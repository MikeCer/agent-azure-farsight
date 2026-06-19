# Get-AppLogBundle

Collects a bounded, redacted ZIP artifact of custom application logs from an approved local folder on the endpoint.

## Status

Production-grade implementation. Requires `app-profiles.json` (copy and customise `app-profiles.sample.json`) with production application roots deployed as part of the collector package.

## Contract

- Entrypoint: `Get-AppLogBundle.ps1`
- Input: JSON matching `input.schema.json`
- Output: FarSight module result envelope with a `application-log-zip` artifact containing matched log files and `manifest.json`
- Artifact kind: `application-log-zip` / `application-log-manifest` (dry-run mode)

## Parameters

| Parameter | Required | Purpose |
|---|---|---|
| `appId` | yes | Approved application profile name |
| `logPathFolder` | yes | Local folder containing logs; validated against approved roots in the app profile |
| `includeFilters` | no | Glob filters for files to include |
| `excludeFilters` | no | Glob filters for files to exclude |
| `startTimeUtc` / `endTimeUtc` | no | Last-write time window |
| `recursive` / `maxDepth` | no | Whether to recurse into sub-folders |
| `maxFiles` / `maxBytes` | no | Collection caps |
| `tailLines` | no | Only include the last N lines of each text file |
| `redactionProfile` | no | `default` or `strict` |
| `includeManifestOnly` | no | Dry-run mode: return manifest without ZIP content |

## App profiles

Copy `app-profiles.sample.json` to `app-profiles.json` and populate `allowedLogRoots` with the real application log folder roots before packaging for Intune deployment. The module falls back to `app-profiles.sample.json` when a production file is absent (for local development only).

## Safety notes

- Path is validated against the `allowedLogRoots` from the matched app profile after `Resolve-Path` canonicalization.
- UNC paths, drive roots, and path traversal sequences are rejected before any I/O.
- Reparse points and symlinks are skipped.
- Binary files are excluded unless the app profile sets `allowBinaryFiles: true`.
- Known secret patterns are redacted from text files before packaging.
- The staging folder is cleaned up after ZIP creation and on failure.
