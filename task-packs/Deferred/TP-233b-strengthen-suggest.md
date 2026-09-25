# TP-233b-suggest — `strengthen`: the AI scaffold-suggestion layer

## Status
- Version target: 0.9.x (AFTER TP-233b-core lands and is trusted)
- Kind: PACK
- Change type: feature (command-body orchestration — agent dispatch; NO new engine)
- Parent: TP-233 (roadmap). Sibling: TP-233b-core (the mechanical engine — MUST land first).
- Gated behind: TP-233b-core (needs the ranked report as input) + the OSS launch.
- Depends on: TP-232 golden examples (shipped `60b233d`) — the scaffold templates it names.
- Hardened by an adversarial pack review (2026-07-01, `wf_a961394a-ade`): 1 BLOCK / 2 WARN / 2 NIT folded in — see the ⚠ markers.

## Motivation
On top of TP-233b-core's mechanical ranked report, this layer turns the top-N
gaps into **reviewable starting-test scaffolds** by dispatching the `test-writer`
agent — the AI-assisted half of strengthen. It is deliberately the *smaller,
softer* pack: it adds no engine, only orchestration in the command body, and it
lives entirely behind the "suggest, don't auto-trust" guardrail. The mechanical
spine (which symbols are untested, in what risk order) stays authoritative and
un-hallucinable; the agent only *drafts tests for a pre-ranked list it is handed*.

## Where this lives (architecture)
The dispatch is **prose in `.claude/commands/strengthen.md`**, executed by Claude
Code via the Task tool at session runtime — the same *tool* as `/test-this` step 2
and `/implement-pack` step 0-A. ⚠ **NB the precedent contrast:** `/test-this`
DELIBERATELY writes the test to disk; suggest mode must NOT. There is **no Python
Task API** — dispatch cannot be invoked from `espalier/` or from pytest, which
shapes what is and isn't mechanically testable (see Pass criteria). A `--suggest`
opt-in flag (default off) keeps the pure-mechanical `espalier strengthen`
fast and agent-free for CI use.

## The four non-negotiable contracts (hard requirements — bake in + test what CAN be tested)
1. **Suggest, don't auto-trust — with a MECHANICAL backstop, not prose hope.** ⚠ The
   `test-writer` agent frontmatter grants `Write` + `Bash(git *)` and its whole design is
   to write test files; a prose "return the body only" fights its default with nothing
   enforcing it, and a git-capable sub-agent shares the live worktree/index
   ([[subagent-git-access-mutates-shared-tree]]). So enforce it one of two ways: **(a)**
   dispatch `test-writer` in suggest mode with a **restricted tool set (no `Write`, no
   `Bash(git *)`)** so "return body only" is mechanical; OR **(b)** after the dispatch loop,
   run `git status --porcelain` in the command body and **ABORT + report a contract
   violation** if any new `tests/` file or index change appeared. No `git add`, no
   auto-write, no green checkmark. Prefer (a).
2. **Characterization honesty — ONE pinned canonical string.** ⚠ "verbatim in spirit" is
   un-assertable and the `examples/golden/test_g4_characterization.py` file does not contain
   the caveat as one contiguous sentence. Define ONE canonical constant
   `CHARACTERIZATION_CAVEAT` (in `espalier/strengthen.py`, cross-checked against the g4
   header wording so there is a single source of truth), have the engine emit it into every
   scaffold stub header, and assert BOTH the emission and the earn-the-red against that exact
   constant.
3. **Scope the review + log the bound.** Dispatch `test-writer` for the top-N only
   (default N = `min(top_n, 10)`); state "suggested scaffolds for the top {N} of {U}
   untested symbols; {U-N} not covered." No silent truncation.
4. **Mechanical spine, advisory ranking.** `test-writer` is handed the **pre-ranked** symbol
   list from core's JSON and told "draft a scaffold for each, in this order." It does NOT
   re-rank or discover symbols. Its own priority opinion is discarded.

## Scope (in)
- **S1** Extend `.claude/commands/strengthen.md`: a `## Suggest mode` section (gated on
  `--suggest`) that (a) reads `reports/strengthen_report.json`, (b) chooses a golden pattern
  per gap — **G4 characterization** when the repo is low/zero-coverage (mode-b or few tests),
  **G2 earn-the-red** where baseline coverage exists, (c) dispatches `test-writer` via Task for
  the top-N with the symbol, its `file:line`, ⚠ **an explicit golden FILE PATH to read**
  (e.g. "follow `examples/golden/test_g4_characterization.py` — read it first"; the agent has
  no built-in knowledge of the `G1..G4` labels), the restricted tool set (contract §1a), and
  the `CHARACTERIZATION_CAVEAT` constant, (d) collects the returned scaffolds into a written
  `strengthen_suggestions.md` (never committed), (e) prints the "review + run + commit yourself"
  note, (f) runs the §1b git-status backstop if (a) restricted-tools wasn't used.
- **S2** Add `--suggest` (default False) to the `strengthen` subparser in `cli.py`; when set,
  `cmd_strengthen` emits `"suggest_requested": true` in the JSON. ⚠ `cmd_strengthen` reads it
  via `getattr(args, "suggest", False)` — the repo convention (`cmd_pre_release` uses
  `getattr(args, "skip_tests", False)`) — so core's existing `TestCmdStrengthen` (which builds a
  Namespace via `_ns()` with no `suggest` kwarg) stays green instead of raising `AttributeError`.
- **S3** Golden-pattern pointer integrity: a pytest test asserting every pattern the command can
  name (`G1..G4`) maps to a live `examples/golden/test_g*.py` file. ⚠ Add
  `# pytest-marker: default-unit` to `tests/test_strengthen_suggest.py` (NEW stem → else
  `test_marker_taxonomy` reds the full suite).
- **S4** Mirror sync (`sync_claude_mirrors.py`) + provenance-clean command doc + CHANGELOG.

## Scope (out)
- Auto-writing/committing tests (contract §1). Ever.
- Re-ranking or symbol discovery by the agent (contract §4).
- New engine logic — all mechanical work is TP-233b-core's (the `CHARACTERIZATION_CAVEAT`
  constant is the one small addition, and it belongs to core's module).
- The super-prompting pipeline and the Vibe-Guide consumer surface — stay in the fork.

## Affected symbols

### Changed-semantics
- `.claude/commands/strengthen.md` — gains the `## Suggest mode` orchestration (+ 2 synced mirrors).
- `espalier/cli.py` :: `cmd_strengthen` / `build_parser` — `--suggest` flag (read via `getattr`) + `suggest_requested` marker.
- `espalier/strengthen.py` :: `CHARACTERIZATION_CAVEAT` — new canonical constant (contract §2).

### Added-paths
- `tests/test_strengthen_suggest.py` (with `# pytest-marker: default-unit`) :: `TestSuggestFlagMarker` (S2), `TestGoldenPatternPointersResolve` (S3), `TestCharacterizationCaveatConstant` (asserts the constant is non-empty + emitted by the stub emitter).

## Implementation notes
- Dispatch shape (command-body prose, not Python): for each top-N gap,
  `Task(subagent_type="test-writer", <restricted tools>, prompt="<repo conventions> +
  read <golden file path> + draft a starting test for <module>::<symbol> at <file:line>.
  Prepend CHARACTERIZATION_CAVEAT verbatim. Return the test body only; you have no Write/git
  tools.")`. Collect → render `strengthen_suggestions.md`.
- `test-writer` already discovers project conventions first and follows earn-the-red
  (`.claude/agents/test-writer.md`); reuse that, don't re-specify it.
- Pattern selection is mechanical (coverage state from core's JSON), not handed to the agent.
- Keep the command doc provenance-clean (no `TP-NNN`/`wf_` tags) and adopter-plain.

## Pass criteria
⚠ **Honest split — the harness cannot pytest-drive session-runtime agent dispatch.**
- **Mechanically testable (pytest earn-the-reds — the real gates):**
  - S2: `espalier strengthen . --suggest` sets `suggest_requested` in the JSON; core's
    no-`suggest`-kwarg `TestCmdStrengthen` still returns 0 (getattr seam) — RED if the flag is
    read as a bare attribute.
  - S3: `TestGoldenPatternPointersResolve` RED if a `G*` name has no matching
    `examples/golden/test_g*.py`; GREEN when all resolve.
  - `CHARACTERIZATION_CAVEAT`: non-empty, present in the scaffold-stub header emitter, and
    cross-checks against the g4 file's wording — RED if the constant is emptied or drifts.
  - Full suite + mirror parity + `test_marker_taxonomy` + provenance + `ruff` green. ZERO deny-predicate.
- **Session-level acceptance (a documented manual runbook, NOT a pytest earn-the-red):**
  a live `espalier strengthen . --suggest` on the `strengthen_fixture` yields a caveated
  scaffold for the known untested symbol following the named pattern; `git status --porcelain`
  shows no new `tests/` file after the run (contract §1 backstop holds).

## Files touched
- Modified: `.claude/commands/strengthen.md` (+ 2 synced mirrors), `espalier/cli.py`
  (`--suggest` via `getattr` + marker), `espalier/strengthen.py` (`CHARACTERIZATION_CAVEAT`),
  `CHANGELOG.md`.
- New: `tests/test_strengthen_suggest.py` (with `# pytest-marker: default-unit`).

## Sub-task ordering
1. **S2** `--suggest` (getattr seam) + `suggest_requested` marker + `TestSuggestFlagMarker`. *(checkpoint: flag round-trips into JSON; core's TestCmdStrengthen stays green)*
2. **§2 constant** `CHARACTERIZATION_CAVEAT` + emitter + `TestCharacterizationCaveatConstant`.
3. **S1** command-body suggest orchestration (restricted-tools dispatch OR git-status backstop; golden file-path anchor; scope log).
4. **S3** golden-pattern pointer test + marker comment.
5. **S4** mirror sync + provenance + CHANGELOG + full gate (incl. `test_marker_taxonomy`).

## Estimated effort
- S2 0.6h · §2 constant 0.4h · S1 1.5h · S3 0.6h · S4 0.6h. **Total ≈ 3.7h.**

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: S3 rename a golden file → pointer test RED; the `CHARACTERIZATION_CAVEAT` assertion RED if the constant is emptied or the stub emitter drops it; S2 RED if `--suggest` is read as a bare attribute (breaks core's Namespace test).
- Date:
