#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# grant-intune-permissions.sh
#
# Grants Microsoft Graph application permissions to the SRE Agent's managed
# identity service principal so it can run Intune diagnostics via Graph API.
#
# Prerequisites:
#   - Azure CLI installed and logged in with Global Admin or Privileged Role
#     Administrator rights (needed to grant admin consent for app permissions)
#   - The managed identity must already exist
#
# Usage:
#   chmod +x grant-intune-permissions.sh
#   ./grant-intune-permissions.sh
#
# To use a different identity, override MI_CLIENT_ID:
#   MI_CLIENT_ID="<other-client-id>" ./grant-intune-permissions.sh
###############################################################################

# --- Configuration -----------------------------------------------------------

# User-Assigned Managed Identity Client ID (default: SRE Agent's UA-MI)
MI_CLIENT_ID="${MI_CLIENT_ID:-e1a19129-67e9-4a64-8fad-874add65d455}"

# Microsoft Graph well-known App ID and Service Principal Object ID vary per
# tenant. The App ID is always the same globally:
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"

# Required Graph application permissions for Intune diagnostics
PERMISSIONS=(
  "DeviceManagementManagedDevices.Read.All"
  "DeviceManagementConfiguration.Read.All"
  "DeviceManagementApps.Read.All"
  "DeviceManagementServiceConfig.Read.All"
  "User.Read.All"
  "Directory.Read.All"
)

# --- Helper functions --------------------------------------------------------

log()  { echo "[INFO]  $*"; }
err()  { echo "[ERROR] $*" >&2; }
die()  { err "$*"; exit 1; }

GRAPH_RESOURCE="https://graph.microsoft.com/"

role_guidance() {
  cat <<'EOF'
[HINT] This operation requires Microsoft Graph delegated permissions + an active Entra admin role.
[HINT] Ensure your current session has an active role such as:
[HINT]   - Privileged Role Administrator (recommended for app role assignments), or
[HINT]   - Global Administrator
[HINT] If your roles are eligible via PIM, activate them before running this script.
[HINT] Re-auth with Graph scope in the same shell:
[HINT]   az login --tenant <tenant-id> --scope https://graph.microsoft.com/.default
EOF
}

# --- Resolve Service Principals ----------------------------------------------

log "Resolving managed identity service principal for client ID: ${MI_CLIENT_ID}"
MI_SP_OBJECT_ID=$(az ad sp show \
  --id "${MI_CLIENT_ID}" \
  --query "id" \
  --output tsv) \
  || die "Could not find service principal for client ID '${MI_CLIENT_ID}'. Ensure the managed identity exists."

log "Managed identity SP object ID: ${MI_SP_OBJECT_ID}"

log "Resolving Microsoft Graph service principal in this tenant..."
GRAPH_SP_OBJECT_ID=$(az ad sp show \
  --id "${GRAPH_APP_ID}" \
  --query "id" \
  --output tsv) \
  || die "Could not find Microsoft Graph service principal. This should not happen in any Azure AD tenant."

log "Microsoft Graph SP object ID: ${GRAPH_SP_OBJECT_ID}"

# --- Fetch available Graph app roles -----------------------------------------

log "Fetching Microsoft Graph app role definitions..."
GRAPH_APP_ROLES_JSON=$(az ad sp show \
  --id "${GRAPH_APP_ID}" \
  --query "appRoles" \
  --output json) \
  || die "Failed to fetch Graph app roles."

log "Validating Microsoft Graph token acquisition for this session..."
az account get-access-token --resource-type ms-graph --query "expiresOn" --output tsv >/dev/null \
  || {
    role_guidance
    die "Unable to get a Microsoft Graph access token for the current CLI session."
  }

# --- Grant each permission ---------------------------------------------------

GRANTED=0
SKIPPED=0
FAILED=0

for PERM in "${PERMISSIONS[@]}"; do
  log "Processing permission: ${PERM}"

  # Look up the app role ID for this permission
  APP_ROLE_ID=$(echo "${GRAPH_APP_ROLES_JSON}" | \
    python3 -c "
import sys, json
roles = json.load(sys.stdin)
target = '${PERM}'
for r in roles:
    if r.get('value') == target:
        print(r['id'])
        sys.exit(0)
sys.exit(1)
" 2>/dev/null) || {
    err "Permission '${PERM}' not found in Microsoft Graph app roles. Skipping."
    ((FAILED+=1))
    continue
  }

  log "  App role ID: ${APP_ROLE_ID}"

  # Check if the assignment already exists
  EXISTING=$(az rest \
    --method GET \
    --resource "${GRAPH_RESOURCE}" \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_SP_OBJECT_ID}/appRoleAssignments" \
    --query "value[?appRoleId=='${APP_ROLE_ID}' && resourceId=='${GRAPH_SP_OBJECT_ID}'].id | [0]" \
    --output tsv 2>/dev/null || echo "")

  if [[ -n "${EXISTING}" && "${EXISTING}" != "None" ]]; then
    log "  Already granted. Skipping."
    ((SKIPPED+=1))
    continue
  fi

  # Create the app role assignment
  BODY=$(cat <<EOF
{
  "principalId": "${MI_SP_OBJECT_ID}",
  "resourceId": "${GRAPH_SP_OBJECT_ID}",
  "appRoleId": "${APP_ROLE_ID}"
}
EOF
)

  log "  Granting permission..."
  POST_OUTPUT=$(az rest \
    --method POST \
    --resource "${GRAPH_RESOURCE}" \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_SP_OBJECT_ID}/appRoleAssignments" \
    --headers "Content-Type=application/json" \
    --body "${BODY}" \
    --output json 2>&1) \
    && {
      log "  Granted: ${PERM}"
      ((GRANTED+=1))
    } \
    || {
      err "  Failed to grant '${PERM}'. Graph response:"
      echo "${POST_OUTPUT}" >&2
      role_guidance
      ((FAILED+=1))
    }
done

# --- Summary -----------------------------------------------------------------

echo ""
echo "============================================"
echo " Permission Grant Summary"
echo "============================================"
echo " Target SP:    ${MI_SP_OBJECT_ID} (${MI_CLIENT_ID})"
echo " Granted:      ${GRANTED}"
echo " Already set:  ${SKIPPED}"
echo " Failed:       ${FAILED}"
echo " Total:        ${#PERMISSIONS[@]}"
echo "============================================"
echo ""

if [[ ${FAILED} -gt 0 ]]; then
  err "Some permissions failed. Ensure you are logged in with sufficient Entra privileges."
  exit 1
fi

log "Done. All Intune diagnostic permissions are in place."
