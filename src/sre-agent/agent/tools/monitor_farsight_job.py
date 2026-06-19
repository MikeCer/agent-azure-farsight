#!/usr/bin/env python3
"""Safe Azure SRE Agent PythonFunctionTool — FarSight async job monitor.

Polls a FarSight job until it reaches a terminal state (Succeeded, Failed,
Expired) and returns the final status plus result summary.  The tool handles
all waiting internally so the agent does not need to poll manually.
"""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_COMMAND_TOKENS = (";", "|", "`", "$(", "\n", "\r", "&&", "||")
_DEPLOYED_SRE_TOOL_ENDPOINT_URL = "__SRE_AGENT_TOOL_ENDPOINT_URL__"
_DEPLOYED_SRE_TOOL_AUTH_MODE = "__SRE_AGENT_TOOL_AUTH_MODE__"
_DEPLOYED_SRE_TOOL_ENDPOINT_SCOPE = "__SRE_AGENT_TOOL_ENDPOINT_SCOPE__"

# Terminal job statuses — polling stops when any of these is reached.
_TERMINAL_STATUSES = {"Succeeded", "Failed", "Expired", "Cancelled"}

# Non-terminal statuses the tool expects while waiting.
_ACTIVE_STATUSES = {"Queued", "Leased", "Running"}
_APPROVAL_WAIT_STATUSES = {"waiting_approval", "WaitingApproval"}

# Poll interval (seconds) per status — tuned to collector check-in schedule.
_POLL_INTERVALS: dict[str, int] = {
    "Queued":  30,   # waiting for collector checkin (every ~5 min, but check early)
    "Leased":  20,   # collector has the job, about to start
    "Running": 15,   # module executing on device
    "unknown": 30,   # any other non-terminal status
}

# Per-module upper-bound estimates (seconds) — used to derive max_wait_seconds
# when the caller does not override it.
_MODULE_MAX_SECONDS: dict[str, int] = {
    "Get-ServiceStatusSnapshot": 180,
    "Get-AppHealthSnapshot":     180,
    "Test-AppConnectivity":      120,
    "Get-ConfigEvidence":        240,
    "Get-AppEventSlice":         300,
    "Get-AppLogBundle":          360,
    "Get-AppDiskEvidence":       240,
}
_DEFAULT_MAX_SECONDS = 300


def _deployment_default(value: str) -> str | None:
    if not value or value.startswith("__SRE_AGENT_TOOL_"):
        return None
    return value


def _error(code: str, message: str, details: Any | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"status": "error", "action": "monitor_farsight_job", "error": error}


def _has_command_tokens(value: str) -> bool:
    return any(token in value for token in _COMMAND_TOKENS)


def _resolve_api_base_url(api_base_url: str | None) -> str | dict:
    base = (
        api_base_url
        or _deployment_default(_DEPLOYED_SRE_TOOL_ENDPOINT_URL)
        or os.environ.get("SRE_AGENT_TOOL_ENDPOINT_URL")
        or ""
    ).strip().rstrip("/")
    if not base:
        return _error("configuration_error", "Tool endpoint URL is required via api_base_url or SRE_AGENT_TOOL_ENDPOINT_URL.")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return _error("configuration_error", "FarSight API base URL must be an absolute HTTP(S) URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return _error("configuration_error", "FarSight API base URL must use HTTPS except for localhost.")
    return base


def _credential_scope(api_base_url: str, api_scope: str | None) -> str:
    configured = api_scope or _deployment_default(_DEPLOYED_SRE_TOOL_ENDPOINT_SCOPE) or os.environ.get("SRE_AGENT_TOOL_ENDPOINT_SCOPE")
    if configured:
        return configured
    return f"{api_base_url}/.default"


def _get_token(auth_mode: str, scope: str) -> str:
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
    client_id = (
        _deployment_default(os.environ.get("FARSIGHT_MANAGED_IDENTITY_CLIENT_ID", ""))
        or os.environ.get("AZURE_CLIENT_ID")
    )
    if auth_mode in {"managed-identity"}:
        cred = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
    else:
        cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return cred.get_token(scope).token


def _http_post(url: str, payload: dict, token: str, http_timeout: int) -> tuple[int, Any]:
    import json as _json
    body = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            return resp.status, _json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, _json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"text": str(exc)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"text": str(exc)}


def _poll_once(api_base_url: str, job_id: str, token: str, http_timeout: int) -> tuple[int, Any]:
    url = f"{api_base_url}/tools/get_job_status"
    return _http_post(url, {"jobId": job_id}, token, http_timeout)


def _fetch_summary(api_base_url: str, job_id: str, token: str, http_timeout: int) -> Any:
    url = f"{api_base_url}/tools/get_job_result_summary"
    _, body = _http_post(url, {"jobId": job_id}, token, http_timeout)
    return body


def main(
    job_id: str,
    task_type: str | None = None,
    api_base_url: str | None = None,
    auth_mode: str | None = None,
    api_scope: str | None = None,
    max_wait_seconds: int | None = None,
    initial_delay_seconds: int = 30,
) -> dict:
    """Poll a FarSight job to completion and return the terminal state + summary.

    The tool blocks until the job reaches Succeeded, Failed, or Expired, or
    until max_wait_seconds is exceeded.  After job creation, pass the jobId
    directly to this tool — the agent does not need to call get_job_status
    or get_job_result_summary separately.
    """
    # Validate job_id
    if not job_id or not isinstance(job_id, str) or len(job_id) > 128 or _has_command_tokens(job_id):
        return _error("invalid_request", "job_id is required and must be a safe string.")

    # Resolve config
    resolved_url = _resolve_api_base_url(api_base_url)
    if isinstance(resolved_url, dict):
        return resolved_url

    mode = (
        auth_mode
        or _deployment_default(_DEPLOYED_SRE_TOOL_AUTH_MODE)
        or os.environ.get("SRE_AGENT_TOOL_AUTH_MODE")
        or "default"
    ).strip().lower().replace("_", "-")

    scope = _credential_scope(resolved_url, api_scope)
    http_timeout = 20

    # Determine max wait based on module type
    effective_max = max_wait_seconds
    if effective_max is None:
        effective_max = _MODULE_MAX_SECONDS.get(task_type or "", _DEFAULT_MAX_SECONDS) if task_type else _DEFAULT_MAX_SECONDS
    effective_max = max(60, min(int(effective_max), 600))

    # Initial delay — give the collector time to pick up the job
    initial_delay = max(0, min(int(initial_delay_seconds), 120))

    start = time.monotonic()
    poll_count = 0
    last_status = "unknown"
    last_response: Any = {}
    token_cache: dict[str, Any] = {}

    def _get_cached_token() -> str:
        now = time.monotonic()
        if token_cache.get("expires_at", 0) > now + 30:
            return token_cache["token"]
        tok = _get_token(mode, scope)
        token_cache["token"] = tok
        token_cache["expires_at"] = now + 3300  # ~55 min
        return tok

    # Wait before first poll
    if initial_delay > 0:
        time.sleep(initial_delay)

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= effective_max:
            return {
                "status": "timeout",
                "action": "monitor_farsight_job",
                "job_id": job_id,
                "last_status": last_status,
                "poll_count": poll_count,
            "elapsed_seconds": round(elapsed),
                "message": (
                    f"Job {job_id} did not complete within {effective_max}s "
                    f"(last status: {last_status}). Use get_job_status to check later."
                ),
            }

        poll_count += 1
        try:
            token = _get_cached_token()
        except Exception as exc:
            return _error("auth_error", f"Failed to obtain access token: {exc}")

        http_status, body = _poll_once(resolved_url, job_id, token, http_timeout)

        if http_status == 0:
            # Network error — wait and retry
            time.sleep(15)
            continue

        if http_status == 404 and poll_count <= 3:
            # Job not yet indexed in Cosmos — wait and retry
            time.sleep(15)
            continue

        if http_status not in (200, 201):
            return _error(
                "api_error",
                f"FarSight API returned HTTP {http_status} while polling job {job_id}.",
                {"http_status": http_status, "response": body},
            )

        # Unwrap gateway ToolResponse envelope if present
        response_data = body.get("data", body) if isinstance(body, dict) and "data" in body else body
        job_status = str(response_data.get("status") or response_data.get("jobStatus") or "unknown")
        last_status = job_status
        last_response = response_data

        if job_status in _APPROVAL_WAIT_STATUSES:
            return {
                "status": "approval_required",
                "action": "monitor_farsight_job",
                "job_id": job_id,
                "job_status": job_status,
                "approval_id": response_data.get("approvalId"),
                "approval_status": response_data.get("approvalStatus"),
                "poll_count": poll_count,
                "elapsed_seconds": round(time.monotonic() - start),
                "status_response": response_data,
                "message": (
                    f"FarSight job {job_id} is waiting for administrator approval. "
                    "Do not keep polling synchronously; schedule a follow-up check and notify via Outlook when it completes, is denied, or expires."
                ),
            }

        if job_status in _TERMINAL_STATUSES:
            result: dict[str, Any] = {
                "status": "complete",
                "action": "monitor_farsight_job",
                "job_id": job_id,
                "job_status": job_status,
                "poll_count": poll_count,
                "elapsed_seconds": round(time.monotonic() - start),
                "status_response": response_data,
            }
            if job_status == "Succeeded":
                try:
                    token = _get_cached_token()
                    summary_body = _fetch_summary(resolved_url, job_id, token, http_timeout)
                    summary_data = summary_body.get("data", summary_body) if isinstance(summary_body, dict) and "data" in summary_body else summary_body
                    result["summary"] = summary_data
                    result["message"] = (
                        f"✅ FarSight job {job_id} completed successfully after "
                        f"{result['elapsed_seconds']}s ({poll_count} polls). "
                        "Result summary is in the 'summary' field."
                    )
                except Exception as exc:
                    result["summary_error"] = str(exc)
                    result["message"] = f"✅ Job succeeded but result summary fetch failed: {exc}"
            else:
                result["message"] = (
                    f"⚠️ FarSight job {job_id} ended with status '{job_status}' "
                    f"after {result['elapsed_seconds']}s ({poll_count} polls)."
                )
            return result

        # Not terminal — wait then poll again
        interval = _POLL_INTERVALS.get(job_status, _POLL_INTERVALS["unknown"])
        remaining = effective_max - (time.monotonic() - start)
        time.sleep(min(interval, max(5, remaining - 5)))
