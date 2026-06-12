# Intune

Intune is the deployment and compliance channel for the FarSight endpoint collector. The current repository provides collector scripts and sample configuration; exact enterprise package names, assignment group IDs, and certificate profiles are environment-specific.

## Deployment scripts

Use Intune to deploy the collector, configuration, certificate material, module manifest, and scheduled task. Scripts must be idempotent and avoid embedding secrets.

## Assignment rings

1. Lab devices.
2. IT pilot.
3. Limited production ring.
4. Broad production rollout.

## Remediations

Intune Remediations can verify collector installation, scheduled task health, certificate presence, and manifest freshness.

## Certificate deployment

Certificates should be delivered using approved enterprise certificate deployment workflows and rotated before expiry.

## Pilot rollout

Track success rate, job latency, API errors, collector errors, and false-positive redaction findings before expanding rings.

## Known gaps

- Add exact Intune package names, assignment group IDs, certificate profile names, and remediation script IDs when the target tenant rollout is defined.
