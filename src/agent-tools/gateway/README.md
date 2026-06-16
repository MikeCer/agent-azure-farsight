# FarSight tool gateway

The FarSight tool gateway exposes typed HTTP endpoints for Azure SRE Agent tools. It is not a command runner and must never accept arbitrary PowerShell, shell commands, script text, or free-form endpoint paths.

## Governance model

The gateway uses Microsoft Agent Governance Toolkit (AGT) as the production policy engine. Every tool function builds an action context and evaluates policy before calling the FarSight control API.

Default bootstrap policy file:

```text
src/agent-tools/gateway/policies/farsight-tool-policy.yaml
```

By default, the gateway uses `FARSIGHT_POLICY_SOURCE=api` so it retrieves the active policy from the FarSight control API, which is backed by the Cosmos DB `policies` container. If the API/policy cannot be loaded, the gateway fails closed and returns an error. Use `FARSIGHT_POLICY_SOURCE=file` only for explicit local/offline development.

Runtime overrides:

| Variable | Purpose |
| --- | --- |
| `FARSIGHT_POLICY_SOURCE` | Policy source selector. Default is `api` (fail-closed if API unavailable). Set `file` only for explicit local/offline development. |
| `FARSIGHT_POLICY_ID` | Policy ID to load from the repository. Defaults to `farsight-tool-policy`. |
| `FARSIGHT_POLICY_CACHE_TTL_SECONDS` | Cache time for active API-loaded policy content. Defaults to 60 seconds. |
| `FARSIGHT_AGT_POLICY_PATH` | Optional path to an alternative AGT policy file. |
| `FARSIGHT_ALLOW_POLICY_FALLBACK` | Local development/test escape hatch. When `true`, use the deterministic fallback evaluator instead of AGT. Do not enable in production. |
| `FARSIGHT_API_BASE_URL` | Required for API forwarding and API-backed policy loading. Base URL of the FarSight control API that the gateway calls after AGT allow decisions. |
| `FARSIGHT_API_SCOPE` | Optional token scope used by the gateway managed identity when calling FarSight API. `api://...` values are normalized to end with `/.default`. Defaults to `{FARSIGHT_API_BASE_URL}/.default` when omitted. |
| `FARSIGHT_AGENT_TOOLS_ENFORCE_WORKLOAD_AUTH` | Enable inbound JWT validation on `/tools/*` routes. Defaults to `false`. |
| `FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES` | Required when inbound workload auth is enabled. CSV of accepted token audiences for gateway callers. |
| `FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS` | Optional allowlist of caller service principal object IDs (`oid`). At least this or required app role must be configured when auth is enabled. |
| `FARSIGHT_AGENT_TOOLS_REQUIRED_APP_ROLE` | Optional required app role claim (`roles`) in caller tokens. |
| `FARSIGHT_AGENT_TOOLS_ALLOWED_ISSUERS` | Optional CSV issuer allowlist for inbound tokens. Falls back to `FARSIGHT_ENTRA_ALLOWED_ISSUERS` or tenant-derived defaults. |
| `FARSIGHT_AGENT_TOOLS_ISSUER` | Optional single issuer override for inbound tokens. |
| `FARSIGHT_AGENT_TOOLS_JWKS_URI` | Optional JWKS URI for inbound token validation. Falls back to `FARSIGHT_ENTRA_JWKS_URI` or tenant discovery endpoint. |
| `FARSIGHT_ENTRA_TENANT_ID` | Tenant used for issuer/JWKS defaults when inbound workload auth is enabled. |

Production behavior is fail-closed: if AGT cannot be imported or the policy file is missing, policy evaluation raises an explicit error and the tool call does not proceed.

## Policy outcomes

| Outcome | Gateway behavior |
| --- | --- |
| `allow` | The gateway calls the FarSight API. |
| `require_approval` | The gateway blocks immediate execution and returns a policy decision. Approval workflow must be used before the action proceeds. |
| `deny` | The gateway blocks the call and returns a policy decision. |

## Local validation

```bash
cd src/agent-tools/gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest  # installs agent-governance-toolkit-core which provides agentmesh.governance
FARSIGHT_ALLOW_POLICY_FALLBACK=true python3 -m unittest discover tests/  # with fallback
FARSIGHT_POLICY_SOURCE=file python3 -m unittest discover tests/           # with real AGT + local policy file
```

API-backed policy loading and forwarded tool execution both use `FARSIGHT_API_BASE_URL` plus managed identity/API scope configuration so the gateway can call `GET /api/v1/policies/{policyId}` and the FarSight job/approval APIs.

## Safety rules

- Use named FarSight modules only.
- Pass schema-valid parameters only.
- Do not create generic job runners.
- Retrieve artifact metadata before artifact content.
- Require approval for sensitive diagnostics, broad scope, expanded collection, or higher-risk actions.
