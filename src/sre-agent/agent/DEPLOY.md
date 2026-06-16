# `deploy.py` deployment flow

`deploy.py` is the content deployment script for Agent-Azure-FarSight SRE. It runs after `azd up` as the `postdeploy` hook and can also be run manually when the Azure infrastructure already exists.

The script does not create Azure resources. Infrastructure is created by the Bicep files under `infra/`; `deploy.py` configures the running Azure SRE Agent through its data-plane API.

## What the script deploys

| Content | Source | Destination |
| --- | --- | --- |
| Knowledge files | `knowledge/agent.md`, `knowledge/intune-data-catalog.md`, and Skill Builder Markdown docs | AgentMemory upload endpoint |
| Python tools | `tools/*.yaml` + matching `tools/*.py`, including `intune_diagnostics_tool` and the FarSight diagnostic tools | `/api/v2/extendedAgent/tools/{toolName}` |
| Skills | `skills/intune-data-analysis/skill.yaml`, `skills/farsight-system-context/skill.yaml`, `skills/farsight-tool-orchestration/skill.yaml`, and matching `SKILL.md` files | `/api/v2/extendedAgent/skills/{skillName}` |
| Custom agent | `agent-azure-farsight-sre.yaml` | `/api/v2/extendedAgent/agents/agent-azure-farsight-sre` |

## Inputs and defaults

The script accepts command-line arguments and falls back to environment variables, including values emitted by `azd` from Bicep outputs.

For every run, `deploy.py` persists a full copy of console output under:

```text
src/sre-agent/agent/.logs/deploy-<UTC timestamp>.log
```

This is especially useful when `azd` hook terminal output is cleared by the shell/UI after completion.

| Option | Environment fallback | Purpose |
| --- | --- | --- |
| `--agent-name` / `-n` | `SRE_AGENT_NAME` | ARM resource name of the Azure SRE Agent. |
| `--resource-group` / `-g` | `AZURE_RESOURCE_GROUP`, then `rg-$AZURE_ENV_NAME`, then `rg-agent-azure-farsight-sre` | Resource group containing the agent. |
| `--subscription` / `-s` | `AZURE_SUBSCRIPTION_ID` | Azure subscription ID. |
| `--dry-run` | none | Builds and prints planned actions without resolving the endpoint or calling the data plane. |
| `--skip-kb` | none | Skips AgentMemory knowledge upload. |
| `--skip-tools` | none | Skips Python tool deployment. |
| `--skip-skills` | none | Skips Skill Builder skill deployment. |

The data-plane token audience defaults to `59f0a04a-b322-4310-adc9-39ac41e9631e`. Override with `SRE_AGENT_TOKEN_RESOURCE` only if the SRE Agent service changes token audience.

## Execution phases

### 1. Resolve Azure context

For non-dry-run deployments, the script first checks that the Azure CLI can access the target subscription:

```bash
az account show --subscription <subscription-id> --query id -o tsv
```

This matters because `azd` and `az` can use different authentication caches, especially when the `azure.yaml` hook runs with `shell: sh` on Windows and executes through WSL or Git Bash.

### 2. Resolve the SRE Agent data-plane endpoint

The script looks up the ARM resource:

```bash
az resource show \
  --resource-type Microsoft.App/agents \
  --name <agent-name> \
  --resource-group <resource-group> \
  --query properties
```

It accepts either `properties.endpoint` or `properties.agentEndpoint`, then removes any trailing slash.

### SRE Agent resource shape alignment

The Bicep deployment now aligns with the migrated stable SRE Agent resource shape by explicitly setting:

- `logConfiguration.applicationInsightsConfiguration` with both `appId` and `connectionString` (the SRE Agent API requires these together), while still linking the App Insights resource ID,
- `monthlyAgentUnitLimit` (default `10000`),
- `experimentalSettings.EnableSandboxGroup` (default `true`),
- `experimentalSettings.EnableWorkspaceTools` (default `true`).

### Trace viewer access (Monitoring Reader)

The Agent portal trace viewer loads execution traces from the linked Application Insights (workspace-based). Reading that telemetry is a **data-plane** operation, so the control-plane `Reader` role is not sufficient and the viewer returns `Failed to load trace data: Request failed with status code 403`.

`infra/modules/monitoring-access.bicep` grants the SRE Agent system-assigned and user-assigned identities the **Monitoring Reader** role (`43d0d8ad-25c7-4714-9337-8ba259a9fe05`) on both the Application Insights component and the Log Analytics workspace. Role assignment propagation can take a few minutes after `azd provision`; refresh the trace view afterward.


### 3. Resolve Intune diagnostics authentication defaults

The script reads `INTUNE_DIAGNOSTICS_AUTH_MODE` to decide which tool call shape to inject into the deployed agent and skill instructions.

| Value | Injected tool authentication | Use when |
| --- | --- | --- |
| `managed-identity` | `auth_mode: default` | The SRE Agent assigned identity has Microsoft Graph/Intune application permissions and admin consent. This is the default. |
| `key-vault` | `auth_mode: client-secret` plus Key Vault URL and secret names | Optional fallback for deployments that intentionally store Intune credentials in Key Vault. |

In `managed-identity` mode, the injected tool call is:

```json
{
  "device_name": "<deviceName>",
  "auth_mode": "default"
}
```

No Key Vault URI is injected, and no Key Vault RBAC repair is attempted. The script prints a managed-identity reminder at the end of deployment, explicitly calling out that Microsoft Graph Intune application permissions with admin consent must be assigned to the runtime SRE Agent identity (system-assigned or user-assigned).

If you explicitly set `INTUNE_DIAGNOSTICS_AUTH_MODE=key-vault`, the script searches the resource group for the generated Key Vault:

```bash
az keyvault list \
  --resource-group <resource-group> \
  --query "[?starts_with(name, 'kv-sre-intune-')].properties.vaultUri | [0]"
```

If found, the URI is injected into the deployed agent and skill instructions through the `{{INTUNE_KEY_VAULT_TOOL_ARGUMENTS}}` placeholder. The deployed instructions then tell the agent to call `intune_diagnostics_tool` with:

```json
{
  "device_name": "<deviceName>",
  "auth_mode": "client-secret",
  "key_vault_url": "<resolved-key-vault-uri>",
  "tenant_id_secret_name": "intune-tenant-id",
  "client_id_secret_name": "intune-client-id",
  "client_secret_secret_name": "intune-client-secret"
}
```

If no Key Vault is found in `key-vault` mode, the placeholder becomes only:

```json
"auth_mode": "client-secret"
```

In that fallback mode, credentials must be supplied by runtime environment variables or explicit tool parameters.

When a Key Vault is found in `key-vault` mode, the script also verifies RBAC for the SRE Agent system-assigned identity. The Python tool runtime can use the agent system-assigned identity when retrieving secrets, so `deploy.py` grants that identity the `Key Vault Secrets User` role on the Key Vault when the assignment is missing.

This complements the infrastructure template, which grants the user-assigned managed identity secret read access. Both identities can exist on the SRE Agent resource, but the Python tool sandbox may authenticate with the system-assigned identity.


### 4. Upload knowledge files

Knowledge files are uploaded as multipart form data to:

```text
POST /api/v1/agentmemory/upload?triggerIndexing=true
```

The script sets MIME types based on file extension. Markdown files are uploaded as `text/markdown`.

After upload, the script expects the service response to list accepted files, then later checks the indexer status during verification.

### 5. Deploy Python tools

Every `tools/*.yaml` file is converted to an `ExtendedAgentTool` payload. The tool set includes `intune_diagnostics_tool` for read-only Microsoft Graph/Intune evidence and the FarSight tools for governed diagnostic jobs, status, result summaries, artifact metadata, investigation history, follow-up modules, and approvals.

For `intune_diagnostics_tool.yaml`, the deployment body includes:

```json
{
  "name": "intune_diagnostics_tool",
  "type": "ExtendedAgentTool",
  "properties": {
    "type": "PythonFunctionTool",
    "description": "...",
    "parameters": [],
    "functionCode": "<contents of tools/intune_diagnostics_tool.py>",
    "dependencies": [],
    "authEnabled": true,
    "authScopes": ["https://vault.azure.net/.default"],
    "timeoutSeconds": 120,
    "toolMode": "Auto"
  }
}
```

The script sends each tool to:

```text
PUT /api/v2/extendedAgent/tools/{toolName}
```

Important details:

- Python source must be sent as `functionCode`, not `code`.
- The deployed Python source must expose a top-level typed `main(...) -> dict`.
- The deployed Python source must not include a top-level CLI execution block, because Azure SRE Agent loads tools in an IPython kernel context.
- The SRE Agent PythonFunctionTool runtime does not automatically inherit `azd env` or operator shell variables. `deploy.py` therefore embeds SRE gateway endpoint defaults (`SRE_AGENT_TOOL_ENDPOINT_URL`, `SRE_AGENT_TOOL_AUTH_MODE`, and `SRE_AGENT_TOOL_ENDPOINT_SCOPE`) into the deployed FarSight tool source and also sets matching parameter defaults. Runtime `os.environ` lookup remains only as a fallback for custom execution environments.

### 6. Deploy Skill Builder skills

Every `skills/*/skill.yaml` file is converted to a `Skill` payload. The current user-facing skills are:

- `intune-data-analysis` for collector JSON, Endpoint Analytics, Intune health/compliance, app reliability, restart/shutdown, and timeline evidence.
- `farsight-system-context` for FarSight module catalog, investigation strategy, trust boundaries, and policy/approval framing.
- `farsight-tool-orchestration` for concrete FarSight tool sequencing and parameter mapping.

For example:

```json
{
  "name": "intune-data-analysis",
  "type": "Skill",
  "properties": {
    "description": "...",
    "tools": ["intune_diagnostics_tool"],
    "skillContent": "<SKILL.md with runtime defaults injected>",
    "additionalFiles": []
  }
}
```

The script sends each skill to:

```text
PUT /api/v2/extendedAgent/skills/{skillName}
```

### 7. Deploy the custom agent

`agent-azure-farsight-sre.yaml` is converted to an `ExtendedAgent` payload:

```json
{
  "name": "agent-azure-farsight-sre",
  "type": "ExtendedAgent",
  "properties": {
    "instructions": "<system_prompt with runtime defaults injected>",
    "handoffDescription": "...",
    "tools": [
      "intune_diagnostics_tool",
      "create_diagnostic_job",
      "get_job_status",
      "get_job_result_summary",
      "retrieve_artifact_metadata",
      "query_device_investigation_history",
      "request_follow_up_module_execution",
      "request_approval_for_action"
    ],
    "enableSkills": true,
    "allowedSkills": [
      "intune-data-analysis",
      "farsight-system-context",
      "farsight-tool-orchestration"
    ],
    "allowParallelToolCalls": true
  }
}
```

The script sends it to:

```text
PUT /api/v2/extendedAgent/agents/{agentName}
```

## Verification

After deployment, the script checks:

1. AgentMemory indexer status:

   ```text
   GET /api/v1/agentmemory/indexer-status
   ```

   A healthy run should show `last execution Success`, nonzero `documentsProcessed`, and `documentsFailed: 0`.

2. Deployed tools:

   ```text
   GET /api/v2/extendedAgent/tools
   ```

3. Deployed skills:

   ```text
   GET /api/v2/extendedAgent/skills
   ```

4. Deployed agents:

   ```text
   GET /api/v2/extendedAgent/agents
   ```

## Common troubleshooting

### Azure CLI cannot find or access the subscription

Run these commands in the same shell that runs `deploy.py`:

```bash
az login --tenant <tenant-id>
az account set --subscription <subscription-id>
az account show --query id -o tsv
```

On Windows, `azd` with `shell: sh` may run through WSL or Git Bash and use a different `az` login cache than PowerShell.

### Knowledge files upload but are not available

Check the deploy output for:

```text
KB indexer: Running, last execution Success, processed <nonzero>, failed 0
```

If `documentsProcessed` is `0`, make sure the upload endpoint includes `?triggerIndexing=true`. The script now uses:

```text
/api/v1/agentmemory/upload?triggerIndexing=true
```

### Python tool fails with `main is not defined`

The Python tool payload must use `functionCode` and the source must expose `def main(...) -> dict`. Do not deploy the source under a `code` property.

### Python tool tries the wrong tenant

For `key-vault` mode, confirm the live agent and skill instructions include Key Vault parameters:

```json
"key_vault_url": "https://kv-sre-intune-....vault.azure.net/",
"tenant_id_secret_name": "intune-tenant-id",
"client_id_secret_name": "intune-client-id",
"client_secret_secret_name": "intune-client-secret"
```

If they are missing, rerun `deploy.py` after the Key Vault exists or set `INTUNE_DIAGNOSTICS_KEY_VAULT_URI` before running the script.

If Key Vault parameters are present but secret retrieval fails with an authorization error, rerun `deploy.py`. It checks the SRE Agent system-assigned principal and assigns `Key Vault Secrets User` on the Key Vault if needed. The deploying identity must have permission to create role assignments at the Key Vault scope.

For `managed-identity` mode, confirm the live agent and skill instructions include `"auth_mode": "default"` and that the SRE Agent assigned identity has the required Microsoft Graph/Intune application permissions.

### Agent Space deployment is blocked

Some tenants/subscriptions reject `Microsoft.App/agentSpaces` with `AgentSpaceOperationNotAllowed`. The Bicep template keeps Agent Space creation disabled by default through:

```bash
SRE_AGENT_ENABLE_AGENT_SPACE=false
```

Only set it to `true` after Microsoft enables Agent Spaces for the tenant/subscription.
