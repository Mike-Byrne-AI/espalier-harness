# TP-359 — Least-attacked subsystem review (blueprint state-machine · worktree · external-pins)

## Status
- Version target: current (self-host, pre-OSS-launch) — a review round, not a launch gate
- Change type: REVIEW-ROADMAP — routes ONE scoped convergence/behavioral defect-hunt over
  three engine subsystems no finder has ever deeply attacked; spawns lettered fix child-packs
  (TP-359a/b…) ONLY if a survivor clears adversarial refutation at BLOCKER/MAJOR. This pack is
  itself no code change — it delegates.
- **Kind: ROADMAP** (routes + sequences work; per the blueprint-authoring skill it MAY omit
  copy-ready Implementation + Pass criteria for the waves it delegates to children)
- Derived from: the **2026-07-26 lost-idea sweep** (workflow `wf_c28406bf-13f`) +
  `reports/lost-idea-sweep-2026-07-26.md` items **#5** (§B, source `Done/TP-266:27`) and **#28**
  (§C, source `reports/oss-release-convergence3-findings.json`). Both are `[wf-verified]`
  never-reviewed-surface flags, not known defects — the review lens exists to convert "unattacked"
  into either a confirmed defect (→ child pack) or a recorded null (the harness's correctness signal).

## Motivation

The lost-idea sweep's null-signal (55% of swept references already tracked/done/captured, zero
functional bugs) left two survivors that are the same shape: **engine subsystems the fan-out
review machinery has structurally never opened.** Item #5 is TP-266's own highest-value scope-out
— the blueprint state machine (`cognitive_blueprint` / `reflect_protocol` / `handoff`) plus
`worktree.py`, deferred at `Done/TP-266:27` as "a next independent review round, not a fix pack …
the blueprint chain is the highest-value target since the hooks drive it every session." Item #28
is the external-pin/diff family, which `oss-release-convergence3-findings.json`'s own completeness
critic named as "the single largest contiguous block of code no finder opened."

Neither gates the public flip — the sweep's bottom line is "the repo is clean enough to flip
public; no lost idea gates function." This pack exists so the flip does not *permanently retire*
these two coverage holes: a review round is coverage expansion, and the value is highest while the
harness still dogfoods on the exact code that drives it. Deferred to a post-flip (or one pre-flip)
review window per the operator; captured now so the target rows enter a tracker instead of leaking
again.

**Two premise corrections baked into scope below** (the sweep's snapshots drifted vs HEAD; changed
ground truth wins — see Scope (out)): worktree.py has **no concurrency** (43 LOC, pure plan
generator), and the "~913 LOC external_pins.py" is really the **four-file family** (external_pins
290 + external_diff 173 + external_fetch 174 + refresh_externals 276 = 913, confirmed exactly).

## Scope (in)

Each sub-task is a **review lane**, not an edit. A lane = a scoped fan-out finder pass (use the
`convergence-review-template` / `layered-review` scaffolds — finders emit FINDING_SCHEMA →
adversarial refute, default-refuted/oracle-confirmed → survivors persist via the two-hop bridge to
a corpus). The "Fix" of a lane is *run the lane and classify*; the "Earn the red" is the survivor
gate: **no survivor is promoted to a child pack without a reproduction that REDs before a fix and
would GREEN after** — the same earn-the-red discipline TP-266 applied to every one of its own fixes.

### Sub-task 1-A — Blueprint state-machine behavioral/concurrency lane
The hooks drive this chain every session: `session_start.py` advances the chain,
`subagent_stop.py` appends, `stop_gate.py` finalizes. The engine core is
`espalier/cognitive_blueprint.py` (699 LOC — `start_session`, `save_blueprint`,
`load_latest_blueprint`, `_prune_blueprints`, `list_blueprint_chain`,
`_truncate_blueprint_to_cap`), `espalier/reflect_protocol.py` (466 LOC — `run_reflect_pass`,
`build_reference_matrix`, `find_orphans`), and `espalier/handoff.py` (156 LOC —
`build_surface_handoff`, `write_surface_handoff`). None has ever been the *primary* target of a
fan-out finder (`Done/TP-266:27`: the TP-266 review touched only 7 of 72 modules and explicitly
deferred this chain; §2.12 EA-1 covers mechanical audit lanes only; INV-26 covers `recovery.py`
only — see Scope (out)).

**Seed leads for the finders (real, grep-confirmed at HEAD — the lane must confirm-or-refute each,
not assume):**
- `save_blueprint` (`cognitive_blueprint.py:209`) already `atomic_write_text`s both `latest.json`
  and the timestamped session file with an explicit "concurrent reader races us mid-write" comment,
  then calls `_prune_blueprints` (`:169`). Lane question: is the **prune-vs-read** and
  **prune-vs-write** ordering race-free the way the single-file replace is, or can a next-session
  `load_latest_blueprint` (`:85`) / `list_blueprint_chain` (`:226`) observe a pruned-away node or a
  half-pruned dir? The atomic-write of the pointer is hardened; the *set-level* operations around it
  are the un-probed part.
- `_load_json` (`:66`) failure modes on a torn/empty/half-written blueprint under concurrent
  SessionStart (two `claude` on one checkout — low likelihood, high blast: a crash here loses the
  whole orientation injection, the same class convergence3 flagged live at `session_start.py:351`).

**Fix (lane action):** run the scoped behavioral+concurrency finder pass over the three modules;
adversarially refute; classify survivors BLOCKER/MAJOR/minor/nit.
**Earn the red:** for any BLOCKER/MAJOR survivor, the lane must hand off a failing oracle
(a reproduction — e.g. an interleaving harness or a crafted torn-JSON fixture) that is RED at HEAD;
that oracle becomes the child pack's earn-the-red. A round that produces **no** BLOCKER/MAJOR is a
recorded null (Sub-task 1-C) — repeatedly finding nothing new across independent passes IS the
correctness signal (Core Rule 9), not a failure of the lane.

### Sub-task 1-B — `worktree.py` correctness lane (NOT concurrency — see premise drift)
`espalier/worktree.py` (43 LOC) appears in **no tracker** as a review target. TP-266's scope-out
labeled it "worktree.py concurrency" — that label is inflated: the module is a pure **plan
generator** (`build_worktree_plan`, `render_worktree_plan`) that emits git-command **strings** and
does one read-only `git branch --show-current` (`_git_branch`). There are no threads, locks, or
mutating subprocess calls, so "concurrency" is the wrong lens. The right lens is **command-string
correctness / injection**:

**Seed lead (real, grep-confirmed):** `build_worktree_plan` builds commands via f-string
interpolation of `repo_root.resolve()`:
```python
    commands = [
        f"git -C {repo_root.resolve()} worktree add ../{root_name}-lane-control -b {base_branch}-lane-control",
        ...
    ]
```
`root_name` has spaces `.replace(" ", "-")`'d, but the absolute `-C {repo_root.resolve()}` path and
the `../{root_name}-…` add-path are interpolated **unquoted**. A repo path containing a space (or a
`base_branch` with a shell metachar) yields a command a copy-paste operator runs broken (or worse).
Lane question: is that a real footgun for the operator who copies these commands, and if so is the
fix quoting/`shlex.quote` at emit time — a child pack, not this round.

**Fix (lane action):** fold `worktree.py` into the 1-A finder pass as a fourth module (it is small
enough to co-review); confirm-or-refute the quoting lead.
**Earn the red:** if the quoting footgun is confirmed MAJOR, the child pack's earn-the-red is a
test asserting `build_worktree_plan(Path("/tmp/a b"))` emits a shell-safe (quoted) `-C` path — RED
at HEAD (raw unquoted path), GREEN after. If refuted (plan strings are illustrative, never
`subprocess`-executed → operator-facing only, low blast), record the null.

### Sub-task 1-C — External-pin/diff family sweep lane
The never-swept surface item #28 calls "external_pins.py (~913 LOC)" is really the **four-file
external-pin/diff family** (premise correction, Scope (out)): `espalier/external_pins.py` (290 —
`parse_pin`, `list_pins`, `list_pins_lenient`, `_parse_frontmatter`, `compute_body_hash`),
`espalier/external_diff.py` (173), `espalier/external_fetch.py` (174 — `fetch_url`),
`espalier/refresh_externals.py` (276). Convergence3's completeness critic:
"867 lines … the single largest contiguous block of code no finder opened," with a flagged
speculative-unverified defect (`refresh-externals.yml --body-file` raw JSON in PR body;
`json.load` on possibly-contaminated stdout). The `/audit-accuracy` external-pin path is
documented-dormant (root `CLAUDE.md`), which lowers stakes but does not review the code.

**Fix (lane action):** run a scoped finder pass over the four-file family (frontmatter parsing
robustness in `_parse_frontmatter`/`parse_pin`; the lenient path `list_pins_lenient`; fetch/refresh
error degradation; the flagged untrusted-stdout `json.load`).
**Earn the red:** any BLOCKER/MAJOR survivor ships a RED reproduction (e.g. a malformed-frontmatter
fixture that traceback-aborts a batch, or a contaminated-stdout fixture) as the child pack's
earn-the-red. Null → recorded (1-D).

### Sub-task 1-D — Persist the round outcome (null OR child-pack spawn), regardless
Whatever the three lanes return, the round's own deliverable is a durable record so these surfaces
never re-enter the "never attacked" set:
- Append ONE cross-round row to `memory/CONVERGENCE_LEDGER.md` (BLOCKER yield + which modules were
  attacked-this-round). `memory/` is census-excluded (`provenance_census.py:71`) so a `TP-359`
  reference here is allowed.
- Add / update the FORWARD_LEDGER **review-target** rows (item #5 blueprint-chain, item #28
  external-pin family) from "never attacked" → "attacked <date>, N BLOCKER/MAJOR" — closing the
  tracker gap the sweep flagged.
- Spawn child packs per the rule below only for confirmed BLOCKER/MAJOR survivors.

**Child-pack spawning rule:** one lettered child pack per confirmed BLOCKER or MAJOR survivor
(`TP-359a`, `TP-359b`, …), each a full `Kind: PACK` with the lane's RED reproduction as its
earn-the-red. **Minors/nits → a single FORWARD_LEDGER capture-and-forget row, not a pack.** A
zero-survivor round spawns **no** child pack — it lands as the null-result record only.
**Fix (lane action):** author the ledger rows + any child-pack DRAFTs.
**Earn the red:** N/A (bookkeeping); the earn-red lives in each spawned child pack.

## Scope (out)
- **`espalier/recovery.py`** — the sweep (item #5) notes INV-26 already covers `recovery.py`
  (recovery-only lens); TP-266's scope-out also named it, but it is tracked, so this round does not
  re-target it. Confirmed present at HEAD (60 LOC).
- **The `tools/cc/` hook copies of the reviewed engine modules** — this lane reviews the
  `espalier/` engine. The engine↔hook *behavioral-parity* class (e.g. the `reflect_protocol`
  engine `build_reference_matrix` ↔ hook `build_matrix` STALE-1 divergence convergence3's critic
  named as the "sharpest angle") is **already closed at HEAD** — both copies carry the
  basename-uniqueness guard (see premise drift). The lane should NOT re-chase that specific closed
  lead; a systemic engine↔hook parity sweep is its own separate roadmap, not this one.
- **`bench/run_benchmark.py`** — convergence3 also flagged it never-runner-logic-reviewed (2233
  LOC), but that is item #2 / SUP-3 territory (a distinct bench-testability pack), tracked
  separately. Out of this pack's blueprint-chain + external-pin scope.
- **Any actual fix** — a review roadmap that also fixes is two changes fused; keeping the round
  pure means its null-result is trustworthy (a lane that "found and fixed" can't cleanly report
  zero). Fixes land in spawned child packs with their own earn-the-red.

## Affected symbols

_This ROADMAP edits **no** production symbol. The bullets below are the **review-targets** the
round's finders attack; each is grep-confirmed present at HEAD. Any edit lands in a spawned
`TP-359x` child pack (with its own `## Affected symbols`), never in this pack. The section exists so
`/scope-check` (`pack_manifest.parse_affected_symbols`) can walk the surface under review._

### Changed-semantics
_(review-targets — attacked, not edited, by this pack)_
- `espalier/cognitive_blueprint.py::save_blueprint` — atomic-write + prune ordering (1-A)
- `espalier/cognitive_blueprint.py::_prune_blueprints` — prune-vs-read/write race surface (1-A)
- `espalier/cognitive_blueprint.py::load_latest_blueprint` — torn/half-pruned read surface (1-A)
- `espalier/cognitive_blueprint.py::list_blueprint_chain` — set-level read under concurrent write (1-A)
- `espalier/reflect_protocol.py::run_reflect_pass` — every-10th-write hook driver behavior (1-A)
- `espalier/reflect_protocol.py::build_reference_matrix` — cross-ref matrix correctness (1-A)
- `espalier/handoff.py::build_surface_handoff` — handoff assembly (1-A)
- `espalier/handoff.py::write_surface_handoff` — handoff write atomicity (1-A)
- `espalier/worktree.py::build_worktree_plan` — unquoted command-string interpolation lead (1-B)
- `espalier/external_pins.py::parse_pin` — frontmatter parse robustness (1-C)
- `espalier/external_pins.py::_parse_frontmatter` — malformed-frontmatter degradation (1-C)
- `espalier/external_pins.py::list_pins_lenient` — lenient-path error handling (1-C)
- `espalier/external_fetch.py::fetch_url` — fetch degradation (partially hardened by TP-266 Fix 4; see premise drift) (1-C)
- `espalier/refresh_externals.py::run_refresh` — batch-refresh degradation / one-bad-pin abort lead (1-C)
- `espalier/refresh_externals.py::cli_main` — untrusted-stdout `json.load` / `--body-file` lead (1-C)

### Added-paths
_(none in this pack — child packs, if spawned, add their own tests)_

## Pass criteria
- **Round completeness:** all three lanes (1-A blueprint chain incl. worktree, 1-C external-pin
  family) ran with a scoped finder → adversarial-refute → persist bridge; a corpus path exists
  under `reports/` (gitignored) with the survivors-slim + refutation record.
- **Earn-red discipline honored:** every survivor promoted to a child pack carries a RED-at-HEAD
  reproduction; no child pack is spawned on an un-reproduced claim (agent-blocker-citations-are-
  claims prior, `docs/STANDING_PRINCIPLES.md §3`).
- **Null is a valid pass:** a zero-BLOCKER/MAJOR round PASSES — it records the null in
  `memory/CONVERGENCE_LEDGER.md` + flips the two FORWARD_LEDGER review-target rows to
  "attacked <date>, 0 BLOCKER/MAJOR." Read the round by BLOCKER-yield trend, not finding count
  (Core Rule 9).
- **Tracker closed:** after 1-D, `grep` of `task-packs/FORWARD_LEDGER.md` shows both the
  blueprint-chain (#5) and external-pin-family (#28) rows present with an attacked-date — the seam
  the sweep flagged is closed.
- **No shipped-surface literal leak:** this ROADMAP itself edits no shipped surface, so the gate is
  trivially clean; **any spawned child pack** must satisfy the full gate — `pytest -q` green;
  `ruff check .` clean; `python3 -m espalier audit .` 0/0; and **no `TP-NNN` literal in any shipped
  surface it touches** (espalier/, docs/, scripts/, tools/cc/ scanned except `_vendor/`). The
  `memory/CONVERGENCE_LEDGER.md` round row may reference `TP-359` because `memory/` is
  census-excluded (`provenance_census.py:71`).

## Files touched
- **Modified (by this ROADMAP):**
  - `task-packs/FORWARD_LEDGER.md` (tracked since 2026-09-21; it was gitignored when this was written) — flip #5 + #28 review-target rows to attacked (1-D).
  - `memory/CONVERGENCE_LEDGER.md` — one cross-round row (1-D); census-excluded, TP-359 ref allowed.
- **New (by this ROADMAP):**
  - `reports/*.json` (gitignored) — the round's fan-out corpus + survivors-slim.
  - `task-packs/Deferred/TP-359a-*.md`, `TP-359b-*.md`, … — **conditional**, one per confirmed
    BLOCKER/MAJOR survivor only.
- **Unmodified-on-purpose (review-targets, edited only by child packs):**
  `espalier/cognitive_blueprint.py`, `espalier/reflect_protocol.py`, `espalier/handoff.py`,
  `espalier/worktree.py`, `espalier/external_pins.py`, `espalier/external_diff.py`,
  `espalier/external_fetch.py`, `espalier/refresh_externals.py`.
- **Mirrors:** none — this pack touches no `.claude/{agents,commands,skills}/` (no
  `sync_claude_mirrors.py`) and no `tools/cc/*.py` (no `sync_vendor_cc.py`). A spawned child pack
  that edits either MUST run the corresponding sync step (both are byte-parity-pinned — never
  hand-edit a mirror).

## Sub-task ordering
1. **1-B** worktree correctness lane — smallest surface (43 LOC), fastest to confirm-or-refute the
   quoting lead; builds momentum + surfaces the review-environment early. Checkpoint: quoting lead
   classified (MAJOR→child, or refuted→null note).
2. **1-A** blueprint state-machine lane — the highest-value/heaviest lane (1421 LOC across three
   modules, the hooks drive it every session). Run after 1-B so worktree can co-review in the same
   pass. Checkpoint: corpus written; survivors classified with RED reproductions.
3. **1-C** external-pin family lane — the largest contiguous unopened block (913 LOC / four files).
   Checkpoint: corpus written; the flagged untrusted-stdout lead confirmed-or-refuted.
4. **1-D** persist — append the CONVERGENCE_LEDGER round row + flip the two FORWARD_LEDGER
   review-target rows + spawn child-pack DRAFTs for confirmed BLOCKER/MAJOR only. Checkpoint:
   `grep` shows both review-target rows attacked-dated; child DRAFTs (if any) written; stamp Landing.

## Estimated effort
- 1-B worktree lane ~30m · 1-A blueprint-chain lane ~2–3h (fan-out + refute + concurrency
  reproduction if a survivor) · 1-C external-pin lane ~1.5–2h · 1-D persist + optional child DRAFTs
  ~30m (+ ~1h per spawned child pack).
  **Total ≈ 4.5–6 h for the review round itself**, exclusive of any spawned child packs.

## Landing
- State: DRAFT
- Commits: —
- Suite: — (no code change in this ROADMAP; child packs carry their own suite deltas)
- Earn-the-red: (planned) each lane promotes a survivor to a child pack ONLY with a RED-at-HEAD
  reproduction (interleaving/torn-JSON for 1-A; unquoted-`-C`-path assertion for 1-B;
  malformed-frontmatter / contaminated-stdout fixture for 1-C). A zero-survivor round lands as the
  recorded null — the correctness signal, not a gap.
- Date: —
- Deferred/notes: authored 2026-07-26 from the lost-idea sweep (`wf_c28406bf-13f`,
  `reports/lost-idea-sweep-2026-07-26.md` #5 + #28). **Premise drift recorded (changed ground
  truth wins):** (1) `worktree.py` has NO concurrency — 43 LOC pure plan generator; reframed 1-B as
  a command-string-correctness lane. (2) "external_pins.py ~913 LOC" is the four-file external-pin
  FAMILY (290+173+174+276=913, confirmed); `external_pins.py` alone is 290. (3) `external_fetch.
  fetch_url` was partially hardened by TP-266 Fix 4 (malformed-URL guard, `7e2d016`) — not wholly
  un-attacked, but the family was never *swept*. (4) The convergence3 "sharpest angle"
  (reflect_protocol engine↔hook STALE-1 parity divergence) is CLOSED at HEAD — both `build_reference_matrix`
  and hook `build_matrix` carry the basename-uniqueness guard — scoped OUT so the lane doesn't
  re-chase a closed lead. Operator provisional reco: defer (agreed — it's coverage expansion, not a
  known defect, and the sweep confirms nothing here gates the flip).
