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


class TestTheTreeBoundedRunEndsTheWholeTree:
    """``_json_safe.run_tree_bounded``: ``run_bounded`` whose timeout, and any
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
