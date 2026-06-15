# Collector

The FarSight collector is a **bounded PowerShell endpoint agent** delivered through Intune and executed by a scheduled task.  
It checks in with FarSight API, executes only allowlisted modules from local manifest, and posts structured result envelopes.

This page is the practical operator guide for:

1. How collector runtime works on the client.
2. How to package it for Intune.
3. How to distribute and validate it in rollout rings.
4. How to configure certificate-based authentication.

For full Intune workflow details, see also `docs/intune/collector-distribution.md`.

## 1. How collector works on endpoint

### Runtime layout

Default install root:

```text
C:\ProgramData\Company\SreCollector
```

Expected folders:

- `config/` - `config.json`, `module-manifest.json`, task intent metadata.
- `modules/` - allowlisted module scripts and module input schemas.
- `state/` - lock file and collector state (`collector-state.json`).
- `logs/` - NDJSON operational logs (`collector.ndjson`).
- `artifacts/` - bounded output artifacts.
- `schemas/` - common schema files.

### Single run flow (`collector.ps1`)

Each scheduled execution follows this sequence:

1. Acquire run lock (`state/collector.lock`) to prevent parallel runs.
2. Load `config/config.json` and `config/module-manifest.json`.
3. Validate module manifest structure.
4. `POST /api/v1/devices/checkin` using configured client certificate thumbprint.
5. If no job is available, write state/log and exit.
6. If a job is available:
   - load job details from API;
   - ensure `taskType` exists in local manifest;
   - resolve module path under module root (path traversal protected);
   - verify module SHA256 when manifest hash is not placeholder;
   - validate module parameters against module schema;
   - execute module with bounded timeout;
   - post `POST /api/v1/jobs/{jobId}/results`.
7. Persist updated local state and exit.

### Security boundaries

- No free-form shell commands are accepted.
- Modules run only if listed in local manifest.
- Schema + hash + timeout checks are enforced locally.
- Certificate-authenticated API calls use explicit thumbprint.
- Logs must not include secrets/tokens/raw sensitive identities.

## 2. Configuration required on clients

Create environment-specific files from:

- `src/collector/config/config.sample.json`
- `src/collector/config/module-manifest.sample.json`

### `config.json` minimum fields

| Field | Purpose |
| --- | --- |
| `api.baseUrl` | FarSight API base URL reachable from managed clients |
| `api.timeoutSeconds` | API timeout per call |
| `api.certificateThumbprint` | Client cert thumbprint for TLS client auth |
| `device.tenantId` | Entra tenant ID |
| `device.deviceId` | Stable device identity (usually Entra device ID) |
| `device.hostnameHash` | Redacted host correlation value |
| `runtime.artifactRoot` | Artifact staging path |
| `runtime.logPath` | Collector log path |
| `redaction.enabled` | Keep `true` outside isolated tests |

### `module-manifest.json` expectations

- Include only approved module names.
- Keep exact script path + schema reference.
- Replace `sha256-placeholder` with release hash before production rollout.
- Keep bounded `timeoutSeconds` and `maxArtifactBytes`.

## 3. Packaging collector for Intune (Win32 app)

Recommended artifacts:

1. **Win32 app** for collector files + task registration.
2. **Certificate profile** for client certificate delivery.
3. **Remediation package** for drift detection/repair.

### Package staging structure

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
  modules/
    <approved-module-folders>
```

Copy collector engine from `src/collector/` and approved module folders from `src/modules/`.

Do not ship `*.sample.json` in production packages.

### Install script behavior

`install.ps1` should:

1. Copy collector and module files to install root.
2. Run `bootstrap.ps1` to prepare directory/task intent baseline.
3. Register scheduled task (SYSTEM or approved least-privilege identity).
4. Exit non-zero on failure.

### Uninstall script behavior

`uninstall.ps1` should:

1. Unregister collector scheduled task.
2. Remove collector binaries/config.
3. Preserve `logs/` and `state/` unless policy explicitly allows deletion.

### Build `.intunewin`

Use Microsoft Win32 Content Prep Tool with:

- source: package root
- setup file: `install.ps1`
- output: release artifact folder

## 4. Intune distribution workflow (ring-based)

### Create Win32 app

In Intune:

1. Apps -> Windows -> Add -> Windows app (Win32).
2. Upload generated `.intunewin`.
3. Install command:
   `powershell.exe -ExecutionPolicy Bypass -File .\install.ps1`
4. Uninstall command:
   `powershell.exe -ExecutionPolicy Bypass -File .\uninstall.ps1`
5. Install behavior: **System**.

### Recommended detection rule

Detect all of:

- collector core files exist;
- config + manifest exist;
- scheduled task exists with approved path/command.

### Assignment rings

Promote in order:

1. Lab devices
2. IT pilot
3. Limited production
4. Broad production

Promotion gate for each ring:

- install success rate
- task health/run cadence
- valid certificate presence
- successful check-in and no-job cycle
- no sensitive logging
- no unexpected API/auth failures

## 5. Certificate authentication configuration

Collector API calls use certificate-based auth via:

- `api.certificateThumbprint` in `config.json`
- local certificate in Windows cert store with private key

### Recommended certificate profile model

Use Intune-delivered **SCEP or PKCS** profile with:

- client authentication EKU
- non-exportable key (preferred)
- predictable target store (for thumbprint lookup)
- rotation before expiry
- revocation/decommission process

### How to wire thumbprint safely

Preferred order:

1. Issue cert via Intune profile.
2. Resolve thumbprint during packaging/install (or generate config during install from local cert selection policy).
3. Write final `config.json` on device.
4. Validate cert presence in detection/remediation scripts.

Avoid hardcoding a static thumbprint shared across all devices.

### Certificate troubleshooting checklist

If check-in fails:

1. Verify cert exists in expected store and has private key.
2. Verify thumbprint in `config.json` matches installed cert.
3. Verify cert validity period and chain trust.
4. Verify API endpoint TLS trust and route reachability.
5. Verify API requires/accepts client cert on that endpoint path.

## 6. Remediation strategy (required)

Use Intune Remediations to detect and fix drift.

Detection script should verify:

- install root and required files
- scheduled task registration and command
- certificate presence/match
- manifest/config freshness

Remediation script should:

- run `repair.ps1`
- recreate missing files/folders/task from approved package content
- never broaden module allowlist or execute unapproved scripts

## 7. Operational checks after deployment

For each ring, confirm:

1. Collector task executes at expected interval.
2. `collector.ndjson` records clean start/no-job or job-complete flow.
3. API receives check-in and result envelopes.
4. Artifact volume remains within configured limits.
5. No sensitive values appear in logs.

## 8. Known gaps

- Exact enterprise Intune assignment group IDs, cert profile names, and remediation IDs are tenant-specific and must be added during production onboarding.
