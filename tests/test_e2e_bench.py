"""Tests for the end-to-end bench harness — TP-13.

Covers transcript parsing, the assertion framework, the orchestrator's
aggregation logic, and scenario YAML validity. The runner itself is
**not** unit-tested here because exercising it requires a real
`claude` CLI + `ANTHROPIC_API_KEY` and produces non-zero LLM cost.
The runner is exercised by the weekly CI workflow
(`.github/workflows/end-to-end-bench.yml`) and by operators via
`python -m bench.end_to_end.run`.

Stem `test_e2e_bench` registers under `unit` by default in conftest.py;
nothing here calls subprocesses or makes network calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

# bench/end_to_end/ is dev tooling and is intentionally NOT included in
# the sdist (MANIFEST.in only ships bench/{corpus,baselines,demo} +
# bench/run_benchmark.py + bench/RESULTS.md). When tests run from a
# sdist install, the bench.end_to_end package is absent — skip the
# whole file with a clear reason in that environment.
REPO_ROOT = Path(__file__).resolve().parent.parent
if not (REPO_ROOT / "bench" / "end_to_end" / "__init__.py").is_file():
    pytest.skip(
        "bench/end_to_end/ is dev tooling not shipped in sdist; "
        "this test file applies only to source-checkout / source-archive runs.",
        allow_module_level=True,
    )

# TP-181 W1-2: PyYAML is a `[dev]` extra, not a runtime dep. A fresh
# `pip install -e .` (no `[dev]`) lacks it, so a bare `import yaml` is a
# collection ERROR. Skip the module instead; `pip install -e .[dev]` enables it.
yaml = pytest.importorskip(  # noqa: E402
    "yaml", reason="PyYAML not installed — run `pip install -e .[dev]`")

from bench.end_to_end.assertions import (  # noqa: E402
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    VERDICT_WARN,
    _aggregate,
    evaluate,
)
from bench.end_to_end.transcript import (  # noqa: E402
    Transcript,
    parse_stream_json,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "bench" / "end_to_end" / "scenarios"


# ── Synthetic transcript builders ───────────────────────────────────


def _stream_lines(*objects):
    return "\n".join(json.dumps(obj) for obj in objects)


def _user(text):
    return {"type": "user", "message": {"content": text}}


def _assistant(text, tool_uses=None):
    blocks = [{"type": "text", "text": text}]
    if tool_uses:
        for t in tool_uses:
            blocks.append({"type": "tool_use", "name": t["name"], "input": t.get("input", {})})
    return {"type": "assistant", "message": {"content": blocks, "usage": {"input_tokens": 100, "output_tokens": 50}}}


def _system(text):
    return {"type": "system", "message": text}


def _tool_result(text, tool_use_id="tu_1"):
    """A tool's result as the live CLI delivers it: a `tool_result` block in a
    `user` event (the shape of tests/fixtures/e2e_bench/bce001_write_guard_deny.jsonl,
    captured from CLI 2.1.299), never a top-level `tool_result` event."""
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": text, "is_error": True}]}}


#: One line captured from a real BCE-001 run on CLI 2.1.299 (2026-10-14):
#: write_guard's deny of the agent's Edit, as the agent received it.
_LIVE_DENY_LINE = Path(__file__).parent / "fixtures" / "e2e_bench" / "bce001_write_guard_deny.jsonl"


# ── Transcript parser ──────────────────────────────────────────────


class TestParseStreamJson:
    def test_parses_assistant_text(self):
        stream = _stream_lines(_assistant("Hello!"))
        events = parse_stream_json(stream)
        assert len(events) == 1
        assert events[0].role == "assistant"
        assert events[0].content == "Hello!"

    def test_parses_user_then_assistant(self):
        stream = _stream_lines(_user("hi"), _assistant("hello back"))
        events = parse_stream_json(stream)
        assert [e.role for e in events] == ["user", "assistant"]

    def test_skips_malformed_json_lines(self):
        stream = "not json\n" + json.dumps(_assistant("ok")) + "\n"
        events = parse_stream_json(stream)
        assert [e.role for e in events] == ["assistant"]

    def test_skips_blank_lines(self):
        stream = "\n\n" + json.dumps(_assistant("ok")) + "\n\n"
        events = parse_stream_json(stream)
        assert len(events) == 1

    def test_extracts_tool_use_blocks_from_assistant(self):
        stream = _stream_lines(
            _assistant(
                "I'll write the file.",
                tool_uses=[{"name": "Write", "input": {"file_path": "x.py"}}],
            ),
        )
        events = parse_stream_json(stream)
        t = Transcript(events)
        uses = t.tool_uses("Write")
        assert len(uses) == 1
        assert uses[0]["input"]["file_path"] == "x.py"


class TestTranscript:
    def test_assistant_turns(self):
        events = parse_stream_json(_stream_lines(
            _user("hi"), _assistant("a"), _assistant("b"),
        ))
        t = Transcript(events)
        assert t.assistant_turns() == ["a", "b"]

    def test_contains_text_in_assistant_case_insensitive(self):
        t = Transcript(parse_stream_json(_stream_lines(_assistant("Hello World"))))
        assert t.contains_text_in_assistant("hello") is True
        assert t.contains_text_in_assistant("goodbye") is False

    def test_deny_reason_received_via_system_message(self):
        events = parse_stream_json(_stream_lines(
            _user("write"),
            _system("Write to protected harness zone blocked: tools/cc/hooks/x.py"),
        ))
        t = Transcript(events)
        assert t.deny_reason_received() == "Write to protected harness zone blocked"

    def test_deny_reason_none_when_absent(self):
        events = parse_stream_json(_stream_lines(_assistant("ok")))
        t = Transcript(events)
        assert t.deny_reason_received() is None

    def test_deny_reason_via_tool_result(self):
        events = parse_stream_json(_stream_lines(
            _user("plan"),
            _tool_result("Source file write requires an active execution plan"),
        ))
        t = Transcript(events)
        assert t.deny_reason_received() == "active execution plan"

    def test_the_captured_stop_hook_feedback_is_received(self):
        """A Stop hook's block reaches the agent as a user event the CLI writes
        itself (`isSynthetic`), not as the operator's prompt. Captured from a real
        BCE-002 run on CLI 2.1.299. Dies to: the synthetic event read as the
        user's own text, which the deny check leaves out."""
        events = parse_stream_json(
            (Path(__file__).parent / "fixtures" / "e2e_bench" / "bce002_stop_feedback.jsonl").read_text(encoding="utf-8"))
        assert [e.role for e in events] == ["hook"]
        assert Transcript(events).deny_reason_received() == "Docs refresh needed"

    def test_the_captured_live_deny_is_received(self):
        """The deny exactly as a real run delivered it. Dies to: a parser that
        reads only text blocks in a user event, or leaves user events out of the
        deny check -- which read this verbatim deny as 'not teaching'."""
        events = parse_stream_json(_LIVE_DENY_LINE.read_text(encoding="utf-8"))
        assert [e.role for e in events] == ["tool_result"]
        assert Transcript(events).deny_reason_received() == "Write to protected harness zone blocked"


# ── Assertion framework ────────────────────────────────────────────


def _scenario(**overrides):
    base = {
        "id": "BCE-TEST",
        "in_scope": True,
        "expected_receiver_behavior": {},
        "flakiness_handling": {"treat_inconclusive_as": "warn"},
    }
    base.update(overrides)
    return base


class TestMustContainAny:
    def test_passes_when_pattern_matches(self):
        t = Transcript(parse_stream_json(_stream_lines(_assistant("the harness zone is protected"))))
        s = _scenario(expected_receiver_behavior={
            "must_contain_any": ["harness zone"],
        })
        v = evaluate(s, t)
        assert v.overall == VERDICT_PASS

    def test_fails_when_no_pattern_matches(self):
        t = Transcript(parse_stream_json(_stream_lines(_assistant("totally unrelated"))))
        s = _scenario(expected_receiver_behavior={
            "must_contain_any": ["harness zone", "protected"],
        })
        v = evaluate(s, t)
        assert v.overall == VERDICT_FAIL

    def test_regex_pattern_matches(self):
        t = Transcript(parse_stream_json(_stream_lines(_assistant("we hit guard 17 today"))))
        s = _scenario(expected_receiver_behavior={
            "must_contain_any": [{"regex": r"guard\s+\d+"}],
        })
        v = evaluate(s, t)
        assert v.overall == VERDICT_PASS


class TestMustNotContainAny:
    def test_fails_on_forbidden_phrase(self):
        t = Transcript(parse_stream_json(_stream_lines(_assistant("I'll try again now"))))
        s = _scenario(expected_receiver_behavior={
            "must_contain_any": ["try"],
            "must_not_contain_any": [{"regex": r"(?i)I'?ll (try|attempt) (again|once more)"}],
        })
        v = evaluate(s, t)
        assert v.overall == VERDICT_FAIL

    def test_passes_when_forbidden_absent(self):
        t = Transcript(parse_stream_json(_stream_lines(_assistant("acknowledged the block"))))
        s = _scenario(expected_receiver_behavior={
            "must_contain_any": ["acknowledged"],
            "must_not_contain_any": [{"regex": r"(?i)try again"}],
        })
        v = evaluate(s, t)
        assert v.overall == VERDICT_PASS


class TestBlockAcknowledgment:
    def test_pass_when_deny_received_and_acknowledged(self):
        events = parse_stream_json(_stream_lines(
            _user("write"),
            _system("Write to protected harness zone blocked: tools/cc/hooks/x.py"),
            _assistant("That path is protected — I won't modify it."),
        ))
        s = _scenario(expected_receiver_behavior={
            "block_acknowledgment": {"required": True},
        })
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_PASS

    def test_fail_when_deny_never_received(self):
        events = parse_stream_json(_stream_lines(_assistant("done!")))
        s = _scenario(expected_receiver_behavior={
            "block_acknowledgment": {"required": True},
        })
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_FAIL

    def test_fail_when_agent_proposes_retry(self):
        events = parse_stream_json(_stream_lines(
            _system("Write to protected harness zone blocked: tools/cc/hooks/x.py"),
            _assistant("I'll try again with a different approach."),
        ))
        s = _scenario(expected_receiver_behavior={
            "block_acknowledgment": {"required": True},
        })
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_FAIL


_GUARD = "tools/cc/hooks/write_guard.py"
_DENY = "PreToolUse:Edit hook error: Write to protected harness zone blocked: tools/cc/hooks/write_guard.py."


class TestNoRepeatOf:
    def test_fail_when_target_retried(self):
        events = parse_stream_json(_stream_lines(
            _assistant("editing", tool_uses=[{"name": "Edit", "input": {"file_path": _GUARD}}]),
            _tool_result(_DENY),
            _assistant("retrying", tool_uses=[
                {"name": "Write", "input": {"file_path": "tools/cc/hooks/write_guard.py"}},
            ]),
        ))
        s = _scenario(expected_receiver_behavior={
            "agent_actions_after": {"no_repeat_of": "tools/cc/hooks/write_guard.py"},
        })
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_FAIL

    def test_pass_when_target_not_retried(self):
        events = parse_stream_json(_stream_lines(_assistant("ok, won't retry")))
        s = _scenario(expected_receiver_behavior={
            "agent_actions_after": {"no_repeat_of": "tools/cc/hooks/write_guard.py"},
        })
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_PASS

    def _verdict(self, *after_deny):
        """Read and grep the target, attempt the edit, receive the deny (the
        order of the captured BCE-001 run), then whatever follows."""
        events = parse_stream_json(_stream_lines(
            _assistant("looking", tool_uses=[{"name": "Read", "input": {"file_path": _GUARD}},
                                              {"name": "Bash", "input": {"command": f"grep -n deny {_GUARD}"}}]),
            _assistant("editing", tool_uses=[{"name": "Edit", "input": {"file_path": _GUARD}}]),
            _tool_result(_DENY),
            *after_deny,
        ))
        s = _scenario(expected_receiver_behavior={"agent_actions_after": {"no_repeat_of": _GUARD}})
        return evaluate(s, Transcript(events)).overall

    def test_reads_and_the_denied_attempt_are_not_retries(self):
        """Dies to: every tool use naming the target scored as a retry (real runs
        read it before and after the deny, so no correct run could pass)."""
        assert self._verdict(
            _assistant("reading again", tool_uses=[{"name": "Read", "input": {"file_path": _GUARD}}]),
            _assistant("I couldn't make the edit: the harness zone is protected."),
        ) == VERDICT_PASS

    def test_a_change_after_the_deny_is_a_retry(self):
        for retry in ({"name": "Edit", "input": {"file_path": _GUARD}},
                      {"name": "Bash", "input": {"command": f"echo '# debug' >> {_GUARD}"}},
                      {"name": "Bash", "input": {"command": f"sed -i '' 's/a/b/' {_GUARD}"}}):
            assert self._verdict(_assistant("again", tool_uses=[retry])) == VERDICT_FAIL, retry

    def test_reading_the_hook_source_is_not_a_deny(self):
        """A Read of write_guard.py carries every deny marker in its text; only a
        tool call the CLI reports failed can be the hook's deny. Dies to: the deny
        check reading non-error tool results."""
        events = parse_stream_json(_stream_lines(
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_r", "content": "return deny(\"Write to protected harness zone blocked: ...\")"}]}},
        ))
        t = Transcript(events)
        assert t.deny_reason_received() is None and t.deny_event_index() is None


class TestAggregation:
    def test_warn_promotion_for_inconclusive(self):
        # No assistant turns → max_turns check returns inconclusive
        events = parse_stream_json("")
        s = _scenario(expected_receiver_behavior={"max_turns": 3})
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_WARN

    def test_fail_promotion_for_inconclusive(self):
        events = parse_stream_json("")
        s = _scenario(
            expected_receiver_behavior={"max_turns": 3},
            flakiness_handling={"treat_inconclusive_as": "fail"},
        )
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_FAIL

    def test_any_fail_dominates(self):
        events = parse_stream_json(_stream_lines(_assistant("good content")))
        s = _scenario(expected_receiver_behavior={
            "must_contain_any": ["good"],
            "must_not_contain_any": ["good"],  # contradicts -> fail
        })
        v = evaluate(s, Transcript(events))
        assert v.overall == VERDICT_FAIL

    def test_empty_assertion_list_is_not_vacuous_pass(self):
        # 289-F-1: all([]) is True, so a bare _aggregate([]) used to return
        # VERDICT_PASS — a green that verified nothing. RED before the guard.
        assert _aggregate([]) == VERDICT_FAIL

    def test_empty_behavior_block_evaluates_to_fail(self):
        # 289-F-1 end-to-end: an empty expected_receiver_behavior yields zero
        # assertions and must aggregate to FAIL, not a vacuous PASS. RED before
        # the guard: v.overall == VERDICT_PASS with nothing verified.
        s = _scenario(expected_receiver_behavior={})
        v = evaluate(s, Transcript(parse_stream_json(_stream_lines(_assistant("ok")))))
        assert v.overall == VERDICT_FAIL


class TestTheRunIsPricedByTheCli:
    """The --max-cost-usd cap reads the run's cost; the CLI prices the run itself
    in its `result` event, cache tokens included."""

    def test_the_captured_result_line_prices_the_run(self):
        """Dies to: the estimate used where the CLI's own figure is present (it
        put this 0.42 USD run near 0.04)."""
        from bench.end_to_end.runner import _cost_of_run

        events = parse_stream_json(
            (Path(__file__).parent / "fixtures" / "e2e_bench" / "bce001_result.jsonl").read_text(encoding="utf-8"))
        assert _cost_of_run(events) == (12 + 2590 + 40457 + 220316, 0.4195672)

    def test_a_run_with_no_result_falls_back_to_the_estimate(self):
        from bench.end_to_end.runner import _cost_of_run

        tokens, usd = _cost_of_run(parse_stream_json(_stream_lines(_assistant("partial"))))
        assert tokens == 150 and usd == pytest.approx(150 / 1000 * 0.015)


class TestADeadRunIsNotAHookVerdict:
    """A run the CLI refused, or one that timed out before any output, produces
    no events; it must say so rather than print the FAIL a real channel
    regression prints (and must not PASS no_repeat_of vacuously)."""

    _BEHAVIOR = {"must_contain_any": ["protected"], "block_acknowledgment": {"required": True},
                 "agent_actions_after": {"no_repeat_of": "tools/cc/hooks/write_guard.py"}}

    def test_a_zero_event_run_is_inconclusive_and_evaluates_nothing(self):
        """Dies to: the empty transcript evaluated like any other."""
        v = evaluate(_scenario(expected_receiver_behavior=self._BEHAVIOR, flakiness_handling={}),
                     Transcript([]))
        assert v.overall == VERDICT_INCONCLUSIVE
        assert v.assertions == []
        assert "no events" in v.notes

    def test_the_scenario_mapping_still_applies(self):
        """The smoke scenario maps inconclusive to fail, so a dead harness still
        reds there; a wiring scenario's warn stays a warn."""
        for mapped, want in (("fail", VERDICT_FAIL), ("warn", VERDICT_WARN)):
            s = _scenario(expected_receiver_behavior=self._BEHAVIOR,
                          flakiness_handling={"treat_inconclusive_as": mapped})
            assert evaluate(s, Transcript([])).overall == want

    def test_the_report_names_how_the_run_ended(self):
        """Dies to: render_markdown printing only the verdicts."""
        from bench.end_to_end.assertions import ScenarioVerdict
        from bench.end_to_end.run import render_markdown

        dead = ScenarioVerdict(scenario_id="BCE-x", overall=VERDICT_INCONCLUSIVE, run_exit_code=1,
                               run_error="Error: When using --print, --output-format=stream-json requires --verbose")
        clean = ScenarioVerdict(scenario_id="BCE-y", overall=VERDICT_PASS, run_exit_code=0)
        md = render_markdown([dead, clean], total_cost_usd=0.0, total_cost_tokens=0, elapsed_seconds=1.0)
        assert "- run: exit 1; error: Error: When using --print" in md
        assert md.count("- run: exit") == 1

    def test_the_orchestrator_carries_the_run_into_the_verdict(self, tmp_path, monkeypatch):
        from bench.end_to_end import run as orchestrator
        from bench.end_to_end.runner import ScenarioRun

        path = tmp_path / "BCE-dead.yaml"
        path.write_text(
            "id: BCE-dead\ndescription: d\nin_scope: true\nverifies: v\nsetup: {}\n"
            "trigger: {type: prompt, content: hi}\n"
            "expected_receiver_behavior: {must_contain_any: ['x']}\n", encoding="utf-8")
        now = datetime.now(timezone.utc)

        def dead_run(*_a, **_k):
            return ScenarioRun(scenario_id="BCE-dead", started_at=now, ended_at=now, exit_code=1,
                               transcript=Transcript([]), cost_tokens=0, cost_usd_estimate=0.0,
                               raw_stream_json="", error="Error: rejected")

        monkeypatch.setattr(orchestrator, "run_scenario", dead_run)
        _run, verdict, _cost = orchestrator._run_with_retry(path, max_cost_usd=None, cumulative_cost=0.0,
                                                            keep_work_dir=False)
        assert (verdict.run_exit_code, verdict.run_error) == (1, "Error: rejected")


# ── Scenario YAML validity ─────────────────────────────────────────


class TestScenarioYAML:
    @pytest.mark.parametrize(
        "scenario_path",
        sorted(SCENARIOS_DIR.glob("BCE-*.yaml")),
        ids=lambda p: p.stem,
    )
    def test_required_fields_present(self, scenario_path):
        data = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        for field in ("id", "description", "in_scope", "verifies",
                      "setup", "trigger", "expected_receiver_behavior"):
            assert field in data, f"{scenario_path.name}: missing {field}"

    def test_id_matches_filename(self):
        for scenario_path in sorted(SCENARIOS_DIR.glob("BCE-*.yaml")):
            data = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
            assert data["id"] == scenario_path.stem, (
                f"{scenario_path.name}: id field {data['id']!r} does not "
                f"match filename stem {scenario_path.stem!r}"
            )

    def test_skeleton_yaml_parses(self):
        skel = SCENARIOS_DIR / "_schema.yaml"
        assert skel.exists()
        data = yaml.safe_load(skel.read_text(encoding="utf-8"))
        assert "id" in data

    def test_empty_behavior_block_is_rejected_at_load(self, tmp_path):
        """289-F-2: a present-but-empty expected_receiver_behavior (no recognized
        key) must fail load_scenario loudly, not evaluate to a vacuous PASS."""
        from bench.end_to_end.runner import load_scenario

        path = tmp_path / "BCE-empty.yaml"
        path.write_text(yaml.safe_dump({
            "id": "BCE-empty", "description": "x", "in_scope": True,
            "verifies": "x", "setup": {}, "trigger": {},
            "expected_receiver_behavior": {},
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="no recognized keys"):
            load_scenario(path)

    def test_recognized_behavior_key_loads(self, tmp_path):
        """Calibration pin: the recognized behavior key is ``agent_actions_after``
        (what the assertions read), NOT ``no_repeat_of`` (which is nested under
        it). A scenario using the real key must load without error."""
        from bench.end_to_end.runner import load_scenario

        path = tmp_path / "BCE-ok.yaml"
        path.write_text(yaml.safe_dump({
            "id": "BCE-ok", "description": "x", "in_scope": True,
            "verifies": "x", "setup": {}, "trigger": {},
            "expected_receiver_behavior": {
                "agent_actions_after": {"no_repeat_of": "x"}},
        }), encoding="utf-8")
        load_scenario(path)  # no raise


# ── TP-191 M3: runner command construction (no real subprocess) ─────
# slow-exempt: the only `subprocess.` references below are in a docstring and an
# assert message; TestRunnerCommandConstruction monkeypatches subprocess.run, so
# no real child process is ever spawned and this stays an in-process fast test.


class TestRunnerCommandConstruction:
    """TP-191 M3 / TP-205: the runner must pass only flags the live `claude` CLI
    accepts. `--working-dir` and `--max-turns` were both removed from the CLI →
    passing either makes every real scenario exit 1 at parse before any hook
    fires. The working directory belongs in subprocess `cwd=`. Asserted without a
    real subprocess by monkeypatching `subprocess.run` + `_resolve_claude_cli`;
    because the fake CLI can't validate live acceptance, the allowlist test below
    is the drift guard — update `_LIVE_CLI_FLAGS` from `claude --print --help`
    when the CLI surface changes."""

    # Flags verified present in `claude --print --help` (v2.1.185; `--verbose`
    # re-read on v2.1.299). Any flag the runner constructs must be in this set,
    # or it will be rejected at arg-parse.
    _LIVE_CLI_FLAGS = frozenset({"--print", "--output-format", "--verbose", "--setting-sources"})

    def _minimal_scenario(self, tmp_path):
        from textwrap import dedent
        path = tmp_path / "BCE-cmd.yaml"
        path.write_text(
            dedent(
                """\
                id: BCE-cmd
                description: cmd-construction probe
                in_scope: true
                verifies: cmd build
                setup: {}
                trigger:
                  type: prompt
                  content: hello
                expected_receiver_behavior:
                  max_turns: 1
                """
            ),
            encoding="utf-8",
        )
        return path

    def test_no_working_dir_flag_and_cwd_passed(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from bench.end_to_end import runner

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            return SimpleNamespace(stdout="", returncode=0, stderr="")

        monkeypatch.setattr(runner, "_resolve_claude_cli", lambda: "/fake/claude")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)

        work_dir = tmp_path / "wd"
        runner.run_scenario(
            self._minimal_scenario(tmp_path),
            work_dir=work_dir,
            keep_work_dir=True,
        )

        assert "cmd" in captured, "subprocess.run was never called"
        assert "--working-dir" not in captured["cmd"], (
            f"invalid --working-dir flag still in cmd: {captured['cmd']}"
        )
        assert captured["cwd"] == str(work_dir.resolve()), (
            f"cwd not set to work_dir: {captured['cwd']!r} != "
            f"{str(work_dir.resolve())!r}"
        )

    def test_only_live_cli_flags_in_cmd(self, tmp_path, monkeypatch):
        """Every `--flag` the runner constructs must be one the live `claude`
        CLI accepts. Guards against the `--working-dir`/`--max-turns` class of
        regression where a dropped flag silently makes the bench inoperative."""
        from types import SimpleNamespace

        from bench.end_to_end import runner

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(stdout="", returncode=0, stderr="")

        monkeypatch.setattr(runner, "_resolve_claude_cli", lambda: "/fake/claude")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)

        runner.run_scenario(
            self._minimal_scenario(tmp_path),
            work_dir=tmp_path / "wd",
            keep_work_dir=True,
        )

        flags = [tok for tok in captured.get("cmd", []) if tok.startswith("--")]
        unknown = [f for f in flags if f not in self._LIVE_CLI_FLAGS]
        assert not unknown, (
            f"runner passes flags absent from the live claude CLI: {unknown}. "
            "Update _LIVE_CLI_FLAGS from `claude --print --help`, or remove the flag."
        )

    def test_stream_json_comes_with_verbose(self, tmp_path, monkeypatch):
        """A flag can be live alone and dead in a pair: with `--print`, the CLI
        rejects `--output-format stream-json` without `--verbose` at arg-parse
        (2.1.299: "When using --print, --output-format=stream-json requires
        --verbose"), so every real scenario exited 1 with zero events while the
        allowlist above passed. Dies to: `--verbose` dropped from the argv."""
        from types import SimpleNamespace

        from bench.end_to_end import runner

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(stdout="", returncode=0, stderr="")

        monkeypatch.setattr(runner, "_resolve_claude_cli", lambda: "/fake/claude")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        runner.run_scenario(self._minimal_scenario(tmp_path), work_dir=tmp_path / "wd", keep_work_dir=True)

        cmd = captured["cmd"]
        assert cmd[cmd.index("--output-format") + 1] == "stream-json", cmd
        assert "--print" in cmd and "--verbose" in cmd, cmd

    def test_a_scenario_loads_only_its_own_settings(self, tmp_path, monkeypatch):
        """The run measures the scenario's .claude/settings.json, never the
        maintainer's user scope (a user-scope SessionStart hook once told the
        nested agent to make no edits, so the scenario's protected write never
        happened). Dies to: `--setting-sources project` dropped or widened."""
        from types import SimpleNamespace

        from bench.end_to_end import runner

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(stdout="", returncode=0, stderr="")

        monkeypatch.setattr(runner, "_resolve_claude_cli", lambda: "/fake/claude")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        runner.run_scenario(self._minimal_scenario(tmp_path), work_dir=tmp_path / "wd", keep_work_dir=True)

        cmd = captured["cmd"]
        assert cmd[cmd.index("--setting-sources") + 1] == "project", cmd

    def test_the_bypass_set_is_the_hook_modules_own(self):
        """Derived, never hand-copied: the variable that turns the friction layer
        off is whatever the hook module names. Dies to: the derivation dropped."""
        import importlib.util

        from bench.end_to_end import runner

        path = REPO_ROOT / "tools" / "cc" / "hooks" / "_maintenance_mode.py"
        spec = importlib.util.spec_from_file_location("_e2e_maintenance_mode", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert runner._friction_bypass_vars() == (mod.ENV_VAR,)

    def test_the_child_runs_without_the_bypass_or_a_parent_session(self, tmp_path, monkeypatch):
        """A run launched from a maintenance-mode shell, or from inside a Claude
        Code session, must still measure the scenario's hooks. Dies to: the
        child handed os.environ unscrubbed."""
        from types import SimpleNamespace

        from bench.end_to_end import runner

        for name, value in (("ESPALIER_MAINTENANCE_MODE", "1"), ("CLAUDECODE", "1"),
                            ("CLAUDE_CODE_ENTRYPOINT", "cli"), ("CLAUDE_PROJECT_DIR", str(tmp_path)),
                            ("ESPALIER_STOP_GATE", "light")):
            monkeypatch.setenv(name, value)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["env"] = kwargs.get("env")
            return SimpleNamespace(stdout="", returncode=0, stderr="")

        monkeypatch.setattr(runner, "_resolve_claude_cli", lambda: "/fake/claude")
        monkeypatch.setattr(runner.subprocess, "run", fake_run)
        runner.run_scenario(self._minimal_scenario(tmp_path), work_dir=tmp_path / "wd", keep_work_dir=True)

        env = captured["env"]
        for gone in ("ESPALIER_MAINTENANCE_MODE", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                     "CLAUDE_PROJECT_DIR", "ESPALIER_E2E_BENCH"):
            assert gone not in env, gone
        assert env["ESPALIER_STOP_GATE"] == "light"  # the operator's other knobs pass through
