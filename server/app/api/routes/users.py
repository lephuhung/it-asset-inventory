"""Route quản trị tài khoản — Super Admin.

- GET  /api/users            — danh sách user (kèm org name)
- POST /api/users            — tạo tài khoản mới (chọn role + org + password)
- GET  /api/users/{id}       — chi tiết user
- PATCH /api/users/{id}      — sửa (vai trò, org, tên, khóa/kích hoạt, phone)
- POST /api/users/{id}/reset-password — đặt lại mật khẩu
- POST /api/users/{id}/reset-2fa      — vô hiệu 2FA (user mất app xác thực)

Chỉ `super_admin` (hoặc legacy `admin_global`) được truy cập.
Không cho phép tự hạ quyền/khoá tài khoản cuối cùng có quyền super_admin.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_role
from app.core.audit import append_audit
from app.core.security import hash_password
from app.db.models import Organization, User, UserRole
from app.db.session import get_db
from app.schemas import (
    Page,
    UserCreateRequest,
    UserOut,
    UserResetPasswordRequest,
    UserUpdateRequest,
)
from app.services.phone_encryption import encrypt_phone

router = APIRouter(prefix="/api/users", tags=["users"])

SUPER_ROLES = {UserRole.SUPER_ADMIN.value, UserRole.ADMIN_GLOBAL.value}


def _is_super(user: User) -> bool:
    return user.role in SUPER_ROLES


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        org_id=u.org_id,
        is_2fa_enabled=u.is_2fa_enabled,
        is_active=u.is_active,
        created_at=u.created_at,
        org_name=u.org.name if u.org else None,
    )


@router.get("", response_model=Page[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN_GLOBAL)),
    org_id: uuid.UUID | None = None,
    role: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    from sqlalchemy import func as sa_func

    query = select(User).options(selectinload(User.org))
    if org_id:
        query = query.where(User.org_id == org_id)
    if role:
        query = query.where(User.role == role)
    if q:
        like = f"%{q}%"
        query = query.where(User.full_name.ilike(like) | User.email.ilike(like))

    total = (await db.execute(select(sa_func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        await db.execute(query.order_by(User.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return Page[UserOut](
        items=[_to_out(u) for u in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN_GLOBAL)),
):
    # Kiểm tra email trùng
    dup = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email đã tồn tại")
    # Kiểm tra org tồn tại
    org = (await db.execute(select(Organization).where(Organization.id == body.org_id))).scalar_one_or_none()
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tổ chức không tồn tại")

    user = User(
        org_id=body.org_id,
        full_name=body.full_name,
        email=body.email.lower(),
        role=body.role,
        password_hash=hash_password(body.password),
        phone_encrypted=encrypt_phone(body.phone) if body.phone else None,
    )
    db.add(user)
    await append_audit(
        db, action="user.create", actor=str(admin.id), target=str(user.id)
    )
    await db.flush()
    user.org = org
    await db.commit()
    await db.refresh(user)
    return _to_out(user)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN_GLOBAL)),
):
    u = (
        await db.execute(
            select(User).options(selectinload(User.org)).where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Người dùng không tồn tại")
    return _to_out(u)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN_GLOBAL)),
):
    u = (
        await db.execute(select(User).options(selectinload(User.org)).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Người dùng không tồn tại")

    # Không cho phép tự hạ quyền / khoá tài khoản super cuối cùng
    if u.id == admin.id:
        if body.role is not None and body.role not in SUPER_ROLES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Không thể tự hạ quyền tài khoản đang đăng nhập")
        if body.is_active is False:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Không thể tự khoá tài khoản đang đăng nhập")

    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None:
        u.role = body.role
    if body.org_id is not None:
        org = (await db.execute(select(Organization).where(Organization.id == body.org_id))).scalar_one_or_none()
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tổ chức không tồn tại")
        u.org_id = body.org_id
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.phone is not None:
        u.phone_encrypted = encrypt_phone(body.phone) if body.phone else None

    await append_audit(db, action="user.update", actor=str(admin.id), target=str(u.id))
    await db.commit()
    await db.refresh(u)
    return _to_out(u)


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: uuid.UUID,
    body: UserResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN_GLOBAL)),
):
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Người dùng không tồn tại")
    u.password_hash = hash_password(body.new_password)
    await append_audit(db, action="user.reset_password", actor=str(admin.id), target=str(u.id))
    await db.commit()
    return {"ok": True}


@router.post("/{user_id}/reset-2fa")
async def reset_2fa(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.ADMIN_GLOBAL)),
):
    """Vô hiệu 2FA khi user mất app xác thực — yêu cầu user bật lại khi đăng nhập."""
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Người dùng không tồn tại")
    u.is_2fa_enabled = False
    u.totp_secret_encrypted = None
    u.backup_codes = None
    await append_audit(db, action="user.reset_2fa", actor=str(admin.id), target=str(u.id))
    await db.commit()
    return {"ok": True}
