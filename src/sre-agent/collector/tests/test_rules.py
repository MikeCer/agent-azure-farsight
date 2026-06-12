import unittest

from intune_diagnostics.config import DiagnosticConfig
from intune_diagnostics.rules import evaluate, resolution_error_finding


class RulesTests(unittest.TestCase):
    def test_flags_stale_noncompliant_and_hardware_bottleneck(self):
        signals = {
            "inventory": {
                "lastSyncDateTime": "2020-01-01T00:00:00Z",
                "complianceState": "noncompliant",
                "hardwareInformation": {"systemMemoryInGB": 4, "storageCapacityInGB": 64},
            },
            "compliance": [{"state": "noncompliant", "displayName": "Baseline"}],
            "health_attestation": {},
            "troubleshooting_events": [],
            "endpoint_analytics": {},
        }
        ids = {finding.id for finding in evaluate(signals, DiagnosticConfig())}
        self.assertIn("stale-intune-checkin", ids)
        self.assertIn("device-noncompliant", ids)
        self.assertIn("hardware-capacity-bottleneck", ids)

    def test_flags_endpoint_analytics_signals(self):
        signals = {
            "inventory": {},
            "compliance": [],
            "health_attestation": {},
            "troubleshooting_events": [],
            "endpoint_analytics": {
                "device_performance": [{"healthScore": 30, "bootTimeInMs": 180000}],
                "app_health_device_performance": [{"crashCount": 2}],
            },
        }
        ids = {finding.id for finding in evaluate(signals, DiagnosticConfig())}
        self.assertIn("endpoint-analytics-performance", ids)
        self.assertIn("endpoint-analytics-app-reliability", ids)

    def test_flags_expanded_intune_evidence(self):
        signals = {
            "inventory": {},
            "compliance": [],
            "compliance_setting_states": [{"setting": "Require BitLocker", "state": "noncompliant"}],
            "configuration_setting_states": [],
            "app_install_status": [{"AppName": "Required App", "InstallState": "failed", "ErrorCode": "0x1"}],
            "updates": {"windows_update_status": [{"updateState": "attentionRequired"}]},
            "management": {
                "device_action_results": [{"actionName": "sync", "actionState": "failed"}],
                "remediation_script_states": [],
            },
            "identity": {"entra_device": {"accountEnabled": False, "isCompliant": True}},
            "security": {
                "windows_protection_state": {"defenderEnabled": False},
                "endpoint_security_intent_device_states": [],
            },
            "health_attestation": {},
            "troubleshooting_events": [],
            "endpoint_analytics": {},
        }
        ids = {finding.id for finding in evaluate(signals, DiagnosticConfig())}
        self.assertIn("setting-level-policy-failures", ids)
        self.assertIn("app-install-failures", ids)
        self.assertIn("windows-update-issues", ids)
        self.assertIn("management-action-or-script-failures", ids)
        self.assertIn("entra-device-identity-risk", ids)
        self.assertIn("windows-protection-risk", ids)

    def test_resolution_authorization_error_has_permission_specific_title_and_actions(self):
        finding = resolution_error_finding(
            "authorization_error",
            "Intune managed-device lookup failed with HTTP 401.",
            details={
                "http_status": 401,
                "graph_error_code": "Forbidden",
                "url": "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices",
            },
        )

        self.assertEqual(finding.title, "Intune device lookup failed because Graph access was denied")
        self.assertIn("DeviceManagementManagedDevices.Read.All", " ".join(finding.recommended_actions))
        self.assertEqual(finding.evidence[1].field, "graph_error_details")


if __name__ == "__main__":
    unittest.main()
