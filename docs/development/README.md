# Development

FarSight development is currently skeleton-first: validation scripts are guarded, several services run locally, and production-grade persistence, identity, and deployment assets are still being filled in.

## Local setup

Use repository-provided build, test, and lint commands. Do not introduce new tooling unless the project adopts it.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/api/requirements.txt
uvicorn app.main:app --app-dir src/api --reload --port 8000
```

```bash
cd src/admin-web/frontend
npm install
npm run dev
```

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

## Validation commands

```bash
bash scripts/validation/check-skeleton.sh
bash scripts/validation/validate-python.sh
bash scripts/validation/validate-markdown.sh
bash scripts/validation/validate-mermaid.sh
bash scripts/validation/validate-bicep.sh
bash scripts/validation/validate-extension-samples.sh
```

## Known gaps

- Add finalized service-specific lint/test commands once project scripts and dependency installation flows are stable.
