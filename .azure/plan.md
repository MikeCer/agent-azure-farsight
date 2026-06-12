# Azure Deployment and Implementation Plan

> **Status:** Executing

Generated: 2026-06-12T12:01:48+02:00

---

## 1. Project Overview

**Goal:** Build Agent-Azure-FarSight, a production-oriented V1 system for governed remote diagnostics of Intune-managed Windows clients. The system uses a PowerShell endpoint collector, a brokered Azure control plane, Azure SRE Agent integration, AGT-governed tools, and auditable approval controls without creating a remote shell.

**Path:** New Project

**Primary design sources:**

| Source | Purpose |
|---|---|
| `Design/azure-sre-collector-design-spec.md` | System architecture, constraints, V1 modules, acceptance criteria |
| `Design/agent-azure-farsight-copilot-planning-prompt.md` | Required planning output, workstreams, contracts, roadmap |
| Azure SRE Agent docs | Azure SRE Agent service model, custom agents, custom tools, knowledge files, review/autonomous modes |
| Agent Governance Toolkit docs | Deterministic tool-call policy enforcement, audit logging, deny/approval outcomes |

---

## 2. Requirements and Confirmed Decisions

| Attribute | Value |
|---|---|
| Classification | Production-oriented V1 |
| Scale | Medium: 1K-100K managed Windows endpoints |
| Budget | Balanced reliability/cost |
| Tenant model | Single Microsoft Entra tenant |
| Subscription | `ME-MngEnv373120-mcerreto-1` (`b4e8dc96-aa76-4fa4-bb90-4dd62234b540`) |
| Tenant | `Contoso` (`b89a7958-64ef-4c1f-b8ee-cccbe097db7f`) |
| Collector/control-plane region | Italy North |
| Azure SRE Agent region | Sweden Central |
| Control API runtime | Azure Container Apps + Python FastAPI |
| Admin/monitoring web app | React + TypeScript frontend served by a lightweight FastAPI/BFF container |
| Admin auth | Microsoft Entra ID sign-in with group/role-based authorization |
| Endpoint runtime | Windows PowerShell 5.1 compatibility first |
| Endpoint deployment | Microsoft Intune platform scripts and Remediations |
| Endpoint execution | Windows Task Scheduler, not a custom service |
| Endpoint auth | Hybrid certificate model: enterprise PKI/SCEP or PKCS for production; guarded enrollment API for dev/pilot |
| Agent governance | Agent Governance Toolkit as primary tool governance layer |
| Secondary approval | Built-in approval API plus Teams notification hook for configurable higher-risk actions |
| Infrastructure workflow | AZD project using Bicep under `infra/` |
| CI/CD | GitHub Actions with `azd` and OIDC federated credentials |
| API exposure | Deployment parameter: public HTTPS for dev/test; private endpoint-capable enterprise topology |
| APIM | Optional deployment parameter; disabled for dev by default |
| Environments | `dev`, `test`, `prod` with parameterized differences |
| Default retention | Configurable defaults: Cosmos jobs 30 days, Log Analytics 90 days, Blob artifacts 30 days |

### Core non-negotiable constraints

- No reverse shell.
- No arbitrary remote PowerShell submitted from cloud to endpoint in V1.
- No inbound endpoint connectivity.
- No compiled endpoint software in V1.
- Endpoint collector executes only named allowlisted modules with schema-validated parameters.
- Large artifacts go to Blob Storage; normalized summaries go to Log Analytics.
- Intune Collect Diagnostics is complementary baseline functionality, not something FarSight duplicates.

---

## 3. Architecture Assumptions and Open Questions

### Assumptions

1. Windows endpoints are Entra joined or hybrid joined and managed by Intune.
2. Intune can distribute scripts, configuration files, module manifests, and certificates or enrollment bootstrap material.
3. The first production deployment is single-tenant and single primary collector region.
4. Italy North is the system-of-record region for device data, job state, approvals, artifacts, and normalized telemetry.
5. Sweden Central hosts the Azure SRE Agent service and the AGT-protected FarSight tool gateway because Azure SRE Agent is not available in Italy North.
6. The Azure SRE Agent uses its system-assigned managed identity for least-privilege access to FarSight dependencies and tool endpoints.
7. The FarSight control API remains the stable contract for devices, admin UI, SRE agent tools, and future integrations.
8. Service Bus is not directly exposed to endpoints or the Azure SRE Agent.
9. Private endpoint support is required for enterprise/prod, but public ingress must remain available as a dev/test deployment mode.
10. V1 focuses on diagnostics and evidence collection. Any remediation capability is explicitly out of scope unless added later behind stricter approval gates.

### Open questions to resolve before infrastructure generation

| Question | Impact | Recommended resolution path |
|---|---|---|
| Exact Azure SRE Agent ARM/Bicep resource type and deployment support | Determines whether SRE Agent is fully deployed by Bicep or configured manually/service-side | Spike during Sprint 1; if ARM support is unavailable, document manual Azure SRE Agent setup and keep FarSight dependencies in Bicep |
| Exact Azure SRE Agent custom tool integration mechanism for FarSight | Determines whether the AGT gateway exposes MCP, custom HTTP tools, runbooks, or a combination | Prefer MCP/custom tool gateway if supported; keep REST API and tool contracts independent |
| Production certificate authority integration | Determines Intune SCEP/PKCS profile requirements and device identity trust chain | Define both production PKI and dev/pilot enrollment flows; select final CA during pilot planning |
| Teams approval implementation target | Determines whether approvals use Power Automate, Teams webhook, Bot Framework, or Logic Apps | Use approval API as source of truth; make Teams notification transport replaceable |
| Private networking topology | Determines VNet, private DNS, APIM internal mode, and Container Apps environment mode | Default public dev topology; add prod private profile with parameterized Bicep |
| First pilot application profiles | Determines module path allowlists, event providers, config profiles, and redaction rules | Collect pilot app IDs, approved paths, event logs, registry keys, and connectivity targets before module hardening |
| Data classification and export rules | Determines artifact encryption, redaction profiles, and retention ceilings | Confirm with security/compliance before production rollout |

---

## 4. Components Detected

| Component | Type | Technology | Path |
|---|---|---|---|
| Design specification | Documentation | Markdown | `Design/azure-sre-collector-design-spec.md` |
| Planning prompt | Documentation | Markdown | `Design/agent-azure-farsight-copilot-planning-prompt.md` |

No implementation code, infrastructure, tests, or deployment configuration currently exists.

---

## 5. Recipe Selection

**Selected:** AZD (Bicep)

**Rationale:**

- User requested Bicep while also selecting AZD as the deployment workflow.
- New multi-component Azure application benefits from `azd` environment management.
- Bicep keeps Azure resource definitions explicit and reviewable.
- GitHub Actions can run `azd provision`, `azd deploy`, and validation with OIDC.
- The repository can still expose direct Bicep module boundaries for security and platform review.

---

## 6. Recommended Target Architecture

**Stack:** Containerized control plane on Azure Container Apps, brokered with Service Bus, durable state in Cosmos DB, artifacts in Blob Storage, telemetry in Log Analytics, agent-side tool governance through AGT.

### Regional topology

| Region | Responsibility |
|---|---|
| Italy North | Device-facing control API, admin/monitoring web app, worker/reconciler, Service Bus, Cosmos DB, Blob artifacts, Log Analytics, App Insights, Key Vault, App Configuration, optional APIM/private endpoints |
| Sweden Central | Azure SRE Agent service, AGT-protected FarSight tool gateway, SRE Agent service-managed resources, optional local observability for the gateway |

### Service mapping

| Component | Azure Service | Recommended SKU/default |
|---|---|---|
| Control API | Azure Container Apps | Consumption profile for dev/test; workload profile for prod if load requires |
| Admin web/BFF | Azure Container Apps | Consumption profile |
| Worker/reconciler | Azure Container Apps | Internal container app or job-style worker |
| AGT tool gateway | Azure Container Apps in Sweden Central | Consumption profile |
| Container images | Azure Container Registry | Standard for dev/test; Premium optional for Private Link/geo-replication |
| Async broker | Azure Service Bus | Standard for V1; Premium optional if throughput/isolation requires |
| Durable state | Azure Cosmos DB for NoSQL | Autoscale provisioned throughput; serverless only for dev |
| Artifact storage | Azure Storage Blob | GPv2, hot tier default, lifecycle to cool/delete |
| Normalized telemetry | Log Analytics + Logs Ingestion API | 90-day default retention, configurable |
| APM | Application Insights | Workspace-based |
| Secrets/certs | Azure Key Vault | RBAC mode, purge protection for prod |
| Runtime config | Azure App Configuration | Standard, Key Vault references, feature flags |
| API edge | Azure API Management | Optional; disabled by default, Standard v2 for prod if enabled |
| Admin auth | Microsoft Entra ID | App registration or Container Apps authentication, group/role claims |
| Device auth | mTLS | Enterprise PKI/SCEP/PKCS for prod; enrollment API for dev/pilot |
| Agent service | Azure SRE Agent | Sweden Central, system-assigned managed identity |

### End-to-end flow

1. SRE operator or Azure SRE Agent identifies a diagnostic hypothesis.
2. Azure SRE Agent invokes the FarSight custom agent/tool gateway in Sweden Central.
3. AGT evaluates tool policy and either allows, denies, or requires approval.
4. If secondary approval is required, the tool gateway creates an approval request through the FarSight API and notifies Teams.
5. Once approved, the control API creates a bounded diagnostic job in Cosmos DB and enqueues metadata to the Service Bus session-enabled jobs queue.
6. The endpoint collector runs by Task Scheduler, checks in over mTLS, fetches one approved job for its device, validates the module and parameters locally, and executes only an allowlisted module.
7. The collector posts structured results to the API and uploads large artifacts directly to Blob Storage with a short-lived signed upload URL.
8. The API updates Cosmos DB, ingests normalized evidence into Log Analytics, and exposes summaries to the admin UI and Azure SRE Agent tools.

---

## 7. Azure Infrastructure in Bicep

### Resource group strategy

| Resource group | Region | Purpose |
|---|---|---|
| `rg-farsight-{env}-itn` | Italy North | Collector/control-plane system of record |
| `rg-farsight-agent-{env}-swc` | Sweden Central | Azure SRE Agent integration and AGT tool gateway |

### Bicep module boundaries

| Module | Resources |
|---|---|
| `infra/bicep/main.bicep` | Orchestrates regional modules, tags, identities, outputs |
| `infra/bicep/modules/container-apps.bicep` | Managed environments, container apps, ingress, revisions, identities |
| `infra/bicep/modules/acr.bicep` | Azure Container Registry, pull permissions |
| `infra/bicep/modules/servicebus.bicep` | Namespace, session-enabled jobs queue, retry/DLQ settings |
| `infra/bicep/modules/cosmos.bicep` | Account, database, containers, TTL, indexing, autoscale |
| `infra/bicep/modules/storage.bicep` | Storage account, blob containers, lifecycle rules, private endpoints optional |
| `infra/bicep/modules/monitoring.bicep` | Log Analytics, App Insights, DCR/DCE for Logs Ingestion API, alerts |
| `infra/bicep/modules/security.bicep` | Key Vault, App Configuration, managed identities, RBAC |
| `infra/bicep/modules/networking.bicep` | Optional VNet, private endpoints, private DNS zones |
| `infra/bicep/modules/apim.bicep` | Optional API Management, APIs, policies, products |
| `infra/bicep/modules/agent-gateway.bicep` | Sweden Central AGT tool gateway app and identity wiring |

### Naming approach

Use deterministic names with short environment and region suffixes:

```text
farsight-{env}-{component}-{regionCode}
rg-farsight-{env}-itn
rg-farsight-agent-{env}-swc
ca-farsight-api-{env}-itn
ca-farsight-admin-{env}-itn
ca-farsight-worker-{env}-itn
ca-farsight-tools-{env}-swc
sb-farsight-{env}-itn
cosmos-farsight-{env}-itn
stfarsight{env}{unique}
kv-farsight-{env}-itn
appcs-farsight-{env}-itn
```

### Key parameters

| Parameter | Purpose | Example/default |
|---|---|---|
| `environmentName` | `dev`, `test`, `prod` | `dev` |
| `collectorLocation` | Control-plane location | `italynorth` |
| `agentLocation` | Azure SRE Agent/tool gateway location | `swedencentral` |
| `enablePublicIngress` | Public HTTPS for dev/test | `true` in dev, `false` in prod private profile |
| `enablePrivateEndpoints` | Private endpoint topology | `false` in dev, `true` in prod |
| `enableApim` | Optional APIM front door | `false` by default |
| `cosmosTtlDaysJobs` | Job retention | `30` |
| `logAnalyticsRetentionDays` | Log retention | `90` |
| `artifactRetentionDays` | Blob lifecycle delete | `30` |
| `enableDevEnrollmentApi` | Dev/pilot certificate enrollment API | `true` in dev/pilot, `false` in prod unless approved |
| `allowedAdminGroupObjectIds` | Admin web authorization | Environment-specific |
| `approvalTeamsWebhookMode` | Teams notification transport | `logicapp`, `webhook`, or `disabled` |

---

## 8. Provisioning Limit Checklist

### Phase 1: Resource Inventory

The planned default deployment uses public HTTPS dev/test ingress and does not deploy optional APIM or private endpoints unless enabled by parameters.

| Resource Type | Region | Number to Deploy | Current Usage | Total After Deployment | Limit/Quota | Notes |
|---|---:|---:|---:|---:|---|---|
| Resource groups | Subscription | 2 | Not region-scoped | Within 980 | 980 per subscription | Official ARM limit |
| Microsoft.App/managedEnvironments | Italy North | 1 | 2 | 3 | QMS-managed regional quota | Current from Azure Resource Graph; quota CLI attempted but returned Microsoft.Quota registration error after provider showed Registered |
| Microsoft.App/containerApps | Italy North | 3 | 4 | 7 | ARM per-type/resource-group limit 800 plus Container Apps env quotas | Apps: API, admin/BFF, worker |
| Microsoft.ContainerRegistry/registries | Italy North | 1 | 2 | 3 | ACR SKU capacity; ARM per-type/resource-group limit 800 | Standard SKU for balanced default |
| Microsoft.ServiceBus/namespaces | Italy North | 1 | 0 | 1 | 1000 namespaces per subscription per region | Official Service Bus limit |
| Microsoft.DocumentDB/databaseAccounts | Italy North | 1 | 4 | 5 | 250 accounts per subscription default | Official Cosmos DB account limit source; Cosmos quota CLI unsupported/unstable |
| Microsoft.Storage/storageAccounts | Italy North | 1 | 3 | 4 | 250 storage accounts per region by default | Official Azure Storage limit |
| Microsoft.OperationalInsights/workspaces | Italy North | 1 | 5 | 6 | ARM per-type/resource-group limit 800; ingestion limits apply | Logs Ingestion API limits: 1 MB call, 12,000 requests/minute/DCR, 2 GB/minute/DCR |
| Microsoft.Insights/components | Italy North | 1 | 2 | 3 | ARM per-type/resource-group limit 800 | Workspace-based Application Insights |
| Microsoft.KeyVault/vaults | Italy North | 1 | 1 | 2 | No object count limit; transaction limits apply | Standard vault, RBAC mode |
| Microsoft.AppConfiguration/configurationStores | Italy North | 1 | 0 | 1 | Unlimited stores for Standard/Premium tier; Free limited to 1 per region | Standard tier recommended |
| Microsoft.ApiManagement/service | Italy North | 0 default / 1 optional | 0 | 0 default / 1 optional | Tier-specific API operation limits | Optional; disabled for dev |
| Microsoft.Network/virtualNetworks | Italy North | 0 default / 1 optional | 5 | 5 default / 6 optional | ARM per-type/resource-group limit 800 | Optional private topology |
| Microsoft.Network/privateEndpoints | Italy North | 0 default / 6 optional | 5 | 5 default / 11 optional | Service-specific private endpoint limits apply | Optional Storage, Cosmos, Key Vault, App Config, ACR Premium, APIM |
| Microsoft.App/managedEnvironments | Sweden Central | 1 | 0 | 1 | QMS-managed regional quota | Tool gateway environment |
| Microsoft.App/containerApps | Sweden Central | 1 | 0 | 1 | ARM per-type/resource-group limit 800 plus Container Apps env quotas | AGT-protected FarSight tool gateway |
| Microsoft.OperationalInsights/workspaces | Sweden Central | 1 | 2 | 3 | ARM per-type/resource-group limit 800; ingestion limits apply | Tool gateway observability; Azure SRE Agent may create its own workspace |
| Microsoft.Insights/components | Sweden Central | 1 | 2 | 3 | ARM per-type/resource-group limit 800 | Tool gateway App Insights; Azure SRE Agent may create its own instance |
| Microsoft.KeyVault/vaults | Sweden Central | 1 | 1 | 2 | No object count limit; transaction limits apply | Gateway policy secrets/config refs if needed |
| Azure SRE Agent service | Sweden Central | 1 | Service-specific | Service-specific | Region and tenant availability varies | Azure SRE Agent docs state service creates Application Insights, Log Analytics workspace, and managed identity |

### Phase 2: Quota validation status

| Check | Result |
|---|---|
| Azure CLI quota extension installed | Completed |
| Microsoft.Quota provider registration attempted | Completed; provider state reported `Registered` |
| `az quota list` for Microsoft.App, Microsoft.Network, Microsoft.Storage, Microsoft.Compute in Italy North and Sweden Central | Failed with `MissingRegistrationForResourceProvider` despite provider state `Registered` |
| Fallback current usage source | Azure Resource Graph resource counts |
| Fallback limit source | Official Microsoft Learn service limits pages |
| Capacity status for planning | Within published static limits and low regional resource counts |
| Mandatory deployment preflight | Re-run `az quota list` or validate through Azure Portal QMS before first production deployment, especially for Container Apps managed environment and core quotas |

---

## 9. Workstreams

### 9.1 Repository foundation and developer workflow

- Create monorepo structure for endpoint collector, modules, API, agent tools, admin web, infrastructure, policies, tests, samples, and docs.
- Add `azure.yaml` for AZD environments.
- Add devcontainer or setup scripts only if the implementation team wants reproducible local tooling.
- Define shared conventions for JSON schema, correlation IDs, structured logging, and API versioning.

### 9.2 Endpoint collector

- Implement `bootstrap.ps1` to create `C:\ProgramData\Company\SreCollector`, scheduled tasks, config, module manifest, logs, local state, and self-heal hooks.
- Implement `collector.ps1` as a single-run scheduled execution, not a daemon.
- Add local lock file to avoid overlapping runs.
- Add check-in, job fetch, lease acknowledgement, module invocation, result upload, and local audit logging.
- Add retry/backoff for HTTP operations.
- Enforce local allowlist, module hash checks, schema validation, timeout, artifact cap, and redaction.
- Support PowerShell 5.1 first.

### 9.3 PowerShell modules

V1 module sequence:

1. `Get-AppLogBundle`
2. `Get-AppEventSlice`
3. `Get-AppHealthSnapshot`
4. `Test-AppConnectivity`
5. `Get-ConfigEvidence`

Each module must include:

- Manifest entry with version, risk tier, content hash, timeout, maximum artifact size, and allowed parameter schema.
- Pester unit tests.
- Sample input/output contract tests.
- Redaction tests.
- Failure-mode tests for invalid paths, invalid event logs, oversized results, and timeout.

### 9.4 Control API

- Implement Python FastAPI service with OpenAPI contract.
- Expose versioned routes under `/api/v1`.
- Enforce request validation and idempotency keys for job creation/result upload.
- Separate device mTLS routes from admin/agent Entra-authenticated routes.
- Implement device check-in, policy retrieval, job retrieval, result ingestion, artifact prepare/commit, approval decision, admin configuration, and summary APIs.
- Use managed identity for Cosmos DB, Service Bus, Storage, App Configuration, Key Vault, and Logs Ingestion API.

### 9.5 Broker and orchestration

- Use one session-enabled Service Bus queue named `jobs`.
- Use `deviceId` as the session ID.
- Queue messages contain routing metadata only; Cosmos DB is authoritative state.
- API creates job state transactionally enough for V1: write Cosmos job, then enqueue command metadata with correlation ID.
- Worker/reconciler handles stale leases, expired jobs, dead-letter monitoring, retries, and telemetry normalization retries.

### 9.6 Cosmos DB state model

Recommended containers:

| Container | Partition key | TTL | Purpose |
|---|---|---:|---|
| `devices` | `/tenantDeviceId` | None or long retention | Device registration, certificate thumbprints, policy version, heartbeat summary |
| `jobs` | `/deviceId` | Configurable, default 30 days after terminal state | Job lifecycle and lease state |
| `approvals` | `/approvalId` | Configurable, default 90 days | Approval requests, decisions, reviewer, evidence |
| `manifests` | `/manifestId` | None | Approved module catalog and hashes |
| `policies` | `/policyId` | None plus version history | Cloud policy and endpoint policy snapshots |
| `investigations` | `/incidentId` | Configurable, default 90 days | Agent-visible investigation timeline and prior history |
| `artifactIndex` | `/jobId` | Configurable, default 30 days | Blob references, hashes, sizes, retention |
| `auditEvents` | `/correlationId` | Configurable, default 180 days | Control-plane and governance audit pointers |

Use optimistic concurrency with ETags for job lease transitions.

### 9.7 Telemetry and Log Analytics

- Use Logs Ingestion API with DCR/DCE for normalized custom tables.
- Store summaries and searchable evidence only; never send large raw bundles to Log Analytics.
- Recommended custom tables:
  - `FarSightCollectorHealth_CL`
  - `FarSightJobLifecycle_CL`
  - `FarSightModuleSummary_CL`
  - `FarSightAppEvents_CL`
  - `FarSightConnectivity_CL`
  - `FarSightConfigEvidence_CL`
  - `FarSightApprovalAudit_CL`
  - `FarSightGovernanceDecision_CL`
- Add KQL queries and workbook definitions under `docs/kql` or `infra/monitoring`.

### 9.8 Blob artifact handling

- Use private blob containers with no public anonymous access.
- Use short-lived user delegation SAS or service-generated upload URLs for collector uploads.
- Require artifact prepare and commit workflow.
- Store artifact metadata, hashes, expected size, content type, retention expiration, and redaction status in Cosmos DB.
- Apply lifecycle delete policy from configurable retention.

### 9.9 Azure SRE Agent integration

- Configure a FarSight custom agent in Azure SRE Agent in Sweden Central.
- Upload FarSight architecture docs, runbooks, tool contracts, policy descriptions, and KQL examples as Azure SRE Agent knowledge files.
- Expose FarSight tools through an AGT-protected tool gateway or supported Azure SRE Agent custom tool mechanism.
- Azure SRE Agent tools authenticate using the agent system-assigned managed identity.
- The FarSight API authorizes tool calls by managed identity, tool name, action risk, tenant scope, and policy result.
- Use Review mode for incident response plans involving higher-risk actions; autonomous mode only for read-only, preapproved collection.

### 9.10 Governance and approvals

- AGT is the primary deterministic policy layer around FarSight tools.
- Tool gateway evaluates AGT policy before calling the FarSight API.
- Policy outcomes:
  - `allow`: call proceeds.
  - `deny`: call is blocked and audited.
  - `require_approval`: approval request is created and no device job is released until approved.
- Secondary approval API is the source of truth for human approval decisions.
- Teams notification is a configurable approval notification channel, not the authoritative decision store.

### 9.11 Admin/monitoring web app

- React + TypeScript frontend served by FastAPI/BFF in Azure Container Apps.
- Entra ID sign-in with group/role-based authorization.
- V1 pages:
  - dashboard: collector health, job latency, failures, DLQ, artifact volume
  - device details and heartbeat
  - job search and details
  - approval queue and decision history
  - module catalog and policy versions
  - retention/network/APIM/configuration view
  - KQL/query shortcuts
- Admin writes go through the same control API authorization and audit pipeline.

### 9.12 Intune packaging and remediation

- Package bootstrap, collector, common module, module catalog, config, and remediation scripts.
- Provide Intune deployment documentation and sample assignment rings.
- Use Remediations for collector health detection/repair.
- Keep Intune as deployment and self-heal channel, not as the dynamic command bus.

### 9.13 Security and identity

- Device-to-API: mTLS, device certificate thumbprint registered to device identity, revocation supported.
- Admin-to-web/API: Entra ID, group claims, least-privilege roles.
- Agent-to-tool/API: Azure SRE Agent managed identity and RBAC-scoped authorization.
- Service-to-service: managed identities only; no connection strings in code.
- Secrets/certificates: Key Vault; App Configuration references Key Vault.
- Endpoint enforcement: manifest allowlist, hashes, bounded schemas, path allowlists, timeouts, redaction, local audit.
- Cloud enforcement: AGT policy, approval gates, API validation, RBAC, audit trail, immutable-ish append audit pattern.

### 9.14 Observability and operations

- Metrics:
  - collector heartbeat success/failure
  - check-in latency
  - queued job age
  - dispatch-to-start latency
  - module duration and failure rate
  - result upload latency
  - artifact upload size/rate
  - Logs Ingestion API failures
  - Service Bus DLQ count
  - approval wait time
  - AGT deny/approval rates
- Alerts:
  - high DLQ count
  - missing heartbeats by device ring
  - high module failure rate
  - stale leases
  - artifact upload failures
  - API 5xx/latency
  - Cosmos RU throttling
  - Service Bus queue depth

### 9.15 Documentation

- Produce complete system documentation as Markdown under `docs/`.
- Treat documentation as an implementation deliverable, not an afterthought; each component PR should update the related docs.
- Required documentation set:
  - `docs/README.md` - documentation index and learning path.
  - `docs/architecture/` - architecture overview, regional topology, data flows, trust boundaries, decision records.
  - `docs/api/` - REST API contracts, OpenAPI usage, auth model, idempotency, error model, versioning.
  - `docs/collector/` - endpoint folder layout, scheduled task model, config, local state, logging, troubleshooting.
  - `docs/modules/` - V1 module catalog, module contract, parameter schema rules, result envelope, redaction rules.
  - `docs/agent-tools/` - Azure SRE Agent custom agent setup, tool contracts, AGT policy wrapping, approval behavior.
  - `docs/intune/` - deployment scripts, assignment rings, Remediations, certificate deployment, pilot rollout.
  - `docs/security/` - threat model, identity/RBAC, mTLS, approvals, artifact protection, audit trail, data retention.
  - `docs/operations/` - dashboards, alerts, KQL queries, runbooks, backup/restore, incident response.
  - `docs/development/` - local setup, coding standards, testing, CI/CD, release process.
  - `docs/extension-guide/` - end-to-end guidance for extending the collector and Azure SRE Agent tools.
- Store generated diagrams in Markdown-friendly Mermaid form and keep the PowerPoint deck as presentation material only.
- Include documentation validation in CI where practical: link checks, Markdown linting if adopted, Mermaid render validation, and OpenAPI/schema consistency checks.

### 9.16 Extension samples and developer experience

- Provide working samples that show how to extend FarSight safely without weakening the no-shell model.
- Required extension sample: add a new read-only diagnostic module and corresponding Azure SRE Agent tool.
- The sample must include:
  - PowerShell module folder under `samples/extensions/collector-module/`.
  - Module manifest entry with version, risk tier, timeout, max artifact size, script hash placeholder, and schema reference.
  - Input schema and sample valid/invalid payloads.
  - Result envelope examples with findings, summary, and optional artifact metadata.
  - Pester tests for validation, redaction, timeout, and failure handling.
  - Tool gateway sample under `samples/extensions/agent-tool/` showing AGT policy evaluation, API call mapping, managed identity assumptions, and approval behavior.
  - AGT policy example under `samples/extensions/policies/` for `allow`, `deny`, and `require_approval` outcomes.
  - API registration/configuration example showing how the tool maps to `POST /api/v1/jobs` or follow-up job creation.
  - Documentation walkthrough under `docs/extension-guide/adding-a-diagnostic-module.md`.
- The sample module must be intentionally harmless and read-only, for example `Get-AppDiskEvidence` or `Get-AppCertificateEvidence`, and must demonstrate allowlisted paths/profiles rather than free-form input.
- Include a checklist for adding future modules: schema, manifest, code, tests, redaction, policy, agent tool, docs, KQL, and rollout approval.

---

## 10. Contracts and Schemas

### 10.1 Device check-in request

```json
{
  "schemaVersion": "1.0",
  "deviceId": "aad-device-guid",
  "tenantId": "tenant-guid",
  "collectorVersion": "0.1.0",
  "manifestVersion": "2026-06-12.1",
  "hostnameHash": "sha256:...",
  "os": {
    "name": "Windows",
    "version": "10.0.26100"
  },
  "lastJobId": "job-20260612-0001",
  "localState": {
    "lastRunUtc": "2026-06-12T10:00:00Z",
    "lastExitCode": 0,
    "pendingArtifactCount": 0
  }
}
```

### 10.2 Device check-in response

```json
{
  "schemaVersion": "1.0",
  "serverTimeUtc": "2026-06-12T10:01:00Z",
  "policyVersion": "2026-06-12.1",
  "manifestVersion": "2026-06-12.1",
  "nextCheckInAfterSeconds": 300,
  "jobAvailable": true,
  "job": {
    "jobId": "job-20260612-0001",
    "leaseToken": "opaque-token",
    "leaseUntilUtc": "2026-06-12T10:11:00Z"
  }
}
```

### 10.3 Job document

```json
{
  "id": "job-20260612-0001",
  "jobId": "job-20260612-0001",
  "deviceId": "aad-device-guid",
  "incidentId": "inc-12345",
  "correlationId": "corr-20260612-abc",
  "taskType": "Get-AppLogBundle",
  "parameters": {
    "appId": "contoso-app",
    "pathProfile": "default",
    "startTime": "2026-06-12T08:00:00Z",
    "endTime": "2026-06-12T09:00:00Z",
    "maxBytes": 10485760
  },
  "riskLevel": "read-only",
  "approvalRequired": false,
  "approvalStatus": "not-required",
  "status": "Queued",
  "policyVersion": "2026-06-12.1",
  "manifestVersion": "2026-06-12.1",
  "createdAtUtc": "2026-06-12T09:05:00Z",
  "expiresAtUtc": "2026-06-12T10:05:00Z",
  "lease": null,
  "retryCount": 0,
  "requestedBy": {
    "kind": "azure-sre-agent",
    "identityObjectId": "managed-identity-object-id",
    "toolName": "create_diagnostic_job"
  }
}
```

### 10.4 Job lease model

```json
{
  "leaseTokenHash": "sha256:...",
  "leasedByDeviceId": "aad-device-guid",
  "leasedAtUtc": "2026-06-12T10:01:00Z",
  "leaseUntilUtc": "2026-06-12T10:11:00Z",
  "attempt": 1
}
```

### 10.5 Module manifest

```json
{
  "manifestVersion": "2026-06-12.1",
  "modules": [
    {
      "name": "Get-AppLogBundle",
      "version": "0.1.0",
      "riskLevel": "read-only",
      "scriptPath": "modules/Get-AppLogBundle.ps1",
      "sha256": "hex-hash",
      "timeoutSeconds": 120,
      "maxArtifactBytes": 10485760,
      "allowedPathProfiles": ["default"],
      "schemaRef": "schemas/Get-AppLogBundle.input.schema.json"
    }
  ]
}
```

### 10.6 Module result envelope

```json
{
  "schemaVersion": "1.0",
  "jobId": "job-20260612-0001",
  "deviceId": "aad-device-guid",
  "correlationId": "corr-20260612-abc",
  "module": "Get-AppLogBundle",
  "status": "Succeeded",
  "startedAtUtc": "2026-06-12T10:02:00Z",
  "completedAtUtc": "2026-06-12T10:03:20Z",
  "summary": {
    "filesMatched": 4,
    "recordsParsed": 1532,
    "warnings": 1
  },
  "findings": [
    {
      "severity": "High",
      "code": "APP_TIMEOUT_PATTERN",
      "message": "42 timeout exceptions observed in ApiWorker.log"
    }
  ],
  "artifacts": [
    {
      "artifactId": "art-001",
      "kind": "zip",
      "name": "contoso-app-logs-20260612.zip",
      "sha256": "hex-hash",
      "sizeBytes": 2048000
    }
  ],
  "nextSuggestedModules": ["Get-AppEventSlice", "Test-AppConnectivity"]
}
```

### 10.7 Artifact prepare/commit workflow

```json
{
  "prepareRequest": {
    "jobId": "job-20260612-0001",
    "artifactId": "art-001",
    "fileName": "contoso-app-logs-20260612.zip",
    "contentType": "application/zip",
    "sizeBytes": 2048000,
    "sha256": "hex-hash"
  },
  "prepareResponse": {
    "uploadUrl": "https://storage/...short-lived-sas...",
    "expiresAtUtc": "2026-06-12T10:13:20Z",
    "requiredHeaders": {
      "x-ms-blob-type": "BlockBlob"
    }
  },
  "commitRequest": {
    "jobId": "job-20260612-0001",
    "artifactId": "art-001",
    "uploaded": true,
    "sha256": "hex-hash"
  }
}
```

### 10.8 Approval request and decision

```json
{
  "approvalRequest": {
    "approvalId": "apr-20260612-0001",
    "correlationId": "corr-20260612-abc",
    "requestedAction": "Start-AppTraceWindow",
    "riskLevel": "sensitive-diagnostic",
    "requestedBy": "azure-sre-agent",
    "reason": "Need bounded trace to confirm intermittent TLS handshake failure",
    "expiresAtUtc": "2026-06-12T11:00:00Z"
  },
  "decision": {
    "approvalId": "apr-20260612-0001",
    "decision": "approved",
    "decidedBy": "user-or-group-object-id",
    "decidedAtUtc": "2026-06-12T10:20:00Z",
    "comment": "Approved for pilot device only"
  }
}
```

### 10.9 Azure SRE Agent tool interfaces

| Tool | Risk | Approval | API mapping |
|---|---|---|---|
| `create_diagnostic_job` | read-only to sensitive depending on module | Policy-driven | `POST /api/v1/jobs` |
| `get_job_status` | read-only | No | `GET /api/v1/jobs/{jobId}` |
| `get_job_result_summary` | read-only | No | `GET /api/v1/jobs/{jobId}/summary` |
| `retrieve_artifact_metadata` | metadata read | Optional for sensitive artifact types | `GET /api/v1/jobs/{jobId}/artifacts` |
| `request_follow_up_module_execution` | read-only to sensitive | Policy-driven | `POST /api/v1/jobs/{jobId}/followups` |
| `request_approval_for_action` | approval workflow | No, creates approval | `POST /api/v1/approvals` |
| `query_device_investigation_history` | read-only | No | `GET /api/v1/devices/{deviceId}/investigations` |
| `query_farsight_kql_summary` | read-only | No | Log Analytics query via API-managed allowlisted KQL |

---

## 11. Recommended Repo Structure

```text
agent-azure-farsight/
  .azure/
    plan.md
  azure.yaml
  src/
    collector/
      bootstrap.ps1
      collector.ps1
      common.psm1
      healthcheck.ps1
      repair.ps1
      config/
      schemas/
    modules/
      Get-AppLogBundle/
      Get-AppEventSlice/
      Get-AppHealthSnapshot/
      Test-AppConnectivity/
      Get-ConfigEvidence/
    api/
      app/
      tests/
      Dockerfile
    admin-web/
      frontend/
      bff/
      Dockerfile
    agent-tools/
      gateway/
      policies/
      tests/
      Dockerfile
  infra/
    bicep/
      main.bicep
      main.parameters.json
      modules/
    monitoring/
      kql/
      workbooks/
  policies/
    agt/
    endpoint/
    redaction/
    approvals/
  docs/
    README.md
    architecture/
      overview.md
      data-flows.md
      trust-boundaries.md
      architecture-diagrams.md
      decisions/
    runbooks/
    intune/
    api/
      openapi.md
      error-model.md
    collector/
      overview.md
      configuration.md
      troubleshooting.md
    modules/
      catalog.md
      module-contract.md
      redaction.md
    agent-tools/
      azure-sre-agent-setup.md
      tool-contracts.md
      governance.md
    security/
      threat-model.md
      identity-and-rbac.md
      data-protection.md
    operations/
      dashboards.md
      alerts.md
      kql.md
    development/
      local-setup.md
      testing.md
      release-process.md
    extension-guide/
      overview.md
      adding-a-diagnostic-module.md
      adding-an-agent-tool.md
    presentations/
  tests/
    contract/
    e2e/
    load/
    security/
    device-simulator/
  samples/
    extensions/
      collector-module/
        Get-AppDiskEvidence/
          Get-AppDiskEvidence.ps1
          manifest.fragment.json
          input.schema.json
          valid-input.json
          invalid-input.json
          expected-result.json
          tests/
      agent-tool/
        create_app_disk_evidence_job.py
        tool-contract.json
        README.md
      policies/
        agt-extension-policy.yaml
    intune/
    module-inputs/
    policies/
    kql/
  .github/
    workflows/
```

---

## 12. Security Model

### Dual-control design

| Layer | Control |
|---|---|
| Agent/tool layer | AGT policy evaluates every tool call before the FarSight API is called |
| Approval layer | Secondary approval API and Teams notification gate configurable higher-risk actions |
| API layer | Entra/managed identity authorization, mTLS validation, request schema validation, idempotency, audit |
| Broker layer | Service Bus sessions, retry limits, DLQ monitoring; no endpoint direct queue access |
| State layer | Cosmos ETags for lease concurrency; TTL for data minimization |
| Endpoint layer | Manifest allowlist, script hashes, parameter schemas, path/provider/URL allowlists, timeouts, size limits |
| Artifact layer | Signed upload URLs, private containers, hash verification, lifecycle deletion |
| Operations layer | Log Analytics, App Insights, KQL workbook, alerts, audit events |

### Roles

| Role | Capabilities |
|---|---|
| FarSight Reader | View dashboard, jobs, summaries, non-sensitive metadata |
| FarSight Operator | Create approved read-only diagnostic jobs |
| FarSight Approver | Approve configured higher-risk diagnostic requests |
| FarSight Admin | Manage module catalog, policies, retention, network/APIM configuration |
| Azure SRE Agent MI | Invoke AGT-governed tool gateway and read/write only allowed FarSight APIs |
| Collector device certificate | Check in, fetch jobs for own device, submit own results/artifacts |

---

## 13. Delivery Roadmap

### MVP

- Repo structure and CI skeleton.
- AZD/Bicep baseline for Italy North control plane and Sweden Central tool gateway.
- Control API with check-in, job create/fetch, result ingestion, and simple summaries.
- Cosmos DB state containers.
- Service Bus session-enabled jobs queue.
- Collector bootstrap and scheduled execution.
- First two modules: `Get-AppLogBundle`, `Get-AppEventSlice`.
- Dev/pilot certificate enrollment flow.
- Basic Log Analytics custom tables.
- Initial `docs/` documentation index, architecture overview, API contracts, collector overview, and development setup.
- First extension sample skeleton showing a read-only collector module plus matching AGT-governed agent tool.

### Pilot

- Add `Get-AppHealthSnapshot`, `Test-AppConnectivity`, `Get-ConfigEvidence`.
- Add Blob artifact prepare/commit workflow.
- Add admin/monitoring web app.
- Add AGT tool gateway and Azure SRE Agent custom agent configuration.
- Add secondary approval API and Teams notification hook.
- Add Intune Remediations healthcheck/repair.
- Complete extension guide with a tested sample module, sample agent tool, policy examples, and rollout checklist.
- Expand Markdown documentation for security, operations, Intune deployment, and troubleshooting.
- Pilot with defined app profiles and device rings.

### Hardening

- Production PKI/SCEP/PKCS integration.
- Private endpoint topology and optional APIM.
- Expanded redaction policies and data classification controls.
- Load and soak testing for check-in/job/result flow.
- Cosmos RU tuning, partition validation, and queue failure testing.
- Security tests, policy tests, and audit validation.
- Documentation quality gate for Mermaid rendering, OpenAPI/schema consistency, and extension sample correctness.

### Production readiness

- Disaster recovery and backup/restore runbooks.
- Operational dashboards and alert tuning.
- Final Azure SRE Agent runbooks, knowledge files, and response plans.
- Complete operator, admin, developer, and extension-author documentation in `docs/`.
- Change management and support model.
- Production deployment gates and rollout rings.

---

## 14. Prioritized Backlog

### Epics

1. Foundation and deployment automation
2. Endpoint collector framework
3. Diagnostic module catalog
4. Control API and brokered job lifecycle
5. Durable state and telemetry
6. Artifact handling
7. Azure SRE Agent and AGT governance
8. Admin/monitoring web app
9. Security, identity, and approvals
10. Intune packaging and pilot rollout
11. Documentation and extension samples

### First implementation stories

| Priority | Story |
|---:|---|
| P0 | As an operator, I can deploy the baseline Azure control plane with AZD/Bicep into dev. |
| P0 | As an endpoint, I can check in over HTTPS/mTLS-compatible contract and receive no-op policy. |
| P0 | As an operator, I can create a bounded diagnostic job for a device. |
| P0 | As a collector, I can fetch one leased job and enforce module allowlist validation. |
| P0 | As an operator, I can see job lifecycle and module summary in Cosmos/Log Analytics. |
| P1 | As an endpoint, I can upload large artifacts through prepare/commit URLs. |
| P1 | As an admin, I can configure retention and module policy through the web app. |
| P1 | As the Azure SRE Agent, I can call AGT-governed FarSight tools using managed identity. |
| P1 | As an approver, I can approve or deny higher-risk actions from a Teams-notified workflow. |
| P1 | As a developer, I can follow Markdown documentation in `docs/` to understand, deploy, operate, and troubleshoot the system. |
| P1 | As an extension author, I can follow a working sample to add a safe collector module and corresponding Azure SRE Agent tool. |

### Spikes

- Azure SRE Agent Bicep/ARM deployment support and custom tool configuration.
- Azure SRE Agent MCP/custom tool authentication model with managed identity.
- Enterprise PKI/SCEP/PKCS integration details for device mTLS.
- Container Apps private endpoint/internal environment topology with dev/prod parameter switch.
- APIM optional front-door value versus Container Apps ingress-only.

---

## 15. Testing Strategy

| Test type | Scope |
|---|---|
| PowerShell unit tests | Module parameter validation, allowlists, redaction, output envelopes |
| Collector integration tests | Locking, retries, local state, manifest hash validation, job execution |
| API unit tests | Request validation, authorization, idempotency, state transitions |
| Contract tests | Check-in, job, lease, result, artifact, approval, tool schemas |
| Device simulator E2E | Simulated check-in/fetch/result loops without Windows endpoint dependency |
| Windows E2E | Intune-deployed collector on pilot devices or test VMs |
| Queue failure tests | DLQ, duplicate messages, stale leases, expired jobs |
| Cosmos concurrency tests | ETag lease transitions, retry conflicts, partition-key correctness |
| Telemetry tests | Logs Ingestion API transformations and KQL query shape |
| Security tests | mTLS validation, Entra auth, RBAC, path traversal, oversized artifacts, secret redaction |
| Governance tests | AGT allow/deny/require_approval policy outcomes and audit records |
| Bicep validation | `azd package`, `azd provision --preview`, `az deployment what-if`, Bicep lint |
| Load tests | Medium-scale check-in cadence, queue depth, Cosmos RU, API latency |
| Documentation tests | Markdown link checks, Mermaid render validation, generated OpenAPI/schema consistency |
| Extension sample tests | Sample collector module tests, sample tool contract tests, AGT policy outcome tests |

---

## 16. First Two Weeks Execution Plan

### Week 1

| Day | Focus | Outcome |
|---:|---|---|
| 1 | Repo skeleton and architecture decisions | Folder structure, coding standards, schema conventions, ADRs |
| 2 | AZD/Bicep baseline | Resource groups, Container Apps envs, ACR, Log Analytics, App Insights, Key Vault, App Config |
| 3 | Cosmos and Service Bus | Containers, partition keys, TTL, session-enabled jobs queue, RBAC |
| 4 | API skeleton | FastAPI routes, OpenAPI, health, auth placeholders, Cosmos repository |
| 5 | Collector skeleton | Bootstrap layout, scheduled task definition, config, local logging, no-op check-in |

### Week 2

| Day | Focus | Outcome |
|---:|---|---|
| 6 | Job lifecycle | Create job, enqueue, check-in response, lease model |
| 7 | Result ingestion | Result envelope, state transitions, basic Log Analytics ingestion |
| 8 | First module | `Get-AppEventSlice` with schema, Pester tests, bounded `Get-WinEvent` |
| 9 | First artifact path | `Get-AppLogBundle` summary plus initial zip artifact prepare/commit |
| 10 | End-to-end demo | Simulated device completes a bounded job; dashboard/API can show lifecycle summary |

### Documentation and samples during first two weeks

- Create `docs/README.md`, `docs/architecture/overview.md`, `docs/api/openapi.md`, `docs/collector/overview.md`, and `docs/development/local-setup.md` while creating the corresponding implementation skeletons.
- Create `docs/extension-guide/overview.md` and a sample extension scaffold under `samples/extensions/` before the first module implementation is considered complete.
- Keep docs and samples aligned with implementation changes in the same pull requests.

---

## 17. Execution Checklist

### Phase 1: Planning

- [x] Analyze workspace
- [x] Gather requirements
- [x] Confirm subscription and location with user/current Azure CLI context
- [x] Prepare resource inventory
- [x] Attempt quota CLI and document fallback validation
- [x] Scan codebase
- [x] Select recipe
- [x] Plan architecture
- [x] User approved this plan

### Phase 2: Execution

- [ ] Research final service-specific implementation references
- [x] Generate `azure.yaml`
- [x] Generate Bicep modules under `infra/bicep`
- [x] Generate app, collector, tool gateway, and admin web skeletons
- [x] Generate Dockerfiles
- [x] Generate full Markdown documentation under `docs/`
- [x] Generate extension samples under `samples/extensions/`
- [x] Add GitHub Actions with OIDC
- [ ] Update plan status to `Ready for Validation`

### Phase 3: Validation

- [ ] Invoke azure-validate skill
- [ ] All validation checks pass
- [ ] Update plan status to `Validated`
- [ ] Record validation proof below

### Phase 4: Deployment

- [ ] Invoke azure-deploy skill
- [ ] Deployment successful
- [ ] Report deployed endpoint URLs
- [ ] Update plan status to `Deployed`

---

## 18. Validation Proof

| Check | Command Run | Result | Timestamp |
|---|---|---|---|
| Not run yet | Validation is blocked until user approves plan and implementation artifacts are generated | Pending | 2026-06-12T12:01:48+02:00 |

---

## 19. Files to Generate

| File | Purpose | Status |
|---|---|---|
| `.azure/plan.md` | This plan | Created |
| `docs/architecture/architecture-diagrams.md` | Mermaid architecture diagrams | Created |
| `docs/presentations/agent-azure-farsight-overview.pptx` | Presentation deck | Created |
| `docs/**/*.md` | Full system documentation, operations guides, security guides, and extension guide | After plan approval |
| `samples/extensions/**` | Sample collector module, matching Azure SRE Agent tool, AGT policy, schemas, and tests | After plan approval |
| `azure.yaml` | AZD configuration | After plan approval |
| `infra/bicep/main.bicep` | Infrastructure entry point | After plan approval |
| `src/*/Dockerfile` | Container builds | After plan approval |

---

## 20. Next Steps

> Current: Planning artifacts.

1. Review `.azure/plan.md`, architecture diagrams, and presentation deck.
2. Approve or adjust the plan.
3. Start implementation with repo foundation, AZD/Bicep baseline, API skeleton, and collector skeleton.
