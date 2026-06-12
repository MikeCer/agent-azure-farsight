# Agent-Azure-FarSight

Agent-Azure-FarSight is a governed remote diagnostics platform for Intune-managed Windows clients. It lets approved Azure SRE Agent tools request targeted, read-only evidence from endpoints without opening a remote shell or allowing arbitrary PowerShell.

## Current state

This repository is in early implementation. It contains skeletons for the control API, admin web/BFF, AGT-governed tool gateway, PowerShell collector, validation scripts, and initial diagnostic modules. Treat docs as the user-facing source for intended behavior; implementation details are still being filled in.

## Architecture summary

- **Azure SRE Agent integration:** SRE Agent actions call specific FarSight tools through a governed AGT tool gateway. Tools evaluate policy before creating diagnostic jobs.
- **Azure control plane:** The API, worker, queue, state store, artifact store, Key Vault/App Configuration, and observability components are deployed through AZD/Bicep as the infrastructure matures.
- **Endpoint collector:** Intune deploys the PowerShell collector, configuration, certificates, and scheduled task to managed Windows clients.
- **Job lifecycle:** Collectors check in over authenticated HTTPS/mTLS, lease one approved job, run an allowlisted module with schema-validated parameters, redact results, and upload a bounded result envelope or approved artifact.
- **Operations:** Telemetry and audit events support dashboards, alerts, policy review, incident response, and retention controls.

## Key safety constraints

- No reverse shell, inbound endpoint connectivity, or arbitrary remote PowerShell.
- Collectors execute only named allowlisted modules from a signed or authenticated manifest.
- Parameters are schema-validated and bounded; free-form commands, script blocks, wildcards, and arbitrary paths are denied.
- Modules are read-only in the current implementation stage.
- Policy, RBAC, approval requirements, mTLS identity, redaction, audit, and retention controls fail closed.

## Repository structure

| Path | Purpose |
| --- | --- |
| `src/api/` | FastAPI control API skeleton for jobs, collectors, approvals, artifacts, and health. |
| `src/agent-tools/gateway/` | AGT-governed Azure SRE Agent tool gateway skeleton. |
| `src/admin-web/` | Admin BFF and React/Vite frontend skeleton. |
| `src/collector/` | PowerShell collector, bootstrap, repair, health check, config, and schemas. |
| `src/modules/` | Built-in diagnostic module skeletons and tests. |
| `azure.yaml`, `infra/` | AZD/Bicep deployment entry points when present and configured for an environment. |
| `docs/` | User-facing architecture, security, operations, development, Intune, and extension docs. |
| `samples/extensions/` | Example collector module, agent tool, and AGT policy extension patterns. |
| `scripts/validation/` | Guarded validation scripts used by CI. |
| `tests/` | Test-plan placeholders for contract, e2e, load, security, and simulator coverage. |
| `design/` | Design background material; docs under `docs/` should be preferred for readers. |

## Prerequisites

- Git, Python 3.12+, Node.js 20+, npm, and PowerShell 7.
- Azure CLI (`az`), Azure Developer CLI (`azd`), and Bicep tooling for Azure deployment work.
- Azure subscription, Entra ID permissions, managed identity/RBAC plan, and target regions.
- Intune permissions for collector packaging, assignment rings, remediation scripts, and certificate deployment.
- Access to the governed Azure SRE Agent/AGT environment for tool integration.

## Quick start: local development

Run components in separate terminals as needed.

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r src/api/requirements.txt
uvicorn app.main:app --app-dir src/api --reload --port 8000
```

```bash
source .venv/bin/activate
pip install -r src/agent-tools/gateway/requirements.txt
uvicorn app.main:app --app-dir src/agent-tools/gateway --reload --port 8001
```

```bash
source .venv/bin/activate
pip install -r src/admin-web/bff/requirements.txt
uvicorn main:app --app-dir src/admin-web/bff --reload --port 8002
```

```bash
cd src/admin-web/frontend
npm install
npm run dev
```

For collector work, use PowerShell 7 and the sample configuration under `src/collector/config/`. Do not bypass the manifest, schema, timeout, redaction, or allowlist checks during local testing.

## Quick start: Azure deployment with AZD

FarSight infrastructure is deployed through AZD/Bicep. Use this flow once the target environment's AZD/Bicep scaffold is present and configured:

```bash
azd auth login
azd env new dev
azd env set AZURE_COLLECTOR_LOCATION italynorth
azd env set AZURE_AGENT_LOCATION swedencentral
azd provision
azd deploy
```

After cloud deployment, package and assign the collector through Intune rings. The collector should receive its endpoint configuration, certificate material, module manifest, and scheduled task through governed Intune workflows.

`azd deploy` builds and pushes container images for the `api`, `admin-web`, and `agent-tools` services, then updates the Container Apps tagged with the matching `azd-service-name`. Bicep uses placeholder images only for initial provisioning.

## Documentation

- [Documentation index and learning path](docs/README.md)
- [Greenfield Azure deployment with private networking](docs/deployment/azure-greenfield-deployment.md)
- [Architecture](docs/architecture/README.md)
- [Security](docs/security/README.md)
- [Collector](docs/collector/README.md)
- [Intune deployment](docs/intune/README.md)
- [Agent tools and AGT governance](docs/agent-tools/README.md)
- [Operations](docs/operations/README.md)
- [Development](docs/development/README.md)
- [Extension guide](docs/extension-guide/README.md)
