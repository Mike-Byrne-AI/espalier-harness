---
description: Push the lane you just committed as a pull request with auto-merge armed and the approval marker bound to its final head; `--release vX.Y.Z` then tags the merge commit and creates the release.
---

Push the lane you just committed as a pull request with auto-merge armed and the approval marker bound to its final head; `--release vX.Y.Z` then tags the merge commit and creates the release.

## Usage

```
/ship                      — the unmerged commits on this branch, as one pull request
/ship --release vX.Y.Z     — after the merge: the tag on the merge commit and the GitHub release
```

You never type a branch name. Every step is one call to the driver,
`tools/cc/ship.py` (deployed with the harness; the standard library and `gh`),
which derives what it needs from git and gh, refuses by name the state it must
not act on, and runs the same on macOS, Linux and Windows. The mechanics of a
pull-request flow are order-sensitive -- bind the marker after the last push,
never rewrite a pushed lane, re-bind after a push, read back what was armed --
and an order that lived in prose and pasted bash blocks was an order a hurried
session, a second checkout or a Windows shell got wrong (2026-09-30: a lane sat
armed and unmerged with its title already correct). Each verb prints what it did,
or `ship: refused -- <why>` and exits 1, and leaves nothing half-done that a
later verb cannot recognise. `python` is shown for brevity; where it does not
print a Python 3 version, try the other interpreter name, then the launcher's
`py -3`.

**When to run it.** Whether `/handoff` pushes is one committed setting,
`handoff_push` in `espalier.toml`, and it is **off unless the file sets it to
`true`**: a push is outward-facing, so a repository opts in.

- **`handoff_push = true`:** a session pushes each lane **once, at its end**.
  `/handoff` writes its row, commits, and runs the `handoff` verb as its last
  step, so the handoff's commit rides the same push as the work. Run `/ship`
  yourself before the handoff only when the next lane needs this merge: `open`
  refuses a lane whose commits never touch `ESPALIER_MEMORY.md` unless given
  `--early "<reason>"`, because the handoff's row then becomes a second push on
  the lane (a check cycle restarted and a marker re-bound).
- **Off:** `/handoff` commits its row and pushes nothing, and `/ship` is how a
  lane leaves the machine, whenever you choose.

`/handoff`'s last step is one verb that reads the setting and either makes that
push (the `lane` and `open` steps below, or a push and a re-bind onto a pull
request already open) or says why it did not -- including, when the setting is
off and a pull request is open, that it will merge without the handoff's commit:

```bash
python tools/cc/ship.py handoff
```

## Step 0: What is there to ship?

```bash
python tools/cc/ship.py preflight
```

Refuses a dirty tracked tree (`/commit` first: ship moves commits, never a dirty
tree) and an empty range. Lists untracked files as a note only: they do not
ship and do not block. Prints one line per recently merged pull request whose
latest run of a check is red -- a check that is not required finishes after
auto-merge has landed the lane and reports to nobody otherwise (the SessionStart
banner's `Merged:` rule, the same states) -- so read that log
(`gh run view <id> --log-failed`) before arming another lane on top of it. When
the base's own post-merge proof is red, notes that `open` will refuse this lane
(a `revert/` lane excepted). Where
`handoff_push` is on, notes when this lane's commits never touch
`ESPALIER_MEMORY.md`: the handoff has not run for it, and `open` will refuse
it without `--early "<reason>"`. Prints the merge verdict against the base:
clean; conflicts only on the record files (`ESPALIER_MEMORY.md`, the forward
ledger and its probes roster), which `open` merges in first and resolves by
shape; or conflicts elsewhere, which `open` notes and pushes past -- the pull
request then reads DIRTY until you merge by hand.

## Step 1: Put the commits on a lane branch

```bash
python tools/cc/ship.py lane
```

On the default branch: creates `lane/<slug of the head subject>` at HEAD,
switches to it, and only then points the local default branch back at origin's
-- every commit the default branch carried is reachable from the lane before
the default branch moves, which is why the order is the tool's and not a
sentence. On a lane already: says so, and nothing moves.

## Step 2: Push once, open the pull request with the marker, arm auto-merge

```bash
python tools/cc/ship.py open
```

Refuses on the default branch (run `lane`), when an open pull request already
exists for the branch (after a push, run `rebind`), and when origin's copy of
the lane has commits this HEAD does not reach: merge them in
(`git merge origin/<lane>`). A pushed lane is never rebased or force-pushed; the
rewrite is what puts a push's check run and a title edit's run in a race.

Refuses, too, while the base's newest post-merge proof is red: nothing lands on
a red base, so the revert goes first, from a `revert/` lane, which it lets
through. The refusal names each pull request whose armed auto-merge would land
on the red base, with `gh pr merge --disable-auto <n>`; a flake clears with a
re-run of that run. It notes, without refusing, when this seat already has
another open pull request (by the seat whose latest claim or release names its
lane: every seat may push as one GitHub account).

Before anything is pushed, the base is merged in when the lane would conflict
with it (`git merge-tree` is the probe, git 2.38 or newer; an older git is a
note), and also when a path carrying a merge attribute changed on both sides
-- the probe reads such a path clean because the local merge honours the
attribute, and GitHub's merge does not. The record files two machines' lanes
collide on by construction -- the
memory file's session rows, the ledger's member rows and derived counts, the
probes roster -- are resolved by shape (`tools/cc/record_merge.py`, deployed
beside the driver): every row either side added is kept, every row either side
evicted is dropped, the memory file is pruned back to its cap with the
merged-in rows kept, the ledger's counts are re-derived, the probes roster is
unioned by id. The merge commit rides the one push, so the pull request is born
mergeable. GitHub's own merge honours no merge driver, so a lane pushed
conflicting sits `CONFLICTING` until a hand resolves it; this is that hand. A
conflict the resolver cannot take -- prose edited on both sides, a row changed
on both sides, one id filed on two machines, a path outside those three files
-- is a note, not a stop: the lane ships and reads DIRTY as it would have, and
the note names the files and the way back.

Then, in order: the diff against the base asked of the harness guard
(`tools/cc/ci_guard.py`, loaded from the tree when it is there -- a tree
without it has no marker to bind, and the verb says so; a guard that will not
load binds the marker anyway and says why) -- before the push, so a diff that
fails or lists nothing refuses with the lane still unpushed; one push; the pull
request created with its title carrying `HARNESS-UPDATE-APPROVED@<head7>` when
the diff touches a protected path -- **bound at creation**, so there is one
event, one check run and no title edit for a race to lose; auto-merge armed and
read back (a repository whose setting is off is named: merge by hand once the
checks are green). The
body is the commit subjects, or `--body-file <path>` for prose -- a file, never
a heredoc, so a backtick in the prose is text and not a command. `--title`
overrides the head subject; at most 72 characters. `--dry-run` asks the guard, prints the calls with the title it would bind, and
changes nothing.

The URL it prints is the handoff's `Next:` line. Go back to work. The next
SessionStart banner names the pull request on its `Open PRs:` line with its
check tally and what holds it; once it has merged, a `Merged:` line says so
until your local default branch has it, with the pull to run:

```bash
git switch main && git pull --ff-only origin main    # your default branch, as the banner names it
```

Start the next lane from there. An independent lane can start while this one
is still open; a lane that builds on this one waits for the merge.

## Step 3: When a check goes red, the head moves, or the lane falls behind

Six shapes to recognise:

- **`verify` red, its message naming two heads** -- the marker is bound to a
  head that is no longer the pull request's (you pushed after binding), or a run
  born from the push judged a title that was already re-bound. Re-bind:

  ```bash
  python tools/cc/ship.py rebind
  ```

  Refuses when HEAD is not the pull request's head (push first). Strips every
  earlier binding and binds one to the head. When the title is already right,
  an identical edit fires no check run, so the verb strips, waits for that
  edit's run to exist (a run that was not there before, not the push's own),
  then re-binds: the second run is created after the first and is the one that
  survives. On a tree whose workflow still judges the event payload's title (a
  newer one parked as `harness-guard.yml.new`), the verb edits nothing and says
  so: re-run the red check from its Actions page, or push a commit and run it
  again.
- **A test cell red** -- read its log (`gh run view <id> --log-failed`), fix,
  commit, `git push`, then `rebind`.
- **A required cell a lost runner ended** (`status` prints `required, runner
  lost:`) -- its runner ended it, not its tests: no hosted runner picked the
  job up, or a step was cancelled mid-run with none failed. Auto-merge waits on
  it forever, so re-run it once:

  ```bash
  python tools/cc/ship.py rerun
  ```

  Re-runs that workflow run's failed jobs (`gh run rerun <id> --failed`) and
  names the cells (`--dry-run` names them and re-runs nothing). It re-runs
  nothing, and says why and what to do instead, while anything else holds
  the merge: a required red its tests decided (fix it; a push re-runs every
  cell, a rebind does not), a run still going, another lost run already
  re-run, a lane behind or in conflict with its base (`catch-up` re-runs every
  cell), or another red in the same run, which `--failed` would retry too (it
  names `gh run rerun <id> --job <job>` for the cell alone). GitHub's attempt
  counter is the bound, so "once" holds across sessions and machines; a cell
  lost a second time is yours -- read its log, or push. The match is on
  GitHub's own wording, so a cell with the right outline and notes it does not
  know prints `required red, cause not read:` with the command that shows
  its log, never a guess either way.
- **Conflicts with the base** (`CONFLICTING` on GitHub; `conflicts with
  <base>` in the banner) -- the server cannot make this merge, so `catch-up`
  below makes it here: the base merged in with the record files resolved by
  shape, a push, a re-bind. A conflict outside the record files it refuses by
  name; then `git fetch origin && git merge origin/<base>`, resolve, commit,
  push, `rebind`. Never a rebase of a pushed lane: a merge carries the same
  content without rewriting what was pushed.
- **Behind the base, nothing red, armed and waiting** -- a repository whose
  branch protection requires the pull request to be up to date with its base
  holds it here; GitHub's merge state reads `BEHIND` and the banner says so.
  Every merge to the base puts every other open pull request behind it, so of
  two lanes in flight the second to merge takes this step:

  ```bash
  python tools/cc/ship.py catch-up
  ```

  Reads how GitHub sees the lane first, waiting out `UNKNOWN` (it recomputes
  mergeability after every merge to the base). `CONFLICTING`: the server
  cannot make the merge, so the verb makes it here -- a clean tree required,
  the base fetched, the record files resolved by shape, the merge pushed, the
  head awaited -- then re-binds. Otherwise it merges the base in on the server
  (`gh pr update-branch`, GitHub CLI 2.53 or newer), waits for the head to
  move (the reply lands before the merge does), pulls fast-forward only
  (refuses on an unpushed commit: push it, run it again), proves HEAD is the
  pull request's head, then re-binds. If the server answers that nothing was
  behind, the hold is something else: read the checks.
- **The base moved near the lane since its CI ran** (`status` prints `<base>
  moved N merge(s) since #n's CI tested it ..., near its files`) -- with the
  up-to-date rule off, a pull request merges on the CI that tested it with the
  base as of its last push. When the merges since then touch a path it
  changes, or a Python module one import away from one, run `catch-up` so CI
  tests the combination before it merges. A move elsewhere is said nowhere:
  the merge-tested green stands.

```bash
python tools/cc/ship.py status
```

The pull request's state, merge state, auto-merge, and the required reds by
name -- parsed whatever `gh pr checks` exits with, since it exits 1 on a failed
check and 8 while one is pending, the two states worth reading. A cancelled
required cell counts as red, never as green; a cell a lost runner ended is
named apart, with `rerun` when it can take one and the reason when it cannot.
With the up-to-date rule off, it also says when the base moved near the pull
request's files since its CI ran. Read-only apart from fetching the base and
the lane: it never re-runs or catches up anything itself.

## `--release vX.Y.Z`: tag the merge commit and create the release *(after the merge)*

Precondition: the lane carried the release fold -- the version surfaces, the
changelog fold, the freshness re-pin (on the Espalier-Harness source tree, the
release checklist's steps 1 to 3). Wait for the merge; stay on the lane branch,
since the pull request is named from it:

```bash
python tools/cc/ship.py release vX.Y.Z
```

Stops, in this order and before anything leaves the machine, unless: the tag is
the tree's version (read from `pyproject.toml`; a tree that keeps it elsewhere
compares by hand); the pull request for this lane is `MERGED` with a merge
commit (the tag lands on the merge commit, never on a lane commit: the publish
workflow fires on any `v*` tag push with no on-default-branch check, and a
package-index upload is immutable); the tag exists neither locally (a prior
attempt's leftover is inspected, never pushed) nor on origin. Then it tags the
merge commit, pushes that one tag by name (never a bulk tag push: more than
three tags at once creates no tag events and the publish workflow never fires),
reads the tag back from origin, and creates the release from the tag. The
release speed bump stops the call once, from the Bash and the PowerShell tool
alike; re-issue it verbatim. To rehearse without it, put `--dry-run` before the
tag (`release --dry-run vX.Y.Z`): after the tag, the bump fires once too. The publish
workflow then parks on its environment's required reviewer: that approval is
the operator's click in the browser, by design -- do not grant it from the
command line. Verify the publish from the package index, not from the release
page; on the Espalier-Harness source tree the release checklist's last step
says how.

---

On the Espalier-Harness source tree the branch protection requires the pull
request and its required checks; the `test (3.x)` cells run the tier the diff
earns (`scripts/proof_tier.py --base`, the same rule as the local run), 9 to
40 minutes measured in September 2026. The guard's `verify` check reads the
pull request title as it is at check time, not as the event that started the
run saw it, so a push's run and a title edit's run agree whichever one GitHub
kept.
