"""Settings profile definitions.

Four profile shapes control what ``espalier init`` writes to
``.claude/settings.json``:

- ``minimal``    read/search only, no Write, no Bash, plus deny rules and hooks
- ``workflow``   ``minimal`` + narrow test commands + governed Write (default)
- ``self-host``  for meta-harnesses governing themselves (Espalier-Harness
                 on Espalier-Harness, similar tools). ``workflow`` plus explicit
                 ``python -m espalier *``, ``python tools/cc/*``, broader git
                 inspection, and refingerprint/doctor/audit/integrity commands.
                 OPT-IN ONLY via ``espalier init --profile self-host`` — not
                 auto-detected per operator preference.
- ``full``       preserves the v0.6.x broad-bash defaults; explicit opt-in via
                 ``espalier init --profile full``

Each profile contributes an ``allow`` rule list. ``deny`` rules are shared
across profiles (``_DENY_DEFAULTS``) so sensitive paths are denied
regardless of how permissive the allow list is.

Hooks are profile-independent: every profile emits the full hook set.
Profile selection only shapes ``permissions``.

This module is the single source of truth for settings profiles. It is
separate from ``espalier/profiles.py`` (which classifies the REPO into
project profiles like ``python_library`` or ``ml_repo``). The two concerns
are unrelated; keeping them in different modules avoids confusion.

The live Claude Code settings
schema (``https://json.schemastore.org/claude-code-settings.json``) does
NOT define a ``disableSkillShellExecution`` key. Setting it would emit a
key Claude Code does not honor and would fail schema-aware validation. The
field is omitted from the generated settings on every profile; see
``docs/SHARP_EDGES.md`` for the gap entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


ProfileName = Literal["minimal", "workflow", "self-host", "full"]


# Shared across all profiles. Order is human-readable, not significant.
# The Read(...) rules use Claude Code's per-tool deny syntax; the bash
# entries cover dangerous patterns that should not be honored at the
# Claude Code permission layer even if a profile broadly allows Bash
# (write_guard.py covers the same shape at the hook layer; this is
# defense in depth, not a substitute).
_DENY_DEFAULTS: tuple[str, ...] = (
    "Bash(curl * | sh)",
    "Bash(wget * | sh)",
    "Bash(rm -rf /)",
    "Bash(rm -rf /*)",
)

# ⚠ THE FIVE `Read()` RULES THAT USED TO LEAD THIS TUPLE WERE REMOVED
# DELIBERATELY, and moved to the hook layer as
# `write_guard.check_secret_path_access`. They were:
#     Read(./.env)  Read(./.env.*)  Read(./secrets/**)
#     Read(./**/.aws/credentials)  Read(./**/credentials.json)
#
# Configuring ANY `Read()` deny rule arms a static-resolvability requirement in
# Claude Code: before running a Bash command it must prove which files that
# command reads, and a command it CANNOT prove -- one containing a `cd`, a
# relative `--include` glob, or a glob over a directory it cannot enumerate --
# raises an interactive permission prompt. Deny outranks `allow` AND outranks
# `bypassPermissions`, so no allow-list and no permission mode could suppress
# it. Verified from the client's own message text: "which file that is cannot be
# resolved statically while a Read() deny rule is configured, so this needs
# approval."
#
# The cost was not theoretical. Espalier's pitch is that an adopter can run in
# bypass mode and not have the session stall; shipping these rules on EVERY
# profile is what made it stall, and a single session measured hours lost to it.
# The Bash entries above do NOT arm that path -- the condition names `Read()`
# specifically -- so they stay here as defense in depth alongside write_guard's
# dangerous-pattern check.
#
# Coverage did not shrink: the same five shapes are denied at the hook layer,
# for the Read tool AND for Bash read verbs, and unlike a permission rule the
# hook check is not bypassed by maintenance mode. It is a friction layer, not a
# security boundary (STANDING_PRINCIPLES §2) -- exactly what the permission
# rules were.
#
# ⚠ THE TWO FETCH-PIPE ENTRIES ABOVE ARE POSIX LITERALS, NOT THE CLASS. They
# deny exactly `curl ... | sh` and `wget ... | sh`; the download-and-execute
# CLASS (`| bash`, `bash <(curl ...)`, `bash -c "$(curl ...)"`, and the
# PowerShell `irm ... | iex` / `iex (irm ...)` / WebClient forms) is covered at
# the hook layer on BOTH shells by the `CP-FETCHEXEC` speed-bump in
# `tools/cc/hooks/_speedbump.py` -- one deny that clears on re-issue. Do NOT
# add PowerShell twins of these two entries: they are POSIX idioms that cannot
# express the harm in PowerShell, so the twins would be green, blind, and claim
# a coverage they do not have (the withdrawn recommendation on the ledger's
# PowerShell fetch-and-execute row).
#
# And the two layers stack: a command matching these two literals meets the
# speed-bump FIRST (one deny, "re-issue to proceed") and then this permission
# deny on the re-issue, which has no re-issue path of its own. For exactly
# `curl ... | sh` and `wget ... | sh` the bump's remedy therefore does not
# apply -- the permission layer is the wall, by design; every other spelling
# of the class clears on re-issue. Both facts are pinned in
# tests/test_settings_profiles.py.


@dataclass(frozen=True)
class Profile:
    name: ProfileName
    description: str
    allow: tuple[str, ...]
    # Whether this profile can be selected via ``espalier.toml``'s
    # ``default_profile`` field. Profiles that widen permissions
    # (``self-host``) set this to ``False`` so they remain CLI-flag-only
    # opt-ins — preventing an upstream repo from silently widening
    # permissions for every downstream operator running ``espalier init``.
    # Default ``True`` so adding new profiles doesn't require changing
    # every existing definition.
    config_selectable: bool = True
    # Callable returning extra ``Bash(...)`` allow patterns
    # derived from the repo's fingerprint. Receives the parsed
    # fingerprint dict; returns a tuple of patterns the renderer
    # merges into ``allow`` at ``_build_settings_json`` time. Default
    # is the no-op ``lambda fp: ()`` — profiles that should not
    # auto-grant Bash (``minimal``) keep it; profiles that should
    # (``workflow``, ``self-host``) wire in a helper below.
    fingerprint_allows: Callable[[dict], tuple[str, ...]] = field(
        default=lambda fp: ()
    )


def _workflow_fingerprint_allows(fp: dict) -> tuple[str, ...]:
    """Derive ``Bash(<binary> *)`` allow patterns from a
    repo's fingerprint, so non-Python adopters (TypeScript / Go /
    Rust / Elixir / .NET / etc.) don't hit a permission-prompt flood
    for their own test/build commands.

    Reads top-level ``test_commands`` and ``inferred_actions["build"]``
    (both ``list[str]``) from the fingerprint as written by
    ``analyze.detect_tests`` / ``analyze.detect_actions``. For each
    command, extracts the leading binary token and emits
    ``Bash(<binary> *)``. A ``python`` / ``python3`` command is narrowed
    to its first argument (``-m <module>``, or the script) and emitted
    under BOTH interpreter names, since the adopter's Claude types
    whichever the host has (DEF-714); a bare ``Bash(python *)`` never
    derives from here. Patterns already in the
    static allow-list are NOT removed here — the renderer dedupes at
    merge time.

    Returns an empty tuple if the fingerprint has no test/build
    commands. The merge in ``_build_settings_json`` is no-op in that
    case (today's static-allow behavior).
    """
    patterns: list[str] = []
    seen_patterns: set[str] = set()  # stores full Bash(...) patterns
    test_cmds = fp.get("test_commands", []) or []
    # Build commands live under inferred_actions["build"] (a
    # list[str] written by analyze.detect_actions — ["npm run build"] /
    # ["make build"]), NOT a top-level "build_commands" key the real
    # fingerprint never carries.
    inferred = fp.get("inferred_actions", {})
    build_cmds = (inferred.get("build", []) if isinstance(inferred, dict) else []) or []
    for cmd in list(test_cmds) + list(build_cmds):
        if not isinstance(cmd, str):
            continue
        tokens = cmd.strip().split()
        if not tokens:
            continue
        binary = tokens[0]
        if binary in ("python", "python3") and len(tokens) >= 2:
            # Both interpreter spellings, whichever the fingerprint recorded:
            # stock macOS has no `python`, many Windows installs no `python3`,
            # and the rule is for whatever the adopter's Claude types there
            # (DEF-714; the static espalier/pytest pairs are the precedent).
            # Narrowed to the first argument -- `-m <module>` or the script --
            # so a `python run_tests.py` command never derives the broad
            # `Bash(python *)` the self-host list forbids.
            if tokens[1] == "-m" and len(tokens) >= 3:
                tail = f"-m {tokens[2]}"
            else:
                tail = tokens[1]
            candidates = [f"Bash(python {tail} *)", f"Bash(python3 {tail} *)"]
        else:
            candidates = [f"Bash({binary} *)"]
        for pattern in candidates:
            if pattern not in seen_patterns:
                patterns.append(pattern)
                seen_patterns.add(pattern)
    return tuple(patterns)


_MINIMAL = Profile(
    name="minimal",
    description=(
        "Read-only posture: Read, Grep, Glob and hooks. No Write, no "
        "Bash allows. Best for code review or audit work where the "
        "session should never mutate the repo."
    ),
    allow=(
        "Read",
        "Grep",
        "Glob",
    ),
)


_WORKFLOW = Profile(
    name="workflow",
    description=(
        "Governed work posture (default): Read, Grep, Glob, narrow "
        "test and git-inspection commands, and Write. Writes are "
        "governed by plan_guard.py — a Write tool call without an "
        "active execution plan is denied by the hook layer."
    ),
    allow=(
        "Read",
        "Grep",
        "Glob",
        "Write",
        "Bash(pytest *)",
        "Bash(python -m pytest *)",
        "Bash(python3 -m pytest *)",  # stock macOS has no `python`; the self-host profile's espalier pair is the precedent
        "Bash(git status)",
        "Bash(git diff *)",
        "Bash(git log *)",
        "Bash(git show *)",
        # Daily friction relief — espalier CLI + ruff/black formatters
        # are routine in this posture. Narrow Bash patterns; subcommand args
        # still flow through `*` wildcard so a hostile arg payload still
        # lands in a fresh permission prompt rather than auto-allow.
        "Bash(espalier *)",
        "Bash(ruff *)",
        "Bash(black *)",
    ),
    fingerprint_allows=_workflow_fingerprint_allows,
)


_SELF_HOST = Profile(
    name="self-host",
    description=(
        "Self-host posture: for repos that govern themselves "
        "(Espalier-Harness on Espalier-Harness, similar meta-tools). "
        "Adds explicit allows for `python -m espalier *`, `python "
        "tools/cc/*`, broader `git *` inspection, and the audit / "
        "doctor / integrity / fingerprint commands the harness "
        "itself emits. Stays narrower than `full` — no bare "
        "`python *` or `pip *`. Opt-in only via "
        "`espalier init --profile self-host`."
    ),
    config_selectable=False,  # CLI-only opt-in; rejected in cmd_init.
    allow=(
        "Read",
        "Grep",
        "Glob",
        "Write",
        # Workflow allows preserved
        "Bash(pytest *)",
        "Bash(python -m pytest *)",
        "Bash(python3 -m pytest *)",  # stock macOS has no `python`; the espalier pair below is the precedent
        "Bash(git status)",
        "Bash(git diff *)",
        "Bash(git log *)",
        "Bash(git show *)",
        "Bash(espalier *)",  # workflow parity
        "Bash(ruff *)",      # workflow parity
        "Bash(black *)",     # workflow parity
        # Self-host additions: harness's own subcommands
        "Bash(python -m espalier *)",
        "Bash(python3 -m espalier *)",
        "Bash(python tools/cc/* *)",
        "Bash(python3 tools/cc/* *)",
        # Self-host additions: broader git for inspection
        "Bash(git branch *)",
        "Bash(git remote *)",
        "Bash(git tag *)",
        "Bash(git ls-files *)",
        # Self-host additions: scripts/ utilities
        "Bash(python scripts/* *)",
        "Bash(python3 scripts/* *)",
    ),
    fingerprint_allows=_workflow_fingerprint_allows,
)


_FULL = Profile(
    name="full",
    description=(
        "Power-user posture: broad Bash allows for python / pip / git "
        "tooling. Preserves the v0.6.x default behavior as an "
        "explicit opt-in. Use when you trust the agent to run "
        "arbitrary scripted automation."
    ),
    allow=(
        "Read",
        "Grep",
        "Glob",
        "Write",
        "Bash(python *)",
        "Bash(python3 *)",
        "Bash(pytest *)",
        "Bash(pip *)",
        "Bash(git *)",
    ),
)


PROFILES: dict[ProfileName, Profile] = {
    "minimal": _MINIMAL,
    "workflow": _WORKFLOW,
    "self-host": _SELF_HOST,
    "full": _FULL,
}

DEFAULT_PROFILE: ProfileName = "workflow"


def get_profile(name: str) -> Profile:
    """Look up a profile by name. Raises ``ValueError`` on unknown names."""
    if name not in PROFILES:
        raise ValueError(
            f"Unknown profile {name!r}; valid names are "
            f"{sorted(PROFILES.keys())}"
        )
    return PROFILES[name]


def deny_defaults() -> tuple[str, ...]:
    """Shared deny rules emitted on every profile."""
    return _DENY_DEFAULTS
