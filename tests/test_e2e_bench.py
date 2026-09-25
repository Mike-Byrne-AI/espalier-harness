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
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}


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


class TestNoRepeatOf:
    def test_fail_when_target_retried(self):
        events = parse_stream_json(_stream_lines(
            _system("Write blocked"),
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
        v = evaluate(s, Transcript(parse_stream_json("")))
        assert v.overall == VERDICT_FAIL


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

    # Flags verified present in `claude --print --help` (v2.1.185). Any flag the
    # runner constructs must be in this set, or it will be rejected at arg-parse.
    _LIVE_CLI_FLAGS = frozenset({"--print", "--output-format"})

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
