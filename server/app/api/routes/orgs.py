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
from app.schemas import OrganizationCreate, OrganizationNode

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