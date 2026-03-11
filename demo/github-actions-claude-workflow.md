# Claude Code in GitHub Actions — Upgrade Versions Workflow

## Architecture

  The workflow uses a hybrid approach to minimise LLM token usage:

  - Bash (cheap, deterministic): scan-versions.sh | fetch-latest-versions.sh discovers all versioned components dynamically (no hardcoded list), fetches latest versions via GitHub API and Helm index, writes .version-report.md
  - Claude (expensive, flexible): reads the pre-computed report, applies sed edits, opens a PR

  The skill lives at .claude/skills/upgrade-versions/SKILL.md and is versioned alongside the code it acts on. The workflow prompt: is just /upgrade-versions — a pointer, not the instructions. Claude Code registers skill files as
  slash commands at startup; when it sees /upgrade-versions, it invokes ToolSearch to load the skill dynamically (visible as turn 2 in the execution log).

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

  Yes, AGENTS.md is always included — Claude Code reads CLAUDE.md at startup and follows @ includes. Every API call in the run carries the full project instructions.

  The jump from 7K to 18K happened when Claude ran cat .version-report.md — the bash output (a markdown table with ~50 rows) went directly into the context and stayed there for every subsequent turn.

---
##  How prompt caching actually works

  This is not like a database cache where a hit means "skip the work." It's the KV cache (key-value vectors in the transformer attention mechanism).

  - Without cache: model computes KV vectors for every input token from scratch — expensive, O(n²) with context length
  - With cache: pre-computed KV vectors are loaded from storage, but the attention pass still runs over all of them — the tokens are still in the context window and still influence every output
  - Cache hit ≠ "free" — it means "90% cheaper" ($0.50/MTok instead of $5/MTok)

  A useful analogy: it's like a pre-compiled library. You still link and load it on every run; you just didn't have to recompile it.

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

  allowedTools (in claude_args): which tools Claude is permitted to call. Must include Skill for slash commands to work. Without Skill, Claude cannot invoke /upgrade-versions and instead works from scratch — this was the cause of
   a 21-turn, $0.97 run.

  defaultMode: "acceptEdits" (in settings): whether Claude Code auto-approves file write operations. In GitHub Actions' non-interactive environment, the default mode blocks file edits and prompts for confirmation — which never
  comes. Setting acceptEdits fixes this. Without it, every Edit tool call fails with a permission denial even if Edit is in allowedTools.

  Also: the deprecated allowed_tools: parameter (v0.x) does nothing in claude-code-action@v1. The correct parameter is claude_args: '--allowedTools "..."'.

  ---
  Debugging artifacts

  The workflow uploads two files to GCS per run:

  - claude-prompt.txt: only contains the prompt: parameter value (/upgrade-versions). Not useful for understanding context size.
  - claude-execution-output.json: the full conversation transcript including the system item (full constructed system prompt), every assistant turn with per-turn usage fields (input_tokens, cache_creation_input_tokens,
  cache_read_input_tokens, output_tokens), and a final result item with aggregate totals and total_cost_usd.

  The result item's usage block is the authoritative source for total cost. The per-turn usage values in streaming mode are incremental chunks, not complete per-turn totals — use the result item for any cost analysis.

  ---
##  Key optimisations applied

  ┌─────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────┐
  │                             Problem                             │                              Fix                              │
  ├─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Claude worked from scratch (21 turns)                           │ Added Skill to allowedTools                                   │
  ├─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Edit tool permission denied                                     │ Added defaultMode: "acceptEdits" in settings                  │
  ├─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Edit requires Read-before-Edit (2 calls/file)                   │ Switched skill to use bash sed — no prior Read needed         │
  ├─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ Deprecated allowed_tools: param                                 │ Changed to claude_args: '--allowedTools ...'                  │
  ├─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ GitHub Step Summary missing                                     │ Added display_report: "true"                                  │
  ├─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┤
  │ provider-gcp-beta-container 404 JSON leaking into version field │ Piped gh api through jq explicitly instead of using --jq flag │
  └─────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────┘

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

## Cost at scale

  A single run costs ~$0.57. At organisation scale:

  - 10 repos × weekly = ~$297/year
  - 100 repos × weekly = ~$2,964/year
  - With extended thinking disabled and tighter turn limits: likely 40-60% lower

  The main levers are: (1) number of turns, (2) output tokens including thinking, (3) how
  quickly the context stabilises. Cache reads are already cheap — optimising them has
  diminishing returns compared to reducing turns.
