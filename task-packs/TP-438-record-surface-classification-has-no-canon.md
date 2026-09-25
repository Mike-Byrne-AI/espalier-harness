# TP-438 — one fact, six registries: the record-surface classification has no canon

## Status

- **Kind: PACK**
- **State:** DRAFT
- **Version target:** `0.8.0b1`
- **Type:** class-fix — establishes a canon for a fact that is currently encoded six
  times, then closes the live divergences. Part hardening, part defect: **seven of the
  nine live cells are genuine misses**, driven, not theoretical.
- **Parent:** `docs/FAILURE_MODES.md` §13.28 (*a guard whose population excludes its
  subject*) and root `CLAUDE.md` Core Rule 13 (*classify a surface before you measure
  it*). This pack is the class-level form of both.
- **Predecessor:** `TP-436`, which shipped the first enforcement and declared its own
  bounds.
- **Supersedes:** this pack's own rev.1 (*"the record-surface guard's population excludes
  most of its subject"*), retracted at its 0-A gate. See *Why rev.1 was retracted*.

## Motivation

One fact — **"is this doc an append-only record, such that editing it to green a checker
falsifies it?"** — governs six independent registries across `espalier/` and `tests/`.
None derives from another. **Not one document is classified consistently by all six.**

Census, driven at authoring time (re-derive with the census probe in 438-A; do not trust
this table, it rots):

| registry | known-findings | session-archive | CONVERGENCE_LEDGER | RELEASE_LEDGER | FAILURE_MODES |
|---|---|---|---|---|---|
| `espalier/claim_extractor.py::FROZEN_RECORD_DOCS` | exempt | exempt | · | exempt | exempt |
| `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` | exempt | exempt | exempt | · | · |
| `tests/test_doc_test_citations.py::_EXCLUDE_FILES` | exempt | exempt | · | exempt | · |
| `espalier/scanners/retired_vocab.py::EXEMPT_FILES` | exempt | · | · | · | · |
| `espalier/scanners/freshness.py::FRAGMENT_SURFACE_DENYLIST` | exempt | · | · | · | · |
| `espalier/scanners/canon_verifier.py::EXEMPT_PROSE_FILES` | · | exempt | · | · | exempt |

**Unanimous: none. Intersection of all six: empty.**

### The two cross-contract exposures this turned up

Both are live, both were invisible to every existing gate, and both are Core Rule 13's
hazard in its exact stated form — *a contract that reds on a record surface can only be
greened by editing the record.*

- **`docs/RELEASE_FINDINGS_LEDGER.md` is a record to two contracts and a swept surface to
  a third.** `FROZEN_RECORD_DOCS` and `_EXCLUDE_FILES` both classify it a record;
  `_RECORD_SURFACE_DOCS` omits it, so `test_doc_source_citations` sweeps it. Driven with
  that module's own `_SOURCE_CITATION_RE`: **3 citations exposed**. The day one of those
  cited symbols is renamed, the only green move is editing the ledger.
- **`memory/CONVERGENCE_LEDGER.md` is the same defect mirrored.** `_RECORD_SURFACE_DOCS`
  classifies it a record — *"editing one to satisfy a citation checker falsifies the
  record it exists to preserve"*, its own words — while `_EXCLUDE_FILES` omits it and
  `_scan_surface_files` yields it. Driven with that module's own `_CITATION_RE`:
  **31 citations exposed.**

Two sibling contracts, written for the same reason, disagreeing about the same two files.

### The scanner-side misses

Driving `TP-436`'s own behavioural probe against the widened subject (3 doc-walking
scanners × 5 candidate surfaces, throwaway trees, **every control arm firing** — no cell
vacuous): **9 of 15 cells flag a record surface.** Only `known-findings.md` is broadly
exempt, which is precisely the file `09be6f5` fixed as an instance.

### Why rev.1 was retracted

Rev.1 proposed widening one guard's subject and deriving it from
`claim_extractor.py::FROZEN_RECORD_DOCS`, calling that "the canon". Three findings at its
0-A gate, all driven:

1. **There is no single canon to import.** Three sets exist, no two identical, and root
   `CLAUDE.md` Core Rule 13 names a *different* one (`_RECORD_SURFACE_DOCS`) as "the
   declared set". `FROZEN_RECORD_DOCS`'s membership criterion is *"exclude from
   audit_accuracy claim extraction"* — an adjacent question. Deriving from it imports a
   criterion written for a different contract. §14 says derive rather than restate;
   deriving from the wrong list is the failure §14 exists to prevent, wearing a
   principled face.
2. **Rev.1 could not have landed green.** Its 438-A widened the subject, its Scope (out)
   forbade fixing the misses that widening exposes, and its criterion 6 demanded a green
   suite. Driven: 3–7 red cells depending on which set it derived from. The three
   constraints were mutually unsatisfiable.
3. **Its 438-B escape hatch had already fired.** Rev.1 said to drive the tripwire over
   `espalier/*.py` first and abandon the widening if the false-positive rate blew the cap.
   Driven with `tests/test_scanner_exempt_files_resolve.py::_names_doc_surface`:
   **30 of 73 modules (41%) are tripwire-positive** against a `_TRIPWIRE_EXCEPTIONS` cap
   of 1. (73, not the 74 a raw `espalier/*.py` glob returns — `__init__.py` is excluded,
   matching that same module's `_scanner_modules()` convention. Re-derive rather than
   trusting either number.) Its stated fallback ("a narrower derived subset … is the
   better deriver") is *exactly* using the heuristic as the deriver, which that file's
   own header block argues fails silently.

Rev.1 fixed one of six sites, using the wrong canon, and could not have gone green. This
revision takes the class as the unit of work (Core Rule 12).

### ⚠ The designated class oracle is blind to this class

Core Rule 12 names `python3 tools/cc/sister_site_probe.py --json` as *the* oracle for
"is this defect one site of a class?". It returns **rc=0** on this tree. It cannot see
this class, for **three independent reasons** — and each defeats the remedy the previous
one suggests:

1. **Name-keying.** Its same-name clique detector groups strictly by symbol name, and the
   six registries share none (`FROZEN_RECORD_DOCS` / `_RECORD_SURFACE_DOCS` /
   `_EXCLUDE_FILES` / `EXEMPT_FILES` / `FRAGMENT_SURFACE_DENYLIST` /
   `EXEMPT_PROSE_FILES`).
2. **Scan scope.** `sister_site_probe.py::_default_scan_targets` walks
   `tools/cc/hooks/*.py` plus `espalier/*.py` **top-level only** — explicitly excluding
   `espalier/scanners/` — and never walks `tests/`. So **only 1 of the 6** registries
   (`claim_extractor.py`) is in the probe's population.
3. **Floor calibration.** The probe *does* have a cross-name detector —
   `sister_site_probe.py::_build_concept_overlaps` — which finds differently-named string
   collections whose elements overlap. It draws from the same scope-blinded target list,
   **and** its floors (`_CONCEPT_OVERLAP_MIN_SIZE = 4`, `_CONCEPT_OVERLAP_MIN_OVERLAP =
   4`) are too coarse for registries this small. Driven: the largest pairwise overlap
   among the six is **3** (`FROZEN_RECORD_DOCS ∩ _EXCLUDE_FILES`), below the floor. So
   even with the scope widened AND the name problem irrelevant, it would still not fire.

⚠ **438-E must record all three.** Each one alone teaches a remedy the next defeats:
rename them alike → still unwalked; widen the scope → the cross-name detector still
under-floors. **Recording is in scope (438-E); widening the probe is not** (Scope (out)).

## The class, stated

> A document is an append-only record or it is not. That single fact is a *component* of
> six registries, each of which mixes it with its own purpose-specific members. Because
> no registry derives the shared component from a canon, a doc added to one is added to
> none of the others, silently — and each registry's own cap is spent defending a
> hand-list rather than an exception.

The fix shape follows the repo's existing idiom rather than inventing one: every registry
becomes `derived_from_canon | purpose_specific_extras`, with **the cap applying only to
the extras**. Canon growth then never consumes a cap, and each cap keeps doing the job it
was written for — making a hand-added exception a deliberate, reasoned act.

⚠ **"Derives from canon" is realised two different ways, and the split is not optional.**
`espalier/scanners/*.py` are copied into adopter repos via `inspect.getsource()`, so
`tests/test_scanners.py::TestScannerSelfContainment::test_no_scanner_imports_from_espalier`
fails on **any** `from espalier` / `import espalier` line in a scanner — regardless of
whether the imported module is itself stdlib-only. Self-containment and stdlib-only are
**two constraints, not one**; an earlier draft of this pack conflated them and prescribed
an import that would have red on its first line. See 438-B for the two tiers.

⚠ **This forced duplication is itself a member of an already-registered class.**
`tests/test_forced_copy_parity.py` is the repo's register for duplications that span a
no-import boundary, and its docstring names *"a stdlib-only scanner ↔ the engine"*
explicitly. Tier 2 therefore adds a **lock to that register**, not a bespoke test —
`memory/grep-for-a-sibling-store-before-building-a-rival.md`. Driven at authoring: the
register holds 13 locks; the cross-boundary duplications that could have been unguarded
siblings (`_skip_nested_repos` ×11, `_safe_rglob` ×6, `iter_py_files` ×4,
`DEFAULT_EXCLUDE` ×5) are **all already pinned** — by lock 2-C and by
`tests/test_nested_repo_skip.py` / `test_safe_walk.py` / `test_scanner_nested_repo_skip.py`.
The class is in good health; this pack joins it rather than reopening it.

## Scope (in)

- **438-A — establish the canon and its written membership criterion.** A single
  record-surface set with the criterion stated in-file: *append-only; editing it to
  satisfy a checker falsifies the record.* Plus the census probe that derives the
  six-registry matrix mechanically, so the table above can never be a hand-copy again.
  `espalier/record_surfaces.py` (new), `tests/test_record_surface_canon.py` (new)
- **438-B — each registry derives from canon and declares its extras.** Six edits in
  **two tiers** (see the ⚠ above), each `canon | extras`, each extra carrying a
  `# sister-site: ok purpose-scoped: <reason>` marker naming what it omits or adds and
  why — the convention already in use across `tools/cc/hooks/` **and inside
  `espalier/claim_extractor.py` itself**, one of this pack's own six targets. Caps
  re-scoped to the extras.
  - **Tier 1 — import** (`espalier/claim_extractor.py`, both `tests/*.py` registries):
    these may import `espalier.record_surfaces` directly.
  - **Tier 2 — inline + parity lock** (`espalier/scanners/`'s three): the canon's members
    are duplicated per-file, and a **new lock in the existing register**
    `tests/test_forced_copy_parity.py` asserts each duplicate equals canon. This is not a
    workaround and not a new mechanism: that register exists for exactly this, and its
    docstring names this exact boundary — *"a forced duplication is one whose copies span
    a no-import boundary (`tools/cc/` ↔ `espalier/`, **a stdlib-only scanner ↔ the
    engine**, or the `_vendor/cc` mirror) … pinned instead."* It already carries 13 locks,
    one of which (**2-C**) pins a scanner-side constant across the five stdlib-only
    scanners — the same shape as this one.
- **438-C — close the two cross-contract exposures.** `_RECORD_SURFACE_DOCS` gains
  `RELEASE_FINDINGS_LEDGER`; `_EXCLUDE_FILES` gains `CONVERGENCE_LEDGER`. Both fall out of
  438-B automatically once each derives from canon; 438-C is the *proof* that they did,
  driven against the 3 and 31 exposed citations.
- **438-D — prove the scanner-side misses closed.** Like 438-C, these **close
  automatically** once 438-B's per-registry union puts the canonical members on
  `retired_vocab` / `freshness`'s path; 438-D is the **per-cell behavioural proof**, not
  a second edit. If a cell needs its own edit here, 438-B was under-derived and *that is
  the finding.* `MAX_EXEMPT_FILES` re-scoped to extras (see 438-B) is what makes it fit
  without a bare ceiling raise.
- **438-E — retire rev.1's hand list; re-home the contract.**
  `tests/test_scanner_exempt_files_resolve.py::CORPUS_REL` becomes a canon import; the
  class's honest-bound docstring is rewritten against the delivered population, counted
  at execution. Decide the contract's home now that its subject is no longer one file —
  the module's stated subject is *"does this exemption point at a real file?"*, which
  this contract has never answered. Record the `sister_site_probe` blind spot in
  `memory/fix-the-class-not-the-instance.md` — **naming both causes** (name-keying *and*
  the `espalier/scanners/` + `tests/` scan-scope exclusion, which is the dominant one),
  because recording only the first teaches a remedy that would not have worked.

## Scope (out)

- **Treating `docs/FAILURE_MODES.md` as a record surface.** Driven: it is swept for source
  citations today, carries 46 of them by `_SOURCE_CITATION_RE`, and is green. It is living
  canon — packs edit it routinely, including this one's parent sections. Its membership in
  `FROZEN_RECORD_DOCS` is a *partition-completeness* obligation of `EXCLUDED_DOC_GLOBS`,
  not a record claim, and 438-B must declare it as exactly that extra. **Do not let this
  scope-out read as "FAILURE_MODES is unprotected"** — it is protected by being *correct*,
  which is the opposite requirement.
- **Widening the doc-walker population past `espalier/scanners/`** (rev.1's 438-B). Its own
  escape hatch fired: 30 of 73 modules tripwire-positive against a cap of 1. The
  population-selection question is real and unanswered; it needs its own pack and an
  operator decision on the deriver, not a bundled guess. **Still a gap.**
- **Widening `sister_site_probe.py` to see cross-name registries.** Named in 438-E,
  deliberately not built here: it changes the oracle Core Rule 12 depends on, which is a
  governance change needing its own justification and its own earn-the-red.
  ⚠ **A trap for whoever takes that follow-up, created by this pack:**
  `_collect_constant_sites` drops any assignment carrying a `# sister-site: ok` marker
  *before* it becomes a `ConstantSite`, so 438-B's six markers make all six registries
  permanently invisible to both the clique and concept-overlap detectors. Zero effect
  today (reason 3 above means neither would fire anyway), but a future widening pass must
  revisit these six markers or scope-widening will accomplish nothing. Write this into
  438-E's recorded lesson, not just here.
- **`canon_verifier.EXEMPT_PROSE_FILES`' two live cells** (`known-findings`,
  `RELEASE_LEDGER`) — *reached only if 438-B's extras re-scoping frees the cap without a
  ceiling raise; otherwise deferred.* See Reach, and treat a ceiling raise as out of
  scope for this pack.
- **`_dedupe_key` / the corpus bullet grammar.** Unchanged from `TP-432` / `TP-436`: the
  stored corpus is keyed on both. Out of scope at any size.

## Implementation

### 438-A — the canon and the census probe

Two artefacts. The canon is a set with a criterion; the probe is what stops the census
above ever becoming a hand-copy again.

The canon lives in `espalier/` (not `tests/`) because three of its six consumers are
shipped engine code and `tests/` may not be imported by `espalier/`. It is stdlib-only —
but **stdlib-only does not buy importability for `espalier/scanners/`**, which is a
separate constraint (see the ⚠ in *The class, stated*). The three scanner consumers take
Tier 2 below.

⚠ **The membership criterion is the load-bearing artefact, not the list.** Write it so a
future reader can classify a *new* doc without asking anyone. The four current members
each satisfy it for a stated reason; a fifth must state its own.

⚠ **`docs/session-archive.md` is gitignored and untracked.** Any contract over the canon
must ask `git check-ignore` rather than demanding the file exist on disk — the exact
born-weak shape `14f834e` fixed once already (see `task-packs/FORWARD_LEDGER.md`, the
`_RECORD_SURFACE_DOCS` fresh-clone row). Reproducing it here would be the third occurrence.

### 438-B — derive-plus-extras, per registry, in two tiers

Six edits of **two** shapes. Common to both:

- take the subset of canon that is **on this registry's path** (a registry cannot exempt
  a surface it never walks — see Reach for the three not-reachable cells),
- union the purpose-specific extras,
- move the existing `MAX_*` cap to count **extras only**, and say so in the constant's
  comment,
- add a `# sister-site: ok purpose-scoped: <what this one omits/adds, and why>` marker.

**Tier 1 — import** (`claim_extractor.py`, `test_doc_source_citations.py`,
`test_doc_test_citations.py`). These import `espalier.record_surfaces` directly.

**Tier 2 — inline + parity lock** (`retired_vocab.py`, `freshness.py`,
`canon_verifier.py`). These duplicate the canon members as a module-level literal, and a
**new lock joins the existing register** `tests/test_forced_copy_parity.py`, asserting
each duplicate equals canon.

⚠ **The inlined copy MUST be its own named constant, bound under one identifier in all
three scanners** — specify it in 438-A and use it verbatim: `_RECORD_SURFACE_CANON`.
Without a fixed name there is nothing for a single generic lock to compare: the canon
members would be spelled straight into the existing combined `EXEMPT_FILES` /
`FRAGMENT_SURFACE_DENYLIST` / `EXEMPT_PROSE_FILES` literal, and no mechanism can recover
*which subset* of a combined literal was supposed to be canon. Each registry is then
built as `_RECORD_SURFACE_CANON | <extras>`. This mirrors the precedent's single
hardcoded `_CONST_NAME`.

⚠ **Two different comparisons, on two different objects — state both, they are not in
conflict.** The registry is a **superset** (`registry ⊇ canon-on-path`, because it also
holds extras). The isolated copy is an **equality** (`_RECORD_SURFACE_CANON ==
canon-on-path`). Only the second catches a stale non-canonical leftover surviving a
rename; only the first is true of the registry. A draft of this pack stated the superset
form in Pass criterion 1 and the equality form here without saying they addressed
different objects, which reads as a contradiction and invites an implementer to build
the weaker one.

⚠ **Join the register; do not build a rival.** The obvious-looking precedent,
`tests/test_memory_filename_constant.py`, is the **outlier** — a bespoke single-symbol
module that is *not* in the register. The register is the class's home: 13 locks, whose
docstring names this pack's exact boundary. Adding a 14th lock is also cheaper than a new
test module (no `tests/conftest.py::_MARKER_RULES` classification, no new test-file
surface for `surface-impact` to enrol).

⚠ **Follow lock 2-A's shape, not the register's default.** The register normally compares
*live copies to each other*, so an identical intentional edit to every copy stays green.
That is wrong here: `espalier/record_surfaces.py` is the **SoT**, and a copies-to-copies
lock would stay green if all three scanners drifted together away from canon. 2-A is the
register's stated exception — it *"pins the hook-side declaration to the engine SoT …
the canonical source it must mirror."* This lock is that shape.

⚠ **Two lessons carry over from `test_memory_filename_constant.py` even though its
mechanism does not.** Its AST-not-regex rule exists because a *text-scanning* guard was
defeated by a `: Final` annotation and passed **vacuously**; an import-and-compare lock
has no such failure mode and is strictly stronger, so use it. But its **sanity floor**
(`_MIN_EXPECTED = 12`) does carry: assert the pinned-scanner count equals the expected
number and that canon is non-empty, or a scanner silently dropped from the lock's list
leaves it passing over nothing.

⚠ **`FROZEN_RECORD_DOCS` is bound by a partition contract**
(`tests/test_doc_maintenance_classes.py::TestDocMaintenanceClasses`): it must equal the
exact-path entries of `EXCLUDED_DOC_GLOBS` minus `LIVE_STATE_MAPS`. Deriving it from canon
therefore constrains `EXCLUDED_DOC_GLOBS` too. Drive that test after this edit
specifically — it is the one place where "derive from canon" and an existing contract can
contradict each other.

⚠ **Two registries are at their cap right now** — `retired_vocab.MAX_EXEMPT_FILES` at 3 of
3, `canon_verifier.MAX_EXEMPT_PROSE_FILES` at 5 of 5. The extras re-scoping is what makes
438-D fit *without* a bare ceiling raise: canon members stop counting. **If it does not
work out that way for a given registry, stop and re-raise — do not raise a ceiling to
clear your own red.** That is the move this repo's cap discipline exists to prevent.

### 438-C — prove the two exposures closed

Each closure is proven against the citations it exposes, not against the registry's
membership. Membership is the fix; the driven sweep is the proof.

### 438-D — prove the scanner-side misses closed

⚠ `freshness.FRAGMENT_SURFACE_DENYLIST` is matched with `fnmatch`, so it mixes glob
patterns with exact paths. Today's canon members carry no `*`, `?`, `[` or `]`, so they
drop in cleanly — but a future canon member whose filename contains one would need
escaping. Note it at the insertion site; do not build a mechanism for a case that does
not exist yet.

Reuse `TP-436`'s probe harness. **Each (scanner × surface) cell needs its own trigger
text**, and this is stronger than rev.1 stated: writing one trigger to several files at
once makes `freshness.discover_fragments` **raise** `FreshnessError: duplicate fragment id`
rather than return a readable result. Probe one surface at a time, or vary the fragment id
per file.

**Every probe keeps its control arm.** The existing control (a non-exempt doc that must
always be flagged) is what stops "not flagged" passing for the wrong reason.

### 438-E — retire the hand list; re-home

Read `tests/test_scanner_exempt_files_resolve.py`'s module docstring before deciding the
home — it already names the two contracts as answering different questions, so the split
is half-argued in place.

⚠ **`CORPUS_REL` is a third access pattern the two tiers do not cover, and "becomes a
canon import" under-specifies it.** It is a *scalar* — used as one path (`root / rel`,
`CORPUS_REL in flagged`) — singled out from canon for a stated semantic reason ("the one
with an automated writer appending reviewer-authored text every round"), and canon has no
individually-addressable per-doc names. Do **not** invent named per-doc constants, and do
**not** select it by a `endswith(...)` string match. Keep it a literal and add the
membership assertion `CORPUS_REL in record_surfaces.CANON` — canon still governs it, and
canon does not grow a naming scheme it has no other use for.

## Affected symbols

### Changed-semantics
- `espalier/claim_extractor.py::FROZEN_RECORD_DOCS` *(438-B — hand tuple becomes
  `canon | extras`; the `EXCLUDED_DOC_GLOBS` partition constrains it)*
- `espalier/scanners/retired_vocab.py::EXEMPT_FILES` *(438-B/D)*
- `espalier/scanners/retired_vocab.py::MAX_EXEMPT_FILES` *(438-B — cap re-scoped to extras)*
- `espalier/scanners/freshness.py::FRAGMENT_SURFACE_DENYLIST` *(438-B/D)*
- `espalier/scanners/canon_verifier.py::EXEMPT_PROSE_FILES` *(438-B — splits two mixed
  criteria: record members derived, syntax-quoting members declared as extras)*
- `espalier/scanners/canon_verifier.py::MAX_EXEMPT_PROSE_FILES` *(438-B — cap re-scoped)*
- `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` *(438-B/C — gains
  `RELEASE_FINDINGS_LEDGER` by derivation)*
- `tests/test_doc_test_citations.py::_EXCLUDE_FILES` *(438-B/C — gains
  `CONVERGENCE_LEDGER` by derivation)*
- `tests/test_scanner_exempt_files_resolve.py::CORPUS_REL` *(438-E — stays a scalar
  literal; gains a `CORPUS_REL in record_surfaces.CANON` membership assertion, NOT an
  import — see the ⚠ in 438-E for why the two tiers do not cover this shape)*
- `tests/test_scanner_exempt_files_resolve.py::_CORPUS_PROBES` *(438-D — probe matrix
  grows on the surface axis; per-cell triggers)*
- `tests/test_scanner_exempt_files_resolve.py::TestDocWalkingScannersAccountForCorpus`
  *(438-E — the honest-bound docstring must be rewritten to the delivered population;
  a stale bound is worse than none)*

⚠ The three `espalier/scanners/` entries above change under **Tier 2**: each gains an
inlined canon literal alongside its extras, pinned by a new lock in
`tests/test_forced_copy_parity.py`. They do **not** gain an import — that is the BLOCK
this pack's own 0-A gate caught.

### Added-paths
- `espalier/record_surfaces.py` — the canon + membership criterion (stdlib-only; imported
  by the Tier-1 consumers, **parity-locked** against the Tier-2 scanners' inlined copies,
  never imported by them)
- `tests/test_record_surface_canon.py` — the canon's own contracts + the six-registry
  census probe

⚠ Both are new shipped/test surfaces. Run `python3 -m espalier surface-impact` on this
pack **before** executing and bundle what it names — a new `tests/test_*.py` must be
classified in `tests/conftest.py::_MARKER_RULES` or the full suite reds on
`test_marker_taxonomy`, and a new `espalier/` module carries provenance + integrity
obligations.

## Reach

Cells are `G<registry>-R<record>`. Registries `G1`–`G6` in Motivation-table order;
records `R1` known-findings, `R2` session-archive, `R3` CONVERGENCE_LEDGER, `R4`
RELEASE_FINDINGS_LEDGER. **Twelve omissions across the six registries**, each classified
below by driven evidence.

| id | omission | status | evidence |
|---|---|---|---|
| `TP-438:G2-R4` | source-citation sweep omits RELEASE_LEDGER | **CLOSED** (438-B/C) | `_swept_docs` yields it; 3 citations by its own `_SOURCE_CITATION_RE` |
| `TP-438:G3-R3` | test-citation sweep omits CONVERGENCE_LEDGER | **CLOSED** (438-B/C) | `_scan_surface_files` yields it; 31 citations by its own `_CITATION_RE` |
| `TP-438:G4-R2` | retired_vocab omits session-archive | **CLOSED** (438-D) | probe FLAGS; control fires |
| `TP-438:G4-R3` | retired_vocab omits CONVERGENCE_LEDGER | **CLOSED** (438-D) | probe FLAGS; control fires. Scans `memory/` |
| `TP-438:G4-R4` | retired_vocab omits RELEASE_LEDGER | **CLOSED** (438-D) | probe FLAGS; control fires |
| `TP-438:G5-R2` | freshness omits session-archive | **CLOSED** (438-D) | probe FLAGS; control fires |
| `TP-438:G5-R4` | freshness omits RELEASE_LEDGER | **CLOSED** (438-D) | probe FLAGS; control fires |
| `TP-438:G1-R3` | FROZEN_RECORD_DOCS omits CONVERGENCE_LEDGER | **NOT A GAP** | `DEFAULT_DOC_GLOBS` omits `memory/**`; the doc is never in the claim-extraction population. Adding it mints a ghost entry **and** forces a vacuous `EXCLUDED_DOC_GLOBS` row via the partition contract |
| `TP-438:G5-R3` | freshness omits CONVERGENCE_LEDGER | **NOT REACHABLE** | walks `docs/**/*.md`; `memory/` is off its path (probe: not flagged) |
| `TP-438:G6-R3` | canon_verifier omits CONVERGENCE_LEDGER | **NOT REACHABLE** | walks `docs/` + root files; `memory/` off path (probe: not flagged) |
| `TP-438:G6-R1` | canon_verifier omits known-findings | **CONDITIONAL** | probe FLAGS. Closes **only if** 438-B's extras re-scoping frees the 5/5 cap; a ceiling raise is Scope (out) |
| `TP-438:G6-R4` | canon_verifier omits RELEASE_LEDGER | **CONDITIONAL** | probe FLAGS. Same condition as `G6-R1` |

**Reach: 7 closed, 2 conditional, 3 not-gaps-or-not-reachable.** The three not-reachable
cells are the honest half of this table — a registry cannot exempt a surface it never
walks, and adding one would mint exactly the ghost entry
`TestScannerExemptFilesResolveOnDisk` exists to catch.

**Explicitly not claimed:** this does not close the doc-walker *population* question
(Scope (out)); it does not claim record-surface safety outside these six registries —
`tools/cc/` and the rest of `tests/` are unswept by any of them; and it does not widen the
class oracle that was blind to this class in the first place.

## Pass criteria

1. **The canon binds every consumer, by whichever tier applies to it.** Two assertions,
   on two objects: every registry **⊇** its canonical members on its own path, AND every
   Tier-2 scanner's isolated `_RECORD_SURFACE_CANON` **==** canon-on-path exactly (not
   merely a superset of it — a superset-only check cannot catch a stale non-canonical
   leftover, which is the vacuity mode this criterion exists to forbid). Tier 1 by
   import, Tier 2 by a pin-to-SoT parity lock in `tests/test_forced_copy_parity.py` with
   its own sanity floor on the pinned-scanner count. "Derived, not restated" is the
   *guarantee*; import is only one of the two mechanisms that delivers it, and a Tier-2
   registry that merely *looks* consistent without a lock has not met this criterion. Adding a fifth member to
   canon reds every registry that walks it, until each either binds it or declares an
   extra with a reason. Prove it by adding a fifth member temporarily — **and add it to
   `EXCLUDED_DOC_GLOBS` in the same edit**, or `test_doc_maintenance_classes.py` reds
   collaterally for an unrelated reason and the demonstration becomes unreadable.
2. **Each of the seven CLOSED cells earns its red** — driven against the unfixed
   registry first, by the same behavioural probe that proves it after. A cell that was
   only ever observed green proves nothing.
3. **Every probe keeps its control arm.** No new probe ships without one. Per-cell
   trigger ids, so `freshness.discover_fragments` returns a result rather than raising.
4. **No cap is raised to clear a red.** Caps are re-scoped to extras — a mechanical
   change to *what is counted*, with the reason in the constant's comment. If a registry
   still will not fit, that cell moves to NOT REACHED with a written reason and the pack
   lands without it. **This criterion constrains strength, not text: strengthening any
   gate in this pack's delivered artefacts is always in scope, and a defect found in one
   of them is this pack's to fix, not a follow-up.**
5. **The census table cannot rot.** The six-registry matrix in Motivation is regenerated
   by the 438-A probe, and a contract asserts the probe's output matches the live
   registries — so a future divergence reds rather than aging quietly into prose.
6. **The honest-bound docstring matches the delivered population**, counted at execution
   — not copied from this pack, which rots. Every remaining gap named by id.
7. **Baselines derived at execution:** full suite via `pytest -q` · `ruff check .` ·
   `python3 -m espalier audit .` · `python3 -m espalier provenance .` ·
   `python3 -m espalier pre-release . --skip-tests --skip-parity` · integrity refreshed
   and verified.

## Files touched

**New**
- `espalier/record_surfaces.py` — 438-A
- `tests/test_record_surface_canon.py` — 438-A ⚠ classify in `tests/conftest.py::_MARKER_RULES`

**Modified**
- `espalier/claim_extractor.py` — 438-B
- `espalier/scanners/retired_vocab.py` — 438-B, 438-D
- `espalier/scanners/freshness.py` — 438-B, 438-D
- `espalier/scanners/canon_verifier.py` — 438-B (conditional 438-D)
- `tests/test_doc_source_citations.py` — 438-B, 438-C
- `tests/test_doc_test_citations.py` — 438-B, 438-C
- `tests/test_scanner_exempt_files_resolve.py` — 438-D, 438-E
- `tests/test_forced_copy_parity.py` — 438-B (Tier-2 lock; next free letter after the
  register's current 13 — derive it at execution, do not assume `2-K`)
- `tests/conftest.py` — 438-A (marker classification for the new test module)
- `memory/fix-the-class-not-the-instance.md` — 438-E (the `sister_site_probe` blind spot)
- `docs/FAILURE_MODES.md` — only if §13.28's attestations change ⚠ **mirrored: run
  `python3 scripts/sync_asset_docs.py` after any edit**
- `CHANGELOG.md` — under `[Unreleased]`

**Unmodified on purpose**
- `tools/cc/sister_site_probe.py` — the blind spot is recorded, not fixed (Scope (out)).
- `docs/FAILURE_MODES.md`'s record status — it stays a swept, living-canon surface.

## Sub-task ordering

| # | Task | Checkpoint |
|---|---|---|
| **438-A** | Canon + membership criterion + census probe | criterion 5; `surface-impact` obligations bundled |
| **438-B** | Six registries derive from canon; caps re-scoped; `sister-site` markers | criteria 1, 4; `test_doc_maintenance_classes.py` driven specifically |
| **438-C** | Prove the two cross-contract exposures closed | criterion 2 (G2-R4, G3-R3) |
| **438-D** | Scanner-side misses; per-cell triggers + controls | criteria 2, 3 (G4/G5; G6 conditional) |
| **438-E** | Retire the hand list; re-home; rewrite the bound; record the oracle blind spot | criterion 6 |
| **438-F** | Full suite · ruff · audit · provenance · pre-release · integrity | criterion 7 |

**Ordering rationale.** 438-A first because every later step imports it. 438-B before
438-C/D because both are *proofs that 438-B worked*, not separate fixes — if a closure
needs its own edit, 438-B was under-derived and that is the finding. 438-E last among the
edits because the right home depends on what the delivered population turns out to be.

## Estimated effort

| Sub-task | Budget |
|---|---|
| 438-A | 60 min (the criterion is the hard part, not the list) |
| 438-B | 110 min (six registries in two tiers; Tier 2 joins an existing register rather than building a mechanism, which is cheaper than the 135 min an earlier draft budgeted for a bespoke AST module) |
| 438-C | 30 min |
| 438-D | 60 min (per-cell triggers; two scanners) |
| 438-E | 45 min |
| 438-F | 15 min + suite |
| **Total** | **~5h 20m** |

⚠ **438-B is the schedule risk, and it is a different risk than rev.1's.** Rev.1's was
population selection. This one is the cap re-scoping: if extras-only counting does not
free `canon_verifier`'s 5/5, the two `G6` cells move to NOT REACHED and the pack lands
without them — **that is a planned outcome, not a failure.** Do not raise the ceiling to
avoid it.

⚠ **The Tier-2 lock is where this pack is most likely to ship a weak guard.** An inlined
literal that is never actually compared to canon looks identical to one that is, in a
green run. Two things separate them: the **pin-to-SoT shape** (2-A's, not the register's
copies-to-copies default — which would stay green if all three scanners drifted together)
and the **sanity floor** on the pinned-scanner count. Drive the lock RED both ways — one
desynced scanner, and all three desynced together — before trusting it.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: <each of the seven CLOSED cells driven RED against the unfixed registry
  before its fix; a fifth canon member reds every on-path registry until bound or
  declared; each new probe's control arm fires; the census probe reds on a planted
  divergence; the Tier-2 parity lock reds on a deliberately-desynced scanner literal, and
  reds when all three scanners drift together away from canon — the failure a
  copies-to-copies lock would miss and 2-A's pin-to-SoT shape catches>
- Date:
