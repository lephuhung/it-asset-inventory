"""Route tổ chức — cây tổ chức (UBND cấp xã / Sở ban ngành + cấp dưới).

- `GET /api/orgs`            : cây tổ chức trong phạm vi user (super admin thấy tất cả,
                               org admin/viewer thấy org mình + cấp dưới).
- `POST /api/orgs`           : tạo tổ chức — "Thêm UBND cấp xã" / "Thêm Sở ban ngành"
                               (chỉ Super Admin tạo cấp này); org admin tạo cấp con
                               (phòng / đơn vị trực thuộc) trong phạm vi của mình.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, is_super_admin, require_admin, visible_org_ids
from app.core.audit import append_audit
from app.db.models import Organization, OrgType, User
from app.db.session import get_db
from app.schemas import OrganizationCreate, OrganizationNode, OrgMachineStat

router = APIRouter(prefix="/api/orgs", tags=["orgs"])

_HIGH_LEVEL_TYPES = {OrgType.UBND_XA.value, OrgType.SO_BAN_NGANH.value}
_VALID_CREATE_TYPES = {
    OrgType.UBND_XA.value,
    OrgType.SO_BAN_NGANH.value,
    OrgType.PHONG.value,
    OrgType.DON_VI.value,
}


def _to_node(o: Organization) -> OrganizationNode:
    return OrganizationNode(id=o.id, parent_id=o.parent_id, name=o.name, type=o.type, children=[])


def _sort_tree(nodes: list[OrganizationNode]) -> None:
    nodes.sort(key=lambda n: n.name)
    for n in nodes:
        _sort_tree(n.children)


@router.get("", response_model=list[OrganizationNode])
async def list_orgs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cây tổ chức trong phạm vi quyền của user (hỗ trợ hiển thị + chọn phạm vi)."""
    visible = await visible_org_ids(db, user)
    rows = (
        (await db.execute(select(Organization).order_by(Organization.name))).scalars().all()
    )
    nodes: dict[str, OrganizationNode] = {
        str(o.id): _to_node(o) for o in rows if str(o.id) in visible
    }
    roots: list[OrganizationNode] = []
    for node in nodes.values():
        parent = str(node.parent_id) if node.parent_id else ""
        if parent in nodes:
            nodes[parent].children.append(node)
        else:
            roots.append(node)
    _sort_tree(roots)
    return roots


@router.post("", response_model=OrganizationNode)
async def create_org(
    body: OrganizationCreate,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Tạo tổ chức — ghi audit log.

    - Super Admin: tạo UBND cấp xã / Sở ban ngành (parent tùy ý, kể cả gốc cây).
    - Org Admin  : chỉ tạo cấp con (phòng / đơn vị trực thuộc) dưới tổ chức của mình
                   (hoặc cấp dưới trong cây) — không tạo UBND xã / Sở ban ngành.
    """
    if body.type not in _VALID_CREATE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Loại tổ chức không hợp lệ")

    visible = await visible_org_ids(db, admin)

    if body.parent_id and str(body.parent_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo tổ chức dưới cấp này")

    if not is_super_admin(admin):
        if body.type in _HIGH_LEVEL_TYPES:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Chỉ Super Admin được tạo UBND cấp xã / Sở ban ngành",
            )
        if not body.parent_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Admin tổ chức phải chỉ định cấp trên (thuộc phạm vi của mình)",
            )

    org = Organization(name=body.name, type=body.type, parent_id=body.parent_id)
    db.add(org)
    await append_audit(
        db,
        action="org.create",
        actor=str(admin.id),
        target=str(org.id),
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return _to_node(org)

@router.get("/machine-stats", response_model=list[OrgMachineStat])
async def org_machine_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Thống kê số máy theo tổ chức — tách máy có agent (đã heartbeat ≥ 1 lần)
    và máy cách ly (chỉ có mặt qua import offline, không bao giờ heartbeat).

    Máy `pending` (chờ duyệt enroll) liệt kê riêng vì chưa thuộc nhóm nào.
    """
    from sqlalchemy import case, func

    from app.db.models import Heartbeat, Machine

    visible = await visible_org_ids(db, user)
    if not visible:
        return []

    agent_sq = select(Heartbeat.machine_id).distinct().subquery()
    rows = (
        await db.execute(
            select(
                Machine.org_id,
                func.count().label("total"),
                func.count(agent_sq.c.machine_id).label("with_agent"),
                func.sum(case((Machine.status == "pending", 1), else_=0)).label("pending"),
            )
            .outerjoin(agent_sq, agent_sq.c.machine_id == Machine.id)
            .where(Machine.org_id.in_(visible))
            .group_by(Machine.org_id)
        )
    ).all()

    orgs = {
        o.id: o
        for o in (
            await db.execute(select(Organization).where(Organization.id.in_(visible)))
        ).scalars()
    }

    stats: list[OrgMachineStat] = []
    for org_id, total, with_agent, pending in rows:
        org = orgs.get(org_id)
        if org is None:
            continue
        p = int(pending or 0)
        w = int(with_agent or 0)
        stats.append(
            OrgMachineStat(
                org_id=org_id,
                org_name=org.name,
                org_type=org.type,
                total=int(total),
                with_agent=w,
                isolated=int(total) - w - p,
                pending=p,
            )
        )
    stats.sort(key=lambda s: s.org_name)
    return stats
