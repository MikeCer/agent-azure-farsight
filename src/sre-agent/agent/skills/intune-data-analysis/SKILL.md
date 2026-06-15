# Skill: Intune Data Analysis

## When to use this skill

Use this skill whenever the user asks to analyze output from the Intune diagnostics collector produced by `intune_diagnostics_tool`, Endpoint Analytics evidence, Intune health/compliance data, app reliability data, restart/shutdown events, or device timeline events.

The collector source for this tool is under `src/sre-agent/intune-collector/` (renamed to avoid confusion with the FarSight endpoint collector under `src/collector/`).

Trigger strongly when the user says things like:

- "analyze this Intune JSON"
- "act as SRE agent"
- "performance analysis"
- "bottlenecks"
- "health check"
- "why is this Windows client slow"
- "analyze Endpoint Analytics"
- "review the collector output"
- "diagnose device WIN-CLIENT-001"
- "analyze logs for device WIN-CLIENT-001"
- "what remediation should I do"

## Supported inputs and tool invocation

This skill supports two entry paths:

1. If `collector_json` is provided, analyze that JSON directly.
2. If the user provides a `device_name` but no collector JSON, first collect Intune evidence with `intune_diagnostics_tool`, then analyze the generated JSON.

Use `intune_diagnostics_tool` when device evidence must be collected:

```json
{
  "device_name": "<deviceName>",
  "auth_mode": "default"
}
```

The default auth path is managed identity. Use `key-vault` only when you explicitly want Key Vault-backed service-principal credentials.

Supported Python tool parameters:

| Parameter | Required | Default | Purpose |
| --- | --- | --- | --- |
| `device_name` | Yes | none | Intune `deviceName` to diagnose. |
| `auth_mode` | No | `auto` | Authentication mode for Microsoft Graph: `auto`, `default`, or `client-secret`. The deployment defaults to managed identity. |
| `tenant_id` | No | none | Optional tenant metadata to include in the output. |
| `azure_tenant_id` | No | none | Optional service-principal tenant id. Use with `azure_client_id` and `azure_client_secret`. |
| `azure_client_id` | No | none | Optional service-principal client id. Use with `azure_tenant_id` and `azure_client_secret`. |
| `azure_client_secret` | No | none | Optional service-principal client secret. Supply only through an approved secret mechanism. |
| `key_vault_url` | No | none | Optional Key Vault URL containing service-principal credential secrets. |
| `tenant_id_secret_name` | No | none | Optional Key Vault secret name containing the tenant id. |
| `client_id_secret_name` | No | none | Optional Key Vault secret name containing the client id. |
| `client_secret_secret_name` | No | none | Optional Key Vault secret name containing the client secret. |
| `managed_device_id` | No | none | Disambiguates duplicate Intune device names. |
| `azure_ad_device_id` | No | none | Disambiguates duplicate Intune device names by Entra device id. |
| `serial_number` | No | none | Disambiguates duplicate Intune device names by serial number. |
| `include_pii` | No | `false` | Includes user and device identifiers that may be PII. Use only when explicitly approved. |
| `include_beta_endpoint_analytics` | No | `true` | Includes beta Endpoint Analytics evidence. |
| `max_resolution_pages` | No | `20` | Caps pages used while resolving the device. |
| `max_optional_pages` | No | `5` | Caps optional collection pages. |

When `auth_mode` is `client-secret`, credentials can be supplied in one of three ways:

1. Prefer Key Vault: provide `key_vault_url`, `tenant_id_secret_name`, `client_id_secret_name`, and `client_secret_secret_name`.
2. Provide direct runtime parameters: `azure_tenant_id`, `azure_client_id`, and `azure_client_secret`.
3. Use runtime environment variables: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`.

With `auth_mode` set to `auto`, use supplied credentials when all three values are available; otherwise use the default managed identity or developer credential chain.

If collection returns an ambiguous-device finding, ask the user for one disambiguator or rerun with the available one: `managed_device_id`, `azure_ad_device_id`, or `serial_number`.

Do not set `include_pii` to `true` unless the user explicitly approves PII in the current diagnostic context.

## Language behavior

- If the user writes in Italian, respond in Italian.
- If the user writes in English, respond in English.
- If the prompt mixes languages, prefer the user's dominant language.
- Keep technical field names, JSON paths, Microsoft Graph names, product names, and tool parameter names unchanged.
- For Italian responses, translate headings and explanations naturally while preserving evidence field names such as `diagnostic_evidence.performance.startup`.

## Expected input schemas

### Intune collector JSON

The Intune collector emits a single focused schema:

```json
{
  "schema_version": "1.0",
  "target": {},
  "assessment": {},
  "issues": [],
  "diagnostic_evidence": {}
}
```

Important sections:

| JSON path | Meaning |
| --- | --- |
| `target` | Device name, Intune managed device id, Entra device id, redacted user id |
| `assessment` | Collector-generated first-pass status and top concerns |
| `issues` | Collector-generated prioritized findings with evidence and recommended actions |
| `diagnostic_evidence.device` | Device OS, model, management/compliance state, enrollment and last sync |
| `diagnostic_evidence.device_health` | Encryption, storage, memory, malware counts, management certificate expiration |
| `diagnostic_evidence.performance.startup` | Startup score, boot/login scores, boot timings, restarts, blue screens |
| `diagnostic_evidence.performance.resource` | CPU/RAM spike scores, resource score, RAM, CPU, machine type |
| `diagnostic_evidence.performance.app_reliability` | App crash/hang counts and reliability score |
| `diagnostic_evidence.installed_applications` | Installed/detected apps: display name, publisher, version |
| `diagnostic_evidence.app_crashes` | Per-device app crash summary and app-level crash list when available |
| `diagnostic_evidence.policy_and_configuration_issues` | Failed/noncompliant policy or setting rows |
| `diagnostic_evidence.recent_restart_shutdown_events` | Intune-initiated restart/shutdown actions |
| `diagnostic_evidence.device_timeline_events` | Timeline-style Intune action/troubleshooting/audit context |
| `diagnostic_evidence.security_issues` | Risky Windows protection fields only |
| `diagnostic_evidence.windows_update_issues` | Windows update records needing attention |
| `diagnostic_evidence.management_failures` | Failed Intune management actions or run states reported in the collector JSON |
| `diagnostic_evidence.identity_issues` | Entra device identity issues |

## Analysis workflow

1. **Identify the target**
   - Device name
   - Managed device id
   - OS and model
   - Last sync time
   - Management/compliance state

2. **Read the collector assessment but verify it**
   - Treat `assessment.top_concerns` as a hint, not the final answer.
   - Confirm every conclusion from `diagnostic_evidence`.

3. **Analyze performance**
   - Start with `diagnostic_evidence.performance.startup`.
   - Then check `resource`.
   - Then check `app_reliability`.

4. **Analyze health and security posture**
   - Check encryption/BitLocker: `device_health.isEncrypted` and policy issues.
   - Check free disk percentage.
   - Check malware counts.
   - Check management certificate expiration.

5. **Analyze app issues**
   - App crash summary first.
   - App-level crash list second.
   - Installed apps only as correlation context; do not treat app presence as a fault.
   - If a known bad version is installed, call it a hypothesis unless crash/update evidence supports it.

6. **Analyze restarts and timeline**
   - `recent_restart_shutdown_events` contains Intune-initiated restart/shutdown actions only.
   - `device_timeline_events` gives management context.
   - If the user asks about OS crashes or unexpected shutdowns, say OS-level crash/shutdown evidence is not present in the collector JSON.

7. **Produce prioritized conclusions**
   - Confirmed issues first.
   - Likely bottlenecks second.
   - Healthy areas third.
   - Missing data last.

8. **Produce mandatory user actions**
   - Always include a final action plan based on what emerged from the data analysis.
   - Actions must be for the user/admin to perform manually. Do not execute, trigger, or offer to execute remediation from the agent.
   - Prioritize by severity, user impact, and confidence.
   - For each action, include the evidence or finding it addresses and the intended outcome.
   - Label actions as `Confirmed`, `Likely`, or `Investigative` to match the evidence strength.

## Performance interpretation rules

### Startup

Use these heuristics:

| Signal | Interpretation |
| --- | --- |
| `startupPerformanceScore < 50` | Startup needs attention |
| `bootScore < 50` | Boot phase likely degraded |
| `loginScore < 50` | Sign-in/profile/GPO/logon phase likely degraded |
| `coreBootTimeInMs > 120000` | Very slow core boot |
| `groupPolicyBootTimeInMs > 10000` | GPO processing may be material |
| `blueScreenCount > 0` | Investigate stability/crash path |
| `restartCount` high with recent restart events | Investigate restart loop or forced reboot pattern |

Be careful: Endpoint Analytics fields may use `0` when a phase is not measured. Say "poor or not measured" when needed.

### Resource

Use these heuristics:

| Signal | Interpretation |
| --- | --- |
| `deviceResourcePerformanceScore >= 80` | Resource health generally good |
| `cpuSpikeTimeScore >= 80` and `cpuSpikeTimePercentage` low | CPU not the primary bottleneck |
| `ramSpikeTimeScore >= 80` and `ramSpikeTimePercentage` low | RAM not the primary bottleneck |
| `freeStoragePercent < 10` | Storage pressure likely |
| `freeStoragePercent >= 20` | Disk capacity is unlikely to be the bottleneck |

### App reliability

Use these heuristics:

| Signal | Interpretation |
| --- | --- |
| `deviceAppHealthScore >= 80` | App reliability healthy |
| `appCrashCount > 0` or `appHangCount > 0` | App reliability issue present |
| `crashing_applications` non-empty | Name the apps and prioritize by crash/hang count |
| `crashing_applications` empty | Do not claim app crash root cause |

## Health check interpretation rules

### Encryption and compliance

Treat these as high priority:

- `device_health.isEncrypted == false`
- BitLocker policy/setting noncompliant
- health attestation security fields unhealthy

Recommended language:

> "Encryption is a confirmed issue because Intune reports `isEncrypted=false` and the BitLocker policy setting is noncompliant."

### Malware and Defender

- `windowsActiveMalwareCount > 0`: high severity.
- `windowsRemediatedMalwareCount > 0`: mention as historical context.
- Defender disabled or real-time protection disabled in Intune/Graph evidence: high severity.

### Management state

- `managementState == managed` and recent `lastSyncDateTime`: management channel appears active.
- Stale sync: consider all other Intune data potentially stale.
- Failed Intune management run states: correlate with device sync freshness and management state from the collector JSON.

## Output format

Use user-friendly Markdown with clear spacing, compact tables, prioritized lists, and visual glyphs/icons. Use this exact structure:

```markdown
## 📌 Executive summary
[2-4 sentences. State the most important conclusion first.]

| Area | Status | Key evidence | User impact |
| --- | --- | --- | --- |
| [Performance/health/security/etc.] | [🔴/🟠/🟡/🔵/✅ status] | [Exact field/value] | [Plain-language impact] |

## ⚡ Performance analysis
[Startup, resource, app reliability. Include evidence values.]

## 🩺 Health check
[Encryption/compliance, malware/security, management state, storage, app health.]

## 🚧 Bottlenecks and likely root causes
[Prioritized list. Separate confirmed from suspected.]

## 🛠️ Recommended user actions
[Mandatory. Prioritized manual actions for the user/admin only. Do not describe actions as executed by the agent. For each action, include priority glyph, evidence/finding addressed, manual action, and intended outcome.]

## 🔎 Missing data that would improve confidence
[Only list data that would materially change the diagnosis.]
```

## Visual formatting rules

- Use severity glyphs consistently: 🔴 Critical, 🟠 High, 🟡 Medium, 🔵 Low, ✅ Healthy/OK, ⚪ Informational.
- Use short paragraphs; avoid dense prose.
- Prefer Markdown tables for status summaries and evidence comparisons.
- Use numbered lists for action plans.
- For every recommended user action, include:
  - priority/severity glyph
  - action confidence: `Confirmed`, `Likely`, or `Investigative`
  - exact evidence or issue addressed
  - manual action for the user/admin
  - intended outcome
- Do not overuse icons. Use them to make the analysis easier to scan.

## How to phrase uncertainty

Use:

- "Confirmed by report" when a field directly supports it.
- "Likely" when multiple signals point to it but root cause is not explicit.
- "Not indicated" when relevant counters are zero or health scores are good.
- "Missing" when the report lacks necessary evidence.

Avoid:

- Claiming OS-level Event Log facts from Intune/Graph-only collector data.
- Calling installed applications "problematic" without crash, update, or performance evidence.
- Treating stale or missing optional data as healthy.

## Examples

### Example: startup degraded, resources healthy

Evidence:

```json
{
  "startupPerformanceScore": 13.28,
  "bootScore": 26,
  "deviceResourcePerformanceScore": 94,
  "cpuSpikeTimeScore": 100,
  "ramSpikeTimeScore": 100
}
```

Conclusion:

> Startup is the primary performance bottleneck. CPU and RAM are not indicated as root causes because resource score and spike scores are healthy.

### Example: BitLocker issue

Evidence:

```json
{
  "isEncrypted": false,
  "setting": "Windows10CompliancePolicy.BitLockerEnabled",
  "state": "nonCompliant"
}
```

Conclusion:

> Encryption is a confirmed health issue. Remediate BitLocker policy/readiness before treating this as a generic compliance false positive.

### Example: no app crash issue

Evidence:

```json
{
  "appCrashCount": 0,
  "appHangCount": 0,
  "crashing_applications": []
}
```

Conclusion:

> App crashes are not indicated by the available Endpoint Analytics data.
