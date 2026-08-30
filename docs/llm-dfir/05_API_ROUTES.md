# 05 — API Routes cho LLM-DFIR

> File mới: `server/app/api/routes/llm_dfir.py`
> Sửa: `server/app/main.py` (include router)

---

## A. Code `server/app/api/routes/llm_dfir.py`

```python
"""API endpoints cho LLM-DFIR:
  - GET    /api/admin/llm-dfir/config          — lấy cấu hình LLM
  - PUT    /api/admin/llm-dfir/config          — cập nhật cấu hình
  - POST   /api/admin/llm-dfir/config/test     — test kết nối
  - GET    /api/admin/llm-dfir/investigations           — list (phân trang)
  - POST   /api/admin/llm-dfir/investigations           — tạo mới
  - GET    /api/admin/llm-dfir/investigations/{id}      — chi tiết
  - GET    /api/admin/llm-dfir/investigations/{id}/messages — chat history
  - POST   /api/admin/llm-dfir/investigations/{id}/chat    — Q&A
  - DELETE /api/admin/llm-dfir/investigations/{id}      — xoá
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_super_admin
from app.core.audit import append_audit
from app.core.security import encrypt_aes_gcm
from app.db.models import (
    DfirInvestigation,
    DfirInvestigationMessage,
    LlmConfig,
    Machine,
    User,
    VelociraptorLink,
)
from app.schemas import (
    DfirInvestigationChatIn,
    DfirInvestigationCreate,
    DfirInvestigationMessageOut,
    DfirInvestigationOut,
    LlmConfigOut,
    LlmConfigUpdate,
    LlmTestConnectionOut,
)
from app.services.llm import LlmClient, mask_api_key
from app.services.llm_prompts import build_dfir_system_prompt
from app.services import dfir_investigation as inv_svc

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
        )
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


def _config_to_out(cfg: LlmConfig, available_models: list[str] | None = None) -> LlmConfigOut:
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
        daily_token_budget=cfg.daily_token_budget,
        tokens_used_today=cfg.tokens_used_today or 0,
        test_status=cfg.test_status,
        test_error=cfg.test_error,
        test_at=cfg.test_at,
        updated_at=cfg.updated_at,
        available_models=available_models or [],
    )


def _decrypt_for_display(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        from app.core.security import decrypt_aes_gcm
        return decrypt_aes_gcm(encrypted)
    except Exception:
        return None


# ── Config endpoints ─────────────────────────────────────────────


@router.get("/config", response_model=LlmConfigOut)
async def get_llm_config(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    cfg = await _get_or_create_config(db)
    # Cố gắng list models (best-effort, 3s timeout)
    models: list[str] = []
    if cfg.base_url:
        try:
            api_key = _decrypt_for_display(cfg.api_key_encrypted)
            async with LlmClient(cfg.base_url, api_key, cfg.model, timeout=5) as llm:
                models = await llm.list_models()
        except Exception:  # noqa: BLE001
            pass
    return _config_to_out(cfg, models)


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
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(422, "base_url phải bắt đầu bằng http:// hoặc https://")
        if not url:
            raise HTTPException(422, "base_url không được rỗng")
        cfg.base_url = url
        changes["base_url"] = url
    if body.api_key is not None:
        if body.api_key == "":
            cfg.api_key_encrypted = None
            changes["api_key"] = "cleared"
        else:
            # Chặn cloud nếu chưa allow
            if not cfg.allow_cloud and "127.0.0.1" not in cfg.base_url and "localhost" not in cfg.base_url and "10." not in cfg.base_url and "192.168." not in cfg.base_url and "172." not in cfg.base_url:
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
        if body.max_tokens < 64 or body.max_tokens > 32000:
            raise HTTPException(422, "max_tokens phải trong [64, 32000]")
        cfg.max_tokens = body.max_tokens
    if body.temperature is not None:
        if not (0.0 <= body.temperature <= 2.0):
            raise HTTPException(422, "temperature phải trong [0.0, 2.0]")
        cfg.temperature = body.temperature
    if body.request_timeout is not None:
        if body.request_timeout < 10 or body.request_timeout > 600:
            raise HTTPException(422, "request_timeout phải trong [10, 600]")
        cfg.request_timeout = body.request_timeout
    if body.max_context_chars is not None:
        if body.max_context_chars < 1000 or body.max_context_chars > 1_000_000:
            raise HTTPException(422, "max_context_chars phải trong [1000, 1000000]")
        cfg.max_context_chars = body.max_context_chars
    if body.allow_cloud is not None:
        cfg.allow_cloud = body.allow_cloud
        changes["allow_cloud"] = body.allow_cloud
    if body.daily_token_budget is not None:
        cfg.daily_token_budget = body.daily_token_budget if body.daily_token_budget > 0 else None

    cfg.updated_at = datetime.now(UTC)
    cfg.updated_by = admin.id
    cfg.test_status = "untested"  # reset sau khi đổi config
    await db.commit()
    await append_audit(
        db, action="llm.config.update", actor=str(admin.id),
        target="llm_config:1", changes=changes,
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
    async with LlmClient(
        cfg.base_url, api_key, cfg.model, timeout=15,
    ) as llm:
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


# ── Investigation endpoints ──────────────────────────────────────


@router.get("/investigations", response_model=list[DfirInvestigationOut])
async def list_investigations(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
    machine_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(DfirInvestigation).order_by(DfirInvestigation.created_at.desc())
    if machine_id:
        stmt = stmt.where(DfirInvestigation.machine_id == machine_id)
    if status_filter:
        stmt = stmt.where(DfirInvestigation.status == status_filter)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    # Hydrate hostname
    out: list[DfirInvestigationOut] = []
    for inv in rows:
        machine = (
            await db.execute(select(Machine).where(Machine.id == inv.machine_id))
        ).scalar_one_or_none()
        out.append(_inv_to_out(inv, machine))
    return out


@router.post("/investigations", response_model=DfirInvestigationOut, status_code=201)
async def create_investigation(
    body: DfirInvestigationCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    # Verify machine exists
    machine = (
        await db.execute(select(Machine).where(Machine.id == body.machine_id))
    ).scalar_one_or_none()
    if machine is None:
        raise HTTPException(404, "Machine không tồn tại")

    # Check rate limit (max 5 active investigations per machine)
    active_count = (
        await db.execute(
            select(func.count())
            .select_from(DfirInvestigation)
            .where(DfirInvestigation.machine_id == body.machine_id)
            .where(DfirInvestigation.status.in_(["pending", "running", "collecting", "analyzing"]))
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
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e

    await append_audit(
        db, action="llm.investigate.start", actor=str(admin.id),
        target=str(inv.id), changes={"machine_id": str(body.machine_id), "artifacts": body.artifacts},
    )
    await db.commit()
    return _inv_to_out(inv, machine)


@router.get("/investigations/{inv_id}", response_model=DfirInvestigationOut)
async def get_investigation(
    inv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin()),
):
    inv = (
        await db.execute(select(DfirInvestigation).where(DfirInvestigation.id == inv_id))
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
    inv_id: uuid.UUID,
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
    inv_id: uuid.UUID,
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
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e

    await append_audit(
        db, action="llm.investigate.chat", actor=str(admin.id),
        target=str(inv_id), changes={"input_tokens": result["input_tokens"]},
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
    inv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_super_admin()),
):
    inv = (
        await db.execute(select(DfirInvestigation).where(DfirInvestigation.id == inv_id))
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


# ── Helpers ──────────────────────────────────────────────────────


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
        input_tokens=inv.input_tokens,
        output_tokens=inv.output_tokens,
        estimated_cost_usd=float(inv.estimated_cost_usd) if inv.estimated_cost_usd is not None else None,
        error=inv.error,
        report_markdown=inv.report_markdown,
        created_at=inv.created_at,
        started_at=inv.started_at,
        completed_at=inv.completed_at,
        requested_by=inv.requested_by,
    )
```

---

## B. Sửa `server/app/main.py`

```python
# Đầu file, thêm import
from app.api.routes import llm_dfir

# Trong phần include router, thêm
app.include_router(llm_dfir.router)
```

---

## C. Sample API call

### Lấy config hiện tại
```bash
curl -H "Cookie: access_token=..." http://localhost:8000/api/admin/llm-dfir/config
```
```json
{
  "enabled": true,
  "provider": "ollama",
  "base_url": "http://127.0.0.1:11434/v1",
  "api_key_masked": "(không đặt)",
  "model": "qwen2.5:14b-instruct-q4_K_M",
  "fallback_model": null,
  "max_tokens": 4096,
  "temperature": 0.0,
  "available_models": ["qwen2.5:14b-instruct-q4_K_M", "qwen2.5:7b-instruct-q4_K_M", ...]
}
```

### Test connection
```bash
curl -X POST -H "Cookie: access_token=..." http://localhost:8000/api/admin/llm-dfir/config/test
```
```json
{
  "ok": true,
  "latency_ms": 1247,
  "models": ["qwen2.5:14b-instruct-q4_K_M", ...],
  "error": null
}
```

### Trigger investigation
```bash
curl -X POST -H "Cookie: access_token=..." \
  -H "Content-Type: application/json" \
  -d '{
    "machine_id": "abc-123-...",
    "artifacts": null,
    "custom_instructions": "Tập trung vào suspicious process và persistence"
  }' \
  http://localhost:8000/api/admin/llm-dfir/investigations
```
```json
{
  "id": "inv-xyz-...",
  "machine_id": "abc-123-...",
  "machine_hostname": "PC-CATTP-001",
  "status": "pending",
  "artifacts": ["Windows.System.Pslist", ...],
  "created_at": "2026-08-29T16:30:00Z",
  ...
}
```

### Poll status
```bash
curl -H "Cookie: access_token=..." \
  http://localhost:8000/api/admin/llm-dfir/investigations/inv-xyz-...
```

### Chat Q&A
```bash
curl -X POST -H "Cookie: access_token=..." \
  -H "Content-Type: application/json" \
  -d '{"message": "Có dấu hiệu crypto miner không?"}' \
  http://localhost:8000/api/admin/llm-dfir/investigations/inv-xyz-.../chat
```

---
