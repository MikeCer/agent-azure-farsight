# Agent tools

FarSight integrates with Azure SRE Agent through governed tools, not a generic command surface. The current gateway is an early FastAPI skeleton for typed tools and AGT policy evaluation.

## Azure SRE Agent setup

Agent tools should expose specific diagnostic actions, not generic job runners. Each tool maps typed inputs to an approved FarSight API request.

## Tool contracts

- Validate input against the tool schema before API calls.
- Include module ID, approved parameters, target selector, idempotency key, and justification.
- Return job metadata and next-step guidance instead of raw sensitive evidence.

## AGT policy wrapping

Evaluate AGT policy before creating jobs:

- `allow` - create job immediately.
- `require_approval` - create or stage job only after approval workflow succeeds.
- `deny` - do not call the API.

## Approval behavior

Require approval for broad scope, elevated-risk modules, large artifact requests, or after-hours execution if policy requires it.

## Known gaps

- Link the deployed Azure SRE Agent configuration, AGT policy bundle, and governed tool registration once available.
