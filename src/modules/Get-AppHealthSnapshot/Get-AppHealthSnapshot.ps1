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
$parameters = $ParametersJson | ConvertFrom-Json
$startedAtUtc = [DateTime]::UtcNow.ToString('o')

[pscustomobject]@{
    schemaVersion = '1.0'
    jobId = $JobId
    deviceId = $DeviceId
    correlationId = $CorrelationId
    module = 'Get-AppHealthSnapshot'
    status = 'Succeeded'
    startedAtUtc = $startedAtUtc
    completedAtUtc = [DateTime]::UtcNow.ToString('o')
    summary = [ordered]@{ servicesChecked = 0; processesChecked = 0; warnings = 0 }
    findings = @()
    artifacts = @()
    nextSuggestedModules = @('Test-AppConnectivity', 'Get-ConfigEvidence')
}
