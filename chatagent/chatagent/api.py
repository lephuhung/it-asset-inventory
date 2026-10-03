"""ChatAgent HTTP surface (Task 12 skeleton; ReAct loop + SSE ở Task 15).

`POST /v1/chat` hiện là stub 501 — task 15 mới cài ReAct loop, SSE và
`GET /v1/chat/{turn_id}/status` / `POST /v1/chat/{turn_id}/cancel`.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, status

app = FastAPI(title="ChatAgent", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — không cần service token."""
    return {"status": "ok"}


@app.post("/v1/chat")
async def chat() -> None:
    """SSE turn stream — chưa triển khai (Task 15)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="[chat_internal] POST /v1/chat chưa được triển khai (Task 15) [HTTP 501]",
    )
