"""The session-start sweep of the temp dirs a killed test run left (DEF-5053).

``tests/_temp_sweep.py`` removes, at the controller's configure, each dir under
pytest's root (``pytest-*``, ``garbage-*``) and each work dir of the makers
that lock theirs (the prefixes on ``OWNED_PREFIXES``) whose ``.lock`` names
a dead pid, and a census holds every other temp-dir maker to a reason. These rows pin that sweep because pytest keeps such
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
from typing import NamedTuple

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
    given = "a --basetemp given at the top level puts this session's dirs outside pytest's root"
    if pytestconfig.option.basetemp and not hasattr(pytestconfig, "workerinput"):
        pytest.skip(given)
    root = ts.pytest_root()
    if hasattr(pytestconfig, "workerinput"):
        # xdist gives every worker its own --basetemp, a child of the
        # controller's, so the option says nothing here; the controller's is
        # read as that parent, and one that is not a numbered dir under the
        # root is the top level's own (DEF-5082's lane: red under any explicit
        # basetemp with xdist, plain or spaced, measured 2026-11-04)
        controller = Path(pytestconfig.option.basetemp).resolve().parent
        if controller.parent != root:
            pytest.skip(given + " (read on the worker as its own basetemp's parent)")
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
        ``_json_safe`` was there before the load. The census folds case as the
        prefix does (``normcase`` lowercases on Windows, DEF-5059)."""
        program = (
            "import json, os, sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "from tests import _temp_sweep as ts\n"
            "path, names = list(sys.path), set(sys.modules)\n"
            "alive = ts.pid_alive()\n"
            "cc = lambda m: os.path.normcase(getattr(m, '__file__', None) or '').replace(chr(92), '/').startswith(ts._TOOLS_CC_PREFIX)\n"
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


#: The calls that make a temp dir (a temp file is not read).
_DIR_MAKERS = frozenset({"mkdtemp", "TemporaryDirectory"})
#: Where the census reads: the trees whose runs leave work dirs on a seat's box.
_MAKER_TREES = ("tests", "scripts", "bench", "tools/cc")
#: The makers the census finds at the pin; under half is a broken scan, over
#: twice a population the pin no longer describes.
_MAKERS_AT_PIN = 47  # 2026-11-02 (DEF-811's shared fixture builder), aliases included
#: Each maker that writes no lock, EXACT, ``file::function`` -> why its dir
#: needs none. An unlocked maker missing here reds, and so does an entry whose
#: function no longer makes an unlocked dir.
_CM_SMALL = "a context manager, removed at exit; a kill leaves "
_IN_BASETEMP = "made inside the test's tmp_path, removed with the session's basetemp"
_UNLOCKED_MAKERS: dict[str, str] = {
    "bench/end_to_end/runner.py::run_scenario":
        "removed in its own finally unless --keep-work-dir; a paid, hand-run bench, so a kill is the operator's",
    "bench/guard_metamorphic.py::_spelling_rc": _CM_SMALL + "an empty dir or one probe file",
    "bench/powershell_guard_rehearsal.py::shaped_root": _CM_SMALL + (
        "empty fixture dirs and a few speed-bump state files, or in a shaped "
        "benchmark run one baseline's setup, an espalier init deploy at most "
        "(every guard fixture's shaped project is built under it, DEF-811)"),
    "bench/powershell_reachability_differential.py::_run_pwsh": _CM_SMALL + "a one-byte victim file",
    "bench/powershell_reachability_differential.py::main": _CM_SMALL + "pwsh's small startup cache",
    "bench/reachability_differential.py::bash_run": _CM_SMALL + "a one-byte victim file",
    "bench/reachability_differential.py::_differential": _CM_SMALL + (
        "a ~4 MB export of tools/ (each guard call's project is the rehearsal's shaped_root, DEF-811)"),
    "bench/run_benchmark.py::_baseline_root": _CM_SMALL + "one baseline's setup, an espalier init deploy at most",
    "bench/sandbox_read_drive/drive.py::main":
        "never removed on purpose: the hand-run drive's output folder; the suite returns before making it",
    "bench/sandbox_read_drive/drive.py::run_case": "made inside the drive's own runs folder, kept with it as the record",
    "scripts/host_check.py::publish": _CM_SMALL + "one temporary git index",
    "scripts/verify_pins.py::run_pytest": "made inside verify's own locked verify-pins- dir, removed or swept with it",
    "tests/_engine_check.py::foreign_engine": _CM_SMALL + "an empty dir",
    "tests/_nested_temp.py::nested_basetemp": "made inside the launching session's basetemp, removed with it",
    "tests/_symlink_support.py::symlinks_supported": _CM_SMALL + "a one-byte file and a link",
    "tests/test_box_lock.py::_spawn": _IN_BASETEMP,
    "tests/test_guard_false_positives.py::_tier": _CM_SMALL + (
        "the protected tree's empty directories and a few speed-bump state files"),
    "tests/test_scanner_filesystem_contracts.py::test_overlaid_script_in_scanner_scope": _CM_SMALL + "one small .py",
    "tests/test_wheel_install_surface_parity.py::test_source_and_wheel_init_deploy_same_managed_surface": _IN_BASETEMP,
    "tests/test_wheel_smoke.py::TestBuildFailureCleanup::test_run_smoke_cleans_scratch_dist_on_build_failure::recording_mkdtemp":
        "a recording passthrough of the wheel smoke's own locked maker, whose dir the test asserts is removed",
    # By file: another lane renames this file's classes, and each of its six makers is a
    # class fixture's context manager.
    "tests/test_write_guard.py":
        "class-fixture context managers, removed at teardown; a kill leaves empty fixture dirs and audit logs",
    "tests/test_xdist_never_ran.py::_drive": _IN_BASETEMP,
    "tools/cc/board.py::read_ledger_at_base": _CM_SMALL + "a ~7 MB base tar and its extracted tools/cc modules",
    "tools/cc/check_ledger_probes.py::_probe_audit_dir": "removed at exit by atexit; a kill leaves a few small audit logs",
    "tools/cc/ci_guard.py::_ci_base_is_self_host": _CM_SMALL + "two files under 200 KB",
    "tools/cc/hooks/_integrity.py::_make_fallback_dir":
        "the HOME-unset audit store, never removed by design (one a process); the suite makes it in tmp_path",
    "tools/cc/hooks/session_start.py::_probe_engine": _CM_SMALL + "an empty dir",
    "tools/cc/record_merge.py::_three_way": _CM_SMALL + "three small text files",
}


class Maker(NamedTuple):
    """One temp-dir maker as :func:`temp_dir_makers` reads it."""

    qual: str
    line: int
    prefix: str | None
    locks: bool
    inside: bool


def temp_dir_makers(text: str) -> list[Maker]:
    """Each call in ``text`` that makes a temp dir, by name or through an
    alias (``from tempfile import mkdtemp as m``, ``real = tempfile.mkdtemp``):
    its function's qualified name (``Class::function``; ``<module>`` at module
    level), its line, its prefix as far as it is a constant (a literal, a
    module constant's value or an f-string's leading text; None otherwise),
    whether its function writes the sweep's lock (a ``write_lock`` call, or a
    ``write_text`` on a path naming ``LOCK_NAME`` or ``.lock``; a module-level
    maker's own statement), and whether it is given a ``dir``."""
    import ast

    tree = ast.parse(text)
    constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                 for target in node.targets if isinstance(target, ast.Name)}
    aliases = set(_DIR_MAKERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tempfile":
            aliases.update(a.asname or a.name for a in node.names if a.name in _DIR_MAKERS)
        elif isinstance(node, ast.Assign) and getattr(node.value, "attr", getattr(node.value, "id", None)) in _DIR_MAKERS:
            aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))

    def argument(call: ast.Call, name: str, position: int) -> ast.expr | None:
        return next((k.value for k in call.keywords if k.arg == name),
                    call.args[position] if len(call.args) > position else None)

    def prefix(call: ast.Call) -> str | None:
        node = argument(call, "prefix", 1)
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
            return str(node.values[0].value)
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def names_the_lock(node: ast.AST) -> bool:
        return any((isinstance(n, (ast.Name, ast.Attribute)) and (getattr(n, "id", None) or getattr(n, "attr", None))
                    == "LOCK_NAME") or (isinstance(n, ast.Constant) and n.value == ".lock") for n in ast.walk(node))

    def locks(scope: ast.AST) -> bool:
        for node in ast.walk(scope):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name == "write_lock" or (name == "write_text" and isinstance(node.func, ast.Attribute)
                                            and names_the_lock(node.func.value)):
                    return True
        return False

    found: list[Maker] = []

    def visit(node: ast.AST, qual: tuple[str, ...], scope: ast.AST | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, qual + (child.name,), child)
                continue
            if isinstance(child, ast.ClassDef):
                visit(child, qual + (child.name,), scope)
                continue
            own = scope if scope is not None else child  # a module-level maker: its own statement
            if isinstance(child, ast.Call) and (getattr(child.func, "attr", None) in _DIR_MAKERS
                                                 or getattr(child.func, "id", None) in aliases):
                found.append(Maker("::".join(qual) or "<module>", child.lineno, prefix(child), locks(own),
                                   argument(child, "dir", 2) is not None))
            visit(child, qual, own)

    visit(tree, (), None)
    return found


@pytest.mark.contract
class TestEveryTempDirMakerIsSweptOrSaysWhy:
    """DEF-5055: the sweep removes only the work dirs whose makers lock them,
    so a maker added without a lock leaves its dir behind each time its run is
    killed, unsaid. This census guards both ways over the Python makers under
    the four trees in ``_MAKER_TREES``: every ``mkdtemp`` and
    ``TemporaryDirectory`` call either writes the lock under a prefix on
    ``OWNED_PREFIXES`` (the one roster) or is enrolled with why it needs none
    (by its function, or by its file where another lane renames its
    functions), and every roster prefix and enrolment names a live maker. The
    function is the unit: a second maker in a function that writes one lock
    reads as locked, so each locked maker's own test file drives its dirs
    (``TestTheWorkDirsLock`` and its kin)."""

    @staticmethod
    def _makers() -> list[tuple[str, Maker]]:
        from tests._live_tree import checkout_glob

        out = []
        for top in _MAKER_TREES:
            for path in checkout_glob(REPO_ROOT / top, "**/*.py"):
                text = path.read_text(encoding="utf-8")
                if any(name in text for name in _DIR_MAKERS):
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    out += [(f"{rel}::{maker.qual}", maker) for maker in temp_dir_makers(text)]
        return out

    @staticmethod
    def _enrolment(site: str) -> str | None:
        return _UNLOCKED_MAKERS.get(site, _UNLOCKED_MAKERS.get(site.split("::", 1)[0]))

    def test_the_scan_clears_its_floor_and_reads_the_two_it_was_written_for(self):
        """Asserted first, so a clean verdict below is not an empty scan."""
        makers = self._makers()
        assert _MAKERS_AT_PIN // 2 <= len(makers) <= 2 * _MAKERS_AT_PIN, (
            f"{len(makers)} makers against a pin of {_MAKERS_AT_PIN}: re-pin it with the date")
        locked = {site for site, maker in makers if maker.locks}
        assert {"scripts/archive_probe.py::make_work_dir", "tests/_live_tree.py::checkout_copy"} <= locked, locked

    def test_a_maker_writes_the_lock_exactly_when_its_prefix_is_on_the_roster(self):
        """A roster prefix whose maker writes no lock is a dir the sweep never
        removes; a lock under a prefix off the roster is one it never reads."""
        wrong = [f"{site}:{maker.line} (prefix {maker.prefix!r}, "
                 f"{'writes the lock' if maker.locks else 'writes no lock'})"
                 for site, maker in self._makers()
                 if maker.locks != (maker.prefix is not None and maker.prefix.startswith(ts.OWNED_PREFIXES))]
        assert not wrong, (
            "write the lock where the prefix is on tests/_temp_sweep.py::OWNED_PREFIXES, and put a locking "
            f"maker's prefix there: {wrong}")

    def test_every_unlocked_maker_says_why(self):
        missing = sorted({site for site, maker in self._makers() if not maker.locks and self._enrolment(site) is None})
        assert not missing, (
            "these make a temp dir the session-start sweep never removes after a killed run: write the lock "
            "(tests/_temp_sweep.py::write_lock, or the pid into LOCK_NAME) and put the prefix on OWNED_PREFIXES, "
            f"or enrol the function in _UNLOCKED_MAKERS with why its dir needs none: {missing}")

    def test_an_enrolment_that_says_inside_is_given_a_dir(self):
        """An enrolment whose reason is that the dir is made inside another is
        true only while the call passes ``dir``: dropped, the dir lands in the
        system temp dir and the reason still reads."""
        wrong = sorted(site for site, maker in self._makers() if not maker.locks and not maker.inside
                       and "inside" in (self._enrolment(site) or ""))
        assert not wrong, wrong

    def test_every_enrolment_and_roster_prefix_names_a_live_maker(self):
        makers = self._makers()
        unlocked = {site for site, maker in makers if not maker.locks}
        files = {site.split("::", 1)[0] for site in unlocked}
        assert not {key for key in _UNLOCKED_MAKERS if key not in unlocked and key not in files}, (
            sorted(key for key in _UNLOCKED_MAKERS if key not in unlocked and key not in files))
        assert all(why.strip() for why in _UNLOCKED_MAKERS.values())
        locked = [maker.prefix for _site, maker in makers if maker.locks and maker.prefix]
        assert all(any(pre.startswith(owned) for pre in locked) for owned in ts.OWNED_PREFIXES), (
            ts.OWNED_PREFIXES, locked)

    @pytest.mark.parametrize("label, source, expect", [
        ("a literal prefix, no lock", "import tempfile\ndef f():\n    tempfile.mkdtemp(prefix='a-')\n",
         [("f", 3, "a-", False, False)]),
        ("a module constant and a lock written by name",
         "import tempfile\nP = 'b-'\nLOCK_NAME = '.lock'\ndef f():\n    d = tempfile.mkdtemp(prefix=P)\n"
         "    (d / LOCK_NAME).write_text('1')\n", [("f", 5, "b-", True, False)]),
        ("a context manager in a method, write_lock",
         "import tempfile\nclass A:\n    def g(self):\n        with tempfile.TemporaryDirectory(prefix=f'c-{1}-') as d:\n"
         "            write_lock(d)\n", [("A::g", 4, "c-", True, False)]),
        ("a positional prefix and dir, and none at all",
         "from tempfile import mkdtemp, TemporaryDirectory\ndef h(t):\n    mkdtemp('', 'd-', t)\n"
         "    TemporaryDirectory()\n", [("h", 3, "d-", False, True), ("h", 4, None, False, False)]),
        ("a lock written in another function is not this one's",
         "import tempfile\nLOCK_NAME = '.lock'\ndef lock(d):\n    (d / LOCK_NAME).write_text('1')\n"
         "def f():\n    lock(tempfile.mkdtemp(prefix='e-'))\n", [("f", 6, "e-", False, False)]),
        ("a lock only removed is not written",
         "import tempfile\nLOCK_NAME = '.lock'\ndef f():\n    d = tempfile.mkdtemp(prefix='g-')\n"
         "    (d / LOCK_NAME).unlink(missing_ok=True)\n", [("f", 4, "g-", False, False)]),
        ("an alias by import and by assignment",
         "import tempfile\nfrom tempfile import mkdtemp as md\ndef f(tmp):\n    real = tempfile.mkdtemp\n"
         "    real(dir=tmp)\n    md()\n", [("f", 5, None, False, True), ("f", 6, None, False, False)]),
        ("a module-level maker reads its own statement, not the module's lock",
         "import tempfile\nLOCK_NAME = '.lock'\nD = tempfile.mkdtemp(prefix='h-')\n"
         "def f(d):\n    (d / LOCK_NAME).write_text('1')\n", [("<module>", 3, "h-", False, False)]),
    ])
    def test_the_census_reads(self, label, source, expect):
        assert [tuple(m) for m in temp_dir_makers(source)] == expect, label


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
