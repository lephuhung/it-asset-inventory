"""Task 9 — inventory tools + SQL guardrail service.

Test dùng **role thật** `inventory_chat_ro` (spec V3-4, không dùng app pool):
role chỉ SELECT 6 view manifest; validator SQL (T9) là tuyến chính chặn
DML/DDL/multi-statement/catalog/function ngoài registry.
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid
from importlib import util
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import pool as sa_pool
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import session as session_module
from app.services import chat_inventory as ci
from app.services.chat_inventory import (
    MANIFEST_VIEWS,
    SqlGuardrailError,
    ToolResult,
    run_sql,
    run_tool,
    validate_sql,
)

CHAT_RO_TEST_PASSWORD = "chat_ro_test_pw"
_MIGRATION_FILE = "e3f4a5b6c7d8_chat_ro_views.py"

PII_NAMES = {"email", "phone", "id_number", "password_hash", "full_name",
             "phone_encrypted", "address"}


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions" / _MIGRATION_FILE
    spec = util.spec_from_file_location("chat_ro_views_migration", path)
    mod = util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _chat_ro_test_url() -> str:
    host = os.environ.get("POSTGRES_TEST_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_TEST_PORT", "5432")
    db = os.environ.get("POSTGRES_TEST_DB", "inventory_test")
    return (
        f"postgresql+asyncpg://inventory_chat_ro:{CHAT_RO_TEST_PASSWORD}"
        f"@{host}:{port}/{db}"
    )


@pytest_asyncio.fixture
async def chat_ro_engine(db_engine):
    """Tạo role + schema + view thật; trả engine chat_ro (role hạn chế)."""
    mig = _load_migration()
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))
        for stmt in mig.ROLE_HARDEN_DDL:
            await conn.exec_driver_sql(stmt)
        await conn.exec_driver_sql(mig.SCHEMA_DDL)
        for stmt in mig.VIEW_DDL:
            await conn.exec_driver_sql(stmt)
        for stmt in mig.GRANT_DDL:
            await conn.exec_driver_sql(stmt)

    engine = session_module.create_chat_ro_engine(
        _chat_ro_test_url(), poolclass=sa_pool.NullPool
    )
    yield engine
    await engine.dispose()
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("DROP SCHEMA IF EXISTS chat_ro_views CASCADE")


@pytest_asyncio.fixture
async def chat_ro_factory(chat_ro_engine):
    return async_sessionmaker(chat_ro_engine, expire_on_commit=False)


async def _seed_machine(db, *, hostname="WS-01", os_name="Windows 10 Pro",
                        os_version="10.0.19045", os_build=None, status="online",
                        org=None, cpu=None, ram_gb=None, disks=None):
    """Seed org (nếu cần) + machine + machine_current qua app pool. Trả (org, machine)."""
    from datetime import UTC, datetime

    from app.db.models import Machine, MachineCurrent, Organization, OrgType

    if org is None:
        org = Organization(id=uuid.uuid4(), name=f"Org-{uuid.uuid4().hex[:6]}",
                           type=OrgType.DON_VI.value)
        db.add(org)
        await db.flush()
    machine = Machine(
        id=uuid.uuid4(), org_id=org.id, machine_uuid=uuid.uuid4().hex,
        hostname=hostname, status=status, last_seen_at=datetime.now(UTC),
    )
    db.add(machine)
    await db.flush()
    db.add(MachineCurrent(
        machine_id=machine.id, collected_at=datetime.now(UTC),
        os_name=os_name, os_version=os_version, os_build=os_build,
        cpu=cpu, ram_gb=ram_gb, disks=disks,
    ))
    await db.flush()
    return org, machine


# ── validate_sql: statement shape ────────────────────────────────────────────

def test_validate_sql_accepts_manifest_select():
    normalized = validate_sql(
        "SELECT id, hostname FROM v_chat_machines WHERE status = 'online'"
    )
    assert "v_chat_machines" in normalized
    assert normalized == normalized.lower() or "SELECT" in normalized


@pytest.mark.parametrize("sql", [
    "INSERT INTO v_chat_machines (hostname) VALUES ('x')",
    "UPDATE v_chat_machines SET hostname = 'x'",
    "DELETE FROM v_chat_machines",
    "DROP TABLE v_chat_machines",
    "ALTER TABLE v_chat_machines ADD COLUMN x int",
    "CREATE TABLE x (id int)",
    "TRUNCATE v_chat_machines",
    "GRANT SELECT ON v_chat_machines TO PUBLIC",
    "COPY v_chat_machines TO STDOUT",
    "CALL some_proc()",
    "SET search_path TO public",
    "EXPLAIN SELECT 1",
    "SELECT 1 INTO x",
    "VACUUM",
])
def test_validate_sql_rejects_dml_ddl_and_other_statements(sql):
    with pytest.raises(SqlGuardrailError):
        validate_sql(sql)


def test_validate_sql_rejects_multi_statement():
    with pytest.raises(SqlGuardrailError):
        validate_sql("SELECT 1; SELECT 2")
    with pytest.raises(SqlGuardrailError):
        validate_sql("SELECT 1;")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM users",
    "SELECT email FROM public.users",
    "SELECT * FROM public.audit_log",
    "SELECT * FROM public.llm_config",
    "SELECT * FROM public.api_keys",
    "SELECT * FROM public.heartbeats_20261003",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM pg_class",
    "SELECT * FROM pg_stat_activity",
])
def test_validate_sql_rejects_denylist_and_catalog(sql):
    """Bỏ allowlist bảng: chỉ chặn denylist (bí mật/log) + system catalog."""
    with pytest.raises(SqlGuardrailError):
        validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM machines",
    "SELECT * FROM public.machines",
    "SELECT * FROM v_chat_machines",
    (
        "SELECT m.hostname FROM public.machines m "
        "JOIN public.organizations o ON o.id = m.org_id"
    ),
    "SELECT * FROM public.machine_current",
    "SELECT * FROM public.system_profiles",
])
def test_validate_sql_accepts_base_tables(sql):
    """Text-to-SQL: bảng gốc nghiệp vụ (ngoài denylist) được phép query."""
    assert validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT pg_sleep(1)",
    "SELECT dblink_connect('x')",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT current_setting('data_directory')",
    "SELECT nextval('x')",
    # quoted-identifier bypass
    'SELECT "md5"(\'x\')',
    'SELECT "pg_sleep"(1)',
])
def test_validate_sql_rejects_forbidden_functions(sql):
    with pytest.raises(SqlGuardrailError):
        validate_sql(sql)


@pytest.mark.parametrize("sql", [
    'SELECT * FROM "users"',
    'SELECT * FROM "pg_catalog"."pg_class"',
])
def test_validate_sql_rejects_quoted_identifier_smuggling(sql):
    with pytest.raises(SqlGuardrailError):
        validate_sql(sql)


def test_validate_sql_accepts_common_functions():
    validate_sql(
        "SELECT count(*), lower(hostname), upper(org_name), length(hostname), "
        "coalesce(os_name, ''), min(last_seen), max(last_seen), now() "
        "FROM v_chat_machines"
    )
    validate_sql(
        "SELECT date_trunc('day', created_at), sum(ram_mb), avg(ram_mb) "
        "FROM v_chat_machine_detail"
    )
    # Hàm ngoài registry cũ nhưng an toàn → được phép.
    validate_sql("SELECT round(avg(ram_gb), 1), md5(hostname) FROM public.machine_specs")


def test_validate_sql_accepts_cte_over_manifest_view():
    validate_sql(
        "WITH online AS (SELECT id FROM v_chat_machines WHERE status = 'online') "
        "SELECT count(*) FROM online"
    )


def test_validate_sql_rejects_recursive_cte():
    with pytest.raises(SqlGuardrailError):
        validate_sql(
            "WITH RECURSIVE t AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM t) "
            "SELECT * FROM t"
        )


def test_validate_sql_rejects_comment_and_dollar_obfuscation():
    with pytest.raises(SqlGuardrailError):
        validate_sql("SELECT/**/ * FROM users")
    with pytest.raises(SqlGuardrailError):
        validate_sql("SELECT $$x$$")


def test_validate_sql_normalizes_whitespace_and_case():
    a = validate_sql("SELECT   id ,  hostname   FROM   v_chat_machines")
    b = validate_sql("select id, hostname from v_chat_machines")
    assert a == b
    assert "  " not in a


def test_validate_sql_rejects_alias_smuggling_pii_source():
    # Không thể lấy PII bằng cách alias bảng nhạy cảm.
    with pytest.raises(SqlGuardrailError):
        validate_sql("SELECT u.email AS hostname FROM users u")


# ── run_sql ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_sql_returns_rows_and_digest(db, chat_ro_factory):
    await _seed_machine(db, hostname="WS-SQL")
    await db.commit()

    sql = "SELECT hostname FROM v_chat_machines WHERE hostname = 'WS-SQL'"
    async with chat_ro_factory() as s:
        result = await run_sql(s, sql, max_rows=100)

    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.row_count == 1
    assert result.rows[0]["hostname"] == "WS-SQL"
    expected = hashlib.sha256(validate_sql(sql).encode("utf-8")).hexdigest()
    assert result.sql_digest == expected


@pytest.mark.asyncio
async def test_run_sql_surfaces_db_error_detail(chat_ro_factory):
    """Lỗi DB (vd cột không tồn tại) phải lộ message ngắn để model tự sửa SQL."""
    async with chat_ro_factory() as s:
        with pytest.raises(SqlGuardrailError) as exc:
            await run_sql(s, "SELECT khong_ton_tai FROM v_chat_machines")
    assert "khong_ton_tai" in str(exc.value)


async def test_run_sql_rejects_dml(db, chat_ro_factory):
    async with chat_ro_factory() as s:
        with pytest.raises(SqlGuardrailError):
            await run_sql(s, "DELETE FROM v_chat_machines", max_rows=10)


@pytest.mark.asyncio
async def test_run_sql_enforces_row_cap(db, chat_ro_factory):
    for i in range(3):
        await _seed_machine(db, hostname=f"CAP-{i}")
    await db.commit()

    async with chat_ro_factory() as s:
        result = await run_sql(s, "SELECT hostname FROM v_chat_machines", max_rows=2)
    assert result.row_count == 2
    assert result.truncated is True


@pytest.mark.asyncio
async def test_run_sql_enforces_byte_cap(db, chat_ro_factory, monkeypatch):
    for i in range(3):
        await _seed_machine(db, hostname=f"BYTE-{i}-" + "x" * 50)
    await db.commit()

    monkeypatch.setattr(ci, "SQL_MAX_BYTES", 80)
    async with chat_ro_factory() as s:
        result = await run_sql(s, "SELECT hostname FROM v_chat_machines", max_rows=100)
    assert result.truncated is True
    assert result.byte_count <= 80
    assert result.row_count < 3


@pytest.mark.asyncio
async def test_execute_readonly_enforces_statement_timeout(chat_ro_factory):
    """statement_timeout DB-enforced (spec "Trần"). Gọi executor thô để test."""
    async with chat_ro_factory() as s:
        with pytest.raises(SqlGuardrailError):
            await ci._execute_readonly(
                s, "SELECT pg_sleep(2)", params=None,
                timeout_ms=50, max_rows=10, wrap=False,
            )


# ── run_tool ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_tool_unknown_tool_rejected(chat_ro_factory):
    async with chat_ro_factory() as s:
        with pytest.raises(SqlGuardrailError):
            await run_tool(s, "not_in_allowlist", {})


@pytest.mark.asyncio
async def test_run_tool_search_returns_manifest_rows(db, chat_ro_factory):
    await _seed_machine(db, hostname="SEARCH-ME", org=None)
    await _seed_machine(db, hostname="OTHER")
    await db.commit()

    async with chat_ro_factory() as s:
        result = await run_tool(s, "inventory_search", {"q": "SEARCH-ME"})
    assert result.ok is True
    assert result.tool == "inventory_search"
    assert {r["hostname"] for r in result.rows} == {"SEARCH-ME"}
    assert set(result.rows[0]).issubset(MANIFEST_VIEWS["v_chat_machines"])
    assert not (PII_NAMES & set(result.rows[0]))


@pytest.mark.asyncio
async def test_run_tool_machine_detail(db, chat_ro_factory):
    _, machine = await _seed_machine(
        db, hostname="DETAIL-1", cpu={"model": "Intel i7"}, ram_gb=16.0,
        disks=[{"size_bytes": 500 * 1024**3}],
    )
    await db.commit()

    async with chat_ro_factory() as s:
        result = await run_tool(s, "inventory_machine_detail",
                                {"machine_id": str(machine.id)})
    assert result.row_count == 1
    row = result.rows[0]
    assert row["hostname"] == "DETAIL-1"
    assert row["cpu"] == "Intel i7"
    assert row["ram_mb"] == 16 * 1024
    assert row["disk_gb"] == 500


@pytest.mark.asyncio
async def test_run_tool_resolve_machine(db, chat_ro_factory):
    await _seed_machine(db, hostname="Resolve-Me")
    await db.commit()
    async with chat_ro_factory() as s:
        result = await run_tool(s, "inventory_resolve_machine",
                                {"hostname": "resolve-me"})
    assert result.row_count == 1
    assert result.rows[0]["hostname"] == "Resolve-Me"


@pytest.mark.asyncio
async def test_run_tool_stats(db, chat_ro_factory):
    org = None
    for i in range(2):
        org, _ = await _seed_machine(db, hostname=f"STAT-{i}", org=org)
    await db.commit()
    async with chat_ro_factory() as s:
        result = await run_tool(s, "inventory_stats", {})
    assert result.row_count >= 1
    assert {"org_name", "machine_count", "online_count", "eol_count"} == set(
        result.rows[0]
    )


@pytest.mark.asyncio
async def test_run_tool_software_and_hardware_and_alerts(db, chat_ro_factory):
    from datetime import UTC, datetime

    from app.db.models import DfirAlert, MachineSoftware

    _, machine = await _seed_machine(db, hostname="SW-HW", cpu={"brand": "AMD"})
    db.add(MachineSoftware(machine_id=machine.id, name="7-Zip", version="23.01",
                           install_date="2024-01-15"))
    db.add(DfirAlert(id=uuid.uuid4(), artifact_pattern="Persistence", severity="critical",
                     flow_id="F.1", machine_id=machine.id, message="m", resolved=False,
                     created_at=datetime.now(UTC)))
    await db.commit()

    mid = str(machine.id)
    async with chat_ro_factory() as s:
        sw = await run_tool(s, "inventory_software", {"machine_id": mid})
        hw = await run_tool(s, "inventory_hardware", {"machine_id": mid})
        al = await run_tool(s, "inventory_alerts", {"machine_id": mid})

    assert {r["software_name"] for r in sw.rows} == {"7-Zip"}
    assert any(r["component"] == "cpu" and r["value"] == "AMD" for r in hw.rows)
    assert al.row_count == 1
    assert al.rows[0]["severity"] == "critical"
    assert al.rows[0]["category"] == "dfir"
    assert al.rows[0]["status"] == "open"


@pytest.mark.asyncio
async def test_run_tool_inventory_sql(db, chat_ro_factory):
    await _seed_machine(db, hostname="VIA-SQL")
    await db.commit()
    async with chat_ro_factory() as s:
        result = await run_tool(s, "inventory_sql",
                                {"sql": "SELECT hostname FROM v_chat_machines"})
    assert result.row_count == 1
    assert result.rows[0]["hostname"] == "VIA-SQL"
    assert len(result.sql_digest) == 64


@pytest.mark.asyncio
async def test_run_tool_inventory_sql_rejects_dml(chat_ro_factory):
    async with chat_ro_factory() as s:
        with pytest.raises(SqlGuardrailError):
            await run_tool(s, "inventory_sql", {"sql": "SELECT 1; DELETE FROM x"})


@pytest.mark.asyncio
async def test_structured_tools_never_expose_pii_columns(db, chat_ro_factory):
    await _seed_machine(db, hostname="NO-PII")
    await db.commit()
    async with chat_ro_factory() as s:
        for tool, params in [
            ("inventory_search", {}),
            ("inventory_stats", {}),
        ]:
            result = await run_tool(s, tool, params)
            for row in result.rows:
                assert not (PII_NAMES & set(row))
