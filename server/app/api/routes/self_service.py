"""Token chế độ B — link tự khai báo (mục 4.4 tài liệu gốc, Phase 2).

- Admin tạo link cho 1 tổ chức (`POST /api/self-service/links`) → URL công khai `/enroll/{code}`.
- Người dùng mở link → xem tên tổ chức → tự nhập thông tin → nhận lệnh cài 1 dòng
  (`POST /api/self-service/{code}/claim`) — token enroll thật được sinh, 1 token = 1 máy.
- Endpoints claim/info là public (không cần đăng nhập) — có rate-limit theo IP.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, visible_org_ids
from app.core.audit import append_audit
from app.core.config import settings
from app.core.security import generate_enroll_token, hash_token
from app.db.models import EnrollToken, Organization, SelfServiceLink, TokenStatus, User
from app.db.session import get_db
from app.schemas import (
    SelfServiceClaimRequest,
    SelfServiceInfoOut,
    SelfServiceLinkCreate,
    SelfServiceLinkOut,
    SelfServiceToggle,
    TokenCreateResponse,
)
from app.services.phone_encryption import encrypt_phone
from app.services.agent_settings import effective_agent_config

router = APIRouter(prefix="/api/self-service", tags=["self-service"])
limiter = Limiter(key_func=get_remote_address)


def _make_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]


def _install_command(token: str, portal_url: str, agent_server_url: str) -> str:
    """Lệnh cài 1 dòng: tải MSI → verify SHA256 → msiexec silent.

    KHÔNG dùng pattern `-EP Bypass`/`irm ... | iex` — Defender ML gắn cờ
    (Trojan:Win32/Commando.A!ml). Giữ logic giống tokens._install_command.
    """
    return (
        "powershell -NoProfile -c '"
        f'$t="{token}";'
        f'if(!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{Write-Host "Chay bang quyen Administrator";exit 1}};'
        f'$m="$env:TEMP\\agent-$t.msi";'
        f'irm "{portal_url}/download/agent.msi" -OutFile $m;'
        f'$a=(Get-FileHash $m -Algorithm SHA256).Hash.ToLower();'
        f'$b=(irm "{portal_url}/download/agent.msi.sha256").Trim().ToLower();'
        f'if($a -ne $b){{Write-Host "LOI: SHA256 khong khop - da dung cai dat";exit 1}};'
        f'msiexec /i $m /qn /norestart ENROLL_TOKEN=$t TOKEN=$t ENDPOINTS="{agent_server_url}"'
        "'"
    )


# ── Admin: quản lý link ─────────────────────────────────────────


@router.post("/links", response_model=SelfServiceLinkOut)
async def create_link(
    body: SelfServiceLinkCreate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    visible = await visible_org_ids(db, admin)
    if str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền tạo link cho tổ chức này")
    code = _make_code()
    while (await db.execute(select(SelfServiceLink).where(SelfServiceLink.code == code))).first():
        code = _make_code()
    link = SelfServiceLink(org_id=body.org_id, code=code, created_by=admin.id)
    db.add(link)
    await append_audit(db, action="self_service.link_create", actor=str(admin.id), target=str(link.id))
    await db.commit()
    return await _to_out(db, link)


@router.get("/links", response_model=list[SelfServiceLinkOut])
async def list_links(
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    visible = await visible_org_ids(db, admin)
    rows = (
        (await db.execute(select(SelfServiceLink).order_by(SelfServiceLink.created_at.desc()))).scalars().all()
    )
    return [await _to_out(db, l) for l in rows if str(l.org_id) in visible]


@router.patch("/links/{link_id}", response_model=SelfServiceLinkOut)
async def toggle_link(
    link_id: uuid.UUID,
    body: SelfServiceToggle,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    link = (await db.execute(select(SelfServiceLink).where(SelfServiceLink.id == link_id))).scalar_one_or_none()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link không tồn tại")
    visible = await visible_org_ids(db, admin)
    if str(link.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền thao tác link này")
    link.enabled = body.enabled
    await db.commit()
    return await _to_out(db, link)


@router.delete("/links/{link_id}")
async def delete_link(
    link_id: uuid.UUID,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    link = (await db.execute(select(SelfServiceLink).where(SelfServiceLink.id == link_id))).scalar_one_or_none()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link không tồn tại")
    visible = await visible_org_ids(db, admin)
    if str(link.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xóa link này")
    await db.delete(link)
    await db.commit()
    return {"ok": True}


async def _to_out(db: AsyncSession, link: SelfServiceLink) -> SelfServiceLinkOut:
    org = (
        await db.execute(select(Organization).where(Organization.id == link.org_id))
    ).scalar_one_or_none()
    agent_cfg = await effective_agent_config(db)
    return SelfServiceLinkOut(
        id=link.id,
        org_id=link.org_id,
        org_name=org.name if org else None,
        code=link.code,
        url=f"{agent_cfg['portal_url']}/enroll/{link.code}",
        enabled=link.enabled,
        created_at=link.created_at,
    )


# ── Public: tự khai báo ─────────────────────────────────────────


@router.get("/{code}", response_model=SelfServiceInfoOut)
async def link_info(code: str, db: AsyncSession = Depends(get_db)):
    """Thông tin công khai của link (tên tổ chức) — không cần đăng nhập."""
    link = (
        await db.execute(select(SelfServiceLink).where(SelfServiceLink.code == code))
    ).scalar_one_or_none()
    if link is None or not link.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link không tồn tại hoặc đã bị khóa")
    org = (
        await db.execute(select(Organization).where(Organization.id == link.org_id))
    ).scalar_one_or_none()
    return SelfServiceInfoOut(org_id=link.org_id, org_name=org.name if org else "—", link_id=link.id)


@router.post("/{code}/claim", response_model=TokenCreateResponse)
@limiter.limit("5/minute")
async def claim(
    request: Request,
    code: str,
    body: SelfServiceClaimRequest,
    db: AsyncSession = Depends(get_db),
):
    """Người dùng tự khai báo → nhận lệnh cài đặt (token 1 lần)."""
    link = (
        await db.execute(select(SelfServiceLink).where(SelfServiceLink.code == code))
    ).scalar_one_or_none()
    if link is None or not link.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link không tồn tại hoặc đã bị khóa")

    token = generate_enroll_token()
    row = EnrollToken(
        token_hash=hash_token(token),
        org_id=link.org_id,
        created_by=link.created_by,
        full_name=body.full_name,
        department=body.department,
        position=body.position,
        email=body.email,
        phone_encrypted=encrypt_phone(body.phone) if body.phone else None,
        note=body.note,
        expires_at=datetime.now(UTC) + timedelta(hours=72),
        status=TokenStatus.PENDING.value,
    )
    db.add(row)
    await append_audit(
        db,
        action="token.create",
        actor=f"self-service:{code}",
        target=str(row.id),
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    agent_cfg = await effective_agent_config(db)
    return TokenCreateResponse(
        token=token,
        install_command=_install_command(token, agent_cfg["portal_url"], agent_cfg["agent_server_url"]),
        expires_at=row.expires_at,
    )