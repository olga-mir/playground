#!/bin/bash
# PreToolUse hook — enforces GitOps rules for the orchestrator's diagnostics agent.
# Receives tool input JSON on stdin. Exit 0 = allow, exit 2 = block (message shown to user).

set -euo pipefail

input=$(cat)

# Extract the bash command being attempted (empty string if not a Bash tool call)
cmd=$(echo "$input" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data.get('tool_input', {}).get('command', ''))
" 2>/dev/null || true)

[[ -z "$cmd" ]] && exit 0

# ── block kubectl write operations ────────────────────────────────────────────
# All cluster changes must go through git → Flux. Read-only kubectl is allowed.
if echo "$cmd" | grep -Eq '\bkubectl\b.*(apply|delete|patch|create|edit|replace|scale|rollout|drain|cordon|uncordon)\b'; then
  echo "BLOCKED: direct kubectl writes are not allowed." >&2
  echo "Fix via git: edit the manifest, commit, and push to develop." >&2
  exit 2
fi

# ── block git push to any branch other than develop or chore/* ────────────────
if echo "$cmd" | grep -Eq '\bgit push\b'; then
  if ! echo "$cmd" | grep -Eq '\bgit push\b[^|&;]*\b(develop|chore/.+)'; then
    echo "BLOCKED: git push is only allowed to 'develop' or 'chore/*' branches." >&2
    echo "Use: git push origin develop  OR  git push origin chore/<name>" >&2
    exit 2
  fi
fi

# ── block force-push even to develop ─────────────────────────────────────────
if echo "$cmd" | grep -Eq '\bgit push\b.*(-f|--force)\b'; then
  echo "BLOCKED: force-push is not allowed." >&2
  exit 2
fi

# ── rebase onto origin/develop before push ────────────────────────────────────
# Intercept push (not commit) — the tree is clean at push time, so rebase works
# without stashing. Doing it at commit time fails because the agent has staged
# changes that git pull --rebase refuses to run over.
if echo "$cmd" | grep -Eq '\bgit push\b'; then
  echo "Pre-push: rebasing onto origin/develop..." >&2
  git fetch origin develop >&2 && git rebase origin/develop >&2 || {
    echo "WARNING: pre-push rebase failed — push may be rejected" >&2
  }
fi

exit 0
