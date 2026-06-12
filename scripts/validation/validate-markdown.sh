#!/usr/bin/env bash
set -euo pipefail

markdown_files="$(find . -path ./.git -prune -o -name '*.md' -print)"
if [[ -z "$markdown_files" ]]; then
  echo "No Markdown files found."
  exit 0
fi

echo "$markdown_files" | while IFS= read -r file; do
  [[ -n "$file" ]] || continue
  if [[ ! -s "$file" ]]; then
    echo "Markdown file is empty: $file" >&2
    exit 1
  fi
done

if command -v markdownlint >/dev/null 2>&1; then
  markdownlint $markdown_files
else
  echo "markdownlint is unavailable; performed non-empty Markdown placeholder check."
fi

echo "Future docs checks: link validation, generated OpenAPI/schema consistency, and release documentation gates."
