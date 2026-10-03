"""Task 3 — read-only inventory pool (`inventory_chat_ro`) + minimized views.

Test dùng **role thật** `inventory_chat_ro` (không dùng app pool) theo spec V3-4:
manifest đóng (chỉ 6 view), ranh giới quyền, hardening role, RESET ALL mỗi checkout,
projection JSONB theo payload thật, EOL parity, password an toàn, suy URL.

Lưu ý spec V3-4: PostgreSQL cấp PUBLIC quyền đọc `pg_catalog`, nên cô lập catalog
**không** DB-enforced — tuyến chính là validator SQL ở T9. Test dưới đây khẳng định
ranh giới thực sự mà DB enforce: **không** đọc được bảng ứng dụng nhạy cảm.
"""
from __future__ import annotations

import os
import sys
import uuid
from importlib import util
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import pool as sa_pool
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import session as session_module

CHAT_RO_TEST_PASSWORD = "chat_ro_test_pw"
_MIGRATION_FILE = "e3f4a5b6c7d8_chat_ro_views.py"

PII_COLUMNS = {"email", "phone", "id_number", "password_hash", "full_name", "address"}

SENSITIVE_TABLES = [
    "users",
    "llm_config",
    "velociraptor_config",
    "api_keys",
    "audit_log",
    "chat_conversations",
    "token_reservations",
]


def _expected_win11_eol(build: int | None, today) -> bool | None:
    """Kỳ vọng EOL Windows 11 tính từ hằng số migration + `today` = DB `CURRENT_DATE`.

    `today` lấy từ `SELECT CURRENT_DATE` của **chính DB session** (timezone server),
    không phải `datetime.now(UTC)`: biểu thức SQL dùng `CURRENT_DATE` session-local nên
    nếu server không ở UTC hai giá trị có thể lệch quanh ngày hết hạn (boundary).
    """
    from datetime import date

    mig = _load_migration()
    if build is None:
        return None
    if build in (mig.WIN11_21H2_BUILD, mig.WIN11_22H2_BUILD, mig.WIN11_23H2_BUILD):
        return True
    if build == mig.WIN11_24H2_BUILD:
        return date.fromisoformat(mig.WIN11_24H2_EOL_DATE) < today
    if build > mig.WIN11_24H2_BUILD:
        return date.fromisoformat(mig.WIN11_NEWER_EOL_DATE) < today
    return None


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
async def chat_ro_session(db_engine, monkeypatch):
    """Tạo role + schema + view thật, trỏ `get_chat_ro_session` vào pool chat_ro.

    Tạo bằng superuser (test user `inventory` có CREATEROLE), chạy cả hardening, rồi
    kết nối lại bằng chính role `inventory_chat_ro` để chứng minh ranh giới quyền.
    Engine test dùng `session_module.create_chat_ro_engine` để có listener RESET ALL.
    """
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
        # Chính sách text-to-SQL hiện hành: SELECT toàn bộ `public` trừ denylist.
        from app.services.chat_sql_policy import sync_chat_ro_privileges

        await sync_chat_ro_privileges(conn)

    engine = session_module.create_chat_ro_engine(
        _chat_ro_test_url(), poolclass=sa_pool.NullPool
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "chat_ro_engine", engine, raising=False)
    monkeypatch.setattr(session_module, "AsyncChatRoSessionLocal", factory, raising=False)
    yield
    await engine.dispose()
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("DROP SCHEMA IF EXISTS chat_ro_views CASCADE")


async def _chat_ro_fetch(sql: str, **params):
    async for s in session_module.get_chat_ro_session():
        result = await s.execute(text(sql), params)
        return result.mappings().all()
    raise AssertionError("chat_ro session did not yield")


async def _chat_ro_scalar(sql: str):
    """Trả 1 giá trị vô hướng từ session chat_ro (vd `SELECT CURRENT_DATE`)."""
    async for s in session_module.get_chat_ro_session():
        return (await s.execute(text(sql))).scalar()
    raise AssertionError("chat_ro session did not yield")


async def _seed_machine(db, *, hostname="WS-01", os_name="Windows 10 Pro",
                        os_version="10.0.19045", os_build=None,
                        status="online", org=None, cpu=None, ram_gb=None, disks=None):
    """Seed org (nếu chưa có) + machine + machine_current. Trả (org, machine)."""
    from datetime import UTC, datetime

    from app.db.models import Machine, MachineCurrent, Organization, OrgType

    if org is None:
        org = Organization(id=uuid.uuid4(), name=f"Org-{uuid.uuid4().hex[:6]}",
                           type=OrgType.DON_VI.value)
        db.add(org)
        await db.flush()
    machine = Machine(
        id=uuid.uuid4(),
        org_id=org.id,
        machine_uuid=uuid.uuid4().hex,
        hostname=hostname,
        status=status,
        last_seen_at=datetime.now(UTC),
    )
    db.add(machine)
    await db.flush()
    db.add(MachineCurrent(
        machine_id=machine.id,
        collected_at=datetime.now(UTC),
        os_name=os_name,
        os_version=os_version,
        os_build=os_build,
        cpu=cpu,
        ram_gb=ram_gb,
        disks=disks,
    ))
    await db.flush()
    return org, machine


# ── Role boundary ────────────────────────────────────────────────────────────

async def test_chat_ro_role_is_noinherit(chat_ro_session):
    async for s in session_module.get_chat_ro_session():
        row = (await s.execute(text(
            "SELECT rolcanlogin, rolinherit FROM pg_roles WHERE rolname = current_user"
        ))).first()
        assert row is not None
        assert row.rolcanlogin is True
        assert row.rolinherit is False


async def test_chat_ro_role_hardened(chat_ro_session):
    """Role không có thuộc tính đặc quyền, không membership, không sở hữu object."""
    async for s in session_module.get_chat_ro_session():
        row = (await s.execute(text(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        ))).one()
        assert not any(row)
        members = (await s.execute(text(
            "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
            "WHERE r.rolname = current_user"
        ))).scalar()
        assert members == 0
        owned = (await s.execute(text(
            "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname = current_user"
        ))).scalar()
        assert owned == 0


async def test_chat_ro_cannot_read_users(chat_ro_session):
    with pytest.raises(Exception) as exc:
        await _chat_ro_fetch("SELECT email FROM public.users LIMIT 1")
    assert "permission denied" in str(exc.value).lower()


@pytest.mark.parametrize("table", SENSITIVE_TABLES)
async def test_chat_ro_cannot_read_sensitive_tables(chat_ro_session, table):
    with pytest.raises(Exception) as exc:
        await _chat_ro_fetch(f"SELECT * FROM public.{table} LIMIT 1")
    assert "permission denied" in str(exc.value).lower()


async def test_chat_ro_can_read_approved_view(chat_ro_session):
    rows = await _chat_ro_fetch("SELECT * FROM v_chat_machines")
    assert rows == []  # view đọc được (không lỗi quyền), chưa seed dữ liệu


async def test_chat_ro_can_read_public_base_table(chat_ro_session):
    """Text-to-SQL: bảng gốc `public` (ngoài denylist) đọc được; bảng bí mật thì không."""
    assert await _chat_ro_fetch("SELECT id FROM public.machines LIMIT 1") == []
    assert await _chat_ro_fetch("SELECT id FROM public.organizations LIMIT 1") == []
    with pytest.raises(Exception) as exc:
        await _chat_ro_fetch("SELECT id FROM public.llm_config LIMIT 1")
    assert "permission denied" in str(exc.value).lower()
    with pytest.raises(Exception) as exc2:
        await _chat_ro_fetch("SELECT id FROM public.audit_log LIMIT 1")
    assert "permission denied" in str(exc2.value).lower()


async def test_chat_ro_extra_schema_object_not_readable(db_engine, chat_ro_session):
    """Critical 1: manifest đóng — object thêm vào schema KHÔNG tự động được đọc."""
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE chat_ro_views.extra_secret(id int)")
    try:
        with pytest.raises(Exception) as exc:
            await _chat_ro_fetch("SELECT * FROM chat_ro_views.extra_secret")
        assert "permission denied" in str(exc.value).lower()
    finally:
        async with db_engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE IF EXISTS chat_ro_views.extra_secret")


async def test_chat_ro_checkout_resets_session_state(chat_ro_session):
    """Important 1: mỗi lần mượn connection phải RESET ALL + đặt lại search_path."""
    engine = session_module.create_chat_ro_engine(
        _chat_ro_test_url(), poolclass=sa_pool.AsyncAdaptedQueuePool,
        pool_size=1, max_overflow=0,
    )
    try:
        async with engine.connect() as c1:
            await c1.execute(text("SET search_path TO public"))
            await c1.execute(text("SET statement_timeout = 123456"))
            assert (await c1.execute(text("SHOW search_path"))).scalar() == "public"
        async with engine.connect() as c2:
            sp = (await c2.execute(text("SHOW search_path"))).scalar()
            st = (await c2.execute(text("SHOW statement_timeout"))).scalar()
        assert "chat_ro_views" in sp
        assert st != "123456"
    finally:
        await engine.dispose()


async def test_chat_ro_checkout_resets_committed_session_state(chat_ro_session):
    """Fix2: RESET phải chạy **autocommit** — `SET` đã commit vẫn bị xoá.

    `SET` (không LOCAL) đã commit tồn tại ở session-level. Nếu listener chạy trong
    transaction ẩn của adapter, `ROLLBACK` sau đó khôi phục giá trị nhiễm — assertion
    `sp_after_rollback` bắt đúng lỗi đó (implementation cũ fail test này).
    """
    engine = session_module.create_chat_ro_engine(
        _chat_ro_test_url(), poolclass=sa_pool.AsyncAdaptedQueuePool,
        pool_size=1, max_overflow=0,
    )
    try:
        async with engine.connect() as c1:
            await c1.execute(text("SET search_path TO public"))
            await c1.execute(text("SET statement_timeout = 123456"))
            await c1.commit()  # session-level SET → tồn tại sau commit
        async with engine.connect() as c2:
            sp = (await c2.execute(text("SHOW search_path"))).scalar()
            st = (await c2.execute(text("SHOW statement_timeout"))).scalar()
            await c2.rollback()  # nếu RESET nằm trong txn → khôi phục giá trị nhiễm
            sp_after_rollback = (await c2.execute(text("SHOW search_path"))).scalar()
        assert "chat_ro_views" in sp
        assert st != "123456"
        assert "chat_ro_views" in sp_after_rollback
    finally:
        await engine.dispose()


async def test_chat_ro_column_grant_revoked(db_engine):
    """Critical 1 (R2): quyền column-level (`GRANT SELECT(email)`) phải bị gỡ.

    `REVOKE ALL ON TABLE` không gỡ quyền column-level — phải quét `pg_attribute.attacl`.
    """
    mig = _load_migration()
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))
        await conn.exec_driver_sql(
            f"GRANT SELECT (email) ON public.users TO {mig.CHAT_RO_ROLE}"
        )

    engine = session_module.create_chat_ro_engine(
        _chat_ro_test_url(), poolclass=sa_pool.NullPool
    )
    try:
        # Trước harden: grant column-level còn hiệu lực → đọc được `email`.
        async with engine.connect() as conn:
            await conn.execute(text("SELECT email FROM public.users LIMIT 1"))

        async with db_engine.begin() as conn:
            for stmt in mig.ROLE_HARDEN_DDL:
                await conn.exec_driver_sql(stmt)

        # Sau harden: quyền column-level đã bị gỡ.
        async with engine.connect() as conn:
            with pytest.raises(Exception) as exc:
                await conn.execute(text("SELECT email FROM public.users LIMIT 1"))
            assert "permission denied" in str(exc.value).lower()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("kind", ["schema", "function"])
async def test_chat_ro_ownership_fails_closed(db_engine, kind):
    """Critical 2 (R2): role sở hữu object (mọi catalog) → harden fail closed."""
    mig = _load_migration()
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))
        if kind == "schema":
            await conn.exec_driver_sql(
                f"CREATE SCHEMA chatro_owned AUTHORIZATION {mig.CHAT_RO_ROLE}"
            )
        else:
            await conn.exec_driver_sql(
                "CREATE FUNCTION public.chatro_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'"
            )
            await conn.exec_driver_sql(
                f"ALTER FUNCTION public.chatro_fn() OWNER TO {mig.CHAT_RO_ROLE}"
            )
    try:
        with pytest.raises(Exception) as exc:
            async with db_engine.begin() as conn:
                await conn.exec_driver_sql(mig.OWNERSHIP_CHECK_DDL)
        assert "owns" in str(exc.value).lower()
    finally:
        async with db_engine.begin() as conn:
            await conn.exec_driver_sql("DROP SCHEMA IF EXISTS chatro_owned CASCADE")
            await conn.exec_driver_sql("DROP FUNCTION IF EXISTS public.chatro_fn()")


async def test_chat_ro_ownership_fails_closed_largeobject_tablespace(db_engine):
    """Critical 2 (R3): role sở hữu `pg_largeobject` + `pg_tablespace` (+ thuộc tính
    đặc quyền) → harden fail closed.

    Hai catalog này bị enumeration 12-query trước đây bỏ sót; `pg_shdepend` (deptype='o')
    phủ cả local (`pg_largeobject`, dbid<>0) lẫn shared (`pg_tablespace`, dbid=0).
    """
    mig = _load_migration()
    role = mig.CHAT_RO_ROLE
    ts_name = "chatro_owned_ts"
    ts_dir = "/tmp/chatro_owned_ts_dir"

    async with db_engine.connect() as conn:
        su = bool(await conn.scalar(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ))
    if not su:
        pytest.skip("CREATE TABLESPACE requires superuser")

    loid = None

    async def _autocommit(sql: str):
        async with db_engine.connect() as c:
            c2 = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c2.exec_driver_sql(sql)

    # Dọn trạng thái sót của lần chạy trước (role/tablespace tồn tại ở tầm cluster).
    await _autocommit(f"DROP TABLESPACE IF EXISTS {ts_name}")
    await _autocommit(
        f"COPY (SELECT '') TO PROGRAM 'rm -rf {ts_dir}'"
    )
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))
        await conn.exec_driver_sql(f"DROP OWNED BY {role} CASCADE")
        # Pre-seed role KHÔNG an toàn: thuộc tính đặc quyền.
        await conn.exec_driver_sql(f"ALTER ROLE {role} SUPERUSER CREATEDB")

    try:
        # 1) large object sở hữu bởi role (local, deptype='o', dbid<>0).
        async with db_engine.begin() as conn:
            loid = await conn.scalar(text("SELECT lo_create(0)"))
            await conn.exec_driver_sql(f"ALTER LARGE OBJECT {loid} OWNER TO {role}")

        # 2) tablespace sở hữu bởi role (shared, deptype='o', dbid=0). Thư mục tạo bằng
        #    `COPY TO PROGRAM` (chạy trong tiến trình PG) → tự chứa, không cần docker CLI.
        await _autocommit(
            f"COPY (SELECT '') TO PROGRAM "
            f"'rm -rf {ts_dir} && mkdir -p {ts_dir} && chmod 700 {ts_dir}'"
        )
        await _autocommit(f"CREATE TABLESPACE {ts_name} LOCATION '{ts_dir}'")
        await _autocommit(f"ALTER TABLESPACE {ts_name} OWNER TO {role}")

        # 3) Chạy hardening như migration → phải fail closed trước khi hoàn tất.
        with pytest.raises(Exception) as exc:
            async with db_engine.begin() as conn:
                await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))
                for stmt in mig.ROLE_HARDEN_DDL:
                    await conn.exec_driver_sql(stmt)
        assert "owns" in str(exc.value).lower()
    finally:
        await _autocommit(f"DROP TABLESPACE IF EXISTS {ts_name}")
        await _autocommit(f"COPY (SELECT '') TO PROGRAM 'rm -rf {ts_dir}'")
        async with db_engine.begin() as conn:
            if loid is not None:
                await conn.execute(text("SELECT lo_unlink(:oid)"), {"oid": loid})
            await conn.exec_driver_sql(
                f"ALTER ROLE {role} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                f"NOREPLICATION NOBYPASSRLS NOINHERIT"
            )
            await conn.exec_driver_sql(f"DROP OWNED BY {role} CASCADE")


async def test_chat_ro_ownership_check_ignores_own_local_grants(db_engine):
    """R3 idempotency: `pg_shdepend` deptype='a' cục bộ (USAGE/SELECT chính migration cấp)
    KHÔNG được kích hoạt fail-closed — nếu không migration không chạy lại được."""
    mig = _load_migration()
    role = mig.CHAT_RO_ROLE
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))
        await conn.exec_driver_sql(f"DROP OWNED BY {role} CASCADE")
        await conn.exec_driver_sql(mig.SCHEMA_DDL)
        await conn.exec_driver_sql(
            f"CREATE TABLE IF NOT EXISTS {mig.CHAT_RO_SCHEMA}.chatro_local_t(id int)"
        )
        await conn.exec_driver_sql(
            f"GRANT USAGE ON SCHEMA {mig.CHAT_RO_SCHEMA} TO {role}"
        )
        await conn.exec_driver_sql(
            f"GRANT SELECT ON {mig.CHAT_RO_SCHEMA}.chatro_local_t TO {role}"
        )
    try:
        async with db_engine.begin() as conn:
            await conn.exec_driver_sql(mig.OWNERSHIP_CHECK_DDL)  # không raise
    finally:
        async with db_engine.begin() as conn:
            await conn.exec_driver_sql(
                f"DROP TABLE IF EXISTS {mig.CHAT_RO_SCHEMA}.chatro_local_t"
            )
            await conn.exec_driver_sql(f"REVOKE ALL ON SCHEMA {mig.CHAT_RO_SCHEMA} FROM {role}")
            await conn.exec_driver_sql(f"DROP OWNED BY {role} CASCADE")
            await conn.exec_driver_sql(
                f"DROP SCHEMA IF EXISTS {mig.CHAT_RO_SCHEMA} CASCADE"
            )


async def test_chat_ro_catalog_is_readable_and_validator_enforced(chat_ro_session):
    """Spec V3-4: PUBLIC đọc `pg_catalog`; cô lập catalog do validator T9, không DB."""
    rows = await _chat_ro_fetch("SELECT 1 AS one FROM pg_catalog.pg_user LIMIT 1")
    assert rows  # không raise — ghi nhận giới hạn DB-enforced


# ── View manifest / PII ──────────────────────────────────────────────────────

async def test_chat_ro_machines_view_has_no_pii(chat_ro_session):
    rows = await _chat_ro_fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'chat_ro_views' AND table_name = 'v_chat_machines'"
    )
    cols = {r["column_name"] for r in rows}
    assert not (PII_COLUMNS & cols)
    assert cols == {
        "id", "hostname", "org_name", "os_name", "os_version",
        "status", "last_seen", "eol_flag",
    }


async def test_chat_ro_no_view_exposes_pii(chat_ro_session):
    rows = await _chat_ro_fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'chat_ro_views'"
    )
    exposed = {(r["table_name"], r["column_name"]) for r in rows}
    assert not {c for _, c in exposed} & PII_COLUMNS


# ── Views read real data ─────────────────────────────────────────────────────

async def test_chat_ro_machines_view_reads_machine(db, chat_ro_session):
    org, machine = await _seed_machine(
        db, hostname="WS-42", os_name="Windows 11 Pro", os_version="10.0.26100.1"
    )
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_machines WHERE id = :id", id=machine.id
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["hostname"] == "WS-42"
    assert row["org_name"] == org.name
    assert row["os_name"] == "Windows 11 Pro"
    assert row["status"] == "online"
    today = await _chat_ro_scalar("SELECT CURRENT_DATE")
    assert row["eol_flag"] == _expected_win11_eol(26100, today)


async def test_chat_ro_eol_flag_heuristic(db, chat_ro_session):
    await _seed_machine(db, hostname="EOL-10", os_name="Windows 10 Pro",
                        os_version="10.0.19045")
    await _seed_machine(db, hostname="OK-11", os_name="Windows 11 Pro",
                        os_version="10.0.26100.1")
    await _seed_machine(db, hostname="EOL-11", os_name="Windows 11 Pro",
                        os_version="10.0.22621.1")
    await _seed_machine(db, hostname="EOL-2012", os_name="Windows Server 2012 R2",
                        os_version="6.3.9600")
    await _seed_machine(db, hostname="UNK", os_name=None, os_version=None)
    await db.commit()

    flags = {
        r["hostname"]: r["eol_flag"]
        for r in await _chat_ro_fetch("SELECT hostname, eol_flag FROM v_chat_machines")
    }
    assert flags["EOL-10"] is True
    today = await _chat_ro_scalar("SELECT CURRENT_DATE")
    assert flags["OK-11"] == _expected_win11_eol(26100, today)  # build 26100: theo ngày tham chiếu
    assert flags["EOL-11"] is True       # build 22621 đã hết hỗ trợ
    assert flags["EOL-2012"] is True
    assert flags["UNK"] is None


async def test_chat_ro_eol_win11_without_build_is_unknown(db, chat_ro_session):
    """Không đoán: Windows 11 thiếu build → NULL, không mặc định FALSE."""
    await _seed_machine(db, hostname="WIN11-NOVER", os_name="Windows 11 Pro",
                        os_version=None, os_build=None)
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT eol_flag FROM v_chat_machines WHERE hostname = 'WIN11-NOVER'"
    )
    assert rows[0]["eol_flag"] is None


async def test_chat_ro_build_expr_takes_first_component_and_validates(db, chat_ro_session):
    """Fix3: `os_build` nhiều thành phần không nối chuỗi; quá dài → NULL (không tràn int).

    `os_build="26100.1"` trước đây bị `regexp_replace` nối thành `261001`; nay lấy
    thành phần build thứ 3 của `os_version` (= 26100) và validate `os_build` trước khi cast.
    """
    mig = _load_migration()
    _, dotted = await _seed_machine(
        db, hostname="B-DOTTED", os_name="Windows 11 Pro",
        os_version="10.0.26100.1", os_build="26100.1",
    )
    _, overflow = await _seed_machine(db, hostname="B-OVERFLOW", os_version=None,
                                      os_build="9999999999")
    _, missing = await _seed_machine(db, hostname="B-MISSING", os_version=None, os_build=None)
    _, pure = await _seed_machine(db, hostname="B-PURE", os_version=None, os_build="26100")
    await db.commit()

    expr = mig.build_expr("machine_current")
    builds = {}
    for label, mid in [("dotted", dotted.id), ("overflow", overflow.id),
                       ("missing", missing.id), ("pure", pure.id)]:
        builds[label] = (await db.execute(
            text(f"SELECT {expr} FROM public.machine_current WHERE machine_id = :id"),
            {"id": mid},
        )).scalar()

    assert builds["dotted"] == 26100      # KHÔNG phải 261001
    assert builds["overflow"] is None     # không tràn int
    assert builds["missing"] is None
    assert builds["pure"] == 26100

    # Lifecycle của build 26100 (không phải 261001) thể hiện qua eol_flag.
    rows = await _chat_ro_fetch(
        "SELECT eol_flag FROM v_chat_machines WHERE hostname = 'B-DOTTED'"
    )
    today = await _chat_ro_scalar("SELECT CURRENT_DATE")
    assert rows[0]["eol_flag"] == _expected_win11_eol(26100, today)


async def test_chat_ro_machine_detail_jsonb_extraction(db, chat_ro_session):
    _, machine = await _seed_machine(
        db, hostname="DETAIL-1",
        cpu={"model": "Intel Xeon Gold", "brand": "Intel", "cores": 8},
        ram_gb=16.0,
        # payload thật: `size_bytes` (500 GB) + legacy `size` (256 GB) = 756 GB
        disks=[{"model": "Samsung", "size_bytes": 536870912000},
               {"size": 274877906944}],
    )
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_machine_detail WHERE id = :id", id=machine.id
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["cpu"] == "Intel Xeon Gold"
    assert row["ram_mb"] == 16384
    assert row["disk_gb"] == 756


async def test_chat_ro_disk_gb_from_legacy_size_gb(db, chat_ro_session):
    """Important 2: legacy `size_gb` vẫn đọc được khi không có trường bytes."""
    _, machine = await _seed_machine(
        db, hostname="DETAIL-LEGACY", disks=[{"model": "Old", "size_gb": 100}],
    )
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT disk_gb FROM v_chat_machine_detail WHERE id = :id", id=machine.id
    )
    assert rows[0]["disk_gb"] == 100


async def test_chat_ro_machine_detail_null_jsonb_is_null(db, chat_ro_session):
    _, machine = await _seed_machine(db, hostname="DETAIL-NULL", cpu=None, ram_gb=None, disks=None)
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_machine_detail WHERE id = :id", id=machine.id
    )
    assert rows[0]["cpu"] is None
    assert rows[0]["ram_mb"] is None
    assert rows[0]["disk_gb"] is None


async def test_chat_ro_cpu_projection_excludes_name(db, chat_ro_session):
    """Important 4: chỉ `model`/`brand`; `name` không được dùng."""
    await _seed_machine(db, hostname="CPU-NAME", cpu={"name": "Foo CPU"})
    await _seed_machine(db, hostname="CPU-BRAND", cpu={"brand": "Intel"})
    await _seed_machine(db, hostname="CPU-MODEL", cpu={"model": "Xeon"})
    await db.commit()

    rows = {
        r["hostname"]: r["cpu"]
        for r in await _chat_ro_fetch("SELECT hostname, cpu FROM v_chat_machine_detail")
    }
    assert rows["CPU-NAME"] is None
    assert rows["CPU-BRAND"] == "Intel"
    assert rows["CPU-MODEL"] == "Xeon"


async def test_chat_ro_org_stats_aggregates(db, chat_ro_session):
    from app.db.models import Organization, OrgType

    org = Organization(id=uuid.uuid4(), name="Stats-Org", type=OrgType.DON_VI.value)
    db.add(org)
    await db.flush()
    await _seed_machine(db, hostname="S-ON", status="online", os_name="Windows 10 Pro", org=org)
    await _seed_machine(db, hostname="S-OFF", status="offline", os_name="Windows Server 2022",
                        org=org)
    await _seed_machine(db, hostname="S-ON2", status="online", os_name="Windows Server 2022",
                        org=org)
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_org_stats WHERE org_name = :n", n="Stats-Org"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["machine_count"] == 3
    assert row["online_count"] == 2
    assert row["eol_count"] == 1  # chỉ máy Windows 10


async def test_chat_ro_software_view(db, chat_ro_session):
    from app.db.models import MachineSoftware

    _, machine = await _seed_machine(db, hostname="SW-1")
    db.add(MachineSoftware(
        id=None, machine_id=machine.id, name="7-Zip", version="23.01", install_date="2024-01-15",
    ))
    await db.flush()
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_software WHERE machine_id = :id", id=machine.id
    )
    assert len(rows) == 1
    assert rows[0]["software_name"] == "7-Zip"
    assert rows[0]["version"] == "23.01"
    assert rows[0]["install_date"] == "2024-01-15"
    assert rows[0]["hostname"] == "SW-1"


async def test_chat_ro_hardware_view(db, chat_ro_session):
    _, machine = await _seed_machine(
        db, hostname="HW-1",
        cpu={"model": "AMD Ryzen 9"},
        ram_gb=32.0,
        disks=[{"model": "NVMe", "size_bytes": 1099511627776}],  # 1024 GB
    )
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT component, value FROM v_chat_hardware WHERE machine_id = :id ORDER BY component",
        id=machine.id,
    )
    by_component = {r["component"]: r["value"] for r in rows}
    assert by_component["cpu"] == "AMD Ryzen 9"
    assert by_component["ram_gb"] == "32"
    assert by_component["disk"] == "NVMe 1024GB"


async def test_chat_ro_alerts_uses_dfir_alerts_and_maps_resolved(db, chat_ro_session):
    from app.db.models import DfirAlert

    _, machine = await _seed_machine(db, hostname="ALERT-1")
    alert = DfirAlert(
        id=uuid.uuid4(), artifact_pattern="Persistence", severity="critical",
        flow_id="F.123", machine_id=machine.id, message="suspicious", resolved=False,
    )
    db.add(alert)
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_alerts WHERE id = :id", id=alert.id
    )
    assert rows[0]["status"] == "open"
    assert rows[0]["severity"] == "critical"
    assert rows[0]["category"] == "dfir"
    assert rows[0]["hostname"] == "ALERT-1"

    alert.resolved = True
    await db.commit()
    rows = await _chat_ro_fetch(
        "SELECT status FROM v_chat_alerts WHERE id = :id", id=alert.id
    )
    assert rows[0]["status"] == "resolved"


# ── Password literal safety ──────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "plain", "p$$w", "a'b", "back\\slash", "mix'$\\x", "$$", "", "a:b", "  spaced  ",
])
async def test_password_literal_matches_postgres_quote_literal(db_engine, value):
    mig = _load_migration()
    async with db_engine.connect() as conn:
        expected = (
            await conn.execute(text("SELECT quote_literal(:v)"), {"v": value})
        ).scalar_one()
    assert mig._pg_literal(value) == expected


async def test_role_password_with_dollar_quotes(db_engine):
    """Important 5: password chứa `$$`/`'`/`:` vẫn tạo role + đăng nhập được."""
    mig = _load_migration()
    weird = "p$$w'ord:?:x\\z"
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(mig.role_ddl(weird))

    host = os.environ.get("POSTGRES_TEST_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_TEST_PORT", "5432")
    db = os.environ.get("POSTGRES_TEST_DB", "inventory_test")
    login_url = make_url(
        f"postgresql+asyncpg://inventory_chat_ro:pw@{host}:{port}/{db}"
    ).set(password=weird).render_as_string(hide_password=False)

    engine = create_async_engine(login_url, poolclass=sa_pool.NullPool)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    finally:
        await engine.dispose()
        # Khôi phục password chuẩn cho các test khác.
        async with db_engine.begin() as conn:
            await conn.exec_driver_sql(mig.role_ddl(CHAT_RO_TEST_PASSWORD))


# ── Config URL derivation ────────────────────────────────────────────────────

def test_effective_chat_ro_database_url_derives_from_database_url(monkeypatch):
    from app.core.config import Settings

    s = Settings(
        database_url="postgresql+asyncpg://inventory:pw@dbhost:5433/inventory_prod",
        chat_ro_password="s3cret",
    )
    assert s.effective_chat_ro_database_url() == (
        "postgresql+asyncpg://inventory_chat_ro:s3cret@dbhost:5433/inventory_prod"
    )


def test_effective_chat_ro_database_url_override_wins():
    from app.core.config import Settings

    s = Settings(
        database_url="postgresql+asyncpg://inventory:pw@dbhost:5432/inventory",
        chat_ro_database_url="postgresql+asyncpg://inventory_chat_ro:x@other:5432/inventory",
    )
    assert s.effective_chat_ro_database_url().startswith(
        "postgresql+asyncpg://inventory_chat_ro:x@other"
    )


def test_effective_chat_ro_database_url_ipv6_preserves_brackets():
    """Minor: host IPv6 phải giữ dấu ngoặc vuông."""
    from app.core.config import Settings

    s = Settings(
        database_url="postgresql+asyncpg://inventory:pw@[::1]:5433/inventory",
        chat_ro_password="s3cret",
    )
    assert s.effective_chat_ro_database_url() == (
        "postgresql+asyncpg://inventory_chat_ro:s3cret@[::1]:5433/inventory"
    )


def test_effective_chat_ro_database_url_encodes_special_password():
    from app.core.config import Settings

    s = Settings(
        database_url="postgresql+asyncpg://inventory:pw@dbhost:5432/inventory",
        chat_ro_password="p@ss/w:rd",
    )
    assert s.effective_chat_ro_database_url() == (
        "postgresql+asyncpg://inventory_chat_ro:p%40ss%2Fw%3Ard@dbhost:5432/inventory"
    )
