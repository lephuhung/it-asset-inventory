"""API endpoints cho LLM-DFIR:
  - /api/admin/llm-dfir/config (GET, PUT, POST test)
  - /api/admin/llm-dfir/investigations (GET list, POST create, DELETE)
  - /api/admin/llm-dfir/investigations/{id}/messages, /chat
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.core.audit import append_audit
from app.core.config import settings
from app.core.security import decrypt_aes_gcm, encrypt_aes_gcm
from app.db.models import (
    DfirInvestigation,
    DfirInvestigationMessage,
    LlmConfig,
    Machine,
    User,
    VelociraptorConfig,
)
from app.schemas import (
    DfirInvestigationChatIn,
    DfirInvestigationCreate,
    DfirInvestigationListOut,
    DfirInvestigationMessageOut,
    DfirInvestigationOut,
    DfirInvestigationStatsOut,
    LlmConfigOut,
    LlmConfigUpdate,
    LlmTestConnectionOut,
    LlmModelsOut,
    DeepAgentTestOut,
)
from app.services import dfir_investigation as inv_svc
from app.services.llm import LlmClient, LlmError, mask_api_key

logger = logging.getLogger("llm.dfir.api")

router = APIRouter(prefix="/api/admin/llm-dfir", tags=["llm-dfir"])


# ── Helpers ──────────────────────────────────────────────────────


async def _get_or_create_config(db: AsyncSession) -> LlmConfig:
    cfg = (
        await db.execute(select(LlmConfig).where(LlmConfig.id == 1))
    ).scalar_one_or_none()
    if cfg is None:
        cfg = LlmConfig(
            id=1,
            enabled=False,
            provider="ollama",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen2.5:14b-instruct-q4_K_M",
            deepagent_enabled=True,
            external_orchestrator="deepagent",
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


def _decrypt_for_display(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        return decrypt_aes_gcm(encrypted)
    except Exception:
        return None


def _config_to_out(
    cfg: LlmConfig, available_models: list[str] | None = None
) -> LlmConfigOut:
    return LlmConfigOut(
        enabled=cfg.enabled,
        provider=cfg.provider,
        base_url=cfg.base_url,
        api_key_masked=mask_api_key(_decrypt_for_display(cfg.api_key_encrypted)),
        model=cfg.model,
        fallback_model=cfg.fallback_model,
        system_prompt=cfg.system_prompt,
        max_tokens=cfg.max_tokens,
        temperature=float(cfg.temperature),
        request_timeout=cfg.request_timeout,
        max_context_chars=cfg.max_context_chars,
        allow_cloud=cfg.allow_cloud,
        external_orchestrator=cfg.external_orchestrator,
        deepagent_enabled=True,
        deepagent_url=cfg.deepagent_url,
        deepagent_service_token_set=bool(_decrypt_for_display(cfg.deepagent_service_token_encrypted)),
        daily_token_budget=cfg.daily_token_budget,
        tokens_used_today=cfg.tokens_used_today or 0,
        test_status=cfg.test_status,
        test_error=cfg.test_error,
        test_at=cfg.test_at,
        updated_at=cfg.updated_at,
        available_models=available_models or [],
    )


def _is_private_host(url: str) -> bool:
    """True nếu URL thuộc mạng nội bộ (không tính cloud)."""
    return any(
        marker in url
        for marker in ("127.0.0.1", "localhost", "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.30", "172.31", ".internal", ".local")
    )


def _inv_to_out(inv: DfirInvestigation, machine: Machine | None) -> DfirInvestigationOut:
    return DfirInvestigationOut(
        id=inv.id,
        machine_id=inv.machine_id,
        machine_hostname=machine.hostname if machine else None,
        status=inv.status,
        artifacts=inv.artifacts or [],
        llm_provider=inv.llm_provider,
        llm_model=inv.llm_model,
        severity=inv.severity,
        findings_count=inv.findings_count,
        findings=inv.findings,
        iocs=inv.iocs,
        input_tokens=inv.input_tokens,
        output_tokens=inv.output_tokens,
        estimated_cost_usd=float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
        error=inv.error,
        report_markdown=inv.report_markdown,
        custom_instructions=inv.custom_instructions,
        external_orchestrator=inv.external_orchestrator,
        external_job_id=inv.external_job_id,
        external_polled_at=inv.external_polled_at,
        hermes_status=inv.hermes_status,
        created_at=inv.created_at,
        started_at=inv.started_at,
        completed_at=inv.completed_at,
        callback_received_at=inv.callback_received_at,
        requested_by=inv.requested_by,
    )


# ── Config endpoints ─────────────────────────────────────────────


@router.get("/config", response_model=LlmConfigOut)
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    cfg = await _get_or_create_config(db)
    return _config_to_out(cfg)


@router.post("/config/models", response_model=LlmModelsOut)
async def list_llm_models(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    """Nạp model theo cấu hình LLM đã lưu, không nhận API key từ trình duyệt."""
    cfg = await _get_or_create_config(db)
    api_key = _decrypt_for_display(cfg.api_key_encrypted)
    try:
        async with LlmClient(cfg.base_url, api_key, cfg.model, timeout=15) as llm:
            return LlmModelsOut(models=await llm.list_models())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Không tải được danh sách model: {exc}") from exc


@router.put("/config", response_model=LlmConfigOut)
async def update_llm_config(
    body: LlmConfigUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    cfg = await _get_or_create_config(db)
    changes: dict = {}

    if body.enabled is not None:
        cfg.enabled = body.enabled
        changes["enabled"] = body.enabled
    if body.provider is not None:
        p = body.provider.strip().lower()
        if p not in ("ollama", "openai", "localai", "vllm", "custom", "qwen", "deepseek"):
            raise HTTPException(422, f"provider không hợp lệ: {p}")
        cfg.provider = p
        changes["provider"] = p
    if body.base_url is not None:
        url = body.base_url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "base_url phải bắt đầu bằng http:// hoặc https://")
        cfg.base_url = url
        changes["base_url"] = url
    if body.api_key is not None:
        if body.api_key == "":
            cfg.api_key_encrypted = None
            changes["api_key"] = "cleared"
        else:
            if not cfg.allow_cloud and not _is_private_host(cfg.base_url):
                raise HTTPException(
                    403,
                    "Không thể đặt API key cho endpoint public khi allow_cloud=false. "
                    "Bật allow_cloud=true trước hoặc dùng LLM nội bộ.",
                )
            cfg.api_key_encrypted = encrypt_aes_gcm(body.api_key.strip())
            changes["api_key"] = "set"
    if body.model is not None:
        if not body.model.strip():
            raise HTTPException(422, "model không được rỗng")
        cfg.model = body.model.strip()
        changes["model"] = cfg.model
    if body.fallback_model is not None:
        cfg.fallback_model = body.fallback_model.strip() or None
    if body.system_prompt is not None:
        cfg.system_prompt = body.system_prompt.strip() or None
    if body.max_tokens is not None:
        if not (64_000 <= body.max_tokens <= 128_000):
            raise HTTPException(422, "max_tokens phải trong [64000, 128000]")
        cfg.max_tokens = body.max_tokens
    if body.temperature is not None:
        if not (0.0 <= body.temperature <= 2.0):
            raise HTTPException(422, "temperature phải trong [0.0, 2.0]")
        cfg.temperature = body.temperature
    if body.request_timeout is not None:
        if not (10 <= body.request_timeout <= 600):
            raise HTTPException(422, "request_timeout phải trong [10, 600]")
        cfg.request_timeout = body.request_timeout
    if body.max_context_chars is not None:
        if not (1000 <= body.max_context_chars <= 1_000_000):
            raise HTTPException(422, "max_context_chars phải trong [1000, 1000000]")
        cfg.max_context_chars = body.max_context_chars
    if body.allow_cloud is not None:
        cfg.allow_cloud = body.allow_cloud
        changes["allow_cloud"] = body.allow_cloud
    if body.external_orchestrator is not None:
        ext = body.external_orchestrator.strip().lower()
        if ext not in ("", "hermes", "deepagent"):
            raise HTTPException(422, f"external_orchestrator không hợp lệ: {ext}")
        cfg.external_orchestrator = ext
        changes["external_orchestrator"] = ext
    if body.deepagent_enabled is not None:
        cfg.deepagent_enabled = body.deepagent_enabled
        changes["deepagent_enabled"] = body.deepagent_enabled
    if body.deepagent_url is not None:
        url = body.deepagent_url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(422, "deepagent_url phải bắt đầu bằng http:// hoặc https://")
        cfg.deepagent_url = url or None
        changes["deepagent_url"] = cfg.deepagent_url
    if body.deepagent_service_token is not None:
        if body.deepagent_service_token.strip():
            cfg.deepagent_service_token_encrypted = encrypt_aes_gcm(body.deepagent_service_token.strip())
            changes["deepagent_service_token"] = "set"
        else:
            cfg.deepagent_service_token_encrypted = None
            changes["deepagent_service_token"] = "cleared"
    if body.daily_token_budget is not None:
        cfg.daily_token_budget = body.daily_token_budget if body.daily_token_budget > 0 else None

    cfg.updated_at = datetime.now(UTC)
    cfg.updated_by = admin.id
    cfg.test_status = "untested"
    await db.commit()
    if changes:
        # encode changes vào target (append_audit không có field changes riêng)
        import json as _json
        target = f"llm_config:1:{_json.dumps(changes, ensure_ascii=False)[:200]}"
        await append_audit(
            db, action="llm.config.update", actor=str(admin.id), target=target,
        )
        await db.commit()
    return _config_to_out(cfg)


@router.post("/config/test", response_model=LlmTestConnectionOut)
async def test_llm_connection(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    cfg = await _get_or_create_config(db)
    if not cfg.base_url or not cfg.model:
        raise HTTPException(422, "Cần base_url + model trước khi test")
    api_key = _decrypt_for_display(cfg.api_key_encrypted)
    async with LlmClient(cfg.base_url, api_key, cfg.model, timeout=15) as llm:
        result = await llm.test_connection()

    cfg.test_status = "ok" if result["ok"] else "error"
    cfg.test_error = result.get("error")
    cfg.test_at = datetime.now(UTC)
    await db.commit()

    return LlmTestConnectionOut(
        ok=result["ok"],
        latency_ms=result["latency_ms"],
        models=result.get("models", []),
        error=result.get("error"),
    )


async def test_deepagent_mcp_for_yaml(api_client_yaml: str) -> DeepAgentTestOut:
    """Kiểm tra DeepAgent/MCP bằng YAML đã được giải mã ở server."""
    if not settings.deepagent_url:
        return DeepAgentTestOut(ok=False, error="DeepAgent Compose chưa có URL nội bộ")
    token = settings.deepagent_api_key
    if not token:
        return DeepAgentTestOut(ok=False, error="DeepAgent Compose chưa có service token")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            health = await client.get(f"{settings.deepagent_url.rstrip('/')}/health")
            health.raise_for_status()
            result = await client.post(
                f"{settings.deepagent_url.rstrip('/')}/v1/mcp/test",
                headers=headers,
                json={"velociraptor_api_client_yaml": api_client_yaml},
            )
            result.raise_for_status()
        payload = result.json()
        return DeepAgentTestOut(
            ok=bool(payload.get("ok")), service_ok=True, mcp_ok=bool(payload.get("ok")),
            tools=payload.get("tools") or [], client_count_sampled=payload.get("client_count_sampled"),
            error=payload.get("error"),
        )
    except httpx.HTTPError as exc:
        return DeepAgentTestOut(ok=False, error=f"DeepAgent không phản hồi: {exc}")


@router.post("/deepagent/test", response_model=DeepAgentTestOut)
async def test_deepagent_mcp(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    """Tương thích endpoint cũ; UI mới gọi kiểm tra này qua Velociraptor."""
    velo_cfg = (await db.execute(select(VelociraptorConfig).where(VelociraptorConfig.id == 1))).scalar_one_or_none()
    if not velo_cfg or not velo_cfg.client_config_encrypted:
        return DeepAgentTestOut(ok=False, error="Chưa upload api_client.yaml trong cấu hình Velociraptor")
    try:
        return await test_deepagent_mcp_for_yaml(decrypt_aes_gcm(velo_cfg.client_config_encrypted))
    except Exception:
        return DeepAgentTestOut(ok=False, error="Không thể đọc api_client.yaml đã lưu")


# ── Investigation endpoints ──────────────────────────────────────


@router.get("/investigations", response_model=DfirInvestigationListOut)
async def list_investigations(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
    machine_id: str | None = None,  # str để tránh 422; convert thủ công
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
):
    """Danh sách investigation có phân trang + filter.

    Query params:
      - machine_id: lọc theo máy (UUID)
      - status: lọc theo status
      - severity: lọc theo severity
      - page: trang (default 1)
      - limit: số items mỗi trang (default 20, max 100)

    Response: {items, total, page, limit, has_more}
    """
    from sqlalchemy import func as sa_func
    # Parse machine_id
    machine_uuid: uuid.UUID | None = None
    if machine_id:
        try:
            machine_uuid = uuid.UUID(machine_id)
        except (ValueError, TypeError):
            raise HTTPException(404, f"Machine ID không hợp lệ: {machine_id!r}")

    # Base query
    base_stmt = select(DfirInvestigation)
    count_stmt = select(sa_func.count()).select_from(DfirInvestigation)
    if machine_uuid:
        base_stmt = base_stmt.where(DfirInvestigation.machine_id == machine_uuid)
        count_stmt = count_stmt.where(DfirInvestigation.machine_id == machine_uuid)
    if status_filter:
        base_stmt = base_stmt.where(DfirInvestigation.status == status_filter)
        count_stmt = count_stmt.where(DfirInvestigation.status == status_filter)
    if severity:
        base_stmt = base_stmt.where(DfirInvestigation.severity == severity)
        count_stmt = count_stmt.where(DfirInvestigation.severity == severity)

    # Count total
    total = (await db.execute(count_stmt)).scalar() or 0

    # Page
    offset = (page - 1) * limit
    stmt = base_stmt.order_by(DfirInvestigation.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    # Batch load machines (tránh N+1 query)
    machine_ids = {inv.machine_id for inv in rows}
    machine_map: dict = {}
    if machine_ids:
        machines = (await db.execute(
            select(Machine).where(Machine.id.in_(machine_ids))
        )).scalars().all()
        machine_map = {m.id: m for m in machines}

    items = [_inv_to_out(inv, machine_map.get(inv.machine_id)) for inv in rows]

    return DfirInvestigationListOut(
        items=items,
        total=total,
        page=page,
        limit=limit,
        has_more=(offset + len(rows)) < total,
    )


@router.get("/stats", response_model=DfirInvestigationStatsOut)
async def get_investigation_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
    days: int = Query(30, ge=1, le=365),
):
    """Thống kê investigation cho dashboard Báo cáo.

    - Tổng số investigation
    - Phân bố theo status, severity
    - Top 10 máy có nhiều investigation nhất (kèm số critical)
    - Đếm 24h, 7 ngày qua
    - Trung bình thời gian xử lý (start → completed)
    - Daily counts cho chart 30 ngày
    - Top MITRE ATT&CK techniques
    """
    from sqlalchemy import func as sa_func, case
    from datetime import timedelta

    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    cutoff_daily = now - timedelta(days=days)

    # 1. Tổng
    total = (await db.execute(
        select(sa_func.count()).select_from(DfirInvestigation)
    )).scalar() or 0

    # 2. By status
    status_rows = (await db.execute(
        select(DfirInvestigation.status, sa_func.count())
        .group_by(DfirInvestigation.status)
    )).all()
    by_status = {s: c for s, c in status_rows}

    # 3. By severity
    severity_rows = (await db.execute(
        select(DfirInvestigation.severity, sa_func.count())
        .where(DfirInvestigation.severity.is_not(None))
        .group_by(DfirInvestigation.severity)
    )).all()
    by_severity = {s: c for s, c in severity_rows}

    # 4. Top máy
    machine_rows = (await db.execute(
        select(
            DfirInvestigation.machine_id,
            sa_func.count().label("count"),
            sa_func.sum(case((DfirInvestigation.severity == "critical", 1), else_=0)).label("critical"),
        )
        .group_by(DfirInvestigation.machine_id)
        .order_by(sa_func.count().desc())
        .limit(10)
    )).all()
    machine_ids = [r[0] for r in machine_rows]
    machine_map = {}
    if machine_ids:
        machines = (await db.execute(
            select(Machine).where(Machine.id.in_(machine_ids))
        )).scalars().all()
        machine_map = {m.id: m for m in machines}
    by_machine = [
        {
            "machine_id": str(mid),
            "hostname": machine_map[mid].hostname if mid in machine_map else None,
            "count": count,
            "critical": int(critical or 0),
        }
        for mid, count, critical in machine_rows
    ]

    # 5. Recent
    recent_24h = (await db.execute(
        select(sa_func.count()).select_from(DfirInvestigation)
        .where(DfirInvestigation.created_at >= cutoff_24h)
    )).scalar() or 0
    recent_7d = (await db.execute(
        select(sa_func.count()).select_from(DfirInvestigation)
        .where(DfirInvestigation.created_at >= cutoff_7d)
    )).scalar() or 0

    # 6. Avg duration (giây) — chỉ tính investigation completed có started_at + completed_at
    avg_dur_row = (await db.execute(
        select(
            sa_func.avg(
                sa_func.extract("epoch", DfirInvestigation.completed_at)
                - sa_func.extract("epoch", DfirInvestigation.started_at)
            )
        )
        .where(
            DfirInvestigation.status == "completed",
            DfirInvestigation.started_at.is_not(None),
            DfirInvestigation.completed_at.is_not(None),
        )
    )).scalar()
    avg_duration_seconds = float(avg_dur_row) if avg_dur_row is not None else None

    # 7. Daily counts (chart series) — nhóm theo ngày
    # Dùng date_trunc trong PostgreSQL
    from sqlalchemy import text as sa_text
    daily_rows = (await db.execute(
        sa_text("""
            SELECT
                DATE(created_at) AS day,
                COUNT(*) AS total,
                SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) AS critical
            FROM dfir_investigations
            WHERE created_at >= :cutoff
            GROUP BY DATE(created_at)
            ORDER BY day ASC
        """),
        {"cutoff": cutoff_daily},
    )).all()
    daily_counts = [
        {"date": str(day), "total": int(total), "critical": int(critical or 0)}
        for day, total, critical in daily_rows
    ]

    # 8. Top findings (từ JSONB findings column)
    findings_rows = (await db.execute(
        sa_text("""
            SELECT
                jsonb_array_elements(findings)->>'mitre_id' AS mitre_id,
                jsonb_array_elements(findings)->>'title' AS title,
                COUNT(*) AS cnt
            FROM dfir_investigations
            WHERE findings IS NOT NULL
              AND jsonb_typeof(findings) = 'array'
              AND jsonb_array_length(findings) > 0
            GROUP BY mitre_id, title
            ORDER BY cnt DESC
            LIMIT 10
        """),
    )).all()
    top_findings = [
        {"mitre_id": m, "title": t, "count": int(c)}
        for m, t, c in findings_rows
        if m
    ]

    return DfirInvestigationStatsOut(
        total=total,
        by_status=by_status,
        by_severity=by_severity,
        by_machine=by_machine,
        recent_24h=recent_24h,
        recent_7d=recent_7d,
        avg_duration_seconds=avg_duration_seconds,
        daily_counts=daily_counts,
        top_findings=top_findings,
    )


@router.post("/investigations", response_model=DfirInvestigationOut, status_code=201)
async def create_investigation(
    body: DfirInvestigationCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    machine = (
        await db.execute(select(Machine).where(Machine.id == body.machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(404, "Machine không tồn tại")

    active_count = (
        await db.execute(
            select(func.count())
            .select_from(DfirInvestigation)
            .where(DfirInvestigation.machine_id == body.machine_id)
            .where(
                DfirInvestigation.status.in_(
                    ["pending", "running", "collecting", "analyzing"]
                )
            )
        )
    ).scalar() or 0
    if active_count >= 5:
        raise HTTPException(
            429,
            f"Đã có {active_count} investigation đang chạy cho máy này. "
            "Đợi hoàn thành hoặc xoá investigation cũ.",
        )

    try:
        inv = await inv_svc.create_investigation(
            db,
            machine_id=str(body.machine_id),
            artifacts=body.artifacts,
            custom_instructions=body.custom_instructions,
            requested_by=str(admin.id),
            use_external_orchestrator=body.use_external_orchestrator,
        )
    except LlmError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e

    # `inv` giờ là dict (tránh detached). Lấy id cho audit.
    inv_id = inv["id"] if isinstance(inv, dict) else inv.id
    await append_audit(
        db, action="llm.investigate.start", actor=str(admin.id),
        target=f"{inv_id}#{body.machine_id}",
    )
    await db.commit()
    # Trả về DfirInvestigationOut từ DB
    inv_id_uuid = _parse_inv_id_or_404(inv_id) if isinstance(inv_id, str) else inv_id
    inv_db = (await db.execute(
        select(DfirInvestigation).where(DfirInvestigation.id == inv_id_uuid)
    )).scalar_one_or_none()
    return _inv_to_out(inv_db, machine)


@router.get("/investigations/{inv_id}", response_model=DfirInvestigationOut)
async def get_investigation(
    inv_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    inv = (
        await db.execute(select(DfirInvestigation).where(DfirInvestigation.id == _parse_inv_id_or_404(inv_id)))
    ).scalar_one_or_none()
    if inv is None:
        raise HTTPException(404, "Investigation không tồn tại")
    machine = (
        await db.execute(select(Machine).where(Machine.id == inv.machine_id))
    ).scalar_one_or_none()
    return _inv_to_out(inv, machine)


@router.get(
    "/investigations/{inv_id}/messages",
    response_model=list[DfirInvestigationMessageOut],
)
async def get_investigation_messages(
    inv_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    msgs = (
        await db.execute(
            select(DfirInvestigationMessage)
            .where(DfirInvestigationMessage.investigation_id == inv_id)
            .order_by(DfirInvestigationMessage.created_at)
        )
    ).scalars().all()
    return [
        DfirInvestigationMessageOut(
            id=m.id, role=m.role, content=m.content, tokens=m.tokens, created_at=m.created_at,
        )
        for m in msgs
    ]


@router.post("/investigations/{inv_id}/chat")
async def chat_investigation(
    inv_id: str,
    body: DfirInvestigationChatIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    if not body.message.strip():
        raise HTTPException(422, "message không được rỗng")
    try:
        result = await inv_svc.chat_with_llm(
            db, investigation_id=str(inv_id), user_message=body.message.strip(),
        )
    except LlmError as e:
        raise HTTPException(400, str(e)) from e

    await append_audit(
        db, action="llm.investigate.chat", actor=str(admin.id),
        target=f"{inv_id}#{result['input_tokens']}",
    )
    await db.commit()
    return {
        "response": result["response"],
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "model": result["model"],
    }

@router.delete("/investigations/{inv_id}", status_code=204)
async def delete_investigation(
    inv_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    inv = (
        await db.execute(select(DfirInvestigation).where(DfirInvestigation.id == _parse_inv_id_or_404(inv_id)))
    ).scalar_one_or_none()
    if inv is None:
        raise HTTPException(404, "Investigation không tồn tại")
    if inv.status in ("running", "collecting", "analyzing"):
        raise HTTPException(409, f"Không thể xoá investigation đang chạy (status={inv.status})")
    await db.delete(inv)
    await append_audit(
        db, action="llm.investigate.delete", actor=str(admin.id), target=str(inv_id),
    )
    await db.commit()


# ── Helper: parse UUID hoặc trả 404 (tránh 422 cho invalid ID) ──


def _parse_inv_id_or_404(inv_id: str) -> uuid.UUID:
    """Parse investigation ID string thành UUID. Nếu sai format → 404 thay vì 422.

    Lý do: khi user nhập URL trực tiếp với ID không hợp lệ (VD notification cũ với
    entity_id='abc-123'), Pydantic mặc định trả 422 (Unprocessable Entity). Nhưng về
    mặt UX, đây thực chất là "không tìm thấy resource" → nên trả 404.
    """
    try:
        return uuid.UUID(inv_id)
    except (ValueError, TypeError):
        raise HTTPException(404, f"Investigation ID không hợp lệ: {inv_id!r}")
