# Security

Security controls are central to FarSight's design. The current implementation is early; production use requires completed identity enforcement, policy review, certificate lifecycle management, and retention approval.

## Threat model

Primary risks are arbitrary code execution, data over-collection, privilege misuse, artifact exposure, and forged collector or agent identities.

## Identity and RBAC

- Collectors authenticate with mTLS.
- Cloud services use managed identity.
- Operators receive least-privilege RBAC.
- Agent tools are scoped to approved modules and device targets.

## mTLS

Collector certificates bind device identity to check-in and result submission. Expired, revoked, or mismatched certificates must fail closed.

## Approvals

Policy can require approval based on module risk, scope, artifact size, target sensitivity, and execution window.

## Artifact protection

Artifacts must be size-limited, redacted, encrypted at rest, access-controlled, and retained only as long as policy allows.

## Audit trail and retention

Audit job requests, policy outcomes, approvals, collector dispatch, result receipt, artifact access, and administrative changes.

## Known gaps

- Add STRIDE table and retention schedule after security review.
