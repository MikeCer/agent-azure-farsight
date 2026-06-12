#!/usr/bin/env bash
set -euo pipefail

main_bicep="infra/bicep/main.bicep"

if [[ ! -f "$main_bicep" ]]; then
  echo "No $main_bicep yet; skipping Bicep build and what-if until infrastructure is added."
  echo "Planned checks: az bicep build, azd package, azd provision --preview, az deployment what-if."
  exit 0
fi

if command -v az >/dev/null 2>&1; then
  az bicep build --file "$main_bicep"
else
  echo "Azure CLI is unavailable; skipping Bicep build."
fi

if [[ "${RUN_AZURE_PREVIEW:-false}" == "true" ]]; then
  if [[ -z "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
    echo "AZURE_SUBSCRIPTION_ID is required for preview checks." >&2
    exit 1
  fi
  echo "Azure what-if preview is intentionally a placeholder until resource group strategy is implemented."
  echo "Future command: az deployment sub what-if --location ${AZURE_COLLECTOR_LOCATION:-italynorth} --template-file $main_bicep"
else
  echo "Azure preview disabled. Set workflow_dispatch run_azure_preview=true after OIDC is configured."
fi
