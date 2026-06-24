import base64
import hmac
import json
import os
from pathlib import Path
from hashlib import sha256
from time import time
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Agent-Azure-FarSight Admin BFF", version="0.1.0")
static_root = Path(__file__).resolve().parent / "static"
control_api_base_url = os.environ.get("FARSIGHT_CONTROL_API_BASE_URL", "http://localhost:8000").rstrip("/")
admin_group_object_ids = {item.strip() for item in os.environ.get("FARSIGHT_ADMIN_GROUP_OBJECT_IDS", "").split(",") if item.strip()}
allow_local_admin_fallback = os.environ.get("FARSIGHT_ADMIN_ALLOW_LOCAL_FALLBACK", "").lower() in {"1", "true", "yes"}
api_internal_auth_secret = os.environ.get("FARSIGHT_API_INTERNAL_AUTH_SECRET", "")


def _decode_client_principal(encoded: str | None) -> dict[str, Any] | None:
    if not encoded:
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        return json.loads(base64.b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None


def _principal_claim_values(principal: dict[str, Any] | None, claim_types: set[str]) -> set[str]:
    values: set[str] = set()
    for claim in (principal or {}).get("claims", []):
        if claim.get("typ") in claim_types and claim.get("val"):
            values.add(str(claim["val"]))
    return values


def get_current_admin(
    x_ms_client_principal: str | None = Header(default=None),
    x_ms_client_principal_id: str | None = Header(default=None),
    x_ms_client_principal_name: str | None = Header(default=None),
    x_ms_client_principal_idp: str | None = Header(default=None),
) -> dict[str, Any]:
    principal = _decode_client_principal(x_ms_client_principal)
    if principal is None and allow_local_admin_fallback:
        return {"authenticated": True, "id": "local-admin", "name": "local-admin", "idp": "local", "roles": ["FarSight.Admin"], "groups": []}
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    roles = _principal_claim_values(principal, {"roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"})
    groups = _principal_claim_values(principal, {"groups", "http://schemas.microsoft.com/ws/2008/06/identity/claims/groupsid"})
    if admin_group_object_ids and not groups.intersection(admin_group_object_ids):
        raise HTTPException(status_code=403, detail="FarSight Admin group membership required.")
    return {
        "authenticated": True,
        "id": x_ms_client_principal_id or principal.get("userId"),
        "name": x_ms_client_principal_name or principal.get("userDetails"),
        "idp": x_ms_client_principal_idp or principal.get("identityProvider"),
        "roles": sorted(roles),
        "groups": sorted(groups),
    }


@app.get("/api/bff/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-admin-bff"}


@app.get("/api/bff/me")
def current_user(current_admin: dict[str, Any] = Depends(get_current_admin)) -> dict[str, object]:
    return current_admin


@app.get("/api/bff/config")
def admin_shell_config() -> dict[str, object]:
    # TODO: Load public UI configuration from App Configuration through managed identity.
    return {"apiBasePath": "/api/v1", "environment": "dev"}


async def _control_api(method: str, path: str, actor: str, json: dict[str, Any] | None = None) -> Any:
    # TODO: Add managed identity token exchange for the control API.
    async with httpx.AsyncClient(base_url=control_api_base_url, timeout=15.0) as client:
        response = await client.request(method, path, json=json, headers={"X-FarSight-Admin-Actor": actor})
        response.raise_for_status()
        return response.json() if response.content else None


def _signed_admin_headers(current_admin: dict[str, Any]) -> dict[str, str]:
    if not api_internal_auth_secret:
        raise HTTPException(status_code=500, detail="FARSIGHT_API_INTERNAL_AUTH_SECRET is not configured for admin API calls.")
    actor = str(current_admin["id"])
    name = str(current_admin.get("name") or "")
    groups = ",".join(str(item) for item in current_admin.get("groups", []))
    expires = str(int(time()) + 300)
    payload = "\n".join([actor, name, groups, expires])
    signature = hmac.new(api_internal_auth_secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return {
        "X-FarSight-Admin-Actor": actor,
        "X-FarSight-Admin-Name": name,
        "X-FarSight-Admin-Groups": groups,
        "X-FarSight-Admin-Expires": expires,
        "X-FarSight-Admin-Signature": signature,
    }


async def _control_api_admin(method: str, path: str, current_admin: dict[str, Any], json: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(base_url=control_api_base_url, timeout=15.0) as client:
        response = await client.request(method, path, json=json, headers=_signed_admin_headers(current_admin))
        response.raise_for_status()
        return response.json() if response.content else None


@app.get("/api/bff/policies")
async def list_policies(current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api("GET", "/api/v1/policies", actor=str(current_admin["id"]))


@app.get("/api/bff/policies/{policy_id}")
async def get_active_policy(policy_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api("GET", f"/api/v1/policies/{policy_id}", actor=str(current_admin["id"]))


@app.get("/api/bff/policies/{policy_id}/versions/{version}")
async def get_policy_version(policy_id: str, version: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api("GET", f"/api/v1/policies/{policy_id}/versions/{version}", actor=str(current_admin["id"]))


@app.post("/api/bff/policies/{policy_id}/validate")
async def validate_policy(policy_id: str, body: dict[str, Any], current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api("POST", f"/api/v1/policies/{policy_id}/validate", actor=str(current_admin["id"]), json=body)


@app.put("/api/bff/policies/{policy_id}/versions/{version}")
async def save_policy(policy_id: str, version: str, body: dict[str, Any], current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("PUT", f"/api/v1/policies/{policy_id}/versions/{version}", current_admin=current_admin, json=body)


@app.post("/api/bff/policies/{policy_id}/versions/{version}/activate")
async def activate_policy(policy_id: str, version: str, body: dict[str, Any], current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("POST", f"/api/v1/policies/{policy_id}/versions/{version}/activate", current_admin=current_admin, json=body)


@app.delete("/api/bff/policies/{policy_id}/versions/{version}")
async def delete_policy_version(policy_id: str, version: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> dict[str, str]:
    await _control_api_admin("DELETE", f"/api/v1/policies/{policy_id}/versions/{version}", current_admin=current_admin)
    return {"status": "deleted"}


@app.get("/api/bff/telemetry/tool-calls/summary")
async def tool_call_summary(window: str = "24h", current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    """Get telemetry summary for tool calls within a specified time window.
    
    Args:
        window: Time window ("24h", "7d", "30d", "all"). Defaults to "24h".
    """
    return await _control_api("GET", f"/api/v1/telemetry/tool-calls/summary?window={window}", actor=str(current_admin["id"]))


@app.get("/api/bff/jobs")
async def list_jobs(device_id: str | None = None, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    """Return diagnostic jobs, optionally scoped to a device ID."""
    path = "/api/v1/admin/jobs"
    if device_id:
        path = f"/api/v1/admin/jobs?device_id={device_id}"
    result = await _control_api_admin("GET", path, current_admin=current_admin)
    # Unwrap the jobs list for the frontend
    if isinstance(result, dict) and "jobs" in result:
        return result["jobs"]
    return result or []


@app.get("/api/bff/jobs/{job_id}")
async def get_job(job_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("GET", f"/api/v1/admin/jobs/{job_id}", current_admin=current_admin)


@app.get("/api/bff/jobs/{job_id}/artifacts")
async def get_job_artifacts(job_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("GET", f"/api/v1/admin/jobs/{job_id}/artifacts", current_admin=current_admin)


@app.get("/api/bff/jobs/{job_id}/artifacts/{artifact_id}/download")
async def download_job_artifact(
    job_id: str,
    artifact_id: str,
    current_admin: dict[str, Any] = Depends(get_current_admin),
) -> Response:
    """Stream an artifact binary to the admin browser as a file download."""
    path = f"/api/v1/admin/jobs/{job_id}/artifacts/{artifact_id}/download"
    async with httpx.AsyncClient(base_url=control_api_base_url, timeout=120.0) as client:
        upstream = await client.request("GET", path, headers=_signed_admin_headers(current_admin))
        if upstream.status_code >= 400:
            detail = upstream.text
            try:
                detail = upstream.json().get("detail", detail)
            except Exception:
                pass
            raise HTTPException(status_code=upstream.status_code, detail=detail)
        headers = {}
        disposition = upstream.headers.get("content-disposition")
        if disposition:
            headers["Content-Disposition"] = disposition
        media_type = upstream.headers.get("content-type", "application/octet-stream")
        return Response(content=upstream.content, media_type=media_type, headers=headers)


@app.post("/api/bff/jobs/{job_id}/requeue", status_code=200)
async def requeue_job(job_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    """Force a stuck Leased job back to Queued."""
    await _control_api_admin("POST", f"/api/v1/admin/jobs/{job_id}/requeue", current_admin=current_admin)
    return {"ok": True}


@app.get("/api/bff/approvals")
async def list_approvals(status_filter: str = "pending", current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    """Return approval records for the admin console."""
    return await _control_api_admin("GET", f"/api/v1/admin/approvals?status_filter={status_filter}", current_admin=current_admin)


@app.get("/api/bff/approvals/{approval_id}")
async def get_approval(approval_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("GET", f"/api/v1/admin/approvals/{approval_id}", current_admin=current_admin)


@app.post("/api/bff/approvals/{approval_id}/decision", status_code=200)
async def decide_approval(approval_id: str, body: dict[str, Any], current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    payload = {
        "approvalId": approval_id,
        "decision": body.get("decision"),
        "decidedBy": str(current_admin["id"]),
        "decidedAtUtc": body.get("decidedAtUtc"),
        "comment": body.get("comment"),
    }
    return await _control_api_admin("POST", f"/api/v1/approvals/{approval_id}/decision", current_admin=current_admin, json=payload)


@app.get("/api/bff/devices")
async def list_devices(current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("GET", "/api/v1/devices", current_admin=current_admin)


@app.get("/api/bff/devices/{device_id}/config")
async def get_device_config(device_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    return await _control_api_admin("GET", f"/api/v1/admin/devices/{device_id}/config", current_admin=current_admin)


@app.put("/api/bff/devices/{device_id}/config", status_code=200)
async def set_device_config(device_id: str, body: dict[str, Any], current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    await _control_api_admin("PUT", f"/api/v1/admin/devices/{device_id}/config", current_admin=current_admin, json=body)
    return {"ok": True}


@app.delete("/api/bff/devices/{device_id}", status_code=200)
async def delete_device(device_id: str, current_admin: dict[str, Any] = Depends(get_current_admin)) -> Any:
    await _control_api_admin("DELETE", f"/api/v1/admin/devices/{device_id}", current_admin=current_admin)
    return {"ok": True}

if static_root.exists():
    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")


@app.get("/{path:path}", response_model=None)
def spa_fallback(path: str) -> FileResponse | dict[str, str]:
    index = static_root / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Admin frontend assets are not built yet."}
