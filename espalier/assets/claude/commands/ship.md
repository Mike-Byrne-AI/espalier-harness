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
later verb cannot recognise. `python` is shown for brevity; try `python3` first
where `python` is not on the box.

**When to run it.** A session pushes each lane **once, at its end**: `/handoff`
writes its row, commits, and runs the `open` verb as its last step, so the
handoff's commit rides the same push as the work. Run `/ship` yourself before
the handoff only when the next lane needs this merge; `preflight` says what
that costs (the handoff's row then becomes a second push on the lane: a check
cycle restarted and a marker re-bound).

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
(`gh run view <id> --log-failed`) before arming another lane on top of it. Notes
when the newest `ESPALIER_MEMORY.md` row is not today's: the handoff has not
run this session.

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

Four shapes to recognise:

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
- **Conflicts with the base** -- `git fetch origin && git merge origin/<base>`,
  resolve, commit, push, `rebind`. Never a rebase of a pushed lane: a merge
  carries the same content without rewriting what was pushed.
- **Behind the base, nothing red, armed and waiting** -- a repository whose
  branch protection requires the pull request to be up to date with its base
  holds it here; GitHub's merge state reads `BEHIND` and the banner says so.
  Every merge to the base puts every other open pull request behind it, so of
  two lanes in flight the second to merge takes this step:

  ```bash
  python tools/cc/ship.py catch-up
  ```

  Merges the base in on the server (`gh pr update-branch`, GitHub CLI 2.53 or
  newer), waits for the head to move (the reply lands before the merge does),
  pulls fast-forward only (refuses on an unpushed commit: push it, run it
  again), proves HEAD is the pull request's head, then re-binds. If the server
  answers that nothing was behind, the hold is something else: read the checks.

```bash
python tools/cc/ship.py status
```

The pull request's state, merge state, auto-merge, and the required reds by
name -- parsed whatever `gh pr checks` exits with, since it exits 1 on a failed
check and 8 while one is pending, the two states worth reading.

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
