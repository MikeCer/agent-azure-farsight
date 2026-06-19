from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class RiskLevel(str, Enum):
    read_only = "read-only"
    sensitive_diagnostic = "sensitive-diagnostic"


class JobStatus(str, Enum):
    waiting_approval = "waiting_approval"
    queued = "Queued"
    leased = "Leased"
    running = "Running"
    succeeded = "Succeeded"
    failed = "Failed"
    expired = "Expired"
    cancelled = "Cancelled"


class ApprovalStatus(str, Enum):
    not_required = "not-required"
    pending = "pending"
    approved = "approved"
    denied = "denied"


class PolicyStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class DeviceOs(CamelModel):
    name: str
    version: str


class LocalState(CamelModel):
    last_run_utc: datetime | None = Field(default=None, alias="lastRunUtc")
    last_exit_code: int | None = Field(default=None, alias="lastExitCode")
    pending_artifact_count: int = Field(default=0, alias="pendingArtifactCount")


class DeviceConfig(CamelModel):
    """Remote configuration that the API pushes to a collector on its next check-in."""
    scheduled_task_interval_minutes: int | None = Field(default=None, alias="scheduledTaskIntervalMinutes")
    max_single_run_seconds: int | None = Field(default=None, alias="maxSingleRunSeconds")
    check_in_interval_seconds: int | None = Field(default=None, alias="checkInIntervalSeconds")
    log_retention_days: int | None = Field(default=None, alias="logRetentionDays")
    config_version: str | None = Field(default=None, alias="configVersion")


class CheckInRequest(CamelModel):
    schema_version: str = Field(alias="schemaVersion")
    device_id: str = Field(alias="deviceId")
    tenant_id: str = Field(alias="tenantId")
    collector_version: str = Field(alias="collectorVersion")
    manifest_version: str = Field(alias="manifestVersion")
    hostname: str | None = Field(default=None, alias="hostname")
    hostname_hash: str = Field(alias="hostnameHash")
    os: DeviceOs
    last_job_id: str | None = Field(default=None, alias="lastJobId")
    applied_config_version: str | None = Field(default=None, alias="appliedConfigVersion")
    local_state: LocalState = Field(alias="localState")


class LeaseOffer(CamelModel):
    job_id: str = Field(alias="jobId")
    lease_token: str = Field(alias="leaseToken")
    lease_until_utc: datetime = Field(alias="leaseUntilUtc")


class CheckInResponse(CamelModel):
    schema_version: str = Field(default="1.0", alias="schemaVersion")
    server_time_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="serverTimeUtc")
    policy_version: str = Field(alias="policyVersion")
    manifest_version: str = Field(alias="manifestVersion")
    next_check_in_after_seconds: int = Field(default=300, alias="nextCheckInAfterSeconds")
    job_available: bool = Field(default=False, alias="jobAvailable")
    job: LeaseOffer | None = None
    pending_config: DeviceConfig | None = Field(default=None, alias="pendingConfig")


class Lease(CamelModel):
    lease_token_hash: str = Field(alias="leaseTokenHash")
    leased_by_device_id: str = Field(alias="leasedByDeviceId")
    leased_at_utc: datetime = Field(alias="leasedAtUtc")
    lease_until_utc: datetime = Field(alias="leaseUntilUtc")
    attempt: int


class RequestedBy(CamelModel):
    kind: str
    identity_object_id: str | None = Field(default=None, alias="identityObjectId")
    tool_name: str | None = Field(default=None, alias="toolName")


class JobDocument(CamelModel):
    id: str
    job_id: str = Field(alias="jobId")
    device_id: str = Field(alias="deviceId")
    incident_id: str | None = Field(default=None, alias="incidentId")
    correlation_id: str = Field(alias="correlationId")
    task_type: str = Field(alias="taskType")
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = Field(default=RiskLevel.read_only, alias="riskLevel")
    approval_required: bool = Field(default=False, alias="approvalRequired")
    approval_status: ApprovalStatus = Field(default=ApprovalStatus.not_required, alias="approvalStatus")
    approval_id: str | None = Field(default=None, alias="approvalId")
    status: JobStatus = JobStatus.queued
    policy_version: str = Field(alias="policyVersion")
    manifest_version: str = Field(alias="manifestVersion")
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAtUtc")
    expires_at_utc: datetime = Field(alias="expiresAtUtc")
    lease: Lease | None = None
    retry_count: int = Field(default=0, alias="retryCount")
    requested_by: RequestedBy = Field(alias="requestedBy")


class JobCreateRequest(CamelModel):
    device_id: str = Field(alias="deviceId")
    incident_id: str | None = Field(default=None, alias="incidentId")
    correlation_id: str = Field(alias="correlationId")
    task_type: str = Field(alias="taskType")
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = Field(default=RiskLevel.read_only, alias="riskLevel")
    approval_required: bool = Field(default=False, alias="approvalRequired")
    approval_status: ApprovalStatus = Field(default=ApprovalStatus.not_required, alias="approvalStatus")
    approval_id: str | None = Field(default=None, alias="approvalId")
    status: JobStatus | None = None
    expires_at_utc: datetime = Field(alias="expiresAtUtc")
    requested_by: RequestedBy = Field(alias="requestedBy")


class Finding(CamelModel):
    severity: str
    code: str
    message: str


class ArtifactMetadata(CamelModel):
    artifact_id: str = Field(alias="artifactId")
    kind: str
    name: str
    sha256: str
    size_bytes: int = Field(alias="sizeBytes")
    local_path: str | None = Field(default=None, alias="localPath")


class ResultEnvelope(CamelModel):
    schema_version: str = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId")
    device_id: str = Field(alias="deviceId")
    correlation_id: str = Field(alias="correlationId")
    module: str
    status: JobStatus
    started_at_utc: datetime = Field(alias="startedAtUtc")
    completed_at_utc: datetime = Field(alias="completedAtUtc")
    summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    artifacts: list[ArtifactMetadata] = Field(default_factory=list)
    next_suggested_modules: list[str] = Field(default_factory=list, alias="nextSuggestedModules")


class ArtifactPrepareRequest(CamelModel):
    job_id: str = Field(alias="jobId")
    artifact_id: str = Field(alias="artifactId")
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes")
    sha256: str


class ArtifactPrepareResponse(CamelModel):
    upload_url: str = Field(alias="uploadUrl")
    expires_at_utc: datetime = Field(alias="expiresAtUtc")
    required_headers: dict[str, str] = Field(default_factory=dict, alias="requiredHeaders")


class ArtifactCommitRequest(CamelModel):
    job_id: str = Field(alias="jobId")
    artifact_id: str = Field(alias="artifactId")
    file_name: str | None = Field(default=None, alias="fileName")
    uploaded: bool
    sha256: str


class ArtifactUploadRequest(CamelModel):
    job_id: str = Field(alias="jobId")
    artifact_id: str = Field(alias="artifactId")
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    content_base64: str = Field(alias="contentBase64")
    sha256: str


class ApprovalRequest(CamelModel):
    approval_id: str = Field(alias="approvalId")
    correlation_id: str = Field(alias="correlationId")
    requested_action: str = Field(alias="requestedAction")
    risk_level: RiskLevel = Field(alias="riskLevel")
    requested_by: str = Field(alias="requestedBy")
    reason: str
    expires_at_utc: datetime = Field(alias="expiresAtUtc")
    status: ApprovalStatus = ApprovalStatus.pending
    job_id: str | None = Field(default=None, alias="jobId")
    device_id: str | None = Field(default=None, alias="deviceId")
    task_type: str | None = Field(default=None, alias="taskType")
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAtUtc")
    decided_by: str | None = Field(default=None, alias="decidedBy")
    decided_at_utc: datetime | None = Field(default=None, alias="decidedAtUtc")
    comment: str | None = None


class ApprovalDecision(CamelModel):
    approval_id: str = Field(alias="approvalId")
    decision: ApprovalStatus
    decided_by: str = Field(alias="decidedBy")
    decided_at_utc: datetime = Field(alias="decidedAtUtc")
    comment: str | None = None


class PolicyValidation(CamelModel):
    status: str
    messages: list[str] = Field(default_factory=list)


class PolicyDocument(CamelModel):
    id: str
    policy_id: str = Field(alias="policyId")
    version: str
    status: PolicyStatus
    format: str = "agt-yaml"
    content: str
    content_hash: str = Field(alias="contentHash")
    created_at_utc: datetime = Field(alias="createdAtUtc")
    created_by: str = Field(alias="createdBy")
    updated_at_utc: datetime = Field(alias="updatedAtUtc")
    updated_by: str = Field(alias="updatedBy")
    activated_at_utc: datetime | None = Field(default=None, alias="activatedAtUtc")
    activated_by: str | None = Field(default=None, alias="activatedBy")
    notes: str | None = None
    validation: PolicyValidation


class PolicySummary(CamelModel):
    policy_id: str = Field(alias="policyId")
    active_version: str | None = Field(default=None, alias="activeVersion")
    versions: list[PolicyDocument] = Field(default_factory=list)


class PolicyUpsertRequest(CamelModel):
    content: str
    status: PolicyStatus = PolicyStatus.draft
    updated_by: str = Field(default="admin-ui", alias="updatedBy")
    notes: str | None = None


class PolicyValidateRequest(CamelModel):
    content: str


class PolicyActivateRequest(CamelModel):
    activated_by: str = Field(default="admin-ui", alias="activatedBy")
    notes: str | None = None


class ToolCallByTool(CamelModel):
    tool_name: str = Field(alias="toolName")
    total_calls: int = Field(default=0, alias="totalCalls")
    allowed_calls: int = Field(default=0, alias="allowedCalls")
    denied_calls: int = Field(default=0, alias="deniedCalls")
    approval_required_calls: int = Field(default=0, alias="approvalRequiredCalls")
    failed_calls: int = Field(default=0, alias="failedCalls")
    last_seen_utc: datetime | None = Field(default=None, alias="lastSeenUtc")


class RecentToolCall(CamelModel):
    timestamp_utc: datetime = Field(alias="timestampUtc")
    tool_name: str = Field(alias="toolName")
    decision: str
    actor: str | None = None
    actor_app_id: str | None = Field(default=None, alias="actorAppId")
    policy_id: str | None = Field(default=None, alias="policyId")
    policy_version: str | None = Field(default=None, alias="policyVersion")
    rule_name: str | None = Field(default=None, alias="ruleName")
    reason: str | None = None
    job_id: str | None = Field(default=None, alias="jobId")
    correlation_id: str | None = Field(default=None, alias="correlationId")


class ToolCallTelemetrySummary(CamelModel):
    window: str = "24h"
    total_calls: int = Field(default=0, alias="totalCalls")
    allowed_calls: int = Field(default=0, alias="allowedCalls")
    denied_calls: int = Field(default=0, alias="deniedCalls")
    approval_required_calls: int = Field(default=0, alias="approvalRequiredCalls")
    failed_calls: int = Field(default=0, alias="failedCalls")
    by_tool: list[ToolCallByTool] = Field(default_factory=list, alias="byTool")
    recent: list[RecentToolCall] = Field(default_factory=list)


class AuditEvent(CamelModel):
    id: str
    event_type: str = Field(alias="eventType")
    action: str
    actor_id: str = Field(alias="actorId")
    actor_name: str | None = Field(default=None, alias="actorName")
    target: str
    decision: str
    reason: str | None = None
    correlation_id: str | None = Field(default=None, alias="correlationId")
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="createdAtUtc")
