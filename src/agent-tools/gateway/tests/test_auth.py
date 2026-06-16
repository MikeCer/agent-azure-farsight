from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.auth import require_workload_caller


class WorkloadAuthTests(unittest.TestCase):
    def test_auth_disabled_returns_sentinel_caller(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            from app import auth as auth_mod

            auth_mod._workload_auth_config.cache_clear()
            auth_mod._jwk_client.cache_clear()
            caller = require_workload_caller()
        self.assertEqual(caller.object_id, "gateway-workload-auth-disabled")

    def test_enabled_requires_bearer_header(self) -> None:
        env = {
            "FARSIGHT_AGENT_TOOLS_ENFORCE_WORKLOAD_AUTH": "true",
            "FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES": "api://agt/.default",
            "FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS": "sp-1",
            "FARSIGHT_ENTRA_TENANT_ID": "tenant-1",
        }
        with patch.dict("os.environ", env, clear=True):
            from app import auth as auth_mod

            auth_mod._workload_auth_config.cache_clear()
            auth_mod._jwk_client.cache_clear()
            with self.assertRaises(HTTPException) as exc:
                require_workload_caller(None)
        self.assertEqual(exc.exception.status_code, 401)

    def test_enabled_accepts_valid_claims(self) -> None:
        env = {
            "FARSIGHT_AGENT_TOOLS_ENFORCE_WORKLOAD_AUTH": "true",
            "FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES": "api://agt/.default",
            "FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS": "sp-1",
            "FARSIGHT_ENTRA_TENANT_ID": "tenant-1",
            "FARSIGHT_AGENT_TOOLS_ALLOWED_ISSUERS": "https://login.microsoftonline.com/tenant-1/v2.0",
        }
        claims = {
            "iss": "https://login.microsoftonline.com/tenant-1/v2.0",
            "aud": "api://agt/.default",
            "exp": 9999999999,
            "tid": "tenant-1",
            "oid": "sp-1",
            "appid": "app-1",
            "roles": ["Farsight.AgentTools.Access"],
            "idtyp": "app",
        }
        with patch.dict("os.environ", env, clear=True):
            from app import auth as auth_mod

            auth_mod._workload_auth_config.cache_clear()
            auth_mod._jwk_client.cache_clear()
            with patch("app.auth._decode_workload_token", return_value=claims):
                caller = require_workload_caller("Bearer token")
        self.assertEqual(caller.object_id, "sp-1")
        self.assertEqual(caller.app_id, "app-1")


if __name__ == "__main__":
    unittest.main()
