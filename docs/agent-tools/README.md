# Agent tools

FarSight integrates with Azure SRE Agent through governed tools, not a generic command surface. The gateway exposes typed FastAPI endpoints and uses Microsoft Agent Governance Toolkit (AGT) as the production policy engine.

## Azure SRE Agent setup

Agent tools should expose specific diagnostic actions, not generic job runners. Each tool maps typed inputs to an approved FarSight API request.

## Tool contracts

- Validate input against the tool schema before API calls.
- Include module ID, approved parameters, target selector, idempotency key, and justification.
- Return job metadata and next-step guidance instead of raw sensitive evidence.

## AGT policy wrapping

Evaluate AGT policy before every FarSight API call:

- `allow` - create job immediately.
- `require_approval` - block immediate execution and route through the approval workflow.
- `deny` - do not call the API.

The bootstrap policy bundle lives at `src/agent-tools/gateway/policies/farsight-tool-policy.yaml`. The API image carries the same seed policy under `src/api/app/policies/` so a new Cosmos DB policy repository can initialize with the canonical gateway policy. Production gateway instances should use `FARSIGHT_POLICY_SOURCE=api` so the active AGT policy is retrieved from the FarSight API and Cosmos DB `policies` container. The gateway fails closed if AGT or the active policy cannot be loaded; local development can opt into a deterministic fallback evaluator with `FARSIGHT_ALLOW_POLICY_FALLBACK=true`.

Policy authors manage versions through the admin web policy repository page. The lifecycle is draft, active, archived. Only validated policies should be activated.

The gateway currently evaluates one configured policy ID, `farsight-tool-policy` by default. The repository can store multiple policy documents so future deployments can separate tool policies by environment, gateway instance, tenant segment, or specialized diagnostic scope. A new policy is not used by the gateway until the gateway is configured to load that policy ID, for example with `FARSIGHT_POLICY_ID`.

## Tool-call monitoring

The admin console includes a Tool-call monitoring page backed by `GET /api/v1/telemetry/tool-calls/summary`. The initial implementation returns an empty summary. Future gateway work should emit AGT decision events with tool name, actor, policy ID/version, decision, correlation ID, job ID, and timestamp so the API can aggregate calls by tool and decision.

## Approval behavior

Require approval for broad scope, elevated-risk modules, large artifact requests, or after-hours execution if policy requires it.

## Implementation entry point

See `src/agent-tools/gateway/README.md` for local validation, runtime variables, and policy behavior.
