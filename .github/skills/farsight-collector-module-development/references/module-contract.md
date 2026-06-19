# FarSight collector module contract

## Module folder

Each module lives under `src/modules/<ModuleName>/`.

Required files:

| File | Purpose |
|---|---|
| `<ModuleName>.ps1` | Read-only PowerShell module implementation. |
| `input.schema.json` | Bounded input schema used by the collector before execution. |
| `manifest.fragment.json` | Module manifest metadata merged into packaged collector manifests. |
| `README.md` | Human documentation for behavior, parameters, artifacts, and safety notes. |
| `tests/<ModuleName>.Tests.ps1` | Pester tests for validation, redaction, failure, and result envelope behavior. |

Optional files:

| File | Purpose |
|---|---|
| `app-profiles.sample.json` | Example allowlisted app/path profiles for path-based modules. |
| `redaction-rules.sample.json` | Module-specific redaction examples if generic redaction is insufficient. |

## PowerShell entrypoint contract

Every module script uses this parameter shape:

```powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$JobId,
    [Parameter(Mandatory = $true)][string]$DeviceId,
    [Parameter(Mandatory = $true)][string]$CorrelationId,
    [Parameter(Mandatory = $true)][string]$ParametersJson,
    [Parameter(Mandatory = $true)][string]$OutputRoot
)
```

Baseline script requirements:

```powershell
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$parameters = $ParametersJson | ConvertFrom-Json
$startedAtUtc = [DateTime]::UtcNow.ToString('o')
```

Return a `[pscustomobject]` envelope on both success and failure.

## Result envelope

Success envelope:

```powershell
[pscustomobject]@{
    schemaVersion        = '1.0'
    jobId                = $JobId
    deviceId             = $DeviceId
    correlationId        = $CorrelationId
    module               = '<ModuleName>'
    status               = 'Succeeded'
    startedAtUtc         = $startedAtUtc
    completedAtUtc       = [DateTime]::UtcNow.ToString('o')
    summary              = [ordered]@{}
    findings             = @()
    artifacts            = @()
    nextSuggestedModules = @()
}
```

Failure envelope:

```powershell
[pscustomobject]@{
    schemaVersion        = '1.0'
    jobId                = $JobId
    deviceId             = $DeviceId
    correlationId        = $CorrelationId
    module               = '<ModuleName>'
    status               = 'Failed'
    startedAtUtc         = $startedAtUtc
    completedAtUtc       = [DateTime]::UtcNow.ToString('o')
    summary              = [ordered]@{ warnings = 1 }
    findings             = @(
        [ordered]@{
            severity = 'error'
            code     = 'module-execution-failed'
            message  = [string]$_.Exception.Message
        }
    )
    artifacts            = @()
    nextSuggestedModules = @()
}
```

## Findings

Use stable, machine-readable finding codes. Good examples:

- `input-invalid`
- `approved-profile-not-found`
- `path-not-approved`
- `collection-truncated-by-byte-cap`
- `redaction-applied`
- `artifact-created`

Severity values should be simple lowercase strings:

- `info`
- `warning`
- `error`

## Artifacts

Artifacts are staged locally by the module and uploaded by `collector.ps1`.

Artifact metadata must include:

```powershell
[ordered]@{
    artifactId = "<kind>-$JobId"
    kind       = '<artifact-kind>'
    name       = '<filename>'
    localPath  = $artifactPath
    sha256     = $artifactHash.Hash.ToLowerInvariant()
    sizeBytes  = [int64]$artifactItem.Length
}
```

The collector upload pipeline expects `localPath`; without it, metadata can be recorded but content will not be retrievable.

## JSON schema rules

Use:

- `additionalProperties: false`
- string `minLength` and `maxLength`
- array `maxItems`
- integer `minimum` and `maximum`
- enums for profiles, modes, risk-sensitive options, or known values

Avoid:

- free-form paths;
- free-form command text;
- unbounded arrays;
- unbounded date ranges;
- unconstrained regex supplied by the user.

## Manifest fragment

Example:

```json
{
  "name": "Example-Module",
  "version": "0.1.0",
  "riskLevel": "read-only",
  "scriptPath": "Example-Module/Example-Module.ps1",
  "sha256": "sha256-placeholder",
  "timeoutSeconds": 60,
  "maxArtifactBytes": 524288,
  "allowedPathProfiles": [],
  "schemaRef": "Example-Module/input.schema.json"
}
```

`scripts/build-collector-intunewin.py` discovers module folders under `src/modules/`, asks the operator to select one or many modules, reads each `manifest.fragment.json`, computes script hashes, and writes the final package `module-manifest.json`.

