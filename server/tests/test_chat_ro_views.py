"""Task 3 — read-only inventory pool (`inventory_chat_ro`) + minimized views.

Test dùng **role thật** `inventory_chat_ro` (không dùng app pool) theo spec V3-4:
alias che PII, catalog isolation (validator-enforced), function side-effect, v.v.

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

    Tạo bằng superuser (test user `inventory` có CREATEROLE), rồi kết nối lại bằng
    chính role `inventory_chat_ro` để chứng minh ranh giới quyền.
    """
    mig = _load_migration()
    async with db_engine.begin() as conn:
        await conn.execute(text(mig.role_ddl(CHAT_RO_TEST_PASSWORD)))
        await conn.execute(text(mig.SCHEMA_DDL))
        for stmt in mig.VIEW_DDL:
            await conn.execute(text(stmt))
        for stmt in mig.GRANT_DDL:
            await conn.execute(text(stmt))

    engine = create_async_engine(
        _chat_ro_test_url(),
        poolclass=sa_pool.NullPool,
        connect_args={"server_settings": {"search_path": "chat_ro_views,pg_catalog"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "chat_ro_engine", engine, raising=False)
    monkeypatch.setattr(session_module, "AsyncChatRoSessionLocal", factory, raising=False)
    yield
    await engine.dispose()
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS chat_ro_views CASCADE"))


async def _chat_ro_fetch(sql: str, **params):
    async for s in session_module.get_chat_ro_session():
        result = await s.execute(text(sql), params)
        return result.mappings().all()
    raise AssertionError("chat_ro session did not yield")


async def _seed_machine(db, *, hostname="WS-01", os_name="Windows 10 Pro",
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
        os_version="10.0.19045",
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
    org, machine = await _seed_machine(db, hostname="WS-42", os_name="Windows 11 Pro")
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
    assert row["eol_flag"] is False


async def test_chat_ro_eol_flag_heuristic(db, chat_ro_session):
    await _seed_machine(db, hostname="EOL-10", os_name="Windows 10 Pro")
    await _seed_machine(db, hostname="OK-11", os_name="Windows 11 Pro")
    await _seed_machine(db, hostname="EOL-2012", os_name="Windows Server 2012 R2")
    await _seed_machine(db, hostname="UNK", os_name=None)
    await db.commit()

    flags = {
        r["hostname"]: r["eol_flag"]
        for r in await _chat_ro_fetch("SELECT hostname, eol_flag FROM v_chat_machines")
    }
    assert flags["EOL-10"] is True
    assert flags["OK-11"] is False
    assert flags["EOL-2012"] is True
    assert flags["UNK"] is None


async def test_chat_ro_machine_detail_jsonb_extraction(db, chat_ro_session):
    _, machine = await _seed_machine(
        db, hostname="DETAIL-1",
        cpu={"model": "Intel Xeon Gold", "brand": "Intel", "cores": 8},
        ram_gb=16.0,
        disks=[{"model": "Samsung", "capacity_gb": 500}, {"capacity_gb": 256}],
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


async def test_chat_ro_machine_detail_null_jsonb_is_null(db, chat_ro_session):
    _, machine = await _seed_machine(db, hostname="DETAIL-NULL", cpu=None, ram_gb=None, disks=None)
    await db.commit()

    rows = await _chat_ro_fetch(
        "SELECT * FROM v_chat_machine_detail WHERE id = :id", id=machine.id
    )
    assert rows[0]["cpu"] is None
    assert rows[0]["ram_mb"] is None
    assert rows[0]["disk_gb"] is None


async def test_chat_ro_org_stats_aggregates(db, chat_ro_session):
    from app.db.models import Organization, OrgType

    org = Organization(id=uuid.uuid4(), name="Stats-Org", type=OrgType.DON_VI.value)
    db.add(org)
    await db.flush()
    await _seed_machine(db, hostname="S-ON", status="online", os_name="Windows 10 Pro", org=org)
    await _seed_machine(db, hostname="S-OFF", status="offline", os_name="Windows 11 Pro", org=org)
    await _seed_machine(db, hostname="S-ON2", status="online", os_name="Windows 11 Pro", org=org)
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
        disks=[{"model": "NVMe", "capacity_gb": 1024}],
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
