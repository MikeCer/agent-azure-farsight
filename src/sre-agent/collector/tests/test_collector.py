import json
import unittest

from intune_diagnostics.collector import collect_device_diagnostics
from intune_diagnostics.config import DiagnosticConfig
from intune_diagnostics.graph_client import GraphError


class FakeGraph:
    def __init__(self):
        self.calls = []

    def get(self, api_version, path_or_url, *, params=None):
        self.calls.append(("get", api_version, path_or_url, params))
        if api_version == "beta" and path_or_url.endswith("/detectedApps"):
            return {"value": [{"displayName": "App", "version": "1.0", "publisher": "Publisher"}]}
        if api_version == "beta" and path_or_url.endswith("/userExperienceAnalyticsAppHealthApplicationPerformance"):
            return {
                "value": [
                    {
                        "appDisplayName": "Crashy App",
                        "appCrashCount": 3,
                        "appHangCount": 1,
                        "appHealthScore": 20,
                    }
                ]
            }
        if api_version == "beta" and path_or_url.endswith("/device-1"):
            return {
                "id": "device-1",
                "deviceName": "WIN-01",
                "isEncrypted": False,
                "totalStorageSpaceInBytes": 100,
                "freeStorageSpaceInBytes": 50,
                "physicalMemoryInBytes": 17179869184,
                "processorArchitecture": "x64",
            }
        if path_or_url.endswith("/device-1"):
            return {
                "id": "device-1",
                "deviceName": "WIN-01",
                "azureADDeviceId": "aad-1",
                "userId": "user-1",
                "userPrincipalName": "user@example.com",
                "serialNumber": "SERIAL",
                "lastSyncDateTime": "2020-01-01T00:00:00Z",
                "complianceState": "compliant",
                "hardwareInformation": {"systemMemoryInGB": 16},
                "deviceHealthAttestationState": {},
                "deviceActionResults": [
                    {
                        "actionName": "rebootNow",
                        "actionState": "done",
                        "startDateTime": "2026-01-01T00:00:00Z",
                        "lastUpdatedDateTime": "2026-01-01T00:02:00Z",
                    }
                ],
            }
        raise GraphError("not found", 404, path_or_url)

    def get_all(self, api_version, path_or_url, *, params=None, max_pages=None):
        self.calls.append(("get_all", api_version, path_or_url, params))
        if path_or_url.endswith("/deviceCompliancePolicyStates"):
            return [], False
        if path_or_url.endswith("/deviceConfigurationStates"):
            return [], False
        if path_or_url.endswith("/deviceManagementTroubleshootingEvents"):
            return [{"status": "failed", "managedDeviceId": "device-1"}], False
        if path_or_url.endswith("/auditEvents"):
            return [
                {
                    "activity": "Update device",
                    "activityDateTime": "2026-01-01T00:03:00Z",
                    "activityResult": "success",
                    "resources": [{"resourceId": "device-1", "displayName": "WIN-01"}],
                }
            ], False
        if api_version == "beta":
            if path_or_url.endswith("/userExperienceAnalyticsDevicePerformance"):
                return [{"startupPerformanceScore": 40, "healthStatus": "needsAttention", "coreBootTimeInMs": 180000}], False
            if path_or_url.endswith("/userExperienceAnalyticsAppHealthDevicePerformance"):
                return [{"deviceAppHealthScore": 90, "healthStatus": "meetingGoals"}], False
            if path_or_url.endswith("/userExperienceAnalyticsResourcePerformance"):
                return [{"deviceResourcePerformanceScore": 80, "healthStatus": "meetingGoals"}], False
            return [], False
        return [], False

    def post(self, api_version, path_or_url, *, payload=None):
        self.calls.append(("post", api_version, path_or_url, payload))
        if path_or_url.endswith("/getDeviceInstallStatusReport"):
            return {
                "schema": [{"column": "AppName"}, {"column": "InstallState"}, {"column": "ErrorCode"}],
                "values": [["Required App", "failed", "0x1"]],
            }
        return {}


class CollectorTests(unittest.TestCase):
    def test_collects_navigation_sources_redacts_pii_and_tries_beta_join_keys(self):
        graph = FakeGraph()
        document = collect_device_diagnostics(
            graph,
            {"id": "device-1", "deviceName": "WIN-01", "azureADDeviceId": "aad-1"},
            "WIN-01",
            DiagnosticConfig(),
        )
        self.assertEqual(document.signals["inventory"]["userPrincipalName"], "redacted")
        self.assertEqual(document.signals["app_install_status"][0]["AppName"], "Required App")
        self.assertEqual(len(document.signals["troubleshooting_events"]), 1)
        finding_ids = {finding.id for finding in document.findings}
        self.assertIn("endpoint-analytics-performance", finding_ids)
        self.assertIn("app-install-failures", finding_ids)
        beta_filters = [
            call[3]["$filter"]
            for call in graph.calls
            if call[0] == "get_all" and call[1] == "beta" and call[3]
        ]
        self.assertIn("id eq 'device-1'", beta_filters)
        self.assertIn("deviceId eq 'device-1'", beta_filters)

    def test_default_json_is_compact_for_sre_agent(self):
        graph = FakeGraph()
        document = collect_device_diagnostics(
            graph,
            {"id": "device-1", "deviceName": "WIN-01", "azureADDeviceId": "aad-1"},
            "WIN-01",
            DiagnosticConfig(),
        )
        payload = json.loads(document.to_json())
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertIn("diagnostic_evidence", payload)
        self.assertIn("assessment", payload)
        self.assertFalse(payload["diagnostic_evidence"]["device_health"]["isEncrypted"])
        self.assertEqual(payload["diagnostic_evidence"]["device_health"]["freeStoragePercent"], 50.0)
        self.assertIn("performance", payload["diagnostic_evidence"])
        self.assertEqual(payload["diagnostic_evidence"]["installed_applications"][0]["displayName"], "App")
        self.assertEqual(
            payload["diagnostic_evidence"]["app_crashes"]["crashing_applications"][0]["appDisplayName"],
            "Crashy App",
        )
        self.assertEqual(
            payload["diagnostic_evidence"]["recent_restart_shutdown_events"][0]["eventType"],
            "restart",
        )
        self.assertEqual(
            payload["diagnostic_evidence"]["device_timeline_events"][0]["source"],
            "intune_audit_event",
        )
        self.assertNotIn("collection_report", payload)
        self.assertNotIn("signals", payload)


if __name__ == "__main__":
    unittest.main()
