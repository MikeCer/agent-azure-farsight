# API

The FarSight control API is an early FastAPI implementation. Contracts below describe the intended V1 shape and current skeleton endpoints; persistence, full identity enforcement, and generated OpenAPI examples are still being completed.

## REST contracts

- `POST /api/v1/jobs` creates a typed diagnostic job.
- `GET /api/v1/jobs/{jobId}` returns job status.
- `POST /api/v1/devices/checkin` lets collectors request pending work.
- `POST /api/v1/jobs/{jobId}/results` submits redacted result envelopes.
- `GET /api/v1/policies` lists AGT policy documents and versions.
- `GET /api/v1/policies/{policyId}` returns the active AGT policy.
- `POST /api/v1/policies/{policyId}/validate` validates AGT YAML before save or activation.
- `PUT /api/v1/policies/{policyId}/versions/{version}` saves a draft or version.
- `POST /api/v1/policies/{policyId}/versions/{version}/activate` activates a validated version.
- `DELETE /api/v1/policies/{policyId}/versions/{version}` deletes a non-active policy version.
- `GET /api/v1/telemetry/tool-calls/summary` returns the tool-call telemetry summary used by the admin console.

## Authentication and authorization

- Agent tools use managed identity or an approved service principal.
- Collectors use mTLS-bound device identity.
- Authorization checks module allowlists, device scope, RBAC, AGT policy outcome, and approval state.
- Admin policy mutations require signed BFF-to-API admin context derived from Easy Auth. The shared signing secret is `FARSIGHT_API_INTERNAL_AUTH_SECRET` and is stored as a Container Apps secret.
- Policy version metadata (`updatedBy`) stores the propagated admin display name when available (falling back to actor ID).

### Workload token enforcement for SRE/gateway machine calls

FarSight API machine-to-machine endpoints now support Entra workload-token validation when enabled.

Environment settings:

- `FARSIGHT_API_ENFORCE_WORKLOAD_AUTH=true`
- `FARSIGHT_ENTRA_TENANT_ID=<tenant-guid>` (or explicit `FARSIGHT_ENTRA_ISSUER`)
- `FARSIGHT_API_ALLOWED_AUDIENCES=<csv of accepted audiences>`
- `FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS=<csv of allowed SP object IDs>` and/or
- `FARSIGHT_API_REQUIRED_APP_ROLE=<app role value expected in token roles claim>`

Use `scripts/provision-farsight-api-app-registration.py` to create/update the FarSight API app registration and application app role, then grant that role to the SRE managed identity with `src/sre-agent/scripts/grant-farsight-api-access.sh`.

When enforcement is enabled, the API validates JWT signature/issuer/audience using Entra JWKS and then enforces caller allowlist and/or required app role.

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

## Policy repository persistence

Policy repository operations use Cosmos DB when `FARSIGHT_COSMOS_ENDPOINT` is configured. The API uses managed identity through `DefaultAzureCredential` and the `policies` container in the `farsight` database by default. The infrastructure assigns the API managed identity the Cosmos DB built-in data contributor role scoped to the FarSight database. Local development without `FARSIGHT_COSMOS_ENDPOINT` uses a seeded in-memory repository for safe iteration.

## Tool-call telemetry

The initial telemetry endpoint returns an empty, stable shape:

- `window`
- aggregate counts for total, allowed, denied, approval-required, and failed calls;
- `byTool` rows;
- `recent` tool-call rows.

Future implementations should populate this from AGT/tool gateway audit events in Log Analytics, Application Insights, or Cosmos DB. The endpoint is read-only and must not be used as an authorization control.

## Known gaps

- Replace the shared-secret BFF-to-API policy mutation signature with Entra service-token validation and persistent audit events.
- Back the tool-call telemetry endpoint with real AGT/tool gateway audit records.
- Publish generated OpenAPI, request/response examples, and finalized error schema once the API stabilizes.
