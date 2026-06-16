import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from .auth import (
    AdminActor,
    DeviceCaller,
    WorkloadCaller,
    require_admin_actor,
    require_bound_device_id,
    require_device_cert,
    require_workload_caller,
)
from .dependencies import AzureClients, get_azure_clients
from .models import (
    AuditEvent,
    ApprovalDecision,
    ApprovalRequest,
    ArtifactCommitRequest,
    ArtifactPrepareRequest,
    ArtifactPrepareResponse,
    CheckInRequest,
    CheckInResponse,
    JobCreateRequest,
    JobDocument,
    JobStatus,
    LeaseOffer,
    PolicyActivateRequest,
    PolicyDocument,
    PolicySummary,
    PolicyStatus,
    PolicyUpsertRequest,
    PolicyValidateRequest,
    PolicyValidation,
    ResultEnvelope,
    ToolCallTelemetrySummary,
)
from .policy_repository import PolicyRepository, get_policy_repository, validate_policy_content

app = FastAPI(title="Agent-Azure-FarSight Control API", version="0.1.0")

POLICY_VERSION = "2026-06-12.1"
MANIFEST_VERSION = "2026-06-12.1"
jobs: dict[str, JobDocument] = {}
results: dict[str, ResultEnvelope] = {}
approvals: dict[str, ApprovalRequest] = {}
artifact_index: dict[str, list[dict[str, object]]] = {}
audit_events: list[AuditEvent] = []


def append_audit_event(action: str, actor: AdminActor, target: str, decision: str = "allowed", reason: str | None = None) -> None:
    audit_events.append(
        AuditEvent(
            id=f"audit-{uuid4()}",
            eventType="policy-admin",
            action=action,
            actorId=actor.actor_id,
            actorName=actor.actor_name,
            target=target,
            decision=decision,
            reason=reason,
        )
    )


def actor_display(actor: AdminActor) -> str:
    return actor.actor_name or actor.actor_id


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-api"}


@app.post("/api/v1/devices/checkin", response_model=CheckInResponse)
def check_in(
    request: CheckInRequest,
    device: DeviceCaller = Depends(require_device_cert),
    _: AzureClients = Depends(get_azure_clients),
) -> CheckInResponse:
    require_bound_device_id(device, request.device_id)
    available = next((job for job in jobs.values() if job.device_id == request.device_id and job.status == JobStatus.queued), None)
    lease = None
    if available:
        # TODO: Persist lease transition in Cosmos with optimistic ETag concurrency.
        available.status = JobStatus.leased
        lease = LeaseOffer(
            jobId=available.job_id,
            leaseToken=f"lease-{uuid4()}",
            leaseUntilUtc=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
    return CheckInResponse(
        policyVersion=POLICY_VERSION,
        manifestVersion=MANIFEST_VERSION,
        jobAvailable=lease is not None,
        job=lease,
    )


@app.get("/api/v1/devices/{deviceId}/jobs")
def get_device_jobs(deviceId: str, device: DeviceCaller = Depends(require_device_cert)) -> list[JobDocument]:
    require_bound_device_id(device, deviceId)
    return [job for job in jobs.values() if job.device_id == deviceId]


@app.get("/api/v1/devices/{deviceId}/policy")
def get_device_policy(deviceId: str, device: DeviceCaller = Depends(require_device_cert)) -> dict[str, object]:
    require_bound_device_id(device, deviceId)
    # TODO: Retrieve endpoint policy snapshot from Cosmos/App Configuration.
    return {"deviceId": deviceId, "policyVersion": POLICY_VERSION, "allowedModules": []}


@app.get("/api/v1/devices/{deviceId}/investigations")
def get_device_investigations(deviceId: str, _: WorkloadCaller = Depends(require_workload_caller)) -> dict[str, object]:
    # TODO: Query Cosmos investigations container and redact sensitive history.
    return {"deviceId": deviceId, "investigations": []}


@app.post("/api/v1/jobs", response_model=JobDocument, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AzureClients = Depends(get_azure_clients),
    __: WorkloadCaller = Depends(require_workload_caller),
) -> JobDocument:
    # TODO: Enforce Entra/managed identity authorization and idempotency key persistence.
    # TODO: Write Cosmos job document, then enqueue Service Bus jobs message using deviceId as session ID.
    job_id = f"job-{uuid4()}"
    job = JobDocument(
        id=job_id,
        jobId=job_id,
        deviceId=request.device_id,
        incidentId=request.incident_id,
        correlationId=request.correlation_id,
        taskType=request.task_type,
        parameters=request.parameters,
        riskLevel=request.risk_level,
        approvalRequired=False,
        approvalStatus="not-required",
        status=JobStatus.queued,
        policyVersion=POLICY_VERSION,
        manifestVersion=MANIFEST_VERSION,
        expiresAtUtc=request.expires_at_utc,
        requestedBy=request.requested_by,
    )
    jobs[job_id] = job
    return job


@app.get("/api/v1/jobs/{jobId}", response_model=JobDocument)
def get_job(jobId: str, device: DeviceCaller = Depends(require_device_cert)) -> JobDocument:
    job = jobs.get(jobId)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    require_bound_device_id(device, job.device_id)
    return job


@app.get("/api/v1/jobs/{jobId}/summary")
def get_job_summary(jobId: str, _: WorkloadCaller = Depends(require_workload_caller)) -> dict[str, object]:
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    result = results.get(jobId)
    return {"jobId": jobId, "status": jobs[jobId].status, "summary": result.summary if result else {}}


@app.get("/api/v1/jobs/{jobId}/results")
def get_job_results(jobId: str) -> ResultEnvelope:
    result = results.get(jobId)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return result


@app.post("/api/v1/jobs/{jobId}/results", status_code=status.HTTP_202_ACCEPTED)
def submit_job_result(
    jobId: str,
    result: ResultEnvelope,
    device: DeviceCaller = Depends(require_device_cert),
    _: AzureClients = Depends(get_azure_clients),
) -> dict[str, str]:
    if jobId != result.job_id:
        raise HTTPException(status_code=400, detail="Path jobId must match result jobId")
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[jobId]
    require_bound_device_id(device, job.device_id)
    require_bound_device_id(device, result.device_id)
    # TODO: Validate lease token, persist result to Cosmos, and ingest normalized summaries into Log Analytics.
    results[jobId] = result
    jobs[jobId].status = result.status
    artifact_index[jobId] = [artifact.model_dump(by_alias=True) for artifact in result.artifacts]
    return {"status": "accepted"}


@app.get("/api/v1/jobs/{jobId}/artifacts")
def get_job_artifacts(jobId: str, _: WorkloadCaller = Depends(require_workload_caller)) -> dict[str, object]:
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"jobId": jobId, "artifacts": artifact_index.get(jobId, [])}


@app.post("/api/v1/jobs/{jobId}/followups", response_model=JobDocument, status_code=status.HTTP_201_CREATED)
def request_followup(
    jobId: str,
    request: JobCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: WorkloadCaller = Depends(require_workload_caller),
) -> JobDocument:
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Parent job not found")
    return create_job(request, idempotency_key)


@app.post("/api/v1/artifacts/prepare", response_model=ArtifactPrepareResponse)
def prepare_artifact_upload(request: ArtifactPrepareRequest, _: AzureClients = Depends(get_azure_clients)) -> ArtifactPrepareResponse:
    # TODO: Create private Blob metadata record and return short-lived user delegation SAS upload URL.
    return ArtifactPrepareResponse(
        uploadUrl=f"https://storage.example.invalid/farsight/{request.job_id}/{request.artifact_id}",
        expiresAtUtc=datetime.now(timezone.utc) + timedelta(minutes=10),
        requiredHeaders={"x-ms-blob-type": "BlockBlob"},
    )


@app.post("/api/v1/artifacts/commit", status_code=status.HTTP_202_ACCEPTED)
def commit_artifact_upload(request: ArtifactCommitRequest, _: AzureClients = Depends(get_azure_clients)) -> dict[str, str]:
    # TODO: Verify Blob exists, validate hash/size, update Cosmos artifactIndex, and audit retention metadata.
    return {"status": "accepted", "artifactId": request.artifact_id}


@app.post("/api/v1/approvals", response_model=ApprovalRequest, status_code=status.HTTP_201_CREATED)
def create_approval(
    request: ApprovalRequest,
    _: AzureClients = Depends(get_azure_clients),
    __: WorkloadCaller = Depends(require_workload_caller),
) -> ApprovalRequest:
    # TODO: Persist approval in Cosmos and send Teams notification through configured transport.
    approvals[request.approval_id] = request
    return request


@app.post("/api/v1/approvals/{approvalId}/decision", status_code=status.HTTP_202_ACCEPTED)
def decide_approval(approvalId: str, decision: ApprovalDecision, _: AzureClients = Depends(get_azure_clients)) -> dict[str, str]:
    if approvalId != decision.approval_id:
        raise HTTPException(status_code=400, detail="Path approvalId must match decision approvalId")
    if approvalId not in approvals:
        raise HTTPException(status_code=404, detail="Approval not found")
    # TODO: Persist immutable approval decision and release blocked jobs when approved.
    return {"status": "accepted", "decision": decision.decision}


@app.get("/api/v1/policy")
def get_policy(
    repository: PolicyRepository = Depends(get_policy_repository),
    _: WorkloadCaller = Depends(require_workload_caller),
) -> PolicyDocument:
    # Backwards-compatible active policy endpoint for gateway consumers.
    return repository.get("farsight-tool-policy")


@app.get("/api/v1/policies", response_model=list[PolicySummary])
def list_policies(repository: PolicyRepository = Depends(get_policy_repository)) -> list[PolicySummary]:
    return repository.list()


@app.get("/api/v1/policies/{policyId}", response_model=PolicyDocument)
def get_active_policy(
    policyId: str,
    repository: PolicyRepository = Depends(get_policy_repository),
    _: WorkloadCaller = Depends(require_workload_caller),
) -> PolicyDocument:
    try:
        return repository.get(policyId)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy not found") from exc


@app.get("/api/v1/policies/{policyId}/versions/{version}", response_model=PolicyDocument)
def get_policy_version(policyId: str, version: str, repository: PolicyRepository = Depends(get_policy_repository)) -> PolicyDocument:
    try:
        return repository.get(policyId, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy version not found") from exc


@app.post("/api/v1/policies/{policyId}/validate", response_model=PolicyValidation)
def validate_policy(policyId: str, request: PolicyValidateRequest) -> PolicyValidation:
    return validate_policy_content(request.content)


@app.put("/api/v1/policies/{policyId}/versions/{version}", response_model=PolicyDocument)
def upsert_policy(
    policyId: str,
    version: str,
    request: PolicyUpsertRequest,
    repository: PolicyRepository = Depends(get_policy_repository),
    actor: AdminActor = Depends(require_admin_actor),
) -> PolicyDocument:
    if request.status != PolicyStatus.draft:
        raise HTTPException(status_code=400, detail="Policy save only supports draft status. Use the activate endpoint to change the active version.")
    doc = repository.upsert(policyId, version, request.content, PolicyStatus.draft, actor_display(actor), request.notes)
    append_audit_event("policy.version.save", actor, f"{policyId}:{version}")
    return doc


@app.post("/api/v1/policies/{policyId}/versions/{version}/activate", response_model=PolicyDocument)
def activate_policy(
    policyId: str,
    version: str,
    request: PolicyActivateRequest,
    repository: PolicyRepository = Depends(get_policy_repository),
    actor: AdminActor = Depends(require_admin_actor),
) -> PolicyDocument:
    try:
        doc = repository.activate(policyId, version, actor_display(actor), request.notes)
        append_audit_event("policy.version.activate", actor, f"{policyId}:{version}")
        return doc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy version not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/policies/{policyId}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy_version(
    policyId: str,
    version: str,
    repository: PolicyRepository = Depends(get_policy_repository),
    actor: AdminActor = Depends(require_admin_actor),
) -> Response:
    try:
        repository.delete_version(policyId, version, actor_display(actor))
        append_audit_event("policy.version.delete", actor, f"{policyId}:{version}")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Policy version not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/telemetry/tool-calls/summary", response_model=ToolCallTelemetrySummary)
def get_tool_call_summary() -> ToolCallTelemetrySummary:
    # TODO: Query AGT/tool gateway audit events from Log Analytics, Application Insights, or Cosmos.
    return ToolCallTelemetrySummary()


@app.get("/api/v1/admin/config")
def get_admin_config() -> dict[str, object]:
    # TODO: Enforce FarSight Admin role and read settings from App Configuration.
    return {"retentionDays": {"jobs": 30, "artifacts": 30, "logs": 90}, "apimEnabled": False}


@app.put("/api/v1/admin/config", status_code=status.HTTP_204_NO_CONTENT)
def update_admin_config(config: dict[str, object]) -> Response:
    # TODO: Validate admin config schema, write App Configuration, and audit changes.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
