"""Pin TP-157 157-F/G/E agent-session signals (hook layer, advisory).

Why this contract exists. stop_gate only ever saw ``write_count`` — it was
blind to the agent's trajectory, so a runaway/recursive-tool session ended
silently. 157-F adds a per-session ``tool_call_count`` (EVERY tool call, not
just source writes) + a ``last_tool`` consecutive-repeat streak; 157-G derives
a rolling session-length baseline; 157-E adds an opt-in scan-clean Stop read.

The load-bearing invariants these tests pin:
  - the counter increments on EVERY tool call — it must run BEFORE the
    write-tool early-return in reflect_trigger._run_main (a regression that
    moves it after silently degrades it to a write-only counter);
  - ``tool_call_count`` is flocked exactly like ``write_count`` (no
    concurrent-session drift), and is INDEPENDENT of ``write_count``;
  - every advisory read is stderr-only and returns the non-BLOCK path —
    these are signals, never gates (no ``exit 1``/Stop ``block``);
  - the rolling baseline records once per session (a re-firing Stop must not
    pollute the median with partial-session samples).
"""
from __future__ import annotations

import ast
import inspect
import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_reflect_trigger():
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import reflect_trigger  # type: ignore
        return reflect_trigger
    finally:
        sys.path.pop(0)


def _load_stop_gate():
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import stop_gate  # type: ignore
        return stop_gate
    finally:
        sys.path.pop(0)


def _seed_state(root, *, tool_calls=None, streak=None, history=None):
    state = root / ".espalier-state"
    state.mkdir(parents=True, exist_ok=True)
    if tool_calls is not None:
        (state / "tool_call_count").write_text(str(tool_calls), encoding="utf-8")
    if streak is not None:
        (state / "last_tool").write_text(
            json.dumps({"tool": "Read", "streak": streak}), encoding="utf-8"
        )
    if history is not None:
        (state / "session_length_baseline").write_text(
            json.dumps({"history": history}), encoding="utf-8"
        )
    return state


def _run_reflect_hook(payload: dict, project_dir: Path):
    """PostToolUse reflect_trigger via subprocess + JSON stdin (the hook's real
    entry path), pinned to a tmp CLAUDE_PROJECT_DIR."""
    import os
    import subprocess
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "reflect_trigger.py")],
        input=json.dumps(payload), capture_output=True, text=True, timeout=15, env=env, encoding="utf-8",
    )


class TestToolCallCounter:
    """157-F: tool_call_count + last_tool streak, exercised directly."""

    def test_record_increments_count(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        assert rt._record_tool_call(state, "Read")[0] == 1
        assert rt._record_tool_call(state, "Bash")[0] == 2
        assert (state / "tool_call_count").read_text(encoding="utf-8").strip() == "2"

    def test_session_of_k_calls_leaves_k(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        for _ in range(17):
            rt._record_tool_call(state, "Read")
        assert int((state / "tool_call_count").read_text(encoding="utf-8").strip()) == 17

    def test_consecutive_same_tool_increments_streak(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        assert rt._record_tool_call(state, "Read")[1] == 1
        assert rt._record_tool_call(state, "Read")[1] == 2
        assert rt._record_tool_call(state, "Read")[1] == 3

    def test_streak_resets_on_different_tool(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        rt._record_tool_call(state, "Read")
        rt._record_tool_call(state, "Read")
        assert rt._record_tool_call(state, "Bash")[1] == 1  # reset
        # last_tool persists as small JSON, not an integer or payload blob.
        obj = json.loads((state / "last_tool").read_text(encoding="utf-8"))
        assert obj == {"tool": "Bash", "streak": 1}

    def test_tool_call_count_independent_of_write_count(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        rt._record_tool_call(state, "Read")          # tool_call_count -> 1
        rt._locked_increment(state)                   # write_count -> 1
        assert (state / "tool_call_count").read_text(encoding="utf-8").strip() == "1"
        assert (state / "write_count").read_text(encoding="utf-8").strip() == "1"


def _record_n_times(state_dir: str, n: int) -> int:
    sys.path.insert(0, str(HOOKS_DIR))
    import reflect_trigger
    last = 0
    for _ in range(n):
        last = reflect_trigger._record_tool_call(Path(state_dir), "Read")[0]
    return last


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock contract")
class TestToolCallCounterConcurrency:
    """tool_call_count must be flocked exactly like write_count — concurrent
    PostToolUse fires across parent-repo + worktree sessions must not drift."""

    def test_eight_workers_each_25(self, tmp_path):
        state = tmp_path / ".espalier-state"
        workers, each = 8, 25
        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            pool.starmap(_record_n_times, [(str(state), each)] * workers)
        final = int((state / "tool_call_count").read_text(encoding="utf-8").strip())
        assert final == workers * each, (
            f"tool_call_count drift: expected {workers*each}, got {final}. The "
            f"157-F counter shares write_count's flock contract."
        )


class TestRunMainCountsEveryTool:
    """157-F integration: the counter fires for EVERY tool, including non-write
    tools that hit the write-filter early-return."""

    def test_non_write_tool_is_counted(self, tmp_path):
        result = _run_reflect_hook({"tool_name": "Read", "tool_input": {}}, tmp_path)
        assert result.returncode == 0
        assert (tmp_path / ".espalier-state" / "tool_call_count").read_text(encoding="utf-8").strip() == "1"

    def test_bash_tool_is_counted(self, tmp_path):
        result = _run_reflect_hook({"tool_name": "Bash", "tool_input": {}}, tmp_path)
        assert result.returncode == 0
        assert (tmp_path / ".espalier-state" / "tool_call_count").read_text(encoding="utf-8").strip() == "1"

    def test_write_tool_counts_both_signals(self, tmp_path):
        (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
        result = _run_reflect_hook(
            {"tool_name": "Write", "tool_input": {"file_path": "mod.py"}}, tmp_path
        )
        assert result.returncode == 0
        state = tmp_path / ".espalier-state"
        assert (state / "tool_call_count").read_text(encoding="utf-8").strip() == "1"
        # mod.py is a source file at repo root -> write_count also ticks.
        assert (state / "write_count").read_text(encoding="utf-8").strip() == "1"

    def test_streak_accumulates_across_hook_invocations(self, tmp_path):
        _run_reflect_hook({"tool_name": "Read", "tool_input": {}}, tmp_path)
        _run_reflect_hook({"tool_name": "Read", "tool_input": {}}, tmp_path)
        obj = json.loads((tmp_path / ".espalier-state" / "last_tool").read_text(encoding="utf-8"))
        assert obj == {"tool": "Read", "streak": 2}

    def test_empty_tool_name_not_counted(self, tmp_path):
        result = _run_reflect_hook({"tool_name": "", "tool_input": {}}, tmp_path)
        assert result.returncode == 0
        assert not (tmp_path / ".espalier-state" / "tool_call_count").exists()


class TestTrajectoryAdvisory:
    """157-G: rolling-baseline trajectory anomaly + 157-F recursive-burst, both
    warn-only (stderr), never stdout, recorded once per session."""

    def test_read_tool_call_count_and_streak(self, tmp_path):
        sg = _load_stop_gate()
        _seed_state(tmp_path, tool_calls=42, streak=7)
        assert sg._read_tool_call_count(tmp_path) == 42
        assert sg._read_last_tool_streak(tmp_path) == 7

    def test_read_last_tool_streak_null_safe(self, tmp_path):
        """Regression (final-review): an explicit null streak (producer drift)
        must coerce to 0, not raise TypeError — the reader is under stop_gate's
        FAIL-CLOSED umbrella, so a raise here would BLOCK the Stop."""
        sg = _load_stop_gate()
        state = tmp_path / ".espalier-state"
        state.mkdir()
        (state / "last_tool").write_text(json.dumps({"tool": "Read", "streak": None}), encoding="utf-8")
        assert sg._read_last_tool_streak(tmp_path) == 0  # no raise

    def test_warns_on_trajectory_anomaly(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_state(tmp_path, tool_calls=50, history=[10, 10, 10])  # 50 > 3×10
        sg._advise_session_signals(tmp_path)
        captured = capsys.readouterr()
        assert "157-G advisory" in captured.err
        assert captured.out == ""  # channel-XOR: NOTHING to stdout

    def test_no_warn_for_normal_session(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_state(tmp_path, tool_calls=12, history=[10, 10, 10])  # 12 < 3×10
        sg._advise_session_signals(tmp_path)
        assert "157-G advisory" not in capsys.readouterr().err

    def test_no_warn_below_min_sessions(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_state(tmp_path, tool_calls=999, history=[1])  # only 1 prior
        sg._advise_session_signals(tmp_path)
        # Too little history to judge — record, don't warn.
        assert "157-G advisory" not in capsys.readouterr().err

    def test_recursive_streak_warns(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_state(tmp_path, tool_calls=30, streak=40)  # >= RECURSIVE threshold
        sg._advise_session_signals(tmp_path)
        assert "157-F advisory" in capsys.readouterr().err

    def test_records_once_per_session(self, tmp_path):
        sg = _load_stop_gate()
        state = _seed_state(tmp_path, tool_calls=50, history=[10, 10, 10])
        sg._advise_session_signals(tmp_path)
        hist1 = json.loads((state / "session_length_baseline").read_text(encoding="utf-8"))["history"]
        assert hist1 == [10, 10, 10, 50]
        assert (state / "session_length_recorded").exists()
        # Second Stop fire this session must NOT append again (no pollution).
        sg._advise_session_signals(tmp_path)
        hist2 = json.loads((state / "session_length_baseline").read_text(encoding="utf-8"))["history"]
        assert hist2 == [10, 10, 10, 50]

    def test_zero_count_is_noop(self, tmp_path):
        sg = _load_stop_gate()
        state = tmp_path / ".espalier-state"
        sg._advise_session_signals(tmp_path)  # no tool_call_count at all
        assert not (state / "session_length_baseline").exists()
        assert not (state / "session_length_recorded").exists()

    def test_history_capped(self, tmp_path):
        sg = _load_stop_gate()
        state = _seed_state(tmp_path, tool_calls=5, history=list(range(20)))
        sg._advise_session_signals(tmp_path)
        hist = json.loads((state / "session_length_baseline").read_text(encoding="utf-8"))["history"]
        assert len(hist) == sg.SESSION_LENGTH_HISTORY_CAP  # rolled, not unbounded
        assert hist[-1] == 5


def _seed_telemetry(root, runs):
    """runs = list of {scanner: fires} dicts; one run per dict."""
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, run in enumerate(runs):
        for scanner, fires in run.items():
            lines.append(json.dumps(
                {"run_ts": f"T{i}", "scanner": scanner, "fires": fires, "exemptions": 0}
            ))
    (reports / "scan_telemetry.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return reports


class TestScanCleanGate:
    """157-E: opt-in scan-clean advisory reads telemetry AS A FILE, warns on
    rising findings, stderr-only, no-op when telemetry absent."""

    def test_warns_on_rising_findings(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_telemetry(tmp_path, [{"exceptions": 1}, {"exceptions": 5}])  # 1 -> 5
        sg._gate_scan_clean(tmp_path)
        cap = capsys.readouterr()
        assert "157-E advisory" in cap.err
        assert cap.out == ""  # channel-XOR: never stdout

    def test_silent_when_not_rising(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_telemetry(tmp_path, [{"exceptions": 5}, {"exceptions": 3}])  # fell
        sg._gate_scan_clean(tmp_path)
        assert "157-E advisory" not in capsys.readouterr().err

    def test_noop_when_telemetry_absent(self, tmp_path, capsys):
        sg = _load_stop_gate()
        sg._gate_scan_clean(tmp_path)  # no reports/ at all
        cap = capsys.readouterr()
        assert cap.err == "" and cap.out == ""

    def test_noop_single_run(self, tmp_path, capsys):
        sg = _load_stop_gate()
        _seed_telemetry(tmp_path, [{"exceptions": 99}])  # only one run
        sg._gate_scan_clean(tmp_path)
        assert "157-E advisory" not in capsys.readouterr().err

    def test_never_imports_espalier(self):
        """tools/cc isolation: the Stop hook must read telemetry as a file,
        never import espalier."""
        sg = _load_stop_gate()
        tree = ast.parse(inspect.getsource(sg))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not n.name.startswith("espalier") for n in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("espalier")


class TestModeContract:
    """157-E must extend _stop_gate_mode's recognized set so scan-clean does NOT
    fall through to the unknown-value warn+light path (the 0-A top finding) —
    while still warning on genuinely-unknown values."""

    def test_scan_clean_recognized(self, monkeypatch, capsys):
        sg = _load_stop_gate()
        monkeypatch.setenv("ESPALIER_STOP_GATE", "scan-clean")
        assert sg._stop_gate_mode() == sg.STOP_GATE_SCAN_CLEAN
        assert "unknown" not in capsys.readouterr().err  # no false warn

    def test_full_and_light_unchanged(self, monkeypatch):
        sg = _load_stop_gate()
        monkeypatch.setenv("ESPALIER_STOP_GATE", "full")
        assert sg._stop_gate_mode() == sg.STOP_GATE_FULL
        monkeypatch.setenv("ESPALIER_STOP_GATE", "  LIGHT  ")  # strip + lower
        assert sg._stop_gate_mode() == sg.STOP_GATE_LIGHT

    def test_unknown_still_warns_and_falls_back(self, monkeypatch, capsys):
        sg = _load_stop_gate()
        monkeypatch.setenv("ESPALIER_STOP_GATE", "bogus")
        assert sg._stop_gate_mode() == sg.STOP_GATE_LIGHT
        assert "unknown ESPALIER_STOP_GATE" in capsys.readouterr().err


class TestStopGateScanCleanIntegration:
    """End-to-end: ESPALIER_STOP_GATE=scan-clean emits the advisory on stderr,
    exits 0, and writes NOTHING to stdout (block() is the sole stdout channel)."""

    def test_scan_clean_stop_exits_zero_stderr_only(self, tmp_path):
        _seed_telemetry(tmp_path, [{"exceptions": 1}, {"exceptions": 9}])
        (tmp_path / ".espalier-state").mkdir()
        (tmp_path / ".espalier-state" / "tool_call_count").write_text("12", encoding="utf-8")
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["ESPALIER_STOP_GATE"] = "scan-clean"
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
            input=json.dumps({}), capture_output=True, text=True, timeout=20, env=env, encoding="utf-8",
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""        # channel-XOR: no block JSON
        assert "157-E advisory" in result.stderr   # rising-findings advisory fired

    def test_advisory_fires_even_when_gate2_blocks(self, tmp_path):
        """Regression (final-review): the scan-clean advisory must run BEFORE
        Gates 2/3. On a long session (write_count>=10, no docs_refreshed flag)
        Gate 2 blocks — but the advisory should already have fired to stderr.
        Run WITHOUT maintenance mode so Gates 2/3 are active."""
        _seed_telemetry(tmp_path, [{"exceptions": 1}, {"exceptions": 9}])
        state = tmp_path / ".espalier-state"
        state.mkdir()
        (state / "write_count").write_text("15", encoding="utf-8")   # >= 10
        (state / "tool_call_count").write_text("20", encoding="utf-8")
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["ESPALIER_STOP_GATE"] = "scan-clean"
        env.pop("ESPALIER_MAINTENANCE_MODE", None)  # so Gate 2 is live
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
            input=json.dumps({}), capture_output=True, text=True, timeout=20, env=env, encoding="utf-8",
        )
        assert result.returncode == 0
        # Gate 2 blocked (docs refresh) -> block JSON on stdout ...
        assert '"decision"' in result.stdout
        # ... but the advisory ALREADY fired to stderr (ordering fix).
        assert "157-E advisory" in result.stderr
