# API

The FarSight control API is an early FastAPI implementation. Contracts below describe the intended V1 shape and current skeleton endpoints; persistence, full identity enforcement, and generated OpenAPI examples are still being completed.

## REST contracts

- `POST /api/v1/jobs` creates a typed diagnostic job.
- `GET /api/v1/jobs/{jobId}` returns job status.
- `POST /api/v1/devices/checkin` lets collectors request pending work.
- `POST /api/v1/jobs/{jobId}/results` submits redacted result envelopes.
- `GET /api/v1/admin/approvals` lists approval requests for the admin console.
- `POST /api/v1/approvals/{approvalId}/decision` approves or denies a pending request and updates linked jobs.
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

### Collector mTLS enforcement and authorization

Collector-facing endpoints now enforce certificate identity binding when `FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH=true`:

- `POST /api/v1/devices/checkin`: certificate subject CN must match request `deviceId`.
- `GET /api/v1/devices/{deviceId}/jobs`: certificate subject CN must match path `deviceId`.
- `GET /api/v1/devices/{deviceId}/policy`: certificate subject CN must match path `deviceId`.
- `GET /api/v1/jobs/{jobId}`: certificate subject CN must match the job owner `deviceId`.
- `POST /api/v1/jobs/{jobId}/results`: certificate subject CN must match both the job owner `deviceId` and result body `deviceId`.

Certificate validation on these paths includes:

- validity period (`notBefore`/`notAfter`);
- Client Authentication EKU;
- certificate must not be a CA certificate;
- key usage must allow digital signature (when key usage extension exists);
- thumbprint allow/deny checks and device ID allow/deny checks;
- trust-chain check against configured trusted CA bundle.

Device mTLS settings:

- `FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH` (`true`/`false`)
- `FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM` (raw PEM bundle or base64-encoded PEM bundle)
- `FARSIGHT_API_REQUIRE_DEVICE_CERT_TRUSTED_CA` (default `true`; fail-closed if trusted CA bundle is missing while mTLS is enforced)
- `FARSIGHT_API_ALLOWED_DEVICE_CERT_THUMBPRINTS` (CSV allowlist; optional)
- `FARSIGHT_API_DENIED_DEVICE_CERT_THUMBPRINTS` (CSV denylist; optional)
- `FARSIGHT_API_ALLOWED_DEVICE_IDS` (CSV allowlist for certificate CN; optional)
- `FARSIGHT_API_DENIED_DEVICE_IDS` (CSV denylist for certificate CN; optional)

### Workload token enforcement for SRE/gateway machine calls

FarSight API machine-to-machine endpoints now support Entra workload-token validation when enabled.

Environment settings:

- `FARSIGHT_API_ENFORCE_WORKLOAD_AUTH=true`
- `FARSIGHT_ENTRA_TENANT_ID=<tenant-guid>` (used for tenant and default issuer/JWKS validation)
- optional `FARSIGHT_ENTRA_ISSUER=<single issuer override>`
- optional `FARSIGHT_ENTRA_ALLOWED_ISSUERS=<csv issuer allowlist>` for explicit issuer control
- `FARSIGHT_API_ALLOWED_AUDIENCES=<csv of accepted audiences>`
- `FARSIGHT_API_ALLOWED_SERVICE_PRINCIPAL_OBJECT_IDS=<csv of allowed SP object IDs>` and/or
- `FARSIGHT_API_REQUIRED_APP_ROLE=<app role value expected in token roles claim>`

Use `scripts/provision-farsight-api-app-registration.py` to create/update the FarSight API app registration and application app role. Grant that role to SRE/AGT managed identities with `src/sre-agent/scripts/grant-farsight-api-access.sh`, or grant AGT-only with `scripts/grant-farsight-agent-tools-api-access.sh`.

When enforcement is enabled, the API validates JWT signature/audience/issuer/tenant using Entra JWKS, requires application workload token claims (`oid`, `appid`/`azp`), blocks delegated `scp` tokens, and then enforces caller allowlist and/or required app role.

## Persistence

The API uses Cosmos DB for durable state when `FARSIGHT_COSMOS_ENDPOINT` is configured. All containers use `DefaultAzureCredential` (managed identity). When the endpoint is not configured, the API falls back to in-memory state for local development.

| Container | Partition key | Used for |
|---|---|---|
| `jobs` | `/deviceId` | Job documents, lease state, result summaries |
| `approvals` | `/approvalId` | Approval requests and decisions |
| `artifactIndex` | `/jobId` | Artifact metadata per job |
| `auditEvents` | `/correlationId` | Policy admin audit trail |
| `investigations` | `/incidentId` | Device investigation history |
| `devices` | `/tenantDeviceId` | Device state, heartbeat, remote config, and last completed job |
| `policies` | `/policyId` | AGT policy versions (managed by `PolicyRepository`) |

Cosmos container name env vars (all default to the container names above):
- `FARSIGHT_COSMOS_JOBS_CONTAINER`
- `FARSIGHT_COSMOS_APPROVALS_CONTAINER`
- `FARSIGHT_COSMOS_ARTIFACT_INDEX_CONTAINER`
- `FARSIGHT_COSMOS_AUDIT_EVENTS_CONTAINER`
- `FARSIGHT_COSMOS_INVESTIGATIONS_CONTAINER`
- `FARSIGHT_COSMOS_POLICIES_CONTAINER`

## Approval-gated jobs

AGT policy can return `require_approval` for sensitive diagnostics or broad read-only collection. In that case, the gateway creates an approval record and a linked job with `status=waiting_approval`, `approvalRequired=true`, `approvalStatus=pending`, and `approvalId=<approval-id>`.

Collectors only lease `Queued` jobs during `/api/v1/devices/checkin`, so `waiting_approval` jobs are not visible to endpoint polling until an administrator approves them. Approval from the admin console changes linked jobs to `Queued`; denial changes linked jobs to `Cancelled` with `approvalStatus=denied`.

Job summary/status responses include approval metadata so SRE tools can stop synchronous waits and schedule follow-up notification.

## Service Bus job queuing (removed)

Service Bus has been removed from the deployment to reduce cost. Job delivery uses Cosmos DB exclusively: the API writes job documents to Cosmos on creation, and the collector discovers pending jobs via `POST /api/v1/devices/checkin` (pull model). This approach is sufficient for the current scale and avoids the Premium tier requirement imposed by private endpoint networking. If durable ordered delivery per device becomes necessary at higher scale, Service Bus can be re-added by setting `FARSIGHT_SERVICE_BUS_NAMESPACE` and restoring the Bicep resources.

## Blob Storage artifacts

Artifact upload uses user-delegation SAS tokens generated by the API (requires the **Storage Blob Delegator** and **Storage Blob Data Contributor** roles on the storage account). The collector calls `POST /api/v1/artifacts/prepare` to receive a short-lived SAS URL, uploads directly to Blob, then calls `POST /api/v1/artifacts/commit` to confirm. If the storage firewall blocks direct endpoint-to-Blob PUT even with SAS, the collector falls back to `POST /api/v1/artifacts/upload`; the API writes the blob with managed identity and the collector then calls commit normally. The canonical blob path is `/{jobId}/{artifactId}/{fileName}`; `fileName` must be included in the commit payload so the API can verify the same blob and store its `blobName` in Cosmos `artifactIndex`. The upload request only sends valid Blob headers (`x-ms-blob-type` plus the standard `Content-Type` set by the collector) so the storage account does not reject the PUT. Artifact content retrieval reads the stored `blobName` first and falls back to the canonical path when needed. The prepare endpoint must be present in the API build; if it is missing, collectors will get a 404 before upload begins.

For raw artifact downloads, the API exposes `GET /api/v1/jobs/{jobId}/artifacts/{artifactId}/download`, which returns the artifact bytes as base64 plus the resolved file name, content type, and size. The SRE Agent uses this for ZIP artifacts before saving them locally and extracting named entries.

Blob env vars (auto-injected by infra):
- `FARSIGHT_BLOB_ACCOUNT_URL` — storage account HTTPS URL
- `FARSIGHT_BLOB_ARTIFACTS_CONTAINER` — blob container name, defaults to `artifacts`

## Device remote configuration

The admin console writes per-device collector configuration into the device document in the Cosmos `devices` container under `pendingConfig`. The API returns that object on the next `/api/v1/devices/checkin` response as `pendingConfig`, and the collector applies it locally before running any job. The collector reports the applied config version back with `appliedConfigVersion`.

If configuration is staged before the first real device heartbeat, the API may create a temporary `unknown:*` placeholder record; the next real check-in deletes that placeholder and keeps the real device document as the source of truth.

When a job result is accepted, the API also stamps `lastJobId` on the matching device document so the admin console can show the most recent completed job immediately.
The device record update uses ISO 8601 timestamps for `updatedAt` so Cosmos writes stay JSON-safe.

The admin console devices grid keeps hostname as the quick UX label, while the device detail modal shows the identifier once and only shows hostname when it differs from the identifier.

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

The AGT tool gateway emits a structured audit event to the FarSight API (`POST /api/v1/telemetry/tool-calls`) after every tool execution. Each event records the tool name, policy decision (allow/deny/require_approval), policy version, actor identity, job ID, correlation ID, and timestamp. Events are persisted in the `auditEvents` Cosmos container with `eventType=tool-call`.

The admin console Tool-call monitoring view queries `GET /api/v1/telemetry/tool-calls/summary` which aggregates the last 24 hours of events into total/allowed/denied/approval-required/failed counts, per-tool breakdowns, and the 50 most recent calls. The endpoint is read-only and must not be used as an authorization control.

Telemetry emission is fire-and-forget from the gateway — a failure to post an audit event does not block or fail the tool call itself. This keeps gateway latency predictable while accepting occasional telemetry loss under transient API failures.

## Known gaps

- Replace the shared-secret BFF-to-API policy mutation signature with Entra service-token validation and persistent audit events.
- Back the tool-call telemetry endpoint with real AGT/tool gateway audit records.
- Publish generated OpenAPI, request/response examples, and finalized error schema once the API stabilizes.
