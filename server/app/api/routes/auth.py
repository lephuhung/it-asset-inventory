"""Routes: auth."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_allow_password_change
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip, rate_limit_key
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_aes_gcm,
    generate_backup_codes,
    generate_totp_secret,
    hash_password,
    hash_token,
    totp_uri,
    verify_password,
    verify_totp_counter,
)
from app.db.models import RefreshToken, User, UserRole
from app.db.session import get_db
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    SelfProfileUpdateRequest,
    TotpConfirmRequest,
    TotpDisableRequest,
    TotpSetupResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=rate_limit_key)


async def _issue_tokens(
    user: User, db: AsyncSession, family_id: uuid.UUID | None = None
) -> LoginResponse:
    """Phát access + refresh token. Refresh token chỉ lưu SHA-256 hash vào DB —
    rotation/revoke/reuse-detection đều dựa trên bảng `refresh_tokens`."""
    access = create_access_token(str(user.id), user.role, str(user.org_id))
    refresh = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        must_change_password=user.must_change_password,
    )


async def _revoke_user_refresh_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Thu hồi mọi refresh token của user (đổi/reset mật khẩu...)."""
    from sqlalchemy import update

    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def _revoke_refresh_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    """Thu hồi toàn bộ family — dùng khi phát hiện replay refresh token."""
    from sqlalchemy import update

    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.rate_limit_login)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    from app.db.seed_org_admins import resolve_login_username

    login_id = body.email.strip().lower()
    resolved_u = resolve_login_username(login_id)
    candidates = {
        login_id,
        f"{login_id}@hatinh.gov.vn",
        f"{login_id}@example.gov.vn",
        f"{resolved_u}@hatinh.gov.vn",
        f"{resolved_u}@example.gov.vn",
    }
    user = (await db.execute(select(User).where(User.email.in_(candidates)))).scalars().first()
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        await append_audit(db, action="auth.login_failed", actor=str(user.id) if user else None,
                           ip=get_client_ip(request))
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sai email hoặc mật khẩu")
    if not user.is_active:
        await append_audit(db, action="auth.login_blocked", actor=str(user.id),
                           ip=get_client_ip(request))
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Tài khoản đã bị khóa")

    if user.is_2fa_enabled:
        if not body.totp_code:
            # Yêu cầu nhập mã TOTP — trả requires_2fa
            return LoginResponse(access_token="", refresh_token="", requires_2fa=True)
        ok = False
        if user.totp_secret_encrypted:
            counter = verify_totp_counter(
                decrypt_aes_gcm(user.totp_secret_encrypted), body.totp_code
            )
            # Chống replay: từ chối mã của counter đã từng được chấp nhận
            if counter is not None and counter > (user.totp_last_counter or -1):
                user.totp_last_counter = counter
                ok = True
        if not ok:
            # Fallback backup code (dùng 1 lần) — user mất thiết bị 2FA
            codes = list(user.backup_codes or [])
            matched = next(
                (h for h in codes if verify_password(body.totp_code, h)), None
            )
            if matched is not None:
                codes.remove(matched)
                user.backup_codes = codes
                ok = True
        if not ok:
            await append_audit(db, action="auth.totp_failed", actor=str(user.id),
                               ip=get_client_ip(request))
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Mã 2FA không đúng")

    # Đánh dấu kích hoạt: lần đăng nhập thành công gần nhất (sau khi qua 2FA nếu có)
    user.last_login_at = datetime.now(UTC)
    await append_audit(db, action="auth.login", actor=str(user.id),
                       ip=get_client_ip(request))
    resp = await _issue_tokens(user, db)
    await db.commit()
    return resp


@router.post("/refresh", response_model=LoginResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
        user_id = uuid.UUID(payload["sub"])
    except Exception:  # noqa: BLE001 — mọi lỗi giải mã/expired đều là token không hợp lệ
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token không hợp lệ")

    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token))
        )
    ).scalar_one_or_none()
    if row is None or row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token không hợp lệ")
    if row.revoked_at is not None:
        # Token hợp lệ về chữ ký nhưng đã bị rotate/revoke → đang bị replay.
        # Thu hồi toàn bộ family để chặn cả session lẫn kẻ trộm.
        await _revoke_refresh_family(db, row.family_id)
        await append_audit(
            db, action="auth.refresh_reuse_detected", actor=str(row.user_id),
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token không hợp lệ")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User không tồn tại")

    # Rotation: token cũ revoke ngay, token mới kế thừa family.
    row.revoked_at = datetime.now(UTC)
    resp = await _issue_tokens(user, db, family_id=row.family_id)
    await db.flush()
    # replaced_by = id của row token mới vừa add (lấy qua hash)
    new_row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(resp.refresh_token))
        )
    ).scalar_one_or_none()
    if new_row is not None:
        row.replaced_by = new_row.id
    await db.commit()
    return resp


@router.get("/me", response_model=dict)
async def me(user: User = Depends(get_current_user_allow_password_change)):
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "org_id": str(user.org_id),
        "is_2fa_enabled": user.is_2fa_enabled,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.totp_secret_encrypted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chưa thiết lập 2FA")
    counter = verify_totp_counter(decrypt_aes_gcm(user.totp_secret_encrypted), body.code)
    if counter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Mã xác nhận không đúng")
    user.is_2fa_enabled = True
    # Ghi nhận counter của mã confirm — mã này không được phép replay ở login.
    user.totp_last_counter = counter
    await append_audit(db, action="auth.totp_enabled", actor=str(user.id))
    resp = await _issue_tokens(user, db)
    await db.commit()
    return resp


@router.post("/logout")
async def logout(
    body: RefreshRequest | None = None,
    user: User = Depends(get_current_user_allow_password_change),
    db: AsyncSession = Depends(get_db),
):
    """Logout: revoke refresh token được gửi kèm (nếu có) để kết thúc phiên."""
    if body and body.refresh_token:
        row = (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == hash_token(body.refresh_token),
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.revoked_at = datetime.now(UTC)
    await append_audit(db, action="auth.logout", actor=str(user.id))
    await db.commit()
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user_allow_password_change),
    db: AsyncSession = Depends(get_db),
):
    """User đổi mật khẩu của chính mình.

    Yêu cầu mật khẩu hiện tại (chống chiếm đoạt phiên). Rate-limit theo IP
    (5/phút) để chống brute-force mật khẩu hiện tại.
    Ghi audit log với target=self để truy vết nếu nghi ngờ.
    Đổi thành công sẽ gỡ cờ bắt buộc đổi mật khẩu (must_change_password).
    """
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Mật khẩu hiện tại không đúng",
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu mới phải khác mật khẩu hiện tại",
        )
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # Đổi mật khẩu → thu hồi mọi phiên refresh đang tồn tại (access token còn
    # sống tối đa access_token_expire_minutes — trade-off chấp nhận được).
    await _revoke_user_refresh_tokens(db, user.id)
    await append_audit(db, action="auth.change_password", actor=str(user.id), target=str(user.id))
    await db.commit()
    return {"ok": True}


@router.patch("/me")
async def update_my_profile(
    body: SelfProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User chỉ tự thay đổi tên hiển thị; email, vai trò và đơn vị do quản trị quản lý."""
    full_name = body.full_name.strip()
    if not full_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Họ và tên không được để trống")
    user.full_name = full_name
    await append_audit(db, action="auth.update_profile", actor=str(user.id), target=str(user.id))
    await db.commit()
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "org_id": str(user.org_id),
        "is_2fa_enabled": user.is_2fa_enabled,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/totp/disable")
async def disable_my_totp(
    body: TotpDisableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tắt 2FA của chính mình sau khi xác thực lại mật khẩu hiện tại."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Mật khẩu hiện tại không đúng")
    user.is_2fa_enabled = False
    user.totp_secret_encrypted = None
    user.backup_codes = None
    user.totp_last_counter = None
    await append_audit(db, action="auth.totp_disabled", actor=str(user.id), target=str(user.id))
    await db.commit()
    return {"ok": True}


async def seed_admin(db: AsyncSession, *, commit: bool = True) -> None:
    existing = (await db.execute(select(User).where(User.email == settings.seed_admin_email))).scalar_one_or_none()
    if existing:
        return
    from app.db.seed_orgs import get_or_create_root

    # Root chuẩn — "UBND tỉnh Hà Tĩnh" (tìm / đổi tên DB cũ / tạo mới nếu thiếu)
    org = await get_or_create_root(db)
    user = User(
        org_id=org.id,
        full_name=settings.seed_admin_full_name,
        email=settings.seed_admin_email,
        role=UserRole.SUPER_ADMIN.value,
        password_hash=hash_password(settings.seed_admin_password),
    )
    db.add(user)
    if commit:
        await db.commit()
