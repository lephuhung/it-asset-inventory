"""Tool registry + manifest đóng cho ChatAgent (Task 14 — spec F8/F9/R6).

Ba nhóm tool:

1. **Inventory** (`inventory_*`) — backend thực thi trên pool `chat_ro` (audit ở
   backend, T10). Agent chỉ chuyển tiếp; không tự chạm DB.
2. **Velociraptor server-side** (`list_clients`, `get_client_metadata`,
   `list_flows`, `get_flow_results`, `run_vql`) — chạy qua bridge MCP, **có audit
   intent trước + outcome sau** (F2). `run_vql` bắt buộc qua validator T13.
3. **Collection read-only** (`windows_pslist`, …) — manifest ĐÓNG: chỉ artifact
   built-in đã review, có `supported_platforms` + provenance. Agent **không**
   truyền parameters/fields; code sinh argument (pattern `mcp_client.py:339-358`).

**Canonical target identity (V3-5/V5/V6).** Resolve hostname → `client_id` bằng
API `SearchClients` của bridge với filter hostname exact, phân trang đầy đủ tới
`total`; ≥2 `client_id` phân biệt → ambiguity, 0 match / total thiếu / total đổi
giữa trang / phân trang không đủ → **fail closed** (`chat_collection_denied`).
Không bao giờ tự chọn.

**Trần số (F9/R6).** `collection_max_time_range_hours`,
`collection_flow_deadline_seconds`, `collection_max_rows`,
`collection_max_outstanding_per_client`, `collection_per_machine_per_hour`.
Helper nào không enforce được bound → fail closed.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from chatagent.backend_client import BackendClient
from chatagent.config import Settings
from chatagent.vql_policy import VQL_MAX_BYTES, validate_vql

CATEGORY_DENIED = "chat_collection_denied"

logger = logging.getLogger(__name__)

# ── Manifest ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BridgeToolSpec:
    """Schema tool mà bridge MCP khai báo (kiểm tra lúc khởi động)."""

    name: str
    input_schema: dict[str, Any] = field(default_factory=dict)


class McpBridge(Protocol):
    """Hợp đồng tối thiểu của bridge MCP (mcp-velociraptor) mà registry cần."""

    async def list_tools(self) -> dict[str, BridgeToolSpec]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ServerTool:
    """Tool Velociraptor server-side hoặc resolver."""

    name: str
    bridge_name: str
    arg_keys: frozenset[str]
    kind: str  # "read" | "vql" | "resolver"


@dataclass(frozen=True)
class CollectionArtifact:
    """Artifact collection built-in đã review (manifest đóng)."""

    name: str
    bridge_name: str
    supported_platforms: frozenset[str]
    provenance: str
    arg_keys: frozenset[str] = frozenset(
        {"client_id", "time_range_hours", "limit", "offset"}
    )


# Tool Velociraptor server-side — tên trùng bridge (spec F8).
SERVER_TOOLS: dict[str, ServerTool] = {
    "list_clients": ServerTool(
        "list_clients", "list_clients", frozenset({"hostname", "limit", "offset"}), "read"
    ),
    "get_client_metadata": ServerTool(
        "get_client_metadata", "get_client_metadata", frozenset({"client_id"}), "read"
    ),
    "list_flows": ServerTool(
        "list_flows", "list_flows", frozenset({"client_id", "limit", "offset"}), "read"
    ),
    "get_flow_results": ServerTool(
        "get_flow_results",
        "get_flow_results",
        frozenset({"client_id", "flow_id", "limit", "offset"}),
        "read",
    ),
    "run_vql": ServerTool("run_vql", "run_vql", frozenset({"query", "limit"}), "vql"),
    # Resolver nội bộ — chỉ dùng qua `resolve_client_id`, không cho model gọi trực tiếp.
    "search_clients": ServerTool(
        "search_clients",
        "search_clients",
        frozenset({"hostname", "exact", "limit", "offset"}),
        "resolver",
    ),
}

# Collection read-only — manifest ĐÓNG. Custom artifact bị loại trừ (F9/R6).
COLLECTION_MANIFEST: dict[str, CollectionArtifact] = {
    "windows_pslist": CollectionArtifact(
        "windows_pslist", "windows_pslist", frozenset({"windows"}), "builtin-reviewed"
    ),
    "windows_netstat_enriched": CollectionArtifact(
        "windows_netstat_enriched",
        "windows_netstat_enriched",
        frozenset({"windows"}),
        "builtin-reviewed",
    ),
    "windows_event_logs": CollectionArtifact(
        "windows_event_logs", "windows_event_logs", frozenset({"windows"}), "builtin-reviewed"
    ),
    "windows_execution_prefetch": CollectionArtifact(
        "windows_execution_prefetch",
        "windows_execution_prefetch",
        frozenset({"windows"}),
        "builtin-reviewed",
    ),
}

# Inventory tool — backend thực thi (structured + SQL ad-hoc).
INVENTORY_TOOLS: frozenset[str] = frozenset(
    {
        "inventory_search",
        "inventory_machine_detail",
        "inventory_resolve_machine",
        "inventory_stats",
        "inventory_software",
        "inventory_hardware",
        "inventory_alerts",
        "inventory_sql",
    }
)

# Tập tool bridge BẮT BUỘC phải có (fail-closed nếu thiếu).
REQUIRED_BRIDGE_TOOLS: frozenset[str] = frozenset(
    spec.bridge_name for spec in SERVER_TOOLS.values()
) | frozenset(spec.bridge_name for spec in COLLECTION_MANIFEST.values())


# ── Lỗi ──────────────────────────────────────────────────────────────────────


class ToolRegistryError(ValueError):
    """Lỗi catalog/registry — không có category (lỗi lập trình/khởi động)."""


class CollectionDeniedError(ToolRegistryError):
    """Fail-closed khi collection/resolve không chứng minh được an toàn."""

    category = CATEGORY_DENIED

    def __init__(self, hint: str) -> None:
        self.hint = hint
        super().__init__(f"[{CATEGORY_DENIED}] {hint}")


class CollectionFlowTimeoutError(CollectionDeniedError):
    """Collection vượt deadline flow — flow có thể vẫn chạy phía Velociraptor.

    Spec F9/R6: caller timeout KHÔNG phải flow-level guarantee; quá hạn → outcome
    `unknown`, **không** huỷ flow, và **không** giải phóng slot per-machine (vì flow
    chưa được xác minh terminal).
    """


# ── Kết quả ──────────────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    tool: str
    ok: bool
    rows: list[Any] = field(default_factory=list)
    row_count: int = 0
    byte_count: int = 0
    truncated: bool = False
    data: dict[str, Any] | None = None
    error_category: str | None = None
    client_id: str | None = None
    flow_id: str | None = None
    duration_ms: int = 0
    skipped: bool = False

    @classmethod
    def from_bridge(
        cls,
        tool: str,
        payload: dict[str, Any],
        settings: Settings,
        *,
        client_id: str | None,
        flow_id: str | None,
        duration_ms: int,
    ) -> ToolResult:
        rows = payload.get("rows")
        if not isinstance(rows, list):
            rows = []
        truncated = bool(payload.get("truncated", False))
        if len(rows) > settings.collection_max_rows:
            rows = rows[: settings.collection_max_rows]
            truncated = True
        serialized = json.dumps(rows, ensure_ascii=False, default=str)
        return cls(
            tool=tool,
            ok=bool(payload.get("ok", True)),
            rows=rows,
            row_count=len(rows),
            byte_count=len(serialized.encode("utf-8")),
            truncated=truncated,
            data=payload,
            error_category=payload.get("error_category"),
            client_id=client_id,
            flow_id=flow_id,
            duration_ms=duration_ms,
        )

    @classmethod
    def from_backend(cls, tool: str, payload: dict[str, Any]) -> ToolResult:
        rows = payload.get("rows")
        if not isinstance(rows, list):
            rows = []
        return cls(
            tool=tool,
            ok=bool(payload.get("ok", True)),
            rows=rows,
            row_count=int(payload.get("row_count", len(rows))),
            byte_count=int(payload.get("byte_count", 0)),
            truncated=bool(payload.get("truncated", False)),
            data=payload,
        )


@dataclass(frozen=True)
class ToolCallContext:
    """Danh tính thực thi của MỘT tool call (V5)."""

    capability: str
    turn_id: uuid.UUID
    tool_call_id: str


def args_digest(arguments: dict[str, Any]) -> str:
    """`sha256` của argument code-owned (canonical, sort_keys) — audit, không raw."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _enforce_byte_cap(result: ToolResult, max_bytes: int) -> None:
    """Fail closed khi kết quả vượt trần byte (spec F1 item 5).

    `run_vql` chỉ VQL server-side; byte cap enforce TẠI EXECUTOR, không chỉ ở
    validator — kết quả vượt trần bị từ chối thay vì trả về nguyên khối.
    """
    if result.byte_count > max_bytes:
        raise CollectionDeniedError(
            f"{result.tool}: kết quả vượt trần byte ({result.byte_count} > {max_bytes})"
        )


# ── Hostname / identity ──────────────────────────────────────────────────────


def normalize_hostname(hostname: Any) -> str:
    """Chuẩn hoá hostname hai phía (lowercase, trim, bỏ FQDN/trailing dot)."""
    if not isinstance(hostname, str):
        return ""
    value = hostname.strip().lower()
    while value.endswith("."):
        value = value[:-1]
    if "." in value:
        value = value.split(".", 1)[0]
    return value


def _validated_identity(item: Any, *, offset: int) -> tuple[str, str]:
    """Trích `(client_id, hostname)` từ một item SearchClients; fail closed nếu hỏng."""
    if not isinstance(item, dict):
        raise CollectionDeniedError(f"record SearchClients không phải object (offset {offset})")
    client_id = item.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise CollectionDeniedError(f"record thiếu client_id hợp lệ (offset {offset})")
    os_info = item.get("os_info")
    if not isinstance(os_info, dict):
        raise CollectionDeniedError(f"record thiếu os_info hợp lệ (offset {offset})")
    hostname = os_info.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        raise CollectionDeniedError(f"record thiếu hostname hợp lệ (offset {offset})")
    return client_id.strip(), normalize_hostname(hostname)


async def resolve_client_id(bridge: McpBridge, hostname: Any, *, settings: Settings) -> str:
    """Resolve hostname → đúng một `client_id` (V3-5/V5/V6) — fail closed.

    Không tự chọn khi mơ hồ: ≥2 `client_id` phân biệt, 0 match, `total` thiếu/đổi,
    phân trang không đủ, phân trang vượt `total`, record lặp giữa trang, hoặc vượt
    số trang/ngân sách thời gian resolve → `chat_collection_denied`.
    """
    target = normalize_hostname(hostname)
    if not target:
        raise CollectionDeniedError("hostname rỗng/không hợp lệ")

    deadline = time.monotonic() + settings.resolver_consistency_window_seconds
    found: set[str] = set()
    seen_ids: set[str] = set()
    offset = 0
    total: int | None = None
    pages = 0
    while True:
        if time.monotonic() > deadline:
            raise CollectionDeniedError(
                f"resolve hostname {target!r} vượt ngân sách thời gian "
                f"{settings.resolver_consistency_window_seconds}s"
            )
        if pages >= settings.resolver_max_pages:
            raise CollectionDeniedError(
                f"resolve hostname {target!r} vượt {settings.resolver_max_pages} trang"
            )
        payload = await bridge.call_tool(
            "search_clients",
            {
                "hostname": target,
                "exact": True,
                "limit": settings.resolver_page_size,
                "offset": offset,
            },
        )
        if not isinstance(payload, dict):
            raise CollectionDeniedError("SearchClients trả payload không hợp lệ")
        items = payload.get("items")
        if not isinstance(items, list):
            raise CollectionDeniedError("SearchClients thiếu `items` (phân trang không xác định)")
        if len(items) > settings.resolver_page_size:
            raise CollectionDeniedError(
                f"SearchClients trả trang vượt page_size {settings.resolver_page_size}"
            )
        page_total = payload.get("total")
        if isinstance(page_total, bool) or not isinstance(page_total, int) or page_total < 0:
            raise CollectionDeniedError("SearchClients thiếu `total` hợp lệ")
        if total is None:
            total = page_total
        elif page_total != total:
            raise CollectionDeniedError(
                f"`total` thay đổi giữa các trang ({total} → {page_total})"
            )
        if page_total == 0 and items:
            raise CollectionDeniedError("total=0 nhưng items không rỗng")
        if offset + len(items) > page_total:
            raise CollectionDeniedError(
                f"trang vượt `total` (offset {offset} + {len(items)} > {page_total})"
            )
        for item in items:
            client_id, item_hostname = _validated_identity(item, offset=offset)
            if client_id in seen_ids:
                raise CollectionDeniedError(
                    f"record lặp giữa các trang (client_id {client_id!r})"
                )
            seen_ids.add(client_id)
            if item_hostname == target:
                found.add(client_id)
        pages += 1
        offset += len(items)
        if offset >= total:
            break
        if not items:
            raise CollectionDeniedError(
                f"phân trang dừng sớm (offset {offset} < total {total})"
            )

    if len(found) > 1:
        raise CollectionDeniedError(
            f"hostname {target!r} khớp nhiều client_id: {sorted(found)}"
        )
    if not found:
        raise CollectionDeniedError(f"không tìm thấy client cho hostname {target!r}")
    return next(iter(found))


# ── Trần số ──────────────────────────────────────────────────────────────────


def enforce_time_range_hours(value: Any, settings: Settings) -> int:
    """Chuẩn hoá + enforce `chat_collection_max_time_range_hours` (fail closed)."""
    maximum = settings.collection_max_time_range_hours
    if value is None:
        return maximum
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CollectionDeniedError(f"time_range_hours không hợp lệ: {value!r}")
    hours = int(value)
    if hours < 1 or hours > maximum:
        raise CollectionDeniedError(
            f"time_range_hours {hours} ngoài khoảng 1..{maximum}"
        )
    return hours


class CollectionRateLimiter:
    """Trần đồng thời + trần/giờ theo `client_id` (spec F9/R6)."""

    def __init__(
        self,
        *,
        max_outstanding_per_client: int,
        per_machine_per_hour: int,
        clock: Callable[[], float] = time.monotonic,
        window_seconds: float = 3600.0,
    ) -> None:
        self._max_outstanding = max_outstanding_per_client
        self._per_hour = per_machine_per_hour
        self._clock = clock
        self._window = window_seconds
        self._outstanding: dict[str, int] = {}
        self._history: dict[str, list[float]] = {}

    def try_acquire(self, client_id: str) -> None:
        self._prune(client_id)
        if self._outstanding.get(client_id, 0) >= self._max_outstanding:
            raise CollectionDeniedError(
                f"client {client_id}: vượt trần {self._max_outstanding} collection đồng thời"
            )
        if len(self._history.get(client_id, [])) >= self._per_hour:
            raise CollectionDeniedError(
                f"client {client_id}: vượt trần {self._per_hour} collection/giờ"
            )
        self._outstanding[client_id] = self._outstanding.get(client_id, 0) + 1
        self._history.setdefault(client_id, []).append(self._clock())

    def release(self, client_id: str) -> None:
        current = self._outstanding.get(client_id, 0)
        if current > 0:
            self._outstanding[client_id] = current - 1

    def _prune(self, client_id: str) -> None:
        cutoff = self._clock() - self._window
        self._history[client_id] = [
            ts for ts in self._history.get(client_id, []) if ts >= cutoff
        ]


# ── Registry ─────────────────────────────────────────────────────────────────


class ToolRegistry:
    """Dispatch tool call → inventory (backend) hoặc Velociraptor (bridge, audited)."""

    def __init__(
        self,
        *,
        bridge: McpBridge,
        backend: BackendClient,
        settings: Settings,
        rate_limiter: CollectionRateLimiter | None = None,
    ) -> None:
        self._bridge = bridge
        self._backend = backend
        self._settings = settings
        self.rate_limiter = rate_limiter or CollectionRateLimiter(
            max_outstanding_per_client=settings.collection_max_outstanding_per_client,
            per_machine_per_hour=settings.collection_per_machine_per_hour,
        )

    def tool_names(self) -> list[str]:
        return sorted(set(INVENTORY_TOOLS) | set(COLLECTION_MANIFEST) | set(SERVER_TOOLS))

    async def run(
        self, ctx: ToolCallContext, tool: str, params: dict[str, Any]
    ) -> ToolResult:
        if tool in INVENTORY_TOOLS:
            return await self._run_inventory(ctx, tool, params)
        if tool in COLLECTION_MANIFEST:
            return await self._run_collection(ctx, tool, params)
        spec = SERVER_TOOLS.get(tool)
        if spec is not None and spec.kind != "resolver":
            return await self._run_server(ctx, spec, params)
        raise ToolRegistryError(f"tool không nằm trong catalog: {tool!r}")

    # ── Inventory: backend thực thi + audit (T10) ────────────────────────────

    async def _run_inventory(
        self, ctx: ToolCallContext, tool: str, params: dict[str, Any]
    ) -> ToolResult:
        if tool == "inventory_sql":
            sql = params.get("sql")
            if not isinstance(sql, str) or not sql.strip():
                raise ToolRegistryError("inventory_sql cần `sql` (string)")
            payload = await self._backend.inventory_sql(capability=ctx.capability, sql=sql)
        else:
            payload = await self._backend.inventory_query(
                capability=ctx.capability, tool=tool, params=dict(params)
            )
        return ToolResult.from_backend(tool, payload)

    # ── Collection: resolve → audit intent → bridge → audit outcome ──────────

    async def _run_collection(
        self, ctx: ToolCallContext, tool: str, params: dict[str, Any]
    ) -> ToolResult:
        artifact = COLLECTION_MANIFEST[tool]
        client_id = await resolve_client_id(
            self._bridge, params.get("hostname"), settings=self._settings
        )
        time_range_hours = enforce_time_range_hours(
            params.get("time_range_hours"), self._settings
        )
        self.rate_limiter.try_acquire(client_id)
        flow_may_be_running = False
        try:
            # Argument do CODE sinh — model không thể đặt parameters/fields/pagination.
            arguments: dict[str, Any] = {
                "client_id": client_id,
                "time_range_hours": time_range_hours,
                "limit": self._settings.collection_max_rows,
                "offset": 0,
            }
            # Collection dùng deadline riêng (spec F9/R6); vượt hạn → outcome `unknown`,
            # KHÔNG huỷ flow. `_audited_call` map timeout → `CollectionFlowTimeoutError`.
            return await self._audited_call(
                ctx,
                tool=tool,
                bridge_name=artifact.bridge_name,
                arguments=arguments,
                client_id=client_id,
                flow_id=None,
                deadline_seconds=float(self._settings.collection_flow_deadline_seconds),
                manifest_platforms=artifact.supported_platforms,
            )
        except CollectionFlowTimeoutError:
            # Flow có thể vẫn chạy phía Velociraptor → KHÔNG giải phóng slot
            # per-machine (spec F9/R6: chưa xác minh terminal thì fail closed cho
            # collection kế tiếp). Reconciliation sẽ đóng outcome `unknown`.
            flow_may_be_running = True
            raise
        finally:
            if not flow_may_be_running:
                self.rate_limiter.release(client_id)

    # ── Server-side Velociraptor tools ───────────────────────────────────────

    async def _run_server(
        self, ctx: ToolCallContext, spec: ServerTool, params: dict[str, Any]
    ) -> ToolResult:
        client_id = params.get("client_id")
        flow_id = params.get("flow_id")
        if spec.kind == "vql":
            query = params.get("query")
            validate_vql(query)  # T13 — raise VqlPolicyError trước khi làm gì khác
            arguments: dict[str, Any] = {
                "query": query,
                "limit": self._settings.collection_max_rows,
            }
        else:
            arguments = self._read_arguments(spec, params)
        result = await self._audited_call(
            ctx,
            tool=spec.name,
            bridge_name=spec.bridge_name,
            arguments=arguments,
            client_id=client_id if isinstance(client_id, str) else None,
            flow_id=flow_id if isinstance(flow_id, str) else None,
            deadline_seconds=float(self._settings.collection_flow_deadline_seconds),
        )
        if spec.kind == "vql":
            # Trần byte VQL enforce tại executor (không chỉ validator) — spec F1 item 5.
            _enforce_byte_cap(result, VQL_MAX_BYTES)
        return result

    @staticmethod
    def _read_arguments(spec: ServerTool, params: dict[str, Any]) -> dict[str, Any]:
        """Chỉ đọc các key allowlist; bỏ mọi thứ model tự thêm."""
        arguments: dict[str, Any] = {}
        for key in spec.arg_keys:
            if key in params:
                arguments[key] = params[key]
        arguments.setdefault("offset", 0)
        return arguments

    # ── Audit wrapper ────────────────────────────────────────────────────────

    async def _audited_call(
        self,
        ctx: ToolCallContext,
        *,
        tool: str,
        bridge_name: str,
        arguments: dict[str, Any],
        client_id: str | None,
        flow_id: str | None,
        deadline_seconds: float | None = None,
        manifest_platforms: frozenset[str] | None = None,
    ) -> ToolResult:
        """Intent TRƯỚC khi chạy (fail → không chạy); outcome SAU (kể cả lỗi/hủy).

        CancelledError/timeout ghi outcome `canceled`/`unknown` (KHÔNG phải `ok`).
        `flow_id` thực tế do bridge báo được forward vào outcome (spec F2).
        """
        digest = args_digest(arguments)
        intent = await self._backend.audit_intent(
            capability=ctx.capability,
            tool_call_id=ctx.tool_call_id,
            tool=tool,
            args_digest=digest,
            client_id=client_id,
            flow_id=flow_id,
        )
        if not intent.get("executed", True):
            # Trùng `(turn_id, tool_call_id)` + identity đầy đủ → KHÔNG chạy lại (V5).
            return ToolResult(
                tool=tool, ok=True, skipped=True, client_id=client_id, flow_id=flow_id
            )

        started = time.monotonic()
        # Mặc định `unknown`: CHỈ đổi thành `ok` khi lời gọi chứng minh đã hoàn tất
        # thành công. Mọi nhánh lỗi/hủy/quá hạn đặt giá trị riêng trước `finally`.
        outcome = "unknown"
        result_flow_id = flow_id
        try:
            if deadline_seconds is not None:
                payload = await asyncio.wait_for(
                    self._bridge.call_tool(bridge_name, arguments), timeout=deadline_seconds
                )
            else:
                payload = await self._bridge.call_tool(bridge_name, arguments)
            duration_ms = int((time.monotonic() - started) * 1000)
            if not isinstance(payload, dict):
                outcome = "error"
                raise CollectionDeniedError(f"{tool}: bridge trả payload không hợp lệ")
            if not payload.get("ok", True):
                outcome = "error"
            else:
                outcome = "ok"
            reported_flow_id = payload.get("flow_id")
            if isinstance(reported_flow_id, str) and reported_flow_id:
                result_flow_id = reported_flow_id
            if manifest_platforms is not None:
                platform = payload.get("platform")
                if isinstance(platform, str) and platform and platform not in manifest_platforms:
                    outcome = "error"
                    raise CollectionDeniedError(
                        f"{tool}: platform {platform!r} không nằm trong "
                        f"{sorted(manifest_platforms)}"
                    )
            return ToolResult.from_bridge(
                tool,
                payload,
                self._settings,
                client_id=client_id,
                flow_id=result_flow_id,
                duration_ms=duration_ms,
            )
        except asyncio.CancelledError:
            # Hủy turn: outcome KHÔNG được là `ok` (spec F2/R2).
            outcome = "canceled"
            raise
        except TimeoutError as exc:
            # Quá deadline: flow giữ nguyên, outcome `unknown` (spec F9/R6).
            # Ném `CollectionFlowTimeoutError` để `_run_collection` giữ slot
            # per-machine (flow chưa được xác minh terminal).
            outcome = "unknown"
            raise CollectionFlowTimeoutError(
                f"{tool}: vượt deadline flow {deadline_seconds}s (flow giữ nguyên)"
            ) from exc
        except BaseException:
            outcome = "error"
            raise
        finally:
            # Best-effort: lỗi audit không che lỗi gốc/hủy; vẫn ghi flow_id/client thực.
            with contextlib.suppress(Exception):
                await self._backend.audit_outcome(
                    turn_id=ctx.turn_id,
                    tool_call_id=ctx.tool_call_id,
                    outcome=outcome,
                    client_id=client_id,
                    flow_id=result_flow_id,
                )


async def build_tools(
    bridge: McpBridge, backend: BackendClient, settings: Settings
) -> ToolRegistry:
    """Dựng registry + kiểm tra schema bridge lúc khởi động (fail-closed).

    Thiếu tool bắt buộc, hoặc code-owned argument không nằm trong schema bridge khi
    bridge khai `additionalProperties=false` → `ToolRegistryError`.
    """
    specs = await bridge.list_tools()
    missing = REQUIRED_BRIDGE_TOOLS - set(specs)
    if missing:
        raise ToolRegistryError(f"bridge thiếu tool bắt buộc: {sorted(missing)}")

    declared: dict[str, frozenset[str]] = {}
    for spec in SERVER_TOOLS.values():
        declared[spec.bridge_name] = spec.arg_keys
    for artifact in COLLECTION_MANIFEST.values():
        declared[artifact.bridge_name] = artifact.arg_keys

    for name, arg_keys in declared.items():
        bridge_spec = specs[name]
        schema = bridge_spec.input_schema or {}
        additional = schema.get("additionalProperties", True)
        if additional is False:
            properties = frozenset((schema.get("properties") or {}).keys())
            if not arg_keys.issubset(properties):
                raise ToolRegistryError(
                    f"schema bridge không khớp cho {name!r}: cần {sorted(arg_keys)}, "
                    f"có {sorted(properties)}"
                )
    return ToolRegistry(bridge=bridge, backend=backend, settings=settings)
