# Regional topology

## Primary pattern

- Deploy API, AGT tool gateway, queue, storage, monitoring, and Key Vault into the approved FarSight control-plane region for the tenant.
- Keep endpoint collectors region-aware through configuration delivered by Intune.
- Prefer private endpoints and managed identities for Azure-to-Azure traffic.
- Deploy Azure SRE Agent resources separately in a service-supported region, such as Sweden Central, and connect them to FarSight through the approved private route or public development endpoint.

## Resilience

- Use zone-redundant services where available.
- Document regional failover and data residency requirements before enabling secondary regions.

## Known gaps

- Add region map, RTO/RPO, and failover runbook links after environment provisioning.
