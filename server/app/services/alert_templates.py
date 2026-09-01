"""CRUD + render cho alert templates (Super Admin quản lý)."""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AlertTemplate, User

logger = logging.getLogger("alert_templates")

_VAR_RE = re.compile(r"\{(\w+)\}")

ALLOWED_OPT_OUT_CONTROLS = {"template", "severity"}


def render_template(text: str, allowed_vars: list[str], context: dict) -> str:
    """Render template string. Biến thiếu → substitute `[MISSING: varname]`.

    Không raise — gọi từ alert_engine (delivery không được chết vì template lỗi).
    """
    if not text:
        return ""
    allowed = set(allowed_vars or [])

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in allowed:
            return f"[MISSING: {name}]"
        val = context.get(name)
        if val is None:
            return f"[MISSING: {name}]"
        return str(val)

    return _VAR_RE.sub(_sub, text)


def validate_template_vars(title: str, body: str | None, allowed_vars: list[str]) -> list[str]:
    """Trả list biến xuất hiện trong template nhưng KHÔNG có trong allowed_vars."""
    allowed = set(allowed_vars or [])
    found: set[str] = set()
    found.update(_VAR_RE.findall(title))
    if body:
        found.update(_VAR_RE.findall(body))
    return sorted(found - allowed)


async def list_templates(
    db: AsyncSession, *, enabled_only: bool = False
) -> list[AlertTemplate]:
    stmt = select(AlertTemplate).order_by(AlertTemplate.category, AlertTemplate.code)
    if enabled_only:
        stmt = stmt.where(AlertTemplate.enabled.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_template(db: AsyncSession, code: str) -> AlertTemplate | None:
    return (await db.execute(
        select(AlertTemplate).where(AlertTemplate.code == code)
    )).scalar_one_or_none()


async def update_template(
    db: AsyncSession, code: str, body, admin: User
) -> AlertTemplate | None:
    """Cập nhật template theo `body` (Pydantic AlertTemplateUpdateIn).

    Validate: opt_out_controls ⊆ {"template","severity"}; biến trong title/body
    phải nằm trong allowed_vars (chỉ chặn nếu allowed_vars được cung cấp).
    """
    row = (await db.execute(
        select(AlertTemplate).where(AlertTemplate.code == code)
    )).scalar_one_or_none()
    if row is None:
        return None

    # Validate opt_out_controls
    if body.opt_out_controls is not None:
        bad = set(body.opt_out_controls) - ALLOWED_OPT_OUT_CONTROLS
        if bad:
            from fastapi import HTTPException, status
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"opt_out_controls không hợp lệ: {sorted(bad)} (chỉ chấp nhận template/severity)",
            )

    # Validate vars nếu cả title/body lẫn allowed_vars cùng được cung cấp
    new_allowed = body.allowed_vars if body.allowed_vars is not None else (row.allowed_vars or [])
    new_title = body.title_template if body.title_template is not None else row.title_template
    new_body = body.body_template if body.body_template is not None else row.body_template
    warnings = validate_template_vars(new_title, new_body, new_allowed)
    if warnings:
        from fastapi import HTTPException, status
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Template dùng biến không khai báo trong allowed_vars: {warnings}",
        )

    for field in ("name", "description", "category", "default_severity",
                  "title_template", "body_template", "opt_out_controls",
                  "allowed_vars", "default_config", "enabled"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, val)

    row.updated_by = admin.id
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    logger.info("Super Admin %s updated template %s", admin.email, code)
    return row
