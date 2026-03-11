# Claude Code in GitHub Actions — Upgrade Versions Workflow

> [!NOTE]
> Always prefer deterministic workflows where possible. Save the costs, the planet and the headache.

> [!NOTE]
> The goal this workflow achieves is not necessarily best suited for an AI. But this is a good example to experiment and understand LLM-based workflows.

Abridged execution log is available in this folder. Random uuids, session ids, though signatures were removed and outputs truncated for brevity. Additionally workflows have Summary available, example: https://github.com/olga-mir/playground/actions/runs/22926261398

PR created with this workflow: https://github.com/olga-mir/playground/pull/58

In this write-up runs refered by a number - this number is a run number in GH Actions: https://github.com/olga-mir/playground/actions/workflows/upgrade-versions.yml Although run-4 is deleted because it exposed information which was not intended to be public.

---

## Glossary

**API call** — one round trip to the Anthropic API. Claude sends the full conversation history and receives a response. This is what counts toward cost.

**Turn** — one tool invocation. A single API call can return multiple tool uses in one response (e.g. 7 `sed` commands), each counting as a separate **turn**. `num_turns` in the execution log counts tool invocations, not API calls.

**`type: user` / `type: assistant`** — message roles in the conversation transcript. `assistant` items are Claude's responses (one per API call, but logged as multiple items when the response contains multiple content blocks). `user` items are either the initial prompt or tool results being sent back. Items sharing the same `(cache_creation_input_tokens, cache_read_input_tokens)` pair belong to the same API call.

**Cached tokens** — tokens whose KV vectors were pre-computed and stored. On cache hit the model still attends over them (they're still in the context window), but at 10× lower cost than fresh input. Cache hit ≠ free — it means 90% cheaper.

---

## Architecture

The workflow uses a hybrid approach to minimise LLM token usage:

- **Bash** (cheap, deterministic): `scan-versions.sh | fetch-latest-versions.sh` discovers all versioned components dynamically (no hardcoded list), fetches latest versions via GitHub API and Helm index, writes `.version-report.md`
- **Claude** (expensive, flexible): reads the pre-computed report, applies sed edits, opens a PR

The skill lives at project skills level [.claude/skills/upgrade-versions/SKILL.md](/.claude/skills/upgrade-versions/SKILL.md). The workflow `prompt:` is just `/upgrade-versions` — a pointer, not the instructions. Claude Code registers skill files as slash commands at startup; when it sees `/upgrade-versions` it loads the skill content into the initial context before the first API call.

---

## What makes up the context window

The initial 7K token cache (before any tool calls) is not just the skill file. It's everything Claude Code constructs at startup:

| Source | ~Tokens |
|---|---|
| Claude Code built-in system prompt | ~3,000 |
| Tool JSON schemas (Bash, Read, Glob, Grep, Skill, TodoWrite) | ~1,800 |
| AGENTS.md (loaded via `@AGENTS.md` in CLAUDE.md) | ~670 |
| SKILL.md | ~770 |

`AGENTS.md` is always included — Claude Code reads `CLAUDE.md` at startup and follows `@` includes. Every API call in the run carries the full project instructions.

The jump from 7K to 18K happened when Claude ran `cat .version-report.md` — the bash output (a markdown table with ~50 rows) went directly into the context and stayed there for every subsequent turn.

---

## How prompt caching actually works

This is not like a database cache where a hit means "skip the work." It's the KV cache (key-value vectors in the transformer attention mechanism).

- **Without cache**: model computes KV vectors for every input token from scratch — expensive, O(n²) with context length
- **With cache**: pre-computed KV vectors are loaded from storage, but the attention pass still runs over all of them — the tokens are still in the context window and still influence every output
- **Cache hit ≠ "free"** — it means "90% cheaper" ($0.50/MTok instead of $5/MTok)

A useful analogy: it's like a pre-compiled library. You still link and load it on every run; you just didn't have to recompile it.

---

## Context window grows with each turn

Every API call sends the entire conversation history — past turns don't expire or get trimmed mid-run. Each tool result (bash output, grep result, thinking block) is appended and stays permanently:

```
Turn 1:  context = 7K  (system prompt + skill + AGENTS.md)
Turn 5:  context = 18K (+ version report from cat)
Turn 10: context = 22K (+ grep outputs, sed confirmations)
Turn 20: context = 25K (+ git diff, push output, PR URL)
```

Total cache reads across all API calls in run-4: 427K tokens at $0.50/MTok = $0.21. Not zero, even though it's "cached." The cache saved ~$1.93 versus no caching.

---

## Cost breakdown — run-4 ($0.608)

Model: `claude-sonnet-4-6` — priced at $5/MTok input, $25/MTok output (not $3/$15 as one might assume from older models).

| Component | Tokens | Cost | % |
|---|---|---|---|
| Cache create (1.25× input) | 35,172 | $0.22 | 36% |
| Cache read (0.10× input) | 427,226 | $0.21 | 35% |
| Output (incl. extended thinking) | 7,010 | $0.18 | 29% |
| Input (non-cached) | 23 | ~$0 | — |

The output tokens include extended thinking — Claude uses `<thinking>` blocks for planning before acting, which are billed as output.

The primary cost lever is **number of API calls**: fewer calls = less re-reading of the growing context = lower total cache read cost.

**Run-4**: grep verify → sed kagent → 7×sed crossplane (one script) → grep verify → grep README → 3×sed README → grep verify → git diff → git commit → git push → gh pr = ~12 bash calls across many API calls with thinking turns between each

**Run-9**: grep → sed+6×find (one API response, 7 `tool_use`) → 2×sed README → 2×git diff → git commit+push+pr = fewer total API calls partly because multiple `tool_use`s were returned in single API responses


---

## Permissions

Two separate permission mechanisms exist and they're easy to conflate:

**`allowedTools`** (in `claude_args`): which tools Claude is permitted to call. Must include `Skill` — without it the CLI does not load any skills at all, so `/upgrade-versions` is never registered and the run crashes immediately at init with exit code 1.

**`defaultMode: "acceptEdits"`** (in `settings`): whether Claude Code auto-approves file write operations. In GitHub Actions' non-interactive environment, the default mode blocks file edits and prompts for confirmation — which never comes. Setting `acceptEdits` fixes this. Without it, every `Edit` tool call fails with a permission denial even if `Edit` is in `allowedTools`.

Also: the deprecated `allowed_tools:` parameter (v0.x) does nothing in `claude-code-action@v1`. The correct parameter is `claude_args: '--allowedTools "..."'`.

---

## What /compact does and doesn't do (run-9)

Attempted to reduce context mid-run by instructing the skill to call `/compact` after all file edits, before the git/PR steps. The call was made via `Skill("compact")`. It did not work.

What actually happened (visible in run9-abridged.json, turns 27-28):

- Turn 27: `Skill("compact")` was called — `context_management` remained null
- Turn 28: `cache_read` **increased** by 3,969 tokens (the compact invocation result itself was appended to the conversation like any other tool output)

Why: `Skill()` invokes user-defined skills from `.claude/skills/`. The built-in `/compact` command is a Claude Code SDK primitive, not a user skill. They share slash-command syntax but are different mechanisms.

The `context_management` field in the execution JSON would become non-null if the SDK's automatic context compaction triggered. That requires hitting a context threshold, not an explicit call.

Run-9 did end up cheaper ($0.57 vs $0.608) and used fewer total cache-read tokens (239K vs 427K) — but this was from Claude making fewer API calls overall, not from compaction.

---

## Comparing run-4 and run-9

| | run-4 | run-9 |
|---|---|---|
| Cost | $0.608 | $0.571 |
| Turns | 20 | 18 |
| Cache read | 427,226 | 239,723 |
| Cache create | 35,172 | 40,264 |
| Output tokens | 7,010 | 7,966 |
| Peak context | ~28K | ~32K |

**Why cache reads differ despite similar peak context:** both runs batched sed commands — run-4 issued all crossplane updates as a single multi-line bash script (one `Bash` tool_use), run-9 issued them as multiple `tool_use` blocks within a single API call. The difference in total cache reads comes from run-4 making more API calls overall: more intermediate verification greps and thinking turns, each re-reading the full growing context. More API calls × ~22K average context = higher total cache reads.

How to identify API calls in the execution JSON: items that share the same `(cache_creation_input_tokens, cache_read_input_tokens)` pair belong to one API call. Total `cache_read` for a run = sum of unique `cache_read_input_tokens` values, one per API call.

---

## Unexpected curveballs

### The simplify hijack (run-10)

Just before opening the PR, Claude decided to invoke the `simplify` skill. This took it on an archaeological journey through repo history, brought up a lot of unrelated changes, and never produced a working PR — while costing $0.917, the most expensive run.

The root cause: `Skill` must be in `allowedTools` (required to load skills at all), but that also allows Claude to call *any* registered skill mid-execution. After running `git diff`, Claude saw changed code and autonomously invoked `simplify` with `caller.type: "direct"` — its own decision, not triggered by an agent.

The skills registered in the session are visible in the `system init` item of the execution JSON:

```json
"skills": ["debug", "simplify", "batch", "claude-api", "upgrade-versions"]
```

**Fix:** (yet to be tested) a `PreToolUse` hook in the workflow's `settings` block blocks any `Skill` call where the skill name is not `upgrade-versions`:

```json
"hooks": {
  "PreToolUse": [{
    "matcher": "Skill",
    "hooks": [{
      "type": "command",
      "command": "skill=$(echo \"$CLAUDE_TOOL_INPUT\" | jq -r '.skill // empty'); if [ \"$skill\" != \"upgrade-versions\" ]; then echo \"Blocked\"; exit 2; fi"
    }]
  }]
}
```

Exit code 2 is Claude Code's signal for permission denied. This is a technical fence enforced before Claude acts — the right place for a workflow-level constraint, not inside the skill itself.

Note: removing `Skill` from `allowedTools` entirely causes the run to crash at init (skills not loaded); the skill file's `allowed-tools` frontmatter does not restrict the global execution context.

### The AJV crash (runs 11+)

Shortly after, the workflow started crashing at init with exit code 1 and an AJV JSON schema validation error, `duration_ms: ~150`, `total_cost_usd: 0`. This is a known upstream bug: https://github.com/anthropics/claude-code-action/issues/892

The action installs the latest Claude Code binary at runtime. A version bump broke AJV schema validation during SDK initialization, affecting all configurations. Earlier runs (9, 10) happened to use a working version.

Downgrading to `@anthropic-ai/claude-code@2.1.18` did not help.
