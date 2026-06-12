# Get-AppLogBundle

Collects a bounded bundle of allowlisted application log files.

## Status

Skeleton for V1 collector integration. The implementation must remain read-only, bounded by `input.schema.json`, and compatible with Windows PowerShell 5.1.

## Contract

- Entrypoint: `Get-AppLogBundle.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional, capped by `manifest.fragment.json`

## Safety notes

Do not add arbitrary command execution, unrestricted paths, or unbounded collection. Use allowlisted application profiles and redaction before artifact upload.
