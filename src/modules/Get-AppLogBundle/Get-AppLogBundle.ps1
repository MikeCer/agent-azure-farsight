[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$JobId,
    [Parameter(Mandatory = $true)][string]$DeviceId,
    [Parameter(Mandatory = $true)][string]$CorrelationId,
    [Parameter(Mandatory = $true)][string]$ParametersJson,
    [Parameter(Mandatory = $true)][string]$OutputRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Get-ParameterValue {
    param([Parameter(Mandatory)][AllowNull()]$Source, [Parameter(Mandatory)][string]$Name, $Default = $null)
    if ($null -eq $Source) { return $Default }
    $prop = $Source.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) { return $Default }
    return $prop.Value
}

function Test-IsTextLikeFile {
    param([string]$Extension)
    $textExtensions = @('.log', '.txt', '.json', '.jsonl', '.ndjson', '.csv', '.xml', '.yaml', '.yml', '.ini', '.conf', '.config', '.md', '.tsv')
    return $textExtensions -contains $Extension.ToLowerInvariant()
}

function Test-MatchesFilter {
    param([string]$RelativePath, [string[]]$Filters)
    $name = [System.IO.Path]::GetFileName($RelativePath)
    foreach ($filter in $Filters) {
        if ($name -like $filter -or $RelativePath -like $filter) { return $true }
    }
    return $false
}

function Get-RedactedContent {
    param([string]$Content, [string]$Profile)
    # Patterns that must be redacted regardless of profile.
    $patterns = @(
        # Bearer / JWT tokens
        [regex]'(?i)(Bearer\s+)[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*',
        # Passwords in key=value / JSON-like strings
        [regex]'(?i)("password"\s*:\s*")[^"]+(")',
        [regex]'(?i)(password\s*=\s*)[^\s&;]+',
        # Connection strings with password parts
        [regex]'(?i)(Password|Pwd)=([^;]+)',
        # SAS tokens
        [regex]'(?i)(sig=)[A-Za-z0-9%+/=]+',
        # API keys / secrets patterns
        [regex]'(?i)("(api_?key|secret|token|access_?key)"\s*:\s*")[^"]+(")',
        # PEM private key blocks
        [regex]'-----BEGIN [A-Z ]*PRIVATE KEY-----[^-]+-----END [A-Z ]*PRIVATE KEY-----'
    )
    $redactionCount = 0
    foreach ($pattern in $patterns) {
        $newContent = $pattern.Replace($Content, {
            param($m)
            $redactionCount++
            if ($m.Groups.Count -ge 3) {
                return $m.Groups[1].Value + '[REDACTED]' + $m.Groups[$m.Groups.Count - 1].Value
            }
            return '[REDACTED]'
        })
        if ($newContent -ne $Content) {
            $Content = $newContent
        }
    }

    # Strict profile: also redact email addresses and GUIDs.
    if ($Profile -eq 'strict') {
        $emailPattern = [regex]'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
        $newContent = $emailPattern.Replace($Content, '[EMAIL-REDACTED]')
        if ($newContent -ne $Content) { $redactionCount++; $Content = $newContent }
    }

    return [pscustomobject]@{ Content = $Content; RedactionCount = $redactionCount }
}

function Resolve-AppProfile {
    param([string]$AppId, [string]$ModuleRoot)
    $profilesPath = Join-Path $ModuleRoot 'app-profiles.json'
    # Fall back to sample profiles when a production profiles file is not present.
    if (-not (Test-Path -LiteralPath $profilesPath)) {
        $profilesPath = Join-Path $ModuleRoot 'app-profiles.sample.json'
    }
    if (-not (Test-Path -LiteralPath $profilesPath)) { return $null }
    $profiles = [System.IO.File]::ReadAllText($profilesPath) | ConvertFrom-Json
    foreach ($profile in $profiles) {
        if ($profile.appId -eq $AppId) { return $profile }
    }
    # Fall back to the 'default' profile if the appId is not explicitly registered.
    foreach ($profile in $profiles) {
        if ($profile.appId -eq 'default') { return $profile }
    }
    return $null
}

function Test-IsPathApproved {
    param([string]$ResolvedPath, [string[]]$ApprovedRoots)
    foreach ($root in $ApprovedRoots) {
        try {
            $resolvedRoot = (Resolve-Path -LiteralPath $root -ErrorAction SilentlyContinue)?.Path
            if ($null -eq $resolvedRoot) { continue }
            if ($ResolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        } catch { continue }
    }
    return $false
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

$parameters = $ParametersJson | ConvertFrom-Json
$startedAtUtc = [DateTime]::UtcNow.ToString('o')

try {
    $appId            = [string](Get-ParameterValue $parameters 'appId' -Default '')
    $logPathFolder    = [string](Get-ParameterValue $parameters 'logPathFolder' -Default '')
    $includeFilters   = @(Get-ParameterValue $parameters 'includeFilters' -Default @())
    $excludeFilters   = @(Get-ParameterValue $parameters 'excludeFilters' -Default @())
    $startTimeRaw     = Get-ParameterValue $parameters 'startTimeUtc' -Default $null
    $endTimeRaw       = Get-ParameterValue $parameters 'endTimeUtc' -Default $null
    $recursive        = [bool](Get-ParameterValue $parameters 'recursive' -Default $true)
    $maxDepth         = [int](Get-ParameterValue $parameters 'maxDepth' -Default 3)
    $maxFiles         = [int](Get-ParameterValue $parameters 'maxFiles' -Default 50)
    $maxBytes         = [int](Get-ParameterValue $parameters 'maxBytes' -Default 10485760)
    $tailLines        = Get-ParameterValue $parameters 'tailLines' -Default $null
    $redactionProfile = [string](Get-ParameterValue $parameters 'redactionProfile' -Default 'default')
    $manifestOnly     = [bool](Get-ParameterValue $parameters 'includeManifestOnly' -Default $false)

    # Validate required parameters.
    if ([string]::IsNullOrWhiteSpace($appId)) {
        throw [System.ArgumentException]::new('appId is required.')
    }
    if ([string]::IsNullOrWhiteSpace($logPathFolder)) {
        throw [System.ArgumentException]::new('logPathFolder is required.')
    }

    # Block UNC paths and drive roots before any I/O.
    if ($logPathFolder.StartsWith('\\')) {
        throw [System.ArgumentException]::new('UNC paths are not permitted for logPathFolder.')
    }
    $cleanedPath = $logPathFolder.TrimEnd('\', '/')
    if ($cleanedPath -match '^[A-Za-z]:$') {
        throw [System.ArgumentException]::new('Drive root paths are not permitted for logPathFolder.')
    }
    if ($logPathFolder -match '\.\.[/\\]' -or $logPathFolder -match '[/\\]\.\.' -or $logPathFolder -eq '..') {
        throw [System.ArgumentException]::new('Path traversal sequences are not permitted in logPathFolder.')
    }

    # Resolve the log folder.
    $findings = [System.Collections.Generic.List[object]]::new()
    if (-not (Test-Path -LiteralPath $logPathFolder -PathType Container)) {
        $findings.Add([ordered]@{
            severity = 'error'
            code     = 'log-folder-not-found'
            message  = "Log folder not found: $logPathFolder"
        })
        throw [System.IO.DirectoryNotFoundException]::new("Log folder not found: $logPathFolder")
    }

    $resolvedFolder = (Resolve-Path -LiteralPath $logPathFolder).ProviderPath

    # Load and validate app profile.
    $moduleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $appProfile = Resolve-AppProfile -AppId $appId -ModuleRoot $moduleRoot
    if ($null -eq $appProfile) {
        throw [System.InvalidOperationException]::new("No app profile found for appId: $appId")
    }

    # Validate path is under an approved root.
    if (-not (Test-IsPathApproved -ResolvedPath $resolvedFolder -ApprovedRoots @($appProfile.allowedLogRoots))) {
        $findings.Add([ordered]@{
            severity = 'error'
            code     = 'log-folder-not-approved'
            message  = "logPathFolder is not under an approved root for appId '$appId'."
        })
        throw [System.UnauthorizedAccessException]::new("logPathFolder is not under an approved root for appId '$appId'.")
    }

    # Merge profile defaults with request filters.
    if ($includeFilters.Count -eq 0) { $includeFilters = @($appProfile.defaultIncludeFilters) }
    $allExcludeFilters = @($appProfile.defaultExcludeFilters) + $excludeFilters | Select-Object -Unique

    # Parse time window.
    $startTime = $null
    $endTime   = [DateTime]::UtcNow
    if (-not [string]::IsNullOrWhiteSpace($startTimeRaw)) {
        $startTime = [DateTime]::Parse($startTimeRaw, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
    }
    if (-not [string]::IsNullOrWhiteSpace($endTimeRaw)) {
        $endTime = [DateTime]::Parse($endTimeRaw, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
    }

    # Enumerate files.
    $getChildParams = @{
        LiteralPath = $resolvedFolder
        File        = $true
        ErrorAction = 'SilentlyContinue'
    }
    if ($recursive -and [bool]$appProfile.allowRecursive) {
        $getChildParams['Recurse'] = $true
        $getChildParams['Depth']   = [Math]::Min($maxDepth, [int]$appProfile.maxDepth)
    }

    $allFiles = Get-ChildItem @getChildParams

    # Build candidate list with filtering.
    $candidates = [System.Collections.Generic.List[object]]::new()
    $skipped    = [System.Collections.Generic.List[object]]::new()

    foreach ($file in $allFiles) {
        $relativePath = $file.FullName.Substring($resolvedFolder.Length).TrimStart('\', '/')

        # Symlink/reparse check: ensure target is still inside approved roots.
        if ($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            $skipped.Add([ordered]@{ relativePath = $relativePath; reason = 'reparse-point-skipped' })
            continue
        }

        # Include filter.
        if ($includeFilters.Count -gt 0 -and -not (Test-MatchesFilter -RelativePath $relativePath -Filters $includeFilters)) {
            $skipped.Add([ordered]@{ relativePath = $relativePath; reason = 'include-filter-no-match' })
            continue
        }

        # Exclude filter.
        if ($allExcludeFilters.Count -gt 0 -and (Test-MatchesFilter -RelativePath $relativePath -Filters $allExcludeFilters)) {
            $skipped.Add([ordered]@{ relativePath = $relativePath; reason = 'excluded-by-filter' })
            continue
        }

        # Binary files.
        $ext = $file.Extension
        $isText = Test-IsTextLikeFile -Extension $ext
        if (-not $isText -and -not [bool]$appProfile.allowBinaryFiles) {
            $skipped.Add([ordered]@{ relativePath = $relativePath; reason = 'excluded-binary-file' })
            continue
        }

        # Time window.
        $lastWrite = $file.LastWriteTimeUtc
        if ($null -ne $startTime -and $lastWrite -lt $startTime) {
            $skipped.Add([ordered]@{ relativePath = $relativePath; reason = 'outside-time-window' })
            continue
        }
        if ($lastWrite -gt $endTime) {
            $skipped.Add([ordered]@{ relativePath = $relativePath; reason = 'outside-time-window' })
            continue
        }

        $candidates.Add([pscustomobject]@{
            File         = $file
            RelativePath = $relativePath
            IsText       = $isText
            SizeBytes    = $file.Length
            LastWriteUtc = $lastWrite
        })
    }

    # Sort by most recent first.
    $candidates = @($candidates | Sort-Object -Property LastWriteUtc -Descending)

    if ($candidates.Count -eq 0) {
        $findings.Add([ordered]@{
            severity = 'warning'
            code     = 'no-log-files-matched'
            message  = "No log files matched the include filters and time window under: $logPathFolder"
        })
    }

    # Apply maxFiles and maxBytes caps.
    $selected        = [System.Collections.Generic.List[object]]::new()
    $bytesAccrued    = 0L
    $truncatedFiles  = $false
    $truncatedBytes  = $false

    foreach ($candidate in $candidates) {
        if ($selected.Count -ge $maxFiles) {
            $skipped.Add([ordered]@{ relativePath = $candidate.RelativePath; reason = 'max-files-cap' })
            $truncatedFiles = $true
            continue
        }
        if ($bytesAccrued + $candidate.SizeBytes -gt $maxBytes) {
            $skipped.Add([ordered]@{ relativePath = $candidate.RelativePath; reason = 'max-bytes-cap' })
            $truncatedBytes = $true
            continue
        }
        $bytesAccrued += $candidate.SizeBytes
        $selected.Add($candidate)
    }

    if ($truncatedFiles) {
        $findings.Add([ordered]@{
            severity = 'warning'
            code     = 'collection-truncated-by-file-count'
            message  = "maxFiles cap ($maxFiles) reached; some files were not included."
        })
    }
    if ($truncatedBytes) {
        $findings.Add([ordered]@{
            severity = 'warning'
            code     = 'collection-truncated-by-byte-cap'
            message  = "maxBytes cap ($maxBytes) reached; some files were not included."
        })
    }

    # Check for stale logs.
    if ($selected.Count -gt 0) {
        $latestLog = ($selected | Sort-Object -Property LastWriteUtc -Descending | Select-Object -First 1).LastWriteUtc
        $staleThreshold = [DateTime]::UtcNow.AddHours(-24)
        if ($latestLog -lt $staleThreshold) {
            $findings.Add([ordered]@{
                severity = 'warning'
                code     = 'stale-logs'
                message  = "Latest matched log is older than 24 hours (last write: $($latestLog.ToString('o')))."
            })
        }
    }

    # ---------------------------------------------------------------------------
    # Stage content and produce artifact.
    # ---------------------------------------------------------------------------

    $artifactFolder = Join-Path $OutputRoot 'Get-AppLogBundle'
    if (-not (Test-Path -LiteralPath $artifactFolder)) {
        New-Item -ItemType Directory -Path $artifactFolder -Force | Out-Null
    }

    $stagingFolder = Join-Path $artifactFolder "$JobId-staging"
    $logsFolder    = Join-Path $stagingFolder 'logs'
    New-Item -ItemType Directory -Path $logsFolder -Force | Out-Null

    $manifestEntries   = [System.Collections.Generic.List[object]]::new()
    $totalRedactions   = 0
    $totalPackagedBytes = 0L
    $earliestLog       = [DateTime]::MaxValue
    $latestLog         = [DateTime]::MinValue
    $accessDeniedCount = 0

    foreach ($candidate in $selected) {
        $srcPath      = $candidate.File.FullName
        $safeRelative = $candidate.RelativePath -replace '[\\/:*?"<>|]', '_'
        $destPath     = Join-Path $logsFolder $safeRelative
        $destDir      = Split-Path -Parent $destPath
        if (-not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }

        $redactionCount = 0
        $packagedBytes  = 0L

        try {
            if ($candidate.IsText) {
                $rawContent = [System.IO.File]::ReadAllText($srcPath)

                # Apply tail if requested.
                if ($null -ne $tailLines) {
                    $lines = $rawContent -split "`n"
                    $start = [Math]::Max(0, $lines.Count - [int]$tailLines)
                    $rawContent = ($lines[$start..($lines.Count - 1)]) -join "`n"
                }

                # Redact.
                $redactResult = Get-RedactedContent -Content $rawContent -Profile $redactionProfile
                $rawContent     = $redactResult.Content
                $redactionCount = $redactResult.RedactionCount

                [System.IO.File]::WriteAllText($destPath, $rawContent, [System.Text.Encoding]::UTF8)
            } else {
                Copy-Item -LiteralPath $srcPath -Destination $destPath -Force
            }

            $packagedItem  = Get-Item -LiteralPath $destPath
            $packagedBytes = $packagedItem.Length
            $fileHash      = (Get-FileHash -LiteralPath $destPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $totalPackagedBytes += $packagedBytes
            $totalRedactions    += $redactionCount

            if ($candidate.LastWriteUtc -lt $earliestLog) { $earliestLog = $candidate.LastWriteUtc }
            if ($candidate.LastWriteUtc -gt $latestLog)   { $latestLog   = $candidate.LastWriteUtc }

            if ($redactionCount -gt 0) {
                $findings.Add([ordered]@{
                    severity = 'info'
                    code     = 'redaction-applied'
                    message  = "$redactionCount redaction(s) applied in $($candidate.RelativePath)."
                })
            }

            $manifestEntries.Add([ordered]@{
                relativePath      = $candidate.RelativePath
                included          = $true
                originalSizeBytes = $candidate.SizeBytes
                packagedSizeBytes = $packagedBytes
                lastWriteTimeUtc  = $candidate.LastWriteUtc.ToString('o')
                sha256            = $fileHash
                redactionCount    = $redactionCount
            })
        } catch [System.UnauthorizedAccessException] {
            $accessDeniedCount++
            $skipped.Add([ordered]@{ relativePath = $candidate.RelativePath; reason = 'access-denied' })
        } catch {
            $skipped.Add([ordered]@{ relativePath = $candidate.RelativePath; reason = "read-error: $($_.Exception.Message)" })
        }
    }

    if ($accessDeniedCount -gt 0) {
        $findings.Add([ordered]@{
            severity = 'warning'
            code     = 'access-denied'
            message  = "$accessDeniedCount file(s) could not be read due to access restrictions."
        })
    }

    # Add skipped entries to manifest.
    foreach ($skip in $skipped) {
        $manifestEntries.Add([ordered]@{
            relativePath = $skip.relativePath
            included     = $false
            reason       = $skip.reason
        })
    }

    # Write manifest.json into staging.
    $manifestObj = [ordered]@{
        schemaVersion = '1.0'
        module        = 'Get-AppLogBundle'
        appId         = $appId
        machine       = $DeviceId
        logPathFolder = $logPathFolder
        generatedAtUtc = [DateTime]::UtcNow.ToString('o')
        selection     = [ordered]@{
            includeFilters      = $includeFilters
            excludeFilters      = $allExcludeFilters
            startTimeUtc        = if ($null -ne $startTime) { $startTime.ToString('o') } else { $null }
            endTimeUtc          = $endTime.ToString('o')
            maxFiles            = $maxFiles
            maxBytes            = $maxBytes
            tailLines           = $tailLines
            redactionProfile    = $redactionProfile
        }
        files = $manifestEntries
    }
    $manifestPath = Join-Path $stagingFolder 'manifest.json'
    $manifestObj | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    # Build summary.
    $includedCount = @($manifestEntries | Where-Object { $_.included -eq $true }).Count
    $skippedCount  = @($manifestEntries | Where-Object { $_.included -eq $false }).Count

    $summary = [ordered]@{
        appId             = $appId
        machine           = $DeviceId
        logPathFolder     = $logPathFolder
        matchedFiles      = $candidates.Count
        includedFiles     = $includedCount
        skippedFiles      = $skippedCount
        totalOriginalBytes = $bytesAccrued
        totalPackagedBytes = $totalPackagedBytes
        redactionCount    = $totalRedactions
        earliestLogUtc    = if ($earliestLog -ne [DateTime]::MaxValue) { $earliestLog.ToString('o') } else { $null }
        latestLogUtc      = if ($latestLog -ne [DateTime]::MinValue) { $latestLog.ToString('o') } else { $null }
    }

    # Produce ZIP artifact or return manifest-only.
    $artifacts = @()

    if (-not $manifestOnly -and $includedCount -gt 0) {
        $zipPath = Join-Path $artifactFolder "$JobId-application-logs.zip"
        Compress-Archive -Path (Join-Path $stagingFolder '*') -DestinationPath $zipPath -Force
        $zipItem = Get-Item -LiteralPath $zipPath
        $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $summary['zipSizeBytes'] = $zipItem.Length

        $artifacts += [ordered]@{
            artifactId  = "application-logs-$JobId"
            kind        = 'app-log-bundle'
            name        = $zipItem.Name
            localPath   = $zipPath
            sha256      = $zipHash
            sizeBytes   = $zipItem.Length
        }
    } elseif ($manifestOnly) {
        # Manifest-only mode: return manifest as a JSON artifact.
        $manifestArtifactPath = Join-Path $artifactFolder "$JobId-manifest.json"
        Copy-Item -LiteralPath $manifestPath -Destination $manifestArtifactPath -Force
        $manifestItem = Get-Item -LiteralPath $manifestArtifactPath
        $manifestHash = (Get-FileHash -LiteralPath $manifestArtifactPath -Algorithm SHA256).Hash.ToLowerInvariant()

        $artifacts += [ordered]@{
            artifactId  = "app-log-bundle-manifest-$JobId"
            kind        = 'app-log-bundle-manifest'
            name        = $manifestItem.Name
            localPath   = $manifestArtifactPath
            sha256      = $manifestHash
            sizeBytes   = $manifestItem.Length
        }
    }

    # Clean up staging folder.
    if (Test-Path -LiteralPath $stagingFolder) {
        Remove-Item -LiteralPath $stagingFolder -Recurse -Force -ErrorAction SilentlyContinue
    }

    [pscustomobject]@{
        schemaVersion        = '1.0'
        jobId                = $JobId
        deviceId             = $DeviceId
        correlationId        = $CorrelationId
        module               = 'Get-AppLogBundle'
        status               = 'Succeeded'
        startedAtUtc         = $startedAtUtc
        completedAtUtc       = [DateTime]::UtcNow.ToString('o')
        summary              = $summary
        findings             = $findings.ToArray()
        artifacts            = $artifacts
        nextSuggestedModules = @('Get-AppEventSlice', 'Get-ServiceStatusSnapshot')
    }
}
catch {
    # Clean up staging on failure.
    $stagingFolder = Join-Path (Join-Path $OutputRoot 'Get-AppLogBundle') "$JobId-staging"
    if (Test-Path -LiteralPath $stagingFolder -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $stagingFolder -Recurse -Force -ErrorAction SilentlyContinue
    }

    [pscustomobject]@{
        schemaVersion        = '1.0'
        jobId                = $JobId
        deviceId             = $DeviceId
        correlationId        = $CorrelationId
        module               = 'Get-AppLogBundle'
        status               = 'Failed'
        startedAtUtc         = $startedAtUtc
        completedAtUtc       = [DateTime]::UtcNow.ToString('o')
        summary              = [ordered]@{
            appId         = $appId
            machine       = $DeviceId
            logPathFolder = $logPathFolder
            warnings      = 1
        }
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
}
