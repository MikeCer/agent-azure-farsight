# Distribute the FarSight collector with Intune

This guide explains how to package and distribute the FarSight PowerShell collector engine from `src/collector/` through Microsoft Intune.

The collector is a bounded diagnostic framework. It is not a remote shell, and Intune packages must not introduce arbitrary PowerShell execution paths.

## Recommended distribution model

Use three Intune artifacts:

| Intune artifact | Purpose | Recommended use |
| --- | --- | --- |
| Win32 app | Installs the collector file tree, modules, config, manifest, and scheduled task. | Primary deployment method. |
| Certificate profile | Delivers the device certificate used for FarSight mTLS. | Required for production. |
| Remediation | Detects and repairs collector drift after install. | Required for health and self-heal. |

Platform scripts can be useful for very early bootstrap testing, but they are not ideal for distributing the full collector file tree.

For operator-led packaging runs, use `scripts/build-collector-intunewin.py`. The helper first prompts for the customer/company name, then stages a complete collector distribution under `.farsight-dist/`, prompts for environment-specific `config.json` values, prompts for the final module selection, records certificate metadata, and then calls `scripts/IntuneWinAppUtil.exe` to generate the Win32 app package.

## 1. Prepare the package staging folder

Create a local staging folder outside the repo build output, for example:

```text
farsight-collector-package/
  install.ps1
  uninstall.ps1
  collector/
    bootstrap.ps1
    collector.ps1
    common.psm1
    healthcheck.ps1
    repair.ps1
    config/
      config.json
      module-manifest.json
    schemas/
      module-result.schema.json
  modules/
    Get-AppLogBundle/
    Get-AppEventSlice/
    Get-AppHealthSnapshot/
    Test-AppConnectivity/
    Get-ConfigEvidence/
```

Copy files from the repo:

| Repo source | Package target |
| --- | --- |
| `src/collector/bootstrap.ps1` | `collector/bootstrap.ps1` |
| `src/collector/collector.ps1` | `collector/collector.ps1` |
| `src/collector/common.psm1` | `collector/common.psm1` |
| `src/collector/healthcheck.ps1` | `collector/healthcheck.ps1` |
| `src/collector/repair.ps1` | `collector/repair.ps1` |
| `src/collector/schemas/` | `collector/schemas/` |
| `src/modules/<module>/` | `modules/<module>/` |
| prepared environment config | `collector/config/config.json` |
| prepared environment manifest | `collector/config/module-manifest.json` |

Do not package `.sample.json` files as production config. Use them only as templates.

## 2. Prepare `config.json`

Start from `src/collector/config/config.sample.json` and produce an environment-specific `config.json`.

Required values:

| Setting | Purpose |
| --- | --- |
| `api.baseUrl` | FarSight control API endpoint reachable by Intune-managed clients. |
| `api.timeoutSeconds` | Bounded API call timeout. |
| `api.certificateThumbprint` | Device certificate used for mTLS. |
| `device.tenantId` | Microsoft Entra tenant ID. |
| `device.deviceId` | Stable device ID, usually Entra device ID. |
| `device.hostnameHash` | Redacted host correlation value. |
| `runtime.artifactRoot` | Local artifact staging folder. |
| `runtime.logPath` | Local structured log path. |
| `redaction.enabled` | Must remain `true` outside isolated tests. |

Production packages should avoid per-device static config values where possible. Prefer deriving device identity locally or writing config during install from a secure tenant-approved source. If a value is per-device, do not hardcode one shared value for all devices.

## 3. Prepare `module-manifest.json`

Start from `src/collector/config/module-manifest.sample.json` and produce `collector/config/module-manifest.json`.

For each module:

- keep only approved module names;
- set the exact module version;
- replace `sha256-placeholder` with the release pipeline hash for the deployed script;
- keep bounded `timeoutSeconds` and `maxArtifactBytes`;
- ensure `scriptPath` and `schemaRef` match the package layout.

The collector rejects jobs whose module is not present in this local manifest.

## 4. Add the Win32 install script

Create `install.ps1` in the package root. This script copies package files into `C:\ProgramData\Company\SreCollector`, runs bootstrap, and registers the scheduled task.

Example:

```powershell
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:ProgramData\Company\SreCollector",
    [string]$TaskName = "Company FarSight Collector"
)

$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$collectorSource = Join-Path $SourceRoot "collector"
$moduleSource = Join-Path $SourceRoot "modules"

New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Copy-Item -Path (Join-Path $collectorSource "*") -Destination $InstallRoot -Recurse -Force
Copy-Item -Path $moduleSource -Destination (Join-Path $InstallRoot "modules") -Recurse -Force

& (Join-Path $InstallRoot "bootstrap.ps1") -InstallRoot $InstallRoot

$collectorScript = Join-Path $InstallRoot "collector.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$collectorScript`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
```

Review this script with endpoint/security owners before production. If your enterprise requires signed scripts, sign `install.ps1`, `bootstrap.ps1`, `collector.ps1`, `common.psm1`, `healthcheck.ps1`, `repair.ps1`, and module scripts.

## 5. Add the Win32 uninstall script

Create `uninstall.ps1` in the package root.

Example:

```powershell
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:ProgramData\Company\SreCollector",
    [string]$TaskName = "Company FarSight Collector",
    [switch]$RemoveLogs
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if ($RemoveLogs) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Get-ChildItem -LiteralPath $InstallRoot -Exclude "logs","state" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
```

By default, preserve logs/state for investigation review unless policy says they can be removed.

## 6. Build the `.intunewin` package

Use the Microsoft Win32 Content Prep Tool.

Packaging inputs:

| Field | Value |
| --- | --- |
| Source folder | `farsight-collector-package` |
| Setup file | `install.ps1` |
| Output folder | your release artifact folder |

The output is a `.intunewin` file that you upload as a Windows app (Win32) in Intune.

## 7. Create the Intune Win32 app

In Intune admin center:

1. Go to **Apps** > **Windows** > **Add**.
2. Select **Windows app (Win32)**.
3. Upload the generated `.intunewin` package.
4. Set app information:
   - Name: `FarSight Collector`.
   - Publisher: your organization.
   - Category: operations or endpoint management.
5. Configure program commands.

Install command:

```text
powershell.exe -ExecutionPolicy Bypass -File .\install.ps1
```

Uninstall command:

```text
powershell.exe -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Install behavior:

```text
System
```

Device restart behavior:

```text
No specific action
```

## 8. Configure requirements

Recommended requirement rules:

| Requirement | Value |
| --- | --- |
| Operating system architecture | 64-bit |
| Minimum operating system | Windows 10 1909 or later / Windows 11 |
| Disk space | Enough for collector, logs, and bounded artifacts |
| PowerShell | Windows PowerShell 5.1 available |

Keep the package compatible with Windows PowerShell 5.1 unless the collector runtime is explicitly changed.

## 9. Configure detection rule

Use a custom PowerShell detection rule.

Example:

```powershell
$InstallRoot = "$env:ProgramData\Company\SreCollector"
$TaskName = "Company FarSight Collector"

$requiredFiles = @(
    "collector.ps1",
    "common.psm1",
    "config\config.json",
    "config\module-manifest.json"
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot $relativePath) -PathType Leaf)) {
        exit 1
    }
}

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    exit 1
}

exit 0
```

Detection should be strict enough to catch missing config, manifest, collector script, and scheduled task drift.

## 10. Assign the app in rings

Use staged assignments:

1. Lab devices.
2. IT pilot devices.
3. Limited production ring.
4. Broad production rollout.

Recommended promotion checks:

- install success rate;
- scheduled task health;
- certificate presence;
- successful FarSight check-in;
- bounded local log volume;
- no sensitive values in local logs;
- no unexpected API errors.

Do not assign the collector broadly until lab devices have completed at least one successful check-in and no-job cycle.

## 11. Configure certificate delivery

Create or reuse an approved Intune certificate profile before assigning the collector broadly.

Production certificate requirements:

- SCEP or PKCS backed by enterprise PKI;
- non-exportable private key when possible;
- client authentication EKU;
- predictable certificate store location;
- rotation before expiry;
- revocation path for lost/decommissioned devices.

The collector config must reference the certificate thumbprint or a secure lookup strategy implemented by your packaging process. The new interactive packaging helper writes `collector/config/certificate-source.json` and resolves the final thumbprint during installation when the certificate is delivered by Intune PKI.

## 12. Configure Remediations

Create an Intune Remediation package:

Detection script responsibilities:

- verify install root exists;
- verify collector and common module exist;
- verify config and manifest exist;
- verify scheduled task exists and points to the approved path;
- verify the certificate is present;
- verify recent collector state/logs when available.

Remediation script responsibilities:

- run `repair.ps1`;
- recreate missing folders;
- restore missing approved files from package/source;
- recreate the scheduled task;
- never broaden module allowlists or deploy unapproved modules.

Use Remediations for drift repair, not dynamic diagnostic command delivery.

## 13. Rollout checks

For each ring, confirm:

- the app installed successfully in Intune reports;
- the scheduled task exists and runs;
- local collector logs are structured JSON;
- FarSight API receives check-ins;
- no diagnostic jobs run unless explicitly requested;
- artifacts stay within configured size and retention bounds.

## 14. Rollback and uninstall

Rollback sequence:

1. Stop assigning the Win32 app to the affected group.
2. Disable or remove the scheduled task.
3. Preserve logs needed for investigation according to retention policy.
4. Remove staged artifacts if policy allows.
5. Uninstall collector files after confirming no active investigation depends on them.

Use the Win32 app uninstall command for controlled removal. Avoid ad hoc cleanup scripts outside the approved package/remediation flow.

## Safety rules

- Do not deploy arbitrary one-off diagnostic scripts through FarSight packages.
- Do not bypass manifest, schema, hash, timeout, redaction, or allowlist checks.
- Do not embed credentials in scripts or configuration.
- Do not broaden module scope during incident response without approval.
- Document module, manifest, certificate, packaging, and rollout changes in `docs/intune/`.

## Test lab flow

Use `infra-test/` to create lab Windows 11 VMs. Enroll those VMs into Intune through the tenant-approved flow, add them to the FarSight lab assignment group, then assign the collector Win32 app and Remediation package.
