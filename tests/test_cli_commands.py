"""Tests for the ``cmd_*`` command functions in ``espalier.cli``
(Task 1-A).

Each test calls a ``cmd_*`` function directly with a constructed
``argparse.Namespace`` and verifies the exit code and on-disk side
effects. The ``_ns()`` helper builds a Namespace with the defaults
every function needs so call sites stay minimal.

Pins the exit-code-and-side-effect contract for the full ``cmd_*``
surface (init, fingerprint, audit, doctor, diff, recover, reflect,
scan, clean-generated, release-pack, pre-release, blueprint,
worktree-plan, integrity, ...). Without this guard an argparse-
schema tweak or a refactor of ``main()`` could silently change a
command's return code or skip a side effect, breaking adopter
shell scripts that compose ``espalier`` with ``&&`` / ``||``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import pytest

from _locked import locked


def _ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace with sensible defaults for any cmd_* function."""
    defaults = {"config": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── cmd_init ────────────────────────────────────────────────────────────────


class TestCmdInit:
    def test_cmd_init_produces_reports(self, python_repo):
        """cmd_init writes repo_fingerprint.json and harness_config.json."""
        from espalier.cli import cmd_init

        ret = cmd_init(_ns(repo=str(python_repo)))
        assert ret == 0
        fp = python_repo / "reports" / "repo_fingerprint.json"
        hc = python_repo / "reports" / "harness_config.json"
        assert fp.exists()
        assert hc.exists()
        assert isinstance(json.loads(fp.read_text(encoding="utf-8")), dict)
        assert isinstance(json.loads(hc.read_text(encoding="utf-8")), dict)

    def test_cmd_init_prints_summary(self, python_repo, capsys):
        """cmd_init prints 'Initialized harness for' and 'Languages:' to stdout."""
        from espalier.cli import cmd_init

        cmd_init(_ns(repo=str(python_repo)))
        out = capsys.readouterr().out
        assert "Initialized harness for" in out
        assert "Languages:" in out

    def test_cmd_init_banner_points_to_cheat_sheet(self, python_repo, capsys):
        """TP-189-C CAPGAP-2: the post-init banner points at docs/CHEAT-SHEET.md and
        tells the operator Claude Code lists slash-commands (type `/`), rather than
        naming only 3 of ~15 commands with no discoverability pointer."""
        from espalier.cli import cmd_init
        cmd_init(_ns(repo=str(python_repo)))
        out = capsys.readouterr().out
        assert "docs/CHEAT-SHEET.md" in out
        assert "type `/`" in out


# ── cmd_fingerprint ─────────────────────────────────────────────────────────


class TestCmdFingerprint:
    def test_cmd_fingerprint_writes_report(self, python_repo):
        """cmd_fingerprint writes a valid JSON fingerprint to reports/."""
        from espalier.cli import cmd_fingerprint

        ret = cmd_fingerprint(_ns(repo=str(python_repo)))
        assert ret == 0
        fp_path = python_repo / "reports" / "repo_fingerprint.json"
        assert fp_path.exists()
        data = json.loads(fp_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "languages" in data


class TestCmdFingerprintDownstreamFailures:
    """R10 W3 (R11 coverage): cmd_fingerprint refreshes downstream
    artifacts (``harness_config.json``, ``cc/SURFACE_HANDOFF.md``).
    Failures during the refresh are now wrapped in try/except and a
    WARN is printed to stderr. Pre-fix, a downstream failure surfaced
    as a raw traceback with no hint that the fingerprint had already
    been written and only the derivatives failed.
    """

    def test_warn_emitted_when_build_harness_config_fails(
        self, python_repo, monkeypatch, capsys,
    ):
        from espalier.cli import cmd_fingerprint
        from espalier import cli as cli_module

        # Pre-create harness_config.json so the refresh branch fires.
        reports = python_repo / "reports"
        reports.mkdir(exist_ok=True)
        (reports / "harness_config.json").write_text("{}", encoding="utf-8")

        def boom(*args, **kwargs):
            raise RuntimeError("simulated harness build failure")

        monkeypatch.setattr(cli_module, "build_harness_config", boom)
        ret = cmd_fingerprint(_ns(repo=str(python_repo)))
        # Fingerprint succeeds even if derivative refresh fails.
        assert ret == 0
        captured = capsys.readouterr()
        # WARN must name the failing artifact and the exception class.
        assert "WARN" in captured.err
        assert "harness_config.json" in captured.err
        assert "RuntimeError" in captured.err

    def test_no_warn_on_clean_run(self, python_repo, capsys):
        """Sanity: when everything succeeds, no stderr WARN."""
        from espalier.cli import cmd_fingerprint
        ret = cmd_fingerprint(_ns(repo=str(python_repo)))
        assert ret == 0
        captured = capsys.readouterr()
        assert "downstream artifact(s) failed" not in captured.err


# ── cmd_audit ───────────────────────────────────────────────────────────────


class TestCmdAudit:
    def test_cmd_audit_passes_on_harness_repo(self, harness_repo):
        """cmd_audit exit 0 on a properly constructed harness."""
        from espalier.cli import cmd_audit

        ret = cmd_audit(_ns(repo=str(harness_repo)))
        assert ret == 0

    def test_cmd_audit_blesses_uninitialized(self, tmp_path, capsys):
        """cmd_audit exits 0 with first-run guidance on a bare/uninitialized
        tree — parity with cmd_doctor, which also exits 0 there. The two
        commands must agree on a fresh tree; the pre-fix assertion of exit 1
        encoded the inconsistency this change removes."""
        from espalier.cli import cmd_audit

        ret = cmd_audit(_ns(repo=str(tmp_path)))
        assert ret == 0
        out = capsys.readouterr().out
        assert "not initialized" in out.lower()

    def test_cmd_audit_fails_on_broken_initialized(self, harness_repo):
        """cmd_audit still exits 1 when an *initialized* repo is missing a
        required surface file. The repo-mode short-circuit only spares the
        no-surface modes (source-checkout / uninitialized); a partial or broken
        deployed surface must still red-fail. Preserves the failure coverage the
        former empty-repo test stood in for."""
        from espalier.cli import cmd_audit

        # Remove one required surface file. The .claude/settings.json runtime
        # marker stays, so detect_repo_mode still classifies this as an
        # initialized repo (not source_checkout/uninitialized) and the surface
        # gate runs and fails.
        (harness_repo / "cc" / "COMMANDS.md").unlink()
        ret = cmd_audit(_ns(repo=str(harness_repo)))
        assert ret == 1


# ── cmd_doctor ──────────────────────────────────────────────────────────────


class TestCmdDoctor:
    def test_cmd_doctor_passes_on_harness_repo(self, harness_repo):
        """cmd_doctor exits 0 (pass or warn) on a complete harness."""
        from espalier.cli import cmd_doctor

        ret = cmd_doctor(_ns(repo=str(harness_repo), skip_self_host=True))
        assert ret == 0

    def test_cmd_doctor_no_crash_on_empty_repo(self, tmp_path):
        """cmd_doctor does not crash on an empty repo (warn, not exception)."""
        from espalier.cli import cmd_doctor

        ret = cmd_doctor(_ns(repo=str(tmp_path), skip_self_host=True))
        assert ret in (0, 1)


# ── cmd_diff ────────────────────────────────────────────────────────────────


class TestCmdDiff:
    def test_cmd_diff_no_crash_on_harness_repo(self, harness_repo):
        """cmd_diff runs without crashing and returns a structured report."""
        from espalier.cli import cmd_diff

        ret = cmd_diff(_ns(repo=str(harness_repo)))
        assert ret in (0, 1)  # clean or changed; no crash


# ── cmd_recover ─────────────────────────────────────────────────────────────


class TestCmdRecover:
    def test_cmd_recover_clean_on_harness_repo(self, harness_repo):
        """cmd_recover exits 0 when all required surface files are present."""
        from espalier.cli import cmd_recover

        ret = cmd_recover(_ns(repo=str(harness_repo)))
        assert ret == 0


# ── cmd_reflect ─────────────────────────────────────────────────────────────


class TestCmdReflect:
    def test_cmd_reflect_runs_on_harness_repo(self, harness_repo):
        """cmd_reflect runs without crashing on an initialized harness."""
        from espalier.cli import cmd_reflect

        ret = cmd_reflect(_ns(repo=str(harness_repo)))
        assert ret in (0, 1)

    def test_cmd_reflect_deep_runs_on_harness_repo(self, harness_repo):
        """cmd_reflect_deep runs without crashing."""
        from espalier.cli import cmd_reflect_deep

        ret = cmd_reflect_deep(_ns(repo=str(harness_repo), json=False, pass_number=1))
        assert ret in (0, 1)


# ── cmd_scan ────────────────────────────────────────────────────────────────


class TestCmdScan:
    def test_cmd_scan_runs_on_harness_repo(self, harness_repo):
        """cmd_scan runs all scanners and writes report files."""
        from espalier.cli import cmd_scan

        ret = cmd_scan(_ns(repo=str(harness_repo)))
        assert ret == 0
        assert (harness_repo / "reports" / "scan_exceptions.json").exists()
        assert (harness_repo / "reports" / "scan_prints.json").exists()

    def test_summary_names_the_report_behind_each_nonzero_count(self, tmp_path, capsys):
        """DEF-773: the counts line was the whole output, while the file and
        line of every finding sat in reports/ with nothing saying so (driven
        2026-09-11: zero mentions of reports/ in the output, twelve files
        under it). The report behind a non-zero count is the next step."""
        from espalier.cli import cmd_scan
        (tmp_path / "app.py").write_text('print("hi")\n', encoding="utf-8")
        assert cmd_scan(_ns(repo=str(tmp_path))) == 0
        out = capsys.readouterr().out
        assert "Prints: 1" in out, out
        assert "Details (file and line per finding), under " in out, out
        assert "scan_prints.json" in out, out
        assert "scan_exceptions.json" not in out, out   # a zero count names no file
        # The scanned repo is not the cwd, so the path is spelled under it.
        assert str(tmp_path / "reports") in out, out

    def test_summary_names_the_directory_when_nothing_was_found(self, tmp_path, capsys):
        from espalier.cli import cmd_scan
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        assert cmd_scan(_ns(repo=str(tmp_path))) == 0
        out = capsys.readouterr().out
        assert "Details (" not in out, out
        m = re.search(r"No findings; the (\d+) scan reports this run wrote are under ", out)
        assert m, out
        # The count is the finding reports the scan wrote: every JSON under
        # reports/ except the summary and overrides envelopes it writes after.
        # (A third envelope must NOT be added to this exclusion tuple to keep
        # the test green -- that would narrow the guard; route it through
        # `_write_report` or leave it out of reports/ instead.)
        finding_reports = [
            p.name for p in (tmp_path / "reports").glob("*.json")
            if p.name not in ("scan_summary.json", "scan_overrides.json")
        ]
        assert int(m.group(1)) == len(finding_reports), (m.group(1), finding_reports)
        # An adopter tree: the four Espalier-only scanners did not run, and
        # the sentence says so instead of calling their empty reports detail.
        assert "Espalier-only scanners that do not run here" in out, out


# ── cmd_strengthen ──────────────────────────────────────────────────────────


class TestCmdStrengthen:
    def test_writes_report_and_returns_zero(self, tmp_path):
        """cmd_strengthen writes strengthen_report.{json,md} and returns 0."""
        from espalier.cli import cmd_strengthen

        (tmp_path / "lib.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        ret = cmd_strengthen(_ns(repo=str(tmp_path), top_n=20, skip_fan_in=False))
        assert ret == 0
        report_json = tmp_path / "reports" / "strengthen_report.json"
        assert report_json.exists()
        data = json.loads(report_json.read_text(encoding="utf-8"))
        assert data["mode"] in ("a", "b", "non_python")
        assert (tmp_path / "reports" / "strengthen_report.md").exists()

    def test_nondir_path_returns_two_not_one(self):
        """A missing path is a precondition failure -> exit 2, never 1."""
        from espalier.cli import cmd_strengthen

        ret = cmd_strengthen(_ns(repo="/no/such/strengthen/path", top_n=20, skip_fan_in=False))
        assert ret == 2

    def test_getattr_seam_tolerates_missing_flags(self, tmp_path):
        """top_n/skip_fan_in read via getattr so a Namespace lacking them (and the
        suggest pack's later --suggest) does not AttributeError."""
        from espalier.cli import cmd_strengthen

        (tmp_path / "lib.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        assert cmd_strengthen(_ns(repo=str(tmp_path))) == 0

    def test_subparser_registered_with_repo_and_flags(self):
        from espalier.cli import build_parser

        p = build_parser()
        ns = p.parse_args(["strengthen", ".", "--top-n", "5", "--skip-fan-in"])
        assert ns.func.__name__ == "cmd_strengthen"
        assert ns.top_n == 5
        assert ns.skip_fan_in is True


# ── cmd_clean_generated ─────────────────────────────────────────────────────


class TestCmdCleanGenerated:
    def test_cmd_clean_generated_dry_run(self, harness_repo):
        """Dry run lists managed files without deleting them."""
        from espalier.cli import cmd_clean_generated

        ret = cmd_clean_generated(_ns(repo=str(harness_repo), execute=False))
        assert ret == 0
        # CLAUDE.md should still exist — nothing was deleted
        assert (harness_repo / "CLAUDE.md").exists()

    def test_cmd_clean_generated_execute(self, harness_repo):
        """--execute removes managed harness files; user files survive."""
        from espalier.cli import cmd_clean_generated

        ret = cmd_clean_generated(_ns(repo=str(harness_repo), execute=True))
        assert ret == 0
        # Non-harness user file must survive
        assert (harness_repo / "app.py").exists()


# ── cmd_release_pack ────────────────────────────────────────────────────────


class TestCmdReleasePack:
    def test_cmd_release_pack_creates_zip(self, harness_repo, as_self_host_tree):
        """cmd_release_pack creates a non-empty zip file from the git INDEX.

        `harness_repo` fakes `.git` as an empty directory, which is a root git
        cannot answer for -- the shape the verb now refuses -- so the fixture
        is made a real repo with the tree staged (`-f`: this machine's global
        ignore hides `.claude/settings.local.json`)."""
        import subprocess
        from espalier.cli import cmd_release_pack

        subprocess.run(["git", "init", "-q", str(harness_repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(harness_repo), "add", "-A", "-f"], check=True, capture_output=True)
        ret = cmd_release_pack(_ns(repo=str(harness_repo), output="dist/release.zip"))
        assert ret == 0
        zip_path = harness_repo / "dist" / "release.zip"
        assert zip_path.exists()
        assert zip_path.stat().st_size > 0

    def test_cmd_release_pack_refuses_a_tree_enumerated_build_on_a_git_root(
        self, harness_repo, as_self_host_tree, capsys
    ):
        """§C13: a root that owns a `.git` git cannot answer for (here the
        fixture's empty fake) is git failing, and the archive it produced holds
        every untracked public file; the verb exits 2 and says so, rather than
        leaving a WARN on stderr as the only trace."""
        from espalier.cli import cmd_release_pack

        ret = cmd_release_pack(_ns(repo=str(harness_repo), output="dist/release.zip"))
        assert ret == 2
        err = capsys.readouterr().err
        assert "WORKING TREE" in err and "fix git" in err, err


# ── cmd_pre_release ─────────────────────────────────────────────────────────


class TestCmdPreRelease:
    def test_cmd_pre_release_skip_flags(self, harness_repo, as_self_host_tree):
        """cmd_pre_release with skip_tests and skip_pack finishes without crashing."""
        from espalier.cli import cmd_pre_release

        # Add required public files
        for fname in ("LICENSE", "CONTRIBUTING.md"):
            p = harness_repo / fname
            if not p.exists():
                p.write_text(f"# {fname}\n", encoding="utf-8")

        ret = cmd_pre_release(
            _ns(repo=str(harness_repo), output="dist/release.zip",
                skip_tests=True, skip_pack=True)
        )
        assert ret in (0, 1)  # self-host check may fail in test env


# ── cmd_blueprint ───────────────────────────────────────────────────────────


class TestCmdBlueprint:
    def test_cmd_blueprint_start_and_chain(self, harness_repo):
        """blueprint start then chain both exit 0 and populate the blueprints dir."""
        from espalier.cli import cmd_blueprint

        ret_start = cmd_blueprint(_ns(repo=str(harness_repo), action="start",
                                      kind=None, description=None, evidence=None,
                                      fragments=None, json=False))
        assert ret_start == 0
        assert (harness_repo / "cc" / "blueprints").exists()

        ret_chain = cmd_blueprint(_ns(repo=str(harness_repo), action="chain",
                                      kind=None, description=None, evidence=None,
                                      fragments=None, json=True))
        assert ret_chain == 0


# ── cmd_worktree_plan ────────────────────────────────────────────────────────


class TestCmdWorktreePlan:
    def test_cmd_worktree_plan(self, harness_repo):
        """cmd_worktree_plan exits 0 and prints a plan."""
        from espalier.cli import cmd_worktree_plan

        ret = cmd_worktree_plan(_ns(repo=str(harness_repo), json=False))
        assert ret == 0


# ── cmd_surface_handoff ────────────────────────────────────────────────────


class TestCmdSurfaceHandoff:
    def test_cmd_surface_handoff_json(self, harness_repo):
        """cmd_surface_handoff --json exits 0 and prints valid JSON."""
        from espalier.cli import cmd_surface_handoff

        ret = cmd_surface_handoff(_ns(repo=str(harness_repo), json=True, out=None))
        assert ret == 0


# ── main() ───────────────────────────────────────────────────────────────────


class TestMain:
    def test_main_nonexistent_path_returns_clean_precondition_code(self, capsys):
        """A nonexistent repo path surfaces as the clean precondition exit (2)
        with a readable message — NOT a raw errno traceback (the shared is_dir
        precheck; see docs/CLI_EXIT_CODES.md). Previously fingerprint leaked
        `[Errno 2] ...` + the resolved path at exit 1."""
        import sys
        from unittest.mock import patch
        from espalier.cli import main

        with patch.object(sys, "argv", ["espalier", "fingerprint", "/nonexistent-path-xyz"]):
            ret = main()
        err = capsys.readouterr().err
        assert ret == 2
        assert "does not exist or is not a directory" in err
        assert "Errno" not in err and "Traceback" not in err

    def test_version_flag(self, capsys):
        """--version prints the package version."""
        import sys
        from unittest.mock import patch
        from espalier.cli import build_parser

        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["espalier", "--version"]):
                parser.parse_args(["--version"])
        assert exc_info.value.code == 0


# ── _build_settings_json (Pack 3-B unit tests) ─────────────────────────────


class TestBuildSettingsJsonStructure:
    """Unit tests for the single authoritative settings generator.

    TP-35 reshaped the generator output. TP-48 C2 then widened the
    PreToolUse matcher back to ``"*"`` so Task / TodoWrite / SlashCommand /
    BashOutput dispatches reach write_guard's kill-switch:
      - Exec form: ``command="python"`` + ``args=[script_path]``
      - PreToolUse matcher is ``"*"``; hooks filter internally on
        ``MUTATION_TOOLS`` for the read-only fast-path.
      - PostToolUse split: post_write_check uses the narrow matcher
        (TP-35 perf), reflect_trigger keeps ``"*"`` for its every-Nth-
        call cadence.

    These tests assert the post-TP-35 contract. The pre-TP-35 wildcard
    expectations were updated in-place; see
    ``tests/test_hook_matcher_precision.py`` and
    ``tests/test_hook_exec_form.py`` for the dedicated TP-35 contract
    tests.
    """

    def _settings(self) -> dict:
        from espalier.cli import _build_settings_json
        return _build_settings_json()

    @staticmethod
    def _script_refs(hook: dict) -> list[str]:
        refs = []
        for arg in hook.get("args") or []:
            if isinstance(arg, str):
                refs.append(arg)
        cmd = hook.get("command", "")
        if isinstance(cmd, str):
            refs.append(cmd)
        return refs

    def test_all_canonical_hooks_wired(self):
        from espalier import surface_contract

        settings = self._settings()
        wired: set[str] = set()
        for event_cfg in settings["hooks"].values():
            for entry in event_cfg:
                for hook in entry.get("hooks", []):
                    for ref in self._script_refs(hook):
                        for name in surface_contract.get_canonical_hook_scripts():
                            if ref.endswith(f"/{name}"):
                                wired.add(name)
        assert wired == set(surface_contract.get_canonical_hook_scripts())

    def test_user_prompt_submit_wires_task_router(self):
        settings = self._settings()
        ups = settings["hooks"].get("UserPromptSubmit")
        assert ups, "UserPromptSubmit event missing"
        refs = [r for entry in ups for h in entry.get("hooks", []) for r in self._script_refs(h)]
        assert any("task_router.py" in r for r in refs), refs

    def test_every_hook_has_claude_project_dir_anchor(self):
        """TP-35 exec form: the curly-form placeholder lives in args[0]."""
        settings = self._settings()
        for event_cfg in settings["hooks"].values():
            for entry in event_cfg:
                for hook in entry.get("hooks", []):
                    args = hook.get("args", [])
                    assert args and "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/" in args[0], (
                        f"hook missing curly CLAUDE_PROJECT_DIR anchor in args: {hook}"
                    )

    def test_canonical_events_present(self):
        settings = self._settings()
        # TP-40: SubagentStop added — 7 -> 8 hook events.
        # TP-163: SubagentStart + PostToolUseFailure — 8 -> 10 hook events.
        expected = {"SessionStart", "UserPromptSubmit", "PreToolUse",
                    "PostToolUse", "PostToolUseFailure", "ConfigChange", "Stop",
                    "SubagentStart", "SubagentStop", "PostCompact"}
        assert set(settings["hooks"].keys()) == expected

    def test_pre_tool_use_matcher_is_star(self):
        """TP-48 C2 + TP-64: write_guard's PreToolUse entry keeps matcher
        '*' so Task / TodoWrite / SlashCommand / BashOutput dispatches
        reach write_guard's kill-switch. write_guard's internal
        MUTATION_TOOLS filter is the perf escape hatch — read-only tool
        calls return 0 quickly without doing path work. plan_guard's
        entry has its own narrow matcher (Write|Edit|NotebookEdit) and
        is exempt from this assertion by design."""
        settings = self._settings()
        found_write_guard_star = False
        for entry in settings["hooks"]["PreToolUse"]:
            hooks = entry.get("hooks", [])
            refs = " ".join(r for h in hooks for r in self._script_refs(h))
            matcher = entry.get("matcher", "")
            if "plan_guard.py" in refs:
                # TP-64: plan_guard is intentionally narrow.
                continue
            assert matcher == "*", (
                f"PreToolUse matcher must be '*' post-TP-48 so Task / "
                f"TodoWrite reach write_guard; got {matcher!r}"
            )
            if "write_guard.py" in refs:
                found_write_guard_star = True
        assert found_write_guard_star, (
            "write_guard.py is not wired to a '*' PreToolUse entry — "
            "kill-switch reach on Task / TodoWrite / SlashCommand / "
            "BashOutput would silently fail."
        )

    def test_pre_tool_use_matcher_covers_mcp(self):
        """R10 B1 → TP-48 → TP-64: write_guard's '*' matcher covers every
        tool name including ``mcp__filesystem__write_file``. The internal
        write_guard MCP branch (write_guard.py:722) still runs; defense
        in depth survives the matcher widening. plan_guard's
        Write|Edit|NotebookEdit matcher intentionally omits MCP — Bash
        and MCP writes are not plan-gated post-TP-64."""
        settings = self._settings()
        for entry in settings["hooks"]["PreToolUse"]:
            hooks = entry.get("hooks", [])
            refs = " ".join(r for h in hooks for r in self._script_refs(h))
            if "plan_guard.py" in refs:
                # TP-64: plan_guard intentionally omits MCP from its matcher.
                continue
            matcher = entry.get("matcher", "")
            assert matcher == "*" or "mcp__" in matcher, (
                f"PreToolUse matcher fails to cover MCP tools: {matcher!r}"
            )

    def test_post_tool_use_matcher_includes_mcp_for_post_write_check(self):
        """R10 B1: PostToolUse narrow matcher (post_write_check.py) must
        also cover ``mcp__.*`` so post-write validation runs for MCP writes.
        ``reflect_trigger.py`` keeps its ``*`` matcher by design.
        """
        settings = self._settings()
        for entry in settings["hooks"]["PostToolUse"]:
            matcher = entry.get("matcher", "")
            if matcher == "*":
                continue  # reflect_trigger keeps wildcard by design
            tokens = matcher.split("|")
            assert any("mcp__" in t for t in tokens), (
                f"PostToolUse narrow matcher missing mcp__ alternative. "
                f"matcher={matcher!r}"
            )

    def test_post_tool_use_matcher_split(self):
        """TP-35: PostToolUse splits — post_write_check narrow, reflect_trigger '*'."""
        settings = self._settings()
        expected_mutation_tools = {"Write", "Edit", "NotebookEdit", "Bash", "PowerShell"}
        found_reflect_star = False
        found_post_write_narrow = False
        for entry in settings["hooks"]["PostToolUse"]:
            matcher = entry.get("matcher", "")
            for hook in entry.get("hooks", []):
                refs = " ".join(self._script_refs(hook))
                if "reflect_trigger.py" in refs:
                    assert matcher == "*", (
                        f"reflect_trigger must use matcher='*'; got {matcher!r}"
                    )
                    found_reflect_star = True
                elif "post_write_check.py" in refs:
                    tokens = set(matcher.split("|"))
                    missing = expected_mutation_tools - tokens
                    assert not missing, (
                        f"post_write_check narrow matcher missing {missing}: {matcher!r}"
                    )
                    found_post_write_narrow = True
        assert found_reflect_star, "reflect_trigger.py not found in PostToolUse"
        assert found_post_write_narrow, "post_write_check.py not found in PostToolUse"

    def test_session_start_no_source_filter(self):
        """SessionStart must fire on all sources — no startup-only matcher."""
        settings = self._settings()
        ss = settings["hooks"]["SessionStart"]
        # All entries must either have no "matcher" key or have an empty/wildcard value.
        for entry in ss:
            if "matcher" in entry:
                assert entry["matcher"] in ("", "*"), (
                    f"SessionStart matcher should be empty or '*' to fire on all "
                    f"sources (resume, compact, clear, startup), got {entry['matcher']!r}"
                )

    def test_stop_gate_timeout_matches_contract(self):
        """Stop timeout must equal hook_contract.STOP_OUTER_TIMEOUT (no stray literal)."""
        from espalier import hook_contract
        settings = self._settings()
        stop_entries = settings["hooks"]["Stop"]
        stop_hooks = [h for entry in stop_entries for h in entry.get("hooks", [])]
        assert stop_hooks, "Stop has no hooks"
        assert stop_hooks[0]["timeout"] == hook_contract.STOP_OUTER_TIMEOUT


# ── TP-73: _detect_python_command + cmd_init pre-flight ─────────────────────


class TestDetectPythonCommand:
    """TP-73 — version-probe must reject Python 2 candidates so a stale
    macOS ``python`` symlink doesn't poison the generated
    ``.claude/settings.json`` and break every hook fire with f-string
    syntax errors."""

    def test_detect_python_rejects_python_2(self, monkeypatch):
        """Python 2 ``python`` symlink falls through to ``python3``."""
        import subprocess
        from espalier import cli

        def fake_which(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("python", "python3") else None

        def fake_run(argv, **kwargs):
            stdout = (
                "Python 2.7.18\n" if argv[0].endswith("/python")
                else "Python 3.10.4\n"
            )
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(cli.shutil, "which", fake_which)
        monkeypatch.setattr(subprocess, "run", fake_run)
        assert cli._detect_python_command() == "python3"

    def test_detect_python_accepts_python_3(self, monkeypatch):
        """``python`` resolving to Python 3 is accepted on the first probe."""
        import subprocess
        from espalier import cli

        monkeypatch.setattr(
            cli.shutil, "which",
            lambda cmd: "/usr/bin/python" if cmd == "python" else None,
        )
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv, 0, stdout="Python 3.11.7\n", stderr="",
            ),
        )
        assert cli._detect_python_command() == "python"

    def test_warn_once_flag_ships_unset(self):
        """The three tests below each reset this flag before doing anything, so
        none of them reads its SHIPPED value -- and that value is the one with
        production consequence.

        Driven: setting `_INTERPRETER_WARNING_EMITTED = True` at module level
        retires the entire fail-open fix (the resolver returns an unvalidated
        name in silence again, on every host, permanently) while the full suite
        stays green. A guard authored and narrowed in the same change needs a
        negative twin; this is it.
        """
        from espalier import cli
        assert cli._INTERPRETER_WARNING_EMITTED is False, (
            "the warn-once flag ships already-set, so the resolver's stderr "
            "warning can never fire -- the pack's headline fix is dead on "
            "arrival."
        )

    def test_unvalidated_fallback_names_the_probe_on_stderr(self, monkeypatch, capsys):
        """2-A: the resolver must not return a name it failed to validate in
        SILENCE. The assertion is on the NAMING, not merely that some line was
        emitted -- a warning that says "something went wrong" leaves the operator
        exactly where the silence did.

        This is the stub-host shape: a name that RESOLVES but is not Python, so
        there is no command-not-found to surface downstream.
        """
        import subprocess
        from espalier import cli

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False)
        monkeypatch.setattr(
            cli.shutil, "which",
            lambda cmd: "/opt/stub/python3" if cmd == "python3" else None,
        )
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv, 9009, stdout="",
                stderr="Python was not found; run without arguments to install\n",
            ),
        )
        assert cli._detect_python_command() == "python"
        err = capsys.readouterr().err
        assert "/opt/stub/python3" in err, (
            f"warning must name the RESOLVED PATH that failed identity; got: {err!r}"
        )
        assert "Python was not found" in err, (
            f"warning must quote what the probe ACTUALLY said; got: {err!r}"
        )

    def test_virtualenv_only_fallback_stays_silent(self, monkeypatch, capsys):
        """2-A scoping: the venv-only fall-through is a DELIBERATE, documented
        fail-safe -- a real Python 3 was found and rejected on purpose. Warning
        there would fire for every developer running init inside an activated
        venv, and an advisory that cries wolf gets ignored (or deleted)."""
        import subprocess
        from espalier import cli

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False)
        monkeypatch.setattr(
            cli.shutil, "which",
            lambda cmd: f"/venv/bin/{cmd}" if cmd in ("python", "python3") else None,
        )
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv, 0, stdout="Python 3.12.1\n", stderr="",
            ),
        )
        monkeypatch.setattr(cli, "_resolves_only_inside_a_virtualenv",
                            lambda name, path: True)
        assert cli._detect_python_command() == "python"
        assert "WARNING" not in capsys.readouterr().err

    def test_warning_is_emitted_once_per_process(self, monkeypatch, capsys):
        """The resolver has 30 call sites and no memoization -- `doctor` alone
        calls it ten times. Ten identical lines on the broken host this exists
        to help is noise, not a signal."""
        import subprocess
        from espalier import cli

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False)
        monkeypatch.setattr(cli.shutil, "which",
                            lambda cmd: "/opt/stub/python3" if cmd == "python3" else None)
        monkeypatch.setattr(
            subprocess, "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv, 9009, stdout="", stderr="not python\n"),
        )
        for _ in range(10):
            cli._detect_python_command()
        assert capsys.readouterr().err.count("WARNING: no Python 3") == 1

    def test_detect_python_falls_back_when_probe_raises(self, monkeypatch):
        """``subprocess.SubprocessError`` skips the candidate, doesn't crash."""
        import subprocess
        from espalier import cli

        monkeypatch.setattr(
            cli.shutil, "which",
            lambda cmd: f"/usr/bin/{cmd}" if cmd in ("python", "python3") else None,
        )

        def fake_run(argv, **kw):
            if argv[0].endswith("/python"):
                raise subprocess.TimeoutExpired(argv, 2)
            return subprocess.CompletedProcess(
                argv, 0, stdout="Python 3.12.0\n", stderr="",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert cli._detect_python_command() == "python3"

    def test_hint_tracks_detected_interpreter(self, tmp_path, monkeypatch):
        """DIW-02: a runtime remedy hint emits the host's interpreter, not a
        hard-coded ``python``. On a python3-only host every hint must read
        ``python3 -m espalier ...``, never bare ``python -m espalier``. Drives
        REAL converted hint sites (doctor's remedy fn + the uninitialized
        report), so it reds against a pre-fix hard-coded literal and greens
        after the interpreter threading -- not a self-contained tautology
        that would pass no matter what the hint sites emit. The seam is the
        REMEDY interpreter shared by cli and doctor (DEF-758): a patch on the
        resolver alone would be probed for the floor and, failing it on the
        very hosts the remedy exists for, replaced by the running interpreter."""
        from espalier import cli, doctor
        monkeypatch.setattr(cli, "_remedy_interpreter", lambda: ("python3", True))

        remedy = doctor._merge_settings_remedy()
        assert "python3 -m espalier merge-settings" in remedy, remedy
        assert "`python -m espalier" not in remedy, remedy

        next_steps = doctor._uninitialized_report(
            tmp_path, "uninitialized")["next_steps"]
        assert any("python3 -m espalier init" in s for s in next_steps), next_steps
        assert not any(
            s.strip().startswith("python -m espalier") for s in next_steps
        ), next_steps


class TestCmdInitGitPreflight:
    """TP-73 — ``cmd_init`` rejects a non-git directory before deploying
    anything, since every hook fires ``git diff`` / ``git log`` and would
    error confusingly on a non-git target."""

    def test_cmd_init_rejects_non_git_dir(self, tmp_path, capsys):
        """Exit 1 + 'not a git repository' on stderr; no .claude/ created."""
        from espalier.cli import cmd_init

        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        # tmp_path deliberately has no .git/
        args = _ns(
            repo=str(tmp_path),
        )
        rc = cmd_init(args)
        captured = capsys.readouterr()
        assert rc == 1
        assert "not a git repository" in captured.err.lower()
        assert not (tmp_path / ".claude").exists()


class TestNoLlmFlagIsNoOp:
    """TP-189-C DEAD-2: `audit-accuracy --no-llm` is a verified no-op — mechanical-
    only is already the default and the LLM-dispatch path is dormant
    (audit_accuracy.is_no_llm resolves True whether dispatch is None or
    _no_llm_dispatch). The help must say so honestly rather than imply the flag
    changes behavior. (The no-op itself is structurally guaranteed by the unchanged
    audit_accuracy.is_no_llm logic; this pins the honest help wording.)"""

    def _audit_help(self) -> str:
        from espalier.cli import build_parser
        parser = build_parser()
        sub = next(
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        return sub.choices["audit-accuracy"].format_help()

    def test_help_states_flag_is_no_op(self):
        assert "no-op compatibility flag" in self._audit_help()

    def test_help_drops_misleading_skip_dispatch_phrasing(self):
        # old help implied the flag DOES something ("skip LLM dispatch path")
        assert "skip LLM dispatch path" not in self._audit_help()


class TestOutFlagAlias:
    """TP-189-C CLI-3: --out is the canonical artifact-path flag; --output is a
    hidden back-compat alias. Both resolve to dest="output" and the default is
    preserved, so existing `--output X` scripts keep working."""

    @pytest.mark.parametrize("cmd", ["release-pack", "pre-release"])
    def test_out_and_output_resolve_same_dest(self, cmd):
        from espalier.cli import build_parser
        p = build_parser()
        # canonical --out (RED pre-fix: unrecognized argument -> SystemExit)
        assert p.parse_args([cmd, ".", "--out", "X.zip"]).output == "X.zip"
        # back-compat --output alias still parses to the same dest
        assert p.parse_args([cmd, ".", "--output", "X.zip"]).output == "X.zip"
        # default preserved (the canonical --out sets it; alias does not clobber)
        assert p.parse_args([cmd, "."]).output == "dist/espalier-harness.zip"


class TestExitCodeConvention:
    """TP-189-C CLI-2: the 0/1/2 exit convention is documented (docs/CLI_EXIT_CODES.md)
    and the `audit` subparser no longer over-promises a flat "1 otherwise". The
    consumed codes (integrity verify -> 2 kill-switch, scope-check -> 2 gap) are
    preserved and pinned by tests/test_integrity.py + tests/test_cli.py."""

    def _audit_help(self) -> str:
        from espalier.cli import build_parser
        p = build_parser()
        sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
        return sub.choices["audit"].format_help()

    def test_exit_code_doc_exists_and_documents_tiers(self):
        doc = Path(__file__).resolve().parent.parent / "docs" / "CLI_EXIT_CODES.md"
        text = doc.read_text(encoding="utf-8")
        for code in ("`0`", "`1`", "`2`"):
            assert code in text

    def test_audit_description_drops_flat_over_promise(self):
        help_text = self._audit_help()
        assert "1 otherwise" not in help_text       # the bare over-promise is gone
        assert "CLI_EXIT_CODES.md" in help_text      # points at the convention doc

    def test_usage_error_exits_two(self):
        from espalier.cli import build_parser
        # an unrecognized flag is a stable usage error regardless of whether the
        # repo positional is required or optional (CLI-1 widens it later).
        p = build_parser()
        with pytest.raises(SystemExit) as exc:
            p.parse_args(["audit", ".", "--no-such-flag"])
        assert exc.value.code == 2


class TestRepoConfigArgConsistency:
    """TP-189-C CLI-5/CLI-4: every repo positional renders a consistent REPO
    metavar (not lowercase `repo`), and --config carries help text — both via the
    shared _add_repo_arg / _add_config_arg helpers."""

    def _subparsers(self):
        from espalier.cli import build_parser
        p = build_parser()
        action = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
        return action.choices

    def test_every_repo_positional_renders_REPO_metavar(self):
        offenders = []
        for name, sub in self._subparsers().items():
            for act in sub._actions:
                if act.dest == "repo" and not act.option_strings:  # positional repo only
                    rendered = act.metavar or act.dest
                    if rendered != "REPO":
                        offenders.append((name, rendered))
        assert not offenders, f"repo positionals not rendering REPO metavar: {offenders}"

    def test_config_flag_has_help(self):
        for name, sub in self._subparsers().items():
            for act in sub._actions:
                if "--config" in act.option_strings:
                    assert act.help, f"--config on {name!r} has no help text"

    def test_sampled_help_has_repo_and_config_strings(self):
        help_text = self._subparsers()["audit"].format_help()
        assert "repo path" in help_text
        assert "espalier.toml config" in help_text


class TestUpgrade:
    """TP-189-D CAPGAP-1: `espalier upgrade` re-deploys a stale harness in place.
    Dry-run is the DEFAULT (writes nothing); --execute applies. A current harness
    is a no-op. An uninitialized repo errors with guidance."""

    def _age_stamp(self, repo):
        # rewrite cc/PACK_MANIFEST.txt's version stamp to an older value so
        # cmd_upgrade sees the deployment as stale.
        manifest = repo / "cc" / "PACK_MANIFEST.txt"
        lines = manifest.read_text(encoding="utf-8").splitlines()
        out = ["# espalier-version: 0.0.1-old" if ln.startswith("# espalier-version:") else ln
               for ln in lines]
        manifest.write_text("\n".join(out) + "\n", encoding="utf-8")

    def test_dry_run_writes_nothing(self, python_repo, capsys):
        from espalier.cli import cmd_init, cmd_upgrade
        cmd_init(_ns(repo=str(python_repo)))
        self._age_stamp(python_repo)
        capsys.readouterr()  # drop init output
        watched = [python_repo / ".claude" / "settings.json",
                   python_repo / ".espalier" / "integrity.json"]
        before = {p: p.stat().st_mtime_ns for p in watched if p.exists()}
        assert before, "fixture: settings.json + integrity.json should exist after init"
        rc = cmd_upgrade(_ns(repo=str(python_repo), execute=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "mode: dry-run" in out and "would re-deploy" in out
        for p, mtime in before.items():
            assert p.stat().st_mtime_ns == mtime, f"dry-run wrote {p.name} (must be no-op)"

    def test_execute_redeploys_and_restamps(self, python_repo, capsys):
        from espalier.cli import cmd_init, cmd_upgrade, _read_deployed_version
        from espalier import __version__
        cmd_init(_ns(repo=str(python_repo)))
        self._age_stamp(python_repo)
        assert _read_deployed_version(python_repo) == "0.0.1-old"  # stale precondition
        capsys.readouterr()
        rc = cmd_upgrade(_ns(repo=str(python_repo), execute=True))
        out = capsys.readouterr().out
        assert rc == 0
        assert "re-deployed" in out
        # the re-deploy re-rendered the manifest -> stamp is current again
        assert _read_deployed_version(python_repo) == __version__

    def test_execute_refreshes_stale_untouched_seed_doc(self, python_repo, capsys):
        # 1-C earn-red: cmd_upgrade --execute re-deploys the init-seeded docs
        # through the stamp-driven refresh path, so an operator-UNTOUCHED but
        # stale seed doc gets the current packaged bytes. deploy_harness never
        # re-visits seed docs, so before the 1-C wiring this REDs (the stale
        # copy survives the upgrade).
        from importlib.resources import as_file

        from espalier.assets import assets_root
        from espalier.cli import _seed_redeploy_decision, cmd_init, cmd_upgrade
        from espalier.managed_inventory import seed_stamp_line
        cmd_init(_ns(repo=str(python_repo)))
        # Forge a stamped-but-stale UNTOUCHED copy of one plain seed doc: the
        # on-disk body hashes to its own stamp (untouched) yet differs from the
        # current packaged content (stale).
        rel = "memory/README.md"
        dest = python_repo / rel
        stale = "STALE SEED BODY -- older packaged content\n"
        dest.write_text(seed_stamp_line(stale) + stale, encoding="utf-8")
        with as_file(assets_root().joinpath(*rel.split("/"))) as src:
            current = src.read_text(encoding="utf-8")
        assert current != stale, "precondition: packaged content differs from forged stale body"
        assert _seed_redeploy_decision(dest, current) == "refresh", (
            "precondition: forged copy must read as refreshable"
        )

        self._age_stamp(python_repo)          # force upgrade past 'nothing to do'
        capsys.readouterr()
        rc = cmd_upgrade(_ns(repo=str(python_repo), execute=True))
        out = capsys.readouterr().out
        assert rc == 0
        refreshed = dest.read_text(encoding="utf-8")
        assert "STALE SEED BODY" not in refreshed, (
            "cmd_upgrade did not refresh the stale untouched seed doc"
        )
        assert refreshed.endswith(current), (
            "refreshed body must match the current packaged content"
        )
        assert "seed doc" in out              # the new upgrade report line

    def test_upgrade_reports_legacy_unstamped_seed_count(self, python_repo, capsys):
        # RE1: an adopter whose seed docs predate the seed-version stamp must get
        # a signal, not a silent "re-deployed 0" that reads as "all current".
        from espalier.cli import cmd_init, cmd_upgrade
        cmd_init(_ns(repo=str(python_repo)))
        # Simulate a pre-stamp deployment: strip the stamp line from one seed doc.
        dest = python_repo / "memory" / "README.md"
        stamped = dest.read_text(encoding="utf-8")
        assert stamped.startswith("<!-- espalier:seed-version "), "fixture: init should stamp the seed"
        dest.write_text(stamped.split("\n", 1)[1], encoding="utf-8")  # drop the stamp line
        self._age_stamp(python_repo)
        capsys.readouterr()
        cmd_upgrade(_ns(repo=str(python_repo), execute=True))
        out = capsys.readouterr().out
        assert "carry no seed-version stamp" in out
        # DEF-696: the note gives the same two remedies as `doctor`, in the same
        # order -- the stamp for an edited copy (doctor prints it), delete-then-
        # re-seed only for a copy never edited. A bare "delete a stale one" stood
        # here while doctor had already learned that the re-seed of a grounding
        # doc is the near-empty stub.
        assert "-m espalier doctor ." in out
        assert "prints the exact stamp line" in out
        assert "only for a copy you never edited" in out
        assert "delete a stale one" not in out

    def test_current_version_skips_redeploy(self, python_repo, capsys):
        from espalier.cli import cmd_init, cmd_upgrade
        cmd_init(_ns(repo=str(python_repo)))  # stamp == current __version__, NOT aged
        capsys.readouterr()
        integrity = python_repo / ".espalier" / "integrity.json"
        before = integrity.stat().st_mtime_ns if integrity.exists() else None
        rc = cmd_upgrade(_ns(repo=str(python_repo), execute=True))  # execute, but current
        out = capsys.readouterr().out
        assert rc == 0
        assert "nothing to do" in out
        if before is not None:
            assert integrity.stat().st_mtime_ns == before  # short-circuit, no write

    def test_uninitialized_repo_errors(self, python_repo, capsys):
        # python_repo has .git but no cc/PACK_MANIFEST.txt (init not run)
        from espalier.cli import cmd_upgrade
        rc = cmd_upgrade(_ns(repo=str(python_repo), execute=False))
        out = capsys.readouterr()
        assert rc == 1
        assert "no harness deployment found" in out.err


def _nested_subparser_actions(parser):
    """Every NESTED ``_SubParsersAction`` below the top-level one.

    Derived, never hand-listed: a third nested sub-verb group added later
    must self-enrol rather than sitting invisible behind a 2-tuple. The
    TOP-LEVEL action is excluded deliberately -- its ``metavar="<command>"``
    is an intentional brace-collapse (see the comment above ``add_subparsers``
    in ``espalier/cli.py``), not drift.
    """
    import argparse
    top = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return [
        (name, action)
        for name, sub in top.choices.items()
        for action in sub._actions
        if isinstance(action, argparse._SubParsersAction)
    ]


class TestNestedSubparserDiscovery:
    """The discovery helper itself -- driven synthetically, no cli.py edit."""

    @staticmethod
    def _three_group_parser(third_metavar):
        import argparse
        p = argparse.ArgumentParser(prog="synthetic")
        top = p.add_subparsers(dest="command", metavar="<command>")
        for name, verbs in (("freshness", ["check", "pin"]), ("memory", ["prune"])):
            sub = top.add_parser(name).add_subparsers(dest=f"{name}_action")
            sub.metavar = "{" + ",".join(verbs) + "}"
            for v in verbs:
                sub.add_parser(v)
        third = top.add_parser("third").add_subparsers(dest="third_action")
        third.metavar = third_metavar
        for v in ("alpha", "beta"):
            third.add_parser(v)
        return p

    def test_discovers_every_nested_group_not_a_fixed_pair(self):
        # Against the old hardcoded ("freshness", "memory") tuple this third
        # group was INVISIBLE: the loop never asked about it, so a hand-set
        # metavar on it passed vacuously. Discovery is what closes that.
        nested = _nested_subparser_actions(self._three_group_parser("{alpha,beta}"))
        assert [name for name, _ in nested] == ["freshness", "memory", "third"]

    def test_drifted_metavar_on_a_discovered_group_is_caught(self):
        # The red the old 2-tuple could not earn: a hand-kept metavar on the
        # third group, stale against its registered choices.
        nested = _nested_subparser_actions(self._three_group_parser("{alpha}"))
        drifted = [
            name for name, action in nested
            if action.metavar != "{" + ",".join(action.choices) + "}"
        ]
        assert drifted == ["third"]

    def test_top_level_action_is_excluded(self):
        # cli.py's top-level metavar="<command>" is a deliberate brace-collapse.
        # Including it would red the live assertion on correct-by-design code.
        nested = _nested_subparser_actions(self._three_group_parser("{alpha,beta}"))
        assert all(action.metavar != "<command>" for _, action in nested)


class TestArgparseErrorCuration:
    """TP-365: the argparse error paths are curated so a typo (the invalid-choice
    path) never advertises the help-suppressed dev/self-host commands, and the
    freshness/memory required-argument path shows the choice metavar instead of
    leaking the raw snake_case ``dest``. Display-only — every hidden command
    stays registered and callable (dispatch is unchanged)."""

    # The dev/self-host commands registered WITHOUT ``help=`` (hidden from
    # ``--help`` and, after this fix, from the invalid-choice enumeration too).
    # Pinned to the parser both ways by test_hidden_tuple_is_the_parsers_help_less_set:
    # `blueprint`, `reflect-deep` and `worktree-plan` left this set on 2026-09-12
    # (DEF-772: adopter verbs the README documents, hidden by accident).
    HIDDEN = (
        "_refresh-self-host-pin", "pre-release", "provenance",
        "refresh-externals", "release-pack", "scaffolding-bench",
        "self-host", "surface-handoff", "verify-landing",
    )

    def test_hidden_tuple_is_the_parsers_help_less_set(self):
        """The tuple above is a hand-kept enumeration; this derives the same
        set from the parser so a verb that gains or loses ``help=`` is a
        decision here, not silent drift in either direction."""
        from espalier.cli import build_parser
        sub = next(
            a for a in build_parser()._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        listed = {a.dest for a in sub._choices_actions}
        assert set(self.HIDDEN) == set(sub.choices) - listed

    def _invalid_choice_stderr(self, capsys) -> str:
        from espalier.cli import build_parser
        p = build_parser()
        with pytest.raises(SystemExit) as exc:
            p.parse_args(["definitely-not-a-command"])
        assert exc.value.code == 2
        return capsys.readouterr().err

    def test_invalid_command_error_hides_dev_commands(self, capsys):
        # earn-the-red: at HEAD every hidden name leaks in the enumeration.
        err = self._invalid_choice_stderr(capsys)
        leaked = [h for h in self.HIDDEN if h in err]
        assert not leaked, f"invalid-choice error leaks hidden commands: {leaked}"

    def test_invalid_command_error_still_lists_public_commands(self, capsys):
        err = self._invalid_choice_stderr(capsys)
        assert "invalid choice" in err
        assert "init" in err    # a representative help-carrying command
        assert "audit" in err

    def test_invalid_choice_quoting_matches_native_argparse(self, capsys):
        # The curated message must preserve the running interpreter's OWN choice
        # rendering -- argparse quotes the choice names on some CPython minors
        # (3.10/3.11/3.13) and not others (3.12/3.14). `integrity` uses a plain
        # choices-positional (no subparsers), so its invalid-choice message is
        # untouched by the override -- a native-style control on this interpreter.
        # Hardcoding one style would green here yet diverge from every sibling
        # error on the other half of the supported-Python matrix.
        from espalier.cli import build_parser
        p = build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["integrity", "definitely-not-a-subverb"])
        native_quoted = "'verify'" in capsys.readouterr().err
        with pytest.raises(SystemExit):
            p.parse_args(["definitely-not-a-command"])
        curated_quoted = "'init'" in capsys.readouterr().err
        assert curated_quoted == native_quoted, (
            "curated invalid-choice quoting must match native argparse styling"
        )

    def test_curation_only_rewrites_the_subcommand_choice_error(self):
        # scoping guard: error() must rewrite ONLY the subparsers-selection
        # message, never another choices-argument a future edit might attach to
        # the same parser. A bad --mode choice keeps its own argument name and
        # its real choice list, untouched by the subcommand curation.
        import contextlib
        import io

        from espalier.cli import _CuratedChoiceParser
        p = _CuratedChoiceParser(prog="probe")
        p.add_argument("--mode", choices=["alpha", "beta"])
        s = p.add_subparsers(dest="command", metavar="<command>")
        s.add_parser("shown", help="visible")
        s.add_parser("_hidden")  # no help= -> help-suppressed
        err = io.StringIO()
        with contextlib.redirect_stderr(err), pytest.raises(SystemExit):
            p.parse_args(["--mode", "gamma"])
        msg = err.getvalue()
        assert "--mode" in msg                    # its own argument name preserved
        assert "alpha" in msg and "beta" in msg   # its real choices, not subcommands
        assert "shown" not in msg                 # subcommand list not injected

    def test_hidden_command_still_dispatchable(self):
        # display-only fix: a help-suppressed command must remain PARSEABLE.
        from espalier.cli import build_parser
        ns = build_parser().parse_args(["_refresh-self-host-pin"])
        assert ns.command == "_refresh-self-host-pin"   # resolves, not "invalid choice"

    def test_freshness_required_arg_error_shows_metavar_not_dest(self, capsys):
        # earn-the-red: bare `espalier freshness` leaks the raw `freshness_action`
        # dest at HEAD; after 1-C it shows the {check,pin,unpin} choice metavar.
        from espalier.cli import build_parser
        p = build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["freshness"])
        err = capsys.readouterr().err
        assert "freshness_action" not in err
        assert "check,pin,unpin" in err

    def test_memory_required_arg_error_shows_metavar_not_dest(self, capsys):
        # earn-the-red: bare `espalier memory` leaks the raw `memory_action` dest.
        from espalier.cli import build_parser
        p = build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["memory"])
        err = capsys.readouterr().err
        assert "memory_action" not in err
        assert "prune" in err

    def test_subparser_metavars_derive_from_registered_choices(self):
        # Enumeration-integrity STRUCTURAL pin (not a value pin): the
        # freshness/memory sub-verb brace list is DERIVED from the registered
        # add_parser choices, not a hand-kept literal. Its teeth are in catching
        # a REGRESSION back to a hand-set string (which silently rots when a
        # sibling sub-verb is added) -- it deliberately does NOT assert WHICH
        # sub-verbs exist (adding a real 4th sub-verb passes trivially, by
        # design); the two ..._shows_metavar_not_dest tests above pin the
        # observable check/pin/unpin + prune rendering.
        from espalier.cli import build_parser
        nested = _nested_subparser_actions(build_parser())
        # Non-vacuity floor: a walk that silently returns [] would green this
        # assertion by having nothing to check -- which is the same shape as the
        # hardcoded 2-tuple it replaced, one level down.
        assert nested, "no nested sub-verb groups discovered -- the walk broke"
        for command, action in nested:
            assert action.metavar == "{" + ",".join(action.choices) + "}", (
                f"{command} metavar {action.metavar!r} drifted from registered "
                f"choices {list(action.choices)!r} -- derive it, don't hand-keep it"
            )

    def test_curation_does_not_drop_nested_subverbs(self, capsys):
        # _CuratedChoiceParser is inherited by subparsers (argparse propagates
        # parser_class). freshness/memory sub-verbs all carry help=, so their
        # invalid-choice enumeration must stay complete -- a guard so a future
        # help-suppressed sub-verb (or a scoping regression) can't silently vanish.
        from espalier.cli import build_parser
        p = build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["freshness", "definitely-not-a-subverb"])
        err = capsys.readouterr().err
        assert "invalid choice" in err
        for verb in ("check", "pin", "unpin"):
            assert verb in err, f"freshness invalid-choice dropped {verb!r}: {err!r}"


class TestHelpEpilogInterpreterIsResolvedLazily:
    """DEF-383a: the top-level ``--help`` epilog spells the interpreter the
    operator should type. It used to be a literal ``python`` -- command-not-found
    on stock macOS -- and it is now resolved at render time only, because the
    resolver spawns ``--version`` probes and ``build_parser()`` runs on every
    CLI call. Since ``DEF-758`` the epilog spells ``cli._remedy_py()`` (the
    resolver's answer when it clears the floor, else the interpreter running
    the command), so the spy sits on that seam: a spy on the resolver alone
    would be probed for the floor and, failing it, replaced.
    """

    def test_building_the_parser_does_not_resolve_the_interpreter(self, monkeypatch):
        from espalier import cli
        calls: list[str] = []

        def spy() -> str:
            calls.append("resolved")
            return "python-spy"

        monkeypatch.setattr(cli, "_detect_python_command", spy)
        parser = cli.build_parser()
        assert calls == [], "build_parser() must not spawn the interpreter probe"
        assert cli._HELP_INTERPRETER_FIELD in (parser.epilog or "")

    def test_rendered_help_spells_the_resolved_interpreter(self, monkeypatch):
        from espalier import cli
        monkeypatch.setattr(cli, "_remedy_py", lambda: "python-spy")
        text = cli.build_parser().format_help()
        assert "First-time setup: python-spy -m espalier init ." in text
        assert cli._HELP_INTERPRETER_FIELD not in text
        # The rendered help carries no other literal interpreter spelling.
        assert "python -m espalier" not in text and "python3 -m espalier" not in text

    def test_the_live_epilog_names_a_real_command(self):
        """No spy: the interpreter it names resolves on this host."""
        import shutil
        from espalier import cli
        text = cli.build_parser().format_help()
        # argparse wraps the epilog at the terminal width, so read across the
        # wrap rather than assuming the name shares the opener's line.
        import re as _re
        match = _re.search(r"First-time setup:\s+(\S+)", text)
        assert match, text
        interpreter = match.group(1)
        assert shutil.which(interpreter), f"epilog names {interpreter!r}, not on PATH"


# ── DEF-772: --help lists every verb the README documents ──────────────────


class TestHelpListsTheDocumentedVerbs:
    """``--help`` omitted four verbs the README documents, because each was
    registered with ``description=`` and no ``help=`` -- the mechanism the
    developer verbs use on purpose, applied by accident (driven 2026-09-11:
    none of the four listed, each executes). Three are adopter verbs and are
    listed now; ``pre-release`` stands down off self-host and stays hidden,
    so the README stopped naming it as an adopter command.

    The population is derived from each doc's ``bash`` code blocks, never
    typed here (a hand-kept list rots silently). Two arms, two scopes:

    - presence, README only (the row's unit): every verb the README's CLI
      blocks name is listed in ``--help``. The cheat sheet deliberately
      documents the hidden-but-safe developer verbs with a caveat apiece
      (``self-host``, ``verify-landing``, ...); un-hiding those is TP-365's
      decision, not this contract's, so the presence arm stops at the README.
    - absence, every shipped doc with CLI blocks: no verb that STANDS DOWN on
      an adopter tree (the gated set the stand-down test derives from the
      code) is documented outside a block marked self-host only. The
      presence arm alone would green a doc that sends an adopter to a verb
      that exits 0 saying ``skipped``; the failure-mode review found the
      cheat sheet's day-1 block doing exactly that after the README was fixed.
    """

    _ROOT = Path(__file__).resolve().parent.parent
    _README = _ROOT / "README.md"
    _DOCS_WITH_CLI_BLOCKS = (
        "README.md", "docs/CHEAT-SHEET.md", "docs/QUICKSTART.md", "docs/TASK_RECIPES.md",
    )
    _COMMAND = re.compile(r"(?:python3?\s+-m\s+)?espalier\s+([a-z][a-z-]*)\b")

    @classmethod
    def _documented_verbs(cls, text: str) -> set[str]:
        """Verbs named at the start of a line inside a ``bash`` fence, in the
        three spellings the docs use (``espalier x``, ``$ espalier x``,
        ``python -m espalier x``), indented or not. A fence whose section
        prose says "self-host only" before it is skipped: that is how the
        cheat sheet marks its release-artifact block."""
        verbs: set[str] = set()
        in_bash = False
        exempt = False
        section: list[str] = []
        for line in text.splitlines():
            if line.startswith("```"):
                if not in_bash:
                    in_bash = line.strip() == "```bash"
                    exempt = "self-host only" in " ".join(section).lower()
                else:
                    in_bash = False
                continue
            if in_bash:
                if not exempt:
                    m = cls._COMMAND.match(line.strip().lstrip("$").strip())
                    if m:
                        verbs.add(m.group(1))
            else:
                if line.startswith("#"):
                    section = []
                section.append(line)
        return verbs

    @staticmethod
    def _help_verbs() -> tuple[set[str], set[str]]:
        """(listed, hidden): the subparsers ``--help`` shows, and the rest."""
        from espalier.cli import build_parser
        sub = next(
            a for a in build_parser()._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        listed = {a.dest for a in sub._choices_actions}
        return listed, set(sub.choices) - listed

    def test_every_verb_the_readme_documents_is_listed_in_help(self):
        documented = self._documented_verbs(self._README.read_text(encoding="utf-8"))
        # The derivation found the CLI section and reads every spelling:
        # `fuse` appears in the README only as `python -m espalier fuse`.
        assert {"init", "doctor", "scan", "fuse"} <= documented, sorted(documented)
        listed, _hidden = self._help_verbs()
        assert documented <= listed, sorted(documented - listed)

    @pytest.mark.parametrize("rel", _DOCS_WITH_CLI_BLOCKS)
    def test_no_stand_down_verb_is_documented_as_an_adopter_command(self, rel):
        from test_adopter_verb_stand_down import TestHarmfulVerbsAreDeclaredAgainstTheHiddenCanon
        gated = TestHarmfulVerbsAreDeclaredAgainstTheHiddenCanon.GATED
        documented = self._documented_verbs((self._ROOT / rel).read_text(encoding="utf-8"))
        assert not (documented & gated), (rel, sorted(documented & gated))

    def test_the_exempt_block_is_read_as_exempt(self):
        """The cheat sheet's release-artifact block names all three gated
        verbs under a "Self-host only" callout; the exemption must be what
        keeps the arm above green there, not an empty derivation."""
        text = (self._ROOT / "docs" / "CHEAT-SHEET.md").read_text(encoding="utf-8")
        assert "espalier pre-release" in text and "self-host only" in text.lower()
        documented = self._documented_verbs(text)
        assert {"init", "doctor", "scan"} <= documented, sorted(documented)

    def test_the_three_adopter_verbs_are_listed(self):
        listed, _hidden = self._help_verbs()
        assert {"blueprint", "reflect-deep", "worktree-plan"} <= listed, sorted(listed)


class TestInitByNamespaceGetsTheParsersGitignoreDefault:
    """DEF-399b (TP-449 Tier 2, 2026-09-12): `cmd_init` read its
    `write_gitignore` through a `getattr` whose fallback disagreed with the
    parser's declared default, so an embedder calling it with a hand-built
    Namespace got the pre-v0.7.9 print-only behaviour and a WARN telling them
    to rerun without a flag they never passed. Driven: `tests/_adopter_tree.py`
    builds every adopter fixture that way and none of them had the block.
    The expected default is read from the parser, never restated here."""

    @staticmethod
    def _parser_default() -> bool:
        from espalier.cli import build_parser
        return build_parser().parse_args(["init", "."]).write_gitignore

    def test_the_fallback_literal_is_the_parsers_default(self):
        import inspect
        import re
        from espalier.cli import cmd_init
        source = inspect.getsource(cmd_init)
        found = re.findall(r'getattr\(args, "write_gitignore", (\w+)\)', source)
        assert found, "cmd_init no longer reads write_gitignore through getattr; retire this pin"
        assert set(found) == {repr(self._parser_default())}, found

    def test_a_hand_built_namespace_writes_the_block(self, tmp_path, capsys):
        from espalier.cli import GITIGNORE_BLOCK_HEADER, cmd_init
        (tmp_path / ".git").mkdir()
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        assert cmd_init(_ns(repo=str(tmp_path))) == 0
        out = capsys.readouterr().out
        gitignore = tmp_path / ".gitignore"
        if self._parser_default():
            assert gitignore.is_file() and GITIGNORE_BLOCK_HEADER in gitignore.read_text(encoding="utf-8")
            assert "Rerun without --no-write-gitignore" not in out, out
        else:  # pragma: no cover - the parser default moved; the pin above says where
            assert not gitignore.exists()


class TestCmdGetattrDefaultsAgreeWithTheParser:
    """The DEF-399b CLASS, censused rather than one site pinned: every
    `getattr(args, "<dest>", <literal>)` in espalier/cli.py whose dest a
    subparser declares must carry that subparser's default, and every
    subparser declaring the dest must agree. A dest no parser declares
    (`func`, `suppress_epilogue`) is a caller-set attribute and is out of
    scope. Measured 2026-09-12: 34 sites, all agree after the fix."""

    def test_every_getattr_fallback_is_the_declared_default(self):
        import argparse
        import ast
        import inspect
        import espalier.cli as cli
        from espalier.cli import build_parser

        # Per subparser: the command function it dispatches to and the
        # defaults it declares. A site inside `cmd_x` is judged against the
        # subparser(s) whose func is cmd_x; a site in a shared helper against
        # the union of every subparser declaring the dest (`repo` is '.' on
        # the widened verbs and None where it stayed required).
        by_func: dict[str, list[dict[str, str]]] = {}
        union: dict[str, set] = {}
        parser = build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    # The parser's OWN effective default per dest: two actions
                    # on one dest (`--out` with a default and a hidden
                    # `--output` alias without) resolve first-declared-wins in
                    # argparse, and `get_default` is where that rule lives.
                    dests = {
                        a.dest for a in sub._actions
                        if a.dest and a.default is not argparse.SUPPRESS and a.dest != "help"
                    }
                    defaults = {dest: repr(sub.get_default(dest)) for dest in dests}
                    func = sub._defaults.get("func")
                    if func is not None:
                        by_func.setdefault(func.__name__, []).append(defaults)
                    for dest, literal in defaults.items():
                        union.setdefault(dest, set()).add(literal)
        tree = ast.parse(inspect.getsource(cli))
        enclosing: dict[ast.AST, str] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for inner in ast.walk(fn):
                    enclosing.setdefault(inner, fn.name)
        sites: list[tuple[int, str, str, str]] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) == 3
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "args"
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[2], ast.Constant)
            ):
                sites.append((node.lineno, enclosing.get(node, ""), str(node.args[1].value), repr(node.args[2].value)))
        assert sites, "no getattr(args, ...) sites found; the census lost its population"
        disagreements = []
        for line, func, dest, literal in sites:
            owners = [d for d in by_func.get(func, []) if dest in d]
            expected = {d[dest] for d in owners} if owners else union.get(dest, set())
            if expected and literal not in expected:
                disagreements.append(
                    f"cli.py:{line} ({func}) getattr(args, {dest!r}, {literal}) vs declared {sorted(expected)}"
                )
        assert not disagreements, "\n".join(disagreements)


class TestSelfcheckContractsFlag:
    """DEF-735 (TP-449 Tier 2, 2026-09-12): `selfcheck.run_contracts` -- the
    three contracts that read the adopter's DEPLOYED tree -- had no caller
    outside its own tests; `espalier --help` offered no way to run them.
    `selfcheck --contracts` runs them; the bare verb still runs the bundled
    engine tests."""

    def test_the_flag_parses_and_defaults_off(self):
        from espalier.cli import build_parser
        parser = build_parser()
        assert parser.parse_args(["selfcheck", "."]).contracts is False
        assert parser.parse_args(["selfcheck", "--contracts", "."]).contracts is True

    def test_the_flag_dispatches_to_run_contracts(self, tmp_path, monkeypatch):
        import espalier.selfcheck as selfcheck
        from espalier.cli import build_parser, cmd_selfcheck
        import espalier.repo_mode as rm
        seen: list[str] = []
        monkeypatch.setattr(selfcheck, "run_contracts", lambda root: seen.append("contracts") or 7)
        monkeypatch.setattr(selfcheck, "run_selfcheck", lambda root: seen.append("bundled") or 0)
        # An initialized tree, as the detector reads it; the never-initialized
        # precondition exit is pinned separately below.
        monkeypatch.setattr(rm, "detect_repo_mode", lambda root: rm.REPO_MODE_INITIALIZED_CONSUMER)
        args = build_parser().parse_args(["selfcheck", "--contracts", str(tmp_path)])
        assert cmd_selfcheck(args) == 7
        assert seen == ["contracts"]

    def test_an_uninitialized_tree_is_told_to_init_first(self, tmp_path, monkeypatch, capsys):
        """The contracts read the deployed tree; on a tree that was never
        initialized they are not run (a C-1 red on a missing hook with no
        remedy, the DEF-770 shape) -- the precondition exit names the step."""
        import espalier.selfcheck as selfcheck
        from espalier.cli import build_parser, cmd_selfcheck
        monkeypatch.setattr(selfcheck, "run_contracts", lambda root: pytest.fail("ran on an uninitialized tree"))
        (tmp_path / ".git").mkdir()
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        args = build_parser().parse_args(["selfcheck", "--contracts", str(tmp_path)])
        assert cmd_selfcheck(args) == 2
        err = capsys.readouterr().err
        assert "not initialized" in err and "-m espalier init" in err, err

    def test_the_bare_verb_still_runs_the_bundled_tests(self, tmp_path, monkeypatch):
        import espalier.selfcheck as selfcheck
        from espalier.cli import build_parser, cmd_selfcheck
        seen: list[str] = []
        monkeypatch.setattr(selfcheck, "run_contracts", lambda root: seen.append("contracts") or 7)
        monkeypatch.setattr(selfcheck, "run_selfcheck", lambda root: seen.append("bundled") or 0)
        args = build_parser().parse_args(["selfcheck", str(tmp_path)])
        assert cmd_selfcheck(args) == 0
        assert seen == ["bundled"]


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits and a non-root user",
)
class TestCommandsOnAClaudeTheyCannotRead:
    """DEF-763, the matrix driven on real 3.10, 3.13 and 3.14 interpreters
    2026-09-13 against an init tree whose `.claude` is mode 000. On CPython
    3.10-3.13 every command died at its first `Path.exists()` with a bare
    `Error: [Errno 13]` line; on 3.14 pathlib read the directory as absent, so `merge-settings` said
    "no settings.json found, run init", `upgrade` dry-ran green and exited 0,
    `doctor` listed every deployed file as missing, `audit` listed every
    manifest entry as promised-and-missing, and `init` printed its seed lines
    before dying at the settings write. One sentence naming the permission,
    on every interpreter: `init` and `upgrade` ask at their own pre-flight
    (exit 1, like their other precondition failures); every command that
    resolves its repo argument through the shared resolver -- `audit` among
    them -- is refused there (exit 2, like a path that is not a directory);
    `doctor` resolves its own and carries the finding in its report (exit 1,
    a failed check). The library gates inside `run_doctor_check` and
    `run_cc_surface_gate` are pinned by their own test files.
    """

    #: command -> the exit code its own precondition convention gives.
    COMMANDS = {
        "init": 1, "upgrade": 1, "merge-settings": 2,
        "clean-generated": 2, "doctor": 1, "audit": 2,
    }

    @pytest.fixture
    def init_tree(self, python_repo, capsys):
        from espalier.cli import cmd_init

        assert cmd_init(_ns(repo=str(python_repo))) == 0
        capsys.readouterr()
        return python_repo

    @staticmethod
    def _drive(repo: Path, command: str, capsys, monkeypatch) -> tuple[int, str, str]:
        from espalier import cli

        functions = {
            "init": cli.cmd_init, "upgrade": cli.cmd_upgrade,
            "merge-settings": cli.cmd_merge_settings,
            "clean-generated": cli.cmd_clean_generated,
            "doctor": cli.cmd_doctor, "audit": cli.cmd_audit,
        }
        args = cli.build_parser().parse_args([command, str(repo)])
        monkeypatch.chdir(repo)
        with locked(repo / ".claude"):
            rc = functions[command](args)
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    @pytest.mark.parametrize("command", sorted(COMMANDS))
    def test_each_command_refuses_with_the_one_sentence(self, init_tree, command, capsys, monkeypatch):
        rc, out, err = self._drive(init_tree, command, capsys, monkeypatch)
        text = out + err
        assert rc == self.COMMANDS[command], (command, rc, text)
        assert ".claude cannot be read" in text and "Permission denied" in text, (command, text)
        assert "permissions" in text and "then re-run" in text, (command, text)
        if command != "init":
            assert "-m espalier init" not in text, (command, text)
        if self.COMMANDS[command] == 1:
            # The pre-flights and the reports name THIS command in the re-run
            # (audit's footer spells the path out); the resolver's refusal
            # does not know which command it is serving.
            assert f"-m espalier {command}" in text, (command, text)

    def test_init_prints_nothing_before_the_refusal(self, init_tree, capsys, monkeypatch):
        _rc, out, _err = self._drive(init_tree, "init", capsys, monkeypatch)
        assert out.strip() == "", out

    def test_upgrade_does_not_dry_run_green(self, init_tree, capsys, monkeypatch):
        _rc, out, err = self._drive(init_tree, "upgrade", capsys, monkeypatch)
        assert "dry-run complete" not in out + err and "would " not in out + err, out + err

    def test_doctor_and_audit_do_not_list_a_phantom_missing_surface(self, init_tree, capsys, monkeypatch):
        _rc, out, err = self._drive(init_tree, "doctor", capsys, monkeypatch)
        assert "missing required managed surface" not in out + err, out + err
        assert "stale saved-plan" not in out + err, out + err
        _rc, out, err = self._drive(init_tree, "audit", capsys, monkeypatch)
        assert "promises missing files" not in out + err, out + err
        assert "missing generated file" not in out + err, out + err

    def test_fuse_refuses_a_host_whose_claude_it_cannot_read(self, init_tree, tmp_path, capsys, monkeypatch):
        """`fuse` resolves its own host and out paths, so the resolver gate
        never sees it; without its own pre-flight the review drove a
        `[fuse] FAIL: [Errno 13] ...` line out of the rollback -- the bare
        errno this lane exists to abolish."""
        from espalier.fuse import cmd_fuse

        out_dir = tmp_path / "fused"
        args = _ns(host=str(init_tree), out=str(out_dir), fresh=True, dry_run=True, no_init=True, wire_hooks=False)
        monkeypatch.chdir(tmp_path)
        with locked(init_tree / ".claude"):
            rc = cmd_fuse(args)
        text = capsys.readouterr().err
        assert rc == 1 and "[fuse] FAIL: .claude cannot be read" in text, (rc, text)
        assert "Permission denied" in text and "permissions" in text, text
        assert not os.path.exists(out_dir), "fuse touched the output on a host it refused"


class TestEveryRepoTakingCommandAsksTheClaudeQuestion:
    """DEF-763's command-layer gate has three homes -- `cli._resolve_repo_arg`
    for the commands that resolve through it, `_refuse_unreadable_harness_root`
    for the pre-flights of the ones that resolve their own, and
    `surface_contract.unreadable_harness_root` in a library entry point or a
    command with its own voice (`fuse`, `doctor`, `audit`). A new command
    that resolves its own path skips all three silently; this contract
    derives the repo-taking commands from the parser and reds on one that
    asks nowhere. An exemption names its reason beside the command.
    """

    #: dests that carry a repo path.
    REPO_DESTS = frozenset({"repo", "host", "repo_root"})
    #: A repo-taking command whose gate is not in its own body, with the reason.
    GATE_EXEMPT: dict[str, str] = {
        "doctor": (
            "asks inside run_doctor_check, so the JSON report carries the "
            "finding for every caller; exit 1, a failed check, per CLI_EXIT_CODES"
        ),
    }
    GATE_CALLS = frozenset({
        "_resolve_repo_arg", "_refuse_unreadable_harness_root", "unreadable_harness_root",
    })

    @staticmethod
    def _repo_taking_commands() -> dict[str, object]:
        import argparse as _argparse

        from espalier.cli import build_parser

        parser = build_parser()
        top = next(a for a in parser._actions if isinstance(a, _argparse._SubParsersAction))
        found: dict[str, object] = {}

        def walk(prefix: str, sub) -> None:
            for name, child in sub.choices.items():
                full = f"{prefix} {name}".strip()
                nested = [a for a in child._actions if isinstance(a, _argparse._SubParsersAction)]
                if nested:
                    for action in nested:
                        walk(full, action)
                    continue
                dests = {a.dest for a in child._actions if a.option_strings == [] and a.dest}
                func = child.get_default("func")
                if func is not None and dests & TestEveryRepoTakingCommandAsksTheClaudeQuestion.REPO_DESTS:
                    found[full] = func

        walk("", top)
        return found

    @staticmethod
    def _calls(func) -> set[str]:
        import ast as _ast
        import inspect
        import textwrap

        tree = _ast.parse(textwrap.dedent(inspect.getsource(func)))
        names = set()
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                target = node.func
                names.add(target.attr if isinstance(target, _ast.Attribute) else getattr(target, "id", ""))
        return names

    def test_the_population_is_not_empty(self):
        commands = self._repo_taking_commands()
        assert len(commands) >= 20, sorted(commands)
        assert {"init", "upgrade", "fuse", "doctor", "audit", "merge-settings"} <= set(commands), sorted(commands)

    def test_every_repo_taking_command_asks_a_gate_or_names_its_exemption(self):
        commands = self._repo_taking_commands()
        ungated = sorted(
            name for name, func in commands.items()
            if name not in self.GATE_EXEMPT and not (self._calls(func) & self.GATE_CALLS)
        )
        assert not ungated, (
            "repo-taking command(s) that ask none of the three `.claude` gates "
            f"(DEF-763): {ungated}. Route through `_resolve_repo_arg`, add "
            "`_refuse_unreadable_harness_root` at the pre-flight, or add the name "
            "to GATE_EXEMPT with the reason it never reads `.claude/`."
        )
        stale = sorted(set(self.GATE_EXEMPT) - set(commands))
        assert not stale, f"GATE_EXEMPT names commands the parser no longer has: {stale}"
