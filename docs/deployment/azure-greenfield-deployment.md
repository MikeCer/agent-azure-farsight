# Greenfield Azure deployment with private networking

This guide deploys Agent-Azure-FarSight into a new Azure environment using
AZD/Bicep, private endpoints, private DNS, and internal Container Apps ingress.
Use it for a production-style FarSight control-plane build in Italy North. The
Azure SRE Agent resource is deployed separately with its own package and can use
Sweden Central when required by service availability.

> Current state: the repository is still early implementation. The AZD scaffold
> already exposes `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS` and
> `FARSIGHT_ENABLE_PUBLIC_INGRESS`; confirm the active branch also wires the VNet,
> subnet, and DNS parameters below before disabling public access in production.

## 1. Prerequisites

### Tools

Install and authenticate these tools from a privileged administration workstation
or deployment runner:

- Git.
- Azure CLI (`az`) with the `containerapp` extension available.
- Azure Developer CLI (`azd`).
- Bicep CLI, either standalone or through Azure CLI.
- PowerShell 7 for collector and Intune packaging validation.
- Python 3.12+ and Node.js 20+ if you will also build service images locally.

Confirm the tools are installed and current before deployment. Keep exact command examples in operational runbooks or CI scripts rather than duplicating them here.

### Azure login and subscription context

Authenticate Azure CLI and Azure Developer CLI to the same tenant/subscription and create the target AZD environment. Use separate environment names for shared production, test, and SRE Agent packages.

### Resource providers

Register required Azure resource providers before previewing the deployment. Provider registration can take several minutes; confirm each provider reaches the registered state before continuing.

### Permissions

The deploying identity needs, at minimum:

- Contributor on the target subscription or resource groups.
- Network Contributor on VNets, subnets, private endpoints, private DNS zones,
  and VNet links when networking is owned by another team.
- Private DNS Zone Contributor on existing private DNS zones.
- User Access Administrator or Owner for managed identity RBAC assignments.
- Key Vault Administrator or equivalent for initial vault access policy/RBAC
  bootstrap.
- API Management Service Contributor if APIM is enabled.
- Azure SRE Agent deployment permissions, including the SRE Agent Administrator
  assignment described in `src/sre-agent/README.md`.
- Intune administrator permissions for collector packaging, assignment rings,
  remediation scripts, and certificate deployment after the cloud deployment.

### Region and quota checks

Use Italy North (`italynorth`) for the FarSight collector/control-plane resources created by this AZD template. Confirm regional availability and quotas before reserving address space. Sweden Central (`swedencentral`) applies to the separate Azure SRE Agent package, not to the main FarSight Container Apps deployment.

Also check subscription quotas and policy for:

- Private endpoints and NICs per VNet/subscription.
- Container Apps managed environments and cores.
- Premium ACR if private endpoints are enabled for registry access.
- Premium Service Bus when private endpoints are enabled.
- Cosmos DB throughput/account limits.
- Service Bus namespaces and queue limits.
- Log Analytics ingestion, retention, and daily caps.
- API Management SKU capacity if APIM is enabled.

## 2. DNS and VNet planning worksheet

Complete this worksheet before running `azd provision --preview`. Do not overlap
with hub, on-premises, VPN, ExpressRoute, or endpoint client ranges.

| Planning item | Italy North FarSight control plane | Separate Azure SRE Agent package, if used | Decision/owner |
| --- | --- | --- | --- |
| Region code | `italynorth` | `swedencentral`, if required | Platform owner |
| VNet name | `<env>-itn-vnet` | SRE Agent package VNet, if deployed |  |
| VNet address space | Example: `10.42.0.0/16` | Example: `10.52.0.0/16`, if deployed |  |
| Container Apps subnet | Example: `10.42.1.0/23` | N/A for this main template | Delegate FarSight subnet to `Microsoft.App/environments` |
| Private endpoint subnet | Example: `10.42.4.0/24` | SRE Agent package subnet, if deployed | Disable PE network policies if required |
| Azure SRE Agent VNet | N/A for this main template | Primary SRE Agent VNet, if deployed | Network owner |
| Hub/firewall route table | Route to FarSight private endpoints and Container Apps | Route from SRE Agent to FarSight endpoints, if needed | Network owner |
| DNS resolver | Azure DNS, Private Resolver, or custom DNS | Same resolver path | DNS owner |
| New private DNS zones? | Yes/no per zone | Yes/no per zone | DNS owner |
| Existing private DNS zone IDs | Record resource IDs | Record resource IDs | DNS owner |
| VNet links to private zones | Italy VNet, hub, resolver spokes | SRE Agent VNet only if it must resolve FarSight private endpoints | DNS owner |
| Cross-region routing | Not required by this main template | Required only if the SRE Agent package uses private FarSight endpoints from another region | Network owner |
| Endpoint client path | Corporate VPN, ExpressRoute, proxy, or other private path | N/A | Endpoint/Intune owner |

Design notes:

- Keep Container Apps subnets separate from private endpoint subnets.
- Do not deploy private endpoints into delegated Container Apps subnets.
- Do not associate NAT Gateway directly to Container Apps infrastructure subnets. Use supported Container Apps egress controls or network routing patterns for production egress design, and use `infra-test/` NAT Gateway for Windows client lab outbound internet.
- Link private DNS zones to every VNet that must resolve FarSight resources,
  including hub resolver VNets. Link an SRE Agent VNet only after private routing
  to the FarSight control-plane VNet exists.
- If endpoint collectors must call an internal API, ensure Windows clients have a
  private route and DNS path through VPN, ExpressRoute, or a managed proxy.
- Decide whether the deployment creates new private DNS zones or links to
  centrally owned zones. Existing zones are preferred in hub-and-spoke networks.

## 3. Required private DNS zones

Create or link the following commercial Azure private DNS zones. Use the official
recommended zone names so Azure private endpoint zone groups can populate A
records automatically.

| FarSight dependency | Private DNS zone |
| --- | --- |
| Storage Blob artifacts | `privatelink.blob.core.windows.net` |
| Key Vault | `privatelink.vaultcore.azure.net` |
| Azure Container Registry | `privatelink.azurecr.io` |
| ACR regional data endpoint | `{regionName}.data.privatelink.azurecr.io` |
| Cosmos DB for NoSQL | `privatelink.documents.azure.com` |
| Service Bus | `privatelink.servicebus.windows.net` |
| App Configuration | `privatelink.azconfig.io` |
| API Management gateway, if enabled | `privatelink.azure-api.net` |
| Azure Monitor private link scope | `privatelink.monitor.azure.com` |
| Log Analytics query | `privatelink.oms.opinsights.azure.com` |
| Log Analytics ingestion | `privatelink.ods.opinsights.azure.com` |
| Azure Monitor agent service | `privatelink.agentsvc.azure-automation.net` |
| Azure Monitor blob dependency | `privatelink.blob.core.windows.net` |
| Container Apps managed environment | `privatelink.{regionName}.azurecontainerapps.io` |

For this topology, `{regionName}` is normally `italynorth` for the main FarSight
deployment. The ACR regional data zone may be populated through `privatelink.azurecr.io` depending on
registry settings; validate generated records during the preview. For Azure
Monitor, deploy an Azure Monitor Private Link Scope (AMPLS) and associate the Log
Analytics workspace and Application Insights component so ingestion and query
traffic both use private link.

## 4. Configure AZD private-mode variables

Set AZD environment values before previewing. Keep the exact values in the deployment environment record or release checklist rather than in this guide.

Expected Bicep parameter mapping:

| AZD variable | Bicep parameter | Purpose |
| --- | --- | --- |
| `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS` | `enablePrivateEndpoints` | Creates private endpoint-capable topology and disables public network access after endpoints and DNS are ready. |
| `FARSIGHT_ENABLE_ACR_TASK_NETWORK_BYPASS` | `enableAcrTaskNetworkBypass` | Keeps ACR in selected-networks/default-deny mode and allows ACR Tasks/trusted Azure services to bypass ACR network rules so AZD remote Docker builds can push images. |
| `FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_ITALY_NORTH` | `acrFirewallAllowedIpRanges[0]` | Allows the Italy North Azure Container Registry build IP range through the ACR firewall for AZD remote builds. Default: `4.232.51.192/26`. |
| `FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_SWEDEN_CENTRAL` | `acrFirewallAllowedIpRanges[1]` | Allows the Sweden Central Azure Container Registry build IP range through the ACR firewall for AZD remote builds. Default: `172.160.222.128/26`. |
| `FARSIGHT_ENABLE_PUBLIC_INGRESS` | `enablePublicIngress` | `true` exposes solution endpoints over public Container Apps ingress. `false` makes Container Apps ingress internal-only. Private endpoints for Azure dependencies are controlled separately by `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS`. |
| `FARSIGHT_VNET_ADDRESS_PREFIX` | `vnetAddressPrefix` | FarSight control-plane VNet address space. |
| `FARSIGHT_CONTAINER_APPS_INFRASTRUCTURE_SUBNET_PREFIX` | `containerAppsInfrastructureSubnetPrefix` | Single delegated subnet for the active FarSight Container Apps environment. Default: `10.10.0.0/23`. |
| `FARSIGHT_PRIVATE_ENDPOINT_SUBNET_PREFIX` | `privateEndpointSubnetPrefix` | Private endpoint subnet for FarSight dependencies. |
| `FARSIGHT_LINK_EXISTING_PRIVATE_DNS_ZONES` | `linkExistingPrivateDnsZones` | Links central zones instead of creating duplicate zones. |
| `FARSIGHT_EXISTING_PRIVATE_DNS_ZONE_IDS` | `existingPrivateDnsZoneIds` | Resource IDs for central private DNS zones. |

### Admin Easy Auth app registration

The admin web app uses Container Apps Easy Auth when enabled. The Entra app registration is not created by Bicep and `scripts/provision-admin-app-registration.py` is intentionally not wired as an AZD hook. Run the script manually after the admin web URL or production custom domain is known, then let AZD pass the resulting values into Bicep on the next provision.

Use this flow for greenfield deployments without a pre-existing custom domain:

1. Keep `FARSIGHT_ENABLE_ADMIN_EASY_AUTH=false` for the first provision/deploy so the admin Container App can be created without auth metadata.
2. Run the initial AZD deployment flow far enough to obtain the admin web host name.
3. Build the Easy Auth redirect URI as `https://<admin-web-host>/.auth/login/aad/callback`, or use the same path under the approved custom domain.
4. Run `scripts/provision-admin-app-registration.py` manually with that redirect URI. Use `--create-secret` when the script must create the Container Apps Easy Auth client secret.
5. Store the emitted `FARSIGHT_ADMIN_AUTH_CLIENT_ID`, `FARSIGHT_ADMIN_AUTH_CLIENT_SECRET`, `FARSIGHT_ADMIN_AUTH_ENCRYPTION_SECRET`, `FARSIGHT_ADMIN_AUTH_ISSUER`, and `FARSIGHT_ADMIN_AUTH_ALLOWED_AUDIENCE` values in the AZD environment.
6. Set `FARSIGHT_ENABLE_ADMIN_EASY_AUTH=true`.
7. Re-run the AZD provision or full deployment flow so Bicep creates the Container Apps Easy Auth configuration.

Easy Auth is skipped unless the enable flag, client ID, client secret, auth encryption secret, and issuer are all populated. The auth token store is disabled by default to avoid requiring a Blob SAS URL setting; enable it only after providing a valid token-store SAS URL setting name.

The Easy Auth Entra client secret is stored as `microsoft-provider-authentication-secret` in the admin web Container App configuration. Container Apps Easy Auth also requires a separate encryption secret, stored as `farsight-admin-auth-encryption-secret`; its value must be a base64 string converted from 32 random bytes. The app-registration script emits this value as `FARSIGHT_ADMIN_AUTH_ENCRYPTION_SECRET`.

For production, prefer a stable custom domain before registering redirect URIs. If the admin host name changes after app registration, update the Entra app redirect URI with the script and reprovision the auth configuration.

If the preview reports unused variables, keep them in the worksheet and finish the
matching Bicep parameter work before production. Do not compensate by leaving
public network access enabled in a private deployment.

### Public solution ingress with private Azure dependencies

`FARSIGHT_ENABLE_PRIVATE_ENDPOINTS` and `FARSIGHT_ENABLE_PUBLIC_INGRESS` are intentionally independent.

- Set `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS=true` to keep Azure dependencies such as Storage, Key Vault, ACR, Cosmos DB, Service Bus, App Configuration, and monitoring on private endpoints with public network access disabled where supported.
- Set `FARSIGHT_ENABLE_PUBLIC_INGRESS=true` when the FarSight API, admin web, and AGT tool gateway must be reachable from the internet for dev/test or for an enterprise pattern that later fronts those endpoints with another access layer.
- Set `FARSIGHT_ENABLE_PUBLIC_INGRESS=false` when clients and operators reach FarSight through VPN, ExpressRoute, peering, private DNS, private resolver, jumpbox, or another approved private path.

With both `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS=true` and `FARSIGHT_ENABLE_PUBLIC_INGRESS=true`, the Container Apps environment is VNet-integrated but not internal-only. The app endpoints are public, while their data-plane dependencies still use private endpoints and managed identities.

Container Apps managed environment internal/public mode is effectively a creation-time network decision. The Bicep names the Container Apps environment and apps with an ingress-mode token (`pub` or `int`) so switching modes creates a fresh compatible environment instead of trying to mutate an existing internal environment. The final topology still uses one Container Apps delegated subnet. Before switching modes in an existing environment, delete the old Container Apps environment and wait until Azure releases the delegated subnet; otherwise the new environment fails with `ManagedEnvironmentSubnetInUse`.

### Provider registration preprovision hook

`azure.yaml` runs `scripts/register-resource-providers.sh` as a `preprovision` hook. The script checks required Azure resource providers in the selected subscription and registers missing providers before Bicep starts. This prevents failures such as an unregistered `Microsoft.App` provider during Container Apps deployment.

## 5. Preview and deploy

### Preview

Run the AZD provision preview and review the result before approving deployment. Review these items:

- Resource group and location match the FarSight control-plane region.
- Container Apps environments use the planned subnets when private endpoints are enabled.
- Container Apps ingress is public when `enablePublicIngress` is `true`, and internal-only when `enablePublicIngress` is `false`.
- Container Apps resource names include `pub` or `int` to reflect ingress mode. Confirm AZD-managed services are tagged on the active mode's app resources, and remove old mode resources before reprovisioning with the opposite mode.
- Private endpoints are created for Storage Blob, Key Vault, ACR, Cosmos DB,
  Service Bus, App Configuration, APIM if enabled, Monitor/Log Analytics, and
  Container Apps managed environments.
- Private DNS zone groups use existing zone IDs when
  `linkExistingPrivateDnsZones` is `true`.
- VNet child operations are intentionally ordered: subnets are created first, then private DNS VNet links are created serially for each VNet. This avoids `AnotherOperationInProgress` errors from Microsoft.Network when subnet updates and DNS zone links target the same VNet at once.
- Public network access is not disabled until the corresponding private endpoint
  and DNS record exist.
- Managed identities and RBAC assignments are scoped to the least privilege
  needed by the API, worker, admin web, and AGT tool gateway.

### Deploy

Deploy through the approved AZD/release process. If your release process separates infrastructure from images, provision infrastructure first, then deploy signed images through the approved pipeline.

AZD builds and publishes the `api`, `admin-web`, and `agent-tools` container images during the deploy phase. The infrastructure outputs the provisioned container registry endpoint and tags each Container App with `azd-service-name` so AZD can push images and update the correct app. Service folders include `.dockerignore` files to keep remote build archives small.

When private endpoints are enabled, the registry is network-restricted. Keep `FARSIGHT_ENABLE_ACR_TASK_NETWORK_BYPASS=true` when using AZD remote Docker builds. In that mode, Bicep keeps the ACR public endpoint enabled but sets the firewall default action to `Deny`, enables ACR Tasks/trusted-service bypass, and allows the configured regional Azure Container Registry build CIDR range. This is selected-networks mode, not open public access.

The dev defaults `FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_ITALY_NORTH=4.232.51.192/26` and `FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_SWEDEN_CENTRAL=172.160.222.128/26` come from the current `AzureContainerRegistry.ItalyNorth` and `AzureContainerRegistry.SwedenCentral` service tags observed during AZD remote builds. For other regions, or as Azure service tags change, update these values from the published Azure IP ranges before deployment. Fully disabling the registry public endpoint or omitting the active regional build range prevents the remote builder from logging in because its Microsoft-managed public IP is outside the private VNet. If security policy disallows this public firewall exception, use a self-hosted runner or local Docker/Podman environment with private DNS and network reachability to the registry instead of AZD remote build. For an existing failed deployment, reprovision after changing this setting before retrying `azd up`.

Container Apps use managed identity to pull private images from the provisioned ACR. Before AZD updates revisions to the published images, Bicep must apply the Container App `registries` configuration and `AcrPull` role assignments for the app identities. If a deployment fails with `UNAUTHORIZED: authentication required` while pulling an `acrfarsight...azurecr.io/...` image, reprovision to apply the registry identity and RBAC configuration, then retry the deploy phase.

Container Apps use a user-assigned managed identity for Azure SDK access. Bicep sets `AZURE_CLIENT_ID` in the app containers so `DefaultAzureCredential` selects the assigned identity consistently. The admin BFF also receives `FARSIGHT_CONTROL_API_BASE_URL` pointing to the API Container App endpoint so policy proxy calls do not fall back to localhost.

Set `FARSIGHT_API_INTERNAL_AUTH_SECRET` to a strong random value before using admin policy mutation workflows. The admin BFF signs Easy Auth admin context with this secret for policy save, activate, and delete calls, and the API verifies the signature and short expiry before accepting the mutation.

The API, admin web, and AGT tool gateway containers listen on port `8000`; their Container Apps ingress `targetPort` must stay aligned with the Dockerfile startup commands. API and AGT tool gateway revisions can show zero replicas when idle because their minimum replica count is `0`; this is expected scale-to-zero behavior. Treat `ActivationFailed` or repeated container exit events as deployment issues. For the admin BFF, ensure the SPA fallback route disables FastAPI response-model generation when returning either `FileResponse` or a JSON placeholder.

## 6. Post-deployment private endpoint and DNS checks

Run these checks from a VM, jumpbox, GitHub Actions runner, or Azure Container App job with line-of-sight to the private VNets.

### Private endpoint state

Review private endpoint resources and connection states. Use the target PaaS resource ID, not the private endpoint resource ID. Approve pending connections only after confirming the requester, resource ID, and subnet are expected.

### DNS records

Review A records in each required private DNS zone. From a private-network host, confirm the public service FQDNs resolve to private IPs.

Expected result: the queried public name follows a CNAME chain into the
`privatelink` zone and returns a private RFC1918 address.

### Ingress and data-plane smoke tests

- From outside the private network, FarSight API/admin ingress should fail when
  `FARSIGHT_ENABLE_PUBLIC_INGRESS=false`.
- From inside the private network, API health endpoints and admin web should
  resolve and respond over HTTPS.
- API/worker identities should reach Cosmos DB, Service Bus, Storage, Key Vault,
  App Configuration, ACR, and monitoring without public network access.
- Log Analytics and Application Insights telemetry should appear after AMPLS DNS
  and private link scope associations are configured.
- If a separate SRE Agent package is deployed in another region, it should reach
  the FarSight control plane over approved private routing or an explicitly
  approved public development endpoint.

## 7. Deploy the SRE Agent package

Deploy the SRE Agent after the FarSight control plane, private DNS, and routing
are validated. The package is under `src/sre-agent/agent` and has its own
AZD template and post-deploy content upload.

Use the dedicated AZD template under `src/sre-agent/agent` for the SRE Agent package. Configure its environment for Sweden Central and the selected Intune diagnostics authentication mode before deployment.

Deployment notes:

- Keep SRE Agent resources in the SRE Agent package environment, such as Sweden
  Central when required by service availability.
- Link the SRE Agent VNet to FarSight private DNS zones only when private routing
  to the FarSight VNet exists; otherwise the SRE Agent can resolve private IPs it
  cannot reach.
- If `INTUNE_DIAGNOSTICS_AUTH_MODE=key-vault`, add the required Intune secrets to
  the SRE Agent Key Vault after provisioning and verify `Key Vault Secrets User`
  for the SRE Agent identity.
- Use `python3 deploy.py --dry-run` for content-only validation before uploading
  tools, skills, and knowledge files to an existing SRE Agent resource.
- Verify the deployed SRE Agent tools call the FarSight AGT gateway/API endpoint
  through the approved network path.

## 8. Deploy the Intune collector after cloud setup

Deploy collectors only after the private API endpoint, certificate path, DNS, and
routing from managed Windows clients are proven.

1. Build or package the approved collector version from `src/collector`.
2. Configure the collector with the private FarSight API endpoint, tenant,
   certificate profile, module manifest, and polling schedule.
3. Publish the package through Intune to lab devices first.
4. Deploy remediation checks for collector installation, scheduled task health,
   certificate presence, manifest freshness, and API reachability.
5. Expand through IT pilot, limited production, and broad production rings.
6. Monitor job lease latency, API errors, collector errors, redaction events,
   upload failures, and artifact retention before each ring expansion.

If endpoint devices are not on the private network, provide a supported path such
as Always On VPN, ExpressRoute-connected corporate network, or an approved proxy.
Do not temporarily expose public ingress for broad collector rollout.

## 9. Troubleshooting

### DNS resolves to public IPs or NXDOMAIN

- Confirm the correct private DNS zone exists for the service.
- Confirm A records were created by the private endpoint zone group.
- Confirm every client VNet, hub resolver VNet, and SRE Agent VNet is linked.
- Check custom DNS forwarders. They must forward `privatelink` zones to Azure DNS
  or to Azure Private Resolver inbound endpoints.
- Avoid duplicate same-name private DNS zones split across resource groups unless
  the routing and VNet links are intentionally partitioned.

### Public access was disabled too early

- Re-enable public network access only from an approved break-glass change if the
  private endpoint or DNS path is not ready.
- Prefer fixing the missing private endpoint, zone group, VNet link, or route.
- Re-run smoke tests from inside the VNet before disabling public access again.

### Private endpoint connections are pending or rejected

- Check whether the target service requires manual approval.
- Validate requester subscription, resource group, endpoint name, and subnet.
- Confirm the endpoint subnet has enough IP addresses.
- Approve through the owning service team, then verify the connection state and
  DNS A record.

### Container Apps internal ingress is unreachable

- Confirm `enablePublicIngress=false` maps to internal ingress and the Container
  Apps environment is integrated with the planned subnet.
- Validate the `privatelink.{regionName}.azurecontainerapps.io` zone, wildcard or
  app records, and VNet links.
- Test from a host inside the VNet before testing from peered or on-premises
  networks.
- Check NSGs, UDRs, Azure Firewall, and hub routing for the Container Apps subnet
  and private endpoint subnet.

### Azure Monitor private link scope problems

- Confirm the Log Analytics workspace and Application Insights component are
  associated with the AMPLS resource.
- Create/link all Azure Monitor zones: `privatelink.monitor.azure.com`,
  `privatelink.oms.opinsights.azure.com`, `privatelink.ods.opinsights.azure.com`,
  `privatelink.agentsvc.azure-automation.net`, and the required blob zone.
- Verify ingestion and query DNS separately; one can work while the other fails.
- Check any firewall egress rules for Azure Monitor private endpoint IPs.

### Cross-region routing fails

- Confirm Italy North and Sweden Central VNets are peered or connected through the
  approved hub, and that both directions allow forwarded traffic when required.
- Validate route tables do not send private endpoint traffic to the internet.
- Confirm private DNS zones are linked to both regional VNets or a shared resolver
  path is in place.
- Test both directions: SRE Agent/gateway to FarSight API, and control plane to
  any required gateway or monitoring endpoint.
