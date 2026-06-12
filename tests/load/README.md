# Load Tests

Planned scope from the validation strategy:

- Medium-scale check-in cadence simulation for 1K-100K endpoint design assumptions.
- Queue depth and Service Bus session behavior.
- Cosmos RU consumption, partition-key correctness, and ETag conflict retries.
- API latency and result-upload throughput.
- Soak testing for collector heartbeat and job lifecycle reliability.

Load tests should use bounded dev/test targets and must not run automatically against production.
