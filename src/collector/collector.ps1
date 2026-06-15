[CmdletBinding()]
param(
    [string]$InstallRoot = $(if ($PSScriptRoot) { $PSScriptRoot } else { "$env:ProgramData\Company\SreCollector" }),
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
        hostnameHash = $config.device.hostnameHash
        os = [ordered]@{ name = 'Windows'; version = [Environment]::OSVersion.Version.ToString() }
        lastJobId = $state.lastJobId
        localState = $state
    }
    $headers = @{ 'x-farsight-client' = 'endpoint-collector' }
    $checkIn = Invoke-FarSightApi -Method POST -Uri ($config.api.baseUrl.TrimEnd('/') + '/api/v1/devices/checkin') -Body $checkInBody -Headers $headers -TimeoutSeconds $config.api.timeoutSeconds -CertificateThumbprint $config.api.certificateThumbprint
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
        artifacts = $moduleResult.Result.artifacts
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
