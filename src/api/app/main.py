from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any
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
from .dependencies import (
    AzureClients,
    get_artifact_index_container,
    get_audit_events_container,
    get_azure_clients,
    get_approvals_container,
    get_blob_service_client,
    get_devices_container,
    get_investigations_container,
    get_jobs_container,
)
from .models import (
    AuditEvent,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    ArtifactCommitRequest,
    ArtifactPrepareRequest,
    ArtifactPrepareResponse,
    ArtifactUploadRequest,
    CheckInRequest,
    CheckInResponse,
    DeviceConfig,
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

# In-memory fallback stores (used when FARSIGHT_COSMOS_ENDPOINT is not set).
jobs: dict[str, JobDocument] = {}
results: dict[str, ResultEnvelope] = {}
approvals: dict[str, ApprovalRequest] = {}
artifact_index: dict[str, list[dict[str, object]]] = {}
audit_events: list[AuditEvent] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def actor_display(actor: AdminActor) -> str:
    return actor.actor_name or actor.actor_id


def _device_checkin_interval_seconds(device_record: dict[str, Any] | None, default_seconds: int = 300) -> int:
    """Return the effective collector cadence for a device."""
    if not device_record:
        return default_seconds
    pending = device_record.get("pendingConfig") or {}
    interval_seconds = pending.get("checkInIntervalSeconds")
    if interval_seconds is not None:
        try:
            return max(60, int(interval_seconds))
        except (TypeError, ValueError):
            return default_seconds
    task_minutes = pending.get("scheduledTaskIntervalMinutes")
    if task_minutes is not None:
        try:
            return max(60, int(task_minutes) * 60)
        except (TypeError, ValueError):
            return default_seconds
    return default_seconds


def _cosmos_upsert(container: Any, doc: Any) -> None:
    container.upsert_item(doc.model_dump(by_alias=True, mode="json"))


def _query_jobs_for_device(container: Any, device_id: str, job_status: JobStatus | None = None) -> list[dict[str, Any]]:
    if job_status is not None:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId AND c.status = @status",
            parameters=[{"name": "@deviceId", "value": device_id}, {"name": "@status", "value": job_status.value}],
            partition_key=device_id,
        ))
    else:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId",
            parameters=[{"name": "@deviceId", "value": device_id}],
            partition_key=device_id,
        ))
    return items


def _get_job_from_cosmos(container: Any, job_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return (item_dict, etag) or (None, None) if not found."""
    items = list(container.query_items(
        query="SELECT * FROM c WHERE c.jobId = @jobId",
        parameters=[{"name": "@jobId", "value": job_id}],
        enable_cross_partition_query=True,
    ))
    if not items:
        return None, None
    item = items[0]
    return item, item.get("_etag")


def append_audit_event(action: str, actor: AdminActor, target: str, decision: str = "allowed", reason: str | None = None) -> None:
    event = AuditEvent(
        id=f"audit-{uuid4()}",
        eventType="policy-admin",
        action=action,
        actorId=actor.actor_id,
        actorName=actor.actor_name,
        target=target,
        decision=decision,
        reason=reason,
    )
    container = get_audit_events_container()
    if container is not None:
        # correlationId is the partition key; use actor_id as fallback if absent.
        item = event.model_dump(by_alias=True, mode="json")
        if not item.get("correlationId"):
            item["correlationId"] = actor.actor_id
        container.upsert_item(item)
    else:
        audit_events.append(event)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-api"}


# ---------------------------------------------------------------------------
# Collector (device mTLS)
# ---------------------------------------------------------------------------

@app.post("/api/v1/devices/checkin", response_model=CheckInResponse)
def check_in(
    request: CheckInRequest,
    device: DeviceCaller = Depends(require_device_cert),
    _: AzureClients = Depends(get_azure_clients),
) -> CheckInResponse:
    require_bound_device_id(device, request.device_id)
    lease = None
    now = _utc_now()
    next_check_in_after_seconds = 300

    # Record heartbeat in the devices container; preserve pendingConfig across upserts.
    pending_config: DeviceConfig | None = None
    devices_container = get_devices_container()
    if devices_container is not None:
        # Read existing record via cross-partition query to preserve pendingConfig.
        # (Container is partitioned by tenantDeviceId, not deviceId.)
        existing: dict[str, Any] = _get_device_record(devices_container, request.device_id) or {}
        device_record = {
            **existing,
            "id": request.device_id,
            "tenantDeviceId": f"{request.tenant_id}:{request.device_id}",
            "deviceId": request.device_id,
            "tenantId": request.tenant_id,
            "hostname": request.hostname or request.device_id,
            "collectorVersion": request.collector_version,
            "manifestVersion": request.manifest_version,
            "hostnameHash": request.hostname_hash,
            "os": request.os.model_dump(by_alias=True, mode="json") if request.os else {},
            "lastCheckinUtc": now.isoformat(),
            "lastJobId": request.last_job_id,
            "appliedConfigVersion": request.applied_config_version,
        }
        try:
            devices_container.upsert_item(device_record)
        except Exception:
            pass  # Non-fatal — checkin still proceeds

        # Clean up any pre-staged placeholder records now that the device has checked in for real.
        _delete_device_placeholders(devices_container, request.device_id)

        # Send pendingConfig if it exists and the client hasn't applied it yet.
        raw_cfg = device_record.get("pendingConfig")
        next_check_in_after_seconds = _device_checkin_interval_seconds(device_record)
        if raw_cfg:
            cfg_version = raw_cfg.get("configVersion")
            if cfg_version and cfg_version != request.applied_config_version:
                try:
                    pending_config = DeviceConfig(**{
                        k: v for k, v in raw_cfg.items() if not k.startswith("_")
                    })
                except Exception:
                    pass

    container = get_jobs_container()
    if container is not None:
        # Reset any expired leases back to Queued before scanning for available jobs.
        lease_timeout = timedelta(minutes=10)
        leased_items = _query_jobs_for_device(container, request.device_id, JobStatus.leased)
        for leased in leased_items:
            leased_at_raw = leased.get("leasedAtUtc")
            if leased_at_raw:
                try:
                    leased_at = datetime.fromisoformat(leased_at_raw.replace("Z", "+00:00"))
                    if now - leased_at > lease_timeout:
                        leased["status"] = JobStatus.queued.value
                        leased.pop("leaseToken", None)
                        leased.pop("leasedAtUtc", None)
                        try:
                            container.replace_item(item=leased["id"], body=leased, if_match=leased.get("_etag"))
                        except Exception:
                            pass  # Concurrency conflict — another replica may have handled it
                except (ValueError, TypeError):
                    pass

        # Atomic lease transition using Cosmos ETag optimistic concurrency.
        queued_items = _query_jobs_for_device(container, request.device_id, JobStatus.queued)
        if queued_items:
            item = queued_items[0]
            etag = item.get("_etag")
            item["status"] = JobStatus.leased.value
            token = f"lease-{uuid4()}"
            item["leaseToken"] = token
            item["leasedAtUtc"] = now.isoformat()
            try:
                container.replace_item(item=item["id"], body=item, if_match=etag)
            except Exception:
                item = None
            if item:
                lease = LeaseOffer(
                    jobId=item["jobId"],
                    leaseToken=token,
                    leaseUntilUtc=now + timedelta(minutes=10),
                )
    else:
        available = next(
            (job for job in jobs.values() if job.device_id == request.device_id and job.status == JobStatus.queued),
            None,
        )
        if available:
            available.status = JobStatus.leased
            lease = LeaseOffer(
                jobId=available.job_id,
                leaseToken=f"lease-{uuid4()}",
                leaseUntilUtc=now + timedelta(minutes=10),
            )
    return CheckInResponse(
        policyVersion=POLICY_VERSION,
        manifestVersion=MANIFEST_VERSION,
        nextCheckInAfterSeconds=next_check_in_after_seconds,
        jobAvailable=lease is not None,
        job=lease,
        pendingConfig=pending_config,
    )


@app.get("/api/v1/devices")
def list_devices(
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, object]:
    """Return registered devices with their last checkin timestamp for heartbeat monitoring."""
    container = get_devices_container()
    if container is not None:
        items = list(container.query_items(
            query="SELECT * FROM c ORDER BY c.lastCheckinUtc DESC OFFSET 0 LIMIT 200",
            enable_cross_partition_query=True,
        ))
        return {"devices": items, "total": len(items)}
    return {"devices": [], "total": 0}


def _get_device_record(container: Any, device_id: str) -> dict[str, Any] | None:
    """Fetch a device record by deviceId using a cross-partition query.
    Returns the most-recently-checked-in real record, preferring non-placeholder entries."""
    try:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId",
            parameters=[{"name": "@deviceId", "value": device_id}],
            enable_cross_partition_query=True,
        ))
        if not items:
            return None
        # Prefer real records (tenantDeviceId not starting with "unknown:") sorted by lastCheckinUtc desc.
        real = [i for i in items if not (i.get("tenantDeviceId") or "").startswith("unknown:")]
        return sorted(real or items, key=lambda i: i.get("lastCheckinUtc") or "", reverse=True)[0]
    except Exception:
        return None


def _delete_device_placeholders(container: Any, device_id: str) -> None:
    """Delete any placeholder records (tenantDeviceId = unknown:*) for a device after it checks in."""
    try:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId AND STARTSWITH(c.tenantDeviceId, 'unknown:')",
            parameters=[{"name": "@deviceId", "value": device_id}],
            enable_cross_partition_query=True,
        ))
        for item in items:
            try:
                container.delete_item(item=item["id"], partition_key=item.get("tenantDeviceId"))
            except Exception:
                pass
    except Exception:
        pass


@app.get("/api/v1/admin/devices/{deviceId}/config")
def get_device_config(deviceId: str, _: AdminActor = Depends(require_admin_actor)) -> dict[str, Any]:
    """Return the pending remote configuration for a device (if any). Returns {} if the device is unknown."""
    container = get_devices_container()
    if container is None:
        raise HTTPException(status_code=503, detail="Devices store unavailable.")
    record = _get_device_record(container, deviceId)
    return (record or {}).get("pendingConfig") or {}


@app.delete("/api/v1/admin/devices/{deviceId}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(deviceId: str, _: AdminActor = Depends(require_admin_actor)) -> Response:
    """Remove a stale device record (e.g. an old GUID-based entry after renaming to hostname)."""
    container = get_devices_container()
    if container is None:
        raise HTTPException(status_code=503, detail="Devices store unavailable.")
    try:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId",
            parameters=[{"name": "@deviceId", "value": deviceId}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Query failed: {exc}") from exc
    if not items:
        raise HTTPException(status_code=404, detail="Device not found.")
    for item in items:
        try:
            container.delete_item(item=item["id"], partition_key=item.get("tenantDeviceId"))
        except Exception:
            pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.put("/api/v1/admin/devices/{deviceId}/config", status_code=status.HTTP_204_NO_CONTENT)
def set_device_config(deviceId: str, config: DeviceConfig, _: AdminActor = Depends(require_admin_actor)) -> Response:
    """Push a new remote configuration to a device. Creates a placeholder record if the device hasn't checked in yet."""
    container = get_devices_container()
    if container is None:
        raise HTTPException(status_code=503, detail="Devices store unavailable.")
    record = _get_device_record(container, deviceId)
    if record is None:
        # Pre-stage config before the device first checks in.
        record = {
            "id": deviceId,
            "tenantDeviceId": f"unknown:{deviceId}",
            "deviceId": deviceId,
            "hostname": deviceId,
        }
    config_dict = config.model_dump(by_alias=True, mode="json", exclude_none=True)
    config_dict["configVersion"] = _utc_now().isoformat()
    record["pendingConfig"] = config_dict
    try:
        container.upsert_item(record)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cosmos update failed: {exc}") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/devices/{deviceId}/jobs")
def get_device_jobs(deviceId: str, device: DeviceCaller = Depends(require_device_cert)) -> list[JobDocument]:
    require_bound_device_id(device, deviceId)
    container = get_jobs_container()
    if container is not None:
        items = _query_jobs_for_device(container, deviceId)
        return [JobDocument.model_validate(item) for item in items]
    return [job for job in jobs.values() if job.device_id == deviceId]


@app.get("/api/v1/devices/{deviceId}/policy")
def get_device_policy(
    deviceId: str,
    device: DeviceCaller = Depends(require_device_cert),
    repository: PolicyRepository = Depends(get_policy_repository),
) -> dict[str, object]:
    require_bound_device_id(device, deviceId)
    try:
        policy_doc = repository.get("farsight-tool-policy")
        return {
            "deviceId": deviceId,
            "policyVersion": policy_doc.version,
            "policyId": policy_doc.policy_id,
        }
    except KeyError:
        return {"deviceId": deviceId, "policyVersion": POLICY_VERSION}


@app.get("/api/v1/devices/{deviceId}/investigations")
def get_device_investigations(
    deviceId: str,
    _: WorkloadCaller = Depends(require_workload_caller),
) -> dict[str, object]:
    container = get_investigations_container()
    if container is not None:
        # investigations partition key is /incidentId — cross-partition query required.
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId ORDER BY c._ts DESC OFFSET 0 LIMIT 50",
            parameters=[{"name": "@deviceId", "value": deviceId}],
            enable_cross_partition_query=True,
        ))
        return {"deviceId": deviceId, "investigations": items}
    return {"deviceId": deviceId, "investigations": []}


# ---------------------------------------------------------------------------
# Jobs (workload callers / SRE agent gateway)
# ---------------------------------------------------------------------------

@app.post("/api/v1/jobs", response_model=JobDocument, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: AzureClients = Depends(get_azure_clients),
    __: WorkloadCaller = Depends(require_workload_caller),
) -> JobDocument:
    container = get_jobs_container()
    if container is not None and idempotency_key:
        # Check for an existing job with the same idempotency key and device.
        existing_items = list(container.query_items(
            query="SELECT * FROM c WHERE c.deviceId = @deviceId AND c.idempotencyKey = @key",
            parameters=[
                {"name": "@deviceId", "value": request.device_id},
                {"name": "@key", "value": idempotency_key},
            ],
            partition_key=request.device_id,
        ))
        if existing_items:
            return JobDocument.model_validate(existing_items[0])

    job_id = f"job-{uuid4()}"
    initial_status = request.status or (
        JobStatus.waiting_approval if request.approval_required or request.approval_status == ApprovalStatus.pending else JobStatus.queued
    )
    if initial_status == JobStatus.waiting_approval and not request.approval_id:
        raise HTTPException(status_code=400, detail="approvalId is required for waiting_approval jobs.")

    job = JobDocument(
        id=job_id,
        jobId=job_id,
        deviceId=request.device_id,
        incidentId=request.incident_id,
        correlationId=request.correlation_id,
        taskType=request.task_type,
        parameters=request.parameters,
        riskLevel=request.risk_level,
        approvalRequired=request.approval_required,
        approvalStatus=request.approval_status,
        approvalId=request.approval_id,
        status=initial_status,
        policyVersion=POLICY_VERSION,
        manifestVersion=MANIFEST_VERSION,
        expiresAtUtc=request.expires_at_utc,
        requestedBy=request.requested_by,
    )
    if container is not None:
        item = job.model_dump(by_alias=True, mode="json")
        if idempotency_key:
            item["idempotencyKey"] = idempotency_key
        container.upsert_item(item)
    else:
        jobs[job_id] = job

    return job


@app.get("/api/v1/jobs/{jobId}", response_model=JobDocument)
def get_job(jobId: str, device: DeviceCaller = Depends(require_device_cert)) -> JobDocument:
    container = get_jobs_container()
    if container is not None:
        item, _ = _get_job_from_cosmos(container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job = JobDocument.model_validate(item)
        require_bound_device_id(device, job.device_id)
        return job
    job = jobs.get(jobId)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    require_bound_device_id(device, job.device_id)
    return job


@app.get("/api/v1/jobs/{jobId}/summary")
def get_job_summary(jobId: str, _: WorkloadCaller = Depends(require_workload_caller)) -> dict[str, object]:
    container = get_jobs_container()
    if container is not None:
        item, _ = _get_job_from_cosmos(container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "jobId": jobId,
            "status": item.get("status"),
            "approvalRequired": item.get("approvalRequired", False),
            "approvalStatus": item.get("approvalStatus"),
            "approvalId": item.get("approvalId"),
            "summary": item.get("resultSummary") or {},
        }
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    result = results.get(jobId)
    job = jobs[jobId]
    return {
        "jobId": jobId,
        "status": job.status,
        "approvalRequired": job.approval_required,
        "approvalStatus": job.approval_status,
        "approvalId": job.approval_id,
        "summary": result.summary if result else {},
    }


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
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        item, etag = _get_job_from_cosmos(jobs_container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job_device_id = item.get("deviceId", "")
        require_bound_device_id(device, job_device_id)
        require_bound_device_id(device, result.device_id)
        # Persist result summary into the job document.
        item["status"] = result.status.value
        item["resultSummary"] = result.summary
        item["resultFindings"] = [f.model_dump(by_alias=True, mode="json") for f in result.findings]
        item["completedAtUtc"] = result.completed_at_utc.isoformat()
        jobs_container.replace_item(item=item["id"], body=item, if_match=etag)
        devices_container = get_devices_container()
        if devices_container is not None and job_device_id:
            device_item = _get_device_record(devices_container, job_device_id)
            if device_item is not None:
                device_item["lastJobId"] = jobId
                device_item["updatedAt"] = _utc_now().isoformat()
                devices_container.upsert_item(device_item)
    else:
        if jobId not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        job = jobs[jobId]
        require_bound_device_id(device, job.device_id)
        require_bound_device_id(device, result.device_id)
        results[jobId] = result
        jobs[jobId].status = result.status
        artifact_index[jobId] = [artifact.model_dump(by_alias=True) for artifact in result.artifacts]
        # In-memory fallback does not persist device documents.

    # Persist artifact metadata to artifactIndex container.
    ai_container = get_artifact_index_container()
    if ai_container is not None and result.artifacts:
        for artifact in result.artifacts:
            existing: dict[str, Any] = {}
            try:
                existing = ai_container.read_item(item=f"{jobId}:{artifact.artifact_id}", partition_key=jobId)
            except Exception:
                pass
            ai_item = {
                **existing,
                **artifact.model_dump(by_alias=True, mode="json"),
            }
            ai_item["id"] = f"{jobId}:{artifact.artifact_id}"
            ai_item["jobId"] = jobId
            ai_container.upsert_item(ai_item)
    elif not ai_container:
        artifact_index[jobId] = [artifact.model_dump(by_alias=True) for artifact in result.artifacts]

    return {"status": "accepted"}


@app.get("/api/v1/jobs/{jobId}/artifacts")
def get_job_artifacts(jobId: str, _: WorkloadCaller = Depends(require_workload_caller)) -> dict[str, object]:
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        item, _ = _get_job_from_cosmos(jobs_container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
    else:
        if jobId not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")

    ai_container = get_artifact_index_container()
    if ai_container is not None:
        artifacts = list(ai_container.query_items(
            query="SELECT * FROM c WHERE c.jobId = @jobId",
            parameters=[{"name": "@jobId", "value": jobId}],
            partition_key=jobId,
        ))
        return {"jobId": jobId, "artifacts": artifacts}
    return {"jobId": jobId, "artifacts": artifact_index.get(jobId, [])}


@app.post("/api/v1/jobs/{jobId}/followups", response_model=JobDocument, status_code=status.HTTP_201_CREATED)
def request_followup(
    jobId: str,
    request: JobCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    azure_clients: AzureClients = Depends(get_azure_clients),
    caller: WorkloadCaller = Depends(require_workload_caller),
) -> JobDocument:
    # Verify parent job exists.
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        item, _ = _get_job_from_cosmos(jobs_container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Parent job not found")
    elif jobId not in jobs:
        raise HTTPException(status_code=404, detail="Parent job not found")
    return create_job(request, idempotency_key, azure_clients, caller)


# ---------------------------------------------------------------------------
# Artifacts (Phase 3 — Blob SAS)
# ---------------------------------------------------------------------------

def _load_artifact_blob(jobId: str, artifactId: str, *, max_bytes: int) -> tuple[bytes, str, str, int, str]:
    """Resolve and download an artifact blob.

    Returns (raw_bytes, file_name, content_type, size_bytes, blob_name).
    Raises HTTPException on missing storage, missing blob, or oversize.
    Shared by the workload-caller download endpoint (base64 JSON) and the
    admin-console download endpoint (binary attachment).
    """
    blob_client = get_blob_service_client()
    if blob_client is None:
        raise HTTPException(
            status_code=503,
            detail="Artifact download requires Blob Storage (FARSIGHT_BLOB_ACCOUNT_URL not configured).",
        )

    ai_container = get_artifact_index_container()
    blob_name: str | None = None
    artifact_file_name: str | None = None
    content_type = ""
    if ai_container is not None:
        try:
            item = ai_container.read_item(item=f"{jobId}:{artifactId}", partition_key=jobId)
            blob_name = item.get("blobName")
            artifact_file_name = item.get("name")
            content_type = (item.get("contentType") or "").lower()
        except Exception:
            pass

    container_name = os.getenv("FARSIGHT_BLOB_ARTIFACTS_CONTAINER", "artifacts")
    if not blob_name:
        if artifact_file_name:
            blob_name = f"{jobId}/{artifactId}/{artifact_file_name}"
        else:
            blob_name = f"{jobId}/{artifactId}"

    try:
        blob = blob_client.get_blob_client(container=container_name, blob=blob_name)
        props = blob.get_blob_properties()
        size_bytes = props.size
        content_type = (props.content_settings.content_type or content_type or "").lower()
        if not artifact_file_name:
            artifact_file_name = blob_name.split("/")[-1] or f"{artifactId}.bin"
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Artifact blob not found: {exc}") from exc

    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact size {size_bytes} bytes exceeds the maximum allowed {max_bytes} bytes for download.",
        )

    try:
        raw = blob.download_blob().readall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to download artifact: {exc}") from exc

    return raw, artifact_file_name, content_type or "application/octet-stream", size_bytes, blob_name


@app.get("/api/v1/jobs/{jobId}/artifacts/{artifactId}/download")
def download_artifact_file(
    jobId: str,
    artifactId: str,
    _: WorkloadCaller = Depends(require_workload_caller),
) -> dict[str, object]:
    """Download an artifact as base64 for agent-side local workspace storage."""
    max_bytes = int(os.getenv("FARSIGHT_ARTIFACT_MAX_DOWNLOAD_BYTES", str(50 * 1024 * 1024)))
    raw, artifact_file_name, content_type, size_bytes, blob_name = _load_artifact_blob(
        jobId, artifactId, max_bytes=max_bytes
    )
    return {
        "jobId": jobId,
        "artifactId": artifactId,
        "blobName": blob_name,
        "fileName": artifact_file_name,
        "contentType": content_type,
        "sizeBytes": size_bytes,
        "contentBase64": base64.b64encode(raw).decode("ascii"),
    }


@app.get("/api/v1/jobs/{jobId}/artifacts/{artifactId}/content")
def get_artifact_content(
    jobId: str,
    artifactId: str,
    _: WorkloadCaller = Depends(require_workload_caller),
) -> dict[str, object]:
    """Return artifact content for agent analysis.

    Only JSON and plain-text artifacts are supported. Content is capped at
    FARSIGHT_ARTIFACT_MAX_CONTENT_BYTES (default 256 KB) to keep agent
    context size manageable. Larger artifacts should be summarized or
    queried via artifact metadata only.
    """
    max_bytes = int(os.getenv("FARSIGHT_ARTIFACT_MAX_CONTENT_BYTES", str(256 * 1024)))
    blob_client = get_blob_service_client()
    if blob_client is None:
        raise HTTPException(
            status_code=503,
            detail="Artifact content retrieval requires Blob Storage (FARSIGHT_BLOB_ACCOUNT_URL not configured).",
        )

    # Look up the blob name from the artifact index (set by commit after upload).
    ai_container = get_artifact_index_container()
    blob_name: str | None = None
    artifact_file_name: str | None = None
    if ai_container is not None:
        try:
            item = ai_container.read_item(item=f"{jobId}:{artifactId}", partition_key=jobId)
            blob_name = item.get("blobName")
            artifact_file_name = item.get("name")  # e.g. "job-xxx-services.json"
        except Exception:
            pass

    container_name = os.getenv("FARSIGHT_BLOB_ARTIFACTS_CONTAINER", "artifacts")
    if not blob_name:
        # Fallback: try 3-level path first (prepare convention), then 2-level.
        if artifact_file_name:
            blob_name = f"{jobId}/{artifactId}/{artifact_file_name}"
        else:
            blob_name = f"{jobId}/{artifactId}"

    try:
        blob = blob_client.get_blob_client(container=container_name, blob=blob_name)
        props = blob.get_blob_properties()
        content_type = (props.content_settings.content_type or "").lower()
        size_bytes = props.size
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Artifact blob not found: {exc}") from exc

    # Only serve text/JSON artifacts to the agent.
    allowed_content_types = {"application/json", "text/plain", "text/json"}
    is_allowed = any(ct in content_type for ct in allowed_content_types) or content_type == ""
    if not is_allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Artifact content type '{content_type}' is not supported for agent analysis. Only JSON and plain text artifacts can be retrieved.",
        )

    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact size {size_bytes} bytes exceeds the maximum allowed {max_bytes} bytes for agent content retrieval. Use retrieve_artifact_metadata to inspect the artifact.",
        )

    try:
        raw = blob.download_blob().readall()
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read artifact content: {exc}") from exc

    # Try to parse as JSON for richer agent consumption.
    import json as _json
    try:
        content = _json.loads(text)
        content_format = "json"
    except _json.JSONDecodeError:
        content = text
        content_format = "text"

    return {
        "jobId": jobId,
        "artifactId": artifactId,
        "blobName": blob_name,
        "contentType": content_type,
        "contentFormat": content_format,
        "sizeBytes": size_bytes,
        "content": content,
    }


@app.get("/api/v1/jobs/{jobId}/artifacts/{artifactId}/zip-entry")
def get_zip_artifact_entry(
    jobId: str,
    artifactId: str,
    file_path: str | None = None,
    tail_lines: int | None = None,
    _: WorkloadCaller = Depends(require_workload_caller),
) -> dict[str, object]:
    """List ZIP contents or extract a specific file from a ZIP artifact.

    If file_path is not provided, returns the list of entries in the ZIP archive.
    If file_path is provided, extracts and returns that file's text content
    (capped at FARSIGHT_ARTIFACT_MAX_CONTENT_BYTES, default 256 KB).

    If tail_lines is provided, only the last N lines of the file are returned,
    bypassing the size cap. This allows reading the tail of large log files.
    """
    import io
    import zipfile
    import json as _json

    max_bytes = int(os.getenv("FARSIGHT_ARTIFACT_MAX_CONTENT_BYTES", str(256 * 1024)))
    max_zip_bytes = int(os.getenv("FARSIGHT_ARTIFACT_MAX_ZIP_BYTES", str(50 * 1024 * 1024)))  # 50 MB
    blob_client = get_blob_service_client()
    if blob_client is None:
        raise HTTPException(
            status_code=503,
            detail="Artifact retrieval requires Blob Storage (FARSIGHT_BLOB_ACCOUNT_URL not configured).",
        )

    # Resolve blob name from artifact index
    ai_container = get_artifact_index_container()
    blob_name: str | None = None
    artifact_file_name: str | None = None
    if ai_container is not None:
        try:
            item = ai_container.read_item(item=f"{jobId}:{artifactId}", partition_key=jobId)
            blob_name = item.get("blobName")
            artifact_file_name = item.get("name")
        except Exception:
            pass

    container_name = os.getenv("FARSIGHT_BLOB_ARTIFACTS_CONTAINER", "artifacts")
    if not blob_name:
        if artifact_file_name:
            blob_name = f"{jobId}/{artifactId}/{artifact_file_name}"
        else:
            blob_name = f"{jobId}/{artifactId}"

    try:
        blob = blob_client.get_blob_client(container=container_name, blob=blob_name)
        props = blob.get_blob_properties()
        size_bytes = props.size
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Artifact blob not found: {exc}") from exc

    if size_bytes > max_zip_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"ZIP artifact size {size_bytes} bytes exceeds the maximum allowed {max_zip_bytes} bytes.",
        )

    try:
        raw = blob.download_blob().readall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to download artifact: {exc}") from exc

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail=f"Artifact is not a valid ZIP file: {exc}") from exc

    # List mode: return file entries
    if not file_path:
        entries = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries.append({
                "path": info.filename,
                "sizeBytes": info.file_size,
                "compressedBytes": info.compress_size,
            })
        return {
            "jobId": jobId,
            "artifactId": artifactId,
            "mode": "list",
            "entryCount": len(entries),
            "entries": entries,
        }

    # Extract mode: return specific file content
    matching = [info for info in zf.infolist() if info.filename == file_path]
    if not matching:
        # Try case-insensitive match
        matching = [info for info in zf.infolist() if info.filename.lower() == file_path.lower()]
    if not matching:
        available = [info.filename for info in zf.infolist() if not info.is_dir()]
        raise HTTPException(
            status_code=404,
            detail=f"File '{file_path}' not found in ZIP. Available entries: {available[:20]}",
        )

    entry = matching[0]

    # If tail_lines is requested, we can read large files but return only the tail
    if tail_lines is not None:
        tail_lines = max(1, min(tail_lines, 10000))  # Cap at 10k lines
    elif entry.file_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Entry '{file_path}' size {entry.file_size} bytes exceeds max {max_bytes} bytes. "
                   f"Use tail_lines parameter to read the last N lines of large files.",
        )

    try:
        entry_bytes = zf.read(entry.filename)
        text = entry_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read ZIP entry: {exc}") from exc

    # Apply tail_lines if requested
    truncated = False
    total_lines = None
    if tail_lines is not None:
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        if len(lines) > tail_lines:
            lines = lines[-tail_lines:]
            truncated = True
        text = "".join(lines)
        # Final output size check (tail should fit in context)
        if len(text.encode("utf-8")) > max_bytes:
            # Further trim to fit
            while len(text.encode("utf-8")) > max_bytes and lines:
                lines.pop(0)
                truncated = True
            text = "".join(lines)

    # Try JSON parse
    try:
        content = _json.loads(text)
        content_format = "json"
    except _json.JSONDecodeError:
        content = text
        content_format = "text"

    result: dict[str, object] = {
        "jobId": jobId,
        "artifactId": artifactId,
        "mode": "extract",
        "filePath": entry.filename,
        "contentFormat": content_format,
        "sizeBytes": entry.file_size,
        "content": content,
    }
    if tail_lines is not None:
        result["tailLines"] = tail_lines
        result["totalLines"] = total_lines
        result["truncated"] = truncated
    return result


@app.post("/api/v1/artifacts/prepare", status_code=status.HTTP_201_CREATED)
def prepare_artifact_upload(request: ArtifactPrepareRequest, _: AzureClients = Depends(get_azure_clients)) -> ArtifactPrepareResponse:
    blob_client = get_blob_service_client()
    expires = _utc_now() + timedelta(minutes=10)
    if blob_client is not None:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas, UserDelegationKey
        container_name = os.getenv("FARSIGHT_BLOB_ARTIFACTS_CONTAINER", "artifacts")
        blob_name = f"{request.job_id}/{request.artifact_id}/{request.file_name}"
        # Get a user delegation key (valid for 10 min, requires Storage Blob Delegator role).
        start = _utc_now() - timedelta(seconds=30)
        try:
            user_delegation_key: UserDelegationKey = blob_client.get_user_delegation_key(start, expires)
            account_name = blob_client.account_name
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=container_name,
                blob_name=blob_name,
                user_delegation_key=user_delegation_key,
                permission=BlobSasPermissions(write=True, create=True),
                expiry=expires,
            )
            upload_url = f"{blob_client.url.rstrip('/')}/{container_name}/{blob_name}?{sas_token}"
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to generate artifact upload URL: {exc}") from exc
        return ArtifactPrepareResponse(
            uploadUrl=upload_url,
            expiresAtUtc=expires,
            requiredHeaders={"x-ms-blob-type": "BlockBlob"},
        )
    # Local dev fallback: return a placeholder URL.
    return ArtifactPrepareResponse(
        uploadUrl=f"https://storage.example.invalid/farsight/{request.job_id}/{request.artifact_id}",
        expiresAtUtc=expires,
        requiredHeaders={"x-ms-blob-type": "BlockBlob"},
    )


@app.post("/api/v1/artifacts/upload", status_code=status.HTTP_201_CREATED)
def upload_artifact_via_api(
    request: ArtifactUploadRequest,
    device: DeviceCaller = Depends(require_device_cert),
    _: AzureClients = Depends(get_azure_clients),
) -> dict[str, str]:
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        item, _ = _get_job_from_cosmos(jobs_container, request.job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        require_bound_device_id(device, item.get("deviceId", ""))

    try:
        content = base64.b64decode(request.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Artifact contentBase64 is not valid base64.") from exc

    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256.lower() != request.sha256.lower():
        raise HTTPException(status_code=400, detail="Artifact SHA-256 does not match uploaded content.")

    blob_client = get_blob_service_client()
    if blob_client is None:
        raise HTTPException(status_code=503, detail="Artifact upload requires Blob Storage (FARSIGHT_BLOB_ACCOUNT_URL not configured).")

    container_name = os.getenv("FARSIGHT_BLOB_ARTIFACTS_CONTAINER", "artifacts")
    blob_name = f"{request.job_id}/{request.artifact_id}/{request.file_name}"
    try:
        from azure.storage.blob import ContentSettings
        blob = blob_client.get_blob_client(container=container_name, blob=blob_name)
        blob.upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type=request.content_type),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload artifact via API: {exc}") from exc

    return {"status": "uploaded", "blobName": blob_name, "sha256": actual_sha256}


@app.post("/api/v1/artifacts/commit", status_code=status.HTTP_202_ACCEPTED)
def commit_artifact_upload(request: ArtifactCommitRequest, _: AzureClients = Depends(get_azure_clients)) -> dict[str, str]:
    blob_client = get_blob_service_client()
    if blob_client is not None:
        container_name = os.getenv("FARSIGHT_BLOB_ARTIFACTS_CONTAINER", "artifacts")
        # Use the same 3-level path that prepare_artifact_upload created.
        # If fileName is not provided, fall back to 2-level path.
        if request.file_name:
            blob_name = f"{request.job_id}/{request.artifact_id}/{request.file_name}"
        else:
            blob_name = f"{request.job_id}/{request.artifact_id}"
        try:
            blob = blob_client.get_blob_client(container=container_name, blob=blob_name)
            props = blob.get_blob_properties()
            actual_size = props.size
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Artifact blob not found: {exc}") from exc

        if not request.uploaded:
            raise HTTPException(status_code=400, detail="Artifact commit requires uploaded=true.")

        # Update Cosmos artifactIndex with confirmed metadata including the blob name.
        ai_container = get_artifact_index_container()
        if ai_container is not None:
            # Merge with any existing metadata (e.g. kind, name from result envelope).
            existing: dict[str, Any] = {}
            try:
                existing = ai_container.read_item(
                    item=f"{request.job_id}:{request.artifact_id}",
                    partition_key=request.job_id,
                )
            except Exception:
                pass
            ai_item = {
                **existing,
                "id": f"{request.job_id}:{request.artifact_id}",
                "jobId": request.job_id,
                "artifactId": request.artifact_id,
                "sha256": request.sha256,
                "sizeBytes": actual_size,
                "blobName": blob_name,
                "committedAtUtc": _utc_now().isoformat(),
            }
            ai_container.upsert_item(ai_item)

    return {"status": "accepted", "artifactId": request.artifact_id}


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@app.post("/api/v1/approvals", response_model=ApprovalRequest, status_code=status.HTTP_201_CREATED)
def create_approval(
    request: ApprovalRequest,
    _: AzureClients = Depends(get_azure_clients),
    __: WorkloadCaller = Depends(require_workload_caller),
) -> ApprovalRequest:
    container = get_approvals_container()
    if container is not None:
        item = request.model_dump(by_alias=True, mode="json")
        item["id"] = request.approval_id
        container.upsert_item(item)
    else:
        approvals[request.approval_id] = request
    # TODO (Phase 2+): Send Teams notification via configured transport.
    return request


@app.post("/api/v1/approvals/{approvalId}/decision", status_code=status.HTTP_202_ACCEPTED)
def decide_approval(
    approvalId: str,
    decision: ApprovalDecision,
    _: AzureClients = Depends(get_azure_clients),
    __: AdminActor = Depends(require_admin_actor),
) -> dict[str, str]:
    if approvalId != decision.approval_id:
        raise HTTPException(status_code=400, detail="Path approvalId must match decision approvalId")
    container = get_approvals_container()
    if container is not None:
        try:
            item = container.read_item(item=approvalId, partition_key=approvalId)
        except Exception as exc:
            if "NotFound" in type(exc).__name__:
                raise HTTPException(status_code=404, detail="Approval not found") from exc
            raise
        # Persist immutable decision fields; do not overwrite an already-decided approval.
        if item.get("decidedBy"):
            raise HTTPException(status_code=409, detail="Approval has already been decided.")
        item.update(decision.model_dump(by_alias=True, mode="json"))
        item["status"] = decision.decision.value
        container.replace_item(item=approvalId, body=item)

        # Release blocked jobs when approved.
        if decision.decision.value == "approved":
            _release_jobs_for_approval(approvalId)
        elif decision.decision.value == "denied":
            _deny_jobs_for_approval(approvalId, decision.comment)
    else:
        if approvalId not in approvals:
            raise HTTPException(status_code=404, detail="Approval not found")
        approval = approvals[approvalId]
        if approval.decided_by:
            raise HTTPException(status_code=409, detail="Approval has already been decided.")
        approval.status = decision.decision  # type: ignore[misc]
        approval.decided_by = decision.decided_by
        approval.decided_at_utc = decision.decided_at_utc
        approval.comment = decision.comment
        if decision.decision.value == "approved":
            _release_jobs_for_approval(approvalId)
        elif decision.decision.value == "denied":
            _deny_jobs_for_approval(approvalId, decision.comment)
    return {"status": "accepted", "decision": decision.decision.value}


@app.get("/api/v1/admin/approvals")
def admin_list_approvals(
    status_filter: str = "pending",
    limit: int = 100,
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, object]:
    """Return approvals for the admin console."""
    limit = max(1, min(limit, 500))
    container = get_approvals_container()
    if container is not None:
        if status_filter == "all":
            items = list(container.query_items(
                query="SELECT * FROM c ORDER BY c.createdAtUtc DESC OFFSET 0 LIMIT @limit",
                parameters=[{"name": "@limit", "value": limit}],
                enable_cross_partition_query=True,
            ))
        else:
            items = list(container.query_items(
                query="SELECT * FROM c WHERE c.status = @status ORDER BY c.createdAtUtc DESC OFFSET 0 LIMIT @limit",
                parameters=[
                    {"name": "@status", "value": status_filter},
                    {"name": "@limit", "value": limit},
                ],
                enable_cross_partition_query=True,
            ))
        return {"approvals": items, "total": len(items)}

    items = [item for item in approvals.values() if status_filter == "all" or item.status.value == status_filter]
    items.sort(key=lambda item: item.created_at_utc, reverse=True)
    return {"approvals": [item.model_dump(by_alias=True, mode="json") for item in items[:limit]], "total": len(items)}


@app.get("/api/v1/admin/approvals/{approvalId}")
def admin_get_approval(
    approvalId: str,
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, object]:
    container = get_approvals_container()
    if container is not None:
        try:
            item = container.read_item(item=approvalId, partition_key=approvalId)
        except Exception as exc:
            if "NotFound" in type(exc).__name__:
                raise HTTPException(status_code=404, detail="Approval not found") from exc
            raise
        jobs_container = get_jobs_container()
        linked_jobs: list[dict[str, Any]] = []
        if jobs_container is not None:
            linked_jobs = list(jobs_container.query_items(
                query="SELECT * FROM c WHERE c.approvalId = @approvalId ORDER BY c.createdAtUtc DESC",
                parameters=[{"name": "@approvalId", "value": approvalId}],
                enable_cross_partition_query=True,
            ))
        return {"approval": item, "jobs": linked_jobs}

    approval = approvals.get(approvalId)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    linked_jobs = [
        job.model_dump(by_alias=True, mode="json")
        for job in jobs.values()
        if job.approval_id == approvalId
    ]
    return {"approval": approval.model_dump(by_alias=True, mode="json"), "jobs": linked_jobs}


def _release_jobs_for_approval(approval_id: str) -> None:
    """Set approvalStatus=approved on all jobs linked to this approval."""
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        blocked = list(jobs_container.query_items(
            query="SELECT * FROM c WHERE c.approvalId = @approvalId AND c.approvalStatus = 'pending'",
            parameters=[{"name": "@approvalId", "value": approval_id}],
            enable_cross_partition_query=True,
        ))
        for item in blocked:
            item["approvalStatus"] = "approved"
            item["status"] = JobStatus.queued.value
            jobs_container.replace_item(item=item["id"], body=item)
    else:
        for job in jobs.values():
            if getattr(job, "approval_id", None) == approval_id:
                job.approval_status = ApprovalStatus.approved
                job.status = JobStatus.queued


def _deny_jobs_for_approval(approval_id: str, comment: str | None = None) -> None:
    """Mark approval-linked jobs as cancelled when an admin denies approval."""
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        blocked = list(jobs_container.query_items(
            query="SELECT * FROM c WHERE c.approvalId = @approvalId AND c.approvalStatus = 'pending'",
            parameters=[{"name": "@approvalId", "value": approval_id}],
            enable_cross_partition_query=True,
        ))
        for item in blocked:
            item["approvalStatus"] = "denied"
            item["status"] = JobStatus.cancelled.value
            item["cancelledReason"] = comment or "Approval denied by administrator."
            jobs_container.replace_item(item=item["id"], body=item)
    else:
        for job in jobs.values():
            if job.approval_id == approval_id and job.approval_status == ApprovalStatus.pending:
                job.approval_status = ApprovalStatus.denied
                job.status = JobStatus.cancelled


# ---------------------------------------------------------------------------
# Policy management
# ---------------------------------------------------------------------------

@app.get("/api/v1/policy")
def get_policy(
    repository: PolicyRepository = Depends(get_policy_repository),
    _: WorkloadCaller = Depends(require_workload_caller),
) -> PolicyDocument:
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


# ---------------------------------------------------------------------------
# Telemetry and admin (stubs — Phase 4/5)
# ---------------------------------------------------------------------------

@app.post("/api/v1/telemetry/tool-calls", status_code=status.HTTP_202_ACCEPTED)
def ingest_tool_call_event(
    event: dict[str, Any],
    _: WorkloadCaller = Depends(require_workload_caller),
) -> dict[str, str]:
    """Receive a tool-call audit event from the AGT tool gateway."""
    container = get_audit_events_container()
    if container is not None:
        # Ensure required Cosmos fields.
        if "id" not in event:
            event["id"] = f"tc-{uuid4()}"
        if "correlationId" not in event:
            event["correlationId"] = event.get("actorId", "unknown")
        event["eventType"] = "tool-call"
        try:
            container.upsert_item(event)
        except Exception:
            pass  # Non-fatal: telemetry loss is acceptable
    else:
        # In-memory fallback for local dev.
        audit_events.append(AuditEvent(
            id=event.get("id", f"tc-{uuid4()}"),
            event_type="tool-call",
            action=event.get("toolName", "unknown"),
            actor_id=event.get("actorId", "unknown"),
            actor_name=event.get("actorAppId"),
            target=event.get("toolName", "unknown"),
            decision=event.get("decision", "unknown"),
            reason=event.get("reason"),
            correlation_id=event.get("correlationId"),
        ))
    return {"status": "accepted"}


@app.get("/api/v1/telemetry/tool-calls/summary", response_model=ToolCallTelemetrySummary)
def get_tool_call_summary(window: str = "24h") -> ToolCallTelemetrySummary:
    """Aggregate tool-call audit events within the specified time window.
    
    Args:
        window: Time window for aggregation. Supported values: "24h", "7d", "30d", "all"
    """
    from collections import defaultdict

    # Map window parameter to timedelta
    window_map = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "all": None,  # No cutoff
    }
    
    # Validate and get the time delta
    time_delta = window_map.get(window)
    if time_delta is None and window != "all":
        # Default to 24h if invalid window provided
        time_delta = timedelta(hours=24)
        normalized_window = "24h"
    else:
        normalized_window = window

    container = get_audit_events_container()
    events: list[dict[str, Any]] = []

    if container is not None:
        if normalized_window == "all":
            # No time cutoff
            try:
                events = list(container.query_items(
                    query="SELECT * FROM c WHERE c.eventType = 'tool-call' ORDER BY c.timestampUtc DESC",
                    enable_cross_partition_query=True,
                ))
            except Exception:
                events = []
        else:
            cutoff = (_utc_now() - time_delta).isoformat()
            try:
                events = list(container.query_items(
                    query="SELECT * FROM c WHERE c.eventType = 'tool-call' AND c.timestampUtc >= @cutoff ORDER BY c.timestampUtc DESC",
                    parameters=[{"name": "@cutoff", "value": cutoff}],
                    enable_cross_partition_query=True,
                ))
            except Exception:
                events = []
    else:
        # In-memory fallback: use audit_events list.
        if normalized_window == "all":
            cutoff_dt = None
        else:
            cutoff_dt = _utc_now() - time_delta
        
        events = [
            {"toolName": e.action, "decision": e.decision, "actorId": e.actor_id,
             "timestampUtc": e.created_at_utc.isoformat(), "correlationId": e.correlation_id,
             "policyName": None, "policyVersion": None, "jobId": None}
            for e in audit_events
            if e.event_type == "tool-call" and (cutoff_dt is None or e.created_at_utc >= cutoff_dt)
        ]

    # Aggregate.
    total = len(events)
    allowed = sum(1 for e in events if e.get("decision") == "allow")
    denied = sum(1 for e in events if e.get("decision") == "deny")
    approval_required = sum(1 for e in events if e.get("decision") == "require_approval")
    failed = total - allowed - denied - approval_required

    by_tool_map: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "totalCalls": 0, "allowedCalls": 0, "deniedCalls": 0,
        "approvalRequiredCalls": 0, "failedCalls": 0, "lastSeenUtc": None,
    })
    for e in events:
        tool = e.get("toolName", "unknown")
        entry = by_tool_map[tool]
        entry["totalCalls"] += 1
        decision = e.get("decision", "")
        if decision == "allow":
            entry["allowedCalls"] += 1
        elif decision == "deny":
            entry["deniedCalls"] += 1
        elif decision == "require_approval":
            entry["approvalRequiredCalls"] += 1
        else:
            entry["failedCalls"] += 1
        ts = e.get("timestampUtc")
        if ts and (entry["lastSeenUtc"] is None or ts > entry["lastSeenUtc"]):
            entry["lastSeenUtc"] = ts

    from .models import ToolCallByTool, RecentToolCall
    by_tool = [
        ToolCallByTool(toolName=name, **counts)
        for name, counts in sorted(by_tool_map.items(), key=lambda x: x[1]["totalCalls"], reverse=True)
    ]

    recent = [
        RecentToolCall(
            timestampUtc=e.get("timestampUtc", _utc_now().isoformat()),
            toolName=e.get("toolName", "unknown"),
            decision=e.get("decision", "unknown"),
            actor=e.get("actorId"),
            actorAppId=e.get("actorAppId"),
            policyId=e.get("policyName"),
            policyVersion=e.get("policyVersion"),
            ruleName=e.get("ruleName"),
            reason=e.get("reason"),
            jobId=e.get("jobId"),
            correlationId=e.get("correlationId"),
        )
        for e in events[:50]  # Most recent 50
    ]

    return ToolCallTelemetrySummary(
        window=normalized_window,
        totalCalls=total,
        allowedCalls=allowed,
        deniedCalls=denied,
        approvalRequiredCalls=approval_required,
        failedCalls=failed,
        byTool=by_tool,
        recent=recent,
    )


@app.get("/api/v1/admin/config")
def get_admin_config() -> dict[str, object]:
    # TODO (Phase 5): Read settings from Azure App Configuration.
    return {"retentionDays": {"jobs": 30, "artifacts": 30, "logs": 90}, "apimEnabled": False}


@app.get("/api/v1/admin/jobs")
def admin_list_jobs(
    device_id: str | None = None,
    limit: int = 100,
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, object]:
    """Return recent jobs for admin monitoring. Optionally scoped to a device ID."""
    limit = max(1, min(limit, 500))
    container = get_jobs_container()
    if container is not None:
        if device_id:
            items = list(container.query_items(
                query="SELECT * FROM c WHERE c.deviceId = @deviceId ORDER BY c.createdAtUtc DESC OFFSET 0 LIMIT @limit",
                parameters=[
                    {"name": "@deviceId", "value": device_id},
                    {"name": "@limit", "value": limit},
                ],
                partition_key=device_id,
            ))
        else:
            items = list(container.query_items(
                query="SELECT * FROM c ORDER BY c.createdAtUtc DESC OFFSET 0 LIMIT @limit",
                parameters=[{"name": "@limit", "value": limit}],
                enable_cross_partition_query=True,
            ))
        return {"jobs": items, "total": len(items)}
    # In-memory fallback
    job_list = list(jobs.values())
    if device_id:
        job_list = [j for j in job_list if j.device_id == device_id]
    job_list.sort(key=lambda j: j.created_at_utc, reverse=True)
    return {"jobs": [j.model_dump(by_alias=True, mode="json") for j in job_list[:limit]], "total": len(job_list)}


@app.post("/api/v1/admin/jobs/{jobId}/requeue", status_code=status.HTTP_204_NO_CONTENT)
def requeue_job(jobId: str, _: AdminActor = Depends(require_admin_actor)) -> Response:
    """Force a stuck Leased job back to Queued so the collector can pick it up again."""
    container = get_jobs_container()
    if container is None:
        raise HTTPException(status_code=503, detail="Jobs store unavailable.")
    try:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.jobId = @jobId",
            parameters=[{"name": "@jobId", "value": jobId}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cosmos query failed: {exc}") from exc
    if not items:
        raise HTTPException(status_code=404, detail="Job not found.")
    item = items[0]
    if item.get("status") not in (JobStatus.leased.value, JobStatus.queued.value):
        raise HTTPException(status_code=409, detail=f"Job status is '{item.get('status')}' — only Leased or Queued jobs can be requeued.")
    item["status"] = JobStatus.queued.value
    item.pop("leaseToken", None)
    item.pop("leasedAtUtc", None)
    try:
        container.replace_item(item=item["id"], body=item)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cosmos update failed: {exc}") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/admin/jobs/{jobId}")
def admin_get_job(jobId: str, _: AdminActor = Depends(require_admin_actor)) -> dict[str, object]:
    """Return a single job's detail/summary for the admin console (admin-authenticated)."""
    container = get_jobs_container()
    if container is not None:
        item, _etag = _get_job_from_cosmos(container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "jobId": jobId,
            "status": item.get("status"),
            "approvalRequired": item.get("approvalRequired", False),
            "approvalStatus": item.get("approvalStatus"),
            "approvalId": item.get("approvalId"),
            "summary": item.get("resultSummary") or {},
        }
    if jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    result = results.get(jobId)
    job = jobs[jobId]
    return {
        "jobId": jobId,
        "status": job.status,
        "approvalRequired": job.approval_required,
        "approvalStatus": job.approval_status,
        "approvalId": job.approval_id,
        "summary": result.summary if result else {},
    }


@app.get("/api/v1/admin/jobs/{jobId}/artifacts")
def admin_list_job_artifacts(jobId: str, _: AdminActor = Depends(require_admin_actor)) -> dict[str, object]:
    """Return artifact metadata for a job for the admin console (admin-authenticated)."""
    jobs_container = get_jobs_container()
    if jobs_container is not None:
        item, _etag = _get_job_from_cosmos(jobs_container, jobId)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
    elif jobId not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    ai_container = get_artifact_index_container()
    if ai_container is not None:
        artifacts = list(ai_container.query_items(
            query="SELECT * FROM c WHERE c.jobId = @jobId",
            parameters=[{"name": "@jobId", "value": jobId}],
            partition_key=jobId,
        ))
        return {"jobId": jobId, "artifacts": artifacts}
    return {"jobId": jobId, "artifacts": artifact_index.get(jobId, [])}


@app.get("/api/v1/admin/jobs/{jobId}/artifacts/{artifactId}/download")
def admin_download_artifact_file(
    jobId: str,
    artifactId: str,
    _: AdminActor = Depends(require_admin_actor),
) -> Response:
    """Stream an artifact as a binary attachment for the admin console."""
    max_bytes = int(os.getenv("FARSIGHT_ARTIFACT_MAX_DOWNLOAD_BYTES", str(50 * 1024 * 1024)))
    raw, artifact_file_name, content_type, _size_bytes, _blob_name = _load_artifact_blob(
        jobId, artifactId, max_bytes=max_bytes
    )
    safe_name = artifact_file_name.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
    return Response(content=raw, media_type=content_type or "application/octet-stream", headers=headers)


@app.put("/api/v1/admin/config", status_code=status.HTTP_204_NO_CONTENT)
def update_admin_config(config: dict[str, object]) -> Response:
    # TODO (Phase 5): Write to Azure App Configuration and audit changes.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
