# TP-362 — Recall focus tie-break · skills-owned surface · doctor helper promotion

## Status
- **Landed 2026-09-11 (two of three legs) under `DEF-532` / §C17, TP-449 Tier 2:**
  sub-task 1-B (skills in every disk-reality ownership view, one owner
  `surface_contract.CLAUDE_KIND_GLOBS`) and 1-C (the helper is
  `extract_count_for_label`, no alias). Shipped tests:
  `tests/test_managed_paths.py::TestFallbackManagedPaths::test_fallback_names_every_claude_file_the_deploy_writes`,
  `::TestSelfHostManagedPaths::test_self_host_contains_every_installed_claude_kind`,
  `tests/test_audit_accuracy.py::TestExtractCountForLabelIsPublic`. 1-A (the
  recall tie-break) closed 2026-09-04. The §193 completeness grep below is too
  narrow -- `bench/run_benchmark.py` held five sites it could not see; sweep
  the whole tracked tree.
- Version target: current (self-host, pre-OSS-launch)
- Change type: FIX / cleanup — three low-leverage, verified-lost forward-work items
  (a recall ranking-fairness gap, a managed-ownership omission, a cross-module
  private-import smell). Each is additive/mechanical; none is a live false-green and
  **none gates the OSS launch**.
- **Kind: PACK** (three independent sub-tasks; lands as one commit)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`,
  100 agents / 6.0M tokens) → `reports/lost-idea-sweep-2026-07-26.md`. Items #12
  (C-tail:234), #19 (C-tail:69), and #E (completeness critic, `espalier/doctor.py:212`).
  All three re-grep-confirmed un-addressed at HEAD during authoring (see Motivation).

## Motivation

The pre-flip sweep found 55% of swept candidate references were already tracked, done, or
captured; the residue never entered the FORWARD_LEDGER lineage — the seam a self-consistency
audit structurally can't see. These three are that residue: real, small, and safe-direction.

- **#12 recall focus tie-break** — `_recall.py::recall` sorts on
  `(score, _is_canonical_footgun, source)` with `reverse=True`. On an **exact** score tie
  the final key is `source` reverse-lexicographic — arbitrary with respect to focus/size,
  so a large aggregate doc can out-rank a focused entry purely because its path sorts higher.
  TP-187 fixed *determinism* (a stable order); it did **not** add focus fairness. TP-297a
  flagged this as "Candidate for TP-297c," but TP-297c took a different scope → it fell
  through. Advisory top-1 recall, exact ties only — **low leverage**, real.
- **#19 skills-owned surface** — post-TP-327, `.claude/skills/` is a *display-only*
  `LIVE_SURFACE` entry: TP-327 wired skills into `discover_self_host_surface` for rendering
  but deliberately left `managed_paths` (ownership) untouched (its scope-out §"owned/drift"
  at `Done/TP-327-live-surface-skills-section.md:69`). `self_host_managed_paths` still omits
  the `"skills"` key, so a committed skill is not in the managed-ownership inventory. This
  pack closes the **ownership** half (the tractable, additive half); the **build-plan drift**
  half stays deferred with a real reason (Scope out).
- **#E doctor helper promotion** — `espalier/doctor.py:21` does
  `from espalier.audit_accuracy import _extract_count_for_label` — a leading-underscore
  (private) symbol imported across modules. The in-source comment (`doctor.py:211-212`) itself
  says *"Cross-module private import (sister-site coupling); promotion to public surface is
  deferred."* Surfaced only by the sweep's completeness critic; in no tracker (0 hits in
  FORWARD_LEDGER). Promote it to a real public name.

**Grounding note (authoring-time re-verification, 2026-07-26):** none of the three is
already addressed at HEAD. `_recall.py:364` still carries the 3-key sort; `managed_paths.py:152-155`
still omits `surface.get("skills", …)`; `doctor.py:21` still imports the underscore name and
the "deferred" comment is live. No premise drift.

## Scope (in)

### Sub-task 1-A — Recall focus/size tie-break (`tools/cc/hooks/_recall.py::recall`)
On an exact score tie, prefer the **focused** (fewer-token) doc over a large aggregate,
inserting the new key *after* the existing canonical-footgun preference (so TP-297a's
"named-catalog coinage wins on a tie" is preserved) and *before* the `source` determinism
key (so TP-187's stable order is preserved as the final fallback). `_Doc` already carries
`tokens: Counter` (`_recall.py:88`); `sum(tokens.values())` is the document length — the
natural size proxy. Under `reverse=True`, a **negated** size makes the smaller doc rank first.

**Fix (`tools/cc/hooks/_recall.py`, ~L364, inside `recall`):**

```python
    # Tie-break order: score DESC → canonical-footgun DESC → focus (fewer tokens)
    # → source DESC. Focus is post-floor and post-score, so it never out-ranks a
    # higher-scoring doc; it only settles an EXACT score+footgun tie in favor of a
    # focused entry over a large aggregate, with source as the final determinism key.
    scored.sort(
        key=lambda sd: (
            sd[0],
            _is_canonical_footgun(sd[1].source),
            -sum(sd[1].tokens.values()),
            sd[1].source,
        ),
        reverse=True,
    )
    return [Hit(d.source, d.snippet, round(s, 4)) for s, d in scored[:top]]
```

(Also revise the L355-363 tie-break block-comment prose so it names the focus key ahead
of source — **no `TP-NNN` literal** in the comment; `_recall.py` is a shipped surface.)

Then **`python3 scripts/sync_vendor_cc.py`** to propagate to
`espalier/_vendor/cc/hooks/_recall.py` (byte-parity-pinned by `tests/test_vendor_cc_parity.py`).

**Earn the red:** add a test to `tests/test_recall.py` (reuse the `_synth` corpus helper,
`test_recall.py:40`) with a corpus of N=4 where exactly two docs match a single query term
`widget` (equal df ⇒ **exact score tie**) but differ in size, and the focused doc's path
sorts *lower* lexicographically than the aggregate's — e.g. `aaa.md` = `"widget\n"` (focused)
vs `zzz.md` = `"widget " + <many distinct filler tokens>` (aggregate), plus two padding docs
without `widget` so `df(widget)=2 <= half=2.0` clears the topical floor. Assert
`recall("widget", root, top=1)[0].source == "memory/aaa.md"`. **RED** pre-fix (source reverse-lex
picks `memory/zzz.md`); **GREEN** post-fix (focus key wins for the smaller doc regardless of path).

### Sub-task 1-B — Wire skills into self-host ownership (`espalier/managed_paths.py::self_host_managed_paths`)
Add the `"skills"` key to the ownership set. `discover_self_host_surface` already returns
`"skills"` (TP-327), so this is a one-line additive consume. Verified safe:
`doctor._is_plan_tracked` (`doctor.py:89-100`) returns True only for `.claude/agents/`,
`.claude/commands/`, `tools/cc/hooks/` — **not** `.claude/skills/` — so newly-owned skills
do **not** trip doctor's `missing_from_saved_plan` warning (which would otherwise fire on
every self-host run because `harness_config.json` has no skills; see Scope out).

**Fix (`espalier/managed_paths.py`, L152-155, inside `self_host_managed_paths`):**

```python
    paths.update(surface.get("agents", []))
    paths.update(surface.get("commands", []))
    paths.update(surface.get("skills", []))
    paths.update(surface.get("hooks", []))
    paths.update(surface.get("managed_reports", []))
```

**Earn the red:** add `test_self_host_contains_skills` to
`tests/test_managed_paths.py::TestSelfHostManagedPaths` (beside `test_self_host_contains_smoke_command`,
L219), asserting `".claude/skills/reflect/SKILL.md" in self_host_managed_paths(REPO_ROOT)`.
**RED** pre-fix (skills absent from the ownership set); **GREEN** post-fix. The existing
`test_self_host_is_sorted_deduped_forward_slash` (L244) stays green — the return already sorts.

### Sub-task 1-C — Promote `_extract_count_for_label` to a public helper (`espalier/audit_accuracy.py`)
Rename the private `_extract_count_for_label` → **`extract_count_for_label`** in its home
module `audit_accuracy.py` (def at L192; internal call at L242) and repoint the one production
consumer plus the tests. This removes the cross-module private-import smell the `doctor.py`
comment flags. No back-compat alias (internal repo, all call sites are in-repo).

**Fix 1 (`espalier/audit_accuracy.py`, L192):**

```python
def extract_count_for_label(text: str, label: str) -> int | None:
```

(and the self-call at L242: `stated = extract_count_for_label(claim.text, label)`.)

**Fix 2 (`espalier/doctor.py`, L21 import + L214/L246 calls):**

```python
from espalier.audit_accuracy import extract_count_for_label
```
```python
                stated = extract_count_for_label(line, "hooks")
```
```python
                stated = extract_count_for_label(line, "bypass classes")
```

And update the now-stale comment at `doctor.py:208-212` — drop *"Cross-module private import
(sister-site coupling); promotion to public surface is deferred."* and replace with a plain
"Route through the hardened **public** helper (negative-lookbehind, ASCII-only digit class,
`re.ASCII`)." **No `TP-NNN` literal** — `doctor.py` is a shipped surface.

**Fix 3 (`espalier/claim_extractor.py:219`, docstring reference):** update the prose
`audit_accuracy._extract_count_for_label` → `audit_accuracy.extract_count_for_label`.

**Fix 4 (tests):** repoint all 11 sites in `tests/test_audit_accuracy.py`
(imports + calls: L252/257, 264-268, 279-281, 328-355, 370-378, 381-385) and the docstring
reference in `tests/test_doctor.py:578`.

**Earn the red:** add a guard `test_extract_count_for_label_is_public` to
`tests/test_audit_accuracy.py` asserting `hasattr(audit_accuracy, "extract_count_for_label")`
**and** `not hasattr(audit_accuracy, "_extract_count_for_label")`. **RED** pre-rename (public
name absent). Also — the 11 existing test sites (which import the private name) go RED on the
private name's disappearance until repointed in the same sub-task, so the rename is proven
complete only when both the guard and the repointed sites are GREEN.

## Scope (out)
- **The build-plan / drift half of #19 (skills in `diffing`).** *Reason:* `_diff_self_host`
  (`diffing.py:151`) compares the discovered surface against the **saved** `harness_config.json`.
  That plan has **no skills source** — `generated_docs` lists only `.claude/commands/` (verified:
  0 skill paths in the live `harness_config.json`). Adding `"skills"` to the drift loop without
  a saved-side source would report all 9 skills as "added" drift on **every** run — a permanent
  false-positive. Making it real requires the analysis/build-plan writer to *enumerate* skills
  into the plan — the "separate, larger decision" TP-327's scope-out named, and operator-gated.
  Moreover skill add/remove is **already** caught elsewhere (`tests/test_package_resource_parity.py`
  mirror parity, `EXPECTED_SKILL_COUNT`, `surface_impact.py:164`), so the diffing gap is
  low-value. Ownership-inventory (1-B) is the clean, additive slice; drift stays deferred.
- **Promoting `_label_word_re` (`audit_accuracy.py:180`) too.** *Reason:* it is used only
  *within* `audit_accuracy.py` (no cross-module import) — it is not the smell #E names. Leave
  it private; promoting an internal-only helper is churn with no consumer.
- **Moving `extract_count_for_label` to a new shared module.** *Reason:* a new
  `espalier/*.py` path auto-enrolls in the public-surface contracts (provenance / mirror /
  hygiene / count-pins) — heavier than warranted for a 2-consumer helper. Renaming in place is
  the proportionate promotion.
- **The other C-tail / completeness-critic items (#13, #17, #29, `WALLPAPER_MIN_RUNS`
  calibration, …).** *Reason:* separate concerns, separate packs; this pack is scoped to the
  three named recall/surface fixes only.

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/_recall.py::recall` — sort key gains a focus (`-sum(tokens.values())`)
  tie-break between the canonical-footgun and source keys (1-A)
- `espalier/_vendor/cc/hooks/_recall.py::recall` — byte-mirror, regenerated via `sync_vendor_cc.py` (1-A)
- `espalier/managed_paths.py::self_host_managed_paths` — ownership set gains `surface.get("skills", [])` (1-B)
- `espalier/doctor.py` — import + two call sites (`_report_managed_paths` region, L214/L246)
  repointed to the public `extract_count_for_label`; stale "deferred" comment removed (1-C)

### Renamed
- `espalier/audit_accuracy.py::_extract_count_for_label` → `espalier/audit_accuracy.py::extract_count_for_label` (1-C)

### Added-paths
- (none — all production edits extend existing modules; new tests extend existing files:
  `tests/test_recall.py`, `tests/test_managed_paths.py`, `tests/test_audit_accuracy.py`)

## Pass criteria
- **Earn-red 1-A:** the new focus-tie-break test REDs pre-fix (top-1 = `memory/zzz.md`,
  the large aggregate, via source reverse-lex) and GREENs post-fix (top-1 = `memory/aaa.md`,
  the focused doc). `python3 scripts/sync_vendor_cc.py` run; `tests/test_vendor_cc_parity.py` green.
- **Earn-red 1-B:** `test_self_host_contains_skills` REDs pre-fix (skills absent) and GREENs
  post-fix; `test_self_host_is_sorted_deduped_forward_slash` stays green; no new doctor
  `missing_from_saved_plan` warning appears (`_is_plan_tracked` excludes `.claude/skills/`).
- **Earn-red 1-C:** `test_extract_count_for_label_is_public` REDs pre-rename (public name
  absent), GREENs post-rename; the 11 repointed `tests/test_audit_accuracy.py` sites stay green;
  `grep -rn "_extract_count_for_label" espalier/ tests/ --include='*.py'` (excluding `_vendor/`)
  returns **zero** hits after the rename.
- **No `TP-NNN` literal** introduced in any shipped surface this pack touches — `tools/cc/hooks/_recall.py`,
  `espalier/managed_paths.py`, `espalier/audit_accuracy.py`, `espalier/doctor.py`,
  `espalier/claim_extractor.py` are all provenance-scanned (only `_vendor/` is skipped).
- Full gate: `pytest -q` green; `ruff check .` clean; `python3 -m espalier audit .` 0/0.

## Files touched
- **Modified:**
  - `tools/cc/hooks/_recall.py` (1-A) — sort key + comment prose
  - `espalier/managed_paths.py` (1-B) — one added `paths.update` line
  - `espalier/audit_accuracy.py` (1-C) — rename def + self-call
  - `espalier/doctor.py` (1-C) — import + 2 calls + comment
  - `espalier/claim_extractor.py` (1-C) — docstring reference
  - `tests/test_recall.py` (1-A) — new focus-tie-break test
  - `tests/test_managed_paths.py` (1-B) — new `test_self_host_contains_skills`
  - `tests/test_audit_accuracy.py` (1-C) — 11 repointed sites + public-name guard test
  - `tests/test_doctor.py` (1-C) — docstring reference at L578
- **Mirrors (regenerated, never hand-edited):** `espalier/_vendor/cc/hooks/_recall.py`
  via `python3 scripts/sync_vendor_cc.py` (1-A).
- **Unmodified on purpose:**
  - `espalier/diffing.py` — the drift half stays deferred (see Scope out)
  - `reports/harness_config.json` — no skills enumeration added (drift half deferred)
  - `.claude/{agents,commands,skills}/` — untouched, so **no** `sync_claude_mirrors.py` run needed
  - `espalier/render_surface.py` / `surface_contract.py` — TP-327's skills render/discovery is unchanged

## Sub-task ordering
1. **1-A recall tie-break** (smallest, self-contained): add the earn-red test → observe RED →
   apply the sort-key fix + comment → GREEN → `python3 scripts/sync_vendor_cc.py`. **Checkpoint:**
   `pytest tests/test_recall.py tests/test_vendor_cc_parity.py -q` green.
2. **1-B skills ownership** (one-line additive): add `test_self_host_contains_skills` → RED →
   add the `surface.get("skills", [])` line → GREEN. **Checkpoint:**
   `pytest tests/test_managed_paths.py tests/test_doctor.py -q` green (no new doctor warning).
3. **1-C helper promotion** (mechanical fan-out, most sites — last): add the public-name guard
   test → RED → rename def + self-call → repoint `doctor.py`, `claim_extractor.py`, and the 11
   `test_audit_accuracy.py` sites + `test_doctor.py:578` → GREEN. **Checkpoint:**
   `pytest tests/test_audit_accuracy.py tests/test_doctor.py -q` green **and**
   `grep -rn "_extract_count_for_label" espalier/ tests/ --include='*.py' | grep -v _vendor` empty.
4. **final** — full `pytest -q` + `ruff check .` + `python3 -m espalier audit .`; stamp Landing.

## Estimated effort
- 1-A ~30m (test + fix + vendor sync) · 1-B ~15m · 1-C ~30m (rename fan-out + guard) ·
  verify+land ~15m. **Total ≈ 1.5 h.**

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) 1-A focus-tie-break test reds pre-fix (large aggregate `zzz.md`
  wins on source reverse-lex) → greens (focused `aaa.md` wins); 1-B `test_self_host_contains_skills`
  reds on the missing ownership key; 1-C public-name guard reds pre-rename.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (`wf_c28406bf-13f`) /
  `reports/lost-idea-sweep-2026-07-26.md`. All three are low-leverage self-host cleanups; none
  gates the OSS launch. Operator provisional reco: **defer** — concurred (post-launch cleanup
  window). The #19 build-plan drift half is deliberately out of scope (permanent false-positive
  without saved-side skill enumeration; already caught by mirror-parity + EXPECTED_SKILL_COUNT).
