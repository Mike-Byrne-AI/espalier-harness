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

import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path, PureWindowsPath

import pytest

from _hook_assertions import assert_hook_allowed
from test_hooks import run_hook  # intentional cross-test reuse (the litter tests do the same)
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

        assert _decision(bash(f"echo x > {live / TARGET}")) == "deny"
        assert_hook_allowed(bash(f"echo x > {live / 'src' / 'app.py'}"))

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
            payload = {"tool_name": "Bash", "tool_input": {"command": f"echo x > {alias}"}}
        elif channel == "PowerShell":
            payload = {"tool_name": "PowerShell",
                       "tool_input": {"command": f"Set-Content -Path {alias} -Value x"}}
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
        out = pwc._bash_derived_payloads({"command": f"echo x > {new}"}, root, already=0)
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
