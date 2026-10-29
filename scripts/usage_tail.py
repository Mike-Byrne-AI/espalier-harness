#!/usr/bin/env python3
"""Where a Claude Code session's tokens go, by context size -- from its transcripts.

The pre-registered instrument for the threshold handoff (`handoff_context_tokens`,
read by `tools/cc/hooks/task_router.py`): weighted tokens per session and per
calendar day, bucketed by the context size each turn ran at, with the restart
cost a fresh session pays and a counterfactual for cutting every session at a
cap. The before/after measure is the per-day table: a session after a `/clear`
is shorter by construction, so per-session figures do not compare across the
change, and a day's spend does. Dev-only, like `scripts/proof_tier.py`; never
deployed.

    python3 scripts/usage_tail.py ~/.claude/projects/<slug> [<slug>...] [--json]
        [--cache-write-weight 2.0]

Reads every `*.jsonl` directly under each directory (one per session) and the
`**/subagents/*.jsonl` beneath it (one per subagent run). A transcript holds one
JSON record per line and one line per CONTENT BLOCK, each carrying the same
`message.usage`, so the figures count one record per `(message.id, requestId)`
(the review of the first derivation found 41,704 lines for 14,154 messages,
2026-10-26). Sessions with fewer than MIN_TURNS turns are left out.

Weights are the published API price ratios against uncached input: cache read
0.1, output 5, cache write 1.25 for the five-minute cache or 2.0 for the
one-hour cache (the status line's `prompt_cache` field names which one an
account runs; this box runs the one-hour cache, so 2.0 is the default). They
are a proxy: the meter behind a subscription limit is not public, and the raw
token shares, printed beside them, show the same shape.

The counterfactual is a crude model, stated so it can be refuted: a turn whose
context exceeded the cap is re-priced as if its cached prefix averaged half the
cap, and each session pays one restart (its own first RESTART_TURNS turns) per
cap-width of peak context. The handoff turns themselves are not modelled.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

CACHE_READ_WEIGHT = 0.1
OUTPUT_WEIGHT = 5.0
DEFAULT_CACHE_WRITE_WEIGHT = 2.0
MIN_TURNS = 20
RESTART_TURNS = 5
BUCKET_EDGES = (0, 50_000, 100_000, 150_000, 200_000, 300_000, 500_000, 750_000, 10**9)
BUCKET_NAMES = ("<50k", "50-100k", "100-150k", "150-200k", "200-300k", "300-500k", "500-750k", "750k+")
CAPS = (150_000, 200_000, 300_000, 500_000)
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def weights(cache_write: float) -> dict[str, float]:
    return {"input_tokens": 1.0, "cache_creation_input_tokens": cache_write,
            "cache_read_input_tokens": CACHE_READ_WEIGHT, "output_tokens": OUTPUT_WEIGHT}


def scan_transcript(path: str) -> list[dict[str, int]]:
    """One usage record per `(message.id, requestId)`, in file order; a line
    that is not JSON, not an assistant record, or has no usage is skipped."""
    seen: dict[tuple[str, str], dict[str, int]] = {}
    order: list[tuple[str, str]] = []
    with open(path, "rb") as fh:
        for lineno, raw in enumerate(fh):
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            message = rec.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            key = (str(message.get("id") or ""), str(rec.get("requestId") or ""))
            if key == ("", ""):
                key = ("", f"line-{lineno}")   # no id at all: its own turn, never folded into one
            if key in seen:
                continue
            record = {k: _count(usage.get(k)) for k in USAGE_KEYS}
            stamp = rec.get("timestamp")
            record["day"] = int(stamp[:10].replace("-", "")) if isinstance(stamp, str) and len(stamp) >= 10 and stamp[:10].replace("-", "").isdigit() else 0
            seen[key] = record
            order.append(key)
    return [seen[k] for k in order]


def _count(value: object) -> int:
    """A usage count as an int; anything that is not a finite number is 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value) if value == value and value not in (float("inf"), float("-inf")) else 0


def context_of(u: dict[str, int]) -> int:
    return u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]


def weighted(u: dict[str, int], w: dict[str, float]) -> float:
    return sum(u[k] * w[k] for k in USAGE_KEYS)


def raw_total(u: dict[str, int]) -> int:
    return context_of(u) + u["output_tokens"]


def bucket_of(context: int) -> str:
    for i in range(len(BUCKET_EDGES) - 1):
        if BUCKET_EDGES[i] <= context < BUCKET_EDGES[i + 1]:
            return BUCKET_NAMES[i]
    return BUCKET_NAMES[-1]


def counterfactual(u: dict[str, int], w: dict[str, float], cap: int) -> float:
    """The turn's weighted cost had the session been cut at ``cap``: a cached
    prefix past the cap is re-priced at an average of half the cap."""
    cost = weighted(u, w)
    context = context_of(u)
    if context <= cap:
        return cost
    scale = (cap / 2) / context
    return cost - u["cache_read_input_tokens"] * w["cache_read_input_tokens"] * (1 - scale)


def analyse_dir(directory: str, w: dict[str, float]) -> dict[str, Any]:
    """The figures for one transcript directory: the per-session rows, the
    bucket table, the restart cost, the cap counterfactuals and the subagent
    shape."""
    # Hidden names under the directory are skipped (a sidecar's dotfile is not
    # a transcript); the directory itself may sit under ~/.claude.
    base = Path(directory)
    sessions = sorted(str(p) for p in base.glob("*.jsonl") if not p.name.startswith("."))
    subagents = sorted(str(p) for p in base.glob("**/subagents/*.jsonl")
                       if not any(part.name.startswith(".") for part in (p, p.parent, p.parent.parent)))
    rows: list[dict[str, Any]] = []
    bucket_w: dict[str, float] = defaultdict(float)
    bucket_raw: dict[str, int] = defaultdict(int)
    bucket_n: dict[str, int] = defaultdict(int)
    composition: dict[str, float] = defaultdict(float)
    restarts: list[float] = []
    cf = {cap: 0.0 for cap in CAPS}
    restarts_needed = {cap: 0 for cap in CAPS}
    by_day_w: dict[int, float] = defaultdict(float)
    by_day_n: dict[int, int] = defaultdict(int)
    total_w = 0.0
    total_raw = 0
    for path in sessions:
        turns = scan_transcript(path)
        if len(turns) < MIN_TURNS:
            continue
        for u in turns:
            by_day_w[u["day"]] += weighted(u, w)
            by_day_n[u["day"]] += 1
        session_w = sum(weighted(u, w) for u in turns)
        peak = max(context_of(u) for u in turns)
        tail_w = sum(weighted(u, w) for u in turns if context_of(u) >= 150_000)
        rows.append({"session": os.path.basename(path)[:8], "turns": len(turns), "peak_context": peak,
                     "weighted": session_w, "tail_share": (tail_w / session_w) if session_w else 0.0})
        restarts.append(sum(weighted(u, w) for u in turns[:RESTART_TURNS]))
        for cap in CAPS:
            restarts_needed[cap] += peak // cap
        for u in turns:
            name = bucket_of(context_of(u))
            cost = weighted(u, w)
            bucket_w[name] += cost
            bucket_raw[name] += raw_total(u)
            bucket_n[name] += 1
            total_w += cost
            total_raw += raw_total(u)
            for k in USAGE_KEYS:
                composition[k] += u[k] * w[k]
            for cap in CAPS:
                cf[cap] += counterfactual(u, w, cap)
    restart_median = statistics.median(restarts) if restarts else 0.0
    caps = {}
    for cap in CAPS:
        overhead = (restarts_needed[cap] * restart_median / total_w) if total_w else 0.0
        ratio = (cf[cap] / total_w) if total_w else 0.0
        caps[cap] = {"counterfactual": ratio, "restart_overhead": overhead, "net": ratio + overhead,
                     "restarts": restarts_needed[cap]}
    sub_peak: list[int] = []
    sub_first: list[int] = []
    sub_w: list[float] = []
    for path in subagents:
        turns = scan_transcript(path)
        if not turns:
            continue
        sub_peak.append(max(context_of(u) for u in turns))
        sub_first.append(context_of(turns[0]))
        sub_w.append(sum(weighted(u, w) for u in turns))
    return {
        "directory": directory, "sessions": len(rows), "turns": sum(r["turns"] for r in rows),
        "rows": sorted(rows, key=lambda r: -r["weighted"]),
        "buckets": {name: {"turns": bucket_n[name], "weighted_share": (bucket_w[name] / total_w) if total_w else 0.0,
                           "raw_share": (bucket_raw[name] / total_raw) if total_raw else 0.0}
                    for name in BUCKET_NAMES},
        "composition": {k: (v / total_w) if total_w else 0.0 for k, v in composition.items()},
        "days": {str(day): {"turns": by_day_n[day], "weighted": by_day_w[day]} for day in sorted(by_day_w)},
        "restart_median": restart_median, "caps": caps,
        "subagents": {"runs": len(sub_w), "peak_p50": _quantile(sub_peak, 0.5), "peak_p90": _quantile(sub_peak, 0.9),
                      "first_turn_p50": _quantile(sub_first, 0.5), "weighted_p50": _quantile(sub_w, 0.5),
                      "weighted_total": sum(sub_w), "share_of_main": (sum(sub_w) / total_w) if total_w else 0.0},
        "weighted_total": total_w,
    }


def _quantile(values: list[Any], q: float) -> Any:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def render(report: dict[str, Any]) -> str:
    out = [f"dir {os.path.basename(report['directory'])}: sessions {report['sessions']}, turns {report['turns']}"]
    out.append("session   turns  peak_ctx   weighted  tail_share")
    for r in report["rows"][:10]:
        out.append(f"{r['session']:<8} {r['turns']:>6} {r['peak_context']:>9,} {r['weighted']:>10,.0f}  {r['tail_share']:.2f}")
    out.append("bucket     turns  weighted_share  raw_share")
    for name, b in report["buckets"].items():
        out.append(f"{name:<9} {b['turns']:>7}  {b['weighted_share']:>13.2f}  {b['raw_share']:>9.2f}")
    out.append("composition: " + ", ".join(f"{k} {v:.2f}" for k, v in report["composition"].items()))
    out.append("day (UTC)   turns    weighted   -- the before/after measure: spend per seat per day")
    for day, d in list(report["days"].items())[-14:]:
        label = f"{day[:4]}-{day[4:6]}-{day[6:]}" if len(day) == 8 else day
        out.append(f"{label:<10} {d['turns']:>6} {d['weighted']:>11,.0f}")
    out.append(f"restart cost (first {RESTART_TURNS} turns), median weighted: {report['restart_median']:,.0f}")
    out.append("cap        counterfactual  restart_overhead   net")
    for cap, c in report["caps"].items():
        out.append(f"{cap:>8,}   {c['counterfactual']:>13.2f}  {c['restart_overhead']:>16.3f}  {c['net']:>5.2f}")
    s = report["subagents"]
    out.append(f"subagents: runs {s['runs']}, peak context p50 {s['peak_p50']:,} p90 {s['peak_p90']:,}, "
               f"first-turn p50 {s['first_turn_p50']:,}, weighted p50 {s['weighted_p50']:,.0f}, "
               f"share of main {s['share_of_main']:.2f}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directories", nargs="+", help="transcript directories (~/.claude/projects/<slug>)")
    parser.add_argument("--json", action="store_true", help="the figures as one JSON object per directory")
    parser.add_argument("--cache-write-weight", type=float, default=DEFAULT_CACHE_WRITE_WEIGHT,
                        help="1.25 for the five-minute cache, 2.0 for the one-hour cache (default)")
    args = parser.parse_args(argv)
    w = weights(args.cache_write_weight)
    reports = []
    for directory in args.directories:
        if not os.path.isdir(directory):
            print(f"usage_tail: not a directory: {directory}", file=sys.stderr)
            return 2
        reports.append(analyse_dir(directory, w))
    if args.json:
        print(json.dumps({"cache_write_weight": args.cache_write_weight, "reports": reports}, default=str))
    else:
        print(f"cache-write weight {args.cache_write_weight}; one record per (message.id, requestId); "
              f"sessions under {MIN_TURNS} turns left out\n")
        print("\n\n".join(render(r) for r in reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
