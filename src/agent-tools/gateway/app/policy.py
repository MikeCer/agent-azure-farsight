from .models import PolicyDecision, PolicyOutcome, ToolRisk

POLICY_VERSION = "2026-06-12.1"


def evaluate_policy(tool_name: str, risk_level: ToolRisk = ToolRisk.read_only) -> PolicyDecision:
    # TODO: Replace this placeholder with AGT policy evaluation and audit emission.
    if risk_level == ToolRisk.sensitive_diagnostic:
        return PolicyDecision(outcome=PolicyOutcome.require_approval, reason=f"{tool_name} requires approval", policyVersion=POLICY_VERSION)
    return PolicyDecision(outcome=PolicyOutcome.allow, reason=f"{tool_name} is read-only", policyVersion=POLICY_VERSION)
