# AGT policy and SRE agent tooling guidance

Use this reference when a new module must be callable by the Azure SRE Agent or governed by AGT policy.

## Policy placement

The canonical policy is:

```text
src/api/app/policies/farsight-tool-policy.yaml
```

The API seeds and serves active policies from the policy repository. The gateway loads policy from the API and fails closed when policy cannot be loaded or evaluated.

## Rule ordering

Put narrow deny rules before broad allow rules.

Good order:

1. deny dangerous input;
2. deny module-specific unsafe scope;
3. require approval for broader/sensitive variants;
4. allow safe read-only baseline;
5. default deny catches everything else.

## Risk tiers

Default to `read-only` only when the module:

- reads local state without changing endpoint configuration;
- is bounded by schema/profile;
- redacts sensitive text;
- has small artifact caps;
- uses approved app/device scopes.

Use `sensitive-diagnostic` or require approval when:

- the module can collect broad logs or large artifacts;
- the module reads identity/auth/certificate/user-profile metadata;
- the time window is long;
- the target app profile is sensitive;
- output can include customer data or regulated data.

## Policy evidence

SRE wrappers and gateway payloads should expose structured evidence fields instead of prose:

```json
{
  "tool_name": "create_diagnostic_job",
  "task_type": "Get-AppLogBundle",
  "risk_level": "read-only",
  "device_id": "fswin111",
  "app_id": "contoso-api",
  "profile": "default",
  "max_bytes": 10485760,
  "max_files": 20,
  "time_window_hours": 2,
  "redaction_profile": "default",
  "approved_app_log_path": true
}
```

AGT policy should not need to parse arbitrary JSON strings to decide.

## Example policy pattern

```yaml
- name: deny-module-unapproved-path
  condition: "task_type == 'Get-AppLogBundle' and approved_app_log_path != true"
  action: deny
  description: "App log collection can only read app-profile-approved paths."

- name: require-approval-for-large-module-output
  condition: "task_type == 'Get-AppLogBundle' and (max_bytes > 10485760 or max_files > 20 or time_window_hours > 24)"
  action: require_approval
  description: "Large or broad log collection requires human approval."

- name: allow-read-only-module
  condition: "tool_name == 'create_diagnostic_job' and risk_level == 'read-only' and task_type == 'Get-AppLogBundle' and approved_app_log_path == true"
  action: allow
  description: "Allow bounded, redacted app log collection."
```

## SRE agent wrapper updates

When adding a new callable module, check:

```text
src/sre-agent/agent/tools/create_diagnostic_job.py
src/sre-agent/agent/tools/create_diagnostic_job.yaml
src/sre-agent/agent/tools/request_follow_up_module_execution.py
src/sre-agent/agent/tools/request_follow_up_module_execution.yaml
src/sre-agent/agent/skills/farsight-tool-orchestration/SKILL.md
```

Update:

- allowed task type set;
- parameter validation;
- YAML tool parameter documentation;
- risk-level defaults;
- idempotency key inputs if needed;
- monitoring/retrieval guidance.

## Gateway telemetry

Tool calls should emit telemetry for the admin console:

- tool name;
- policy decision;
- actor object ID and app ID;
- policy name/version/rule;
- job ID and correlation ID;
- timestamp.

Do not let telemetry failures block tool execution.

## Admin console expectations

If the module adds a new artifact kind or summary shape, ensure:

- job detail can display the summary clearly;
- artifact metadata has kind/name/size/hash;
- tool-call detail shows enough context for approvals and audits;
- docs explain how operators interpret findings.

