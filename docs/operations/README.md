# Operations

Operations guidance covers the intended production posture. Current dashboards, workbooks, and alert rule IDs are not finalized yet; use these sections as the checklist for implementation and review.

## Dashboards

Track API availability, job queue depth, collector check-in freshness, job success rate, module duration, redaction counts, and policy outcomes.

## Alerts

- Collector check-in drops below threshold.
- Job failure rate spikes.
- mTLS failures increase.
- Artifact upload failures occur.
- Policy deny or approval volume changes unexpectedly.

## KQL queries

```kusto
FarSightJobs
| summarize count() by Status, ModuleId, bin(TimeGenerated, 1h)
```

```kusto
FarSightPolicy
| summarize count() by Outcome, Reason, bin(TimeGenerated, 1d)
```

## Runbooks

- Collector not checking in.
- Job stuck in queued state.
- Result schema validation failure.
- Certificate expiry or revocation.
- Suspected sensitive artifact exposure.

## Backup and restore

Back up configuration, policy, schemas, and required operational metadata. Do not keep raw evidence longer than retention policy.

## Incident response

Disable affected module IDs, revoke credentials, preserve audit logs, notify owners, and document customer impact.

## Known gaps

- Link live workbooks and alert rule IDs.
