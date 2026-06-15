[CmdletBinding(SupportsShouldProcess = $true)]
param([string]$InstallRoot = $(if ($PSScriptRoot) { $PSScriptRoot } else { "$env:ProgramData\Company\SreCollector" }))

Set-StrictMode -Version 2.0
foreach ($directory in @($InstallRoot, (Join-Path $InstallRoot 'logs'), (Join-Path $InstallRoot 'state'), (Join-Path $InstallRoot 'artifacts'))) {
    if (-not (Test-Path -LiteralPath $directory) -and $PSCmdlet.ShouldProcess($directory, 'Create missing collector directory')) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}
[pscustomobject]@{ status = 'RepairSkeletonCompleted'; installRoot = $InstallRoot; repairedAtUtc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Depth 4
