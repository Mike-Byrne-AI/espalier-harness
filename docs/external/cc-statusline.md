---
source_url: https://code.claude.com/docs/en/statusline.md
fetch_note: |
  The `.md` suffix is LOAD-BEARING, for the reason recorded on
  cc-hook-protocol.md: without it the origin serves the rendered page and the
  refresher stores the HTML verbatim.
mirrors:
  - https://code.claude.com/docs/en/statusline
fetched: 2026-09-07
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
**Fetched:** 2026-09-07
**Section:** "How status lines work", "Windows configuration", "Troubleshooting"
**Purpose:** Verification target for the statusLine string `espalier init` renders and every espalier claim about the shell that runs it, when it runs, and how it fails.

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
> your script runs once after the changes stop.

## How it fails — silently

> Scripts that exit with non-zero codes or produce no output cause the status
> line to go blank

> Run `claude --debug` to log the exit code and stderr from the first status
> line invocation in a session

This is the sentence the DEF-508 fallback rests on: a statusline whose command
cannot start shows NOTHING, so the `|| echo '<line>'` clause must both exit 0
and print, or the operator sees a blank either way.

## Gated like hooks

> Because `statusLine` executes a shell command, Claude Code runs it under the
> same workspace trust rule as hooks in settings files.
>
> Until then, the status line stays blank

> If `disableAllHooks` is `true` outside managed settings after settings
> precedence applies, Claude Code runs only a `statusLine` from managed
> settings, and with no managed `statusLine` the status line is disabled.

So a kill-switched install loses the fallback line along with the hooks it
would have reported on; the CI guard and `doctor` remain the detectors for
that state.

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
  Whether the PowerShell-only path runs a quoted head is the walk's to
  witness; the plain render it replaces expanded nothing there either.
- `tests/test_hook_exec_form.py::TestStatusLinePortability` — the string is
  shell-form, quoted against a space-bearing project dir, POSIX-only for the
  clause, the clause prints the line with exit 0 when the interpreter is
  missing or the placeholder is unexpanded, and the shim carries the same
  text, forces exit 0 on that branch and uses no label (cmd.exe misreads a
  label search in an LF-only file).
- `espalier/doctor.py::_statusline_fallback_notes` — says when the clause
  disagrees with the host.
- `docs/HOOKS.md`, `docs/TROUBLESHOOTING.md` — the operator-facing claims
  about the blank statusline and the fallback line.

**Observed, not quoted** (a live probe, Claude Code 2.1.263, 2026-09-07): an
exec-form hook whose `command` is not on PATH produces the transcript notice
`Error occurred while executing hook command: Executable not found in $PATH:
"<name>"`, and the session continues. The hooks page documents the shell-form
sibling (`Failed with non-blocking status code: /bin/sh: ...: No such file or
directory`) but not the exec-form text; if a refresh of cc-hook-protocol.md
ever does, move this observation there.
