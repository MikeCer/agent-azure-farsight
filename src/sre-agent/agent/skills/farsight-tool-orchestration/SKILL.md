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
3. If the response is `approval_required` or the job status is `waiting_approval`, stop synchronous monitoring. Tell the user the job is waiting for admin approval, create a scheduled SRE Agent platform follow-up to check completion later, and use the configured Outlook connector to notify the requester when the job completes, is denied, or expires.
4. If approval is not required, use **`monitor_farsight_job`** — pass the `jobId` and `task_type` immediately after creation. The tool waits, polls, and returns the terminal state and result summary automatically. **Do not manually poll with `get_job_status` when `monitor_farsight_job` is available.**
5. Present findings from `monitor_farsight_job.summary` to the user.
6. `retrieve_artifact_metadata` — list artifacts for a job.
7. `retrieve_artifact_content(job_id, artifact_id)` — download the artifact content (JSON/text, ≤256 KB) for analysis. If too large or binary → `request_follow_up_module_execution` for a smaller slice.
8. `extract_zip_artifact_entry(zip_path, entry_path?)` — for ZIP artifacts already downloaded into the SRE Agent workspace. Call without `entry_path` to list ZIP contents, then call again with a specific `entry_path` to extract that file to a local output directory.
9. `request_follow_up_module_execution` only for bounded evidence gaps.
10. `request_approval_for_action` when a separate approval request is needed before creating a higher-risk action.

> Use `get_job_status` and `get_job_result_summary` only to recover an old job or when the monitor timed out.

## monitor_farsight_job — preferred async pattern

```json
{
  "job_id": "<jobId from create_diagnostic_job>",
  "task_type": "Get-ServiceStatusSnapshot"
}
```

The tool:
- Waits `initial_delay_seconds` (default 30s) before first poll — collector check-in cadence
- Stops and reports pending human approval when status is `waiting_approval`
- Polls with status-aware intervals: Queued=30s, Leased=20s, Running=15s
- Auto-times out per module: 180s for `Get-ServiceStatusSnapshot`, 300s for `Get-AppLogBundle`, etc.
- On `Succeeded`: fetches `get_job_result_summary` and returns it inline
- On `Failed`/`Expired`: returns status with message for the user
- On timeout: returns last status so the agent can report and offer to retry later

**Do not call `get_job_status` in a manual loop when `monitor_farsight_job` is available.**

## Async job lifecycle

FarSight jobs are **asynchronous**. After `create_diagnostic_job` returns a `jobId`, the job follows this lifecycle before results are available:

```
Queued → Leased → Running → Succeeded | Failed | Expired
```

Approval-gated jobs add a human step:

```text
waiting_approval -> Queued -> Leased -> Running -> Succeeded | Failed | Expired
                 -> Cancelled (admin denied)
```

**Do not call `get_job_status` immediately after job creation.** The collector on the device is scheduled (typically every 5 minutes). Allow time for the collector to pick up the job.

### Polling rules

| Condition | Action |
|---|---|
| Job just created | **Wait at least 30 seconds** before first `get_job_status` call |
| Status is `waiting_approval` | Do **not** keep polling in the same turn. Schedule a follow-up check and notify via Outlook when the job later completes/denies/expires |
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

## Get-AppLogBundle example

```json
{
  "device_id": "fswin111",
  "task_type": "Get-AppLogBundle",
  "correlation_id": "<incident-or-trace-id>",
  "expires_at_utc": "<iso-8601-utc>",
  "risk_level": "read-only",
  "app_id": "contoso-api",
  "log_path_folder": "C:\\ProgramData\\Contoso\\Logs",
  "include_patterns_csv": "*.log,*.jsonl",
  "tail_lines": 2000,
  "max_bytes": 10485760,
  "justification": "Investigating service errors reported by Intune health check"
}
```

Note: `app_id` is **not required** for `Get-ServiceStatusSnapshot`, `Get-ConfigEvidence`, `Test-AppConnectivity`, or `Get-AppDiskEvidence`. Only provide it for `Get-AppLogBundle` and `Get-AppHealthSnapshot`.

**`Get-AppLogBundle` requires `log_path_folder`** — the local path where the application stores logs on the target device (e.g. `C:\ProgramData\Contoso\Logs`). The folder must be under an approved root in the module's app-profiles. `start_time_utc` and `end_time_utc` are optional (defaults to all recent files within profile caps).

## Extracting files from ZIP artifacts

`Get-AppLogBundle` produces a ZIP artifact that should first be downloaded into the SRE Agent workspace. Use `extract_zip_artifact_entry` to inspect its contents locally:

```
1. retrieve_artifact_metadata(job_id="job-abc123") → artifact list includes ZIP file
2. download the ZIP artifact into the SRE Agent workspace
3. extract_zip_artifact_entry(zip_path="C:\\...\\AppWorkload.zip") → { "mode": "list", "entries": [...] }
4. extract_zip_artifact_entry(zip_path="C:\\...\\AppWorkload.zip", entry_path="logs/AppWorkload.log") → { "mode": "extract", "extractedPath": "C:\\...\\farsight-extracted\\AppWorkload\\logs\\AppWorkload.log" }
```

Use the list step to identify the relevant log file by name/size, then extract only what you need for diagnosis. Do not attempt to use `retrieve_artifact_content` on ZIP artifacts — use the local ZIP extraction tool instead.

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

## Approval-required job response

If `create_diagnostic_job` returns:

```json
{
  "status": "approval_required",
  "jobId": "job-...",
  "approvalId": "approval-...",
  "approvalStatus": "pending"
}
```

respond to the user with:

```text
This diagnostic request requires administrator approval before the endpoint collector can run it. I created job <jobId> and approval <approvalId>. I will schedule a follow-up check and notify you by email when the job completes, is denied, or expires.
```

Then create a scheduled SRE Agent platform task that periodically checks `get_job_status(job_id=<jobId>)`. When the status becomes `Succeeded`, call `get_job_result_summary` and use the configured Outlook connector to email the requester with the result summary and next-step artifact guidance. If the status becomes `Cancelled`, `Failed`, or `Expired`, email the terminal state and reason.

## Guardrails

- Never use arbitrary command text or non-catalog module names.
- Active policy may deny even tool-accepted task types.
- If approval is required/missing/expired, do not proceed with higher-risk execution.
- If a job is `waiting_approval`, do not block the current conversation waiting for a human decision.
- Do not poll more than 10 times for a single job.
- Always report job failures and expired jobs to the user rather than silently retrying.
