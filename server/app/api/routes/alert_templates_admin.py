"""Alert templates CRUD — Super Admin only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.db.models import User
from app.schemas import (
    AlertTemplateOut,
    AlertTemplatePreviewIn,
    AlertTemplatePreviewOut,
    AlertTemplateUpdateIn,
)
from app.services.alert_templates import (
    get_template,
    list_templates,
    render_template,
    update_template,
    validate_template_vars,
)

router = APIRouter(prefix="/api/admin/alert-templates", tags=["admin-alert-templates"])


def _to_out(t) -> AlertTemplateOut:
    return AlertTemplateOut(
        id=t.id, code=t.code, name=t.name, description=t.description,
        category=t.category, default_severity=t.default_severity,
        title_template=t.title_template, body_template=t.body_template,
        opt_out_controls=t.opt_out_controls or [],
        allowed_vars=t.allowed_vars or [],
        default_config=t.default_config or {},
        enabled=t.enabled, updated_at=t.updated_at,
    )


@router.get("", response_model=list[AlertTemplateOut])
async def list_templates_endpoint(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    rows = await list_templates(db)
    return [_to_out(t) for t in rows]


@router.get("/{code}", response_model=AlertTemplateOut)
async def get_template_endpoint(
    code: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    row = await get_template(db, code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template không tồn tại")
    return _to_out(row)


@router.patch("/{code}", response_model=AlertTemplateOut)
async def update_template_endpoint(
    code: str,
    body: AlertTemplateUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    row = await update_template(db, code, body, admin)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template không tồn tại")
    return _to_out(row)


@router.post("/{code}/preview", response_model=AlertTemplatePreviewOut)
async def preview_template(
    code: str,
    body: AlertTemplatePreviewIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin()),
):
    row = await get_template(db, code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template không tồn tại")
    ctx = body.context or {}
    title = render_template(row.title_template, row.allowed_vars or [], ctx)
    body_text = render_template(row.body_template or "", row.allowed_vars or [], ctx) or None
    warnings = validate_template_vars(row.title_template, row.body_template, row.allowed_vars or [])
    return AlertTemplatePreviewOut(title=title, body=body_text, warnings=warnings)
