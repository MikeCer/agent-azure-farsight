# FarSight Admin Web Skeleton

React + TypeScript frontend assets live under `frontend/`. The lightweight FastAPI BFF in `bff/` serves the built SPA and exposes endpoints for Container Apps Easy Auth user context, policy repository operations, and admin monitoring views.

## Console shell

The admin app is a multi-feature console. The current navigation includes:

- Overview;
- Policy repository;
- Tool-call monitoring;
- Diagnostic jobs;
- Devices;
- Approvals;
- Configuration;
- Audit.

Only Policy repository and the initial Tool-call monitoring read-only surface are implemented now. Other menu entries are placeholders for planned feature areas.

The shell supports light and dark themes. The toggle is displayed in the page header, follows the user's system preference on first load, and stores the selected theme in browser local storage.

The layout is intentionally wide for code-editing workflows and uses icon-led navigation so administrators can distinguish feature areas quickly. The overview page gives directional context instead of duplicating the full feature menu.

## Authentication

Production uses Container Apps Easy Auth with Microsoft Entra ID. The app registration is created or updated by manually running `scripts/provision-admin-app-registration.py` after the admin URL or custom domain is known; the script is not wired as an AZD hook. Store the resulting `FARSIGHT_ADMIN_AUTH_*` values, including `FARSIGHT_ADMIN_AUTH_ENCRYPTION_SECRET`, in the AZD environment, enable Easy Auth, and reprovision so Bicep can apply the Container Apps auth configuration.

The BFF reads Easy Auth headers such as `x-ms-client-principal`, `x-ms-client-principal-id`, and `x-ms-client-principal-name`. Policy write calls forward the authenticated principal ID to the control API as `X-FarSight-Admin-Actor`.

Set `FARSIGHT_ADMIN_GROUP_OBJECT_IDS` on the admin app to enforce group membership in the BFF. Local development can use `FARSIGHT_ADMIN_ALLOW_LOCAL_FALLBACK=true`; do not enable this in production.

## Policy repository editor

The admin UI includes a Monaco-based AGT YAML editor for policies stored in the FarSight policy repository. The BFF proxies these operations to the control API:

- list policies;
- retrieve active or versioned policy documents;
- validate AGT YAML;
- save a draft;
- activate a validated version.
- delete non-active policy versions.

The control API persists policies to Cosmos DB when `FARSIGHT_COSMOS_ENDPOINT` is configured. Local development uses an in-memory seeded repository.

In Azure, Bicep sets `FARSIGHT_CONTROL_API_BASE_URL` on the admin BFF so policy operations proxy to the deployed API app instead of localhost. The API seeds the default `farsight-tool-policy` document into Cosmos DB on first use when no seed version exists, and repairs seed-created fallback content when the bundled canonical policy changes.

The policy repository can store multiple policy IDs and versions. The AGT gateway uses the configured active policy ID, defaulting to `farsight-tool-policy`; additional policy IDs are stored for future gateway/environment/scope separation until a gateway is configured to load them.

Policy write endpoints currently require `FARSIGHT_ENABLE_POLICY_ADMIN_WRITES=true` on the control API. Bicep enables this temporary gate for the current admin editor flow, but production must replace it with Entra-authenticated FarSight Admin role checks before enabling policy writes broadly.

Active policy versions cannot be deleted from the UI or API. Activate another valid version first, then delete the archived or draft version.

Production gaps still to complete:

- audit propagation for save/activate actions.

## Tool-call monitoring

The Tool-call monitoring page reads `GET /api/bff/telemetry/tool-calls/summary`, which proxies to `GET /api/v1/telemetry/tool-calls/summary` on the control API.

The current API returns a stable empty summary until AGT/tool gateway audit events are written to Log Analytics, Application Insights, or Cosmos DB. The UI intentionally shows an empty state rather than sample data.
