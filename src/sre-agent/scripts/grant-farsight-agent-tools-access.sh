#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# grant-farsight-agent-tools-access.sh
#
# Grants the FarSight Agent Tools app role to managed identity service
# principal(s) so callers (for example Azure SRE Agent managed identity) can
# call protected AGT gateway /tools/* endpoints.
#
# Required inputs:
#   - one of:
#       - MI_CLIENT_ID / MI_CLIENT_IDS   managed identity client ID(s)
#       - MI_OBJECT_ID / MI_OBJECT_IDS   managed identity service principal object ID(s)
#   - FARSIGHT_AGENT_TOOLS_APP_ID        Agent Tools app registration client ID
#
# Optional:
#   - FARSIGHT_AGENT_TOOLS_ROLE_VALUE (default: Farsight.AgentTools.Access)
#
# Example:
#   MI_CLIENT_ID="<sre-mi-client-id>" \
#   FARSIGHT_AGENT_TOOLS_APP_ID="<agent-tools-app-client-id>" \
#   FARSIGHT_AGENT_TOOLS_ROLE_VALUE="Farsight.AgentTools.Access" \
#   ./scripts/grant-farsight-agent-tools-access.sh
###############################################################################

MI_CLIENT_ID="${MI_CLIENT_ID:-}"
MI_CLIENT_IDS="${MI_CLIENT_IDS:-}"
MI_OBJECT_ID="${MI_OBJECT_ID:-}"
MI_OBJECT_IDS="${MI_OBJECT_IDS:-}"
FARSIGHT_AGENT_TOOLS_APP_ID="${FARSIGHT_AGENT_TOOLS_APP_ID:-}"
FARSIGHT_AGENT_TOOLS_ROLE_VALUE="${FARSIGHT_AGENT_TOOLS_ROLE_VALUE:-Farsight.AgentTools.Access}"
GRAPH_RESOURCE="https://graph.microsoft.com/"

log() { echo "[INFO]  $*"; }
err() { echo "[ERROR] $*" >&2; }
die() { err "$*"; exit 1; }

[[ -n "${FARSIGHT_AGENT_TOOLS_APP_ID}" ]] || die "FARSIGHT_AGENT_TOOLS_APP_ID is required."

log "Validating Microsoft Graph token for current Azure CLI session..."
az account get-access-token --resource-type ms-graph --query "expiresOn" --output tsv >/dev/null \
  || die "Cannot get Graph token. Run: az login --tenant <tenant-id> --scope https://graph.microsoft.com/.default"

declare -a MI_SP_OBJECT_IDS=()

append_unique_id() {
  local candidate="$1"
  [[ -n "${candidate}" ]] || return 0
  for existing in "${MI_SP_OBJECT_IDS[@]:-}"; do
    if [[ "${existing}" == "${candidate}" ]]; then
      return 0
    fi
  done
  MI_SP_OBJECT_IDS+=("${candidate}")
}

resolve_client_id() {
  local client_id="$1"
  local sp_object_id
  sp_object_id=$(az ad sp show --id "${client_id}" --query id --output tsv) \
    || die "Managed identity service principal not found for client ID=${client_id}"
  append_unique_id "${sp_object_id}"
}

if [[ -n "${MI_CLIENT_ID}" ]]; then
  resolve_client_id "${MI_CLIENT_ID}"
fi

if [[ -n "${MI_CLIENT_IDS}" ]]; then
  IFS=',' read -r -a ids <<< "${MI_CLIENT_IDS}"
  for id in "${ids[@]}"; do
    id="${id// /}"
    [[ -n "${id}" ]] || continue
    resolve_client_id "${id}"
  done
fi

if [[ -n "${MI_OBJECT_ID}" ]]; then
  append_unique_id "${MI_OBJECT_ID}"
fi

if [[ -n "${MI_OBJECT_IDS}" ]]; then
  IFS=',' read -r -a object_ids <<< "${MI_OBJECT_IDS}"
  for id in "${object_ids[@]}"; do
    id="${id// /}"
    append_unique_id "${id}"
  done
fi

[[ ${#MI_SP_OBJECT_IDS[@]} -gt 0 ]] || die "Provide MI_CLIENT_ID/MI_CLIENT_IDS or MI_OBJECT_ID/MI_OBJECT_IDS."

log "Resolving Agent Tools service principal..."
AGENT_TOOLS_SP_OBJECT_ID=$(az ad sp show --id "${FARSIGHT_AGENT_TOOLS_APP_ID}" --query id --output tsv) \
  || die "Agent Tools service principal not found for FARSIGHT_AGENT_TOOLS_APP_ID=${FARSIGHT_AGENT_TOOLS_APP_ID}"
log "  Agent Tools service principal object ID: ${AGENT_TOOLS_SP_OBJECT_ID}"

log "Resolving Agent Tools app role '${FARSIGHT_AGENT_TOOLS_ROLE_VALUE}'..."
AGENT_TOOLS_ROLE_ID=$(az ad app show \
  --id "${FARSIGHT_AGENT_TOOLS_APP_ID}" \
  --query "appRoles[?value=='${FARSIGHT_AGENT_TOOLS_ROLE_VALUE}' && contains(allowedMemberTypes, 'Application')].id | [0]" \
  --output tsv) \
  || die "Unable to query app roles from Agent Tools app registration."

if [[ -z "${AGENT_TOOLS_ROLE_ID}" || "${AGENT_TOOLS_ROLE_ID}" == "None" ]]; then
  die "Role '${FARSIGHT_AGENT_TOOLS_ROLE_VALUE}' not found as an Application appRole in Agent Tools app registration ${FARSIGHT_AGENT_TOOLS_APP_ID}."
fi
log "  Agent Tools app role ID: ${AGENT_TOOLS_ROLE_ID}"

for MI_SP_OBJECT_ID in "${MI_SP_OBJECT_IDS[@]}"; do
  log "Processing managed identity service principal: ${MI_SP_OBJECT_ID}"
  EXISTING=$(az rest \
    --method GET \
    --resource "${GRAPH_RESOURCE}" \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_SP_OBJECT_ID}/appRoleAssignments" \
    --query "value[?resourceId=='${AGENT_TOOLS_SP_OBJECT_ID}' && appRoleId=='${AGENT_TOOLS_ROLE_ID}'].id | [0]" \
    --output tsv || echo "")

  if [[ -n "${EXISTING}" && "${EXISTING}" != "None" ]]; then
    log "  Assignment already exists."
    continue
  fi

  BODY=$(cat <<EOF
{
  "principalId": "${MI_SP_OBJECT_ID}",
  "resourceId": "${AGENT_TOOLS_SP_OBJECT_ID}",
  "appRoleId": "${AGENT_TOOLS_ROLE_ID}"
}
EOF
)

  log "  Creating app role assignment..."
  az rest \
    --method POST \
    --resource "${GRAPH_RESOURCE}" \
    --url "https://graph.microsoft.com/v1.0/servicePrincipals/${MI_SP_OBJECT_ID}/appRoleAssignments" \
    --headers "Content-Type=application/json" \
    --body "${BODY}" \
    --output none
done

log "Done. Granted '${FARSIGHT_AGENT_TOOLS_ROLE_VALUE}' to ${#MI_SP_OBJECT_IDS[@]} managed identity service principal(s)."
