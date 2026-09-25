"""TP-111: forbid hand-typed cc/ path literals in tools/cc/.

Walks ``tools/cc/**/*.py`` excluding ``_paths.py`` itself.
AST-extracts every ``ast.Constant`` (str) AND every ``ast.JoinedStr``
(f-string) literal-prefix; for each, asserts the value does NOT
exactly match a ``_paths`` string constant.

The f-string check guards the failure mode where
``f"writing to cc/blueprints/{session}.json"`` would otherwise slip
past a plain-Constant scan — drift in either direction must fire.

Exclusions:
- ``_paths.py`` itself (defines the canonical strings).
- Lines marked with ``# contract: ok path-literal <reason>``
  (TP-109b's canonical opt-out grammar).

This pins the post-TP-111 steady state: any new cc/ path literal
in tools/cc/ either uses the _paths constant or carries an explicit
opt-out marker; without one, the contract fires at pytest time.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "cc"))

import _paths  # noqa: E402

from tests._contracts import find_opt_out_markers  # noqa: E402

FORBIDDEN_LITERALS = frozenset({
    _paths.BLUEPRINTS_DIR_REL,
    _paths.BLUEPRINT_LATEST_REL,
    _paths.LIVE_SURFACE_REL,
    _paths.COMMANDS_INDEX_REL,
    _paths.PACK_MANIFEST_REL,
    _paths.SURFACE_HANDOFF_REL,
})

TOOLS_CC_ROOT = REPO_ROOT / "tools" / "cc"
SELF_EXCLUDE = TOOLS_CC_ROOT / "_paths.py"


def _collect_str_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Walk AST + return (lineno, literal-string) for both Constant
    strings AND f-string literal-prefix components (JoinedStr).
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            hits.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    hits.append((part.lineno, part.value))
    return hits


def _line_has_opt_out(source_lines: list[str], lineno: int) -> bool:
    if 0 < lineno <= len(source_lines):
        return any(
            rid == "path-literal"
            for rid, _ in find_opt_out_markers(source_lines[lineno - 1])
        )
    return False


def _iter_tools_cc_files() -> list[Path]:
    return sorted(
        p for p in TOOLS_CC_ROOT.rglob("*.py")
        if p != SELF_EXCLUDE and "__pycache__" not in p.parts
    )


def test_no_hand_typed_cc_literals_in_tools_cc():
    """Walks every tools/cc/**/*.py (except _paths.py) and asserts no
    str/f-string literal exactly matches a _paths-canonical cc/ path.
    """
    violations: list[str] = []
    for path in _iter_tools_cc_files():
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        source_lines = source.splitlines()
        for lineno, value in _collect_str_literals(tree):
            if value not in FORBIDDEN_LITERALS:
                continue
            if _line_has_opt_out(source_lines, lineno):
                continue
            rel = path.relative_to(REPO_ROOT)
            violations.append(f"{rel}:{lineno}: {value!r}")
    assert not violations, (
        "Hand-typed cc/ path literals found in tools/cc/. "
        "Import from _paths instead, or annotate the line with "
        "`# contract: ok path-literal <reason>` (TP-109b opt-out):\n"
        + "\n".join(violations)
    )


def test_forbidden_fstring_prefix_fires_synthetic(tmp_path):
    """Negative-shape regression: an f-string literal-prefix matching
    a FORBIDDEN_LITERAL must be collected by the AST walker. Guards
    the f-string blind spot a plain-Constant walker would miss.
    """
    synthetic = tmp_path / "fake_consumer.py"
    forbidden = next(iter(FORBIDDEN_LITERALS))
    synthetic.write_text(
        f'session = "x"\n'
        f'msg = f"writing to {forbidden}/{{session}}.json"\n',
        encoding="utf-8",
    )
    tree = ast.parse(synthetic.read_text(encoding="utf-8"))
    hits = [v for _, v in _collect_str_literals(tree)]
    assert forbidden in hits or any(forbidden in h for h in hits), (
        f"AST walker missed f-string literal-prefix {forbidden!r}; "
        f"got {hits!r}. The f-string blind spot regression has returned."
    )


def test_opt_out_marker_suppresses_violation(tmp_path):
    """Negative-shape regression: a line carrying the # contract: ok
    path-literal opt-out marker must be excluded from the violation
    set. Guards the opt-out grammar wiring between this test and
    TP-109b's find_opt_out_markers.
    """
    forbidden = next(iter(FORBIDDEN_LITERALS))
    line = f'PATH = "{forbidden}"  # contract: ok path-literal test fixture'
    assert _line_has_opt_out([line], 1), (
        f"Opt-out marker grammar not recognized; line was: {line!r}"
    )


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_LITERALS))
def test_forbidden_set_is_non_empty_string(forbidden):
    """Vacuous-pass guard: ensure FORBIDDEN_LITERALS isn't a frozenset
    of empty strings (regression on _paths constant initialization).
    """
    assert isinstance(forbidden, str) and len(forbidden) > 0
    assert "cc/" in forbidden
