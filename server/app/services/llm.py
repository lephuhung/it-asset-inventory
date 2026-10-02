"""LLM service — wrapper OpenAI-compatible cho DFIR AI Assistant.

Hỗ trợ các backend: Ollama, LocalAI, vLLM, OpenAI, Qwen/DashScope, DeepSeek.
Tất cả đều dùng OpenAI Chat Completions format → 1 client duy nhất.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.egress import (
    assert_redirect_allowed,
    host_header,
    pinned_base_url,
    resolve_private_host,
    sni_hostname,
)

logger = logging.getLogger("llm")


# ── Exceptions ────────────────────────────────────────────────────


class LlmError(Exception):
    """Lỗi tổng quát khi gọi LLM."""


class LlmAuthError(LlmError):
    """API key sai / không đủ quyền."""


class LlmRateLimitError(LlmError):
    """LLM rate limit (429)."""


class LlmTimeoutError(LlmError):
    """LLM response chậm quá timeout."""


# ── Data classes ─────────────────────────────────────────────────


@dataclass
class LlmMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LlmResponse:
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
    finish_reason: str
    latency_ms: int

    @property
    def estimated_cost_usd(self) -> float:
        """Ước lượng chi phí USD (chỉ áp dụng cho cloud). Local = $0."""
        price_table: dict[str, dict[str, float]] = {
            "gpt-4o-mini": {"in": 0.15 / 1_000_000, "out": 0.6 / 1_000_000},
            "gpt-4o": {"in": 2.5 / 1_000_000, "out": 10.0 / 1_000_000},
            "qwen-plus": {"in": 0.11 / 1_000_000, "out": 0.27 / 1_000_000},
            "qwen-turbo": {"in": 0.04 / 1_000_000, "out": 0.08 / 1_000_000},
            "deepseek-chat": {"in": 0.14 / 1_000_000, "out": 0.28 / 1_000_000},
        }
        p = price_table.get(self.model)
        if not p:
            return 0.0
        return self.input_tokens * p["in"] + self.output_tokens * p["out"]


# ── Main client ──────────────────────────────────────────────────


class LlmClient:
    """OpenAI-compatible LLM client — context manager.

    Usage:
        async with LlmClient(base_url, api_key, model, timeout=120) as llm:
            resp = await llm.chat([LlmMessage("user", "Xin chào")])
            print(resp.content, resp.input_tokens, resp.output_tokens)
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        *,
        allow_cloud: bool = False,
        fallback_model: str | None = None,
        timeout: int = 120,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        verify_ssl: bool = True,
    ):
        base_url = base_url.strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url phải bắt đầu bằng http:// hoặc https://")
        if not model.strip():
            raise ValueError("model không được rỗng")

        # R7/V3-6: xác thực egress (loopback/private/link-local/CGNAT) và GHIM IP đã
        # resolve để kết nối — chống DNS rebinding giữa lúc kiểm tra và lúc gọi.
        self._host, self._pinned_ip = resolve_private_host(base_url, allow_cloud=allow_cloud)
        self._pinned_base_url = pinned_base_url(base_url, self._pinned_ip)
        self._host_header = host_header(base_url)
        self._sni_hostname = sni_hostname(base_url)
        self._allow_cloud = allow_cloud

        self.base_url = base_url
        self.api_key = api_key
        self.model = model.strip()
        self.fallback_model = fallback_model.strip() if fallback_model else None
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.verify_ssl = verify_ssl
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "LlmClient":
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # URL kết nối đã bị đổi host sang IP đã ghim → gửi kèm Host header gốc để
        # virtual-host vẫn đúng.
        headers["Host"] = self._host_header
        self._client = httpx.AsyncClient(
            base_url=self._pinned_base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            verify=self.verify_ssl,
            headers=headers,
            event_hooks={"response": [self._guard_redirect_hook]},
        )
        return self

    def _request_extensions(self) -> dict[str, str]:
        """Extension cho mỗi request: giữ TLS SNI = hostname gốc khi URL đã đổi sang IP."""
        return {"sni_hostname": self._sni_hostname}

    def _guard_redirect(self, response: httpx.Response) -> None:
        """R7: cấm redirect sang host public (chạy trên mọi response 3xx)."""
        if not response.is_redirect:
            return
        location = response.headers.get("location")
        if location:
            assert_redirect_allowed(
                str(response.request.url), location, self._allow_cloud
            )

    async def _guard_redirect_hook(self, response: httpx.Response) -> None:
        """httpx async client yêu cầu event hook async — bọc phần logic đồng bộ."""
        self._guard_redirect(response)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_models(self) -> list[str]:
        """Gọi GET {base_url}/models."""
        if not self._client:
            raise LlmError("Client chưa khởi tạo — dùng async with")
        url = "/models"
        t0 = time.time()
        try:
            r = await self._client.get(url, extensions=self._request_extensions())
        except httpx.ConnectError as e:
            raise LlmError(f"Không kết nối được LLM server: {e}") from e
        except httpx.TimeoutException as e:
            raise LlmTimeoutError(f"Timeout khi list models: {e}") from e

        if r.status_code == 401:
            raise LlmAuthError("API key không hợp lệ (401)")
        if r.status_code >= 400:
            raise LlmError(f"List models thất bại HTTP {r.status_code}: {r.text[:300]}")

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise LlmError(f"Response không phải JSON: {e}") from e

        models: list[str] = []
        for m in data.get("data", []):
            mid = m.get("id")
            if mid:
                models.append(mid)
        latency = int((time.time() - t0) * 1000)
        logger.info("LLM list_models: %d models, latency=%dms", len(models), latency)
        return sorted(models)

    async def chat(
        self,
        messages: list[LlmMessage],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LlmResponse:
        """Gọi POST {base_url}/chat/completions."""
        if not self._client:
            raise LlmError("Client chưa khởi tạo — dùng async with")

        use_model = (model or self.model).strip()
        body: dict[str, Any] = {
            "model": use_model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }

        url = "/chat/completions"
        t0 = time.time()

        try:
            r = await self._client.post(
                url, json=body, extensions=self._request_extensions()
            )
        except httpx.ConnectError as e:
            raise LlmError(f"Không kết nối được LLM server: {e}") from e
        except httpx.TimeoutException as e:
            raise LlmTimeoutError(
                f"Timeout sau {self.timeout}s khi gọi model={use_model}"
            ) from e

        latency = int((time.time() - t0) * 1000)

        if r.status_code == 401:
            raise LlmAuthError("API key không hợp lệ (401)")
        if r.status_code == 429:
            raise LlmRateLimitError(f"Rate limit: {r.text[:200]}")
        if r.status_code == 404:
            if self.fallback_model and use_model != self.fallback_model:
                logger.warning(
                    "Model %s not found (404), thử fallback %s",
                    use_model,
                    self.fallback_model,
                )
                return await self.chat(
                    messages,
                    model=self.fallback_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            raise LlmError(f"Model không tồn tại: {use_model}")
        if r.status_code >= 500:
            raise LlmError(f"LLM server lỗi {r.status_code}: {r.text[:300]}")
        if r.status_code >= 400:
            raise LlmError(f"LLM trả lỗi {r.status_code}: {r.text[:500]}")

        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise LlmError(f"Response không phải JSON: {r.text[:300]}") from e

        choices = data.get("choices") or []
        if not choices:
            raise LlmError(f"Response không có choices: {data}")

        choice0 = choices[0]
        message = choice0.get("message") or {}
        content = message.get("content") or ""
        finish_reason = choice0.get("finish_reason") or "stop"

        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens") or 0)
        out_tok = int(usage.get("completion_tokens") or 0)
        total_tok = int(usage.get("total_tokens") or (in_tok + out_tok))

        if not in_tok and not out_tok and content:
            in_tok = sum(_estimate_tokens(m.content) for m in messages)
            out_tok = _estimate_tokens(content)

        logger.info(
            "LLM chat: model=%s in=%d out=%d latency=%dms finish=%s",
            use_model,
            in_tok,
            out_tok,
            latency,
            finish_reason,
        )

        return LlmResponse(
            content=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=total_tok,
            model=use_model,
            finish_reason=finish_reason,
            latency_ms=latency,
        )

    async def test_connection(self) -> dict[str, Any]:
        """Test kết nối + gọi 1 câu nhỏ."""
        t0 = time.time()
        try:
            models = await self.list_models()
            test_resp = await self.chat(
                [
                    LlmMessage("system", "Bạn là AI assistant. Trả lời ngắn gọn."),
                    LlmMessage("user", "Trả lời đúng 1 từ: OK"),
                ],
                max_tokens=10,
                temperature=0.0,
            )
            latency = int((time.time() - t0) * 1000)
            return {
                "ok": True,
                "latency_ms": latency,
                "models": models,
                "test_response": test_resp.content[:100],
                "test_model": test_resp.model,
                "error": None,
            }
        except LlmError as e:
            latency = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "latency_ms": latency,
                "models": [],
                "error": str(e),
            }
        except Exception as e:  # noqa: BLE001
            latency = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "latency_ms": latency,
                "models": [],
                "error": f"{type(e).__name__}: {e}",
            }


# ── Helpers ──────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Ước lượng số token khi LLM không trả usage."""
    if not text:
        return 0
    cjk = sum(
        1
        for c in text
        if "\u4e00" <= c <= "\u9fff"
        or "\u3040" <= c <= "\u30ff"
        or "\uac00" <= c <= "\ud7af"
    )
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


def mask_api_key(api_key: str | None) -> str:
    """Mask API key: 'oll-***xyz' hoặc '(không đặt)'."""
    if not api_key:
        return "(không đặt)"
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}***{api_key[-4:]}"
