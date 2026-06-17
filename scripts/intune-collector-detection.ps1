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

    # Check Execute contains powershell.exe (may be full path on some Windows versions)
    $execute = [string]$action.Execute
    if ($execute -inotlike '*powershell.exe') {
        return $false
    }

    # Check Arguments contain the expected script path (use -like for robustness
    # against minor whitespace/quoting differences stored by Task Scheduler)
    $expectedScript = Join-Path $InstallRoot 'collector.ps1'
    $arguments = [string]$action.Arguments
    return ($arguments -ilike "*ExecutionPolicy Bypass*" -and
            $arguments -ilike "*$expectedScript*")
}

function Test-CollectorCertificate {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)

    $configPath = Join-Path $InstallRoot 'config\config.json'
    $profilePath = Join-Path $InstallRoot 'config\certificate-source.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $false
    }

    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $false
    }

    $thumbprint = [string]$config.api.certificateThumbprint
    # If thumbprint is still a placeholder (install-time stamping failed or cert not yet enrolled)
    # treat as not-installed so Intune retries rather than masking the real failure.
    if ([string]::IsNullOrWhiteSpace($thumbprint) -or $thumbprint -like '__*') {
        return $false
    }

    $storeLocation = 'LocalMachine'
    $storeName = 'My'
    if (Test-Path -LiteralPath $profilePath -PathType Leaf) {
        try {
            $profile = Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($profile.storeLocation) { $storeLocation = [string]$profile.storeLocation }
            if ($profile.storeName) { $storeName = [string]$profile.storeName }
        } catch { }
    }

    $storePath = "Cert:\$storeLocation\$storeName"
    if (-not (Test-Path -LiteralPath $storePath)) {
        return $false
    }

    $normalizedThumbprint = $thumbprint.Replace(' ', '').ToUpperInvariant()
    $cert = Get-ChildItem -Path $storePath -ErrorAction SilentlyContinue | Where-Object {
        $_.HasPrivateKey -and
        $_.Thumbprint.Replace(' ', '').ToUpperInvariant() -eq $normalizedThumbprint
    } | Select-Object -First 1

    return ($null -ne $cert)
}

# --- Discovery: enumerate company subfolders under ProgramData directly ---
# Avoid using wildcards in the middle of a path with Get-ChildItem, which can
# be unreliable on some PS 5.1 environments running as SYSTEM.
$programData = [Environment]::GetFolderPath('CommonApplicationData')
$metadataFiles = @()
foreach ($companyDir in (Get-ChildItem -LiteralPath $programData -Directory -ErrorAction SilentlyContinue)) {
    $candidate = Join-Path $companyDir.FullName 'SreCollector\config\package-metadata.json'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $metadataFiles += Get-Item -LiteralPath $candidate
    }
}

foreach ($metadataFile in $metadataFiles) {
    $installRoot = Split-Path -Parent (Split-Path -Parent $metadataFile.FullName)

    if (-not (Test-CollectorFiles -InstallRoot $installRoot)) {
        continue
    }

    try {
        $metadata = Get-Content -LiteralPath $metadataFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        continue
    }

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
