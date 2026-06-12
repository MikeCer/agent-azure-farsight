# FarSight Intune test lab infrastructure

`infra-test/` contains a small Bicep template for creating Windows 11 test clients and a virtual network for FarSight collector and Intune rollout testing.

## What it deploys

- One virtual network.
- One subnet protected by an NSG.
- Two Windows 11 VMs by default.
- One NIC and OS disk per VM.
- Optional public IPs for break-glass testing only.

## Cost posture

The default VM size is `Standard_B2s`, which is intended for intermittent low-cost dev/test use. Stop or delete the VMs when they are not being used. Override `vmSize` if Windows 11 performance is not acceptable for your test scenario.

## Security defaults

- Public IPs are disabled by default.
- Public RDP is denied by default.
- Trusted Launch is enabled.
- Boot diagnostics are enabled.
- Admin password is a secure parameter.

Use Azure Bastion, VPN, ExpressRoute, or another approved private access path for interactive administration. If public IPs are temporarily enabled, restrict RDP sources with `allowedRdpSourceAddressPrefixes`.

## Intune enrollment note

Bicep creates Windows 11 VMs, but it does not automatically enroll them into Intune. After deployment:

1. Confirm Intune MDM auto-enrollment is configured in the tenant.
2. Sign in to each VM with a licensed Entra user or use the organization's approved enrollment flow.
3. Confirm the device appears in Intune.
4. Add the device or user to the FarSight lab assignment group.
5. Apply the FarSight collector deployment and remediation assignments.

## Deployment guidance

Use a dedicated resource group for the lab. Provide a secure admin password at deployment time rather than committing real secrets into `main.parameters.json`.

Required planning values:

| Parameter | Default | Notes |
| --- | --- | --- |
| `vmCount` | `2` | Increase only for lab scale testing. |
| `vmSize` | `Standard_B2s` | Low-cost default. |
| `vnetAddressPrefix` | `10.70.0.0/16` | Must not overlap connected networks. |
| `subnetAddressPrefix` | `10.70.1.0/24` | Windows test VM subnet. |
| `enablePublicIp` | `false` | Keep disabled unless approved for break-glass testing. |

## Cleanup

Delete the lab resource group when testing is complete. Also remove or retire matching Intune assignment group memberships so stale devices do not receive collector policy.
