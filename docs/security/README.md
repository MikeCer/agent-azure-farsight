# Security model

Security controls are central to Agent-Azure-FarSight's design. The solution is built around a layered model: strong identity at every boundary, no arbitrary remote execution, least-privilege Azure access, governed SRE tool actions, private networking for production, and auditable evidence handling.

The current implementation is still early. Production use requires completed identity enforcement, certificate lifecycle management, policy review, audit review, and retention approval.

## Security principles

- **No remote shell:** FarSight must never expose reverse shell, arbitrary PowerShell, arbitrary command, or free-form script execution.
- **Named modules only:** Endpoint execution is limited to allowlisted diagnostic modules with schema-validated parameters.
- **Fail closed:** Missing identity, invalid certificate, unavailable AGT policy, invalid policy, expired approval, or invalid target state must block the action.
- **Least privilege:** Every app, operator, SRE Agent, and Azure resource identity receives only the permissions required for its role.
- **Defense in depth:** Identity, policy, network, data, and audit controls are independent layers; no single layer is assumed sufficient.
- **Operator accountability:** Human and agent actions must be attributable to an Entra identity, managed identity, or device certificate identity.

## Trust boundaries

| Boundary | Primary control | Expected behavior |
| --- | --- | --- |
| Windows collector to FarSight API | Device certificate and mTLS | Only known devices with valid, unexpired, non-revoked certificates can check in, fetch jobs, or submit results. |
| Admin browser to admin web/BFF | Microsoft Entra ID through Container Apps Easy Auth | Operators authenticate with Entra ID and must satisfy FarSight admin group/role checks for write operations. |
| Admin BFF to control API | Managed identity or Entra service token | The BFF forwards the authenticated actor and uses a service identity for API calls. |
| Azure SRE Agent to tool gateway | Managed identity / Entra workload identity | The SRE Agent calls only published FarSight tools through an authenticated service path. |
| Tool gateway to control API | Managed identity plus AGT policy evaluation | Tool calls are evaluated by AGT before any FarSight API request is made. |
| FarSight apps to Azure resources | Managed identities and Azure RBAC | Cosmos DB, Storage, Key Vault, ACR, App Configuration, Service Bus, and monitoring access use least-privilege RBAC where supported. |
| Public network to FarSight apps | Ingress mode, private endpoints, private DNS | Production deployments should use internal Container Apps ingress and private endpoints unless public development access is explicitly approved. |

## Device and collector authentication

Collectors are intended to authenticate to the control API with **mutual TLS (mTLS)**.

Production certificate expectations:

- Certificates are issued through enterprise PKI integrated with Intune SCEP or PKCS profiles.
- Certificates bind the request to a known device identity, such as Entra device ID or another approved stable device identifier.
- The API validates certificate chain, expiry, revocation status, intended usage, tenant binding, and device record mapping.
- Certificate mismatch, unknown device, expired certificate, revoked certificate, or tenant mismatch fails closed.
- Certificate rollover must be handled before expiry, with old certificate retirement and audit records.

Collector requests should also include explicit device metadata, correlation IDs, module manifest version, and collector version. Those values are not substitutes for certificate authentication; they support authorization, audit, and troubleshooting after the mTLS identity is accepted.

The development enrollment API path is only for dev/pilot bootstrap. It should not replace production PKI and should be disabled unless explicitly approved.

## Collector authorization and execution safety

Authenticated devices are authorized only for their own jobs and artifacts.

The collector must enforce local safety before executing anything:

- Fetch at most one leased job for its device.
- Execute only named modules present in the signed or hash-validated module manifest.
- Validate module parameters against the module schema.
- Enforce path allowlists, size limits, timeouts, and redaction policy locally.
- Reject arbitrary script text, shell commands, unsigned modules, unknown module IDs, and unsupported parameters.
- Submit structured result envelopes and bounded artifacts only.

FarSight's cloud API should independently validate the requested device, module ID, job state, lease, result schema, and artifact metadata. Local collector validation is required, but cloud-side validation remains authoritative.

## Admin authentication and authorization

The admin web app uses **Container Apps Easy Auth** with Microsoft Entra ID.

Deployment model:

- The Entra app registration is created or updated manually with `scripts/provision-admin-app-registration.py` after the admin URL or custom domain is known.
- FarSight API app registration and API app role for workload-token enforcement are created or updated manually with `scripts/provision-farsight-api-app-registration.py`.
- Optional dedicated Agent Tools audience registration can be created/updated with `scripts/provision-farsight-agent-tools-app-registration.py` and used for `SRE_AGENT_TOOL_ENDPOINT_SCOPE`.
- The resulting `FARSIGHT_ADMIN_AUTH_*` values are stored in the AZD environment.
- Bicep enables Easy Auth only when the enable flag, client ID, client secret, auth encryption secret, and issuer are all populated.
- The Easy Auth Entra client secret is stored on the admin web Container App as `microsoft-provider-authentication-secret`.
- Container Apps Easy Auth uses a separate `farsight-admin-auth-encryption-secret` value for auth encryption. It must be a base64 string converted from 32 random bytes and is emitted by the app-registration script as `FARSIGHT_ADMIN_AUTH_ENCRYPTION_SECRET`.

Runtime model:

- The BFF consumes Easy Auth headers such as `x-ms-client-principal`, `x-ms-client-principal-id`, and `x-ms-client-principal-name`.
- `FARSIGHT_ADMIN_GROUP_OBJECT_IDS` should be configured so privileged write operations require FarSight admin group membership.
- Policy write operations should propagate the authenticated principal to the control API as the administrative actor.
- During the current authorization phase, BFF-to-API policy mutations are signed with `FARSIGHT_API_INTERNAL_AUTH_SECRET`. The API verifies actor, group, expiry, and HMAC signature before accepting save, activate, or delete.
- Local fallback authentication is for development only and must not be enabled in production.

Production must evolve this into Entra-authenticated service-token validation, FarSight Admin role checks, and durable audited authorization decisions.

## Azure SRE Agent and AGT-governed tools

Azure SRE Agent integration must not bypass FarSight controls. The SRE Agent should interact with FarSight through typed tools exposed by the AGT-governed tool gateway.

The tool gateway security model is:

- Authenticate the SRE Agent or calling workload with managed identity / Entra workload identity.
- FarSight API workload auth validates Entra signature/audience/issuer/tenant and rejects delegated user tokens (`scp`) for machine-only routes.
- Convert each tool call into a structured action context.
- Evaluate the action with Microsoft Agent Governance Toolkit before calling the control API.
- Return `allow`, `deny`, or `require_approval` outcomes.
- Fail closed if AGT is unavailable, policy cannot be loaded, policy is invalid, or the action context is incomplete.
- Load production policies from the API-backed policy repository (`FARSIGHT_POLICY_SOURCE=api`) rather than local files.

AGT complements Azure RBAC. RBAC controls what the tool gateway identity can reach; AGT controls whether a specific action is allowed for a specific device, module, risk level, scope, and approval state.

## Policy repository and approvals

AGT policies are versioned documents in the FarSight policy repository.

Expected controls:

- Admins edit policy YAML through the admin UI.
- Drafts are validated before activation.
- Only validated versions can become active.
- Active policy versions cannot be deleted; administrators must activate a replacement version before deleting archived or draft versions.
- Gateways load the active version and cache it for a short, bounded interval.
- The default `farsight-tool-policy` is seeded from the canonical gateway policy bundle. The repository can store additional policy IDs and versions, but a gateway only evaluates the policy ID it is configured to load.
- Policy changes are audited with actor, timestamp, version, diff metadata, and validation result.
- Higher-risk actions can require secondary approval before job creation.

Approval policy can consider module risk, target device sensitivity, target group size, artifact size, execution window, actor identity, and recent activity. Expired, missing, or mismatched approvals must fail closed.

## Azure resource access

FarSight apps use managed identities for Azure resource access.

Current intended assignments include:

- Container Apps identities receive ACR pull permissions for the provisioned registry.
- API and tool gateway identities receive only the Cosmos DB, Service Bus, Storage, Key Vault, App Configuration, and monitoring permissions they require.
- Admin web/BFF identity receives only permissions needed to call the control API and read public UI configuration.
- SRE Agent package identities receive only the Microsoft Graph, Key Vault, and FarSight permissions required by their tools.

Container Apps that use Azure SDKs set `AZURE_CLIENT_ID` so `DefaultAzureCredential` uses the expected user-assigned managed identity rather than probing unavailable credential sources.

Avoid connection strings and local authentication where managed identity is supported. If a service still requires a secret, store it in Key Vault or Container Apps secrets as appropriate, rotate it, and audit access.

## Network security

FarSight supports two independent network decisions: whether Azure dependencies use private endpoints, and whether FarSight solution endpoints are public or internal-only.

- Public Container Apps ingress for FarSight API, admin web, and tool gateway when clients or administrators must reach the solution over the internet.
- Internal Container Apps ingress for hybrid/private deployments where clients and administrators use VPN, ExpressRoute, peering, private DNS, or another approved private path.
- Private endpoints for Storage, Key Vault, ACR, Cosmos DB, Service Bus, App Configuration, monitoring, and other supported dependencies, regardless of whether solution ingress is public or internal.
- Private DNS zones linked only to VNets that have working private routes to the target private endpoints.
- Approved hub, VPN, ExpressRoute, firewall, or private resolver paths for managed endpoints and operators.
- No public RDP for lab VMs except explicitly approved short-lived break-glass scenarios.

When private endpoints and public ingress are both enabled, the FarSight application endpoints are internet-reachable, but their Azure service dependencies remain private. Public ingress must still be protected by mTLS for collectors, Easy Auth/Entra ID for administrators, AGT policy for SRE actions, and least-privilege managed identities for data-plane access.

Because Container Apps environment internal/public mode is a creation-time network posture, deployments use mode-specific app names. Treat old internal/public app sets as stale only after validating the replacement endpoint and then remove them through an approved cleanup operation. The final topology uses one Container Apps delegated subnet, so mode switches require deleting the old environment and waiting for subnet release before creating the replacement environment.

ACR remote builds are a special deployment-time case. When AZD remote Docker builds are used with a network-restricted registry, ACR uses selected-networks mode with default deny, ACR Tasks/trusted-service bypass, and explicitly configured Azure Container Registry build CIDR ranges. If this exception is not approved, use a private-network runner or local Docker/Podman environment with private DNS reachability to ACR.

## Data and artifact protection

FarSight collects diagnostic evidence, so data minimization is mandatory.

Expected controls:

- Modules collect only the minimum data required for the diagnostic hypothesis.
- Redaction runs before upload where feasible.
- Artifacts are size-limited and retained only for the configured lifecycle.
- Blob artifacts are encrypted at rest and accessed through controlled API flows or short-lived scoped upload/download URLs.
- Cosmos DB job state, policy documents, approvals, and device metadata use TTL where appropriate.
- Log Analytics retention is bounded and reviewed for data classification.
- Sensitive fields, tokens, certificates, private keys, and secrets must never be written to collector logs, API logs, policy documents, or artifacts.

## Audit trail

Audit records should make every diagnostic action explainable.

Audit these events at minimum:

- Device certificate enrollment, renewal, rejection, and revocation.
- Collector check-in, job lease, result submission, and artifact upload.
- Job creation, cancellation, expiry, retry, and approval state changes.
- AGT policy evaluation outcome, including deny and require-approval decisions.
- Admin sign-in context, policy save, policy activation, and privileged write actions.
- SRE Agent/tool gateway calls and mapped FarSight API requests.
- Artifact access and deletion.
- RBAC, identity, and configuration changes that affect security posture.

Audit records should include correlation IDs, actor identity, device identity, job ID, module ID, policy version, decision, timestamp, and reason.

The admin console Tool-call monitoring view is an observability surface over these audit records. It helps administrators understand volume, tool distribution, and AGT decisions, but it is not an authorization layer. Enforcement remains in identity, RBAC, AGT policy evaluation, and approval checks.

## Known implementation gaps

- Add certificate revocation-status validation (CRL/OCSP) and persistent device-record checks to complement current API-side mTLS identity binding.
- Complete Entra/managed-identity authorization for API write paths.
- Replace the current shared-secret BFF-to-API policy mutation signature with Entra service-token validation and FarSight Admin role checks.
- Back tool-call monitoring with real AGT/tool gateway audit events.
- Finalize production certificate issuance, renewal, and revocation runbooks.
- Add STRIDE threat model and approved retention schedule.
- Add alert rules for failed mTLS, repeated policy denials, unusual artifact volume, and privileged policy changes.
- Validate private DNS/routing assumptions for every production VNet before linking private zones.
