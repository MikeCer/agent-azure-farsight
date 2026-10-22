# Intune Diagnostics Collector

This project provides the first toolable building block for an Azure SRE Agent that diagnoses one corporate Windows client managed by Intune. It collects read-only evidence from Microsoft Graph and Intune only; it does not access the endpoint directly and does not execute remediation actions.

## Usage

```bash
intune-diagnostics --device-name WIN-CLIENT-001 --auth-mode auto
python -m intune_diagnostics --device-name WIN-CLIENT-001 --output diagnostic.json
```

`--device-name` is required because the Azure SRE Agent will call the script as a tool with the Intune device name. If multiple Intune records share the same name, the script returns structured JSON with an `ambiguous` finding. Optional disambiguators are available:

```bash
intune-diagnostics --device-name WIN-CLIENT-001 --managed-device-id <intune-managed-device-id>
intune-diagnostics --device-name WIN-CLIENT-001 --azure-ad-device-id <entra-device-id>
intune-diagnostics --device-name WIN-CLIENT-001 --serial-number <serial>
```

The JSON output is intentionally optimized for the SRE agent context window. It contains one troubleshooting-focused schema with prioritized issues and only diagnostic evidence useful for client health, startup/performance, app reliability, policy/security, update, and management-channel analysis.

### On-demand sections

Use `--sections cpu`, `--sections memory,cpu`, or `--sections performance` to
collect only the evidence families needed. The Python tool exposes the same
comma-separated `sections` string, defaulting to `full` for compatibility.
Targeted calls skip unrelated Graph queries and return only selected evidence,
plus target identity, scoped assessment/issues, `collection_scope`, and
`data_gaps`. Invalid sections fail before authentication or Graph calls.

`memory` returns installed RAM and an explicit null for unavailable live free
RAM; `cpu` returns processor architecture; `storage` returns disk capacity/free
space. Full mode preserves the existing evidence families and bounded output.
The deployed tool still defaults beta Endpoint Analytics to false: set it true
for full performance/crash analysis. The local CLI retains its beta-enabled
default; `--no-include-beta-endpoint-analytics` disables those sources.

See the [section contract and examples](../../../docs/agent-tools/README.md#intune-on-demand-evidence)
for the complete allowlist, limitations, validation, and deployment steps.

## Build a Single Script

To generate one Python entry script that embeds all local `intune_diagnostics` modules and exposes an Azure SRE Agent-compatible `main(...) -> dict` function:

```bash
python scripts/build_single_script.py
```

The generated file is `dist/intune_diagnostics_tool.py` and is copied to `../agent/tools/intune_diagnostics_tool.py`. Azure SRE Agent deploys it as a `PythonFunctionTool` and calls its typed `main(...)` function. For local CLI testing, use `python -m intune_diagnostics` from the source package instead.

Important: this bundles only this project code. External packages are still required in the runtime environment:

```bash
pip install azure-identity requests
```

## Authentication

The collector uses Microsoft Graph with the `https://graph.microsoft.com/.default` scope.

Supported modes:

- `--auth-mode default`: `DefaultAzureCredential`, intended for managed identity in ADC and local developer credentials.
- `--auth-mode client-secret`: service principal using `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`.
- `--auth-mode auto`: uses complete service-principal environment variables when present; otherwise falls back to `DefaultAzureCredential`. Partial service-principal configuration fails clearly.

For service-principal authentication, set these environment variables before running the script:

| Variable | Description |
| --- | --- |
| `AZURE_TENANT_ID` | Microsoft Entra tenant id that contains the Intune tenant |
| `AZURE_CLIENT_ID` | App registration / service principal client id |
| `AZURE_CLIENT_SECRET` | Client secret for the app registration |

Example:

```bash
export AZURE_TENANT_ID="<tenant-id>"
export AZURE_CLIENT_ID="<app-registration-client-id>"
export AZURE_CLIENT_SECRET="<client-secret>"

python dist/intune_diagnostics_tool.py \
  --device-name WIN-CLIENT-001 \
  --auth-mode client-secret
```

With `--auth-mode auto`, the same variables are used when all three are present. If only one or two are set, the script fails instead of silently falling back to another identity.

Required and optional Microsoft Graph application permissions:

| Permission | Required | Used for |
| --- | --- | --- |
| `DeviceManagementManagedDevices.Read.All` | Yes | Managed-device lookup/detail, health details, device action history, restart/shutdown actions, Windows update joins, Endpoint Analytics joins. |
| `DeviceManagementConfiguration.Read.All` | Yes | Compliance/configuration policy states, setting states, Windows protection state, endpoint security intent states, scripts, and proactive remediation run states. |
| `DeviceManagementApps.Read.All` | Yes | App install status reports and detected app inventory. |
| `DeviceManagementServiceConfig.Read.All` | Yes | Endpoint Analytics data and Autopilot identity/service configuration data. |
| `User.Read.All` | Recommended | User-scoped Intune troubleshooting events under `/users/{userId}/deviceManagementTroubleshootingEvents` when required by tenant policy. |
| `Directory.Read.All` | Recommended | Entra device identity lookup through `/devices`. |

Admin consent is required for unattended service-principal or managed-identity execution.

When Microsoft Graph returns an error, the collector logs the non-sensitive identity context from the access token to stderr, including tenant id, object id, app id, user name when present, and identity type. This helps troubleshoot production permission issues without logging tokens or secrets.

Dynamic Microsoft Graph path segments are percent-encoded before requests are sent. This is required for user-scoped and nested Intune endpoints where identifiers can contain characters such as `/`, `#`, `@`, spaces, or `?`; query options and OData filters are still passed through `requests` parameters so `$filter`, `$select`, and pagination links are not double-encoded.

## Data Sources

The collector uses `v1.0` Intune endpoints for device inventory, compliance/configuration state, user-scoped troubleshooting events, app install status reports, Windows protection state, Windows update status, Entra device identity, and Autopilot identity where available. It also uses Microsoft Graph `beta` Endpoint Analytics endpoints that support per-device lookups for startup performance, resource performance, and app reliability.

Beta-derived signals are marked in the collection report and documented in [`docs/intune-data-catalog.md`](docs/intune-data-catalog.md).

## Output

The script emits deterministic JSON with:

- target device identity
- `assessment`: generated time, highest severity, issue count, performance status, top concerns
- `issues`: prioritized findings with compact evidence and remediation steps
- `diagnostic_evidence`: only useful context for troubleshooting/performance analysis

High-value SRE signals now include:

- Endpoint Analytics startup score, boot/login timing, restarts, and blue screen counts
- Endpoint Analytics resource score, CPU/RAM spike metrics, and hardware sizing
- Endpoint Analytics app reliability score, crash/hang counts, and mean time to failure
- enriched device health details from Intune beta, including encryption state, storage capacity/free space, memory, malware counts, and management certificate expiration
- installed application inventory with app name, publisher, and version
- crashing application list from Endpoint Analytics app health when crash/hang data is available
- recent Intune-initiated restart/shutdown actions
- device timeline events from Intune device actions, troubleshooting events, and matching audit events where available
- setting-level compliance/configuration failures
- app install, Windows update, security, management, identity, and troubleshooting issues only when problematic

PII-like values such as UPN and serial number are redacted by default. Use `--include-pii` only when the execution context and data-handling policy allow it.

## Limitations

- No direct machine access, remote shell, WMI, WinRM, local event logs, or Defender live response.
- Device-name resolution is not guaranteed unique in Intune.
- Some Graph filters are tenant/API dependent; the resolver falls back to capped client-side matching.
- Endpoint Analytics APIs are beta and may change shape.
- Missing optional data is reported as warnings instead of being silently ignored.
- Intune `detectedApp` inventory does not expose the per-device application installation date. The collector cannot include app install dates unless Microsoft Graph adds that field or another tenant-specific report exposes it.
- Intune does not expose raw local Windows Event Log restart/shutdown events through Graph. `recent_restart_shutdown_events` only includes Intune device actions such as `rebootNow`/`shutDown`; true OS event IDs require local collection or a remediation/script that reports them back to Intune.

## Local Windows diagnostics scripts

For deeper root-cause analysis that Intune Graph cannot provide, use the read-only scripts in [`../local-scripts/`](../local-scripts/):

- `Collect-WindowsClientLocalDiagnostics.ps1`: collects local restart/shutdown event IDs, boot performance events, startup commands, auto-start services, disk state, pending reboot flags, Defender state, Intune Management Extension status, and top process snapshots.
- `Remediate-WindowsClientLocalDiagnostics.ps1`: no-op remediation companion for Intune remediation packages.

The collector writes:

```text
C:\ProgramData\AzureSREAgent\local-diagnostics.json
```
