from contextlib import redirect_stderr
import base64
import io
import json
from types import SimpleNamespace
import unittest

from intune_diagnostics.graph_client import GraphClient, GraphError


class FakeResponse:
    def __init__(self, status_code, payload, url="https://graph.test/v1.0/items", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.url = url
        self.headers = headers or {}
        self.content = b"{}"
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        response.request = SimpleNamespace(method=method)
        return response


class GraphClientTests(unittest.TestCase):
    def test_follows_odata_next_link_verbatim(self):
        session = FakeSession(
            [
                FakeResponse(200, {"value": [{"id": "1"}], "@odata.nextLink": "https://graph.test/next"}),
                FakeResponse(200, {"value": [{"id": "2"}]}, "https://graph.test/next"),
            ]
        )
        client = GraphClient(lambda: "token", base_url="https://graph.test", session=session)
        items, followed = client.get_all("v1.0", "/items", params={"$select": "id"})
        self.assertTrue(followed)
        self.assertEqual(items, [{"id": "1"}, {"id": "2"}])
        self.assertEqual(session.requests[1][1], "https://graph.test/next")
        self.assertIsNone(session.requests[1][2]["params"])

    def test_retries_429_with_retry_after(self):
        session = FakeSession(
            [
                FakeResponse(429, {"error": {"message": "throttled"}}, headers={"Retry-After": "0"}),
                FakeResponse(200, {"value": [{"id": "1"}]}),
            ]
        )
        client = GraphClient(lambda: "token", base_url="https://graph.test", session=session)
        items, _ = client.get_all("v1.0", "/items")
        self.assertEqual(items, [{"id": "1"}])
        self.assertEqual(len(session.requests), 2)

    def test_logs_token_identity_context_on_graph_error(self):
        token = _jwt(
            {
                "tid": "tenant-1",
                "oid": "object-1",
                "appid": "app-1",
                "preferred_username": "user@example.com",
                "idtyp": "app",
            }
        )
        session = FakeSession([FakeResponse(401, {"error": {"code": "Forbidden", "message": "denied"}})])
        client = GraphClient(lambda: token, base_url="https://graph.test", session=session)
        stderr = io.StringIO()

        with redirect_stderr(stderr), self.assertRaises(GraphError) as caught:
            client.get("v1.0", "/deviceManagement/managedDevices")

        log = stderr.getvalue()
        self.assertIn("status=401", log)
        self.assertIn("tenant_id=tenant-1", log)
        self.assertIn("object_id=object-1", log)
        self.assertIn("app_id=app-1", log)
        self.assertEqual(caught.exception.identity_context["tenant_id"], "tenant-1")
        self.assertEqual(caught.exception.identity_context["object_id"], "object-1")


def _jwt(claims):
    header = _b64({"alg": "none"})
    payload = _b64(claims)
    return f"{header}.{payload}."


def _b64(value):
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


if __name__ == "__main__":
    unittest.main()
