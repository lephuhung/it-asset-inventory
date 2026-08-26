"""Quản lý partition cho `heartbeats` theo ngày (PostgreSQL, mục 5.1 tài liệu gốc).

Migration tạo `heartbeats` dạng PARTITION BY RANGE (ts) + `heartbeats_default`
(DEFAULT partition → mọi write không bao giờ lỗi do thiếu partition). Hàm này
tự tạo partition cho từng ngày tới `days_ahead`, gọi định kỳ từ background task
để luôn có partition sẵn cho ngày hiện tại & tương lai.

Lưu ý: chỉ áp dụng cho PostgreSQL sản phẩm (bảng qua Alembic). Ở test (conftest
dùng create_all theo ORM) bảng heartbeats là bảng thường — test functional vẫn
chạy bình thường; partition được test riêng trong tests/test_partition.py.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


def _partition_name(day: date) -> str:
    return f"heartbeats_{day.strftime('%Y%m%d')}"


async def _partition_exists(conn: AsyncConnection, name: str) -> bool:
    row = await conn.execute(
        text("SELECT 1 FROM pg_class WHERE relname = :n AND relkind = 'r'"), {"n": name}
    )
    return row.first() is not None


async def _stash_default_rows(conn: AsyncConnection, day: date, next_day: date) -> bool:
    """Di chuyển rows thuộc [day, next_day) ra khỏi DEFAULT partition vào bảng
    tạm `heartbeats_deferred`. Trả về True nếu có rows phải xử lý.

    PostgreSQL không cho tạo partition mới nếu DEFAULT còn rows vi phạm constraint.
    Bảng tạm giữ rows → sau khi tạo partition sẽ insert lại qua parent.
    """
    has_rows = await conn.execute(
        text(
            "SELECT 1 FROM ONLY heartbeats_default "
            "WHERE ts >= :lo AND ts < :hi LIMIT 1"
        ),
        {"lo": day, "hi": next_day},
    )
    if has_rows.first() is None:
        return False

    await conn.execute(text("DROP TABLE IF EXISTS heartbeats_deferred"))
    await conn.execute(text("CREATE TABLE heartbeats_deferred (LIKE heartbeats INCLUDING ALL)"))
    await conn.execute(
        text(
            "INSERT INTO heartbeats_deferred "
            "SELECT * FROM ONLY heartbeats_default WHERE ts >= :lo AND ts < :hi"
        ),
        {"lo": day, "hi": next_day},
    )
    await conn.execute(
        text("DELETE FROM ONLY heartbeats_default WHERE ts >= :lo AND ts < :hi"),
        {"lo": day, "hi": next_day},
    )
    return True


async def _restore_deferred_rows(conn: AsyncConnection) -> None:
    """Insert lại rows từ bảng tạm về `heartbeats` (routing đúng partition theo ts)."""
    count = (
        await conn.execute(text("SELECT count(*) FROM heartbeats_deferred"))
    ).scalar_one()
    if count:
        await conn.execute(text("INSERT INTO heartbeats SELECT * FROM heartbeats_deferred"))
    await conn.execute(text("DROP TABLE IF EXISTS heartbeats_deferred"))


async def ensure_heartbeat_partitions(
    conn: AsyncConnection, *, days_ahead: int = 7, start_day: date | None = None
) -> list[str]:
    """Đảm bảo tồn tại partition cho các ngày từ hôm nay tới +days_ahead.

    Nếu DEFAULT còn rows thuộc ngày đang tạo partition → tạm chuyển ra bảng temp,
    tạo partition, rồi insert lại (routing đúng theo ts). Trả về partition vừa tạo.
    """
    # Kiểm tra heartbeats có phải partition root không — nếu không (test) thì bỏ qua
    rooted = await conn.execute(
        text(
            "SELECT 1 FROM pg_class c JOIN pg_partitioned_table pt "
            "ON c.oid = pt.partrelid WHERE c.relname = 'heartbeats'"
        )
    )
    if rooted.first() is None:
        return []

    start = start_day or datetime.now(UTC).date()
    created: list[str] = []
    for i in range(days_ahead):
        day = start + timedelta(days=i)
        next_day = day + timedelta(days=1)
        name = _partition_name(day)
        if await _partition_exists(conn, name):
            continue
        stashed = await _stash_default_rows(conn, day, next_day)
        lo = day.isoformat()
        hi = next_day.isoformat()
        await conn.execute(
            text(
                f"CREATE TABLE {name} PARTITION OF heartbeats "
                f"FOR VALUES FROM ('{lo}') TO ('{hi}')"
            )
        )
        created.append(name)
        if stashed:
            await _restore_deferred_rows(conn)
    return created
