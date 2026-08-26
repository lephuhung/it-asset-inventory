"""Test partition `heartbeats` theo ngày (PostgreSQL).

Conftest tạo schema bằng create_all (heartbeats là bảng thường). Test này tự dựng
bản partition (giống DDL trong migration) lên bảng heartbeats để kiểm thử service
và việc routing insert theo ngày. Được cô lập: mỗi test drop/create schema mới.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.partition import ensure_heartbeat_partitions


async def _make_heartbeats_partitioned(engine: AsyncEngine, days_ahead: int = 3) -> None:
    """Drop heartbeats thường → tạo bản PARTITION BY RANGE (ts) + DEFAULT."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS heartbeats"))
        await conn.execute(
            text(
                """
                CREATE TABLE heartbeats (
                    id          BIGSERIAL,
                    machine_id  UUID NOT NULL,
                    ts          TIMESTAMPTZ NOT NULL,
                    ip          VARCHAR(45),
                    logged_user VARCHAR(255),
                    uptime_sec  INTEGER,
                    PRIMARY KEY (id, ts)
                ) PARTITION BY RANGE (ts)
                """
            )
        )
        await conn.execute(text("CREATE TABLE heartbeats_default PARTITION OF heartbeats DEFAULT"))
        await conn.execute(
            text("CREATE INDEX ix_heartbeats_machine_ts ON heartbeats (machine_id, ts)")
        )
        await conn.execute(text("CREATE INDEX ix_heartbeats_ts ON heartbeats (ts)"))


async def _partition_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT relname FROM pg_class WHERE relname LIKE 'heartbeats_%' AND relkind='r'")
        )
        return {r[0] for r in rows.all()}


async def test_ensure_creates_daily_partitions(db_engine: AsyncEngine):
    await _make_heartbeats_partitioned(db_engine)
    today = datetime.now(UTC).date()

    async with db_engine.begin() as conn:
        created = await ensure_heartbeat_partitions(conn, days_ahead=7, start_day=today)

    names = await _partition_names(db_engine)
    assert "heartbeats_default" in names
    # 7 partition ngày từ hôm nay
    for i in range(7):
        expected = f"heartbeats_{(today + timedelta(days=i)).strftime('%Y%m%d')}"
        assert expected in names
    assert len(created) == 7


async def test_ensure_is_idempotent(db_engine: AsyncEngine):
    await _make_heartbeats_partitioned(db_engine)
    today = datetime.now(UTC).date()

    async with db_engine.begin() as conn:
        first = await ensure_heartbeat_partitions(conn, days_ahead=3, start_day=today)
    async with db_engine.begin() as conn:
        second = await ensure_heartbeat_partitions(conn, days_ahead=3, start_day=today)

    assert len(first) == 3
    assert second == []  # đã tồn tại — không tạo lại


async def test_noop_when_not_partitioned(db_engine: AsyncEngine):
    """Nếu heartbeats không phải partition table (môi trường test thường) → no-op."""
    async with db_engine.begin() as conn:
        created = await ensure_heartbeat_partitions(conn, days_ahead=3)
    assert created == []


async def test_insert_routes_to_daily_partition(db_engine: AsyncEngine, db):
    """Insert heartbeat cho hôm nay phải tới đúng partition ngày (không dùng DEFAULT)."""

    from app.db.models import Heartbeat

    await _make_heartbeats_partitioned(db_engine)
    today = datetime.now(UTC).date()

    async with db_engine.begin() as conn:
        await ensure_heartbeat_partitions(conn, days_ahead=1, start_day=today)

    # Insert 1 heartbeat (machine_id giả — không check FK vì partition DDL không có FK ở đây)
    hb = Heartbeat(
        machine_id="22222222-2222-2222-2222-222222222222",
        ts=datetime.now(UTC),
        ip="10.0.0.5",
    )
    db.add(hb)
    await db.commit()

    # Kiểm tra sự kiện nằm ở partition ngày, không phải DEFAULT
    # (đếm trực tiếp trên từng partition — không dùng pg_stat_user_tables do stats lag)
    named = await _partition_names(db_engine)

    # Máy đã insert nhưng có thể chưa commit được do transaction của session db —
    # đảm bảo commit và flush
    await db.commit()

    async with db_engine.connect() as conn:
        counts: dict[str, int] = {}
        for name in named:
            try:
                val = (
                    await conn.execute(text(f"SELECT count(*) FROM {name}"))
                ).scalar_one()
                counts[name] = val
            except Exception:
                counts[name] = -1  # không phải bảng data trực tiếp

    expected = f"heartbeats_{today.strftime('%Y%m%d')}"
    assert counts.get(expected, 0) >= 1, f"không tìm thấy row trong partition {expected}: {counts}"
    assert counts.get("heartbeats_default", 0) == 0, f"dữ liệu không được vào DEFAULT: {counts}"


async def test_rows_in_default_migrated_on_partition_create(db_engine: AsyncEngine):
    """Rows trong DEFAULT thuộc ngày đang tạo partition phải được chuyển về partition đó.

    Race case thực tế: heartbeat tới trước khi monitor tạo partition (rơi vào DEFAULT).
    Khi tạo partition sau đó, PG từ chối nếu DEFAULT còn rows vi phạm — service phải
    tự di chuyển tạm rồi insert lại đúng partition.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Heartbeat

    await _make_heartbeats_partitioned(db_engine)
    today = datetime.now(UTC).date()

    # 1. Chèn thẳng heartbeat (chưa tạo partition) → rơi vào DEFAULT
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            Heartbeat(
                machine_id="33333333-3333-3333-3333-333333333333",
                ts=datetime.now(UTC),
                ip="10.1.1.1",
            )
        )
        await s.commit()

    async with db_engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM ONLY heartbeats_default"))).scalar_one()
        assert n == 1, "row phải nằm ở DEFAULT trước khi tạo partition"

    # 2. Tạo partition hôm nay → phải tự migrate row từ DEFAULT
    async with db_engine.begin() as conn:
        created = await ensure_heartbeat_partitions(conn, days_ahead=1, start_day=today)

    expected = f"heartbeats_{today.strftime('%Y%m%d')}"
    assert expected in created

    async with db_engine.connect() as conn:
        in_daily = (
            await conn.execute(text(f"SELECT count(*) FROM {expected}"))
        ).scalar_one()
        in_default = (
            await conn.execute(text("SELECT count(*) FROM ONLY heartbeats_default"))
        ).scalar_one()
    assert in_daily == 1, f"row phải chuyển sang partition ngày: {in_daily}"
    assert in_default == 0, "DEFAULT phải trống sau migrate"
