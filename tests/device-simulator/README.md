# Device Simulator Tests

Planned scope from the validation strategy:

- Simulated endpoint check-in without inbound connectivity.
- Fetching at most one leased job per device session.
- Enforcing manifest, module allowlist, timeout, and size-limit behavior.
- Submitting structured result envelopes and artifact metadata.
- Replaying retries, backoff, local state, and stale lease conditions.

The simulator provides early E2E confidence before Windows/Intune pilot validation is available.
