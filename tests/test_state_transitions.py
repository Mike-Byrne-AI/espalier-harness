"""TP-117: every registered state-machine transition must be unit-tested.

This contract pins the (state_field, transition) -> test_function
mapping declared in tests/_state_machines.py. It guards against the
sticky-state regression class (TP-102 missing-else branch where
plan-level status stayed sticky-blocked forever) and the predicate-
includes-closed-state class (TP-33 _has_active_plan off-by-one)
by forcing every declared transition to have an exercising test in
the registered location. Without this contract, adding a new
transition to STATE_FIELDS without authoring its test silently
weakens coverage; renaming a test function (or letting drift between
the field name and the test name go unnoticed) silently strands
transitions as untested.

Convention: tests are named
``test_<field>_<from>_to_<to>_transition`` so they're discoverable +
greppable. Tests for STATE FIELDS owned by tools/cc/execution_plan.py
go in tests/test_execution_plan.py. Tests for plan_guard predicates
go in tests/test_plan_guard.py. The contract walks the implementation-
test mapping in TRANSITION_TEST_LOCATIONS below.
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
from _state_machines import STATE_FIELDS


# Map state-field name -> test file that owns its transition tests
TRANSITION_TEST_LOCATIONS: dict[str, str] = {
    "execution_plan.steps[i].status": "tests/test_execution_plan.py",
    "execution_plan.status": "tests/test_execution_plan.py",
    "plan_guard plan-level state": "tests/test_plan_guard.py",
    "blueprint gate_status": "tests/test_cognitive_blueprint.py",
    "kill_switch active": "tests/test_write_guard.py",
    "maintenance_mode flag": "tests/test_maintenance_mode.py",
}


def _substantive_test_exists(test_path: Path, fn_name: str) -> bool:
    """True iff ``fn_name`` exists in ``test_path`` AND actually verifies
    something — at least one ``assert`` or a ``with`` (e.g. ``pytest.raises``)
    block.

    TP-152 C-5: the pre-fix check (``_test_function_exists``) matched on the
    name alone, so a renamed-but-empty stub (``pass`` / docstring-only) could
    satisfy the transition-coverage contract vacuously. Body-discrimination
    is the sister discipline of
    ``test_test_quality._function_has_real_assertion``.
    """
    try:
        tree = ast.parse(test_path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return False
    for node in ast.walk(tree):
        # DR7 round-7 (TP-196): include AsyncFunctionDef — the documented sister
        # of test_test_quality._function_has_real_assertion carried the same
        # async-blind walk, so an `async def test_..._transition()` was reported
        # as missing (a false transition-coverage gap). Fixed in lockstep.
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == fn_name):
            return _verifies_something(node)
    return False


def _verifies_something(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A test verifies something if it has a bare ``assert``, a ``with``
    (e.g. ``pytest.raises``), OR calls an assert-helper (``_assert_*`` /
    ``self.assertEqual`` — many transition tests delegate to a shared
    ``_assert_transition(...)``). A pass/docstring-only stub has none."""
    for n in ast.walk(node):
        if isinstance(n, (ast.Assert, ast.With)):
            return True
        if isinstance(n, ast.Call):
            func = n.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else ""
            )
            if "assert" in name.lower():
                return True
    return False


_NAME_NORMALIZATIONS: tuple[tuple[str, str], ...] = (
    # Order matters: longest-prefix-first to avoid partial-match drift.
    ("execution_plan.steps[i].", "step_"),
    ("execution_plan.", "plan_"),
    ("plan_guard plan-level state", "plan_guard_state"),
    ("blueprint gate_status", "blueprint_gate_status"),
    ("kill_switch active", "kill_switch"),
    ("maintenance_mode flag", "maintenance_mode"),
)


def _transition_test_name(field_name: str, from_state: str, to_state: str) -> str:
    """Normalize a field name into a greppable test-function name.

    If the contract fires on a renamed field, the diff between the
    failing test name and the live field name is the rename
    discoverability signal -- consider whether the field was renamed
    and update _NAME_NORMALIZATIONS + STATE_FIELDS together.
    """
    short = field_name
    for pattern, replacement in _NAME_NORMALIZATIONS:
        short = short.replace(pattern, replacement)
    short = short.replace(".", "_").replace("[]", "")
    return f"test_{short}_{from_state}_to_{to_state}_transition"


@pytest.mark.parametrize(
    "field,transition",
    [
        (f, t)
        for f in STATE_FIELDS
        for t in f.transitions
    ],
    ids=lambda x: x.name if hasattr(x, "name") else f"{x[0]}_to_{x[1]}",
)
def test_transition_has_unit_test(field, transition):
    if not field.transitions:
        pytest.skip(f"{field.name}: no transitions declared")
    from_state, to_state = transition
    test_loc = TRANSITION_TEST_LOCATIONS.get(field.name)
    assert test_loc, (
        f"No test location registered for state field {field.name!r} "
        f"in TRANSITION_TEST_LOCATIONS"
    )
    expected_test_name = _transition_test_name(
        field.name, from_state, to_state
    )
    assert _substantive_test_exists(REPO_ROOT / test_loc, expected_test_name), (
        f"Transition {from_state} -> {to_state} for {field.name!r} is "
        f"declared in _state_machines.STATE_FIELDS but no substantive test "
        f"function {expected_test_name!r} (one that asserts) exists in "
        f"{test_loc}. Add a test that drives the transition and asserts the "
        f"new state is reached."
    )


def test_substantive_test_exists_rejects_name_only_stub(tmp_path):
    """TP-152 C-5 earn-the-red: a function that matches the name but only
    `pass`es (no assertion) must NOT satisfy the contract — that was the
    pre-fix gap that let a renamed empty stub pass the transition check."""
    stub = tmp_path / "test_stub.py"
    stub.write_text(
        "def test_real():\n    assert 1 == 1\n\n"
        "def test_empty():\n    pass\n\n"
        'def test_doc_only():\n    """only a docstring"""\n',
        encoding="utf-8",
    )
    assert _substantive_test_exists(stub, "test_real") is True
    assert _substantive_test_exists(stub, "test_empty") is False
    assert _substantive_test_exists(stub, "test_doc_only") is False
    assert _substantive_test_exists(stub, "test_absent") is False


def test_substantive_test_exists_handles_async(tmp_path):
    """DR7 round-7 (TP-196) earn-the-red: a transition test written as
    `async def` must be found and body-discriminated. Pre-fix the FunctionDef-
    only walk missed it, so the transition-coverage contract falsely reported
    an async-tested transition as MISSING (a workflow-friction false-positive).
    Sister of test_test_quality.test_walk_catches_async_vacuous_tests."""
    stub = tmp_path / "test_async_stub.py"
    stub.write_text(
        "async def test_real():\n    assert driver().state == 'done'\n\n"
        "async def test_empty():\n    pass\n",
        encoding="utf-8",
    )
    assert _substantive_test_exists(stub, "test_real") is True
    assert _substantive_test_exists(stub, "test_empty") is False
