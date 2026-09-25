#!/usr/bin/env python3
"""The archive drive as a script: pytest inside the extracted release archive.

Builds the release archive from this checkout into a work directory, extracts
it, gives the extracted tree the git a clone would have (the matrix's DEF-670
seed: ``init``, ``add -A``, every ``--exclude-standard``-withheld path
force-added, one commit, tracked count == on-disk count), asserts the tree IS
a release export, builds a venv there, installs the tree's ``dev`` extra into
it, then runs pytest inside it with the caller's arguments, streamed.
``--audit`` sets ``ESPALIER_FULL_TREE_AUDIT=1`` in the child so every
``full_tree`` registration RUNS instead of skipping -- the self-expiry oracle
for ``tests/conftest.py::_FULL_TREE_NODEIDS`` (``docs/ENV_CATALOG.md``): a
registered test that PASSES there over a real population is a stale entry,
and failures are the healthy result.

This is stage 02 of ``scripts/final_release_matrix.py`` with the suite cut
down to what the caller names: the same builder, the same seed, the same venv
factory and the same runner, bound by import from the matrix module and never
copied -- ``tests/test_archive_probe.py`` pins the composition. The five
modules the matrix red on 2026-09-23 answer in under four minutes here against
the stage's forty-five, so a dev-tree row is measured at authoring time,
before the matrix and not by it.

Usage::

    python3 scripts/archive_probe.py -- tests/test_recall.py -q -p no:cacheprovider -rfEs
    python3 scripts/archive_probe.py --audit -- -q -rA -m full_tree -n 4
    python3 scripts/archive_probe.py --work-dir /path/to/fresh/dir --clean -- tests/test_export_guard.py -q

Everything after the first ``--`` goes to pytest verbatim, and every test path
in it is relative to the archive root (an absolute path would run the dev
tree's file and conftest inside the export's venv, and the audit would read
every registration as stale, so one is refused). The builder enumerates the
INDEX for names and reads the WORKING TREE for content: ``git add -N`` a new
file before driving, or the archive omits it and the probe measures a tree
without your fix; and what it measures is your dirty tree, never HEAD
(``scripts/fresh_clone_gate.py`` proves HEAD). ``--root`` measures that
tree's content under THIS checkout's builder, seed and matrix helpers.

The work directory is printed first and kept; the default is a fresh temp
directory under the system temp root. A ``--work-dir`` that exists and is not
empty is refused, so the probe only ever writes into a directory that holds
nothing of yours. ``--clean`` removes what the probe wrote (``archive_out/``,
``extracted/``, ``venv/``, ``probe.log``) on exit 0, and the directory itself
only when the probe made it -- the shape of ``fresh_clone_gate.py``'s
``_remove_own``. Read-only on the checkout it builds from.

The pytest child runs in its own session on POSIX and a bound kill takes the
whole process group, so ``-n N`` workers die with it instead of reparenting to
PID 1 and spinning; Ctrl-C or SIGTERM at the probe is forwarded to that group
for the same reason.

Exit codes::

    0..5  pytest's own exit inside the archive
    124   the child ran past the matrix's suite bound and was killed
    70    the probe refused: no pytest arguments after ``--``; a pytest
          argument that is an absolute or parent-relative path; a
          ``--work-dir`` that exists and is not empty; a build, extract, seed,
          venv or install step that failed (the reason is printed and written
          to the work dir's ``probe.log``); or an extracted tree that is NOT a
          release export by ``surface_contract.is_release_export`` -- an audit
          on such a tree would read every registration as stale while nothing
          was tested on an export, so the probe never runs pytest there
    2     a usage error in the probe's own options (argparse)
    1     an unexpected exception; the traceback is the report

Maintainer-only, like ``scripts/fresh_clone_gate.py``: not fused into an
adopter tree.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from espalier import surface_contract  # noqa: E402
from espalier._archive_safety import safe_extract_zip  # noqa: E402

MATRIX_PATH = REPO_ROOT / "scripts" / "final_release_matrix.py"
#: The switch ``tests/conftest.py`` and ``tests/_export_guard.py`` read.
AUDIT_ENV = "ESPALIER_FULL_TREE_AUDIT"
#: Outside pytest's 0..5 on purpose, the same code as ``fresh_clone_gate.py``.
EXIT_REFUSED = 70
#: GNU timeout's code, the same the matrix's ``_run`` returns on a bound.
EXIT_TIMEOUT = 124
WORK_PREFIX = "espalier-archive-probe-"
#: What the probe writes under the work dir, and all ``--clean`` removes.
WORK_ENTRIES = ("archive_out", "extracted", "venv", "probe.log")


class ProbeRefusal(Exception):
    """The probe could not measure; the message says why."""


def _load_matrix():
    """The matrix module by path. Its seed, venv factory, runner and bounds are
    the oracle's own; the probe composes them and defines none of them.
    Registered in ``sys.modules`` so the module's ``@dataclass`` resolves its
    ``__module__`` (required on Python 3.14; ``tests/test_final_release_matrix.py``
    loads it the same way)."""
    spec = importlib.util.spec_from_file_location("final_release_matrix", MATRIX_PATH)
    if spec is None or spec.loader is None:
        raise ProbeRefusal(f"cannot load {MATRIX_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_matrix = _load_matrix()
_seed_git = _matrix._seed_git
_make_venv = _matrix._make_venv
_run = _matrix._run
_SUITE_BOUND_S: int = _matrix._SUITE_BOUND_S
_RELEASE_CHECK_OPT_INS: tuple[str, ...] = tuple(_matrix._RELEASE_CHECK_OPT_INS)
#: The six repo-redirecting git keys the seed strips on every call; the pytest
#: child must not inherit them either, or its git arms answer about the dev
#: repo while the probe reports on the export.
_GIT_REDIRECT_ENV: tuple[str, ...] = tuple(_matrix._GIT_REDIRECT_ENV)


def say(line: str) -> None:
    print(line, flush=True)


# ── the pure pieces (pinned in tests/test_archive_probe.py) ─────────────────


def split_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(the probe's own options, the pytest arguments)``: split at the FIRST
    ``--``; a later ``--`` belongs to pytest. No ``--`` means no pytest
    arguments, which the probe refuses rather than running a default suite."""
    argv = list(argv)
    if "--" not in argv:
        return argv, []
    cut = argv.index("--")
    return argv[:cut], argv[cut + 1:]


def parse_args(opts: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        usage="%(prog)s [--root PATH] [--work-dir DIR] [--clean] [--audit] -- <pytest args>",
    )
    ap.add_argument("--root", default=str(REPO_ROOT),
                    help="the checkout to build the archive from (default: this one)")
    ap.add_argument("--work-dir", metavar="DIR",
                    help="where the archive, the extracted tree, the venv and probe.log go "
                         "(default: a fresh temp dir; printed first, kept; an existing "
                         "non-empty dir is refused)")
    ap.add_argument("--clean", action="store_true",
                    help="on exit 0 remove what the probe wrote, and the dir itself only "
                         "when the probe made it")
    ap.add_argument("--audit", action="store_true",
                    help=f"set {AUDIT_ENV}=1 in the child: registered full_tree tests RUN "
                         "instead of skipping; every PASS over a real population is a stale "
                         "registration")
    return ap.parse_args(list(opts))


def probe_child_env(audit: bool, parent: Mapping[str, str] | None = None) -> dict[str, str]:
    """The pytest child's environment: the parent's, minus release_check's
    opt-ins (inherited, they re-spawn a nested suite or a wheel build mid-run;
    the matrix strips the same set) and minus the six repo-redirecting git keys
    (the seed strips them too; inherited, a git arm inside the export would
    answer about the dev repo), with the audit switch set by ``--audit`` and
    ONLY by ``--audit`` -- an inherited switch is dropped, so the probe's mode
    is its flag's, never the shell's."""
    env = dict(os.environ if parent is None else parent)
    for key in (*_RELEASE_CHECK_OPT_INS, *_GIT_REDIRECT_ENV):
        env.pop(key, None)
    env.pop(AUDIT_ENV, None)
    if audit:
        env[AUDIT_ENV] = "1"
    return env


def build_pytest_command(venv_python: Path, pytest_args: Sequence[str]) -> list[str]:
    """``<venv python> -m pytest <the caller's arguments, verbatim>``. The
    runner below spells the same three-token prefix as a literal so the
    subprocess-contract scanner resolves the call site; the two are pinned
    equal by the test module."""
    return [str(venv_python), "-m", "pytest"] + list(pytest_args)


def refuse_unless_relative(pytest_args: Sequence[str]) -> None:
    """A bare pytest argument that is an absolute path, or climbs out with
    ``..``, names a file OUTSIDE the extracted tree: pytest would run the dev
    tree's module and conftest inside the export's venv, and under ``--audit``
    every registration would read as stale. Options are left alone."""
    for arg in pytest_args:
        if arg.startswith("-"):
            continue
        if Path(arg).is_absolute() or arg.startswith(".."):
            raise ProbeRefusal(
                f"pytest argument {arg!r} reaches outside the extracted tree; name tests "
                "relative to the archive root (tests/test_x.py), never by an absolute path"
            )


# ── the steps ───────────────────────────────────────────────────────────────


def build_archive(root: Path, output_dir: Path) -> Path:
    """This checkout's ``scripts/build_release_archive.py`` on ``root``, the way
    ``scripts/release_check.py`` imports it (a ``sys.path`` insert of
    ``scripts/``, removed by value afterwards). The builder enumerates the git
    index of ``root`` for names and reads its working tree for content."""
    scripts_dir = str(REPO_ROOT / "scripts")
    sys.path.insert(0, scripts_dir)
    try:
        from build_release_archive import build_release_archive  # type: ignore[import-not-found]
    finally:
        if scripts_dir in sys.path:
            sys.path.remove(scripts_dir)
    try:
        return build_release_archive(root, output_dir=output_dir)
    except SystemExit as exc:  # the builder refuses with a message
        raise ProbeRefusal(f"build_release_archive refused: {exc.code}") from exc


def extract(archive: Path, extract_to: Path) -> Path:
    """Extract into an empty ``extract_to``; exactly one top-level directory,
    and it carries no ``.git/`` (the seed gives it one)."""
    if extract_to.exists():
        shutil.rmtree(extract_to)
    extract_to.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            safe_extract_zip(zf, extract_to)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProbeRefusal(f"archive extract failed: {exc}") from exc
    roots = [p for p in extract_to.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise ProbeRefusal(
            f"the archive extracted {len(roots)} top-level directories under "
            f"{extract_to}; expected exactly one"
        )
    target = roots[0]
    if (target / ".git").exists():
        raise ProbeRefusal(f"the extracted archive carries .git/: {target}")
    return target


def refuse_unless_export(target: Path) -> None:
    """The audit's own precondition, asserted before pytest ever runs: the
    switch reaches the auto-skip only where ``is_release_export`` is True, and a
    work dir the predicate does not call an export makes every registration
    read as stale while nothing was tested on an export."""
    if not surface_contract.is_release_export(target):
        raise ProbeRefusal(
            f"{target} is not a release export by surface_contract.is_release_export; "
            "the probe measures nothing on a tree the auto-skip would not fire on"
        )


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group on POSIX -- the child was started
    in its own session, so ``-n N`` workers die with it instead of reparenting
    to PID 1 and spinning (one such orphan spun 45 hours on one core,
    2026-09-10); a plain kill on Windows."""
    if sys.platform != "win32":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    proc.kill()


def run_pytest(
    venv_python: Path,
    target: Path,
    pytest_args: Sequence[str],
    env: Mapping[str, str],
    *,
    timeout_s: float = _SUITE_BOUND_S,
    echo: Callable[[str], None] = say,
) -> int:
    """Run pytest inside ``target`` with the caller's arguments verbatim, every
    line streamed to ``echo`` as it arrives (a fifteen-minute audit is read as
    it runs, never captured). Bounded by the matrix's suite bound: a child past
    it is killed with its process group and the probe exits ``EXIT_TIMEOUT``.
    Ctrl-C or SIGTERM at the probe kills that group too before propagating."""
    cmd = [str(venv_python), "-m", "pytest"] + list(pytest_args)
    timed_out = threading.Event()
    proc = subprocess.Popen(
        cmd, cwd=str(target), env=dict(env), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        start_new_session=(sys.platform != "win32"),
    )

    def _kill() -> None:
        timed_out.set()
        _kill_process_tree(proc)

    watchdog = threading.Timer(timeout_s, _kill)
    watchdog.daemon = True
    watchdog.start()

    def _forward(signum, frame):  # noqa: ARG001 -- the handler signature
        _kill_process_tree(proc)
        watchdog.cancel()
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    previous: dict[int, object] = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _forward)
        except (ValueError, OSError):  # not the main thread, or unsupported here
            pass
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            echo(line.rstrip("\n"))
        rc = proc.wait()
    finally:
        watchdog.cancel()
        for sig, handler in previous.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]
    if timed_out.is_set():
        echo(f"probe: pytest ran past the matrix's suite bound ({timeout_s:.0f}s) and was killed")
        return EXIT_TIMEOUT
    return rc


def _seed_line(log_parts: Sequence[str]) -> str:
    return next((p for p in log_parts if p.startswith("git seed: ")), "git seed: (no count line)")


def _clean_work(work: Path, made_work: bool) -> None:
    """Remove what the probe wrote, and the directory itself only when the
    probe made it (``fresh_clone_gate.py::_remove_own``'s rule)."""
    for name in WORK_ENTRIES:
        entry = work / name
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        elif entry.exists():
            entry.unlink(missing_ok=True)
    if made_work:
        shutil.rmtree(work, ignore_errors=True)


def _main(ns: argparse.Namespace, pytest_args: list[str]) -> int:
    if not pytest_args:
        raise ProbeRefusal(
            "no pytest arguments after `--`; the probe runs what you name, never a default suite"
        )
    refuse_unless_relative(pytest_args)
    root = Path(ns.root).resolve()
    made_work = ns.work_dir is None
    if made_work:
        work = Path(tempfile.mkdtemp(prefix=WORK_PREFIX))
    else:
        work = Path(ns.work_dir).resolve()
        if work.exists() and any(work.iterdir()):
            raise ProbeRefusal(
                f"--work-dir {work} exists and is not empty; the probe builds into a "
                "fresh directory only (--clean removes what it wrote there and the "
                "extract step clears its `extracted/`), so pick a path that holds "
                "nothing of yours"
            )
        work.mkdir(parents=True, exist_ok=True)
    say(f"probe: work dir {work}  (kept; --clean removes what the probe wrote on exit 0)")
    say(
        "probe: the builder enumerates the INDEX for names and reads the WORKING TREE "
        "for content -- `git add -N` a new file before driving, or the archive omits "
        "it; this proves your dirty tree, not HEAD"
    )
    log_parts: list[str] = []
    log_path = work / "probe.log"
    try:
        log_parts.append(f"=== build_release_archive from {root} ===")
        archive = build_archive(root, work / "archive_out")
        say(f"probe: archive {archive.name} ({archive.stat().st_size} bytes)")
        target = extract(archive, work / "extracted")
        say(f"probe: extracted {target}")

        seed_error = _seed_git(target, log_parts)
        if seed_error:
            raise ProbeRefusal(seed_error)
        say(f"probe: {_seed_line(log_parts)}")

        # The precondition needs only the layout and .gitattributes, so it is
        # asked before the venv and the install: a refusal costs seconds, not
        # minutes.
        refuse_unless_export(target)
        say(f"probe: {target} is a release export (surface_contract.is_release_export True)")

        venv_python, err = _make_venv(work, log_parts)
        if venv_python is None:
            raise ProbeRefusal(err)
        log_parts.append("=== pip install -e .[dev] (in venv) ===")
        rc, out = _run(
            [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"],
            cwd=target, timeout=300, strip_env=_RELEASE_CHECK_OPT_INS,
        )
        log_parts.append(out)
        if rc != 0:
            raise ProbeRefusal("pip install -e .[dev] failed in the extracted tree; see probe.log")
        say(f"probe: venv {venv_python}")

        env = probe_child_env(ns.audit)
        say(
            f"probe: pytest ({'audit ON: ' + AUDIT_ENV + '=1' if ns.audit else 'audit off'}) "
            f"in {target}: {' '.join(build_pytest_command(venv_python, pytest_args))}"
        )
        rc = run_pytest(venv_python, target, pytest_args, env)
        log_parts.append(f"=== pytest exit {rc} (output streamed, not captured) ===")
        say(f"probe: pytest exit {rc}")
    except ProbeRefusal as exc:
        log_parts.append(f"=== REFUSED: {exc} ===")
        raise
    finally:
        log_path.write_text("\n".join(log_parts) + "\n", encoding="utf-8")
    if rc == 0 and ns.clean:
        _clean_work(work, made_work)
        say(f"probe: --clean removed what the probe wrote under {work}"
            + ("" if made_work else " (the directory was yours and stays)"))
    return rc


def main(argv: Sequence[str] | None = None) -> int:
    opts, pytest_args = split_argv(sys.argv[1:] if argv is None else argv)
    ns = parse_args(opts)
    try:
        return _main(ns, pytest_args)
    except ProbeRefusal as exc:
        say(f"probe: REFUSED -- {exc}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
