"""Contract tests for ``tools/cc/seat.py``: launch, list and retire a clone's
seats (TP-701 Wave B, B-2).

REAL-GIT cases, because what a seat holds is git's answer: a bare origin, a
clone named ``box`` (``git config espalier.machine``), and worktrees under its
``.claude/worktrees/`` created, named and removed by the driver; claims go out
on the scratch origin's mail refs through ``mail.py``'s own send. The session
registry is a temp config dir (``checkout_sync.claude_config_dirs`` patched),
so a "live session" is this process's pid and a gone one is a reaped child's.
``claude`` never runs: the one spawn, ``subprocess.call``, is replaced.

The pack's reds: ``launch`` with a registry entry whose cwd is the target and
whose pid is this process refuses, and with a dead pid proceeds to the print;
``retire`` on a scratch channel closes the seat's claim so ``claims`` no
longer lists it. Its named mutation, the cwd comparison dropped from the
liveness oracle, makes ``launch`` proceed into an occupied checkout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._git_oracle import _git_env

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "tools" / "cc" / "seat.py"


def _load(alias: str):
    """The importlib dance ``tests/CLAUDE.md`` mandates for a ``tools/cc`` module."""
    spec = importlib.util.spec_from_file_location(alias, MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def seat():
    # Bound by name through the loader so the derived-population census can
    # read this file (its loader-function rule); a dance inlined in the fixture
    # binds only ``spec``/``mod``, which the census reads as unresolved.
    driver = _load("seat_under_test")
    return driver


@pytest.fixture(autouse=True)
def _outside_a_session(monkeypatch):
    """The suite may run inside a Claude session; the oracle then insists the
    registry list it, and finds the caller by the ids a session exports.
    These cases are about the seat, not the caller."""
    for name in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_git_env(), check=check, timeout=45)


def _out(repo: Path, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    return child.pid


@pytest.fixture
def clone(tmp_path):
    """A bare origin with one commit and a clone of it named ``box``, with
    per-worktree config on (as SessionStart leaves a named clone)."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--quiet", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "--quiet", str(origin), str(work))
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        _git(work, "config", key, value)
    (work / ".gitignore").write_bytes(b".claude/settings.json\n.claude/worktrees/\n")
    (work / ".worktreeinclude").write_bytes(b"# copied into a new worktree\n.claude/settings.json\n")
    (work / "README.md").write_bytes(b"seed\n")
    _git(work, "add", ".gitignore", ".worktreeinclude", "README.md")
    _git(work, "commit", "--quiet", "-m", "seed")
    _git(work, "push", "--quiet", "-u", "origin", "main")
    _git(work, "remote", "set-head", "origin", "main")
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_bytes(b'{"hooks": {}}\n')
    _git(work, "config", "espalier.machine", "box")
    _git(work, "config", "extensions.worktreeConfig", "true")
    return work


def _worktree(work: Path, folder: str, *, name: str | None = None) -> Path:
    path = work / ".claude" / "worktrees" / folder
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(work, "worktree", "add", "--quiet", "-b", f"lane/{folder}", str(path), "origin/main")
    if name:
        _git(path, "config", "--worktree", "espalier.machine", name)
    if (work / "espalier.toml").is_file():   # tracked on a real tree, so every checkout holds it
        (path / "espalier.toml").write_bytes((work / "espalier.toml").read_bytes())
    return path


@pytest.fixture
def registry(seat, tmp_path, monkeypatch):
    """A session registry of this test's own: ``add(cwd, pid=...)``."""
    cfg = tmp_path / "claude-config"
    (cfg / "sessions").mkdir(parents=True)
    monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [cfg])

    def add(cwd: Path, *, pid: int | None = None, entrypoint: str = "cli") -> int:
        pid = pid or os.getpid()
        (cfg / "sessions" / f"{pid}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": f"s{pid}", "cwd": str(cwd), "kind": "interactive",
             "entrypoint": entrypoint, "startedAt": 1792045849132}), encoding="utf-8")
        return pid

    add.dir = cfg
    return add


@pytest.fixture
def no_claude(seat, monkeypatch):
    """Record the one spawn instead of running claude, as from a terminal of
    the operator's own (the suite's stdin is no terminal)."""
    monkeypatch.setattr(seat, "session_refusal", lambda: "", raising=False)
    calls: list[dict] = []
    real = seat.shutil.which
    # Only claude is faked: shutil.which is the one module every git runner shares.
    monkeypatch.setattr(seat.shutil, "which",
                        lambda name, path=None: "/fake/bin/claude" if name == "claude" else real(name, path=path))

    def call(argv, *, cwd, env):
        calls.append({"argv": argv, "cwd": cwd, "env": env})
        return 0

    monkeypatch.setattr(seat, "run_session", call)
    return calls


def _send(mod, path: Path, machine: str, type_: str, text: str, **kw) -> dict:
    message = mod.mail.new_message(machine, type_, text, **kw)
    mod.mail.send(path, message, say=lambda _s: None)
    return message


def _live_claims_from(seat, root: Path, machine: str) -> list[dict]:
    seat.mail.fetch_mail(root)
    by_machine, _ = seat.mail.read_mail(root)
    return [c for c in seat.mail.live_claims(by_machine) if c.get("from") == machine]


# -- list ----------------------------------------------------------------------------

class TestList:
    def test_the_clone_and_each_worktree_seat_are_named_with_who_is_in_them(self, seat, clone, registry):
        feat = _worktree(clone, "feat", name="box-feat")
        _worktree(clone, "plain")
        registry(clone)
        found, _note = seat.seats(clone, fetch=False)
        assert [(s.name, s.naming, s.where) for s in found] == [
            ("box", "clone", "the clone"), ("box-feat", "own", ".claude/worktrees/feat"),
            ("box-plain", "derived", ".claude/worktrees/plain")]
        assert [len(s.sessions) for s in found] == [1, 0, 0]
        assert [s.oracle for s in found] == ["registry"] * 3
        assert [s.removal for s in found] == ["", "removable", "removable"]
        text = seat.render(found, "")
        assert f"seat box -- the clone ({clone}), on main at" in text
        assert f"  sessions: pid {os.getpid()} (cli, started 2026-10-15 06:30Z)" in text
        assert "seat box-plain (name derived; SessionStart sets it) -- .claude/worktrees/plain" in text
        assert "  retire:   would remove it" in text and text.isascii()
        assert feat.is_dir()

    def test_claims_and_jobs_come_from_the_mail_refs(self, seat, clone, registry):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat", paths=["README.md"])
        _send(seat, clone, "box", "assign", "build it", lane="lane/feat-2", seat="box-feat")
        found, _note = seat.seats(clone, fetch=True)
        by_name = {s.name: s for s in found}
        assert [c["re"]["lane"] for c in by_name["box-feat"].claims] == ["lane/feat"]
        assert [j["re"]["lane"] for j in by_name["box-feat"].jobs] == ["lane/feat-2"]
        assert by_name["box"].claims == [] and by_name["box"].jobs == []
        assert by_name["box-feat"].removal.startswith("its seat box-feat holds 1 live claim (lane/feat)")

    def test_a_registry_that_cannot_be_read_says_cannot_tell(self, seat, clone, monkeypatch):
        monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [clone.parent / "no-such-config"])
        found, _note = seat.seats(clone, fetch=False)
        assert found[0].sessions is None
        assert "cannot tell (Claude Code's session registry could not be read in full" in seat.render(found, "")

    def test_the_cli_runs_from_inside_a_worktree_and_reports_the_whole_clone(self, seat, clone, registry,
                                                                             monkeypatch, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(feat)
        assert seat.main(["list", "--json", "--no-fetch"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert [s["name"] for s in payload["seats"]] == ["box", "box-feat"]


# -- launch --------------------------------------------------------------------------

class TestLaunch:
    def test_an_occupied_seat_is_refused_and_a_gone_session_is_not_occupancy(self, seat, clone, registry, no_claude,
                                                                             capsys):
        """The pack's red. Dies to: dropping the cwd comparison from the
        liveness oracle (launch then proceeds into an occupied checkout)."""
        feat = _worktree(clone, "feat", name="box-feat")
        pid = registry(feat / "src")
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        said = str(refused.value)
        assert said.startswith(f"seat box-feat is occupied: pid {pid} (cli, started 2026-10-15 06:30Z) (their "
                               f"entries are under {registry.dir / 'sessions'}) is in {feat}")
        assert "One checkout holds one session at a time" in said and "Core Rule" not in said
        (registry.dir / "sessions" / f"{pid}.json").unlink()
        registry(feat, pid=_dead_pid())
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True) == 0
        assert "claude" in capsys.readouterr().out
        assert no_claude == []

    def test_a_session_in_another_seat_does_not_occupy_this_one(self, seat, clone, registry, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        registry(clone)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True) == 0
        with pytest.raises(seat.Refused):
            seat.cmd_launch(clone, "box", [], maintenance=False, unchecked=False, print_only=True)
        assert feat.is_dir()

    def test_occupancy_nobody_can_tell_refuses_unless_unchecked(self, seat, clone, monkeypatch, capsys):
        _worktree(clone, "feat", name="box-feat")
        monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [clone.parent / "no-such-config"])
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        assert "cannot be told" in str(refused.value) and "--unchecked launches anyway" in str(refused.value)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=True, print_only=True) == 0

    def test_a_missing_seat_is_created_from_origin_named_and_given_its_include_files(self, seat, clone, registry,
                                                                                     no_claude, monkeypatch, capsys):
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        rc = seat.cmd_launch(clone, "box-new", ["--model", "x"], maintenance=False, unchecked=False, print_only=False)
        assert rc == 0
        path = clone / ".claude" / "worktrees" / "new"
        assert _out(path, "rev-parse", "--abbrev-ref", "HEAD") == "worktree-new"
        assert _out(path, "rev-parse", "HEAD") == _out(clone, "rev-parse", "origin/main")
        assert _out(path, "config", "--worktree", "--get", "espalier.machine") == "box-new"
        assert (path / ".claude" / "settings.json").read_bytes() == b'{"hooks": {}}\n'
        (call,) = no_claude
        # The operator's arguments pass through unchanged; the first message rides last.
        assert call["argv"][:3] == ["/fake/bin/claude", "--model", "x"] and Path(call["cwd"]) == path
        assert call["argv"][3:] == ["--", seat.compose_brief(clone, "box-new", path).text]
        env = call["env"]
        assert "ESPALIER_MAINTENANCE_MODE" not in env and "CLAUDE_CODE_SESSION_ID" not in env
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
        out = capsys.readouterr().out
        assert "created " in out and "copied .claude/settings.json" in out and "named this worktree box-new" in out

    def test_maintenance_is_set_only_when_asked_and_the_seats_venv_leads_the_path(self, seat, clone, registry,
                                                                                  no_claude):
        feat = _worktree(clone, "feat", name="box-feat")
        bindir = feat / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        seat.cmd_launch(clone, "box-feat", [], maintenance=True, unchecked=False, print_only=False)
        env = no_claude[0]["env"]
        assert env["ESPALIER_MAINTENANCE_MODE"] == "1"
        assert env["PATH"].split(os.pathsep)[0] == str(bindir)

    def test_the_drivers_flags_after_the_seat_are_its_own_and_claudes_follow_the_dashes(self, seat, clone, registry,
                                                                                        no_claude, monkeypatch,
                                                                                        capsys):
        """Dies to: a remainder argument, which took `--print` for claude and
        launched a session (driven 2026-10-15, before this was split)."""
        monkeypatch.chdir(clone)
        assert seat.main(["launch", "box", "--print", "--", "--model", "o p"]) == 0
        assert no_claude == []
        # The first message spans two lines inside its quotes; claude's line is its first.
        out = next(line for line in capsys.readouterr().out.splitlines() if "claude" in line)
        assert "'o p'" in out and "You are seat box" in out
        assert seat.split_claude_args(["launch", "x", "--", "--print"]) == (["launch", "x"], ["--print"])

    def test_names_that_are_no_seat_are_refused(self, seat, clone, tmp_path):
        with pytest.raises(seat.Refused, match="no seat 'nobody' here: this clone is 'box'"):
            seat.resolve(clone, "nobody")
        stray = clone / ".claude" / "worktrees" / "stray"
        stray.mkdir(parents=True)
        with pytest.raises(seat.Refused, match="exists but git does not register it as a worktree: look at what is"):
            seat.resolve(clone, "box-stray")
        _worktree(clone, "other", name="box-renamed")
        with pytest.raises(seat.Refused, match=r"is a registered worktree that answers 'box-renamed', not 'box-other'"
                                               r".*launch box-renamed"):
            seat.resolve(clone, "box-other")
        _git(clone, "config", "--unset", "espalier.machine")
        with pytest.raises(seat.Refused, match="this clone names no machine"):
            seat.resolve(clone, "box")

    def test_the_command_line_is_quoted_for_each_shell(self, seat, tmp_path):
        target = seat.Target("box-x", tmp_path / "it's here", True, False)
        ps = seat.command_line(target, ["--model", "o p", "a\u2019b"], maintenance=True, shell="powershell")
        assert ps.startswith(f"Set-Location -LiteralPath '{str(tmp_path / 'it')}''s here'; ")
        assert "$env:ESPALIER_MAINTENANCE_MODE = '1'" in ps and ps.endswith("claude '--model' 'o p' 'a\u2019\u2019b'")
        assert "Remove-Item Env:VIRTUAL_ENV" in ps
        plain = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert "Remove-Item Env:ESPALIER_MAINTENANCE_MODE" in plain
        with pytest.raises(seat.Refused, match="Windows PowerShell 5.1 splits"):
            seat.command_line(target, ['say "hi"'], maintenance=False, shell="powershell")
        sh = seat.command_line(target, ["--model", "o p"], maintenance=False, shell="posix")
        assert sh.endswith("&& env -u ESPALIER_MAINTENANCE_MODE -u VIRTUAL_ENV claude --model 'o p'")
        bindir = target.path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        with_venv = seat.command_line(target, [], maintenance=False, shell="powershell")
        assert f"$env:PATH = '{str(bindir).replace(chr(39), chr(39) * 2)};' + $env:PATH" in with_venv
        posix_venv = seat.command_line(target, [], maintenance=True, shell="posix")
        assert "env ESPALIER_MAINTENANCE_MODE=1 VIRTUAL_ENV=" in posix_venv and ':"$PATH" claude' in posix_venv

    def test_the_childs_environment_drops_the_parent_sessions_and_names_the_seats_venv(self, seat, tmp_path):
        """Read 2026-10-15: a session exports its pid, id and messaging token
        to its children, and VIRTUAL_ENV named the main checkout's .venv in a
        worktree seat's session. Dies to: dropping a name, or a prefix strip
        that also drops a user's CLAUDE_CODE_USE_BEDROCK."""
        base = {name: "x" for name in seat.SESSION_ENV}
        base.update({"CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CONFIG_DIR": "/cfg", "VIRTUAL_ENV": "/other/.venv",
                     "ESPALIER_MAINTENANCE_MODE": "1", "PATH": "/bin"})
        target = seat.Target("box-x", tmp_path, True, False)
        env = seat.child_env(target, maintenance=False, base=base)
        assert not set(seat.SESSION_ENV) & set(env)
        assert {"CLAUDECODE", "CLAUDE_CODE_MESSAGING_TOKEN", "AI_AGENT"} <= seat.SESSION_ENV
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1" and env["CLAUDE_CONFIG_DIR"] == "/cfg"
        assert "VIRTUAL_ENV" not in env and "ESPALIER_MAINTENANCE_MODE" not in env
        bindir = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        bindir.mkdir(parents=True)
        env = seat.child_env(target, maintenance=True, base=base)
        assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv") and env["PATH"].split(os.pathsep)[0] == str(bindir)

    def test_from_inside_a_session_nothing_is_created_or_started(self, seat, clone, registry, monkeypatch):
        """Dies to: a launch an AI collaborator types under its Bash tool,
        which would start a hidden child session (the stripped variables keep
        Claude Code from even knowing it is nested)."""
        monkeypatch.setattr(seat, "run_session", lambda *a, **k: pytest.fail("a session was started"))
        monkeypatch.setenv("CLAUDECODE", "1")
        with pytest.raises(seat.Refused, match="runs inside a Claude Code session"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert not (clone / ".claude" / "worktrees" / "new").exists()
        monkeypatch.delenv("CLAUDECODE")
        with pytest.raises(seat.Refused, match="standard input is not a terminal"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)

    def test_an_existing_seat_without_its_settings_gets_them_before_it_starts(self, seat, clone, registry,
                                                                              no_claude, capsys):
        """A worktree made by hand, or before .worktreeinclude, or left by a
        failed create. Dies to: copying only on create, so the session starts
        with no hook at all."""
        feat = _worktree(clone, "feat", name="box-feat")
        assert not (feat / ".claude" / "settings.json").exists()
        seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False)
        assert (feat / ".claude" / "settings.json").read_bytes() == b'{"hooks": {}}\n'
        assert "copied .claude/settings.json from the clone" in capsys.readouterr().out

    def test_include_entries_it_cannot_take_are_said_not_raised(self, seat, clone):
        (clone / ".worktreeinclude").write_bytes(
            b".claude/settings.json\n!negated.txt\n/anchored.json\nconf/\n/nonexistent*\n")
        (clone / "anchored.json").write_bytes(b"{}\n")
        (clone / ".gitignore").write_bytes(b".claude/settings.json\n.claude/worktrees/\nanchored.json\n")
        target = clone / "plain-dir"
        target.mkdir()
        copied, skipped = seat.copy_includes(clone, target)
        assert copied == [".claude/settings.json", "anchored.json"]
        assert [s.split(" ")[0] for s in skipped] == ["!negated.txt", "conf/"]

    def test_a_worktrees_folder_git_does_not_ignore_is_refused_before_anything_is_made(self, seat, clone, registry,
                                                                                       no_claude):
        (clone / ".gitignore").write_bytes(b".claude/settings.json\n")
        with pytest.raises(seat.Refused, match=r"\.claude/worktrees/new/ is not ignored by git here"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert not (clone / ".claude" / "worktrees" / "new").exists()

    def test_a_leftover_merged_branch_is_reused_and_unmerged_work_is_not(self, seat, clone, registry, no_claude,
                                                                        capsys):
        _git(clone, "branch", "worktree-new", "origin/main")
        seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert "deleted the leftover branch worktree-new" in capsys.readouterr().out
        _git(clone, "worktree", "remove", "--force", str(clone / ".claude" / "worktrees" / "new"))
        _git(clone, "switch", "--quiet", "worktree-new")
        (clone / "w.txt").write_bytes(b"w\n")
        _git(clone, "add", "w.txt")
        _git(clone, "commit", "--quiet", "-m", "work")
        _git(clone, "switch", "--quiet", "main")
        with pytest.raises(seat.Refused, match="a branch worktree-new already exists with work origin/main lacks"):
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)

    def test_a_session_only_a_marker_names_passes_with_unchecked(self, seat, clone, registry, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")
        marker = {"session_id": "m1", "pid": os.getpid(), "cwd": str(feat)}
        monkeypatch.setattr(seat.sync, "_default_marker_reader",
                            lambda: (lambda tree: [marker] if seat.sync._norm(tree) == seat.sync._norm(feat) else []))
        with pytest.raises(seat.Refused, match="only a session marker names it: --unchecked passes it"):
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=True)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=True, print_only=True) == 0
        registry(feat)
        with pytest.raises(seat.Refused, match="is occupied"):
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=True, print_only=True)


# -- brief ---------------------------------------------------------------------------

#: The worker tick as the operator pasted it on 2026-10-15 18:56Z (mail note
#: 215fbb, verbatim): the self-host render must reproduce it byte for byte.
_OPERATOR_TICK = (
    "/loop 10m Worker tick. Run /inbox (mark read) and /inbox board and read live state. Act only on what is "
    "yours, in this order: your own open PR red, in conflict or stale (fix it, or ship.py catch-up); a new "
    "assign or note from air; continue your current lane through its full procedure (plan, red-team both "
    "reviewers on a snapshot clone, one fix batch, the tier the diff earns with --base origin/main, one open PR "
    "per seat, every step listed with its evidence in the PR body; a skipped step is a stop); then your next "
    "assigned job. STOP and send air one request, then only re-read mail until it is answered, on anything not "
    "green: a red you cannot fix in two attempts, a choice the assign does not settle, a refusal you cannot "
    "resolve, a conflict outside your own files, anything that is the operator's decision. Never unassigned "
    "work, never another seat's branch. A quiet tick is one line."
)


def _dispatcher(clone: Path, value: str) -> None:
    """The ``dispatcher`` line, written where a tracked espalier.toml would be:
    the clone and every worktree of it (the brief reads the seat's own copy)."""
    homes = [clone, *sorted((clone / ".claude" / "worktrees").glob("*"))]
    for home in homes:
        (home / "espalier.toml").write_text(f"dispatcher = {value}\n", encoding="utf-8")


def _holds(path: Path, *rels: str) -> None:
    for rel in rels:
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_bytes(b"x\n")


class TestBrief:
    """B-7: a seat's first message is composed by the tool, never pasted.
    Dies to: the self-host render drifting from the operator's tick, a form
    naming a protocol home its checkout does not hold, or a double quote
    (Windows PowerShell 5.1 splits a native argument there)."""

    def test_a_worker_on_this_repository_gets_the_operators_tick_verbatim(self, seat, clone):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "memory/parallel-work-protocol.md", "docs/WORKFLOW.md", "scripts/proof_tier.py")
        brief = seat.compose_brief(clone, "box-feat", feat)
        first, loop = brief.text.split("\n")
        assert brief.role == "worker" and loop == brief.loop == _OPERATOR_TICK
        assert first.startswith("You are seat box-feat, a worker under the dispatcher air (Core Rule 15, "
                                "memory/parallel-work-protocol.md). Orient from the banner, then run /inbox")
        assert first.endswith("Then start the worker loop on the next line with no further message from the operator.")

    def test_an_adopter_worker_is_pointed_at_what_its_checkout_holds(self, seat, clone):
        _dispatcher(clone, '"hub"')
        feat = _worktree(clone, "feat", name="box-feat")
        _holds(feat, "docs/WORKFLOW.md")
        seeded = seat.compose_brief(clone, "box-feat", feat)
        assert "a worker under the dispatcher hub (docs/WORKFLOW.md, Parallel seats)." in seeded.text
        assert "the proof the change earns per /implement-task step 7" in seeded.loop and "--base" not in seeded.text
        assert "both reviewers at once with your edits frozen per /implement-task step 6" in seeded.loop
        assert "snapshot clone" not in seeded.text   # defined on this repository only
        assert "note from hub;" in seeded.loop and "send hub one request" in seeded.loop
        assert "memory/" not in seeded.text and "Core Rule" not in seeded.text
        bare = seat.compose_brief(clone, "box-feat", clone / "no-such-checkout")   # the clone holds neither
        assert "(the /inbox command's body)" in bare.text

    def test_with_no_dispatcher_named_a_worker_answers_to_the_operator(self, seat, clone):
        brief = seat.compose_brief(clone, "box", clone)
        assert brief.role == "worker"
        assert "a worker under the operator (espalier.toml names no dispatcher)" in brief.text
        assert "note from the operator;" in brief.loop and "send the operator one request" in brief.loop

    def test_the_dispatcher_seat_gets_the_board_loop_and_its_duties(self, seat, clone):
        _dispatcher(clone, '"box"')
        _holds(clone, "memory/parallel-work-protocol.md")
        brief = seat.compose_brief(clone, "box", clone)
        first, loop = brief.text.split("\n")
        assert brief.role == "dispatcher" and loop == brief.loop == "/loop 15m /inbox board"
        assert first.startswith("You are the dispatcher seat box (Core Rule 15, memory/parallel-work-protocol.md). "
                                "Orient from the banner, then run /inbox (mark read) and /inbox board.")
        assert "revert first on a red main" in first and "Decisions stay the operator's." in first
        assert "model" not in first   # the operator's own setting, never the template's
        _holds(clone, "cc/GOAL.md")
        assert "Orient from the banner and cc/GOAL.md's notes, then" in seat.compose_brief(clone, "box", clone).text

    def test_an_unusable_dispatcher_setting_refuses_the_brief_and_launch_names_the_way_past(self, seat, clone,
                                                                                            registry, no_claude):
        _dispatcher(clone, '"Not A Name"')   # not lowercase letters, digits and hyphens
        with pytest.raises(seat.Refused, match="the brief names the dispatcher, and "):
            seat.compose_brief(clone, "box", clone)
        _worktree(clone, "feat", name="box-feat")
        with pytest.raises(seat.Refused, match="--no-brief launches without the first message"):
            seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False)
        with pytest.raises(seat.Refused, match="the brief names the dispatcher"):   # before the worktree is made
            seat.cmd_launch(clone, "box-new", [], maintenance=False, unchecked=False, print_only=False)
        assert not (clone / ".claude" / "worktrees" / "new").exists()
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False,
                               brief=False) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude"]

    def test_every_form_is_ascii_with_no_double_quote_and_survives_both_shells(self, seat, clone, tmp_path):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        worker = seat.compose_brief(clone, "box-feat", clone)
        _holds(feat, "memory/parallel-work-protocol.md", "scripts/proof_tier.py")
        self_host = seat.compose_brief(clone, "box-feat", feat)
        _dispatcher(clone, '"box"')
        _holds(clone, "cc/GOAL.md")
        dispatcher = seat.compose_brief(clone, "box", clone)
        target = seat.Target("box-feat", feat, True, False)
        for brief in (worker, self_host, dispatcher):
            assert brief.text.isascii() and '"' not in brief.text and "%" not in brief.text, brief.text
            assert not set(brief.text) & set(seat._PS_DOUBLE)
            # Both --print forms quote it whole, so it reaches claude as one argument.
            assert seat.command_line(target, [brief.text], maintenance=False, shell="powershell")
            line = seat.command_line(target, [brief.text], maintenance=False, shell="posix")
            assert seat.shlex.split(line.split(" claude ", 1)[1]) == [brief.text]

    def test_launch_passes_the_brief_last_and_no_brief_drops_it(self, seat, clone, registry, no_claude, monkeypatch,
                                                                capsys):
        _dispatcher(clone, '"air"')
        feat = _worktree(clone, "feat", name="box-feat")
        monkeypatch.chdir(clone)
        assert seat.main(["launch", "box-feat", "--", "--model", "x"]) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", "--model", "x", "--",
                                         seat.compose_brief(clone, "box-feat", feat).text]
        assert seat.main(["launch", "box-feat", "--no-brief", "--", "--model", "x"]) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", "--model", "x"]
        assert "no first message" in capsys.readouterr().out
        assert seat.main(["brief", "box-feat"]) == 0
        assert capsys.readouterr().out == seat.compose_brief(clone, "box-feat", feat).text + "\n"

    def test_an_adopters_dispatcher_proposes_the_revert_and_this_repository_reverts_first(self, seat, clone):
        """Reverting first on a red base is this repository's rule; an
        adopter's dispatcher loop must not do it unasked. Dies to: the
        self-host duty rendered for every tree."""
        _dispatcher(clone, '"box"')
        _holds(clone, "docs/WORKFLOW.md")
        adopter = seat.compose_brief(clone, "box", clone).text
        assert "propose the revert to the operator on a red main" in adopter and "revert first" not in adopter
        _holds(clone, "memory/parallel-work-protocol.md")
        assert "revert first on a red main" in seat.compose_brief(clone, "box", clone).text

    @pytest.mark.contract   # it reads a shipped command body (tests/test_marker_taxonomy.py)
    def test_the_adopter_phrases_name_steps_the_shipped_command_body_holds(self, seat):
        """The adopter tick points at /implement-task's steps by number: a
        step inserted into the shipped body would re-point every adopter
        seat. Dies to: a renumbered body with the phrases left behind."""
        body = (REPO_ROOT / "espalier" / "assets" / "claude" / "commands" / "implement-task.md").read_text(
            encoding="utf-8")
        steps = body.splitlines()
        assert seat.ADOPTER_REVIEW.endswith("per /implement-task step 6")
        assert any(s.startswith("6. **Review before the one full run.") for s in steps)
        assert any(s.startswith("7. **Run the proof tier once") for s in steps)

    @pytest.mark.parametrize("args", [["-p"], ["--print"], ["--resume"], ["--resume=abc"], ["-c"], ["--continue"],
                                      ["--teleport"], ["fix this"], ["--model", "x", "--", "fix this"]])
    def test_the_brief_is_refused_beside_a_mode_flag_or_a_prompt_of_its_own(self, seat, clone, registry, no_claude,
                                                                           args):
        """Dies to: passing the brief beside them (two prompts, or a resumed
        session that never reads it)."""
        _worktree(clone, "feat", name="box-feat")
        with pytest.raises(seat.Refused, match="--no-brief launches without the first message"):
            seat.cmd_launch(clone, "box-feat", args, maintenance=False, unchecked=False, print_only=False)
        assert no_claude == []
        assert seat.cmd_launch(clone, "box-feat", args, maintenance=False, unchecked=False, print_only=False,
                               brief=False) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *args]

    def test_a_list_option_keeps_its_values_and_the_brief_follows_a_dashdash(self, seat, clone, registry, no_claude):
        """Driven on 2.1.301: a prompt after `--add-dir <dir>` was read as a
        second directory and the session had no prompt; after a `--` it was
        answered. Dies to: the brief appended bare."""
        feat = _worktree(clone, "feat", name="box-feat")
        args = ["--add-dir", "a", "b"]
        assert seat.cmd_launch(clone, "box-feat", args, maintenance=False, unchecked=False, print_only=False) == 0
        assert no_claude[-1]["argv"] == ["/fake/bin/claude", *args, "--",
                                         seat.compose_brief(clone, "box-feat", feat).text]

    def test_a_cmd_shim_refuses_the_brief_because_cmd_cuts_it_at_its_line_break(self, seat, clone, registry,
                                                                                no_claude, monkeypatch):
        """Driven by the failure-mode review on this host: a .cmd given the
        two-line brief received only its first line, so the loop never
        arrived. Dies to: launching through the shim with the brief."""
        _worktree(clone, "feat", name="box-feat")
        real = seat.shutil.which
        monkeypatch.setattr(seat.shutil, "which", lambda name, path=None:
                            "C:/npm/claude.CMD" if name == "claude" else real(name, path=path))
        for print_only in (False, True):
            with pytest.raises(seat.Refused, match="a script cmd.exe runs, which cuts an argument at its line break"):
                seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=print_only)
        assert seat.cmd_launch(clone, "box-feat", [], maintenance=False, unchecked=False, print_only=False,
                               brief=False) == 0

    def test_the_banner_line_is_the_short_form_of_the_same_brief(self, seat, clone):
        """Its interval is read from the loop each form ends with, so the two
        cannot drift. Dies to: an interval spelled apart from the template."""
        _dispatcher(clone, '"box"')
        worker = seat.compose_brief(clone, "box-feat", None)
        dispatcher = seat.compose_brief(clone, "box", None)
        assert seat.brief_line(worker.role, "box-feat", "py -3") == (
            "run /inbox, then /inbox board, then start the worker loop (/loop 10m); "
            "py -3 tools/cc/seat.py brief box-feat prints the first message")
        assert worker.loop.startswith("/loop 10m ")
        assert seat.brief_line(dispatcher.role, "box") == (
            "run /inbox, then /inbox board, then start the board loop (/loop 15m)")
        assert dispatcher.loop.startswith("/loop 15m ")


# -- retire --------------------------------------------------------------------------

class TestRetire:
    def test_a_seats_claims_are_released_under_its_own_name_then_its_worktree_goes(self, seat, clone, registry,
                                                                                    capsys):
        """The pack's red: the protocol's open item 5. Dies to: removing the
        worktree before the release (the claim then stays live with no seat
        left to close it), or sending the release under the clone's name."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat", paths=["README.md"])
        _send(seat, feat, "box-feat", "claim", "a row", ids=["DEF-1"])
        assert len(_live_claims_from(seat, clone, "box-feat")) == 2
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True) == 0
        assert _live_claims_from(seat, clone, "box-feat") == []
        assert not feat.exists() and "lane/feat" not in _out(clone, "branch", "--format=%(refname:short)").split()
        origin_file = _out(clone.parent / "origin.git", "show", "refs/heads/mail/box-feat:mail.jsonl")
        releases = [json.loads(ln) for ln in origin_file.splitlines() if json.loads(ln)["type"] == "release"]
        assert [r["from"] for r in releases] == ["box-feat", "box-feat"]
        out = capsys.readouterr().out
        assert f"retired box-feat: removed {feat}" in out

    def test_an_occupied_seat_is_neither_released_nor_removed(self, seat, clone, registry):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        registry(feat)
        with pytest.raises(seat.Refused, match="seat box-feat is occupied"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1

    def test_occupancy_nobody_can_tell_releases_and_removes_nothing(self, seat, clone, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        monkeypatch.setattr(seat.sync, "claude_config_dirs", lambda: [clone.parent / "no-such-config"])
        with pytest.raises(seat.Refused, match="cannot be told"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1

    def test_a_seat_holding_jobs_is_refused_unless_they_are_handed_back(self, seat, clone, registry, capsys):
        """The dispatcher's job and the seat's claim on ONE lane (the ordinary
        case). Dies to: a release by lane, which closes the job too while the
        driver says it left jobs alone (the failure-mode review drove it)."""
        feat = _worktree(clone, "feat", name="box-feat")
        assign = _send(seat, clone, "box", "assign", "build it", lane="lane/feat", seat="box-feat")
        claim = _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        with pytest.raises(seat.Refused, match=r"seat box-feat holds 1 job\(s\) from the dispatcher \(lane/feat\)"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        by_machine, _ = seat.mail.read_mail(clone)
        assert [j["id"] for j in seat.mail.live_assignments(by_machine)] == [assign["id"]]
        assert len(_live_claims_from(seat, clone, "box-feat")) == 1 and feat.is_dir()
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True, return_jobs=True) == 0
        origin_file = _out(clone.parent / "origin.git", "show", "refs/heads/mail/box-feat:mail.jsonl")
        releases = [json.loads(ln) for ln in origin_file.splitlines() if json.loads(ln)["type"] == "release"]
        assert [(r["ack"], r["re"]["lane"]) for r in releases] == [(claim["id"], ""), (assign["id"], "")]
        assert "goes back to the dispatcher" in releases[1]["text"]
        by_machine, _ = seat.mail.read_mail(clone)
        assert seat.mail.live_assignments(by_machine) == [] and not feat.exists()

    def test_a_worktree_that_must_stay_keeps_its_claims(self, seat, clone, registry):
        """Live claims usually mean unpushed work. Dies to: releasing first and
        judging the removal after, which leaves the work kept and unclaimed."""
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        (feat / "work.txt").write_bytes(b"unpushed\n")
        _git(feat, "add", "work.txt")
        _git(feat, "commit", "--quiet", "-m", "work not on main")
        with pytest.raises(seat.Refused, match=r"would be kept \(1 commit\(s\) not in main \(lane/feat\)\), so "
                                               r"nothing was released"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=True)
        assert len(_live_claims_from(seat, clone, "box-feat")) == 1 and feat.is_dir()

    def test_a_channel_that_cannot_be_read_retires_nothing(self, seat, clone, registry, monkeypatch):
        feat = _worktree(clone, "feat", name="box-feat")

        def unreadable(root, **kw):
            raise seat.mail.Unresolvable("git for-each-ref failed")

        monkeypatch.setattr(seat.mail, "read_mail", unreadable)
        with pytest.raises(seat.Refused, match="the mail channel could not be read .* nothing is released or removed"):
            seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=False)
        assert feat.is_dir()

    def test_a_dead_holders_lock_is_released_and_said(self, seat, clone, registry, capsys):
        feat = _worktree(clone, "feat", name="box-feat")
        gone = _dead_pid()
        _git(clone, "worktree", "lock", "--reason", f"claude session feat (pid {gone})", str(feat))
        assert seat.cmd_retire(clone, "box-feat", dry_run=False, fetch=False) == 0
        assert f"unlocked feat (pid {gone}): the lock's holder has exited" in capsys.readouterr().out

    def test_a_seat_whose_worktree_is_gone_gets_the_recipe(self, seat, clone, registry):
        gone = _worktree(clone, "gone", name="box-gone")
        _send(seat, gone, "box-gone", "claim", "lost", lane="lane/gone")
        _git(clone, "worktree", "remove", "--force", str(gone))
        with pytest.raises(seat.Refused) as refused:
            seat.cmd_retire(clone, "box-gone", dry_run=False, fetch=True)
        said = str(refused.value)
        assert said.startswith("seat box-gone holds 1 live claim(s) and its worktree is gone")
        assert "git worktree add --detach .claude/worktrees/gone origin/main" in said
        assert "git -C .claude/worktrees/gone config --worktree espalier.machine box-gone" in said
        assert "python tools/cc/mail.py send --type release --lane lane/gone" in said

    def test_the_clone_itself_is_never_retired_and_a_dry_run_changes_nothing(self, seat, clone, registry, capsys):
        with pytest.raises(seat.Refused, match="box is the clone itself"):
            seat.cmd_retire(clone, "box", dry_run=False, fetch=False)
        feat = _worktree(clone, "feat", name="box-feat")
        _send(seat, feat, "box-feat", "claim", "the feature", lane="lane/feat")
        seat.cmd_retire(clone, "box-feat", dry_run=True, fetch=True)
        out = capsys.readouterr().out
        assert "dry-run: would release 1 claim(s) of box-feat (lane/feat)" in out
        assert feat.is_dir() and len(_live_claims_from(seat, clone, "box-feat")) == 1
