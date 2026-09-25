"""Pin the SoT-vs-witness contract for tests/_surface_expected.py.

Walks every EXPECTED_X constant. If it carries `# class: derived`, asserts
that no test in tests/ uses it on the right-hand-side of an
`assert len(...) ==` where the left-hand-side also derives from the same SoT.

Prevents future regressions of the TP-12 / TP-74 / TP-136 convergence-theater
pattern at its structural root.
"""

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[1]
_TARGET = _REPO / "tests" / "_surface_expected.py"

# TP-225-B: the convergence-theater shape is "count of a producer == a derived
# SoT constant". The count can be spelled with any of these builtins, and the
# `==` is symmetric — `len(X) == EXPECTED_X`, `EXPECTED_X == len(X)`,
# `set(X) == EXPECTED_X`, `tuple(X) == EXPECTED_X` are all the same tautology.
# The pre-TP-225 predicate only caught left-hand `len(...)` and missed the other
# three spellings (AST-verified). `>=` / `<=` floors/ceilings stay legitimate
# and are still skipped by the ast.Eq guard below.
_COUNTING_BUILTINS = frozenset({"len", "set", "tuple", "frozenset"})


def _classified_constants() -> dict[str, str]:
    """Walk _surface_expected.py, return {name: class} for each EXPECTED_X."""
    text = _TARGET.read_text(encoding="utf-8")
    classes: dict[str, str] = {}
    for raw in text.splitlines():
        if "EXPECTED_" not in raw or "=" not in raw or "# class:" not in raw:
            continue
        head, _, tail = raw.partition("=")
        name = head.strip()
        cls_marker = tail.split("# class:", 1)[1].strip().split()[0]
        if cls_marker in {"derived", "literal"}:
            classes[name] = cls_marker
    return classes


def test_every_expected_constant_has_class_marker() -> None:
    """Every EXPECTED_X must carry `# class: derived` or `# class: literal`."""
    text = _TARGET.read_text(encoding="utf-8")
    missing: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("EXPECTED_"):
            continue
        if "=" not in stripped:
            continue
        if "# class:" not in stripped:
            missing.append(stripped.split("=")[0].strip())
    assert not missing, (
        f"_surface_expected.py constants missing class marker: {missing}. "
        "Add `# class: derived` or `# class: literal` per TP-137 §B contract."
    )


def test_derived_constants_not_used_as_witnesses() -> None:
    """No test asserts `len(producer) == EXPECTED_X` for a `derived` EXPECTED_X."""
    classes = _classified_constants()
    derived = {n for n, c in classes.items() if c == "derived"}
    if not derived:
        pytest.skip("no derived constants yet")

    offenders: list[str] = []
    for test_file in (_REPO / "tests").rglob("test_*.py"):
        if test_file.name == "test_surface_expected_witness_contract.py":
            continue
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            # Only `==` parity is the convergence-theater shape. `>=` /
            # `<=` represent floor / ceiling contracts that are
            # legitimately asymmetric (e.g., "deployed surface contains
            # at least the universal-floor agents"). Skip non-equality
            # comparisons.
            if not (node.ops and isinstance(node.ops[0], ast.Eq)):
                continue
            operands = [node.left, *node.comparators]
            # The shape is theater only if ONE operand is a counting builtin
            # call AND ANOTHER is a `derived` EXPECTED_X name — symmetric, so
            # we don't care which side each is on. TP-225-B broadened this from
            # left-hand-`len`-only to all of _COUNTING_BUILTINS on either side.
            has_counting_call = any(
                isinstance(op, ast.Call)
                and isinstance(op.func, ast.Name)
                and op.func.id in _COUNTING_BUILTINS
                for op in operands
            )
            if not has_counting_call:
                continue
            for op in operands:
                if isinstance(op, ast.Name) and op.id in derived:
                    offenders.append(
                        f"{test_file.relative_to(_REPO)}:{node.lineno} — "
                        f"uses derived `{op.id}` as independent witness"
                    )

    assert not offenders, (
        "convergence theater: tests asserting len(producer) == derived "
        "EXPECTED_X are tautological:\n  " + "\n  ".join(offenders) + "\n"
        "Either pin EXPECTED_X as `# class: literal`, or use an independent "
        "witness (e.g., committed-file vs live-rendered, or AST-extracted "
        "pattern string from two distinct producer modules)."
    )


def test_witness_scanner_catches_all_counting_spellings():
    """TP-225-B regression pin: the convergence-theater detector must flag a
    derived EXPECTED_X used as a witness in ANY counting spelling, not just
    left-hand `len(...)`.

    Pre-TP-225 the predicate matched only `len(X) == Name`; reversed,
    `set(...)`, and `tuple(...)` forms slipped through (AST-verified). Without
    this pin a future contributor could re-narrow the predicate and silently
    re-open the three spellings. The four shapes below are the exact bypass
    set; the two legitimate floor/ceiling forms must stay un-flagged.
    """
    derived = {"EXPECTED_X"}

    def _flags(code: str) -> bool:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not (node.ops and isinstance(node.ops[0], ast.Eq)):
                continue
            operands = [node.left, *node.comparators]
            has_counting = any(
                isinstance(op, ast.Call)
                and isinstance(op.func, ast.Name)
                and op.func.id in _COUNTING_BUILTINS
                for op in operands
            )
            if not has_counting:
                continue
            if any(isinstance(op, ast.Name) and op.id in derived for op in operands):
                return True
        return False

    # Theater — must be flagged.
    assert _flags("assert len(producer) == EXPECTED_X")
    assert _flags("assert EXPECTED_X == len(producer)")
    assert _flags("assert set(producer) == EXPECTED_X")
    assert _flags("assert tuple(producer) == EXPECTED_X")
    assert _flags("assert frozenset(producer) == EXPECTED_X")
    # Legitimate — must NOT be flagged (floor / ceiling / no counting call).
    assert not _flags("assert len(producer) >= EXPECTED_X")
    assert not _flags("assert len(producer) <= EXPECTED_X")
    assert not _flags("assert producer == EXPECTED_X")
