#!/bin/bash
# PreToolUse hook — blocks edits to Flux-generated files.
# Receives tool input JSON on stdin. Exit 0 = allow, exit 2 = block.

set -euo pipefail

input=$(cat)

file_path=$(echo "$input" | python3 -c "
import json, sys
data = json.load(sys.stdin)
ti = data.get('tool_input', {})
# Edit tool uses 'file_path'; Write tool uses 'file_path'
print(ti.get('file_path', ''))
" 2>/dev/null || true)

[[ -z "$file_path" ]] && exit 0

echo "[protect] checking edit of: $file_path" >&2

if [[ "$file_path" == *"gotk-components.yaml" ]]; then
  echo "[protect] BLOCKED: gotk-components.yaml is Flux-generated — do not edit manually." >&2
  exit 2
fi

echo "[protect] allowed" >&2
exit 0
