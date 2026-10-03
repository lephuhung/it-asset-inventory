"""VQL validator fail-closed (Task 13 — spec F1/R6).

`run_vql` chỉ chạy VQL **phía server**; validator từ chối bất cứ thứ gì không
chứng minh được an toàn. Thiết kế **closed allowlist** — mọi lời gọi (plugin ở
`FROM`, hàm ở projection/predicate/argument/subquery) phải nằm trong allowlist
đã duyệt; mọi từ khóa statement ngoài `SELECT`/`WITH` bị từ chối.

Các lớp phòng thủ:

1. **Một statement, bắt đầu bằng `SELECT`/`WITH`.** Cấm `;`. Cấm `LET`, `SET`,
   DDL/DML, `CALL`, `EXEC`, … ở bất kỳ vị trí nào.
2. **Plugin server-side** (`clients`, `flows`, `hunts`, `labels`, `artifacts`,
   `notebooks`, `info`, `scope`). Artifact client-side (`pslist`, …) không hợp lệ
   trong `run_vql`.
3. **Hàm allowlist đóng** cho projection/predicate/argument/subquery. Hàm
   side-effect (`collect_client`, `collect_artifact`, `file_write`, `yara`, …)
   bị từ chối ở mọi vị trí, kể cả trong `SELECT` và comment-obfuscated.
4. **Không dynamic dispatch** (`eval`, gọi gián tiếp), không `WITH RECURSIVE`.
5. **Trần** timeout/row/byte export cho executor (T15).

Nếu validator không đủ tin cậy, spec F1 cho phép fallback chỉ template cố định;
hiện tại validator là tuyến chính và fail-closed.
"""
from __future__ import annotations

import re

CATEGORY = "chat_guardrail_vql"

# ── Trần (spec F1 item 5 / "Guardrail SQL inventory" — dùng cho executor T15) ──
VQL_STATEMENT_TIMEOUT_MS = 5000
VQL_MAX_ROWS = 5000
VQL_MAX_BYTES = 2 * 1024 * 1024
# Trần kích thước query text — chặn input oversized trước khi tokenize.
VQL_MAX_QUERY_CHARS = 20_000

# Plugin SERVER-SIDE được duyệt (lowercase). Artifact client-side không nằm đây.
SERVER_PLUGINS: frozenset[str] = frozenset(
    {
        "clients",
        "flows",
        "hunts",
        "labels",
        "artifacts",
        "notebooks",
        "info",
        "scope",
    }
)

# Hàm allowlist ĐÓNG (lowercase). Mọi hàm khác bị từ chối.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "count",
        "min",
        "max",
        "sum",
        "avg",
        "coalesce",
        "date_trunc",
        "lower",
        "upper",
        "length",
        "now",
        "if",
        "else",
        "case",
        "when",
        "then",
        "end",
        "str",
        "int",
        "typeof",
    }
)

# Hàm side-effect / dynamic dispatch — từ chối TƯỜNG MINH ở mọi vị trí. (Closed
# allowlist đã từ chối chúng; danh sách này để thông báo lỗi rõ ràng + chặn trước.)
SIDE_EFFECT_FUNCTIONS: frozenset[str] = frozenset(
    {
        "collect_client",
        "collect_artifact",
        "artifact_set",
        "file_write",
        "upload",
        "execve",
        "shell",
        "rm",
        "kill_process",
        "quarantine",
        "yara",
        "eval",
        "exec",
        "execute",
        "system",
        "os_shell",
        "powershell",
        "wmic",
        "reg",
    }
)

# Từ khóa statement ngoài `SELECT`/`WITH` — từ chối ở mọi vị trí.
STATEMENT_DENY: frozenset[str] = frozenset(
    {
        "let",
        "set",
        "insert",
        "update",
        "delete",
        "replace",
        "merge",
        "upsert",
        "drop",
        "create",
        "alter",
        "truncate",
        "grant",
        "revoke",
        "copy",
        "call",
        "exec",
        "execute",
        "attach",
        "detach",
        "pragma",
        "declare",
        "vacuum",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "explain",
    }
)

# Từ khóa kết thúc clause FROM — dùng để biết một lời gọi là plugin (FROM) hay
# hàm (projection/predicate). Reset `in_from` về False.
CLAUSE_RESET: frozenset[str] = frozenset(
    {"select", "where", "group", "order", "limit", "having", "union", "on", "by", "as", "into", "values"}
)

# Từ khóa ngôn ngữ KHÔNG phải lời gọi (dù đứng trước `(`), ví dụ `AND (`, `IN (`,
# `NOT (`, `JOIN (`. Bỏ qua kiểm tra call cho chúng — chúng không thể gây side-effect
# và mọi biểu thức bên trong ngoặc vẫn được validate token-by-token.
NON_CALL_KEYWORDS: frozenset[str] = frozenset(
    {
        "and",
        "or",
        "not",
        "in",
        "exists",
        "any",
        "all",
        "between",
        "like",
        "is",
        "null",
        "true",
        "false",
        "distinct",
        "asc",
        "desc",
        "offset",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "cross",
        "lateral",
        "over",
        "partition",
    }
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_TWO_CHAR_PUNCT = {"<=", ">=", "!=", "<>", "==", "&&", "||", "::", "->", "=>"}
_PUNCT_CHARS = set("()[],.;*=<>!+-/&|%^~{}:")


class VqlPolicyError(ValueError):
    """VQL vi phạm policy fail-closed. Message mang prefix `[chat_guardrail_vql]`."""

    def __init__(self, message: str) -> None:
        super().__init__(f"[{CATEGORY}] {message}")


class _Tok:
    __slots__ = ("kind", "text")

    def __init__(self, kind: str, text: str) -> None:
        self.kind = kind  # "ident" | "string" | "number" | "punct"
        self.text = text


def _tokenize(query: str) -> list[_Tok]:
    """Tokenizer fail-closed: comment bị loại, chuỗi là token mờ (không phân tích)."""
    toks: list[_Tok] = []
    i = 0
    n = len(query)
    while i < n:
        c = query[i]
        if c.isspace():
            i += 1
            continue
        # ── comment ──
        if c == "/" and i + 1 < n and query[i + 1] == "*":
            end = query.find("*/", i + 2)
            if end == -1:
                raise VqlPolicyError("block comment không đóng")
            i = end + 2
            continue
        if (c == "/" and i + 1 < n and query[i + 1] == "/") or (
            c == "-" and i + 1 < n and query[i + 1] == "-"
        ):
            end = query.find("\n", i + 2)
            i = n if end == -1 else end + 1
            continue
        # ── chuỗi / định danh backtick-quoted ──
        if c in ("'", '"', "`"):
            quote = c
            j = i + 1
            buf: list[str] = []
            closed = False
            while j < n:
                ch = query[j]
                if quote != "`" and ch == "\\" and j + 1 < n:
                    buf.append(query[j + 1])
                    j += 2
                    continue
                if ch == quote:
                    if j + 1 < n and query[j + 1] == quote:
                        buf.append(quote)
                        j += 2
                        continue
                    closed = True
                    j += 1
                    break
                buf.append(ch)
                j += 1
            if not closed:
                raise VqlPolicyError("literal không đóng")
            # Backtick = định danh được quote (VQL/SQL) → phải được validate như
            # một tên gọi, KHÔNG được coi là chuỗi mờ (nếu không sẽ tạo bypass
            # `SELECT `collect_client`() ...`).
            kind = "ident" if quote == "`" else "string"
            toks.append(_Tok(kind, "".join(buf)))
            i = j
            continue
        # ── số ──
        if c.isdigit():
            m = _NUMBER_RE.match(query, i)
            assert m is not None
            toks.append(_Tok("number", m.group(0)))
            i = m.end()
            continue
        # ── định danh ──
        m = _IDENT_RE.match(query, i)
        if m is not None:
            toks.append(_Tok("ident", m.group(0)))
            i = m.end()
            continue
        # ── dấu câu / toán tử ──
        two = query[i : i + 2]
        if two in _TWO_CHAR_PUNCT:
            toks.append(_Tok("punct", two))
            i += 2
            continue
        if c in _PUNCT_CHARS:
            toks.append(_Tok("punct", c))
            i += 1
            continue
        raise VqlPolicyError(f"ký tự không hợp lệ trong VQL: {c!r}")
    return toks


def validate_vql(query: str) -> None:
    """Fail-closed: raise `VqlPolicyError` nếu `query` không chứng minh được an toàn.

    Trả `None` khi hợp lệ. Không có suy diễn "có lẽ an toàn" — mọi lời gọi không
    nằm trong allowlist đều bị từ chối.
    """
    if not isinstance(query, str) or not query.strip():
        raise VqlPolicyError("VQL rỗng")
    if len(query) > VQL_MAX_QUERY_CHARS:
        raise VqlPolicyError(
            f"VQL vượt trần {VQL_MAX_QUERY_CHARS} ký tự (byte cap input)"
        )

    toks = _tokenize(query)
    if not toks:
        raise VqlPolicyError("VQL rỗng")

    # ── cấm nhiều statement ──
    for t in toks:
        if t.kind == "punct" and t.text == ";":
            raise VqlPolicyError("cấm nhiều statement (`;`)")

    # ── statement phải bắt đầu bằng SELECT/WITH ──
    first = toks[0]
    if first.kind != "ident" or first.text.lower() not in ("select", "with"):
        raise VqlPolicyError(
            f"statement phải bắt đầu bằng SELECT/WITH, nhận {first.text!r}"
        )

    in_from = False
    for idx, t in enumerate(toks):
        # ── cấm gọi gián tiếp: `(` ngay sau một string literal ──
        if (
            t.kind == "punct"
            and t.text == "("
            and idx > 0
            and toks[idx - 1].kind == "string"
        ):
            raise VqlPolicyError("cấm gọi gián tiếp qua chuỗi")
        if t.kind != "ident":
            continue
        low = t.text.lower()

        if low in STATEMENT_DENY:
            raise VqlPolicyError(f"cấm từ khóa statement: {t.text}")
        if low == "recursive":
            raise VqlPolicyError("cấm WITH RECURSIVE")
        if low == "from":
            in_from = True
            continue
        if low in CLAUSE_RESET:
            in_from = False
            continue
        if low in NON_CALL_KEYWORDS:
            continue

        is_call = (
            idx + 1 < len(toks)
            and toks[idx + 1].kind == "punct"
            and toks[idx + 1].text == "("
        )
        if not is_call:
            continue

        if low in SIDE_EFFECT_FUNCTIONS:
            raise VqlPolicyError(f"cấm hàm side-effect/dynamic: {t.text}")
        if in_from:
            if low not in SERVER_PLUGINS:
                raise VqlPolicyError(f"plugin không nằm trong allowlist server-side: {t.text}")
        else:
            if low not in ALLOWED_FUNCTIONS:
                raise VqlPolicyError(f"hàm không nằm trong allowlist: {t.text}")
