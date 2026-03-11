# Claude Code in GitHub Actions — Upgrade Versions Workflow

> [!NOTE]
> Always prefer deterministic workflows where possible. Save the costs, the planet and the headache.


> [!NOTE]
> The goal this workflow achieves is not necessarily best suited for an AI. But this is a good example to experiment and understand LLM-based workflows.

Abridged execution log is available in this folder. Random uuids, session ids, though signatures were removed and outputs truncated for brevity. Additionally workflows have Summary available, example: https://github.com/olga-mir/playground/actions/runs/22926261398

PR created with this workflow: https://github.com/olga-mir/playground/pull/58

## Architecture

The workflow uses a hybrid approach to minimise LLM token usage:

- Bash (cheap, deterministic): `scan-versions.sh | fetch-latest-versions.sh` discovers all versioned components dynamically (no hardcoded list), fetches latest versions via GitHub API and Helm index, writes `.version-report.md`
- Claude (expensive, flexible): reads the pre-computed report, applies sed edits, opens a PR

The skill lives at project skills level [.claude/skills/upgrade-versions/SKILL.md](/.claude/skills/upgrade-versions/SKILL.md). The workflow prompt: is just `/upgrade-versions` — a pointer, not the instructions. Claude Code registers skill files as
slash commands at startup; when it sees /upgrade-versions, it invokes `ToolSearch` to load the skill dynamically.

---

##  What makes up the context window

The initial 7K token cache (before any tool calls) is not just the skill file. It's everything Claude Code constructs at startup:

  ┌──────────────────────────────────────────────────────────────┬─────────┐
  │                            Source                            │ ~Tokens │
  ├──────────────────────────────────────────────────────────────┼─────────┤
  │ Claude Code built-in system prompt                           │ ~3,000  │
  ├──────────────────────────────────────────────────────────────┼─────────┤
  │ Tool JSON schemas (Bash, Read, Glob, Grep, Skill, TodoWrite) │ ~1,800  │
  ├──────────────────────────────────────────────────────────────┼─────────┤
  │ AGENTS.md (loaded via @AGENTS.md in CLAUDE.md)               │ ~670    │
  ├──────────────────────────────────────────────────────────────┼─────────┤
  │ SKILL.md                                                     │ ~770    │
  └──────────────────────────────────────────────────────────────┴─────────┘

`AGENTS.md` is always included — Claude Code reads `CLAUDE.md` at startup and follows @ includes. Every API call in the run carries the full project instructions.

The jump from 7K to 18K happened when Claude ran cat .version-report.md — the bash output (a markdown table with ~50 rows) went directly into the context and stayed there for every subsequent turn.

---
##  How prompt caching actually works

  This is not like a database cache where a hit means "skip the work." It's the KV cache (key-value vectors in the transformer attention mechanism).

  - Without cache: model computes KV vectors for every input token from scratch — expensive, O(n²) with context length
  - With cache: pre-computed KV vectors are loaded from storage, but the attention pass still runs over all of them — the tokens are still in the context window and still influence every output
  - Cache hit ≠ "free" — it means "90% cheaper" ($0.50/MTok instead of $5/MTok)

---

##  Why the context window keeps growing

  Every API call sends the entire conversation history — past turns don't expire or get trimmed mid-run. Each tool result (bash output, grep result, thinking block) is appended and stays permanently. With 20 turns and outputs
  accumulating:

  Turn 1:  context = 7K  (system prompt + skill + AGENTS.md)
  Turn 5:  context = 18K (+ version report from cat)
  Turn 10: context = 22K (+ grep outputs, sed confirmations, todo list)
  Turn 20: context = 25K (+ git diff, push output, PR URL)

  Total cache reads across all 28 API calls: 427K tokens at $0.50/MTok = $0.21. Not zero, even though it's "cached." The cache saved ~$1.93 versus no caching.

  ---

##  Cost breakdown — run-4 ($0.608)

  Model: claude-sonnet-4-6 — priced at $5/MTok input, $25/MTok output (not $3/$15 as one might assume from older models).

  ┌──────────────────────────────────┬─────────┬───────┬─────┐
  │            Component             │ Tokens  │ Cost  │  %  │
  ├──────────────────────────────────┼─────────┼───────┼─────┤
  │ Cache create (1.25× input)       │ 35,172  │ $0.22 │ 36% │
  ├──────────────────────────────────┼─────────┼───────┼─────┤
  │ Cache read (0.10× input)         │ 427,226 │ $0.21 │ 35% │
  ├──────────────────────────────────┼─────────┼───────┼─────┤
  │ Output (incl. extended thinking) │ 7,010   │ $0.18 │ 29% │
  ├──────────────────────────────────┼─────────┼───────┼─────┤
  │ Input (non-cached)               │ 23      │ ~$0   │ —   │
  └──────────────────────────────────┴─────────┴───────┴─────┘

  The output tokens (7,010) include extended thinking — Claude uses <thinking> blocks for planning before acting, which are billed as output. This is what drives the per-turn output cost even when the visible response is short.

  The primary cost lever is number of turns: fewer turns = less context accumulation = lower cache read total.
  Permissions

  Two separate permission mechanisms exist and they're easy to conflate:

  `allowedTools` (in `claude_args`): which tools Claude is permitted to call. Must include Skill for slash commands to work. Without Skill, Claude cannot invoke /upgrade-versions and instead works from scratch — this was the cause of
   a 21-turn, $0.97 run.

  defaultMode: "acceptEdits" (in settings): whether Claude Code auto-approves file write operations. In GitHub Actions' non-interactive environment, the default mode blocks file edits and prompts for confirmation — which never
  comes. Setting acceptEdits fixes this. Without it, every Edit tool call fails with a permission denial even if Edit is in allowedTools.

---

## What /compact does and doesn't do (run-9)

Attempted to reduce context mid-run by instructing the skill to call /compact after all file
edits, before the git/PR steps. The call was made via Skill("compact"). It did not work.

What actually happened (visible in run9-abridged.json, turns 27-28):

- Turn 27: Skill("compact") was called — context_management remained null
- Turn 28: cache_read INCREASED by 3,969 tokens (the compact invocation result itself was
  appended to the conversation like any other tool output)

Why: Skill() invokes user-defined skills from .claude/skills/. The built-in /compact command
is a Claude Code SDK primitive, not a user skill. They share slash-command syntax but are
different mechanisms. Calling Skill("compact") just searched for and found no matching skill,
added the result to context, and moved on.

The context_management field in the execution JSON would become non-null if the SDK's
automatic context compaction triggered. That requires hitting a context threshold, not an
explicit call. It cannot be triggered manually via a skill instruction.

Run-9 did end up cheaper ($0.57 vs $0.608) and used half the cache_read tokens (239K vs
427K), but this was from better command batching — Claude ran 7 sed commands in the same
turn (cr_delta=0 across turns 10-16), keeping the cached context stable across those calls.

---

## Comparing run-4 and run-9

  ┌──────────────────┬────────────┬────────────┐
  │                  │   run-4    │   run-9    │
  ├──────────────────┼────────────┼────────────┤
  │ Cost             │ $0.608     │ $0.571     │
  ├──────────────────┼────────────┼────────────┤
  │ Turns            │ 20         │ 18         │
  ├──────────────────┼────────────┼────────────┤
  │ Cache read       │ 427,226    │ 239,723    │
  ├──────────────────┼────────────┼────────────┤
  │ Cache create     │ 35,172     │ 40,264     │
  ├──────────────────┼────────────┼────────────┤
  │ Output tokens    │ 7,010      │ 7,966      │
  ├──────────────────┼────────────┼────────────┤
  │ Peak context     │ ~28K       │ ~32K       │
  └──────────────────┴────────────┴────────────┘

  Cache reads halved despite peak context being larger — fewer turns meant less re-reading of
  the growing context. The cost improvement came from command batching, not from compaction.


---

## Unexpected Curveballs

As I was iterating with my workflow runs, suddendenly two things happened one after the other. First, during the execution, just before opening PR Claude decided it would be a cool idea to `Simplify`. This took it on an archeological journey through repo history, brought up a lot of unrelated stuff and never ended in a working PR, while burning more tokens than previous runs. This Skill is added automatically and I haven't find a way to remove or block it. In the run9 logs in this folder you can see at the top following snippet:

```
    "skills": [
      "debug",
      "simplify",
      "batch",
      "claude-api",
      "upgrade-versions"
    ],
```

Second, all of a sudden the workflow started breking at init stage, presumably due to: https://github.com/anthropics/claude-code-action/issues/892

