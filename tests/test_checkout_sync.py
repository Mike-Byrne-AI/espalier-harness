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
                          errors="replace", env=_git_env(), check=check, timeout=45)


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
            return [{"from": seat, "re": {"lane": "lane/feat"}}, {"from": seat, "re": {"lane": "lane/next"}}]

        monkeypatch.setattr(cs, "seat_live_claims", claims)
        report = cs.reap_worktrees(work, sessions=[])
        assert asked == ["work-feat"] and report.removed == [] and wt.is_dir()
        (name, reason), = report.kept
        assert name == "feat"
        assert reason.startswith("its seat work-feat holds 2 live claims (lane/feat, lane/next) that only it can")
        assert "mail.py send --type release --lane <lane>" in reason

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
                              capture_output=True, env=_git_env(), check=True, timeout=45).stdout.decode().strip()
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

    def test_a_plan_in_progress_in_it_keeps_it(self, cs, repos):
        work = repos["work"]
        with open(work / ".git" / "info" / "exclude", "a", encoding="utf-8") as exclude:
            exclude.write("cc/\n")
        wt = _worktree(repos, "planning")
        (wt / "cc").mkdir()
        (wt / "cc" / "execution_plan.json").write_text('{"status": "in_progress"}', encoding="utf-8")
        assert cs.reap_worktrees(work, sessions=[]).kept == [("planning", "a plan in it is still in progress")]

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
        assert cs.live_sessions() == [{"pid": os.getpid(), "session_id": "s1", "cwd": str(tmp_path)},
                                      {"pid": os.getpid(), "session_id": "s2", "cwd": str(home)}]

    def test_only_the_nearest_ancestor_in_the_registry_is_the_caller(self, cs, tmp_path):
        """A session launched from another session (a nested `claude -p`) has
        both as ancestors; only the nearer is the caller, and the farther one
        is another session in the checkout (the review's W4)."""
        ancestors = cs.ancestor_pids()
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
        assert payload["checkout"]["state"] == "would_catch_up"
        assert _out(work, "rev-parse", "HEAD") == before
