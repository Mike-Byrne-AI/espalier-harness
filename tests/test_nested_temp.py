"""DEF-5056: a pytest child a test launches keeps its temp dirs inside its
parent session's, so it never deletes another session's numbered dir inside
the test's clock.

pytest gives each session a numbered basetemp under one root per user and,
when the session ends, deletes every unlocked numbered dir three or more below
the newest (``_pytest/pathlib.py::cleanup_numbered_dir``). A child sharing its
parent's root therefore paid, at its own end, for the delete of whatever big
run had finished last: on windows-latest the cited-pin child of
``tests/test_declared_limits_contract.py`` paid the parallel leg's 8.9 GB
basetemp and ran past its 300 s bound. These rows pin both halves of
``tests/_nested_temp.py`` (the session's export, the child's basetemp) and
guard the harm itself: a child run under a temp root of the test's own
making, with a finished session's dir planted there, leaves the dir alone.
Each child runs this file's own reporting row, so the suite's conftest loads
in it as it does in every nested run. The helper is imported inside its one
row, never at the top, so on a tree without it these rows fail by assertion
rather than erroring at collection.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REL = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
#: Spelled here, not imported: see the module docstring.
KEY = "ESPALIER_PARENT_BASETEMP"
_REPORT = "NESTED_TMP_PATH="
_REPORTING_ROW = "test_a_child_reports_where_its_tmp_path_landed"


def _user() -> str:
    """The name pytest puts in its root (``_pytest/tmpdir.py::get_user``)."""
    try:
        return getpass.getuser()
    except (ImportError, OSError, KeyError):
        return "unknown"


def _plant(root: Path) -> tuple[Path, Path]:
    """pytest's root under ``root`` holding four numbered dirs, none locked:
    ``pytest-0`` stands for a finished session (a file in it says whether it
    survived) and ``pytest-3`` for the parent session's basetemp."""
    pytest_root = root / f"pytest-of-{_user()}"
    for n in range(4):
        (pytest_root / f"pytest-{n}").mkdir(parents=True)
    finished = pytest_root / "pytest-0" / "a-finished-sessions-file"
    finished.write_text("x", encoding="utf-8")
    return finished, pytest_root / "pytest-3"


def _run_child(root: Path | None, parent: Path | None, *extra: str) -> tuple[subprocess.CompletedProcess, Path | None]:
    """This file's reporting row in a child whose temp dir is ``root``, with
    ``parent`` exported as the launching session's basetemp (or nothing); the
    child's ``tmp_path`` as it reported it. ``root`` None leaves the temp dir
    and the export as this session's, as every real launch has them."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_DEBUG_TEMPROOT")}
    if root is not None:
        env.pop(KEY, None)
        env.update(TMPDIR=str(root), TEMP=str(root), TMP=str(root))
        if parent is not None:
            env[KEY] = str(parent)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", *extra, f"{REL}::{_REPORTING_ROW}"],
        cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=45,
    )
    landed = next((Path(line[len(_REPORT):]) for line in proc.stdout.splitlines() if line.startswith(_REPORT)), None)
    return proc, landed


def _tail(proc: subprocess.CompletedProcess) -> str:
    return f"rc {proc.returncode}\n--- stdout ---\n{proc.stdout[-1500:]}\n--- stderr ---\n{proc.stderr[-800:]}"


def test_a_child_reports_where_its_tmp_path_landed(tmp_path):
    """The row the children below run: it prints its own ``tmp_path``."""
    print(f"{_REPORT}{tmp_path}")
    assert tmp_path.is_dir()


class TestAChildKeepsItsTempDirsInItsParents:
    def test_a_child_leaves_a_finished_sessions_dir_alone(self, tmp_path):
        """The guard: with the parent's basetemp exported under the child's
        own root, the child's session end deletes nothing of another
        session's, and its ``tmp_path`` lands inside the parent's."""
        root = tmp_path / "temp"
        finished, parent = _plant(root)
        proc, landed = _run_child(root, parent)
        assert proc.returncode == 0 and landed is not None, _tail(proc)
        assert finished.exists(), (
            "the child deleted a finished session's numbered dir at its own end, inside the "
            f"launching test's clock (its tmp_path: {landed})\n{_tail(proc)}")
        assert landed.is_relative_to(parent) and landed.relative_to(parent).parts[0].startswith("nest-"), landed

    def test_a_child_whose_root_is_its_own_keeps_pytests_default(self, tmp_path):
        """A test that moved the child's temp dir away from its own session's
        (to watch pytest's own handling) gets pytest's default: a numbered
        dir, and the delete of the planted one, which also shows the plant
        above is one pytest would delete."""
        root = tmp_path / "temp"
        finished, _ = _plant(root)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        proc, landed = _run_child(root, elsewhere)
        assert proc.returncode == 0 and landed is not None, _tail(proc)
        assert landed.is_relative_to(finished.parent.parent / "pytest-4"), landed
        assert not finished.exists(), _tail(proc)

    def test_a_child_on_this_sessions_temp_root_nests_in_its_basetemp(self, tmp_path_factory):
        """The rows above plant a temp root; this one leaves the inherited
        one, the case every real launch is (on windows-latest a short 8.3
        temp path that only ``resolve()`` expands)."""
        proc, landed = _run_child(None, None)
        assert proc.returncode == 0 and landed is not None, _tail(proc)
        assert landed.is_relative_to(tmp_path_factory.getbasetemp()), landed

    def test_a_child_given_a_basetemp_keeps_it(self, tmp_path):
        """An explicit ``--basetemp`` wins over the export."""
        root = tmp_path / "temp"
        _, parent = _plant(root)
        given = tmp_path / "given"
        proc, landed = _run_child(root, parent, f"--basetemp={given}")
        assert proc.returncode == 0 and landed is not None, _tail(proc)
        assert landed.is_relative_to(given), landed


class TestTheSessionExportsItsBasetemp:
    def test_this_session_exports_its_basetemp(self, tmp_path_factory):
        """The other half: a test's children read where to nest from the
        session that runs it."""
        assert os.environ.get(KEY) == str(tmp_path_factory.getbasetemp())

    def test_the_helper_reads_the_key_this_file_spells(self):
        from tests import _nested_temp
        assert _nested_temp.KEY == KEY


@pytest.mark.parametrize("value", [None, ""])
def test_a_session_with_no_export_reads_none(monkeypatch, value):
    """Unset or empty, the export names no parent."""
    from tests import _nested_temp
    if value is None:
        monkeypatch.delenv(KEY, raising=False)
    else:
        monkeypatch.setenv(KEY, value)
    assert _nested_temp.parent_basetemp() is None
