# FarSight tool gateway

The FarSight tool gateway exposes typed HTTP endpoints for Azure SRE Agent tools. It is not a command runner and must never accept arbitrary PowerShell, shell commands, script text, or free-form endpoint paths.

## Governance model

The gateway uses Microsoft Agent Governance Toolkit (AGT) as the production policy engine. Every tool function builds an action context and evaluates policy before calling the FarSight control API.

The active policy is loaded at runtime from the FarSight control API (`GET /api/v1/policies/{policyId}`), which is backed by the Cosmos DB `policies` container. The canonical seed policy lives at `src/api/app/policies/farsight-tool-policy.yaml` — it is seeded into Cosmos DB on first deploy and editable via the admin console. If the API is unavailable or returns an empty policy, the gateway fails closed with an error.

Runtime configuration:

| Variable | Purpose |
| --- | --- |
| `FARSIGHT_API_BASE_URL` | Required. Base URL of the FarSight control API. Used for policy loading and tool forwarding. |
| `FARSIGHT_API_SCOPE` | Token scope for gateway→API managed identity auth. `api://...` normalized to `/.default`. Defaults to `{FARSIGHT_API_BASE_URL}/.default`. |
| `FARSIGHT_POLICY_ID` | Policy ID to load from the repository. Defaults to `farsight-tool-policy`. |
| `FARSIGHT_POLICY_CACHE_TTL_SECONDS` | Cache time for API-loaded policy content. Defaults to 60 seconds. |
| `FARSIGHT_AGENT_TOOLS_ENFORCE_WORKLOAD_AUTH` | Enable inbound JWT validation on `/tools/*` routes. Defaults to `false`. |
| `FARSIGHT_AGENT_TOOLS_ALLOWED_AUDIENCES` | Required when inbound workload auth is enabled. CSV of accepted token audiences for gateway callers. |
| `FARSIGHT_AGENT_TOOLS_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS` | Optional allowlist of caller service principal object IDs (`oid`). |
| `FARSIGHT_AGENT_TOOLS_REQUIRED_APP_ROLE` | Optional required app role claim (`roles`) in caller tokens. |
| `FARSIGHT_AGENT_TOOLS_ALLOWED_ISSUERS` | Optional CSV issuer allowlist for inbound tokens. |
| `FARSIGHT_AGENT_TOOLS_ISSUER` | Optional single issuer override for inbound tokens. |
| `FARSIGHT_AGENT_TOOLS_JWKS_URI` | Optional JWKS URI for inbound token validation. |
| `FARSIGHT_ENTRA_TENANT_ID` | Tenant used for issuer/JWKS defaults when inbound workload auth is enabled. |

Production behavior is fail-closed: if `agent-governance-toolkit-core` is not installed or the policy cannot be loaded from the API, policy evaluation raises an explicit error and the tool call does not proceed.

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
pip install -r requirements.txt  # installs agent-governance-toolkit-core (agentmesh.governance)
python3 -m unittest discover tests/
```

Tests use an inline policy YAML (no API call required) so they run fully offline.

API-backed policy loading and forwarded tool execution both use `FARSIGHT_API_BASE_URL` plus managed identity/API scope configuration.

## Safety rules

- Use named FarSight modules only.
- Pass schema-valid parameters only.
- Do not create generic job runners.
- Retrieve artifact metadata before artifact content.
- Require approval for sensitive diagnostics, broad scope, expanded collection, or higher-risk actions.
