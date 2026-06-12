import os
from dataclasses import dataclass

import httpx
from azure.identity import DefaultAzureCredential


@dataclass(frozen=True)
class ManagedIdentityAuth:
    """Placeholder for Azure SRE Agent managed identity authentication."""

    credential: DefaultAzureCredential
    scope: str

    def bearer_token(self) -> str:
        # TODO: Request a token for the FarSight API application ID URI/scope.
        token = self.credential.get_token(self.scope)
        return token.token


class FarSightApiClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get("FARSIGHT_API_BASE_URL", "https://farsight-api.example.invalid")
        self.auth = ManagedIdentityAuth(
            credential=DefaultAzureCredential(),
            scope=os.environ.get("FARSIGHT_API_SCOPE", "api://farsight/.default"),
        )

    async def request(self, method: str, path: str, json: dict | None = None) -> dict:
        # TODO: Enable retries, timeouts, correlation headers, and AGT audit propagation.
        headers = {"Authorization": f"Bearer {self.auth.bearer_token()}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            response = await client.request(method, path, json=json, headers=headers)
            response.raise_for_status()
            return response.json()
