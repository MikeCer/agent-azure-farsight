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

function Get-ParameterValue {
    param(
        [Parameter(Mandatory = $true)]$Source,
        [Parameter(Mandatory = $true)][string]$Name,
        $Default = $null
    )

    if ($null -eq $Source) { return $Default }
    $property = $Source.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    if ($null -eq $property.Value) { return $Default }
    return $property.Value
}

function Protect-ServiceAccount {
    param([AllowNull()][string]$Account)

    if ([string]::IsNullOrWhiteSpace($Account)) { return $null }
    $normalized = $Account.Trim()
    if ($normalized -in @('LocalSystem', 'LocalService', 'NetworkService', 'NT AUTHORITY\LocalService', 'NT AUTHORITY\NetworkService')) {
        return $normalized
    }
    return '[REDACTED]'
}

$parameters = $ParametersJson | ConvertFrom-Json
$startedAtUtc = [DateTime]::UtcNow.ToString('o')

try {
    $serviceNames = @()
    $serviceNamesInput = Get-ParameterValue -Source $parameters -Name 'serviceNames' -Default @()
    foreach ($name in @($serviceNamesInput)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$name)) {
            $serviceNames += [string]$name
        }
    }

    $includeStartupType = [bool](Get-ParameterValue -Source $parameters -Name 'includeStartupType' -Default $true)
    $includeServiceAccount = [bool](Get-ParameterValue -Source $parameters -Name 'includeServiceAccount' -Default $false)
    $includeArtifact = [bool](Get-ParameterValue -Source $parameters -Name 'includeArtifact' -Default $false)
    $maxServicesRaw = [int](Get-ParameterValue -Source $parameters -Name 'maxServices' -Default 100)
    $maxServices = [Math]::Min([Math]::Max($maxServicesRaw, 1), 200)

    $cimByName = @{}
    foreach ($item in Get-CimInstance -ClassName Win32_Service) {
        $cimByName[$item.Name] = $item
    }

    $selectedServices = @()
    if ($serviceNames.Count -gt 0) {
        foreach ($requestedName in $serviceNames) {
            $service = Get-Service -Name $requestedName -ErrorAction SilentlyContinue
            if ($null -ne $service) {
                $selectedServices += $service
            }
        }
    } else {
        $selectedServices = @(Get-Service | Sort-Object -Property Name)
    }

    $selectedServices = @($selectedServices | Select-Object -First $maxServices)
    $missingServices = @($serviceNames | Where-Object { $_ -notin $selectedServices.Name })

    $runningCount = 0
    $stoppedCount = 0
    $disabledCount = 0
    $warningCount = 0
    $findings = @()
    $rows = @()

    foreach ($service in $selectedServices) {
        $statusText = [string]$service.Status
        if ($statusText -eq 'Running') {
            $runningCount++
        } else {
            $warningCount++
            if ($statusText -eq 'Stopped') { $stoppedCount++ }
            $findings += [ordered]@{
                severity = 'warning'
                code = 'service-not-running'
                message = "Service '$($service.Name)' is $statusText."
            }
        }

        $startupType = $null
        $serviceAccount = $null
        $cim = $cimByName[[string]$service.Name]
        if ($null -ne $cim) {
            if ($includeStartupType) { $startupType = [string]$cim.StartMode }
            if ([string]$cim.StartMode -eq 'Disabled') { $disabledCount++ }
            if ($includeServiceAccount) { $serviceAccount = Protect-ServiceAccount -Account ([string]$cim.StartName) }
        }

        $row = [ordered]@{
            serviceName = [string]$service.Name
            displayName = [string]$service.DisplayName
            status = $statusText
        }
        if ($includeStartupType) { $row.startupType = $startupType }
        if ($includeServiceAccount) { $row.serviceAccount = $serviceAccount }
        $rows += $row
    }

    foreach ($missing in $missingServices) {
        $warningCount++
        $findings += [ordered]@{
            severity = 'warning'
            code = 'service-not-found'
            message = "Requested service '$missing' was not found."
        }
    }

    $artifacts = @()
    if ($includeArtifact) {
        $artifactFolder = Join-Path $OutputRoot 'Get-ServiceStatusSnapshot'
        if (-not (Test-Path -LiteralPath $artifactFolder)) {
            New-Item -ItemType Directory -Path $artifactFolder -Force | Out-Null
        }
        $artifactPath = Join-Path $artifactFolder "$($JobId)-services.json"
        $rows | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $artifactPath -Encoding UTF8
        $artifactItem = Get-Item -LiteralPath $artifactPath
        $artifactHash = Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256
        $artifacts += [ordered]@{
            artifactId = "services-$JobId"
            kind = 'service-snapshot'
            name = [string]$artifactItem.Name
            localPath = $artifactPath
            sha256 = $artifactHash.Hash.ToLowerInvariant()
            sizeBytes = [int64]$artifactItem.Length
        }
    }

    [pscustomobject]@{
        schemaVersion = '1.0'
        jobId = $JobId
        deviceId = $DeviceId
        correlationId = $CorrelationId
        module = 'Get-ServiceStatusSnapshot'
        status = 'Succeeded'
        startedAtUtc = $startedAtUtc
        completedAtUtc = [DateTime]::UtcNow.ToString('o')
        summary = [ordered]@{
            servicesEvaluated = $rows.Count
            servicesRequested = $serviceNames.Count
            missingServices = $missingServices.Count
            runningServices = $runningCount
            stoppedServices = $stoppedCount
            disabledServices = $disabledCount
            warnings = $warningCount
        }
        findings = $findings
        artifacts = $artifacts
        nextSuggestedModules = @('Get-AppEventSlice', 'Get-ConfigEvidence')
    }
}
catch {
    [pscustomobject]@{
        schemaVersion = '1.0'
        jobId = $JobId
        deviceId = $DeviceId
        correlationId = $CorrelationId
        module = 'Get-ServiceStatusSnapshot'
        status = 'Failed'
        startedAtUtc = $startedAtUtc
        completedAtUtc = [DateTime]::UtcNow.ToString('o')
        summary = [ordered]@{
            servicesEvaluated = 0
            warnings = 1
        }
        findings = @(
            [ordered]@{
                severity = 'error'
                code = 'module-execution-failed'
                message = [string]$_.Exception.Message
            }
        )
        artifacts = @()
        nextSuggestedModules = @()
    }
}
