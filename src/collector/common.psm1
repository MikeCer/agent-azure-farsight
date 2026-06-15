Set-StrictMode -Version 2.0

function Get-FarSightUtcNow {
    [CmdletBinding()]
    param()
    return [DateTime]::UtcNow.ToString('o')
}

function Write-FarSightLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidateSet('Debug','Information','Warning','Error')][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message,
        [hashtable]$Context = @{},
        [string]$LogPath
    )

    $entry = [ordered]@{
        timestampUtc = Get-FarSightUtcNow
        level = $Level
        message = Protect-FarSightText -Text $Message
        context = Protect-FarSightObject -InputObject $Context
    }

    function Resolve-FarSightLogPath {
        [CmdletBinding()]
        param(
            [Parameter(Mandatory = $true)][string]$LogRoot,
            [string]$FileName = 'collector.ndjson'
        )

        if ([string]::IsNullOrWhiteSpace($LogRoot)) {
            throw 'Log root is required'
        }

        if ($LogRoot -match '\.ndjson$') {
            return $LogRoot
        }

        return (Join-Path $LogRoot $FileName)
    }
    $json = $entry | ConvertTo-Json -Depth 8 -Compress
    if ([string]::IsNullOrWhiteSpace($LogPath)) {
        Write-Output $json
        return
    }

    $directory = Split-Path -Parent $LogPath
    if (-not [string]::IsNullOrWhiteSpace($directory) -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    Add-Content -LiteralPath $LogPath -Value $json -Encoding UTF8
}

function Protect-FarSightText {
    [CmdletBinding()]
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) { return $null }
    $redacted = $Text
    foreach ($pattern in @(
        '(?i)(password|passwd|pwd|secret|token|apikey|api_key)\s*[:=]\s*[^\s,;]+',
        '(?i)Bearer\s+[A-Za-z0-9._\-]+',
        '\b[A-Fa-f0-9]{32,}\b'
    )) {
        $redacted = [regex]::Replace($redacted, $pattern, '[REDACTED]')
    }
    return $redacted
}

function Protect-FarSightObject {
    [CmdletBinding()]
    param([AllowNull()]$InputObject)

    if ($null -eq $InputObject) { return $null }
    if ($InputObject -is [string]) { return Protect-FarSightText -Text $InputObject }
    if ($InputObject -is [System.Collections.IDictionary]) {
        $copy = @{}
        foreach ($key in $InputObject.Keys) {
            if ($key -match '(?i)password|secret|token|key|credential') {
                $copy[$key] = '[REDACTED]'
            } else {
                $copy[$key] = Protect-FarSightObject -InputObject $InputObject[$key]
            }
        }
        return $copy
    }
    if ($InputObject -is [System.Collections.IEnumerable] -and -not ($InputObject -is [string])) {
        $items = @()
        foreach ($item in $InputObject) { $items += ,(Protect-FarSightObject -InputObject $item) }
        return $items
    }
    return $InputObject
}

function Read-FarSightJsonFile {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON file not found: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-FarSightManifest {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Manifest)

    $errors = New-Object System.Collections.ArrayList
    if ([string]::IsNullOrWhiteSpace($Manifest.manifestVersion)) { [void]$errors.Add('manifestVersion is required') }
    if ($null -eq $Manifest.modules -or $Manifest.modules.Count -eq 0) { [void]$errors.Add('modules must contain at least one entry') }

    foreach ($module in @($Manifest.modules)) {
        foreach ($property in @('name','version','riskLevel','scriptPath','sha256','timeoutSeconds','maxArtifactBytes','schemaRef')) {
            if ($null -eq $module.$property -or [string]::IsNullOrWhiteSpace([string]$module.$property)) {
                [void]$errors.Add("module '$($module.name)' is missing $property")
            }
        }
        if ($module.scriptPath -match '(^[a-zA-Z]:)|(^\\)|\.\.') {
            [void]$errors.Add("module '$($module.name)' scriptPath must be relative under the module root")
        }
    }

    return [pscustomobject]@{ IsValid = ($errors.Count -eq 0); Errors = @($errors) }
}

function Test-FarSightModuleParameters {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Parameters,
        [Parameter(Mandatory = $true)][string]$SchemaPath
    )

    if (-not (Test-Path -LiteralPath $SchemaPath -PathType Leaf)) {
        return [pscustomobject]@{ IsValid = $false; Errors = @("schema file not found: $SchemaPath") }
    }
    $schema = Read-FarSightJsonFile -Path $SchemaPath
    $errors = New-Object System.Collections.ArrayList
    foreach ($required in @($schema.required)) {
        if ($null -eq $Parameters.$required) { [void]$errors.Add("required parameter missing: $required") }
    }
    return [pscustomobject]@{ IsValid = ($errors.Count -eq 0); Errors = @($errors) }
}

function Invoke-FarSightApi {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][ValidateSet('GET','POST','PUT')][string]$Method,
        [Parameter(Mandatory = $true)][ValidatePattern('^https://')][string]$Uri,
        [object]$Body,
        [hashtable]$Headers = @{},
        [int]$TimeoutSeconds = 30,
        [string]$CertificateThumbprint
    )

    $parameters = @{ Method = $Method; Uri = $Uri; Headers = $Headers; TimeoutSec = $TimeoutSeconds; ErrorAction = 'Stop' }
    if ($null -ne $Body) {
        $parameters['Body'] = ($Body | ConvertTo-Json -Depth 12)
        $parameters['ContentType'] = 'application/json'
    }
    if (-not [string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
        $parameters['CertificateThumbprint'] = $CertificateThumbprint
    }
    return Invoke-RestMethod @parameters
}

function New-FarSightArtifactPackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string[]]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [long]$MaxBytes = 10485760
    )

    $selected = @()
    $totalBytes = 0L
    foreach ($path in $LiteralPath) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $item = Get-Item -LiteralPath $path
        $totalBytes += $item.Length
        if ($totalBytes -gt $MaxBytes) { throw "Artifact package would exceed maximum size of $MaxBytes bytes" }
        $selected += $item.FullName
    }
    if ($selected.Count -eq 0) { throw 'No artifact files selected for packaging' }

    $destinationDirectory = Split-Path -Parent $DestinationPath
    if (-not [string]::IsNullOrWhiteSpace($destinationDirectory) -and -not (Test-Path -LiteralPath $destinationDirectory)) {
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    }
    Compress-Archive -LiteralPath $selected -DestinationPath $DestinationPath -Force
    $hash = Get-FileHash -LiteralPath $DestinationPath -Algorithm SHA256
    $package = Get-Item -LiteralPath $DestinationPath
    return [pscustomobject]@{ path = $package.FullName; sha256 = $hash.Hash.ToLowerInvariant(); sizeBytes = $package.Length }
}

function Invoke-FarSightWithTimeout {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
        [Parameter(Mandatory = $true)][ValidateRange(1, 3600)][int]$TimeoutSeconds,
        [string]$OperationName = 'operation'
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $result = & $ScriptBlock
    $stopwatch.Stop()
    if ($stopwatch.Elapsed.TotalSeconds -gt $TimeoutSeconds) {
        throw "$OperationName exceeded timeout after completion: $([int]$stopwatch.Elapsed.TotalSeconds)s > ${TimeoutSeconds}s"
    }
    return [pscustomobject]@{ Result = $result; DurationMs = $stopwatch.ElapsedMilliseconds }
}

Export-ModuleMember -Function Get-FarSightUtcNow, Write-FarSightLog, Resolve-FarSightLogPath, Protect-FarSightText, Protect-FarSightObject, Read-FarSightJsonFile, Test-FarSightManifest, Test-FarSightModuleParameters, Invoke-FarSightApi, New-FarSightArtifactPackage, Invoke-FarSightWithTimeout
