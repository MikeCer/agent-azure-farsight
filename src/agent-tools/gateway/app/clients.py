import os
from dataclasses import dataclass

import httpx
from azure.identity import DefaultAzureCredential


def normalize_api_scope(scope: str, fallback_base_url: str) -> str:
    value = scope.strip()
    if value.startswith("api://") and not value.endswith("/.default"):
        return f"{value.rstrip('/')}/.default"
    if value:
        return value
    return f"{fallback_base_url}/.default"


@dataclass(frozen=True)
class ManagedIdentityAuth:
    """Managed identity authentication for FarSight API calls."""

    credential: DefaultAzureCredential
    scope: str

    def bearer_token(self) -> str:
        # TODO: Request a token for the FarSight API application ID URI/scope.
        token = self.credential.get_token(self.scope)
        return token.token


class FarSightApiClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get("FARSIGHT_API_BASE_URL", "").strip().rstrip("/")
        if not self.base_url:
            raise ValueError("FARSIGHT_API_BASE_URL is required for gateway API forwarding.")
        scope = normalize_api_scope(os.environ.get("FARSIGHT_API_SCOPE", ""), self.base_url)
        self.auth = ManagedIdentityAuth(
            credential=DefaultAzureCredential(),
            scope=scope,
        )

    async def request(self, method: str, path: str, json: dict | None = None, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.auth.bearer_token()}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            response = await client.request(method, path, json=json, params=params, headers=headers)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
