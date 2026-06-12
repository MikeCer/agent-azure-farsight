# Data flows

## Job creation

1. Azure SRE Agent tool evaluates AGT policy and approval rules.
2. Tool maps a typed request to `POST /api/v1/jobs`.
3. API validates identity, schema, module allowlist, idempotency key, and requested scope.
4. Job is queued for the target device or group.

## Evidence collection

1. Collector checks in using mTLS.
2. Collector receives only allowlisted module jobs.
3. Module runs read-only diagnostics with typed inputs.
4. Collector redacts results and returns a result envelope.

## Known gaps

- Add sequence diagrams for retries and expired jobs.
