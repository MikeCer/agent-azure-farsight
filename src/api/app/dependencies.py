from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from azure.identity import DefaultAzureCredential


@dataclass(frozen=True)
class AzureClients:
    """Managed-identity backed Azure client holder."""
    credential: DefaultAzureCredential


def get_azure_clients() -> AzureClients:
    return AzureClients(credential=DefaultAzureCredential())


# ---------------------------------------------------------------------------
# Cosmos DB container clients
# ---------------------------------------------------------------------------

_cosmos_client: Any | None = None


def _cosmos_container(container_name: str) -> Any | None:
    """Return a Cosmos DB ContainerProxy for the given container name.

    Returns None when FARSIGHT_COSMOS_ENDPOINT is not configured so all
    callers can transparently fall back to in-memory state for local dev.
    """
    global _cosmos_client
    endpoint = os.getenv("FARSIGHT_COSMOS_ENDPOINT", "").strip()
    if not endpoint:
        return None
    if _cosmos_client is None:
        from azure.cosmos import CosmosClient
        _cosmos_client = CosmosClient(endpoint, credential=DefaultAzureCredential())
    db_name = os.getenv("FARSIGHT_COSMOS_DATABASE", "farsight")
    return _cosmos_client.get_database_client(db_name).get_container_client(container_name)


def get_jobs_container() -> Any | None:
    return _cosmos_container(os.getenv("FARSIGHT_COSMOS_JOBS_CONTAINER", "jobs"))


def get_approvals_container() -> Any | None:
    return _cosmos_container(os.getenv("FARSIGHT_COSMOS_APPROVALS_CONTAINER", "approvals"))


def get_artifact_index_container() -> Any | None:
    return _cosmos_container(os.getenv("FARSIGHT_COSMOS_ARTIFACT_INDEX_CONTAINER", "artifactIndex"))


def get_audit_events_container() -> Any | None:
    return _cosmos_container(os.getenv("FARSIGHT_COSMOS_AUDIT_EVENTS_CONTAINER", "auditEvents"))


def get_investigations_container() -> Any | None:
    return _cosmos_container(os.getenv("FARSIGHT_COSMOS_INVESTIGATIONS_CONTAINER", "investigations"))


def get_devices_container() -> Any | None:
    return _cosmos_container(os.getenv("FARSIGHT_COSMOS_DEVICES_CONTAINER", "devices"))


# ---------------------------------------------------------------------------
# Blob Storage client (Phase 3)
# ---------------------------------------------------------------------------

_blob_service_client: Any | None = None


def get_blob_service_client() -> Any | None:
    """Return an azure-storage-blob BlobServiceClient.

    Returns None when FARSIGHT_BLOB_ACCOUNT_URL is not configured.
    """
    global _blob_service_client
    account_url = os.getenv("FARSIGHT_BLOB_ACCOUNT_URL", "").strip()
    if not account_url:
        return None
    if _blob_service_client is None:
        from azure.storage.blob import BlobServiceClient
        _blob_service_client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return _blob_service_client
