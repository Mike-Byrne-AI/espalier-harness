"""TP-150-B: bench corpus<->runner wiring parity contract.

The §1.11 "gate credibility" inverse-polarity instance (FAILURE_MODES.md
§1.11 corpus scope-metadata drift): a corpus class can enter the in-scope
set carrying ``expected_outcome=blocked`` faster than the runner learns to
*wire* a verifier for it. When that happens the verifier name silently
falls through ``BASELINE_INVOKERS["espalier"].get(name, invoke_always_allow)``
(bench/run_benchmark.py) to ``invoke_always_allow`` — the attempt is reported
as NOT blocked, the all-in-scope-blocked gate goes permanently RED, and
because the corpus is also the public scoreboard the contradiction reads as
"the harness is broken" rather than "the corpus out-ran the wiring." Pre-TP-150
43 in-scope attempts (11 distinct verifier names) were unwired exactly this way.

This contract is an INDEPENDENT witness (no shared code with the runner): it
parses the ``BASELINE_INVOKERS["espalier"]`` dict out of run_benchmark.py *as
AST text* and asserts every in-scope attempt whose ``expected_outcome`` is
``blocked`` resolves to a verifier that is BOTH a key in that dict AND mapped to
a real invoker (not ``invoke_always_allow``). It does NOT import or run the
producer, so a producer bug can't mask the drift.

Earn-the-red: ``test_earn_the_red_pre_fix_wiring_fails`` reconstructs the
pre-TP-150 7-key espalier wiring and asserts the parity check FIRES on it —
proving the check discriminates (FAILURE_MODES.md §5.10 presence-vs-firing).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "bench" / "run_benchmark.py"
CORPUS_DIR = REPO_ROOT / "bench" / "corpus"

ALWAYS_ALLOW = "invoke_always_allow"


def _espalier_wiring() -> dict[str, str]:
    """Parse ``BASELINE_INVOKERS["espalier"]`` from run_benchmark.py source.

    Returns {verifier_name: invoker_function_name}. AST-based (not import)
    so the test is a text witness independent of the runner's runtime.
    """
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # `BASELINE_INVOKERS: dict[...] = {...}` is an annotated assignment.
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "BASELINE_INVOKERS" for t in targets):
            continue
        assert isinstance(node.value, ast.Dict), "BASELINE_INVOKERS is not a dict literal"
        for key, val in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "espalier":
                assert isinstance(val, ast.Dict), "espalier baseline is not a dict literal"
                wiring: dict[str, str] = {}
                for vk, vv in zip(val.keys, val.values):
                    assert isinstance(vk, ast.Constant) and isinstance(vk.value, str)
                    assert isinstance(vv, ast.Name), (
                        f"espalier['{vk.value}'] is not a bare invoker name"
                    )
                    wiring[vk.value] = vv.id
                return wiring
    raise AssertionError("could not locate BASELINE_INVOKERS['espalier'] in run_benchmark.py")


def _in_scope_blocked_verifiers() -> set[str]:
    """Every verifier name used by an in-scope attempt expecting 'blocked'."""
    names: set[str] = set()
    for path in sorted(CORPUS_DIR.glob("BC-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("in_scope", True):
            continue
        for attempt in data.get("canonical_attempts", []):
            if attempt.get("expected_outcome") == "blocked":
                names.add(attempt["verifier"])
    return names


def _parity_violations(wiring: dict[str, str], verifiers: set[str]) -> list[str]:
    """Verifier names that are unwired or wired to invoke_always_allow."""
    return sorted(
        name for name in verifiers
        if wiring.get(name, ALWAYS_ALLOW) == ALWAYS_ALLOW
    )


def test_every_in_scope_blocked_verifier_is_faithfully_wired():
    """Live contract: no in-scope expected-blocked verifier silently
    falls through to invoke_always_allow."""
    wiring = _espalier_wiring()
    verifiers = _in_scope_blocked_verifiers()
    assert verifiers, "no in-scope blocked verifiers found — corpus glob broke"
    violations = _parity_violations(wiring, verifiers)
    assert not violations, (
        "in-scope expected_outcome=blocked verifiers not wired in the espalier "
        f"baseline (silently fall through to {ALWAYS_ALLOW}): {violations}. "
        "Either wire a faithful invoker in BASELINE_INVOKERS['espalier'] or "
        "rescope the corpus class to BC-OOS-* (in_scope:false, "
        "expected_outcome:allowed). See FAILURE_MODES.md §1.11 corpus "
        "scope-metadata drift."
    )


def test_earn_the_red_pre_fix_wiring_fails():
    """The pre-TP-150 espalier wiring had 7 verifier keys; the corpus
    carried 11 more in-scope expected-blocked names. The parity check MUST
    fire on that historical wiring — proving it discriminates, not merely
    that the verifier names exist (FAILURE_MODES.md §5.10)."""
    pre_fix = {
        "bash_hook": "invoke_real_write_guard",
        "path_hook": "invoke_real_write_guard",
        "kill_switch_scan": "invoke_real_integrity_verify",
        "marker_recognition": "invoke_marker_recognition",
        "deploy_iteration_invariant": "invoke_deploy_iteration_invariant",
        "statusline_read": "invoke_statusline_read",
        "freshness_design_check": "invoke_freshness_design_check",
    }
    verifiers = _in_scope_blocked_verifiers()
    violations = _parity_violations(pre_fix, verifiers)
    assert violations, (
        "pre-fix 7-key wiring should have left in-scope verifiers unwired; "
        "the parity check did not fire — it cannot discriminate."
    )
    # The headline alias-drift name must be among the caught violations.
    assert "write_guard_pretooluse" in violations


def _all_corpus_verifiers() -> set[str]:
    """Every verifier name used by ANY corpus attempt (in-scope + OOS)."""
    names: set[str] = set()
    for path in sorted(CORPUS_DIR.glob("BC-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for attempt in data.get("canonical_attempts", []):
            names.add(attempt["verifier"])
    return names


def test_every_corpus_verifier_is_an_explicit_espalier_key():
    """TP-171 §4.2: every verifier the corpus uses — in-scope OR OOS — must be
    an EXPLICIT key in BASELINE_INVOKERS['espalier']. Pre-fix, an OOS verifier
    name absent from the dict (BC-OOS-008's ``verify_integrity``) silently
    routed to invoke_always_allow at runtime, reporting the attempt as
    "exercised" while the real defense was never invoked. The runner now RAISES
    on a missing espalier verifier; this test pins the source-side invariant so
    the failure surfaces in CI, not only at run time. A non-runner-exercisable
    OOS class is wired to invoke_always_allow WITH a receipt comment — this test
    only requires the key to be present."""
    wiring = _espalier_wiring()
    missing = sorted(v for v in _all_corpus_verifiers() if v not in wiring)
    assert not missing, (
        "corpus verifiers absent from BASELINE_INVOKERS['espalier'] — they "
        f"silently fall through to {ALWAYS_ALLOW} at runtime: {missing}. Wire "
        "each explicitly (invoke_always_allow + a receipt for an OOS class)."
    )
