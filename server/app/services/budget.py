"""Token budget reservation service — spec F11/R8/V3-7/V5.

Redis là cache; **DB là nguồn sự thật** cho reservation. Mỗi thao tác tính phí có
`operation_id` riêng (chat = turn_id; investigation_analysis = 1 lần chạy phân tích;
investigation_chat = 1 câu hỏi). `association_id` chỉ để liên kết, không phải key.

Bất biến `charged`:

    charged(budget_date) = Σ reserved(state=reserved)
                         + Σ actual(state=settled)
                         + Σ reserved(state=unknown)

Admission (reserve) và settle đều lấy
`pg_advisory_xact_lock(hashtext('budget:' || budget_date))` để serialize toàn cục.
`reserve` dùng ngày hôm nay; `settle` dùng **`budget_date` bất biến của chính
reservation** (không phải hôm nay) — nhờ vậy settle qua nửa đêm vẫn được serialize
cùng admission của ngày tương ứng.

**Caller phải commit ngay sau `reserve`** (trước khi gọi LLM/tool tốn thời gian):
advisory lock là transaction-scoped, giữ đến `COMMIT`, nên nếu để lock mở suốt
cuộc gọi LLM thì mọi admission khác sẽ bị chặn. `settle` cũng nên được commit ngay
sau khi hoàn tất (không có thao tác chậm nào giữa settle và commit).

**Lỗi DB** trong `reserve`/`settle` được dịch thành `BudgetUnavailable`
(`[chat_budget_unavailable] ... [HTTP 503]`). Admission fail → fail closed cho thao
tác MỚI; settle fail SAU khi đã có kết quả → caller chỉ log, KHÔNG biến công việc
đã hoàn thành thành thất bại (spec R8).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TokenReservation

# Scope hợp lệ theo spec R8/V3-7.
SCOPES = frozenset({"chat_turn", "investigation_analysis", "investigation_chat"})

_LOCK_PREFIX = "budget:"
_TERMINAL_STATES = frozenset({"settled", "unknown"})


class BudgetConflict(ValueError):
    """Settle lần hai với `actual` khác lần đầu — vi phạm 'chỉ một winner settle'."""


class BudgetUnavailable(RuntimeError):
    """DB ngân sách không khả dụng — fail closed cho thực thi MỚI (spec R8).

    Caller phải rollback session đang dở trước khi dùng tiếp (transaction đã abort).
    Thông điệp theo format lỗi chung: `[<category>] <hint> [HTTP <code>]`.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"[chat_budget_unavailable] budget DB không khả dụng ({detail}) [HTTP 503]"
        )


@dataclass(frozen=True)
class Reservation:
    """Kết quả reserve (tách khỏi ORM session)."""

    scope: str
    operation_id: uuid.UUID
    association_id: uuid.UUID | None
    envelope: int
    budget_date: date
    state: str


def _utc_today() -> date:
    """Ngày budget theo UTC (spec: rollover theo budget_date UTC)."""
    return datetime.now(UTC).date()


def _lock_key(d: date) -> str:
    return f"{_LOCK_PREFIX}{d.isoformat()}"


def _charge_expr():
    """Biểu thức `charged` theo bất biến: settled→actual, còn lại→reserved."""
    return case(
        (TokenReservation.state == "settled", func.coalesce(TokenReservation.actual, 0)),
        else_=TokenReservation.reserved,
    )


def _to_dto(row: TokenReservation) -> Reservation:
    return Reservation(
        scope=row.scope,
        operation_id=row.operation_id,
        association_id=row.association_id,
        envelope=row.reserved,
        budget_date=row.budget_date,
        state=row.state,
    )


async def _acquire_lock(db: AsyncSession, d: date) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _lock_key(d)}
    )


async def charged(db: AsyncSession, budget_date: date | None = None) -> int:
    """Tổng token đã tính cho 1 `budget_date` (mặc định hôm nay, UTC)."""
    d = budget_date or _utc_today()
    total = (
        await db.execute(
            select(func.coalesce(func.sum(_charge_expr()), 0)).where(
                TokenReservation.budget_date == d
            )
        )
    ).scalar_one()
    return int(total or 0)


async def reserve(
    db: AsyncSession,
    *,
    scope: str,
    operation_id: uuid.UUID,
    association_id: uuid.UUID | None = None,
    envelope: int,
    budget: int | None,
) -> Reservation | None:
    """Giữ chỗ `envelope` token cho 1 thao tác.

    - Idempotent theo `(scope, operation_id)`: gọi lại trả bản ghi cũ, **không**
      trừ thêm (retry cùng thao tác phải dùng lại `operation_id`).
    - `budget=None` → không giới hạn.
    - Trả `None` khi `charged + envelope > budget` (vượt trần, fail closed).
    """
    if scope not in SCOPES:
        raise ValueError(f"budget scope không hợp lệ: {scope!r}")
    if envelope < 0:
        raise ValueError(f"envelope phải >= 0, nhận {envelope!r}")

    d = _utc_today()
    try:
        await _acquire_lock(db, d)

        # Idempotent retry: bản ghi đã tồn tại → trả lại, KHÔNG trừ thêm.
        existing = (
            await db.execute(
                select(TokenReservation).where(
                    TokenReservation.scope == scope,
                    TokenReservation.operation_id == operation_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _to_dto(existing)

        if budget is not None and await charged(db, d) + envelope > budget:
            return None

        # Chèn conflict-safe (spec R8/V3-7 yêu cầu `INSERT ... ON CONFLICT`).
        # Dưới advisory lock cùng ngày thì không thể trùng, nhưng retry cùng khóa
        # vắt qua nửa đêm UTC giữ lock của ngày khác nhau: hai transaction có thể
        # cùng SELECT-miss rồi cùng chèn. `ON CONFLICT DO NOTHING` biến race đó
        # thành idempotent thay vì ném `UniqueViolation`.
        stmt = (
            pg_insert(TokenReservation)
            .values(
                scope=scope,
                operation_id=operation_id,
                association_id=association_id,
                budget_date=d,
                reserved=envelope,
                state="reserved",
            )
            .on_conflict_do_nothing(index_elements=["scope", "operation_id"])
            .returning(TokenReservation)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Conflict: một transaction khác đã thắng race — trả bản ghi của họ.
            row = (
                await db.execute(
                    select(TokenReservation).where(
                        TokenReservation.scope == scope,
                        TokenReservation.operation_id == operation_id,
                    )
                )
            ).scalar_one()
        return _to_dto(row)
    except SQLAlchemyError as exc:
        raise BudgetUnavailable(type(exc).__name__) from exc


async def settle(
    db: AsyncSession,
    *,
    scope: str,
    operation_id: uuid.UUID,
    actual: int | None = None,
) -> None:
    """Chốt một reservation thành terminal.

    - `actual` biết được → `state=settled`, tính đúng `actual`.
    - `actual=None` (mất usage) → `state=unknown`, tính đủ `envelope` (đã giữ chỗ).
    - Lấy advisory lock theo **`budget_date` của reservation** (đọc trước, bất biến),
      không phải `_utc_today()` — để settle qua nửa đêm vẫn serialize đúng ngày.
    - Chỉ một winner: settle lần hai CÙNG giá trị là no-op; khác giá trị theo BẤT KỲ
      chiều nào (known↔unknown, hoặc hai `actual` known khác nhau) → `BudgetConflict`.
    - Không có reservation (chưa từng reserve) → no-op (đường lỗi/hủy chạy trước reserve).
    """
    try:
        # `budget_date` bất biến sau khi insert — đọc trước (không khóa) để lấy
        # ĐÚNG ngày của reservation. Không dùng `_utc_today()`: qua nửa đêm, một
        # reservation của hôm qua phải được khóa/ghi theo ngày hôm qua, nếu không
        # admission (giữ lock ngày hôm qua) và settle sẽ không được serialize.
        budget_date = (
            await db.execute(
                select(TokenReservation.budget_date).where(
                    TokenReservation.scope == scope,
                    TokenReservation.operation_id == operation_id,
                )
            )
        ).scalar_one_or_none()
        if budget_date is None:
            return

        await _acquire_lock(db, budget_date)
        row = (
            await db.execute(
                select(TokenReservation)
                .where(
                    TokenReservation.scope == scope,
                    TokenReservation.operation_id == operation_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return
        if row.state in _TERMINAL_STATES:
            # Chỉ một winner settle. So cả hai chiều: known↔unknown khác nhau là
            # xung đột, và hai `actual` known khác nhau cũng xung đột.
            incoming_known = actual is not None
            stored_known = row.state == "settled"
            if incoming_known != stored_known or (stored_known and row.actual != actual):
                raise BudgetConflict(
                    f"reservation {scope}/{operation_id} đã settle"
                    f" state={row.state} actual={row.actual} (yêu cầu actual={actual})"
                )
            return

        row.actual = actual
        row.state = "settled" if actual is not None else "unknown"
        row.resolved_at = datetime.now(UTC)
    except SQLAlchemyError as exc:
        raise BudgetUnavailable(type(exc).__name__) from exc
