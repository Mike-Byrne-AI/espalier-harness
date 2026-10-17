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

import sys
from pathlib import Path
from typing import NoReturn

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

# The one remedy for a harness-path collision (DEF-910): an adopter's own
# source that merely shares a harness path's name (a top-level `cc/`) is
# relocated from their own terminal; maintenance mode is for editing the
# HARNESS and is not the remedy for that. Composed into every harness-zone
# template -- the Write / Edit and PowerShell pair, the Bash and MCP one-liners,
# the symlink and hardlink ones -- and kept off the adopter's own templates
# below. Until 2026-10-16 only the full pair carried it, each its own copy.
_NAME_COLLISION_WRITE: str = (
    "\n  Your own source colliding with a harness path (e.g. a top-level "
    "`cc/`)? Relocate it from your own terminal, outside a Claude Code "
    "session (the guard reads tool calls, not your shell) -- maintenance "
    "mode is not the remedy for that."
)
# The delete / move twin: a move of the colliding directory is itself refused.
_NAME_COLLISION_MUTATION: str = (
    "\n  Your own source colliding with a harness path (e.g. a top-level "
    "`cc/`)? Relocate it from your own terminal, outside a Claude Code "
    "session (the guard reads tool calls, not your shell -- and a move of "
    "that directory is itself a refused row) -- maintenance mode is not the "
    "remedy for that."
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
) + _NAME_COLLISION_WRITE

# The adopter's OWN zones -- a path their espalier.toml names under
# ``protected_paths`` ("never touch") or ``generated_paths`` ("regenerate; do not
# hand-edit"), read by write_guard since DEF-951 closed. Their own templates,
# literal like every operator-facing one (the tests read these constants as
# text): the harness pair's remedy, a maintenance-mode relaunch, is the wrong
# move for a user's own tree, and it also switches this check off for the
# session. ``write_guard._zone_template`` picks the template for the zone;
# ``{hint}`` is ADOPTER_ZONE_HINT, which names the key and the zone.
ADOPTER_ZONE_WRITE_PROTECTED = (
    "Write to protected zone blocked: {path}.{hint}"
    "\n  Don't: relaunch in maintenance mode for this -- it is for editing the "
    "harness, and it switches this check off for the whole session."
    "\n  Do: write elsewhere, or change the `protected_paths` entry in "
    "espalier.toml from your own terminal if this zone should open; "
    "`/status --explain <path>` shows which zone covers a path."
)
ADOPTER_ZONE_WRITE_GENERATED = (
    "Write to protected zone blocked: {path}.{hint}"
    "\n  Don't: relaunch in maintenance mode for this -- it is for editing the "
    "harness, and it switches this check off for the whole session."
    "\n  Do: run the generator (a build step's own Bash write or delete here is "
    "not refused), or drop the `generated_paths` entry in espalier.toml if "
    "this file is maintained by hand; `/status --explain <path>` shows which "
    "zone covers a path."
)
ADOPTER_ZONE_MUTATION = (
    "{effect} of protected zone blocked: {path}.{hint}"
    "\n  Don't: relaunch in maintenance mode for this -- it is for editing the "
    "harness, and it switches this check off for the whole session."
    "\n  Do: leave the zone in place, or change the `protected_paths` entry in "
    "espalier.toml from your own terminal if this zone should open; "
    "`/status --explain <path>` shows which zone covers a path."
)

PROTECTED_ZONE_WRITE_BASH = (
    "Bash write to protected harness zone blocked: {path}.{hint}"
) + _NAME_COLLISION_WRITE

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
) + _NAME_COLLISION_MUTATION

PROTECTED_ZONE_MUTATION_BASH = (
    "Bash {effect} of protected harness zone blocked: {path}.{hint}"
) + _NAME_COLLISION_MUTATION

PROTECTED_ZONE_WRITE_MCP = (
    "Write to protected harness zone blocked: {path} (via mcp tool "
    "{tool_name}, field {field_name}).{hint}"
) + _NAME_COLLISION_WRITE

# The way-forward clause a zone deny carries when the zone is the ADOPTER'S
# OWN -- a path their espalier.toml names under ``protected_paths`` ("never
# touch") or ``generated_paths`` ("regenerate; do not hand-edit"), read by
# write_guard since DEF-951 closed. Substituted for the maintenance-mode hint
# by ``write_guard._zone_hint``: telling a user to relaunch in maintenance mode
# to write into their own tree is the wrong remedy, and that mode also
# switches this check off for the session.
ADOPTER_ZONE_HINT = (
    " This zone is YOURS, not the harness's: your espalier.toml names `{zone}` "
    "under `{key}` ({kind_text})."
)
ADOPTER_ZONE_KIND_TEXT = {
    "protected": "never touch",
    "generated": "generated; regenerate, do not hand-edit",
}

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
) + _NAME_COLLISION_WRITE

# MCP / PowerShell symlink-creation twins of the Bash check. A symlink may
# NEVER land in a governed zone (protected OR allowlisted-in-protected)
# regardless of channel -- a stray symlink would silently redirect a later
# harness read to off-path content (e.g. a swapped cc/execution_plan.json).
# De-prioritized defense-in-depth: kept (deleting fails toward over-protect),
# but no self-user reaches it by mistake.
PROTECTED_ZONE_SYMLINK_MCP = (
    "MCP symlink creation into protected harness zone blocked: {path} "
    "(via mcp tool {tool_name}; symlinks bypass the file-path allowlist by design)"
) + _NAME_COLLISION_WRITE
PROTECTED_ZONE_SYMLINK_PS = (
    "PowerShell symlink creation into protected harness zone blocked: {path} "
    "(symlinks bypass the file-path allowlist by design)"
) + _NAME_COLLISION_WRITE

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
) + _NAME_COLLISION_WRITE
PROTECTED_ZONE_HARDLINK_INODE = (
    "Write to a hardlink alias of a protected harness file blocked: {path} "
    "(its inode matches a protected file; the write would rewrite protected bytes)"
) + _NAME_COLLISION_WRITE

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
#
# What every recursive-delete wall text says is NOT refused, and which of it
# the speed bump still asks about -- ONE fragment for the seven texts that
# carry it. Until 2026-10-07 they said "most draw one confirm-by-re-issue
# nudge" of all three classes, and a path below a temp root drew it; the
# temp-root carve-out (`_bash_patterns.below_a_temp_root`) passes scratch
# that holds no git checkout. Annotated, so the dead-template contract reads
# it as a fragment, not a template a hook must name.
_NOT_REFUSED_HERE: str = (
    "a path inside the repo or inside your home directory, or under a temp "
    "root, is not refused here (scratch below a temp root that is no git "
    "checkout, and a relative build/ or dist/, pass without a nudge; the "
    "rest draw one confirm-by-re-issue nudge)"
)
DANGEROUS_BASH_PATTERN_FALLBACK = (
    "Dangerous command blocked: {what}. If this was a deliberate, scoped "
    "cleanup, narrow the target to the directory you mean: "
    + _NOT_REFUSED_HERE
    + "; the filesystem root, your home directory or the "
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
#: What both tools' meaning judges read as a shallow system path, ONE
#: fragment for every wall text that names it: until DEF-1041 the Bash
#: texts named /etc and /usr/local only, while the Bash judge now walls a
#: drive path two levels below its drive as the PowerShell one does.
#: Annotated, so the dead-template contract reads it as a fragment.
_SHALLOW_SYSTEM_PATHS: str = (
    "a shallow system path such as /etc or /usr/local, a path two or fewer "
    "levels below a drive root outside the repo, your home directory and "
    "the temp roots (C:/Windows/System32, C:/work/old)"
)

CATASTROPHIC_RM = (
    "Dangerous command blocked: recursive delete, forced or not, of a "
    "catastrophic target -- the filesystem root, your home "
    "directory or the repo (or a parent of either), " + _SHALLOW_SYSTEM_PATHS
    + ", or an absolute path with a '..' step -- "
    "detected in any flag order, by rm or by cmd.exe's own rd /s, rmdir /s, "
    "del /s or erase /s in a program cmd /c runs (cmd's %USERPROFILE% read "
    "as your home directory); a relative target is read from the directory "
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
    "mean: " + _NOT_REFUSED_HERE + "."
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
    "(or a parent of either), " + _SHALLOW_SYSTEM_PATHS + ", or an absolute "
    "path with a '..' step; a relative root is "
    "read from the directory the command runs in, after its own cd, and a "
    "bare '*' glob root is refused wherever it runs (root the walk at . or a "
    "named directory instead). "
    "Un-narrowed, the walk takes every file under the root, hooks included, "
    "so this is a hard safety stop (maintenance mode does not bypass it). To "
    "proceed, narrow the walk with a -name, -path or -regex predicate placed "
    "before the action, or root it at the directory you mean: "
    + _NOT_REFUSED_HERE + "."
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
    "your home directory or the repo (or a parent of either), "
    + _SHALLOW_SYSTEM_PATHS + ", or an absolute path with a '..' "
    "step; a relative root is read from the directory the command runs in, "
    "after its own cd, and a bare '*' glob root is refused wherever it runs "
    "(a pipeline or a loop is never a plain command). "
    "The enumerator hands the remove verb every path under "
    "the root, hooks included, so this is a hard safety stop (maintenance "
    "mode does not bypass it). To proceed, narrow the enumeration with a "
    "-name, -path or -regex predicate, a bounded wildcard or a bounded "
    "pathspec, or root it at "
    "the directory you mean: " + _NOT_REFUSED_HERE + "."
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
    "your home directory or the repo (or a parent of either), "
    + _SHALLOW_SYSTEM_PATHS + ", or an absolute path with a '..' "
    "step; a relative root is read from the directory the command runs in, "
    "after its own cd, and a bare '*' glob root is refused wherever it runs "
    "(a pipeline or a loop is never a plain command). "
    "The loop hands the remove verb every path under the "
    "root one per turn, or each listed entry to recurse into, hooks included, "
    "so this is a hard safety stop (maintenance mode does not bypass it). To "
    "proceed, narrow the enumeration with a -name, -path or -regex predicate, "
    "a bounded wildcard or a bounded pathspec, list only the entries you mean "
    "(for f in build/* draws one confirm-by-re-issue nudge, since the loop "
    "removes a variable), or root it at the directory you mean: "
    + _NOT_REFUSED_HERE + "."
)

# What the PowerShell tool's judge (`_bash_patterns._ps_sweep_root_is_catastrophic`,
# behind the recursive remove without the force switch and the sweeps) walls
# by target -- ONE phrase, so the two wall texts below and the forced form's
# drop -Force remedy cannot drift apart: that remedy promised one nudge for
# every path but a drive root, the home directory and the repo while the
# unforced judge walled every path two or fewer levels below a drive root
# outside the repo and the home directory (DEF-1042, driven on Windows
# 2026-10-01). Annotated, so the dead-template contract reads it as the
# fragment it is, not a template a hook must name. Forward slashes: a
# backslash in a PowerShell reason reads as a leaked regex there.
_PS_CATASTROPHIC_TARGETS: str = (
    "the filesystem root or a drive root, your home directory or the repo "
    "(or a parent of either), " + _SHALLOW_SYSTEM_PATHS + ", an absolute "
    "path with a '..' step"
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
    "recursive .NET directory delete -- rooted at a catastrophic target: "
    + _PS_CATASTROPHIC_TARGETS
    + ", or a root the guard cannot read (a variable, a backtick); a "
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
    "mean: " + _NOT_REFUSED_HERE + "."
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
    "any alias or unambiguous switch prefix, the native rm -r by its name, "
    "file name or path -- rm.exe, /bin/rm -- or cmd.exe's own rd /s, "
    "rmdir /s, del /s or erase /s in a program cmd /c runs), forced or not, "
    "of a catastrophic target: "
    + _PS_CATASTROPHIC_TARGETS
    + ", a "
    "variable that names the home directory ($HOME, $env:USERPROFILE, cmd's "
    "%USERPROFILE%), or a "
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
    "the directory you mean: " + _NOT_REFUSED_HERE + "."
)

# Plain-English descriptions keyed by PS record pid -- the operator sees
# intent, never the raw regex source (parity with DANGEROUS_BASH_PLAIN).
DANGEROUS_PS_PLAIN = {
    "ps-remove-item-recurse-force-prefix": (
        "a recursive force-delete via Remove-Item -Recurse -Force (by any "
        "alias, or the native rm -rf by its name, file name or path)"
    ),
    "ps-remove-item-recurse-force-mixed": (
        "a recursive force-delete via Remove-Item with -Recurse and -Force (by "
        "any alias, or the native rm -rf by its name, file name or path)"
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
    "absolute, variable or otherwise unreadable target, or a wildcard "
    "anywhere but the two places below, so re-pointing it at another such "
    "path will not clear this deny; a plainly relative target inside the "
    "repo (a bare leading '*' in a plain command is read as the directory it "
    "expands in) draws one confirm-by-re-issue nudge instead, a wildcard "
    "after a build directory on the ephemeral roster (build/*) is read as "
    "that directory, and a "
    "literal path below a temp directory (your TEMP directory, a drive-root "
    "tmp or temp, /tmp) passes without one unless it is a git checkout; an "
    "array is judged element by element, each by the rule it meets. If you "
    "drop -Force, the remove is judged by what its target "
    "names from where it runs: "
    + _PS_CATASTROPHIC_TARGETS
    + ", your home directory by ~, $HOME or $env:USERPROFILE, and a bare "
    "'*' or $PWD read as the location itself are refused, scratch below a "
    "temp root passes, and any other path or variable draws one nudge -- "
    "and without -Force it "
    "still removes every item that is not hidden or read-only, with no "
    "prompt, so confirm the target before you re-issue."
)

WRITE_GUARD_INTERNAL_ERROR = (
    "write_guard internal error; failing closed."
    " Re-issue once; if every call is denied the guard is wedged: `/status --log` counts it, and the repair is made from a terminal outside this session."
)

# write_guard's own time budget ran out before its judgment did (DEF-1160).
# Claude Code cancels a PreToolUse command hook at its wired timeout and a
# cancelled hook does not block, so the guard refuses at a budget below that
# timeout rather than let the call through unjudged. Carried like every
# other deny, one stdout JSON object through the audited funnel. {budget}
# is the budget in seconds.
WRITE_GUARD_TIME_BUDGET = (
    "Command blocked: write_guard could not finish judging this command within"
    " its {budget} s time budget, so the call is refused rather than let"
    " through unjudged."
    "\n  Don't: re-issue the same command unchanged -- a command this long runs"
    " out of time again."
    "\n  Do: split it into shorter commands (a long generated list of paths in"
    " batches of a hundred or two), each judged on its own."
)

KILL_SWITCH_DETECTED = (
    "Espalier-Harness kill-switch setting detected{context}: {findings}. "
    "Remove the setting and run `espalier integrity verify .` before "
    "continuing."
    "\n  Don't: set `disableAllHooks: true` (or analogous kill-switches) "
    "to silence a hook that's firing inconveniently: {ci_clause}"
    "\n  Do: remove the offending setting shown above ({findings}) "
    "-- or restore the hooks block -- to undo it, then identify what the hook "
    "flagged and fix the root cause, or file a tracked issue if the hook is wrong."
)

# KILL_SWITCH_DETECTED's {ci_clause}, and the SessionStart kill-switch WARN's:
# what still re-checks the setting once local hooks are off. Chosen by
# `kill_switch_ci_clause` on whether the CI gate's files are on disk: plain
# `init` installs no CI gate, and "CI will still fail the merge" told an adopter
# without one something false. Two files on disk prove the gate is installed,
# not that a host runs it, so the present text says no more than that.
KILL_SWITCH_CI_GATE_PRESENT = (
    "the CI gate is installed here, so wherever its workflow runs a pull request "
    "is re-checked regardless of the local setting."
)
KILL_SWITCH_CI_GATE_ABSENT = (
    "nothing downstream re-checks this repository: no CI gate is installed "
    "(`espalier install-ci` adds one)."
)

#: The files ``espalier install-ci`` writes that make the CI gate: the guard and
#: the workflow that runs it. Plain ``init`` writes neither. Pinned to the
#: engine's ``managed_inventory.get_install_ci_artifacts()`` (less its ``.new``
#: parity twin) by ``tests/test_hooks.py``.
CI_GATE_FILES: tuple[str, ...] = ("tools/cc/ci_guard.py", ".github/workflows/harness-guard.yml")


def kill_switch_ci_clause(root: Path) -> str:
    """The clause that is true of ``root``'s CI gate (see the two texts above).
    Callers read this function with a fallback, so a kept copy of this module
    that predates it costs the clause, never the deny or the warning."""
    try:
        present = all((root / rel).is_file() for rel in CI_GATE_FILES)
    except OSError:  # fail-open: ok deliberate -- an unreadable tree is told no CI gate re-checks it, the claim that cannot mislead
        present = False
    return KILL_SWITCH_CI_GATE_PRESENT if present else KILL_SWITCH_CI_GATE_ABSENT

# A project settings change that unwires a governance gate the
# session runs. Claude Code shows this reason to no one (the protocol pin); the
# same route reaches Claude through the next PostToolUse
# (``_integrity.take_unwired_notice``), and this text is what the debug log and
# the audit record keep.
GOVERNANCE_GATES_UNWIRED = (
    "Espalier-Harness blocked a project settings change that leaves governance "
    "gates unwired: {findings}. This session keeps its hooks, but the file on "
    "disk keeps the change, so the next session starts without those gates."
    "\n  Don't: remove the hooks block or delete .claude/settings.json to quiet "
    "a hook mid-session -- that switches every gate off at once."
    "\n  Do: run `espalier merge-settings --repair` to wire the gates back "
    "(`espalier init .` instead if the file was deleted), then `espalier doctor`."
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
    f"(`{_maintenance_mode.ENV_VAR}=1 claude -p ...`, behind a wrapper such "
    "as `npx`/`nohup`/`sh -c`, or after a `set` of one inside `cmd /c`, which "
    "are refused the same way)."
    "\n  Do: prefix the command you actually want it for, which works and is "
    f"allowed -- `{_maintenance_mode.ENV_VAR}=1 pytest -q`, and the same "
    "prefix works on whatever command you use to drive a hook you just "
    "edited. To change the CURRENT session, exit and relaunch from your "
    f"own terminal with {_maintenance_mode.relaunch_hint()}, "
    "which keeps the session you are in -- a bare relaunch starts a new "
    "blueprint node and a fresh conversation -- and verify it before "
    "retrying: the relaunched session's SessionStart banner reads "
    "MAINTENANCE=on. See docs/HOOKS.md \"Maintenance mode\"."
)

# ── plan_guard reason templates ──────────────────────────────────────

NO_ACTIVE_PLAN_FILE = (
    "No active execution plan ({state}). Mutation requires "
    "status='in_progress'; a completed, planned, or cancelled plan does "
    "NOT authorize new writes."
    "\n  Don't: edit source files directly hoping the gate is advisory -- "
    "it's mechanical (PreToolUse deny). Repeated edits won't tire it out."
    "\n  Do: `/implement-task \"<one-line description>\"` then proceed. "
    "Use `/implement-task --multi` for coordinated multi-phase work."
    " (attempted: {path}){exempt_hint}"
)

NO_ACTIVE_PLAN_BASH = (
    "No active execution plan ({state}). Mutation requires "
    "status='in_progress'; a completed, planned, or cancelled plan does "
    "NOT authorize new writes."
    "\n  Don't: bypass via Bash write-intent (`echo X > src/y.py`, "
    "`cat <<EOF >`, redirected heredocs) -- write_guard catches the "
    "pattern."
    "\n  Do: open a plan with `/implement-task` (`--multi` for multi-phase) "
    "then run the edit."
    "{exempt_hint}"
)

PLAN_GUARD_INTERNAL_ERROR = (
    "plan_guard internal error; failing closed."
    " Re-issue once; if every call is denied the guard is wedged: `/status --log` counts it, and the repair is made from a terminal outside this session."
)

# ── config_guard reason templates ────────────────────────────────────

CONFIG_GUARD_INTERNAL_ERROR = (
    "config_guard internal error; failing closed."
    " Re-issue once; if every call is denied the guard is wedged: `/status --log` counts it, and the repair is made from a terminal outside this session."
)

# ── stop_gate reason templates (per gate) ────────────────────────────

# Fail-CLOSED umbrella reason. stop_gate is a blocking Stop hook, so an uncaught
# crash re-blocks (rather than failing open with the gates unrun). Diagnostic --
# reports a fault, so excluded from the operator-facing wrong/right-shape
# contract (same class as the other *_INTERNAL_ERROR).
STOP_GATE_INTERNAL_ERROR = (
    "stop_gate internal error; failing closed (re-blocking the Stop event): "
    "{error}."
    " Re-issue once; if every Stop is blocked the gate is wedged: "
    "`/status --log` counts it, and the repair is made from a terminal outside this session."
)

GATE_PYTEST_FAILED = (
    "Tests are failing. Fix these failures before stopping:\n{tail}"
)

# env-override Gate 1 templates.
GATE_COMMAND_TIMEOUT = (
    "Gate 1 ({source}): timeout running `{cmd}` after {budget}s, the gate's "
    "STOP_INNER_BUDGET. A gate green because it ran out of time is no gate, so "
    "this blocks.\n"
    "Do: {do}"
)

# The Do line of GATE_COMMAND_TIMEOUT per source: the command that ran out
# of time is changed where it lives, not declared again.
GATE_COMMAND_TIMEOUT_DO_ENV = (
    "give Gate 1 a faster command where the variable is set (the shell that "
    "launches Claude Code): one directory, a marker, `-x`; the change takes "
    "effect at the next launch. ESPALIER_STOP_GATE set to light at the next launch "
    "turns the gate off."
)
GATE_COMMAND_TIMEOUT_DO_TOML = (
    "narrow the `test` entry under [extra_actions] in espalier.toml to what "
    "proves a change (one directory, a marker, `-x`); the hook reads the file on "
    "every Stop, so the change is live at once (from this session the edit needs "
    "an execution plan: /implement-task). ESPALIER_STOP_GATE set to light at the next "
    "launch turns the gate off."
)
GATE_COMMAND_TIMEOUT_DO_FINGERPRINT = (
    "declare a faster command as [extra_actions] test in espalier.toml (read on "
    "every Stop), or set ESPALIER_STOP_GATE_TEST_CMD in the shell that launches "
    "Claude Code; ESPALIER_STOP_GATE set to light at the next launch turns the gate off."
)

GATE_COMMAND_FAILED = (
    "Gate 1 ({source}) failed: `{cmd}` exited "
    "{returncode}.\n{tail}"
)

# The override could not be STARTED. The command is configuration the operator
# wrote, so the failure recurs on every Stop and is not the passing
# infrastructure fault the pytest branch allows on: it blocks, naming the
# token that did not resolve and the platform's own remedy.
#
# ONCE A SESSION, and the text says so. The variable is read when Claude Code
# launches, so nothing done inside the session can clear this; blocking every
# Stop would return at Gate 1 every turn and the gates behind it (docs,
# review, the blueprint finalize) would not run again until the next launch.
#
# The habit pair is for the reader this reason most often has: the agent, in
# the continuation turn. The only shell it can reach is its own tool, where an
# export never reaches a hook -- it would report the gate fixed and the next
# session would block again -- and the `env` block of a settings file is
# writable and changes every session that reads the file.
GATE_COMMAND_SPAWN_FAILED = (
    "Stop blocked once: the test gate could not start `{cmd}` "
    "({error_class}: {error_text}). {resolution}, "
    "so the gate armed by {source} is not running. It is "
    "started without a shell, at the repository root. This is reported once "
    "a session; later Stops run the other gates without the test gate.\n"
    "Don't: {dont}\n"
    "Do: {do}"
)

# The Don't line of GATE_COMMAND_SPAWN_FAILED, per source of the command.
GATE_COMMAND_DONT_ENV = (
    "set, unset or export ESPALIER_STOP_GATE_TEST_CMD from this session. The "
    "hooks read it when Claude Code launches, so a change made here never reaches "
    "them, and an `env` edit in a settings file changes every session that reads "
    "that file."
)
GATE_COMMAND_DONT_TOML = (
    "re-issue the Stop without respelling the entry, or write a relief record by "
    "hand; the hook re-reads espalier.toml on every Stop, so the respelling is "
    "what clears this."
)
GATE_COMMAND_DONT_FINGERPRINT = (
    "set or export ESPALIER_STOP_GATE_TEST_CMD from this session: the hooks read "
    "it when Claude Code launches, so a change made here never reaches them; the "
    "declared key in espalier.toml is read on every Stop."
)

# The Do line of GATE_COMMAND_SPAWN_FAILED, per source of the command (the
# runner picks one and fills {remedy} with the platform's): the override is
# changed where it was set and read at the next launch; a declared or detected
# command is re-read on every Stop, so its respelling is live at once.
GATE_COMMAND_DO_ENV = (
    "tell the operator the test gate is not running, and how to respell "
    "ESPALIER_STOP_GATE_TEST_CMD. {remedy} It is changed where it was set (the shell that "
    "launches Claude Code, or the `env` block of a settings file) and takes "
    "effect at the next launch."
)
GATE_COMMAND_DO_TOML = (
    "respell the `test` entry under [extra_actions] in espalier.toml (from this "
    "session a root-file edit needs an execution plan: /implement-task; or tell "
    "the operator), or remove it to fall back to the detected command; the hook "
    "reads the file on every Stop, so the change is live at once. {remedy}"
)
GATE_COMMAND_DO_FINGERPRINT = (
    "declare the command that runs here as [extra_actions] test in "
    "espalier.toml (read on every Stop; from this session a root-file edit needs "
    "an execution plan: /implement-task), or tell the operator to set "
    "ESPALIER_STOP_GATE_TEST_CMD in the shell that launches Claude Code. {remedy}"
)

GATE_COMMAND_SPAWN_REMEDY_WINDOWS = (
    "On Windows a script shim (npm, npx, pnpm) is a .cmd file; the gate resolves "
    "it through PATHEXT, so a plain `npm test` starts when npm is on the PATH of "
    "the shell that launches Claude Code (spelling it `npm.cmd test` is no longer "
    "needed). If it resolved and still could not start, the shim's own error is "
    "the cause; an argument carrying a cmd metacharacter is refused before the "
    "shim can re-parse it."
)

GATE_COMMAND_SPAWN_REMEDY_QUOTING = (
    "The command has an unbalanced quote, so it cannot be split into a program "
    "and its arguments: fix the quoting where the variable is set."
)

GATE_COMMAND_SPAWN_REMEDY_SHELL_SYNTAX = (
    "Give the gate one program per entry: `test = [\"npm run build\", \"npm test\"]` "
    "runs each in order at the repository root (no `cd` is needed), or put the "
    "line in a script and name the script."
)
GATE_COMMAND_SPAWN_REMEDY_POSIX = (
    "Name a program that is on PATH for the shell that launches Claude Code, "
    "or give its full path."
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
    "the Stop event; a docs agent of this repository's own relieves the gate "
    "too once espalier.toml names it in `docs_refresh_agents`. If the docs are "
    "genuinely current, record that judgement "
    "instead -- write `.espalier-state/docs_refreshed` as "
    "{\"agent\": \"operator\", \"note\": \"<a sentence saying why nothing needed refreshing>\"}; "
    "that is a judgement you are recording, not a gate you are skipping, and "
    "the gate notes it in the debug log when it honours one."
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
    "the gate notes it in the debug log when it honours one."
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
    "BLOCK findings, then Stop again; a reviewer of this repository's own "
    "relieves the gate too once espalier.toml names it in `code_review_agents`. "
    "If the diff was reviewed another way, "
    "record that judgement instead -- write `.espalier-state/code_reviewed` "
    "as {\"agent\": \"operator\", \"note\": \"<a sentence saying how it was reviewed>\"}; "
    "that is a judgement you are recording, not a gate you are skipping, and "
    "the gate notes it in the debug log when it honours one."
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
# GATE_PYTEST_FAILED, GATE_COMMAND_*, and the DANGEROUS_*_FALLBACK
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
    # The adopter's own zones (espalier.toml): the same pair, the zone's remedy.
    "ADOPTER_ZONE_WRITE_PROTECTED",
    "ADOPTER_ZONE_WRITE_GENERATED",
    "ADOPTER_ZONE_MUTATION",
    "KILL_SWITCH_DETECTED",
    "GOVERNANCE_GATES_UNWIRED",
    "SECRET_PATH_ACCESS",
    "HARNESS_ENV_PREFIX_INLINE",
    "NO_ACTIVE_PLAN_FILE",
    "NO_ACTIVE_PLAN_BASH",
    "GATE_DOCS_REFRESH_NEEDED",
    "GATE_DOCS_REFRESH_NO_CHANGES",
    "GATE_CODE_REVIEW_BLOCK",
    "GATE_RELIEF_RECORD_INVALID",
    # The one Gate 1 reason that instructs rather than reports: nothing done
    # in the session clears it, so the wrong move is named beside the right
    # one. Its siblings (a failing command, a timeout) stay diagnostic.
    "GATE_COMMAND_SPAWN_FAILED",
    # The PowerShell dangerous-command fallback now carries a Don't/Do
    # way-forward (was a raw-regex-leaking diagnostic) -- under the
    # both-markers + actionability contracts going forward.
    "DANGEROUS_PS_PATTERN_FALLBACK",
    # The time-budget refusal: the wrong move (the same long command again)
    # times out again, so it is named beside the split that passes.
    "WRITE_GUARD_TIME_BUDGET",
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
# ── a deny hook that cannot start (DEF-1176, DEF-2010, DEF-4025) ─────
#: The structured refusals a deny hook emits when a sibling import fails at its
#: module top. Under the hook protocol an uncaught exit 1 is a NON-BLOCKING
#: error, so a guard that dies at import judges nothing (measured 2026-10-07
#: and 2026-10-10: every call proceeded unguarded); these are the fail-closed
#: shape instead. Two causes read differently (DEF-2010). A KEPT OLD HELPER: an
#: upgrade kept the tree's ``tools/cc/hooks/_hook_utils.py`` as the adopter's
#: (no managed marker) and regenerated the rest, which import a name the kept
#: copy lacks -- or, on a tree being edited, an edit removed the name or added
#: its import first. ANY OTHER RAISE: the file that raised is named, with its
#: line, and the upgrade is not offered, since it would regenerate the file
#: under edit (the 2026-10-14 and 10-16 lock-outs, each a sibling that raised
#: at import and a refusal that blamed the helper). Composed by
#: :func:`refuse_on_helper_skew` from this module and the standard library
#: alone, since any other sibling may be the one that failed. ``{hook}`` is
#: the hook's stem, ``{error}`` the exception's class and text, ``{restore}``
#: the repair (:func:`_restore_clause`).
HELPER_SKEW = (
    "{hook} cannot start: {taker} takes `{name}` from tools/cc/hooks/_hook_utils.py,"
    " which lacks it ({error}). If an upgrade kept _hook_utils.py as yours (no managed"
    " marker) and regenerated the rest: from a terminal, restore its `# espalier:managed`"
    " marker line and run `espalier upgrade --execute .`. If an edit in progress removed"
    " the name or added its import, restore the edited file to HEAD: {restore}. Every"
    " call this hook judges is refused until then."
)
SIBLING_RAISED = (
    "{hook} cannot start: {file} raised {error} at line {line} while the hook imported"
    " its siblings. No name is missing from tools/cc/hooks/_hook_utils.py, so this is"
    " not a kept old helper and `espalier upgrade` would not repair it. Restore the file"
    " to HEAD: {restore}. Every call this hook judges is refused until then."
)
#: The import failed in a file outside ``tools/cc/`` (never seen: the hook's
#: own frame is under it), so nothing is named to restore.
SIBLING_RAISED_UNPLACED = (
    "{hook} cannot start: a sibling import failed ({error}) and no file under"
    " tools/cc/ is on its traceback. Read the error from a terminal and repair the"
    " file it names. Every call this hook judges is refused until then."
)
#: The crash guard's text for a fault after the imports (DEF-4025's twin):
#: the class and the place, never the message (a message can quote a path or a
#: file's contents), as the record never carries it either.
WRITE_GUARD_CRASHED_AT = (
    "write_guard internal error ({error} at {file}:{line}); failing closed. Re-issue"
    " once. If every call is denied the guard is wedged, and if {file} is being"
    " edited, restore it to HEAD: {restore}. Otherwise `/status --log` counts it and"
    " the repair is made from a terminal outside this session."
)
#: The context of the one call a wedged PreToolUse hook lets through (DEF-4025):
#: a Bash call that is one command, a restore to HEAD of a file the refusal
#: names. No ``permissionDecision`` goes with it, so the operator's permission
#: mode decides the call as it would any other; the text reaches Claude.
WEDGE_RESTORE_CONTEXT = (
    "{hook} is wedged ({cause}), so it refuses every call but one: a restore to"
    " HEAD of a file its refusal names. This call restores {file}, so it was let"
    " through. {copy} The next call is judged by the restored hook; if it still"
    " cannot start, its refusal names what raised next."
)

#: The Bash command words a restore may not contain: a separator, a pipe, a
#: redirect, an expansion, a substitution, a glob, a group or a comment (a
#: second command, or an operand the shell would rewrite). Quotes and the
#: backslash are read as the shell reads them (``shlex``).
_RESTORE_SHELL_CHARS = frozenset(";&|<>$`(){}*?[]~!#\n\r\x00")
#: The longest restore command read; past it the call is refused unread.
_RESTORE_COMMAND_CAP = 4096
#: The deny hooks a Bash call reaches: ``write_guard`` is wired for every
#: tool; ``plan_guard`` matches Write, Edit and NotebookEdit, and the
#: ConfigChange and Stop hooks judge no tool call. Only these let a restore
#: through, and only their refusals offer one; the others name the terminal.
_LETS_A_RESTORE_THROUGH = frozenset({"write_guard"})


class _SkewReading:
    """What a failed start can say about itself: the file that raised (an
    absolute path under ``tools/cc/``) and its line, the helper name a sibling
    takes and ``_hook_utils`` lacks (the kept-old-helper test), and the files
    whose restore to HEAD the refusal names and lets through: the raising file
    first, then (on the kept-helper test) ``_hook_utils.py``, then every other
    ``tools/cc/`` file on the traceback, inner to outer."""

    def __init__(self, file: Path | None, line: int | None, missing: str | None,
                 restorable: list[Path], cc_dir: Path) -> None:
        self.file = file
        self.line = line
        self.missing = missing
        self.restorable = restorable
        self.cc_dir = cc_dir

    def rel(self, path: Path) -> str:
        """``path`` as the repository spells it, ``tools/cc/...``."""
        return "tools/cc/" + path.relative_to(self.cc_dir).as_posix()


def _under(path: Path, cc_dir: Path) -> bool:
    try:
        path.relative_to(cc_dir)
    # fail-open: ok deliberate a path outside tools/cc is an answer, not a fault
    except ValueError:
        return False
    return True


def _missing_helper_name(exc: BaseException) -> str | None:
    """The kept-old-helper test: the name a sibling takes from ``_hook_utils``
    that the loaded ``_hook_utils`` lacks, or None. Read from the exception's
    own fields (an ``ImportError`` from ``from _hook_utils import <name>``, an
    ``AttributeError`` on the ``_hook_utils`` module object), then checked
    against the module, so an error raised for any other reason never reads as
    a kept helper."""
    helper = sys.modules.get("_hook_utils")
    if helper is None:
        return None
    name: object = None
    if isinstance(exc, ImportError) and exc.name == "_hook_utils":
        name = getattr(exc, "name_from", None)
        if not isinstance(name, str):
            text = str(exc)
            if text.startswith("cannot import name '"):
                name = text[len("cannot import name '"):].split("'", 1)[0]
    elif isinstance(exc, AttributeError) and getattr(exc, "obj", None) is helper:
        name = exc.name
    if isinstance(name, str) and name and not hasattr(helper, name):
        return name
    return None


def wedge_reading(exc: BaseException) -> _SkewReading | None:
    """Read a failed start (or, for the crash guard, a fault after it): the
    innermost traceback frame in a file under ``tools/cc/`` -- or, for a
    ``SyntaxError``, which has no frame in the file it names, that file -- and
    the kept-old-helper test. The file that raised is often not the file that
    was edited (a circular import raises in the module it re-enters, a bad
    argument in the helper it was handed to, a new module's import in the new
    module), so every ``tools/cc/`` file on the traceback may be restored, and
    ``_hook_utils.py`` too when the test holds; a restore to HEAD of any of
    them re-enables the committed guard and can disable nothing. It reads
    the exception's class, traceback, ``filename`` and the name a sibling
    takes, never renders its text, so the crash guard may hand it a caught
    OSError (the portability roster's argued entry). Never raises: None when
    nothing can be read."""
    try:
        cc_dir = Path(__file__).resolve().parent.parent
        file: Path | None = None
        line: int | None = None
        if isinstance(exc, SyntaxError) and exc.filename:
            named = Path(exc.filename).resolve()
            if _under(named, cc_dir):
                file, line = named, exc.lineno
        chain: list[tuple[Path, int]] = []
        tb = exc.__traceback__
        while tb is not None:
            frame_file = Path(tb.tb_frame.f_code.co_filename)
            if frame_file.is_absolute() or frame_file.exists():
                resolved = frame_file.resolve()
                if _under(resolved, cc_dir):
                    chain.append((resolved, tb.tb_lineno))
            tb = tb.tb_next
        if file is None and chain:
            file, line = chain[-1]
        missing = _missing_helper_name(exc)
        restorable: list[Path] = [file] if file is not None else []
        if missing is not None:
            restorable.append(cc_dir / "hooks" / "_hook_utils.py")
        for outer, _line in reversed(chain):
            if outer not in restorable:
                restorable.append(outer)
        return _SkewReading(file, line, missing, restorable, cc_dir)
    # fail-open: ok text-fallback the refusal goes out unplaced
    except Exception:  # noqa: BLE001
        return None


def _restore_clause(reading: _SkewReading, lets_through: bool) -> str:
    """The repair a refusal names: a restore to HEAD of the file that raised
    (``--source=HEAD``: a bare ``git restore`` reads the index, which keeps a
    staged break and refuses an unmerged path), and of the file you edited
    when it is another one on the traceback. ``lets_through`` says the hook
    passes one such Bash command; otherwise the terminal is the route (a Bash
    call meets ``write_guard``, which judges it as any other call)."""
    first, *others = [reading.rel(p) for p in reading.restorable]
    clause = f"`git restore --source=HEAD -- {first}`"
    if others:
        clause += (" (or the same command for the file you edited, if it is "
                   + " or ".join(others) + ")")
    if lets_through:
        return (clause + ", as one Bash command, is the one call this hook lets through"
                " while it is wedged, and it saves the file's bytes under"
                " .espalier-state/wedge-restore/ first; or run it from a terminal")
    return clause + ", run from a terminal (a Bash call meets write_guard, which judges it as any other)"


def _restore_operand(words: list[str]) -> str | None:
    """The one path a restore to HEAD names, or None for any other command:
    ``git restore [--source=HEAD | -s HEAD | --worktree | -W] [--] <path>``,
    ``git checkout -- <path>`` or ``git checkout HEAD -- <path>``. Any other
    option (``--staged`` restores the index, not the file), ref or operand
    count is refused."""
    if len(words) < 3 or words[0] != "git":
        return None
    verb, rest = words[1], words[2:]
    operands: list[str] = []
    if verb == "restore":
        ended = False
        i = 0
        while i < len(rest):
            word = rest[i]
            if ended or not word.startswith("-"):
                operands.append(word)
            elif word == "--":
                ended = True
            elif word in ("--source=HEAD", "--worktree", "-W"):
                pass
            elif word in ("--source", "-s") and rest[i + 1:i + 2] == ["HEAD"]:
                i += 1
            else:
                return None
            i += 1
    elif verb == "checkout":
        if rest[:1] == ["--"]:
            operands = rest[1:]
        elif rest[:2] == ["HEAD", "--"]:
            operands = rest[2:]
        else:
            return None
    else:
        return None
    return operands[0] if len(operands) == 1 else None


def _restore_target(payload: object, reading: _SkewReading) -> Path | None:
    """The restorable file this call restores to HEAD, or None (DEF-4025):
    a Bash call whose command is one ``git restore`` or ``git checkout --`` of
    exactly one file the refusal names. A relative operand resolves against the
    payload's ``cwd``; forward and back slashes both read. Standard library
    only: ``_bash_patterns`` may be the module that raised."""
    import os
    import shlex

    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or len(command) > _RESTORE_COMMAND_CAP:
        return None
    if _RESTORE_SHELL_CHARS & set(command):
        return None
    try:
        words = shlex.split(command, posix=True)
    # fail-open: ok deliberate an unbalanced quote is no restore, and is refused
    except ValueError:
        return None
    operand = _restore_operand(words)
    # A trailing space or dot is dropped by the Windows path layer, so the
    # path would read equal to a named file while git reads another one.
    if not operand or operand != operand.strip() or operand.endswith("."):
        return None
    cwd = payload.get("cwd")
    base = Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())
    target = Path(operand.replace("\\", "/"))
    if not target.is_absolute():
        target = base / target
    wanted = os.path.normcase(str(target.resolve()))
    for path in reading.restorable:
        if os.path.normcase(str(path.resolve())) == wanted:
            return path
    return None


def _read_payload() -> dict | None:
    """The hook's stdin as a JSON object, or None (anything else, unreadable
    included). The floor helper's reader is not used: the kept helper may
    lack it."""
    import json

    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    # fail-open: ok deliberate an unread payload lets nothing through
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def wedge_restore(hook: str, reading: _SkewReading | None, error: str,
                  payload: object) -> tuple[str, dict] | None:
    """The one call a wedged PreToolUse hook lets through (DEF-4025): when
    ``payload`` restores to HEAD a file ``reading`` (:func:`wedge_reading`)
    names, save the file's bytes under ``.espalier-state/wedge-restore/`` and
    return the context to send and the record's details; else None. ``error``
    is the exception's class name. A failed copy never blocks the restore, and
    the context says so. Never raises."""
    try:
        if reading is None or not reading.restorable:
            return None
        target = _restore_target(payload, reading)
        if target is None:
            return None
        rel = reading.rel(target)
        raiser = reading.rel(reading.file) if reading.file is not None else "a sibling"
        if reading.missing is not None:
            cause = f"{raiser} takes `{reading.missing}`, which tools/cc/hooks/_hook_utils.py lacks"
        else:
            cause = f"{raiser} raised {error}"
        copy = _save_before_restore(target, reading.cc_dir)
        context = WEDGE_RESTORE_CONTEXT.format(hook=hook, cause=cause, file=rel, copy=copy)
        return context, {"hook": hook, "file": rel, "error": error}
    # fail-open: ok deliberate a reading that faults lets nothing through
    except Exception:  # noqa: BLE001
        return None


def _save_before_restore(target: Path, cc_dir: Path) -> str:
    """Copy ``target``'s bytes to ``<root>/<state dir>/wedge-restore/`` and say
    where; the discard speed bump's snapshot cannot run while the hook is
    wedged, and the restore discards the file's uncommitted edit."""
    import datetime

    try:
        # The state directory's one spelling is the helper's; a kept helper
        # that names none gets no copy, and the restore still goes through.
        state = getattr(sys.modules.get("_hook_utils"), "STATE_DIR", None)
        if not isinstance(state, str) or not state:
            return "No copy was saved first (the helper names no state directory)."
        if not target.is_file():
            return "There was no file to copy first."
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest_dir = cc_dir.parent.parent / state / "wedge-restore"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{target.stem}-{stamp}.py.txt"
        dest.write_bytes(target.read_bytes())
        return f"Its bytes as they were are saved at {dest.relative_to(cc_dir.parent.parent).as_posix()}."
    except Exception as err:  # noqa: BLE001 -- fail-open: ok copy-failed the restore still goes through, and says so
        return f"No copy was saved first ({type(err).__name__})."


def crash_refusal(reading: _SkewReading | None, error: str,
                  read_payload: bool) -> tuple[dict, dict] | None:
    """The crash guard's named refusal (DEF-4025's twin): the fields of
    :data:`WRITE_GUARD_CRASHED_AT` naming the innermost ``tools/cc/`` frame of
    ``reading`` (:func:`wedge_reading`) by ``error``, the exception's class
    name, and its line, with the record's details; None when no frame is
    placed. The guard formats the template at its deny site, so the
    deny-marker contract reads the reason there. ``read_payload`` is whether
    the guard read the call before it crashed: a crash in the read lets
    nothing through, so its text offers the terminal alone. Never raises."""
    try:
        if reading is None or reading.file is None:
            return None
        rel = reading.rel(reading.file)
        fields = {"error": error, "file": rel, "line": reading.line,
                  "restore": _restore_clause(reading, read_payload)}
        return fields, {"file": rel, "line": reading.line}
    # fail-open: ok text-fallback today's unplaced text goes out
    except Exception:  # noqa: BLE001
        return None


def refuse_on_helper_skew(hook: str, event: str, exc: BaseException) -> NoReturn:
    """Emit the fail-closed refusal for a deny hook whose sibling import failed
    at module top, then exit 0: the structured channel, where an exit 1 would be
    read as non-blocking. ``event`` picks the decision shape -- ``PreToolUse``
    emits ``hookSpecificOutput.permissionDecision: deny``, ``ConfigChange`` and
    ``Stop`` the Stop-style ``{"decision": "block"}``. The text names the file
    that raised and its line, and offers the upgrade only on the kept-old-helper
    test (DEF-2010). On ``PreToolUse`` the payload is read first, and a Bash
    restore to HEAD of a file the refusal names is let through instead, with
    context and no decision (DEF-4025, :func:`wedge_restore`). Standard library
    and this module only: ``_hook_utils`` is the floor the caller already
    imported, ``_integrity`` may be the module that failed, so the audit record
    is best-effort, and the exception's text routes through ``_json_safe``'s
    ``os_error_text`` (never the helper's, which may be the name missing), with
    ``str`` as the floor. The record types are composed, never literals, so the
    crash-guard census does not read this module as a fifth blocking hook: the
    refusal's is the crash guard's, ``<event>_blocked_internal_error`` with
    ``details.skew`` naming the cause, and the let-through's is a fail-open
    record, ``<event>_failed_open_wedge_restore``, so no roster or documented
    table grows. One channel per decision: nothing on stderr. Pinned by
    ``tests/test_hooks_start_on_a_kept_helper.py``."""
    import json

    reading = wedge_reading(exc)
    lets_through = event == "PreToolUse" and hook in _LETS_A_RESTORE_THROUGH
    if lets_through:
        passed = wedge_restore(hook, reading, type(exc).__name__, _read_payload())
        if passed is not None:
            context, passed_details = passed
            _record(f"{event.lower()}_failed_open_wedge_restore", passed_details)
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": event, "additionalContext": context}}) + "\n")
            sys.stdout.flush()
            raise SystemExit(0)
    # The seam renders an OSError's path as a path (a Windows path through
    # str() is its repr, backslashes doubled); it lives one directory up in
    # tools/cc, beside the hooks and regenerated with them, never in the kept
    # helper -- so the cross-directory shim the other hooks use goes first (a
    # fresh adopter's hook process has only the hooks directory on its path).
    # str is the floor if even that cannot import.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
    try:
        from _json_safe import os_error_text  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 -- fail-open: ok text-fallback the refusal still goes out, with the plain text
        os_error_text = str  # type: ignore[assignment]
    details: dict = {"hook": hook, "error": type(exc).__name__, "skew": "sibling import"}
    # The text is composed under a catch-all: an escape here would be the
    # exit 1 this refusal exists to replace (DEF-1176), so a template that
    # cannot format falls back to plain words that cannot raise.
    try:
        error = f"{type(exc).__name__}: {os_error_text(exc)}"
        if reading is not None and reading.file is not None:
            details.update(file=reading.rel(reading.file), line=reading.line)
        if reading is not None and reading.missing is not None and reading.file is not None:
            reason = HELPER_SKEW.format(hook=hook, taker=reading.rel(reading.file), name=reading.missing,
                                        error=error, restore=_restore_clause(reading, lets_through))
            details["cause"] = "kept helper"
        elif reading is not None and reading.file is not None:
            details["cause"] = "raised"
            reason = SIBLING_RAISED.format(hook=hook, file=reading.rel(reading.file), error=error,
                                           line=reading.line, restore=_restore_clause(reading, lets_through))
        else:
            reason = SIBLING_RAISED_UNPLACED.format(hook=hook, error=error)
    # fail-open: ok text-fallback the refusal still goes out, in plain words
    except Exception:  # noqa: BLE001
        reason = (str(hook) + " cannot start: a sibling import failed (" + type(exc).__name__
                  + "), and its text could not be composed. Read the error from a terminal;"
                  " every call this hook judges is refused until then.")
    _record(f"{event.lower()}_blocked_internal_error", details)
    output: dict
    if event in ("ConfigChange", "Stop"):
        output = {"decision": "block", "reason": reason}
    else:
        output = {"hookSpecificOutput": {
            "hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}}
    sys.stdout.write(json.dumps(output) + "\n")
    sys.stdout.flush()
    raise SystemExit(0)


def _record(event_type: str, details: dict) -> None:
    """A best-effort audit record for a hook that cannot start: ``_integrity``
    may be the module that failed."""
    try:
        import _hook_utils  # type: ignore[import-not-found]
        import _integrity  # type: ignore[import-not-found]
        _integrity.append_audit(
            _hook_utils.resolve_project_root(), {"event_type": event_type, "details": details}, quiet=True)
    except Exception:  # noqa: BLE001, S110 -- a best-effort record; the decision is the point
        pass


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
