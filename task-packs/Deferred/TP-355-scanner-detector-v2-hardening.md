# TP-355 — Scanner / detector v2 hardening (six deferred detector follow-ups)

## Status
- **⚠ MAINTENANCE-MODE — launch with `ESPALIER_MAINTENANCE_MODE=1 claude`.** 5 of the 6
  sub-tasks (6-A/6-C/6-D/6-E/6-F) edit write_guard-protected zones — `tools/cc/` and
  `espalier/` (both in `PROTECTED_PREFIXES`, `tools/cc/hooks/_protected_zones.py:41-51`);
  only 6-B is test-only (`tests/`, unprotected). Without the flag `write_guard` denies the
  protected-zone writes mid-session. Set it in the parent shell BEFORE launch (mid-session
  `export` does not reach running hooks). Parity with sibling TP-369.
- Version target: current (self-host, pre-OSS-launch)
- Change type: FIX/HARDENING — six independently-deferred **v2** enhancements to
  already-shipped detectors, each surfaced (un-tracked + un-done) by the pre-flip
  lost-idea sweep. Three widen false-positive surface (the exact v1 deferral reason)
  and must be calibrated against the live population before landing; one is
  conditional on an FP=0 precondition; two are low-risk. **None gate the OSS flip.**
- **PRE-FLIP vs DEFER fork (operator's elect — this pack does NOT resolve it):** the body is
  DEFER-recommended (post-flip calibration), but `FORWARD_LEDGER.md:78` tags this row
  `PRE-FLIP` (operator-elected to land before the public flip). If the operator elects
  pre-flip, the FP-safe subset is **6-B / 6-D / 6-F** (additive or comment-only — no live-FP
  surface widened); **6-A / 6-C / 6-E MUST stay post-flip** — each widens the false-positive
  surface and needs the live-population calibration gate before landing. State the fork; the
  elect is the operator's.
- **Kind: PACK** (six independent sub-tasks; may land as one commit or be cherry-picked)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`,
  100 agents / 6.0M tokens) + `reports/lost-idea-sweep-2026-07-26.md` section C rows
  #6, #11, #13, #31, #33, #39 — each citing the Done-pack/report where the deferral
  was originally made.

## Motivation

The lost-idea sweep read 55% of its 87 candidate references as already
tracked/done/captured; the genuine survivors "never entered the ledger's lineage —
the seam a self-consistency audit structurally can't catch." Six of those survivors
are the same shape: a detector shipped with a deliberately-narrow v1 scope, its
`v2` widening scoped OUT with a real reason, and the follow-up row never created.

They cluster because they share one risk profile — **each widens what a detector
sees, and widening detection widens the false-positive surface.** That is why v1
stopped where it did, and why this pack is DEFER-recommended: it is post-flip
calibration work, not launch-blocking. Grouping them lets one calibration pass
(run each widened detector against the live tree, confirm FP=0 or triage each hit)
amortize across all six rather than repeating per-item.

Read this pack by which sub-tasks are safe (6-B, 6-D, 6-F: additive or comment-only)
versus which need a live-population calibration gate before they can land
(6-A, 6-C, 6-E: FP-surface widenings).

## Scope (in)

### Sub-task 6-A — concept-duplication detector v2: extract dict KEYS + nested tuples (`sister_site_probe._string_elements`)
`tools/cc/sister_site_probe.py::_string_elements` (L336-365) feeds the
concept-overlap detector (`_build_concept_overlaps`, L447) the str-element set of a
module-scope literal collection. It accepts **only** str-homogeneous `Set`/`List`/
`Tuple` literals (and their `set/frozenset/tuple/list(...)` call forms); a `dict`
literal returns `None` and is dropped from element-wise comparison:

```python
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return None          # a dict returns None here — never compared
    elems: set[str] = set()
    for e in node.elts:
```

So a concept expressed as a dict's KEYS — e.g. a `SUFFIX_TO_LANGUAGE = {".py":
"python", ...}` mapping whose key-set duplicates a sibling extension SET under a
different name — is invisible to the concept-overlap arm. Ledger §2.15 / DEF-20
covers only the ALIAS arm (`_collect_alias_misses`); this concept-EXTRACTION arm was
never widened (source `Done/TP-276:145`).

**Fix (`tools/cc/sister_site_probe.py`, then vendor-sync):** teach `_string_elements`
to also return the str KEY-set of an `ast.Dict` whose keys are all str constants
(values ignored — the concept is the key vocabulary). Guard it exactly as the
existing arms: any non-str / non-constant key → `None`; empty → `None`. Keep
`_is_interesting_constant` unchanged (it already returns `True` for `ast.Dict`, L380,
so dict sites are already collected — only the element extraction is blind).

```python
    node = value
    if isinstance(node, ast.Call):
        ...                                  # existing set/frozenset/tuple/list arm
        node = node.args[0]
    if isinstance(node, ast.Dict):           # NEW: str-homogeneous dict keys
        keys: set[str] = set()
        for k in node.keys:
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                return None                  # a **kwargs spread key is None
            keys.add(k.value)
        return frozenset(keys) if keys else None
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return None
```
The sweep also names "pack_manifest's inline for-loop tuple" — an in-comprehension
tuple, NOT a module-scope literal, so it is an `ast.Tuple` inside a `For`/`ListComp`
body that `_collect_constant_sites` never visits (it walks `tree.body` top-level
assignments only). Widening the collector to comprehension bodies is a **separate,
larger** change with much higher FP risk — scope it OUT (see below); this sub-task
delivers only the dict-KEY arm.

**Earn the red:** add a synthetic fixture (extend `tests/test_sister_site_probe_synthetic.py`)
with two module-scope constants under different names — a `frozenset({...})` of ≥4
extensions and a `dict` whose keys are the same extensions — and assert
`_build_concept_overlaps` reports a cluster spanning both. RED at HEAD (dict → `None`
→ dropped → no cluster); GREEN after the dict-key arm. Add a negative: a dict with a
non-str key (`{1: "x"}`) must still return `None` (no over-fire).

### Sub-task 6-B — promote `nondiscriminating_hook_assert` advisory → hard gate, GATED on live FP=0 (`test_loosening`)
`espalier/scanners/test_loosening.py` emits the `nondiscriminating_hook_assert`
finding (rule declared L14, appended L481-485) but the scanner is **purely
advisory**: `main()` returns `0` unconditionally (L568) and no CI leg, stop-gate, or
self-scan test fails on the finding. The rule's own docstring calls it "calibrated to
0 false positives over the live tree" (L21-24). The follow-up (source `Done/TP-303:72`):
wire it into a hard gate — but ONLY after the live-tree FP rate is *demonstrably* 0.

**Precondition check (do FIRST, no code change unless it passes):** run
`test_loosening.scan_repo(REPO_ROOT)`, filter `results[].findings` to
`rule == "nondiscriminating_hook_assert"`, and confirm the live count is `0`. If any
hit exists, triage each as a true positive (a real returncode-only deny test → fix
the test, not the gate) before the gate can land. If a hit is a genuine FP, the rule
is NOT ready for promotion → **stop 6-B**, record the FP in this pack's Landing, and
leave the rule advisory (do not weaken the rule to force FP=0 — that is the
gate-weakening antipattern CP-GATEWEAKEN exists to catch).

**Fix (test-only, once precondition passes):** add a self-clean regression test
patterned on the existing live-scan self-test
`tests/test_scanner_test_loosening.py::test_fixture_skipped_by_live_scan` (L54-66):

```python
def test_live_tree_has_no_nondiscriminating_hook_assert() -> None:
    """Hard gate (TP-303 follow-up): the live tree must stay clean of
    returncode-only deny tests. Precondition-verified FP=0 before landing."""
    report = scn.scan_repo(str(REPO_ROOT))
    hits = [r for row in report["results"] for r in row.get("findings", [])
            if r["rule"] == "nondiscriminating_hook_assert"]
    assert hits == [], (
        "a returncode-only hook-deny test landed; assert on the "
        "permissionDecision channel, not .returncode"
    )
```
The pytest suite IS the CI gate (`harness-guard.yml`), so a failing self-clean test
blocks merge — that is the "hard gate" without touching the scanner's advisory exit
contract (leave `main()` returning 0; other advisory rules must not become gates).

**Earn the red:** the self-clean test REDs against a tmp/fixture tree seeded with one
returncode-only deny test (reuse the positive fixture the existing suite already
builds at L203-244); GREEN against the live tree once the precondition confirms FP=0.

### Sub-task 6-C — teach the class-1 duplicate detector to see index-row duplication (`memory_sort_audit._audit_duplicates`)
`tools/cc/memory_sort_audit.py::_audit_duplicates` iterates the auto-memory entry
FILES and skips the index (L289-291):

```python
    for entry in sorted(auto_dir.glob("*.md")):
        if entry.name == "MEMORY.md":
            continue  # the index, not an entry
        if _POINTER_LINE_RE.search(_read(entry)):
```

So a lesson that lives **only as an index ROW** in `MEMORY.md` (no standalone backing
file — e.g. after a file prune leaves a still-live, non-pointer row) can duplicate a
committed twin and never be flagged: there is no file for the loop to visit. TP-315
widened the twin-SET to monolithic docs (`_MONOLITHIC_TWINS`, L178) but not this skip
(source `Done/TP-308:181`).

**Fix (`tools/cc/memory_sort_audit.py`, then vendor-sync):** after the file loop,
parse `MEMORY.md`'s index rows and run each against the same `twins` set. Extract the
per-row link-target slug (a row linking `slug.md` yields `slug`) — the same slug the file arm
compares — and skip rows already collapsed to a pointer (`_POINTER_MARKERS` in the row
text: "Migrated to the repo" / "Canonized in the repo"). Reuse `_same_subject` and the
existing `twins` list; append the same `[duplicated-across-stores]` finding string with
an `(index row)` qualifier so the finding names the row, not a phantom file.

**Casefold BOTH sides (pointer-marker mismatch):** `_POINTER_MARKERS`
(`memory_sort_audit.py:85`) is capitalized (`"Migrated to the repo"` / `"Canonized in the
repo"`) and the file-arm `_POINTER_LINE_RE` anchors that casing, but the live index rows
write the pointer **lowercase** ("migrated to the repo" / "canonized in the repo" — 46 such
rows in the live `MEMORY.md`, 0 capitalized). A case-sensitive pointer check against index
rows would skip NONE of them → every collapsed row re-fires. The new index-row arm MUST
casefold both the row text and the markers before the pointer test.

**FP note (why this is deferred, not bolted on):** index rows carry far noisier slugs
than filenames (titles, dates, `[[wiki]]` refs), so the `_same_subject` token-overlap
match will fire more loosely. This sub-task MUST re-run the FP=0 calibration against
the live `MEMORY.md` (the sweep's own excerpt shows ~40 pointer rows + ~15 live rows)
and extend the exemption set (never lower `_MIN_SHARED_TOKENS`) — the same discipline
`_GENERIC_HEADINGS` (L161) already encodes for the monolithic-doc arm.

**Earn the red:** extend `tests/test_memory_sort_audit.py` with a fixture auto-store
whose `MEMORY.md` contains a non-pointer row titled "git checkout nukes uncommitted work"
linking `gone.md` (no `gone.md` file) while `docs/SHARP_EDGES.md` carries the twin heading. RED at HEAD
(index skipped → no finding); GREEN after (index-row finding). Negative: a row already
carrying "Canonized in the repo" produces no finding.

### Sub-task 6-D — retire the dangling `FM-21` id + correct the fixtures-ignore comment (`ruff_config_contract.py`)
`espalier/ruff_config_contract.py` L47-49 cites a failure-mode id that has no home —
the scheme only reaches FM-17 (module docstring L6):

```python
    # Test fixtures deliberately exhibit anti-patterns under test.
    # FM-21 (post-OSS) is queued to narrow this set; for now, fixtures
    # get the broad-class ignore.
    (
        "tests/fixtures/**",
        frozenset({"S", "B", "F", "RUF"}),
        "Test fixtures deliberately exhibit anti-patterns",
    ),
```

**PREMISE DRIFT (verified this session):** the comment's premise — "queued to narrow
this set" — is stale. `tests/fixtures` is in the top-level `[tool.ruff] exclude`
(`pyproject.toml:127`), so ruff never lints those files at all; the
`"tests/fixtures/**"` per-file-ignore is **dead config** — it can never fire.
Confirmed empirically: `ruff check tests/fixtures/` and `--no-force-exclude` both
report "All checks passed" (the dir is excluded before per-file-ignores apply), yet
`ruff check tests/fixtures/ --isolated --select S,B,F,RUF` finds 78 errors — proof the
fixtures WOULD trip the rules but ruff never sees them. So "narrowing" the
`{S,B,F,RUF}` set accomplishes nothing observable.

**Fix (comment + registry, `espalier/ruff_config_contract.py` — NO functional change):**
replace the dangling-`FM-21` comment with an accurate one: the entry is retained as
belt-and-suspenders behind the top-level `exclude` (defensive, in case a future edit
narrows the exclude), NOT a queued narrowing. Keep the `frozenset({"S","B","F","RUF"})`
row and the `pyproject.toml` twin unchanged so
`tests/test_ruff_config_includes_security_rules.py` parity stays green.
**Constraint: introduce NO `TP-NNN` literal** — `espalier/` is provenance-scanned;
cite the rationale by mechanism ("redundant behind the top-level exclude"), never by
pack id.

**Earn the red / verify:** `grep -rn "FM-21" espalier/ pyproject.toml` returns the
dangling ref before (RED), empty after (GREEN); `pytest
tests/test_ruff_config_includes_security_rules.py` stays green (the ignore set is
byte-unchanged); `python3 -m espalier audit .` stays 0/0.

### Sub-task 6-E — named-predicate CP-GATEWEAKEN for the guard-predicate files (`_speedbump`)
`tools/cc/hooks/_speedbump.py::_pred_gateweaken` (L327) fires only for files in
`_GUARD_FILES` (L313: `write_guard/plan_guard/config_guard/stop_gate`) and only when a
`_DENY_TOKENS` count drops. The module's own NOTE (L317-322) documents the exact gap:

```python
    # (NOTE: _protected_zones.py / _bash_patterns.py deny via bare
    # `return True` from named predicates — no deny-token substring — so adding
    # them to _GUARD_FILES would be inert, and a `return True` token would over-fire
    # on every benign `return True` removal. Detecting their predicate-flip needs a
    # separate named-predicate mechanism; deferred, not bolted on here.)
```

`_protected_zones.py::_is_protected` (L155, `return True`/`return False` deny surface)
and `_bash_patterns.py::has_catastrophic_recursive_rm` (L726) / `_operand_can_be_catastrophic`
(L633) are the named deny-predicates a slip/agent could neuter (e.g. inserting an early
`return False` / flipping `return True`→`return False`) with zero deny-token delta,
riding green-local to merge. Distinct from DEF-8 (source `_speedbump.py:322`).

**Fix (`tools/cc/hooks/_speedbump.py`, then vendor-sync):** add a second, NAMED-predicate
arm to `_pred_gateweaken` (or a sibling predicate composed into `CP_GATEWEAKEN`) keyed
on a small registry of `(filename, predicate_name)` pairs — the deny predicates in
those two files — that fires when an Edit's `old_string` contains the predicate's
`def <name>(` or a `return True` inside it AND `new_string` weakens the return polarity
(`return True`→`return False`, or inserts a top-of-body `return False`). Keep it a
SYNTACTIC pre-edit proxy (no file read, consistent with the removal-proxy design) and
cap-exempt/one-shot-per-file like the keystone. Do NOT add these files to `_GUARD_FILES`
(the NOTE is right — that arm would be inert or over-fire).

**FP note (deferral reason):** distinguishing a *weakening* return-flip from a benign
refactor with only `old_string`/`new_string` is inherently lossy; this arm needs
calibration against real guard-file edit history to keep it from firing on every
`return True` touch. That is why it was deferred, not bolted onto the keystone.

**Bypass bench not implicated:** `_speedbump.py` is a soft advisory (a metacognitive
speed-bump), NOT a fail-closed deny surface — a miss here degrades the nudge, it does not
open a protected zone. So this arm is out of scope for the release-gating bypass benchmark;
it earns per-`tests/test_speedbump_metacognitive.py` coverage, not a bench lane.

**Earn the red:** extend `tests/test_speedbump_metacognitive.py` — feed `_pred_gateweaken`
(or the new predicate) an Edit against `tools/cc/hooks/_protected_zones.py` whose
`old_string` is the `_is_protected` body and `new_string` inserts `return False` at the
top. RED at HEAD (file not in `_GUARD_FILES`, no deny-token delta → no fire); GREEN after.
Negatives: a benign `return True`→`return True` reflow, and an edit to a NON-guard file,
must not fire.

### Sub-task 6-F — reflect drift-checker: flag DEAD inline-code backtick `docs/*.md` paths (`reflect_protocol`)
`tools/cc/reflect_protocol.py` broken-link detection (main body L629-640) walks
`LOCAL_LINK_RE` (L37: `\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)`) — i.e. it only
resolves markdown LINKS (link text followed by a parenthesised target). A doc path written as inline code —
`` `docs/GONE.md` `` — that points to a nonexistent file is invisible: no `[..](..)`,
no finding. This is the root-cause arm of the phantom cross-ref rot (sweep item #21
sibling); TP-253 Item 3 said "keep on the ledger as durable insurance" but the row was
never created (source `Done/TP-253:120`).

**Fix (`tools/cc/reflect_protocol.py`, then vendor-sync):** add an inline-code path
arm alongside the `LOCAL_LINK_RE` loop. Match backtick spans containing a repo-relative
`.md` path (a tight regex, e.g. `` `([\w./-]+\.md)` ``), resolve exactly as the link arm
does (`(path.parent / t).resolve()` for relative, `root / t.lstrip("/")` for absolute),
skip `<placeholder>`/ellipsis targets, and emit a `gap`/`high` "Broken inline path in
{rel}: {t}" finding when the target does not exist. Reuse `_strip_fences` (L619, already
applied) so fenced code blocks are exempt — only INLINE backticks are checked.

**Class-fix scope check (STANDING_PRINCIPLES §8):** the same broken-link logic is
mirrored in the espalier engine (`espalier/reflection.py` L84 consumes
`espalier/reflect_protocol.py::LOCAL_LINK_RE`). During execution, determine whether the
espalier-side checker is a consumer that ALSO needs the inline-path arm; if so, apply
the parallel change there (no vendor sync — `espalier/` is not a `tools/cc` mirror) and
add it to Files touched. If the espalier arm is out of scope (different consumer
contract), record why in Landing. Do not silently ship a one-sided class-fix.

**Earn the red:** extend `tests/test_reflect_link_guards.py` with a fixture `.md`
containing `` `docs/DOES_NOT_EXIST.md` `` inline → RED at HEAD (no finding); GREEN after
(one `gap` finding). Negatives: `` `docs/SHARP_EDGES.md` `` (exists) → no finding; a
fenced code block containing the dead path → no finding (fence-stripped).

## Scope (out)
- **6-A's comprehension-body / nested-tuple arm.** The sweep names "pack_manifest's
  inline for-loop tuple," but that is an `ast.Tuple` inside a comprehension/`For` body
  that `_collect_constant_sites` never visits (it walks `tree.body` top-level only).
  Widening the *collector* to comprehension bodies is a much larger, higher-FP change
  than the dict-KEY arm — a separate pack, not this one. 6-A ships only the dict-KEY
  extraction.
- **6-D: any functional change to the fixtures-ignore set.** Because the entry is dead
  config behind the top-level `exclude` (premise drift, above), "narrowing"
  `{S,B,F,RUF}` is moot AND would churn the `pyproject`↔contract parity test for zero
  observable benefit. 6-D is comment/rationale-only. Removing the entry entirely (and
  its parity row) is a defensible alternative but sacrifices the belt-and-suspenders
  posture; deferred as a deliberate design call, not bundled here.
- **6-E: adding `_protected_zones.py`/`_bash_patterns.py` to `_GUARD_FILES`.** The
  module NOTE proves this arm is inert (no deny-token) or over-fires (bare `return True`);
  the fix is a distinct named-predicate mechanism, never a `_GUARD_FILES` extension.
- **Making `test_loosening.main()` exit non-zero on findings (6-B).** The scanner's
  advisory exit contract is shared by ~7 other rules that are NOT ready to gate; 6-B
  gates via a self-clean pytest test (CI-enforced) and leaves `main()` returning 0.
- **The other 33 lost-idea-sweep survivors.** Tracked in `reports/lost-idea-sweep-2026-07-26.md`
  and (where they carry real work) routed to the FORWARD_LEDGER / §1 launch rows; only
  the six detector-v2 follow-ups belong to this pack's shared risk profile.

## Affected symbols

### Changed-semantics
- `tools/cc/sister_site_probe.py::_string_elements` — add str-homogeneous `ast.Dict` key-set arm (6-A) + `espalier/_vendor/cc/sister_site_probe.py::_string_elements` byte-mirror
- `tools/cc/memory_sort_audit.py::_audit_duplicates` — add `MEMORY.md` index-row scan against the twin set (6-C) + `espalier/_vendor/cc/memory_sort_audit.py::_audit_duplicates` byte-mirror
- `espalier/ruff_config_contract.py::ALLOWED_PER_FILE_IGNORES` — retire dangling `FM-21` comment, correct the fixtures-ignore rationale (6-D; comment-only, ignore set byte-unchanged)
- `tools/cc/hooks/_speedbump.py::_pred_gateweaken` — add named-predicate weakening arm for `_protected_zones.py`/`_bash_patterns.py` (6-E) + `espalier/_vendor/cc/hooks/_speedbump.py::_pred_gateweaken` byte-mirror
- `tools/cc/reflect_protocol.py::main` — add inline-backtick dead-`.md`-path broken-ref arm (6-F) + `espalier/_vendor/cc/reflect_protocol.py::main` byte-mirror; if the class-fix check confirms the espalier arm is an in-scope consumer it touches BOTH `espalier/reflect_protocol.py` (new inline-path regex beside `LOCAL_LINK_RE`, defined at `:38`) AND `espalier/reflection.py` (the `LOCAL_LINK_RE.finditer` broken-link walk at `:84`, which imports the regex from `espalier.reflect_protocol`) — not `reflection.py` alone

### Extended test coverage (existing files — NO new paths)
All six test files below are already tracked (`git ls-files` confirms each); this pack
adds CASES to them, it does not create paths.
- `tests/test_sister_site_probe_synthetic.py` — dict-key concept-overlap fixture + non-str-key negative (6-A)
- `tests/test_scanner_test_loosening.py` — live-tree self-clean gate for `nondiscriminating_hook_assert` (6-B)
- `tests/test_memory_sort_audit.py` — index-row duplication fixture + pointer-row negative (6-C)
- `tests/test_ruff_config_includes_security_rules.py` — assertion that no dangling `FM-` id remains in the contract (6-D)
- `tests/test_speedbump_metacognitive.py` — named-predicate weakening-flip case + benign/non-guard negatives (6-E)
- `tests/test_reflect_link_guards.py` — dead inline-backtick `.md` path case + exists/fenced negatives (6-F)

## Pass criteria
- **Earn-red 6-A:** dict-key concept-overlap fixture REDs at HEAD (dict → `None`), GREEN after; non-str-key dict still returns `None`.
- **Earn-red 6-B:** self-clean test REDs on a returncode-only-deny fixture tree, GREEN on the live tree — AND the FP=0 precondition is recorded (count 0, or each hit triaged to a true positive) before the gate lands.
- **Earn-red 6-C:** index-row fixture REDs at HEAD (index skipped), GREEN after; a pointer-marked row yields no finding; live-`MEMORY.md` FP=0 re-calibration recorded.
- **6-D:** `grep -rn "FM-21" espalier/ pyproject.toml` empty after; `test_ruff_config_includes_security_rules.py` green (ignore set byte-unchanged); **no `TP-NNN` literal added to `espalier/`**.
- **Earn-red 6-E:** a return-polarity-weakening Edit to `_protected_zones.py` fires the new arm (RED→GREEN); a benign reflow and a non-guard-file edit do not fire; the `_GUARD_FILES` tuple is unchanged.
- **Earn-red 6-F:** dead inline `` `docs/*.md` `` REDs at HEAD (no finding), GREEN after; an existing path and a fenced dead path yield no finding; espalier-side class-fix decision recorded.
- **Mirrors:** `python3 scripts/sync_vendor_cc.py` run after 6-A/6-C/6-E/6-F (they touch `tools/cc/*.py`); `tests/test_vendor_cc_parity.py` green. (No `.claude/{agents,commands,skills}/` edits → `sync_claude_mirrors.py` not required.)
- **Full gate:** `pytest -q` green; `ruff check .` clean; `python3 -m espalier audit .` 0/0; **no `TP-NNN` literal in any shipped surface touched** — this pack edits `espalier/` (6-D), `tools/cc/` (6-A/C/E/F), and `tests/`; all are scanned except `_vendor/` (which the sync script regenerates from the SoT).

## Files touched
- **Modified (SoT):** `tools/cc/sister_site_probe.py` (6-A), `tools/cc/memory_sort_audit.py` (6-C), `espalier/ruff_config_contract.py` (6-D), `tools/cc/hooks/_speedbump.py` (6-E), `tools/cc/reflect_protocol.py` (6-F); conditionally `espalier/reflection.py` (6-F class-fix).
- **New test cases (extend existing files):** `tests/test_sister_site_probe_synthetic.py`, `tests/test_scanner_test_loosening.py`, `tests/test_memory_sort_audit.py`, `tests/test_ruff_config_includes_security_rules.py`, `tests/test_speedbump_metacognitive.py`, `tests/test_reflect_link_guards.py`.
- **Mirrors (regenerated, never hand-edited):** `espalier/_vendor/cc/sister_site_probe.py`, `.../memory_sort_audit.py`, `.../hooks/_speedbump.py`, `.../reflect_protocol.py` via `python3 scripts/sync_vendor_cc.py` (6-A/C/E/F).
- **Unmodified on purpose:** `pyproject.toml` (6-D leaves the ignore set byte-identical — comment-only fix lives in the contract module, not the toml); `espalier/scanners/test_loosening.py` (6-B gates via a test, not a scanner exit-code change); `tools/cc/hooks/_speedbump.py::_GUARD_FILES` tuple (6-E adds a named-predicate arm, not a `_GUARD_FILES` member).

## Sub-task ordering
0. **Launch check (maintenance mode):** confirm the session was started with
   `ESPALIER_MAINTENANCE_MODE=1` — 6-A/6-C/6-D/6-E/6-F write `tools/cc/` and `espalier/`
   (both `PROTECTED_PREFIXES`); without the flag `write_guard` denies those edits. If it is
   unset, exit and relaunch `ESPALIER_MAINTENANCE_MODE=1 claude` (mid-session `export` does
   not reach running hooks). 6-B is test-only and needs no flag.
1. **6-D** ruff FM-21 (smallest — comment/registry, no vendor sync): grep RED → edit → parity green → `espalier audit .` 0/0. **Checkpoint:** `pytest tests/test_ruff_config_includes_security_rules.py`.
2. **6-B** promote gate: run the FP=0 precondition FIRST (abort/record if any live hit) → add self-clean test → RED on fixture / GREEN on live tree. **Checkpoint:** `pytest tests/test_scanner_test_loosening.py`.
3. **6-F** reflect inline-backtick arm → `sync_vendor_cc.py` → resolve the espalier-side class-fix decision. **Checkpoint:** `pytest tests/test_reflect_link_guards.py tests/test_vendor_cc_parity.py`.
4. **6-C** memory index-row (FP-risky): live-`MEMORY.md` calibration → widen detector → `sync_vendor_cc.py`. **Checkpoint:** `pytest tests/test_memory_sort_audit.py tests/test_vendor_cc_parity.py`.
5. **6-A** concept-dup dict keys (FP-risky): widen `_string_elements` → run `sister_site_probe` over the live tree, confirm no new FP cluster → `sync_vendor_cc.py`. **Checkpoint:** `pytest tests/test_sister_site_probe_synthetic.py tests/test_vendor_cc_parity.py`.
6. **6-E** named-predicate CP-GATEWEAKEN (heaviest — new mechanism): add arm → `sync_vendor_cc.py`. **Checkpoint:** `pytest tests/test_speedbump_metacognitive.py tests/test_hooks.py tests/test_vendor_cc_parity.py`.
7. **final** full `pytest -q` + `ruff check .` + `python3 -m espalier audit .`; stamp Landing.

## Estimated effort
- 6-D ~15m · 6-B ~30m (incl. precondition) · 6-F ~35m (+ ~15m if espalier class-fix taken) · 6-C ~45m (calibration-heavy) · 6-A ~40m · 6-E ~60m (new mechanism + calibration) · verify+land ~20m.
  **Total ≈ 4–4.5 h** (≈ 1 h for the safe trio 6-D/6-B/6-F; the rest is the three FP-surface widenings + their live-population calibration).

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) each sub-task carries a fixture that REDs against the unwidened detector and GREENs after — 6-A dict-key cluster, 6-B returncode-only-deny fixture, 6-C index-row fixture, 6-D dangling-`FM-21` grep, 6-E return-polarity weakening Edit, 6-F dead inline `.md` path.
- Date: —
- **D1 RESOLVED 2026-07-27 (operator): entire pack DEFERRED post-flip** — all six sub-tasks, superseding the pre-flip FP-safe-subset (6-B/6-D/6-F) option. Moved to `task-packs/Deferred/`. State stays DRAFT (deferred, not landed/scrapped).
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (`wf_c28406bf-13f`, `reports/lost-idea-sweep-2026-07-26.md` rows #6/#11/#13/#31/#33/#39). **DEFER-recommended** — none gate the OSS flip; three sub-tasks (6-A/6-C/6-E) widen FP surface (the original v1 deferral reason) and need live-population calibration, and 6-B is conditional on an FP=0 precondition, so this is post-flip hardening. **Premise drift (6-D):** the `tests/fixtures/**` per-file-ignore is dead config behind `pyproject.toml:127`'s top-level `exclude` — narrowing is moot; 6-D is scoped to retiring the dangling `FM-21` id + correcting the comment, not a functional narrowing. Revised 2026-07-26 (active-set review wf_c005d89d): added MAINTENANCE-MODE banner + step-0 launch check (5/6 sub-tasks write protected zones), named the PRE-FLIP-vs-DEFER fork (safe subset 6-B/6-D/6-F; 6-A/6-C/6-E stay post-flip), moved the 6 already-tracked test files out of Added-paths, added 6-C casefold-both-sides note, corrected the 6-D ruff isolated count (5→78, tree-wide command), widened the 6-F class-fix scope to both `espalier/reflect_protocol.py`+`espalier/reflection.py`, and noted 6-E's `_speedbump` is a soft advisory (bypass bench not implicated).
