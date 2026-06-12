#!/usr/bin/env bash
set -euo pipefail

sample_root="samples/extensions"
if [[ ! -d "$sample_root" ]]; then
  echo "No $sample_root directory yet; skipping extension sample validation."
  echo "Planned checks: collector module schema/examples, Pester tests, agent tool contract, and AGT policy outcomes."
  exit 0
fi

expected=(
  "$sample_root/collector-module"
  "$sample_root/agent-tool"
  "$sample_root/policies"
)

missing=0
for path in "${expected[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "Extension sample path not yet present: $path"
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  echo "Extension samples are incomplete; retaining placeholder status for early skeleton stage."
  exit 0
fi

echo "Extension sample structure is present. Detailed validation will be added with sample implementation."
