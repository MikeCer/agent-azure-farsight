# Pester tests for Get-AppLogBundle.

Describe 'Get-AppLogBundle' {

    BeforeAll {
        $script:ModuleScript = Join-Path $PSScriptRoot '..' 'Get-AppLogBundle.ps1'
        $script:TempRoot = Join-Path $TestDrive 'output'
        New-Item -ItemType Directory -Path $script:TempRoot -Force | Out-Null

        function Invoke-Module {
            param([hashtable]$Params)
            $json = $Params | ConvertTo-Json -Depth 10
            & $script:ModuleScript `
                -JobId         ($Params.JobId ?? 'test-job-001') `
                -DeviceId      ($Params.DeviceId ?? 'test-device') `
                -CorrelationId ($Params.CorrelationId ?? 'test-corr-001') `
                -ParametersJson $json `
                -OutputRoot    $script:TempRoot
        }
    }

    Context 'Parameter validation' {

        It 'fails with missing appId' {
            $result = Invoke-Module @{ logPathFolder = 'C:\Temp' }
            $result.status | Should -Be 'Failed'
            $result.findings[0].code | Should -Be 'module-execution-failed'
        }

        It 'fails with missing logPathFolder' {
            $result = Invoke-Module @{ appId = 'default' }
            $result.status | Should -Be 'Failed'
        }

        It 'fails when logPathFolder is a UNC path' {
            $result = Invoke-Module @{ appId = 'default'; logPathFolder = '\\server\share\logs' }
            $result.status | Should -Be 'Failed'
            $result.findings[0].message | Should -BeLike '*UNC*'
        }

        It 'fails when logPathFolder is a drive root' {
            $result = Invoke-Module @{ appId = 'default'; logPathFolder = 'C:' }
            $result.status | Should -Be 'Failed'
        }

        It 'fails when logPathFolder contains path traversal' {
            $result = Invoke-Module @{ appId = 'default'; logPathFolder = 'C:\Logs\..\Windows' }
            $result.status | Should -Be 'Failed'
        }
    }

    Context 'Folder not found' {

        It 'returns error finding when folder does not exist' {
            $result = Invoke-Module @{ appId = 'default'; logPathFolder = 'C:\NonExistent\Path\That\Should\Not\Exist' }
            $result.status | Should -Be 'Failed'
            $errorCodes = $result.findings | ForEach-Object { $_.code }
            $errorCodes | Should -Contain 'log-folder-not-found'
        }
    }

    Context 'Approved path validation' {

        It 'fails when logPathFolder is outside approved roots' {
            $result = Invoke-Module @{ appId = 'default'; logPathFolder = 'C:\Windows\System32' }
            $result.status | Should -Be 'Failed'
            $errorCodes = $result.findings | ForEach-Object { $_.code }
            $errorCodes | Should -Contain 'log-folder-not-approved'
        }
    }

    Context 'Log collection' {

        BeforeAll {
            # Create a sample log folder under ProgramData (which is the approved default root).
            $script:LogDir = Join-Path $env:ProgramData 'FarSightTestLogs'
            New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null

            Set-Content -LiteralPath (Join-Path $script:LogDir 'app.log')    -Value "line1`nline2`nline3"
            Set-Content -LiteralPath (Join-Path $script:LogDir 'app2.log')   -Value "info log entry"
            Set-Content -LiteralPath (Join-Path $script:LogDir 'dump.dmp')   -Value "binary-ish content"
            Set-Content -LiteralPath (Join-Path $script:LogDir 'secret.log') -Value "password=mysecret123"
        }

        AfterAll {
            if (Test-Path -LiteralPath $script:LogDir) {
                Remove-Item -LiteralPath $script:LogDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }

        It 'collects matching log files and produces a ZIP artifact' {
            $result = Invoke-Module @{
                appId         = 'default'
                logPathFolder = $script:LogDir
                includeFilters = @('*.log')
            }
            $result.status | Should -Be 'Succeeded'
            $result.summary.includedFiles | Should -BeGreaterOrEqual 1
            $result.artifacts.Count | Should -BeGreaterOrEqual 1
            $result.artifacts[0].kind | Should -Be 'application-log-zip'
            Test-Path -LiteralPath $result.artifacts[0].localPath | Should -BeTrue
        }

        It 'excludes dump files by default' {
            $result = Invoke-Module @{
                appId         = 'default'
                logPathFolder = $script:LogDir
                includeFilters = @('*.log', '*.dmp')
            }
            $result.status | Should -Be 'Succeeded'
            $skippedDump = $result.summary.skippedFiles
            # The .dmp file should appear skipped in the manifest.
            $skippedDump | Should -BeGreaterOrEqual 1
        }

        It 'returns warning finding when no files match filters' {
            $result = Invoke-Module @{
                appId         = 'default'
                logPathFolder = $script:LogDir
                includeFilters = @('*.xyz_nonexistent')
            }
            $result.status | Should -Be 'Succeeded'
            $warningCodes = $result.findings | ForEach-Object { $_.code }
            $warningCodes | Should -Contain 'no-log-files-matched'
        }

        It 'redacts known secret patterns in text files' {
            $result = Invoke-Module @{
                appId         = 'default'
                logPathFolder = $script:LogDir
                includeFilters = @('secret.log')
            }
            $result.status | Should -Be 'Succeeded'
            $result.summary.redactionCount | Should -BeGreaterOrEqual 1
            $redactionFindings = $result.findings | Where-Object { $_.code -eq 'redaction-applied' }
            $redactionFindings.Count | Should -BeGreaterOrEqual 1
        }

        It 'supports manifest-only dry-run mode' {
            $result = Invoke-Module @{
                appId               = 'default'
                logPathFolder       = $script:LogDir
                includeManifestOnly = $true
            }
            $result.status | Should -Be 'Succeeded'
            $result.artifacts[0].kind | Should -BeLike '*manifest*'
        }

        It 'honours maxFiles cap and emits truncation warning' {
            $result = Invoke-Module @{
                appId         = 'default'
                logPathFolder = $script:LogDir
                includeFilters = @('*.log')
                maxFiles       = 1
            }
            $result.status | Should -Be 'Succeeded'
            $result.summary.includedFiles | Should -BeLessOrEqual 1
            $warningCodes = $result.findings | ForEach-Object { $_.code }
            if ($result.summary.matchedFiles -gt 1) {
                $warningCodes | Should -Contain 'collection-truncated-by-file-count'
            }
        }
    }

    Context 'Result envelope structure' {

        It 'always returns a valid FarSight module envelope' {
            $result = Invoke-Module @{ appId = 'default'; logPathFolder = 'C:\Windows\NonExistent' }
            $result.schemaVersion | Should -Not -BeNullOrEmpty
            $result.module | Should -Be 'Get-AppLogBundle'
            $result.PSObject.Properties.Name | Should -Contain 'findings'
            $result.PSObject.Properties.Name | Should -Contain 'artifacts'
        }
    }
}
