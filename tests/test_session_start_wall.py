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
# The `__main__` block that starts the hook (it calls main); the floor's block
# above the imports is another (TP-706), and this interpreter is above it.
# Read and compiled BEFORE the import, whose module load starts the hook's
# clock: a script start compiles its module before the first line runs, so
# the wall never counts this (DEF-5094).
hook = cc / "hooks" / "session_start.py"
block = next(n for n in ast.parse(hook.read_text(encoding="utf-8")).body if isinstance(n, ast.If)
             and getattr(getattr(n.test, "left", None), "id", "") == "__name__"
             and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "main" for c in ast.walk(n)))
start = compile(ast.Module(body=block.body, type_ignores=[]), str(hook), "exec")
import session_start as ss
import _zone_watch
ss._WALL_SECONDS = wall
def stall_for(*args, **kwargs):
    time.sleep(stall)
    return ""
# Every call in a phase a row passes through on the way to the one it stalls
# answers at once, so that phase is reached the same way on an idle box and a
# loaded CI cell (the code review: 5 of 10 loaded runs reached the banner build
# past a 2 s wall with the reads live; DEF-5094: the banner-build row cut at
# 3.1 s in the pull-request reads, two of its reads left live). The zone
# baseline's walk is the largest cost before the banner. TestTheDriverCounts-
# OnlyTheStartItMeasures derives the set from _run_main.
_zone_watch.take_baseline = lambda *args, **kwargs: True
ss._open_prs_line = lambda *args, **kwargs: "OPEN-LINE-READ-BEFORE-THE-CUT"
ss._read_open_prs = ss._read_merged_prs = lambda *args, **kwargs: ""
ss._post_merge_unread = ss._merged_prs_line = ss._merge_rules_line = lambda *args, **kwargs: ""
ss._read_merge_rules = lambda *args, **kwargs: ("", -1, "")
ss._mail_line = ss._engine_line = lambda *args, **kwargs: ""
owner, _, name = target.rpartition(".")
if name:
    setattr(_zone_watch if owner == "_zone_watch" else ss, name, stall_for)
exec(start, vars(ss))
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


def _cut_banner(r: subprocess.CompletedProcess, phase: str) -> str:
    """The one banner of a start stalled in ``phase``. A cut that names an
    earlier phase fails as what it is: the start passed the wall before it
    reached the stall, which is this host's load (DEF-5094), never a cut in
    the wrong place by the lane under test."""
    # The head is read as the parametrized row reads it: the cut opening's one
    # reader is tests/_cut_start.py, and a second copy here reds its one-home
    # pin (tests/test_quickstart_doctor_example.py). The head names the phase
    # the cut landed in and its seconds.
    banners = _banners(r.stdout)
    assert len(banners) == 1, r.stdout[-2000:]
    head = banners[0].splitlines()[0]
    if "(short" in head and f" in the {phase};" not in head:
        pytest.fail(f"the start passed its wall before it reached the {phase} this row stalls, which is the "
                    f"load on this host, not a cut in the wrong place: {head}")
    return banners[0]


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
        banner = _cut_banner(r, phase)
        head = banner.splitlines()[0]
        assert "SessionStart (short" in head and f"in the {phase}" in head, banner[:800]
        assert "the hooks are loaded" in banner, banner[:800]
        assert f"the checks from the {phase} on did not run" in banner, banner[:800]

    def test_a_cut_in_the_catch_up_says_a_move_may_still_run(self, tmp_path):
        """The catch-up's git move is never killed, so a session cut there is
        told to read the tree before it edits."""
        r = _start(tmp_path, "_sync_checkout")
        banner = _cut_banner(r, "checkout catch-up")
        assert "run `git status` before editing" in banner, banner[:2000]

    def test_the_cut_is_at_the_wall_by_the_banners_own_clock(self, tmp_path):
        r = _start(tmp_path, "_report_integrity_state")
        banner = _cut_banner(r, "integrity check")
        cut = banner.split("cut at ", 1)[1].split(" s", 1)[0]
        assert _TEST_WALL_SECONDS <= float(cut) < _TEST_WALL_SECONDS + 1.0, banner[:400]

    def test_a_line_read_before_the_cut_is_kept(self, tmp_path):
        r = _start(tmp_path, "_build_context")
        banner = _cut_banner(r, "banner build")
        assert "OPEN-LINE-READ-BEFORE-THE-CUT" in banner, banner[:1200]

    def test_the_cut_leaves_its_record_before_the_process_ends(self, tmp_path):
        """A cut start is a hook_success to the host, so the transcript no
        longer counts it: the audit record is the count."""
        r = _start(tmp_path, "_report_integrity_state")
        _cut_banner(r, "integrity check")
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
        blocks = [n for n in tree.body if isinstance(n, ast.If)
                  and getattr(getattr(n.test, "left", None), "id", "") == "__name__"]
        calls = [c for n in blocks for c in ast.walk(n)
                 if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "main"]
        assert len(calls) == 1, [ast.dump(n) for n in blocks]
        assert [getattr(a, "id", "") for a in calls[0].args] == ["_LOAD_T0"], ast.dump(calls[0])


class TestTheDriverCountsOnlyTheStartItMeasures:
    """DEF-5094: a stalled row is green only while the start reaches the phase
    it stalls inside the 3 s wall, so whatever the driver leaves live before
    that phase is billed to the row, and a loaded Windows cell turned it into
    a red that named no defect: the zone-baseline row cut "in the start" at
    6.1 s (Portability run 42511710052, #530's head), and the banner-build row
    cut at 3.1 s in the pull-request reads (run 42906546492, #580's head),
    where two reads the driver did not stub ran live. Measured on the Windows
    box, cold, idle (four runs each): the start reached the banner build at
    0.83 to 1.06 s with the driver as it was, the zone baseline about 0.48 s
    of it."""

    _TREE = ast.parse((HOOKS_DIR / "session_start.py").read_text(encoding="utf-8"))
    # The phases a stalled row passes through on the way to the one it stalls,
    # whose work the driver answers at once: the zone baseline (the one walk of
    # the tree, the largest cost before the banner), and the network reads.
    _ANSWERED_AT_ONCE = ("zone baseline", "mail scan", "pull-request reads", "merge-rules read", "engine probe")
    # A phase's failure path, never reached on the driver's start.
    _NOT_WORK = {"_phase", "_late_load_failed"}

    @staticmethod
    def _driver() -> ast.Module:
        return ast.parse(_DRIVER)

    def test_the_driver_parses_the_hook_before_the_hook_starts_its_clock(self):
        """The hook's clock starts as its module loads, and a script start
        compiles that module before its first line runs: the driver's own read
        and parse of the source after ``import session_start`` is time the wall
        counted and a real start never spends. Dies to: the parse moved back
        below the import."""
        body = self._driver().body
        imports = [n.lineno for n in body if isinstance(n, ast.Import)
                   and any(a.name == "session_start" for a in n.names)]
        parses = [n.lineno for n in ast.walk(self._driver()) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", "") == "parse" and getattr(n.func.value, "id", "") == "ast"]
        assert len(imports) == 1 and parses, (imports, parses)
        assert max(parses) < imports[0], (parses, imports)

    def test_every_call_in_a_phase_it_passes_through_is_answered_at_once(self):
        """Derived from ``_run_main``, so a read added to one of these phases
        later is red here, not on a loaded cell: each call to a hook function,
        or to ``_zone_watch``, made in a phase of ``_ANSWERED_AT_ONCE`` is one
        the driver replaces. Dies to: any one of the driver's replacements
        dropped (``_post_merge_unread`` and ``_merged_prs_line`` were the two
        missing at #580's red)."""
        func = next(n for n in self._TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_run_main")
        hook_funcs = {n.name for n in self._TREE.body if isinstance(n, ast.FunctionDef)}
        marks = sorted((c.lineno, c.args[0].value) for c in ast.walk(func) if isinstance(c, ast.Call)
                       and getattr(c.func, "id", "") == "_phase" and c.args and isinstance(c.args[0], ast.Constant))
        assert set(self._ANSWERED_AT_ONCE) <= {name for _, name in marks}, marks

        def phase_of(line: int) -> str:
            return max((m for m in marks if m[0] <= line), default=(0, ""))[1]

        needed: set[tuple[str, str]] = set()
        for c in ast.walk(func):
            if not isinstance(c, ast.Call) or phase_of(c.lineno) not in self._ANSWERED_AT_ONCE:
                continue
            if isinstance(c.func, ast.Name) and c.func.id in hook_funcs - self._NOT_WORK:
                needed.add(("ss", c.func.id))
            elif isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", "") == "_zone_watch":
                needed.add(("_zone_watch", c.func.attr))
        replaced = {(t.value.id, t.attr) for n in ast.walk(self._driver()) if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)}
        assert needed, marks
        assert not needed - replaced, sorted(needed - replaced)


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

    def test_main_hands_each_pull_request_line_its_own_read(self):
        """A listing of None tells a line to read for itself, so a listing main
        pre-read that did not answer would be read again (a second gh read at
        its 5 s cap). Dies to: main reading the listing itself again."""
        calls = [n for n in ast.walk(self._func("_run_main")) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)]
        assert not {c.func.id for c in calls} & {"_read_open_prs", "_read_merged_prs"}
        for name in ("_open_prs_line", "_merged_prs_line"):
            (call,) = [c for c in calls if c.func.id == name]
            assert isinstance(call.args[0], ast.Constant) and call.args[0].value is None, name

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

    def test_every_deadline_in_run_main_is_clipped(self):
        """DEF-5051's failure-mode review: a block given a fresh deadline of its
        own (`time.monotonic() + X`) beside the network budget passes the sum
        pin, which reads the module's constants. Every such deadline in
        ``_run_main`` sits inside a ``min(...)`` with the budget it is part of."""
        def fresh(n):
            return (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and isinstance(n.left, ast.Call)
                    and getattr(n.left.func, "attr", "") == "monotonic")
        func = self._func("_run_main")
        every = {id(n) for n in ast.walk(func) if fresh(n)}
        clipped = {id(n) for c in ast.walk(func) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "min"
                   for a in c.args for n in ast.walk(a) if fresh(n)}
        assert every and every == clipped, len(every - clipped)

    def test_every_handler_in_run_main_is_inside_a_named_phase(self):
        phases = {c.args[0].value for c in self._phase_calls() if c.args and isinstance(c.args[0], ast.Constant)}
        labels = {n.args[0].value.removeprefix("session_start: ").removesuffix(" failed")
                  for n in ast.walk(self._func("_run_main")) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "_late_load_failed"
                  and n.args and isinstance(n.args[0], ast.Constant)}
        assert labels and not labels - phases - self._ONE_PHASE, sorted(labels - phases - self._ONE_PHASE)


class TestTheMailIsReadBeforeThePullRequests:
    """DEF-5051: the seat naming, the mail and the orders read first, under a
    share of the one network budget of their own, and the pull-request block
    takes what they leave. They read last, on what the two `gh pr list` reads
    left, so a slow `gh` cost a worker seat its `Mail:` and `Orders:` lines
    first (win's banner, 2026-10-31), while the pull-request lines it kept are
    the ones `/inbox board` reads anyway. In-process starts with the network
    budget shrunk, so a row costs about as long as that budget."""

    _BUDGET_SECONDS = 1.5

    @staticmethod
    def _reached(seen: dict, key: str, phase: str):
        """``seen[key]``, which a fake sets only when the start reaches
        ``phase``: a phase the budget skipped (the 0.2 s floor every read here
        keeps) is a named failure, never a KeyError that reads as the clip
        being wrong (#509's Windows leg, run 42413047496)."""
        assert key in seen, f"the start never reached the {phase}, so the row judged nothing: {seen}"
        return seen[key]

    @staticmethod
    def _hook(monkeypatch):
        """The hook module, with its folder on the path first: a row that read
        a constant before its start imported it bare, which held only after
        an earlier row of the class had imported it (alone, a
        ModuleNotFoundError)."""
        monkeypatch.syspath_prepend(str(HOOKS_DIR.parent))
        monkeypatch.syspath_prepend(str(HOOKS_DIR))
        import session_start

        return session_start

    def _start(self, tmp_path, monkeypatch, *, read_prs, fetch_mail, share=None, spent=None, caps=None):
        """One in-process start; ``share`` patches the mail's share, ``spent``
        starts the hook's clock that many seconds ago (kept as ``self.hook_start``),
        and ``caps`` sets the pull-request block's budget and the mail's
        share and caps to that many seconds, so the hook's budget is the one
        clip that can bind."""
        import time

        repo = _tree(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
        monkeypatch.setenv("ESPALIER_SESSION_CATCH_UP", "0")
        import types

        ss = self._hook(monkeypatch)

        win = {"id": "20261101T000000Z-win-aaaaaa", "from": "win", "type": "note", "text": "the fixture hang", "re": {}}
        job = {"id": "20261101T000000Z-air-bbbbbb", "from": "air", "type": "assign", "text": "",
               "re": {"lane": "lane/the-job-the-banner-names", "seat": "mac"}}
        mail = types.SimpleNamespace(
            machine_setting=lambda root, timeout=None: ("mac", "git config espalier.machine = mac"),
            fetch_mail=fetch_mail,
            read_mail=lambda root, timeout=None: ({"win": [win], "air": [job]}, {}),
            local_mail_machines=lambda root, timeout=None: [],
            read_cursor=lambda root: {},
            unread=lambda by, cursor, exclude_machine: [win],
            headline=lambda m: f"{m['from']}: {m['type']} -- \"{m['text']}\"",
            dispatcher_setting=lambda root: ("air", "espalier.toml dispatcher = air"),
            live_assignments=lambda by, dispatcher: [job],
        )
        monkeypatch.setattr(ss, "_PR_BLOCK_BUDGET_SECONDS", self._BUDGET_SECONDS)
        monkeypatch.setattr(ss, "_load_mail", lambda: mail)
        monkeypatch.setattr(ss, "_read_open_prs", read_prs)
        monkeypatch.setattr(ss, "_read_merged_prs", read_prs)
        monkeypatch.setattr(ss, "_read_merge_rules", lambda *args, **kwargs: ("", -1, ""))
        monkeypatch.setattr(ss, "_engine_line", lambda *args, **kwargs: "")
        if caps is not None:
            for name in ("_PR_BLOCK_BUDGET_SECONDS", "_MAIL_SHARE_SECONDS",
                         "_MAIL_FETCH_CAP_SECONDS", "_MAIL_READ_CAP_SECONDS"):
                monkeypatch.setattr(ss, name, caps)
        if share is not None:
            monkeypatch.setattr(ss, "_MAIL_SHARE_SECONDS", share)
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"source": "resume", "session_id": "t-def5051"})))
        self.hook_start = None if spent is None else time.monotonic() - spent
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert ss.main(self.hook_start) == 0
        banners = _banners(buf.getvalue())
        assert len(banners) == 1, buf.getvalue()[:800]
        return banners[0]

    def test_a_slow_gh_costs_the_pull_request_lines_and_never_the_mail_or_the_orders(self, tmp_path, monkeypatch):
        """Must-deny: a `gh` that takes every second it is given. Dies to: the
        mail read after the pull-request block, on what it left."""
        import time

        def slow_gh(root, deadline=None):
            time.sleep(max(0.0, deadline - time.monotonic()))
            return ""

        banner = self._start(tmp_path, monkeypatch, read_prs=slow_gh, fetch_mail=lambda root, timeout: (True, ""))
        assert 'Mail:      win: note -- "the fixture hang"' in banner, banner[:1500]
        assert "Orders:    mac: 1 job from air, first lane/the-job-the-banner-names; 1 unread" in banner, banner[:1500]

    def test_the_pull_request_block_takes_what_the_mail_left_and_no_more(self, tmp_path, monkeypatch):
        """Must-not: the mail's share comes out of the one budget, never beside
        it, so the hook's network time stays the budget the sum pin counts.
        Dies to: a fresh pull-request deadline taken after the mail."""
        import time

        entered: list[float] = []
        deadlines: list[float] = []

        def fast_gh(root, deadline=None):
            entered.append(time.monotonic())
            deadlines.append(deadline)
            return ""

        def slow_fetch(root, timeout):
            entered.append(time.monotonic())
            time.sleep(0.5)
            return True, ""

        self._start(tmp_path, monkeypatch, read_prs=fast_gh, fetch_mail=slow_fetch)
        assert deadlines, "the pull-request block read nothing"
        assert max(deadlines) <= min(entered) + self._BUDGET_SECONDS + 0.2, (min(entered), deadlines)

    def test_the_mail_stops_at_its_share_and_the_pull_requests_get_the_rest(self, tmp_path, monkeypatch):
        """Must-deny: with the share under the budget, a fetch that hangs is
        given the share and no more, and the pull-request reads start once it
        is spent. Dies to: the mail read under the whole deadline (a hung
        config read, fetch and refs read could take seven of the eight seconds)."""
        import time

        seen: dict = {}

        def hung_fetch(root, timeout):
            seen["fetch"] = (time.monotonic(), timeout)
            time.sleep(timeout)
            return False, "timed out"

        def gh(root, deadline=None):
            seen.setdefault("gh", time.monotonic())
            return ""

        self._start(tmp_path, monkeypatch, read_prs=gh, fetch_mail=hung_fetch, share=0.5)
        start, timeout = self._reached(seen, "fetch", "mail fetch")
        assert timeout <= 0.5, timeout
        assert self._reached(seen, "gh", "pull-request reads") - start <= 0.5 + 0.3, (start, seen)

    # What the start has left of the hook's budget when its clock starts: room
    # for everything before the network reads on a loaded runner (more than
    # 0.8 s of it on #509's Windows leg, where a second left skipped the
    # fetch), and under the caps the row lifts, which never bind.
    _LEFT_SECONDS = 4.0
    _NEVER_BINDS_SECONDS = 60.0

    def test_both_deadlines_stop_at_the_hooks_budget(self, tmp_path, monkeypatch):
        """Must-deny: a start that has already spent most of the hook's budget
        (a slow catch-up, or a fresh start's child) gives the mail and the pull
        requests only what is left of it. The block's budget and the mail's
        share and caps are lifted past what is left, so the hook's budget is
        the one clip that binds, and the start keeps enough of it to reach both
        reads on a slow runner. Dies to: either deadline unclipped."""
        import time

        seen: dict = {}

        def fetch(root, timeout):
            seen["fetch_ends"] = time.monotonic() + timeout
            return True, ""

        def gh(root, deadline=None):
            seen.setdefault("pr", deadline)
            return ""

        budget = self._hook(monkeypatch)._HOOK_BUDGET_SECONDS
        self._start(tmp_path, monkeypatch, read_prs=gh, fetch_mail=fetch,
                    spent=budget - self._LEFT_SECONDS, caps=self._NEVER_BINDS_SECONDS)
        limit = self.hook_start + budget + 0.05
        assert self._reached(seen, "fetch_ends", "mail fetch") <= limit, (seen, limit)
        assert self._reached(seen, "pr", "pull-request reads") <= limit, (seen, limit)
