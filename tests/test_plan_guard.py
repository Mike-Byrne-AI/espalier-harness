"""Tests for tools/cc/hooks/plan_guard.py — write-intent detection and root-file policy.

Tests cover:
  - bash_has_write_intent() unit tests (import directly)
  - Redirect-before-allowlist regression (classification order)
  - Root-level source/config file blocking
  - Active-plan positive path (blocked commands pass when plan exists)
  - Read-only commands always allowed

This module exercises *classifier correctness* — does
bash_has_write_intent, _mcp_tool_is_write, and the dispatch logic
classify inputs the way we expect? It runs the hook as a subprocess
and imports the helpers directly.

The companion module tests/test_plan_guard_branch_pinned.py pins the
*wiring contract* post-TP-64: the .claude/settings.json matcher is
narrow (Write|Edit|NotebookEdit), the in-source banner documents the
unreachability, and the Bash/PowerShell/MCP branches remain as
importable classifiers. If a future change widens the matcher AND
deletes the branches in the same commit, that pin test fires.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._hook_assertions import assert_hook_allowed, assert_hook_denied

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))


def run_hook(command_str: str, tmp_path: Path, *, with_plan: bool = False) -> subprocess.CompletedProcess:
    """Run plan_guard.py with a Bash tool event."""
    script = HOOKS_DIR / "plan_guard.py"
    if with_plan:
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir(exist_ok=True)
        plan = {"task": "test", "status": "in_progress", "steps": [{"description": "test step"}]}
        (cc_dir / "execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    payload = {"tool_name": "Bash", "tool_input": {"command": command_str}}
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env, encoding="utf-8",
    )


def run_hook_edit(file_path: str, tmp_path: Path, *, with_plan: bool = False) -> subprocess.CompletedProcess:
    """Run plan_guard.py with an Edit tool event."""
    script = HOOKS_DIR / "plan_guard.py"
    if with_plan:
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir(exist_ok=True)
        plan = {"task": "test", "status": "in_progress", "steps": [{"description": "test step"}]}
        (cc_dir / "execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    payload = {"tool_name": "Edit", "tool_input": {"file_path": file_path}}
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env, encoding="utf-8",
    )


# ── Unit tests for bash_has_write_intent ──────────────────────────────────────


class TestBashWriteIntentDetection:
    """Direct unit tests for the bash_has_write_intent() classifier."""

    def _fn(self, command: str) -> bool:
        from plan_guard import bash_has_write_intent
        return bash_has_write_intent(command)

    # Redirect forms
    def test_output_redirect_detected(self):
        assert self._fn("echo x > src/x.py") is True

    def test_append_redirect_detected(self):
        assert self._fn("echo x >> src/x.py") is True

    def test_cat_pipe_redirect_detected(self):
        assert self._fn("cat > src/x.py") is True

    def test_cat_copy_redirect_detected(self):
        assert self._fn("cat src/a.py > src/b.py") is True

    # Mutation commands
    def test_rm_detected(self):
        assert self._fn("rm src/x.py") is True

    def test_mv_detected(self):
        assert self._fn("mv a.py src/x.py") is True

    def test_cp_detected(self):
        assert self._fn("cp a.py src/x.py") is True

    def test_touch_detected(self):
        assert self._fn("touch src/new.py") is True

    def test_mkdir_detected(self):
        assert self._fn("mkdir src/new_package") is True

    def test_tee_detected(self):
        assert self._fn("tee src/x.py") is True

    def test_tee_append_detected(self):
        assert self._fn("tee -a src/x.py") is True

    def test_sed_inplace_detected(self):
        assert self._fn("sed -i 's/a/b/' src/x.py") is True

    def test_perl_inplace_detected(self):
        assert self._fn("perl -pi -e 's/a/b/' src/x.py") is True

    # Python -c write APIs
    def test_python_open_write_mode_detected(self):
        assert self._fn("python -c \"open('src/x.py','w').write('x')\"") is True

    def test_python_path_write_text_detected(self):
        assert self._fn("python -c \"Path('src/x.py').write_text('x')\"") is True

    def test_python_write_text_shorthand_detected(self):
        assert self._fn("python -c \"p.write_text('x')\"") is True

    def test_python_shutil_copy_detected(self):
        assert self._fn("python -c \"shutil.copyfile('a', 'src/x.py')\"") is True

    def test_python_os_remove_detected(self):
        assert self._fn("python -c \"os.remove('src/x.py')\"") is True

    def test_python_path_unlink_detected(self):
        assert self._fn("python -c \"Path('src/x.py').unlink()\"") is True

    # Read-only — must NOT be detected as writes
    def test_echo_no_redirect_not_write(self):
        assert self._fn("echo hello") is False

    def test_cat_read_not_write(self):
        assert self._fn("cat src/x.py") is False

    def test_python_print_not_write(self):
        assert self._fn("python -c \"print('hello')\"") is False

    def test_python_read_text_not_write(self):
        assert self._fn("python -c \"import pathlib; print(pathlib.Path('src/x.py').read_text())\"") is False

    def test_grep_not_write(self):
        assert self._fn("grep -R foo src/") is False

    def test_rg_not_write(self):
        assert self._fn("rg foo src/") is False

    def test_fd_redirect_not_write(self):
        assert self._fn("command 2>&1") is False

    def test_fd_redirect_stderr_not_write(self):
        assert self._fn("command >&2") is False

    def test_pytest_not_write(self):
        assert self._fn("python -m pytest -q") is False


# ── Regression: classification order ─────────────────────────────────────────


class TestClassificationOrder:
    """Redirects and inline-Python writes must be caught BEFORE the read-only allowlist.

    Historical bug: the read-only regex matched `echo`, `cat`, `python -c` as safe
    before write-intent detection ran, silently allowing writes without a plan.
    """

    def test_plan_guard_checks_redirects_before_readonly_allowlist(self, tmp_path):
        """echo x > src/x.py must be blocked even though echo is in the read-only list."""
        result = run_hook("echo x > src/x.py", tmp_path)
        assert_hook_denied(result)

    def test_plan_guard_blocks_inline_python_write_before_python_allowlist(self, tmp_path):
        """python -c with open(...,'w') must be blocked without a plan."""
        result = run_hook("python -c \"open('src/x.py','w').write('x')\"", tmp_path)
        assert_hook_denied(result)

    def test_cat_redirect_blocked_not_allowed_as_readonly(self, tmp_path):
        """cat src/a.py > src/b.py must be blocked even though cat looks read-only."""
        result = run_hook("cat src/a.py > src/b.py", tmp_path)
        assert_hook_denied(result)

    def test_python_path_write_text_blocked(self, tmp_path):
        """python -c with Path.write_text must be blocked without a plan."""
        result = run_hook(
            "python -c \"from pathlib import Path; Path('src/x.py').write_text('x')\"",
            tmp_path,
        )
        assert_hook_denied(result)

    def test_append_redirect_blocked(self, tmp_path):
        """echo x >> src/x.py must be blocked without a plan."""
        result = run_hook("echo x >> src/x.py", tmp_path)
        assert_hook_denied(result)

    def test_touch_blocked_without_plan(self, tmp_path):
        """touch src/new.py must be blocked without a plan."""
        result = run_hook("touch src/new.py", tmp_path)
        assert_hook_denied(result)

    def test_sed_inplace_blocked_without_plan(self, tmp_path):
        """sed -i must be blocked without a plan."""
        result = run_hook("sed -i 's/a/b/' src/x.py", tmp_path)
        assert_hook_denied(result)

    # Read-only counterexamples — must remain allowed without a plan
    def test_echo_no_redirect_allowed(self, tmp_path):
        """echo hello (no redirect) must be allowed without a plan."""
        result = run_hook("echo hello", tmp_path)
        assert_hook_allowed(result)

    def test_cat_read_allowed(self, tmp_path):
        """cat src/x.py (read) must be allowed without a plan."""
        result = run_hook("cat src/x.py", tmp_path)
        assert_hook_allowed(result)

    def test_python_print_allowed(self, tmp_path):
        """python -c print(...) must be allowed without a plan."""
        result = run_hook("python -c \"print('x')\"", tmp_path)
        assert_hook_allowed(result)

    def test_python_read_text_allowed(self, tmp_path):
        """python -c read_text must be allowed without a plan."""
        result = run_hook(
            "python -c \"from pathlib import Path; print(Path('src/x.py').read_text())\"",
            tmp_path,
        )
        assert_hook_allowed(result)


# ── Root-level file policy ────────────────────────────────────────────────────


class TestRootFilePolicy:
    """Root-level source/config/project files must require a plan.

    Previously, ALL root-level files were exempt. Now only known transient/harness
    files (e.g. ESPALIER_MEMORY.md) remain exempt; source, config, and known project docs require a plan.
    """

    def test_edit_main_py_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("main.py", tmp_path)
        assert_hook_denied(result)

    def test_edit_memory_note_allowed_without_plan(self, tmp_path):
        """§C23/DEF-440: the deployed reflect skill and /handoff both instruct a
        `memory/*.md` write at status='complete' — the exact moment no plan is
        active. Denying it makes the harness block its own prescribed workflow."""
        result = run_hook_edit("memory/new-lesson.md", tmp_path)
        assert_hook_allowed(result)

    def test_edit_docs_allowed_without_plan(self, tmp_path):
        """§C23/DEF-495: stop_gate Gate 2 orders a docs-maintainer run that writes
        `docs/*.md`. Denying those edits made the gate unpassable on its own terms
        — and subagent_stop set the relief flag on agent COMPLETION, so the gate
        then passed with zero docs written."""
        result = run_hook_edit("docs/CONVENTIONS.md", tmp_path)
        assert_hook_allowed(result)

    def test_edit_app_py_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("app.py", tmp_path)
        assert_hook_denied(result)

    def test_edit_pyproject_toml_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("pyproject.toml", tmp_path)
        assert_hook_denied(result)

    def test_edit_readme_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("README.md", tmp_path)
        assert_hook_denied(result)

    def test_edit_changelog_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("CHANGELOG.md", tmp_path)
        assert_hook_denied(result)

    def test_edit_contributing_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("CONTRIBUTING.md", tmp_path)
        assert_hook_denied(result)

    def test_edit_requirements_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("requirements.txt", tmp_path)
        assert_hook_denied(result)

    def test_edit_dockerfile_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("Dockerfile", tmp_path)
        assert_hook_denied(result)

    def test_memory_md_still_exempt(self, tmp_path):
        """ESPALIER_MEMORY.md is a harness-internal file and must remain exempt."""
        result = run_hook_edit("ESPALIER_MEMORY.md", tmp_path)
        assert result.returncode == 0

    def test_src_file_blocked_without_plan(self, tmp_path):
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)


# ── Active-plan positive path ─────────────────────────────────────────────────


class TestActivePlanAllowsWrites:
    """Every command that is blocked without a plan must be allowed when one exists."""

    def test_edit_src_file_allowed_with_plan(self, tmp_path):
        result = run_hook_edit("src/app.py", tmp_path, with_plan=True)
        assert result.returncode == 0

    def test_edit_main_py_allowed_with_plan(self, tmp_path):
        result = run_hook_edit("main.py", tmp_path, with_plan=True)
        assert result.returncode == 0

    def test_redirect_allowed_with_plan(self, tmp_path):
        result = run_hook("echo x > src/x.py", tmp_path, with_plan=True)
        assert_hook_allowed(result)

    def test_python_write_allowed_with_plan(self, tmp_path):
        result = run_hook(
            "python -c \"open('src/x.py','w').write('x')\"",
            tmp_path,
            with_plan=True,
        )
        assert_hook_allowed(result)

    def test_path_write_text_allowed_with_plan(self, tmp_path):
        result = run_hook(
            "python -c \"Path('src/x.py').write_text('x')\"",
            tmp_path,
            with_plan=True,
        )
        assert_hook_allowed(result)

    def test_touch_allowed_with_plan(self, tmp_path):
        result = run_hook("touch src/new.py", tmp_path, with_plan=True)
        assert_hook_allowed(result)

    def test_sed_inplace_allowed_with_plan(self, tmp_path):
        result = run_hook("sed -i 's/a/b/' src/x.py", tmp_path, with_plan=True)
        assert_hook_allowed(result)

    def test_edit_pyproject_toml_allowed_with_plan(self, tmp_path):
        result = run_hook_edit("pyproject.toml", tmp_path, with_plan=True)
        assert result.returncode == 0

    def test_edit_readme_allowed_with_plan(self, tmp_path):
        result = run_hook_edit("README.md", tmp_path, with_plan=True)
        assert result.returncode == 0


# ── Always-allowed read-only commands ────────────────────────────────────────


class TestReadOnlyCommandsAlwaysAllowed:
    """Read-only developer commands must pass without any active plan."""

    def test_pytest_allowed(self, tmp_path):
        result = run_hook("python -m pytest -q", tmp_path)
        assert_hook_allowed(result)

    def test_grep_allowed(self, tmp_path):
        result = run_hook("grep -R foo src/", tmp_path)
        assert_hook_allowed(result)

    def test_rg_allowed(self, tmp_path):
        result = run_hook("rg foo src/", tmp_path)
        assert_hook_allowed(result)

    def test_cat_read_allowed(self, tmp_path):
        result = run_hook("cat src/x.py", tmp_path)
        assert_hook_allowed(result)

    def test_ls_allowed(self, tmp_path):
        result = run_hook("ls src/", tmp_path)
        assert_hook_allowed(result)

    def test_git_status_allowed(self, tmp_path):
        result = run_hook("git status", tmp_path)
        assert_hook_allowed(result)

    def test_python_read_text_allowed(self, tmp_path):
        result = run_hook(
            "python -c \"import pathlib; print(pathlib.Path('src/x.py').read_text())\"",
            tmp_path,
        )
        assert_hook_allowed(result)

    def test_fd_redirect_stderr_allowed(self, tmp_path):
        result = run_hook("command 2>&1", tmp_path)
        assert_hook_allowed(result)


class TestMaintenanceModeBypass:
    """ESPALIER_MAINTENANCE_MODE=1 in env bypasses the plan-required check.

    Bypass runs before stdin parsing — stays inert if the flag is unset and
    on falsy values, identical to write_guard's contract.
    """

    def _run(self, payload: dict, tmp_path: Path, *, mode: str | None):
        script = HOOKS_DIR / "plan_guard.py"
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        if mode is not None:
            env["ESPALIER_MAINTENANCE_MODE"] = mode
        else:
            env.pop("ESPALIER_MAINTENANCE_MODE", None)
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            env=env, encoding="utf-8",
        )

    def test_root_source_write_denied_without_plan_or_flag(self, tmp_path):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}}
        result = self._run(payload, tmp_path, mode=None)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_root_source_write_allowed_with_flag_no_plan(self, tmp_path):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}}
        result = self._run(payload, tmp_path, mode="1")
        assert result.returncode == 0
        assert result.stdout == "", f"expected empty stdout (allow), got {result.stdout!r}"
        assert "MAINTENANCE_MODE" in result.stderr

    def test_bash_write_intent_allowed_with_flag_no_plan(self, tmp_path):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo x > src/x.py"},
        }
        result = self._run(payload, tmp_path, mode="1")
        assert result.returncode == 0
        assert result.stdout == ""

    def test_flag_value_must_be_exactly_one(self, tmp_path):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}}
        for falsy in ("", "0", "true", "yes"):
            result = self._run(payload, tmp_path, mode=falsy)
            output = json.loads(result.stdout)
            assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
                f"flag value {falsy!r} should not bypass"
            )


# ── TP-33: strict active-plan predicate ──────────────────────────────────────


def _write_plan(repo_root: Path, *, status, with_steps: bool = True) -> None:
    """Write cc/execution_plan.json with the given status under repo_root.

    status=None omits the status key entirely. with_steps=False omits steps,
    exercising the "no-steps" branch of the gate.
    """
    cc_dir = repo_root / "cc"
    cc_dir.mkdir(exist_ok=True)
    plan: dict = {"task": "tp33-test"}
    if status is not None:
        plan["status"] = status
    if with_steps:
        plan["steps"] = [{"description": "test step"}]
    (cc_dir / "execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")


class TestPlanGuardStatusPredicate:
    """TP-33: plan_guard treats ONLY status='in_progress' as an active mutation window.

    Pre-fix, `_plan_exists` returned True for both "in_progress" and
    "complete", so a completed plan kept the mutation window open until
    the file was reset. The fix tightens the predicate to
    `status == "in_progress"`. The parametrized table below pins the
    full status space so the regression cannot return.
    """

    @pytest.mark.parametrize("status", [
        "complete",
        "blocked",      # TP-117 expansion: blocked must deny too
        "planned",
        "cancelled",
        "",
        "unknown",
        "Complete",     # case sensitivity
        "IN_PROGRESS",  # case sensitivity
    ])
    def test_non_in_progress_denies_write(self, tmp_path, status):
        _write_plan(tmp_path, status=status)
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)

    def test_in_progress_allows_write(self, tmp_path):
        _write_plan(tmp_path, status="in_progress")
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_allowed(result)

    def test_missing_plan_file_denies(self, tmp_path):
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)

    def test_malformed_json_denies(self, tmp_path):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir(exist_ok=True)
        (cc_dir / "execution_plan.json").write_text("{not valid json", encoding="utf-8")
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)

    def test_no_steps_denies_even_when_in_progress(self, tmp_path):
        _write_plan(tmp_path, status="in_progress", with_steps=False)
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)

    def test_status_omitted_denies(self, tmp_path):
        _write_plan(tmp_path, status=None)
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)

    def test_complete_status_specifically_denies(self, tmp_path):
        """TP-33 regression case: 'complete' was treated as active pre-fix."""
        _write_plan(tmp_path, status="complete")
        result = run_hook_edit("src/app.py", tmp_path)
        assert_hook_denied(result)

    def test_complete_status_specifically_denies_bash(self, tmp_path):
        """Same regression case for the Bash write-intent path."""
        _write_plan(tmp_path, status="complete")
        result = run_hook("echo x > src/x.py", tmp_path)
        assert_hook_denied(result)


class TestPlanGuardDenyReasonContent:
    """TP-33 Task 33-D: deny reason must mention the actual plan state.

    Useful operator signal — without seeing the status value in the
    reason, the user can't tell whether the plan is missing, complete,
    or some other closed state.
    """

    def _reason(self, result):
        payload = json.loads(result.stdout)
        return payload["hookSpecificOutput"]["permissionDecisionReason"]

    def test_reason_names_complete_status(self, tmp_path):
        _write_plan(tmp_path, status="complete")
        result = run_hook_edit("src/app.py", tmp_path)
        reason = self._reason(result)
        assert "complete" in reason, f"reason should name 'complete': {reason!r}"

    def test_reason_names_planned_status(self, tmp_path):
        _write_plan(tmp_path, status="planned")
        result = run_hook_edit("src/app.py", tmp_path)
        reason = self._reason(result)
        assert "planned" in reason, f"reason should name 'planned': {reason!r}"

    def test_reason_says_missing_when_file_absent(self, tmp_path):
        result = run_hook_edit("src/app.py", tmp_path)
        reason = self._reason(result)
        assert "missing" in reason, f"reason should say 'missing': {reason!r}"

    def test_reason_says_malformed_for_bad_json(self, tmp_path):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir(exist_ok=True)
        (cc_dir / "execution_plan.json").write_text("{bad json", encoding="utf-8")
        result = run_hook_edit("src/app.py", tmp_path)
        reason = self._reason(result)
        assert "malformed" in reason, f"reason should say 'malformed': {reason!r}"

    def test_reason_says_no_steps_when_steps_empty(self, tmp_path):
        _write_plan(tmp_path, status="in_progress", with_steps=False)
        result = run_hook_edit("src/app.py", tmp_path)
        reason = self._reason(result)
        assert "no-steps" in reason, f"reason should say 'no-steps': {reason!r}"

    def test_reason_names_plan_exempt_prefixes_escape(self, tmp_path):
        """TP-99 B4: deny reason must point adopters at plan_exempt_prefixes.

        Pre-TP-99 the deny message named only `/implement-task` as the escape,
        which trained adopters to relaunch with ESPALIER_MAINTENANCE_MODE=1
        (the trap TP-97 was designed to prevent). The hint surfaces the
        narrow knob first and explicitly warns against MAINTENANCE_MODE.
        """
        _write_plan(tmp_path, status="complete")
        result = run_hook_edit("src/app.py", tmp_path)
        reason = self._reason(result)
        assert "plan_exempt_prefixes" in reason, (
            f"reason should name plan_exempt_prefixes escape valve: {reason!r}"
        )
        assert "espalier.toml" in reason, (
            f"reason should name espalier.toml as the config surface: {reason!r}"
        )


# ── TP-47 (M12): out-of-repo path exemption ───────────────────────────────────


class TestPlanGuardOutOfRepoExemption:
    """Paths outside repo root are outside the harness's governance scope.

    _normalize_path returns the raw absolute string when relative_to(root)
    fails (path is not under repo root). _is_exempt's absolute-path branch
    returns True for these so plan-mode writes to ~/.claude/plans/* and
    similar do not trigger plan-required denials. write_guard's own
    _normalize_path resolves symlinks before its protected check, so this
    exemption does not enable redirect attacks into the repo.
    """

    def test_home_plans_path_exempt_without_plan(self, tmp_path):
        """Write to ~/.claude/plans/foo.md passes plan_guard without active plan."""
        # Derive from the real home: an absolute home path is out of the repo
        # root on any platform. The POSIX literal /Users/... is NOT absolute on
        # Windows (a drive letter is required), so it would not be exempted.
        home_plan = Path.home() / ".claude" / "plans" / "foo.md"
        result = run_hook_edit(str(home_plan), tmp_path)
        assert result.returncode == 0
        assert result.stdout == "", f"expected silent allow, got: {result.stdout!r}"

    def test_tmp_path_exempt_without_plan(self, tmp_path):
        """An absolute path outside the repo root is outside governance scope."""
        # tmp_path.parent is a sibling of the repo root: absolute and out of
        # repo on any platform (the POSIX literal /tmp is not absolute on Windows).
        outside = tmp_path.parent / "scratch.md"
        result = run_hook_edit(str(outside), tmp_path)
        assert result.returncode == 0
        assert result.stdout == "", f"expected silent allow, got: {result.stdout!r}"

    def test_in_repo_relative_path_still_requires_plan(self, tmp_path):
        """Regression: the fix must not weaken in-repo enforcement."""
        result = run_hook_edit("src/module.py", tmp_path)
        assert_hook_denied(result)


# ── TP-142 (FM-2 §10.4): fail-closed umbrella ──────────────────────────


class TestPlanGuardFailClosed:
    """FM-2 §10.4 close: plan_guard.main MUST fail-closed on internal exception.

    Sister-site of write_guard's existing umbrella (write_guard.py main).
    Negative proof: inject a function that raises inside _run_main; assert
    the wrapper exits 0 with a deny() payload on stdout (channel-XOR),
    NOT exit 1 (which Claude Code would treat as "non-blocking script
    error" and the tool call would proceed).
    """

    def test_fail_closed_on_runtime_error(self, monkeypatch, capsys):
        # Clear maintenance-mode env so _run_main's bypass doesn't
        # short-circuit before reaching the injected boom (the parent
        # shell may have ESPALIER_MAINTENANCE_MODE=1 set during pack
        # execution).
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)

        import importlib
        if "plan_guard" in sys.modules:
            plan_guard = importlib.reload(sys.modules["plan_guard"])
        else:
            import plan_guard  # type: ignore[import-not-found]

        def boom():
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr(plan_guard._hook_utils, "read_stdin_safely", boom)
        rc = plan_guard.main()
        captured = capsys.readouterr()
        # Channel-XOR: exit 0 + structured deny on stdout (NOT exit 1).
        assert rc == 0
        assert "[ERROR] plan_guard crashed: RuntimeError" in captured.err
        # The deny envelope is JSON; tests/test_hook_protocol.py pins the
        # exact schema. Here we just assert SOMETHING was emitted on stdout.
        assert captured.out.strip(), "expected deny envelope on stdout"
        assert "plan_guard internal error" in captured.out

    def test_fail_closed_on_attribute_error(self, monkeypatch, capsys):
        """Tool_input shape changes (future-CC API drift) would surface
        as AttributeError. Same fail-closed contract applies."""
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)

        import importlib
        if "plan_guard" in sys.modules:
            plan_guard = importlib.reload(sys.modules["plan_guard"])
        else:
            import plan_guard  # type: ignore[import-not-found]

        def boom():
            raise AttributeError("'dict' object has no attribute 'new_field'")

        monkeypatch.setattr(plan_guard._hook_utils, "read_stdin_safely", boom)
        rc = plan_guard.main()
        captured = capsys.readouterr()
        assert rc == 0
        assert "[ERROR] plan_guard crashed: AttributeError" in captured.err
        assert captured.out.strip()
