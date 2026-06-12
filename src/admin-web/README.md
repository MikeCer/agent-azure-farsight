# FarSight Admin Web Skeleton

React + TypeScript frontend assets live under `frontend/`. The lightweight FastAPI BFF in `bff/` serves the built SPA and exposes endpoints for Entra-authenticated user/config context and policy repository operations.

## Policy repository editor

The admin UI includes a Monaco-based AGT YAML editor for policies stored in the FarSight policy repository. The BFF proxies these operations to the control API:

- list policies;
- retrieve active or versioned policy documents;
- validate AGT YAML;
- save a draft;
- activate a validated version.

The control API persists policies to Cosmos DB when `FARSIGHT_COSMOS_ENDPOINT` is configured. Local development uses an in-memory seeded repository.

Policy write endpoints are fail-closed until `FARSIGHT_ENABLE_POLICY_ADMIN_WRITES=true` is set on the control API. Production must replace this temporary gate with Entra-authenticated FarSight Admin role checks before enabling policy writes.

Production gaps still to complete:

- MSAL or Container Apps auth integration;
- group/role authorization for FarSight Admin;
- audit propagation for save/activate actions.
