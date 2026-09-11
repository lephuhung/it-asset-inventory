"""Route hồ sơ cấp độ hệ thống thông tin (cấp 1–3).

- `GET /api/system-profiles`                 — danh sách (scope theo org của user).
- `POST /api/system-profiles`                — tạo hồ sơ (Admin/Super Admin, mã hồ sơ tự sinh).
- `GET /api/system-profiles/stats`           — thống kê theo trạng thái + cấp độ.
- `GET /api/system-profiles/{id}`            — chi tiết (kèm devices + machines).
- `PATCH /api/system-profiles/{id}`          — sửa thông tin / sơ đồ mermaid.
- `DELETE /api/system-profiles/{id}`         — xóa (Super Admin, hoặc Admin khi chưa trình).
- `POST /api/system-profiles/{id}/submit`    — trình duyệt (Admin → pending_review).
- `POST /api/system-profiles/{id}/review`    — Super Admin approve/reject.
- `POST /api/system-profiles/{id}/report-implementation`     — đơn vị khai báo đã triển khai.
- `POST /api/system-profiles/{id}/confirm-implementation`    — Super Admin xác nhận đáp ứng hồ sơ.
- `POST/PUT/DELETE .../devices[...]`         — CRUD thiết bị khai báo.
- `POST/DELETE .../machines`                 — gắn/gỡ Machine đã enroll.

Luồng phê duyệt: `drafted` → `pending_review` → `approved`/`rejected`;
sau approved: đơn vị khai báo đã triển khai (`implemented`) → Super Admin
xác nhận đáp ứng (`fulfilled`).
Super Admin tạo/sửa được approve trực tiếp (kèm số quyết định).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    get_current_user,
    is_super_admin,
    require_admin,
    require_super_admin,
    visible_org_ids,
)
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import (
    DeviceType,
    ItContact,
    LevelRequirement,
    Machine,
    Officer,
    Organization,
    ProfileRequirementStatus,
    ServiceAudience,
    SystemDevice,
    SystemProfile,
    SystemProfileApplication,
    SystemProfileContact,
    SystemProfileEvent,
    SystemProfileIpRange,
    SystemProfileMachine,
    SystemProfileParty,
    SystemProfileRequirement,
    SystemProfileStatus,
    User,
)
from app.db.session import get_db
from app.schemas import (
    LevelRequirementIn,
    LevelRequirementOut,
    LevelRequirementUpdate,
    OfficerOut,
    Page,
    ProfileRequirementOut,
    ProfileRequirementRequest,
    ProfileRequirementReview,
    SystemProfileApplicationIn,
    SystemProfileApplicationOut,
    SystemProfileAssignOfficerIn,
    SystemProfileConfirmImplementation,
    SystemProfileContactOut,
    SystemProfileCreate,
    SystemProfileDetailOut,
    SystemProfileDeviceIn,
    SystemProfileDeviceOut,
    SystemProfileEventOut,
    SystemProfileIpRangeIn,
    SystemProfileIpRangeOut,
    SystemProfileMachineOut,
    SystemProfileOut,
    SystemProfilePartyIn,
    SystemProfilePartyOut,
    SystemProfileReportImplementation,
    SystemProfileReview,
    SystemProfileStats,
    SystemProfileUpdate,
)

router = APIRouter(prefix="/api/system-profiles", tags=["system-profiles"])

def _log_event(db: AsyncSession, profile: SystemProfile, event: str, message: str, actor: User | None) -> None:
    """Ghi 1 mốc timeline của hồ sơ (gọi trước commit, cùng transaction)."""
    db.add(
        SystemProfileEvent(
            profile_id=profile.id,
            event=event,
            message=message,
            actor_id=actor.id if actor else None,
            actor_name=actor.full_name if actor else None,
        )
    )


async def _valid_device_type(db: AsyncSession, device_type: str) -> bool:
    """Validate `device_type` tra catalog `device_types` (quản trị động).

    Chỉ chấp nhận `code` còn đang active. Dữ liệu cũ dùng inactive type vẫn
    được đọc/render bình thường — bất kỳ create/update device mới phải chọn
    code đang hoạt động (xem P2-3 fix).
    """
    return (
        await db.execute(
            select(func.count()).select_from(DeviceType).where(
                DeviceType.code == device_type,
                DeviceType.is_active.is_(True),
            )
        )
    ).scalar_one() > 0


# Trạng thái hồ sơ mà nội dung dossier được coi là "đã chốt" — Org Admin
# không được mutate child resource (devices, machines, parties, applications,
# ip-ranges). Super Admin vẫn được phép (override có audit + timeline).
_FROZEN_STATUSES: frozenset[str] = frozenset({
    SystemProfileStatus.APPROVED.value,
    SystemProfileStatus.IMPLEMENTED.value,
    SystemProfileStatus.FULFILLED.value,
})


def assert_profile_content_mutable(
    profile: SystemProfile, user: User, *, action: str
) -> None:
    """Guard tập trung: chặn Org Admin mutate nội dung dossier khi hồ sơ đã chốt.

    - Status: approved / implemented / fulfilled (đã có quyết định / đã triển khai).
    - Org Admin → 400, message rõ ràng cho client hiển thị.
    - Super Admin vẫn được mutate (ghi timeline qua `_log_event`).

    Endpoint nào mutate **nội dung** (devices, machines, parties,
    applications, ip-ranges) phải gọi guard này. Endpoint chỉ mutate
    workflow (submit/review, requirement request/review) thì KHÔNG gọi.
    """
    if is_super_admin(user):
        return
    if profile.status in _FROZEN_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Hồ sơ đã ở trạng thái '{profile.status}' — không thể {action}. "
                "Liên hệ quản trị viên hệ thống để chỉnh sửa."
            ),
        )


async def _get_profile_scoped(db: AsyncSession, profile_id: uuid.UUID, user: User) -> SystemProfile:
    """Lấy hồ sơ theo id với scope **chỉ đọc** (Org Admin đọc được cả con).

    Dùng cho endpoint GET. Endpoint mutation phải dùng `_get_profile_mutable`.
    """
    profile = (
        await db.execute(
            select(SystemProfile)
            .options(
                selectinload(SystemProfile.devices),
                selectinload(SystemProfile.ip_ranges),
                selectinload(SystemProfile.contacts).selectinload(SystemProfileContact.contact),
                selectinload(SystemProfile.events),
                selectinload(SystemProfile.officer),
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


async def _get_profile_mutable(
    db: AsyncSession, profile_id: uuid.UUID, user: User
) -> SystemProfile:
    """Lấy hồ sơ cho endpoint **mutation** — Org Admin chỉ mutate được hồ sơ
    của CHÍNH đơn vị mình, không phải của org cấp dưới.

    Phân biệt rõ với `_get_profile_scoped` (read visibility bao gồm cả cây con)
    để tránh privilege escalation: Org Admin của parent org không nên sửa /
    xóa / mutate child-org profile dù vẫn đọc được.

    Super Admin giữ toàn quyền.
    """
    profile = await _get_profile_scoped(db, profile_id, user)
    if not is_super_admin(user) and str(profile.org_id) != str(user.org_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Chỉ được sửa hồ sơ thuộc đơn vị của bạn",
        )
    return profile

def _officer_out(o: Officer) -> OfficerOut:
    return OfficerOut(
        id=o.id, name=o.name, organization=o.organization, title=o.title,
        phone=o.phone, email=o.email, note=o.note,
        profile_count=0,  # computed lazily; không cần trong profile response
        created_at=o.created_at, updated_at=o.updated_at,
    )


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
        managed_by=profile.managed_by,
        officer_id=profile.officer_id,
        officer=_officer_out(profile.officer) if profile.officer is not None else None,
        document_number=profile.document_number,
        document_date=profile.document_date,
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
        events=[
            SystemProfileEventOut(
                id=e.id, event=e.event, message=e.message,
                actor_id=e.actor_id, actor_name=e.actor_name, created_at=e.created_at,
            )
            # sort phòng khi selectinload không áp order_by của relationship
            for e in sorted(profile.events or [], key=lambda x: x.created_at, reverse=True)
        ],
        contacts=[
            SystemProfileContactOut(
                contact_id=pc.contact_id, kind=pc.contact.kind, name=pc.contact.name,
                position=pc.contact.position, contact_person=pc.contact.contact_person,
                phone=pc.contact.phone, email=pc.contact.email, note=pc.note, added_at=pc.added_at,
            )
            for pc in (profile.contacts or [])
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
        like = f"%{q}%"
        conds.append(SystemProfile.name.ilike(like) | SystemProfile.code.ilike(like) | SystemProfile.document_number.ilike(like))

    base = select(SystemProfile).options(
        selectinload(SystemProfile.devices),
        selectinload(SystemProfile.machines).selectinload(SystemProfileMachine.machine),
        selectinload(SystemProfile.requirements).selectinload(SystemProfileRequirement.requirement),
        selectinload(SystemProfile.officer),
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


async def _generate_profile_code(db: AsyncSession, org_id: uuid.UUID) -> str:
    """Sinh mã hồ sơ `HS-{năm}-{seq 3 chữ số}` — seq đếm theo đơn vị + năm.

    Race-safe: SELECT-max-then-INSERT có thể trùng code khi nhiều transaction
    chạy song song (cùng max(seq)). Khi caller INSERT bị `IntegrityError` do
    vi phạm unique constraint `(org_id, code)`, họ sẽ retry — generator
    thực hiện pre-check và trả code mới; tuy nhiên cạnh tranh vẫn có thể
    xảy ra. Caller (POST endpoint) phải catch IntegrityError và re-call
    generator. Hàm này cố tình không retry tự động để giữ trách nhiệm rõ
    ràng cho transaction layer.
    """
    year = datetime.now(UTC).year
    prefix = f"HS-{year}-"
    rows = (
        await db.execute(
            select(SystemProfile.code).where(
                SystemProfile.org_id == org_id, SystemProfile.code.like(f"{prefix}%")
            )
        )
    ).scalars().all()
    seq = 0
    for code in rows:
        try:
            seq = max(seq, int(code[len(prefix):]))
        except ValueError:
            continue
    return f"{prefix}{seq + 1:03d}"


async def _create_profile_with_unique_code(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    creator: User,
    name: str,
    level: int,
    description: str | None = None,
    diagram_mermaid: str | None = None,
    decision_number: str | None = None,
    decision_date: datetime | None = None,
    decision_agency: str | None = None,
    max_attempts: int = 5,
) -> SystemProfile:
    """Tạo SystemProfile với code duy nhất — bounded retry khi race condition.

    Sinh code qua `_generate_profile_code`; nếu INSERT vi phạm unique constraint
    `(org_id, code)`, retry với code mới. Sau `max_attempts` lần thất bại thì
    raise IntegrityError để caller xử lý (không bị nuốt lỗi).
    """
    from sqlalchemy.exc import IntegrityError

    # Snapshot các trường cần từ creator TRƯỚC retry loop và TRƯỚC BẤT KỲ
    # rollback nào: production truyền persistent `User` được load từ chính
    # AsyncSession của request. Sau rollback, ORM state persistent bị expire —
    # đọc `creator.id` / `creator.role` lại sẽ trigger implicit refresh
    # (async IO không mong đợi / MissingGreenlet trên AsyncSession).
    creator_id = creator.id
    creator_role = getattr(creator, "role", None)
    is_super = creator_role in {"super_admin", "admin_global"}
    # Super Admin có decision_number → approved ngay
    status_value = (
        SystemProfileStatus.APPROVED.value
        if is_super and decision_number
        else SystemProfileStatus.DRAFTED.value
    )

    last_error: IntegrityError | None = None
    for _ in range(max_attempts):
        code = await _generate_profile_code(db, org_id)
        profile = SystemProfile(
            org_id=org_id,
            code=code,
            name=name,
            level=level,
            description=description,
            diagram_mermaid=diagram_mermaid,
            status=status_value,
            decision_number=decision_number if is_super else None,
            decision_date=decision_date if is_super else None,
            decision_agency=decision_agency if is_super else None,
            reviewed_by=creator_id if is_super and decision_number else None,
            reviewed_at=datetime.now(UTC) if is_super and decision_number else None,
            created_by=creator_id,
        )
        try:
            # BLOCKER 1 v4: mỗi attempt chạy trong SAVEPOINT (nested
            # transaction). Unique collision chỉ rollback savepoint của attempt
            # đó — outer transaction + session state (creator snapshot, các
            # object khác đang pending của request) còn nguyên. Trước fix dùng
            # `db.rollback()` toàn transaction → expire mọi persistent state.
            async with db.begin_nested():
                db.add(profile)
                await db.flush()
            return profile
        except IntegrityError as exc:
            # BLOCKER 3 narrowing: chỉ retry khi lỗi thuộc UNIQUE constraint
            # `uq_system_profiles_org_code` (2 transactions race trên cùng code).
            # FK / NOT NULL / check constraint khác phải propagate ngay để caller
            # biết — không lặp 5 lần gây trễ + vẫn fail. Savepoint đã được
            # rollback bởi context manager; failed profile của attempt bị
            # resurrect về transient, không pollute session state.
            if not _is_unique_code_violation(exc):
                raise
            last_error = exc
            # Thử lại với code mới
            continue
    # Hết lần retry — vẫn trả IntegrityError để caller thấy
    assert last_error is not None
    raise last_error


def _is_unique_code_violation(exc: IntegrityError) -> bool:
    """Inspect IntegrityError.orig to determine if it's the unique constraint
    `(org_id, code)` violation on system_profiles. Returns True nếu chỉ conflict
    unique trên 2 cột đó, False cho FK / NOT NULL / check constraint khác.

    PostgreSQL: IntegrityError.orig is asyncpg.exceptions.UniqueViolationError
    (subclass of asyncpg.IntegrityConstraintError). constraint_name attribute
    chứa tên constraint.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name is None:
        # Thử parse từ message nếu attribute không có.
        msg = str(orig)
        if "uq_system_profiles_org_code" in msg:
            return True
        return False
    return constraint_name == "uq_system_profiles_org_code"


async def _find_party_by_role(
    db: AsyncSession, profile_id: uuid.UUID, role: str
) -> SystemProfileParty | None:
    """Tìm party row theo (profile_id, role). Tách thành helper để test có thể
    monkey-patch bypass pre-check → exercise DB conflict path thực sự.
    """
    return (
        await db.execute(
            select(SystemProfileParty).where(
                SystemProfileParty.profile_id == profile_id,
                SystemProfileParty.role == role,
            )
        )
    ).scalar_one_or_none()


def _is_party_role_unique_violation(exc: IntegrityError) -> bool:
    """Tương tự _is_unique_code_violation, nhưng cho `uq_system_profile_party_role`.

    P2 v3 narrowing: add_party catch IntegrityError quá rộng. Chỉ map constraint
    này thành 409; các FK / NOT NULL khác phải propagate để caller thấy lỗi
    thực (debug rõ hơn).
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name is None:
        msg = str(orig)
        if "uq_system_profile_party_role" in msg:
            return True
        return False
    return constraint_name == "uq_system_profile_party_role"


@router.get("/stats", response_model=SystemProfileStats)
async def profile_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Thống kê hồ sơ cấp độ theo trạng thái + cấp độ (scope theo đơn vị)."""
    conds = []
    if not is_super_admin(user):
        conds.append(SystemProfile.org_id.in_(await visible_org_ids(db, user)))
    status_q = select(SystemProfile.status, func.count()).group_by(SystemProfile.status)
    level_q = select(SystemProfile.level, func.count()).group_by(SystemProfile.level)
    if conds:
        status_q = status_q.where(*conds)
        level_q = level_q.where(*conds)
    by_status = {s: c for s, c in (await db.execute(status_q)).all()}
    by_level = {str(l): c for l, c in (await db.execute(level_q)).all()}
    return SystemProfileStats(total=sum(by_status.values()), by_status=by_status, by_level=by_level)


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

    approved_directly = is_super_admin(admin) and bool(body.decision_number)
    # P2-4 fix: dùng `_create_profile_with_unique_code` thay vì chỉ
    # `_generate_profile_code`. Generator SELECT-max-then-INSERT có race:
    # hai transaction đồng thời cùng đọc max(seq) và INSERT cùng code →
    # unique constraint `(org_id, code)` sẽ reject 1 trong 2, gây 500
    # unhandled. Helper mới catch IntegrityError và retry với code mới
    # (bounded = 5 attempts).
    profile = await _create_profile_with_unique_code(
        db,
        org_id=body.org_id,
        creator=admin,
        name=body.name.strip(),
        level=body.level,
        description=body.description,
        diagram_mermaid=body.diagram_mermaid,
        decision_number=body.decision_number if approved_directly else None,
        decision_date=body.decision_date if approved_directly else None,
        decision_agency=body.decision_agency if approved_directly else None,
    )
    profile.managed_by = body.managed_by
    profile.document_number = body.document_number
    profile.document_date = body.document_date
    await db.flush()  # cần profile.id để ghi event
    _log_event(db, profile, "created", f"Tạo hồ sơ (cấp độ {body.level})" + (f" — số văn bản đề nghị {body.document_number}" if body.document_number else ""), admin)
    await append_audit(
        db,
        action="system_profile.create",
        actor=str(admin.id),
        target=f"{body.org_id}:{profile.code}",
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    # Lưu ý: KHÔNG gọi assert_profile_content_mutable ở đây — endpoint này có
    # rule riêng cho phép Org Admin sửa `managed_by` + `document_*` sau approval
    # (xem check `set(changes) - {"managed_by"}` ngay dưới). Việc khóa hồ sơ
    # sau approval đã được thực thi bởi child-resource endpoints (devices,
    # machines, parties, applications, ip_ranges, contacts) thông qua guard.
    # P2 nullable clearing: dùng `exclude_unset=True` (bỏ field không gửi)
    # nhưng GIỮ `None` explicit — cho phép client xóa nullable field qua JSON null.
    # Các field business-rule không cho phép null (vd name, level) check riêng.
    changes = body.model_dump(exclude_unset=True)
    # Số văn bản đề nghị + ngày văn bản có thể bổ sung sau, kể cả khi đã duyệt
    doc_fields = {f: changes.pop(f) for f in ("document_number", "document_date") if f in changes}
    if profile.status in (SystemProfileStatus.APPROVED.value, SystemProfileStatus.IMPLEMENTED.value, SystemProfileStatus.FULFILLED.value) and not is_super_admin(admin):
        if set(changes) - {"managed_by"}:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Hồ sơ đã được phê duyệt — chỉ sửa được tên chủ quản và số văn bản, liên hệ quản trị viên hệ thống để sửa nội dung khác",
            )
    if "service_audience" in changes and changes["service_audience"] not in {a.value for a in ServiceAudience}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="service_audience không hợp lệ")
    level_changed = "level" in changes and changes["level"] != profile.level
    # P2-1 fix: snapshot giá trị cũ TRƯỚC khi setattr. Trước fix, log_event dùng
    # `profile.level` đã bị thay bằng `changes["level"]` → event ghi "3 → 2" thay vì
    # "2 → 3" (vd). Phải capture old value trước mutation.
    old_level = profile.level if level_changed else None
    for field, value in {**changes, **doc_fields}.items():
        setattr(profile, field, value)
    # Ghi timeline chi tiết từng trường thay đổi (diff) để quản trị dễ truy vết
    FIELD_LABELS = {
        "name": "Tên hệ thống",
        "description": "Mô tả",
        "diagram_mermaid": "Sơ đồ lô-gic",
        "physical_diagram_mermaid": "Sơ đồ vật lý",
        "physical_location": "Địa điểm lắp đặt",
        "user_accounts": "Số lượng tài khoản",
        "data_volume": "Lượng dữ liệu",
        "service_audience": "Đối tượng sử dụng",
        "managed_by": "Tên chủ quản",
    }
    changed_labels = [FIELD_LABELS[f] for f in changes if f in FIELD_LABELS]
    if "level" in changes and level_changed:
        # Dùng snapshot `old_level` thay vì `profile.level` (đã bị setattr thành new).
        _log_event(
            db, profile, "level_changed",
            f"Đổi cấp độ đề xuất: {old_level} → {changes['level']}",
            admin,
        )
    if doc_fields:
        parts = [f"{'Số văn bản' if f == 'document_number' else 'Ngày văn bản'}: {v}" for f, v in doc_fields.items()]
        _log_event(db, profile, "document_updated", "Cập nhật văn bản đề nghị — " + "; ".join(parts), admin)
    if changed_labels:
        _log_event(db, profile, "updated", "Cập nhật hồ sơ: " + ", ".join(changed_labels), admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    if profile.status not in (SystemProfileStatus.DRAFTED.value, SystemProfileStatus.REJECTED.value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Hồ sơ đã được trình hoặc đã duyệt")
    profile.status = SystemProfileStatus.PENDING_REVIEW.value
    _log_event(db, profile, "submitted", "Trình hồ sơ để thẩm định", admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
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
        _log_event(db, profile, "approved", f"Phê duyệt hồ sơ — quyết định {body.decision_number.strip()}", admin)
    else:
        if not body.review_note or not body.review_note.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Phải nhập lý do từ chối để đơn vị biết và sửa hồ sơ")
        profile.status = SystemProfileStatus.REJECTED.value
        profile.review_note = body.review_note.strip()
        _log_event(db, profile, "rejected", f"Từ chối hồ sơ: {body.review_note.strip()}", admin)
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


@router.post("/{profile_id}/report-implementation", response_model=SystemProfileDetailOut)
async def report_implementation(
    profile_id: uuid.UUID,
    body: SystemProfileReportImplementation,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Đơn vị khai báo đã triển khai hệ thống theo hồ sơ (approved → implemented).

    Hồ sơ là căn cứ để đơn vị triển khai hệ thống đảm bảo cấp độ đã được duyệt;
    khi triển khai xong, đơn vị khai báo để Super Admin xác nhận đáp ứng.
    """
    profile = await _get_profile_mutable(db, profile_id, admin)
    if profile.status != SystemProfileStatus.APPROVED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chỉ khai báo được với hồ sơ đã được phê duyệt")
    if not is_super_admin(admin) and str(admin.org_id) != str(profile.org_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ đơn vị của hồ sơ được khai báo triển khai")
    # Hồ sơ là căn cứ triển khai — phải đáp ứng đủ 100% yêu cầu ATTT của cấp độ đã thẩm định đạt
    reqs = profile.requirements or []
    verified = sum(1 for r in reqs if r.status == ProfileRequirementStatus.VERIFIED.value)
    if not reqs or verified < len(reqs):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Chưa đáp ứng đủ yêu cầu cấp độ {profile.level} ({verified}/{len(reqs)} đã thẩm định đạt) — hãy trình và hoàn tất thẩm định trước khi khai báo triển khai",
        )
    profile.status = SystemProfileStatus.IMPLEMENTED.value
    if body.note:
        profile.review_note = body.note.strip()
    # P2-2: lưu note vào timeline event để giữ audit history (review_note
    # chỉ là latest; timeline là immutable history). Mọi note cũ vẫn truy vết
    # được dù bị overwrite bởi confirm_implementation / reject sau này.
    impl_note = (body.note or "").strip()
    _log_event(
        db, profile, "implementation_reported",
        f"Đơn vị khai báo đã triển khai hệ thống theo hồ sơ"
        + (f" — note: {impl_note}" if impl_note else ""),
        admin,
    )
    await append_audit(db, action="system_profile.report_implementation", actor=str(admin.id), target=str(profile.id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    return _to_detail(profile, None)


@router.post("/{profile_id}/confirm-implementation", response_model=SystemProfileDetailOut)
async def confirm_implementation(
    profile_id: uuid.UUID,
    body: SystemProfileConfirmImplementation,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin xác nhận đơn vị đã đáp ứng hồ sơ (implemented → fulfilled)."""
    profile = await _get_profile_mutable(db, profile_id, admin)
    if profile.status != SystemProfileStatus.IMPLEMENTED.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Chỉ xác nhận được hồ sơ đang ở trạng thái đã khai báo triển khai")
    fulfill_note = (body.review_note or "").strip() if body.review_note else ""
    if body.review_note:
        profile.review_note = fulfill_note
    profile.status = SystemProfileStatus.FULFILLED.value
    profile.reviewed_by = admin.id
    profile.reviewed_at = datetime.now(UTC)
    _log_event(
        db, profile, "fulfilled",
        f"Xác nhận đơn vị đã đáp ứng hồ sơ"
        + (f" — review_note: {fulfill_note}" if fulfill_note else ""),
        admin,
    )
    await append_audit(db, action="system_profile.confirm_implementation", actor=str(admin.id), target=str(profile.id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    if not await _valid_device_type(db, body.device_type):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Loại thiết bị không hợp lệ: {body.device_type}")
    await _validate_machine(db, body.machine_id, profile)
    db.add(SystemDevice(profile_id=profile.id, **body.model_dump()))
    _log_event(db, profile, "device_added", f"Thêm thiết bị: {body.name} ({body.device_type})", admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    _log_event(db, profile, "device_updated", f"Cập nhật thiết bị: {body.name}", admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    device = (
        await db.execute(
            select(SystemDevice).where(SystemDevice.id == device_id, SystemDevice.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy thiết bị")
    await db.delete(device)
    _log_event(db, profile, "device_removed", f"Xóa thiết bị: {device.name}", admin)
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
    request: Request = None,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    hostname = (await db.execute(select(Machine.hostname).where(Machine.id == machine_id))).scalar_one_or_none()
    _log_event(db, profile, "machine_attached", f"Gắn máy tính: {hostname or machine_id}", admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    hostname = link.machine.hostname if link.machine else None
    await db.delete(link)
    _log_event(db, profile, "machine_detached", f"Gỡ máy tính: {hostname or machine_id}", admin)
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


# ── Chuyên trách CNTT / tổ chức vận hành gắn vào hồ sơ ──────


@router.post("/{profile_id}/contacts/{contact_id}", response_model=SystemProfileDetailOut, status_code=status.HTTP_201_CREATED)
async def attach_contact(
    profile_id: uuid.UUID,
    contact_id: uuid.UUID,
    note: str | None = None,
    request: Request = None,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Gắn chuyên trách CNTT / tổ chức vận hành (từ danh bạ) vào hồ sơ.

    Contact phải cùng đơn vị với hồ sơ. `note` ghi vai trò trong hồ sơ
    (vd: phụ trách vận hành, đầu mối kỹ thuật).
    """
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    contact = (await db.execute(select(ItContact).where(ItContact.id == contact_id))).scalar_one_or_none()
    if contact is None or str(contact.org_id) != str(profile.org_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Contact không thuộc đơn vị của hồ sơ")
    exists = (
        await db.execute(
            select(SystemProfileContact).where(
                SystemProfileContact.profile_id == profile.id,
                SystemProfileContact.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Contact đã nằm trong hồ sơ")
    db.add(SystemProfileContact(profile_id=profile.id, contact_id=contact_id, note=note))
    kind_label = "Tổ chức vận hành" if contact.kind == "org" else "Chuyên trách CNTT"
    _log_event(db, profile, "contact_attached", f"Gắn {kind_label.lower()}: {contact.name}", admin)
    await append_audit(db, action="system_profile.contact.attach", actor=str(admin.id), target=f"{profile.id}:{contact_id}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    return _to_detail(profile, None)


@router.delete("/{profile_id}/contacts/{contact_id}", response_model=SystemProfileDetailOut)
async def detach_contact(
    profile_id: uuid.UUID,
    contact_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    link = (
        await db.execute(
            select(SystemProfileContact).where(
                SystemProfileContact.profile_id == profile.id,
                SystemProfileContact.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Contact không nằm trong hồ sơ")
    contact_name = link.contact.name if link.contact else str(contact_id)
    await db.delete(link)
    _log_event(db, profile, "contact_detached", f"Gỡ chuyên trách/tổ chức: {contact_name}", admin)
    await append_audit(db, action="system_profile.contact.detach", actor=str(admin.id), target=f"{profile.id}:{contact_id}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    return _to_detail(profile, None)


@router.put("/{profile_id}/officer", response_model=SystemProfileDetailOut)
async def assign_officer(
    profile_id: uuid.UUID,
    body: SystemProfileAssignOfficerIn,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Gán cán bộ phụ trách (từ bảng officers) cho hồ sơ.

    1 hồ sơ - 1 cán bộ; gọi lại để thay thế. Thông tin cán bộ (tên, tổ chức, …)
    sống ở bảng `officers` — chỉnh sửa 1 chỗ áp dụng cho mọi hồ sơ đang gán.
    """
    profile = await _get_profile_mutable(db, profile_id, admin)
    officer = (
        await db.execute(select(Officer).where(Officer.id == body.officer_id))
    ).scalar_one_or_none()
    if officer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cán bộ")
    was_existing = profile.officer_id is not None
    previous_id = profile.officer_id
    profile.officer_id = officer.id
    verb = "Đổi" if was_existing else "Chỉ định"
    if was_existing and previous_id == officer.id:
        verb = "Cập nhật"
    _log_event(
        db, profile, "officer_assigned",
        f"{verb} cán bộ phụ trách: {officer.name}",
        admin,
    )
    await append_audit(
        db, action="system_profile.officer.assign", actor=str(admin.id),
        target=f"{profile.id}:{officer.id}", ip=get_client_ip(request),
    )
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    return _to_detail(profile, None)


@router.delete("/{profile_id}/officer", response_model=SystemProfileDetailOut)
async def unassign_officer(
    profile_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_super_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Gỡ cán bộ phụ trách khỏi hồ sơ. Bản ghi officer vẫn còn trong bảng officers."""
    profile = await _get_profile_mutable(db, profile_id, admin)
    if profile.officer_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hồ sơ chưa có cán bộ phụ trách")
    removed = profile.officer
    removed_name = removed.name if removed else str(profile.officer_id)
    profile.officer_id = None
    _log_event(
        db, profile, "officer_cleared",
        f"Gỡ cán bộ phụ trách: {removed_name}",
        admin,
    )
    await append_audit(
        db, action="system_profile.officer.unassign", actor=str(admin.id),
        target=str(profile.id), ip=get_client_ip(request),
    )
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
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
    req_title = (await db.execute(select(LevelRequirement.title).where(LevelRequirement.id == row.requirement_id))).scalar_one_or_none() or ""
    _log_event(db, profile, "requirement_requested", f"Trình thẩm định yêu cầu ATTT: {req_title}", admin)
    await append_audit(db, action="system_profile.requirement.request", actor=str(admin.id), target=f"{profile.id}:{row_id}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
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
    req_title = (await db.execute(select(LevelRequirement.title).where(LevelRequirement.id == row.requirement_id))).scalar_one_or_none() or ""
    if body.action == "verify":
        _log_event(db, profile, "requirement_verified", f"Thẩm định ĐẠT yêu cầu ATTT: {req_title}", admin)
    else:
        _log_event(db, profile, "requirement_rejected", f"Thẩm định KHÔNG ĐẠT yêu cầu ATTT: {req_title}" + (f" — {body.review_note}" if body.review_note else ""), admin)
    await append_audit(db, action=f"system_profile.requirement.{body.action}", actor=str(admin.id), target=f"{profile.id}:{row_id}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    # Pre-check duplicate role (UX friendly). Có thể bypass bằng monkeypatch
    # `_find_party_by_role` trong test (DB constraint vẫn enforce ở commit).
    dup = await _find_party_by_role(db, profile.id, body.role)
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Đã có bản ghi cho vai trò này — hãy sửa thay vì thêm")
    db.add(SystemProfileParty(profile_id=profile.id, **body.model_dump()))
    # _log_event / append_audit / commit đều có thể trigger autoflush (audit log
    # cần SELECT last_hash trước khi INSERT). Wrap toàn bộ flow trong try để
    # catch IntegrityError ngay tại flush đầu tiên, KHÔNG chỉ ở commit.
    try:
        _log_event(db, profile, "party_added", f"Khai báo {'đơn vị chủ quản' if body.role == 'owner' else 'đơn vị vận hành'}: {body.name}", admin)
        await append_audit(db, action="system_profile.party.add", actor=str(admin.id), target=f"{profile.id}:{body.role}", ip=get_client_ip(request))
        await db.commit()
    except IntegrityError as exc:
        # P2 race + v3 narrowing: chỉ map unique constraint
        # `uq_system_profile_party_role` thành 409 Conflict. FK / NOT NULL /
        # check constraint khác phải propagate (caller sẽ thấy 500 với detail
        # lỗi cụ thể — chấp nhận được, vì đó là bug khác cần fix riêng).
        if not _is_party_role_unique_violation(exc):
            await db.rollback()
            raise
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Đã có bản ghi cho vai trò này (constraint violation).",
        ) from exc
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    party = (
        await db.execute(
            select(SystemProfileParty).where(SystemProfileParty.id == party_id, SystemProfileParty.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if party is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi")
    for field, value in body.model_dump().items():
        setattr(party, field, value)
    _log_event(db, profile, "party_updated", f"Cập nhật thông tin {'chủ quản' if body.role == 'owner' else 'đơn vị vận hành'}: {body.name}", admin)
    await append_audit(db, action="system_profile.party.update", actor=str(admin.id), target=str(party_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    return _to_detail(profile, None)


@router.delete("/{profile_id}/parties/{party_id}", response_model=SystemProfileDetailOut)
async def delete_party(
    profile_id: uuid.UUID,
    party_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    party = (
        await db.execute(
            select(SystemProfileParty).where(SystemProfileParty.id == party_id, SystemProfileParty.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if party is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi")
    party_name = party.name
    await db.delete(party)
    _log_event(db, profile, "party_removed", f"Xóa thông tin chủ quản/vận hành: {party_name}", admin)
    await append_audit(db, action="system_profile.party.delete", actor=str(admin.id), target=str(party_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    await _validate_machine(db, body.machine_id, profile)
    db.add(SystemProfileApplication(profile_id=profile.id, **body.model_dump()))
    _log_event(db, profile, "application_added", f"Khai báo ứng dụng/dịch vụ: {body.name}", admin)
    await append_audit(db, action="system_profile.application.add", actor=str(admin.id), target=f"{profile.id}:{body.name}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    _log_event(db, profile, "application_updated", f"Cập nhật ứng dụng/dịch vụ: {body.name}", admin)
    await append_audit(db, action="system_profile.application.update", actor=str(admin.id), target=str(app_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    return _to_detail(profile, None)


@router.delete("/{profile_id}/applications/{app_id}", response_model=SystemProfileDetailOut)
async def delete_application(
    profile_id: uuid.UUID,
    app_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    app = (
        await db.execute(
            select(SystemProfileApplication).where(SystemProfileApplication.id == app_id, SystemProfileApplication.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy ứng dụng")
    app_name = app.name
    await db.delete(app)
    _log_event(db, profile, "application_removed", f"Xóa ứng dụng/dịch vụ: {app_name}", admin)
    await append_audit(db, action="system_profile.application.delete", actor=str(admin.id), target=str(app_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    db.add(SystemProfileIpRange(profile_id=profile.id, **body.model_dump()))
    _log_event(db, profile, "ip_range_added", f"Khai báo vùng mạng {body.zone} ({body.cidr})", admin)
    await append_audit(db, action="system_profile.ip_range.add", actor=str(admin.id), target=f"{profile.id}:{body.zone}", ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
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
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    ip = (
        await db.execute(
            select(SystemProfileIpRange).where(SystemProfileIpRange.id == range_id, SystemProfileIpRange.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if ip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy dải IP")
    for field, value in body.model_dump().items():
        setattr(ip, field, value)
    _log_event(db, profile, "ip_range_updated", f"Cập nhật vùng mạng {body.zone} ({body.cidr})", admin)
    await append_audit(db, action="system_profile.ip_range.update", actor=str(admin.id), target=str(range_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    return _to_detail(profile, None)


@router.delete("/{profile_id}/ip-ranges/{range_id}", response_model=SystemProfileDetailOut)
async def delete_ip_range(
    profile_id: uuid.UUID,
    range_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    ip = (
        await db.execute(
            select(SystemProfileIpRange).where(SystemProfileIpRange.id == range_id, SystemProfileIpRange.profile_id == profile.id)
        )
    ).scalar_one_or_none()
    if ip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Không tìm thấy dải IP")
    ip_zone, ip_cidr = ip.zone, ip.cidr
    await db.delete(ip)
    _log_event(db, profile, "ip_range_removed", f"Xóa vùng mạng {ip_zone} ({ip_cidr})", admin)
    await append_audit(db, action="system_profile.ip_range.delete", actor=str(admin.id), target=str(range_id), ip=get_client_ip(request))
    await db.commit()
    profile = await _get_profile_mutable(db, profile_id, admin)
    assert_profile_content_mutable(profile, admin, action="mutate nội dung hồ sơ")
    return _to_detail(profile, None)
