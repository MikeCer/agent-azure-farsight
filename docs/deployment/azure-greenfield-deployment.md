# Greenfield Azure deployment runbook (step-by-step)

Use this runbook to deploy **Agent-Azure-FarSight** into a new Azure environment with AZD/Bicep.  
It is written as an operator sequence for difficult first-time deployments.

- Main FarSight control plane (this repo root): Italy North (`italynorth`)
- Azure SRE Agent package (separate template): typically Sweden Central (`swedencentral`)

> Current state: FarSight is still early implementation. Follow this document as the source of truth for deployment order, especially the manual Entra registration steps.

## 0. Decide topology before touching AZD

1. Choose ingress mode:
   - Public app ingress: `FARSIGHT_ENABLE_PUBLIC_INGRESS=true`
   - Internal-only app ingress: `FARSIGHT_ENABLE_PUBLIC_INGRESS=false`
2. Decide private dependencies:
   - Recommended production: `FARSIGHT_ENABLE_PRIVATE_ENDPOINTS=true`
3. Confirm DNS/routing owners:
   - Who owns private DNS zones
   - Who owns VNet links and route tables
4. Reserve non-overlapping address space for:
   - VNet
   - Container Apps infra subnet (delegated)
   - Private endpoint subnet

## 1. Prerequisites and permissions

Required tools:

- `git`
- `az` (Azure CLI)
- `azd` (Azure Developer CLI)
- Python 3.12+
- PowerShell 7 (collector/Intune workflows)

Required permissions for deploying identity:

- Contributor on target subscription/resource group
- Network Contributor for VNets/subnets/private endpoints/DNS links
- Private DNS Zone Contributor (if using existing zones)
- User Access Administrator or Owner (for role assignments)
- Entra admin role for app registration + app role assignment when doing manual Entra steps

## 2. Initialize local deployment context

From repository root:

```bash
cd /home/mcerreto/work/c3techlab/agent-az-farsight

az login
azd auth login

azd env list
azd env new <env-name>   # if new
azd env select <env-name>
```

Set region defaults:

```bash
azd env set AZURE_LOCATION italynorth
azd env set AZURE_COLLECTOR_LOCATION italynorth
```

## 3. Configure baseline AZD variables

Set core deployment flags first (adjust to your target topology):

```bash
azd env set FARSIGHT_ENABLE_PRIVATE_ENDPOINTS true
azd env set FARSIGHT_ENABLE_PUBLIC_INGRESS false
azd env set FARSIGHT_ENABLE_ACR_TASK_NETWORK_BYPASS true
azd env set FARSIGHT_ENABLE_APIM false
azd env set FARSIGHT_ENABLE_NAT_GATEWAY false
```

Set network ranges:

```bash
azd env set FARSIGHT_VNET_ADDRESS_PREFIX 10.42.0.0/16
azd env set FARSIGHT_CONTAINER_APPS_INFRASTRUCTURE_SUBNET_PREFIX 10.42.1.0/23
azd env set FARSIGHT_PRIVATE_ENDPOINT_SUBNET_PREFIX 10.42.4.0/24
azd env set FARSIGHT_APIM_SUBNET_PREFIX 10.42.6.0/24
```

ACR build firewall ranges (required for AZD remote builds when registry is private/default-deny):

```bash
azd env set FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_ITALY_NORTH 4.232.51.192/26
azd env set FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_SWEDEN_CENTRAL 172.160.222.128/26
azd env set FARSIGHT_ACR_FIREWALL_ALLOWED_IP_RANGE_CLIENT "$(curl -s https://api.ipify.org)/32"
```

## 4. Configure private DNS mapping (if linking existing zones)

If your platform team provides existing private DNS zones, enable linking and set IDs:

```bash
azd env set FARSIGHT_LINK_EXISTING_PRIVATE_DNS_ZONES true
azd env set FARSIGHT_PRIVATE_DNS_ZONE_STORAGE_BLOB_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_KEY_VAULT_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_CONTAINER_REGISTRY_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_COSMOS_SQL_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_SERVICE_BUS_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_APP_CONFIGURATION_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_CONTAINER_APPS_ENVIRONMENT_RESOURCE_ID "<resource-id>"
```

> The Azure Monitor private DNS zone variables (`FARSIGHT_PRIVATE_DNS_ZONE_AZURE_MONITOR_RESOURCE_ID`, `..._LOG_ANALYTICS_OMS_...`, `..._LOG_ANALYTICS_ODS_...`, `..._AZURE_MONITOR_AGENT_SVC_...`) are no longer consumed. Application Insights and Log Analytics use public ingestion/query and are not placed behind a monitor private endpoint, so no Azure Monitor private DNS zones are created or linked.

If APIM private networking is enabled, also set:

```bash
azd env set FARSIGHT_PRIVATE_DNS_ZONE_API_MANAGEMENT_RESOURCE_ID "<resource-id>"
```

## 5. First pass deploy (infrastructure + apps, without optional auth hardening)

Keep these disabled for pass 1 unless you already prepared Entra metadata:

```bash
azd env set FARSIGHT_ENABLE_ADMIN_EASY_AUTH false
azd env set FARSIGHT_ENABLE_API_WORKLOAD_AUTH false
```

Set internal admin mutation shared secret before first `azd up`:

```bash
azd env set FARSIGHT_API_INTERNAL_AUTH_SECRET "<strong-random-secret>"
```

If public MCR placeholder pulls are throttled or blocked during provision, point placeholders to already-pushed private ACR tags from a previous successful deploy:

```bash
azd env set FARSIGHT_API_PLACEHOLDER_IMAGE "<acr>.azurecr.io/agent-azure-farsight/api-dev:<known-good-tag>"
azd env set FARSIGHT_ADMIN_PLACEHOLDER_IMAGE "<acr>.azurecr.io/agent-azure-farsight/admin-web-dev:<known-good-tag>"
azd env set FARSIGHT_TOOLS_PLACEHOLDER_IMAGE "<acr>.azurecr.io/agent-azure-farsight/agent-tools-dev:<known-good-tag>"
```

Preview and deploy:

```bash
azd provision --preview
azd up
```

Notes:

- `azure.yaml` runs `scripts/register-resource-providers.sh` pre-provision.
- AZD builds/pushes `api`, `admin-web`, and `agent-tools`.
- With private endpoints + remote build, keep `FARSIGHT_ENABLE_ACR_TASK_NETWORK_BYPASS=true` unless you use a private runner with direct ACR reachability.

## 6. Manual Entra step A: Admin Easy Auth app registration

After first deploy, get the admin host and create/update app registration:

```bash
python3 scripts/provision-admin-app-registration.py \
  --redirect-uri "https://<admin-host>/.auth/login/aad/callback" \
  --create-secret
```

Set emitted values in AZD env:

```bash
azd env set FARSIGHT_ADMIN_AUTH_CLIENT_ID "<value>"
azd env set FARSIGHT_ADMIN_AUTH_CLIENT_SECRET "<value>"
azd env set FARSIGHT_ADMIN_AUTH_ENCRYPTION_SECRET "<value>"
azd env set FARSIGHT_ADMIN_AUTH_ISSUER "<value>"
azd env set FARSIGHT_ADMIN_AUTH_ALLOWED_AUDIENCE "<value>"
azd env set FARSIGHT_ENABLE_ADMIN_EASY_AUTH true
```

## 7. Manual Entra step B: FarSight API app registration (workload auth)

Create/update API app registration + application app role:

```bash
python3 scripts/provision-farsight-api-app-registration.py
```

Set emitted values in AZD env:

```bash
azd env set FARSIGHT_ENABLE_API_WORKLOAD_AUTH true
azd env set FARSIGHT_API_ALLOWED_AUDIENCES "<csv-from-script>"
azd env set FARSIGHT_API_REQUIRED_APP_ROLE "<value-from-script>"
```

At this stage you also need allowed caller SP object IDs:

```bash
az ad sp show --id "<sre-managed-identity-client-id>" --query id -o tsv
azd env set FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS "<sre-mi-sp-object-id>"
```

## 8. Grant FarSight API app role to SRE managed identity

Use the dedicated grant helper:

```bash
MI_CLIENT_ID="<sre-mi-client-id>" \
FARSIGHT_API_APP_ID="<farsight-api-app-id>" \
FARSIGHT_API_ROLE_VALUE="Farsight.Api.Access" \
./src/sre-agent/scripts/grant-farsight-api-access.sh
```

## 9. Second pass apply (activate Easy Auth + workload auth in runtime)

Run deployment again to apply new env settings into Container Apps:

```bash
azd provision
azd up
```

## 10. Post-deployment verification checklist

1. Container Apps
   - API/admin/tools apps are healthy
   - ingress mode matches `FARSIGHT_ENABLE_PUBLIC_INGRESS`
2. DNS/private endpoints
   - private endpoint connections approved
   - expected `privatelink` records exist
3. Auth
   - admin web requires Entra login when Easy Auth enabled
   - workload calls without valid bearer token fail on protected endpoints
4. ACR/image pull
   - no `UNAUTHORIZED` pull failures on revisions
5. Telemetry
   - Application Insights and Log Analytics receiving data

## 11. Deploy the separate SRE Agent package

The SRE Agent is **not** deployed by root `azd up`. Deploy it from:

- `src/sre-agent/agent`

Use a **dedicated AZD environment** for the SRE package so outputs/vars do not collide with the main FarSight environment.

Create/select that environment from the SRE package folder:

```bash
cd src/sre-agent/agent

azd env list
azd env new <sre-env-name>      # example: sre-dev
azd env select <sre-env-name>
```

Set minimum recommended variables before `azd up`:

```bash
azd env set AZURE_LOCATION swedencentral
azd env set AZURE_PRINCIPAL_ID "<entra-object-id-for-sre-admin-role>"
azd env set INTUNE_DIAGNOSTICS_AUTH_MODE managed-identity   # or key-vault

# FarSight API base URL - copy from the main FarSight azd env output
azd env set FARSIGHT_API_BASE_URL "<farsight-api-base-url>"

# FarSight API token scope for managed identity auth (avoids invalid_scope error)
# Use FARSIGHT_API_APP_ID output from scripts/provision-farsight-api-app-registration.py
azd env set FARSIGHT_API_SCOPE "api://<farsight-api-app-id>/.default"

# Optional but recommended SRE resource defaults
azd env set SRE_AGENT_UPGRADE_CHANNEL Stable
azd env set SRE_AGENT_DEFAULT_MODEL_PROVIDER Anthropic
azd env set SRE_AGENT_DEFAULT_MODEL_NAME Automatic
azd env set SRE_AGENT_MONTHLY_AGENT_UNIT_LIMIT 10000
azd env set SRE_AGENT_ENABLE_SANDBOX_GROUP true
azd env set SRE_AGENT_ENABLE_WORKSPACE_TOOLS true

# Optional: set only for first-time Agent Space identity initialization
azd env set SRE_AGENT_INITIAL_SPONSOR_GROUP_ID "<entra-group-object-id>"
```

If this SRE environment must use private endpoints, also set the SRE-specific networking variables from `src/sre-agent/agent/infra/main.bicepparam` (for example `SRE_AGENT_ENABLE_PRIVATE_ENDPOINTS`, address prefixes, and the Key Vault private DNS zone ID).

> **Application Insights and Log Analytics use public ingestion/query and are not placed behind private endpoints.** The Agent portal trace viewer queries telemetry over the public endpoint, so Azure Monitor private link (AMPLS) would break trace loading (`PrivateOnly` query mode returns 403). When `SRE_AGENT_ENABLE_PRIVATE_ENDPOINTS=true`, only the Key Vault dependency gets a private endpoint; the monitoring module always provisions Application Insights and the Log Analytics workspace with `publicNetworkAccessForIngestion`/`publicNetworkAccessForQuery` set to `Enabled`.

Deploy SRE infrastructure + content:

```bash
azd up
```

Important notes after SRE deploy:

- Keep SRE Agent env/region separate from FarSight core env if required.
- For `INTUNE_DIAGNOSTICS_AUTH_MODE=managed-identity`, grant Graph app permissions:

```bash
MI_CLIENT_ID="<sre-mi-client-id>" \
./src/sre-agent/scripts/grant-intune-permissions.sh
```

- Use content dry run before upload:

```bash
cd src/sre-agent/agent
python3 deploy.py --dry-run
```

## 12. Deploy Intune collector only after cloud path is proven

Rollout sequence:

1. Package collector from `src/collector`
2. Configure endpoint API URL/cert/module manifest
3. Publish to lab ring via Intune
4. Validate health/remediation policies
5. Expand rings gradually (lab -> pilot -> limited prod -> broad prod)

Do not use temporary public ingress as a shortcut for broad collector rollout.

## 13. Common failure patterns

### `UNAUTHORIZED` while pulling ACR images

- Re-run `azd provision` to ensure registry config + `AcrPull` role assignment are applied.
- Verify ACR firewall range and bypass settings for AZD remote build.

### Private DNS resolves public IP or NXDOMAIN

- Validate zone link coverage for all required VNets/resolver path.
- Confirm private endpoint zone groups created A records.

### Easy Auth not active after deploy

- Confirm all required `FARSIGHT_ADMIN_AUTH_*` variables are set.
- Re-run `azd provision` after setting them.

### Workload auth denies SRE caller

- Confirm `FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS` includes SRE MI SP object ID.
- Confirm SRE MI has the required API app role assignment.
- Confirm token audience matches `FARSIGHT_API_ALLOWED_AUDIENCES`.

### FarSight tools fail with `(invalid_scope) None, None` / auth error

The FarSight tools default to `{api_base_url}/.default` as the token scope when `FARSIGHT_API_SCOPE` is not set. The Container Apps URL is **not** a valid Entra resource audience.

1. Get the FarSight API app registration client ID:
   ```bash
   python3 scripts/provision-farsight-api-app-registration.py  # outputs FARSIGHT_API_APP_ID
   ```
2. Set the correct scope in the SRE azd environment:
   ```bash
   cd src/sre-agent/agent
   azd env set FARSIGHT_API_SCOPE "api://<FARSIGHT_API_APP_ID>/.default"
   ```
3. Grant the SRE managed identity the `Farsight.Api.Access` app role:
   ```bash
   MI_CLIENT_ID="<sre-mi-client-id>" \
   FARSIGHT_API_APP_ID="<farsight-api-app-id>" \
   ./src/sre-agent/scripts/grant-farsight-api-access.sh
   ```
4. Redeploy tools so the scope default is injected:
   ```bash
   cd src/sre-agent/agent
   python3 deploy.py --skip-kb --skip-skills
   ```

### `InvalidApplicationInsightsConfiguration: The AppId and ConnectionString fields must be provided together`

- The SRE Agent ARM payload must include both Application Insights `appId` and `connectionString` in `logConfiguration.applicationInsightsConfiguration`.
- Re-run `azd provision`/`azd up` after pulling the latest infra changes in `src/sre-agent/agent/infra/modules/sre-agent.bicep`.

### `A resource with this name already exists or is in a conflicting state` during SRE Agent provision

- Check whether the agent already exists in the target resource group:
  `az resource show --resource-group <rg> --resource-type Microsoft.App/agents --name <agent-name>`.
- If re-running against an existing agent, leave `SRE_AGENT_INITIAL_SPONSOR_GROUP_ID` unset. This value is intended for first-create identity initialization only.

### SRE Agent portal: `Failed to load trace data: Request failed with status code 403`

The trace viewer reads execution traces from the linked Application Insights (workspace-based), which is a data-plane operation. The control-plane `Reader` role is not enough.

- `infra/modules/monitoring-access.bicep` grants the SRE Agent system-assigned and user-assigned identities **Monitoring Reader** on both Application Insights and the Log Analytics workspace. Re-run `azd provision` after pulling the latest infra.
- To fix an existing deployment immediately, grant Monitoring Reader to both agent identities:

  ```bash
  RG=<sre-resource-group>
  AGENT=<sre-agent-name>
  SUB=<subscription-id>
  APPI_ID=$(az resource show -g "$RG" --resource-type Microsoft.Insights/components --name "appi-$AGENT" --query id -o tsv)
  LAW_ID=$(az resource show -g "$RG" --resource-type Microsoft.OperationalInsights/workspaces --name "law-$AGENT" --query id -o tsv)
  SYS_MI=$(az resource show -g "$RG" --resource-type Microsoft.App/agents --name "$AGENT" --query identity.principalId -o tsv)
  for SCOPE in "$APPI_ID" "$LAW_ID"; do
    az role assignment create --assignee-object-id "$SYS_MI" --assignee-principal-type ServicePrincipal \
      --role "43d0d8ad-25c7-4714-9337-8ba259a9fe05" --scope "$SCOPE"
  done
  ```

- RBAC propagation can take a few minutes; refresh the trace view afterward.

There are two independent causes for this 403; check both:

1. **Missing telemetry-read role** (handled by the Monitoring Reader grant above).
2. **Azure Monitor private link / restricted public query.** If the Log Analytics workspace has `publicNetworkAccessForQuery=Disabled`, or it is scoped into an Azure Monitor Private Link Scope (AMPLS) with `queryAccessMode=PrivateOnly`, the portal's public query is blocked. The current infra provisions Application Insights and Log Analytics with public ingestion/query and no AMPLS. To remediate an older deployment that still has these:

   ```bash
   RG=<sre-resource-group>
   AGENT=<sre-agent-name>
   # Re-enable public query/ingestion on the workspace
   az monitor log-analytics workspace update -g "$RG" --workspace-name "law-$AGENT" \
     --ingestion-access Enabled --query-access Enabled
   # Remove the Azure Monitor private endpoint and AMPLS if present
   az network private-endpoint delete -g "$RG" --name "pe-ampls-<suffix>"
   az resource delete -g "$RG" --resource-type Microsoft.Insights/privateLinkScopes --name "ampls-<suffix>"
   # Delete the now-orphaned monitor private DNS zones (remove vnet links first)
   for Z in privatelink.monitor.azure.com privatelink.oms.opinsights.azure.com \
            privatelink.ods.opinsights.azure.com privatelink.agentsvc.azure-automation.net; do
     for L in $(az network private-dns link vnet list -g "$RG" --zone-name "$Z" --query "[].name" -o tsv); do
       az network private-dns link vnet delete -g "$RG" --zone-name "$Z" --name "$L" --yes
     done
     az network private-dns zone delete -g "$RG" --name "$Z" --yes
   done
   ```


