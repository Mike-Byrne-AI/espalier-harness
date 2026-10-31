---
source_url: https://code.claude.com/docs/en/statusline.md
fetch_note: |
  The `.md` suffix is LOAD-BEARING, for the reason recorded on
  cc-hook-protocol.md: without it the origin serves the rendered page and the
  refresher stores the HTML verbatim.
mirrors:
  - https://code.claude.com/docs/en/statusline
fetched: 2026-10-10
section: "How status lines work; Windows configuration; Troubleshooting"
section_anchor: "how-status-lines-work"
content_hash: ""
refresh_policy: weekly
purpose: |
  Verification target for the statusLine string `espalier init` renders
  (`espalier/cli.py::_statusline_command`) and for any espalier doc or
  docstring claim about which shell runs it, when it runs, and what Claude
  Code shows when it fails -- the facts the DEF-508 interpreter-missing
  fallback rests on.
---

# Claude Code Status Line — Pinned Excerpt

**Source:** https://code.claude.com/docs/en/statusline (fetched as the `.md` twin)
**Fetched:** 2026-10-10
**Section:** "How status lines work", "Windows configuration", "Troubleshooting"
**Purpose:** Verification target for the statusLine string `espalier init` renders and every espalier claim about the shell that runs it, when it runs, and how it fails.

<!-- re-excerpt 2026-10-01: all three section names in `section:` still exist
     upstream verbatim, so `section:` and `section_anchor` are unchanged. The
     field/shape quotes below come from "Manually configure a status line",
     which `section:` has never named -- left as it was rather than widened in
     a refresh. -->

<!-- re-excerpt 2026-10-10, against the page fetched that day, by the
     refresh's quote check (DEF-744): 11 of the 12 quoted passages stood word
     for word; the workspace-trust passage under "Gated like hooks" was
     reworded upstream ("the status line stays blank" moved to its first
     sentence, same rule) and is re-excerpted. All four section names above
     still exist. -->

---

## It is a shell string, with no exec form

> Set `type` to `"command"` and point `command` to a script path or an inline
> shell command.
>
> The `command` field runs in a shell, so you can also use inline commands
> instead of a script file.

The page documents the fields `type`, `command`, `padding`, `refreshInterval`
and `hideVimModeIndicator`. There is no `args` field and no exec form — which
is why espalier's statusLine stays a single command string while its hooks are
exec-form (`docs/external/cc-hook-protocol.md`, `tests/test_hook_exec_form.py`).

The page now also documents a sibling setting, `subagentStatusLine`, with the
same two-field shape (`type: "command"` plus a `command` string) and no `args`
either, for the per-subagent rows in the agent panel. espalier does not render
it.

<!-- re-excerpt 2026-10-01: both quotes above are word for word what the
     2026-09-28 page says; the first now has a cross-reference sentence
     appended after it ("For a full walkthrough of creating a script, see Build
     a status line step by step"), which changes nothing the pin rests on. The
     four optional fields are still the complete set and there is still no
     `args`. `subagentStatusLine` is NEW to the page and recorded because it is
     the one place a reader could expect an exec form to have appeared. -->

## Which shell

The page names the shell only for Windows:

> On Windows, Claude Code runs status line commands through Git Bash when Git
> Bash is installed, or through PowerShell when Git Bash is absent.

For macOS and Linux it says only that the command "runs in a shell". The hooks
page pins `sh -c` for shell-form *hook* commands on macOS and Linux
(cc-hook-protocol.md's source, section "Exec form and shell form", read
2026-09-07); espalier does NOT assume the statusline uses the same shell — the
`|| echo` clause it renders behaves identically under sh, bash, dash and zsh,
and the test drives it under `sh -c`.

The page now also says how Git Bash mangles a Windows path in the `command`
string, and that the failure is invisible:

> Git Bash treats unquoted backslashes as escape characters, so a Windows-style
> path such as `C:\Users\username\script.mjs` reaches the script runner with
> its separators removed and the command fails without a visible error. Write
> file paths in the `command` string with forward slashes, as shown in the
> examples below. The `~` shorthand also works and expands to your Windows
> home directory.

> To run a PowerShell script as your status line, invoke it via `powershell`.
> This works whether Claude Code routes the command through Git Bash or
> PowerShell

<!-- re-excerpt 2026-10-01: NEW upstream text, and it CONFIRMS two choices the
     pin's assertions already carry rather than contradicting either. espalier
     renders `"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" <interp>`: the
     separators it writes itself are forward slashes, and the placeholder is
     inside double quotes, which is exactly the "unquoted" qualifier upstream
     names -- so the quoting that DEF-508's test pins against word-splitting is
     now load-bearing for a second, independently documented reason on Windows.
     "the command fails without a visible error" is a second upstream sentence
     behind the silent-blank claim below. The `powershell`-invocation sentence
     is the shape espalier deliberately does NOT use (DEF-729 wires the batch
     shim instead, because the walk drove the `cmd /c` spellings dead and
     PowerShell 5.1 has no `||`); it is recorded so the alternative is on the
     record, not adopted. -->

## When it runs

> Your script runs once when a session starts, including when you resume one.
> After that, it runs again when:
>
> * A new assistant message arrives
> * `/compact` finishes
> * The permission mode changes
> * Vim mode toggles
> * You change the `command` in your `statusLine` settings
> * A `refreshInterval` timer elapses, if you set one
> * A rate-limit window in the data your script last received reaches its `resets_at` time
> * A warm prompt cache in the data your script last received reaches its `expires_at` time
>
> Claude Code debounces updates at 300ms, so rapid changes batch together and
> your script runs once after the changes stop. A change to the `command`
> itself skips the debounce: Claude Code runs the new command right away. If a
> new update triggers while your script is still running, Claude Code cancels
> the in-flight script. If you edit your script, the changes appear the next
> time an update trigger re-runs it.

<!-- re-excerpt 2026-10-01: the trigger list and the 300ms debounce sentence are
     unchanged word for word. THREE sentences are new after the debounce one
     (command-change skips the debounce; an in-flight script is cancelled when
     a new trigger arrives; a script edit takes effect on the next trigger).
     None weakens the fallback: the `|| echo` clause is part of the `command`
     string, so an interpreter that stops resolving produces the fallback on
     every one of these triggers, and a cancelled in-flight run is a run that
     never reached the clause -- the same blank the clause exists to replace,
     from a slow script rather than a missing one. -->

## How it fails — silently

> Scripts that exit with non-zero codes or produce no output cause the status
> line to go blank

> Slow scripts block the status line from updating until they complete. Keep
> scripts fast to avoid stale output.

> Run `claude --debug` to log your script's stderr on every status line
> invocation, and its exit code on the first invocation in a session

<!-- re-excerpt 2026-10-01: the blank-on-non-zero-or-no-output sentence is
     UNCHANGED, so the DEF-508 premise stands as quoted. The `claude --debug`
     sentence CHANGED and the 2026-09-07 excerpt's version of it ("log the exit
     code and stderr from the first status line invocation in a session") is now
     a misquote: upstream logs stderr on EVERY invocation and only the exit code
     on the first. Replaced above with the live sentence. Downstream doc fix
     owed, not made here: `docs/TROUBLESHOOTING.md:86` (and its deployed mirror
     `espalier/assets/docs/TROUBLESHOOTING.md:86`) still say "logs the exit code
     and stderr of the first statusline run". The slow-script sentence is new
     and is the one failure mode the `||` clause cannot cover. -->

This is the sentence the DEF-508 fallback rests on: a statusline whose command
cannot start shows NOTHING, so the `|| echo '<line>'` clause must both exit 0
and print, or the operator sees a blank either way.

## Gated like hooks

> Until you accept the workspace trust dialog, the status line stays blank.
> Because `statusLine` executes a shell command, Claude Code runs it under the
> same workspace trust rule as hooks in settings files. Accepting the dialog
> for the folder, or for a parent directory whose trust extends to it, is
> enough.
>
> Until then, `claude --debug` logs `Status line command skipped: workspace
> trust not accepted`. Restart Claude Code and accept the trust dialog to
> enable it.

> If `disableAllHooks` is `true` outside managed settings after settings
> precedence applies, Claude Code runs only a `statusLine` from managed
> settings, and with no managed `statusLine` the status line is disabled.
> Remove the setting, or set it to `false` in the file that sets it, to
> re-enable.

A THIRD gate the 2026-09-07 excerpt did not carry:

> If your organization sets `allowManagedHooksOnly` in managed settings, your
> custom status line disappears without warning: you can only get a status
> line from a `statusLine` value in those managed settings.

and, on the sibling setting:

> The same trust, `disableAllHooks`, and `allowManagedHooksOnly` gates that
> apply to `statusLine` apply here.

<!-- re-excerpt 2026-10-01: both 2026-09-07 quotes hold word for word and are
     EXTENDED, not contradicted -- the trust rule now says a parent folder's
     trust suffices and names the `--debug` line a blocked statusline logs, and
     the `disableAllHooks` bullet now names the re-enable step. `allowManagedHooksOnly`
     is NEW on this page and belongs to the pin's `purpose` ("trust/kill-switch
     gating"): it is a managed-settings gate that blanks espalier's statusline
     "without warning", and unlike `disableAllHooks` it is not a kill-switch a
     slip can write locally -- only managed settings can set it, so neither
     `config_guard` nor `write_guard` is the detector for it. docs/CC_AUTOMATION.md:53
     is the only place in the harness that names it today. -->

So a kill-switched install loses the fallback line along with the hooks it
would have reported on; the CI guard and `doctor` remain the detectors for
that state — and under `allowManagedHooksOnly` the line is gone with no local
setting to detect at all.

---

## What espalier asserts against this excerpt

- `espalier/cli.py::_statusline_command` renders one shell string (no `args`),
  appends `|| echo '<STATUSLINE_FALLBACK_TEXT>'` on a POSIX host and, on
  Windows (`os.name == "nt"`), wires the deployed batch shim
  `tools/cc/statusline.cmd` as the command's head with the interpreter as its
  argument (DEF-729): Windows PowerShell 5.1 has no `||`, and the Windows
  walk drove the `cmd /c` spellings dead (Git Bash rewrites the switch into a
  drive path; `//c` starts an interactive cmd under PowerShell). Batch has
  the or-operator, so the shim prints the same line, exit 0, and a `.cmd` is
  invocable from Git Bash, the shell this page names when it is installed.
  The PowerShell-only path reads a quoted head as an expression (witnessed
  2026-09-26, driven again 2026-10-31), so where `espalier._venv.git_bash_path`
  finds no Git Bash the render is `& "<shim>" <interp>`, PowerShell's call
  operator, which Git Bash cannot parse. Neither form serves both shells (a
  `powershell -NoProfile -Command "& '<shim>' <interp>"` head does, at a
  second PowerShell start on every refresh, driven by the 2026-10-31 review
  and not adopted), so the render follows the shell this page says will run
  it, and keeps the bare form wherever a trace of Git Bash is found.
  <!-- re-excerpt 2026-10-01: unchanged and now better supported. The page's new
       Git Bash backslash paragraph says a backslash-separated path in the
       `command` string "fails without a visible error" when UNQUOTED -- the
       render is forward-slashed and double-quoted, so it is on the documented
       side of both halves. -->
- `tests/test_hook_exec_form.py::TestStatusLinePortability` — the string is
  shell-form, quoted against a space-bearing project dir, POSIX-only for the
  clause, the clause prints the line with exit 0 when the interpreter is
  missing or the placeholder is unexpanded, and the shim carries the same
  text, forces exit 0 on that branch and uses no label (cmd.exe misreads a
  label search in an LF-only file).
- `espalier/doctor.py::_statusline_fallback_notes` — says when the clause
  disagrees with the host, and when a Windows shim render is the form for
  the other shell.
  <!-- re-excerpt 2026-10-01: newly qualifiable, no code change asserted here.
       The four states it enumerates are all about the STRING vs the host. The
       page now documents a fifth way espalier's statusline goes dark that no
       string inspection can see: `allowManagedHooksOnly` in managed settings,
       which "disappears without warning" and leaves a perfectly correct
       `statusLine` in the repo's own settings. Whether `doctor` should read
       managed settings for it is a decision, not a refresh. -->
- `docs/HOOKS.md`, `docs/TROUBLESHOOTING.md` — the operator-facing claims
  about the blank statusline and the fallback line.
  <!-- re-excerpt 2026-10-01: one of these is now STALE against upstream.
       `docs/TROUBLESHOOTING.md:86` says `claude --debug` "logs the exit code
       and stderr of the first statusline run"; upstream now logs stderr on
       every invocation and the exit code only on the first. The deployed
       mirror `espalier/assets/docs/TROUBLESHOOTING.md:86` carries the same
       sentence and must move with it. -->

**Observed, not quoted** (the 2.1.316 binary, read 2026-10-31): the page's
"Git Bash when Git Bash is installed" is a lookup, in this order: a
`CLAUDE_CODE_GIT_BASH_PATH` whose file name is `bash`, `sh`, `bash.exe` or
`sh.exe` and which exists (otherwise a warning, and the lookup goes on);
`C:\Program Files\Git\bin\bash.exe`; `C:\Program Files (x86)\Git\bin\bash.exe`;
then `bin\bash.exe` two levels above the first `git` that `where.exe` names.
The statusLine runs through the hook runner, whose default shell is `bash`
when that lookup finds a path and `powershell` otherwise; under PowerShell
the runner rewrites `${CLAUDE_PROJECT_DIR}` to `${env:CLAUDE_PROJECT_DIR}` and
passes the string as `-Command`, and under Git Bash it forward-slashes
`CLAUDE_PROJECT_DIR`. The statusLine schema in that build is `type`,
`command`, `padding`, `refreshInterval` and `hideVimModeIndicator`: no
`shell`, though the no-Git-Bash notice it shows names a `"shell"` setting
for StatusLine commands too; Claude Code applies each settings file's `env`
to its own environment before the lookup, and its settings-env filter names
`CLAUDE_CODE_GIT_BASH_PATH`. `espalier/_venv.py::git_bash_path` follows the
lookup with `shutil.which` in place of `where.exe`, and widens it: the
variable is also read from the settings files, and every `git` on PATH is
asked, not only the first, because a wrong "none" writes a form bash cannot
parse while a wrong "found" keeps the line hosts had before.

**Observed, not quoted** (a live probe, Claude Code 2.1.263, 2026-09-07): an
exec-form hook whose `command` is not on PATH produces the transcript notice
`Error occurred while executing hook command: Executable not found in $PATH:
"<name>"`, and the session continues. The hooks page documents the shell-form
sibling (`Failed with non-blocking status code: /bin/sh: ...: No such file or
directory`) but not the exec-form text; if a refresh of cc-hook-protocol.md
ever does, move this observation there.

<!-- re-excerpt 2026-10-01: checked, stays here. The hooks page at the same
     2026-09-28 fetch still documents only the shell-form sibling (its
     "A hook that can't start lands in the same non-blocking bucket" paragraph,
     quoting `/bin/sh: /path/to/hook.sh: No such file or directory`) and still
     prints no exec-form text, so there is nowhere to move it to. -->
