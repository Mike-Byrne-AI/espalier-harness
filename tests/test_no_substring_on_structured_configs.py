"""TP-147 147-E: structured config files (TOML, YAML, JSON) must be
read structurally, not via substring scan.

Class of bug: ``pyproject_text = path.read_text().lower(); if "[tool.x]"
in pyproject_text`` false-fires on commented headers, docstring-embedded
TOML, and any prose mention of the section name inside the file. The
cure for the load-bearing form is ``tomllib.loads()`` / ``yaml.safe_load()``
/ ``json.loads()``. For genuinely textual scans (e.g., scanning an
issue template body for user-facing prose), the file declares an
explicit exemption marker so the reason stays at the surface.

The contract scans ``espalier/`` + ``tools/cc/`` for the chained shape
``X.read_text(...).lower()`` and ``func(...).lower()`` where ``func``
is a known config-reading helper (``_safe_text``). Modules carrying
the marker ``# allow-text-scan-of-structured-config: <reason>`` are
exempted file-wide — the reason text is the audit trail.

Multi-line patterns (assign, then ``.lower()`` on the next line) are
out of scope for v1: the inline chained shape is the only one in the
repo today (verified via grep at pack execution time). If a future
edit introduces a multi-line form, the in-line check below will not
catch it; the convention is "prefer structural parse" and reviewers
catch the multi-line form at PR time.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("espalier", "tools/cc")
MARKER = "# allow-text-scan-of-structured-config:"
CONFIG_READING_HELPERS = frozenset({"_safe_text"})


def _iter_py_files():
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            yield p


def _find_chained_lower_hits(tree: ast.AST) -> list[int]:
    """Return lineno of every ``X.lower()`` call whose receiver is one
    of the patterns flagged as substring-on-structured.

    Flagged receivers:
    - ``path.read_text(...)`` / ``path.read_bytes(...)`` (Attribute call)
    - ``_safe_text(path)`` (Name call to a known helper)
    """
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute) and node.func.attr == "lower"
        ):
            continue
        receiver = node.func.value
        if not isinstance(receiver, ast.Call):
            continue
        rfunc = receiver.func
        if isinstance(rfunc, ast.Attribute) and rfunc.attr in {
            "read_text", "read_bytes",
        }:
            hits.append(node.lineno)
            continue
        if isinstance(rfunc, ast.Name) and rfunc.id in CONFIG_READING_HELPERS:
            hits.append(node.lineno)
    return hits


def test_no_chained_lower_on_config_reads():
    drift: list[tuple[str, list[int]]] = []
    for py in sorted(_iter_py_files()):
        text = py.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        hits = _find_chained_lower_hits(tree)
        if hits:
            drift.append((py.relative_to(REPO_ROOT).as_posix(), hits))
    assert not drift, (
        "TP-147 147-E: chained `.read_text(...).lower()` / "
        "`_safe_text(...).lower()` shape detected on a structured-config "
        "read path. Convert to `tomllib.loads(...)` / `yaml.safe_load(...)` / "
        "`json.loads(...)`, OR add a module-level "
        f"`{MARKER} <reason>` comment if the substring scan is intentional "
        "and the reason is non-obvious.\n\nDrift sites:\n  "
        + "\n  ".join(f"{name}:{lines}" for name, lines in drift)
    )
