"""Contract tests for ``tools/cc/checkout_sync.py``: the session-start
catch-up of a merged checkout and the reaper of leftover worktrees.

REAL-GIT cases, because git's own refusals and ancestry answers are the
thing under test: a bare origin, a seed clone that plays the other machine
merging pull requests, and the checkout under test. Each move is read back
from git (HEAD, the branch list, ``git worktree list``), never from the
module's own account of itself.

The reaper's anchor case is the 2026-10-08 incident: an idle background
session, resumed by Claude Code's daemon, sat in a clean, merged worktree
with no lock and no recent file writes; a one-off cleanup keyed on file
recency removed it. Claude Code's session registry is what names it, and
``TestReapWorktrees::test_todays_case_*`` pins that the reaper reads it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests._git_oracle import _git_env
from tests._interpreter_hosts import HOOK_PYTHON
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "tools" / "cc" / "checkout_sync.py"


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cs():
    return _load(MODULE, "checkout_sync_under_test")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=check, timeout=scaled(45))


def _out(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _identity(repo: Path) -> None:
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo: Path, name: str, text: str = "x\n") -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "--quiet", "-m", f"add {name}")
    return _out(repo, "rev-parse", "HEAD")


def _dead_pid() -> int:
    """The pid of a process that has exited (reaped, so it is not a zombie)."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    return child.pid


@pytest.fixture
def repos(tmp_path):
    """origin (bare), seed (the other machine), work (the checkout under test)."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--quiet", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "--quiet", str(origin), str(seed))
    _identity(seed)
    _commit(seed, "README.md", "seed\n")
    _git(seed, "push", "--quiet", "-u", "origin", "main")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "--quiet", str(origin), str(work))
    _identity(work)
    return {"origin": origin, "seed": seed, "work": work}


def _advance(seed: Path, n: int = 1, prefix: str = "more") -> None:
    _git(seed, "pull", "--quiet", "--ff-only")
    for i in range(n):
        _commit(seed, f"{prefix}{i}.txt")
    _git(seed, "push", "--quiet", "origin", "main")


def _merged_lane(repos, lane: str = "lane/x") -> None:
    """``lane`` committed and pushed from work, merged on origin with a merge
    commit by the seed, and its remote branch deleted (GitHub's
    delete-on-merge): work is left ON the lane, behind origin/main."""
    work, seed = repos["work"], repos["seed"]
    _git(work, "switch", "--quiet", "-c", lane)
    _commit(work, f"{lane.replace('/', '_')}.txt")
    _git(work, "push", "--quiet", "-u", "origin", lane)
    _git(seed, "pull", "--quiet", "--ff-only")
    _git(seed, "fetch", "--quiet", "origin", lane)
    _git(seed, "merge", "--quiet", "--no-ff", "-m", f"Merge {lane}", f"origin/{lane}")
    _git(seed, "push", "--quiet", "origin", "main")
    _git(seed, "push", "--quiet", "origin", "--delete", lane)


# -- catch-up ----------------------------------------------------------------------

class TestCatchUp:
    def test_a_merged_lane_moves_to_main_fast_forwards_and_drops_the_gone_branch(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"], 2)
        result = cs.catch_up(work)
        assert result.state == "caught_up", result
        assert _out(work, "symbolic-ref", "--short", "HEAD") == "main"
        assert _out(work, "rev-parse", "HEAD") == _out(work, "rev-parse", "origin/main")
        assert result.deleted_branch == "lane/x"
        assert "lane/x" not in _out(work, "branch", "--format=%(refname:short)").split()
        line = cs.checkout_line(result)
        assert line.startswith("caught up -- left lane/x (merged, branch deleted); main fast-forwarded")
        assert line.isascii()

    def test_main_behind_with_nothing_local_fast_forwards(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"], 3)
        result = cs.catch_up(work)
        assert result.state == "caught_up" and result.behind == 3
        assert _out(work, "rev-parse", "HEAD") == _out(work, "rev-parse", "origin/main")

    def test_a_lane_created_a_moment_ago_stays_put(self, cs, repos):
        """No commits yet, so 'fully merged' by ancestry -- and nothing to gain."""
        work = repos["work"]
        _git(work, "switch", "--quiet", "-c", "lane/new")
        result = cs.catch_up(work)
        assert result.state == "current"
        assert _out(work, "symbolic-ref", "--short", "HEAD") == "lane/new"

    def test_a_stale_empty_lane_is_named_not_moved(self, cs, repos):
        """Behind, no commits of its own, never pushed: 'no commits of its
        own' is not 'this branch is done' (a lane about to start, a hotfix
        made from an old tag). Only main or a `[gone]` branch moves."""
        work = repos["work"]
        _git(work, "switch", "--quiet", "-c", "lane/idle")
        _advance(repos["seed"])
        result = cs.catch_up(work)
        assert result.state == "lane" and result.reason == "nothing of its own yet"
        assert _out(work, "symbolic-ref", "--short", "HEAD") == "lane/idle"
        assert cs.checkout_line(result) == "on lane/idle (nothing of its own yet); main has 1 newer -- left as is"

    def test_a_merged_lane_whose_remote_branch_still_exists_is_left_as_is(self, cs, repos):
        work, seed = repos["work"], repos["seed"]
        _git(work, "switch", "--quiet", "-c", "lane/kept")
        _commit(work, "kept.txt")
        _git(work, "push", "--quiet", "-u", "origin", "lane/kept")
        _git(seed, "pull", "--quiet", "--ff-only")
        _git(seed, "fetch", "--quiet", "origin", "lane/kept")
        _git(seed, "merge", "--quiet", "--no-ff", "-m", "Merge lane/kept", "origin/lane/kept")
        _git(seed, "push", "--quiet", "origin", "main")
        result = cs.catch_up(work)
        assert result.state == "lane" and result.reason == "its remote branch still exists"
        assert _out(work, "symbolic-ref", "--short", "HEAD") == "lane/kept"

    def test_a_detached_head_behind_is_named_not_moved(self, cs, repos):
        work = repos["work"]
        _git(work, "switch", "--quiet", "--detach", "HEAD")
        before = _out(work, "rev-parse", "HEAD")
        _advance(repos["seed"])
        result = cs.catch_up(work)
        assert result.state == "lane" and _out(work, "rev-parse", "HEAD") == before
        assert cs.checkout_line(result).startswith("on a detached HEAD (nothing of its own); main has 1 newer")

    def test_an_open_plan_holds(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"])
        result = cs.catch_up(work, plan_open=True)
        assert result.state == "held" and "a plan is in progress" in result.reason

    def test_a_move_still_running_at_its_wait_is_never_killed(self, cs, repos):
        """A switch cut off mid-write leaves index.lock and a half-moved tree
        (reproduced by the review on this host): the move is waited on and,
        at the wait, left running and named -- never killed."""
        work = repos["work"]
        _advance(repos["seed"])
        calls = []

        def spawner(argv, *, cwd, wait, kill):
            calls.append((argv[1:], kill))
            if "switch" in argv:
                return cs.Spawned(done=False, pid=4242)
            return cs.spawn(argv, cwd=cwd, wait=wait, kill=kill)

        result = cs.catch_up(work, spawner=spawner)
        assert result.state == "moving" and "git pid 4242" in result.reason
        assert cs.checkout_line(result).startswith("catching up -- the move to origin/main is still running")
        moves = [kill for args, kill in calls if "switch" in args]
        fetches = [kill for args, kill in calls if "fetch" in args]
        assert moves == [False] and fetches == [True]

    def test_uncommitted_tracked_edits_hold_and_name_the_remedy(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        (work / "README.md").write_text("edited\n", encoding="utf-8")
        before = _out(work, "rev-parse", "HEAD")
        result = cs.catch_up(work)
        assert result.state == "held" and "uncommitted change" in result.reason
        assert _out(work, "rev-parse", "HEAD") == before
        assert (work / "README.md").read_text(encoding="utf-8") == "edited\n"
        line = cs.checkout_line(result)
        assert line.startswith("NOT caught up (") and "git switch main && git pull --ff-only origin main" in line

    def test_untracked_files_alone_do_not_hold_and_ride_along(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        (work / "scratch.txt").write_text("mine\n", encoding="utf-8")
        assert cs.catch_up(work).state == "caught_up"
        assert (work / "scratch.txt").read_text(encoding="utf-8") == "mine\n"

    def test_a_lane_with_unpushed_commits_is_left_as_is(self, cs, repos):
        work = repos["work"]
        _git(work, "switch", "--quiet", "-c", "lane/wip")
        head = _commit(work, "wip.txt")
        _advance(repos["seed"])
        result = cs.catch_up(work)
        assert result.state == "lane" and result.ahead == 1
        assert _out(work, "rev-parse", "HEAD") == head
        assert cs.checkout_line(result) == "on lane/wip (1 commit not in main); main has 1 newer -- left as is"

    def test_a_lane_with_work_and_nothing_newer_says_nothing(self, cs, repos):
        work = repos["work"]
        _git(work, "switch", "--quiet", "-c", "lane/busy")
        _commit(work, "busy.txt")
        assert cs.checkout_line(cs.catch_up(work)) == ""

    def test_local_main_with_commits_origin_lacks_holds(self, cs, repos):
        """`switch -C main` would reset local main: it runs only when local
        main is already in origin/main."""
        work = repos["work"]
        _merged_lane(repos)
        _git(work, "switch", "--quiet", "main")
        _commit(work, "local-only.txt")
        local = _out(work, "rev-parse", "main")
        _git(work, "switch", "--quiet", "lane/x")
        _advance(repos["seed"])
        result = cs.catch_up(work)
        assert result.state == "held" and "local main has commits" in result.reason
        assert _out(work, "rev-parse", "main") == local

    def test_a_merge_in_progress_holds(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"])
        merge_head = Path(_out(work, "rev-parse", "--git-path", "MERGE_HEAD"))
        (work / merge_head if not merge_head.is_absolute() else merge_head).write_text(
            _out(work, "rev-parse", "HEAD") + "\n", encoding="utf-8")
        result = cs.catch_up(work)
        assert result.state == "held" and "a merge is in progress" in result.reason

    def test_another_live_session_in_the_checkout_holds(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"])
        result = cs.catch_up(work, other_session="pid 4242")
        assert result.state == "held" and "another live session" in result.reason
        assert result.remedy.startswith("end the other session first (pid 4242;")
        assert _out(work, "rev-parse", "HEAD") != _out(work, "rev-parse", "origin/main")

    def test_no_origin_is_silent(self, cs, tmp_path):
        lone = tmp_path / "lone"
        _git(tmp_path, "init", "--quiet", "-b", "main", str(lone))
        _identity(lone)
        _commit(lone, "a.txt")
        result = cs.catch_up(lone)
        assert result.state == "skipped" and cs.checkout_line(result) == ""

    def test_a_dangling_origin_head_falls_back_to_main(self, cs, repos):
        """Driven 2026-10-08: a clone taken while its source sat on a lane
        points origin/HEAD at that lane, and a --prune fetch drops the lane
        but leaves the symref -- trusted blindly, it named a branch that is
        not there as the base and held with a nonsense remedy."""
        work = repos["work"]
        _git(work, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/lane/vanished")
        _advance(repos["seed"])
        result = cs.catch_up(work)
        assert result.state == "caught_up" and result.base == "main", result

    def test_a_dry_run_moves_nothing(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        before = _out(work, "rev-parse", "HEAD")
        result = cs.catch_up(work, dry_run=True)
        assert result.state == "would_catch_up"
        assert _out(work, "rev-parse", "HEAD") == before

    def test_a_spent_deadline_holds_without_moving_and_says_why(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"])
        before = _out(work, "rev-parse", "HEAD")
        result = cs.catch_up(work, deadline=time.monotonic())
        assert result.state == "held" and "in time" in result.reason
        assert _out(work, "rev-parse", "HEAD") == before

    def test_a_linked_worktree_detaches_at_origin_main_when_main_is_checked_out_elsewhere(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos, "lane/z")
        _git(work, "switch", "--quiet", "main")
        linked = work.parent / "linked"
        _git(work, "worktree", "add", "--quiet", str(linked), "lane/z")
        _advance(repos["seed"])
        result = cs.catch_up(linked)
        assert result.state == "caught_up", result
        assert _git(linked, "symbolic-ref", "--quiet", "HEAD", check=False).returncode != 0  # detached
        assert _out(linked, "rev-parse", "HEAD") == _out(linked, "rev-parse", "origin/main")

    def test_a_switch_git_refuses_is_held_with_its_reason(self, cs, repos):
        """An untracked file where main brings a tracked one: git refuses the
        switch, and the outcome says so rather than claiming a catch-up."""
        work, seed = repos["work"], repos["seed"]
        _merged_lane(repos)
        _git(seed, "pull", "--quiet", "--ff-only")
        _commit(seed, "collide.txt", "theirs\n")
        _git(seed, "push", "--quiet", "origin", "main")
        (work / "collide.txt").write_text("mine\n", encoding="utf-8")
        result = cs.catch_up(work)
        assert result.state == "held" and result.reason.startswith("the move failed")
        assert (work / "collide.txt").read_text(encoding="utf-8") == "mine\n"


# -- the reaper --------------------------------------------------------------------

def _worktree(repos, name: str, branch: str | None = None, *, base: str = "origin/main") -> Path:
    work = repos["work"]
    path = work / ".claude" / "worktrees" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["worktree", "add", "--quiet"]
    args += ["-b", branch, str(path), base] if branch else ["--detach", str(path), base]
    _git(work, *args)
    return path


def _registered(repo: Path, path: Path) -> bool:
    listing = _out(repo, "worktree", "list", "--porcelain")
    return any(Path(line[len("worktree "):]).resolve() == path.resolve()
               for line in listing.splitlines() if line.startswith("worktree "))


def _registry(tmp_path: Path, entries: list[dict]) -> Path:
    cfg = tmp_path / "claude-config"
    (cfg / "sessions").mkdir(parents=True)
    for e in entries:
        (cfg / "sessions" / f"{e['pid']}.json").write_text(json.dumps(e), encoding="utf-8")
    return cfg


# pins: claim:hook-assumption-6-session-registry
class TestReapWorktrees:
    def test_a_clean_merged_worktree_is_removed_and_its_branch_deleted(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "agent-a1", "lane/agent-a1")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == ["agent-a1"], report
        assert not wt.exists() and not _registered(work, wt)
        assert "lane/agent-a1" not in _out(work, "branch", "--format=%(refname:short)").split()
        assert cs.worktrees_line(report).startswith("removed 1 leftover (merged, clean): agent-a1")

    def test_a_worktree_whose_own_seat_holds_live_claims_is_kept(self, cs, repos, monkeypatch):
        """A worktree named for itself is the only writer of its seat's mail:
        removed with a claim unreleased, the claim stays live and nothing can
        close it. Dies to: removing it (the gap the Wave B review recorded)."""
        work = repos["work"]
        wt = _worktree(repos, "feat", "lane/feat")
        _git(work, "config", "extensions.worktreeConfig", "true")
        _git(wt, "config", "--worktree", "espalier.machine", "work-feat")
        asked: list = []

        def claims(root, seat, timeout):
            asked.append(seat)
            return [{"id": "c-feat", "from": seat, "re": {"lane": "lane/feat"}},
                    {"id": "c-next", "from": seat, "re": {"lane": "lane/next"}}]

        monkeypatch.setattr(cs, "seat_live_claims", claims)
        report = cs.reap_worktrees(work, sessions=[])
        assert asked == ["work-feat"] and report.removed == [] and wt.is_dir()
        (name, reason), = report.kept
        assert name == "feat"
        assert reason.startswith("its seat work-feat holds 2 live claims (lane/feat, lane/next) that only it can")
        # By id: a lane release from the seat reads as its lane shipped and closes a job it was given.
        assert "mail.py send --type release --ack <claim id>` for each (c-feat, c-next)" in reason, reason
        assert "--lane" not in reason

    def test_a_seat_with_no_live_claim_and_an_inherited_name_are_removed(self, cs, repos, monkeypatch):
        """No claim left: the worktree goes. A worktree that answers its
        clone's name is not asked at all: the clone's seat can still release."""
        work = repos["work"]
        named = _worktree(repos, "done", "lane/done")
        inherited = _worktree(repos, "plain", "lane/plain")
        _git(work, "config", "extensions.worktreeConfig", "true")
        _git(named, "config", "--worktree", "espalier.machine", "work-done")
        asked: list = []
        monkeypatch.setattr(cs, "seat_live_claims", lambda root, seat, timeout: asked.append(seat) or [])
        report = cs.reap_worktrees(work, sessions=[])
        assert sorted(report.removed) == ["done", "plain"] and asked == ["work-done"]
        assert not named.exists() and not inherited.exists()

    def test_the_seat_claims_are_read_from_the_mail_refs(self, cs, repos, tmp_path):
        """The real read: one claim and one release on the seat's mail ref,
        one claim still live, and another seat's claim not counted."""
        mail = _load(REPO_ROOT / "tools" / "cc" / "mail.py", "mail_for_reaper_test")
        work = repos["work"]
        lines = [mail.encode(mail.new_message("work-feat", "claim", "a", lane="lane/feat")),
                 mail.encode(mail.new_message("work-feat", "claim", "b", lane="lane/old")),
                 mail.encode(mail.new_message("work-feat", "release", "", lane="lane/old"))]
        body = tmp_path / "mail.jsonl"
        body.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        blob = _out(work, "hash-object", "-w", str(body))
        # Bytes and -z: a text-mode input on Windows writes "\n" as "\r\n", and
        # mktree would name the file "mail.jsonl\r".
        tree = subprocess.run(["git", "mktree", "-z"], cwd=work, input=f"100644 blob {blob}\tmail.jsonl\0".encode(),
                              capture_output=True, env=_git_env(), check=True,
                              timeout=scaled(45)).stdout.decode().strip()
        commit = _out(work, "commit-tree", tree, "-m", "mail")
        _git(work, "update-ref", "refs/remotes/origin/mail/work-feat", commit)
        claims = cs.seat_live_claims(work, "work-feat", 10.0)
        assert [(c["from"], c["re"]["lane"]) for c in claims] == [("work-feat", "lane/feat")]
        assert cs.seat_live_claims(work, "work-other", 10.0) == []

    def test_claims_that_cannot_be_read_keep_the_worktree(self, cs, repos, monkeypatch):
        work = repos["work"]
        wt = _worktree(repos, "feat", "lane/feat")
        _git(work, "config", "extensions.worktreeConfig", "true")
        _git(wt, "config", "--worktree", "espalier.machine", "work-feat")

        def unreadable(root, seat, timeout):
            raise RuntimeError("git show took longer than 2s")

        monkeypatch.setattr(cs, "seat_live_claims", unreadable)
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept == [("feat", "its seat work-feat's claims could not be read (git show took longer than 2s)")]
        assert wt.is_dir()

    def test_a_seat_name_that_cannot_be_read_keeps_the_worktree(self, cs, repos, monkeypatch):
        """Only the seat-name read fails (a config git cannot parse, then no
        answer in time), so every other check passes. Dies to the failed read
        taken for "no seat of its own": the worktree went, and with it the one
        checkout that could release its seat's live claims."""
        work = repos["work"]
        _git(work, "config", "extensions.worktreeConfig", "true")
        real_ask = cs._Git.ask
        for i, failed in enumerate((subprocess.CompletedProcess([], 128, "", "fatal: bad config line 3"), None)):
            wt = _worktree(repos, f"feat{i}", f"lane/feat{i}")
            _git(wt, "config", "--worktree", "espalier.machine", f"work-feat{i}")

            def ask(self, *args, _failed=failed, **kw):
                if args == ("config", "--worktree", "--get", "espalier.machine"):
                    return _failed
                return real_ask(self, *args, **kw)
            monkeypatch.setattr(cs._Git, "ask", ask)
            monkeypatch.setattr(cs, "seat_live_claims", lambda root, seat, timeout: [])
            report = cs.reap_worktrees(work, sessions=[])
            assert report.removed == [] and wt.is_dir(), report
            reason = dict(report.kept)[f"feat{i}"]
            assert reason.startswith("its seat name could not be read ("), reason
            assert ("bad config line 3" if failed else "did not answer in time") in reason, reason

    def test_a_switch_read_that_fails_keeps_the_worktree(self, cs, repos, monkeypatch):
        """The per-worktree config switch read itself failing (a value git
        cannot read as a boolean, then no answer in time). Dies to a failed
        switch read taken for "off", which reads as no seat of its own and
        lets the worktree go with its seat's claims."""
        work = repos["work"]
        _git(work, "config", "extensions.worktreeConfig", "true")
        real_ask = cs._Git.ask
        switch = ("config", "--local", "--type=bool", "--get", "extensions.worktreeConfig")
        for i, failed in enumerate((subprocess.CompletedProcess([], 128, "", "fatal: bad boolean config value"),
                                    None)):
            wt = _worktree(repos, f"sw{i}", f"lane/sw{i}")
            _git(wt, "config", "--worktree", "espalier.machine", f"work-sw{i}")

            def ask(self, *args, _failed=failed, **kw):
                return _failed if args == switch else real_ask(self, *args, **kw)
            monkeypatch.setattr(cs._Git, "ask", ask)
            monkeypatch.setattr(cs, "seat_live_claims", lambda root, seat, timeout: [])
            report = cs.reap_worktrees(work, sessions=[])
            assert wt.is_dir(), report
            reason = dict(report.kept)[f"sw{i}"]
            assert reason.startswith("its seat name could not be read ("), reason
            assert ("bad boolean config value" if failed else "did not answer in time") in reason, reason

    def test_a_yes_switch_reads_as_on(self, cs, repos, monkeypatch):
        """git reads the switch as a boolean. Dies to `yes` read as off, which
        took a worktree whose own seat holds claims for one with no seat."""
        work = repos["work"]
        wt = _worktree(repos, "yes", "lane/yes")
        _git(work, "config", "extensions.worktreeConfig", "yes")
        _git(wt, "config", "--worktree", "espalier.machine", "work-yes")
        monkeypatch.setattr(cs, "seat_live_claims",
                            lambda root, seat, timeout: [{"from": seat, "re": {"lane": "lane/yes"}}])
        report = cs.reap_worktrees(work, sessions=[])
        assert wt.is_dir() and dict(report.kept)["yes"].startswith("its seat work-yes holds 1 live claim"), report

    def test_todays_case_an_idle_session_in_a_clean_merged_worktree_keeps_it(self, cs, repos, tmp_path):
        """Clean, merged, unlocked, no file written for hours -- and a live
        Claude session sits in it. The registry names it; the reaper keeps it."""
        work = repos["work"]
        wt = _worktree(repos, "setup-commands")
        old = time.time() - 6 * 3600
        for f in wt.rglob("*"):
            if f.is_file():
                os.utime(f, (old, old))
        cfg = _registry(tmp_path, [{"pid": os.getpid(), "sessionId": "245e75e7", "cwd": str(wt),
                                    "kind": "background", "status": "idle"}])
        sessions = cs.live_sessions(cfg)
        assert sessions and sessions[0]["cwd"] == str(wt)
        report = cs.reap_worktrees(work, sessions=sessions)
        assert report.removed == []
        assert report.kept == [("setup-commands", f"a live Claude session is in it (pid {os.getpid()})")]
        assert wt.is_dir() and _registered(work, wt)

    def test_a_session_in_a_subfolder_of_the_worktree_also_keeps_it(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "deep")
        (wt / "sub").mkdir()
        report = cs.reap_worktrees(work, sessions=[{"pid": os.getpid(), "session_id": "s", "cwd": str(wt / "sub")}])
        assert report.removed == [] and wt.is_dir()

    def test_a_registry_entry_whose_process_is_gone_does_not_keep_it(self, cs, repos, tmp_path):
        work = repos["work"]
        wt = _worktree(repos, "ghost")
        cfg = _registry(tmp_path, [{"pid": _dead_pid(), "sessionId": "dead", "cwd": str(wt)}])
        sessions = cs.live_sessions(cfg)
        assert sessions == []
        assert cs.reap_worktrees(work, sessions=sessions).removed == ["ghost"]

    @pytest.mark.parametrize("shape", ["no_dir", "bad_json", "no_cwd", "not_an_object",
                                       "pid_as_string", "no_pid", "pid_renamed", "half_written_live"])
    def test_a_registry_that_cannot_be_read_reaps_nothing(self, cs, repos, tmp_path, shape):
        """Every shape the reader does not know is "cannot tell", never
        "gone": a string pid once read as a dead session and turned the
        reaper ON (the review's B2), the opposite of fail-closed."""
        work = repos["work"]
        wt = _worktree(repos, "keepme")
        cfg = tmp_path / "cfg"
        if shape != "no_dir":
            (cfg / "sessions").mkdir(parents=True)
            live = {"cwd": str(wt), "sessionId": "s"}
            body = {"bad_json": "{not json", "no_cwd": json.dumps({"pid": os.getpid()}),
                    "not_an_object": "[1, 2]",
                    "pid_as_string": json.dumps({**live, "pid": str(os.getpid())}),
                    "no_pid": json.dumps(live),
                    "pid_renamed": json.dumps({**live, "processId": os.getpid()}),
                    "half_written_live": '{"pid": ' + str(os.getpid())}[shape]
            name = f"{os.getpid()}.json" if shape == "half_written_live" else "entry.json"
            (cfg / "sessions" / name).write_text(body, encoding="utf-8")
        sessions = cs.live_sessions(cfg)
        assert sessions is None
        report = cs.reap_worktrees(work, sessions=sessions)
        assert report.removed == [] and wt.is_dir()
        assert report.note.startswith("Claude Code's session registry could not be read")
        assert "keepme" in cs.worktrees_line(report)

    def test_a_lock_held_by_a_dead_pid_is_released_and_removed(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "agent-dead")
        _git(work, "worktree", "lock", "--reason", f"claude agent agent-dead (pid {_dead_pid()})", str(wt))
        assert cs.reap_worktrees(work, sessions=[]).removed == ["agent-dead"]
        assert not _registered(work, wt)

    def test_a_lock_held_by_a_live_pid_keeps_it(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "agent-live")
        _git(work, "worktree", "lock", "--reason", f"claude agent agent-live (pid {os.getpid()})", str(wt))
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept == [("agent-live", f"locked by a running process (pid {os.getpid()})")]
        assert _registered(work, wt)

    @pytest.mark.parametrize("reason", [None, "mine, do not touch"])
    def test_a_hand_set_lock_keeps_it(self, cs, repos, reason):
        work = repos["work"]
        wt = _worktree(repos, "by-hand")
        _git(work, "worktree", "lock", *(["--reason", reason] if reason else []), str(wt))
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept == [("by-hand", "locked by hand (git worktree unlock releases it)")]

    def test_unmerged_commits_keep_it_and_say_how_many(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "lane-wip", "lane/wip")
        _identity(wt)
        _commit(wt, "a.txt")
        _commit(wt, "b.txt")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept == [("lane-wip", "2 commit(s) not in main (lane/wip)")]
        assert wt.is_dir()

    def test_uncommitted_changes_keep_it(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "dirty")
        (wt / "README.md").write_text("changed\n", encoding="utf-8")
        (wt / "new.txt").write_text("new\n", encoding="utf-8")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept == [("dirty", "2 uncommitted changes")]

    def test_this_sessions_own_worktree_is_kept(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "mine")
        report = cs.reap_worktrees(work, sessions=[], own_cwd=wt)
        assert report.kept == [("mine", "this session is in it")]

    def test_a_live_marker_keeps_it_and_a_broken_marker_check_reads_as_live(self, cs, repos):
        work = repos["work"]
        _worktree(repos, "marked")

        def boom(_path):
            raise RuntimeError("marker reader broke")

        for check in (lambda _p: True, boom):
            report = cs.reap_worktrees(work, sessions=[], marker_live=check)
            assert report.kept == [("marked", "a session marker in it was touched recently")]

    def test_a_worktree_outside_claude_worktrees_is_never_touched(self, cs, repos):
        work = repos["work"]
        sibling = work.parent / "sibling-checkout"
        _git(work, "worktree", "add", "--quiet", "--detach", str(sibling), "origin/main")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == [] and report.kept == []
        assert sibling.is_dir() and _registered(work, sibling)

    def test_notes_are_saved_into_the_root_archive_and_never_overwrite(self, cs, repos):
        work = repos["work"]
        # As in the harness tree, the session state under cc/ is ignored, so
        # the notes do not make the worktree read as dirty.
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("cc/\n")
        wt = _worktree(repos, "noted")
        legs_wt = wt / "cc" / "blueprints" / "compact_summaries"
        legs_root = work / "cc" / "blueprints" / "compact_summaries"
        legs_wt.mkdir(parents=True)
        legs_root.mkdir(parents=True)
        (legs_wt / "aaa.md").write_text("worktree leg\n", encoding="utf-8")
        (legs_wt / "bbb.md").write_text("same\n", encoding="utf-8")
        (legs_root / "aaa.md").write_text("root leg\n", encoding="utf-8")
        (legs_root / "bbb.md").write_text("same\n", encoding="utf-8")
        (wt / "cc" / "_working_summary.md").write_text("the handoff notes\n", encoding="utf-8")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == ["noted"]
        assert (legs_root / "aaa.md").read_text(encoding="utf-8") == "root leg\n"
        assert (legs_root / "aaa.2.md").read_text(encoding="utf-8") == "worktree leg\n"
        assert (legs_root / "noted.working-summary.md").read_text(encoding="utf-8") == "the handoff notes\n"
        assert not (legs_root / "bbb.2.md").exists()
        assert sorted(report.saved) == ["cc/blueprints/compact_summaries/aaa.2.md",
                                        "cc/blueprints/compact_summaries/noted.working-summary.md"]

    def test_out_of_time_defers_the_removal(self, cs, repos, monkeypatch):
        work = repos["work"]
        wt = _worktree(repos, "later")
        monkeypatch.setattr(cs, "REMOVE_FLOOR_S", 1000.0)
        report = cs.reap_worktrees(work, sessions=[], deadline=time.monotonic() + 30)
        assert report.deferred == ["later"] and wt.is_dir()
        assert "1 more next session (out of time): later" in cs.worktrees_line(report)

    def test_a_half_written_entry_of_a_crashed_session_is_skipped(self, cs, repos, tmp_path):
        work = repos["work"]
        wt = _worktree(repos, "after-crash")
        cfg = tmp_path / "cfg"
        (cfg / "sessions").mkdir(parents=True)
        (cfg / "sessions" / f"{_dead_pid()}.json").write_text('{"pid": 1', encoding="utf-8")
        sessions = cs.live_sessions(cfg)
        assert sessions == []
        assert cs.reap_worktrees(work, sessions=sessions).removed == ["after-crash"]
        assert not wt.exists()

    def test_a_removal_git_refuses_is_reported_not_assumed(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "stubborn")

        def spawner(argv, *, cwd, wait, kill):
            if argv[1:3] == ["worktree", "remove"]:
                return cs.Spawned(done=True, returncode=1, stderr="fatal: refused for the test\n")
            return cs.spawn(argv, cwd=cwd, wait=wait, kill=kill)

        report = cs.reap_worktrees(work, sessions=[], spawner=spawner)
        assert report.removed == []
        assert report.kept == [("stubborn", "git did not remove it: fatal: refused for the test")]
        assert wt.is_dir()

    def test_a_removal_still_running_at_its_wait_is_never_killed(self, cs, repos):
        work = repos["work"]
        _worktree(repos, "slow")
        kills = []

        def spawner(argv, *, cwd, wait, kill):
            if argv[1:3] == ["worktree", "remove"]:
                kills.append(kill)
                return cs.Spawned(done=False, pid=5151)
            return cs.spawn(argv, cwd=cwd, wait=wait, kill=kill)

        report = cs.reap_worktrees(work, sessions=[], spawner=spawner)
        assert kills == [False]
        assert report.kept == [("slow", "its removal is still running (git pid 5151); it finishes on its own")]

    def test_an_ignored_file_git_status_cannot_see_keeps_the_worktree(self, cs, repos):
        """`git worktree remove` deletes ignored files without --force, and
        `status --porcelain` does not list them: a TP-*.md draft (ignored on
        this tree) was deleted under "merged, clean" in the review's probe."""
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("TP-*.md\n__pycache__/\n")
        wt = _worktree(repos, "draft")
        (wt / "TP-480.md").write_text("a draft\n", encoding="utf-8")
        (wt / "__pycache__").mkdir()
        (wt / "__pycache__" / "x.pyc").write_bytes(b"\0")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == [] and (wt / "TP-480.md").is_file()
        assert report.kept[0][1].startswith("1 ignored file git status cannot see (TP-480.md)")

    def test_caches_alone_do_not_keep_it(self, cs, repos):
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("__pycache__/\n.pytest_cache/\n")
        wt = _worktree(repos, "cached")
        for d in ("__pycache__", ".pytest_cache"):
            (wt / d).mkdir()
            (wt / d / "f").write_bytes(b"\0")
        assert cs.reap_worktrees(work, sessions=[]).removed == ["cached"]

    @pytest.mark.parametrize("same, removed", [(True, True), (False, False)])
    def test_a_worktreeinclude_copy_goes_only_when_identical_to_the_roots(self, cs, repos, same, removed):
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write(".claude/settings.json\n")
        wt = _worktree(repos, "wired")
        for tree, body in ((work, "{}\n"), (wt, "{}\n" if same else '{"hooks": {}}\n')):
            (tree / ".claude").mkdir(parents=True, exist_ok=True)
            (tree / ".claude" / "settings.json").write_text(body, encoding="utf-8")
        report = cs.reap_worktrees(work, sessions=[])
        assert (report.removed == ["wired"]) is removed

    def test_a_plan_in_progress_in_an_unmerged_or_dirty_worktree_keeps_it(self, cs, repos):
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("cc/\n")
        ahead = _worktree(repos, "planning", "lane/planning")
        _identity(ahead)
        _commit(ahead, "lane.txt")
        dirty = _worktree(repos, "dirty-plan")
        (dirty / "README.md").write_text("changed\n", encoding="utf-8")
        for wt in (ahead, dirty):
            (wt / "cc").mkdir()
            (wt / "cc" / "execution_plan.json").write_text('{"status": "in_progress"}', encoding="utf-8")
        report = cs.reap_worktrees(work, sessions=[])
        assert sorted(report.kept) == [("dirty-plan", "a plan in it is still in progress"),
                                       ("planning", "a plan in it is still in progress")], report

    def test_a_plan_left_open_in_a_merged_clean_worktree_is_named_and_removed(self, cs, repos):
        """DEF-4047: the work worktree's lane merged as #322 with its plan's
        last step still running, and every banner for six days kept it as a
        plan in progress. A merged lane with a clean tree is finished work
        whatever its plan says; the plan is saved with the cc/ state and the
        removal names it."""
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("cc/\n")
        wt = _worktree(repos, "finished", "lane/finished")
        (wt / "cc").mkdir()
        plan = '{"status": "in_progress", "steps": [{"status": "running"}]}'
        (wt / "cc" / "execution_plan.json").write_text(plan, encoding="utf-8")
        dry = cs.reap_worktrees(work, sessions=[], dry_run=True)
        assert dry.would_remove == ["finished (its plan was never closed; the lane merged)"], dry
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == ["finished (its plan was never closed; the lane merged)"], report
        assert not wt.exists() and not _registered(work, wt)
        assert report.saved == ["cc/blueprints/from-worktrees/finished/execution_plan.json"], report.saved
        assert (work / report.saved[0]).read_text(encoding="utf-8") == plan
        assert "finished (its plan was never closed; the lane merged)" in cs.worktrees_line(report)

    def test_another_live_session_in_the_root_removes_nothing(self, cs, repos):
        """A session that entered a worktree mid-session may still read as
        being in the root (the review's B4): while one is live there, the
        reaper stands down."""
        work = repos["work"]
        wt = _worktree(repos, "fresh")
        report = cs.reap_worktrees(work, sessions=[], held_by_other="pid 4242")
        assert report.removed == [] and wt.is_dir()
        assert report.note.startswith("another live session is in this checkout (pid 4242)")

    def test_a_tail_capped_marker_cwd_inside_the_worktree_keeps_it(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "entered")
        report = cs.reap_worktrees(work, sessions=[{"pid": None, "session_id": "m",
                                                    "cwd": ".../.claude/worktrees/entered/src"}])
        assert report.kept == [("entered", "a live Claude session is in it")] and wt.is_dir()

    def test_a_dry_run_never_prunes(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "gone-dry")
        shutil.rmtree(wt)
        report = cs.reap_worktrees(work, sessions=[], dry_run=True)
        assert report.would_remove == ["gone-dry (folder already gone)"]
        assert "gone-dry" in _out(work, "worktree", "list")

    def test_the_prune_is_not_run_when_a_registration_outside_would_go_too(self, cs, repos):
        work = repos["work"]
        ours = _worktree(repos, "gone-ours")
        outside = work.parent / "elsewhere"
        _git(work, "worktree", "add", "--quiet", "--detach", str(outside), "origin/main")
        shutil.rmtree(ours)
        shutil.rmtree(outside)
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept[0][0] == "gone-ours" and "not run" in report.kept[0][1]
        listing = _out(work, "worktree", "list")
        assert "gone-ours" in listing and "elsewhere" in listing

    def test_a_folder_whose_git_link_is_missing_is_kept(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "unlinked")
        (wt / ".git").unlink()
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == [] and wt.is_dir()
        assert "link is missing" in report.kept[0][1]

    @pytest.mark.skipif(os.name != "nt", reason="the rename probe is Windows-only")
    def test_a_folder_a_process_holds_open_is_kept_on_windows(self, cs, repos):
        """The review's W11: a terminal or editor in a merged worktree is no
        Claude session, so the registry cannot see it; Windows refuses to
        rename a folder that is a process's cwd."""
        work = repos["work"]
        wt = _worktree(repos, "held")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(wt))
        try:
            time.sleep(0.5)
            report = cs.reap_worktrees(work, sessions=[])
        finally:
            child.kill()
            child.wait(timeout=10)
        assert report.kept == [("held", "a process has it open (Windows refused to rename it)")]
        assert wt.is_dir() and _registered(work, wt)

    @pytest.mark.skipif(os.name != "posix", reason="the cwd reader is the POSIX arm (Windows has its rename probe)")
    def test_a_folder_a_process_works_in_is_kept_and_its_pid_named(self, cs, repos):
        """DEF-4079: a nohup'd run whose session ended is no Claude session and
        leaves no marker, and a rename succeeds under it off Windows; its
        working directory in a merged, clean worktree is what keeps it."""
        work = repos["work"]
        wt = _worktree(repos, "running")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(wt))
        try:
            time.sleep(0.5)
            report = cs.reap_worktrees(work, sessions=[])
        finally:
            child.kill()
            child.wait(timeout=10)
        assert report.removed == [] and wt.is_dir() and _registered(work, wt), report
        assert report.kept == [("running", f"a process works in it (pid {child.pid})")], report.kept
        assert f"running [a process works in it (pid {child.pid})]" in cs.worktrees_line(report)

    @pytest.mark.skipif(os.name != "posix", reason="the cwd reader is the POSIX arm (Windows has its rename probe)")
    @pytest.mark.skipif(os.name != "posix", reason="the cwd reader is the POSIX arm (Windows has its rename probe)")
    def test_a_dry_run_names_a_held_worktree_as_kept(self, cs, repos):
        """seat.py's list and retire read the dry run: it says what the real run does."""
        work = repos["work"]
        wt = _worktree(repos, "busy")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(wt))
        try:
            time.sleep(0.5)
            report = cs.reap_worktrees(work, sessions=[], dry_run=True)
        finally:
            child.kill()
            child.wait(timeout=10)
        assert report.would_remove == [] and report.kept == [("busy", f"a process works in it (pid {child.pid})")]

    def test_the_process_table_is_read_once_and_only_at_a_removal(self, cs, repos, monkeypatch):
        work = repos["work"]
        _worktree(repos, "one")
        _worktree(repos, "two")
        dirty = _worktree(repos, "dirty")
        (dirty / "README.md").write_text("changed\n", encoding="utf-8")
        reads: list = []
        monkeypatch.setattr(cs, "process_cwds", lambda pids=None, **kw: reads.append(pids) or {})
        report = cs.reap_worktrees(work, sessions=[])
        # Windows proves an open cwd by its rename probe and reads no table.
        once = [None] if os.name != "nt" else []
        assert sorted(report.removed) == ["one", "two"] and reads == once, (report, reads)
        reads.clear()
        cs.reap_worktrees(work, sessions=[])
        assert reads == [], "a worktree kept before the removal stage reads no table"

    @pytest.mark.skipif(os.name != "posix", reason="the cwd reader is the POSIX arm (Windows has its rename probe)")
    def test_a_table_the_reader_could_not_read_keeps_it(self, cs, repos, monkeypatch):
        work = repos["work"]
        wt = _worktree(repos, "unread")
        monkeypatch.setattr(cs, "process_cwds", lambda pids=None, **kw: None)
        report = cs.reap_worktrees(work, sessions=[])
        assert report.kept == [("unread", "the process table could not be read, so a run in it cannot be ruled out")]
        assert wt.is_dir()

    def test_a_worktree_whose_folder_is_gone_is_pruned(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "vanished")
        shutil.rmtree(wt)
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == ["vanished (folder already gone)"]
        assert not _registered(work, wt)

    def test_a_dry_run_removes_nothing(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "dry")
        report = cs.reap_worktrees(work, sessions=[], dry_run=True)
        assert report.would_remove == ["dry"] and wt.is_dir()


# -- the SessionStart wiring -------------------------------------------------------

HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _seeded_with_tools_cc(repos, ignore: str = ".espalier-state/") -> None:
    """``tools/cc`` committed on origin's main and fetched into work, with the
    state directory ignored as ``init``'s block ignores it (or by ``ignore``):
    the guard can then run in a worktree, and the worktree reads clean once
    its edit is restored."""
    from tests._live_tree import copy_checkout

    seed, work = repos["seed"], repos["work"]
    # git's view of tools/cc, never the filesystem's (the live-tree ratchet)
    copy_checkout(REPO_ROOT / "tools" / "cc", seed / "tools" / "cc", ignore=shutil.ignore_patterns("__pycache__"))
    (seed / ".gitignore").write_bytes(f"{ignore}\n__pycache__/\n".encode("utf-8"))
    _git(seed, "add", "-A")
    _git(seed, "commit", "--quiet", "-m", "tools/cc")
    _git(seed, "push", "--quiet", "origin", "main")
    _git(work, "fetch", "--quiet", "origin")


def _wedge_restore(wt: Path) -> tuple[bytes, list[Path]]:
    """In ``wt``: the uncommitted edit that wedges the guard (a raise appended
    to a sibling it imports), the guard asked about the restore it lets
    through (it saves the copy first), then the restore run, as the Bash tool
    would. Returns the edited bytes and the copies the guard wrote."""
    reinject = wt / "tools" / "cc" / "hooks" / "_reinject.py"
    edited = reinject.read_bytes() + b"\nraise KeyError(1)\n"
    reinject.write_bytes(edited)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(CLAUDE_PROJECT_DIR=str(wt), PYTHONDONTWRITEBYTECODE="1")
    payload = {"tool_name": "Bash", "cwd": str(wt),
               "tool_input": {"command": "git restore --source=HEAD -- tools/cc/hooks/_reinject.py"}}
    guard = subprocess.run([HOOK_PYTHON, str(wt / "tools" / "cc" / "hooks" / "write_guard.py")],
                           input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=wt, env=env, timeout=scaled(50))
    assert guard.returncode == 0, guard.stderr
    copies = sorted(wt.rglob("*.py.txt"))
    _git(wt, "restore", "--source=HEAD", "--", "tools/cc/hooks/_reinject.py")
    return edited, copies


class TestTheReaperKeepsAWedgeRestoreCopy:
    """DEF-3009: the one copy of the edit a wedge restore discards is saved
    under ``.espalier-state/wedge-restore/``, which the reaper read as state
    (a cache) and its ignored listing collapsed unread, so a clean, merged
    worktree was removed at the next fresh session with the copy inside it
    (driven 2026-10-17 at e336012: "removed 1 leftover (merged, clean)", the
    copy gone). The worktree is now kept, the copy named, until it is read.
    Earned red: the rows that drive the guard, the beside-other-state row,
    the spelling pin and the new helper's own rows fail on main; the two
    rows that remove hold on both."""

    def test_a_wedge_restore_copy_keeps_the_worktree_and_is_named(self, cs, repos):
        work = repos["work"]
        _seeded_with_tools_cc(repos)
        wt = _worktree(repos, "wedged")
        edited, copies = _wedge_restore(wt)
        assert len(copies) == 1 and copies[0].read_bytes() == edited, copies
        assert _out(wt, "status", "--porcelain") == ""
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == [] and copies[0].is_file(), report
        rel = copies[0].relative_to(wt).as_posix()
        (name, reason), = report.kept
        assert name == "wedged"
        assert reason == (f"1 saved edit a wedge restore discarded (.claude/worktrees/wedged/{rel}): read it, "
                          "keep what you need, then delete it"), reason
        assert f"wedged [{reason}]" in cs.worktrees_line(report)

    def test_a_copy_beside_other_state_is_still_found(self, cs, repos):
        """The state directory's other files (a session marker) are still a
        cache: the copy is named alone, and the line counts nothing else."""
        work = repos["work"]
        _seeded_with_tools_cc(repos)
        wt = _worktree(repos, "busy")
        _edited, copies = _wedge_restore(wt)
        (wt / ".espalier-state" / "sessions").mkdir(parents=True)
        (wt / ".espalier-state" / "sessions" / "s.json").write_text("{}\n", encoding="utf-8")
        report = cs.reap_worktrees(work, sessions=[])
        (_name, reason), = report.kept
        assert reason.startswith(
            "1 saved edit a wedge restore discarded (.claude/worktrees/busy/.espalier-state/wedge-restore/")
        assert "other ignored file" not in reason and copies[0].is_file()

    def test_two_copies_and_another_ignored_file_are_counted(self, cs, repos):
        """The plural reason and the other ignored files' count, in full."""
        work = repos["work"]
        _seeded_with_tools_cc(repos)
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("notes.txt\n")
        wt = _worktree(repos, "many")
        kept = wt / ".espalier-state" / "wedge-restore"
        kept.mkdir(parents=True)
        for name in ("_reinject-20261017T000000000001Z.py.txt", "_hook_utils-20261017T000000000002Z.py.txt"):
            (kept / name).write_bytes(b"edited\n")
        (wt / "notes.txt").write_text("mine\n", encoding="utf-8")
        (_name, reason), = cs.reap_worktrees(work, sessions=[]).kept
        here = ".claude/worktrees/many/.espalier-state/wedge-restore"
        assert reason == (f"2 saved edits a wedge restore discarded ({here}/_hook_utils-20261017T000000000002Z.py.txt, "
                          f"{here}/_reinject-20261017T000000000001Z.py.txt): read them, keep what you need, then "
                          "delete them (1 other ignored file too)"), reason

    @pytest.mark.parametrize("ignore", [".espalier-state/", ".espalier-state/*"])
    def test_the_copy_counts_once_and_its_empty_folder_holds_nothing(self, cs, repos, ignore):
        """The failure-mode review, driven: a hand-written spelling listed the
        state directory and the saved-edit folder both, naming the copy twice;
        and once the copy was deleted, as the reason says, the empty folder
        still kept the worktree."""
        work = repos["work"]
        _seeded_with_tools_cc(repos, ignore=ignore)
        wt = _worktree(repos, "once")
        _edited, copies = _wedge_restore(wt)
        (_name, reason), = cs.reap_worktrees(work, sessions=[]).kept
        assert reason.startswith("1 saved edit a wedge restore discarded ("), reason
        copies[0].unlink()
        assert cs.reap_worktrees(work, sessions=[]).removed == ["once"]

    def test_every_worktree_holding_a_copy_is_named_on_the_line(self, cs):
        """The failure-mode review, driven: with four kept, the line showed
        three and "and 1 more", the copy-holder among the hidden."""
        notes = "1 ignored file git status cannot see (notes.md); move what you need"
        copy = "1 saved edit a wedge restore discarded (.claude/worktrees/zz/x): read it"
        report = cs.Reap(kept=[("a", notes), ("b", notes), ("c", notes), ("d", notes), ("zz", copy)])
        line = cs.worktrees_line(report)
        assert line.startswith(f"kept 5: zz [{copy}], a [{notes}]"), line
        assert line.endswith("and 1 more"), line

    def test_other_state_alone_does_not_keep_it(self, cs, repos):
        work = repos["work"]
        _seeded_with_tools_cc(repos)
        wt = _worktree(repos, "plain")
        (wt / ".espalier-state" / "sessions").mkdir(parents=True)
        (wt / ".espalier-state" / "sessions" / "s.json").write_text("{}\n", encoding="utf-8")
        assert cs.reap_worktrees(work, sessions=[]).removed == ["plain"]

    @pytest.mark.parametrize("rel", ["hooks/_reinject.py", "checkout_sync.py"])
    def test_a_copy_its_file_still_holds_does_not_keep_it(self, cs, repos, rel):
        """The copy is written before the permission prompt. Declined, the
        restore never runs and the edit stays; committed and merged, the copy
        holds nothing the branch does not, so it does not hold the worktree.
        A restore can name a file in tools/cc/ or in tools/cc/hooks/: both."""
        work = repos["work"]
        _seeded_with_tools_cc(repos)
        wt = _worktree(repos, "declined")
        held = (wt / "tools" / "cc" / rel).read_bytes()
        stem = rel.rsplit("/", 1)[-1][: -len(".py")]
        (wt / ".espalier-state" / "wedge-restore").mkdir(parents=True)
        (wt / ".espalier-state" / "wedge-restore" / f"{stem}-20261017T000000000000Z.py.txt").write_bytes(held)
        assert cs.reap_worktrees(work, sessions=[]).removed == ["declined"]

    @pytest.mark.parametrize("name, body", [
        ("_reinject-20261017T000000000000Z.py.txt", None),          # unreadable (absent)
        ("_reinject.py.txt", b"x"),                                  # the writer's shape lacks its stamp
        ("_reinject-20261017T000000000000Z.txt", b"x"),             # nor its suffix
        ("_no_such_stem-20261017T000000000000Z.py.txt", b"x"),      # no file of its name
        ("_reinject-20261017T000000000000Z.py.txt", b"y"),          # its file, other bytes
    ])
    def test_a_copy_that_cannot_be_matched_to_its_file_is_kept(self, cs, tmp_path, name, body):
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "hooks" / "_reinject.py").write_bytes(b"x")
        rel = f".espalier-state/wedge-restore/{name}"
        if body is not None:
            (tmp_path / rel).parent.mkdir(parents=True)
            (tmp_path / rel).write_bytes(body)
        assert cs._held_by_its_file(tmp_path, rel) is False

    def test_the_reapers_spelling_is_the_writers(self, cs, tmp_path):
        """Derived, not copied: the writer is driven, and the path it writes
        is a saved edit to the reaper, never a cache."""
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "tools" / "cc" / "hooks" / "_hook_utils.py", hooks / "_hook_utils.py")
        (hooks / "_reinject.py").write_bytes(b"edited\n")
        sr = _load(REPO_ROOT / "tools" / "cc" / "hooks" / "_start_refusal.py", "start_refusal_under_test")
        said = sr._save_before_restore(hooks / "_reinject.py", tmp_path / "tools" / "cc")
        copy, = (tmp_path / ".espalier-state").rglob("*.py.txt")
        rel = copy.relative_to(tmp_path).as_posix()
        assert rel in said and cs._disposable(rel) is False and cs._held_by_its_file(tmp_path, rel) is True
        assert cs._KEPT_STATE_REL == f"{sr._state_dir_from_source(tmp_path / 'tools' / 'cc')}/wedge-restore"


@pytest.fixture(scope="module")
def ss():
    return _load(HOOKS_DIR / "session_start.py", "_ss_checkout_sync_wiring")




class TestSessionStartWiring:
    @pytest.mark.parametrize("toml, self_host, env, expected", [
        (None, True, None, True),                               # self-host default
        (None, False, None, False),                             # adopter default
        ("session_catch_up = true\n", False, None, True),       # adopter opts in
        ("session_catch_up = false\n", True, None, False),      # self-host opts out
        ('session_catch_up = "yes"\n', False, None, False),     # not a boolean: the default
        ("session_catch_up = true\n", True, "0", False),        # the env switch wins
        (None, False, "1", True),
    ])
    def test_the_switch_reads_env_then_toml_then_the_default(self, ss, tmp_path, monkeypatch,
                                                             toml, self_host, env, expected):
        if toml is not None:
            (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
        if env is None:
            monkeypatch.delenv(ss.CATCH_UP_ENV, raising=False)
        else:
            monkeypatch.setenv(ss.CATCH_UP_ENV, env)
        assert ss._catch_up_enabled(tmp_path, self_host) is expected

    @pytest.mark.parametrize("source", ["resume", "compact", ""])
    def test_a_continuing_session_never_moves_the_tree(self, ss, repos, monkeypatch, source):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        monkeypatch.setenv(ss.CATCH_UP_ENV, "1")
        before = _out(work, "rev-parse", "HEAD")
        assert ss._sync_checkout(work, {"cwd": str(work)}, "s1", source, True, None) == ("", "", [])
        assert _out(work, "rev-parse", "HEAD") == before

    @staticmethod
    def _drive(work: Path, tmp_path: Path, entries: list[dict]):
        """The hook as Claude Code runs it on a fresh session, against a
        fixture registry; HOME moved so the real ~/.claude/sessions is never
        read (the reader also looks at the default location)."""
        from tests.test_hooks import run_hook

        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "source": "startup", "session_id": "t-catch-up",
             "cwd": str(work)},
            {"CLAUDE_PROJECT_DIR": str(work), "ESPALIER_SESSION_CATCH_UP": "1",
             "CLAUDE_CONFIG_DIR": str(_registry(tmp_path, entries)), "HOME": str(home),
             "USERPROFILE": str(home)},
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_the_whole_hook_catches_a_merged_checkout_up_and_says_so(self, repos, tmp_path):
        """The banner's Branch: line already reads main, because the catch-up
        ran first."""
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"], 2)
        leftover = _worktree(repos, "agent-old", "lane/agent-old")
        banner = self._drive(work, tmp_path, [{"pid": os.getpid(), "sessionId": "t-catch-up", "cwd": str(work)}])
        assert "Checkout:  caught up -- left lane/x (merged, branch deleted); main fast-forwarded" in banner
        assert "Worktrees: removed 1 leftover (merged, clean): agent-old" in banner
        assert banner.index("Status:") < banner.index("Checkout:") < banner.index("Worktrees:")
        assert "Branch:    main" in banner
        assert _out(work, "rev-parse", "HEAD") == _out(work, "rev-parse", "origin/main")
        assert not leftover.exists()

    def test_a_registry_without_this_session_reaps_nothing(self, repos, tmp_path):
        """A registry that does not list the session asking is not the one
        it writes to (another config dir, a moved file, a new shape), so
        nothing it fails to list is trusted absent."""
        work = repos["work"]
        leftover = _worktree(repos, "agent-old", "lane/agent-old")
        banner = self._drive(work, tmp_path, [{"pid": _dead_pid(), "sessionId": "someone-else",
                                               "cwd": str(work)}])
        assert ("Worktrees: this session is not in Claude Code's session registry, so no worktree was "
                "removed: agent-old") in banner
        assert leftover.is_dir()

    def test_an_unread_process_table_is_said_and_a_kept_older_reader_keeps_its_words(self, ss, repos,
                                                                                      monkeypatch):
        """The catch-up places the session by its id, then by its parents: a
        table that could not be read matched none of them, which says nothing
        about the registry (DEF-2046). A kept older checkout_sync, with no
        find_own_entry, keeps the older words and the hook."""
        work = repos["work"]
        _worktree(repos, "agent-old", "lane/agent-old")
        monkeypatch.setenv(ss.CATCH_UP_ENV, "1")
        sync = ss._hook_utils.load_checkout_sync()
        monkeypatch.setattr(sync, "live_sessions", lambda *a, **k: [_row(work, pid=_dead_pid(), sid="someone")])
        monkeypatch.setattr(sync, "_parent_map", lambda *a, **k: None)
        _checkout, worktrees, _kept = ss._sync_checkout(work, {"cwd": str(work)}, "s1", "startup", True, None)
        assert worktrees == ("the process table could not be read, so this session could not be found in Claude "
                             "Code's session registry, so no worktree was removed: agent-old"), worktrees

        class _KeptOlder:   # its own_entry answers; the names this change added are not in it
            def __getattr__(self, name):
                if name in ("find_own_entry", "find_caller", "TABLE_UNREAD", "NOT_LISTED", "ancestry"):
                    raise AttributeError(name)
                return getattr(sync, name)

        monkeypatch.setattr(ss._hook_utils, "load_checkout_sync", _KeptOlder)
        _checkout, worktrees, _kept = ss._sync_checkout(work, {"cwd": str(work)}, "s1", "startup", True, None)
        assert worktrees == ("this session is not in Claude Code's session registry, so no worktree was removed: "
                             "agent-old"), worktrees

    def test_the_catch_up_places_the_others_by_the_entry_it_found(self, ss, repos, monkeypatch):
        work = repos["work"]
        _worktree(repos, "agent-old", "lane/agent-old")
        monkeypatch.setenv(ss.CATCH_UP_ENV, "1")
        sync = ss._hook_utils.load_checkout_sync()
        walks = iter([([4242], True)])
        monkeypatch.setattr(sync, "ancestry", lambda depth=8: next(walks, ([], False)))
        monkeypatch.setattr(sync, "live_sessions", lambda *a, **k: [_row(work, pid=4242, sid="me")])
        _checkout, worktrees, _kept = ss._sync_checkout(work, {"cwd": str(work)}, "s1", "startup", True, None)
        assert "pid 4242" not in worktrees, worktrees

    def test_the_banner_renders_both_lines_and_stays_byte_identical_without_them(self, ss, tmp_path):
        plain = ss._build_context(tmp_path, False, False)
        assert "Checkout:" not in plain and "Worktrees:" not in plain
        shown = ss._build_context(tmp_path, False, False, checkout="caught up -- x", worktrees="removed 1: a")
        assert "Status:" in shown
        after_status = shown.split("Status:", 1)[1]
        assert after_status.index("Checkout:  caught up -- x\n") < after_status.index("Worktrees: removed 1: a\n")
        assert shown.replace("Checkout:  caught up -- x\n", "").replace("Worktrees: removed 1: a\n", "") == plain


# -- the pieces --------------------------------------------------------------------

class TestPieces:
    def test_plan_in_progress_reads_the_merge_beside_the_tree(self, cs, tmp_path):
        """DEF-4047: the keep rule takes the lane's state beside the plan."""
        tree = tmp_path / "t"
        assert cs.plan_in_progress(tree) is False and cs.plan_in_progress(tree, merged_and_clean=True) is False
        (tree / "cc").mkdir(parents=True)
        plan = tree / "cc" / "execution_plan.json"
        for body, open_ in (('{"status": "in_progress"}', True), ("not json", True), ('{"status": "complete"}', False)):
            plan.write_text(body, encoding="utf-8")
            assert cs.plan_in_progress(tree) is open_, body
            assert cs.plan_in_progress(tree, merged_and_clean=True) is False, body

    def test_pid_alive_answers_for_this_process_a_finished_one_and_non_pids(self, cs):
        assert cs.pid_alive(os.getpid()) is True
        assert cs.pid_alive(_dead_pid()) is False
        for not_a_pid in (0, -1, True, "123", None):
            assert cs.pid_alive(not_a_pid) is False

    @pytest.mark.skipif(os.name != "nt", reason="os.kill(pid, 0) is CTRL_C_EVENT only on Windows")
    def test_pid_alive_never_signals_on_windows(self, cs, monkeypatch):
        def boom(*_a):
            raise AssertionError("os.kill would send CTRL_C_EVENT on Windows")

        monkeypatch.setattr(os, "kill", boom)
        assert cs.pid_alive(os.getpid()) is True

    def test_the_registry_reader_reads_claude_config_dir_and_the_default(self, cs, tmp_path, monkeypatch):
        """A nested session launched with CLAUDE_* stripped registers under
        ~/.claude even when its parent's CLAUDE_CONFIG_DIR points elsewhere:
        the reader reads both."""
        cfg = _registry(tmp_path, [{"pid": os.getpid(), "sessionId": "s1", "cwd": str(tmp_path)}])
        home = tmp_path / "home"
        (home / ".claude" / "sessions").mkdir(parents=True)
        (home / ".claude" / "sessions" / "x.json").write_text(
            json.dumps({"pid": os.getpid(), "sessionId": "s2", "cwd": str(home)}), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("HOME", str(home))
        assert cs.claude_config_dir() == cfg
        bare = {"kind": "", "entrypoint": "", "started_at": None}
        assert cs.live_sessions() == [{"pid": os.getpid(), "session_id": "s1", "cwd": str(tmp_path), **bare},
                                      {"pid": os.getpid(), "session_id": "s2", "cwd": str(home), **bare}]

    def test_only_the_nearest_ancestor_in_the_registry_is_the_caller(self, cs, tmp_path):
        """A session launched from another session (a nested `claude -p`) has
        both as ancestors; only the nearer is the caller, and the farther one
        is another session in the checkout (the review's W4)."""
        ancestors, read = cs.ancestry()
        if not read:
            pytest.skip("the process table did not answer on this host, so the walk cannot tell")
        assert len(ancestors) >= 2, ancestors
        near, far = ancestors[0], ancestors[1]
        rows = [{"pid": far, "session_id": "parent", "cwd": str(tmp_path)},
                {"pid": near, "session_id": "child", "cwd": str(tmp_path)}]
        assert cs.own_entry(rows) is rows[1]
        assert cs.other_sessions_in_checkout(rows, tmp_path) == [rows[0]]
        assert cs.own_entry(rows, "parent") is rows[0]

    @staticmethod
    def _registered(cs, monkeypatch, tmp_path, *pids: int) -> None:
        directory = tmp_path / "cfg" / "sessions"
        directory.mkdir(parents=True)
        for pid in pids:
            (directory / f"{pid}.json").write_text(json.dumps({"pid": pid, "cwd": "x"}), encoding="utf-8")
        monkeypatch.setattr(cs, "claude_config_dirs", lambda: [tmp_path / "cfg"])

    def test_the_window_is_the_registered_parent(self, cs, monkeypatch, tmp_path):
        """The measured macOS shape: the hook's parent is Claude Code itself,
        answered with no process-table read."""
        self._registered(cs, monkeypatch, tmp_path, 4242)
        monkeypatch.setattr(cs.os, "getppid", lambda: 4242)
        monkeypatch.setattr(cs, "_process_table_windows", lambda: pytest.fail("the table was read"))
        assert cs.window_pid() == 4242

    def test_the_window_steps_over_one_venv_launcher(self, cs, monkeypatch, tmp_path):
        """The measured Windows shape: hook <- venv python.exe <- claude.exe,
        the launcher exiting with the hook. Dies to: keeping the parent (the
        key every clear missed on Windows before)."""
        self._registered(cs, monkeypatch, tmp_path, 300)
        monkeypatch.setattr(cs.os, "getppid", lambda: 100)
        for launcher in ("python.exe", "pythonw.exe", "py.exe", "Python3.12.exe"):
            assert cs.window_pid({100: (300, launcher)}) == 300, launcher

    def test_a_leftover_entry_that_is_not_this_process_names_no_window(self, cs, monkeypatch, tmp_path):
        """A marker's window pid is now read by its exit, so a crashed
        session's file must not make a reused pid (a launcher) a window
        (failure-mode review, S3). Dies to: counting the file alone."""
        directory = tmp_path / "cfg" / "sessions"
        directory.mkdir(parents=True)
        monkeypatch.setattr(cs, "claude_config_dirs", lambda: [tmp_path / "cfg"])
        monkeypatch.setattr(cs.os, "getppid", lambda: 4242)
        monkeypatch.setattr(cs, "_process_table_windows", lambda: {})
        (directory / "4242.json").write_text(json.dumps({"pid": 99, "cwd": "x"}), encoding="utf-8")
        assert cs.window_pid() is None                                    # another pid's entry
        (directory / "4242.json").write_text("{not json", encoding="utf-8")
        assert cs.window_pid() is None                                    # no answer
        (directory / "4242.json").write_text(json.dumps({"pid": 4242, "cwd": "x"}), encoding="utf-8")
        assert cs.window_pid() == 4242

    @pytest.mark.skipif(os.name != "nt", reason="procStart is measured against the Windows creation FILETIME")
    def test_an_entry_whose_creation_time_is_another_process_names_no_window(self, cs, monkeypatch, tmp_path):
        directory = tmp_path / "cfg" / "sessions"
        directory.mkdir(parents=True)
        monkeypatch.setattr(cs, "claude_config_dirs", lambda: [tmp_path / "cfg"])
        me = os.getpid()
        monkeypatch.setattr(cs.os, "getppid", lambda: me)
        record = {"pid": me, "cwd": "x", "procStart": "1"}
        (directory / f"{me}.json").write_text(json.dumps(record), encoding="utf-8")
        monkeypatch.setattr(cs, "_process_table_windows", lambda: {})
        assert cs.window_pid() is None
        record["procStart"] = cs._proc_start_windows(me)
        (directory / f"{me}.json").write_text(json.dumps(record), encoding="utf-8")
        assert cs.window_pid() == me

    def test_the_window_never_walks_past_one_step(self, cs, monkeypatch, tmp_path):
        """A hook a test suite spawns sits under pytest and a shell, with the
        session running the suite further up: a walk to the nearest
        registered ancestor would key the test's markers to that session.
        Dies to: a walk."""
        self._registered(cs, monkeypatch, tmp_path, 300)
        monkeypatch.setattr(cs.os, "getppid", lambda: 100)
        assert cs.window_pid({100: (200, "python.exe"), 200: (300, "bash.exe")}) is None
        assert cs.window_pid({100: (300, "bash.exe")}) is None          # not a launcher: no step
        assert cs.window_pid({}) is None                                 # an unreadable table
        assert cs.window_pid({100: (0, "python.exe")}) is None

    def test_sessions_in_checkout_leave_out_worktree_sessions(self, cs, tmp_path):
        root = tmp_path / "repo"
        rows = [{"cwd": str(root)}, {"cwd": str(root / "src")},
                {"cwd": str(root / ".claude" / "worktrees" / "a")}, {"cwd": str(tmp_path / "other")}]
        assert cs.sessions_in_checkout(rows, root) == rows[:2]

    def test_the_lines_are_ascii_and_cap_the_names(self, cs):
        report = cs.Reap(removed=[f"wt{i}" for i in range(5)], kept=[("x", "1 commit(s) not in main (lane/x)")])
        line = cs.worktrees_line(report)
        assert line.isascii()
        assert "removed 5 leftovers (merged, clean): wt0, wt1, wt2, and 2 more" in line
        assert "kept 1: x [1 commit(s) not in main (lane/x)]" in line
        assert cs.worktrees_line(cs.Reap()) == ""
        assert cs.checkout_line(cs.CatchUp("current")) == ""

    def test_the_cli_dry_run_reports_and_moves_nothing(self, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        before = _out(work, "rev-parse", "HEAD")
        env = {**_git_env(), "CLAUDE_CONFIG_DIR": str(work.parent / "no-registry")}
        env.pop("CLAUDECODE", None)
        r = subprocess.run([HOOK_PYTHON, str(MODULE), "--root", str(work), "--json"], capture_output=True,
                           text=True, encoding="utf-8", env=env, timeout=30, cwd=str(work))
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert _out(work, "rev-parse", "HEAD") == before
        if not payload["checkout"]["fetched"]:
            # The fetch did not land inside FETCH_CAP_S (a loaded runner:
            # #452's windows-latest leg read `current` here), so the state is
            # the last fetch's and this test cannot tell (DEF-2046).
            pytest.skip("the CLI's fetch did not land inside its cap on this runner")
        assert payload["checkout"]["state"] == "would_catch_up"


# -- the one liveness oracle (TP-701 B-1) ----------------------------------------------

@pytest.mark.skipif(os.name != "posix", reason="the cwd reader is the POSIX arm; Windows reads nothing")
class TestTheProcessReader:
    """The one reader of where a process works (DEF-4070's, moved here from
    session_start for DEF-4078 and DEF-4079): the SessionStart Loose: line,
    the CP-KILL speed bump and held_open all read it."""

    def test_the_lsof_arm_reads_its_output_whatever_the_exit_code(self, cs, monkeypatch, tmp_path):
        monkeypatch.setattr(cs, "_PROC_ROOT", tmp_path / "no-proc")
        monkeypatch.setattr(cs.shutil, "which", lambda name, path=None: "/usr/sbin/lsof")
        seen = []

        def lsof(argv, *, cwd, timeout):
            seen.append((argv, cwd, timeout))
            # Exit 1: one listed pid could not be read (pid 1 is root's); the
            # rest still print, measured on macOS.
            return subprocess.CompletedProcess(argv, 1, "p71609\nfcwd\nn/a/b c\np72404\nfcwd\nn/c\nwarning\n", "")

        monkeypatch.setattr(cs, "run", lsof)
        assert cs.process_cwds([71609, 72404, 1], timeout=1.5) == {71609: "/a/b c", 72404: "/c"}
        assert cs.parse_lsof_cwds("p\u00b2\nn/x\np7\nn/y\n") == {7: "/y"}, "a non-ASCII digit is no pid"
        argv, cwd, timeout = seen[0]
        assert argv == ["/usr/sbin/lsof", "-w", "-a", "-d", "cwd", "-p", "71609,72404,1", "-Fn"]
        assert timeout == 1.5
        assert cwd == Path(os.path.abspath("/")), "lsof runs from the root, never from the folder asked about"
        seen.clear()
        assert cs.process_cwds([]) == {} and seen == [], "no pid: no spawn"
        cs.process_cwds(list(range(100, 100 + cs.CWD_PID_CAP + 8)))
        assert seen[0][0][6].split(",") == [str(p) for p in range(100, 100 + cs.CWD_PID_CAP)]
        seen.clear()
        cs.process_cwds(None)
        assert seen[0][0] == ["/usr/sbin/lsof", "-w", "-a", "-d", "cwd", "-Fn"], "every process: no -p"

    def test_an_lsof_that_cannot_answer_reads_as_unread_not_as_none(self, cs, monkeypatch, tmp_path):
        """None (the reader ran and failed) is not {} (nothing to read): a
        caller that removes on an empty answer must be able to tell them apart."""
        monkeypatch.setattr(cs, "_PROC_ROOT", tmp_path / "no-proc")
        monkeypatch.setattr(cs.shutil, "which", lambda name, path=None: "/usr/sbin/lsof")
        monkeypatch.setattr(cs, "run", lambda argv, *, cwd, timeout: None)
        assert cs.process_cwds([4242]) is None
        assert cs.process_cwds(None) is None
        monkeypatch.setattr(cs.shutil, "which", lambda name, path=None: None)
        monkeypatch.setattr(cs, "run", lambda *a, **k: pytest.fail("spawned with no lsof"))
        assert cs.process_cwds([4242]) == {} and cs.process_cwds(None) == {}

    def test_an_lsof_that_read_nothing_is_unread(self, cs, monkeypatch, tmp_path):
        """A failed run prints nothing, and a read of every process lists lsof
        itself at least: either empty answer is no answer, so held_open keeps."""
        monkeypatch.setattr(cs, "_PROC_ROOT", tmp_path / "no-proc")
        monkeypatch.setattr(cs.shutil, "which", lambda name, path=None: "/usr/sbin/lsof")
        for code in (1, 0):
            monkeypatch.setattr(cs, "run", lambda argv, *, cwd, timeout, code=code: subprocess.CompletedProcess(
                argv, code, "", ""))
            assert cs.process_cwds(None) is None, code
            assert cs.held_open(tmp_path) == "the process table could not be read, so a run in it cannot be ruled out"
        assert cs.process_cwds([4242]) == {}, "gone pids named by number read as none, an answer"
        monkeypatch.setattr(cs, "run", lambda argv, *, cwd, timeout: subprocess.CompletedProcess(argv, 1, "", ""))
        assert cs.process_cwds([4242]) is None, "a failed run is unread"

    def test_lsof_is_never_taken_from_the_checkout(self, cs, monkeypatch, tmp_path):
        """An empty or relative PATH entry is the hook's cwd, the checkout: a
        file named `lsof` there would run at every session start."""
        from tests._stubs import write_stub
        planted = write_stub(tmp_path / "lsof", "#!/bin/sh\nexit 0\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cs, "_LSOF_FALLBACK_DIRS", ())
        for path in ("", ":/nonexistent", ".", "relative/bin"):
            monkeypatch.setenv("PATH", path)
            assert cs.lsof_path() is None, path
        monkeypatch.setenv("PATH", f":{tmp_path}")
        assert cs.lsof_path() == str(planted), "an absolute entry still answers"

    def test_the_proc_arm_reads_each_cwd_link_with_no_spawn(self, cs, monkeypatch, tmp_path):
        proc = tmp_path / "proc"
        (proc / "self").mkdir(parents=True)
        os.symlink(str(tmp_path), proc / "self" / "cwd")
        (proc / "4242").mkdir()
        os.symlink("/a/b (deleted)", proc / "4242" / "cwd")
        (proc / "4301").mkdir()   # no cwd link to read: another user's process, or gone
        (proc / "net").mkdir()    # not a pid
        monkeypatch.setattr(cs, "_PROC_ROOT", proc)
        monkeypatch.setattr(cs, "run", lambda *a, **k: pytest.fail("the /proc arm spawned"))
        assert cs.process_cwds([4242, 4301]) == {4242: "/a/b (deleted)"}
        assert cs.process_cwds(None) == {4242: "/a/b (deleted)"}, "every process: each numbered entry"

    def test_the_live_reader_finds_this_process_cwd(self, cs):
        """The one live drive: whichever arm this host takes reads a real pid,
        by name and in the whole table."""
        got = cs.process_cwds([os.getpid()])
        if not got and not (cs._PROC_ROOT / "self" / "cwd").exists() and not cs.lsof_path():
            pytest.skip("this host has neither /proc cwd links nor lsof")
        assert os.path.realpath(got[os.getpid()]) == os.path.realpath(os.getcwd())
        every = cs.process_cwds(None)
        assert every is not None and os.path.realpath(every[os.getpid()]) == os.path.realpath(os.getcwd())

    def test_pid_checkout_names_this_checkout_another_and_neither(self, cs, repos, tmp_path):
        work = repos["work"]
        wt = _worktree(repos, "lane")
        (wt / "sub").mkdir()
        (tmp_path / "elsewhere").mkdir()
        assert cs.pid_checkout(str(work), work) == ("cwd in this checkout, the main checkout", False)
        assert cs.pid_checkout(str(wt), work) == (
            "cwd in .claude/worktrees/lane, another checkout of this clone", True)
        assert cs.pid_checkout(str(wt / "sub"), wt) == ("cwd in this checkout, .claude/worktrees/lane", False)
        assert cs.pid_checkout(str(work), wt) == ("cwd in the main checkout, another checkout of this clone", True)
        assert cs.pid_checkout(str(tmp_path / "elsewhere"), work) == ("cwd outside this clone's checkouts", False)
        assert cs.pid_checkout(f"{wt} (deleted)", work) == ("cwd deleted", False)
        assert cs.pid_checkout(str(tmp_path / "gone"), work) == ("cwd deleted", False)
        given = [work, wt]
        assert cs.pid_checkout(str(wt), work, given)[1] is True, "a given checkout list is read as given"
        assert cs.pid_checkout(str(wt), work, [])[1] is False, "a worktree the list does not hold is not one"

    def test_held_open_names_the_pids_working_in_the_folder_but_not_its_own(self, cs, tmp_path):
        folder = tmp_path / "wt"
        (folder / "sub").mkdir(parents=True)
        (tmp_path / "wt-two").mkdir()
        mine = os.getpid()
        assert cs.held_open(folder, lambda: {}) == ""
        assert cs.held_open(folder, lambda: {mine: str(folder)}) == "", "the caller's own cwd is judged by own_cwd"
        assert cs.held_open(folder, lambda: {4242: str(tmp_path / "wt-two")}) == "", "a sibling folder is not inside"
        assert cs.held_open(folder, lambda: {4242: str(folder / "sub"), mine: str(folder)}) == (
            "a process works in it (pid 4242)")
        many = {p: str(folder) for p in (4301, 4242, 5100, 5200, 6000)}
        assert cs.held_open(folder, lambda: many) == "5 processes work in it (pids 4242, 4301, 5100, and 2 more)"
        assert cs.held_open(folder, lambda: None) == (
            "the process table could not be read, so a run in it cannot be ruled out")

    def test_ancestors_of_walks_a_held_table_nearest_first(self, cs, monkeypatch):
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: pytest.fail("a held table is read, not re-read"))
        assert cs.ancestors_of(10, {10: 5, 5: 1, 1: 0}) == [5, 1]
        assert cs.ancestors_of(7, {7: 7}) == [], "a pid that is its own parent ends the walk"
        assert cs.ancestors_of(3, {3: 4, 4: 3}) == [4], "a cycle ends the walk"
        assert cs.ancestors_of(9, {}) == []
        assert cs.ancestors_of(10, {10: 5, 5: 4, 4: 3}, depth=2) == [5, 4]


def _row(cwd: object, *, pid: int | None = None, sid: str = "s") -> dict:
    return {"pid": pid or os.getpid(), "session_id": sid, "cwd": str(cwd), "kind": "", "entrypoint": "",
            "started_at": None}


def _ids(rows) -> list[str]:
    return [r["session_id"] for r in rows]


class TestTheOneLivenessOracle:
    """``sessions_in`` and ``occupancy``: the one answer the seat driver, the
    ship driver and (later) the banner ask "is a session live in this
    checkout" of. A session belongs to the DEEPEST registered checkout that
    holds its cwd; the registry answers, the markers only ever add, and an
    answer nobody can give is "cannot tell", never "empty"."""

    def test_a_registry_row_carries_its_kind_entrypoint_and_start(self, cs, tmp_path):
        """The measured headless shape (2026-10-15, 2.1.300): a `claude -p` run
        registers as kind interactive, entrypoint sdk-cli. Dies to: dropping
        the fields, which leaves a headless run indistinguishable from a window."""
        cfg = _registry(tmp_path, [
            {"pid": os.getpid(), "sessionId": "h1", "cwd": str(tmp_path), "kind": "interactive",
             "entrypoint": "sdk-cli", "startedAt": 1792045849132},
            {"pid": os.getppid(), "sessionId": "odd", "cwd": str(tmp_path / "x"), "kind": 7,
             "entrypoint": None, "startedAt": True},
        ])
        rows = sorted(cs.live_sessions(cfg), key=lambda r: r["session_id"] != "h1")
        assert rows[0] == {"pid": os.getpid(), "session_id": "h1", "cwd": str(tmp_path), "kind": "interactive",
                           "entrypoint": "sdk-cli", "started_at": 1792045849.132}
        assert (rows[1]["kind"], rows[1]["entrypoint"], rows[1]["started_at"]) == ("", "", None)
        assert cs.describe_session(rows[0]) == f"pid {os.getpid()} (sdk-cli, started 2026-10-15 06:30Z)"
        assert cs.describe_session(_row(tmp_path, pid=42)) == "pid 42"

    def test_a_session_belongs_to_the_deepest_checkout_that_holds_it(self, cs, repos):
        """Dies to: dropping the cwd comparison or the depth (a worktree's
        session then counts for the clone that holds its folder), and to the
        reaper's prefix rule (a worktree outside .claude/worktrees counted for
        the clone: the disagreement the Wave A review found)."""
        work = repos["work"]
        inside = _worktree(repos, "seat-a")
        side = work / "side"
        _git(work, "worktree", "add", "--quiet", "--detach", str(side), "origin/main")
        rows = [_row(work, sid="root"), _row(work / "src", sid="root-sub"), _row(inside, sid="a"),
                _row(inside / "deep", sid="a-sub"), _row(side, sid="side"),
                _row(work.parent / "elsewhere", sid="out")]
        assert _ids(cs.sessions_in(work, sessions=rows)) == ["root", "root-sub"]
        assert _ids(cs.sessions_in(inside, sessions=rows)) == ["a", "a-sub"]
        assert _ids(cs.sessions_in(side, sessions=rows)) == ["side"]
        listed = cs.registered_checkouts(work)
        assert [p.name for p in listed][1:] == ["seat-a", "side"]
        # Depth decides, not git's listing order (the main checkout first).
        backwards = list(reversed(listed))
        assert _ids(cs.sessions_in(work, sessions=rows, checkouts=backwards)) == ["root", "root-sub"]
        assert _ids(cs.sessions_in(inside, sessions=rows, checkouts=backwards)) == ["a", "a-sub"]

    @pytest.mark.skipif(os.name != "nt", reason="the registry spells the drive letter both ways on Windows")
    def test_the_drive_letter_case_names_one_checkout(self, cs, repos):
        work = repos["work"]
        text = str(work)
        flipped = text[0].swapcase() + text[1:]
        assert _ids(cs.sessions_in(work, sessions=[_row(flipped, sid="lower")])) == ["lower"]

    def test_without_git_a_worktree_under_claude_worktrees_still_counts_as_its_own(self, cs, tmp_path):
        root = tmp_path / "repo"
        rows = [_row(root, sid="root"), _row(root / ".claude" / "worktrees" / "a", sid="a")]
        assert _ids(cs.sessions_in(root, sessions=rows, runner=lambda *a, **k: None)) == ["root"]

    def test_without_git_a_worktree_nested_elsewhere_in_the_folder_counts_as_its_own(self, cs, repos):
        """DEF-3024: the catch-up's other-session read (session_start.py's
        other_sessions_in_checkout) and the git-less fallback placed a session
        by folder, so one in a worktree nested in the clone's folder outside
        .claude/worktrees/ held the clone's catch-up. The siblings are read
        from git's registry on disk, no spawn. Dies to: the folder rule alone,
        and to placing by the first checkout that holds the cwd."""
        work = repos["work"]
        inside = _worktree(repos, "seat-a")
        side = work / "side"
        _git(work, "worktree", "add", "--quiet", "--detach", str(side), "origin/main")
        rows = [_row(work, pid=4001, sid="root"), _row(work / "src", pid=4002, sid="root-sub"),
                _row(inside, pid=4003, sid="a"), _row(side, pid=4004, sid="side"),
                _row(side / "deep", pid=4005, sid="side-sub"), _row(work.parent / "elsewhere", pid=4006, sid="out")]
        assert _ids(cs.sessions_in_checkout(rows, work)) == ["root", "root-sub"]
        assert _ids(cs.other_sessions_in_checkout(rows, work, "root")) == ["root-sub"]
        assert _ids(cs.sessions_in_checkout(rows, side)) == ["side", "side-sub"]
        assert _ids(cs.sessions_in(work, sessions=rows, runner=lambda *a, **k: None)) == ["root", "root-sub"]

    def test_where_the_hooks_reader_cannot_answer_the_folder_rule_stands(self, cs, repos, monkeypatch):
        """A checkout_sync.py deployed without hooks/_hook_utils.py, or one whose
        reader breaks, cannot read the registry off the disk: the
        .claude/worktrees/ rule stands alone and holds for the rest, never a
        raise. Dies to: an unguarded reader."""
        work = repos["work"]
        side = work / "side"
        _git(work, "worktree", "add", "--quiet", "--detach", str(side), "origin/main")
        rows = [_row(work, pid=4001, sid="root"), _row(side, pid=4004, sid="side")]
        monkeypatch.setattr(cs, "_hook_utils_by_path", lambda: None)
        assert _ids(cs.sessions_in_checkout(rows, work)) == ["root", "side"]

        class _Broken:
            @staticmethod
            def sibling_checkouts(root):
                raise OSError("unreadable")

        monkeypatch.setattr(cs, "_hook_utils_by_path", lambda: _Broken)
        assert _ids(cs.sessions_in_checkout(rows, work)) == ["root", "side"]

        def _unloadable():
            raise ImportError("a hooks file that raises at import")

        monkeypatch.setattr(cs, "_hook_utils_by_path", _unloadable)
        assert _ids(cs.sessions_in_checkout(rows, work)) == ["root", "side"]

    def test_a_registration_whose_git_file_is_gone_is_no_checkout(self, cs, repos):
        """A worktree folder whose .git file was deleted while its registration
        stayed (git reads it prunable) is the clone's folder again: a session
        there shares the clone's repository and must hold its catch-up. Dies
        to: taking every registered folder that exists as a checkout."""
        work = repos["work"]
        side = work / "side"
        _git(work, "worktree", "add", "--quiet", "--detach", str(side), "origin/main")
        (side / ".git").unlink()
        rows = [_row(work, pid=4001, sid="root"), _row(side, pid=4004, sid="side")]
        assert _ids(cs.sessions_in_checkout(rows, work)) == ["root", "side"]

    def test_without_git_a_marker_is_placed_by_the_same_rule(self, cs, repos, monkeypatch):
        """occupancy's marker fallback placed a marker by folder alone, where the
        registry rows' fallback leaves .claude/worktrees/ out and places by the
        deepest checkout. Dies to: within(cwd, path) for the markers."""
        monkeypatch.delenv("CLAUDECODE", raising=False)
        work = repos["work"]
        inside = _worktree(repos, "seat-a")
        side = work / "side"
        _git(work, "worktree", "add", "--quiet", "--detach", str(side), "origin/main")
        marks = [{"session_id": "in-root", "pid": 4101, "cwd": str(work / "src")},
                 {"session_id": "in-seat", "pid": 4102, "cwd": str(inside)},
                 {"session_id": "in-side", "pid": 4103, "cwd": str(side)}]
        occ = cs.occupancy(work, sessions=[], markers=lambda tree: marks, runner=lambda *a, **k: None)
        assert _ids(occ.sessions) == ["in-root"]
        seat = cs.occupancy(inside, sessions=[], markers=lambda tree: marks, runner=lambda *a, **k: None)
        assert _ids(seat.sessions) == ["in-seat"]
        # A marker caps a cwd past 120 characters to "..." and its tail, which
        # matches by folder names alone: kept where the folder rule keeps it,
        # never ruled out by a worktrees folder in its tail.
        capped = {"session_id": "capped", "pid": 4104,
                  "cwd": ".../.claude/worktrees/seat-a/packages/core/src/lib/components/forms/" + "y" * 40}
        long_seat = cs.occupancy(inside, sessions=[], markers=lambda tree: [capped], runner=lambda *a, **k: None)
        assert _ids(long_seat.sessions) == ["capped"]

    def test_an_unreadable_registry_is_cannot_tell_and_the_markers_only_ever_add(self, cs, tmp_path,
                                                                                  monkeypatch):
        """An idle session touches no marker, so "no marker" is never "nobody".
        Dies to: reading an empty marker list as an empty checkout."""
        monkeypatch.setattr(cs, "live_sessions", lambda *a, **k: None)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert cs.sessions_in(tmp_path) is None
        blind = cs.occupancy(tmp_path, markers=lambda tree: [])
        assert (blind.sessions, blind.oracle) == (None, "")
        assert blind.note == ("Claude Code's session registry could not be read in full; no session marker "
                              "answers either, so who is in it cannot be told")
        live = {"session_id": "m1", "pid": os.getpid(), "cwd": str(tmp_path)}
        seen = cs.occupancy(tmp_path, markers=lambda tree: [live])
        assert seen.oracle == "markers" and _ids(seen.sessions) == ["m1"]
        assert seen.sessions[0]["source"] == "marker" and seen.from_registry() == []
        gone = cs.occupancy(tmp_path, markers=lambda tree: [{**live, "pid": _dead_pid(), "alive": False}])
        assert gone.sessions is None, "a marker whose registry-named window pid exited names nobody"
        # A pid the registry did not name (the hook's fallback parent, a launcher
        # that exits with the hook on Windows) says nothing by its exit, so the
        # marker still counts. Dies to: asking pid_alive about any recorded pid.
        fallback = cs.occupancy(tmp_path, markers=lambda tree: [{**live, "pid": _dead_pid(), "alive": None}])
        assert fallback.oracle == "markers" and _ids(fallback.sessions) == ["m1"]
        broken = cs.occupancy(tmp_path, markers=lambda tree: 1 / 0)
        assert broken.sessions is None and broken.oracle == ""

    def test_a_registry_that_does_not_list_the_session_asking_is_not_trusted(self, cs, tmp_path, monkeypatch):
        rows = [_row(tmp_path, sid="someone")]
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("CLAUDE_PID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setattr(cs, "ancestry", lambda depth=8: ([999999], True))
        stranger = cs.occupancy(tmp_path, sessions=rows, checkouts=[tmp_path], markers=lambda tree: [])
        assert stranger.sessions is None
        assert stranger.note.startswith("this session is not in Claude Code's session registry")
        monkeypatch.setattr(cs, "ancestry", lambda depth=8: ([os.getpid()], True))
        listed = cs.occupancy(tmp_path, sessions=rows, checkouts=[tmp_path], markers=lambda tree: [])
        assert listed.oracle == "registry" and listed.sessions == [{**rows[0], "source": "registry"}]
        assert listed.caller is rows[0]

    def test_the_caller_is_found_by_the_ids_a_session_exports(self, cs, tmp_path, monkeypatch):
        """A session exports its registry pid and session id to its children
        (CLAUDE_PID, CLAUDE_CODE_SESSION_ID; equal to the registry's, read
        2026-10-15): no process walk needed. Dies to: an 8-deep walk that
        misses a longer chain and leaves the registry untrusted."""
        rows = [_row(tmp_path, pid=4242, sid="mine"), _row(tmp_path, pid=4343, sid="other")]
        monkeypatch.setattr(cs, "ancestry", lambda depth=8: ([], True))
        monkeypatch.setenv("CLAUDE_PID", "4242")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert cs.caller_entry(rows) is rows[0]
        monkeypatch.delenv("CLAUDE_PID")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "other")
        assert cs.caller_entry(rows) is rows[1]

    def test_a_live_marker_names_a_session_that_moved_into_the_checkout(self, cs, repos, monkeypatch):
        """A session that went into a worktree mid-session keeps its registry
        cwd (the clone) and records the move in the clone's marker, the shape
        SessionStart's reaper reads (session_start.py). Dies to: a readable
        registry hiding every marker, so launch or retire acts on a worktree
        a clone session is working in."""
        monkeypatch.delenv("CLAUDECODE", raising=False)
        work = repos["work"]
        feat = _worktree(repos, "feat")
        clone_session = _row(work, pid=os.getpid(), sid="clone")
        moved = {"session_id": "clone", "pid": os.getpid(), "cwd": str(feat)}
        visitor = {"session_id": "visitor", "pid": os.getppid(), "cwd": str(feat / "src")}
        # The hooks' reader judges liveness (alive False: a registry-named pid that exited).
        gone = {"session_id": "gone", "pid": _dead_pid(), "cwd": str(feat), "alive": False}
        in_root = {"session_id": "root-only", "pid": os.getppid(), "cwd": ""}
        own_marker = {"session_id": "clone", "pid": os.getpid(), "cwd": ""}
        by_tree = {cs._norm(work): [moved, visitor, gone, in_root, own_marker], cs._norm(feat): []}
        occ = cs.occupancy(feat, sessions=[clone_session], markers=lambda tree: by_tree[cs._norm(tree)])
        assert occ.oracle == "registry" and occ.from_registry() == []
        assert _ids(occ.sessions) == ["clone", "visitor"] and {r["source"] for r in occ.sessions} == {"marker"}
        here = cs.occupancy(work, sessions=[clone_session], markers=lambda tree: by_tree[cs._norm(tree)])
        assert _ids(here.sessions) == ["clone", "root-only"], "the registry row and its own marker are one session"

    @pytest.mark.skipif(os.name != "nt", reason="procStart is measured against the Windows creation FILETIME")
    def test_an_entry_whose_pid_now_names_another_process_is_gone(self, cs, tmp_path):
        """A crashed session's entry whose pid Windows handed to an unrelated
        process: alive by pid, gone by procStart. Dies to: reading the pid
        alone, which refuses a checkout for good."""
        own = cs._proc_start_windows(os.getpid())
        assert own and own.isdigit()
        cfg = _registry(tmp_path, [
            {"pid": os.getpid(), "sessionId": "real", "cwd": str(tmp_path), "procStart": own},
            {"pid": os.getppid(), "sessionId": "ghost", "cwd": str(tmp_path), "procStart": "1"},
        ])
        assert _ids(cs.live_sessions(cfg)) == ["real"]

    def test_a_start_time_of_no_real_moment_is_left_out_of_the_words(self, cs, tmp_path):
        for raw in (float("inf"), float("nan"), 1e20, -5, True, "x"):
            assert cs._started_at(raw) is None, raw
        row = {**_row(tmp_path, pid=42), "started_at": float("inf"), "kind": "background", "entrypoint": "cli"}
        assert cs.describe_session(row) == "pid 42 (cli, background)"
        assert cs.describe_session({**_row(tmp_path, pid=7), "source": "marker"}) == "pid 7 (a session marker)"

    def test_reaping_one_named_worktree_leaves_the_rest_and_says_what_it_unlocked(self, cs, repos):
        """``seat.py retire``'s removal: the reaper's rules for one worktree. A
        lock whose holder exited (a `claude --worktree -p` run leaves one, read
        2026-10-15: "claude session <name> (pid N)") is released and said."""
        work = repos["work"]
        a = _worktree(repos, "a", "lane/a")
        b = _worktree(repos, "b", "lane/b")
        gone = _dead_pid()
        _git(work, "worktree", "lock", "--reason", f"claude session a (pid {gone})", str(a))
        report = cs.reap_worktrees(work, sessions=[], only=a)
        assert report.removed == ["a"] and report.unlocked == [f"a (pid {gone})"]
        assert not a.exists() and b.is_dir() and _registered(work, b)


def test_every_worktree_include_entry_is_safe_for_the_reap(cs):
    """Each path `.worktreeinclude` copies into a worktree (init's roster for
    adopters, and this repo's own file) must be one the reap can account for:
    a regenerable output (``_disposable``) or a copy it compares with the
    root's (``_COPIED_FROM_ROOT``). Any other copied file keeps every worktree
    forever, silently (failure-mode review, 2026-10-12: the reports were safe
    only because ``reports`` is a disposable top, and nothing said so)."""
    from espalier.cli import WORKTREE_INCLUDE_ENTRIES

    own = REPO_ROOT / ".worktreeinclude"
    lines = [ln.strip() for ln in own.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")] if own.is_file() else []
    entries = [*WORKTREE_INCLUDE_ENTRIES, *lines]
    assert ".claude/settings.json" in entries
    for entry in entries:
        assert cs._disposable(entry) or entry in cs._COPIED_FROM_ROOT, entry


# The child a SessionStart is: the hook's two sys.path entries, its module
# loaded the way the wiring loads it, its payload on a real stdin pipe, its
# audit log inside the tree, then the catch-up's effect on disk (a shared
# helper this process already imported gains a name, and each module the hook
# first loads after the catch-up starts importing it, then marks that it
# loaded), then, by mode, one late load or the whole start.
_STALE_HELPER_CHILD = r'''
import json, os, sys, time
from pathlib import Path
repo = Path(sys.argv[1])
mode = sys.argv[2]
sites = json.loads(sys.argv[3])
cc = repo / "tools" / "cc"
sys.path[:0] = [str(cc / "hooks"), str(cc)]
for key in [k for k in os.environ if k.startswith("ESPALIER") and k != "ESPALIER_SESSION_START_HANDOFF"]:
    os.environ.pop(key)
os.environ["CLAUDE_PROJECT_DIR"] = str(repo)
os.environ["ESPALIER_AUDIT_DIR"] = str(repo / ".audit")
os.environ["DEF2003_MARKER"] = str(repo / "loaded.txt")
import session_start as ss

def _raise(message):
    raise ImportError(message)

def move():
    helper = cc / "_json_safe.py"
    helper.write_bytes(helper.read_bytes() + b"\n\ndef moved_in_by_the_catch_up():\n    return True\n")
    for site, (rel, _load) in sites.items():
        late = cc / rel
        lines = late.read_bytes().split(b"\n")
        at = next(i for i, ln in enumerate(lines) if ln.startswith(b"from __future__ import"))
        lines[at + 1:at + 1] = [
            b"from _json_safe import moved_in_by_the_catch_up  # noqa: E402",
            ("import os as _o; open(_o.environ['DEF2003_MARKER'], 'a').write(%r + '\\n')" % site).encode(),
        ]
        late.write_bytes(b"\n".join(lines))

if mode == "late-load":
    move()
    (site, (rel, load)), = sites.items()
    try:
        print("LOADED", eval(load) is not None)
    except Exception as exc:
        print("RAISED", type(exc).__name__, exc)
    raise SystemExit(0)

called = []
def fake_catch_up(*args, **kwargs):
    called.append(True)
    move()
    return "main moved to origin/main (the test's catch-up)", "", []
ss._sync_checkout = fake_catch_up
CHILD = {
    "dies": "import sys; sys.exit(3)",
    "hangs": "import time; time.sleep(30)",
    "late-banner": ("import json, sys, time; print(json.dumps({'hookSpecificOutput': {'hookEventName': "
                    "'SessionStart', 'additionalContext': 'the late banner'}})); sys.stdout.flush(); time.sleep(30)"),
    "advances-then-dies": ("import os, sys, pathlib; p = pathlib.Path(os.environ['CLAUDE_PROJECT_DIR']) / 'cc' / "
                           "'blueprints' / 'latest.json'; p.parent.mkdir(parents=True, exist_ok=True); "
                           "p.write_text('{\"advanced\": \"by the child\"}'); sys.exit(3)"),
}
kind = mode.split(":", 1)[1] if ":" in mode else ""
if kind in CHILD:
    ss._handoff_argv = lambda: [sys.executable, "-c", CHILD[kind]]
if kind in ("hangs", "late-banner"):
    ss._HOOK_BUDGET_SECONDS, ss._HANDOFF_RESERVE_SECONDS = 4.0, 2.0
advanced = []
real_build = ss._build_context
def build(root, self_host, advance_chain, *args, **kwargs):
    advanced.append(advance_chain)
    return real_build(root, self_host, advance_chain, *args, **kwargs)
ss._build_context = build
retired = []
ss._hook_utils.retire_same_window_markers = lambda root, sid, window: retired.append(window)
start = time.monotonic()
ss.main()
print("ELAPSED", round(time.monotonic() - start, 2))
print("CATCH-UP-CALLED", bool(called))
print("ADVANCED", advanced)
print("RETIRED", retired)
'''

# Each module the hook first loads after the catch-up, and how it loads it:
# the six sites the 2026-10-17 measurement found importing a helper the hook
# has cached at load (by path: the mail driver, through record_merge, the seat
# driver, the merge rules, the record-fragment loader; by name: the zone watch
# and the denial reasons).
_LATE_SITES = {
    "mail": ("record_merge.py", "ss._load_mail()"),
    "seat": ("seat.py", "ss._load_seat()"),
    "merge-rules": ("_merge_rules.py", "ss._load_merge_rules()"),
    # the loader keeps its failure rather than raising (the memory index notes it)
    "record-fragments": ("_record_fragments.py",
                         "ss._hook_utils.load_record_fragments() or _raise(ss._hook_utils.RECORD_FRAGMENTS_LOAD_ERROR)"),
    "zone-watch": ("hooks/_zone_watch.py", "__import__('_zone_watch')"),
    "denial-reasons": ("hooks/_denial_reasons.py", "__import__('_denial_reasons')"),
}


class TestACatchUpThatMovesAnImportedHelper:
    """DEF-2003: SessionStart imports its sibling helpers at module load and
    only then catches the checkout up, so a module it first loads after the
    move runs the new bytes against the helpers' old copies already in
    ``sys.modules``. Seen once on the Windows seat (2026-10-13, across #206):
    ``tools/cc/mail.py``'s ``record_merge`` asked ``_json_safe`` for a name
    the old module lacked, and the banner lost its mail line under an
    ImportError that read as a broken install. When the catch-up moved a
    helper the hook imported, the rest of the start now runs in a fresh
    process on the moved tree; if that cannot give a banner, the parent gives
    a short one (out of time) or goes on itself (a fast failure), and the
    Checkout line names the cost. The child process here is a start, driven:
    a copy of the tree (git's view) holding the session-log fragments, the
    hook loaded as the wiring loads it, the payload on its stdin, the
    catch-up's effect written to disk."""

    PAYLOAD = {"source": "startup", "session_id": "t-def2003"}

    def _child(self, tmp_path: Path, mode: str, sites: dict, *, payload: dict | None = None,
               env: dict | None = None) -> str:
        from tests._live_tree import copy_checkout

        repo = tmp_path / "repo"
        copy_checkout(REPO_ROOT / "tools" / "cc", repo / "tools" / "cc")
        (repo / "memory" / "session-log.d").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=scaled(30))
        subprocess.run(["git", "-C", str(repo), "config", "espalier.machine", "t-def2003"], check=True,
                       timeout=scaled(30))
        driver = tmp_path / "child.py"
        driver.write_bytes(_STALE_HELPER_CHILD.encode("utf-8"))
        r = subprocess.run([HOOK_PYTHON, str(driver), str(repo), mode, json.dumps(sites)], capture_output=True,
                           input=json.dumps(payload or self.PAYLOAD), text=True, encoding="utf-8",
                           errors="replace", timeout=scaled(45), env={**os.environ, **(env or {})})
        assert r.returncode == 0, r.stderr[-2000:]
        return r.stdout

    @staticmethod
    def _banner(out: str) -> str:
        line = next(ln for ln in out.splitlines() if ln.startswith('{"hookSpecificOutput"'))
        return json.loads(line)["hookSpecificOutput"]["additionalContext"]

    @staticmethod
    def _checkout(banner: str) -> str:
        return next(ln for ln in banner.splitlines() if ln.startswith("Checkout:"))

    @staticmethod
    def _field(out: str, name: str) -> str:
        return next(ln for ln in out.splitlines() if ln.startswith(name + " "))[len(name) + 1:]

    @staticmethod
    def _loaded(tmp_path: Path) -> set[str]:
        marks = tmp_path / "repo" / "loaded.txt"
        return set(marks.read_text(encoding="utf-8").split()) if marks.is_file() else set()

    @pytest.mark.parametrize("site", sorted(_LATE_SITES))
    def test_a_late_load_after_the_move_meets_the_old_helper(self, tmp_path, site):
        """The oracle (Task 0), at each site: the mechanism the row names,
        made to fail in the process that imported the helper before the move."""
        out = self._child(tmp_path, "late-load", {site: _LATE_SITES[site]}).strip()
        assert out.startswith("RAISED ImportError"), out
        assert "moved_in_by_the_catch_up" in out, out

    def test_the_rest_of_the_start_runs_on_the_moved_tree(self, tmp_path):
        """The banner comes whole from a fresh start: the catch-up's own line,
        the hand-off named on it, no load failure, the late sites it reaches
        loaded with the moved bytes, the chain advanced once."""
        out = self._child(tmp_path, "start", _LATE_SITES)
        banner = self._banner(out)
        checkout = self._checkout(banner)
        assert "main moved to origin/main (the test's catch-up)" in checkout, checkout
        assert "so the rest of this start ran in a fresh process" in checkout, checkout
        assert "ImportError" not in banner and "no fresh start took over" not in banner, banner[-3000:]
        assert {"mail", "merge-rules", "zone-watch", "record-fragments"} <= self._loaded(tmp_path)
        assert self._field(out, "ADVANCED") == "[]", "the parent built no banner of its own"

    def test_a_fresh_start_that_dies_leaves_the_parent_to_name_the_cost(self, tmp_path):
        """A fast failure: the hand-off exits 3, the parent goes on itself, and
        the Checkout line names the move and each line it cost, in place of a
        WARN that reads as a broken install; the memory index says why its
        fragments were not read."""
        out = self._child(tmp_path, "start:dies", _LATE_SITES)
        banner = self._banner(out)
        checkout = self._checkout(banner)
        assert "no fresh start took over (it exited 3)" in checkout, checkout
        assert "_json_safe.py" in checkout, checkout
        for line in ("mail scan", "merge-rules read", "zone baseline"):
            assert line in checkout, (line, checkout)
        assert "ImportError" not in banner, banner[-3000:]
        assert "the catch-up moved a helper this start had loaded" in banner, banner[-3000:]
        assert self._field(out, "ADVANCED") == "[True]"

    def test_a_fresh_start_that_advanced_the_chain_is_not_advanced_again(self, tmp_path):
        """The failure-mode review's drive: a child that advanced the chain and
        then failed left the parent advancing it a second time."""
        out = self._child(tmp_path, "start:advances-then-dies", _LATE_SITES)
        assert self._field(out, "ADVANCED") == "[False]", out[-2000:]

    def test_a_fresh_start_out_of_time_leaves_a_short_banner_inside_the_budget(self, tmp_path):
        """A child that hangs: the parent prints a short banner naming the move
        instead of a second full pass, which crossed the 15 s ceiling (17.2 s
        driven) and lost the banner whole. Budgets are shrunk here to 4 s."""
        out = self._child(tmp_path, "start:hangs", _LATE_SITES)
        banner = self._banner(out)
        assert "the rest resumes at the next start" in banner, banner
        assert "no fresh start took over (it ran past the hook's budget)" in self._checkout(banner), banner
        assert float(self._field(out, "ELAPSED")) < 4.0 + 2.0, out[-500:]
        assert self._field(out, "ADVANCED") == "[]"

    def test_a_banner_printed_before_the_time_ran_out_is_relayed(self, tmp_path):
        """A child that printed its banner and was then slow to exit: its banner
        stands, and the parent builds nothing (no second chain advance)."""
        out = self._child(tmp_path, "start:late-banner", _LATE_SITES)
        assert self._banner(out) == "the late banner"
        assert self._field(out, "ADVANCED") == "[]"

    def test_the_fresh_start_never_catches_up_or_hands_off_again(self, tmp_path):
        """At most once: a start that carries its own parent's hand-off runs no
        catch-up of its own and takes the parent's lines and window."""
        handed = json.dumps({"parent": os.getpid(), "hook_start": None, "window": 424242, "window_found": True,
                             "checkout": "handed by the parent", "worktrees": "", "kept": [],
                             "advisories": ["[INFO] the parent's own line"]})
        out = self._child(tmp_path, "start", _LATE_SITES, payload={"source": "clear", "session_id": "t-def2003"},
                          env={"ESPALIER_SESSION_START_HANDOFF": handed})
        assert self._field(out, "CATCH-UP-CALLED") == "False", out[-2000:]
        assert self._field(out, "RETIRED") == "[424242]", "a /clear retires by the window the parent read"
        banner = self._banner(out)
        assert "handed by the parent" in banner and "the parent's own line" in banner, banner[-3000:]

    def test_a_marker_from_another_process_runs_the_start_as_a_parent(self, tmp_path):
        """A marker inherited from a shell (an operator reproducing the probe)
        is not this start's parent's: the catch-up and the state jobs run."""
        stray = json.dumps({"parent": 1, "checkout": "a stray marker"})
        out = self._child(tmp_path, "start", {}, env={"ESPALIER_SESSION_START_HANDOFF": stray})
        assert self._field(out, "CATCH-UP-CALLED") == "True", out[-2000:]
        assert "a stray marker" not in self._banner(out)

    def test_every_block_after_the_catch_up_speaks_through_the_move(self):
        """Derived, not listed: every handler in ``_run_main`` after the
        hand-off decision speaks through ``_late_load_failed``, which is
        ``advise_exc`` unless a move no fresh start took over; one that called
        ``advise_exc`` itself would WARN an ImportError the move caused."""
        import ast

        source = (REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py").read_text(encoding="utf-8")
        run_main = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_run_main")
        after = next(n.lineno for n in ast.walk(run_main) if isinstance(n, ast.Call)
                     and getattr(n.func, "id", "") == "_moved_helpers")
        direct = sorted({n.lineno for n in ast.walk(run_main) if isinstance(n, ast.Call)
                         and getattr(n.func, "attr", "") == "advise_exc" and n.lineno > after})
        late = sorted({n.lineno for n in ast.walk(run_main) if isinstance(n, ast.Call)
                       and getattr(n.func, "id", "") == "_late_load_failed"})
        assert not direct, f"advise_exc after the catch-up in _run_main at lines {direct}"
        assert len(late) >= 10, late


_SEAT_CLAIMS_CHILD = r'''
import sys
from pathlib import Path
cc = Path(sys.argv[1])
sys.path.insert(0, str(cc))
import checkout_sync
try:
    print("CLAIMS", checkout_sync.seat_live_claims(cc, "seat-x", 5))
except Exception as exc:
    print("RAISED", type(exc).__name__)
'''


class TestTheReaperKeepsAWorktreeWhoseClaimsDidNotRead:
    """DEF-2003's sister site inside the catch-up: the worktree reaper asks
    ``seat_live_claims``, which imports ``mail`` after the move. A mail
    driver that is deployed but does not import (it met an old helper) read
    as no claims, and a clean, merged worktree whose seat still held live
    claims was removed (the failure-mode review's drive). Only a mail driver
    that is not deployed reads as no claims now; the caller keeps a worktree
    whose claims raised."""

    def _run(self, tmp_path: Path, mail_text: bytes | None) -> str:
        cc = tmp_path / "cc"
        cc.mkdir()
        for name in ("checkout_sync.py", "_json_safe.py", "_stack_table.py"):
            (cc / name).write_bytes((REPO_ROOT / "tools" / "cc" / name).read_bytes())
        if mail_text is not None:
            (cc / "mail.py").write_bytes(mail_text)
        driver = tmp_path / "child.py"
        driver.write_bytes(_SEAT_CLAIMS_CHILD.encode("utf-8"))
        r = subprocess.run([HOOK_PYTHON, str(driver), str(cc)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=45)
        assert r.returncode == 0, r.stderr[-2000:]
        return r.stdout.strip()

    def test_a_deployed_mail_driver_that_does_not_import_raises(self, tmp_path):
        assert self._run(tmp_path, b"from _json_safe import a_name_this_copy_lacks\n") == "RAISED ImportError"

    def test_a_mail_driver_not_deployed_is_no_claims(self, tmp_path):
        assert self._run(tmp_path, None) == "CLAIMS []"


# -- a read that did not answer says it cannot tell (DEF-2046) -------------------------

def _killing(cs, *heads: tuple[str, ...], once_after: list | None = None):
    """A runner that answers as a read killed at its cap does (None) for each
    git argv opening with one of ``heads`` and runs every other read; with
    ``once_after``, only once that list holds something (a spawner fills it
    when the change under test has run)."""
    def runner(argv, *, cwd, timeout):
        if argv[0] == "git" and (once_after is None or once_after) and any(
                tuple(argv[1:1 + len(head)]) == head for head in heads):
            return None
        return cs.run(argv, cwd=cwd, timeout=timeout)
    return runner


def _noting(cs, verb: tuple[str, ...], seen: list):
    """A spawner that runs everything and notes each run of git ``verb``."""
    def spawner(argv, *, cwd, wait, kill):
        done = cs.spawn(argv, cwd=cwd, wait=wait, kill=kill)
        if tuple(argv[1:1 + len(verb)]) == verb:
            seen.append(argv)
        return done
    return spawner


_ORIGIN_HEAD_READ = ("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")


class TestAKilledReadSaysItCannotTell:
    """DEF-2046, this module's sites: a bounded read killed at its cap, or
    never started for want of time, answered as its success would. A killed
    fetch read ``current`` and the line printed nothing (#452's windows-latest
    leg); a killed ref read let the catch-up switch a lane whose remote branch
    still exists. A read that did not answer is now counted apart from a
    non-zero exit, an act waits on every read it rests on, and the line says
    what did not answer. Each case runs real git with one read killed, beside
    the success twin the classes above already pin."""

    def test_a_read_that_did_not_answer_is_counted_and_a_failed_one_is_not(self, cs, tmp_path):
        killed = cs._Git(tmp_path, None, runner=lambda argv, **_k: None)
        assert killed.out("status") is None and killed.yes("show-ref") is None
        assert killed.unanswered == 2
        assert killed.at(tmp_path / "wt").out("status") is None and killed.unanswered == 3  # one count
        failed = cs._Git(tmp_path, None,
                         runner=lambda argv, **_k: subprocess.CompletedProcess(argv, 128, "", "fatal: no\n"))
        assert failed.out("status") is None and failed.yes("show-ref") is None
        assert failed.unanswered == 0
        spent = cs._Git(tmp_path, time.monotonic() - 1, runner=lambda argv, **_k: pytest.fail("spawned"))
        assert spent.out("status") is None and spent.unanswered == 1

    def test_a_fetch_that_did_not_land_is_said_on_every_state_that_compares(self, cs):
        """The row's own site: the note rode ``caught_up`` and ``held`` alone."""
        for state in ("current", "lane", "would_catch_up", "caught_up", "skipped"):
            result = cs.CatchUp(state, branch="lane/x", base="main", behind=1, head="abc1234",
                                reason="no default branch on origin", fetched=False)
            line = cs.checkout_line(result)
            assert "origin not reached" in line and line.isascii(), (state, line)
        assert cs.checkout_line(cs.CatchUp("current")) == ""
        early = cs.checkout_line(cs.CatchUp("held", reason="git did not answer in time", fetched=False))
        assert early == "NOT caught up (git did not answer in time) (origin not reached)"  # nothing compared

    def test_a_killed_fetch_reads_current_and_says_so(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"])

        def spawner(argv, *, cwd, wait, kill):
            return None if "fetch" in argv else cs.spawn(argv, cwd=cwd, wait=wait, kill=kill)

        result = cs.catch_up(work, spawner=spawner)
        assert (result.state, result.fetched) == ("current", False), result
        assert cs.checkout_line(result) == "current (origin not reached; compared with the last fetch)"

    def test_a_killed_default_branch_read_holds_and_never_reads_as_skipped(self, cs, repos):
        """The origin/HEAD read alone killed: the main/master fallback that
        still answers is a guess past it, never the base."""
        result = cs.catch_up(repos["work"], runner=_killing(cs, _ORIGIN_HEAD_READ))
        assert (result.state, result.reason) == ("held", "git did not answer which branch is origin's default")
        assert cs.checkout_line(result).startswith("NOT caught up (git did not answer")

    def test_a_killed_head_read_holds_and_never_reads_as_detached(self, cs, repos):
        work = repos["work"]
        _advance(repos["seed"])
        before = _out(work, "rev-parse", "HEAD")
        result = cs.catch_up(work, runner=_killing(cs, ("symbolic-ref", "--quiet", "--short", "HEAD")))
        assert result.state == "held" and "did not answer" in result.reason, result
        assert _out(work, "rev-parse", "HEAD") == before

    def test_a_killed_ref_read_never_switches_a_lane_whose_remote_branch_exists(self, cs, repos):
        """The unsafe one. A lane pushed without -u tracks main, so only its
        own ref on origin says it is still someone's (DEF-2042); a killed read
        of it read as not listed, and the catch-up switched the lane away and
        deleted it."""
        work, seed = repos["work"], repos["seed"]
        _git(work, "switch", "--quiet", "-c", "lane/kept", "--track", "origin/main")
        _commit(work, "kept.txt")
        _git(work, "push", "--quiet", "origin", "lane/kept")
        _git(seed, "pull", "--quiet", "--ff-only")
        _git(seed, "fetch", "--quiet", "origin", "lane/kept")
        _git(seed, "merge", "--quiet", "--no-ff", "-m", "Merge lane/kept", "origin/lane/kept")
        _git(seed, "push", "--quiet", "origin", "main")
        assert cs.catch_up(work, dry_run=True).reason == "its remote branch still exists"
        result = cs.catch_up(work, runner=_killing(cs, ("for-each-ref", "--format=%(refname)")))
        assert (result.state, result.reason) == ("lane", "whether it merged could not be read"), result
        assert _out(work, "symbolic-ref", "--short", "HEAD") == "lane/kept"
        assert "lane/kept" in _out(work, "branch", "--format=%(refname:short)").split()

    def test_a_killed_worktree_list_never_moves_a_branch_another_checkout_holds(self, cs, repos):
        """git before 2.43 runs `switch -C main` over a main another worktree
        holds and moves it under that checkout (both reviews drove it on
        2.39.5): a list that did not answer holds the move."""
        work = repos["work"]
        _merged_lane(repos, "lane/z")
        _git(work, "switch", "--quiet", "main")
        linked = work.parent / "linked"
        _git(work, "worktree", "add", "--quiet", str(linked), "lane/z")
        _advance(repos["seed"])
        before = _out(work, "rev-parse", "refs/heads/main")
        result = cs.catch_up(linked, runner=_killing(cs, ("worktree", "list")))
        assert (result.state, result.reason) == ("held", "git did not answer where main is checked out"), result
        assert _out(work, "rev-parse", "refs/heads/main") == before
        assert _out(linked, "symbolic-ref", "--short", "HEAD") == "lane/z"

    def test_a_killed_local_base_read_says_it_could_not_compare(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        result = cs.catch_up(work, runner=_killing(cs, ("merge-base", "--is-ancestor", "refs/heads/main")))
        assert (result.state, result.reason) == ("held", "git could not compare local main with origin/main")

    def test_reads_killed_after_a_move_that_worked_read_caught_up(self, cs, repos):
        work = repos["work"]
        _merged_lane(repos)
        _advance(repos["seed"])
        moved: list = []
        result = cs.catch_up(work, runner=_killing(cs, ("rev-parse",), ("diff", "--name-only"), once_after=moved),
                             spawner=_noting(cs, ("switch",), moved))
        assert moved and result.state == "caught_up", result
        assert _out(work, "rev-parse", "HEAD") == _out(work, "rev-parse", "origin/main")
        line = cs.checkout_line(result)
        assert line.startswith("caught up -- left lane/x (merged, branch deleted); main fast-forwarded"), line
        assert "now unread" in line and "4 git reads did not answer in time" in line, line
        assert "/clear" in line, line   # what changed did not read, so the hooks may have

    def test_a_killed_root_read_says_git_did_not_answer(self, cs, monkeypatch, tmp_path):
        """The common-dir read alone killed: its fallback answers (here, no
        repository; in a linked worktree, the worktree's own root), and must
        not be reached on a read that did not answer."""
        monkeypatch.chdir(tmp_path)
        real = cs.run
        monkeypatch.setattr(cs, "run", lambda argv, **k: None if "--git-common-dir" in argv else real(argv, **k))
        with pytest.raises(SystemExit, match="did not answer"):
            cs._repo_root(None)

    def test_a_killed_list_after_a_removal_that_worked_reads_removed(self, cs, repos):
        work = repos["work"]
        wt = _worktree(repos, "done")
        removed: list = []
        report = cs.reap_worktrees(work, sessions=[], runner=_killing(cs, ("worktree", "list"), once_after=removed),
                                   spawner=_noting(cs, ("worktree", "remove"), removed))
        assert (report.removed, report.kept) == (["done"], []), report
        assert not wt.exists() and not _registered(work, wt)
        assert cs.worktrees_line(report).endswith("; 1 git read did not answer in time")

    def test_a_killed_default_branch_read_in_the_reaper_says_so(self, cs, repos):
        _worktree(repos, "unknown")
        report = cs.reap_worktrees(repos["work"], sessions=[], runner=_killing(cs, _ORIGIN_HEAD_READ))
        assert report.kept == [("unknown", "git did not answer which branch is origin's default")], report

    def test_a_killed_operation_read_says_it_could_not_rule_one_out(self, cs, repos):
        _worktree(repos, "unsure")
        report = cs.reap_worktrees(repos["work"], sessions=[], runner=_killing(cs, ("rev-parse", "--git-path")))
        assert report.kept == [("unsure", "git could not rule out an operation in progress in it")], report

    def test_the_line_counts_what_did_not_answer_and_a_bare_note_ends_clean(self, cs):
        assert cs.worktrees_line(cs.Reap(note="git could not list the worktrees")) == "git could not list the worktrees"
        assert cs.worktrees_line(cs.Reap(unanswered=2)) == "2 git reads did not answer in time"
        assert cs.worktrees_line(cs.Reap()) == ""


class TestAProcessTableThatDidNotAnswerSaysItCannotTell:
    """DEF-2046, the process table and the checkout list: a ``ps`` killed at
    its cap read as a host with no processes, so an ancestor walk stopped at
    the first hop and a session it could not place was printed as one the
    registry does not list; a killed ``git worktree list`` read as no other
    checkout, and ``occupancy`` asked it twice."""

    @pytest.mark.skipif(os.name != "posix", reason="the ps arm; the Windows arm is driven below on every host")
    def test_a_ps_that_did_not_answer_is_unread_never_an_empty_table(self, cs, monkeypatch):
        for answer in (None, subprocess.CompletedProcess(["ps"], 1, "", "ps: denied\n"),
                       subprocess.CompletedProcess(["ps"], 0, "", "")):
            monkeypatch.setattr(cs, "run", lambda argv, *, cwd, timeout, given=answer: given)
            assert cs._parent_map() is None, answer
        monkeypatch.setattr(cs, "run", lambda argv, *, cwd, timeout: subprocess.CompletedProcess(
            argv, 0, "    1     0\n   42     1\nnoise\n", ""))
        assert cs._parent_map() == {1: 0, 42: 1}

    def test_an_empty_snapshot_is_unread_on_windows_too(self, cs, monkeypatch):
        monkeypatch.setattr(cs, "_process_table_windows", lambda: {})
        assert cs._parent_map_windows() is None
        monkeypatch.setattr(cs, "_process_table_windows", lambda: {4: (0, "System")})
        assert cs._parent_map_windows() == {4: 0}

    def test_an_unread_table_leaves_the_parent_alone_and_says_so(self, cs, monkeypatch):
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: None)
        assert cs.ancestry() == ([os.getppid()], False)
        assert cs.ancestors_of(os.getpid()) is None
        assert cs.ancestors_of(10, {10: 5}) == [5], "a table handed in is read as given"
        # A caller older than the None hands it straight back: no second read
        # (a second ps per pid outran the guard's time budget).
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: pytest.fail("a None handed in was read again"))
        assert cs.ancestors_of(10, None) is None
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: {os.getpid(): 77, 77: 1})
        assert cs.ancestry() == ([77, 1], True)

    def test_a_session_the_unread_table_could_not_place_is_never_called_unlisted(self, cs, tmp_path, monkeypatch):
        rows = [_row(tmp_path, pid=4242, sid="someone")]
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("CLAUDE_PID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: None)
        blind = cs.occupancy(tmp_path, sessions=rows, checkouts=[tmp_path], markers=lambda tree: [])
        assert blind.sessions is None
        assert blind.note == ("the process table could not be read, so this session could not be found in "
                              "Claude Code's session registry; no session marker answers either, so who is in "
                              "it cannot be told")
        assert cs.find_caller(rows) == (None, False) and cs.find_own_entry(rows) == (None, False)
        assert cs.find_own_entry(rows, "someone") == (rows[0], True), "found by its id: no table asked"
        monkeypatch.setenv("CLAUDE_PID", "4242")
        assert cs.find_caller(rows) == (rows[0], True), "found by the exported window pid: no table needed"
        monkeypatch.delenv("CLAUDE_PID")
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: {os.getpid(): 999999})
        listed = cs.occupancy(tmp_path, sessions=rows, checkouts=[tmp_path], markers=lambda tree: [])
        assert listed.note.startswith("this session is not in Claude Code's session registry"), listed.note
        assert cs.find_caller(rows) == (None, True)

    def test_the_cli_says_the_table_could_not_be_read(self, cs, repos, monkeypatch, capsys):
        work = repos["work"]
        _worktree(repos, "kept")   # the reaper's note names a worktree it kept
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.delenv("CLAUDE_PID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.setattr(cs, "live_sessions", lambda *a, **k: [_row(work, pid=4242, sid="someone")])
        monkeypatch.setattr(cs, "_parent_map", lambda *a, **k: None)
        assert cs.main(["--root", str(work), "--json"]) == 0
        note = json.loads(capsys.readouterr().out)["worktrees"]["note"]
        assert note == ("the process table could not be read, so this session could not be found in Claude "
                        "Code's session registry, so no worktree was removed"), note

    def test_a_killed_checkout_list_is_asked_once_and_the_folder_places_the_sessions(self, cs, repos, monkeypatch):
        work = repos["work"]
        wt = _worktree(repos, "lane")
        asked: list = []

        def runner(argv, *, cwd, timeout):
            if argv[1:3] == ["worktree", "list"]:
                asked.append(argv)
                return None
            return cs.run(argv, cwd=cwd, timeout=timeout)

        monkeypatch.delenv("CLAUDECODE", raising=False)
        rows = [_row(work, pid=4242, sid="in-main"), _row(wt, pid=4343, sid="in-lane")]
        occupied = cs.occupancy(work, sessions=rows, markers=lambda tree: [], runner=runner)
        assert len(asked) == 1, asked
        assert _ids(occupied.sessions) == ["in-main"]

    def test_a_killed_checkout_list_still_reads_the_main_checkouts_markers(self, cs, repos, monkeypatch):
        """A session that moved from the clone into a worktree keeps its
        registry cwd and records the move in the clone's marker: a killed list
        read as no main checkout, so retire found the worktree empty."""
        work = repos["work"]
        wt = _worktree(repos, "lane")
        moved = {"session_id": "moved", "pid": os.getpid(), "cwd": str(wt)}
        markers = lambda tree: [moved] if cs._norm(tree) == cs._norm(work) else []  # noqa: E731
        monkeypatch.delenv("CLAUDECODE", raising=False)
        killed = _killing(cs, ("worktree", "list"))
        seen = cs.occupancy(wt, sessions=[], markers=markers, runner=killed)
        assert _ids(seen.sessions) == ["moved"], seen
        monkeypatch.setattr(cs, "_sibling_places", lambda root: None)
        blind = cs.occupancy(wt, sessions=[], markers=markers, runner=killed)
        assert blind.sessions is None and "main checkout's session markers were not read" in blind.note, blind

    def test_the_cli_places_the_others_by_the_entry_it_found(self, cs, repos, monkeypatch, capsys):
        """A second walk of the table, killed after the first answered, once
        left the caller among the others: the catch-up named its own pid."""
        work = repos["work"]
        _worktree(repos, "kept")
        walks = iter([([4242], True)])
        monkeypatch.setattr(cs, "ancestry", lambda depth=8: next(walks, ([], False)))
        monkeypatch.setattr(cs, "live_sessions", lambda *a, **k: [_row(work, pid=4242, sid="me")])
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert cs.main(["--root", str(work), "--json"]) == 0
        payload = capsys.readouterr().out
        assert "pid 4242" not in payload, payload

    def test_a_killed_checkout_list_places_a_pid_by_the_registry_on_disk_or_says_unread(self, cs, repos,
                                                                                       monkeypatch):
        """``registered_checkouts`` is None on a kill, and ``or []`` read that
        as no other checkout: a nested worktree's process was this checkout's,
        and so in the Loose: line's paste."""
        work = repos["work"]
        wt = _worktree(repos, "lane")
        monkeypatch.setattr(cs, "registered_checkouts", lambda *a, **k: None)
        assert cs.pid_checkout(str(wt), work) == (
            "cwd in .claude/worktrees/lane, another checkout of this clone", True)
        monkeypatch.setattr(cs, "_sibling_places", lambda root: None)
        assert cs.pid_checkout(str(wt), work) == (
            "cwd's checkout unread: git did not list this clone's checkouts", True)


class TestTheSweepReadsPatchesNotShas:
    """DEF-5077: a worktree whose commits reached main as cherry-picks or
    applied diffs was kept on every banner as ``<n> commit(s) not in main``,
    counted by sha (three of five agent worktrees on the Air, 2026-11-02). The
    sweep now reads which commits main lacks by patch; a merge commit is never
    read as on main, and a read that did not answer keeps the worktree."""

    @staticmethod
    def _on_main_by_patch(repos, *names: str) -> None:
        """Each of ``names`` committed onto origin/main by the seed: the same
        patch as the worktree's commit, under another sha (main moves first
        and the pick says so, or the two commits are one object)."""
        seed = repos["seed"]
        _git(seed, "pull", "--quiet", "--ff-only")
        _commit(seed, "main-moved-on.txt")
        for name in names:
            (seed / name).write_text("x\n", encoding="utf-8")
            _git(seed, "add", name)
            _git(seed, "commit", "--quiet", "-m", f"pick {name}")
        _git(seed, "push", "--quiet", "origin", "main")
        _git(repos["work"], "fetch", "--quiet", "origin")

    @staticmethod
    def _lane(repos, name: str, *files: str) -> Path:
        wt = _worktree(repos, name, f"lane/{name}")
        _identity(wt)
        for file in files:
            _commit(wt, file)
        return wt

    def test_a_worktree_main_holds_by_patch_is_removed(self, cs, repos):
        wt = self._lane(repos, "picked", "p.txt", "p2.txt")
        self._on_main_by_patch(repos, "p.txt", "p2.txt")
        report = cs.reap_worktrees(repos["work"], sessions=[])
        assert (report.removed, report.kept) == (["picked"], []), report
        assert not wt.exists()

    def test_a_commit_main_lacks_keeps_it_named_by_the_patch_count(self, cs, repos):
        self._lane(repos, "half", "p.txt", "own.txt")
        self._on_main_by_patch(repos, "p.txt")
        report = cs.reap_worktrees(repos["work"], sessions=[])
        assert report.kept == [("half", "1 commit(s) not in main (lane/half)")], report

    def test_a_merge_commit_is_never_read_as_on_main(self, cs, repos):
        wt = self._lane(repos, "merged-in", "p.txt")
        _git(wt, "switch", "--quiet", "-c", "side", "origin/main")
        _commit(wt, "q.txt")
        _git(wt, "switch", "--quiet", "lane/merged-in")
        _git(wt, "merge", "--quiet", "--no-ff", "-m", "merge side", "side")
        self._on_main_by_patch(repos, "p.txt", "q.txt")
        report = cs.reap_worktrees(repos["work"], sessions=[])
        assert report.kept == [("merged-in", "1 commit(s) not in main (lane/merged-in)")], report

    def test_a_detached_head_main_holds_by_patch_is_kept(self, cs, repos):
        """A patch id ignores whitespace, and a detached HEAD has no branch to
        keep its commits after the removal (the failure-mode review): only
        ancestry removes it. Dies to: counting `=` for a detached HEAD."""
        wt = _worktree(repos, "loose")
        _identity(wt)
        _commit(wt, "p.txt")
        self._on_main_by_patch(repos, "p.txt")
        report = cs.reap_worktrees(repos["work"], sessions=[])
        assert report.kept == [("loose", "1 commit(s) not in main (detached)")], report
        assert wt.is_dir()

    def test_a_patch_read_that_did_not_answer_keeps_it_as_cannot_tell(self, cs, repos):
        wt = self._lane(repos, "unread", "p.txt")
        self._on_main_by_patch(repos, "p.txt")
        report = cs.reap_worktrees(repos["work"], sessions=[], runner=_killing(cs, ("rev-list", "--cherry-mark")))
        assert report.kept == [("unread", "git could not compare it with origin/main")], report
        assert wt.is_dir()

    def test_a_plan_left_open_in_a_worktree_main_holds_by_patch_is_named_and_removed(self, cs, repos):
        """DEF-4047's rule reads the patch answer too: the lane finished."""
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("cc/\n")
        wt = self._lane(repos, "picked-plan", "p.txt")
        (wt / "cc").mkdir()
        (wt / "cc" / "execution_plan.json").write_text('{"status": "in_progress"}', encoding="utf-8")
        self._on_main_by_patch(repos, "p.txt")
        report = cs.reap_worktrees(work, sessions=[])
        assert report.removed == ["picked-plan (its plan was never closed; the lane merged)"], report
