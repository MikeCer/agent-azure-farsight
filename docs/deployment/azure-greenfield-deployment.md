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
azd env set FARSIGHT_PRIVATE_DNS_ZONE_AZURE_MONITOR_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_LOG_ANALYTICS_OMS_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_LOG_ANALYTICS_ODS_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_AZURE_MONITOR_AGENT_SVC_RESOURCE_ID "<resource-id>"
azd env set FARSIGHT_PRIVATE_DNS_ZONE_CONTAINER_APPS_ENVIRONMENT_RESOURCE_ID "<resource-id>"
```

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

# Optional but recommended SRE resource defaults
azd env set SRE_AGENT_UPGRADE_CHANNEL Stable
azd env set SRE_AGENT_DEFAULT_MODEL_PROVIDER Anthropic
azd env set SRE_AGENT_DEFAULT_MODEL_NAME Automatic
azd env set SRE_AGENT_MONTHLY_AGENT_UNIT_LIMIT 10000
azd env set SRE_AGENT_ENABLE_SANDBOX_GROUP true
azd env set SRE_AGENT_ENABLE_WORKSPACE_TOOLS true
```

If this SRE environment must use private endpoints, also set the SRE-specific networking variables from `src/sre-agent/agent/infra/main.bicepparam` (for example `SRE_AGENT_ENABLE_PRIVATE_ENDPOINTS`, address prefixes, and private DNS zone IDs).

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
