"""A spawn's ``timeout`` bounds the call even when a grandchild holds its pipe.

On Windows ``subprocess.run`` kills only the child at the timeout and then
reads the pipes with no timeout, so a ``.bat`` shim's program, or the real git
behind Git for Windows's ``cmd\\git.exe`` launcher, set the bound instead
(2026-10-12, CPython 3.11.9: a 2 s cap returned after 20.1 s through a shim, a
1 s cap on ``git ls-remote`` after 21.1 s). ``_json_safe.run_bounded`` kills
the tree and drains under a grace; ``_hook_utils.spawn_checked`` is built on
it, and ``tests/test_spawn_chokepoint.py`` holds every timed spawn under
``tools/cc`` to one of the two (and drives the Windows branch on every OS with
a stand-in ``Popen``).

The oracle is an order, not a clock: each holder writes a ``done`` marker when
its ``HOLD_SECONDS`` sleep ends, and a bounded call returns before that marker
exists, where an unbounded one waits for the holder and finds it. A loaded box
can slow the call but cannot reorder it, so the module asserts no wall-clock
bound (``scripts/proof_tier.py::WALL_CLOCK_SERIAL_FILES`` is for those). On
POSIX ``run`` was already bounded, so the cases hold there as regression cases;
but there its timeout kills the child alone and what the child started runs on,
which ``_json_safe.run_tree_bounded`` (and ``communicate_tree_bounded`` for a
child the caller holds) ends: ``TestTheTreeBoundedRunEndsTheWholeTree`` and
``TestTheWalkSignalsOnlyItsOwnTree``. Real processes on every OS, so the module
is slow.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from tests._platform_standin import as_os
from tests._wait_budget import scaled

TOOLS_CC = Path(__file__).resolve().parents[1] / "tools" / "cc"
CAP_SECONDS = 3.0  # long enough that the holder has surely started inside it
HOLD_SECONDS = 20  # how long the holder sleeps before it writes its marker


def _load_hook_utils():
    spec = importlib.util.spec_from_file_location("hook_utils_for_bound", str(TOOLS_CC / "hooks" / "_hook_utils.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hook_utils_for_bound"] = mod
    spec.loader.exec_module(mod)
    return mod


def _alive(pid: int) -> bool:
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


def _end_holder(pidfile: Path) -> None:
    """Teardown: end the holder a case started, where it is still alive: on
    POSIX ``run_bounded``'s timeout kills only the child, so the grandchild
    sleeps on; a tree-bounded row that failed leaves its holder too; and the
    limit row's holder is one the tree kill leaves running by design."""
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _holder(tmp_path: Path, hold: float = HOLD_SECONDS) -> tuple[list[str], Path, Path]:
    """A launcher (``.bat`` on Windows, ``sh`` elsewhere) whose child -- the
    spawn's grandchild -- inherits stdout, writes its pid, sleeps ``hold``
    seconds, and then writes the ``done`` marker."""
    pidfile, done = tmp_path / "holder.pid", tmp_path / "holder.done"
    body = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
            f"print(1, flush=True); time.sleep({hold}); open({str(done)!r}, 'w').write('done')")
    if os.name == "nt":
        shim = tmp_path / "holder.bat"
        shim.write_bytes(f'@echo off\r\n"{sys.executable}" -c "{body}"\r\n'.encode("ascii"))
    else:
        shim = tmp_path / "holder.sh"
        shim.write_bytes(f'#!/bin/sh\n"{sys.executable}" -c "{body}"\n'.encode("ascii"))
        shim.chmod(0o755)
    return [str(shim)], pidfile, done


class TestTheTimeoutIsABound:
    def test_a_grandchild_holding_the_pipe_cannot_outlast_the_chokepoints_timeout(self, tmp_path):
        hu = _load_hook_utils()
        argv, pidfile, done = _holder(tmp_path)
        start = time.monotonic()
        try:
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                hu.spawn_checked(argv, root=tmp_path, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=CAP_SECONDS)
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the cap, so the case did not run"
            holder_alive = _alive(int(pidfile.read_text(encoding="utf-8").strip()))
        finally:
            _end_holder(pidfile)
        assert returned_first, (
            f"a {CAP_SECONDS:.0f} s timeout returned only after the holder finished its "
            f"{HOLD_SECONDS} s sleep ({took:.1f} s): the grandchild holding the pipe set the bound"
        )
        if os.name == "nt":
            # The bound alone holds without the tree kill (the drain gives up at
            # its grace); these two hold only with it: the holder is ended, so
            # its pipe closed and what it wrote was read.
            assert not holder_alive, "the timeout returned but the grandchild outlived the tree kill"
            assert "1" in (caught.value.stdout or ""), f"the drain read nothing: {caught.value.stdout!r}"

    def test_the_banners_mail_fetch_is_bounded_by_its_cap(self, tmp_path):
        """The hook-level case: ``mail.fetch_mail``, the SessionStart ``Mail:``
        line's network read, through ``record_merge.run``, against an origin
        whose upload-pack sleeps and then writes the marker (local, so no
        network decides the outcome). git's own processes hold the pipe here:
        the launcher on Windows."""
        if shutil.which("git") is None:
            pytest.skip("git is not on PATH")
        remote, clone, done = tmp_path / "remote.git", tmp_path / "clone", tmp_path / "upload-pack.done"
        uploadpack = f"sleep {HOLD_SECONDS}; echo done > '{done.as_posix()}' #"
        for argv in (["git", "init", "-q", "--bare", str(remote)], ["git", "init", "-q", str(clone)],
                     ["git", "-C", str(clone), "remote", "add", "origin", str(remote)],
                     ["git", "-C", str(clone), "config", "remote.origin.uploadpack", uploadpack]):
            subprocess.run(argv, check=True, capture_output=True, timeout=30)
        sys.path.insert(0, str(TOOLS_CC))
        try:
            import mail
        finally:
            sys.path.remove(str(TOOLS_CC))
        start = time.monotonic()
        ok, problem = mail.fetch_mail(clone, timeout=CAP_SECONDS)
        returned_first = not done.exists()
        took = time.monotonic() - start
        assert not ok and "longer than" in problem, (ok, problem)
        assert returned_first, (
            f"the mail fetch's {CAP_SECONDS:.0f} s cap returned only after the upload-pack finished "
            f"its {HOLD_SECONDS} s sleep ({took:.1f} s): git's own processes held the pipe past it, "
            "so the banner waits on the network, not its cap"
        )

    def test_an_engine_command_runner_is_bounded_by_its_cap(self, tmp_path):
        """The engine-level case (DEF-3004): ``espalier/pre_release.py``'s
        command runner, which ``espalier pre-release`` runs each gate command
        through, on the same holder. Before the engine had its own bounded
        spawn (``espalier/_spawn.py``) its call was ``subprocess.run``'s, and on
        Windows it returned only after the holder ended."""
        from espalier import pre_release

        argv, pidfile, done = _holder(tmp_path)
        start = time.monotonic()
        try:
            result = pre_release._run_command(argv, tmp_path, timeout_seconds=int(CAP_SECONDS))
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the cap, so the case did not run"
        finally:
            _end_holder(pidfile)
        assert result["timed_out"], result
        assert returned_first, (
            f"the engine's {CAP_SECONDS:.0f} s command cap returned only after the holder finished "
            f"its {HOLD_SECONDS} s sleep ({took:.1f} s): the grandchild holding the pipe set the bound"
        )


def _load_json_safe():
    spec = importlib.util.spec_from_file_location("json_safe_for_tree_bound", str(TOOLS_CC / "_json_safe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTheTreeBoundEndsEveryProcessAtTheDeadline:
    """``_json_safe.run_tree_to_deadline``, the spawn ``write_guard``'s parent
    answers through (DEF-3048): at the deadline the child and every process
    below it end, and nothing waits past the deadline on a pipe a grandchild
    holds. The same order oracle as the rest of the module: the call returns
    before the holder's ``done`` marker exists."""

    def test_at_the_deadline_the_call_answers_none_and_the_grandchild_ends(self, tmp_path):
        js = _load_json_safe()
        argv, pidfile, done = _holder(tmp_path)
        try:
            answer = js.run_tree_to_deadline(argv, deadline=time.monotonic() + CAP_SECONDS, input=b"")
            returned_first = not done.exists()
            assert pidfile.exists(), "the holder never started inside the deadline, so the case did not run"
            holder = int(pidfile.read_text(encoding="utf-8").strip())
            gone_by = time.monotonic() + 5.0
            while _alive(holder) and time.monotonic() < gone_by:
                time.sleep(0.05)
            holder_alive = _alive(holder)
        finally:
            _end_holder(pidfile)
        assert answer is None, answer
        assert returned_first, "the call waited for the holder's sleep: the grandchild set the bound"
        assert not holder_alive, "the call answered but the grandchild outlived the tree kill"

    def test_a_child_that_ends_in_time_is_answered_with_its_code_and_both_streams(self, tmp_path):
        js = _load_json_safe()
        echo = "import sys; sys.stdout.write(sys.stdin.read()); sys.stderr.write('e'); sys.exit(2)"
        answer = js.run_tree_to_deadline([sys.executable, "-c", echo], deadline=time.monotonic() + 30,
                                         input=b'{"x": 1}')
        assert answer == (2, b'{"x": 1}', b"e"), answer

    def test_a_child_that_ended_while_its_grandchild_held_the_pipe_keeps_its_answer(self, tmp_path):
        js = _load_json_safe()
        pidfile, done = tmp_path / "holder.pid", tmp_path / "holder.done"
        body = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
                f"time.sleep({HOLD_SECONDS}); open({str(done)!r}, 'w').write('done')")
        leaves = (f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {body!r}]); "
                  "print('decided', flush=True); sys.exit(0)")
        try:
            answer = js.run_tree_to_deadline([sys.executable, "-c", leaves],
                                             deadline=time.monotonic() + CAP_SECONDS, input=b"")
            returned_first = not done.exists()
        finally:
            _end_holder(pidfile)
        assert returned_first, "the call waited for the holder's sleep"
        assert answer is not None and answer[0] == 0 and b"decided" in answer[1], answer

    def test_a_child_that_never_reads_its_input_does_not_hold_the_deadline(self, tmp_path):
        """The input goes in from a thread of its own: a payload larger than
        the pipe, which the child never reads, holds no write past the
        deadline. CPython 3.11 and 3.12 write ``communicate``'s input on
        Windows before the timed joins, so this row reds there on that shape;
        POSIX writes the input through the selector, green on either."""
        js = _load_json_safe()
        done = tmp_path / "sleeper.done"
        sleeps = f"import time; time.sleep({HOLD_SECONDS}); open({str(done)!r}, 'w').write('done')"
        answer = js.run_tree_to_deadline([sys.executable, "-c", sleeps], deadline=time.monotonic() + CAP_SECONDS,
                                         input=b"x" * (4 << 20))
        assert not done.exists(), "the call waited for the child's sleep: its unread input set the bound"
        assert answer is None, answer

    def test_a_child_that_cannot_start_raises_the_start_error(self, tmp_path):
        """A caller tells a child that never ran (judge in its place) from one
        that ran and was lost (never judge twice) by this type alone; it stays
        an ``OSError`` for a caller that catches the spawn's own error."""
        js = _load_json_safe()
        with pytest.raises(js.TreeStartError) as caught:
            js.run_tree_to_deadline([str(tmp_path / "no-such-program")], deadline=time.monotonic() + CAP_SECONDS,
                                    input=b"")
        assert isinstance(caught.value, OSError)
        assert isinstance(caught.value.__cause__, OSError), caught.value.__cause__

    def test_at_the_deadline_heard_takes_what_the_child_wrote_on_stderr(self, tmp_path):
        """DEF-2091: ``write_guard``'s parent tells a child that had begun
        judging from one still starting up by what the child wrote before the
        kill, so the stderr drained at the deadline goes to ``heard``."""
        js = _load_json_safe()
        done = tmp_path / "sleeper.done"
        began = tmp_path / "sleeper.began"
        # The child marks its first line before it writes, so a red tells a
        # child the cap's load kept from starting from a drain that lost what
        # it wrote.
        # The sleep outlasts the cap however far a ceiling scales it.
        body = (f"import os, time; open({str(began)!r}, 'w').close(); os.write(2, b'began\\n'); "
                f"time.sleep({scaled(CAP_SECONDS) + HOLD_SECONDS}); open({str(done)!r}, 'w').write('done')")
        heard: list[bytes] = []
        answer = js.run_tree_to_deadline([sys.executable, "-c", body],
                                         deadline=time.monotonic() + scaled(CAP_SECONDS), input=b"", heard=heard)
        assert not done.exists(), "the call waited for the child's sleep"
        assert answer is None, answer
        assert began.exists(), ("the child never reached its first line inside the cap: the box's load, not"
                                " the drain", heard)
        assert heard == [b"began\n"], heard

    def test_a_reader_thread_that_cannot_start_leaves_stderr_to_the_drain(self, monkeypatch):
        """Where ``heard`` is asked on Windows, stderr is read on a thread of
        its own; one that cannot start leaves it to ``communicate``, as on
        POSIX, never a raise before the tree's guard that loses the answer
        and leaves the child running (DEF-2094's review)."""
        import threading

        js = _load_json_safe()
        start = threading.Thread.start
        refused: list[int] = []

        def refuse_the_reader(self: threading.Thread) -> None:
            if getattr(self, "_target", None) is js._read_chunks:
                refused.append(1)
                raise RuntimeError("can't start new thread")
            start(self)

        monkeypatch.setattr(threading.Thread, "start", refuse_the_reader)
        body = "import sys; sys.stdout.write('out'); sys.stderr.write('err')"
        answer = js.run_tree_to_deadline([sys.executable, "-c", body], deadline=time.monotonic() + scaled(30),
                                         input=b"", heard=[])
        assert answer == (0, b"out", b"err"), answer
        # The reader thread is Windows' alone: elsewhere this row proves only the answer.
        assert refused == ([1] if os.name == "nt" else []), refused

    def test_an_ahead_thread_that_cannot_start_leaves_the_wait_to_answer(self, monkeypatch):
        """``ahead``'s callback starts on a thread of its own; one that cannot
        start is skipped and the wait goes on, never a raise that loses the
        child's answer (DEF-2094's review)."""
        import threading

        js = _load_json_safe()
        start = threading.Thread.start
        ran: list[int] = []

        def build() -> None:
            ran.append(1)

        refused: list[int] = []

        def refuse_the_build(self: threading.Thread) -> None:
            if getattr(self, "_target", None) is build:
                refused.append(1)
                raise RuntimeError("can't start new thread")
            start(self)

        monkeypatch.setattr(threading.Thread, "start", refuse_the_build)
        body = "import sys, time; time.sleep(0.5); sys.stdout.write('late')"
        answer = js.run_tree_to_deadline([sys.executable, "-c", body], deadline=time.monotonic() + scaled(30),
                                         input=b"", ahead=(time.monotonic() + 0.05, build))
        assert answer is not None and answer[:2] == (0, b"late"), answer
        assert ran == [], ran
        # The child sleeps past ``ahead``'s time, so the refusal was met.
        assert refused == [1], refused

    def test_a_feeder_that_cannot_start_ends_the_child_and_says_none_ran(self, monkeypatch):
        """The input goes in from a thread of its own; one that cannot start
        leaves the child without its input, so it did nothing with it: the
        tree is ended and the caller is told no child ran (``TreeStartError``),
        so ``write_guard`` judges the call itself rather than refusing it as a
        fault inside a run (F5 of DEF-2094's review)."""
        import threading

        js = _load_json_safe()
        start = threading.Thread.start
        made: list[subprocess.Popen] = []
        popen = subprocess.Popen

        def recording(*args, **kwargs):
            proc = popen(*args, **kwargs)
            if not made:  # the child; the tree kill's own spawns (Windows' taskkill) go unrecorded
                made.append(proc)
            return proc

        def refuse_the_feeder(self: threading.Thread) -> None:
            if getattr(self, "_target", None) is js._feed:
                raise RuntimeError("can't start new thread")
            start(self)

        monkeypatch.setattr(subprocess, "Popen", recording)
        monkeypatch.setattr(threading.Thread, "start", refuse_the_feeder)
        sleeps = f"import time; time.sleep({scaled(10) + HOLD_SECONDS})"
        try:
            with pytest.raises(js.TreeStartError) as caught:
                js.run_tree_to_deadline([sys.executable, "-c", sleeps], deadline=time.monotonic() + scaled(30),
                                        input=b"x")
            assert isinstance(caught.value.__cause__, RuntimeError), caught.value.__cause__
            assert len(made) == 1, made
            try:
                made[0].wait(timeout=scaled(10))
            except subprocess.TimeoutExpired:
                pytest.fail("the child outlived the raise: nothing ended the tree")
        finally:
            for proc in made:
                proc.kill()

    def test_a_raise_in_the_deadlines_read_still_ends_the_tree(self, monkeypatch):
        """At the deadline the runner reads whether the child ended on its own
        before it ends the tree; a raise in that read (an interrupt) still ends
        it, since the handler it sits in is outside the guard that ends the
        tree on a raise, and on POSIX the child's own session keeps it out of
        any kill of the caller (F6 of DEF-2094's review)."""
        js = _load_json_safe()
        made: list[subprocess.Popen] = []
        popen = subprocess.Popen

        def recording(*args, **kwargs):
            proc = popen(*args, **kwargs)
            if made:  # the tree kill's own spawns (Windows' taskkill) read as they are
                return proc
            read = proc.poll
            calls: list[int] = []

            def raise_first() -> int | None:
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("an interrupt in the read")
                return read()

            proc.poll = raise_first  # type: ignore[method-assign]
            made.append(proc)
            return proc

        monkeypatch.setattr(subprocess, "Popen", recording)
        # The sleep outlasts the wait below however far a ceiling scales both.
        sleeps = f"import time; time.sleep({scaled(10) + HOLD_SECONDS})"
        try:
            with pytest.raises(RuntimeError, match="an interrupt in the read"):
                js.run_tree_to_deadline([sys.executable, "-c", sleeps], deadline=time.monotonic() + 0.5, input=b"")
            assert len(made) == 1, made
            try:
                made[0].wait(timeout=scaled(10))
            except subprocess.TimeoutExpired:
                pytest.fail("the child outlived the raise: nothing ended the tree")
        finally:
            for proc in made:
                proc.kill()

    def test_a_child_that_answers_before_ahead_never_starts_it(self):
        """DEF-2092's callback costs a call answered in time nothing: a child
        that answers before ``ahead``'s time never starts it (40ec7f)."""
        js = _load_json_safe()
        started: list[int] = []
        answer = js.run_tree_to_deadline([sys.executable, "-c", "pass"], deadline=time.monotonic() + 60,
                                         input=b"", ahead=(time.monotonic() + 50, lambda: started.append(1)))
        assert answer is not None and answer[0] == 0, answer
        assert started == [], started

    def test_a_child_still_running_at_ahead_starts_it_once_on_a_thread_of_its_own(self):
        """A child still running at ``ahead``'s time starts its callback once,
        on a thread of its own, and the wait goes on to the deadline: DEF-2092's
        refusal is built there while the parent still waits."""
        import threading

        js = _load_json_safe()
        ran: list[threading.Thread] = []
        done = threading.Event()

        def build() -> None:
            ran.append(threading.current_thread())
            done.set()

        at = time.monotonic() + 0.5
        answer = js.run_tree_to_deadline([sys.executable, "-c", f"import time; time.sleep({HOLD_SECONDS})"],
                                         deadline=time.monotonic() + CAP_SECONDS, input=b"", ahead=(at, build))
        assert answer is None, answer
        assert done.wait(scaled(10)), "the callback never ran"
        # The order, never a clock: this module asserts no wall-clock bound,
        # and a callback started before ``ahead`` is the answered-in-time
        # row's red (it starts none there).
        assert len(ran) == 1, ran
        assert ran[0] is not threading.main_thread()


class TestTheTreeBoundedRunEndsTheWholeTree:
    """``_json_safe.run_tree_bounded`` (and, through the engine's command
    runner, its twin ``espalier/_spawn.py::run_tree_bounded``, held equal in
    code by ``tests/test_contracts.py::TestTheBoundedSpawnTwins``):
    ``run_bounded`` whose timeout, and any
    exception while it waits, ends the child's whole tree on every OS, while
    the child starts in the caller's own process group so an ancestor's group
    kill still reaches it. On POSIX ``run`` kills the child alone and leaves
    what it started running at parent 1 (``scripts/verify_pins.py``'s inner
    pytest, and the suite's runs of that script), so each row here reds there
    with ``run_bounded`` in its place. The same order oracle as the rest of
    the module: the call returns before the holder's ``done`` marker exists,
    and the holder is gone after it."""

    @staticmethod
    def _gone(pidfile: Path) -> bool:
        assert pidfile.exists(), "the holder never started inside the bound, so the case did not run"
        holder = int(pidfile.read_text(encoding="utf-8").strip())
        gone_by = time.monotonic() + 5.0
        while _alive(holder) and time.monotonic() < gone_by:
            time.sleep(0.05)
        return not _alive(holder)

    def test_at_the_timeout_the_grandchild_ends_and_the_timeout_is_raised(self, tmp_path):
        js = _load_json_safe()
        argv, pidfile, done = _holder(tmp_path)
        try:
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                js.run_tree_bounded(argv, capture_output=True, timeout=CAP_SECONDS)
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
        assert returned_first, "the call waited for the holder's sleep: the grandchild set the bound"
        assert gone, "the call raised but the grandchild outlived the tree kill"
        assert caught.value.timeout == CAP_SECONDS

    def test_the_engines_command_runner_ends_the_grandchild_at_its_cap(self, tmp_path):
        """DEF-5090 at the engine's own site: ``espalier pre-release`` runs the
        not-heavy suite through ``espalier/pre_release.py::_run_command``, which
        takes the engine's tree run (``espalier/_spawn.py::run_tree_bounded``),
        so at its cap the holder the child started is gone too. With the
        runner on ``run_no_stdin`` this reds on POSIX, where ``run`` kills the
        child alone (driven under WSL on 2026-11-17: the grandchild outlived
        the cap 3 of 3 times at ``origin/main``, 0 of 3 on the lane); on
        Windows ``run_bounded``'s ``taskkill /T`` ended it there too, so the red
        is the POSIX cells'."""
        from espalier import pre_release

        argv, pidfile, done = _holder(tmp_path)
        try:
            result = pre_release._run_command(argv, tmp_path, timeout_seconds=int(CAP_SECONDS))
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
        assert result["timed_out"], result
        assert returned_first, "the engine's command runner waited for the holder's sleep"
        assert gone, ("the engine's command runner timed out but the grandchild outlived it: the cap "
                      "killed the child alone, and what it started runs on at parent 1")

    @pytest.mark.parametrize("middle", ["a tree-bounded run of its own", "a child in a session of its own"])
    def test_a_nested_run_is_ended_with_the_outer_one(self, tmp_path, middle):
        """The suite's run of ``verify_pins``, whose inner pytest is bounded
        by a run of its own: the outer timeout ends the inner tree too, and so
        it does where the middle level started its child in a session of its
        own, which no group kill from above reaches."""
        js = _load_json_safe()
        # Two interpreters start before the holder does, so the bound is wider
        # than a plain row's, and the holder sleeps past it on any ceiling.
        argv, pidfile, done = _holder(tmp_path, hold=scaled(10) + HOLD_SECONDS)
        if middle.startswith("a tree"):
            spawn = ("import importlib.util; "
                     f"s = importlib.util.spec_from_file_location('js', {str(TOOLS_CC / '_json_safe.py')!r}); "
                     "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                     f"m.run_tree_bounded({argv!r}, timeout=600)")
        else:
            spawn = f"import subprocess; subprocess.Popen({argv!r}, start_new_session=True).wait()"
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                js.run_tree_bounded([sys.executable, "-c", spawn], capture_output=True,
                                    timeout=scaled(10))
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
        assert returned_first, "the call waited for the holder's sleep"
        assert gone, f"the outer timeout left the holder below {middle} running"

    @pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX; Windows walks the tree by parent")
    def test_the_child_starts_in_the_callers_own_group(self):
        """A group of its own would hide the tree from every ancestor's group
        kill (``scripts/fresh_clone_gate.py``'s, ``scripts/archive_probe.py``'s)."""
        js = _load_json_safe()
        got = js.run_tree_bounded([sys.executable, "-c", "import os; print(os.getpgid(0))"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=scaled(30))
        assert int(got.stdout) == os.getpgid(0), got

    def test_a_child_that_ends_in_time_is_answered_as_run_answers(self, tmp_path):
        js = _load_json_safe()
        body = "import os, sys; print(os.getcwd()); sys.stderr.write(sys.stdin.read()); sys.exit(3)"
        got = js.run_tree_bounded([sys.executable, "-c", body], input="fed", capture_output=True, text=True,
                                  encoding="utf-8", cwd=str(tmp_path), timeout=scaled(30))
        assert (got.returncode, got.stderr) == (3, "fed"), got
        assert Path(got.stdout.strip()).resolve() == tmp_path.resolve(), got
        with pytest.raises(subprocess.CalledProcessError):
            js.run_tree_bounded([sys.executable, "-c", "raise SystemExit(4)"], check=True, timeout=scaled(30))

    @pytest.mark.skipif(os.name == "nt", reason="the signal-raised exception is the POSIX ceiling's shape")
    def test_an_exception_while_it_waits_ends_the_tree_and_goes_on(self, tmp_path):
        """The per-test ceiling raises inside the wait (pytest-timeout's
        ``signal`` method); so does a Ctrl-C. The tree ends and the error goes
        on, where ``run`` would kill the child alone. The signal goes to this
        thread (``pthread_kill``), where a process-directed one may land on
        another and leave the wait running."""
        import signal
        import threading

        class _Ceiling(Exception):
            pass

        def _raise(*_):
            raise _Ceiling()

        js = _load_json_safe()
        argv, pidfile, done = _holder(tmp_path)
        before = signal.signal(signal.SIGUSR1, _raise)
        timer = threading.Timer(CAP_SECONDS, signal.pthread_kill, (threading.get_ident(), signal.SIGUSR1))
        try:
            timer.start()
            with pytest.raises(_Ceiling):
                js.run_tree_bounded(argv, capture_output=True, timeout=30)
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            timer.cancel()
            signal.signal(signal.SIGUSR1, before)
            _end_holder(pidfile)
        assert returned_first, "the call waited for the holder's sleep"
        assert gone, "the exception went on but the grandchild outlived it"

    @pytest.mark.skipif(os.name == "nt", reason="the process-table walk is the POSIX kill")
    def test_the_table_read_gives_each_column_its_own_flag_and_reads_this_process(self):
        """POSIX reads the text after ``=`` as the header for the rest of its
        argument, so ``-o pid=,ppid=,pgid=`` is one column on a ps that follows
        it (BusyBox's), where every row then fails the parse and the walk falls
        back to the child alone without a word; macOS and procps split it
        anyway, so the spelling is pinned by shape. Then the real read here."""
        js = _load_json_safe()
        argv = js.PS_TABLE_ARGV
        columns = [argv[i + 1] for i, flag in enumerate(argv) if flag == "-o"]
        assert columns == ["pid=", "ppid=", "pgid="], argv
        table = js._process_table(time.monotonic() + scaled(10))
        assert table is not None, "ps answered nothing parseable on this host"
        assert table.get(os.getpid()) == (os.getppid(), os.getpgid(0)), table.get(os.getpid())

    @pytest.mark.skipif(os.name == "nt", reason="the process-table walk is the POSIX kill")
    def test_where_the_table_cannot_be_read_the_child_alone_is_ended(self, tmp_path, monkeypatch):
        """No ``ps``: the kill falls back to the child, and the call still
        raises at its timeout instead of waiting on the child's sleep."""
        js = _load_json_safe()
        monkeypatch.setattr(js, "_process_table", lambda _end: None)
        pidfile, done = tmp_path / "sleeper.pid", tmp_path / "sleeper.done"
        sleeps = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
                  f"time.sleep({HOLD_SECONDS}); open({str(done)!r}, 'w').write('done')")
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                js.run_tree_bounded([sys.executable, "-c", sleeps], capture_output=True,
                                    timeout=scaled(CAP_SECONDS))
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
        assert returned_first, "the call waited for the child's sleep"
        assert gone, "with no process table the child itself outlived the timeout"

    def test_a_stand_in_for_run_is_called_as_is(self, monkeypatch):
        """A test that replaces ``subprocess.run`` has no tree to end; the
        call reaches its stand-in, as ``run_bounded``'s does."""
        js = _load_json_safe()
        seen = []
        monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.append((args, kw.get("timeout"))) or "stood in")
        assert js.run_tree_bounded(["x"], timeout=7) == "stood in"
        assert seen == [(["x"], 7)]

    @pytest.mark.skipif(os.name == "nt", reason="sessions and process groups are POSIX")
    @pytest.mark.parametrize("given", ["start_new_session", "process_group", "preexec_fn"])
    def test_a_session_or_group_of_its_own_is_refused(self, tmp_path, given):
        """A session at this level hides the tree from every ancestor's group
        kill, which ``scripts/fresh_clone_gate.py`` and
        ``scripts/archive_probe.py`` end their runs by; so the call refuses the
        keywords that make one, before anything starts."""
        js = _load_json_safe()
        started = tmp_path / "started"
        value = {"start_new_session": True, "process_group": 0, "preexec_fn": os.setsid}[given]
        with pytest.raises(ValueError, match=given):
            js.run_tree_bounded([sys.executable, "-c", f"open({str(started)!r}, 'w').write('1')"],
                                timeout=scaled(30), **{given: value})
        assert not started.exists(), "the refused call started its child anyway"

    @pytest.mark.skipif(os.name == "nt", reason="the process-table walk is the POSIX kill")
    def test_where_the_table_cannot_be_read_a_child_that_leads_a_group_is_ended_through_it(
            self, tmp_path, monkeypatch):
        """No ``ps``, and a child that made a session of its own: the kill takes
        the child's group as well as the child, so what it started there ends
        with it."""
        js = _load_json_safe()
        monkeypatch.setattr(js, "_process_table", lambda _end: None)
        pidfile, done = tmp_path / "holder.pid", tmp_path / "holder.done"
        body = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
                f"time.sleep({HOLD_SECONDS}); open({str(done)!r}, 'w').write('done')")
        leads = (f"import os, subprocess, sys, time; os.setsid(); "
                 f"subprocess.Popen([sys.executable, '-c', {body!r}], stdout=subprocess.DEVNULL); "
                 f"time.sleep({HOLD_SECONDS})")
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                js.run_tree_bounded([sys.executable, "-c", leads], capture_output=True,
                                    timeout=scaled(CAP_SECONDS))
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
        assert returned_first, "the call waited for the holder's sleep"
        assert gone, "with no process table the kill reached the child and not the group it leads"

    @staticmethod
    def _chain(tmp_path: Path, *, leader_waits: bool, hold: float) -> tuple[str, Path, Path, Path]:
        """``R -> L -> A -> B``: the child ``R`` starts ``L`` in a session of
        its own, ``L`` runs ``A``, and ``A`` starts ``B`` and exits, so ``B``
        sits at parent 1 in ``L``'s group. ``leader_waits``: ``L`` sleeps on
        (its group is one the tree leads); else ``L`` exits too and ``R``
        sleeps alone, so ``B``'s group has no leader in the tree."""
        pidfile, done, ready = tmp_path / "b.pid", tmp_path / "b.done", tmp_path / "chain.ready"
        b = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
             f"time.sleep({hold}); open({str(done)!r}, 'w').write('done')")
        a = (f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {b!r}], "
             "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)")
        tail = f"; import time; time.sleep({hold})" if leader_waits else ""
        leader = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {a!r}])" + tail
        root = (f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {leader!r}], "
                "start_new_session=True)" + ("" if leader_waits else ".wait()")
                + f"; open({str(ready)!r}, 'w').write('1'); time.sleep({hold})")
        return root, pidfile, done, ready

    @pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
    def test_a_process_left_at_parent_1_in_a_group_the_tree_leads_is_ended(self, tmp_path):
        """``B``'s parent ended before the walk, so no read finds it below the
        child; its group's leader is in the tree, and the kill of that group
        ends it. With the group kill left out ``B`` runs on at parent 1."""
        js = _load_json_safe()
        root, pidfile, done, _ready = self._chain(tmp_path, leader_waits=True, hold=scaled(10) + HOLD_SECONDS)
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                js.run_tree_bounded([sys.executable, "-c", root], capture_output=True, timeout=scaled(10))
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
        assert returned_first, "the call waited for B's sleep"
        assert gone, "B, at parent 1 in a group a tree process leads, outlived the tree kill"

    def test_an_orphan_whose_group_leader_ended_first_runs_on_posix_and_the_job_ends_it_on_windows(self, tmp_path):
        """The declared limit (POSIX), pinned as it stands, on every host:
        ``B``'s parent and its group's leader both ended before the timeout,
        so on POSIX ``B`` is below no process in the tree and in no group the
        walk knows, and it runs on after the call. The day a reader finds it,
        this row reds and the sentence in ``docs/SHARP_EDGES.md`` that cites it
        is rewritten. On Windows ``start_new_session`` is not read, ``B`` sits
        under a dead parent where ``taskkill /T`` cannot reach it, and it is
        still in the kill-on-close job ``R`` was put in, so the job's
        ``TerminateJobObject`` ends it: the one row that pins the job on a
        real process."""
        js = _load_json_safe()
        root, pidfile, done, ready = self._chain(tmp_path, leader_waits=False, hold=scaled(10) + HOLD_SECONDS)
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                js.run_tree_bounded([sys.executable, "-c", root], capture_output=True, timeout=scaled(10))
            assert ready.exists() and pidfile.exists(), "the chain did not finish inside the bound, so the case did not run"
            if os.name == "nt":
                ended = self._gone(pidfile)
            else:
                holder = int(pidfile.read_text(encoding="utf-8").strip())
                time.sleep(0.5)
                survived = _alive(holder) and not done.exists()
        finally:
            _end_holder(pidfile)
        if os.name == "nt":
            assert ended, "B, under a dead parent, outlived the job: TerminateJobObject did not end what was in it"
        else:
            assert survived, "the orphan in a leaderless group was ended: the limit closed, rewrite its sentence"

    @pytest.mark.skipif(os.name == "nt", reason="the process-table walk is the POSIX kill")
    def test_a_process_forked_after_a_read_is_read_and_ended_too(self, tmp_path, monkeypatch):
        """The child forks for as long as it runs, starting the moment the
        walk's first read has returned (the read is wrapped to start it), so
        that read is stale before the stop. The walk stops what it read, reads
        again until a read finds nothing new, and only then kills: every
        process forked is ended. One read, or no stop before the next read,
        leaves the forks made after the last read running at parent 1."""
        js = _load_json_safe()
        sleep = shutil.which("sleep") or "/bin/sleep"
        ready, trigger, pids = tmp_path / "ready", tmp_path / "go", tmp_path / "forked.pids"
        spawner = (
            "import os, subprocess, time\n"
            f"open({str(ready)!r}, 'w').write('1')\n"
            f"while not os.path.exists({str(trigger)!r}):\n"
            "    time.sleep(0.002)\n"
            f"with open({str(pids)!r}, 'a') as fh:\n"
            "    while True:\n"
            f"        p = subprocess.Popen([{sleep!r}, '30'], stdin=subprocess.DEVNULL,\n"
            "                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "        fh.write(str(p.pid) + '\\n'); fh.flush()\n"
            "        time.sleep(0.005)\n"
        )
        real_read = js._process_table
        reads: list = []

        def stale_first_read(end):
            table = real_read(end)
            if not reads:
                trigger.write_text("go", encoding="utf-8")
                forked_by = time.monotonic() + 5.0
                while not (pids.exists() and pids.read_text(encoding="utf-8").strip()) and time.monotonic() < forked_by:
                    time.sleep(0.002)
            reads.append(table)
            return table

        monkeypatch.setattr(js, "_process_table", stale_first_read)

        def forked() -> list[int]:
            text = pids.read_text(encoding="utf-8") if pids.exists() else ""
            return [int(line) for line in text.split() if line.isdigit()]

        try:
            with pytest.raises(subprocess.TimeoutExpired):
                js.run_tree_bounded([sys.executable, "-c", spawner], capture_output=True,
                                    timeout=scaled(CAP_SECONDS))
            assert ready.exists() and forked(), "the child never forked inside the bound, so the case did not run"
            gone_by = time.monotonic() + 5.0
            while any(_alive(pid) for pid in forked()) and time.monotonic() < gone_by:
                time.sleep(0.05)
            alive = [pid for pid in forked() if _alive(pid)]
        finally:
            for pid in forked():
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        # First, so a run starved past the walk's grace before its second read
        # says so, rather than reading as forks the walk left behind.
        assert len(reads) >= 2, (
            f"the walk read the table {len(reads)} time(s) inside its grace: the box was too slow "
            f"for the case to run (or the walk stopped re-reading), {len(alive)} fork(s) left")
        assert not alive, f"{len(alive)} of {len(forked())} forks outlived the tree kill: {alive[:5]}"

    def test_a_child_the_caller_holds_is_ended_with_its_tree_at_the_timeout(self, tmp_path):
        """``communicate_tree_bounded``: the timeout of a ``communicate`` on a
        ``Popen`` the caller started ends the child's whole tree, then raises
        with what was read; ``communicate`` alone raises and leaves it all
        running."""
        js = _load_json_safe()
        argv, pidfile, done = _holder(tmp_path)
        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                 text=True, encoding="utf-8")
        try:
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                js.communicate_tree_bounded(child, timeout=scaled(CAP_SECONDS))
            returned_first = not done.exists()
            gone = self._gone(pidfile)
        finally:
            _end_holder(pidfile)
            child.kill()
            child.wait(timeout=10)
        assert returned_first, "the call waited for the holder's sleep"
        assert gone, "the held child's grandchild outlived the timeout"
        assert caught.value.stdout == "1\n", caught.value.stdout


class _SignalRecorder:
    """``os`` for the walk under test, with every signal recorded and none sent.

    The walk signals whatever pid its table names, and these tables are made
    up: their pids sit above any host's pid ceiling, and nothing is sent to
    them either. ``refuse`` names the pids whose stop fails as a process that
    is not ours fails; ``interrupt_at`` raises ``KeyboardInterrupt`` at that
    stop (1-based), as a Ctrl-C landing mid-walk would."""

    def __init__(self, groups: dict[int, int], *, refuse: tuple[int, ...] = (), interrupt_at: int = 0) -> None:
        self.groups, self.refuse, self.interrupt_at = groups, refuse, interrupt_at
        self.stopped: list[int] = []
        self.killed: list[int] = []
        self.group_kills: list[int] = []
        self._stops = 0

    def __getattr__(self, name: str):
        return getattr(os, name)

    def kill(self, pid: int, sig: int) -> None:
        import signal

        if sig == signal.SIGSTOP:
            self._stops += 1
            if self._stops == self.interrupt_at:
                raise KeyboardInterrupt
            if pid in self.refuse:
                raise PermissionError(1, "Operation not permitted")
            self.stopped.append(pid)
        elif sig == signal.SIGKILL:
            self.killed.append(pid)

    def killpg(self, group: int, sig: int) -> None:
        self.group_kills.append(group)

    def getpgid(self, pid: int) -> int:
        if pid == 0:
            return os.getpgid(0)
        if pid not in self.groups:
            raise ProcessLookupError(3, "No such process")
        return self.groups[pid]


@pytest.mark.skipif(os.name == "nt", reason="the process-table walk is the POSIX kill")
class TestTheWalkSignalsOnlyItsOwnTree:
    """``_json_safe._end_the_whole_tree`` on a scripted table, every signal
    recorded (``_SignalRecorder``): it walks only a child that is unreaped and
    whose parent the table names as this process, since a reaped pid may
    already be another process's; the fallback kill of the child's group runs
    only where the table could not be read at all, never where it named
    another parent; and a pid joins the set it kills just before its stop and
    leaves it when the stop fails, so a failed stop is never followed by a
    kill, and an interrupt mid-walk still kills every pid that may be
    stopped."""

    CHILD, GRANDCHILD = 5_000_001, 5_000_002  # above every host's pid ceiling

    def _walk(self, monkeypatch, *, returncode, parent, recorder_kw=None, child_leads=False, readable=True,
              reaped_by_the_read=False):
        """The walk with a scripted table: ``child_leads`` puts the child at the
        head of a group of its own (else in this process's), ``readable``
        False makes every table read fail, as a host with no ``ps`` does, and
        ``reaped_by_the_read`` has the child reaped while the read runs, as a
        wait on another thread would."""
        js = _load_json_safe()
        me, mine = os.getpid(), os.getpgid(0)
        child_group = self.CHILD if child_leads else mine
        table = {me: (1, mine), self.CHILD: (parent, child_group), self.GRANDCHILD: (self.CHILD, child_group)}
        recorder = _SignalRecorder({pid: group for pid, (_ppid, group) in table.items()}, **(recorder_kw or {}))
        kills: list[str] = []
        proc = type("Proc", (), {"pid": self.CHILD, "returncode": returncode,
                                 "kill": lambda _self: kills.append("kill")})()

        def read(_end):
            if reaped_by_the_read:
                proc.returncode = 0
            return dict(table) if readable else None

        monkeypatch.setattr(js, "os", recorder)
        monkeypatch.setattr(js, "_process_table", read)
        return js, proc, recorder, kills

    def test_with_no_table_an_unreaped_child_that_leads_a_group_is_ended_through_it(self, monkeypatch):
        """The fallback path: every read fails and the child leads its own
        group, so the group goes with the child; a child reaped by then (here
        while the failed read ran) is not read for a group at all, since its
        pid may be another process's now."""
        js, proc, recorder, kills = self._walk(monkeypatch, returncode=None, parent=os.getpid(),
                                               child_leads=True, readable=False)
        js._end_the_whole_tree(proc, time.monotonic() + 2.0)
        assert (recorder.stopped, recorder.killed, recorder.group_kills) == ([], [], [self.CHILD]), vars(recorder)
        assert kills == ["kill"]
        monkeypatch.undo()
        js, proc, recorder, kills = self._walk(monkeypatch, returncode=None, parent=os.getpid(),
                                               child_leads=True, readable=False, reaped_by_the_read=True)
        js._end_the_whole_tree(proc, time.monotonic() + 2.0)
        assert (recorder.stopped, recorder.killed, recorder.group_kills) == ([], [], []), vars(recorder)
        assert kills == ["kill"]

    def test_a_child_the_table_names_under_another_parent_is_not_ended_through_its_group(self, monkeypatch):
        """The table answered, and named a parent other than this process: the
        pid may have been reaped elsewhere and reused by a process that leads
        a group of its own, so no group is killed, though the pid leads one."""
        js, proc, recorder, kills = self._walk(monkeypatch, returncode=None, parent=1, child_leads=True)
        js._end_the_whole_tree(proc, time.monotonic() + 2.0)
        assert (recorder.stopped, recorder.killed, recorder.group_kills) == ([], [], []), vars(recorder)
        assert kills == ["kill"]

    def test_a_reaped_child_or_one_this_process_did_not_start_is_never_walked(self, monkeypatch):
        for returncode, parent, why in ((0, os.getpid(), "reaped"), (None, 1, "another process's child")):
            js, proc, recorder, kills = self._walk(monkeypatch, returncode=returncode, parent=parent)
            js._end_the_whole_tree(proc, time.monotonic() + 2.0)
            assert (recorder.stopped, recorder.killed, recorder.group_kills) == ([], [], []), (why, vars(recorder))
            assert kills == ["kill"], why
            monkeypatch.undo()
        js, proc, recorder, kills = self._walk(monkeypatch, returncode=None, parent=os.getpid())
        js._end_the_whole_tree(proc, time.monotonic() + 2.0)
        assert sorted(recorder.stopped) == sorted(recorder.killed) == [self.CHILD, self.GRANDCHILD], vars(recorder)

    def test_a_stop_that_failed_is_never_followed_by_a_kill(self, monkeypatch):
        js, proc, recorder, _kills = self._walk(monkeypatch, returncode=None, parent=os.getpid(),
                                                recorder_kw={"refuse": (self.GRANDCHILD,)})
        js._end_the_whole_tree(proc, time.monotonic() + 2.0)
        assert recorder.killed == [self.CHILD], vars(recorder)

    def test_an_interrupt_mid_walk_still_kills_what_was_stopped(self, monkeypatch):
        """The interrupt lands on the second stop: the first pid was stopped,
        and the second may have been (a signal landing just after its stop),
        so both are killed."""
        js, proc, recorder, kills = self._walk(monkeypatch, returncode=None, parent=os.getpid(),
                                               recorder_kw={"interrupt_at": 2})
        with pytest.raises(KeyboardInterrupt):
            js._end_the_whole_tree(proc, time.monotonic() + 2.0)
        assert len(recorder.stopped) == 1, vars(recorder)
        assert sorted(recorder.killed) == [self.CHILD, self.GRANDCHILD], vars(recorder)
        assert kills == ["kill"]


class TestTheTreeBoundedRunsWindowsBranch:
    """``run_tree_bounded``'s Windows arm, driven on every OS with a stand-in
    ``Popen`` and the platform read as ``win32`` (as ``TestEveryCopysWindowsBranch``
    drives ``run_bounded``'s): the child goes into the kill-on-close job object
    (a child the caller holds, at ``communicate_tree_bounded``'s entry), the
    kill is ``_end_the_tree_now`` with that job (``taskkill /T`` then
    ``TerminateJobObject``), and a child already reaped is ended through the
    job alone, never ``taskkill`` by a pid that may be another process's now."""

    @pytest.fixture
    def windows(self, monkeypatch):
        js = _load_json_safe()
        calls: list[tuple] = []
        StandInPopen = _stand_in_popen(calls)
        as_os(monkeypatch, "windows", os_name=False)
        monkeypatch.setattr(subprocess, "Popen", StandInPopen)
        monkeypatch.setattr(js, "_kill_on_close_job", lambda proc: calls.append(("job", proc.pid)) or 77)
        monkeypatch.setattr(js, "_end_the_tree_now", lambda proc, job, end: calls.append(("end_the_tree_now", job)))
        monkeypatch.setattr(js, "_terminate_job", lambda job: calls.append(("terminate_job", job)))
        return js, StandInPopen, calls

    def test_the_child_joins_the_job_and_the_timeout_ends_the_tree_then_the_job(self, windows):
        js, popen, calls = windows
        popen.plan = ["timeout", 0]
        with pytest.raises(subprocess.TimeoutExpired):
            js.run_tree_bounded(["git", "log"], timeout=3, capture_output=True, text=True, encoding="utf-8")
        assert [c[0] for c in calls] == ["popen", "job", "communicate", "end_the_tree_now", "communicate", "wait"], calls
        assert ("end_the_tree_now", 77) in calls, calls

    def test_a_child_the_caller_holds_joins_the_job_at_entry_and_the_timeout_ends_the_tree_then_the_job(
            self, windows):
        """``communicate_tree_bounded``: a ``Popen`` the caller started goes
        into the job before the wait, so its kill has the job behind the
        ``taskkill /T`` walk, as ``run_tree_bounded``'s does."""
        js, popen, calls = windows
        held = popen(["git", "log"])
        calls.clear()
        popen.plan = ["timeout", 0]
        with pytest.raises(subprocess.TimeoutExpired):
            js.communicate_tree_bounded(held, timeout=3)
        assert [c[0] for c in calls] == ["job", "communicate", "end_the_tree_now", "communicate", "wait"], calls
        assert ("end_the_tree_now", 77) in calls, calls

    def test_a_reaped_child_is_ended_through_its_job_alone(self, windows):
        js, popen, calls = windows
        reaped = popen(["git", "log"])
        reaped.returncode = 0
        calls.clear()
        js._end_the_whole_tree(reaped, time.monotonic() + 2.0, 77)
        assert calls == [("terminate_job", 77)], calls


def _load_script(rel: str):
    """A ``scripts/`` module by path, registered so its dataclasses resolve."""
    name = "_bound_" + rel.replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, str(TOOLS_CC.parents[1] / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestAWatchdogEndsTheTree:
    """The same defect in the shape no census reads: a parent that streams its
    child's pipe line by line under a watchdog thread. A watchdog that kills
    only the child leaves the loop reading while a grandchild holds the pipe,
    on Windows (a venv's ``python.exe`` is a redirector, so the real
    interpreter is already a grandchild) and on POSIX (the tier's pytest
    outlives a killed parent). Both watchdogs end the whole tree."""

    def test_the_fresh_clone_gates_leg_bound_ends_the_tier(self, tmp_path):
        """``scripts/fresh_clone_gate.py::run_tier``: a leg past
        ``--leg-timeout`` is refused at the bound, not when the tier ends."""
        gate = _load_script("scripts/fresh_clone_gate.py")
        argv, pidfile, done = _holder(tmp_path)
        clone = tmp_path / "clone"
        (clone / "scripts").mkdir(parents=True)
        (clone / "scripts" / "proof_tier.py").write_bytes(
            f"import subprocess\nsubprocess.call({argv!r})\n".encode("utf-8"))
        start = time.monotonic()
        try:
            with pytest.raises(gate.GateRefusal, match="--leg-timeout"):
                gate.run_tier(Path(sys.executable), clone, dict(os.environ), tmp_path / "tier.log",
                              echo=lambda _line: None, timeout_s=CAP_SECONDS)
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the bound, so the case did not run"
        finally:
            _end_holder(pidfile)
        assert returned_first, (
            f"the gate's {CAP_SECONDS:.0f} s leg bound returned only after the holder finished its "
            f"{HOLD_SECONDS} s sleep ({took:.1f} s): the watchdog ended the child, not the tree"
        )

    def test_the_archive_probes_suite_bound_ends_pytest(self, tmp_path):
        """``scripts/archive_probe.py::run_pytest``: pytest past the suite bound
        is ended with everything it started."""
        probe = _load_script("scripts/archive_probe.py")
        argv, pidfile, done = _holder(tmp_path)
        target = tmp_path / "target"
        target.mkdir()
        (target / "test_hold.py").write_bytes(
            f"import subprocess\n\ndef test_hold():\n    subprocess.call({argv!r})\n".encode("utf-8"))
        bound = 3 * CAP_SECONDS  # pytest's own start-up comes first
        start = time.monotonic()
        try:
            rc = probe.run_pytest(Path(sys.executable), target,
                                  ["-q", "-s", "-p", "no:cacheprovider", "test_hold.py"],
                                  dict(os.environ), timeout_s=bound, echo=lambda _line: None)
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the bound, so the case did not run"
        finally:
            _end_holder(pidfile)
        assert rc == probe.EXIT_TIMEOUT, rc
        assert returned_first, (
            f"the probe's {bound:.0f} s suite bound returned only after the holder finished its "
            f"{HOLD_SECONDS} s sleep ({took:.1f} s): the watchdog ended pytest, not its tree"
        )


#: The bounded spawn's three copies (``tests/test_contracts.py::
#: TestTheBoundedSpawnTwins`` holds their code equal; this drives each).
_COPIES = ("tools/cc/_json_safe.py", "espalier/_spawn.py", "espalier/scanners/freshness.py")


def _load_copy(rel: str):
    if rel == "espalier/_spawn.py":
        from espalier import _spawn
        return _spawn
    if rel == "espalier/scanners/freshness.py":
        from espalier.scanners import freshness
        return freshness
    spec = importlib.util.spec_from_file_location("json_safe_for_every_copy", str(TOOLS_CC / "_json_safe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stand_in_popen(calls: list) -> type:
    """A ``Popen`` that records what the harness does with it in ``calls`` and
    answers from a ``plan`` the test sets (a return code, ``"timeout"``, or an
    exception to raise). It is a context manager too, so the standard library's
    own ``subprocess.run`` can hold it when the platform is read as POSIX."""

    class StandInPopen:
        plan: list = []

        def __init__(self, args, **kw):
            calls.append(("popen", args, kw))
            self.args, self.pid, self.returncode = args, 4242, None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def poll(self):
            return self.returncode

        def communicate(self, input=None, timeout=None):
            calls.append(("communicate", input, timeout))
            step = StandInPopen.plan.pop(0)
            if isinstance(step, BaseException):
                raise step
            if step == "timeout":
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = step
            return ("out", "err")

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return self.returncode if self.returncode is not None else 1

        def kill(self):
            calls.append(("kill",))

    return StandInPopen


class TestEveryCopysWindowsBranch:
    """Each copy's Windows branch, driven on every OS with a stand-in ``Popen``
    and the platform read as ``win32`` through ``tests/_platform_standin.py``
    (the required cells are Linux, where the call is ``subprocess.run``), the
    tree kill recorded rather than made."""

    @pytest.fixture(params=_COPIES)
    def windows(self, request, monkeypatch):
        mod = _load_copy(request.param)
        calls: list[tuple] = []
        StandInPopen = _stand_in_popen(calls)
        as_os(monkeypatch, "windows", os_name=False)
        monkeypatch.setattr(subprocess, "Popen", StandInPopen)
        monkeypatch.setattr(mod, "_end_tree", lambda proc, end: calls.append(("end_tree", proc.pid)))
        return mod, StandInPopen, calls

    def test_at_the_timeout_the_tree_ends_then_the_pipes_drain_then_the_child_is_reaped(self, windows):
        mod, popen, calls = windows
        popen.plan = ["timeout", 0]
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            mod.run_bounded(["git", "log"], timeout=3, capture_output=True, text=True, encoding="utf-8")
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "communicate", "wait"], calls
        assert calls[0][2]["stdout"] is subprocess.PIPE and calls[0][2]["stderr"] is subprocess.PIPE
        assert calls[1][2] == 3 and calls[3][2] <= mod.SPAWN_KILL_GRACE_SECONDS, calls
        assert (caught.value.stdout, caught.value.stderr) == ("out", "err")

    def test_check_and_the_argument_errors_are_runs_own(self, windows):
        mod, popen, calls = windows
        popen.plan = [2]
        with pytest.raises(subprocess.CalledProcessError) as caught:
            mod.run_bounded(["git"], timeout=3, capture_output=True, check=True)
        assert (caught.value.returncode, caught.value.output) == (2, "out")
        with pytest.raises(ValueError, match="stdin and input"):
            mod.run_bounded(["git"], timeout=3, input="x", stdin=subprocess.PIPE)

    def test_an_interrupt_mid_call_ends_the_tree_and_goes_on(self, windows):
        mod, popen, calls = windows
        popen.plan = [KeyboardInterrupt()]
        with pytest.raises(KeyboardInterrupt):
            mod.run_bounded(["git"], timeout=3)
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "wait"], calls

    def test_a_stand_in_run_is_honoured(self, windows, monkeypatch):
        mod, popen, calls = windows
        seen: list = []

        def fake(args, **kw):
            seen.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake)
        mod.run_bounded(["git"], timeout=3)
        assert seen == [["git"]] and calls == [], (seen, calls)

    @pytest.mark.parametrize("target_os", ["linux", "windows"])
    def test_the_timeout_shape_follows_the_platform_the_harness_reads(self, target_os, monkeypatch):
        """Read as ``windows``, every copy ends the child's whole tree at the
        timeout, drains the pipes and reaps it (the one shape that bounds a
        grandchild holding the pipe, the sharp edge this module exists for);
        read as ``linux``, the call is ``subprocess.run``'s own and the child
        alone is killed. The standard library's ``run`` stays in place on
        purpose: ``_is_stdlib_run`` (``tools/cc/_json_safe.py``, the guard on
        the Windows branch) sends a replaced ``run`` down the run branch at
        BOTH values, so a node observing a fake ``run`` could not tell the two
        apart; only the stand-in ``Popen`` is replaced, and ``run`` holds it as
        its context manager. One node, two platforms, on whatever host runs it:
        this is the adopter-axes registry's proof of the ``target_os/linux`` and
        ``target_os/windows`` cells (tests/_axis_registry.py), so it carries the
        ``target_os`` parameter and no skip, since a Linux cell that skipped the
        Windows shape would prove nothing about it."""
        copies = [(rel, _load_copy(rel)) for rel in _COPIES]  # imported before the platform is faked
        as_os(monkeypatch, target_os, os_name=False)
        for rel, mod in copies:
            calls: list[tuple] = []
            popen = _stand_in_popen(calls)
            popen.plan = ["timeout", 0]
            monkeypatch.setattr(subprocess, "Popen", popen)
            monkeypatch.setattr(mod, "_end_tree", lambda proc, end: calls.append(("end_tree", proc.pid)))
            with pytest.raises(subprocess.TimeoutExpired):
                mod.run_bounded(["git", "log"], timeout=3, capture_output=True, text=True, encoding="utf-8")
            names = [c[0] for c in calls]
            if target_os == "windows":
                assert names == ["popen", "communicate", "end_tree", "communicate", "wait"], (rel, calls)
            else:
                # subprocess.run's own handler: kill the child, then wait (POSIX)
                # or drain (a Windows host); the tree is never ended.
                assert "end_tree" not in names and names[:3] == ["popen", "communicate", "kill"], (rel, calls)


class TestTheEngineWrapperClosesTheChildsStdin:
    """``espalier/_spawn.py::run_no_stdin`` (DEF-928): ``run_bounded`` with the
    child's stdin closed unless the caller feeds it."""

    @pytest.fixture
    def handed(self, monkeypatch):
        from espalier import _spawn
        calls = []
        monkeypatch.setattr(_spawn, "run_bounded", lambda args, **kw: calls.append(kw) or "ran")
        return _spawn.run_no_stdin, calls

    def test_a_child_handed_nothing_gets_a_closed_stdin(self, handed):
        run_no_stdin, calls = handed
        assert run_no_stdin(["git", "log"], timeout=5) == "ran"
        assert calls == [{"input": None, "stdin": subprocess.DEVNULL, "timeout": 5}]

    def test_a_stdin_of_none_counts_as_none_given(self, handed):
        run_no_stdin, calls = handed
        run_no_stdin(["git", "log"], stdin=None)
        assert calls == [{"input": None, "stdin": subprocess.DEVNULL}]

    def test_a_stdin_the_caller_gives_is_left_as_given(self, handed):
        run_no_stdin, calls = handed
        run_no_stdin(["git", "log"], stdin=subprocess.PIPE)
        assert calls == [{"input": None, "stdin": subprocess.PIPE}]

    def test_a_child_fed_input_gets_no_stdin_of_the_wrappers(self, handed):
        """The two engine spawns that feed their child keep feeding it."""
        run_no_stdin, calls = handed
        run_no_stdin(["git", "hash-object", "--stdin"], input="body")
        assert calls == [{"input": "body"}]

    def test_the_child_reads_end_of_file_at_once(self):
        """A real child: the stdin it is handed is empty and closed, so a read
        returns at once instead of waiting on a pipe the suite holds open."""
        from espalier._spawn import run_no_stdin
        proc = run_no_stdin([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert proc.returncode == 0 and proc.stdout.strip() == "''", (proc.stdout, proc.stderr)


@pytest.mark.skipif(sys.platform != "win32", reason="the handle duplication is Windows's (Popen._get_handles)")
class TestTheWrappersHandleTradeOnWindows:
    """What ``run_no_stdin`` costs (DEF-928, the dispatcher's 3bbff2): a child
    handed a stdin has its stdout and stderr duplicated from the parent, so a
    child that streams to a dead output handle no longer starts, where with all
    three handles left alone it did. Measured, not guarded: a dead stdout with a
    live stdin is not the row's user. A guard that changes this reds here."""

    def test_a_streaming_child_on_a_dead_stdout_starts_bare_and_not_through_the_wrapper(self, tmp_path):
        import json

        out = tmp_path / "trade.json"
        driver = (
            "import ctypes, json, subprocess, sys, _winapi\n"
            "from espalier._spawn import run_no_stdin\n"
            "ctypes.windll.kernel32.SetStdHandle(_winapi.STD_OUTPUT_HANDLE, ctypes.c_void_p(0x0BAD0))\n"
            "seen = {}\n"
            "for name, start in (('bare', lambda: subprocess.run([sys.executable, '-c', 'pass'])),\n"
            "                    ('wrapper', lambda: run_no_stdin([sys.executable, '-c', 'pass']))):\n"
            "    try:\n"
            "        seen[name] = start().returncode\n"
            "    except OSError as exc:\n"
            "        seen[name] = getattr(exc, 'winerror', None)\n"
            "open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps(seen))\n"
        )
        subprocess.run([sys.executable, "-c", driver, str(out)], check=True, stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=30)  # two bare starts, about 1 s; under the 60 s ceiling
        assert json.loads(out.read_text(encoding="utf-8")) == {"bare": 0, "wrapper": 6}


#: A Windows script shim's body: echo one word, CRLF-ended as cmd.exe writes it.
_SHIM_BODY = b"@echo shimmed" + bytes([13, 10])


class TestTheEngineSpawnHandsBackAStartThatFailed:
    """``espalier/_spawn.py::spawn_checked`` (DEF-985): the hooks' contract for
    the engine. argv[0] is resolved first, a program that does not start comes
    back as a ``SpawnFailure``, and what a child that started does still raises
    as it did, so a caller speaks on a start that failed and on nothing else."""

    def test_a_program_on_no_path_comes_back_unresolved(self):
        from espalier._spawn import SpawnFailure, spawn_checked
        got = spawn_checked(["espalier-no-such-program-985"], capture_output=True, timeout=30)
        assert got == SpawnFailure(("espalier-no-such-program-985",), "Unresolved", None)
        assert got.resolution == "`espalier-no-such-program-985` did not resolve to a program"

    def test_an_empty_command_comes_back_empty(self):
        from espalier._spawn import SpawnFailure, spawn_checked
        assert spawn_checked([]) == SpawnFailure((), "EmptyCommand", None)

    def test_a_file_that_is_no_program_resolves_and_still_cannot_start(self, tmp_path):
        """POSIX: not executable, so ``exec`` refuses; Windows: not a program
        ``CreateProcess`` runs. Either way the token resolved, and the failure
        says to what."""
        from espalier._spawn import SpawnFailure, spawn_checked
        notes = tmp_path / "notes.txt"
        notes.write_bytes(b"not a program")
        got = spawn_checked([str(notes)], capture_output=True, timeout=30)
        assert isinstance(got, SpawnFailure) and got.resolved == str(notes), got
        assert got.error not in ("Unresolved", "EmptyCommand") and got.detail, got
        assert got.resolution.endswith("and still could not start"), got.resolution

    def test_an_argument_popen_refuses_comes_back_as_a_start_that_failed(self):
        from espalier._spawn import SpawnFailure, spawn_checked
        got = spawn_checked([sys.executable, "-c", "pass", "a" + chr(0) + "b"], capture_output=True, timeout=scaled(30))
        assert isinstance(got, SpawnFailure) and got.error == "ValueError", got

    def test_a_child_that_ran_and_answered_no_is_the_callers_answer(self):
        """A non-git tree's ``git`` exits 128: it started, so no failure."""
        from espalier._spawn import spawn_checked
        got = spawn_checked([sys.executable, "-c", "raise SystemExit(3)"], capture_output=True, timeout=scaled(30))
        assert isinstance(got, subprocess.CompletedProcess) and got.returncode == 3, got

    def test_a_check_exit_still_raises(self):
        from espalier._spawn import spawn_checked
        with pytest.raises(subprocess.CalledProcessError):
            spawn_checked([sys.executable, "-c", "raise SystemExit(3)"], capture_output=True, check=True,
                          timeout=scaled(30))

    def test_output_that_does_not_decode_still_raises(self, monkeypatch):
        """A ``UnicodeDecodeError`` is a ``ValueError``, and the child that
        printed it ran: it propagates, never a start that failed. Faked at the
        bounded spawn, because on Windows with a timeout CPython decodes in
        ``communicate``'s reader thread and the error never reaches the caller
        at all."""
        from espalier import _spawn

        def undecodable(args, **kw):
            raise UnicodeDecodeError("utf-8", bytes([255]), 0, 1, "invalid start byte")

        monkeypatch.setattr(_spawn, "run_bounded", undecodable)
        with pytest.raises(UnicodeDecodeError):
            _spawn.spawn_checked([sys.executable, "-c", "pass"], capture_output=True, text=True, encoding="utf-8",
                                 timeout=scaled(30))

    def test_a_timeout_still_raises(self):
        from espalier._spawn import spawn_checked
        with pytest.raises(subprocess.TimeoutExpired):
            spawn_checked([sys.executable, "-c", "import time; time.sleep(60)"], capture_output=True, timeout=scaled(1))

    def test_the_child_gets_a_closed_stdin_and_the_resolved_program(self, monkeypatch):
        from espalier import _spawn
        calls = []
        monkeypatch.setattr(_spawn, "run_bounded", lambda args, **kw: calls.append((args, kw)) or "ran")
        assert _spawn.spawn_checked(["git", "log"], timeout=5) == "ran"
        assert calls == [([_spawn.resolve_program("git"), "log"],
                          {"input": None, "stdin": subprocess.DEVNULL, "timeout": 5})]
        assert os.path.isabs(calls[0][0][0]), calls

    def test_a_program_in_the_current_directory_is_not_resolved(self, tmp_path, monkeypatch):
        """``shutil.which`` searches the current directory first on Windows, so
        a ``git.cmd`` a cloned tree carries would run where ``CreateProcess``
        never looked (the code review of 2026-11-17): the engine looks on PATH
        alone, and a relative PATH entry is skipped as the same place."""
        from espalier import _spawn
        from tests._stubs import write_stub
        name = "planted985"
        write_stub(tmp_path / (name + ".cmd" if os.name == "nt" else name),
                   "@echo planted" if os.name == "nt" else "#!/bin/sh\necho planted", crlf=os.name == "nt")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", os.pathsep.join([".", "", os.environ.get("PATH", "")]))
        assert _spawn.resolve_program(name) is None
        got = _spawn.spawn_checked([name], capture_output=True, timeout=scaled(30))
        assert isinstance(got, _spawn.SpawnFailure) and got.error == "Unresolved", got

    @pytest.mark.parametrize("clash", [
        {"input": "x", "stdin": subprocess.DEVNULL},
        {"capture_output": True, "stdout": subprocess.DEVNULL},
    ], ids=["input-with-stdin", "capture-with-stdout"])
    def test_a_callers_keyword_clash_raises_and_is_no_start_that_failed(self, clash):
        from espalier._spawn import spawn_checked
        with pytest.raises(ValueError):
            spawn_checked(["git", "log"], **clash)

    def test_the_contract_reads_as_the_hooks_copy_does(self):
        """The engine's copy and ``tools/cc/hooks/_hook_utils.py``'s are held
        to the same shim refusal and the same sentences, so a fix to one
        reaches the other. They parted twice until DEF-2102 brought the hooks'
        copy to the engine's reading: a bare name is never resolved in the
        current directory (the lookup below is one function in both trees),
        and a decode error is a child that ran (each copy's own test drives
        it). What still differs is the signature: the hooks resolve a path
        token against the root they are handed, the engine against ``cwd``."""
        from espalier import _spawn
        hooks = _load_hook_utils()
        assert _spawn._CMD_SHIM_METACHARS == hooks._CMD_SHIM_METACHARS
        for args in [((), "EmptyCommand", None), (("git",), "Unresolved", None),
                     (("npm", "a&b"), "CmdShimMetachar", "C:/x/npm.cmd"),
                     (("git",), "FileNotFoundError", "/usr/bin/git", "[Errno 2] gone")]:
            assert _spawn.SpawnFailure(*args).resolution == hooks.SpawnFailure(*args).resolution, args

    def test_the_path_lookup_is_one_function_in_both_trees(self):
        """``_on_path`` is copied, since ``espalier/`` imports nothing from
        ``tools/cc/``: compared as parsed code, its docstring included, so a fix
        to the lookup in one tree that the other misses reds here (DEF-2102:
        the hooks' copy had kept ``shutil.which`` and its current-folder
        search after the engine's moved off it)."""
        import ast

        def lookup(path: Path) -> str:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_on_path"]
            assert len(found) == 1, f"{path}: one module-level _on_path, found {len(found)}"
            return ast.dump(found[0])

        engine = lookup(TOOLS_CC.parents[1] / "espalier" / "_spawn.py")
        assert lookup(TOOLS_CC / "hooks" / "_hook_utils.py") == engine, (
            "tools/cc/hooks/_hook_utils.py::_on_path differs from espalier/_spawn.py::_on_path: "
            "make the same change in both (the hooks' copy is imported by write_guard on every "
            "tool call, so rehearse its edit in a scratch clone first), then run "
            "scripts/sync_vendor_cc.py for the vendored copy")

    def test_both_copies_refuse_a_program_the_current_folder_holds(self, tmp_path, monkeypatch):
        """The two resolvers driven on one planted tree: each finds nothing
        for a bare name the current folder holds, with ``.`` and an empty
        entry on PATH, and each finds the same file once its folder is an
        absolute PATH entry."""
        from espalier import _spawn
        from tests._stubs import write_stub
        hooks = _load_hook_utils()
        name = "twin2102"
        here = tmp_path / "project"
        here.mkdir()
        write_stub(here / (name + ".cmd" if os.name == "nt" else name),
                   "@echo planted" if os.name == "nt" else "#!/bin/sh\necho planted", crlf=os.name == "nt")
        monkeypatch.chdir(here)
        monkeypatch.setenv("PATH", os.pathsep.join([".", "", os.environ.get("PATH", "")]))
        assert (_spawn.resolve_program(name), hooks.resolve_program(name, root=here)) == (None, None)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", os.pathsep.join([str(here), os.environ.get("PATH", "")]))
        engine, hook = _spawn.resolve_program(name), hooks.resolve_program(name, root=here)
        assert engine and engine == hook, (engine, hook)

    @pytest.mark.skipif(sys.platform != "win32", reason="PATHEXT and the .cmd shim are Windows's")
    def test_a_cmd_shim_starts_where_a_bare_spawn_cannot_find_it(self, tmp_path, monkeypatch):
        """``npm`` is ``npm.cmd``: ``subprocess`` alone looks for an .exe and
        raises, ``shutil.which`` honours PATHEXT and finds the shim."""
        from espalier._spawn import spawn_checked
        (tmp_path / "shim985.cmd").write_bytes(_SHIM_BODY)
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        with pytest.raises(FileNotFoundError):
            subprocess.run(["shim985"], capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
        got = spawn_checked(["shim985"], capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert isinstance(got, subprocess.CompletedProcess) and got.stdout.strip() == "shimmed", got

    @pytest.mark.skipif(sys.platform != "win32", reason="PATHEXT and the .cmd shim are Windows's")
    def test_a_cmd_shim_with_a_metacharacter_argument_is_refused(self, tmp_path, monkeypatch):
        from espalier._spawn import spawn_checked
        (tmp_path / "shim985.cmd").write_bytes(_SHIM_BODY)
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
        got = spawn_checked(["shim985", "a&b"], capture_output=True, timeout=30)
        assert got.error == "CmdShimMetachar" and got.resolved.lower().endswith("shim985.cmd"), got


class TestTheEngineSaysOnceThatAProgramNeverStarted:
    """``espalier/_spawn.py::say_unstarted`` (DEF-985): one line on stderr per
    program per process, naming the program, how it failed and what the caller
    answers in its place; a stream that cannot take it costs the caller nothing."""

    @pytest.fixture(autouse=True)
    def fresh(self, monkeypatch):
        from espalier import _spawn
        monkeypatch.setattr(_spawn, "_SAID_UNSTARTED", set())

    def test_the_line_names_the_program_and_what_answers_in_its_place(self, capsys):
        from espalier._spawn import SpawnFailure, say_unstarted
        say_unstarted(SpawnFailure(("git", "ls-files"), "Unresolved", None), "the tracked set reads empty")
        err = capsys.readouterr().err
        assert err == "espalier: `git` did not resolve to a program, so the tracked set reads empty\n", err

    def test_a_second_failure_of_the_same_program_says_nothing_and_another_program_does(self, capsys):
        from espalier._spawn import SpawnFailure, say_unstarted
        say_unstarted(SpawnFailure(("git", "a"), "Unresolved", None), "one")
        say_unstarted(SpawnFailure(("git", "b"), "FileNotFoundError", "/x/git", "[Errno 2] gone"), "two")
        say_unstarted(SpawnFailure(("rg",), "Unresolved", None), "three")
        lines = capsys.readouterr().err.splitlines()
        assert [ln.split(",", 1)[0] for ln in lines] == [
            "espalier: `git` did not resolve to a program", "espalier: `rg` did not resolve to a program"], lines

    def test_a_failure_that_raised_carries_its_detail(self, capsys):
        from espalier._spawn import SpawnFailure, say_unstarted
        say_unstarted(SpawnFailure(("git",), "PermissionError", "/opt/git", "[Errno 13] Permission denied: /opt/git"),
                      "the branch reads main")
        assert capsys.readouterr().err.startswith(
            "espalier: `git` resolved to `/opt/git` and still could not start "
            "([Errno 13] Permission denied: /opt/git), so the branch reads main\n")

    def test_a_path_the_stream_cannot_encode_is_escaped_not_raised(self, monkeypatch):
        from espalier import _spawn

        class _Cp1252Console:
            """A stock Windows console's stream: it encodes strictly, so a
            character outside its code page raises at the write."""
            encoding = "cp1252"

            def __init__(self):
                self.raw = bytearray()

            def write(self, text):
                self.raw += text.encode(self.encoding)

            def flush(self):
                pass

        stream = _Cp1252Console()
        monkeypatch.setattr(_spawn.sys, "stderr", stream)
        word = chr(0x436)  # outside cp1252
        _spawn.say_unstarted(_spawn.SpawnFailure(("git",), "Unresolved", None), word + " reads empty")
        escaped = word.encode("cp1252", "backslashreplace").decode("cp1252")
        assert escaped[0] == chr(92) and escaped != word
        assert bytes(stream.raw).decode("cp1252").startswith(
            "espalier: `git` did not resolve to a program, so " + escaped + " reads empty")

    @pytest.mark.parametrize("closed", [True, False], ids=["no-stderr", "stderr-raises"])
    def test_a_stream_that_cannot_take_the_line_costs_the_caller_nothing(self, monkeypatch, closed):
        from espalier import _spawn

        class _Closed:
            encoding = "utf-8"

            def write(self, text):
                raise ValueError("I/O operation on closed file.")

        monkeypatch.setattr(_spawn.sys, "stderr", None if closed else _Closed())
        _spawn.say_unstarted(_spawn.SpawnFailure(("git",), "Unresolved", None), "the tracked set reads empty")


def _git_dir(root: Path) -> Path:
    (root / ".git").mkdir(exist_ok=True)
    return root


def _deployed_hook(root: Path, name: str) -> Path:
    hook = root / "tools" / "cc" / "hooks" / name
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes(b"")
    return root


def _frontmatter_at_risk(root: Path, monkeypatch) -> Path:
    from espalier import render_surface
    monkeypatch.setattr(render_surface, "frontmatter_body_paths", lambda repo: [".claude/agents/a.md"])
    monkeypatch.setattr(render_surface, "_read_body_bytes", lambda path: "")
    monkeypatch.setattr(render_surface, "frontmatter_has_crlf", lambda text: False)
    monkeypatch.setattr(render_surface, "frontmatter_hazards",
                        lambda text: [("description", render_surface.FRONTMATTER_FRAGILE, "", "")])
    return root


def _bound_paths(monkeypatch) -> None:
    from espalier import freshness
    monkeypatch.setattr(freshness, "_pinned_bound_paths", lambda repo: ["x.py"])
    monkeypatch.setattr(freshness, "_pinned_marker_paths", lambda repo: [])


def _workflow_on_disk(root: Path) -> Path:
    from espalier import fuse
    workflow = root / fuse._WORKFLOW_REL
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_bytes(b"name: x")
    return root


def _root_markdown(root: Path) -> Path:
    (root / "a.md").write_bytes(b"# a")
    return root


def _site(name: str):
    import importlib
    module, _, attr = name.rpartition(".")
    return getattr(importlib.import_module("espalier." + module), attr)


#: Each engine site that answers in place of a program that never started
#: (DEF-985): its name under ``espalier.``, the call (tmp_path, monkeypatch),
#: the answer it gives in the program's place, and words of what it says. The
#: answer is the one each site gave before the contract on a missing program:
#: the contract adds the line. Three sites answer where they used to raise (a
#: PermissionError at ``detect_git_conventions``, a ValueError at
#: ``_pinned_bound_changed_since`` and ``_tracked_dirs``): the permissive side.
_ENGINE_SITES = [
    ("analyze.detect_head_sha", lambda t, m: _site("analyze.detect_head_sha")(t), "", "records no head commit"),
    ("analyze.detect_git_conventions",
     lambda t, m: _site("analyze.detect_git_conventions")(t)["format"], "freeform", "reads as freeform"),
    ("cli._git_covered_entries",
     lambda t, m: _site("cli._git_covered_entries")(t / ".gitignore", ("reports/",), fold=False), None,
     "already cover is not asked of git"),
    ("cli._git_ignorecase", lambda t, m: _site("cli._git_ignorecase")(t), False, "case folding reads as off"),
    ("cli._untracked_conflicts",
     lambda t, m: (m.setattr(__import__("espalier.cli").cli, "_git_ignorecase", lambda repo: False),
                   _site("cli._untracked_conflicts")(t, ["task-packs/"]))[1], {}, "no uncommitted file"),
    ("cli._git_tracked", lambda t, m: _site("cli._git_tracked")(t), None, "no tracked file is checked"),
    ("cli._ignored_files_under", lambda t, m: _site("cli._ignored_files_under")(t, "task-packs"), None,
     "retiring the task-packs/ rule"),
    ("cli._git_hides", lambda t, m: _site("cli._git_hides")(t, ".worktreeinclude"), False,
     ".worktreeinclude reads as not ignored"),
    ("cli._git_ignored", lambda t, m: _site("cli._git_ignored")(_git_dir(t), ["a"]), None, "harness paths"),
    ("doctor._probe_deployed_stop_gate",
     lambda t, m: _site("doctor._probe_deployed_stop_gate")(_deployed_hook(t, "stop_gate.py")), None,
     "deployed stop gate"),
    ("doctor._probe_recall_corpus",
     lambda t, m: _site("doctor._probe_recall_corpus")(_deployed_hook(t, "_recall.py")), {"error": "no_answer"},
     "recall corpus as not readable"),
    ("doctor._check_frontmatter_line_endings",
     lambda t, m: _site("doctor._check_frontmatter_line_endings")(_frontmatter_at_risk(t, m)), [],
     "LF line endings"),
    ("freshness._git_head_sha_quiet", lambda t, m: _site("freshness._git_head_sha_quiet")(t), None,
     "cache reads as stale"),
    ("freshness._git_is_ancestor_within_n",
     lambda t, m: _site("freshness._git_is_ancestor_within_n")("a" * 40, "HEAD", n=5, cwd=t), False,
     "off this branch"),
    ("freshness._pinned_bound_changed_since",
     lambda t, m: (_bound_paths(m), _site("freshness._pinned_bound_changed_since")(t, "a" * 40))[1], True,
     "cache reads as stale"),
    ("fuse._tracked_files", lambda t, m: _site("fuse._tracked_files")(t), None, "no git repository"),
    ("fuse._workflow_tracked", lambda t, m: _site("fuse._workflow_tracked")(_workflow_on_disk(t)), None,
     "fused CI workflow"),
    ("fuse._run_in_fusion", lambda t, m: _site("fuse._run_in_fusion")(t, [sys.executable, "-c", "pass"]), None,
     "reports no exit code"),
    ("pre_release._parity_runnable", lambda t, m: _site("pre_release._parity_runnable")(), False,
     "not runnable here"),
    ("reflect_protocol._tracked_root_markdown",
     lambda t, m: _site("reflect_protocol._tracked_root_markdown")(_root_markdown(t)), ["a.md"], "on disk"),
    ("worktree._git_branch", lambda t, m: _site("worktree._git_branch")(t), "main", "base branch reads as main"),
    ("zone_writes._tracked_dirs", lambda t, m: _site("zone_writes._tracked_dirs")(_git_dir(t), ["tools/cc/"]),
     frozenset(), "without git's tracked set"),
]

#: The stdlib-only freshness scanner's git reads, through its own copy of the
#: bounded spawn and its own form of the line.
_SCANNER_SITES = [
    ("_git_log_name_only", lambda sf, t: sf._git_log_name_only(t, "a" * 40, ["x.py"]), {},
     "touching its bound files"),
    ("_place_symbol", lambda sf, t: sf._place_symbol(t, "x.py", "f"), (None, "git did not answer"), "not placed"),
    ("_git_log_symbol_commits", lambda sf, t: sf._git_log_symbol_commits(t, "a" * 40, "x.py", (1, 2)), None,
     "commits since its pin"),
    ("_git_status_dirty", lambda sf, t: sf._git_status_dirty(t, ["x.py"]), {}, "uncommitted change"),
    ("_git_diff_old_ranges", lambda sf, t: sf._git_diff_old_ranges(t, "x.py"), None, "working-tree change"),
    ("_manifest_fragments_at_head", lambda sf, t: sf._manifest_fragments_at_head(t), None, "not at HEAD"),
    ("_head_sha", lambda sf, t: sf._head_sha(t), "", "records no head commit"),
]


def _never_starts(args, **kwargs):
    raise FileNotFoundError(2, "No such file or directory")


def _said(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("espalier: ")]


class TestEveryEngineSiteSaysAProgramThatNeverStarted:
    """DEF-985's user: an adopter whose ``git`` is missing or shimmed reads an
    empty, all-clear answer from ``init``, ``doctor``, ``analyze`` or
    ``freshness``, because a spawn that never started fell into a handler that
    said nothing. Each site now says it, once, on stderr, and gives the answer
    it gave before. A child that ran and answered no (a non-git tree's ``git``
    exits 128) says nothing. The census in ``tests/test_contracts.py``
    (``TestNoEngineSpawnFailsToStartInSilence``) holds the population; this
    drives each member. The memo is reset with ``raising=False`` so this file
    laid over the tree before the contract reds on the missing line, not on a
    missing name."""

    @pytest.fixture(autouse=True)
    def fresh(self, monkeypatch):
        from espalier import _spawn
        from espalier.scanners import freshness as scanner
        monkeypatch.setattr(_spawn, "_SAID_UNSTARTED", set(), raising=False)
        monkeypatch.setattr(scanner, "_SAID_UNSTARTED", set(), raising=False)

    @pytest.mark.parametrize("name,call,answer,words", _ENGINE_SITES, ids=[row[0] for row in _ENGINE_SITES])
    def test_an_engine_site_says_once_and_its_answer_stands(self, tmp_path, monkeypatch, capsys,
                                                            name, call, answer, words):
        from espalier import _spawn
        monkeypatch.setattr(_spawn, "run_bounded", _never_starts)
        assert call(tmp_path, monkeypatch) == answer
        said = _said(capsys.readouterr().err)
        assert len(said) == 1 and words in said[0] and "could not start" in said[0], said

    @pytest.mark.parametrize("name,call,answer,words", _SCANNER_SITES, ids=[row[0] for row in _SCANNER_SITES])
    def test_a_scanner_site_says_once_and_its_answer_stands(self, tmp_path, monkeypatch, capsys,
                                                            name, call, answer, words):
        from espalier.scanners import freshness as scanner
        monkeypatch.setattr(scanner, "run_bounded", _never_starts)
        assert call(scanner, tmp_path) == answer
        said = _said(capsys.readouterr().err)
        assert len(said) == 1 and words in said[0] and "`git` could not start" in said[0], said

    @pytest.mark.parametrize("name,call,answer,words", _ENGINE_SITES, ids=[row[0] for row in _ENGINE_SITES])
    def test_an_engine_site_whose_program_ran_says_nothing(self, tmp_path, monkeypatch, capsys,
                                                           name, call, answer, words):
        """The real program, in a tree that is no repository: git starts and
        answers no, the interpreter starts; none of it is a start that failed."""
        call(tmp_path, monkeypatch)
        assert _said(capsys.readouterr().err) == []

    @pytest.mark.parametrize("name,call,answer,words", _SCANNER_SITES, ids=[row[0] for row in _SCANNER_SITES])
    def test_a_scanner_site_whose_git_ran_says_nothing(self, tmp_path, capsys, name, call, answer, words):
        from espalier.scanners import freshness as scanner
        call(scanner, tmp_path)
        assert _said(capsys.readouterr().err) == []

    @pytest.mark.parametrize("raised", [
        subprocess.TimeoutExpired(["git"], 30),
        UnicodeDecodeError("utf-8", bytes([255]), 0, 1, "invalid start byte"),
    ], ids=["timeout", "undecodable"])
    def test_a_scanner_git_that_started_and_then_failed_says_nothing(self, tmp_path, monkeypatch, capsys, raised):
        """The scanner reads the exception, so its own type check is the line
        between a start that failed and a child that ran: a timeout and output
        that did not decode are the second, and keep the scan's old answer."""
        from espalier.scanners import freshness as scanner

        def started_then_failed(args, **kwargs):
            raise raised

        monkeypatch.setattr(scanner, "run_bounded", started_then_failed)
        assert scanner._head_sha(tmp_path) == ""
        assert _said(capsys.readouterr().err) == []

    def test_a_git_on_no_path_is_named_as_unresolved(self, tmp_path, monkeypatch, capsys):
        """The anchor, with nothing faked: PATH holds no git, so the lane
        plan's branch read never starts, and the line says why."""
        from espalier.worktree import _git_branch
        empty = tmp_path / "empty-path"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert _git_branch(tmp_path) == "main"
        assert _said(capsys.readouterr().err) == [
            "espalier: `git` did not resolve to a program, so the lane plan's base branch reads as main"]

    def test_a_fresh_process_says_it_with_the_memo_as_shipped(self, tmp_path):
        """Nothing faked and nothing reset: a new interpreter with no git on
        PATH, so a memo that ships holding a program (a debug edit that
        "quiets the noise") reds here, where every in-process test resets it
        first (the failure-mode review of 2026-11-17)."""
        empty = tmp_path / "empty-path"
        empty.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "PATH"}
        env["PATH"] = str(empty)
        done = subprocess.run(
            [sys.executable, "-c", "from espalier.worktree import _git_branch; print(_git_branch('.'))"],
            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=scaled(30))  # one import and one spawn, about a second
        assert done.stdout.strip() == "main", done.stdout + done.stderr
        assert _said(done.stderr) == [
            "espalier: `git` did not resolve to a program, so the lane plan's base branch reads as main"], done.stderr

    def test_the_driven_sites_are_every_checked_spawn(self):
        """The table above is kept by hand; it is held to the engine's own
        ``spawn_checked`` callers, so a new one is driven too (the
        failure-mode review of 2026-11-17)."""
        from tests.test_spawn_chokepoint import spawn_sites
        engine = Path(__file__).resolve().parents[1] / "espalier"
        callers = {
            f"{site['file'][:-3].replace('/', '.')}.{site['function']}"
            for site in spawn_sites(engine, "**/*.py")
            if site["callee"] == "spawn_checked" and site["file"] != "_spawn.py"
            and not site["file"].startswith("_vendor/")
        }
        assert callers == {row[0] for row in _ENGINE_SITES}, sorted(callers ^ {row[0] for row in _ENGINE_SITES})
