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
    --stack NAME    Write the stack table's ``adopter-NAME`` row into the target
                    before its ``git init`` (``none``, the default: an empty tree).
    --spaced-root   Put the venv and the target under a directory whose name
                    holds a space.

Exit codes::

    0   PASS — every assertion held.
    1   FAIL — first failure terminates the run; failure reason printed.
"""
from __future__ import annotations

import argparse
import errno
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import types
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The file the suite's temp sweep reads in a work dir this script makes:
#: this process's pid, so a run killed mid-way leaves a dir the next session
#: start removes (``tests/_temp_sweep.py``); a run asked to keep its dir never
#: writes it, so a kept dir stays even when its run is killed.
LOCK_NAME = ".lock"
#: The suite's stack table: ``--stack`` writes its ``adopter-<stack>`` row into
#: the target. Loaded by path, so this script imports nothing of the suite,
#: and a run without ``--stack`` never reads it.
STACK_TABLE = REPO_ROOT / "tests" / "_stack_trees.py"
#: ``--stack``'s values. ``none`` is the default run's empty ``git init``; each
#: other names an adopter row of the table.
STACK_CHOICES: tuple[str, ...] = ("none", "python", "node", "go", "rust")
#: The directory ``--spaced-root`` puts the venv and the target under. The pid
#: lock stays on the mkdtemp root above it, which is where the sweep reads.
SPACED_ROOT_NAME = "spaced root"

# ── Expected deployed surface — single source of truth for the assertions ────
#
# EXPECTED_COMMAND_COUNT is derived from the package's bundled assets so a new
# command landing in espalier/assets/ keeps wheel_smoke honest without a manual
# bump. The literal constants below are stable enough that the
# canary tests in tests/test_wheel_smoke.py::TestExpectedCountsMatchPackagedAssets
# are sufficient — those tests independently assert each constant matches disk.


# The per-kind globs, spelled here because this script is stdlib-only and cannot
# import the owner (surface_contract.CLAUDE_KIND_GLOBS); tests/test_wheel_smoke.py
# pins the two equal, so a fifth kind added at the owner reds here instead of
# counting zero and passing vacuously.
KIND_GLOBS: dict[str, str] = {
    "agents": "*.md",
    "commands": "*.md",
    "skills": "*/SKILL.md",
    "workflows": "*.js",
}


def _visible(paths, base: Path) -> "list[Path]":
    """``paths`` without a dot-prefixed component below ``base``, sorted: the
    local twin of ``espalier._safe_walk.visible`` (§C28), kept local because
    this script proves the WHEEL and must not import the source tree."""
    return sorted(p for p in paths if not any(part.startswith(".") for part in p.relative_to(base).parts))


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
    return sum(1 for p in _visible(asset_dir.glob(KIND_GLOBS[kind]), asset_dir) if p.is_file())




EXPECTED_COMMAND_COUNT = _count_packaged_assets("commands")
EXPECTED_SKILL_COUNT = _count_packaged_assets("skills")
EXPECTED_WORKFLOW_COUNT = _count_packaged_assets("workflows")
EXPECTED_AGENT_COUNT_MIN = _count_packaged_assets("agents")
EXPECTED_HOOK_ENTRY_COUNT = 12
EXPECTED_HOOK_HELPER_COUNT = 15
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
    "_start_refusal.py",
    "_zone_watch.py",
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


#: The twins of ``espalier._rmtree``'s two constants: ``os.chmod`` takes
#: ``follow_symlinks=False`` (macOS, Windows from 3.13; not Linux), and
#: Windows, whose bare ``os.chmod`` never follows a link.
_CHMOD_NO_FOLLOW = os.chmod in os.supports_follow_symlinks
_BARE_CHMOD_IS_THE_LINKS = os.name == "nt"


def _add_owner_bits(path: str, bits: int) -> None:
    """Add ``bits`` for the owner on ``path`` itself, never through a link to
    a file outside the tree (DEF-5060): read by ``lstat``, set without
    following where ``os.chmod`` can, and a link left as it is where it
    cannot (Linux). The twin of ``espalier._rmtree._add_owner_bits``, driven
    over the same three arms beside it in ``tests/test_wheel_smoke.py``."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return
    wanted = stat.S_IMODE(mode) | bits
    try:
        if _CHMOD_NO_FOLLOW:
            os.chmod(path, wanted, follow_symlinks=False)
        elif _BARE_CHMOD_IS_THE_LINKS or not stat.S_ISLNK(mode):
            os.chmod(path, wanted)
    except OSError:
        pass


def _add_write_bit(path: str) -> None:
    """``chmod u+w``: the answer to every refusal but a directory's entry."""
    _add_owner_bits(path, stat.S_IWUSR)


def _key(path: str) -> str:
    """The one spelling a re-walked directory is remembered by."""
    return os.path.normpath(path).replace("\\", "/")


def _rmtree_with_handler(path: Path, handler) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=handler)
        return
    shutil.rmtree(path, onerror=lambda func, p, exc_info: handler(func, p, exc_info[1]))


def _remove_tree_clearing_bits(path: Path) -> None:
    """``shutil.rmtree`` that answers a permission refusal by adding the owner
    write bit to the entry and to its parent inside the tree (the tree's own
    root included, never the root's parent), then retrying once -- the
    discipline of ``espalier._rmtree.remove_tree``, stdlib only (a read-only
    entry, or a locked directory inside the tree, refuses a bare rmtree; a
    second refusal raises). The bit goes on the entry itself, never through a
    link (``_add_write_bit``). ``rmtree`` hands a refusal of the root itself
    back as the ``Path`` it was given, so the refused path is read through
    ``os.fspath`` (DEF-3023).

    A directory the walk cannot enter (``os.open`` on the fd walk,
    ``os.scandir`` on the walk Windows uses) is not retried bare: ``os.open``
    needs its flags, and ``rmtree`` has already skipped the subtree. It gets
    its owner read, write and search bits back and is walked again, once, and
    the walk's own later call on a directory removed that way, or on an entry
    it had queued inside one, is not a fault (DEF-5062, the engine's DEF-5054
    fix, driven alike in both deleters in ``tests/test_wheel_smoke.py``).
    """
    root = str(path)
    rewalked: set[str] = set()

    def _under_a_rewalk(failed: str) -> bool:
        key = _key(failed)
        return any(key == done or key.startswith(done + "/") for done in rewalked)

    def _on_failure(func, failed: str, exc: BaseException) -> None:
        if isinstance(exc, FileNotFoundError) and _under_a_rewalk(failed):
            return
        if not (isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM)):
            raise exc
        if func is os.open or func is os.scandir:
            try:
                is_directory = stat.S_ISDIR(os.lstat(failed).st_mode)
            except OSError:
                is_directory = False
            if _key(failed) in rewalked or not is_directory:
                raise exc
            rewalked.add(_key(failed))
            _add_owner_bits(failed, stat.S_IRWXU)
            _rmtree_with_handler(Path(failed), _on_failure)
            return
        refused = os.fspath(failed)  # ``rmtree`` hands the root back as it was given, a Path
        for target in (refused, os.path.dirname(refused)):
            if target == root or target.startswith(root + os.sep):
                _add_write_bit(target)
        func(failed)

    _rmtree_with_handler(path, _on_failure)


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

    Builds in ``repo_root`` itself, on purpose: this smoke is hand-run and runs
    alone. The suite builds through ``espalier.artifact_parity.build_wheel``,
    a namesake with the opposite cwd rule -- it stages a copy of the tree and
    never writes the root (DEF-1138, 2026-10-06; the scope-out is the
    operator's call, and ``tests/test_test_suite_contract.py`` names this file
    as one of the two allowed to build in place).

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
    """Read ``project.version`` from a ``pyproject.toml`` with the stdlib ``tomllib``.

    The wheel_smoke script is stdlib-only on purpose (it must run from a bare
    checkout or a fresh wheel-install venv with no third-party deps).
    """
    # Standalone stdlib-only version parse — intentionally NOT derived from
    # espalier.version_surfaces. This smoke test validates the BUILT wheel; deriving
    # "expected" from the wheel-under-test's own code would defeat the parity check.
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except ValueError as exc:  # strict decode: a structured answer (DEF-829)
        raise SmokeFailure(format_failure(
            f"pyproject.toml at {pyproject} is not UTF-8 TOML ({exc})",
            "the wheel cannot be version-checked without a canonical source - "
            "check that pyproject.toml decodes and parses",
        )) from exc
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if isinstance(version, str) and version:
        return version
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
    commands = _visible((target / ".claude" / "commands").glob("*.md"), target / ".claude" / "commands")
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
    skills = _visible((target / ".claude" / "skills").glob("*/SKILL.md"), target / ".claude" / "skills")
    if len(skills) != EXPECTED_SKILL_COUNT:
        raise SmokeFailure(format_failure(
            f"wheel init deployed {len(skills)} skills, "
            f"expected {EXPECTED_SKILL_COUNT}",
            ".claude skill SKILL.md files are not included as package resources - "
            "check espalier/assets/claude/skills/*/SKILL.md",
        ))

    # 2b. Workflows count (the .claude/workflows/*.js review scaffolds)
    workflows = _visible((target / ".claude" / "workflows").glob("*.js"), target / ".claude" / "workflows")
    if len(workflows) != EXPECTED_WORKFLOW_COUNT:
        raise SmokeFailure(format_failure(
            f"wheel init deployed {len(workflows)} workflows, "
            f"expected {EXPECTED_WORKFLOW_COUNT}",
            ".claude workflow .js files are not included as package resources - "
            "check espalier/assets/claude/workflows/*.js in pyproject.toml package-data",
        ))

    # 3. Agents floor
    agents = _visible((target / ".claude" / "agents").glob("*.md"), target / ".claude" / "agents")
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


def load_stack_table(stack: str) -> types.ModuleType:
    """The stack table module, checked to hold ``adopter-<stack>``.

    Loaded by path through ``importlib.util.spec_from_file_location``; the
    table is stdlib-only. A table that is absent or holds no such row fails
    the run: the smoke never falls back to the empty tree.
    """
    table = STACK_TABLE
    row = f"adopter-{stack}"
    if not table.is_file():
        raise SmokeFailure(format_failure(
            f"--stack {stack}: the stack table {table} is absent",
            "run from a source checkout, which holds tests/_stack_trees.py "
            "(an sdist does not), or drop --stack",
        ))
    spec = importlib.util.spec_from_file_location("_wheel_smoke_stack_trees", table)
    if spec is None or spec.loader is None:
        raise SmokeFailure(format_failure(
            f"--stack {stack}: the stack table {table} cannot be loaded",
            "the path must name a Python source file",
        ))
    module = importlib.util.module_from_spec(spec)
    # Registered while it runs: a dataclass in a module under postponed
    # annotations looks its module up in sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SmokeFailure(format_failure(
            f"--stack {stack}: the stack table {table} raised on load: {exc!r}",
            "the table must import with the standard library alone (tests/test_stack_trees.py)",
        )) from exc
    finally:
        sys.modules.pop(spec.name, None)
    stacks = getattr(module, "STACKS", None)
    if not isinstance(stacks, dict) or row not in stacks or not callable(getattr(module, "write_stack", None)):
        raise SmokeFailure(format_failure(
            f"--stack {stack}: the stack table {table} has no {row!r} row and write_stack",
            "a row was renamed or removed; each STACK_CHOICES value but none must be an "
            "adopter row of the table (tests/test_wheel_smoke.py pins each to one)",
        ))
    return module


def run_smoke(args: argparse.Namespace) -> SmokeReport:
    """Run the full wheel-smoke sequence; return a populated report."""
    report = SmokeReport()
    # Read first, so a table this run cannot use costs no build or install.
    stack_table = load_stack_table(args.stack) if args.stack != "none" else None

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
        if not args.keep_temp:
            (scratch_dist / LOCK_NAME).write_text(str(os.getpid()), encoding="utf-8")
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
    if not args.keep_temp:
        (scratch / LOCK_NAME).write_text(str(os.getpid()), encoding="utf-8")
    work = scratch / SPACED_ROOT_NAME if args.spaced_root else scratch
    work.mkdir(exist_ok=True)
    venv_dir = work / "venv"
    target = work / "target"
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

        if stack_table is not None:
            row = f"adopter-{args.stack}"
            stack_table.write_stack(target, row)
            report.add(StepResult("write_stack", "PASS", f"{row}: {len(stack_table.STACKS[row])} paths"))

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
    parser.add_argument(
        "--stack", choices=STACK_CHOICES, default="none",
        help="Write the adopter-<stack> row of tests/_stack_trees.py into the "
             "target before its git init; none (the default) leaves it empty.",
    )
    parser.add_argument(
        "--spaced-root", action="store_true",
        help="Put the venv and the target under a directory whose name holds a space.",
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
