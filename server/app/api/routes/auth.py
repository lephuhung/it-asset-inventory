"""Routes: auth."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.core.audit import append_audit
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_aes_gcm,
    generate_backup_codes,
    generate_totp_secret,
    hash_password,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.db.models import User, UserRole
from app.db.session import get_db
from app.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TotpConfirmRequest,
    TotpSetupResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


def _issue_tokens(user: User) -> LoginResponse:
    access = create_access_token(str(user.id), user.role, str(user.org_id))
    refresh = create_refresh_token(str(user.id))
    return LoginResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.rate_limit_login)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        await append_audit(db, action="auth.login_failed", actor=str(user.id) if user else None,
                           ip=request.client.host if request.client else None)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sai email hoặc mật khẩu")
    if not user.is_active:
        await append_audit(db, action="auth.login_blocked", actor=str(user.id),
                           ip=request.client.host if request.client else None)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Tài khoản đã bị khóa")

    if user.is_2fa_enabled:
        if not body.totp_code:
            # Yêu cầu nhập mã TOTP — trả requires_2fa
            return LoginResponse(access_token="", refresh_token="", requires_2fa=True)
        if not user.totp_secret_encrypted or not verify_totp(
            decrypt_aes_gcm(user.totp_secret_encrypted), body.totp_code
        ):
            await append_audit(db, action="auth.totp_failed", actor=str(user.id),
                               ip=request.client.host if request.client else None)
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Mã 2FA không đúng")

    await append_audit(db, action="auth.login", actor=str(user.id),
                       ip=request.client.host if request.client else None)
    await db.commit()
    return _issue_tokens(user)


@router.post("/refresh", response_model=LoginResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
        user_id = uuid.UUID(payload["sub"])
    except Exception:  # noqa: BLE001 — mọi lỗi giải mã/expired đều là token không hợp lệ
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token không hợp lệ")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User không tồn tại")
    return _issue_tokens(user)


@router.get("/me", response_model=dict)
async def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "org_id": str(user.org_id),
        "is_2fa_enabled": user.is_2fa_enabled,
    }


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(user: User = Depends(require_admin()), db: AsyncSession = Depends(get_db)):
    """Bật 2FA: sinh secret + backup codes."""
    secret = generate_totp_secret()
    uri = totp_uri(secret, user.email)
    codes = generate_backup_codes()
    # Lưu secret dạng mã hóa; backup codes lưu hash
    from app.core.security import encrypt_aes_gcm, hash_password
    user.totp_secret_encrypted = encrypt_aes_gcm(secret)
    user.backup_codes = [hash_password(c) for c in codes]  # type: ignore[attr-defined]
    user.is_2fa_enabled = False  # chờ confirm
    await db.commit()
    return TotpSetupResponse(secret=secret, uri=uri, backup_codes=codes)


@router.post("/totp/confirm", response_model=LoginResponse)
async def totp_confirm(
    body: TotpConfirmRequest,
    user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    if not user.totp_secret_encrypted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chưa thiết lập 2FA")
    if not verify_totp(decrypt_aes_gcm(user.totp_secret_encrypted), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Mã xác nhận không đúng")
    user.is_2fa_enabled = True
    await append_audit(db, action="auth.totp_enabled", actor=str(user.id))
    await db.commit()
    return _issue_tokens(user)


@router.post("/logout")
async def logout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await append_audit(db, action="auth.logout", actor=str(user.id))
    await db.commit()
    return {"ok": True}


# Seed admin khi app khởi động (chỉ môi trường dev/khởi tạo)
async def seed_admin(db: AsyncSession) -> None:
    existing = (await db.execute(select(User).where(User.email == settings.seed_admin_email))).scalar_one_or_none()
    if existing:
        return
    from sqlalchemy import select as _s

    from app.db.models import Organization, OrgType
    org = (await db.execute(_s(Organization).where(Organization.name == "Root"))).scalar_one_or_none()
    if org is None:
        org = Organization(name="Root", type=OrgType.ROOT.value)
        db.add(org)
        await db.flush()
    user = User(
        org_id=org.id,
        full_name=settings.seed_admin_full_name,
        email=settings.seed_admin_email,
        role=UserRole.SUPER_ADMIN.value,
        password_hash=hash_password(settings.seed_admin_password),
    )
    db.add(user)
    await db.commit()
