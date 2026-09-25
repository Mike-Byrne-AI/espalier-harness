"""Regression tests for tools/cc/hooks/task_router.py.

The hook injects [HARNESS] Multi-step routing guidance into UserPromptSubmit
context when the prompt looks multi-step. Two failure modes pinned here:

1. Routing guidance fired mid-flow when an execution plan was already
   active — pure noise; user is already in a tracked workflow.
2. Pure correctness: it must still fire when no plan is active and the
   prompt matches a multi-step keyword.

The hook runs as a subprocess in production. These tests exercise the
real CLI surface via subprocess to match that contract.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "cc" / "hooks" / "task_router.py"


def _run(prompt: str, cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the hook with the given prompt; return the CompletedProcess."""
    payload = json.dumps({"prompt": prompt})
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(cwd),
        check=False, encoding="utf-8",
    )


def _write_plan(cwd: Path, status: str) -> None:
    """Stand up a minimal execution_plan.json at the canonical path."""
    plan_dir = cwd / "cc"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "execution_plan.json").write_text(
        json.dumps({
            "task": "test",
            "status": status,
            "steps": [{"index": 0, "status": "pending", "description": "x"}],
        }),
        encoding="utf-8",
    )


class TestRoutingFiresWithoutActivePlan:
    """Without an active plan, multi-step prompts get the routing hint
    (existing behavior preserved)."""

    def test_multi_step_keyword_fires_routing(self, tmp_path):
        result = _run("lets implement a new feature with three steps", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Multi-step task detected" in result.stdout

    def test_quick_fix_question_does_not_fire(self, tmp_path):
        result = _run("how does the integrity check work?", tmp_path)
        assert result.returncode == 0
        assert result.stdout == ""


class TestActivePlanSuppressesRouting:
    """When an execution plan is active, the routing hint is suppressed
    regardless of prompt content — the user is already mid-flow.

    Pre-fix, every UserPromptSubmit during a tracked /implement-task --multi
    session triggered the hint, producing noise on every prompt.
    """

    def test_in_progress_plan_suppresses_routing(self, tmp_path):
        _write_plan(tmp_path, status="in_progress")
        result = _run("lets create a new module to handle X", tmp_path)
        assert result.returncode == 0
        assert result.stdout == "", (
            f"routing guidance should be suppressed mid-flow; got: "
            f"{result.stdout!r}"
        )

    def test_blocked_plan_does_not_suppress_routing(self, tmp_path):
        """TP-142 FM-1 close: ``blocked`` is NOT active — the operator
        is stuck and routing guidance is *more* useful, not less. The
        predicate must only treat ``status == "in_progress"`` as open
        (sister-site of plan_guard's TP-33 fix).
        """
        _write_plan(tmp_path, status="blocked")
        result = _run("lets refactor the whole thing", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Multi-step task detected" in result.stdout

    def test_complete_plan_does_not_suppress_routing(self, tmp_path):
        """Complete plans should NOT suppress — a new multi-step task
        deserves fresh routing guidance."""
        _write_plan(tmp_path, status="complete")
        result = _run("lets build a new caching layer", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Multi-step task detected" in result.stdout

    def test_malformed_plan_does_not_suppress(self, tmp_path):
        """A torn-write or corrupt plan file should NOT be treated as
        active — better to fire the hint than swallow it silently."""
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "execution_plan.json").write_text(
            "not valid json{", encoding="utf-8"
        )
        result = _run("lets implement a parser for X", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Multi-step task detected" in result.stdout

    def test_missing_plan_file_does_not_suppress(self, tmp_path):
        """No plan file at all → fire normally."""
        result = _run("lets implement a parser", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Multi-step task detected" in result.stdout


class TestHasActivePlanStateSpace:
    """Pin _has_active_plan across the full execution_plan.json state space.

    Sister-site contract of plan_guard's TestPlanStateLabel (TP-33). Both
    predicates must agree on what "open" means — happy-path tests on
    ``in_progress`` alone do not catch silent acceptance of closed or
    stuck states. The parametrization is the gate: every new status
    value execution_plan.py learns to emit must be classified here.
    """

    @staticmethod
    def _import_task_router():
        import importlib
        import sys
        hook_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hook_dir))
        try:
            if "task_router" in sys.modules:
                return importlib.reload(sys.modules["task_router"])
            return importlib.import_module("task_router")
        finally:
            sys.path.remove(str(hook_dir))

    @pytest.fixture
    def plan_root(self, tmp_path, monkeypatch):
        (tmp_path / "cc").mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        return tmp_path

    @pytest.mark.parametrize(
        "status,expected",
        [
            ("in_progress", True),          # only OPEN state
            ("complete", False),            # TP-33 motivating case
            ("blocked", False),             # FM-1: was True pre-TP-142
            ("running", False),             # FM-1: dead vocab, was True pre-TP-142
            ("cancelled", False),
            ("planned", False),
            ("", False),
            ("unknown_future_status", False),
        ],
    )
    def test_only_in_progress_is_active(self, plan_root, status, expected):
        plan_file = plan_root / "cc" / "execution_plan.json"
        plan_file.write_text(
            json.dumps({"status": status, "steps": [{"index": 0}]}),
            encoding="utf-8",
        )
        task_router = self._import_task_router()
        assert task_router._has_active_plan() is expected

    def test_missing_file_is_inactive(self, plan_root):
        task_router = self._import_task_router()
        assert task_router._has_active_plan() is False

    def test_malformed_json_is_inactive(self, plan_root):
        (plan_root / "cc" / "execution_plan.json").write_text(
            "not json {", encoding="utf-8"
        )
        task_router = self._import_task_router()
        assert task_router._has_active_plan() is False

    def test_non_dict_json_is_inactive(self, plan_root):
        """TP-150 §1.12: a valid-JSON-but-non-dict plan (a top-level list,
        e.g. ``[{"status": "in_progress", "steps": [1]}]``) must classify as
        inactive, not crash. Pre-fix, ``data.get(...)`` raised
        ``AttributeError`` — exit 1 from this UserPromptSubmit advisory hook,
        spewing a traceback on every prompt (a sister-miss TP-149 left in
        place; plan_guard's twin already handled it via _plan_state_label)."""
        (plan_root / "cc" / "execution_plan.json").write_text(
            json.dumps([{"status": "in_progress", "steps": [1]}]),
            encoding="utf-8",
        )
        task_router = self._import_task_router()
        assert task_router._has_active_plan() is False


class TestSisterPredicateParity:
    """TP-150 §1.12 sister-predicate domain blindness: ``task_router._has_active_plan``
    and ``plan_guard._has_active_plan`` are declared to agree, but TP-149 aligned
    them only on the no-steps cell — the non-dict/malformed-parse cell was never
    enumerated, and the twins diverged there (task_router crashed; plan_guard
    returned False).

    This test EXECUTES BOTH predicates against the SAME plan file across the full
    domain, including the non-dict cell. The truth-table registry in
    tests/_state_machines.py only DECLARES keys (it never calls a predicate) —
    per §5.10, a declaration is not a firing, so this executing parity test is
    the real backstop the registry edit alone cannot be.
    """

    @staticmethod
    def _import_both():
        import importlib
        import sys
        hook_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hook_dir))
        try:
            mods = {}
            for name in ("task_router", "plan_guard"):
                mods[name] = (
                    importlib.reload(sys.modules[name])
                    if name in sys.modules
                    else importlib.import_module(name)
                )
            return mods["task_router"], mods["plan_guard"]
        finally:
            sys.path.remove(str(hook_dir))

    @pytest.fixture
    def plan_root(self, tmp_path, monkeypatch):
        (tmp_path / "cc").mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        return tmp_path

    @pytest.mark.parametrize(
        "label,content,expected",
        [
            ("in_progress", json.dumps({"status": "in_progress", "steps": [{"index": 0}]}), True),
            ("complete", json.dumps({"status": "complete", "steps": [{"index": 0}]}), False),
            ("blocked", json.dumps({"status": "blocked", "steps": [{"index": 0}]}), False),
            ("no-steps", json.dumps({"status": "in_progress", "steps": []}), False),
            ("missing", None, False),
            ("malformed", "not json {", False),
            ("non-dict", json.dumps([{"status": "in_progress", "steps": [1]}]), False),
        ],
    )
    def test_twins_agree_across_full_domain(self, plan_root, label, content, expected):
        if content is not None:
            (plan_root / "cc" / "execution_plan.json").write_text(
                content, encoding="utf-8"
            )
        task_router, plan_guard = self._import_both()
        # task_router._has_active_plan() resolves root via CLAUDE_PROJECT_DIR;
        # plan_guard._has_active_plan(root) takes the root explicitly.
        tr = task_router._has_active_plan()
        pg = plan_guard._has_active_plan(plan_root)
        assert tr is expected, f"task_router disagreed on {label!r}: got {tr!r}"
        assert pg is expected, f"plan_guard disagreed on {label!r}: got {pg!r}"
        assert tr == pg, f"sister predicates diverged on {label!r}: tr={tr} pg={pg}"


class TestClassifyWordBoundary:
    """TP-189-B FRICTION-4: ``_classify`` matched MULTI_STEP_KEYWORDS as bare
    substrings, so ``rebuild the index`` matched ``build`` and the multi-step
    banner false-fired on benign prompts. Word-boundary matching + dropping the
    two low-signal 2-grams (``add a`` / ``add the``) fixes the false positive
    without over-suppressing a genuine multi-step prompt."""

    @staticmethod
    def _import_task_router():
        import importlib
        import sys
        hook_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hook_dir))
        try:
            if "task_router" in sys.modules:
                return importlib.reload(sys.modules["task_router"])
            return importlib.import_module("task_router")
        finally:
            sys.path.remove(str(hook_dir))

    def test_rebuild_does_not_match_build(self):
        # bare-substring matched `build` inside `rebuild` -> RED before Fix 8-B
        tr = self._import_task_router()
        assert tr._classify("rebuild the index files") is False

    def test_add_a_2gram_dropped(self):
        # bare-substring matched the `add a` 2-gram -> RED before Fix 8-A
        tr = self._import_task_router()
        assert tr._classify("add a missing newline to the file") is False

    def test_real_multi_step_still_fires(self):
        # the fix must not over-suppress a genuine multi-step prompt
        tr = self._import_task_router()
        assert tr._classify("refactor the authentication module") is True


class TestNonUtf8ReadersDegrade:
    """TP-195 195-A: both ``latest.json`` / ``current.json`` readers must
    degrade silently on a BOM/non-UTF-8 file rather than raise.

    ``UnicodeDecodeError`` is a ``ValueError`` subclass — neither
    ``json.JSONDecodeError`` nor ``OSError`` catches it, so a non-UTF-8 file
    raised uncaught out of ``read_text(encoding="utf-8")``. The hook's umbrella
    ``except BaseException`` then fail-opened (exit 0) but printed
    ``[ERROR] task_router crashed`` and lost the advisory. TP-192 W3-2 fixed the
    identical read in ``post_compact`` / ``post_write_check``; these two readers
    were the missed siblings (a §2.8 narrow-lock instance).

    Sister-site posture: the fix is applied byte-identically to the
    ``espalier/_vendor/cc`` mirror (``tests/test_vendor_cc_parity.py`` gate).
    """

    @staticmethod
    def _import_task_router():
        import importlib
        import sys
        hook_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hook_dir))
        try:
            if "task_router" in sys.modules:
                return importlib.reload(sys.modules["task_router"])
            return importlib.import_module("task_router")
        finally:
            sys.path.remove(str(hook_dir))

    # A non-UTF-8 byte (0xe9, latin-1 'é') inside otherwise-valid JSON.
    _BAD_BYTES = b'{"reasoning_entries": ["caf\xe9 step", {"kind": "decision"}]}'

    def test_non_utf8_plan_is_inactive(self, tmp_path, monkeypatch):
        """A non-UTF-8 execution_plan.json must read as inactive, not raise."""
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "execution_plan.json").write_bytes(
            b'{"status": "in_progress", "steps": ["caf\xe9"]}'
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        tr = self._import_task_router()
        assert tr._has_active_plan() is False

    def test_non_utf8_blueprint_counts_zero(self, tmp_path):
        """A non-UTF-8 latest.json must count zero decisions, not raise."""
        bp = tmp_path / "latest.json"
        bp.write_bytes(self._BAD_BYTES)
        tr = self._import_task_router()
        assert tr._count_decisions_in_blueprint(bp) == 0

    def test_valid_utf8_blueprint_still_counts(self, tmp_path):
        """Regression guard: the widened except must not swallow good reads."""
        bp = tmp_path / "latest.json"
        bp.write_text(
            '{"reasoning_entries": [{"kind": "decision"}, {"kind": "note"}]}',
            encoding="utf-8",
        )
        tr = self._import_task_router()
        assert tr._count_decisions_in_blueprint(bp) == 1


def _run_cold(prompt: str, cwd: Path) -> subprocess.CompletedProcess:
    """Like ``_run`` but pins ``CLAUDE_PROJECT_DIR`` to ``cwd`` so the cold-open
    flag and any plan resolve to the tmp root deterministically, independent of the
    ambient env."""
    import os
    payload = json.dumps({"prompt": prompt})
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload, capture_output=True, text=True, timeout=5,
        cwd=str(cwd), check=False,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(cwd)}, encoding="utf-8",
    )


def _drop_cold_open_flag(cwd: Path) -> Path:
    """Plant the one-shot cold-open flag the SessionStart producer would drop."""
    state = cwd / ".espalier-state"
    state.mkdir(parents=True, exist_ok=True)
    flag = state / "cold_open_pending"
    flag.write_text("2026-06-30T00:00:00+00:00", encoding="utf-8")
    return flag


class TestColdOpenConsumer:
    """TP-242: consumer half of the cold-open baton. On the session's first prompt
    after a new-session SessionStart, task_router emits the orientation directive
    (one-shot, BEFORE the active-plan early-return) and deletes the flag, so a
    task-first prompt can't silently preempt the readout."""

    @staticmethod
    def _import_task_router():
        import importlib
        hook_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        sys.path.insert(0, str(hook_dir))
        try:
            if "task_router" in sys.modules:
                return importlib.reload(sys.modules["task_router"])
            return importlib.import_module("task_router")
        finally:
            sys.path.remove(str(hook_dir))

    def test_directive_fires_and_consumes_flag(self, tmp_path):
        flag = _drop_cold_open_flag(tmp_path)
        result = _run_cold("how does X work?", tmp_path)  # benign, non-multi-step
        assert result.returncode == 0
        assert "[HARNESS] Cold open" in result.stdout
        assert not flag.exists(), "flag must be consumed (deleted) one-shot"

    def test_one_shot_second_prompt_no_directive(self, tmp_path):
        _drop_cold_open_flag(tmp_path)
        first = _run_cold("how does X work?", tmp_path)
        assert "[HARNESS] Cold open" in first.stdout
        second = _run_cold("how does Y work?", tmp_path)
        assert "[HARNESS] Cold open" not in second.stdout

    def test_fires_even_with_active_plan(self, tmp_path):
        """The directive precedes the _has_active_plan early-return: a /clear into a
        planned task is exactly when the where-was-I readout matters most."""
        _drop_cold_open_flag(tmp_path)
        _write_plan(tmp_path, status="in_progress")
        result = _run_cold("lets create a new module to handle X", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Cold open" in result.stdout
        # routing stays suppressed mid-plan (the early-return fires AFTER cold-open)
        assert "[HARNESS] Multi-step task detected" not in result.stdout

    def test_composes_with_routing_cold_open_first(self, tmp_path):
        """No active plan + a multi-step prompt: both fire, cold-open FIRST."""
        _drop_cold_open_flag(tmp_path)
        result = _run_cold("lets implement a new feature with three steps", tmp_path)
        assert result.returncode == 0
        out = result.stdout
        assert "[HARNESS] Cold open" in out
        assert "[HARNESS] Multi-step task detected" in out
        assert out.index("Cold open") < out.index("Multi-step task detected")

    def test_no_directive_without_flag(self, tmp_path):
        result = _run_cold("how does X work?", tmp_path)
        assert result.returncode == 0
        assert "[HARNESS] Cold open" not in result.stdout

    def test_consume_cold_open_fails_open_on_oserror(self, tmp_path, monkeypatch):
        """A flag-I/O OSError degrades to False (no directive) rather than crashing
        the advisory hook or suppressing the routing advisories below."""
        tr = self._import_task_router()

        def boom(self):
            raise OSError("planted")

        monkeypatch.setattr(Path, "is_file", boom)
        assert tr._consume_cold_open(tmp_path) is False


@pytest.mark.security
class TestRootResolvedOncePerInvocation:
    """One hook run must not resolve the project root twice.

    `_run_main` resolves the root, then `_has_active_plan()` resolved it again
    on its own. With CLAUDE_PROJECT_DIR unset that made `resolve_project_root`
    emit its fallback warning TWICE per prompt from a single UserPromptSubmit
    hook -- duplicate operator-visible stderr with no second question being
    asked. Fixed by letting the caller pass the root it already has.

    Pinned on the OBSERVABLE (how many warnings reach stderr) rather than on a
    call count, so a future refactor that resolves twice by another route is
    caught just the same.
    """

    WARNING_NEEDLE = "CLAUDE_PROJECT_DIR is empty"

    def test_fallback_warning_is_emitted_at_most_once(self, tmp_path):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": ""}
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps({"prompt": "hello there friend"}),
            capture_output=True, text=True, timeout=5,
            cwd=str(tmp_path), check=False, env=env, encoding="utf-8",
        )
        hits = proc.stderr.count(self.WARNING_NEEDLE)
        assert hits <= 1, (
            f"resolve_project_root ran more than once in a single hook "
            f"invocation -- {hits} fallback warnings on stderr:\n{proc.stderr}"
        )

    def test_predicate_still_resolves_its_own_root_when_not_given_one(self, tmp_path):
        """The zero-arg call must keep working — the parity contract uses it."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("_tr_probe", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        plan = tmp_path / "cc" / "execution_plan.json"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            json.dumps({"status": "in_progress", "steps": [{"index": 0}]}),
            encoding="utf-8",
        )
        monkey = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            assert mod._has_active_plan() is True
            assert mod._has_active_plan(tmp_path) is True
        finally:
            if monkey is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = monkey
