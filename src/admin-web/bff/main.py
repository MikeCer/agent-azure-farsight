from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI(title="Agent-Azure-FarSight Admin BFF", version="0.1.0")
static_root = Path(__file__).resolve().parent / "static"
control_api_base_url = os.environ.get("FARSIGHT_CONTROL_API_BASE_URL", "http://localhost:8000").rstrip("/")


@app.get("/api/bff/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "farsight-admin-bff"}


@app.get("/api/bff/me")
def current_user_placeholder() -> dict[str, object]:
    # TODO: Use Entra ID auth claims and group/role authorization from Container Apps auth or MSAL.
    return {"authenticated": False, "roles": []}


@app.get("/api/bff/config")
def admin_shell_config() -> dict[str, object]:
    # TODO: Load public UI configuration from App Configuration through managed identity.
    return {"apiBasePath": "/api/v1", "environment": "dev"}


async def _control_api(method: str, path: str, json: dict[str, Any] | None = None) -> Any:
    # TODO: Add Entra-authenticated user claims and managed identity token exchange for the control API.
    async with httpx.AsyncClient(base_url=control_api_base_url, timeout=15.0) as client:
        response = await client.request(method, path, json=json, headers={"X-FarSight-Admin-Actor": "admin-ui"})
        response.raise_for_status()
        return response.json() if response.content else None


@app.get("/api/bff/policies")
async def list_policies() -> Any:
    return await _control_api("GET", "/api/v1/policies")


@app.get("/api/bff/policies/{policy_id}")
async def get_active_policy(policy_id: str) -> Any:
    return await _control_api("GET", f"/api/v1/policies/{policy_id}")


@app.get("/api/bff/policies/{policy_id}/versions/{version}")
async def get_policy_version(policy_id: str, version: str) -> Any:
    return await _control_api("GET", f"/api/v1/policies/{policy_id}/versions/{version}")


@app.post("/api/bff/policies/{policy_id}/validate")
async def validate_policy(policy_id: str, body: dict[str, Any]) -> Any:
    return await _control_api("POST", f"/api/v1/policies/{policy_id}/validate", body)


@app.put("/api/bff/policies/{policy_id}/versions/{version}")
async def save_policy(policy_id: str, version: str, body: dict[str, Any]) -> Any:
    return await _control_api("PUT", f"/api/v1/policies/{policy_id}/versions/{version}", body)


@app.post("/api/bff/policies/{policy_id}/versions/{version}/activate")
async def activate_policy(policy_id: str, version: str, body: dict[str, Any]) -> Any:
    return await _control_api("POST", f"/api/v1/policies/{policy_id}/versions/{version}/activate", body)


if static_root.exists():
    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse | dict[str, str]:
    index = static_root / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Admin frontend assets are not built yet."}
