"""Shared denial-reason templates for hook scripts.

Single source of truth for the reason strings passed to ``deny()`` /
``block()`` across write_guard, plan_guard, config_guard, and
stop_gate. The deny()/block() FUNCTIONS stay per-hook (event-shape
specific per docs/external/cc-hook-protocol.md); the REASON STRINGS
centralize here.

Stdlib-only. Zero ``espalier`` imports -- runs standalone alongside
the rest of ``tools/cc/hooks/`` per the harness's zero-imports rule.

Self-host scope: the contract test ``tests/test_denial_reasons.py``
is gated by ``_hook_utils.is_self_host_repo()`` and does NOT fire on
adopter repos. Adopters may edit their copy without breaking upstream
contracts; this is a deliberate friction tradeoff.

Conventions:
- Templates are module-level ``UPPER_SNAKE_CASE`` string constants.
- Format placeholders use ``{name}`` (not positional ``{0}``) so
  callers can pass keyword arguments.
- Helper functions (``def``) compose templates with required kwargs
  when the call site benefits from not knowing the format keys.
- The ``Contract 3`` dead-template scan in
  ``tests/test_denial_reasons.py`` walks module-level ``ast.Assign``
  nodes only -- function definitions are excluded by AST type.
"""
from __future__ import annotations

# Import the canonical env-var name so the reason templates pin to the SoT in
# _maintenance_mode.ENV_VAR rather than carrying a divergent literal.
# Sibling-module import; the importing hook has already set
# ``sys.path.insert(0, hooks_dir)`` by the time this module loads (see
# write_guard.py:45-50 for the pattern).
import _maintenance_mode  # type: ignore[import-not-found]


# ── write_guard reason templates ─────────────────────────────────────

MALFORMED_WRITE_PAYLOAD = (
    "Malformed Write/Edit payload: file_path must be str, got {type_name}"
)

MALFORMED_MCP_PAYLOAD = (
    "Malformed MCP payload: field {field_name!r} on {tool_name} must be "
    "str, got {type_name}"
)

# The relaunch inside is _maintenance_mode.relaunch_hint(), evaluated ONCE at
# import (host-keyed); a platform-sensitive test reloads via importlib.
PROTECTED_ZONE_WRITE = (
    "Write to protected harness zone blocked: {path}.{hint}"
    "\n  Don't: edit harness files from a regular session (`.claude/settings.json`, "
    "the whole `tools/cc/` tree, etc.), and don't disable "
    "hooks to get around this."
    f"\n  Do: ask the operator to relaunch with {_maintenance_mode.relaunch_hint()} "
    "BEFORE the edit (env-vars set mid-session don't reach already-running "
    "hooks; --continue keeps the session you are in), then resume the change "
    "through your normal workflow (/implement-task) -- the harness self-edit "
    "is the exception, not your task."
    # Maintenance mode is for editing the HARNESS. If this is your OWN source
    # that merely collides with a harness path (e.g. a top-level `cc/`),
    # relocate your directory instead -- don't run in maintenance mode.
    "\n  Your own source colliding with a harness path (e.g. a top-level "
    "`cc/`)? Relocate it from your own terminal, outside a Claude Code "
    "session (the guard reads tool calls, not your shell) -- maintenance "
    "mode is not the remedy for that."
)

PROTECTED_ZONE_WRITE_BASH = (
    "Bash write to protected harness zone blocked: {path}.{hint}"
)

# The remove/relocate twins of the write templates (§C52): ``{effect}`` is
# ``delete`` or ``move`` -- the operand a verb removes or relocates, or a
# directory enclosing a protected path. Same way-forward as the write
# template; "protected harness zone" is the substring the end-to-end bench
# recognises as a deny reason.
PROTECTED_ZONE_MUTATION = (
    "{effect} of protected harness zone blocked: {path}.{hint}"
    "\n  Don't: delete, move or rename harness files from a regular session "
    "(`.claude/settings.json`, the whole `tools/cc/` tree, etc.), and don't "
    "disable hooks to get around this."
    f"\n  Do: ask the operator to relaunch with {_maintenance_mode.relaunch_hint()} "
    "BEFORE the change (env-vars set mid-session don't reach already-running "
    "hooks; --continue keeps the session you are in), then resume the change "
    "through your normal workflow (/implement-task) -- the harness self-edit "
    "is the exception, not your task."
    "\n  Your own source colliding with a harness path (e.g. a top-level "
    "`cc/`)? Relocate it from your own terminal, outside a Claude Code "
    "session (the guard reads tool calls, not your shell -- and a move of "
    "that directory is itself a refused row) -- maintenance mode is not the "
    "remedy for that."
)

PROTECTED_ZONE_MUTATION_BASH = (
    "Bash {effect} of protected harness zone blocked: {path}.{hint}"
)

PROTECTED_ZONE_WRITE_MCP = (
    "Write to protected harness zone blocked: {path} (via mcp tool "
    "{tool_name}, field {field_name}).{hint}"
)

# An MCP payload nested deeper / wider than the leaf-walk can verify is denied
# fail-closed (an un-inspectable write target is refused, not waved through).
# Carries the {hint} so the deny is attributable to the protected-zone layer
# (parity with PROTECTED_ZONE_WRITE_MCP).
MCP_PAYLOAD_UNVERIFIABLE = (
    "MCP payload too deeply nested or too large to verify its write targets "
    "(via mcp tool {tool_name}); denied fail-closed.{hint}"
)

PROTECTED_ZONE_SYMLINK_BASH = (
    "Bash symlink creation into protected harness zone blocked: {path} "
    "(symlinks bypass the file-path allowlist by design)"
)

# MCP / PowerShell symlink-creation twins of the Bash check. A symlink may
# NEVER land in a governed zone (protected OR allowlisted-in-protected)
# regardless of channel -- a stray symlink would silently redirect a later
# harness read to off-path content (e.g. a swapped cc/execution_plan.json).
# De-prioritized defense-in-depth: kept (deleting fails toward over-protect),
# but no self-user reaches it by mistake.
PROTECTED_ZONE_SYMLINK_MCP = (
    "MCP symlink creation into protected harness zone blocked: {path} "
    "(via mcp tool {tool_name}; symlinks bypass the file-path allowlist by design)"
)
PROTECTED_ZONE_SYMLINK_PS = (
    "PowerShell symlink creation into protected harness zone blocked: {path} "
    "(symlinks bypass the file-path allowlist by design)"
)

# A HARDLINK aliases an inode under a second name, so
# `ln <protected> alias; echo evil > alias` rewrites the protected file's bytes
# while the write lands on an UNPROTECTED path string. `Path.resolve()` cannot
# follow a hardlink (there is no target to follow), so the path-string check is
# blind to it -- the inode sister of the symlink class. Two diagnostics: the
# creation-time deny (the ln/cp -l command) names the protected SOURCE; the
# write-through backstop names the alias whose inode matches a protected file.
PROTECTED_ZONE_HARDLINK_BASH = (
    "Bash hardlink of a protected harness file blocked: {path} "
    "(a hardlink aliases the file's bytes under a second name; writing through "
    "the alias would rewrite the protected file)"
)
PROTECTED_ZONE_HARDLINK_INODE = (
    "Write to a hardlink alias of a protected harness file blocked: {path} "
    "(its inode matches a protected file; the write would rewrite protected bytes)"
)

# pid -> plain-English "what matched", so the operator sees the intent, not a
# raw regex. Keyed by BashPatternRecord.pid (write_guard.DANGEROUS_BASH_PATTERNS).
# Message text only -- the patterns themselves are unchanged.
DANGEROUS_BASH_PLAIN = {
    # ⚠ BOTH RECORDS ARE RIGHT-ANCHORED (`rm -rf /` or `rm -rf *`, then
    # whitespace or the end of the command), so each fires only when the target
    # IS the bare root or the bare glob. `rm -rf /tmp/x` never reaches them:
    # since the 2026-08-24 re-tier `_bash_patterns._target_is_catastrophic`
    # judges every other target by MEANING, and CATASTROPHIC_RM below names
    # that rule. For two weeks after the re-tier this entry still said the
    # guard refuses an absolute path "whether or not the target is the
    # filesystem root" -- the previous matcher's sentence over the new one, a
    # false statement about what the operator had typed (DEF-739).
    "rm-rf-root": "a recursive delete of the filesystem root itself ('rm -rf /')",
    "rm-rf-star": (
        "a recursive delete of everything in the working directory "
        "('rm -rf *')"
    ),
}
# ⚠ THE REMEDY MUST NAME THE AXIS THAT ACTUALLY CLEARS THE DENY, and two texts
# have named the wrong one. "narrow the target (a specific path)" -- a scoped
# path already IS specific. Then "relative to the repo", which was the axis
# until the 2026-08-24 re-tier and has not been since: the repo's own build
# directory by absolute path and `rm -rf /tmp/x` fall to the soft tier, while an
# absolute path with a `..` step does not. The axis is what the target MEANS
# (`_bash_patterns._target_is_catastrophic`), so the remedy says which
# targets run and which are refused, in the operator's terms. Keep it in step
# with CATASTROPHIC_RM below; tests/test_denial_reasons.py pins the vocabulary.
DANGEROUS_BASH_PATTERN_FALLBACK = (
    "Dangerous command blocked: {what}. If this was a deliberate, scoped "
    "cleanup, narrow the target to the directory you mean: a path inside the "
    "repo or inside your home directory, or under a temp root, is not refused "
    "here (most draw one confirm-by-re-issue nudge; a relative build/ or dist/ "
    "there passes without one); the filesystem root, your home directory or the "
    "repo itself (a bare '*' glob or $PWD counts as the directory the delete "
    "runs in when the command is plain, and is refused when it is not), a "
    "shallow system path such as /etc or "
    "/usr/local, and an absolute path with a '..' step are refused in every "
    "flag order -- then re-run."
)

# Flag-order-independent catastrophic recursive-delete hard-deny. The two
# literal `-rf` regexes in write_guard.DANGEROUS_BASH_PATTERNS only catch the
# glued order against a bare `/` or `*`; this fires for `rm -fr /`, `rm -r -f
# /`, `rm --recursive --force /`, `rm -rvf /*`, multi-operand and quoted forms,
# and it is the tier that judges every OTHER target by meaning
# (`_bash_patterns._target_is_catastrophic`: the root, home or the repo or a
# parent of either, a shallow system path, an absolute `..` step, and a bare
# glob or `$PWD` judged as the directory it names -- DEF-849/843; everything
# else falls to the CP-RMRF nudge). Diagnostic
# (a hard safety stop), so it is intentionally NOT in _OPERATOR_FACING_TEMPLATES
# -- no Don't/Do habit pair (cf. DANGEROUS_BASH_PATTERN_FALLBACK).
CATASTROPHIC_RM = (
    "Dangerous command blocked: recursive delete, forced or not, of a "
    "catastrophic target -- the filesystem root, your home "
    "directory or the repo (or a parent of either), a shallow system path "
    "such as /etc or /usr/local, or an absolute path with a '..' step -- "
    "detected in any flag order; a relative target is read from the directory "
    "the command runs in, after its own cd (so a `cd ..` followed by a delete "
    "of the checkout by its own name names the repo), and a bare '*' glob or "
    "$PWD as that directory itself, but only in a plain command -- statements "
    "joined by ;, &&, || or newlines, each run by a command the guard knows "
    "hands nothing to a shell (a build tool such as make is not one: put the "
    "clean in its own command); with a pipe, a group, a subshell, a "
    "substitution, a heredoc, a loop or another shell's program in the "
    "command, or after a cd it cannot read, a bare glob or $PWD is refused. "
    "This is a hard safety "
    "stop (maintenance mode "
    "does not bypass it). To proceed, narrow the target to the directory you "
    "mean: a path inside the repo or inside your home directory, or under a "
    "temp root, is not refused here (most draw one confirm-by-re-issue nudge; "
    "a relative build/ or dist/ there passes without one)."
)

# The same hard stop for the enumerator spelling (DEF-815): an un-narrowed
# `find` with a delete action rooted at a catastrophic target. Same
# vocabulary as CATASTROPHIC_RM (the classifier is the same), same tier, the
# same absence from _OPERATOR_FACING_TEMPLATES; the remedy names the two
# axes that clear it -- a narrowing predicate, or a narrower root. Pinned
# beside CATASTROPHIC_RM in tests/test_denial_reasons.py.
CATASTROPHIC_FIND_DELETE = (
    "Dangerous command blocked: a find with a delete action (-delete, or "
    "-exec with a remove verb) and no name-or-path predicate in force before "
    "it (a -type or an attribute test narrows nothing; a negation or an -o "
    "re-widens the walk), rooted at a catastrophic target -- the filesystem "
    "root, your home directory or the repo "
    "(or a parent of either), a shallow system path such as /etc or "
    "/usr/local, or an absolute path with a '..' step; a relative root is "
    "read from the directory the command runs in, after its own cd, and a "
    "bare '*' glob root is refused wherever it runs (root the walk at . or a "
    "named directory instead). "
    "Un-narrowed, the walk takes every file under the root, hooks included, "
    "so this is a hard safety stop (maintenance mode does not bypass it). To "
    "proceed, narrow the walk with a -name, -path or -regex predicate placed "
    "before the action, or root it at the directory you mean: a path inside "
    "the repo or inside your home directory, or under a temp root, is not "
    "refused here (most draw one confirm-by-re-issue nudge; a relative "
    "build/ or dist/ there passes without one)."
)

# The carrier spelling of the same wipe (DEF-826): an enumerator -- a find
# with no action, `ls` -- piped through `xargs` into a remove verb, its
# operands arriving on stdin. Same vocabulary, same tier, same judge
# (`_bash_patterns._target_is_catastrophic`); pinned beside the two above in
# tests/test_denial_reasons.py, the claims driven through
# `_bash_patterns.has_catastrophic_bash_sweep`.
CATASTROPHIC_PIPED_REMOVE = (
    "Dangerous command blocked: an enumerator (a find with no action, ls, or "
    "git ls-files) piped through xargs into a remove verb, with no "
    "name-or-path predicate, bounded wildcard or bounded pathspec narrowing "
    "it (a -type or an attribute test narrows nothing; a catch-all value such "
    "as -name '*' narrows nothing; an exclude pathspec narrows nothing), rooted at "
    "a catastrophic target -- the filesystem root, "
    "your home directory or the repo (or a parent of either), a shallow "
    "system path such as /etc or /usr/local, or an absolute path with a '..' "
    "step; a relative root is read from the directory the command runs in, "
    "after its own cd, and a bare '*' glob root is refused wherever it runs "
    "(a pipeline or a loop is never a plain command). "
    "The enumerator hands the remove verb every path under "
    "the root, hooks included, so this is a hard safety stop (maintenance "
    "mode does not bypass it). To proceed, narrow the enumeration with a "
    "-name, -path or -regex predicate, a bounded wildcard or a bounded "
    "pathspec, or root it at "
    "the directory you mean: a path inside the repo or inside your home "
    "directory, or under a temp root, is not refused here (most draw one "
    "confirm-by-re-issue nudge; a relative build/ or dist/ there passes "
    "without one)."
)

# The loop carrier's twin of the stop above (DEF-830): the same enumerator
# bound to a loop variable and removed in the loop's body -- the pipe into a
# read loop, a for loop over the enumerator's command substitution, a read
# loop fed from it at its tail -- rooted at a catastrophic target; and
# (DEF-837) a for loop's own word list, which has no enumerator, so the text
# names it beside one and offers the remedy that fits it (list only what you
# mean). Same vocabulary, same tier, same judge. Pinned beside CATASTROPHIC_RM
# in tests/test_denial_reasons.py, the claims driven through
# `_bash_patterns.has_catastrophic_bash_sweep` on all four heads.
CATASTROPHIC_LOOP_REMOVE = (
    "Dangerous command blocked: an enumerator (a find with no action, ls, or "
    "git ls-files) or a for loop's own word list, bound to a loop variable "
    "and removed in the loop's body (a pipe into a read loop, a for loop over "
    "the enumerator's command substitution or over the listed words, or a "
    "read loop fed from it at its tail), with no "
    "name-or-path predicate, bounded wildcard or bounded pathspec narrowing "
    "it (a -type or an attribute test narrows nothing; a catch-all value such "
    "as -name '*' narrows nothing; an exclude pathspec narrows nothing), rooted at "
    "a catastrophic target -- the filesystem root, "
    "your home directory or the repo (or a parent of either), a shallow "
    "system path such as /etc or /usr/local, or an absolute path with a '..' "
    "step; a relative root is read from the directory the command runs in, "
    "after its own cd, and a bare '*' glob root is refused wherever it runs "
    "(a pipeline or a loop is never a plain command). "
    "The loop hands the remove verb every path under the "
    "root one per turn, or each listed entry to recurse into, hooks included, "
    "so this is a hard safety stop (maintenance mode does not bypass it). To "
    "proceed, narrow the enumeration with a -name, -path or -regex predicate, "
    "a bounded wildcard or a bounded pathspec, list only the entries you mean "
    "(for f in build/* draws one confirm-by-re-issue nudge, since the loop "
    "removes a variable), or root it at the directory you mean: a path inside "
    "the repo or "
    "inside your home directory, or under a temp root, is not refused here "
    "(most draw one confirm-by-re-issue nudge; a relative build/ or dist/ there "
    "passes without one)."
)

# The PowerShell tool's twin of the two stops above (DEF-824, DEF-822): the
# shapes pwsh runs that spell the same wipe -- GNU/BSD find with a delete
# action (verbatim under pwsh on macOS and Linux), and an enumerator piped
# into a remove verb (`Get-ChildItem -Recurse | Remove-Item -Recurse -Force`
# by any alias or unambiguous switch prefix) -- rooted at a catastrophic
# target. Same vocabulary, same tier, one difference the text states: a
# variable or a backtick in the root is refused too, as the Remove-Item tier
# refuses them (the value is pwsh's to expand). Pinned beside CATASTROPHIC_RM
# in tests/test_denial_reasons.py, the claims driven through
# `_bash_patterns.has_catastrophic_ps_sweep`.
CATASTROPHIC_PS_SWEEP = (
    "Dangerous command blocked: a sweep with nothing narrowing it -- a find "
    "with a delete action (-delete, or -exec with a remove verb) and no "
    "name-or-path predicate in force before it (a -type or an attribute test "
    "narrows nothing; a negation or an -o re-widens the walk; a catch-all "
    "value such as -name '*' narrows nothing), an enumerator (Get-ChildItem, "
    "gci, ls, dir, a find with no action, or git ls-files) piped into a remove verb "
    "(directly, or through xargs) with no -Include or -Filter value "
    "that excludes anything, no bounded wildcard in its root and, for git "
    "ls-files, no bounded pathspec, or a "
    "recursive .NET directory delete -- rooted at a catastrophic target: the "
    "filesystem root, "
    "your home directory or the repo (or a parent of either), a "
    "shallow system path such as /etc or /usr/local, an absolute path with a "
    "'..' step, or a root the guard cannot read (a variable, a backtick); a "
    "relative root is read from the directory the command runs in, after "
    "its own Set-Location, and a bare '*' glob as the directory it expands "
    "in (a find's bare glob root only in a plain command -- no pipe, block, "
    "subexpression, call or dot operator, script or another shell's program "
    "-- and refused in any other). Un-narrowed, the sweep takes every file under "
    "the root, hooks included, so this is a hard safety stop (maintenance "
    "mode does not bypass it). To proceed, narrow the sweep (a -name, -path "
    "or -regex predicate placed before the action; -Include or -Filter on "
    "the enumerator; a bounded pathspec or wildcard on git ls-files -- each "
    "with a value that excludes something, since a "
    "catch-all such as * narrows nothing), or root it at the directory you "
    "mean: a path inside "
    "the repo or inside your home directory, or under a temp root, is not "
    "refused here (most draw one confirm-by-re-issue nudge; a relative "
    "build/ or dist/ there passes without one)."
)

# The PowerShell tool's twin of CATASTROPHIC_RM for the recursive remove
# WITHOUT the force switch (DEF-842): the records match recurse-and-force
# only, and the unforced remove takes every item that is not hidden or
# read-only with no prompt when no terminal is attached (driven on pwsh
# 7.6.5). Judged by the sweep tier's judge, so the same vocabulary, and the
# same difference CATASTROPHIC_PS_SWEEP states: a target the guard cannot
# read is refused. Enrolled in the vocabulary check by its prefix.
CATASTROPHIC_PS_RECURSIVE_REMOVE = (
    "Dangerous command blocked: a recursive remove (Remove-Item -Recurse by "
    "any alias or unambiguous switch prefix, or the native rm -r pwsh hands "
    "a POSIX host), forced or not, of a catastrophic target: the filesystem "
    "root or a drive root, your home "
    "directory or the repo (or a parent of either), a shallow system path "
    "such as /etc or /usr/local, an absolute path with a '..' step, a "
    "variable that names the home directory ($HOME, $env:USERPROFILE), or a "
    "target the guard cannot read (a backtick); a relative target is read "
    "from the directory the command runs in, after its own Set-Location, and "
    "a bare '*' wildcard as the directory it expands in, but only in a plain "
    "command (statements joined by ;, &&, || or newlines: with a pipe, a "
    "block, a subexpression, the call or dot operator, a script or another "
    "shell's program in the command, or after a Set-Location it cannot read, "
    "the wildcard is refused); "
    "any other variable draws one confirm-by-re-issue nudge instead. Without "
    "-Force the remove still takes every item that is "
    "not hidden or read-only, with no prompt, so this is a hard safety stop "
    "(maintenance mode does not bypass it). To proceed, narrow the target to "
    "the directory you mean: a path inside the repo or inside your home "
    "directory, or under a temp root, is not refused here (most draw one "
    "confirm-by-re-issue nudge; a relative build/ or dist/ there passes "
    "without one)."
)

# Plain-English descriptions keyed by PS record pid -- the operator sees
# intent, never the raw regex source (parity with DANGEROUS_BASH_PLAIN).
DANGEROUS_PS_PLAIN = {
    "ps-remove-item-recurse-force-prefix": (
        "a recursive force-delete via Remove-Item -Recurse -Force"
    ),
    "ps-remove-item-recurse-force-mixed": (
        "a recursive force-delete via Remove-Item with -Recurse and -Force"
    ),
}
# ⚠ CLASS SIBLING of DANGEROUS_BASH_PATTERN_FALLBACK, and the worse instance.
# Driven 2026-08-22: `ps-remove-item-recurse-force-*` fires on EVERY -Recurse
# +-Force invocation -- INCLUDING a relative target, which the Bash twin
# allows. So the twin's "narrow the target to a specific path" named an action
# that could not clear the deny for ANY input. The remedy now names the flag
# combination, which is the thing the operator can actually change.
DANGEROUS_PS_PATTERN_FALLBACK = (
    "Dangerous PowerShell command blocked: {what} (plain-English by design "
    "-- the raw regex is never surfaced, parity with the Bash "
    "dangerous-command deny)."
    "\n  Don't: reshape the command to slip past the pattern -- this is a hard "
    "safety stop, not a lint nit, and maintenance mode does not bypass it."
    "\n  Do: this pattern refuses -Recurse together with -Force for an "
    "absolute, wildcard, variable or otherwise unreadable target, so "
    "re-pointing it at another such path will not clear this deny; a plainly "
    "relative target inside the repo draws one confirm-by-re-issue nudge "
    "instead. If you drop -Force, the remove is judged by what its target "
    "names from where it runs: the filesystem or a drive root, your home "
    "directory (by path, ~, $HOME or $env:USERPROFILE) and the repo are "
    "refused, a bare '*' or $PWD as the location itself, and any other path "
    "or variable draws one nudge -- and without -Force it "
    "still removes every item that is not hidden or read-only, with no "
    "prompt, so confirm the target before you re-issue."
)

WRITE_GUARD_INTERNAL_ERROR = "write_guard internal error; failing closed"

KILL_SWITCH_DETECTED = (
    "Espalier-Harness kill-switch setting detected{context}: {findings}. "
    "Remove the setting and run `espalier integrity verify .` before "
    "continuing."
    "\n  Don't: set `disableAllHooks: true` (or analogous kill-switches) "
    "to silence a hook that's firing inconveniently -- CI will still fail "
    "the merge regardless of the local setting."
    "\n  Do: remove the offending setting shown above ({findings}) "
    "-- or restore the hooks block -- to undo it, then identify what the hook "
    "flagged and fix the root cause, or file a tracked issue if the hook is wrong."
)

# Centralizing the harness-env-prefix deny message here brings it under the
# tested operator-facing-template contract (test_template_contains_both_markers).
# The env-var name pins to the SoT (_maintenance_mode.ENV_VAR); ESPALIER_STOP_GATE
# stays a literal (its SoT is stop_gate.STOP_GATE_MODE_ENV, not importable here
# under the zero-cross-import rule).
# Fires ONLY on an assignment that invokes nothing -- the form that genuinely
# cannot work. `VAR=1 <cmd>` is ALLOWED (the variable does reach <cmd>), so the
# message must not tell the operator to avoid it: the previous wording forbade
# `VAR=1 <cmd>` and then prescribed `VAR=1 claude`, which is that same form, so
# the remedy contradicted the prohibition and the rule denied the command it
# told you to run. Name the narrow thing that is actually refused.
HARNESS_ENV_PREFIX_INLINE = (
    f"This harness env var ({_maintenance_mode.ENV_VAR}, ESPALIER_STOP_GATE) "
    "assignment is blocked because it reaches nothing useful: each hook process "
    "reads these when it starts, so an assignment that runs no command changes "
    "nothing, and it can never reach the hooks of the session you are already "
    "in. Launching `claude` with one is blocked for a different and stronger "
    "reason -- it starts a NESTED session with the protected-zone check already "
    "bypassed, so this raises the cost of spawning an agent that skips the "
    "guard. Like the rest of this layer it is friction, not a sandbox: "
    "obfuscated spellings stay out of scope (docs/SHARP_EDGES.md)."
    "\n  Don't: assign one on its own -- "
    f"`{_maintenance_mode.ENV_VAR}=1`, `export {_maintenance_mode.ENV_VAR}=1`, "
    "or with `&&`/`;` before the next command, where past a separator the "
    "variable is not passed on either -- and don't launch `claude` with one "
    f"(`{_maintenance_mode.ENV_VAR}=1 claude -p ...`, or behind a wrapper such "
    "as `npx`/`nohup`/`sh -c`, which are refused the same way)."
    "\n  Do: prefix the command you actually want it for, which works and is "
    f"allowed -- `{_maintenance_mode.ENV_VAR}=1 pytest -q`, and the same "
    "prefix works on whatever command you use to drive a hook you just "
    "edited. To change the CURRENT session, exit and relaunch from your "
    f"own terminal with {_maintenance_mode.relaunch_hint()}, "
    "which keeps the session you are in -- a bare relaunch starts a new "
    "blueprint node and a fresh conversation. See CLAUDE.md "
    "\"Maintenance mode\" section."
)

# ── plan_guard reason templates ──────────────────────────────────────

NO_ACTIVE_PLAN_FILE = (
    "No active execution plan ({state}). Mutation requires "
    "status='in_progress'; a completed, planned, or cancelled plan does "
    "NOT authorize new writes."
    "\n  Don't: edit source files directly hoping the gate is advisory -- "
    "it's mechanical (PreToolUse deny). Repeated edits won't tire it out."
    "\n  Do: `/implement-task \"<one-line description>\"` then proceed. "
    "Use `/implement-task --multi` for coordinated multi-phase work. "
    "`/accomplish` remains a compatibility alias for --multi."
    " (attempted: {path}){exempt_hint}"
)

NO_ACTIVE_PLAN_BASH = (
    "No active execution plan ({state}). Mutation requires "
    "status='in_progress'; a completed, planned, or cancelled plan does "
    "NOT authorize new writes."
    "\n  Don't: bypass via Bash write-intent (`echo X > src/y.py`, "
    "`cat <<EOF >`, redirected heredocs) -- write_guard catches the "
    "pattern."
    "\n  Do: open a plan with `/implement-task` (`--multi` for multi-phase; "
    "`/accomplish` alias) then run the edit."
    "{exempt_hint}"
)

PLAN_GUARD_INTERNAL_ERROR = "plan_guard internal error; failing closed"

# ── config_guard reason templates ────────────────────────────────────

CONFIG_GUARD_INTERNAL_ERROR = "config_guard internal error; failing closed"

# ── stop_gate reason templates (per gate) ────────────────────────────

# Fail-CLOSED umbrella reason. stop_gate is a blocking Stop hook, so an uncaught
# crash re-blocks (rather than failing open with the gates unrun). Diagnostic --
# reports a fault, so excluded from the operator-facing wrong/right-shape
# contract (same class as the other *_INTERNAL_ERROR).
STOP_GATE_INTERNAL_ERROR = (
    "stop_gate internal error; failing closed (re-blocking the Stop event): "
    "{error}"
)

GATE_PYTEST_FAILED = (
    "Tests are failing. Fix these failures before stopping:\n{tail}"
)

# env-override Gate 1 templates.
GATE_ENV_OVERRIDE_TIMEOUT = (
    "Gate 1 (env override): timeout running `{cmd}`"
)

GATE_ENV_OVERRIDE_FAILED = (
    "Gate 1 (env override) failed: `{cmd}` exited "
    "{returncode}.\n{tail}"
)

# The three hygiene-gate messages below spell a subagent dispatch ONE way --
# `the <name> subagent (subagent_type='<name>')` -- and name the one hand-written
# escape both gates honour: a record whose agent is "operator" and whose note
# says why. DEF-496: one of them used to name the docs-maintainer two ways in a
# paragraph (`@docs-maintainer` and `via the Task tool`), and the gate that
# reads these accepted either; the Task tool has since been renamed, and the
# @-mention form never carried its `@agent-` prefix. The parameter name is what
# survives a tool rename.

GATE_DOCS_REFRESH_NEEDED = (
    "Docs refresh needed before Claude Code stops: this session made 10 or "
    "more source writes and no docs refresh has run. Dispatch the "
    "`docs-maintainer` subagent (subagent_type='docs-maintainer') on the "
    "session's changes, then retry the Stop event."
    "\n  Don't: write `.espalier-state/docs_refreshed` by hand to skip the "
    "refresh -- the next session lands on stale docs and the drift compounds."
    "\n  Do: dispatch the `docs-maintainer` subagent "
    "(subagent_type='docs-maintainer'), review its proposed edits, then retry "
    "the Stop event. If the docs are genuinely current, record that judgement "
    "instead -- write `.espalier-state/docs_refreshed` as "
    "{\"agent\": \"operator\", \"note\": \"<a sentence saying why nothing needed refreshing>\"}; "
    "that is a judgement you are recording, not a gate you are skipping, and "
    "the gate says so on stderr when it honours one."
)

GATE_DOCS_REFRESH_NO_CHANGES = (
    "The docs-maintainer ran but changed no documentation, so the docs "
    "refresh gate is not satisfied: the record says the subagent ran, and "
    "the gate reads the changed docs it lists -- the agent completing is not "
    "the same as the docs being refreshed."
    "\n  Don't: re-run the same subagent expecting a different result -- if it "
    "was denied, or found nothing to do, running it again reproduces this."
    "\n  Do: check whether its edits were blocked (see the deny messages in "
    "this session), or make the doc changes this session's work actually "
    "requires. If the docs are genuinely current, record that judgement -- "
    "write `.espalier-state/docs_refreshed` as "
    "{\"agent\": \"operator\", \"note\": \"<a sentence saying why nothing needed refreshing>\"}; "
    "that is a judgement you are recording, not a gate you are skipping, and "
    "the gate says so on stderr when it honours one."
)

GATE_CODE_REVIEW_BLOCK = (
    "Code review needed before Claude Code stops: this session made 10 or "
    "more source writes and no code review has run -- the review must be "
    "dispatched, not merely asked for. Dispatch the `code-reviewer` subagent "
    "(subagent_type='code-reviewer') on the session's diff, then retry the "
    "Stop event; the gate relieves when that subagent finishes, and "
    "`.espalier-state/code_reviewed` records which agent ran and what it "
    "concluded."
    "\n  Don't: write `.espalier-state/code_reviewed` by hand to skip the "
    "review -- you lose the second pair of eyes the harness was holding for."
    "\n  Do: dispatch the `code-reviewer` subagent "
    "(subagent_type='code-reviewer') on this session's diff, address any "
    "BLOCK findings, then Stop again. If the diff was reviewed another way, "
    "record that judgement instead -- write `.espalier-state/code_reviewed` "
    "as {\"agent\": \"operator\", \"note\": \"<a sentence saying how it was reviewed>\"}; "
    "that is a judgement you are recording, not a gate you are skipping, and "
    "the gate says so on stderr when it honours one."
)

# Either hygiene gate, when its flag file exists but is not a relief record:
# empty, not JSON, not an object, an operator record whose note is blank or a
# word, or a record naming an agent the table does not map to the gate. The
# no-changes message above describes an agent run; for these states none
# happened, and saying so is the difference between a fix and a loop.
GATE_RELIEF_RECORD_INVALID = (
    "`.espalier-state/{flag}` exists but is not a relief record: {why}. The "
    "gate reads the JSON object the SubagentStop hook writes when the mapped "
    "subagent finishes, or a hand-recorded judgement; a file that is neither "
    "must be replaced by one that is."
    "\n  Don't: touch the file, or write a one-word note, to get past the "
    "gate -- the record is the evidence the gate exists to hold you to."
    "\n  Do: dispatch the subagent the gate names (the Stop message before "
    "this one, or docs/HOOKS.md gates 2 and 3), or record a real judgement: "
    "write the file as {{\"agent\": \"operator\", \"note\": \"<a sentence "
    "saying why>\"}} and Stop again."
)


# ── operator-facing templates registry ──────────────────────────────
# Templates that name a path forward (instructional, not diagnostic).
# Each MUST model both the wrong-shape and the right-shape per §1.6
# habit-formation contract -- enforced by
# tests/test_denial_reasons.py::TestOperatorFacingTemplatesPairWrongAndRight.
# Diagnostic templates (MALFORMED_*, *_INTERNAL_ERROR,
# GATE_PYTEST_FAILED, GATE_ENV_OVERRIDE_*, and the DANGEROUS_*_FALLBACK
# hard-stops except DANGEROUS_PS_PATTERN_FALLBACK) are excluded -- they
# lack the Don't/Do habit-pair. The PS dangerous-command fallback is the
# one restructured as a Don't/Do pair (the Bash fallback names a "narrow
# the target" remediation too, but as a single sentence with no markers,
# so it stays out of the paired registry), so it joins the both-markers
# + actionability contracts and is registered below.
SECRET_PATH_ACCESS = (
    "Secret-path access blocked: {target} matches {shape}. Espalier denies "
    "these at the HOOK layer so an adopter's settings need no `Read()` deny "
    "rule -- a configured `Read()` rule makes Claude Code require static proof "
    "of every Bash command's read set, and any command it cannot prove (a "
    "`cd`, a relative glob, an unenumerable directory) raises a permission "
    "prompt that neither an allow rule nor bypassPermissions can suppress."
    "\n  Don't: read, copy, archive, link or rename `.env`, `secrets/`, or a "
    "credentials file from a session -- whatever is read is persisted to the "
    "transcript on disk, sent to the API, and may reach a committed blueprint "
    "or memory row, and a copy or a rename lands the same bytes at a path "
    "nothing guards."
    "\n  Do: narrow the target to the specific non-secret file you need, ask "
    "the operator to paste just the one value, or move the file from your "
    "own terminal."
)


_OPERATOR_FACING_TEMPLATES: tuple[str, ...] = (
    "PROTECTED_ZONE_WRITE",
    "PROTECTED_ZONE_MUTATION",
    "KILL_SWITCH_DETECTED",
    "SECRET_PATH_ACCESS",
    "HARNESS_ENV_PREFIX_INLINE",
    "NO_ACTIVE_PLAN_FILE",
    "NO_ACTIVE_PLAN_BASH",
    "GATE_DOCS_REFRESH_NEEDED",
    "GATE_DOCS_REFRESH_NO_CHANGES",
    "GATE_CODE_REVIEW_BLOCK",
    "GATE_RELIEF_RECORD_INVALID",
    # The PowerShell dangerous-command fallback now carries a Don't/Do
    # way-forward (was a raw-regex-leaking diagnostic) -- under the
    # both-markers + actionability contracts going forward.
    "DANGEROUS_PS_PATTERN_FALLBACK",
)

#: Reasons whose deny/block is FAIL-CLOSED because the hook could not read or
#: verify its payload, so no governance rule matched and there is no denial to
#: record in the audit log. A CRASH is not one of these: every BLOCKING hook's
#: crash guard (the four that define a ``deny``/``block``; the reporter hooks
#: fail open and log nothing) writes its own record
#: (``*_blocked_internal_error``, the exception's
#: class and never its message) before it emits, because the block that
#: strands an operator is the one they most need to find in ``/status --log``
#: afterwards (DEF-803; three Stop blocks on the Windows host 2026-09-14, two
#: in the log). Every OTHER bare ``deny``/``block`` in a hook must be audited --
#: the governance audit-log contract test discovers the sites, consumes this
#: set, and reds when a member here is no longer used by any site. Lives in
#: the shipped tree on purpose: widening it means editing a protected hook
#: file, in view of the reviewer and the gate-weakening speed bump, not a
#: test file.
FAIL_CLOSED_REASONS: frozenset[str] = frozenset({
    "MALFORMED_WRITE_PAYLOAD",
    "MALFORMED_MCP_PAYLOAD",
    "MCP_PAYLOAD_UNVERIFIABLE",
})


# ── helpers ──────────────────────────────────────────────────────────

def format_dangerous_bash(pid: str) -> str:
    """Compose DANGEROUS_BASH_PATTERN_FALLBACK from a record pid. Helper exists
    so callers pass the stable pid, not the raw regex source."""
    what = DANGEROUS_BASH_PLAIN.get(pid, "a dangerous command pattern")
    return DANGEROUS_BASH_PATTERN_FALLBACK.format(what=what)


def format_dangerous_ps(pid: str) -> str:
    """Compose DANGEROUS_PS_PATTERN_FALLBACK from a record pid. Helper exists
    so callers pass the stable pid, not the raw regex source -- parity with
    format_dangerous_bash; the raw regex must never reach operator-facing text."""
    what = DANGEROUS_PS_PLAIN.get(pid, "a dangerous command pattern")
    return DANGEROUS_PS_PATTERN_FALLBACK.format(what=what)
