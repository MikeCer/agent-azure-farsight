# Get-ConfigEvidence

Collects bounded read-only evidence from allowlisted configuration profiles.

## Status

Skeleton for V1 collector integration. The implementation must remain read-only, bounded by `input.schema.json`, and compatible with Windows PowerShell 5.1.

## Contract

- Entrypoint: `Get-ConfigEvidence.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional, capped by `manifest.fragment.json`

## Safety notes

Do not add writes to registry, files, services, or environment. Collect only allowlisted evidence and redact before upload.
