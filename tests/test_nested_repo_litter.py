"""Earn-the-red for the SessionStart nested-repo-litter early-warning.

Plants an untracked nested git repo in a tmp working tree and asserts the
detector surfaces it -- and stays SILENT on a clean tree (no boot noise).
Loads the hook by path (tools/cc/ runs standalone), mirroring test_session_banner.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"


def _load():
    spec = importlib.util.spec_from_file_location("_ss_litter", HOOKS_DIR / "session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, encoding="utf-8")


def _init_repo(path):
    _git(["init"], path)
    _git(["config", "user.email", "t@t"], path)
    _git(["config", "user.name", "t"], path)
    _git(["config", "commit.gpgsign", "false"], path)  # immune to a global gpgsign
    _git(["config", "core.excludesFile", ""], path)  # immune to a global ignore of `.claude/` (drove a hostile red)


def _seed_commit(path):
    _init_repo(path)
    (path / "seed.txt").write_text("seed", encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-m", "seed"], path)


def _add_worktree(path, name, *, lock=False):
    # A real `git worktree add` -- the registered-worktree shape source A reads
    # and the `.git` gitlink shape source B finds. `lock=True` stands in for the
    # lock Claude Code holds on a running agent's or backgrounded session's
    # worktree (docs/external/cc-worktrees.md): git cannot tell that lock from
    # one you set yourself (same `locked` file, same porcelain line), which is
    # why an operator-set lock also suppresses the warning -- permanently,
    # since the sweep never releases it.
    rel = f".claude/worktrees/{name}"
    (path / ".claude" / "worktrees").mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", rel, "-b", f"wt-{name}"], path)
    if lock:
        _git(["worktree", "lock", rel], path)
    return path / rel


def _exclude_worktrees(path):
    # The self-host blind spot (see test_excluded_worktree_still_caught_via_worktree_list):
    # `.claude/worktrees/` is machine-local-excluded, so `git status` is blind and
    # ONLY the worktree-list source can see the worktree -- the source that must
    # also know to skip it.
    (path / ".git" / "info" / "exclude").write_text("**/.claude/worktrees/\n", encoding="utf-8")


class TestNestedRepoLitter:
    def test_untracked_nested_repo_is_flagged(self, tmp_path):
        _init_repo(tmp_path)
        nested = tmp_path / "adopt2"
        nested.mkdir()
        _git(["init"], nested)  # a real nested repo (own .git dir)
        assert "adopt2" in _load()._find_nested_repo_litter(tmp_path)

    def test_clean_tree_is_silent(self, tmp_path, capsys):
        _init_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.txt").write_text("x", encoding="utf-8")
        mod = _load()
        assert mod._find_nested_repo_litter(tmp_path) == []
        mod._warn_if_nested_repo_litter(tmp_path)
        assert capsys.readouterr().err == ""

    def test_gitlink_worktree_shape_is_flagged(self, tmp_path):
        # A real `git worktree add` leaves a `.git` GITLINK FILE (not a dir) -- the
        # exact shape a leftover worktree leaves, hidden under a collapsed
        # `?? .claude/` porcelain line and found by the bounded descent. (A
        # hand-authored dangling gitlink is invisible to `git status`, so it would
        # never surface as an untracked candidate -- verified empirically.)
        _init_repo(tmp_path)
        (tmp_path / "seed.txt").write_text("seed", encoding="utf-8")
        _git(["add", "-A"], tmp_path)
        _git(["commit", "-m", "seed"], tmp_path)
        (tmp_path / ".claude" / "worktrees").mkdir(parents=True)
        _git(["worktree", "add", ".claude/worktrees/leftover", "-b", "wt"], tmp_path)
        assert (tmp_path / ".claude" / "worktrees" / "leftover" / ".git").is_file()
        assert any(p.endswith("leftover") for p in _load()._find_nested_repo_litter(tmp_path))

    def test_excluded_worktree_still_caught_via_worktree_list(self, tmp_path):
        # The self-host blind spot, pinned: `.claude/worktrees/` is commonly
        # machine-local-excluded (`.git/info/exclude`), so `git status` is BLIND
        # to a leftover worktree there -- but `git worktree list` finds it anyway.
        # Without this fixture the suite greens on a fresh tmp repo that lacks the
        # exclude, hiding the exact case the feature exists for (env-relative green).
        _init_repo(tmp_path)
        (tmp_path / "seed.txt").write_text("seed", encoding="utf-8")
        _git(["add", "-A"], tmp_path)
        _git(["commit", "-m", "seed"], tmp_path)
        (tmp_path / ".git" / "info" / "exclude").write_text("**/.claude/worktrees/\n", encoding="utf-8")
        (tmp_path / ".claude" / "worktrees").mkdir(parents=True)
        _git(["worktree", "add", ".claude/worktrees/leftover", "-b", "wt"], tmp_path)
        # `git status` is genuinely blind here (the untracked-scan alone misses it):
        st = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path),
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "worktrees" not in st.stdout, "fixture must reproduce the exclude blind spot"
        # ...but the detector still catches it via the worktree-list source:
        assert any(p.endswith("leftover") for p in _load()._find_nested_repo_litter(tmp_path))

    def test_unicode_named_nested_repo_is_not_silently_missed(self, tmp_path):
        # git C-quotes a non-ASCII path in porcelain; the detector runs
        # `-c core.quotepath=false` so a `réf/` nested repo stays visible and is
        # not silently missed (a silent miss = the false-confidence failure the
        # feature exists to prevent).
        _init_repo(tmp_path)
        nested = tmp_path / "réf"
        nested.mkdir()
        _git(["init"], nested)
        assert _load()._find_nested_repo_litter(tmp_path), "unicode-named nested repo was silently missed"

    def test_reporter_emits_stderr_when_litter_present(self, tmp_path, capsys):
        _init_repo(tmp_path)
        nested = tmp_path / "adopt2"
        nested.mkdir()
        _git(["init"], nested)
        mod = _load()
        mod._warn_if_nested_repo_litter(tmp_path)
        err = capsys.readouterr().err
        assert "adopt2" in err and "nested git repo" in err

    def test_reporter_fails_open_on_non_git_dir(self, tmp_path, capsys):
        # non-git dir: `git status` returns non-zero -> detector returns [] and the
        # reporter stays silent; it must never raise (fail-open reporter contract).
        mod = _load()
        assert mod._find_nested_repo_litter(tmp_path) == []
        mod._warn_if_nested_repo_litter(tmp_path)
        assert capsys.readouterr().err == ""


class TestWorktreeInUseIsNotLitter:
    """The nested repo the session is running in, and any worktree carrying a
    ``git worktree lock`` (Claude Code's, or one you set yourself), are not
    litter -- docs/external/cc-worktrees.md is the source of truth: the hook
    input's ``cwd`` follows Claude into a worktree while ``CLAUDE_PROJECT_DIR``
    stays at the project root, and Claude Code holds a lock on a running
    agent's or backgrounded session's worktree. The in-use tree gets one INFO
    line in place of the WARN (inside a nested worktree the harness's path
    guards are keyed to the project root, and that line is the only one
    saying so). Every other nested repo is still reported -- each case carries
    its control.
    """

    def test_worktree_containing_cwd_is_not_reported_via_worktree_list(self, tmp_path):
        # Excluded shape: `git status` is blind, so the only source that can see
        # the worktree is the one that must skip it.
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        live = _add_worktree(tmp_path, "live")
        _add_worktree(tmp_path, "stale")
        mod = _load()
        # Control: with cwd at the project root both worktrees are litter.
        at_root = mod._find_nested_repo_litter(tmp_path, cwd=tmp_path)
        assert ".claude/worktrees/live" in at_root and ".claude/worktrees/stale" in at_root
        # A cwd INSIDE the worktree (a subdirectory: containment, not equality).
        sub = live / "src"
        sub.mkdir()
        in_live = mod._find_nested_repo_litter(tmp_path, cwd=sub)
        assert ".claude/worktrees/live" not in in_live
        assert ".claude/worktrees/stale" in in_live  # the skip is per-worktree, not global

    def test_worktree_containing_cwd_is_not_reported_via_untracked_scan(self, tmp_path):
        # Untracked shape: `.claude/` is untracked, so the descent finds the
        # gitlink too -- the skip must hold at that site as well.
        _seed_commit(tmp_path)
        live = _add_worktree(tmp_path, "live")
        st = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path),
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "?? .claude/" in st.stdout, "fixture must expose the worktree to the untracked scan"
        mod = _load()
        assert ".claude/worktrees/live" in mod._find_nested_repo_litter(tmp_path, cwd=tmp_path)
        assert ".claude/worktrees/live" not in mod._find_nested_repo_litter(tmp_path, cwd=live)

    def test_locked_worktree_is_not_reported_via_worktree_list(self, tmp_path):
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        _add_worktree(tmp_path, "held", lock=True)
        _add_worktree(tmp_path, "stale")
        wl = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=str(tmp_path),
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "\nlocked" in wl.stdout, "fixture must produce a locked line"
        found = _load()._find_nested_repo_litter(tmp_path, cwd=tmp_path)
        assert ".claude/worktrees/stale" in found  # control: the unlocked sibling
        assert ".claude/worktrees/held" not in found

    def test_locked_worktree_is_not_reported_via_untracked_scan(self, tmp_path):
        _seed_commit(tmp_path)
        _add_worktree(tmp_path, "held", lock=True)
        _add_worktree(tmp_path, "stale")
        st = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path),
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "?? .claude/" in st.stdout, "fixture must expose the worktrees to the untracked scan"
        found = _load()._find_nested_repo_litter(tmp_path, cwd=tmp_path)
        assert ".claude/worktrees/stale" in found
        assert ".claude/worktrees/held" not in found

    def test_untracked_clone_containing_cwd_is_not_reported(self, tmp_path):
        _init_repo(tmp_path)
        clone = tmp_path / "adopt2"
        clone.mkdir()
        _git(["init"], clone)
        other = tmp_path / "adopt3"
        other.mkdir()
        _git(["init"], other)
        mod = _load()
        assert "adopt2" in mod._find_nested_repo_litter(tmp_path, cwd=tmp_path)  # control
        in_clone = mod._find_nested_repo_litter(tmp_path, cwd=clone)
        assert "adopt2" not in in_clone
        assert "adopt3" in in_clone

    def test_cwd_defaults_to_the_process_cwd(self, tmp_path, monkeypatch):
        # No payload (the probe's shape, and any caller that passes none): the
        # process's own working directory is the fallback.
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        live = _add_worktree(tmp_path, "live")
        mod = _load()
        monkeypatch.chdir(live)
        assert mod._find_nested_repo_litter(tmp_path) == []
        monkeypatch.chdir(tmp_path)
        assert ".claude/worktrees/live" in mod._find_nested_repo_litter(tmp_path)  # control

    def test_hook_cwd_reads_the_payload_and_falls_back(self, tmp_path):
        mod = _load()
        assert mod._hook_cwd({"cwd": str(tmp_path)}) == tmp_path.resolve()
        assert mod._hook_cwd({}) is None
        assert mod._hook_cwd({"cwd": ""}) is None
        assert mod._hook_cwd({"cwd": 5}) is None
        assert mod._hook_cwd("not a dict") is None
        # Upstream documents `cwd` absolute; a relative or `~` spelling would
        # resolve against the hook's own cwd and name the wrong tree.
        assert mod._hook_cwd({"cwd": "relative/dir"}) is None
        assert mod._hook_cwd({"cwd": "~/tilde"}) is None
        # An embedded NUL raises ValueError from resolve(), not OSError.
        assert mod._hook_cwd({"cwd": "\x00bad"}) is None

    def test_reporter_swaps_the_warn_for_one_info_line_from_inside_the_worktree(self, tmp_path, capsys):
        # Inside a nested worktree the reporter must not go silent -- one INFO
        # line naming it as a registered worktree, no WARN. (Until DEF-743 the
        # line also said the path guards were keyed to the project root and
        # covered nothing there; they resolve against the worktree now, and
        # tests/test_hooks_worktree_checkouts.py drives both guards inside it.)
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        live = _add_worktree(tmp_path, "live")
        mod = _load()
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "[WARN] untracked" in err and "[INFO]" not in err  # control
        mod._warn_if_nested_repo_litter(tmp_path, cwd=live / "src")
        err = capsys.readouterr().err
        assert "[WARN]" not in err
        assert err.count("[INFO] session cwd is inside registered worktree .claude/worktrees/live") == 1

    def test_nested_repo_containing_walks_up_to_the_root_only(self, tmp_path):
        _seed_commit(tmp_path)
        live = _add_worktree(tmp_path, "live")
        clone = tmp_path / "adopt2"
        clone.mkdir()
        _git(["init"], clone)
        mod = _load()
        assert mod._nested_repo_containing(tmp_path, tmp_path) is None
        assert mod._nested_repo_containing(tmp_path, tmp_path / "seed_dir_missing") is None
        (live / "deep" / "er").mkdir(parents=True)
        assert mod._nested_repo_containing(tmp_path, live / "deep" / "er") == ".claude/worktrees/live"
        assert mod._nested_repo_containing(tmp_path, clone) == "adopt2"
        assert mod._nested_repo_containing(tmp_path, tmp_path.parent) is None  # outside the repo

    def test_lock_skip_degrades_to_reporting_when_the_worktree_list_fails(self, tmp_path, monkeypatch):
        # The `locked` set comes from `git worktree list`; when that command is
        # lost (timeout, non-zero exit) the untracked descent reports the locked
        # worktree -- fail-open toward noise, pinned here so the degradation is
        # a decision and not a surprise. The cwd skip does not depend on it.
        _seed_commit(tmp_path)
        held = _add_worktree(tmp_path, "held", lock=True)
        live = _add_worktree(tmp_path, "live")
        mod = _load()
        real_run = mod.subprocess.run

        def failing_worktree_list(args, *a, **kw):
            if list(args[:3]) == ["git", "worktree", "list"]:
                raise mod.subprocess.TimeoutExpired(args, 5)
            return real_run(args, *a, **kw)

        monkeypatch.setattr(mod.subprocess, "run", failing_worktree_list)
        degraded = mod._find_nested_repo_litter(tmp_path, cwd=live)
        assert ".claude/worktrees/held" in degraded  # reported: the lock skip is lost
        assert ".claude/worktrees/live" not in degraded  # the cwd skip holds
        monkeypatch.setattr(mod.subprocess, "run", real_run)
        assert ".claude/worktrees/held" not in mod._find_nested_repo_litter(tmp_path, cwd=live)  # control
        assert held.is_dir()

    def test_case_variant_root_spelling_keeps_both_skips(self, tmp_path):
        # On a case-insensitive filesystem (APFS, NTFS) one directory has two
        # spellings and `Path.resolve()` canonicalises neither; identity must be
        # by inode. Driven 2026-09-09 on macOS: a lower-case root spelling under
        # a plain `==` lost both skips and prescribed the failing remedy.
        _seed_commit(tmp_path)
        _add_worktree(tmp_path, "held", lock=True)
        live = _add_worktree(tmp_path, "live")
        _add_worktree(tmp_path, "stale")
        variant = tmp_path.parent / tmp_path.name.swapcase()
        if variant == tmp_path or not variant.is_dir():
            pytest.skip("case-sensitive filesystem: no second spelling of the root exists")
        mod = _load()
        # Untracked shape: the descent builds paths from the variant spelling.
        found = mod._find_nested_repo_litter(variant, cwd=live)
        assert ".claude/worktrees/stale" in found
        assert ".claude/worktrees/held" not in found
        assert ".claude/worktrees/live" not in found
        # Excluded shape: the worktree list prints git's own spelling.
        _exclude_worktrees(tmp_path)
        found = mod._find_nested_repo_litter(variant, cwd=live)
        assert ".claude/worktrees/stale" in found
        assert ".claude/worktrees/held" not in found
        assert ".claude/worktrees/live" not in found

    def test_session_start_drive_with_cwd_payload_stays_silent(self, tmp_path):
        # The whole hook as Claude Code runs it for a worktree session:
        # CLAUDE_PROJECT_DIR at the project root, the payload's cwd inside the
        # worktree (docs/external/cc-worktrees.md).
        from test_hooks import run_hook  # noqa: WPS433 (intentional cross-test reuse)
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        live = _add_worktree(tmp_path, "live")
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        control = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(tmp_path)},
            env,
        )
        assert control.returncode == 0
        assert "[WARN] untracked" in control.stderr  # reachable: the warning fires from the root
        assert "[INFO] session cwd" not in control.stderr
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(live)},
            env,
        )
        assert result.returncode == 0
        assert "[WARN] untracked" not in result.stderr
        assert "[INFO] session cwd is inside registered worktree .claude/worktrees/live" in result.stderr
        json.loads(result.stdout)  # stdout stays the banner JSON (channel XOR)
