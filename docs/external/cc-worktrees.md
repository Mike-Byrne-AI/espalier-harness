---
source_url: https://code.claude.com/docs/en/worktrees.md
fetch_note: |
  The `.md` suffix is LOAD-BEARING, for the reason recorded on
  cc-hook-protocol.md: without it the origin serves the rendered page and the
  refresher stores the HTML verbatim. The "cwd follows Claude" sentences are
  printed on TWO upstream pages; this pin's `source_url` is the worktrees page,
  and the hooks page's copy is quoted below with its own URL for the human
  reviewer. No refresh re-verifies that copy: the refresher diffs each pin
  against its own `source_url` only, and cc-hook-protocol.md's excerpt does
  not carry these sentences. Re-read it by hand when that pin refreshes.
mirrors:
  - https://code.claude.com/docs/en/worktrees
fetched: 2026-09-09
section: "Hook paths don't follow the worktree; Clean up subagent and background session worktrees; Use worktrees with -p"
section_anchor: "clean-up-subagent-and-background-session-worktrees"
content_hash: ""
refresh_policy: weekly
purpose: |
  Verification target for the SessionStart nested-repo-litter reporter
  (`tools/cc/hooks/session_start.py::_find_nested_repo_litter` and
  `::_warn_if_nested_repo_litter`): which directory a hook may treat as the
  one Claude is working in when the session has entered a worktree, and when
  a registered worktree carries a lock Claude Code set for a running agent or
  backgrounded session rather than a leftover a person should remove.
---

# Claude Code Worktrees — Pinned Excerpt

**Source:** https://code.claude.com/docs/en/worktrees (fetched as the `.md` twin)
**Fetched:** 2026-09-09
**Section:** "Hook paths don't follow the worktree", "Clean up subagent and background session worktrees", "Use worktrees with -p"
**Purpose:** Verification target for the SessionStart nested-repo-litter reporter — the worktree the session is using and the worktree Claude Code holds a lock on are not litter.

---

## The hook's `cwd` follows Claude into the worktree; `CLAUDE_PROJECT_DIR` stays put

The worktrees page:

> **Hook paths don't follow the worktree.** After Claude enters a worktree,
> Claude Code keeps `${CLAUDE_PROJECT_DIR}` in your hooks where it was and
> passes the worktree path to them a different way:
>
> * **`${CLAUDE_PROJECT_DIR}` stays put**: it still points at the project root
>   where the session started, so a hook command such as
>   `${CLAUDE_PROJECT_DIR}/.claude/hooks/check-style.sh` still runs the script
>   in the main checkout.
> * **`cwd` follows Claude**: the `cwd` field in the hook's input JSON is the
>   worktree root, and it moves again when Claude runs `cd`. Read it when a
>   hook needs the worktree path.

The hooks page (https://code.claude.com/docs/en/hooks.md, the page
cc-hook-protocol.md pins; read 2026-09-09) prints the same rule under
"Reference scripts by path":

> **Worktrees are different.** If Claude enters a worktree during the session,
> Claude Code keeps `${CLAUDE_PROJECT_DIR}` where it was and passes the
> worktree path to your hooks a different way:
>
> * **`${CLAUDE_PROJECT_DIR}` stays put**: it still points at the project root
>   where the session started, so a command such as
>   `${CLAUDE_PROJECT_DIR}/.claude/hooks/check-style.sh` still runs the script
>   in the main checkout.
> * **`cwd` follows Claude**: the `cwd` field in the hook's input JSON is the
>   worktree root after Claude enters a worktree, and the new directory after
>   Claude runs `cd`. Read it when a hook needs to know which directory Claude
>   is working in.

and lists `cwd` among the fields every hook input carries ("Common input
fields"):

> `cwd` — Current working directory when the hook is invoked

So a SessionStart hook launched for a worktree session resolves its project
root from `CLAUDE_PROJECT_DIR` (the main checkout) while the payload's `cwd`
names the worktree: a nested-repo scan rooted at the project root will find the
very worktree the session is running in unless it reads `cwd`.

## Claude Code holds a `git worktree lock` while it uses a worktree

> While an agent is running, Claude Code holds a `git worktree lock` on its
> worktree so that concurrent cleanup can't remove it, and releases the lock
> when the agent finishes. Claude Code holds the same lock on the worktree it
> created for a backgrounded session while the session runs, so the sweep
> leaves the worktree in place and `git worktree remove` refuses to remove it.

## A lock can outlive its session (the stale-lock window)

> The sweep also releases a lock Claude Code set for a session whose process
> has exited, so a killed background session doesn't leave its worktree
> permanently locked. The sweep never releases a lock you set yourself with
> `git worktree lock`. Before v2.1.210, a lock left by a killed session stayed
> in place until you ran `git worktree unlock`.

> Non-interactive runs with `-p` have no exit prompt, so Claude doesn't clean
> up their worktrees, and Claude Code leaves the lock it took on each one at
> creation in place until a later session's stale-lock sweep releases it. To
> remove one, run `git worktree remove`; if git refuses because the worktree
> is locked, run `git worktree unlock` on it first.

The page does not say when in a session the stale-lock sweep runs relative to
the SessionStart hook. Between a session's death and the sweep, a leftover
worktree can still carry Claude Code's lock; espalier treats a locked worktree
as in use for that window rather than guessing.

## git refuses to remove a locked worktree

> To clean up a worktree that the sweep keeps, run `git worktree remove`,
> adding `--force` if the worktree has uncommitted changes or untracked files.
> If git refuses because the worktree is locked, run `git worktree unlock` on
> it first.

**Observed, not quoted** (git 2.39.5, Apple Git-154, driven 2026-09-09):
`git worktree list --porcelain` prints a `locked` line in a locked worktree's
block — bare `locked` when no reason was given, `locked <reason>` otherwise —
and `git worktree remove --force` on a locked worktree exits 128 with
`fatal: cannot remove a locked working tree`. The reporter's remedy line names
`git worktree remove --force <path>`, so a locked worktree is never a tree that
remedy applies to.

**Not asserted:** the page also says Claude Code "writes a marker into the git
metadata of every worktree it creates with git" and that the sweep keeps any
worktree without one. The marker's form is not documented, so espalier does not
read it; the lock and the `cwd` are the two documented signals.

---

## What espalier asserts against this excerpt

- `tools/cc/hooks/session_start.py::_find_nested_repo_litter` skips a
  registered worktree, or an untracked nested clone, that contains the hook's
  `cwd`, and skips any registered worktree whose `git worktree list
  --porcelain` block carries a `locked` line -- any lock, Claude Code's or one
  set by hand, since git prints the same line for both and a lock set by hand
  is the one the sweep never releases (an untracked candidate that resolves to
  a locked worktree is skipped by the same rule). Every other nested repo is
  still reported. Identity is by inode (`samefile`), so a case-variant
  spelling of the root or of `cwd` on a case-insensitive filesystem cannot
  lose a skip.
- `tools/cc/hooks/session_start.py::_hook_cwd` reads `cwd` from the hook
  input (absolute only, as upstream documents it); when the payload has none
  the finder falls back to the process's working directory.
- `tools/cc/hooks/session_start.py::_warn_if_nested_repo_litter` prints one
  INFO line naming the nested repo `cwd` sits in
  (`::_nested_repo_containing`, a pure filesystem walk), in place of the WARN:
  a registered worktree of this repository is named as one
  (`::_is_registered_worktree`, over `_hook_utils.sibling_checkouts`), and a
  foreign nested repo keeps the clause that the path guards and plan checks do
  not govern writes made inside it. The clause used to cover a worktree too,
  while the guards were keyed to `CLAUDE_PROJECT_DIR` alone; since DEF-743
  every normaliser relativises a target against the checkout containing it,
  read from git's own worktree registry (`<common>/worktrees/<id>/gitdir`)
  rather than from this page's `cwd`, so the guards govern a worktree like
  the root and this pin is not their verification target.
- `tests/test_nested_repo_litter.py::TestWorktreeInUseIsNotLitter` — the
  function-level cases for both candidate sources (the excluded shape only the
  worktree list sees, and the untracked shape the descent sees), the payload
  read and its fallback, and a subprocess drive of the whole hook with
  `CLAUDE_PROJECT_DIR` at the project root and the payload's `cwd` inside the
  worktree.
