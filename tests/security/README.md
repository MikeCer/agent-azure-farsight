# Security Tests

Planned scope from the validation strategy:

- Device mTLS validation and certificate-to-device binding.
- Entra ID authorization, RBAC role boundaries, and managed identity access.
- Manifest allowlists, script hashes, schema validation, and path/provider/URL allowlists.
- Oversized artifact rejection and secret/redaction behavior.
- AGT `allow`, `deny`, and `require_approval` policy outcomes.
- Audit record shape and correlation across API, governance, and endpoint actions.

Security tests should avoid real secrets and use synthetic certificates, tokens, and fixtures.
