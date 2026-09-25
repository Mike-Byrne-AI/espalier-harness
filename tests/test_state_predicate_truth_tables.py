"""TP-117: every predicate over a state field must have a truth-
table test covering EVERY value in the field's domain.

Catches the TP-33 / 'predicate includes closed state' bug class:
a predicate function (``_has_active_plan``, ``_is_terminal``, etc.)
that reads a state field but doesn't exhaustively handle every
value in the domain.

Convention: predicate truth-table tests are parametrized over
``field.domain`` and assert ``predicate(setup_state(value)) ==
field.predicates[predicate_name][value]``.
"""
import sys
from pathlib import Path

import pytest

from _state_machines import STATE_FIELDS

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_predicate_bindings():
    """Map predicate-name -> (callable, value->input setup) for the predicates
    that are PURE functions of their input (no filesystem / process state).

    TP-151 H-1: the contract test below only asserted DECLARATION shape (value
    in domain, expected is a bool) — a corrupted registry value
    (``gate_passed['pass']: True->False``) slipped straight through. These
    bindings let ``test_predicate_binding_matches_registry`` actually CALL each
    predicate and pin the registry to real behavior.

    The file-reading ``_has_active_plan`` twins are intentionally excluded —
    they need a plan file on disk, and their EXECUTING parity is already owned
    by ``tests/test_task_router.py::TestSisterPredicateParity`` (named in the
    registry comment). Excluding them is the "exclude fields that omit the
    binding" option, not a coverage gap.
    """
    cc_dir = REPO_ROOT / "tools" / "cc"
    hooks_dir = cc_dir / "hooks"
    for p in (str(cc_dir), str(hooks_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import _integrity  # tools/cc/hooks/_integrity.py
    import _maintenance_mode  # tools/cc/hooks/_maintenance_mode.py
    import cognitive_blueprint  # tools/cc/cognitive_blueprint.py

    return {
        # gate dict {"status": v}; the domain value IS the status string.
        "gate_passed": (
            cognitive_blueprint.gate_passed,
            lambda v: {"status": v},
        ),
        # settings dict; "absent" -> no key, else disableAllHooks bool.
        "is_kill_switch_set": (
            _integrity.is_kill_switch_set,
            lambda v: {} if v == "absent" else {"disableAllHooks": (v == "true")},
        ),
        # env string | None; "unset" -> None, else the literal "0"/"1".
        "_maintenance_mode_active": (
            _maintenance_mode._maintenance_mode_active,
            lambda v: None if v == "unset" else v,
        ),
    }


def _bindable_cases():
    bindings = _load_predicate_bindings()
    for field in STATE_FIELDS:
        for pred_name, truth_table in field.predicates.items():
            binding = bindings.get(pred_name)
            if binding is None:
                continue
            fn, setup = binding
            for value, expected in truth_table.items():
                yield (pred_name, fn, setup, value, expected)


@pytest.mark.parametrize(
    "pred_name,fn,setup,value,expected",
    list(_bindable_cases()),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_predicate_binding_matches_registry(pred_name, fn, setup, value, expected):
    """TP-151 H-1: BIND each pure-predicate's registry truth table to the REAL
    implementation. The declaration test only checks shape, so a registry that
    LIES about a predicate (a flipped expected value) would pass it. This test
    calls ``predicate(setup_state(value))`` and asserts it equals the declared
    expectation — a regressed predicate OR a wrong registry value fails here."""
    actual = fn(setup(value))
    assert actual is expected, (
        f"{pred_name}({setup(value)!r}) returned {actual!r} but the "
        f"_state_machines registry declares {expected!r} for value {value!r}. "
        f"Either the predicate regressed or the registry truth table is wrong."
    )


def _all_predicates():
    for field in STATE_FIELDS:
        for pred_name, truth_table in field.predicates.items():
            for value, expected in truth_table.items():
                yield (field, pred_name, value, expected)


@pytest.mark.parametrize(
    "field,pred_name,value,expected",
    list(_all_predicates()),
    ids=lambda x: x if isinstance(x, str) else (
        x.name if hasattr(x, "name") else str(x)
    ),
)
def test_predicate_truth_table_covered(field, pred_name, value, expected):
    """Each (predicate, value) in field.predicates declares an
    EXPECTED boolean. This test asserts the declaration alone; the
    BEHAVIORAL test (does the predicate actually return that value
    for that state?) is in the predicate's normal test file
    (tests/test_plan_guard.py for _has_active_plan, etc.).

    This contract catches: someone removed a domain value from a
    predicate's truth table without removing it from field.domain
    (which would silently weaken coverage).
    """
    assert value in field.domain, (
        f"Predicate {pred_name!r} declares truth-table entry for "
        f"value {value!r} but {value!r} is NOT in "
        f"{field.name!r}.domain. Either add to domain or remove "
        f"from predicate truth table."
    )
    assert isinstance(expected, bool), (
        f"Predicate {pred_name!r} truth-table entry for {value!r} "
        f"is not a bool: {expected!r}"
    )


def test_every_predicate_covers_full_domain():
    """For each predicate, assert its truth-table keys equal
    field.domain. Catches partial coverage (predicate handles
    'in_progress' + 'complete' but not 'blocked')."""
    failures = []
    for field in STATE_FIELDS:
        domain = set(field.domain)
        for pred_name, truth_table in field.predicates.items():
            covered = set(truth_table.keys())
            missing = domain - covered
            extra = covered - domain
            if missing or extra:
                failures.append(
                    f"  {field.name}::{pred_name}: missing={sorted(missing)}, "
                    f"extra={sorted(extra)}"
                )
    assert not failures, (
        "Predicate truth tables don't cover full domain:\n"
        + "\n".join(failures)
    )
