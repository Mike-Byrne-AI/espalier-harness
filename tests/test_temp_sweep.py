"""The session-start sweep of the temp dirs a killed test run left (DEF-5053).

``tests/_temp_sweep.py`` removes, at the controller's configure, each dir under
pytest's root (``pytest-*``, ``garbage-*``) and each work dir of the two makers
that lock theirs (``espalier-archive-probe-*``, ``checkout-copy-*``) whose
``.lock`` names a dead pid. These rows pin that sweep because pytest keeps such
a dir for 72 h by its lock's age alone, and 13 of them held 32 GB on one seat's
machine; they guard what it must keep (a live or unknown pid, an unlocked dir,
a link, ``pytest-current``) and that pytest still writes the lock it reads. The
unit rows drive ``sweep`` on scratch roots with the liveness answer injected;
the end-to-end rows start a real nested session from this checkout with its
temp dir moved into ``tmp_path``.
"""
from __future__ import annotations

# slow-exempt: two one-test nested pytest sessions of under a second each, one
# interpreter for the load row, and a child that exits at once per dead pid.

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _temp_sweep as ts
from tests._symlink_support import requires_symlink

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The exited children whose pids the rows plant. Held for the session: on
#: Windows a pid is handed out again once its last handle closes, and a reused
#: pid would read as a live run.
_EXITED: list[subprocess.Popen] = []


def _dead_pid() -> int:
    """The pid of a process that has exited (reaped, so it is not a zombie)."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    _EXITED.append(child)
    return child.pid


def _plant(root: Path, name: str, pid: int | None, *, extra: str = "left.txt") -> Path:
    """A dir under ``root`` holding a file, with a lock naming ``pid``."""
    d = root / name
    (d / "sub").mkdir(parents=True)
    (d / "sub" / extra).write_text("x", encoding="utf-8")
    if pid is not None:
        (d / ts.LOCK_NAME).write_text(str(pid), encoding="utf-8")
    return d


def _alive(answers: dict[int, bool | None]):
    return lambda pid: answers.get(pid, False)


class TestTheSweepRemovesWhatADeadRunLeft:
    def test_a_dir_whose_lock_names_a_dead_pid_goes(self, tmp_path):
        d = _plant(tmp_path, "pytest-90", 4242)
        ro = d / "sub" / "pack.idx"
        ro.write_text("x", encoding="utf-8")
        ro.chmod(stat.S_IREAD)  # git's packfiles carry the read-only bit
        removed, stuck = ts.sweep(tmp_path, ts.PYTEST_PREFIXES, alive=_alive({}), rm=ts.deleter())
        assert (removed, stuck) == (["pytest-90"], [])
        assert not d.exists()

    def test_a_live_pid_an_unknown_answer_and_a_missing_or_unreadable_lock_keep_the_dir(self, tmp_path):
        kept = [_plant(tmp_path, "pytest-1", 11), _plant(tmp_path, "pytest-2", 12),
                _plant(tmp_path, "pytest-3", None), _plant(tmp_path, "pytest-4", None),
                _plant(tmp_path, "pytest-5", None)]
        (kept[3] / ts.LOCK_NAME).write_text("not a pid", encoding="utf-8")
        (kept[4] / ts.LOCK_NAME).write_text("0", encoding="utf-8")
        removed, stuck = ts.sweep(tmp_path, ts.PYTEST_PREFIXES, alive=_alive({11: True, 12: None}),
                                  rm=ts.deleter())
        assert (removed, stuck) == ([], [])
        assert all(d.exists() for d in kept)

    def test_pytests_own_garbage_dirs_go_and_other_names_stay(self, tmp_path):
        garbage = _plant(tmp_path, "garbage-0b1c", 4242)
        other = _plant(tmp_path, "other-1", 4242)
        removed, _ = ts.sweep(tmp_path, ts.PYTEST_PREFIXES, alive=_alive({}), rm=ts.deleter())
        assert removed == ["garbage-0b1c"]
        assert not garbage.exists() and other.exists()

    def test_a_kept_path_is_never_touched(self, tmp_path):
        current = _plant(tmp_path, "pytest-93", 4242)
        removed, _ = ts.sweep(tmp_path, ts.PYTEST_PREFIXES, alive=_alive({}), rm=ts.deleter(),
                              keep=[current])
        assert removed == [] and current.exists()

    @requires_symlink
    def test_a_link_is_never_followed_and_pytest_current_names_a_kept_dir(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = _plant(tmp_path, "outside", 4242)
        (root / "pytest-77").symlink_to(outside, target_is_directory=True)
        current = _plant(root, "pytest-93", 4242)
        (root / ts.CURRENT_LINK).symlink_to(current, target_is_directory=True)
        assert ts.current_target(root) == Path(os.path.realpath(current))
        removed, stuck = ts.sweep(root, ts.PYTEST_PREFIXES, alive=_alive({}), rm=ts.deleter(),
                                  keep=[ts.current_target(root)])
        assert (removed, stuck) == ([], [])
        assert (outside / "sub" / "left.txt").is_file() and (current / "sub" / "left.txt").is_file()
        assert (root / ts.CURRENT_LINK).is_symlink()

    def test_a_dir_whose_contents_will_not_go_keeps_its_lock_for_the_next_start(self, tmp_path):
        d = _plant(tmp_path, "pytest-90", 4242)
        refusing = SimpleNamespace(remove_tree=lambda path, best_effort: None,
                                   remove_file=lambda path, best_effort: None)
        removed, stuck = ts.sweep(tmp_path, ts.PYTEST_PREFIXES, alive=_alive({}), rm=refusing)
        assert (removed, stuck) == ([], ["pytest-90"])
        assert ts.lock_pid(d) == 4242

    def test_a_fault_in_one_dir_is_that_one_left_and_the_rest_still_go(self, tmp_path):
        """A delete that raises something other than OSError (the shared
        deleter's retry, DEF-5054) or a liveness check that raises costs that
        entry alone."""
        faulting, after = _plant(tmp_path, "pytest-1", 4242), _plant(tmp_path, "pytest-2", 4242)
        unaskable = _plant(tmp_path, "pytest-3", 99)
        real = ts.deleter()

        def remove_tree(path, best_effort):
            if path.parent == faulting:
                raise TypeError("open() missing required argument 'flags'")
            real.remove_tree(path, best_effort=best_effort)

        def alive(pid):
            if pid == 99:
                raise OverflowError("signed integer is greater than maximum")
            return False

        rm = SimpleNamespace(remove_tree=remove_tree, remove_file=real.remove_file)
        removed, stuck = ts.sweep(tmp_path, ts.PYTEST_PREFIXES, alive=alive, rm=rm)
        assert (removed, stuck) == (["pytest-2"], ["pytest-1"])
        assert ts.lock_pid(faulting) == 4242 and not after.exists() and unaskable.exists()

    def test_past_the_deadline_a_dir_keeps_its_lock_for_the_next_start(self, tmp_path):
        d = _plant(tmp_path, "pytest-90", 4242)
        assert ts.remove(d, ts.deleter(), deadline=time.monotonic() - 1) is False
        assert ts.lock_pid(d) == 4242 and (d / "sub" / "left.txt").is_file()

    def test_the_line_names_what_went_and_counts_past_five(self):
        assert ts.summary([], [], 1.0) is None
        line = ts.summary([f"pytest-{n}" for n in range(7)], ["pytest-9"], 2.04)
        assert line == ("temp sweep: removed 7 dir(s) a dead run left (pytest-0, pytest-1, pytest-2, "
                        "pytest-3, pytest-4 and 2 more) in 2.0 s; 1 left for the next start (pytest-9): "
                        "past the 60 s budget, or a file that would not go")


def _numbered_dir(tmp_path: Path, pytestconfig) -> Path:
    """The numbered dir pytest made for this session, directly under its
    root, above ``tmp_path``: an xdist worker's base temp is a child of the
    controller's (``popen-gw<N>``), so it is found the same way there."""
    if pytestconfig.option.basetemp and not hasattr(pytestconfig, "workerinput"):
        pytest.skip("a --basetemp given at the top level puts this session's dirs outside pytest's root")
    root = ts.pytest_root()
    found = [p for p in tmp_path.resolve().parents if p.parent == root]
    assert found, f"{tmp_path} is not under pytest's root as the sweep reads it ({root})"
    return found[0]


class TestTheRootAndTheLockArePytests:
    def test_this_sessions_numbered_dir_is_under_the_root_the_sweep_reads(self, tmp_path, pytestconfig):
        assert _numbered_dir(tmp_path, pytestconfig).name.startswith(ts.PYTEST_PREFIXES[0])

    def test_pytest_locks_it_with_a_live_pid_the_sweep_reads(self, tmp_path, pytestconfig):
        """A pytest that renames its lock, writes another shape into it, or
        stops writing one (``tmp_path_retention_policy = "none"``) leaves
        every dead run's dir kept by the sweep; this row says so."""
        numbered = _numbered_dir(tmp_path, pytestconfig)
        assert ts.pid_alive()(ts.lock_pid(numbered)) is True, f"no live pid in {numbered / ts.LOCK_NAME}"

    def test_the_debug_temproot_moves_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(tmp_path))
        assert ts.pytest_root().parent == tmp_path.resolve()
        assert ts.pytest_root().name.startswith("pytest-of-")


class TestWhenItStandsDown:
    def _config(self, **option):
        return SimpleNamespace(option=SimpleNamespace(**option), pluginmanager=None)

    def test_a_worker_a_nested_run_and_a_run_of_no_tests_stand_down_without_a_word(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        assert not ts.skipped(self._config())
        assert ts.skipped(SimpleNamespace(option=SimpleNamespace(), workerinput={}))
        assert ts.skipped(self._config(collectonly=True))
        assert ts.skipped(SimpleNamespace())  # a stub config, as the suite's configure tests pass
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_x.py::test_y (call)")
        assert ts.skipped(self._config())

    @pytest.mark.parametrize("value", ["0", "off", "false", "no"])
    def test_any_switch_value_but_one_turns_it_off_and_the_summary_says_so(self, monkeypatch, value):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv(ts.SKIP_KEY, value)
        registered: list = []
        manager = SimpleNamespace(hasplugin=lambda name: False,
                                  register=lambda plugin, name: registered.append((plugin, name)))
        ts.pytest_configure(SimpleNamespace(option=SimpleNamespace(), pluginmanager=manager))
        assert [name for _, name in registered] == [ts.PLUGIN_NAME]
        assert registered[0][0].line.startswith(f"temp sweep: off ({ts.SKIP_KEY}={value!r})")

    @pytest.mark.parametrize("value", ["1", ""])
    def test_one_or_empty_leaves_it_on(self, monkeypatch, value):
        monkeypatch.setenv(ts.SKIP_KEY, value)
        assert ts.switched_off() is None

    def test_loading_checkout_sync_leaves_the_import_path_and_the_bare_names_alone(self):
        """In a fresh interpreter, where neither ``tools/cc`` on the path nor
        ``_json_safe`` was there before the load."""
        program = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "from tests import _temp_sweep as ts\n"
            "path, names = list(sys.path), set(sys.modules)\n"
            "alive = ts.pid_alive()\n"
            "cc = lambda m: (getattr(m, '__file__', None) or '').replace(chr(92), '/').startswith(ts._TOOLS_CC_PREFIX)\n"
            "added = sorted(n for n in set(sys.modules) - names if cc(sys.modules[n]))\n"
            "print(json.dumps({'path_kept': sys.path == path, 'added_from_tools_cc': added,"
            " 'self_alive': alive(__import__('os').getpid())}))\n"
        )
        proc = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout.strip().splitlines()[-1])
        assert got == {"path_kept": True, "added_from_tools_cc": ["_temp_sweep_checkout_sync"],
                       "self_alive": True}, got


class TestTheMakersLockTheirWorkDirs:
    def test_a_checkout_copy_sits_one_level_under_a_locked_holder(self):
        """The holder carries this process's lock; a walker over the copy never
        meets it. ``scripts/archive_probe.py``'s lock is pinned beside its own
        tests (``tests/test_archive_probe.py::TestTheWorkDirsLock``)."""
        from tests._live_tree import checkout_copy

        copy = checkout_copy(["pyproject.toml"])
        holder = copy.parent
        assert holder.name.startswith(ts.OWNED_PREFIXES), holder.name
        assert ts.lock_pid(holder) == os.getpid()
        assert (copy / "pyproject.toml").is_file()
        assert list(copy.rglob(ts.LOCK_NAME)) == []


def _child_env(temp: Path, *, keep_current_test: bool = False) -> dict[str, str]:
    """This process's environment for a nested session: its temp dir moved to
    ``temp``, and no pytest, harness or Claude Code variable of the outer run
    but the suite's audit store (``PYTEST_CURRENT_TEST`` kept where asked)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTEST_", "ESPALIER_", "CLAUDE_")) or k == "ESPALIER_AUDIT_DIR"}
    env.update(TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp))
    if keep_current_test:
        env["PYTEST_CURRENT_TEST"] = os.environ.get("PYTEST_CURRENT_TEST", "tests/x.py::y (call)")
    return env


def _start_a_session(env: dict[str, str]) -> subprocess.CompletedProcess:
    """One nested session from this checkout that selects no test: its
    configure runs, and nothing else of note."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "selects_nothing_at_all",
         str(Path(__file__).resolve())],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=45,
    )


def _user_root(temp: Path) -> Path:
    import getpass
    return temp / f"pytest-of-{getpass.getuser()}"


class TestASessionStartSweeps:
    def test_a_session_start_removes_a_dead_runs_dirs_and_keeps_the_rest(self, tmp_path):
        temp = tmp_path / "temp"
        root = _user_root(temp)
        dead, live = _dead_pid(), os.getpid()
        gone = [_plant(root, "pytest-90", dead), _plant(root, "garbage-0b1c", dead),
                _plant(temp, "espalier-archive-probe-a1", dead), _plant(temp, "checkout-copy-b2", dead)]
        stay = [_plant(root, "pytest-91", live), _plant(root, "pytest-92", None),
                _plant(temp, "checkout-copy-c3", live), _plant(temp, "unrelated-d4", dead)]
        current = _plant(root, "pytest-93", dead)
        try:
            (root / ts.CURRENT_LINK).symlink_to(current, target_is_directory=True)
        except OSError:  # no symlink privilege: pytest itself runs without the link there
            gone.append(current)
        else:
            stay.append(current)
        proc = _start_a_session(_child_env(temp))
        out = proc.stdout + proc.stderr
        assert proc.returncode == 5, out  # no test selected: configure ran, nothing failed
        assert [d.name for d in gone if d.exists()] == [], out
        assert [d.name for d in stay if not d.exists()] == [], out
        assert f"temp sweep: removing {len(gone)} dir(s) a dead run left" in proc.stderr, out
        assert f"temp sweep: removed {len(gone)} dir(s) a dead run left" in proc.stderr, out

    def test_a_session_started_inside_a_test_leaves_them(self, tmp_path):
        temp = tmp_path / "temp"
        d = _plant(_user_root(temp), "pytest-90", _dead_pid())
        proc = _start_a_session(_child_env(temp, keep_current_test=True))
        assert proc.returncode == 5, proc.stdout + proc.stderr
        assert d.exists() and "temp sweep" not in proc.stderr
