End the session cleanly and leave the next Claude Code session with usable continuity.

> **First:** if you have uncommitted changes (`git status`), decide whether to
> `/commit` them before handing off — `/handoff` persists *reasoning + memory*,
> not your code. Commit the work, then hand off.
>
> That is about **your code**. `/handoff` then writes tracked files of its own
> (ESPALIER_MEMORY.md always; `memory/` or `docs/FAILURE_MODES.md` on a step-1b
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

## 1b. Surface ship-tier'd promotion candidates

Run the candidate pass so durable insights from this session are proposed
for promotion before they die in a Session-Log row:

```bash
python tools/cc/reflect_protocol.py --candidates
```

Each candidate carries a proposed **ship-tier** (`SHIP_ADOPTER` → `docs/FAILURE_MODES.md`,
the catalog deployed with its content and so reachable by adopters via `/recall`;
`SELFHOST_DEV` → the `memory/` folder; `OPERATOR_PRIVATE` → keep local) plus its
nearest existing note. Act on each per the `reflect` skill's *Memory Promotion*
section — a `SHIP_ADOPTER` insight goes to `docs/FAILURE_MODES.md` (generalized),
not the non-shipping `memory/` folder. **Not `docs/SHARP_EDGES.md` or
`docs/CONVENTIONS.md`:** `init` seeds both as near-empty **stubs** for the host
repo's own patterns, so this repo's copies never reach an adopter — they stay the
right home for a footgun *this* repo trips on, but an adopter-relevant lesson
written there reaches nobody. Propose-not-write: never auto-record; you approve.
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
- next session entry point

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
trailer, prints the ahead-of-origin count for step 7, and drives the owed-list
probes so step 7 starts from their verdicts. `--dry-run` prints the plan. The
manual form of each step follows — **if the script ran, skip steps 3 and 5
below; they are the manual form, not a follow-up** (a second finalize is
harmless; a second commit finds nothing staged).

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
| `memory/*.md` | step 1b | on a `SELFHOST_DEV` promotion |
| `docs/FAILURE_MODES.md` | step 1b | on a `SHIP_ADOPTER` promotion |
| its byte-mirror `espalier/assets/docs/FAILURE_MODES.md` (self-host only — not deployed by `init`) | step 1b | **paired** with the row above — run `python scripts/sync_asset_docs.py` first |

That last row is the one a hand-kept list loses. `docs/` is byte-pinned to
`espalier/assets/docs/`; committing one side alone reds the parity contract and
leaves the tree dirty — exactly what this step exists to prevent. The registry,
not this table, is canon: `espalier/mirror_registry.py` (Espalier source repo).
A repo without those mirrors simply has fewer rows.

Everything else this command touches is disposable local state on THIS repo —
`cc/GOAL.md`, `cc/_working_summary.md`, `cc/blueprints/**`, the archive spill
`docs/session-archive.md` (generated on your tree; not deployed). **Confirm with `git check-ignore <path>` rather than
assuming**: which paths a repo ignores is that repo's `.gitignore`, and an
adopter's differs from the harness's. If a path this command wrote is NOT
ignored there, it needs committing or ignoring — silently leaving it untracked
is how a pruned memory row stops existing anywhere but one disk.

**Stage by explicit path. Never `git add -A` or `git add .`** — a handoff
routinely runs on a tree that also holds a parallel session's in-flight work, and
a broad stage silently attributes someone else's changes to your memory commit.
(`/commit` does stage broadly; that is its own call on a tree you have just
reviewed. Here you have not reviewed the whole tree — you have only written to
part of it.)

If step 1b wrote `docs/FAILURE_MODES.md`, run `python -m espalier provenance .`
before staging: a promotion drafted from session notes routinely carries an
internal build tag, and that reds a shipping-surface contract after the commit.
On any repo other than the Espalier-Harness source tree this census stands down
and exits 0 without scanning — the tags it hunts are Espalier's own, and the
contract it protects is Espalier's own, so there is nothing here to check on
your tree and nothing to fix if it says so.

```bash
git status --short                       # look first; know what is yours
git add ESPALIER_MEMORY.md               # plus any step-1b paths, each named
git commit -m "docs(memory): <what this session established>"
git status --short                       # confirm what remains is deliberate
```

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

## 7. Refresh cc/GOAL.md (if the repo keeps one)

If this repo maintains a `cc/GOAL.md` goal/progress snapshot, update it to match
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
perishable half and drops the durable one. This file is gitignored, so no test can
observe its structure — the ordering is a convention nothing mechanical can catch,
which is why it is stated here. Keep the final section well under the goal cap; a
single trailing section larger than the whole budget is head-cut in place.

**Start from the owed probes' verdicts, not from the prior list.** The
`after-memory-row` phase above already drove them; by hand:
```bash
# Espalier source repo only -- not deployed by init; an adopter re-reads the bullets by hand
python scripts/check_handoff_landing.py --skip-tests --skip-trailer --skip-keys
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

Repos without a `cc/GOAL.md` can skip this step (or create one to opt in).

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
point is to leave `main` green, not to record that it was not.

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

