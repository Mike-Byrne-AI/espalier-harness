# TP-449 — The adopter-facing minors and nits, in three tiers

## Status

- Version target: pre-`0.8.0b1`
- Type: correctness + hygiene — the adopter-facing remainder after the three
  majors went behind the Windows walk
- Ledger: every LIVE row whose effective audience is ADOPTER at severity
  minor or nit, excluding §C5 and §C49 (walk-gated). Roster derived, never
  typed — see Task 0.
- Gate: **operator decision 2026-09-08, option A** — Tier 1 runs while the
  walk runs; Tier 2 waits for the operator's Windows `0-A` pull; Tier 3 waits
  for the walk itself.
- **Kind: ROADMAP** — routes the work into lanes and checkpoints. Copy-ready
  Implementation and Pass criteria are withheld on purpose: each lane is a
  class whose ledger preamble already carries the unit of work, and each lane
  runs the `/implement-task` discipline (hazard recall, both reviewers, one
  fix batch, one proof-tier run, rows struck by the ledger verb). Prescribing
  code here would buy a review round per assertion and change no source.

## Motivation

On 2026-09-08 the adopter-facing slice of the ledger was re-derived: three
majors (`DEF-616`, `DEF-493`, `DEF-637`) are all sequenced behind the Windows
walk, seven maintainer rows left the adopter audience, and 45 minors and nits
remain that nothing gates. The operator asked for the biggest responsible
batch. "Responsible" here means: one lane per class (the class is the unit of
work, Core Rule 12), a driven probe for every member so a strike is measured,
no lane that relaxes the write-guard layer before a real host baselines it
(the 447-0-D reasoning), and no lane that moves the install layer under a walk
that is driving it.

A session cannot carry nine reviewed lanes in one context. The lanes are cut
into groups with a **handoff** between them, so each group starts fresh and
the record (memory row, GOAL, record-branch snapshot with the ledger strikes)
is written when its facts are final.

## Scope (in)

- Tier 1, three groups, run now.
- Tier 2, one list, run after the operator reports the Windows `0-A` pull.
- Tier 3, three rows, run after the walk with the walk-gated majors.
- Each lane closes its rows through `python3 scripts/ledger_row.py strike`
  with the probe retired, sibling sites in-lane.

## Scope (out)

- **§C18** (`DEF-553`, `DEF-412i`, `DEF-392a`, and the gate rows `DEF-622`,
  `DEF-626` that look standalone): the class records that per-site fixing
  grew the dead-cite count. The unit is one resolver over "does the adopter's
  tree receive this reference?", and that is a pack of its own, not a lane.
- **§C16** (`DEF-418c`): gated on a false-positive triage over roughly 985
  call sites. A measurement lane, then a fix; not in a tier until the number
  exists.
- **`DEF-410k`**: half of it is Windows path rendering. Observe on the walk.
- **`DEF-699`'s fix**: measure-first by the row's own instruction; the
  measurement is a Tier 1 lane, the fix lands in Tier 2 only if the number
  says so.
- **The walk-gated majors** (`DEF-616`, `DEF-493`, `DEF-410p`, `DEF-637`):
  TP-447 and §C49 own them; Tier 3 follows them, does not include them.

## Task 0 — Verify (re-derive the roster; may re-scope a tier)

**Oracle.** The tier population is the ledger's, not this file's:

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, "scripts")
import generate_ledger_regions as g
text = g._LEDGER.read_text(encoding="utf-8"); tags = g.declared_class_tags(text)
for sec, rows in g.ledger_sections(text).items():
    if sec in ("§C5", "§C49"): continue
    cpop, caud = tags.get(sec, (None, None))
    for r in rows:
        if g._is_struck(r): continue
        c = g.member_cells(r)
        aud = caud if caud in g.AUDIENCES else (c[5].strip() if len(c) > 5 else "?")
        if aud == "ADOPTER" and c[3].strip().lower() in ("minor", "nit"):
            print(sec, c[0].strip("`"), c[3].strip())
EOF
```

Measured 2026-09-08: 45 rows over 15 classes. **Refuting result:** a lane's
rows are absent from this output (struck since, or re-tagged) — drop the lane,
do not re-open the row. A row present here but absent from a tier below was
filed after this pack — assign it by surface using the tier rule, and say so
in Landing.

**Second oracle, per lane, before the first edit:**
`python3 scripts/check_ledger_probes.py --id <every row in the lane>` must
print `STILL_OPEN` for each. A `STRIKE_CANDIDATE` means the defect moved
under the pack: strike it by the verb, do not author.

## Relevant memory

Recent pattern, measured this week: task-shaped recall queries returned the
two largest generic docs and none of the applicable entries (`DEF-699`); the
hazard-word queries below returned the right entries first try. Two of the
last three guard lanes had every blocker in the repair, not the defect.

| Entry | Where |
|---|---|
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| Recall keys on the hazard, not the task | `memory/recall-keys-on-the-hazard-not-the-task.md` |
| Markdown Escaped Pipes Silently Drop Matrix Rows | `docs/SHARP_EDGES.md` |
| A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently | `docs/SHARP_EDGES.md` |
| Two operator-doc contracts can collide on one line | `docs/SHARP_EDGES.md` |

Resolved 2026-09-08 by `python3 tools/cc/hooks/_recall.py "<topic>"` with the
topics `escaped pipes`, `hand-maintained enumeration`, `operator docs python`;
re-run per lane with the lane's own hazard words (a scanner lane asks
`scanner false positive fixture`, a session-machinery lane asks `hook exit
code channel`).

## Implementation — the tiers

Every Tier 1 and Tier 2 lane touches `tools/cc/` or `espalier/*.py`, so each
earns the full proof tier (`python3 scripts/proof_tier.py --run`, about ten
minutes on two workers here) and both reviewers (`code-reviewer` +
`failure-mode-reviewer`, dispatched together, edits frozen until both return).
Surface letters are the dossier's: (a) write-guard layer, (b) install and
diagnostics layer, (c) shipped docs, (d) scanners, (e) session machinery,
(g) other engine.

### Tier 1 — now, no walk interaction

| Group | Lane | Rows | Surface | Effort (ledger) | Checkpoint |
|---|---|---|---|---|---|
| 1 | §C12 align the two halves of `/reflect` | `DEF-416a`, `DEF-589`, `DEF-410g` | (e)+(g) `tools/cc/reflect_protocol.py`, `espalier/reflect_protocol.py` | ~80 LOC | |
| 1 | §C10 scanner predicates | `DEF-312b`, `DEF-410e`, `DEF-410m`, `DEF-410l` | (d) three scanners + `espalier/scan_credibility.py` | ~77 LOC | **handoff** |
| 2 | §C13 release archive from the git index | `DEF-417g`, `DEF-417f`, `DEF-417e` | (g) `release_pack.py`, `surface_contract.py`, `pre_release.py` | ~45 LOC | |
| 2 | §C11 nested-repo warning | `TP-346` | (e) `session_start.py::_find_nested_repo_litter` | ~90 LOC | |
| 2 | `TP-330` session_resume residuals | `TP-330` | (e) `tools/cc/session_resume.py` | unstated | **handoff** |
| 3 | `DEF-586` keep subagent reasoning | `DEF-586` | (e) `tools/cc/hooks/subagent_stop.py` | unstated | |
| 3 | `DEF-338` approval tied to a commit | `DEF-338` | (g) `tools/cc/ci_guard.py::_approval_marker_present` | unstated | |
| 3 | `DEF-410j` 0-D sees deletes | `DEF-410j` | (g) `espalier/surface_impact.py` | unstated | |
| 3 | `DEF-699` **measurement only** | `DEF-699` | scripts: a third query class in `scripts/recall_eval.py` | unstated | **handoff** |

Order inside a group is the table's. The `DEF-699` lane delivers a number, not
a ranker change; its Landing line says what the seven task-shaped queries
score today.

### Tier 2 — after the operator reports the Windows `0-A` pull

Surface (b) or a caveat that needs a measurement first. Anything pushed
before the pull enters the walk; the sheet's 0-A diff line will stop the
operator, so hold the pushes, not the work.

| Lane | Rows | Caveat |
|---|---|---|
| §C8 one inventory for write, claim, uninstall | `DEF-556`, `DEF-410d`, `DEF-552` | measure first: drive `clean-generated --execute` on a scratch `init` tree; the "five kinds" claim predates `cleanup.py`'s import of the getters |
| §C7 pack parser honours the pack's markup | `CONV-2`, `DEF-430`, `DEF-431` | `cli.py` message paths ride along |
| §C20 shipped sentences say what the command does | `DEF-517`, `DEF-432`, `DEF-410a`, `DEF-412g` | multi-site; run `scripts/sync_asset_docs.py` and the mirror sync per copy |
| §C17 `.claude/skills/` visible to ownership and teardown | `DEF-532` | overlaps §C8; run after it |
| `DEF-348a` atomic writes | `DEF-348a` | fourteen sites incl. the adopter's `settings.json`; the class oracle enumerates them |
| `DEF-410f` raw-existence detectors | `DEF-410f` | the seeded-doc leg closed 2026-09-05; what is left is the detector class |
| `DEF-567`, `DEF-399b`, `DEF-415h`, `DEF-382a`, `DEF-643` | one row each | (b) or `fuse.py` epilogue; `DEF-643` is `_hook_utils.py` but not a write-guard verdict |
| §C6 `DEF-702` | `DEF-702` | no driven probe; the lane builds a CLI oracle over a scratch manifest first |
| `DEF-699` fix | `DEF-699` | only if the Tier 1 number justifies it |

### Tier 3 — after the walk, alongside the walk-gated majors

`DEF-410q` (§C4), `DEF-8` (§C14 speed-bump), `DEF-509`. All three change
what the write-guard layer allows; the walk baselines that layer first.

## Affected symbols

The child lanes' entry points, re-derived by each lane from its rows' `site`
cells; only symbols read in the tree on 2026-09-08 are listed.

### Changed-semantics

- `espalier/reflect_protocol.py::_count_placeholders`
- `espalier/scanners/test_loosening.py::scan_repo`
- `espalier/scanners/convergence_theater.py::_compare_two_sides`
- `espalier/surface_contract.py::is_transient`
- `espalier/pre_release.py::_find_transient_noise`
- `tools/cc/hooks/session_start.py::_find_nested_repo_litter`
- `tools/cc/ci_guard.py::_approval_marker_present`
- `tools/cc/hooks/_recall.py::_vocab_norm`

## Reach

Members derived by the Task 0 command (scope: live ADOPTER rows at minor or
nit outside §C5 and §C49; a row's absence there is a strike or a re-tag, never
an absence proof for the class it belonged to).

| Item | Status | Evidence |
|---|---|---|
| Tier 1 rows (16) | **LANE ASSIGNED** | each lane strikes by the ledger verb; Landing lists the ids struck |
| Tier 2 rows (18) | **HELD** | operator's `0-A` pull is the gate |
| Tier 3 rows (3) | **HELD** | the walk is the gate |
| `DEF-553`, `DEF-412i`, `DEF-392a`, `DEF-622`, `DEF-626` | **NOT REACHED** | §C18 is a resolver pack of its own |
| `DEF-418c` | **NOT REACHED** | false-positive triage first |
| `DEF-410k` | **NOT REACHED** | observe on the walk |

## Pass criteria

- Every struck row was struck by `scripts/ledger_row.py strike` with its
  probe retired; `scripts/check_ledger_probes.py --strikes` exits 0 after
  each lane.
- No assertion in an existing test may be weakened to clear a lane's red; a
  gate a lane touches may only be strengthened.
- Each lane's Landing line names the mutation its new test died to.
- A lane whose Task 0 probes print `STRIKE_CANDIDATE` strikes, does not build.

## Files touched

Per lane, from its rows' `site` cells. This file: `## Landing` only.

## Sub-task ordering

1. **Group 1** — §C12, then §C10. Checkpoint: `/handoff`, then `/clear`.
   *Moved 2026-09-08:* the session that ran §C12 also carried the adopter
   assessment, the walk re-anchor and the ledger re-tag, so its checkpoint
   fell after §C12 alone; §C10 opens the next session as Group 1's second
   lane, and the Group 2 checkpoint stands.
2. **Group 2** — §C13, §C11, `TP-330`. Checkpoint: `/handoff`, then `/clear`.
3. **Group 3** — `DEF-586`, `DEF-338`, `DEF-410j`, the `DEF-699` measurement.
   Checkpoint: `/handoff`.
4. **Operator reports the Windows `0-A` pull** → Tier 2 in the table's order,
   a handoff every two or three lanes.
5. **Walk recorded under `## WALK 2`** → Tier 3 after the walk-gated majors.

Why a handoff and not a compaction at each checkpoint: a group's review and
proof transcript is dead weight the next group never needs, and the handoff
writes the durable record at the moment the facts are final (memory row, GOAL,
the record-branch snapshot that carries the ledger strikes). The next session
resumes from GOAL's notes and this file.

## Estimated effort

| Item | Budget |
|---|---|
| A Tier 1 lane: recall, plan, fix, two reviewers, one fix batch, full tier, strike | 35–50 min |
| Group 1 (2 lanes) | ~1.5 h |
| Group 2 (3 lanes) | ~2 h |
| Group 3 (4 small lanes) | ~2 h |
| Each handoff | ~10 min |

## Landing

- State: ROADMAP
- Commits: `75fb8a8` the §C12 lane on main (2026-09-08; rows DEF-416a, DEF-589,
  DEF-410g struck by the ledger verb; DEF-719 filed under §C28 from the same
  full tier -- a test asserting a tree state every handoff removes). The §C10
  lane (2026-09-08; rows DEF-312b, DEF-410m, DEF-410l, DEF-410e struck by the
  verb, DEF-312b's probe re-pinned first to drive the instance because its
  text probe conjoined a symptom and a source line the fix keeps): both
  reviewers, one fix batch (the changelog's pack tag tripped the provenance
  gate; the freshness accept-and-leave entry in the shipped catalog closed;
  the narration boundary witnessed both ways; the calibration re-pinned to a
  dated snapshot with margins and its re-derive command). Earn-the-red per
  row: a deny test whose only stdout mention is its assert message read as
  observing the channel on the old code; the old closure walker returned only
  the bound file for six relative and name importers; `pytest.approx(X) == X`
  was missed; one fire in twenty runs read `healthy`. **Group 1 complete.**
  The §C10 unit of work as written prescribed an assert-subject reading that
  the lane measured and refuted (five live false positives); the ledger
  preamble now says so.
- Suite: `python3 scripts/proof_tier.py --run` per lane
- Earn-the-red: per lane, in its Landing line
- Red-team: both reviewers per lane
- Reach: see Reach; Landing lists ids struck per group
- Date: 2026-09-08 (authored)

- **Group 2, lane 1 -- §C13 (2026-09-08):** rows DEF-417g, DEF-417f, DEF-417e
  struck by the verb (DEF-417g's probe re-pinned to a driven instance BEFORE the
  first edit: its text form could never flip while the tree walk survives as the
  no-index fallback). Both archive builders enumerate the git index through
  `surface_contract.tracked_paths` (replacing `gitignored_paths`); `.git` as a
  bare gitlink file is transient on both witnesses; the noise scan classifies
  with the contract under the packer's prune. The reviewers' batch reached the
  sister sites the first cut missed: `_find_internal_leaks` (the failing half,
  a false red on an untracked `docs/internal/` scratch file), the parity
  fixtures running on the fallback, no gate reading the fallback WARN (now
  `pre-release`, the `release-pack` verb and `release_check` refuse a
  tree-enumerated build on a git root and an empty archive), and the
  wheel/sdist filesystem sweep -- filed as DEF-721 under §C0 (maintainer; a
  build-driven oracle is its own row) with an artifact-level witness in
  `tests/test_wheel_payload.py`. Mutations the new tests died to: forcing the
  tree walk back in both builders (7 tests), dropping `.git` from the SoT (5),
  removing the prune and the tree collapse (3). Full tier: 10,655 passed on
  two workers + 724 serial, mypy clean; one xdist live-tree race
  (`test_golden_examples`, 5 passed serially, logged), two real reds fixed
  (a CLI fixture faking `.git`, the freshness fragment's count) and the
  contract slice re-run green after the test-only edits. Adopter rows 38 -> 35.
  Audience note: `pre-release` skips and `release-pack` refuses adopter trees,
  so these three hurt the maintainer's release; the roster had them as adopter.
  Owed: the `release-denylist-patterns` fragment re-pin at the landed commit
  (a bound change invalidates the pin once committed), in the group's memory
  commit.

- **Group 2, lane 2 -- `TP-330` (2026-09-08, run before §C11 because its probe
  was already driven and §C11's second half had no mechanical definition
  yet):** row TP-330 struck by the verb; its probe (the `--log <path>`
  argparse error) flipped on the first edit. Three residuals, one class:
  `--log` takes an integer as the count or an existing directory as the
  swallowed `repo_root`, and anything else is a usage error;
  `_integrity.tail_audit` keeps only the asked-about checkout's records (the
  file is keyed by basename) and the tail prints a per-type day count above
  the window; the `write_guard`/`plan_guard` `deny` and `_audit_deny` twins
  are pinned (AST-equal emitters, behaviourally-equal funnels), not merged;
  `DENIAL_EVENT_TYPES` gains the secret-path type (written, filtered out, off
  the shipped table) and a speed-bump type (never written), the fire routes
  through `_audit_deny` with tool + checkpoint id via `_speedbump.check_fired`,
  and the call boundary fails toward allow. Contracts derived, not typed:
  emitted `*_blocked_*` literals reaching a writer == the set both ways;
  HOOKS.md rows == the set both ways; every bare emitter in every hook defining
  one is classified against the shipped `_denial_reasons.FAIL_CLOSED_REASONS`
  (self-expiring) with `stop_gate` on a reasoned exemption and a synthetic
  offender proving the detector; `/status` points at the table. Both reviewers:
  code-reviewer approved with one nit; failure-mode-reviewer requested changes
  (20 findings; 18 accepted, 2 refuted with reasons in the strike text). Filed:
  DEF-722 (PostToolUse sibling-attribute advisory), DEF-723 (`stop_gate`
  blocks unlogged), DEF-724 (speed-bump records in the denial view). Adopter
  minors and nits 35 -> 36 by the Task 0 oracle: TP-330 struck (-1), DEF-723
  and DEF-724 filed ADOPTER (+2), DEF-722 is MAINTAINER. Incident: a two-step
  edit of `_speedbump.py` wedged
  the session (write_guard raised between the steps; every mutation tool
  denied); the operator restored the file; SHARP_EDGES gained the sibling-edit
  variant. Full tier: mypy clean, 10,679 passed on two workers + 724 serial
  (the first `-n auto` run was killed for memory; the aging it exposed -- the
  denylist-count fragment's expected value dropped by the previous re-pin, the
  dual-witness fragment at seven commits -- verified and re-pinned at HEAD).
  DEF-647 re-pinned (its solo-TP-cell count moved 26 -> 24 when the strike
  rewrote TP-330's two rows). Group 2 now has §C11 left; this session ran two
  lanes' worth of review on one, so the checkpoint falls here.

- **Group 2, lane 3 -- §C11 half 2, `TP-346` (2026-09-09):** row struck by
  the verb; its probe was re-pinned BEFORE the first edit to a driven instance
  (`active_worktree_reported=... locked_worktree_reported=...`) and both
  flipped. The reporter reads `cwd` from the hook input (`_hook_cwd`, the
  process cwd as fallback) and skips the nested repo containing it and any
  registered worktree carrying a `locked` line, in both candidate sources;
  identity by inode, not spelling; the lost-worktree-list degradation pinned;
  one INFO line replaces the WARN for the in-use tree. Upstream sentences
  pinned in `docs/external/cc-worktrees.md` (the hooks page's cwd rule, the
  worktrees page's lock and stale-lock rules). Half 1 (the ignored clone)
  dropped by the operator, recorded on the row. Both reviewers approved with
  notes. code-reviewer: 4 minors, 7 nits, every skip predicate
  mutation-killed, 0 differences against HEAD's finder on ten fixtures with a
  neutral cwd. failure-mode-reviewer: 1 major, 7 minors, 3 nits -- the major
  (inside a nested worktree write_guard and plan_guard are keyed to the
  project root and cover nothing; driven again here) is filed as `DEF-743`
  (§C0, adopter major) and the reporter keeps one INFO line so the session
  is not silent about it. Also filed `DEF-744` (§C0, maintainer minor): the
  pin refresh runs a hand-kept two-file list, never a pin's declared binding
  tests, and diffs the excerpt against the whole page. Batch beyond the row:
  `core.excludesFile` cleared per fixture repo (a global ignore of `.claude/`
  reddened the fixture, driven), `_hook_cwd` total, the four statements of
  the rule aligned on the pin, the hook-authoring event table names the
  SessionStart payload fields, the docs map lists all three pins, CHANGELOG
  bullet. Full tier by hand (`-n 2`): the first run reddened two doc-pointer
  gates because the deployed hook and the deployed skill body cited the
  undeployed pin by path -- reworded to name the pin without a path
  (deploying a new managed doc is an enumeration change with its own
  fan-out; not this lane's); the re-run is 10,701 passed on two workers +
  724 serial, mypy clean, with one xdist live-tree race
  (`test_guard_false_positives.py`, a sibling worker's `reports/` temp file)
  rerun serially at 179 passed and logged. Adopter minors and nits by the
  Task 0 oracle: 42 rows over 11 classes after the strike (this lane -1;
  `DEF-743` is major and `DEF-744` MAINTAINER, so neither enters the
  population; the walk-2 rows filed 2026-09-09 sit in the base). Effort:
  ~90 LOC estimated; landed ~210 lines of hook change, ~255 of tests, a
  155-line pin -- the review reached a class again (spelling-based identity
  on case-insensitive filesystems) and a pre-existing guard gap. Group 2 is
  complete; checkpoint here: `/handoff`, then `/clear`.

- **Group 3, lane 1 -- `DEF-586` (2026-09-11, `7d1b239`):** struck by the verb
  with its probe retired. `subagent_stop` records the lead of the documented
  SubagentStop `last_assistant_message` (printable ASCII, word-boundary cut at
  600) with `agent_transcript_path` as the entry's evidence; no message string
  records `completed` with no evidence. Both `cognitive_blueprint` twins tell a
  REPORT from an anchor by that evidence: every agent entry stays out of pins,
  decisions, patterns and reflect's memory candidates; a report is carried
  through one bounded slot after the patterns (pinned first, newest, one per
  description, two, pinned across the twins) and kept by `show-recent` inside
  the same bound. Operator chose this shape (B) over hook-only (nothing reads
  the entry), a new entry kind (a schema bump for a minor row) and
  archive-only (`docs/HOOKS.md` had already promised the next session). Both
  reviewers REQUEST CHANGES, one fix batch, and it reached four sibling holes
  the first cut missed: `show-recent` unbounded (five reports took all five
  slots from the session's decisions in the compact banner and `/reflect`,
  the DEF-584 shape at the sibling reader), the scaffolding canon's
  continuity signal scoring report fragments (both directions driven; third
  epoch recorded in `docs/CONVENTIONS.md`), the record CLI's echo crashing on
  a Windows child's cp1252 stdout after the write (the lead folded to ASCII
  at the producer, every echo sanitized), and the reviewer bodies putting the
  verdict last where the lead takes the head. Earn-the-red per row: twelve
  hook rows, eight reader rows and the parity pin red on HEAD; a dedup fixture
  that put the duplicates oldest was green for the wrong reason and was
  re-ordered. Full tier 11,386 parallel on four workers plus 966 serial with
  one red family (a docs count-claims gate read "two agent REPORTS" as a roster
  claim), closed docs-only under the contract slice (3,014) plus the touched
  files (85). `DEF-665` re-pinned 39 -> 42 by the strikes check: three
  `tests/test_host_check.py` timeouts from the Bash trio, not this lane.

- **Group 3, lane 2 -- `DEF-338` (2026-09-11, `164ceeb`):** struck by the verb
  with its probe retired. On PR-like events the title marker is bound to the
  head under review (`HARNESS-UPDATE-APPROVED@<sha>` prefix-matching
  `PR_HEAD_SHA`, forwarded by the workflow asset); a force-push after approval
  goes red naming both heads and the fragment to paste; a bare marker is
  refused; a missing or malformed head fails closed naming the parked
  `harness-guard.yml.new` and the exact env line; push events unchanged.
  Operator chose this shape (A) over accepting the bare marker with a warning
  (leaves the hole), a protected-path digest (heavier ceremony) and the
  GitHub-API comparison the SHARP_EDGES residual had deferred to (token and
  network in a zero-dependency script). Both reviewers REQUEST CHANGES, one
  fix batch, and the reviews reached what the diff could not show: the
  pull-request trigger had no `edited` type, so a title edit never re-ran the
  gate and the prescribed recovery could not close (added to the asset, with
  a pin); `install-ci` parks a differing workflow as `.new` rather than
  overwriting it, so the red's remedy was a no-op for exactly the adopters
  who hit it (the message names the file and the line; install-ci warns by
  name); the bypass benchmark's `ci_marker` driver built a bare title and no
  head, so its positive control read the binding as a vacuous gate (driver
  fixed, BC-055 witnesses both shapes, RESULTS.md regenerated at 266);
  every env key the gate reads is now derived and asserted forwarded by the
  asset; the honest frame (a self-attested, timeline-logged re-binding, not
  independent evidence; re-review a force-push) restored to SHARP_EDGES.
  Earn-the-red: eight deny rows and the workflow pin red on HEAD; the allow
  rows were green on HEAD because the old predicate accepted any title
  containing the marker, which was the hole. Full tier 11,434 parallel plus
  966 serial with three red families (the DEF-586 probe retired after that
  lane's tier had run, a text-mode subprocess without an encoding pin in the
  bench helper, README's bypass-class count), closed under the contract slice
  (3,015) plus the touched files (264). Proposal left for the operator, not
  filed: a provenance stamp on the deployed workflow would let install-ci
  refresh an espalier-authored stale copy while still preserving a
  host-authored one.

- **Group 3, lane 3 -- `DEF-410j` (2026-09-11, `fdc6ffb`):** struck by the verb
  with its probe retired. A removed or renamed path runs through the same
  surface classifier as an addition and is reported as a removal with the
  same sites in reverse, minus the demands that police a departing file's own
  content; the renderer says once what reverse means, names which mirror sync
  prunes and that the asset-doc sync never does, and tells a directory-shaped
  removal to declare its files; a removed CLI verb declares the cheat-sheet
  obligation; the verb exits 2 on a public removal. Operator chose this shape
  (A) over a separate reverse-worded table. Both reviewers REQUEST CHANGES, one
  fix batch; the failure-mode review's census of all 234 packs in the tree
  found the rename arm false on both live spellings, so the fix went to the
  parser (a spaced `path :: symbol` names the symbol; a `(none ...)` bullet
  declares nothing) and scope-check's rename predicate now uses the
  pre-flight's recognizer, so 0-B and 0-D agree. `DEF-441`'s probe re-pinned
  to require an import of the mirror registry: it had conjoined a mention
  with any `.direction` attribute and counted the new `Obligation.direction`.
  Earn-the-red: seven rows red on HEAD; the no-scan recorder and the
  bare-symbol negative green by design. Full tier 11,464 parallel plus 966
  serial, PASS.

- **Group 3, lane 4 -- the `DEF-699` measurement (2026-09-11):** the number,
  not a ranker change. `scripts/recall_eval.py` gains a fourth, task-shaped
  arm: `_TASK_ARM` in `tests/test_recall.py` beside `_PARAPHRASE_ARM`, read by
  the same AST loader (generalised to a named constant), exact-source match.
  Of the seven queries driven on 2026-09-06 only one was persisted verbatim
  (the DEF-699 probe's); the other six were plan step texts and an operator
  prompt no record kept, so the arm carries that one query with its four
  applicable SHARP_EDGES entries as four labels, plus the three Group 3 rows
  run today as queries (the ledger row's own claim sentence, what an executor
  reads first) each labelled with the entry that lane's hazard-word recall
  found and its constraint line used. Measured at 310 corpus documents:
  task arm n=7, control@1 1/7, control@4 1/7, union@any 1/7 (14.3 percent),
  delivered 3.86 candidates per query over 4 distinct queries; the one hit is
  the DEF-338 row, whose claim names the approval marker the entry is titled
  by (marked TITLE-OVERLAP), so the sharper reading is 0 of 6 when the query
  does not name the entry; three of the seven labels came from a hazard-word
  recall and make the rate an optimistic bound, said per row. The per-label
  `got` lists (what displaced each entry) are in the `--json` report, which is
  what a Tier 2 decision reads; the filed rows ratchet, the arm grows one row
  per lane at handoff (implement-task step 1 says when), and a renamed
  heading is caught at the commit that renames by
  `tests/test_recall_pasted_counts.py`. Against the same
  ranker the same run: heading 301 at 83.4/97.7/95.7, stripped 262 at
  81.7/97.3/92.0, paraphrase 16 at 43.8/56.3/62.5. `memory/CONVERGENCE_LEDGER.md`
  is the front door's first line on five of the seven task queries and
  `memory/task-packs.md` on the sixth -- the length-norm mechanism the row
  names, now printed on every run. No rate is pinned (rates move on
  documentation commits); the arm grows one row per lane at handoff. The fix
  stays a Tier 2 decision for the operator: the number says the rule "run
  /recall before a fix" returns the two largest generic documents for a task
  text six times in seven, and the event-keyed pointer rows of 2026-09-06 are
  the lever that already keys on the hazard.

- **Tier 2, lane 1 -- §C8 (2026-09-11).** Gate: the operator confirmed walk
  2's `0-A` the same day, which opened Tier 2; the three majors the Status
  paragraph still names as walk-gated had closed on 09-09 (§C49) and 09-11
  (§C5). Rows DEF-556, DEF-410d, DEF-552, DEF-737 struck by the verb;
  DEF-410d re-pinned BEFORE the first edit to a driven probe (init, then
  `clean-generated --execute` on a scratch tree, count the surviving harness
  files no report bucket names: 2 at HEAD of 29 survivors on a three-file
  tree, the manifest write-lock and the appended gitignore block). One owner
  in `managed_inventory`: the four runtime roots, a render-artifact predicate,
  `local_state_on_disk` (exact runtime paths, the surface contract's local-only
  and runtime-generated lists, every file under a root, minus git's index);
  README out of the packaged root docs and the tracked manifest; `cli`'s
  ownership predicate reads the inventory; the uninstall names every survivor,
  deletes `tools/cc` bytecode caches, finishes the settings unwire (statusLine,
  sentinel, emptied hooks key) and previews it under dry run; the gitignore
  block is retired entry by entry on the operator's choice among three shapes
  (retire what nothing needs, keep what guards preserved state, report both);
  `init` closes the block with an end marker; a legacy block with an uncertain
  edge keeps its header. Both reviewers REQUEST CHANGES, one fix batch: the
  working summary the PostCompact hook writes under bare `cc/` (in
  `ADOPTER_RUNTIME_GENERATED`, unread; now read, pinned by a test derived from
  that list), an empty header cut beside another block, adopter lines absorbed
  past an inferred edge, a dead symbol in a docstring, the atomic writer and
  CRLF, the bytecode sweep scoped to `tools/cc/`. Refuted with reason:
  `cc/session_findings.jsonl` (a self-host-only writer). Mutations the tests
  died to: HEAD's cleanup restored by a one-file stash killed 15 of the 18 new
  tests; the delta test reddened on its README pin before it was rewritten.
  Docs: QUICKSTART and TROUBLESHOOTING uninstall sections rewritten to what
  the verb does (both had said settings and the skeleton docs were removed);
  mirror synced; CHANGELOG entry. First full tier (four workers, 10:50):
  11,496 passed, 9 failed, 966 serial green -- two mine (an aliased import the
  sister-site probe counts; the census entry for `tests/test_cleanup.py`
  growing 9 to 13 derived rows), seven pre-existing at HEAD (five recall pins
  aged by the fold's corpus appends, filed as DEF-775; one protected-path
  parity false positive on the session log, a record surface, exempted like
  CHANGELOG). Side rows from a stranger's-eye scratch drive and the lane's
  own measurement, each driven before filing: DEF-770 (doctor after uninstall
  reports a broken install), DEF-771 (README contradicts itself on deny
  defaults; a §C20 member filed in §C0 because the verb refuses the class),
  DEF-772 (four documented verbs hidden from `--help`), DEF-773 (scan names
  none of its twelve reports), DEF-774 (re-init names no overwritten path),
  DEF-776 (the ledger verb cannot file into a one-declared-tag class). Adopter
  rows by the Task 0 oracle: 43 -> 44 (4 struck, 5 filed ADOPTER; DEF-775,
  DEF-776 and DEF-777 are MAINTAINER). Final full tier over the final tree
  (four workers, 12:03): 11,500 passed, 8 failed, 966 serial green -- the
  five recall reds of DEF-775, one probe-baseline entry the strike of
  DEF-552's text probe left dead (dropped, its file green), and the live
  pins control keyed on the parity test file being modified (DEF-777, green
  once committed).

- **Tier 2, lane 2 -- §C7 (2026-09-11).** Rows CONV-2, DEF-430, DEF-431
  struck by the verb; DEF-430 and DEF-431 re-pinned BEFORE the first edit to
  driven scratch-pack instances (bullets under `### Fixed` told they are
  malformed; a literals-only pack told it declares a symbols section), both
  1 to 0; CONV-2's archive probe 2 to 0. Operator's forks: name the unrouted
  heading rather than route it; rewrite the three active bullets (TP-430,
  TP-447) to the none spelling so the guard lands green. Measured before the
  guard was written: four routed bullets in two active packs and eighteen in
  the archive had no live token, eight of them `None` spellings the paren-only
  rule did not read. Landed: both parsers and the diagnostics remove the
  struck spans from a section before they look for bullets (a wrapped strike
  closes across the newline; a strike never crosses a blank line or a bullet
  start); the none rule reads `none` and `no new` and a whole-bullet
  parenthesised aside; a routed bullet with no live token and a strike
  spelling the parser does not honour are `!` diagnostics, `scope-check` names
  each token a strike withdrew, and `surface-impact` carries the parser
  notes; the landing verifier reads claims live; the zero-parse message names
  five causes and both when both sections are empty, the summary line the
  heading it matched; the chain driver shows the cause on a clean skip; the
  sharp-edge entry records the reversal under its unchanged heading;
  PACK_AUTHORING and the blueprint-authoring skill carry the rules. Both
  reviewers REQUEST CHANGES, one fix batch: the wrapped strike (the symbols
  parser reads physical lines; driven at 87 references, rc 2), bare `no`
  swallowing `- No longer generated: `x.py`` with the diagnostic silenced, a
  stray `~~` pairing across bullets, the two sister readers, the fifth cause
  (live on TP-430 the moment the none rule widened), the both-sections case,
  the guard's live-tree idiom (`REPO_ROOT` + a reasoned skipif + the
  full-tree-exempt marker), the dead symbols-heading regex. Refuted or
  deferred with reason: the 2026-08-01 fork chose the guard over honouring
  `~~`; the class's unit of work prescribes both and both landed, recorded on
  CONV-2's strike. Mutations the tests died to: with HEAD's four modules
  restored by a stash of those files, 25 of the 40 selected new tests died.
  Full tier (four workers, 10:23): 11,540 passed, 6 failed, 966 serial green;
  the six are DEF-775's recall family, whose numbers this lane's corpus edit
  does not move (measured by the failure-mode reviewer on two 310-document
  roots). Side rows: DEF-778 (an annotation-only token parses as a
  declaration, §C7), DEF-779 (the sharp-edge heading states the reversed
  claim; rename with DEF-775's re-pin), DEF-780 (five instruction surfaces
  gloss exit 1 as "neither section"), DEF-781 (the chain driver reads a
  declared-but-empty section as a clean skip). Adopter rows by the Task 0
  oracle: 44 -> 43 (3 struck, DEF-778 and DEF-780 filed ADOPTER; DEF-779 and
  DEF-781 MAINTAINER).

- **Tier 2, lane 3 -- §C20 (2026-09-11).** Row DEF-432 struck by the verb
  (probe `True` to `False`). The banner `init` stamps on the nine Tier-2
  seeds carried the retired re-init promise (a seed, once written, would never be touched again); the writer refreshes a
  stamped, untouched seed when the packaged copy changes. Every copy now
  states the rule in the one wording that survives every corner ("refreshed
  on re-init only while it still matches the copy it was deployed from, and
  otherwise left exactly as you left it"): the header, the two Tier-3 stubs,
  the README and QUICKSTART bullets for both seed groups (changed at the
  generator and regenerated; the phrase was born wrong on 2026-08-12,
  eighteen days after the refresh helper), QUICKSTART's "never overwrites
  existing files" gloss (now the marker rule), the reflect skill's quotation
  with its mirrors, the two docstrings beside the header. Both reviewers
  REQUEST CHANGES, one fix batch: two more copies in deployed code (the
  reflect protocol's comment with its vendored mirror; the hook rationale
  that kept the placeholder-body history append-only because init never
  overwrites, with its test docstring), a new overclaim in the gloss ("never
  overwrites a file you edited" is false for a marked body), the stubs'
  "your first edit makes it permanent" (false after a byte-for-byte revert),
  the fused stub written unstamped (preserved forever, so the sentence was
  false on every fused tree; `fuse` now stamps it), the second seed group's
  bullet, and the hand-listed absence test (now derived from the git index
  through the suite's oracle; it had missed both deployed copies). Refuted
  or deferred with reason: the fixture prose calling the self-host copies
  skipped is true (unstamped) and now says why; the digest consequence
  (every adopter's untouched seeds refresh on the next init, named by
  basename on stderr, counted on stdout, previewed by nothing) is DEF-774,
  widened by repin. Mutations the tests died to: with the ten non-test files
  restored by a stash, four of the seven selected tests died. Full tier
  (four workers, 10:04): 11,543 passed, 7 failed, 1 error, 966 serial green;
  six are DEF-775's recall family, one is DEF-431's probe-baseline entry
  left dead by lane 2's strike after lane 2's tier (dropped), and the error
  is an xdist live-tree race in `tests/test_audit_accuracy.py` (a sibling
  worker's temp file under `reports/`), 47 of 47 green serially and recorded
  on the races line. Adopter rows by the Task 0 oracle: 43 -> 42. **Group
  complete (three lanes); handoff.**

- **Tier 2, group 3, lane 2 -- §C6 lane A (2026-09-12).** Opened on the
  operator's "user-facing errors batched by class": §C6 taken by its shared
  oracle (run the verb on a scratch tree, read the output) as DEF-770,
  DEF-773, DEF-774, DEF-732, plus DEF-772 from §C0 assigned by surface (a row
  filed after this pack, the same oracle); DEF-758 and DEF-702 stay in the
  class as their own lanes (own oracles). Operator's forks: `pre-release`
  stays hidden and the README line is corrected; the forty `skip (exists)`
  lines stay, root-relative; no backup before a regenerate. All five probes
  STILL_OPEN and every row reproduced on a scratch drive before the first
  edit. Landed: doctor's uninstalled branch (`_deployed_surface_remains` over
  the plan's inventory unioned with disk reality under the harness-owned
  roots; `_uninstall_leftovers` over the mode detector's markers, with
  `repo_mode.runtime_marker_paths()` made public, plus the saved reports;
  the never-initialized status, prose at exit 0, terminal advice); scan's
  one `_write_report` record deriving the counts line and a Details or
  No-findings line that names the four Espalier-only stubs on an adopter
  tree; init's summary naming regenerated paths untruncated, refreshed seeds
  and source-missing files; `_write_seed` with a required `label` and a
  `dry_run`; `_deploy_seed_docs` returning created and refreshed; upgrade's
  version-current branch consulting the seed preview as a fourth drift
  oracle (refreshed copies only) and its seed stage naming both arms, the
  preview degrading to a WARN on a package-data-less install; fuse's
  epilogue in two try blocks; `help=` on three verbs; README and the cheat
  sheet's day-1 and maintenance fences cleared of the three stand-down verbs
  (all three under Release Artifacts now); the TP-365 HIDDEN tuple pinned to
  the parser; a README-derived help contract (presence arm README-only,
  absence arm over four docs, three command spellings, self-host-only fences
  exempt); the DEF-11 doctor fixture given one deployed file so it stays on
  the branch it tests. Both reviewers REQUEST CHANGES, one fix batch: the
  blocker both drove (the first draft's "delete these files to finish the
  uninstall" round-tripped to the fail wall -- the adopter's unwired
  settings.json is a runtime marker and the branch was gated on the plan
  file), the skills blind spot of a plan-only predicate, the preview
  traceback on a package-data-less install, the truncated regenerated list,
  the label default, the cheat sheet sister site, two more command
  spellings, init's anonymous source-missing count, the stale
  `memory/asset-mirroring.md` snippet, the over-marked `_SLOW_FILES` entry
  (now `# slow-exempt`, measured 1.4 s), the scan stub wording, the plural
  mismatch, the cwd-relative scan path. Refuted or deferred with reason:
  un-hiding the hidden-but-safe developer verbs the cheat sheet documents
  (TP-365's decision; the presence arm is README-scoped and says so); the
  backslash-blind `generated_docs` in `managed_paths_from_plan` (read, not
  driven, no host; recorded here only); doctor's prose-not-JSON on an
  uninstalled tree (the shape it shares with never-initialized). Mutations
  the tests died to: 15 of 22 targeted new tests red at 102681d in a scratch
  worktree (the 7 greens are the controls), and with the disk-reality union
  removed from the predicate in a scratch copy the leftover-skill test died.
  Tier one (four workers, 10:57): 11,614 passed, 10 failed, 966 serial green
  -- six DEF-775 recall reds, four mine, all fixed in place (two upgrade pins
  on a fixture deployed without seeds, so the fourth oracle counts refreshed
  copies only; the report-filename parity reads the literal `reports_dir /`
  path, kept; the derived-population census adjudicated by hand, two
  entries, counts 93/319 -> 94/322). Tier two over the final tree (four
  workers, 11:37): 11,618 passed, 6 failed, 1 error, 966 serial green -- the
  six are DEF-775's family and the error is the recorded xdist live-tree
  race in `tests/test_e2e_bench.py` (35 of 35 green serially, appended to
  the races line). After the tier, test-only: two subprocess timeouts
  dropped to the 60 s ceiling (DEF-665's probe back to 42) and the races
  line; the contract slice (3,077 green) plus the two files. Ledger: five
  struck by the verb; the repin verb refused post-fix for DEF-770 and DEF-772
  (it runs probes from the checkout root), so the replacement probes were
  measured by hand in a 102681d worktree and on the fixed tree (False to
  True; 3 to 0) and the strike texts carry the pair; DEF-647 re-pinned
  '1 22' to '0 21' (group 2's DEF-532 id-cell normalisation removed the
  regex's one hit; not this lane); `--strikes` exits 0. Filed: DEF-785
  (doctor prints `self-host surface gate: fail` on a partially-present
  consumer tree; probe driven, §C6). Adopter rows by the Task 0 oracle:
  39 -> 35.
- **Tier 2, group 4, lane 1 -- the driven-verb class (2026-09-12).** Opened on
  "keep working to clear user facing issues, batched as efficiently as possible
  by class": the Task 0 roster (35 rows) clustered by ORACLE, and the five that
  share "run the verb on a scratch tree, read what it prints and leaves behind"
  taken as one lane -- `DEF-567`, `DEF-399b` (the one-row lanes), `DEF-785`
  (§C6's own-oracle remainder), plus `DEF-766` and `DEF-735` (rows filed after
  this pack, assigned by surface: engine, driven). All probes STILL_OPEN; every
  row reproduced on a scratch drive before the first edit (`DEF-766` by its
  census on an API tree: two siblings, four consumers correct by construction).
  Landed: `scaffolding-bench` rewrites the current json/md only on changed
  bytes, snapshots only a report that differs from the newest one and never
  zero sessions, and says which happened; `doctor` stands the self-host check
  down where the audit already does (a missing surface), the audit line carries
  the gate's first error-level finding through one owner
  (`proofs.first_error_detail`), the gate's own line is withheld when the
  audit failed (they are the same gate on an initialized tree), and
  `gate_failure_reason` names the gate for the tree it ran on from the
  producer's `self_host_repo` flag; `cmd_init`'s `write_gitignore` fallback
  agrees with the parser and the whole `getattr(args, ...)` class is censused
  against each subparser's effective default (34 sites); one owner
  `asset_inventory.packaged_agent_names()` read by doctor (folded), the
  surface gate (a bodiless recommendation is not warned) and the init summary
  (the bodiless ones named under the count); `selfcheck --contracts` wired,
  with C-2 comparing in the deployed form (anchored marker stripped both
  sides, package-only drift only when shipped, deployed-only drift only when
  marked or on the self-host tree) and an uninitialized tree sent to `init`
  at exit 2. Both reviewers REQUEST CHANGES, one batch: the blocker both
  found (the cheat sheet's asset mirror unsynced); the failure-mode review's
  self-host dead arm in C-2, the gate label keyed on a mode an adopter can
  reach, a reason forwarded on a passing gate, the `_2` ordering unpinned,
  a stale test comment, the flat-leaf assumption, the substring strip; the
  code review's zero-session note false on corrupt blueprints, the verb
  blind to the .md, the surface-present sister site (one deleted command,
  three errors), the flag's C-1 red on an uninitialized tree, the untested
  owner, both-sides strip, the getattr census. Mutations the tests died
  to: 33 of 41 new tests red at b9bfc61 in a scratch worktree (30 measured,
  the parity module's two at import, one red by construction), the eight
  greens controls; the reviewers' 13 scratch mutations, 12 caught, the
  escape (the .md verb) fixed and pinned by mtime. Tier (four workers,
  10:11): 11,657 passed, 7 failed, 966 serial green -- six `DEF-775` and the
  derived-population census, adjudicated by hand (two entries, 94/322 to
  95/324); then the contract slice (3,094) plus the two touched files.
  Ledger: five struck by the verb (probes True to False, 1 to 0, True to
  False, census, False to True); `DEF-786` filed (§C6: the recovery check
  reports a missing managed file the audit already named, a different
  oracle). Adopter rows by the Task 0 oracle: 35 -> 31. Observed for the
  operator: `DEF-415h` is a re-tag candidate (`pre-release` hidden, its
  user the maintainer).

- **Group 4, lanes 2+3 -- the session-start hook reads adopter state; pasteable
  remedies (2026-09-12):** rows `DEF-643`, `DEF-752`, `DEF-758`, `DEF-739` struck
  by the verb (probes retired with the rows); `DEF-382a` legs a and b landed,
  leg c open (re-pinned to a probe over the test that would close it);
  `DEF-787` filed (§C6: `/smoke`'s hook-wiring check reports all twelve hooks
  missing on a healthy tree because the loader substitutes
  `${CLAUDE_PROJECT_DIR}` in the command body); `DEF-383b` re-pinned (its probe
  counted the resolver names this lane renamed; the per-entry loop stands).
  Two lane commits (485c150, f4f0e56) plus the tier's adjudications (0863d10);
  one full tier at the group head: 11,679 passed, 9 failed = the six recall
  reds + three adjudicated (census +3 rows, a placeholder token in a comment,
  the docs sample's conditional `Loose:` line), then the slice (443). Both
  reviewers REQUEST CHANGES, one batch: a `--rewire-interpreter` re-run spelled
  through the write-answer alias (the pin's first cut keyed on one name), two
  tests green only by this host's interpreter, the live `ps` header on procps,
  cli's four hand-edit sentences carrying the remedy answer, the 0-based step
  index rendered as a fraction, a newline forging a section header, a non-list
  `steps`, the stems read positionally, the container/detached-run wording,
  text-to-text pins made driven. Earn-the-red: 23 of 28 selected reds at
  f188153 on the first worktree run, 7 of 9 on the batch's (the classifier
  table and the re-seamed interpreter test green by construction). Adopter rows
  by the Task 0 oracle: 31 -> 28. Task arm: 23 labels over 13 queries,
  control@1 4.3%, union@any 13.0% (three rows added). Observed, not filed:
  `_remedy_py()` is uncached (failure paths only); `_active_plan_status` still
  reads the plan file with a following read.

- **Group 5 -- the pointer-gate class and five singletons (2026-09-12):**
  lane 1 (`85e237a`): the adopter pointer gate reads path-qualified source
  citations, interpreter invocations (prose and fences) and wikilinks with the
  markdown form's marker machinery; a fenced invocation is excused by a file
  guard or its governing `#` comment; three catalogue docs carry a
  carrier-bound head banner for the citation form; a "not deployed" note
  beside a file the adopter has reds (leg c); every dead site in the deployed
  set marked, guarded, bannered or reworded (measured first: 392 references,
  170 unresolved, 162 unmarked, 34 dead invocations); the shipped-asset
  invocation gate derives its population; README's deny-defaults sentence,
  the exit-1 gloss at six copies, one docstring. Rows `DEF-622`, `DEF-626`,
  `DEF-553`, `DEF-382a` (leg c), `DEF-412i`, `DEF-771`, `DEF-780`, `DEF-392a`
  struck. Lane 2 (`ee4e2fc`): doctor composes its recovery line from the
  assessor's data and withholds only the path clause by token boundary;
  `/smoke` and the config advisor strip the project-dir prefix by its tail; the
  reflect candidate pass counts the log lines it drops and the landing check
  names a torn cited key; the pack parser's declaration is the first token
  outside an annotation (3 of 1,214 symbol bullets change, 0 of 186 literals);
  `post_write_check` learns skill bodies through one tuple pinned to the
  engine's kinds. Rows `DEF-786`, `DEF-787`, `DEF-764`, `DEF-778`, `DEF-782`
  struck. Both reviewers REQUEST CHANGES, one batch: two blockers (a bare line
  anchor in a helper comment tripping the anchor ratchet; the census file
  count), four majors (the leg-c recogniser blind to the house spelling, the
  banner unbounded, the fence-wide marker scope, a sixth exit-1 gloss copy in
  the deployed PACK_AUTHORING), the rest landed too (asset-gate key for
  `.claude/` bodies, `errors="replace"` on the log, a `$VAR` phantom path, a
  commented-out command, dict-order pin, tool-owned tuple to carrier rows,
  parens inside backticks literal). Earn-the-red: 15 of 32 selected reds at
  5bc3269 in a scratch worktree, the 17 greens the controls. Tier by hand
  (`proof_tier.py` refuses on the untracked `cc/_cold` plan record --
  `DEF-788` filed): 11,722 + 968 passed, 8 failed = the six recall reds + one
  docstring pack-id tag on a shipping surface, adjudicated by rewording and
  re-proven on the touched files plus the contract slice (3,142). Adopter
  rows by the Task 0 oracle: 28 -> 16.

- **Group 6 -- the atomic writer's target identity, with the reset verb's
  leftover (2026-09-12), one lane:** `DEF-783` (the mode reset), `DEF-784`
  (the symlinked target), `DEF-788` (`cc/_cold/` unignored) -- "what a verb
  leaves on the tree". The four copies of the writer, the bytes twin and the
  release archive's writer create their tempfile with mode 0o666 under the
  kernel umask and copy an existing regular target's mode by `fchmod`
  (POSIX; a no-op on Windows, unverified there); the operator's fork
  (engine follows, hooks replace) was refined to a per-TARGET rule after the
  failure-mode review measured the engine following a link at
  `.espalier/freshness.json` and leaving its own `O_NOFOLLOW` reader empty:
  every copy replaces a symlinked state file, and the engine's copy takes
  `follow_symlinks=True` for the adopter's own file at five AST-pinned sites
  (retire, settings merge, hook-wiring repair, interpreter rewire, unwire);
  an emptied linked `.gitignore` is neither unlinked nor lost between report
  buckets. `cc/_cold/` joined every registry `cc/blueprints/` is in (the
  init block, the self-host ignore file, the runtime prefixes, both fixture
  twins, the fingerprint pin) and the doc regions were regenerated (12 ->
  13); the tier script ran again because of it. Reds earned: 22 + 18 live
  against HEAD code (`tests/test_atomic_io.py`), 4 of 4 and 2 of 2 in a HEAD
  worktree (`test_cleanup.py::TestSymlinkedAdopterFiles`,
  `test_execution_plan_cli.py::TestResetLeavesNothingUnignored`). Reviews:
  code APPROVE with follow-ups (fd closed when `fdopen` raises, the NT
  directory-name retry, three stale docstrings, an emptied linked
  `.gitignore` in no bucket), failure-mode REQUEST CHANGES (three majors:
  the freshness counter-example, the over-claimed "every hook reader
  refuses" rationale, nothing catching a fifth copy -- now a derived roster
  `_REPLACE_WRITERS` and an `os.open` create counted by the engine census;
  plus the release archive at 0600, the umask widening disclosed, the
  doctor remedy made pasteable, the "second block" wording), one batch.
  Tier by `proof_tier.py --run` at 4 workers: 11,784 + 968 passed, 10
  failed = the six `DEF-775` reds plus four from one cause, the un-synced
  selfcheck mirror of `tests/test_analyze.py` (an in-place Bash edit skips
  the mirror advisory an Edit-tool write raises), synced and re-proven with
  the 14 pins and the 3,142 contract slice. Rows `DEF-783`, `DEF-784`,
  `DEF-788` struck; `DEF-749` (the maintainer twin of `DEF-788`) surfaced
  as a STRIKE_CANDIDATE and was re-pinned to its one open leg, the reset
  message naming `_cold/` without its `cc/` parent, for the next `tools/cc`
  lane. Task arm: 27 labels over 15 queries, 3.7% at 1, 7.4% at 4, 14.8%
  union (four rows added; the POSIX-only `os.O_*` flags entry was found by
  neither the task text nor any hazard query, only by title). Adopter rows
  by the Task 0 oracle: 16 -> 13.
- **Group 7 -- the session log's Stop-gate records and its two tiers, the
  freshness dirty-bound rule, the reset message (2026-09-12), one lane:**
  `DEF-723` (Stop-gate blocks unlogged), `DEF-724` (pause records beside
  refusals), `DEF-702` (a pin vouching for a tree HEAD does not back),
  `DEF-749` (the reset message's bare `_cold/`). The two design questions
  the rows left open went to the operator in one turn: one type per gate,
  two tiers. The Stop hook's gates write through `_audit_block`, typed per
  gate, metadata only (AST-pinned at every site); `_integrity` holds
  `DENIAL_EVENT_TYPES` and `PAUSE_EVENT_TYPES`, and the reader tails the
  refusals, counts the pauses, widens under `--all`. `pin_fragment` refuses
  a bound with uncommitted changes, `pin --all` refuses before pinning
  anything, `scan_repo` reads such a bound `stale` narrowed to the symbol
  span; the hand-edit leg runs where the manifest is committed and says
  when it stands down. The row's scan-side shape was refined: it would have
  read every honest bump unverified until a second pin. Reds earned: 27
  against HEAD over five test files. Reviews: code REQUEST CHANGES (one
  block, `pin --all ""` resolved to the cwd; a docstring overclaim on the
  writer's stderr; two nits), failure-mode REQUEST CHANGES (two majors: the
  hand-edit check dead on every adopter tree because `init` gitignores the
  manifest, and `pin --all` re-stamping a hand-edited literal; six minors,
  four nits), one batch: the empty-path guard, `append_audit(quiet=)`
  across the three funnels with real-OSError proofs, the tri-state HEAD
  manifest with a `literal_check` note, the up-front `--all` refusal with
  its own remedy, the reader's attribute fallbacks, an exemption must cite
  a ledger row, the funnel's keywords pinned, a rename and a spaced path
  parsed, four doc corrections. Found and fixed in the lane: `pin --all
  <repo>` ran on the cwd (a test's first cut and the code reviewer's
  reproduction each re-pinned the self-host manifest before the guard
  landed). Tier by `proof_tier.py --run` at 4 workers: 11,815 + 968
  passed; 13 failed and 1 error = the six `DEF-775` recall reds, one xdist
  race (`test_atomic_io` concurrency, 12 passed serially, recorded), and
  seven from three causes -- a doc sentence read as a count claim by the
  release check, the deny-marker contract not knowing the new funnel, the
  env catalog's cited line drifted by 23 -- all tests-and-docs fixes,
  re-proven with the touched files (393) and the 3,142 contract slice.
  Rows `DEF-723`, `DEF-724`, `DEF-702`, `DEF-749` struck; `DEF-789` filed
  (MAINTAINER: the maintenance bypass leaves no record). Adopter rows by
  the Task 0 oracle: 13 -> 10.

- **Group 8 -- the recall lane: the six red calibration pins, the pull
  ranker's two displacing notes, the strikethrough heading (2026-09-12 to
  13), one lane (`d4c703f`):** `DEF-775` (six recall pins red since the
  2026-09-11 fold; the tier rule let a corpus change land on the contract
  slice), `DEF-699` (the Tier 2 row: task-shaped queries return the two
  largest memory notes), `DEF-779` (the sharp-edge heading stating the
  opposite of its body). The operator's two calls, taken in one turn:
  strike `DEF-699` AND exclude the pack-authoring note as well as the
  ledger (outside the record axis, on measurement, after the concern was
  raised); the naming guard over epsilon zero or alpha. Measured first
  through the eval's corpus-injection path: no lever moves the task arm
  off 1 of 29, so the task-shaped leg is a vocabulary gap, not a ranker
  defect; the `gate parser inputs only output` loss was the relative tie
  window, not the length norm (the note out-scored §1.12 and lost inside
  one percent); the blind held-out 17 -> 16 was the ledger displacing
  principle 8 (driven on a pre-fold scratch worktree). Landed:
  `PULL_EXCLUDED_MEMORY_NOTES` (pull-side only, case-folded, record
  members bound to the canon over every key the loader could read,
  FAILURE_MODES the named exception), `_names` guarding the canonical
  promotion (357 labelled queries, one cell moved), a third proof tier
  `recall` earned by any corpus file (both-ways pinned), the four pasted
  tables regenerated last, three corpus-shape pins re-derived with per-note
  A/B'd causes (the paraphrase climb now a shape on its own escalation
  rule; the six-slot headline parity at under four lines), the `(was:
  ...)` heading-rename convention in CONVENTIONS.md. Reviews: code
  APPROVE WITH FOLLOW-UPS (four nits, taken), failure-mode REQUEST CHANGES
  (the exclusion in the shared loader had silently cost `nearest_by_title`
  its fold targets -- the blocker; plus two gaps and five rough edges, all
  taken), one batch. Tier at 4 workers: 11,856 + 968; two reds fixed in
  tests, docs and a script (a census entry, the tests/ router at 24 lines
  since group 7) and re-proven with the touched files and the 3,163
  contract slice. Rows `DEF-775`, `DEF-699`, `DEF-779` struck; nothing
  filed. Adopter rows by the Task 0 oracle: 10 -> 9. Task arm: 29 labels
  over 16 queries, control@1 3.5%, control@4 10.3%, union@any 10.3%
  (four rows added, all in the filed ratchet).

- **Group 9 -- Tier 3, the write-guard layer (2026-09-13):** three lanes,
  one two-reviewer fan-out, one fix batch and one re-check, three full tiers
  (the first found five contract reds and a race, the second was clean, the
  third found two ledger reds -- a floor and an unescaped pipe -- fixed and
  re-proven with the touched files and the 3,163 contract slice), landed as
  `bae54fa`. Lane 9a: `DEF-410q` (one named `_QUOTED_VERB_TAIL` after every
  command-position verb arm; measured first over every anchored arm, only
  `tee`, the `git` verbs and the reader heads missed; a fixture roster keyed
  by arm name held equal to the module's anchored patterns), `DEF-760`
  (`[scriptblock]::Create(` a re-parsing opener, UNCONDITIONAL by the
  operator's call -- the assign-then-invoke spelling is what a conditional
  form would miss; 235 of 235 in the differential, run in real pwsh),
  `DEF-746` (three object-API matchers with a read allow-list; the bare
  `::new(...).IsReadOnly =` form added by the re-check). Lane 9b: `DEF-8`
  (`flag_key` receives the tool name; the MCP nudge keyed per full tool
  name with a hashed tail), `DEF-747` (the discard predicate and snapshot
  read the PowerShell tool through PowerShell-anchored twins of the discard
  regexes plus `bash -c` bodies; the bare `git reset --hard` typed on that
  tool taken in-lane as the same class). Lane 9c: `DEF-509` (the payload
  cwd as the start, the cd/pushd/popd and Set-Location chain with candidate
  directories per statement, an existence oracle crediting a directory an
  earlier mkdir makes, pipeline/background/function-body and if/case/loop
  rules, the .NET process-directory exemption, `post_write_check` as the
  sister reader; eleven shell shapes driven against /bin/bash across the
  two review rounds). Plus: `DEF-415h` re-tagged MAINTAINER; the snapshot
  call in `_run_main` wrapped after a rename split across two parallel
  edits wedged every mutating tool (the operator repaired the file from the
  prompt box); five legacy `cd /tmp` fixtures and BC-051-a7 re-derived to
  `cd .`, BC-051-a9 added (267 of 267); the blind held-out pin 17 -> 16 for
  drift that predates the lane (`0e6701c`'s folds, bisected per file); the
  alpha table regenerated; the ledger's ADOPTER floor 10 -> 1 as the roster
  passed under it. Reviews: code REQUEST CHANGES (two blockers -- the
  failed-cd false allow, the class-close census; two nits), failure-mode
  REQUEST CHANGES (three regressions incl. five shell shapes and the .NET
  exemption, three gaps incl. the post_write_check sister and two stale
  docs, four rough edges), then a re-check (two majors: the mkdir idiom, the
  keyword conditionals; one nit) -- all taken. Rows struck: `DEF-410q`,
  `DEF-760`, `DEF-746`, `DEF-8`, `DEF-747`, `DEF-509`; filed: `DEF-790`
  (the rm hard tier and the bumps still read a relative operand against the
  root), `DEF-791` (the PowerShell call-operator quoted verb). Live 180 ->
  176; adopter 12 -> 7; adopter rows by the Task 0 oracle: 9 -> 6
  (`DEF-790`, `410k`, `729`, `757`, `734`, `418c`). Task arm: two rows
  added (the MCP predicate edge, Class-A1), ratchet 16 -> 18.

- **Group 10 -- Tier 3, the guard trio (2026-09-13):** three lanes on this
  host, one two-reviewer fan-out, one fix batch, two full tiers at 4 workers
  (the first found a placeholder token and a subprocess in a unit module,
  both the lane's, plus one live-tree race; the second 12,128 + 984 clean).
  Lane 10a: `DEF-790` (the rm classifier answered "relative, the soft
  tier's" before joining an operand to any directory; now a relative target
  joins the directory the command runs in LEXICALLY -- operator decision:
  `../scratch` at the root stays soft, `../<repo>` is a wall -- and each
  delete is read in its OWN statement's directories by slice, the PowerShell
  removal tier by offset with positional operands and `-Path` values only;
  the bases builders moved to `_bash_patterns`; every speed-bump predicate
  takes `cwd`, CP-RMRF defers on the same reading, CP-DISCARD probes git from
  the statement's directory and skips a base outside the checkout). Lane 10b:
  `DEF-791` (`_PS_CALL_OPERATOR_QUOTE` on the separator behind `&` alone,
  never `=`; the closing-quote tail on every PowerShell verb arm and the two
  Remove-Item records; `_GIT_VERB` admits `git.exe` on both shells; measured
  10 of 16 pairs flipped before, all agree after; a PowerShell shape pin over
  the derived roster plus write_guard's records, 7 rehearsal rows, a
  call-operator axis in the differential, 252 of 252 in real pwsh twice).
  Lane 10c: `DEF-410k` (ci_guard's `_plural` mirror at five sites,
  session_resume's three inline, the one remaining bare `relative_to` print
  in cli.py -- not ten -- as `as_posix`, `tests/test_bench_surface_hygiene.py`
  over the authored bench docs with a derived agent roster and a negative
  control; corpus rows and `results/` out of scope by decision). Folded:
  `_pred_gateweaken` matched `tests/test_write_guard.py` by suffix (driven
  while writing the rows). Reviews: code REQUEST CHANGES (one blocker, the
  rehearsal docstring count; one warning, the duplicated call-operator
  fragment), failure-mode REQUEST CHANGES (four regressions -- the
  needle-collision wall, the flag-value wall, the backslash needle miss, the
  count; four gaps -- the snapshot promise, three stale sentences, the
  two-module roster, the silent three-argument predicate; three rough edges
  -- the hygiene scope, the `results/` records, `.exe` on one arm) -- all
  taken in one batch. `DEF-418c` struck on a falsified premise (the cited
  scanner checks schema parity, not encoding; widened to `tests/` it yields
  419 fixture writes) and `DEF-792` filed (an explicit-encoding scanner,
  MAINTAINER). Rows struck: `DEF-790`, `DEF-791`, `DEF-410k`, `DEF-418c`.
  Adopter rows by the Task 0 oracle: 6 -> 3 (`DEF-729`, `DEF-757`,
  `DEF-734`), every one Windows-gated or a design change.
