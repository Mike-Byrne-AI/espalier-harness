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


#: The reaper's home (`tools/cc/checkout_sync.py`'s WORKTREES_REL), where Claude
#: Code puts a `--worktree` session's and an agent's tree; `_ELSEWHERE` is a
#: registered worktree inside the repository that the reaper never judges.
_HOME = ".claude/worktrees"
_ELSEWHERE = "wt"


def _add_worktree(path, name, *, lock=False, parent=_HOME):
    # A real `git worktree add` -- the registered-worktree shape source A reads
    # and the `.git` gitlink shape source B finds. `lock=True` stands in for the
    # lock Claude Code holds on a running agent's or backgrounded session's
    # worktree (docs/external/cc-worktrees.md): git cannot tell that lock from
    # one you set yourself (same `locked` file, same porcelain line), which is
    # why an operator-set lock also suppresses the warning -- permanently,
    # since the sweep never releases it.
    rel = f"{parent}/{name}"
    (path / parent).mkdir(parents=True, exist_ok=True)
    branch = f"wt-{name}" if parent == _HOME else f"wt-{parent.replace('/', '-')}-{name}"
    _git(["worktree", "add", rel, "-b", branch], path)
    if lock:
        _git(["worktree", "lock", rel], path)
    return path / rel


def _exclude_worktrees(path):
    # The self-host blind spot (see test_excluded_worktree_still_caught_via_worktree_list):
    # `.claude/worktrees/` is machine-local-excluded, so `git status` is blind and
    # ONLY the worktree-list source can see the worktree -- the source that must
    # also know to skip it. The folder outside the reaper's home is excluded the
    # same way, so both kinds are read from the same source.
    (path / ".git" / "info" / "exclude").write_text(f"**/{_HOME}/\n/{_ELSEWHERE}/\n", encoding="utf-8")


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

    def test_a_worktree_the_reaper_named_is_left_to_the_worktrees_line(self, tmp_path, capsys):
        """The catch-up's reaper names each worktree it kept, with the reason
        (uncommitted changes, a live session); the litter WARN's removal for
        the same path would contradict it (a live session's clean tree is one
        a plain removal takes)."""
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        kept = _add_worktree(tmp_path, "kept")
        _add_worktree(tmp_path, "other")
        mod = _load()
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path, covered=[str(kept)])
        err = capsys.readouterr().err
        assert ".claude/worktrees/other" in err
        assert ".claude/worktrees/kept" not in err
        assert "tools/cc/checkout_sync.py" in err and "git worktree remove" not in err, err  # DEF-3086

    def test_reporter_fails_open_on_non_git_dir(self, tmp_path, capsys):
        # non-git dir: `git status` returns non-zero -> detector returns [] and the
        # reporter stays silent; it must never raise (fail-open reporter contract).
        mod = _load()
        assert mod._find_nested_repo_litter(tmp_path) == []
        mod._warn_if_nested_repo_litter(tmp_path)
        assert capsys.readouterr().err == ""


def _warn_lines(err: str) -> list[str]:
    # The litter lines, without the scan's own did-not-finish WARN.
    return [line for line in err.splitlines()
            if line.startswith("[WARN]") and not line.startswith("[WARN] the nested-repo scan")]


def _prescribed_remove(line: str, path: Path) -> list[str]:
    # The removal the line prescribes, as an argv for the named worktree; no
    # spelling of the overriding flag, and no delete, anywhere in the line.
    import re
    assert not re.search(r"remove\s+(-f|--force)\b|--force|delete", line), line
    spelled = re.search(r"`(git worktree remove [^`]*)`", line)
    assert spelled, line
    return [str(path) if word == "<path>" else word for word in spelled.group(1).split()]


class TestEachKindGetsItsOwnRemedy:
    """DEF-5109: the WARN prescribed `git worktree remove --force` for every
    nested repo it named, and Claude Code leaves an agent's worktree behind
    only when it holds changes, so the line named exactly the tree whose work
    the flag drops. A registered worktree of this repository now gets the
    plain removal, which git itself refuses while the tree holds uncommitted
    changes or untracked files (git is the oracle, not a read of ours); a
    nested clone, which `git worktree remove` cannot take and which may hold
    commits no other copy has, gets a remedy that loses nothing. The kind is
    read from git's own worktree registry on disk, so the split costs no
    spawn per entry under SessionStart's wall (DEF-3015). The plain removal
    is for a worktree outside `.claude/worktrees/`, which no reaper judges;
    one inside it is sent to the reaper's dry run (DEF-3086, the class below)."""

    def test_a_dirty_worktree_gets_the_plain_remove_which_git_refuses(self, tmp_path, capsys):
        """Dies to: `--force` kept anywhere in the line (a caveat included:
        the row's probe reads the word), or a removal git carries out over the
        uncommitted file."""
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        dirty = _add_worktree(tmp_path, "agent-x", parent=_ELSEWHERE)
        (dirty / "work.txt").write_text("unsaved", encoding="utf-8")
        _load()._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "--force" not in err, err
        (line,) = _warn_lines(err)
        assert "wt/agent-x" in line and "worktree of this repository" in line, line
        argv = _prescribed_remove(line, dirty)
        refused = subprocess.run(argv, cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8")
        assert refused.returncode != 0, refused
        assert (dirty / "work.txt").read_text(encoding="utf-8") == "unsaved"
        # Control: the same removal takes a clean leftover, so it is a remedy, not a no-op.
        clean = _add_worktree(tmp_path, "agent-y", parent=_ELSEWHERE)
        taken = subprocess.run(_prescribed_remove(line, clean), cwd=str(tmp_path),
                               capture_output=True, text=True, encoding="utf-8")
        assert taken.returncode == 0 and not clean.exists(), taken

    def test_a_foreign_clone_gets_a_remedy_that_loses_nothing(self, tmp_path, capsys):
        """Dies to: the clone told to delete the dir or to run a worktree
        removal (git cannot take a clone), or named as a worktree."""
        _init_repo(tmp_path)
        clone = tmp_path / "adopt2"
        clone.mkdir()
        _git(["init"], clone)
        (clone / "notes.txt").write_text("only copy", encoding="utf-8")
        _load()._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        (line,) = _warn_lines(err)
        assert "adopt2" in line and "worktree registry does not list" in line, line
        assert "move it out of the working tree" in line and ".gitignore" in line, line
        for harm in ("--force", "delete", "git worktree remove", "worktree of this repository"):
            assert harm not in line, (harm, line)

    def test_a_mixed_tree_names_each_kind_on_its_own_line(self, tmp_path, capsys):
        """Dies to: one shared remedy for both kinds, or a path named on the
        other kind's line."""
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        _add_worktree(tmp_path, "agent-x", parent=_ELSEWHERE)
        _add_worktree(tmp_path, "agent-h")
        clone = tmp_path / "adopt2"
        clone.mkdir()
        _git(["init"], clone)
        _load()._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        lines = _warn_lines(capsys.readouterr().err)
        assert len(lines) == 3, lines
        (tree,) = [line for line in lines if "git worktree remove" in line]
        (home,) = [line for line in lines if "checkout_sync.py" in line]
        (other,) = [line for line in lines if "move it out" in line]
        assert "wt/agent-x" in tree and "adopt2" not in tree and "agent-h" not in tree, tree
        assert ".claude/worktrees/agent-h" in home and "agent-x" not in home and "adopt2" not in home, home
        assert "adopt2" in other and "agent-x" not in other and "agent-h" not in other, other

    def test_the_kind_survives_a_worktree_list_that_did_not_answer(self, tmp_path, monkeypatch, capsys):
        """The registry is read from disk, so a `git worktree list` lost to
        its cap still leaves a worktree the descent found with the worktree
        remedy. Dies to: the kind read from that list's output."""
        _seed_commit(tmp_path)
        dirty = _add_worktree(tmp_path, "agent-x", parent=_ELSEWHERE)  # `wt/` untracked: the descent finds it
        (dirty / "work.txt").write_text("unsaved", encoding="utf-8")
        mod = _load()
        real_run = mod.subprocess.run

        def failing_worktree_list(args, *a, **kw):
            if list(args[:3]) == ["git", "worktree", "list"]:
                raise mod.subprocess.TimeoutExpired(args, 5)
            return real_run(args, *a, **kw)

        monkeypatch.setattr(mod.subprocess, "run", failing_worktree_list)
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "git worktree list did not answer in 5 s" in err, err
        (line,) = _warn_lines(err)
        assert "wt/agent-x" in line and "git worktree remove" in line, line
        assert "--force" not in err, err
        # The lock skip is lost with the list, so a locked tree may be a live
        # one's: the line says to leave it, never to unlock it.
        assert "a locked one may be in use, so leave it" in line and "git worktree unlock" not in line, line

    def test_the_banner_cut_keeps_each_remedy_and_its_caveats(self, tmp_path, capsys):
        """The banner cuts each warning at its byte cap; the first cut of this
        line left the refusal's caveats past it, and seven entries left only
        paths. Dies to: the paths or a preamble placed ahead of the remedy."""
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        for i in range(7):
            _add_worktree(tmp_path, f"agent-{i:016x}", parent=_ELSEWHERE)
            _add_worktree(tmp_path, f"agent-{i:016x}")
        clone = tmp_path / "adopt2"
        clone.mkdir()
        _git(["init"], clone)
        mod = _load()
        mod._hook_utils.take_advisories()
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        capsys.readouterr()
        block = mod._warnings_section()
        for clause in ("`git worktree remove <path>`", "uncommitted changes or untracked files",
                       "its ignored files go with it", "`git worktree unlock <path>` first if locked",
                       "move it out of the working tree", "`git worktree move`", ".gitignore",
                       "tools/cc/checkout_sync.py`", "a live session, a lock, an operation in progress",
                       "a removal by hand would take a live session's clean tree"):
            assert clause in block, (clause, block)

    def test_a_detached_worktree_adds_the_branch_step(self, tmp_path, capsys):
        """The plain removal takes a clean detached tree and its own commits
        with it (no branch keeps them); the registry's HEAD says detached with
        no spawn. Dies to: the clause missing for a detached tree, or printed
        for a tree on a branch."""
        mod = _load()
        # One root per case: the registry read is memoised per root for the
        # process, as one hook start reads it once.
        for name, detach in (("on-branch", False), ("detached", True)):
            root = tmp_path / name
            root.mkdir()
            _seed_commit(root)
            _exclude_worktrees(root)
            _add_worktree(root, "on-branch", parent=_ELSEWHERE)
            if detach:
                _git(["worktree", "add", "--detach", f"{_ELSEWHERE}/detached"], root)
            mod._warn_if_nested_repo_litter(root, cwd=root)
            (line,) = _warn_lines(capsys.readouterr().err)
            clause = "branch a detached one's commits first: `git -C <path> branch <name>`"
            assert (clause in line) is detach, line

    def test_the_remedy_costs_no_spawn_per_entry(self, tmp_path, monkeypatch):
        """A guard, not a red: the split must not ask git about each entry
        (SessionStart's 13 s wall, DEF-3015). Dies to: a status or list call
        per named worktree."""
        mod = _load()
        real_popen = mod.subprocess.Popen
        spawned: list[list[str]] = []

        class CountingPopen(real_popen):  # type: ignore[misc, valid-type]
            def __init__(self, args, *a, **kw):
                spawned.append(list(args))
                super().__init__(args, *a, **kw)

        # The interpreter the reaper's line spells is probed once a process (a
        # memo the banner's Host line fills first): read it before counting.
        mod._hook_utils.python_command_hint()
        counts = {}
        for parent in (_ELSEWHERE, _HOME):
            for n in (1, 3):
                root = tmp_path / f"{parent.replace('/', '-')}-r{n}"
                root.mkdir()
                _seed_commit(root)
                _exclude_worktrees(root)
                for i in range(n):
                    (_add_worktree(root, f"agent-{i}", parent=parent) / "work.txt").write_text(
                        "unsaved", encoding="utf-8")
                spawned.clear()
                monkeypatch.setattr(mod.subprocess, "Popen", CountingPopen)
                mod._warn_if_nested_repo_litter(root, cwd=root)
                monkeypatch.setattr(mod.subprocess, "Popen", real_popen)
                counts[(parent, n)] = len(spawned)
        for parent in (_ELSEWHERE, _HOME):
            assert counts[(parent, 1)] == counts[(parent, 3)] and counts[(parent, 1)] > 0, counts


#: The head of the line a tree under the reaper's home gets (DEF-3086).
_UNJUDGED = "under .claude/worktrees/ not judged at this start"


class TestATreeNoReaperJudgedGetsItsDryRun:
    """DEF-3086: a registered worktree under `.claude/worktrees/` that no reaper
    judged at this start -- a resume or compact start, catch-up off (the
    adopter default), a tree the reaper deferred for time -- got the plain
    removal, which git carries out on a clean tree, a live session's
    included: driven 2026-11-15 on the Windows box, a resume of the main
    checkout's session named the second seat's clean, unlocked worktree for
    removal. That folder is the reaper's home, and its dry run
    (`tools/cc/checkout_sync.py`, no `--apply`) judges what the line cannot
    read under the wall: the session registry and markers, a lock when the
    worktree list is lost, an operation in progress, commits not in main,
    ignored files. The line names that dry run, and leaves out a tree a live
    session marker places a session in, by the reaper's own marker reads."""

    def test_a_clean_unlocked_tree_no_reaper_judged_is_sent_to_the_dry_run(self, tmp_path, capsys):
        """Dies to: the plain removal (or an unlock) printed for a tree under
        `.claude/worktrees/`, or a command spelled with a flag that acts."""
        import re

        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        seat = _add_worktree(tmp_path, "2")  # a `--worktree` session's tree: clean, unlocked
        _add_worktree(tmp_path, "elsewhere", parent=_ELSEWHERE)
        mod = _load()
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path, covered=[])  # a resume: no reaper ran
        lines = _warn_lines(capsys.readouterr().err)
        (home,) = [line for line in lines if ".claude/worktrees/2" in line]
        assert _UNJUDGED in home, home
        for harm in ("git worktree remove", "git worktree unlock", "--apply", "--force", "delete"):
            assert harm not in home, (harm, home)
        spelled = re.search(r"`([^`]*tools/cc/checkout_sync\.py[^`]*)`", home)
        assert spelled and spelled.group(1).split()[-1] == "tools/cc/checkout_sync.py", home  # no flag: the dry run
        # Control: a worktree the reaper never judges keeps git's own refusal as its remedy.
        (other,) = [line for line in lines if "wt/elsewhere" in line]
        assert "git worktree remove <path>" in other and ".claude/worktrees/2" not in other, other
        # The harm the old remedy carried, measured: git takes the clean tree.
        taken = subprocess.run(["git", "worktree", "remove", str(seat)], cwd=str(tmp_path),
                               capture_output=True, text=True, encoding="utf-8")
        assert taken.returncode == 0 and not seat.exists(), taken

    def test_a_lost_worktree_list_still_sends_a_home_tree_to_the_dry_run(self, tmp_path, monkeypatch, capsys):
        """Lead 1 of note e72e1b: with `git worktree list` lost the lock skip
        goes with it, and a locked tree the descent finds may be a live
        session's. The dry run reads its own list and judges the lock. Dies
        to: the unlock or a removal printed for a tree under the home."""
        _seed_commit(tmp_path)
        _add_worktree(tmp_path, "held", lock=True)  # `.claude/` untracked: the descent finds it
        mod = _load()
        real_run = mod.subprocess.run

        def failing_worktree_list(args, *a, **kw):
            if list(args[:3]) == ["git", "worktree", "list"]:
                raise mod.subprocess.TimeoutExpired(args, 5)
            return real_run(args, *a, **kw)

        monkeypatch.setattr(mod.subprocess, "run", failing_worktree_list)
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "git worktree list did not answer in 5 s" in err, err
        (line,) = _warn_lines(err)
        assert ".claude/worktrees/held" in line and "tools/cc/checkout_sync.py" in line, line
        assert "unlock" not in line and "git worktree remove" not in line, line

    def test_a_tree_a_live_session_marker_places_a_session_in_is_not_named(self, tmp_path, capsys):
        """The reaper keeps a tree a marker touched within the live window
        places a session in: one in the tree's own state directory, or one of
        the root's whose recorded cwd is inside it (a session that entered
        the worktree). The line reads the same markers by the same reader, so
        a live seat's tree is not named on every resume. Dies to: either read
        missing. Control: the same markers past the window name both trees."""
        import os
        import time

        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        own = _add_worktree(tmp_path, "own-marker")
        entered = _add_worktree(tmp_path, "entered")
        mod = _load()
        hu = mod._hook_utils
        assert hu.write_session_marker(own, "seat-in-own", cwd=str(own))
        assert hu.write_session_marker(tmp_path, "seat-that-entered", cwd=str(entered / "src"))
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        assert _warn_lines(capsys.readouterr().err) == []
        stale = time.time() - hu.SESSION_MARKER_LIVE_S - 60
        for marker in (hu.session_marker_path(own, "seat-in-own"),
                       hu.session_marker_path(tmp_path, "seat-that-entered")):
            os.utime(marker, (stale, stale))
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        (line,) = _warn_lines(capsys.readouterr().err)
        assert ".claude/worktrees/own-marker" in line and ".claude/worktrees/entered" in line, line

    def test_without_the_reaper_deployed_the_line_names_its_upgrade(self, tmp_path, monkeypatch, capsys):
        """A deploy set without `tools/cc/checkout_sync.py` has no dry run to
        run: the line names the upgrade that deploys it. Dies to: a fall back
        to the plain removal."""
        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        _add_worktree(tmp_path, "2")
        mod = _load()
        monkeypatch.setattr(mod._hook_utils, "load_checkout_sync", lambda: None)
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        (line,) = _warn_lines(capsys.readouterr().err)
        assert "`espalier upgrade`" in line and "tools/cc/checkout_sync.py" in line, line
        assert "git worktree remove" not in line, line


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

    def test_a_claude_lock_whose_holder_exited_no_longer_hides_the_worktree(self, tmp_path):
        """Claude Code's lock names its holder, `claude agent <id> (pid N)`.
        Once N has exited nobody wants the tree: seven such stale locks hid
        seven leftovers on 2026-10-08. A live holder still hides it."""
        import os
        import sys as _sys

        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        child = subprocess.Popen([_sys.executable, "-c", "pass"])
        child.wait(timeout=30)
        dead = _add_worktree(tmp_path, "dead-holder")
        live = _add_worktree(tmp_path, "live-holder")
        _git(["worktree", "lock", "--reason", f"claude agent agent-d (pid {child.pid})", str(dead)], tmp_path)
        _git(["worktree", "lock", "--reason", f"claude agent agent-l (pid {os.getpid()})", str(live)], tmp_path)
        found = _load()._find_nested_repo_litter(tmp_path, cwd=tmp_path)
        assert ".claude/worktrees/dead-holder" in found
        assert ".claude/worktrees/live-holder" not in found

    def test_a_claude_lock_naming_a_live_pids_other_start_still_hides_the_worktree(self, tmp_path, monkeypatch):
        """Claude Code's lock can name its holder's start, `(pid N start
        <date>)`. This warning names a worktree for removal, and git takes a clean one, so it reads the
        pid alone and reads no start: a live N keeps the tree hidden whatever
        start the lock names (the reaper, which removes only a clean, merged
        tree, is the reader that compares it)."""
        import os

        _seed_commit(tmp_path)
        _exclude_worktrees(tmp_path)
        held = _add_worktree(tmp_path, "start-held")
        _git(["worktree", "lock", "--reason",
              f"claude agent agent-s (pid {os.getpid()} start Thu Jan  1 00:00:00 2026)", str(held)], tmp_path)
        ss = _load()
        sync = ss._hook_utils.load_checkout_sync()
        monkeypatch.setattr(sync, "proc_starts", lambda *a, **k: pytest.fail("the warning read a start"))
        assert ".claude/worktrees/start-held" not in ss._find_nested_repo_litter(tmp_path, cwd=tmp_path)

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
        assert f"[WARN] 1 worktree {_UNJUDGED}" in err and "[INFO]" not in err  # control
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
        unread: list[str] = []
        degraded = mod._find_nested_repo_litter(tmp_path, cwd=live, unread=unread)
        assert ".claude/worktrees/held" in degraded  # reported: the lock skip is lost
        assert ".claude/worktrees/live" not in degraded  # the cwd skip holds
        assert unread == ["git worktree list did not answer in 5 s"]  # and the loss is told
        monkeypatch.setattr(mod.subprocess, "run", real_run)
        unread.clear()
        assert ".claude/worktrees/held" not in mod._find_nested_repo_litter(tmp_path, cwd=live, unread=unread)
        assert unread == [] and held.is_dir()  # control

    def test_a_scan_cut_short_warns_and_never_reads_as_a_clean_tree(self, tmp_path, monkeypatch, capsys):
        """A killed `git status` (or the descent's node cap) returned what it
        had, and an empty list printed nothing, the same as a clean tree. Dies
        to: either cut-off folded back into the silent return."""
        _init_repo(tmp_path)
        nested = tmp_path / "adopt2"
        nested.mkdir()
        _git(["init"], nested)
        mod = _load()
        real_run = mod.subprocess.run

        def killed_status(args, *a, **kw):
            if "status" in list(args):
                raise mod.subprocess.TimeoutExpired(args, 5)
            return real_run(args, *a, **kw)

        monkeypatch.setattr(mod.subprocess, "run", killed_status)
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "the nested-repo scan did not finish (git status did not answer in 5 s)" in err, err
        assert "adopt2" not in err
        monkeypatch.setattr(mod.subprocess, "run", real_run)
        unread: list[str] = []
        assert mod._find_nested_repo_litter(tmp_path, cwd=tmp_path, max_nodes=0, unread=unread) == []
        assert unread == ["the untracked descent stopped at 0 directories in adopt2/"]
        # The cap is a size bound that repeats every start: an INFO with the folder and the remedy.
        real_find = mod._find_nested_repo_litter
        monkeypatch.setattr(mod, "_find_nested_repo_litter", lambda root, **kw: real_find(root, max_nodes=0, **kw))
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "[INFO] the nested-repo scan stops early (the untracked descent stopped at 0 directories in " \
               "adopt2/)" in err and "gitignored" in err, err
        assert "[WARN] the nested-repo scan" not in err
        monkeypatch.setattr(mod, "_find_nested_repo_litter", real_find)
        mod._warn_if_nested_repo_litter(tmp_path, cwd=tmp_path)
        err = capsys.readouterr().err
        assert "adopt2" in err and "did not finish" not in err  # control: the scan that finished

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
        from _hook_runner import run_hook  # noqa: WPS433
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
        assert f"[WARN] 1 worktree {_UNJUDGED}" in control.stderr  # reachable: the warning fires from the root
        assert "[INFO] session cwd" not in control.stderr
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(live)},
            env,
        )
        assert result.returncode == 0
        assert _UNJUDGED not in result.stderr and "leftover worktree" not in result.stderr
        assert "[INFO] session cwd is inside registered worktree .claude/worktrees/live" in result.stderr
        json.loads(result.stdout)  # stdout stays the banner JSON (channel XOR)
