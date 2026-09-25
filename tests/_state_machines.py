"""State-machine declarations for transition-coverage contracts.

Each entry pins:
- The state field's NAME and SOURCE (file path + JSON key path).
- The complete VALUE DOMAIN (closed enumeration).
- The allowed TRANSITIONS (directed pairs).
- The PREDICATES that read the field (each with their truth-table
  expectation across the full domain).

Adding a state field to a harness JSON surface requires adding an
entry here; the TP-117 contract test asserts every transition and
every predicate has a unit test exercising it.

Authored after TP-102 fixed ``execution_plan`` blocked-sticky
(missing demote branch) and TP-33 closed ``_has_active_plan`` off-by-
one (predicate included closed state). Predicate helpers
``gate_passed`` / ``is_kill_switch_set`` / ``_maintenance_mode_active``
authored in TP-117 sub-task 117-G as thin bool wrappers so the
truth-table contract has real implementations to bind against.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateField:
    """A JSON state field's complete shape: domain + transitions +
    predicate truth tables.
    """

    name: str                                    # e.g. "execution_plan.steps[i].status"
    source_file: str                             # e.g. "cc/execution_plan.json"
    json_key_path: str                           # e.g. "steps.[].status"
    domain: tuple[str, ...]                      # closed enumeration of values
    transitions: tuple[tuple[str, str], ...]    # (from_state, to_state) directed pairs
    predicates: dict[str, dict[str, bool]]      # predicate-name -> {value: expected-bool}


STATE_FIELDS: tuple[StateField, ...] = (
    StateField(
        name="execution_plan.steps[i].status",
        source_file="cc/execution_plan.json",
        json_key_path="steps.[].status",
        domain=("pending", "running", "passed", "failed"),
        transitions=(
            ("pending", "running"),
            ("running", "passed"),
            ("running", "failed"),
            ("failed", "running"),    # TP-102 fix -- re-open from failed
            ("passed", "running"),    # re-run after passed (allowed)
            ("pending", "failed"),    # skip-mark-failed (allowed)
        ),
        predicates={
            # No step-level predicates in the codebase today;
            # add entries as predicates are introduced.
        },
    ),
    StateField(
        name="execution_plan.status",
        source_file="cc/execution_plan.json",
        json_key_path="status",
        domain=("in_progress", "complete", "blocked"),
        transitions=(
            ("in_progress", "complete"),     # all steps passed
            ("in_progress", "blocked"),      # any step failed
            ("blocked", "in_progress"),      # TP-102 fix: failed->passed
            ("blocked", "complete"),         # all blocking failures now passed
        ),
        predicates={},
    ),
    StateField(
        name="plan_guard plan-level state",
        source_file="cc/execution_plan.json",
        json_key_path="status",
        # TP-150 §1.12: "non-dict" is the structural-malformity cell — a
        # valid-JSON top-level non-object (e.g. a list). It was the divergent
        # cell no prior pack enumerated; both sister predicates must classify
        # it as not-active.
        domain=("in_progress", "complete", "blocked", "missing", "non-dict"),
        transitions=(),  # transitions handled by execution_plan.status entry
        predicates={
            # plan_guard._has_active_plan(root): True ONLY for in_progress.
            # TP-33 closed the off-by-one where complete previously
            # returned True; document the truth table so a regression
            # fires.
            "_has_active_plan": {
                "in_progress": True,
                "complete": False,    # TP-33 -- was True pre-fix
                "blocked": False,
                "missing": False,
                "non-dict": False,    # TP-150 §1.12 -- non-dict parse
            },
            # TP-150 §1.12: register the sister predicate so the "every
            # predicate covers full domain" contract exercises BOTH twins.
            # They diverged on the non-dict cell (task_router crashed with
            # AttributeError; plan_guard returned False) — TP-149 aligned
            # them only on no-steps. The EXECUTING parity test that actually
            # calls both is tests/test_task_router.py::TestSisterPredicateParity
            # (this registry only declares keys; §5.10 — declaration != firing).
            "task_router._has_active_plan": {
                "in_progress": True,
                "complete": False,
                "blocked": False,
                "missing": False,
                "non-dict": False,
            },
        },
    ),
    StateField(
        name="blueprint gate_status",
        source_file="cc/blueprints/latest.json",
        json_key_path="gates[].status",
        domain=("pending", "running", "pass", "fail", "skipped", "unknown"),
        transitions=(
            ("pending", "running"),
            ("running", "pass"),
            ("running", "fail"),
            ("running", "skipped"),
            ("fail", "running"),    # re-run allowed after fail
            ("pass", "running"),    # re-run after pass (idempotent)
            ("unknown", "running"), # first run after default-init
        ),
        predicates={
            # gate_passed(gate_record) returns True ONLY for "pass".
            # Skipped is NOT a pass for gating purposes.
            "gate_passed": {
                "pending": False,
                "running": False,
                "pass": True,
                "fail": False,
                "skipped": False,
                "unknown": False,
            },
        },
    ),
    StateField(
        name="kill_switch active",
        source_file=".claude/settings.json",
        json_key_path="disableAllHooks",
        domain=("absent", "false", "true"),
        transitions=(
            ("absent", "true"),       # enable kill-switch
            ("true", "absent"),       # remove
            ("true", "false"),        # toggle off
            ("false", "true"),        # toggle on
            ("absent", "false"),      # explicit-false override
            ("false", "absent"),      # remove explicit-false
        ),
        predicates={
            # is_kill_switch_set(settings) returns True only when
            # disableAllHooks is the boolean True. Absent + false
            # both mean "enforcement runs."
            "is_kill_switch_set": {
                "absent": False,
                "false": False,
                "true": True,
            },
        },
    ),
    StateField(
        name="maintenance_mode flag",
        source_file="parent shell env",
        json_key_path="ESPALIER_MAINTENANCE_MODE",
        domain=("unset", "0", "1"),
        transitions=(
            ("unset", "1"),
            ("1", "unset"),
            ("unset", "0"),
            ("0", "1"),
            ("1", "0"),
        ),
        predicates={
            # _maintenance_mode_active(env): True only for "1".
            "_maintenance_mode_active": {
                "unset": False,
                "0": False,
                "1": True,
            },
        },
    ),
    # Future entries as new state fields land. The registry is
    # hand-curated; chip-up is review-visible.
)
