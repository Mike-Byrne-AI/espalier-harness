---
source_url: https://code.claude.com/docs/en/troubleshoot-install.md
fetch_note: |
  The `.md` suffix is LOAD-BEARING, for the reason recorded on
  cc-hook-protocol.md: without it the origin serves the rendered page and the
  refresher stores the HTML verbatim. The lookup is stated on the
  troubleshoot-install page; the variable's own row is on the env-vars page and
  the settings-file remedy on the setup page, both listed under
  `quote_sources`, so every quoted passage is checked against all three.
mirrors:
  - https://code.claude.com/docs/en/troubleshoot-install
quote_sources:
  - https://code.claude.com/docs/en/env-vars.md
  - https://code.claude.com/docs/en/setup.md
fetched: 2026-10-31
section: "Claude Code on Windows requires either Git for Windows (for bash) or PowerShell (troubleshoot-install); the CLAUDE_CODE_GIT_BASH_PATH row and Set variables in settings files (env-vars); Install on native Windows (setup)"
section_anchor: "claude-code-on-windows-requires-either-git-for-windows-for-bash-or-powershell"
content_hash: ""
refresh_policy: weekly
purpose: |
  Verification target for `espalier/_venv.py::git_bash_path`, espalier's copy
  of the lookup by which Claude Code on Windows finds Git Bash, which `doctor`
  reads to name a statusLine an older `init` wrote for the shell this host
  does not run (`espalier/doctor.py::statusline_shell_mismatch`).
---

# Claude Code's Git Bash Lookup — Pinned Excerpt

**Source:** https://code.claude.com/docs/en/troubleshoot-install (fetched as the `.md` twin), with https://code.claude.com/docs/en/env-vars and https://code.claude.com/docs/en/setup
**Fetched:** 2026-10-31
**Section:** "Claude Code on Windows requires either Git for Windows (for bash) or
PowerShell" (troubleshoot-install); the `CLAUDE_CODE_GIT_BASH_PATH` row and "Set
variables in settings files" (env-vars); "Install on native Windows" (setup)
**Purpose:** Verification target for espalier's copy of the Git Bash lookup, the one `doctor` reads to judge a legacy Windows statusLine.

## Why this is pinned

The status line page (the `cc-statusline` pin) says Claude Code runs a status
line command "through Git Bash when Git Bash is installed, or through
PowerShell when Git Bash is absent". Until this pin, espalier's copy of the
lookup quoted here rested on one read of
the 2.1.316 binary (that pin's "Observed, not quoted" paragraph), and the weekly
refresh re-read nothing that stated it. The pages state the lookup for Git Bash
as a whole: for the Bash tool, and for the error when neither shell is found.
That the status line's choice of shell runs through the same lookup is the
binary read's finding, not a quote.

## The lookup

From "Claude Code on Windows requires either Git for Windows (for bash) or
PowerShell":

> Git for Windows is optional. Claude Code uses the PowerShell tool when Git
> Bash is absent, so this error means neither shell was found.

> **If Git is already installed** but Claude Code can't find it, compare its
> location against the places Claude Code checks. When
> `CLAUDE_CODE_GIT_BASH_PATH` isn't set, Claude Code looks for `bash.exe` in
> this order:
>
> 1. The default install locations `C:\Program Files\Git` and `C:\Program Files (x86)\Git`.
>
> 2. The `git` on your `PATH`, using the `bin\bash.exe` from that Git
> installation.

## A `git` the project placed is skipped

> In step 2, Claude Code skips a `git` that sits in the folder you launched
> Claude Code from, or below it in a path that contains `node_modules` or a
> virtual-environment folder such as `.venv` or `env`, for example
> `C:\dev\env\myproject\Git` when you launched from `C:\dev\env\myproject`.
> This keeps Claude Code from running an executable that a project placed
> there. If your Git is in a location like that, point
> `CLAUDE_CODE_GIT_BASH_PATH` at it.

## The variable, and the file names it accepts

> **To point Claude Code at a specific Git installation**, find it by running
> `where.exe git` in PowerShell, then set the `bin\bash.exe` path from that
> installation as `CLAUDE_CODE_GIT_BASH_PATH` in your settings.json file:

> **If `CLAUDE_CODE_GIT_BASH_PATH` is set to the correct path and the file
> exists** but Claude Code still doesn't use it, check the file's name first.
> Claude Code accepts only a file named `bash.exe`, `sh.exe`, `bash`, or `sh`;
> with any other name, such as Git for Windows' `git-bash.exe` launcher, it
> ignores the variable and auto-detects Git Bash as if it were unset, logging a
> warning visible with `--debug`. A path that doesn't exist gets the same
> fallback and warning. Before v2.1.219, Claude Code used any existing file as
> the shell without checking its name, and exited at startup with `Claude Code
> was unable to find CLAUDE_CODE_GIT_BASH_PATH path` when the path didn't
> exist.

The env-vars page, the variable's row:

> `CLAUDE_CODE_GIT_BASH_PATH` — Windows only: path to the Git Bash executable
> (`bash.exe`). Use when Git Bash is installed but not in your PATH. If the
> path doesn't exist or the file isn't named `bash.exe`, `sh.exe`, `bash`, or
> `sh`, Claude Code ignores the variable and auto-detects Git Bash as if it
> were unset, logging a warning visible with `--debug`.

## The variable in a settings file

The setup page, "Install on native Windows":

> **With Git for Windows**, Claude Code uses Git Bash for the Bash tool. If
> Claude Code can't find Git Bash, set the path in your settings.json file:

The env-vars page, "Set variables in settings files" and "Precedence":

> Add variables under the `env` key in a `settings.json` file, creating the
> file if it doesn't exist. Claude Code reads them directly from the file, so
> they take effect no matter how `claude` was launched.

> | `~/.claude/settings.json` | You, in every project |
> | `.claude/settings.json` | Everyone working in the project, checked into source control |
> | `.claude/settings.local.json` | You, in this project only, gitignored when Claude Code saves a setting to it; add it to your gitignore if you create it by hand |

> When the same variable is set in both your shell and a settings file `env`
> block, the settings file value applies in most sessions.

---

## What espalier asserts against this excerpt

- `espalier/_venv.py::GIT_BASH_DEFAULT_PATHS` is the page's two default
  install locations, in its order, each with `bin\bash.exe` under it (the
  page's step 1 names only the install roots; the `bin\bash.exe` under them
  is step 2's suffix and the 2.1.316 binary's literal, so no quote binds it),
  and `::GIT_BASH_NAMES` is the four file names the variable accepts.
  `tests/test_hook_exec_form.py::TestGitBashLookup::test_the_copy_is_the_pinned_lookup`
  reads both off this file's quotes, so a re-excerpt that moves either reds
  that test until the copy follows.
- `espalier/_venv.py::git_bash_path` follows the documented order: the
  variable, when its file name is one of those four and the path exists (else
  it falls through, as the page says it has since v2.1.219); then the default
  locations; then `bin\bash.exe` in the Git installation of a `git` on PATH.
  It widens on purpose, as its docstring says: every `git` on PATH is asked,
  not only the first; and the variable is read from the three settings files
  above as well as from the process environment, since Claude Code reads
  those however it was launched. A third widening follows from the second:
  the copy tries each candidate value in turn, where Claude Code applies one
  (the settings value outranking the shell's), so a usable shell value beside
  an unusable settings value reads as a path here while Claude Code ignores
  the variable and auto-detects. `doctor` reads only whether any step finds a
  bash, so the precedence moves its verdict only on such a host.
- **Not followed:** the step-2 skip of a `git` the project placed (`DEF-3021`).
  `git_bash_path` asks every `git` on PATH, under the project or not. Who it
  reaches: a host whose only Git with a `bin\bash.exe` sits under the project
  in such a folder, carrying a bare statusLine an older `init` wrote: Claude
  Code skips that `git` and runs the line under PowerShell, which blanks it,
  and `doctor` finds the bash and says nothing. The wording leaves open
  whether the virtual-environment folder must sit below the launch folder
  (the page's own example has `env` above it), and `doctor` runs from the
  repository root, not from the folder Claude Code was launched from; the
  row's fix reads the installed binary first.
- **Not asserted:** a `CLAUDE_CODE_GIT_BASH_PATH` set in managed settings.
  espalier reads no managed settings file, so such a value is unseen and the
  copy can read None where Claude Code finds Git Bash: `doctor` then names a
  working bare line and asks for the dotted form, which also runs.
- **Not asserted:** the page's version notes (v2.1.219's name check). The
  copy follows the current rule only.
