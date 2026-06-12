# Security

Security controls are central to FarSight's design. The current implementation is early; production use requires completed identity enforcement, policy review, certificate lifecycle management, and retention approval.

## Threat model

Primary risks are arbitrary code execution, data over-collection, privilege misuse, artifact exposure, and forged collector or agent identities.

## Identity and RBAC

- Collectors authenticate with mTLS.
- Cloud services use managed identity.
- Operators receive least-privilege RBAC.
- Agent tools are scoped to approved modules and device targets.
- Admin web authentication is enforced with Container Apps Easy Auth and Microsoft Entra ID. The BFF consumes Easy Auth principal headers and should require FarSight Admin group membership for write operations.

## mTLS

Collector certificates bind device identity to check-in and result submission. Expired, revoked, or mismatched certificates must fail closed.

## Approvals

Policy can require approval based on module risk, scope, artifact size, target sensitivity, and execution window.

The FarSight tool gateway uses Microsoft Agent Governance Toolkit to evaluate tool-call policy before a FarSight API request is made. This complements Azure RBAC: RBAC limits what the gateway identity can reach, while AGT decides whether a specific tool action is allowed, denied, or approval-gated.

Policies are versioned documents in the Cosmos DB-backed policy repository. Admins edit AGT YAML through the admin web editor, validate it, save a draft, and activate a validated version. Gateway instances load the active version from the API and fail closed if policy retrieval or AGT evaluation fails.

## Artifact protection

Artifacts must be size-limited, redacted, encrypted at rest, access-controlled, and retained only as long as policy allows.

## Audit trail and retention

Audit job requests, policy outcomes, approvals, collector dispatch, result receipt, artifact access, and administrative changes.

## Known gaps

- Add STRIDE table and retention schedule after security review.
