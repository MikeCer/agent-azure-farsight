from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from .dependencies import AzureClients, get_azure_clients
from .models import (
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
    ResultEnvelope,
)

app = FastAPI(title="Agent-Azure-FarSight Control API", version="0.1.0")

POLICY_VERSION = "2026-06-12.1"
MANIFEST_VERSION = "2026-06-12.1"
jobs: dict[str, JobDocument] = {}
results: dict[str, ResultEnvelope] = {}
approvals: dict[str, ApprovalRequest] = {}
artifact_index: dict[str, list[dict[str, object]]] = {}


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-api"}


@app.post("/api/v1/devices/checkin", response_model=CheckInResponse)
def check_in(request: CheckInRequest, _: AzureClients = Depends(get_azure_clients)) -> CheckInResponse:
    # TODO: Validate device mTLS certificate binding and update Cosmos devices heartbeat.
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
def get_device_jobs(deviceId: str) -> list[JobDocument]:
    # TODO: Authorize collector to read only jobs for its own device identity.
    return [job for job in jobs.values() if job.device_id == deviceId]


@app.get("/api/v1/devices/{deviceId}/policy")
def get_device_policy(deviceId: str) -> dict[str, object]:
    # TODO: Retrieve endpoint policy snapshot from Cosmos/App Configuration.
    return {"deviceId": deviceId, "policyVersion": POLICY_VERSION, "allowedModules": []}


@app.get("/api/v1/devices/{deviceId}/investigations")
def get_device_investigations(deviceId: str) -> dict[str, object]:
    # TODO: Query Cosmos investigations container and redact sensitive history.
    return {"deviceId": deviceId, "investigations": []}


@app.post("/api/v1/jobs", response_model=JobDocument, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AzureClients = Depends(get_azure_clients),
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
def get_job(jobId: str) -> JobDocument:
    job = jobs.get(jobId)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/v1/jobs/{jobId}/summary")
def get_job_summary(jobId: str) -> dict[str, object]:
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
def submit_job_result(jobId: str, result: ResultEnvelope, _: AzureClients = Depends(get_azure_clients)) -> dict[str, str]:
    if jobId != result.job_id:
        raise HTTPException(status_code=400, detail="Path jobId must match result jobId")
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    # TODO: Validate lease token, persist result to Cosmos, and ingest normalized summaries into Log Analytics.
    results[jobId] = result
    jobs[jobId].status = result.status
    artifact_index[jobId] = [artifact.model_dump(by_alias=True) for artifact in result.artifacts]
    return {"status": "accepted"}


@app.get("/api/v1/jobs/{jobId}/artifacts")
def get_job_artifacts(jobId: str) -> dict[str, object]:
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"jobId": jobId, "artifacts": artifact_index.get(jobId, [])}


@app.post("/api/v1/jobs/{jobId}/followups", response_model=JobDocument, status_code=status.HTTP_201_CREATED)
def request_followup(jobId: str, request: JobCreateRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> JobDocument:
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
def create_approval(request: ApprovalRequest, _: AzureClients = Depends(get_azure_clients)) -> ApprovalRequest:
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
def get_policy() -> dict[str, object]:
    # TODO: Retrieve cloud policy from Cosmos/App Configuration.
    return {"policyVersion": POLICY_VERSION, "toolPolicy": "placeholder"}


@app.get("/api/v1/admin/config")
def get_admin_config() -> dict[str, object]:
    # TODO: Enforce FarSight Admin role and read settings from App Configuration.
    return {"retentionDays": {"jobs": 30, "artifacts": 30, "logs": 90}, "apimEnabled": False}


@app.put("/api/v1/admin/config", status_code=status.HTTP_204_NO_CONTENT)
def update_admin_config(config: dict[str, object]) -> Response:
    # TODO: Validate admin config schema, write App Configuration, and audit changes.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
