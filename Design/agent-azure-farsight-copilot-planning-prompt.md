# GitHub Copilot Planning Prompt for Agent-Azure-FarSight

## Objective

Create a detailed implementation plan for **Agent-Azure-FarSight**, a production-oriented V1 system for governed remote diagnostics of Windows clients managed with Intune. The solution must include:

- A PowerShell-based endpoint collector deployed through Intune.
- A brokered cloud control plane on Azure.
- Bicep infrastructure to deploy the Azure resources.
- An Azure-hosted SRE agent with configured tools that can use the collection system to request diagnostics and receive results.
- Security and governance controls so the system does not become a remote shell.

## Core constraints

- Endpoint OS: Windows.
- Endpoint deployment: Microsoft Intune.
- Avoid compiled endpoint software in V1.
- Endpoint runtime must be PowerShell-based.
- No reverse shell.
- No arbitrary remote PowerShell from the cloud in V1.
- No inbound connectivity to endpoints.
- Endpoint execution should use Windows Task Scheduler, not a custom Windows service.
- Cloud entry point should be a custom HTTPS control and collection API.
- Use Azure Service Bus as the asynchronous broker.
- Use Cosmos DB for durable state.
- Use Azure Monitor Logs Ingestion API for normalized telemetry.
- Use Blob Storage for large artifacts.
- Use Bicep for infrastructure deployment.
- Include an Azure SRE agent that has explicit tools configured for creating jobs, checking job status, retrieving summaries, and requesting approved follow-up diagnostics.
- Use a governance layer such as Agent Governance Toolkit to constrain what the Azure SRE agent can do.
- Intune built-in Collect Diagnostics already exists; the custom collector must complement it, not duplicate it.

## System concept

Agent-Azure-FarSight is a brokered remote collection system.

- Intune deploys `bootstrap.ps1` and remediation scripts.
- `bootstrap.ps1` creates local folders, scheduled tasks, config, logs, local state, and a module manifest.
- `collector.ps1` checks in periodically, fetches one approved job, executes a named allowlisted module, and uploads structured results.
- Modules are bounded by parameter validation, allowlists, size limits, and timeouts.
- Cloud services persist jobs in Cosmos DB and broker async work through Azure Service Bus.
- The control API receives check-ins, serves pending jobs, accepts results, and coordinates artifact uploads.
- Normalized evidence is written to Log Analytics.
- The Azure SRE agent uses configured tools to interact with the control plane rather than directly executing commands on endpoints.

## V1 endpoint modules

Plan for these modules in V1:

1. `Get-AppLogBundle`
2. `Get-AppEventSlice`
3. `Get-AppHealthSnapshot`
4. `Test-AppConnectivity`
5. `Get-ConfigEvidence`

## Required outputs

Produce a detailed planning document that includes the following sections.

### 1. Architecture assumptions and open questions

- Explicit assumptions.
- Design decisions that still need confirmation.
- Alternative paths worth evaluating.

### 2. Recommended target architecture

Describe the end-to-end architecture for:

- Intune deployment and maintenance.
- PowerShell collector execution model.
- Control API.
- Azure Service Bus broker.
- Cosmos DB state model.
- Log Analytics ingestion and tables.
- Blob artifact storage.
- Azure SRE agent runtime.
- Governance and approval flow.

### 3. Workstreams

Create an implementation plan broken down by workstream:

- Endpoint collector.
- PowerShell modules.
- Control API.
- Broker and asynchronous orchestration.
- Cosmos DB and data model.
- Telemetry and Log Analytics.
- Blob artifact handling.
- Azure SRE agent.
- Governance and approvals.
- Intune packaging and remediation.
- Bicep infrastructure.
- CI/CD.
- Security and identity.
- Observability and operations.
- Pilot rollout.

### 4. Repo structure

Recommend a concrete repo structure. Include folders for:

- `src/collector`
- `src/modules`
- `src/api`
- `src/agent-tools`
- `infra/bicep`
- `docs`
- `tests`
- `samples`
- `policies`

Be specific about what belongs in each folder.

### 5. Contracts and schemas

Define draft contracts for:

- device check-in request/response
- job document
- job lease model
- module manifest
- module input schema
- module result envelope
- artifact upload preparation and commit workflow
- approval request and decision payloads
- SRE agent tool interfaces

### 6. Azure infrastructure in Bicep

The planning output must include a detailed Bicep deployment plan for all required Azure resources. Recommend the exact resource types, naming approach, environment parameterization, and module boundaries.

At minimum, cover:

- Resource group strategy.
- Azure Key Vault.
- Azure Service Bus namespace, queues or topics, and session strategy.
- Azure Cosmos DB account, database, containers, partition keys, TTL choices.
- Azure Storage account and blob containers.
- Log Analytics workspace and custom table ingestion path.
- API hosting choice, for example Azure Functions or Azure Container Apps.
- Identity model using managed identities where possible.
- App Configuration or equivalent if needed.
- Monitoring and alerting resources.
- Role assignments and RBAC.
- Environment separation for dev, test, prod.

The plan should also explain how the Bicep deployment supports the Azure SRE agent and its tools.

### 7. Azure SRE agent design

The planning output must define the Azure SRE agent implementation concept.

Include:

- Where the SRE agent runs.
- How it authenticates to the control plane.
- Which tools it exposes.
- How those tools map to FarSight APIs.
- How AGT or equivalent governance policies wrap those tools.
- Which tools are read-only versus approval-gated.
- How tool outputs are structured for reasoning and follow-up investigation.

At minimum, define tools for:

- create diagnostic job
- get job status
- get job result summary
- retrieve artifact metadata
- request follow-up module execution
- request approval for higher-risk action
- query prior device investigation history

### 8. Security model

Provide a dual-control security design:

- cloud-side governance for the SRE agent
- endpoint-side enforcement in the collector

Cover:

- identities
- approvals
- allowlists
- script signing
- input validation
- artifact protection
- secret storage
- data redaction
- audit trail
- failure isolation

### 9. Delivery roadmap

Create a phased roadmap:

- MVP
- Pilot
- Hardening
- Production readiness

### 10. Testing strategy

Include:

- unit tests
- PowerShell module tests
- API integration tests
- contract tests
- end-to-end device simulation
- queue failure tests
- Cosmos concurrency tests
- security tests
- policy/governance tests
- Bicep validation and deployment tests

### 11. Prioritized backlog

Provide:

- epics
- user stories
- technical tasks
- spikes
- suggested sequencing

### 12. First two weeks execution plan

Give a practical day-by-day or sprint-style starting plan.

## Important design preferences

- Keep V1 narrow, deterministic, and enterprise-safe.
- Prefer explicit module contracts over generic script execution.
- Prefer concrete recommendations over generic options.
- Highlight trade-offs clearly.
- Assume the audience is a senior Azure / Windows / DevOps engineer.
- The final plan should be detailed enough that implementation can begin immediately after review.

## Final instruction

Do not write code yet. Produce a planning-oriented technical design and implementation plan that will directly guide repository creation, backlog definition, and phased delivery for Agent-Azure-FarSight.
