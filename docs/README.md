# Agent-Azure-FarSight documentation

This directory is the user-facing documentation set for FarSight. It explains the current skeleton, intended architecture, operational model, and extension rules without requiring access to internal planning artifacts.

## Learning path

1. [Architecture](architecture/README.md) - system components, deployment topology, data flows, trust boundaries, and decision records.
2. [Greenfield Azure deployment](deployment/azure-greenfield-deployment.md) - step-by-step private networking, DNS, AZD, SRE Agent, and Intune rollout guide.
3. [Security](security/README.md) - threat model, identity, approvals, artifact protection, audit, and retention controls.
4. [Collector](collector/README.md) - endpoint layout, scheduled task model, configuration, local state, and troubleshooting.
5. [Intune](intune/README.md) - Intune deployment/compliance entrypoint and links to the canonical collector runbook.
6. [API](api/README.md) - REST contracts, authentication, idempotency, errors, and versioning.
7. [Agent tools](agent-tools/README.md) - Azure SRE Agent integration through governed AGT tools and approval behavior.
8. [Modules](modules/README.md) - diagnostic module catalog, schema rules, result envelopes, and redaction expectations.
9. [Operations](operations/README.md) - dashboards, alerts, KQL examples, runbooks, backup/restore, and incident response.
10. [Development](development/README.md) - local setup, [Azure lab setup](development/setup-lab.md), coding standards, testing, CI/CD, and release notes.
11. [Extension guide](extension-guide/README.md) - walkthroughs for adding safe modules and matching agent tools.
12. [Evolution](evolution/README.md) - future collector module ideas and product evolution notes.

## Start here by role

- **SRE operator:** Read [Architecture](architecture/README.md), [Agent tools](agent-tools/README.md), and [Operations](operations/README.md).
- **Endpoint/Intune engineer:** Read [Collector](collector/README.md), [Intune](intune/README.md), and [Security](security/README.md).
- **API or platform engineer:** Read [API](api/README.md), [Architecture](architecture/README.md), and [Development](development/README.md).
- **Extension author:** Read [Modules](modules/README.md) and [Extension guide](extension-guide/README.md) before writing code.
- **Security reviewer:** Read [Security](security/README.md), [Trust boundaries](architecture/trust-boundaries.md), and [Decision records](architecture/decisions.md).

## Current implementation notes

FarSight is in early implementation. Some pages describe intended behavior and guardrails before all code and deployment assets are complete. Pages should clearly call out current-state gaps instead of implying finished production behavior.

## Additional assets

- [Architecture diagrams](architecture/architecture-diagrams.md)
- Presentation material: `docs/presentations/`

## Documentation maintenance

- Update the relevant doc with every component change. This is a repository rule: code, infrastructure, policy, sample, deployment, security, and operations changes must include matching Markdown updates under `docs/` in the same change set.
- If a change has no matching documentation page, create one in the closest `docs/` section and link it from this index.
- Prefer Mermaid diagrams in Markdown; keep PowerPoint as presentation material only.
- Use "Current state" or "Known gaps" sections for unfinished behavior.
- Validate Markdown, links, Mermaid, OpenAPI, schemas, and examples in CI when practical.
