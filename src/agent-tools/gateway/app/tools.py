from typing import Any

from .models import (
    ApprovalToolRequest,
    ArtifactMetadataRequest,
    DiagnosticJobRequest,
    FollowUpRequest,
    InvestigationHistoryRequest,
    JobLookupRequest,
    PolicyDecision,
    PolicyOutcome,
    ToolResponse,
)
from .policy import evaluate_policy


def _blocked(tool_name: str, policy: PolicyDecision) -> ToolResponse:
    return ToolResponse(toolName=tool_name, policy=policy, data={"status": "blocked"})


async def _call_api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # TODO: Wire to FarSightApiClient once API auth/RBAC contract is provisioned.
    # return await FarSightApiClient().request(method, path, json=payload)
    return {"method": method, "path": path, "payload": payload, "status": "placeholder"}


async def create_diagnostic_job(request: DiagnosticJobRequest) -> ToolResponse:
    tool_name = "create_diagnostic_job"
    payload = request.model_dump(by_alias=True)
    policy = evaluate_policy(tool_name, request.risk_level, payload)
    if policy.outcome == PolicyOutcome.deny:
        return _blocked(tool_name, policy)
    if policy.outcome == PolicyOutcome.require_approval:
        return _blocked(tool_name, policy)
    data = await _call_api("POST", "/api/v1/jobs", payload)
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def get_job_status(request: JobLookupRequest) -> ToolResponse:
    tool_name = "get_job_status"
    policy = evaluate_policy(tool_name, payload=request.model_dump(by_alias=True))
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/jobs/{request.job_id}")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def get_job_result_summary(request: JobLookupRequest) -> ToolResponse:
    tool_name = "get_job_result_summary"
    policy = evaluate_policy(tool_name, payload=request.model_dump(by_alias=True))
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/jobs/{request.job_id}/summary")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def retrieve_artifact_metadata(request: ArtifactMetadataRequest) -> ToolResponse:
    tool_name = "retrieve_artifact_metadata"
    policy = evaluate_policy(tool_name, payload=request.model_dump(by_alias=True))
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/jobs/{request.job_id}/artifacts")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def request_follow_up_module_execution(request: FollowUpRequest) -> ToolResponse:
    tool_name = "request_follow_up_module_execution"
    payload = request.model_dump(by_alias=True)
    policy = evaluate_policy(tool_name, request.risk_level, payload)
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    parent_job_id = payload.pop("parentJobId")
    data = await _call_api("POST", f"/api/v1/jobs/{parent_job_id}/followups", payload)
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def request_approval_for_action(request: ApprovalToolRequest) -> ToolResponse:
    tool_name = "request_approval_for_action"
    payload = request.model_dump(by_alias=True) | {"requestedBy": "azure-sre-agent"}
    policy = evaluate_policy(tool_name, request.risk_level, payload)
    if policy.outcome == PolicyOutcome.deny:
        return _blocked(tool_name, policy)
    data = await _call_api("POST", "/api/v1/approvals", payload)
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def query_device_investigation_history(request: InvestigationHistoryRequest) -> ToolResponse:
    tool_name = "query_device_investigation_history"
    policy = evaluate_policy(tool_name, payload=request.model_dump(by_alias=True))
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/devices/{request.device_id}/investigations")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)
