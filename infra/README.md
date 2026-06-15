# FarSight Azure deployment

This folder contains the AZD/Bicep deployment scaffold for the Agent-Azure-FarSight cloud control plane.

For a production-style private deployment, start with the [greenfield Azure deployment guide](../docs/azure-greenfield-deployment.md).

## What it deploys

- Italy North collector/control-plane resources:
  - Azure Container Apps environment and app placeholders for API, admin web, worker, and AGT tool gateway.
  - Azure Container Registry.
  - Service Bus Standard namespace with session-enabled `jobs` queue.
  - Cosmos DB for NoSQL database and state containers.
  - Storage account and private artifacts container with lifecycle deletion.
  - Log Analytics and workspace-based Application Insights.
  - Key Vault and App Configuration.
  - Optional API Management placeholder.
  - A shared Log Analytics and workspace-based Application Insights instance for app telemetry.

## Prerequisites

- Azure CLI and Azure Developer CLI installed.
- `azd auth login` completed.
- Subscription access to deploy Container Apps, Cosmos DB, Service Bus, Storage, Key Vault, App Configuration, and monitoring resources.
- Region availability confirmed for the collector/control-plane location.

## Configure and preview

```bash
azd auth login
azd env new dev
azd env set AZURE_LOCATION italynorth
azd env set AZURE_COLLECTOR_LOCATION italynorth
azd env set FARSIGHT_ENABLE_PUBLIC_INGRESS true
azd env set FARSIGHT_ENABLE_PRIVATE_ENDPOINTS true
azd env set FARSIGHT_ENABLE_NAT_GATEWAY false
azd env set FARSIGHT_ENABLE_APIM false
azd provision --preview
```

`azure.yaml` runs `scripts/register-resource-providers.sh` before provisioning. The hook registers missing Azure resource providers such as `Microsoft.App`, `Microsoft.ContainerRegistry`, `Microsoft.ServiceBus`, and `Microsoft.DocumentDB` in the selected subscription.

`FARSIGHT_ENABLE_PRIVATE_ENDPOINTS` and `FARSIGHT_ENABLE_PUBLIC_INGRESS` are independent:

- `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS=true` keeps Azure dependencies on private endpoints with public network access disabled where supported.
- `FARSIGHT_ENABLE_PUBLIC_INGRESS=true` exposes the FarSight API, admin web, and AGT tool gateway over public Container Apps ingress.
- `FARSIGHT_ENABLE_PUBLIC_INGRESS=false` makes the Container Apps environment internal-only for hybrid/private access paths.

Container Apps environment network mode is treated as creation-time behavior. Bicep includes `pub` or `int` in the Container Apps environment and app names so changing public ingress creates a compatible replacement set instead of mutating an internal environment. The final topology uses one Container Apps delegated subnet; when switching modes, delete the old Container Apps environment and wait for Azure to release the subnet before reprovisioning.

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

The Bicep deployment outputs `AZURE_CONTAINER_REGISTRY_ENDPOINT` from the provisioned Azure Container Registry. AZD uses this output during publish/deploy to determine where service images must be pushed.

Private ACR deployments keep `FARSIGHT_ENABLE_ACR_TASK_NETWORK_BYPASS=true` by default. This uses selected-networks mode: the ACR public endpoint stays enabled, the firewall default action is `Deny`, ACR trusted-service plus Tasks network bypass are enabled, and the configured regional Azure Container Registry build CIDRs are allowed so AZD remote Docker builds can log in and push images. The observed dev defaults are `FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_ITALY_NORTH=4.232.51.192/26` and `FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_SWEDEN_CENTRAL=172.160.222.128/26`; update them from the current Azure service tag data for other regions or after service tag changes. Set the bypass to `false` only when builds run from a private-network runner or local Docker/Podman environment that can resolve and reach the registry private endpoint.

Container Apps pull private images from ACR with their user-assigned managed identities. Bicep configures each AZD-managed Container App with a registry entry that references the provisioned ACR login server and assigns `AcrPull` to the app identity before revision updates.

Bicep sets `AZURE_CLIENT_ID` for Container Apps that use Azure SDKs so `DefaultAzureCredential` selects the user-assigned identity. The admin BFF gets `FARSIGHT_CONTROL_API_BASE_URL` set to the API Container App endpoint for policy proxy calls.

Set `FARSIGHT_API_INTERNAL_AUTH_SECRET` to a strong random value before enabling admin policy mutations. Bicep stores it as a Container Apps secret for both API and admin web. The BFF uses it to sign Easy Auth admin context for policy save, activate, and delete requests.

Each service folder includes a `.dockerignore` file so remote builds do not upload local build artifacts such as `node_modules`, `dist`, Python caches, or local environment files.

The API, admin web, and AGT tool gateway containers listen on port `8000`, and the Container Apps ingress `targetPort` values must match. API and AGT tool gateway apps use `minReplicas=0`, so seeing zero replicas while idle is expected; `ActivationFailed` indicates a real container startup or ingress configuration issue. The admin BFF SPA fallback must use `response_model=None` because it may return either static files or a JSON placeholder.

## Admin app registration and Easy Auth

The admin web app can use Container Apps Easy Auth with Microsoft Entra ID. The Entra app registration is not created by Bicep, and `scripts/provision-admin-app-registration.py` is intentionally run as a standalone administrator step rather than an AZD hook.

Easy Auth is only configured when `FARSIGHT_ENABLE_ADMIN_EASY_AUTH=true` and the client ID, client secret, auth encryption secret, and issuer are all set. Token store is disabled by default; set `FARSIGHT_ADMIN_AUTH_TOKEN_STORE_SAS_URL_SETTING_NAME` only when a valid Blob SAS URL setting has been configured.

The Easy Auth Entra client secret is attached to the admin web Container App as `microsoft-provider-authentication-secret`. A separate `farsight-admin-auth-encryption-secret` value is used for Container Apps auth encryption and must be a base64-encoded 32-byte value. The app-registration script emits both values.

If the final Container App URL is not known yet, provision once with Easy Auth disabled, capture the admin URL or configure a custom domain, run the app-registration script with the Easy Auth callback URI, store the emitted `FARSIGHT_ADMIN_AUTH_*` values in the AZD environment, then provision again with Easy Auth enabled. The full operator sequence is documented in `docs/deployment/azure-greenfield-deployment.md`.

## Notes

- Do not replace service images manually in Bicep for AZD-managed services. Keep the `azd-service-name` tags aligned with `azure.yaml`.
- Private endpoint and APIM support are parameterized but intentionally skeletal for early implementation.
- VNet child operations are serialized in the networking module: subnets are ordered before private DNS VNet links, and DNS links run one at a time. This avoids Microsoft.Network `AnotherOperationInProgress` conflicts when several operations update the same VNet.
- Service Bus uses Premium SKU when private endpoints are enabled because private endpoint connections are not supported on Standard namespaces.
- App Configuration local authentication is disabled. Do not seed key-values through ARM/Bicep local-auth mode; write settings through application code or pass-through identity-aware tooling after deployment.
- NAT Gateway is optional and disabled by default to avoid extra cost. The shared networking module does not associate NAT Gateway to Container Apps infrastructure subnets; use it only for supported non-Container-Apps subnets such as optional APIM. Use `infra-test/` NAT Gateway for Windows client lab outbound internet.
- Container App resource names use compact environment and region tokens to stay within the Azure Container Apps 32-character name limit.
- The main AZD/Bicep deployment does not deploy the Azure SRE Agent service or a separate SRE Agent regional VNet. Use the dedicated SRE Agent package under `src/sre-agent/agent` when deploying the SRE Agent resource.
