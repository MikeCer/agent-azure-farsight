---
name: FarSight collector module development
description: Use this skill whenever a user asks to create, update, review, or wire a FarSight collector module under src/modules, including PowerShell module code, input.schema.json, manifest.fragment.json, app profiles, Pester tests, AGT policy rules, SRE agent tool wrappers, collector packaging, or module documentation. This skill is strongly recommended for any task mentioning FarSight collector modules, diagnostic modules, endpoint module manifests, module risk tiers, module artifacts, or adding a new Windows diagnostic capability.
---

# FarSight collector module development

Use this skill to build FarSight collector modules that are safe for enterprise Windows endpoints and compatible with the Agent-Azure-FarSight control plane.

FarSight modules are the only executable diagnostic surface on endpoints. Treat each module as a tightly scoped evidence collector, not a general-purpose automation hook.

## Start here

1. Read the user's requested diagnostic capability and restate the evidence question in one sentence.
2. Inspect the closest existing module under `src/modules/`.
3. Read the relevant reference file:
   - `references/module-contract.md` for required files, script parameters, result envelopes, artifacts, and findings.
   - `references/implementation-checklist.md` for implementation and validation steps.
   - `references/policy-and-agent-tooling.md` when the module must be callable through the SRE agent or AGT gateway.
4. Implement the smallest safe module that answers the evidence question.
5. Update documentation under `docs/` in the same change set.

## Safety model

Design modules around bounded evidence, not remote control.

- Do not accept arbitrary PowerShell, shell commands, script blocks, encoded commands, or command fragments.
- Do not accept arbitrary filesystem paths unless they are resolved through an approved profile/root model and canonicalized before use.
- Prefer enums, approved profiles, bounded arrays, booleans, and capped integers.
- Keep all operations read-only.
- Avoid collecting secrets, private keys, raw tokens, credential stores, browser data, user documents, or unrelated system-wide dumps.
- Redact sensitive values before creating artifacts.
- Emit summaries first; artifacts should be optional, bounded, and explicitly useful.
- Return a structured failure envelope instead of throwing unhandled exceptions to the collector.

## Required module layout

Create or update:

```text
src/modules/<ModuleName>/
  <ModuleName>.ps1
  input.schema.json
  manifest.fragment.json
  README.md
  tests/<ModuleName>.Tests.ps1
```

Use optional profile files when user input selects from approved local paths or application scopes:

```text
src/modules/<ModuleName>/
  app-profiles.sample.json
```

## Standard workflow

1. **Define the module contract**
   - Name the module with a verb-noun PowerShell-style name.
   - Define the diagnostic question.
   - Identify risk tier, timeout, artifact cap, and expected findings.
   - Decide whether artifacts are required.

2. **Create `input.schema.json`**
   - Use draft 2020-12 JSON Schema.
   - Use `additionalProperties: false`.
   - Bound all strings, arrays, integers, and time windows.
   - Prefer allowlisted `enum` values or app/profile IDs.

3. **Create `manifest.fragment.json`**
   - Include `name`, `version`, `riskLevel`, `scriptPath`, `sha256`, `timeoutSeconds`, `maxArtifactBytes`, `allowedPathProfiles`, and `schemaRef`.
   - Keep `sha256` as `sha256-placeholder` unless release automation is computing it.

4. **Implement PowerShell**
   - Support Windows PowerShell 5.1.
   - Use the standard parameters: `JobId`, `DeviceId`, `CorrelationId`, `ParametersJson`, `OutputRoot`.
   - Use `Set-StrictMode -Version 2.0` and `$ErrorActionPreference = 'Stop'`.
   - Use `-LiteralPath` for filesystem access.
   - Resolve paths and reject unsafe roots before reading files.
   - Create artifacts under `$OutputRoot/<ModuleName>/`.
   - Include artifact metadata with `localPath` so `collector.ps1` can upload it.

5. **Wire policy and SRE tooling when needed**
   - Update `src/api/app/policies/farsight-tool-policy.yaml`.
   - Update SRE PythonFunctionTool allowlists under `src/sre-agent/agent/tools/` when the module is callable by the agent.
   - Add deny rules before allow rules for dangerous scope.
   - Add require-approval rules for broad, sensitive, or high-volume collection.

6. **Update docs**
   - Update `docs/modules/README.md`.
   - Update module README.
   - Update `docs/extension-guide/` or `docs/evolution/` when behavior or future guidance changes.
   - Update operations/security docs if collection sensitivity, artifacts, or approvals change.

7. **Validate**
   - Parse PowerShell with `pwsh` when available.
   - Run relevant Pester tests if the repo already supports them.
   - Run Python/build checks only for surfaces you changed.
   - Check the Intune package builder still discovers the module from `src/modules/`.

## Good examples in this repository

- `src/modules/Get-AppLogBundle/` - app-profile-based log collection with bounded ZIP artifacts.
- `src/modules/Get-ServiceStatusSnapshot/` - simple bounded module result and JSON artifact pattern.
- `docs/evolution/plans/get-applogbundle-plan.md` - full module development plan for app-log collection.

## Before finishing

Confirm these are true:

- The module answers a specific diagnostic question.
- Inputs are bounded and do not expose a remote-shell or arbitrary-path pattern.
- The module folder has script, schema, manifest, README, and tests.
- Artifacts include `localPath`, `sha256`, and `sizeBytes`.
- AGT policy and SRE tool allowlists are updated if the module is callable.
- Documentation is updated.
- Validation commands were run or the reason they could not be run is clear.

