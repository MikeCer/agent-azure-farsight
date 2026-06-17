[CmdletBinding()]
param(
    [string]$InstallRoot = $(
        # $PSScriptRoot is set by PowerShell when the script is loaded via -File.
        # When running under the scheduled task (SYSTEM from System32), $PSScriptRoot
        # is the directory containing collector.ps1 — which is the install root.
        # The Company\SreCollector fallback is only used during manual dev testing.
        if ($PSScriptRoot -and (Test-Path -LiteralPath $PSScriptRoot)) { $PSScriptRoot }
        elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path }
        else { "$env:ProgramData\Company\SreCollector" }
    ),
    [string]$ConfigPath = (Join-Path $InstallRoot 'config\config.json'),
    [string]$ManifestPath = (Join-Path $InstallRoot 'config\module-manifest.json')
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module (Join-Path $scriptRoot 'common.psm1') -Force
$stateRoot = Join-Path $InstallRoot 'state'
$lockPath = Join-Path $stateRoot 'collector.lock'
$lockStream = $null
$logPath = $null  # Initialize early so catch block can reference it

# Ensure state directory exists
if (-not (Test-Path -LiteralPath $stateRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
}

try {
    $config = Read-FarSightJsonFile -Path $ConfigPath
    $logPath = Resolve-FarSightLogPath -LogRoot $config.runtime.logPath
    $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    Write-FarSightLog -Level Information -Message 'Collector run started' -LogPath $logPath
    $manifest = Read-FarSightJsonFile -Path $ManifestPath
    $manifestResult = Test-FarSightManifest -Manifest $manifest
    if (-not $manifestResult.IsValid) { throw ('Invalid module manifest: ' + ($manifestResult.Errors -join '; ')) }

    $statePath = Join-Path $InstallRoot 'state\collector-state.json'
    $state = [ordered]@{ lastRunUtc = Get-FarSightUtcNow; lastExitCode = $null; pendingArtifactCount = 0; lastJobId = $null }
    if (Test-Path -LiteralPath $statePath -PathType Leaf) { $state = Read-FarSightJsonFile -Path $statePath }

    $checkInBody = [ordered]@{
        schemaVersion = '1.0'
        deviceId = $config.device.deviceId
        tenantId = $config.device.tenantId
        collectorVersion = $config.collectorVersion
        manifestVersion = $manifest.manifestVersion
        hostname = if ($config.device.hostname) { $config.device.hostname } else { $config.device.deviceId }
        hostnameHash = $config.device.hostnameHash
        appliedConfigVersion = if ($config.device.appliedConfigVersion) { $config.device.appliedConfigVersion } else { $null }
        os = [ordered]@{ name = 'Windows'; version = [Environment]::OSVersion.Version.ToString() }
        lastJobId = $state.lastJobId
        localState = $state
    }
    $headers = @{ 'x-farsight-client' = 'endpoint-collector' }
    $checkIn = Invoke-FarSightApi -Method POST -Uri ($config.api.baseUrl.TrimEnd('/') + '/api/v1/devices/checkin') -Body $checkInBody -Headers $headers -TimeoutSeconds $config.api.timeoutSeconds -CertificateThumbprint $config.api.certificateThumbprint

    # Apply remote configuration if the server pushed a new version.
    if ($checkIn.pendingConfig -and $checkIn.pendingConfig.configVersion -and
        $checkIn.pendingConfig.configVersion -ne $config.device.appliedConfigVersion) {
        try {
            $cfg = $checkIn.pendingConfig
            Write-FarSightLog -Level Information -Message 'Applying remote configuration' -LogPath $logPath -Context @{ configVersion = $cfg.configVersion }

            # Update scheduled task repetition interval if specified.
            # Must create a fresh trigger object — CimInstance properties are read-only.
            if ($cfg.scheduledTaskIntervalMinutes) {
                $taskName = 'FarSight Collector'
                $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
                if ($task) {
                    $intervalMinutes = [int]$cfg.scheduledTaskIntervalMinutes
                    # Build a new trigger via the task XML so the repetition interval is set correctly.
                    $taskXml = [xml]($task | Export-ScheduledTask)
                    $ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
                    $triggerNode = $taskXml.Task.Triggers.ChildNodes | Select-Object -First 1
                    if ($triggerNode -and $triggerNode.Repetition) {
                        $isoDuration = 'PT{0}M' -f $intervalMinutes
                        $triggerNode.Repetition.Interval = $isoDuration
                        Register-ScheduledTask -Xml $taskXml.OuterXml -TaskName $taskName -Force | Out-Null
                        Write-FarSightLog -Level Information -Message 'Scheduled task interval updated' -LogPath $logPath -Context @{ intervalMinutes = $intervalMinutes }
                    }
                }
            }

            # Update runtime config in config.json.
            $configObj = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.maxSingleRunSeconds) { $configObj.runtime.maxSingleRunSeconds = [int]$cfg.maxSingleRunSeconds }
            if ($cfg.logRetentionDays) { $configObj.runtime.logRetentionDays = [int]$cfg.logRetentionDays }
            if (-not $configObj.device.PSObject.Properties['appliedConfigVersion']) {
                $configObj.device | Add-Member -NotePropertyName 'appliedConfigVersion' -NotePropertyValue $cfg.configVersion
            } else {
                $configObj.device.appliedConfigVersion = $cfg.configVersion
            }
            $configObj | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

            # Reload config to pick up changes for this run.
            $config = Read-FarSightJsonFile -Path $ConfigPath
            Write-FarSightLog -Level Information -Message 'Remote configuration applied' -LogPath $logPath -Context @{ configVersion = $cfg.configVersion }
        } catch {
            Write-FarSightLog -Level Warning -Message "Failed to apply remote configuration: $_" -LogPath $logPath
        }
    }

    if (-not $checkIn.jobAvailable) {
        Write-FarSightLog -Level Information -Message 'No job available' -LogPath $logPath -Context @{ nextCheckInAfterSeconds = $checkIn.nextCheckInAfterSeconds }
        $state.lastRunUtc = Get-FarSightUtcNow
        $state.lastExitCode = 0
        $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8
        return
    }

    $job = Invoke-FarSightApi -Method GET -Uri ($config.api.baseUrl.TrimEnd('/') + '/api/v1/jobs/' + [uri]::EscapeDataString($checkIn.job.jobId)) -Headers $headers -TimeoutSeconds $config.api.timeoutSeconds -CertificateThumbprint $config.api.certificateThumbprint
    $moduleEntry = @($manifest.modules | Where-Object { $_.name -eq $job.taskType }) | Select-Object -First 1
    if ($null -eq $moduleEntry) { throw "Job taskType is not allowlisted by local manifest: $($job.taskType)" }

    $moduleRoot = Join-Path $InstallRoot 'modules'
    if (-not (Test-Path -LiteralPath $moduleRoot)) { $moduleRoot = Join-Path $scriptRoot '..\modules' }
    $resolvedModuleRoot = (Resolve-Path -LiteralPath $moduleRoot).ProviderPath
    $resolvedModulePath = (Resolve-Path -LiteralPath (Join-Path $moduleRoot $moduleEntry.scriptPath)).ProviderPath
    if (-not $resolvedModulePath.StartsWith($resolvedModuleRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Resolved module path escaped the configured module root'
    }
    $actualHash = (Get-FileHash -LiteralPath $resolvedModulePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($moduleEntry.sha256 -ne 'sha256-placeholder' -and $actualHash -ne $moduleEntry.sha256.ToLowerInvariant()) {
        throw "Module hash mismatch for $($moduleEntry.name)"
    }

    $parameterValidation = Test-FarSightModuleParameters -Parameters $job.parameters -SchemaPath (Join-Path $moduleRoot $moduleEntry.schemaRef)
    if (-not $parameterValidation.IsValid) { throw ('Invalid module parameters: ' + ($parameterValidation.Errors -join '; ')) }

    $startedAtUtc = Get-FarSightUtcNow
    $moduleResult = Invoke-FarSightWithTimeout -TimeoutSeconds ([int]$moduleEntry.timeoutSeconds) -OperationName $moduleEntry.name -ScriptBlock {
        & $resolvedModulePath -JobId $job.jobId -DeviceId $config.device.deviceId -CorrelationId $job.correlationId -ParametersJson ($job.parameters | ConvertTo-Json -Depth 12) -OutputRoot (Join-Path $InstallRoot 'artifacts')
    }

    # Upload artifacts to blob storage via prepare/commit API calls.
    $uploadedArtifacts = @()
    foreach ($artifact in @($moduleResult.Result.artifacts)) {
        $artifactLocalPath = $artifact.localPath
        if (-not $artifactLocalPath -or -not (Test-Path -LiteralPath $artifactLocalPath -PathType Leaf)) {
            # No local file — include metadata only, content won't be retrievable.
            $uploadedArtifacts += $artifact
            continue
        }
        try {
            $fileBytes = [System.IO.File]::ReadAllBytes($artifactLocalPath)
            $sha256Bytes = [System.Security.Cryptography.SHA256]::Create().ComputeHash($fileBytes)
            $sha256Hex = ($sha256Bytes | ForEach-Object { $_.ToString('x2') }) -join ''
            $fileName = [System.IO.Path]::GetFileName($artifactLocalPath)
            $contentType = if ($fileName -like '*.json') { 'application/json' } else { 'text/plain' }
            $sizeBytes = $fileBytes.Length

            # Request a pre-signed upload URL from the API.
            $prepareBody = [ordered]@{
                jobId = $job.jobId
                artifactId = $artifact.artifactId
                fileName = $fileName
                contentType = $contentType
                sizeBytes = $sizeBytes
                sha256 = $sha256Hex
            }
            $prepareResp = Invoke-FarSightApi -Method POST -Uri ($config.api.baseUrl.TrimEnd('/') + '/api/v1/artifacts/prepare') -Body $prepareBody -Headers $headers -TimeoutSeconds $config.api.timeoutSeconds -CertificateThumbprint $config.api.certificateThumbprint

            # Upload the file directly to blob storage.
            $uploadHeaders = @{ 'x-ms-blob-type' = 'BlockBlob'; 'Content-Type' = $contentType }
            foreach ($h in $prepareResp.requiredHeaders.PSObject.Properties) { $uploadHeaders[$h.Name] = $h.Value }
            $uploadResp = Invoke-WebRequest -Uri $prepareResp.uploadUrl -Method PUT -Body $fileBytes -Headers $uploadHeaders -UseBasicParsing -ErrorAction Stop
            if ($uploadResp.StatusCode -notin @(200, 201)) { throw "Blob upload returned HTTP $($uploadResp.StatusCode)" }

            # Commit the upload so the API indexes it.
            $commitBody = [ordered]@{ jobId = $job.jobId; artifactId = $artifact.artifactId; uploaded = $true; sha256 = $sha256Hex }
            Invoke-FarSightApi -Method POST -Uri ($config.api.baseUrl.TrimEnd('/') + '/api/v1/artifacts/commit') -Body $commitBody -Headers $headers -TimeoutSeconds $config.api.timeoutSeconds -CertificateThumbprint $config.api.certificateThumbprint | Out-Null

            Write-FarSightLog -Level Information -Message 'Artifact uploaded' -LogPath $logPath -Context @{ artifactId = $artifact.artifactId; sizeBytes = $sizeBytes }
            $uploadedArtifacts += $artifact
        } catch {
            Write-FarSightLog -Level Warning -Message "Artifact upload failed for $($artifact.artifactId): $_" -LogPath $logPath
            $uploadedArtifacts += $artifact  # Still include metadata even if upload failed
        }
    }

    $resultEnvelope = [ordered]@{
        schemaVersion = '1.0'
        jobId = $job.jobId
        deviceId = $config.device.deviceId
        correlationId = $job.correlationId
        module = $moduleEntry.name
        status = 'Succeeded'
        startedAtUtc = $startedAtUtc
        completedAtUtc = Get-FarSightUtcNow
        summary = $moduleResult.Result.summary
        findings = $moduleResult.Result.findings
        artifacts = $uploadedArtifacts
        nextSuggestedModules = $moduleResult.Result.nextSuggestedModules
    }
    Invoke-FarSightApi -Method POST -Uri ($config.api.baseUrl.TrimEnd('/') + '/api/v1/jobs/' + [uri]::EscapeDataString($job.jobId) + '/results') -Body $resultEnvelope -Headers $headers -TimeoutSeconds $config.api.timeoutSeconds -CertificateThumbprint $config.api.certificateThumbprint | Out-Null
    Write-FarSightLog -Level Information -Message 'Collector job completed' -LogPath $logPath -Context @{ jobId = $job.jobId; module = $moduleEntry.name }
    $state.lastRunUtc = Get-FarSightUtcNow
    $state.lastExitCode = 0
    $state.lastJobId = $job.jobId
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8
}
catch {
    if ($null -ne $logPath) {
        Write-FarSightLog -Level Error -Message $_.Exception.Message -LogPath $logPath
    }
    throw
}
finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
}
