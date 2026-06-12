from dataclasses import dataclass

from azure.identity import DefaultAzureCredential


@dataclass(frozen=True)
class AzureClients:
    """Managed-identity backed Azure client holder.

    TODO: Initialize Cosmos DB, Service Bus, Blob Storage, App Configuration,
    Key Vault, and Logs Ingestion clients with DefaultAzureCredential.
    """

    credential: DefaultAzureCredential


def get_azure_clients() -> AzureClients:
    return AzureClients(credential=DefaultAzureCredential())
