"""Route install — render script cài đặt động cho agent.

Mục 4.2 tài liệu gốc: GET /i/{token} → render install.ps1 với token nhúng.
Script: tải MSI → verify SHA256 + chữ ký Authenticode → msiexec /qn → tự enroll.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_token
from app.db.models import EnrollToken, TokenStatus
from app.db.session import get_db
from app.services.agent_settings import effective_agent_config

router = APIRouter(tags=["install"])

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"  # app/templates
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)


async def _validate_token(token: str, db: AsyncSession) -> EnrollToken:
    """Kiểm tra token còn dùng được không (chưa dùng/revoke/hết hạn)."""
    from datetime import UTC, datetime

    row = (
        await db.execute(select(EnrollToken).where(EnrollToken.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Token không tồn tại")
    if row.status == TokenStatus.USED.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token đã được sử dụng")
    if row.status == TokenStatus.REVOKED.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token đã bị thu hồi")
    if row.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token đã hết hạn")
    return row


@router.get("/i/{token}", response_class=PlainTextResponse)
async def render_install_script(token: str, db: AsyncSession = Depends(get_db)):
    """Render install.ps1 đầy đủ với token nhúng — gọi bởi `irm ... | iex`."""
    await _validate_token(token, db)
    agent_cfg = await effective_agent_config(db)
    template = jinja_env.get_template("install.ps1.j2")
    script = template.render(
        token=token,
        portal_url=settings.portal_url,
        agent_server_url=agent_cfg["agent_server_url"],
    )
    return PlainTextResponse(content=script, media_type="text/plain")
