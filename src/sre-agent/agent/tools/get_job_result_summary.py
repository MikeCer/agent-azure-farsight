#!/usr/bin/env python3
"""Safe Azure SRE Agent PythonFunctionTool wrapper for FarSight REST calls."""
from __future__ import annotations

import json
import os
import re
import socket
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

ALLOWED_TASK_TYPES = {
    "Get-AppLogBundle",
    "Get-AppEventSlice",
    "Get-AppHealthSnapshot",
    "Test-AppConnectivity",
    "Get-ConfigEvidence",
    "Get-AppDiskEvidence",
    "Get-ServiceStatusSnapshot",
}
ALLOWED_RISK_LEVELS = {"read-only", "sensitive-diagnostic"}
ALLOWED_DISK_PROFILES = {"contoso-app", "winget-cache"}
ALLOWED_APPROVAL_ACTIONS = ALLOWED_TASK_TYPES | {
    "broad-diagnostic-collection",
    "large-artifact-collection",
    "follow-up-module-execution",
    "sensitive-diagnostic",
}
_COMMAND_TOKENS = (";", "|", "`", "$(", "\n", "\r", "&&", "||")
_MAX_TIMEOUT_SECONDS = 120
_DEFAULT_TIMEOUT_SECONDS = 30


def _error(action: str, code: str, message: str, details: Any | None = None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"status": "error", "action": action, "error": error}


def _success(action: str, response: Any, http_status: int | None = None, request: dict[str, Any] | None = None) -> dict:
    result = {"status": "success", "action": action, "response": response}
    if http_status is not None:
        result["http_status"] = http_status
    if request is not None:
        result["request"] = request
    return result


def _approval_required(action: str, reason: str, details: Any | None = None) -> dict:
    result = {"status": "approval_required", "action": action, "reason": reason}
    if details is not None:
        result["details"] = details
    return result


def _sanitize_timeout(timeout_seconds: int | None) -> int:
    try:
        timeout = int(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT_SECONDS
    return max(1, min(timeout, _MAX_TIMEOUT_SECONDS))


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


def _validate_iso8601(action: str, field: str, value: str | None, *, required: bool = True) -> dict | None:
    err = _validate_text(action, field, value, required=required, max_len=64)
    if err or not value:
        return err
    candidate = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return _error(action, "invalid_request", f"{field} must be an ISO 8601 timestamp.")
    return None


def _csv_list(action: str, field: str, value: str | None, *, max_items: int = 25, max_item_len: int = 256) -> list[str] | dict:
    if value is None or str(value).strip() == "":
        return []
    err = _validate_text(action, field, str(value), max_len=max_items * (max_item_len + 1))
    if err:
        return err
    items = [item.strip() for item in str(value).split(",") if item.strip()]
    if len(items) > max_items:
        return _error(action, "invalid_request", f"{field} has too many values; max is {max_items}.")
    for item in items:
        if len(item) > max_item_len or _has_command_tokens(item):
            return _error(action, "invalid_request", f"{field} contains an invalid value.")
    return items


def _int_list(action: str, field: str, value: str | None, *, min_value: int, max_value: int, max_items: int = 50) -> list[int] | dict:
    raw_items = _csv_list(action, field, value, max_items=max_items, max_item_len=10)
    if isinstance(raw_items, dict):
        return raw_items
    numbers: list[int] = []
    for item in raw_items:
        try:
            number = int(item)
        except ValueError:
            return _error(action, "invalid_request", f"{field} values must be integers.")
        if number < min_value or number > max_value:
            return _error(action, "invalid_request", f"{field} values must be between {min_value} and {max_value}.")
        numbers.append(number)
    return numbers


def _bounded_int(action: str, field: str, value: int | None, *, default: int, min_value: int, max_value: int) -> int | dict:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return _error(action, "invalid_request", f"{field} must be an integer.")
    if number < min_value or number > max_value:
        return _error(action, "invalid_request", f"{field} must be between {min_value} and {max_value}.")
    return number


def _require_one(action: str, names_to_values: dict[str, Any]) -> dict | None:
    if not any(value for value in names_to_values.values()):
        fields = ", ".join(names_to_values)
        return _error(action, "invalid_request", f"At least one of these fields is required: {fields}.")
    return None


def _validate_url_list(action: str, field: str, value: str | None) -> list[str] | dict:
    urls = _csv_list(action, field, value, max_items=20, max_item_len=512)
    if isinstance(urls, dict):
        return urls
    for url in urls:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return _error(action, "invalid_request", f"{field} contains an invalid HTTP(S) URL.")
    return urls


def _resolve_api_base_url(action: str, api_base_url: str | None) -> str | dict:
    base_url = (api_base_url or os.environ.get("FARSIGHT_API_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return _error(action, "configuration_error", "FarSight API base URL is required via api_base_url or FARSIGHT_API_BASE_URL.")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return _error(action, "configuration_error", "FarSight API base URL must be an absolute HTTP(S) URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return _error(action, "configuration_error", "FarSight API base URL must use HTTPS except for localhost development.")
    return base_url


def _credential_scope(api_base_url: str, api_scope: str | None) -> str:
    configured = api_scope or os.environ.get("FARSIGHT_API_SCOPE")
    if configured:
        return configured
    return f"{api_base_url}/.default"


def _auth_headers(action: str, api_base_url: str, auth_mode: str | None, api_scope: str | None) -> dict[str, str] | dict:
    mode = (auth_mode or os.environ.get("FARSIGHT_AUTH_MODE") or "default").strip().lower().replace("_", "-")
    if mode == "auto":
        mode = "access-token" if os.environ.get("FARSIGHT_ACCESS_TOKEN") else "default"
    if mode in {"access-token", "bearer-token-env"}:
        token = os.environ.get("FARSIGHT_ACCESS_TOKEN")
        if not token:
            return _error(action, "configuration_error", "FARSIGHT_ACCESS_TOKEN is required when auth_mode is access-token.")
        return {"Authorization": f"Bearer {token}"}
    if mode not in {"default", "managed-identity"}:
        return _error(action, "configuration_error", "Unsupported auth_mode. Use default, managed-identity, access-token, or auto.")
    try:
        if mode == "managed-identity":
            from azure.identity import ManagedIdentityCredential
            client_id = os.environ.get("FARSIGHT_MANAGED_IDENTITY_CLIENT_ID") or os.environ.get("AZURE_CLIENT_ID")
            credential = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
        else:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        token = credential.get_token(_credential_scope(api_base_url, api_scope)).token
        close = getattr(credential, "close", None)
        if callable(close):
            close()
        return {"Authorization": f"Bearer {token}"}
    except ImportError as exc:
        return _error(action, "dependency_error", "Missing dependency azure-identity for managed identity authentication.", str(exc))
    except Exception as exc:
        return _error(action, "authentication_error", "Could not acquire a FarSight API access token.", str(exc))


def _read_response_body(response: Any) -> Any:
    raw = response.read()
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def _http_call(
    action: str,
    method: str,
    api_base_url: str,
    path: str,
    payload: dict[str, Any] | None,
    auth_mode: str | None,
    api_scope: str | None,
    timeout_seconds: int | None,
    idempotency_key: str | None = None,
) -> dict:
    auth = _auth_headers(action, api_base_url, auth_mode, api_scope)
    if isinstance(auth, dict) and auth.get("status") == "error":
        return auth
    headers = {"Accept": "application/json", **auth}
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    url = f"{api_base_url}{path}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    timeout = _sanitize_timeout(timeout_seconds)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = _read_response_body(response)
            status_code = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        body = _read_response_body(exc)
        return _error(
            action,
            "api_error",
            f"FarSight API returned HTTP {exc.code}.",
            {"http_status": exc.code, "response": body, "path": path},
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        return _error(action, "network_error", "FarSight API request failed or timed out.", {"path": path, "detail": str(exc)})
    except Exception as exc:
        return _error(action, "unexpected_error", "Unexpected error calling FarSight API.", str(exc))
    return _success(action, response_body, status_code, {"method": method, "path": path})


def _build_requested_by(kind: str | None, identity_object_id: str | None, tool_name: str | None) -> dict[str, Any]:
    return {
        "kind": kind or "agent_tool",
        "identityObjectId": identity_object_id,
        "toolName": tool_name or TOOL_ACTION,
    }


def _base_job_validation(
    action: str,
    device_id: str,
    task_type: str,
    correlation_id: str,
    expires_at_utc: str,
    risk_level: str,
) -> dict | None:
    for field, value in {
        "device_id": device_id,
        "task_type": task_type,
        "correlation_id": correlation_id,
    }.items():
        err = _validate_text(action, field, value, required=True, max_len=128)
        if err:
            return err
    err = _validate_iso8601(action, "expires_at_utc", expires_at_utc, required=True)
    if err:
        return err
    if task_type not in ALLOWED_TASK_TYPES:
        return _error(action, "invalid_request", f"task_type must be one of: {', '.join(sorted(ALLOWED_TASK_TYPES))}.")
    if risk_level not in ALLOWED_RISK_LEVELS:
        return _error(action, "invalid_request", "risk_level must be read-only or sensitive-diagnostic.")
    return None


def _with_common_job_parameters(parameters: dict[str, Any], justification: str | None, approval_id: str | None) -> dict[str, Any]:
    if justification:
        parameters["justification"] = justification
    if approval_id:
        parameters["approvalId"] = approval_id
    return parameters


def _build_module_parameters(
    action: str,
    task_type: str,
    approval_id: str | None,
    justification: str | None,
    app_id: str | None,
    path_profile: str | None,
    start_time_utc: str | None,
    end_time_utc: str | None,
    tail_lines: int | None,
    max_bytes: int | None,
    include_patterns_csv: str | None,
    exclude_patterns_csv: str | None,
    log_name: str | None,
    provider_names_csv: str | None,
    event_ids_csv: str | None,
    levels_csv: str | None,
    max_events: int | None,
    service_names_csv: str | None,
    process_names_csv: str | None,
    config_profiles_csv: str | None,
    targets_csv: str | None,
    ports_csv: str | None,
    urls_csv: str | None,
    dns_names_csv: str | None,
    expected_tls_thumbprints_csv: str | None,
    registry_profiles_csv: str | None,
    file_profiles_csv: str | None,
    redaction_profile: str | None,
    disk_profile: str | None,
    include_file_samples: bool,
    max_file_samples: int | None,
) -> dict[str, Any] | dict:
    err = _validate_text(action, "justification", justification, required=not bool(approval_id), max_len=1024)
    if err:
        return err

    if task_type == "Get-AppLogBundle":
        for field, value in {"app_id": app_id, "path_profile": path_profile}.items():
            err = _validate_text(action, field, value, required=True, max_len=128)
            if err:
                return err
        for field, value in {"start_time_utc": start_time_utc, "end_time_utc": end_time_utc}.items():
            err = _validate_iso8601(action, field, value, required=True)
            if err:
                return err
        include_patterns = _csv_list(action, "include_patterns_csv", include_patterns_csv, max_items=20)
        exclude_patterns = _csv_list(action, "exclude_patterns_csv", exclude_patterns_csv, max_items=20)
        tail = _bounded_int(action, "tail_lines", tail_lines, default=1000, min_value=1, max_value=10000)
        bytes_limit = _bounded_int(action, "max_bytes", max_bytes, default=10485760, min_value=1024, max_value=52428800)
        for value in (include_patterns, exclude_patterns, tail, bytes_limit):
            if isinstance(value, dict):
                return value
        return _with_common_job_parameters({
            "appId": app_id,
            "pathProfile": path_profile,
            "startTime": start_time_utc,
            "endTime": end_time_utc,
            "tailLines": tail,
            "maxBytes": bytes_limit,
            "includePatterns": include_patterns,
            "excludePatterns": exclude_patterns,
        }, justification, approval_id)

    if task_type == "Get-AppEventSlice":
        err = _validate_text(action, "log_name", log_name, required=True, max_len=128)
        if err:
            return err
        for field, value in {"start_time_utc": start_time_utc, "end_time_utc": end_time_utc}.items():
            err = _validate_iso8601(action, field, value, required=True)
            if err:
                return err
        providers = _csv_list(action, "provider_names_csv", provider_names_csv, max_items=25)
        event_ids = _int_list(action, "event_ids_csv", event_ids_csv, min_value=0, max_value=65535, max_items=50)
        levels = _csv_list(action, "levels_csv", levels_csv, max_items=5, max_item_len=32)
        events_limit = _bounded_int(action, "max_events", max_events, default=500, min_value=1, max_value=5000)
        for value in (providers, event_ids, levels, events_limit):
            if isinstance(value, dict):
                return value
        return _with_common_job_parameters({
            "logName": log_name,
            "providerNames": providers,
            "eventIds": event_ids,
            "levels": levels,
            "startTime": start_time_utc,
            "endTime": end_time_utc,
            "maxEvents": events_limit,
        }, justification, approval_id)

    if task_type == "Get-AppHealthSnapshot":
        err = _validate_text(action, "app_id", app_id, required=True, max_len=128)
        if err:
            return err
        services = _csv_list(action, "service_names_csv", service_names_csv, max_items=30)
        processes = _csv_list(action, "process_names_csv", process_names_csv, max_items=30)
        config_profiles = _csv_list(action, "config_profiles_csv", config_profiles_csv, max_items=20)
        for value in (services, processes, config_profiles):
            if isinstance(value, dict):
                return value
        err = _require_one(action, {"service_names_csv": services, "process_names_csv": processes, "config_profiles_csv": config_profiles})
        if err:
            return err
        return _with_common_job_parameters({
            "appId": app_id,
            "serviceNames": services,
            "processNames": processes,
            "configProfiles": config_profiles,
        }, justification, approval_id)

    if task_type == "Test-AppConnectivity":
        targets = _csv_list(action, "targets_csv", targets_csv, max_items=20)
        ports = _int_list(action, "ports_csv", ports_csv, min_value=1, max_value=65535, max_items=20)
        urls = _validate_url_list(action, "urls_csv", urls_csv)
        dns_names = _csv_list(action, "dns_names_csv", dns_names_csv, max_items=20)
        tls_thumbprints = _csv_list(action, "expected_tls_thumbprints_csv", expected_tls_thumbprints_csv, max_items=20, max_item_len=128)
        for value in (targets, ports, urls, dns_names, tls_thumbprints):
            if isinstance(value, dict):
                return value
        err = _require_one(action, {"targets_csv": targets, "urls_csv": urls, "dns_names_csv": dns_names})
        if err:
            return err
        return _with_common_job_parameters({
            "targets": targets,
            "ports": ports,
            "urls": urls,
            "dnsNames": dns_names,
            "expectedTlsThumbprints": tls_thumbprints,
        }, justification, approval_id)

    if task_type == "Get-ConfigEvidence":
        registry_profiles = _csv_list(action, "registry_profiles_csv", registry_profiles_csv, max_items=20)
        file_profiles = _csv_list(action, "file_profiles_csv", file_profiles_csv, max_items=20)
        for value in (registry_profiles, file_profiles):
            if isinstance(value, dict):
                return value
        err = _require_one(action, {"registry_profiles_csv": registry_profiles, "file_profiles_csv": file_profiles})
        if err:
            return err
        err = _validate_text(action, "redaction_profile", redaction_profile or "default", required=True, max_len=128)
        if err:
            return err
        return _with_common_job_parameters({
            "registryProfiles": registry_profiles,
            "fileProfiles": file_profiles,
            "redactionProfile": redaction_profile or "default",
        }, justification, approval_id)

    if task_type == "Get-AppDiskEvidence":
        err = _validate_text(action, "disk_profile", disk_profile, required=True, max_len=128)
        if err:
            return err
        if disk_profile not in ALLOWED_DISK_PROFILES:
            return _error(action, "invalid_request", f"disk_profile must be one of: {', '.join(sorted(ALLOWED_DISK_PROFILES))}.")
        sample_limit = _bounded_int(action, "max_file_samples", max_file_samples, default=5, min_value=0, max_value=20)
        if isinstance(sample_limit, dict):
            return sample_limit
        return _with_common_job_parameters({
            "profile": disk_profile,
            "includeFileSamples": bool(include_file_samples),
            "maxFileSamples": sample_limit,
        }, justification, approval_id)

    return _error(action, "invalid_request", "Unsupported task_type.")


def _build_job_payload(
    action: str,
    device_id: str,
    incident_id: str | None,
    correlation_id: str,
    task_type: str,
    risk_level: str,
    expires_at_utc: str,
    approval_id: str | None,
    justification: str | None,
    requested_by_kind: str | None,
    requested_by_identity_object_id: str | None,
    requested_by_tool_name: str | None,
    app_id: str | None,
    path_profile: str | None,
    start_time_utc: str | None,
    end_time_utc: str | None,
    tail_lines: int | None,
    max_bytes: int | None,
    include_patterns_csv: str | None,
    exclude_patterns_csv: str | None,
    log_name: str | None,
    provider_names_csv: str | None,
    event_ids_csv: str | None,
    levels_csv: str | None,
    max_events: int | None,
    service_names_csv: str | None,
    process_names_csv: str | None,
    config_profiles_csv: str | None,
    targets_csv: str | None,
    ports_csv: str | None,
    urls_csv: str | None,
    dns_names_csv: str | None,
    expected_tls_thumbprints_csv: str | None,
    registry_profiles_csv: str | None,
    file_profiles_csv: str | None,
    redaction_profile: str | None,
    disk_profile: str | None,
    include_file_samples: bool,
    max_file_samples: int | None,
) -> dict[str, Any] | dict:
    err = _base_job_validation(action, device_id, task_type, correlation_id, expires_at_utc, risk_level)
    if err:
        return err
    for field, value in {
        "incident_id": incident_id,
        "approval_id": approval_id,
        "requested_by_identity_object_id": requested_by_identity_object_id,
        "requested_by_tool_name": requested_by_tool_name,
    }.items():
        err = _validate_text(action, field, value, required=False, max_len=128)
        if err:
            return err
    if risk_level == "sensitive-diagnostic" and not approval_id:
        return _approval_required(action, "sensitive-diagnostic risk requires approval_id before job creation.")
    parameters = _build_module_parameters(
        action,
        task_type,
        approval_id,
        justification,
        app_id,
        path_profile,
        start_time_utc,
        end_time_utc,
        tail_lines,
        max_bytes,
        include_patterns_csv,
        exclude_patterns_csv,
        log_name,
        provider_names_csv,
        event_ids_csv,
        levels_csv,
        max_events,
        service_names_csv,
        process_names_csv,
        config_profiles_csv,
        targets_csv,
        ports_csv,
        urls_csv,
        dns_names_csv,
        expected_tls_thumbprints_csv,
        registry_profiles_csv,
        file_profiles_csv,
        redaction_profile,
        disk_profile,
        include_file_samples,
        max_file_samples,
    )
    if isinstance(parameters, dict) and parameters.get("status") in {"error", "approval_required"}:
        return parameters
    return {
        "deviceId": device_id,
        "incidentId": incident_id,
        "correlationId": correlation_id,
        "taskType": task_type,
        "parameters": parameters,
        "riskLevel": risk_level,
        "expiresAtUtc": expires_at_utc,
        "requestedBy": _build_requested_by(requested_by_kind, requested_by_identity_object_id, requested_by_tool_name),
    }


def _default_idempotency_key(action: str, device_id: str, task_type: str, correlation_id: str) -> str:
    source = f"{action}:{device_id}:{task_type}:{correlation_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source))


def _lookup_main(action: str, job_id: str, path_suffix: str, api_base_url: str | None, auth_mode: str | None, api_scope: str | None, timeout_seconds: int) -> dict:
    err = _validate_text(action, "job_id", job_id, required=True, max_len=128)
    if err:
        return err
    api_url = _resolve_api_base_url(action, api_base_url)
    if isinstance(api_url, dict):
        return api_url
    encoded_job = urllib.parse.quote(job_id, safe="")
    return _http_call(action, "GET", api_url, f"/api/v1/jobs/{encoded_job}{path_suffix}", None, auth_mode, api_scope, timeout_seconds)


TOOL_ACTION = "get_job_result_summary"


def main(
    job_id: str,
    api_base_url: str | None = None,
    auth_mode: str | None = None,
    api_scope: str | None = None,
    timeout_seconds: int = 30,
) -> dict:
    """Return the compact FarSight result summary for a completed job."""
    return _lookup_main(TOOL_ACTION, job_id, "/summary", api_base_url, auth_mode, api_scope, timeout_seconds)
