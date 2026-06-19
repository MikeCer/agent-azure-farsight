# Collect-ApplicationLog development plan

## Purpose

`Collect-ApplicationLog` collects a bounded ZIP artifact of custom application logs from a Windows endpoint. It is intended for SRE-agent investigations that start with Intune signals but need deeper app-specific evidence from a known machine and known log folder.

The module must not become arbitrary filesystem collection. It should let the agent request a target machine, an application profile, an approved log folder, filters, and time/size bounds, then return a structured summary plus a ZIP artifact containing only approved, redacted log files.

## Relationship to existing modules

`Get-AppLogBundle` already exists as an early V1 skeleton for bounded allowlisted log bundles. `Collect-ApplicationLog` should either replace that skeleton or become its production-grade successor. The new module differs by requiring a fuller contract:

- explicit `machine`/device target validation;
- approved `logPathFolder` under an application profile;
- include/exclude filters;
- time-window filtering;
- optional tail-only collection;
- ZIP artifact manifest with per-file reasons, hashes, and redaction results;
- SRE-agent-friendly findings for no-match, access-denied, oversize, and stale-log cases.

## Goals

- Collect application logs from a local endpoint path approved by app profile and manifest policy.
- Produce a ZIP artifact that the FarSight artifact pipeline can upload and retrieve.
- Include a `manifest.json` in the ZIP so SRE and automation can inspect what was included or skipped without opening every log.
- Support incident-focused filtering by file name, relative path, last-write time, and optional text tailing.
- Redact known sensitive patterns before packaging when files are text-like.
- Preserve strict module safety: no shell execution, no unbounded paths, no symlink/reparse traversal, no secret exfiltration by default.

## Non-goals

- No arbitrary path collection outside approved app roots.
- No recursive full-disk search.
- No collection of binary dumps, credential stores, private keys, browser data, user document folders, or OS-wide event logs.
- No remote access. The collector runs locally on the target device selected by the job.
- No streaming upload directly from module code. The module writes a local artifact; the collector owns prepare/upload/commit.

## User stories

1. An SRE agent sees an Intune app deployment failure and requests recent logs from the app's known log folder on device `fswin111`.
2. An SRE agent diagnoses a service that is running but unhealthy and collects only files matching `service-*.log` from the last 2 hours.
3. An SRE agent avoids huge rotated logs by requesting only the last 1,000 lines per file.
4. An SRE agent can inspect `manifest.json` to understand which files were included, skipped, or redacted.

## Module identity

| Field | Value |
|---|---|
| Module name | `Collect-ApplicationLog` |
| Risk tier | `read-only` by default; `sensitive-diagnostic` if broad profile, large artifact cap, or redaction disabled in non-prod |
| Script path | `Collect-ApplicationLog/Collect-ApplicationLog.ps1` |
| Schema path | `Collect-ApplicationLog/input.schema.json` |
| Default timeout | 180 seconds |
| Default max artifact bytes | 52,428,800 bytes (50 MB) or lower per app profile |
| Artifact kind | `application-log-zip` |
| Artifact content type | `application/zip` |

## Input contract

The SRE-agent tool should expose these parameters. The module receives them as JSON through `ParametersJson`.

| Parameter | Type | Required | Description | Validation |
|---|---:|---:|---|---|
| `machine` | string | yes | Target device/machine identifier requested by the SRE agent. | Must match the FarSight job `deviceId` or known hostname alias from device metadata. The module must not use this value for remote access. |
| `appId` | string | yes | Approved application profile name. | Must be an enum or allowlisted string in manifest/config, for example `contoso-api`, `winget-cache`, `line-of-business-app`. |
| `logPathFolder` | string | yes | Folder containing application logs on the local machine. | Must resolve under one of the approved roots for `appId`; reject traversal, UNC paths, drive roots, Windows/system folders unless explicitly profiled. |
| `includeFilters` | string[] | no | File name or relative-path filters to include, for example `*.log`, `app-*.jsonl`. | Max 20. No absolute paths. No `..`. Applied to relative path only. Defaults to app profile include filters. |
| `excludeFilters` | string[] | no | File name or relative-path filters to exclude, for example `*.dmp`, `*.bak`, `*secret*`. | Max 20. Applied after include filters. Defaults include sensitive and huge file extensions. |
| `startTimeUtc` | date-time | no | Include files last-written at or after this timestamp. | Must be UTC ISO 8601. Maximum lookback controlled by schema/profile. |
| `endTimeUtc` | date-time | no | Include files last-written before this timestamp. | Must be UTC ISO 8601 and after `startTimeUtc`. Defaults to now. |
| `recursive` | boolean | no | Include child folders. | Defaults to `true` only if app profile permits recursion. |
| `maxDepth` | integer | no | Maximum folder depth below `logPathFolder`. | Range 0-5. Ignored when `recursive=false`. |
| `maxFiles` | integer | no | Maximum number of files included in ZIP. | Range 1-100, profile default 50. |
| `maxBytes` | integer | no | Maximum total bytes read before compression. | Range 1 KB to profile cap, hard cap 50 MB. |
| `tailLines` | integer | no | Include only the last N lines of each text file. | Range 1-20,000. Useful for large text logs. |
| `minSeverity` | string | no | Optional hint for text filters (`trace`, `debug`, `info`, `warning`, `error`, `critical`). | Advisory only unless app profile defines severity parsing rules. |
| `redactionProfile` | string | no | Redaction rule set. | Must be one of profile-approved values. Defaults to `default`. Cannot be `none` in production. |
| `includeManifestOnly` | boolean | no | Return only file selection manifest without ZIP log content. | Useful for dry-run planning; defaults to `false`. |

### Draft JSON schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.farsight.local/modules/Collect-ApplicationLog/input.schema.json",
  "title": "Collect-ApplicationLog input",
  "type": "object",
  "required": ["machine", "appId", "logPathFolder"],
  "properties": {
    "machine": { "type": "string", "minLength": 1, "maxLength": 128 },
    "appId": { "type": "string", "minLength": 1, "maxLength": 64 },
    "logPathFolder": { "type": "string", "minLength": 3, "maxLength": 260 },
    "includeFilters": {
      "type": "array",
      "maxItems": 20,
      "items": { "type": "string", "minLength": 1, "maxLength": 128 }
    },
    "excludeFilters": {
      "type": "array",
      "maxItems": 20,
      "items": { "type": "string", "minLength": 1, "maxLength": 128 }
    },
    "startTimeUtc": { "type": "string", "format": "date-time" },
    "endTimeUtc": { "type": "string", "format": "date-time" },
    "recursive": { "type": "boolean", "default": true },
    "maxDepth": { "type": "integer", "minimum": 0, "maximum": 5, "default": 3 },
    "maxFiles": { "type": "integer", "minimum": 1, "maximum": 100, "default": 50 },
    "maxBytes": { "type": "integer", "minimum": 1024, "maximum": 52428800, "default": 10485760 },
    "tailLines": { "type": "integer", "minimum": 1, "maximum": 20000 },
    "minSeverity": { "type": "string", "enum": ["trace", "debug", "info", "warning", "error", "critical"] },
    "redactionProfile": { "type": "string", "enum": ["default", "strict"], "default": "default" },
    "includeManifestOnly": { "type": "boolean", "default": false }
  },
  "additionalProperties": false
}
```

## Application profile model

The module should not trust `logPathFolder` by itself. It must validate it against an application profile bundled with the collector manifest or a signed profile file.

Example profile:

```json
{
  "appId": "contoso-api",
  "displayName": "Contoso API Client",
  "allowedLogRoots": [
    "C:\\ProgramData\\Contoso\\Logs",
    "C:\\Program Files\\Contoso\\Client\\Logs"
  ],
  "defaultIncludeFilters": ["*.log", "*.jsonl", "*.txt"],
  "defaultExcludeFilters": ["*.dmp", "*.etl", "*.bak", "*secret*", "*token*"],
  "maxBytes": 52428800,
  "maxFiles": 50,
  "allowRecursive": true,
  "maxDepth": 3,
  "redactionProfiles": ["default", "strict"]
}
```

Initial implementation can keep profiles in `src/modules/Collect-ApplicationLog/app-profiles.sample.json` and package production profiles into the collector config/manifest.

## Selection algorithm

1. Parse `ParametersJson`.
2. Validate the `machine` value against the job/device context.
3. Load the app profile for `appId`.
4. Resolve `logPathFolder` with `Resolve-Path -LiteralPath`.
5. Reject if path:
   - does not exist;
   - is not a directory;
   - is a drive root;
   - is a UNC path;
   - contains traversal;
   - resolves outside approved roots;
   - is a reparse point/symlink target outside approved roots.
6. Enumerate files using bounded recursion and `maxDepth`.
7. Apply include filters, then exclude filters.
8. Apply last-write time window.
9. Sort files by `LastWriteTimeUtc` descending.
10. Select until `maxFiles` or `maxBytes` would be exceeded.
11. For each selected file:
    - identify text-like vs binary;
    - if `tailLines` is set and file is text-like, write only tail content to staging;
    - apply redaction to staged text content;
    - compute SHA-256 of staged content;
    - add file entry to `manifest.json`.
12. ZIP staged files plus `manifest.json`.
13. Return summary, findings, and artifact metadata with `localPath`.

## ZIP artifact layout

```text
Collect-ApplicationLog/
  manifest.json
  logs/
    <relative-path-safe-name>.log
    <relative-path-safe-name>.jsonl
```

`manifest.json` example:

```json
{
  "schemaVersion": "1.0",
  "module": "Collect-ApplicationLog",
  "appId": "contoso-api",
  "machine": "fswin111",
  "logPathFolder": "C:\\ProgramData\\Contoso\\Logs",
  "generatedAtUtc": "2026-06-19T08:00:00Z",
  "selection": {
    "includeFilters": ["*.log"],
    "excludeFilters": ["*.dmp", "*secret*"],
    "startTimeUtc": "2026-06-19T06:00:00Z",
    "endTimeUtc": "2026-06-19T08:00:00Z",
    "maxFiles": 50,
    "maxBytes": 10485760,
    "tailLines": 1000
  },
  "files": [
    {
      "relativePath": "app.log",
      "included": true,
      "originalSizeBytes": 421120,
      "packagedSizeBytes": 84231,
      "lastWriteTimeUtc": "2026-06-19T07:59:11Z",
      "sha256": "abc...",
      "redactionCount": 3
    }
  ],
  "skipped": [
    {
      "relativePath": "memory.dmp",
      "reason": "excluded-extension"
    }
  ]
}
```

## Result envelope

Summary fields:

| Field | Description |
|---|---|
| `appId` | Application profile used. |
| `machine` | Target machine/device identifier from request. |
| `logPathFolder` | Requested folder, redacted or normalized as needed. |
| `matchedFiles` | Files matching include/time criteria before caps. |
| `includedFiles` | Files packaged in ZIP. |
| `skippedFiles` | Files skipped with reasons in manifest. |
| `totalOriginalBytes` | Sum of selected original file sizes. |
| `totalPackagedBytes` | Sum of staged file sizes before ZIP. |
| `zipSizeBytes` | Final ZIP artifact size. |
| `redactionCount` | Total redactions across packaged files. |
| `earliestLogUtc` | Earliest included file timestamp. |
| `latestLogUtc` | Latest included file timestamp. |

Findings:

| Code | Severity | Trigger |
|---|---|---|
| `log-folder-not-found` | error | Folder does not exist. |
| `log-folder-not-approved` | error | Folder not under approved app roots. |
| `no-log-files-matched` | warning | No files matched filters/time window. |
| `collection-truncated-by-file-count` | warning | `maxFiles` cap reached. |
| `collection-truncated-by-byte-cap` | warning | `maxBytes` cap reached. |
| `access-denied` | warning | One or more files could not be read. |
| `sensitive-file-excluded` | info | Sensitive extension/name skipped. |
| `redaction-applied` | info | Redactions occurred. |
| `stale-logs` | warning | Latest matched log is older than threshold. |

Artifact metadata:

```json
{
  "artifactId": "application-logs-<jobId>",
  "kind": "application-log-zip",
  "name": "<jobId>-application-logs.zip",
  "localPath": "<collector artifact path>",
  "sha256": "<zip sha256>",
  "sizeBytes": 12345
}
```

## Redaction requirements

Text files must be processed through a redaction pipeline before packaging. Minimum redaction patterns:

- bearer/JWT tokens;
- connection strings;
- passwords and API keys;
- SAS URLs and signed URLs;
- private key PEM blocks;
- email addresses or usernames when not needed for diagnosis;
- tenant IDs where not needed;
- certificate private-key material.

Binary or unknown files should be skipped unless explicitly allowed by app profile.

## Security and safety controls

- Read-only operations only.
- Never execute commands, scripts, or app binaries.
- Use `-LiteralPath` for all filesystem access.
- Reject paths that resolve outside the approved roots after canonicalization.
- Do not follow reparse points unless the resolved target remains inside approved roots.
- Do not include hidden/system files unless app profile explicitly allows them.
- Do not include dump files by default.
- Do not include files larger than the per-file cap.
- Always produce a manifest even when zero files are collected.
- Use stable skip reasons instead of silent omission.

## SRE-agent tool contract

Add or update a PythonFunctionTool wrapper so the SRE agent can call:

```text
Collect-ApplicationLog
```

The wrapper must:

- require `machine`, `appId`, and `logPathFolder`;
- validate filter lengths and counts before calling the gateway;
- pass `machine` as the FarSight device target;
- create a diagnostic job with `taskType=Collect-ApplicationLog`;
- set `riskLevel=read-only` unless policy escalates based on size/window/profile;
- surface the artifact ID and suggested retrieval action once the job completes.

## AGT policy design

`Collect-ApplicationLog` must be explicitly represented in the AGT policy because it can collect application-owned text files that may contain sensitive operational data. The policy should decide whether a request is allowed, denied, or requires approval before a job is created.

### Risk classification

Default risk tier: `read-only`.

Escalate to `sensitive-diagnostic` when any of these are true:

- requested `maxBytes` exceeds the low-risk threshold, for example 10 MB;
- requested `maxFiles` exceeds the low-risk threshold, for example 20 files;
- requested time window exceeds the low-risk window, for example 24 hours;
- requested `tailLines` is not set and full-file collection is requested for text logs;
- requested `appId` belongs to a sensitive application profile;
- requested `logPathFolder` is approved but broad, for example a shared app root instead of a dedicated log folder;
- requested `redactionProfile` is not `strict` for applications known to log identity, tokens, or connection strings.

### Recommended AGT rules

| Rule | Outcome | Condition | Rationale |
|---|---|---|---|
| `deny-unapproved-module` | deny | `tool_name == 'create_diagnostic_job'` and `task_type == 'Collect-ApplicationLog'` and module is not in approved catalog | Prevents undeployed or unreviewed module calls. |
| `deny-freeform-log-path` | deny | `task_type == 'Collect-ApplicationLog'` and `logPathFolder` is not under an approved app profile root | Blocks arbitrary file-system collection. |
| `deny-sensitive-file-filters` | deny | include filters allow dump/key/cert/token/browser/user-document patterns | Prevents predictable secret-heavy artifacts. |
| `deny-redaction-disabled` | deny | production environment and `redactionProfile` is missing, `none`, or not approved for `appId` | Redaction must be mandatory in production. |
| `require-approval-large-log-bundle` | require_approval | `maxBytes > 10485760` or `maxFiles > 20` | Larger bundles increase data exposure and cost. |
| `require-approval-long-window` | require_approval | requested time window exceeds 24 hours | Long windows are more likely to include unrelated sensitive data. |
| `require-approval-sensitive-app` | require_approval | `appId` is tagged `sensitive` | Sensitive apps may log regulated or customer data. |
| `allow-bounded-app-log-collection` | allow | approved app profile, approved path, bounded filters, strict/default redaction, low-risk size/time limits | Standard SRE troubleshooting path. |

### Policy evidence fields

The SRE tool wrapper and gateway should pass enough structured evidence for AGT to decide without parsing free text:

```json
{
  "tool_name": "create_diagnostic_job",
  "task_type": "Collect-ApplicationLog",
  "risk_level": "read-only",
  "device_id": "fswin111",
  "app_id": "contoso-api",
  "log_path_folder": "C:\\ProgramData\\Contoso\\Logs",
  "include_filters": ["*.log"],
  "exclude_filters": ["*.dmp", "*secret*"],
  "start_time_utc": "2026-06-19T06:00:00Z",
  "end_time_utc": "2026-06-19T08:00:00Z",
  "max_files": 20,
  "max_bytes": 10485760,
  "tail_lines": 1000,
  "redaction_profile": "default",
  "app_profile_tags": ["production", "standard"]
}
```

### Example policy sketch

```yaml
- name: deny-collect-application-log-unapproved-path
  condition: "task_type == 'Collect-ApplicationLog' and approved_app_log_path != true"
  action: deny
  description: "Collect-ApplicationLog can only collect from app-profile-approved log folders."

- name: require-approval-for-large-application-log-collection
  condition: "task_type == 'Collect-ApplicationLog' and (max_bytes > 10485760 or max_files > 20 or time_window_hours > 24)"
  action: require_approval
  description: "Large or broad application log collection requires human approval."

- name: allow-bounded-application-log-collection
  condition: "task_type == 'Collect-ApplicationLog' and approved_app_log_path == true and redaction_profile in ['default', 'strict'] and max_bytes <= 10485760 and max_files <= 20"
  action: allow
  description: "Allow bounded, redacted application log collection for approved app profiles."
```

### Admin policy UX expectations

- The policy editor should show `Collect-ApplicationLog` as a catalog module with `read-only` default risk and clear escalation rules.
- Policy validation should fail if `Collect-ApplicationLog` lacks a deny rule for unapproved paths.
- Tool-call telemetry should show whether a request was allowed, denied, or approval-required and include the policy rule name.
- Approval records should include `appId`, `logPathFolder`, time window, `maxBytes`, `maxFiles`, and redaction profile.

## API and gateway changes

- Add `Collect-ApplicationLog` to allowed task types in SRE agent wrappers.
- Add AGT policy rule permitting the module only for approved app profiles.
- Add module manifest fragment and package it into the collector manifest.
- Ensure artifact retrieval supports `application/zip` metadata. Full content retrieval may remain metadata-only if ZIP exceeds content preview caps.
- Admin console job detail should show artifact kind `application-log-zip` and size.

## Files to add

```text
src/modules/Collect-ApplicationLog/
  Collect-ApplicationLog.ps1
  input.schema.json
  manifest.fragment.json
  README.md
  app-profiles.sample.json
  tests/Collect-ApplicationLog.Tests.ps1
```

Optional shared helpers:

```text
src/collector/redaction/
  redaction-rules.json
```

## Test plan

### Unit tests

- Reject missing `machine`, `appId`, or `logPathFolder`.
- Reject path outside approved roots.
- Reject path traversal and UNC paths.
- Reject reparse point escaping approved root.
- Include files matching include filters.
- Exclude files matching exclude filters.
- Enforce time window.
- Enforce `maxFiles`.
- Enforce `maxBytes`.
- Tail text files when `tailLines` is set.
- Redact tokens/secrets in staged content.
- Produce manifest for all included/skipped files.
- Return no-match warning without failing the module.

### Integration tests

- Run module with a temporary app log folder and sample logs.
- Verify ZIP contains `manifest.json` and expected staged logs.
- Verify collector uploads ZIP through artifact pipeline.
- Verify SRE agent can retrieve artifact metadata.

### Negative tests

- Access denied file.
- Huge file above per-file cap.
- Binary file excluded by default.
- Stale logs warning.
- Invalid app profile.
- Invalid date window.

## Acceptance criteria

- A job targeting `Collect-ApplicationLog` can be created through the SRE agent.
- The collector validates schema, app profile, path, filters, and bounds.
- The module produces a structured summary and ZIP artifact with `manifest.json`.
- The collector uploads the artifact and commits metadata.
- The SRE agent can retrieve artifact metadata and explain what was collected.
- No arbitrary paths, command execution, or unredacted known secret patterns are allowed.
- Tests pass for schema validation, path safety, selection, redaction, ZIP packaging, and result envelope generation.

## Implementation phases

1. **Contract**: schema, manifest fragment, README, app profile sample.
2. **Core module**: path validation, file enumeration, filtering, caps, manifest.
3. **Packaging**: ZIP creation, artifact metadata, collector manifest inclusion.
4. **Redaction**: default text redaction pipeline and tests.
5. **SRE tool support**: wrapper task type, AGT policy, result guidance.
6. **Validation**: unit/integration tests and manual run against a sample app profile.
