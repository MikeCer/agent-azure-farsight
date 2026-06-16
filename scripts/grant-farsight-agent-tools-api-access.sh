#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# grant-farsight-agent-tools-api-access.sh
#
# Grants the FarSight API application role to the Agent Tools gateway managed
# identity so AGT -> API machine-to-machine calls can pass API workload auth.
#
# Required inputs:
#   - one of:
#       - AGENT_TOOLS_MI_CLIENT_ID / AGENT_TOOLS_MI_CLIENT_IDS
#       - AGENT_TOOLS_MI_OBJECT_ID / AGENT_TOOLS_MI_OBJECT_IDS
#   - FARSIGHT_API_APP_ID
#
# Optional:
#   - FARSIGHT_API_ROLE_VALUE (default: Farsight.Api.Access)
#
# Example:
#   AGENT_TOOLS_MI_CLIENT_ID="<agt-mi-client-id>" \
#   FARSIGHT_API_APP_ID="<api-app-client-id>" \
#   ./scripts/grant-farsight-agent-tools-api-access.sh
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BASE_GRANT_SCRIPT="${ROOT_DIR}/src/sre-agent/scripts/grant-farsight-api-access.sh"

[[ -x "${BASE_GRANT_SCRIPT}" ]] || {
  echo "[ERROR] Missing or non-executable base script: ${BASE_GRANT_SCRIPT}" >&2
  exit 1
}

MI_CLIENT_ID="${AGENT_TOOLS_MI_CLIENT_ID:-}"
MI_CLIENT_IDS="${AGENT_TOOLS_MI_CLIENT_IDS:-}"
MI_OBJECT_ID="${AGENT_TOOLS_MI_OBJECT_ID:-}"
MI_OBJECT_IDS="${AGENT_TOOLS_MI_OBJECT_IDS:-}"

if [[ -z "${MI_CLIENT_ID}" && -z "${MI_CLIENT_IDS}" && -z "${MI_OBJECT_ID}" && -z "${MI_OBJECT_IDS}" ]]; then
  echo "[ERROR] Provide AGENT_TOOLS_MI_CLIENT_ID(S) or AGENT_TOOLS_MI_OBJECT_ID(S)." >&2
  exit 1
fi

MI_CLIENT_ID="${MI_CLIENT_ID}" \
MI_CLIENT_IDS="${MI_CLIENT_IDS}" \
MI_OBJECT_ID="${MI_OBJECT_ID}" \
MI_OBJECT_IDS="${MI_OBJECT_IDS}" \
FARSIGHT_API_APP_ID="${FARSIGHT_API_APP_ID:-}" \
FARSIGHT_API_ROLE_VALUE="${FARSIGHT_API_ROLE_VALUE:-Farsight.Api.Access}" \
"${BASE_GRANT_SCRIPT}"
