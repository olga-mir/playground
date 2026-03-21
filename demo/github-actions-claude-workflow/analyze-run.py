#!/usr/bin/env python3
"""
Analyze a Claude Code execution JSON log (abridged or full).

Usage:
    python3 analyze-run.py run9-abridged.json [run25-abridged.json ...]

For each file, prints:
  - Per-API-call token breakdown (groups assistant items by cc/cr pair)
  - Total token counts
  - Implied pricing (back-calculated from total_cost_usd in result item)
  - Side-by-side comparison when multiple files given
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Known pricing tiers (input, cache_create, cache_read, output) in $/MTok
PRICING_TIERS = [
    ("sonnet-4-6 v1  ($5/25)", 5.00, 6.25, 0.500, 25.0),
    ("sonnet-4-6 v2  ($3/15)", 3.00, 3.75, 0.300, 15.0),
    ("sonnet-4-5      ($3/15)", 3.00, 3.75, 0.300, 15.0),
    ("haiku-4-5      ($0.8/4)", 0.80, 1.00, 0.080,  4.0),
]


def load(path):
    with open(path) as f:
        return json.load(f)


def extract_stats(data):
    """
    Returns a dict with aggregate stats and per-API-call breakdown.

    API calls are identified by unique (cc, cr) pairs on assistant items.
    Items sharing the same pair belong to one API call.
    """
    result_item = None
    init_item = None
    api_calls = {}           # (cc, cr) -> {"cc": int, "cr": int, "tools": [], "texts": [], "thinking": []}
    call_order = []          # preserves insertion order of (cc, cr) keys

    for item in data:
        t = item.get("type")

        if t == "system" and item.get("subtype") == "init":
            init_item = item

        elif t == "result":
            result_item = item

        elif t == "assistant":
            msg = item.get("message", {})
            usage = msg.get("usage", {})
            cc = usage.get("cache_creation_input_tokens", 0)
            cr = usage.get("cache_read_input_tokens", 0)
            key = (cc, cr)

            if key not in api_calls:
                api_calls[key] = {"cc": cc, "cr": cr, "tools": [], "texts": [], "thinking": []}
                call_order.append(key)

            for c in msg.get("content", []):
                ctype = c.get("type")
                if ctype == "tool_use":
                    api_calls[key]["tools"].append(c.get("name", "?"))
                elif ctype == "text":
                    api_calls[key]["texts"].append(c.get("text", "")[:80].replace("\n", " "))
                elif ctype == "thinking":
                    api_calls[key]["thinking"].append(c.get("thinking", "")[:80].replace("\n", " "))

    usage = result_item.get("usage", {}) if result_item else {}
    total = {
        "input":  usage.get("input_tokens", 0),
        "cc":     usage.get("cache_creation_input_tokens", 0),
        "cr":     usage.get("cache_read_input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "cost":   result_item.get("total_cost_usd") if result_item else None,
        "turns":  result_item.get("num_turns") if result_item else None,
        "duration_s": (result_item.get("duration_ms", 0) // 1000) if result_item else None,
        "model":  init_item.get("model", "?") if init_item else "?",
        "claude_code_version": init_item.get("claude_code_version", "?") if init_item else "?",
        "num_api_calls": len(api_calls),
        "api_calls_detail": [api_calls[k] for k in call_order],
    }
    return total


def implied_pricing(stats):
    """Returns (tier_name, inp_rate, cc_rate, cr_rate, out_rate) of best match."""
    if stats["cost"] is None:
        return None
    best = None
    best_diff = float("inf")
    for tier in PRICING_TIERS:
        name, r_inp, r_cc, r_cr, r_out = tier
        calc = (
            stats["input"] * r_inp +
            stats["cc"] * r_cc +
            stats["cr"] * r_cr +
            stats["output"] * r_out
        ) / 1_000_000
        diff = abs(calc - stats["cost"])
        if diff < best_diff:
            best_diff = diff
            best = (tier, calc, diff)
    return best


def print_run(label, stats):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  model={stats['model']}  cc_version={stats['claude_code_version']}")
    print(f"{'='*60}")
    print(f"  Turns:          {stats['turns']}")
    print(f"  Duration:       {stats['duration_s']}s")
    print(f"  API calls:      {stats['num_api_calls']}")
    print(f"  Input tokens:   {stats['input']:>10,}")
    print(f"  Cache create:   {stats['cc']:>10,}")
    print(f"  Cache read:     {stats['cr']:>10,}")
    print(f"  Output tokens:  {stats['output']:>10,}")
    if stats["cost"] is not None:
        print(f"  Total cost:     ${stats['cost']:.6f}")
        match = implied_pricing(stats)
        if match:
            tier, calc, diff = match
            print(f"  Implied tier:   {tier[0]}  (calculated=${calc:.6f}, diff=${diff:+.6f})")

    print()
    print("  Per-API-call breakdown:")
    print(f"  {'#':>3}  {'cc':>8}  {'cr':>8}  {'tools / text'}")
    print(f"  {'-'*3}  {'-'*8}  {'-'*8}  {'-'*40}")
    for i, call in enumerate(stats["api_calls_detail"], 1):
        tools = ", ".join(call["tools"]) if call["tools"] else ""
        text = " | ".join(call["texts"]) if call["texts"] else ""
        thinking = call["thinking"][0][:60] if call["thinking"] else ""
        summary = tools or text or thinking or "(no content)"
        print(f"  {i:>3}  {call['cc']:>8,}  {call['cr']:>8,}  {summary[:60]}")


def print_comparison(labels, all_stats):
    print(f"\n{'='*60}")
    print("  Side-by-side comparison")
    print(f"{'='*60}")
    fields = [
        ("Turns",         "turns"),
        ("API calls",     "num_api_calls"),
        ("Duration (s)",  "duration_s"),
        ("Input tokens",  "input"),
        ("Cache create",  "cc"),
        ("Cache read",    "cr"),
        ("Output tokens", "output"),
        ("Cost (USD)",    "cost"),
    ]
    col_w = 14
    header = f"  {'':20}" + "".join(f"{l:>{col_w}}" for l in labels)
    print(header)
    print(f"  {'-'*20}" + "-" * col_w * len(labels))
    for fname, key in fields:
        row = f"  {fname:<20}"
        for s in all_stats:
            val = s.get(key)
            if val is None:
                row += f"{'N/A':>{col_w}}"
            elif isinstance(val, float):
                row += f"${val:>{col_w-1}.4f}"
            else:
                row += f"{val:>{col_w},}" if isinstance(val, int) else f"{val:>{col_w}}"
        print(row)

    print()
    print("  Implied pricing tier:")
    for label, s in zip(labels, all_stats):
        match = implied_pricing(s)
        if match:
            tier, calc, diff = match
            print(f"    {label}: {tier[0]}  (calc=${calc:.4f}, diff=${diff:+.4f})")
        else:
            print(f"    {label}: cost unknown")


def main():
    paths = sys.argv[1:]
    if not paths:
        print("Usage: analyze-run.py <run-abridged.json> [...]")
        sys.exit(1)

    all_stats = []
    labels = []
    for p in paths:
        path = Path(p)
        data = load(path)
        stats = extract_stats(data)
        label = path.stem
        labels.append(label)
        all_stats.append(stats)
        print_run(label, stats)

    if len(all_stats) > 1:
        print_comparison(labels, all_stats)


if __name__ == "__main__":
    main()
