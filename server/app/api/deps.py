"""FastAPI dependencies: auth JWT, RBAC, mTLS header check."""
from __future__ import annotations

import uuid

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.models import Organization, User, UserRole
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

# Vai trò "admin" (có quyền sinh token / quản lý), kèm alias legacy.
ADMIN_ROLES = {
    UserRole.SUPER_ADMIN.value,
    UserRole.ORG_ADMIN.value,
    UserRole.ADMIN_GLOBAL.value,  # legacy
    UserRole.ADMIN_ORG.value,     # legacy
}
SUPER_ADMIN_ROLES = {UserRole.SUPER_ADMIN.value, UserRole.ADMIN_GLOBAL.value}


async def _resolve_user_from_token(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Thiếu token")
    try:
        payload = decode_token(credentials.credentials, "access")
        user_id = uuid.UUID(payload["sub"])
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ hoặc hết hạn")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User không tồn tại hoặc bị khóa")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency mặc định — chặn user chưa đổi mật khẩu mặc định (403).

    User có `must_change_password=True` (tài khoản seed / vừa được reset) chỉ được
    phép gọi các endpoint dùng `get_current_user_allow_password_change` — buộc đổi
    mật khẩu trước khi dùng bất kỳ chức năng nào khác.
    """
    user = await _resolve_user_from_token(credentials, db)
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="PASSWORD_CHANGE_REQUIRED")
    return user


async def get_current_user_allow_password_change(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Cho phép user đang bị bắt đổi mật khẩu — chỉ dùng cho auth.me / change-password / logout."""
    return await _resolve_user_from_token(credentials, db)


def require_role(*roles: UserRole):
    """RBAC dependency: user phải có 1 trong các vai trò đã chỉ định."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in {r.value for r in roles}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền")
        return user

    return checker


def require_admin():
    """Admin (super_admin / org_admin, kèm alias legacy)."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in ADMIN_ROLES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền")
        return user

    return checker


def require_super_admin():
    """Chỉ Super Admin (kèm alias legacy admin_global)."""

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in SUPER_ADMIN_ROLES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cần quyền Super Admin")
        return user

    return checker


def is_super_admin(user: User) -> bool:
    return user.role in SUPER_ADMIN_ROLES


async def visible_org_ids(db: AsyncSession, user: User) -> set[str]:
    """Tập org_id mà user được phép nhìn thấy.

    - Super Admin (hoặc legacy admin_global): toàn bộ tổ chức.
    - Org Admin / Viewer: org của mình **và toàn bộ cấp dưới** trong cây tổ chức
      (UBND xã / Sở ban ngành → phòng, đơn vị trực thuộc…).
    """
    rows = (await db.execute(select(Organization.id, Organization.parent_id))).all()
    if is_super_admin(user):
        return {str(oid) for oid, _ in rows}

    by_parent: dict[str, list[str]] = {}
    for oid, parent_id in rows:
        by_parent.setdefault(str(parent_id) if parent_id else "", []).append(str(oid))

    visible: set[str] = set()

    def walk(oid: str) -> None:
        if oid in visible:
            return
        visible.add(oid)
        for child in by_parent.get(oid, []):
            walk(child)

    walk(str(user.org_id))
    return visible


async def get_client_machine_id(
    request: Request,
    x_ssl_client_verify: str | None = Header(default=None),
    x_ssl_client_cn: str | None = Header(default=None),
) -> str:
    """Đọc identity agent từ header nginx forward (mTLS).

    Nếu `require_agent_mtls_header=True` (prod), từ chối mọi request không qua nginx mTLS.
    Dev (không nginx): agent tự gửi `X-Machine-Id` — header chỉ được chấp nhận khi
    `require_agent_mtls_header=False`, prod vẫn bắt buộc X-SSL-Client-CN từ nginx.
    """
    if settings.require_agent_mtls_header and x_ssl_client_verify != "SUCCESS":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Thiếu chứng thực mTLS hợp lệ")
    cn = x_ssl_client_cn
    if cn is None and not settings.require_agent_mtls_header:
        # Dev không có nginx forward header → agent gửi machine_id trực tiếp
        cn = request.headers.get("X-Machine-Id")
    if cn is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Thiếu client cert CN")
    # CN dạng machine-<uuid> — lấy phần sau dấu gạch
    if cn.startswith("machine-"):
        return cn[len("machine-"):]
    return cn
