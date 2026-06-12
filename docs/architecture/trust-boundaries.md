# Trust boundaries

## Boundaries

- **Agent to API:** authenticated and policy-gated; no arbitrary PowerShell or shell text crosses this boundary.
- **API to collector:** collector receives signed or authenticated module job definitions only.
- **Collector to module:** module execution is allowlisted by manifest, schema, timeout, and path/profile controls.
- **Evidence store:** redacted output and approved artifacts only.

## Controls

- mTLS for collector identity.
- Managed identity for cloud components.
- RBAC for operators and service principals.
- Audit logs for job creation, approval, dispatch, completion, and artifact access.

## Known gaps

- Add final RBAC role IDs and certificate lifecycle details.
