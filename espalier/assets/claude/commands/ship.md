Push the lane you just committed as a pull request with auto-merge armed and the approval marker bound to its final head; `--release vX.Y.Z` then tags the merge commit and creates the release.

## Usage

```
/ship                      — the unmerged commits on this branch, as one pull request
/ship --release vX.Y.Z     — the same, then the tag on the merge commit and the GitHub release
```

You never type a branch name. Commit where you are — the default branch or a
lane branch — and `/ship` puts the commits where the pull-request flow needs
them. Every block below stands alone (it derives what it uses), because a tool
shell forgets variables between calls; `set -u` makes an unset name a stop,
and the `:?` checks make an EMPTY one a stop too, since a failed command
substitution leaves a variable set and empty, which `set -u` does not catch.
Both stop a script and the tool shell; a terminal you paste into prints the
message and carries on, so read what it says before the next line runs.

## Step 0: What is there to ship?

```bash
set -u
BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name); : "${BASE:?gh could not name the default branch: sign in (gh auth status) or fix the remote}"
git fetch origin --quiet
git status --short -uno                     # tracked changes only; must print nothing: /ship moves commits, never a dirty tree
git log --oneline "origin/$BASE..HEAD"      # the commits the pull request will carry
```

Stop if the tree is dirty (`/commit` first) or the range is empty (nothing to
ship). An untracked scratch file does not block a push and does not count.

## Step 1: Put the commits on a lane branch

The block decides for itself: it moves commits only when HEAD is the default
branch, and prints why it did nothing otherwise. On the default branch the
unmerged commits sit on your local copy of it, and a protected default branch
will not take them by push, so they move to a lane named from the head
commit's subject:

```bash
set -u
BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name); : "${BASE:?gh could not name the default branch}"
[ "$(git branch --show-current)" = "$BASE" ] || { echo "HEAD is not $BASE (a lane already, or detached): nothing to move -- on a lane go to step 2, on a detached HEAD stop"; exit 0; }
LANE="lane/$(git log -1 --format=%s | tr -cs 'A-Za-z0-9' '[-*]' | tr 'A-Z' 'a-z' | cut -c1-48 | sed 's/-*$//')"
git branch "$LANE" && git switch "$LANE" && git branch -f "$BASE" "origin/$BASE"
git log --oneline "origin/$BASE..HEAD"      # the same commits, now on the lane; local $BASE is back at origin
```

Nothing is lost by the last command of the chain, because the guard above
only lets it run when HEAD IS the local default branch's tip: the lane is
created at that tip first, so every commit the default branch carried is
reachable from the lane before the default branch is pointed back at origin.
(Run from a third branch, the same chain would discard commits sitting on the
default branch, which is why the guard is mechanical and not a sentence.) If
the slug comes out empty or the name already exists, the chain stops at its
first command — pick another subject-derived name by hand, and say so.

## Step 2: Push the lane and open the pull request

```bash
git push -u origin HEAD
```

Then open the pull request. The title is the head commit's subject when the
lane is one commit, else one line (at most 72 characters) naming the lane; the
body is what a reviewer who has never seen this session needs — what changed,
why, and how it was proved, drawing the why from the blueprint's
`reasoning_entries` (`kind=decision|alternative|pattern|insight`) — followed
by the commits. The prose goes through a QUOTED heredoc, so a backtick or a
`$` in it is written into the body, never run by the shell:

```bash
set -u
BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name); : "${BASE:?gh could not name the default branch}"
{ cat <<'EOF'
<two or three lines: what changed, why, how it was proved>
EOF
  echo
  git log --format='- %s' "origin/$BASE..HEAD"
} | gh pr create --base "$BASE" --title '<subject, at most 72 characters>' --body-file -
```

`gh pr create` prints the URL; carry it into the handoff's `Next:` line.

## Step 3: Bind the approval marker, when the diff needs one *(a repository whose CI runs the harness guard — the Espalier-Harness source tree is one)*

The harness-guard workflow fails the merge of a pull request that touches a
path the guard protects unless the pull request **title** carries
`HARNESS-UPDATE-APPROVED@<head7>`, bound to the head under review (a seven-plus
hex prefix of the commit the checks ran on). A marker in a commit message is
refused on a pull request by design; the title is the only channel. Ask the
guard's own predicate whether this diff needs it — never a list kept in this
file, which would age the moment the guard's roster moved. The check reads
the guard from the repository root, not from wherever the shell happens to
be, and it prints one of three verdicts:

```bash
set -u
BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name); : "${BASE:?gh could not name the default branch}"
ROOT=$(git rev-parse --show-toplevel); : "${ROOT:?not inside a git checkout}"
git diff --name-only "origin/$BASE...HEAD" | python -c '
import pathlib, sys
root = pathlib.Path(sys.argv[1])
if not (root / "tools" / "cc" / "ci_guard.py").is_file():
    print("MARKER NOT REQUIRED: no harness guard on this tree"); raise SystemExit(0)
sys.path.insert(0, str(root / "tools" / "cc"))
import ci_guard
paths = [line.strip() for line in sys.stdin if line.strip()]
if not paths:
    print("CHECK DID NOT RUN: the diff listed no paths (a failed git diff above?) -- bind the marker"); raise SystemExit(1)
hit = [p for p in paths if ci_guard.is_protected(p)]
print("MARKER REQUIRED: " + ", ".join(hit) if hit else "MARKER NOT REQUIRED: no protected path in the diff")
' "$ROOT"
```

The program rides `-c`, not a heredoc: the paths arrive on stdin through the
pipe, and a heredoc on the same command would either replace them (bash) or be
concatenated with them (zsh, whose multios feeds both), which is how the first
drive of this block parsed a path list as Python.

`MARKER REQUIRED` — bind it. `MARKER NOT REQUIRED` — go to step 4. Anything
else, including no verdict at all (the interpreter was not found, the diff
failed) — the check did not run, so bind the marker; a marker nobody needed
costs nothing, a missing one stalls the merge. Bind it to the head you just
pushed, and only now, after the last push; the pull request is named from
the branch you are on, and the block stops if that branch has none:

```bash
set -u
BR=$(git branch --show-current); : "${BR:?detached HEAD: switch to the lane}"
PR=$(gh pr list --head "$BR" --state all --limit 1 --json number -q '.[0].number'); : "${PR:?no pull request for this branch: run step 2, or switch to the lane}"
gh pr edit "$PR" --title "$(gh pr view "$PR" --json title -q .title) HARNESS-UPDATE-APPROVED@$(git rev-parse --short=7 HEAD)"
```

⚠ **A push after the binding restales it.** The head moves, the `verify`
check reds on the old fragment, and an armed auto-merge sits silently,
unmerged, with nothing in front of you saying so — that stall is the reason
this command exists. If you push again, re-bind (step 5).

## Step 4: Arm auto-merge and keep working

```bash
set -u
BR=$(git branch --show-current); : "${BR:?detached HEAD: switch to the lane}"
PR=$(gh pr list --head "$BR" --state all --limit 1 --json number -q '.[0].number'); : "${PR:?no pull request for this branch}"
gh pr merge "$PR" --auto --merge
```

The pull request merges on its own when every required check is green
(auto-merge is a repository setting; if `gh` says it is not allowed, merge by
hand once the checks are green). Go back to work. The next SessionStart banner
carries an `Open PRs:` line naming this pull request with its check tally and
whether auto-merge is armed; once it has merged, a `Merged:` line says so
until your local default branch has it:

```bash
set -u
BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name); : "${BASE:?gh could not name the default branch}"
git switch "$BASE" && git pull --ff-only origin "$BASE"
```

Start the next lane from there. An independent lane can start while this one
is still open (its pull request shows only its own commits); a lane that
builds on this one waits for the merge. Every later block names the pull
request from the branch it runs on, so to touch this one again, switch back
to its lane first.

## Step 5: When a check goes red, the head moves, or the lane falls behind

Fix on the lane, commit, push — the head moved, so if step 3 bound a marker,
re-bind it by replacing the old fragment (auto-merge stays armed and fires
when the checks are green):

```bash
set -u
BR=$(git branch --show-current); : "${BR:?detached HEAD: switch to the lane}"
PR=$(gh pr list --head "$BR" --state all --limit 1 --json number -q '.[0].number'); : "${PR:?no pull request for this branch: switch to the lane}"
gh pr edit "$PR" --title "$(gh pr view "$PR" --json title -q .title | sed -E 's/ *HARNESS-UPDATE-APPROVED@[0-9a-fA-F]+//') HARNESS-UPDATE-APPROVED@$(git rev-parse --short=7 HEAD)"
```

Four shapes to recognise:

- **`verify` red alone, its message naming two heads** — the marker is stale:
  you pushed after binding. Re-bind; nothing else is wrong.
- **A test cell red** — read its log (`gh run view --log-failed`), fix, commit,
  push, re-bind.
- **Conflicts with the base** — merge the base in, resolve, commit, push,
  re-bind. Never rebase a pushed lane: the force push it needs is its own
  checkpoint, and a merge carries the same content.

  ```bash
  set -u
  BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name); : "${BASE:?gh could not name the default branch}"
  git fetch origin && git merge "origin/$BASE"
  ```

- **Behind the base, nothing red, auto-merge armed and waiting** — a
  repository whose branch protection requires a pull request to be up to date
  with its base before it merges holds it here: GitHub's merge state reads
  `BEHIND`, and the SessionStart banner's `Open PRs:` line says `behind` your
  base (the Espalier-Harness source tree has that rule on). Every merge to the
  base puts every other open pull request behind it, so under the rule, of two
  lanes in flight the second to merge takes this step. Catch the lane up on
  the server, wait for the head to move (the reply comes back before the merge
  lands), then pull, so the re-bind reads the head the checks now run on —
  the merge commit GitHub made, not the commit you last pushed. The block
  stops when the pull cannot fast-forward (an unpushed commit on the lane:
  push it, the head moves anyway) and when HEAD is still not the pull
  request's head. Never rebase a pushed lane here either. `gh pr update-branch`
  arrived in GitHub CLI 2.53 (July 2024): an `unknown command` reply means an
  older gh.

  ```bash
  set -u
  BR=$(git branch --show-current); : "${BR:?detached HEAD: switch to the lane}"
  PR=$(gh pr list --head "$BR" --state all --limit 1 --json number -q '.[0].number'); : "${PR:?no pull request for this branch: switch to the lane}"
  WAS=$(gh pr view "$PR" --json headRefOid -q .headRefOid); : "${WAS:?gh could not read the head of the pull request}"
  gh pr update-branch "$PR" || exit 1                 # merges the base into the lane on the server, never a rebase
  for _ in $(seq 1 15); do [ "$(gh pr view "$PR" --json headRefOid -q .headRefOid)" != "$WAS" ] && break; sleep 2; done
  git pull --ff-only origin "$BR" || exit 1           # cannot fast-forward = an unpushed commit here: push it, then run this block again
  [ "$(git rev-parse HEAD)" = "$(gh pr view "$PR" --json headRefOid -q .headRefOid)" ] || { echo "HEAD is not the pull request's head yet: wait a moment, then run this block again"; exit 1; }
  ```

  Then, if step 3 bound a marker, the re-bind block at the top of this step:
  the guard runs twice — red when the head moved under the old fragment,
  green when the title changed. Every other check re-runs on the new head,
  so the merge is one check cycle away. If `update-branch` answered
  `already up-to-date`, nothing was behind: the hold is something else, read
  the checks.

## `--release vX.Y.Z`: tag the merge commit and create the release *(after the merge)*

Precondition: the lane carried the release fold — the version surfaces, the
changelog fold, the freshness re-pin (on the Espalier-Harness source tree, the
release checklist's steps 1 to 3). Wait for the merge, then tag the merge
commit as it sits on origin — no branch switch, and never a tag on the lane
commit before the merge: the publish workflow fires on any `v*` tag push with
no on-default-branch check, and a package-index upload is immutable. Stay on
the lane branch: the pull request is named from it.

```bash
set -u
BR=$(git branch --show-current); : "${BR:?detached HEAD: switch to the lane}"
PR=$(gh pr list --head "$BR" --state all --limit 1 --json number -q '.[0].number'); : "${PR:?no pull request for this branch: switch to the lane}"
gh pr view "$PR" --json state,mergeCommit -q '.state + " " + .mergeCommit.oid'
```

Only when that prints `MERGED <sha>`. The tag is written ONCE, at the top of
the block, and checked against the version the tree carries before anything
leaves the machine — so an unsubstituted placeholder stops here instead of
pushing a tag named after itself (which the release speed bump would not
catch: it looks for a digit after the `v`):

```bash
set -u
TAG=vX.Y.Z                                          # the version you passed to --release, once
VERSION=$(python -c "import re, pathlib; print(re.search(r'^version\s*=\s*\"([^\"]+)\"', pathlib.Path('pyproject.toml').read_text(encoding='utf-8'), re.M).group(1))"); : "${VERSION:?could not read the version of the tree}"
[ "$TAG" = "v$VERSION" ] || { echo "tag $TAG is not the tree's version v$VERSION: stop"; exit 1; }
BR=$(git branch --show-current); : "${BR:?detached HEAD: switch to the lane}"
PR=$(gh pr list --head "$BR" --state all --limit 1 --json number -q '.[0].number'); : "${PR:?no pull request for this branch}"
git fetch origin
MERGE=$(gh pr view "$PR" --json mergeCommit -q .mergeCommit.oid); : "${MERGE:?the pull request has no merge commit yet}"
git tag -a "$TAG" -m "$TAG: <one line>" "$MERGE"
git push origin "$TAG"                              # this one tag, by name
git ls-remote --tags origin | grep "$TAG"           # the SHA, on origin
gh release create "$TAG" --notes-from-tag
gh run watch "$(gh run list --limit 1 --json databaseId -q '.[0].databaseId')"   # the run the tag push just started; if the list shows another first, name that id
```

On a tree whose version lives somewhere other than `pyproject.toml`, read it
from there; the comparison is the point. Never a bulk tag push here: pushing
more than three tags at once creates no tag events, the publish workflow
never fires, and the release silently does not publish — name the one tag.
The release speed bump stops the tag push and the release create once each;
re-issue the same command verbatim. The publish workflow then parks on its
environment's required reviewer: that approval is the operator's click in the
browser, by design — do not grant it from the command line. Verify the
publish from the package index, not from the release page; on the
Espalier-Harness source tree the release checklist's last step says how.

---

On the Espalier-Harness source tree the branch protection requires the pull
request and its required checks; the `test (3.x)` cells run the tier the diff
earns (`scripts/proof_tier.py --base`, the same rule as the local run), 9 to
40 minutes measured in September 2026. Session work done? `/handoff` persists
the reasoning and the memory row — and its own commit ships the same way.
