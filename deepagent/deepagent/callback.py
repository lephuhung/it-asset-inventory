from __future__ import annotations

from time import perf_counter

import httpx

from deepagent.config import Settings
from deepagent.models import CallbackPayload
from deepagent.observability import log_event


class BackendCallbackClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def submit_status(
        self,
        investigation_id: str,
        *,
        external_job_id: str,
        phase: str,
        progress_percent: int,
        current_step: int | None = None,
        total_steps: int | None = None,
        message: str | None = None,
    ) -> dict:
        started_at = perf_counter()
        if not self.settings.backend_api_key:
            error = RuntimeError("DEEPAGENT_BACKEND_API_KEY chưa được cấu hình")
            log_event(
                phase="backend_status_callback",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                callback_phase=phase,
                progress_percent=progress_percent,
                error=error,
            )
            raise error
        url = (
            self.settings.backend_url.rstrip("/")
            + f"/api/external/llm-dfir/investigations/{investigation_id}/status"
        )
        body = {
            "external_job_id": external_job_id,
            "phase": phase,
            "progress_percent": progress_percent,
            "current_step": current_step,
            "total_steps": total_steps,
            "message": message,
        }
        headers = {"Authorization": f"Bearer {self.settings.backend_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            log_event(
                phase="backend_status_callback",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                callback_phase=phase,
                progress_percent=progress_percent,
                error=exc,
            )
            raise
        log_event(
            phase="backend_status_callback",
            outcome="succeeded",
            duration_ms=(perf_counter() - started_at) * 1000,
            callback_phase=phase,
            progress_percent=progress_percent,
        )
        return result

    async def submit(self, investigation_id: str, payload: CallbackPayload) -> dict:
        started_at = perf_counter()
        if not self.settings.backend_api_key:
            error = RuntimeError("DEEPAGENT_BACKEND_API_KEY chưa được cấu hình")
            log_event(
                phase="backend_result_callback",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                error=error,
            )
            raise error
        url = (
            self.settings.backend_url.rstrip("/")
            + f"/api/external/llm-dfir/investigations/{investigation_id}/result"
        )
        headers = {
            "Authorization": f"Bearer {self.settings.backend_api_key}",
            "X-Idempotency-Key": payload.external_job_id,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    url, headers=headers, json=payload.model_dump(mode="json")
                )
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            log_event(
                phase="backend_result_callback",
                outcome="failed",
                duration_ms=(perf_counter() - started_at) * 1000,
                error=exc,
            )
            raise
        log_event(
            phase="backend_result_callback",
            outcome="succeeded",
            duration_ms=(perf_counter() - started_at) * 1000,
            findings_count=payload.findings_count,
            severity=payload.severity,
        )
        return result
