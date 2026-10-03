"""Inventory tools + SQL guardrail (Task 9 — spec F4/R5, V3-4).

Phục vụ tool `inventory` của ChatAgent: định tuyến tới các truy vấn cố định
(tham số hóa) trên 6 view manifest `v_chat_*`, và validate SQL tự do qua một
validator fail-closed.

**Ranh giới thực thi (spec V3-4).** PostgreSQL cấp `PUBLIC` quyền đọc
`pg_catalog`, nên cô lập catalog **không** DB-enforced. Hai tuyến phòng thủ:

1. **DB-enforced:** role `inventory_chat_ro` chỉ có `USAGE` schema `chat_ro_views`
   + `SELECT` 6 view; không quyền bảng gốc (`users`, `audit_log`, `llm_config`, …).
   Đây là tuyến chặn thật cho mọi truy vấn, kể cả khi validator bị vượt.
2. **Validator-enforced (tuyến chính):** `validate_sql` chỉ cho MỘT statement
   `SELECT`/`WITH`; từ chối DML/DDL/`COPY`/`CALL`/`SET`/…; từ chối tham chiếu
   `pg_catalog`/`information_schema`/`pg_*`; từ chối bảng ngoài manifest; function
   registry đóng.

**Trần (spec "Guardrail SQL inventory"):** `statement_timeout=5000ms`, row cap
5000, byte cap 2MB — vượt → `truncated` (cắt) hoặc từ chối (timeout).

**Audit:** SQL audit = `sha256(normalized_sql)`, không raw. Caller (T10) ghi audit
với digest này.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# ── Trần (spec "Guardrail SQL inventory") ────────────────────────────────────
SQL_STATEMENT_TIMEOUT_MS = 5000
SQL_MAX_ROWS = 5000
SQL_MAX_BYTES = 2 * 1024 * 1024

CATEGORY = "chat_guardrail_sql"

# Manifest view/cột (đóng) — khớp migration T3 `e3f4a5b6c7d8_chat_ro_views.py`.
MANIFEST_VIEWS: dict[str, frozenset[str]] = {
    "v_chat_machines": frozenset(
        {"id", "hostname", "org_name", "os_name", "os_version", "status",
         "last_seen", "eol_flag"}
    ),
    "v_chat_machine_detail": frozenset(
        {"id", "hostname", "org_name", "os_name", "os_version", "cpu", "ram_mb",
         "disk_gb", "status", "last_seen"}
    ),
    "v_chat_org_stats": frozenset(
        {"org_name", "machine_count", "online_count", "eol_count"}
    ),
    "v_chat_software": frozenset(
        {"machine_id", "hostname", "software_name", "version", "install_date"}
    ),
    "v_chat_hardware": frozenset({"machine_id", "hostname", "component", "value"}),
    "v_chat_alerts": frozenset(
        {"id", "machine_id", "hostname", "severity", "category", "created_at", "status"}
    ),
}

ALLOWED_SCHEMA = "chat_ro_views"

# Function registry đóng (spec V3-4). Chỉ hàm projection/predicate thuần.
FUNCTION_REGISTRY = frozenset(
    {"count", "min", "max", "sum", "avg", "coalesce", "date_trunc",
     "lower", "upper", "length", "now"}
)

# Từ khóa SQL hợp lệ (không phải function call khi theo sau là `(`).
KEYWORDS = frozenset({
    "select", "from", "where", "group", "by", "having", "order", "limit",
    "offset", "as", "and", "or", "not", "is", "null", "in", "between", "like",
    "ilike", "distinct", "on", "join", "left", "right", "inner", "outer",
    "full", "cross", "union", "all", "case", "when", "then", "else", "end",
    "cast", "asc", "desc", "true", "false", "lateral", "over", "partition",
    "nulls", "first", "last", "filter", "exists", "any", "some", "with",
    "fetch", "for", "using", "natural", "text", "integer", "int", "bigint",
    "smallint", "boolean", "uuid", "timestamp", "timestamptz", "date",
    "numeric", "real", "double", "precision", "varchar", "char", "interval",
    "json", "jsonb", "materialized",
})

# Câu lệnh/động từ bị cấm (mọi vị trí).
FORBIDDEN_KEYWORDS = frozenset({
    "insert", "update", "delete", "drop", "create", "alter", "truncate",
    "grant", "revoke", "copy", "call", "set", "reset", "explain", "vacuum",
    "analyze", "commit", "rollback", "begin", "do", "merge", "refresh",
    "reindex", "cluster", "listen", "notify", "lock", "execute", "prepare",
    "deallocate", "comment", "into", "values", "start", "transaction",
    "declare",
})

# Từ khóa kết thúc danh sách FROM.
_CLAUSE_ENDERS = frozenset(
    {"where", "group", "order", "having", "limit", "offset", "union", "on",
     "window", "fetch", "for"}
)

_FORBIDDEN_SCHEMAS = frozenset({"pg_catalog", "information_schema"})


class SqlGuardrailError(ValueError):
    """Vi phạm guardrail SQL / tool. Prefix `[chat_guardrail_sql]`, HTTP 400."""

    CATEGORY = CATEGORY
    HTTP_STATUS = 400

    def __init__(self, hint: str, http_status: int = 400) -> None:
        self.hint = hint
        self.http_status = http_status
        super().__init__(f"[{CATEGORY}] {hint} [HTTP {http_status}]")


@dataclass(frozen=True)
class ToolResult:
    """Kết quả một tool inventory.

    `rows` là list dict (chỉ cột thuộc manifest view). `sql_digest` =
    `sha256(normalized_sql)` để ghi audit (không log raw SQL).
    """

    tool: str
    ok: bool = True
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    byte_count: int = 0
    sql_digest: str = ""
    error_category: str | None = None


# ── Tokenizer ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Tok:
    kind: str  # ident | qident | string | number | bind | op
    value: str


def _tokenize(sql: str) -> list[_Tok]:
    """Tách token, bỏ comment, cấm `$`/dollar-quote và literal chưa đóng."""
    toks: list[_Tok] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if sql.startswith("/*", i):
            j, depth = i + 2, 1
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth:
                raise SqlGuardrailError("comment khối không đóng")
            i = j
            continue
        if c == "'":
            j, buf = i + 1, ["'"]
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("''")
                        j += 2
                        continue
                    buf.append("'")
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            else:
                raise SqlGuardrailError("string literal không đóng")
            toks.append(_Tok("string", "".join(buf)))
            i = j
            continue
        if c == '"':
            j, buf = i + 1, ['"']
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        buf.append('""')
                        j += 2
                        continue
                    buf.append('"')
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            else:
                raise SqlGuardrailError("quoted identifier không đóng")
            inner = "".join(buf)[1:-1].replace('""', '"')
            toks.append(_Tok("qident", inner))
            i = j
            continue
        if c == "$":
            raise SqlGuardrailError("ký tự '$' bị cấm (dollar-quote/parameter)")
        if c.isalpha() or c == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            toks.append(_Tok("ident", sql[i:j]))
            i = j
            continue
        if c.isdigit():
            j = i
            while j < n and (sql[j].isdigit() or sql[j] == "."):
                j += 1
            toks.append(_Tok("number", sql[i:j]))
            i = j
            continue
        if c == ":":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j == i + 1:
                toks.append(_Tok("op", ":"))
                i += 1
                continue
            toks.append(_Tok("bind", sql[i + 1:j]))
            i = j
            continue
        toks.append(_Tok("op", c))
        i += 1
    return toks


def _check_identifier(value: str) -> None:
    low = value.lower()
    if low in _FORBIDDEN_SCHEMAS or low.startswith("pg_"):
        raise SqlGuardrailError(f"tham chiếu catalog hệ thống bị cấm: {value!r}")


def _collect_cte_names(toks: list[_Tok]) -> frozenset[str]:
    """Thu tên CTE của preamble `WITH [RECURSIVE] name [ (cols) ] AS (...) [, ...]`."""
    names: set[str] = set()
    i = 0
    if not toks or toks[0].kind != "ident" or toks[0].value.lower() != "with":
        return frozenset()
    i = 1
    if i < len(toks) and toks[i].kind == "ident" and toks[i].value.lower() == "recursive":
        raise SqlGuardrailError("WITH RECURSIVE bị cấm")
    while i < len(toks):
        if toks[i].kind != "ident":
            raise SqlGuardrailError("cú pháp CTE không hợp lệ")
        names.add(toks[i].value.lower())
        i += 1
        if i < len(toks) and toks[i].value == "(":
            i = _skip_balanced(toks, i)
        if not (i < len(toks) and toks[i].kind == "ident"
                and toks[i].value.lower() == "as"):
            raise SqlGuardrailError("CTE thiếu AS")
        i += 1
        while (i < len(toks) and toks[i].kind == "ident"
               and toks[i].value.lower() in ("materialized", "not")):
            i += 1
        if not (i < len(toks) and toks[i].value == "("):
            raise SqlGuardrailError("CTE thiếu thân truy vấn")
        i = _skip_balanced(toks, i)
        if i < len(toks) and toks[i].value == ",":
            i += 1
            continue
        break
    return frozenset(names)


def _skip_balanced(toks: list[_Tok], i: int) -> int:
    """`toks[i]` là '('; trả index sau ')' khớp. Raise nếu không đóng."""
    depth = 0
    while i < len(toks):
        if toks[i].value == "(":
            depth += 1
        elif toks[i].value == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise SqlGuardrailError("ngoặc không đóng")


def _check_table(schema: str | None, table: str, cte_names: frozenset[str]) -> None:
    low = table.lower()
    if schema is not None:
        if schema.lower() != ALLOWED_SCHEMA:
            raise SqlGuardrailError(f"schema ngoài manifest bị cấm: {schema!r}")
        if low not in MANIFEST_VIEWS:
            raise SqlGuardrailError(f"bảng ngoài manifest bị cấm: {ALLOWED_SCHEMA}.{low}")
        return
    if low in MANIFEST_VIEWS:
        return
    # `pg_*`/`information_schema` đã bị chặn ở _check_identifier.
    if low in cte_names:
        return
    raise SqlGuardrailError(f"bảng ngoài manifest bị cấm: {low}")


def _normalize(toks: list[_Tok]) -> str:
    parts = []
    for t in toks:
        if t.kind == "qident":
            parts.append('"' + t.value + '"')
        elif t.kind == "ident":
            parts.append(t.value.lower())
        elif t.kind == "bind":
            parts.append(":" + t.value)
        else:
            parts.append(t.value)
    return " ".join(parts)


def validate_sql(sql: str) -> str:
    """Validate + normalize SQL. Raise `SqlGuardrailError` nếu vi phạm.

    Trả chuỗi normalized (lowercase ident, một khoảng trắng) để tính digest audit.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SqlGuardrailError("SQL rỗng")
    toks = _tokenize(sql)
    if not toks:
        raise SqlGuardrailError("SQL rỗng")

    for t in toks:
        if t.kind == "op" and t.value == ";":
            raise SqlGuardrailError("chỉ cho phép một statement (cấm ';')")

    first = toks[0]
    if not (first.kind == "ident" and first.value.lower() in ("select", "with")):
        raise SqlGuardrailError("chỉ cho phép SELECT/WITH")

    cte_names = _collect_cte_names(toks)

    # 1) Kiểm tra mọi identifier (catalog/pg_*) + keyword bị cấm. Áp cho cả
    #    quoted identifier (`"pg_catalog"`, `"users"`).
    for t in toks:
        if t.kind in ("ident", "qident"):
            low = t.value.lower()
            _check_identifier(t.value)
            if t.kind == "ident" and low in FORBIDDEN_KEYWORDS:
                raise SqlGuardrailError(f"từ khóa bị cấm: {low!r}")

    # 2) Function registry đóng: ident theo sau '(' và không phải keyword. Quoted
    #    identifier gọi hàm (`"md5"(...)`) bị từ chối thẳng (fail closed).
    for idx, t in enumerate(toks[:-1]):
        if t.kind not in ("ident", "qident"):
            continue
        if toks[idx + 1].kind != "op" or toks[idx + 1].value != "(":
            continue
        low = t.value.lower()
        if t.kind == "qident":
            raise SqlGuardrailError(f"gọi hàm bằng quoted identifier bị cấm: {t.value!r}")
        if low in KEYWORDS:
            continue
        if low not in FUNCTION_REGISTRY:
            raise SqlGuardrailError(f"function ngoài registry bị cấm: {low!r}")

    # 3) Bảng trong FROM/JOIN phải thuộc manifest (hoặc là CTE).
    i, depth = 0, 0
    expect_table = False
    in_from = False
    while i < len(toks):
        t = toks[i]
        if t.kind == "op" and t.value == "(":
            depth += 1
            i += 1
            continue
        if t.kind == "op" and t.value == ")":
            depth -= 1
            i += 1
            continue
        low = t.value.lower() if t.kind == "ident" else None
        if expect_table:
            if t.kind == "op" and t.value == "(":
                expect_table = False
                i += 1
                continue
            if t.kind == "ident":
                schema = None
                table = low
                if (i + 2 < len(toks) and toks[i + 1].kind == "op"
                        and toks[i + 1].value == "."
                        and toks[i + 2].kind == "ident"):
                    schema = low
                    table = toks[i + 2].value.lower()
                    i += 3
                else:
                    i += 1
                _check_table(schema, table, cte_names)
                expect_table = False
                continue
            raise SqlGuardrailError("cú pháp FROM/JOIN không hợp lệ")
        if low in ("from", "join"):
            expect_table = True
            in_from = True
            i += 1
            continue
        if low in _CLAUSE_ENDERS:
            in_from = False
            i += 1
            continue
        if t.kind == "op" and t.value == "," and depth == 0 and in_from:
            expect_table = True
            i += 1
            continue
        i += 1

    return _normalize(toks)


def _digest(normalized_sql: str) -> str:
    return hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()


# ── Executor (read-only + caps) ──────────────────────────────────────────────

async def _execute_readonly(
    session: AsyncSession,
    sql: str,
    *,
    params: Mapping[str, object] | None = None,
    timeout_ms: int = SQL_STATEMENT_TIMEOUT_MS,
    max_rows: int = SQL_MAX_ROWS,
    wrap: bool = True,
) -> tuple[list[dict], bool, int]:
    """Chạy `sql` read-only, enforce `statement_timeout` + row/byte cap.

    Trả `(rows, truncated, byte_count)`. Raise `SqlGuardrailError` khi DB lỗi
    (gồm timeout). Không validate ở đây — caller đã validate.
    """
    exec_sql = sql
    if wrap:
        exec_sql = f"SELECT * FROM (\n{sql}\n) AS _chat_guard LIMIT {int(max_rows) + 1}"
    binds = dict(params or {})

    owns_tx = not session.in_transaction()
    if owns_tx:
        await session.begin()
    try:
        if owns_tx:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        result = await session.execute(text(exec_sql), binds)
        raw = result.mappings().all()
    except SQLAlchemyError as exc:
        if owns_tx:
            await session.rollback()
        raise SqlGuardrailError(
            f"truy vấn inventory thất bại ({type(exc).__name__})"
        ) from exc
    if owns_tx:
        await session.commit()

    rows = [dict(r) for r in raw]
    truncated = False
    if len(rows) > max_rows:
        rows = rows[:max_rows]
        truncated = True

    kept: list[dict] = []
    total = 0
    for r in rows:
        size = len(json.dumps(r, ensure_ascii=False, default=str).encode("utf-8"))
        if total + size > SQL_MAX_BYTES:
            truncated = True
            break
        kept.append(r)
        total += size
    return kept, truncated, total


# ── Tool builders (manifest, tham số hóa) ────────────────────────────────────

def _clamp_limit(params: Mapping[str, object], default: int = 50) -> int:
    raw = params.get("limit", default)
    if raw is None:
        raw = default
    try:
        val = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise SqlGuardrailError("tham số limit không hợp lệ")
    if val < 1:
        raise SqlGuardrailError("limit phải >= 1")
    return min(val, SQL_MAX_ROWS)


def _machine_id_param(params: Mapping[str, object]) -> str:
    val = params.get("machine_id")
    if val is None:
        raise SqlGuardrailError("thiếu tham số machine_id")
    try:
        return str(uuid.UUID(str(val)))
    except (ValueError, AttributeError, TypeError):
        raise SqlGuardrailError("machine_id không phải UUID hợp lệ")


def _hostname_param(params: Mapping[str, object], key: str = "hostname") -> str:
    val = params.get(key)
    if not isinstance(val, str) or not val.strip():
        raise SqlGuardrailError(f"thiếu/không hợp lệ tham số {key}")
    return val


def _str_param(params: Mapping[str, object], key: str) -> str | None:
    val = params.get(key)
    if val is None:
        return None
    if not isinstance(val, str):
        raise SqlGuardrailError(f"tham số {key} không hợp lệ")
    return val


def _build_search(params: Mapping[str, object]) -> tuple[str, dict]:
    cols = "id, hostname, org_name, os_name, os_version, status, last_seen, eol_flag"
    limit = _clamp_limit(params)
    q = _str_param(params, "q")
    if q:
        sql = (
            f"SELECT {cols} FROM v_chat_machines "
            "WHERE hostname ILIKE :like OR org_name ILIKE :like "
            "ORDER BY last_seen DESC NULLS LAST LIMIT :limit"
        )
        return sql, {"like": f"%{q}%", "limit": limit}
    sql = (
        f"SELECT {cols} FROM v_chat_machines "
        "ORDER BY last_seen DESC NULLS LAST LIMIT :limit"
    )
    return sql, {"limit": limit}


def _build_machine_detail(params: Mapping[str, object]) -> tuple[str, dict]:
    cols = ("id, hostname, org_name, os_name, os_version, cpu, ram_mb, disk_gb, "
            "status, last_seen")
    if params.get("machine_id") is not None:
        sql = (
            f"SELECT {cols} FROM v_chat_machine_detail "
            "WHERE id = CAST(:machine_id AS uuid) LIMIT 1"
        )
        return sql, {"machine_id": _machine_id_param(params)}
    sql = f"SELECT {cols} FROM v_chat_machine_detail WHERE hostname = :hostname LIMIT 1"
    return sql, {"hostname": _hostname_param(params)}


def _build_resolve(params: Mapping[str, object]) -> tuple[str, dict]:
    sql = (
        "SELECT id, hostname, status, last_seen FROM v_chat_machines "
        "WHERE lower(hostname) = lower(:hostname) "
        "ORDER BY last_seen DESC NULLS LAST LIMIT :limit"
    )
    return sql, {
        "hostname": _hostname_param(params),
        "limit": _clamp_limit(params, default=10),
    }


def _build_stats(params: Mapping[str, object]) -> tuple[str, dict]:
    base = "SELECT org_name, machine_count, online_count, eol_count FROM v_chat_org_stats"
    limit = _clamp_limit(params, default=100)
    q = _str_param(params, "org_name")
    if q:
        sql = base + " WHERE org_name ILIKE :like ORDER BY machine_count DESC LIMIT :limit"
        return sql, {"like": f"%{q}%", "limit": limit}
    return base + " ORDER BY machine_count DESC LIMIT :limit", {"limit": limit}


def _build_software(params: Mapping[str, object]) -> tuple[str, dict]:
    limit = _clamp_limit(params, default=200)
    conds: list[str] = []
    binds: dict = {"limit": limit}
    if params.get("machine_id") is not None:
        conds.append("machine_id = CAST(:machine_id AS uuid)")
        binds["machine_id"] = _machine_id_param(params)
    else:
        conds.append("hostname = :hostname")
        binds["hostname"] = _hostname_param(params)
    name = _str_param(params, "name")
    if name:
        conds.append("software_name ILIKE :name_like")
        binds["name_like"] = f"%{name}%"
    where = " AND ".join(conds)
    sql = (
        "SELECT machine_id, hostname, software_name, version, install_date "
        f"FROM v_chat_software WHERE {where} ORDER BY software_name LIMIT :limit"
    )
    return sql, binds


def _build_hardware(params: Mapping[str, object]) -> tuple[str, dict]:
    limit = _clamp_limit(params, default=200)
    conds: list[str] = []
    binds: dict = {"limit": limit}
    if params.get("machine_id") is not None:
        conds.append("machine_id = CAST(:machine_id AS uuid)")
        binds["machine_id"] = _machine_id_param(params)
    else:
        conds.append("hostname = :hostname")
        binds["hostname"] = _hostname_param(params)
    component = _str_param(params, "component")
    if component:
        conds.append("component = :component")
        binds["component"] = component
    where = " AND ".join(conds)
    sql = (
        "SELECT machine_id, hostname, component, value "
        f"FROM v_chat_hardware WHERE {where} ORDER BY component LIMIT :limit"
    )
    return sql, binds


def _build_alerts(params: Mapping[str, object]) -> tuple[str, dict]:
    limit = _clamp_limit(params, default=200)
    conds: list[str] = []
    binds: dict = {"limit": limit}
    if params.get("machine_id") is not None:
        conds.append("machine_id = CAST(:machine_id AS uuid)")
        binds["machine_id"] = _machine_id_param(params)
    elif params.get("hostname") is not None:
        conds.append("hostname = :hostname")
        binds["hostname"] = _hostname_param(params)
    severity = _str_param(params, "severity")
    if severity:
        conds.append("severity = :severity")
        binds["severity"] = severity
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = (
        "SELECT id, machine_id, hostname, severity, category, created_at, status "
        f"FROM v_chat_alerts{where} ORDER BY created_at DESC NULLS LAST LIMIT :limit"
    )
    return sql, binds


STRUCTURED_TOOLS: dict[str, object] = {
    "inventory_search": _build_search,
    "inventory_machine_detail": _build_machine_detail,
    "inventory_resolve_machine": _build_resolve,
    "inventory_stats": _build_stats,
    "inventory_software": _build_software,
    "inventory_hardware": _build_hardware,
    "inventory_alerts": _build_alerts,
}

ALL_TOOLS = frozenset(STRUCTURED_TOOLS) | {"inventory_sql"}


async def run_tool(
    session: AsyncSession, tool: str, params: Mapping[str, object] | None = None
) -> ToolResult:
    """Chạy một tool inventory trong manifest. Raise `SqlGuardrailError` nếu vi phạm.

    `session` PHẢI là session pool `chat_ro` (role `inventory_chat_ro`) — caller
    (T10) mở từ `get_chat_ro_session`/`AsyncChatRoSessionLocal`.
    """
    params = params or {}
    if tool not in ALL_TOOLS:
        raise SqlGuardrailError(f"tool ngoài allowlist: {tool!r}")
    if tool == "inventory_sql":
        sql = _str_param(params, "sql")
        if not sql:
            raise SqlGuardrailError("thiếu tham số sql")
        return await run_sql(session, sql, max_rows=SQL_MAX_ROWS)

    builder = STRUCTURED_TOOLS[tool]
    raw_sql, binds = builder(params)  # type: ignore[operator]
    normalized = validate_sql(raw_sql)  # self-check: template không được trôi khỏi manifest
    rows, truncated, byte_count = await _execute_readonly(
        session, raw_sql, params=binds, timeout_ms=SQL_STATEMENT_TIMEOUT_MS,
        max_rows=SQL_MAX_ROWS, wrap=True,
    )
    return ToolResult(
        tool=tool, ok=True, rows=rows, row_count=len(rows), truncated=truncated,
        byte_count=byte_count, sql_digest=_digest(normalized),
    )


async def run_sql(
    session: AsyncSession, sql: str, max_rows: int = SQL_MAX_ROWS
) -> ToolResult:
    """Validate SQL tự do rồi chạy read-only trên pool `chat_ro`.

    `session` PHẢI là session pool `chat_ro` (role `inventory_chat_ro`).
    """
    normalized = validate_sql(sql)
    rows, truncated, byte_count = await _execute_readonly(
        session, normalized, timeout_ms=SQL_STATEMENT_TIMEOUT_MS, max_rows=max_rows,
        wrap=True,
    )
    return ToolResult(
        tool="inventory_sql", ok=True, rows=rows, row_count=len(rows),
        truncated=truncated, byte_count=byte_count, sql_digest=_digest(normalized),
    )
