# Test-AppConnectivity

Performs bounded connectivity checks to allowlisted host and port targets.

## Status

Skeleton for V1 collector integration. The implementation must remain read-only, bounded by `input.schema.json`, and compatible with Windows PowerShell 5.1.

## Contract

- Entrypoint: `Test-AppConnectivity.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope
- Artifacts: optional, capped by `manifest.fragment.json`

## Safety notes

Keep checks bounded to allowlisted targets. Do not add port scanning, shell execution, or credentialed network access.
