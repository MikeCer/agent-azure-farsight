# Get-AppEventSlice

Reads a bounded slice from allowlisted Windows Event Logs.

## Status

Skeleton for V1 collector integration. The implementation must remain read-only, bounded by `input.schema.json`, and compatible with Windows PowerShell 5.1.

## Contract

- Entrypoint: `Get-AppEventSlice.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional, capped by `manifest.fragment.json`

## Safety notes

Do not add arbitrary command execution, unrestricted event logs, or unbounded collection. Use allowlisted providers and redaction before artifact upload.
