# Get-ServiceStatusSnapshot

Collects a bounded, read-only snapshot of Windows services and their runtime status.

## Status

First production-style built-in module implementation for FarSight flow validation.

## Contract

- Entrypoint: `Get-ServiceStatusSnapshot.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional service snapshot JSON when `includeArtifact` is true

## Safety notes

- Read-only commands only (`Get-Service`, `Get-CimInstance Win32_Service`)
- No free-form command execution
- Bounded output via `maxServices`
- Service account values are redacted except for built-in local service identities
