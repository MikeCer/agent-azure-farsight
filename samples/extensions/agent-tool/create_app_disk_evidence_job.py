#!/usr/bin/env python3
"""Sample Azure SRE Agent tool for creating a safe FarSight diagnostic job."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

MODULE_ID = "Get-AppDiskEvidence"
ALLOWED_PROFILES = {"contoso-app", "winget-cache"}


def fail(message: str, code: str = "invalid_request") -> None:
    print(json.dumps({"status": "failed", "code": code, "message": message}))
    raise SystemExit(1)


def evaluate_policy(request: dict[str, Any]) -> dict[str, str]:
    profile = request.get("profile")
    max_file_samples = int(request.get("maxFileSamples", 5))
    target = request.get("targetDeviceId", "")

    if profile not in ALLOWED_PROFILES:
        return {"outcome": "deny", "reason": "profile_not_allowlisted"}
    if any(token in str(profile) for token in ("\\", "/", ";", "|", "&", "$(")):
        return {"outcome": "deny", "reason": "path_or_command_token_detected"}
    if max_file_samples > 20:
        return {"outcome": "deny", "reason": "sample_limit_exceeded"}
    if target.startswith("group:") or max_file_samples > 10:
        if not request.get("approvalId"):
            return {"outcome": "require_approval", "reason": "broad_or_large_collection"}
    return {"outcome": "allow", "reason": "low_risk_read_only_module"}


def build_job_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "moduleId": MODULE_ID,
        "target": {"type": "device", "deviceId": request["targetDeviceId"]},
        "parameters": {
            "profile": request["profile"],
            "includeFileSamples": bool(request.get("includeFileSamples", False)),
            "maxFileSamples": int(request.get("maxFileSamples", 5)),
        },
        "justification": request["justification"],
        "requestedBy": os.environ.get("AGENT_ACTOR", "azure-sre-agent-sample"),
        "approvalId": request.get("approvalId"),
    }


def post_job(api_base_url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base_url.rstrip('/')}/api/v1/jobs",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"{MODULE_ID}:{body['target']['deviceId']}:{int(time.time() // 300)}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        fail(f"FarSight API rejected the job request with HTTP {exc.code}.", "api_error")


def main() -> None:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        fail(f"Input must be JSON: {exc}", "invalid_json")

    for field in ("targetDeviceId", "profile", "justification"):
        if not request.get(field):
            fail(f"Missing required field: {field}")

    policy = evaluate_policy(request)
    if policy["outcome"] == "deny":
        fail(f"AGT policy denied request: {policy['reason']}", "policy_denied")
    if policy["outcome"] == "require_approval":
        print(json.dumps({"status": "approval_required", "policy": policy}, indent=2))
        return

    api_base_url = os.environ.get("FARSIGHT_API_BASE_URL")
    token = os.environ.get("FARSIGHT_ACCESS_TOKEN")
    if not api_base_url or not token:
        print(json.dumps({
            "status": "dry_run",
            "policy": policy,
            "jobRequest": build_job_request(request),
            "note": "Set FARSIGHT_API_BASE_URL and use managed identity/token acquisition in production."
        }, indent=2))
        return

    result = post_job(api_base_url, token, build_job_request(request))
    print(json.dumps({"status": "submitted", "policy": policy, "job": result}, indent=2))


if __name__ == "__main__":
    main()
