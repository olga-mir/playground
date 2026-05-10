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

echo "[guardrails] checking: ${cmd:0:120}" >&2

# ── block kubectl write operations ────────────────────────────────────────────
# All cluster changes must go through git → Flux. Read-only kubectl is allowed.
if echo "$cmd" | grep -Eq '\bkubectl\b.*[[:space:]](apply|delete|patch|create|edit|replace|scale|rollout|drain|cordon|uncordon)\b'; then
  echo "[guardrails] BLOCKED: direct kubectl writes are not allowed. Fix via git → Flux." >&2
  exit 2
fi

# ── block ambiguous kubectl queries ──────────────────────────────────────────
if echo "$cmd" | grep -Eq '\bkubectl\b.*\bget\b.*\b(providers|clusters)(\s|$)' && ! echo "$cmd" | grep -Eq '\b(providers\.pkg\.crossplane\.io|clusters\.container\.gcp\.m\.upbound\.io)\b'; then
  echo "[guardrails] BLOCKED: ambiguous resource name. Use fully qualified names like 'providers.pkg.crossplane.io' or 'clusters.container.gcp.m.upbound.io'." >&2
  exit 2
fi

# ── block git push to any branch other than develop or chore/* ────────────────
if echo "$cmd" | grep -Eq '\bgit push\b'; then
  # Check command text for an explicit branch name, and also check the current
  # branch — the command may use a shell variable that we can't expand here.
  current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  cmd_allows=$(echo "$cmd" | grep -Eq '\bgit push\b[^|&;]*\b(develop|chore/.+)' && echo yes || echo no)
  branch_allows=$(echo "$current_branch" | grep -Eq '^(develop|chore/)' && echo yes || echo no)
  if [[ "$cmd_allows" != "yes" && "$branch_allows" != "yes" ]]; then
    echo "[guardrails] BLOCKED: git push is only allowed to 'develop' or 'chore/*' branches (current: ${current_branch})." >&2
    exit 2
  fi
fi

# ── block force-push even to develop ─────────────────────────────────────────
if echo "$cmd" | grep -Eq '\bgit push\b.*(-f|--force)\b'; then
  echo "[guardrails] BLOCKED: force-push is not allowed." >&2
  exit 2
fi

# ── rebase onto origin/develop before push (develop branch only) ──────────────
# Only rebase when pushing from the develop branch itself. chore/* branches are
# based on main and must not be rebased onto develop — that would contaminate
# them with develop-only commits that aren't in main.
if echo "$cmd" | grep -Eq '\bgit push\b'; then
  current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  if [[ "$current_branch" == "develop" ]]; then
    echo "[guardrails] pre-push: fetching and rebasing onto origin/develop..." >&2
    if git fetch origin develop >&2 && git rebase origin/develop >&2; then
      echo "[guardrails] pre-push rebase OK — proceeding with push" >&2
    else
      echo "[guardrails] WARNING: pre-push rebase failed — push may be rejected" >&2
    fi
  fi
fi

echo "[guardrails] allowed" >&2
exit 0
