param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("contoso-app", "winget-cache")]
    [string]$Profile,

    [Parameter(Mandatory = $false)]
    [bool]$IncludeFileSamples = $false,

    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 20)]
    [int]$MaxFileSamples = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$moduleId = "Get-AppDiskEvidence"
$schemaVersion = "1.0"

$profiles = @{
    "contoso-app" = @(
        "$env:ProgramData\Contoso\App",
        "$env:ProgramData\Contoso\App\Logs"
    )
    "winget-cache" = @(
        "$env:ProgramData\Microsoft\WinGet",
        "$env:LOCALAPPDATA\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState"
    )
}

function ConvertTo-RedactedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $redacted = $Path
    if ($env:USERNAME) {
        $redacted = $redacted -replace [regex]::Escape($env:USERNAME), "<user>"
    }
    if ($env:USERPROFILE) {
        $redacted = $redacted -replace [regex]::Escape($env:USERPROFILE), "<user-profile>"
    }
    return $redacted
}

try {
    $allowlistedPaths = $profiles[$Profile]
    if (-not $allowlistedPaths) {
        throw "Profile is not allowlisted."
    }

    $findings = @()
    $samples = @()
    $totalBytes = 0
    $existingPathCount = 0

    foreach ($path in $allowlistedPaths) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            $findings += @{
                type = "path_missing"
                severity = "info"
                path = ConvertTo-RedactedPath -Path $path
            }
            continue
        }

        $existingPathCount++
        $files = Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue
        $pathBytes = ($files | Measure-Object -Property Length -Sum).Sum
        if ($null -eq $pathBytes) { $pathBytes = 0 }
        $totalBytes += [int64]$pathBytes

        $findings += @{
            type = "path_summary"
            severity = "info"
            path = ConvertTo-RedactedPath -Path $path
            fileCount = @($files).Count
            totalBytes = [int64]$pathBytes
        }

        if ($IncludeFileSamples -and $MaxFileSamples -gt 0) {
            $samples += $files |
                Sort-Object Length -Descending |
                Select-Object -First $MaxFileSamples |
                ForEach-Object {
                    @{
                        name = $_.Name
                        redactedPath = ConvertTo-RedactedPath -Path $_.FullName
                        length = [int64]$_.Length
                        lastWriteTimeUtc = $_.LastWriteTimeUtc.ToString("o")
                    }
                }
        }
    }

    @{
        schemaVersion = $schemaVersion
        moduleId = $moduleId
        status = "succeeded"
        summary = @{
            profile = $Profile
            existingPathCount = $existingPathCount
            totalBytes = [int64]$totalBytes
            fileSampleCount = @($samples).Count
        }
        findings = $findings
        artifacts = @()
        redactions = @("username", "userProfile")
        collectedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json -Depth 8
}
catch {
    @{
        schemaVersion = $schemaVersion
        moduleId = $moduleId
        status = "failed"
        summary = @{
            profile = $Profile
            errorCode = "module_execution_failed"
        }
        findings = @(
            @{
                type = "error"
                severity = "error"
                message = "The read-only disk evidence module failed safely."
            }
        )
        artifacts = @()
        redactions = @()
        collectedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json -Depth 8
    exit 1
}
