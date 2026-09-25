"""TP-RELEASE-23 — smoke test for the final release matrix script.

The actual matrix is too long for a pytest run (full source-archive
build + extract + install is ~5-10 minutes). This test pins the
script's importability + the stage-runner signatures + the
``StageResult`` dataclass shape so a refactor of
``scripts/final_release_matrix.py`` cannot silently break the
manually-invoked release verification without anyone noticing
until cut-day. Without this guard, a renamed stage runner or a
dropped dataclass field would only surface during the actual
release attempt, which is the worst time to discover it.

To run the full matrix manually::

    python scripts/final_release_matrix.py
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import itertools
import json
import sys
import warnings
from pathlib import Path

import pytest

# slow-exempt: the only direct child spawns are the DEF-670 seed pins' three
# local git calls (init, add, commit) on a three-file scratch tree -- 0.55 s
# for the three tests, measured 2026-09-13. The one genuinely slow test here,
# the stage-one smoke, carries its own @pytest.mark.slow; marking the whole
# module would pull twenty fast pins out of the `not slow` slice.

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_SCRIPT = REPO_ROOT / "scripts" / "final_release_matrix.py"


def _import_matrix_module():
    spec = importlib.util.spec_from_file_location(
        "final_release_matrix", MATRIX_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so the @dataclass decorator can resolve
    # `cls.__module__` to a live module dict via `sys.modules.get(...)`.
    # Required whenever a module is loaded via importlib.util.spec_from_file_location
    # rather than a normal import — not Python-version-specific.
    sys.modules["final_release_matrix"] = module
    spec.loader.exec_module(module)
    return module


def test_script_exists():
    assert MATRIX_SCRIPT.exists(), "scripts/final_release_matrix.py missing"


def test_script_imports():
    mod = _import_matrix_module()
    assert hasattr(mod, "main")
    assert hasattr(mod, "StageResult")
    assert hasattr(mod, "stage_source_checkout")
    assert hasattr(mod, "stage_source_archive")
    assert hasattr(mod, "stage_sdist")
    assert hasattr(mod, "stage_wheel")
    assert hasattr(mod, "stage_artifact_cleanliness")


def test_stage_result_renders_pass():
    mod = _import_matrix_module()
    result = mod.StageResult(name="test_stage", status="PASS", duration_s=1.5)
    rendered = result.render()
    assert "test_stage" in rendered
    assert "PASS" in rendered
    assert "1.5" in rendered


def test_stage_result_renders_fail_with_reason():
    mod = _import_matrix_module()
    result = mod.StageResult(
        name="test_stage", status="FAIL",
        duration_s=2.5, reason="something broke",
    )
    rendered = result.render()
    assert "FAIL" in rendered
    assert "something broke" in rendered


def test_load_version_returns_string():
    mod = _import_matrix_module()
    version = mod._load_version()
    assert isinstance(version, str)
    assert version.count(".") >= 1, f"version doesn't look like semver: {version}"


def _import_wheel_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "wheel_smoke", REPO_ROOT / "scripts" / "wheel_smoke.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["wheel_smoke"] = module
    spec.loader.exec_module(module)
    return module


# ``win64``/``windows`` are the probe inputs: they are the only ``sys.platform``
# strings where the historical ``startswith("win")`` idiom diverged from
# ``== "win32"``. Including them earns the test's red -- it would have failed on
# the pre-parity code (one copy resolving to Scripts/, the other to bin/) and
# passes only because both copies now use the identical predicate. ``win32`` and
# the POSIX values pin the real-platform behavior.
@pytest.mark.parametrize("platform", ["win32", "linux", "darwin", "win64", "windows"])
def test_venv_python_parity_with_wheel_smoke(monkeypatch, platform):
    """``final_release_matrix._venv_python`` and ``wheel_smoke._venv_python`` are
    deliberately duplicated (each script must run standalone in a fresh venv, so a
    shared import is avoided). They must resolve the interpreter path identically
    on every platform; this pins that behavioral parity so the two copies cannot
    drift back apart.
    """
    matrix = _import_matrix_module()
    wheel_smoke = _import_wheel_smoke_module()
    monkeypatch.setattr(sys, "platform", platform)
    venv = Path("/fake/venv")
    assert matrix._venv_python(venv) == wheel_smoke._venv_python(venv)


@pytest.mark.slow
@pytest.mark.timeout(2400)  # TP-148 148-B: stage_source_checkout() spawns the
# full non-slow suite as a child -- about ten minutes on the self-host box
# (604 s measured 2026-09-23), bounded INSIDE the stage by `_SMOKE_BOUND_S`
# (twice the leg recorded in scripts/release_check.py). This outer timeout
# sits above the SUM of the stage's own bounds -- the driven row below pins
# that ordering -- so a slow leg is reported by the stage as a FAIL with its
# log (surfaced as a warning here), never by this wrapper as a bare timeout;
# the global 60s thread-timeout (set for fast unit tests) would otherwise fire
# on this one test and keep unfiltered `pytest -q` red even after the
# version-stamp fix.
def test_stage_one_source_checkout_smoke(tmp_path, monkeypatch):
    """Run stage 1 only (source-checkout) end-to-end. This is the
    fastest stage; the full matrix is too long for default pytest.

    Marked slow so it's opt-in via ``pytest -m slow``.
    """
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "matrix_out")
    mod._setup_output_dir()
    result = mod.stage_source_checkout()
    assert isinstance(result, mod.StageResult)
    assert result.status in ("PASS", "FAIL")
    if result.status == "FAIL":
        # Surface, never gate: this is a harness smoke, but a swallowed FAIL is
        # how a slow leg hid (2026-09-23) -- the reporting path the mark's
        # comment promises has to exist.
        warnings.warn(f"stage 01 FAILED: {result.reason}; log {result.log_path}", stacklevel=1)
    assert result.duration_s > 0


# ---------------------------------------------------------------------------
# Exit-time workspace pruning
#
# ``_setup_output_dir`` wipes OUTPUT_ROOT at the START of a run, so nothing
# reclaims a completed run's scratch until the NEXT run -- measured live at
# 132.8 MB of venvs in a 169.5 MB workspace against a single 137-byte surviving
# log. The logs ARE this script's deliverable, so the cleanup must be surgical.
#
# A real matrix run is minutes, so both tests drive a synthetic OUTPUT_ROOT.
# ---------------------------------------------------------------------------

# Mirrors the real layout: each stage builds ``<stage>_work/venv`` next to the
# artifacts it produces (see stage_source_archive / stage_sdist / stage_wheel).
_WORK_STAGES = ("source_archive_work", "sdist_work", "wheel_work")


def _seed_workspace(root: Path) -> None:
    """Build a workspace shaped like a completed matrix run."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "01_source_checkout.log").write_text("stage log\n", encoding="utf-8")
    (root / "final_report.json").write_text("{}\n", encoding="utf-8")
    for stage in _WORK_STAGES:
        venv_dir = root / stage / "venv"
        venv_bin = venv_dir / "bin"
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        # The interpreter's own venv marker -- what the prune actually keys on,
        # rather than the directory's name.
        (venv_dir / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
        # A real stage keeps its built artifact OUTSIDE the venv; the prune
        # must not take it.
        out_dir = root / stage / f"{stage.split('_work')[0]}_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "artifact.bin").write_bytes(b"artifact")


def _surviving(root: Path) -> tuple[list[Path], list[Path]]:
    venvs = sorted(root.glob("*_work/venv"))
    keepers = sorted(
        p for p in root.rglob("*") if p.is_file() and "venv" not in p.parts
    )
    return venvs, keepers


def test_prune_work_venvs_drops_venvs_and_keeps_logs(tmp_path, monkeypatch):
    """Every ``*_work/venv`` is removed; every log, report and artifact stays.

    Earns its red at HEAD two ways: ``_prune_work_venvs`` does not exist
    (AttributeError), and nothing else removes the venvs.
    """
    root = tmp_path / "matrix_out"
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", root)
    _seed_workspace(root)

    venvs_before, keepers_before = _surviving(root)
    assert len(venvs_before) == len(_WORK_STAGES), "fixture did not seed the venvs"

    mod._prune_work_venvs()

    venvs_after, keepers_after = _surviving(root)
    assert venvs_after == [], f"work venvs survived the prune: {venvs_after}"
    assert keepers_after == keepers_before, (
        "prune took a non-venv file: "
        f"{sorted(set(keepers_before) - set(keepers_after))}"
    )


def test_prune_work_venvs_is_a_noop_when_workspace_absent(tmp_path, monkeypatch):
    """No workspace on disk is the normal state before the first run."""
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "never_created")
    mod._prune_work_venvs()  # must not raise


def test_main_prunes_work_venvs_on_the_fail_path(tmp_path, monkeypatch):
    """The half a naive 'clean up on success' placement misses.

    Drives ``main()`` with every stage forced to FAIL and confirms the venvs
    are still gone. Earns its red at HEAD: nothing prunes on either path, so
    the venvs survive a failing run exactly as they survive a passing one.
    """
    root = tmp_path / "matrix_out"
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", root)
    monkeypatch.setattr(sys, "argv", ["final_release_matrix.py"])
    # main() now removes the previous run's report files under REPO_ROOT /
    # "reports" at start (DEF-461); point it at the scratch tree or the
    # live reports/ loses its files mid-suite (the live-tree watch caught
    # exactly that on 2026-09-13). The version read follows REPO_ROOT too.
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_load_version", lambda: "0.0.0+test")

    def _failing_stage(name: str):
        def _run() -> "mod.StageResult":
            # A real stage creates its own work tree before failing.
            _seed_workspace(root)
            return mod.StageResult(
                name=name, status="FAIL", duration_s=0.01, reason="forced"
            )

        return _run

    for stage_attr in (
        "stage_source_checkout",
        "stage_source_archive",
        "stage_sdist",
        "stage_wheel",
        "stage_artifact_cleanliness",
        "stage_surface_matrix",
    ):
        monkeypatch.setattr(mod, stage_attr, _failing_stage(stage_attr))

    monkeypatch.setattr(mod, "_capture_archive_members", lambda: None)
    # Return a path UNDER REPO_ROOT: main() renders it via relative_to(REPO_ROOT),
    # which is pure path math and does not require the file to exist.
    monkeypatch.setattr(
        mod,
        "_write_final_report",
        lambda version, results, members, skipped=None: (
            mod.REPO_ROOT / "dist" / "report.json"
        ),
    )

    rc = mod.main()

    assert rc == 1, "forced-FAIL stages should exit non-zero"
    venvs_after, _ = _surviving(root)
    assert venvs_after == [], (
        f"work venvs survived a FAILING run: {venvs_after} -- the prune is on "
        "the success path only"
    )
    assert (root / "01_source_checkout.log").exists(), "the log is the deliverable"


def test_main_prunes_work_venvs_on_keyboard_interrupt(tmp_path, monkeypatch):
    """Ctrl-C is the likeliest early exit, and ``except Exception`` misses it.

    ``KeyboardInterrupt`` is a ``BaseException``, so the per-stage handler does
    not catch it and it propagates straight out of ``main``. A multi-minute pip
    install is exactly what an operator interrupts -- and an interrupted run
    strands the workspace for longer than a failing one. Only a ``finally``
    covers this.
    """
    root = tmp_path / "matrix_out"
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", root)
    monkeypatch.setattr(sys, "argv", ["final_release_matrix.py"])
    # main() now removes the previous run's report files under REPO_ROOT /
    # "reports" at start (DEF-461); point it at the scratch tree or the
    # live reports/ loses its files mid-suite (the live-tree watch caught
    # exactly that on 2026-09-13). The version read follows REPO_ROOT too.
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_load_version", lambda: "0.0.0+test")

    def _interrupting_stage() -> "mod.StageResult":
        _seed_workspace(root)
        raise KeyboardInterrupt

    monkeypatch.setattr(mod, "stage_source_checkout", _interrupting_stage)

    with pytest.raises(KeyboardInterrupt):
        mod.main()

    venvs_after, _ = _surviving(root)
    assert venvs_after == [], (
        f"work venvs survived Ctrl-C: {venvs_after} -- the prune is not in a "
        "finally, so the one exit path most likely to strand the workspace is "
        "the one it misses"
    )
    assert (root / "01_source_checkout.log").exists(), "the log is the deliverable"


# ---------------------------------------------------------------------------
# Stage 03's "does this artifact ship tests" discriminator
#
# MANIFEST.in does ``prune tests`` and then re-includes exactly one NON-test
# helper (``tests/_corpus_ref_resolver.py`` -- the shipped benchmark loads it by
# literal path). That made ``tests_dir.is_dir()`` True on an sdist carrying zero
# test files: pytest exits 5 (NO_TESTS_COLLECTED), stage_sdist's ``if rc != 0``
# fired, and stage 03 failed unconditionally, so ``ready_to_tag`` could never be
# true. Earned red, measured before the fix: a directory holding only
# ``_corpus_ref_resolver.py`` gives a real pytest exit code of 5.
#
# The lasting point is the discriminator, not the instance: directory-existence
# was unique by COINCIDENCE (true only while ``prune tests`` left the directory
# absent), file presence is unique by CONSTRUCTION (docs/FAILURE_MODES.md
# §13.21). These cases pin the distinction at N+1, not just at today's N.
# ---------------------------------------------------------------------------


def test_shipped_test_modules_ignores_a_non_test_helper(tmp_path):
    """The live sdist shape: tests/ exists, holds only the benchmark helper."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "_corpus_ref_resolver.py").write_text("# helper\n", encoding="utf-8")
    mod = _import_matrix_module()
    assert mod._shipped_test_modules(tests_dir) == [], (
        "a helper-only tests/ must read as 'ships no tests' -- treating it as "
        "'ships tests' is what made stage 03 unpassable"
    )


def test_shipped_test_modules_finds_both_pytest_default_patterns(tmp_path):
    """pyproject sets no python_files override, so BOTH defaults must count."""
    tests_dir = tmp_path / "tests"
    (tests_dir / "nested").mkdir(parents=True)
    (tests_dir / "test_alpha.py").write_text("", encoding="utf-8")
    (tests_dir / "beta_test.py").write_text("", encoding="utf-8")
    (tests_dir / "nested" / "test_gamma.py").write_text("", encoding="utf-8")
    (tests_dir / "_helper.py").write_text("", encoding="utf-8")
    mod = _import_matrix_module()
    found = {p.name for p in mod._shipped_test_modules(tests_dir)}
    assert found == {"test_alpha.py", "beta_test.py", "test_gamma.py"}, (
        f"expected both default patterns, recursively; got {sorted(found)}"
    )


def test_shipped_test_modules_handles_absent_directory(tmp_path):
    """The pre-re-include shape -- ``prune tests`` with nothing added back."""
    mod = _import_matrix_module()
    assert mod._shipped_test_modules(tmp_path / "tests") == []


def test_shipped_test_modules_is_not_fooled_by_an_empty_directory(tmp_path):
    """An empty tests/ ships no tests. Directory existence is not the signal."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    mod = _import_matrix_module()
    assert mod._shipped_test_modules(tests_dir) == []


# ---------------------------------------------------------------------------
# ``ready_to_tag`` and the stages that never ran (DEF-461)
#
# ``--skip`` drops a stage from ``results`` before the report is written, so
# ``fails == 0`` was true over whatever DID run and the report said ready over
# a stage nobody executed. A skipped stage is neither PASS nor FAIL: it is
# recorded by id, it withholds readiness, and the FINAL line says so.
# ---------------------------------------------------------------------------

_ALL_STAGE_ATTRS = (
    "stage_source_checkout",
    "stage_source_archive",
    "stage_sdist",
    "stage_wheel",
    "stage_artifact_cleanliness",
    "stage_surface_matrix",
)


def _drive_main_with_passing_stages(tmp_path, monkeypatch, *argv: str):
    """Run ``main()`` with every stage forced to PASS; return (rc, report)."""
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "matrix_out")
    # The report is written under REPO_ROOT / "reports" and rendered relative
    # to REPO_ROOT; pointing both at the scratch tree keeps the live
    # reports/ directory untouched.
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_load_version", lambda: "0.0.0+test")
    monkeypatch.setattr(mod, "_capture_archive_members", lambda: None)
    monkeypatch.setattr(sys, "argv", ["final_release_matrix.py", *argv])

    def _passing(name: str):
        return lambda: mod.StageResult(name=name, status="PASS", duration_s=0.01)

    for stage_attr in _ALL_STAGE_ATTRS:
        monkeypatch.setattr(mod, stage_attr, _passing(stage_attr))

    rc = mod.main()
    report_path = tmp_path / "reports" / "final_release_candidate_report.json"
    return rc, json.loads(report_path.read_text(encoding="utf-8"))


def test_a_skipped_stage_is_recorded_and_withholds_ready_to_tag(
    tmp_path, monkeypatch, capsys
):
    rc, report = _drive_main_with_passing_stages(
        tmp_path, monkeypatch, "--skip", "02", "--skip", "05",
    )
    assert rc == 0, "the stages that ran all passed; the exit code reports those"
    assert report["skipped"] == ["02", "05"], report
    assert report["ready_to_tag"] is False, (
        "ready_to_tag is true over two stages that never ran"
    )
    ran = [s["name"] for s in report["stages"]]
    assert "stage_source_archive" not in ran and "stage_artifact_cleanliness" not in ran
    assert report["summary"]["pass"] == 4 and report["summary"]["fail"] == 0
    out = capsys.readouterr().out
    assert "not ready to tag" in out.lower(), out
    assert "provably clean" not in out, (
        "the FINAL line claims every install path over a skipped stage"
    )


def test_every_stage_run_and_passed_is_ready_to_tag(tmp_path, monkeypatch, capsys):
    """The control: the flag still turns true when nothing was skipped."""
    rc, report = _drive_main_with_passing_stages(tmp_path, monkeypatch)
    assert rc == 0
    assert report["skipped"] == []
    assert report["ready_to_tag"] is True
    assert report["summary"]["pass"] == len(_ALL_STAGE_ATTRS)
    assert "provably clean" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Stage 02 seeds git in the extracted tree (DEF-670)
#
# The archive ships no ``.git/`` and the stage asserts as much -- then it used
# to run the suite in exactly that tree, where every arm that asks git a
# question either skipped fail-open (``if not tracked``) or, since
# ``tests/_git_oracle.py``, failed loudly on ``GitAnswerUnavailable``. Driven
# 2026-09-13 on the built archive: 21 failed in the no-git configuration, the
# bulk of them that oracle. The seed is derived from the tree itself.
# ---------------------------------------------------------------------------


def _git(tree: Path, *argv: str) -> str:
    import subprocess
    return subprocess.run(
        ["git", "-C", str(tree), *argv], capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def test_seed_git_tracks_every_shipped_file_and_commits(tmp_path):
    """``add -A`` obeys the archive's own .gitignore; the seed must not."""
    mod = _import_matrix_module()
    tree = tmp_path / "extracted"
    (tree / "pkg").mkdir(parents=True)
    (tree / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tree / "notes.md").write_text("shipped, yet ignored\n", encoding="utf-8")
    # The archive's .gitignore withholds a file the archive nevertheless ships
    # -- the DEF-632 shape (examples/ESPALIER_MEMORY.template.md).
    (tree / ".gitignore").write_text("notes.md\n", encoding="utf-8")
    log: list[str] = []

    error = mod._seed_git(tree, log)

    assert error is None, error
    tracked = set(_git(tree, "ls-files").split())
    assert tracked == {".gitignore", "pkg/a.py", "notes.md"}, tracked
    assert _git(tree, "status", "--porcelain") == "", "a clone's status is clean"
    assert _git(tree, "rev-parse", "--verify", "HEAD").strip(), "the seed commits"
    joined = "\n".join(log)
    assert "notes.md" in joined and "3 tracked, 3 on disk" in joined, joined


def test_seed_git_fails_the_stage_when_a_shipped_file_stays_untracked(
    tmp_path, monkeypatch
):
    """A file the seed cannot see falls back into the fail-open skip; say so."""
    mod = _import_matrix_module()
    tree = tmp_path / "extracted"
    tree.mkdir()
    (tree / "a.py").write_text("x = 1\n", encoding="utf-8")
    real_run = mod._run

    def _run_without_the_force_add(cmd, **kwargs):
        # Let every git call through except the force-add, so the withheld
        # file stays untracked and the count check has to catch it.
        if cmd[:3] == ["git", "add", "-f"]:
            return 0, ""
        return real_run(cmd, **kwargs)

    (tree / "withheld.txt").write_text("shipped\n", encoding="utf-8")
    (tree / ".gitignore").write_text("withheld.txt\n", encoding="utf-8")
    monkeypatch.setattr(mod, "_run", _run_without_the_force_add)
    log: list[str] = []

    error = mod._seed_git(tree, log)

    assert error is not None and "2 of 3" in error, (error, log)


def test_stage_two_seeds_git_after_asserting_the_archive_ships_none():
    """Order is the contract: assert no .git/, THEN give the tree one."""
    import ast as _ast
    src = MATRIX_SCRIPT.read_text(encoding="utf-8")
    fn = next(
        n for n in _ast.walk(_ast.parse(src))
        if isinstance(n, _ast.FunctionDef) and n.name == "stage_source_archive"
    )
    body = _ast.get_source_segment(src, fn) or ""
    assertion = body.find("extracted archive contains .git/")
    seed = body.find("_seed_git(")
    pytest_run = body.find('"pytest"')
    assert 0 <= assertion < seed < pytest_run, (assertion, seed, pytest_run)


def test_an_aborted_run_leaves_no_stale_report_behind(tmp_path, monkeypatch):
    """The previous run's proof must not outlive a run that never wrote one.

    `_write_final_report` is the LAST statement of main's try block, so any
    early exit -- the Ctrl-C the finally exists for -- used to leave the prior
    run's `ready_to_tag: true` on disk for the checklist to read.
    """
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "matrix_out")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_load_version", lambda: "0.0.0+test")
    monkeypatch.setattr(sys, "argv", ["final_release_matrix.py"])
    reports = tmp_path / "reports"
    reports.mkdir()
    stale_report = reports / "final_release_candidate_report.json"
    stale_report.write_text('{"ready_to_tag": true, "skipped": []}\n', encoding="utf-8")
    stale_members = reports / "final_release_candidate_archive_members.txt"
    stale_members.write_text("old member\n", encoding="utf-8")

    def _interrupting() -> "mod.StageResult":
        raise KeyboardInterrupt

    monkeypatch.setattr(mod, "stage_source_checkout", _interrupting)

    with pytest.raises(KeyboardInterrupt):
        mod.main()

    assert not stale_report.exists(), "a stale ready_to_tag: true survived an aborted run"
    assert not stale_members.exists(), "a stale member list survived an aborted run"


def test_the_slow_exempt_claim_still_covers_only_the_seed_pins():
    """`# slow-exempt:` forgives the WHOLE module; pin what it was measured over.

    The marker's measurement covers `_git` alone (three local git calls on a
    three-file tree). A future test that drives `main()` as a child process
    would inherit the exemption unmeasured; this arm makes it re-measure.
    """
    import ast as _ast
    tree = _ast.parse(Path(__file__).read_text(encoding="utf-8"))
    spawners = sorted({
        fn.name
        for fn in _ast.walk(tree)
        if isinstance(fn, _ast.FunctionDef)
        for n in _ast.walk(fn)
        if isinstance(n, _ast.Call)
        and isinstance(n.func, _ast.Attribute)
        and isinstance(n.func.value, _ast.Name)
        and n.func.value.id == "subprocess"
    })
    assert spawners == ["_git"], (
        f"{spawners} spawn children directly; the module-level slow-exempt was "
        "measured over `_git` alone (0.55 s, 2026-09-13). Re-measure and update "
        "the marker, or move the new test to a slow module."
    )


def test_run_turns_a_timeout_into_a_logged_failure(tmp_path):
    """A stage that outruns its bound must fail by its own path, log intact.

    The first git-seeded stage 02 (2026-09-13) hit the 1800 s bound; the
    TimeoutExpired escaped `_run`, the stage's `except Exception` filed it as
    `02_unknown`, and the stage log -- written only at the stage's end -- was
    never written, seed lines and all.
    """
    mod = _import_matrix_module()
    rc, out = mod._run(
        [sys.executable, "-c", "import sys, time; print('partial'); sys.stdout.flush(); time.sleep(30)"],
        cwd=tmp_path, timeout=1,
    )
    assert rc == 124, (rc, out)
    assert "TIMEOUT" in out and "exceeded 1s" in out and "PARTIAL" in out, out


# ---------------------------------------------------------------------------
# The two build stages clear the stale packaging state before the builder
# ---------------------------------------------------------------------------


def _drive_stage_to_the_builder(mod, tmp_path, monkeypatch, stage_name: str):
    """Run one build stage with the builder stubbed to fail, so the stage stops
    right after its ``python -m build`` call; return the recorded call order
    and the stage's log text."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "out")
    calls: list[str] = []

    def recording_clear(repo_root):
        assert repo_root == repo
        calls.append("clear")
        return [repo / "build"]

    def failing_run(cmd, **kwargs):
        calls.append("build" if cmd[1:3] == ["-m", "build"] else cmd[0])
        return 1, "stub: the builder is not run here"

    monkeypatch.setattr(mod, "clear_stale_packaging_state", recording_clear)
    monkeypatch.setattr(mod, "_run", failing_run)
    result = getattr(mod, stage_name)()
    assert result.status == "FAIL" and "build" in result.reason, result
    return calls, Path(result.log_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("stage_name", ["stage_sdist", "stage_wheel"])
def test_build_stages_clear_stale_state_before_the_builder(tmp_path, monkeypatch, stage_name):
    """Each build stage clears ``build/`` and the top-level egg-info before it
    calls the builder, and its log says what it cleared. RED with the call
    removed from that stage."""
    mod = _import_matrix_module()
    calls, log = _drive_stage_to_the_builder(mod, tmp_path, monkeypatch, stage_name)
    assert calls == ["clear", "build"], calls
    assert "stale packaging state cleared" in log and str(tmp_path / "repo" / "build") in log


# ---------------------------------------------------------------------------
# Every release_check call strips the opt-ins (the matrix runs those proofs
# as its own stages)
# ---------------------------------------------------------------------------


def test_every_release_check_call_strips_the_opt_ins():
    """Every ``_run`` of ``scripts/release_check.py`` hands over the strip list:
    a release_check that inherits the opt-in flags re-runs the suite and the
    wheel smoke inside the stage's 300 s timeout (stage 01 was killed at 300 s
    with both flags set on 2026-09-23 and reported ``release_check failed``
    with no check having failed). Derived from the source, so a third call
    site is covered the day it lands."""
    tree = ast.parse(MATRIX_SCRIPT.read_text(encoding="utf-8"))
    sites: list[tuple[int, str | None]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_run"):
            continue
        argv = node.args[0] if node.args else None
        names = [e.value for e in getattr(argv, "elts", []) if isinstance(e, ast.Constant)]
        if "scripts/release_check.py" not in names:
            continue
        strip = next((k.value for k in node.keywords if k.arg == "strip_env"), None)
        sites.append((node.lineno, ast.unparse(strip) if strip is not None else None))
    assert len(sites) == 2, sites  # stage 01 in the checkout, stage 02 in its venv
    assert all(value == "_RELEASE_CHECK_OPT_INS" for _, value in sites), sites


def test_stage_one_pytest_leg_is_bounded_by_the_derived_smoke_bound(tmp_path, monkeypatch):
    """Driven: stage 01 hands ``_run`` the derived ``_SMOKE_BOUND_S`` for its
    pytest leg, not a literal. The bare ``timeout=600`` this replaced sat
    inside one per cent of the leg's measured 592-604 s -- below the 604
    reading -- and killed it at 97 % on 2026-09-23 (8,352 tests run, no red)
    once the tree had gained tests, so the matrix read a green suite as a
    failed stage. The bound follows the rule ``_SUITE_BOUND_S`` states for the
    archive stages -- at least twice the recorded measurement -- and is
    derived from the figure recorded once in scripts/release_check.py, whose
    ``check_tests_pass`` runs the same leg. The smoke test above must also
    out-wait the SUM of the stage's own bounds, or it would report a slow leg
    as a bare timeout and drop the log."""
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "out")
    (tmp_path / "out").mkdir()
    default_timeout = inspect.signature(mod._run).parameters["timeout"].default  # the real runner's
    seen: list[tuple[list[str], dict]] = []

    def recording_run(cmd, **kwargs):
        seen.append((list(cmd), dict(kwargs)))
        return 0, "stub: passed"

    monkeypatch.setattr(mod, "_run", recording_run)
    result = mod.stage_source_checkout()
    assert result.status == "PASS", result
    pytest_calls = [kw for cmd, kw in seen if "pytest" in cmd]
    assert len(pytest_calls) == 1, seen
    assert pytest_calls[0]["timeout"] == mod._SMOKE_BOUND_S, pytest_calls
    assert mod._SMOKE_BOUND_S == 2 * mod._SMOKE_MEASURED_S
    assert mod._SMOKE_BOUND_S < mod._SUITE_BOUND_S  # a smoke, not the suite
    inner = sum(kw.get("timeout", default_timeout) for _, kw in seen)
    mark = next(m for m in test_stage_one_source_checkout_smoke.pytestmark if m.name == "timeout")
    assert mark.args[0] > inner, (mark.args[0], inner, seen)


def test_stage_one_reports_a_timed_out_leg_as_a_bound_not_a_red(tmp_path, monkeypatch):
    """``_run`` returns 124 with the partial transcript when its bound fires;
    the stage's reason then says TIMED OUT and names the bound. On 2026-09-23
    the same event read ``pytest failed; see log`` in the report and cost an
    hour of misdiagnosis on a leg with no red in it."""
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "out")
    (tmp_path / "out").mkdir()

    def timing_out_run(cmd, **kwargs):
        if "pytest" in cmd:
            return 124, "partial transcript\n[final_release_matrix] TIMEOUT: killed"
        return 0, "stub"

    monkeypatch.setattr(mod, "_run", timing_out_run)
    result = mod.stage_source_checkout()
    assert result.status == "FAIL", result
    assert "TIMED OUT" in result.reason and str(mod._SMOKE_BOUND_S) in result.reason, result.reason
    assert "pytest failed" not in result.reason, result.reason
    # a real red keeps the plain reason, byte for byte
    monkeypatch.setattr(mod, "_run", lambda cmd, **kw: (1, "1 failed") if "pytest" in cmd else (0, ""))
    assert mod.stage_source_checkout().reason == "pytest failed; see log"


def test_stage_one_notes_a_passing_leg_that_outgrew_the_recorded_measurement(tmp_path, monkeypatch):
    """The ratchet on the recorded figure: a leg that PASSES but took longer
    than ``_SMOKE_MEASURED_S`` carries a NOTE in the stage's report ``details``
    (a PASS writes no log) naming the constant to re-measure, so the figure
    is refreshed on the first slow green day rather than discovered on the
    first red one."""
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "out")
    (tmp_path / "out").mkdir()
    clock = itertools.count(0.0, float(mod._SMOKE_MEASURED_S) + 1.0)
    monkeypatch.setattr(mod, "_now", lambda: next(clock))
    monkeypatch.setattr(mod, "_run", lambda cmd, **kw: (0, "stub"))
    result = mod.stage_source_checkout()
    assert result.status == "PASS", result
    assert "NOTE: the not-slow leg took" in result.details, result
    assert "NOT_SLOW_LEG_MEASURED_S" in result.details, result
    # and a leg inside the recorded figure carries no note
    monkeypatch.setattr(mod, "_now", lambda: 0.0)
    result = mod.stage_source_checkout()
    assert result.status == "PASS" and result.details == "", result


def test_stage_one_release_check_runs_without_the_opt_ins(tmp_path, monkeypatch):
    """Driven: with both flags in the environment, stage 01's release_check call
    hands ``_run`` the strip list (its pytest call already did; the release_check
    call did not, and inherited a ten-minute nested suite)."""
    mod = _import_matrix_module()
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path / "out")
    (tmp_path / "out").mkdir()
    for flag in mod._RELEASE_CHECK_OPT_INS:
        monkeypatch.setenv(flag, "1")
    seen: list[tuple[list[str], dict]] = []

    def recording_run(cmd, **kwargs):
        seen.append((list(cmd), dict(kwargs)))
        if "scripts/release_check.py" in cmd:
            return 1, "stub: the stage stops here"
        return 0, "stub: pytest passed"

    monkeypatch.setattr(mod, "_run", recording_run)
    result = mod.stage_source_checkout()
    assert result.status == "FAIL" and "release_check" in result.reason, result
    release_check_calls = [kw for cmd, kw in seen if "scripts/release_check.py" in cmd]
    assert len(release_check_calls) == 1, seen
    assert tuple(release_check_calls[0].get("strip_env", ())) == tuple(mod._RELEASE_CHECK_OPT_INS)
