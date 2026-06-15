#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# grant-farsight-api-access.sh
#
# Grants a FarSight API app role to a managed identity service principal so
# Azure SRE Agent / AGT gateway workload tokens can call protected API routes.
#
# Required inputs:
#   - MI_CLIENT_ID           managed identity client ID (appId)
#   - FARSIGHT_API_APP_ID    FarSight API app registration client ID
#
# Optional:
#   - FARSIGHT_API_ROLE_VALUE (default: Farsight.Api.Access)
#
# Example:
#   MI_CLIENT_ID="<mi-client-id>" \
#   FARSIGHT_API_APP_ID="<api-app-client-id>" \
#   FARSIGHT_API_ROLE_VALUE="Farsight.Api.Access" \
#   ./grant-farsight-api-access.sh
###############################################################################

MI_CLIENT_ID="${MI_CLIENT_ID:-}"
FARSIGHT_API_APP_ID="${FARSIGHT_API_APP_ID:-}"
FARSIGHT_API_ROLE_VALUE="${FARSIGHT_API_ROLE_VALUE:-Farsight.Api.Access}"
GRAPH_RESOURCE="https://graph.microsoft.com/"

log() { echo "[INFO]  $*"; }
err() { echo "[ERROR] $*" >&2; }
die() { err "$*"; exit 1; }

[[ -n "${MI_CLIENT_ID}" ]] || die "MI_CLIENT_ID is required."
[[ -n "${FARSIGHT_API_APP_ID}" ]] || die "FARSIGHT_API_APP_ID is required."

log "Validating Microsoft Graph token for current Azure CLI session..."
az account get-access-token --resource-type ms-graph --query "expiresOn" --output tsv >/dev/null \
  || die "Cannot get Graph token. Run: az login --tenant <tenant-id> --scope https://graph.microsoft.com/.default"

log "Resolving managed identity service principal..."
MI_SP_OBJECT_ID=$(az ad sp show --id "${MI_CLIENT_ID}" --query id --output tsv) \
  || die "Managed identity service principal not found for MI_CLIENT_ID=${MI_CLIENT_ID}"
log "  MI service principal object ID: ${MI_SP_OBJECT_ID}"

log "Resolving FarSight API service principal..."
API_SP_OBJECT_ID=$(az ad sp show --id "${FARSIGHT_API_APP_ID}" --query id --output tsv) \
  || die "FarSight API service principal not found for FARSIGHT_API_APP_ID=${FARSIGHT_API_APP_ID}"
log "  API service principal object ID: ${API_SP_OBJECT_ID}"

log "Resolving FarSight API app role '${FARSIGHT_API_ROLE_VALUE}'..."
API_ROLE_ID=$(az ad app show \
  --id "${FARSIGHT_API_APP_ID}" \
  --query "appRoles[?value=='${FARSIGHT_API_ROLE_VALUE}' && contains(allowedMemberTypes, 'Application')].id | [0]" \
  --output tsv) \
  || die "Unable to query app roles from FarSight API app registration."

if [[ -z "${API_ROLE_ID}" || "${API_ROLE_ID}" == "None" ]]; then
  die "Role '${FARSIGHT_API_ROLE_VALUE}' not found as an Application appRole in API app registration ${FARSIGHT_API_APP_ID}."
fi
log "  API app role ID: ${API_ROLE_ID}"

EXISTING=$(az rest \
  --method GET \
  --resource "${GRAPH_RESOURCE}" \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_SP_OBJECT_ID}/appRoleAssignments" \
  --query "value[?resourceId=='${API_SP_OBJECT_ID}' && appRoleId=='${API_ROLE_ID}'].id | [0]" \
  --output tsv || echo "")

if [[ -n "${EXISTING}" && "${EXISTING}" != "None" ]]; then
  log "Role assignment already exists. Nothing to do."
  exit 0
fi

BODY=$(cat <<EOF
{
  "principalId": "${MI_SP_OBJECT_ID}",
  "resourceId": "${API_SP_OBJECT_ID}",
  "appRoleId": "${API_ROLE_ID}"
}
EOF
)

log "Creating app role assignment..."
az rest \
  --method POST \
  --resource "${GRAPH_RESOURCE}" \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_SP_OBJECT_ID}/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "${BODY}" \
  --output none

log "Done. Granted '${FARSIGHT_API_ROLE_VALUE}' to managed identity SP ${MI_SP_OBJECT_ID}."
