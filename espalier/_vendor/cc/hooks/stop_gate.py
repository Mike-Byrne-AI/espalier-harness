#!/usr/bin/env python3
"""Stop hook — lightweight session hygiene by default.

Mode is read from ESPALIER_STOP_GATE (default: "light"):
  - "light":      skip Gate 1 (pytest). Run hygiene gates 2–4 only.
  - "full":       run Gate 1 (pytest) before the hygiene gates.
  - "scan-clean": opt into the advisory session-signal reads (scan-clean
                  delta + tool-call/trajectory). All warn-only (stderr); never
                  blocks; does NOT run pytest. (Single value, NOT composable
                  with full — keeps session_start.py/statusline.py exact-match
                  ESPALIER_STOP_GATE parsers consistent.)
  - other:        warn to stderr and fall back to "light".

Heavy proof (full pytest, lint, type) belongs in `/preflight` and CI. Local
Stop should not spend the inner pytest budget on every turn. (`espalier
pre-release` is a further tier on top of that, but only on the Espalier-Harness
source tree -- it stands down at exit 0 anywhere else, so it is not the heavy
tier this default is trading against on your repo.)

Gate 1: Core pytest           — Opt-in via ESPALIER_STOP_GATE=full. Fail → BLOCK.
Gate 2: Docs refresh          — write_count >= 10, no docs_refreshed flag → BLOCK.
Gate 3: Code review           — write_count >= 10, no code_reviewed record → BLOCK.
Gate 5: Handoff owed          — nothing in flight (no plan in progress, no tracked
                                edit), the branch holds commits its upstream does
                                not, made this session, handoff_push = true → BLOCK,
                                once per commit (runs under MAINTENANCE_MODE too, and
                                alone on the continuation Stop); while this seat has
                                ANOTHER pull request open the lane is held instead
                                (one open pull request per seat), re-checked every
                                five minutes, and the block returns once none is.
Gate 4: Auto-finalize         — Run cognitive_blueprint.py finalize (silent, always passes).

Gate 5 runs before Gate 4 (a block returns before the finalize, which a later
Stop runs) and keeps the number a gate retired in 2026-05 freed: it is not that
"session state saved" gate, which was unreachable by design -- cc/blueprints/
is gitignored, so Gate 4's auto-finalize output never appears in `git status`
to satisfy such a check. This one reads the plan, the index and git, which the
blueprint never enters: a finished lane left unpushed for the operator's
/handoff sat unrowed and claimed for eleven hours (2026-10-24).

Exit 0 with no JSON = allow stop.
Exit 0 + decision="block" = block stop, CC continues working.

Every gate block also lands one record in the governance audit log, typed per
gate (``stop_blocked_pytest`` / ``_docs_refresh`` / ``_code_review``, metadata
only), through ``_audit_block`` -- so ``/status --log`` can say why a session
was returned. A block is once per turn (the protocol's loop signal lets the
next Stop through), so the reader files these as pauses beside the speed
bump, not as refusals; see docs/HOOKS.md "Governance audit log". When
MAINTENANCE_MODE skips Gates 2 and 3, the first Stop of the session lands one
advisory record instead (``stop_bypassed_maintenance_mode``, in neither tier),
so the reader can say the hygiene gates were bypassed rather than reading the
day as clean (DEF-789).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Import timing constants from the co-located copy (_hook_contract.py).
# tools/cc/ cannot import from espalier/ (isolation rule), so _hook_contract.py
# is a standalone copy of espalier/hook_contract.py kept in sync by tests.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
# The start refusal first and alone, then the guard over every other sibling,
# the floor included: write_guard.py's import block is the sister site and says
# why (DEF-1176, DEF-3008). A Stop hook that dies at import is exit 1, which the
# protocol reads as non-blocking, so the gates run nothing and the stop
# goes through unjudged; under `__main__` it is the Stop-style block naming the
# repair instead, which the protocol's loop signal lets through on the next
# Stop (a pause, never a lockout).
try:
    import _start_refusal  # noqa: E402
except Exception as _floor:  # noqa: BLE001 -- the start refusal itself cannot import (DEF-3008)
    if __name__ != "__main__":
        raise
    try:  # the protocol's loop signal: this Stop is the one continued after the last block
        _stop = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        _again = isinstance(_stop, dict) and bool(_stop.get("stop_hook_active"))
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate an unread Stop is refused
        _again = False
    if _again:
        raise SystemExit(0) from None
    sys.stdout.write(json.dumps({"decision": "block", "reason": (
        "stop_gate cannot start: tools/cc/hooks/_start_refusal.py raised " + type(_floor).__name__
        + "; it is the start refusal every deny hook imports first. Restore it to HEAD:"
        " `git restore --source=HEAD -- :/tools/cc/hooks/_start_refusal.py`, as one Bash command"
        " (write_guard, wedged by the same file, lets that one call through) or from a terminal;"
        " if HEAD has no such file (an upgrade that did not finish), run"
        " `espalier upgrade --execute .` from a terminal instead. Every call this hook judges"
        " is refused until then.")}) + "\n")
    sys.stdout.flush()
    raise SystemExit(0) from None
try:
    import _hook_utils  # noqa: E402
    import _denial_reasons  # noqa: E402
    from _hook_contract import STOP_INNER_BUDGET  # noqa: E402
    import _maintenance_mode  # noqa: E402
    import _integrity  # noqa: E402
    from _json_safe import os_error_text  # noqa: E402
    from _json_safe import decode_text_or_problem, load_json_dict_safe  # noqa: E402
    # Every helper name this hook's import graph takes (write_guard.py says why).
    _STOP_GATE_HELPER_NAMES = (
        "CODE_REVIEWED", "DOCS_REFRESHED", "HANDOFF_GATE_FLAG", "HANDOFF_GATE_HOLD", "ONCE_FLAG_PREFIX",
        "OPERATOR_RELIEF_AGENT",
        "OPERATOR_RELIEF_NOTE_MIN_CHARS", "RELIEF_FLAGS", "STATE_DIR", "SpawnFailure", "_toml_parser",
        "atomic_write_text", "floor_text", "has_active_plan", "lock_file", "plan_completion",
        "python_command_hint", "read_stdin_safely", "read_toml_table",
        "relief_agents_line", "relief_flags", "resolve_project_root", "say_bad_stdin", "say_once", "spawn_checked",
        "split_command", "stop_gate_test_cmd", "unlock_file", "warn", "warn_exc",
    )
    for _name in _STOP_GATE_HELPER_NAMES:
        getattr(_hook_utils, _name)
except Exception as _skew:  # noqa: BLE001 -- a kept helper that predates its siblings (DEF-1176)
    if __name__ != "__main__":
        raise
    _start_refusal.refuse_on_helper_skew("stop_gate", "Stop", _skew)

STATE_DIR = _hook_utils.STATE_DIR  # single source of truth; see _hook_utils
# The relief records Gates 2 and 3 read. subagent_stop is their only writer;
# the table is shared so the reader cannot drift from the writer.
DOCS_REFRESHED = _hook_utils.DOCS_REFRESHED
CODE_REVIEWED = _hook_utils.CODE_REVIEWED

# Host-repo fallback. The harness's own three test files don't
# exist on a consumer repo, so a literal hard-coded CORE_TESTS list made
# Gate 1 silently no-op there. ``_resolve_core_tests`` reads
# ``reports/repo_fingerprint.json::test_commands`` when present (host
# repos after a fingerprint run); falls back to the harness defaults
# when missing (self-host before first analyze, or any pre-fingerprint
# state). The fallback list MUST stay stdlib-only — no espalier imports.
_HARNESS_DEFAULT_TESTS: tuple[str, ...] = (
    "tests/test_fingerprint.py",
    "tests/test_hooks.py",
    "tests/test_scanners.py",
    # Cheap (~3s) positional-pin guard so a magic_depth ``parents[N]``
    # line-pin shift reds on the fast path, not full-suite-only.
    "tests/test_scanner_magic_depth.py",
)


#: Every status ``_resolve_core_tests`` can return. Checked at construction, so a
#: status built anywhere -- a helper, a positional call -- that the gate does not
#: name cannot reach ``_gate_pytest``'s fallthrough and allow; the vocabulary pin
#: holds this set equal to the resolver's literals and the gate's branches.
_STATUSES: frozenset[str] = frozenset({
    "ok", "ok_env_override", "ok_detected", "ok_harness_defaults", "dormant_no_paths",
})


@dataclass(frozen=True)
class ResolvedTests:
    """Result of `_resolve_core_tests` (five statuses).

    status:
      - ``"ok"``: ``paths`` is non-empty; Gate 1 runs them under the hook
        interpreter's pytest.
      - ``"ok_env_override"``: ``ESPALIER_STOP_GATE_TEST_CMD`` set; ``paths``
        is empty and Gate 1 spawns ``commands`` (the one command, also in
        ``env_cmd``) at the repository root.
      - ``"ok_detected"``: no override; Gate 1 spawns ``commands`` -- the
        ``[extra_actions] test`` list espalier.toml declares (``source`` is
        ``"espalier.toml"``), else the first command the fingerprint detected
        (``"fingerprint"``) -- each at the repository root, the first non-zero
        exit blocking. The arm that was ``dormant_non_pytest`` until
        2026-10-08: a detected ``npm test`` is run, not announced.
      - ``"ok_harness_defaults"``: a pytest-shaped command naming no files on
        a tree holding one or more of the harness default test files;
        ``paths`` names them and ``note`` says the gate runs only those, not
        the suite (a partial gate is never silent).
      - ``"dormant_no_paths"``: no override, nothing declared, no command
        detected and no harness default file here: Gate 1 runs nothing and
        says so once a session. Every status literal ``_resolve_core_tests``
        returns is listed here; a pin derives the set from the source and
        reds on an unlisted one.
    env_cmd: the env-override command string (only non-empty when status is
        ``"ok_env_override"``); doctor's child-process probe reads it.
    commands: what Gate 1 spawns, in order, on ``ok_env_override`` and
        ``ok_detected``; empty otherwise.
    source: where ``commands`` came from -- ``"env"``, ``"espalier.toml"`` or
        ``"fingerprint"``; empty otherwise. ``_gate_pytest`` reads these
        rather than re-reading the environment or the file.
    """
    paths: list[str]
    status: str
    note: str
    env_cmd: str = ""
    commands: tuple[str, ...] = ()
    source: str = ""

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"unknown Gate 1 status {self.status!r}; declare it in _STATUSES")


# Pytest flags that consume the NEXT token as their value. Without
# this denylist, the naive "tok for tok in rest if not tok.startswith('-')"
# filter drops `-m` but keeps `security` (the marker value), and pytest
# then treats `security` as a positional file path -- "ERROR: file or
# directory not found: security". This fixes flag-values-as-paths. See
# bench/corpus/BC-OOS-007-pytest-flag-value-as-path.json (the parser fix
# is CI-pinned by the test below, but a future flag absent from
# _PYTEST_FLAGS_WITH_ARG has no runtime guard, so the bench runner can't
# faithfully exercise the class as in-scope).
#
# Long forms with `=` (e.g., `--override-ini=foo=bar`) are single tokens already
# caught by startswith("-"); it is the SEPARATED-ARG shape that needs the skip,
# in both the short and long spellings. (This comment previously said only
# separated short forms plus `--override-ini` needed it -- true until the long
# forms below were measured leaking, false the moment they were added.)
_PYTEST_FLAGS_WITH_ARG: frozenset[str] = frozenset({
    "-m",   # marker expression: `-m "security and not slow"`
    "-k",   # keyword filter: `-k test_foo`
    "-p",   # plugin name: `-p no:cacheprovider`
    "-c",   # config file path: `-c pytest.ini`
    "-o",   # ini override: `-o cache_dir=/tmp/x`
    "-r",   # short test summary chars: `-r fEsxX`
    "-W",   # warning filter: `-W error::DeprecationWarning`
    "-n",   # xdist worker count/`auto` -- a DECLARED dev dep, and this repo's
            # own documented invocation is `pytest -n auto`, so `auto` reached
            # pytest as a positional path.
    "--override-ini",  # long form of -o (separated arg shape)
    "--basetemp",      # temp dir path
    "--junitxml",      # report path
    "--maxfail",       # integer
    "--rootdir",       # dir path
    "--tb",            # traceback style token (`short`, `long`, `line`, `no`)
    "--deselect",      # a selector -- leaking it INVERTS deselect into select
})


def _is_pytest_shaped(cmd: object) -> bool:
    """True iff ``cmd`` is a pytest invocation Gate 1 can run: a bare ``pytest ...``
    or a ``python|python3 -m pytest ...`` form. Conservative (exact first-token /
    exact ``-m pytest`` prefix) -- stop_gate is a blocking gate and a false-positive
    here suppresses a real dormancy advisory, so we do NOT widen to startswith."""
    if not isinstance(cmd, str):
        return False
    tokens = cmd.strip().split()
    if not tokens:
        return False
    if tokens[0] == "pytest":
        return True
    return (
        len(tokens) >= 3
        and tokens[0] in ("python", "python3")
        and tokens[1] == "-m"
        and tokens[2] == "pytest"
    )


def _parse_pytest_positional_args(commands: list) -> list[str]:
    """Extract pytest positional args from a list of shell command strings.

    Recognizes ``pytest ...`` and ``python|python3 -m pytest ...`` forms.
    Non-pytest commands (``npm test``, ``go test ./...``, ``cargo test``,
    ``make test``) yield no positional args: the resolver runs them whole
    on its detected arm (since 2026-10-08; before that Gate 1 skipped them
    with a stderr line and was dormant on such a tree).

    Token-by-token state machine:
      - Tokens in ``_PYTEST_FLAGS_WITH_ARG`` consume the FOLLOWING token
        as their value (the next token is dropped, not kept).
      - Other tokens starting with ``-`` are boolean flags or long
        forms with ``=`` -- dropped as before.
      - Anything else is a positional arg (file path, ``dir/``,
        ``file.py::test`` selector).

    BC-041b: without the flag-value denylist a naive filter lets marker
    values (``security`` in ``pytest -m security``), keyword exprs
    (``test_foo`` in ``pytest -k test_foo``), plugin names
    (``no:cacheprovider`` in ``pytest -p no:cacheprovider``), config
    paths, ini overrides, and warning filters slip through as positional
    args. Gate 1 then runs pytest against those literal strings,
    producing ``ERROR: file or directory not found: <value>``.
    """
    positional: list[str] = []
    for cmd in commands:
        cmd_str = str(cmd).strip()
        if not cmd_str:
            continue
        tokens = cmd_str.split()
        if not _is_pytest_shaped(cmd_str):
            # Not a pytest form, so no positional paths to take from it; the
            # resolver's detected arm runs the command whole.
            continue
        rest = tokens[3:] if tokens[:3] in (
            ["python", "-m", "pytest"], ["python3", "-m", "pytest"]
        ) else tokens[1:]

        skip_next = False
        for tok in rest:
            if skip_next:
                skip_next = False
                continue
            if tok in _PYTEST_FLAGS_WITH_ARG:
                skip_next = True
                continue
            if tok.startswith("-"):
                continue
            positional.append(tok)
    return positional


def _read_fingerprint_test_commands(repo_root: Path) -> list:
    """Return ``test_commands`` (a list of shell strings) from the fingerprint,
    or ``[]`` when absent/unreadable/non-dict. Routes through load_json_dict_safe
    so a non-dict fingerprint can't crash the fail-closed Gate-1 resolution."""
    fingerprint_path = repo_root / "reports" / "repo_fingerprint.json"
    if not fingerprint_path.is_file():
        return []
    try:
        # Bytes, not text: the helper decodes tolerantly (a BOM, a stray byte).
        # A strict read here raised UnicodeDecodeError -- a ValueError the
        # OSError handler let past into the fail-closed crash guard (DEF-829).
        data = load_json_dict_safe(fingerprint_path.read_bytes())
    except OSError as exc:
        # An unreadable fingerprint falls back to the harness test defaults:
        # recorded once a session, since this hook exits 0 and a stderr line
        # alone reaches the debug log only (the protocol pin).
        _hook_utils.say_once(
            repo_root, f"fingerprint-read-{type(exc).__name__}", "stop_gate",
            "stop_failed_open_fingerprint_read",
            f"reports/repo_fingerprint.json could not be read ({type(exc).__name__}); "
            "Gate 1 falls back to the harness test defaults",
            fault=type(exc).__name__,
        )
        return []
    cmds = data.get("test_commands")
    return cmds if isinstance(cmds, list) else []


def _toml_text_declares_test(root: Path) -> bool:
    """Whether ``espalier.toml`` carries a ``test`` key under ``[extra_actions]``,
    read by regex for the host with no TOML parser: full-line comments dropped,
    the table's region taken up to the next header. Best-effort, and only ever
    used to SAY that the key could not be read -- never to run it."""
    try:
        toml_text = (root / "espalier.toml").read_text(encoding="utf-8", errors="replace")
    except OSError:  # fail-open: ok deliberate -- no file, or an unreadable one: there is no key to say anything about, and the detected command runs
        return False
    toml_text = re.sub(r"(?m)^\s*#.*$", "", toml_text)
    header = re.search(r"(?m)^[ \t]*\[extra_actions\][ \t]*$", toml_text)
    if header is None:
        return False
    region = toml_text[header.end():]
    nxt = re.search(r"(?m)^[ \t]*\[", region)
    if nxt is not None:
        region = region[: nxt.start()]
    return re.search(r"(?m)^[ \t]*test[ \t]*=", region) is not None


def _declared_test_commands(root: Path) -> tuple[str, ...]:
    """``[extra_actions] test`` from ``<root>/espalier.toml`` -- the declared
    test command ``/preflight`` already runs -- as a tuple, or ``()`` when the
    file, the table or the key is absent, or the key is the empty list (what
    the engine reads as not declared). Any other value that is not a list of
    non-empty strings is ignored and SAID once a session
    (``stop_failed_open_toml_test_shape``): a setting that does nothing is the
    defect. A file that will not parse is said once too, and the detected
    command runs. Read through ``_hook_utils.read_toml_table`` (``tomllib``,
    or ``tomli`` on 3.10); with neither importable the table cannot be read,
    the detected command runs, and a key the file carries (found by regex)
    is said once -- a setting that does nothing with nobody told is the
    defect, and the docs say the key needs 3.11+ or tomli.
    """
    if _hook_utils._toml_parser() is None:
        if _toml_text_declares_test(root):
            _hook_utils.say_once(
                root, "gate1-toml-no-parser", "stop_gate", "stop_failed_open_toml_no_parser",
                "espalier.toml declares [extra_actions] test, but this interpreter has no TOML "
                "parser (tomllib is Python 3.11+; install tomli below it), so Gate 1 uses the "
                "detected command",
            )
        return ()
    table = _hook_utils.read_toml_table(root, on_error=lambda problem: _hook_utils.say_once(
        root, "gate1-toml", "stop_gate", "stop_failed_open_toml_unreadable",
        f"espalier.toml could not be parsed ({problem}); Gate 1 uses the detected command",
    ))
    actions = (table or {}).get("extra_actions")
    declared = actions.get("test") if isinstance(actions, dict) else None
    if declared is None or declared == []:
        # Absent, or declared empty: the engine's reader treats ``test = []``
        # as not declared and says nothing, so the hook agrees (two readers of
        # one key must not disagree); the detected command runs.
        return ()
    if isinstance(declared, list) and all(isinstance(c, str) and c.strip() for c in declared):
        return tuple(c.strip() for c in declared)
    _hook_utils.say_once(
        root, "gate1-toml-shape", "stop_gate", "stop_failed_open_toml_test_shape",
        "espalier.toml [extra_actions] test is not a list of command strings; "
        "Gate 1 uses the detected command",
    )
    return ()


def _resolve_core_tests(repo_root: Path) -> ResolvedTests:
    """Return what Gate 1 runs here, with its dormancy visible.

    Order (the operator's 2026-10-08 decision on where the stop-time test
    command lives): ``ESPALIER_STOP_GATE_TEST_CMD`` first; then
    ``[extra_actions] test`` from ``espalier.toml`` (the repository's declared
    test command, the one ``/preflight`` runs; it travels with a clone, the
    variable does not); then the fingerprint. Of the fingerprint
    (``reports/repo_fingerprint.json::test_commands``, SHELL COMMAND STRINGS
    written by ``espalier.analyze.detect_tests``, never file paths): a pytest
    form naming files runs those files under the hook interpreter's pytest
    (``ok``); a pytest form naming none on a tree holding the harness default
    test files runs only those and says so (``ok_harness_defaults``, the
    self-host shape); otherwise the first detected command runs whole at the
    repository root (``ok_detected`` -- ``npm test``, ``go test ./...``,
    ``cargo test``, or a bare ``pytest -q`` on a tree without the default
    files). Nothing anywhere is ``dormant_no_paths``, said once a session.

    The mode (``ESPALIER_STOP_GATE``) stays environment-only. Stdlib-only --
    no espalier imports (tools/cc/ isolation rule).
    """
    env_override = _hook_utils.stop_gate_test_cmd().strip()
    if env_override:
        return ResolvedTests(
            paths=[], status="ok_env_override",
            note=f"Gate 1 will run env-override: {env_override!r}",
            env_cmd=env_override, commands=(env_override,), source="env",
        )

    declared = _declared_test_commands(repo_root)
    if declared:
        return ResolvedTests(
            paths=[], status="ok_detected", source="espalier.toml", commands=declared,
            note=("Gate 1 runs the test command espalier.toml declares "
                  f"([extra_actions] test): {' && '.join(declared)!r}; "
                  "ESPALIER_STOP_GATE_TEST_CMD overrides it"),
        )

    raw_cmds = _read_fingerprint_test_commands(repo_root)

    positional = _parse_pytest_positional_args(raw_cmds)
    if positional:
        return ResolvedTests(paths=positional, status="ok", note="")

    has_pytest_shaped = any(_is_pytest_shaped(c) for c in raw_cmds)
    defaults = [str(p) for p in _HARNESS_DEFAULT_TESTS]
    defaults_present = [p for p in defaults if (repo_root / p).exists()]
    if defaults_present and (not raw_cmds or has_pytest_shaped):
        # A pytest tree that happens to hold one of the harness default file
        # names used to resolve `ok` with an empty note here, so Gate 1 ran that
        # one file, said nothing, and allowed a Stop while the rest of the suite
        # failed (case D of the measurement). A partial gate is never silent.
        return ResolvedTests(
            paths=defaults_present, status="ok_harness_defaults",
            note=(
                "Gate 1 runs only the harness default test files present here "
                f"({', '.join(defaults_present)}), not your suite. Set "
                "ESPALIER_STOP_GATE_TEST_CMD=<your test command> to run it."
            ),
        )

    detected_all = [c.strip() for c in raw_cmds if isinstance(c, str) and c.strip()]
    if detected_all:
        detected, others = detected_all[0], detected_all[1:]
        # The first, as /preflight takes it; a polyglot tree's other commands
        # are named so a partial gate is never silent.
        not_run = (
            f"; also detected and not run: {', '.join(others)} -- declare "
            "[extra_actions] test = [...] in espalier.toml to run them all"
            if others else ""
        )
        return ResolvedTests(
            paths=[], status="ok_detected", source="fingerprint", commands=(detected,),
            note=(f"Gate 1 runs the detected test command {detected!r}; "
                  "[extra_actions] test in espalier.toml or ESPALIER_STOP_GATE_TEST_CMD "
                  f"overrides it{not_run}"),
        )
    return ResolvedTests(
        paths=[], status="dormant_no_paths",
        note=(
            "Gate 1 dormant: no test command is declared or detected and the "
            "harness default test files are not here, so it runs nothing. "
            "Declare [extra_actions] test in espalier.toml, or set "
            "ESPALIER_STOP_GATE_TEST_CMD=<your test command> in the shell that "
            "launches Claude Code."
        ),
    )


#: Once-per-session guard for the override that cannot be started: set after
#: the block that reports it, cleared by session_start on a new session.
GATE1_SPAWN_FAILURE_REPORTED_FLAG = "gate1_spawn_failure_reported"


def _spawn_remedy_platform() -> str:
    """``os.name``, behind a seam a test can turn: the remedy a spawn failure
    prints is the platform's own."""
    return os.name


_SOURCE_PHRASE: dict[str, str] = {
    "env": "your ESPALIER_STOP_GATE_TEST_CMD",
    "espalier.toml": "the `test` command espalier.toml declares under [extra_actions]",
    "fingerprint": "the test command detected from this repository's files (the fingerprint's test_commands)",
}
_SOURCE_DO: dict[str, str] = {
    "env": _denial_reasons.GATE_COMMAND_DO_ENV,
    "espalier.toml": _denial_reasons.GATE_COMMAND_DO_TOML,
    "fingerprint": _denial_reasons.GATE_COMMAND_DO_FINGERPRINT,
}
_SOURCE_DONT: dict[str, str] = {
    "env": _denial_reasons.GATE_COMMAND_DONT_ENV,
    "espalier.toml": _denial_reasons.GATE_COMMAND_DONT_TOML,
    "fingerprint": _denial_reasons.GATE_COMMAND_DONT_FINGERPRINT,
}
_SOURCE_TIMEOUT_DO: dict[str, str] = {
    "env": _denial_reasons.GATE_COMMAND_TIMEOUT_DO_ENV,
    "espalier.toml": _denial_reasons.GATE_COMMAND_TIMEOUT_DO_TOML,
    "fingerprint": _denial_reasons.GATE_COMMAND_TIMEOUT_DO_FINGERPRINT,
}
# Tokens no shell interprets here: an entry carrying one would start its first
# program alone (`cd web && npm test` starts /usr/bin/cd on macOS, which exits
# 0 with `npm test` never run -- a green gate over a suite that did not run;
# the 2026-10-08 review drove it), so it is refused before the spawn.
_SHELL_SYNTAX_TOKENS = frozenset({"&&", "||", "|", ";", "&"})
_SHELL_SYNTAX_PREFIXES = (">", "<", "2>", "1>", "$(", "`")


def _shell_syntax_token(parts: list[str]) -> str:
    """The first token of a split command that is shell syntax, or ``""``."""
    for tok in parts:
        if tok in _SHELL_SYNTAX_TOKENS or tok.startswith(_SHELL_SYNTAX_PREFIXES) or tok.endswith(";"):
            return tok
    return ""


def _spawn_failure_digest(source: str, cmd: str) -> str:
    """One line of the once-a-session flag file: the command and its source,
    never the text -- a second broken entry gets its own report."""
    return hashlib.sha256(f"{source}\0{cmd}".encode("utf-8", "replace")).hexdigest()[:16]


def _spawn_failure_reported(root: Path, digest: str) -> bool:
    try:
        return digest in (root / STATE_DIR / GATE1_SPAWN_FAILURE_REPORTED_FLAG).read_text(
            encoding="utf-8", errors="replace").split()
    except OSError:  # fail-open: ok deliberate -- an unreadable flag reads as not reported, so the fault is told again (the safe direction)
        return False


def _mark_spawn_failure_reported(root: Path, digest: str) -> None:
    flag = root / STATE_DIR / GATE1_SPAWN_FAILURE_REPORTED_FLAG
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        with flag.open("a", encoding="utf-8") as fh:
            fh.write(digest + "\n")
    except OSError:
        pass  # told again on the next Stop, which is the safe direction


def _source_phrase(source: str) -> str:
    return _SOURCE_PHRASE.get(source, f"the test command ({source or 'unknown source'})")


def _run_command_gate(root: Path, commands: tuple[str, ...], *, source: str) -> int:
    """Gate 1 on a command the repository or the operator named: each of
    ``commands`` in order, split without a shell and started at ``root``; the
    first non-zero exit blocks with its tail, a timeout blocks naming the
    budget, a command that cannot start -- or carries shell syntax -- blocks
    once a session per command. Returns 0 on green (an empty tuple is green:
    the resolver never hands one over, and a caller that does has nothing to
    run). ``source`` says where the commands came from -- ``"env"`` (the
    override), ``"espalier.toml"`` (the declared ``[extra_actions] test``) or
    ``"fingerprint"`` (the detected command) -- and reaches the reason text and
    the audit record (``details.source``). The once-a-session report is per
    command (the flag file holds one digest per reported command): a list with
    two broken entries reports the second on the Stop after the first, and a
    shared flag would have waved it through unreported (the review drove it).
    Until 2026-10-08 this was ``_run_env_override_gate`` and ran the override
    alone; the detected arm was dormant."""
    for cmd in commands:
        rc = _run_one_command(root, cmd, source=source)
        if rc != 0:
            return rc
    return 0


def _run_one_command(root: Path, cmd: str, *, source: str) -> int:
    """One command of ``_run_command_gate``. ``shell=False`` -- arguments
    split via ``_hook_utils.split_command`` so quoted strings survive, and an
    entry carrying shell syntax is refused before the spawn (see
    ``_shell_syntax_token``). Returns 0 on green; calls ``_audit_block(...)``
    on non-zero exit, on timeout and on a command that cannot be started
    (matches Gate 1 contract; see ``_gate_pytest``); ``root`` is where the
    command runs and where the record is filed.

    The command runs AT ``root``, as the pytest branch and Gate 4 do. Without
    it the override ran in the hook process's directory: a relative test glob
    matched nothing from a subdirectory, the runner exited 0 over zero tests
    and the Stop was allowed with a failing test in the tree, while a literal
    relative path blocked a green one.

    A spawn failure BLOCKS, once a session per command. It allowed until
    2026-09-29, on the pytest branch's reasoning that a gate which could not
    run is an infrastructure fault; but this command is configuration the
    operator wrote (or the manifest's own test script), so the failure recurs
    on every Stop, and on Windows the plain spelling of a Node command never
    starts without a shell. The gate they had armed was green on every Stop
    and wrote no record.

    Once, not every Stop: the variable is read when Claude Code launches, so
    nothing done in the session repairs it (a declared or detected command is
    re-read each Stop, and a respelling there is a new command with its own
    report). A block on every Stop returns from ``_run_main`` at Gate 1 every
    turn, and the continuation's Stop passes the loop guard before any gate
    runs, so the docs gate, the review gate and the blueprint finalize would
    not run again until the next launch. After the first report the failure
    goes to stderr -- the debug log, this hook exiting 0 -- and the gates
    behind this one run. The flag is written AFTER the block, so a flag that
    cannot be written costs a second block, never a silent gate.

    ``posix=False`` on Windows is required, not cosmetic. In POSIX mode
    ``shlex.split`` treats ``\\`` as an escape character, so a native path --
    ``C:\\Python\\python.exe`` -- is silently rewritten to ``C:Pythonpython.exe``
    and the spawn fails on a path the operator never typed. Measured on the
    Windows CI runner: the override never ran, the gate emitted no decision,
    and the caller got empty stdout where JSON was contracted.
    ``posix=False`` keeps quotes in the tokens, so strip them afterwards to
    preserve the "quoted strings survive" half of the contract."""
    phrase = _source_phrase(source)
    result: "subprocess.CompletedProcess[str] | _hook_utils.SpawnFailure"
    try:
        parts = _hook_utils.split_command(cmd)
    except ValueError as exc:
        # Unbalanced quotes: the command cannot be split, so it cannot start.
        # It takes the SAME once-a-session branch as a spawn failure below: a
        # block on every Stop would switch the gates behind this one off for
        # the session (the 2-A review drove three Stops, three blocks, no flag).
        result = _hook_utils.SpawnFailure((cmd,), "UnbalancedQuotes", None, os_error_text(exc))
    else:
        if not parts:
            # Gate 1 skips: recorded once a session (exit 0; stderr alone
            # would reach the debug log only).
            _hook_utils.say_once(
                root, "env-override-empty", "stop_gate", "stop_failed_open_env_override_empty",
                f"Gate 1 skipped: {phrase} holds no command once split",
            )
            return 0
        shell_token = _shell_syntax_token(parts)
        if shell_token:
            result = _hook_utils.SpawnFailure(
                (cmd,), "ShellSyntax", None, f"the token {shell_token!r} is shell syntax",
            )
        else:
            try:
                # subprocess-contract: ok the-test-command-the-operator-or-the-repository-named-via-ESPALIER_STOP_GATE_TEST_CMD-or-extra_actions-test-or-the-fingerprint
                result = _hook_utils.spawn_checked(
                    parts, root=root,
                    capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=STOP_INNER_BUDGET,
                    cwd=str(root),
                )
            except subprocess.TimeoutExpired:
                return _audit_block(
                    root, "stop_blocked_pytest",
                    _denial_reasons.GATE_COMMAND_TIMEOUT.format(
                        cmd=cmd, source=phrase, budget=STOP_INNER_BUDGET,
                        do=_SOURCE_TIMEOUT_DO.get(source, _denial_reasons.GATE_COMMAND_TIMEOUT_DO_FINGERPRINT),
                    ),
                    gate=1, rule="GATE_COMMAND_TIMEOUT", source=source,
                )
    if isinstance(result, _hook_utils.SpawnFailure):
        digest = _spawn_failure_digest(source, cmd)
        if _spawn_failure_reported(root, digest):
            # voice: twin the first Stop of this session blocked with this fault and its remedy
            sys.stderr.write(
                f"(stop_gate) Gate 1 still cannot start {ascii(cmd)} "
                f"({result.error}; {phrase}); reported earlier this session, so the "
                "gates behind it run\n"
            )
            return 0
        if result.error == "UnbalancedQuotes":
            remedy = _denial_reasons.GATE_COMMAND_SPAWN_REMEDY_QUOTING
        elif result.error == "ShellSyntax":
            remedy = _denial_reasons.GATE_COMMAND_SPAWN_REMEDY_SHELL_SYNTAX
        else:
            remedy = (
                _denial_reasons.GATE_COMMAND_SPAWN_REMEDY_WINDOWS
                if _spawn_remedy_platform() == "nt"
                else _denial_reasons.GATE_COMMAND_SPAWN_REMEDY_POSIX
            )
        do = _SOURCE_DO.get(source, _denial_reasons.GATE_COMMAND_DO_FINGERPRINT).format(remedy=remedy)
        dont = _SOURCE_DONT.get(source, _denial_reasons.GATE_COMMAND_DONT_FINGERPRINT)
        blocked = _audit_block(
            root, "stop_blocked_pytest",
            _denial_reasons.GATE_COMMAND_SPAWN_FAILED.format(
                cmd=cmd,
                resolution=result.resolution,
                error_class=result.error,
                error_text=result.detail or result.resolved or "no program of that name on PATH",
                source=phrase,
                dont=dont,
                do=do,
            ),
            gate=1, rule="GATE_COMMAND_SPAWN_FAILED", error=result.error, source=source,
        )
        _mark_spawn_failure_reported(root, digest)
        return blocked
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip()
        return _audit_block(
            root, "stop_blocked_pytest",
            _denial_reasons.GATE_COMMAND_FAILED.format(
                cmd=cmd, source=phrase,
                returncode=result.returncode,
                tail=tail[-800:],
            ),
            gate=1, rule="GATE_COMMAND_FAILED", returncode=result.returncode, source=source,
        )
    return 0



STOP_GATE_MODE_ENV = "ESPALIER_STOP_GATE"
STOP_GATE_LIGHT = "light"
STOP_GATE_FULL = "full"
STOP_GATE_SCAN_CLEAN = "scan-clean"  # opt-in advisory session signals


def _stop_gate_mode(root: Path) -> str:
    """Resolve Stop gate mode from env. Default light; unknown values warn.

    ``scan-clean`` is in the recognized set — without it the value would hit
    the unknown-value branch, warn, and silently fall back to light, leaving
    the advisory reads permanently inert. It is a single value, deliberately
    NOT composable with ``full``, so the independent exact-match parsers in
    session_start.py / statusline.py stay consistent (no compound-token
    grammar)."""
    raw = os.environ.get(STOP_GATE_MODE_ENV, STOP_GATE_LIGHT).strip().lower()
    if raw in {STOP_GATE_LIGHT, STOP_GATE_FULL, STOP_GATE_SCAN_CLEAN}:
        return raw
    # A misspelt mode runs the light gate where the operator asked for more:
    # recorded once a session (exit 0; stderr alone reaches the debug log).
    _hook_utils.say_once(
        root, "stop-gate-mode", "stop_gate",
        "stop_failed_open_unknown_mode",
        f"unknown {STOP_GATE_MODE_ENV}={raw!r}; the light Stop gate runs",
    )
    return STOP_GATE_LIGHT


_resolve_project_root = _hook_utils.resolve_project_root


def block(reason: str) -> int:
    """Print Stop block JSON and return a truthy sentinel for gate control flow.

    Stop event schema differs from PreToolUse: top-level `decision` and
    `reason`, not nested under hookSpecificOutput. Channel-XOR house rule: the
    structured block is stdout JSON with exit 0 and nothing on stderr. See
    docs/SHARP_EDGES.md "Hook Exit Codes — Channel XOR".

    Channel-XOR: stdout JSON is the structured channel. We do NOT mirror to
    stderr (Claude Code renders ``reason`` to the operator from the JSON).
    Earlier versions dual-channeled for terminal visibility; dropped to
    preserve forward compatibility if CC ever feeds stderr-on-exit-0 back
    as advisory context.

    Returns 1 as an internal sentinel so callers can check `if result:`.
    main() always translates any blocked result to sys.exit(0).
    """
    output = {
        "decision": "block",
        "reason": reason,
    }
    print(json.dumps(output))
    return 1  # Internal sentinel; main() exits 0.


def _audit_block(root: Path, event_type: str, reason: str, **details: object) -> int:
    """Best-effort ``append_audit`` then ``block`` -- the audited-block funnel,
    the Stop hook's twin of the PreToolUse hooks' ``_audit_deny``. Every block
    routes through here, the crash guard's included (DEF-803), so
    ``/status --log`` can say why a session was returned. ``details`` are
    metadata only (the gate number, the rule constant's name, the write
    count, an exit code, an exception's class) -- never the reason text,
    which can quote a pytest tail or an exception message. A record write that fails neither raises
    nor prints: the writer's own OSError branch is told to stay ``quiet`` (it
    would otherwise warn on stderr beside the block JSON), anything else it
    raises is swallowed here, and a hook that could not log still has to gate
    (a visibility layer, not a security boundary). Hooks cannot share this via
    ``_hook_utils`` (``_integrity`` imports it; a shared owner there would
    cycle)."""
    try:
        _integrity.append_audit(root, {"event_type": event_type, "details": details}, quiet=True)
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; the block path stays silent
        pass
    return block(reason)


def _record_maintenance_bypass(root: Path, write_count: int) -> None:
    """One advisory audit record per session when MAINTENANCE_MODE skips Gates
    2 and 3 (DEF-789; write_guard and plan_guard write the sibling record for
    the checks the flag switches off in them). Neither a refusal nor a pause --
    nothing was blocked -- so the reader keeps it out of the tail and counts it
    on its own line: a box that runs maintenance mode all day otherwise reads
    as a day on which no hygiene gate fired. Once per session, guarded by the
    shared per-hook flag ``_integrity`` owns and session_start clears. The
    record is written BEFORE the guard, so a failed flag write yields a
    duplicate record on the next Stop rather than a silent session;
    ``append_audit`` is best-effort and ``quiet`` (a visibility layer, never a
    gate). The literal is spelled here, at the writer, so the ledger probe and
    the audit-log tests can see it reach ``append_audit``; ``_integrity``
    carries the reader's set and the tests pin the two equal. ``details`` are
    metadata only."""
    if _integrity.maintenance_bypass_recorded(root, "stop_gate"):
        return
    try:
        _integrity.append_audit(
            root,
            {"event_type": "stop_bypassed_maintenance_mode",
             "details": {"hook": "stop_gate", "gates": "2,3", "write_count": write_count}},
            quiet=True,
        )
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; the bypass path stays silent
        pass
    _integrity.mark_maintenance_bypass_recorded(root, "stop_gate")


def _read_write_count(root: Path) -> int:
    """Read the session write counter."""
    counter_path = root / STATE_DIR / "write_count"
    if not counter_path.exists():
        return 0
    try:
        return int(counter_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError) as exc:
        # Fail open, with voice: a counter that reads as zero moves the docs
        # and review gates' thresholds, so a corrupt or unreadable one is said.
        _hook_utils.say_once(
            root, "counter-write_count", "stop_gate", "stop_failed_open_counter",
            f"write_count could not be read ({type(exc).__name__}); the docs and review gates see zero writes this session",
            fault=type(exc).__name__,
        )
        return 0


# ── agent-session trajectory signals (advisory, stderr-only) ──

TOOL_CALL_COUNTER_FILE = "tool_call_count"
LAST_TOOL_FILE = "last_tool"
SESSION_LENGTH_BASELINE_FILE = "session_length_baseline"   # PERSISTS (rolling)
SESSION_LENGTH_RECORDED_FLAG = "session_length_recorded"   # cleared per session
# Calibration-deferred (advisory only; NEVER a BLOCK / exit 1 / stdout):
TRAJECTORY_MULTIPLIER = 3.0          # uncalibrated (advisory; tune from real history): session > M×median -> warn
MIN_SESSIONS_FOR_TRAJECTORY = 3      # uncalibrated (advisory; tune from real history): priors before judging
RECURSIVE_REPEAT_THRESHOLD = 25      # uncalibrated (advisory; tune from real history): identical-tool streak -> warn
SESSION_LENGTH_HISTORY_CAP = 20      # rolling-window size


def _read_tool_call_count(root: Path) -> int:
    """Read this session's tool_call_count (written by reflect_trigger;
    per-session, cleared at SessionStart). Mirrors ``_read_write_count``."""
    counter_path = root / STATE_DIR / TOOL_CALL_COUNTER_FILE
    if not counter_path.exists():
        return 0
    try:
        return int(counter_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):  # fail-open: ok telemetry -- an advisory session signal; a corrupt counter is no signal
        return 0


def _read_last_tool_streak(root: Path) -> int:
    """Read the identical-consecutive-tool streak from last_tool."""
    path = root / STATE_DIR / LAST_TOOL_FILE
    if not path.exists():
        return 0
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        # `or 0` coalesces an explicit null streak (producer drift); TypeError
        # guards int(None) — mirrors reflect_trigger._track_last_tool. This
        # reader sits under stop_gate's FAIL-CLOSED umbrella, so an uncaught
        # raise here would BLOCK the Stop, not just skip an advisory.
        return int(obj.get("streak", 0) or 0) if isinstance(obj, dict) else 0
    # fail-open: ok telemetry -- an advisory session signal; a corrupt record is no signal
    except (ValueError, TypeError, OSError):  # JSONDecodeError ⊂ ValueError
        return 0


def _advise_session_signals(root: Path) -> None:
    """Agent-trajectory advisories. STDERR-ONLY, returns None —
    NEVER blocks, NEVER emits stdout (block() is stop_gate's sole stdout
    channel). Runs at most ONCE per session: the ``session_length_recorded``
    guard (cleared at SessionStart) stops a re-firing Stop from polluting the
    rolling baseline with partial-session samples.

    Trajectory anomaly: this session's tool_call_count vs M× the rolling median
    of prior sessions. Recursive-loop signal: a long identical-consecutive-tool
    streak. Every threshold is uncalibrated (advisory); this is signal, not a
    gate.
    """
    state_dir = root / STATE_DIR
    if (state_dir / SESSION_LENGTH_RECORDED_FLAG).exists():
        return  # already recorded this session — don't double-count
    count = _read_tool_call_count(root)
    if count <= 0:
        return  # no session-signal telemetry this session (no-op)

    history: list = []
    base_path = state_dir / SESSION_LENGTH_BASELINE_FILE
    if base_path.exists():
        try:
            obj = json.loads(base_path.read_text(encoding="utf-8"))
            if isinstance(obj, dict) and isinstance(obj.get("history"), list):
                history = [int(x) for x in obj["history"] if isinstance(x, (int, float))]
        # fail-open: ok telemetry -- the rolling baseline is advisory; a corrupt history starts over
        except (ValueError, OSError):  # JSONDecodeError ⊂ ValueError
            history = []

    # Trajectory-length anomaly vs the rolling median of PRIOR sessions.
    if len(history) >= MIN_SESSIONS_FOR_TRAJECTORY:
        median = statistics.median(history)
        if median > 0 and count > TRAJECTORY_MULTIPLIER * median:
            # voice: debug-log advisory only, and Stop has no quiet channel to Claude: its additionalContext continues the turn
            sys.stderr.write(
                f"(stop_gate) [157-G advisory] session trajectory anomaly: "
                f"{count} tool calls vs rolling median {median:.0f} "
                f"(>{TRAJECTORY_MULTIPLIER:g}x). Advisory only -- not a gate.\n"
            )

    # Recursive-call burst (identical-consecutive tool streak).
    streak = _read_last_tool_streak(root)
    if streak >= RECURSIVE_REPEAT_THRESHOLD:
        # voice: debug-log advisory only, and Stop has no quiet channel to Claude: its additionalContext continues the turn
        sys.stderr.write(
            f"(stop_gate) [157-F advisory] {streak} consecutive identical tool "
            f"calls this session (possible recursive loop). Advisory only.\n"
        )

    # Record this session ONCE. Set the guard FIRST so that if the history
    # write later fails, a re-firing Stop still sees the guard and does NOT
    # re-append — guarding against rolling-baseline pollution with
    # partial-session samples (the alternative ordering could double-count).
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / SESSION_LENGTH_RECORDED_FLAG).write_text("", encoding="utf-8")
    except OSError:  # fail-open: ok telemetry -- the recording guard could not be set, so the sample is skipped (no pollution risk)
        return  # couldn't set the guard — skip recording (no pollution risk)
    history.append(count)
    history = history[-SESSION_LENGTH_HISTORY_CAP:]
    try:
        _hook_utils.atomic_write_text(base_path, json.dumps({"history": history}))
    except OSError:
        pass  # guard already set; this session's sample is simply lost. Advisory.


def _gate_scan_clean(root: Path) -> None:
    """Opt-in advisory — warn when the most recent scan run's
    total findings rose vs the prior run. Reads ``reports/scan_telemetry.jsonl``
    AS A FILE (json.loads per line) — NEVER imports espalier (tools/cc
    isolation). STDERR-only, returns None; no-op when <2 runs of telemetry
    exist (the 'no scan ran / telemetry absent' case). Compares the two most
    recent scan runs (telemetry is not session-tagged)."""
    path = root / "reports" / "scan_telemetry.jsonl"
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):  # fail-open: ok telemetry -- the scan-clean advisory reads a telemetry file; unreadable is no advisory
        return
    fires_by_run: dict = {}
    order: list = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        run = rec.get("run_ts")
        if run is None:
            continue
        if run not in fires_by_run:
            fires_by_run[run] = 0
            order.append(run)
        try:
            fires_by_run[run] += int(rec.get("fires", 0) or 0)
        except (TypeError, ValueError):
            pass
    if len(order) < 2:
        return  # need a prior run to compare against
    prior, latest = fires_by_run[order[-2]], fires_by_run[order[-1]]
    if latest > prior:
        # voice: debug-log advisory only, and Stop has no quiet channel to Claude: its additionalContext continues the turn
        sys.stderr.write(
            f"(stop_gate) [157-E advisory] scan findings rose: {prior} -> "
            f"{latest} across the two most recent scan runs. Advisory only.\n"
        )


# ── Gate 1: pytest ─────────────────────────────────────────────────────────────────

def _gate_pytest(root: Path) -> int:
    """Run core test suite. DENY if any tests fail. Opt-in via STOP_GATE_FULL."""
    # Resolve what runs here: the override, the declared [extra_actions]
    # test, or the fingerprint (file paths under pytest, the harness
    # defaults on a self-host-shaped tree, else the detected command
    # whole). A tree with nothing to run is a once-a-session record, never
    # a silent green.
    resolved = _resolve_core_tests(root)
    if resolved.status == "dormant_no_paths":
        # Gate 1 runs nothing here: recorded once a session, since this hook
        # exits 0 and a stderr line alone reaches the debug log only (the
        # protocol pin); the SessionStart banner names it at boot under full.
        _hook_utils.say_once(
            root, "gate1-dormant", "stop_gate", "stop_failed_open_gate1_dormant", resolved.note,
        )
        return 0
    if resolved.status == "ok_harness_defaults":
        # Runs below, and says what it is running: a partial gate is never
        # silent -- the banner's dormancy note says it at boot.
        # voice: twin the SessionStart startup banner's stop-gate dormancy note names this (the compact banner omits it)
        sys.stderr.write(f"(stop_gate) {resolved.note}\n")
    if resolved.status in ("ok_env_override", "ok_detected"):
        # voice: debug-log names the command about to run and its source; a failure blocks the Stop with both named
        sys.stderr.write(f"(stop_gate) {resolved.note}\n")
        return _run_command_gate(root, resolved.commands, source=resolved.source)
    test_args = [t for t in resolved.paths if (root / t).exists()]
    if not test_args:
        # No test files found: the gate skips, and says which paths it looked
        # for -- a fingerprint whose test paths all moved was a silent green.
        # Recorded once a session: this hook exits 0, so a stderr line alone
        # reaches the debug log only (the protocol pin).
        _hook_utils.say_once(
            root, "pytest-no-paths", "stop_gate", "stop_failed_open_pytest_no_paths",
            "Gate 1 skipped: none of the fingerprint's test paths exist "
            f"under {root} ({', '.join(resolved.paths) or 'no paths resolved'})",
        )
        return 0

    try:
        result = _hook_utils.spawn_checked(
            [sys.executable, "-m", "pytest"] + test_args + ["-q", "--tb=short"],
            root=root,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=STOP_INNER_BUDGET,
            cwd=str(root),
        )
        if isinstance(result, _hook_utils.SpawnFailure):
            # An infrastructure fault, not a failing test: allow, and say so
            # once -- a Stop that re-blocks on every fault is the hostile shape.
            _hook_utils.say_once(
                root, "pytest-spawn", "stop_gate", "stop_failed_open_pytest_spawn",
                f"Gate 1 skipped: pytest could not start ({result.error}; {result.resolution})",
                fault=result.error, resolved=result.resolved,
            )
            return 0
        if result.returncode != 0 and "No module named pytest" in (result.stderr or ""):
            # The hook interpreter has no pytest: an infrastructure fault, not a
            # failing test, and the same exit code (1) would otherwise block every
            # Stop. Reachable on a Windows host whose hooks are wired to the
            # launcher's system Python (`py -3`) while the project's pytest lives
            # in a virtualenv: init prefers the launcher to a venv-only name,
            # because the venv vanishes with the shell that settings.json outlives.
            _hook_utils.say_once(
                root, "pytest-missing", "stop_gate", "stop_failed_open_pytest_missing",
                f"Gate 1 skipped: the hook interpreter ({sys.executable}) has no "
                "pytest -- install pytest for it, or set ESPALIER_STOP_GATE_TEST_CMD "
                "to the command that runs your tests",
                fault="No module named pytest", resolved=sys.executable,
            )
            return 0
        if result.returncode != 0:
            output = (result.stdout + result.stderr).strip()
            lines = output.splitlines()
            tail = "\n".join(lines[-20:]) if len(lines) > 20 else output
            return _audit_block(
                root, "stop_blocked_pytest",
                _denial_reasons.GATE_PYTEST_FAILED.format(tail=tail),
                gate=1, rule="GATE_PYTEST_FAILED", returncode=result.returncode,
            )
        return 0
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        # Don't block on test infrastructure failure -- but never allow
        # unannounced: a suite that outgrew STOP_INNER_BUDGET is killed here,
        # and a stderr line alone reached the debug log only (exit 0; the
        # protocol pin). Recorded once a session per fault class, naming the
        # error type so the operator can tell a timeout (raise
        # STOP_INNER_BUDGET) from a missing interpreter (fix PATH) at a glance.
        cls = type(e).__name__
        _hook_utils.say_once(
            root, f"pytest-did-not-run-{cls}", "stop_gate", "stop_failed_open_pytest_did_not_run",
            f"Gate 1 skipped: pytest did not run ({cls}: {os_error_text(e)}). To investigate: "
            + (f"{_py} -m pytest tests/ -q"
               if (_py := _hook_utils.python_command_hint())
               else "run pytest with a Python "
                    f"{_hook_utils.floor_text()}+ interpreter (none on PATH)"),
            fault=cls,
        )
        return 0


# ── Relief records (Gates 2 and 3) ────────────────────────────────────────────

def _relief_record(root: Path, flag: str) -> tuple[dict | None, str]:
    """``(record, why)`` for ``STATE_DIR/<flag>``.

    ``record`` is ``None`` when the flag is absent and ``{}`` when the file
    exists but is not a record; ``why`` then says which way it is not
    (``empty``, ``not JSON``, ``not a JSON object``, ``unreadable``, ``not
    UTF-8 text``) so the gate can say so instead of describing an agent run
    that never happened. A touched file is a file, not evidence. The hygiene
    gates only ever READ here: subagent_stop is the sole writer (DEF-608).

    Decoded through ``decode_text_or_problem``, the one owner of the
    decode-then-check idiom and its sentence for every file an operator writes
    by hand: this is one (the deny messages, docs/TROUBLESHOOTING.md), and Windows
    PowerShell 5.1's ``>`` and ``Out-File`` write it as UTF-16LE with a
    byte-order mark. The strict UTF-8 read raised on that mark, and a
    ``UnicodeDecodeError`` is a ``ValueError`` the JSON handler below never
    saw, so the crash guard re-blocked with an internal error instead of this
    gate's named reason -- the documented escape hatch bricked the Stop
    (DEF-797, driven on the Windows host 2026-09-14). Bytes that are neither
    UTF-8 nor BOM-marked UTF-16/32, or a mark-less UTF-16 file, are named by
    the helper's sentence, with the encoding to re-save in.
    """
    path = root / STATE_DIR / flag
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, ""
    except OSError as exc:
        return {}, f"unreadable ({type(exc).__name__})"
    text, problem = decode_text_or_problem(raw)
    if problem:
        return {}, problem
    if not text.strip():
        return {}, "empty"
    try:
        payload = json.loads(text)
    except ValueError:
        return {}, "not JSON"
    if not isinstance(payload, dict):
        return {}, "not a JSON object"
    return payload, ""


def _hand_record_note(record: dict | None) -> str | None:
    """The note of an operator-recorded judgement, or ``None`` when the record
    is not one (a missing or non-string note reads as ``""``)."""
    if not record or record.get("agent") != _hook_utils.OPERATOR_RELIEF_AGENT:
        return None
    note = record.get("note")
    return note if isinstance(note, str) else ""


def _recorded_by_hand(record: dict | None) -> bool:
    """An operator-recorded judgement both gates honour: ``agent`` is the
    hand-record sentinel and ``note`` is at least the floor's worth of why. It
    is the deliberate escape the deny messages name; a punctuation mark is not
    a judgement, and its use is announced on stderr by the gate it relieves."""
    note = _hand_record_note(record)
    return (
        note is not None
        and len(note.strip()) >= _hook_utils.OPERATOR_RELIEF_NOTE_MIN_CHARS
    )


def _hand_record_defect(record: dict | None) -> str:
    """Why an operator record does NOT count -- ``""`` when it does, or when
    the record is not an operator record at all."""
    note = _hand_record_note(record)
    if note is None or _recorded_by_hand(record):
        return ""
    length = len(note.strip())
    if length == 0:
        return "the operator note is blank"
    return (
        f"the operator note is {length} characters, and a judgement is at "
        f"least {_hook_utils.OPERATOR_RELIEF_NOTE_MIN_CHARS}"
    )


def _announce_hand_relief(flag: str, record: dict | None) -> None:
    """The one bypass this hook offers leaves a stderr record, the way a
    maintenance-mode bypass does -- in the debug log, not the transcript,
    since this hook exits 0."""
    note = (_hand_record_note(record) or "").strip()
    # voice: debug-log by design, as the docstring says; the hand record itself sits in the state dir
    print(
        f"[stop_gate] {flag}: relieved by a hand-recorded judgement -- {note[:120]}",
        file=sys.stderr,
    )


# ── Gate 2: docs refresh ──────────────────────────────────────────────────────

def _docs_refresh_evidence(record: dict | None) -> list[str]:
    """Doc paths the docs-maintainer actually changed, per the relief record.

    DEF-495: the flag used to be a zero-byte file written on agent COMPLETION,
    so Gate 2 relieved on attendance rather than on work — a docs-maintainer that
    ran and wrote nothing (which is what happened while ``docs/`` was
    PreToolUse-denied) cleared the gate on retry with zero docs written. The
    record now carries the evidence and this reads it. A missing, empty or
    unparseable record yields ``[]`` — no evidence, so no relief.
    """
    if not record:
        return []
    changed = record.get("changed_docs")
    if not isinstance(changed, list):
        return []
    return [p for p in changed if isinstance(p, str) and p]


def _gate_docs_refresh(root: Path, write_count: int) -> int:
    """DENY if long session with no docs refresh — or with a refresh that
    changed nothing, which is the same thing wearing a flag."""
    if write_count < 10:
        return 0
    record, why = _relief_record(root, DOCS_REFRESHED)
    if _docs_refresh_evidence(record):
        return 0
    if _recorded_by_hand(record):
        _announce_hand_relief(DOCS_REFRESHED, record)
        return 0
    if record is None:
        return _audit_block(
            root, "stop_blocked_docs_refresh",
            _denial_reasons.GATE_DOCS_REFRESH_NEEDED
            + _hook_utils.relief_agents_line(root, DOCS_REFRESHED, hook="stop_gate"),
            gate=2, rule="GATE_DOCS_REFRESH_NEEDED", write_count=write_count,
        )
    defect = why or _hand_record_defect(record)
    if defect:
        # The file is not a record (or is an operator record without a
        # judgement). Say THAT: the no-changes message below describes an
        # agent run, and none happened.
        return _audit_block(
            root, "stop_blocked_docs_refresh",
            _denial_reasons.GATE_RELIEF_RECORD_INVALID.format(flag=DOCS_REFRESHED, why=defect),
            gate=2, rule="GATE_RELIEF_RECORD_INVALID", write_count=write_count,
        )
    # The agent ran and recorded no changed docs. Say so specifically — a
    # generic "dispatch the docs-maintainer" would send the operator round the
    # same loop that produced this state.
    return _audit_block(
        root, "stop_blocked_docs_refresh", _denial_reasons.GATE_DOCS_REFRESH_NO_CHANGES,
        gate=2, rule="GATE_DOCS_REFRESH_NO_CHANGES", write_count=write_count,
    )


# ── Gate 3: code review ───────────────────────────────────────────────────────

def _code_review_evidence(record: dict | None, root: Path | None = None) -> str:
    """The reviewer subagent that ran, per the relief record, or ``""``.

    DEF-608: this gate used to WRITE ``review_requested`` itself on its first
    block, so it relieved on having asked for a review -- once per session,
    with no review run. It now only reads: subagent_stop writes the record when
    a reviewer subagent finishes, and the record names that agent. Any agent
    the shared table maps to this flag counts, so a second reviewer added to
    the table relieves the gate without an edit here, and so does a reviewer
    the adopter declares in espalier.toml's ``code_review_agents`` (read when
    ``root`` is given).
    """
    if not record:
        return ""
    agent = record.get("agent")
    if not isinstance(agent, str):
        return ""
    table = (
        _hook_utils.relief_flags(root, hook="stop_gate") if root is not None
        else _hook_utils.RELIEF_FLAGS
    )
    return agent if table.get(agent) == CODE_REVIEWED else ""


def _gate_code_review(root: Path, write_count: int) -> int:
    """DENY if a long session's turn ends with no code review having RUN.
    Reads only -- see ``_code_review_evidence``; the hygiene gates never write
    their own relief. The block re-arms on every turn until a record exists
    (the continuation's own Stop passes by the protocol's loop guard in
    ``_run_main``, so it fires on the first Stop of each turn, not on every
    Stop)."""
    if write_count < 10:
        return 0
    record, why = _relief_record(root, CODE_REVIEWED)
    if _code_review_evidence(record, root):
        return 0
    if _recorded_by_hand(record):
        _announce_hand_relief(CODE_REVIEWED, record)
        return 0
    if record is not None:
        agent = record.get("agent")
        defect = why or _hand_record_defect(record) or (
            f"it names {agent!r}, which the relief table does not map to a "
            f"reviewer" if isinstance(agent, str) else "it names no agent"
        )
        return _audit_block(
            root, "stop_blocked_code_review",
            _denial_reasons.GATE_RELIEF_RECORD_INVALID.format(flag=CODE_REVIEWED, why=defect),
            gate=3, rule="GATE_RELIEF_RECORD_INVALID", write_count=write_count,
        )
    return _audit_block(
        root, "stop_blocked_code_review",
        _denial_reasons.GATE_CODE_REVIEW_BLOCK
        + _hook_utils.relief_agents_line(root, CODE_REVIEWED, hook="stop_gate"),
        gate=3, rule="GATE_CODE_REVIEW_BLOCK", write_count=write_count,
    )


# ── Gate 5: the handoff gate ─────────────────────────────────────────────────

#: The flag under STATE_DIR (``_hook_utils.HANDOFF_GATE_FLAG``): its text is the
#: HEAD this gate last judged. SessionStart seeds it with HEAD on a new session,
#: so the gate speaks about commits made in THIS session and a lane an earlier
#: session left unpushed is the banner's to name; a compaction keeps it. Every
#: judgment rewrites it (a block, or a pass with nothing owed at this HEAD), so a
#: new commit speaks again and the same HEAD does not
#: (tests/test_state_file_flag_parity.py lists the file).
HANDOFF_GATE_FLAG = _hook_utils.HANDOFF_GATE_FLAG
#: One deadline for every git question the gate asks (at most seven reads of
#: local refs and the index, no network), inside STOP_SAFETY_MARGIN.
HANDOFF_GATE_DEADLINE_S = 5.0
#: The hold under STATE_DIR (``_hook_utils.HANDOFF_GATE_HOLD``, DEF-4058): JSON
#: ``{"head", "branch", "checked", "seat", "prs"}``, written at the decision
#: point while this seat has ANOTHER pull request open -- one open pull request
#: per seat (memory/parallel-work-protocol.md item 4): the next job is built on
#: a new branch while the first is in CI and opened when it merges, so a block
#: here told a worker to open the second beside the first. The Stop then passes
#: without a block (one record per held HEAD, ``stop_held_handoff``), the hold's
#: HEAD is not remembered as judged, and gh is asked again only past
#: ``HANDOFF_GATE_HOLD_RECHECK_S``; once none is open the hold clears and the
#: block returns, which makes this gate the reminder that the first lane merged.
#: A torn hold, or another head's, is no hold. SessionStart clears it with the
#: flag on a new session (tests/test_state_file_flag_parity.py lists the file).
HANDOFF_GATE_HOLD = _hook_utils.HANDOFF_GATE_HOLD
#: One `gh pr list` read, on its own clock beside the git deadline (the
#: banner's cap for the same read; measured 0.5 to 1.3 s), the one network
#: read the gate makes: paid at the decision point of a new HEAD on an
#: unpushed lane of a NAMED seat, then at most once per re-check interval
#: while the hold stands; never on a judged HEAD, an unnamed checkout, a tree
#: without the mail channel, or a lane with an upstream of its own.
HANDOFF_GATE_GH_CAP_S = 5.0
#: Each git read the driver's attribution makes (the box's name; the local
#: mail refs: one `for-each-ref`, then one `show` per seat) is bounded by this.
HANDOFF_GATE_DRIVER_CAP_S = 5.0
#: While the hold names HEAD, gh is asked again no more often than this.
HANDOFF_GATE_HOLD_RECHECK_S = 300.0
#: The hold's clock (its ``checked`` and ``since`` stamps): one name, so a
#: test pins the interval by moving it, never by sleeping.
HOLD_CLOCK: Callable[[], float] = time.time
#: What the one-per-seat attribution reads of each row, where the driver
#: exports no field list of its own (``ship.OPEN_PR_FIELDS`` is the one home):
#: the lane, its number, and the `seat:` label where no claim names the lane.
_OPEN_PR_FIELDS = "number,headRefName,labels"
#: The fourth carve-out of GATE_HANDOFF_OWED, filled into its ``{fourth}``
#: (with ``{count}`` "Four") only where the read of this seat's other open
#: pull requests could not be made -- the ``{prs}`` sentence says so. A hold
#: the model takes on its own must rest on a read made in THIS turn, by
#: number, never on a pull request remembered from earlier in the session:
#: listed on every block, the carve-out invited the hold the gate itself
#: would not take (the failure-mode review of 2026-10-31). A fragment of the
#: one reason, so it lives beside the gate and not in the reasons module,
#: whose every text is a whole reason the bench recognises by its marker.
HANDOFF_FOURTH_CARVE_OUT = (
    "; or the read above could not be made and a read you make in this turn names "
    "one of this seat's pull requests open, by number -- say the number in your one "
    "line; a pull request remembered from earlier in the session is not that read"
)
#: The own-clear marker under STATE_DIR, as ``tools/cc/ship.py`` names it
#: (``OWN_CLEAR_MARKER`` there; tests/test_own_clear.py pins the two): the
#: handoff's last act arms it, with ``head`` the HEAD it ran at.
OWN_CLEAR_MARKER = "own_clear.json"


def _own_clear_armed_at(root: Path, head: str) -> bool:
    """Whether the own-clear marker is armed for ``head``: the handoff ran to
    its end at this HEAD and its push was held (DEF-4057), so the lane is the
    next window's to land and not owed again here. A marker that is missing,
    unreadable or another head's reads False, and the gate judges as before."""
    try:
        marker = json.loads((root / STATE_DIR / OWN_CLEAR_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fail-open: ok deliberate a missing or torn marker is not armed, and the gate still judges the lane
        return False
    return isinstance(marker, dict) and marker.get("state") == "armed" and marker.get("head") == head
#: The reason quotes the plan's title up to this many characters.
HANDOFF_GATE_TASK_CHARS = 80


class _GitFault(Exception):
    """git could not be asked: it did not start, or the deadline was spent."""


def _git_answer(root: Path, deadline: float, *args: str) -> str | None:
    """``git <args>`` at ``root``: stdout stripped on exit 0; ``None`` on any
    other exit, which is git answering in the negative (no upstream, a
    detached HEAD, not a repository); ``_GitFault`` when it could not be asked
    at all, the deadline spent included. Through the gate chokepoint, so the
    bound holds on Windows too."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _GitFault(f"deadline of {HANDOFF_GATE_DEADLINE_S:g}s spent")
    try:
        result = _hook_utils.spawn_checked(
            ["git", *args], root=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=remaining, cwd=str(root),
        )
    except subprocess.TimeoutExpired as exc:
        raise _GitFault(f"deadline of {HANDOFF_GATE_DEADLINE_S:g}s spent") from exc
    if isinstance(result, _hook_utils.SpawnFailure):
        raise _GitFault(result.error)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def _tracked_edits(root: Path, deadline: float) -> bool | None:
    """Whether a tracked file is modified, added or deleted in the working tree
    or the index (``git status --porcelain -uno``): work in flight, which a
    handoff must not be asked for. Untracked files are not counted -- a scratch
    note beside a finished lane is common. ``None`` when git answered in the
    negative (not a repository)."""
    out = _git_answer(root, deadline, "status", "--porcelain", "-uno")
    if out is None:
        return None
    return bool(out)


def _unpushed_commits(root: Path, deadline: float) -> tuple[int, str, str, bool] | None:
    """``(ahead, branch, upstream, own)``: the commits HEAD holds that its
    upstream does not, and whether that upstream is the branch's own (a lane
    already pushed) or the remote's default branch, which a lane never pushed
    is measured against as the ship driver's push will measure it:
    ``origin/HEAD``, else ``origin/main``, else ``origin/master``. ``None``
    when there is nothing to compare: a detached HEAD, no upstream and no
    remote default branch, no commits, not a git tree. Raises ``_GitFault``
    when git could not be asked."""
    branch = _git_answer(root, deadline, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        return None
    upstream = _git_answer(root, deadline, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    # A lane's OWN upstream is its own remote branch (`origin/<branch>`: a lane
    # already pushed, whose next push lands on its open pull request). A branch
    # created from `origin/main` tracks origin/main by git's default
    # autoSetupMerge: an upstream, but not its own, so the push would OPEN a
    # pull request (the failure-mode review of 2026-10-31 reproduced the hold
    # skipped on exactly the lane the protocol tells a seat to start).
    own = bool(upstream) and str(upstream).endswith("/" + branch)
    if not upstream:
        upstream = _git_answer(root, deadline, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    for name in ("origin/main", "origin/master"):
        if upstream:
            break
        if _git_answer(root, deadline, "rev-parse", "--verify", "-q", f"refs/remotes/{name}") is not None:
            upstream = name
    if not upstream:
        return None
    count = _git_answer(root, deadline, "rev-list", "--count", f"{upstream}..HEAD")
    if count is None or not count.isdigit():
        return None
    return int(count), branch, upstream, own


def _driver_stands_down(root: Path, why: str, fault: str) -> bool:
    """The handoff gate stands down over the ship driver, said once a session
    (``stop_failed_open_handoff_driver``); ``fault`` is a class name or a
    fixed word, never a path or a message."""
    _hook_utils.say_once(
        root, "handoff-gate-driver", "stop_gate", "stop_failed_open_handoff_driver",
        f"the handoff gate stands down: {why}", fault=fault,
    )
    return False


def _vetted_driver(root: Path) -> types.ModuleType | None:
    """The ship driver (``tools/cc/ship.py``) as a module, or None: a tree
    without it has no handoff push to owe, so nothing is said; a driver that
    cannot import (a sibling missing after a partial upgrade) or a module
    elsewhere answering to its name stands the gate down and says so once.
    The one import site, so the handoff_push read and the one-per-seat read
    vet the same module in whatever order they run."""
    try:
        import ship  # lazy: tools/cc is on sys.path above; only a Stop with nothing in flight pays for it
    except ModuleNotFoundError as exc:  # fail-open: ok deliberate -- the one silent arm is a tree without tools/cc/ship.py, which has no handoff push to owe; a missing sibling is said once
        if exc.name == "ship":
            return None
        return _no_driver(
            root, f"tools/cc/ship.py imports {exc.name}, which this tree lacks "
                  "(`espalier upgrade --execute .` refreshes the deployed drivers)",
            exc.name or "ModuleNotFoundError",
        )
    except Exception as exc:  # noqa: BLE001 -- a driver that cannot import is said once, never a crash-block of every Stop
        return _no_driver(
            root, f"tools/cc/ship.py could not be imported ({type(exc).__name__})", type(exc).__name__,
        )
    expected = Path(__file__).resolve().parents[1] / "ship.py"
    found = getattr(ship, "__file__", None)
    try:
        same = bool(found) and Path(str(found)).resolve() == expected
    except OSError:  # fail-open: ok deliberate -- a module path that cannot resolve reads as another module answering, said once below
        same = False
    if not same:
        return _no_driver(
            root, f"another module answers to `ship` ({found or 'no file'}), not {expected}", "ShadowedDriver",
        )
    return ship


def _no_driver(root: Path, why: str, fault: str) -> types.ModuleType | None:
    """``_driver_stands_down`` for the module-valued reader: said once, no module."""
    _driver_stands_down(root, why, fault)
    return None


def _handoff_push_on(root: Path) -> bool:
    """Whether this repository's /handoff pushes (``handoff_push = true`` in
    espalier.toml), read by the ship driver's own reader so the gate owes
    exactly what the push verb will do. No driver, or one that cannot be
    vetted (``_vetted_driver``), a driver that predates the reader, or a read
    that fails: the gate stands down, said once where it is a fault."""
    ship = _vetted_driver(root)
    if ship is None:
        return False
    setting = getattr(ship, "handoff_push_setting", None)
    if setting is None:
        return _driver_stands_down(
            root, "tools/cc/ship.py predates handoff_push_setting "
                  "(`espalier upgrade --execute .` refreshes the deployed driver)",
            "NoHandoffPushSetting",
        )
    try:
        on, _how = setting(root)
    except Exception as exc:  # noqa: BLE001 -- the reader is the driver's; a fault there is said once, never a crash-block of every Stop
        return _driver_stands_down(
            root, f"the driver's handoff_push read failed ({type(exc).__name__})", type(exc).__name__,
        )
    return bool(on)


def _flag_text(flag: Path) -> str:
    """The HEAD the flag holds (a SHA: a structured answer, read strictly), or
    "" when there is none or it cannot be read."""
    try:
        return flag.read_text(encoding="utf-8").strip() if flag.is_file() else ""
    # fail-open: ok deliberate -- an unreadable or corrupt flag reads as not yet judged; the cost is one more judgment, never a lockout
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-829)
        return ""


def _remember_head(flag: Path, head: str) -> None:
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        _hook_utils.atomic_write_text(flag, head)
    except OSError:  # fail-open: ok deliberate -- a flag that cannot be written costs one more judgment next Stop, never a lockout (the loop signal lets each continuation through)
        pass


def _hold_read(root: Path) -> dict | None:
    """The hold's record, or None: no hold, or one that cannot be read, which
    is no hold (the lane is judged again, at the cost of one gh read)."""
    try:
        data = json.loads((root / STATE_DIR / HANDOFF_GATE_HOLD).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fail-open: ok deliberate -- a missing or torn hold is no hold; the gate judges the lane again, which costs one gh read
        return None
    return data if isinstance(data, dict) else None


def _hold_write(root: Path, head: str, branch: str, seat: str, prs: list[str], ahead: int,
                since: object = None) -> None:
    """The hold for ``head``: this seat's other open pull requests as the
    driver names them, the lane's commit count, ``since`` (the first hold on
    this HEAD, carried across re-stamps so a reader can say how long) and
    ``checked`` (now). Through the roster writer, so a symlinked path is
    replaced, never followed."""
    path = root / STATE_DIR / HANDOFF_GATE_HOLD
    now = HOLD_CLOCK()
    record = {
        "head": head, "branch": branch, "checked": now,
        "since": since if isinstance(since, (int, float)) and not isinstance(since, bool) else now,
        "seat": seat, "prs": list(prs), "ahead": ahead,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _hook_utils.atomic_write_text(path, json.dumps(record))
    except OSError:  # fail-open: ok deliberate -- a hold that cannot be written costs one gh read per Stop while the other pull request is open, never a block over the rule
        pass


def _hold_clear(root: Path) -> None:
    try:
        (root / STATE_DIR / HANDOFF_GATE_HOLD).unlink(missing_ok=True)
    except OSError:  # fail-open: ok deliberate -- a hold that cannot be removed is re-read at the next Stop and re-checked past its interval
        pass


def _gh_open_prs(root: Path, fields: str) -> list[dict] | str:
    """Every open pull request as `gh pr list` lists it (every author: the
    seats push as one account, and the driver's attribution tells them
    apart), or the fault as a word: ``Unresolved`` (no gh), ``TimeoutExpired``,
    ``rc=<n>`` (gh ran and refused: not signed in, no GitHub remote),
    ``NotJSON``. Through the gate's chokepoint, under its own cap."""
    try:
        result = _hook_utils.spawn_checked(
            ["gh", "pr", "list", "--state", "open", "--limit", "50", "--json", fields],
            root=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=HANDOFF_GATE_GH_CAP_S, cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return "TimeoutExpired"
    if isinstance(result, _hook_utils.SpawnFailure):
        return result.error
    if result.returncode != 0:
        return f"rc={result.returncode}"
    try:
        rows = json.loads(result.stdout or "")  # json-dict-safe: ok -- a LIST of rows; each row is isinstance-checked below
    except ValueError:
        return "NotJSON"
    if not isinstance(rows, list):
        return "NotJSON"
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("number"), int)]


@dataclass(frozen=True)
class _SeatPrs:
    """What the one-per-seat read found: ``fault`` (a word) when the seat's
    name, the listing or the attribution could not be made; ``read`` (gh was
    asked: False for an unnamed box or a tree without the mail channel, where
    nothing is read); ``others`` (another pull request is open at all);
    ``seat``; and ``mine`` (this seat's, as the driver names them: ``#n (lane)``)."""

    fault: str = ""
    read: bool = False
    others: bool = False
    seat: str = ""
    mine: tuple[str, ...] = ()


def _seat_other_open_prs(root: Path, branch: str) -> _SeatPrs:
    """This seat's open pull requests other than ``branch``'s. The seat's name
    first, through the driver (``ship.seat_name``: the mail channel's
    ``espalier.machine``), so an unnamed box or a tree without the channel
    reads nothing and pays no spawn; then one gh listing, in the driver's own
    field set; then the driver's attribution (``ship.seat_open_prs``: the
    seat whose latest claim or release names each lane, else its `seat:`
    label), each git read of it bounded. The driver speaks on ITS stdout
    (`note:` lines, its fail-open voice); here stdout is the decision
    channel, so its words are captured and read as the read not made."""
    ship = _vetted_driver(root)
    if ship is None:
        return _SeatPrs(fault="NoDriver")
    name_reader = getattr(ship, "seat_name", None)
    reader = getattr(ship, "seat_open_prs", None)
    if name_reader is None or reader is None:
        return _SeatPrs(fault="DriverPredatesSeatName")
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink):
            seat, problem = name_reader(root, timeout=HANDOFF_GATE_DRIVER_CAP_S)
    except Exception as exc:  # noqa: BLE001 -- the driver's name read is fail-open with voice on its own stdout; a raise is a word in the block's text
        return _SeatPrs(fault=type(exc).__name__)
    seat = str(seat or "")
    if problem:
        return _SeatPrs(fault="NameUnread")
    if not seat:
        return _SeatPrs()
    rows = _gh_open_prs(root, str(getattr(ship, "OPEN_PR_FIELDS", "") or _OPEN_PR_FIELDS))
    if isinstance(rows, str):
        return _SeatPrs(fault=rows, seat=seat)
    if not any(str(row.get("headRefName") or "") != branch for row in rows):
        return _SeatPrs(read=True, seat=seat)
    try:
        with contextlib.redirect_stdout(sink):
            found_seat, mine = reader(root, branch, rows, timeout=HANDOFF_GATE_DRIVER_CAP_S)
    except Exception as exc:  # noqa: BLE001 -- the driver's reader is fail-open with voice on its own stdout, kept off this hook's channel; a raise is a word in the block's text
        return _SeatPrs(fault=type(exc).__name__, read=True, seat=seat)
    if sink.getvalue().strip():
        return _SeatPrs(fault="DriverNote", read=True, seat=seat)
    return _SeatPrs(read=True, others=True, seat=str(found_seat or seat),
                    mine=tuple(str(m) for m in (mine or ())))


def _recheck_words() -> str:
    return f"{int(HANDOFF_GATE_HOLD_RECHECK_S // 60)} min"


def _hold_recheck(root: Path, hold: dict) -> tuple[bool, _SeatPrs | None]:
    """``(stands, found)`` for a hold naming HEAD at this Stop. Inside the
    re-check interval it stands, unread; past it this seat's other open pull
    requests are read again: one still open re-stamps the hold, none clears
    it and the lane is judged at this same Stop, with ``found`` (that one
    read) handed on so gh is not asked twice. A read that cannot be made
    keeps the hold for one more interval and says so once per fault
    (``stop_failed_open_handoff_prs``)."""
    checked = hold.get("checked")
    if isinstance(checked, (int, float)) and 0 <= HOLD_CLOCK() - checked < HANDOFF_GATE_HOLD_RECHECK_S:
        return True, None
    head, branch, seat = (str(hold.get(key) or "") for key in ("head", "branch", "seat"))
    ahead = hold.get("ahead")
    ahead = ahead if isinstance(ahead, int) and not isinstance(ahead, bool) else 0
    since = hold.get("since")
    found = _seat_other_open_prs(root, branch)
    if found.fault:
        _hook_utils.say_once(
            root, f"handoff-gate-hold-reread-{found.fault}", "stop_gate", "stop_failed_open_handoff_prs",
            f"the handoff gate's hold on {branch} could not be re-checked ({found.fault}); "
            f"it stands for another {_recheck_words()}",
            fault=found.fault,
        )
        prs = hold.get("prs")
        _hold_write(root, head, branch, seat, [str(p) for p in prs] if isinstance(prs, list) else [], ahead,
                    since=since)
        return True, None
    if found.mine:
        _hold_write(root, head, branch, found.seat, list(found.mine), ahead, since=since)
        return True, None
    _hold_clear(root)
    return False, found


def _say_held(root: Path, head: str, branch: str, ahead: int, found: _SeatPrs) -> None:
    """The hold's one record per held HEAD -- ``stop_held_handoff``, advisory
    and in neither block tier, since nothing was blocked; its details are the
    counts of commits and of pull requests, never the branch -- and its
    stderr line, guarded by a once-flag of the ``once_`` family under
    STATE_DIR (session_start sweeps the family), written AFTER the record so
    a failed flag write yields a duplicate record at the next Stop, never a
    silent hold. Not ``say_once``: that voice is the fail-open family's, and
    a hold is the rule working, not a fault."""
    flag = root / STATE_DIR / (_hook_utils.ONCE_FLAG_PREFIX + f"handoff-gate-hold-{head[:12]}")
    try:
        if flag.exists():
            return
    except OSError:  # fail-open: ok deliberate -- an unreadable state dir: the record is written once more, never a silent hold
        pass
    try:
        _integrity.append_audit(
            root,
            {"event_type": "stop_held_handoff",
             "details": {"hook": "stop_gate", "ahead": ahead, "open": len(found.mine)}},
            quiet=True,
        )
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; the hold path stays silent
        pass
    commits = f"{ahead} commit" + ("" if ahead == 1 else "s")
    print(
        f"[stop_gate] the handoff gate holds {branch} ({commits} unpushed): this seat ({found.seat}) "
        f"has {', '.join(found.mine)} open, and one open pull request per seat; it asks again once "
        f"none is (gh re-read every {_recheck_words()} while held)",
        file=sys.stderr,
    )
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        _hook_utils.atomic_write_text(flag, "")
    except OSError:  # fail-open: ok deliberate -- a read-only state dir: the record repeats at the next Stop, never a silent hold
        pass


def _hold_or_clause(
    root: Path, head: str, branch: str, ahead: int, found: _SeatPrs | None = None,
) -> tuple[str, bool] | None:
    """At the decision point of a lane whose push would OPEN a pull request:
    None when the Stop passes because this seat has another one open (the
    record said once per held HEAD, then the hold written), else the block's
    sentence on what was read and whether the read could not be made (the
    fourth carve-out is listed only then). ``found`` is a read already made
    for this branch at this Stop (the hold's re-check), else one is made here."""
    if found is None:
        found = _seat_other_open_prs(root, branch)
    if found.fault:
        return (f"Whether this seat has another open pull request could not be read ({found.fault}): "
                "hold only on a read you make in this turn that names one of this seat's pull requests "
                "open, by number (the fourth carve-out below); otherwise run /handoff.", True)
    if not found.read:
        return ("This checkout names no seat (git config espalier.machine), so no other open "
                "pull request was looked for.", False)
    if not found.others:
        return "No other pull request is open.", False
    if found.mine:
        _say_held(root, head, branch, ahead, found)
        _hold_write(root, head, branch, found.seat, list(found.mine), ahead)
        return None
    return f"This seat ({found.seat}) has no other open pull request.", False


def _gate_handoff(root: Path) -> int:
    """Gate 5: BLOCK once per commit when nothing is in flight -- no plan in
    progress, no tracked edit -- and the branch holds commits its upstream
    does not, made in this session, on a repository whose espalier.toml sets
    ``handoff_push = true``: the handoff is owed, and it is cheapest in the
    turn that finished the work, while the context is warm. The measured
    case: a lane finished at 05:13 and left for the operator's /handoff sat
    unpushed, unrowed and claimed for eleven hours, under MAINTENANCE_MODE
    (2026-10-24), so this gate runs under the flag too (continuity, not
    friction), and alone on the continuation Stop. "This session" is the flag:
    SessionStart seeds it with HEAD and every judgment rewrites it, so a HEAD
    already judged, or already there when the session began, is passed over; a
    new commit speaks once; a handoff whose push failed (its row moved HEAD)
    speaks again. A plan in progress or an edit in flight passes and writes
    nothing, so the judgment waits for the commit; nothing unpushed, nothing
    to compare against, or a repository whose handoff does not push passes
    and remembers the HEAD. A git that cannot be asked allows and speaks once
    (``stop_failed_open_handoff_git``).

    One open pull request per seat (DEF-4058): where the push would OPEN a
    pull request (the branch has no upstream of its own) and this seat has
    another one open, the lane is held instead -- the Stop passes, one record
    per held HEAD, the hold file names HEAD and is re-checked past its
    interval -- and the block returns once none is open; the block's text
    says what was read, and names the wait where the read could not be made."""
    if _hook_utils.has_active_plan(root):
        return 0
    deadline = time.monotonic() + HANDOFF_GATE_DEADLINE_S
    flag = root / STATE_DIR / HANDOFF_GATE_FLAG
    lifted: tuple[str, _SeatPrs] | None = None   # the lifted hold's branch and its one read
    try:
        head = _git_answer(root, deadline, "rev-parse", "HEAD")
        if not head or _flag_text(flag) == head:
            return 0
        if _tracked_edits(root, deadline) is not False:
            return 0
        hold = _hold_read(root)
        if hold is not None and hold.get("head") == head:
            # A hold is the lane's, not the commit's: another branch on this
            # same commit is judged afresh.
            if hold.get("branch") != _git_answer(root, deadline, "rev-parse", "--abbrev-ref", "HEAD"):
                _hold_clear(root)
            elif not _handoff_push_on(root):
                _hold_clear(root)
                _remember_head(flag, head)
                return 0
            else:
                stands, found_now = _hold_recheck(root, hold)
                if stands:
                    return 0
                # None of this seat's other pull requests is open now: the hold
                # is lifted, and the lane is judged below at this same Stop.
                if found_now is not None:
                    lifted = (str(hold.get("branch") or ""), found_now)
        if not _handoff_push_on(root):
            _remember_head(flag, head)
            return 0
        found = _unpushed_commits(root, deadline)
    except _GitFault as fault:
        _hook_utils.say_once(
            root, "handoff-gate-git", "stop_gate", "stop_failed_open_handoff_git",
            f"the handoff gate could not ask git ({fault}) and let the Stop through; "
            "the lane's push state is unread this session",
            fault=str(fault),
        )
        return 0
    if found is None:
        return 0
    ahead, branch, upstream, own = found
    if ahead <= 0 or _own_clear_armed_at(root, head):
        # Nothing owed at this HEAD; or the handoff ran to its end for it and
        # its push was held (the base red, or a step after a landed push
        # refused; DEF-4057): the ship driver armed the own-clear with the
        # lane to land first in the next window's brief, and the mod clears
        # this window at the turn's end -- the end a block here would
        # withhold, asking for a handoff that could only write a second row
        # and re-arm (both reviews, 2026-10-30).
        _remember_head(flag, head)
        return 0
    failed_read = False
    if own:
        prs = f"The push lands on {branch}'s own pull request, so no second one opens."
    else:
        reuse = lifted[1] if lifted is not None and lifted[0] == branch else None
        verdict = _hold_or_clause(root, head, branch, ahead, found=reuse)
        if verdict is None:
            return 0   # held: not remembered as judged, so the hold is re-read at the next Stop
        prs, failed_read = verdict
    _remember_head(flag, head)
    complete, task = _hook_utils.plan_completion(root)
    if complete:
        title = task if len(task) <= HANDOFF_GATE_TASK_CHARS else task[:HANDOFF_GATE_TASK_CHARS - 3] + "..."
        plan = f"the plan `{title}` is complete"
    else:
        plan = "no plan is in progress"
    commits = f"{ahead} commit" + ("" if ahead == 1 else "s")
    push = ("onto its open pull request, re-binding the marker" if own
            else "opening the pull request with auto-merge armed")
    return _audit_block(
        root, "stop_blocked_handoff",
        _denial_reasons.GATE_HANDOFF_OWED.format(
            plan=plan, target=branch, ahead=commits, upstream=upstream, push=push, prs=prs,
            count="Four" if failed_read else "Three",
            fourth=HANDOFF_FOURTH_CARVE_OUT if failed_read else ""),
        gate=5, rule="GATE_HANDOFF_OWED", ahead=ahead,
    )


# ── Gate 4: auto-finalize blueprint ────────────────────────────────────────────

def _gate_finalize_blueprint(root: Path) -> None:
    """Run cognitive_blueprint.py finalize. Always passes — never blocks."""
    blueprint_script = root / "tools" / "cc" / "cognitive_blueprint.py"
    if not blueprint_script.exists():
        return
    # env= pins CLAUDE_PROJECT_DIR to root so Gate 4 finalizes the session
    # in the right repo. cognitive_blueprint._repo_root() prefers the env
    # var over cwd; inherited values from the parent shell would silently
    # finalize in a different repo.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    try:
        result = _hook_utils.spawn_checked(
            [sys.executable, str(blueprint_script), "finalize"],
            root=root,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=10,
            cwd=str(root),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):  # fail-open: ok deliberate -- the finalize is best-effort; a timeout costs one node's close, never the Stop
        return
    if isinstance(result, _hook_utils.SpawnFailure):
        _hook_utils.say_once(
            root, "finalize-spawn", "stop_gate", "stop_failed_open_finalize_spawn",
            f"blueprint finalize could not start ({result.error}); this session's node is not closed",
            fault=result.error,
        )


def main() -> int:
    """Public entry-point. Fail-CLOSED umbrella: stop_gate is a BLOCKING Stop
    hook, so an uncaught crash in ``_run_main`` must RE-BLOCK — the protocol
    treats exit 1 as a non-blocking script error, which would let the session
    Stop with the gates unrun. Sister to plan_guard.main / write_guard.main,
    adapted to stop_gate's block() sentinel.

    block() returns 1 (main's historical "translate to exit 0" sentinel) and
    the funnel forwards it, so we DISCARD it and return 0 explicitly --
    ``return _audit_block(...)`` would propagate 1 -> sys.exit(1) ->
    channel-XOR violation. KeyboardInterrupt / SystemExit pass through (an
    operator Ctrl-C or an inner sys.exit must not be rewritten into a block).

    The crash block goes through the audited funnel (DEF-803): it is the one
    block that strands an operator, and it was the one block that wrote no
    record -- three Stop blocks on the Windows host 2026-09-14, two in the
    log. The record carries the exception's class, never its message (a
    message can quote a path or a file's contents).
    """
    try:
        return _run_main()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — fail-closed crash guard
        # The root is resolved here on its own, best-effort: the crash may
        # have been in resolving it, and Gate 4 and the record both want
        # one. ``resolve_project_root`` reads an env var and resolves a path,
        # so its fallback is the cwd it would have used; ``Path(".")`` makes
        # no syscall here, and a cwd that cannot resolve fails inside the
        # funnel, which swallows it.
        try:
            root = _resolve_project_root()
        except BaseException:  # noqa: BLE001 — best-effort; never mask the block
            root = Path(".")
        # Best-effort Gate 4 (blueprint finalize — "always passes, preserves
        # continuity") so it isn't skipped exactly when something crashed.
        try:
            _gate_finalize_blueprint(root)
        except BaseException:  # noqa: BLE001, S110 — best-effort; never mask the block
            pass
        error_type = type(exc).__name__
        print(
            f"[ERROR] stop_gate crashed: {error_type}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        _audit_block(
            root, "stop_blocked_internal_error",
            _denial_reasons.STOP_GATE_INTERNAL_ERROR.format(
                error=f"{error_type}: {os_error_text(exc)}",
            ),
            rule="STOP_GATE_INTERNAL_ERROR", error=error_type,
        )
        return 0


def _run_main() -> int:
    data = _hook_utils.read_stdin_safely()
    root = _resolve_project_root()

    # Loop guard: Claude Code re-fires Stop with stop_hook_active=True
    # after a prior block. A persistently-failing gate (docs-refresh /
    # code-review on a long session) would otherwise re-block forever. Honor
    # the protocol's loop signal: ALLOW the stop past Gates 1 to 4. Gate 5
    # alone still runs here: its own flag (the HEAD it judged) keeps it to
    # once per commit, so it cannot hold a session either, and a lane whose
    # first Stop was held by the docs or review gate is still told in the
    # same turn (the failure-mode review of 2026-10-24 drove the case).
    # read_stdin_safely() always returns a dict, so .get is safe.
    if data.get("stop_hook_active"):
        _gate_handoff(root)
        return 0

    _hook_utils.say_bad_stdin(root, "stop_gate", "stop_failed_open_bad_stdin", data)
    write_count = _read_write_count(root)
    mode = _stop_gate_mode(root)

    # Gate 1: pytest — opt-in via ESPALIER_STOP_GATE=full. Always runs even
    # under MAINTENANCE_MODE: tests are signal, not friction.
    if mode == STOP_GATE_FULL:
        if _gate_pytest(root):
            return 0

    # Opt-in advisory session-signal reads. Stderr-only,
    # NEVER block. Placed BEFORE Gates 2/3 deliberately: those gates can
    # early-return (block) on a long session (write_count>=10, flag absent),
    # which would otherwise SUPPRESS the advisory exactly when the session is
    # longest — the case the trajectory signal most wants to surface. light/
    # full behavior is unchanged (advisories only fire under scan-clean mode).
    if mode == STOP_GATE_SCAN_CLEAN:
        _gate_scan_clean(root)
        _advise_session_signals(root)

    maintenance = _maintenance_mode.is_active(
        "stop_gate", action="docs/review gates bypassed"
    )

    # Gates 2 and 3 are session-hygiene friction. MAINTENANCE_MODE skips them.
    if not maintenance:
        # Gate 2: docs refresh
        if _gate_docs_refresh(root, write_count):
            return 0

        # Gate 3: code review
        if _gate_code_review(root, write_count):
            return 0
    else:
        _record_maintenance_bypass(root, write_count)

    # Gate 5: the handoff gate. Runs under MAINTENANCE_MODE too: a finished
    # lane left unpushed is lost continuity, not friction, and the measured
    # case ran under the flag. Its flag, not the loop guard, keeps it to once
    # per commit.
    if _gate_handoff(root):
        return 0

    # Gate 4: auto-finalize blueprint (silent, always passes — preserves
    # session continuity even under MAINTENANCE_MODE).
    _gate_finalize_blueprint(root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
