#!/usr/bin/env bash
set -euo pipefail

mermaid_count="$(grep -R --include='*.md' -n '```mermaid' . 2>/dev/null || true)"
mermaid_count="$(printf '%s\n' "$mermaid_count" | grep -c . || true)"
if [[ "$mermaid_count" == "0" ]]; then
  echo "No Mermaid blocks found; render validation will run when architecture diagrams are added."
  exit 0
fi

if command -v mmdc >/dev/null 2>&1; then
  echo "Mermaid CLI is available; render extraction will be implemented when diagram files are stable."
else
  echo "Found $mermaid_count Mermaid block(s), but mmdc is unavailable. Skipping guarded render placeholder."
fi
