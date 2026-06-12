# FarSight Test Skeleton

This directory mirrors the approved validation strategy in `.azure/plan.md`.

The current content is intentionally a non-destructive skeleton. Test suites will be enabled as implementation appears for the collector, modules, API, broker, telemetry, governance, and extension samples.

## Areas

- `contract/` validates check-in, job, lease, result, artifact, approval, and Azure SRE Agent tool schemas.
- `device-simulator/` covers simulated endpoint check-in/fetch/result loops without requiring Windows pilot devices.
- `e2e/` covers integrated API, broker, collector, and eventual Windows/Intune flows.
- `load/` covers medium-scale check-in cadence, queue depth, Cosmos RU behavior, and API latency.
- `security/` covers mTLS, Entra auth, RBAC, path traversal, artifact bounds, secret redaction, AGT governance, and audit records.
