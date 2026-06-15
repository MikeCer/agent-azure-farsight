from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os

GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class AuthConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    tenant_id: str | None = None
    client_id: str | None = None


def _service_principal_env() -> tuple[str | None, str | None, str | None]:
    return (
        os.getenv("AZURE_TENANT_ID"),
        os.getenv("AZURE_CLIENT_ID"),
        os.getenv("AZURE_CLIENT_SECRET"),
    )


def build_token_provider(auth_mode: str = "auto") -> tuple[Callable[[], str], AuthSettings]:
    try:
        from azure.identity import ClientSecretCredential, DefaultAzureCredential
    except ImportError as exc:
        raise AuthConfigurationError(
            "Missing dependency azure-identity. Install the package before authenticating to Microsoft Graph."
        ) from exc

    tenant_id, client_id, client_secret = _service_principal_env()
    present = [bool(tenant_id), bool(client_id), bool(client_secret)]

    if auth_mode not in {"auto", "default", "client-secret"}:
        raise AuthConfigurationError(f"Unsupported auth mode: {auth_mode}")

    if auth_mode == "client-secret" or (auth_mode == "auto" and all(present)):
        if not all(present):
            raise AuthConfigurationError(
                "Client-secret authentication requires AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET."
            )
        credential = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
        settings = AuthSettings(mode="client-secret", tenant_id=tenant_id, client_id=client_id)
    elif auth_mode == "auto" and any(present):
        raise AuthConfigurationError(
            "Partial service-principal configuration detected. Set all of AZURE_TENANT_ID, "
            "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, or remove them to use DefaultAzureCredential."
        )
    else:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        settings = AuthSettings(mode="default")

    def get_token() -> str:
        return credential.get_token(GRAPH_SCOPE).token

    return get_token, settings

