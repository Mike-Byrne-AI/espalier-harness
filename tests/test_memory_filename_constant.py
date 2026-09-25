# pytest-marker: default-unit
"""Guard the per-file ``_MEMORY_FILENAME`` constants against a partial flip.

The committed project-memory filename is routed through a *per-file* module-level
constant (``_MEMORY_FILENAME = "ESPALIER_MEMORY.md"``) in every production file that names
it -- deliberately per-file rather than a single shared import, because
``espalier/scanners/`` is stdlib-only (``test_scanners_stdlib_only``) and cannot
import a cross-module constant, and ``tools/cc/`` scripts run standalone.

That design has one failure mode: a rename that flips only SOME of the constants
leaves a silent split-brain (some code points at the old name, some at the new).
Nothing else pins agreement, so this test does -- it turns a partial flip into a
RED instead of a runtime surprise.

The matcher is an AST scan of each module's top-level statements, not a regex: a
guard whose whole job is catching a rename must not itself be defeated by a
reformat. A ``: Final`` annotation, a single-quoted value, or extra spacing around
``=`` all evaded the old format-anchored regex (``^_MEMORY_FILENAME = "..."``), so
an annotated file could drop out of the agreement set and a partial flip pass
vacuously. The scan reads every module-level ``_MEMORY_FILENAME = "..."`` /
``_MEMORY_FILENAME: Final = "..."`` binding regardless of formatting, and excludes
``_LEGACY_MEMORY_FILENAME`` (a different target name) by construction.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ("espalier", "tools/cc")
_CONST_NAME = "_MEMORY_FILENAME"
# Sanity floor: fewer than this means the walk silently matched nothing (a broken
# test that would pass vacuously), not that the constants agree.
_MIN_EXPECTED = 12


def _memory_filename_values(text: str) -> list[str]:
    """Every module-level ``_MEMORY_FILENAME = "..."`` string value in ``text``,
    tolerant of a ``: Final`` annotation, quote style, and spacing. Excludes
    ``_LEGACY_MEMORY_FILENAME`` (a different target name) by construction. Returns
    ``[]`` for unparseable source rather than raising. Module-level bindings only —
    a nested (function/class-local) ``_MEMORY_FILENAME`` is a separate binding, not a
    cross-file split-brain."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    values: list[str] = []
    # Module-level statements only (the old ^-anchored regex matched column 0). A
    # function-local ``_MEMORY_FILENAME`` is a separate, intentional binding and must
    # not be read as a cross-file split-brain.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == _CONST_NAME for t in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            values.append(value.value)
    return values


class TestMemoryFilenameConstantAgreement:
    def test_all_per_file_constants_hold_one_value(self) -> None:
        found: list[tuple[str, str]] = []
        for rel in _SCAN_DIRS:
            for py in sorted((_REPO_ROOT / rel).rglob("*.py")):
                text = py.read_text(encoding="utf-8")
                for value in _memory_filename_values(text):
                    key = str(py.relative_to(_REPO_ROOT)).replace("\\", "/")
                    found.append((key, value))

        assert len(found) >= _MIN_EXPECTED, (
            f"expected >= {_MIN_EXPECTED} `_MEMORY_FILENAME =` definitions across "
            f"{_SCAN_DIRS}, found {len(found)} -- the walk broke or the constants "
            f"were removed (this guard would otherwise pass vacuously)."
        )

        values = sorted({value for _, value in found})
        assert len(values) == 1, (
            "per-file `_MEMORY_FILENAME` constants disagree (partial flip / "
            f"split-brain); a rename must flip ALL of them. Distinct values: "
            f"{values}\n" + "\n".join(f"  {key}: {value!r}" for key, value in found)
        )

    def test_matcher_is_annotation_quote_and_spacing_tolerant(self) -> None:
        """A reformatted constant -- ``: Final`` annotation, single quotes, or
        extra spacing around ``=`` -- must still be seen by the agreement guard.
        The old format-anchored regex (``^_MEMORY_FILENAME = "..."``) silently
        returned ``[]`` for each of these, so a partial flip that touched an
        annotated file passed vacuously. Earn-the-red: each variant below is
        invisible to that regex; the AST walk sees it."""
        for src in (
            '_MEMORY_FILENAME: Final = "ESPALIER_MEMORY.md"',
            "_MEMORY_FILENAME = 'ESPALIER_MEMORY.md'",
            '_MEMORY_FILENAME  =  "ESPALIER_MEMORY.md"',
            '_MEMORY_FILENAME: str = "ESPALIER_MEMORY.md"',
        ):
            assert _memory_filename_values(src) == ["ESPALIER_MEMORY.md"], src

    def test_legacy_constant_is_not_pulled_into_the_agreement_set(self) -> None:
        """``_LEGACY_MEMORY_FILENAME`` names the OLD file on purpose (migration
        detection) and must never be counted as a disagreeing value."""
        src = (
            '_LEGACY_MEMORY_FILENAME = "MEMORY.md"\n'
            '_MEMORY_FILENAME = "ESPALIER_MEMORY.md"\n'
        )
        assert _memory_filename_values(src) == ["ESPALIER_MEMORY.md"]

    def test_bare_annotation_without_value_is_ignored(self) -> None:
        """A bare ``_MEMORY_FILENAME: str`` annotation (no assigned value) has no
        string to agree on and must neither crash nor contribute a value."""
        assert _memory_filename_values("_MEMORY_FILENAME: str\n") == []
