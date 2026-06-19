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

### End-to-end module flow check: Get-ServiceStatusSnapshot

Use this sequence to validate the complete FarSight path after policy/module updates:

1. Invoke `create_diagnostic_job` with `task_type=Get-ServiceStatusSnapshot`, `risk_level=read-only`, bounded `service_names_csv`, and `max_services`.
2. Verify gateway policy decision is `allow` for `farsight-tool-policy`.
3. Confirm API job creation (`Queued`), collector lease transition (`Leased`), and result submission (`Succeeded`).
4. Query `get_job_result_summary` and `retrieve_artifact_metadata` for the same job.
5. Confirm summary fields include service counts and warnings, and artifact metadata is present only when `include_artifact=true`.

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

## Approval operations

Use the admin web Approvals page to handle AGT `require_approval` outcomes:

1. Review pending approval details, including requested action, device, module/task type, risk, requester, reason, expiry, and linked job.
2. Approve only when the request scope is bounded and justified. Approval releases linked `waiting_approval` jobs to `Queued` so the collector can lease them on its next check-in.
3. Deny requests that are too broad, unapproved, expired, or insufficiently justified. Denial marks linked jobs `Cancelled`.
4. After deciding, monitor the related job in Diagnostic jobs and rely on SRE Agent scheduled follow-up/Outlook notification for the requester.

## Admin console navigation

- Each data-rich blade in the admin console includes a refresh action so operators can pull the latest server state without reloading the page.
- Browser back/forward stays within the single-page console and moves between console blades instead of leaving the app immediately.

## Incident response

Disable affected module IDs, revoke credentials, preserve audit logs, notify owners, and document customer impact.

## Known gaps

- Link live workbooks and alert rule IDs.
