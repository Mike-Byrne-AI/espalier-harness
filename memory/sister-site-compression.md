# Sister-site compression

**Status:** active
**Linked from:** docs/CONVENTIONS.md "Sister-site compression (TP-104 / TP-105)"

Accumulated notes on the upstream-compression discipline: when to reach
for it, how the 0-C probe works, and the deliberate-debt registry.

## Running compression debts

Duplicates the 0-C probe could (or already does) surface, but which are
deliberately deferred or out-of-shape for compression.

| Site | Shape | Why deferred |
|---|---|---|
| `espalier/scanners/_classify` parallel impls | Deliberately different bodies per scanner (Python AST vs other classifiers) | Scope-out today — `_default_scan_targets` excludes `espalier/scanners/`. Future re-inclusion needs `# sister-site: ok <reason>` markers per scanner. |
| `_load_json` across 5 espalier modules | **IDENTICAL** — 5 sites, one body hash (`cognitive_blueprint.py::_load_json`, `diffing.py::_load_json`, `handoff.py::_load_json`, `proofs.py::_load_json`, `reflection.py::_load_json`). The *callers* consume different JSON shapes; the loader bodies do not differ. | **Block-eligible in shape, ADVISORY today — corrected 2026-08-10.** Every one of the 5 bodies is now `return load_report_json(path)`: a pure forward to one imported owner, so the clique is classified DELEGATING and does not set `has_debt`. The unification this row asked for HAS happened — `espalier._report_io.load_report_json` is the typed helper, and what remains at each site is a local alias for it, not a copy of it. |
| `_safe_text` × 3 in espalier engine | **IDENTICAL** — 3 sites, one body hash (`analyze.py`, `proofs.py`, `reflect_protocol.py`). Fallback semantics differ by *call site*, not by body. | Same as above — WARN, DELEGATING, advisory since 2026-08-10. All 3 bodies are `return safe_text(path)`, forwarding to one imported owner. |
| `bypass_class_count` constant in `NUMERIC_CONTRACTS` | Tightly filesystem-coupled (`bench/corpus/`). | Lift into `_surface_expected.py` requires derive-from-filesystem — TP-105 didn't ship the helper. Probe doesn't cover this site (counts aren't functions). |
| `_check_branch` × 2 in `post_compact.py` + `session_start.py` | IDENTICAL body, only 2 sites — INFO clique (advisory). | Two-site duplicates are tolerated (bootstrap pattern); upstream-promotion of git-branch checking to `_hook_utils.py` would land in a follow-up pack if a third site appears. |
| `--kind` choices × 2 in `tools/cc/cognitive_blueprint.py` (`:835`, `:851`) | Byte-identical 4-element list `["decision", "alternative_rejected", "pattern_discovered", "reflect_insight"]` declared twice in one file. **The probe cannot see it** — see the blindness note below. | Open, low severity. The consumer set is really three: these two `argparse` sites plus `reflect_protocol._ELIGIBLE_KINDS`, which holds a deliberately *different* (3-element) set. Any fix must preserve that asymmetry rather than "unify" it — the exclusion of `reflect_insight` is a recorded decision, not drift (see the note below). Ride it along the next pack with legitimate business in `tools/cc/`; it does not justify a maintenance-mode relaunch on its own. |
| `MUTATION_TOOLS` literal × 3 (write_guard / plan_guard / test_hook_matcher_precision) | **CLOSED by TP-108** — promoted to `tools/cc/hooks/_hook_utils.py::MUTATION_TOOLS` (frozenset). All three sites now import the shared SoT. First worked example of the constant-clique detection mode catching its own seed instance. |
| 9 × `_project_root = _hook_utils.resolve_project_root` aliases | **CLOSED by TP-341** — Option A: the hook-internal alias LHS renamed to `_resolve_project_root` across all 9 hooks (+ their internal call sites + the guard/monkeypatch test refs), so the LHS basename now matches the `resolve_project_root` export. Option B (rename the `_hook_utils` export to `project_root`) was rejected: a worse (value-shaped) name and a larger blast radius — it touches the public export plus the 3 by-name importers (`task_router`, `context_reinject_failure`, `_recall`) added since TP-104, which Option A leaves untouched. |
| 2 × `_normalize_rel = _hook_utils.normalize_path` aliases (`post_write_check`, `reflect_trigger`) | **CLOSED by TP-341** — renamed to `_normalize_path`, matching the canonical `write_guard` / `plan_guard` shape, including the 5 references in `tests/test_reflect_trigger_path_normalization.py`. All four hooks now share the identical `_normalize_path = _hook_utils.normalize_path` alias. |
| `INIT_TOOL_SCRIPTS` (`cli.py`) == `STANDARD_MANAGED_TOOLS` (`managed_paths.py`) | **CLOSED** (concept-overlap, TP-276): same 12-element tool-script list, different names, both in `espalier/`. | **Derived — `cli.INIT_TOOL_SCRIPTS = list(STANDARD_MANAGED_TOOLS)`, the single owner in `managed_paths.py`.** The vacuous constant-vs-constant parity test was removed; the meaningful cross-check (`INIT_TOOL_SCRIPTS ⊆ rendered manifest`) survives. The ONE derive-candidate the TP-276 triage left flagged; the other 8 clusters were forced-across-boundary or purpose-scoped (`# sister-site: ok`). |

> **Corrected 2026-08-06.** The `_load_json` and `_safe_text` rows read
> "DIVERGENT — never block" while the alias-miss section below said, correctly,
> that the probe "already exits 2 from the pre-existing `_load_json`/`_safe_text`
> **IDENTICAL** cliques." One file, two contradictory answers, and the wrong one
> was load-bearing: a draft pack (TP-425, retired) designed its noise filter
> around the DIVERGENT claim and would have shipped an advisory that fired on
> five hot modules forever. **Nothing asserts a row's stated shape against the
> probe's live verdict** — this table is a hand-kept restatement of a fact the
> probe computes, which is `§C2` of the forward ledger. The durable fix is a
> parity test over this table, not a re-read. See
> [[fix-the-class-not-the-instance]].

> **A near-identical set is not always drift — check the lines `grep` didn't print.**
> `reflect_protocol._ELIGIBLE_KINDS` holds **3** kinds while `cognitive_blueprint.py`'s
> `--kind` accepts **4**. That asymmetry is *deliberate*: `reflect_insight` is excluded so
> `/reflect` cannot recurse on its own prior insights. The reason is written **directly above
> the constant** (`reflect_protocol.py::LOCAL_LINK_RE`) and recorded as an authoring fork in
> `docs/session-archive.md`. It was nonetheless filed as a `§C1` defect on 2026-08-06 and a
> whole pack (TP-428, retired) was authored on it — because `grep -n "_ELIGIBLE_KINDS"` returns
> the matching line and not the four comment lines above it. **A grep hit is a line, not a
> context.** Before calling two near-identical sets drift, read the surrounding lines at both
> sites; the difference between a bug and a decision often lives exactly there.

## Constant-clique detection (TP-108)

The probe surfaces module-level constant duplication using the same
clique-detection mechanism that catches function bodies. Detected
shapes (in `_collect_constant_sites`):

- `ast.Assign` / `ast.AnnAssign` with RHS that is one of:
  - `ast.Set`, `ast.List`, `ast.Tuple`, `ast.Dict` (literal collections)
  - `ast.Call` with `func.id ∈ {set, frozenset, tuple, list, dict}`
    (collection constructors with literal args)
  - `ast.Constant` with `value` being a string of `len >= 20`
    (long string constants — file paths, regex patterns, error messages)

Short scalars (`MAX_RETRIES = 3`, `_DEBUG = False`) are skipped to
avoid noise. Threshold-style detection is exact: `value_hash =
sha256(ast.dump(value))`. Same opt-out marker honored.

Severity rules mirror function cliques: 3+ IDENTICAL → WARN (blocking
unless `--accept-compression-debt`); 2-site → INFO (advisory);
DIVERGENT (same name, different value) → advisory. Constants have no
DELEGATING state — the function-clique carve-out for a pure forward to an
imported owner has no analogue here, because a constant cannot forward.

`tests/test_sister_site_probe_ceilings.py::test_constant_clique_count_does_not_grow`
pins the ceiling at 0.

## An opt-out marker suppresses the SITE, not the finding you aimed it at

`probe_compression_debt` drops any site whose `opt_out_reason` is set, before
any arm runs. One marker therefore reaches every arm at once, and it removes
the site from the clique *population* rather than annotating it.

Measured 2026-08-10: three files with identical `_classify` bodies exit 2. Add
a `# sister-site: ok` marker above **one** of them and the probe prints an
empty report and exits 0 — not "2 sites remain, downgraded to INFO". The
3-site WARN fell below the 2-site INFO floor and the clique vanished.

So a marker written to quiet the canon-miss arm silently retires a clique the
author never looked at. Prefer fixing the shape over marking it; when you do
mark, re-run the probe and check that the finding you did NOT intend to
suppress is still in the report.

## Alias-miss detection (TP-108)

The probe surfaces module-level `LHS = Module.Attr` assignments where
LHS basename (stripped of leading underscores) differs from RHS attr
name (also stripped). Rationale: `_X = M.X` is the legitimate
"rename-for-private" convention; `_my_helper = M.normalize_path` is a
rename drift that breaks the "alias claim is self-documenting"
property.

**Symmetric underscore stripping** (TP-108-Audit fix): both LHS and
RHS basenames are `lstrip("_")` before comparison. Pre-fix, only LHS
was stripped — making `_REDIRECT_RE = _bash_patterns._REDIRECT_RE`
(both privatized) fire as drift, when it is the legitimate symmetric
re-export shape used by `write_guard.py` for `_bash_patterns` regex
re-exports. 15 false positives cleared by the fix.

**Blocking as of TP-341.** The pack §108-E originally specified
alias_misses as blocking, but the audit surfaced 11 pre-existing
sites that were defensible per TP-104's design intent, so the flip
was deferred. TP-341 landed that closure: grounding the detector on
the live tree found **13** alias-misses (not the registry's 11 — two
untracked sites, `reflect_trigger.SOURCE_EXTENSIONS` and
`pre_release._matches_attr_pattern`, both the same rename-drift
class), renamed all 13 to the canonical `_X = M.X` shape, then added
`bool(report.alias_misses)` to `main`'s `has_debt`. The gate is
forward-looking: with the live count already driven to 0, the flip
changes no current exit code — and note the probe already exits 2
from the pre-existing `_load_json`/`_safe_text` IDENTICAL cliques, so
its CLI exit is NOT a discriminating alias-drift oracle until those
cliques are compressed. The **load-bearing guard is
`test_alias_miss_count_does_not_grow`** (asserts the live count stays
0 via `EXPECTED_ALIAS_MISS_CEILING`). `has_debt` gating covers a new
**assignment-form** alias in a scanned tree (`tools/cc/hooks/` +
top-level `espalier/`); opt out a deliberate one with a
`# sister-site: ok <reason>` marker. **Import-alias shape covered as of
TP-350**: `_collect_alias_misses` gained `ast.ImportFrom` + `ast.Import`
arms (the symmetric underscore strip applies to the `as` name, so
`import stat as _stat` / `from M import X as _X` stay legitimate), and
`AliasMiss` carries a `shape` field (`assign` | `import-from` | `import`).
Grounding the extended detector on the live tree surfaced **6** diverging
import aliases — all `import-from` — which TP-350 closed to their canonical
names: `_reinject`/`subagent_start` `_MAINT_ENV`←`ENV_VAR`, `cli`
`run_surface_gate`←`run_cc_surface_gate`, `fuse` `fm`←`fusion_manifest`,
`proofs` `SUSPICIOUS_TEXT`←`SUSPICIOUS_CONTENT`, `surface_contract`
`_TRANSIENT_PATH_PATTERNS`←`RELEASE_NOISE_PATTERNS`. **Calibration lesson:**
the FORWARD_LEDGER note said "import-alias shape evades detection"; running
the extended rule on the live tree turned that claim into a concrete 6-site
population *and* exposed a latent hole — `_live_opt_out_count` counted only
FUNCTION/method opt-outs, so a `# sister-site: ok` marker on an
assignment/import site would suppress a finding yet stay invisible to
`EXPECTED_OPT_OUT_CEILING`. **Resolved by TP-351:** the counter now reads
markers above every module-level node (assign/import/constant/function/
class) AND every class method — the full surface where a marker suppresses a
finding — grandfather-frozen at the live population (20), not 0. The 0-A
pack-artifact review caught that the naive `tree.body`-only fix would itself
have DROPPED the class-method surface the old `_collect_sites` walk covered
(the same "counted invisibly" class the pack exists to close, in miniature),
so the shipped counter is the *union* of both, with a pinned earn-red
asserting neither sub-walk alone is a faithful count. TP-351 also made the
alias-miss message name the `# sister-site: ok` escape and fixed the
`.numpy` leading-dot render. Still NOT covered (follow-up, see
FORWARD_LEDGER DEF-20 (b)): rename-aliases in unscanned paths
(`tools/cc/*.py` root, `espalier/` subpackages), and module-level scope only
— a shim nested in a function body or `try/except` fallback is unseen in
either spelling.

## Concept-overlap detection (TP-276)

The probe's third detection mode, closing the gap the name-clique and
value-hash detectors both missed: the same concept expressed under
**different names AND different (overlapping) values**. Two extension sets —
one dotted, one un-dotted, different names — were invisible to both prior
detectors.

`_build_concept_overlaps` clusters `ConstantSite`s whose str-element sets
overlap. Design:

- **Metric = CONTAINMENT** (`|A∩B| / min(|A|,|B|)`), NOT Jaccard: a narrow
  near-subset of a wide set (the derive-from-core signal) is caught even where
  Jaccard (`5/15`) would miss it.
- **`str_elems`** on `ConstantSite`: the frozenset of str elements of a
  str-HOMOGENEOUS `set`/`list`/`tuple` literal (or `set/frozenset/tuple/list(<lit>)`
  call), else `None`. A comprehension-derived set is an `ast.SetComp`, not a
  literal → `None` → **self-heals**: fixing a dup by deriving from the canon
  removes the site from the advisory (no whack-a-mole).
- **Tokens normalized** `(t[1:] if t.startswith('.') else t).casefold()` so
  `.py ≡ py`.
- **Five stacked floors** keep it quiet: str-homogeneous only, `MIN_SIZE=4`,
  `MIN_OVERLAP=4` (absolute), `K=0.6` (containment), different-name pairs only.
  Clusters are connected components, but a reported cluster ALSO requires a
  global shared core `≥ MIN_OVERLAP` — a coreless transitive chain (A-B-C where
  A∩C is empty) is dropped, not reported as a blob.
- **Advisory only**: `concept_overlaps` on `ProbeReport`, EXCLUDED from
  `has_debt` (never exit-2), exactly like `alias_misses`. The same
  `# sister-site: ok` marker suppresses collection.

Synthetic contract:
`tests/test_sister_site_probe_synthetic.py::TestConceptOverlapDetection`
(POSITIVE wide/narrow subset → 1 cluster; NEGATIVE disjoint → none; SELF-HEAL
comprehension-derived → none; ADVISORY seeded overlap keeps exit 0).

**Calibration lesson — the pack's premise was wrong.** TP-276 predicted the
detector would fire on ~1 cluster (the A5 extension sets) — "a quiet advisory."
Run on HEAD it fired on **9 real clusters**, all genuine concept-overlaps the
pack hadn't anticipated. A detector's thresholds AND its *predicted output
count* are a claim — the design-phase face of [[premise-check-before-authoring-a-fix]]:
RUN the rule on the live tree before trusting "this will be quiet"; tune by
MEASURING, not by authoring. When the real count diverges from the pack's
premise, that is premise-drift — surface it to the operator, don't silently ship
the noise or silently tune it away. Here the operator chose to triage all 9: 8
were forced-across-boundary or purpose-scoped (acknowledged `# sister-site: ok`
with a per-site reason), 1 left flagged (the running debt above). The operator's
"a catalog's collapse-to-canon is a CLAIM — classify forced/unforced/purpose-scoped
per case" discipline applies to the detector's OWN output, not just a hand-authored
catalog.

## Probe operator notes

- The probe is read-only; safe to run anytime. CLI:
  `python tools/cc/sister_site_probe.py [--json] [--include-info]`.
- Default scan (self-host): `tools/cc/hooks/*.py` (excluding `_hook_utils.py`; the
  probe's own comment keeps `_protected_zones.py` IN so its two helpers are
  shadow-detectable) + top-level `espalier/*.py`. Subdirectories
  (`espalier/scanners/`, `espalier/assets/`) are out of scope today.
- **Adopter trees (DEF-673, 2026-09-05).** When `tools/cc/hooks/` carries the
  `# espalier:managed` line `init` writes — or when there is no `espalier/` engine
  package beside the hooks at all (a pre-marker install, hand-copied hooks, a bare
  tree) — `probe_mode` answers ADOPTER: the
  gating scope is the adopter's own `.py` source (the whole tree minus junk,
  `tests/`, dot-directories and `tools/cc/` + `cc/`; `--roots <dir>` narrows and
  a pruned dir named there is walked), the deployed hooks are reported under
  HARNESS-INTERNAL and never gate, and the canon-miss / alias-miss arms run only
  over harness files (an adopter's `import numpy as np` is not rename drift).
  Also pruned: nested git repos (a `.git` dir, worktree file, or dangling
  symlink), and — on a fused tree (`.espalier-fusion` present) or wherever the
  vendored engine's two-module signature sits — the harness overlay at the
  manifest's OWN granularity (`espalier/` whole; `bench/corpus|baselines|end_to_end`
  and `bench/run_benchmark.py`; the two overlaid scripts; `tools/__init__.py` +
  `tools/review_agent_audit.py`, with `tools/cc` a deploy zone), so a host's own
  `bench/x.py` or `tools/x.py` stays in scope — mirrored from
  `fusion_manifest.HARNESS_INCLUDE` under a both-direction derive-by-test pin.
  Zone prunes match by on-disk IDENTITY (`os.path.samefile`), not spelling: a
  repo with an existing `Tools/` on APFS/NTFS gets `init`'s harness inside it and
  a literal `tools/cc` compare missed it (38 of 39 gating files were Espalier's).
  Name prunes are case-insensitive (`Tests/`). The mode rule checks the fusion
  marker before the engine package, and self-host needs the engine package AND an
  unmarked hooks tree (a vendored engine with no hooks is an adopter's). The
  failure-mode pass drove a real `fuse` before the prune existed: 97 of the 98
  files called "your source" were Espalier's and three gated; its second round
  drove `fuse --no-init`, a vendored engine, a `Tools/` host and a host with its
  own `bench/`; its third round closed all eight with earned reds and no blocking
  finding — the convergence signal — and traced the dangling-`.git` prune back
  to `espalier/_safe_walk.py::has_git_entry`, now the PRUNE predicate for every
  walker (`safe_rglob`, `analyze`, `repo_mode`, `session_start`'s zero-import
  copy) while `is_own_git_repo` stays strict. Wall-clock, measured: this repo's
  633 `.py` walk and parse in 1.1 s on the M2 Air; 4,000 synthetic modules in
  0.6 s, and 0.48 s with the maximal eleven-zone identity prune (reviewer-measured).
  The source tree (engine package present, hooks unmarked) — and every
  synthetic fixture, which now creates an empty `espalier/` for that reason — is
  self-host and unchanged. The SCOPE block says what was scanned; `scanned 0`
  means it never looked. Driven on a real `init` tree by
  `tests/test_sister_site_probe_adopter_tree.py`. **Open calibration question:**
  the 3+ identical clique / constant-clique thresholds were measured on THIS
  repo's corpus (see above) and now gate arbitrary adopter code unmeasured;
  `--accept-compression-debt` is the escape hatch, and a first-run false
  positive on ordinary adopter code is plausible and unrecorded — the first
  adopter report decides whether the adopter arm needs its own floor.
- **`tools/cc/` ROOT is entirely out of scope — measured 2026-08-06: 15 `.py`
  files there, 0 in the scan set.** `cognitive_blueprint.py`,
  `reflect_protocol.py`, `execution_plan.py`, `session_resume.py`,
  `sister_site_probe.py` itself — none is scanned. So a duplicate in the session
  machinery is found by reading, never by the probe, and the `--kind` row above
  is the worked example. Tracked as `DEF-20`. Do not read a clean probe run as
  "no duplication in `tools/cc/`"; it is "no duplication in `tools/cc/hooks/`."
- Threshold defaults to byte-identical body
  (`ast.dump(annotate_fields=False, include_attributes=False)` SHA-256).
  Don't lower without a parametrized regression test.
- DIVERGENT cliques are reported but never block — same name, different
  bodies (e.g. every CLI/hook has its own `main`) is legitimate.
- Per-function opt-out marker: `# sister-site: ok <reason>` placed
  directly above the `def` (blank lines between marker and def are
  tolerated; the marker does NOT cascade through decorators).
- Override at 0-C:
  `python tools/cc/sister_site_probe.py --accept-compression-debt "<reason>"`.
  The reason prints to stderr and exit becomes 0; record it in the
  per-pack blueprint reasoning entry.

## How the gate "earned" its place

Pre-TP-104 state had 9 `def _project_root()` copies — one in every hook.
The probe was authored against that state and validated by checking out
the `pre-pack-TP-104` git tag (`8e138f6`) in a worktree; the probe
reports exit 2 with `_project_root (identical, 9 sites)` as the headline
clique. Without this "earn the gate" step, the probe could ship with a
false-positive default tuned to current HEAD and silently miss the next
9-clique it was supposed to catch.

`tests/test_sister_site_probe_regression.py::test_tag_sha_matches_pin`
mechanically pins the tag SHA so a rebase / force-move / deletion is
caught by the test suite, not by silent calibration drift.

## Related contracts

- `tests/test_hook_helper_consolidation.py::TestHelperShadow` —
  same-name shadow detection (parametrized over public `_hook_utils.py`
  exports).
- `tests/test_marker_taxonomy.py` — every test file is deliberately
  marker-classified (catches "new test silently defaults to `unit`").
- `tools/cc/hooks/_protected_zones.py` re-exports — removed in
  TP-105-H once probe confirmed no other callers.
- `docs/REDEFINED_INFORMATION_REGISTRY.md` (internal: kept in the maintainers' private archive, not in the public repository, so a path rather than a link)
  (internal; `export-ignore`d, so the absolute link is what resolves for a
  reader outside the dev tree)
  — full catalogue of all 30 duplication classes (function-body,
  cross-file string, cross-language, needs-decision, out-of-reach)
  with management status + recommended SoT mechanism + proposed
  implementation pack (TP-109).
