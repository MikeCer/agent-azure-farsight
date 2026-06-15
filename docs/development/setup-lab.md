# Set up a FarSight test lab in Azure

Use this guide to stand up a greenfield Azure lab for testing the FarSight collector on Windows 11 devices that will be managed through Intune.

This page is an orchestration checklist. It intentionally links to the authoritative implementation guides instead of duplicating their full details.

## What this lab is for

The lab helps validate:

- Windows 11 VM connectivity to the FarSight control plane.
- Intune enrollment and assignment rings.
- FarSight collector installation through Intune.
- Collector check-in, no-job behavior, and later diagnostic job execution.
- Remediation and repair behavior.

## What this lab does not do

- It does not automatically enroll Azure VMs into Intune.
- It does not replace the production private-network deployment guide.
- It does not deploy the FarSight control plane by itself.
- It does not bypass tenant, certificate, or Intune enrollment prerequisites.

## Related documentation

Read these before starting:

| Topic | Documentation |
| --- | --- |
| Full Azure greenfield deployment | [Greenfield Azure deployment](../deployment/azure-greenfield-deployment.md) |
| Test VM infrastructure | [`infra-test/README.md`](../../infra-test/README.md) |
| Intune collector packaging | [Collector documentation](../collector/README.md#3-packaging-collector-for-intune-win32-app) |
| Collector runtime model | [Collector documentation](../collector/README.md) |
| Security expectations | [Security](../security/README.md) |

## Step-by-step lab setup

### 1. Prepare the Azure subscription

Use a dedicated lab resource group and confirm the subscription has capacity for:

- the FarSight control plane if it is not already deployed;
- the Windows 11 test VMs from `infra-test/`;
- network resources for the lab VNet and subnet;
- any private DNS/VNet routing dependencies needed to reach the FarSight API.

Follow the provider, quota, private networking, and DNS planning guidance in the [greenfield Azure deployment guide](../deployment/azure-greenfield-deployment.md).

### 2. Deploy or identify the FarSight control plane

Before deploying test clients, decide which FarSight API endpoint the collector will use:

- private endpoint/internal endpoint for production-like testing;
- public development endpoint only for early isolated validation.

Record the API base URL because it must be placed in the collector `config.json`.

### 3. Deploy the Windows 11 lab VMs

Use the Bicep template in `infra-test/`.

Before deployment, review:

- VM count and size;
- VNet and subnet address prefixes;
- Windows 11 image parameters, including the default `win11-24h2-pro` SKU verified for Italy North;
- admin username and inline `adminPassword` handling;
- whether public IPs are disabled.
- whether NAT Gateway is needed for outbound internet without public IPs.

The default posture is low-cost and private: two `Standard_B2s` Windows 11 VMs, no public IPs, and public RDP denied. NAT Gateway is optional; enable it when lab VMs need outbound internet for Intune enrollment or updates without public IPs. See [`infra-test/README.md`](../../infra-test/README.md) for the template purpose, parameters, security defaults, and cleanup guidance.

### 4. Establish admin access to the lab VMs

Use an approved private administration path, such as:

- Azure Bastion provided by your platform team;
- VPN or ExpressRoute-connected workstation;
- just-in-time access through an approved jumpbox;
- another enterprise-approved method.

Avoid enabling public RDP unless it is explicitly approved as a short-lived break-glass exception.

### 5. Enroll the VMs into Intune

Bicep creates VMs only. It does not make them Intune-managed.

Enroll the VMs using the tenant-approved path:

1. Confirm Intune MDM auto-enrollment is enabled for the target users/devices.
2. Sign in or join each VM using a licensed Entra user and approved enrollment flow.
3. Confirm each VM appears in Intune.
4. Add the devices or users to the FarSight lab assignment group.
5. Wait for Intune policy sync before assigning the collector broadly.

### 6. Prepare the collector package

Follow [Collector packaging for Intune](../collector/README.md#3-packaging-collector-for-intune-win32-app).

At minimum, prepare:

- `config.json` with the lab FarSight API endpoint and certificate reference;
- `module-manifest.json` with approved module entries;
- collector scripts from `src/collector/`;
- approved module folders from `src/modules/`;
- install, uninstall, and detection scripts for the Win32 app package;
- certificate profile or approved pilot certificate path.

### 7. Assign the collector to the lab ring

Assign the collector Win32 app only to the lab group first.

Track:

- app install success;
- detection rule success;
- scheduled task creation;
- certificate presence;
- local collector logs;
- FarSight API check-ins.

Do not move to IT pilot until the lab ring has stable install and check-in behavior.

### 8. Add Remediations

Create Intune Remediations for collector health and repair. Use the responsibilities described in [Collector remediation strategy](../collector/README.md#6-remediation-strategy-required):

- detect missing install files;
- detect missing config or manifest;
- detect missing scheduled task;
- detect missing certificate;
- run approved repair logic only.

Remediations must not become a dynamic command bus.

### 9. Run the first FarSight smoke test

Start with a no-job collector cycle:

- collector installed;
- scheduled task runs;
- collector checks in;
- API returns no job;
- local log records a successful no-job run.

Then create a low-risk read-only diagnostic job and confirm:

- the job is leased by the intended VM;
- the module is allowlisted locally;
- result envelope is submitted;
- no oversized or sensitive artifact is uploaded unexpectedly.

### 10. Expand only after evidence review

Review the lab results before expanding:

- installation reliability;
- local log content and redaction;
- API errors and retries;
- policy decisions and approvals;
- operator usability;
- Intune remediation behavior.

Only then move to IT pilot.

## Cleanup

When testing is complete:

1. Remove lab devices/users from FarSight assignment groups.
2. Unassign or uninstall the collector package.
3. Preserve required logs according to retention policy.
4. Delete the `infra-test` lab resource group.
5. Remove stale Intune device records if your tenant process requires it.

## Known gaps

- Exact tenant-specific Intune group names, certificate profile names, and remediation IDs are intentionally not hardcoded here.
- The lab relies on your tenant's approved Entra join and Intune enrollment process.
- Public RDP remains disabled by default; use your platform team's private access pattern.
