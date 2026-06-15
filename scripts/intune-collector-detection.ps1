[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Test-CollectorFiles {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)

    $requiredFiles = @(
        'collector.ps1',
        'common.psm1',
        'config\config.json',
        'config\module-manifest.json',
        'config\package-metadata.json'
    )

    foreach ($relativePath in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot $relativePath) -PathType Leaf)) {
            return $false
        }
    }

    return $true
}

function Test-CollectorTask {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$TaskName
    )

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        return $false
    }

    $action = $task.Actions | Select-Object -First 1
    if (-not $action) {
        return $false
    }

    $expectedScript = Join-Path $InstallRoot 'collector.ps1'
    $expectedArgument = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$expectedScript`""
    return (
        [string]$action.Execute -ieq 'powershell.exe' -and
        [string]$action.Arguments -eq $expectedArgument
    )
}

function Test-CollectorCertificate {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)

    $configPath = Join-Path $InstallRoot 'config\config.json'
    $profilePath = Join-Path $InstallRoot 'config\certificate-source.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $false
    }

    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $thumbprint = [string]$config.api.certificateThumbprint
    if ([string]::IsNullOrWhiteSpace($thumbprint) -or $thumbprint -like '__*') {
        return $false
    }

    $storeLocation = 'LocalMachine'
    $storeName = 'My'
    if (Test-Path -LiteralPath $profilePath -PathType Leaf) {
        $profile = Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($profile.storeLocation) { $storeLocation = [string]$profile.storeLocation }
        if ($profile.storeName) { $storeName = [string]$profile.storeName }
    }

    $storePath = "Cert:\$storeLocation\$storeName"
    if (-not (Test-Path -LiteralPath $storePath)) {
        return $false
    }

    $cert = Get-ChildItem -Path $storePath | Where-Object {
        $_.HasPrivateKey -and $_.Thumbprint.Replace(' ', '').ToUpperInvariant() -eq $thumbprint.Replace(' ', '').ToUpperInvariant()
    } | Select-Object -First 1

    return ($null -ne $cert)
}

$candidates = Get-ChildItem -Path (Join-Path $env:ProgramData '*\SreCollector\config\package-metadata.json') -File -ErrorAction SilentlyContinue
foreach ($metadataFile in @($candidates)) {
    $installRoot = Split-Path -Parent (Split-Path -Parent $metadataFile.FullName)
    if (-not (Test-CollectorFiles -InstallRoot $installRoot)) {
        continue
    }

    $metadata = Get-Content -LiteralPath $metadataFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskName = [string]$metadata.taskName
    if ([string]::IsNullOrWhiteSpace($taskName)) {
        continue
    }

    if (-not (Test-CollectorTask -InstallRoot $installRoot -TaskName $taskName)) {
        continue
    }

    if (-not (Test-CollectorCertificate -InstallRoot $installRoot)) {
        continue
    }

    exit 0
}

exit 1
