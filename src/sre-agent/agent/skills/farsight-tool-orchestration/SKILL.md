# Skill: FarSight Tool Orchestration

## When to use this skill

Use this skill for **exact FarSight tool calls** and sequencing after scope/module intent is known.

Always align to live tool parameter names:

- `device_id`, `task_type`, `correlation_id`, `expires_at_utc`
- `parent_job_id`, `job_id`
- `risk_level`, `approval_id`

## Canonical workflow sequence

1. `query_device_investigation_history` to avoid duplicate investigations.
2. `create_diagnostic_job` for initial governed execution.
3. `get_job_status` until terminal state.
4. `get_job_result_summary` for findings.
5. `retrieve_artifact_metadata` before any artifact expansion.
6. `request_follow_up_module_execution` only for bounded evidence gaps.
7. `request_approval_for_action` when `risk_level` is `sensitive-diagnostic` or follow-up scope is higher risk.

## Create job baseline example

```json
{
  "device_id": "<device-id>",
  "task_type": "Get-ServiceStatusSnapshot",
  "correlation_id": "<incident-or-trace-id>",
  "expires_at_utc": "<iso-8601-utc>",
  "risk_level": "read-only",
  "incident_id": "<optional-incident-id>",
  "app_id": "<app-or-scope-id>",
  "service_names_csv": "Spooler,W32Time",
  "max_services": 25
}
```

## Follow-up example

```json
{
  "parent_job_id": "<parent-job-id>",
  "device_id": "<device-id>",
  "task_type": "Get-ServiceStatusSnapshot",
  "correlation_id": "<incident-or-trace-id>",
  "expires_at_utc": "<iso-8601-utc>",
  "risk_level": "read-only",
  "app_id": "<app-or-scope-id>",
  "service_names_csv": "Spooler",
  "max_services": 10
}
```

## Approval request example

```json
{
  "approval_id": "<approval-record-id>",
  "correlation_id": "<incident-or-trace-id>",
  "requested_action": "<higher-risk-action-or-follow-up>",
  "risk_level": "sensitive-diagnostic",
  "reason": "<why this is necessary>",
  "expires_at_utc": "<iso-8601-utc>"
}
```

## Guardrails

- Never use arbitrary command text or non-catalog module names.
- Active policy may deny even tool-accepted task types.
- If approval is required/missing/expired, do not proceed with higher-risk execution.
