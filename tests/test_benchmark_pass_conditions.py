"""TP-152 B-1: the benchmark pass gate must FAIL on an empty in-scope
corpus rather than pass vacuously.

The 100%-blocked predicate is ``in_scope_blocked != in_scope_total``; with
zero in-scope entries that is ``0 != 0`` (False), so a misfiltered or empty
corpus slipped through as green. A gate with nothing to verify is RED.
This pins the zero-corpus floor and prevents that silent vacuous pass.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_update_canonical_refuses_a_shaped_root(monkeypatch, tmp_path):
    """DEF-811: the canonical scoreboard is the plain root's run, so a run
    under another root shape refuses to write it, before any baseline runs,
    and the module's shape is plain again for the next caller."""
    import bench.run_benchmark as rb

    monkeypatch.setattr(rb, "RESULTS_DIR", tmp_path / "results")
    ran: list[str] = []
    monkeypatch.setattr(rb, "run_baseline", lambda name, corpus: ran.append(name) or [])
    results_path = rb.BENCH_DIR / "RESULTS.md"
    before = results_path.read_bytes()
    assert rb.main(["--update-canonical", "--quiet", "--root-shape", "paren"]) == 1
    assert ran == [] and results_path.read_bytes() == before
    assert rb.ROOT_SHAPE == "plain"


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


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = REPO_ROOT / "tools" / "cc" / "hooks"
BENCH = REPO_ROOT / "bench"


def _refusal(monkeypatch) -> str:
    """write_guard's time-budget refusal as the hook prints it: its own
    ``deny`` over the live template at the live budget."""
    monkeypatch.syspath_prepend(str(HOOKS))
    import _denial_reasons
    import write_guard

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        write_guard.deny(_denial_reasons.WRITE_GUARD_TIME_BUDGET.format(budget=write_guard.JUDGMENT_BUDGET_S))
    return out.getvalue()


class _Answers:
    """A stand-in for a bench module's ``run_bounded``: each call answers the
    next stdout in turn with exit 0, and is counted."""

    def __init__(self, *stdouts: str):
        self.stdouts = list(stdouts)
        self.calls = 0

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess:
        self.calls += 1
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdouts.pop(0), stderr="")


class TestTheBudgetsRefusalIsNoVerdict:
    """DEF-5071: write_guard's time budget refuses a judgment that outruns
    3.5 s with a deny on the decision channel, exit 0, that judged nothing.
    The bench's reader (``bench/run_benchmark.py``, which every bench reader
    of the deny goes through) knows it by the template the hook tree words
    it with, retries it once where the refused call left no state, and
    otherwise has no verdict to give."""

    def test_the_reader_knows_the_refusal_and_only_it(self, monkeypatch, tmp_path):
        import bench.run_benchmark as rb

        refusal = _refusal(monkeypatch)
        import write_guard

        judged = io.StringIO()
        with contextlib.redirect_stdout(judged):
            write_guard.deny("Command blocked: a judged deny, whatever its reason.")
        assert rb.budget_refused(refusal, HOOKS) is True
        assert rb.budget_refused(judged.getvalue(), HOOKS) is False
        assert rb.budget_refused("", HOOKS) is False
        assert rb.budget_refused("not json", HOOKS) is False
        # A tree with no such template (one older than the budget, or a
        # stand-in hook) has no refusal to read.
        assert rb.budget_refused(refusal, tmp_path) is False

    def test_a_refusal_that_left_no_state_is_retried_once(self, monkeypatch, tmp_path, capsys):
        import bench.run_benchmark as rb

        answers = _Answers(_refusal(monkeypatch), "")
        proc = rb.judged_within_budget(lambda: answers(["write_guard.py"]), HOOKS, tmp_path)
        assert (proc.stdout, answers.calls) == ("", 2)
        assert "retrying it once" in capsys.readouterr().err

    def test_a_second_refusal_is_no_verdict(self, monkeypatch, tmp_path):
        import bench.run_benchmark as rb

        refusal = _refusal(monkeypatch)
        answers = _Answers(refusal, refusal)
        with pytest.raises(rb.BudgetMiss, match="refused the call twice"):
            rb.judged_within_budget(lambda: answers(["write_guard.py"]), HOOKS, tmp_path)
        assert answers.calls == 2

    def test_a_refusal_that_left_state_is_not_retried(self, monkeypatch, tmp_path):
        """A nudge the refused judgment fired would read the retry as its
        re-issue and answer differently."""
        import bench.run_benchmark as rb

        answers = _Answers(_refusal(monkeypatch), "")

        def spawn():
            (tmp_path / ".espalier-state").mkdir(exist_ok=True)
            (tmp_path / ".espalier-state" / "nudge").write_text("fired", encoding="utf-8")
            return answers(["write_guard.py"])

        with pytest.raises(rb.BudgetMiss, match="left state"):
            rb.judged_within_budget(spawn, HOOKS, tmp_path)
        assert answers.calls == 1

    def test_is_deny_never_scores_the_refusal(self, monkeypatch):
        import bench.run_benchmark as rb

        with pytest.raises(rb.BudgetMiss):
            rb._is_deny(_refusal(monkeypatch), 0)

    def test_the_attempt_loop_lets_the_miss_through(self, monkeypatch):
        """Its broad arm scores any other exception as not blocked, which an
        out-of-scope row reads as the allow it expects."""
        import bench.run_benchmark as rb

        def refused(attempt, project):
            raise rb.BudgetMiss("refused twice")

        monkeypatch.setattr(rb, "setup_baseline", lambda name, project: None)
        monkeypatch.setitem(rb.BASELINE_INVOKERS, "espalier", {"refused": refused})
        corpus = [{"id": "BC-T", "in_scope": False, "canonical_attempts": [
            {"attempt_id": "BC-T-a1", "verifier": "refused", "expected_outcome": "allowed"}]}]
        with pytest.raises(rb.BudgetMiss):
            rb.run_baseline("espalier", corpus)

    def test_the_run_exits_3_with_no_verdict(self, monkeypatch, tmp_path, capsys):
        import bench.run_benchmark as rb

        monkeypatch.setattr(rb, "RESULTS_DIR", tmp_path / "results")

        def run(name, corpus):
            raise rb.BudgetMiss("refused twice")

        monkeypatch.setattr(rb, "run_baseline", run)
        assert rb.main(["--quiet", "--baseline", "espalier"]) == 3
        assert "NO VERDICT" in capsys.readouterr().err
        assert list((tmp_path / "results").iterdir()) == []
        assert rb.ROOT_SHAPE == "plain"


@pytest.fixture
def load_bench():
    """Load ``bench/<name>.py`` by path under an alias (tests/CLAUDE.md). The
    tier benches import the rehearsal by its bare name after a sys.path
    insert: both are put back after the test."""
    path = list(sys.path)
    saved = sys.modules.get("powershell_guard_rehearsal")

    def load(name: str):
        spec = importlib.util.spec_from_file_location(f"_budget_reader_{name}", BENCH / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    yield load
    sys.path[:] = path
    if saved is None:
        sys.modules.pop("powershell_guard_rehearsal", None)
    else:
        sys.modules["powershell_guard_rehearsal"] = saved


#: Each bench reader of write_guard's deny, driven with a command the guard
#: allows, and what it answers for an allow.
_READERS = [
    pytest.param("guard_metamorphic", lambda m, p: m.guard_tier("ls -la", "Bash"), "ALLOW",
                 id="guard_metamorphic.guard_tier"),
    pytest.param("powershell_reachability_differential", lambda m, p: m.guard_tier("Get-Date"), "ALLOW",
                 id="powershell_reachability_differential.guard_tier"),
    pytest.param("powershell_guard_rehearsal", lambda m, p: m._tier(HOOKS / "write_guard.py", "Bash", "ls"),
                 "ALLOW", id="powershell_guard_rehearsal._tier"),
    pytest.param("reachability_differential", lambda m, p: m.guard_denies("ls", HOOKS, str(p)), False,
                 id="reachability_differential.guard_denies"),
    pytest.param("run_benchmark", lambda m, p: m.invoke_real_write_guard(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}}, p).blocked, False,
                 id="run_benchmark.invoke_real_write_guard"),
]


class TestEveryBenchReaderTellsTheBudgetFromAVerdict:
    """DEF-5071: each bench reader of write_guard's deny, its spawn answering
    the budget's refusal first. Read as a verdict, the refusal turned an
    ALLOW tier into SOFT, a guard_denies call into a deny and the release
    gate's row into a block; each reader now retries it and reads the allow,
    and a refusal that comes twice is no verdict."""

    @pytest.mark.parametrize(("name", "read", "allowed"), _READERS)
    def test_a_refusal_then_an_allow_reads_as_the_allow(
            self, load_bench, monkeypatch, tmp_path, name, read, allowed):
        module = load_bench(name)
        answers = _Answers(_refusal(monkeypatch), "")
        monkeypatch.setattr(module, "run_bounded", answers)
        assert read(module, tmp_path) == allowed
        assert answers.calls == 2

    @pytest.mark.parametrize(("name", "read", "allowed"), _READERS)
    def test_a_refusal_twice_is_no_verdict(self, load_bench, monkeypatch, tmp_path, name, read, allowed):
        module = load_bench(name)
        refusal = _refusal(monkeypatch)
        monkeypatch.setattr(module, "run_bounded", _Answers(refusal, refusal))
        with pytest.raises(RuntimeError, match="refused the call twice") as caught:
            read(module, tmp_path)
        assert type(caught.value).__name__ == "BudgetMiss"
