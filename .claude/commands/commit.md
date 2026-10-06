---
description: Review uncommitted changes, then stage and commit with a generated message.
---

Review uncommitted changes, then stage and commit with a generated message.

## Step 1: Overview
```bash
git status --short --untracked-files=all
git diff --stat
```

`git diff` lists modified tracked files only. The status lines are what show
an untracked file (`??`). A file this change did not make is someone's work in
progress, a parallel session's, or runtime state: it is not part of this
commit, and step 3 leaves it out by name.

## Step 2: Detailed review
```bash
git diff
```

An untracked file has no diff: read the file.

For each changed file:
1. **Summarize** the change in one sentence
2. **Risk check:**
   - Does it touch harness files (`tools/cc/`, `.claude/`, `espalier/`)?
     If yes, verify the change is intentional.
   - Does it touch files warned about in docs/SHARP_EDGES.md?
   - Does it introduce new dependencies or change existing ones?
3. **Convention check:** Does the change follow docs/CONVENTIONS.md?

## Step 3: Generate commit message
```
<type>(<scope>): <description>

<body — what changed and why>
```
Types: feat, fix, refactor, test, docs, chore, style
Scope: the module or area affected

The message is for a reader who has never seen this repository's working
vocabulary: a contributor, a future you bisecting a bug, a changelog tool.

- **Subject at most 72 characters**, imperative, no trailing period. Git tooling
  and GitHub truncate past 72, so the subject carries the whole headline alone.
- **No internal identifiers anywhere in the message** (a task-pack, ledger-row,
  review-round or workflow-run id): say what changed and why in plain words. The
  traceability lives in the pull request and in the record that lands the
  change, which points at the commit, never the other way round.
- **Body**: what changed, why, and how it was proved, wrapped at 72 columns;
  the trailer lines last.

On the Espalier-Harness source tree, step 4's landing check reds a subject past
72 or an internal id in the message.

**Beside the message, list the paths to commit.** Build the list from step 1:
every file that belongs to this change, one per line, whatever its status
(modified, deleted, renamed, added, untracked). A deleted file is on the list:
leaving it off ships the old file beside its replacement. Under the list, name
what you left out and why:

- a file this change did not make, modified or untracked;
- an **untracked** path under `cc/`, `.espalier/`, `.espalier-state/` or
  `reports/`, or `.claude/settings*`: runtime state the ignore rules should
  have caught. (A **tracked** file under `cc/`, such as the generated surface
  docs, is an ordinary file: it goes on the list when the change touched it.)
- a tracked file the harness rewrites while it runs. `cc/execution_plan.json`
  is the usual one: it should not be tracked at all, and
  `git rm --cached -- cc/execution_plan.json` retires it. Say so, and leave
  it out.
- any file you stop tracking but keep on disk (`git rm --cached`): a commit
  that names a path takes it as it is on disk, so naming it tracks it again.
  Land the untrack as a commit of its own, once `git diff --cached --name-only`
  lists nothing else.

Present the message and the path list, and wait for approval. The approval
covers the message and exactly the paths on the list, nothing from the
left-out section. To change the list, the user names the path to add or to
take off.

## Step 4: Commit

First, the **pre-commit provenance gate** — the ~1s CLI twin of the full-suite
`test_no_provenance_in_shipped_code`. It catches an internal build-history tag
(`TP-NNN`, `round-N`, `wf_…`) that slipped onto a shipping surface — e.g. a
`tools/cc/` comment that byte-mirrors into the shipped `espalier/_vendor/cc/` —
BEFORE the commit, not after (avoids the commit → full-suite-red → re-commit cycle):

```bash
python -m espalier provenance .
```

Exit 0 = clean, proceed. Exit 2 = offenders: strip the provenance wrapper (keep
the behavioral content) or add a load-bearing entry to `_ALLOWED_HITS` with a
reason, then re-run. Do NOT stage until it exits 0.

On any repo other than the Espalier-Harness source tree this census stands down
and prints why, exiting 0. That is expected, not a misconfiguration: it polices
Espalier's own internal build-history vocabulary (`TP-`, `TQ-`, `XPLAT-`), which
overlaps ordinary ticket prefixes, and its remedy lives in a constant inside the
installed engine that you cannot edit.

Stage and commit the approved list and nothing else, by explicit path on both
lines:

```bash
git status                     # a merge, a cherry-pick or a rebase in progress? stop and ask
git add -- <approved paths>
git commit -m "<approved message>" -- <approved paths>
```

Never `git add -A`, `git add --all` or `git add .`, and never
`git commit -a`: each takes files that were not on the list. The paths on the
commit line are what keep the commit to the list when the index already holds
something else. A change somebody staged before you started is theirs: it
stays staged and uncommitted, and you do not unstage it. If the first line
says a merge, a cherry-pick or a rebase is in progress, stop before the add
line and ask: git refuses a path-limited commit during a merge or a
cherry-pick, and whatever you stage meanwhile belongs to the operation
(`git merge --abort` deletes it from disk). Do not fall back to a broad
commit.

Report the commit hash. On the Espalier-Harness source tree, run the cheap
arms of the landing check now — trailer, message shape (subject at most 72,
no internal ids, over every unmerged commit on the branch), owed-list probes
and candidate keys, all sub-second — and skip its test slice:
```bash
if [ -f scripts/check_handoff_landing.py ]; then
  python scripts/check_handoff_landing.py --skip-tests
fi
```
If it reds on the message, amend now, before anything is pushed:
`git commit --amend --only -F <file>`, the file holding the whole corrected
message with its body and trailer lines (`--amend -m` replaces the whole
message and drops them; plain `git commit --amend --only` opens an editor,
which from a tool call is usually a no-op that keeps the old message). The
`--only` keeps the amend to this commit: a bare `--amend` takes everything
staged into it, the change you left staged above among them. A pushed message is
frozen; a subject nobody can change (a revert's generated one) is what
`--skip-shape` is for, with the reason said aloud.

The full landing check (its ~70 s test slice is session-scoped, not
commit-scoped — it re-runs the same growing set every time) belongs to
`/handoff` step 7c, once. Running the whole gate after each commit paid
that slice three times in one session (2026-09-06) for checks that take
under a second. An adopter repo has no `scripts/` and skips this.

## Step 5: Say how the commit reaches the default branch *(ask first — never automatic)*

After a clean commit, say how the lane leaves this machine, which depends on
one committed setting, `handoff_push` in `espalier.toml` (off unless the file
sets it to `true`):

- **On** (`handoff_push = true`): the lane ships **once, at `/handoff`**. The handoff writes its row,
  commits, and runs the ship driver as its last step, so this commit and the
  handoff's ride one push, one pull request, one check cycle. Offer `/ship` now
  only when the next lane needs this merge before the session ends, and name the
  cost: the handoff's row then becomes a second push on the lane (the checks
  restart and the marker is re-bound) or its own pull request.
- **Off** (absent or `false`): `/handoff` pushes nothing, so `/ship` is how this lane is pushed,
  whenever the operator chooses. Offer it; do not say the handoff will push.
Never offer to ship a commit the landing check redded. `/ship` moves the
commits onto a lane branch when you are on the default branch, pushes, opens the
pull request with the approval marker bound at creation when the diff needs one,
and arms auto-merge — you never type a branch name.

Only proceed on the user's explicit yes (global rule: commit or push only
when asked). If the user declines, stop here — nothing is pushed.

---

Session work done? Run `/handoff` to persist reasoning + the MEMORY row
before you close.
