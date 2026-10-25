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

from pathlib import Path

# Import the canonical env-var name so the reason templates pin to the SoT in
# _maintenance_mode.ENV_VAR rather than carrying a divergent literal.
# Sibling-module import; the importing hook has already set
# ``sys.path.insert(0, hooks_dir)`` by the time this module loads (see
# write_guard.py:45-50 for the pattern).
import _maintenance_mode  # type: ignore[import-not-found]
# The start refusal's old home (DEF-3008): an upgrade keeps a deny hook the
# adopter edited and regenerates this module, and a kept hook from before
# the move calls the refusal here. The start refusal imports only the
# standard library, and every deny hook imported it first.
from _start_refusal import refuse_on_helper_skew as refuse_on_helper_skew  # type: ignore[import-not-found]  # noqa: E402,F401


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

# A move or delete of a directory that ENCLOSES harness ground (DEF-5012):
# `tools` holding `tools/cc/`, `.github` holding the harness-guard workflow.
# The harness pair's relaunch switches the zone check off and the change then
# carries the harness's files with the directory; its relocate line does the
# same from a terminal. So neither is offered, whether or not the adopter's
# espalier.toml lists a zone there, and the Do moves the adopter's own files
# and leaves the harness's. ``write_guard._zone_reason`` picks these for an
# operand the call itself moves or deletes: ``{ground}`` is the harness entry
# inside it, ``{operand}`` the directory, and ``{zone}`` / ``{key}`` /
# ``{kind_text}`` the adopter's zone it sits in or holds. A write, link or
# destination there changes no harness file and keeps the zone's own text. No
# ``{hint}`` slot: they name no relaunch. A maintainer restructuring the
# harness itself has maintenance mode (docs/HOOKS.md).
HARNESS_GROUND_ENCLOSED = (
    "{effect} of a directory holding a protected zone blocked: {path}. The "
    "harness's own `{ground}` is inside it, so this would take the harness's "
    "files with it."
    "\n  Don't: relaunch in maintenance mode for this, or do it from your own "
    "terminal instead -- either way `{ground}` goes with it."
    "\n  Do: move your own files out of `{operand}` one by one and leave "
    "`{ground}` where it is; `/status --explain <path>` shows which zone covers "
    "a path."
)
ADOPTER_ZONE_ENCLOSING_HARNESS = (
    "{effect} of protected zone blocked: {path}. The harness's own `{ground}` "
    "is inside it, and your espalier.toml names `{zone}` under `{key}` "
    "({kind_text}), so this would take the harness's files with yours."
    "\n  Don't: relaunch in maintenance mode for this, or do it from your own "
    "terminal instead -- either way `{ground}` goes with it, and maintenance "
    "mode switches this check off for the whole session."
    "\n  Do: leave `{operand}` in place; to move your own files, first narrow "
    "the `{key}` entry in espalier.toml from your own terminal so it covers "
    "neither `{ground}` nor what you move, then move yours one by one and "
    "leave `{ground}` where it is; `/status --explain <path>` shows which zone "
    "covers a path."
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

# Gate 5, the handoff gate: nothing in flight (no plan in progress, no tracked
# edit) and the branch holds commits its upstream does not, made in this
# session, on a repository whose espalier.toml sets handoff_push = true.
# Instructional (the right move is one command), so it carries the Don't/Do
# pair. The gate's own flag (the HEAD it last judged), not the loop signal, is
# what keeps it from returning on every turn; the text says so. {target} is
# the branch (the actionability contract's subject field); {plan} is "the
# plan `...` is complete" or "no plan is in progress"; {ahead} arrives already
# pluralised ("1 commit", "3 commits"); {push} says what the push does for
# this branch (open the pull request, or push onto the one already open).
GATE_HANDOFF_OWED = (
    "Handoff owed before Claude Code stops: nothing is in flight ({plan}; no "
    "tracked edit) and {target} holds {ahead} that {upstream} does not, so the "
    "lane must be handed off now. A finished lane is handed off in the turn "
    "that finishes it, while the context is warm. Run /handoff: it writes the "
    "Session Log row, and its last step, the ship driver's `handoff` verb "
    "(tools/cc/ship.py), pushes the lane once, {push}. This gate speaks once "
    "per commit."
    "\n  Don't: report the lane as done and stop for the operator to type "
    "/handoff -- the lane sits unpushed, with no row and its claims live, until "
    "someone returns, and the next session hands it off from a cold context."
    "\n  Do: run /handoff in this turn. Three carve-outs, each said in one line "
    "before stopping again: the operator asked to hold the push; this lane ships "
    "together with another; or more of this lane's work is still to come this "
    "session (a lane group, the next pack of a chain). The continuation is let "
    "through, and the gate does not return for this commit."
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
    # A move or delete of a directory enclosing harness ground (DEF-5012),
    # in an adopter zone or none: both remedies refused.
    "HARNESS_GROUND_ENCLOSED",
    "ADOPTER_ZONE_ENCLOSING_HARNESS",
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
    # Gate 5: the one move (run /handoff in this turn) beside the one that
    # left a lane unpushed for eleven hours (2026-10-24).
    "GATE_HANDOFF_OWED",
    # The PowerShell dangerous-command fallback now carries a Don't/Do
    # way-forward (was a raw-regex-leaking diagnostic) -- under the
    # both-markers + actionability contracts going forward.
    "DANGEROUS_PS_PATTERN_FALLBACK",
    # The time-budget refusal: the wrong move (the same long command again)
    # times out again, so it is named beside the split that passes.
    "WRITE_GUARD_TIME_BUDGET",
)

# ── a deny hook that cannot start (DEF-1176, DEF-2010, DEF-4025) ─────
#: The start refusal's templates and readers are in
#: ``tools/cc/hooks/_start_refusal.py``, which every deny hook imports first,
#: before this module (DEF-3008): a refusal composed here could not go out when
#: this module, or ``_maintenance_mode`` under it, is the one that raised. The
#: crash guard's text stays here: ``write_guard`` formats it at its deny site,
#: after every import succeeded.
#: The crash guard's text for a fault after the imports (DEF-4025's twin):
#: the class and the place, never the message (a message can quote a path or a
#: file's contents), as the record never carries it either.
WRITE_GUARD_CRASHED_AT = (
    "write_guard internal error ({error} at {file}:{line}); failing closed. Re-issue"
    " once. If every call is denied the guard is wedged, and if {file} is being"
    " edited, restore it to HEAD: {restore}. Otherwise `/status --log` counts it and"
    " the repair is made from a terminal outside this session."
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
