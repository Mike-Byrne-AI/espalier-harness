# INSTALL-CI — Enabling the Harness Guard guarantee layer

The Harness Guard workflow (`.github/workflows/harness-guard.yml`) is the only
Espalier-Harness enforcement layer with a real guarantee. The in-session hooks are
friction (they slow casual bypass) and visibility (they surface what slipped
past). This layer is the stop: no commit touching protected paths reaches
your default branch without the `HARNESS-UPDATE-APPROVED` marker.

The guarantee lives on GitHub's infrastructure, outside the agent's reach. It
requires one manual step — **enabling branch protection in the repository
settings** — which the installer deliberately does not automate. Automating
it would need an admin-scope GitHub token and hide the opt-in moment.

---

## 1. Install the workflow + guard script

> **Interpreter note.** The commands below spell `python`. A stock macOS ships only
> `python3` (and it is 3.9; Espalier requires 3.10+), while many Windows installs ship
> only `python`. Use whichever both resolves AND reports 3.10+
> (`<name> --version`); on a stock macOS `python3` resolves but is 3.9.
> `espalier doctor .` checks this for you.

```bash
python -m espalier.cli install-ci .
# or, installed:
espalier install-ci .
```

The installer writes:

- `.github/workflows/harness-guard.yml`
- `tools/cc/ci_guard.py`

The command exits `0` on success — including an idempotent re-run, where it
prints `unchanged:` for each file already in place. A zero exit means the
files are deployed, **not** that the gate is live: nothing can block a merge
until you complete the branch-protection step below, and no command can check
that for you.

### Which jobs run on your repo

The shipped `harness-guard.yml` defines six jobs — five checks plus an internal
`detect-source` plumbing job — but only one check is universal. `install-ci`
deploys the workflow + `tools/cc/ci_guard.py` — it does **not** deploy the
`espalier/` source tree or the `scripts/` helpers. So the three self-host-only
checks must skip on adopter repos.

The `detect-source` job computes that gate: it sets an output `is_source` —
**true only when `espalier/__init__.py` is present AND the `.espalier-fusion`
marker is absent** — and each self-host check gates on it with
`if: ${{ needs.detect-source.outputs.is_source == 'true' }}`, so they **skip
automatically on adopter repos**. The engine-presence clause skips plain
adopters (no `espalier/__init__.py`). The marker clause skips **fusions**
(`espalier fuse`), which *do* overlay the full `espalier/` tree but ship a
tracked `.espalier-fusion` marker — without it those self-host jobs would fire
on a fused repo's first PR. Only the Espalier source repo has the engine **and**
no marker, so only it runs all three.

`detect-source` exists as its own job because `hashFiles()` and file tests are
valid only in a **step** context — a job-level `if:` that calls `hashFiles()` is
rejected at workflow-parse time, creating zero jobs. The job computes the gate in
a step and exposes it as an output the `needs` context can read.

| Job | Runs on adopter repos? | Why |
|---|---|---|
| `verify` | **Yes** (universal) | Runs the deployed `ci_guard.py` — the branch-protected merge gate. This is the job branch protection requires. |
| `freshness` | No (self-host only) | Runs `espalier freshness` against the `espalier/` source tree (an editable install of this repository); an adopter repo carries no source tree, and the pip-installed CLI alone does not make it one. |
| `ruff-lint` | No (self-host only) | `ruff check .` lints the `espalier/` source tree, absent on adopter repos. |
| `mypy-hooks` | No (self-host only) | Type-checks the harness's own hook sources against the engine's source tree, absent on adopter repos. |
| `memory-tag-parity` | No (self-host only) | Runs `scripts/check_memory_md_tag_parity.py`, which `install-ci` does not deploy. |

When you enable branch protection (step 2), the status check to require is
**`verify`** — the job name, not the workflow name.

This distinction is the one that costs people an afternoon. `Harness Guard` is
the *workflow* (`name:` on line 1 of `harness-guard.yml`), and GitHub's
required-status-check picker lists **check runs**, which are named after the
**jobs**. None of this workflow's jobs sets a `name:`, so their check-run names
are their job ids: `verify`, `detect-source`, `freshness`, `ruff-lint`,
`mypy-hooks`, `memory-tag-parity`. Typing `Harness Guard` into the picker
finds nothing; adding it as a free-text entry wedges every PR on
*"Expected — waiting for status to be reported"*, because no check run will
ever report under that name.

The skipped self-host jobs report as neutral/skipped and do not block.

## 2. Enable branch protection in the GitHub UI

1. Go to `https://github.com/<owner>/<repo>/settings/branches`.
2. Click **Add rule** (or **Add branch protection rule**).
3. Set the rule:
   - **Branch name pattern**: your default branch (commonly `main`, or
     `master` on older repositories). A pattern matching no branch is
     accepted and protects nothing.
   - **Require a pull request before merging**: on
   - **Require approvals**: at least `1`
   - **Require status checks to pass before merging**: on
     - Add the status check named **`verify`** (the job, not the workflow —
       see the note above). If it does not appear in the search box yet, push
       one commit so the workflow reports at least once; GitHub only offers
       check names it has seen.
4. Save.

Until step 2 is complete, the workflow runs on every PR and push but **cannot
block merges**. It is advisory only.

## 3. Approving legitimate harness updates

Any commit touching one of these paths requires the marker
`HARNESS-UPDATE-APPROVED`. **Which channel carries it depends on the event,
and only one channel is read per event:**

| Event | Where the marker must be |
|---|---|
| `pull_request` (the normal case) | **the PR title**, bound to the head under review as `HARNESS-UPDATE-APPROVED@<sha>` — the commit message is not consulted |
| `push` (direct to a branch) | **the HEAD commit message** — there is no PR title to read |

This is not belt-and-braces: `_approval_marker_present` in `tools/cc/ci_guard.py`
allowlists by event, so amending a commit message on an open PR re-runs the
gate to exactly the same red.

On a pull request the marker **names the head it approves**: `<sha>` is at
least the first seven characters of the head commit the reviewer looked at
(`git rev-parse --short HEAD` on the branch; any case). A force-push after
approval changes the head, so the same title goes red and the gate prints
the exact fragment to paste for the new head — re-review, then re-bind the
title. Editing the title re-runs the check on the same head (the workflow
lists `edited` among its pull-request activity types for exactly this); a
new push moves the head and needs a new binding, so bind the title to the
head you are about to have reviewed, not one you are still changing. A bare
`HARNESS-UPDATE-APPROVED` in a PR title is refused for the same reason: it
would approve the pull request, not a commit. The binding is self-attested —
a pull-request author can edit their own title — so it is an audit trail
that forces an explicit, timeline-logged re-binding per head, not
independent evidence that a reviewer approved it: still re-review a
force-push. The head reaches the gate as `PR_HEAD_SHA`, which the deployed
workflow forwards from the pull-request event.

**Upgrading from a release before the binding.** `espalier install-ci`
rewrites `tools/cc/ci_guard.py` but never overwrites a workflow that differs
from its own: it writes `.github/workflows/harness-guard.yml.new` and warns.
Merge that over yours — the lines that matter are the `PR_HEAD_SHA` forward
in the env block of the `Check protected paths` step and `edited` in the
pull-request activity types — commit the script and the workflow together,
and re-title any open pull request that carries a bare marker. Until the
forward lands, every protected-path pull request fails closed, and the red
output prints the exact line to add.

The protected paths:

- `tools/cc/hooks/` — every hook script under it
- `.github/workflows/` — **every** workflow, not only `harness-guard.yml`
- `.espalier/integrity.json`
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.github/workflows/harness-guard.yml`
- `tools/cc/ci_guard.py`

### The one exemption: genuine Dependabot action bumps

`.github/workflows/` is protected, and Dependabot's `github-actions` ecosystem
opens a PR against it on a schedule — with a generated title like
`Bump actions/checkout from 4.2.1 to 4.2.2`, which carries no marker. Without an
exemption the guard would fail on **every** dependency PR, and you would end up
either retitling bot PRs forever or learning to ignore a red gate. The second is
the outcome this whole tool exists to prevent.

So a pull request is allowed without a marker when **all** of the following
hold — any one of them failing denies as normal:

1. the actor is exactly `dependabot[bot]`;
2. **every** changed path is a `.github/workflows/*.yml` file;
3. every changed line is a `uses:` ref whose action **identity** is unchanged —
   only the ref after `@` may move.

Condition 3 is why an action *swap* (`actions/checkout@sha` →
`someone-else/action@sha`) is still denied: both are well-formed `uses:` lines,
so a shape-only check would have allowed it. Your approval is then the merge
itself, plus whatever your `test` / `release` checks require.

This is a workflow speed-bump, not a security boundary: an attacker who can
forge `GITHUB_ACTOR` inside your CI has already won. Conditions 2 and 3 are
there to bound the allowance to the shape Dependabot actually produces.

**The kill-switch scan is not exempted.** It runs before any of this and the
marker never overrode it either.

### On a pull request: put the bound marker in the PR title

```
HARNESS-UPDATE-APPROVED@1a2b3c4: tighten write_guard bash patterns
```

where `1a2b3c4` is the head commit you reviewed. The gate's red output prints
the exact fragment for the head it sees, so the ceremony is a copy and paste.

### On a direct push: put the marker in the HEAD commit message

This channel is read on `push` events only. On a pull request the gate does
not look here.

```bash
git commit -m "$(cat <<'EOF'
HARNESS-UPDATE-APPROVED: tighten write_guard bash patterns

Extends the bash-write detector to cover tee/sed/cp/mv in-place edits.
EOF
)"
```

If the marker is missing and the change is legitimate, put it in the channel
your event reads — on a pull request `HARNESS-UPDATE-APPROVED@<sha>` in the
PR title for the head under review, on a push the marker in the HEAD commit
message. The workflow reruns on every push and on a title edit; a new push
moves the head, so bind the title after the last push.

## 4. Known limitations

- **Non-`main` default branch.** Mostly handled for you now. The workflow's
  push trigger lists both `main` and `master`, and the guard resolves its diff
  base from the repository's real default branch, which the workflow forwards as
  `DEFAULT_BRANCH`. Two things still need your attention if your default branch
  is named anything else: add it to `on.push.branches` in
  `.github/workflows/harness-guard.yml` (that block cannot be templated --
  GitHub does not evaluate expressions there, and an expression silently matches
  nothing), and set the branch-protection pattern to match.
  ⚠ Previously this note told you to edit `resolve_base` and said nothing about
  the push trigger -- which was the half that actually silenced enforcement.
- **Force-pushes to feature branches.** A force-push that rewrites the
  feature branch does not retrigger CI on GitHub until a new push event is
  emitted — but the merge is still blocked by branch protection because the
  required status check won't be green on the rewritten history.
- **Upstream `disableAllHooks` bypass.** A managed-settings-tier bypass
  (Anthropic issue #26637) can disable all hooks at a higher precedence than
  Espalier-Harness can reach. The CI layer still catches anything that reaches
  your default branch, which is the whole point of having an out-of-process
  gate.
- **Gitignored `.claude/settings.json` + `.espalier/integrity.json` (layered
  defense).** `espalier init` gitignores both paths on a repo that does not
  already track them (default `--write-gitignore`) — `.claude/settings.json`
  carries a machine-specific interpreter name, and `.espalier/` is per-install
  integrity state. So in a clean CI checkout these files are normally absent
  **by design**, and the marker-gated change check that lists them above is a
  force-add (`git add -f`) *backstop*, not the primary gate: the gitignore is
  the primary foreclosure and `config_guard` is the live deny. See
  `tools/cc/ci_guard.py` and the layered-defense note in `CLAUDE.md`.

  **Exception — a repo that already tracks `.claude/settings.json`.** Ignoring
  an already-tracked path protects nothing (git ignores `.gitignore` for files
  in the index), so `init` **withholds** that one entry rather than writing a
  line that would leave the file tracked *and* ignored — an invisible state
  `git check-ignore` does not even report without `--no-index`. It prints the
  `git rm --cached` remedy instead. Until the adopter runs it, there is no
  gitignore foreclosure for that path and **the CI scan is the primary gate**,
  not a backstop. `.espalier/` is unaffected: it is a directory entry covering
  an open set of future files, so `init` always writes it and simply discloses
  the consequence for anything already tracked underneath.

## 5. Recovering from a denied check

If the check is red:

1. Read the workflow's output — `ci_guard.py` lists the offending paths.
2. Decide: was the change legitimate?
   - **Yes, legitimate:** add the marker to the channel your event reads —
     on a pull request `HARNESS-UPDATE-APPROVED@<sha>` in the **PR title**,
     bound to the head under review (the failure output prints the exact
     fragment); on a push the marker in the **HEAD commit message**.
   - **No, accidental:** `git revert` or `git reset` the offending commit.
3. The check reruns on a title edit and on the next push to the PR. A push
   moves the head, so a title bound before it goes red again with the new
   fragment on screen.

## What `install-ci` adds to your repo

`espalier install-ci` deploys exactly one workflow —
`.github/workflows/harness-guard.yml` — plus its helper `tools/cc/ci_guard.py`.
It is a merge gate: `ci_guard.py` requires the `HARNESS-UPDATE-APPROVED` marker
before a change to a protected harness path can merge, so the local hook layer
can't be silently loosened on the way to your default branch.

That is the whole surface this command installs. To make it effective, add
`verify` — the job id, not the workflow name — as a required check in your
branch-protection rules.

It is independent of whatever test/build CI you already run: harness-guard
gates *harness integrity*, your own workflows gate *your code*, and both run
side by side.
