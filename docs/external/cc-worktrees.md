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
fetched: 2026-09-28
section: "Ask Claude to create a worktree (the 'Hook paths don't follow the worktree' note); Clean up worktrees; Clean up subagent and background-session worktrees"
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
**Fetched:** 2026-09-28
**Section:** "Ask Claude to create a worktree" (the "Hook paths don't follow
the worktree" note), "Clean up worktrees", "Clean up subagent and
background-session worktrees"
**Purpose:** Verification target for the SessionStart nested-repo-litter reporter — the worktree the session is using and the worktree Claude Code holds a lock on are not litter.

<!-- re-excerpt 2026-10-01: `section:` restructured upstream, not contradicted.
     The "Hook paths don't follow the worktree" rule is no longer a section of
     its own -- it is a `<Note>` block inside "### Ask Claude to create a
     worktree", with its text UNCHANGED word for word. "Use worktrees with -p"
     is gone as a heading: its two sentences (no exit prompt, the lock left in
     place until a later sweep) now sit at the end of "## Clean up worktrees"
     and are quoted below from there, also unchanged. The section's own name
     gained a hyphen ("background session" -> "background-session"); the
     anchor `#clean-up-subagent-and-background-session-worktrees` is still the
     live one, so `section_anchor` is unchanged. -->

---

## The hook's `cwd` follows Claude into the worktree; `CLAUDE_PROJECT_DIR` stays put

The worktrees page (in the `<Note>` under "Ask Claude to create a worktree"):

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
cc-hook-protocol.md pins; read 2026-09-09, re-verified word for word
2026-09-28 against that page's candidate from the same fetch) prints the same
rule under "Reference scripts by path":

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

## Where Claude Code's own worktrees live

> By default, the worktree is created under `.claude/worktrees/<name>/` at your
> repository root, on a new branch named `worktree-<name>`

<!-- re-excerpt 2026-10-01: NEW to this excerpt (quoted from "Start Claude in a
     worktree"). It names the default directory the reporter's descent walks
     into, and the `<Tip>` beside it tells the operator to gitignore it -- i.e.
     the common shape is an IGNORED nested checkout, which is why the finder
     has to see both candidate sources. Not a new assertion; context the pin
     was missing. -->

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

From "Clean up worktrees" (the sentences that used to carry their own
"Use worktrees with -p" heading):

> Non-interactive runs with `-p` have no exit prompt, so Claude doesn't clean
> up their worktrees, and Claude Code leaves the lock it took on each one at
> creation in place until a later session's stale-lock sweep releases it. To
> remove one, run `git worktree remove`; if git refuses because the worktree
> is locked, run `git worktree unlock` on it first.

The page still does not say when in a session the stale-lock sweep runs
relative to the SessionStart hook. It now says the sweep is *periodic* and
age-gated:

> Claude Code runs a periodic sweep that removes worktrees that Claude created
> for subagents and background sessions once they are older than your
> `cleanupPeriodDays` setting, following the retention sweep rules.

<!-- re-excerpt 2026-10-01: the "does not say when the sweep runs" sentence is
     still true but is now QUALIFIABLE: upstream names the sweep's cadence
     (periodic) and its gate (`cleanupPeriodDays`), neither of which was in the
     2026-09-09 excerpt. Nothing here pins the sweep to a session event, so the
     conclusion below is unchanged. -->

Between a session's death and the sweep, a leftover worktree can still carry
Claude Code's lock; espalier treats a locked worktree as in use for that window
rather than guessing. The age gate widens that window rather than closing it:
a lock Claude Code set is released by the sweep, and the sweep does not look at
the worktree until it is older than `cleanupPeriodDays`.

## What the sweep leaves in place

> When you background a `--worktree` session, its worktree becomes a
> background-session worktree that the sweep can remove. The sweep leaves a
> worktree in place in these cases:
>
> * The worktree still holds work: changed or untracked files, or unpushed
>   commits.
> * A checked-out submodule in the worktree holds changed or untracked files,
>   or Claude Code can't inspect the worktree's submodules. This check requires
>   Claude Code v2.1.274 or later.
> * One of the four cases that also block worktree creation applies: Claude
>   Code can't determine which filter drivers the repository config defines, or
>   finds a setting there it can't switch off.
> * The worktree belongs to a `--worktree` session you haven't backgrounded,
>   whatever its age.
> * You created the worktree yourself with `git worktree add`, even if you then
>   ran a `--worktree <name>` session in it and backgrounded that session.

> Each subagent gets a temporary worktree that Claude Code removes
> automatically when the subagent finishes without changes; a worktree with
> changes stays on disk until the periodic sweep below can remove it without
> losing work.

<!-- re-excerpt 2026-10-01: NEW section in this excerpt, inside the pin's own
     named section. It is the direct answer to the reporter's question and it
     CUTS AGAINST reading a lock as the only in-use signal: a dirty subagent
     worktree survives on disk with NO lock once the subagent finishes, so a
     registered worktree with uncommitted work is a legitimate on-disk resident
     the sweep is deliberately preserving, not litter a person forgot. espalier
     reports it today (only `cwd`-containment and a `locked` line skip), which
     is a reporter-only INFO/WARN and not a guard decision -- recorded here as
     the newly-documented shape, not as a defect this pin asserts away. -->

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
worktree without one — now extended to say so explicitly for a worktree a
`WorktreeCreate` hook created, and that "Before v2.1.246, the sweep didn't
check for the marker". The marker's form is still not documented, so espalier
does not read it; the lock and the `cwd` are the two documented signals.

**Not asserted (new upstream section):** the page now carries
"How Claude Code enforces isolation" — four checks (file edits, command
working directory, git redirects, command shape) by which Claude Code itself
blocks a worktree-isolated session from touching the main checkout, and which
"covers every subagent Claude spawns from the isolated session". That is Claude
Code's own enforcement, not the hook input's shape, so it is outside this pin's
`purpose` and nothing here asserts against it. It is named so the next reader
sees it exists; widening this pin (or opening one of its own) is a scope
decision, not a refresh.

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
