# FarSight Azure deployment

This folder contains the AZD/Bicep deployment scaffold for the Agent-Azure-FarSight cloud control plane.

## What it deploys

- Italy North collector/control-plane resources:
  - Azure Container Apps environment and app placeholders for API, admin web, and worker.
  - Azure Container Registry.
  - Service Bus Standard namespace with session-enabled `jobs` queue.
  - Cosmos DB for NoSQL database and state containers.
  - Storage account and private artifacts container with lifecycle deletion.
  - Log Analytics and workspace-based Application Insights.
  - Key Vault and App Configuration.
  - Optional API Management placeholder.
- Sweden Central agent-tool gateway resources:
  - Container Apps environment and AGT tool gateway placeholder app.
  - Log Analytics and Application Insights for gateway telemetry.

## Prerequisites

- Azure CLI and Azure Developer CLI installed.
- `azd auth login` completed.
- Subscription access to deploy Container Apps, Cosmos DB, Service Bus, Storage, Key Vault, App Configuration, and monitoring resources.
- Region availability confirmed for Italy North and Sweden Central.

## Configure and preview

```bash
azd auth login
azd env new dev
azd env set AZURE_LOCATION italynorth
azd env set AZURE_COLLECTOR_LOCATION italynorth
azd env set AZURE_AGENT_LOCATION swedencentral
azd env set FARSIGHT_ENABLE_PUBLIC_INGRESS true
azd env set FARSIGHT_ENABLE_PRIVATE_ENDPOINTS false
azd env set FARSIGHT_ENABLE_APIM false
azd provision --preview
```

## Deploy

```bash
azd up
```

## Notes

- Container image references currently use safe placeholder images. Replace them with built application images when the service deployment pipeline is finalized.
- Private endpoint and APIM support are parameterized but intentionally skeletal for early implementation.
- Azure SRE Agent service deployment is documented as an integration step until the service-specific Bicep/ARM contract is confirmed.
