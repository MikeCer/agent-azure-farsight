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
3. **Wait before polling** — see async lifecycle below.
4. `get_job_status` until terminal state.
5. `get_job_result_summary` for findings.
6. `retrieve_artifact_metadata` before any artifact expansion.
7. `request_follow_up_module_execution` only for bounded evidence gaps.
8. `request_approval_for_action` when `risk_level` is `sensitive-diagnostic` or follow-up scope is higher risk.

## Async job lifecycle

FarSight jobs are **asynchronous**. After `create_diagnostic_job` returns a `jobId`, the job follows this lifecycle before results are available:

```
Queued → Leased → Running → Succeeded | Failed | Expired
```

**Do not call `get_job_status` immediately after job creation.** The collector on the device is scheduled (typically every 5 minutes). Allow time for the collector to pick up the job.

### Polling rules

| Condition | Action |
|---|---|
| Job just created | **Wait at least 30 seconds** before first `get_job_status` call |
| Status is `Queued` or `Leased` | Wait 30–60 seconds, then poll again |
| Status is `Running` | Wait 15–30 seconds, then poll again |
| Status is `Succeeded` | Proceed to `get_job_result_summary` |
| Status is `Failed` or `Expired` | Do not retry automatically; report the failure |
| `get_job_status` returns 404 | Wait 15 seconds and retry (job may not be indexed yet) |

**Maximum polling attempts**: 10 before reporting a timeout to the user.

The `get_job_status` and `get_job_result_summary` tools each have a 60-second tool execution timeout (`timeout_seconds: 60` in their manifests). This timeout covers the HTTP call to the gateway only — it does **not** mean the job will complete within 60 seconds.

### Typical job durations

- `Get-ServiceStatusSnapshot`: 30–120 seconds end-to-end
- `Get-AppLogBundle`, `Get-AppEventSlice`: 60–300 seconds depending on log volume
- `Get-AppHealthSnapshot`: 30–90 seconds
- `Test-AppConnectivity`: 15–60 seconds
- `Get-ConfigEvidence`: 30–120 seconds

## Create job baseline example

```json
{
  "device_id": "<device-id>",
  "task_type": "Get-ServiceStatusSnapshot",
  "correlation_id": "<incident-or-trace-id>",
  "expires_at_utc": "<iso-8601-utc>",
  "risk_level": "read-only",
  "incident_id": "<optional-incident-id>",
  "service_names_csv": "Spooler,W32Time",
  "max_services": 25
}
```

Note: `app_id` is **not required** for `Get-ServiceStatusSnapshot`, `Get-ConfigEvidence`, `Test-AppConnectivity`, or `Get-AppDiskEvidence`. Only provide it for `Get-AppLogBundle` and `Get-AppHealthSnapshot`.

## Polling example flow

```
1. create_diagnostic_job → returns { "jobId": "job-abc123", "status": "Queued" }
2. [wait 30 seconds]
3. get_job_status(job_id="job-abc123") → { "status": "Leased" }
4. [wait 30 seconds]
5. get_job_status(job_id="job-abc123") → { "status": "Running" }
6. [wait 20 seconds]
7. get_job_status(job_id="job-abc123") → { "status": "Succeeded" }
8. get_job_result_summary(job_id="job-abc123") → findings and summary
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
- Do not poll more than 10 times for a single job.
- Always report job failures and expired jobs to the user rather than silently retrying.
