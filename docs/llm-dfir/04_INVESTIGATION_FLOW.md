# 04 — Investigation Orchestrator + Background Worker

> File mới: `server/app/services/dfir_investigation.py`
> Sửa: `server/app/services/monitor.py`

Đây là **trái tim** của tính năng: điều phối Velociraptor collect → LLM phân tích → lưu báo cáo.

---

## A. Code `server/app/services/dfir_investigation.py`

```python
"""Orchestrator cho LLM-DFIR investigation.

Một investigation chạy qua 5 trạng thái:
    pending → running → collecting → analyzing → completed
                                       ↘ failed / timeout

Flow:
  1. _run_pending_investigations() — chạy mỗi 30s từ monitor loop
     → lấy các row status=pending/running/collecting
     → xử lý theo state
  2. trigger_collect() — gọi Velociraptor collect_artifact cho từng artifact
  3. poll_collect() — chờ flow.status="OK" rồi lấy results
  4. analyze_with_llm() — bundle data + gọi LLM + lưu report
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

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
    VelociraptorLink,
)
from app.services.llm import (
    LlmAuthError,
    LlmBudgetExceededError,
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
from app.services.velociraptor import VelociraptorError
from app.services.velociraptor import VelociraptorClient as VeloClient

logger = logging.getLogger("llm.dfir")


# ── Config loader ────────────────────────────────────────────────


async def _load_llm_config(db: AsyncSession) -> LlmConfig | None:
    """Lấy LlmConfig singleton."""
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
) -> DfirInvestigation:
    """Tạo investigation mới (status=pending) — background worker sẽ xử lý."""
    if not await _is_llm_enabled(db):
        raise LlmError("LLM chưa được cấu hình hoặc chưa bật (xem /admin/llm-dfir/settings).")

    # Lấy Velociraptor link
    link = (
        await db.execute(
            select(VelociraptorLink).where(VelociraptorLink.machine_id == machine_id)
        )
    ).scalar_one_or_none()
    if not link or not link.client_id:
        raise LlmError(
            "Máy chưa được link với Velociraptor (chưa có client_id). "
            "Chạy POST /api/admin/velociraptor/sync trước hoặc đợi sync 5 phút/lần."
        )

    if not artifacts:
        artifacts = list(settings.llm_default_artifacts)

    inv = DfirInvestigation(
        machine_id=machine_id,
        velociraptor_client_id=link.client_id,
        artifacts=artifacts,
        status="pending",
        custom_instructions=custom_instructions,  # cần thêm field này
        requested_by=requested_by,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    logger.info(
        "Investigation %s created (machine=%s, client_id=%s, artifacts=%d)",
        inv.id,
        machine_id,
        link.client_id,
        len(artifacts),
    )
    return inv


# ── Public: background worker entry point ────────────────────────


async def run_pending_investigations() -> dict:
    """Gọi từ monitor loop mỗi LLM_INVESTIGATION_INTERVAL_SECONDS.

    Returns dict thống kê (debug + log).
    """
    started = time.time()
    processed: list[str] = []
    errors: list[str] = []

    async with db_session.AsyncSessionLocal() as db:
        if not await _is_llm_enabled(db):
            return {"skipped": True, "reason": "llm_disabled"}

        # Lấy các investigation đang chạy
        active = (
            await db.execute(
                select(DfirInvestigation)
                .where(DfirInvestigation.status.in_(["pending", "running", "collecting"]))
                .order_by(DfirInvestigation.created_at)
                .limit(5)  # xử lý tối đa 5 concurrent
            )
        ).scalars().all()

        for inv in active:
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
    """State machine cho 1 investigation."""
    if inv.status == "pending":
        await _state_start(db, inv)
    elif inv.status == "running":
        await _state_poll_collect(db, inv)
    elif inv.status == "collecting":
        await _state_analyze(db, inv)


async def _state_start(db: AsyncSession, inv: DfirInvestigation) -> None:
    """pending → running → collecting (gọi Velociraptor)."""
    inv.status = "running"
    inv.started_at = datetime.now(UTC)
    await db.commit()

    # Gọi Velociraptor collect artifacts
    try:
        # Lazy import để tránh circular
        from app.api.routes.velociraptor import _build_velociraptor_client
        async with _build_velociraptor_client(db) as velo:
            # Collect từng artifact một (Velociraptor collect_artifact = 1 flow)
            flows: list[dict] = []
            for art in inv.artifacts:
                flow = await velo.collect_artifact(
                    client_id=inv.velociraptor_client_id,
                    artifact=art,
                )
                flows.append({"artifact": art, "flow_id": flow.get("flow_id"), "raw": flow})
            inv.raw_artifacts = {"flows": flows}
            inv.flow_id = flows[0]["flow_id"] if flows else None
            inv.status = "collecting"
            await db.commit()
            logger.info("Investigation %s: triggered %d flows", inv.id, len(flows))
    except VelociraptorError as e:
        inv.status = "failed"
        inv.error = f"Velociraptor: {e}"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        raise


async def _state_poll_collect(db: AsyncSession, inv: DfirInvestigation) -> None:
    """collecting: poll Velociraptor chờ flow xong → analyzing."""
    # Timeout
    if inv.started_at:
        elapsed = (datetime.now(UTC) - inv.started_at).total_seconds()
        if elapsed > settings.llm_collect_max_wait_seconds:
            inv.status = "failed"
            inv.error = f"Timeout sau {elapsed:.0f}s chờ Velociraptor"
            inv.completed_at = datetime.now(UTC)
            await db.commit()
            return

    # Poll từng flow
    flows = (inv.raw_artifacts or {}).get("flows") or []
    if not flows:
        inv.status = "failed"
        inv.error = "Không có flow nào để poll"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        return

    try:
        from app.api.routes.velociraptor import _build_velociraptor_client
        async with _build_velociraptor_client(db) as velo:
            all_done = True
            for flow in flows:
                flow_id = flow.get("flow_id")
                if not flow_id or flow.get("results_cached"):
                    continue
                status = await velo.get_flow_status(inv.velociraptor_client_id, flow_id)
                if status.get("is_running"):
                    all_done = False
                    continue
                if status.get("error"):
                    flow["error"] = status["error"]
                    flow["results_cached"] = True
                    continue
                # Flow xong → lấy results
                try:
                    results = await velo.get_flow_results(inv.velociraptor_client_id, flow_id)
                    flow["results"] = results
                    flow["results_cached"] = True
                except Exception as e:  # noqa: BLE001
                    flow["error"] = f"get_results: {e}"
                    flow["results_cached"] = True
            await db.commit()

            if all_done:
                inv.status = "analyzing"
                await db.commit()
                logger.info("Investigation %s: all flows done → analyzing", inv.id)
    except VelociraptorError as e:
        logger.warning("Investigation %s poll error: %s", inv.id, e)
        # Không fail ngay, thử lại lần sau


async def _state_analyze(db: AsyncSession, inv: DfirInvestigation) -> None:
    """analyzing: bundle data + gọi LLM + lưu report → completed."""
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
        results = flow.get("results") or []
        if isinstance(results, list):
            artifacts_data[art] = results
        elif isinstance(results, dict):
            # Một số artifact trả về dict {column: [values]} — chuyển về list[dict]
            cols = list(results.keys())
            n = max((len(v) for v in results.values() if isinstance(v, list)), default=0)
            rows: list[dict] = []
            for i in range(n):
                row = {c: results[c][i] if i < len(results.get(c, [])) else None for c in cols}
                rows.append(row)
            artifacts_data[art] = rows

    # Lấy OS info từ VelociraptorLink
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

    # Lấy hostname
    machine = (
        await db.execute(select(Machine).where(Machine.id == inv.machine_id))
    ).scalar_one_or_none()
    hostname = (machine.hostname if machine else None) or (os_info.get("hostname") or "unknown")

    # Build prompt
    custom = getattr(inv, "custom_instructions", None)
    user_prompt = build_investigation_user_prompt(
        hostname=hostname,
        os_info=os_info,
        artifacts_data=artifacts_data,
        custom_instructions=custom,
    )

    # Trim nếu quá dài
    if len(user_prompt) > cfg.max_context_chars:
        # Cắt phần artifacts, giữ system + header
        user_prompt = user_prompt[: cfg.max_context_chars] + "\n\n[DỮ LIỆU ĐÃ CẮT BỚT DO QUÁ DÀI]"

    system_prompt = cfg.system_prompt or build_dfir_system_prompt()
    messages = [
        LlmMessage("system", system_prompt),
        LlmMessage("user", user_prompt),
    ]

    # Gọi LLM
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
            verify_ssl=True,
        ) as llm:
            resp = await llm.chat(messages)

        inv.report_markdown = resp.content
        inv.input_tokens = resp.input_tokens
        inv.output_tokens = resp.output_tokens
        inv.estimated_cost_usd = resp.estimated_cost_usd

        # Parse severity + findings từ response (đơn giản: regex)
        inv.severity = _parse_severity(resp.content)
        inv.findings_count = _parse_findings_count(resp.content)

        # Lưu system + user + assistant messages
        db.add(DfirInvestigationMessage(
            investigation_id=inv.id, role="system", content=system_prompt,
            tokens=cfg.max_tokens,
        ))
        db.add(DfirInvestigationMessage(
            investigation_id=inv.id, role="user", content=user_prompt,
            tokens=resp.input_tokens,
        ))
        db.add(DfirInvestigationMessage(
            investigation_id=inv.id, role="assistant", content=resp.content,
            tokens=resp.output_tokens,
        ))

        # Cộng token vào daily budget
        cfg.tokens_used_today = (cfg.tokens_used_today or 0) + resp.total_tokens

        inv.status = "completed"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
        logger.info(
            "Investigation %s completed: severity=%s findings=%d tokens=%d",
            inv.id, inv.severity, inv.findings_count or 0, resp.total_tokens,
        )

    except LlmAuthError as e:
        inv.status = "failed"
        inv.error = f"LLM auth: {e}"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
    except LlmTimeoutError as e:
        inv.status = "failed"
        inv.error = f"LLM timeout: {e}"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
    except LlmRateLimitError as e:
        inv.status = "failed"
        inv.error = f"LLM rate limit: {e}"
        inv.completed_at = datetime.now(UTC)
        await db.commit()
    except LlmError as e:
        inv.status = "failed"
        inv.error = f"LLM: {e}"
        inv.completed_at = datetime.now(UTC)
        await db.commit()


# ── Public: chat Q&A ─────────────────────────────────────────────


async def chat_with_llm(db: AsyncSession, *, investigation_id: str, user_message: str) -> dict:
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

    # Lấy tất cả messages trước
    msgs = (
        await db.execute(
            select(DfirInvestigationMessage)
            .where(DfirInvestigationMessage.investigation_id == investigation_id)
            .order_by(DfirInvestigationMessage.created_at)
        )
    ).scalars().all()

    # Build context: tất cả messages + câu hỏi mới
    llm_messages = [LlmMessage(m.role, m.content) for m in msgs]
    question_prompt = build_chat_user_prompt(user_message)
    llm_messages.append(LlmMessage("user", question_prompt))

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

    # Lưu 2 messages mới
    db.add(DfirInvestigationMessage(
        investigation_id=inv.id, role="user", content=user_message, tokens=resp.input_tokens,
    ))
    db.add(DfirInvestigationMessage(
        investigation_id=inv.id, role="assistant", content=resp.content, tokens=resp.output_tokens,
    ))
    cfg.tokens_used_today = (cfg.tokens_used_today or 0) + resp.total_tokens
    await db.commit()

    return {
        "response": resp.content,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "model": resp.model,
    }


# ── Helpers ──────────────────────────────────────────────────────


def _parse_severity(markdown: str) -> str:
    """Trích severity từ response markdown: '**Mức độ nghiêm trọng:** critical'."""
    import re
    m = re.search(r"(?:Mức độ nghiêm trọng|severity)[*:\s]+(\w+)", markdown, re.IGNORECASE)
    if m:
        sev = m.group(1).lower()
        if sev in ("critical", "high", "medium", "low", "info"):
            return sev
    return "info"


def _parse_findings_count(markdown: str) -> int:
    """Đếm số phát hiện: '**Số phát hiện:** N' hoặc '### 2.1' patterns."""
    import re
    m = re.search(r"(?:Số phát hiện|findings)[*:\s]+(\d+)", markdown, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Fallback: đếm heading '### 2.x'
    return len(re.findall(r"^###\s+2\.\d+", markdown, re.MULTILINE))
```

---

## B. Sửa `server/app/db/models.py` — thêm field `custom_instructions`

Trong class `DfirInvestigation`, thêm 1 dòng sau `artifacts`:

```python
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Và thêm vào migration (file `n2o3p4q5r6s7_llm_dfir.py`):

```python
    sa.Column("custom_instructions", sa.Text(), nullable=True),
```

---

## C. Sửa `server/app/services/monitor.py` — đăng ký background worker

Thêm import và đăng ký 1 task poll mới:

```python
# Đầu file, thêm
from app.services import dfir_investigation
```

Trong `monitor_loop()`, thêm block (đặt cùng cụm với velociraptor check):

```python
        # LLM-DFIR investigation worker
        last_llm_worker_check = -LLM_INVESTIGATION_INTERVAL_SECONDS
        # ...

        if now - last_llm_worker_check >= LLM_INVESTIGATION_INTERVAL_SECONDS:
            try:
                await dfir_investigation.run_pending_investigations()
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM-DFIR worker error: %s", exc)
            last_llm_worker_check = now
```

Và định nghĩa constant ngay đầu file:

```python
LLM_INVESTIGATION_INTERVAL_SECONDS = settings.llm_investigation_interval_seconds
```

---

## D. VelociraptorClient — thêm helper cần thiết

Trong `server/app/services/velociraptor.py`, đảm bảo có 2 method này (nếu chưa có — xem file hiện tại dòng 121+):

```python
async def collect_artifact(self, client_id: str, artifact: str) -> dict:
    """Gọi Velociraptor POST /api/v1/CollectArtifact — trả {flow_id, ...}"""
    url = f"{self.server_url}{self.BASE_PATH}/CollectArtifact"
    body = {
        "client_id": client_id,
        "artifacts": [artifact],
        "specs": {},
    }
    r = await self._client.post(url, json=body, params={"require_new_flow": "true"})
    r.raise_for_status()
    return r.json() if r.text else {}


async def get_flow_status(self, client_id: str, flow_id: str) -> dict:
    """Gọi Velociraptor GET /api/v1/GetFlowStatus — trả {is_running, error, ...}"""
    url = f"{self.server_url}{self.BASE_PATH}/GetFlowStatus"
    r = await self._client.get(url, params={"client_id": client_id, "flow_id": flow_id})
    r.raise_for_status()
    data = r.json() if r.text else {}
    # Velociraptor: context.flow.status trả "RUNNING"/"FINISHED" — wrap
    ctx = data.get("context", {}) if isinstance(data, dict) else {}
    state = ctx.get("flow", {}).get("state") if isinstance(ctx, dict) else None
    if isinstance(state, str):
        data["is_running"] = (state == "RUNNING")
        data["state"] = state
    return data


async def get_flow_results(self, client_id: str, flow_id: str) -> list | dict:
    """Gọi Velociraptor GET /api/v1/GetFlow → parse results."""
    url = f"{self.server_url}{self.BASE_PATH}/GetFlow"
    r = await self._client.get(url, params={"client_id": client_id, "flow_id": flow_id})
    r.raise_for_status()
    data = r.json() if r.text else {}
    # Parse results từ available_downloads / exported_results — tùy version Velociraptor
    # Trả về list rows hoặc dict columnar
    if isinstance(data, dict):
        # Thử nhiều vị trí Velociraptor có thể trả kết quả
        if "results" in data:
            return data["results"]
        if "available_downloads" in data:
            return data["available_downloads"]
    return data
```

> **Lưu ý:** Cần kiểm tra API doc Velociraptor hiện tại của bạn — field chính xác có thể khác. Stub trên là dạng phổ biến. Khi implement thật, mở Velociraptor GUI → chạy 1 collect đơn giản → dùng DevTools Network để xem response mẫu.

---

## E. Sơ đồ trạng thái investigation

```
                    ┌─────────────┐
                    │   pending   │  ← Tạo bởi API
                    └──────┬──────┘
                           │ background worker (≤30s)
                           ▼
                    ┌─────────────┐
              ┌────►│   running   │  Gọi Velociraptor.collect_artifact
              │     └──────┬──────┘
              │            │ có flow_id
              │            ▼
              │     ┌─────────────┐
              │     │ collecting  │  Poll mỗi 10s
              │     └──────┬──────┘
              │            │ tất cả flow OK
              │            ▼
              │     ┌─────────────┐
              │     │  analyzing  │  Gọi LLM
              │     └──────┬──────┘
              │            │ LLM xong
              │            ▼
              │     ┌─────────────┐
              │     │  completed  │  ✅ Hiển thị report + Q&A
              │     └─────────────┘
              │
       Velociraptor error / LLM error / timeout
              │
              ▼
       ┌─────────────┐
       │   failed    │  ❌ Lưu error
       └─────────────┘
```

---
