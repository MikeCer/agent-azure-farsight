[CmdletBinding()]
param([string]$InstallRoot = $(
    if ($PSScriptRoot -and (Test-Path -LiteralPath $PSScriptRoot)) { $PSScriptRoot }
    elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path }
    else { "$env:ProgramData\Company\SreCollector" }
))

Set-StrictMode -Version 2.0
$required = @(
    $InstallRoot,
    (Join-Path $InstallRoot 'config\config.json'),
    (Join-Path $InstallRoot 'config\module-manifest.json'),
    (Join-Path $InstallRoot 'logs'),
    (Join-Path $InstallRoot 'state')
)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_) })
$result = [pscustomobject]@{ healthy = ($missing.Count -eq 0); missing = $missing; checkedAtUtc = [DateTime]::UtcNow.ToString('o') }
$result | ConvertTo-Json -Depth 4
if (-not $result.healthy) { exit 1 }
