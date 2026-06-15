import unittest

from intune_diagnostics.config import DiagnosticConfig
from intune_diagnostics.graph_client import GraphError
from intune_diagnostics.resolver import DeviceResolutionError, resolve_device_by_name


class FakeGraph:
    def __init__(self, items, fail_filter=False):
        self.items = items
        self.fail_filter = fail_filter
        self.calls = []

    def get_all(self, api_version, path_or_url, *, params=None, max_pages=None):
        self.calls.append((api_version, path_or_url, params, max_pages))
        if params and "$filter" in params and self.fail_filter:
            raise GraphError("filter unsupported", 400, path_or_url)
        return self.items, False


class ResolverTests(unittest.TestCase):
    def test_resolves_single_device_after_filter_fallback(self):
        graph = FakeGraph([{"id": "1", "deviceName": "WIN-01"}], fail_filter=True)
        device = resolve_device_by_name(graph, "WIN-01", DiagnosticConfig())
        self.assertEqual(device["id"], "1")
        self.assertEqual(len(graph.calls), 2)

    def test_ambiguous_device_name_raises_with_candidates(self):
        graph = FakeGraph([{"id": "1", "deviceName": "WIN-01"}, {"id": "2", "deviceName": "WIN-01"}])
        with self.assertRaises(DeviceResolutionError) as caught:
            resolve_device_by_name(graph, "WIN-01", DiagnosticConfig())
        self.assertEqual(caught.exception.kind, "ambiguous")
        self.assertEqual(len(caught.exception.candidates), 2)

    def test_escapes_apostrophe_in_odata_filter(self):
        graph = FakeGraph([{"id": "1", "deviceName": "PC-O'Hare"}])
        resolve_device_by_name(graph, "PC-O'Hare", DiagnosticConfig())
        self.assertEqual(graph.calls[0][2]["$filter"], "deviceName eq 'PC-O''Hare'")

    def test_permission_failure_raises_authorization_error(self):
        class AuthFailGraph(FakeGraph):
            def get_all(self, api_version, path_or_url, *, params=None, max_pages=None):
                raise GraphError(
                    "Microsoft Graph returned HTTP 401: forbidden",
                    401,
                    "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices",
                    error_code="Forbidden",
                )

        with self.assertRaises(DeviceResolutionError) as caught:
            resolve_device_by_name(AuthFailGraph([]), "WIN-01", DiagnosticConfig())

        self.assertEqual(caught.exception.kind, "authorization_error")
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.error_code, "Forbidden")


if __name__ == "__main__":
    unittest.main()
