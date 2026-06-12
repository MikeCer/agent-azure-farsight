from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.models import ToolRisk
from app.policy import PolicyConfigurationError, evaluate_policy


class PolicyTests(unittest.TestCase):
    def test_policy_fails_closed_without_agt_or_fallback(self) -> None:
        def missing_agt():
            raise PolicyConfigurationError("missing AGT")

        with patch.dict(os.environ, {}, clear=True), patch("app.policy._load_agt_govern", missing_agt):
            with self.assertRaises(PolicyConfigurationError):
                evaluate_policy("get_job_status", payload={"jobId": "job-1"})

    def test_fallback_allows_read_only_lookup(self) -> None:
        with patch.dict(os.environ, {"FARSIGHT_ALLOW_POLICY_FALLBACK": "true"}, clear=True):
            decision = evaluate_policy("get_job_status", payload={"jobId": "job-1"})

        self.assertEqual(decision.outcome, "allow")
        self.assertEqual(decision.rule_name, "allow-read-only-lookups")

    def test_fallback_requires_approval_for_sensitive_job(self) -> None:
        with patch.dict(os.environ, {"FARSIGHT_ALLOW_POLICY_FALLBACK": "true"}, clear=True):
            decision = evaluate_policy(
                "create_diagnostic_job",
                ToolRisk.sensitive_diagnostic,
                {"taskType": "Get-AppLogBundle", "deviceId": "device-1"},
            )

        self.assertEqual(decision.outcome, "require_approval")
        self.assertEqual(decision.rule_name, "require-approval-for-sensitive-diagnostics")

    def test_fallback_denies_arbitrary_execution_payload(self) -> None:
        with patch.dict(os.environ, {"FARSIGHT_ALLOW_POLICY_FALLBACK": "true"}, clear=True):
            decision = evaluate_policy(
                "create_diagnostic_job",
                ToolRisk.read_only,
                {
                    "taskType": "Get-AppLogBundle",
                    "parameters": {
                        "path": "C:\\Temp; powershell -EncodedCommand bad"
                    },
                },
            )

        self.assertEqual(decision.outcome, "deny")
        self.assertEqual(decision.rule_name, "deny-arbitrary-execution-input")

    def test_fallback_denies_unsupported_module(self) -> None:
        with patch.dict(os.environ, {"FARSIGHT_ALLOW_POLICY_FALLBACK": "true"}, clear=True):
            decision = evaluate_policy(
                "create_diagnostic_job",
                ToolRisk.read_only,
                {"taskType": "Invoke-ArbitraryScript"},
            )

        self.assertEqual(decision.outcome, "deny")
        self.assertEqual(decision.rule_name, "deny-unsupported-diagnostic-module")

    def test_fallback_allows_well_formed_approval_request(self) -> None:
        with patch.dict(os.environ, {"FARSIGHT_ALLOW_POLICY_FALLBACK": "true"}, clear=True):
            decision = evaluate_policy(
                "request_approval_for_action",
                ToolRisk.sensitive_diagnostic,
                {"requestedAction": "Start approved trace window"},
            )

        self.assertEqual(decision.outcome, "allow")
        self.assertEqual(decision.rule_name, "allow-approval-request")


if __name__ == "__main__":
    unittest.main()
