# TP-437 — a chain outcome that needs triage must outlive the process that found it

## Status

- **Kind: PACK**
- **State:** DRAFT
- **Version target:** `0.8.0b1` (not flip-gating — self-host dev tooling; `scripts/` is not
  deployed by `espalier init`)
- **Type:** bug fix — a durable home for two outcomes that currently die with the shell
- **Parent:** `task-packs/FORWARD_LEDGER.md` **`DEF-644`** (§C14). *Re-pointed 2026-09-21 at
  TP-452 1-H: the original parent `DEF-312d` was REFUTED and struck on 2026-08-20, and the
  2026-09-20 rebuild filed `DEF-644`, whose text carries the behaviour this pack's Motivation
  drove -- the silent skip, both triage outcomes, and the `HALTED-nocommit` leg 437-F covers --
  so 437-C (correct the row) is retired as already done by the ledger.*
- **Predecessor:** `TP-432` (`5299f81`). This pack is the successor its `432-E` was split
  into: `432-E`'s premise was **falsified by a driven produce→resume**, so it was removed
  rather than executed. This pack starts from the measurement, not from that prescription.

## Motivation

The unattended pack-chain driver classifies a pack it committed but could not fully land as
`LANDED-nostamp` (`fin_rc == 3`) or `LANDED-unverified` (`fin_rc == 4`). Both mean *"the work
is in git, but a human must look at it."* Both reach exactly two destinations, and **neither
survives the process**:

- `>&2` — the operator's terminal, gone when the run ends;
- `REPORT_ROWS` — a bash array, gone with the shell.

So an unattended chain can land a pack needing triage, print the warning to a terminal nobody
is watching, exit, and leave **no trace anywhere on disk** that triage is owed.

**And the resume makes it worse, in the opposite direction to what `DEF-312d` claimed** (the
row was refuted 2026-08-20; `DEF-644` now states the skip). The
row says a resumed chain re-surfaces the pack as *pending work*. Driven, it does not:
`post_commit_verify_and_finalize` appends to the resume ledger **unconditionally, before** it
branches on `fin_rc`, so the pack is recorded as done regardless of outcome. On resume,
`preflight_chain` finds the token and the main loop emits `SKIPPED-resumed`. **The pack is
silently skipped.** Nothing is re-surfaced, and the triage need is not merely un-persisted —
it is actively erased by a subsequent successful-looking run.

**Why `432-E`'s prescription could not work.** It said to append the outcome to "the chain's
on-disk report alongside the in-memory array". Driven at `HEAD`, a whole-file write census
finds exactly **two** persisted artifacts — `$LEDGER` and `$COMMITTED_MARKER` — and
`scripts/run_pack_chain.sh::print_report` performs **no file writes at all**; it is echo-only.
The destination that prescription targets does not exist. That is why this is a design change
and not a thirty-minute append, and why the successor was split out rather than executed.

Driven at `HEAD` while authoring — re-derive before executing, per criterion 8:

| Claim | How it was checked |
|---|---|
| `print_report` persists nothing | function body extracted by brace-matching; zero file-write redirections |
| the ledger write precedes the outcome branch | `post_commit_verify_and_finalize` writes `$LEDGER`, then branches on `fin_rc == 3` / `== 4` |
| only two persisted artifacts exist | write census over the whole script: `$LEDGER`, `$COMMITTED_MARKER` |
| `fin_rc == 4` has the same loss and no owner | it is `LANDED-unverified`; `DEF-312d` named only the `nostamp` case (`DEF-644` names both) |
| both artifacts are env-overridable + gitignored by name | `PACK_CHAIN_LEDGER` / `PACK_CHAIN_COMMITTED_MARKER`; `.gitignore` carries an explicit row for each |

## Scope (in)

- **437-A — a triage artifact that outlives the run.** Add a third persisted runtime file
  recording each pack whose landing needs a human, written at **both** `fin_rc == 3` and
  `fin_rc == 4`. Follow the two existing artifacts exactly: an env-overridable path defaulting
  beside the existing session-state artifacts, created on demand, and **its own `.gitignore` row** (both siblings are ignored
  by explicit name; a new file is NOT covered by any existing pattern — verified).
  `scripts/run_pack_chain.sh` · `.gitignore`
- **437-B — a reader at the resume skip.** `preflight_chain` currently answers only *"has this
  pack been done?"*. It must also answer *"was it done cleanly?"*, so a resumed chain reports a
  triage-owed pack as **needing triage** rather than as `SKIPPED-resumed`. A written artifact
  with no reader is the failure class this pack exists to close, one layer down — 437-A without
  437-B is not a partial fix, it is the same bug in a new file.
  `scripts/run_pack_chain.sh`
- **437-C — retired 2026-09-21 (TP-452 1-H).** It was to correct `DEF-312d`'s row, which
  described the resumed chain re-surfacing the pack as pending where, driven, the chain
  **silently skips** it. That row was refuted and struck on 2026-08-20, and its successor
  `DEF-644` (filed by the 2026-09-20 rebuild) states the silent skip and names both
  outcomes. Nothing left to rewrite; the strike of `DEF-644` belongs to execution.
- **437-D — earn the red on a produce→resume, not on a unit.** The defect only exists across
  **two runs**: run 1 produces the outcome, run 2 must surface it. A single-run assertion cannot
  express it. `tests/test_run_pack_chain.py`
- **437-F — disambiguate `HALTED-nocommit`, which now carries two opposite outcomes.** The
  driver halts at `:843` when the goal returns 0 but `HEAD` did not advance, and files
  `HALTED-nocommit`. That token meant one thing when this pack was written: the session failed
  to do the work. The revised pack format added a second producer of the *identical* signal —
  a pack whose `## Task 0` oracle returns its stated refuting result **correctly refuses to
  build**, returns 0, and makes no commit. A licensed refusal and a driver failure are now
  indistinguishable, and the successful one is reported as a fault. Emit a distinct outcome
  token for the refusal, persist it to 437-A's triage artifact (the refusal is exactly the
  kind of outcome that must outlive the run), and let 437-B's reader surface it on resume.
  ⚠ **Do not make the refusal halt the chain** — see the Scope (out) row on hard-failing;
  a correct refusal stranding every pack behind it is the worst of both readings.
  `scripts/run_pack_chain.sh` · `tests/test_run_pack_chain.py`

## Scope (out)

- **Changing what `finalize_landing` returns, or when `fin_rc` is 3 vs 4.** The classification
  is correct; only its *durability* is broken. Touching the classifier widens a bug fix into a
  redesign of the landing protocol.
- **Making the driver fail (non-zero exit) on a triage-owed pack.** Considered and rejected on
  the same evidence `TP-432`'s 432-F used: these are advisories, and a chain that hard-fails on
  one triage-owed pack strands the packs behind it — turning a bookkeeping gap into lost work.
  Report loudly; do not halt.
- **A `/status` or CLI surface over the triage file.** Paid surface (`EXPECTED_SCRIPT_COUNT`,
  cheat-sheet parity, count pins) for a self-host dev tool. Revisit only if the file proves
  hard to notice in practice.
- ~~**The `HALTED-nocommit` path.** It already halts the chain, so the operator learns about it
  by the chain stopping. Different failure, already loud.~~ ⚠ **SCOPE-OUT RETIRED 2026-08-16b —
  its premise was falsified by a change outside this pack, and it is recorded rather than
  deleted so the reversal is auditable.** The reasoning was sound when written and is *still*
  sound for the case it described: a genuine driver failure is loud and self-announcing. What
  changed is that the revised task-pack format introduced a **second producer of the same
  token**. A pack whose `## Task 0` refuses correctly also returns 0 with no commit, so
  `HALTED-nocommit` now spans a failure and a success, and "already loud" no longer implies
  "already understood" — the loudest possible signal is worthless when it cannot say which of
  two opposite things happened. Now in scope as **437-F**.
- **Anything in `TP-436`'s corpus-writer scope.** Different subsystem entirely; the two packs
  share no file.

## Task 0 — Verify

Run before building anything. **Its licensed outcomes include "do not build this."** Each row
kills its own sub-task; a refutation does not necessarily kill the pack, and the exit says which.

| Oracle | Refuting result | Exit |
|---|---|---|
| Extract `print_report`'s body and census it for file-write redirections | It persists **anything**. `432-E` was retired because the destination it targeted did not exist; if one now does, 437-A is building a second one | Stop 437-A. Re-raise: the fix is an append to the existing artifact, not a new file |
| In `post_commit_verify_and_finalize`, check whether the `$LEDGER` append still precedes the `fin_rc` branch | It now follows the branch | Stop 437-B — the silent-skip is already closed, and 437-A's reader has nothing to read |
| Drive both `:843` paths (a Task-0 refusal and a plain no-commit) and compare the persisted rows | They already differ | Stop 437-F; the disambiguation exists |
| `grep -n 'State: SCRAPPED' .claude/commands/implement-pack.md` and confirm the refusal path is reachable without a commit | The executor has no way to mark a refusal before exiting | **437-F's fix shape is refuted** — re-raise rather than inferring intent from an absence |
| Re-derive every Motivation-table claim (criterion 8) | Any row no longer reproduces | Stop and re-raise with the new measurement; do not adjust the prescription and continue |

**If the whole Motivation is falsified** — the outcomes now persist by some other route — stamp
`State: SCRAPPED` with the measurement and stop. That path needs no commit.

## Relevant memory

Recent pattern, measured this session: **every review pass found real defects in
the repair rather than in the original code** — five of eight independent lanes
returned REQUEST CHANGES on work that was already full-suite green. Three of
those were in the *test written to prove the fix*, and in each case the test's
fixture did not match the shape of the real artifact, so it passed while proving
nothing. 437-D writes a two-run fixture; that is exactly the shape at risk.

| Entry | Where |
|---|---|
| The measuring instrument is a claim too | `docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A rotted citation's fix target is itself a claim | `docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md` |
| Task pack authoring | `memory/task-packs.md` |

Resolved at authoring time via `python3 tools/cc/hooks/_recall.py "<topic>"`.
Re-run before executing rather than trusting this list — and note the retriever
is unreliable enough that a miss here is not evidence of nothing relevant.

## Implementation

### 437-A — the triage artifact

`scripts/run_pack_chain.sh`. Declare the path beside its two siblings, matching their form —
an env override with a session-state default — so the tests can drive it on a throwaway tree instead
of the live one. Read both existing declarations first and copy their shape rather than
inventing a third convention (`STANDING_PRINCIPLES` §13).

Write the row inside `post_commit_verify_and_finalize`'s **existing** `fin_rc == 3` and
`fin_rc == 4` branches — the outcomes are already classified there; only the persistence is
missing. Record enough for a human to act months later without the terminal scrollback:
the pack, the outcome, the commit, and a timestamp.

⚠ **Do NOT encode the outcome into `$LEDGER`.** `preflight_chain` tests membership with
`grep -qxF`, which is a **whole-line** match: a decorated row (`TP-999|LANDED-nostamp`) does
not equal the bare token, so the pack reads as *not done* and the driver **re-runs the `-p`
session** — driven previously to `HALTED-nocommit`, rc 1. The resume ledger's line format is
load-bearing; the triage record needs its own file.

⚠ **`scripts/` IS provenance-scanned** (unlike `.claude/workflows/`). Write every new comment
in terms of behaviour — never cite a pack id, a round, or a workflow id. Run
`python -m espalier provenance .` after the edit; it is ~1s.

### 437-B — the reader

The resume path must distinguish *done cleanly* from *done, needs triage*. Today
`preflight_chain` answers one question with one artifact. Adding a second artifact without
teaching the resume to read it reproduces this pack's own subject.

Two properties the implementation must hold, both currently true and easy to break:

- **A clean pack must still skip silently.** The whole point of the resume ledger is not
  re-running finished work; a reader that makes every resumed pack noisy will be turned off.
- **The triage report must not re-run the pack.** The commit is already in git. Surfacing
  the outcome and re-executing the pack are different acts, and only the first is wanted.

Decide explicitly whether a triaged pack, once resolved, is cleared from the file by hand or
by the driver, and say so in the comment. An append-only file nobody can clear becomes noise,
and noise gets ignored — which is where this pack started.

### 437-C — retired: the ledger row was corrected by the rebuild

`DEF-312d` asserted a behaviour the driver does not have; it was refuted and struck on
2026-08-20, and `DEF-644` (§C14, filed by the 2026-09-20 rebuild) describes the **silent
skip**, names both `LANDED-nostamp` and `LANDED-unverified`, and carries the `HALTED-nocommit`
leg 437-F covers. Nothing to rewrite (dispositioned 2026-09-21, TP-452 1-H). Keep `DEF-644`
open; this pack closes it, and the strike belongs to execution.

### 437-F — disambiguating the halt

**Fix shape (untested — this pack's Task 0 decides whether it is the right one).** At the
`:843` HEAD-did-not-advance branch, the driver currently has one outcome token for two causes.
It cannot ask the session why it stopped, so the signal has to come from the pack: a Task-0
refusal is a deliberate act and can leave its own mark (a stamped `State: SCRAPPED`, or a
refusal line in 437-A's triage artifact written by the executor before it exits).

**Refuted if** the executor cannot be relied on to leave that mark before exiting — in which
case the driver is being asked to infer intent from an absence, which is the shape this whole
pack exists to reject, and 437-F needs a different mechanism rather than a heuristic.

**Do not** infer the refusal from `git status`, the pack's mtime, or the absence of a commit.
Those are proxies for intent, and the pack's own Motivation records what happened last time a
proxy stood in for a fact.

### 437-D — the earn-the-red

The red must be a **produce→resume**, driven against a throwaway tree via the env overrides:

1. Run 1: drive a pack to `fin_rc == 3`. Assert the triage file records it.
2. Run 2 (resume, same ledger): assert the pack is reported as **needing triage** and that it
   is **not re-executed**.
3. The same pair for `fin_rc == 4`, which no test covers today.
4. A negative: a cleanly-landed pack still resumes as a silent skip, and writes nothing to the
   triage file.

`tests/test_run_pack_chain.py` already carries 46 tests over this driver — read its existing
harness and reuse it; do not build a second way to drive the script.

## Affected symbols

### Changed-semantics
- `scripts/run_pack_chain.sh::post_commit_verify_and_finalize` *(437-A — persist the triage
  outcome in the existing `fin_rc` 3 and 4 branches)*
- `scripts/run_pack_chain.sh::preflight_chain` *(437-B — the resume test gains a second
  question; the whole-line `grep -qxF` on `$LEDGER` must not change)*

### Added-paths
- *(none in the package surface. The new runtime artifact is a gitignored session-state file
  living beside its two siblings — it ships nowhere and adds no public path. **It still needs an explicit
  `.gitignore` row**: verified that no existing pattern covers a new `cc/_pack_chain_*.txt`.
  Run `python -m espalier surface-impact` at execution to confirm nothing else is implied.)*

## Reach

`DEF-644` is the only ledger member this pack claims (it succeeded `DEF-312d`, struck
2026-08-20; that row's wrong statement of the resume's behaviour was closed by the ledger
itself -- refuted 2026-08-20, `DEF-644` filed 2026-09-20 -- so it is history here, not a
row this pack closes). Enumerated:

| Item | Status | Evidence |
|---|---|---|
| `DEF-644` — `LANDED-nostamp` has no durable home | **CLOSED — 437-A + 437-B** | outcome reaches only `>&2` and `REPORT_ROWS`; both die with the process |
| `LANDED-nostamp` erased by a later resume | **CLOSED — 437-B** | the ledger write precedes the `fin_rc` branch, so resume reports `SKIPPED-resumed` |
| `LANDED-unverified` (`fin_rc == 4`) — same loss | **CLOSED — 437-A + 437-B** | identical destinations; **unnamed by `DEF-312d`**, which is why it had no owner (`DEF-644` names it) |
| `HALTED-nocommit` conflates a driver failure with a licensed Task-0 refusal | **CLOSED — 437-F** | the revised pack format added a second producer of the same token; driven at `:843`, both paths return 0 with no commit and are reported identically |
| The absence of any CLI/status surface over the file | **NOT REACHED** | deliberate: paid surface for a self-host dev tool (Scope (out)) |

**Explicitly not claimed:** this pack does not make the driver's landing *succeed* more often.
It makes a landing that needed a human impossible to lose. The rate of `fin_rc` 3 and 4 is
unchanged.

## Pass criteria

1. **The red is a produce→resume, and it fails before the fix.** Run 1 produces `fin_rc == 3`;
   run 2 on the same ledger reports the pack as needing triage. Before the change, run 2 emits
   `SKIPPED-resumed` with the triage need gone. Drive it on a throwaway tree via the env
   overrides — **never against the live `cc/` artifacts**.
2. **`fin_rc == 4` is covered by the same pair.** It has no test today, and it is the case that
   went unowned because `DEF-312d` never named it (`DEF-644` does).
3. **A clean pack still resumes silently.** No triage row, no extra output. If this regresses,
   the resume becomes noisy and the ledger's purpose is defeated — assert it, do not assume it.
4. **A triage-owed pack is never re-executed on resume.** The commit is already in git;
   re-running the `-p` session is the `HALTED-nocommit` failure this must not cause.
5. **The resume ledger's line format is unchanged.** `preflight_chain`'s `grep -qxF` stays a
   whole-line match against a bare token. Assert that a triage row lands in its **own** file
   and that `$LEDGER` still contains only bare tokens — the decoration trap, pinned.
6. **The new artifact is gitignored.** `git check-ignore` resolves it, and `git status` is clean
   after a driven run. A runtime file that shows up as untracked will eventually be committed by
   someone, and `git status`-based detectors go blind to what is excluded.
7. **No gate is weakened.** None of the 46 existing driver tests may be relaxed or skipped to
   accommodate the new artifact. Strengthening any of them is permitted.
8. **Every citation in this pack is re-derived before execution.** `scripts/run_pack_chain.sh`
   is actively edited; the function names above are the durable handles, and the `fin_rc`
   values, the write census, and the `print_report`-writes-nothing claim are all re-checkable
   in under a minute. Criterion 9 of the predecessor pack exists because a stale prescription
   shipped once already.
9. Full suite green · `ruff` clean · `audit` 0/0 · **`provenance` clean (`scripts/` is
   scanned)** · `pre-release` pass · integrity refreshed. Baselines derived at execution time,
   not copied here.
10. **A licensed Task-0 refusal and a driver failure are distinguishable on disk, and the
    chain survives the refusal.** Drive both paths to the same `:843` condition — one where
    the session refused because the pack's own oracle refuted it, one where the session simply
    made no commit — and assert the persisted outcome tokens DIFFER. Then assert the refusal
    does not halt: packs behind it still run. ⚠ The earn-the-red here is the pair, not either
    half: before the change both paths produce the identical row, so a test that drives only
    the refusal passes against the unfixed script.

## Files touched

**Modified**
- `scripts/run_pack_chain.sh` — 437-A, 437-B, 437-F ⚠ provenance-scanned: no pack/round/workflow ids
  in comments
- `.gitignore` — 437-A (one row for the new runtime artifact)
- `tests/test_run_pack_chain.py` — 437-D, 437-F

**Modified, local-only (0)**
- `task-packs/FORWARD_LEDGER.md` — no longer touched: 437-C's row correction was done by the
  2026-09-20 rebuild (`DEF-644`); the strike of that row belongs to execution

**Unmodified on purpose**
- `scripts/run_pack_chain.sh::finalize_landing` — the `fin_rc` classifier is correct; only the
  durability of its result is not (Scope (out)).
- `scripts/run_pack_chain.sh::print_report` — it stays echo-only. The fix is a persisted
  artifact plus a reader, not a report that writes a file nobody opens.
- `$LEDGER`'s line format — load-bearing for `grep -qxF`; see the decoration trap.

## Sub-task ordering

| # | Task | Checkpoint |
|---|---|---|
| ~~**437-C**~~ | Retired 2026-09-21: `DEF-644` already states the measured behaviour | — |
| **437-A** | The triage artifact + its `.gitignore` row | criterion 6 |
| **437-B** | The reader at the resume skip | criteria 1, 2, 3, 4 |
| **437-D** | The produce→resume earn-the-reds | criteria 1–5 |
| **437-F** | Disambiguate `HALTED-nocommit`; route the refusal to 437-A's artifact | criterion 10 |
| **437-E** | Full suite · ruff · audit · **provenance** · integrity | criteria 7, 9 |

**Ordering rationale.** 437-C was first and deliberately -- bookkeeping about a *measurement*,
which the predecessor pack recorded decays fastest when deferred (its own 432-A was pulled
forward for exactly this reason) -- and the ledger rebuild did it before this pack ran, so
it is retired (2026-09-21); a mid-execution reader now plans from `DEF-644`, which states
the measured behaviour. 437-A before 437-B because the reader needs something to read. 437-D last among the edits so the reds are driven against the
finished pair rather than a half-wired one.

## Estimated effort

| Sub-task | Budget |
|---|---|
| ~~437-C~~ | 0 (retired 2026-09-21) |
| 437-A | 45 min |
| 437-B | 60 min (the clean-skip / triage-skip distinction is the design) |
| 437-D | 75 min (a two-run harness is the bulk; reuse the existing one) |
| 437-E | 15 min + suite |
| 437-F | (unbudgeted at authoring; its pass criterion is 10) |
| **Total** | **~3h 15m** (re-derived 2026-09-21 after 437-C's retirement; 437-F unbudgeted) |

⚠ **437-D is the schedule risk.** A produce→resume test drives a real shell script across two
invocations. Reuse `tests/test_run_pack_chain.py`'s existing harness rather than writing a
second driver, and keep it deterministic — no sleeps, no wall-clock ordering.

## Sharp-edge entry to add

**"An outcome that only reaches stderr and an array has no home."** The chain driver already
*classified* the failure correctly, named it precisely, and printed a clear warning. Every
part of the diagnosis was right, and all of it was written to two places that vanish when the
process exits — so the quality of the message was irrelevant to whether anyone ever read it.
The tell: for any outcome a human is expected to act on, ask *"which file holds this after the
process exits, and what reads that file?"* Two questions, because a written artifact with no
reader is the same failure one layer down. Worse here, a later successful-looking run
**erased** the need, because the "did we do this?" record was written before the "did it go
cleanly?" branch — so unconditional bookkeeping recorded success for an outcome that was not
one.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: <run 1 produces `fin_rc == 3`; before the fix run 2 emits `SKIPPED-resumed`
  with the triage need gone, after it reports the pack as needing triage and does not
  re-execute it; the same pair for `fin_rc == 4`, uncovered today; a cleanly-landed pack
  still resumes as a silent skip and writes no triage row; `$LEDGER` still holds bare tokens
  only, so `grep -qxF` cannot be defeated by a decorated row>
- Date:
