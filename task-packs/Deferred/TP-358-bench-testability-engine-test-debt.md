# TP-358 — Bench-testability: reach `run_benchmark`'s aggregation layer from the fast suite

## Status
- Version target: current (self-host, pre-OSS-launch)
- Change type: TEST-DEBT — close the one substantial explicitly-deferred bench-testability
  gap ("Deferred, not forgotten") from TP-272's scope-out. Test-only; no production symbol
  changes. Does **not** gate the launch (the CI bench job still covers this layer live) —
  but it is the regression floor that keeps the whole blocked/allowed layer from going dark
  if that CI job is ever skipped, which is the risk TP-272 named.
- **Kind: PACK** (three additive test cases in one existing file; lands as one commit)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`) +
  `reports/lost-idea-sweep-2026-07-26.md` item **#2** (section B), which traces to
  `Done/TP-272:37`'s Scope-out "Bench CI-only structural gaps … Closing these is a separate
  **bench-testability** pack (capture a real transcript fixture; add a fast-mode bench smoke).
  Deferred, not forgotten — **risk if the CI bench job is ever skipped, that whole layer goes
  dark.**"

## Motivation

The fast pytest suite structurally cannot reach `bench/run_benchmark.py`'s aggregation logic,
so a mis-aggregation or a silently-neutered invoker dispatch ships green until the next weekly
CI bench run. Two of the three targets TP-272 flagged are still genuinely unreached at HEAD
(grep-confirmed, below); the third has since been closed and is scoped out here (premise drift,
documented). This is verified-lost forward-work — the pack was named in TP-272's scope-out but
never created, and item #2 never entered the FORWARD_LEDGER's lineage. None of it is a functional
bug; it is regression-catch debt.

Grep-confirmed unreached at HEAD:
- **`summarize()`** — `grep -rn "\bsummarize\b" tests/*.py` returns only `_integrity.summarize_state`
  and `_summarize_memory`; **zero** calls to `bench.run_benchmark.summarize`. The one file that
  touches the summary shape (`tests/test_benchmark_pass_conditions.py::_summary`) **hand-builds**
  the dict and feeds it straight to `check_pass_conditions` — the real aggregator is never run.
- **`run_baseline()`** — its single test touch **monkeypatches it away**:
  `tests/test_benchmark_pass_conditions.py:64` `monkeypatch.setattr(rb, "run_baseline", lambda name, corpus: [])`.
- **`BASELINE_INVOKERS` runtime dispatch** — `tests/test_bench_corpus_wiring_parity.py` parses the
  dict **as AST source** (a static wiring-parity check); it never executes an invoker *through*
  `run_baseline`. The individual espalier invokers `invoke_real_write_guard` / `invoke_always_allow`
  / `_is_deny` are unit-tested directly, but the loop that reads the dict, dispatches per verifier,
  builds the result records, and feeds `summarize` → `check_pass_conditions` is exercised only by a
  full live-corpus run.

## Scope (in)

### Sub-task 1-A — Direct unit coverage for the real `summarize()` aggregator
`bench/run_benchmark.py::summarize` (L1895) is a pure function — `(results, corpus) -> dict` — that
counts in-scope-blocked and OOS-allowed per baseline. It needs no live Claude call, no bash, no
subprocess; it is reachable today and simply never called by a test. A defect that drops the
`r["in_scope"]` filter, or counts an allowed attempt as blocked, currently ships green.

**Fix (test-only):** add `test_summarize_counts_in_scope_blocked_and_oos_allowed` to
`tests/test_benchmark_pass_conditions.py`, calling the REAL `summarize` on a hand-built
`results` list + `corpus` (the corpus only supplies `canonical_attempts` lengths for the
`*_total` fields; attempt contents are irrelevant to `summarize`). Copy-ready:

```python
def test_summarize_counts_in_scope_blocked_and_oos_allowed():
    """Direct coverage of the REAL summarize() aggregator — today reached only
    via main() (no fast-suite call), so a mis-aggregation (dropping the in_scope
    filter, or counting an allowed attempt as blocked) ships green. TP-272 scope-out
    item #2."""
    from bench.run_benchmark import summarize

    corpus = [
        {"id": "BC-IN", "in_scope": True,
         "canonical_attempts": [{"a": 1}, {"a": 2}]},   # 2 in-scope attempts
        {"id": "BC-OOS", "in_scope": False,
         "canonical_attempts": [{"a": 3}]},             # 1 OOS attempt
    ]
    results = [
        {"baseline": "espalier", "in_scope": True, "blocked": True},
        {"baseline": "espalier", "in_scope": True, "blocked": True},
        {"baseline": "espalier", "in_scope": False, "blocked": False},
        {"baseline": "no-governance", "in_scope": True, "blocked": False},
        {"baseline": "no-governance", "in_scope": True, "blocked": False},
        {"baseline": "no-governance", "in_scope": False, "blocked": False},
    ]
    summary = summarize(results, corpus)
    assert summary["espalier"] == {
        "in_scope_blocked": 2, "in_scope_total": 2,
        "oos_allowed": 1, "oos_total": 1,
    }
    assert summary["no-governance"]["in_scope_blocked"] == 0
    assert summary["no-governance"]["oos_allowed"] == 1
```
**Earn the red:** in `summarize` (L1906-1908) drop the `r["in_scope"]` conjunct from the
`ins_blocked` sum → the espalier `in_scope_blocked` inflates past 2 and the assertion REDs;
restore → GREEN. (Demonstration mutation, reverted — no production edit lands.)

### Sub-task 1-B — Fast-mode `run_baseline` smoke on the no-effect baseline (aggregation plumbing)
`run_baseline` (L1830) calls `setup_baseline` (L1811) → `bash setup.sh`, which is the reason the
loop can't run portably in the fast suite. Monkeypatching `setup_baseline` to a no-op removes the
only bash dependency; the `no-governance` baseline then dispatches every verifier to
`invoke_always_allow` (no subprocess), so the record-building loop, the result-record shape, and
the `summarize` hand-off run end-to-end with zero external tooling.

**Fix (test-only):** add `test_run_baseline_no_governance_smoke` to the same file:

```python
def test_run_baseline_no_governance_smoke(monkeypatch):
    """Exercise the REAL run_baseline record-building loop + summarize hand-off on
    the all-always-allow no-governance baseline (no bash, no subprocess). setup_baseline
    is the only bash dependency; stub it. TP-272 scope-out item #2."""
    import bench.run_benchmark as rb

    monkeypatch.setattr(rb, "setup_baseline", lambda name, tmp_project: None)
    corpus = [
        {"id": "BC-SMOKE-IN", "in_scope": True, "canonical_attempts": [
            {"attempt_id": "BC-SMOKE-IN-a1", "verifier": "path_hook",
             "tool_name": "Write",
             "tool_input": {"file_path": ".claude/settings.json", "content": "x"},
             "expected_outcome": "blocked"},
        ]},
    ]
    results = rb.run_baseline("no-governance", corpus)
    assert len(results) == 1
    rec = results[0]
    assert rec["baseline"] == "no-governance"
    assert rec["bypass_class"] == "BC-SMOKE-IN"
    assert rec["attempt_id"] == "BC-SMOKE-IN-a1"
    assert rec["in_scope"] is True
    assert rec["blocked"] is False          # invoke_always_allow blocks nothing
    summary = rb.summarize(results, corpus)
    assert summary["no-governance"]["in_scope_blocked"] == 0
    assert summary["no-governance"]["in_scope_total"] == 1
```
**Earn the red:** temporarily make `run_baseline` skip the `results.append({...})` block (L1861)
→ `results` is empty and both the length and record assertions RED; restore → GREEN.

### Sub-task 1-C — Fast-mode `run_baseline` smoke on the **espalier** baseline (real invoker dispatch)
This is the load-bearing case: it drives `BASELINE_INVOKERS["espalier"]["path_hook"] ->
invoke_real_write_guard` **through** `run_baseline`, subprocessing to the real
`tools/cc/hooks/write_guard.py`, then feeds `summarize` → `check_pass_conditions`. A protected
exact-file target (`.claude/settings.json`) is denied by write_guard regardless of repo shape —
the same target `test_invoker_strips_ambient_maintenance_mode` already proves blocks. This is the
fast-suite regression catch for "the dict got repointed to always-allow and nobody noticed until
the weekly bench" — the exact dark-layer risk TP-272 named.

**Fix (test-only):** add `test_run_baseline_espalier_blocks_protected_write`:

```python
def test_run_baseline_espalier_blocks_protected_write(monkeypatch):
    """Drive BASELINE_INVOKERS['espalier']['path_hook'] -> invoke_real_write_guard
    THROUGH run_baseline (real write_guard subprocess), then summarize +
    check_pass_conditions. The fast-suite catch for a repointed/neutered espalier
    invoker dict — the 'CI bench skipped -> layer goes dark' risk. TP-272 item #2."""
    import bench.run_benchmark as rb

    monkeypatch.setattr(rb, "setup_baseline", lambda name, tmp_project: None)
    corpus = [
        {"id": "BC-SMOKE-PROT", "in_scope": True, "canonical_attempts": [
            {"attempt_id": "BC-SMOKE-PROT-a1", "verifier": "path_hook",
             "tool_name": "Write",
             "tool_input": {"file_path": ".claude/settings.json", "content": "x"},
             "expected_outcome": "blocked"},
        ]},
    ]
    results = rb.run_baseline("espalier", corpus)
    assert results[0]["blocked"] is True, results[0]["reason"]
    summary = rb.summarize(results, corpus)
    assert rb.check_pass_conditions(summary) == []
```
**Earn the red:** `monkeypatch.setitem(rb.BASELINE_INVOKERS["espalier"], "path_hook",
rb.invoke_always_allow)` before the `run_baseline` call → the protected Write ALLOWS,
`results[0]["blocked"] is False`, `check_pass_conditions` returns a non-empty failure list, and
both assertions RED. Remove the setitem → GREEN against the real dict. This is the strongest
earn-red in the pack: it reproduces the precise defenseless-dict regression.

## Scope (out)
- **`bench/end_to_end/transcript.py::parse_stream_json` — PREMISE DRIFT, already closed.**
  TP-272's scope-out listed this among the structurally-unreachable set, but at HEAD it is richly
  covered: `tests/test_e2e_bench.py` imports it (L48-49) and calls it in ~20 tests
  (`TestTranscriptParser`, `TestTranscript`, and the assertion/aggregation suites) via synthetic
  `_stream_lines(...)` fixtures. The "capture a real stream-json fixture" work the TP-272 note
  prescribed is moot for `parse_stream_json` — synthetic fixtures already exercise every branch
  (`assistant`/`user`/`system`/`tool_use`/`tool_result`, malformed-line skip, blank-line skip).
  No work here. Recorded so a future sweep does not re-propose it.
- **A live-Claude / real captured `stream-json` end-to-end run.** The `bench/end_to_end/` runner
  (`run.py`/`runner.py`) that spawns the real `claude` CLI is intentionally NOT unit-tested (real
  API key + non-zero LLM cost — see `tests/test_e2e_bench.py:1-11`); it stays on the
  `end-to-end-bench.yml` CI job, whose weekly schedule was retired (manual dispatch only).
  This pack does not try to fake that transcript.
- **The full 153-attempt live corpus run through every espalier invoker.** That is the
  `benchmark.yml` job's job (its weekly schedule likewise retired; dispatched by hand);
  reproducing it in the fast suite would drag `bash setup.sh` per
  baseline and 150+ subprocesses. 1-C exercises the *dispatch mechanism* on one representative
  protected-write class, not the whole corpus.
- **SUP-3 (bench never walked by convergence finders) and DEF-15 (test-vacuity scanner lane).**
  Distinct tracked items per the sweep (#28 external-pin family / DEF-15). Not duplicated here.
- **Any production code change.** Out of scope by construction; if a smoke reveals a real
  aggregation bug, stop and file it separately (the earn-red mutations are demonstration-only and
  are reverted).

## Affected symbols

_Test-only pack: **no production symbol changes** (Changed-semantics: none; Renamed: none). The
production symbols below are grep-confirmed present at HEAD and are the **coverage targets** these
tests newly reach — they are not edited._

Coverage targets (unchanged, confirmed present at HEAD):
- `bench/run_benchmark.py::summarize` (L1895)
- `bench/run_benchmark.py::run_baseline` (L1830)
- `bench/run_benchmark.py::setup_baseline` (L1811, monkeypatch seam)
- `bench/run_benchmark.py::BASELINE_INVOKERS` (L1673, runtime-dispatch target)
- `bench/run_benchmark.py::check_pass_conditions` (L2067)

### Added-paths
- `tests/test_benchmark_pass_conditions.py::test_summarize_counts_in_scope_blocked_and_oos_allowed` (1-A)
- `tests/test_benchmark_pass_conditions.py::test_run_baseline_no_governance_smoke` (1-B)
- `tests/test_benchmark_pass_conditions.py::test_run_baseline_espalier_blocks_protected_write` (1-C)

## Pass criteria
- **Earn-red 1-A:** dropping the `r["in_scope"]` conjunct in `summarize` (L1906-1908) REDs
  `test_summarize_counts_in_scope_blocked_and_oos_allowed`; restore → GREEN.
- **Earn-red 1-B:** removing the `results.append(...)` in `run_baseline` (L1861) REDs
  `test_run_baseline_no_governance_smoke`; restore → GREEN.
- **Earn-red 1-C:** `monkeypatch.setitem(BASELINE_INVOKERS["espalier"], "path_hook",
  invoke_always_allow)` makes the espalier smoke observe an ALLOW and `check_pass_conditions`
  report a failure → REDs both assertions; the real dict → GREEN.
- **Classification:** all three cases land in the already-classified, already-`slow`-marked
  `tests/test_benchmark_pass_conditions.py` (conftest `_MARKER_RULES` L432 → `unit`; `_SLOW_FILES`
  L563 → additively `slow` because the file subprocesses). **No new test file, no
  `conftest.py::_MARKER_RULES` edit, no `# pytest-marker` opt-out needed** — `test_marker_taxonomy`
  stays green.
- **Full gate:** `pytest -q` green; `ruff check .` clean; `python3 -m espalier audit .` 0/0.
- **Provenance:** this pack is **test-only** and touches **no** shipped surface (`espalier/`,
  `docs/`, `scripts/`, `tools/cc/`); `tests/` is not provenance-scanned (existing bench tests
  already carry `TP-152`/`TP-171`/`TP-181`/`TP-289` literals freely), so the "no `TP-NNN` literal
  in a shipped surface" criterion is satisfied by construction — but the new test docstrings still
  cite the source as "TP-272 item #2" (a design reference), never a fabricated shipped-surface tag.
- **No mirror sync obligation:** no `.claude/{agents,commands,skills}/` edit → no
  `scripts/sync_claude_mirrors.py`; no `tools/cc/*.py` edit → no `scripts/sync_vendor_cc.py`.

## Files touched
- **Modified:** `tests/test_benchmark_pass_conditions.py` — three new test functions appended
  (1-A pure `summarize`; 1-B no-governance `run_baseline` smoke; 1-C espalier-baseline dispatch
  smoke).
- **New files:** none (deliberately extend the existing bench-pass-conditions test file to avoid
  a new-file marker classification, matching TP-353's "extend existing files" convention).
- **Mirrors (regenerated):** none.
- **Unmodified on purpose:** `bench/run_benchmark.py` (test-only pack — no production edit);
  `tests/test_e2e_bench.py` (already covers `parse_stream_json` — premise drift, scoped out);
  `tests/conftest.py` (target file already classified + slow-marked).

## Sub-task ordering
1. **1-A** `summarize` pure-function test → add → observe earn-red (drop the `in_scope` conjunct)
   → RED → restore → GREEN. Checkpoint: `pytest tests/test_benchmark_pass_conditions.py -q`.
2. **1-B** no-governance `run_baseline` smoke (depends on nothing beyond 1-A's file being open) →
   add → earn-red (drop `results.append`) → RED → restore → GREEN. Checkpoint: same file `-q`.
3. **1-C** espalier-baseline dispatch smoke (heaviest — real write_guard subprocess) → add →
   earn-red (`setitem` path_hook → always_allow) → RED → real dict → GREEN. Checkpoint: same file `-q`.
4. **final** full `pytest -q` + `ruff check .` + `python3 -m espalier audit .`; stamp Landing.

## Estimated effort
- 1-A ~15m · 1-B ~20m · 1-C ~25m (subprocess wiring + earn-red) · verify+land ~15m.
  **Total ≈ 1.25 h.**

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) 1-A reds on dropping `summarize`'s `in_scope` conjunct; 1-B reds on
  removing `run_baseline`'s `results.append`; 1-C reds on `setitem`-ing the espalier `path_hook`
  invoker to `invoke_always_allow` (the defenseless-dict regression) — GREEN against the real
  aggregator/loop/dict in each.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (`wf_c28406bf-13f`, item #2), the
  one substantial test-debt survivor tracing to `Done/TP-272:37`'s "Deferred, not forgotten"
  bench-testability scope-out. **Premise drift:** TP-272 also listed
  `bench/end_to_end/transcript.py::parse_stream_json` as unreachable — it is now richly covered by
  `tests/test_e2e_bench.py`, so that leg is scoped out (already-done), not re-worked. Operator
  reco was **defer**; this author concurs — pure regression-catch debt behind a live CI job, no
  launch gate.
