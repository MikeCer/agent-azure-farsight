# API

The FarSight control API is an early FastAPI implementation. Contracts below describe the intended V1 shape and current skeleton endpoints; persistence, full identity enforcement, and generated OpenAPI examples are still being completed.

## REST contracts

- `POST /api/v1/jobs` creates a typed diagnostic job.
- `GET /api/v1/jobs/{jobId}` returns job status.
- `POST /api/v1/devices/checkin` lets collectors request pending work.
- `POST /api/v1/jobs/{jobId}/results` submits redacted result envelopes.

## Authentication and authorization

- Agent tools use managed identity or an approved service principal.
- Collectors use mTLS-bound device identity.
- Authorization checks module allowlists, device scope, RBAC, AGT policy outcome, and approval state.

## Idempotency

- Clients provide an `Idempotency-Key` for job creation.
- Replayed requests with the same body return the original job.
- Conflicting replays return a typed error.

## Error model

Use stable machine-readable codes such as `invalid_schema`, `policy_denied`, `approval_required`, `module_not_allowed`, `target_not_found`, and `rate_limited`.

## Versioning

- API path version: `/api/v1`.
- Request and result envelopes include `schemaVersion`.
- Breaking schema changes require a new version and migration note.

## Known gaps

- Publish generated OpenAPI, request/response examples, and finalized error schema once the API stabilizes.
