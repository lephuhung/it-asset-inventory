"""Route machines — danh sách máy, chi tiết máy.

RBAC theo cây tổ chức: super admin xem tất cả; org admin / viewer xem org của mình
và toàn bộ cấp dưới (`visible_org_ids`). 1 máy thuộc 1 cá nhân (assigned_user_id,
kèm tên người dùng lấy từ tài khoản hoặc token enroll).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, visible_org_ids
from app.core.audit import append_audit
from app.core.config import settings
from app.db.models import (
    EnrollToken,
    Heartbeat,
    Machine,
    MachineCurrent,
    MachineSpec,
    Organization,
    User,
)
from app.db.session import get_db
from app.schemas import (
    AssignUserRequest,
    AssignUserResponse,
    MachineDecision,
    MachineDetail,
    MachineLifecycleUpdate,
    MachineListItem,
)
from app.services.phone_encryption import mask_phone

router = APIRouter(prefix="/api/machines", tags=["machines"])

# Hai heartbeat liên tiếp cách nhau quá ngưỡng này = máy đã tắt trong khoảng đó
# (chu kỳ heartbeat tối đa 75s; ngưỡng 300s an toàn cho mọi jitter/offline cache).
SESSION_GAP_SECONDS = 300


@router.get("", response_model=list[MachineListItem])
async def list_machines(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    q: str | None = None,
):
    visible = await visible_org_ids(db, user)
    if org_id and str(org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập tổ chức này")

    query = select(Machine).where(Machine.org_id.in_(visible))
    if org_id:
        query = query.where(Machine.org_id == org_id)
    if status_filter:
        query = query.where(Machine.status == status_filter)
    if q:
        like = f"%{q}%"
        query = query.where(Machine.hostname.ilike(like) | Machine.machine_uuid.ilike(like))
    rows = (await db.execute(query.order_by(Machine.enrolled_at.desc()))).scalars().all()
    ids = [m.id for m in rows]
    # user Windows đang đăng nhập — lấy từ machine_current (snapshot mới nhất, có index PK)
    logged: dict[str, str | None] = {}
    if ids:
        latest_rows = (
            await db.execute(
                select(MachineCurrent.machine_id, MachineCurrent.logged_user).where(
                    MachineCurrent.machine_id.in_(ids)
                )
            )
        ).all()
        logged = {str(mid): lu for mid, lu in latest_rows}
    return [
        MachineListItem(
            id=m.id,
            hostname=m.hostname,
            machine_uuid=m.machine_uuid,
            status=m.status,
            lifecycle=m.lifecycle,
            is_vm=m.is_vm,
            last_seen_at=m.last_seen_at,
            enrolled_at=m.enrolled_at,
            org_id=m.org_id,
            assigned_user_id=m.assigned_user_id,
            logged_user=logged.get(str(m.id)),
            public_ip=m.public_ip,
        )
        for m in rows
    ]


@router.get("/stats", response_model=dict)
async def machine_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    visible = await visible_org_ids(db, user)
    rows = (await db.execute(select(Machine).where(Machine.org_id.in_(visible)))).scalars().all()
    counts: dict[str, int] = {}
    for m in rows:
        counts[m.status] = counts.get(m.status, 0) + 1
    return {"by_status": counts, "total": len(rows)}


async def _assigned_info(db: AsyncSession, machine: Machine) -> tuple[str | None, str | None]:
    """Tên + ĐT (mask) của cá nhân sở hữu máy — ưu tiên tài khoản gán, fallback token enroll."""
    name: str | None = None
    phone_masked: str | None = None
    if machine.assigned_user_id:
        u = (
            await db.execute(select(User).where(User.id == machine.assigned_user_id))
        ).scalar_one_or_none()
        if u:
            name = u.full_name
            phone_masked = mask_phone(u.phone_encrypted)
    if machine.id:
        tok = (
            await db.execute(
                select(EnrollToken).where(EnrollToken.used_by == machine.id).limit(1)
            )
        ).scalar_one_or_none()
        if tok and (tok.full_name or tok.email) and name is None:
            # Token ghi thông tin người dùng tại lúc enroll — coi là chủ máy nếu chưa có
            name = tok.full_name
    return name, phone_masked


@router.get("/{machine_id}", response_model=MachineDetail)
async def get_machine(
    machine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    visible = await visible_org_ids(db, user)
    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy không tồn tại")
    if str(machine.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem máy này")

    latest = (
        await db.execute(
            select(MachineSpec)
            .where(MachineSpec.machine_id == machine.id)
            .order_by(MachineSpec.collected_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    assigned_name, assigned_phone = await _assigned_info(db, machine)
    org = (
        await db.execute(select(Organization).where(Organization.id == machine.org_id))
    ).scalar_one_or_none()

    return MachineDetail(
        id=machine.id,
        hostname=machine.hostname,
        machine_uuid=machine.machine_uuid,
        status=machine.status,
        lifecycle=machine.lifecycle,
        is_vm=machine.is_vm,
        last_seen_at=machine.last_seen_at,
        enrolled_at=machine.enrolled_at,
        org_id=machine.org_id,
        assigned_user_id=machine.assigned_user_id,
        public_ip=machine.public_ip,
        fingerprint=machine.fingerprint or {},
        note=machine.note,
        latest_spec=(
            {
                "os_name": latest.os_name,
                "os_version": latest.os_version,
                "os_build": latest.os_build,
                "os_arch": latest.os_arch,
                "os_installed_at": latest.os_installed_at,
                "activation_status": latest.activation_status,
                "cpu": latest.cpu,
                "ram_gb": latest.ram_gb,
                "disks": latest.disks,
                "gpu": latest.gpu,
                "mainboard": latest.mainboard,
                "bios": latest.bios,
                "network": latest.network,
                "logged_user": latest.logged_user,
                "installed_software": latest.installed_software,
                "security": latest.security,
                "public_ip": latest.public_ip,
                "config_hash": latest.config_hash,
                "collected_at": latest.collected_at,
            }
            if latest
            else None
        ),
        phone_masked=assigned_phone,
        assigned_user_name=assigned_name,
        org_name=org.name if org else None,
    )


@router.get("/{machine_id}/timeline", response_model=dict)
async def machine_timeline(
    machine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    days: int = Query(default=30, ge=1, le=90),
):
    """Timeline bật/tắt máy (tính năng #1, Phase 2).

    Gom heartbeat thành các phiên bật máy (session): hai heartbeat cách nhau quá
    SESSION_GAP_SECONDS coi là máy đã tắt. Trả tổng hợp theo ngày + danh sách phiên.
    """
    visible = await visible_org_ids(db, user)
    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy không tồn tại")
    if str(machine.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền xem máy này")

    cutoff = datetime.now(UTC) - timedelta(days=days)
    timestamps = (
        (
            await db.execute(
                select(Heartbeat.ts)
                .where(Heartbeat.machine_id == machine.id, Heartbeat.ts >= cutoff)
                .order_by(Heartbeat.ts)
            )
        )
        .scalars()
        .all()
    )

    sessions: list[dict] = []
    start: datetime | None = None
    prev: datetime | None = None
    for ts in timestamps:
        if start is None:
            start = ts
        elif prev is not None and (ts - prev).total_seconds() > SESSION_GAP_SECONDS:
            sessions.append(
                {
                    "start": start.isoformat(),
                    "end": prev.isoformat(),
                    "duration_sec": int((prev - start).total_seconds()),
                }
            )
            start = ts
        prev = ts
    if start is not None and prev is not None:
        sessions.append(
            {
                "start": start.isoformat(),
                "end": prev.isoformat(),
                "duration_sec": int((prev - start).total_seconds()),
            }
        )

    daily_map: dict[str, dict] = {}
    for s in sessions:
        date_key = s["start"][:10]
        entry = daily_map.setdefault(date_key, {"date": date_key, "boots": 0, "online_sec": 0})
        entry["boots"] += 1
        entry["online_sec"] += s["duration_sec"]

    return {
        "machine_id": str(machine.id),
        "hostname": machine.hostname,
        "days": days,
        "total_online_sec": sum(s["duration_sec"] for s in sessions),
        "sessions_count": len(sessions),
        "daily": sorted(daily_map.values(), key=lambda x: x["date"], reverse=True),
        "sessions": sessions[-200:],
    }


async def _get_machine_in_scope(db: AsyncSession, machine_id: uuid.UUID, user: User) -> Machine:
    visible = await visible_org_ids(db, user)
    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy không tồn tại")
    if str(machine.org_id) not in visible:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Không có quyền thao tác máy này")
    return machine


@router.patch("/{machine_id}/lifecycle", response_model=dict)
async def update_lifecycle(
    machine_id: uuid.UUID,
    body: MachineLifecycleUpdate,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Vòng đời tài sản (#18): Mới cài → Đang dùng → Sửa chữa → Thanh lý."""
    if body.lifecycle not in {"new", "in_use", "in_repair", "decommissioned"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Vòng đời không hợp lệ")
    machine = await _get_machine_in_scope(db, machine_id, admin)
    machine.lifecycle = body.lifecycle
    if body.note:
        machine.note = body.note
    if body.lifecycle == "decommissioned":
        machine.status = "decommissioned"
    await append_audit(db, action="machine.lifecycle", actor=str(admin.id), target=str(machine.id), machine_id=machine.id)
    await db.commit()
    return {"ok": True, "lifecycle": machine.lifecycle, "status": machine.status}


@router.post("/{machine_id}/approve", response_model=dict)
async def approve_machine(
    machine_id: uuid.UUID,
    body: MachineDecision,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Pending approval (#20): duyệt máy mới enroll → chính thức (online/offline theo last_seen)."""
    machine = await _get_machine_in_scope(db, machine_id, admin)
    if machine.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Máy không ở trạng thái chờ duyệt")
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    if machine.last_seen_at and machine.last_seen_at >= _dt.now(_UTC) - _td(seconds=settings.effective_online_ttl_seconds + 60):
        machine.status = "online"
    else:
        machine.status = "offline"
    machine.lifecycle = "in_use"
    if body.note:
        machine.note = body.note
    await append_audit(db, action="machine.approve", actor=str(admin.id), target=str(machine.id), machine_id=machine.id)
    await db.commit()
    return {"ok": True, "status": machine.status}


@router.post("/{machine_id}/reject", response_model=dict)
async def reject_machine(
    machine_id: uuid.UUID,
    body: MachineDecision,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Từ chối máy chờ duyệt → đánh dấu decommissioned (máy lạ không được tính chính thức)."""
    machine = await _get_machine_in_scope(db, machine_id, admin)
    machine.status = "decommissioned"
    machine.lifecycle = "decommissioned"
    machine.note = f"Từ chối duyệt: {body.note or 'không rõ lý do'}" + (f"\n{machine.note or ''}" if machine.note else "")
    await append_audit(db, action="machine.reject", actor=str(admin.id), target=str(machine.id), machine_id=machine.id)
    await db.commit()
    return {"ok": True, "status": machine.status}




@router.post("/{machine_id}/assign-user", response_model=AssignUserResponse)
async def assign_user(
    machine_id: uuid.UUID,
    body: AssignUserRequest,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Gán người sử dụng cho máy.

    Flow chuẩn sau khi upload ZIP cách ly: admin nhập user info ở đây để link
    `machine.assigned_user_id` với user có sẵn hoặc tạo mới (role=viewer).

    - `mode="existing"`: chỉ cần `user_id`. User phải thuộc cùng org với máy.
    - `mode="new"`: cần `full_name`, `email` (unique). `phone` mã hóa AES-256-GCM.

    Audit `machine.assign_user` để truy vết. Cho phép gán lại (đổi người dùng).
    """
    from app.core.security import hash_password  # noqa: PLC0415 — import tại chỗ cho gọn
    from app.services.phone_encryption import encrypt_phone, mask_phone  # noqa: PLC0415

    machine = await _get_machine_in_scope(db, machine_id, admin)

    was_created = False
    if body.mode == "existing":
        if not body.user_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="mode=existing cần user_id")
        user = (await db.execute(select(User).where(User.id == body.user_id))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User không tồn tại")
        if user.org_id != machine.org_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="User phải thuộc cùng tổ chức với máy",
            )
    else:
        # mode="new" — tạo user mới trong cùng org với máy
        if not body.full_name or not body.email:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="mode=new cần full_name và email",
            )
        dup = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Email {body.email} đã thuộc về user khác",
            )
        # Tạo user với role=viewer, KHÔNG có password (admin phải set sau hoặc user reset)
        # → password_hash = None → user phải dùng SSO/reset flow để đăng nhập
        user = User(
            org_id=machine.org_id,
            full_name=body.full_name,
            email=body.email,
            phone_encrypted=encrypt_phone(body.phone) if body.phone else None,
            role="viewer",
            password_hash=None,  # buộc reset password trước khi đăng nhập
            is_active=True,
        )
        db.add(user)
        await db.flush()  # lấy id
        was_created = True

    old_user_id = machine.assigned_user_id
    machine.assigned_user_id = user.id

    await append_audit(
        db,
        action="machine.assign_user",
        actor=str(admin.id),
        target=f"{machine.id}|new={user.id}|email={user.email}|created={was_created}"[:255],
        ip=request.client.host if request.client else None,
        machine_id=machine.id,
    )
    await db.commit()
    await db.refresh(user)

    return AssignUserResponse(
        machine_id=machine.id,
        assigned_user_id=user.id,
        assigned_user_name=user.full_name,
        assigned_user_email=user.email,
        phone_masked=mask_phone(user.phone_encrypted),
        was_created=was_created,
    )


@router.delete("/{machine_id}/assign-user", response_model=dict)
async def unassign_user(
    machine_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Gỡ người dùng khỏi máy (vd: máy được chuyển cho người khác, decommissioned)."""
    machine = await _get_machine_in_scope(db, machine_id, admin)
    if machine.assigned_user_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy chưa gán người dùng")
    old_user_id = machine.assigned_user_id
    machine.assigned_user_id = None
    await append_audit(
        db,
        action="machine.unassign_user",
        actor=str(admin.id),
        target=f"{machine.id}|old={old_user_id}",
        ip=request.client.host if request.client else None,
        machine_id=machine.id,
    )
    await db.commit()
    return {"machine_id": str(machine.id), "unassigned": True}


@router.post("/{machine_id}/rescan", response_model=dict)
async def request_rescan(
    machine_id: uuid.UUID,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """On-demand rescan (#23): đặt cờ Redis → agent nhận `rescan_requested` ở heartbeat kế tiếp."""
    machine = await _get_machine_in_scope(db, machine_id, admin)
    from app.core.config import settings as _s

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(_s.redis_url, decode_responses=True)
        await r.set(f"machine:rescan:{machine.id}", "1", ex=600)
        await r.aclose()
    except Exception:  # noqa: BLE001 — Redis down: fallback ghi flag trong DB để heartbeat đọc
        machine._rescan_pending = True
    await append_audit(db, action="machine.rescan_requested", actor=str(admin.id), target=str(machine.id), machine_id=machine.id)
    await db.commit()
    return {"ok": True, "message": "Đã yêu cầu agent thu thập lại cấu hình (khi máy online)"}