"""DEF-743 -- the path guards inside a git worktree of the repository.

A Claude Code session that enters a worktree keeps ``CLAUDE_PROJECT_DIR`` at
the project root while every path it edits sits under the worktree (the
``cc-worktrees`` external pin). Relativised against the root alone, a worktree
target read ``.claude/worktrees/<name>/tools/cc/x.py`` -- no protected prefix,
and plan-exempt under ``.claude/`` -- so both blocking guards allowed
everything there (driven 2026-09-09: the same path at the root was denied).

The fix keys a target to the checkout that CONTAINS it: ``_hook_utils`` reads
git's own worktree registry (``<common>/worktrees/<id>/gitdir``, no
subprocess) and every normaliser relativises against the deepest containing
checkout, so a worktree's ``tools/cc/`` reads as ``tools/cc/``. The sites that
rejoin the relative path to a directory afterwards (the hardlink backstop,
post_write_check's read and prune) take that checkout as their base.

Written and run RED against HEAD before the source edit -- red by ordering,
never by stash or checkout.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path, PureWindowsPath

import pytest

from tests._spaced_paths import PS, quoted

from _hook_assertions import assert_hook_allowed
from _hook_runner import run_hook
from test_nested_repo_litter import _add_worktree, _git, _init_repo, _seed_commit

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
TARGET = "tools/cc/hooks/write_guard.py"
_GUARD_CLAUSE = "do not govern writes made inside it"


def _hook_utils():
    spec = importlib.util.spec_from_file_location("_hook_utils", HOOKS_DIR / "_hook_utils.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _session_start():
    spec = importlib.util.spec_from_file_location("_ss_worktree", HOOKS_DIR / "session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hook_module(name: str):
    """A hook module by the sys.path dance the reinject pins use: the hooks
    import their siblings by bare name, so a spec load under another name
    would not bind them."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


def _env(root: Path) -> dict:
    # CLAUDE_PROJECT_DIR at the ROOT, as Claude Code keeps it for a worktree
    # session; the maintenance bypass this repo's own sessions run under is
    # popped so the protected-zone and plan checks actually run.
    return {"CLAUDE_PROJECT_DIR": str(root), "ESPALIER_MAINTENANCE_MODE": None}


def _repo(tmp_path: Path) -> Path:
    """A seeded repository carrying a harness zone, a source file and a test."""
    root = tmp_path / "repo"
    root.mkdir()
    _seed_commit(root)
    (root / "tools" / "cc" / "hooks").mkdir(parents=True)
    (root / TARGET).write_text("print('guard')\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "layout"], root)
    return root


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """The repository plus a registered worktree at ``.claude/worktrees/live``
    checked out from it (the shape ``EnterWorktree`` / ``isolation: worktree``
    / ``--worktree`` create)."""
    root = _repo(tmp_path)
    return root, _add_worktree(root, "live")


def _foreign_clone(root: Path) -> Path:
    """A clone dropped into the tree: its own repository, not a checkout of this one."""
    foreign = root / "vendor" / "foreign"
    foreign.mkdir(parents=True)
    _init_repo(foreign)
    return foreign


def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def _write_payload(target: Path, cwd: Path) -> dict:
    return {
        "hook_event_name": "PreToolUse", "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "x"}, "cwd": str(cwd),
    }


def _decision(result) -> str:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


class TestSiblingCheckouts:
    """``_hook_utils.sibling_checkouts``: the OTHER checkouts of the repository
    ``root`` belongs to, read from git's registry on disk -- no subprocess."""

    def test_a_plain_repository_has_none(self, tmp_path):
        assert _hook_utils().sibling_checkouts(_repo(tmp_path)) == ()

    def test_a_registered_worktree_nested_under_the_root_is_one(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        assert _hook_utils().sibling_checkouts(root) == (live.resolve(),)

    def test_a_registered_worktree_beside_the_root_is_one(self, tmp_path):
        root = _repo(tmp_path)
        beside = tmp_path / "beside"
        _git(["worktree", "add", str(beside), "-b", "wt-beside"], root)
        assert _hook_utils().sibling_checkouts(root) == (beside.resolve(),)

    def test_a_worktree_whose_directory_is_gone_is_skipped(self, tmp_path):
        # Registered but prunable: `git worktree prune` has not run yet.
        root, live = _repo_with_worktree(tmp_path)
        shutil.rmtree(live)
        assert _hook_utils().sibling_checkouts(root) == ()

    def test_from_inside_a_worktree_the_main_checkout_is_a_sibling(self, tmp_path):
        # The operator launched Claude IN the worktree: CLAUDE_PROJECT_DIR is
        # the worktree, its `.git` is a gitlink, and the main checkout is the
        # other checkout of the same repository. Never the root itself.
        root, live = _repo_with_worktree(tmp_path)
        assert _hook_utils().sibling_checkouts(live) == (root.resolve(),)

    def test_a_nested_clone_and_a_submodule_shape_are_not_checkouts(self, tmp_path):
        root = _repo(tmp_path)
        _foreign_clone(root)
        sub = root / "vendor" / "sub"
        sub.mkdir()
        (root / ".git" / "modules" / "sub").mkdir(parents=True)
        (sub / ".git").write_text("gitdir: ../../.git/modules/sub\n", encoding="utf-8")  # the submodule gitlink shape
        assert _hook_utils().sibling_checkouts(root) == ()

    def test_outside_a_repository_and_on_a_pure_path_the_answer_is_empty(self, tmp_path):
        hu = _hook_utils()
        plain = tmp_path / "plain"
        plain.mkdir()
        assert hu.sibling_checkouts(plain) == ()
        # The FS-free tests hand the normalisers a PureWindowsPath root; a pure
        # path has no filesystem behind it and must not raise.
        assert hu.sibling_checkouts(PureWindowsPath("C:/Users/anyone/repo")) == ()

    def test_the_memo_is_per_process_and_cleared_by_hand(self, tmp_path):
        # A hook process is one tool call; a test worker is not. The conftest
        # fixture clears both memos around every test; in-process, clear them
        # after registering a worktree on a root that was already read.
        root = _repo(tmp_path)
        hu = _hook_utils()
        assert hu.sibling_checkouts(root) == ()
        live = _add_worktree(root, "live")
        assert hu.sibling_checkouts(root) == ()  # memoised: the registry is not re-read
        hu._SIBLING_CHECKOUTS_MEMO.clear()
        hu._CHECKOUT_BASES_MEMO.clear()
        assert hu.sibling_checkouts(root) == (live.resolve(),)
        assert hu.is_sibling_checkout(root, live)
        assert hu.sibling_checkout_containing(root, live / "src") == live.resolve()
        assert hu.sibling_checkout_containing(root, root / "src") is None


class TestSiblingCheckoutContaining:
    """``_hook_utils.sibling_checkout_containing`` answers the DEEPEST checkout
    holding the path, the root among them, and ``None`` when that is the root.
    From a worktree nested in the main checkout's folder the main checkout is
    the first sibling listed and holds every path in the worktree by folder;
    the first match named it on every worker seat's banner (DEF-5068)."""

    def test_from_a_nested_worktree_root_its_own_path_names_no_sibling(self, tmp_path):
        # The probe's shape: the session's root is the worktree, its cwd the root.
        _root, live = _repo_with_worktree(tmp_path)
        hu = _hook_utils()
        assert hu.sibling_checkout_containing(live, live) is None
        assert hu.sibling_checkout_containing(live, live / "src") is None

    def test_from_a_nested_worktree_root_a_second_nested_worktree_is_named(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        other = _add_worktree(root, "other")
        assert _hook_utils().sibling_checkout_containing(live, other / "src") == other.resolve()

    def test_from_a_nested_worktree_root_the_main_checkouts_own_folder_names_it(self, tmp_path):
        # The deepest holding the path is still the main checkout here (control).
        root, live = _repo_with_worktree(tmp_path)
        assert _hook_utils().sibling_checkout_containing(live, root / "src") == root.resolve()

    def test_from_a_root_beside_the_main_checkout_a_nested_worktree_is_named(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        beside = tmp_path / "beside"
        _git(["worktree", "add", str(beside), "-b", "wt-beside"], root)
        assert _hook_utils().sibling_checkout_containing(beside, live / "src") == live.resolve()

    def test_a_worktree_nested_in_a_worktree_is_named_over_the_one_holding_it(self, tmp_path):
        # `live` sorts before `nested` in git's registry, so the first match was `live`.
        root, live = _repo_with_worktree(tmp_path)
        nested = live / "nested"
        _git(["worktree", "add", str(nested), "-b", "wt-nested"], root)
        assert _hook_utils().sibling_checkout_containing(root, nested / "src") == nested.resolve()

    def test_the_base_named_is_matched_to_its_sibling_case_insensitively(self, tmp_path, monkeypatch):
        # A base list spelled in another case (a later edit folding Windows' `c:`
        # and `C:` together) still names the sibling; an exact compare went silent.
        root, live = _repo_with_worktree(tmp_path)
        other = _add_worktree(root, "other")
        hu = _hook_utils()
        bases = tuple(b.upper() for b in hu._checkout_bases(live))
        monkeypatch.setattr(hu, "_checkout_bases", lambda _root: bases)
        assert hu.sibling_checkout_containing(live, other / "src") == other.resolve()


class TestResolveInCheckout:
    """Every normaliser relativises against the DEEPEST checkout containing
    the target; the rejoin sites get that checkout back as the base."""

    def test_a_worktree_target_reads_like_the_root_target(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        hu = _hook_utils()
        assert hu.resolve_in_checkout(str(root / TARGET), root) == (root, TARGET)  # control
        assert hu.resolve_in_checkout(str(live / TARGET), root) == (live.resolve(), TARGET)
        assert hu.normalize_path(str(live / TARGET), root) == TARGET
        assert hu.normalize_path(str(live / "src" / "app.py"), root) == "src/app.py"

    def test_the_fs_free_and_bash_channels_agree(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        hu = _hook_utils()
        assert hu.normalize_path_str(str(live / TARGET), root) == TARGET
        assert hu.normalize_bash_path('"' + str(live / TARGET) + '"', root) == TARGET
        assert hu.resolve_bash_in_checkout(str(live / TARGET), root) == (live.resolve(), TARGET)

    def test_a_case_variant_spelling_under_the_worktree_relativises(self, tmp_path):
        # resolve() does not canonicalise case on APFS / NTFS, so the compare
        # is case-insensitive on every side (the Path Normalization rule).
        root, live = _repo_with_worktree(tmp_path)
        spelled = _posix(live.resolve()).upper() + "/" + TARGET
        assert _hook_utils().normalize_path(spelled, root) == TARGET

    def test_a_foreign_nested_repository_is_not_a_checkout(self, tmp_path):
        # A clone dropped into the tree carries its own tools/cc/; those are not
        # this repository's zones and stay root-relative (no over-reach).
        root = _repo(tmp_path)
        _foreign_clone(root)
        rel = "vendor/foreign/" + TARGET
        assert _hook_utils().normalize_path(str(root / rel), root) == rel

    def test_a_path_outside_every_checkout_keeps_its_spelling(self, tmp_path):
        root, _live = _repo_with_worktree(tmp_path)
        hu = _hook_utils()
        assert hu.resolve_in_checkout("/etc/passwd", root) == (root, "/etc/passwd")
        assert hu.normalize_path("/etc/passwd", root) == "/etc/passwd"


class TestWriteGuardInsideAWorktree:
    """write_guard driven as Claude Code runs it for a worktree session:
    ``CLAUDE_PROJECT_DIR`` at the root, the payload's ``cwd`` and every target
    inside the worktree."""

    def test_a_protected_write_inside_a_nested_worktree_is_denied(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _env(root)
        assert _decision(run_hook("write_guard.py", _write_payload(root / TARGET, live), env)) == "deny"  # control
        assert _decision(run_hook("write_guard.py", _write_payload(live / TARGET, live), env)) == "deny"
        assert_hook_allowed(run_hook("write_guard.py", _write_payload(live / "src" / "app.py", live), env))

    def test_a_protected_write_inside_a_worktree_beside_the_root_is_denied(self, tmp_path):
        root = _repo(tmp_path)
        beside = tmp_path / "beside"
        _git(["worktree", "add", str(beside), "-b", "wt-beside"], root)
        env = _env(root)
        assert _decision(run_hook("write_guard.py", _write_payload(beside / TARGET, beside), env)) == "deny"
        # a path under no checkout at all stays out of the harness's scope
        assert_hook_allowed(run_hook("write_guard.py", _write_payload(tmp_path / "elsewhere" / TARGET, beside), env))

    def test_a_bash_redirect_into_the_worktree_zone_is_denied(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _env(root)

        def bash(command: str):
            return run_hook("write_guard.py", {
                "hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": command}, "cwd": str(live),
            }, env)

        assert _decision(bash(f"echo x > {quoted(str(live / TARGET))}")) == "deny"
        assert_hook_allowed(bash(f"echo x > {quoted(str(live / 'src' / 'app.py'))}"))

    def test_mcp_writes_into_the_worktree_zone_are_denied_on_both_layers(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _env(root)
        canonical = {
            "hook_event_name": "PreToolUse", "tool_name": "mcp__filesystem__write_file",
            "tool_input": {"path": str(live / TARGET), "content": "x"}, "cwd": str(live),
        }
        nested = {
            "hook_event_name": "PreToolUse", "tool_name": "mcp__filesystem__write_files",
            "tool_input": {"files": [{"path": str(live / TARGET), "content": "x"}]}, "cwd": str(live),
        }
        assert _decision(run_hook("write_guard.py", canonical, env)) == "deny"  # Layer 1, resolve()
        assert _decision(run_hook("write_guard.py", nested, env)) == "deny"     # Layer 2, the FS-free leaf-walk

    @pytest.mark.skipif(os.name == "nt", reason="the inode backstop stands down without st_ino")
    def test_a_worktree_hardlink_alias_of_a_protected_file_is_still_denied(self, tmp_path):
        # The backstop stats the TARGET. With the relative path now keyed to
        # the worktree, a root-keyed stat would look at <root>/alias.py, find
        # nothing, and wave the write-through past -- the base must follow.
        # Denied before this change too (the path was root-relative then); the
        # pin is against the half-fix.
        root, live = _repo_with_worktree(tmp_path)
        alias = live / "alias.py"
        os.link(root / TARGET, alias)
        result = run_hook("write_guard.py", _write_payload(alias, live), _env(root))
        assert _decision(result) == "deny"
        assert "hardlink alias" in result.stdout

    @pytest.mark.skipif(os.name == "nt", reason="the inode backstop stands down without st_ino")
    @pytest.mark.parametrize("channel", ["Bash", "PowerShell", "mcp"])
    def test_the_hardlink_backstop_takes_the_checkout_on_every_channel(self, tmp_path, channel):
        # The Bash, PowerShell and MCP-canonical sites each pass the base; a
        # half-fix that drops one of them greens the Write case above alone
        # (the failure-mode review's mutation table -- and the PowerShell site
        # WAS the one dropped, the sixth of a five-site fix).
        root, live = _repo_with_worktree(tmp_path)
        alias = live / "alias.py"
        os.link(root / TARGET, alias)
        if channel == "Bash":
            payload = {"tool_name": "Bash", "tool_input": {"command": f"echo x > {quoted(str(alias))}"}}
        elif channel == "PowerShell":
            payload = {"tool_name": "PowerShell",
                       "tool_input": {"command": f"Set-Content -Path {quoted(str(alias), PS)} -Value x"}}
        else:
            payload = {"tool_name": "mcp__filesystem__write_file",
                       "tool_input": {"path": str(alias), "content": "x"}}
        payload.update({"hook_event_name": "PreToolUse", "cwd": str(live)})
        result = run_hook("write_guard.py", payload, _env(root))
        assert _decision(result) == "deny", result.stdout
        assert "hardlink alias" in result.stdout

    def test_the_deny_names_the_checkout_when_it_is_not_the_root(self, tmp_path):
        # Two different files produced byte-identical denials and audit rows
        # (`tools/cc/hooks/write_guard.py` in the root and in the worktree); an
        # operator shown the worktree's deny looked at the root and found
        # nothing wrong there.
        root, live = _repo_with_worktree(tmp_path)
        env = _env(root)
        at_root = run_hook("write_guard.py", _write_payload(root / TARGET, live), env)
        in_worktree = run_hook("write_guard.py", _write_payload(live / TARGET, live), env)
        assert _decision(at_root) == "deny" and "(in checkout" not in at_root.stdout
        assert f"{TARGET} (in checkout .claude/worktrees/live)" in in_worktree.stdout


class TestPlanGuardInsideAWorktree:
    def test_a_source_write_inside_the_worktree_needs_a_plan(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _env(root)
        # exempt under the worktree the way it is at the root (control)
        assert_hook_allowed(run_hook("plan_guard.py", _write_payload(live / "tests" / "test_app.py", live), env))
        assert _decision(run_hook("plan_guard.py", _write_payload(live / "src" / "app.py", live), env)) == "deny"
        (root / "cc").mkdir()
        (root / "cc" / "execution_plan.json").write_text(json.dumps(
            {"task": "t", "status": "in_progress", "steps": [{"description": "s"}]},
        ), encoding="utf-8")
        assert_hook_allowed(run_hook("plan_guard.py", _write_payload(live / "src" / "app.py", live), env))

    def test_an_mcp_write_inside_the_worktree_needs_a_plan(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        payload = {
            "hook_event_name": "PreToolUse", "tool_name": "mcp__filesystem__write_file",
            "tool_input": {"path": str(live / "src" / "app.py"), "content": "x"}, "cwd": str(live),
        }
        assert _decision(run_hook("plan_guard.py", payload, _env(root))) == "deny"


class TestSpeedBumpInsideAWorktree:
    """CP-GATEWEAKEN reads the pre-image of a full-file Write from disk. Keyed
    to the root it read the root's copy of a guard file -- a different commit
    -- and denied a harmless worktree edit (the failure-mode review drove it
    against the live win-walk worktree). Driven under the maintenance bypass,
    the session class the checkpoint exists for, so the verdict is the
    checkpoint's alone."""

    @staticmethod
    def _maintenance_env(root: Path) -> dict:
        return {"CLAUDE_PROJECT_DIR": str(root), "ESPALIER_MAINTENANCE_MODE": "1"}

    def test_a_worktree_edit_is_judged_against_the_worktree_copy(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        (root / TARGET).write_text("return deny(a)\nreturn deny(b)\nreturn deny(c)\n", encoding="utf-8")  # the root is ahead
        assert "deny(" not in (live / TARGET).read_text(encoding="utf-8")  # the worktree copy carries no deny path
        payload = _write_payload(live / TARGET, live)
        payload["tool_input"]["content"] = (live / TARGET).read_text(encoding="utf-8") + "# a note\n"
        assert_hook_allowed(run_hook("write_guard.py", payload, self._maintenance_env(root)))

    def test_a_real_weakening_in_the_worktree_still_fires(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        (live / TARGET).write_text("return deny(a)\n", encoding="utf-8")
        payload = _write_payload(live / TARGET, live)
        payload["tool_input"]["content"] = "pass\n"
        result = run_hook("write_guard.py", payload, self._maintenance_env(root))
        assert _decision(result) == "deny"
        assert "CP-GATEWEAKEN" in result.stdout


class TestSessionStartLineInsideAWorktree:
    """The one INFO line the SessionStart reporter prints from inside a nested
    repo carried the clause that the guards did not cover it. For a registered
    worktree that clause is retired with this change; a foreign nested repo,
    which the guards still do not govern, keeps it."""

    def test_a_registered_worktree_is_named_as_one_without_the_clause(self, tmp_path, capsys):
        root, live = _repo_with_worktree(tmp_path)
        _session_start()._warn_if_nested_repo_litter(root, cwd=live / "src")
        err = capsys.readouterr().err
        assert "[INFO] session cwd is inside registered worktree .claude/worktrees/live" in err
        assert _GUARD_CLAUSE not in err
        # the positive fact, not just the retired clause: a returning operator
        # holds the pre-DEF-743 model unless the line says otherwise
        assert "govern it like the root" in err
        assert "[WARN]" not in err

    def test_a_foreign_nested_repository_keeps_the_clause(self, tmp_path, capsys):
        root = _repo(tmp_path)
        foreign = _foreign_clone(root)
        _session_start()._warn_if_nested_repo_litter(root, cwd=foreign)
        err = capsys.readouterr().err
        assert "[INFO] session cwd is inside nested git repo vendor/foreign" in err
        assert _GUARD_CLAUSE in err

    def test_a_worktree_beside_the_root_gets_the_line_too(self, tmp_path, capsys):
        # Outside the root the nested-repo walk finds nothing, and the shape
        # docs/FAILURE_MODES.md recommends for a second instance was silent.
        root = _repo(tmp_path)
        beside = tmp_path / "beside"
        _git(["worktree", "add", str(beside), "-b", "wt-beside"], root)
        _session_start()._warn_if_nested_repo_litter(root, cwd=beside / "src")
        err = capsys.readouterr().err
        assert f"[INFO] session cwd is inside worktree {beside.resolve()} of this repository" in err
        assert "govern it like the root" in err

    def test_a_cwd_in_a_nested_worktree_root_names_no_other_checkout(self, tmp_path, capsys):
        # A worker seat: the root is the worktree, nested in the main checkout's
        # folder, and the line named the main checkout as the cwd's worktree.
        _root, live = _repo_with_worktree(tmp_path)
        _session_start()._warn_if_nested_repo_litter(live, cwd=live / "src")
        assert "session cwd is inside" not in capsys.readouterr().err

    def test_from_a_nested_worktree_root_a_cwd_in_another_names_that_one(self, tmp_path, capsys):
        root, live = _repo_with_worktree(tmp_path)
        other = _add_worktree(root, "other")
        _session_start()._warn_if_nested_repo_litter(live, cwd=other / "src")
        err = capsys.readouterr().err
        assert f"[INFO] session cwd is inside worktree {other.resolve()} of this repository" in err

    def test_from_a_worktree_root_the_main_checkout_is_named_as_the_main_checkout(self, tmp_path, capsys):
        # DEF-3025: a worker seat whose cwd moved into the main checkout read
        # that it worked in a worktree.
        root, live = _repo_with_worktree(tmp_path)
        _session_start()._warn_if_nested_repo_litter(live, cwd=root / "src")
        err = capsys.readouterr().err
        assert f"[INFO] session cwd is inside the main checkout {root.resolve()} of this repository" in err
        assert "inside worktree" not in err
        assert "govern it like the root" in err


class TestPostWriteCheckInsideAWorktree:
    def test_the_syntax_check_reads_the_worktree_copy(self, tmp_path):
        # The rejoin site: post_write_check reads `<base>/<rel>` back. Keyed to
        # the root it would read the root's valid copy and stay silent about
        # the broken file that was actually written.
        root, live = _repo_with_worktree(tmp_path)
        (live / TARGET).write_text("def (:\n", encoding="utf-8")
        compile((root / TARGET).read_text(encoding="utf-8"), str(root / TARGET), "exec")  # the root copy stays valid
        result = run_hook("post_write_check.py", {
            "hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(live / TARGET), "content": "def (:\n"}, "cwd": str(live),
        }, _env(root))
        assert result.returncode == 0
        assert "has a Python syntax error" in result.stderr

    def test_a_new_test_file_written_in_the_worktree_gets_the_advisory(self, tmp_path):
        # The reinject pointer rows asked `(root / rel).is_file()`: a file that
        # exists only in the worktree made the new-test-file advisory go silent.
        # Driven at the seam the reinject pins use -- the PostToolUse rows are
        # self-host-gated in the hook, so a scratch repo cannot carry them end
        # to end -- with the real `git ls-files`, asked of the worktree.
        root, live = _repo_with_worktree(tmp_path)
        new = live / "tests" / "test_new.py"
        new.write_text("def test_x():\n    pass\n", encoding="utf-8")
        reinject = _hook_module("_reinject")
        tool_input = {"file_path": str(new), "content": new.read_text(encoding="utf-8")}
        assert reinject._pointer_target(tool_input, root, reinject._TEST_FILE_RE) == (
            live.resolve(), "tests/test_new.py",
        )
        text = reinject._render_new_test_file("Write", tool_input, root)
        assert text is not None and "New test file `tests/test_new.py`" in text

    def test_a_test_file_written_by_bash_in_the_worktree_gets_the_advisory(self, tmp_path):
        # The Bash bridge: existence, the index and the synthesized payload's
        # path all belong to the checkout the file sits in.
        root, live = _repo_with_worktree(tmp_path)
        new = live / "tests" / "test_new2.py"
        new.write_text("def test_x():\n    pass\n", encoding="utf-8")
        pwc = _hook_module("post_write_check")
        out = pwc._bash_derived_payloads({"command": f"echo x > {quoted(str(new))}"}, root, already=0)
        assert "New test file `tests/test_new2.py`" in "\n".join(out), out

    def test_the_prune_takes_the_checkout_and_the_spot_check_stays_on_the_root(self, tmp_path, monkeypatch):
        # The seam the subprocess drive cannot see: the memory auto-prune runs on
        # the checkout whose ESPALIER_MEMORY.md was written, and the integrity
        # spot-check -- about the root's deployed surface -- does not run for a
        # worktree write at all.
        root, live = _repo_with_worktree(tmp_path)
        (live / "ESPALIER_MEMORY.md").write_text("# memory\n", encoding="utf-8")
        pwc = _hook_module("post_write_check")
        pruned: list = []
        checked: list = []
        monkeypatch.setattr(pwc, "_maybe_autoprune_memory", lambda repo_root, rel: pruned.append((repo_root, rel)))
        monkeypatch.setattr(pwc, "_integrity_spot_check", lambda repo_root, rel: checked.append((repo_root, rel)))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)
        payload = json.dumps({
            "hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(live / "ESPALIER_MEMORY.md"), "content": "# memory\n"},
        })
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode("utf-8")), encoding="utf-8"))
        assert pwc._run_main() == 0
        assert pruned == [(live.resolve(), "ESPALIER_MEMORY.md")]
        assert checked == []


# The lists of a repository's checkouts read off the disk: the hooks' reader
# and checkout_sync's wrapper of it, which lists the root first.
_SIBLING_LISTS = ("sibling_checkouts", "_sibling_places")

# Every reader of those lists under tools/cc, with the rule it places a path
# by. A worktree nested in the main checkout's folder is held by both, so the
# first checkout holding a path is the wrong answer (DEF-5068, DEF-3024).
_SIBLING_READERS = {
    ("tools/cc/checkout_sync.py", "_sibling_places"): "filtered and handed to sessions_in_checkout",
    ("tools/cc/checkout_sync.py", "sessions_in_checkout"): "checkout_of over the places",
    ("tools/cc/checkout_sync.py", "occupancy"): "the main checkout picked by its .git folder, never by position",
    ("tools/cc/checkout_sync.py", "pid_checkout"): "a killed git list's stand-in, handed to cwd_checkout",
    ("tools/cc/hooks/_hook_utils.py", "_checkout_bases"): "sorted longest first for containing_checkout",
    ("tools/cc/hooks/_hook_utils.py", "sibling_checkout_containing"): "equal to containing_checkout's hit",
    ("tools/cc/hooks/_hook_utils.py", "is_sibling_checkout"): "identity by inode, no containment",
    ("tools/cc/hooks/_speedbump.py", "<module>"): "binds the reader with a degrade, places nothing",
    ("tools/cc/hooks/_speedbump.py", "_kill_reading"): "handed to checkout_sync.cwd_checkout",
    ("tools/cc/hooks/_speedbump.py", "_checkout_label"): "the main checkout picked by its .git folder, never by position",
    ("tools/cc/hooks/_speedbump.py", "_shell_reading"): "spellings the gate searches the text for; each path placed by containing_checkout",
    ("tools/cc/hooks/session_start.py", "_loose_processes_line"): "handed to checkout_sync.pid_checkout",
}


def _sibling_checkout_readers(tree_root: Path) -> set[tuple[str, str]]:
    """Every (file, enclosing function) under ``tree_root/tools/cc`` naming a
    list in ``_SIBLING_LISTS``: a call by name or attribute, getattr's
    string, or an import of it (an alias is caught where it is imported)."""
    found: set[tuple[str, str]] = set()

    def walk(node: ast.AST, rel: str, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, rel, child.name)
                continue
            if ((isinstance(child, ast.Name) and child.id in _SIBLING_LISTS)
                    or (isinstance(child, ast.Attribute) and child.attr in _SIBLING_LISTS)
                    or (isinstance(child, ast.Constant) and child.value in _SIBLING_LISTS)
                    or (isinstance(child, ast.alias) and child.name in _SIBLING_LISTS)):
                found.add((rel, owner))
            walk(child, rel, owner)

    for path in sorted((tree_root / "tools" / "cc").rglob("*.py")):
        walk(ast.parse(path.read_text(encoding="utf-8")), path.relative_to(tree_root).as_posix(), "<module>")
    return found


class TestEverySiblingReaderIsNamedWithItsRule:
    """No contract stopped a new first-match loop over sibling_checkouts, the
    shape DEF-5068 fixed and DEF-3024 found again in checkout_sync: every
    reader is named here with the rule it places by, so a new one is read
    before it lands. It pins the roster of readers, not their bodies: a
    second loop inside a named reader is the reviewer's to read."""

    def test_every_reader_is_named_with_its_rule(self):
        root = HOOKS_DIR.parent.parent.parent
        assert "def sibling_checkouts(" in (HOOKS_DIR / "_hook_utils.py").read_text(encoding="utf-8"), (
            "sibling_checkouts moved or was renamed: point _SIBLING_LISTS at its new name, never empty the census")
        found = _sibling_checkout_readers(root)
        assert found, "the scan found no reader at all: the scan is broken, not the tree clean"
        new = sorted(found - set(_SIBLING_READERS))
        gone = sorted(set(_SIBLING_READERS) - found)
        assert not new and not gone, (
            f"new readers: {new}; named readers that no longer read a list: {gone}. Place a path by the "
            "deepest checkout holding it (checkout_sync.checkout_of, or _hook_utils.containing_checkout), "
            "never the first that holds it, then name each new reader in _SIBLING_READERS with its rule; a "
            "reader renamed or moved is one of each, its rule carried over")

    def test_a_first_match_loop_is_named_by_the_scan(self, tmp_path):
        planted = tmp_path / "tools" / "cc" / "hooks" / "_planted.py"
        planted.parent.mkdir(parents=True)
        planted.write_text(
            "from _hook_utils import sibling_checkouts\n\n\n"
            "def first_holder(root, path):\n"
            "    for c in sibling_checkouts(root):\n"
            "        if str(path).startswith(str(c)):\n"
            "            return c\n\n\n"
            "def by_name(h, root):\n"
            "    return getattr(h, 'sibling_checkouts')(root)\n",
            encoding="utf-8")
        aliased = tmp_path / "tools" / "cc" / "_aliased.py"
        aliased.write_text(
            "from checkout_sync import _sibling_places as places\n\n\n"
            "def first_place(root, path):\n"
            "    return next(p for p in places(root) if str(path).startswith(str(p)))\n",
            encoding="utf-8")
        assert _sibling_checkout_readers(tmp_path) == {
            ("tools/cc/hooks/_planted.py", "<module>"), ("tools/cc/hooks/_planted.py", "first_holder"),
            ("tools/cc/hooks/_planted.py", "by_name"), ("tools/cc/_aliased.py", "<module>")}


# -- DEF-3106: a file tool's write into another checkout of this clone --------


def _seat_env(project: Path, *, maintenance: bool = False) -> dict:
    """``CLAUDE_PROJECT_DIR`` at the session's project dir (a worktree seat
    launches in its worktree; a session that entered a worktree keeps the
    root), and the maintenance switch as the row asks."""
    return {"CLAUDE_PROJECT_DIR": str(project), "ESPALIER_MAINTENANCE_MODE": "1" if maintenance else None}


def _edit_payload(target: Path, cwd: Path | None, *, tool: str = "Edit") -> dict:
    payload: dict = {"hook_event_name": "PreToolUse", "tool_name": tool}
    if tool == "NotebookEdit":
        payload["tool_input"] = {"notebook_path": str(target), "new_source": "x"}
    elif tool == "Write":
        payload["tool_input"] = {"file_path": str(target), "content": "x"}
    else:
        payload["tool_input"] = {"file_path": str(target), "old_string": "x = 1", "new_string": "x = 2"}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def _bumped(result) -> str:
    """The reason of a CP-OTHER-CHECKOUT fire, failing on any other answer."""
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), f"the write passed with no word: no checkpoint fired ({result.stderr[-300:]})"
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", out
    reason = out["permissionDecisionReason"]
    assert "[CP-OTHER-CHECKOUT]" in reason, reason
    return reason


class TestAWriteIntoAnotherCheckoutIsBumped:
    """CP-OTHER-CHECKOUT, through the real hook on real worktree layouts: a
    Write, Edit or NotebookEdit into a checkout of this clone other than the
    session's own is refused once per file per session, naming both checkouts
    and the session's own copy, and passes on its re-issue. The session's
    checkout is the one holding the payload's cwd (air's 16ab70 (1)); the
    worktree seats' slips it answers (win-2's into win's tree, 2026-11-18; five
    on the Air) all dropped ``.claude/worktrees/<name>`` from the path."""

    def test_a_worktree_seat_writing_the_main_checkouts_copy_is_bumped_once(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        slip = _edit_payload(root / "src" / "app.py", live)
        reason = _bumped(run_hook("write_guard.py", slip, _seat_env(live)))
        assert "writes into the main checkout" in reason
        assert "not .claude/worktrees/live where this session works" in reason
        # the session's own copy, whole: a tail cut read as a relative path and
        # the agent wrote to one it made up (the 2026-11-21 drive, 1 run of 3)
        own = _posix((live / "src" / "app.py").resolve())
        assert f"this session's copy is {own}: use that one unless the other tree is meant" in reason
        assert_hook_allowed(run_hook("write_guard.py", slip, _seat_env(live)))   # the re-issue passes
        assert (root / "src" / "app.py").read_text(encoding="utf-8") == "x = 1\n"

    def test_the_sessions_own_tree_is_silent(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", live), _seat_env(live)))
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", root), _seat_env(root)))
        # a path under no checkout of this clone is out of scope
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(tmp_path / "notes.md", live, tool="Write"),
                                     _seat_env(live)))

    def test_a_sibling_worktree_is_bumped(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        other = _add_worktree(root, "other")
        reason = _bumped(run_hook("write_guard.py", _edit_payload(other / "src" / "app.py", live), _seat_env(live)))
        assert "writes into .claude/worktrees/other" in reason

    def test_the_main_checkout_writing_a_nested_worktree_is_bumped(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        reason = _bumped(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", root), _seat_env(root)))
        assert "writes into .claude/worktrees/live" in reason and "not the main checkout" in reason
        # The same payload is also a declared limit's: a session working in that
        # worktree (entered, or a main seat's agent) whose shell moved back into
        # main sends exactly this, so it reads main as its own and is bumped here.

    def test_a_session_whose_shell_moved_into_a_sibling_reads_it_as_its_own(self, tmp_path):
        # Declared limit (the session's checkout is cwd's): a worktree seat whose
        # shell moved into another seat's worktree writes there unsaid and is
        # bumped writing its own tree. Pinned so a refactor flips it on purpose.
        root, live = _repo_with_worktree(tmp_path)
        other = _add_worktree(root, "other")
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(other / "src" / "app.py", other), _seat_env(live)))
        reason = _bumped(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", other), _seat_env(live)))
        assert "writes into .claude/worktrees/live" in reason and "not .claude/worktrees/other" in reason

    def test_a_write_under_a_checkouts_git_folder_is_silent(self, tmp_path):
        # The common dir every checkout shares (`.git/info/exclude` is each
        # worktree's too) and a worktree's link file are git's, no seat's tree;
        # a bump there named a `<own>/.git/...` copy that does not exist.
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(root / ".git" / "info" / "exclude", live, tool="Write"), env))
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(live / ".git", root, tool="Write"), _seat_env(root)))
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", live), env))   # control
        # a name that only starts like it is a tree file, and still bumped
        _bumped(run_hook("write_guard.py", _edit_payload(root / ".github" / "x.yml", live, tool="Write"), env))
        _bumped(run_hook("write_guard.py", _edit_payload(root / ".gitignore", live, tool="Write"), env))

    def test_a_session_that_entered_a_worktree_keeps_its_tree_and_bumps_a_dropped_segment(self, tmp_path):
        # CLAUDE_PROJECT_DIR stays at the root after a session enters a worktree
        # (docs/external/cc-worktrees.md): read alone it would bump the tree the
        # session now works in, which is the mutant this row kills.
        root, live = _repo_with_worktree(tmp_path)
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", live), _seat_env(root)))
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", live), _seat_env(root)))

    def test_an_agent_worktree_writes_its_own_tree_silently(self, tmp_path):
        # An `isolation: worktree` agent spawned by a worktree seat: the seat's
        # project dir, the agent's cwd in a tree of its own beside the seat's
        # (40 such writes in the Air's transcripts, none a slip).
        root, live = _repo_with_worktree(tmp_path)
        agent = _add_worktree(root, "agent-a1b2c3")
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(agent / "src" / "app.py", agent), _seat_env(live)))
        _bumped(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", agent), _seat_env(live)))

    def test_a_worktree_seat_whose_shell_moved_into_main_keeps_its_own_tree(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", root), _seat_env(live)))
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", root), _seat_env(live)))

    def test_a_cwd_in_no_checkout_reads_the_project_dirs(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", elsewhere), _seat_env(live)))
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", elsewhere), _seat_env(live)))
        # a payload that carries no cwd reads the same way
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(live / "src" / "app.py", None), _seat_env(live)))

    def test_a_clone_nested_in_the_other_checkout_is_silent(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        foreign = _foreign_clone(root)
        (foreign / "x.py").write_text("x = 1\n", encoding="utf-8")
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(foreign / "x.py", live), _seat_env(live)))
        # control: the same folder with no repository of its own is the main checkout's tree
        shutil.rmtree(foreign / ".git")
        _bumped(run_hook("write_guard.py", _edit_payload(foreign / "x.py", live), _seat_env(live)))

    def test_it_fires_under_maintenance_mode(self, tmp_path):
        # Every seat on the Air runs maintenance mode, which skips the zone
        # check; a bump fires there, which is why this is a bump.
        root, live = _repo_with_worktree(tmp_path)
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", live), _seat_env(live, maintenance=True)))

    def test_a_second_file_is_bumped_again_and_a_case_variant_of_the_first_is_not(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        first = _edit_payload(root / "src" / "app.py", live)
        _bumped(run_hook("write_guard.py", first, env))
        assert_hook_allowed(run_hook("write_guard.py", first, env))
        _bumped(run_hook("write_guard.py", _edit_payload(root / "tests" / "test_app.py", live), env))
        variant = _edit_payload(root / "SRC" / "App.py", live)
        assert_hook_allowed(run_hook("write_guard.py", variant, env))

    def test_a_notebook_edit_is_read_by_its_notebook_path(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        reason = _bumped(run_hook("write_guard.py", _edit_payload(root / "n.ipynb", live, tool="NotebookEdit"),
                                  _seat_env(live)))
        assert "this NotebookEdit writes into the main checkout" in reason

    def test_a_cross_checkout_edit_that_weakens_a_guard_file_meets_both_nudges_in_turn(self, tmp_path):
        # Registered ahead of CP-GATEWEAKEN (air's 16ab70 (5)): the wrong tree
        # is said first, the weakening on the re-issue, then the edit passes.
        # Maintenance mode, as a self-edit session runs, so no zone deny answers first.
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live, maintenance=True)
        weaken = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(live),
                  "tool_input": {"file_path": str(root / TARGET), "old_string": "return deny(r)", "new_string": "pass"}}
        _bumped(run_hook("write_guard.py", weaken, env))
        second = json.loads(run_hook("write_guard.py", weaken, env).stdout)["hookSpecificOutput"]
        assert second["permissionDecision"] == "deny" and "[CP-GATEWEAKEN]" in second["permissionDecisionReason"]
        assert_hook_allowed(run_hook("write_guard.py", weaken, env))


class TestTheOtherCheckoutRegistryRow:
    """The checkpoint's settings, each load-bearing (docs/SHARP_EDGES.md, the
    keystone speed-bump entry): cap-exempt, keyed per file, its reason held to
    512 bytes at its caps."""

    def test_it_fires_with_the_session_cap_spent(self, tmp_path):
        speedbump = _hook_module("_speedbump")
        root, live = _repo_with_worktree(tmp_path)
        canaries = tuple(speedbump.SpeedBump(id=f"CP-CANARY-{i}", predicate=lambda *a: True, body="canary")
                         for i in range(speedbump.SPEEDBUMP_SESSION_CAP))
        for _ in range(speedbump.SPEEDBUMP_SESSION_CAP):
            speedbump.check("Bash", {"command": "x"}, live, bumps=canaries)
        fired = speedbump.check_fired("Edit", _edit_payload(root / "src" / "app.py", live)["tool_input"], live,
                                      bumps=(speedbump.CP_OTHER_CHECKOUT,), cwd=live)
        assert fired is not None and fired[0] == "CP-OTHER-CHECKOUT"

    def test_the_row_sits_ahead_of_the_gate_weaken_nudge_and_keys_per_file(self):
        speedbump = _hook_module("_speedbump")
        ids = [b.id for b in speedbump.SPEEDBUMPS]
        assert ids.index("CP-OTHER-CHECKOUT") + 1 == ids.index("CP-GATEWEAKEN")
        bump = speedbump.CP_OTHER_CHECKOUT
        assert bump.cap_exempt is True and bump.fires_in_maintenance is True
        one = bump.flag_key("Edit", {"file_path": "/r/src/__init__.py"})
        assert one != bump.flag_key("Edit", {"file_path": "/r/tests/__init__.py"})   # a bare-name key would collide
        assert one == bump.flag_key("Write", {"file_path": "/R/SRC/__init__.py"})

    def test_the_reason_stays_within_512_bytes_at_its_caps(self, monkeypatch, tmp_path):
        speedbump = _hook_module("_speedbump")
        monkeypatch.setattr(speedbump, "_other_checkout_hit", lambda *a, **k: ("/" + "a" * 300, "/" + "b" * 300, "c" * 400))
        body = speedbump._other_checkout_body("NotebookEdit", {}, tmp_path, None)
        reason = speedbump._REASON_TEMPLATE.format(id="CP-OTHER-CHECKOUT", body=body)
        assert len(reason.encode("utf-8")) <= 512, len(reason.encode("utf-8"))
        # a name past ASCII is measured as the one byte it is sent as
        accented = speedbump._other_checkout_text("NotebookEdit", "é" * 300, "é" * 300, "/é" * 300)
        sent = speedbump._REASON_TEMPLATE.format(id="CP-OTHER-CHECKOUT", body=accented)
        assert len(sent.encode("utf-8")) <= 512, len(sent.encode("utf-8"))

    def test_the_sessions_own_copy_is_whole_and_the_names_are_cut_first(self):
        # The own copy is what the agent acts on: whole at a seat's length (this
        # clone's seats run 67 characters of checkout plus at most 84 of path),
        # the checkouts' names cut to their floor before it is, and past even
        # that its tail is kept, the part that names the checkout and the file.
        speedbump = _hook_module("_speedbump")
        text, template = speedbump._other_checkout_text, speedbump._REASON_TEMPLATE

        def sent(*args: str) -> str:
            reason = template.format(id="CP-OTHER-CHECKOUT", body=text(*args))
            assert len(reason.encode("utf-8")) <= 512, len(reason.encode("utf-8"))
            return reason

        seat = "/Users/someone/Developer/espalier-harness/.claude/worktrees/work/" + "d" * 84
        assert f"copy is {seat}: use" in sent("Edit", "the main checkout", ".claude/worktrees/work", seat)
        long_name, longer_seat = "n" * 60, "/" + "e" * 160
        reason = sent("NotebookEdit", long_name, long_name, longer_seat)
        assert f"copy is {longer_seat}: use" in reason and long_name not in reason
        overlong = "/" + "f" * 300 + "/.claude/worktrees/work/src/app.py"
        reason = sent("NotebookEdit", long_name, long_name, overlong)
        # the tail fills the room the floors leave, the reason at its cap, never the old 120 cut
        assert "copy is ..." in reason and f"{overlong[-160:]}: use" in reason
        assert len(reason.encode("utf-8")) == 512

    def test_a_helper_without_the_checkout_reader_leaves_it_silent(self, monkeypatch, tmp_path):
        # A kept, older `_hook_utils.py` that predates `containing_checkout`
        # (DEF-1176): the checkpoint passes the write with no word and spends
        # no flag, as before it existed, never a raise into the hook.
        speedbump = _hook_module("_speedbump")
        root, live = _repo_with_worktree(tmp_path)
        monkeypatch.setattr(speedbump, "containing_checkout", None)
        slip = _edit_payload(root / "src" / "app.py", live)["tool_input"]
        assert speedbump.check_fired("Edit", slip, live, bumps=(speedbump.CP_OTHER_CHECKOUT,), cwd=live) is None
        state = live / speedbump.STATE_DIR
        assert not (state.is_dir() and any(state.glob("speedbump_*")))

    def test_a_checkout_that_cannot_be_resolved_is_named_by_its_path(self, monkeypatch, tmp_path):
        # The name read for the reminder resolves every checkout of the clone;
        # one that raises there names the checkout by its path, and the fire
        # keeps its per-fire text (an unguarded resolve fell to the static body).
        speedbump = _hook_module("_speedbump")
        root, live = _repo_with_worktree(tmp_path)

        class _Unresolvable(type(Path())):
            def resolve(self, strict=False):
                raise OSError("unresolvable")

        monkeypatch.setattr(speedbump, "sibling_checkouts", lambda _root: (_Unresolvable(root),))
        body = speedbump._other_checkout_body("Edit", _edit_payload(root / "src" / "app.py", live)["tool_input"], live, live)
        assert body != speedbump.CP_OTHER_CHECKOUT.body
        assert body.startswith("this Edit writes into ") and "the main checkout" not in body


# -- DEF-5135: a shell write into another checkout of this clone --------------


def _shell_payload(command: str, cwd: Path | None, *, tool: str = "Bash") -> dict:
    payload: dict = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


def _in(path: Path, shell: str = "sh") -> str:
    """A path as a shell row spells it, quoted where it holds a space."""
    return quoted(str(path), PS) if shell == PS else quoted(str(path))


class TestAShellWriteIntoAnotherCheckoutIsBumped:
    """CP-OTHER-CHECKOUT's shell arm (DEF-5135), through the real hook on real
    worktree layouts: a Bash or PowerShell call that writes, removes or moves
    a file in a checkout of this clone other than the session's is refused
    once per file, naming both checkouts and the session's own copy, and passes
    on its re-issue. Read by the readers write_guard's zone twins take, over
    the directories the command runs in, with the session's checkout taken at
    each of them by DEF-3106's rule."""

    def test_a_redirect_into_the_main_checkout_from_a_worktree_seat_is_bumped_once(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        slip = _shell_payload(f"echo z >> {_in(root / 'src' / 'app.py')}", live)
        reason = _bumped(run_hook("write_guard.py", slip, _seat_env(live)))
        assert "this Bash writes into the main checkout" in reason
        assert "not .claude/worktrees/live where this session works" in reason
        own = _posix((live / "src" / "app.py").resolve())
        assert f"this session's copy is {own}: use that one unless the other tree is meant" in reason
        assert_hook_allowed(run_hook("write_guard.py", slip, _seat_env(live)))   # the re-issue passes

    @pytest.mark.parametrize("form", ["sed", "cp", "tee", "heredoc"])
    def test_each_write_form_the_extractor_reads_is_bumped(self, tmp_path, form):
        root, live = _repo_with_worktree(tmp_path)
        there = _in(root / "src" / "app.py")
        command = {"sed": f"sed -i 's/1/2/' {there}", "cp": f"cp src/app.py {there}",
                   "tee": f"echo z | tee -a {there}", "heredoc": f"cat > {there} <<'EOF'\nx = 2\nEOF"}[form]
        assert "this Bash writes into the main checkout" in _bumped(
            run_hook("write_guard.py", _shell_payload(command, live), _seat_env(live)))

    @pytest.mark.parametrize("form", ["rm", "mv"])
    def test_a_remove_or_a_move_of_the_other_checkouts_file_is_bumped(self, tmp_path, form):
        root, live = _repo_with_worktree(tmp_path)
        there = _in(root / "src" / "app.py")
        command = f"rm {there}" if form == "rm" else f"mv {there} {_in(tmp_path / 'app.py')}"
        reason = _bumped(run_hook("write_guard.py", _shell_payload(command, live), _seat_env(live)))
        assert "this Bash removes or moves a file in the main checkout" in reason

    def test_the_sessions_own_tree_and_ordinary_calls_are_silent(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        for command in (f"echo z >> {_in(live / 'src' / 'app.py')}", "echo z >> src/app.py",
                        "git log origin/main..HEAD > /dev/null", f"echo z > {_in(tmp_path / 'notes.md')}",
                        f"git -C {_in(root)} status", f"ls {_in(root / 'src')}"):
            assert_hook_allowed(run_hook("write_guard.py", _shell_payload(command, live), env))
        # the main seat's own tree, too
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload("echo z >> src/app.py", root), _seat_env(root)))

    def test_a_cd_into_main_then_a_relative_write_is_bumped(self, tmp_path):
        # `cd X && write` reads as a cd call, then the write: the worktree seat
        # whose shell moved into main keeps its own tree (air's 16ab70 (1)).
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        _bumped(run_hook("write_guard.py", _shell_payload(f"cd {_in(root)} && echo z > src/app.py", live), env))
        _bumped(run_hook("write_guard.py", _shell_payload("cd ../../.. && echo z > tests/test_app.py", live), env))

    def test_a_shell_standing_in_main_writing_a_relative_path_is_bumped(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        _bumped(run_hook("write_guard.py", _shell_payload("echo z >> src/app.py", root), env))
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(
            f"echo z >> {_in(live / 'tests' / 'test_app.py')}", root), env))

    def test_a_cd_into_a_sibling_reads_it_as_the_sessions_own(self, tmp_path):
        # Declared limit, the file arm's: a shell moved into another seat's
        # worktree reads that tree as its own, and the seat's own tree as another.
        root, live = _repo_with_worktree(tmp_path)
        other = _add_worktree(root, "other")
        env = _seat_env(live)
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(f"cd {_in(other)} && echo z > src/app.py", live), env))
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            f"cd {_in(other)} && echo z > {_in(live / 'src' / 'app.py')}", live), env))
        assert "writes into .claude/worktrees/live" in reason and "not .claude/worktrees/other" in reason

    def test_a_home_step_into_the_other_checkout_is_bumped(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = {**_seat_env(live), "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
        _bumped(run_hook("write_guard.py", _shell_payload("echo z > ~/repo/src/app.py", live), env))

    def test_a_write_under_git_and_into_a_nested_clone_is_silent(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(
            f"echo z >> {_in(root / '.git' / 'info' / 'exclude')}", live), env))
        foreign = _foreign_clone(root)
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(f"echo z > {_in(foreign / 'x.py')}", live), env))
        shutil.rmtree(foreign / ".git")   # control: no repository of its own, the main checkout's tree
        _bumped(run_hook("write_guard.py", _shell_payload(f"echo z > {_in(foreign / 'x.py')}", live), env))

    def test_the_main_seat_writing_a_worktree_is_bumped(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            f"echo z >> {_in(live / 'src' / 'app.py')}", root), _seat_env(root)))
        assert "this Bash writes into .claude/worktrees/live" in reason and "not the main checkout" in reason

    def test_a_duplicated_descriptor_or_a_null_device_names_no_file(self, tmp_path):
        # The readers return `1` for `2>&1`: four of Task 0's 107 placed calls
        # were that, from a shell standing in main (the failure-mode review).
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        for command in ("git status 2>&1 | head -3", "ls >&2", "make 2>&- && echo ok", "cmd 2> /dev/null"):
            assert_hook_allowed(run_hook("write_guard.py", _shell_payload(command, root), env))
        for command in ("Get-Item x > $null", "Get-Item x 2>$null", "dir > NUL"):
            assert_hook_allowed(run_hook("write_guard.py", _shell_payload(command, root, tool="PowerShell"), env))
        # control: a file really named 1 is a file
        _bumped(run_hook("write_guard.py", _shell_payload("echo z > 1", root), env))

    def test_every_file_a_call_writes_there_keys_the_fire(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", live), env))
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", live), env))
        # a told file and a new one in one call: told again, the count named
        both = f"sed -i 's/1/2/' {_in(root / 'src' / 'app.py')} {_in(root / 'tests' / 'test_app.py')}"
        assert "this Bash writes 2 files into the main checkout" in _bumped(
            run_hook("write_guard.py", _shell_payload(both, live), env))
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(both, live), env))   # its re-issue passes

    def test_a_link_in_the_sessions_tree_is_removed_not_what_it_points_at(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        (live / "venvlink").symlink_to(root / "src", target_is_directory=True)
        env = _seat_env(live)
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(
            f"rm -f venvlink && ln -s {_in(root / 'src')} venvlink", live), env))
        # control: a file in the folder it points at, named, is main's
        assert "removes or moves a file in the main checkout" in _bumped(run_hook(
            "write_guard.py", _shell_payload(f"rm -f {_in(root / 'src' / 'app.py')}", live), env))

    def test_the_project_dir_variable_is_read_from_the_project_dir(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        # a worktree seat whose shell moved into main writes its own tree through it
        seat = _seat_env(live)
        for command in (f"cd {_in(root)} && echo z > $CLAUDE_PROJECT_DIR/src/app.py",
                        f"cd {_in(root)} && echo z > ${{CLAUDE_PROJECT_DIR}}/src/app.py"):
            assert_hook_allowed(run_hook("write_guard.py", _shell_payload(command, live), seat))
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(
            f'Set-Location {_in(root, PS)}; Set-Content -Path "$($env:CLAUDE_PROJECT_DIR)/src/app.py" -Value z',
            live, tool="PowerShell"), seat))
        # a session that entered a worktree (project dir main, cwd the worktree) writes main through it
        assert "writes into the main checkout" in _bumped(run_hook(
            "write_guard.py", _shell_payload("echo z > $CLAUDE_PROJECT_DIR/src/app.py", live), _seat_env(root)))

    def test_a_folder_in_the_worktrees_folder_that_no_checkout_holds_is_silent(self, tmp_path):
        # 9632e9 (A): Claude Code's worktree folder holds a reviewer's snapshot
        # clone or a subagent's scratch (102 of Task 0's 107 placed calls), no
        # seat's tree; a registered worktree there is still its own checkout.
        root, live = _repo_with_worktree(tmp_path)
        (root / ".claude" / "worktrees" / "scratch").mkdir()
        (root / "scratch").mkdir()
        env = _seat_env(live)
        for command in ("echo z > ../scratch/out.txt", f"echo z > {_in(root / '.claude' / 'worktrees' / 'scratch' / 'o.txt')}",
                        "mkdir -p ../gone/x && echo z > ../gone/x/out.txt"):
            assert_hook_allowed(run_hook("write_guard.py", _shell_payload(command, live), env))
        assert_hook_allowed(run_hook("write_guard.py", _edit_payload(
            root / ".claude" / "worktrees" / "scratch" / "notes.md", live, tool="Write"), env))
        # controls: the same folder name in main's own tree, and a registered sibling, are bumped
        _bumped(run_hook("write_guard.py", _shell_payload(f"echo z > {_in(root / 'scratch' / 'out.txt')}", live), env))
        _bumped(run_hook("write_guard.py", _edit_payload(root / "scratch" / "notes.md", live, tool="Write"), env))
        other = _add_worktree(root, "other")
        assert "writes into .claude/worktrees/other" in _bumped(run_hook(
            "write_guard.py", _shell_payload("echo z > ../other/src/app.py", live), env))
        # the main checkout's folder alone: a linked worktree's own is that seat's tree
        (other / ".claude" / "worktrees" / "scratch").mkdir(parents=True)
        assert "writes into .claude/worktrees/other" in _bumped(run_hook(
            "write_guard.py", _shell_payload("echo z > ../other/.claude/worktrees/scratch/o.txt", live), env))

    def test_the_main_seat_writing_a_nested_worktree_by_its_relative_path_is_bumped(self, tmp_path):
        # air's 32b8d3 (2): the path from main's root names no other checkout's
        # root, so the gate opens on the nested checkout's relative spelling.
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(root)
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            "echo z >> .claude/worktrees/live/src/app.py", root), env))
        assert "this Bash writes into .claude/worktrees/live" in reason and "not the main checkout" in reason
        # from a folder inside main, by a tail of two parts or more
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            "echo z >> worktrees/live/tests/test_app.py", root / ".claude"), env))
        assert "this Bash writes into .claude/worktrees/live" in reason

    def test_the_main_seat_cd_into_a_nested_worktree_reads_it_as_its_own(self, tmp_path):
        # Declared limits. A cd into the worktree reads as a cd call, then the
        # write, and a shell moved into a worktree reads that tree as its own
        # (the file arm's limit); a cd that leaves only the worktree's last
        # part to name never opens the gate (its docstring's, since a one-part
        # tail would open it on every `2>&1` where a worktree is named `2`).
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(root)
        for command in ("cd .claude/worktrees/live && echo z >> src/app.py",
                        "cd .claude/worktrees && echo z >> live/src/app.py"):
            assert_hook_allowed(run_hook("write_guard.py", _shell_payload(command, root), env))
        # control: the same cd, then a write into main's own tree, is a write into main
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            f"cd .claude/worktrees/live && echo z >> {_in(root / 'src' / 'app.py')}", root), env))
        assert "writes into the main checkout" in reason and "not .claude/worktrees/live" in reason

    def test_it_keys_per_file_and_shares_the_key_with_the_file_tools(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        _bumped(run_hook("write_guard.py", _edit_payload(root / "src" / "app.py", live), env))
        # the shell write of a file the session was already told about passes
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(f"echo z >> {_in(root / 'src' / 'app.py')}", live), env))
        _bumped(run_hook("write_guard.py", _shell_payload(f"echo z >> {_in(root / 'tests' / 'test_app.py')}", live), env))

    def test_it_fires_under_maintenance_mode(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        _bumped(run_hook("write_guard.py", _shell_payload(f"echo z >> {_in(root / 'src' / 'app.py')}", live),
                         _seat_env(live, maintenance=True)))

    def test_the_powershell_carrier_is_read_the_same_way(self, tmp_path):
        root, live = _repo_with_worktree(tmp_path)
        env = _seat_env(live)
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            f"Set-Content -Path {_in(root / 'src' / 'app.py', PS)} -Value z", live, tool="PowerShell"), env))
        assert "this PowerShell writes into the main checkout" in reason
        reason = _bumped(run_hook("write_guard.py", _shell_payload(
            f"Remove-Item {_in(root / 'tests' / 'test_app.py', PS)}", live, tool="PowerShell"), env))
        assert "this PowerShell removes or moves a file in the main checkout" in reason
        assert_hook_allowed(run_hook("write_guard.py", _shell_payload(
            f"Set-Content -Path {_in(live / 'src' / 'app.py', PS)} -Value z", live, tool="PowerShell"), env))


class TestTheShellArmsGate:
    """The string gate ahead of the shell readers is a superset of what they
    reach, and an ordinary call never pays for the readers: maintenance mode
    skips the zone check, so on a seat that runs it no Bash call read the
    extractor before this arm."""

    WT, MAIN = "/r/.claude/worktrees/live", "/r"

    def _gate(self, command: str, *, ours: str = WT, others: tuple = (MAIN,), elsewhere: bool = False) -> bool:
        speedbump = _hook_module("_speedbump")
        return speedbump._shell_may_reach_another_checkout(command, list(others), ours, elsewhere)

    @pytest.mark.parametrize("command", [
        "echo z > /r/.claude/worktrees/live/src/a", "git log origin/main..HEAD", "git show HEAD~1 > /tmp/x",
        "echo z > /r-2/src/a", "ls -la", "echo z > src/a"])
    def test_it_stays_shut_on_the_sessions_own_tree_and_ordinary_text(self, command):
        assert self._gate(command) is False

    @pytest.mark.parametrize("command", [
        "echo z > /r/src/a", "echo z > /R/SRC/a", "echo z > /r//src/a", "cd .. && echo z > a", "echo z > ../a",
        "cat a/../b > c", "echo z > ~/r/a", "echo z > ~other/a", "echo z > $CLAUDE_PROJECT_DIR/a",
        "echo z > /r/.claude/worktrees/other/a", "cd /r && echo z > a"])
    def test_it_opens_on_every_text_that_can_reach_another_checkout(self, command):
        assert self._gate(command) is True

    def test_it_opens_for_a_shell_standing_in_another_checkout(self):
        assert self._gate("echo z > a", elsewhere=True) is True

    def test_from_the_main_seat_it_opens_on_a_nested_checkouts_relative_path(self):
        # air's 32b8d3 (2): the relative path from the session's root, and its
        # tails of two parts or more; a one-part tail stays shut.
        main = {"ours": self.MAIN, "others": (self.WT,)}
        for command in ("echo z > .claude/worktrees/live/a", "echo z > worktrees/live/a",
                        "echo z > ./.CLAUDE/Worktrees/live/a", "cd .claude/worktrees/live && echo z > a"):
            assert self._gate(command, **main) is True, command
        for command in ("echo z > live/a", "echo z > .claude/worktrees/livery/a", "echo z > a/worktrees/lives"):
            assert self._gate(command, **main) is False, command
        # a worktree named 2 never opens it on a redirect of stderr
        assert self._gate("make 2>&1 | tee log", ours=self.MAIN, others=("/r/.claude/worktrees/2",)) is False

    def test_from_a_folder_inside_main_it_reads_the_nested_path_from_there(self):
        speedbump = _hook_module("_speedbump")
        gate = speedbump._shell_may_reach_another_checkout
        assert gate("echo z > worktrees/live/a", [self.WT], self.MAIN, False, "/r/.claude") is True
        assert gate("echo z > live/a", [self.WT], self.MAIN, False, "/r/.claude/worktrees") is False

    def test_it_reads_the_spellings_a_checkout_has_on_each_host(self):
        win_ours, win_main = "C:/r/.claude/worktrees/live", "C:/r"
        assert self._gate(r"echo z > C:\r\src\a", ours=win_ours, others=(win_main,)) is True
        assert self._gate("echo z > /c/r/src/a", ours=win_ours, others=(win_main,)) is True     # Git Bash
        assert self._gate(r"echo z > C:\r\.claude\worktrees\live\a", ours=win_ours, others=(win_main,)) is False
        mac_ours, mac_main = "/private/var/r/.claude/worktrees/live", "/private/var/r"
        assert self._gate("echo z > /var/r/src/a", ours=mac_ours, others=(mac_main,)) is True    # the firmlink
        assert self._gate("echo z > /var/r/.claude/worktrees/live/a", ours=mac_ours, others=(mac_main,)) is False

    def test_an_ordinary_call_reads_no_extractor(self, tmp_path, monkeypatch):
        speedbump = _hook_module("_speedbump")
        root, live = _repo_with_worktree(tmp_path)
        read: list[str] = []
        for name in ("_candidate_paths_from_bash", "iter_removed_or_relocated_operands", "bash_bases"):
            real = getattr(speedbump._bash_patterns, name)
            monkeypatch.setattr(speedbump._bash_patterns, name,
                                lambda *a, _real=real, _name=name, **k: read.append(_name) or _real(*a, **k))
        bump = (speedbump.CP_OTHER_CHECKOUT,)
        for command in ("ls -la", "git status", f"echo z >> {_in(live / 'src' / 'app.py')}", "pytest -q > out.txt"):
            assert speedbump.check_fired("Bash", {"command": command}, live, bumps=bump, cwd=live) is None
        assert read == []
        # control: a slip reads them and fires
        fired = speedbump.check_fired("Bash", {"command": f"echo z >> {_in(root / 'src' / 'app.py')}"}, live,
                                      bumps=bump, cwd=live)
        assert fired is not None and fired[0] == "CP-OTHER-CHECKOUT" and read

    def test_a_clone_of_one_checkout_reads_nothing(self, tmp_path, monkeypatch):
        speedbump = _hook_module("_speedbump")
        root = _repo(tmp_path)
        monkeypatch.setattr(speedbump._bash_patterns, "_candidate_paths_from_bash",
                            lambda *a, **k: pytest.fail("a clone with no other checkout read the extractor"))
        assert speedbump.check_fired("Bash", {"command": "echo z > ../x"}, root,
                                     bumps=(speedbump.CP_OTHER_CHECKOUT,), cwd=root) is None

    def test_the_effects_are_write_guards_zone_effects(self):
        tree = ast.parse((HOOKS_DIR / "write_guard.py").read_text(encoding="utf-8"))
        zone = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_ZONE_EFFECTS" for t in node.targets))
        assert isinstance(zone, ast.Call) and zone.func.id == "frozenset"
        assert _hook_module("_speedbump")._OTHER_CHECKOUT_EFFECTS == frozenset(ast.literal_eval(zone.args[0]))

    def test_the_reason_stays_within_512_bytes_with_the_longer_verb(self):
        speedbump = _hook_module("_speedbump")
        verb = speedbump._counted_verb(speedbump._REMOVES, 1000)
        body = speedbump._other_checkout_text("PowerShell", "n" * 300, "o" * 300, "/" + "p" * 400, verb)
        reason = speedbump._REASON_TEMPLATE.format(id="CP-OTHER-CHECKOUT", body=body)
        assert len(reason.encode("utf-8")) <= 512, len(reason.encode("utf-8"))
        assert "this PowerShell removes or moves 1000 files in " in reason
        assert speedbump._counted_verb(speedbump._WRITES, 1) == "writes into"

    def test_the_project_dir_spellings_hold_the_helpers_own(self):
        # a hand copy (this module reads no new helper name), held to the canon
        canon = _hook_module("_hook_utils")._PS_ENV_PROJECT_DIR_PREFIXES
        assert canon and {s.rstrip("/") for s in canon} <= set(_hook_module("_speedbump")._PROJECT_DIR_SPELLINGS)
