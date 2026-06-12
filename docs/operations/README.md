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

## Policy operations

Use the admin web policy repository page to edit AGT policies. Recommended workflow:

1. Open the active `farsight-tool-policy` version.
2. Edit YAML in the Monaco editor.
3. Validate before saving.
4. Save as a draft/version with notes.
5. Activate only after validation and peer review.
6. Monitor policy deny/approval counts after activation.

If a policy blocks expected diagnostics, reactivate the previous known-good version and investigate the changed rule.

## Incident response

Disable affected module IDs, revoke credentials, preserve audit logs, notify owners, and document customer impact.

## Known gaps

- Link live workbooks and alert rule IDs.
