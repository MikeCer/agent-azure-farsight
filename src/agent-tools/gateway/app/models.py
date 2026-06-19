from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PolicyOutcome(str, Enum):
    allow = "allow"
    deny = "deny"
    require_approval = "require_approval"


class ToolRisk(str, Enum):
    read_only = "read-only"
    sensitive_diagnostic = "sensitive-diagnostic"


class PolicyDecision(CamelModel):
    outcome: PolicyOutcome
    reason: str
    policy_version: str = Field(alias="policyVersion")
    policy_name: str | None = Field(default=None, alias="policyName")
    rule_name: str | None = Field(default=None, alias="ruleName")
    audit_id: str | None = Field(default=None, alias="auditId")
    evidence: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(CamelModel):
    tool_name: str = Field(alias="toolName")
    policy: PolicyDecision
    data: dict[str, Any] = Field(default_factory=dict)


class RequestedBy(CamelModel):
    kind: str = "agent_tool"
    identity_object_id: str | None = Field(default=None, alias="identityObjectId")
    tool_name: str | None = Field(default=None, alias="toolName")


class DiagnosticJobRequest(CamelModel):
    device_id: str = Field(alias="deviceId")
    incident_id: str | None = Field(default=None, alias="incidentId")
    correlation_id: str = Field(alias="correlationId")
    task_type: str = Field(alias="taskType")
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: ToolRisk = Field(default=ToolRisk.read_only, alias="riskLevel")
    expires_at_utc: datetime = Field(alias="expiresAtUtc")
    requested_by: RequestedBy = Field(
        default_factory=lambda: RequestedBy(kind="agent_tool"),
        alias="requestedBy",
    )


class JobLookupRequest(CamelModel):
    job_id: str = Field(alias="jobId")


class ArtifactMetadataRequest(CamelModel):
    job_id: str = Field(alias="jobId")


class FollowUpRequest(DiagnosticJobRequest):
    parent_job_id: str = Field(alias="parentJobId")


class ApprovalToolRequest(CamelModel):
    approval_id: str = Field(alias="approvalId")
    correlation_id: str = Field(alias="correlationId")
    requested_action: str = Field(alias="requestedAction")
    risk_level: ToolRisk = Field(alias="riskLevel")
    reason: str
    expires_at_utc: datetime = Field(alias="expiresAtUtc")


class ArtifactContentRequest(CamelModel):
    job_id: str = Field(alias="jobId")
    artifact_id: str = Field(alias="artifactId")


class ArtifactDownloadRequest(CamelModel):
    job_id: str = Field(alias="jobId")
    artifact_id: str = Field(alias="artifactId")


class ZipArtifactEntryRequest(CamelModel):
    job_id: str = Field(alias="jobId")
    artifact_id: str = Field(alias="artifactId")
    file_path: str | None = Field(default=None, alias="filePath")
    tail_lines: int | None = Field(default=None, alias="tailLines")


class InvestigationHistoryRequest(CamelModel):
    device_id: str = Field(alias="deviceId")
    incident_id: str | None = Field(default=None, alias="incidentId")
