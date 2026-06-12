# FarSight Intune test lab infrastructure

`infra-test/` deploys a small Azure lab for testing the FarSight collector on Windows 11 clients that you later enroll and manage with Intune.

## What gets deployed

- One virtual network.
- One subnet protected by an NSG.
- Two Windows 11 VMs by default.
- One NIC and OS disk per VM.
- Optional public IPs for break-glass testing only.
- Optional NAT Gateway for outbound internet from the VM subnet.

## Important Intune note

Bicep creates the Windows 11 VMs and network. It does **not** automatically enroll the VMs into Intune. After deployment, enroll the VMs using your tenant-approved Entra/Intune flow, then assign the FarSight collector package.

## Prerequisites

Before deploying, prepare:

| Item | Requirement |
| --- | --- |
| Azure access | Permission to create resource groups, VNets, NSGs, NICs, disks, and VMs. |
| Region | A region where the selected Windows 11 image and VM size are available. |
| Address space | Non-overlapping `vnetAddressPrefix` and `subnetAddressPrefix`. |
| Admin credentials | A secure local admin password provided at deployment time. |
| Access path | Bastion, VPN, ExpressRoute, jumpbox, or another approved way to reach private VMs. |
| Intune | MDM auto-enrollment and assignment groups ready for lab devices/users. |

## Parameters to review

`main.parameters.json` contains safe lab defaults. Review these before each deployment:

| Parameter | Default | Notes |
| --- | --- | --- |
| `environmentName` | `farsight-test` | Used in resource names and tags. |
| `location` | `italynorth` | Change if Windows 11 image/SKU is unavailable. |
| `vmCount` | `2` | Increase only for lab scale testing. |
| `vmSize` | `Standard_B2s` | Low-cost default; use `Standard_B2ms` if Windows feels too constrained. |
| `adminUsername` | `farsightadmin` | Local admin username. |
| `adminPassword` | placeholder | Replace at deployment time; do not commit real passwords. |
| `vnetAddressPrefix` | `10.70.0.0/16` | Must not overlap connected networks. |
| `subnetAddressPrefix` | `10.70.1.0/24` | Windows test VM subnet. |
| `enablePublicIp` | `false` | Keep disabled unless a short-lived break-glass exception is approved. |
| `allowedRdpSourceAddressPrefixes` | `[]` | Required if public IP/RDP is enabled. |
| `enableNatGateway` | `false` | Enable for outbound internet without public IPs. |

## Deployment procedure

### 1. Create a dedicated resource group

Use a dedicated lab resource group so cleanup is simple. Recommended naming:

```text
rg-farsight-lab-dev
```

Create it in the same region you plan to use for the VMs.

### 2. Prepare secure parameters

Do not commit a real password to `main.parameters.json`.

Use one of these approaches:

- copy `main.parameters.json` to a local ignored file and replace the placeholder there;
- pass `adminPassword` securely at deployment time;
- use your organization's approved secret injection process.

Also decide whether the lab VMs need outbound internet:

- If the VMs are private and need Windows Update, Intune enrollment, package downloads, or Entra sign-in paths through the internet, set `enableNatGateway=true`.
- If outbound internet is handled by your corporate network, firewall, proxy, or another route, keep `enableNatGateway=false`.

### 3. Preview the deployment

Preview the Bicep deployment before creating resources. Review the planned resources:

- VNet and subnet address prefixes.
- NSG rules.
- VM count and size.
- Public IP setting.
- NAT Gateway setting.
- Windows image publisher/offer/SKU.

Do not continue if the preview shows public IPs or RDP rules you did not intend.

### 4. Deploy the lab

Deploy `main.bicep` to the dedicated lab resource group with the reviewed parameters.

After deployment, record:

- VM names.
- Private IP addresses.
- VNet/subnet names.
- Whether NAT Gateway was enabled.
- Resource group name for cleanup.

### 5. Establish private admin access

Use an approved private administration path:

- Azure Bastion managed by the platform team;
- VPN or ExpressRoute-connected workstation;
- approved jumpbox;
- just-in-time access flow.

Avoid public RDP. If public RDP is temporarily enabled, restrict source prefixes and remove the exception immediately after use.

### 6. Enroll VMs into Intune

For each VM:

1. Sign in or join the device using the tenant-approved Entra/Intune enrollment method.
2. Confirm the device appears in Intune.
3. Confirm the expected user/device compliance and enrollment profile state.
4. Add the device or user to the FarSight lab assignment group.
5. Wait for Intune policy sync.

### 7. Assign the FarSight collector

Follow [Collector distribution with Intune](../docs/intune/collector-distribution.md) to package and assign the collector.

For the lab ring:

- assign the Win32 app to only the lab group;
- assign Remediations to only the lab group;
- confirm the certificate profile is present before expecting successful mTLS check-in;
- confirm collector scheduled task creation and first no-job check-in.

### 8. Run a smoke test

Start with a no-job cycle:

- collector installed;
- scheduled task exists;
- collector runs once and exits;
- local structured log is created;
- FarSight API receives check-in;
- no diagnostic job executes unless explicitly created.

Then create one low-risk read-only diagnostic job and confirm the expected result envelope is submitted.

## Cleanup

When testing is complete:

1. Remove lab devices/users from FarSight Intune assignment groups.
2. Unassign or uninstall the collector package.
3. Preserve required logs according to retention policy.
4. Delete the lab resource group.
5. Remove stale Intune device records if your tenant process requires it.

## Related docs

- [Development lab setup](../docs/development/setup-lab.md)
- [Collector distribution with Intune](../docs/intune/collector-distribution.md)
- [Greenfield Azure deployment](../docs/deployment/azure-greenfield-deployment.md)
