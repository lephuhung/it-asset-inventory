"""Route hồ sơ cấp độ hệ thống thông tin (cấp 1–3).

- `GET /api/system-profiles`                 — danh sách (scope theo org của user).
- `POST /api/system-profiles`                — tạo hồ sơ (Admin/Super Admin).
- `GET /api/system-profiles/{id}`            — chi tiết (kèm devices + machines).
- `PATCH /api/system-profiles/{id}`          — sửa thông tin / sơ đồ mermaid.
- `DELETE /api/system-profiles/{id}`         — xóa (Super Admin, hoặc Admin khi chưa trình).
- `POST /api/system-profiles/{id}/submit`    — trình duyệt (Admin → pending_review).
- `POST /api/system-profiles/{id}/review`    — Super Admin approve/reject.
- `POST/PUT/DELETE .../devices[...]`         — CRUD thiết bị khai báo.
- `POST/DELETE .../machines`                 — gắn/gỡ Machine đã enroll.

Luồng phê duyệt: `drafted` → `pending_review` → `approved`/`rejected`.
Super Admin tạo/sửa được approve trực tiếp (kèm số quyết định).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, is_super_admin, require_admin, require_super_admin, visible_org_ids
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import (
    DeviceType,
    LevelRequirement,
    Machine,
    Organization,
    ServiceAudience,
    ProfileRequirementStatus,
    SystemDevice,
    SystemProfile,
    SystemProfileApplication,
    SystemProfileIpRange,
    SystemProfileParty,
    SystemProfileMachine,
    SystemProfileRequirement,
    SystemProfileStatus,
    User,
)
from app.db.session import get_db
from app.schemas import (
    LevelRequirementIn,
    LevelRequirementOut,
    LevelRequirementUpdate,
    SystemProfileApplicationIn,
    SystemProfileApplicationOut,
    SystemProfileIpRangeIn,
    SystemProfileIpRangeOut,
    SystemProfilePartyIn,
    SystemProfilePartyOut,
    Page,
    ProfileRequirementOut,
    ProfileRequirementRequest,
    ProfileRequirementReview,
    SystemProfileCreate,
    SystemProfileDeviceIn,
    SystemProfileDeviceOut,
    SystemProfileDetailOut,
    SystemProfileMachineOut,
    SystemProfileOut,
    SystemProfileReview,
    SystemProfileUpdate,
)

router = APIRouter(prefix="/api/system-profiles", tags=["system-profiles"])

async def _valid_device_type(db: AsyncSession, device_type: str) -> bool:
    """Validate `device_type` tra catalog `device_types` (quản trị động)."""
    return (
        await db.execute(select(func.count()).select_from(DeviceType).where(DeviceType.code == device_type))
    ).scalar_one() > 0


async def _get_profile_scoped(db: AsyncSession, profile_id: uuid.UUID, user: User) -> SystemProfile:
    """Lấy hồ sơ theo id, chặn nếu nằm ngoài phạm vi org của user."""
    profile = (
        await db.execute(
            select(SystemProfile)
            .options(
                selectinload(SystemProfile.devices),
                selectinload(SystemProfile.machines).selectinload(SystemProfileMachine.machine),
                selectinload(SystemProfile.requirements).selectinload(SystemProfileRequirement.requirement),
                selectinload(SystemProfile.parties),
                selectinload(SystemProfile.applications).selectinload(SystemProfileApplication.machine),
                selectinload(SystemProfile.ip_ranges),
            )
            .where(SystemProfile.id == profile_id)
            # populate_existing: nạp lại collections (session dùng
            # expire_on_commit=False nên object cũ giữ collection stale)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy hồ sơ")
    if not is_super_admin(user) and str(profile.org_id) not in await visible_org_ids(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Hồ sơ ngoài phạm vi của bạn")
    return profile


def _to_out(profile: SystemProfile, org_name: str | None = None) -> SystemProfileOut:
    return SystemProfileOut(
        id=profile.id,
        org_id=profile.org_id,
        org_name=org_name,
        code=profile.code,
        name=profile.name,
        level=profile.level,
        description=profile.description,
        status=profile.status,
        decision_number=profile.decision_number,
        decision_date=profile.decision_date,
        decision_agency=profile.decision_agency,
        review_note=profile.review_note,
        reviewed_at=profile.reviewed_at,
        diagram_mermaid=profile.diagram_mermaid,
        created_by=profile.created_by,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        device_count=len(profile.devices) if profile.devices is not None else 0,
        machine_count=len(profile.machines) if profile.machines is not None else 0,
    )


def _req_out(r: SystemProfileRequirement) -> ProfileRequirementOut:
    req = r.requirement
    return ProfileRequirementOut(
        id=r.id,
        requirement_id=r.requirement_id,
        code=req.code if req else "",
        title=req.title if req else "",
        description=req.description if req else None,
        sort_order=req.sort_order if req else 0,
        status=r.status,
        evidence=r.evidence,
        review_note=r.review_note,
        requested_at=r.requested_at,
        reviewed_at=r.reviewed_at,
    )


def _to_detail(profile: SystemProfile, org_name: str | None) -> SystemProfileDetailOut:
    base = _to_out(profile, org_name).model_dump()
    reqs = sorted(profile.requirements or [], key=lambda r: (r.requirement.sort_order if r.requirement else 0, r.requirement.code if r.requirement else ""))
    verified = sum(1 for r in reqs if r.status == ProfileRequirementStatus.VERIFIED.value)
    return SystemProfileDetailOut(
        **base,
        devices=[
            SystemProfileDeviceOut(
                id=d.id,
                profile_id=d.profile_id,
                name=d.name,
                device_code=d.device_code,
                tag=d.tag,
                device_type=d.device_type,
                ip=d.ip,
                model=d.model,
                machine_id=d.machine_id,
                sort_order=d.sort_order,
                location=d.location,
                purpose=d.purpose,
            )
            for d in profile.devices
        ],
        machines=[
            SystemProfileMachineOut(
                machine_id=m.machine_id,
                hostname=m.machine.hostname,
                machine_uuid=m.machine.machine_uuid,
                status=m.machine.status,
                note=m.note,
                added_at=m.added_at,
            )
            for m in profile.machines
        ],
        requirements=[_req_out(r) for r in reqs],
        physical_diagram_mermaid=profile.physical_diagram_mermaid,
        physical_location=profile.physical_location,
        user_accounts=profile.user_accounts,
        data_volume=profile.data_volume,
        service_audience=profile.service_audience,
        parties=[
            SystemProfilePartyOut(
                id=p2.id, profile_id=p2.profile_id, role=p2.role, name=p2.name,
                mandate_document=p2.mandate_document, legal_representative=p2.legal_representative,
                representative_title=p2.representative_title, address=p2.address,
                phone=p2.phone, email=p2.email,
            )
            for p2 in profile.parties
        ],
        applications=[
            SystemProfileApplicationOut(
                id=a.id, profile_id=a.profile_id, name=a.name, machine_id=a.machine_id,
                server_name=a.server_name, os_name=a.os_name, role=a.role, url=a.url, note=a.note,
            )
            for a in profile.applications
        ],
        ip_ranges=[
            SystemProfileIpRangeOut(
                id=ip.id, profile_id=ip.profile_id, zone=ip.zone, zone_description=ip.zone_description,
                cidr=ip.cidr, ip_kind=ip.ip_kind, gateway=ip.gateway, note=ip.note,
            )
            for ip in profile.ip_ranges
        ],
        requirements_total=len(reqs),
        requirements_verified=verified,
        level_compliant=len(reqs) > 0 and verified == len(reqs),
    )


async def _sync_profile_requirements(db: AsyncSession, profile: SystemProfile) -> None:
    """Đồng bộ danh sách yêu cầu của hồ sơ theo catalog của cấp độ hiện tại.

    Gọi khi tạo hồ sơ hoặc đổi cấp độ: sinh đủ hàng cho các yêu cầu `is_active`
    của cấp độ; gỡ hàng thuộc cấp độ khác; giữ nguyên trạng thái thẩm định của
    các hàng còn hiệu lực.
    """
    rows = (
        await db.execute(select(LevelRequirement).where(LevelRequirement.level == profile.level, LevelRequirement.is_active.is_(True)))
    ).scalars().all()
    valid_ids = {req.id for req in rows}
    for r in list(profile.requirements or []):
        if r.requirement_id not in valid_ids:
            await db.delete(r)
    existing = {r.requirement_id for r in (profile.requirements or [])}
    for req in rows:
        if req.id not in existing:
            db.add(SystemProfileRequirement(profile_id=profile.id, requirement_id=req.id))


@router.get("", response_model=Page[SystemProfileOut])
async def list_profiles(
    org_id: uuid.UUID | None = None,
    level: int | None = Query(default=None, ge=1, le=3),
    profile_status: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conds = []
    if is_super_admin(user):
        visible = None
    else:
        visible = await visible_org_ids(db, user)
        if org_id is not None:
            if str(org_id) not in visible:
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Đơn vị ngoài phạm vi của bạn")
            conds.append(SystemProfile.org_id == org_id)
        else:
            conds.append(SystemProfile.org_id.in_(visible))
    if org_id is not None and visible is None:
        conds.append(SystemProfile.org_id == org_id)
    if level is not None:
        conds.append(SystemProfile.level == level)
    if profile_status is not None:
        conds.append(SystemProfile.status == profile_status)
    if q:
        conds.append(SystemProfile.name.ilike(f"%{q}%"))

    base = select(SystemProfile).options(
        selectinload(SystemProfile.devices),
        selectinload(SystemProfile.machines).selectinload(SystemProfileMachine.machine),
        selectinload(SystemProfile.requirements).selectinload(SystemProfileRequirement.requirement),
    )
    count_q = select(func.count()).select_from(SystemProfile)
    if conds:
        base = base.where(*conds)
        count_q = count_q.where(*conds)

    rows = (
        (await db.execute(base.order_by(SystemProfile.updated_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    total = (await db.execute(count_q)).scalar_one()

    org_ids = {p.org_id for p in rows}
    org_names: dict[uuid.UUID, str] = {}
    if org_ids:
        for oid, name in (
            await db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(org_ids)))
        ).all():
            org_names[oid] = name
    return Page(
        items=[_to_out(p, org_names.get(p.org_id)) for p in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: SystemProfileCreate,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    if not is_super_admin(admin):
        if str(admin.org_id) != str(body.org_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ tạo hồ sơ cho đơn vị của bạn")
    dup = (
        await db.execute(
            select(SystemProfile).where(SystemProfile.org_id == body.org_id, SystemProfile.code == body.code)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Mã hồ sơ '{body.code}' đã tồn tại tại đơn vị này")

    approved_directly = is_super_admin(admin) and bool(body.decision_number)
    profile = SystemProfile(
        org_id=body.org_id,
        code=body.code.strip(),
        name=body.name.strip(),
        level=body.level,
        description=body.description,
        diagram_mermaid=body.diagram_mermaid,
        status=SystemProfileStatus.APPROVED.value if approved_directly else SystemProfileStatus.DRAFTED.value,
        decision_number=body.decision_number if approved_directly else None,
        decision_date=body.decision_date if approved_directly else None,
        decision_agency=body.decision_agency if approved_directly else None,
        reviewed_by=admin.id if approved_directly else None,
        reviewed_at=datetime.now(UTC) if approved_directly else None,
        created_by=admin.id,
    )
    db.add(profile)
    await append_audit(
        db,
        action="system_profile.create",
        actor=str(admin.id),
        target=f"{body.org_id}:{body.code}",
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    # Sinh danh sách yêu cầu an toàn theo cấp độ của hồ sơ
    await _sync_profile_requirements(db, profile)
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


@router.get("/{profile_id}", response_model=SystemProfileDetailOut)
async def get_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    profile = await _get_profile_scoped(db, profile_id, user)
    org_name = (
        await db.execute(select(Organization.name).where(Organization.id == profile.org_id))
    ).scalar_one_or_none()
    return _to_detail(profile, org_name)


@router.patch("/{profile_id}", response_model=SystemProfileDetailOut)
async def update_profile(
    profile_id: uuid.UUID,
    body: SystemProfileUpdate,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    if profile.status == SystemProfileStatus.APPROVED.value and not is_super_admin(admin):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Hồ sơ đã được phê duyệt — không sửa được, liên hệ quản trị viên hệ thống",
        )
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "service_audience" in changes and changes["service_audience"] not in {a.value for a in ServiceAudience}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="service_audience không hợp lệ")
    level_changed = "level" in changes and changes["level"] != profile.level
    for field, value in changes.items():
        setattr(profile, field, value)
    # Sửa lại hồ sơ sau khi bị từ chối → về drafted để trình lại
    if profile.status == SystemProfileStatus.REJECTED.value:
        profile.status = SystemProfileStatus.DRAFTED.value
        profile.review_note = None
    await append_audit(
        db,
        action="system_profile.update",
        actor=str(admin.id),
        target=str(profile.id),
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    if level_changed:
        # Đổi cấp độ → đồng bộ danh sách yêu cầu theo catalog cấp độ mới
        # (giữ nguyên trạng thái các yêu cầu trùng code giữa 2 cấp độ — so theo id)
        await _sync_profile_requirements(db, profile)
        await db.commit()
        await db.refresh(profile)
    return _to_detail(profile, None)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    if not is_super_admin(admin):
        if profile.status not in (SystemProfileStatus.DRAFTED.value, SystemProfileStatus.REJECTED.value):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chỉ xóa được hồ sơ chưa trình / bị từ chối")
    await append_audit(
        db,
        action="system_profile.delete",
        actor=str(admin.id),
        target=f"{profile.org_id}:{profile.code}",
        ip=get_client_ip(request),
    )
    await db.delete(profile)
    await db.commit()


@router.post("/{profile_id}/submit", response_model=SystemProfileDetailOut)
async def submit_profile(
    profile_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    if profile.status not in (SystemProfileStatus.DRAFTED.value, SystemProfileStatus.REJECTED.value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Hồ sơ đã được trình hoặc đã duyệt")
    profile.status = SystemProfileStatus.PENDING_REVIEW.value
    await append_audit(
        db,
        action="system_profile.submit",
        actor=str(admin.id),
        target=str(profile.id),
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


@router.post("/{profile_id}/review", response_model=SystemProfileDetailOut)
async def review_profile(
    profile_id: uuid.UUID,
    body: SystemProfileReview,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    if profile.status != SystemProfileStatus.PENDING_REVIEW.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chỉ duyệt được hồ sơ đang chờ duyệt")
    if body.action == "approve":
        if not body.decision_number:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Phải nhập số quyết định phê duyệt")
        profile.status = SystemProfileStatus.APPROVED.value
        profile.decision_number = body.decision_number.strip()
        profile.decision_date = body.decision_date or datetime.now(UTC)
        profile.decision_agency = body.decision_agency
        profile.review_note = body.review_note
    else:
        profile.status = SystemProfileStatus.REJECTED.value
        profile.review_note = body.review_note
    profile.reviewed_by = admin.id
    profile.reviewed_at = datetime.now(UTC)
    await append_audit(
        db,
        action=f"system_profile.{body.action}",
        actor=str(admin.id),
        target=str(profile.id),
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


# ── Thiết bị khai báo ────────────────────────────────────────


async def _validate_machine(db: AsyncSession, machine_id: uuid.UUID | None, profile: SystemProfile) -> None:
    if machine_id is None:
        return
    machine = (
        await db.execute(select(Machine).where(Machine.id == machine_id))
    ).scalar_one_or_none()
    if machine is None or str(machine.org_id) != str(profile.org_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Máy không thuộc đơn vị của hồ sơ")


@router.post("/{profile_id}/devices", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def add_device(
    profile_id: uuid.UUID,
    body: SystemProfileDeviceIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    if not await _valid_device_type(db, body.device_type):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Loại thiết bị không hợp lệ: {body.device_type}")
    await _validate_machine(db, body.machine_id, profile)
    db.add(SystemDevice(profile_id=profile.id, **body.model_dump()))
    await append_audit(
        db,
        action="system_profile.device.add",
        actor=str(admin.id),
        target=f"{profile.id}:{body.name}",
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


@router.put("/{profile_id}/devices/{device_id}", response_model=SystemProfileDetailOut)
async def update_device(
    profile_id: uuid.UUID,
    device_id: uuid.UUID,
    body: SystemProfileDeviceIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    device = (
        await db.execute(
            select(SystemDevice).where(SystemDevice.id == device_id, SystemDevice.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy thiết bị")
    if not await _valid_device_type(db, body.device_type):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Loại thiết bị không hợp lệ: {body.device_type}")
    await _validate_machine(db, body.machine_id, profile)
    for field, value in body.model_dump().items():
        setattr(device, field, value)
    await append_audit(
        db,
        action="system_profile.device.update",
        actor=str(admin.id),
        target=str(device.id),
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


@router.delete("/{profile_id}/devices/{device_id}", response_model=SystemProfileDetailOut)
async def delete_device(
    profile_id: uuid.UUID,
    device_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    device = (
        await db.execute(
            select(SystemDevice).where(SystemDevice.id == device_id, SystemDevice.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy thiết bị")
    await db.delete(device)
    await append_audit(
        db,
        action="system_profile.device.delete",
        actor=str(admin.id),
        target=str(device_id),
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


# ── Gắn máy tính (Machine đã enroll) ────────────────────────


@router.post("/{profile_id}/machines", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def attach_machine(
    profile_id: uuid.UUID,
    machine_id: uuid.UUID,
    note: str | None = None,
    request: Request = None,  # noqa: RUF012 — gán bởi FastAPI dependency injection
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    await _validate_machine(db, machine_id, profile)
    exists = (
        await db.execute(
            select(SystemProfileMachine).where(
                SystemProfileMachine.profile_id == profile.id,
                SystemProfileMachine.machine_id == machine_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Máy đã nằm trong hồ sơ")
    db.add(SystemProfileMachine(profile_id=profile.id, machine_id=machine_id, note=note))
    await append_audit(
        db,
        action="system_profile.machine.attach",
        actor=str(admin.id),
        target=f"{profile.id}:{machine_id}",
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


@router.delete("/{profile_id}/machines/{machine_id}", response_model=SystemProfileDetailOut)
async def detach_machine(
    profile_id: uuid.UUID,
    machine_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    link = (
        await db.execute(
            select(SystemProfileMachine).where(
                SystemProfileMachine.profile_id == profile.id,
                SystemProfileMachine.machine_id == machine_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Máy không nằm trong hồ sơ")
    await db.delete(link)
    await append_audit(
        db,
        action="system_profile.machine.detach",
        actor=str(admin.id),
        target=f"{profile.id}:{machine_id}",
        ip=get_client_ip(request),
    )
    await db.commit()
    await db.refresh(profile)
    return _to_detail(profile, None)


# ── Yêu cầu an toàn theo cấp độ: catalog + thẩm định ────────

catalog_router = APIRouter(prefix="/api/level-requirements", tags=["level-requirements"])


@catalog_router.get("", response_model=list[LevelRequirementOut])
async def list_level_requirements(
    level: int | None = Query(default=None, ge=1, le=3),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conds = [LevelRequirement.level == level] if level else []
    q = select(LevelRequirement).order_by(LevelRequirement.level, LevelRequirement.sort_order)
    if conds:
        q = q.where(*conds)
    rows = (await db.execute(q)).scalars().all()
    return [
        LevelRequirementOut(
            id=r.id, level=r.level, code=r.code, title=r.title,
            description=r.description, sort_order=r.sort_order, is_active=r.is_active,
        )
        for r in rows
    ]


@catalog_router.post("", response_model=LevelRequirementOut, status_code=status.HTTP_201_CREATED)
async def create_level_requirement(
    body: LevelRequirementIn,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(select(LevelRequirement).where(LevelRequirement.code == body.code))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Mã yêu cầu '{body.code}' đã tồn tại")
    req = LevelRequirement(
        level=body.level, code=body.code.strip(), title=body.title.strip(),
        description=body.description, sort_order=body.sort_order, is_active=body.is_active,
    )
    db.add(req)
    await append_audit(db, action="level_requirement.create", actor=str(admin.id), target=f"L{body.level}:{body.code}", ip=get_client_ip(request))
    await db.commit()
    await db.refresh(req)
    return LevelRequirementOut(
        id=req.id, level=req.level, code=req.code, title=req.title,
        description=req.description, sort_order=req.sort_order, is_active=req.is_active,
    )


@catalog_router.patch("/{requirement_id}", response_model=LevelRequirementOut)
async def update_level_requirement(
    requirement_id: uuid.UUID,
    body: LevelRequirementUpdate,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    req = (await db.execute(select(LevelRequirement).where(LevelRequirement.id == requirement_id))).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(req, field, value)
    await append_audit(db, action="level_requirement.update", actor=str(admin.id), target=str(requirement_id), ip=get_client_ip(request))
    await db.commit()
    await db.refresh(req)
    return LevelRequirementOut(
        id=req.id, level=req.level, code=req.code, title=req.title,
        description=req.description, sort_order=req.sort_order, is_active=req.is_active,
    )


@catalog_router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_level_requirement(
    requirement_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    req = (await db.execute(select(LevelRequirement).where(LevelRequirement.id == requirement_id))).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu")
    referenced = (
        await db.execute(select(func.count()).select_from(SystemProfileRequirement).where(SystemProfileRequirement.requirement_id == requirement_id))
    ).scalar_one()
    if referenced:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Yêu cầu đang được dùng trong hồ sơ — hãy tắt bật (is_active=false) thay vì xóa")
    await append_audit(db, action="level_requirement.delete", actor=str(admin.id), target=str(requirement_id), ip=get_client_ip(request))
    await db.delete(req)
    await db.commit()


@router.post("/{profile_id}/requirements/{row_id}/request", response_model=SystemProfileDetailOut)
async def request_requirement_review(
    profile_id: uuid.UUID,
    row_id: uuid.UUID,
    body: ProfileRequirementRequest,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Đơn vị khai báo hoàn thành yêu cầu → chờ Super Admin thẩm định."""
    profile = await _get_profile_scoped(db, profile_id, admin)
    row = (
        await db.execute(
            select(SystemProfileRequirement).where(
                SystemProfileRequirement.id == row_id, SystemProfileRequirement.profile_id == profile.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu trong hồ sơ")
    if row.status in (ProfileRequirementStatus.REQUESTED.value, ProfileRequirementStatus.VERIFIED.value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Yêu cầu đang chờ thẩm định hoặc đã được thẩm định đạt")
    row.status = ProfileRequirementStatus.REQUESTED.value
    row.evidence = body.evidence.strip()
    row.requested_by = admin.id
    row.requested_at = datetime.now(UTC)
    row.review_note = None
    await append_audit(db, action="system_profile.requirement.request", actor=str(admin.id), target=f"{profile.id}:{row_id}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.post("/{profile_id}/requirements/{row_id}/review", response_model=SystemProfileDetailOut)
async def review_requirement(
    profile_id: uuid.UUID,
    row_id: uuid.UUID,
    body: ProfileRequirementReview,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin thẩm định yêu cầu: verify (đạt) / reject (không đạt)."""
    profile = await _get_profile_scoped(db, profile_id, admin)
    row = (
        await db.execute(
            select(SystemProfileRequirement).where(
                SystemProfileRequirement.id == row_id, SystemProfileRequirement.profile_id == profile.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu trong hồ sơ")
    if row.status != ProfileRequirementStatus.REQUESTED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chỉ thẩm định được yêu cầu đang chờ thẩm định")
    if body.action == "verify":
        row.status = ProfileRequirementStatus.VERIFIED.value
    else:
        row.status = ProfileRequirementStatus.REJECTED.value
    row.reviewed_by = admin.id
    row.reviewed_at = datetime.now(UTC)
    row.review_note = body.review_note
    await append_audit(db, action=f"system_profile.requirement.{body.action}", actor=str(admin.id), target=f"{profile.id}:{row_id}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


# ── Chủ quản / Đơn vị vận hành ──────────────────────────────


@router.post("/{profile_id}/parties", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def add_party(
    profile_id: uuid.UUID,
    body: SystemProfilePartyIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    dup = (
        await db.execute(
            select(SystemProfileParty).where(
                SystemProfileParty.profile_id == profile.id, SystemProfileParty.role == body.role
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Đã có bản ghi cho vai trò này — hãy sửa thay vì thêm")
    db.add(SystemProfileParty(profile_id=profile.id, **body.model_dump()))
    await append_audit(db, action="system_profile.party.add", actor=str(admin.id), target=f"{profile.id}:{body.role}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.put("/{profile_id}/parties/{party_id}", response_model=SystemProfileDetailOut)
async def update_party(
    profile_id: uuid.UUID,
    party_id: uuid.UUID,
    body: SystemProfilePartyIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    party = (
        await db.execute(
            select(SystemProfileParty).where(SystemProfileParty.id == party_id, SystemProfileParty.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if party is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi")
    for field, value in body.model_dump().items():
        setattr(party, field, value)
    await append_audit(db, action="system_profile.party.update", actor=str(admin.id), target=str(party_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.delete("/{profile_id}/parties/{party_id}", response_model=SystemProfileDetailOut)
async def delete_party(
    profile_id: uuid.UUID,
    party_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    party = (
        await db.execute(
            select(SystemProfileParty).where(SystemProfileParty.id == party_id, SystemProfileParty.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if party is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi")
    await db.delete(party)
    await append_audit(db, action="system_profile.party.delete", actor=str(admin.id), target=str(party_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


# ── Ứng dụng / dịch vụ ──────────────────────────────────────


@router.post("/{profile_id}/applications", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def add_application(
    profile_id: uuid.UUID,
    body: SystemProfileApplicationIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    await _validate_machine(db, body.machine_id, profile)
    db.add(SystemProfileApplication(profile_id=profile.id, **body.model_dump()))
    await append_audit(db, action="system_profile.application.add", actor=str(admin.id), target=f"{profile.id}:{body.name}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.put("/{profile_id}/applications/{app_id}", response_model=SystemProfileDetailOut)
async def update_application(
    profile_id: uuid.UUID,
    app_id: uuid.UUID,
    body: SystemProfileApplicationIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    app = (
        await db.execute(
            select(SystemProfileApplication).where(SystemProfileApplication.id == app_id, SystemProfileApplication.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy ứng dụng")
    await _validate_machine(db, body.machine_id, profile)
    for field, value in body.model_dump().items():
        setattr(app, field, value)
    await append_audit(db, action="system_profile.application.update", actor=str(admin.id), target=str(app_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.delete("/{profile_id}/applications/{app_id}", response_model=SystemProfileDetailOut)
async def delete_application(
    profile_id: uuid.UUID,
    app_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    app = (
        await db.execute(
            select(SystemProfileApplication).where(SystemProfileApplication.id == app_id, SystemProfileApplication.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy ứng dụng")
    await db.delete(app)
    await append_audit(db, action="system_profile.application.delete", actor=str(admin.id), target=str(app_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


# ── Quy hoạch vùng mạng & IP ────────────────────────────────


@router.post("/{profile_id}/ip-ranges", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def add_ip_range(
    profile_id: uuid.UUID,
    body: SystemProfileIpRangeIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    db.add(SystemProfileIpRange(profile_id=profile.id, **body.model_dump()))
    await append_audit(db, action="system_profile.ip_range.add", actor=str(admin.id), target=f"{profile.id}:{body.zone}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.put("/{profile_id}/ip-ranges/{range_id}", response_model=SystemProfileDetailOut)
async def update_ip_range(
    profile_id: uuid.UUID,
    range_id: uuid.UUID,
    body: SystemProfileIpRangeIn,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    ip = (
        await db.execute(
            select(SystemProfileIpRange).where(SystemProfileIpRange.id == range_id, SystemProfileIpRange.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if ip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy dải IP")
    for field, value in body.model_dump().items():
        setattr(ip, field, value)
    await append_audit(db, action="system_profile.ip_range.update", actor=str(admin.id), target=str(range_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)


@router.delete("/{profile_id}/ip-ranges/{range_id}", response_model=SystemProfileDetailOut)
async def delete_ip_range(
    profile_id: uuid.UUID,
    range_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_scoped(db, profile_id, admin)
    ip = (
        await db.execute(
            select(SystemProfileIpRange).where(SystemProfileIpRange.id == range_id, SystemProfileIpRange.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if ip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy dải IP")
    await db.delete(ip)
    await append_audit(db, action="system_profile.ip_range.delete", actor=str(admin.id), target=str(range_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_scoped(db, profile_id, admin)
    return _to_detail(profile, None)
