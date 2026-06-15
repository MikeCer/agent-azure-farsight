# Collector

The FarSight collector is a **bounded PowerShell endpoint agent** delivered through Intune and executed by a scheduled task.  
It checks in with FarSight API, executes only allowlisted modules from local manifest, and posts structured result envelopes.

This page is the practical operator guide for:

1. How collector runtime works on the client.
2. How to package it for Intune.
3. How to distribute and validate it in rollout rings.
4. How to configure certificate-based authentication.

This page is the canonical guide for collector + Intune packaging, distribution, certificate setup, and remediation.

## 1. How collector works on endpoint

### Runtime layout

Default install root is company-specific and chosen during packaging. For example:

```text
C:\ProgramData\Company\SreCollector
```

When you run collector scripts without passing `-InstallRoot`, they now default to the script directory (`$PSScriptRoot`) first, then fall back to the legacy `C:\ProgramData\Company\SreCollector` path. This keeps manual test runs aligned with the actual packaged install location.

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
| `device.deviceId` | Stable device identity, stamped per device at install time from the enrolled certificate CN |
| `device.hostnameHash` | Redacted host correlation value, stamped per device at install time from the local machine name |
| `runtime.artifactRoot` | Artifact staging path (Windows path) |
| `runtime.logPath` | Collector log directory (Windows path); the collector writes `collector.ndjson` inside it |
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

For the fastest operator flow, use `scripts/build-collector-intunewin.py`. It first asks for the customer/company name, then stages a package under `.farsight-dist/collector-package/`, interactively collects `config.json`, the final `module-manifest.json`, and certificate metadata, then invokes `scripts/IntuneWinAppUtil.exe` to produce the `.intunewin` output.

**Install command**: The helper automatically includes the `-i` parameter with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1` so Intune knows how to execute the PowerShell install script. This is essential for the Win32 app installation to proceed after detection succeeds.

The helper separates shared package settings from install-time lookup values, so it should not ask for per-device IDs or thumbprints when Intune PKI is selected.

The helper also emits package metadata (`package-metadata.json`) so the generated install/uninstall scripts use the chosen company name in the install root and scheduled task name.

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

In the Intune Win32 app, configure **Detection rules** as:

1. **Rules format**: `Use a custom detection script`.
2. **Script type**: PowerShell.
3. **Run script as 64-bit**: `Yes`.
4. **Run script in 32-bit PowerShell**: `No`.
5. **Script file**: upload [`scripts/intune-collector-detection.ps1`](../../scripts/intune-collector-detection.ps1).
6. **Detection logic**: the script returns success only when all of these are true:
   - the collector install root exists;
   - `config\config.json` exists;
   - `config\module-manifest.json` exists;
   - `collector.ps1` and `common.psm1` exist;
   - `config\package-metadata.json` exists;
   - the scheduled task exists and its command still points to the approved install root;
   - the device certificate thumbprint exists in the expected cert store.

If you need to customize the install root or task name, edit the script before uploading it to Intune.

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

Certificate options from lowest to highest operational maturity:

| Option | Use case |
| --- | --- |
| Known thumbprint at packaging time | Lab or single-device test only. Do not use in production. |
| Intune-managed PKCS (third-party CA) | Existing on-premises PKI issuing PKCS#12 profiles through Intune. |
| **Intune Cloud PKI + SCEP** | Recommended for production. Fully cloud-managed, no on-premises CA required. |

### Option A: Intune Cloud PKI with SCEP (recommended)

Microsoft Intune Cloud PKI is a fully cloud-managed PKI built into Intune. No on-premises CA, NDES server, or certificate connector is required.

#### Step 1 — Create a Cloud PKI root CA

1. In **Intune admin center** → **Tenant administration** → **Cloud PKI**.
2. Select **Create** → **Root CA**.
3. Configure:
   - **Name**: e.g. `FarSight Collector Root CA`
   - **Validity period**: 10 years (recommended)
   - **Key algorithm**: RSA 2048 or ECDSA P-256
   - **Subject**: set `O=<company>`, `CN=FarSight Collector Root CA`
4. Save and wait for provisioning to complete.
5. Download the Root CA certificate for distribution to client trust stores.

#### Step 2 — Create a Cloud PKI issuing CA

1. In **Cloud PKI**, select **Create** → **Issuing CA**.
2. Set **Parent CA** to the root CA created in step 1.
3. Configure:
   - **Name**: e.g. `FarSight Collector Issuing CA`
   - **Validity period**: 3 years
   - **Key algorithm**: match root CA
   - **Subject**: set `O=<company>`, `CN=FarSight Collector Issuing CA`
4. Save and copy the **SCEP URL** from the issuing CA properties — you need it for the certificate profile.

#### Step 3 — Distribute root CA to client trust stores

The Windows client must trust the issuing CA chain before the SCEP profile can reference it, and the FarSight API endpoint must trust the root CA.

For Windows clients:
1. In **Devices** → **Configuration** → **Create** → **New policy**.
2. Platform: **Windows 10 and later**. Profile type: **Trusted certificate**.
3. Upload the Root CA `.cer` file downloaded in step 1.
4. Destination store: **Computer certificate store - Root**.
5. Assign to the same device groups.

For the FarSight API (Azure Container App):

Azure Container Apps does not perform OS-level CA trust for inbound mTLS. Instead, configure the Container Apps Environment to accept and forward client certificates so the API application can validate them.

1. **Export the Root CA certificate from Intune Cloud PKI.**
   In Intune admin center → **Tenant administration** → **Cloud PKI** → select the root CA → **Download certificate**. Save as `farsight-root-ca.cer`.

2. **Make the Root CA available to the API container.**
   Azure Container Apps has no CA trust store for client certificate validation — chain validation is the application's responsibility. Provide the Root CA PEM to the API as an environment variable.

   Base64-encode the PEM file:
   ```bash
   base64 -w 0 FarSightCollectorRootCA.pem
   ```
   Set the output as an AZD environment variable:
   ```bash
   azd env set FARSIGHT_API_DEVICE_CERT_TRUSTED_CA_PEM <base64-output>
   ```
   The API's `require_device_cert` dependency loads this at startup and verifies each device certificate's signature against the CA public key.

3. **Enable client certificate pass-through on the API Container App ingress.**
   Set `clientCertificateMode` to `accept` (forwards cert if present; does not require it) or `require` (rejects requests with no cert).
   ```bash
   az containerapp ingress update \
     --resource-group <rg> \
     --name <api-container-app-name> \
     --client-certificate-mode accept
   ```
   If your `containerapp` extension version does not support `--client-certificate-mode`, use ARM REST patch:
   ```bash
   az rest --method PATCH \
     --uri "https://management.azure.com/subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.App/containerApps/<api-container-app-name>?api-version=2024-03-01" \
     --body '{"properties":{"configuration":{"ingress":{"clientCertificateMode":"accept"}}}}'
   ```
   Or in Bicep, add to the `ingress` block:
   ```bicep
   ingress: {
     external: containerAppIngressExternal
     targetPort: 8000
     transport: 'http'
     allowInsecure: false
     clientCertificateMode: 'accept'
   }
   ```

4. **The API validates the forwarded certificate on collector-facing endpoints.**
   Azure Container Apps forwards the client certificate via the `X-Forwarded-Client-Cert` header (URL-encoded PEM). The `require_device_cert` dependency in `src/api/app/auth.py` parses the certificate, checks validity period and Client Authentication EKU, and binds the certificate CN to the claimed `device_id` in the request body.

   Enable enforcement by setting the env var:
   ```
   FARSIGHT_API_ENFORCE_DEVICE_CERT_AUTH=true
   ```
   When unset or `false`, the dependency passes through (safe for local development without a certificate).

#### Step 4 — Create a SCEP certificate profile

1. In **Devices** → **Configuration** → **Create** → **New policy**.
2. Platform: **Windows 10 and later**. Profile type: **SCEP certificate**.
3. Configure:
   - **Certificate type**: Device
   - **Subject name format**: `CN={{AAD_Device_ID}}` (device ID as subject so each cert is unique)
   - **Subject alternative name**: `URI: spiffe://<tenant-id>/farsight/collector/{{AAD_Device_ID}}` (optional, recommended for future mTLS validation)
   - **Certificate validity**: 1 year
   - **Key size**: 2048 or P-256
   - **Extended key usage**: **Client Authentication** (OID 1.3.6.1.5.5.7.3.2)
   - **Key storage provider**: TPM KSP if required, otherwise Software KSP
   - **Root certificate**: select the trusted certificate profile created in step 3
   - **SCEP server URLs**: paste the SCEP URL from step 2
4. Assign to the same device groups used for the collector Win32 app.

> Certificate enrollment happens before the collector install script runs, as long as the trusted certificate and SCEP profiles are assigned earlier in the ring.

#### Step 5 — Run the packaging helper in Intune PKI mode

When running `scripts/build-collector-intunewin.py`, select **Intune PKI (SCEP/PKCS)** for the certificate mode. The helper prompts:

- Certificate store location: `LocalMachine`
- Certificate store name: `My`
- Subject contains: value matching your SCEP profile subject (e.g. `farsight`)
- Issuer contains: (optional) partial issuer CN from the issuing CA

The helper writes `certificate-source.json` and leaves `api.certificateThumbprint` as an install-time placeholder. At install time, `install.ps1` searches the device certificate store using these criteria, finds the SCEP-enrolled certificate, and writes the resolved thumbprint into `config.json` before registering the scheduled task.

#### Step 6 — Verify certificate delivery order in deployment

Ensure the Intune assignment deployment order is:
1. Trusted root CA certificate profile ← deploys first
2. SCEP certificate profile ← enrolls device cert
3. FarSight collector Win32 app ← installs and resolves thumbprint from enrolled cert

### Option B: Intune-managed PKCS (on-premises CA)

If using an existing enterprise PKI through Intune PKCS profile instead of Cloud PKI:

1. Configure a Intune Certificate Connector on a server with access to your CA.
2. Create a PKCS certificate profile with **Client Authentication** EKU.
3. In the packaging helper, select **Intune PKI (SCEP/PKCS)** and provide the subject/issuer match criteria matching the PKCS profile.
4. The install-time resolution flow is identical to Cloud PKI.

### How to wire thumbprint safely

Summary regardless of option:

1. Issue cert via Intune profile (Cloud PKI SCEP or PKCS).
2. At install time, `install.ps1` resolves the thumbprint from the enrolled cert using `certificate-source.json` selector.
3. `config.json` is written with the resolved thumbprint.
4. Detection/remediation scripts validate cert presence on every compliance cycle.

Avoid hardcoding a static thumbprint shared across all devices.

When the package is built for Intune PKI, the helper script writes a `certificate-source.json` sidecar into `.farsight-dist/collector-package/collector/config/`. The generated `install.ps1` uses that metadata to find the issued device certificate and overwrite the placeholder thumbprint in `config.json` during installation.

### Certificate troubleshooting checklist

If check-in fails:

1. Verify cert exists in `LocalMachine\My` store and has private key.
2. Verify SCEP/PKCS profile enrollment succeeded in Intune device reports.
3. Verify subject/issuer selector in `certificate-source.json` matches the enrolled cert.
4. Verify thumbprint in `config.json` is uppercase and without spaces.
5. Verify cert validity period and chain trust to root CA.
6. Verify FarSight API TLS trust for the issuing CA chain.
7. Verify API endpoint reachability from the managed device (DNS, routing, firewall).

### Cloud PKI operational notes

- Cloud PKI SCEP URL is per-issuing-CA; do not share it between tenants or customer environments.
- Certificate revocation is handled through Cloud PKI CRL/OCSP automatically.
- Rotate issuing CA before expiry; renew root CA well in advance (18 months before expiry recommended).
- Monitor Cloud PKI quota usage in Intune admin center (Tenant administration → Cloud PKI → Usage).

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
