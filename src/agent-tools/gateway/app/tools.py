from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException

from .clients import FarSightApiClient
from .models import (
    ApprovalToolRequest,
    ArtifactContentRequest,
    ArtifactMetadataRequest,
    DiagnosticJobRequest,
    FollowUpRequest,
    InvestigationHistoryRequest,
    JobLookupRequest,
    PolicyDecision,
    PolicyOutcome,
    ToolResponse,
    ZipArtifactEntryRequest,
)
from .policy import PolicyConfigurationError, evaluate_policy


def _blocked(tool_name: str, policy: PolicyDecision) -> ToolResponse:
    return ToolResponse(toolName=tool_name, policy=policy, data={"status": "blocked"})


def _policy_error(tool_name: str, message: str) -> ToolResponse:
    """Return a structured error response when policy evaluation fails to configure."""
    from .models import ToolRisk
    return ToolResponse(
        toolName=tool_name,
        policy=PolicyDecision(
            outcome=PolicyOutcome.deny,
            reason=f"Policy configuration error: {message}",
            policyVersion="unknown",
            policyName="error",
            evidence={"tool_name": tool_name},
        ),
        data={"status": "policy_error", "message": message},
    )


def _eval_policy(tool_name: str, risk_level=None, payload=None) -> PolicyDecision | ToolResponse:
    """Evaluate policy and return either PolicyDecision or a ToolResponse on configuration error."""
    try:
        from .models import ToolRisk
        if risk_level is None:
            return evaluate_policy(tool_name, payload=payload)
        return evaluate_policy(tool_name, risk_level, payload=payload)
    except PolicyConfigurationError as exc:
        return _policy_error(tool_name, str(exc))


async def _call_api(method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return await FarSightApiClient().request(method, path, json=payload, params=params)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail={"error": "configuration_error", "message": str(exc)}) from exc
    except httpx.HTTPStatusError as exc:
        upstream_detail: Any
        try:
            upstream_detail = exc.response.json()
        except ValueError:
            upstream_detail = {"text": exc.response.text}
        raise HTTPException(
            status_code=exc.response.status_code,
            detail={
                "error": "upstream_api_error",
                "message": f"FarSight API returned HTTP {exc.response.status_code}.",
                "response": upstream_detail,
                "path": path,
            },
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "network_error", "message": "FarSight API request failed.", "path": path, "detail": str(exc)},
        ) from exc


async def _create_waiting_approval_job(
    *,
    tool_name: str,
    payload: dict[str, Any],
    policy: PolicyDecision,
    followup_parent_job_id: str | None = None,
) -> ToolResponse:
    approval_id = f"approval-{uuid4()}"
    requested_by = payload.get("requestedBy") or {}
    if isinstance(requested_by, dict):
        requested_by_text = requested_by.get("identityObjectId") or requested_by.get("toolName") or requested_by.get("kind") or "azure-sre-agent"
    else:
        requested_by_text = str(requested_by or "azure-sre-agent")

    approval_payload = {
        "approvalId": approval_id,
        "correlationId": payload.get("correlationId") or f"corr-{uuid4()}",
        "requestedAction": f"{tool_name}:{payload.get('taskType', 'unknown')}",
        "riskLevel": payload.get("riskLevel", "sensitive-diagnostic"),
        "requestedBy": requested_by_text,
        "reason": policy.reason,
        "expiresAtUtc": payload.get("expiresAtUtc"),
        "deviceId": payload.get("deviceId"),
        "taskType": payload.get("taskType"),
        "status": "pending",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
    }
    await _call_api("POST", "/api/v1/approvals", approval_payload)

    job_payload = {
        **payload,
        "approvalRequired": True,
        "approvalStatus": "pending",
        "approvalId": approval_id,
        "status": "waiting_approval",
    }
    if followup_parent_job_id:
        data = await _call_api("POST", f"/api/v1/jobs/{followup_parent_job_id}/followups", job_payload)
    else:
        data = await _call_api("POST", "/api/v1/jobs", job_payload)
    data["status"] = "approval_required"
    data["approvalId"] = approval_id
    data["approvalStatus"] = "pending"
    data["message"] = "This diagnostic job is waiting for administrator approval before collector polling can lease it."
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def create_diagnostic_job(request: DiagnosticJobRequest) -> ToolResponse:
    tool_name = "create_diagnostic_job"
    payload = request.model_dump(by_alias=True, mode="json")
    policy = _eval_policy(tool_name, request.risk_level, payload)
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome == PolicyOutcome.deny:
        return _blocked(tool_name, policy)
    if policy.outcome == PolicyOutcome.require_approval:
        return await _create_waiting_approval_job(tool_name=tool_name, payload=payload, policy=policy)
    data = await _call_api("POST", "/api/v1/jobs", payload)
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def get_job_status(request: JobLookupRequest) -> ToolResponse:
    tool_name = "get_job_status"
    policy = _eval_policy(tool_name, payload=request.model_dump(by_alias=True, mode="json"))
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    # /api/v1/jobs/{id}/summary is the workload-caller endpoint;
    # /api/v1/jobs/{id} requires device cert and is collector-only.
    data = await _call_api("GET", f"/api/v1/jobs/{request.job_id}/summary")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def get_job_result_summary(request: JobLookupRequest) -> ToolResponse:
    tool_name = "get_job_result_summary"
    policy = _eval_policy(tool_name, payload=request.model_dump(by_alias=True, mode="json"))
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/jobs/{request.job_id}/summary")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def retrieve_artifact_metadata(request: ArtifactMetadataRequest) -> ToolResponse:
    tool_name = "retrieve_artifact_metadata"
    policy = _eval_policy(tool_name, payload=request.model_dump(by_alias=True, mode="json"))
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/jobs/{request.job_id}/artifacts")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def request_follow_up_module_execution(request: FollowUpRequest) -> ToolResponse:
    tool_name = "request_follow_up_module_execution"
    payload = request.model_dump(by_alias=True, mode="json")
    policy = _eval_policy(tool_name, request.risk_level, payload)
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome == PolicyOutcome.deny:
        return _blocked(tool_name, policy)
    if policy.outcome == PolicyOutcome.require_approval:
        parent_job_id = payload.pop("parentJobId")
        return await _create_waiting_approval_job(
            tool_name=tool_name,
            payload=payload,
            policy=policy,
            followup_parent_job_id=parent_job_id,
        )
    parent_job_id = payload.pop("parentJobId")
    data = await _call_api("POST", f"/api/v1/jobs/{parent_job_id}/followups", payload)
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def request_approval_for_action(request: ApprovalToolRequest) -> ToolResponse:
    tool_name = "request_approval_for_action"
    payload = request.model_dump(by_alias=True, mode="json") | {"requestedBy": "azure-sre-agent"}
    policy = _eval_policy(tool_name, request.risk_level, payload)
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome == PolicyOutcome.deny:
        return _blocked(tool_name, policy)
    data = await _call_api("POST", "/api/v1/approvals", payload)
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def query_device_investigation_history(request: InvestigationHistoryRequest) -> ToolResponse:
    tool_name = "query_device_investigation_history"
    policy = _eval_policy(tool_name, payload=request.model_dump(by_alias=True, mode="json"))
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api("GET", f"/api/v1/devices/{request.device_id}/investigations")
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def retrieve_artifact_content(request: ArtifactContentRequest) -> ToolResponse:
    tool_name = "retrieve_artifact_content"
    policy = _eval_policy(tool_name, payload=request.model_dump(by_alias=True, mode="json"))
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    data = await _call_api(
        "GET",
        f"/api/v1/jobs/{request.job_id}/artifacts/{request.artifact_id}/content",
    )
    return ToolResponse(toolName=tool_name, policy=policy, data=data)


async def extract_zip_artifact_entry(request: ZipArtifactEntryRequest) -> ToolResponse:
    tool_name = "extract_zip_artifact_entry"
    policy = _eval_policy(tool_name, payload=request.model_dump(by_alias=True, mode="json"))
    if isinstance(policy, ToolResponse):
        return policy
    if policy.outcome != PolicyOutcome.allow:
        return _blocked(tool_name, policy)
    params = {}
    if request.file_path:
        params["file_path"] = request.file_path
    data = await _call_api(
        "GET",
        f"/api/v1/jobs/{request.job_id}/artifacts/{request.artifact_id}/zip-entry",
        params=params,
    )
    return ToolResponse(toolName=tool_name, policy=policy, data=data)
