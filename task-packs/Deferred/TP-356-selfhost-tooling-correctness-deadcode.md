# TP-356 — Self-host tooling: correctness & dead-code

## Status
- Version target: current (`0.8.0a13`, self-host, pre-OSS-launch)
- Change type: FIX / cleanup — four low-leverage self-host correctness &
  dead-code follow-ups, each an un-tracked deferral surfaced by the pre-flip
  lost-idea sweep. Two adjacent items (from the same cluster) are deliberately
  **scoped out** with reasoning below (one is a refuted watch-item, one cuts
  against a documented design). None gates the OSS launch.
- **Kind: PACK** (independent sub-tasks; lands as one commit)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`,
  100 agents / 6.0M tokens) + `reports/lost-idea-sweep-2026-07-26.md` (a local
  report, not shipped) section C rows #1, #4/#24, #23, #29 and section-D-adjacent #25.

## Motivation

The sweep swept 87 deduped candidate references and found **55% already
tracked/done/captured** — the null-signal a mature FORWARD_LEDGER should
produce. The genuinely-lost survivors that leaked the ledger's lineage are
overwhelmingly low-leverage self-host tooling an OSS adopter never touches.
This pack collects the four that are worth a bounded, verifiable fix (a real
duplication, a real fs-branch fail-open, a forward-only migration gap, and a
long-elapsed dead-code-retirement trigger) into one release-cleanup window.

Each item was ground-checked against HEAD before drafting — two of the five
cluster items turned out to have **drifted premises** (their source scope-out
is stale or architecturally infeasible as stated) and are scoped OUT rather
than turned into make-work. None of the four in-scope items gates the launch;
the sweep's bottom line is "clean enough to flip public."

## Scope (in)

### Sub-task 1-A — Route `final_release_matrix._load_version` through the version SoT (`scripts/final_release_matrix.py`)
`espalier/version_surfaces.py` is the single source of truth for every file
carrying the release-version literal, and its `read_surface_version` reader is
already the version oracle for **both** sibling release scripts
(`scripts/release_check.py:860` and `scripts/build_release_archive.py:115`).
`final_release_matrix._load_version` (`scripts/final_release_matrix.py:89`)
alone re-implements the read with its own `tomllib.load` — the exact
version-SoT duplication `version_surfaces` exists to close. The script already
`import`s espalier (`from espalier._archive_safety import ...`, line 56), so
routing through the engine is not new coupling; independence is not
load-bearing here.

**Fix** — replace the standalone tomllib read, matching the `release_check`
precedent verbatim:

```python
def _load_version() -> str:
    from espalier.version_surfaces import VERSION_SURFACES, read_surface_version

    version = read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])
    if version is None:
        raise RuntimeError("could not read version from pyproject.toml")
    return version
```

`VERSION_SURFACES[0]` is `("pyproject.toml", <^version = "..."> regex)` — the
same anchored `[project].version` read the two siblings already trust. Then
drop the now-unused `tomllib` import block (`scripts/final_release_matrix.py:35-38`)
**iff** no other call remains (grep-confirm: line 92 is the only `tomllib.load`
site at HEAD).

**Earn the red:** `tests/test_final_release_matrix.py::test_load_version_returns_string`
already exercises `_load_version()`. Add an assertion that its result equals
`read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])` (single-oracle
identity). RED if the routed body diverges from the SoT read; GREEN when they
agree. The existing "returns a string" assertion is the regression floor.

### Sub-task 2-A — Fail-closed the `check_tracked_noise` fs-branch for pruned secret/archive leaks (`scripts/release_check.py`)
`check_tracked_noise` (`scripts/release_check.py:210`) gets its file list from
`repo_mode.list_tracked_or_walked_files`. On a **no-`.git`** tree (an extracted
source export / sdist) that returns the `_walked_files_matching_git_tracked`
branch (`espalier/repo_mode.py:222`), which prunes **every**
`surface_contract.is_release_excluded` path *before* the caller sees it. Every
`_TRACKED_NOISE_PATTERN` is itself release-excluded (all of
`RELEASE_NOISE_PATTERNS` classify `transient`; grep-confirmed at HEAD:
`.env`/`id_rsa`/`credentials`/`project.zip`/`*.whl` all
`classify_release_path == "transient"` → `is_release_excluded == True`). So on
the fs-branch the noise loop is **structurally a no-op** — every offender it
could flag is pre-pruned. A force-`git add`-ed secret/archive file that shipped
into an export slips the noise gate there; the git-branch (`git ls-files`, no
prune) and the archive-member dual-witness still catch it, so this is
defense-in-depth, adversarial-only, low-value under
[[espalier-is-workflow-toolbelt-not-security-boundary]].

Un-pruning the whole list would reintroduce the extract-time false-positives
(`.pytest_cache/`, `*.egg-info/`, `reports/`) the prune exists to suppress. The
honest, non-regressing floor: re-scan the **un-pruned** walk for only the two
classes a fresh extract+test can *never* legitimately create — `SECRET_FILES`
and `ARCHIVE_FILES` (`espalier/release_noise.py:82,98`).

**Fix** — after the existing offender loop, add an fs-branch-only rescan
(`_glob_to_regex` and `re` are already module-level; `list_repo_files_via_filesystem`
imports from the same module as `list_tracked_or_walked_files`):

```python
    files, source = list_tracked_or_walked_files(repo_root)
    compiled = [(re.compile(p), p) for p in _TRACKED_NOISE_PATTERNS]
    offenders: list[tuple[str, str]] = []
    for path in files:
        for pattern, source_pattern in compiled:
            if pattern.search(path):
                offenders.append((path, source_pattern))
                break

    # Defense-in-depth (fs-branch only): list_tracked_or_walked_files prunes
    # every is_release_excluded path before we see it, and every noise pattern
    # is release-excluded -- so the loop above is a no-op on a no-.git tree.
    # Re-scan the UN-pruned walk for the two classes a fresh extract+test can
    # never legitimately create (secrets + archive artifacts); their presence
    # in an extracted tree is a real leak the git branch would catch.
    if source == "filesystem":
        from espalier.release_noise import ARCHIVE_FILES, SECRET_FILES
        from espalier.repo_mode import list_repo_files_via_filesystem
        never_benign = [
            (re.compile(_glob_to_regex(p)), p)
            for p in SECRET_FILES + ARCHIVE_FILES
        ]
        seen = {o[0] for o in offenders}
        for path in list_repo_files_via_filesystem(repo_root):
            if path in seen:
                continue
            for pattern, source_pattern in never_benign:
                if pattern.search(path):
                    offenders.append((path, source_pattern))
                    seen.add(path)
                    break
```

**Earn the red:** add a **committed negative fixture** to `tests/test_release_check.py`
— a `tmp_path` tree with **no `.git/`** containing a `.env` (secret) file plus a
benign `.pytest_cache/x` (proves the prune-suppressed class stays suppressed),
asserting `check_tracked_noise(tmp_path).status == "FAIL"` and that the offender
is the `.env`, not the cache. RED against the unfixed code (the `.env` is pruned
→ PASS); GREEN after the rescan. A second assertion that a tree with only
`.pytest_cache/x` still PASSes pins that the fix did not reintroduce the
extract-time false-positive.

### Sub-task 3-A — One-time migration to stamp byte-identical legacy seed docs (`espalier/cli.py`)
The TP-348 seed-version stamp (`_seed_stamp_line` / `_seed_redeploy_decision`,
`espalier/cli.py:179-210`) is **forward-only**: an unstamped legacy seed doc
(deployed by a pre-stamp engine) returns `"preserve"` forever
(`cli.py:203`, `"unstamped legacy copy -- safe fallback"`), so `cmd_upgrade`
can never refresh it even after the packaged content drifts. `cmd_upgrade`
(`cli.py:2446`) only *counts* them (`_count_unstamped_seed_docs`, `cli.py:2017`,
called at `cli.py:2524`) and prints "delete a stale one to re-seed." (Distinct
from the tracked `DEF-348a`, which is `fuse.py::_seed_bench_results` — a
different seam; not duplicated here.)

The safe migration stamps **only** a legacy copy whose bytes still equal the
freshly-rendered packaged content — provably-untouched-and-current, so adding
the provenance line loses nothing and lets a later upgrade correctly detect
drift. An edited copy (bytes differ) stays unstamped/preserved, exactly as
today; the migration must **not** clobber operator edits.

**Fix — add the helper** (mirrors `_seed_redeploy_decision`'s render/compare,
reusing `_deploy_seed_docs`' rendering via `_SEED_ADAPT_HEADER` /
`seed_needs_adapt_header`):

```python
def _stamp_untouched_legacy_seed_docs(repo_root: Path) -> list[str]:
    """One-time: stamp legacy (pre-stamp-engine) seed docs whose bytes still
    equal the packaged content, so a later upgrade can refresh them. An
    operator-edited copy (bytes differ) is left unstamped -- never clobbered."""
    from espalier.managed_inventory import get_seed_docs, seed_needs_adapt_header
    stamped: list[str] = []
    for rel in get_seed_docs():
        dest = repo_root / rel
        if not dest.is_file():
            continue
        try:
            existing = dest.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _SEED_STAMP_RE.match(existing) is not None:
            continue  # already stamped
        header = _SEED_ADAPT_HEADER if seed_needs_adapt_header(rel) else None
        source = (_DEPLOY_SOURCE_PATH... )  # rendered packaged bytes for rel
        if existing != rendered:
            continue  # operator-edited or drifted -- preserve, cannot prove untouched
        atomic_write_text(dest, _seed_stamp_line(rendered) + rendered)
        stamped.append(rel)
    return stamped
```

> NOTE for the executor: derive `rendered` the same way `_deploy_file` does
> (`(header or "") + <packaged source bytes for rel>`). `_deploy_seed_docs`
> (`cli.py:1994`) already resolves the packaged source path per `rel` via
> `get_seed_docs()` + the deploy-source lookup — lift that exact resolution so
> the byte-comparison uses the identical rendering, otherwise a true match
> mis-reads as "edited." Confirm the deploy-source accessor name at execution
> (`cli._deploy_source_path`) rather than pasting the placeholder above.

**Wire into `cmd_upgrade`** on `--execute`, right after the seed-doc redeploy
(`cli.py:2522-2528`), replacing the passive "left as-is" note path so a legacy
copy that is provably-current gets adopted:

```python
        n = len(_deploy_seed_docs(repo_root))
        print(f"[upgrade] re-deployed {n} seed doc(s).")
        migrated = _stamp_untouched_legacy_seed_docs(repo_root)
        if migrated:
            print(f"[upgrade] stamped {len(migrated)} untouched legacy seed "
                  "doc(s) so future upgrades can refresh them.")
        legacy = _count_unstamped_seed_docs(repo_root)
        if legacy:
            print(f"[upgrade] note: {legacy} seed doc(s) predate the "
                  "seed-version stamp and differ from packaged bytes -- can't "
                  "prove untouched, so left as-is.")
```

**Earn the red:** in `tests/test_cli_deploy.py`, deploy a seed doc, strip its
stamp line in place (simulating a legacy copy) while keeping the body
byte-identical to packaged, run `_stamp_untouched_legacy_seed_docs`, and assert
the doc is now stamped (`_SEED_STAMP_RE.match` non-None) with an unchanged body.
A second doc whose body is edited must stay unstamped. RED before the helper
exists (import/attribute error → the stamp never appears); GREEN after.

### Sub-task 4-A — Retire the 7 dual-run `NUMERIC_CONTRACTS` migration entries (complete TP-56-D) (`tests/`, `docs/FRESHNESS.md`)
`docs/FRESHNESS.md:258-266` records the plan: 7 `NUMERIC_CONTRACTS` entries
"dual-run as both registry contracts AND freshness fragments; the registry is
slated for deletion after one v0.7.x cycle of zero parity failures." We are at
`0.8.0a13` — the trigger elapsed several cycles ago. The 7 are grep-confirmed
fragment-guarded and parity-belted by
`tests/test_freshness_migrations.py::TestNumericMigrations` (fragment
discoverable + pinned + `expected_value` matches registry for all 7).

**Premise-drift correction (important):** the sweep item says "delete the
legacy `NUMERIC_CONTRACTS` registry." At HEAD that is **wrong** — the registry
is a live, growing mechanism: of its 11 entries, only the **7** listed in
`MIGRATIONS` are the legacy dual-run set; the rest (`self-host signal count`,
`canonical hook count`, `slash command count`, `skill count`) are
registry-native contracts never migrated to fragments. Deleting the whole
tuple would regress their coverage and break `test_doc_test_citations.py`'s
citation resolution. So this sub-task completes the **actual** long-planned
TP-56-D step — retire the 7 migrated entries, keep the registry for its native
contracts — exactly as `TestDualRunParity`'s docstring anticipates
("post-removal this assertion becomes `>= 0`").

**Fix (test + doc, no production symbol):**
1. Remove the 7 dual-run `NumericContract(...)` entries from
   `tests/test_documented_claims.py::NUMERIC_CONTRACTS` (`memory-line-cap`,
   `release-check-results`, `bypass-class-count`, `surface-matrix-rows`,
   `release-denylist-patterns`, `redos-timeout-budget-ms`,
   `redos-worst-case-payload` — names per `MIGRATIONS`).
2. Flip `tests/test_freshness_migrations.py` to assert the retirement, mirroring
   the existing `tests/test_freshness_hook_count_migration.py` template: rename
   `TestNumericMigrations.test_expected_value_matches_registry`'s registry half
   to assert each migrated name is **absent** from `NUMERIC_CONTRACTS` (keep the
   fragment discoverable/pinned/expected-value assertions — the fragment is now
   the *sole* guard); update `TestDualRunParity.test_registry_retains_migration_set`
   (`>= 7` → the migrated names absent) and drop
   `test_migration_targets_are_subset_of_registry` (its invariant inverts).
3. Update `docs/FRESHNESS.md` §9 (and its byte-mirror `espalier/assets/docs/FRESHNESS.md`
   §9 + the "all 7 migrated" line at `:102`) to state the 7 are retired and the
   fragment is now the sole guard, and that the registry persists for its
   non-migrated native contracts. **No `TP-NNN` literal** in the doc body.
   Then `python3 scripts/sync_asset_docs.py` (docs → `espalier/assets/docs/`).

**Earn the red:** the flipped `tests/test_freshness_migrations.py` assertions
RED against the un-removed registry (the 7 still present) and GREEN once removed;
independently, drift is still caught by the fragment alone — the existing
`test_freshness_hook_count_migration.py::test_adding_canonical_hook_wiring_entry_yields_stale_state`
pattern proves fragment-only drift detection survives (no code change; it is the
model that fragment-sole guarding already works).

## Scope (out)

- **#1 part (b) — fold the three `_venv_python` copies into a shared helper**
  (`espalier/artifact_parity.py:213`, `scripts/final_release_matrix.py:135`,
  `scripts/wheel_smoke.py:194`). **Deferred by design, not omission.** Both
  script copies document the split as deliberate ("both run standalone in fresh
  venvs; a shared import is deliberately avoided") and their behavioral parity is
  already pinned by
  `tests/test_final_release_matrix.py::test_venv_python_parity_with_wheel_smoke`.
  `wheel_smoke.py` carries **no** top-level espalier import (it runs from an
  extracted archive with nothing installed beyond the wheel under test), so
  routing its copy through `espalier.artifact_parity` would couple a
  standalone-in-fresh-venv script to the source tree — the exact thing its
  design avoids. The parity test makes drift a non-issue; the fold trades a real
  invariant for a cosmetic dedup. Left as three guarded copies.

- **#25 (W4) — wire `is_release_export` into `session_start.py`.** **Refuted at
  source + architecturally infeasible as stated.** The source finding
  (`reports/context-blind-overreach-hunt.md:157-162`) was itself **refuted under
  the oracle**: "hooks are reporters that fail open to a thinner banner, not a
  hard fail ... watch, don't act." There is no live run-site (finder slice 1:
  "no call site is run [on an export]"). And `is_release_export` lives in
  `espalier/surface_contract.py:1111`; `session_start.py` is a
  `tools/cc/hooks/` script under the **zero-espalier-imports** contract
  (`_hook_utils` mirrors only `is_self_host_repo`, not the export discriminator).
  Wiring it is therefore not a one-line "use the flag" — it requires porting the
  whole `.gitattributes` export-ignore-sentinel logic into a new `_hook_utils`
  mirror, disproportionate to a refuted watch-item. Keep it as a watch-item; do
  not build a hook-side mirror on spec.

- **All other lost-idea sweep rows** (sections A/B and the rest of C) — launch-
  gate items (#26/#14/#7), ledger rows (#5/#2/#16), and the remaining long tail
  — are ledger/checklist/roadmap work, not the correctness/dead-code lane this
  pack scopes.

## Affected symbols

### Changed-semantics
- `scripts/final_release_matrix.py::_load_version` — routed through `espalier.version_surfaces.read_surface_version`; drop the standalone `tomllib` read (1-A)
- `scripts/release_check.py::check_tracked_noise` — fs-branch secret/archive rescan over the un-pruned walk (2-A)
- `espalier/cli.py::cmd_upgrade` — call the new legacy-stamp migration on `--execute` (3-A)
- `tests/test_documented_claims.py::NUMERIC_CONTRACTS` — remove the 7 dual-run migration entries (4-A)
- `tests/test_freshness_migrations.py::TestNumericMigrations` / `tests/test_freshness_migrations.py::TestDualRunParity` — flip registry-presence assertions to registry-absence (4-A)

### Added-paths
- `espalier/cli.py::_stamp_untouched_legacy_seed_docs` — one-time byte-identical legacy seed-doc stamp migration (3-A)
- `tests/test_release_check.py` — committed negative fixture: `.env` in a no-`.git` tree FAILs `check_tracked_noise` (2-A)
- `tests/test_cli_deploy.py` — legacy-seed-doc stamp migration test (byte-identical stamped, edited preserved) (3-A)
- `tests/test_final_release_matrix.py` — single-oracle identity assertion for `_load_version` (1-A)

## Pass criteria
- **Earn-red 1-A:** `test_load_version_returns_string` (+ the identity assertion)
  green; `_load_version` returns `read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])`;
  no `tomllib` import remains if unused.
- **Earn-red 2-A:** the new negative fixture REDs (a `.env` in a no-`.git` tree
  PASSes) before the rescan and GREENs (FAILs on the `.env`) after; the
  `.pytest_cache/`-only tree still PASSes (no reintroduced false-positive).
- **Earn-red 3-A:** the migration test REDs before `_stamp_untouched_legacy_seed_docs`
  exists and GREENs after — a byte-identical legacy copy becomes stamped
  (body unchanged), an edited copy stays unstamped.
- **Earn-red 4-A:** the flipped `test_freshness_migrations.py` assertions RED
  against the un-removed registry and GREEN once the 7 entries are removed;
  fragment-sole drift detection still proven by the existing hook-count model.
- **4-A doc sync:** `docs/FRESHNESS.md` §9 updated; `python3 scripts/sync_asset_docs.py`
  run; `espalier/assets/docs/FRESHNESS.md` byte-parity green.
- Full gate: `pytest -q` green; `ruff check .` clean; `python3 -m espalier audit .`
  0/0; **no `TP-NNN` literal** in any shipped surface this pack touches —
  `espalier/cli.py` (3-A), `scripts/final_release_matrix.py` (1-A),
  `scripts/release_check.py` (2-A), `docs/FRESHNESS.md` + `espalier/assets/docs/FRESHNESS.md`
  (4-A) are all scanned (`_vendor/` excluded; `tests/` and this pack file are not
  shipped surfaces).

## Files touched
- **Modified:** `scripts/final_release_matrix.py` (1-A), `scripts/release_check.py`
  (2-A), `espalier/cli.py` (3-A), `docs/FRESHNESS.md` (4-A),
  `tests/test_documented_claims.py` (4-A), `tests/test_freshness_migrations.py` (4-A).
- **New test cases (extend existing files):** `tests/test_final_release_matrix.py`
  (1-A), `tests/test_release_check.py` (2-A), `tests/test_cli_deploy.py` (3-A).
- **Mirrors (regenerated, never hand-edited):** `espalier/assets/docs/FRESHNESS.md`
  via `python3 scripts/sync_asset_docs.py` (4-A).
- **Unmodified on purpose:** `espalier/artifact_parity.py` + `scripts/wheel_smoke.py`
  `_venv_python` copies (Scope-out: deliberate standalone design, parity-tested);
  `tools/cc/hooks/session_start.py` (Scope-out #25: refuted watch-item);
  `espalier/repo_mode.py::_walked_files_matching_git_tracked` (2-A fixes at the
  caller, NOT the shared prune, to avoid changing provenance/codename callers).

## Sub-task ordering
1. **1-A** version-SoT route — smallest change; add the identity assertion → green.
2. **2-A** noise fs-branch — add the negative fixture → observe RED → add the
   rescan → GREEN; confirm the cache-only tree still PASSes.
3. **3-A** seed-doc migration — add the earn-red test → RED → add
   `_stamp_untouched_legacy_seed_docs` + wire into `cmd_upgrade` → GREEN.
4. **4-A** registry retirement — flip the migration assertions → RED → remove
   the 7 entries → GREEN → update `docs/FRESHNESS.md` §9 →
   `python3 scripts/sync_asset_docs.py` → parity green.
5. **final** — full `pytest -q` + `ruff check .` + `python3 -m espalier audit .`;
   grep the four shipped surfaces for any `TP-NNN` leak; stamp Landing.

## Estimated effort
- 1-A ~15m · 2-A ~35m · 3-A ~40m · 4-A ~45m · verify+land ~20m.
  **Total ≈ 2.5 h.**

## Landing
- State: DRAFT
- Commits: —
- Suite: —
- Earn-the-red: (planned) 1-A identity-of-oracles assertion; 2-A `.env`-in-no-git
  negative fixture reds pre-rescan; 3-A migration test reds before the helper
  exists; 4-A flipped registry-absence assertions red against the un-removed 7.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (`wf_c28406bf-13f`).
  Operator provisional reco was **defer**; concur — all four items are
  capture-and-forget self-host cleanup, none gates the OSS flip. Two cluster
  items scoped OUT on drifted premises (fold-`_venv_python` = deliberate design;
  #25 export-banner = source-refuted + hook-import-infeasible).
