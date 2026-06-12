from fastapi import FastAPI

from .models import (
    ApprovalToolRequest,
    ArtifactMetadataRequest,
    DiagnosticJobRequest,
    FollowUpRequest,
    InvestigationHistoryRequest,
    JobLookupRequest,
    ToolResponse,
)
from .tools import (
    create_diagnostic_job,
    get_job_result_summary,
    get_job_status,
    query_device_investigation_history,
    request_approval_for_action,
    request_follow_up_module_execution,
    retrieve_artifact_metadata,
)

app = FastAPI(title="FarSight AGT Tool Gateway", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-tool-gateway"}


@app.post("/tools/create_diagnostic_job", response_model=ToolResponse)
async def create_diagnostic_job_endpoint(request: DiagnosticJobRequest) -> ToolResponse:
    return await create_diagnostic_job(request)


@app.post("/tools/get_job_status", response_model=ToolResponse)
async def get_job_status_endpoint(request: JobLookupRequest) -> ToolResponse:
    return await get_job_status(request)


@app.post("/tools/get_job_result_summary", response_model=ToolResponse)
async def get_job_result_summary_endpoint(request: JobLookupRequest) -> ToolResponse:
    return await get_job_result_summary(request)


@app.post("/tools/retrieve_artifact_metadata", response_model=ToolResponse)
async def retrieve_artifact_metadata_endpoint(request: ArtifactMetadataRequest) -> ToolResponse:
    return await retrieve_artifact_metadata(request)


@app.post("/tools/request_follow_up_module_execution", response_model=ToolResponse)
async def request_follow_up_module_execution_endpoint(request: FollowUpRequest) -> ToolResponse:
    return await request_follow_up_module_execution(request)


@app.post("/tools/request_approval_for_action", response_model=ToolResponse)
async def request_approval_for_action_endpoint(request: ApprovalToolRequest) -> ToolResponse:
    return await request_approval_for_action(request)


@app.post("/tools/query_device_investigation_history", response_model=ToolResponse)
async def query_device_investigation_history_endpoint(request: InvestigationHistoryRequest) -> ToolResponse:
    return await query_device_investigation_history(request)
