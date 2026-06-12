# FarSight tool gateway

The FarSight tool gateway exposes typed HTTP endpoints for Azure SRE Agent tools. It is not a command runner and must never accept arbitrary PowerShell, shell commands, script text, or free-form endpoint paths.

## Governance model

The gateway uses Microsoft Agent Governance Toolkit (AGT) as the production policy engine. Every tool function builds an action context and evaluates policy before calling the FarSight control API.

Default policy file:

```text
src/agent-tools/gateway/policies/farsight-tool-policy.yaml
```

Runtime overrides:

| Variable | Purpose |
| --- | --- |
| `FARSIGHT_AGT_POLICY_PATH` | Optional path to an alternative AGT policy file. |
| `FARSIGHT_ALLOW_POLICY_FALLBACK` | Local development/test escape hatch. When `true`, use the deterministic fallback evaluator if AGT is unavailable. Do not enable in production. |

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
pip install -r requirements.txt pytest
FARSIGHT_ALLOW_POLICY_FALLBACK=true pytest tests
```

## Safety rules

- Use named FarSight modules only.
- Pass schema-valid parameters only.
- Do not create generic job runners.
- Retrieve artifact metadata before artifact content.
- Require approval for sensitive diagnostics, broad scope, expanded collection, or higher-risk actions.
