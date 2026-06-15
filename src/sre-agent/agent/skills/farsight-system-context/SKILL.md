# Skill: FarSight System Context

## When to use this skill

Use this skill to reason about **what FarSight should do** before deciding **which tool call to execute**.

Use it for:

- selecting the right module family for a symptom;
- understanding module purpose and scope;
- deciding whether to stay in Intune evidence path or move to FarSight diagnostics;
- applying policy/approval boundaries before orchestration.

## FarSight module catalog (current)

Built-in module IDs:

- `Get-AppLogBundle`: bounded application log bundle collection
- `Get-AppEventSlice`: bounded Windows event-log slice
- `Get-AppHealthSnapshot`: app-scoped service/process/config health snapshot
- `Test-AppConnectivity`: bounded connectivity checks
- `Get-ConfigEvidence`: bounded config evidence
- `Get-ServiceStatusSnapshot`: bounded Windows service status snapshot

Extension sample module:

- `Get-AppDiskEvidence`: sample extension path; tool wrappers may allow it but active policy can deny it by default.

## Policy and governance model

- FarSight execution is deny-by-default via active `farsight-tool-policy`.
- Tool contracts and policy both must allow a request.
- Approval is mandatory for `sensitive-diagnostic` risk paths.
- Use metadata-first artifact handling (`retrieve_artifact_metadata`) before any broader artifact action.

## Evidence boundary guidance

- Use `intune-data-analysis` for Intune/Graph-native evidence and timeline interpretation.
- Use FarSight when you need governed endpoint diagnostics through named modules.
- Combine both only when correlation requires it.

## Outputs from this skill

Produce:

1. recommended `task_type` candidate(s),
2. evidence scope and risk level recommendation (`read-only` vs approval-gated),
3. required guardrails (time bounds, artifact bounds, redaction expectations),
4. prerequisites for orchestration (device identity, correlation id, approval state).
