"""Tests for ``espalier.worktree`` — ``_git_branch``,
``build_worktree_plan``, ``render_worktree_plan``, the helpers that
back the ``/worktree`` workflow and surface git branch state to the
statusline.

Pins ``_git_branch``'s contract: returns the current branch when in
a git repo (``main``, ``develop``, etc.), falls back to ``main``
when run outside a repo. Without this guard a subprocess-failure
regression could silently make the statusline always show ``main``
even on feature branches, defeating the cue the operator relies on
to avoid accidentally committing to the wrong branch.
"""
from __future__ import annotations

from pathlib import Path


from espalier.worktree import _git_branch, build_worktree_plan, render_worktree_plan


def _init_git_repo(path: Path, branch: str = "main") -> Path:
    """Create a minimal git repo with a committed file on the given branch."""
    import subprocess
    subprocess.run(["git", "init", "-b", branch, str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True, check=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)
    return path


class TestGitBranch:
    def test_returns_string(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        result = _git_branch(tmp_path)
        assert isinstance(result, str)

    def test_returns_main_for_main_branch(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        result = _git_branch(tmp_path)
        assert result == "main"

    def test_returns_custom_branch_name(self, tmp_path):
        _init_git_repo(tmp_path, branch="develop")
        result = _git_branch(tmp_path)
        assert result == "develop"

    def test_returns_main_fallback_for_non_git_dir(self, tmp_path):
        result = _git_branch(tmp_path)
        assert result == "main"

    def test_result_is_non_empty(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        result = _git_branch(tmp_path)
        assert len(result) > 0


class TestBuildWorktreePlan:
    def test_returns_dict(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert isinstance(plan, dict)

    def test_contains_repo_root_key(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert "repo_root" in plan

    def test_contains_base_branch_key(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert "base_branch" in plan

    def test_contains_lanes_key(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert "lanes" in plan

    def test_contains_commands_key(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert "commands" in plan

    def test_lanes_has_three_entries(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert len(plan["lanes"]) == 3

    def test_commands_has_three_entries(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert len(plan["commands"]) == 3

    def test_base_branch_reflects_git_branch(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert plan["base_branch"] == "main"

    def test_lane_names_are_distinct(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        names = [lane["name"] for lane in plan["lanes"]]
        assert len(set(names)) == 3

    def test_lane_branches_include_base_branch(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        for lane in plan["lanes"]:
            assert plan["base_branch"] in lane["branch"]

    def test_lane_branches_are_distinct(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        branches = [lane["branch"] for lane in plan["lanes"]]
        assert len(set(branches)) == 3

    def test_commands_contain_worktree_add(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        for cmd in plan["commands"]:
            assert "worktree add" in cmd

    def test_repo_root_in_plan_is_absolute(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        assert Path(plan["repo_root"]).is_absolute()

    def test_repo_root_forward_slashes_compatible(self, tmp_path):
        _init_git_repo(tmp_path, branch="main")
        plan = build_worktree_plan(tmp_path)
        # build_worktree_plan returns str(repo_root.resolve()) with NO separator
        # normalization, so on the windows-latest CI lane the raw value
        # legitimately contains backslashes — the old `assert "\\" not in
        # value.replace("\\","/")` was unconditionally true and discriminated
        # nothing. Assert the SUT's forward-slash-normalized value equals the
        # expected posix path (computed independently from the fixture): REDs if
        # the SUT stops resolving, returns a relative path, or mangles the root.
        assert plan["repo_root"].replace("\\", "/") == tmp_path.resolve().as_posix()

    def test_repo_name_with_spaces_becomes_hyphenated_in_commands(self, tmp_path):
        spaced = tmp_path / "my project"
        spaced.mkdir()
        _init_git_repo(spaced, branch="main")
        plan = build_worktree_plan(spaced)
        # The worktree TARGET path segment ("../<root>-lane-*") must hyphenate
        # the space in the repo dir name ("my project" -> "my-project"). Isolate
        # the target by structure ("worktree add <target> -b <branch>") rather
        # than by whitespace split: the repo path itself contains a space, so a
        # naive cmd.split() scatters both the path AND the target. The prior
        # version scanned split tokens for one containing both "my" and
        # "project" -- once the SUT stopped hyphenating, the space split the
        # name across two tokens satisfying neither half of the guard, so it
        # matched nothing and 0 assertions ran (the regression stayed green).
        targets = [
            cmd.split(" worktree add ", 1)[1].split(" -b ", 1)[0]
            for cmd in plan["commands"]
        ]
        assert targets, "expected at least one worktree add command"
        for target in targets:
            assert " " not in target
            assert "my-project" in target

    def test_a_spaced_repo_root_is_one_word_in_every_command(self, tmp_path):
        """The ``-C`` root is the reader's checkout, and a space in it split the
        printed command into two words, so git changed into the truncated prefix
        and aborted (driven in PowerShell, cmd and Git Bash on Windows 11:
        ``fatal: cannot change to '...\\def912'``). Quoted, it is one word in
        all three, and in a POSIX shell's tokenizer here."""
        import shlex
        spaced = tmp_path / "my project"
        spaced.mkdir()
        _init_git_repo(spaced, branch="main")
        plan = build_worktree_plan(spaced)
        assert len(plan["commands"]) == 3
        for cmd in plan["commands"]:
            words = shlex.split(cmd, posix=True)
            assert words[:5] == ["git", "-C", str(spaced.resolve()), "worktree", "add"], cmd

    def test_the_printed_root_runs_in_the_hosts_own_shell(self, tmp_path):
        """The real oracle: each command's ``git -C <root>`` prefix, as printed,
        handed to this host's default shell (cmd on Windows, sh elsewhere) with a
        read-only verb in place of ``worktree add``, lands in the spaced root."""
        import os
        import subprocess
        spaced = tmp_path / "my project"
        spaced.mkdir()
        _init_git_repo(spaced, branch="main")
        # An inherited GIT_DIR or GIT_WORK_TREE (pytest run from a git hook)
        # would point rev-parse at the outer repository instead.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        for cmd in build_worktree_plan(spaced)["commands"]:
            prefix = cmd.split(" worktree add ", 1)[0]
            # The shell IS the oracle: the printed text must survive its word split.
            proc = subprocess.run(f"{prefix} rev-parse --show-toplevel", shell=True,  # noqa: S602
                                  capture_output=True, text=True, timeout=60, env=env)
            assert proc.returncode == 0, (cmd, proc.stderr)
            assert Path(proc.stdout.strip()).resolve() == spaced.resolve(), (cmd, proc.stdout)

    def test_an_unspaced_repo_root_is_printed_bare(self, tmp_path):
        """No quotes where none are needed: the plain root reads as before."""
        root = tmp_path / "plainrepo"
        root.mkdir()
        _init_git_repo(root, branch="main")
        resolved = str(root.resolve())
        if any(ch.isspace() for ch in resolved):
            import pytest
            pytest.skip("this host's temp root itself holds whitespace")
        for cmd in build_worktree_plan(root)["commands"]:
            assert cmd.startswith(f"git -C {resolved} worktree add "), cmd

    def test_custom_branch_propagates_to_lane_branches(self, tmp_path):
        _init_git_repo(tmp_path, branch="feature-x")
        plan = build_worktree_plan(tmp_path)
        assert plan["base_branch"] == "feature-x"
        for lane in plan["lanes"]:
            assert "feature-x" in lane["branch"]


class TestRenderWorktreePlan:
    def _make_plan(self, tmp_path) -> dict:
        _init_git_repo(tmp_path, branch="main")
        return build_worktree_plan(tmp_path)

    def test_returns_string(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert isinstance(result, str)

    def test_ends_with_newline(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert result.endswith("\n")

    def test_contains_worktree_plan_header(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert "WORKTREE PLAN" in result

    def test_contains_repo_root(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert plan["repo_root"].replace("\\", "/") in result.replace("\\", "/")

    def test_contains_base_branch(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert plan["base_branch"] in result

    def test_contains_all_commands(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        for cmd in plan["commands"]:
            assert cmd in result

    def test_contains_suggested_commands_label(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert "Suggested worktree commands" in result

    def test_commands_prefixed_with_dash(self, tmp_path):
        plan = self._make_plan(tmp_path)
        result = render_worktree_plan(plan)
        for cmd in plan["commands"]:
            assert f"- {cmd}" in result

    def test_non_git_dir_does_not_crash(self, tmp_path):
        plan = build_worktree_plan(tmp_path)
        result = render_worktree_plan(plan)
        assert isinstance(result, str)
