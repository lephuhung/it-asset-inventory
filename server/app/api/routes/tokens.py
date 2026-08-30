"""Route tokens — portal sinh/liệt kê/revoke token enroll."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, visible_org_ids
from app.core.client_ip import get_client_ip
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


def _install_command_linux(token: str, portal_url: str, agent_server_url: str) -> str:
    """One-liner cài cho Linux: `curl -fsSL https://host/i/<token> | sudo bash`.

    Tự detect distro + architecture → tải .deb hoặc .rpm phù hợp → verify SHA256
    → cài package → ghi /etc/orginventory/config.json → enable systemd service.

    Lưu ý: URL dùng cho download script là portal_url (Portal có route /i/<token>
    render install-online.sh động). portal_url phải là URL mà user từ xa truy cập
    được (KHÔNG phải localhost).
    """
    return f"curl -fsSL {portal_url}/i/{token} | sudo bash"


def _install_command(token: str, portal_url: str, agent_server_url: str) -> str:
    """Lệnh cài 1 dòng: tải MSI → verify SHA256 → msiexec silent.

    QUAN TRỌNG — URL dùng để tải MSI là `portal_url` (Portal Next.js proxy `/api/downloads/*`
    về FastAPI `/download/*`). portal_url phải là URL public — user copy lệnh và chạy
    trên máy từ xa, browser/PowerShell từ máy đó phải truy cập được. KHÔNG dùng
    `http://localhost:3003` khi user từ xa — phải là IP LAN (vd `http://10.10.0.241:3003`)
    hoặc domain thật.

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


def _validate_install_urls(portal_url: str, agent_server_url: str) -> list[str]:
    """Cảnh báo khi URL dùng cho install command chưa public.

    Trả về danh sách cảnh báo (text). Mỗi phần tử là 1 vấn đề. Empty list = OK.
    Frontend sẽ hiển thị banner cảnh báo cho admin.
    """
    warnings: list[str] = []
    if not portal_url or portal_url.startswith("http://localhost") or "127.0.0.1" in portal_url:
        warnings.append(
            f"Portal URL hiện tại là '{portal_url}'. Script cài sẽ fail trên máy user ở xa. "
            "Cập nhật Portal URL trong Cấu hình agent (vd 'http://10.10.0.241:3003' cho LAN, "
            "hoặc 'https://portal.example.gov.vn' cho production)."
        )
    if not agent_server_url or agent_server_url.startswith("http://localhost") or "127.0.0.1" in agent_server_url:
        warnings.append(
            f"Agent server URL hiện tại là '{agent_server_url}'. Sau khi cài, agent sẽ không "
            "gửi heartbeat/inventory được. Cập nhật Agent server URL trong Cấu hình agent."
        )
    return warnings


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
            classification=body.classification,
            purpose_tags=body.purpose_tags or [],
        )
        db.add(row)
        cmd_win = _install_command(token, portal_url, agent_cfg["agent_server_url"])
        cmd_linux = _install_command_linux(token, portal_url, agent_cfg["agent_server_url"])
        offline_url = f"{portal_url}/download/offline-package.zip"
        warnings = _validate_install_urls(portal_url, agent_cfg["agent_server_url"])
        tokens_out.append(
            TokenCreateResponse(
                token=token,
                install_command=cmd_win,
                install_command_windows=cmd_win,
                install_command_linux=cmd_linux,
                install_offline_url=offline_url,
                install_url_warnings=warnings,
                expires_at=expires,
            )
        )
    await append_audit(
        db,
        action="token.bulk_create",
        actor=str(admin.id),
        target=f"org:{body.org_id}:{len(tokens_out)}",
        ip=get_client_ip(request),
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
        # Loại máy + tag mục đích — áp cho máy khi enroll (mặc định công vụ).
        classification=body.classification,
        purpose_tags=body.purpose_tags or [],
    )
    db.add(row)
    await append_audit(
        db,
        action="token.create",
        actor=str(admin.id),
        target=str(row.id),
        ip=get_client_ip(request),
    )
    await db.commit()

    # install command — tải MSI + verify SHA256 + msiexec (không dùng /i/{token} | iex)
    agent_cfg = await effective_agent_config(db)
    portal_url = agent_cfg["portal_url"]

    cmd_win = _install_command(token, portal_url, agent_cfg["agent_server_url"])
    cmd_linux = _install_command_linux(token, portal_url, agent_cfg["agent_server_url"])
    offline_url = f"{portal_url}/download/offline-package.zip"
    warnings = _validate_install_urls(portal_url, agent_cfg["agent_server_url"])
    return TokenCreateResponse(
        token=token,
        install_command=cmd_win,
        install_command_windows=cmd_win,
        install_command_linux=cmd_linux,
        install_offline_url=offline_url,
        install_url_warnings=warnings,
        expires_at=expires,
    )


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
        ip=get_client_ip(request),
    )
    await db.commit()
    return {"ok": True}


@router.post("/{token_id}/reissue", response_model=TokenCreateResponse)
async def reissue_token(
    token_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Tái sinh install command khi Portal/Agent URL đã thay đổi.

    Lý do: install_command sinh tại thời điểm tạo token, không lưu DB. Nếu admin
    đổi Portal/Agent URL sau khi token đã phát cho user, script cũ vẫn trỏ
    về URL cũ → user chạy fail. Endpoint này:
    1. Tạo token MỚI (giữ nguyên full_name/department/etc) — user copy lệnh mới.
    2. Mark token cũ là 'superseded' (không revoke — vẫn dùng được nếu user đã nhận).
    3. Trả về install command dựng lại từ URL cấu hình hiện tại.

    Bảo mật: chỉ admin trong phạm vi org mới tái sinh được.
    """
    old = (await db.execute(select(EnrollToken).where(EnrollToken.id == token_id))).scalar_one_or_none()
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Token không tồn tại")
    visible = await visible_org_ids(db, admin)
    if str(old.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền thao tác token này")
    if old.status in (TokenStatus.USED.value, TokenStatus.REVOKED.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Token đã {old.status} — không tái sinh được. Sinh token mới.",
        )

    # Tạo token mới với cùng metadata; expires tính lại từ giờ.
    from datetime import UTC, timedelta
    agent_cfg = await effective_agent_config(db)
    portal_url = agent_cfg["portal_url"]

    new_token = generate_enroll_token()
    new_row = EnrollToken(
        token_hash=hash_token(new_token),
        org_id=old.org_id,
        created_by=admin.id,
        full_name=old.full_name,
        department=old.department,
        position=old.position,
        email=old.email,
        phone_encrypted=old.phone_encrypted,
        note=(old.note or "") + " [reissue]",
        expires_at=datetime.now(UTC) + timedelta(hours=72),
        status=TokenStatus.PENDING.value,
        classification=old.classification,
        purpose_tags=old.purpose_tags or [],
    )
    db.add(new_row)

    # Mark token cũ là 'superseded' (1 token cũ 1 token mới). KHÔNG revoke — nếu user
    # đã nhận token cũ và cấu hình URL mới chưa được apply, họ vẫn dùng được token cũ
    # (chỉ fail nếu URL cũ đã chết). Khi token cũ expire unused → tự động cleanup.
    old.note = (old.note or "") + f" [superseded by {new_row.id}]"

    await db.flush()  # lấy new_row.id

    await append_audit(
        db, action="token.reissue", actor=str(admin.id), target=str(new_row.id),
        ip=get_client_ip(request),
    )
    await db.commit()

    cmd_win = _install_command(new_token, portal_url, agent_cfg["agent_server_url"])
    cmd_linux = _install_command_linux(new_token, portal_url, agent_cfg["agent_server_url"])
    offline_url = f"{portal_url}/download/offline-package.zip"
    warnings = _validate_install_urls(portal_url, agent_cfg["agent_server_url"])
    return TokenCreateResponse(
        token=new_token,
        install_command=cmd_win,
        install_command_windows=cmd_win,
        install_command_linux=cmd_linux,
        install_offline_url=offline_url,
        install_url_warnings=warnings,
        expires_at=new_row.expires_at,
    )
