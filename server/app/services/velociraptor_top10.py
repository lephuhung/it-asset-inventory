"""Trích xuất Top N sự kiện / log gần nhất cho từng Artifact DFIR trên 1 client.

Chuyển thể từ script ``Velociraptor Top 10 DFIR Events Extractor`` — tự động chọn
artifact phù hợp với OS của endpoint (Windows /  Linux / macOS):

  Windows:
  - ``Windows.Forensics.Prefetch``  — Top N binary được thực thi gần nhất
    (sort theo ModificationTime desc — giống script gốc)
  - ``Windows.Network.Netstat``      — Top N socket / cổng mạng đang mở
  - ``Windows.System.Pslist``        — Top N tiến trình hệ thống đang chạy

  Linux:
  - ``Linux.Sys.Pslist``             — Top N tiến trình hệ thống đang chạy
  - ``Linux.Network.NetstatEnriched``— Top N kết nối mạng / cổng đang mở
  - ``Linux.Sys.LastUserLogin``      — Top N phiên đăng nhập gần nhất

  macOS (Darwin):
  - ``MacOS.Sys.Pslist``             — Top N tiến trình hệ thống đang chạy
  - ``MacOS.Network.Netstat``        — Top N kết nối mạng / cổng đang mở

Quy trình mỗi artifact (khớp script):
  1. ``find_latest_finished_flow`` — tìm flow FINISHED gần nhất đã chạy artifact
     (GetClientFlows — Velociraptor trả mới nhất trước) → **tái sử dụng dữ liệu**,
     không collect lại.
  2. Nếu chưa có flow FINISHED nhưng đang có flow RUNNING → báo ``running``.
  3. ``collect_artifact_and_wait`` — CollectArtifact + poll GetFlowDetails
     tới khi FINISHED (chỉ khi ``collect_missing=True`` — endpoint collect riêng).
  4. ``get_table`` (GetTable) → Top N rows (sort theo spec của từng artifact).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.velociraptor import VelociraptorError

# Bộ artifact cho tính năng "Top 10 DFIR events" — thứ tự = thứ tự hiển thị.
# Mỗi OS có bộ artifact phù hợp (chỉ thu thập artifact khả dụng trên hệ đó):
#   - Windows: Prefetch / Netstat / Pslist
#   - Linux:   Pslist / NetstatEnriched / LastUserLogin
#   - macOS:   Pslist / Netstat
# `sort`: key dùng sort desc (None = giữ thứ tự Velociraptor trả về).
TOP10_ARTIFACTS_WINDOWS: list[dict[str, Any]] = [
    {
        "artifact": "Windows.Forensics.Prefetch",
        "label": "Prefetch — Top 10 binary được thực thi gần nhất",
        "sort": "ModificationTime",
    },
    {
        "artifact": "Windows.Network.Netstat",
        "label": "Netstat — Top 10 kết nối mạng / cổng đang mở",
        "sort": None,
    },
    {
        "artifact": "Windows.System.Pslist",
        "label": "Pslist — Top 10 tiến trình hệ thống",
        "sort": None,
    },
]

TOP10_ARTIFACTS_LINUX: list[dict[str, Any]] = [
    {
        "artifact": "Linux.Sys.Pslist",
        "label": "Pslist — Top 10 tiến trình hệ thống",
        "sort": None,
    },
    {
        "artifact": "Linux.Network.NetstatEnriched",
        "label": "Netstat — Top 10 kết nối mạng / cổng đang mở",
        "sort": None,
    },
    {
        "artifact": "Linux.Sys.LastUserLogin",
        "label": "Đăng nhập — Top 10 phiên đăng nhập gần nhất",
        "sort": None,
    },
]

TOP10_ARTIFACTS_DARWIN: list[dict[str, Any]] = [
    {
        "artifact": "MacOS.Sys.Pslist",
        "label": "Pslist — Top 10 tiến trình hệ thống",
        "sort": None,
    },
    {
        "artifact": "MacOS.Network.Netstat",
        "label": "Netstat — Top 10 kết nối mạng / cổng đang mở",
        "sort": None,
    },
]

# Giữ tên cũ cho tương thích (mặc định = Windows; có thể đổi qua `_top10_artifacts_for`).
TOP10_ARTIFACTS: list[dict[str, Any]] = TOP10_ARTIFACTS_WINDOWS


def _top10_artifacts_for(system: str | None) -> list[dict[str, Any]]:
    """Chọn bộ artifact Top10 phù hợp với OS của client.

    - ``linux``  → bộ Linux (Pslist / NetstatEnriched / LastUserLogin).
    - ``darwin`` → bộ macOS (Pslist / Netstat).
    - còn lại (windows + không xác định) → bộ Windows (mặc định, giữ hành vi cũ).
    """
    s = (system or "").strip().lower()
    if s == "linux":
        return TOP10_ARTIFACTS_LINUX
    if s in ("darwin", "macos", "osx", "mac"):
        return TOP10_ARTIFACTS_DARWIN
    return TOP10_ARTIFACTS_WINDOWS


async def _client_system(velo: Any, client_id: str) -> str | None:
    """Lấy OS của client (vd 'windows' | 'linux' | 'darwin').

    Gọi Velociraptor metadata một lần; nếu lỗi hoặc thiếu OS → None
    (lúc đó rơi về bộ artifact Windows mặc định).
    """
    try:
        meta = await velo.get_client_metadata(client_id)
        return ((meta or {}).get("os_info") or {}).get("system")
    except Exception:  # noqa: BLE001 — OS không xác định → dùng bộ mặc định
        return None


def _find_flow_by_artifact(flows: list[dict], artifact: str) -> dict | None:
    """Flow đầu tiên (mới nhất trước) có chạy artifact này."""
    for f in flows:
        artifacts = f.get("Artifacts") or []
        if artifact in artifacts:
            return f
    return None


def _top_rows(table: list[dict], spec: dict, top_n: int) -> tuple[list[dict], int]:
    """Sort + cắt Top N rows cho 1 artifact (sort desc nếu spec có `sort`)."""
    total = len(table)
    sort_key = spec.get("sort")
    if sort_key:
        table = sorted(
            table, key=lambda r: str(r.get(sort_key) or ""), reverse=True
        )
    return table[:top_n], total


async def extract_top10(
    velo: Any,
    client_id: str,
    *,
    collect_missing: bool = False,
    top_n: int = 10,
    rows: int = 100,
    collect_timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Trích xuất Top N sự kiện cho từng artifact trên 1 Velociraptor client.

    Args:
        velo: VelociraptorClient instance (đang mở `async with`).
        client_id: Velociraptor client_id (C.xxxx).
        collect_missing: True → collect artifact chưa có flow FINISHED
            (đồng bộ, có thể mất tới collect_timeout_seconds). False → chỉ đọc.
        top_n: số dòng hiển thị mỗi artifact.
        rows: số rows đọc tối đa từ Velociraptor (cap khi parse Top N).
        collect_timeout_seconds: cap thời gian chờ flow FINISHED khi collect.

    Returns dict:
        {
          "client_id", "generated_at",
          "artifacts": [{artifact, label, flow_id, source, rows, total_rows, error?}],
          "flows": list top_n flows gần nhất,
        }
        source: "reused" | "running" | "collected" | "missing" | "error"
    """
    # Chọn đúng bộ artifact theo OS của client (Windows / Linux / macOS).
    system = await _client_system(velo, client_id)
    specs = _top10_artifacts_for(system)

    flows = await velo.list_client_flows(client_id, limit=max(50, rows))
    artifacts_out: list[dict[str, Any]] = []

    for spec in specs:
        artifact = spec["artifact"]
        entry: dict[str, Any] = {
            "artifact": artifact,
            "label": spec["label"],
            "flow_id": None,
            "source": "missing",
            "rows": [],
            "total_rows": 0,
        }
        flow = _find_flow_by_artifact(flows, artifact)

        if flow is not None and flow.get("State") == "FINISHED":
            entry["source"] = "reused"
            entry["flow_id"] = flow.get("FlowId")
            try:
                table = await velo.get_table(
                    client_id, flow["FlowId"], artifact, rows=rows
                )
                entry["rows"], entry["total_rows"] = _top_rows(table, spec, top_n)
            except VelociraptorError as e:
                entry["source"] = "error"
                entry["error"] = str(e)
        elif flow is not None:
            # Đang có flow chạy artifact này (chưa xong) — không collect lại.
            entry["source"] = "running"
            entry["flow_id"] = flow.get("FlowId")
        elif collect_missing:
            try:
                flow_id = await velo.collect_artifact_and_wait(
                    client_id,
                    artifact,
                    timeout_seconds=collect_timeout_seconds,
                )
                entry["source"] = "collected"
                entry["flow_id"] = flow_id
                table = await velo.get_table(client_id, flow_id, artifact, rows=rows)
                entry["rows"], entry["total_rows"] = _top_rows(table, spec, top_n)
            except VelociraptorError as e:
                entry["source"] = "error"
                entry["error"] = str(e)

        artifacts_out.append(entry)

    return {
        "client_id": client_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": artifacts_out,
        "flows": flows[:top_n],
    }


async def collect_missing_top10(
    velo: Any,
    client_id: str,
    allowlist: list[str],
) -> dict[str, Any]:
    """Kick-off collect các artifact chưa có flow FINISHED (không chờ xong).

    Gọi cho endpoint ``POST /clients/{client_id}/top10/collect`` — trả về ngay,
    portal poll ``GET /top10`` tới khi flow FINISHED rồi đọc Top N.

    Args:
        velo: VelociraptorClient instance (đang mở).
        client_id: Velociraptor client_id.
        allowlist: allowlist artifact đang hiệu lực (chặn collect ngoài allowlist).

    Returns dict:
        {"client_id", "started_at",
         "artifacts": [{artifact, label, status, flow_id, error?}]}
        status: "reused" (đã có flow FINISHED — không collect)
                | "collecting" (CollectArtifact đã gửi)
                | "not_allowed" (ngoài allowlist — 403 tầng route)
                | "error"
    """
    # Chọn đúng bộ artifact theo OS của client.
    system = await _client_system(velo, client_id)
    specs = _top10_artifacts_for(system)

    flows = await velo.list_client_flows(client_id, limit=50)
    out: list[dict[str, Any]] = []

    for spec in specs:
        artifact = spec["artifact"]
        entry: dict[str, Any] = {
            "artifact": artifact,
            "label": spec["label"],
            "status": "missing",
            "flow_id": None,
        }
        if artifact not in allowlist:
            entry["status"] = "not_allowed"
            out.append(entry)
            continue

        flow = _find_flow_by_artifact(flows, artifact)
        if flow is not None and flow.get("State") == "FINISHED":
            entry["status"] = "reused"
            entry["flow_id"] = flow.get("FlowId")
        else:
            try:
                flow_id = await velo.collect_artifact(client_id, [artifact])
                entry["status"] = "collecting"
                entry["flow_id"] = flow_id
            except VelociraptorError as e:
                entry["status"] = "error"
                entry["error"] = str(e)
        out.append(entry)

    return {
        "client_id": client_id,
        "started_at": datetime.now(UTC).isoformat(),
        "artifacts": out,
    }
