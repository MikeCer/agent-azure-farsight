from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Agent-Azure-FarSight Admin BFF", version="0.1.0")
static_root = Path(__file__).resolve().parent / "static"


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


if static_root.exists():
    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse | dict[str, str]:
    index = static_root / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Admin frontend assets are not built yet."}
