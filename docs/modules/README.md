# Modules

Modules are the only executable diagnostic surface on endpoints. The current catalog includes early read-only module skeletons and an extension sample; production rollout requires schema review, tests, redaction review, and manifest approval.

## V1 module catalog

| Module | Purpose | Risk tier | Notes |
| --- | --- | --- | --- |
| `Get-AppHealthSnapshot` | Early health snapshot for approved application profiles | Low | Built-in skeleton |
| `Get-AppEventSlice` | Early bounded event-log slice collection | Low | Built-in skeleton |
| `Get-AppLogBundle` | Early bounded log bundle collection | Low/Medium by scope | Built-in skeleton |
| `Get-ConfigEvidence` | Early configuration evidence collection | Low | Built-in skeleton |
| `Test-AppConnectivity` | Early connectivity checks to allowlisted endpoints | Low | Built-in skeleton |
| `Get-ServiceStatusSnapshot` | Bounded Windows service inventory with runtime status | Low | Built-in implemented module |
| `Get-AppDiskEvidence` | Sample read-only disk evidence for an allowlisted app profile | Low | Extension sample |

## Module contract

Each module must provide:

- Manifest entry with ID, version, risk tier, timeout, max artifact size, script hash, and schema reference.
- JSON input schema with narrow enums and bounded values.
- PowerShell that performs read-only diagnostics only.
- Result envelope with `schemaVersion`, `moduleId`, `status`, `summary`, `findings`, and optional artifact metadata.
- Tests for validation, redaction, timeout, and failure handling.

## Parameter schema rules

- Prefer enums over free text.
- Use allowlisted paths, profiles, and switches.
- Bound arrays, strings, numbers, and durations.
- Deny script blocks, command strings, wildcards supplied by users, and arbitrary filesystem paths.

## Redaction rules

Redact usernames, tenant IDs where not needed, secrets, tokens, raw certificates, and full local paths unless explicitly approved.

## Known gaps

- Add finalized production module catalog, schema registry link, and module risk review records.
