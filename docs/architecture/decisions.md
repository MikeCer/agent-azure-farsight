# Decision records

## ADR-001: No arbitrary PowerShell

FarSight extensions must expose typed modules and typed agent tools. Free-form PowerShell, script blocks, command text, or user-provided paths are denied.

## ADR-002: Read-only diagnostic modules first

Initial modules collect evidence only. Remediation modules require a separate threat model, approval model, and rollout plan.

## ADR-003: Schemas are part of the contract

Every module and agent tool requires JSON schema validation, examples, tests, and documentation updates.

## Known gaps

- Convert decisions into numbered ADR files if the project adopts a formal ADR template.
