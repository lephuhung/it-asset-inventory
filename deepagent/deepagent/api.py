from __future__ import annotations

import asyncio
import hmac
import json
import os
import tempfile
from datetime import UTC, datetime
from time import perf_counter

from fastapi import Depends, FastAPI, Header, HTTPException, status

from deepagent.analysis_model import OpenAIAnalysisModel
from deepagent.callback import BackendCallbackClient
from deepagent.config import Settings, get_settings
from deepagent.mcp_client import VelociraptorMCP
from deepagent.models import (
    CallbackPayload,
    InvestigationRequest,
    JobStatus,
    McpTestRequest,
    McpTestResult,
)
from deepagent.observability import investigation_context, log_event, safe_error_detail
from deepagent.runner import InvestigationRunner

app = FastAPI(title="DeepAgent DFIR", version="0.1.0")
_jobs: dict[str, JobStatus] = {}
_tasks: set[asyncio.Task] = set()
_semaphore: asyncio.Semaphore | None = None


def _auth(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = f"Bearer {settings.service_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")


async def _execute(request: InvestigationRequest, job_id: str, settings: Settings) -> None:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
    sensitive_values = (
        request.llm_runtime.api_key,
        request.velociraptor_api_client_yaml,
        request.suspicious_activity,
        request.llm_runtime.system_prompt or "",
    )
    with investigation_context(
        investigation_id=str(request.investigation_id),
        job_id=job_id,
        sensitive_values=sensitive_values,
    ):
        async with _semaphore:
            job = _jobs[job_id]
            job.status = "running"
            callback = BackendCallbackClient(settings)
            api_client_path: str | None = None
            runner: InvestigationRunner | None = None
            started_at = perf_counter()
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".yaml", delete=False
                ) as handle:
                    handle.write(request.velociraptor_api_client_yaml)
                    api_client_path = handle.name
                mcp_env = settings.mcp_env()
                mcp_env["VELOCIRAPTOR_API_CONFIG"] = api_client_path
                job_settings = settings.model_copy(update={"mcp_env_json": json.dumps(mcp_env)})
                runner = InvestigationRunner(
                    settings=job_settings,
                    mcp=VelociraptorMCP(job_settings),
                    model=OpenAIAnalysisModel(request.llm_runtime),
                    callback=callback,
                )
                await runner.run(request, job_id)
                job.status = "completed"
            except Exception as exc:  # noqa: BLE001 - trả trạng thái lỗi cho job async
                job.status = "failed"
                job.error = safe_error_detail(exc, sensitive_values)
                if runner is None:
                    log_event(
                        phase="job_summary",
                        outcome="failed",
                        duration_ms=(perf_counter() - started_at) * 1000,
                        model=request.llm_runtime.model,
                        successful_tool_count=0,
                        failed_tool_count=0,
                        total_duration_ms=int((perf_counter() - started_at) * 1000),
                        error=exc,
                    )
                # Không để backend treo vĩnh viễn ở trạng thái analyzing khi MCP,
                # model hoặc callback bước thành công gặp sự cố trước đó.
                fallback_started_at = perf_counter()
                try:
                    await callback.submit(
                        str(request.investigation_id),
                        CallbackPayload(
                            report_markdown=(
                                f"# Điều tra thất bại: {request.hostname}\n\n"
                                "DeepAgent không thể hoàn tất truy vấn. Xem trường lỗi của "
                                "investigation để biết chi tiết vận hành.\n"
                            ),
                            severity="info",
                            findings_count=0,
                            findings=[],
                            iocs=[],
                            llm_model=settings.llm_model,
                            external_job_id=job_id,
                            error=job.error,
                            raw_response={"workflow": "bounded-langgraph-v1", "phase": "failed"},
                        ),
                    )
                except Exception as callback_exc:  # noqa: BLE001 - callback must not fail job cleanup
                    log_event(
                        phase="backend_result_callback_fallback",
                        outcome="failed",
                        duration_ms=(perf_counter() - fallback_started_at) * 1000,
                        error=callback_exc,
                    )
            finally:
                if api_client_path:
                    try:
                        os.unlink(api_client_path)
                    except FileNotFoundError:
                        pass
                job.completed_at = datetime.now(UTC)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": "deepagent-dfir"}


@app.post("/v1/mcp/test", response_model=McpTestResult, dependencies=[Depends(_auth)])
async def test_mcp_connection(
    request: McpTestRequest, settings: Settings = Depends(get_settings)
) -> McpTestResult:
    """Safe diagnostic: nạp MCP tools và gọi list_clients tối đa một row."""
    api_client_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".yaml", delete=False
        ) as handle:
            handle.write(request.velociraptor_api_client_yaml)
            api_client_path = handle.name
        mcp_env = settings.mcp_env()
        mcp_env["VELOCIRAPTOR_API_CONFIG"] = api_client_path
        test_settings = settings.model_copy(update={"mcp_env_json": json.dumps(mcp_env)})
        result = await VelociraptorMCP(test_settings).test_connection()
        return McpTestResult(ok=True, **result)
    except Exception as exc:  # noqa: BLE001 - trả diagnostics vận hành, không lộ secrets
        return McpTestResult(
            ok=False,
            error=safe_error_detail(exc, (request.velociraptor_api_client_yaml,)),
        )
    finally:
        if api_client_path:
            try:
                os.unlink(api_client_path)
            except FileNotFoundError:
                pass


@app.post(
    "/v1/investigations",
    response_model=JobStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_auth)],
)
async def create_investigation(
    request: InvestigationRequest, settings: Settings = Depends(get_settings)
) -> JobStatus:
    # investigation_id là idempotency scope: không xếp thêm job nếu backend retry.
    for job in _jobs.values():
        if job.investigation_id == request.investigation_id:
            return job
    # Stable per-investigation ID lets Backend recover/retry after an API restart
    # without creating a second job identity for the same investigation.
    job_id = f"deepagent-{request.investigation_id}"
    job = JobStatus(
        job_id=job_id,
        investigation_id=request.investigation_id,
        status="queued",
        created_at=datetime.now(UTC),
    )
    _jobs[job_id] = job
    task = asyncio.create_task(_execute(request, job_id, settings))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


@app.get(
    "/v1/jobs/{job_id}",
    response_model=JobStatus,
    dependencies=[Depends(_auth)],
)
async def get_job(job_id: str) -> JobStatus:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job không tồn tại")
    return job
