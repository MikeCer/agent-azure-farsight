# Get-AppHealthSnapshot

Captures read-only process, service, and resource health signals for an allowlisted application profile.

## Status

Skeleton for V1 collector integration. The implementation must remain read-only, bounded by `input.schema.json`, and compatible with Windows PowerShell 5.1.

## Contract

- Entrypoint: `Get-AppHealthSnapshot.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional, capped by `manifest.fragment.json`

## Safety notes

Do not add remediation, service restarts, arbitrary process control, or unbounded collection.
