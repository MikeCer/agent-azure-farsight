from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import ToolRisk
from app.policy import (
    PolicyConfigurationError,
    _agt_evaluate_policy,
    build_policy_context,
    _evaluate_with_agt,
)

# Canonical policy for tests — mirrors src/api/app/policies/farsight-tool-policy.yaml
POLICY_YAML = textwrap.dedent("""\
    apiVersion: governance.toolkit/v1
    name: farsight-tool-policy
    version: "2026-06-12.1"
    default_action: deny
    rules:
      - name: deny-arbitrary-execution-input
        condition: "contains_dangerous_input"
        action: deny
      - name: allow-read-only-lookups
        condition: "tool_name in ['get_job_status', 'get_job_result_summary', 'retrieve_artifact_metadata', 'query_device_investigation_history']"
        action: allow
      - name: allow-approval-request
        condition: "tool_name == 'request_approval_for_action' and requested_action"
        action: allow
      - name: require-approval-for-sensitive-diagnostics
        condition: "risk_level == 'sensitive-diagnostic'"
        action: require_approval
      - name: allow-read-only-diagnostic-job
        condition: "tool_name == 'create_diagnostic_job' and risk_level == 'read-only' and task_type in ['Get-AppLogBundle', 'Get-AppEventSlice', 'Get-AppHealthSnapshot', 'Test-AppConnectivity', 'Get-ConfigEvidence', 'Get-ServiceStatusSnapshot']"
        action: allow
      - name: allow-read-only-follow-up
        condition: "tool_name == 'request_follow_up_module_execution' and risk_level == 'read-only' and task_type in ['Get-AppLogBundle', 'Get-AppEventSlice', 'Get-AppHealthSnapshot', 'Test-AppConnectivity', 'Get-ConfigEvidence', 'Get-ServiceStatusSnapshot']"
        action: allow
""")


def _policy_file() -> Path:
    """Write POLICY_YAML to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", prefix="test-policy-", delete=False, encoding="utf-8")
    f.write(POLICY_YAML)
    f.flush()
    f.close()
    return Path(f.name)


def _eval(tool_name: str, risk: ToolRisk = ToolRisk.read_only, payload: dict | None = None):
    """Helper: evaluate against in-memory test policy."""
    ctx = build_policy_context(tool_name, risk, payload or {})
    policy_path = _policy_file()
    try:
        return _agt_evaluate_policy(policy_path, ctx)
    finally:
        policy_path.unlink(missing_ok=True)


class PolicyTests(unittest.TestCase):
    def test_allows_read_only_lookup(self) -> None:
        action, rule = _eval("get_job_status", payload={"jobId": "job-1"})
        self.assertEqual(action, "allow")
        self.assertEqual(rule, "allow-read-only-lookups")

    def test_allows_diagnostic_job_approved_module(self) -> None:
        action, rule = _eval("create_diagnostic_job", payload={"taskType": "Get-AppLogBundle"})
        self.assertEqual(action, "allow")
        self.assertEqual(rule, "allow-read-only-diagnostic-job")

    def test_denies_diagnostic_job_unsupported_module(self) -> None:
        action, rule = _eval("create_diagnostic_job", payload={"taskType": "Invoke-ArbitraryScript"})
        self.assertEqual(action, "deny")  # via default_action: deny (no allow rule matches)

    def test_requires_approval_for_sensitive_job(self) -> None:
        action, rule = _eval("create_diagnostic_job", ToolRisk.sensitive_diagnostic, {"taskType": "Get-AppLogBundle"})
        self.assertEqual(action, "require_approval")
        self.assertEqual(rule, "require-approval-for-sensitive-diagnostics")

    def test_denies_arbitrary_execution_payload(self) -> None:
        action, rule = _eval(
            "create_diagnostic_job",
            ToolRisk.read_only,
            {"taskType": "Get-AppLogBundle", "parameters": {"path": "C:\\Temp; powershell bad"}},
        )
        self.assertEqual(action, "deny")
        self.assertEqual(rule, "deny-arbitrary-execution-input")

    def test_allows_well_formed_approval_request(self) -> None:
        action, rule = _eval(
            "request_approval_for_action",
            ToolRisk.sensitive_diagnostic,
            {"requestedAction": "Start approved trace window"},
        )
        self.assertEqual(action, "allow")
        self.assertEqual(rule, "allow-approval-request")

    def test_policy_fails_closed_when_api_unavailable(self) -> None:
        """evaluate_policy must raise PolicyConfigurationError when the API is unreachable."""
        with patch("app.policy._fetch_policy_from_api", side_effect=PolicyConfigurationError("API down")):
            from app.policy import evaluate_policy
            with self.assertRaises(PolicyConfigurationError):
                evaluate_policy("get_job_status", payload={"jobId": "job-1"})


if __name__ == "__main__":
    unittest.main()
