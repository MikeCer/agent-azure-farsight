import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from .auth import WorkloadCaller, require_workload_caller
from .clients import FarSightApiClient
from .models import (
    ApprovalToolRequest,
    ArtifactDownloadRequest,
    ArtifactContentRequest,
    ArtifactMetadataRequest,
    DiagnosticJobRequest,
    FollowUpRequest,
    InvestigationHistoryRequest,
    JobLookupRequest,
    ToolResponse,
    ZipArtifactEntryRequest,
)
from .policy import PolicyConfigurationError
from .tools import (
    create_diagnostic_job,
    download_artifact_file,
    get_job_result_summary,
    get_job_status,
    query_device_investigation_history,
    request_approval_for_action,
    request_follow_up_module_execution,
    retrieve_artifact_content,
    retrieve_artifact_metadata,
    extract_zip_artifact_entry,
)

logger = logging.getLogger("farsight.gateway")

app = FastAPI(title="FarSight AGT Tool Gateway", version="0.1.0")


@app.exception_handler(PolicyConfigurationError)
async def policy_configuration_error_handler(request: Request, exc: PolicyConfigurationError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": "policy_configuration_error",
            "message": str(exc),
            "hint": "Set FARSIGHT_ALLOW_POLICY_FALLBACK=true to use the built-in fallback policy evaluator.",
        },
    )


async def _emit_tool_call_event(response: ToolResponse, caller: WorkloadCaller) -> None:
    """Fire-and-forget: post a tool-call audit event to the FarSight API."""
    try:
        event = {
            "id": f"tc-{uuid4()}",
            "eventType": "tool-call",
            "toolName": response.tool_name,
            "decision": response.policy.outcome.value,
            "policyName": response.policy.policy_name,
            "policyVersion": response.policy.policy_version,
            "ruleName": response.policy.rule_name,
            "reason": response.policy.reason,
            "actorId": caller.object_id,
            "actorAppId": caller.app_id,
            "jobId": response.data.get("jobId"),
            "correlationId": response.data.get("correlationId"),
            "timestampUtc": datetime.now(timezone.utc).isoformat(),
        }
        client = FarSightApiClient()
        await client.request("POST", "/api/v1/telemetry/tool-calls", json=event)
    except Exception as exc:
        logger.warning("Failed to emit tool-call telemetry: %s", exc)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-tool-gateway"}


@app.post("/tools/create_diagnostic_job", response_model=ToolResponse)
async def create_diagnostic_job_endpoint(
    request: DiagnosticJobRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await create_diagnostic_job(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/get_job_status", response_model=ToolResponse)
async def get_job_status_endpoint(
    request: JobLookupRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await get_job_status(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/get_job_result_summary", response_model=ToolResponse)
async def get_job_result_summary_endpoint(
    request: JobLookupRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await get_job_result_summary(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/retrieve_artifact_metadata", response_model=ToolResponse)
async def retrieve_artifact_metadata_endpoint(
    request: ArtifactMetadataRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await retrieve_artifact_metadata(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/request_follow_up_module_execution", response_model=ToolResponse)
async def request_follow_up_module_execution_endpoint(
    request: FollowUpRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await request_follow_up_module_execution(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/request_approval_for_action", response_model=ToolResponse)
async def request_approval_for_action_endpoint(
    request: ApprovalToolRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await request_approval_for_action(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/query_device_investigation_history", response_model=ToolResponse)
async def query_device_investigation_history_endpoint(
    request: InvestigationHistoryRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await query_device_investigation_history(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/download_artifact_file", response_model=ToolResponse)
async def download_artifact_file_endpoint(
    request: ArtifactDownloadRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await download_artifact_file(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/retrieve_artifact_content", response_model=ToolResponse)
async def retrieve_artifact_content_endpoint(
    request: ArtifactContentRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await retrieve_artifact_content(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response


@app.post("/tools/extract_zip_artifact_entry", response_model=ToolResponse)
async def extract_zip_artifact_entry_endpoint(
    request: ZipArtifactEntryRequest,
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    response = await extract_zip_artifact_entry(request)
    asyncio.ensure_future(_emit_tool_call_event(response, caller))
    return response
