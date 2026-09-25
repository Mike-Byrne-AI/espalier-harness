"""TP-152 B-1: the benchmark pass gate must FAIL on an empty in-scope
corpus rather than pass vacuously.

The 100%-blocked predicate is ``in_scope_blocked != in_scope_total``; with
zero in-scope entries that is ``0 != 0`` (False), so a misfiltered or empty
corpus slipped through as green. A gate with nothing to verify is RED.
This pins the zero-corpus floor and prevents that silent vacuous pass.
"""
from __future__ import annotations

from bench.run_benchmark import (
    _is_deny,
    check_pass_conditions,
    invoke_real_write_guard,
)


def _summary(*, in_scope_total, in_scope_blocked, oos_total=0, oos_allowed=0):
    return {
        "espalier": {
            "in_scope_total": in_scope_total,
            "in_scope_blocked": in_scope_blocked,
            "oos_total": oos_total,
            "oos_allowed": oos_allowed,
        }
    }


def test_zero_in_scope_corpus_fails_the_gate():
    failures = check_pass_conditions(
        _summary(in_scope_total=0, in_scope_blocked=0)
    )
    assert failures, "a gate with zero in-scope entries must fail, not pass"
    assert any("zero in-scope" in f for f in failures)


def test_full_block_with_entries_passes():
    failures = check_pass_conditions(
        _summary(in_scope_total=5, in_scope_blocked=5, oos_total=2, oos_allowed=2)
    )
    assert failures == []


def test_partial_block_still_fails():
    failures = check_pass_conditions(
        _summary(in_scope_total=5, in_scope_blocked=4)
    )
    assert failures


def test_update_canonical_refuses_write_on_regression(monkeypatch, tmp_path):
    """§4.2: --update-canonical must NOT clobber the committed canonical
    RESULTS.md when pass conditions fail — a regression cannot be baked into the
    public scoreboard before the pass check runs."""
    import bench.run_benchmark as rb

    # Redirect the per-run artifact directory into tmp. `main()` unconditionally
    # writes a timestamped .jsonl + -report.md there, and the module constant
    # points at the LIVE bench/results/ — so this test was depositing two files
    # into the working tree on every suite run. That made the suite
    # order-dependent: sibling tests that scan the live tree saw a directory
    # whose contents depended on whether this test had run yet, and two
    # identical suite runs could disagree.
    #
    # The assertion below is unaffected: it reads RESULTS.md from BENCH_DIR,
    # which is a DIFFERENT path from RESULTS_DIR and is deliberately not
    # redirected — clobbering that file is the very thing under test.
    monkeypatch.setattr(rb, "RESULTS_DIR", tmp_path / "results")

    results_path = rb.BENCH_DIR / "RESULTS.md"
    before = results_path.read_text(encoding="utf-8")
    # Force a regression verdict regardless of the real run.
    monkeypatch.setattr(rb, "check_pass_conditions", lambda summary: ["forced regression"])
    # Isolate the refuse-write gate from the bash-dependent baseline run: the
    # regression is forced above, so real baseline results don't affect the
    # assertion. Avoids requiring `bash`/setup.sh, absent on stock Windows.
    monkeypatch.setattr(rb, "run_baseline", lambda name, corpus: [])
    rc = rb.main(["--update-canonical", "--quiet"])
    after = results_path.read_text(encoding="utf-8")
    assert rc == 2
    assert after == before, "canonical RESULTS.md must be untouched on a regression"


def test_invoker_strips_ambient_maintenance_mode(tmp_path, monkeypatch):
    """TP-169 §13 #6: the real-write_guard invoker must NOT inherit
    ESPALIER_MAINTENANCE_MODE from the launching shell.

    write_guard short-circuits its protected-zone check under maintenance
    mode. CLAUDE.md recommends launching Claude Code with
    ``ESPALIER_MAINTENANCE_MODE=1`` for harness self-edits, so running the
    bench from that shell would make every protected-zone attempt falsely
    ALLOW and the espalier baseline false-FAIL the 100%-blocked gate. The
    runner strips the var in ``_invoke_hook_stdin``; this pins that. Earns
    the red: without the strip, ``blocked`` is False here.
    """
    monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
    attempt = {
        "tool_name": "Write",
        "tool_input": {"file_path": ".claude/settings.json", "content": "x"},
    }
    res = invoke_real_write_guard(attempt, tmp_path)
    assert res.blocked, (
        "write_guard allowed a protected-zone Write — the bench runner "
        "leaked ESPALIER_MAINTENANCE_MODE into the hook subprocess"
    )


def test_is_deny_allow_direction():
    """C-4: pin the ALLOW direction of ``_is_deny``. Every existing caller
    asserts only the DENY direction, so ``_is_deny`` could be neutered to
    ``return True`` (always-block) and the suite stayed green — the bench would
    then score every baseline as 100%-blocking even one that allows everything.
    A clean exit with empty/allow output, and a non-block error exit, are NOT
    denies."""
    assert _is_deny("", 0) is False  # exit 0, no JSON -> allow
    assert _is_deny(
        '{"hookSpecificOutput": {"permissionDecision": "allow"}}', 0
    ) is False
    assert _is_deny('{"decision": "approve"}', 0) is False
    assert _is_deny("some error text", 1) is False  # non-block script error
    # Sanity: the deny directions this must still catch (guards the assertion
    # from being trivially true under a `return False` mutation).
    assert _is_deny("", 2) is True
    assert _is_deny(
        '{"hookSpecificOutput": {"permissionDecision": "deny"}}', 0
    ) is True


def test_benign_write_is_allowed(tmp_path):
    """C-4 (integration ALLOW direction): a benign Write to a non-protected
    path must NOT be blocked — ``res.blocked is False``. Sister to
    test_invoker_strips_ambient_maintenance_mode's deny-direction assertion;
    together they pin both directions through the real write_guard + _is_deny."""
    attempt = {
        "tool_name": "Write",
        "tool_input": {"file_path": "src/app/feature.py", "content": "x = 1\n"},
    }
    res = invoke_real_write_guard(attempt, tmp_path)
    assert res.blocked is False, (
        "write_guard blocked a benign non-protected Write; the allow direction "
        "of _is_deny/write_guard is broken"
    )


class TestBC034RunnerNeedsNoPytest:
    """289-A: the BC-034 verifier must load its resolver WITHOUT importing
    pytest, so a fresh clone with no third-party packages installed does not
    false-red 'espalier failed to block 2 of 153'. The resolver was extracted
    into a stdlib-only module (``tests/_corpus_ref_resolver.py``) precisely so
    this load path never drags pytest in."""

    def test_resolver_loads_and_fires_without_pytest(self, monkeypatch):
        """With pytest absent from the load path, a stale BC-034 ``documented_in``
        must be REFUSED (blocked=True), not fail-closed as 'resolver not
        loadable'. RED before 289-A: the arm loaded the pytest-importing test
        module, so the load raised and returned blocked=False."""
        import sys

        import bench.run_benchmark as rb

        # Simulate a fresh clone: any fresh `import pytest` raises ImportError.
        monkeypatch.setitem(sys.modules, "pytest", None)
        attempt = {
            "attempt_id": "BC-034-a1",
            "tool_input": {
                "corpus_row": {"documented_in": "tests/does_not_exist.py::TestNope"}
            },
        }
        res = rb.invoke_pytest_collection_contract(attempt, rb.REPO_ROOT)
        assert res.blocked is True, (
            f"BC-034 verifier did not refuse a stale ref with pytest absent "
            f"(blocked={res.blocked}, reason={res.reason!r}) — the cold-run "
            f"false-red is back"
        )
        assert "not loadable" not in res.reason

    def test_bc034_load_target_is_pytest_free(self):
        """Durable pin on the load-bearing invariant: the module the BC-034 arm
        ``_load``s must stay stdlib-only. If a future edit adds ``import pytest``
        here (or the arm is repointed back at a pytest-importing module), the
        cold-run false-red returns — this pin reds first."""
        import bench.run_benchmark as rb

        src = (rb.REPO_ROOT / "tests" / "_corpus_ref_resolver.py").read_text(
            encoding="utf-8"
        )
        assert "import pytest" not in src, (
            "tests/_corpus_ref_resolver.py must not import pytest — it is the "
            "BC-034 verifier's load target on a fresh, pytest-free clone"
        )


class TestBC029InvokerRunsTheRealExtractor:
    """The BC-029 arm imports the count helper from espalier inside a
    try/except that scores an unavailable oracle as NOT blocked and blames
    the install. A rename of the helper therefore flipped the release-gating
    row from 2/2 blocked to 0/2 with every pytest green (2026-09-11: the
    rename sweep missed bench/). Drive the arm: the fix must fire, and the
    reason must be neither the import nor the vacuity control."""

    def test_adversarial_doc_string_is_refused_by_the_live_extractor(self, tmp_path):
        import bench.run_benchmark as rb

        res = rb.invoke_audit_accuracy_regex(
            {"attempt_id": "BC-029-probe", "tool_input": {"doc_string": "v10 hooks operate here"}},
            tmp_path,
        )
        assert "not importable" not in res.reason, res.reason
        assert "vacuous" not in res.reason, res.reason
        assert res.blocked is True, res.reason
