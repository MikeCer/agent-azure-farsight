# Regional topology

## Primary pattern

- Deploy API, queue, storage, monitoring, and Key Vault into the approved Azure region for the tenant.
- Keep endpoint collectors region-aware through configuration delivered by Intune.
- Prefer private endpoints and managed identities for Azure-to-Azure traffic.

## Resilience

- Use zone-redundant services where available.
- Document regional failover and data residency requirements before enabling secondary regions.

## Known gaps

- Add region map, RTO/RPO, and failover runbook links after environment provisioning.
