# Agent-Azure-FarSight SRE Project

This project packages the Agent-Azure-FarSight SRE deployment template, a governed FarSight diagnostic tool surface, and an Intune diagnostics collector. The SRE Agent diagnoses endpoint health and reliability issues using approved evidence sources such as Microsoft Graph/Intune data from `intune_diagnostics_tool` and governed FarSight diagnostic jobs/artifacts.

## Project layout

| Path | Purpose |
| --- | --- |
| `intune-collector/` | Python Intune diagnostics collector source, tests, packaging metadata, generated `dist/`, and build script. |
| `agent/` | Azure SRE Agent azd template, agent YAML, Skill Builder packages, knowledge files, Python tool manifests, FarSight tools, and packaged collector tool. |
| `local-scripts/` | Optional endpoint-side diagnostic scripts kept outside the v1 SRE Agent package. |

## Build the collector tool

Build the collector and refresh the packaged SRE Agent tool with:

```bash
cd intune-collector
python3 scripts/build_single_script.py
```

That command updates both:

- `intune-collector/dist/intune_diagnostics_tool.py`
- `agent/tools/intune_diagnostics_tool.py`

The SRE Agent package uses `agent/tools/intune_diagnostics_tool.py`, so run the build command before deploying whenever collector source changes.

## Deploy the Azure SRE Agent

The deployable Azure SRE Agent package is in `agent/`. It contains:

| Path | Purpose |
| --- | --- |
| `agent/azure.yaml` | Azure Developer CLI template. |
| `agent/infra/` | Bicep for resource group, Log Analytics, Application Insights, Key Vault, Agent Space, managed identity, and `Microsoft.App/agents@2026-01-01`. |
| `agent/deploy.py` | Post-deploy script that uploads knowledge files, deploys Python tools, deploys skills, and deploys the custom agent. |
| `agent/agent-azure-farsight-sre.yaml` | Azure SRE Agent `AgentConfiguration`. |
| `agent/skills/intune-data-analysis/` | Skill Builder package for analyzing Intune collector JSON as one evidence source. |
| `agent/skills/farsight-system-context/` | Skill Builder package for FarSight module catalog, governance model, and investigation strategy framing. |
| `agent/skills/farsight-tool-orchestration/` | Skill Builder package for concrete FarSight tool-call sequencing and parameter mapping. |
| `agent/tools/intune_diagnostics_tool.py` | Packaged Azure SRE PythonFunctionTool source used by the SRE Agent. |
| `agent/tools/intune_diagnostics_tool.yaml` | Tool deployment manifest for `intune_diagnostics_tool`. |
| `agent/tools/create_diagnostic_job.*`, `get_job_status.*`, `get_job_result_summary.*`, `retrieve_artifact_metadata.*`, `query_device_investigation_history.*`, `request_follow_up_module_execution.*`, `request_approval_for_action.*` | FarSight tool surface for governed diagnostic jobs, results, history, artifacts, follow-up modules, and approvals. |

### Prerequisites

- Azure CLI authenticated to the target tenant/subscription.
- Azure Developer CLI (`azd`) for full infrastructure deployment.
- Python 3 with `PyYAML` for `agent/deploy.py`.
- Permission to deploy the SRE Agent infrastructure and assign the SRE Agent Administrator role.
- A Microsoft Graph application or managed identity with the Intune read permissions documented in `intune-collector/docs/intune-data-catalog.md`.

Install the deploy script dependency:

```bash
cd agent
python3 -m pip install -r requirements.txt
```

The `azd` postdeploy hook runs `agent/deploy.py`, which uses the Azure CLI (`az`) directly. Make sure `az` is authenticated in the same shell/environment used by the hook:

```bash
az login --tenant <tenant-id>
az account set --subscription <subscription-id>
az account show --query id -o tsv
```

On Windows, the default `shell: sh` hook can execute through WSL or Git Bash, which may have a different Azure CLI login cache than Windows PowerShell. If the hook reports that a valid subscription is not found, authenticate `az` in that shell or change the hook in `agent/azure.yaml` to use `pwsh`.

### azd configuration

Set azd environment values before provisioning:

```bash
cd agent
azd env set AZURE_ENV_NAME <environment-name>
azd env set AZURE_LOCATION <azure-region>
azd env set AZURE_PRINCIPAL_ID <your-entra-object-id>
```

| Variable | Required | Notes |
| --- | --- | --- |
| `AZURE_ENV_NAME` | Yes | Drives resource group and resource naming. |
| `AZURE_LOCATION` | No | Defaults to `westeurope` if omitted. |
| `AZURE_PRINCIPAL_ID` | Recommended | Entra object ID that receives SRE Agent Administrator role on the deployed SRE Agent resource. |
| `SRE_AGENT_UPGRADE_CHANNEL` | No | Defaults to `Stable` so new deployments use the current non-preview SRE Agent generation. |
| `SRE_AGENT_DEFAULT_MODEL_PROVIDER` | No | Defaults to `Anthropic`; allowed values are `Anthropic` and `MicrosoftFoundry`. |
| `SRE_AGENT_DEFAULT_MODEL_NAME` | No | Defaults to `Automatic`. |
| `SRE_AGENT_INITIAL_SPONSOR_GROUP_ID` | Recommended | Entra group object ID used to initialize the 2026 SRE Agent identity. Falls back to `AZURE_PRINCIPAL_ID` when omitted. |
| `SRE_AGENT_ENABLE_AGENT_SPACE` | No | Defaults to `false`. Set to `true` only when `Microsoft.App/agentSpaces` is enabled for the tenant/subscription. |
| `INTUNE_DIAGNOSTICS_AUTH_MODE` | No | Defaults to `key-vault`. Use `managed-identity` to make the tool call Microsoft Graph with the SRE Agent assigned identity instead of Key Vault service-principal credentials. |

### Full deployment

From `agent`:

```bash
azd up
```

`azd up` provisions the infrastructure and then runs:

```bash
python3 deploy.py
```

The post-deploy script uploads these knowledge files:

- `knowledge/agent.md`
- `knowledge/intune-data-catalog.md`
- `skills/intune-data-analysis/SKILL.md`
- `skills/farsight-system-context/SKILL.md`
- `skills/farsight-tool-orchestration/SKILL.md`

It then deploys:

- Tools: `intune_diagnostics_tool` and the FarSight diagnostic tools
- Skills: `intune-data-analysis`, `farsight-system-context`, `farsight-tool-orchestration`
- Agent: `agent-azure-farsight-sre`

### Content-only deployment

Use this when the SRE Agent resource already exists:

```bash
cd agent
python3 deploy.py --agent-name <sre-agent-resource-name> \
  --resource-group <sre-agent-resource-group> \
  --subscription <subscription-id>
```

Useful options:

| Option | Purpose |
| --- | --- |
| `--dry-run` | Print the knowledge files, tools, skills, and agent YAML that would be deployed without remote API calls. |
| `--skip-kb` | Skip knowledge upload. |
| `--skip-tools` | Skip Python tool deployment. |
| `--skip-skills` | Skip Skill Builder skill deployment. |
| `--agent-name` | SRE Agent ARM resource name. Falls back to `SRE_AGENT_NAME`. |
| `--resource-group` | Resource group containing the SRE Agent. Falls back to `AZURE_RESOURCE_GROUP`, `rg-$AZURE_ENV_NAME`, or `rg-agent-azure-farsight-sre`. |
| `--subscription` | Azure subscription ID. Falls back to `AZURE_SUBSCRIPTION_ID`. |

Dry-run example:

```bash
cd agent
python3 deploy.py --agent-name dry-run --dry-run
```

## Runtime Intune configuration

The deployment supports two authentication modes for `intune_diagnostics_tool`. Choose the mode before `azd up`:

```bash
azd env set INTUNE_DIAGNOSTICS_AUTH_MODE key-vault
# or
azd env set INTUNE_DIAGNOSTICS_AUTH_MODE managed-identity
```

### Key Vault service-principal mode

`key-vault` is the default. The post-deploy script injects Key Vault parameters into the deployed agent and skill instructions, so the tool retrieves service-principal credentials from Key Vault and calls Microsoft Graph/Intune with those credentials.

The deployment creates a Key Vault and outputs:

- `INTUNE_DIAGNOSTICS_KEY_VAULT_NAME`
- `INTUNE_DIAGNOSTICS_KEY_VAULT_URI`

After deployment, add these secrets in the Azure portal:

| Secret name | Value |
| --- | --- |
| `intune-tenant-id` | Microsoft Entra tenant id |
| `intune-client-id` | App registration / service principal client id |
| `intune-client-secret` | Client secret for the app registration |

The SRE Agent system-assigned identity needs `Key Vault Secrets User` on this Key Vault. `deploy.py` checks and creates that role assignment when it runs, if the deploying identity has permission to create role assignments.

### Managed identity mode

`managed-identity` makes the deployed instructions call the tool with:

```json
{
  "device_name": "<deviceName>",
  "auth_mode": "default"
}
```

In this mode the Python tool uses `DefaultAzureCredential`, so the SRE Agent assigned identity must have the required Microsoft Graph application permissions for Intune. Grant and admin-consent the required Graph permissions to the managed identity/service principal before testing this mode.

The SRE Agent collector also supports service-principal authentication through environment variables:

```bash
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
```

Do not commit these values. Configure them through Key Vault, the approved secret mechanism for the target Azure SRE Agent execution environment, or managed runtime configuration.

The app registration or managed identity should have the Intune/Microsoft Graph read-only permissions required by the collector. Typical permissions include:

- `DeviceManagementManagedDevices.Read.All`
- `DeviceManagementConfiguration.Read.All`
- `DeviceManagementApps.Read.All`
- `DeviceManagementServiceConfig.Read.All`
- `User.Read.All` or equivalent read permission when collecting user-scoped Intune troubleshooting events

Admin consent is required for unattended execution.

## Validate locally

Before deploying, run:

```bash
cd intune-collector
python3 scripts/build_single_script.py
cmp -s dist/intune_diagnostics_tool.py ../agent/tools/intune_diagnostics_tool.py
PYTHONPATH=src python3 -m unittest discover -s tests
```

Then validate the SRE Agent package:

```bash
cd ../agent
python3 deploy.py --agent-name dry-run --dry-run
az bicep build --file infra/main.bicep --stdout > agent_bicep.json
```

## First prompt after deployment

```text
Analyze this Intune diagnostics JSON for device health, performance bottlenecks, app crashes, restart/shutdown events, and prioritized remediation actions.
```

Or ask the deployed agent to collect Intune evidence first:

```text
Analyze device <deviceName> for performance and health issues.
```

Or ask for a governed FarSight diagnostic workflow:

```text
Run FarSight diagnostics for device <deviceName> and summarize the job status, result summary, and approved artifact metadata.
```
