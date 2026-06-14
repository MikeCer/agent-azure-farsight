#!/usr/bin/env sh
set -eu

if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: Azure CLI is required to register resource providers." >&2
  exit 1
fi

if [ -n "${AZURE_SUBSCRIPTION_ID:-}" ]; then
  az account set --subscription "$AZURE_SUBSCRIPTION_ID" 1>/dev/null
fi

providers="
Microsoft.App
Microsoft.ContainerRegistry
Microsoft.OperationalInsights
Microsoft.Insights
Microsoft.ManagedIdentity
Microsoft.Network
Microsoft.Storage
Microsoft.KeyVault
Microsoft.AppConfiguration
Microsoft.ServiceBus
Microsoft.DocumentDB
Microsoft.ApiManagement
"

echo "Checking Azure resource provider registration..."

for namespace in $providers; do
  state="$(az provider show --namespace "$namespace" --query registrationState -o tsv 2>/dev/null || true)"

  if [ "$state" = "Registered" ]; then
    echo "  $namespace: Registered"
    continue
  fi

  if [ -z "$state" ]; then
    echo "  $namespace: unavailable or not visible in this subscription; attempting registration"
  else
    echo "  $namespace: $state; registering"
  fi

  az provider register --namespace "$namespace" --wait 1>/dev/null
  echo "  $namespace: Registered"
done

echo "Azure resource provider registration check completed."
