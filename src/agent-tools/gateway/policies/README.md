# FarSight AGT policies

`farsight-tool-policy.yaml` is the default policy loaded by the FarSight tool gateway.

The gateway evaluates each tool call before it reaches the FarSight API. The policy is intentionally conservative:

- unsafe arbitrary execution input is denied;
- unsupported module names are denied;
- read-only lookup tools are allowed;
- sensitive diagnostics require approval;
- read-only diagnostic job creation is allowed only for approved modules.

Set `FARSIGHT_AGT_POLICY_PATH` to load a different policy file at runtime.

The gateway fails closed if Microsoft Agent Governance Toolkit is unavailable. Local development can opt into the deterministic fallback evaluator with:

```bash
export FARSIGHT_ALLOW_POLICY_FALLBACK=true
```
