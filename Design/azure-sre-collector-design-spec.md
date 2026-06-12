# Agent-Azure-FarSight Design Spec

## Overview

This document defines a V1 architecture for Agent-Azure-FarSight, a Windows remote diagnostics and bounded-remediation system designed for an Azure-hosted SRE agent. The design avoids inbound remote access and avoids compiled endpoint software by using an Intune-deployed PowerShell collector framework, a brokered cloud control plane, and policy-governed agent actions.

The endpoint side is intentionally implemented as PowerShell scripts plus Windows Task Scheduler rather than a custom executable. Intune platform scripts can deploy PowerShell to Windows devices through the Intune management extension, while Remediations can run scheduled or on-demand detection/remediation packages, making Intune a practical bootstrap and maintenance channel for the collector.

The cloud side uses a custom HTTPS control and collection API, Azure Service Bus for asynchronous command brokering, Cosmos DB for durable job state, and Azure Monitor Logs Ingestion API for normalized diagnostics into Log Analytics. Azure Service Bus provides durable queues, topics, and subscriptions, and supports message sessions for ordered handling of related message streams such as work for a single device.

Agent governance is applied separately from endpoint execution. The Agent Governance Toolkit is intended to govern the SRE agent's tool calls with runtime policy enforcement, approvals, identity controls, and auditability so that the AI side cannot directly bypass operational guardrails.

## Project name

The project name for this system is **Agent-Azure-FarSight**. The name emphasizes governed remote visibility and targeted diagnostics rather than direct remote control or shell access.

## Goals

- Collect targeted diagnostics from Windows endpoints without direct interactive access.
- Reuse Intune for deployment, healing, and baseline diagnostics where possible.
- Add custom application-aware diagnostics beyond Intune's built-in collection set.
- Support asynchronous, brokered, auditable job execution rather than a shell or relay tunnel.
- Keep the endpoint implementation script-based and easy to update with Intune.
- Enforce dual control: cloud-side governance for the SRE agent and endpoint-side allowlisting for the collector.

## Non-goals

- No reverse shell.
- No arbitrary remote PowerShell submitted by the cloud in V1.
- No persistent inbound connectivity requirement.
- No compiled Windows service in V1.
- No broad remote desktop functionality.

## Architecture

### High-level flow

1. The SRE agent identifies a diagnostic hypothesis.
2. A governed Python tool calls the control API to create a job.
3. The control API persists the job in Cosmos DB and enqueues command metadata to Azure Service Bus.
4. The endpoint PowerShell collector checks in on schedule, fetches work for its device, validates the job against local policy, and executes only an approved module.
5. The collector posts structured results and optional artifact metadata to the collection API.
6. The API writes lifecycle state to Cosmos DB and normalized telemetry to Log Analytics through the Logs Ingestion API.
7. The SRE agent reads evidence, proposes next steps, and requests approval when a state-changing action is required.

### Core components

| Component | Role |
|---|---|
| Intune | Deploy bootstrap script, distribute updates, run remediations, use built-in diagnostics where useful. |
| PowerShell collector | Local scheduled script framework for check-in, module execution, local logging, and artifact packaging. |
| Windows Task Scheduler | Runs collector on startup and recurring intervals using native scheduling primitives. |
| Custom control API | Device check-in, job retrieval, result ingestion, artifact coordination, approval-aware routing. |
| Azure Service Bus | Durable broker for asynchronous command flow; sessions preserve ordered handling per device. |
| Cosmos DB | Job state, endpoint state, approvals, leases, TTL, correlation IDs. |
| Log Analytics | Central query plane for normalized diagnostics via Logs Ingestion API. |
| Blob Storage | Storage for bundles, zipped logs, traces, and large artifacts. |
| Agent Governance Toolkit | Runtime policy and audit around SRE agent tool execution.|

## Endpoint collector design

### Execution model

The endpoint collector is a script framework rooted under a stable local path such as `C:\ProgramData\Company\SreCollector`. Intune deploys a bootstrap script once, and the bootstrap installs the directory structure, a scheduled task, a configuration file, local logging, and a signed module manifest.

The collector should not run as a long-lived looped process in V1. A scheduled task should run on startup and then periodically, for example every 5 to 15 minutes, because Task Scheduler is the simplest reliable native mechanism for recurring background PowerShell execution without compiling a Windows service.

### Folder layout

```text
C:\ProgramData\Company\SreCollector\
  bootstrap\
  modules\
  state\
  logs\
  cache\
  artifacts\
  config\
    config.json
    module-manifest.json
```

### Script layout

- `bootstrap.ps1` - initial install and upgrades.
- `collector.ps1` - check-in, fetch, validate, execute, upload.
- `common.psm1` - HTTP helpers, auth helpers, schema validation, compression, redaction.
- `modules\*.ps1` - approved diagnostics modules.
- `healthcheck.ps1` - self-test used by Intune Remediations.
- `repair.ps1` - self-heal for missing scheduled tasks, folders, or stale config.

### Security boundaries

The collector only executes module names present in a local allowlist manifest. Each module receives schema-validated parameters and returns structured JSON plus optional artifact references. No module may accept raw PowerShell script text, free-form command lines, or unconstrained file paths in V1.

Suggested endpoint safeguards:

- Signed scripts where feasible.
- Allowlisted file paths, registry paths, event channels, URLs, and process names.
- Time window, size, and count limits per module.
- Redaction of secrets and connection strings before upload.
- Local execution transcript plus structured JSON audit.
- Short job lease and expiration handling.
- Module manifest with version and content hashes.

## Cloud control plane

### Control API

Recommended endpoints:

- `POST /devices/checkin`
- `GET /devices/{deviceId}/jobs`
- `POST /jobs/{jobId}/results`
- `POST /jobs/{jobId}/artifacts/prepare`
- `POST /telemetry`
- `GET /devices/{deviceId}/policy`
- `POST /approvals/{approvalId}/decision`

The device should authenticate using device identity, certificate-based trust, or another enterprise-approved mechanism. The API should be the stable boundary for both devices and SRE tools so the broker can evolve internally without forcing endpoint changes.

### Messaging

Azure Service Bus should be used as the asynchronous job broker, not as the device-facing API. Queues or topics may be used, but sessions are recommended with `deviceId` as the session key when per-device ordering matters.[cite:88][cite:78]

Suggested messaging semantics:

- One command stream per device session.
- Retry with max delivery count.
- Dead-letter queue for poison jobs.
- Correlation IDs propagated across API, queue, collector, and logs.
- Lease tokens to avoid duplicate job execution.

### State and telemetry

Cosmos DB stores authoritative control-plane state:

- devices
- jobs
- approvals
- module manifests
- policy snapshots
- heartbeat summaries

Log Analytics stores normalized operational evidence:

- custom app log summaries
- event slices
- connectivity tests
- performance bursts
- collector health events

The Logs Ingestion API is the preferred ingestion path for custom data into Log Analytics.[cite:69]

## Module catalog for V1

The V1 collector should focus on investigation modules that complement Intune diagnostics rather than duplicate them. Intune's Collect Diagnostics action already gathers a built-in Windows bundle including selected registry keys, common commands such as `ipconfig /all` and `dsregcmd /status`, diagnostic tooling output, specific file paths, and several predefined event logs.[cite:122]

### Tier 1 modules

#### 1. Get-AppLogBundle

Purpose: collect custom application logs from approved file paths.

Inputs:

- `appId`
- `pathProfile`
- `startTime`
- `endTime`
- `tailLines`
- `maxBytes`
- `includePatterns`
- `excludePatterns`

Outputs:

- summary with files matched, bytes collected, error counts
- normalized records where possible
- zipped artifact reference when needed

Why: Intune doesn't know custom application log folders or schemas.[cite:122]

#### 2. Get-AppEventSlice

Purpose: collect targeted Windows event data not covered by the built-in Intune set.

Inputs:

- `logName`
- `providerNames`
- `eventIds`
- `levels`
- `startTime`
- `endTime`
- `maxEvents`

Outputs:

- summary of event counts by provider, ID, and level
- selected event payloads
- event correlation hints

Implementation note: use `Get-WinEvent -FilterHashtable` for efficient bounded queries.[cite:136]

#### 3. Get-AppHealthSnapshot

Purpose: gather app-semantic status.

Inputs:

- `appId`
- `serviceNames`
- `processNames`
- `configProfiles`

Outputs:

- service state and startup mode
- process state and versions
- config checksum and safe key-values
- restart evidence and recent failures

#### 4. Test-AppConnectivity

Purpose: diagnose app reachability.

Inputs:

- `targets`
- `ports`
- `urls`
- `dnsNames`
- `expectedTlsThumbprints` (optional)

Outputs:

- DNS result
- route/interface summary
- TCP/TLS/HTTP status
- proxy hints
- latency summary

#### 5. Get-ConfigEvidence

Purpose: read approved registry and config sources with redaction.

Inputs:

- `registryProfiles`
- `fileProfiles`
- `redactionProfile`

Outputs:

- normalized config values
- missing keys/files
- drift indicators

### Tier 2 modules

#### 6. Get-CorrelationTrace

Search a correlation ID, session ID, or request ID across log files and event entries for a bounded time window.

#### 7. Get-ServiceDependencyState

Collect service dependency graph, failure actions, and supporting service-related events.

#### 8. Get-TaskSchedulerState

Collect app-related scheduled task state, last result, principals, and recent failures.

#### 9. Get-PerfBurst

Capture short-duration performance counters for CPU, memory, disk, and optional app counters.

#### 10. Start-AppTraceWindow

Start a short approved trace window for ETW or vendor-specific diagnostics and upload the resulting artifact.

### Tier 3 modules

#### 11. Get-DumpMetadata

Inspect presence and metadata of crash dumps without uploading dump contents by default.

#### 12. Get-UserSessionImpact

Capture active sessions and user-context data relevant to app behavior in VDI or multi-user environments.

## Intune integration strategy

### What Intune should do

- Bootstrap the collector using platform scripts.[cite:101]
- Repair or validate collector health using Remediations.[cite:109]
- Optionally trigger bounded support actions through dedicated remediation packages.[cite:109]
- Collect built-in diagnostics when generic Windows baseline evidence is needed.[cite:122]

### What Intune should not do

- Act as the dynamic command bus for the collector.
- Be the only scheduling engine for all custom investigations.
- Deliver arbitrary one-off diagnostic logic on every investigation.

## Governance model

### Cloud-side governance

The SRE agent must call only governed tools. AGT policies should control who can request data, which modules are allowed, what parameter ranges are acceptable, and which actions require approval.[cite:61]

Policy tiers:

- Read-only collection modules: auto-allow.
- Potentially sensitive modules, such as trace start or dump metadata: require approval.
- Any state-changing remediation in later versions: require approval and stricter parameter constraints.

### Endpoint-side governance

The collector enforces a second layer:

- local module allowlist
- argument schema validation
- path/provider/URL allowlists
- execution timeout per module
- artifact size limits
- result signing or checksum tagging if needed

## Data contracts

### Job document example

```json
{
  "jobId": "job-20260612-0001",
  "deviceId": "aad-device-guid",
  "incidentId": "inc-12345",
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
  "policyVersion": "2026-06-12.1",
  "createdAt": "2026-06-12T09:05:00Z",
  "expiresAt": "2026-06-12T10:05:00Z",
  "leaseUntil": null,
  "retryCount": 0,
  "requestedBy": "sre-agent"
}
```

### Module result envelope

```json
{
  "jobId": "job-20260612-0001",
  "deviceId": "aad-device-guid",
  "module": "Get-AppLogBundle",
  "status": "Succeeded",
  "startedAt": "2026-06-12T09:06:00Z",
  "completedAt": "2026-06-12T09:07:20Z",
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
      "kind": "zip",
      "name": "contoso-app-logs-20260612.zip",
      "blobRef": "pending-or-uploaded-reference"
    }
  ],
  "nextSuggestedModules": [
    "Get-AppEventSlice",
    "Test-AppConnectivity"
  ]
}
```

## Implementation guidance

### PowerShell guidance

- Use PowerShell 5.1 compatibility first unless a PowerShell 7 runtime is guaranteed.
- Prefer modules/functions over monolithic scripts.
- Use structured JSON logging everywhere.
- Wrap all external calls with timeout and retry handling.
- Keep module execution idempotent and bounded.
- Use `Compress-Archive` or equivalent for bundles when artifact upload is needed.
- Use `Get-WinEvent` with bounded filters rather than unrestricted event export for targeted scenarios.

### API guidance

- Treat the control API as the stable contract.
- Validate every request server-side.
- Use signed upload URLs for artifact transfer.
- Separate control-plane writes from heavy artifact upload paths.
- Store only summarized operational data in Log Analytics; place large artifacts in Blob Storage.[cite:69]

### Observability guidance

At minimum, track:

- collector heartbeat success/failure
- job dispatch latency
- job execution duration by module
- module failure rate
- artifact upload rate and size
- dead-letter count
- approval wait time

## V1 delivery plan

### Phase 1

- bootstrap via Intune
- scheduled task installation
- check-in API
- job retrieval API
- Cosmos job store
- Service Bus broker
- results ingestion
- two modules: `Get-AppLogBundle`, `Get-AppEventSlice`

### Phase 2

- `Get-AppHealthSnapshot`
- `Test-AppConnectivity`
- `Get-ConfigEvidence`
- Blob artifact uploads
- local manifest update flow
- Log Analytics normalization rules

### Phase 3

- governance integration with AGT around SRE tools
- approval workflow
- additional Tier 2 modules
- dashboards and KQL investigations

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Collector becomes a de facto shell | Only support named modules with validated schemas and allowlists. |
| PowerShell trust concerns from security teams | Signed scripts, constrained module set, full audit, no free-form code. |
| Duplicate data with Intune diagnostics | Use Intune for baseline bundles and custom collector for targeted deltas.[cite:122] |
| Large artifacts overwhelm Log Analytics | Store artifacts in Blob Storage, send only summaries to Logs Ingestion API.[cite:69] |
| Device-side drift or task deletion | Use Intune Remediations to validate and repair the collector footprint.[cite:109] |
| Unordered or duplicated commands | Use Service Bus sessions, leases, retries, and idempotent job handling.[cite:78][cite:88] |

## Acceptance criteria for V1

- Collector deploys successfully through Intune to pilot Windows devices.[cite:101]
- Collector self-runs via scheduled task without a compiled service.[cite:110]
- Jobs can be created and completed asynchronously end to end.[cite:88]
- At least three modules are production-ready: `Get-AppLogBundle`, `Get-AppEventSlice`, `Get-AppHealthSnapshot`.
- Log Analytics contains normalized summaries searchable by device, incident, module, and correlation ID.[cite:69]
- AGT policies govern SRE-side job creation and any higher-risk operation.[cite:61]
- No arbitrary remote shell capability exists in the implementation.

## Prompt for an advanced coding agent

Use the following prompt with an advanced coding agent to produce a detailed implementation plan.

```text
You are designing the implementation plan for a production-oriented V1 of a Windows remote diagnostics platform for an Azure SRE agent.

Objective:
Create a step-by-step implementation plan, architecture breakdown, repo structure, milestones, interfaces, and delivery backlog for a brokered remote collector system.

Important constraints:
- Endpoint OS: Windows.
- Endpoint distribution: Microsoft Intune.
- Avoid compiled endpoint software in V1.
- Endpoint implementation must be PowerShell-based.
- No reverse shell.
- No arbitrary remote PowerShell from the cloud in V1.
- No inbound connectivity to endpoints.
- Collector should run via scheduled task, not a custom Windows service.
- Cloud should use a custom HTTPS control/collection API.
- Use Azure Service Bus as async broker.
- Use Cosmos DB for durable job state.
- Use Azure Monitor Logs Ingestion API for normalized telemetry into Log Analytics.
- Use Blob Storage for large artifacts.
- Use Agent Governance Toolkit to govern SRE agent tool calls and approvals.
- Intune built-in Collect Diagnostics exists already; custom collector should complement it rather than duplicate it.

System concept:
- Intune deploys bootstrap.ps1 and remediation scripts.
- Bootstrap creates local folder structure, scheduled tasks, config, logs, and module manifest.
- collector.ps1 checks in periodically, fetches one approved job, executes an allowlisted module, and uploads structured results.
- Module execution is bounded by JSON-schema-like parameter validation, allowlists, timeouts, and artifact size caps.
- Cloud control plane persists jobs in Cosmos DB and uses Service Bus for asynchronous brokering.
- Results go to Cosmos DB plus Log Analytics through Logs Ingestion API.

V1 modules to plan for:
1. Get-AppLogBundle
2. Get-AppEventSlice
3. Get-AppHealthSnapshot
4. Test-AppConnectivity
5. Get-ConfigEvidence

Your tasks:
1. Produce a detailed implementation plan by workstream: endpoint collector, API, broker, state store, telemetry, governance, IaC, CI/CD, security, observability, and pilot rollout.
2. Propose a monorepo or multi-repo structure with folders for PowerShell, API, IaC, tests, docs, and sample policies.
3. Define the main contracts: job document schema, result envelope, module manifest, device check-in payload, artifact upload workflow.
4. Define the endpoint execution model in detail: scheduled tasks, locking, retries, local state, logging, redaction, manifest updates, and failure handling.
5. Define the API surface in detail: endpoints, auth, validation, response codes, idempotency, and versioning.
6. Recommend exact Azure building blocks for the API runtime, auth model, queue design, Cosmos containers/partition keys, Log Analytics custom tables, and Blob layout.
7. Provide a phased delivery plan with MVP, pilot, and hardening phases.
8. Identify security risks and operational risks, then propose mitigations.
9. Propose a testing strategy: unit, integration, contract, endpoint simulation, chaos/failure testing.
10. Produce a prioritized backlog with epics, stories, and technical spikes.
11. Call out decisions where alternatives should be evaluated, for example Azure Functions vs Container Apps, queue vs topic, PowerShell 5.1 vs 7, certificate auth vs device token, and whether to use Intune Remediations for self-heal only or also for manual trigger flows.

Output format:
- Start with architecture assumptions and explicit open questions.
- Then provide a recommended target architecture.
- Then provide the implementation plan by workstream.
- Then provide schemas/contracts.
- Then provide repo structure.
- Then provide backlog and milestones.
- Then provide risk register.
- Then provide test strategy.
- Then provide a final “first 2 weeks” execution plan.

Quality bar:
- Be concrete and implementation-oriented.
- Prefer specific decisions over generic advice.
- Highlight trade-offs and defaults.
- Keep V1 intentionally narrow and secure.
- Assume the reader is a senior Azure/Windows/DevOps engineer.
```
