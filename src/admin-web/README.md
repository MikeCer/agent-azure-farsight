# FarSight Admin Web Skeleton

React + TypeScript frontend assets live under `frontend/`. The lightweight FastAPI BFF in `bff/` serves the built SPA and exposes endpoints for Container Apps Easy Auth user context and policy repository operations.

## Authentication

Production uses Container Apps Easy Auth with Microsoft Entra ID. The app registration is created or updated with `scripts/provision-admin-app-registration.py`, then the resulting values are passed into Bicep through AZD environment variables.

The BFF reads Easy Auth headers such as `x-ms-client-principal`, `x-ms-client-principal-id`, and `x-ms-client-principal-name`. Policy write calls forward the authenticated principal ID to the control API as `X-FarSight-Admin-Actor`.

Set `FARSIGHT_ADMIN_GROUP_OBJECT_IDS` on the admin app to enforce group membership in the BFF. Local development can use `FARSIGHT_ADMIN_ALLOW_LOCAL_FALLBACK=true`; do not enable this in production.

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

- audit propagation for save/activate actions.
