# Skill: FarSight Diagnostics

## When to use this skill

Use this skill when the Azure SRE Agent must guide or run a governed FarSight endpoint diagnostic workflow for a device, user symptom, incident, or follow-up investigation. FarSight is for controlled endpoint diagnostics through approved diagnostic jobs and named modules only.

Trigger strongly when the user asks things like:

- "run FarSight diagnostics"
- "investigate this endpoint with FarSight"
- "create a diagnostic job"
- "check the FarSight job status"
- "summarize the diagnostic results"
- "retrieve artifact metadata"
- "run a follow-up module"
- "request approval for a remediation action"
- "what happened in previous investigations for this device"

If the evidence is Intune diagnostics collector JSON from `intune_diagnostics_tool`, Microsoft Graph/Intune evidence, Endpoint Analytics data, app reliability data, restart/shutdown events, or Intune timeline events, use the complementary `intune-data-analysis` skill. Use this FarSight skill when the next step requires live governed FarSight diagnostics, FarSight artifacts, FarSight job history, or approved named module execution.

## Non-negotiable safety guardrails

FarSight workflows must remain governed and auditable:

- Never request, generate, or execute a reverse shell.
- Never run arbitrary PowerShell, shell commands, scripts, encoded commands, or user-provided command text.
- Use named FarSight modules only. Do not invent module names or bypass module catalogs.
- Pass only schema-validated parameters accepted by the selected named module.
- Respect endpoint allowlists, tenant scoping, device scoping, rate limits, and maintenance windows.
- Redact secrets, tokens, credentials, user identifiers, hostnames, IPs, and other sensitive data unless the current workflow explicitly permits disclosure.
- Retrieve artifact metadata before artifact content; only request bounded artifacts needed for the investigation.
- Keep artifact access bounded by size, count, time range, retention policy, and least-privilege need.
- Treat destructive, privacy-sensitive, high-volume, persistence-changing, isolation, quarantine, restart, collection-expansion, or remediation actions as higher risk.
- Use `request_approval_for_action` before any higher-risk action or follow-up that could alter endpoint state, collect sensitive data, increase scope, or affect user productivity.
- If approval is denied, missing, ambiguous, or expired, do not proceed with the higher-risk action. Provide safe alternatives.

## Language behavior

- If the user writes in Italian, respond in Italian.
- If the user writes in English, respond in English.
- If the prompt mixes languages, prefer the user's dominant language.
- Keep FarSight tool names, module names, JSON paths, product names, IDs, and parameter names unchanged.
- For Italian responses, translate headings and explanations naturally while preserving technical identifiers such as `create_diagnostic_job`, `job_id`, and `module_parameters`.

## Diagnostic workflow

### 1. Scope the investigation

Collect only the minimum data needed to start:

| Needed data | Examples | If missing |
| --- | --- | --- |
| Target | `device_identifier`, `device_name`, device id | Ask for one stable identifier or explain that a job cannot be safely targeted. |
| Symptom | user impact, alert, incident, performance/security/health concern | State assumptions and choose a low-risk baseline diagnostic goal only if target is clear. |
| Time window | incident start/end, "last 24 hours" | Use `latest_relevant_window` and mark the time window as a confidence limitation. |
| Tenant/scope | tenant id, workspace, environment | Do not cross tenant or endpoint allowlists; ask for missing scope. |
| Approval context | change ticket, incident id, approver, business impact | Required before higher-risk actions. |

Before creating new work, use `query_device_investigation_history` when prior FarSight context may change the plan, such as repeated symptoms, an existing active job, prior approvals, recent failed modules, or duplicate investigations.

### 2. Query investigation history

Use `query_device_investigation_history` to find prior or active investigations for the target device.

Use it when:

- The device has an ongoing incident or repeated symptom.
- The user asks what was already investigated.
- You need to avoid duplicate jobs or correlate current findings with prior runs.
- Approval, artifact, or module history may constrain the next action.

How to use it conceptually:

```json
{
  "device_identifier": "<device-or-asset-id>",
  "time_window": "<bounded-lookback>",
  "include_active_jobs": true
}
```

Summarize relevant prior jobs, modules, findings, approvals, and unresolved follow-ups. Do not expose sensitive artifact values; use redacted summaries.

### 3. Create a governed diagnostic job

Use `create_diagnostic_job` when a new FarSight diagnostic run is needed and the target/scope are clear.

Use it for:

- Low-risk baseline diagnostics.
- Approved incident-specific diagnostic plans.
- Collecting structured evidence from named modules.

How to use it conceptually:

```json
{
  "device_identifier": "<device-or-asset-id>",
  "diagnostic_goal": "<performance|health|security|connectivity|incident-specific>",
  "time_window": "<bounded-time-window>",
  "modules": [
    {
      "name": "<approved_named_module>",
      "parameters": {}
    }
  ],
  "safety": {
    "named_modules_only": true,
    "schema_validated_parameters": true,
    "endpoint_allowlist_required": true,
    "redaction_required": true,
    "artifact_bounds_required": true
  }
}
```

Do not create a job when the target is ambiguous, the requested module is not approved, parameters are not schema-valid, the endpoint is outside allowlists, or the user asks for arbitrary command execution.

### 4. Track job execution

Use `get_job_status` after job creation and while waiting for completion.

Use it to report:

- `job_id`
- current state
- started/updated timestamps
- completed, failed, cancelled, timed out, or waiting states
- safe next step

How to use it conceptually:

```json
{
  "job_id": "<job-id>"
}
```

If a job is still running, do not invent results. Provide current status and when to check again. If a job fails, report the failure stage, safe error detail, retry eligibility, and missing prerequisites.

### 5. Summarize diagnostic results

Use `get_job_result_summary` when the job is complete or has partial results explicitly available.

Use it to produce:

- confirmed findings
- likely hypotheses
- healthy/not-indicated areas
- module-level evidence
- confidence and limitations
- recommended next steps

How to use it conceptually:

```json
{
  "job_id": "<job-id>",
  "redaction": "required",
  "include_artifact_references": true
}
```

Base conclusions on returned FarSight evidence only. Do not claim OS event log, process, network, security, or configuration facts that are not present in the summary or approved artifacts.

### 6. Retrieve artifact metadata before content

Use `retrieve_artifact_metadata` before requesting any artifact content or expanded collection.

Use it to determine:

- artifact type and source module
- size, record count, and retention
- sensitivity classification
- time range
- redaction state
- whether approval is required for content access

How to use it conceptually:

```json
{
  "job_id": "<job-id>",
  "artifact_id": "<artifact-id>",
  "metadata_only": true
}
```

Only recommend accessing artifact content when it is necessary, bounded, allowed, redacted, and proportionate to the diagnostic question.

### 7. Request follow-up named module execution

Use `request_follow_up_module_execution` when the result summary identifies a specific evidence gap that a named FarSight module can safely close.

Use it only when:

- The module name is from the approved catalog.
- Parameters match the module schema.
- The target remains within endpoint allowlists.
- Artifact bounds are explicit.
- The follow-up is proportional to the investigation.
- Required approvals have been granted for higher-risk follow-ups.

How to use it conceptually:

```json
{
  "job_id": "<parent-job-id>",
  "module_name": "<approved_named_module>",
  "module_parameters": {},
  "reason": "<specific evidence gap>",
  "artifact_bounds": {
    "time_window": "<bounded-time-window>",
    "max_records": "<bounded-count>",
    "max_bytes": "<bounded-size>"
  }
}
```

Do not use this tool to run arbitrary commands, PowerShell, scripts, reverse shells, unrestricted file collection, or unbounded searches.

### 8. Request approval for higher-risk actions

Use `request_approval_for_action` before actions that may alter endpoint state, collect sensitive data, expand scope materially, increase cost/load, or affect user productivity.

Approval requests must include:

- action name and module name
- target device/scope
- reason and expected benefit
- risk classification
- sensitive data/artifact impact
- exact schema-validated parameters
- rollback or stop condition when applicable
- expiration/time window
- approver or approval channel if available

How to use it conceptually:

```json
{
  "action": "<higher-risk-action-or-follow-up>",
  "target": "<device-or-scope>",
  "risk": "<medium|high|critical>",
  "reason": "<why this is necessary>",
  "parameters": {},
  "bounds": {},
  "expires_at": "<approval-expiration>"
}
```

Proceed only after approval is explicitly granted and still valid. Record approval status in the investigation summary.

## Missing-data guidance

Be explicit and safe when required data is missing:

- Missing target: do not create a job; ask for a stable device identifier.
- Ambiguous device: do not choose a device by guess; request a disambiguator.
- Missing symptom: run only low-risk baseline diagnostics if target and scope are clear; otherwise ask for the symptom.
- Missing time window: use a conservative default and state the limitation.
- Missing tenant or allowlist status: do not proceed until scope is established.
- Missing module schema or unknown module: do not run it; ask for an approved named module or catalog entry.
- Missing approval: do not perform higher-risk actions; provide the exact approval needed.
- Missing artifact metadata: do not request artifact content; retrieve metadata first.
- Tool unavailable or failed: report the failed step, what is known, what is unknown, and the safest next step.

## Suggested response format

Use concise Markdown with evidence-first conclusions:

```markdown
## 📌 Executive summary
[2-4 sentences. Most important finding first. Include job status or whether a job was not started.]

| Area | Status | Evidence | Impact |
| --- | --- | --- | --- |
| [Performance/health/security/etc.] | [🔴/🟠/🟡/🔵/✅/⚪] | [FarSight job/module/artifact evidence] | [Plain-language impact] |

## 🧭 Scope and governance
- Target: [device/scope or "missing"]
- Time window: [window]
- FarSight job: [job_id/status]
- Guardrails: named modules only, schema validation, endpoint allowlist, redaction, artifact bounds
- Approval status: [not needed/requested/granted/denied/missing]

## 🔎 Findings
1. [Confirmed/Likely/Not indicated] [finding]
   - Evidence: [module/result/artifact metadata reference]
   - Confidence: [High/Medium/Low]

## 🧪 Follow-up diagnostics
- [Named module only, why it is needed, required parameters, artifact bounds]
- [State whether approval is required before execution]

## 🛡️ Safety and data handling
- [Redactions applied]
- [Sensitive artifacts avoided or bounded]
- [Any actions blocked by guardrails]

## 🛠️ Recommended actions
1. [Manual or approval-gated action, priority, evidence addressed, expected outcome]

## 🔎 Missing data that would improve confidence
- [Only data that materially changes the diagnosis]
```

Severity glyphs: 🔴 Critical, 🟠 High, 🟡 Medium, 🔵 Low, ✅ Healthy/OK, ⚪ Informational.

## How to phrase uncertainty

Use:

- "Confirmed by FarSight evidence" when a module result directly supports it.
- "Likely" when multiple FarSight signals point to it but root cause is not explicit.
- "Not indicated" when relevant checks are present and healthy.
- "Missing" when required evidence is absent.
- "Blocked by guardrail" when a requested action violates safety rules.
- "Approval required" when the action is allowed only after explicit approval.

Avoid:

- Claiming facts not present in FarSight summaries or approved artifacts.
- Treating missing data as healthy.
- Recommending arbitrary scripts, PowerShell, reverse shells, or unbounded artifact collection.
- Presenting approval-gated actions as already executed.
