"""TP-02 §4 — source-init vs wheel-init deployed surface parity.

The structural ``test_artifact_parity`` suite proves the generated
``settings.json`` matches across source and wheel installs (modulo the
interpreter token). This module proves the *file tree itself* matches
across the public managed roots — commands, skills, agents, hooks,
workflows, surface docs, and integrity manifest. Adds the protection
that a future packaging mistake (e.g., dropping a glob from
``[tool.setuptools.package-data]``) cannot land silently.

Marked ``slow`` + ``release`` because each invocation builds a wheel
and provisions a venv. Local devs can run with::

    pytest -m 'slow and release' tests/test_wheel_install_surface_parity.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from espalier.artifact_parity import (
    _venv_python,
    build_wheel,
    run_init_source_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES (release + slow).


# ---------------------------------------------------------------------------
# Build availability — mirrors test_artifact_parity._require_build_or_skip
# ---------------------------------------------------------------------------


def _build_available() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--help"],
            capture_output=True, text=True, timeout=10, check=False, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0 or "usage" not in (result.stdout + result.stderr).lower():
        return False
    # `build --help` succeeds even without a build backend; the real build
    # (`--no-isolation`) needs setuptools.build_meta, which 3.12+ venvs no
    # longer bundle -- assert it so the skip-guard stops green-washing (W0-2).
    backend = subprocess.run(
        [sys.executable, "-c", "import setuptools.build_meta"],
        capture_output=True, text=True, timeout=10, check=False, encoding="utf-8",
    )
    return backend.returncode == 0


def _require_build_or_skip() -> None:
    if _build_available():
        return
    if os.environ.get("ESPALIER_ALLOW_PARITY_SKIP") == "1":
        pytest.skip("python -m build unavailable; ESPALIER_ALLOW_PARITY_SKIP=1 set")
    pytest.fail(
        "python -m build is required for the wheel surface parity test. "
        "Install with: pip install build. "
        "If this CI environment legitimately cannot build, set "
        "ESPALIER_ALLOW_PARITY_SKIP=1 explicitly."
    )


# ---------------------------------------------------------------------------
# Roots compared between source-init and wheel-init
# ---------------------------------------------------------------------------

# Public managed roots — same files must be present on both sides.
COMPARED_ROOTS: tuple[str, ...] = (
    ".claude/commands",
    ".claude/skills",
    ".claude/agents",
    "tools/cc/hooks",
    ".github/workflows",
    "cc",
    ".espalier",
    "memory",
    "docs/sharp-edges",
    "docs",
    "task-packs",
)

# Files allowed to differ in *presence* between the two sides. Empty by
# design — if anything ends up here, document the reason.
ALLOWED_PATH_DIFFERENCES: dict[str, frozenset[str]] = {
    # subdir → set of relative paths allowed to be missing on either side
}

# Volatile / local-only paths not compared at all.
EXCLUDED_FROM_COMPARISON: frozenset[str] = frozenset({
    "reports",
    ".claude/settings.local.json",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_install_ci_source(target_repo: Path) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "espalier.cli", "install-ci", str(target_repo)],
    )


def _run_install_ci_in_venv(venv_dir: Path, target_repo: Path) -> None:
    vpython = _venv_python(venv_dir)
    subprocess.check_call(
        [str(vpython), "-m", "espalier.cli", "install-ci", str(target_repo)],
    )


def _run_init_in_venv_only(wheel_path: Path, target_repo: Path) -> Path:
    """Install wheel into a venv + run init; return the venv path.

    Like ``run_init_in_clean_venv`` but returns the venv path so the
    caller can run additional CLI commands (install-ci) afterwards.
    """
    target_repo.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", str(target_repo)])
    venv_dir = target_repo.parent / "venv"
    subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    vpython = _venv_python(venv_dir)
    subprocess.check_call(
        [str(vpython), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
    )
    subprocess.check_call(
        [str(vpython), "-m", "pip", "install", "--quiet", str(wheel_path)],
    )
    subprocess.check_call(
        [str(vpython), "-m", "espalier.cli", "init", str(target_repo)],
    )
    return venv_dir


def _list_relative_files(root: Path, base: Path) -> set[str]:
    """Return the set of files under ``root``, expressed relative to ``base``."""
    if not root.is_dir():
        return set()
    out: set[str] = set()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        if any(rel == ex or rel.startswith(ex + "/") for ex in EXCLUDED_FROM_COMPARISON):
            continue
        out.add(rel)
    return out


# ---------------------------------------------------------------------------
# The parity check
# ---------------------------------------------------------------------------


def test_source_and_wheel_init_deploy_same_managed_surface(tmp_path):
    """Source-init and wheel-init deploy the same managed file set.

    Builds a wheel, runs ``espalier init`` + ``install-ci`` once with the
    source interpreter (target A) and once via a wheel-installed venv
    (target B), then compares the relative path sets across every
    managed root in ``COMPARED_ROOTS``.

    Mismatch hint: missing files on the wheel side usually means the
    package-data glob in ``pyproject.toml`` doesn't match a new asset
    type. Missing files on the source side usually means a new asset
    was packaged but the source-mode init step doesn't deploy it yet.
    """
    _require_build_or_skip()

    scratch = Path(tempfile.mkdtemp(prefix="wheel-surface-parity-"))
    try:
        # 1. Build the wheel once and reuse it.
        wheel = build_wheel(REPO_ROOT, scratch / "dist")

        # 2. Source-mode init + install-ci into target A.
        source_target = scratch / "source-target"
        run_init_source_path(source_target)
        _run_install_ci_source(source_target)

        # 3. Wheel-mode init + install-ci into target B (fresh venv).
        wheel_target = scratch / "wheel-target"
        venv = _run_init_in_venv_only(wheel, wheel_target)
        _run_install_ci_in_venv(venv, wheel_target)

        # 4. Compare each root — relative path set, not file content.
        diffs: list[str] = []
        for subdir in COMPARED_ROOTS:
            src_files = _list_relative_files(source_target / subdir, source_target)
            wh_files = _list_relative_files(wheel_target / subdir, wheel_target)
            allowed = ALLOWED_PATH_DIFFERENCES.get(subdir, frozenset())

            only_source = (src_files - wh_files) - allowed
            only_wheel = (wh_files - src_files) - allowed

            if only_source:
                diffs.append(
                    f"{subdir}: source-only files (wheel missing): "
                    f"{sorted(only_source)}"
                )
            if only_wheel:
                diffs.append(
                    f"{subdir}: wheel-only files (source missing): "
                    f"{sorted(only_wheel)}"
                )

        assert not diffs, (
            "wheel-init vs source-init deployed surface diverged:\n  "
            + "\n  ".join(diffs)
            + "\n\nLikely causes:\n"
            "  - missing pyproject.toml [tool.setuptools.package-data] glob\n"
            "  - source-mode init step not deploying a newly-packaged asset class\n"
            "  - install-ci not writing to a managed root on one side"
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
