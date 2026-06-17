#!/usr/bin/env python3
"""Build an Intune Win32 package for the FarSight collector.

The script stages a collector distribution under `.farsight-dist/`, interactively
collects environment-specific configuration, builds a final module manifest from
the selected module set, prepares certificate-auth metadata, and finally invokes
the Win32 Content Prep Tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_SRC = ROOT / "src" / "collector"
MODULES_SRC = ROOT / "src" / "modules"
DOCS_MODULES = ROOT / "docs" / "modules" / "README.md"
INTUNE_TOOL = ROOT / "scripts" / "IntuneWinAppUtil.exe"
DIST_ROOT = ROOT / ".farsight-dist"
PACKAGE_ROOT = DIST_ROOT / "collector-package"
INTUNE_OUTPUT_ROOT = DIST_ROOT / "intunewin"
INTUNE_PACKAGE_NAME = "FarSightCollector.intunewin"


@dataclass(frozen=True)
class ModuleCatalogEntry:
    name: str
    purpose: str
    risk_tier: str


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{text}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default


def prompt_bool(text: str, default: bool = False) -> bool:
    default_label = "Y/n" if default else "y/N"
    while True:
        value = input(f"{text} ({default_label}): ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "true", "1"}:
            return True
        if value in {"n", "no", "false", "0"}:
            return False
        print("Please answer yes or no.")


def prompt_choice(text: str, choices: list[str], default: str | None = None) -> str:
    indexed = ", ".join(f"{i + 1}:{choice}" for i, choice in enumerate(choices))
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{text}{suffix} ({indexed}): ").strip()
        if not value and default is not None:
            return default
        if value.isdigit():
            idx = int(value) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        if value in choices:
            return value
        print("Select one of the listed choices.")


def sanitize_path_segment(value: str) -> str:
    cleaned = "".join(char if char not in '\\/:*?"<>|' else "-" for char in value).strip()
    return cleaned or "Company"


def ps_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_join(*parts: str) -> str:
    return "\\".join(part.strip("\\/") for part in parts if part).replace(":/", ":\\")


def prompt_multi_select(entries: list[ModuleCatalogEntry]) -> list[str]:
    print("\nAvailable collector modules:")
    for index, entry in enumerate(entries, start=1):
        print(f"  {index}. {entry.name} - {entry.purpose} [{entry.risk_tier}]")
    print("\nEnter comma-separated numbers, or type 'all'.")
    while True:
        value = input("Modules to include [all]: ").strip().lower()
        if not value or value == "all":
            return [entry.name for entry in entries]
        selected: list[str] = []
        try:
            for item in value.split(","):
                index = int(item.strip()) - 1
                if index < 0 or index >= len(entries):
                    raise ValueError
                selected.append(entries[index].name)
        except ValueError:
            print("Enter valid comma-separated module numbers, or 'all'.")
            continue
        deduped = []
        for name in selected:
            if name not in deduped:
                deduped.append(name)
        return deduped


def load_module_catalog() -> dict[str, ModuleCatalogEntry]:
    catalog: dict[str, ModuleCatalogEntry] = {}
    if DOCS_MODULES.exists():
        for line in DOCS_MODULES.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `"):
                continue
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) < 4:
                continue
            name = parts[0].strip("` ")
            purpose = parts[1]
            risk_tier = parts[2]
            catalog[name] = ModuleCatalogEntry(name=name, purpose=purpose, risk_tier=risk_tier)
    return catalog


def module_directories() -> list[Path]:
    return sorted([path for path in MODULES_SRC.iterdir() if path.is_dir()])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_collector_runtime() -> None:
    target = PACKAGE_ROOT / "collector"
    target.mkdir(parents=True, exist_ok=True)

    for name in ("bootstrap.ps1", "collector.ps1", "common.psm1", "healthcheck.ps1", "repair.ps1"):
        shutil.copy2(COLLECTOR_SRC / name, target / name)

    shutil.copytree(COLLECTOR_SRC / "schemas", target / "schemas", dirs_exist_ok=True)


def copy_module_source(module_name: str) -> None:
    source = MODULES_SRC / module_name
    if not source.exists():
        raise FileNotFoundError(f"Module source folder not found: {source}")
    destination = PACKAGE_ROOT / "modules" / module_name
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests"))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def build_config(install_root: str) -> dict:
    sample_path = COLLECTOR_SRC / "config" / "config.sample.json"
    config = json.loads(sample_path.read_text(encoding="utf-8"))
    print("\nPackage-wide collector config.json")
    config["collectorVersion"] = prompt("Collector version (shared package setting)", config.get("collectorVersion", "0.1.0"))
    config["api"]["baseUrl"] = prompt("FarSight API base URL (shared package setting)", config["api"]["baseUrl"])
    config["api"]["timeoutSeconds"] = int(prompt("API timeout seconds (shared package setting)", str(config["api"]["timeoutSeconds"])))
    config["device"]["tenantId"] = prompt("Entra tenant ID (shared package setting)", config["device"]["tenantId"])
    config["device"]["deviceId"] = "__DEVICE_ID_FROM_CERT_CN__"
    print("Device ID will be stamped at install time from the enrolled certificate CN.")
    config["device"]["hostnameHash"] = "__HOSTNAME_HASH_FROM_DEVICE_NAME__"
    print("Hostname hash will be stamped at install time from the local machine name.")
    config["runtime"]["maxSingleRunSeconds"] = int(prompt("Max single-run seconds (shared package setting)", str(config["runtime"]["maxSingleRunSeconds"])))
    config["runtime"]["artifactRoot"] = prompt("Artifact root (shared package setting)", windows_join(install_root, "artifacts"))
    config["runtime"]["logPath"] = prompt("Log path directory (shared package setting)", windows_join(install_root, "logs"))
    config["redaction"]["enabled"] = prompt_bool("Enable redaction for the packaged collector", bool(config["redaction"]["enabled"]))
    return config


def build_certificate_metadata(config: dict) -> dict:
    print("\nCertificate provisioning and install-time lookup")
    mode = prompt_choice(
        "How will the collector certificate be provided for this package?",
        ["Existing thumbprint", "Intune PKI (SCEP/PKCS)", "Not yet decided"],
        default="Intune PKI (SCEP/PKCS)",
    )

    if mode == "Existing thumbprint":
        thumbprint = prompt("Certificate thumbprint (shared package only)").replace(" ", "")
        config["api"]["certificateThumbprint"] = thumbprint
        return {"mode": "thumbprint", "thumbprint": thumbprint}

    if mode == "Intune PKI (SCEP/PKCS)":
        selector = {
            "mode": "intune-pki",
            "storeLocation": prompt_choice("Certificate store location for install-time lookup", ["LocalMachine", "CurrentUser"], default="LocalMachine"),
            "storeName": prompt("Certificate store name for install-time lookup", "My"),
            "subjectContains": prompt("Subject contains (install-time lookup filter)", ""),
            "issuerContains": prompt("Issuer contains (optional install-time lookup filter)", "FarSight Collector"),
            "requirePrivateKey": prompt_bool("Require private key during install-time lookup", True),
        }
        config["api"]["certificateThumbprint"] = "__INTUNE_PKI_RESOLVE_AT_INSTALL__"
        return selector

    config["api"]["certificateThumbprint"] = "__CERTIFICATE_THUMBPRINT_PENDING__"
    return {"mode": "pending"}


def _next_manifest_version(current: str) -> str:
    """Return the next manifestVersion in YYYY-MM-DD.N format.

    If current is already today's date, increments the counter.
    Otherwise starts a new date sequence at .1.
    Returns empty string if auto-generation cannot be determined
    (caller should prompt the user).
    """
    from datetime import date
    today = date.today().isoformat()
    if current and current.startswith(today + "."):
        try:
            counter = int(current.split(".")[-1])
            return f"{today}.{counter + 1}"
        except (ValueError, IndexError):
            pass
    if current:
        # Previous version exists but is from a different date — start today at .1
        return f"{today}.1"
    # No previous version at all — cannot auto-determine
    return ""


def build_manifest(selected_modules: list[str]) -> dict:
    sample_path = COLLECTOR_SRC / "config" / "module-manifest.sample.json"
    try:
        sample_manifest = json.loads(sample_path.read_text(encoding="utf-8"))
        current_version = sample_manifest.get("manifestVersion", "")
    except (OSError, json.JSONDecodeError):
        print(f"  Warning: could not read {sample_path}")
        sample_manifest = {}
        current_version = ""

    lookup = {path.name: path for path in module_directories()}
    manifest_modules: list[dict] = []

    for module_name in selected_modules:
        module_dir = lookup.get(module_name)
        if module_dir is None:
            raise FileNotFoundError(f"Module folder not found for {module_name}")
        fragment_path = module_dir / "manifest.fragment.json"
        if not fragment_path.exists():
            raise FileNotFoundError(f"Missing manifest fragment: {fragment_path}")
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        script_path = module_dir / Path(fragment["scriptPath"]).name
        if not script_path.exists():
            script_path = module_dir / f"{module_name}.ps1"
        if not script_path.exists():
            raise FileNotFoundError(f"Module script not found for {module_name}")
        fragment["sha256"] = sha256_file(script_path)
        manifest_modules.append(fragment)

    new_version = _next_manifest_version(current_version)
    if not new_version:
        # Could not determine version automatically — ask the user
        from datetime import date
        suggested = f"{date.today().isoformat()}.1"
        new_version = prompt(
            "Cannot determine manifestVersion automatically. Enter version "
            "(format: YYYY-MM-DD.N)",
            default=suggested,
        )

    sample_manifest["manifestVersion"] = new_version
    sample_manifest["modules"] = manifest_modules

    # Write the bumped version back to the sample file so the next build
    # continues incrementing from the correct base.
    try:
        updated_sample = json.loads(sample_path.read_text(encoding="utf-8")) if sample_path.exists() else {}
        updated_sample["manifestVersion"] = new_version
        sample_path.write_text(json.dumps(updated_sample, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"  Warning: could not write back manifestVersion to sample file: {exc}")

    print(f"  manifestVersion → {new_version}")
    return sample_manifest


def make_install_script(install_root: str, task_name: str) -> str:
    install_root_ps = ps_single_quoted(install_root)
    task_name_ps = ps_single_quoted(task_name)
    return dedent(
        r"""
        [CmdletBinding()]
        param(
            [string]$InstallRoot = __INSTALL_ROOT__,
            [string]$TaskName = __TASK_NAME__
        )

        Set-StrictMode -Version 2.0
        $ErrorActionPreference = 'Stop'
        $SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

        function Resolve-FarSightCertificateThumbprint {
            param([string]$ConfigPath, [string]$CertificateProfilePath)

            $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $thumbprint = [string]$config.api.certificateThumbprint
            if (-not [string]::IsNullOrWhiteSpace($thumbprint) -and $thumbprint -notlike '__*') {
                return $thumbprint.Replace(' ', '').ToUpperInvariant()
            }

            if (-not (Test-Path -LiteralPath $CertificateProfilePath -PathType Leaf)) {
                throw 'Certificate metadata file is missing and the config does not contain a usable thumbprint.'
            }

            $profile = Get-Content -LiteralPath $CertificateProfilePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($profile.mode -eq 'thumbprint' -and -not [string]::IsNullOrWhiteSpace($profile.thumbprint)) {
                return ([string]$profile.thumbprint).Replace(' ', '').ToUpperInvariant()
            }

            $stores = @()
            if ($profile.storeLocation -and $profile.storeName) {
                $stores += "Cert:\$($profile.storeLocation)\$($profile.storeName)"
            } else {
                $stores += 'Cert:\LocalMachine\My'
            }

            $candidates = foreach ($store in $stores) {
                if (Test-Path -LiteralPath $store) {
                    Get-ChildItem -Path $store | Where-Object {
                        $_.HasPrivateKey -and
                        (-not $profile.subjectContains -or $_.Subject -like "*$($profile.subjectContains)*") -and
                        (-not $profile.issuerContains -or $_.Issuer -like "*$($profile.issuerContains)*")
                    }
                }
            }

            $selected = @($candidates | Sort-Object NotAfter -Descending | Select-Object -First 1)
            if (-not $selected) {
                throw 'No matching certificate found. Install the Intune PKI certificate profile before deploying the collector.'
            }
            return $selected[0].Thumbprint.Replace(' ', '').ToUpperInvariant()
        }

        function Resolve-FarSightDeviceId {
            param([string]$ConfigPath, [string]$CertificateProfilePath)

            $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $deviceId = [string]$config.device.deviceId
            if (-not [string]::IsNullOrWhiteSpace($deviceId) -and $deviceId -notlike '__*') {
                return $deviceId
            }

            if (-not (Test-Path -LiteralPath $CertificateProfilePath -PathType Leaf)) {
                throw 'Certificate metadata file is missing and the config does not contain a usable device ID.'
            }

            $profile = Get-Content -LiteralPath $CertificateProfilePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $stores = @()
            if ($profile.storeLocation -and $profile.storeName) {
                $stores += "Cert:\$($profile.storeLocation)\$($profile.storeName)"
            } else {
                $stores += 'Cert:\LocalMachine\My'
            }

            $candidates = foreach ($store in $stores) {
                if (Test-Path -LiteralPath $store) {
                    Get-ChildItem -Path $store | Where-Object {
                        $_.HasPrivateKey -and
                        (-not $profile.subjectContains -or $_.Subject -like "*$($profile.subjectContains)*") -and
                        (-not $profile.issuerContains -or $_.Issuer -like "*$($profile.issuerContains)*")
                    }
                }
            }

            $selected = @($candidates | Sort-Object NotAfter -Descending | Select-Object -First 1)
            if (-not $selected) {
                throw 'No matching certificate found. Install the Intune PKI certificate profile before deploying the collector.'
            }

            $cn = [string]($selected[0].Subject -replace '.*CN=([^,]+).*', '$1')
            if ([string]::IsNullOrWhiteSpace($cn) -or $cn -eq $selected[0].Subject) {
                throw 'Selected device certificate does not expose a usable CN for device ID stamping.'
            }
            return $cn
        }

        function Resolve-FarSightHostnameHash {
            param([string]$ConfigPath)

            $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $hostnameHash = [string]$config.device.hostnameHash
            if (-not [string]::IsNullOrWhiteSpace($hostnameHash) -and $hostnameHash -notlike '__*') {
                return $hostnameHash
            }

            $hostname = [System.Environment]::MachineName.Trim().ToLowerInvariant()
            $sha256 = [System.Security.Cryptography.SHA256]::Create()
            try {
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($hostname)
                $hashBytes = $sha256.ComputeHash($bytes)
                $hex = ($hashBytes | ForEach-Object { $_.ToString('x2') }) -join ''
                return "sha256:$hex"
            } finally {
                $sha256.Dispose()
            }
        }

        $collectorSource = Join-Path $SourceRoot 'collector'
        $moduleSource = Join-Path $SourceRoot 'modules'

        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
        Copy-Item -Path (Join-Path $collectorSource '*') -Destination $InstallRoot -Recurse -Force
        Copy-Item -Path $moduleSource -Destination (Join-Path $InstallRoot 'modules') -Recurse -Force

        $configPath = Join-Path $InstallRoot 'config\config.json'
        $profilePath = Join-Path $InstallRoot 'config\certificate-source.json'
        $resolvedThumbprint = Resolve-FarSightCertificateThumbprint -ConfigPath $configPath -CertificateProfilePath $profilePath
        $resolvedDeviceId = Resolve-FarSightDeviceId -ConfigPath $configPath -CertificateProfilePath $profilePath
        $resolvedHostnameHash = Resolve-FarSightHostnameHash -ConfigPath $configPath

        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $config.api.certificateThumbprint = $resolvedThumbprint
        $config.device.deviceId = $resolvedDeviceId
        $config.device.hostnameHash = $resolvedHostnameHash
        $config | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $configPath -Encoding UTF8

        & (Join-Path $InstallRoot 'bootstrap.ps1') -InstallRoot $InstallRoot

        $collectorScript = Join-Path $InstallRoot 'collector.ps1'
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$collectorScript`""
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        """
    ).strip().replace("__INSTALL_ROOT__", install_root_ps).replace("__TASK_NAME__", task_name_ps) + "\n"


def make_uninstall_script(install_root: str, task_name: str) -> str:
    install_root_ps = ps_single_quoted(install_root)
    task_name_ps = ps_single_quoted(task_name)
    return dedent(
        r"""
        [CmdletBinding()]
        param(
            [string]$InstallRoot = __INSTALL_ROOT__,
            [string]$TaskName = __TASK_NAME__,
            [switch]$RemoveLogs
        )

        Set-StrictMode -Version 2.0
        $ErrorActionPreference = 'Stop'

        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }

        if ($RemoveLogs) {
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
        } else {
            Get-ChildItem -LiteralPath $InstallRoot -Exclude 'logs','state' -ErrorAction SilentlyContinue |
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        }
        """
    ).strip().replace("__INSTALL_ROOT__", install_root_ps).replace("__TASK_NAME__", task_name_ps) + "\n"


def invoke_intune_tool() -> None:
    if not INTUNE_TOOL.exists():
        raise FileNotFoundError(f"IntuneWinAppUtil.exe not found: {INTUNE_TOOL}")
    INTUNE_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    command = [
        str(INTUNE_TOOL),
        "-c",
        str(PACKAGE_ROOT),
        "-s",
        "install.ps1",
        "-i",
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1",
        "-o",
        str(INTUNE_OUTPUT_ROOT),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    generated = sorted(INTUNE_OUTPUT_ROOT.glob("*.intunewin"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not generated:
        raise FileNotFoundError(f"Intune package was not generated in {INTUNE_OUTPUT_ROOT}")
    source = generated[0]
    target = INTUNE_OUTPUT_ROOT / INTUNE_PACKAGE_NAME
    if source != target:
        if target.exists():
            target.unlink()
        source.rename(target)


def main() -> int:
    global DIST_ROOT, PACKAGE_ROOT, INTUNE_OUTPUT_ROOT
    parser = argparse.ArgumentParser(description="Interactively build a FarSight collector Intune package.")
    parser.add_argument("--dist-root", default=str(DIST_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    DIST_ROOT = Path(args.dist_root).resolve()
    PACKAGE_ROOT = DIST_ROOT / "collector-package"
    INTUNE_OUTPUT_ROOT = DIST_ROOT / "intunewin"

    print("FarSight collector Intune package builder")
    print(f"Distribution root: {DIST_ROOT}")
    print(f"Collector source:   {COLLECTOR_SRC}")
    print(f"Modules source:     {MODULES_SRC}")

    company_name = prompt("Company name", "Company")
    company_segment = sanitize_path_segment(company_name)
    install_root = rf"C:\ProgramData\{company_segment}\SreCollector"
    task_name = f"{company_name} FarSight Collector"

    print(f"Company:            {company_name}")
    print(f"Install root:       {install_root}")
    print(f"Task name:          {task_name}")

    catalog_map = load_module_catalog()
    selected_modules = prompt_multi_select(
        [catalog_map.get(path.name, ModuleCatalogEntry(path.name, "See module README", "unknown")) for path in module_directories()]
    )

    config = build_config(install_root)
    cert_metadata = build_certificate_metadata(config)
    manifest = build_manifest(selected_modules)

    if DIST_ROOT.exists() and any(DIST_ROOT.iterdir()):
        if not prompt_bool(f"{DIST_ROOT} already exists. Replace it", default=False):
            print("Aborted.")
            return 1

    ensure_clean_dir(DIST_ROOT)
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    (PACKAGE_ROOT / "collector" / "config").mkdir(parents=True, exist_ok=True)
    (PACKAGE_ROOT / "modules").mkdir(parents=True, exist_ok=True)

    copy_collector_runtime()
    for module_name in selected_modules:
        copy_module_source(module_name)
    write_json(PACKAGE_ROOT / "collector" / "config" / "config.json", config)
    write_json(PACKAGE_ROOT / "collector" / "config" / "module-manifest.json", manifest)
    write_json(PACKAGE_ROOT / "collector" / "config" / "certificate-source.json", cert_metadata)
    write_json(PACKAGE_ROOT / "collector" / "config" / "package-metadata.json", {
        "companyName": company_name,
        "installRoot": install_root,
        "taskName": task_name,
        "manifestVersion": manifest["manifestVersion"],
    })
    (PACKAGE_ROOT / "install.ps1").write_text(make_install_script(install_root, task_name), encoding="utf-8")
    (PACKAGE_ROOT / "uninstall.ps1").write_text(make_uninstall_script(install_root, task_name), encoding="utf-8")

    print("\nStaged package:")
    print(f"  {PACKAGE_ROOT}")
    print("Generated files:")
    print(f"  {PACKAGE_ROOT / 'collector' / 'config' / 'config.json'}")
    print(f"  {PACKAGE_ROOT / 'collector' / 'config' / 'module-manifest.json'}")
    print(f"  {PACKAGE_ROOT / 'collector' / 'config' / 'certificate-source.json'}")
    print(f"  {PACKAGE_ROOT / 'collector' / 'config' / 'package-metadata.json'}")

    if args.dry_run:
        print("\nDry run requested; skipping Intune package generation.")
        return 0

    print("\nInvoking Intune Win32 Content Prep Tool...")
    invoke_intune_tool()
    print(f"\n✓ Final package: {INTUNE_OUTPUT_ROOT / INTUNE_PACKAGE_NAME}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
