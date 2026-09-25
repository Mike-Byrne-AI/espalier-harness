"""TP-128: auto-justification from plan metadata.

Pins the auto-compose contract: when an `execution_plan` carries
both top-level `goal` AND `not_doing`, every `mark <i> running`
records an `action_justification` on the active blueprint via the
sibling `cognitive_blueprint justify` subprocess. Both fields are
required together — partial population must fall through to the
existing advisory rather than silently fabricate a default for the
missing field. This prevents the audit-trail from drifting away
from author intent.

The contract also pins the composed `content_hash` format
(`^sha256:[a-f0-9]{64}$`) because the validator subprocess silently
discards records with bare hex, which would make auto-compose a
no-op without the prefix. Pins precedence order:
`--justification-fields` > pre-populated step field > auto-compose >
advisory.

The cmd_mark tests run the real CLI via subprocess (mirrors
test_execution_plan.py style) and assert against the resulting
plan JSON + blueprint JSON written to a tmp_path repo root.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from espalier.cognitive_blueprint import _AJ_HASH_RE, _AJ_MAX_FIELD_CHARS


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "cc" / "execution_plan.py"
BLUEPRINT_SCRIPT = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"

# Derive from the real validator instead of re-declaring the pattern. The espalier
# twin is byte-identical to the tools/cc cognitive_blueprint producer this test drives
# — pinned equal by tests/test_forced_copy_parity::TestActionJustificationHashRegexParity.
HASH_PATTERN = _AJ_HASH_RE


def _load_module():
    spec = importlib.util.spec_from_file_location("execution_plan", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_repo(tmp_path: Path) -> None:
    """Create a minimal pyproject + tools/cc structure so _plan_path()
    resolves under tmp_path (per its repo-root detection at line 47)."""
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "blueprints").mkdir()


def _run(args, cwd, env=None):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=str(cwd), capture_output=True, text=True, env=full_env, encoding="utf-8",
    )


def _seed_active_blueprint(tmp_path: Path) -> Path:
    """Create cc/blueprints/latest.json so cognitive_blueprint justify
    has a target (cmd_justify uses _load_latest which reads latest.json
    and exits 2 if absent)."""
    bp_path = tmp_path / "cc" / "blueprints" / "latest.json"
    bp_path.write_text(
        json.dumps({
            "session_id": "20260526-000001-aaaaaa",
            "started_at": "2026-05-26T00:00:01+00:00",
            "depth": 0,
            "action_justifications": [],
            "reasoning_entries": [],
        }) + "\n", encoding="utf-8")
    return bp_path


# ────────────────────────────────────────────────────────────────────
# 128-B1: cmd_create flag plumbing
# ────────────────────────────────────────────────────────────────────


class TestCreateStoresGoalAndNotDoing:
    def test_top_level_keys_populated(self, tmp_path):
        _bootstrap_repo(tmp_path)
        result = _run(
            ["create", "--task", "T", "--goal", "G", "--not-doing", "N",
             "--steps", "a|b"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        plan = json.loads((tmp_path / "cc" / "execution_plan.json").read_text(encoding="utf-8"))
        assert plan["goal"] == "G"
        assert plan["not_doing"] == "N"


class TestCreateDefaultsAreEmptyString:
    def test_omitted_flags_produce_empty_strings(self, tmp_path):
        _bootstrap_repo(tmp_path)
        result = _run(
            ["create", "--task", "T", "--steps", "a"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        plan = json.loads((tmp_path / "cc" / "execution_plan.json").read_text(encoding="utf-8"))
        assert plan["goal"] == ""
        assert plan["not_doing"] == ""


# ────────────────────────────────────────────────────────────────────
# 128-B2: _compose_phase_justification semantics
# ────────────────────────────────────────────────────────────────────


class TestComposeReturnsDictWhenGoalAndNotDoingPresent:
    def test_six_keys_with_required_membership(self):
        mod = _load_module()
        plan = {"task": "T", "goal": "G", "not_doing": "N"}
        step = {"index": 0, "description": "D"}
        result = mod._compose_phase_justification(plan, step)
        assert result is not None
        assert set(result.keys()) == set(mod._AJ_REQUIRED_KEYS)


class TestComposeReturnsNoneWhenGoalAbsent:
    def test_empty_goal_short_circuits(self):
        mod = _load_module()
        assert mod._compose_phase_justification(
            {"task": "T", "goal": "", "not_doing": "N"},
            {"index": 0, "description": "D"},
        ) is None


class TestComposeReturnsNoneWhenNotDoingAbsent:
    def test_empty_not_doing_short_circuits(self):
        mod = _load_module()
        assert mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": ""},
            {"index": 0, "description": "D"},
        ) is None


class TestComposeContentHashFormat:
    def test_sha256_prefix_required(self):
        mod = _load_module()
        result = mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": "D"},
        )
        assert HASH_PATTERN.match(result["content_hash"]), (
            f"content_hash {result['content_hash']!r} does not match "
            "^sha256:[a-f0-9]{64}$ — validator subprocess would reject")


class TestComposeIsDeterministic:
    def test_same_inputs_same_hash(self):
        mod = _load_module()
        a = mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": "D"},
        )
        b = mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": "D"},
        )
        assert a["content_hash"] == b["content_hash"]


# ────────────────────────────────────────────────────────────────────
# 128-B3: cmd_mark integration
# ────────────────────────────────────────────────────────────────────


class TestMarkRunningAutoComposesWhenPlanHasBothFields:
    def test_blueprint_appended_with_sha256_hash(self, tmp_path):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        r1 = _run(
            ["create", "--task", "T", "--goal", "ship TP-128",
             "--not-doing", "no scope creep", "--steps", "phase-a"],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        r2 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
        assert len(bp["action_justifications"]) == 1, bp["action_justifications"]
        entry = bp["action_justifications"][0]
        assert entry["goal"] == "ship TP-128"
        assert entry["not_doing"] == "no scope creep"
        assert HASH_PATTERN.match(entry["content_hash"])


class TestMarkRunningExplicitFieldsTakePrecedence:
    def test_explicit_wins_over_auto_compose(self, tmp_path):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        r1 = _run(
            ["create", "--task", "T", "--goal", "AUTO-GOAL",
             "--not-doing", "AUTO-ND", "--steps", "phase-a"],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        explicit_hash = "sha256:" + "0" * 64
        r2 = _run([
            "mark", "0", "running",
            "--justification-fields",
            "goal=EXPLICIT-GOAL", "step_rationale=R",
            "expected_outcome=E", "not_doing=EXPLICIT-ND",
            "tool=Edit", f"content_hash={explicit_hash}",
        ], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
        assert len(bp["action_justifications"]) == 1
        assert bp["action_justifications"][0]["goal"] == "EXPLICIT-GOAL"
        assert bp["action_justifications"][0]["not_doing"] == "EXPLICIT-ND"


class TestMarkRunningAdvisoryWhenNoGoalAndNoFields:
    def test_advisory_fires_blueprint_unchanged(self, tmp_path):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        # No --goal / --not-doing: plan has empty-string defaults.
        r1 = _run(
            ["create", "--task", "T", "--steps", "phase-a"],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        r2 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr
        assert "starting without" in r2.stderr, (
            f"expected advisory text in stderr, got: {r2.stderr!r}")
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
        assert bp["action_justifications"] == []


class TestMarkRunningAdvisoryWhenGoalButNotNotDoing:
    def test_partial_metadata_falls_through_to_advisory(self, tmp_path):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        r1 = _run(
            ["create", "--task", "T", "--goal", "have-goal",
             "--steps", "phase-a"],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        r2 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr
        assert "starting without" in r2.stderr
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
        assert bp["action_justifications"] == []


class TestMarkRunningStepActionJustificationStillRespected:
    def test_pre_populated_step_field_bypasses_auto_compose(self, tmp_path):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        # Create plan WITHOUT goal but manually inject step's action_justification.
        r1 = _run(
            ["create", "--task", "T", "--steps", "phase-a"],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        plan_path = tmp_path / "cc" / "execution_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["steps"][0]["action_justification"] = {
            "goal": "STEP-LEVEL", "step_rationale": "R",
            "expected_outcome": "E", "not_doing": "ND",
            "tool": "Bash",
            "content_hash": "sha256:" + "a" * 64,
        }
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        r2 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
        assert len(bp["action_justifications"]) == 1
        assert bp["action_justifications"][0]["goal"] == "STEP-LEVEL"


# ────────────────────────────────────────────────────────────────────
# A refused justification must not be recorded as if it were accepted
# ────────────────────────────────────────────────────────────────────


class TestRefusedJustificationIsNotRecordedOnTheStep:
    """The plan must not assert a justification the validator rejected.

    ``post_write_check``'s matcher gates on action_justification PRESENCE, so a
    step carrying a refused payload reads as compliant while the blueprint --
    the durable audit trail -- has nothing. The two records then disagree, and
    the reassuring one is the one a reviewer meets first. Measured on this repo
    2026-08-13: a live plan step carried a 635-char step_rationale that the
    500-char cap had already refused.
    """

    def test_step_carries_no_justification_when_the_validator_refuses(
        self, tmp_path
    ):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        r1 = _run(
            ["create", "--task", "T", "--steps", "phase-a"], cwd=tmp_path, env=env
        )
        assert r1.returncode == 0, r1.stderr

        # A bare-hex content_hash is refused by the validator (it requires the
        # `sha256:` prefix). Any refusal reason would do; this one is independent
        # of the field-length clamp so the two behaviours stay separately pinned.
        r2 = _run(
            [
                "mark", "0", "running",
                "--justification-fields",
                "goal=G", "step_rationale=R", "expected_outcome=E",
                "not_doing=ND", "tool=Bash", "content_hash=" + "a" * 64,
            ],
            cwd=tmp_path, env=env,
        )
        assert r2.returncode == 0, r2.stderr

        step = json.loads(
            (tmp_path / "cc" / "execution_plan.json").read_text(encoding="utf-8")
        )["steps"][0]
        assert "action_justification" not in step, (
            "the step kept a justification the validator refused: "
            f"{step.get('action_justification')!r}. A presence check cannot "
            "tell that apart from a recorded one, so the plan certifies "
            "something the blueprint never received."
        )
        assert json.loads(bp_path.read_text(encoding="utf-8"))["action_justifications"] == [], (
            "blueprint recorded a refused justification"
        )
        assert "REFUSED" in r2.stderr, (
            "a refusal must be reported, not absorbed -- the step is now "
            f"running with no justification at all. stderr: {r2.stderr!r}"
        )


class TestMalformedPlanMetadataTakesTheAdvisoryPath:
    """A blank composed field is a bad PLAN, not a bad justification.

    The validator refuses prose that is empty after ``.strip()``, so a doubled pipe
    in ``--steps`` or a whitespace-only ``--goal`` used to arrive as a REFUSAL --
    telling the operator to fix a payload when the plan is what is malformed, and
    (after the refusal path landed) under a banner that names the wrong remedy.
    """

    def test_blank_description_composes_nothing(self):
        mod = _load_module()
        assert mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": "   "},
        ) is None

    def test_whitespace_only_goal_composes_nothing(self):
        mod = _load_module()
        assert mod._compose_phase_justification(
            {"task": "T", "goal": "   ", "not_doing": "N"},
            {"index": 0, "description": "D"},
        ) is None

    def test_non_string_description_does_not_crash_the_clamp(self):
        mod = _load_module()
        result = mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": 42},
        )
        assert result is not None and result["step_rationale"] == "42"

    def test_the_advisory_not_the_refusal_banner_is_printed(self, tmp_path):
        _bootstrap_repo(tmp_path)
        _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        _run(["create", "--task", "T", "--goal", "G", "--not-doing", "N",
              "--steps", "a||b"], cwd=tmp_path, env=env)
        result = _run(["mark", "1", "running"], cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr
        assert "REFUSED" not in result.stderr, (
            "a malformed plan was reported as a refused justification, which sends "
            f"the operator to fix the wrong thing. stderr: {result.stderr!r}"
        )
        assert "without action_justification" in result.stderr, (
            f"expected the advisory naming the real remedy; got {result.stderr!r}"
        )


class TestComposeHashIsOverTheRawDescription:
    """Pins the choice so a clamped entry does not later look like corruption."""

    def test_clamped_rationale_does_not_reproduce_the_hash(self):
        import hashlib

        mod = _load_module()
        long_desc = "D" * (_AJ_MAX_FIELD_CHARS + 400)
        result = mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": long_desc},
        )
        raw = hashlib.sha256(f"T|0|{long_desc}".encode()).hexdigest()
        assert result["content_hash"] == f"sha256:{raw}", (
            "the hash is documented as identifying the step via its RAW description"
        )
        from_recorded = hashlib.sha256(
            f"T|0|{result['step_rationale']}".encode()
        ).hexdigest()
        assert result["content_hash"] != f"sha256:{from_recorded}", (
            "if these ever match, the clamp stopped truncating and this pin is moot"
        )


class TestAnUnavailableBlueprintIsNotReadAsARefusal:
    """Re-marking a step running must not delete an ALREADY-ACCEPTED justification.

    ``justify`` once exited 2 both for "the validator refused this" and for "there
    is no active session", so the planner could not tell them apart and dropped the
    step's justification on either. The second says nothing about the payload: the
    blueprint may already hold it. Dropping there inverts the failure this whole
    contract exists to prevent -- the plan then claims LESS than the blueprint, and
    the two still disagree.

    The trigger is the documented resume step (`mark <i> running` a second time,
    per .claude/commands/implement-pack.md), and nothing in the suite marked a step
    running twice, so the only path where a payload exists to destroy was unwalked.
    """

    def test_accepted_justification_survives_a_remark_with_no_blueprint(
        self, tmp_path
    ):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        r1 = _run(
            ["create", "--task", "T", "--goal", "G", "--not-doing", "N",
             "--steps", "phase-a"],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        r2 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr

        plan_path = tmp_path / "cc" / "execution_plan.json"
        accepted = json.loads(plan_path.read_text(encoding="utf-8"))["steps"][0].get(
            "action_justification"
        )
        assert accepted is not None, "precondition: first mark should have recorded"
        assert len(json.loads(bp_path.read_text(encoding="utf-8"))["action_justifications"]) == 1

        # The blueprint goes away -- rotated, a fresh `claude -p`, session_start not
        # yet run. The operator resumes exactly as the command body instructs.
        bp_path.rename(bp_path.with_name("away.json"))
        r3 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r3.returncode == 0, r3.stderr

        step = json.loads(plan_path.read_text(encoding="utf-8"))["steps"][0]
        assert step.get("action_justification") == accepted, (
            "an accepted, blueprint-recorded justification was destroyed because "
            "the blueprint was unavailable on a later mark. Unavailability "
            "validated nothing -- it is not evidence against the payload."
        )
        assert "REFUSED" not in r3.stderr, (
            "an unavailable blueprint was reported as a refusal, which tells the "
            f"operator to fix a payload that is fine. stderr: {r3.stderr!r}"
        )


class TestLongStepDescriptionStillYieldsAJustification:
    """A carefully-written step must not lose its audit trail for being long.

    The composed rationale is the step description verbatim, and this repo's
    pack conventions put files, proof and rollback in that one string -- so
    before the clamp the relationship was inverted: the more thorough the step,
    the more certainly it overflowed the cap and was refused outright.
    """

    def test_composed_fields_fit_the_cap_and_mark_the_cut(self):
        # Cap comes from the VALIDATOR, which owns it and predates the planner's
        # forced copy. Keying on the planner's own constant would make this red
        # with AttributeError before the fix -- proving the constant is new
        # rather than proving the overflow was real.
        mod = _load_module()
        long_desc = "D" * (_AJ_MAX_FIELD_CHARS + 400)
        result = mod._compose_phase_justification(
            {"task": "T", "goal": "G", "not_doing": "N"},
            {"index": 0, "description": long_desc},
        )
        for field in ("goal", "step_rationale", "expected_outcome", "not_doing"):
            assert len(result[field]) <= _AJ_MAX_FIELD_CHARS, (
                f"{field} is {len(result[field])} chars against a "
                f"{_AJ_MAX_FIELD_CHARS} cap -- the validator refuses it and "
                "the step runs unjustified"
            )
        assert result["step_rationale"] != long_desc, (
            "an over-cap rationale was passed through unchanged"
        )
        assert "clamped" in result["step_rationale"], (
            "a clamped field must say it was cut, or a reader cannot tell a "
            "short rationale from a truncated one"
        )

    def test_the_long_step_is_actually_recorded_end_to_end(self, tmp_path):
        _bootstrap_repo(tmp_path)
        bp_path = _seed_active_blueprint(tmp_path)
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        long_desc = "D" * (_AJ_MAX_FIELD_CHARS + 400)
        r1 = _run(
            ["create", "--task", "T", "--goal", "G", "--not-doing", "N",
             "--steps", long_desc],
            cwd=tmp_path, env=env,
        )
        assert r1.returncode == 0, r1.stderr
        r2 = _run(["mark", "0", "running"], cwd=tmp_path, env=env)
        assert r2.returncode == 0, r2.stderr
        assert len(json.loads(bp_path.read_text(encoding="utf-8"))["action_justifications"]) == 1, (
            "a long step description produced no blueprint record at all; "
            f"stderr: {r2.stderr!r}"
        )
