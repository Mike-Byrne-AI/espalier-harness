"""Contracts for ``scripts/archive_probe.py`` -- the archive drive as a script.

The composition is pinned first: the probe binds the DEF-670 seed, the venv
factory and the runner FROM ``scripts/final_release_matrix.py`` and defines
none of them (a copy creeping in reds here, because two seeds drift). The pure
pieces are pinned directly: the split at the first ``--``, the caller's
arguments riding through verbatim, the child environment without the
release_check opt-ins or the repo-redirecting git keys and with the audit
switch set by the flag alone, the runner executing exactly the command the
builder spells in its own session with the streaming kwargs, the bound kill
that takes the process group and exits 124. The refusals are pinned where they
are cheap, and the order they come in is driven through ``_main`` with every
step stubbed and a Popen that must never be built: no pytest arguments before
any write; a work dir that is not empty before any build; an absolute test
path before any build; a tree the predicate does not call an export before
pytest. One driven row (``heavy_e2e``) runs the probe on this checkout against
one shipped module and reads the work dir: a seeded extracted tree the
predicate calls an export, the archive's member list equal to the tracked set,
exit 0.

Why the export precondition is its own row: the audit switch reaches the
auto-skip only where ``is_release_export`` is True, so a work dir the predicate
does not call an export would make every registration read as stale while
nothing was tested on an export. The probe asserts it; this file asserts the
probe asserts it, and asserts it BEFORE pytest.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
import time
import types
import zipfile
from pathlib import Path

import pytest

from tests._git_oracle import require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "archive_probe.py"
if not MODULE_PATH.is_file():
    pytest.skip("scripts/archive_probe.py is dev tooling not shipped in the sdist",
                allow_module_level=True)

# Marker assignment lives in tests/conftest.py::_MARKER_RULES (integration).


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return _load("archive_probe", MODULE_PATH)


# ── the composition ────────────────────────────────────────────────────────


class TestComposition:
    def test_the_seed_the_venv_and_the_runner_are_bound_from_the_matrix(self, probe):
        assert probe._seed_git is probe._matrix._seed_git
        assert probe._make_venv is probe._matrix._make_venv
        assert probe._run is probe._matrix._run
        assert probe._SUITE_BOUND_S == probe._matrix._SUITE_BOUND_S
        assert tuple(probe._RELEASE_CHECK_OPT_INS) == tuple(probe._matrix._RELEASE_CHECK_OPT_INS)
        assert tuple(probe._GIT_REDIRECT_ENV) == tuple(probe._matrix._GIT_REDIRECT_ENV)

    def test_the_probe_defines_none_of_them(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        defined = {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        composed = {"_seed_git", "_make_venv", "_run"}
        assert not (defined & composed), (
            f"the probe re-implements {sorted(defined & composed)}; it must bind them from "
            "the matrix module so the drive and stage 02 cannot drift"
        )
        bound_from_matrix = {
            node.targets[0].id
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name) and node.value.value.id == "_matrix"
        }
        assert composed <= bound_from_matrix, (
            f"not bound from the matrix module: {sorted(composed - bound_from_matrix)}"
        )


# ── the pure pieces ────────────────────────────────────────────────────────


class TestSplitArgv:
    def test_the_first_double_dash_splits_and_a_later_one_belongs_to_pytest(self, probe):
        opts, rest = probe.split_argv(["--audit", "--work-dir", "w", "--", "-q", "--", "x"])
        assert opts == ["--audit", "--work-dir", "w"]
        assert rest == ["-q", "--", "x"]

    def test_no_double_dash_means_no_pytest_arguments(self, probe):
        assert probe.split_argv(["--audit"]) == (["--audit"], [])
        assert probe.split_argv([]) == ([], [])

    def test_the_options_parse_and_default_to_this_checkout(self, probe):
        ns = probe.parse_args(["--audit", "--clean"])
        assert ns.audit and ns.clean and ns.work_dir is None
        assert Path(ns.root) == REPO_ROOT


class TestBuildPytestCommand:
    def test_the_callers_arguments_ride_through_verbatim(self, probe, tmp_path):
        vpy = tmp_path / "venv" / "bin" / "python"
        args = ["tests/test_x.py", "-q", "-p", "no:cacheprovider", "-m", "not full_tree", "--", "odd"]
        assert probe.build_pytest_command(vpy, args) == [str(vpy), "-m", "pytest", *args]

    def test_no_arguments_is_a_bare_pytest_the_probe_never_runs(self, probe, tmp_path):
        vpy = tmp_path / "py"
        assert probe.build_pytest_command(vpy, []) == [str(vpy), "-m", "pytest"]


class TestProbeChildEnv:
    def _parent(self, probe):
        parent = {"PATH": "/usr/bin", "HOME": "/h", "PYTEST_ADDOPTS": "-rfEs"}
        parent.update({key: "1" for key in probe._RELEASE_CHECK_OPT_INS})
        parent.update({key: "/elsewhere" for key in probe._GIT_REDIRECT_ENV})
        parent[probe.AUDIT_ENV] = "1"
        return parent

    def test_the_opt_ins_are_absent_and_the_rest_passes_through(self, probe):
        env = probe.probe_child_env(False, self._parent(probe))
        assert not (set(env) & set(probe._RELEASE_CHECK_OPT_INS))
        assert env["PATH"] == "/usr/bin" and env["HOME"] == "/h"
        assert env["PYTEST_ADDOPTS"] == "-rfEs"

    def test_the_repo_redirecting_git_keys_are_absent(self, probe):
        # Inherited, a git arm inside the export would answer about the dev
        # repo (the seed strips the same six on every call).
        env = probe.probe_child_env(False, self._parent(probe))
        assert not (set(env) & set(probe._GIT_REDIRECT_ENV))
        assert "GIT_DIR" in probe._GIT_REDIRECT_ENV

    def test_the_audit_switch_is_the_flags_never_the_shells(self, probe):
        assert probe.AUDIT_ENV not in probe.probe_child_env(False, self._parent(probe))
        assert probe.probe_child_env(True, {"PATH": "/usr/bin"})[probe.AUDIT_ENV] == "1"

    def test_the_opt_in_set_is_the_matrixs_and_non_empty(self, probe):
        # The set is imported, not re-listed: an empty tuple would strip nothing
        # and the child would re-spawn the nested proofs.
        assert probe._RELEASE_CHECK_OPT_INS
        assert probe.AUDIT_ENV == "ESPALIER_FULL_TREE_AUDIT"


class TestRelativeArguments:
    def test_an_absolute_or_parent_relative_test_path_is_refused(self, probe):
        with pytest.raises(probe.ProbeRefusal, match="outside the extracted tree"):
            probe.refuse_unless_relative([str(REPO_ROOT / "tests" / "test_recall.py"), "-q"])
        with pytest.raises(probe.ProbeRefusal, match="outside the extracted tree"):
            probe.refuse_unless_relative(["../tests/test_recall.py"])

    def test_relative_paths_and_options_pass(self, probe):
        probe.refuse_unless_relative(["tests/test_recall.py", "-q", "-p", "no:cacheprovider",
                                     "-m", "not full_tree", "--rootdir=/anything"])


class _FakeProc:
    """What ``run_pytest`` needs of a ``Popen``: an iterable stdout, ``wait``,
    ``kill``, ``pid``. ``lines`` may carry a float, which the iterator sleeps
    for -- the shape that drives the watchdog."""

    calls: list[dict] = []
    lines: list = ["collected 1 item\n", ". [100%]\n"]
    rc: int = 3

    def __init__(self, argv, **kwargs):
        _FakeProc.calls.append({"argv": list(argv), **kwargs})
        self.pid = 4242
        self.killed = False
        self.stdout = self._stream()

    def _stream(self):
        for item in _FakeProc.lines:
            if isinstance(item, float):
                time.sleep(item)
            else:
                yield item

    def wait(self):
        return -9 if self.killed else _FakeProc.rc

    def kill(self):
        self.killed = True


@pytest.fixture
def fake_popen(probe, monkeypatch):
    _FakeProc.calls.clear()
    _FakeProc.lines = ["collected 1 item\n", ". [100%]\n"]
    _FakeProc.rc = 3
    monkeypatch.setattr(probe.subprocess, "Popen", _FakeProc)
    return _FakeProc


class TestRunPytest:
    def test_the_runner_executes_exactly_the_built_command_in_the_target(self, probe, tmp_path, fake_popen):
        vpy = tmp_path / "venv" / "bin" / "python"
        target = tmp_path / "extracted" / "espalier-harness-x"
        args = ["tests/test_y.py", "-q"]
        env = {"PATH": "/usr/bin", probe.AUDIT_ENV: "1"}
        echoed: list[str] = []
        rc = probe.run_pytest(vpy, target, args, env, echo=echoed.append)
        assert rc == 3
        assert len(fake_popen.calls) == 1
        call = fake_popen.calls[0]
        assert call["argv"] == probe.build_pytest_command(vpy, args), (
            "the runner's literal prefix and build_pytest_command drifted apart"
        )
        assert call["cwd"] == str(target)
        assert call["env"] == env
        # The streaming kwargs: stderr folded into stdout, text mode, and on
        # POSIX its own session so a bound kill takes the workers with it.
        assert call["stdout"] is probe.subprocess.PIPE
        assert call["stderr"] is probe.subprocess.STDOUT
        assert call["text"] is True
        assert call["start_new_session"] is (sys.platform != "win32")
        assert echoed == ["collected 1 item", ". [100%]"]

    def test_a_child_past_the_bound_is_killed_with_its_group_and_exits_124(self, probe, tmp_path, fake_popen, monkeypatch):
        killed: list[int] = []

        def fake_kill_tree(proc):
            killed.append(proc.pid)
            proc.kill()

        monkeypatch.setattr(probe, "_kill_process_tree", fake_kill_tree)
        fake_popen.lines = ["collected 1 item\n", 0.3, "never\n"]
        echoed: list[str] = []
        rc = probe.run_pytest(tmp_path / "py", tmp_path, ["-q"], {}, timeout_s=0.05, echo=echoed.append)
        assert rc == probe.EXIT_TIMEOUT
        assert killed == [4242]
        assert any("was killed" in line for line in echoed)

    def test_the_exit_codes_sit_outside_pytests(self, probe):
        assert probe.EXIT_REFUSED == 70
        assert probe.EXIT_TIMEOUT == 124


# ── the steps' own refusals ────────────────────────────────────────────────


def _zip_with(tmp_path: Path, members: dict[str, bytes]) -> Path:
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return archive


class TestExtract:
    def test_two_top_level_directories_are_refused(self, probe, tmp_path):
        archive = _zip_with(tmp_path, {"a/x.txt": b"1", "b/y.txt": b"2"})
        with pytest.raises(probe.ProbeRefusal, match="2 top-level directories"):
            probe.extract(archive, tmp_path / "out")

    def test_a_shipped_git_directory_is_refused(self, probe, tmp_path):
        archive = _zip_with(tmp_path, {"a/x.txt": b"1", "a/.git/HEAD": b"ref"})
        with pytest.raises(probe.ProbeRefusal, match=r"carries \.git/"):
            probe.extract(archive, tmp_path / "out")

    def test_one_clean_root_is_returned(self, probe, tmp_path):
        archive = _zip_with(tmp_path, {"a/x.txt": b"1", "a/d/y.txt": b"2"})
        assert probe.extract(archive, tmp_path / "out") == tmp_path / "out" / "a"


class TestBuildArchive:
    def test_the_builders_refusal_is_the_probes(self, probe, tmp_path, monkeypatch):
        fake = types.ModuleType("build_release_archive")

        def refusing(root, *, output_dir=None):
            raise SystemExit("Refusing to build: not a repo root")

        fake.build_release_archive = refusing
        monkeypatch.setitem(sys.modules, "build_release_archive", fake)
        with pytest.raises(probe.ProbeRefusal, match="refused: Refusing to build"):
            probe.build_archive(tmp_path, tmp_path / "out")


class TestCleanWork:
    def test_only_what_the_probe_wrote_goes_and_a_borrowed_dir_stays(self, probe, tmp_path):
        work = tmp_path / "w"
        for name in ("archive_out", "extracted", "venv"):
            (work / name).mkdir(parents=True)
            (work / name / "f").write_text("x", encoding="utf-8")
        (work / "probe.log").write_text("log", encoding="utf-8")
        probe._clean_work(work, made_work=False)
        assert work.is_dir() and not any(work.iterdir())

    def test_a_dir_the_probe_made_goes_whole(self, probe, tmp_path):
        work = tmp_path / "w"
        (work / "venv").mkdir(parents=True)
        probe._clean_work(work, made_work=True)
        assert not work.exists()


# ── the refusals, in order ─────────────────────────────────────────────────


class TestRefusals:
    def test_no_pytest_arguments_refuses_before_any_write(self, probe, tmp_path, capsys):
        work = tmp_path / "w"
        assert probe.main(["--work-dir", str(work), "--"]) == probe.EXIT_REFUSED
        assert probe.main(["--work-dir", str(work)]) == probe.EXIT_REFUSED
        assert not work.exists()
        assert "REFUSED" in capsys.readouterr().out

    def test_an_absolute_test_path_refuses_before_any_write(self, probe, tmp_path):
        work = tmp_path / "w"
        rc = probe.main(["--work-dir", str(work), "--", str(REPO_ROOT / "tests" / "test_x.py")])
        assert rc == probe.EXIT_REFUSED
        assert not work.exists()

    def test_a_non_empty_work_dir_is_refused_before_any_build(self, probe, tmp_path, monkeypatch, capsys):
        # --clean removes the probe's entries and extract() clears `extracted/`:
        # a reusable path holding earlier receipts is refused before anything is
        # built (the 2026-09-23 reviews' shared finding).
        work = tmp_path / "w"
        work.mkdir()
        (work / "receipts.txt").write_text("mine\n", encoding="utf-8")

        def no_build(root, output_dir):
            raise AssertionError("built into a work dir that was not empty")

        monkeypatch.setattr(probe, "build_archive", no_build)
        assert probe.main(["--work-dir", str(work), "--clean", "--", "-q"]) == probe.EXIT_REFUSED
        assert (work / "receipts.txt").read_text(encoding="utf-8") == "mine\n"
        assert "not empty" in capsys.readouterr().out

    def test_a_tree_the_predicate_does_not_call_an_export_refuses(self, probe, tmp_path):
        # A bare directory: is_release_export is positive-confirmation-only and
        # answers False on any uncertainty, which is exactly the refusal shape.
        with pytest.raises(probe.ProbeRefusal, match="not a release export"):
            probe.refuse_unless_export(tmp_path)

    def test_this_checkout_is_not_an_export_so_the_guard_is_live_here(self, probe):
        # The refusal must fire on the DEV tree the probe builds from, or the
        # driven row below proves nothing about the precondition.
        with pytest.raises(probe.ProbeRefusal):
            probe.refuse_unless_export(REPO_ROOT)

    def test_the_export_refusal_comes_before_the_venv_and_before_pytest(self, probe, tmp_path, monkeypatch):
        """The isolated pin above does not prove `_main` asks before it runs
        pytest (the 2026-09-23 failure-mode review, F4): every step is stubbed
        here, the venv factory and a Popen must never be reached, and the
        refusal reason lands in probe.log."""
        work = tmp_path / "w"
        target = work / "extracted" / "espalier-harness-x"

        def fake_build(root, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)
            archive = output_dir / "x.zip"
            archive.write_bytes(b"")
            return archive

        def fake_extract(archive, extract_to):
            target.mkdir(parents=True)
            return target

        def never(*args, **kwargs):
            raise AssertionError("reached a step after the export precondition")

        monkeypatch.setattr(probe, "build_archive", fake_build)
        monkeypatch.setattr(probe, "extract", fake_extract)
        monkeypatch.setattr(probe, "_seed_git", lambda t, log: None)
        monkeypatch.setattr(probe, "_make_venv", never)
        monkeypatch.setattr(probe, "_run", never)
        monkeypatch.setattr(probe.subprocess, "Popen", never)
        ns = probe.parse_args(["--work-dir", str(work)])
        with pytest.raises(probe.ProbeRefusal, match="not a release export"):
            probe._main(ns, ["-q"])
        log = (work / "probe.log").read_text(encoding="utf-8")
        assert "=== REFUSED: " in log and "not a release export" in log


# ── the driven row ─────────────────────────────────────────────────────────


@pytest.mark.timeout(900)
def test_the_probe_drives_this_checkout_into_a_seeded_export(probe, tmp_path, capsys):
    """One real drive: the archive built from this checkout's index, extracted,
    seeded, a venv with the dev extra, one shipped module run inside it. Read
    the work dir, not the exit code alone: the extracted tree has the git a
    clone would have (tracked == on-disk), the predicate calls it an export,
    and the probe said so before pytest ran."""
    work = tmp_path / "w"
    rc = probe.main([
        "--work-dir", str(work), "--",
        "tests/test_export_guard.py", "-q", "-p", "no:cacheprovider",
    ])
    out = capsys.readouterr().out
    assert rc == 0, out[-3000:]
    roots = [p for p in (work / "extracted").iterdir() if p.is_dir()]
    assert len(roots) == 1, roots
    target = roots[0]
    assert (target / ".git").is_dir(), "the DEF-670 seed did not land"
    assert probe.surface_contract.is_release_export(target)
    assert "is a release export (surface_contract.is_release_export True)" in out
    # The seed's receipt: tracked == on disk, counted BEFORE the install (pip
    # and pytest leave egg-info and __pycache__ behind, so a walk afterwards
    # overcounts -- measured 1173 on disk against 1113 tracked).
    receipt = re.search(r"^probe: git seed: (\d+) tracked, (\d+) on disk$", out, re.M)
    assert receipt, out[-3000:]
    assert receipt.group(1) == receipt.group(2), receipt.group(0)
    # An oracle the probe did not write: the archive's own member list, against
    # the tracked set the seeded tree reports through the git oracle.
    archive = next((work / "archive_out").glob("*.zip"))
    with zipfile.ZipFile(archive) as zf:
        members = {n.split("/", 1)[1] for n in zf.namelist() if "/" in n and not n.endswith("/")}
    tracked = set(require_tracked_paths(target, minimum=500))
    assert tracked == members, (sorted(tracked ^ members)[:20], len(tracked), len(members))
    assert int(receipt.group(1)) == len(members)
    assert (work / "probe.log").is_file()
    assert (work / "venv").is_dir()
