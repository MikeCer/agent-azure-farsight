# Agent-Azure-FarSight SRE Agent

This folder packages the Agent-Azure-FarSight SRE Agent as an Azure Developer CLI template for Azure SRE Agent.

The package provisions an Azure SRE Agent resource and deploys one custom agent, the Intune diagnostics collector tool, the governed FarSight diagnostic tool surface, and Skill Builder skills for both evidence paths. Intune diagnostics remain a supported evidence source; FarSight diagnostics provide the governed workflow for approved jobs, result summaries, artifact metadata, investigation history, follow-up modules, and approvals.

## Included files

| Path | Purpose |
| --- | --- |
| `azure.yaml` | azd template entry point. |
| `infra/` | Bicep provisioning for Log Analytics, Application Insights, Key Vault, Agent Space, managed identity, and `Microsoft.App/agents@2026-01-01`. |
| `deploy.py` | Uploads knowledge files, deploys Python tools, deploys skills, and deploys the custom agent through the Azure SRE Agent data-plane API. See `DEPLOY.md` for the detailed flow. |
| `agent-azure-farsight-sre.yaml` | Azure SRE Agent configuration for Agent-Azure-FarSight SRE. |
| `skills/intune-data-analysis/` | Skill Builder package for analyzing Intune collector JSON as one evidence source. |
| `skills/farsight-system-context/` | Skill Builder package for FarSight system context, module selection, and policy boundaries. |
| `skills/farsight-tool-orchestration/` | Skill Builder package for FarSight job orchestration and parameter-accurate tool usage. |
| `knowledge/agent.md` | Source system instructions used to build the agent. |
| `knowledge/intune-data-catalog.md` | Catalog of Intune/Graph data sources, output mappings, permissions, and limitations. |
| `tools/intune_diagnostics_tool.py` | Single-file Azure SRE PythonFunctionTool artifact exposing `main(...) -> dict`. |
| `tools/intune_diagnostics_tool.yaml` | Tool deployment manifest for `intune_diagnostics_tool`. |
| `tools/create_diagnostic_job.*`, `get_job_status.*`, `get_job_result_summary.*`, `retrieve_artifact_metadata.*`, `query_device_investigation_history.*`, `request_follow_up_module_execution.*`, `request_approval_for_action.*` | FarSight tool manifests and Python functions for governed diagnostic workflows. |

## Deployment

Install the deploy script dependency:

```bash
python3 -m pip install -r requirements.txt
```

The postdeploy script calls the Azure CLI (`az`) to resolve the SRE Agent endpoint and get a bearer token. Authenticate `az` in the same shell/environment that runs the hook:

```bash
az login --tenant <tenant-id>
az account set --subscription <subscription-id>
az account show --query id -o tsv
```

If you run `azd up` on Windows while `azure.yaml` uses `shell: sh`, the hook may execute through WSL or Git Bash and use a different `az` login cache than Windows PowerShell. Either authenticate `az` in that shell or switch the postdeploy hook to `pwsh` for a Windows PowerShell-based run.

Provision and deploy:

```bash
azd up
```

The `postdeploy` hook in `azure.yaml` runs `python3 -u deploy.py` so hook logs stream without Python buffering during `azd up`.
`deploy.py` also writes a persistent copy of hook output to `agent/.logs/deploy-<timestamp>.log`.

Content-only deployment after infrastructure already exists:

```bash
python3 deploy.py --agent-name <sre-agent-resource-name> \
  --resource-group <sre-agent-resource-group> \
  --subscription <subscription-id>
```

`deploy.py` uploads only supported document formats to AgentMemory. Python sources are deployed separately as ExtendedAgent tools through `/api/v2/extendedAgent/tools/{name}`.

Dry-run validation without remote API calls:

```bash
python3 deploy.py --agent-name dry-run --dry-run
```

## azd environment values

Set these with `azd env set <KEY> <VALUE>` before `azd up`:

| Variable | Required | Notes |
| --- | --- | --- |
| `AZURE_ENV_NAME` | Yes | Drives resource group and resource naming. |
| `AZURE_LOCATION` | No | Defaults to `westeurope`. |
| `AZURE_PRINCIPAL_ID` | Recommended | Entra object ID that receives SRE Agent Administrator role. |
| `SRE_AGENT_UPGRADE_CHANNEL` | No | Defaults to `Stable` so new deployments use the current non-preview SRE Agent generation. |
| `SRE_AGENT_DEFAULT_MODEL_PROVIDER` | No | Defaults to `Anthropic`; allowed values are `Anthropic` and `MicrosoftFoundry`. |
| `SRE_AGENT_DEFAULT_MODEL_NAME` | No | Defaults to `Automatic`. |
| `SRE_AGENT_MONTHLY_AGENT_UNIT_LIMIT` | No | Defaults to `10000`. Matches current migrated SRE Agent resource unit-limit shape. |
| `SRE_AGENT_ENABLE_SANDBOX_GROUP` | No | Defaults to `true`. Enables the newer SRE sandbox feature on resource creation. |
| `SRE_AGENT_ENABLE_WORKSPACE_TOOLS` | No | Defaults to `true`. Enables newer workspace tool capabilities on resource creation. |
| `SRE_AGENT_INITIAL_SPONSOR_GROUP_ID` | Optional | Entra group object ID used to initialize the 2026 SRE Agent identity on first create. Leave empty for repeatable updates. |
| `SRE_AGENT_ENABLE_AGENT_SPACE` | No | Defaults to `false`. Set to `true` only when `Microsoft.App/agentSpaces` is enabled for the tenant/subscription. |
| `FARSIGHT_API_BASE_URL` | Recommended | FarSight control-plane API base URL. Injected as the default `api_base_url` for all FarSight tools (`create_diagnostic_job`, `get_job_status`, `get_job_result_summary`, `retrieve_artifact_metadata`, `query_device_investigation_history`, `request_follow_up_module_execution`, `request_approval_for_action`). If omitted, the agent must supply `api_base_url` explicitly on each tool call. Set to the `FARSIGHT_API_BASE_URL` output from the main FarSight azd environment. |
| `FARSIGHT_API_SCOPE` | Recommended | Token scope for FarSight API managed identity auth. Format: `api://<farsight-api-app-id>/.default`. Obtain `<farsight-api-app-id>` from the `FARSIGHT_API_APP_ID` output of `scripts/provision-farsight-api-app-registration.py`. If omitted, tools fall back to `{api_base_url}/.default` which will fail with `invalid_scope` when the FarSight API is Entra-protected. |
| `FARSIGHT_AUTH_MODE` | No | FarSight API authentication mode injected into FarSight tools. Defaults to `default`, which uses `DefaultAzureCredential` in the SRE Agent tool runtime. |

FarSight tool runtime does not automatically inherit the operator shell or `azd env` values. During `deploy.py`, these values are embedded into each deployed Python tool as code-level defaults and exposed as parameter defaults, so the SRE Agent can omit `api_base_url`, `api_scope`, and `auth_mode` on normal tool calls.

## Intune runtime credentials

The deployment creates a Key Vault for Intune diagnostics runtime credentials and grants:

- the SRE Agent user-assigned managed identity `Key Vault Secrets User`
- `AZURE_PRINCIPAL_ID`, when provided, `Key Vault Secrets Officer`

The default deployment mode is **managed identity**. After `azd up`, call `intune_diagnostics_tool` with:

```json
{
  "device_name": "<deviceName>",
  "auth_mode": "default"
}
```

If you explicitly opt into `key-vault` mode, use the Key Vault output and secret names below:

| Secret name | Value |
| --- | --- |
| `intune-tenant-id` | Microsoft Entra tenant id |
| `intune-client-id` | App registration / service principal client id |
| `intune-client-secret` | Client secret for the app registration |

Optional direct service-principal auth:

```bash
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
```

Do not commit these values. Configure them through managed identity by default, or through Key Vault only when you explicitly choose `key-vault` mode.

The service principal needs Microsoft Graph permissions for the Intune collector, including the read-only Device Management permissions documented in `knowledge/intune-data-catalog.md`.

## Scope

This package supports Intune/Graph evidence analysis and governed FarSight diagnostic workflows. `intune_diagnostics_tool` is a read-only evidence source. FarSight workflows must use the named FarSight tools, stay within approved diagnostic modules and scopes, and request approval before higher-risk follow-up or remediation actions.

## Suggested prompt

```text
Analyze this Intune diagnostics JSON for device health, performance bottlenecks, app crashes, restart/shutdown events, and prioritized remediation actions.
```

Or ask the agent to collect evidence first:

```text
Analyze device <deviceName> for performance and health issues.
```

Or ask for governed FarSight diagnostics:

```text
Run FarSight diagnostics for device <deviceName> and summarize the job status, result summary, and approved artifact metadata.
```
