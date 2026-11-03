"""CP-KILL (DEF-4078): a kill of a pid another checkout of this clone is
running, or one under the box lock's holder for another seat, is nudged once.

On 2026-10-31 the dispatcher's window ended air-work's parallel tier leg by
pid from the root checkout, having read it from the process table as a stray;
no reader asked whose process it was. The rows drive real children in a temp
clone with a second worktree, through ``_speedbump.check_fired`` as the hook
calls it, and the box-lock rows build their record with the suite's own
writer (``tests/_box_lock.py::build_record``).

The rule the rows pin is the NEAREST process with its working directory in a
checkout (the pid, then its parents): a seat's own child has among its parents
the launcher and terminal that started the seat, whose cwd is the root
checkout, so "any parent" would nudge every kill of one's own run (driven by
air, 2026-11-02, c8e05b).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from tests._git_oracle import _git_env

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _speedbump  # noqa: E402

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="a temp clone is built with git")
posix_only = pytest.mark.skipif(os.name != "posix", reason="the cwd reader is the POSIX arm; Windows reads none")

_SLEEP = "import time; time.sleep(60)"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=_git_env(), timeout=30)


def _clone(tmp_path: Path, worktree: str = ".claude/worktrees/other") -> tuple[Path, Path]:
    """A main checkout and a second worktree of it, the worktree named for a
    seat of its own (``other-seat``) the way SessionStart names one."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.name", "t")
    _git(main, "config", "user.email", "t@t")
    (main / "a.txt").write_text("a\n", encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "a")
    other = main / worktree
    other.parent.mkdir(parents=True, exist_ok=True)
    _git(main, "worktree", "add", "-q", "--detach", str(other))
    _git(other, "config", "extensions.worktreeConfig", "true")
    _git(other, "config", "--worktree", "espalier.machine", "other-seat")
    return main, other


@pytest.fixture
def children():
    """Start children; every one is killed at the test's end."""
    started: list[subprocess.Popen] = []

    def start(cwd: Path, code: str = _SLEEP) -> subprocess.Popen:
        # A group of its own, so a parent's child goes with it at the end: the
        # rows share the box's process table with other seats, and a sleeping
        # orphan at PPID 1 is the shape the reap recipe hunts.
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(cwd), stdout=subprocess.PIPE, text=True,
                                encoding="utf-8", start_new_session=True)
        started.append(proc)
        return proc

    yield start
    # os.killpg and SIGKILL are POSIX names; the box lock's rows run on Windows too.
    killpg = getattr(os, "killpg", None)
    for proc in started:
        try:
            if killpg is None:
                raise OSError("no process groups here")
            killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        proc.wait(timeout=10)
        if proc.stdout is not None:
            proc.stdout.close()


def _parent_with_a_child(start, parent_cwd: Path, child_cwd: Path) -> int:
    """A parent working in ``parent_cwd`` whose child works in ``child_cwd``;
    the child's pid, read from the parent."""
    code = ("import subprocess, sys, time; "
            f"c = subprocess.Popen([sys.executable, '-c', {_SLEEP!r}], cwd={str(child_cwd)!r}); "
            "print(c.pid, flush=True); time.sleep(60); c.kill()")
    parent = start(parent_cwd, code)
    assert parent.stdout is not None
    return int(parent.stdout.readline().strip())


def _fire(root: Path, command: str, tool: str = "Bash"):
    _speedbump._last_kill = None   # a hook run is one process: each call reads afresh
    return _speedbump.check_fired(tool, {"command": command}, root)


@pytest.fixture(autouse=True)
def _no_box_lock(monkeypatch):
    # The developer's own seat may run under a box lock: these rows set their own.
    monkeypatch.delenv("ESPALIER_BOX_LOCK", raising=False)


def _registry(monkeypatch, tmp_path: Path, *, readable: bool) -> None:
    """Point Claude Code's session registry at ``tmp_path``: an empty one
    (read, no session there) or none at all (unread). Left to the host, the
    reason read the developer's own ``~/.claude`` and a CI runner has none."""
    cfg = tmp_path / "cfg"
    (cfg / "sessions").mkdir(parents=True) if readable else cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


@needs_git
@posix_only
class TestAnotherCheckoutsRun:
    @pytest.mark.parametrize("readable, there", [
        (True, "no live Claude session there"),
        (False, "its sessions unread"),
    ])
    def test_a_kill_of_a_pid_working_in_another_checkout_is_nudged_once(self, tmp_path, children, monkeypatch,
                                                                          readable, there):
        _registry(monkeypatch, tmp_path, readable=readable)
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        fired = _fire(main, f"kill -9 {theirs.pid}")
        assert fired is not None and fired[0] == "CP-KILL", fired
        reason = fired[1]
        assert f"pid {theirs.pid} works in .claude/worktrees/other, another checkout of this clone" in reason, reason
        assert "seat other-seat" in reason and there in reason, reason
        assert reason.isascii() and len(reason.encode("utf-8")) <= 512, reason
        assert _fire(main, f"kill -9 {theirs.pid}") is None, "the re-issue proceeds"

    def test_a_kill_of_this_checkouts_own_run_passes(self, tmp_path, children):
        main, _other = _clone(tmp_path)
        mine = children(main)
        time.sleep(0.3)
        assert _fire(main, f"kill {mine.pid}") is None

    def test_the_nearest_checkout_decides_not_any_parent(self, tmp_path, children):
        """A seat's own child under a launcher whose cwd is another checkout
        (the root, for every launched seat) is the seat's own run."""
        main, other = _clone(tmp_path)
        pid = _parent_with_a_child(children, other, main)
        time.sleep(0.3)
        assert _fire(main, f"kill {pid}") is None

    def test_a_run_found_through_its_parent_is_named_by_both_pids(self, tmp_path, children):
        """An xdist worker works in a test's temp folder; its controller works
        in the checkout."""
        main, other = _clone(tmp_path)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        pid = _parent_with_a_child(children, other, scratch)
        time.sleep(0.3)
        fired = _fire(main, f"kill -TERM {pid}")
        assert fired is not None and fired[0] == "CP-KILL", fired
        assert f"pid {pid} runs under pid " in fired[1] and "which works in .claude/worktrees/other" in fired[1]

    def test_the_main_checkout_is_another_checkout_from_a_worktree(self, tmp_path, children):
        main, other = _clone(tmp_path)
        theirs = children(main)
        time.sleep(0.3)
        fired = _fire(other, f"kill {theirs.pid}")
        assert fired is not None and f"pid {theirs.pid} works in the main checkout" in fired[1], fired

    def test_a_mention_a_probe_and_an_unknown_pid_pass(self, tmp_path, children):
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        for command in (f'echo "kill -9 {theirs.pid}"', f"ls  # kill {theirs.pid}", f"kill -0 {theirs.pid}",
                        f"kill -s 0 {theirs.pid}", "kill -l", f"git commit -m 'kill {theirs.pid}'",
                        "kill 2147483646"):
            assert _fire(main, command) is None, command

    def test_a_second_pid_of_another_seat_is_nudged_again(self, tmp_path, children):
        """Keyed per pid: an id-only flag would let a second seat's pid pass
        with no word (air, c8e05b)."""
        main, other = _clone(tmp_path)
        first, second = children(other), children(other)
        time.sleep(0.3)
        assert _fire(main, f"kill {first.pid}") is not None
        assert _fire(main, f"kill {second.pid}") is not None

    def test_a_kill_handed_to_a_shell_is_read(self, tmp_path, children):
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        assert _fire(main, f"bash -c 'kill -9 {theirs.pid}'") is not None

    def test_the_powershell_tool_reads_stop_process(self, tmp_path, children):
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        fired = _fire(main, f"Stop-Process -Id {theirs.pid} -Force", tool="PowerShell")
        assert fired is not None and fired[0] == "CP-KILL", fired
        assert _fire(main, f"Stop-Process -Id {theirs.pid} -WhatIf", tool="PowerShell") is None

    def test_another_signal_to_a_pid_already_nudged_passes(self, tmp_path, children):
        """Keyed per pid, not per spelling: the nudge was about the pid."""
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        assert _fire(main, f"kill -9 {theirs.pid}") is not None
        assert _fire(main, f"kill -TERM {theirs.pid}") is None

    def test_one_check_reads_the_process_table_once(self, tmp_path, children, monkeypatch):
        """The predicate, the reminder and the flag key all ask: one reading."""
        import _hook_utils
        sync = _hook_utils.load_checkout_sync()
        reads: list = []
        real = sync.process_cwds
        monkeypatch.setattr(sync, "process_cwds", lambda *a, **k: reads.append(a) or real(*a, **k))
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        assert _fire(main, f"kill {theirs.pid}") is not None and len(reads) == 1, reads

    def test_every_foreign_pid_of_one_kill_is_named_and_keyed(self, tmp_path, children):
        main, other = _clone(tmp_path)
        first, second = children(other), children(other)
        time.sleep(0.3)
        fired = _fire(main, f"kill {first.pid} {second.pid}")
        assert fired is not None and f"pid {first.pid} (and 1 more named here) works in" in fired[1], fired
        assert _fire(main, f"kill {first.pid} {second.pid}") is None, "the re-issue proceeds"

    def test_a_parent_filtered_kill_is_judged_by_the_children(self, tmp_path, children):
        main, other = _clone(tmp_path)
        parent = children(main, "import subprocess, sys, time; "
                                f"subprocess.Popen([sys.executable, '-c', {_SLEEP!r}], cwd={str(other)!r}); "
                                "print('up', flush=True); time.sleep(60)")
        assert parent.stdout is not None and parent.stdout.readline().strip() == "up"
        time.sleep(0.3)
        fired = _fire(main, f"pkill -P {parent.pid}")
        assert fired is not None and "works in .claude/worktrees/other" in fired[1], fired

    def test_a_parent_kill_wider_than_the_reading_is_nudged(self, tmp_path):
        main, _other = _clone(tmp_path)
        fired = _fire(main, "pkill -P 1")
        assert fired is not None and "pkill -P 1 ends" in fired[1] and "read each one's working directory" in fired[1]

    def test_this_checkouts_run_under_another_seats_lock_is_its_own(self, tmp_path, children, monkeypatch):
        """The nearest checkout decides first; the lock decides only a chain no
        checkout holds (a killed seat's tier recorded on another lane, say)."""
        main, other = _clone(tmp_path)
        lock = tmp_path / "box.lock"
        lock.write_text(json.dumps(_record(other)), encoding="utf-8")
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
        mine = children(main)
        time.sleep(0.3)
        assert _fire(main, f"kill {mine.pid}") is None

    def test_one_checkout_with_no_lock_spawns_nothing(self, tmp_path, monkeypatch):
        import _hook_utils
        sync = _hook_utils.load_checkout_sync()
        monkeypatch.setattr(sync, "_parent_map", lambda *a, **k: pytest.fail("read the table with no other checkout"))
        lone = tmp_path / "lone"
        lone.mkdir()
        _git(lone, "init", "-q")
        assert _fire(lone, f"kill {os.getpid()}") is None

    def test_a_long_checkout_path_stays_under_the_reason_cap(self, tmp_path, children):
        main, other = _clone(tmp_path, worktree="/".join(["a-long-folder-name-for-the-cap"] * 8))
        theirs = children(other)
        time.sleep(0.3)
        fired = _fire(main, f"kill {theirs.pid}")
        assert fired is not None and len(fired[1].encode("utf-8")) <= 512, len(fired[1].encode("utf-8"))


def _reads(monkeypatch, **answers) -> None:
    """Answer the named readers of the checkout_sync the hook loads."""
    import _hook_utils
    sync = _hook_utils.load_checkout_sync()
    for name, answer in answers.items():
        monkeypatch.setattr(sync, name, answer)


@needs_git
class TestAReadThatDidNotAnswer:
    """DEF-2046 at CP-KILL: a process table or a cwd read that did not answer
    read as empty, so `pkill -P` found no children and a pid its own cwd does
    not place could not be climbed to its owner: the kill passed with no
    word. Such a read now nudges once for each pid it leaves unplaced; a pid
    its own cwd places still decides as before."""

    @pytest.mark.parametrize("table", [None, {}], ids=["unread", "empty-from-an-older-checkout-sync"])
    def test_a_parent_kill_on_an_unread_table_is_nudged(self, tmp_path, monkeypatch, table):
        main, _other = _clone(tmp_path)
        _reads(monkeypatch, _parent_map=lambda *a, **k: table)
        fired = _fire(main, "pkill -P 4242")
        assert fired is not None and "pkill -P 4242: the process table could not be read" in fired[1], fired
        assert _fire(main, "pkill -P 4242") is None, "the re-issue proceeds"

    @posix_only
    def test_a_pid_its_own_cwd_does_not_place_is_nudged_on_an_unread_table(self, tmp_path, children, monkeypatch):
        main, _other = _clone(tmp_path)
        loose = tmp_path / "loose"
        loose.mkdir()
        theirs = children(loose)
        time.sleep(0.3)
        assert _fire(main, f"kill {theirs.pid}") is None, "a table that answered climbs to no checkout"
        _reads(monkeypatch, _parent_map=lambda *a, **k: None)
        fired = _fire(main, f"kill {theirs.pid}")
        assert fired is not None and (
            f"pid {theirs.pid}: the process table could not be read, so whose run" in fired[1]), fired
        assert _fire(main, f"kill {theirs.pid}") is None, "the re-issue proceeds"

    @posix_only
    def test_a_pid_placed_elsewhere_beside_an_unread_parent_kill_takes_the_words(self, tmp_path, children,
                                                                                monkeypatch):
        """The parent kill's cannot-tell once returned before the other targets
        were judged, and its re-issue passed another seat's run unnamed."""
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        _reads(monkeypatch, _parent_map=lambda *a, **k: None)
        fired = _fire(main, f"pkill -P 4242; kill {theirs.pid}")
        assert fired is not None and "works in .claude/worktrees/other" in fired[1], fired

    @posix_only
    def test_a_cannot_tell_nudge_never_spends_the_flag_a_placed_reading_needs(self, tmp_path, children,
                                                                               monkeypatch):
        main, other = _clone(tmp_path)
        theirs = children(other)
        time.sleep(0.3)
        with monkeypatch.context() as unread:
            _reads(unread, process_cwds=lambda *a, **k: None)
            assert "could not be read" in _fire(main, f"kill {theirs.pid}")[1]
        fired = _fire(main, f"kill -9 {theirs.pid}")
        assert fired is not None and "works in .claude/worktrees/other" in fired[1], fired

    @posix_only
    def test_a_gone_pid_is_never_nudged_for_a_read_that_did_not_answer(self, tmp_path, monkeypatch):
        """lsof reads a gone pid as nothing found and exit 1, which the
        reader cannot tell from a failed run: a pid that is gone has no run
        to protect either way."""
        main, _other = _clone(tmp_path)
        _reads(monkeypatch, _parent_map=lambda *a, **k: None, process_cwds=lambda *a, **k: None)
        assert _fire(main, "kill 2147483646") is None

    @posix_only
    def test_a_pid_its_own_cwd_places_still_decides_on_an_unread_table(self, tmp_path, children, monkeypatch):
        main, other = _clone(tmp_path)
        mine, theirs = children(main), children(other)
        time.sleep(0.3)
        _reads(monkeypatch, _parent_map=lambda *a, **k: None)
        assert _fire(main, f"kill {mine.pid}") is None, "this checkout's own run"
        fired = _fire(main, f"kill {theirs.pid}")
        assert fired is not None and "works in .claude/worktrees/other" in fired[1], fired

    @posix_only
    def test_a_cwd_read_that_did_not_answer_is_nudged(self, tmp_path, children, monkeypatch):
        main, _other = _clone(tmp_path)
        mine = children(main)
        time.sleep(0.3)
        _reads(monkeypatch, process_cwds=lambda *a, **k: None)
        fired = _fire(main, f"kill {mine.pid}")
        assert fired is not None and (
            f"pid {mine.pid}: its working directory could not be read, so whose run" in fired[1]), fired


def _record(rootpath: Path) -> dict:
    """The box lock's holder record, written by the suite's own writer, for a
    run in ``rootpath``: this test process is its pid."""
    import tests._box_lock as box
    return box.build_record(types.SimpleNamespace(rootpath=rootpath), box._primitive())


@needs_git
class TestTheBoxLocksHolder:
    def test_a_child_of_another_seats_holder_is_nudged(self, tmp_path, children, monkeypatch):
        main, other = _clone(tmp_path)
        lock = tmp_path / "box.lock"
        lock.write_text(json.dumps(_record(other)), encoding="utf-8")
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        child = children(scratch)
        time.sleep(0.3)
        fired = _fire(main, f"kill {child.pid}")
        assert fired is not None and fired[0] == "CP-KILL", fired
        assert (f"pid {child.pid} runs under the box lock's holder (pid {os.getpid()}, seat other-seat, "
                "lane HEAD)") in fired[1], fired[1]

    def test_this_checkouts_own_holder_passes(self, tmp_path, children, monkeypatch):
        main, _other = _clone(tmp_path)
        _git(main, "config", "espalier.machine", "main-seat")
        _git(main, "switch", "-q", "-c", "lane/mine")
        lock = tmp_path / "box.lock"
        record = _record(main)
        assert (record["seat"], record["lane"]) == ("main-seat", "lane/mine"), record
        lock.write_text(json.dumps(record), encoding="utf-8")
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        child = children(scratch)
        time.sleep(0.3)
        assert _fire(main, f"kill {child.pid}") is None

    def test_an_unnamed_holder_is_nudged_even_from_its_own_seat(self, tmp_path, children, monkeypatch):
        """A fresh-clone gate's clone has no local config, so its record reads
        seat '?': a lane of '?' or HEAD never passes (declared: one nudge)."""
        main, _other = _clone(tmp_path)
        bare = tmp_path / "gate-clone"
        bare.mkdir()
        lock = tmp_path / "box.lock"
        record = _record(bare)
        assert record["seat"] == "?" and record["lane"] == "?", record
        lock.write_text(json.dumps(record), encoding="utf-8")
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
        child = children(bare)
        time.sleep(0.3)
        assert _fire(main, f"kill {child.pid}") is not None

    def test_a_dead_holders_record_names_nobody(self, tmp_path, children, monkeypatch):
        main, _other = _clone(tmp_path)
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait(timeout=30)
        lock = tmp_path / "box.lock"
        lock.write_text(json.dumps({**_record(tmp_path), "pid": gone.pid}), encoding="utf-8")
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        child = children(scratch)
        time.sleep(0.3)
        assert _fire(main, f"kill {child.pid}") is None

    def test_an_unreadable_record_names_no_holder(self, tmp_path, monkeypatch):
        for body in ("", "{not json", json.dumps({"pid": True}), json.dumps({"pid": -3}), json.dumps([1])):
            lock = tmp_path / "box.lock"
            lock.write_text(body, encoding="utf-8")
            monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
            assert _speedbump._box_lock_holder() is None, body
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(tmp_path / "missing.lock"))
        assert _speedbump._box_lock_holder() is None
        monkeypatch.delenv("ESPALIER_BOX_LOCK")
        assert _speedbump._box_lock_holder() is None, "no default path: the variable alone names the lock"


class TestTheKillWords:
    @pytest.mark.parametrize("command,pids", [
        ("kill -9 101", [101]),
        ("kill -s KILL 102 103", [102, 103]),
        ("kill -- 104", [104]),
        ("kill -- -105", []),            # a process group
        ("kill %1", []),
        ("kill -s 0 106", []),
        ("kill -0 107", []),
        ("kill -l", []),
        ("pkill -P 108,109", [108, 109]),
        ("pkill -P110 -f tier", [110]),
        ("pkill -f pytest", []),          # by name: no pid to read
        ("taskkill /F /PID 111 /PID 112", [111, 112]),
        ("taskkill //F //PID 113", [113]),
        ("taskkill /IM python.exe", []),
        ("sudo kill -9 114", [114]),
        ("cd /tmp && kill 115", [115]),
        ("echo kill 116", []),
        ("echo 'kill 117'", []),
        ("kill $PID", []),
        ("kill 118 119 120 121 122", [118, 119, 120, 121]),
    ])
    def test_the_bash_tool_reads_each_spelling(self, command, pids):
        assert _speedbump._named_kill_pids("Bash", {"command": command}) == pids

    @pytest.mark.parametrize("command,pids", [
        ("Stop-Process -Id 201 -Force", [201]),
        ("Stop-Process -Id 202, 203", [202, 203]),
        ("Stop-Process 204", [204]),
        ("spps -Id:205", [205]),
        ("kill 206", [206]),
        ("Stop-Process -Name python", []),
        ("Stop-Process -ErrorAction SilentlyContinue 210", [210]),
        ("Stop-Process -Id 207 -WhatIf", []),
        ("taskkill.exe /PID 208", [208]),
        ("Write-Output 'Stop-Process -Id 209'", []),
    ])
    def test_the_powershell_tool_reads_each_spelling(self, command, pids):
        assert _speedbump._named_kill_pids("PowerShell", {"command": command}) == pids

    def test_another_tool_reads_nothing(self):
        assert _speedbump._named_kill_pids("Edit", {"command": "kill 301"}) == []


class TestTheRegistryRow:
    def test_cp_kill_follows_the_irreversible_tier_cap_exempt_and_keyed_per_pid(self):
        ids = [b.id for b in _speedbump.SPEEDBUMPS]
        assert ids.index("CP-KILL") == 6, ids
        bump = next(b for b in _speedbump.SPEEDBUMPS if b.id == "CP-KILL")
        assert bump.cap_exempt and bump.flag_key is _speedbump._kill_key and bump.body_for is not None
        reason = _speedbump._REASON_TEMPLATE.format(id=bump.id, body=bump.body)
        assert reason.isascii() and len(reason.encode("utf-8")) <= 512
