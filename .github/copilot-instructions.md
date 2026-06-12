# Agent-Azure-FarSight repository instructions

## Documentation synchronization rule

Every system change must update the related Markdown documentation under `docs/` in the same change set.

When changing code, infrastructure, configuration, policies, samples, deployment behavior, security controls, or operational workflows:

1. Identify the corresponding documentation page under `docs/`.
2. Update that page to reflect the new behavior, assumptions, configuration, validation steps, and known gaps.
3. If no suitable page exists, create one under the closest `docs/` section and link it from `docs/README.md`.
4. Keep diagrams in Mermaid Markdown when architecture or flow changes.
5. Do not leave behavior documented only in implementation code, comments, or planning files.

This rule applies to all future agent and human changes in this repository.
