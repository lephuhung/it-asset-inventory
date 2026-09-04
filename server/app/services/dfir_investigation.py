"""Orchestrator cho LLM-DFIR investigation.

State machine: pending → running → collecting → analyzing → completed (| failed).
Chạy qua background worker `run_pending_investigations()` mỗi 30s.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime, timedelta

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_aes_gcm
from app.db import session as db_session
from app.db.models import (
    DfirInvestigation,
    DfirInvestigationMessage,
    LlmConfig,
    Machine,
    VelociraptorArtifact,
    VelociraptorConfig,
    VelociraptorLink,
)
from app.services.llm import (
    LlmAuthError,
    LlmClient,
    LlmError,
    LlmMessage,
    LlmRateLimitError,
    LlmTimeoutError,
)
from app.services.llm_prompts import (
    build_chat_user_prompt,
    build_dfir_system_prompt,
    build_investigation_user_prompt,
)

logger = logging.getLogger("llm.dfir")


class ExternalInvestigationNotFound(LlmError):
    """Investigation external không tồn tại."""


async def _load_custom_artifact_refs(db: AsyncSession) -> list[dict]:
    """Catalog artifact Custom.* (CLIENT, enabled) cho DeepAgent request payload.

    Description parse từ YAML đã lưu, cắt 300 ký tự — đúng hợp đồng
    CustomArtifactRef của DeepAgent. Tối đa 20 artifact.
    """
    rows = (
        (
            await db.execute(
                select(VelociraptorArtifact)
                .where(VelociraptorArtifact.enabled.is_(True))
                .where(VelociraptorArtifact.artifact_type == "CLIENT")
                .order_by(VelociraptorArtifact.name)
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    refs: list[dict] = []
    for row in rows:
        description = ""
        try:
            doc = yaml.safe_load(row.definition_yaml)
            if isinstance(doc, dict):
                description = str(doc.get("description") or "")[:300]
        except yaml.YAMLError:
            description = ""
        refs.append({"name": row.name, "description": description})
    return refs


class ExternalCallbackConflict(LlmError):
    """Callback không thuộc job hiện tại hoặc bị lặp với idempotency key khác."""


# ── DeepAgent capacity queue ─────────────────────────────────────


async def claim_deepagent_dispatches(
    db: AsyncSession, capacity: int
) -> list[DfirInvestigation]:
    """Chọn và lock các DeepAgent rows pending tối đa bằng capacity còn trống.

    FIFO: rows có created_at nhỏ nhất (ASC) được ưu tiên.
    Chỉ chọn rows có external_orchestrator='deepagent' và status='pending'.
    Active slots = rows đang analyzing (chiếm capacity).

    Args:
        db: AsyncSession hiện tại
        capacity: Tổng số slot có thể chiếm (1..3)

    Returns:
        Danh sách DfirInvestigation đã được claim (external_job_id đã set)
    """
    if capacity <= 0:
        return []

    # Đếm active DeepAgent slots (đang analyzing)
    active_count_result = await db.execute(
        select(DfirInvestigation.id)
        .where(
            DfirInvestigation.external_orchestrator == "deepagent",
            DfirInvestigation.status == "analyzing",
        )
    )
    active_ids = list(active_count_result.scalars().all())
    active_count = len(active_ids)

    # Tính số slot còn trống
    available = max(capacity - active_count, 0)
    if available == 0:
        return []

    # Lock và chọn N pending rows cũ nhất (FIFO)
    stmt = (
        select(DfirInvestigation)
        .where(
            DfirInvestigation.external_orchestrator == "deepagent",
            DfirInvestigation.status == "pending",
        )
        .order_by(DfirInvestigation.created_at.asc())
        .limit(available)
        .with_for_update(skip_locked=True)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    # Reserve mỗi row bằng deterministic job ID
    for row in rows:
        row.external_job_id = f"deepagent-{row.id}"

    await db.commit()
    return rows


# ── Alert notification (alert engine) ─────────────────────────────


async def _notify_investigation_result(
    db: AsyncSession,
    *,
    investigation_id,
    machine_id,
    status: str,  # "completed" | "failed"
    severity: str | None = None,
    findings_count: int | None = None,
    llm_model: str | None = None,
    error: str | None = None,
) -> None:
    """Gọi alert_engine.trigger_alert — recipients = Org Admin của máy + Super Admin.

    Best-effort: lỗi chỉ log, không làm chết pipeline investigation.
    """
    from app.db.models import Machine as _M
    from app.services.alert_engine import trigger_alert

    machine = await db.get(_M, machine_id)
    org_id = machine.org_id if machine else None

    context = {
        "hostname": machine.hostname if machine else None,
        "investigation_id": str(investigation_id),
    }
    if status == "completed":
        context.update({
            "findings_count": findings_count or 0,
            "severity": severity or "info",
            "llm_model": llm_model or "—",
        })
    else:
        context["error"] = (error or "")[:300]

    try:
        await trigger_alert(
            db,
            template_code=(
                "investigation_completed" if status == "completed"
                else "investigation_failed"
            ),
            org_id=org_id,
            machine_id=machine_id,
            context=context,
        )
    except Exception as e:  # noqa: BLE001 — không làm chết pipeline investigation
        logger.warning("notify investigation %s failed: %s", status, e)


# ── Helpers ──────────────────────────────────────────────────────


async def _load_llm_config(db: AsyncSession) -> LlmConfig | None:
    cfg = (
        await db.execute(select(LlmConfig).where(LlmConfig.id == 1))
    ).scalar_one_or_none()
    return cfg


async def _is_llm_enabled(db: AsyncSession) -> bool:
    cfg = await _load_llm_config(db)
    return bool(cfg and cfg.enabled and cfg.base_url and cfg.model)


def _decrypt_api_key(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        return decrypt_aes_gcm(encrypted)
    except Exception as e:  # noqa: BLE001
        logger.warning("Giải mã LLM api_key thất bại: %s", e)
        return None


# ── Public: enqueue investigation ────────────────────────────────


async def create_investigation(
    db: AsyncSession,
    *,
    machine_id: str,
    artifacts: list[str] | None,
    custom_instructions: str | None,
    requested_by: str,
    use_external_orchestrator: bool | None = None,
) -> DfirInvestigation:
    """Tạo investigation mới (status=pending).

    Nếu `use_external_orchestrator=True` (hoặc LlmConfig.llm_external_orchestrator
    được set), orchestrator sẽ chỉ thu thập data rồi đợi external service (Hermes)
    POST kết quả về — KHÔNG gọi LLM local.
    """
    if not await _is_llm_enabled(db):
        raise LlmError("LLM chưa được cấu hình hoặc chưa bật.")

    link = (
        await db.execute(
            select(VelociraptorLink).where(VelociraptorLink.machine_id == machine_id)
        )
    ).scalar_one_or_none()
    if not link or not link.client_id:
        raise LlmError(
            "Máy chưa được link với Velociraptor (chưa có client_id). "
            "Chạy POST /api/admin/velociraptor/sync hoặc đợi sync 5 phút/lần."
        )

    if not artifacts:
        artifacts = list(settings.llm_default_artifacts)

    # Quyết định external mode
    # 1) Nếu admin truyền use_external_orchestrator=True/False → dùng giá trị đó (override)
    # 2) Ngược lại → đọc từ LlmConfig.external_orchestrator (DB) hoặc env settings.llm_external_orchestrator
    cfg = await _load_llm_config(db)
    configured_external = (
        getattr(cfg, "external_orchestrator", "") if cfg else ""
    ) or settings.llm_external_orchestrator
    if use_external_orchestrator is True:
        ext_orch = configured_external or "hermes"
    elif use_external_orchestrator is False:
        ext_orch = None
    else:
        ext_orch = configured_external or None
    if ext_orch not in (None, "hermes", "deepagent"):
        raise LlmError("external_orchestrator chỉ hỗ trợ hermes hoặc deepagent")

    inv = DfirInvestigation(
        machine_id=machine_id,
        velociraptor_client_id=link.client_id,
        artifacts=artifacts,
        status="pending",
        custom_instructions=custom_instructions,
        external_orchestrator=ext_orch,
        requested_by=requested_by,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    logger.info(
        "Investigation %s created (machine=%s, client_id=%s, artifacts=%d, external=%s)",
        inv.id,
        machine_id,
        link.client_id,
        len(artifacts),
        ext_orch,
    )
    return _inv_to_dict(inv)


# ── Public: background worker entry point ────────────────────────


async def run_pending_investigations() -> dict:
    """Gọi từ monitor loop mỗi LLM_INVESTIGATION_INTERVAL_SECONDS."""
    started = time.time()
    processed: list[str] = []
    errors: list[str] = []

    async with db_session.AsyncSessionLocal() as db:
        if not await _is_llm_enabled(db):
            return {"skipped": True, "reason": "llm_disabled"}

        # ── B-2 fix: use capacity-bounded FIFO claim for DeepAgent rows ──────
        # Reconcile active jobs before counting their slots. A DeepAgent process
        # restart loses its in-memory registry; a 404 safely returns that row to
        # pending so this same tick can reclaim it in FIFO order.
        active_deepagent_rows = (
            await db.execute(
                select(DfirInvestigation)
                .where(
                    DfirInvestigation.external_orchestrator == "deepagent",
                    DfirInvestigation.status == "analyzing",
                )
                .order_by(DfirInvestigation.created_at.asc())
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for inv in active_deepagent_rows:
            await _state_check_deepagent_job(db, inv)

        # Then atomically claim up to available slots using the claim helper.
        # Non-DeepAgent rows (local LLM) are processed unchanged.
        active_deepagent_claimed = await claim_deepagent_dispatches(
            db, capacity=settings.deepagent_max_concurrent_jobs
        )
        # Process claimed DeepAgent rows first (they are already locked to analyzing)
        for inv in active_deepagent_claimed:
            try:
                await _state_dispatch_deepagent(db, inv)
                processed.append(str(inv.id))
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
                errors.append(f"{inv.id}: {err}")
                logger.exception("Investigation %s failed", inv.id)
                inv.status = "failed"
                inv.error = err[:2000]
                inv.completed_at = datetime.now(UTC)
                await db.commit()

        # ── Process non-DeepAgent rows (local LLM) unchanged ─────────────────
        non_deepagent = (
            await db.execute(
                select(DfirInvestigation)
                .where(
                    DfirInvestigation.status.in_(
                        ["pending", "running", "collecting", "analyzing"]
                    ),
                    DfirInvestigation.external_orchestrator != "deepagent",
                )
                .order_by(DfirInvestigation.created_at)
                .limit(5)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for inv in non_deepagent:
            try:
                await _process_one(db, inv)
                processed.append(str(inv.id))
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
                errors.append(f"{inv.id}: {err}")
                logger.exception("Investigation %s failed", inv.id)
                inv.status = "failed"
                inv.error = err[:2000]
                inv.completed_at = datetime.now(UTC)
                await db.commit()

    elapsed_ms = int((time.time() - started) * 1000)
    if processed or errors:
        logger.info(
            "LLM-DFIR worker: %d processed, %d errors, %dms",
            len(processed),
            len(errors),
            elapsed_ms,
        )
    return {"processed": len(processed), "errors": len(errors), "elapsed_ms": elapsed_ms}


# ── Private: process 1 investigation theo state ──────────────────


async def _process_one(db: AsyncSession, inv: DfirInvestigation) -> None:
    # DeepAgent tự truy vấn Velociraptor qua MCP. Không collect artifact ở
    # backend trước, để graph điều phối việc thu thập theo dấu hiệu nghi ngờ.
    if inv.external_orchestrator == "deepagent":
        if inv.status == "pending":
            await _state_dispatch_deepagent(db, inv)
        elif inv.status == "analyzing":
            await _state_check_deepagent_job(db, inv)
        return
    if inv.status == "pending":
        await _state_start(db, inv)
    elif inv.status == "running":
        await _state_poll_collect(db, inv)
    elif inv.status == "collecting":
        await _state_poll_collect(db, inv)  # tiếp tục poll
    elif inv.status == "analyzing":
        await _state_analyze(db, inv)


async def _state_check_deepagent_job(db: AsyncSession, inv: DfirInvestigation) -> None:
    """Requeue a job lost by a DeepAgent process restart.

    The backend owns the investigation state, while DeepAgent keeps its short-lived
    job registry in memory. A missing job is therefore safe to dispatch again;
    network errors leave the current investigation untouched for a later poll.
    """
    if not inv.external_job_id:
        dispatch_started_at = inv.started_at
        timeout_seconds = max(settings.deepagent_request_timeout_seconds * 2, 60)
        if (
            inv.hermes_status == "dispatching"
            and dispatch_started_at
            and (datetime.now(UTC) - dispatch_started_at).total_seconds() > timeout_seconds
        ):
            inv.status = "pending"
            inv.hermes_status = "recovery_required"
            inv.hermes_response = {"reason": "deepagent_dispatch_interrupted"}
            await db.commit()
            logger.warning("DeepAgent dispatch interrupted for investigation %s", inv.id)
        return
    try:
        async with httpx.AsyncClient(timeout=settings.deepagent_request_timeout_seconds) as client:
            response = await client.get(
                f"{settings.deepagent_url.rstrip('/')}/v1/jobs/{inv.external_job_id}",
                headers={"Authorization": f"Bearer {settings.deepagent_api_key}"},
            )
    except Exception as exc:  # noqa: BLE001 - retry on the next worker tick
        logger.warning("DeepAgent job check failed for %s: %s", inv.id, exc)
        return
    if response.status_code != 404:
        return

    inv.status = "pending"
    inv.external_job_id = None
    inv.hermes_status = "recovery_required"
    inv.hermes_response = {"reason": "deepagent_job_missing_after_restart"}
    await db.commit()
    logger.warning("DeepAgent job missing for investigation %s; queued for redispatch", inv.id)


async def _state_dispatch_deepagent(db: AsyncSession, inv: DfirInvestigation) -> None:
    """Dispatch idempotent một investigation sang DeepAgent LangGraph."""
    if not inv.velociraptor_client_id:
        raise LlmError("Investigation thiếu Velociraptor client_id")

    machine = (
        await db.execute(select(Machine).where(Machine.id == inv.machine_id))
    ).scalar_one_or_none()
    hostname = machine.hostname if machine and machine.hostname else str(inv.machine_id)
    llm_cfg = await _load_llm_config(db)
    if not llm_cfg or not llm_cfg.enabled or not llm_cfg.base_url or not llm_cfg.model:
        raise LlmError("LLM runtime chưa được cấu hình")
    api_key = _decrypt_api_key(llm_cfg.api_key_encrypted)
    if not api_key:
        raise LlmError("LLM runtime thiếu API key")
    # DeepAgent là service Compose nội bộ, luôn được dùng khi runtime được cấu hình.
    deepagent_enabled = settings.deepagent_enabled
    deepagent_url = settings.deepagent_url
    deepagent_token = settings.deepagent_api_key
    if not deepagent_enabled or not deepagent_token:
        raise LlmError("DeepAgent chưa được bật hoặc chưa có service token")
    velo_cfg = (await db.execute(select(VelociraptorConfig).where(VelociraptorConfig.id == 1))).scalar_one_or_none()
    if not velo_cfg or not velo_cfg.client_config_encrypted:
        raise LlmError("Chưa upload api_client.yaml cho Velociraptor")
    api_client_yaml = decrypt_aes_gcm(velo_cfg.client_config_encrypted)
    now = datetime.now(UTC)
    time_from = now - timedelta(hours=settings.deepagent_default_lookback_hours)
    expected_job_id = f"deepagent-{inv.id}"
    request_body = {
        "schema_version": "dfir.deepagent.request/1.1",
        "investigation_id": str(inv.id),
        "client_id": inv.velociraptor_client_id,
        "hostname": hostname,
        "time_range": {"from": time_from.isoformat(), "to": now.isoformat()},
        "suspicious_activity": inv.custom_instructions
        or "Điều tra chủ động: đánh giá tiến trình, mạng, persistence, event log và PowerShell; không mặc định máy đã bị xâm nhập.",
        "llm_runtime": {"base_url": llm_cfg.base_url, "api_key": api_key, "model": llm_cfg.model, "temperature": float(llm_cfg.temperature), "timeout_seconds": llm_cfg.request_timeout, "max_tokens": llm_cfg.max_tokens, "system_prompt": llm_cfg.system_prompt},
        "velociraptor_api_client_yaml": api_client_yaml,
        "custom_artifacts": await _load_custom_artifact_refs(db),
    }
    inv.status = "analyzing"
    inv.external_job_id = expected_job_id
    inv.hermes_status = "dispatching"
    inv.started_at = now
    await db.commit()
    try:
        async with httpx.AsyncClient(timeout=settings.deepagent_request_timeout_seconds) as client:
            response = await client.post(
                f"{deepagent_url.rstrip('/')}/v1/investigations",
                headers={"Authorization": f"Bearer {deepagent_token}"},
                json=request_body,
            )
        response.raise_for_status()
        body = response.json()
        if body.get("job_id") != expected_job_id:
            raise LlmError("DeepAgent trả về job ID không khớp investigation")
        inv.external_job_id = expected_job_id
        inv.hermes_status = "dispatched"
        inv.hermes_response = {
            "job_id": inv.external_job_id,
            "status": body.get("status"),
        }
        await db.commit()
        logger.info("Investigation %s dispatched to DeepAgent job=%s", inv.id, inv.external_job_id)
    except Exception as exc:
        inv.status = "failed"
        inv.hermes_status = "dispatch_failed"
        inv.error = f"DeepAgent dispatch: {type(exc).__name__}: {exc}"[:2000]
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        raise


async def _state_start(db: AsyncSession, inv: DfirInvestigation) -> None:
    """pending → running → collecting.

    Mỗi artifact collect riêng 1 flow. Nếu 1 artifact fail → flow đó có
    `error`, các flow khác vẫn tiếp tục. Chuyển sang `collecting` khi tất
    cả flow đã trigger (thành công hoặc lỗi) — orchestrator sẽ poll kết quả.
    """
    inv.status = "running"
    inv.started_at = datetime.now(UTC)
    await db.commit()

    from app.api.routes.velociraptor import _build_velociraptor_client
    flows: list[dict] = []
    try:
        velo_cfg = await _build_velociraptor_client(db)
        if velo_cfg is None:
            raise RuntimeError("Velociraptor chưa cấu hình")
        velo = velo_cfg[0]
        async with velo:
            for art in inv.artifacts:
                try:
                    # collect_artifact signature: (client_id, artifacts: list[str], env=None) -> flow_id
                    flow_id = await velo.collect_artifact(
                        client_id=inv.velociraptor_client_id,
                        artifacts=[art],
                    )
                    flows.append({"artifact": art, "flow_id": flow_id, "raw": {"flow_id": flow_id}})
                    logger.info("Investigation %s: triggered %s → flow_id=%s", inv.id, art, flow_id)
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {e}"
                    flows.append({"artifact": art, "error": err})
                    logger.warning("Investigation %s: collect %s failed: %s", inv.id, art, err)
    except Exception as e:  # noqa: BLE001
        # Không tạo được VelociraptorClient (sai config, mất kết nối…) → fail toàn bộ
        err = f"{type(e).__name__}: {e}"
        inv.status = "failed"
        inv.error = f"Velociraptor: {err}"[:2000]
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        raise

    inv.raw_artifacts = {"flows": flows}
    # flow_id column lưu flow đầu tiên (tham khảo) — UI dùng raw_artifacts.flows
    inv.flow_id = next((f.get("flow_id") for f in flows if f.get("flow_id")), None)
    inv.status = "collecting"
    await db.commit()
    logger.info("Investigation %s: triggered %d flows → collecting", inv.id, len(flows))


async def _state_poll_collect(db: AsyncSession, inv: DfirInvestigation) -> None:
    """collecting: poll Velociraptor chờ flow xong → analyzing.

    Mỗi flow: gọi `get_flow_status` — nếu còn RUNNING thì đợi lần sau.
    Khi FINISHED/ERROR: gọi `get_flow_results` lưu vào flow.results. Có lỗi
    Velociraptor (mạng, 5xx...) thì KHÔNG fail ngay, để lần poll sau retry.
    """
    if inv.started_at:
        elapsed = (datetime.now(UTC) - inv.started_at).total_seconds()
        if elapsed > settings.llm_collect_max_wait_seconds:
            inv.status = "failed"
            inv.error = f"Timeout sau {elapsed:.0f}s chờ Velociraptor"
            inv.completed_at = datetime.now(UTC)
            await db.commit()
            return

    flows = (inv.raw_artifacts or {}).get("flows") or []
    if not flows:
        inv.status = "failed"
        inv.error = "Không có flow nào để poll"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        return

    all_done = True
    from app.api.routes.velociraptor import _build_velociraptor_client
    try:
        velo_cfg = await _build_velociraptor_client(db)
        if velo_cfg is None:
            raise RuntimeError("Velociraptor chưa cấu hình")
        velo = velo_cfg[0]
        async with velo:
            for flow in flows:
                flow_id = flow.get("flow_id")
                art_name = flow.get("artifact")
                # Bỏ qua flow đã cache, không có flow_id, hoặc đã lỗi từ _state_start
                if not flow_id or flow.get("results_cached") or flow.get("error"):
                    continue
                try:
                    status = await velo.get_flow_status(inv.velociraptor_client_id, flow_id)
                    if status.get("is_running"):
                        all_done = False
                        continue
                    # Flow kết thúc (FINISHED hoặc ERROR) → lấy results
                    if status.get("error") and not flow.get("results"):
                        flow["error"] = status["error"]
                    try:
                        results = await velo.get_flow_results(
                            inv.velociraptor_client_id,
                            flow_id,
                            artifact=art_name,
                            max_rows=5000,
                        )
                        flow["results"] = results
                    except Exception as e:  # noqa: BLE001
                        # Không lấy được rows nhưng flow đã kết thúc → vẫn cache
                        flow["results_error"] = f"{type(e).__name__}: {e}"
                    flow["results_cached"] = True
                except Exception as e:  # noqa: BLE001
                    # Lỗi mạng / API tạm thời → retry lần sau, KHÔNG fail
                    logger.warning(
                        "Investigation %s: poll flow %s error (sẽ retry): %s",
                        inv.id, flow_id, e,
                    )
                    all_done = False
    except Exception as e:  # noqa: BLE001
        # Không tạo được VelociraptorClient → fail cả investigation
        inv.status = "failed"
        inv.error = f"Velociraptor poll: {type(e).__name__}: {e}"[:2000]
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        raise

    await db.commit()

    if all_done:
        # Nếu external_orchestrator được set → KHÔNG gọi LLM local.
        # Đặt status=analyzing + flag external_pending=True; đợi external push kết quả.
        # Timeout ở đây cũng tương tự local: vẫn áp dụng llm_collect_max_wait_seconds.
        if inv.external_orchestrator:
            inv.status = "analyzing"
            inv.hermes_status = "awaiting_external"
            await db.commit()
            logger.info(
                "Investigation %s: all flows done → analyzing (external=%s, waiting for push)",
                inv.id, inv.external_orchestrator,
            )
        else:
            inv.status = "analyzing"
            await db.commit()
            logger.info("Investigation %s: all flows done → analyzing", inv.id)


async def _state_analyze(db: AsyncSession, inv: DfirInvestigation) -> None:
    """analyzing: gọi LLM → completed."""
    if inv.external_orchestrator:
        # Kết quả external chỉ được chấp nhận qua callback đã xác thực.
        return
    cfg = await _load_llm_config(db)
    if not cfg:
        inv.status = "failed"
        inv.error = "LLM config bị xoá giữa chừng"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        return

    # Bundle artifacts data
    artifacts_data: dict[str, list[dict]] = {}
    flows = (inv.raw_artifacts or {}).get("flows") or []
    for flow in flows:
        art = flow.get("artifact", "Unknown")
        results = flow.get("results")
        if isinstance(results, list):
            artifacts_data[art] = results
        elif isinstance(results, dict):
            cols = list(results.keys())
            n = max((len(v) for v in results.values() if isinstance(v, list)), default=0)
            rows: list[dict] = []
            for i in range(n):
                row = {
                    c: results[c][i] if i < len(results.get(c, [])) else None
                    for c in cols
                }
                rows.append(row)
            artifacts_data[art] = rows
        elif flow.get("error"):
            artifacts_data[art] = [{"error": flow["error"]}]

    # Lấy OS info
    os_info: dict = {}
    if inv.velociraptor_client_id:
        link = (
            await db.execute(
                select(VelociraptorLink).where(
                    VelociraptorLink.client_id == inv.velociraptor_client_id
                )
            )
        ).scalar_one_or_none()
        if link and link.os_info:
            os_info = link.os_info

    machine = (
        await db.execute(select(Machine).where(Machine.id == inv.machine_id))
    ).scalar_one_or_none()
    hostname = (
        (machine.hostname if machine else None)
        or (os_info.get("hostname") if os_info else None)
        or "unknown"
    )

    user_prompt = build_investigation_user_prompt(
        hostname=hostname,
        os_info=os_info,
        artifacts_data=artifacts_data,
        custom_instructions=inv.custom_instructions,
        max_chars=cfg.max_context_chars,
    )

    system_prompt = cfg.system_prompt or build_dfir_system_prompt()
    messages = [
        LlmMessage("system", system_prompt),
        LlmMessage("user", user_prompt),
    ]

    api_key = _decrypt_api_key(cfg.api_key_encrypted)
    inv.llm_provider = cfg.provider
    inv.llm_model = cfg.model
    await db.commit()

    try:
        async with LlmClient(
            base_url=cfg.base_url,
            api_key=api_key,
            model=cfg.model,
            fallback_model=cfg.fallback_model,
            timeout=cfg.request_timeout,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        ) as llm:
            resp = await llm.chat(messages)

        inv.report_markdown = resp.content
        inv.input_tokens = resp.input_tokens
        inv.output_tokens = resp.output_tokens
        inv.estimated_cost_usd = resp.estimated_cost_usd
        inv.severity = _parse_severity(resp.content)
        inv.findings_count = _parse_findings_count(resp.content)

        db.add(DfirInvestigationMessage(
            investigation_id=inv.id, role="system", content=system_prompt,
        ))
        db.add(DfirInvestigationMessage(
            investigation_id=inv.id, role="user", content=user_prompt,
            tokens=resp.input_tokens,
        ))
        db.add(DfirInvestigationMessage(
            investigation_id=inv.id, role="assistant", content=resp.content,
            tokens=resp.output_tokens,
        ))

        cfg.tokens_used_today = (cfg.tokens_used_today or 0) + resp.total_tokens

        inv.status = "completed"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        logger.info(
            "Investigation %s completed: severity=%s findings=%d tokens=%d",
            inv.id, inv.severity, inv.findings_count or 0, resp.total_tokens,
        )

        # Gửi notification qua alert engine (Org Admin + Super Admin)
        await _notify_investigation_result(
            db, investigation_id=inv.id, machine_id=inv.machine_id,
            status="completed", severity=inv.severity,
            findings_count=inv.findings_count, llm_model=inv.llm_model,
        )

    except (LlmAuthError, LlmTimeoutError, LlmRateLimitError, LlmError) as e:
        inv.status = "failed"
        inv.error = f"LLM: {e}"[:2000]
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        logger.warning("Investigation %s LLM failed: %s", inv.id, e)
        # Gửi notification failed
        await _notify_investigation_result(
            db, investigation_id=inv.id, machine_id=inv.machine_id,
            status="failed", error=str(e),
        )


# ── Public: chat Q&A ─────────────────────────────────────────────


async def chat_with_llm(
    db: AsyncSession, *, investigation_id: str, user_message: str
) -> dict:
    """Hỏi tiếp về 1 cuộc điều tra (sau khi đã completed)."""
    inv = (
        await db.execute(
            select(DfirInvestigation).where(DfirInvestigation.id == investigation_id)
        )
    ).scalar_one_or_none()
    if not inv:
        raise LlmError("Investigation không tồn tại")
    if inv.status != "completed":
        raise LlmError(f"Investigation chưa hoàn thành (status={inv.status})")
    if not await _is_llm_enabled(db):
        raise LlmError("LLM chưa được cấu hình")

    msgs = (
        await db.execute(
            select(DfirInvestigationMessage)
            .where(DfirInvestigationMessage.investigation_id == investigation_id)
            .order_by(DfirInvestigationMessage.created_at)
        )
    ).scalars().all()

    llm_messages = [LlmMessage(m.role, m.content) for m in msgs]
    llm_messages.append(LlmMessage("user", build_chat_user_prompt(user_message)))

    cfg = await _load_llm_config(db)
    api_key = _decrypt_api_key(cfg.api_key_encrypted)

    async with LlmClient(
        base_url=cfg.base_url,
        api_key=api_key,
        model=cfg.model,
        fallback_model=cfg.fallback_model,
        timeout=cfg.request_timeout,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    ) as llm:
        resp = await llm.chat(llm_messages)

    db.add(DfirInvestigationMessage(
        investigation_id=inv.id, role="user", content=user_message, tokens=resp.input_tokens,
    ))
    db.add(DfirInvestigationMessage(
        investigation_id=inv.id, role="assistant", content=resp.content,
        tokens=resp.output_tokens,
    ))
    cfg.tokens_used_today = (cfg.tokens_used_today or 0) + resp.total_tokens
    await db.commit()

    return {
        "response": resp.content,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "model": resp.model,
    }


# ── Helpers: parse response ──────────────────────────────────────


def _parse_severity(markdown: str) -> str:
    """Trích severity từ response markdown."""
    m = re.search(
        r"(?:Mức độ nghiêm trọng|severity)[*:\s]+(\w+)", markdown, re.IGNORECASE
    )
    if m:
        sev = m.group(1).lower()
        if sev in ("critical", "high", "medium", "low", "info"):
            return sev
    return "info"


def _parse_findings_count(markdown: str) -> int:
    """Đếm số phát hiện."""
    m = re.search(
        r"(?:Số phát hiện|findings)[*:\s]+(\d+)", markdown, re.IGNORECASE
    )
    if m:
        return int(m.group(1))
    return len(re.findall(r"^###\s+2\.\d+", markdown, re.MULTILINE))


# ── External orchestration (Hermes push kết quả) ───────────────


async def list_pending_for_external(
    db: AsyncSession,
    *,
    limit: int = 10,
) -> list[DfirInvestigation]:
    """Investigation đang đợi external service (Hermes) xử lý.

    Lấy các row có status=analyzing + external_orchestrator=set, sắp xếp
    theo created_at asc (FIFO). External service sẽ poll endpoint này.
    """
    reclaim_before = datetime.now(UTC) - timedelta(minutes=5)
    stmt = (
        select(DfirInvestigation)
        .where(
            DfirInvestigation.status == "analyzing",
            DfirInvestigation.external_orchestrator == "hermes",
            (DfirInvestigation.external_polled_at.is_(None))
            | (DfirInvestigation.external_polled_at < reclaim_before),
        )
        .order_by(DfirInvestigation.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if rows:
        now = datetime.now(UTC)
        for inv in rows:
            inv.external_polled_at = now
            inv.hermes_status = "claimed"
        await db.commit()
    return rows


async def mark_external_polled(
    db: AsyncSession, inv: DfirInvestigation
) -> None:
    """Update lần cuối external service poll investigation này."""
    inv.external_polled_at = datetime.now(UTC)
    inv.hermes_status = "claimed"
    await db.commit()


async def submit_external_result(
    db: AsyncSession,
    *,
    investigation_id: str,
    api_key_id: str | None,
    report_markdown: str | None,
    severity: str = "info",
    findings_count: int | None = None,
    findings: list | None = None,
    iocs: list | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
    error: str | None = None,
    external_job_id: str | None = None,
    raw_response: dict | None = None,
    idempotency_key: str | None = None,
) -> DfirInvestigation:
    """External service (Hermes) gọi endpoint này để submit kết quả.

    Flow:
      1. Lookup investigation (phải ở status=analyzing + external_orchestrator set)
      2. Nếu `error` → set status=failed, lưu error
      3. Ngược lại: lưu report + findings + iocs → status=completed
      4. Trigger notification tới admin yêu cầu + super admins
      5. Update daily token count nếu có

    Idempotency: nếu investigation đã completed/failed → trả về row hiện tại (no-op).
    """
    inv = (
        await db.execute(
            select(DfirInvestigation)
            .where(DfirInvestigation.id == investigation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if not inv:
        raise ExternalInvestigationNotFound(
            f"Investigation {investigation_id} không tồn tại"
        )
    if not inv.external_orchestrator:
        raise ExternalCallbackConflict(
            f"Investigation {investigation_id} không dùng external orchestrator "
            f"(external_orchestrator={inv.external_orchestrator})"
        )
    if not idempotency_key:
        raise ExternalCallbackConflict("Thiếu idempotency key cho external callback")
    if inv.external_orchestrator == "deepagent" and not inv.external_job_id:
        raise ExternalCallbackConflict(
            f"Investigation {inv.id} chưa được bind với DeepAgent job"
        )
    if inv.status in ("completed", "failed"):
        if (
            not inv.external_callback_idempotency_key
            or idempotency_key != inv.external_callback_idempotency_key
        ):
            raise ExternalCallbackConflict(
                f"Investigation {inv.id} đã nhận callback với idempotency key khác"
            )
        logger.info(
            "submit_external_result: investigation %s đã ở status=%s — idempotent no-op",
            inv.id, inv.status,
        )
        snapshot = _inv_to_dict(inv)
        await db.commit()  # đóng session sạch
        return snapshot
    if inv.external_job_id and external_job_id != inv.external_job_id:
        raise ExternalCallbackConflict(
            f"external_job_id không khớp với job đã dispatch cho investigation {inv.id}"
        )
    if inv.status != "analyzing":
        raise ExternalCallbackConflict(
            f"Investigation {inv.id} chưa sẵn sàng nhận callback (status={inv.status})"
        )

    # Lưu kết quả
    now = datetime.now(UTC)
    inv.callback_received_at = now

    if error:
        inv.status = "failed"
        inv.error = f"External ({inv.external_orchestrator}): {error}"[:2000]
        inv.completed_at = now
        inv.hermes_status = "failed"
        inv.hermes_response = raw_response
        if external_job_id:
            inv.external_job_id = external_job_id
        inv.external_callback_idempotency_key = idempotency_key
        snapshot = _inv_to_dict(inv)
        await db.commit()
        # Notify failed
        await _notify_investigation_result(
            db, investigation_id=snapshot["id"], machine_id=snapshot["machine_id"],
            status="failed", error=error,
        )
        return snapshot

    # Success path
    sev = (severity or "info").lower()
    if sev not in ("critical", "high", "medium", "low", "info"):
        sev = "info"
    inv.severity = sev
    inv.findings = findings or []
    inv.iocs = iocs or []
    inv.findings_count = findings_count if findings_count is not None else len(inv.findings)
    inv.report_markdown = report_markdown
    inv.llm_provider = llm_provider or inv.external_orchestrator
    inv.llm_model = llm_model
    inv.input_tokens = input_tokens
    inv.output_tokens = output_tokens
    inv.estimated_cost_usd = estimated_cost_usd
    inv.status = "completed"
    inv.completed_at = now
    inv.hermes_status = "completed"
    inv.hermes_response = raw_response
    if external_job_id:
        inv.external_job_id = external_job_id
    inv.external_callback_idempotency_key = idempotency_key

    # Cộng token vào daily budget nếu có
    if (input_tokens or 0) + (output_tokens or 0) > 0:
        cfg = await _load_llm_config(db)
        if cfg:
            cfg.tokens_used_today = (cfg.tokens_used_today or 0) + (input_tokens or 0) + (output_tokens or 0)

    # Snapshot trước commit; refresh ở đây sẽ làm mất các thay đổi chưa commit.
    snapshot = _inv_to_dict(inv)
    await db.commit()
    logger.info(
        "Investigation %s: external result received (severity=%s findings=%d tokens=%d)",
        snapshot["id"], snapshot["severity"], snapshot["findings_count"] or 0,
        (input_tokens or 0) + (output_tokens or 0),
    )

    # Gửi notification (alert engine — Org Admin + Super Admin)
    await _notify_investigation_result(
        db, investigation_id=snapshot["id"], machine_id=snapshot["machine_id"],
        status="completed", severity=snapshot.get("severity"),
        findings_count=snapshot.get("findings_count"),
        llm_model=snapshot.get("llm_model"),
    )

    return snapshot


def _inv_to_dict(inv) -> dict:
    """Convert DfirInvestigation SQLAlchemy object → plain dict.
    Tránh detached instance / lazy-load ngoài async context khi return từ service.
    """
    return {
        "id": inv.id,
        "status": inv.status,
        "severity": inv.severity,
        "findings_count": inv.findings_count,
        "findings": inv.findings,
        "iocs": inv.iocs,
        "report_markdown": inv.report_markdown,
        "llm_provider": inv.llm_provider,
        "llm_model": inv.llm_model,
        "input_tokens": inv.input_tokens,
        "output_tokens": inv.output_tokens,
        "estimated_cost_usd": float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
        "external_orchestrator": inv.external_orchestrator,
        "external_job_id": inv.external_job_id,
        "external_polled_at": inv.external_polled_at,
        "hermes_status": inv.hermes_status,
        "callback_received_at": inv.callback_received_at,
        "completed_at": inv.completed_at,
        "machine_id": inv.machine_id,
        "error": inv.error,
    }
