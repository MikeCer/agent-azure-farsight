# Get-ServiceStatusSnapshot

Collects a bounded, read-only snapshot of Windows services and their runtime status.

## Status

First production-style built-in module implementation for FarSight flow validation.

## Contract

- Entrypoint: `Get-ServiceStatusSnapshot.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional service snapshot JSON when `includeArtifact` is true

## Input parameters

All parameters are optional. No `appId` is required — this is a system-wide service snapshot, not app-scoped.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `serviceNames` | string[] | `[]` | Explicit service names to collect; if empty, returns first `maxServices` sorted by name |
| `includeStartupType` | bool | `true` | Include startup type from WMI |
| `includeServiceAccount` | bool | `false` | Include service account (built-in identities only; others redacted) |
| `includeArtifact` | bool | `false` | Write full service list as a JSON artifact |
| `maxServices` | int | `100` | Maximum number of services to return (1–200) |

## Safety notes

- Read-only commands only (`Get-Service`, `Get-CimInstance Win32_Service`)
- No free-form command execution
- Bounded output via `maxServices`
- Service account values are redacted except for built-in local service identities
