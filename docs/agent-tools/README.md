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

## AGT policy wrapping

Evaluate AGT policy before every FarSight API call:

- `allow` - create job immediately.
- `require_approval` - block immediate execution and route through the approval workflow.
- `deny` - do not call the API.

The bootstrap policy bundle lives at `src/agent-tools/gateway/policies/farsight-tool-policy.yaml`. The API image carries the same seed policy under `src/api/app/policies/` so a new Cosmos DB policy repository can initialize with the canonical gateway policy. Gateway policy source now defaults to API-backed (`FARSIGHT_POLICY_SOURCE=api`), so if API policy retrieval fails the gateway returns an error (fail closed). Use `FARSIGHT_POLICY_SOURCE=file` only for explicit local/offline development. The gateway fails closed if AGT or the active policy cannot be loaded; local development can opt into a deterministic fallback evaluator with `FARSIGHT_ALLOW_POLICY_FALLBACK=true`.

The default policy module allowlist matches the built-in modules currently implemented under `src/modules`: `Get-AppLogBundle`, `Get-AppEventSlice`, `Get-AppHealthSnapshot`, `Test-AppConnectivity`, `Get-ConfigEvidence`, and `Get-ServiceStatusSnapshot`. Extension sample modules are not enabled by default until they are promoted into the built-in module set.

Policy authors manage versions through the admin web policy repository page. The lifecycle is draft, active, archived. Only validated policies should be activated.

The gateway currently evaluates one configured policy ID, `farsight-tool-policy` by default. The repository can store multiple policy documents so future deployments can separate tool policies by environment, gateway instance, tenant segment, or specialized diagnostic scope. A new policy is not used by the gateway until the gateway is configured to load that policy ID, for example with `FARSIGHT_POLICY_ID`.

## Tool-call monitoring

The admin console includes a Tool-call monitoring page backed by `GET /api/v1/telemetry/tool-calls/summary`. The initial implementation returns an empty summary. Future gateway work should emit AGT decision events with tool name, actor, policy ID/version, decision, correlation ID, job ID, and timestamp so the API can aggregate calls by tool and decision.

## Approval behavior

Require approval for broad scope, elevated-risk modules, large artifact requests, or after-hours execution if policy requires it.

## Implementation entry point

See `src/agent-tools/gateway/README.md` for local validation, runtime variables, and policy behavior.
