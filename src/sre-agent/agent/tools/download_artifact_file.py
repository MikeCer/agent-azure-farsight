#!/usr/bin/env python3
"""Safe Azure SRE Agent PythonFunctionTool wrapper for downloading artifacts locally."""
from __future__ import annotations

import base64
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_COMMAND_TOKENS = (";", "|", "`", "$(", "\n", "\r", "&&", "||")
_MAX_TIMEOUT_SECONDS = 120
_DEFAULT_TIMEOUT_SECONDS = 60
_DEPLOYED_SRE_TOOL_ENDPOINT_URL = "__SRE_AGENT_TOOL_ENDPOINT_URL__"
_DEPLOYED_SRE_TOOL_AUTH_MODE = "__SRE_AGENT_TOOL_AUTH_MODE__"
_DEPLOYED_SRE_TOOL_ENDPOINT_SCOPE = "__SRE_AGENT_TOOL_ENDPOINT_SCOPE__"


def _deployment_default(value: str) -> str | None:
    if not value or value.startswith("__SRE_AGENT_TOOL_"):
        return None
    return value


def _error(action: str, code: str, message: str, details: Any | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"status": "error", "action": action, "error": error}


def _success(action: str, response: Any, http_status: int | None = None) -> dict:
    result: dict[str, Any] = {"status": "success", "action": action, "response": response}
    if http_status is not None:
        result["http_status"] = http_status
    return result


def _has_command_tokens(value: str) -> bool:
    return any(token in value for token in _COMMAND_TOKENS)


def _validate_text(action: str, field: str, value: str | None, *, required: bool = False, max_len: int = 512) -> dict | None:
    if value is None or value == "":
        if required:
            return _error(action, "invalid_request", f"Missing required field: {field}")
        return None
    if not isinstance(value, str):
        return _error(action, "invalid_request", f"{field} must be a string.")
    if len(value) > max_len:
        return _error(action, "invalid_request", f"{field} exceeds maximum length {max_len}.")
    if _has_command_tokens(value):
        return _error(action, "invalid_request", f"{field} contains unsupported command-like tokens.")
    return None


def _sanitize_timeout(timeout_seconds: int | None) -> int:
    try:
        timeout = int(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, _MAX_TIMEOUT_SECONDS))


def _resolve_api_base_url(action: str, api_base_url: str | None) -> str | dict:
    base_url = (
        api_base_url
        or _deployment_default(_DEPLOYED_SRE_TOOL_ENDPOINT_URL)
        or os.environ.get("SRE_AGENT_TOOL_ENDPOINT_URL")
        or ""
    ).strip().rstrip("/")
    if not base_url:
        return _error(action, "configuration_error", "Tool endpoint URL is required via api_base_url or SRE_AGENT_TOOL_ENDPOINT_URL.")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return _error(action, "configuration_error", "FarSight API base URL must be an absolute HTTP(S) URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return _error(action, "configuration_error", "FarSight API base URL must use HTTPS except for localhost development.")
    return base_url


def _credential_scope(api_base_url: str, api_scope: str | None) -> str:
    configured = api_scope or _deployment_default(_DEPLOYED_SRE_TOOL_ENDPOINT_SCOPE) or os.environ.get("SRE_AGENT_TOOL_ENDPOINT_SCOPE")
    if configured:
        return configured
    return f"{api_base_url}/.default"


def _auth_headers(action: str, api_base_url: str, auth_mode: str | None, api_scope: str | None) -> dict[str, str] | dict:
    mode = (
        auth_mode
        or _deployment_default(_DEPLOYED_SRE_TOOL_AUTH_MODE)
        or os.environ.get("SRE_AGENT_TOOL_AUTH_MODE")
        or "default"
    ).strip().lower().replace("_", "-")
    if mode == "auto":
        mode = "default"
    if mode not in {"default", "managed-identity"}:
        return _error(action, "configuration_error", "Unsupported auth_mode. Use default or managed-identity.")
    scope = _credential_scope(api_base_url, api_scope)
    try:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
        client_id = (
            _deployment_default(os.environ.get("FARSIGHT_MANAGED_IDENTITY_CLIENT_ID", ""))
            or os.environ.get("AZURE_CLIENT_ID")
        )
        if mode == "managed-identity":
            cred = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
        else:
            cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        token = cred.get_token(scope).token
    except Exception as exc:
        return _error(action, "auth_error", f"Failed to obtain access token: {exc}")
    return {"Authorization": f"Bearer {token}"}


def _http_call(
    action: str,
    method: str,
    api_base_url: str,
    path: str,
    payload: dict[str, Any] | None,
    auth_mode: str | None,
    api_scope: str | None,
    timeout_seconds: int,
) -> dict:
    import json as _json
    headers = _auth_headers(action, api_base_url, auth_mode, api_scope)
    if isinstance(headers, dict) and headers.get("status") == "error":
        return headers
    headers["Accept"] = "application/json"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = _json.dumps(payload).encode("utf-8")
    url = api_base_url.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            status_code = resp.status
            response_body = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err_body = _json.loads(exc.read().decode("utf-8"))
        except Exception:
            err_body = {"text": str(exc)}
        return _error(action, "api_error", f"FarSight API returned HTTP {exc.code}.", {
            "http_status": exc.code, "response": err_body, "path": path,
        })
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        return _error(action, "network_error", f"FarSight API request failed: {exc}", {"path": path})

    if isinstance(response_body, dict) and "data" in response_body:
        response_body = response_body["data"]

    return _success(action, response_body, status_code)


TOOL_ACTION = "download_artifact_file"


def main(
    job_id: str,
    artifact_id: str,
    output_path: str | None = None,
    output_dir: str | None = None,
    api_base_url: str | None = None,
    auth_mode: str | None = None,
    api_scope: str | None = None,
    timeout_seconds: int = 60,
) -> dict:
    """Download a FarSight artifact into the local SRE Agent workspace.

    Use this tool for ZIP artifacts before passing the resulting local file path
    to extract_zip_artifact_entry. If output_path is omitted, the artifact is
    written to output_dir/fileName, or to the current working directory.
    """
    for field, value in {"job_id": job_id, "artifact_id": artifact_id}.items():
        err = _validate_text(TOOL_ACTION, field, value, required=True, max_len=128)
        if err:
            return err
    if output_path is not None:
        err = _validate_text(TOOL_ACTION, "output_path", output_path, required=False, max_len=1024)
        if err:
            return err
    if output_dir is not None:
        err = _validate_text(TOOL_ACTION, "output_dir", output_dir, required=False, max_len=1024)
        if err:
            return err

    api_url = _resolve_api_base_url(TOOL_ACTION, api_base_url)
    if isinstance(api_url, dict):
        return api_url
    timeout = _sanitize_timeout(timeout_seconds)

    response = _http_call(
        TOOL_ACTION,
        "POST",
        api_url,
        "/tools/download_artifact_file",
        {"jobId": job_id, "artifactId": artifact_id},
        auth_mode,
        api_scope,
        timeout,
    )
    if response.get("status") != "success":
        return response

    payload = response.get("response")
    if not isinstance(payload, dict):
        return _error(TOOL_ACTION, "invalid_response", "Unexpected response shape from FarSight API.")

    content_b64 = payload.get("contentBase64")
    if not isinstance(content_b64, str) or not content_b64:
        return _error(TOOL_ACTION, "invalid_response", "Download response did not include contentBase64.")

    try:
        raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
    except Exception as exc:
        return _error(TOOL_ACTION, "invalid_response", f"Invalid base64 content: {exc}")

    file_name = str(payload.get("fileName") or f"{artifact_id}.bin")
    if output_path:
        target = Path(output_path).expanduser()
    else:
        base_dir = Path(output_dir).expanduser() if output_dir else Path.cwd()
        target = base_dir / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)

    return _success(
        TOOL_ACTION,
        {
            "jobId": job_id,
            "artifactId": artifact_id,
            "downloadedPath": str(target),
            "fileName": file_name,
            "blobName": payload.get("blobName"),
            "contentType": payload.get("contentType"),
            "sizeBytes": payload.get("sizeBytes"),
        },
    )
