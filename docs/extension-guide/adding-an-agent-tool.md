# Adding an agent tool

This walkthrough uses `samples/extensions/agent-tool/create_app_disk_evidence_job.py`.

## 1. Start from a typed tool contract

Define a narrow `tool-contract.json` with target selector, approved profile, sample controls, and business justification. The tool must not accept module IDs, PowerShell text, shell commands, or arbitrary paths from the user.

## 2. Evaluate AGT policy first

Load policy and evaluate:

- actor and role.
- target scope and sensitivity.
- module risk tier.
- requested profile and sample count.
- approval context.

If the outcome is `deny`, stop. If the outcome is `require_approval`, stop until an approved workflow result is present.

## 3. Map to FarSight API

Create a `POST /api/v1/jobs` body with:

- `moduleId`: `Get-AppDiskEvidence`.
- `target`: approved selector.
- `parameters`: schema-valid module input.
- `justification`.
- `requestedBy`.

Use managed identity in production. The sample uses environment variables as placeholders for local demonstration only.

## 4. Return safe output

Return job ID, status, policy outcome, and next-step guidance. Do not dump raw evidence into agent chat unless the retrieval path has its own authorization and redaction controls.

## 5. Update tests and docs

Add tests for allow, deny, require-approval, API mapping, idempotency, and error handling. Update `docs/agent-tools/`, `docs/modules/`, and operational KQL notes.

## Approval triggers

Require approval for broad groups, sensitive device tags, high sample counts, off-hours execution, or modules above low risk.
