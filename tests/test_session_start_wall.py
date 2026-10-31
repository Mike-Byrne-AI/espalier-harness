"""DEF-3015: the SessionStart hook gives a banner inside the host's timeout.

Claude Code cancels a SessionStart hook past its 15 s ``timeout`` and keeps
none of its output, so a start that ran long lost the whole banner (13 of 95
runs on the Windows box, 2026-10-16 to 2026-10-29; one more on each Windows
seat on 2026-10-31). The network reads were budgeted; the local phases around
them were not (a fresh tree's zone baseline took 2.6 s against 0.07 s warm,
and one start ran 36 s with its phase unread). The hook now cuts itself at a
wall of its own and prints a short banner naming the phase in flight. These
rows pin that cut, because a start the host cancels leaves the session no
banner at all, and the root rule then reads loaded hooks as unloaded.

The subprocess rows run the hook module's own ``__main__`` block, the way the
wiring starts it, with one phase made to stall; the wall is shrunk so a row
costs seconds. In-process callers (this suite) never arm the wall: the cut
ends the process.
"""
from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from tests._interpreter_hosts import HOOK_PYTHON

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

# A stalled phase sleeps this long; the child is given less than this to
# answer, so a start with no wall of its own is a timeout here, never a pass.
_STALL_SECONDS = 40.0
_CHILD_TIMEOUT_SECONDS = 30.0
_TEST_WALL_SECONDS = 3.0

_DRIVER = r'''
import ast, json, os, sys, time
from pathlib import Path
repo, target, wall, stall = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
cc = repo / "tools" / "cc"
sys.path[:0] = [str(cc / "hooks"), str(cc)]
for key in [k for k in os.environ if k.startswith("ESPALIER")]:
    os.environ.pop(key)
os.environ["CLAUDE_PROJECT_DIR"] = str(repo)
os.environ["ESPALIER_AUDIT_DIR"] = str(repo / ".audit")
os.environ["ESPALIER_SESSION_CATCH_UP"] = "0"
import session_start as ss
import _zone_watch
ss._WALL_SECONDS = wall
def stall_for(*args, **kwargs):
    time.sleep(stall)
    return ""
# The network reads answer at once, so the phase a row stalls is reached the
# same way on an idle box and a loaded CI cell (the code review: 5 of 10 loaded
# runs reached the banner build past a 2 s wall with the reads live).
ss._open_prs_line = lambda *args, **kwargs: "OPEN-LINE-READ-BEFORE-THE-CUT"
ss._read_open_prs = ss._read_merged_prs = lambda *args, **kwargs: ""
ss._read_merge_rules = lambda *args, **kwargs: ("", -1, "")
ss._mail_line = ss._engine_line = lambda *args, **kwargs: ""
owner, _, name = target.rpartition(".")
if name:
    setattr(_zone_watch if owner == "_zone_watch" else ss, name, stall_for)
src = Path(ss.__file__).read_text(encoding="utf-8")
block = next(n for n in ast.parse(src).body if isinstance(n, ast.If)
             and getattr(getattr(n.test, "left", None), "id", "") == "__name__")
exec(compile(ast.Module(body=block.body, type_ignores=[]), ss.__file__, "exec"), vars(ss))
'''


def _tree(tmp_path: Path) -> Path:
    from tests._live_tree import copy_checkout

    repo = tmp_path / "repo"
    copy_checkout(REPO_ROOT / "tools" / "cc", repo / "tools" / "cc")
    (repo / "memory" / "session-log.d").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
    return repo


def _start(tmp_path: Path, target: str, wall: float = _TEST_WALL_SECONDS) -> subprocess.CompletedProcess:
    repo = _tree(tmp_path)
    driver = tmp_path / "start.py"
    driver.write_bytes(_DRIVER.encode("utf-8"))
    payload = json.dumps({"source": "clear", "session_id": "t-def3015", "hook_event_name": "SessionStart"})
    try:
        return subprocess.run(
            [HOOK_PYTHON, str(driver), str(repo), target, str(wall), str(_STALL_SECONDS)],
            input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_CHILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        pytest.fail(f"no banner inside {_CHILD_TIMEOUT_SECONDS:.0f} s with {target} stalled: the start ran on "
                    f"through the stall, which the host would cancel at 15 s and drop whole; stdout {out[-500:]!r}")


def _banners(out: str) -> list[str]:
    return [json.loads(ln)["hookSpecificOutput"]["additionalContext"]
            for ln in out.splitlines() if ln.startswith('{"hookSpecificOutput"')]


class TestAStalledPhaseIsCutAtTheWall:
    """Must-deny: a phase that stalls past the wall ends in one short banner
    naming it, never in silence."""

    @pytest.mark.parametrize(("target", "phase"), [
        ("_sync_checkout", "checkout catch-up"),
        ("_report_integrity_state", "integrity check"),
        ("_zone_watch.take_baseline", "zone baseline"),
        ("_build_context", "banner build"),
    ])
    def test_the_banner_arrives_short_and_names_the_phase_in_flight(self, tmp_path, target, phase):
        r = _start(tmp_path, target)
        assert r.returncode == 0, r.stderr[-2000:]
        banners = _banners(r.stdout)
        assert len(banners) == 1, r.stdout[-2000:]
        head = banners[0].splitlines()[0]
        assert "SessionStart (short" in head and f"in the {phase}" in head, banners[0][:800]
        assert "the hooks are loaded" in banners[0], banners[0][:800]
        assert f"the checks from the {phase} on did not run" in banners[0], banners[0][:800]

    def test_a_cut_in_the_catch_up_says_a_move_may_still_run(self, tmp_path):
        """The catch-up's git move is never killed, so a session cut there is
        told to read the tree before it edits."""
        r = _start(tmp_path, "_sync_checkout")
        banners = _banners(r.stdout)
        assert len(banners) == 1 and "run `git status` before editing" in banners[0], r.stdout[-2000:]

    def test_the_cut_is_at_the_wall_by_the_banners_own_clock(self, tmp_path):
        r = _start(tmp_path, "_report_integrity_state")
        banners = _banners(r.stdout)
        assert len(banners) == 1, r.stdout[-2000:]
        cut = banners[0].split("cut at ", 1)[1].split(" s", 1)[0]
        assert _TEST_WALL_SECONDS <= float(cut) < _TEST_WALL_SECONDS + 1.0, banners[0][:400]

    def test_a_line_read_before_the_cut_is_kept(self, tmp_path):
        r = _start(tmp_path, "_build_context")
        banners = _banners(r.stdout)
        assert len(banners) == 1, r.stdout[-2000:]
        assert "OPEN-LINE-READ-BEFORE-THE-CUT" in banners[0], banners[0][:1200]

    def test_the_cut_leaves_its_record_before_the_process_ends(self, tmp_path):
        """A cut start is a hook_success to the host, so the transcript no
        longer counts it: the audit record is the count."""
        r = _start(tmp_path, "_report_integrity_state")
        assert len(_banners(r.stdout)) == 1, r.stdout[-2000:]
        records = [json.loads(ln) for log in (tmp_path / "repo" / ".audit").glob("*.log")
                   for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        cuts = [rec for rec in records if rec.get("event_type") == "sessionstart_failed_open_wall_cut"]
        assert len(cuts) == 1, [rec.get("event_type") for rec in records]


class TestAStartInsideTheWallIsUntouched:
    """Must-allow: a start that finishes inside the wall prints its full
    banner once, and the suite's in-process starts never arm the wall."""

    def test_a_start_with_no_stall_prints_the_full_banner_once(self, tmp_path):
        r = _start(tmp_path, "", wall=13.0)
        assert r.returncode == 0, r.stderr[-2000:]
        banners = _banners(r.stdout)
        assert len(banners) == 1, r.stdout[-2000:]
        assert "(short" not in banners[0].splitlines()[0], banners[0][:400]
        assert "OPEN-LINE-READ-BEFORE-THE-CUT" in banners[0]

    def test_an_in_process_start_arms_no_wall(self, tmp_path, monkeypatch):
        repo = _tree(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.syspath_prepend(str(HOOKS_DIR.parent))
        monkeypatch.syspath_prepend(str(HOOKS_DIR))
        import session_start as ss

        def armed(*args, **kwargs):
            pytest.fail("an in-process start armed the wall, whose cut would end this process")

        monkeypatch.setattr(ss, "_arm_wall", armed)
        real = ss._report_integrity_state

        def slow(root):
            import time
            time.sleep(0.3)
            return real(root)

        monkeypatch.setattr(ss, "_report_integrity_state", slow)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"source": "resume", "session_id": "t-def3015-in"})))
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert ss.main() == 0
        banners = _banners(buf.getvalue())
        assert len(banners) == 1 and "(short" not in banners[0].splitlines()[0], buf.getvalue()[:800]


class TestTheBudgetsFitTheWall:
    """The network reads end with room for the work after them, and the wall
    leaves the interpreter's start and the host's kill inside 15 s."""

    def _load(self):
        sys.path[:0] = [str(HOOKS_DIR), str(HOOKS_DIR.parent)]
        import session_start as ss
        return ss

    def test_the_wall_is_under_the_host_timeout_with_headroom(self):
        ss = self._load()
        assert ss._WALL_SECONDS <= 13.0

    def test_the_tail_reserve_covers_the_work_after_the_reads(self):
        """The engine probe's cap and the measured cold banner build fit in the
        tail, so a start whose reads ran to their deadline still finishes
        before the wall (and before the chain advance it would cut)."""
        ss = self._load()
        assert ss._TAIL_RESERVE_SECONDS >= ss._ENGINE_CAP_SECONDS + ss._BANNER_BUILD_SECONDS

    def test_the_cut_ends_inside_the_timeout_init_wires(self):
        """The wall plus the cut's two bounded waits, plus half a second for the
        interpreter's start and the host's lag, fit under the timeout `espalier
        init` writes for this hook."""
        ss = self._load()
        from espalier.harness_config import CANONICAL_HOOK_WIRING

        timeout = CANONICAL_HOOK_WIRING["session_start.py"]["timeout"]
        assert ss._WALL_SECONDS + 2 * ss._CUT_RECORD_SECONDS + 0.5 <= timeout

    def test_a_fresh_start_is_killed_before_the_parents_wall(self):
        """A hand-off child arms no wall of its own: the parent's kill, which
        must land before the parent's wall, is its bound."""
        ss = self._load()
        kill = (ss._HOOK_BUDGET_SECONDS - ss._HANDOFF_RESERVE_SECONDS) + ss._ENGINE_CAP_SECONDS + ss._HANDOFF_TAIL_SECONDS
        assert kill < ss._WALL_SECONDS

    def test_the_exit_takes_the_state_write_lock_first(self):
        """The cut's exit waits, bounded, for another thread's append to
        finish (write_guard's exit takes the same lock)."""
        import inspect

        src = inspect.getsource(self._load()._cut)
        assert "STATE_WRITE_LOCK" in src and src.index(".acquire(") < src.index("exit_(0)"), src

    def test_the_cut_record_is_in_the_family_status_log_counts(self):
        """`/status --log` counts the fail-open family by predicate and shows
        no type outside its families (DEF-1152's shape), so a cut record named
        outside it would never be read."""
        ss = self._load()
        import _integrity

        assert _integrity.is_fail_open_event(ss._CUT_EVENT), ss._CUT_EVENT

    def test_the_script_run_passes_the_load_clock(self):
        """Structural: the ``__main__`` block hands ``main`` the clock read at
        module load, so the wall counts the imports. Dies to: ``main()`` with no
        argument there, which no subprocess row above would catch if the wall
        were also armed in-process."""
        tree = ast.parse((HOOKS_DIR / "session_start.py").read_text(encoding="utf-8"))
        block = next(n for n in tree.body if isinstance(n, ast.If)
                     and getattr(getattr(n.test, "left", None), "id", "") == "__name__")
        calls = [n for n in ast.walk(block) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "main"]
        assert calls and [getattr(a, "id", "") for a in calls[0].args] == ["_LOAD_T0"], ast.dump(block)


class TestTheWallMechanism:
    """The two claims the subprocess rows cannot isolate: the wall counts from
    the clock it is given, and one banner leaves whichever thread gets there
    first (mutants of each survived the subprocess rows, the code review)."""

    def _load(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.syspath_prepend(str(HOOKS_DIR.parent))
        monkeypatch.syspath_prepend(str(HOOKS_DIR))
        import session_start as ss

        ss._reset_wall_state()
        return ss

    def test_the_wall_counts_from_the_clock_it_is_given(self, monkeypatch, tmp_path):
        import threading
        import time

        ss = self._load(monkeypatch, tmp_path)
        exited = threading.Event()
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                ss._arm_wall(time.monotonic() - 20, exit_=lambda code: exited.set())
                assert exited.wait(5), "a wall whose clock is 20 s old did not fire at once"
        finally:
            ss._disarm_wall()
            ss._reset_wall_state()
        assert len(_banners(buf.getvalue())) == 1, buf.getvalue()[:800]

    def test_one_banner_leaves_however_the_two_threads_meet(self, monkeypatch, tmp_path):
        import time

        ss = self._load(monkeypatch, tmp_path)
        exits: list[int] = []
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                assert ss._emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "a"}})
                assert not ss._emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "b"}})
                # A cut that loses the race takes nothing the main banner owns.
                ss._hook_utils.take_advisories()
                ss._hook_utils.advise("[INFO] kept for the main banner", echo=False)
                ss._cut(time.monotonic(), exits.append)
                kept = ss._hook_utils.take_advisories()
        finally:
            ss._reset_wall_state()
        assert _banners(buf.getvalue()) == ["a"] and exits == [], (buf.getvalue(), exits)
        assert kept == ["[INFO] kept for the main banner"], kept


class TestEveryBlockHasAPhase:
    """Derived, not listed: the cut's banner carries every line the full banner
    renders, and every block of ``_run_main`` names its phase, so a block added
    later without one is red here, not billed to the phase before it."""

    _TREE = ast.parse((HOOKS_DIR / "session_start.py").read_text(encoding="utf-8"))
    # The pull-request block is one phase with three handlers.
    _ONE_PHASE = {"open pull-request scan", "merged pull-request scan", "post-merge verdict module probe"}

    def _func(self, name: str) -> ast.FunctionDef:
        return next(n for n in self._TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)

    def _phase_calls(self) -> list[ast.Call]:
        return [n for n in ast.walk(self._func("_run_main")) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_phase"]

    def test_the_cut_keeps_every_line_the_full_banner_renders(self):
        build = next(n for n in ast.walk(self._func("_build_context")) if isinstance(n, ast.Call)
                     and getattr(n.func, "id", "") == "_fit_run_lines")
        rendered = {t.elts[0].value for t in build.args[0].elts}
        kept: set[str] = set()
        for call in self._phase_calls():
            for kw in call.keywords:
                if kw.arg is not None:
                    kept.add(kw.arg)
                elif isinstance(kw.value, ast.Dict):
                    kept |= {k.value for k in kw.value.keys if isinstance(k, ast.Constant)}
        assert kept == rendered, (sorted(rendered - kept), sorted(kept - rendered))

    def test_every_handler_in_run_main_is_inside_a_named_phase(self):
        phases = {c.args[0].value for c in self._phase_calls() if c.args and isinstance(c.args[0], ast.Constant)}
        labels = {n.args[0].value.removeprefix("session_start: ").removesuffix(" failed")
                  for n in ast.walk(self._func("_run_main")) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "_late_load_failed"
                  and n.args and isinstance(n.args[0], ast.Constant)}
        assert labels and not labels - phases - self._ONE_PHASE, sorted(labels - phases - self._ONE_PHASE)
