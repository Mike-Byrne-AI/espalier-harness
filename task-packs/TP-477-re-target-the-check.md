# TP-477 — Re-target the check: live classes whose fix teaches one reader every shape, and the target that would see them all

## Status

- Version target: after `0.8.0b2`. Each candidate is its own lane with its own Task 0, and becomes a lettered child pack (TP-477a, TP-477b, ...) only if its Task 0 survives.
- Type: assessment (this document) + refactor (the children).
- **Kind: ROADMAP.** No candidate here is copy-ready. Each carries a hypothesis, the oracle that decides it, and a refuting result that ends it.
- Ledger: one §3 row names this pack (filed 2026-10-07). It re-routes no member row. A child that survives its Task 0 re-routes its class's rows through `tools/cc/ledger_row.py`.
- Gate, the operator's words on 2026-10-07: "If we have found a method that allows us to eventually trim code and make things more reliable, lets explore if moving controls to different layers and targets has been underutilised as a technique."
- Siblings:
  - `TP-476` is this method applied to the guard; it was already drafted.
  - `TP-475` carries the questions that route a class here, and the lineage that will flag the next candidate.
- Provenance: the Windows clone, 2026-10-07. Class facts are read from `task-packs/FORWARD_LEDGER.md` (each class's own "Unit of work" and "Why one class" paragraphs); mirror facts are read from `memory/asset-mirroring.md`. Nothing here was driven.

## Motivation

**The technique.** `TP-475`'s Motivation separates two ways of moving a control:
- **Consolidation** asks the same question in one place: one chokepoint, one derived list. The repo does this often, and doctrine names it (§14, §18).
- **Re-targeting** changes what is checked:
  - the effect instead of a prediction of it;
  - the producer instead of every shape at the consumer;
  - a tool that enumerates instead of a hand list.

  It is rare here, and no doctrine names it.

Consolidation stalls when the one remaining question is "recognise every shape". Each new shape is then one more fix in the same place, and that place grows: the guard parser grew by +1,446 net lines and 14 fix commits from 2026-09-24 to 2026-10-07.

**The routing questions** (`TP-475` Task 4) pick the candidates:
1. State the job without naming the mechanism.
2. Effect or prediction?
3. Closed input of ours, or open input of someone else's?
4. Would a slip produce it?
5. Already moved once, with defects arriving at the new site?

A live class is a candidate when question 1 can only be answered in the mechanism's own words today, and question 3 has an answer that removes the enumeration.

**The hope, and the caveat.** The operator asked for a method that "eventually trims code and makes things more reliable".
- Re-targeting can delete code, because a reader that learned many shapes becomes a check of one form, or a tool's output.
- The counter-warning still applies: the new target brings its own defects (`memory/a-fixed-fail-open-can-move-rather-than-close.md`). Each child measures what it deletes and what it adds, and claims neither in advance.

**The named users (§16):**
- the maintainer who adds the next citation form, ledger row form or mirror, and must remember to teach a reader that form or the gate goes quiet;
- the adopter whose tree inherits the same readers.

## Scope (in) — the candidates

Each candidate states: the job without the mechanism, today's target, the proposed target, what could be trimmed (hypothesised), and its Task 0.

### Candidate A — `§C32`: the ledger's enforcement parses every row shape the ledger uses

- **The job, without the mechanism:** every ledger row is well-formed and every cross-reference it makes resolves.
- **Today's target:** detectors in `tests/test_forward_ledger_completeness.py` and its neighbours, one per malformation shape found. The class's own "Why one class" asks for one instance of each shape seeded into a fixture ledger, and a required red.
- **Proposed target (re-target to the producer):** `tools/cc/ledger_row.py` already writes rows. Make its formatter the definition of a well-formed row, and add one round-trip check: parse each member row's cells and re-render them with the formatter; any row that does not round-trip is malformed, whatever its shape.
  - Hand edits that keep the canonical form pass; anything else is caught without a detector for its shape.
  - Hypothesis: the shape detectors among the class's acceptance items collapse into this one check.
- **What it does not reach:** the class's cross-reference members (Scope-out pack ids that must exist, DEF ids in tests against open rows, the strike gate on a citing pack). They are reference checks, not shape checks, so this candidate leaves them where they are.
- **Task 0 (A-0):**
  - Oracle: classify each live `§C32` member, derived from the class section at execution time, as **shape** or **reference**, from its row's headline. Then prototype the round-trip over the current ledger in a scratch script: how many live member rows fail it today?
  - Refuting result, either one:
    - fewer than half the members are shape members;
    - more than a tenth of the current rows fail the round-trip for reasons that are formatter limits, not real malformation. The formatter then is not the definition yet.
  - Exit: stop and re-raise with the classification and the failing rows.

### Candidate B — `§C31`: the citation resolvers learn every anchor shape the repo writes

- **The job, without the mechanism:** every citation in the docs points at something that exists.
- **Today's target:** regexes in `tests/test_catalog_self_consistency.py` widened per shape. The class says why it exists: "each shape was added to the sweep separately and each new shape re-opened the same rot".
- **Proposed target, two options for Task 0 to decide:**
  - **B1, observe the effect.** Resolve each citation by the mechanism its reader uses:
    - a heading anchor through parsed headings and the renderer's slug rule;
    - a pytest node id through `pytest --collect-only` (the class already asks for this sweep);
    - a commit hash through `git rev-parse` (the class already asks for this too).

    A new shape needs no regex, as long as it uses a mechanism the resolver already runs.
  - **B2, own the producer.** Constrain citations to a small set of written forms, checked at write time, so the readers need only those forms.
- **Task 0 (B-0):**
  - Oracle: list the citation forms in `docs/` and `memory/`, and for each, whether B1 can resolve it by an existing mechanism. Read headings and links, not content.
  - Refuting result: more than a quarter of the forms have no mechanism B1 can run. Those are free-text pointers. B1 then reaches too little, and B2 must be costed instead.
  - Exit: re-raise with the form census.

### Candidate C — `§C36`: each named assertion is hand-mutated, then tightened until it reds

- **The job, without the mechanism:** every gate test fails when the defect it guards against is introduced.
- **Today's target:** a hand-written mutation per named assertion (`docs/STANDING_PRINCIPLES.md` §19). The class states its own limit: "no scanner finds weak assertions — so the member list is the whole claim".
- **Proposed target (re-target to a tool that enumerates):** a mutation-testing tool run over the modules the gate tests guard. Its surviving mutants are a *measured* population of weak assertions, and that is the scanner the class says does not exist.
  - Hypothesis: the tool finds the class's named members and more, and a periodic run replaces hand discovery. §19 stays the authoring rule for a new gate.
- **Task 0 (C-0):**
  - Oracle: run one mutation-testing tool over the module of one live `§C36` member, with the member's test file as the suite, on a host the tool supports.
    - Name the tool and its version in the record. Windows support differs by tool, and the result must say which host ran it.
    - Then check: does the member's weakness appear as a surviving mutant?
  - Refuting result: run on three members, the tool surfaces fewer than two. The class's weaknesses then sit in fixtures and allowlists the tool does not mutate.
  - Exit: record the run and stop. The hand method stays.
  - Cost line, recorded either way: the tool's wall time on one module.

### Candidate D — the byte-copy mirrors

- **The job, without the mechanism:** what ships to an adopter equals the source the maintainer edited.
- **Today's target:** committed byte-copies, a sync script per row, and a parity test per row. The census lives in `espalier/mirror_registry.py`, and root `CLAUDE.md` calls the sync "the single most-missed step".
- **Why the copies are committed** (`memory/asset-mirroring.md`):
  - `espalier/` never imports `tools/`, so the wheel needs a deploy source inside the package;
  - the dogfooding example ships in the sdist;
  - some rows are rendered or chained, not copied.
- **Proposed target (re-target to the packaging layer), for plain whole-tree byte-copy rows only:** the build step copies the source into the package at build time, so parity holds by construction. In a source checkout, the deploy resolver reads the source path directly. The copy then exists only in built artifacts, and the sync step and the parity test for that row go away.
  - Rendered and chained rows are out: their mirror is a transform, not a copy.
- **Task 0 (D-0):**
  - Oracle: for each registry row whose kind is whole-tree byte copy, answer two questions.
    - (1) Can the build backend in `pyproject.toml` place the source into the package at build time? Name the mechanism and whether it needs a custom build step.
    - (2) Does any consumer read the committed copy in a source checkout for a reason other than its presence? For example, `espalier selfcheck` runs against the installed mirror on purpose.
  - Refuting result, either one:
    - (1) needs a custom build step that the release gates (`scripts/fresh_clone_gate.py`, the clean-checkout workflow) cannot exercise;
    - (2) finds a consumer that needs the copy in source mode.

    The committed copy is then the cheaper design.
  - Exit: record why in `memory/asset-mirroring.md` and stop. The record is worth having, because the question will be asked again.

## Scope (out)

- **The guard's location jobs.** That is `TP-476`.
- **`§C75`** (every adopter-side stand-down says so). Its fix extends the fail-open voice gate, which is consolidation. That gate has already drawn defects of its own (`TP-475` Motivation), so question 5 comes first: what would observe a silent stand-down as an effect? That is not yet answered, and it gets no candidate until it is.
- **`§C37`** (four hand-kept gate populations become derivations). It is already a consolidation move with its own pack-sized unit, and not a re-targeting candidate.
- **Any change to a class's members by this document.** Children re-route rows; this ROADMAP does not.
- **A census or generator of command spellings,** for any candidate (`docs/CLASSIFIER_FALSE_POSITIVES.md`).

## Task 0 — Verify (the roadmap's own)

**0-A Is each candidate's class still live and still enumeration-shaped?**
- Oracle: the class index row and the class section in `task-packs/FORWARD_LEDGER.md` at execution time. Read the live count and the "Why one class" paragraph.
- Refuting result, per candidate:
  - the class has no live members;
  - or its paragraph no longer describes one reader learning shapes (it was re-scoped since 2026-10-07).
- Exit: drop that candidate.

Then run each surviving candidate's own Task 0 (A-0 to D-0), in its own lane, in any order. Stop each where it is refuted.

**Hygiene, binding on every task:**
- Rows are read by headline, one at a time.
- No spelling roster is built.
- C-0 runs the mutation tool on a module's own test file only, not on the full tier, because a mutation run multiplies the suite's wall time.

## Relevant memory

Recent pattern, read 2026-10-07: the repo's moves of a control were mostly consolidations, and in at least three of them (the path chokepoint, the fail-open voice gate, the line-ending canon) defects kept arriving at the consolidated site.

| Entry | Where |
|---|---|
| Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` §14 |
| Name the mutation before you write the gate | `docs/STANDING_PRINCIPLES.md` §19 |
| A fixed fail-open can move rather than close | `memory/a-fixed-fail-open-can-move-rather-than-close.md` |
| Completeness gate must discover its population | `memory/completeness-gate-must-discover-its-population.md` |
| Fix the surface the reader consumes | `memory/fix-the-surface-the-reader-consumes.md` |
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |

Resolved by a history read of `memory/` and `docs/` for moves of a control (2026-10-07, second session), plus the class sections named above. Re-derive them if the pack has been sitting.

## Implementation

None at roadmap level. Each candidate that survives its Task 0 becomes a child pack, which carries copy-ready Implementation, earn-the-red per fix, and its own Reach over its class's members by id.

## Affected symbols

### Changed-semantics
- (none -- a ROADMAP; each child pack declares its own)

### Renamed
- (none -- a ROADMAP)

### Added-paths
- (none -- a ROADMAP)

### Removed-paths
- None.

## Reach

This roadmap closes nothing itself. Each child states its reach over its class's members by id, derived from the class section at execution time.

| Item | Status | Evidence |
|---|---|---|
| `§C32` members | **NOT REACHED** by this roadmap | Candidate A: shape members only, if A-0 survives; reference members not reached by A |
| `§C31` members | **NOT REACHED** by this roadmap | Candidate B, if B-0 survives |
| `§C36` members | **NOT REACHED** by this roadmap | Candidate C, if C-0 survives |
| mirror registry rows (whole-tree byte copies) | **NOT REACHED** by this roadmap | Candidate D, if D-0 survives |
| `§C75` members | **NOT REACHED** | Scope (out): question 5 is not yet answered |

## Pass criteria (roadmap)

- 0-A is recorded per candidate.
- Each candidate's Task 0 is recorded with its oracle output, and either a child pack exists or the refutation and its exit are written here.
- A child claims deleted code only by measurement (lines removed and added, in its own Landing), never by this roadmap's hypothesis.

## Files touched

- **This roadmap:** none beyond this file and its §3 row.
- **Children:** each declares its own. Expected surfaces, for orientation only:
  - A: `tools/cc/ledger_row.py`, the ledger completeness tests;
  - B: `tests/test_catalog_self_consistency.py`;
  - C: a mutation-tool configuration, and a record of the run;
  - D: `pyproject.toml`, `espalier/mirror_registry.py`, the deploy resolver.

## Sub-task ordering

1. 0-A for all four candidates (about 30 minutes, reading only).
2. The candidates' own Task 0s, cheapest first: A-0 (a scratch script over the ledger), B-0 (a form census), D-0 (reading the build backend's documentation and the registry), then C-0 (needs a supported host and a tool install).
3. A child pack for each survivor, authored with the `blueprint-authoring` skill.

## Estimated effort

| Step | Budget |
|---|---|
| 0-A | 0.5 h |
| A-0 | 1 h |
| B-0 | 1 h |
| C-0 | 2 h (tool setup on a supported host) |
| D-0 | 1 h |
| **Total for the roadmap's Task 0s** | **about 5.5 h**; children are budgeted in their own packs |

**Most likely to be wrong:**
- that the ledger formatter can be the definition of a well-formed row (A-0's second refutation);
- that a mutation tool sees weaknesses that sit in fixtures (C-0);
- that the build backend can place sources at build time without a custom step the release gates cannot exercise (D-0).

## Landing

- State: ROADMAP
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
