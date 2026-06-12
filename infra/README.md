# FarSight Azure deployment

This folder contains the AZD/Bicep deployment scaffold for the Agent-Azure-FarSight cloud control plane.

For a production-style private deployment, start with the [greenfield Azure deployment guide](../docs/azure-greenfield-deployment.md).

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
azd env set FARSIGHT_ENABLE_NAT_GATEWAY false
azd env set FARSIGHT_AGENT_GATEWAY_ENABLE_NAT_GATEWAY false
azd env set FARSIGHT_ENABLE_APIM false
azd provision --preview
```

## Deploy

```bash
azd up
```

## Container image handoff

AZD handles application container image build, push, and Container Apps updates for the declared services:

- `api`
- `admin-web`
- `agent-tools`

`azure.yaml` marks these services as `host: containerapp` and enables remote Docker builds. During `azd deploy`, AZD builds each image, pushes it to the provisioned Azure Container Registry, and updates the Container App that carries the matching `azd-service-name` tag.

The Bicep templates keep safe placeholder images so first provisioning can succeed before any service images exist. The `worker` container is also a placeholder until a worker implementation is added to `azure.yaml`.

## Notes

- Do not replace service images manually in Bicep for AZD-managed services. Keep the `azd-service-name` tags aligned with `azure.yaml`.
- Private endpoint and APIM support are parameterized but intentionally skeletal for early implementation.
- Service Bus uses Premium SKU when private endpoints are enabled because private endpoint connections are not supported on Standard namespaces.
- App Configuration local authentication is disabled. Do not seed key-values through ARM/Bicep local-auth mode; write settings through application code or pass-through identity-aware tooling after deployment.
- NAT Gateway is optional and disabled by default to avoid extra cost. The shared networking module does not associate NAT Gateway to Container Apps infrastructure subnets; use it only for supported non-Container-Apps subnets such as optional APIM. Use `infra-test/` NAT Gateway for Windows client lab outbound internet.
- When both regional modules deploy in the same resource group, the agent gateway reuses the core module's private DNS zones by default to avoid duplicate private DNS zone resources.
- Container App resource names use compact environment and region tokens to stay within the Azure Container Apps 32-character name limit.
- Azure SRE Agent service deployment is documented as an integration step until the service-specific Bicep/ARM contract is confirmed.
