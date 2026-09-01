from __future__ import annotations

import httpx

from deepagent.config import Settings
from deepagent.models import CallbackPayload


class BackendCallbackClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def submit(self, investigation_id: str, payload: CallbackPayload) -> dict:
        if not self.settings.backend_api_key:
            raise RuntimeError("DEEPAGENT_BACKEND_API_KEY chưa được cấu hình")
        url = (
            self.settings.backend_url.rstrip("/")
            + f"/api/external/llm-dfir/investigations/{investigation_id}/result"
        )
        headers = {
            "Authorization": f"Bearer {self.settings.backend_api_key}",
            "X-Idempotency-Key": payload.external_job_id,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url, headers=headers, json=payload.model_dump(mode="json")
            )
        response.raise_for_status()
        return response.json()
