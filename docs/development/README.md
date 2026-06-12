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

## Testing

Add unit, integration, schema, and policy tests for any new behavior. Extension modules require validation, redaction, timeout, and failure-path coverage.

## CI/CD

CI should validate Markdown links, schema consistency, OpenAPI compatibility, policy examples, and test suites where practical.

## Release process

Document module manifest changes, schema changes, rollout ring, approval requirements, rollback steps, and operational queries.

## Known gaps

- Add finalized service-specific lint/test guidance once project scripts and dependency installation flows are stable.
