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
Gate 4: Auto-finalize         — Run cognitive_blueprint.py finalize (silent, always passes).

(There is no "session state saved" gate: it would be unreachable-by-design
because cc/blueprints/ is gitignored, so Gate 4's auto-finalize output never
appears in `git status` to satisfy such a check. That coverage falls back to
/handoff, git status, IDE gutters, and Gate 4 itself.)

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

import json
import os
import shlex
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Import timing constants from the co-located copy (_hook_contract.py).
# tools/cc/ cannot import from espalier/ (isolation rule), so _hook_contract.py
# is a standalone copy of espalier/hook_contract.py kept in sync by tests.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
from _hook_contract import STOP_INNER_BUDGET  # noqa: E402
import _denial_reasons  # noqa: E402
import _maintenance_mode  # noqa: E402
import _hook_utils  # noqa: E402
import _integrity  # noqa: E402
from _json_safe import os_error_text  # noqa: E402
from _json_safe import decode_text_or_problem, load_json_dict_safe  # noqa: E402

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


@dataclass(frozen=True)
class ResolvedTests:
    """Tri-state result from `_resolve_core_tests`.

    status:
      - ``"ok"``: ``paths`` is non-empty; Gate 1 runs them.
      - ``"dormant_non_pytest"``: fingerprint has non-pytest commands;
        Gate 1 cannot drive them. Visible dormancy via stderr, not
        green-skip (BC-041 sister-class prevention).
      - ``"dormant_no_paths"``: fingerprint pytest commands have no
        positional args, and harness defaults aren't present in this
        repo. Visible dormancy.
      - ``"ok_env_override"``: ``ESPALIER_STOP_GATE_TEST_CMD`` set;
        ``paths`` is empty but Gate 1 spawns ``env_cmd`` directly.
    env_cmd: the env-override command string (only non-empty when
        status is ``"ok_env_override"``). Single source of truth —
        ``_gate_pytest`` reads this rather than re-reading the env.
    """
    paths: list[str]
    status: str
    note: str
    env_cmd: str = ""


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
    ``make test``) are skipped with a one-line stderr advisory; Gate 1
    is semantically a pytest gate.

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
            sys.stderr.write(
                f"(stop_gate) skipping non-pytest test_command: {cmd_str}\n"
            )
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
    except OSError:
        return []
    cmds = data.get("test_commands")
    return cmds if isinstance(cmds, list) else []


def _resolve_core_tests(repo_root: Path) -> ResolvedTests:
    """Return Gate 1 runnable pytest positional args with tri-state
    dormancy detection.

    ``reports/repo_fingerprint.json::test_commands`` is the canonical
    SoT, written by ``espalier.analyze.detect_tests``. **The fingerprint
    stores SHELL COMMAND STRINGS** (e.g., ``"pytest -q"``,
    ``"npm test"``, ``"go test ./..."``), **NOT file paths** — they must
    not be passed verbatim to pytest as positional args.

    The ``ResolvedTests`` tri-state makes dormancy visible: non-pytest
    fingerprints fall back to harness defaults that don't exist in
    adopter repos, where pytest would return ``collected 0 items`` and
    Gate 1 report a misleading green. Dormancy instead surfaces as a
    stderr note + SessionStart banner warn.

    Honors ``ESPALIER_STOP_GATE_TEST_CMD`` env override at function
    entry — when set, returns ``ResolvedTests(status="ok_env_override",
    env_cmd=<cmd>)`` and Gate 1 spawns ``env_cmd`` via
    ``_run_env_override_gate``.

    Stdlib-only — no espalier imports (tools/cc/ isolation rule).
    """
    env_override = os.environ.get(
        "ESPALIER_STOP_GATE_TEST_CMD", ""
    ).strip()
    if env_override:
        return ResolvedTests(
            paths=[],
            status="ok_env_override",
            note=f"Gate 1 will run env-override: {env_override!r}",
            env_cmd=env_override,
        )

    raw_cmds = _read_fingerprint_test_commands(repo_root)

    positional = _parse_pytest_positional_args(raw_cmds)
    if positional:
        return ResolvedTests(
            paths=positional, status="ok", note=""
        )

    has_pytest_shaped = any(_is_pytest_shaped(c) for c in raw_cmds)
    if raw_cmds and not has_pytest_shaped:
        return ResolvedTests(
            paths=[],
            status="dormant_non_pytest",
            note=(
                f"Gate 1 dormant: fingerprint test_commands "
                f"{raw_cmds!r} are non-pytest. Set "
                "ESPALIER_STOP_GATE_TEST_CMD=<command> to enable a "
                "custom Gate 1, or change test_commands in the "
                "fingerprint."
            ),
        )

    defaults = [str(p) for p in _HARNESS_DEFAULT_TESTS]
    defaults_present = [
        p for p in defaults if (repo_root / p).exists()
    ]
    if not defaults_present:
        return ResolvedTests(
            paths=[],
            status="dormant_no_paths",
            note=(
                "Gate 1 dormant: no positional args from fingerprint; "
                "harness defaults not present in this repo. Add a "
                "pytest invocation with positional args or set "
                "ESPALIER_STOP_GATE_TEST_CMD."
            ),
        )
    return ResolvedTests(
        paths=defaults_present, status="ok", note=""
    )


def _run_env_override_gate(root: Path, cmd: str) -> int:
    """Spawn the ``ESPALIER_STOP_GATE_TEST_CMD`` override command via
    subprocess. ``shell=False`` — arguments split via
    ``shlex.split`` so quoted strings survive. Returns 0 on green;
    calls ``_audit_block(...)`` on non-zero exit or timeout (matches Gate 1
    contract; see ``_gate_pytest``); ``root`` is where the record is filed.

    ``posix=False`` on Windows is required, not cosmetic. In POSIX mode
    ``shlex.split`` treats ``\\`` as an escape character, so a native path —
    ``C:\\Python\\python.exe`` — is silently rewritten to ``C:Pythonpython.exe``
    and the spawn fails on a path the operator never typed. Measured on the
    Windows CI runner: the override never ran, the gate emitted no decision,
    and the caller got empty stdout where JSON was contracted.
    ``posix=False`` keeps quotes in the tokens, so strip them afterwards to
    preserve the "quoted strings survive" half of the contract."""
    if os.name == "nt":
        parts = [
            tok[1:-1] if len(tok) > 1 and tok[0] == tok[-1] and tok[0] in "\"'" else tok
            for tok in shlex.split(cmd, posix=False)
        ]
    else:
        parts = shlex.split(cmd)
    if not parts:
        sys.stderr.write(
            "(stop_gate) ESPALIER_STOP_GATE_TEST_CMD empty after shlex\n"
        )
        return 0
    try:
        # subprocess-contract: ok operator-supplied-env-override-via-ESPALIER_STOP_GATE_TEST_CMD
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=STOP_INNER_BUDGET,
        )
    except subprocess.TimeoutExpired:
        return _audit_block(
            root, "stop_blocked_pytest",
            _denial_reasons.GATE_ENV_OVERRIDE_TIMEOUT.format(cmd=cmd),
            gate=1, rule="GATE_ENV_OVERRIDE_TIMEOUT",
        )
    except OSError as e:
        sys.stderr.write(
            f"(stop_gate) Gate 1 env-override failed to spawn: "
            f"{type(e).__name__}: {os_error_text(e)}\n"
        )
        return 0
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip()
        return _audit_block(
            root, "stop_blocked_pytest",
            _denial_reasons.GATE_ENV_OVERRIDE_FAILED.format(
                cmd=cmd,
                returncode=result.returncode,
                tail=tail[-800:],
            ),
            gate=1, rule="GATE_ENV_OVERRIDE_FAILED", returncode=result.returncode,
        )
    return 0

STOP_GATE_MODE_ENV = "ESPALIER_STOP_GATE"
STOP_GATE_LIGHT = "light"
STOP_GATE_FULL = "full"
STOP_GATE_SCAN_CLEAN = "scan-clean"  # opt-in advisory session signals


def _stop_gate_mode() -> str:
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
    _hook_utils.warn(f"unknown {STOP_GATE_MODE_ENV}={raw!r}; using light")
    return STOP_GATE_LIGHT


_resolve_project_root = _hook_utils.resolve_project_root


def block(reason: str) -> int:
    """Print Stop block JSON and return a truthy sentinel for gate control flow.

    Stop event schema differs from PreToolUse: top-level `decision` and
    `reason`, not nested under hookSpecificOutput. Per protocol: JSON only
    processed on exit 0. See docs/SHARP_EDGES.md "Hook Exit Codes — Channel XOR".

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
    except (ValueError, OSError):
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
    except (ValueError, OSError):
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
        except (ValueError, OSError):  # JSONDecodeError ⊂ ValueError
            history = []

    # Trajectory-length anomaly vs the rolling median of PRIOR sessions.
    if len(history) >= MIN_SESSIONS_FOR_TRAJECTORY:
        median = statistics.median(history)
        if median > 0 and count > TRAJECTORY_MULTIPLIER * median:
            sys.stderr.write(
                f"(stop_gate) [157-G advisory] session trajectory anomaly: "
                f"{count} tool calls vs rolling median {median:.0f} "
                f"(>{TRAJECTORY_MULTIPLIER:g}x). Advisory only -- not a gate.\n"
            )

    # Recursive-call burst (identical-consecutive tool streak).
    streak = _read_last_tool_streak(root)
    if streak >= RECURSIVE_REPEAT_THRESHOLD:
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
    except OSError:
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
    except (OSError, ValueError):
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
        sys.stderr.write(
            f"(stop_gate) [157-E advisory] scan findings rose: {prior} -> "
            f"{latest} across the two most recent scan runs. Advisory only.\n"
        )


# ── Gate 1: pytest ─────────────────────────────────────────────────────────────────

def _gate_pytest(root: Path) -> int:
    """Run core test suite. DENY if any tests fail. Opt-in via STOP_GATE_FULL."""
    # Resolve via fingerprint so host repos run their own tests,
    # not the harness's hard-coded list. Falls back to harness defaults
    # when fingerprint is absent. Tri-state dormancy: non-pytest
    # fingerprints or absent defaults yield a visible stderr note
    # instead of silent green.
    resolved = _resolve_core_tests(root)
    if resolved.status in ("dormant_non_pytest", "dormant_no_paths"):
        sys.stderr.write(f"(stop_gate) {resolved.note}\n")
        return 0
    if resolved.status == "ok_env_override":
        sys.stderr.write(f"(stop_gate) {resolved.note}\n")
        return _run_env_override_gate(root, resolved.env_cmd)
    test_args = [t for t in resolved.paths if (root / t).exists()]
    if not test_args:
        return 0  # No test files found — skip gate

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"] + test_args + ["-q", "--tb=short"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=STOP_INNER_BUDGET,
            cwd=str(root),
        )
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
        # Don't block on test infrastructure failure. Surface the error
        # type so the operator can tell a timeout (raise STOP_INNER_BUDGET)
        # from a missing interpreter (fix PATH) at a glance.
        cls = type(e).__name__
        print(
            f"[WARN] stop_gate: pytest did not run ({cls}: {os_error_text(e)}). "
            f"Gate 1 skipped. To investigate: "
            + (f"{_py} -m pytest tests/ -q"
               if (_py := _hook_utils.python_command_hint())
               else "run pytest with a Python "
                    f"{_hook_utils.floor_text()}+ interpreter (none on PATH)"),
            file=sys.stderr,
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
    """The one bypass this hook offers is observable in the transcript, the
    way a maintenance-mode bypass is."""
    note = (_hand_record_note(record) or "").strip()
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
            root, "stop_blocked_docs_refresh", _denial_reasons.GATE_DOCS_REFRESH_NEEDED,
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

def _code_review_evidence(record: dict | None) -> str:
    """The reviewer subagent that ran, per the relief record, or ``""``.

    DEF-608: this gate used to WRITE ``review_requested`` itself on its first
    block, so it relieved on having asked for a review -- once per session,
    with no review run. It now only reads: subagent_stop writes the record when
    a reviewer subagent finishes, and the record names that agent. Any agent
    the shared table maps to this flag counts, so a second reviewer added to
    the table relieves the gate without an edit here.
    """
    if not record:
        return ""
    agent = record.get("agent")
    if not isinstance(agent, str):
        return ""
    return agent if _hook_utils.RELIEF_FLAGS.get(agent) == CODE_REVIEWED else ""


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
    if _code_review_evidence(record):
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
        root, "stop_blocked_code_review", _denial_reasons.GATE_CODE_REVIEW_BLOCK,
        gate=3, rule="GATE_CODE_REVIEW_BLOCK", write_count=write_count,
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
        subprocess.run(
            [sys.executable, str(blueprint_script), "finalize"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=10,
            cwd=str(root),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


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

    # Loop guard: Claude Code re-fires Stop with stop_hook_active=True
    # after a prior block. A persistently-failing gate (docs-refresh /
    # code-review on a long session) would otherwise re-block forever. Honor
    # the protocol's loop signal: ALLOW the stop. This only ADDS an exit-0
    # short-circuit ahead of every gate — it changes no deny predicate.
    # read_stdin_safely() always returns a dict, so .get is safe.
    if data.get("stop_hook_active"):
        return 0

    root = _resolve_project_root()
    write_count = _read_write_count(root)
    mode = _stop_gate_mode()

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

    # Gate 4: auto-finalize blueprint (silent, always passes — preserves
    # session continuity even under MAINTENANCE_MODE).
    _gate_finalize_blueprint(root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
