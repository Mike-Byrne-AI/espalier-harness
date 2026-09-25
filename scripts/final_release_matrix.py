#!/usr/bin/env python
"""Final release proof matrix - one command, six proofs.

Run from the repo root:

    python scripts/final_release_matrix.py

Exit codes:

- 0: every stage passed; the release is provably clean across every
     install path Espalier supports.
- 1: at least one stage failed; output names the failing stage(s).

Each stage emits a single line:

    STAGE_NAME ... PASS  (time: 12.3s)
    STAGE_NAME ... FAIL  (time: 4.1s)  reason: <one line>

Detailed logs are written to ``dist/final-release-matrix/<stage>.log``
for any FAIL.

The script is idempotent - running it twice on a clean tree produces
the same result. Temp directories are cleaned between stages.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
try:
    import tomllib  # Python 3.11+
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Make the gate work whether espalier is installed or run from the source
# tree, and let stages that import the ``tests`` package (stage 05's archive
# denylist) resolve it. A script's sys.path[0] is its OWN dir (``scripts/``),
# not the repo root, so a bare ``python scripts/final_release_matrix.py``
# resolves neither ``import espalier`` nor ``from tests...`` without this — the
# same bootstrap the sibling ``build_release_archive.py`` already carries.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Safe-extraction helpers shared from ``espalier/_archive_safety`` so
# non-script consumers reuse the same member-validation discipline.
from espalier._archive_safety import safe_extract_tar, safe_extract_zip  # noqa: E402
from espalier.artifact_parity import clear_stale_packaging_state  # noqa: E402

OUTPUT_ROOT = REPO_ROOT / "dist" / "final-release-matrix"

# release_check.py Tier-1 opt-ins: they tell release_check to actually shell
# out (nested pytest / wheel build) instead of SKIP. The matrix runs those
# proofs as its OWN stages, so the raw suite stages (01/02) must NOT inherit
# them — otherwise test_release_check's aggregator tests (which call
# run_all_checks/main) re-spawn a nested suite or wheel build mid-stage and
# blow the per-test timeout under contention.
#
# IMPORTED, not re-listed. This was a hand-kept 2-element copy whose comment
# claimed it "mirrors check_tests_pass's own child-env strip" — which was false
# in both directions at once: check_tests_pass stripped ONE flag, and this copy
# omitted ESPALIER_RELEASE_CHECK_WITH_URLS. Two hand-maintained copies of one
# set, already divergent, each describing the other as its authority. The set
# now has exactly one home.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from release_check import OPT_IN_ENV_FLAGS as _RELEASE_CHECK_OPT_INS  # noqa: E402
# The `not slow` leg's recorded measurement and its derived bound live beside
# the check that runs the same leg (`check_tests_pass`); stage 01 imports them
# for the reason the flag set above is imported -- one home.
from release_check import NOT_SLOW_LEG_BOUND_S as _SMOKE_BOUND_S  # noqa: E402
from release_check import NOT_SLOW_LEG_MEASURED_S as _SMOKE_MEASURED_S  # noqa: E402


@dataclass
class StageResult:
    name: str
    status: str  # "PASS" or "FAIL"
    duration_s: float
    reason: str = ""
    log_path: Path | None = None
    details: str = ""

    def render(self) -> str:
        line = f"{self.name:<32} ... {self.status:<4}  (time: {self.duration_s:5.1f}s)"
        if self.status == "FAIL":
            line += f"  reason: {self.reason}"
        return line


def _load_version() -> str:
    pyproject = REPO_ROOT / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def _setup_output_dir() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True)


def _prune_work_venvs() -> None:
    """Drop each stage's throwaway venv, keeping every log and report.

    ``_setup_output_dir`` wipes OUTPUT_ROOT at the START of a run, so without
    this the venvs survive until the NEXT run -- measured at 132.8 MB of a
    169.5 MB workspace (78%), against a single 137-byte surviving log. The
    logs ARE this script's deliverable, so exit-time cleanup must be
    surgical: venvs only, never the whole tree.

    Called from ``main`` inside a ``finally`` so every exit path cleans up --
    pass, fail, raise, and Ctrl-C. An interrupted run is exactly when the
    workspace is most likely to sit untouched for days.

    Venvs are located by ``pyvenv.cfg``, the interpreter's own marker, rather
    than by globbing a ``*_work/venv`` naming convention: the convention is
    maintained by hand in three separate stage functions and would drift
    silently, whereas the marker is what *makes* a directory a venv.
    """
    if not OUTPUT_ROOT.exists():
        return
    for marker in sorted(OUTPUT_ROOT.rglob("pyvenv.cfg")):
        venv_dir = marker.parent
        if not venv_dir.is_dir():
            continue
        shutil.rmtree(venv_dir, ignore_errors=True)
        if venv_dir.exists():
            # ignore_errors swallows the reason, and this function's whole
            # purpose is reclaiming a measured 132.8 MB -- a silent failure
            # means that problem persists with no trace. Say so.
            print(
                f"  warning: could not remove {venv_dir}; workspace not fully "
                "reclaimed",
                file=sys.stderr,
            )


def _write_log(stage: str, content: str) -> Path:
    log_path = OUTPUT_ROOT / f"{stage}.log"
    log_path.write_text(content, encoding="utf-8")
    return log_path


#: Outer bound on the extracted-tree pytest runs (stages 02 and 03). The suite
#: runs SERIALLY there -- the stage inherited that shape; the venv it builds
#: installs the ``dev`` extra, so pytest-xdist IS present and unused (DEF-918
#: rows the move to the proof tier's two-line form) -- and it has outgrown the
#: 1800 s this used to be: driven 2026-09-13, the first git-seeded stage 02
#: (12,857 tests) hit the bound and the stage died as "unhandled exception:
#: timed out", its log never written. The same selection at 4 xdist workers
#: took 12:01 wall / 2,151 CPU-seconds, so serial was about 36 min on this
#: box then; the same leg measured 45 min (2,711 s, 17,397 tests) on
#: 2026-09-23. The bound is 7200 s -- about 2.7x that, never less than twice
#: the measurement, clear of slower CI hardware -- because a bound trimmed to
#: the measurement fires on a slow day (the older comment below says why).
#: Per-test hangs are pytest-timeout's job, not this one's.
_SUITE_BOUND_S = 7200

#: The source-checkout smoke (stage 01) runs the dev tree's `not slow` slice
#: serially in this checkout, the leg `scripts/release_check.py`'s
#: `check_tests_pass` also runs, so its recorded measurement and bound are
#: imported from there (`_SMOKE_MEASURED_S`, `_SMOKE_BOUND_S`, above) rather
#: than typed here: the same rule as `_SUITE_BOUND_S`, at least twice the
#: measurement. The bare `timeout=600` that stood here killed the leg at 97 %
#: on 2026-09-23 (8,352 tests run, no red) once the tree had gained tests --
#: one per cent of headroom fires on the first slow day and, until
#: `_failed_reason` below, read as a failed suite. Pinned by driven rows in
#: tests/test_final_release_matrix.py.
_now = time.monotonic  # the leg's own clock, injectable by the driven rows


def _failed_reason(rc: int, plain: str, what: str, bound: int) -> str:
    """A stage's reason for a non-zero `_run`: `plain` for a real red, and for
    124 -- the runner's own bound firing, returned with the partial transcript
    -- a reason that says so and names the bound. The two must not read alike
    in the report: on 2026-09-23 stage 01's timed-out leg was filed as
    `pytest failed; see log` and read as a failed suite until the log's last
    line was found."""
    if rc == 124:
        return (f"{what} TIMED OUT at {bound}s -- a bound, not a red; "
                "re-measure the recorded leg; see log")
    return plain

#: Ambient git env that re-points every git command at a DIFFERENT repository
#: (`git bisect run`, `git rebase --exec`, any hook). Inherited into the seed
#: below, `git init` would re-initialise the operator's repo and `git add -A`
#: would stage the extract over the live index. The same six keys as
#: tests/_git_oracle.py, scripts/record_snapshot.py and espalier/cli.py;
#: parity is pinned by tests/test_git_oracle.py, not claimed here.
_GIT_REDIRECT_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
)


def _as_text(stream: "bytes | str | None") -> str:
    """``TimeoutExpired`` hands back whatever was captured: bytes, str or None."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    strip_env: tuple[str, ...] = (),
    timeout: int = 600,
) -> tuple[int, str]:
    """Run a subprocess; return (returncode, combined_output)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    for key in strip_env:
        full_env.pop(key, None)
    try:
        # subprocess-contract: ok release-matrix-generic-runner-callers-pin-each-CLI
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=full_env,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, ValueError) as exc:
        # A timeout used to escape as an unhandled exception: the stage's
        # `except Exception` filed it as `<stage>_unknown` and the stage's log,
        # written only at its end, was lost with everything the run had said
        # (the first git-seeded stage 02, 2026-09-13). Return it as a failed
        # run with the partial transcript, so the stage fails by its own path
        # and writes its log. 124 is GNU timeout's exit code for the same event.
        partial = [
            _as_text(stream)
            for stream in (exc.stdout, exc.stderr)
        ]
        return 124, (
            partial[0] + "\n" + partial[1]
            + f"\n[final_release_matrix] TIMEOUT: {cmd[0]!r} exceeded {timeout}s; "
            "the transcript above is PARTIAL -- the run was killed, not finished."
        )
    # Observed on the Windows CI runner: `stdout` came back None even though
    # capture_output=True was set, while `stderr` decoded normally, so the bare
    # concatenation raised TypeError and killed the stage. The mechanism is NOT
    # established -- there is no interceptor, no test double, and PIPE is
    # requested -- so this does not claim to fix a known cause; it stops an
    # unset stream from crashing the runner.
    #
    # Deliberately NOT a silent `or ""`: an empty transcript reads as "the stage
    # produced no output", which is indistinguishable from success to every
    # caller that greps this string. If a stream is unset, say so IN the
    # transcript so the failure stays visible.
    missing = [n for n, v in (("stdout", result.stdout), ("stderr", result.stderr)) if v is None]
    out = result.stdout or ""
    err = result.stderr or ""
    if missing:
        err += (
            f"\n[final_release_matrix] WARNING: subprocess returned no {'/'.join(missing)} "
            f"stream despite capture_output=True (cmd: {cmd[0]!r}). Output below is "
            f"INCOMPLETE -- do not read an empty transcript as a clean run."
        )
    return result.returncode, out + "\n" + err


def _venv_python(venv_dir: Path) -> Path:
    """Path to a venv's python interpreter (Windows vs POSIX).

    Parallels scripts/wheel_smoke.py::_venv_python. Both scripts run standalone
    in fresh venvs, so a shared import is deliberately avoided; instead the two
    copies use the identical ``sys.platform == "win32"`` idiom (also matching
    wheel_smoke's sibling ``_venv_executable``) and their behavioral parity is
    pinned by tests/test_final_release_matrix.py::
    test_venv_python_parity_with_wheel_smoke so they cannot drift.
    """
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _seed_git(target: Path, log_parts: list[str]) -> str | None:
    """Give the extracted tree the git a clone would have; None or a reason.

    Stage 02 asserts the archive ships no ``.git/`` and then used to run
    pytest in exactly that tree, where every arm that asks git a question --
    the ``git ls-files``-derived contracts, the citation resolvers, the
    census -- skipped fail-open on ``if not tracked``, so the validator could
    not see the failures of the tree it validates. Driven 2026-09-02 on
    three modules: 1 failed and 9 skipped with no git, 4 failed once seeded
    (DEF-670).

    The seed is derived, never typed. ``git add -A`` first; then every file
    ``--exclude-standard`` withholds -- the archive's own ``.gitignore``, and
    on the host that runs the matrix its ``core.excludesFile`` and
    ``.git/info/exclude`` too -- is force-added (one on 2026-09-13,
    ``examples/ESPALIER_MEMORY.template.md``, which ``git add -A`` dropped
    silently in the DEF-632 drive); then one commit, so the tree answers
    ``git status`` and ``HEAD`` the way a clone does. Every call strips the
    repo-redirecting env (``_GIT_REDIRECT_ENV``), the init takes no template
    and the commit runs no hook path and signs nothing, so the operator's
    shell config cannot reach the seed. The tracked count must equal the
    on-disk count: a shipped file the seed cannot see would fall straight back
    into the fail-open skip this step exists to close, so a mismatch fails the
    stage, and the message says which side is short. A path carrying a newline
    is dropped from both listings (the NUL-split has to shed ``_run``'s
    trailing stderr chunk); none ships, and one would fail the count loudly.
    """
    def git(*args: str) -> tuple[int, str]:
        return _run(
            ["git", *args], cwd=target, timeout=300, strip_env=_GIT_REDIRECT_ENV,
        )

    def paths(out: str) -> list[str]:
        # -z: NUL-separated, never quoted. _run appends "\n" + stderr after
        # stdout, so the last chunk carries a newline and is not a path.
        return [p for p in out.split("\0") if p and "\n" not in p]

    log_parts.append("=== git seed (DEF-670) ===")
    for args in (("-c", "init.templateDir=", "init", "-q"), ("add", "-A")):
        rc, out = git(*args)
        log_parts.append(out)
        if rc != 0:
            return f"git seed failed at `git {' '.join(args)}`"

    rc, out = git("ls-files", "-z", "--others", "--ignored", "--exclude-standard")
    if rc != 0:
        log_parts.append(out)
        return "git seed could not list the files the ignore rules withhold"
    withheld = paths(out)
    if withheld:
        log_parts.append(
            f"force-adding {len(withheld)} file(s) the ignore rules withhold: "
            f"{', '.join(withheld)}"
        )
        rc, out = git("add", "-f", "--", *withheld)
        log_parts.append(out)
        if rc != 0:
            return "git seed could not force-add the withheld files"

    rc, out = git(
        "-c", "user.name=espalier-release",
        "-c", "user.email=release@espalier.invalid",
        "-c", "commit.gpgsign=false",
        "-c", "core.hooksPath=",
        "commit", "-q", "--no-verify", "-m", "release archive seed",
    )
    log_parts.append(out)
    if rc != 0:
        return "git seed could not commit"

    rc, out = git("ls-files", "-z")
    if rc != 0:
        log_parts.append(out)
        return "git seed could not list the tracked files"
    tracked = len(paths(out))

    # The walk must see every shipped file, or the count check accuses the
    # index of the walk's own blindness: an unreadable directory is logged,
    # never swallowed, and a symlink to a directory -- one index entry, filed
    # under dirnames by os.walk and never descended -- counts as the one file
    # it is.
    on_disk = 0
    walk_errors: list[str] = []
    for dirpath, dirnames, filenames in os.walk(
        target, onerror=lambda err: walk_errors.append(str(err)),
    ):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        on_disk += len(filenames)
        on_disk += sum(
            1 for d in dirnames if os.path.islink(os.path.join(dirpath, d))
        )
    for err in walk_errors:
        log_parts.append(f"walk error: {err}")
    log_parts.append(f"git seed: {tracked} tracked, {on_disk} on disk")
    if tracked < on_disk:
        return (
            f"git seed tracks {tracked} of {on_disk} shipped files; an "
            "untracked file is invisible to every git-derived gate"
        )
    if tracked > on_disk:
        short = f" ({len(walk_errors)} walk error(s) logged)" if walk_errors else ""
        return (
            f"git tracks {tracked} files but the walk saw {on_disk}: the walk "
            f"is short, not the index{short}"
        )
    return None


def _make_venv(work_dir: Path, log_parts: list[str]) -> tuple[Path | None, str]:
    """Create a fresh venv under work_dir and return (venv_python_path, "")
    on success, or (None, error_message) on failure.

    Used by stages 2 and 3 so the editable install of the extracted tree
    doesn't pollute (or get refused by) the host Python. Homebrew Python
    on macOS is PEP 668 externally-managed; system Python on modern
    Debian/Ubuntu is similar. CI runners using a fresh `python -m venv`
    are unaffected, but using a per-stage venv normalizes behavior across
    all hosts.
    """
    venv_dir = work_dir / "venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    log_parts.append(f"=== create venv at {venv_dir} ===")
    rc, out = _run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=work_dir,
        timeout=120,
    )
    log_parts.append(out)
    if rc != 0:
        return None, "venv creation failed"
    return _venv_python(venv_dir), ""


# ---------------------------------------------------------------------------
# Stage 1 — Source checkout proof
# ---------------------------------------------------------------------------


def stage_source_checkout() -> StageResult:
    name = "01_source_checkout"
    t0 = time.monotonic()
    log_parts: list[str] = []

    def fail(reason: str) -> StageResult:
        return StageResult(
            name=name, status="FAIL",
            duration_s=time.monotonic() - t0,
            reason=reason,
            log_path=_write_log(name, "\n".join(log_parts)),
        )

    log_parts.append("=== pytest (non-slow) ===")
    # `not slow` STAYS here, deliberately -- and the reason has to be written
    # down, because stage 02 twelve hundred lines below now argues the exact
    # opposite for the archive lane. The asymmetry is real: as of 2026-08-14 the
    # matrix verifies the extracted ARCHIVE more thoroughly than the source
    # checkout it is a proof of.
    #
    # That is intentional, not an oversight. This stage is a smoke: its job is
    # to fail fast on a source tree that is obviously broken before spending
    # three quarters of an hour building and testing an archive from it (stage
    # 02 measured 45 min serial on 2026-09-23). The dev tree's full suite
    # already has two owners -- `.github/workflows/test.yml` runs a bare
    # `pytest -q` on every push, including the clean-checkout job, and locally
    # `scripts/fresh_clone_gate.py` runs the full tier in a fresh clone of HEAD
    # per interpreter as Tier 3 step 0, before this matrix -- whereas
    # NOTHING but stage 02 ever ran the slow lane against an export, which is
    # precisely why `not slow` was load-bearing there and is not here.
    #
    # If CI ever stops running the full suite on push, this carve becomes a real
    # hole and must go. Flagged by the adversarial pass as a sister-site gap;
    # kept, with the rationale recorded rather than left to inference.
    leg_t0 = _now()
    rc, out = _run(
        [sys.executable, "-m", "pytest", "-q", "-m", "not slow"],
        cwd=REPO_ROOT,
        strip_env=_RELEASE_CHECK_OPT_INS,
        timeout=_SMOKE_BOUND_S,
    )
    leg_s = _now() - leg_t0
    log_parts.append(out)
    if rc != 0:
        return fail(_failed_reason(rc, "pytest failed; see log", "pytest", _SMOKE_BOUND_S))
    note = ""
    if leg_s > _SMOKE_MEASURED_S:
        # The ratchet: a passing leg that outgrew the recorded figure says so
        # on the day it passes, not on the day the bound fires. A PASS writes
        # no log, so the note rides the report's per-stage `details`.
        note = (
            f"NOTE: the not-slow leg took {leg_s:.0f}s, over the recorded "
            f"{_SMOKE_MEASURED_S}s (bound {_SMOKE_BOUND_S}s) -- re-measure "
            "NOT_SLOW_LEG_MEASURED_S in scripts/release_check.py"
        )
        log_parts.append(f"[final_release_matrix] {note}")

    log_parts.append("=== release_check ===")
    # The opt-ins are stripped here as they are for the pytest call above: a
    # release_check that inherits them re-runs the suite and the wheel smoke
    # inside this 300 s timeout (killed at 300 s with both flags set on
    # 2026-09-23, reported as `release_check failed` though no check had
    # failed); the matrix runs those proofs as its own stages.
    rc, out = _run(
        [sys.executable, "scripts/release_check.py"],
        cwd=REPO_ROOT,
        strip_env=_RELEASE_CHECK_OPT_INS,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail(_failed_reason(rc, "release_check failed", "release_check", 300))

    log_parts.append("=== self-host --mode source-checkout ===")
    rc, out = _run(
        [sys.executable, "-m", "espalier.cli", "self-host", str(REPO_ROOT),
         "--mode", "source-checkout"],
        cwd=REPO_ROOT,
        timeout=120,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("self-host source-checkout failed")

    return StageResult(
        name=name, status="PASS",
        duration_s=time.monotonic() - t0,
        details=note,
    )


# ---------------------------------------------------------------------------
# Stage 2 — Source archive proof
# ---------------------------------------------------------------------------


def stage_source_archive() -> StageResult:
    name = "02_source_archive"
    t0 = time.monotonic()
    log_parts: list[str] = []

    def fail(reason: str) -> StageResult:
        return StageResult(
            name=name, status="FAIL",
            duration_s=time.monotonic() - t0,
            reason=reason,
            log_path=_write_log(name, "\n".join(log_parts)),
        )

    work_dir = OUTPUT_ROOT / "source_archive_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    archive_out = work_dir / "archive_out"
    archive_out.mkdir(exist_ok=True)
    extract_to = work_dir / "extracted"
    if extract_to.exists():
        shutil.rmtree(extract_to)
    extract_to.mkdir()

    log_parts.append("=== build_release_archive ===")
    rc, out = _run(
        [sys.executable, "scripts/build_release_archive.py",
         "--output-dir", str(archive_out)],
        cwd=REPO_ROOT,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("build_release_archive failed")

    zips = list(archive_out.glob("*.zip"))
    if not zips:
        return fail("no .zip produced")
    archive = zips[0]
    log_parts.append(f"Archive: {archive.name} ({archive.stat().st_size} bytes)")

    log_parts.append("=== extract ===")
    try:
        with zipfile.ZipFile(archive) as zf:
            safe_extract_zip(zf, extract_to)
    except (zipfile.BadZipFile, OSError) as e:
        return fail(f"archive extract failed: {e}")
    extracted_roots = [p for p in extract_to.iterdir() if p.is_dir()]
    if not extracted_roots:
        return fail("archive extracted no top-level directory")
    target = extracted_roots[0]
    log_parts.append(f"Extracted to: {target}")

    if (target / ".git").exists():
        return fail("extracted archive contains .git/")

    # The archive ships without git; the suite then runs in a tree that HAS
    # it, because that is the tree a clone gives an adopter and because the
    # arms that ask git a question skip fail-open without it (DEF-670).
    seed_error = _seed_git(target, log_parts)
    if seed_error:
        return fail(seed_error)

    venv_python, err = _make_venv(work_dir, log_parts)
    if venv_python is None:
        return fail(err)

    log_parts.append("=== pip install + pytest (in venv) ===")
    rc, out = _run(
        [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=target,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("pip install -e .[dev] failed on extracted archive")

    rc, out = _run(
        # Exclude full_tree: the extracted archive prunes dev-only content
        # (ESPALIER_MEMORY.md, task-packs/, .claude/workflows/), so full-dev-tree
        # invariants would fail here as a category error. The archive is
        # verified for shipped-code behavior, not dev-repo consistency. The
        # carve is orthogonal to slow by design (slow was doing export-safety
        # by accident for a handful of tests).
        #
        # `not slow` is GONE (2026-08-14, DEF-491). It was never an export
        # policy -- it was a speed carve that happened to hide the slow lane's
        # export-hostility, so a test could be export-broken for as long as it
        # was also slow and this stage stayed green. Recall is now by
        # construction: everything the archive can answer, it answers here.
        # The 29 that could not were triaged one by one and are registered in
        # tests/conftest.py::_FULL_TREE_NODEIDS.
        [str(venv_python), "-m", "pytest", "-q", "-m", "not full_tree"],
        cwd=target,
        strip_env=_RELEASE_CHECK_OPT_INS,
        # Measured on an 8-core M-series box across six runs: 468s / 472s as this
        # stage in two full matrix runs, 519s / 529s driven standalone at both
        # extraction locations, and 603s / 612s standalone again after the
        # 2026-08-15 red-team round added tests.
        #
        # Note the last pair: 612s EXCEEDS the old 600s bound. That run would
        # have TIMED OUT -- not failed on a defect, just reported nothing at all
        # about the archive, which is the useless kind of fail-closed. The spread
        # (468-612s, 31%) is the real argument here, not any single figure: it
        # moves with machine load, with concurrent runs, and with every test
        # added. A bound trimmed to the measurement is a bound that fires on a
        # slow day.
        #
        # Note this is the OUTER bound on the whole pytest subprocess. Per-test
        # hangs are already caught by pyproject.toml's 60s pytest-timeout, so
        # what this actually guards is aggregate slowness and a collection-phase
        # stall that the per-test timer cannot see. It is deliberately set well
        # clear of slower CI hardware rather than trimmed to the measurement.
        timeout=_SUITE_BOUND_S,
    )
    log_parts.append(out)
    if rc != 0:
        return fail(_failed_reason(
            rc, "pytest failed on extracted archive", "pytest on the extracted archive",
            _SUITE_BOUND_S,
        ))

    log_parts.append("=== release_check on extracted tree (in venv) ===")
    rc, out = _run(
        [str(venv_python), "scripts/release_check.py"],
        cwd=target,
        strip_env=_RELEASE_CHECK_OPT_INS,  # as in stage 01: never the nested proofs
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail(_failed_reason(
            rc, "release_check failed on extracted archive",
            "release_check on the extracted archive", 300,
        ))

    log_parts.append("=== self-host on extracted tree (in venv) ===")
    rc, out = _run(
        [str(venv_python), "-m", "espalier.cli", "self-host", str(target),
         "--mode", "source-checkout"],
        cwd=target,
        timeout=120,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("self-host source-checkout failed on extracted archive")

    return StageResult(
        name=name, status="PASS",
        duration_s=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# Stage 3 — Sdist proof
# ---------------------------------------------------------------------------


def _shipped_test_modules(tests_dir: Path) -> list[Path]:
    """Test modules pytest would collect from an extracted artifact.

    The discriminator for *"does this artifact ship tests"* must be the presence
    of collectible test MODULES, never the existence of the directory.
    ``MANIFEST.in`` does ``prune tests`` and then re-includes exactly one
    NON-test helper (``tests/_corpus_ref_resolver.py``, which the shipped
    benchmark loads by literal path at ``bench/run_benchmark.py::invoke_pytest_collection_contract``). So the
    sdist carries a ``tests/`` directory holding zero test files:
    ``tests_dir.is_dir()`` is True, pytest collects nothing and exits **5**
    (``NO_TESTS_COLLECTED``), and the stage's ``if rc != 0`` failed
    unconditionally — ``ready_to_tag`` could never be true.

    Directory-existence was a correct discriminator only while ``prune tests``
    left the directory absent entirely; the re-include made it unique by
    coincidence rather than by construction (``docs/FAILURE_MODES.md`` §13.21).
    File presence is unique by construction.

    Patterns mirror pytest's defaults (``test_*.py``, ``*_test.py``);
    ``pyproject.toml`` sets no ``python_files`` override. ``rglob`` because a
    curated artifact may nest them.
    """
    if not tests_dir.is_dir():
        return []
    found = {p for pat in ("test_*.py", "*_test.py") for p in tests_dir.rglob(pat)}
    return sorted(found)


def stage_sdist() -> StageResult:
    name = "03_sdist"
    t0 = time.monotonic()
    log_parts: list[str] = []

    def fail(reason: str) -> StageResult:
        return StageResult(
            name=name, status="FAIL",
            duration_s=time.monotonic() - t0,
            reason=reason,
            log_path=_write_log(name, "\n".join(log_parts)),
        )

    work_dir = OUTPUT_ROOT / "sdist_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    sdist_out = work_dir / "sdist_out"
    if sdist_out.exists():
        shutil.rmtree(sdist_out)
    sdist_out.mkdir()
    extract_to = work_dir / "extracted"
    if extract_to.exists():
        shutil.rmtree(extract_to)
    extract_to.mkdir()

    cleared = clear_stale_packaging_state(REPO_ROOT)
    log_parts.append("=== stale packaging state cleared before the build ===")
    log_parts.append("\n".join(str(p) for p in cleared) or "(nothing to clear)")
    log_parts.append("=== python -m build --sdist ===")
    rc, out = _run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(sdist_out)],
        cwd=REPO_ROOT,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("python -m build --sdist failed")

    tarballs = list(sdist_out.glob("*.tar.gz"))
    if not tarballs:
        return fail("no .tar.gz produced")
    sdist = tarballs[0]

    try:
        with tarfile.open(sdist) as tf:
            safe_extract_tar(tf, extract_to)
    except (tarfile.TarError, OSError) as e:
        return fail(f"sdist extract failed: {e}")
    extracted_roots = [p for p in extract_to.iterdir() if p.is_dir()]
    if not extracted_roots:
        return fail("sdist extracted no top-level directory")
    target = extracted_roots[0]

    venv_python, err = _make_venv(work_dir, log_parts)
    if venv_python is None:
        return fail(err)

    log_parts.append("=== pip install + pytest on sdist (in venv) ===")
    rc, out = _run(
        [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=target,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("pip install -e .[dev] failed on extracted sdist")

    tests_dir = target / "tests"
    shipped = _shipped_test_modules(tests_dir)
    if shipped:
        rc, out = _run(
            # Exclude full_tree (see stage 02): the extracted sdist prunes
            # the dev-only content those invariants assert on. `not slow`
            # dropped with stage 02's for the same reason -- kept identical
            # deliberately, so the two extracted-tree lanes cannot drift into
            # asking different questions. This branch is DORMANT today (the
            # sdist ships no collectible test modules, see the else below), so
            # it is unmeasured; it inherits stage 02's bound (_SUITE_BOUND_S)
            # rather than a figure of its own.
            [str(venv_python), "-m", "pytest", "-q", "-m", "not full_tree"],
            cwd=target,
            strip_env=_RELEASE_CHECK_OPT_INS,
            timeout=_SUITE_BOUND_S,
        )
        log_parts.append(out)
        if rc == 5:
            # NO_TESTS_COLLECTED with modules present means the marker selection
            # deselected every one of them. Passing here would report a green
            # stage that verified nothing -- "nothing to check" and "could not
            # check" must stay distinguishable, so this is a loud failure.
            return fail(
                f"sdist ships {len(shipped)} test module(s) but "
                "'not full_tree' selected none -- the stage would "
                "have PASSed while running nothing"
            )
        if rc != 0:
            return fail(_failed_reason(
                rc, "pytest failed on extracted sdist", "pytest on the extracted sdist",
                _SUITE_BOUND_S,
            ))
    else:
        # Count what IS there, so a skip is never mistaken for a run. An sdist
        # that ships helper files but no tests is the expected state today.
        others = len(list(tests_dir.rglob("*"))) if tests_dir.is_dir() else 0
        log_parts.append(
            f"(sdist ships no collectible test modules; skipping pytest -- "
            f"tests/ {'absent' if not tests_dir.is_dir() else f'present with {others} non-test file(s)'})"
        )

    return StageResult(
        name=name, status="PASS",
        duration_s=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# Stage 4 — Wheel install proof
# ---------------------------------------------------------------------------


def stage_wheel() -> StageResult:
    # Deliberately NOT delegated to scripts/wheel_smoke.py. This stage builds an
    # ISOLATED wheel (`python -m build --wheel`, no --no-isolation) and reports a
    # StageResult with stage-04's own fail() taxonomy plus a per-stage log file;
    # wheel_smoke builds --no-isolation and returns a deeper SmokeReport (version
    # parity + surface + audit + integrity) whose failure shape differs and whose
    # extra coverage belongs to sibling matrix stages (surface_matrix, artifact
    # cleanliness), not here. Folding it in would change the taxonomy and double
    # up coverage, so the parallel wheel-install proof is intentional.
    name = "04_wheel_install"
    t0 = time.monotonic()
    log_parts: list[str] = []

    def fail(reason: str) -> StageResult:
        return StageResult(
            name=name, status="FAIL",
            duration_s=time.monotonic() - t0,
            reason=reason,
            log_path=_write_log(name, "\n".join(log_parts)),
        )

    work_dir = OUTPUT_ROOT / "wheel_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    wheel_out = work_dir / "wheel_out"
    if wheel_out.exists():
        shutil.rmtree(wheel_out)
    wheel_out.mkdir()

    cleared = clear_stale_packaging_state(REPO_ROOT)
    log_parts.append("=== stale packaging state cleared before the build ===")
    log_parts.append("\n".join(str(p) for p in cleared) or "(nothing to clear)")
    log_parts.append("=== python -m build --wheel ===")
    rc, out = _run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheel_out)],
        cwd=REPO_ROOT,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("python -m build --wheel failed")

    wheels = list(wheel_out.glob("*.whl"))
    if not wheels:
        return fail("no .whl produced")
    wheel = wheels[0]
    log_parts.append(f"Wheel: {wheel.name} ({wheel.stat().st_size} bytes)")

    venv_python, err = _make_venv(work_dir, log_parts)
    if venv_python is None:
        return fail(err)

    log_parts.append("=== pip install <wheel> ===")
    rc, out = _run(
        [str(venv_python), "-m", "pip", "install", str(wheel)],
        cwd=work_dir,
        timeout=300,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("pip install <wheel> failed")

    log_parts.append("=== smoke ===")
    rc, out = _run(
        [str(venv_python), "-c", "import espalier; print(espalier.__name__)"],
        cwd=work_dir,
        timeout=30,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("`import espalier` failed in installed venv")

    rc, out = _run(
        [str(venv_python), "-m", "espalier.cli", "--help"],
        cwd=work_dir,
        timeout=30,
    )
    log_parts.append(out)
    if rc != 0:
        return fail("`espalier --help` failed")

    doctor_target = work_dir / "doctor_target"
    doctor_target.mkdir(exist_ok=True)
    (doctor_target / "README.md").write_text("# tmp\n", encoding="utf-8")
    rc, out = _run(
        ["git", "init", "--quiet"],
        cwd=doctor_target,
        timeout=30,
    )
    log_parts.append(out)
    rc, out = _run(
        [str(venv_python), "-m", "espalier.cli", "doctor",
         str(doctor_target), "--mode", "auto"],
        cwd=work_dir,
        timeout=60,
    )
    log_parts.append(out)
    try:
        json_start = out.find("{")
        json_end = out.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            data = json.loads(out[json_start:json_end])
            log_parts.append(f"doctor status: {data.get('status', 'unknown')}")
    except (json.JSONDecodeError, ValueError):
        log_parts.append("doctor: structured output not parsed (acceptable)")

    return StageResult(
        name=name, status="PASS",
        duration_s=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# Stage 5 — Cross-artifact cleanliness
# ---------------------------------------------------------------------------


def _flag_forbidden_members(artifact_name, members, forbidden):
    """Return [(artifact_name, member, label)] for members matching a forbidden shape.

    Strips a shared top-level dir ONLY when every member shares one: sdist / source
    archives carry a ``name-version/`` prefix that must be stripped before matching,
    but wheels have no shared top dir — stripping a wheel member's first path segment
    would drop a real package segment and defeat anchored shapes like
    ``\\.claude/scheduled_tasks\\.lock$``.
    """
    tops = {m.split("/", 1)[0] for m in members if "/" in m}
    single_top = next(iter(tops)) if len(tops) == 1 else None
    out: list[tuple[str, str, str]] = []
    for member in members:
        rel = (
            member.split("/", 1)[1]
            if single_top and member.startswith(single_top + "/")
            else member
        )
        for pattern, label in forbidden:
            if re.search(pattern, rel):
                out.append((artifact_name, member, label))
                break
    return out


def stage_artifact_cleanliness() -> StageResult:
    name = "05_artifact_cleanliness"
    t0 = time.monotonic()
    log_parts: list[str] = []

    def fail(reason: str) -> StageResult:
        return StageResult(
            name=name, status="FAIL",
            duration_s=time.monotonic() - t0,
            reason=reason,
            log_path=_write_log(name, "\n".join(log_parts)),
        )

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    try:
        from test_release_archive_filtering import FORBIDDEN_SHAPES
    except ImportError as e:
        sys.path.pop(0)
        return fail(f"could not import FORBIDDEN_SHAPES: {e}")
    sys.path.pop(0)

    forbidden = FORBIDDEN_SHAPES
    log_parts.append(f"Loaded {len(forbidden)} forbidden shapes from denylist")

    artifacts: list[Path] = []
    artifacts.extend((OUTPUT_ROOT / "source_archive_work" / "archive_out").glob("*.zip"))
    artifacts.extend((OUTPUT_ROOT / "sdist_work" / "sdist_out").glob("*.tar.gz"))
    artifacts.extend((OUTPUT_ROOT / "wheel_work" / "wheel_out").glob("*.whl"))

    if not artifacts:
        return fail("no built artifacts found to scan")

    offenders: list[tuple[str, str, str]] = []
    for artifact in artifacts:
        log_parts.append(f"--- scanning {artifact.name} ---")
        members = _list_archive_members(artifact)
        offenders.extend(_flag_forbidden_members(artifact.name, members, forbidden))
        log_parts.append(f"  {len(members)} members; {len([o for o in offenders if o[0] == artifact.name])} offences")

    if offenders:
        log_parts.append("--- offenders ---")
        for artifact, member, label in offenders[:20]:
            log_parts.append(f"  {artifact}: {member} ({label})")
        return fail(f"{len(offenders)} forbidden shape(s) in built artifacts")

    return StageResult(
        name=name, status="PASS",
        duration_s=time.monotonic() - t0,
    )


def _list_archive_members(archive: Path) -> list[str]:
    """Return the member list for a zip, tar.gz, or whl."""
    name = archive.name.lower()
    if name.endswith(".zip") or name.endswith(".whl"):
        with zipfile.ZipFile(archive) as zf:
            return zf.namelist()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive) as tf:
            return tf.getnames()
    raise ValueError(f"Unsupported archive: {archive}")


def stage_surface_matrix() -> StageResult:
    """Validate the surface support matrix and pin its tests.

    ``docs/SURFACE_SUPPORT_MATRIX.md`` is the normative declaration of
    which Claude Code surfaces espalier governs. The final release
    matrix records that the matrix file exists and its validator tests
    pass — so a tag can't ship if the matrix has drifted from the
    public-docs claims it gates.
    """
    name = "06_surface_matrix"
    t0 = time.monotonic()
    log_parts: list[str] = []

    def fail(reason: str) -> StageResult:
        return StageResult(
            name=name, status="FAIL",
            duration_s=time.monotonic() - t0,
            reason=reason,
            log_path=_write_log(name, "\n".join(log_parts)),
        )

    matrix_path = REPO_ROOT / "docs" / "SURFACE_SUPPORT_MATRIX.md"
    if not matrix_path.exists():
        return fail(f"{matrix_path.relative_to(REPO_ROOT)} not found")
    log_parts.append(f"Found {matrix_path.relative_to(REPO_ROOT)}")

    rc, out = _run(
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/test_surface_support_matrix.py",
            "tests/test_agent_frontmatter_contract.py",
        ],
        cwd=REPO_ROOT,
        timeout=120,
    )
    log_parts.append(out)
    if rc != 0:
        tail = out.strip().splitlines()[-3:]
        return fail(f"matrix tests rc={rc}; {' / '.join(tail)}"[:200])
    summary = next(
        (ln for ln in reversed(out.splitlines()) if "passed" in ln),
        "matrix tests pass",
    )
    return StageResult(
        name=name, status="PASS",
        duration_s=time.monotonic() - t0,
        details=summary.strip(),
        log_path=_write_log(name, "\n".join(log_parts)),
    )


def _capture_archive_members() -> Path | None:
    """Write the sorted member list of the built release archive
    to ``reports/final_release_candidate_archive_members.txt``.

    The file is the audit trail for what shipped. Returns the report
    path on success, or ``None`` if no archive was built (the stage
    that produces it failed earlier in the matrix).
    """
    candidates = list((OUTPUT_ROOT / "source_archive_work" / "archive_out").glob("*.zip"))
    if not candidates:
        return None
    archive = candidates[0]
    members = sorted(_list_archive_members(archive))
    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    out = reports_dir / "final_release_candidate_archive_members.txt"
    out.write_text("\n".join(members) + "\n", encoding="utf-8")
    return out


def _write_final_report(
    version: str,
    results: list[StageResult],
    archive_members_path: Path | None,
    skipped: list[str] | None = None,
) -> Path:
    """Persist the publish-gate proof shape to
    ``reports/final_release_candidate_report.json``.

    ``ready_to_tag`` is true iff every stage ran and none failed. A stage
    dropped by ``--skip`` is neither PASS nor FAIL: it is listed under
    ``skipped`` and withholds readiness on its own, because ``fails == 0``
    over the stages that ran says nothing about the ones that did not -- a
    ``--skip 02`` run used to report ready over the one stage that installs
    and tests the archive (DEF-461). Operators consult this file before
    running ``git tag``.
    """
    import datetime as _dt
    captured = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    skipped = list(skipped or [])
    passes = sum(1 for r in results if r.status == "PASS")
    fails = sum(1 for r in results if r.status == "FAIL")
    total = sum(r.duration_s for r in results)
    blockers = [
        {"stage": r.name, "reason": r.reason}
        for r in results if r.status == "FAIL"
    ]
    matrix_rel = "docs/SURFACE_SUPPORT_MATRIX.md"
    report = {
        "version": version,
        "captured_at_utc": captured,
        "stages": [
            {
                "name": r.name,
                "status": r.status,
                "duration_s": round(r.duration_s, 2),
                "details": r.details or r.reason or "",
            }
            for r in results
        ],
        "summary": {
            "pass": passes,
            "fail": fails,
            "total_duration_s": round(total, 2),
        },
        "blockers": blockers,
        "skipped": skipped,
        "matrix_path": matrix_rel,
        "archive_members_path": (
            str(archive_members_path.relative_to(REPO_ROOT))
            if archive_members_path else None
        ),
        "ready_to_tag": fails == 0 and not skipped,
    }
    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    out = reports_dir / "final_release_candidate_report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip", action="append", default=[],
        choices=["01", "02", "03", "04", "05", "06"],
        help="skip a stage (repeat to skip multiple)",
    )
    args = parser.parse_args()

    print("Espalier-Harness final release proof matrix")
    print("=" * 60)
    version = _load_version()
    print(f"Version: {version}")
    print()

    _setup_output_dir()
    # The previous run's proof must not outlive this one: `_write_final_report`
    # is the last statement of the try below, so a Ctrl-C during pip install,
    # a BadZipFile out of the member capture, or a `--skip` run that dies
    # early would otherwise leave a `ready_to_tag: true` from an earlier full
    # run on disk for the checklist to read before `git tag` (DEF-461).
    for stale in (
        "final_release_candidate_report.json",
        "final_release_candidate_archive_members.txt",
    ):
        (REPO_ROOT / "reports" / stale).unlink(missing_ok=True)

    stages: list[tuple[str, Callable[[], StageResult]]] = [
        ("01", stage_source_checkout),
        ("02", stage_source_archive),
        ("03", stage_sdist),
        ("04", stage_wheel),
        ("05", stage_artifact_cleanliness),
        ("06", stage_surface_matrix),
    ]

    results: list[StageResult] = []
    # Recorded by id, in stage order, so the report can say which stages the
    # verdict below does NOT cover (DEF-461).
    skipped = [stage_id for stage_id, _ in stages if stage_id in args.skip]
    # try/finally, not a call before the pass/fail branch: `except Exception`
    # below does NOT catch KeyboardInterrupt, and Ctrl-C during a multi-minute
    # pip install is the single most likely way this run ends early -- which is
    # exactly when the workspace is most likely to sit untouched for days.
    # _capture_archive_members / _write_final_report are also outside any
    # handler and can raise (a corrupt archive throws BadZipFile straight out).
    # The finally covers every exit: pass, fail, raise, and interrupt.
    try:
        for stage_id, runner in stages:
            if stage_id in args.skip:
                print(f"  (skipping {stage_id})")
                continue
            try:
                result = runner()
            except Exception as e:  # noqa: BLE001
                result = StageResult(
                    name=f"{stage_id}_unknown", status="FAIL",
                    duration_s=0.0,
                    reason=f"unhandled exception: {e}",
                )
            results.append(result)
            print(result.render())
            if result.log_path:
                print(f"    log: {result.log_path}")

        # Capture archive member list + write structured final report
        # so operators have an audit trail and a single proof file before tagging.
        archive_members_path = _capture_archive_members()
        report_path = _write_final_report(
            version, results, archive_members_path, skipped,
        )
    finally:
        _prune_work_venvs()

    print()
    print("=" * 60)
    failures = [r for r in results if r.status == "FAIL"]
    if failures:
        print(f"FINAL: FAIL ({len(failures)} stage(s) failed)")
        for f in failures:
            print(f"  - {f.name}: {f.reason}")
        print(f"  report: {report_path.relative_to(REPO_ROOT)}")
        return 1

    if skipped:
        # The stages that ran passed; the verdict covers only those. Exit 0
        # reports the run, the report withholds readiness, and the line says
        # which stages a `git tag` would rest on nothing.
        print(
            f"FINAL: PASS ({len(results)} of {len(stages)} stages ran; "
            f"skipped {', '.join(skipped)}) -- NOT ready to tag"
        )
        print(f"  report:  {report_path.relative_to(REPO_ROOT)}")
        return 0

    print(f"FINAL: PASS (all {len(results)} stages)")
    print(f"Version {version} is provably clean across every install path.")
    print(f"  report:  {report_path.relative_to(REPO_ROOT)}")
    if archive_members_path:
        print(f"  members: {archive_members_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
