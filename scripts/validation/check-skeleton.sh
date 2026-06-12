#!/usr/bin/env bash
set -euo pipefail

required_paths=(
  ".github/workflows/validation.yml"
  "tests/README.md"
  "tests/contract/README.md"
  "tests/e2e/README.md"
  "tests/load/README.md"
  "tests/security/README.md"
  "tests/device-simulator/README.md"
  "scripts/validation/check-skeleton.sh"
  "scripts/validation/validate-bicep.sh"
  "scripts/validation/validate-python.sh"
  "scripts/validation/validate-markdown.sh"
  "scripts/validation/validate-mermaid.sh"
  "scripts/validation/validate-extension-samples.sh"
)

missing=0
for path in "${required_paths[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "Missing required skeleton path: $path" >&2
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

echo "FarSight validation skeleton is present."
