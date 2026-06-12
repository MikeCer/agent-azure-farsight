#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is unavailable; skipping Python placeholder."
  exit 0
fi

python_files="$(find . -path ./.git -prune -o -name '*.py' -print)"
if [[ -z "$python_files" ]]; then
  echo "No Python files yet. Planned checks: API/tool linting, unit tests, contract tests, and schema validation."
  exit 0
fi

python3 -m compileall -q .

if command -v pytest >/dev/null 2>&1; then
  pytest -q
else
  echo "pytest is unavailable; compile check completed and unit tests are deferred until dependencies are defined."
fi
