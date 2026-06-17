[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallRoot = $(if ($PSScriptRoot) { $PSScriptRoot } else { "$env:ProgramData\Company\SreCollector" }),
    [string]$SourceRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$TaskName = 'Company FarSight Collector',
    [switch]$RegisterScheduledTask
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$directories = @($InstallRoot, (Join-Path $InstallRoot 'config'), (Join-Path $InstallRoot 'logs'), (Join-Path $InstallRoot 'state'), (Join-Path $InstallRoot 'artifacts'), (Join-Path $InstallRoot 'modules'), (Join-Path $InstallRoot 'schemas'))
foreach ($directory in $directories) {
    if ($PSCmdlet.ShouldProcess($directory, 'Create collector directory')) {
        if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    }
}

$taskIntent = [ordered]@{
    taskName = $TaskName
    description = 'Runs the FarSight collector as a bounded single-run scheduled task.'
    executable = 'powershell.exe'
    arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallRoot 'collector.ps1')`" -InstallRoot `"$InstallRoot`""
    triggerIntent = 'Every 5 minutes with deployment-defined jitter'
    runAs = 'SYSTEM or approved least-privilege local identity'
    registeredByThisSkeleton = $false
}
$taskIntentPath = Join-Path (Join-Path $InstallRoot 'config') 'scheduled-task.intent.json'
if ($PSCmdlet.ShouldProcess($taskIntentPath, 'Write scheduled task intent')) {
    $taskIntent | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $taskIntentPath -Encoding UTF8
}
if ($RegisterScheduledTask) {
    Write-Warning 'Scheduled task registration is intentionally not implemented in this skeleton. Deploy through Intune or approved endpoint packaging.'
}

foreach ($name in @('config.sample.json','module-manifest.sample.json')) {
    $sample = Join-Path (Join-Path $SourceRoot 'config') $name
    if (Test-Path -LiteralPath $sample -PathType Leaf) {
        $target = Join-Path (Join-Path $InstallRoot 'config') ($name -replace '\.sample', '')
        if (-not (Test-Path -LiteralPath $target) -and $PSCmdlet.ShouldProcess($target, 'Copy sample configuration')) {
            Copy-Item -LiteralPath $sample -Destination $target -Force
        }
    }
}

[pscustomobject]@{ status = 'Prepared'; installRoot = $InstallRoot; taskIntentPath = $taskIntentPath } | ConvertTo-Json -Depth 4
