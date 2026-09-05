"""Routes quản trị Velociraptor Custom Artifacts — chỉ Super Admin.

Endpoints (prefix `/api/admin/velociraptor/artifacts`):
  GET    ""                  — list artifact đã lưu + trạng thái hiện diện trên server
  POST   ""                  — validate + push artifact mới (hoặc cập nhật) lên server
  POST   "/sync-from-server" — đồng bộ các artifact Custom.* từ server về DB
  GET    "/{name}"           — chi tiết 1 artifact kèm YAML gốc
  PUT    "/{name}"           — cập nhật definition YAML hoặc metadata của artifact
  DELETE "/{name}"           — xóa artifact trên server và trong DB
  POST   "/{name}/push"      — re-push từ definition đã lưu (server rebuild recovery)

YAML definition là dữ liệu nhạy cảm vận hành: không log, không đưa vào audit
target; audit chỉ ghi action + artifact name.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_super_admin
from app.api.routes.velociraptor import _build_velociraptor_client
from app.core.audit import append_audit
from app.core.client_ip import get_client_ip
from app.db.models import User, VelociraptorArtifact
from app.db.session import get_db
from app.schemas import (
    VelociraptorArtifactDetailOut,
    VelociraptorArtifactOut,
    VelociraptorArtifactSyncOut,
    VelociraptorArtifactUpdate,
    VelociraptorArtifactUpload,
)
from app.services.velociraptor import VelociraptorError
from app.services.velociraptor_artifacts import (
    ArtifactDeleteError,
    ArtifactPushError,
    ArtifactValidationError,
    delete_artifact,
    list_server_artifacts,
    pull_server_artifacts,
    push_artifact,
    validate_artifact_definition,
)

logger = logging.getLogger("api.velociraptor.artifacts")

router = APIRouter(prefix="/api/admin/velociraptor/artifacts", tags=["velociraptor-artifacts"])


def _to_out(row: VelociraptorArtifact, *, on_server: bool) -> VelociraptorArtifactOut:
    return VelociraptorArtifactOut(
        id=row.id,
        name=row.name,
        sha256=row.sha256,
        artifact_type=row.artifact_type,
        enabled=row.enabled,
        supported_platforms=row.supported_platforms,
        selection_priority=row.selection_priority,
        on_server=on_server,
        last_push_status=row.last_push_status,
        last_push_error=row.last_push_error,
        updated_at=row.updated_at,
    )


async def _live_server_names(db: AsyncSession) -> set[str]:
    """Tên Custom.* đang có trên server; rỗng nếu chưa cấu hình/kết nối lỗi."""
    built = await _build_velociraptor_client(db)
    if built is None:
        return set()
    client, _cfg = built
    try:
        async with client:
            return await list_server_artifacts(client)
    except Exception as exc:  # noqa: BLE001 — list không được fail vì server down
        logger.warning("Không đọc được artifact list từ Velociraptor: %s", type(exc).__name__)
        return set()


async def _push_and_record(
    db: AsyncSession, row: VelociraptorArtifact, definition_yaml: str
) -> None:
    """Push definition của row lên server, cập nhật trạng thái push vào row."""
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chưa cấu hình Velociraptor (cần enabled + api_client.yaml mTLS)",
        )
    client, _cfg = built
    try:
        spec = validate_artifact_definition(definition_yaml)
    except ArtifactValidationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    async with client:
        try:
            await push_artifact(client, spec)
        except (ArtifactPushError, VelociraptorError) as exc:
            row.last_push_status = "failed"
            row.last_push_error = str(exc)[:500]
            row.updated_at = datetime.now(UTC)
            await db.commit()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Push artifact lên Velociraptor thất bại — xem last_push_error",
            ) from exc
    row.last_push_status = "pushed"
    row.last_push_error = None
    row.updated_at = datetime.now(UTC)


@router.get("", response_model=list[VelociraptorArtifactOut])
async def list_artifacts(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    rows = (
        (await db.execute(select(VelociraptorArtifact).order_by(VelociraptorArtifact.name)))
        .scalars()
        .all()
    )
    server_names = await _live_server_names(db)
    return [_to_out(row, on_server=row.name in server_names) for row in rows]


@router.post("", response_model=VelociraptorArtifactOut)
async def upload_artifact(
    body: VelociraptorArtifactUpload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    try:
        spec = validate_artifact_definition(body.definition_yaml)
    except ArtifactValidationError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    row = (
        await db.execute(
            select(VelociraptorArtifact).where(VelociraptorArtifact.name == spec.name)
        )
    ).scalar_one_or_none()
    if row is None:
        row = VelociraptorArtifact(
            name=spec.name,
            definition_yaml=spec.definition_yaml,
            sha256=spec.sha256,
            artifact_type=spec.artifact_type,
            supported_platforms=body.supported_platforms,
            selection_priority=body.selection_priority,
            created_by=admin.id,
        )
        db.add(row)
        await db.flush()
    else:
        row.definition_yaml = spec.definition_yaml
        row.sha256 = spec.sha256
        row.artifact_type = spec.artifact_type
        row.supported_platforms = body.supported_platforms
        row.selection_priority = body.selection_priority

    await _push_and_record(db, row, spec.definition_yaml)
    await append_audit(
        db,
        action="velociraptor.artifact.push",
        actor=str(admin.id),
        target=f"velociraptor_artifact:{spec.name}",
        ip=get_client_ip(request),
    )
    await db.commit()
    server_names = await _live_server_names(db)
    return _to_out(row, on_server=row.name in server_names)


@router.post("/sync-from-server", response_model=VelociraptorArtifactSyncOut)
async def sync_artifacts_from_server(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    built = await _build_velociraptor_client(db)
    if built is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Chưa cấu hình Velociraptor (cần enabled + api_client.yaml mTLS)",
        )
    client, _cfg = built
    try:
        async with client:
            server_items = await pull_server_artifacts(client)
    except Exception as exc:
        logger.error("Lỗi khi kéo artifact từ Velociraptor server: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Không thể lấy danh sách artifact từ Velociraptor: {exc}",
        ) from exc

    imported = 0
    updated = 0
    for item in server_items:
        raw_yaml = item.get("raw") or ""
        try:
            spec = validate_artifact_definition(raw_yaml)
        except ArtifactValidationError:
            continue

        row = (
            await db.execute(
                select(VelociraptorArtifact).where(VelociraptorArtifact.name == spec.name)
            )
        ).scalar_one_or_none()
        if row is None:
            lower_yaml = raw_yaml.lower()
            detected_platforms: list[str] = []
            if "windows" in lower_yaml:
                detected_platforms.append("windows")
            if "linux" in lower_yaml:
                detected_platforms.append("linux")
            if "darwin" in lower_yaml or "macos" in lower_yaml:
                detected_platforms.append("macos")
            if not detected_platforms:
                detected_platforms = ["windows"]

            row = VelociraptorArtifact(
                name=spec.name,
                definition_yaml=spec.definition_yaml,
                sha256=spec.sha256,
                artifact_type=spec.artifact_type,
                enabled=True,
                supported_platforms=detected_platforms,
                selection_priority=100,
                last_push_status="pushed",
                last_push_error=None,
                created_by=admin.id,
            )
            db.add(row)
            imported += 1
        else:
            if row.sha256 != spec.sha256:
                row.definition_yaml = spec.definition_yaml
                row.sha256 = spec.sha256
                row.artifact_type = spec.artifact_type
                row.last_push_status = "pushed"
                row.last_push_error = None
                row.updated_at = datetime.now(UTC)
                updated += 1
            else:
                row.last_push_status = "pushed"
                row.last_push_error = None

    await append_audit(
        db,
        action="velociraptor.artifact.sync_from_server",
        actor=str(admin.id),
        target="velociraptor_artifact:sync",
        ip=get_client_ip(request),
    )
    await db.commit()
    return VelociraptorArtifactSyncOut(
        imported=imported,
        updated=updated,
        total_on_server=len(server_items),
    )


@router.get("/{name}", response_model=VelociraptorArtifactDetailOut)
async def get_artifact(
    name: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    row = (
        await db.execute(
            select(VelociraptorArtifact).where(VelociraptorArtifact.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Artifact không tồn tại trong DB")
    server_names = await _live_server_names(db)
    return VelociraptorArtifactDetailOut(
        **_to_out(row, on_server=row.name in server_names).model_dump(),
        definition_yaml=row.definition_yaml,
    )


@router.put("/{name}", response_model=VelociraptorArtifactDetailOut)
async def update_artifact(
    name: str,
    body: VelociraptorArtifactUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    row = (
        await db.execute(
            select(VelociraptorArtifact).where(VelociraptorArtifact.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Artifact không tồn tại trong DB")

    if body.definition_yaml is not None:
        try:
            spec = validate_artifact_definition(body.definition_yaml)
        except ArtifactValidationError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

        if spec.name != name:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Không được đổi tên artifact từ '{name}' thành '{spec.name}' qua PUT. Hãy tạo artifact mới.",
            )
        row.definition_yaml = spec.definition_yaml
        row.sha256 = spec.sha256
        row.artifact_type = spec.artifact_type
        await _push_and_record(db, row, spec.definition_yaml)

    if body.supported_platforms is not None:
        row.supported_platforms = body.supported_platforms
    if body.selection_priority is not None:
        row.selection_priority = body.selection_priority
    if body.enabled is not None:
        row.enabled = body.enabled

    row.updated_at = datetime.now(UTC)
    await append_audit(
        db,
        action="velociraptor.artifact.update",
        actor=str(admin.id),
        target=f"velociraptor_artifact:{name}",
        ip=get_client_ip(request),
    )
    await db.commit()
    server_names = await _live_server_names(db)
    return VelociraptorArtifactDetailOut(
        **_to_out(row, on_server=row.name in server_names).model_dump(),
        definition_yaml=row.definition_yaml,
    )


@router.delete("/{name}")
async def delete_custom_artifact(
    name: str,
    request: Request,
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    row = (
        await db.execute(
            select(VelociraptorArtifact).where(VelociraptorArtifact.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Artifact không tồn tại trong DB")

    built = await _build_velociraptor_client(db)
    if built is not None:
        client, _cfg = built
        async with client:
            try:
                await delete_artifact(client, name)
            except ArtifactDeleteError as exc:
                if not force:
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        detail=f"Xóa artifact trên Velociraptor thất bại: {exc}",
                    ) from exc
                logger.warning(
                    "Force delete artifact %s dù lỗi Velociraptor: %s", name, exc
                )
    elif not force:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Không thể kết nối Velociraptor để xóa. Thêm ?force=true nếu muốn chỉ xóa trong DB.",
        )

    await db.delete(row)
    await append_audit(
        db,
        action="velociraptor.artifact.delete",
        actor=str(admin.id),
        target=f"velociraptor_artifact:{name}",
        ip=get_client_ip(request),
    )
    await db.commit()
    return {"detail": f"Đã xóa artifact {name}", "deleted": True}


@router.post("/{name}/push", response_model=VelociraptorArtifactOut)
async def repush_artifact(
    name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    row = (
        await db.execute(
            select(VelociraptorArtifact).where(VelociraptorArtifact.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Artifact không tồn tại trong DB")

    await _push_and_record(db, row, row.definition_yaml)
    await append_audit(
        db,
        action="velociraptor.artifact.repush",
        actor=str(admin.id),
        target=f"velociraptor_artifact:{row.name}",
        ip=get_client_ip(request),
    )
    await db.commit()
    server_names = await _live_server_names(db)
    return _to_out(row, on_server=row.name in server_names)
