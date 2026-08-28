"""Route tokens — portal sinh/liệt kê/revoke token enroll."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, visible_org_ids
from app.core.audit import append_audit
from app.core.config import settings
from app.core.security import generate_enroll_token, hash_token
from app.db.models import EnrollToken, TokenStatus, User
from app.db.session import get_db
from app.schemas import (
    BulkTokenRequest,
    BulkTokenResponse,
    Page,
    TokenCreateRequest,
    TokenCreateResponse,
    TokenListItem,
    TokenRevokeRequest,
)
from app.services.phone_encryption import encrypt_phone, mask_phone
from app.services.agent_settings import effective_agent_config

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


def _install_command(token: str, portal_url: str, agent_server_url: str) -> str:
    """Lệnh cài 1 dòng: tải MSI → verify SHA256 → msiexec silent.

    KHÔNG dùng pattern `powershell -EP Bypass -c "irm ... | iex"` — Defender ML
    gắn cờ pattern download-and-execute (Trojan:Win32/Commando.A!ml).

    Dùng `-EncodedCommand` (base64 UTF-16LE): copy-paste vào cmd.exe HAY PowerShell
    đều chạy đúng — không bị shell bóc dấu nháy (cmd bóc `"`, còn `'...'` thì
    PowerShell chỉ in ra string mà KHÔNG thực thi — lỗi đã gặp thực tế).
    """
    import base64

    script = (
        f'$t="{token}";'
        f'if(!([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{Write-Host "Chay bang quyen Administrator";exit 1}};'
        f'$m="$env:TEMP\\agent-$t.msi";'
        f'irm "{portal_url}/download/agent.msi" -OutFile $m;'
        f'$a=(Get-FileHash $m -Algorithm SHA256).Hash.ToLower();'
        f'$b=(irm "{portal_url}/download/agent.msi.sha256").Trim().ToLower();'
        f'if($a -ne $b){{Write-Host "LOI: SHA256 khong khop - da dung cai dat";exit 1}};'
        f'msiexec /i $m /qn /norestart ENROLL_TOKEN=$t TOKEN=$t ENDPOINTS="{agent_server_url}"'
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -EncodedCommand {encoded}"


@router.post("/bulk", response_model=BulkTokenResponse)
async def create_tokens_bulk(
    body: BulkTokenRequest,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Import hàng loạt (bulk import CSV — mục 4.4): 1 dòng = 1 token = 1 máy."""
    visible = await visible_org_ids(db, admin)
    if str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền sinh token cho tổ chức này")

    expires = datetime.now(UTC) + timedelta(hours=body.ttl_hours)
    agent_cfg = await effective_agent_config(db)
    portal_url = agent_cfg["portal_url"]
    tokens_out: list[TokenCreateResponse] = []
    for item in body.items:
        token = generate_enroll_token()
        row = EnrollToken(
            token_hash=hash_token(token),
            org_id=body.org_id,
            created_by=admin.id,
            full_name=item.full_name,
            department=item.department,
            position=item.position,
            email=item.email,
            phone_encrypted=encrypt_phone(item.phone) if item.phone else None,
            note=item.note,
            expires_at=expires,
            status=TokenStatus.PENDING.value,
        )
        db.add(row)
        tokens_out.append(
            TokenCreateResponse(
                token=token,
                install_command=_install_command(token, portal_url, agent_cfg["agent_server_url"]),
                expires_at=expires,
            )
        )
    await append_audit(
        db,
        action="token.bulk_create",
        actor=str(admin.id),
        target=f"org:{body.org_id}:{len(tokens_out)}",
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return BulkTokenResponse(created=len(tokens_out), tokens=tokens_out)


@router.post("", response_model=TokenCreateResponse)
async def create_token(
    body: TokenCreateRequest,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Sinh token enroll (1 token = 1 máy, TTL mặc định 72h)."""
    # Chỉ sinh token cho tổ chức trong phạm vi quyền (org mình + cấp dưới)
    visible = await visible_org_ids(db, admin)
    if str(body.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền sinh token cho tổ chức này")
    token = generate_enroll_token()
    expires = datetime.now(UTC) + timedelta(hours=body.ttl_hours)
    row = EnrollToken(
        token_hash=hash_token(token),
        org_id=body.org_id,
        created_by=admin.id,
        full_name=body.full_name,
        department=body.department,
        position=body.position,
        email=body.email,
        phone_encrypted=encrypt_phone(body.phone) if body.phone else None,
        note=body.note,
        expires_at=expires,
        status=TokenStatus.PENDING.value,
    )
    db.add(row)
    await append_audit(
        db,
        action="token.create",
        actor=str(admin.id),
        target=str(row.id),
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    # install command — tải MSI + verify SHA256 + msiexec (không dùng /i/{token} | iex)
    agent_cfg = await effective_agent_config(db)

    command = _install_command(token, agent_cfg["portal_url"], agent_cfg["agent_server_url"])
    return TokenCreateResponse(token=token, install_command=command, expires_at=expires)


@router.get("", response_model=Page[TokenListItem])
async def list_tokens(
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
    org_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    from sqlalchemy import func as sa_func

    q = select(EnrollToken)
    visible = await visible_org_ids(db, admin)
    q = q.where(EnrollToken.org_id.in_(visible))
    if org_id:
        if str(org_id) not in visible:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem token của tổ chức này")
        q = q.where(EnrollToken.org_id == org_id)

    total = (await db.execute(select(sa_func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(q.order_by(EnrollToken.expires_at.desc()).limit(limit).offset(offset))
    ).scalars().all()

    # Lazy-expire: token còn "pending" nhưng đã quá hạn → đánh dấu expired để phễu
    # triển khai và KPI "token hết hạn" luôn đúng logic (không chờ enroll chạm vào).
    now = datetime.now(UTC)
    expired_ids: list[uuid.UUID] = []
    for r in rows:
        if r.status == TokenStatus.PENDING.value and r.expires_at.replace(tzinfo=UTC) < now:
            r.status = TokenStatus.EXPIRED.value
            expired_ids.append(r.id)
    if expired_ids:
        await db.commit()
        for r in rows:  # refresh status sau commit
            await db.refresh(r)

    return Page[TokenListItem](
        items=[
            TokenListItem(
                id=r.id,
                full_name=r.full_name,
                department=r.department,
                email=r.email,
                phone_masked=mask_phone(r.phone_encrypted),
                status=TokenStatus(r.status),
                expires_at=r.expires_at,
                created_at=r.created_at if hasattr(r, "created_at") else r.expires_at,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/revoke")
async def revoke_token(
    body: TokenRevokeRequest,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(EnrollToken).where(EnrollToken.id == body.token_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Token không tồn tại")
    visible = await visible_org_ids(db, admin)
    if str(row.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền thu hồi token này")
    if row.status == TokenStatus.USED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Token đã dùng — không revoke được")
    row.status = TokenStatus.REVOKED.value
    await append_audit(
        db, action="token.revoke", actor=str(admin.id), target=str(row.id),
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return {"ok": True}
