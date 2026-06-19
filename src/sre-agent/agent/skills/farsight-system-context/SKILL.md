# Skill: FarSight System Context

## When to use this skill

Use this skill to reason about **what FarSight should do** before deciding **which tool call to execute**.

Activate when:

- the user describes a Windows endpoint symptom and you need to pick the right diagnostic module;
- you need to decide whether Intune-native evidence is sufficient or FarSight endpoint collection is needed;
- you want to understand module scope, risk tier, required parameters, or approval implications before orchestrating;
- you want to verify that a proposed module is in the active catalog and allowed by policy.

## FarSight module catalog

| Module | Purpose | Risk | Key parameters |
|---|---|---|---|
| `Get-AppLogBundle` | Collect bounded, redacted app logs from an approved folder | read-only | `app_id` (required), `log_path_folder` (required), `include_patterns_csv`, `exclude_patterns_csv`, `start_time_utc`, `end_time_utc`, `tail_lines`, `max_bytes`, `redaction_profile` |
| `Get-AppEventSlice` | Bounded Windows event-log slice by provider/time/level | read-only | `log_name` (required), `start_time_utc` (required), `end_time_utc` (required), `provider_names_csv`, `event_ids_csv`, `levels_csv`, `max_events` |
| `Get-AppHealthSnapshot` | Service/process/config health for an app profile | read-only | `app_id` (required), `service_names_csv`, `process_names_csv`, `config_profiles_csv` |
| `Test-AppConnectivity` | DNS/TCP/TLS/HTTP reachability checks | read-only | `targets_csv`, `ports_csv`, `urls_csv`, `dns_names_csv`, `expected_tls_thumbprints_csv` |
| `Get-ConfigEvidence` | Registry and filesystem configuration evidence | read-only | `registry_profiles_csv`, `file_profiles_csv`, `redaction_profile` |
| `Get-ServiceStatusSnapshot` | Windows service inventory with runtime status | read-only | `service_names_csv`, `max_services`, `include_startup_type`, `include_service_account`, `include_artifact` |

Extension (not always allowed by active policy):

| Module | Purpose | Risk | Key parameters |
|---|---|---|---|
| `Get-AppDiskEvidence` | Bounded disk artifact sampling for an app profile | read-only | `disk_profile` (required), `include_file_samples`, `max_file_samples` |

## Module selection decision tree

```text
User symptom → Which module?

App logs needed (errors, traces, output files)
  → Get-AppLogBundle (requires app_id + log_path_folder)

Windows Event Log slice needed (system events, provider logs)
  → Get-AppEventSlice (requires log_name + time window)

App runtime health (services running? processes alive? config state?)
  → Get-AppHealthSnapshot (requires app_id)

Network reachability (DNS, ports, TLS certs, HTTP endpoints)
  → Test-AppConnectivity (requires at least one target)

Registry/config state (settings drift, expected values)
  → Get-ConfigEvidence (requires registry or file profiles)

Windows service inventory (what's running/stopped/disabled)
  → Get-ServiceStatusSnapshot (optional service filter)

Disk artifacts for an app (installed files, cache, package state)
  → Get-AppDiskEvidence (requires disk_profile)
```

## Policy and governance model

- FarSight execution is **deny-by-default** via the active `farsight-tool-policy`.
- Both the tool contract and the AGT policy must allow a request for it to proceed.
- `read-only` modules are allowed automatically when the module is in the policy allowlist.
- `sensitive-diagnostic` risk level or broad collection (large `max_bytes`, many files, long time window) triggers `require_approval`.
- Approval-gated jobs enter `waiting_approval` status and are invisible to collector polling until an administrator approves them.
- When a job is waiting for approval, **do not block the conversation**. Schedule a follow-up check and use the Outlook connector for completion/denial/expiry notification.
- Use metadata-first artifact handling (`retrieve_artifact_metadata`) before downloading content.
- For ZIP artifacts (e.g., `Get-AppLogBundle` output), first download the ZIP into the SRE Agent workspace, then use `extract_zip_artifact_entry` to list contents or extract a specific file locally. Do not use `retrieve_artifact_content` on ZIP artifacts.

## Evidence boundary guidance

| Evidence source | When to use |
|---|---|
| `intune-data-analysis` skill | Intune/Graph-native evidence: compliance, Endpoint Analytics, app reliability, device health, timeline events |
| FarSight modules | Governed endpoint diagnostics: app logs, event slices, connectivity, config, service state |
| Both combined | When Intune signals identify the problem area but endpoint evidence is needed to confirm root cause |

## Outputs from this skill

After applying this skill, produce:

1. **Recommended `task_type`** — the module name to use.
2. **Required parameters** — which parameters the tool will need (especially `log_path_folder` for app logs, `log_name` for events).
3. **Risk level** — `read-only` or `sensitive-diagnostic` based on scope.
4. **Guardrails** — time bounds, byte/file caps, redaction profile.
5. **Prerequisites** — device identity (`device_id`), correlation ID, approval state if needed.
