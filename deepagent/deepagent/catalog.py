from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    description: str
    uses_time_range: bool = False


# Chỉ gồm helper thu thập read-only từ mcp-velociraptor. Không đưa run_vql,
# hunt, collect_file, collect_artifact, YARA, quarantine hay kill_process vào graph.
#
# M-4 fix: windows_event_logs is in the allowlist so it survives plan sanitization,
# but the graph MUST route it exclusively through the typed bounded triage/detail
# APIs (collect_event_log_triage / collect_event_log_detail). The graph detects
# windows_event_logs steps and routes them to the typed helpers; routing through
# generic collect() would bypass the 100-row cap and VQL LIMIT. See graph.py
# collect_step() which enforces this routing.
WINDOWS_TOOL_POLICIES: dict[str, ToolPolicy] = {
    "windows_pslist": ToolPolicy("Tiến trình đang chạy và command line"),
    "windows_netstat_enriched": ToolPolicy("Kết nối mạng gắn với tiến trình"),
    "windows_services": ToolPolicy("Dịch vụ và binary thực thi"),
    "windows_scheduled_tasks": ToolPolicy("Scheduled task và persistence"),
    "windows_autoruns": ToolPolicy("Điểm tự khởi động"),
    "windows_wmi_persistence": ToolPolicy("WMI permanent event persistence"),
    "windows_event_logs": ToolPolicy("Windows event log theo khoảng thời gian", True),
    "windows_event_log_cleared": ToolPolicy("Dấu hiệu xóa event log", True),
    "windows_powershell_scriptblock": ToolPolicy("PowerShell 4104 theo thời gian", True),
    "windows_execution_prefetch": ToolPolicy("Bằng chứng thực thi Prefetch"),
    "windows_execution_amcache": ToolPolicy("Bằng chứng thực thi Amcache"),
    "windows_execution_userassist": ToolPolicy("Bằng chứng thực thi UserAssist"),
    "windows_execution_shimcache": ToolPolicy("Dấu vết ShimCache"),
    "windows_logon_events": ToolPolicy("Phiên đăng nhập Windows"),
    "windows_dns_cache": ToolPolicy("DNS cache hiện tại"),
}

BASELINE_TOOLS = (
    "windows_pslist",
    "windows_netstat_enriched",
    "windows_services",
    "windows_scheduled_tasks",
    "windows_event_logs",
    "windows_powershell_scriptblock",
)


def catalog_prompt() -> str:
    return "\n".join(
        f"- {name}: {policy.description}" for name, policy in WINDOWS_TOOL_POLICIES.items()
    )
