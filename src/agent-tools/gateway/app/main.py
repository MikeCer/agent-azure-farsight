from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from .auth import WorkloadCaller, require_workload_caller
from .models import (
    ApprovalToolRequest,
    ArtifactContentRequest,
    ArtifactMetadataRequest,
    DiagnosticJobRequest,
    FollowUpRequest,
    InvestigationHistoryRequest,
    JobLookupRequest,
    ToolResponse,
)
from .policy import PolicyConfigurationError
from .tools import (
    create_diagnostic_job,
    get_job_result_summary,
    get_job_status,
    query_device_investigation_history,
    request_approval_for_action,
    request_follow_up_module_execution,
    retrieve_artifact_content,
    retrieve_artifact_metadata,
)

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

app = FastAPI(title="FarSight AGT Tool Gateway", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-tool-gateway"}


@app.post("/tools/create_diagnostic_job", response_model=ToolResponse)
async def create_diagnostic_job_endpoint(
    request: DiagnosticJobRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await create_diagnostic_job(request)


@app.post("/tools/get_job_status", response_model=ToolResponse)
async def get_job_status_endpoint(
    request: JobLookupRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await get_job_status(request)


@app.post("/tools/get_job_result_summary", response_model=ToolResponse)
async def get_job_result_summary_endpoint(
    request: JobLookupRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await get_job_result_summary(request)


@app.post("/tools/retrieve_artifact_metadata", response_model=ToolResponse)
async def retrieve_artifact_metadata_endpoint(
    request: ArtifactMetadataRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await retrieve_artifact_metadata(request)


@app.post("/tools/request_follow_up_module_execution", response_model=ToolResponse)
async def request_follow_up_module_execution_endpoint(
    request: FollowUpRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await request_follow_up_module_execution(request)


@app.post("/tools/request_approval_for_action", response_model=ToolResponse)
async def request_approval_for_action_endpoint(
    request: ApprovalToolRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await request_approval_for_action(request)


@app.post("/tools/query_device_investigation_history", response_model=ToolResponse)
async def query_device_investigation_history_endpoint(
    request: InvestigationHistoryRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await query_device_investigation_history(request)


@app.post("/tools/retrieve_artifact_content", response_model=ToolResponse)
async def retrieve_artifact_content_endpoint(
    request: ArtifactContentRequest,
    _caller: WorkloadCaller = Depends(require_workload_caller),
) -> ToolResponse:
    return await retrieve_artifact_content(request)
