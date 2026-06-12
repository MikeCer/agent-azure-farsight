# End-to-End Tests

Planned scope from the validation strategy:

- Device simulator completing check-in, job fetch, execution, result, and artifact metadata flows.
- API, Service Bus, Cosmos DB, Storage, and telemetry integration in a dev environment.
- Windows E2E validation for Intune-deployed collectors on pilot devices or test VMs.
- Queue failure paths such as duplicate messages, stale leases, expired jobs, and DLQ handling.

E2E tests must remain non-destructive by default and use explicit dev/test environment configuration.
