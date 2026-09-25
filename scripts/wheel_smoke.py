#!/usr/bin/env python3
"""Canonical wheel smoke + release gate.

Proves wheel-installed Espalier-Harness deploys the same harness surface
as a source checkout into a fresh user repo. Sequence::

    built wheel → fresh venv → fresh target repo → init → install-ci
                → doctor → audit → integrity verify
                → assert deployed surface (counts + canonical files)

Stdlib-only on purpose: this script must run from a checkout *or* from a
release-archive copy, with nothing installed beyond the wheel under test.
The helper functions are unit-tested in ``tests/test_wheel_smoke.py``.

CLI::

    --wheel PATH    Use an existing wheel; otherwise build one.
    --skip-build    With --wheel, skip the build entirely (for CI artifact reuse).
    --keep-temp     Leave the scratch directory in place for inspection.
    --json          Emit a machine-readable summary at the end.

Exit codes::

    0   PASS — every assertion held.
    1   FAIL — first failure terminates the run; failure reason printed.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Expected deployed surface — single source of truth for the assertions ────
#
# EXPECTED_COMMAND_COUNT is derived from the package's bundled assets so a new
# command landing in espalier/assets/ keeps wheel_smoke honest without a manual
# bump. The literal constants below are stable enough that the
# canary tests in tests/test_wheel_smoke.py::TestExpectedCountsMatchPackagedAssets
# are sufficient — those tests independently assert each constant matches disk.


def _count_packaged_assets(kind: str) -> int:
    """Count `.claude/{kind}/*.md` files in the package asset tree.

    Walks the filesystem rather than importlib.resources because this
    script is stdlib-only and must run from a source checkout. The asset
    tree at `espalier/assets/claude/{kind}/` is the SoT that
    `espalier init` deploys from.
    """
    asset_dir = REPO_ROOT / "espalier" / "assets" / "claude" / kind
    if not asset_dir.is_dir():
        return 0
    if kind == "skills":
        return sum(
            1 for p in asset_dir.iterdir()
            if p.is_dir() and (p / "SKILL.md").is_file()
        )
    return sum(1 for p in asset_dir.glob("*.md"))


EXPECTED_COMMAND_COUNT = _count_packaged_assets("commands")
EXPECTED_SKILL_COUNT = _count_packaged_assets("skills")
EXPECTED_AGENT_COUNT_MIN = _count_packaged_assets("agents")
EXPECTED_HOOK_ENTRY_COUNT = 12
EXPECTED_HOOK_HELPER_COUNT = 13
EXPECTED_WIRED_HOOK_COUNT = 12

CANONICAL_RICH_AGENTS: tuple[str, ...] = (
    "architecture-analyst",
    "code-reviewer",
    "docs-maintainer",
    "failure-mode-reviewer",
    "harness-config-advisor",
    "repo-analyst",
    "test-writer",
)

EXPECTED_HOOK_HELPERS: tuple[str, ...] = (
    "_bash_patterns.py",
    "_born_weak.py",
    "_denial_reasons.py",
    "_explain_path.py",
    "_hook_contract.py",
    "_hook_utils.py",
    "_integrity.py",
    "_maintenance_mode.py",
    "_protected_zones.py",
    "_recall.py",
    "_reinject.py",
    "_self_host_fingerprint.py",
    "_speedbump.py",
)

# Stub agents are <500 bytes; rich agents are 7KB+. 2KB is comfortably
# above the largest plausible stub and below the smallest rich agent.
RICH_AGENT_MIN_BYTES = 2048


# ── Failure model ──────────────────────────────────────────────────────────


class SmokeFailure(Exception):
    """A surface assertion failed; the message is operator-actionable."""


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    status: str  # "PASS" | "FAIL"
    detail: str = ""


@dataclass
class SmokeReport:
    wheel_path: str = ""
    target: str = ""
    steps: list[StepResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "FAIL" if any(s.status == "FAIL" for s in self.steps) else "PASS"

    def add(self, step: StepResult) -> None:
        self.steps.append(step)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "wheel_path": self.wheel_path,
            "target": self.target,
            "steps": [
                {"name": s.name, "status": s.status, "detail": s.detail}
                for s in self.steps
            ],
        }


def format_failure(msg: str, hint: str) -> str:
    """Format a failure with the actionable hint operators need.

    The hint should name the *class* of bug (missing package data, broken
    CLI entry, etc.) so a maintainer reading red CI knows which file to
    open first.
    """
    return f"{msg}\n  hint: {hint}"


# ── Wheel discovery + build ────────────────────────────────────────────────


def locate_wheel(dist_dir: Path) -> Path:
    """Return the newest ``espalier_harness-*.whl`` in ``dist_dir``.

    Raises :class:`SmokeFailure` if no wheel is present, naming the
    likely cause (forgot to build).
    """
    if not dist_dir.is_dir():
        raise SmokeFailure(format_failure(
            f"wheel directory not found: {dist_dir}",
            "run `python -m build --wheel --no-isolation` "
            f"--outdir {dist_dir} first, or pass --wheel PATH",
        ))
    wheels = sorted(dist_dir.glob("espalier_harness-*.whl"))
    if not wheels:
        raise SmokeFailure(format_failure(
            f"no espalier_harness-*.whl in {dist_dir}",
            "the build step did not produce a wheel; check `python -m build` output",
        ))
    return wheels[-1]


def _remove_tree_clearing_bits(path: Path) -> None:
    """``shutil.rmtree`` that answers a permission refusal by adding the owner
    write bit to the entry and to its parent inside the tree, then retrying
    once -- the discipline of ``espalier._rmtree.remove_tree``, stdlib only
    (a read-only entry, or a locked directory inside the tree, refuses a bare
    rmtree; a second refusal raises).
    """
    root = str(path)

    def _on_failure(func, failed: str, exc: BaseException) -> None:
        if not (isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM)):
            raise exc
        for target in (failed, os.path.dirname(failed)):
            if target == root or target.startswith(root + os.sep):
                try:
                    os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR)
                except OSError:
                    pass
        func(failed)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_on_failure)
        return
    shutil.rmtree(path, onerror=lambda func, p, exc_info: _on_failure(func, p, exc_info[1]))


def _clear_stale_packaging_state(repo_root: Path) -> list[Path]:
    """Stdlib twin of ``espalier.artifact_parity.clear_stale_packaging_state``
    (this script imports nothing from the package by design: it runs from a
    release-archive copy with only the wheel under test installed). Removes
    ``repo_root/build`` and every top-level ``*.egg-info`` -- the two cached
    channels that re-ship what the current config dropped -- and returns
    what it removed; a nested egg-info and a plain file of either name are
    left alone, a symlinked ``build`` is unlinked, never followed (a directory
    symlink on Windows through ``rmdir``), and a locked directory inside the tree is
    unlocked and retried, as the engine helper does. Parity with the engine
    helper is DRIVEN, not compared textually: ``tests/test_wheel_smoke.py::
    test_clear_stale_packaging_state_parity_with_artifact_parity`` runs both
    on one tree that carries every one of those shapes.
    """
    removed: list[Path] = []
    for path in [repo_root / "build", *sorted(repo_root.glob("*.egg-info"))]:
        if path.is_symlink():
            if sys.platform == "win32" and path.is_dir():
                path.rmdir()  # a directory symlink: rmdir drops the link, not the target
            else:
                path.unlink()
        elif path.is_dir():
            _remove_tree_clearing_bits(path)
        else:
            continue
        removed.append(path)
    return removed


def build_wheel(repo_root: Path, dest_dir: Path) -> Path:
    """Build a wheel from ``repo_root`` into ``dest_dir`` and return its path.

    Clears the stale packaging state first, so the wheel is built from the
    committed tree (the order is pinned in ``tests/test_wheel_smoke.py``).
    """
    _clear_stale_packaging_state(repo_root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(dest_dir)],
        cwd=str(repo_root),
    )
    return locate_wheel(dest_dir)


# ── Venv handling ──────────────────────────────────────────────────────────


def _venv_python(venv_dir: Path) -> Path:
    """Path to the venv's python interpreter (Windows vs POSIX).

    Parallels scripts/final_release_matrix.py::_venv_python (both run standalone
    in fresh venvs; a shared import is deliberately avoided). Behavioral parity
    is pinned by tests/test_final_release_matrix.py::
    test_venv_python_parity_with_wheel_smoke.
    """
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_executable(venv_dir: Path, name: str) -> Path:
    """Path to a console script inside the venv (e.g. ``espalier``)."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / f"{name}.exe"
    return venv_dir / "bin" / name


def install_wheel(wheel: Path, venv_dir: Path) -> None:
    """Create a fresh venv and install ``wheel`` into it."""
    subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    vpython = _venv_python(venv_dir)
    subprocess.check_call(
        [str(vpython), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
    )
    subprocess.check_call(
        [str(vpython), "-m", "pip", "install", "--quiet", str(wheel)],
    )


def run_cli(venv_dir: Path, *args: str, cwd: Path | None = None) -> str:
    """Run the venv-installed ``espalier`` CLI; return stdout. Raises on non-zero."""
    espalier = _venv_executable(venv_dir, "espalier")
    if not espalier.exists():
        raise SmokeFailure(format_failure(
            f"espalier CLI missing from venv: {espalier}",
            "the wheel installed but did not register its console script - "
            "check pyproject.toml [project.scripts] is included in the build",
        ))
    # subprocess-contract: ok wheel-smoke-invokes-installed-CLI-per-test-callers-pin-args
    result = subprocess.run(
        [str(espalier), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise SmokeFailure(format_failure(
            f"espalier {' '.join(args)} returned {result.returncode}",
            f"stderr: {result.stderr.strip()[:300]}",
        ))
    return result.stdout


# ── Version-parity assertions ──────────────────────────────────────────────


def _read_pyproject_version(pyproject: Path) -> str:
    """Extract ``project.version`` from a ``pyproject.toml`` using only the stdlib.

    The wheel_smoke script is stdlib-only on purpose (it must run from a bare
    checkout or a fresh wheel-install venv with no third-party deps). ``tomllib``
    is stdlib only on Python 3.11+, but the project supports 3.10, and ``tomli``
    would be a third-party dep — both are off the table here. So scan the single
    ``version`` key out of the top-level ``[project]`` table by hand rather than
    parse the whole document.
    """
    in_project = False
    for raw in pyproject.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        header = re.match(r"\[([^\]]+)\]", line)
        if header:
            in_project = header.group(1).strip() == "project"
            continue
        if in_project:
            # Standalone stdlib-only version parse — intentionally NOT derived from
            # espalier.version_surfaces. This smoke test validates the BUILT wheel; deriving
            # "expected" from the wheel-under-test's own code would defeat the parity check.
            m = re.match(r"""version\s*=\s*["']([^"']*)["']""", line)
            if m and m.group(1):
                return m.group(1)
    raise SmokeFailure(format_failure(
        f"pyproject.toml at {pyproject} has no [project].version",
        "the wheel cannot be version-checked without a canonical source - "
        "check that pyproject.toml has a project.version key",
    ))


def assert_version_parity(venv_dir: Path, pyproject: Path) -> str:
    """Assert ``espalier --version`` and ``espalier.__version__`` both match
    ``pyproject.toml::project.version`` inside the fresh venv.

    Catches the failure mode where the three version surfaces (pyproject,
    package ``__init__.__version__``, and CLI entry-point output) drift apart
    silently — every surface has its own test, but no test cross-checks them
    against each other from inside a fresh install. Returns the expected
    version string for downstream use.
    """
    expected = _read_pyproject_version(pyproject)

    cli_out = run_cli(venv_dir, "--version").strip()
    if expected not in cli_out:
        raise SmokeFailure(format_failure(
            f"espalier --version mismatch: pyproject says {expected!r}, "
            f"CLI says {cli_out!r}",
            "the CLI entry-point in pyproject.toml is wired to a stale version "
            "string - verify espalier/cli.py reads __version__ from espalier/__init__.py",
        ))

    vpython = _venv_python(venv_dir)
    try:
        pkg_out = subprocess.check_output(
            [str(vpython), "-c", "import espalier; print(espalier.__version__)"],
            text=True, encoding="utf-8",
        ).strip()
    except ValueError as exc:  # strict decode: a structured answer (DEF-821)
        raise SmokeFailure(format_failure(
            f"espalier.__version__ output was not UTF-8: {exc}",
            "a version string is ASCII -- the installed package printed bytes that are not; "
            "re-check the wheel's espalier/__init__.py",
        )) from exc
    if pkg_out != expected:
        raise SmokeFailure(format_failure(
            f"espalier.__version__ mismatch: pyproject says {expected!r}, "
            f"package says {pkg_out!r}",
            "espalier/__init__.py::__version__ has drifted from "
            "pyproject.toml::project.version - bump them in lockstep",
        ))

    return expected


# ── Settings inspection ────────────────────────────────────────────────────


def count_wired_hooks(settings: dict) -> int:
    """Total number of hook command entries across all events."""
    hooks_cfg = settings.get("hooks", {})
    if not isinstance(hooks_cfg, dict):
        return 0
    n = 0
    for event_entries in hooks_cfg.values():
        if not isinstance(event_entries, list):
            continue
        for entry in event_entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []) or []:
                if isinstance(hook, dict) and hook.get("command"):
                    n += 1
    return n


# ── Surface assertions ──────────────────────────────────────────────────────


def assert_surface(target: Path) -> None:
    """Assert the deployed surface in ``target`` matches the expected surface.

    Raises :class:`SmokeFailure` on the first failed assertion. Each failure
    message names the missing class so operators can map red CI to the
    likely root cause without re-reading the pack.
    """
    # 1. Commands count
    commands = sorted((target / ".claude" / "commands").glob("*.md"))
    if len(commands) != EXPECTED_COMMAND_COUNT:
        raise SmokeFailure(format_failure(
            f"wheel init deployed {len(commands)} commands, "
            f"expected {EXPECTED_COMMAND_COUNT}",
            "Two failure modes share this assertion. Determine which by "
            "inspecting espalier/assets/claude/commands/: "
            "(1) if the asset tree has EXPECTED_COMMAND_COUNT files, then "
            ".claude command assets aren't installed by the wheel - check "
            "pyproject.toml [tool.setuptools.package-data] for "
            "espalier/assets/claude/commands/*.md. "
            "(2) if the asset tree has a different count, "
            "EXPECTED_COMMAND_COUNT is wrong - it derives "
            "via _count_packaged_assets(), so a stale value means the "
            "derivation broke (REPO_ROOT resolving wrong, etc.).",
        ))

    # 2. Skills count
    skills = sorted((target / ".claude" / "skills").glob("*/SKILL.md"))
    if len(skills) != EXPECTED_SKILL_COUNT:
        raise SmokeFailure(format_failure(
            f"wheel init deployed {len(skills)} skills, "
            f"expected {EXPECTED_SKILL_COUNT}",
            ".claude skill SKILL.md files are not included as package resources - "
            "check espalier/assets/claude/skills/*/SKILL.md",
        ))

    # 3. Agents floor
    agents = sorted((target / ".claude" / "agents").glob("*.md"))
    if len(agents) < EXPECTED_AGENT_COUNT_MIN:
        raise SmokeFailure(format_failure(
            f"wheel init deployed {len(agents)} agents, "
            f"expected at least {EXPECTED_AGENT_COUNT_MIN}",
            ".claude rich agent assets are missing - "
            "check espalier/assets/claude/agents/*.md",
        ))

    # 4. Canonical-rich-agents check BY NAME intentionally absent.
    # ``espalier/assets/claude/agents/`` ships the rich agent roster (the
    # floor at step 3 is derived from it, seven at HEAD); a hand-kept
    # name list here would duplicate that derived floor and drift with
    # the roster (an earlier name-list block did exactly that and turned
    # every release CI run red -- see tests/test_wheel_smoke.py). What this
    # script does NOT check anywhere is deployed CONTENT: a file with the
    # right name and the wrong bytes passes. The in-repo asset trees' byte
    # parity is tests/test_package_resource_parity.py's job
    # (TestAssetClaudeMirrorParity, TestRootMirrorParity);
    # tests/test_wheel_install_surface_parity.py compares path SETS only.
    # The bytes a wheel install actually deploys are pinned by nothing today.

    # 5. Settings: 12 wired hook commands
    settings_path = target / ".claude" / "settings.json"
    if not settings_path.is_file():
        raise SmokeFailure(format_failure(
            ".claude/settings.json missing",
            "init did not write settings.json - check cmd_init step 4 in cli.py",
        ))
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except ValueError as exc:  # JSONDecodeError, or the decode itself (DEF-829)
        raise SmokeFailure(format_failure(
            f".claude/settings.json is not valid JSON: {exc}",
            "init wrote malformed JSON - check _build_settings_json in cli.py",
        )) from exc
    n_hooks = count_wired_hooks(settings)
    if n_hooks != EXPECTED_WIRED_HOOK_COUNT:
        raise SmokeFailure(format_failure(
            f"settings.json wires {n_hooks} hook commands, "
            f"expected {EXPECTED_WIRED_HOOK_COUNT}",
            "_build_settings_json in cli.py is out of sync with the canonical "
            "hook roster - see surface_contract.get_canonical_hook_scripts()",
        ))

    # 6. tools/cc/hooks: 12 entry scripts (non-underscore)
    hooks_dir = target / "tools" / "cc" / "hooks"
    if not hooks_dir.is_dir():
        raise SmokeFailure(format_failure(
            "tools/cc/hooks/ missing",
            "init did not deploy the hook scripts - check INIT_HOOK_SCRIPTS in cli.py",
        ))
    entry_scripts = sorted(
        p for p in hooks_dir.glob("*.py")
        if not p.name.startswith("_")
    )
    if len(entry_scripts) != EXPECTED_HOOK_ENTRY_COUNT:
        raise SmokeFailure(format_failure(
            f"tools/cc/hooks has {len(entry_scripts)} entry scripts, "
            f"expected {EXPECTED_HOOK_ENTRY_COUNT}",
            "INIT_HOOK_SCRIPTS in cli.py is out of sync with the live hook set",
        ))

    # 7. Hook helpers
    helper_paths = sorted(hooks_dir.glob("_*.py"))
    helper_names = {p.name for p in helper_paths if p.name != "__init__.py"}
    expected = set(EXPECTED_HOOK_HELPERS)
    missing_helpers = sorted(expected - helper_names)
    extra_helpers = sorted(helper_names - expected)
    if missing_helpers or extra_helpers:
        problems = []
        if missing_helpers:
            problems.append(f"missing: {missing_helpers}")
        if extra_helpers:
            problems.append(f"unexpected extras: {extra_helpers}")
        raise SmokeFailure(format_failure(
            f"tools/cc/hooks helper module set drift - {'; '.join(problems)}",
            "INIT_HOOK_SCRIPTS in cli.py and EXPECTED_HOOK_HELPERS in "
            f"wheel_smoke.py must agree - expected exactly "
            f"{sorted(expected)}",
        ))

    # 8 + 9. install-ci surface
    workflow = target / ".github" / "workflows" / "harness-guard.yml"
    if not workflow.is_file():
        raise SmokeFailure(format_failure(
            ".github/workflows/harness-guard.yml missing",
            "install-ci did not write the workflow - check cmd_install_ci in cli.py "
            "(workflow now reads via espalier.assets.github_workflow_asset)",
        ))
    ci_guard = target / "tools" / "cc" / "ci_guard.py"
    if not ci_guard.is_file():
        raise SmokeFailure(format_failure(
            "tools/cc/ci_guard.py missing",
            "install-ci did not write ci_guard.py - check cmd_install_ci copy step",
        ))

    # 10/11/12. cc/ surface
    for rel in ("cc/COMMANDS.md", "cc/LIVE_SURFACE.md", "cc/PACK_MANIFEST.txt"):
        p = target / rel
        if not p.is_file():
            raise SmokeFailure(format_failure(
                f"{rel} missing",
                f"init did not render {rel} - check write_required_surface in cli.py",
            ))

    # 13. Integrity manifest
    integrity = target / ".espalier" / "integrity.json"
    if not integrity.is_file():
        raise SmokeFailure(format_failure(
            ".espalier/integrity.json missing",
            "init did not seed the integrity manifest - check cmd_init step 4b in cli.py",
        ))


# ── Orchestrator ───────────────────────────────────────────────────────────


def _git_init(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        ["git", "init", "--quiet"], cwd=str(target),
    )


def run_smoke(args: argparse.Namespace) -> SmokeReport:
    """Run the full wheel-smoke sequence; return a populated report."""
    report = SmokeReport()

    if args.wheel:
        wheel = Path(args.wheel).resolve()
        if not wheel.is_file():
            raise SmokeFailure(format_failure(
                f"--wheel {wheel} does not exist",
                "pass an existing wheel path or omit --wheel to build one",
            ))
        report.add(StepResult("locate_wheel", "PASS", str(wheel)))
    else:
        if args.skip_build:
            raise SmokeFailure(format_failure(
                "--skip-build requires --wheel PATH",
                "either pass --wheel to point at an existing wheel or drop --skip-build",
            ))
        scratch_dist = Path(tempfile.mkdtemp(prefix="wheel-smoke-dist-"))
        try:
            wheel = build_wheel(REPO_ROOT, scratch_dist)
            report.add(StepResult("build_wheel", "PASS", wheel.name))
        except subprocess.CalledProcessError as exc:
            shutil.rmtree(scratch_dist, ignore_errors=True)
            raise SmokeFailure(format_failure(
                f"wheel build failed: rc={exc.returncode}",
                "check `python -m build --wheel --no-isolation` output above",
            )) from exc
    report.wheel_path = str(wheel)

    scratch = Path(tempfile.mkdtemp(prefix="wheel-smoke-"))
    venv_dir = scratch / "venv"
    target = scratch / "target"
    report.target = str(target)

    try:
        install_wheel(wheel, venv_dir)
        report.add(StepResult("install_wheel", "PASS", str(venv_dir)))

        # Sanity: CLI entry point + version
        version = run_cli(venv_dir, "--version").strip()
        report.add(StepResult("cli_entry", "PASS", version))

        # Assert pyproject + CLI + __version__ all match.
        pyproject = REPO_ROOT / "pyproject.toml"
        parity_version = assert_version_parity(venv_dir, pyproject)
        report.add(StepResult("version_parity", "PASS", parity_version))

        _git_init(target)
        report.add(StepResult("git_init", "PASS", str(target)))

        # Plain init now deploys the FULL packaged asset set — the
        # harness-dev deploy tier was retired, so every consumer gets the
        # same surface (EXPECTED_* derive from _count_packaged_assets, every
        # bundled asset). This smoke verifies the wheel can deploy everything
        # it packages.
        run_cli(venv_dir, "init", str(target))
        report.add(StepResult("espalier_init", "PASS"))

        run_cli(venv_dir, "install-ci", str(target))
        report.add(StepResult("espalier_install_ci", "PASS"))

        # doctor — surface health (does not modify state)
        run_cli(venv_dir, "doctor", str(target))
        report.add(StepResult("espalier_doctor", "PASS"))

        # audit — proof gates
        run_cli(venv_dir, "audit", str(target))
        report.add(StepResult("espalier_audit", "PASS"))

        # integrity verify — manifest matches deployed state
        run_cli(venv_dir, "integrity", "verify", str(target))
        report.add(StepResult("espalier_integrity_verify", "PASS"))

        assert_surface(target)
        report.add(StepResult("assert_surface", "PASS",
                              f"{EXPECTED_COMMAND_COUNT} commands / "
                              f"{EXPECTED_SKILL_COUNT} skills / "
                              f">={EXPECTED_AGENT_COUNT_MIN} agents / "
                              f"{EXPECTED_WIRED_HOOK_COUNT} hooks"))
    finally:
        if not args.keep_temp:
            shutil.rmtree(scratch, ignore_errors=True)
            if not args.wheel:
                # We built into our own scratch dist; clean it too.
                shutil.rmtree(Path(wheel).parent, ignore_errors=True)
        else:
            print(f"  --keep-temp: scratch retained at {scratch}", file=sys.stderr)

    return report


def _print_human(report: SmokeReport) -> None:
    width = max((len(s.name) for s in report.steps), default=10) + 2
    for s in report.steps:
        line = f"  {s.name:<{width}}{s.status}"
        if s.detail:
            line += f"   {s.detail}"
        print(line)
    print()
    print(f"wheel_smoke {report.status}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="wheel_smoke",
        description=(
            "Build (or use) a wheel, install into a fresh venv + target repo, "
            "exercise the CLI, and assert the deployed harness surface. "
            "The canonical release smoke."
        ),
    )
    parser.add_argument(
        "--wheel", default=None,
        help="Path to an existing espalier_harness-*.whl. "
             "Without --wheel, a wheel is built into a scratch dir.",
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="Require --wheel; do not build a fresh wheel.",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="Leave the scratch venv + target repo on disk for inspection.",
    )
    parser.add_argument(
        "--json", dest="emit_json", action="store_true",
        help="Emit a machine-readable JSON summary at the end.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_smoke(args)
    except SmokeFailure as exc:
        if args.emit_json:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        msg = format_failure(
            f"subprocess failed: {exc.cmd} (rc={exc.returncode})",
            "check the failing command's output above",
        )
        if args.emit_json:
            print(json.dumps({"status": "FAIL", "error": msg}, indent=2))
        else:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    if args.emit_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report)
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
