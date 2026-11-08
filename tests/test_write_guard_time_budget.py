"""write_guard's time budget: a judgment that runs long is refused, not let through.

Claude Code cancels a PreToolUse command hook at its wired timeout, and a
cancelled command hook does not block (``docs/external/cc-hook-protocol.md``,
"Timeouts"). A long generated delete list made the guard's judgment run past
it, so the whole guard -- the wall, the nudge, the zone check, the kill-switch
gate -- was skipped for that call. ``write_guard.main`` now judges in a worker
thread under ``JUDGMENT_BUDGET_S`` and denies the call, as it denies any call
(exit 0, one stdout JSON deny object through the audited funnel), when the
budget runs out first.

Every row here injects a slow judgment (``_run_main`` replaced by a stub that
waits on an event) under a tiny budget, and the budget's wait is gated to start
only once the judgment has begun, so nothing depends on how fast the runner is
or how the threads are scheduled, and no command is ever executed. No row here
drives a real long list: its timing is the runner's, so it was driven by hand
when the budget landed (the struck ledger row and the CHANGELOG carry the
numbers), and the property it rests on -- the judgment hands the interpreter
lock to the waiting thread between its many short calls -- is measured, not
pinned.

That property fails for one long call: a compiled pattern's search holds the
lock for its whole call, so the budget's thread wakes only when it ends
(DEF-3048). The hook process is now a thin parent that answers through a
judging child and kills the child's tree at ``HARD_DEADLINE_S``. The rows from
``TestOneLongCallInTheJudgmentIsRefusedInTime`` on run the real hook as a
process, a ``sitecustomize`` seam standing in for the slow or failing part:
the strike row (one long search, refused under the wired timeout), the relay
(the child's answer goes out byte for byte), the fallback where no child can
start, and the child's own CPU cap.
"""
# slow-exempt: short hook-shaped children -- a stuck judgment, the relay, fallback and CPU-cap rows (a fraction of a second each), the strike row (about 4 s: the deadline it proves), one fresh-process module census
from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _denial_reasons  # noqa: E402
import _hook_utils  # noqa: E402
import write_guard  # noqa: E402

#: The least the budget leaves under the wired timeout: the spawn and the
#: interpreter's start before the hook's first line, the waiting thread's wake,
#: the refusal's record and a state write in flight all spend it. Driven on the
#: Windows self-host box (2026-10-07) the refusal exited at about 3.6 s from
#: the spawn against the 5 s timeout.
_MARGIN_UNDER_TIMEOUT_S = 1.0
#: The least the budget may be: an ordinary call costs about 0.3 s in all on
#: the same box (interpreter, import, judgment), and the budget stays ten times
#: above it so a slow runner never refuses an ordinary call.
_BUDGET_FLOOR_S = 3.0
#: The tiny budget the injected rows run under.
_TINY_BUDGET_S = 0.05
#: How long a row waits on an event before it calls the run broken. Never the
#: thing measured: every wait here ends on its event long before this.
_EVENT_CEILING_S = 30.0
#: Slack for the exact bound on a spawn's timeout. The hook arms the deadline
#: as ``clock + budget`` and asks ``deadline - time.monotonic() - reserve``; on a
#: host whose monotonic clock is coarse (Windows under CPython 3.12 and earlier
#: ticks at 15.6 ms; 3.13 moved the clock to QueryPerformanceCounter, per its
#: release notes) both reads can return the same tick, and
#: ``(clock + 10.0) - clock - 0.5`` is not always ``9.5`` in floating point: 3 of
#: 200,000 simulated clock values read above it (worst by 1.2e-10), none with
#: the clock advanced one tick. Measured red on the windows-latest portability
#: cell of #171, which runs 3.12 (2026-10-10, DEF-4000). A microsecond is about
#: eight thousand times the simulation's worst excess and sixty millionths of
#: a tick: a change in the hook's arithmetic still reds through it.
_SAME_TICK_SLACK_S = 1e-6

_DENY = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                "permissionDecisionReason": "the stub's own decision"}}


def _audit_records() -> list[dict]:
    """Every record in the redirected audit dir (``tests/conftest.py``)."""
    out: list[dict] = []
    for log in sorted(Path(os.environ["ESPALIER_AUDIT_DIR"]).glob("*.log")):
        out.extend(json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip())
    return out


def _types() -> list[str]:
    return [r["event_type"] for r in _audit_records()]


def _payload(tool: str = "Bash", tool_input: dict | None = None) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"command": "git status"} if tool_input is None else tool_input}


class _Streams:
    """The streams one ``main()`` call sees as real."""

    def __init__(self) -> None:
        self.out, self.err = io.StringIO(), io.StringIO()


def _drive(monkeypatch: pytest.MonkeyPatch, payload: dict) -> tuple[int, _Streams]:
    """``write_guard.main()`` in process, the payload on stdin."""
    streams = _Streams()
    raw = io.BytesIO(json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(raw, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", streams.out)
    monkeypatch.setattr(sys, "stderr", streams.err)
    return int(write_guard.main()), streams


def _decisions(text: str) -> list[dict]:
    """Every stdout JSON object, one a line."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _the_one_deny(streams: "_Streams") -> str:
    """The reason of the call's one decision, which must be a deny."""
    decisions = _decisions(streams.out.getvalue())
    assert len(decisions) == 1, decisions
    decision = decisions[0]["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    return str(decision["permissionDecisionReason"])


def _judgment_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == write_guard.JUDGMENT_THREAD_NAME]


class _SlowJudgment:
    """A stand-in for ``_run_main`` that waits until released, then returns
    (printing a decision first when ``decides``). ``holds_state_lock`` makes it
    hold the state-write lock while it waits, the shape of a write in flight."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release_state_lock = threading.Event()
        self.decides = False
        self.holds_state_lock = False

    def __call__(self, data: dict | None = None) -> int:
        if self.holds_state_lock:
            with _hook_utils.STATE_WRITE_LOCK:
                self.entered.set()  # inside the lock: the budget's wait starts after it is held
                self.release_state_lock.wait(_EVENT_CEILING_S)
        else:
            self.entered.set()
        self.release.wait(_EVENT_CEILING_S)
        if self.decides:
            print(json.dumps(_DENY))
            print("[write_guard] a late line from the judgment", file=sys.stderr)
            return int(_hook_utils.DENIED)
        return 0


def _use_threading(monkeypatch: pytest.MonkeyPatch, *, event: type = threading.Event,
                   thread: type = threading.Thread) -> None:
    """``write_guard``'s view of ``threading``, with the event or thread class
    a row needs (the claim's lock stays the real one)."""
    monkeypatch.setattr(write_guard, "threading", types.SimpleNamespace(
        Event=event, Thread=thread, Lock=threading.Lock,
    ))


def _gated_event(judgment: _SlowJudgment, *, then=None) -> type:
    """An Event whose timed wait -- the budget's -- starts only once the
    judgment has begun (stdin read, the stub entered, the state-write lock
    held when the row asks for it); ``then`` runs when the wait returns."""

    class _Gated(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            if timeout is None:
                return super().wait()
            assert judgment.entered.wait(_EVENT_CEILING_S), "the judgment never began"
            got = super().wait(timeout)
            if then is not None:
                then()
            return got

    return _Gated


@pytest.fixture
def guard_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch, guard_root: Path):
    """A slow judgment under a tiny budget, the budget's wait gated on the
    judgment having begun. Teardown releases it and joins every judgment
    thread, so no worker outlives its row."""
    judgment = _SlowJudgment()
    monkeypatch.setattr(write_guard, "_run_main", judgment)
    monkeypatch.setattr(write_guard, "JUDGMENT_BUDGET_S", _TINY_BUDGET_S)
    _use_threading(monkeypatch, event=_gated_event(judgment))
    yield judgment
    judgment.release_state_lock.set()
    judgment.release.set()
    for t in _judgment_threads():
        t.join(_EVENT_CEILING_S)
    assert not _judgment_threads(), "a judgment thread outlived its row"


class TestTheBudgetSitsBelowTheWiring:
    def test_the_budget_leaves_a_margin_under_the_wired_timeout(self):
        from espalier.harness_config import CANONICAL_HOOK_WIRING

        timeout = CANONICAL_HOOK_WIRING["write_guard.py"]["timeout"]
        assert write_guard.JUDGMENT_BUDGET_S + _MARGIN_UNDER_TIMEOUT_S <= timeout, (
            f"budget {write_guard.JUDGMENT_BUDGET_S} s leaves under {_MARGIN_UNDER_TIMEOUT_S} s "
            f"below the wired {timeout} s timeout"
        )
        assert write_guard.JUDGMENT_BUDGET_S >= _BUDGET_FLOOR_S
        assert 0 < write_guard.MIN_JUDGMENT_WINDOW_S < write_guard.JUDGMENT_BUDGET_S

    def test_the_hook_process_counts_from_its_first_line_and_exits_on_a_refusal(self):
        tree = ast.parse((HOOKS_DIR / "write_guard.py").read_text(encoding="utf-8"))
        # The `__name__` block that calls main(): the first one says the floor.
        main_block = next(
            n for n in tree.body
            if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"
            and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "main"
                    for c in ast.walk(n))
        )
        calls = [c for c in ast.walk(main_block) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name) and c.func.id == "main"]
        assert len(calls) == 1, ast.unparse(main_block)
        kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
        assert kw == {"started": "_HOOK_STARTED", "exit_on_budget": "True"}, kw
        # The clock reads before the first co-located helper module imports
        # (the import is most of an ordinary call's cost). Every helper imports
        # under a guard since the start refusal moved out of the floor
        # (DEF-3008), so a top-level `try` body is read as the top level.
        started_at = next(n.lineno for n in tree.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "_HOOK_STARTED" for t in n.targets))
        top = [m for n in tree.body for m in (n.body if isinstance(n, ast.Try) else [n])]
        first_helper = next(n.lineno for n in top if isinstance(n, ast.Import)
                            and any(a.name.startswith("_") for a in n.names))
        assert started_at < first_helper


class TestAJudgmentInTimeIsUnchanged:
    @pytest.mark.parametrize("rel, decides", [(".claude/settings.json", True), ("src/app.py", False)])
    def test_main_emits_what_the_judgment_emits(self, monkeypatch, guard_root, rel, decides):
        payload = _payload("Write", {"file_path": str(guard_root / rel), "content": "x"})
        direct = io.StringIO()
        monkeypatch.setattr(sys, "stdout", direct)
        write_guard._run_main(payload)
        rc, streams = _drive(monkeypatch, payload)
        assert streams.out.getvalue() == direct.getvalue()
        assert bool(streams.out.getvalue()) is decides
        assert rc == 0
        assert "pretooluse_blocked_time_budget" not in _types()

    @pytest.mark.parametrize("where", ["_run_main", "read_stdin_safely"])
    def test_the_crash_guard_still_denies_on_stdout(self, monkeypatch, guard_root, where):
        def _boom(data=None):
            raise ValueError("synthetic")

        # The payload's read moved into the worker with the judgment; a raise
        # there is the umbrella's as much as one in the judgment itself.
        monkeypatch.setattr(write_guard if where == "_run_main" else _hook_utils, where, _boom)
        rc, streams = _drive(monkeypatch, _payload())
        assert rc == 0
        decision = json.loads(streams.out.getvalue())["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "internal error" in decision["permissionDecisionReason"]
        assert "write_guard crashed" in streams.err.getvalue()
        assert _types() == ["pretooluse_blocked_internal_error"]


class TestASlowJudgmentIsRefused:
    @pytest.mark.parametrize("tool, tool_input", [
        ("Bash", {"command": "git status"}),
        ("PowerShell", {"command": "Get-ChildItem"}),
        ("Write", {"file_path": "src/app.py", "content": "x"}),
        ("Edit", {"file_path": "src/app.py", "old_string": "a", "new_string": "b"}),
        ("NotebookEdit", {"notebook_path": "nb.ipynb", "new_source": "x"}),
        ("mcp__filesystem__write_file", {"path": "src/app.py", "content": "x"}),
        ("Read", {"file_path": "README.md"}),
    ])
    def test_every_tool_is_denied_through_the_funnel(self, monkeypatch, slow, tool, tool_input):
        rc, streams = _drive(monkeypatch, _payload(tool, tool_input))
        # The structured channel, as every other deny: exit 0, one stdout
        # JSON deny object carrying the split-it reason, nothing on stderr.
        assert rc == 0
        expected = _denial_reasons.WRITE_GUARD_TIME_BUDGET.format(budget=_TINY_BUDGET_S)
        assert _the_one_deny(streams) == expected
        assert streams.err.getvalue() == ""
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_blocked_time_budget"]
        assert len(records) == 1, _types()
        command = tool_input.get("command")
        assert records[0]["details"] == {
            "hook": "write_guard", "tool": tool, "budget_s": _TINY_BUDGET_S,
            "chars": len(command) if command else 0,
        }

    def test_maintenance_mode_does_not_lift_the_budget(self, monkeypatch, slow):
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
        rc, streams = _drive(monkeypatch, _payload())
        assert rc == 0
        assert "could not finish judging" in _the_one_deny(streams)
        assert "pretooluse_blocked_time_budget" in _types()

    def test_the_refusal_names_the_split_and_the_wrong_move(self):
        text = _denial_reasons.WRITE_GUARD_TIME_BUDGET.format(budget=3.5)
        assert "3.5 s" in text
        assert "Don't:" in text and "Do:" in text and "split" in text
        assert text.isascii()

    def test_a_refused_judgments_late_output_is_discarded(self, monkeypatch, slow):
        slow.decides = True
        rc, streams = _drive(monkeypatch, _payload())
        assert rc == 0
        # The caller's own print, while the refused judgment still runs,
        # reaches its stream: only the judgment's writes are held.
        print("the caller is not silenced")
        slow.release.set()
        for t in _judgment_threads():
            t.join(_EVENT_CEILING_S)
        # The judgment printed a decision and a line once released: neither
        # reached the streams the call answered on, and the streams are back.
        lines = streams.out.getvalue().splitlines()
        assert len(lines) == 2 and lines[1] == "the caller is not silenced", lines
        decision = json.loads(lines[0])["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "could not finish judging" in decision["permissionDecisionReason"]
        assert "late line" not in streams.err.getvalue()
        assert sys.stdout is streams.out and sys.stderr is streams.err

    def test_the_refusal_waits_for_a_state_write_in_flight(self, monkeypatch, slow):
        slow.holds_state_lock = True
        # The refusal's own record would wait on the same lock first (any
        # append does); a no-op record leaves the refusal's hold of the lock,
        # around its exit, as the only thing that can keep the caller waiting.
        monkeypatch.setattr(write_guard, "_audit", lambda *a, **k: None)
        result: list[tuple[int, _Streams]] = []
        caller = threading.Thread(target=lambda: result.append(_drive(monkeypatch, _payload())))
        caller.start()
        assert slow.entered.wait(_EVENT_CEILING_S)
        caller.join(0.3)
        # The budget ran out long ago, but the judgment holds the state-write
        # lock (a write in flight): the refusal neither exits nor answers yet.
        assert caller.is_alive()
        assert result == []
        slow.release_state_lock.set()
        caller.join(_EVENT_CEILING_S)
        assert not caller.is_alive()
        rc, streams = result[0]
        assert rc == 0
        assert "could not finish judging" in _the_one_deny(streams)


class TestExactlyOneVerdict:
    def test_the_claim_admits_one_claimant(self):
        verdict = write_guard._Verdict()
        wins: list[str] = []
        gate = threading.Barrier(16)

        def _claim(i: int) -> None:
            gate.wait()
            if verdict.claim(f"c{i}", i):
                wins.append(f"c{i}")

        threads = [threading.Thread(target=_claim, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(_EVENT_CEILING_S)
        assert len(wins) == 1 and verdict.by == wins[0]
        assert not verdict.claim("late")

    def _race(self, monkeypatch, slow, *, judgment_wins: bool) -> tuple[int, _Streams]:
        """Drive the instant the budget runs out: either the judgment returns
        and claims between the wait's timeout and the main thread's claim, or
        it returns the instant after the main thread claimed."""
        slow.decides = True
        judged = threading.Event()

        class _Signalling(write_guard._Verdict):
            def claim(self, by: str, value: object = None) -> bool:
                won = super().claim(by, value)
                if won and by == "judged":
                    judged.set()
                if won and by == "budget":
                    slow.release.set()  # the judgment ends right after the budget claimed
                return won

        def _at_the_budget() -> None:
            if judgment_wins:
                slow.release.set()  # the judgment returns now ...
                assert judged.wait(_EVENT_CEILING_S)  # ... and claims first

        monkeypatch.setattr(write_guard, "_Verdict", _Signalling)
        _use_threading(monkeypatch, event=_gated_event(slow, then=_at_the_budget))
        rc, streams = _drive(monkeypatch, _payload())
        for t in _judgment_threads():
            t.join(_EVENT_CEILING_S)
        return rc, streams

    def test_a_judgment_that_claims_at_the_budget_is_the_one_verdict(self, monkeypatch, slow):
        rc, streams = self._race(monkeypatch, slow, judgment_wins=True)
        assert rc == 0
        assert _decisions(streams.out.getvalue()) == [_DENY]
        assert "could not finish judging" not in streams.out.getvalue()
        assert "pretooluse_blocked_time_budget" not in _types()

    def test_a_budget_that_claims_first_is_the_one_verdict(self, monkeypatch, slow):
        rc, streams = self._race(monkeypatch, slow, judgment_wins=False)
        assert rc == 0
        # The refusal is the one decision; the judgment's own deny, printed
        # the instant after the budget claimed, never reached stdout.
        assert "could not finish judging" in _the_one_deny(streams)
        assert "late line" not in streams.err.getvalue()
        assert _types().count("pretooluse_blocked_time_budget") == 1


class TestTheEntryPointsEdges:
    def test_an_interrupted_wait_refuses_as_the_crash_guard_does(self, monkeypatch, slow):
        def _interrupt() -> None:
            raise KeyboardInterrupt

        _use_threading(monkeypatch, event=_gated_event(slow, then=_interrupt))
        rc, streams = _drive(monkeypatch, _payload())
        assert rc == 0
        assert _the_one_deny(streams) == _denial_reasons.WRITE_GUARD_INTERNAL_ERROR
        assert streams.err.getvalue() == ""
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_blocked_internal_error"]
        assert [r["details"] for r in records] == [{"hook": "write_guard", "error": "KeyboardInterrupt"}]

    @pytest.mark.parametrize("fault", [RuntimeError, MemoryError])
    def test_a_thread_that_cannot_start_judges_inline_and_says_so(self, monkeypatch, guard_root, fault):
        # Any fault in setting the worker up, not only the documented one: an
        # escape from main() would exit non-zero, which lets the call through.
        class _NoThread(threading.Thread):
            def start(self) -> None:
                raise fault("can't start new thread")

        _use_threading(monkeypatch, thread=_NoThread)
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())  # say_once's per-process memory
        payload = _payload("Write", {"file_path": str(guard_root / ".claude" / "settings.json"), "content": "x"})
        rc, streams = _drive(monkeypatch, payload)
        assert rc == 0
        assert json.loads(streams.out.getvalue())["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "time budget is off" in streams.err.getvalue()
        assert "pretooluse_failed_open_time_budget" in _types()


#: The driver for the hook-process row: the real entry point with a stuck
#: judgment, ``exit_on_budget`` as the ``__main__`` block passes it.
_HOOK_PROCESS_DRIVER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import write_guard

    def _stuck(data=None):
        time.sleep(float(sys.argv[2]))
        print('{"late": "decision"}')
        return 0

    write_guard._run_main = _stuck
    write_guard.JUDGMENT_BUDGET_S = 0.2
    raise SystemExit(int(write_guard.main(exit_on_budget=True)))
""")


class TestTheHookProcessExitsWithoutWaiting:
    def test_a_refusal_ends_the_process_with_one_deny_while_the_judgment_still_runs(self, tmp_path):
        driver = tmp_path / "drive_budget.py"
        driver.write_text(_HOOK_PROCESS_DRIVER, encoding="utf-8")
        # Structural, not a speed claim: the judgment stays stuck for longer
        # than the subprocess bound allows the process to live, so the process
        # can only end by the refusal; the bound sits well inside
        # pytest-timeout's per-test 60 s (pyproject.toml).
        stuck_s = 40.0
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(driver), str(HOOKS_DIR), str(stuck_s)],
            input=json.dumps(_payload()), capture_output=True, text=True, encoding="utf-8",
            timeout=stuck_s / 2, env=env,
        )
        assert result.returncode == 0, (result.returncode, result.stderr)
        decisions = _decisions(result.stdout)
        assert len(decisions) == 1, result.stdout  # the stuck judgment's late print never lands
        decision = decisions[0]["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "could not finish judging this command within its 0.2 s time budget" in (
            decision["permissionDecisionReason"])
        assert "could not finish judging" not in result.stderr
        assert "pretooluse_blocked_time_budget" in _types()


#: A ``sitecustomize`` that stalls the judgment the way DEF-3048 was driven. The
#: payload's parse (``_hook_utils.read_stdin_safely`` calls ``json.loads`` in the
#: judging thread) first starts a sleeping grandchild and records its pid,
#: written whole and renamed into place. Then it runs ONE compiled-pattern
#: search that backtracks for far longer than any bound here. A search holds the
#: interpreter lock for its whole call, so the thread waiting on the budget
#: cannot wake; only a bound outside the judging process can answer in time. It
#: fires on the marker in the command alone, so nothing else in any process the
#: hook starts is slowed.
_STALL_SITE = textwrap.dedent('''
    import json, os, re, subprocess, sys
    _loads = json.loads
    def _stalling_loads(text, *args, **kwargs):
        if isinstance(text, str) and "STALL-IN-ONE-C-CALL" in text:
            sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            part = os.environ["STALL_PID_FILE"] + ".tmp"
            with open(part, "w", encoding="utf-8") as fh:
                fh.write(str(sleeper.pid))
            os.replace(part, os.environ["STALL_PID_FILE"])
            re.match(r"(a+)+$", "a" * 40 + "!")
        return _loads(text, *args, **kwargs)
    json.loads = _stalling_loads
''')

#: The strike row's bound on the hook process: it ends only a run the hook
#: never answers (the unbounded judgment's search outlasts it many times over),
#: three wired timeouts, so a deny that lands late reads as late, not as hung.
_UNANSWERED_RUN_BOUND_S = 15.0


def _pid_alive(pid: int) -> bool:
    """Whether ``pid`` names a running process (Windows: ``tasklist``; POSIX: signal 0)."""
    if os.name == "nt":
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        return f'"{pid}"' in listed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _end_the_sleeper(pid_file: Path) -> None:
    """Teardown: end the one sleeper the stalled judgment started, by the pid it
    recorded, where it is still alive. It is the only process this ends."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if _pid_alive(pid):
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        else:
            import signal
            os.kill(pid, signal.SIGKILL)


class TestOneLongCallInTheJudgmentIsRefusedInTime:
    """DEF-3048: the thread budget alone answered at the length of the call in
    flight, past the wired timeout, which let the call through unjudged. A
    judgment sitting in one long lock-holding call is now refused before the
    timeout, and the processes it started end with it."""

    def test_the_deny_lands_under_the_wired_timeout_and_the_judgments_tree_ends(self, tmp_path):
        from espalier.harness_config import CANONICAL_HOOK_WIRING

        timeout = CANONICAL_HOOK_WIRING["write_guard.py"]["timeout"]
        site = tmp_path / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(_STALL_SITE, encoding="utf-8")
        pid_file = tmp_path / "sleeper.pid"
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path), PYTHONPATH=str(site),
                   STALL_PID_FILE=str(pid_file))
        payload = _payload("Bash", {"command": "echo STALL-IN-ONE-C-CALL"})
        assert _UNANSWERED_RUN_BOUND_S > timeout, "the run's bound must leave the wired timeout room to fail"
        try:
            started = time.monotonic()
            try:
                result = subprocess.run(
                    [sys.executable, str(HOOKS_DIR / "write_guard.py")], input=json.dumps(payload),
                    capture_output=True, text=True, encoding="utf-8", timeout=_UNANSWERED_RUN_BOUND_S, env=env,
                )
            except subprocess.TimeoutExpired:
                # The defect itself, failed by name: the unbounded judgment
                # never answers, and Claude Code would have let the call
                # through at its timeout (a bare TimeoutExpired reads as a row
                # that never reached its assertion).
                pytest.fail(f"the hook gave no answer within {_UNANSWERED_RUN_BOUND_S} s, so Claude Code's"
                            f" {timeout} s timeout would let the call through unjudged")
            elapsed = time.monotonic() - started
            assert pid_file.is_file(), ("the seam never fired: the judgment did not stall", result.stderr)
            sleeper = int(pid_file.read_text(encoding="utf-8").strip())
            assert result.returncode == 0, (result.returncode, result.stderr)
            decisions = _decisions(result.stdout)
            assert len(decisions) == 1, result.stdout
            decision = decisions[0]["hookSpecificOutput"]
            assert decision["permissionDecision"] == "deny", decision
            assert "could not finish judging this command within its" in decision["permissionDecisionReason"]
            assert elapsed < timeout, f"the deny landed at {elapsed:.2f} s, past the wired {timeout} s timeout"
            gone_by = time.monotonic() + 5.0
            while _pid_alive(sleeper) and time.monotonic() < gone_by:
                time.sleep(0.05)
            assert not _pid_alive(sleeper), "the judgment's grandchild outlived the refusal"
        finally:
            _end_the_sleeper(pid_file)


def _run_the_hook(root: Path, payload: dict, *, judge: bool = False, site: Path | None = None,
                  extra_env: dict | None = None) -> tuple[int, bytes, bytes]:
    """The real hook as a process, bytes in and bytes out: as Claude Code starts
    it, or (``judge``) as its parent starts the judging child. ``site`` holds a
    ``sitecustomize`` the row needs in every process the run starts."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), **(extra_env or {}))
    if site is not None:
        env["PYTHONPATH"] = str(site)
    argv = [sys.executable, str(HOOKS_DIR / "write_guard.py")] + ([write_guard._JUDGE_FLAG] if judge else [])
    result = subprocess.run(argv, input=json.dumps(payload).encode("utf-8"), capture_output=True,
                            timeout=30, env=env)
    return result.returncode, result.stdout, result.stderr


def _site(tmp_path: Path, body: str) -> Path:
    """A directory holding ``body`` as its ``sitecustomize``."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(body, encoding="utf-8")
    return site


#: A ``sitecustomize`` that stands in for the judging child: in a process
#: started with the judge flag it writes the bytes and ends with the code the
#: row names, before any of the guard's own code runs. The hook process itself
#: (no flag) runs as it is, so what the row reads is the parent's relay alone.
_STAND_IN_CHILD_SITE = textwrap.dedent('''
    import os, sys
    if sys.argv[1:2] == ["--judge"]:
        os.write(1, bytes.fromhex(os.environ["RELAY_OUT"]))
        os.write(2, bytes.fromhex(os.environ["RELAY_ERR"]))
        if os.environ["RELAY_CODE"] == "signal":
            import signal
            signal.raise_signal(signal.SIGKILL)
        os._exit(int(os.environ["RELAY_CODE"]))
''')

#: A ``sitecustomize`` that makes the judging child's first helper import fail,
#: so the child answers with the start refusal; the hook process is untouched.
_NO_HELPERS_IN_THE_CHILD_SITE = textwrap.dedent('''
    import sys
    if sys.argv[1:2] == ["--judge"]:
        sys.modules["_hook_utils"] = None
''')

#: A ``sitecustomize`` under which no judging child can start: the spawn of a
#: command carrying the judge flag raises ``OSError``, the shape of a spawn the
#: box refuses. Every other spawn (git, for one) runs as it is.
_NO_JUDGING_CHILD_SITE = textwrap.dedent('''
    import subprocess
    _Popen = subprocess.Popen
    class _NoJudgingChild(_Popen):
        def __init__(self, args, *rest, **kwargs):
            if "--judge" in list(args):
                raise OSError("this row starts no judging child")
            super().__init__(args, *rest, **kwargs)
    subprocess.Popen = _NoJudgingChild
''')

#: A ``sitecustomize`` that records the CPU cap of the process parsing the
#: payload (the judging child: the parent passes the payload's bytes through
#: unparsed), written whole and renamed into place, on the marker alone.
_READ_THE_CPU_CAP_SITE = textwrap.dedent('''
    import json, os
    _loads = json.loads
    def _reading_loads(text, *args, **kwargs):
        if isinstance(text, str) and "READ-THE-CPU-CAP" in text:
            import resource
            part = os.environ["CPU_CAP_FILE"] + ".tmp"
            with open(part, "w", encoding="utf-8") as fh:
                fh.write(" ".join(str(n) for n in resource.getrlimit(resource.RLIMIT_CPU)))
            os.replace(part, os.environ["CPU_CAP_FILE"])
        return _loads(text, *args, **kwargs)
    json.loads = _reading_loads
''')


class TestTheHookAnswersThroughItsJudgingChild:
    """DEF-3048's parent changes how the verdict reaches Claude Code, never what
    it is: the judging child's stdout, stderr and exit code go out byte for
    byte; where no child can start, the hook process judges as it did before
    the bound and says so once; and the child caps its own CPU time, the
    backstop for a child whose parent was ended from outside."""

    @pytest.mark.parametrize(("code", "out", "err"), [
        (0, b'{"hookSpecificOutput": {"hookEventName": "PreToolUse"}}\n', b""),
        (2, b"", b"blocked in plain words\r\n"),
        (1, b"no newline at the end, and a byte no codec reads: \xff", b"Traceback (most recent call last):\n"),
    ], ids=["a decision on stdout", "a plain block", "a crash"])
    def test_the_childs_streams_and_code_go_out_byte_for_byte(self, tmp_path, code, out, err):
        site = _site(tmp_path, _STAND_IN_CHILD_SITE)
        answer = _run_the_hook(tmp_path, _payload(), site=site, extra_env={
            "RELAY_OUT": out.hex(), "RELAY_ERR": err.hex(), "RELAY_CODE": str(code)})
        assert answer == (code, out, err), answer

    @pytest.mark.skipif(os.name == "nt", reason="a POSIX signal ends the stand-in child")
    def test_a_child_ended_by_a_signal_answers_as_a_crashed_hook_did(self, tmp_path):
        # Exit 1, which the protocol reads as a non-blocking error: a hook
        # process killed by a signal let the call through before the bound
        # too. Failing closed instead is DEC-41, the operator's call.
        site = _site(tmp_path, _STAND_IN_CHILD_SITE)
        answer = _run_the_hook(tmp_path, _payload(), site=site, extra_env={
            "RELAY_OUT": b"partial".hex(), "RELAY_ERR": "".encode().hex(), "RELAY_CODE": "signal"})
        assert answer == (1, b"partial", b""), answer

    @pytest.mark.parametrize("case", ["an allow", "a zone deny", "a start refusal"])
    def test_the_hook_answers_as_its_judging_child_does(self, tmp_path, case):
        site = _site(tmp_path, _NO_HELPERS_IN_THE_CHILD_SITE) if case == "a start refusal" else None
        answers = []
        # Each run in a fresh root of its own, so state one run writes (a
        # said-once flag) cannot change the other's answer; the roots' names
        # are the one difference, and they are read as one name.
        for name, judge in (("run-a", False), ("run-b", True)):
            root = tmp_path / name
            root.mkdir()
            payload = (_payload("Bash", {"command": "git status"}) if case == "an allow" else
                       _payload("Write", {"file_path": str(root / ".claude" / "settings.json"), "content": "x"}))
            code, out, err = _run_the_hook(root, payload, judge=judge, site=site)
            answers.append((code, out.replace(name.encode(), b"run-x"), err.replace(name.encode(), b"run-x")))
        hook, child = answers
        assert hook == child, (hook, child)
        code, out, _err = hook
        assert code == 0, hook
        decisions = [d["hookSpecificOutput"] for d in _decisions(out.decode("utf-8"))]
        denies = [d for d in decisions if d.get("permissionDecision") == "deny"]
        if case == "an allow":
            assert not denies, decisions
        else:
            assert len(denies) == 1, decisions
        if case == "a start refusal":
            assert "cannot start" in denies[0]["permissionDecisionReason"], denies

    def test_where_no_child_can_start_the_hook_judges_itself_and_says_so(self, tmp_path):
        site = _site(tmp_path, _NO_JUDGING_CHILD_SITE)
        payload = _payload("Write", {"file_path": str(tmp_path / ".claude" / "settings.json"), "content": "x"})
        code, out, err = _run_the_hook(tmp_path, payload, site=site)
        assert code == 0, (code, err)
        decisions = _decisions(out.decode("utf-8"))
        assert len(decisions) == 1, out
        assert decisions[0]["hookSpecificOutput"]["permissionDecision"] == "deny", decisions
        assert b"judging child could not start (OSError)" in err, err
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_failed_open_time_budget"]
        assert [r["details"].get("fault") for r in records] == ["OSError"], records

    @pytest.mark.skipif(os.name == "nt", reason="no RLIMIT_CPU on Windows: the job object is the backstop there")
    def test_the_judging_child_caps_its_own_cpu_time(self, tmp_path):
        import resource

        site = _site(tmp_path, _READ_THE_CPU_CAP_SITE)
        cap_file = tmp_path / "cpu.cap"
        code, out, err = _run_the_hook(tmp_path, _payload("Bash", {"command": "echo READ-THE-CPU-CAP"}),
                                       site=site, extra_env={"CPU_CAP_FILE": str(cap_file)})
        assert code == 0, (code, err)
        assert cap_file.is_file(), ("the seam never fired: no process parsed the payload", err)
        soft, hard = (int(n) for n in cap_file.read_text(encoding="utf-8").split())
        _ours, our_hard = resource.getrlimit(resource.RLIMIT_CPU)
        cap = write_guard._CHILD_CPU_SECONDS
        assert hard == our_hard, (hard, our_hard)
        assert soft == (cap if our_hard == resource.RLIM_INFINITY else min(cap, our_hard)), (soft, hard)


def _modules_the_guard_reaches() -> list[Path]:
    """The ``tools/cc`` and ``tools/cc/hooks`` modules loaded once write_guard
    has imported and judged a call of each tool family -- derived in a fresh
    process, never listed by hand."""
    probe = textwrap.dedent("""
        import io, os, shutil, sys, tempfile
        sys.path.insert(0, sys.argv[1])
        root = tempfile.mkdtemp()
        os.environ["CLAUDE_PROJECT_DIR"] = root
        os.environ["ESPALIER_AUDIT_DIR"] = root
        import write_guard
        out = sys.stdout
        for tool, ti in [("Bash", {"command": "git status"}), ("PowerShell", {"command": "Get-ChildItem"}),
                         ("Write", {"file_path": "src/a.py", "content": "x"}),
                         ("mcp__fs__write_file", {"path": "src/a.py", "content": "x"})]:
            sys.stdout = io.StringIO()
            write_guard._run_main({"tool_name": tool, "tool_input": ti, "cwd": root})
        sys.stdout = out
        hooks = os.path.normcase(os.path.abspath(sys.argv[1]))
        dirs = {hooks, os.path.dirname(hooks)}
        for m in list(sys.modules.values()):
            f = getattr(m, "__file__", None)
            if f and os.path.normcase(os.path.dirname(os.path.abspath(f))) in dirs:
                print(os.path.relpath(os.path.abspath(f), os.path.dirname(hooks)))
        shutil.rmtree(root, ignore_errors=True)
    """)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER") or k == "ESPALIER_AUDIT_DIR"}
    result = subprocess.run([sys.executable, "-c", probe, str(HOOKS_DIR)], capture_output=True,
                            text=True, encoding="utf-8", timeout=45, env=env)
    assert result.returncode == 0, result.stderr
    return sorted(HOOKS_DIR.parent / rel for rel in set(result.stdout.split()))


def _append_mode(call: ast.Call) -> str | None:
    """The mode of an append-mode ``open`` (``a`` first, no ``+``: an ``a+``
    open is a lock handle nothing is written to), else None. Builtin and
    ``io``/``codecs`` opens take the mode second, ``Path.open`` first;
    ``os.open`` takes flags and is not a text append."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "open":
        positional = call.args[1:2]
    elif isinstance(func, ast.Attribute) and func.attr == "open":
        owner = func.value.id if isinstance(func.value, ast.Name) else ""
        if owner == "os":
            return None
        positional = call.args[1:2] if owner in {"io", "codecs"} else call.args[0:1]
    else:
        return None
    candidates = [*positional, *(k.value for k in call.keywords if k.arg == "mode")]
    for c in candidates:
        if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value[:1] == "a" and "+" not in c.value:
            return c.value
    return None


def _append_writes_outside_the_lock(path: Path) -> list[str]:
    """Every write to an append-mode handle in ``path`` that no enclosing
    ``with`` holds ``STATE_WRITE_LOCK`` around -- the lock may enclose the
    open or sit inside its body around the write (``_integrity.append_audit``
    takes it inside the file lock). An append handle opened outside a ``with``
    is named too: its writes cannot be scoped."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _locked(node: ast.AST) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.With) and any(
                ast.unparse(item.context_expr).endswith("STATE_WRITE_LOCK") for item in node.items
            ):
                return True
        return False

    out: list[str] = []
    scoped: set[ast.Call] = set()
    for with_node in ast.walk(tree):
        if not isinstance(with_node, ast.With):
            continue
        for item in with_node.items:
            call = item.context_expr
            if not (isinstance(call, ast.Call) and _append_mode(call)):
                continue
            scoped.add(call)
            handle = item.optional_vars.id if isinstance(item.optional_vars, ast.Name) else None
            for stmt in with_node.body:
                for sub in ast.walk(stmt):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr in {"write", "writelines"}
                            and isinstance(sub.func.value, ast.Name) and sub.func.value.id == handle
                            and not _locked(sub)):
                        out.append(f"{path.name}:{sub.lineno} {handle}.{sub.func.attr}(...)")
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and call not in scoped and _append_mode(call):
            out.append(f"{path.name}:{call.lineno} an append handle opened outside a with")
        # The order the refusal relies on: a file lock taken while the
        # state-write lock is held could deadlock the refusal (it takes the
        # audit file's lock, then the state-write lock) until the timeout.
        if (isinstance(call, ast.Call) and _locked(call) and (
                (isinstance(call.func, ast.Name) and call.func.id == "lock_file")
                or (isinstance(call.func, ast.Attribute) and call.func.attr == "lock_file"))):
            out.append(f"{path.name}:{call.lineno} lock_file(...) inside the state-write lock")
    return out


class TestNoTornStateOnARefusal:
    def test_every_append_the_guard_reaches_writes_under_the_state_lock(self):
        reached = _modules_the_guard_reaches()
        names = {p.name for p in reached}
        # The floor: the guard and the three modules whose appends it reaches.
        assert {"write_guard.py", "_hook_utils.py", "_integrity.py", "_speedbump.py"} <= names, names
        appends = [p.name for p in reached if any(
            isinstance(c, ast.Call) and _append_mode(c) for c in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        )]
        assert sorted(appends) == ["_hook_utils.py", "_integrity.py", "_speedbump.py"], appends
        offenders = [o for p in reached for o in _append_writes_outside_the_lock(p)]
        assert offenders == [], (
            "an append the guard reaches writes outside _hook_utils.STATE_WRITE_LOCK, so a budget "
            f"refusal could end the process inside it and leave a torn line: {offenders}"
        )

    def test_the_census_names_an_unlocked_append(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text(
            "def f(p, line):\n"
            "    with p.open('a', encoding='utf-8') as fh:\n"
            "        fh.write(line)\n"
            "def g(p, line):\n"
            "    with STATE_WRITE_LOCK, p.open('a') as fh:\n"
            "        fh.write(line)\n"
            "def h(p, line):\n"
            "    with open(p, 'a') as fh:\n"
            "        with _hook_utils.STATE_WRITE_LOCK:\n"
            "            fh.write(line)\n"
            "def i(p):\n"
            "    return open(p, 'a+'), open('app.log'), os.open(p, 1)\n"
            "def j(p):\n"
            "    fh = open(p, 'ab')\n"
            "def k(p, line):\n"
            "    with STATE_WRITE_LOCK, open(p, 'a') as fh:\n"
            "        _hook_utils.lock_file(fh)\n"
            "        fh.write(line)\n",
            encoding="utf-8",
        )
        assert sorted(_append_writes_outside_the_lock(bad)) == sorted([
            "bad.py:3 fh.write(...)", "bad.py:14 an append handle opened outside a with",
            "bad.py:17 lock_file(...) inside the state-write lock",
        ])

    def test_an_audit_append_waits_for_the_state_lock(self, guard_root):
        import _integrity

        landed = threading.Event()
        writer = threading.Thread(target=lambda: (
            _integrity.append_audit(guard_root, {"event_type": "test_record", "details": {}}, quiet=True),
            landed.set(),
        ))
        with _hook_utils.STATE_WRITE_LOCK:
            writer.start()
            # Held here, the lock keeps the line from being written at all.
            assert not landed.wait(0.3)
            assert "test_record" not in _types()
        writer.join(_EVENT_CEILING_S)
        assert landed.is_set()
        assert _types() == ["test_record"]


#: What a writer killed mid-append leaves at a log's end: a record cut off,
#: with no newline after it.
_TORN = '{"event_type": "cut_off_mid_rec'

#: The hook-side appends that need no heal, each with why: what a torn line
#: costs there is nothing a later record loses.
_APPENDS_THAT_NEED_NO_HEAL = {
    "post_compact.py::_capture_compact_summary": "each append opens with a blank line of its own",
    "stop_gate.py::_mark_spawn_failure_reported": (
        "read by whitespace split: a digest a tear loses is told again, the safe direction"),
}


def _after_a_tear(log: Path, append) -> list[str]:
    """The log's lines once ``append`` ran on a log ending in a torn record."""
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(_TORN.encode("utf-8"))
    append()
    return log.read_text(encoding="utf-8").splitlines()


def _appends_that_skip_the_heal(path: Path) -> list[str]:
    """``file::function`` for each function in ``path`` that opens a file for
    append and never names ``own_line`` (the helper, or a module's guarded
    alias of it), unless declared in :data:`_APPENDS_THAT_NEED_NO_HEAL`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    funcs = [f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and _append_mode(call)):
            continue
        owner = min((f for f in funcs if f.lineno <= call.lineno <= (f.end_lineno or f.lineno)),
                    key=lambda f: (f.end_lineno or f.lineno) - f.lineno, default=None)
        where = f"{path.name}::{owner.name if owner else '<module>'}"
        heals = owner is not None and any(
            (isinstance(n, ast.Name) and n.id.lstrip("_").lower() == "own_line")
            or (isinstance(n, ast.Attribute) and n.attr.lstrip("_").lower() == "own_line")
            for n in ast.walk(owner))
        if not heals and where not in _APPENDS_THAT_NEED_NO_HEAL:
            out.append(where)
    return out


class TestATornLineLosesOnlyItself:
    """DEF-1160's lock keeps the in-process refusal from cutting an append off
    mid-line, and no lock can stop a kill from outside: write_guard's parent
    ends its judging child at the deadline wherever it is (DEF-3048), and
    Claude Code ends any hook at its wired timeout. A record cut off with no
    newline then swallowed the next record appended after it -- the parent's
    own time-budget record first among them. Each line-record append now starts
    a line of its own after a torn one, so the torn record is the only loss
    (the readers skip a line that does not parse)."""

    def test_an_audit_record_after_a_torn_line_reads_whole(self, guard_root):
        import _integrity

        lines = _after_a_tear(_integrity.audit_path(guard_root), lambda: _integrity.append_audit(
            guard_root, {"event_type": "after_the_tear", "details": {}}, quiet=True))
        assert lines[0] == _TORN, lines
        assert json.loads(lines[-1])["event_type"] == "after_the_tear", lines
        assert [json.loads(ln)["event_type"] for ln in _integrity.tail_audit(guard_root)] == ["after_the_tear"]

    def test_a_telemetry_record_after_a_torn_line_reads_whole(self, tmp_path):
        lines = _after_a_tear(tmp_path / "state" / "t.jsonl", lambda: _hook_utils._append_jsonl(
            tmp_path / "state", "t.jsonl", {"event": "after_the_tear"}))
        assert lines[0] == _TORN, lines
        assert json.loads(lines[-1])["event"] == "after_the_tear", lines

    def test_a_born_weak_observation_after_a_torn_line_reads_whole(self, tmp_path):
        import _born_weak

        lines = _after_a_tear(tmp_path / _hook_utils.STATE_DIR / _born_weak._BW_LOG_NAME,
                              lambda: _born_weak.bw_log_observation(tmp_path, {"event": "after_the_tear"}))
        assert lines[0] == _TORN, lines
        assert json.loads(lines[-1])["event"] == "after_the_tear", lines

    def test_a_discard_snapshot_after_a_torn_line_reads_whole(self, tmp_path):
        import _speedbump

        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, timeout=30)

        git("init", "-q", ".")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "file.py").write_text("committed\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "init")
        (tmp_path / "file.py").write_text("uncommitted\n", encoding="utf-8")
        taken: list[str | None] = []
        lines = _after_a_tear(tmp_path / _speedbump.SNAPSHOT_LOG, lambda: taken.append(
            _speedbump.snapshot_discard("Bash", {"command": "git checkout file.py"}, tmp_path)))
        assert taken[0], "no snapshot taken for a dirty tree, so the case did not run"
        assert lines[0] == _TORN, lines
        # The deny text sends the operator to the log's last line for the sha.
        assert lines[-1].split("\t")[1] == taken[0], lines

    def test_every_hook_side_append_heals_a_torn_line(self):
        skipped = [w for p in sorted(HOOKS_DIR.glob("*.py")) for w in _appends_that_skip_the_heal(p)]
        assert not skipped, (
            f"{skipped} open a file for append without own_line: a record a killed writer cut off "
            "swallows the next one. Write the line through own_line (under the lock the append "
            "already holds), or declare why a torn line costs nothing there in _APPENDS_THAT_NEED_NO_HEAL.")

    def test_the_census_names_an_append_that_skips_the_heal(self, tmp_path):
        planted = tmp_path / "planted.py"
        planted.write_text(textwrap.dedent("""
            def heals(path, line):
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(own_line(path, line))

            def skips(path, line):
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line)
        """), encoding="utf-8")
        assert _appends_that_skip_the_heal(planted) == ["planted.py::skips"]

    def test_every_declared_exemption_still_names_an_append(self):
        live = {f"{p.name}::{f.name}" for p in HOOKS_DIR.glob("*.py")
                for f in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                if isinstance(f, ast.FunctionDef)
                and any(isinstance(c, ast.Call) and _append_mode(c) for c in ast.walk(f))}
        assert set(_APPENDS_THAT_NEED_NO_HEAL) <= live, set(_APPENDS_THAT_NEED_NO_HEAL) - live


class TestASlowGitCostsItsSnapshotNotTheCall:
    """The judgment's git spawns (the discard snapshot, the dirty-tree checks)
    time out inside the budget: a git that runs slow on a large repo or a cold
    cache costs its snapshot, said once, and the call is still judged -- never
    refused with a split it cannot follow (the failure-mode review's finding)."""

    def test_the_spawn_timeout_is_the_budget_left_less_the_reserve(self, monkeypatch):
        monkeypatch.setattr(_hook_utils, "_judgment_deadline", None)
        assert _hook_utils.spawn_timeout(15) == 15
        now = 1000.0
        monkeypatch.setattr(_hook_utils.time, "monotonic", lambda: now)
        _hook_utils.set_judgment_deadline(now + 3.0)
        try:
            assert _hook_utils.spawn_timeout(15) == pytest.approx(3.0 - _hook_utils.SPAWN_RESERVE_S)
            assert _hook_utils.spawn_timeout(1) == 1
            _hook_utils.set_judgment_deadline(now + 0.1)
            assert _hook_utils.spawn_timeout(15) == 0.05  # the floor: past the reserve, a token wait
        finally:
            _hook_utils.set_judgment_deadline(None)

    def test_a_same_tick_read_lands_a_rounding_above_the_exact_bound(self, monkeypatch):
        """The control for DEF-4000: with the clock frozen on one tick for both
        the arming and the ask (what a coarse monotonic clock does on Windows),
        the timeout the hook computes is the budget less the reserve to within
        float rounding -- and NOT always at or below it, which is why the
        assertion below carries ``_SAME_TICK_SLACK_S``. The clock value is one
        the simulation found; the premise is asserted first, so a change in the
        hook's arithmetic reports itself here and not as a Windows-only red."""
        clock, budget = 262142.61777491038, 10.0
        exact = budget - _hook_utils.SPAWN_RESERVE_S
        assert (clock + budget) - clock - _hook_utils.SPAWN_RESERVE_S > exact, \
            "the premise: this clock value rounds above the exact bound"
        monkeypatch.setattr(_hook_utils.time, "monotonic", lambda: clock)
        _hook_utils.set_judgment_deadline(clock + budget)
        try:
            asked = _hook_utils.spawn_timeout(15)
        finally:
            _hook_utils.set_judgment_deadline(None)
        assert asked > exact  # the exact bound, the assertion's old shape, reds here
        assert asked <= exact + _SAME_TICK_SLACK_S
        assert asked == pytest.approx(exact)

    def test_a_git_that_times_out_leaves_the_call_judged(self, monkeypatch, guard_root):
        import _speedbump

        asked: list[float] = []

        def _slow_git(argv, **kwargs):
            # A git that would run past its timeout: it is asked for no more
            # than the budget leaves, then gives up the way a real one does.
            asked.append(kwargs["timeout"])
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        budget = 10.0
        monkeypatch.setattr(write_guard, "JUDGMENT_BUDGET_S", budget)
        monkeypatch.setattr(_speedbump.subprocess, "run", _slow_git)
        monkeypatch.setattr(_hook_utils, "_SAID_THIS_PROCESS", set())
        payload = _payload("Bash", {"command": "git checkout -- src/app.py"})
        rc, streams = _drive(monkeypatch, payload)
        # Judged: the discard reminder's one-shot deny on stdout, exit 0 -- not
        # the refusal, and the snapshot that could not be taken is said once.
        assert rc == 0, streams.err.getvalue()
        decision = json.loads(streams.out.getvalue())["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "Speed-bump" in decision["permissionDecisionReason"]
        assert "pretooluse_blocked_time_budget" not in _types()
        assert "pretooluse_failed_open_discard_snapshot" in _types()
        # Every git the judgment asked was cut to the budget left, under the
        # snapshot's own 15 s.
        assert asked, "the discard snapshot asked git nothing"
        assert max(asked) <= budget - _hook_utils.SPAWN_RESERVE_S + _SAME_TICK_SLACK_S
        assert _hook_utils._judgment_deadline is None, "the deadline outlived the verdict"
