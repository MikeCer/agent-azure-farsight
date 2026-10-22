import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from intune_diagnostics.cli import main as cli_main
from intune_diagnostics.collector import collect_device_diagnostics
from intune_diagnostics.config import DiagnosticConfig, EVIDENCE_SECTIONS, parse_sections
from intune_diagnostics.graph_client import GraphError
from intune_diagnostics.tool import main
from test_collector import FakeGraph


DEVICE = {"id": "device-1", "deviceName": "WIN-01", "azureADDeviceId": "aad-1"}


class SectionTests(unittest.TestCase):
    def collect(self, sections, *, beta=True, graph=None):
        graph = graph or FakeGraph()
        document = collect_device_diagnostics(
            graph, DEVICE, "WIN-01",
            DiagnosticConfig(sections=sections, include_beta_endpoint_analytics=beta),
        )
        return graph, document.to_sre_dict()

    def test_hardware_queries_and_output_are_narrow(self):
        expected = {
            "cpu": {"processorArchitecture": "x64"},
            "memory": {"physicalMemoryInBytes": 17179869184, "freeMemoryInBytes": None},
            "storage": {
                "totalStorageSpaceInBytes": 100, "freeStorageSpaceInBytes": 50,
                "freeStoragePercent": 50.0,
            },
        }
        for section, evidence in expected.items():
            with self.subTest(section=section):
                graph, payload = self.collect(section, beta=False)
                self.assertEqual(payload["diagnostic_evidence"], {section: evidence})
                self.assertEqual(len(graph.calls), 1)
                self.assertEqual(graph.calls[0][:3], ("get", "beta", "/deviceManagement/managedDevices/device-1"))
                selected_fields = graph.calls[0][3]["$select"].split(",")
                self.assertEqual(set(selected_fields), {"id", *[key for key in evidence if key not in {
                    "freeMemoryInBytes", "freeStoragePercent",
                }]})
                self.assertEqual(payload["issues"], [])
                self.assertEqual(payload["collection_scope"]["mode"], "targeted")
                self.assertLess(len(json.dumps(payload)), 2000)

    def test_memory_limitation_is_explicit(self):
        _, payload = self.collect("memory")
        self.assertTrue(any("Live free RAM" in gap["reason"] for gap in payload["data_gaps"]))

    def test_unreported_hardware_field_is_visible(self):
        graph = FakeGraph()
        graph.get = lambda *args, **kwargs: {"id": "device-1"}
        _, payload = self.collect("cpu", graph=graph)
        self.assertIsNone(payload["diagnostic_evidence"]["cpu"]["processorArchitecture"])
        self.assertTrue(any("processorArchitecture" in gap["reason"] for gap in payload["data_gaps"]))

    def test_combined_sections_share_health_query(self):
        graph, payload = self.collect(" memory, cpu,memory ")
        self.assertEqual(set(payload["diagnostic_evidence"]), {"memory", "cpu"})
        self.assertEqual(len(graph.calls), 1)
        self.assertEqual(payload["collection_scope"]["requested_sections"], ["memory", "cpu"])

    def test_hardware_combined_with_nonhardware_section(self):
        _, payload = self.collect("cpu,installed_applications")
        self.assertEqual(set(payload["diagnostic_evidence"]), {"cpu", "installed_applications"})
        self.assertEqual(payload["issues"], [])

    def test_every_named_section_limits_output(self):
        for section in EVIDENCE_SECTIONS:
            with self.subTest(section=section):
                _, payload = self.collect(section)
                self.assertLessEqual(set(payload["diagnostic_evidence"]), {section})
                self.assertEqual(payload["collection_scope"]["requested_sections"], [section])

    def test_performance_skips_app_inventory_and_crash_list(self):
        graph, payload = self.collect("performance")
        paths = [call[2] for call in graph.calls]
        self.assertEqual(len(paths), 4)  # Device detail plus three analytics summaries.
        self.assertFalse(any("detectedApps" in path or "ApplicationPerformance" in path for path in paths))
        self.assertEqual(set(payload["diagnostic_evidence"]), {"performance"})

    def test_crashes_skip_startup_and_resource_queries(self):
        graph, payload = self.collect("app_crashes")
        paths = [call[2] for call in graph.calls]
        self.assertFalse(any("ResourcePerformance" in path or path.endswith("AnalyticsDevicePerformance") for path in paths))
        self.assertEqual(set(payload["diagnostic_evidence"]), {"app_crashes"})

    def test_disabled_analytics_is_reported_without_analytics_requests(self):
        graph, payload = self.collect("performance", beta=False)
        self.assertEqual(len(graph.calls), 1)
        self.assertEqual(payload["diagnostic_evidence"], {})
        self.assertTrue(any("disabled" in gap["reason"] for gap in payload["data_gaps"]))

    def test_optional_graph_failure_is_visible(self):
        graph = FakeGraph()
        graph.get = lambda *args, **kwargs: self.fail_graph()
        _, payload = self.collect("cpu", graph=graph)
        self.assertIsNone(payload["diagnostic_evidence"]["cpu"]["processorArchitecture"])
        self.assertTrue(any(gap["source"] == "device_health_detail" for gap in payload["data_gaps"]))

    @staticmethod
    def fail_graph():
        raise GraphError("Access denied", 403, "/deviceManagement/managedDevices/device-1")

    def test_full_is_backward_compatible_and_broader_than_targeted(self):
        full_graph, full = self.collect("full")
        cpu_graph, cpu = self.collect("cpu")
        self.assertIn("installed_applications", full["diagnostic_evidence"])
        self.assertIn("device_health", full["diagnostic_evidence"])
        self.assertNotIn("cpu", full["diagnostic_evidence"])
        self.assertEqual(full["collection_scope"]["mode"], "full")
        self.assertGreater(len(full_graph.calls), len(cpu_graph.calls))
        self.assertGreater(len(json.dumps(full)), len(json.dumps(cpu)) * 3)

    def test_invalid_selection_fails_before_authentication(self):
        for value in ("", "unknown", "full,cpu", "cpu,", "CPU", "../cpu", None, ["cpu"]):
            with self.subTest(value=value), patch("intune_diagnostics.tool.build_token_provider") as auth:
                payload = main("WIN-01", sections=value)
                auth.assert_not_called()
                self.assertEqual(payload["issues"][0]["id"], "device-resolution-invalid_input")
                self.assertIn("sections", payload["issues"][0]["description"])

    def test_parser_rejects_invalid_config(self):
        with self.assertRaises(ValueError):
            DiagnosticConfig(sections="bad")
        self.assertEqual(parse_sections("cpu, memory,cpu"), ("cpu", "memory"))

    def test_tool_forwards_scope_to_collector(self):
        document = collect_device_diagnostics(FakeGraph(), DEVICE, "WIN-01", DiagnosticConfig(sections="cpu"))
        with (
            patch("intune_diagnostics.tool.build_token_provider", return_value=(lambda: "token", None)),
            patch("intune_diagnostics.tool.resolve_device_by_name", return_value=DEVICE),
            patch("intune_diagnostics.tool.collect_device_diagnostics", return_value=document) as collect,
        ):
            payload = main("WIN-01", sections="cpu")
        self.assertEqual(collect.call_args.args[3].sections, "cpu")
        self.assertEqual(set(payload["diagnostic_evidence"]), {"cpu"})

    def test_cli_forwards_sections(self):
        with patch("intune_diagnostics.cli.collect_intune_diagnostics", return_value={}) as collect:
            with patch("intune_diagnostics.cli._write_output"):
                self.assertEqual(cli_main(["--device-name", "WIN-01", "--sections", "memory,cpu"]), 0)
        self.assertEqual(collect.call_args.kwargs["sections"], "memory,cpu")

    def test_embedded_tool_has_matching_selection_contract(self):
        root = Path(__file__).resolve().parents[2]
        tool = root / "agent" / "tools" / "intune_diagnostics_tool.py"
        code = (
            "import importlib.util; "
            f"spec = importlib.util.spec_from_file_location('embedded_tool', {str(tool)!r}); "
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "result = module.main('WIN-01', sections='not-a-section'); "
            "assert result['issues'][0]['id'] == 'device-resolution-invalid_input'; "
            "from intune_diagnostics.collector import collect_device_diagnostics; "
            "from intune_diagnostics.config import DiagnosticConfig; "
            "from test_collector import FakeGraph; "
            f"device = {DEVICE!r}; "
            "result = collect_device_diagnostics(FakeGraph(), device, 'WIN-01', "
            "DiagnosticConfig(sections='cpu')).to_sre_dict(); "
            "assert result['diagnostic_evidence'] == {'cpu': {'processorArchitecture': 'x64'}}"
        )
        subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(__file__).parent)


if __name__ == "__main__":
    unittest.main()
