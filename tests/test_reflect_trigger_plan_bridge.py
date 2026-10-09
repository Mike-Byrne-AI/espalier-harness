"""The plan-mode bridge (INV-8): an APPROVED ``ExitPlanMode`` opens
``cc/execution_plan.json`` through ``reflect_trigger`` -- the PostToolUse hook
whose ``"*"`` matcher already receives the call -- so ``plan_guard`` allows the
edits the user just approved without a manual ``/implement-task``.

Three surfaces, pinned here:

1. The Markdown reader (``_steps_from_plan``, ``_plan_title``,
   ``_not_doing_from_plan``): top-level numbered items outside fenced code and
   outside a FRAME heading (Context, Decisions, Risks...), else the ``##``/``###``
   headings minus the frame ones, else one step from the title -- never empty,
   because ``plan_guard`` reads an empty step list as no plan. Linear on a 30 KB
   payload (every pattern is line-anchored and bounded).
2. The payload gate (``_approved_plan_text``): the plan is taken from a
   success-shaped payload only -- ``tool_response`` an object with a non-empty
   ``plan`` string, or the approval text as a string with ``tool_input.plan`` --
   and a subagent's approval (``isAgent``) opens nothing. Anything else writes
   nothing, exits 0, and names the shape in the hook's one JSON object.
3. The hook end to end, through a subprocess as Claude Code runs it: the file,
   its schema (the keys the schema-parity test pins), ``plan_guard``'s read of
   it, the one stdout object, the superseded-plan note, and the non-write
   tools that still print nothing.

Earn-the-red (2026-10-09, the lane branch): ``TestBridgeThroughTheHook``'s
approved-plan case driven against HEAD's ``reflect_trigger.py`` (``git show
HEAD:tools/cc/hooks/reflect_trigger.py`` into a scratch dir, the live
``tools/cc/hooks`` and ``tools/cc`` on PYTHONPATH, the same payload file): rc 0,
empty stdout, no ``cc/execution_plan.json`` -- RED. With the bridge: the file,
two steps, one JSON object -- GREEN.

Not pinned here, by the protocol: a REJECTED ``ExitPlanMode`` fails the tool
and reaches PostToolUseFailure, never this hook (``docs/HOOK_ASSUMPTIONS.md``
§7.1; driven live 2026-10-09 -- a rejected ExitPlanMode left
``.espalier-state/last_tool`` on the previous tool).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
TOOLS_CC = REPO_ROOT / "tools" / "cc"

# A plain import with the hook dir on sys.path -- the shape the sibling
# ``test_reflect_trigger_additionalcontext`` uses. Nothing here patches the
# module, so sharing the object with other tests in the process is safe.
sys.path.insert(0, str(HOOKS_DIR))
sys.path.insert(0, str(TOOLS_CC))
import _hook_utils  # noqa: E402
import plan_guard  # noqa: E402
import reflect_trigger as rt  # noqa: E402


def _schema_pins() -> tuple[frozenset[str], frozenset[str]]:
    """The plan's pinned key sets, read from the schema-parity test by path
    (robust under any pytest import mode; the constant lives in ONE place)."""
    spec = importlib.util.spec_from_file_location(
        "_schema_parity_pins", REPO_ROOT / "tests" / "test_execution_plan_schema_parity.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.EXPECTED_PLAN_TOP_LEVEL_KEYS, mod.EXPECTED_STEP_KEYS


PLAN = """# Add a logout button

## Context

The header has no way out; support asked twice.

## Decisions

1. The button goes in the header, not the footer.
2. No confirmation dialog.

## Steps

1. Add the button to the header; files: src/header.tsx
2. Wire the click to the session API
3. Add the test

## Non-goals

- No redesign of the header
- No change to the session timeout
"""

PLAN_FILE = "/home/u/.claude/plans/logout-button.md"

#: Thirty-kilobyte plans built from the shapes a line pattern could go
#: super-linear on; tests/test_redos.py times the reader on them.
_ADVERSARIAL_PLANS: dict[str, str] = {
    "numbered": ("1. " + "a" * 60 + "\n") * 500,
    "hashes": ("#" * 60 + " x\n") * 500,
    "spaced": ("  1.    " + "b" * 50 + "\n") * 600,
    "fences": "```\n" * 15000,
    "one-line": "1. " + "z" * 30000,
    "no-newline-hashes": "#" * 30000,
    "closing-hashes": ("## t " + "#" * 50 + "\n") * 600,
}


def _payload(plan: str = PLAN, *, response: str = "dict", is_agent: bool = False,
             path: str = PLAN_FILE) -> dict:
    """An ExitPlanMode PostToolUse payload in the shape Claude Code sends: the
    plan and its file in ``tool_input`` (``plan``, ``planFilePath``) and again
    in ``tool_response`` (``plan``, ``isAgent``, ``filePath``) -- the shape a
    real approved plan showed in this box's transcript, 2026-08-18."""
    tool_input = {"plan": plan, "planFilePath": path}
    responses: dict[str, object] = {
        "dict": {"plan": plan, "isAgent": is_agent, "filePath": path},
        "dict-no-plan": {"isAgent": is_agent, "filePath": path},
        "approved-str": "User has approved your plan. You can now start coding.",
        "other-str": "The user doesn't want to proceed with this tool use.",
        "list": [],
        "none": None,
    }
    data: dict = {"tool_name": "ExitPlanMode", "tool_input": tool_input}
    if response != "absent":
        data["tool_response"] = responses[response]
    return data


def _hook(payload: dict, root: Path, name: str = "reflect_trigger") -> subprocess.CompletedProcess:
    """Run a hook as Claude Code does: JSON on stdin, the project at ``root``,
    and none of the launching shell's harness variables."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ESPALIER_"))}
    clean["CLAUDE_PROJECT_DIR"] = str(root)
    audit_dir = os.environ.get("ESPALIER_AUDIT_DIR")
    if audit_dir:
        clean["ESPALIER_AUDIT_DIR"] = audit_dir
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / f"{name}.py")],
        input=json.dumps(payload), capture_output=True, encoding="utf-8",
        env=clean, cwd=str(root), timeout=45,
    )


def _one_object(stdout: str) -> str:
    """The additionalContext of the ONE JSON object on stdout; two objects, or
    none, fail the parse the way Claude Code reads it."""
    obj = json.loads(stdout)
    assert obj["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    return obj["hookSpecificOutput"]["additionalContext"]


def _plan_file(root: Path) -> Path:
    return root / "cc" / "execution_plan.json"


def _records(event_type: str) -> list[dict]:
    """Audit records of ``event_type`` under ``ESPALIER_AUDIT_DIR`` (conftest
    points it at a per-test directory; the child hook inherits it)."""
    out: list[dict] = []
    for log in Path(os.environ["ESPALIER_AUDIT_DIR"]).glob("*.log"):
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("event_type") == event_type:
                out.append(rec)
    return out


class TestStepsFromPlan:
    def test_numbered_items_under_a_steps_heading_become_the_steps(self):
        assert rt._steps_from_plan(PLAN) == [
            "Add the button to the header; files: src/header.tsx",
            "Wire the click to the session API",
            "Add the test",
        ]

    def test_numbered_items_under_a_frame_heading_are_not_steps(self):
        # The first smoke on a real plan turned four numbered DECISIONS into
        # steps 1-4; the frame headings are skipped, and when only frame
        # sections carry numbered items the reader falls through to headings.
        frame_only = "# T\n\n## Decisions\n\n1. a\n2. b\n\n## Build it\n\n## Ship it\n"
        assert rt._steps_from_plan(frame_only) == ["Build it", "Ship it"]

    def test_items_inside_a_fenced_block_and_nested_items_are_skipped(self):
        # Three spaces is nested too: a `1. ` parent's content starts at
        # column 3 (CommonMark), and a tab is an indent of four.
        text = ("# T\n\n```\n1. not a step\n```\n\n1. real step\n    2. nested detail\n"
                "   3. also nested\n\t4. tab-nested\n2. second real step\n")
        assert rt._steps_from_plan(text) == ["real step", "second real step"]

    def test_a_fence_closes_only_on_its_own_delimiter(self):
        text = "# T\n\n~~~\n1. inside\n```\n2. still inside\n~~~\n3. outside\n"
        assert rt._steps_from_plan(text) == ["outside"]

    def test_a_sub_heading_inside_a_frame_section_stays_framed(self):
        # The review's case: `### Rejected options` under `## Decisions` used
        # to re-admit the numbered list beneath it as the plan's steps.
        text = ("# T\n\n## Decisions\n\n### Rejected options\n\n1. keep the footer\n2. add a dialog\n\n"
                "## Build it\n\n1. the real step\n")
        assert rt._steps_from_plan(text) == ["the real step"]

    def test_an_atx_closing_hash_run_is_not_part_of_the_text(self):
        assert rt._steps_from_plan("# T ##\n\n## Build it ##\n\n## Ship it ###\n") == ["Build it", "Ship it"]
        assert rt._plan_title("# Add a button ##\n", "") == "Add a button"

    def test_a_pipe_in_a_step_is_replaced_because_the_cli_splits_on_it(self):
        steps = rt._steps_from_plan("1. run a | b\n2. then c\n")
        assert steps == ["run a / b", "then c"]
        assert not any("|" in s for s in steps)

    def test_emphasis_and_code_marks_are_dropped_and_whitespace_collapsed(self):
        assert rt._steps_from_plan("1. **Build** the   `thing`\n") == ["Build the thing"]

    def test_the_cap_keeps_the_first_items_and_names_the_rest(self):
        text = "".join(f"{i}. item {i}\n" for i in range(1, 46))
        steps = rt._steps_from_plan(text)
        assert len(steps) == rt.PLAN_BRIDGE_MAX_STEPS
        assert steps[0] == "item 1"
        assert steps[-1] == "...and 16 more items in the plan file"

    def test_a_long_item_is_truncated_with_an_ellipsis(self):
        steps = rt._steps_from_plan("1. " + "x" * 1000 + "\n")
        assert len(steps[0]) == rt.PLAN_BRIDGE_STEP_CHARS
        assert steps[0].endswith("...")

    def test_headings_are_the_fallback_minus_the_frame_ones(self):
        text = ("# T\n\n## Context\n\nwhy\n\n## Goals of this lane\n\n## Build the thing\n\n### Verify it\n\n"
                "## Risks\n\n## Not doing\n\n- the footer\n")
        assert rt._steps_from_plan(text) == ["Build the thing", "Verify it"]
        assert "not doing" in rt._PLAN_FRAME_HEADINGS  # the not-doing reader and the frame set agree

    def test_a_title_alone_is_one_step_and_nothing_is_never_a_step_list(self):
        assert rt._steps_from_plan("# Just a title\n\nprose\n") == ["Execute the approved plan: Just a title"]
        assert rt._steps_from_plan("") == ["Execute the approved plan"]
        assert rt._steps_from_plan("prose only") == ["Execute the approved plan"]

    @pytest.mark.parametrize("text", ["", "#", "1.", "1. ", "##\n##\n", "```\n1. x\n", "   \n\t\n"])
    def test_every_degenerate_shape_yields_at_least_one_step(self, text):
        # plan_guard reads an empty step list as NO plan, so the reader never
        # returns one.
        assert rt._steps_from_plan(text)

    def test_the_reader_answers_every_thirty_kilobyte_adversarial_shape(self):
        # The shapes a super-linear line pattern would choke on. The wall-clock
        # budget for them lives with the other hook-pattern budgets in the
        # serial file (tests/test_redos.py::TestPlanModeBridgeReader): a timed
        # bound here would false-fail the parallel run (test_proof_tier pins
        # that rule). This test pins only that each shape yields a step list.
        for body in _ADVERSARIAL_PLANS.values():
            assert rt._steps_from_plan(body)
            assert rt._not_doing_from_plan(body)
            assert rt._plan_title(body, "")

    def test_not_doing_is_the_first_line_under_a_non_goals_heading_else_fixed(self):
        assert rt._not_doing_from_plan(PLAN) == "No redesign of the header"
        assert rt._not_doing_from_plan("# T\n\n## Out of scope\n\nNothing about auth.\n") == "Nothing about auth."
        assert rt._not_doing_from_plan("# T\n\n1. a\n") == rt._PLAN_FIXED_NOT_DOING
        assert rt._not_doing_from_plan("")  # never empty: auto-compose needs the field

    def test_the_title_is_the_h1_else_the_file_else_a_fixed_name(self):
        assert rt._plan_title(PLAN, PLAN_FILE) == "Add a logout button"
        assert rt._plan_title("no heading", PLAN_FILE) == "approved plan-mode plan (logout-button)"
        assert rt._plan_title("no heading", "") == "approved plan-mode plan"
        assert rt._plan_title("```\n# inside a fence\n```\n", "") == "approved plan-mode plan"

    def test_the_frame_heading_set_spells_no_stack_directory_name(self):
        # Purpose-scoped to plan prose; the stack-table census would read a
        # bare 'test'/'tests' as the test-root vocabulary.
        assert not {"test", "tests", "spec", "src", "lib"} & set(rt._PLAN_FRAME_HEADINGS)


class TestApprovedPlanText:
    def test_an_object_response_with_a_plan_is_the_approval(self):
        plan, path, why = rt._approved_plan_text(_payload())
        assert (plan, path, why) == (PLAN, PLAN_FILE, "")

    def test_the_file_path_falls_back_to_tool_input(self):
        data = _payload()
        del data["tool_response"]["filePath"]
        assert rt._approved_plan_text(data)[1] == PLAN_FILE

    def test_a_subagents_approval_is_refused_by_name(self):
        plan, _, why = rt._approved_plan_text(_payload(is_agent=True))
        assert plan == "" and "subagent" in why

    def test_an_object_without_a_plan_text_names_its_keys(self):
        plan, _, why = rt._approved_plan_text(_payload(response="dict-no-plan"))
        assert plan == "" and "without a plan text" in why and "filePath" in why

    def test_the_approval_string_takes_the_plan_from_tool_input(self):
        plan, path, why = rt._approved_plan_text(_payload(response="approved-str"))
        assert (plan, path, why) == (PLAN, PLAN_FILE, "")

    def test_the_approval_string_with_no_tool_input_plan_opens_nothing(self):
        data = _payload(response="approved-str")
        data["tool_input"] = {"planFilePath": PLAN_FILE}
        plan, _, why = rt._approved_plan_text(data)
        assert plan == "" and "no plan in tool_input" in why

    @pytest.mark.parametrize("response", ["other-str", "list", "none", "absent"])
    def test_any_other_shape_is_not_an_approval(self, response):
        plan, _, why = rt._approved_plan_text(_payload(response=response))
        assert plan == "" and "not an approval" in why

    def test_a_non_object_tool_input_never_raises(self):
        data = _payload(response="approved-str")
        data["tool_input"] = "not a dict"
        assert rt._approved_plan_text(data)[0] == ""
        data = _payload()
        data["tool_input"] = None
        assert rt._approved_plan_text(data)[0] == PLAN


class TestBridgeThroughTheHook:
    def test_an_approved_plan_opens_the_execution_plan_and_says_so(self, tmp_path):
        result = _hook(_payload(), tmp_path)
        assert result.returncode == 0, result.stderr
        plan = json.loads(_plan_file(tmp_path).read_text(encoding="utf-8"))
        assert plan["status"] == "in_progress"
        assert plan["task"] == "Add a logout button"
        assert [s["description"] for s in plan["steps"]] == [
            "Add the button to the header; files: src/header.tsx",
            "Wire the click to the session API",
            "Add the test",
        ]
        assert plan["goal"] == f"approved in plan mode -- {PLAN_FILE}"
        assert plan["not_doing"] == "No redesign of the header"
        top_keys, step_keys = _schema_pins()
        assert set(plan) == set(top_keys)
        assert all(set(s) == set(step_keys) for s in plan["steps"])
        # The row's own integration: plan_guard reads the file as an OPEN window.
        assert plan_guard._has_active_plan(tmp_path) is True
        context = _one_object(result.stdout)
        assert "cc/execution_plan.json opened from the approved plan -- 3 steps" in context
        assert "execution_plan.py status" in context and "mark <i> passed" in context
        assert "superseded" not in context
        # The approval counted as a tool call, like every other call.
        assert (tmp_path / ".espalier-state" / "tool_call_count").read_text(encoding="utf-8").strip() == "1"

    def test_the_approval_string_shape_opens_the_plan_from_tool_input(self, tmp_path):
        result = _hook(_payload(response="approved-str"), tmp_path)
        assert result.returncode == 0, result.stderr
        plan = json.loads(_plan_file(tmp_path).read_text(encoding="utf-8"))
        assert plan["task"] == "Add a logout button" and len(plan["steps"]) == 3
        assert plan_guard._has_active_plan(tmp_path) is True

    def test_a_subagents_approval_opens_nothing_and_says_why(self, tmp_path):
        result = _hook(_payload(is_agent=True), tmp_path)
        assert result.returncode == 0, result.stderr
        assert not _plan_file(tmp_path).exists()
        assert plan_guard._has_active_plan(tmp_path) is False
        assert "no execution plan opened" in _one_object(result.stdout)
        assert "subagent" in _one_object(result.stdout)
        assert _records("posttooluse_failed_open_plan_bridge_shape") == []  # a decision, not a fault

    @pytest.mark.parametrize("response", ["other-str", "list", "none", "absent", "dict-no-plan"])
    def test_a_payload_that_is_not_an_approval_opens_nothing_and_exits_zero(self, tmp_path, response):
        # Class-B: a valid-JSON non-object tool_response, or a string that is
        # not the approval text, must neither crash the hook nor open the window.
        result = _hook(_payload(response=response), tmp_path)
        assert result.returncode == 0, result.stderr
        assert not _plan_file(tmp_path).exists()
        assert "no execution plan opened" in _one_object(result.stdout)
        # A shape the bridge does not read is a Claude Code that moved: the
        # record outlives the one turn of additionalContext.
        assert len(_records("posttooluse_failed_open_plan_bridge_shape")) == 1

    def test_an_in_progress_plan_is_replaced_and_named(self, tmp_path):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ESPALIER_"))}
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        script = TOOLS_CC / "execution_plan.py"
        subprocess.run(
            [sys.executable, str(script), "create", "--task", "Old lane", "--steps", "one|two"],
            check=True, capture_output=True, encoding="utf-8", env=env, cwd=str(tmp_path), timeout=45,
        )
        subprocess.run(
            [sys.executable, str(script), "mark", "0", "passed"],
            check=True, capture_output=True, encoding="utf-8", env=env, cwd=str(tmp_path), timeout=45,
        )
        result = _hook(_payload(), tmp_path)
        assert result.returncode == 0, result.stderr
        plan = json.loads(_plan_file(tmp_path).read_text(encoding="utf-8"))
        assert plan["task"] == "Add a logout button"
        context = _one_object(result.stdout)
        assert "superseded: Old lane (1/2 passed), demoted to cc/_cold/" in context
        # The superseded plan's record survives beside the blueprint cold
        # store, as `reset` leaves it: its passed step is not overwritten.
        cold = sorted((tmp_path / "cc" / "_cold").glob("*-execution_plan.json"))
        assert len(cold) == 1, cold
        old = json.loads(cold[0].read_text(encoding="utf-8"))
        assert old["task"] == "Old lane" and old["steps"][0]["status"] == "passed"

    def test_a_completed_plan_is_replaced_without_a_superseded_note(self, tmp_path):
        _plan_file(tmp_path).parent.mkdir(parents=True)
        _plan_file(tmp_path).write_text(
            json.dumps({"task": "Done lane", "status": "complete", "steps": [{"status": "passed"}]}),
            encoding="utf-8",
        )
        result = _hook(_payload(), tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(_plan_file(tmp_path).read_text(encoding="utf-8"))["task"] == "Add a logout button"
        assert "superseded" not in _one_object(result.stdout)

    def test_a_malformed_old_plan_file_is_replaced_not_crashed_on(self, tmp_path):
        _plan_file(tmp_path).parent.mkdir(parents=True)
        _plan_file(tmp_path).write_text("[1, 2", encoding="utf-8")
        result = _hook(_payload(), tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(_plan_file(tmp_path).read_text(encoding="utf-8"))["status"] == "in_progress"

    def test_a_read_payload_still_prints_nothing_and_opens_nothing(self, tmp_path):
        # ExitPlanMode is the one non-write tool this hook speaks on; the
        # others keep the empty stdout test_session_signals and test_hooks pin.
        result = _hook({"tool_name": "Read", "tool_input": {"file_path": "src/app.py"},
                        "tool_response": {"plan": PLAN}}, tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert not _plan_file(tmp_path).exists()

    def test_a_write_payload_still_counts_and_opens_nothing(self, tmp_path):
        result = _hook({"tool_name": "Write", "tool_input": {"file_path": "src/app.py", "content": "x"}}, tmp_path)
        assert result.returncode == 0, result.stderr
        assert not _plan_file(tmp_path).exists()
        assert (tmp_path / ".espalier-state" / "tool_call_count").read_text(encoding="utf-8").strip() == "1"



class TestBridgeInProcess:
    def test_a_plan_module_that_predates_the_bridge_is_named_not_crashed_on(self, tmp_path, monkeypatch):
        # An upgrade preserves a user-edited tools/cc/execution_plan.py; such a
        # module has no build_plan, and the generic handler would name a class.
        monkeypatch.setitem(sys.modules, "execution_plan", types.ModuleType("execution_plan"))
        _hook_utils.take_advisories()
        rt._bridge_approved_plan(_payload(), tmp_path)
        lines = _hook_utils.take_advisories()
        assert any("predates the bridge" in ln and "espalier:managed" in ln for ln in lines), lines
        assert not _plan_file(tmp_path).exists()
