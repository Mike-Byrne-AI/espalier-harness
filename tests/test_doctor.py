# slow-exempt: the only child processes are three git plumbing calls (init,
# add, commit) in TestDoctorWithholdsTrackedGitignoreEntries, which needs a
# REAL repo because `_tracked_conflicts` answers from `git ls-files` and the
# DEF-11 withheld state is unreachable without one. Measured 2026-08-26:
# 0.48s for all three tests against 14.91s for the module, so moving 112
# tests out of the fast slice would buy nothing. Same shape as the exemption
# in test_catalog_self_consistency.py and test_doc_regions.py.
"""Tests for ``espalier.doctor.run_doctor_check`` — the live-state
verification command invoked by the release ``doctor`` CI step and
the ``/status`` slash command.

Pins both the happy path (fully populated ``harness_repo`` returns a
non-fail status) and the failure paths (missing
``.claude/settings.json`` or ``cc/LIVE_SURFACE.md`` reports
``status=fail``). Without this contract a refactor to
``surface_contract`` or the required-init-files list could silently
let doctor report PASS on a half-installed harness, masking adopter
setup failures from the release gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

import pytest
import zipfile

from espalier import surface_contract
from espalier.cli import cmd_init
from espalier.doctor import run_doctor_check

from tests._symlink_support import requires_symlink


def _real_integrity():
    """The live ``tools/cc/hooks/_integrity`` module, via doctor's own bridge."""
    from espalier._integrity_bridge import load_integrity_module

    return load_integrity_module()


class _IntegrityStub:
    """Base for the fake integrity modules the doctor tests monkeypatch in.

    doctor reads sentinel CONSTANTS off the module as well as calling
    ``verify_integrity``, so a stub defining only the method is an incomplete
    fake and crashes with AttributeError. Delegating every other attribute to
    the real module means a stub cannot drift from the producer, and a
    constant added to the seam later needs no edit here.
    """

    def __getattr__(self, name):
        return getattr(_real_integrity(), name)


class TestDoctorPass:
    def test_pass_on_clean_harness_repo(self, harness_repo):
        """Fully populated harness_repo → status is not fail."""
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] in ("pass", "warn")

    def test_skip_self_host_flag(self, harness_repo):
        """skip_self_host=True marks the self_host check as skipped."""
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["checks"]["self_host"]["status"] == "skipped"

    def test_load_bearing_tool_warning_is_self_host_gated(self, harness_repo, monkeypatch):
        """TP-266 Fix 5 earn-the-red: the load-bearing external-tool loop (ruff)
        must fire only on the self-host repo. ruff ships in espalier's own dev
        extras and its CI gate is `if: is_source == 'true'`, so a ruff-less
        `pip install` adopter's headline doctor status must stay `pass` — a
        missing-ruff warning on THEIR machine is friction, not signal. RED
        before: the loop ran unconditionally, so a non-self-host repo with ruff
        absent gained the warning. GREEN after: gated on is_self_host_repo, the
        warning is absent for the adopter and still present for self-host.

        Simulates ruff-absent by stubbing the tool probe, and controls the
        repo classification directly so the test does not depend on whether
        the temp fixture happens to read as self-host."""
        sentinel = "load-bearing external tool 'ruff' not found"
        monkeypatch.setattr(
            "espalier.doctor._check_external_tool",
            lambda name, hint: [sentinel] if name == "ruff" else [],
        )

        # Adopter (non-self-host): a ruff-absent warning must NOT appear.
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda p: False)
        adopter = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any(sentinel in w for w in adopter["warnings"]), (
            f"ruff-absent warning leaked to a non-self-host adopter: "
            f"{adopter['warnings']!r}"
        )

        # Self-host: the ruff-absent warning is real signal and must remain.
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda p: True)
        selfhost = run_doctor_check(harness_repo, skip_self_host=True)
        assert any(sentinel in w for w in selfhost["warnings"]), (
            f"self-host repo lost its ruff-absent warning: {selfhost['warnings']!r}"
        )


class TestDoctorOwnership:
    def test_fallback_harness_owned_roots_derives_from_constant(
        self, harness_repo, monkeypatch
    ):
        """1-A earn-the-red: the non-self-host fallback ownership dict must read
        ``harness_owned_roots`` from the ``managed_paths.HARNESS_OWNED_ROOTS``
        canon, not a hard-copied ``[".claude", "cc", "tools/cc"]`` literal — one
        owner per fact (STANDING_PRINCIPLES §8). Force the fallback branch (no
        plan, non-self-host, so ``not (plan or is_self_host_repo(repo_root))``)
        and monkeypatch the constant to add a sentinel root; doctor's report must
        reflect it. RED before: the fallback hard-copied the literal and ignored
        the constant, so the sentinel never appeared. GREEN after: the fallback
        derives ``list(HARNESS_OWNED_ROOTS)``.
        """
        # Force the fallback branch: not (plan or is_self_host_repo(repo_root)).
        monkeypatch.setattr("espalier.doctor._load_plan", lambda repo_root: None)
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda p: False)
        # A sentinel the hard-copied literal can never contain.
        monkeypatch.setattr(
            "espalier.doctor.HARNESS_OWNED_ROOTS",
            (".claude", "cc", "tools/cc", "SENTINEL_ROOT"),
        )
        result = run_doctor_check(harness_repo, skip_self_host=True)
        # Confirm we actually reached the non-self-host fallback dict.
        assert result["ownership"]["mode"] == "none", (
            f"expected the non-self-host fallback ownership dict, got: "
            f"{result['ownership']!r}"
        )
        assert "SENTINEL_ROOT" in result["ownership"]["harness_owned_roots"], (
            f"doctor's fallback harness_owned_roots ignored the "
            f"HARNESS_OWNED_ROOTS canon (hard-copied literal?): "
            f"{result['ownership']['harness_owned_roots']!r}"
        )


class TestDoctorFailures:
    def test_fail_when_settings_json_missing(self, harness_repo):
        """Missing .claude/settings.json → status is fail."""
        (harness_repo / ".claude" / "settings.json").unlink()
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"

    def test_fail_on_live_kill_switch_even_when_fully_wired(self, harness_repo):
        """#2 earn-the-red: a ``disableAllHooks: true`` kill-switch in the LIVE
        settings silences every governance gate at runtime, yet the wiring
        oracle reads a fully-wired repo as green. Doctor must consult the
        value-marker kill-switch and FAIL — never report 'safe to proceed'
        while all enforcement is off. Pre-fix (no kill-switch consult) the
        fully-wired harness_repo doctor stays non-fail."""
        settings = harness_repo / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["disableAllHooks"] = True  # fully wired AND killed
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("kill-switch" in f.lower() for f in result["failures"]), (
            f"doctor did not surface the live kill-switch: {result['failures']!r}"
        )

    def test_fail_on_bypass_permissions_kill_switch(self, harness_repo):
        """#2 sister marker: ``permissions.defaultMode == bypassPermissions``
        is the second value-marker kill-switch and must also FAIL doctor."""
        settings = harness_repo / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data.setdefault("permissions", {})["defaultMode"] = "bypassPermissions"
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("kill-switch" in f.lower() for f in result["failures"]), result["failures"]

    def test_no_kill_switch_failure_on_clean_wired_settings(self, harness_repo):
        """#2 negative: the fully-wired harness_repo with NO kill-switch must
        not gain a spurious kill-switch failure."""
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any("kill-switch" in f.lower() for f in result["failures"]), (
            f"spurious kill-switch failure on clean settings: {result['failures']!r}"
        )


class TestBenignHooklessKillSwitch:
    """#3: ``_is_benign_hookless_settings`` must not wave through a settings
    file carrying a value-marker kill-switch — a 'brought-your-own, run
    merge-settings' remedy would wire hooks the kill-switch still disables."""

    def test_kill_switched_settings_is_not_benign(self, tmp_path):
        from espalier.doctor import _is_benign_hookless_settings
        s = tmp_path / "settings.json"
        s.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
        assert _is_benign_hookless_settings(s) is False

    def test_bypass_permissions_settings_is_not_benign(self, tmp_path):
        from espalier.doctor import _is_benign_hookless_settings
        s = tmp_path / "settings.json"
        s.write_text(
            json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}),
            encoding="utf-8",
        )
        assert _is_benign_hookless_settings(s) is False

    def test_genuine_brought_your_own_still_benign(self, tmp_path):
        """Negative: a real brought-your-own settings (no hooks key, no
        kill-switch) stays benign so the soft onboarding line is preserved."""
        from espalier.doctor import _is_benign_hookless_settings
        s = tmp_path / "settings.json"
        s.write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Read"]}}),
                     encoding="utf-8")
        assert _is_benign_hookless_settings(s) is True

    def test_fail_on_integrity_drift(self, harness_repo, monkeypatch):
        # C (CV2 F4): a present-but-neutered protected file (integrity drift) must
        # make doctor FAIL — previously doctor never consulted the manifest and
        # reported "safe to proceed" while `integrity verify` reported drift.
        from espalier import doctor as doctor_module

        class _Drifted(_IntegrityStub):
            def verify_integrity(self, root):
                return (False, ["tools/cc/hooks/write_guard.py"])

        monkeypatch.setattr(doctor_module, "load_integrity_module", lambda: _Drifted())
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("integrity drift" in f for f in result["failures"])

    def test_absent_integrity_manifest_does_not_false_red(self, harness_repo, monkeypatch):
        # C (CV2 F4): the MANIFEST_ABSENT sentinel is NOT edit-drift — a
        # never-refreshed repo must NOT get a new false-RED (matches cmd_integrity).
        from espalier import doctor as doctor_module

        class _NoManifest(_IntegrityStub):
            def verify_integrity(self, root):
                return (False, [_real_integrity().MANIFEST_ABSENT])

        monkeypatch.setattr(doctor_module, "load_integrity_module", lambda: _NoManifest())
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any("integrity drift" in f for f in result["failures"])

    def test_doctor_survives_a_version_skewed_integrity_module(
        self, harness_repo, monkeypatch
    ):
        """A PRE-SPLIT _integrity.py must not crash doctor.

        The absent/unreadable split gave the engine two module ATTRIBUTES to
        read off a module loaded by file path, and the two can be skewed:
        `git checkout <older-sha> -- tools/` during a bisect is enough. The
        block that reads them catches OSError, not AttributeError, and its
        stated contract is "no integrity signal, not a crash" — in a command
        CI invokes at .github/workflows/test.yml.

        Driven before the fix: raises AttributeError on a healthy manifest AND
        a corrupt one, because on this repo the swapped file is itself
        manifest-covered, so verification always reports drift — the exact
        branch that reads the attribute.
        """
        from espalier import doctor as doctor_module

        class _PreSplit:  # deliberately NO MANIFEST_ABSENT / MANIFEST_UNREADABLE
            def verify_integrity(self, root):
                return (False, ["<manifest missing>"])

        monkeypatch.setattr(
            doctor_module, "load_integrity_module", lambda: _PreSplit()
        )
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] in {"pass", "warn", "fail"}

    def test_doctor_survives_a_neutered_integrity_module(
        self, harness_repo, monkeypatch
    ):
        """The case the bridge backfill CANNOT cover, hence the widened guard.

        The pack's own motivating scenario is a governance file truncated to
        empty. Applied to the verifier itself, the module has no
        `verify_integrity` at all — no backfill helps, so the `except` has to
        catch AttributeError for doctor to stay fail-honest.
        """
        from espalier import doctor as doctor_module

        class _Neutered:  # an empty _integrity.py
            pass

        monkeypatch.setattr(
            doctor_module, "load_integrity_module", lambda: _Neutered()
        )
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] in {"pass", "warn", "fail"}
        assert not any("integrity drift" in f for f in result["failures"]), (
            "a module that could not be read must yield NO integrity signal, "
            "not a fabricated drift finding"
        )

    def test_unreadable_integrity_manifest_fails_loud(self, harness_repo, monkeypatch):
        """LANEB-02 earn-the-red: a corrupt manifest must NOT ride the
        fresh-checkout exemption.

        Pre-fix, `_load_manifest_unlocked` returned None for an absent manifest
        AND for one that was truncated, non-dict, unreadable or symlinked, so
        `verify_integrity` emitted one sentinel for both — and doctor's
        (correct) exemption for the absent case silently forgave the rest.
        A repo whose tamper-detection was blind reported status=warn, exit 0,
        failures=[]. This is the other half of the pair above: absent stays
        exempt, unreadable must be loud, and only pinning BOTH keeps the
        exemption honest.
        """
        from espalier import doctor as doctor_module

        class _Unreadable(_IntegrityStub):
            def verify_integrity(self, root):
                return (False, [_real_integrity().MANIFEST_UNREADABLE])

        monkeypatch.setattr(doctor_module, "load_integrity_module", lambda: _Unreadable())
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        failures = " ".join(result["failures"])
        assert "unreadable" in failures
        # The corruption must be NAMED. Reusing the drift wording would claim a
        # protected file "changed out of band" when nothing was compared at
        # all, sending the operator hunting for an edit that never happened.
        assert "changed out of band" not in failures
        assert any(
            "integrity refresh" in s for s in result.get("next_steps", [])
        ), "an unreadable manifest must be rebuilt, not diffed"

    def test_fail_when_required_init_file_missing(self, harness_repo):
        """Missing cc/LIVE_SURFACE.md → status is fail."""
        (harness_repo / "cc" / "LIVE_SURFACE.md").unlink()
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"

    def test_uninitialized_when_no_surface(self, tmp_path):
        """Empty repo → status is 'uninitialized', not 'fail' (TP-UX-01).

        A fresh, never-initialized repo is the expected starting condition,
        not a failure. doctor returns the dedicated 'uninitialized' status
        with a friendly next_steps pointer rather than a failures wall.
        """
        result = run_doctor_check(tmp_path, skip_self_host=True)
        assert result["status"] == "uninitialized"
        assert not result.get("failures")
        # TP-391 4-B: substring membership on `-m espalier init .` stays GREEN on a hint
        # rendered with no interpreter token at all (`-m espalier init .`), which is the
        # regression the sibling assertion in test_init.py exists to catch. Require a
        # non-space token immediately before ` -m ` -- interpreter-agnostic, so both
        # `python` and `python3` pass.
        next_steps = result.get("next_steps", [])
        assert any(re.search(r"[\w./-]+ -m espalier init \.", s) for s in next_steps), (
            "doctor's uninitialized next_steps must hint `<interp> -m espalier init .`; "
            f"a bare or interpreter-less form is command-not-found in a fusion.\n{next_steps}"
        )


class TestDoctorStructure:
    def test_next_steps_populated_on_failure(self, tmp_path):
        result = run_doctor_check(tmp_path, skip_self_host=True)
        assert len(result["next_steps"]) > 0

    def test_next_steps_populated_on_fingerprint_drift_warning(self, harness_repo):
        """A ``warn`` verdict must not be the one that returns an empty action list.

        ``next_steps`` was populated only inside the failure branches and under
        ``status == "pass"``. Fingerprint drift is the most common non-pass
        verdict, so the one verdict that asks the operator to act was the one
        telling them nothing to do.
        """
        saved = harness_repo / "reports" / "repo_fingerprint.json"
        data = json.loads(saved.read_text(encoding="utf-8"))
        data["languages"] = ["cobol"]
        saved.write_text(json.dumps(data), encoding="utf-8")

        result = run_doctor_check(harness_repo, skip_self_host=True)

        assert "saved reports differ from fresh inference" in result["warnings"]
        assert result["status"] == "warn", result["status"]
        assert result["next_steps"], "warn verdict returned an empty action list"
        assert any("fingerprint" in s for s in result["next_steps"]), result["next_steps"]

    def test_ownership_summary_present(self, harness_repo):
        result = run_doctor_check(harness_repo, skip_self_host=True)
        ownership = result["ownership"]
        assert "harness_owned_roots" in ownership
        assert "managed_paths" in ownership

    def test_ownership_names_a_deployed_skill(self, harness_repo):
        """A skill init deployed is harness-owned in the doctor's report the
        way its agents and commands are. Driven 2026-09-11 on a fresh init:
        nine skill files on disk, nine named by clean-generated, none in
        ownership.managed_paths, so the adopter read them as their own
        (DEF-532)."""
        skill = harness_repo / ".claude" / "skills" / "reflect" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("x", encoding="utf-8")
        result = run_doctor_check(harness_repo, skip_self_host=True)
        ownership = result["ownership"]
        assert ".claude/skills/reflect/SKILL.md" in ownership["managed_paths"]
        assert ".claude/skills/reflect/SKILL.md" in ownership["managed_settings"]

    def test_required_list_sourced_from_contract(self, harness_repo):
        """Pack 2-C — required-file list comes from surface_contract."""
        result = run_doctor_check(harness_repo, skip_self_host=True)
        required = result["checks"]["presence"]["required"]
        for path in surface_contract.get_required_init_files():
            assert path in required


class TestDoctorFreshInit:
    """Pack 2-C — fresh successful init must produce status=pass."""

    def _run_init(self, repo: Path) -> int:
        # `write_gitignore=True` is the DECLARED CLI default: `--no-write-gitignore`
        # is `store_false`, so argparse hands cmd_init True unless the operator
        # opts out. A hand-built Namespace that omits the attribute gets the
        # opposite -- espalier/cli.py::cmd_init reads it through a getattr whose
        # fallback disagrees with that declared default (ledger row DEF-399b) --
        # so this fixture must state the flag rather than inherit it. Without it
        # the "fresh init" leaves .gitignore unwritten, which is not what a real
        # `espalier init` does.
        args = argparse.Namespace(
            repo=str(repo), config=None, write_gitignore=True,
        )
        return cmd_init(args)

    def test_fresh_init_then_doctor_is_pass(self, tmp_path):
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        self._run_init(tmp_path)
        result = run_doctor_check(tmp_path, skip_self_host=True)
        assert result["status"] == "pass", (
            f"Expected pass after fresh init; got {result['status']}. "
            f"Reason: {result['primary_reason']}"
        )


class TestDoctorThreeWayOwnership:
    """Pack 2-C — doctor reports current / stale / missing-from-plan paths."""

    def test_ownership_delta_keys_present(self, harness_repo):
        result = run_doctor_check(harness_repo, skip_self_host=True)
        delta = result["ownership_delta"]
        assert "current_managed_paths" in delta
        assert "stale_saved_paths" in delta
        assert "missing_from_saved_plan" in delta

    def test_stale_saved_paths_detected(self, harness_repo):
        """Saved plan references a generated_doc that no longer exists → stale.

        TP-31: agents no longer deploy by default, so the old test that added
        an agent to the plan and checked for stale agent path no longer
        reflects real behavior. Using generated_docs for stale detection.
        """
        plan_path = harness_repo / "reports" / "harness_config.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan.setdefault("generated_docs", [])
        plan["generated_docs"].append("cc/NONEXISTENT.md")
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        result = run_doctor_check(harness_repo, skip_self_host=True)
        stale = result["ownership_delta"]["stale_saved_paths"]
        assert "cc/NONEXISTENT.md" in stale

    def test_load_plan_tolerates_non_utf8(self, tmp_path):
        """TP-190: a non-UTF-8 / BOM-prefixed harness_config.json raises
        UnicodeDecodeError (a ValueError, NOT JSONDecodeError); _load_plan must
        return None, not traceback through run_doctor_check."""
        from espalier.doctor import _load_plan
        reports = tmp_path / "reports"
        reports.mkdir()
        # 0x80 is an invalid UTF-8 start byte → read_text(encoding="utf-8") raises.
        (reports / "harness_config.json").write_bytes(b"\x80\x81 not utf-8")
        assert _load_plan(tmp_path) is None  # degrades, no traceback

    def test_missing_from_saved_plan_detected(self, harness_repo):
        """A hook exists on disk but is not in the saved plan → drift."""
        # Fixture has hooks on disk but plan has agents=[] and generated_docs=[]
        # plus hooks=[], so everything discovered is "missing from plan."
        hooks_dir = harness_repo / "tools" / "cc" / "hooks"
        (hooks_dir / "task_router.py").write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8"
        )
        result = run_doctor_check(harness_repo, skip_self_host=True)
        missing = result["ownership_delta"]["missing_from_saved_plan"]
        assert isinstance(missing, list)
        # TP-191 W7: behavioral assert — the hook just written to disk (and absent
        # from the saved plan) must actually appear in the missing list, not just
        # "missing is a list of something". The pre-fix shape-only check passed
        # even if the drift detector silently returned [].
        assert any("task_router" in str(m) for m in missing), (
            f"task_router.py on disk but not flagged missing from plan: {missing}"
        )

    def test_current_managed_paths_reports_disk_not_plan(self, tmp_path):
        """TP-197: current_managed_paths reflects DISK reality (every deployed
        agent), while missing_from_saved_plan stays plan-based so a tier-deployed
        agent the saved plan omits does NOT spuriously warn on a fresh init."""
        from espalier.doctor import _three_way_ownership
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        for name in ("alpha", "beta"):
            (agents_dir / f"{name}.md").write_text("x", encoding="utf-8")
        # Saved plan lists only alpha (fingerprint-recommended); beta is tier-deployed.
        plan = {"agents": [{"name": "alpha"}], "generated_docs": [], "hooks": []}
        delta = _three_way_ownership(tmp_path, plan)
        # Disk reality in the report: beta is named even though the plan omits it.
        assert ".claude/agents/beta.md" in delta["current_managed_paths"]
        # ...but the plan-based drift check does NOT flag beta (no fresh-init noise).
        assert ".claude/agents/beta.md" not in delta["missing_from_saved_plan"]

    def test_current_managed_paths_names_a_deployed_skill(self, tmp_path):
        """A deployed skill is disk reality the report names, and the
        plan-based drift check stays quiet about it: the saved plan carries no
        skills source, so flagging it would warn on every fresh init (DEF-532)."""
        from espalier.doctor import _three_way_ownership
        skill = tmp_path / ".claude" / "skills" / "reflect" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("x", encoding="utf-8")
        plan = {"agents": [], "generated_docs": [], "hooks": []}
        delta = _three_way_ownership(tmp_path, plan)
        assert ".claude/skills/reflect/SKILL.md" in delta["current_managed_paths"]
        assert ".claude/skills/reflect/SKILL.md" not in delta["missing_from_saved_plan"]

    def test_recommended_agent_without_a_packaged_body_is_not_stale(self, tmp_path):
        """DEF-756: the plan builder's OPTIONAL_AGENTS recommends agents no
        engine since TP-31 ships a body for, so their paths were never on disk
        to be "no longer" there. A PACKAGED agent absent from disk stays stale
        (genuine drift), and so does one the current builder no longer
        recommends at all (retired by a newer engine; a re-baseline drops it);
        an unshipped recommendation is reported apart; an adopter-authored
        body at a recommended path is neither."""
        from espalier.doctor import _three_way_ownership
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "code-reviewer.md").write_text("# body\n", encoding="utf-8")
        (agents_dir / "content-reviewer.md").write_text("# the adopter wrote this one\n", encoding="utf-8")
        plan = {
            "agents": [
                {"name": n} for n in (
                    "code-reviewer", "test-writer", "api-reviewer",
                    "content-reviewer", "legacy-reviewer",
                )
            ],
            "generated_docs": [], "hooks": [],
        }
        delta = _three_way_ownership(tmp_path, plan)
        assert delta["stale_saved_paths"] == [
            ".claude/agents/legacy-reviewer.md", ".claude/agents/test-writer.md",
        ]
        assert delta["unshipped_saved_agents"] == [".claude/agents/api-reviewer.md"]

    def test_fresh_init_of_an_api_project_does_not_warn_about_an_unshipped_recommendation(
        self, python_repo, capsys,
    ):
        """DEF-756, the driven instance: the FastAPI fixture trips the
        api-reviewer predicate, so before the oracle fix every fresh init of an
        API project left doctor in warn with two remedies that re-claimed the
        same path. The recommendation is still named, as information."""
        import argparse
        from espalier.cli import cmd_init
        assert cmd_init(argparse.Namespace(repo=str(python_repo), config=None)) == 0
        capsys.readouterr()
        result = run_doctor_check(python_repo, skip_self_host=True)
        assert not any("stale saved-plan" in w for w in result["warnings"]), result["warnings"]
        assert any("api-reviewer" in line for line in result["info"]), result["info"]

    def test_empty_repo_returns_valid_output(self, tmp_path):
        """Empty (uninitialized) repo returns the uninitialized branch shape.

        Per TP-UX-01: empty repos no longer go through the
        ownership_delta / failures pipeline; they return the dedicated
        'uninitialized' status. This test pins the new shape.
        """
        result = run_doctor_check(tmp_path, skip_self_host=True)
        assert result["status"] == "uninitialized"
        assert result.get("message")
        assert isinstance(result.get("next_steps", []), list)


class TestDoctorPrimaryReason:
    """Pack 2-C — primary_reason names a specific category, not a blob."""

    def test_primary_reason_is_non_empty(self, harness_repo):
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["primary_reason"]

    def test_primary_reason_on_empty_repo(self, tmp_path):
        """Empty repo's primary_reason names the uninitialized state (TP-UX-01)."""
        result = run_doctor_check(tmp_path, skip_self_host=True)
        assert "initialized" in result["primary_reason"].lower()


# ── TP-UX-01: friendly first-run output on uninitialized repos ──────────


class TestDoctorUninitializedRepo:
    """`espalier doctor` on an uninitialized repo emits friendly guidance,
    not a JSON failure dump. See TP-UX-01.

    Failure mode this guards against: regression to dumping JSON with
    `"failures": ["missing required managed surface: ..."]` on a fresh
    repo, which reads as 'the tool is broken' to first-time evaluators.
    """

    def _make_fresh_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        return tmp_path

    def test_uninitialized_repo_returns_status_marker(self, tmp_path):
        """run_doctor_check returns a 'uninitialized' status, not failures."""
        repo = self._make_fresh_repo(tmp_path)
        result = run_doctor_check(repo, skip_self_host=True)
        assert result.get("status") == "uninitialized"
        assert not result.get("failures")

    def test_cli_doctor_exit_zero_on_fresh_repo(self, tmp_path):
        """Exit code is 0, not 1, on a fresh repo."""
        import argparse
        from espalier.cli import cmd_doctor
        repo = self._make_fresh_repo(tmp_path)
        args = argparse.Namespace(repo=str(repo), config=None)
        rc = cmd_doctor(args)
        assert rc == 0, f"Expected exit 0 on fresh repo; got {rc}"

    def test_cli_doctor_human_message_on_fresh_repo(self, tmp_path, capsys):
        """The CLI emits plain text containing 'espalier init', not JSON."""
        import argparse
        from espalier.cli import cmd_doctor
        repo = self._make_fresh_repo(tmp_path)
        args = argparse.Namespace(repo=str(repo), config=None)
        cmd_doctor(args)
        out = capsys.readouterr().out
        assert "espalier init" in out, (
            f"Output should mention 'espalier init'. Got:\n{out}"
        )
        assert not out.lstrip().startswith("{"), (
            f"Uninitialized output should be human-readable, not JSON. Got:\n{out}"
        )

    def test_initialized_repo_still_returns_json(self, harness_repo, capsys):
        """Backward compat: initialized repos still get the JSON dump."""
        import argparse
        from espalier.cli import cmd_doctor
        args = argparse.Namespace(
            repo=str(harness_repo), config=None, skip_self_host=True
        )
        cmd_doctor(args)
        out = capsys.readouterr().out
        assert out.lstrip().startswith("{"), (
            f"Initialized repo should still emit JSON. Got:\n{out[:200]}"
        )


class TestDoctorRecoveryForwarding:
    """R10 W2 (R11 coverage): doctor must forward
    ``recover["recommendations"]`` and ``recover["missing"]`` into the
    returned report when recovery status is ``"fail"``. Pre-fix the
    fields were dropped, leaving the operator with only an opaque
    "blocking conditions" string.

    Tested at the source-level by exercising the in-place branch in
    ``run_doctor_check`` directly. ``run_doctor_check`` calls
    ``assess_repo_state`` only when ``has_surface`` is True (the
    initialized-repo branch), so the test reuses the ``harness_repo``
    fixture and monkeypatches ``assess_repo_state``.
    """

    def test_doctor_forwards_recovery_recommendations(self, harness_repo, monkeypatch):
        from espalier.doctor import run_doctor_check
        from espalier import doctor as doctor_module
        fake_recover = {
            "status": "fail",
            "missing": [".espalier/integrity.json", "reports/repo_fingerprint.json"],
            "recommendations": [
                "run `espalier integrity refresh .`",
                "run `espalier fingerprint .`",
            ],
        }
        monkeypatch.setattr(
            doctor_module, "assess_repo_state", lambda root: fake_recover
        )
        report = run_doctor_check(harness_repo, skip_self_host=True)
        next_steps = report.get("next_steps", [])
        failures = report.get("failures", [])
        assert any("integrity refresh" in s for s in next_steps), (
            f"missing 'integrity refresh' in next_steps: {next_steps}"
        )
        assert any("fingerprint" in s for s in next_steps), (
            f"missing 'fingerprint' in next_steps: {next_steps}"
        )
        # The paths are NAMED on the recovery line itself (DEF-786): one
        # line, counted by kind, listing what the assessor found.
        recovery = [f for f in failures if f.startswith("recovery check:")]
        assert len(recovery) == 1, failures
        assert "2 required paths missing" in recovery[0], recovery
        assert ".espalier/integrity.json" in recovery[0], recovery
        assert "reports/repo_fingerprint.json" in recovery[0], recovery
        assert not any("blocking conditions" in f for f in failures), failures

    def test_doctor_does_not_duplicate_init_recommendation(self, harness_repo, monkeypatch):
        """Forwarded recommendation should not duplicate an existing entry.

        We construct a recover that returns the init recommendation. The
        doctor.py wrapper also appends 'espalier init' separately for the
        missing-presence branch — but on harness_repo presence is OK, so
        only the forwarded one should appear. Verify a single occurrence of
        the INITIALIZE recommendation: the required-gitignore remedy names
        `init .` too (a re-run appends the missing entries as a block) and
        is a different step, not a duplicate of this one.
        """
        from espalier.doctor import run_doctor_check
        from espalier import doctor as doctor_module
        fake_recover = {
            "status": "fail",
            "missing": [],
            "recommendations": [
                "run `espalier init <repo>` to initialize the harness",
            ],
        }
        monkeypatch.setattr(
            doctor_module, "assess_repo_state", lambda root: fake_recover
        )
        report = run_doctor_check(harness_repo, skip_self_host=True)
        init_steps = [
            s for s in report.get("next_steps", [])
            if "espalier init" in s and "to initialize the harness" in s
        ]
        assert len(init_steps) == 1, (
            f"init recommendation should appear exactly once, got: {init_steps}"
        )


class TestPythonResolverCheck:
    """TP-130 30-C: warn when the python interpreter named in
    ``.claude/settings.json`` does not resolve on the current host
    (Windows ships ``python.exe``, not ``python3``; macOS may need a
    brew install)."""

    def test_warns_when_python3_missing(self, tmp_path, monkeypatch):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": '
            '[{"command": "python3"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(doctor_module.shutil, "which", lambda x: None)
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        assert any("python3" in i for i in issues)
        assert any("Windows" in i for i in issues)

    def test_passes_when_python3_resolves(self, tmp_path, monkeypatch):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": '
            '[{"command": "python3"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(
            doctor_module.shutil, "which", lambda x: "/usr/bin/python3"
        )
        # Patch the identity probe too, not just `which`. `which` is
        # fabricated here, so `_interpreter_is_python3` would go to the real
        # filesystem and ask whether a made-up `/usr/bin/python3` is a Python 3
        # -- true on this developer's machine and on the Linux runner, false on
        # Windows, which is a test that passes for a reason it never states.
        # The three siblings below already patch this seam; these two were
        # missed when it was introduced.
        monkeypatch.setattr(
            doctor_module, "_interpreter_is_python3",
            lambda path: path == "/usr/bin/python3",
        )
        # Patch the FLOOR seam for the same reason, and it is not the same
        # question (TP-448 Class 3 / DEF-636): identity asks "is this a Python
        # 3", the floor asks "is it one this package runs on". `which` is
        # fabricated, so the real floor probe would execute the host's actual
        # /usr/bin/python3 -- 3.9.6 on stock macOS, below the 3.10 floor. Left
        # unpatched this test passes on a 3.12 host and reds on a stock Mac:
        # the exact "means different things in different places" failure the
        # comment above was written about.
        monkeypatch.setattr(
            doctor_module, "_interpreter_meets_floor",
            lambda path: path == "/usr/bin/python3",
        )
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        assert issues == []

    def test_silent_when_settings_missing(self, tmp_path):
        # No .claude/settings.json — out-of-scope for this check.
        from espalier.doctor import _check_python_resolver
        issues = _check_python_resolver(tmp_path)
        assert issues == []

    def test_silent_on_non_python_command(self, tmp_path, monkeypatch):
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": '
            '[{"command": "bash"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(doctor_module.shutil, "which", lambda x: None)
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        # `bash` not python-like; resolver check ignores it.
        assert issues == []

    # ── The wired name may RESOLVE and still be broken (venv-scoped) ──────

    @staticmethod
    def _fake_venv(tmp_path, name="python"):
        """A venv-shaped tree: `pyvenv.cfg` beside a bin/ holding an executable.

        Fabricated rather than built with `python3 -m venv` on purpose — this
        module is not in conftest._SLOW_FILES and spawns no child process, and
        the predicate under test keys on pyvenv.cfg + PATH, not on a working
        interpreter.
        """
        venv = tmp_path / "venv"
        bindir = venv / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
        # `.exe` on Windows: `shutil.which`'s win32 branch builds
        # `[cmd + ext for ext in PATHEXT]` and only tries the bare name when it
        # already carries a PATHEXT extension -- so a file literally named
        # `python` is never found, the predicate saw an unresolvable name
        # rather than a venv-only one, and the test asserted the wrong branch.
        shim = bindir / (name + ".exe" if os.name == "nt" else name)
        shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shim.chmod(0o755)
        return venv, bindir

    def test_warns_when_wired_name_resolves_only_inside_a_venv(
        self, tmp_path, monkeypatch
    ):
        """The wired name RESOLVES for the shell doctor is standing in, and is
        still broken: it is a virtualenv shim that vanishes with the shell.

        This is the composition the check was blind to — running doctor from
        the venv the install told the operator to activate reported
        `pass -- repo is healthy` on a tree whose every hook was dead.
        """
        _venv, bindir = self._fake_venv(tmp_path)
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python"}]}]}}', encoding="utf-8"
        )
        # The venv is FIRST on PATH, exactly as an activated venv would be,
        # and nothing else supplies `python`.
        monkeypatch.setenv("PATH", str(bindir))
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        from espalier import doctor as doctor_module
        issues = doctor_module._check_python_resolver(tmp_path, settings)

        assert issues, (
            "a venv-scoped interpreter must be reported: it resolves here and "
            "will not resolve for the shell Claude Code is launched from"
        )
        joined = " ".join(issues)
        assert "virtualenv" in joined or "venv" in joined, (
            f"the warning must name the cause as venv-scoped; got: {issues!r}"
        )
        # It must NOT reuse the unresolvable-name remedy: the name DOES
        # resolve, and symlinking to a venv interpreter makes it permanent.
        assert "does not resolve" not in joined, (
            f"wrong cause -- the name resolves; got: {issues!r}"
        )
        assert "symlink" not in joined, (
            f"symlinking to a venv shim makes the breakage permanent; got: {issues!r}"
        )

    def test_warns_when_statusline_interpreter_is_unresolvable(
        self, tmp_path, monkeypatch
    ):
        """statusLine is the 13th interpreter site and was never walked.

        Hooks healthy, statusLine broken -> the check returned [] and doctor
        called the tree healthy.
        """
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [{"command": "python3"}]}]},
            "statusLine": {
                "type": "command",
                "command": 'pythonX "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py"',
            },
        }), encoding="utf-8")
        from espalier import doctor as doctor_module
        monkeypatch.setattr(
            doctor_module.shutil, "which",
            lambda x, path=None: "/usr/bin/python3" if x == "python3" else None,
        )
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        assert any("pythonX" in i for i in issues), (
            f"statusLine interpreter must be checked too; got: {issues!r}"
        )

    def test_silent_when_statusline_absent(self, tmp_path, monkeypatch):
        """A brought-your-own settings.json has no statusLine key at all."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python3"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(
            doctor_module.shutil, "which",
            lambda x, path=None: "/usr/bin/python3",
        )
        # Patch the identity probe too, not just `which`. `which` is
        # fabricated here, so `_interpreter_is_python3` would go to the real
        # filesystem and ask whether a made-up `/usr/bin/python3` is a Python 3
        # -- true on this developer's machine and on the Linux runner, false on
        # Windows, which is a test that passes for a reason it never states.
        # The three siblings below already patch this seam; these two were
        # missed when it was introduced.
        monkeypatch.setattr(
            doctor_module, "_interpreter_is_python3",
            lambda path: path == "/usr/bin/python3",
        )
        # Patch the FLOOR seam for the same reason, and it is not the same
        # question (TP-448 Class 3 / DEF-636): identity asks "is this a Python
        # 3", the floor asks "is it one this package runs on". `which` is
        # fabricated, so the real floor probe would execute the host's actual
        # /usr/bin/python3 -- 3.9.6 on stock macOS, below the 3.10 floor. Left
        # unpatched this test passes on a 3.12 host and reds on a stock Mac:
        # the exact "means different things in different places" failure the
        # comment above was written about.
        monkeypatch.setattr(
            doctor_module, "_interpreter_meets_floor",
            lambda path: path == "/usr/bin/python3",
        )
        assert doctor_module._check_python_resolver(tmp_path, settings) == []

    def test_present_python3_nudges_reinit_not_brew(self, tmp_path, monkeypatch):
        """W6-3 (TP-177): when `python3` IS on PATH but settings wired a
        different name (`python`), the hint must point at re-init / symlink,
        NOT `brew install python` (the real fix is rewiring, not installing)."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": '
            '[{"command": "python"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(
            doctor_module.shutil, "which",
            lambda x: "/usr/bin/python3" if x == "python3" else None,
        )
        # Declare the identity dependency instead of leaning on real filesystem
        # state. Patching only `which` and handing back a fabricated path made
        # this test's outcome depend on whether that exact path is a working
        # interpreter on the machine running the suite -- it is Python 3.9.6 on
        # the author's host and absent on a minimal container, so the same
        # fixture asserted two different things in the two places.
        monkeypatch.setattr(
            doctor_module, "_interpreter_is_python3",
            lambda path: path == "/usr/bin/python3",
        )
        # Patch the FLOOR seam for the same reason, and it is not the same
        # question (TP-448 Class 3 / DEF-636): identity asks "is this a Python
        # 3", the floor asks "is it one this package runs on". `which` is
        # fabricated, so the real floor probe would execute the host's actual
        # /usr/bin/python3 -- 3.9.6 on stock macOS, below the 3.10 floor. Left
        # unpatched this test passes on a 3.12 host and reds on a stock Mac:
        # the exact "means different things in different places" failure the
        # comment above was written about.
        monkeypatch.setattr(
            doctor_module, "_interpreter_meets_floor",
            lambda path: path == "/usr/bin/python3",
        )
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        assert any("python" in i for i in issues)
        joined = " ".join(issues)
        assert "init" in joined or "symlink" in joined, (
            f"present-python3 hint should suggest re-init/symlink: {issues}"
        )
        assert "brew install" not in joined, (
            f"must NOT recommend installing python when python3 exists: {issues}"
        )

    def test_stub_interpreter_is_reported_not_silent(self, tmp_path, monkeypatch):
        """2-C: the CLASS C host. Both names RESOLVE -- so the old
        `elif which(cmd) is None` was False and **no branch fired at all** --
        but neither answers as Python 3. doctor is the only reachable detector
        on such a host (the session-start hook is spawned by the very
        interpreter it would warn about), so silence here is the whole defect.
        """
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(doctor_module.shutil, "which",
                            lambda x: f"/stub/{x}" if x in ("python", "python3") else None)
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        monkeypatch.setattr(doctor_module, "_interpreter_is_python3", lambda path: False)
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        assert issues, "a stub host must not be reported as healthy"
        joined = " ".join(issues)
        assert "/stub/python" in joined, (
            f"the finding must name the path that failed identity: {issues}"
        )
        assert "fails OPEN" in joined or "fail OPEN" in joined, (
            f"the finding must state the consequence, not just the symptom: {issues}"
        )

    def test_stub_python3_does_not_produce_reinit_advice(self, tmp_path, monkeypatch):
        """2-C at `:372`. `py3_present` was `shutil.which("python3") is not None`,
        which a stub satisfies -- so doctor told the operator "`python3` IS on
        PATH, re-run init", which is ACTIVELY WRONG on the one host this check
        exists for. Re-running init re-detects the same stub."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python"}]}]}}', encoding="utf-8"
        )
        from espalier import doctor as doctor_module
        monkeypatch.setattr(doctor_module.shutil, "which",
                            lambda x: f"/stub/{x}" if x in ("python", "python3") else None)
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        monkeypatch.setattr(doctor_module, "_interpreter_is_python3", lambda path: False)
        joined = " ".join(doctor_module._check_python_resolver(tmp_path, settings))
        assert "IS on PATH" not in joined, (
            f"a stub host must not be told a working python3 is present: {joined}"
        )


# ── TP-142 (FM-5 §10.1): doctor count regexes routed through helper ─


class TestCountRegexesUseHardenedHelper:
    """FM-5 §10.1 close: doctor's count-drift checks now route through
    ``audit_accuracy.extract_count_for_label`` so they inherit TP-58's
    hardening (negative lookbehind, ASCII-only digit class, ``re.ASCII``).

    Pre-fix shapes the bare ``\\d+`` matched as false positives:
      * ``v10 hooks`` extracted ``10``
      * ``1.10 hooks`` extracted ``10``
      * ``４ hooks`` (fullwidth digit) extracted ``4``

    Each parametrized case sets up a synthetic CLAUDE.md and the
    requisite hook count so the bare-regex path would have produced a
    spurious mismatch; the new path must report no finding for those
    specific shapes.
    """

    @pytest.fixture(autouse=True)
    def _present_as_self_host(self, monkeypatch):
        """R2: the hook-count drift check is now self-host-gated. These cases
        exercise the regex hardening on a SYNTHETIC repo, so present it as
        self-host; without this the gate would skip the block and the
        expect_finding=False cases would pass VACUOUSLY (wrong reason). The
        adopter gate itself is covered by test_adopter_repo_skips_hook_count_drift."""
        import espalier.surface_contract as _sc
        monkeypatch.setattr(_sc, "is_self_host_repo", lambda *_a, **_k: True)

    @staticmethod
    def _make_hooks(tmp_path: Path, count: int) -> None:
        # TP-174a S1: doctor now counts only canonical-roster hooks, so the
        # old synthetic ``hook_N.py`` names no longer count. Lay down the
        # first ``count`` real canonical names instead.
        from espalier.surface_contract import get_canonical_hook_scripts

        canonical = get_canonical_hook_scripts()
        assert count <= len(canonical), (
            f"test count {count} exceeds canonical roster size {len(canonical)}"
        )
        hooks_dir = tmp_path / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for name in canonical[:count]:
            (hooks_dir / name).write_text("# hook\n", encoding="utf-8")

    def test_stray_non_canonical_hook_does_not_inflate_count(self, tmp_path):
        """TP-174a S1 earn-the-red: a stray non-canonical .py (a refactor
        backup) in tools/cc/hooks/ must NOT inflate doctor's hook count and
        emit a spurious drift finding when the docs correctly state the
        canonical count. Against pre-S1 HEAD this FAILS (reports N+1)."""
        from espalier.surface_contract import get_canonical_hook_scripts

        canonical = get_canonical_hook_scripts()
        n = len(canonical)
        self._make_hooks(tmp_path, n)
        # A stray, non-canonical file (e.g. left by a refactor).
        (tmp_path / "tools" / "cc" / "hooks" / "write_guard_backup.py").write_text(
            "# stray\n", encoding="utf-8"
        )
        (tmp_path / "CLAUDE.md").write_text(
            f"Ships {n} hooks total.\n", encoding="utf-8"
        )
        from espalier.doctor import _check_doc_drift

        hook_findings = [f for f in _check_doc_drift(tmp_path) if "hook scripts" in f]
        assert not hook_findings, (
            f"stray non-canonical hook inflated the count: {hook_findings!r}"
        )

    def test_live_count_hooks_ignores_stray_file(self, tmp_path):
        """Sister-site of the doctor fix: audit_accuracy._live_count_hooks must
        also ignore a stray non-canonical .py."""
        from espalier.audit_accuracy import _live_count_hooks
        from espalier.surface_contract import get_canonical_hook_scripts

        canonical = get_canonical_hook_scripts()
        self._make_hooks(tmp_path, len(canonical))
        (tmp_path / "tools" / "cc" / "hooks" / "write_guard_backup.py").write_text(
            "# stray\n", encoding="utf-8"
        )
        assert _live_count_hooks(tmp_path) == len(canonical)

    @pytest.mark.parametrize(
        "doc_text,actual,expect_finding",
        [
            ("Currently 10 hooks operate.", 10, False),  # exact match
            ("Currently 9 hooks operate.", 10, True),    # real mismatch
            ("Version v10 hooks ship.", 10, False),      # was: matched "10 hooks"
            ("Threshold 1.10 hooks/s.", 10, False),      # was: matched "10 hooks"
            ("Cluster ABC10 hooks.", 10, False),         # alpha prefix
            ("Cap is ４ hooks.", 4, False),               # fullwidth digit
        ],
    )
    def test_hardened_regex_rejects_known_false_matches(
        self, tmp_path, doc_text, actual, expect_finding
    ):
        self._make_hooks(tmp_path, actual)
        (tmp_path / "CLAUDE.md").write_text(doc_text, encoding="utf-8")

        from espalier.doctor import _check_doc_drift
        findings = _check_doc_drift(tmp_path)
        hook_findings = [f for f in findings if "hook scripts" in f]

        if expect_finding:
            assert hook_findings, (
                f"expected drift finding for {doc_text!r} vs actual={actual}; "
                f"got {findings!r}"
            )
        else:
            assert not hook_findings, (
                f"expected NO hook-count finding for {doc_text!r} "
                f"vs actual={actual}; got {hook_findings!r}"
            )

    def test_adopter_repo_skips_hook_count_drift(self, tmp_path, monkeypatch):
        """R2:DOCTOR-DOCDRIFT — on a NON-self-host (adopter) repo, an unrelated
        'N hooks' line (git hooks, React hooks) must NOT produce a hook-count
        drift finding; the check is self-host-gated. Overrides the autouse
        self-host fixture to exercise the real adopter path."""
        import espalier.surface_contract as _sc
        monkeypatch.setattr(_sc, "is_self_host_repo", lambda *_a, **_k: False)
        self._make_hooks(tmp_path, 12)  # disk has 12 canonical hooks
        (tmp_path / "README.md").write_text(
            "We use 5 git hooks for pre-commit.\n", encoding="utf-8"
        )
        from espalier.doctor import _check_doc_drift
        hook_findings = [f for f in _check_doc_drift(tmp_path) if "hook scripts" in f]
        assert not hook_findings, (
            f"adopter 'git hooks' prose false-flagged as drift: {hook_findings!r}"
        )

    def test_bypass_class_count_uses_hardened_helper(self, tmp_path):
        """The 'bypass classes' multi-word label is special-cased in
        ``_label_word_re``; ensure the doctor caller reaches it cleanly."""
        corpus = tmp_path / "bench" / "corpus"
        corpus.mkdir(parents=True)
        for i in range(5):
            (corpus / f"BC-{i:03d}.json").write_text("{}", encoding="utf-8")

        (tmp_path / "README.md").write_text(
            "We document 5 bypass classes and the v5 bypass classes counter.",
            encoding="utf-8",
        )
        from espalier.doctor import _check_doc_drift
        findings = _check_doc_drift(tmp_path)
        # First clause matches (5 == 5); second clause "v5" must be
        # rejected by the hardened helper (alpha-prefix exclusion). Net:
        # no bypass-class finding.
        bypass_findings = [f for f in findings if "bypass classes" in f]
        assert not bypass_findings, (
            f"expected no bypass-class finding; got {bypass_findings!r}"
        )


def _gov_settings_path(repo: Path) -> Path:
    return repo / ".claude" / "settings.json"


def _load_settings(repo: Path) -> dict:
    return json.loads(_gov_settings_path(repo).read_text(encoding="utf-8"))


def _save_settings(repo: Path, data: dict) -> None:
    _gov_settings_path(repo).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _governance_failures(result: dict) -> list[str]:
    return [
        f for f in result.get("failures", [])
        if "governance gate" in f.lower()
    ]


class TestN7GovernanceEventWiring:
    """TP-169 §13 #8 (N7): deleting a whole blocking-governance EVENT key from
    .claude/settings.json silently removes a DENY/blocking gate while the hook
    *files* stay on disk — pre-fix every doctor signal stayed green. The
    completeness oracle must report a FAILURE for any blocking hook not wired
    under its canonical event, and a fully-wired baseline must still pass.
    """

    def test_baseline_full_wiring_has_no_governance_failure(self, harness_repo):
        # Positive control: the faithful fixture wires all four gates.
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert _governance_failures(result) == [], (
            f"fully-wired baseline must not flag a governance gate; "
            f"got {_governance_failures(result)!r}"
        )

    def test_deleting_configchange_event_fails(self, harness_repo):
        data = _load_settings(harness_repo)
        data["hooks"].pop("ConfigChange", None)
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        gov = _governance_failures(result)
        assert any("config_guard.py" in f and "ConfigChange" in f for f in gov), gov

    def test_deleting_stop_event_fails(self, harness_repo):
        data = _load_settings(harness_repo)
        data["hooks"].pop("Stop", None)
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("stop_gate.py" in f and "Stop" in f for f in _governance_failures(result))

    def test_deleting_pretooluse_event_fails_for_both_scripts(self, harness_repo):
        data = _load_settings(harness_repo)
        data["hooks"].pop("PreToolUse", None)
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        gov = _governance_failures(result)
        assert any("write_guard.py" in f for f in gov), gov
        assert any("plan_guard.py" in f for f in gov), gov

    def test_unwiring_one_pretooluse_script_fails(self, harness_repo):
        # Event present, but plan_guard dropped from the entry list.
        data = _load_settings(harness_repo)
        data["hooks"]["PreToolUse"] = [
            e for e in data["hooks"]["PreToolUse"]
            if "plan_guard.py" not in json.dumps(e)
        ]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        gov = _governance_failures(result)
        assert any("plan_guard.py" in f for f in gov), gov
        # write_guard still wired → not flagged.
        assert not any("write_guard.py" in f for f in gov), gov

    def test_script_wired_under_wrong_event_fails(self, harness_repo):
        # config_guard moved off ConfigChange onto PostToolUse: present in the
        # file, but not wired under the event that makes it a DENY gate.
        data = _load_settings(harness_repo)
        moved = data["hooks"].pop("ConfigChange")
        data["hooks"]["PostToolUse"] = moved
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("config_guard.py" in f and "ConfigChange" in f for f in _governance_failures(result))


class TestN7ExecutabilityFailOpens:
    """TP-169 §13 #8 re-attack: a blocking gate whose script *path* is present
    but whose gate is DEAD (no-op command, wrong type, stale-copy path, or a
    tool-excluding matcher) must be flagged — a path-only check reads it as
    wired (fail-OPEN). Each row earns-the-red against the executability fix."""

    def _wg_entry(self, harness_repo):
        data = _load_settings(harness_repo)
        for e in data["hooks"]["PreToolUse"]:
            if "write_guard.py" in json.dumps(e):
                return data, e
        raise AssertionError("write_guard entry not found")

    def test_inert_exec_command_true_flags(self, harness_repo):
        data, wg = self._wg_entry(harness_repo)
        wg["hooks"][0]["command"] = "true"  # path stays in args, never executes
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    def test_shell_noop_bait_flags(self, harness_repo):
        data = _load_settings(harness_repo)
        data["hooks"]["ConfigChange"] = [{"hooks": [{
            "type": "command",
            "command": ": ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/config_guard.py",
        }]}]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("config_guard.py" in f for f in _governance_failures(result))

    def test_shell_form_invocation_flagged(self, harness_repo):
        # TP-169 §13 #8 round-2: shell-form `command` strings are undecidable to
        # verify (`false && python3 X.py`, `python3 -m pytest X.py` all "look"
        # live), so the oracle recognizes ONLY canonical exec form and fails
        # CLOSED on shell form — even a genuine `python3 <path>` is conservatively
        # flagged (use exec form: command + args).
        data = _load_settings(harness_repo)
        data["hooks"]["ConfigChange"] = [{"hooks": [{
            "type": "command",
            "command": "python3 ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/config_guard.py",
        }]}]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("config_guard.py" in f for f in _governance_failures(result))

    @pytest.mark.parametrize("bad_args", [
        ["-c", "pass", "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
        ["-m", "py_compile", "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
    ])
    def test_exec_flag_prefix_inert_script_flagged(self, harness_repo, bad_args):
        # `python3 -c pass X.py` / `-m mod X.py`: python runs the flag, X.py is
        # inert sys.argv → the gate never executes (round-2 critical).
        data, wg = self._wg_entry(harness_repo)
        wg["hooks"][0]["args"] = bad_args
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    def test_dot_slash_path_passes(self, harness_repo):
        # Positive control: ${CLAUDE_PROJECT_DIR}/./tools/... normalizes to the
        # canonical path on both legs — must NOT be flagged (round-2 parity).
        data, wg = self._wg_entry(harness_repo)
        wg["hooks"][0]["args"] = ["${CLAUDE_PROJECT_DIR}/./tools/cc/hooks/write_guard.py"]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any("write_guard.py" in f for f in _governance_failures(result))

    def test_source_checkout_mode_still_flags_present_neutered_gate(self, harness_repo):
        # TP-169 §13 #8 round-2: forcing --mode source-checkout on a repo with a
        # present-but-neutered settings.json must NOT skip the governance oracle.
        from espalier.repo_mode import REPO_MODE_SOURCE_CHECKOUT
        data, wg = self._wg_entry(harness_repo)
        wg["matcher"] = "Bash"  # neuter the PreToolUse gate
        _save_settings(harness_repo, data)
        result = run_doctor_check(
            harness_repo, skip_self_host=True, mode=REPO_MODE_SOURCE_CHECKOUT)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    def test_wrong_type_prompt_flags(self, harness_repo):
        data, wg = self._wg_entry(harness_repo)
        wg["hooks"][0]["type"] = "prompt"  # CC runs only type=="command"
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    def test_stale_copy_path_flags(self, harness_repo):
        # Canonical file on disk, but wired from a stale .claude/hooks/ copy.
        stale = harness_repo / ".claude" / "hooks" / "write_guard.py"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        data, wg = self._wg_entry(harness_repo)
        wg["hooks"][0]["args"] = [".claude/hooks/write_guard.py"]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    def test_tool_excluding_matcher_flags(self, harness_repo):
        data, wg = self._wg_entry(harness_repo)
        wg["matcher"] = "Bash"  # excludes Write/Edit/NotebookEdit → gate dead
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    @pytest.mark.parametrize("narrowed", [
        "Write|Edit|NotebookEdit",                           # the round-4 survivor
        "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*",   # broad but not fire-all
    ])
    def test_write_guard_non_fire_all_matcher_flagged(self, harness_repo, narrowed):
        # TP-169 §13 #8 round-4: write_guard's canonical matcher is "*" because
        # its kill-switch must reach EVERY tool (Task/Bash/MCP/…). A matcher that
        # merely covers mutations (or even mutations+bash+mcp) silently collapses
        # the kill-switch's reach — a dead-ish gate the old covers-mutations check
        # read as wired. Per-hook canonical-matcher check now flags it.
        data, wg = self._wg_entry(harness_repo)
        wg["matcher"] = narrowed
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("write_guard.py" in f for f in _governance_failures(result))

    def test_write_guard_star_matcher_passes(self, harness_repo):
        # Positive control: canonical write_guard matcher "*" (fire-on-all) passes.
        data, wg = self._wg_entry(harness_repo)
        wg["matcher"] = "*"
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any("write_guard.py" in f for f in _governance_failures(result))

    def test_plan_guard_covers_mutations_passes(self, harness_repo):
        # plan_guard's canonical matcher is the mutation set, so a mutation-
        # covering matcher (even broader) passes — only write_guard needs fire-all.
        data = _load_settings(harness_repo)
        for e in data["hooks"]["PreToolUse"]:
            if "plan_guard.py" in json.dumps(e):
                e["matcher"] = "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*"
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any("plan_guard.py" in f for f in _governance_failures(result))


class TestN7MalformedSettingsFailClosed:
    """TP-169 §13 #8 round-3: a present settings.json the oracle cannot prove
    wires the gates (no `hooks` key, non-dict `hooks`, malformed JSON, non-dict
    top-level) is the MOST complete neutering — all gates dead at once. It must
    fail CLOSED (flag every deployed gate), matching ci_guard, never read green."""

    @pytest.mark.parametrize("raw", [
        '{"permissions": {}}',          # no hooks key
        '{"hooks": "disabled"}',        # hooks non-dict (string)
        '{"hooks": []}',                # hooks non-dict (list)
        '{"hooks": null}',              # hooks null
        '[]',                           # top-level non-dict
        '{ not valid json',             # malformed
    ])
    def test_unprovable_settings_flags_all_deployed_gates(self, harness_repo, raw):
        (harness_repo / ".claude" / "settings.json").write_text(raw, encoding="utf-8")
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        gov = _governance_failures(result)
        for script in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            assert any(script in f for f in gov), f"{script} not flagged on {raw!r}: {gov}"


class TestN7BomSettings:
    """TP-169 §13 #8 round-5: a UTF-8-BOM-prefixed but byte-canonical
    settings.json (PowerShell/editor re-encode) must NOT false-flag the gates —
    the readers use utf-8-sig per the project's own BOM convention."""

    def test_bom_canonical_settings_not_flagged(self, harness_repo):
        sp = harness_repo / ".claude" / "settings.json"
        raw = sp.read_text(encoding="utf-8").encode("utf-8")
        sp.write_bytes(b"\xef\xbb\xbf" + raw)  # prepend BOM, content unchanged
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert _governance_failures(result) == [], (
            "BOM'd byte-canonical settings.json must not flag any gate; "
            f"got {_governance_failures(result)!r}"
        )


class TestN7DanglingSymlinkSettings:
    """TP-169 §13 #8 round-6: a dangling-symlink .claude/settings.json (lexists
    True, exists False — e.g. settings.json -> a per-machine file absent on CI)
    is present-but-unreadable, not absent. With hook files deployed, the
    governance oracle must fail CLOSED (flag the gates), not read it as absent."""

    @requires_symlink
    def test_dangling_symlink_settings_flags_gates(self, harness_repo):
        import os
        sp = harness_repo / ".claude" / "settings.json"
        sp.unlink()
        os.symlink("per-machine-absent.json", sp)  # dangling
        assert sp.is_symlink() and not sp.exists()
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        gov = _governance_failures(result)
        for script in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            assert any(script in f for f in gov), f"{script} not flagged: {gov}"


class TestM2BroughtYourOwnSettingsOnboarding:
    """TP-192 M2 (operator decision: consolidate, keep fail-closed): a
    readable+valid settings.json that wires NO Espalier hooks collapses the N
    near-identical per-gate failures into ONE fail-closed line that STILL names
    every gate and points at `merge-settings` — keeping the TP-169 N7
    fail-closed contract (status=fail, gates named) AND pack pass-criterion 4
    (no deny path weakened), while stopping the wall-of-red. Consolidation is
    PRESENTATION-only (in run_doctor_check); the `_check_governance_event_wiring`
    oracle stays per-gate so it remains count-parity-locked with ci_guard. A
    partial disarm, an all-inert/neutered surface, and an unreadable settings
    all stay loud."""

    _GATES = ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py")

    def test_oracle_stays_per_gate_for_ci_parity(self, harness_repo):
        """The scan oracle is NOT consolidated — it returns one failure per
        deployed gate (count-parity-locked with ci_guard); the consolidation
        happens only in the doctor report."""
        from espalier.doctor import _check_governance_event_wiring

        _save_settings(harness_repo, {"permissions": {"allow": ["Read"]}})
        failures = _check_governance_event_wiring(harness_repo)
        assert len(failures) == len(self._GATES), failures
        assert not any("merge-settings" in f for f in failures), failures

    def test_zero_wired_consolidates_in_doctor_report(self, harness_repo):
        _save_settings(harness_repo, {"permissions": {"allow": ["Read"]}})
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"  # still fail-closed
        assert any("merge-settings" in s for s in result["next_steps"]), result["next_steps"]
        # exactly one consolidated governance line, not a 4-line wall...
        gov = _governance_failures(result)
        assert len(gov) == 1, gov
        # ...still naming every gate (TP-169 N7 contract holds).
        for script in self._GATES:
            assert script in gov[0], gov[0]

    def test_partial_disarm_stays_loud(self, harness_repo):
        # write_guard + stop_gate stay wired; drop plan_guard and config_guard.
        data = _load_settings(harness_repo)
        data["hooks"]["PreToolUse"] = [
            e for e in data["hooks"]["PreToolUse"] if "plan_guard.py" not in json.dumps(e)
        ]
        data["hooks"].pop("ConfigChange", None)
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        # NOT consolidated — the per-gate wall survives, no merge-settings remedy.
        # Consolidation is detected DIRECTLY, by the absence of the collapsed
        # line, not by proxy through next_steps. The old spelling asserted that
        # `merge-settings` appeared nowhere in next_steps, which worked only
        # while the loud branch offered no actions at all. It now offers
        # shape-correct ones, so the proxy fired on a tree that had NOT been
        # consolidated. Driven 2026-08-27 on this exact fixture: config_guard
        # (whole event key deleted) IS repaired by merge-settings and
        # plan_guard (entry removed from a surviving event) is NOT, so naming
        # the command for the first and a hand edit for the second is the
        # honest advice -- and withholding both, which is what the proxy
        # enforced, left this operator with nothing to do.
        assert not any(
            "wires no Espalier hooks" in f for f in result["failures"]
        ), result["failures"]
        gov = _governance_failures(result)
        # both dropped gates individually flagged (a wall, not one consolidated line).
        assert len(gov) == 2, gov
        assert any("plan_guard.py" in f for f in gov), gov
        assert any("config_guard.py" in f for f in gov), gov

    def test_all_inert_full_disarm_stays_loud(self, harness_repo):
        """Calibrated-deviation guard (TP-192 §6.10): an all-inert settings.json
        — references the canonical hook paths but neuters every command to a
        no-op — is a FULL DISARM (tamper), NOT benign onboarding. It must stay
        loud (per-gate wall), not consolidate."""
        _save_settings(harness_repo, {"hooks": {
            "PreToolUse": [{
                "matcher": "*",
                "hooks": [{
                    "type": "command", "command": "true",
                    "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
                }],
            }],
        }})
        result = run_doctor_check(harness_repo, skip_self_host=True)
        # Consolidation is detected DIRECTLY, by the absence of the collapsed
        # line, not by proxy through next_steps. The old spelling asserted that
        # `merge-settings` appeared nowhere in next_steps, which worked only
        # while the loud branch offered no actions at all. It now offers
        # shape-correct ones, so the proxy fired on a tree that had NOT been
        # consolidated. Driven 2026-08-27 on this exact fixture: config_guard
        # (whole event key deleted) IS repaired by merge-settings and
        # plan_guard (entry removed from a surviving event) is NOT, so naming
        # the command for the first and a hand edit for the second is the
        # honest advice -- and withholding both, which is what the proxy
        # enforced, left this operator with nothing to do.
        assert not any(
            "wires no Espalier hooks" in f for f in result["failures"]
        ), result["failures"]
        gov = _governance_failures(result)
        assert any("write_guard.py" in f for f in gov), gov

    def test_backslash_path_neuter_stays_loud(self, harness_repo):
        """TP-192 §6.10 (adversarial follow-up): a BACKSLASH-path neutered gate
        (`…\\tools\\cc\\hooks\\write_guard.py` with an inert command) must stay
        loud — the benign-hookless discriminator normalizes separators (CLAUDE.md
        path rule), so it is NOT softened to the onboarding line."""
        _save_settings(harness_repo, {"hooks": {
            "PreToolUse": [{
                "matcher": "*",
                "hooks": [{
                    "type": "command", "command": "true",
                    "args": ["${CLAUDE_PROJECT_DIR}\\tools\\cc\\hooks\\write_guard.py"],
                }],
            }],
        }})
        result = run_doctor_check(harness_repo, skip_self_host=True)
        # Consolidation is detected DIRECTLY, by the absence of the collapsed
        # line, not by proxy through next_steps. The old spelling asserted that
        # `merge-settings` appeared nowhere in next_steps, which worked only
        # while the loud branch offered no actions at all. It now offers
        # shape-correct ones, so the proxy fired on a tree that had NOT been
        # consolidated. Driven 2026-08-27 on this exact fixture: config_guard
        # (whole event key deleted) IS repaired by merge-settings and
        # plan_guard (entry removed from a surviving event) is NOT, so naming
        # the command for the first and a hand edit for the second is the
        # honest advice -- and withholding both, which is what the proxy
        # enforced, left this operator with nothing to do.
        assert not any(
            "wires no Espalier hooks" in f for f in result["failures"]
        ), result["failures"]
        gov = _governance_failures(result)
        assert any("write_guard.py" in f for f in gov), gov


class TestDoctorGroundingNudge:
    """#1 earn-the-red: doctor points an un-grounded repo at `/analyze`."""

    def test_needs_grounding_true_when_conventions_absent(self, tmp_path):
        from espalier.doctor import _needs_grounding
        assert _needs_grounding(tmp_path) is True

    def test_needs_grounding_true_when_conventions_near_empty(self, tmp_path):
        from espalier.doctor import _needs_grounding
        conv = tmp_path / "docs" / "CONVENTIONS.md"
        conv.parent.mkdir(parents=True, exist_ok=True)
        conv.write_text("# Heading only\n\nseed line\n", encoding="utf-8")
        assert _needs_grounding(tmp_path) is True

    def test_needs_grounding_false_when_conventions_populated(self, tmp_path):
        from espalier.doctor import _needs_grounding
        conv = tmp_path / "docs" / "CONVENTIONS.md"
        conv.parent.mkdir(parents=True, exist_ok=True)
        conv.write_text(
            "\n".join(f"real convention line {i}" for i in range(40)),
            encoding="utf-8",
        )
        assert _needs_grounding(tmp_path) is False

    def _stamped(self, body: str) -> str:
        import hashlib

        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return f"<!-- espalier:seed-version v0.8.0a13 sha256:{digest} -->\n{body}"

    def test_untouched_seeded_stub_needs_grounding_whatever_its_length(self, tmp_path):
        """DEF-687: the Tier-3 stub carries more content lines than the floor,
        so the line count alone read every fresh install as grounded."""
        from espalier.doctor import _GROUNDING_MIN_CONTENT_LINES, _needs_grounding

        conv = tmp_path / "docs" / "CONVENTIONS.md"
        conv.parent.mkdir(parents=True, exist_ok=True)
        body = "# Conventions\n\n" + "\n".join(
            f"prompt line {i}" for i in range(_GROUNDING_MIN_CONTENT_LINES + 10)
        ) + "\n"
        conv.write_text(self._stamped(body), encoding="utf-8")
        assert _needs_grounding(tmp_path) is True

    def test_edited_seeded_stub_falls_through_to_the_floor(self, tmp_path):
        from espalier.doctor import _GROUNDING_MIN_CONTENT_LINES, _needs_grounding

        conv = tmp_path / "docs" / "CONVENTIONS.md"
        conv.parent.mkdir(parents=True, exist_ok=True)
        body = "# Conventions\n\n" + "\n".join(
            f"prompt line {i}" for i in range(_GROUNDING_MIN_CONTENT_LINES + 10)
        ) + "\n"
        conv.write_text(self._stamped(body) + "- the adopter wrote this\n", encoding="utf-8")
        assert _needs_grounding(tmp_path) is False

    def test_the_real_seed_stub_as_init_writes_it_needs_grounding(self, tmp_path):
        """Pins the SHIPPED stub, so the seed growing again cannot regress this."""
        from espalier.managed_inventory import seed_stamp_line
        from espalier.doctor import _needs_grounding

        seed = Path(__file__).resolve().parent.parent / "espalier" / "assets" / "seed" / "CONVENTIONS.md"
        body = seed.read_text(encoding="utf-8")
        conv = tmp_path / "docs" / "CONVENTIONS.md"
        conv.parent.mkdir(parents=True, exist_ok=True)
        conv.write_text(seed_stamp_line(body) + body, encoding="utf-8")
        assert _needs_grounding(tmp_path) is True

    def test_pass_repo_gets_grounding_nudge(self, harness_repo):
        # harness_repo ships no docs/CONVENTIONS.md, so a coherent-but-
        # un-grounded repo surfaces the /analyze nudge. Guard on pass —
        # the fixture's status is only pinned as non-fail.
        report = run_doctor_check(harness_repo, skip_self_host=True)
        if report["status"] == "pass":
            assert any("/analyze" in s for s in report["next_steps"]), report["next_steps"]


class TestDecodeTolerance:
    """An adopter-authored file the engine reads must not crash a DIAGNOSTIC.

    ``docs/CONVENTIONS.md`` is adopter-owned, and a Windows adopter can resave it
    as cp1252. The read was guarded by ``except OSError`` alone, but
    ``UnicodeDecodeError`` is a ``ValueError`` — so it escaped and took down
    ``doctor``, the command whose whole job is to report on a broken repo.

    ONE earn-the-red per BEHAVIOUR CLASS, deliberately, not one per site: the
    other six sites read files the harness itself writes as UTF-8, so their
    corruption is unreachable without hand-editing. Writing seven near-identical
    fixtures would be ceremony, not coverage.
    """

    def test_cp1252_conventions_file_degrades_instead_of_crashing(self, tmp_path):
        from espalier.doctor import _needs_grounding

        docs = tmp_path / "docs"
        docs.mkdir()
        # 0xE9 is 'é' in cp1252 and is NOT valid standalone UTF-8.
        (docs / "CONVENTIONS.md").write_bytes(
            b"# Conventions\n\nNaive caf\xe9 rules apply.\nSecond line.\n"
        )
        assert _needs_grounding(tmp_path) is False

    # NO end-to-end companion, deliberately. `_needs_grounding` has exactly one
    # call site in the engine, and a BARE anchor is the honest citation for a call
    # site -- a symbol+line pair reads as "defined here" to the anchor checker and
    # would red against the def. It is `espalier/doctor.py::run_doctor_check`, inside the
    # `if status == "pass"` branch of run_doctor_check, and the
    # `harness_repo` fixture measures `warn` — so a run_doctor_check() test never
    # reaches the branch and passes IDENTICALLY with the defect live. That test
    # was written, measured vacuous, and removed rather than shipped: a green
    # assertion over an unexecuted line is the born-weak shape this suite exists
    # to catch, and it would have read as end-to-end proof.


class TestEveryWarningCarriesANextStep:
    """DEF-433 (ledger §C6) — a `warn` verdict must never hand back an empty
    action list.

    `run_doctor_check` has eight warn-producing sites and exactly ONE of them
    (fingerprint/build-plan drift) populated `next_steps`. The comment beside
    that one branch concedes the gap in the singular -- an earlier pass fixed
    the branch in front of it and stopped -- which is why this contract is
    written against the whole population rather than against a symptom.

    Shape: BEHAVIOURAL fixtures (drive `run_doctor_check` with each warn state
    actually tripped) plus a COUNT RATCHET pinning the warn-site population, so
    a warn branch added later reds here until someone gives it a fixture.

    ⚠ Every warn producer is quieted first and then exactly ONE is switched on.
    Without that, `next_steps` is populated by unrelated failure branches and a
    bare `assert result["next_steps"]` passes no matter what the warn branch
    does -- measured, and it is how the first draft of this test false-greened
    all seven fixtures.
    """

    @staticmethod
    def _quiet_all(mp):
        """Silence every warn producer. Each fixture re-arms exactly one.

        Also forces ``is_self_host_repo`` True for the whole comparison: the
        external-tool warn site is gated on it, so on an adopter tree that
        branch is unreachable and its fixture could never arm. Forcing it in
        the BASELINE too keeps the delta attributable -- any self-host-only
        next_step appears on both sides and subtracts out.
        """
        from espalier import doctor as d
        from espalier import surface_contract as sc

        mp.setattr(sc, "is_self_host_repo", lambda root: True)

        real_presence = d._surface_presence

        def _clean_presence(root):
            out = dict(real_presence(root))
            out["partial"] = False
            out["surface_missing"] = False
            return out

        mp.setattr(d, "_three_way_ownership", lambda root, plan: {
            "current_paths": [], "stale_saved_paths": [],
            "missing_from_saved_plan": [],
        })
        mp.setattr(d, "reflect_repo", lambda root: {
            "broken_markdown_links": [], "plan_missing_docs": [],
        })
        mp.setattr(d, "diff_repo", lambda root, cfg: {
            "fingerprint_changed": False, "build_plan_changed": False,
        })
        mp.setattr(d, "_surface_presence", _clean_presence)
        mp.setattr(d, "_check_doc_drift", lambda root: [])
        mp.setattr(d, "_check_python_resolver", lambda root: [])
        mp.setattr(d, "_check_external_tool", lambda tool, hint: [])
        mp.setattr(d, "_check_reporter_hook_wiring", lambda root: [])

        # The gitignore branch reads espalier.cli.gitignore_status via a lazy
        # import, so it must be silenced at the SOURCE module, not on `d`.
        from espalier import cli as _cli
        from espalier.cli import GitignoreStatus
        mp.setattr(_cli, "gitignore_status", lambda root: GitignoreStatus(
            exists=True, missing=(), unanchored=(), withheld={}, shared={},
            oracle="git",
        ))

    @staticmethod
    def _stale_saved_paths(mp):
        from espalier import doctor as d
        mp.setattr(d, "_three_way_ownership", lambda root, plan: {
            "current_paths": [], "stale_saved_paths": ["cc/retired.md"],
            "missing_from_saved_plan": [],
        })

    @staticmethod
    def _missing_from_saved_plan(mp):
        from espalier import doctor as d
        mp.setattr(d, "_three_way_ownership", lambda root, plan: {
            "current_paths": [], "stale_saved_paths": [],
            "missing_from_saved_plan": ["cc/unclaimed.md"],
        })

    @staticmethod
    def _reflect_surface_drift(mp):
        from espalier import doctor as d
        mp.setattr(d, "reflect_repo", lambda root: {
            "broken_markdown_links": ["docs/gone.md"], "plan_missing_docs": [],
        })

    @staticmethod
    def _report_drift(mp):
        from espalier import doctor as d
        mp.setattr(d, "diff_repo", lambda root, cfg: {
            "fingerprint_changed": True, "build_plan_changed": False,
        })

    @staticmethod
    def _partial_surface(mp):
        from espalier import doctor as d
        real = d._surface_presence

        def _partial(root):
            out = dict(real(root))
            out["partial"] = True
            out["surface_missing"] = False
            return out

        mp.setattr(d, "_surface_presence", _partial)

    @staticmethod
    def _doc_drift(mp):
        from espalier import doctor as d
        mp.setattr(d, "_check_doc_drift", lambda root: ["docs/CONVENTIONS.md"])

    @staticmethod
    def _python_resolver(mp):
        from espalier import doctor as d
        mp.setattr(
            d, "_check_python_resolver",
            lambda root: ["hook interpreter 'python' does not resolve on this host"],
        )

    @staticmethod
    def _external_tool_missing(mp):
        from espalier import doctor as d
        mp.setattr(
            d, "_check_external_tool",
            lambda tool, hint: [f"{tool} not found on PATH"] if tool == "ruff" else [],
        )

    # Method NAMES, resolved with getattr at call time. Storing the function
    # objects here would capture raw `staticmethod` descriptors (the class does
    # not exist yet inside its own body), which is not worth unwrapping.
    @staticmethod
    def _gitignore_missing(mp):
        from espalier import cli as _cli
        from espalier.cli import GitignoreStatus
        mp.setattr(_cli, "gitignore_status", lambda root: GitignoreStatus(
            exists=True, missing=(".espalier-state/",), unanchored=(),
            withheld={}, shared={}, oracle="git",
        ))

    @staticmethod
    def _dead_reporter(mp):
        """DEF-619: a deployed reporter hook with no executable wiring."""
        from espalier import doctor as d
        mp.setattr(
            d, "_check_reporter_hook_wiring",
            lambda root: ["reporter hook not wired: post_compact.py is on disk "
                          "but has no executable, correctly-matched wiring"],
        )

    WARN_STATES = [
        "_dead_reporter",
        "_gitignore_missing",
        "_stale_saved_paths",
        "_missing_from_saved_plan",
        "_reflect_surface_drift",
        "_report_drift",
        "_partial_surface",
        "_doc_drift",
        "_python_resolver",
        "_external_tool_missing",
    ]

    @pytest.mark.parametrize(
        "state_method", WARN_STATES, ids=[m.lstrip("_") for m in WARN_STATES]
    )
    def test_warn_branch_names_something_to_do(
        self, harness_repo, monkeypatch, state_method
    ):
        state_id = state_method.lstrip("_")

        self._quiet_all(monkeypatch)
        baseline = run_doctor_check(
            harness_repo, skip_self_host=True, check_doc_drift=True
        )
        assert not baseline["warnings"], (
            "_quiet_all failed to silence every warn producer; baseline still "
            f"warns: {baseline['warnings']}"
        )

        getattr(self, state_method)(monkeypatch)
        result = run_doctor_check(
            harness_repo, skip_self_host=True, check_doc_drift=True
        )

        # Trip-guard: a fixture that stops tripping its branch must red as a
        # broken fixture, not pass as a satisfied contract.
        assert result["warnings"], (
            f"fixture {state_id!r} did not trip a warning -- the fixture is "
            "broken, not the code under test"
        )
        added = [s for s in result["next_steps"] if s not in baseline["next_steps"]]
        assert added, (
            f"{state_id!r} warned {result['warnings']} but added no next_step "
            f"(next_steps unchanged at {result['next_steps']})"
        )

    #: Branches that append a failure and deliberately name no action, each
    #: with the reason it does not need one. An entry here is a CLAIM that gets
    #: read at review time -- it is not a way to make a red go away.
    UNPAIRED_FAILURE_EXEMPTIONS = {
        "self_host_failure": (
            "premise falsified 2026-08-26: driven across ten cause-states, this "
            "was never failures[0] and next_steps was never empty, so the "
            "empty-action-list harm this ratchet exists for does not reach it"
        ),
        "recover_missing": (
            "sits inside the `recover status == fail` branch, which forwards "
            "`recover['recommendations']` into next_steps immediately above it. "
            "PROBABLE, NOT DRIVEN -- established by static reading only; if you "
            "are here because it reddened, drive it rather than trusting this"
        ),
    }

    def test_advisory_site_population_is_pinned(self):
        """Count ratchet over BOTH advisory lists and BOTH spellings.

        Reds when a `warnings`/`failures` append, extend, or `+=` is added to or
        removed from ``run_doctor_check``.

        ⚠ THIS TEST USED TO COVER HALF ITS CLASS AND SAY OTHERWISE. It counted
        `warnings.append/extend` only. Driven 2026-08-26 by injecting a branch
        and watching it stay green: `warnings += [...]` is an AugAssign rather
        than a Call and was invisible, and every `failures.*` site was invisible
        because the name differed — the larger population (9 vs 8 at the time)
        and the more damaging one, since `_primary_reason` surfaces
        `failures[0]`, making an unpaired failure the HEADLINE verdict with an
        empty action list.

        The behavioural fixtures above are a hand-written population and
        therefore blind to a branch nobody wrote a fixture for
        (STANDING_PRINCIPLES §14). This is the tighten-me leg: a new site reds
        here, and clearing the red means adding its fixture (for a warning) or
        pairing it / declaring it in UNPAIRED_FAILURE_EXEMPTIONS (for a failure)
        in the same edit.
        """
        import ast

        source = (Path(__file__).resolve().parent.parent
                  / "espalier" / "doctor.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        target = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "run_doctor_check"
        )

        def sites(name):
            found = []
            for n in ast.walk(target):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in {"append", "extend"}
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == name):
                    found.append(n.lineno)
                # `x += [...]` -- the spelling that slipped past the first version.
                if (isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
                        and n.target.id == name):
                    found.append(n.lineno)
            return sorted(set(found))

        warn_sites = sites("warnings")
        fail_sites = sites("failures")

        assert len(warn_sites) == len(self.WARN_STATES), (
            f"run_doctor_check has {len(warn_sites)} warning sites "
            f"(lines {warn_sites}) but {len(self.WARN_STATES)} behavioural "
            "fixtures exist. Add the missing fixture to WARN_STATES (or drop "
            "the stale one) -- do not just change this number."
        )
        assert len(fail_sites) == self.EXPECTED_FAILURE_SITES, (
            f"run_doctor_check has {len(fail_sites)} failure sites "
            f"(lines {fail_sites}), expected {self.EXPECTED_FAILURE_SITES}. A new "
            "failure branch must either populate next_steps or be named in "
            "UNPAIRED_FAILURE_EXEMPTIONS with a reason, and this number moved "
            "in the same edit. `_primary_reason` reports failures[0], so an "
            "unpaired failure is the headline verdict with nothing to do."
        )

    #: Failure-producing CALL SITES in run_doctor_check -- individual
    #: append/extend/`+=` statements, not guarded branches. The two counts
    #: differ and the distinction matters: 11 sites sit inside 9 guards, of
    #: which 4 were unpaired (2 now pair, 2 are declared above). Pinning sites
    #: rather than branches keeps the check purely mechanical.
    #: Moves only with a pairing or a declared exemption -- never on its own.
    EXPECTED_FAILURE_SITES = 11

    def test_failure_exemptions_state_a_reason(self):
        """An exemption whose justification is a word is a suppression."""
        thin = {k: v for k, v in self.UNPAIRED_FAILURE_EXEMPTIONS.items()
                if len(v) < 40}
        assert not thin, (
            f"these failure-branch exemptions carry no usable reason: {thin}"
        )


class TestRewireNextStepSpellsAnInterpreterThatCanRun:
    """`DEF-727`, the doctor site. The resolver-issue next step spelled its
    command with `_detect_python_command()` -- the same resolver whose answer
    the warning above it had just called broken. On the Windows walk 2 host
    (`python` = a Python 2 shim, no `python3`) the step read
    `python -m espalier init . --rewire-interpreter`, a command that cannot
    run. The interpreter running `doctor` demonstrably can, and is the one to
    spell when neither probed name on PATH clears the floor -- with the honest
    preface that the rewire has no target until one does. The blocker is PATH,
    not a missing install: this doctor is running under a Python that clears
    the floor, so "install Python" prescribed an install already done (the
    code review drove both remedies).
    """

    def _rewire_step(self, harness_repo, monkeypatch, resolver_answer: str) -> str:
        from espalier import cli

        TestEveryWarningCarriesANextStep._quiet_all(monkeypatch)
        TestEveryWarningCarriesANextStep._python_resolver(monkeypatch)
        monkeypatch.setattr(cli, "_detect_python_command", lambda: resolver_answer)
        result = run_doctor_check(
            harness_repo, skip_self_host=True, check_doc_drift=True
        )
        steps = [s for s in result["next_steps"] if "--rewire-interpreter" in s]
        assert len(steps) == 1, result["next_steps"]
        return steps[0]

    def test_a_resolver_answer_that_cannot_run_is_not_spelled(
        self, harness_repo, monkeypatch
    ):
        from espalier._python_floor import floor_text

        step = self._rewire_step(harness_repo, monkeypatch, "python-espalier-absent")
        assert "python-espalier-absent -m espalier" not in step, (
            f"the next step is spelled with an interpreter doctor cannot vouch for: {step}"
        )
        assert sys.executable in step, (
            f"the interpreter running doctor is the one that can run the rewire: {step}"
        )
        assert "on path" in step.lower() and "no target" in step.lower(), (
            f"the rewire has no target on this PATH; the step must say what to "
            f"put on PATH: {step}"
        )
        assert "install" not in step.lower(), (
            f"the operator running doctor has already installed a Python that "
            f"clears the floor ({floor_text()}); an install must not be prescribed: {step}"
        )

    def test_a_resolver_answer_that_clears_the_floor_is_spelled_as_is(
        self, harness_repo, monkeypatch
    ):
        """CONTROL: the common host -- `python3` clears the floor and settings
        wired another name -- keeps the plain step, with no install preface."""
        step = self._rewire_step(harness_repo, monkeypatch, sys.executable)
        assert step.startswith(f"run `{sys.executable} -m espalier init . --rewire-interpreter`"), step
        assert "no target" not in step.lower() and "on path" not in step.lower(), step


class TestDoctorReportsMissingGitignoreEntries:
    """DEF-551 (ledger §C6) — a READ-ONLY command must be able to tell an
    adopter a required `.gitignore` entry is missing.

    Before this, the only code that ever said so lived on the mutating
    `init`/`upgrade` path (`_handle_gitignore`). An adopter who ran `init`
    once, dismissed the WARN, and later ran `doctor` had no non-mutating
    command that would mention it again -- and the entries matter: the harness
    writes machine-specific runtime state, and `.claude/settings.json` records
    the interpreter detected on ONE machine, so committing it hands a teammate
    broken hook wiring.

    The check reads `espalier.cli.gitignore_status`, the same computation
    `_handle_gitignore` renders from, so the mutating and read-only paths
    cannot drift apart on the facts.
    """

    @staticmethod
    def _write_complete_gitignore(repo: Path) -> None:
        """Give the tree every required entry.

        ⚠ The `harness_repo` fixture writes NO .gitignore at all, despite its
        docstring calling itself a faithful initialized harness -- a real
        `espalier init` appends the required block. So "complete" has to be
        constructed here rather than assumed, or the control below asserts
        nothing.
        """
        from espalier.cli import REQUIRED_GITIGNORE

        (repo / ".gitignore").write_text(
            "\n".join(REQUIRED_GITIGNORE) + "\n", encoding="utf-8"
        )

    @classmethod
    def _strip_gitignore(cls, repo: Path) -> str:
        """Build a complete .gitignore, then remove exactly one entry."""
        from espalier.cli import REQUIRED_GITIGNORE

        cls._write_complete_gitignore(repo)
        gi = repo / ".gitignore"
        victim = REQUIRED_GITIGNORE[0]
        kept = [
            ln for ln in gi.read_text(encoding="utf-8").splitlines()
            if ln.strip() != victim
        ]
        gi.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return victim

    def test_status_helper_is_pure_and_sees_the_gap(self, harness_repo):
        """The extraction itself: computing the verdict must not mutate."""
        from espalier.cli import gitignore_status

        victim = self._strip_gitignore(harness_repo)
        before = (harness_repo / ".gitignore").read_text(encoding="utf-8")

        status = gitignore_status(harness_repo)

        assert victim in status.missing, (
            f"{victim!r} was removed from .gitignore but gitignore_status did "
            f"not report it missing; missing={status.missing}"
        )
        assert (harness_repo / ".gitignore").read_text(encoding="utf-8") == before, (
            "gitignore_status mutated .gitignore -- it must be read-only"
        )

    def test_doctor_names_the_missing_entry(self, harness_repo):
        victim = self._strip_gitignore(harness_repo)

        result = run_doctor_check(harness_repo, skip_self_host=True)

        # Attributable: a WARNING that names .gitignore AND the entry. A blob
        # search over the whole report is not a test -- every required entry is
        # also a `presence` path, so `.claude/settings.json` appears in a clean
        # report and the assertion passes with no check wired at all. Measured;
        # it false-greened this test's first draft.
        hits = [
            w for w in result["warnings"]
            if ".gitignore" in w and victim in w
        ]
        assert hits, (
            f"no warning named the missing required .gitignore entry "
            f"{victim!r}. warnings={result['warnings']}"
        )

    def test_doctor_hands_back_an_action(self, harness_repo):
        """DEF-433's contract applies to this new branch too."""
        self._strip_gitignore(harness_repo)

        result = run_doctor_check(harness_repo, skip_self_host=True)

        # Attributable for the same reason: next_steps is populated by other
        # branches, so a bare non-empty assertion proves nothing here.
        hits = [n for n in result["next_steps"] if ".gitignore" in n]
        assert hits, (
            "doctor reported the gitignore gap with no .gitignore next_step; "
            f"next_steps={result['next_steps']}"
        )

    def test_doctor_is_quiet_when_gitignore_is_complete(self, harness_repo):
        """Control -- the check must not fire on a correctly-ignored tree."""
        self._write_complete_gitignore(harness_repo)

        result = run_doctor_check(harness_repo, skip_self_host=True)

        gitignore_warnings = [
            w for w in result["warnings"] if ".gitignore" in w
        ]
        assert not gitignore_warnings, (
            f"doctor warned about .gitignore on a complete tree: "
            f"{gitignore_warnings}"
        )


class TestDoctorWithholdsTrackedGitignoreEntries:
    """DEF-11 exclusion in the new doctor gitignore check (red team, 2026-08-26).

    The full 9265-test suite was GREEN with this exclusion deleted. It could not
    have been otherwise: ``harness_repo`` builds ``.git`` as an EMPTY DIRECTORY,
    so ``_tracked_conflicts`` shells out to git, fails, and degrades to an empty
    ``withheld`` -- and the warn-branch fixtures monkeypatch ``withheld={}``
    explicitly. No test in the suite ever drove doctor with a non-empty
    ``withheld``, so no mutation of that filter could red.

    This needs a REAL git repo, which is why it does not reuse ``harness_repo``.
    """

    @staticmethod
    def _repo_tracking_settings(tmp_path: Path) -> Path:
        import subprocess

        from espalier.cli import REQUIRED_GITIGNORE

        repo = tmp_path / "tracked"
        (repo / ".claude").mkdir(parents=True)
        (repo / "README.md").write_text("# r\n", encoding="utf-8")
        (repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        # One deployed file under a harness-owned root, so doctor reads this
        # as an initialized tree whose surface is partly missing -- the
        # branch these tests drive -- and not, since DEF-770, as an
        # uninstalled one: a settings.json with nothing deployed beside it is
        # exactly the state an uninstall leaves, and reads as never
        # initialized (no gitignore report; init's own check owns that).
        (repo / "cc").mkdir()
        (repo / "cc" / "COMMANDS.md").write_text("# commands\n", encoding="utf-8")
        # Every required entry present EXCEPT the one git tracks, so the only
        # thing the check can speak about is the withheld path.
        (repo / ".gitignore").write_text(
            "\n".join(e for e in REQUIRED_GITIGNORE
                      if e != ".claude/settings.json") + "\n",
            encoding="utf-8",
        )
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(repo))
        subprocess.check_call(["git", "add", "-A"], cwd=str(repo))
        subprocess.check_call(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "adopter tracks its own settings"], cwd=str(repo),
        )
        return repo

    def test_status_marks_the_tracked_entry_withheld(self, tmp_path):
        from espalier.cli import gitignore_status

        repo = self._repo_tracking_settings(tmp_path)
        status = gitignore_status(repo)

        assert ".claude/settings.json" in status.missing, "precondition"
        assert ".claude/settings.json" in status.withheld, (
            "git tracks .claude/settings.json but gitignore_status did not "
            f"withhold it; withheld={dict(status.withheld)}"
        )

    def test_doctor_never_advises_ignoring_a_tracked_path(self, tmp_path):
        repo = self._repo_tracking_settings(tmp_path)

        result = run_doctor_check(repo, skip_self_host=True)

        offending = [
            n for n in result["next_steps"]
            if ".gitignore" in n and ".claude/settings.json" in n
        ]
        assert not offending, (
            "doctor told the operator to ignore a path git already tracks -- "
            f"the tracked-and-ignored state DEF-11 exists to prevent: {offending}"
        )

    def test_doctor_still_reports_the_withheld_entry_as_context(self, tmp_path):
        """Both directions. (a) alone passes if the branch stops firing at all."""
        repo = self._repo_tracking_settings(tmp_path)

        result = run_doctor_check(repo, skip_self_host=True)

        mentions = [i for i in result["info"] if ".claude/settings.json" in i]
        assert mentions, (
            "the withheld entry vanished entirely -- it must be reported as "
            f"context so the operator can act on it. info={result['info']}"
        )

    # DEF-635: `missing` is git's verdict when git can answer and a
    # line-exact spelling compare when it cannot. The compare reads a
    # broader pattern that already covers an entry (`*.py[cod]` for `*.pyc`)
    # as absent, so a report built on it must say which oracle answered.
    @classmethod
    def _doctor_with_status(cls, monkeypatch, tmp_path, **fields):
        from espalier import cli as _cli
        from espalier.cli import GitignoreStatus
        repo = cls._repo_tracking_settings(tmp_path)
        base = dict(exists=True, missing=("*.pyc",), unanchored=(),
                    withheld={}, shared={})
        base.update(fields)
        monkeypatch.setattr(
            _cli, "gitignore_status", lambda root: GitignoreStatus(**base)
        )
        return run_doctor_check(repo, skip_self_host=True)

    def test_doctor_names_the_spelling_fallback_when_git_could_not_answer(
        self, tmp_path, monkeypatch,
    ):
        result = self._doctor_with_status(monkeypatch, tmp_path, oracle="line-exact")
        assert any("*.pyc" in w for w in result["warnings"]), result["warnings"]
        qualified = [i for i in result["info"] if "line-for-line" in i]
        assert qualified, (
            "the .gitignore verdict came from the spelling compare and doctor "
            f"let it wear git's certainty. info={result['info']}"
        )

    def test_doctor_stays_silent_about_the_oracle_when_git_answered(
        self, tmp_path, monkeypatch,
    ):
        """Both directions: the qualifier must not become a standing line."""
        result = self._doctor_with_status(monkeypatch, tmp_path, oracle="git")
        assert any("*.pyc" in w for w in result["warnings"]), result["warnings"]
        assert not [i for i in result["info"] if "line-for-line" in i], result["info"]


class TestNextStepsNameEachCommandOnce:
    """A report must not list the same command twice in different wording.

    Driven 2026-08-26: a corrupt `reports/repo_fingerprint.json` trips BOTH the
    unreadable-file failure and the saved-reports-drift warning, and both want
    `espalier fingerprint .`. The report carried it twice, phrased differently,
    which reads as two separate things to do. The existing case-insensitive
    whole-string dedup (used for the recovery forwarding) cannot see it, because
    the sentences differ; `_append_step` dedupes on the backticked command.
    """

    @staticmethod
    def _commands(next_steps):
        import re
        found = []
        for step in next_steps:
            m = re.search(r"`([^`]+)`", step)
            if m:
                found.append(m.group(1))
        return found

    def test_a_corrupt_report_names_fingerprint_once(self, tmp_path):
        import subprocess
        import sys as _sys

        repo = tmp_path / "adopter"
        repo.mkdir()
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(repo))
        (repo / "README.md").write_text("# a\n", encoding="utf-8")
        subprocess.run(
            [_sys.executable, "-m", "espalier.cli", "init", str(repo)],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, timeout=300,
        )
        (repo / "reports" / "repo_fingerprint.json").write_text(
            "not json{{{", encoding="utf-8"
        )

        result = run_doctor_check(repo, skip_self_host=True)

        commands = self._commands(result["next_steps"])
        dupes = [c for c in set(commands) if commands.count(c) > 1]
        assert not dupes, (
            f"doctor named the same command more than once: {dupes}\n"
            f"next_steps={result['next_steps']}"
        )

    def test_the_fixture_actually_trips_the_two_branches(self, tmp_path):
        """Trip-guard: if the state stops producing both branches, the test
        above passes without testing anything."""
        import subprocess
        import sys as _sys

        repo = tmp_path / "adopter2"
        repo.mkdir()
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(repo))
        (repo / "README.md").write_text("# a\n", encoding="utf-8")
        subprocess.run(
            [_sys.executable, "-m", "espalier.cli", "init", str(repo)],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, timeout=300,
        )
        (repo / "reports" / "repo_fingerprint.json").write_text(
            "not json{{{", encoding="utf-8"
        )

        result = run_doctor_check(repo, skip_self_host=True)

        assert any("unreadable" in f for f in result["failures"]), (
            "the corrupt-report fixture no longer trips the unreadable failure"
        )
        assert any("fingerprint" in n for n in result["next_steps"]), (
            "no fingerprint action at all -- the dedupe may have eaten both"
        )


@pytest.mark.integration
class TestPartialDisarmNamesAShapeCorrectAction:
    """doctor's loudest verdict must arrive with an action, and the action must
    be one that works on THIS tree.

    `_primary_reason` surfaces `failures[0]`, so on the partial-disarm branch
    the headline verdict used to be paired with `next_steps == []` — the most
    alarming thing doctor says, and nothing to do about it.

    The subtlety that makes this more than a missing append: the remedy is
    SHAPE-dependent and only one shape has a command. Driven 2026-08-27 and
    asserted below rather than described:

      deleted event  -> `merge-settings` tops it up, gate returns, status pass
      inert command  -> `merge-settings` is a NO-OP; nothing repairs it

    A prior session recorded merge-settings as a dead remedy for this whole
    branch. That record came from driving the INERT tree and generalising to
    both. Each row here therefore drives its own remedy and asserts the
    post-condition, because "doctor named a command" and "the operator is fixed"
    are different claims and this file has confused them before.
    """

    @staticmethod
    def _initialized(tmp_path: Path) -> Path:
        target = tmp_path / "adopter"
        target.mkdir()
        (target / "README.md").write_text("# t\n", encoding="utf-8")
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target)],
            capture_output=True, text=True, timeout=180, encoding="utf-8",
        )
        return target

    @staticmethod
    def _settings(target: Path) -> Path:
        return target / ".claude" / "settings.json"

    def test_deleted_event_names_merge_settings_and_it_repairs(self, tmp_path):
        from espalier.doctor import run_doctor_check
        from espalier.harness_config import unwired_governance_gates

        target = self._initialized(tmp_path)
        sp = self._settings(target)
        data = json.loads(sp.read_text(encoding="utf-8"))
        data["hooks"].pop("PreToolUse", None)
        sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        report = run_doctor_check(target)
        assert report["status"] == "fail"
        steps = report.get("next_steps") or []
        assert steps, "the loudest verdict doctor emits arrived with no action"
        assert any("merge-settings" in s for s in steps), steps

        # The remedy is a CLAIM until driven. Drive it.
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(target)],
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert unwired_governance_gates(target) == [], (
            "doctor named merge-settings and merge-settings did not repair it"
        )

    def test_inert_gates_do_not_name_a_command_that_does_nothing(self, tmp_path):
        from espalier.doctor import run_doctor_check
        from espalier.harness_config import unwired_governance_gates

        target = self._initialized(tmp_path)
        sp = self._settings(target)
        data = json.loads(sp.read_text(encoding="utf-8"))
        touched = 0
        for entries in data["hooks"].values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if any(isinstance(a, str) and "tools/cc/hooks/" in a
                           for a in (hook.get("args") or [])):
                        hook["command"] = "echo"
                        touched += 1
        assert touched, "fixture mutated nothing"
        sp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        before = unwired_governance_gates(target)
        assert before, "precondition: the gates must read as unwired"

        report = run_doctor_check(target)
        steps = report.get("next_steps") or []
        assert steps, "partial disarm handed back an empty action list"
        assert any("by hand" in s for s in steps), steps
        assert any("merge-settings . --repair" in s for s in steps), steps
        # The PLAIN merge is a no-op on this tree (driven below); `--repair`
        # is the opt-in that rewrites, and it is the one spelling allowed.
        assert not any(
            "run `" in s and "merge-settings" in s and "--repair" not in s
            for s in steps
        ), (
            "doctor pointed an operator at plain merge-settings for inert gates; "
            "driven, it is a no-op on this tree:\n" + "\n".join(steps)
        )

        # And prove the omission is earned, not cautious.
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(target)],
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert unwired_governance_gates(target) == before, (
            "merge-settings repaired the inert tree after all -- if that is "
            "true, this test and doctor's advice are both wrong"
        )

    def test_unrecognized_shape_still_gets_an_action(self, tmp_path,
                                                     monkeypatch):
        """The sibling of the same gap in ``cli._unwired_gate_diagnosis``.

        This branch dispatches on four known shapes. A fifth would match none
        of them, and this class exists precisely because the loudest verdict
        paired with no action is the defect (DEF-433). Here the gate is still
        NAMED by the per-gate failures, so an unknown shape costs the ACTION
        rather than the finding -- but that is still the branch's own bug, and
        it stays fixed only if something drives it.

        Fixed on BOTH surfaces in one change: the class is "a gate shape the
        narrator has no branch for", and its sites are this arm and cli's
        (STANDING_PRINCIPLES §8).
        """
        from espalier import harness_config
        from espalier.doctor import run_doctor_check

        target = self._initialized(tmp_path)
        settings = self._settings(target)
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("ConfigChange", None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        real = harness_config.classify_unwired_gate
        monkeypatch.setattr(
            harness_config, "classify_unwired_gate",
            lambda root, script: ("a_shape_from_the_future"
                                  if script == "config_guard.py"
                                  else real(root, script)),
        )
        steps = run_doctor_check(target).get("next_steps", [])

        assert any("config_guard.py" in s for s in steps), (
            "a gate in an unrecognized shape produced no next step at all, so "
            "doctor's headline verdict arrives with nothing to do about it:\n"
            + "\n".join(steps)
        )

    def test_merge_settings_step_names_what_it_leaves_behind(self, tmp_path):
        """Sister-site row: the caveat `cli._unwired_gate_diagnosis` carries was
        missing HERE, on the surface that shares its bucketing.

        Driven side by side on one mixed tree, before the fix:
          init  : "...wire the missing ConfigChange event -- this does NOT fix
                   stop_gate.py."
          doctor: "...wire the governance events missing from
                   .claude/settings.json"        <- no caveat at all
        An operator who runs the first step and sees success does not read the
        steps below it, so a list whose head looks total is a false finish --
        which is the same defect on both surfaces, fixed on both
        (STANDING_PRINCIPLES §8).
        """
        from espalier.doctor import run_doctor_check

        target = self._initialized(tmp_path)
        settings = self._settings(target)
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("ConfigChange", None)          # absent -> repairable
        for entry in data["hooks"]["Stop"]:              # inert  -> not
            for hook in entry.get("hooks", []):
                hook["command"] = "echo"
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        steps = run_doctor_check(target).get("next_steps", [])
        merge_step = next((s for s in steps if "merge-settings" in s), None)

        assert merge_step, "doctor stopped offering merge-settings:\n" + "\n".join(steps)
        assert "stop_gate.py" in merge_step, (
            "doctor's merge-settings step does not name the gate it leaves "
            "dead, so its first line reads as a complete fix:\n" + merge_step
        )

    def test_every_shape_gets_a_doctor_next_step(self, tmp_path, monkeypatch):
        """The cli-side twin of this gate shipped alone; that is a half-swept
        class fix, which is the defect (STANDING_PRINCIPLES §8).

        ⚠ Must assert on ``next_steps``, NOT on the whole report. ``failures``
        names every deployed gate regardless of shape, so "the gate appears
        somewhere in doctor's output" passes vacuously for a shape with no
        branch at all — born weak. The ACTION is what a missing branch costs
        (DEF-433: a verdict paired with nothing to do), so the action is what
        this pins.

        Monkeypatching ``harness_config.group_unwired_gates_by_shape`` reaches
        doctor because doctor imports the MODULE. It would not reach ``cli``,
        which imports the classifier by value at cli.py:79 — a split verified
        this session, and the reason the cli-side gate is written differently.
        """
        from espalier import doctor, harness_config

        target = self._initialized(tmp_path)
        for shape in sorted(harness_config.GATE_SHAPES):
            monkeypatch.setattr(
                harness_config, "group_unwired_gates_by_shape",
                lambda _root, _s=shape: {_s: ["write_guard.py"]},
            )
            steps = doctor.run_doctor_check(target).get("next_steps", [])
            if shape == harness_config.GATE_ABSENT:
                # The ONE exemption, and it is earned rather than convenient:
                # absent gates share a single command that repairs all of them
                # at once, and `failures` already enumerates each gate + event.
                # Naming every script inside the command line would be noise.
                # ⚠ Exactly one shape may sit here; a second means the pattern
                # has stopped being an exemption and started being a hole.
                assert any("merge-settings" in s for s in steps), (
                    "the absent shape lost its repairing command: "
                    f"{steps!r}"
                )
                continue
            assert any("write_guard.py" in s for s in steps), (
                f"shape {shape!r} produces no doctor next_step naming the "
                f"affected gate, so the operator gets a verdict and no action.\n"
                f"  next_steps: {steps!r}"
            )

    def test_neither_arm_offers_a_merge_the_merge_will_refuse(self, tmp_path):
        """`doctor` offers merge-settings from TWO arms; both named it on files
        the merge refuses whole.

        `merge_hooks_into_settings` returns MERGE_BAD_HOOKS the moment any
        canonical event's value is a truthy non-list -- it does not skip the bad
        event and top up the rest. Driven 2026-08-27 on both arms: doctor said
        "run merge-settings", the merge returned `bad_hooks`, and nothing was
        written. Found in review on `cli`'s sibling site and fixed on all three
        (STANDING_PRINCIPLES §8: class-fix scope is every shipped surface).
        """
        from espalier.cli import merge_hooks_into_settings
        from espalier.doctor import run_doctor_check

        # Arm 1: partial disarm -- some gates wired, one event malformed.
        target = self._initialized(tmp_path)
        settings = self._settings(target)
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("ConfigChange", None)
        data["hooks"]["PreToolUse"] = "malformed-not-a-list"
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        steps = run_doctor_check(target).get("next_steps", [])
        assert not any(s.startswith("run") and "merge-settings" in s
                       for s in steps), (
            "doctor offered a command that refuses this file:\n"
            + "\n".join(steps)
        )
        assert any("hooks.PreToolUse" in s for s in steps), (
            "the real blocker was not named:\n" + "\n".join(steps)
        )
        # Earned, not cautious: the merge really does refuse.
        assert merge_hooks_into_settings(
            settings, profile="workflow", repo_root=target
        ).status == "bad_hooks"

    def test_a_wellformed_absent_tree_still_gets_the_offer(self, tmp_path):
        """The control for the row above.

        Withholding the offer everywhere would pass that row and lose the whole
        point: on a well-formed tree with a deleted event, merge-settings IS the
        remedy and doctor must still say so.
        """
        from espalier.cli import merge_hooks_into_settings
        from espalier.doctor import run_doctor_check

        target = self._initialized(tmp_path)
        settings = self._settings(target)
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("ConfigChange", None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        steps = run_doctor_check(target).get("next_steps", [])

        assert any("merge-settings" in s for s in steps), (
            "doctor stopped offering the command that repairs this tree:\n"
            + "\n".join(steps)
        )
        assert merge_hooks_into_settings(
            settings, profile="workflow", repo_root=target
        ).status == "wired"


class TestUnstampedSeedIsNamed:
    """DEF-691: an adopter who deletes a seed's first-line stamp gets the day-one
    fingerprint noise back, and until now only `upgrade` counted the state.
    `doctor` names it -- and only when it is true (the negative twin). Runs on a
    COPY of the real `adopter_tree` (an `espalier init`'d foreign repo), never
    the synthetic `harness_repo`, which deploys no seed at all -- the first cut
    asked that fixture and its own guard tripped.

    DEF-696: the remedy is the stamp ITSELF, printed. The earlier line sent the
    adopter to `git show HEAD:<file>`, which fails loudly for a seed that was
    never committed (the adopter with no other content-preserving path) and
    returns exit 0 with a plausible wrong line in the other two states. The
    remedy tests here read the stamp OFF THE PRINTED LINE and paste it, the
    way an adopter does, then check what the next `init` would do with it."""

    _STAMP_IN_LINE = r"(\S+): `(<!-- espalier:seed-version v\S+ sha256:[0-9a-f]{64} -->)`"

    def _printed_stamps(self, repo: Path) -> dict[str, str]:
        """rel -> stamp, parsed from doctor's own info line -- never recomputed,
        so the remedy under test is the one the adopter can actually perform."""
        import re
        from espalier.doctor import run_doctor_check
        hits = [s for s in run_doctor_check(repo)["info"] if "espalier:seed-version" in s]
        assert hits, "no unstamped-seed line to read the stamp from"
        return dict(re.findall(self._STAMP_IN_LINE, hits[0]))

    def _paste(self, seed: Path, stamp: str) -> None:
        """The remedy as printed: the stamp as line 1, above everything else."""
        seed.write_text(stamp + "\n" + seed.read_text(encoding="utf-8"), encoding="utf-8")

    @pytest.fixture
    def adopter_copy(self, adopter_tree, tmp_path):
        import shutil
        target = tmp_path / "adopter"
        shutil.copytree(adopter_tree, target, symlinks=True)
        return target

    def _seed(self, repo: Path) -> Path:
        from espalier.managed_inventory import get_seed_docs
        rels = [r for r in get_seed_docs() if (repo / r).is_file()]
        assert rels, "fixture drift: init deployed no seed doc"
        return repo / rels[0]

    def _strip_stamp(self, seed: Path) -> None:
        lines = seed.read_text(encoding="utf-8").splitlines(keepends=True)
        assert "espalier:seed-version" in lines[0], "fixture drift: seed is not stamped"
        seed.write_text("".join(lines[1:]), encoding="utf-8")

    def test_a_seed_without_its_stamp_gets_an_info_line(self, adopter_copy):
        from espalier.doctor import run_doctor_check
        seed = self._seed(adopter_copy)
        self._strip_stamp(seed)
        report = run_doctor_check(adopter_copy)
        hits = [s for s in report["info"] if "espalier:seed-version" in s]
        assert hits, report["info"]
        assert "1 seeded doc " in hits[0]
        rel = seed.relative_to(adopter_copy).as_posix()
        assert rel in hits[0], hits[0]
        assert "To keep your edits" in hits[0]
        # the remedy is the stamp itself, the exact line init writes (DEF-696);
        # not a git command the never-committed adopter cannot run, not a pipe
        from espalier.managed_inventory import render_seed_stamp
        assert f"{rel}: `{render_seed_stamp(rel).rstrip()}`" in hits[0], hits[0]
        assert "git show" not in hits[0]
        assert "| head" not in hits[0]
        assert "That stamp is the exact line" in hits[0]   # one stamp: singular
        assert "next three" not in hits[0]              # nothing past the cap
        assert "Only for a copy you never edited" in hits[0]
        # the stub consequence must ride in the LINE: a legacy tree's own
        # troubleshooting doc is an unstamped seed init preserves forever
        assert "near-empty stub" in hits[0]
        assert "upgrade --execute" not in hits[0]
        assert all(ord(ch) < 128 for ch in hits[0])

    def test_a_stamped_seed_gets_no_info_line(self, adopter_copy):
        from espalier.doctor import run_doctor_check
        report = run_doctor_check(adopter_copy)
        assert not [s for s in report["info"] if "espalier:seed-version" in s], report["info"]

    def test_the_self_host_tree_gets_no_info_line(self):
        """The docs HERE are the seed sources and carry no stamp; the first cut
        fired on 20 of 20 with a remedy that had no referent. The gate must have
        something to suppress, or this test proves nothing."""
        from espalier.doctor import run_doctor_check
        from espalier.managed_inventory import count_unstamped_seed_docs
        repo_root = Path(__file__).resolve().parents[1]
        assert count_unstamped_seed_docs(repo_root), "gate has nothing to suppress"
        report = run_doctor_check(repo_root)
        assert not [s for s in report["info"] if "espalier:seed-version" in s], report["info"]

    def test_the_printed_stamp_keeps_adopter_edits_with_nothing_committed(self, adopter_copy):
        """The remedy the line leads with, performed FROM the line, in the state
        the git-show remedy could not serve: the seed was never committed (the
        adopter tree commits before `init`, so every seed is untracked -- the
        precondition is asserted). The edits survive, the count is zero, and a
        real `init` PRESERVES the file: the stamp's digest is the packaged
        body's, so the edited copy keeps mismatching."""
        import os
        import subprocess
        import sys
        from espalier.managed_inventory import count_unstamped_seed_docs
        seed = self._seed(adopter_copy)
        rel = seed.relative_to(adopter_copy).as_posix()
        assert subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=adopter_copy, capture_output=True,
        ).returncode != 0, "precondition: the seed must be uncommitted (git show has nothing)"
        body = seed.read_text(encoding="utf-8").splitlines(keepends=True)[1:]
        seed.write_text("".join(body) + "ADOPTER CONTENT\n", encoding="utf-8")
        assert count_unstamped_seed_docs(adopter_copy) == 1
        self._paste(seed, self._printed_stamps(adopter_copy)[rel])
        assert count_unstamped_seed_docs(adopter_copy) == 0
        env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(adopter_copy)],
            capture_output=True, text=True, timeout=180, check=True,
            cwd=str(Path(__file__).resolve().parents[1]), env=env, encoding="utf-8",
        )
        assert "ADOPTER CONTENT" in seed.read_text(encoding="utf-8")
        assert count_unstamped_seed_docs(adopter_copy) == 0

    def test_the_printed_stamp_restores_untouched_status_on_a_tidied_copy(self, adopter_copy):
        """A body that IS today's packaged body with only the first line gone (a
        tidy that removed just the stamp). Pasted back, the stamp's digest
        matches the body again, so the copy is untouched as far as `init` and
        `upgrade` can tell: byte-identical packaged bytes are a no-churn skip and
        the next packaged drift REFRESHES it -- the git-show remedy could only
        restore that for a committed copy. The legacy-with-an-OLDER-body state
        is the next test, and it does NOT get this."""
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import count_unstamped_seed_docs, render_seed_body
        seed = self._seed(adopter_copy)
        rel = seed.relative_to(adopter_copy).as_posix()
        self._strip_stamp(seed)
        self._paste(seed, self._printed_stamps(adopter_copy)[rel])
        assert count_unstamped_seed_docs(adopter_copy) == 0
        assert _seed_redeploy_decision(seed, render_seed_body(rel)) == "preserve"
        assert _seed_redeploy_decision(seed, render_seed_body(rel) + "DRIFT\n") == "refresh"

    def test_a_legacy_copy_of_an_older_packaged_body_is_kept_but_not_refreshed(self, adopter_copy):
        """The third state as it really is: a pre-stamp deployment whose body is
        an OLDER packaged body. The printed stamp digests TODAY's body, so above
        the old one it never matches -- the noise is gone (the win), the copy is
        kept, and it will not be refreshed on the next drift. The first cut's
        prose promised the refresh here; the failure-mode pass drove it and got
        `preserve`. The line's other remedy, delete-then-`init`, is this copy's
        path to current bytes, which is why it is offered for a never-edited
        copy."""
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import count_unstamped_seed_docs, render_seed_body
        seed = self._seed(adopter_copy)
        rel = seed.relative_to(adopter_copy).as_posix()
        seed.write_text(render_seed_body(rel) + "<!-- an older release's tail -->\n", encoding="utf-8")
        assert count_unstamped_seed_docs(adopter_copy) == 1
        self._paste(seed, self._printed_stamps(adopter_copy)[rel])
        assert count_unstamped_seed_docs(adopter_copy) == 0
        assert "an older release's tail" in seed.read_text(encoding="utf-8")
        assert _seed_redeploy_decision(seed, render_seed_body(rel)) == "preserve"
        assert _seed_redeploy_decision(seed, render_seed_body(rel) + "DRIFT\n") == "preserve"

    def test_a_tidied_tier2_seed_keeps_its_edits_under_the_printed_stamp(self, adopter_copy):
        """The adopter the row names: one who tidied a Tier-2 header -- the stamp
        AND the adapt-header comment below it -- and wrote their own note. The
        printed stamp goes above what they kept; its digest (of header + asset)
        never matches, so the next `init` preserves the file, header still gone."""
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import (
            SEED_ADAPT_HEADER,
            count_unstamped_seed_docs,
            render_seed_body,
            seed_needs_adapt_header,
        )
        rel = "docs/FAILURE_MODES.md"
        assert seed_needs_adapt_header(rel)
        seed = adopter_copy / rel
        text = seed.read_text(encoding="utf-8")
        below_stamp = text.split("\n", 1)[1]
        assert below_stamp.startswith(SEED_ADAPT_HEADER), "fixture drift: no adapt header"
        seed.write_text(below_stamp[len(SEED_ADAPT_HEADER):] + "MY NOTE\n", encoding="utf-8")
        assert count_unstamped_seed_docs(adopter_copy) == 1
        self._paste(seed, self._printed_stamps(adopter_copy)[rel])
        assert count_unstamped_seed_docs(adopter_copy) == 0
        assert _seed_redeploy_decision(seed, render_seed_body(rel)) == "preserve"
        kept = seed.read_text(encoding="utf-8")
        assert "MY NOTE" in kept and SEED_ADAPT_HEADER not in kept

    def test_a_bom_crlf_paste_still_counts_as_stamped(self, adopter_copy):
        """The other platform: pasted in Notepad, saved with a BOM and CRLF. The
        fingerprint's predicate folds both, so the seed is stamped again; the
        redeploy decision reads the BOM as an edit and preserves -- the safe
        side, and the line's promise (your copy is kept) still holds."""
        from espalier.cli import _seed_redeploy_decision
        from espalier.managed_inventory import count_unstamped_seed_docs, render_seed_body
        from espalier.managed_markers import path_has_seed_stamp
        seed = self._seed(adopter_copy)
        rel = seed.relative_to(adopter_copy).as_posix()
        self._strip_stamp(seed)
        stamp = self._printed_stamps(adopter_copy)[rel]
        rest = seed.read_text(encoding="utf-8").replace("\n", "\r\n")
        seed.write_bytes(("\ufeff" + stamp + "\r\n" + rest).encode("utf-8"))
        assert path_has_seed_stamp(seed)
        assert count_unstamped_seed_docs(adopter_copy) == 0
        assert _seed_redeploy_decision(seed, render_seed_body(rel)) == "preserve"

    def test_each_named_seed_gets_its_own_stamp_and_no_other(self, adopter_copy):
        """Past the three-name cap the line stamps exactly the three it names, in
        the same order, and says the next three come on the next run -- a stamp
        for a file the line does not name would be one the adopter pastes on
        the wrong file."""
        from espalier.doctor import run_doctor_check
        from espalier.managed_inventory import get_seed_docs, render_seed_stamp
        present = [r for r in get_seed_docs() if (adopter_copy / r).is_file()]
        assert len(present) > 4
        for rel in present:
            self._strip_stamp(adopter_copy / rel)
        hit = [s for s in run_doctor_check(adopter_copy)["info"] if "espalier:seed-version" in s][0]
        named = hit.split("(", 1)[1].split(" (+", 1)[0].split(", ")
        assert len(named) == 3, named
        stamps = self._printed_stamps(adopter_copy)
        assert list(stamps) == named, (list(stamps), named)
        for rel in named:
            assert stamps[rel] == render_seed_stamp(rel).rstrip()
        assert "Each stamp is the exact line" in hit
        assert "`doctor` names and stamps the next three" in hit
        assert all(ord(ch) < 128 for ch in hit)

    @pytest.mark.parametrize("exc", [FileNotFoundError, zipfile.BadZipFile, KeyError, TypeError])
    def test_an_unreadable_packaged_copy_is_named_without_a_stamp(self, adopter_copy, monkeypatch, exc):
        """A diagnostic must not crash on the broken install it is diagnosing:
        a seed whose packaged asset cannot be rendered is still named, with the
        cause and a re-install pointer where its stamp would be. A package-
        resource read raises a wider family than a filesystem read -- the
        first cut caught `(OSError, UnicodeDecodeError)` and the failure-mode
        pass drove `zipfile.BadZipFile` (not an `OSError`) to a bare traceback."""
        import espalier.managed_inventory as managed_inventory
        from espalier.doctor import run_doctor_check

        def _unreadable(rel: str) -> str:
            raise exc(rel)

        real_render = managed_inventory.render_seed_stamp   # BEFORE the patch
        monkeypatch.setattr(managed_inventory, "render_seed_stamp", _unreadable)
        seed = self._seed(adopter_copy)
        rel = seed.relative_to(adopter_copy).as_posix()
        self._strip_stamp(seed)
        hits = [s for s in run_doctor_check(adopter_copy)["info"] if "espalier:seed-version" in s]
        assert hits, "the line must still fire"
        assert f"{rel}: its packaged copy is unreadable in this install ({exc.__name__})" in hits[0], hits[0]
        assert "sha256:" not in hits[0]
        # and the line promises nothing it did not print: the code-review pass
        # drove the first cut saying "That is the exact line init writes" about
        # the re-install pointer itself
        assert "is the exact line" not in hits[0], hits[0]
        assert "Only for a copy you never edited" in hits[0]

        # mixed: one readable, one not -- the promise is made for the one stamp
        # that was printed, in the singular, and the unreadable one stays named
        other = next(
            r for r in managed_inventory.get_seed_docs()
            if r != rel and (adopter_copy / r).is_file()
        )
        self._strip_stamp(adopter_copy / other)
        monkeypatch.setattr(
            managed_inventory, "render_seed_stamp",
            lambda r: real_render(r) if r == other else _unreadable(r),
        )
        hits = [s for s in run_doctor_check(adopter_copy)["info"] if "espalier:seed-version" in s]
        assert f"{other}: `{real_render(other).rstrip()}`" in hits[0], hits[0]
        assert f"{rel}: its packaged copy is unreadable" in hits[0], hits[0]
        assert "That stamp is the exact line" in hits[0], hits[0]
        assert "Each stamp" not in hits[0]

    def test_the_consequential_seed_is_named_first(self, adopter_copy):
        """Past the three-name cap the grounding doc and the largest seed must
        surface, not the first three in authoring order (a review pass drove a
        20-file legacy tree naming three that produce none of the symptoms)."""
        from espalier.doctor import run_doctor_check
        from espalier.managed_inventory import get_seed_docs
        present = [r for r in get_seed_docs() if (adopter_copy / r).is_file()]
        assert "docs/CONVENTIONS.md" in present and len(present) > 4
        for rel in present:
            self._strip_stamp(adopter_copy / rel)
        report = run_doctor_check(adopter_copy)
        hit = [s for s in report["info"] if "espalier:seed-version" in s][0]
        named = hit.split("(", 1)[1].split(")", 1)[0]
        assert named.startswith("docs/CONVENTIONS.md, docs/SHARP_EDGES.md, "), named
        assert "docs/FAILURE_MODES.md" in named, named
        assert f"(+{len(present) - 3} more)" in hit, hit
        # the key derives from the stub canon: with CONVENTIONS gone, the other
        # stub-backed seed still leads (a literal left it 19th of 19)
        (adopter_copy / "docs/CONVENTIONS.md").unlink()
        report = run_doctor_check(adopter_copy)
        hit = [s for s in report["info"] if "espalier:seed-version" in s][0]
        assert hit.split("(", 1)[1].startswith("docs/SHARP_EDGES.md, "), hit

    def test_the_named_remedy_re_seeds_the_doc(self, adopter_copy):
        """The line's remedy must WORK: an unstamped copy is preserved by `init`
        and `upgrade` on purpose, and the first cut named `upgrade --execute`,
        which re-seeded nothing (driven). Delete, then `init`."""
        import os
        import subprocess
        import sys
        from espalier.managed_inventory import count_unstamped_seed_docs
        seed = self._seed(adopter_copy)
        self._strip_stamp(seed)
        assert count_unstamped_seed_docs(adopter_copy) == 1
        seed.unlink()
        env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(adopter_copy)],
            capture_output=True, text=True, timeout=180, check=True,
            cwd=str(Path(__file__).resolve().parents[1]), env=env, encoding="utf-8",
        )
        assert seed.is_file()
        assert count_unstamped_seed_docs(adopter_copy) == 0

    def test_a_windows_resaved_unstamped_seed_is_still_counted(self, adopter_copy):
        """The counter is the fingerprint's own predicate: a strict read skipped
        a cp1252 resave and under-counted the very doc that had re-entered the
        fingerprint (failure-mode pass, driven)."""
        from espalier.managed_inventory import unstamped_seed_docs
        seed = self._seed(adopter_copy)
        self._strip_stamp(seed)
        seed.write_bytes(b"caf\xe9 -- not utf-8\n" + seed.read_bytes())
        assert seed.relative_to(adopter_copy).as_posix() in unstamped_seed_docs(adopter_copy)


class TestMergeOfferOnAFileTheMergeCannotRead:
    """DEF-700: on a settings.json the merge refuses BEFORE reading a hook
    value -- absent, empty, truncated, undecodable -- doctor must not hand back
    `merge-settings`, because that command exits 1 on exactly that file.

    Driven 2026-09-06 on a real init tree with settings.json truncated to 0
    bytes: the unreadable failure was right and its first step worked, then the
    unwired-gate lines pointed at a merge that could not run. The predicate's
    blanket `except` had read the parse failure as "not refused". Each row here
    earns its red against the real merge first.
    """

    SHAPES = [
        ("zero bytes", b""),
        ("whitespace only", b"  \n\t\n"),
        ("BOM only", b"\xef\xbb\xbf"),
        ("truncated object", b'{"hooks": {"PreToolUse": ['),
        ("not utf-8", b"\x80\x81{"),
        ("UTF-16 BOM only", b"\xff\xfe"),
    ]

    @pytest.mark.parametrize("label,raw", SHAPES, ids=[s[0] for s in SHAPES])
    def test_neither_arm_offers_the_merge(self, harness_repo, label, raw):
        from espalier.cli import merge_hooks_into_settings
        from espalier.doctor import _merge_would_be_refused, run_doctor_check

        settings = _gov_settings_path(harness_repo)
        settings.write_bytes(raw)
        # Earned: the merge really does refuse this file, before any value.
        assert merge_hooks_into_settings(
            settings, profile="workflow", repo_root=harness_repo
        ).status == "parse_error"
        refused = _merge_would_be_refused(harness_repo)
        assert refused and refused.startswith("unparseable"), refused

        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        steps = result.get("next_steps", [])
        assert not any(s.startswith("run") and "merge-settings" in s for s in steps), (
            f"[{label}] doctor offered a command that refuses this file:\n" + "\n".join(steps)
        )
        assert any("espalier init" in s for s in steps), steps

    def test_an_absent_file_is_refused_not_offered(self, harness_repo):
        from espalier.cli import merge_hooks_into_settings
        from espalier.doctor import _merge_would_be_refused, run_doctor_check

        settings = _gov_settings_path(harness_repo)
        settings.unlink()
        assert merge_hooks_into_settings(
            settings, profile="workflow", repo_root=harness_repo
        ).status == "no_file"
        assert _merge_would_be_refused(harness_repo) == "absent"
        steps = run_doctor_check(harness_repo, skip_self_host=True).get("next_steps", [])
        assert not any(s.startswith("run") and "merge-settings" in s for s in steps), steps
        # The offer arm's own sentence is folded away: it spells the init
        # command exactly as the presence branch does, so `_append_step` keeps
        # the presence step and drops the arm's. (Other branches legitimately
        # name `espalier init` too, so this is not a count of the phrase.)
        assert not any("no file to merge into" in s for s in steps), steps
        assert any("to initialize the harness" in s for s in steps), steps

    def test_empty_file_is_sent_to_init_in_place_not_moved_aside(self, harness_repo):
        from espalier.doctor import run_doctor_check

        settings = _gov_settings_path(harness_repo)
        settings.write_bytes(b"")
        steps = run_doctor_check(harness_repo, skip_self_host=True).get("next_steps", [])
        assert any("rewrites an empty file in place" in s for s in steps), steps
        assert not any("move .claude/settings.json aside" in s for s in steps), steps
        # A file with content, however broken, still gets the move-aside step.
        settings.write_bytes(b'{"hooks": {"PreToolUse": [')
        steps = run_doctor_check(harness_repo, skip_self_host=True).get("next_steps", [])
        assert any("move .claude/settings.json aside" in s for s in steps), steps
        assert not any("rewrites an empty file in place" in s for s in steps), steps

    FILE_SHAPES = [
        ("well-formed, one event deleted", "delete-event"),
        ("zero bytes", b""),
        ("truncated object", b'{"hooks": {"PreToolUse": ['),
        ("top-level list", b"[]\n"),
        ("hooks block is a string", b'{"hooks": "x"}\n'),
        ("over-long int literal", b"1" * 5000 + b"\n"),
        ("event value is a string", "bad-event"),
        (".claude is a plain file", "claude-is-a-file"),
        (".claude denies traversal", "claude-unreadable"),
    ]

    #: What each refusing shape's rendered sentence must say -- and, for the
    #: hooks-block row, must NOT say: the first renderer called it "top level".
    EXPECTED_SENTENCE = {
        "zero bytes": ("does not parse", None),
        "truncated object": ("does not parse", None),
        "top-level list": ("top level is a list", None),
        "hooks block is a string": ("hooks block", "top level"),
        "over-long int literal": ("does not parse", None),
        "event value is a string": ("hooks.PreToolUse", None),
        ".claude is a plain file": ("no file to merge into", "does not parse"),
        # DEF-763: a parent that denies traversal is UNREADABLE, never absent.
        # "no file" sent the adopter to `init` on a directory it cannot
        # search; the permission is the remedy, and it is the same sentence
        # on CPython 3.10-3.13 (where pathlib raised here) and 3.14 (where it
        # swallowed the error into "absent").
        ".claude denies traversal": ("could not be read", "no file"),
    }

    @pytest.mark.parametrize("label,shape", FILE_SHAPES, ids=[s[0] for s in FILE_SHAPES])
    def test_predicate_agrees_with_the_merge_at_the_file_level(self, harness_repo, label, shape):
        """The file-level twin of test_merge_settings' refusal-oracle matrix:
        the predicate must answer for the merge on the shapes the merge decides
        before it reads a value, not only on the value shapes."""
        from espalier.cli import merge_hooks_into_settings
        from espalier.doctor import _merge_would_be_refused

        import shutil
        import stat

        from espalier.cli import merge_refusal_step

        settings = _gov_settings_path(harness_repo)
        claude_dir = settings.parent
        restore = None
        if shape == "claude-is-a-file":
            shutil.rmtree(claude_dir)
            claude_dir.write_text("not a directory\n", encoding="utf-8")
        elif shape == "claude-unreadable":
            if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
                pytest.skip("needs POSIX permissions and a non-root user")
            claude_dir.chmod(0)
            restore = stat.S_IRWXU
        elif isinstance(shape, bytes):
            settings.write_bytes(shape)
        else:
            data = json.loads(settings.read_text(encoding="utf-8"))
            data["hooks"].pop("ConfigChange", None)
            if shape == "bad-event":
                data["hooks"]["PreToolUse"] = "malformed-not-a-list"
            settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            predicted = _merge_would_be_refused(harness_repo)
            actual = merge_hooks_into_settings(
                settings, profile="workflow", repo_root=harness_repo
            )
        finally:
            if restore is not None:
                claude_dir.chmod(restore)
        refused = actual.status in (
            "no_file", "unreadable", "parse_error", "not_object", "bad_hooks",
        )
        assert bool(predicted) == refused, (
            f"[{label}] predicate said {predicted!r}, merge said {actual.status!r}"
        )
        if shape == "claude-unreadable":
            # Both sides name the permission, with the OS's own words.
            assert actual.status == "unreadable" and "Permission denied" in actual.detail, actual
            assert predicted.startswith("unreadable: ") and "Permission denied" in predicted, predicted
        if shape == "bad-event":
            # The value-level verdict carries the merge's own detail, verbatim.
            assert predicted == "hooks.PreToolUse: str", predicted
        if refused:
            must, must_not = self.EXPECTED_SENTENCE[label]
            sentence = merge_refusal_step(predicted, "python3")
            assert must in sentence, f"[{label}] {sentence}"
            if must_not:
                assert must_not not in sentence, f"[{label}] {sentence}"
            assert "refuses" in sentence or "no file" in sentence or "cannot read" in sentence, sentence


class TestDoctorNamesTheProfileAllowRulesTheFileLacks:
    """DEF-715: a profile allow rule added after an install never reaches the
    operator's settings.json (the merge preserves permissions by contract), so
    doctor says which rules of the INSTALLED profile the file lacks -- as info,
    never a failure -- with the opt-in that appends them, spelled for that
    profile. Driven on real `init` trees, one per profile: a fresh install
    lacks nothing whichever profile rendered it (the first cut compared every
    install against `workflow` and told a `minimal` install it lacked `Write`).
    """

    @staticmethod
    def _initialized(tmp_path: Path, profile: str | None = None) -> Path:
        target = tmp_path / "adopter"
        target.mkdir()
        (target / "README.md").write_text("# t\n", encoding="utf-8")
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        argv = [sys.executable, "-m", "espalier.cli", "init", str(target)]
        if profile:
            argv += ["--profile", profile]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180, encoding="utf-8")
        assert proc.returncode == 0, proc.stderr
        assert (target / ".claude" / "settings.json").is_file(), "init wrote no settings.json"
        return target

    @staticmethod
    def _lacking(result) -> list[str]:
        return [i for i in result["info"] if "lacks" in i and "allow rule" in i]

    @pytest.mark.parametrize("profile", ["workflow", "minimal", "full", "self-host"])
    def test_a_fresh_init_tree_lacks_nothing_whichever_profile_rendered_it(self, tmp_path, profile):
        from espalier.doctor import run_doctor_check
        target = self._initialized(tmp_path, profile)
        result = run_doctor_check(target, skip_self_host=True)
        assert not self._lacking(result), result["info"]

    def test_a_removed_profile_rule_is_named_with_the_opt_in_for_that_profile(self, tmp_path):
        from espalier.doctor import run_doctor_check
        target = self._initialized(tmp_path, "workflow")
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"]["allow"] = [r for r in data["permissions"]["allow"] if r != "Bash(python3 -m pytest *)"]
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result = run_doctor_check(target, skip_self_host=True)
        lines = self._lacking(result)
        assert len(lines) == 1, result["info"]
        assert "Bash(python3 -m pytest *)" in lines[0]
        assert "--profile workflow --add-allows" in lines[0]
        assert not any("allow rule" in x for x in result["failures"] + result["warnings"]), "info, never a failure or warning"

    def test_a_malformed_permissions_block_is_named_not_measured(self, tmp_path):
        from espalier.doctor import run_doctor_check
        target = self._initialized(tmp_path)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"] = "nope"
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result = run_doctor_check(target, skip_self_host=True)
        assert not self._lacking(result)
        assert any("could not be compared" in i and "str" in i for i in result["info"]), result["info"]


class TestStatuslineFallbackNotes:
    """DEF-508: `_statusline_fallback_notes` says, as INFO, when the
    interpreter-missing fallback in `statusLine.command` disagrees with the
    host -- absent on a POSIX host (rendered before it existed), present on a
    Windows host (rendered elsewhere, carried in by a tracked settings.json).
    Neither breaks a guard, so neither is a warning."""

    @staticmethod
    def _settings(tmp_path, command):
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"hooks": {}}
        if command is not None:
            body["statusLine"] = {"type": "command", "command": command}
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def test_posix_host_without_the_clause_is_told_where_the_clause_is(
        self, tmp_path, monkeypatch
    ):
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        path = self._settings(
            tmp_path, 'python3 "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py"'
        )
        notes = doctor_module._statusline_fallback_notes(path, tmp_path)
        assert len(notes) == 1, notes
        assert "settings.json.new" in notes[0]
        assert "-m espalier init ." in notes[0]

    def test_posix_host_with_the_clause_is_silent(self, tmp_path, monkeypatch):
        from espalier import cli
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        path = self._settings(tmp_path, cli._statusline_command("python3", posix=True))
        assert doctor_module._statusline_fallback_notes(path, tmp_path) == []

    def test_windows_host_with_the_clause_gets_the_hand_edit(
        self, tmp_path, monkeypatch
    ):
        from espalier import cli
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        path = self._settings(tmp_path, cli._statusline_command("python", posix=True))
        notes = doctor_module._statusline_fallback_notes(path, tmp_path)
        assert len(notes) == 1, notes
        assert "PowerShell" in notes[0] and " || " in notes[0]

    def test_windows_host_with_the_shim_render_is_silent(self, tmp_path, monkeypatch):
        """The nt render is the shim head (DEF-729): the right shape for the
        host, nothing to say."""
        from espalier import cli
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        path = self._settings(tmp_path, cli._statusline_command("python", posix=False))
        assert doctor_module._statusline_fallback_notes(path, tmp_path) == []

    def test_windows_host_with_a_shim_head_that_also_carries_the_clause_gets_the_hand_edit(
        self, tmp_path, monkeypatch
    ):
        """A half-taken hand edit or a merge of two generations: the clause
        cannot parse under Windows PowerShell whatever the head is, so the
        clause note fires rather than the shim head silencing it."""
        from espalier import cli
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        hybrid = cli._statusline_command("python", posix=False) + " || echo 'x'"
        notes = doctor_module._statusline_fallback_notes(self._settings(tmp_path, hybrid), tmp_path)
        assert len(notes) == 1 and " || " in notes[0], notes

    def test_a_case_varied_shim_head_reads_as_the_shim(self, tmp_path, monkeypatch):
        """The string runs on Windows, whose filesystem is case-insensitive:
        a hand-edited `STATUSLINE.CMD` head runs the shim and is read as it
        by doctor and the rewire alike."""
        from espalier._venv import interpreter_site_token, is_statusline_shim_head
        from espalier import doctor as doctor_module

        head = '"${CLAUDE_PROJECT_DIR}\\tools\\cc\\STATUSLINE.CMD" python'
        assert is_statusline_shim_head('${CLAUDE_PROJECT_DIR}\\tools\\cc\\STATUSLINE.CMD')
        assert interpreter_site_token(head) == "python"
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        assert doctor_module._statusline_fallback_notes(self._settings(tmp_path, head), tmp_path) == []
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        notes = doctor_module._statusline_fallback_notes(self._settings(tmp_path, head), tmp_path)
        assert len(notes) == 1 and "statusline.cmd" in notes[0], notes

    def test_windows_host_with_the_plain_render_is_told_where_the_shim_is(
        self, tmp_path, monkeypatch
    ):
        """A Windows install rendered before the shim existed runs the script
        with no fallback at all: when `python` stops resolving the statusline
        goes blank. Same note as the POSIX no-clause case -- take the fresh
        render's statusLine line."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        path = self._settings(tmp_path, 'python "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py"')
        notes = doctor_module._statusline_fallback_notes(path, tmp_path)
        assert len(notes) == 1, notes
        assert "settings.json.new" in notes[0] and "no interpreter-missing fallback" in notes[0]

    def test_posix_host_with_the_shim_render_names_it(self, tmp_path, monkeypatch):
        """The third direction: a settings.json rendered on Windows and
        carried in by a tracked file (DEF-11). A POSIX shell cannot run a
        .cmd, so the statusline goes blank on a healthy install."""
        from espalier import cli
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        path = self._settings(tmp_path, cli._statusline_command("python", posix=False))
        notes = doctor_module._statusline_fallback_notes(path, tmp_path)
        assert len(notes) == 1, notes
        assert "tools/cc/statusline.cmd" in notes[0] and "settings.json.new" in notes[0]

    def test_the_shim_headed_statusline_is_checked_for_its_interpreter_argument(
        self, tmp_path, monkeypatch
    ):
        """The resolver check reads argv[1] behind the shim, the same helper
        the rewire reads (DEF-729): a broken interpreter ARGUMENT is warned
        about by name, and the shim path itself is never mistaken for one."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"hooks": [{"command": "python3"}]}]},
            "statusLine": {
                "type": "command",
                "command": '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" pythonX',
            },
        }), encoding="utf-8")
        from espalier import doctor as doctor_module
        monkeypatch.setattr(
            doctor_module.shutil, "which",
            lambda x, path=None: "/usr/bin/python3" if x == "python3" else None,
        )
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        assert any("pythonX" in i for i in issues), issues
        assert not any("statusline.cmd" in i for i in issues), issues

    def test_an_operators_own_statusline_is_not_examined(self, tmp_path, monkeypatch):
        """Only espalier's statusline (naming tools/cc/statusline.py) is ours
        to comment on; a brought-your-own script is theirs, and so is no
        statusLine on a tree where the script was never deployed (DEF-798:
        with the script deployed an absent key IS ours to name -- the sibling
        `test_an_absent_key_beside_the_deployed_script_names_the_state_and_the_verb`)."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        assert doctor_module._statusline_fallback_notes(
            self._settings(tmp_path, "~/.claude/statusline.sh"), tmp_path
        ) == []
        assert doctor_module._statusline_fallback_notes(
            self._settings(tmp_path, None), tmp_path
        ) == []

    def test_the_note_reaches_the_doctor_report_as_info(self, tmp_path, monkeypatch):
        """Wired, not merely defined: the note lands in `info`, never in
        `warnings` or `failures`."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        settings = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["statusLine"]["command"] = data["statusLine"]["command"].split(" || ", 1)[0]
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        report = doctor_module.run_doctor_check(tmp_path)
        assert any("settings.json.new" in line for line in report["info"]), report["info"]
        assert not any("settings.json.new" in line for line in report["warnings"])
        assert not any("settings.json.new" in line for line in report["failures"])

    def test_an_absent_key_beside_the_deployed_script_names_the_state_and_the_verb(
        self, tmp_path, monkeypatch
    ):
        """DEF-798, the fourth shape: script and shim deployed, no key -- what
        --wire-hooks left on the Windows walk and on a POSIX throwaway
        (driven 2026-09-15: doctor passed with one INFO about allow rules).
        The key is the test; the deployed script says it is espalier's
        statusline that is missing; the verb named adds it."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "statusline.py").write_text("# stub\n", encoding="utf-8")
        notes = doctor_module._statusline_fallback_notes(self._settings(tmp_path, None), tmp_path)
        assert len(notes) == 1, notes
        assert "has no statusLine" in notes[0] and "-m espalier merge-settings ." in notes[0], notes
        assert "never touches one of your own" in notes[0], notes
        # Same answer on a Windows host: the state is host-independent.
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        assert doctor_module._statusline_fallback_notes(self._settings(tmp_path, None), tmp_path) == notes

    def test_upgrade_and_doctor_read_one_predicate_for_the_absent_key(self, tmp_path):
        """The two narrators of a deployed tree cannot disagree: doctor's fourth
        note and upgrade's version-current line both call
        `doctor.espalier_statusline_missing` (failure-mode review: the first
        cut gave upgrade a script-blind twin, so it named a state doctor was
        deliberately silent on). The predicate itself: key absent AND the
        script deployed; every other shape reads False."""
        import inspect

        from espalier import cli
        from espalier import doctor as doctor_module

        assert "espalier_statusline_missing(" in inspect.getsource(doctor_module._statusline_fallback_notes)
        assert "espalier_statusline_missing(" in inspect.getsource(cli.cmd_upgrade)
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        script = tmp_path / "tools" / "cc" / "statusline.py"
        absent = self._settings(tmp_path, None)
        assert doctor_module.espalier_statusline_missing(absent, tmp_path) is False, "no script: not ours"
        script.write_text("# stub\n", encoding="utf-8")
        assert doctor_module.espalier_statusline_missing(absent, tmp_path) is True
        for value in (None, "off", {}, {"type": "command", "command": "mine"}):
            body = {"hooks": {}, "statusLine": value}
            absent.write_text(json.dumps(body), encoding="utf-8")
            assert doctor_module.espalier_statusline_missing(absent, tmp_path) is False, value
        absent.write_text("not json", encoding="utf-8")
        assert doctor_module.espalier_statusline_missing(absent, tmp_path) is False

    def test_an_absent_key_with_no_deployed_script_is_silent(self, tmp_path, monkeypatch):
        """No espalier statusline to miss: a brought-your-own settings.json on
        a tree where init never ran keeps its silence (the sibling
        `test_an_operators_own_statusline_is_not_examined` pins the same
        file; this one pins WHY -- the script, not the host, decides)."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        assert not (tmp_path / "tools" / "cc" / "statusline.py").exists()
        assert doctor_module._statusline_fallback_notes(self._settings(tmp_path, None), tmp_path) == []

    def test_an_absent_key_reaches_the_report_as_info_and_the_verb_clears_it(
        self, tmp_path, monkeypatch
    ):
        """End to end: init, drop the key (an older wiring), doctor names the
        state as INFO -- never a warning or failure -- and merge-settings adds
        the key, after which doctor is silent again."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        settings = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        del data["statusLine"]
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        report = doctor_module.run_doctor_check(tmp_path)
        hits = [line for line in report["info"] if "has no statusLine" in line]
        assert len(hits) == 1 and "merge-settings ." in hits[0], report["info"]
        assert not any("statusLine" in line for line in report["warnings"] + report["failures"])
        subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(tmp_path)],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        assert "statusLine" in json.loads(settings.read_text(encoding="utf-8"))
        report = doctor_module.run_doctor_check(tmp_path)
        assert not any("has no statusLine" in line for line in report["info"]), report["info"]




def _reporter_warnings(result: dict) -> list[str]:
    return [w for w in result.get("warnings", []) if "reporter hook not wired" in w]


class TestReporterHookWiring:
    """DEF-619: the wiring oracle was pinned to the four blocking gates, so a
    reporter (SubagentStart, PostToolUseFailure, PostCompact, ...) could be
    deleted or neutered with `init` claiming armed and `doctor` at pass. Now a
    deployed reporter with no executable wiring is a WARNING -- never a
    failure, so the gate count stays parity-locked with ci_guard."""

    def test_faithful_baseline_has_no_reporter_warning(self, harness_repo):
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert _reporter_warnings(result) == [], _reporter_warnings(result)

    def test_deleted_reporter_event_warns_and_names_the_merge(self, harness_repo):
        data = _load_settings(harness_repo)
        data["hooks"].pop("PostCompact")
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        warns = _reporter_warnings(result)
        assert any("post_compact.py" in w and "'PostCompact'" in w for w in warns), warns
        assert any("merge-settings" in w for w in warns), warns
        # A warning, never a failure: the blocking-gate oracle is untouched.
        assert result["status"] == "warn", result["status"]
        assert _governance_failures(result) == []
        assert any("doctor" in step for step in result["next_steps"]), result["next_steps"]

    def test_neutered_reporter_warns_with_the_hand_edit(self, harness_repo):
        data = _load_settings(harness_repo)
        for entry in data["hooks"]["PostToolUse"]:
            for hook in entry["hooks"]:
                if "reflect_trigger.py" in json.dumps(hook):
                    hook["command"] = "echo"
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        warns = _reporter_warnings(result)
        assert any("reflect_trigger.py" in w and "runs no interpreter" in w for w in warns), warns
        assert not any("post_write_check.py" in w for w in warns), warns

    def test_orphaned_reporter_warns_that_merge_adds_nothing(self, harness_repo):
        data = _load_settings(harness_repo)
        data["hooks"]["PostToolUse"] = [
            e for e in data["hooks"]["PostToolUse"]
            if "post_write_check.py" not in json.dumps(e)
        ]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        warns = _reporter_warnings(result)
        assert any("post_write_check.py" in w and "carries no entry" in w for w in warns), warns

    def test_narrowed_post_write_check_matcher_is_not_wired(self, harness_repo):
        """Found by review: the coverage test stopped at the three mutation
        tools, so a matcher narrowed from the canonical
        `Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*` to the trio read as
        wired -- Bash, PowerShell and MCP writes silently unchecked."""
        data = _load_settings(harness_repo)
        for entry in data["hooks"]["PostToolUse"]:
            if "post_write_check.py" in json.dumps(entry):
                entry["matcher"] = "Write|Edit|NotebookEdit"
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        warns = _reporter_warnings(result)
        assert any("post_write_check.py" in w and "does not cover" in w for w in warns), (
            result["warnings"]
        )

    def test_narrowed_gate_matcher_is_miswired_not_legacy(self, harness_repo):
        """Driven 2026-09-07: plan_guard narrowed to `Write` classified
        legacy_form -- the one shape the enforcement claim forgives -- so
        `init` said "Hooks now intercept" over a gate that never fires on
        Edit. Readable means verifiably dead: its own shape, named in the
        next step with the half that is wrong."""
        from espalier import harness_config as hc

        data = _load_settings(harness_repo)
        for entry in data["hooks"]["PreToolUse"]:
            if "plan_guard.py" in json.dumps(entry):
                entry["matcher"] = "Write"
        _save_settings(harness_repo, data)
        assert hc.classify_unwired_gate(harness_repo, "plan_guard.py") == hc.GATE_MISWIRED
        assert "does not cover" in hc.miswiring_detail(harness_repo, "plan_guard.py")
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert result["status"] == "fail"
        assert any("plan_guard.py" in s and "does not cover" in s for s in result["next_steps"]), (
            result["next_steps"]
        )

    def test_gate_on_the_wrong_event_is_miswired_with_the_event_named(self, harness_repo):
        from espalier import harness_config as hc

        data = _load_settings(harness_repo)
        data["hooks"]["PostToolUseFailure"] = data["hooks"].pop("ConfigChange")
        _save_settings(harness_repo, data)
        assert hc.classify_unwired_gate(harness_repo, "config_guard.py") == hc.GATE_MISWIRED
        detail = hc.miswiring_detail(harness_repo, "config_guard.py")
        assert "'PostToolUseFailure' instead of 'ConfigChange'" in detail, detail

    def test_shell_form_reporter_is_reported_as_unverifiable_not_dead(self, harness_repo):
        """Driven by the failure-mode pass on a shell-form tree: the first cut
        called the hook dead and prescribed `--rewire-interpreter`, which
        swaps argv[0] of a bare interpreter and declines a shell string (the
        DEF-620 loop). The shape gets its own sentence and a hand-edit remedy."""
        data = _load_settings(harness_repo)
        data["hooks"]["PostCompact"] = [{"hooks": [{
            "type": "command",
            "command": "python3 ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/post_compact.py",
        }]}]
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        legacy = [w for w in result["warnings"]
                  if "reporter hook wired in a form this check cannot verify" in w]
        assert any("post_compact.py" in w and "most likely fires" in w for w in legacy), (
            result["warnings"]
        )
        assert not any("--rewire-interpreter" in w for w in legacy), legacy
        assert not any("post_compact.py" in w for w in _reporter_warnings(result))

    def test_unparseable_file_gets_no_per_hook_remedies(self, harness_repo):
        """Driven on a truncated settings.json: eight 'add the event by hand'
        lines beside a failure whose step is 'move it aside and re-run init'.
        You cannot add an event to a file that does not parse."""
        from espalier import doctor as doctor_module

        _gov_settings_path(harness_repo).write_text('{ "hooks": ', encoding="utf-8")
        assert doctor_module._check_reporter_hook_wiring(harness_repo) == []

    def test_reporter_warnings_come_after_every_other_warning(self, harness_repo, monkeypatch):
        """`_primary_reason` surfaces warnings[0]; a dead reporter must not
        outrank the interpreter or gitignore headline."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(
            doctor_module, "_check_python_resolver",
            lambda root: ["hook interpreter 'python' does not resolve on this host"],
        )
        data = _load_settings(harness_repo)
        data["hooks"].pop("PostCompact")
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert "reporter hook not wired" in result["warnings"][-1], result["warnings"]
        assert any("does not resolve" in w for w in result["warnings"][:-1]), result["warnings"]

    def test_undeployed_reporter_is_out_of_scope(self, harness_repo):
        """Keying on file-on-disk, exactly like the gates: a reporter that was
        never deployed is not a dead reporter."""
        (harness_repo / "tools" / "cc" / "hooks" / "post_compact.py").unlink()
        data = _load_settings(harness_repo)
        data["hooks"].pop("PostCompact")
        _save_settings(harness_repo, data)
        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert not any("post_compact.py" in w for w in _reporter_warnings(result))

    def test_voided_file_is_left_to_the_governance_failure(self, harness_repo):
        """One stray hook `type` voids the whole block; the governance FAILURE
        already says no hook loads, so per-reporter warnings would only
        contradict it with false per-entry remedies."""
        from espalier import doctor as doctor_module

        data = _load_settings(harness_repo)
        data["hooks"]["PostCompact"][0]["hooks"][0]["type"] = "prompt"
        _save_settings(harness_repo, data)
        assert doctor_module._check_reporter_hook_wiring(harness_repo) == []
        assert doctor_module._check_governance_event_wiring(harness_repo)

    def test_blocking_failure_count_is_untouched_by_a_dead_reporter(self, harness_repo):
        """The parity lock with ci_guard counts governance FAILURES; a reporter
        must never change that number in either direction."""
        from espalier import doctor as doctor_module

        before = len(doctor_module._check_governance_event_wiring(harness_repo))
        data = _load_settings(harness_repo)
        data["hooks"].pop("PostCompact")
        data["hooks"].pop("PostToolUse")
        _save_settings(harness_repo, data)
        assert len(doctor_module._check_governance_event_wiring(harness_repo)) == before
        assert len(doctor_module._check_reporter_hook_wiring(harness_repo)) == 3


# ── DEF-770: an uninstalled tree is uninstalled, not broken ──────────────


class TestDoctorUninstalledTree:
    """`clean-generated --execute` leaves the saved plan and the runtime
    markers on disk, so the tree still detected as an initialized consumer
    repo and fell to the saved-plan branch: `fail`, "missing required managed
    surface", and every removed hook script listed as a stale plan path --
    handed to an adopter confirming the uninstall took (driven 2026-09-11 on
    the §C8 lane's scratch tree, seventeen stale paths). Reported now as
    uninstalled, naming what was left behind and both next steps.

    The driven instance (init, the verb, then doctor) is
    `tests/test_adopter_lifecycle_diagnostics.py`; these build the leftover
    state by hand and drive the two controls that keep the fail verdict:
    one hook script left behind, and a settings.json that still wires one.
    """

    @staticmethod
    def _plan() -> dict:
        return {
            "agents": [{"name": "code-reviewer"}],
            "generated_docs": [".claude/commands/status.md"],
            "hooks": [],
        }

    def _leftover_tree(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# app\n", encoding="utf-8")
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            json.dumps(self._plan()), encoding="utf-8",
        )
        (reports / "repo_fingerprint.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".claude").mkdir()
        _save_settings(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        (tmp_path / ".espalier").mkdir()
        (tmp_path / ".espalier" / "integrity.json").write_text("{}", encoding="utf-8")
        return tmp_path

    def test_leftover_plan_and_markers_read_as_uninstalled(self, tmp_path):
        repo = self._leftover_tree(tmp_path)
        result = run_doctor_check(repo, skip_self_host=True)
        assert result["status"] == "uninitialized", result
        assert result["failures"] == [] and result["warnings"] == [], result
        assert "reports/harness_config.json" in result["primary_reason"], result
        # Derived from the mode detector's markers plus the saved reports,
        # minus the adopter's settings.json: what marks the tree initialized.
        assert set(result["leftovers"]) == {
            ".espalier/integrity.json",
            "reports/repo_fingerprint.json",
            "reports/harness_config.json",
        }, result["leftovers"]
        steps = result["next_steps"]
        assert any(re.search(r"[\w./-]+ -m espalier init \.", s) for s in steps), steps
        assert any(
            "reports/harness_config.json" in s and "preserved_user_files" in s
            for s in steps
        ), steps

    def test_deleting_the_named_leftovers_does_not_restore_the_fail_verdict(self, tmp_path):
        """The code review drove the first draft round-tripping: delete the
        three named files, and the adopter's unwired settings.json (a runtime
        marker, kept by contract) still detects the tree as initialized while
        the plan file's absence failed the branch's own gate -- `fail`, the
        JSON wall, exit 1. The advice must be terminal."""
        repo = self._leftover_tree(tmp_path)
        first = run_doctor_check(repo, skip_self_host=True)
        for rel in first["leftovers"]:
            (repo / rel).unlink()
        assert (repo / ".claude" / "settings.json").is_file()
        second = run_doctor_check(repo, skip_self_host=True)
        assert second["status"] == "uninitialized", second
        assert second["failures"] == [] and second["warnings"] == [], second
        assert not second.get("leftovers"), second

    def test_one_leftover_skill_file_keeps_the_broken_install_verdict(self, tmp_path):
        """The saved plan never lists skills (the failure-mode review drove
        it): a plan-only predicate read nine leftover SKILL.md files as
        uninstalled. Disk reality under the owned roots is read too."""
        repo = self._leftover_tree(tmp_path)
        skill = repo / ".claude" / "skills" / "review" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: review\n---\n# body\n", encoding="utf-8")
        result = run_doctor_check(repo, skip_self_host=True)
        assert result["status"] == "fail", result["status"]

    def test_one_hook_script_left_on_disk_keeps_the_broken_install_verdict(self, tmp_path):
        repo = self._leftover_tree(tmp_path)
        hook = repo / "tools" / "cc" / "hooks" / "write_guard.py"
        hook.parent.mkdir(parents=True)
        hook.write_text("# a hook script the uninstall did not take\n", encoding="utf-8")
        result = run_doctor_check(repo, skip_self_host=True)
        assert result["status"] == "fail", result["status"]
        assert any(
            "missing required managed surface" in f for f in result["failures"]
        ), result["failures"]

    def test_a_wired_espalier_hook_keeps_the_broken_install_verdict(self, tmp_path):
        repo = self._leftover_tree(tmp_path)
        _save_settings(repo, {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{
            "type": "command", "command": "python3",
            "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
        }]}]}})
        result = run_doctor_check(repo, skip_self_host=True)
        assert result["status"] == "fail", result["status"]

    def test_cli_prints_the_leftovers_and_exits_zero(self, tmp_path, capsys):
        from espalier.cli import cmd_doctor
        repo = self._leftover_tree(tmp_path)
        rc = cmd_doctor(argparse.Namespace(repo=str(repo), config=None))
        out = capsys.readouterr().out
        assert rc == 0
        assert "harness not on disk" in out, out
        assert "reports/harness_config.json" in out, out
        assert "preserved_user_files" in out, out
        assert ".claude/settings.json is yours" in out, out
        assert not out.lstrip().startswith("{"), out


class TestDoctorReportsOneMissingFileOnce:
    """DEF-786 (TP-449 Tier 2, 2026-09-12): a fresh init tree with one
    deployed command deleted. The audit line names the file; the recovery
    assessor sees the same file through cc/PACK_MANIFEST.txt and used to add
    `recovery check reported blocking conditions` beside it -- two errors
    for one fact, the second naming nothing. Driven, not faked: the shape is
    the ledger probe's."""

    @pytest.fixture
    def one_command_gone(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        rc = cmd_init(argparse.Namespace(repo=str(tmp_path), config=None))
        assert rc == 0
        (tmp_path / ".claude" / "commands" / "smoke.md").unlink()
        return tmp_path

    def test_the_audit_names_the_file_and_the_recovery_line_stands_down(self, one_command_gone):
        result = run_doctor_check(one_command_gone, skip_self_host=True)
        assert result["status"] == "fail", result["status"]
        naming = [f for f in result["failures"] if ".claude/commands/smoke.md" in f]
        assert len(naming) == 1, result["failures"]
        assert not [f for f in result["failures"] if "recovery check" in f], result["failures"]
        assert not [f for f in result["failures"] if "blocking conditions" in f], result["failures"]
        # The assessor's recommendation is still forwarded: the line stood
        # down, the advice did not.
        assert any("PACK_MANIFEST" in s for s in result["next_steps"]), result["next_steps"]

    def test_a_path_the_audit_did_not_name_is_named_on_the_recovery_line(
        self, one_command_gone, monkeypatch
    ):
        """The other half of the rule: when the assessor finds something the
        audit did not, the line prints and names it."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(
            doctor_module,
            "assess_repo_state",
            lambda root: {
                "status": "fail",
                "missing": ["reports/repo_fingerprint.json"],
                "manifest_missing_docs": [".claude/commands/smoke.md"],
                "recommendations": [],
            },
        )
        result = run_doctor_check(one_command_gone, skip_self_host=True)
        recovery = [f for f in result["failures"] if f.startswith("recovery check:")]
        assert len(recovery) == 1, result["failures"]
        assert "1 required paths missing" in recovery[0], recovery
        assert "1 manifest entries missing" in recovery[0], recovery
        assert "reports/repo_fingerprint.json" in recovery[0], recovery

    def test_a_path_that_is_a_substring_of_a_named_one_is_not_withheld(
        self, one_command_gone, monkeypatch
    ):
        """Named means a whole path token, never a substring: the audit names
        `.claude/commands/smoke.md`; the assessor's `commands/smoke.md` is a
        different claim and is said."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(
            doctor_module, "assess_repo_state",
            lambda root: {"status": "fail", "missing": ["commands/smoke.md"], "recommendations": []},
        )
        result = run_doctor_check(one_command_gone, skip_self_host=True)
        recovery = [f for f in result["failures"] if f.startswith("recovery check:")]
        assert len(recovery) == 1 and "commands/smoke.md" in recovery[0], result["failures"]

    def test_an_unreadable_report_survives_the_withhold(self, one_command_gone, monkeypatch):
        """Only the path clause can be withheld. An unreadable report is a
        fact the audit line never carries and is said; the gate status the
        assessor read is the report the audit just wrote, so with the audit
        failed above it is the same fact and is withheld too."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(
            doctor_module, "assess_repo_state",
            lambda root: {
                "status": "fail",
                "manifest_missing_docs": [".claude/commands/smoke.md"],   # the audit names it
                "surface_gate_status": "fail",                            # the audit's own report
                "unreadable_reports": ["reports/harness_config.json"],
                "fail_reasons": ["1 manifest entries missing", "surface gate status: fail"],
                "recommendations": [],
            },
        )
        result = run_doctor_check(one_command_gone, skip_self_host=True)
        recovery = [f for f in result["failures"] if f.startswith("recovery check:")]
        assert len(recovery) == 1, result["failures"]
        assert "reports/harness_config.json" in recovery[0], recovery
        assert "manifest entries missing" not in recovery[0], recovery
        assert "surface gate status" not in recovery[0], recovery

    def test_a_gate_status_the_audit_did_not_report_is_said(self, harness_repo, monkeypatch):
        """The audit passes on this tree, so a non-pass status in the report
        the assessor read is stale or foreign, and the recovery line is its
        only reporter."""
        from espalier import doctor as doctor_module

        monkeypatch.setattr(
            doctor_module, "assess_repo_state",
            lambda root: {"status": "fail", "surface_gate_status": "DEGRADED_MARKER",
                          "fail_reasons": ["surface gate status: DEGRADED_MARKER"],
                          "recommendations": []},
        )
        result = run_doctor_check(harness_repo, skip_self_host=True)
        recovery = [f for f in result["failures"] if f.startswith("recovery check:")]
        assert len(recovery) == 1 and "DEGRADED_MARKER" in recovery[0], result["failures"]


class TestDoctorOnAHalfInstalledConsumerTree:
    """DEF-785 (TP-449 Tier 2, 2026-09-12): the ledger probe's shape -- a
    consumer tree carrying settings.json, the saved plan and one cc/ doc.
    Driven through the CLI it printed two failures, the second
    `self-host surface gate: fail`, and `doctor: fail -- 2 errors`. The gate
    wraps the same check the audit already stands down on a missing surface,
    so it stands down too; the presence failure is the one error."""

    @staticmethod
    def _tree(tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "harness_config.json").write_text("{}", encoding="utf-8")
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "COMMANDS.md").write_text("# c\n", encoding="utf-8")
        return tmp_path

    def test_one_missing_surface_is_one_error_and_no_self_host_text(self, tmp_path):
        result = run_doctor_check(self._tree(tmp_path))
        assert result["status"] == "fail", result["status"]
        presence = [f for f in result["failures"] if "missing required managed surface" in f]
        assert len(presence) == 1, result["failures"]
        assert len(result["failures"]) == 1, result["failures"]
        assert not [f for f in result["failures"] if "self-host" in f], result["failures"]
        assert result["checks"]["self_host"]["status"] == "skipped"


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits and a non-root user",
)
class TestDoctorOnAClaudeItCannotRead:
    """DEF-763, driven on real 3.10, 3.13 and 3.14 interpreters 2026-09-13:
    with `.claude` mode 000, doctor on CPython 3.14 listed every deployed
    file as missing and offered `init` (which cannot write there either); on
    3.10-3.13 it died on the first `Path.exists()` with a bare `Permission
    denied` line. One failure, naming the permission and the remedy, on
    every interpreter."""

    @staticmethod
    def _run_locked(repo: Path, mode: int = 0) -> dict:
        from _locked import locked
        from espalier.doctor import run_doctor_check

        with locked(repo / ".claude", mode):
            return run_doctor_check(repo, skip_self_host=True)

    def test_one_failure_names_the_permission_not_a_missing_surface(self, harness_repo):
        result = self._run_locked(harness_repo)
        assert result["status"] == "fail", result
        assert ".claude cannot be read" in result["primary_reason"], result["primary_reason"]
        assert "Permission denied" in result["primary_reason"], result["primary_reason"]
        assert result["failures"] == [result["primary_reason"]], result["failures"]
        assert not [w for w in result["warnings"] if "stale saved-plan" in w], result["warnings"]

    def test_the_remedy_is_the_permission_never_init(self, harness_repo):
        steps = self._run_locked(harness_repo)["next_steps"]
        assert any("permissions" in s and "espalier doctor" in s for s in steps), steps
        assert not any("espalier init" in s for s in steps), steps

    @pytest.mark.parametrize("mode", [0o400, 0o100], ids=["read only", "search only"])
    def test_each_lock_shape_is_the_same_failure(self, harness_repo, mode):
        result = self._run_locked(harness_repo, mode)
        assert result["status"] == "fail" and ".claude cannot be read" in result["primary_reason"], result

    def test_a_readable_claude_is_untouched_by_the_gate(self, harness_repo):
        from espalier.doctor import run_doctor_check

        result = run_doctor_check(harness_repo, skip_self_host=True)
        assert ".claude cannot be read" not in result["primary_reason"], result["primary_reason"]
