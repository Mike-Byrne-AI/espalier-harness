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


def _refusal(monkeypatch, *, start_up_spent: bool = False) -> str:
    """write_guard's time-budget refusal as the hook prints it: its own
    ``deny`` over the live templates at the live budget, worded as judging
    spent the time, or (``start_up_spent``) as start-up did (DEF-2091): a
    child that had not begun judging, which the re-issue answers."""
    monkeypatch.syspath_prepend(str(HOOKS))
    import _denial_reasons
    import write_guard

    began = not start_up_spent
    start_up, judged = (write_guard.JUDGMENT_BUDGET_S, 0.0) if start_up_spent else (0.3, 3.2)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        write_guard.deny(write_guard._budget_reason(
            _denial_reasons, write_guard.JUDGMENT_BUDGET_S, write_guard._CHILD_BOUND, began, start_up, judged))
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
        # Its start-up twin is the same miss, never a scored block (DEF-2091).
        twin = _refusal(monkeypatch, start_up_spent=True)
        assert "re-issue the same command once" in twin, twin
        assert rb.budget_refused(twin, HOOKS) is True
        assert rb.budget_refused(judged.getvalue(), HOOKS) is False
        assert rb.budget_refused("", HOOKS) is False
        assert rb.budget_refused("not json", HOOKS) is False
        # A tree with no such template (one older than the budget, or a
        # stand-in hook) has no refusal to read.
        assert rb.budget_refused(refusal, tmp_path) is False

    def test_the_reader_knows_the_parents_fallback_refusal(self, monkeypatch, tmp_path):
        """DEF-2058: where the parent cannot import ``_denial_reasons`` at its
        deadline it refuses in plain words that never hold the template's, so
        a reader of the template alone scored that refusal as a block. The
        reason is rendered from the live hook's own fallback binding at the
        live deadline, and tied to the phrase the test-side readers know it
        by (``tests/_hook_spawn.py::BUDGET_FALLBACK``)."""
        import ast
        import json

        import bench.run_benchmark as rb
        from tests import _hook_spawn as hs

        monkeypatch.syspath_prepend(str(HOOKS))
        import write_guard

        owner = next(n for n in ast.parse((HOOKS / "write_guard.py").read_text(encoding="utf-8")).body
                     if isinstance(n, ast.FunctionDef) and n.name == "_answer_from_a_judging_child")
        bound = [n.value for t in ast.walk(owner) if isinstance(t, ast.Try) for h in t.handlers
                 for s in h.body for n in ast.walk(s) if isinstance(n, ast.Assign)
                 and any(isinstance(x, ast.Name) and x.id == "reason" for x in n.targets)]
        assert len(bound) == 1, bound
        # The binding reads what spent the time (DEF-2091): rendered here for a
        # child still starting up, the shape a loaded box gave.
        reason = eval(compile(ast.Expression(bound[0]), "write_guard.py", "eval"),
                      {**vars(write_guard), "began": False, "start_up": write_guard.HARD_DEADLINE_S, "judged": 0.0})
        assert hs.BUDGET_FALLBACK in reason and hs.BUDGET_REFUSAL not in reason, reason

        def decision(text: str) -> str:
            return json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": text}}) + "\n"

        assert rb.budget_refused(decision(reason), HOOKS) is True
        # The fallback in full, never a judged deny that only quotes its phrase.
        assert rb.budget_refused(decision(f"Command blocked: a judged deny ({hs.BUDGET_FALLBACK})."), HOOKS) is False
        assert rb.budget_refused(decision(f"Dangerous command blocked, quoting: {reason}"), HOOKS) is False
        # A tree whose write_guard holds no fallback (one older than it, or a
        # stand-in hook) has none to read.
        (tmp_path / "write_guard.py").write_text("def deny(reason):\n    pass\n", encoding="utf-8")
        assert rb.budget_refused(decision(reason), tmp_path) is False

    @pytest.mark.parametrize("binding", [
        'reason: str = f"Stand-in ran out of its {BUDGET} s budget, refused."',
        'reason = "Stand-in ran out of its 9 s budget, refused."',
    ], ids=["annotated-fstring", "literal"])
    def test_the_fallback_is_read_from_the_trees_own_source(self, tmp_path, binding):
        """The reader reads a tree's own wording, in either binding form, and
        no other tree's."""
        import json

        import bench.run_benchmark as rb

        (tmp_path / "write_guard.py").write_text(
            "def _answer_from_a_judging_child():\n    try:\n        import _denial_reasons\n"
            f"    except Exception:\n        {binding}\n", encoding="utf-8")

        def decision(text: str) -> str:
            return json.dumps({"hookSpecificOutput": {"permissionDecision": "deny",
                                                      "permissionDecisionReason": text}})

        assert rb.budget_refused(decision("Stand-in ran out of its 9 s budget, refused."), tmp_path) is True
        assert rb.budget_refused(decision("Stand-in ran out of its 9 s budget."), tmp_path) is False

    def test_a_fallback_bound_in_an_unreadable_form_is_no_verdict(self, tmp_path):
        """A binding the reader cannot render refuses, never scores the
        fallback as a block again."""
        import bench.run_benchmark as rb

        (tmp_path / "write_guard.py").write_text(
            "def _answer_from_a_judging_child():\n    try:\n        import _denial_reasons\n"
            "    except Exception:\n        reason = _plain_words()\n", encoding="utf-8")
        with pytest.raises(rb.BudgetMiss, match="cannot read"):
            rb.budget_refused('{"hookSpecificOutput": {}}', tmp_path)

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


def _decision(reason: str) -> str:
    """A deny on the decision channel, as a PreToolUse hook prints it."""
    import json

    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}) + "\n"


def _crash_reasons(monkeypatch) -> dict[str, str]:
    """Every deny write_guard gives a call it never judged because it failed
    itself (DEF-2096), rendered from the hook sources, each field filled:
    every ``_denial_reasons`` template that says write_guard's internal error
    and each one its crash guard (``_judge``'s handlers) and its runner's
    refusal (``_runner_fault_reason``) read, that refusal's two plain-words
    forms, write_guard's own last resort where ``_start_refusal`` cannot
    import, every ``_start_refusal`` template but the two named as no deny,
    and the plain-words last resorts it composes where a template could not
    be (the start refusal's and the floor's). Derived by name and by words,
    not by the readers' heads, so a new template in these places joins
    without an edit here; a crash text written anywhere else does not."""
    import ast
    import collections
    import types

    monkeypatch.syspath_prepend(str(HOOKS))
    import _denial_reasons
    import _start_refusal
    import write_guard

    fields = collections.defaultdict(lambda: "x", hook="write_guard", error="TypeError",
                                     file="tools/cc/hooks/_bash_patterns.py", line="4560")
    # Every reasons template that says write_guard's internal error, by its
    # words, wherever write_guard reads it, beside those its two refusers read.
    reasons: dict[str, str] = {
        name: value.format_map(fields) for name, value in vars(_denial_reasons).items()
        if isinstance(value, str) and "write_guard internal error" in value}
    tree = ast.parse((HOOKS / "write_guard.py").read_text(encoding="utf-8"))
    # Its own last resort where _start_refusal cannot import, composed in
    # plain words at module level.
    last = [n.value for t in tree.body if isinstance(t, ast.Try) for h in t.handlers for n in ast.walk(h)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.BinOp) and any(
                isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant)
                and x.slice.value == "permissionDecisionReason" for x in n.targets)]
    assert len(last) == 1, [ast.unparse(n) for n in last]
    reasons["write_guard-last-resort"] = eval(compile(ast.Expression(last[0]), "write_guard.py", "eval"), {
        "_cause": "tools/cc/hooks/_start_refusal.py raised ImportError", "_LAST_RESTORE": "git restore x"})
    owners = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name in ("_judge", "_runner_fault_reason")}
    assert set(owners) == {"_judge", "_runner_fault_reason"}, sorted(owners)
    scopes = [h for t in ast.walk(owners["_judge"]) if isinstance(t, ast.Try) for h in t.handlers]
    scopes.append(owners["_runner_fault_reason"])
    for scope in scopes:
        for node in ast.walk(scope):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "_denial_reasons"
                    and isinstance(getattr(_denial_reasons, node.attr, None), str)):
                reasons[node.attr] = getattr(_denial_reasons, node.attr).format_map(fields)
    monkeypatch.setattr(write_guard, "_HOOK_STARTED", -1e12)  # past the deadline: the plain words
    named = ({"error": "OSError", "file": "tools/cc/hooks/write_guard.py", "line": 1,
              "restore": "git restore tools/cc/hooks/write_guard.py"}, {})
    for label, fault in (("runner-unplaced", None), ("runner-placed", named)):
        reasons[label] = write_guard._runner_fault_reason(types.SimpleNamespace(reasons=None), fault)
    # Every start-refusal template but the two that are no deny, left out by
    # name: a new refusal joins whatever its words, and reds a reader that
    # does not know them.
    not_a_deny = {"WEDGE_RESTORE_CONTEXT": "the context of the one restore a wedged hook lets through",
                  "BELOW_FLOOR_BANNER": "the SessionStart banner's line"}
    assert set(not_a_deny) <= set(_start_refusal._OPERATOR_FACING_TEMPLATES), not_a_deny
    for name in _start_refusal._OPERATOR_FACING_TEMPLATES:
        if name not in not_a_deny:
            reasons[name] = getattr(_start_refusal, name).format_map(fields)
    source = ast.parse(Path(_start_refusal.__file__).read_text(encoding="utf-8"))
    composed = [n.value for t in ast.walk(source) if isinstance(t, ast.Try) for h in t.handlers
                for s in h.body for n in ast.walk(s) if isinstance(n, ast.Assign) and isinstance(n.value, ast.BinOp)
                and any(isinstance(x, ast.Name) and x.id == "reason" for x in n.targets)]
    # The start refusal's and the floor's last resorts, each composed in plain
    # words where its template could not be.
    assert len(composed) >= 2, [ast.unparse(c) for c in composed]
    for node in composed:
        for body in (False, True):
            reasons[f"composed-line-{node.lineno}-body={body}"] = eval(
                compile(ast.Expression(node), "_start_refusal.py", "eval"),
                {"hook": "write_guard", "body": body, "exc": TypeError("x"), "_FLOOR": _start_refusal._FLOOR})
    # The derivation never shrinks under the members it was written against.
    assert {"WRITE_GUARD_INTERNAL_ERROR", "WRITE_GUARD_CRASHED_AT", "WRITE_GUARD_CRASHED_ON_A_KEPT_FILE",
            "WRITE_GUARD_RUNNER_FAULT", "HELPER_SKEW", "SIBLING_RAISED", "SIBLING_RAISED_UNPLACED",
            "BODY_RAISED", "BODY_RAISED_UNPLACED", "BELOW_FLOOR", "write_guard-last-resort"} <= set(reasons), (
        sorted(reasons))
    return reasons


def _census_module():
    spec = importlib.util.spec_from_file_location("_crash_reader_guard_cost_census",
                                                  REPO_ROOT / "scripts" / "guard_cost_census.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A crash as write_guard's crash guard words it (``WRITE_GUARD_CRASHED_AT``).
_A_CRASH = ("write_guard internal error (TypeError at tools/cc/hooks/_bash_patterns.py:4560); failing closed."
            " Re-issue once.")
#: A fault in the parent's runner of its judging child (``WRITE_GUARD_RUNNER_FAULT``).
_A_RUNNER_FAULT = ("write_guard internal error (OSError at tools/cc/hooks/write_guard.py:500) while it ran its"
                   " judging child; failing closed. Re-issue once.")
#: A refusal to start (``_start_refusal.SIBLING_RAISED``).
_A_START_REFUSAL = ("write_guard cannot start: tools/cc/hooks/_integrity.py raised ImportError at line 3 while"
                    " the hook imported its siblings.")


class TestACrashIsNoVerdict:
    """DEF-2096: a deny write_guard gives a call it never judged because it
    failed itself -- its crash guard's, its runner's, or its refusal to start
    -- read as a judged block in every reader that knew the budget's refusal
    alone, so a guard that crashed on a bypass row passed it, and the release
    gate was green on a guard that judged nothing. Each reader now reads it as
    no verdict, as it reads the budget's refusal, unless its caller expects
    the crash: the one corpus row whose expected outcome it is (BC-023-a6)
    and the suite's rows that drive a wedged guard."""

    def test_every_reader_reads_every_crash_as_no_verdict(self, monkeypatch):
        import bench.run_benchmark as rb
        from tests import _hook_spawn as hs

        from espalier import selfcheck

        census = _census_module()
        for name, reason in _crash_reasons(monkeypatch).items():
            out = _decision(reason)
            assert (rb.budget_refused(out, HOOKS), hs.holds_a_budget_refusal(out),
                    census.decision("bash", 0, out), selfcheck._crash_head(out) is not None) == (
                True, True, "deny (crash)", True), (name, reason)

    def test_a_caller_that_expects_the_crash_reads_it_as_its_verdict(self, monkeypatch):
        import bench.run_benchmark as rb
        from tests import _hook_spawn as hs

        for name, reason in _crash_reasons(monkeypatch).items():
            out = _decision(reason)
            assert (rb.budget_refused(out, HOOKS, crash_expected=True),
                    hs.holds_a_budget_refusal(out, crash_expected=True)) == (False, False), name
            # A row's own expected crash is that crash alone (the code review):
            # the umbrella's words expect its internal error, never a refusal
            # to start, which judged nothing of the row either.
            umbrella = rb.budget_refused(out, HOOKS, crash_expected="write_guard internal error")
            assert umbrella is (not reason.startswith("write_guard internal error")), name
        # The budget's refusal is no verdict to it still.
        refusal = _refusal(monkeypatch)
        assert rb.budget_refused(refusal, HOOKS, crash_expected=True) is True
        assert hs.holds_a_budget_refusal(refusal, crash_expected=True) is True

    @pytest.mark.parametrize("reason", [
        f"Dangerous command blocked, quoting: {_A_CRASH}",
        "Command blocked: a protected zone (the hook said: write_guard cannot start: x).",
        "Command blocked: a protected zone.",
    ], ids=["quotes-the-crash", "quotes-the-start-refusal", "plain"])
    def test_a_judged_deny_stays_a_verdict(self, reason):
        """The crash's words read at the reason's start only, so a judged deny
        that quotes them is the block it is."""
        import bench.run_benchmark as rb
        from tests import _hook_spawn as hs

        out = _decision(reason)
        assert (rb.budget_refused(out, HOOKS), hs.holds_a_budget_refusal(out),
                _census_module().decision("bash", 0, out)) == (False, False, "deny")

    def test_a_runner_fault_then_an_answer_reads_as_the_answer(self, tmp_path, capsys):
        """A fault in the runner of the judging child can pass a second call,
        so it is retried as the budget's refusal is."""
        import bench.run_benchmark as rb

        answers = _Answers(_decision(_A_RUNNER_FAULT), "")
        proc = rb.judged_within_budget(lambda: answers(["write_guard.py"]), HOOKS, tmp_path)
        assert (proc.stdout, answers.calls) == ("", 2)
        assert "crashed" in capsys.readouterr().err

    def test_two_runner_faults_are_no_verdict(self, tmp_path):
        import bench.run_benchmark as rb

        fault = _decision(_A_RUNNER_FAULT)
        answers = _Answers(fault, fault)
        with pytest.raises(rb.BudgetMiss, match="crashed on the call twice"):
            rb.judged_within_budget(lambda: answers(["write_guard.py"]), HOOKS, tmp_path)
        assert answers.calls == 2

    @pytest.mark.parametrize("crash", [_A_CRASH, _A_START_REFUSAL], ids=["crash-guard", "start-refusal"])
    def test_a_crash_in_the_judgment_is_no_verdict_at_once(self, tmp_path, crash):
        """Any other crash comes back: a retry would hide one that fires on
        some calls behind the second answer (the failure-mode review)."""
        import bench.run_benchmark as rb

        answers = _Answers(_decision(crash), "")
        with pytest.raises(rb.BudgetMiss, match="it is not retried"):
            rb.judged_within_budget(lambda: answers(["write_guard.py"]), HOOKS, tmp_path)
        assert answers.calls == 1

    def test_an_expected_crash_is_the_answer_at_once(self, tmp_path):
        import bench.run_benchmark as rb

        answers = _Answers(_decision(_A_CRASH))
        proc = rb.judged_within_budget(lambda: answers(["write_guard.py"]), HOOKS, tmp_path, crash_expected=True)
        assert (proc.stdout, answers.calls) == (_decision(_A_CRASH), 1)

    @pytest.mark.parametrize(("name", "read", "allowed"), _READERS)
    def test_a_crash_is_no_verdict_to_every_bench_reader(
            self, load_bench, monkeypatch, tmp_path, name, read, allowed):
        module = load_bench(name)
        crash = _decision(_A_CRASH)
        monkeypatch.setattr(module, "run_bounded", _Answers(crash, crash))
        with pytest.raises(RuntimeError, match="crashed on the call") as caught:
            read(module, tmp_path)
        assert type(caught.value).__name__ == "BudgetMiss"
        assert "TypeError at tools/cc/hooks/_bash_patterns.py:4560" in str(caught.value)

    def test_a_spawn_that_skipped_the_reader_never_scores_a_crash(self):
        import bench.run_benchmark as rb

        with pytest.raises(rb.BudgetMiss, match="crashed"):
            rb._is_deny(_decision(_A_CRASH), 0)
        assert rb._is_deny(_decision(_A_CRASH), 0, crash_expected=True) is True

    def test_the_one_corpus_row_that_expects_the_crash_is_bc_023_a6(self):
        """Its expected block is the crash guard's own (the umbrella's
        class); a crash on any other row is no verdict."""
        import bench.run_benchmark as rb

        expecting = {a["attempt_id"]: rb.expected_crash(a) for entry in rb.load_corpus()
                     for a in entry["canonical_attempts"] if rb.expected_crash(a)}
        assert expecting == {"BC-023-a6": "write_guard internal error"}

    def test_the_release_bench_scores_the_expected_crash_and_no_other(self, monkeypatch, tmp_path):
        import bench.run_benchmark as rb

        rows = {a["attempt_id"]: a for entry in rb.load_corpus() for a in entry["canonical_attempts"]}
        crash = _decision(_A_CRASH)
        monkeypatch.setattr(rb, "run_bounded", _Answers(crash))
        scored = rb.invoke_real_write_guard(rows["BC-023-a6"], tmp_path)
        assert (scored.blocked, scored.reason) == (True, _A_CRASH)
        monkeypatch.setattr(rb, "run_bounded", _Answers(crash))
        with pytest.raises(rb.BudgetMiss, match="crashed on the call"):
            rb.invoke_real_write_guard(rows["BC-023-a1"], tmp_path)
        # The umbrella's row expects its internal error: a guard that cannot
        # start never judged it either (the code review).
        monkeypatch.setattr(rb, "run_bounded", _Answers(_decision(_A_START_REFUSAL)))
        with pytest.raises(rb.BudgetMiss, match="cannot start"):
            rb.invoke_real_write_guard(rows["BC-023-a6"], tmp_path)

    def test_the_kill_switch_invoker_reads_a_crash_as_no_verdict(self, monkeypatch, tmp_path):
        """Its own spawn passes the row's expectation as the plain one does
        (the code review: no row drove it)."""
        import bench.run_benchmark as rb

        attempt = next(a for entry in rb.load_corpus() for a in entry["canonical_attempts"]
                       if a["verifier"] == "killswitch_under_maintenance")
        monkeypatch.setattr(rb, "run_bounded", _Answers(_decision(_A_CRASH)))
        with pytest.raises(rb.BudgetMiss, match="crashed on the call"):
            rb.invoke_killswitch_under_maintenance(attempt, tmp_path)
        assert not (tmp_path / ".claude" / "settings.json").exists()

    def test_the_attempt_loop_names_the_row_it_has_no_verdict_for(self, monkeypatch):
        import bench.run_benchmark as rb

        def crashed(attempt, project):
            raise rb.BudgetMiss("write_guard crashed on the call twice")

        monkeypatch.setattr(rb, "setup_baseline", lambda name, project: None)
        monkeypatch.setitem(rb.BASELINE_INVOKERS, "espalier", {"crashed": crashed})
        corpus = [{"id": "BC-T", "in_scope": True, "canonical_attempts": [
            {"attempt_id": "BC-T-a1", "verifier": "crashed", "expected_outcome": "blocked"}]}]
        with pytest.raises(rb.BudgetMiss, match=r"^BC-T-a1: write_guard crashed"):
            rb.run_baseline("espalier", corpus)


def _raising(exc: BaseException):
    def raise_it(*args, **kwargs):
        raise exc
    return raise_it


#: Each differential's main, its first judgment refused twice. Exit 1 is a
#: fail-open in reachability_differential and a violation in guard_metamorphic.
_MAINS = [
    pytest.param("guard_metamorphic", lambda m, mp: mp.setattr(
        m, "assert_instrument_is_live", _raising(m.BudgetMiss("refused the call twice"))),
                 id="guard_metamorphic.main"),
    pytest.param("powershell_reachability_differential", lambda m, mp: (
        mp.setattr(m, "find_powershell", lambda: ("pwsh", "core")),
        mp.setattr(m, "assert_instrument_is_live", _raising(m.BudgetMiss("refused the call twice")))),
                 id="powershell_reachability_differential.main"),
    pytest.param("reachability_differential", lambda m, mp: mp.setattr(
        m, "_differential", _raising(m._rehearsal().BudgetMiss("refused the call twice"))),
                 id="reachability_differential.main"),
]


@pytest.mark.parametrize(("name", "refuse"), _MAINS)
def test_a_differential_exits_3_with_no_verdict(load_bench, monkeypatch, capsys, name, refuse):
    """DEF-5071: a miss ends a differential with exit 3, as a broken
    instrument does, never with a tree verdict or a traceback's exit 1."""
    module = load_bench(name)
    refuse(module, monkeypatch)
    assert module.main([]) == 3
    assert "NO VERDICT" in capsys.readouterr().err
