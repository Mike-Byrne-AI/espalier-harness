---
description: End the session cleanly and leave the next Claude Code session with usable continuity.
---

End the session cleanly and leave the next Claude Code session with usable continuity.

> **First:** if you have uncommitted changes (`git status`), decide whether to
> `/commit` them before handing off — `/handoff` persists *reasoning + memory*
> and, where `espalier.toml` sets `handoff_push = true`, then pushes the lane
> once (step 8); it commits nothing of yours. Commit the work, then hand off.
> (Step 5 names its own files on the commit line, so a change you staged and
> did not commit stays staged and out of the handoff's commit.)
>
> That is about **your code**. `/handoff` then writes tracked files of its own
> (ESPALIER_MEMORY.md always; the target step 1b prints, on a step-1b
> promotion) — **step 5 commits those.** Without it every handoff ends on a dirty
> tree by construction, and the next session opens on uncommitted memory that
> looks like someone's abandoned work.

## 1. Capture reasoning that should survive this session

Record only durable facts: decisions, rejected alternatives, discovered patterns, unresolved risks, and next-step constraints. Do not record noise.

**Write each entry for the next session's COLD read** — it is reinjected at orientation. Lead with the conclusion/decision/owed, then the supporting detail (inverted pyramid), so the load-bearing line lands first and an over-long entry gets rewritten tighter rather than silently cut (the `record` command prints a write-time advisory past the soft target; the reinjection selection drops *whole* entries, newest/pinned first, never slicing one mid-thought). **Pin the one to three most load-bearing entries** so they reach the next session over pure recency:

```bash
# pin at record time:
python tools/cc/cognitive_blueprint.py record --kind decision --carry-forward --description "..."
# or pin an already-recorded entry by index:
python tools/cc/cognitive_blueprint.py pin 0
```

Record a design decision:

```bash
python tools/cc/cognitive_blueprint.py record --kind decision --description "chose X over Y because Z"
```

Record an alternative that was considered and rejected:

```bash
python tools/cc/cognitive_blueprint.py record --kind alternative_rejected --description "considered X, rejected because Y"
```

Record a discovered pattern:

```bash
python tools/cc/cognitive_blueprint.py record --kind pattern_discovered --description "files in X follow pattern Y"
```

View the current session chain when needed:

```bash
python tools/cc/cognitive_blueprint.py chain
```

If a record/finalize command reports that no active blueprint exists, start one once, then retry the capture/finalize step:

```bash
python tools/cc/cognitive_blueprint.py start
```

## 1b. Surface promotion candidates and their targets

Run the candidate pass so durable insights from this session are proposed
for promotion before they die in a Session-Log row:

```bash
python tools/cc/reflect_protocol.py --candidates
```

Each candidate prints a `proposed: <tier> -> <target>` line beside its nearest
existing note. **The printed target is where a promotion goes on this tree** — the
pass reads which tree it runs on, so do not route from memory or from a table
copied out of these docs. On a repo that adopted the harness it names
`docs/SHARP_EDGES.md`, the catalog `/recall` reads back on every tree, or keep
local for a note about a person; the Espalier source repo has its own table,
because its docs ship to adopters. Act on each per the `reflect` skill's
*Memory Promotion* section. Propose-not-write: never auto-record; you approve.
`MEMORY CANDIDATES: none` is the common, correct result.

A candidate you have read but will not decide this session is **`held`**: append
a `held` row to the disposition log (same schema, the printed `key` verbatim).
The pass re-proposes held rows from the log on every later run until a decision
row lands, so a hold survives the session. A key written into the Session-Log
row and called "logged" does not — the lineage walk forgets it past a 60-minute
gap, and step 7c reds on a cited key that has no log row. Never cite a key the
log does not hold.

## 2. Update ESPALIER_MEMORY.md

**Prepend** the new Session Log row — newest-first, directly under the table header. (This said "append" for months while every session prepended; one row followed the doc and sits out of order at the bottom of the live file to this day. Recency is now read from each row's `| YYYY-MM-DD` cell rather than its position, so a stray row no longer misreports the digest — but same-day rows tie-break on file order, so prepending is what keeps *today's* rows in the right order.) The `post_write_check` hook (`tools/cc/hooks/post_write_check.py`) auto-archives the oldest row to `docs/session-archive.md` (generated on your tree; not deployed) when the write pushes ESPALIER_MEMORY.md over the 120-line cap. Manual `espalier memory prune --rows N` is still available for bulk archival but is no longer the routine path.

Update only durable repo operating knowledge:

- harness decisions made this session
- footguns discovered
- stable command or hook behavior changes
- current known release blockers
- next session entry point (name the lane, not a pull request number: where
  `handoff_push` is on, the pull request is opened after this row is written,
  by step 8's push, and the next SessionStart banner's `Open PRs:` line names
  it; where it is off, nothing is pushed and no pull request will appear, so
  say the lane is committed locally)

Keep ESPALIER_MEMORY.md compact. Preserve only the recent useful session log entries.

## 3. Finalize the cognitive blueprint

**Steps 3 and 5 are one script call** on the Espalier-Harness source tree
(an adopter repo without `scripts/` runs the two commands by hand):
```bash
# Espalier source repo only -- not deployed by init; an adopter runs steps 3 and 5 by hand
python scripts/handoff_mechanics.py after-memory-row \
    --message "docs(memory): <what this session established>" \
    [--also memory/<new-note>.md] [--trailer "Claude-Session: <url>"]
```
It prunes ESPALIER_MEMORY.md to its cap (a row prepended by a script lands
without the hook's autoprune), finalizes the blueprint, stages the memory file
and each `--also` path with its byte-mirror twin, commits with the canonical
trailer and those paths on the commit line (step 5's rule), prints the
ahead-of-origin count for step 7, and drives the owed-list probes so step 7
starts from their verdicts. `--dry-run` prints the plan. The manual form of
each step follows — **if the script ran, skip steps 3 and 5 below; they are
the manual form, not a follow-up** (a second finalize is harmless; a second
commit finds nothing to commit on its paths).

```bash
python tools/cc/cognitive_blueprint.py finalize
```

This creates continuation fragments for the next `/context-load` session.

## 4. Surface any captured compaction summaries

If the session compacted, the post-compaction hook saved the verbatim Claude
Code summary for durability — the "pick up where we left off" text, preserved
after Claude Code drops the transcript. Surface the **path** only (never inline
the body — it is operator-writable free text kept out of every priming channel;
read it on demand with `/read-summary`):

```bash
[ -d cc/blueprints/compact_summaries ] && ls cc/blueprints/compact_summaries/
```

`/read-summary` (no args) now dumps the live `cc/_working_summary.md` — the
always-current working summary (step 6); `--session <stem>` reads a specific
archived capture from the list above, `--list` enumerates them.

## 5. Commit the handoff's own artifacts

The preamble's `/commit` covers **your code**, and it runs *before* every step
above. Steps 1b and 2 then write **tracked** files. Committing them is this
command's job — not the next session's problem.

**This step runs BEFORE steps 6-7 on purpose.** Those two author a working
summary and a goal snapshot that quote an ahead-of-origin count. Commit after
them and every handoff ships a snapshot that is off by exactly one, into the
banner the next session opens on. Commit first and they can *measure* the tree
(`git rev-list --count origin/<branch>..<branch>`) instead of asserting about it.

Paths in scope — **derive, do not trust this list**. Run `git status --short`
and stage only what *this command* wrote:

| Path | Written by | When |
|---|---|---|
| `ESPALIER_MEMORY.md` | step 2 | every handoff |
| every file step 1b wrote: the printed `proposed:` target on a promote, the nearest note on an update | step 1b | on a disposition that writes |
| the byte-mirror `espalier/assets/docs/FAILURE_MODES.md` (self-host only — not deployed by `init`) | step 1b | **paired** with `docs/FAILURE_MODES.md` as that target — run `python scripts/sync_asset_docs.py` first |

That last row is the one a hand-kept list loses. `docs/` is byte-pinned to
`espalier/assets/docs/`; committing one side alone reds the parity contract and
leaves the tree dirty — exactly what this step exists to prevent. The registry,
not this table, is canon: `espalier/mirror_registry.py` (Espalier source repo).
A repo without those mirrors simply has fewer rows.

Everything else this command touches is disposable local state on THIS repo —
`cc/GOAL.md` (none when `espalier.toml` sets `goal_snapshot = false`),
`cc/_working_summary.md`, `cc/blueprints/**`, the archive spill
`docs/session-archive.md` (generated on your tree; not deployed). **Confirm with `git check-ignore <path>` rather than
assuming**: which paths a repo ignores is that repo's `.gitignore`, and an
adopter's differs from the harness's. If a path this command wrote is NOT
ignored there, it needs committing or ignoring — silently leaving it untracked
is how a pruned memory row stops existing anywhere but one disk.

**Stage by explicit path. Never `git add -A` or `git add .`** — a handoff
routinely runs on a tree that also holds a parallel session's in-flight work, and
a broad stage silently attributes someone else's changes to your memory commit.
A by-path stage is only half of it: the commit line names the paths too,
because the index can already hold something you did not stage.
(`/commit` stages and commits by path too: the list it shows beside the
message, approved with it. Here the list is the files this handoff wrote.)

If step 1b wrote `docs/FAILURE_MODES.md`, run `python -m espalier provenance .`
before staging: a promotion drafted from session notes routinely carries an
internal build tag, and that reds a shipping-surface contract after the commit.
On any repo other than the Espalier-Harness source tree this census stands down
and exits 0 without scanning — the tags it hunts are Espalier's own, and the
contract it protects is Espalier's own, so there is nothing here to check on
your tree and nothing to fix if it says so.

```bash
git status                               # look first: know what is yours, and that nothing is in progress
git add -- ESPALIER_MEMORY.md <any step-1b paths>
git commit -m "docs(memory): <headline, at most 72 characters>" \
           -m "<two lines: what the row records; what the next session picks up>" \
           -m "<the canonical co-author trailer your task-pack conventions name>" \
           -- ESPALIER_MEMORY.md <any step-1b paths>
git status --short                       # confirm what remains is deliberate
```

If that first `git status` says a merge, a cherry-pick or a rebase is in
progress, stop before the add line and ask. Git refuses a path-limited commit
during a merge or a cherry-pick, a rebase would take the row into the history
it is rewriting, and whatever you stage meanwhile belongs to the operation:
`git merge --abort` deletes it from disk along with the merge. Do not fall back
to a broad commit.

`<any step-1b paths>` is each path from the table above that this handoff
wrote, the byte-mirror twin included, or nothing. **The commit line names the
same paths as the add line**: without them the commit takes the whole index,
and a change somebody staged before the handoff (your own, held back from
`/commit`, or a parallel session's) would ride into a memory commit nobody
reviews and leave with step 8's push. A change staged before you started is
not yours to commit here: it stays staged and uncommitted, and you do not
unstage it. It does keep the tracked tree dirty, and where `handoff_push` is
on, step 8's ship driver refuses a dirty tree: name the change in the summary,
for its owner to commit or unstage before the push.

The subject is an email subject: 72 characters at most and no pack or ledger id
(those live in the row itself); the second `-m` is the body that names what the
row records, so the subject can stay short.

**Nothing to commit is valid only as an observation, never an assertion.** Step 2
writes ESPALIER_MEMORY.md on every handoff, so "nothing to commit" and "step 2
ran" cannot both be true. Prove it with `git status --porcelain ESPALIER_MEMORY.md`
and paste the empty output into the summary — otherwise there is something to commit.

## 6. Refresh the working-summary doc

**Author step 7 before this one.** Nothing binds their order (step 5's commit
must precede both; 7b must follow 7), and the `## Notes to next session` that
step 7 authors is what the next session OPENS on, injected by the banner —
while this doc is pull-only. Spend the freshest context on the perishable
note, then write the summary. **Steps 6.2, 6.3, 7b and 7c are one script call**
once the body below and the goal file are written:
```bash
# Espalier source repo only -- not deployed by init; an adopter runs 6.2, 6.3, 7b and 7c by hand
python scripts/handoff_mechanics.py after-goal
```
It refuses until the 9-section body is in place and the goal snapshot (step 7)
carries today's `_Updated:` line, then appends the resume index, appends the handoff
leg under the header `read_summary` splits on, snapshots the record branch,
pushes it to the record remote (§7b: the checkout-local `espalier.recordRemote`
key, `origin` on this tree; an unset key or a refused push stops the script
there, loudly) and runs
the landing check last. The manual form of each step follows — **if
the script ran, skip 6.2, 6.3, 7b and 7c below**: a second pass appends the
resume index and the archive leg twice, under a header `read_summary` splits
on, and the script's own re-entry guard will then refuse until the duplicate
index is removed.

`cc/_working_summary.md` is the single live "pick up where we left off" tool doc
— overwritten at every boundary so it is never stale (the post-compaction hook
writes it automatically at compaction; handoff is a boundary with no
auto-compaction, so write it by hand here). It is pull-only — referenced on
demand, never injected.

> Parallel-session note: on ONE working tree, two instances overwrite this same
> path (last-writer-wins) — the per-session archive (step 3 below /
> `cc/blueprints/compact_summaries/<stem>.md`) is the safe per-session record.
> Separate git worktrees don't collide. See docs/SHARP_EDGES.md.

Produce an **exact mirror of the Claude Code post-compaction summary shape**
(summarize from the raw transcript for fidelity, not just your compacted
context — the resume index points to it):

```text
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Current Work
9. Optional Next Step
```

Do these THREE steps **in order** — step 3 depends on the file step 1 creates:

1. **Write the 9-section mirror to `cc/_working_summary.md` (OVERWRITE)** — your
   hand-authored narrative (use the Write tool / editor; the body is composed,
   not generated). ESPALIER_MEMORY.md and the blueprint remain the curated truth; this is
   additive recall.
2. **Append the mechanical resume index** beneath that body.
3. **Preserve this session's final state in the archive** by *appending* a
   handoff leg (never `cp`/overwrite — the archive file may already hold this
   session's compaction captures, and `cp` would clobber them).

```bash
# Step 1 produced cc/_working_summary.md (the 9-section body) above, by hand.
# Step 2: append the resume index to that existing file:
python tools/cc/session_summary.py >> cc/_working_summary.md

# Step 3: resolve <stem> for THIS session from `python tools/cc/read_summary.py
# --list` (the newest [transcript] row) and substitute it below. <stem> is a
# manual placeholder, NOT shell command-substitution. Append (>>), never cp.
# The header MUST be the exact phrase read_summary._ARTIFACT_HEADER matches or
# the leg won't split out under --session/--all:
printf '\n\n===== compaction captured (transcript <stem>) =====\n\n' >> cc/blueprints/compact_summaries/<stem>.md
cat cc/_working_summary.md >> cc/blueprints/compact_summaries/<stem>.md
```

Verify the substitution: `python tools/cc/read_summary.py --list` must NOT show a
literal `<stem>` row. The handoff leg now lives in
`cc/blueprints/compact_summaries/<stem>.md` — inspect that file directly to
confirm it landed. (It surfaces via `--session <stem>` only AFTER Claude Code GCs
the transcript: `--session` is transcript-primary while the transcript exists, so
it reads the live transcript, not the archive leg.)

The doc is local-only and git-ignored — it never ships and is never committed.

## 7. Refresh cc/GOAL.md

First check the opt-out: when `espalier.toml` sets `goal_snapshot = false`, skip
this step (and if a `cc/GOAL.md` is still there, tell the operator the banner keeps
showing it until the file is deleted). Otherwise `init` seeded a `cc/GOAL.md`
goal/progress snapshot unless one already existed. Update it to match
where the build now stands — the current phase, what just shipped or moved, the
next gate, and an honest "how close." It is the local, gitignored answer to
"where are we?" that SessionStart surfaces near the top of the next session,
distinct from ESPALIER_MEMORY.md's durable knowledge + session log. Refresh the
`_Updated: <date>_` line so staleness stays visible; keep it tight (it is
byte-bounded in the banner) and honest — no "release-ready" without the evidence.

**Section ORDER is load-bearing — the perishable block first, the goal-proper last.**
The banner bounds this file and cuts from the TOP, keeping whole trailing `## `
sections (`session_start.py::_truncate_keeping_tail`). So the handoff notes belong
at the head where they can yield, and "where we are"/"next gate" belong at the tail
where they are protected. Reorder them and the banner faithfully delivers the
perishable half and drops the durable one. A test pins the order `init` seeds; once
you edit the file, nothing mechanical can observe its structure (it is gitignored),
which is why the rule is stated here. Keep the final section well under the goal cap; a
single trailing section larger than the whole budget is head-cut in place.

**Start from the owed probes' verdicts, not from the prior list.** The
`after-memory-row` phase above already drove them; by hand:
```bash
# Espalier source repo only -- not deployed by init; an adopter re-reads the bullets by hand
python scripts/check_handoff_landing.py --skip-tests --skip-trailer --skip-shape --skip-keys
```
It re-derives every `## Still owed` bullet in well under a second, so
hand-verify only what it still calls open.

When nothing is owed (Espalier source repo -- not deployed by `init`; an adopter has
no owed probes), remove `cc/GOAL_OWED.json` and write a NON-bullet line under
`## Still owed` carrying the witness `<!--owed:none-->`, with no other owed marker
anywhere in the file. Clean is a presence: the gate refuses prose without that
witness, because a re-titled heading or an indented bullet reads to its parser
exactly like nothing owed (driven 2026-09-26).

**Re-verify carried-forward state before you rewrite it.** The prior owed-list and
any "N ahead of origin" count are *inputs*, not ground truth — SessionStart surfaced
them, but an item it still calls "owed" may have shipped since. A stale "owed"
laundered forward is trusted as input next session and rewritten again, so it survives
indefinitely unless re-grounded here.

⚠ **Check each owed item by looking for the THING, not by reading a commit range.**
An earlier version of this instruction prescribed `git log --oneline
origin/<branch>..<branch>` — and that oracle is unsound for this question, which was
proved the expensive way on 2026-08-31. An owed item had landed 3h20m earlier in a
commit that was *already pushed*, so it sat outside that range; the check listed three
commits, none of them the one that closed the item, and the false "owed" was carried
forward for two more sessions. **A commit-range oracle answers "what changed
recently". An owed-list needs "is this done".** Ask the second question directly —
does the section exist, does the file contain it, does the count still exceed the
threshold — and only then rewrite the list.

**An owed item must be mechanically re-derivable, or say why it is not.** Anything you
carry forward needs a check that a later session can run without your context; an item
with no local oracle should say so explicitly rather than be silently untestable. Step
7c drives these, so an item that has quietly landed is reported instead of inherited.

**Owed belongs HERE, not in the session record.** State what is outstanding in this
file, which is rewritten every handoff and can therefore self-correct. A dated
`ESPALIER_MEMORY.md` row is history and is frozen the moment it lands — an "OWED:"
clause inside one cannot ever be corrected without falsifying the record, and it is
the frozen copy that gets read forward. Narrative in the record; obligations here.

**Any count you write here must be derived NOW, not carried from the banner you
read at startup.** Step 5's commit is already in the tree, so `git rev-list --count
origin/<branch>..<branch>` includes it — that is the number, and it is why the
commit runs before this step rather than after. Never transcribe an ahead-count
from earlier in the session: it was true before step 5 and is off by one after.

**Author the `## Notes to next session` section** (keep it near the top). This is
YOUR note to next-session Claude, written now from the freshest possible vantage —
you just made the handoff artifacts. It is discretionary and informal, NOT a fixed
template: whatever the you-who-did-the-work would most want whispered to the
you-who-picks-up. Good candidates: what's in flight + how to resume it, decisions
the operator settled this session (so next-you doesn't re-litigate them), a
last-second finding, a hunch you didn't chase, a dangling thread. The structured
artifacts capture what's *settled*; this captures what's *fresh and perishable*.
Replace the prior session's note — it does not accumulate. The session OPENS by
reasoning over this note, so write it to prime that first-thoughts read.

**If the file is absent:** on the Espalier source repo, skip this step and leave it
absent. Its GOAL is the operator's own:
`scripts/check_handoff_landing.py` (Espalier source repo only) reads the file's
presence as the tell that a checkout is the operator's tree, and
`scripts/handoff_mechanics.py` (Espalier source repo only) prints which case applies.
On any other repo that has not opted out, the tree predates the seed or the file
was deleted: tell the operator you are recreating it and that `goal_snapshot = false`
in `espalier.toml` stops it, then create it with the sections `init` seeds, in this
order -- `## Notes to next session`, `## Still owed`, `## Goal`,
`## Where we are / next gate` -- and ask the operator for the goal rather than
inventing one.

## 7b. Snapshot the record branch *(Espalier-Harness self-host step — an adopter repo has no `scripts/` and skips this)*

Everything this session generated that `.gitignore` keeps out of the tracked
tree — blueprints, packs, reports, the session archive — currently exists on
one disk with no history. Fold it into `refs/heads/record`:

```bash
# Espalier source repo only -- not deployed by init
python scripts/record_snapshot.py
```

It runs **after** step 7 on purpose: the goal snapshot was just rewritten, and
this should carry that version rather than the previous one.

The ref is an orphan branch that shares no history with the working branch, and
nothing in the harness or the suite reads it. The build uses a separate index,
so your index, `HEAD` and worktree are untouched. Each run chains onto the last,
so the branch is a *history* of the record; git de-duplicates unchanged blobs,
so a quiet session costs almost nothing and an unchanged tree makes no commit
at all. A skipped run therefore loses nothing permanent — only the delta.

**On exit 2 the run refused; it did not fail silently.** Either its
content-exclusion config is absent, or `--verify` found the ref behind the tree.
The stderr message names which and what to do about it — read it rather than
retrying. `--dry-run` reports what would be recorded without writing anything.

This step only writes the ref locally; the `after-goal` script pushes it right
after to the **record remote**: the checkout-local
`git config --local espalier.recordRemote <name>` when that key is set, else
`origin` (`scripts/record_snapshot.py::record_remote` is the one reader — Espalier
source repo only, not deployed by `init`; `git push <name> record` is the manual
form). On the public checkout the key
names the renamed private archive (`DEC-31`; the First-publish runbook sets it
in the same sitting as the remotes), so the record never reaches the public
remote; and because `espalier.toml` sets `record_remote_required = true`, an
UNSET key refuses rather than defaulting — a fresh clone has no local config,
and the default would be the publishing direction — measured 2026-09-07, 31 of 49 snapshots had never left the disk
because the push was a separate act nobody took. Before a record's FIRST push, run `python
scripts/record_snapshot.py --audit-history` (Espalier source repo only): the
exclusion rule binds at write time, but the vocabulary is
mutable and history is not, so material that looked clean under an older
vocabulary stays reachable while `--verify` still reports the tip as current.
That audit is the only mechanical way to know the rule was actually honoured.

The record is append-only in practice: `git add -f` takes an explicit list, so a
path left out today can be added tomorrow, but a path included today cannot be
withdrawn from a pushed history.

To read anything back out, use `git archive record | tar -x` or
`git show record:<path>`. **Never `git checkout record -- <path>`** — that
writes the file *and* stages it onto your working branch, silently growing the
tracked set of the very repo that deliberately ignores this material.

## 7c. Re-check what you just wrote *(Espalier-Harness self-host step — an adopter repo has no `scripts/` and skips this)*

```bash
# Espalier source repo only -- not deployed by init
python scripts/check_handoff_landing.py
```

⚠ **This step exists because every step above it writes AFTER the session's last
verification ran.** The suite ran before step 5's commit; steps 6, 7 and 7b then
rewrote the working summary, the goal snapshot and the record. The
`ESPALIER_MEMORY.md` row is the last thing a session writes, and nothing re-reads
it.

It also reads the new row's cited reflect-candidate keys against
`.espalier/memory_candidate_log.jsonl`: a key with no log row is a claim about a
file that is false, and the candidate it names is already gone (step 1b's `held`
rule is the durable form).

That is not hypothetical. `main` has been RED AT HEAD five times by this exact
mechanism — four on `ESPALIER_MEMORY.md`, a tracked file, so each was a genuine CI
red on a commit that changed no code; the fifth on the ledger, gitignored at the
time (tracked since 2026-09-21), so its tests skipped in CI and the red was
local-only and therefore invisible until the next full run.

It is deliberately not the full suite. At ~14 minutes nobody runs that after a
handoff, and a gate nobody runs is not a gate. The selection is the subset that has
actually caught this class and takes about seventy seconds (measured). It also checks that the
step-5 commit carries the canonical co-author trailer, which the script parses
from this repo's own task-pack conventions rather than restating.

**On exit 2 it found something real.** Fix it and amend the step-5 commit — the
point is to leave `main` green, not to record that it was not. Amend by path,
as step 5 committed: after a fix to a file, `git add -- <the paths you fixed>`
and then `git commit --amend -- <the paths you fixed>`; after a fix to the
message alone, `git commit --amend --only`. A bare `--amend` takes the whole
index into the commit, the change step 5 left staged among them. Edit the
message in place (the editor opens on it, or pass `-F <file>` with the whole
message; from a tool call the editor is usually a no-op that keeps the old
message, so `-F` is the form that works there): `--amend -m "<subject>"`
replaces the entire message and drops the body and the trailer, which reds the
trailer arm on the very next run.

## 8. Emit the handoff summary

Return this summary **last** — every other step has now run, so `Changed:`
can name the step-5 commit SHA and `Proof:` can reflect the final tree:

```text
SESSION SUMMARY
Repo: {name}
Branch: {branch}
Changed: {files touched}
Proof: {green | red | not run}
Blueprint: {finalized | not finalized, reason}
Memory: {updated | not updated, reason}
Next: {smallest useful next step}
Risks: {remaining blockers or none}
```

Then the push, which is the repository's own committed choice: `handoff_push`
in `espalier.toml`, **off unless the file sets it to `true`** (a push is
outward-facing, so a repository opts in). On a repository whose default branch
takes direct pushes, the pull-request flow below does not apply: with the
setting on, `git push`; otherwise leave the commit local. Everywhere else, one
verb reads the setting and says which way it went:

```bash
python tools/cc/ship.py handoff
```

- **`handoff_push = true`:** the lane's ONE push, carrying the session's work
  and this handoff's commit together: a lane branch when HEAD is the default
  branch, the push, the pull request with the approval marker bound at
  creation, auto-merge armed and read back (`/ship` documents each verb). If
  the lane already has an open pull request (it was shipped mid-session with
  `open --early`), the verb pushes this commit onto it and re-binds the marker
  to the new head -- the memory row must land, not sit local while the pull
  request merges without it. Either way, when the lane would conflict with its
  base (two machines' handoffs collide on this very row), the base is merged in
  first with the record files resolved by shape (`/ship` step 2), so the push
  leaves the pull request mergeable and the merge commit rides it. Once the
  push lands, the verb releases this machine's live claims on the lane on the
  mail channel (`/inbox` step 5): the claim's lifetime is the lane's time on
  this machine, so no claim is left warning the other box forever.
- **Off (the default):** nothing is pushed. The commit stays on this branch in
  this checkout, and the verb prints how to push it (`/ship`) and how to opt in.
  Say so in the summary: the next session here reads the row while it stays on
  this branch, but another machine or clone sees it only after a push.

Either way, say in the `Next:` line what happened -- the URL the driver
printed, "committed locally, not pushed (handoff_push is off)", or the direct
push -- so the next session knows whether its local default branch is behind a
merge it did not see. Shipping here, after the row, is the order that costs one
check cycle per lane: a lane shipped mid-session makes this commit a second push
(the checks restart and the marker is re-bound), or its own pull request, which
is why, where `handoff_push` is on, `open` refuses a lane that does not carry its
row unless given `--early "<reason>"`.

