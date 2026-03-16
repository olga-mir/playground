# Claude Code in GitHub Actions — Upgrade Versions Workflow

> [!NOTE]
> Always prefer deterministic workflows where possible. Save the costs, the planet and the headache.

> [!NOTE]
> The goal this workflow achieves is not necessarily best suited for an AI. But this is a good example to experiment and understand LLM-based workflows.

Abridged execution log is available in this folder. Random uuids, session ids, though signatures were removed and outputs truncated for brevity. Additionally workflows have Summary available, example: https://github.com/olga-mir/playground/actions/runs/22926261398

PR created with this workflow: https://github.com/olga-mir/playground/pull/58

In this write-up, runs are referred to by a number, which corresponds to the run number in GitHub Actions: https://github.com/olga-mir/playground/actions/workflows/upgrade-versions.yml. Note that run-4 was deleted because it exposed information that was not intended to be public.

---

## Glossary

**API call** — one round trip to the Anthropic API. Claude sends the full conversation history and receives a response. This is what counts toward cost.

**Turn** — one tool invocation. A single API call can return multiple tool uses in one response (e.g. 7 `sed` commands), each counting as a separate **turn**. `num_turns` in the execution log counts tool invocations, not API calls.

**`type: user` / `type: assistant`** — message roles in the conversation transcript. `assistant` items are Claude's responses (one per API call, but logged as multiple items when the response contains multiple content blocks). `user` items are either the initial prompt or tool results being sent back. Items sharing the same `(cache_creation_input_tokens, cache_read_input_tokens)` pair belong to the same API call.

**Cached tokens** — tokens whose KV vectors were pre-computed and stored. On cache hit the model still attends over them (they're still in the context window), but at 10× lower cost than fresh input. Cache hit ≠ free — it means 90% cheaper.

**cc, cr** - shorthands for `context_creation`, context_read - fields seen in the execution log.

For example in run9 **one API call** returned 9 content blocks (`thinking` × 2, `tool_use` × 7). The SDK logged each block as a separate assistant item — all sharing cc=3007, cr=20774. Then 7 separate user items carry the results back, all empty because sed -i has no stdout.

```
  ONE API CALL (items 12-20, all cc=3007 cr=20774):
    item 12: assistant / thinking  "Good. kagent helm files use 0.7.21 without v prefix…"
    item 13: assistant / text      "Good - no v prefix. Now I'll apply all updates…"
    item 14: assistant / tool_use  Bash: sed -i kagent versions
    item 15: assistant / tool_use  Bash: find | xargs sed provider-helm
    item 16: assistant / tool_use  Bash: find | xargs sed provider-kubernetes
    item 17: assistant / tool_use  Bash: find | xargs sed function-go-templating
    item 18: assistant / tool_use  Bash: find | xargs sed function-auto-ready
    item 19: assistant / tool_use  Bash: find | xargs sed function-patch-and-transform
    item 20: assistant / tool_use  Bash: find | xargs sed function-environment-configs

  7 TOOL RESULTS (items 21-27, one user item per result):
    item 21: user / tool_result  "" (empty — sed -i has no stdout)
    item 22: user / tool_result  "" (empty)
    ...
    item 27: user / tool_result  "" (empty)

  NEXT API CALL begins at item 28 (new cc/cr pair)
```

If one API call did one sed operation, each call would incur charges for the entire context again and again.

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

The skills registered in the session are visible in the `system init` item of the [execution JSON](/demo/github-actions-claude-workflow/run9-abridged.json). Only `upgrade-versions` is the SKILL that comes from this repo, the rest are added automatically by Claude.

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

### SDK crash (runs 11+)

https://github.com/anthropics/claude-code-action/issues/892 (`SDK execution error: 14 |     depsCount: ${Q},`)
and
https://github.com/anthropics/claude-code-action/issues/1053 (`Credit balance is too low`)

Have fresh reports of the same issues that started happening in my workflows, without any known workarounds. Finalizing this demo will be suspended until this is resolved.

Did not help:
* Bumping API limits,
* Rotating API key
* Downgrading to SHA version mentioned in the 892 description, which still does not work:

```
SDK execution error: 14 |     depsCount: ${Q},
15 |     deps: ${$}}`};var Pj={keyword:"dependencies",type:"object",schemaType:"object",error:EB.error,code(X){let[Q,$]=Sj(X);RB(X,Q),IB(X,$)}};function Sj({schema:X}){let Q={},$={};for(let Y in X){if(Y==="__proto__")continue;let W=Array.isArray(X[Y])?Q:$;W[Y]=X[Y]}return[Q,$]}function RB(X,Q=X.schema){let{gen:$,data:Y,it:W}=X;if(Object.keys(Q).length===0)return;let J=$.let("missing");for(let G in Q){let H=Q[G];if(H.length===0)continue;let B=(0,W4.propertyInData)($,Y,G,W.opts.ownProperties);if(X.setParams({property:G,depsCount:H.length,deps:H.join(", ")}),W.allErrors)$.if(B,()=>{for(let z of H)(0,W4.checkReportMissingProp)(X,z)});else $.if(fY._`${B} && (${(0,W4.checkMissingProp)(X,H,J)})`),(0,W4.reportMissingProp)(X,J),$.else()}}EB.validatePropertyDeps=RB;function IB(X,Q=X.schema){let{gen:$,data:Y,keyword:W,it:J}=X,G=$.name("valid");for(let H in Q){if((0,bj.alwaysValidSchema)(J,Q[H]))continue;$.if((0,W4.propertyInData)($,Y,H,J.opts.ownProperties),()=>{let B=X.subschema({keyword:W,schemaProp:H},G);X.mergeValidEvalu
16 | `))X=Z0(X);let Y=`${new Date().toISOString()} [${Q.toUpperCase()}] ${X.trim()}
17 | `;if(WW()){d7(Y);return}_U().write(Y)}function GW(){return JW()??process.env.CLAUDE_CODE_DEBUG_LOGS_DIR??YW(V4(),"debug",`${s7()}.txt`)}var xU=k1(()=>{if(process.argv[2]==="--ripgrep")return;try{let X=GW(),Q=z9(X),$=YW(Q,"latest");if(!n0().existsSync(Q))n0().mkdirSync(Q);if(n0().existsSync($))try{n0().unlinkSync($)}catch{}n0().symlinkSync(X,$)}catch{}});var lU=!1;function F0(X,Q){let $=performance.now();try{return Q()}finally{performance.now()-$>B9}}var mU={cwd(){return process.cwd()},existsSync(X){return F0(`existsSync(${X})`,()=>h.existsSync(X))},async stat(X){return yU(X)},async readdir(X){return gU(X,{withFileTypes:!0})},async unlink(X){return fU(X)},async rmdir(X){return hU(X)},async rm(X,Q){return uU(X,Q)},statSync(X){return F0(`statSync(${X})`,()=>h.statSync(X))},lstatSync(X){return F0(`lstatSync(${X})`,()=>h.lstatSync(X))},readFileSync(X,Q){return F0(`readFileSync(${X})`,()=>h.readFileSync(X,{encoding:Q.encoding}))},readFileBytesSync(X){return F0(`readFileBytesSync(${X})`,()=>h.readFileSync(X))},readS
18 | `),F4}function N1(X){let Q=tU();if(!Q)return;let Y=`${new Date().toISOString()} ${X}
19 | `;nU(Q,Y)}function zW(X,Q){let $={...X};if(Q){let Y={sandbox:Q};if($.settings)try{Y={...L4($.settings),sandbox:Q}}catch{}$.settings=Z0(Y)}return $}class XX{options;process;processStdin;processStdout;ready=!1;abortController;exitError;exitListeners=[];processExitHandler;abortHandler;constructor(X){this.options=X;this.abortController=X.abortController||N6(),this.initialize()}getDefaultExecutable(){return j6()?"bun":"node"}spawnLocalProcess(X){let{command:Q,args:$,cwd:Y,env:W,signal:J}=X,G=W.DEBUG_CLAUDE_AGENT_SDK||this.options.stderr?"pipe":"ignore",H=aU(Q,$,{cwd:Y,stdio:["pipe","pipe",G],signal:J,env:W,windowsHide:!0});if(W.DEBUG_CLAUDE_AGENT_SDK||this.options.stderr)H.stderr.on("data",(z)=>{let K=z.toString();if(N1(K),this.options.stderr)this.options.stderr(K)});return{stdin:H.stdin,stdout:H.stdout,get killed(){return H.killed},get exitCode(){return H.exitCode},kill:H.kill.bind(H),on:H.on.bind(H),once:H.once.bind(H),off:H.off.bind(H)}}initialize(){try{let{additionalDirectories:X=[],agent:Q,betas:$,cwd:Y,execu

error: Claude Code process exited with code 1
      at $ (/home/runner/work/_actions/anthropics/claude-code-action/01e756b34ef7a1447e9508f674143b07d20c2631/base-action/node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs:19:7668)
      at emit (node:events:98:22)
      at #handleOnExit (node:child_process:520:14)

Error: Process completed with exit code 1.
```
