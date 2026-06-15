from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any
from urllib.parse import quote

from .auth import AuthConfigurationError, build_token_provider
from .collector import collect_device_diagnostics
from .config import DiagnosticConfig
from .graph_client import GraphClient, GraphError
from .models import DiagnosticDocument, Target, utc_now_iso
from .resolver import DeviceDisambiguation, DeviceResolutionError, resolve_device_by_name
from .rules import resolution_error_finding

DEFAULT_AUTH_MODE = "__INTUNE_DEFAULT_AUTH_MODE__"
DEFAULT_KEY_VAULT_URL = "__INTUNE_DEFAULT_KEY_VAULT_URL__"
DEFAULT_TENANT_ID_SECRET_NAME = "__INTUNE_DEFAULT_TENANT_ID_SECRET_NAME__"
DEFAULT_CLIENT_ID_SECRET_NAME = "__INTUNE_DEFAULT_CLIENT_ID_SECRET_NAME__"
DEFAULT_CLIENT_SECRET_SECRET_NAME = "__INTUNE_DEFAULT_CLIENT_SECRET_SECRET_NAME__"


def main(
    device_name: str,
    auth_mode: str = "auto",
    tenant_id: str | None = None,
    azure_tenant_id: str | None = None,
    azure_client_id: str | None = None,
    azure_client_secret: str | None = None,
    key_vault_url: str | None = None,
    tenant_id_secret_name: str | None = None,
    client_id_secret_name: str | None = None,
    client_secret_secret_name: str | None = None,
    managed_device_id: str | None = None,
    azure_ad_device_id: str | None = None,
    serial_number: str | None = None,
    include_pii: bool = False,
    include_beta_endpoint_analytics: bool = True,
    max_resolution_pages: int = DiagnosticConfig.max_resolution_pages,
    max_optional_pages: int = DiagnosticConfig.max_optional_pages,
) -> dict[str, Any]:
    """Collect read-only Intune diagnostics for one Windows client device."""
    config = DiagnosticConfig(
        include_beta_endpoint_analytics=include_beta_endpoint_analytics,
        include_pii=include_pii,
        max_resolution_pages=max_resolution_pages,
        max_optional_pages=max_optional_pages,
    )
    try:
        (
            auth_mode,
            key_vault_url,
            tenant_id_secret_name,
            client_id_secret_name,
            client_secret_secret_name,
        ) = _apply_deployment_defaults(
            auth_mode=auth_mode,
            key_vault_url=key_vault_url,
            tenant_id_secret_name=tenant_id_secret_name,
            client_id_secret_name=client_id_secret_name,
            client_secret_secret_name=client_secret_secret_name,
        )
        resolved_tenant_id, resolved_client_id, resolved_client_secret = _resolve_service_principal_values(
            azure_tenant_id=azure_tenant_id,
            azure_client_id=azure_client_id,
            azure_client_secret=azure_client_secret,
            key_vault_url=key_vault_url,
            tenant_id_secret_name=tenant_id_secret_name,
            client_id_secret_name=client_id_secret_name,
            client_secret_secret_name=client_secret_secret_name,
        )
        service_principal_env = _service_principal_env(resolved_tenant_id, resolved_client_id, resolved_client_secret)
        with _temporary_env(service_principal_env):
            token_provider, _ = build_token_provider(auth_mode)
            graph = GraphClient(token_provider)
            disambiguation = DeviceDisambiguation(managed_device_id, azure_ad_device_id, serial_number)
            device = resolve_device_by_name(graph, device_name, config, disambiguation=disambiguation)
            document = collect_device_diagnostics(
                graph,
                device,
                device_name,
                config,
                tenant_id=tenant_id or resolved_tenant_id,
            )
        return document.to_sre_dict()
    except DeviceResolutionError as exc:
        return _error_document(
            device_name,
            exc.kind,
            exc.message,
            exc.candidates,
            details={
                "http_status": exc.status_code,
                "graph_error_code": exc.error_code,
                "url": exc.url,
                "identity": exc.identity_context,
            },
        ).to_sre_dict()
    except (AuthConfigurationError, GraphError) as exc:
        details = {}
        if isinstance(exc, GraphError):
            details = {
                "http_status": exc.status_code,
                "graph_error_code": exc.error_code,
                "url": exc.url,
                "identity": exc.identity_context,
            }
        return _error_document(device_name, "collection_error", str(exc), details=details).to_sre_dict()


def _error_document(
    device_name: str,
    kind: str,
    message: str,
    candidates: list[dict[str, object]] | None = None,
    details: dict[str, object] | None = None,
) -> DiagnosticDocument:
    now = utc_now_iso()
    document = DiagnosticDocument(target=Target(input_device_name=device_name), started_at=now, completed_at=now)
    document.warnings.append(message)
    document.findings.append(resolution_error_finding(kind, message, candidates, details))
    return document


def _resolve_service_principal_values(
    azure_tenant_id: str | None,
    azure_client_id: str | None,
    azure_client_secret: str | None,
    key_vault_url: str | None,
    tenant_id_secret_name: str | None,
    client_id_secret_name: str | None,
    client_secret_secret_name: str | None,
) -> tuple[str | None, str | None, str | None]:
    direct_values = [azure_tenant_id, azure_client_id, azure_client_secret]
    key_vault_values = [key_vault_url, tenant_id_secret_name, client_id_secret_name, client_secret_secret_name]
    if all(direct_values):
        return azure_tenant_id, azure_client_id, azure_client_secret
    if any(direct_values):
        raise AuthConfigurationError(
            "Direct service-principal tool parameters require azure_tenant_id, azure_client_id, and azure_client_secret."
        )
    if not any(key_vault_values):
        return None, None, None
    if not all(key_vault_values):
        raise AuthConfigurationError(
            "Key Vault credential retrieval requires key_vault_url, tenant_id_secret_name, "
            "client_id_secret_name, and client_secret_secret_name."
        )

    assert key_vault_url is not None
    assert tenant_id_secret_name is not None
    assert client_id_secret_name is not None
    assert client_secret_secret_name is not None
    return (
        _get_key_vault_secret(key_vault_url, tenant_id_secret_name),
        _get_key_vault_secret(key_vault_url, client_id_secret_name),
        _get_key_vault_secret(key_vault_url, client_secret_secret_name),
    )


def _default_value(value: str) -> str | None:
    if not value or value.startswith("__INTUNE_DEFAULT_"):
        return None
    return value


def _apply_deployment_defaults(
    auth_mode: str,
    key_vault_url: str | None,
    tenant_id_secret_name: str | None,
    client_id_secret_name: str | None,
    client_secret_secret_name: str | None,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    default_auth_mode = _default_value(DEFAULT_AUTH_MODE)
    default_key_vault_url = _default_value(DEFAULT_KEY_VAULT_URL)
    if auth_mode == "auto" and default_auth_mode:
        auth_mode = default_auth_mode
    return (
        auth_mode,
        key_vault_url or default_key_vault_url,
        tenant_id_secret_name or _default_value(DEFAULT_TENANT_ID_SECRET_NAME),
        client_id_secret_name or _default_value(DEFAULT_CLIENT_ID_SECRET_NAME),
        client_secret_secret_name or _default_value(DEFAULT_CLIENT_SECRET_SECRET_NAME),
    )


def _get_key_vault_secret(key_vault_url: str, secret_name: str) -> str:
    try:
        import requests
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise AuthConfigurationError(
            "Key Vault credential retrieval requires azure-identity and requests in the Python tool runtime."
        ) from exc

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    token = credential.get_token("https://vault.azure.net/.default").token
    url = f"{key_vault_url.rstrip('/')}/secrets/{quote(secret_name, safe='')}?api-version=7.5"
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if response.status_code >= 400:
        raise AuthConfigurationError(
            f"Could not retrieve secret '{secret_name}' from Key Vault: HTTP {response.status_code}."
        )
    value = response.json().get("value")
    if not value:
        raise AuthConfigurationError(f"Secret '{secret_name}' in Key Vault has no value.")
    return str(value)


def _service_principal_env(
    azure_tenant_id: str | None,
    azure_client_id: str | None,
    azure_client_secret: str | None,
) -> dict[str, str]:
    values = {
        "AZURE_TENANT_ID": azure_tenant_id,
        "AZURE_CLIENT_ID": azure_client_id,
        "AZURE_CLIENT_SECRET": azure_client_secret,
    }
    if not any(values.values()):
        return {}
    if not all(values.values()):
        raise AuthConfigurationError(
            "Service-principal tool parameters require azure_tenant_id, azure_client_id, and azure_client_secret."
        )
    return {key: value for key, value in values.items() if value is not None}


@contextmanager
def _temporary_env(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
