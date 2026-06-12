# Adding a diagnostic module

This walkthrough uses the sample `Get-AppDiskEvidence` module in `samples/extensions/collector-module/`.

## 1. Define the safe diagnostic purpose

Write down the evidence question the module answers. The sample answers: "How much disk evidence is visible for an approved application profile?"

Do not build generic command runners. Do not pass arbitrary PowerShell, command text, script blocks, wildcards, registry paths, or filesystem paths from the agent to the collector.

## 2. Create a bounded schema

Use `input.schema.json` to constrain every input:

- `profile` is an enum such as `contoso-app` or `winget-cache`.
- `includeFileSamples` is a boolean.
- `maxFileSamples` has a small maximum.

All path choices are resolved inside module code from an allowlist. User input never becomes a path.

## 3. Add a manifest entry

Add or update `manifest.fragment.json` with:

- module ID and version.
- risk tier.
- timeout.
- max artifact size.
- script hash placeholder or final hash from the release pipeline.
- schema reference.

Collectors must reject modules missing manifest metadata or failing hash validation.

## 4. Implement read-only PowerShell

The sample only calls read-only commands such as `Get-ChildItem` and never mutates local state. Return a result envelope with summary, findings, redactions, and optional artifact metadata.

## 5. Test required behavior

Add Pester coverage for:

- valid and invalid schema input.
- denied profiles and arbitrary paths.
- redaction of user-specific paths and names.
- timeout behavior.
- graceful failure envelopes.

The sample includes a test README placeholder describing the required cases.

## 6. Wire policy and rollout

Update the AGT policy under `samples/extensions/policies/` and require approval for broad targets, high sample counts, or sensitive devices.

## 7. Update docs and operations

Update the module catalog, extension guide, agent tool docs, KQL queries, and rollout notes before enabling the module in any ring.

## Checklist

- [ ] Schema created and reviewed.
- [ ] Manifest created with hash, timeout, risk tier, and artifact limit.
- [ ] Module code is read-only and allowlisted.
- [ ] Tests cover validation, redaction, timeout, and failure.
- [ ] AGT policy defines allow, deny, and require-approval outcomes.
- [ ] Matching agent tool contract maps to `POST /api/v1/jobs`.
- [ ] Docs, KQL, and rollout approval are updated.
