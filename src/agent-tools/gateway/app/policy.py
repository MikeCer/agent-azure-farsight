from __future__ import annotations

import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential

from .clients import normalize_api_scope
import yaml

from .models import PolicyDecision, PolicyOutcome, ToolRisk

POLICY_VERSION = "2026-06-12.1"
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "farsight-tool-policy.yaml"
DEFAULT_POLICY_ID = "farsight-tool-policy"
SAFE_DIAGNOSTIC_MODULES = {
    "Get-AppLogBundle",
    "Get-AppEventSlice",
    "Get-AppHealthSnapshot",
    "Test-AppConnectivity",
    "Get-ConfigEvidence",
    "Get-ServiceStatusSnapshot",
}
DANGEROUS_INPUT_PATTERNS = (
    r"(?i)\bpowershell(\.exe)?\b",
    r"(?i)\bpwsh(\.exe)?\b",
    r"(?i)\bcmd(\.exe)?\b",
    r"(?i)\bInvoke-Expression\b",
    r"(?i)\biex\b",
    r"(?i)\bEncodedCommand\b",
    r"`",
    r"\$\(",
    r";",
    r"\|",
    r"&&",
)


class PolicyConfigurationError(RuntimeError):
    pass


class GovernanceDenied(RuntimeError):
    """Fallback denial type used when AGT is unavailable in local mode."""


_POLICY_CACHE: dict[str, Any] = {"expires_at": 0.0, "path": None, "version": None, "hash": None}


def _load_agt_govern() -> Any:
    try:
        from agentmesh.governance.policy import Policy  # noqa: F401
    except Exception as exc:
        raise PolicyConfigurationError(
            "agent-governance-toolkit-core is required for FarSight policy enforcement. "
            "Install it with: pip install agent-governance-toolkit-core"
        ) from exc


def _agt_evaluate_policy(policy_path: Path, context: dict[str, Any]) -> tuple[str, str | None]:
    """Evaluate context against an AGT Policy file. Returns (action, rule_name)."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from agentmesh.governance.policy import Policy
    except ImportError as exc:
        raise PolicyConfigurationError(
            "agent-governance-toolkit-core is required for FarSight policy enforcement. "
            "Install it with: pip install agent-governance-toolkit-core"
        ) from exc

    content = policy_path.read_text(encoding="utf-8")
    policy = Policy.from_yaml(content)

    # Evaluate rules in priority order; first match wins
    rules = sorted(policy.rules, key=lambda r: r.priority)
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.evaluate(context):
            return rule.action, rule.name

    return policy.default_action, None


def _policy_path() -> Path:
    return Path(os.getenv("FARSIGHT_AGT_POLICY_PATH", str(DEFAULT_POLICY_PATH))).resolve()


def _policy_source() -> str:
    return os.getenv("FARSIGHT_POLICY_SOURCE", "api").strip().lower()


def _allow_fallback() -> bool:
    return os.getenv("FARSIGHT_ALLOW_POLICY_FALLBACK", "").strip().lower() in {"1", "true", "yes"}


def _flatten_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items: list[str] = []
        for key, child in value.items():
            items.extend(_flatten_values(key))
            items.extend(_flatten_values(child))
        return items
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for child in value:
            items.extend(_flatten_values(child))
        return items
    return [str(value)]


def _contains_dangerous_input(payload: dict[str, Any]) -> bool:
    combined = "\n".join(_flatten_values(payload))
    return any(re.search(pattern, combined) for pattern in DANGEROUS_INPUT_PATTERNS)


def _extract_task_type(payload: dict[str, Any]) -> str:
    task_type = payload.get("taskType") or payload.get("task_type") or payload.get("requestedAction") or payload.get("requested_action")
    return str(task_type or "")


def build_policy_context(tool_name: str, risk_level: ToolRisk = ToolRisk.read_only, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "tool_name": tool_name,
        "action": {
            "type": tool_name,
            "risk_level": risk_level.value,
        },
        "risk_level": risk_level.value,
        "task_type": _extract_task_type(payload),
        "requested_action": str(payload.get("requestedAction") or payload.get("requested_action") or ""),
        "contains_dangerous_input": _contains_dangerous_input(payload),
        "payload": payload,
    }


def _evaluate_with_fallback(context: dict[str, Any]) -> PolicyDecision:
    tool_name = str(context["tool_name"])
    risk_level = ToolRisk(context.get("risk_level", ToolRisk.read_only.value))
    task_type = str(context.get("task_type") or "")

    if context.get("contains_dangerous_input"):
        return PolicyDecision(
            outcome=PolicyOutcome.deny,
            reason="Denied by fallback policy: unsafe arbitrary execution input was detected.",
            policyVersion=POLICY_VERSION,
            policyName="farsight-tool-policy-fallback",
            ruleName="deny-arbitrary-execution-input",
            evidence={"tool_name": tool_name, "task_type": task_type},
        )

    if tool_name in {"create_diagnostic_job", "request_follow_up_module_execution"} and task_type not in SAFE_DIAGNOSTIC_MODULES:
        return PolicyDecision(
            outcome=PolicyOutcome.deny,
            reason=f"Denied by fallback policy: unsupported diagnostic module '{task_type}'.",
            policyVersion=POLICY_VERSION,
            policyName="farsight-tool-policy-fallback",
            ruleName="deny-unsupported-diagnostic-module",
            evidence={"tool_name": tool_name, "task_type": task_type},
        )

    if tool_name in {"get_job_status", "get_job_result_summary", "retrieve_artifact_metadata", "query_device_investigation_history"}:
        return PolicyDecision(
            outcome=PolicyOutcome.allow,
            reason="Allowed by fallback policy: read-only lookup tool.",
            policyVersion=POLICY_VERSION,
            policyName="farsight-tool-policy-fallback",
            ruleName="allow-read-only-lookups",
            evidence={"tool_name": tool_name},
        )

    if tool_name == "request_approval_for_action" and context.get("requested_action"):
        return PolicyDecision(
            outcome=PolicyOutcome.allow,
            reason="Allowed by fallback policy: approval request creation.",
            policyVersion=POLICY_VERSION,
            policyName="farsight-tool-policy-fallback",
            ruleName="allow-approval-request",
            evidence={"tool_name": tool_name, "requested_action": context["requested_action"]},
        )

    if risk_level == ToolRisk.sensitive_diagnostic:
        return PolicyDecision(
            outcome=PolicyOutcome.require_approval,
            reason="Approval required by fallback policy: sensitive diagnostic request.",
            policyVersion=POLICY_VERSION,
            policyName="farsight-tool-policy-fallback",
            ruleName="require-approval-for-sensitive-diagnostics",
            evidence={"tool_name": tool_name, "risk_level": risk_level.value},
        )

    if tool_name in {"create_diagnostic_job", "request_follow_up_module_execution"}:
        return PolicyDecision(
            outcome=PolicyOutcome.allow,
            reason="Allowed by fallback policy: read-only diagnostic request.",
            policyVersion=POLICY_VERSION,
            policyName="farsight-tool-policy-fallback",
            ruleName="allow-read-only-diagnostic",
            evidence={"tool_name": tool_name, "task_type": task_type},
        )

    return PolicyDecision(
        outcome=PolicyOutcome.deny,
        reason="Denied by fallback policy: no matching allow rule.",
        policyVersion=POLICY_VERSION,
        policyName="farsight-tool-policy-fallback",
        ruleName="default-deny",
        evidence={"tool_name": tool_name},
    )


def _api_bearer_token() -> str:
    base_url = os.getenv("FARSIGHT_API_BASE_URL", "").rstrip("/")
    scope = normalize_api_scope(os.getenv("FARSIGHT_API_SCOPE", ""), base_url or "api://farsight")
    return DefaultAzureCredential().get_token(scope).token


def _fetch_policy_from_api() -> tuple[Path, str | None, str | None]:
    ttl = int(os.getenv("FARSIGHT_POLICY_CACHE_TTL_SECONDS", "60"))
    now = time.time()
    cached_path = _POLICY_CACHE.get("path")
    if cached_path and now < float(_POLICY_CACHE.get("expires_at", 0.0)):
        return Path(cached_path), _POLICY_CACHE.get("version"), _POLICY_CACHE.get("hash")

    base_url = os.getenv("FARSIGHT_API_BASE_URL", "").rstrip("/")
    if not base_url:
        raise PolicyConfigurationError("FARSIGHT_API_BASE_URL is required when FARSIGHT_POLICY_SOURCE=api.")

    policy_id = os.getenv("FARSIGHT_POLICY_ID", DEFAULT_POLICY_ID)
    request = urllib.request.Request(
        f"{base_url}/api/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {_api_bearer_token()}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            import json

            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise PolicyConfigurationError(f"Failed to retrieve active policy '{policy_id}' from FarSight API.") from exc

    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise PolicyConfigurationError(f"FarSight API returned an empty policy for '{policy_id}'.")

    temp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", prefix="farsight-agt-policy-", delete=False)
    with temp:
        temp.write(content)

    _POLICY_CACHE.update({
        "expires_at": now + ttl,
        "path": temp.name,
        "version": body.get("version"),
        "hash": body.get("contentHash"),
    })
    return Path(temp.name), body.get("version"), body.get("contentHash")


def _resolve_policy_material() -> tuple[Path, str | None, str | None]:
    if _policy_source() == "api":
        return _fetch_policy_from_api()
    return _policy_path(), None, None


def _evaluate_with_agt(context: dict[str, Any]) -> PolicyDecision:
    policy_path, policy_version, policy_hash = _resolve_policy_material()
    if not policy_path.exists():
        raise PolicyConfigurationError(f"AGT policy file not found: {policy_path}")

    action, rule_name = _agt_evaluate_policy(policy_path, context)

    policy_doc = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    effective_version = str(policy_version or policy_doc.get("version") or POLICY_VERSION)
    effective_name = str(policy_doc.get("name") or policy_path.stem)

    if action == "allow":
        return PolicyDecision(
            outcome=PolicyOutcome.allow,
            reason=f"Allowed by AGT policy rule '{rule_name}'." if rule_name else "Allowed by AGT policy default.",
            policyVersion=effective_version,
            policyName=effective_name,
            ruleName=rule_name,
            evidence={"tool_name": context["tool_name"], "content_hash": policy_hash},
        )
    if action == "require_approval":
        return PolicyDecision(
            outcome=PolicyOutcome.require_approval,
            reason=f"AGT policy rule '{rule_name}' requires approval.",
            policyVersion=effective_version,
            policyName=effective_name,
            ruleName=rule_name,
            evidence={"tool_name": context["tool_name"], "content_hash": policy_hash},
        )
    # deny (default)
    return PolicyDecision(
        outcome=PolicyOutcome.deny,
        reason=f"Denied by AGT policy rule '{rule_name}'." if rule_name else "Denied by AGT policy default (no matching allow rule).",
        policyVersion=effective_version,
        policyName=effective_name,
        ruleName=rule_name,
        evidence={"tool_name": context["tool_name"], "content_hash": policy_hash},
    )


def evaluate_policy(tool_name: str, risk_level: ToolRisk = ToolRisk.read_only, payload: dict[str, Any] | None = None) -> PolicyDecision:
    context = build_policy_context(tool_name=tool_name, risk_level=risk_level, payload=payload)
    if _allow_fallback():
        return _evaluate_with_fallback(context)
    return _evaluate_with_agt(context)
