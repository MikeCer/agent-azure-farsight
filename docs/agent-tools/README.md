# Agent tools

FarSight integrates with Azure SRE Agent through governed tools, not a generic command surface. The gateway exposes typed FastAPI endpoints and uses Microsoft Agent Governance Toolkit (AGT) as the production policy engine.

## Azure SRE Agent setup

Agent tools should expose specific diagnostic actions, not generic job runners. Each tool maps typed inputs to an approved FarSight API request.

SRE deployments should route FarSight tool calls through the AGT gateway, not directly to FarSight API. For SRE package configuration use:

- `SRE_AGENT_TOOL_ENDPOINT_URL` (gateway URL)
- `SRE_AGENT_TOOL_ENDPOINT_SCOPE` (token scope used by SRE tools; typically the FarSight API app ID URI, or a dedicated Agent Tools scope emitted by `scripts/provision-farsight-agent-tools-app-registration.py`)
- `SRE_AGENT_TOOL_AUTH_MODE` (default/managed-identity/access-token/auto)

Gateway inbound authorization can also enforce workload JWT validation at FastAPI level on `/tools/*` when `FARSIGHT_AGENT_TOOLS_ENFORCE_WORKLOAD_AUTH=true`. Configure gateway audiences/issuers/caller allowlist with `FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES`, `FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS`, and related `FARSIGHT_AGENT_TOOLS_*` variables.

## Tool contracts

- Validate input against the tool schema before API calls.
- Include module ID, approved parameters, target selector, idempotency key, and justification.
- Return job metadata and next-step guidance instead of raw sensitive evidence.
- For ZIP artifacts, first use `download_artifact_file` to save the artifact into the SRE Agent workspace, then use the local ZIP extraction tool to list contents or extract a named file instead of trying to send the archive through the gateway.

### Gateway-mediated tool routing

Every SRE Agent tool wrapper calls the AGT gateway, not the FarSight control API directly. The gateway exposes one typed endpoint per tool under `POST /tools/{tool_name}` (for example `POST /tools/download_artifact_file`, `POST /tools/retrieve_artifact_content`, `POST /tools/get_job_result_summary`). The wrapper sends a JSON body with camelCase fields (such as `{"jobId": "...", "artifactId": "..."}`) and receives a `ToolResponse` envelope of the form `{"toolName": ..., "policy": ..., "data": {...}}`. The gateway evaluates AGT policy, then forwards to the appropriate control-API route (for example `GET /api/v1/jobs/{jobId}/artifacts/{artifactId}/download`) using its managed identity.

Tool wrappers must never call raw `/api/v1/...` paths against the gateway base URL: the gateway only serves `/tools/*` routes and returns `404 Not Found` for control-API paths. The artifact payload (for example `contentBase64`, `fileName`, `sizeBytes`) is always nested inside the `data` field of the `ToolResponse`; wrappers unwrap `data` before using it.

## AGT policy wrapping

Evaluate AGT policy before every FarSight API call:

- `allow` - create job immediately.
- `require_approval` - create a linked approval and a `waiting_approval` job; the collector cannot lease it until an administrator approves it.
- `deny` - do not call the API.

The canonical seed policy lives at `src/api/app/policies/farsight-tool-policy.yaml`. It is seeded into the Cosmos DB policy repository on first deploy and editable via the admin console. The gateway always loads the active policy from the FarSight control API (`GET /api/v1/policies/{policyId}`); if the API is unavailable or returns an empty policy the gateway fails closed with an error. No local policy file or fallback evaluator is used in production.

The default policy module allowlist matches the built-in modules currently implemented under `src/modules`: `Get-AppLogBundle`, `Get-AppEventSlice`, `Get-AppHealthSnapshot`, `Test-AppConnectivity`, `Get-ConfigEvidence`, and `Get-ServiceStatusSnapshot`. Extension sample modules are not enabled by default until they are promoted into the built-in module set.

Policy context includes the diagnostic request fields that the gateway forwards to AGT, including `task_type`, `risk_level`, `appId`, `max_bytes`, `max_files`, `time_window_hours`, `redaction_profile`, and `approved_app_log_path`. Rules can key off `appId` directly for app-specific approval or deny decisions.

Policy authors manage versions through the admin web policy repository page. The lifecycle is draft, active, archived. Only validated policies should be activated.

The gateway currently evaluates one configured policy ID, `farsight-tool-policy` by default. The repository can store multiple policy documents so future deployments can separate tool policies by environment, gateway instance, tenant segment, or specialized diagnostic scope. A new policy is not used by the gateway until the gateway is configured to load that policy ID, for example with `FARSIGHT_POLICY_ID`.

## Tool-call monitoring

The admin console includes a Tool-call monitoring page backed by `GET /api/v1/telemetry/tool-calls/summary`. The AGT tool gateway emits a structured audit event (`POST /api/v1/telemetry/tool-calls`) after every tool execution. Each event includes: tool name, policy decision (allow/deny/require_approval), policy name/version, rule name, actor identity (object ID and Entra app ID), job ID, correlation ID, and UTC timestamp. Events are persisted in the `auditEvents` Cosmos container and aggregated by the summary endpoint. The aggregation window is selectable via the `window` query parameter (`24h`, `7d`, `30d`, or `all`; default `24h`), surfaced as a time-window dropdown in the admin console so operators can review historical activity beyond the last 24 hours.

In the tool-call detail view, this actor field is labelled **Actor App ID (Entra)** to distinguish the SRE Agent's Entra application (client) ID from a diagnostic module's `appId` parameter (an application profile name such as `myapp`). The two are unrelated: AGT policy rules that key off `appId` match the module profile parameter, never the actor's Entra app ID.

## Approval behavior

Require approval for broad scope, elevated-risk modules, large artifact requests, or after-hours execution if policy requires it. When a tool response reports `approval_required`, the SRE Agent should not wait synchronously for completion. It should tell the user the request is pending human approval, schedule a later status check on the SRE Agent platform, and use the configured Outlook connector to notify the requester when the job succeeds, is denied/cancelled, fails, or expires.

## Implementation entry point

See `src/agent-tools/gateway/README.md` for local validation, runtime variables, and policy behavior.
