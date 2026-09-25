# TP-360 — Hook & scanner performance levers

## Status
- Version target: current (self-host, pre-OSS-launch)
- Change type: PERF — two measured-but-unbuilt latency levers, batched as a
  single deferred "performance" pack so they share one before/after
  measurement discipline. **Neither gates the launch.** Both are
  moderate-to-higher risk relative to their payoff, and the payoff itself is
  MEASURED for one lever and only CLAIMED for the other — this pack requires a
  real before/after number, it does not assume the win.
- **Kind: PACK** (two independent sub-tasks; 1-A is self-contained and lands
  first, 2-A is architectural and rides behind it — may be split off or dropped)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`)
  + `reports/lost-idea-sweep-2026-07-26.md` rows **#34** (cross-scanner
  shared-AST cache, source `blueprint 20260626-044723`) and **#20**
  (dispatcher-merge latency lever, source `Done/TP-340:70`,
  `reports/hook_latency.md:~78`).

## Motivation

The pre-flip sweep surfaced two performance levers that were **measured or
named, then never built and never tracked** — they leaked out of the
FORWARD_LEDGER's lineage entirely (the seam a self-consistency audit
structurally can't catch). Both are verified-lost forward-work: un-tracked AND
un-done at HEAD (grep-confirmed below — no `_ast_cache`, no dispatcher exists).

They belong together because the honest framing is identical for both: **the
direction is sound; the magnitude is the open question.**

- **1-A (AST cache)** has a MEASURED payoff (~1.9 s of redundant re-parsing on
  `espalier scan`), a contained blast radius, and a real correctness risk
  (decode-policy unification across scanners) that a differential test pins.
- **2-A (dispatcher-merge)** has a CLAIMED payoff (~50% of a ~170 ms/edit
  footprint → ~93 ms), a large blast radius (it breaks the one-hook-per-event
  model and its contract tests), and was explicitly judged **"not worth it
  pre-release"** in `reports/hook_latency.md`. It is packed here so the idea has
  a tracked home, not because it is ready to execute — see the reco note in the
  Landing stanza.

Neither lever is on any adopter's hot path: `espalier scan` is a self-host /
maintenance command, and the per-edit hook footprint is already sub-200 ms
(below interactive-friction threshold for an agent loop whose threat model is
mistakes, not throughput — `reports/hook_latency.md` "Verdict"). This is
deferred cleanup, not release work.

## Scope (in)

### Sub-task 1-A — Cross-scanner shared-AST cache (#34)

**Mechanism (grounded).** `espalier/cli.py::cmd_scan` (L2876) runs ~10 scanners
sequentially in one process. Eight of them **re-parse the same file tree
independently** — each has its own `ast.parse` call site and its own directory
walk:

| Scanner | Parse site | Reader |
|---|---|---|
| `exceptions` | `scanners/exceptions.py:162` | `open(...).read()` |
| `prints` | `scanners/prints.py:42` | `open(..., errors="replace").read()` |
| `godfiles` | `scanners/godfiles.py:99,179` | `open(...).read()` |
| `magic_depth` | `scanners/magic_depth.py:170` | `path.read_text()` |
| `convergence_theater` | `scanners/convergence_theater.py:259` | `path.read_text()` |
| `subprocess_contracts` | `scanners/subprocess_contracts.py:239` | `path.read_text()` |
| `filesystem_contracts` | `scanners/filesystem_contracts.py:152,525` | `path.read_text()` |
| `test_loosening` | `scanners/test_loosening.py:429` | `open(...).read()` |

(`perf_smells` and `retired_vocab` are regex-only — `grep -c ast.parse` = 0 for
both — so they are untouched.) Because every scanner walks a **different** file
set with a **different** exclude list (see the divergent-scope note in
`scan_composition.py`'s docstring), the union is re-parsed up to 8× per run. The
sweep measured ~1.9 s of that redundancy.

The cross-scanner *join* in `espalier/scan_composition.py::report_finding_paths`
happens over the written JSON **reports**, not over trees — so the cache is
purely an in-`cmd_scan` parse-time optimization; it does **not** touch the
report-shape SoT. Confirmed no cache exists at HEAD:
`grep -rniE "ast_cache|parse_cache|lru_cache" espalier/scanners/` → empty.

**Fix — add a stdlib-only shared-parse module, then re-point the 8 call sites at
it.** New file `espalier/scanners/_ast_cache.py` (scanners are stdlib-only —
`functools`/`ast`/`os` are all stdlib, contract-safe):

```python
"""Process-local parsed-AST cache shared across scanners in one scan run.

Keyed on (resolved-path, st_mtime_ns, st_size) so a file edited between two
scan runs in the same long-lived process (the pytest suite) auto-invalidates —
no manual clear. Returns (tree_or_None, source): None tree == the file did not
parse (SyntaxError) OR could not be read, matching every scanner's current
"skip on parse failure" behavior. Decode policy is UNIFIED to errors='replace'
(see Earn the red — this is the one semantics change and the differential test
is its guard). Stdlib-only; espalier layer.
"""
from __future__ import annotations

import ast
import os

# (path, mtime_ns, size) -> (tree | None, source)
_CACHE: dict[tuple[str, int, int], tuple[ast.Module | None, str]] = {}


def parse_cached(path: str | os.PathLike[str]) -> tuple[ast.Module | None, str]:
    p = os.fspath(path)
    try:
        st = os.stat(p)
        key = (os.path.abspath(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return None, ""
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        result: tuple[ast.Module | None, str] = (None, "")
        _CACHE[key] = result
        return result
    try:
        tree: ast.Module | None = ast.parse(src, filename=p)
    except SyntaxError:
        tree = None
    result = (tree, src)
    _CACHE[key] = result
    return result
```

Then, per scanner, replace the local read+parse with the cached call. Example
for `prints.py::scan_file` (current, L38-45):

```python
def scan_file(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []
    lines = src.splitlines()
```

becomes:

```python
def scan_file(path: str) -> list[dict[str, Any]]:
    from espalier.scanners import _ast_cache
    tree, src = _ast_cache.parse_cached(path)
    if tree is None:
        return []
    lines = src.splitlines()
```

The `build_report`-family sites (e.g. `magic_depth.py::_scan_file`, L164-172)
convert the same way — swap the `path.read_text()` + `ast.parse(source)` +
`SyntaxError` guard for `tree, source = _ast_cache.parse_cached(path)` /
`if tree is None: return`.

**Earn the red.** Two RED-before / GREEN-after guards in a new
`tests/test_scanner_ast_cache.py`:
1. **Differential (behavior-preserving):** run each of the 8 scanners over the
   live repo (or a fixture tree) with the cache module present vs. a
   monkeypatched pass-through that forces a fresh `ast.parse` per call, and
   assert **byte-identical reports**. RED if the decode-policy unification
   (`errors="replace"` for the four scanners that previously used `path.read_text`
   and *skipped* undecodable files) changes any finding on the corpus; GREEN
   proves the swap is a pure speedup on the real tree. (If it REDs, that is a
   finding to resolve — cache raw bytes + per-scanner decode — not a regression
   to paper over.)
2. **Invalidation:** `parse_cached` a temp file, assert a hit; rewrite the file
   with different content (changes `st_size`/`st_mtime_ns`), assert the second
   call returns the NEW tree. RED against a path-only key; GREEN against the
   `(path, mtime_ns, size)` key.
3. **Measurement gate (recorded, not asserted):** capture `espalier scan .`
   wall-clock before and after over ≥3 runs; record the delta in this pack's
   Landing. The pack does not *assume* the ~1.9 s — it requires the number.

### Sub-task 2-A — Same-event hook dispatcher-merge (#20)

**Mechanism (grounded).** `reports/hook_latency.md` measured ~170 ms p50 /
~180 ms p95 of added wall-clock per Edit/Write, **~85% of it Python-interpreter
startup + sibling-import paid fresh 4×** (Claude Code spawns a new `python3`
per hook). A single Edit fires `PreToolUse(write_guard + plan_guard)` +
`PostToolUse(post_write_check + reflect_trigger)` = 4 spawns. The report names
**one** lever: merge same-event hooks into a single dispatcher process
(4 spawns → 2), a **claimed** ~50% cut — and immediately scopes it out as
"a structural change that breaks the one-hook-per-event model and its tests;
not worth it pre-release."

The wiring SoT is `espalier/harness_config.py::CANONICAL_HOOK_WIRING` (L17) —
one dict entry per hook script, each with `event`/`matcher`/`timeout`.
`espalier/cli.py::_build_settings_json` (L486) renders it into `.claude/settings.json`
via `_matcher_for` (L428) / `_timeout_for` (L434). Confirmed no dispatcher
exists: `ls tools/cc/hooks/ | grep -iE "dispatch"` → none (the only `dispatch`
hits are prose comments about the internal `if rc: return rc` pattern).

**Fix (design skeleton — validate, do not drop in blind).** Add two dispatcher
hook scripts under `tools/cc/hooks/` that each own one event and call the
existing per-hook check functions in order, short-circuiting on the first deny:

- `pretooluse_dispatch.py` — calls `write_guard`'s check chain
  (`check_write_edit` L260, `check_bash_*`, `check_mcp` L516) then `plan_guard`'s
  plan-gate, in that order, returning the **first** non-allow structured channel.
- `posttooluse_dispatch.py` — runs `post_write_check` then `reflect_trigger`
  (both non-blocking) in one process.

Order and short-circuit are load-bearing: write_guard must run and deny FIRST
(it is the anti-self-disable floor), and the merged process must emit exactly
the first denier's structured-channel JSON — not run both and clobber it. The
dispatch pattern already exists per-hook (`_hook_utils` truthy-zero deny
sentinel, L44-49) so the check functions compose cleanly; the new script is the
harness that sequences them. Then flip the two `PreToolUse`/`PostToolUse`
entries in `CANONICAL_HOOK_WIRING` from two script rows to one dispatcher row
each, keeping the widest matcher/longest timeout of the merged pair, and update
`GOVERNANCE_BLOCKING_HOOKS` (+ its `ci_guard.py` inline mirror) accordingly.

Because this edits `tools/cc/hooks/*.py`, run `python3 scripts/sync_vendor_cc.py`
(the `_vendor/cc` mirror is byte-parity-pinned — never hand-edit it). Because it
edits the wiring SoT, regenerate `.claude/settings.json` via `espalier init`
(the live file is gitignored + guard-protected — regeneration, not a hand-edit,
is the sanctioned path).

**Earn the red.** In `tests/test_hooks.py` (or a new
`tests/test_pretooluse_dispatch.py`): feed the dispatcher a payload write_guard
must DENY (a write into a protected zone) **followed by** an input plan_guard
would also flag, and assert the dispatcher returns write_guard's structured deny
verdict **and stops** (plan_guard's verdict never overwrites it). RED against a
naive "run both, return last" merge (loses the first deny); GREEN against the
short-circuit dispatcher. Plus the same **before/after wall-clock** measurement
gate as 1-A: record the real merged-spawn latency — the ~50% is CLAIMED and this
pack must produce the number before the merge is judged worth keeping.

## Scope (out)

- **Item #17 — migrating the measured ~170 ms footprint into
  `docs/HOOK_ASSUMPTIONS.md`.** Named in the same `Done/TP-340` scope-out block
  as #20, but it is a **doc-parity content migration**, not a perf lever — a
  separate concern with its own contract. Not bundled here.
- **Item #21 — a committed link-checker over gitignored `reports/`.** Also from
  `TP-340`'s scope-out; it is tooling/infra, unrelated to latency. Separate pack.
- **`espalier/scanners/freshness.py:418`'s `ast.parse`.** It belongs to the
  `freshness` scanner (a different command surface), not the `cmd_scan` ten, so
  folding it into the shared cache would widen 1-A's blast radius for no
  `espalier scan` win. Convert only if/when freshness runs inside `cmd_scan`.
- **`strengthen.py`'s `ast.parse`.** Different command (`/strengthen`), not part
  of the scan run; out of the cache's process scope.
- **Parallelizing hooks instead of merging them.** `reports/hook_latency.md`
  notes that IF Claude Code runs same-event hooks in parallel the real
  wall-clock is already the max (~93 ms), not the sum — but that is a
  platform-behavior assumption we do not control and cannot pin. The dispatcher
  merge is the lever we *can* own; parallelism is out of scope.
- **Caching across separate `espalier scan` invocations (on-disk cache).** The
  in-process dict dies with `cmd_scan` by design; a persistent cache adds
  invalidation surface (a stale on-disk tree is a correctness footgun) for a
  command run at most a few times per session. Deliberately not built.

## Affected symbols

### Changed-semantics
- `espalier/scanners/prints.py::scan_file` — read+parse → `_ast_cache.parse_cached` (1-A)
- `espalier/scanners/exceptions.py::scan_file` — same (1-A)
- `espalier/scanners/godfiles.py::build_report` — parse sites L99/L179 → cache (1-A)
- `espalier/scanners/test_loosening.py::scan_file` — same (1-A)
- `espalier/scanners/magic_depth.py::_scan_file` — same (1-A)
- `espalier/scanners/convergence_theater.py::build_report` — parse site L259 → cache (1-A)
- `espalier/scanners/subprocess_contracts.py::_scan_file` — parse site L239 → cache (1-A)
- `espalier/scanners/filesystem_contracts.py::_scan_file` — parse sites L152/L525 → cache (1-A)
- `espalier/harness_config.py::CANONICAL_HOOK_WIRING` — collapse two PreToolUse + two PostToolUse rows into one dispatcher row each (2-A)
- `espalier/harness_config.py::GOVERNANCE_BLOCKING_HOOKS` — remap write_guard/plan_guard blocking-event ownership onto the dispatcher (2-A)
- `espalier/cli.py::_build_settings_json` — render the merged dispatcher wiring (2-A)

### Added-paths
- `espalier/scanners/_ast_cache.py::parse_cached` — shared parsed-tree cache (1-A)
- `tests/test_scanner_ast_cache.py` — differential + invalidation earn-red (1-A)
- `tools/cc/hooks/pretooluse_dispatch.py` — merged PreToolUse dispatcher (2-A)
- `tools/cc/hooks/posttooluse_dispatch.py` — merged PostToolUse dispatcher (2-A)
- `espalier/_vendor/cc/hooks/pretooluse_dispatch.py` / `posttooluse_dispatch.py` — byte-mirrors via `sync_vendor_cc.py` (2-A)
- `tests/test_pretooluse_dispatch.py` — short-circuit deny earn-red (2-A)

## Pass criteria
- **Earn-red 1-A (differential):** the 8-scanner cache-vs-fresh-parse comparison
  is byte-identical on the corpus; the decode-policy unification changes no
  finding. RED if any report diverges (resolve, don't paper over).
- **Earn-red 1-A (invalidation):** `parse_cached` returns the NEW tree after a
  file's size/mtime changes; REDs against a path-only key.
- **Measurement 1-A:** `espalier scan .` before/after wall-clock recorded in
  Landing (≥3 runs each) — the ~1.9 s is confirmed by number, not assumed.
- **Earn-red 2-A:** the dispatcher returns write_guard's deny verdict AND
  short-circuits; REDs against a run-both-return-last merge.
- **Measurement 2-A:** merged per-edit wall-clock recorded in Landing; the ~50%
  claim is confirmed-or-refuted by number before the merge is kept.
- **Mirror parity:** 2-A runs `python3 scripts/sync_vendor_cc.py`;
  `tests/test_vendor_cc_parity.py` byte-parity GREEN. 1-A touches no
  `.claude/{agents,commands,skills}/` and no `tools/cc/` — no mirror sync needed.
- **Wiring contracts (2-A):** `tests/test_hook_event_contracts.py`,
  `tests/test_hook_matcher_precision.py`, `tests/test_ci_guard.py` updated to the
  merged model and GREEN.
- **Full gate:** `pytest -q` green; `ruff check .` clean; `python3 -m espalier
  audit .` 0/0; **no `TP-360` (or any `TP-NNN`) literal in any shipped surface
  touched** — this pack edits `espalier/` and `tools/cc/` (both scanned except
  `_vendor/`); the new `_ast_cache.py` and dispatcher scripts must carry no
  pack-id.

## Files touched
- **New:** `espalier/scanners/_ast_cache.py` (1-A); `tests/test_scanner_ast_cache.py`
  (1-A); `tools/cc/hooks/pretooluse_dispatch.py`, `tools/cc/hooks/posttooluse_dispatch.py`,
  `tests/test_pretooluse_dispatch.py` (2-A).
- **Modified:** the 8 scanner modules above (1-A); `espalier/harness_config.py`,
  `espalier/cli.py::_build_settings_json` (2-A); the three hook-wiring contract
  test files (2-A).
- **Mirrors (regenerated, never hand-edited):** `espalier/_vendor/cc/hooks/*`
  via `scripts/sync_vendor_cc.py` (2-A only).
- **Unmodified on purpose:** `espalier/scan_composition.py` (the join reads
  reports, not trees — the cache never touches it); `perf_smells.py`,
  `retired_vocab.py` (regex-only, no `ast.parse`); `freshness.py`,
  `strengthen.py` (different command surfaces — see Scope out).

## Sub-task ordering
1. **1-A-1** — add `espalier/scanners/_ast_cache.py`; write the invalidation +
   differential earn-red tests → observe RED (path-only key fails invalidation)
   → confirm the module GREENs the invalidation test. Checkpoint:
   `pytest tests/test_scanner_ast_cache.py -q`.
2. **1-A-2** — re-point the 8 scanner parse sites at `parse_cached`, one module
   at a time; after each, run the differential assertion. Checkpoint:
   `pytest tests/test_scanners.py tests/test_scanner_ast_cache.py -q` +
   `espalier scan .` produces identical `scan_summary.json` counts.
3. **1-A-3** — record before/after `espalier scan .` wall-clock (≥3 runs).
   Checkpoint: number captured for Landing. **1-A can land here** if 2-A is
   deferred/dropped.
4. **2-A-1** — add the two dispatcher scripts; write the short-circuit deny
   earn-red → observe RED against a run-both-return-last stub → GREEN against the
   short-circuit dispatcher. Checkpoint: `pytest tests/test_pretooluse_dispatch.py -q`.
5. **2-A-2** — flip `CANONICAL_HOOK_WIRING` + `GOVERNANCE_BLOCKING_HOOKS` +
   `_build_settings_json` to the merged model; update the three wiring contract
   tests; `python3 scripts/sync_vendor_cc.py`; regenerate `.claude/settings.json`
   via `espalier init`. Checkpoint: `pytest tests/test_hook_event_contracts.py
   tests/test_hook_matcher_precision.py tests/test_ci_guard.py
   tests/test_vendor_cc_parity.py -q`.
6. **2-A-3** — record before/after per-edit wall-clock; confirm-or-refute the
   ~50% claim. Checkpoint: number captured for Landing.
7. **final** — full `pytest -q` + `ruff check .` + `python3 -m espalier audit .`;
   grep the touched shipped surfaces for any `TP-` literal; stamp Landing.

## Estimated effort
- 1-A-1 ~40m · 1-A-2 ~1.5h (8 call sites + per-site differential) · 1-A-3 ~20m
  · 2-A-1 ~1h · 2-A-2 ~2h (wiring SoT + 3 contract tests + mirror + settings
  regen) · 2-A-3 ~20m · verify+land ~30m.
  **Total ≈ 6.5 h** (≈ 2.5 h for 1-A alone if 2-A is split off or dropped).

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) 1-A invalidation reds on a path-only cache key and the
  differential reds if the decode-policy unification shifts any finding; 2-A deny
  short-circuit reds against a run-both-return-last merge. Both sub-tasks
  additionally gate on a RECORDED before/after wall-clock — the ~1.9 s (1-A) is
  measured, the ~50% (2-A) is claimed and must be confirmed by number.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (row #34 + #20).
  Neither lever gates the OSS launch. **Reco: DEFER**, and split — 1-A is the
  stronger half (measured payoff, contained blast radius, real correctness guard)
  and could land alone in a maintenance window; 2-A is borderline-DROP — its
  payoff is unmeasured, its blast radius large, and `reports/hook_latency.md`
  already judged it "not worth it pre-release" for a sub-200 ms cost. Keep 2-A
  packed only as a tracked home so the "only real lever" idea stops re-leaking;
  do not execute it without a fresh measurement that changes the report's verdict.
