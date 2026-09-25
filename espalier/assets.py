"""Resource lookup for bundled Espalier-Harness assets.

Wheel-installed Espalier reads its public harness surface (commands, skills,
agents, workflows) from package resources rather than from a source-checkout
``.claude/`` directory. This module is the single import surface for those
lookups; callers must not reach for ``Path(__file__).parent.parent / ".claude"``
or similar source-tree assumptions.

The package resource root is ``espalier/assets/`` with this layout::

    espalier/assets/claude/agents/<name>.md
    espalier/assets/claude/commands/<name>.md
    espalier/assets/claude/skills/<name>/SKILL.md
    espalier/assets/github/workflows/<name>.yml
"""
from __future__ import annotations

from importlib.resources import files
try:
    # ``importlib.resources.abc`` landed in 3.11; ``requires-python`` is >=3.10.
    # Try the modern location first so 3.11-3.14 (where ``importlib.abc.Traversable``
    # was *removed* in 3.14) keep using it; fall back to ``importlib.abc`` only on
    # 3.10, where that branch still carries ``Traversable``. Order is load-bearing.
    from importlib.resources.abc import Traversable
except ImportError:  # pragma: no cover - exercised on Python 3.10 only
    from importlib.abc import Traversable  # type: ignore[no-redef]

__all__ = [
    "AssetNotFound",
    "assets_root",
    "claude_assets_root",
    "github_workflow_asset",
    "iter_claude_asset_files",
]


class AssetNotFound(FileNotFoundError):
    """A required packaged asset is missing from the installed wheel."""


def assets_root() -> Traversable:
    """Return the package-relative root of bundled assets.

    Wheel-safe: returns a ``Traversable`` rooted at ``espalier/assets``. Use
    ``importlib.resources.as_file`` when a real filesystem ``Path`` is required.
    """
    return files("espalier").joinpath("assets")


def claude_assets_root() -> Traversable:
    """Return the package-relative root for ``.claude/`` deploy assets."""
    return assets_root().joinpath("claude")


def github_workflow_asset(name: str) -> Traversable:
    """Return the bundled GitHub Actions workflow named ``name``.

    Raises :class:`AssetNotFound` if the workflow is not packaged.
    """
    candidate = assets_root().joinpath("github", "workflows", name)
    if not candidate.is_file():
        raise AssetNotFound(
            f"packaged github workflow not found: assets/github/workflows/{name} "
            f"(action: github_workflow_asset)"
        )
    return candidate


def iter_claude_asset_files(subdir: str) -> list[Traversable]:
    """List packaged ``.claude/<subdir>`` files, recursively.

    ``subdir`` is one of ``"agents"``, ``"commands"``, ``"skills"``. Returns
    the ``Traversable`` for every regular file beneath that subtree, in a
    deterministic depth-first order. Raises :class:`AssetNotFound` if the
    subtree is missing entirely.
    """
    root = claude_assets_root().joinpath(subdir)
    if not root.is_dir():
        raise AssetNotFound(
            f"packaged claude subtree not found: assets/claude/{subdir} "
            f"(action: iter_claude_asset_files)"
        )
    out: list[Traversable] = []
    _collect_files(root, out)
    return out


def _collect_files(node: Traversable, out: list[Traversable]) -> None:
    if node.is_file():
        out.append(node)
        return
    for child in sorted(node.iterdir(), key=lambda n: n.name):
        _collect_files(child, out)
