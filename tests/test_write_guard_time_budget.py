"""write_guard's time budget: a judgment that runs long is refused, not let through.

Claude Code cancels a PreToolUse command hook at its wired timeout, and a
cancelled command hook does not block (``docs/external/cc-hook-protocol.md``,
"Timeouts"). A long generated delete list made the guard's judgment run past
it, so the whole guard -- the wall, the nudge, the zone check, the kill-switch
gate -- was skipped for that call. ``write_guard.main`` now judges in a worker
thread under ``JUDGMENT_BUDGET_S`` and refuses on stderr with exit 2 when the
budget runs out first.

Every row here injects a slow judgment (``_run_main`` replaced by a stub that
waits on an event) under a tiny budget, so nothing depends on how fast the
runner is and no command is ever executed. The one row with a real long list
is the ledger probe, driven at the lane's end, not here.
"""
# slow-exempt: two short children -- one hook-shaped process with a stuck judgment, one fresh-process module census -- about a second each
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
        self.entered.set()
        if self.holds_state_lock:
            with _hook_utils.STATE_WRITE_LOCK:
                self.release_state_lock.wait(_EVENT_CEILING_S)
        self.release.wait(_EVENT_CEILING_S)
        if self.decides:
            print(json.dumps(_DENY))
            print("[write_guard] a late line from the judgment", file=sys.stderr)
            return int(_hook_utils.DENIED)
        return 0


@pytest.fixture
def guard_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch, guard_root: Path):
    """A slow judgment under a tiny budget. Teardown releases it and joins
    every judgment thread, so no worker outlives its row."""
    judgment = _SlowJudgment()
    monkeypatch.setattr(write_guard, "_run_main", judgment)
    monkeypatch.setattr(write_guard, "JUDGMENT_BUDGET_S", _TINY_BUDGET_S)
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
        main_block = next(
            n for n in tree.body
            if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"
        )
        calls = [c for c in ast.walk(main_block) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name) and c.func.id == "main"]
        assert len(calls) == 1, ast.unparse(main_block)
        kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
        assert kw == {"started": "_HOOK_STARTED", "exit_on_budget": "True"}, kw
        # The clock reads before the first co-located helper module imports
        # (the import is most of an ordinary call's cost).
        started_at = next(n.lineno for n in tree.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "_HOOK_STARTED" for t in n.targets))
        first_helper = next(n.lineno for n in tree.body if isinstance(n, ast.Import)
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

    def test_the_crash_guard_still_denies_on_stdout(self, monkeypatch, guard_root):
        def _boom(data=None):
            raise ValueError("synthetic")

        monkeypatch.setattr(write_guard, "_run_main", _boom)
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
    def test_every_tool_is_refused_on_stderr_with_exit_2(self, monkeypatch, slow, tool, tool_input):
        rc, streams = _drive(monkeypatch, _payload(tool, tool_input))
        assert rc == 2
        assert streams.out.getvalue() == "", "a refusal opens no stdout: exit 2 is the simple-block channel"
        expected = _denial_reasons.WRITE_GUARD_TIME_BUDGET.format(budget=_TINY_BUDGET_S)
        assert streams.err.getvalue() == expected + "\n"
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
        assert rc == 2
        assert "could not finish judging" in streams.err.getvalue()
        assert "pretooluse_blocked_time_budget" in _types()

    def test_the_refusal_names_the_split_and_the_wrong_move(self):
        text = _denial_reasons.WRITE_GUARD_TIME_BUDGET.format(budget=3.5)
        assert "3.5 s" in text
        assert "Don't:" in text and "Do:" in text and "split" in text
        assert text.isascii()

    def test_a_refused_judgments_late_output_is_discarded(self, monkeypatch, slow):
        slow.decides = True
        rc, streams = _drive(monkeypatch, _payload())
        assert rc == 2
        slow.release.set()
        for t in _judgment_threads():
            t.join(_EVENT_CEILING_S)
        # The judgment printed a decision and a line once released: neither
        # reached the streams the call answered on, and the streams are back.
        assert streams.out.getvalue() == ""
        assert "late line" not in streams.err.getvalue()
        assert streams.err.getvalue().count("could not finish judging") == 1
        assert sys.stdout is streams.out and sys.stderr is streams.err

    def test_the_refusal_waits_for_a_state_write_in_flight(self, monkeypatch, slow):
        slow.holds_state_lock = True
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
        assert rc == 2
        assert "could not finish judging" in streams.err.getvalue()


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

        class _AtTheBudget(threading.Event):
            def wait(self, timeout: float | None = None) -> bool:
                if timeout is None:
                    return super().wait()
                got = super().wait(timeout)
                if judgment_wins:
                    slow.release.set()  # the judgment returns now ...
                    assert judged.wait(_EVENT_CEILING_S)  # ... and claims first
                return got

        monkeypatch.setattr(write_guard, "_Verdict", _Signalling)
        monkeypatch.setattr(write_guard, "threading", types.SimpleNamespace(
            Event=_AtTheBudget, Thread=threading.Thread, Lock=threading.Lock,
        ))
        rc, streams = _drive(monkeypatch, _payload())
        for t in _judgment_threads():
            t.join(_EVENT_CEILING_S)
        return rc, streams

    def test_a_judgment_that_claims_at_the_budget_is_the_one_verdict(self, monkeypatch, slow):
        rc, streams = self._race(monkeypatch, slow, judgment_wins=True)
        assert rc == 0
        assert [json.loads(line) for line in streams.out.getvalue().splitlines()] == [_DENY]
        assert "could not finish judging" not in streams.err.getvalue()
        assert "pretooluse_blocked_time_budget" not in _types()

    def test_a_budget_that_claims_first_is_the_one_verdict(self, monkeypatch, slow):
        rc, streams = self._race(monkeypatch, slow, judgment_wins=False)
        assert rc == 2
        assert streams.out.getvalue() == ""
        assert streams.err.getvalue().count("could not finish judging") == 1
        assert "late line" not in streams.err.getvalue()
        assert _types().count("pretooluse_blocked_time_budget") == 1


class TestTheEntryPointsEdges:
    def test_an_interrupted_wait_refuses_as_the_crash_guard_does(self, monkeypatch, slow):
        class _Interrupted(threading.Event):
            def wait(self, timeout: float | None = None) -> bool:
                if timeout is None:
                    return super().wait()
                raise KeyboardInterrupt

        monkeypatch.setattr(write_guard, "threading", types.SimpleNamespace(
            Event=_Interrupted, Thread=threading.Thread, Lock=threading.Lock,
        ))
        rc, streams = _drive(monkeypatch, _payload())
        assert rc == 2
        assert streams.out.getvalue() == ""
        assert streams.err.getvalue() == _denial_reasons.WRITE_GUARD_INTERNAL_ERROR + "\n"
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_blocked_internal_error"]
        assert [r["details"] for r in records] == [{"hook": "write_guard", "error": "KeyboardInterrupt"}]

    def test_a_thread_that_cannot_start_judges_inline_and_says_so(self, monkeypatch, guard_root):
        class _NoThread(threading.Thread):
            def start(self) -> None:
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(write_guard, "threading", types.SimpleNamespace(
            Event=threading.Event, Thread=_NoThread, Lock=threading.Lock,
        ))
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
    def test_a_refusal_ends_the_process_with_exit_2_while_the_judgment_still_runs(self, tmp_path):
        driver = tmp_path / "drive_budget.py"
        driver.write_text(_HOOK_PROCESS_DRIVER, encoding="utf-8")
        # The stuck judgment outlasts the subprocess bound, which sits well
        # inside pytest-timeout's per-test 60 s (pyproject.toml).
        stuck_s = 40.0
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
        begun = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(driver), str(HOOKS_DIR), str(stuck_s)],
            input=json.dumps(_payload()), capture_output=True, text=True, encoding="utf-8",
            timeout=stuck_s / 2, env=env,
        )
        elapsed = time.monotonic() - begun
        assert result.returncode == 2, (result.returncode, result.stderr)
        assert result.stdout == ""
        assert "could not finish judging this command within its 0.2 s time budget" in result.stderr
        assert "pretooluse_blocked_time_budget" in _types()
        # Structural, not a speed claim: the judgment was stuck for forty
        # seconds and the process ended in under half of that.
        assert elapsed < stuck_s / 2


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
    env = {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER")}
    result = subprocess.run([sys.executable, "-c", probe, str(HOOKS_DIR)], capture_output=True,
                            text=True, encoding="utf-8", timeout=120, env=env)
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
            "    fh = open(p, 'ab')\n",
            encoding="utf-8",
        )
        assert _append_writes_outside_the_lock(bad) == [
            "bad.py:3 fh.write(...)", "bad.py:14 an append handle opened outside a with",
        ]

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
