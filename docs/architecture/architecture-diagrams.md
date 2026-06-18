# Agent-Azure-FarSight Architecture Diagrams

Generated: 2026-06-12

These diagrams document the intended Agent-Azure-FarSight V1 architecture during early implementation.

## 1. High-level regional architecture

```mermaid
flowchart LR
    subgraph Endpoints["Windows endpoints managed by Intune"]
        Intune["Microsoft Intune<br/>Platform scripts + Remediations"]
        Task["Windows Task Scheduler"]
        Collector["PowerShell collector<br/>collector.ps1"]
        Modules["Allowlisted diagnostic modules"]
        LocalPolicy["Local manifest, schemas,<br/>hashes, allowlists"]
        Intune --> Task
        Task --> Collector
        Collector --> LocalPolicy
        Collector --> Modules
    end

    subgraph Italy["Italy North - FarSight collector/control plane"]
        Api["Control API<br/>Container Apps + FastAPI"]
        Admin["Admin and monitoring web app<br/>React + FastAPI BFF"]
        Gateway["AGT-governed<br/>FarSight tool gateway"]
        Cosmos["Cosmos DB<br/>jobs, devices, approvals, policies"]
        Blob["Blob Storage<br/>diagnostic artifacts"]
        LA["Log Analytics<br/>custom tables"]
        KV["Key Vault"]
        AppConfig["App Configuration"]
        APIM["Optional APIM"]
    end

    subgraph Sweden["Sweden Central - Azure SRE Agent integration"]
        SRE["Azure SRE Agent<br/>custom FarSight agent"]
    end

    Operator["SRE operator"] --> SRE
    SRE --> Gateway
    Gateway -->|managed identity| Api
    Admin --> Api
    Api --> Cosmos
    Api --> Blob
    Api --> LA
    Api --> KV
    Api --> AppConfig
    Collector -->|mTLS check-in, fetch, result| APIM
    APIM --> Api
    Collector -->|dev/test direct HTTPS if APIM disabled| Api
    Collector -->|short-lived upload URL| Blob
    Gateway --> AgentObs
```

## 2. Diagnostic job lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant Op as SRE operator
    participant SRE as Azure SRE Agent
    participant AGT as AGT tool gateway
    participant API as FarSight Control API
    participant Approvals as Approval API and Teams hook
    participant Cosmos as Cosmos DB
    participant Collector as Endpoint collector
    participant Blob as Blob Storage
    participant LA as Log Analytics

    Op->>SRE: Ask for targeted diagnostics
    SRE->>AGT: create_diagnostic_job(tool args)
    AGT->>AGT: Evaluate AGT policy
    alt Policy denies
        AGT-->>SRE: GovernanceDenied + audit id
    else Policy requires approval
        AGT->>API: Create approval request
        API->>Cosmos: Store approval
        API->>Approvals: Notify Teams
        Approvals->>API: Approve or deny
        API->>Cosmos: Persist decision
    end
    AGT->>API: Create bounded diagnostic job
    API->>Cosmos: Persist job Queued
    Collector->>API: Check in over mTLS
    API->>Cosmos: Verify device, policy, pending job
    API-->>Collector: Return one leased job
    Collector->>Collector: Validate manifest, hash, schema, allowlists
    Collector->>Collector: Execute named module with timeout
    opt Large artifact
        Collector->>API: Prepare artifact upload
        API-->>Collector: Short-lived upload URL
        Collector->>Blob: Upload artifact
        Collector->>API: Commit artifact metadata
    end
    Collector->>API: Submit result envelope
    API->>Cosmos: Mark job terminal and store summary
    API->>LA: Ingest normalized telemetry
    API-->>AGT: Job accepted/status available
    SRE->>AGT: get_job_result_summary
    AGT->>API: Read summary
    API-->>AGT: Findings and next suggested modules
    AGT-->>SRE: Evidence for reasoning
```

## 3. Dual-control security model

```mermaid
flowchart TB
    subgraph Cloud["Cloud-side governance"]
        SRE["Azure SRE Agent"]
        Tool["FarSight custom tool call"]
        Policy["AGT policy engine<br/>allow, deny, require_approval"]
        Approval["Secondary approval API<br/>Teams notification hook"]
        APIAuth["API authorization<br/>managed identity + RBAC + claims"]
        Audit["Governance and audit events"]
        SRE --> Tool --> Policy
        Policy -->|allow| APIAuth
        Policy -->|deny| Audit
        Policy -->|require approval| Approval --> APIAuth
        Approval --> Audit
        APIAuth --> Audit
    end

    subgraph Endpoint["Endpoint-side enforcement"]
        Cert["Device certificate<br/>mTLS"]
        Manifest["Local module manifest"]
        Hash["Script hash verification"]
        Schema["Parameter schema validation"]
        Allowlist["Path, event provider, URL,<br/>registry and process allowlists"]
        Runtime["Timeout, size cap,<br/>single-job lease"]
        Redaction["Redaction before upload"]
        LocalAudit["Local structured audit log"]
        Cert --> Manifest --> Hash --> Schema --> Allowlist --> Runtime --> Redaction --> LocalAudit
    end

    APIAuth --> Cert
```

## 4. Azure deployment topology

```mermaid
flowchart TB
    subgraph Repo["GitHub repository"]
        AZD["azure.yaml"]
        Bicep["infra/bicep modules"]
        API["src/api"]
        Admin["src/admin-web"]
        Gateway["src/agent-tools/gateway"]
        Collector["src/collector + src/modules"]
        Policies["policies/agt + endpoint + approvals"]
        Actions["GitHub Actions<br/>OIDC federation"]
    end

    subgraph Azure["Azure subscription"]
        subgraph RG1["rg-farsight-{env}-itn"]
            ACA1["Container Apps env"]
            APIApp["ca-farsight-api"]
            AdminApp["ca-farsight-admin"]
            Data["Cosmos DB,<br/>Storage, Key Vault, App Config"]
            Monitor["Log Analytics, App Insights,<br/>DCR/DCE, alerts"]
            Optional["Optional APIM, VNet,<br/>private endpoints"]
        end
        subgraph RG2["rg-farsight-agent-{env}-swc"]
            ACA2["Container Apps env"]
            ToolApp["ca-farsight-tools"]
            AgentKV["Gateway Key Vault"]
            AgentMonitor["Gateway App Insights<br/>and Log Analytics"]
            SREAgent["Azure SRE Agent<br/>service-created MI and observability"]
        end
    end

    Actions -->|azd provision/deploy| AZD
    AZD --> Bicep
    Bicep --> RG1
    Bicep --> RG2
    API --> APIApp
    Admin --> AdminApp
    Gateway --> ToolApp
    Policies --> ToolApp
    Collector -->|packaged by Intune pipeline/manual export| IntunePackage["Intune package artifacts"]
```

## 5. Cosmos DB state model

```mermaid
flowchart LR
    subgraph Cosmos["Cosmos DB for NoSQL - farsight database"]
        Devices["devices<br/><b>PK:</b> /tenantDeviceId<br/>certificate thumbprint<br/>policy version<br/>last heartbeat"]
        Jobs["jobs<br/><b>PK:</b> /deviceId<br/>job status<br/>task type<br/>lease and expiry<br/>correlation ID"]
        Approvals["approvals<br/><b>PK:</b> /approvalId<br/>risk level<br/>requested by<br/>decision and expiry"]
        Manifests["manifests<br/><b>PK:</b> /manifestId<br/>module versions<br/>hashes<br/>schemas"]
        Policies["policies<br/><b>PK:</b> /policyId<br/>cloud policy<br/>endpoint policy<br/>version history"]
        Investigations["investigations<br/><b>PK:</b> /incidentId<br/>device timeline<br/>summary<br/>prior history"]
        ArtifactIndex["artifactIndex<br/><b>PK:</b> /jobId<br/>artifact metadata<br/>blob reference<br/>hash and size"]
        AuditEvents["auditEvents<br/><b>PK:</b> /correlationId<br/>actor<br/>action<br/>event time"]
    end

    Devices -->|receives| Jobs
    Devices -->|participates in| Investigations
    Investigations -->|groups| Jobs
    Approvals -->|gates| Jobs
    Manifests -->|constrains| Jobs
    Policies -->|evaluated for| Jobs
    Jobs -->|produces| ArtifactIndex
    Jobs -->|emits| AuditEvents
```

## 6. Endpoint collector execution model

```mermaid
flowchart TD
    Start["Task Scheduler trigger<br/>startup + every 5-15 min"] --> Lock["Acquire local lock"]
    Lock -->|lock exists| Exit["Exit with structured log"]
    Lock --> Config["Load config and manifest"]
    Config --> Health["Self-check folders, state,<br/>cert, clock, module hashes"]
    Health --> Checkin["POST /devices/checkin<br/>mTLS"]
    Checkin --> Job{"Job available?"}
    Job -->|No| LogHeartbeat["Write heartbeat log"] --> Release["Release lock"] --> Done["Exit"]
    Job -->|Yes| Validate["Validate lease, module name,<br/>schema, allowlists"]
    Validate -->|Invalid| Reject["Submit rejected result<br/>with reason"] --> Release
    Validate --> Execute["Run allowlisted module<br/>with timeout and size caps"]
    Execute --> Redact["Redact secrets and package summary"]
    Redact --> Artifact{"Artifact needed?"}
    Artifact -->|Yes| Upload["Prepare, upload, commit artifact"]
    Artifact -->|No| Submit["Submit result envelope"]
    Upload --> Submit
    Submit --> LocalAudit["Write local audit and state"]
    LocalAudit --> Release
```

## 7. Public-dev versus private-prod ingress

```mermaid
flowchart LR
    subgraph Dev["Dev/test profile"]
        DevEndpoint["Collector / admin / tools"] --> DevIngress["Public HTTPS Container Apps ingress"]
        DevIngress --> DevAPI["Control API"]
    end

    subgraph Prod["Enterprise/private profile"]
        Corp["Corporate network / managed egress"] --> PrivateDns["Private DNS"]
        PrivateDns --> PE["Private endpoints"]
        PE --> InternalIngress["Internal Container Apps/APIM ingress"]
        InternalIngress --> ProdAPI["Control API"]
    end

    DevAPI --> SameBackend["Same API contracts and auth"]
    ProdAPI --> SameBackend
```
