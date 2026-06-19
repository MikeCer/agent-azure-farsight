# Extension guide

FarSight extensions add typed collector modules and matching Azure SRE Agent tools without weakening the no-shell model.

## Walkthroughs

- [Adding a diagnostic module](adding-a-diagnostic-module.md)
- [Adding an agent tool](adding-an-agent-tool.md)

Coding agents should use the repository skill at `.github/skills/farsight-collector-module-development/` when creating, updating, or reviewing FarSight collector modules.

## Required checklist

- Schema with bounded and allowlisted inputs.
- Manifest entry with version, risk tier, timeout, artifact limit, script hash, and schema reference.
- Read-only module code.
- Tests for validation, redaction, timeout, and failure handling.
- AGT policy update with `allow`, `deny`, and `require_approval` outcomes.
- Agent tool contract and API mapping.
- Documentation update, KQL update, and rollout approval.

## Safety principles

- Never accept arbitrary PowerShell, script blocks, command strings, or free-form filesystem paths.
- Prefer enums and server-side allowlists.
- Deny by default and require approval for broader scope or higher risk.
