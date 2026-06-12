# Greenfield Azure deployment with private networking

This guide deploys Agent-Azure-FarSight into a new Azure environment using
AZD/Bicep, private endpoints, private DNS, and internal Container Apps ingress.
Use it for a production-style build in Italy North for the collector/control
plane and Sweden Central for the Azure SRE Agent/tool gateway.

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

Use Italy North (`italynorth`) for collector-facing resources and Sweden Central (`swedencentral`) for the SRE Agent/tool gateway. Confirm regional availability and quotas before reserving address space.

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

| Planning item | Italy North collector/control plane | Sweden Central SRE Agent/gateway | Decision/owner |
| --- | --- | --- | --- |
| Region code | `italynorth` | `swedencentral` | Platform owner |
| VNet name | `<env>-itn-vnet` | `<env>-sec-vnet` |  |
| VNet address space | Example: `10.42.0.0/16` | Example: `10.52.0.0/16` |  |
| Container Apps subnet | Example: `10.42.1.0/23` | Example: `10.52.1.0/23` | Delegate to `Microsoft.App/environments` |
| Private endpoint subnet | Example: `10.42.4.0/24` | Example: `10.52.4.0/24` | Disable PE network policies if required |
| Azure SRE Agent VNet | Peered or routed to Sweden Central | Primary SRE Agent VNet | Network owner |
| Hub/firewall route table | Route to private endpoints and ACA | Route to FarSight API and monitor endpoints | Network owner |
| DNS resolver | Azure DNS, Private Resolver, or custom DNS | Same resolver path | DNS owner |
| New private DNS zones? | Yes/no per zone | Yes/no per zone | DNS owner |
| Existing private DNS zone IDs | Record resource IDs | Record resource IDs | DNS owner |
| VNet links to private zones | Italy VNet, hub, resolver spokes | Sweden VNet, hub, resolver spokes | DNS owner |
| Cross-region routing | Italy <-> Sweden peering, hub, or VPN | Sweden <-> Italy peering, hub, or VPN | Network owner |
| Endpoint client path | Corporate VPN, ExpressRoute, proxy, or other private path | N/A | Endpoint/Intune owner |

Design notes:

- Keep Container Apps subnets separate from private endpoint subnets.
- Do not deploy private endpoints into delegated Container Apps subnets.
- Do not associate NAT Gateway directly to Container Apps infrastructure subnets. Use supported Container Apps egress controls or network routing patterns for production egress design, and use `infra-test/` NAT Gateway for Windows client lab outbound internet.
- Link private DNS zones to every VNet that must resolve FarSight resources,
  including hub resolver VNets and the SRE Agent VNet.
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

For this topology, `{regionName}` is `italynorth` or `swedencentral`. The ACR
regional data zone may be populated through `privatelink.azurecr.io` depending on
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
| `FARSIGHT_ENABLE_PUBLIC_INGRESS` | `enablePublicIngress` | `false` makes Container Apps ingress internal-only for private deployments. |
| `FARSIGHT_COLLECTOR_VNET_ADDRESS_PREFIXES` | `collectorVnetAddressPrefixes` | Italy North VNet address space. |
| `FARSIGHT_COLLECTOR_CONTAINER_APPS_SUBNET_PREFIX` | `collectorContainerAppsSubnetPrefix` | Delegated subnet for Italy North Container Apps environment. |
| `FARSIGHT_COLLECTOR_PRIVATE_ENDPOINT_SUBNET_PREFIX` | `collectorPrivateEndpointSubnetPrefix` | Private endpoint subnet for Italy North dependencies. |
| `FARSIGHT_SRE_AGENT_VNET_ADDRESS_PREFIXES` | `sreAgentVnetAddressPrefixes` | Sweden Central SRE Agent/gateway VNet address space. |
| `FARSIGHT_SRE_AGENT_CONTAINER_APPS_SUBNET_PREFIX` | `sreAgentContainerAppsSubnetPrefix` | Delegated subnet for Sweden Central Container Apps environment. |
| `FARSIGHT_SRE_AGENT_PRIVATE_ENDPOINT_SUBNET_PREFIX` | `sreAgentPrivateEndpointSubnetPrefix` | Private endpoint subnet for SRE Agent/gateway dependencies. |
| `FARSIGHT_LINK_EXISTING_PRIVATE_DNS_ZONES` | `linkExistingPrivateDnsZones` | Links central zones instead of creating duplicate zones. |
| `FARSIGHT_EXISTING_PRIVATE_DNS_ZONE_IDS` | `existingPrivateDnsZoneIds` | Resource IDs for central private DNS zones. |

If the preview reports unused variables, keep them in the worksheet and finish the
matching Bicep parameter work before production. Do not compensate by leaving
public network access enabled in a private deployment.

## 5. Preview and deploy

### Preview

Run the AZD provision preview and review the result before approving deployment. Review these items:

- Resource groups and locations match Italy North and Sweden Central.
- Container Apps environments use the planned subnets.
- Container Apps ingress is internal when `enablePublicIngress` is `false`.
- Private endpoints are created for Storage Blob, Key Vault, ACR, Cosmos DB,
  Service Bus, App Configuration, APIM if enabled, Monitor/Log Analytics, and
  Container Apps managed environments.
- Private DNS zone groups use existing zone IDs when
  `linkExistingPrivateDnsZones` is `true`.
- Public network access is not disabled until the corresponding private endpoint
  and DNS record exist.
- Managed identities and RBAC assignments are scoped to the least privilege
  needed by the API, worker, admin web, and tool gateway.

### Deploy

Deploy through the approved AZD/release process. If your release process separates infrastructure from images, provision infrastructure first, then deploy signed images through the approved pipeline.

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
- The SRE Agent/tool gateway in Sweden Central should reach the FarSight control
  plane over private routing, not public ingress.

## 7. Deploy the SRE Agent package

Deploy the SRE Agent after the FarSight control plane, private DNS, and routing
are validated. The package is under `src/sre-agent/agent` and has its own
AZD template and post-deploy content upload.

Use the dedicated AZD template under `src/sre-agent/agent` for the SRE Agent package. Configure its environment for Sweden Central and the selected Intune diagnostics authentication mode before deployment.

Deployment notes:

- Keep SRE Agent resources in or routed to the Sweden Central VNet from the
  worksheet.
- Link the SRE Agent VNet to the same private DNS zones needed to resolve the
  FarSight API, tool gateway, Key Vault, and monitoring endpoints.
- If `INTUNE_DIAGNOSTICS_AUTH_MODE=key-vault`, add the required Intune secrets to
  the SRE Agent Key Vault after provisioning and verify `Key Vault Secrets User`
  for the SRE Agent identity.
- Use `python3 deploy.py --dry-run` for content-only validation before uploading
  tools, skills, and knowledge files to an existing SRE Agent resource.
- Verify the deployed tools call internal FarSight endpoints and do not require
  public API ingress.

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
