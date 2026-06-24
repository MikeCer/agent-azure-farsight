# Development

FarSight development is currently skeleton-first: validation scripts are guarded, several services run locally, and production-grade persistence, identity, and deployment assets are still being filled in.

## Local setup

Use repository-provided build, test, and lint entry points. Do not introduce new tooling unless the project adopts it. Keep local setup instructions in component READMEs instead of duplicating command blocks across docs.

For end-to-end lab validation, follow [Set up a FarSight test lab in Azure](setup-lab.md).

## Coding standards

- Keep module and tool inputs typed and schema-validated.
- Fail closed on validation, policy, identity, and approval errors.
- Avoid arbitrary shell execution and dynamic command construction.
- Redact sensitive data before persistence or upload.
- Keep SRE skill instructions aligned to live tool contracts and naming (`src/sre-agent/intune-collector/` for Intune evidence collection and FarSight tool parameters such as `device_id`, `task_type`, and `job_id`).
- The `intune_diagnostics_tool` returns one complete JSON object as its function result; the `intune-data-analysis` skill must treat that return as the authoritative full dataset. Do not instruct the agent to re-run the tool, read execution log files, import the tool as a module, or pipe it through a shell to "recover" output that only looks truncated in the reasoning preview. Keep the first-pass collection compact (`include_beta_endpoint_analytics: false`, `max_optional_pages: 2`, `include_pii: false`) so the result stays small.
- Preserve the FarSight two-skill boundary: `farsight-system-context` for domain/governance context and `farsight-tool-orchestration` for execution sequencing.
- For `src/sre-agent/agent` deployments, rely on persisted postdeploy logs in `src/sre-agent/agent/.logs/deploy-*.log` when shell/CLI UI clears hook output after completion.

## Testing

Add unit, integration, schema, and policy tests for any new behavior. Extension modules require validation, redaction, timeout, and failure-path coverage.

## CI/CD

CI should validate Markdown links, schema consistency, OpenAPI compatibility, policy examples, and test suites where practical.

## Release process

Document module manifest changes, schema changes, rollout ring, approval requirements, rollback steps, and operational queries.

## Known gaps

- Add finalized service-specific lint/test guidance once project scripts and dependency installation flows are stable.
