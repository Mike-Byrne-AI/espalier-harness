"""Settings profile definitions.

Four profile shapes control what ``espalier init`` writes to
``.claude/settings.json``:

- ``minimal``    read/search only, no Write, no Bash, plus deny rules and hooks
- ``workflow``   ``minimal`` + the repository's own test, lint and build
                 commands (narrowed to each command's prefix, never a bare
                 binary; the Python runner and formatters only for a Python
                 fingerprint) + governed Write (default)
- ``self-host``  for meta-harnesses governing themselves (Espalier-Harness
                 on Espalier-Harness, similar tools). ``workflow`` plus explicit
                 ``python -m espalier *``, ``python tools/cc/*``, broader git
                 inspection, and refingerprint/doctor/audit/integrity commands.
                 OPT-IN ONLY via ``espalier init --profile self-host`` — not
                 auto-detected per operator preference.
- ``full``       preserves the v0.6.x broad-bash defaults; explicit opt-in via
                 ``espalier init --profile full``

Each profile contributes an ``allow`` rule list. ``deny`` rules are shared
across profiles (``_DENY_DEFAULTS``) so the dangerous bash shapes are denied
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
from typing import Callable, Literal, Sequence


ProfileName = Literal["minimal", "workflow", "self-host", "full"]


# Shared across all profiles. Order is human-readable, not significant.
# The bash entries cover dangerous patterns that should not be honored at the
# Claude Code permission layer even if a profile broadly allows Bash
# (write_guard.py covers the same shape at the hook layer; this is
# defense in depth, not a substitute). The Read(...) rules that used to lead
# the tuple moved to the hook layer (the note below).
_DENY_DEFAULTS: tuple[str, ...] = (
    "Bash(curl * | sh)",
    "Bash(wget * | sh)",
    "Bash(rm -rf /)",
)

# ⚠ A TRAILING `*` IN A `Bash(...)` RULE IS A PREFIX MATCH, NEVER A LITERAL.
# In a Claude Code permission rule the text before the first `*` is matched as
# written and the star matches any text, and there is no way to spell a
# literal asterisk (the platform's permissions page, read 2026-09-29). Text
# AFTER a star is still required -- driven the same day: `curl --version` runs
# under `Bash(curl * | sh)`, so the two fetch-pipe rules above deny the
# pipe-to-sh family and nothing else -- but a rule that ENDS in a star denies
# everything that begins with its prefix. `Bash(rm -rf /*)`, written for the
# root glob wipe, therefore denied EVERY recursive delete of an absolute path
# -- a temp build directory, a scratch tree -- in every permission mode,
# bypass included (deny outranks the mode), with no reason shown and no
# re-issue path, right after the CP-RMRF speed bump had promised passage on
# re-issue. Driven on the self-host tree 2026-09-28 and 2026-09-29 (three
# probes: a relative path passed on the re-issue, every absolute path was
# refused). The wipe it was written for is walled at the hook layer by
# `write_guard`'s catastrophic-rm classifier, which reads the root glob as the
# root itself (pinned in tests/test_write_guard.py), so the rule was redundant
# for its target and over-broad for everything else. It is RETIRED: `init` no
# longer writes it, and `doctor`, `merge-settings` and the `upgrade` preview
# name it on a settings.json that still carries it -- the merge never removes
# an operator's rule, so the delete is theirs. Pinned in
# tests/test_settings_profiles.py: no deny default ends in a `*` or puts one
# right after a `/`, and a retired rule is never also a default.
#
# Each row is `(rule, last version whose init wrote it, why)`. The version is
# the provenance contract: a rule goes here only if `init` SHIPPED it, so the
# reporters can say so; a merely bad rule an operator wrote themselves is
# theirs, never "retired", and does not belong here.
RETIRED_DENY_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "Bash(rm -rf /*)",
        "0.8.0b2",
        "a trailing star in a Bash rule is a prefix match, so this rule denied "
        "every recursive delete of an absolute path in every permission mode; "
        "the write_guard hook already blocks the root wipe it was written for",
    ),
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


def powershell_twins(rules: Sequence[str]) -> tuple[str, ...]:
    """The ``PowerShell(<cmd>)`` twin of every ``Bash(<cmd>)`` rule in
    ``rules``, in the rules' order, skipping a twin already present.

    Claude Code's PowerShell tool is a separate tool from Bash and its
    permission rules are tool-scoped, so a ``Bash(...)`` allow-list is inert
    for every command the agent issues through PowerShell -- driven on a
    Windows 11 host (walk 2, finding 3, 2026-09-09: 14 of 18 rules inert),
    and the platform docs show the ``PowerShell(...)`` rule shape with the
    same prefix-wildcard semantics. ``cli._profile_allow_list`` appends these
    only when the render host is Windows, the way the statusLine picks its
    batch shim, so a POSIX install's file does not grow rules for a tool it
    does not have. Allow rules only: the deny defaults are never twinned (see
    the note above ``_DENY_DEFAULTS``; pinned in tests/test_settings_profiles.py).
    Non-``Bash(...)`` rules (``Read``, ``Write``, ...) pass through untwinned.
    """
    rules = list(rules)  # a one-shot iterable would be drained by `seen` (review, 2026-09-25)
    out: list[str] = []
    seen = set(rules)
    for rule in rules:
        if rule.startswith("Bash(") and rule.endswith(")"):
            twin = "PowerShell(" + rule[len("Bash("):]
            if twin not in seen:
                out.append(twin)
                seen.add(twin)
    return tuple(out)


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
    # fingerprint dict and, as ``extra_actions``, espalier.toml's
    # ``[extra_actions]`` table (or None); returns a tuple of patterns the
    # renderer merges into ``allow`` at ``_build_settings_json`` time.
    # Default is the no-op -- profiles that should not
    # auto-grant Bash (``minimal``) keep it; profiles that should
    # (``workflow``, ``self-host``) wire in a helper below.
    fingerprint_allows: Callable[..., tuple[str, ...]] = field(
        default=lambda fp, extra_actions=None: ()
    )
    # Rules in ``allow`` that render only for a Python fingerprint
    # (:data:`PYTHON_ONLY_ALLOWS`); ``cli._profile_allow_list`` drops them
    # otherwise. Empty for a profile whose list is unconditional.
    python_only: frozenset[str] = frozenset()


#: The rules a profile carries for a Python repository only: its test runner
#: under three spellings and its two formatters. ``cli._profile_allow_list``
#: drops them unless the fingerprint lists Python among the repository's
#: languages (:func:`is_python_fingerprint`). Before 2026-10-06 every
#: repository got them: on a Node tree the only Python is the harness's own
#: vendored ``tools/cc/``, and an unprompted ``ruff format .`` or ``black .``
#: there rewrote the protected files and read back as integrity drift
#: (DEF-965; the operator's call, DEC-37 branch (a)).
PYTHON_ONLY_ALLOWS: frozenset[str] = frozenset({
    "Bash(pytest *)",
    "Bash(python -m pytest *)",
    "Bash(python3 -m pytest *)",
    "Bash(ruff *)",
    "Bash(black *)",
})

#: The actions whose commands the fingerprint-derived rules cover, besides the
#: test commands: the three a session and /preflight run routinely.
DERIVED_ACTIONS: tuple[str, ...] = ("lint", "test", "build")

#: Binaries whose ``run`` (or ``run-script``) subcommand runs a named script:
#: the narrowed rule keeps the script name, so ``npm run build`` never grants
#: every other script.
_SCRIPT_RUNNERS: frozenset[str] = frozenset({"npm", "pnpm", "yarn", "bun"})
_RUN_VERBS: frozenset[str] = frozenset({"run", "run-script"})


def is_python_fingerprint(fp: dict | None) -> bool:
    """Whether the fingerprint lists Python among the repository's languages:
    the condition :data:`PYTHON_ONLY_ALLOWS` ship on. No fingerprint is not a
    Python one: ``init`` writes the fingerprint before it renders settings."""
    languages = fp.get("languages") if isinstance(fp, dict) else None
    return isinstance(languages, list) and "python" in languages


def narrowed_rules(command: str) -> list[str]:
    """The allow rules one fingerprinted command derives, never a bare binary.

    * ``python`` / ``python3``: narrowed to the first argument (``-m <module>``
      or the script) and emitted under BOTH interpreter names, since the
      adopter's Claude types whichever the host has (DEF-714).
    * everything else keeps its subcommand, and a script runner's ``run``
      keeps the script name: ``npm test`` derives ``Bash(npm test)`` and
      ``Bash(npm test *)``, ``npm run build`` derives ``Bash(npm run build)``
      and ``Bash(npm run build *)``, ``go test ./...`` derives ``Bash(go
      test)`` and ``Bash(go test *)``.
    * a command whose first argument is a flag keeps the command as written,
      and a bare binary (``make``) derives only its exact rule, so no input
      derives ``Bash(<binary> *)``.

    Both the exact and the wildcard form are emitted: Claude Code's pinned
    documentation in this repository does not settle whether ``Bash(npm test
    *)`` also matches a bare ``npm test`` (checked 2026-10-06), and the exact
    rule costs nothing if it does.
    """
    tokens = command.strip().split()
    if not tokens:
        return []
    binary = tokens[0]
    if binary in ("python", "python3"):
        if len(tokens) < 2 or (tokens[1] == "-m" and len(tokens) < 3):
            return []
        tail = f"-m {tokens[2]}" if tokens[1] == "-m" else tokens[1]
        return [f"Bash(python {tail} *)", f"Bash(python3 {tail} *)"]
    runs_a_script = binary in _SCRIPT_RUNNERS and len(tokens) >= 2 and tokens[1] in _RUN_VERBS
    if len(tokens) == 1 or (runs_a_script and len(tokens) == 2):
        # A bare binary, or `npm run` naming no script: the wildcard form
        # would be the whole binary, or every script.
        return [f"Bash({' '.join(tokens)})"]
    if tokens[1].startswith("-") or (runs_a_script and tokens[2].startswith("-")):
        prefix = tokens
    elif runs_a_script:
        prefix = tokens[:3]
    else:
        prefix = tokens[:2]
    head = " ".join(prefix)
    return [f"Bash({head})", f"Bash({head} *)"]


def _workflow_fingerprint_allows(
    fp: dict, extra_actions: dict | None = None,
) -> tuple[str, ...]:
    """Derive narrow allow rules from the repository's own commands, so a
    TypeScript, Go or Rust adopter is not prompted for every test, lint and
    build run, while nothing beyond those commands is pre-approved.

    Reads ``test_commands`` and ``inferred_actions`` (lint, test and build)
    from the fingerprint as ``analyze.detect_tests`` and
    ``analyze.detect_actions`` write them, and the same three actions from
    ``espalier.toml``'s ``[extra_actions]`` when the caller passes that table.
    Each command derives the rules :func:`narrowed_rules` names, never a
    bare ``Bash(<binary> *)``: until 2026-10-06 a Node fingerprint derived
    ``Bash(npm *)``, which pre-approves ``npm install``, ``npm exec --yes``,
    ``npm publish`` and every script (DEF-965; DEC-37 branch (a)). Rules
    already in the static list are not removed here; the renderer dedupes.

    Returns an empty tuple when the repository declares no such command.
    """
    patterns: list[str] = []
    seen_patterns: set[str] = set()
    commands: list[object] = list(fp.get("test_commands", []) or [])
    inferred = fp.get("inferred_actions", {})
    tables = [inferred if isinstance(inferred, dict) else {}]
    if isinstance(extra_actions, dict):
        tables.append(extra_actions)
    for table in tables:
        for action in DERIVED_ACTIONS:
            listed = table.get(action) or []
            if isinstance(listed, list):
                commands.extend(listed)
    for cmd in commands:
        if not isinstance(cmd, str):
            continue
        for pattern in narrowed_rules(cmd):
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
        "Governed work posture (default): Read, Grep, Glob, the "
        "repository's own test, lint and build commands, git "
        "inspection, and Write. Writes are governed by plan_guard.py "
        "— a Write tool call without an active execution plan is "
        "denied by the hook layer."
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
        # Daily friction relief -- the espalier CLI, and on a Python
        # repository its formatters. A trailing `*` is a prefix match (the
        # note above RETIRED_DENY_RULES): every argument after the prefix is
        # pre-approved, so a rule is only as narrow as its prefix. The pytest,
        # ruff and black rules render for a Python fingerprint only
        # (PYTHON_ONLY_ALLOWS).
        "Bash(espalier *)",
        "Bash(ruff *)",
        "Bash(black *)",
    ),
    fingerprint_allows=_workflow_fingerprint_allows,
    python_only=PYTHON_ONLY_ALLOWS,
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
    python_only=PYTHON_ONLY_ALLOWS,
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


def retired_deny_rules() -> tuple[tuple[str, str, str], ...]:
    """``(rule, last_shipped, why)`` rows: deny rules ``init`` used to write
    and no longer does, with the last version that wrote each.

    A settings.json that still carries one is named by ``doctor``,
    ``merge-settings`` and the ``upgrade`` preview, with the reason and the
    version; nothing removes it, because ``permissions`` is the operator's
    (the note above ``RETIRED_DENY_RULES``).
    """
    return RETIRED_DENY_RULES
