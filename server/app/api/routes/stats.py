"""Route stats — thống kê tổng quan dashboard."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, visible_org_ids
from app.db.models import EnrollToken, Machine, MachineCurrent, MachineSoftware, TokenStatus, User
from app.db.session import get_db
from app.schemas import InventoryStatsResponse, StatBucket, StatsOverview, TagOrgStat, TagStatItem, TagStatsResponse, TopSoftwareItem

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverview)
async def overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    visible = await visible_org_ids(db, user)
    qm = select(Machine).where(Machine.org_id.in_(visible))
    qt = select(EnrollToken).where(EnrollToken.org_id.in_(visible))

    machines = (await db.execute(qm)).scalars().all()
    tokens = (await db.execute(qt)).scalars().all()

    # Lazy-expire: token pending quá hạn → đánh dấu expired (phễu + KPI đúng logic)
    now = datetime.now(UTC)
    for t in tokens:
        if t.status == TokenStatus.PENDING.value and t.expires_at.replace(tzinfo=UTC) < now:
            t.status = TokenStatus.EXPIRED.value
    await db.commit()

    total = len(machines)
    online = sum(1 for m in machines if m.status == "online")
    offline = sum(1 for m in machines if m.status == "offline")
    lost = sum(1 for m in machines if m.status == "lost")
    pending = sum(1 for t in tokens if t.status == TokenStatus.PENDING.value)
    expired = sum(1 for t in tokens if t.status == TokenStatus.EXPIRED.value)

    # Phân loại máy — đếm theo tag classification (công vụ = official + bmnn).
    # Tag mục đích KHÔNG đụng vào — chỉ lọc kind='classification'.
    from app.db.models import MachineTag, Tag, TagKind

    class_rows = (
        await db.execute(
            select(Tag.key, func.count())
            .select_from(MachineTag)
            .join(Machine, Machine.id == MachineTag.machine_id)
            .join(Tag, Tag.id == MachineTag.tag_id)
            .where(
                Machine.org_id.in_(visible),
                MachineTag.kind == TagKind.CLASSIFICATION.value,
            )
            .group_by(Tag.key)
        )
    ).all()
    class_counts = {key: int(cnt) for key, cnt in class_rows}

    return StatsOverview(
        total_machines=total,
        online=online,
        offline=offline,
        lost=lost,
        pending_tokens=pending,
        expired_tokens=expired,
        personal=class_counts.get("personal", 0),
        official=class_counts.get("official", 0),
        bmnn=class_counts.get("bmnn", 0),
    )


def _bucket_key(value) -> str:
    """Chuẩn hóa key nhóm đếm: None → unknown; bool → true/false."""
    if value is None:
        return "unknown"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


# Thứ tự bucket RAM tăng dần (dùng cho cả SQL CASE và sắp xếp ở portal).
RAM_BUCKET_ORDER: tuple[str, ...] = ("<4 GB", "4–8 GB", "8–16 GB", "16–32 GB", "32+ GB", "unknown")


def _ram_bucket_expr(ram_col):
    """SQL CASE biểu thức nhóm RAM từ `machine_current.ram_gb`.

    Dùng thay vì GROUP BY trực tiếp lên cột float để có bucket rời rạc, dễ
    hiển thị và sắp xếp theo thứ tự tăng dần ở tầng portal. NULL → 'unknown'.
    Dùng `sqlalchemy.case` (top-level) — `func.case` không hỗ trợ tham số `else_`.
    """
    return func.coalesce(
        case(
            (ram_col.is_(None), "unknown"),
            (ram_col < 4, "<4 GB"),
            (ram_col < 8, "4–8 GB"),
            (ram_col < 16, "8–16 GB"),
            (ram_col < 32, "16–32 GB"),
            else_="32+ GB",
        ),
        "unknown",
    )


@router.get("/inventory", response_model=InventoryStatsResponse)
async def inventory_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = None,
    top_software_limit: int = Query(default=20, ge=1, le=100),
):
    """Thống kê cấu hình 'hiện tại' — Win10/11, update, firewall, antivirus, top phần mềm.

    Đọc từ `machine_current` (snapshot mới nhất/máy) + `machine_software` — GROUP BY SQL
    trên cột có index, không scan lịch sử JSONB. RBAC theo cây tổ chức (visible_org_ids);
    `org_id` chỉ định → lọc trong phạm vi được phép (403 nếu ngoài phạm vi).
    """
    visible = await visible_org_ids(db, user)
    if org_id and str(org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem thống kê tổ chức này")

    mc = MachineCurrent
    m = Machine
    scope = [m.org_id.in_(visible)]
    if org_id:
        scope = [m.org_id == org_id]

    async def bucket(col) -> list[StatBucket]:
        rows = (
            await db.execute(
                select(col, func.count())
                .select_from(mc)
                .join(m, m.id == mc.machine_id)
                .where(*scope)
                .group_by(col)
            )
        ).all()
        out = [StatBucket(key=_bucket_key(k), count=cnt) for k, cnt in rows]
        out.sort(key=lambda b: -b.count)
        return out

    total = (
        await db.execute(
            select(func.count()).select_from(mc).join(m, m.id == mc.machine_id).where(*scope)
        )
    ).scalar_one()

    top_rows = (
        await db.execute(
            select(
                func.max(MachineSoftware.name).label("name"),
                func.count(func.distinct(MachineSoftware.machine_id)).label("machines"),
            )
            .select_from(MachineSoftware)
            .join(m, m.id == MachineSoftware.machine_id)
            .where(*scope)
            .group_by(func.lower(MachineSoftware.name))
            .order_by(
                func.count(func.distinct(MachineSoftware.machine_id)).desc(),
                func.max(MachineSoftware.name),
            )
            .limit(top_software_limit)
        )
    ).all()
    top_software = [TopSoftwareItem(name=r.name, machines=r.machines) for r in top_rows]

    return InventoryStatsResponse(
        total_machines=total,
        by_os_family=await bucket(mc.os_family),
        by_os_arch=await bucket(func.upper(mc.os_arch)),
        by_is_vm=await bucket(mc.is_vm),
        by_ram_gb=await bucket(_ram_bucket_expr(mc.ram_gb)),
        by_windows_update_status=await bucket(mc.windows_update_status),
        by_windows_update_enabled=await bucket(mc.windows_update_enabled),
        by_firewall=await bucket(mc.firewall_enabled),
        by_antivirus=await bucket(mc.antivirus_enabled),
        by_bitlocker=await bucket(mc.bitlocker),
        top_software=top_software,
        generated_at=datetime.now(UTC),
    )


@router.get("/tags", response_model=TagStatsResponse)
async def tag_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Thống kê máy theo TAG — đếm số máy đang mang mỗi tag (classification + purpose).

    Trả về toàn bộ tag trong phạm vi user (visible_org_ids), kèm phân bố theo tổ chức
    để portal vẽ biểu đồ (donut / bar) khi người dùng chọn 1 tag. Mỗi máy có thể mang
    nhiều tag mục đích → máy được đếm ở MỌI tag nó mang.
    """
    from app.db.models import MachineTag, Organization, Tag

    visible = await visible_org_ids(db, user)
    if not visible:
        return TagStatsResponse(total_machines=0, tags=[])

    total = (
        await db.execute(select(func.count()).select_from(Machine).where(Machine.org_id.in_(visible)))
    ).scalar_one()

    # Đếm (tag, org) — join qua machine_tags; không nhân dòng vì group theo (tag, org).
    rows = (
        await db.execute(
            select(
                Tag.id,
                Tag.key,
                Tag.label,
                Tag.kind,
                Tag.color,
                Machine.org_id,
                func.count(),
            )
            .select_from(MachineTag)
            .join(Machine, Machine.id == MachineTag.machine_id)
            .join(Tag, Tag.id == MachineTag.tag_id)
            .where(Machine.org_id.in_(visible))
            .group_by(Tag.id, Tag.key, Tag.label, Tag.kind, Tag.color, Machine.org_id)
        )
    ).all()

    orgs = {
        o.id: o
        for o in (await db.execute(select(Organization).where(Organization.id.in_(visible)))).scalars()
    }

    # Gom theo tag → org_stats
    by_tag: dict[uuid.UUID, dict] = {}
    for tag_id, key, label, kind, color, org_id, cnt in rows:
        item = by_tag.setdefault(
            tag_id,
            {"key": key, "label": label, "kind": kind, "color": color, "orgs": {}},
        )
        item["orgs"][org_id] = int(cnt)

    tags: list[TagStatItem] = []
    for tag_id, item in by_tag.items():
        org_stats = [
            TagOrgStat(
                org_id=oid,
                org_name=orgs[oid].name,
                org_type=orgs[oid].type,
                count=cnt,
            )
            for oid, cnt in sorted(item["orgs"].items(), key=lambda kv: orgs[kv[0]].name)
        ]
        tags.append(
            TagStatItem(
                id=tag_id,
                key=item["key"],
                label=item["label"],
                kind=item["kind"],
                color=item["color"],
                count=sum(item["orgs"].values()),
                org_stats=org_stats,
            )
        )

    # Classification trước, purpose sau; trong kind sort theo label
    tags.sort(key=lambda t: (0 if t.kind == "classification" else 1, t.label))
    return TagStatsResponse(total_machines=total, tags=tags)