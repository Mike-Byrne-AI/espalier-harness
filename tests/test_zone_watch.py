"""TP-476 wave A-1: the protected zones compared after every shell call.

Why: a shell call changes a protected file without naming it -- a formatter
over the whole tree, a script, a copy -- and write_guard's path check reads
only the command's words. Wave A-1 snapshots the watched files per session and
reports, after each Bash or PowerShell call, a change that no legitimate path
accounts for (the pack's decision of 2026-10-08: a guard selective enough that
when it fires, the only right response is to stop and tell the operator). A
change that landed before the call began goes to the operator's line only (the
operator's decision of 2026-10-09).

Each earn-the-red test names the mutation it was seen red against.
"""
# slow-exempt: a few deployed-hook, git and import subprocesses over scratch trees, about a second each
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

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "cc" / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_a1", HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


zw = _load("_zone_watch")
hu = zw._hook_utils
_HOOK = "tools/cc/hooks/write_guard.py"
_OTHER = "tools/cc/hooks/plan_guard.py"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """An adopter-shaped tree: two deployed hooks, a cc/ state file, the two
    settings files, a bytecode cache. Bytes throughout: a text-mode write is
    CRLF already on Windows."""
    hooks = tmp_path / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "write_guard.py").write_bytes(b"print('guard')\n")
    (hooks / "plan_guard.py").write_bytes(b"print('plan')\n")
    (hooks / "__pycache__").mkdir()
    (hooks / "__pycache__" / "write_guard.cpython-312.pyc").write_bytes(b"\x00pyc")
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "execution_plan.json.lock").write_bytes(b"")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_bytes(b'{"hooks": {}}\n')
    (tmp_path / ".claude" / "settings.local.json").write_bytes(b'{"permissions": {"allow": []}}\n')
    return tmp_path


def _bump(path: Path, text: str, *, ago_s: float | None = None) -> None:
    """Rewrite ``path``; its mtime moves clearly past the racy window, or to
    ``ago_s`` seconds in the past (a change made before the call began)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    when = time.time_ns() + (-int(ago_s * 1e9) if ago_s is not None else 5_000_000_000)
    os.utime(path, ns=(when, when))


def _run(tree: Path, script: str, payload: dict, *, hooks_dir: Path = HOOKS_DIR,
         extra_env: dict | None = None) -> "subprocess.CompletedProcess[str]":
    """Run a deployed hook over ``tree``: the project dir pointed at it, the
    audit log kept in it, and the launching session's harness variables
    removed so the run is this tree's alone."""
    from tests._interpreter_hosts import HOOK_PYTHON

    env = {k: v for k, v in os.environ.items() if not k.startswith(("ESPALIER_", "CLAUDE_"))}
    env["CLAUDE_PROJECT_DIR"] = str(tree)
    env["ESPALIER_AUDIT_DIR"] = str(tree / ".audit")
    env.update(extra_env or {})
    return subprocess.run(
        [HOOK_PYTHON, str(hooks_dir / script)], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, env=env, cwd=str(tree),
    )


def _post(tree: Path, tool: str, tool_input: dict, sid: str = "s-1", *,
          duration_ms: int | None = None, **kw) -> dict:
    """post_write_check on one payload; its JSON object ({} for a quiet run)."""
    payload = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tool_input,
               "session_id": sid, "cwd": str(tree)}
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    result = _run(tree, "post_write_check.py", payload, **kw)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else {}


def _context(obj: dict) -> str:
    return obj.get("hookSpecificOutput", {}).get("additionalContext", "")


_FORMATTER = {"command": "ruff format ."}  # names nothing in any zone
_NO_OP = {"command": "git status"}


def _audit(tree: Path) -> list[dict]:
    rows = []
    for log in (tree / ".audit").glob("*.log"):
        rows += [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def _audit_types(tree: Path) -> list[str]:
    return [r.get("event_type") for r in _audit(tree)]


class TestTheWatchedSet:
    def test_hooks_are_watched_and_cc_state_and_the_settings_files_are_not(self, tree: Path) -> None:
        """The settings files are config_guard's: it sees every settings change,
        Claude Code's own permission writes included. Mutation: watch cc/."""
        snap = zw.snapshot(tree)
        assert _HOOK in snap
        assert not any(rel.startswith("cc/") for rel in snap)
        assert ".claude/settings.json" not in snap and ".claude/settings.local.json" not in snap

    def test_bytecode_caches_dependencies_and_clutter_are_never_snapshotted(self, tree: Path) -> None:
        """Earn-the-red 7 and the clutter rows. Mutations: drop the cache
        prune; drop the clutter skip."""
        hooks = tree / "tools" / "cc" / "hooks"
        for rel in (".mypy_cache/x.json", "node_modules/pkg/index.js", "tools/.ruff_cache/x"):
            (hooks / rel).parent.mkdir(parents=True, exist_ok=True)
            (hooks / rel).write_bytes(b"x")
        for name in (".DS_Store", "write_guard.py.swp", "write_guard.py~", ".#write_guard.py",
                     ".write_guard.py.1a2b3c4d.tmp"):
            (hooks / name).write_bytes(b"x")
        assert sorted(zw.snapshot(tree)) == [_OTHER, _HOOK]
        assert not zw.is_watched(tree, "tools/cc/hooks/__pycache__/write_guard.cpython-312.pyc")
        assert not zw.is_watched(tree, "tools/cc/hooks/.DS_Store")

    def test_an_adopter_protected_path_is_watched_and_a_generated_one_is_not(self, tree: Path) -> None:
        (tree / "espalier.toml").write_text(
            'protected_paths = ["vault/"]\ngenerated_paths = ["build/"]\n', encoding="utf-8")
        for top in ("vault", "build"):
            (tree / top).mkdir()
            (tree / top / "f.txt").write_bytes(b"x\n")
        snap = zw.snapshot(tree)
        assert "vault/f.txt" in snap
        assert "build/f.txt" not in snap

    def test_a_declared_dependency_dir_is_pruned(self, tree: Path) -> None:
        (tree / "espalier.toml").write_text(
            'protected_paths = ["vault/"]\ndependency_dirs = ["third_party"]\n', encoding="utf-8")
        (tree / "vault" / "third_party").mkdir(parents=True)
        (tree / "vault" / "third_party" / "lib.py").write_bytes(b"x\n")
        (tree / "vault" / "mine.py").write_bytes(b"x\n")
        snap = zw.snapshot(tree)
        assert "vault/mine.py" in snap and "vault/third_party/lib.py" not in snap

    def test_a_large_file_is_identified_by_its_stat_and_never_read(self, tree: Path, monkeypatch) -> None:
        """A model or data file must not cost a hook its timeout. Mutation:
        hash every file whatever its size."""
        big = tree / "tools" / "cc" / "weights.bin"
        with big.open("wb") as fh:
            fh.truncate(zw.BIG_FILE_BYTES + 1)
        real = Path.read_bytes

        def guarded(self):
            assert self.name != "weights.bin", "a large file was read"
            return real(self)

        monkeypatch.setattr(Path, "read_bytes", guarded)
        assert zw.snapshot(tree)["tools/cc/weights.bin"][2].startswith("stat:")

    def test_a_watched_set_past_the_walk_budget_turns_the_check_off_and_says_why(self, tree: Path, monkeypatch) -> None:
        """A hook that times out reports nothing and costs every later call.
        Mutation: walk without a budget."""
        monkeypatch.setattr(zw, "WALK_FILE_BUDGET", 1)
        assert zw.take_baseline(tree, "s-1")
        result = zw.after_shell_call(tree, "s-1")
        assert result is not None and result["status"] == "off"


class TestTheSnapshotAndDiff:
    def test_a_content_change_an_addition_and_a_removal_are_each_named(self, tree: Path) -> None:
        before = zw.snapshot(tree)
        _bump(tree / _HOOK, "print('changed')\n")
        (tree / "tools" / "cc" / "hooks" / "new_hook.py").write_bytes(b"x = 1\n")
        (tree / _OTHER).unlink()
        after = zw.snapshot(tree, before)
        assert zw.diff(before, after) == {
            "changed": [_HOOK], "added": ["tools/cc/hooks/new_hook.py"], "removed": [_OTHER]}

    def test_a_line_ending_change_alone_is_no_change(self, tree: Path) -> None:
        """The digest is the integrity manifest's canon, never raw bytes.
        Mutation: hash raw bytes."""
        before = zw.snapshot(tree)
        target = tree / _HOOK
        target.write_bytes(b"print('guard')\r\n")
        later = time.time_ns() + 5_000_000_000
        os.utime(target, ns=(later, later))
        assert zw.diff(before, zw.snapshot(tree, before)) == {"changed": [], "added": [], "removed": []}

    def test_an_unmoved_stat_keeps_the_prior_digest_without_a_read(self, tree: Path) -> None:
        target = tree / _HOOK
        st = target.stat()
        before = zw.snapshot(tree)
        target.write_bytes(b"print('GUARD')\n")  # same size
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        after = zw.snapshot(tree, before, st.st_mtime_ns + 10 * zw.RACY_WINDOW_NS)
        assert after[_HOOK] is before[_HOOK]

    def test_a_racy_entry_is_hashed_again(self, tree: Path) -> None:
        """Mutation: drop the racy window, and this same-size rewrite is missed."""
        target = tree / _HOOK
        st = target.stat()
        before = zw.snapshot(tree)
        target.write_bytes(b"print('GUARD')\n")
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        assert zw.diff(before, zw.snapshot(tree, before, st.st_mtime_ns))["changed"] == [_HOOK]


class TestTheBaseline:
    def test_it_round_trips_and_a_malformed_one_reads_as_none(self, tree: Path) -> None:
        assert zw.take_baseline(tree, "s-1")
        path = zw.baseline_path(tree, "s-1")
        record = zw.read_baseline(path)
        assert record is not None and _HOOK in record["files"]
        for bad in (b"", b"[]", b'{"v": 1}', b'{"v": 2, "taken_ns": 1, "files": {"a": [1]}}'):
            path.write_bytes(bad)
            assert zw.read_baseline(path) is None

    def test_it_sits_beside_the_marker_where_the_marker_readers_never_look(self, tree: Path) -> None:
        assert hu.write_session_marker(tree, "sid-1", pid=1234, source="startup")
        assert zw.take_baseline(tree, "sid-1")
        assert zw.baseline_path(tree, "sid-1").parent == hu.sessions_dir(tree)
        assert [row["session_id"] for row in hu.other_live_sessions(tree, "sid-2")] == ["sid-1"]

    def test_the_marker_sweeps_retire_it(self, tree: Path) -> None:
        for sid in ("old", "window", "orphan"):
            hu.write_session_marker(tree, sid, pid=4242 if sid == "window" else 1)
            zw.take_baseline(tree, sid)
        directory = hu.sessions_dir(tree)
        (directory / "orphan.json").unlink()
        ancient = time.time() - hu.SESSION_MARKER_PRUNE_S - 60
        for name in ("old.json", "old.zones", "old.zones.lock", "orphan.zones", "orphan.zones.lock"):
            os.utime(directory / name, (ancient, ancient))
        assert hu.prune_session_markers(tree) == 1
        assert hu.retire_same_window_markers(tree, "new", 4242) == ["window"]
        assert sorted(p.name for p in directory.iterdir()) == []

    def test_a_fresh_sessions_baseline_is_kept_by_the_age_sweep(self, tree: Path) -> None:
        hu.write_session_marker(tree, "live", pid=1)
        zw.take_baseline(tree, "live")
        assert hu.prune_session_markers(tree) == 0
        assert zw.baseline_path(tree, "live").is_file()

    def test_an_id_nothing_survives_of_has_no_baseline(self, tree: Path) -> None:
        assert zw.baseline_path(tree, "../..") is None
        assert zw.take_baseline(tree, "") is False

    def test_a_compaction_keeps_what_the_session_knows(self, tree: Path) -> None:
        """A compaction continues the same process. Mutation: retake on every source."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('an edit')\n")
        zw.after_file_tool(tree, "s-1", [_HOOK])
        assert zw.take_baseline(tree, "s-1", keep_valid=True)
        assert _HOOK in zw.read_baseline(zw.baseline_path(tree, "s-1"))["known"]
        assert zw.take_baseline(tree, "s-1")
        assert zw.read_baseline(zw.baseline_path(tree, "s-1"))["known"] == {}


def _session_start(tree: Path, source: str, sid: str = "s-1") -> None:
    result = _run(tree, "session_start.py", {"hook_event_name": "SessionStart", "source": source, "session_id": sid})
    assert result.returncode == 0, result.stderr


class TestSessionStartTakesTheBaseline:
    @pytest.mark.parametrize("source", ["startup", "compact"])
    def test_a_start_of_either_kind_writes_this_sessions_baseline(self, tree: Path, source: str) -> None:
        """Mutation: drop the job."""
        _session_start(tree, source)
        record = zw.read_baseline(zw.baseline_path(tree, "s-1"))
        assert record is not None and _HOOK in record["files"]

    def test_a_compact_start_keeps_the_baseline_and_a_startup_retakes_it(self, tree: Path) -> None:
        """Mutation: pass keep_valid=False on compact."""
        _session_start(tree, "startup")
        _bump(tree / _HOOK, "print('an edit')\n")
        zw.after_file_tool(tree, "s-1", [_HOOK])
        _session_start(tree, "compact")
        assert _HOOK in zw.read_baseline(zw.baseline_path(tree, "s-1"))["known"]
        _session_start(tree, "startup")
        assert zw.read_baseline(zw.baseline_path(tree, "s-1"))["known"] == {}


class TestTheAfterCheck:
    def test_a_zone_change_through_a_command_that_names_no_zone_is_reported(self, tree: Path) -> None:
        """Earn-the-red 1, spelling independence, as the measured named-user
        case: a whole-tree formatter. Mutation: delete the shell branch."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('reformatted')\n")
        text = _context(_post(tree, "Bash", _FORMATTER))
        assert f"changed {_HOOK}" in text and "Stop and tell the operator" in text
        assert "post_shell_zone_change" in _audit_types(tree)

    def test_drift_already_present_is_silent(self, tree: Path) -> None:
        """Earn-the-red 2. Mutation: compare against verify_integrity."""
        zw._integrity.write_manifest(tree)
        _bump(tree / _HOOK, "print('drifted before the session')\n")
        assert zw._integrity.verify_integrity(tree)[0] is False
        assert zw.take_baseline(tree, "s-1")
        assert _context(_post(tree, "Bash", _NO_OP)) == ""

    def test_a_file_tool_write_is_refreshed_not_reported(self, tree: Path) -> None:
        """Earn-the-red 4. Mutation: drop the file tool's refresh."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('edited')\n")
        assert "protected files" not in _context(_post(tree, "Edit", {"file_path": str(tree / _HOOK)}))
        assert _context(_post(tree, "Bash", _NO_OP)) == ""

    def test_the_harness_state_under_cc_is_silent(self, tree: Path) -> None:
        """Earn-the-red 5. Mutation: watch cc/."""
        assert zw.take_baseline(tree, "s-1")
        (tree / "cc" / "blueprints").mkdir(parents=True)
        (tree / "cc" / "blueprints" / "20261009-node.json").write_bytes(b"{}\n")
        _bump(tree / "cc" / "execution_plan.json.lock", "x")
        assert _context(_post(tree, "Bash", _NO_OP)) == ""

    def test_a_settings_file_rewritten_by_claude_code_is_left_to_config_guard(self, tree: Path) -> None:
        """A "don't ask again" click writes settings.local.json before the
        command runs. Mutation: watch the settings files."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / ".claude" / "settings.local.json", '{"permissions": {"allow": ["Bash(npm test)"]}}\n')
        _bump(tree / _HOOK, "print('a hook in the same call')\n")
        text = _context(_post(tree, "Bash", {"command": "npm test"}))
        assert f"changed {_HOOK}" in text and "settings" not in text

    def test_the_operator_is_told_once_per_change_and_a_return_is_known(self, tree: Path) -> None:
        """Earn-the-red 6, keyed by content. Mutations: drop the operator
        line; key its throttle on the path alone; forget reported content."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('one')\n")
        first = _post(tree, "Bash", _FORMATTER)
        assert _HOOK in first.get("systemMessage", "")
        _bump(tree / _HOOK, "print('two')\n")
        second = _post(tree, "Bash", _FORMATTER)
        assert f"changed {_HOOK}" in _context(second) and _HOOK in second.get("systemMessage", "")
        _bump(tree / _HOOK, "print('one')\n")
        assert _post(tree, "Bash", _FORMATTER) == {}

    def test_the_wording_never_says_the_command_wrote_it_and_asks_a_subagent_to_pass_it_on(self, tree: Path) -> None:
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('x')\n")
        text = _context(_post(tree, "Bash", _FORMATTER))
        assert "this call or a parallel one made it" in text.lower()
        assert "command wrote" not in text.lower()
        assert "a subagent: put this in your final reply" in text
        assert text.isascii()

    def test_no_baseline_takes_one_and_says_so_where_claude_reads_it_once(self, tree: Path) -> None:
        """Flow step 6; an exit-0 hook's stderr reaches no one, so the notice
        is Claude's to read. Mutation: say it on stderr only."""
        _bump(tree / _HOOK, "print('before')\n")
        first = _context(_post(tree, "Bash", _FORMATTER))
        assert "this call was not checked" in first and f"changed {_HOOK}" not in first
        zw.baseline_path(tree, "s-1").unlink()
        assert "not checked" not in _context(_post(tree, "Bash", _FORMATTER))
        assert _audit_types(tree).count("posttooluse_failed_open_zone_unchecked") == 1
        _bump(tree / _HOOK, "print('after')\n")
        assert f"changed {_HOOK}" in _context(_post(tree, "Bash", _FORMATTER))

    def test_a_live_sibling_sessions_file_tool_write_is_silent(self, tree: Path) -> None:
        """Path 1 across sessions in one checkout. Mutation: ignore siblings."""
        for sid in ("s-1", "s-2"):
            hu.write_session_marker(tree, sid, pid=1)
            assert zw.take_baseline(tree, sid)
        _bump(tree / _HOOK, "print('sibling edit')\n")
        _post(tree, "Edit", {"file_path": str(tree / _HOOK)}, sid="s-2")
        assert _context(_post(tree, "Bash", _NO_OP, sid="s-1")) == ""

    def test_a_change_to_the_watched_set_is_not_read_as_removals(self, tree: Path) -> None:
        """Narrowing protected_paths drops files from the set; they did not
        disappear. Mutation: compare across the change."""
        (tree / "espalier.toml").write_text('protected_paths = ["vault/"]\n', encoding="utf-8")
        (tree / "vault").mkdir()
        (tree / "vault" / "f.txt").write_bytes(b"x\n")
        assert zw.take_baseline(tree, "s-1")
        (tree / "espalier.toml").write_text('protected_paths = []\n', encoding="utf-8")
        assert _context(_post(tree, "Bash", _NO_OP)) == ""


class TestTheCallWindow:
    """The operator's decision of 2026-10-09: a change that landed before the
    shell call began (a person's editor, another session, a background job)
    goes to the operator's line only; Claude is asked to stop for what landed
    during the call. The call began ``duration_ms`` before the hook ran."""

    def test_a_change_made_before_the_call_reaches_only_the_operator(self, tree: Path) -> None:
        """Mutation: read every change as made during the call."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('saved in an editor a minute ago')\n", ago_s=60)
        obj = _post(tree, "Bash", _NO_OP, duration_ms=1000)
        assert _context(obj) == ""
        assert "between Claude's calls" in obj.get("systemMessage", "") and _HOOK in obj["systemMessage"]
        rows = [r for r in _audit(tree) if r.get("event_type") == "post_shell_zone_change"]
        assert rows and rows[-1]["details"]["changed_between_calls"] == [_HOOK]

    def test_a_change_made_during_the_call_asks_claude_to_stop(self, tree: Path) -> None:
        """Mutation: read every change as made before the call."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('written by the command')\n", ago_s=1)
        obj = _post(tree, "Bash", _FORMATTER, duration_ms=30_000)
        assert "Stop and tell the operator" in _context(obj)
        assert "during Claude's last shell call" in obj.get("systemMessage", "")

    def test_a_payload_without_a_duration_reads_as_during(self, tree: Path) -> None:
        """No call start is the loud side, never the quiet one."""
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('x')\n", ago_s=600)
        assert "Stop and tell the operator" in _context(_post(tree, "Bash", _NO_OP))


def _git(tree: Path, *args: str) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "core.autocrlf=false", *args],
                          cwd=str(tree), capture_output=True, timeout=30)


def _git_ok(tree: Path, *args: str) -> None:
    result = _git(tree, *args)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def repo(tree: Path) -> Path:
    """The tree as a git repository with its hooks committed on ``main``,
    one commit deep (a reflog of one entry, as on a fresh clone); the
    settings files stay untracked, as init leaves them."""
    _git_ok(tree, "init", "-q", "-b", "main")
    _git_ok(tree, "add", "tools")
    _git_ok(tree, "commit", "-q", "-m", "hooks")
    return tree


class TestGitAccountsForCommittedContent:
    def test_a_file_brought_back_to_its_committed_content_is_silent(self, repo: Path) -> None:
        """Mutation: drop path 2."""
        _bump(repo / _HOOK, "print('dirty when the session began')\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", _HOOK)
        assert _context(_post(repo, "Bash", {"command": "git checkout -- ."})) == ""

    def test_one_reflog_entry_and_a_removal_in_the_same_call_keep_gits_answers(self, repo: Path) -> None:
        """A fresh repository's reflog has one entry; asking for HEAD@{1} there
        ends the whole batch, and every legitimate change reads as 'git could
        not be asked'. Mutation: ask for HEAD@{1} instead of the stored HEAD."""
        (repo / "tools" / "cc" / "hooks" / "local.py").write_bytes(b"untracked\n")
        _bump(repo / _HOOK, "print('dirty')\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", _HOOK)
        (repo / "tools" / "cc" / "hooks" / "local.py").unlink()
        text = _context(_post(repo, "Bash", _NO_OP))
        assert "git could not be asked" not in text
        assert "removed tools/cc/hooks/local.py" in text and f"changed {_HOOK}" not in text

    def test_new_content_beside_a_head_move_still_reports(self, repo: Path) -> None:
        """Mutation: let any blob at HEAD account for a path, whatever its content."""
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('committed')\n")
        _git_ok(repo, "commit", "-q", "-am", "guard")
        _bump(repo / _OTHER, "print('not committed')\n")
        text = _context(_post(repo, "Bash", _FORMATTER))
        assert f"changed {_OTHER}" in text and _HOOK not in text

    def test_a_rebase_onto_a_main_that_dropped_a_file_is_silent(self, repo: Path) -> None:
        """Several HEAD moves in one call: the removal is judged against the
        HEAD of the previous check, not HEAD@{1}. Mutation: judge removals
        with no stored HEAD."""
        _git_ok(repo, "switch", "-q", "-c", "lane")
        (repo / "notes.txt").write_bytes(b"lane work\n")
        _git_ok(repo, "add", "notes.txt")
        _git_ok(repo, "commit", "-q", "-m", "lane")
        _git_ok(repo, "switch", "-q", "main")
        _git_ok(repo, "rm", "-q", _OTHER)
        _git_ok(repo, "commit", "-q", "-m", "drop plan_guard")
        (repo / "more.txt").write_bytes(b"more\n")
        _git_ok(repo, "add", "more.txt")
        _git_ok(repo, "commit", "-q", "-m", "more")
        _git_ok(repo, "switch", "-q", "lane")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "rebase", "-q", "main")
        assert _context(_post(repo, "Bash", {"command": "git rebase main"})) == ""

    def test_a_deleted_untracked_hook_is_not_gits(self, repo: Path) -> None:
        """Absent at HEAD and on disk alike is no proof git removed it."""
        (repo / "tools" / "cc" / "hooks" / "local.py").write_bytes(b"untracked\n")
        assert zw.take_baseline(repo, "s-1")
        (repo / "tools" / "cc" / "hooks" / "local.py").unlink()
        assert "removed tools/cc/hooks/local.py" in _context(_post(repo, "Bash", _NO_OP))

    def test_a_stash_and_its_pop_of_a_judged_edit_are_both_silent(self, repo: Path) -> None:
        """Mutation: keep no known contents of this session's own."""
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('an edit judged by path')\n")
        _post(repo, "Edit", {"file_path": str(repo / _HOOK)})
        _git_ok(repo, "stash", "-q")
        assert _context(_post(repo, "Bash", {"command": "git stash"})) == ""
        _git_ok(repo, "stash", "pop", "-q")
        assert _context(_post(repo, "Bash", {"command": "git stash pop"})) == ""

    def test_a_stash_of_a_new_judged_file_is_silent(self, repo: Path) -> None:
        """The session's own uncommitted new file leaving the tree: the
        tree is back to committed history for that path. Mutation: drop the
        known-removal rule."""
        assert zw.take_baseline(repo, "s-1")
        new = repo / "tools" / "cc" / "hooks" / "new_hook.py"
        _bump(new, "x = 1\n")
        _post(repo, "Write", {"file_path": str(new)})
        _git_ok(repo, "add", str(new))
        _git_ok(repo, "stash", "-q")
        assert not new.exists()
        assert _context(_post(repo, "Bash", {"command": "git stash"})) == ""

    def test_a_merge_stopped_on_a_conflict_holds_until_git_is_done(self, repo: Path) -> None:
        """While git is half way through, nothing is judged; the result is
        judged once it is done. Mutation: judge mid-operation."""
        _git_ok(repo, "switch", "-q", "-c", "lane")
        _bump(repo / _HOOK, "print('lane side')\n")
        _git_ok(repo, "commit", "-q", "-am", "lane")
        _git_ok(repo, "switch", "-q", "main")
        _bump(repo / _HOOK, "print('main side')\n")
        _bump(repo / _OTHER, "print('main changed this cleanly')\n")
        _git_ok(repo, "commit", "-q", "-am", "main")
        _git_ok(repo, "switch", "-q", "lane")
        assert zw.take_baseline(repo, "s-1")
        assert _git(repo, "merge", "-q", "main").returncode != 0  # stops on the conflict
        assert _context(_post(repo, "Bash", {"command": "git merge main"})) == ""
        _git_ok(repo, "checkout", "--theirs", _HOOK)
        _git_ok(repo, "commit", "-q", "-am", "merge main")
        assert _context(_post(repo, "Bash", {"command": "git commit"})) == ""

    def test_git_that_cannot_answer_reports_and_says_why(self, repo: Path, monkeypatch) -> None:
        """Mutation: read a git failure as 'accounted'."""
        _bump(repo / _HOOK, "print('dirty')\n")
        assert zw.take_baseline(repo, "s-1")
        (repo / _HOOK).write_bytes(b"print('guard')\n")  # HEAD's content again
        from tests._interpreter_hosts import HOOK_PYTHON
        monkeypatch.setenv("PATH", str(Path(HOOK_PYTHON).parent))
        text = _context(_post(repo, "Bash", _NO_OP))
        assert f"changed {_HOOK}" in text and "git could not be asked" in text


class TestAHarnessWriterStillRunningHoldsTheCheck:
    def test_a_running_marker_holds_the_baseline_until_the_run_ends(self, tree: Path) -> None:
        """A check during a writer's run reports half a run. Mutation: judge
        while a writer runs."""
        assert zw.take_baseline(tree, "s-1")
        records = tree / ".espalier-state" / "zone_writes"
        records.mkdir(parents=True)
        marker = records / ("espalier-upgrade.json" + zw.RUNNING_SUFFIX)
        marker.write_bytes(b"{}\n")
        _bump(tree / _HOOK, "print('half way through an upgrade')\n")
        assert _context(_post(tree, "Bash", _NO_OP)) == ""
        marker.unlink()
        assert f"changed {_HOOK}" in _context(_post(tree, "Bash", _NO_OP))

    def test_a_marker_older_than_a_run_can_last_holds_nothing(self, tree: Path) -> None:
        assert zw.take_baseline(tree, "s-1")
        records = tree / ".espalier-state" / "zone_writes"
        records.mkdir(parents=True)
        marker = records / ("espalier-upgrade.json" + zw.RUNNING_SUFFIX)
        marker.write_bytes(b"{}\n")
        ancient = time.time() - zw.WRITER_RUNNING_MAX_S - 60
        os.utime(marker, (ancient, ancient))
        _bump(tree / _HOOK, "print('a killed run long ago')\n")
        assert f"changed {_HOOK}" in _context(_post(tree, "Bash", _NO_OP))


class TestParallelCallsReportOnce:
    def test_a_call_that_peeked_before_a_sibling_reported_finds_nothing_under_the_lock(
            self, tree: Path, monkeypatch) -> None:
        """Mutation: compare against the peeked record under the lock."""
        assert zw.take_baseline(tree, "s-1")
        path = zw.baseline_path(tree, "s-1")
        stale = zw.read_baseline(path)
        _bump(tree / _HOOK, "print('one change')\n")
        first = zw.after_shell_call(tree, "s-1")
        assert first is not None and first["during"]["changed"] == [_HOOK]
        real_read = zw.read_baseline
        reads = []

        def stale_first(p):
            reads.append(p)
            return stale if len(reads) == 1 else real_read(p)

        monkeypatch.setattr(zw, "read_baseline", stale_first)
        assert zw.after_shell_call(tree, "s-1") is None
        assert len(reads) == 2

    def test_a_call_that_changed_nothing_takes_no_lock_and_writes_nothing(self, tree: Path, monkeypatch) -> None:
        assert zw.take_baseline(tree, "s-1")
        path = zw.baseline_path(tree, "s-1")
        before = path.read_bytes()
        monkeypatch.setattr(zw, "baseline_lock", lambda p: (_ for _ in ()).throw(AssertionError("locked")))
        assert zw.after_shell_call(tree, "s-1") is None
        assert path.read_bytes() == before

    def test_a_finding_survives_a_baseline_that_cannot_be_replaced(self, tree: Path, monkeypatch) -> None:
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / _HOOK, "print('x')\n")

        def refuse(path, record):
            raise OSError("read-only")

        monkeypatch.setattr(zw, "write_baseline", refuse)
        result = zw.after_shell_call(tree, "s-1")
        assert result is not None and result["during"]["changed"] == [_HOOK]
        assert any("could not be replaced" in note for note in result["notes"])


_GUARD_WF = ".github/workflows/harness-guard.yml"
_GUARD_WF_SOURCE = "espalier/assets/github/workflows/harness-guard.yml"


class TestMirrorsOnTheHarnessSourceTreeOnly:
    @pytest.fixture
    def mirrored(self, tree: Path) -> Path:
        for rel in (_GUARD_WF, _GUARD_WF_SOURCE):
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / rel).write_bytes(b"name: guard\n")
        return tree

    @pytest.fixture
    def self_host(self, monkeypatch):
        """Path 3's gate reads the tree as the harness's own; the watched
        prefixes stay the adopter's, so the packaged source (under espalier/,
        which the source tree watches and whose edits a file tool makes) is
        not itself in play here."""
        monkeypatch.setattr(zw._hook_utils, "is_self_host_repo", lambda root: True)
        monkeypatch.setattr(zw._hook_utils, "harness_protected_prefixes",
                            lambda root: ["tools/cc/", "cc/", ".github/workflows/"])

    def test_a_copy_synced_to_its_source_is_silent(self, mirrored: Path, self_host) -> None:
        """Mutation: drop path 3."""
        assert zw.take_baseline(mirrored, "s-1")
        (mirrored / _GUARD_WF_SOURCE).write_bytes(b"name: guard v2\n")
        _bump(mirrored / _GUARD_WF, "name: guard v2\n")
        assert zw.after_shell_call(mirrored, "s-1") is None

    def test_a_copy_that_differs_from_its_source_reports(self, mirrored: Path, self_host) -> None:
        """Mutation: let a mirror path account for itself whatever it holds."""
        assert zw.take_baseline(mirrored, "s-1")
        _bump(mirrored / _GUARD_WF, "name: guard, edited by hand\n")
        result = zw.after_shell_call(mirrored, "s-1")
        assert result is not None and result["during"]["changed"] == [_GUARD_WF]

    def test_a_copy_removed_beside_its_source_is_silent_and_alone_is_not(self, mirrored: Path, self_host) -> None:
        """Mutation: account any removed copy."""
        assert zw.take_baseline(mirrored, "s-1")
        (mirrored / _GUARD_WF).unlink()
        result = zw.after_shell_call(mirrored, "s-1")
        assert result is not None and result["during"]["removed"] == [_GUARD_WF]
        (mirrored / _GUARD_WF).write_bytes(b"name: guard\n")
        assert zw.take_baseline(mirrored, "s-1")
        (mirrored / _GUARD_WF).unlink()
        (mirrored / _GUARD_WF_SOURCE).unlink()
        assert zw.after_shell_call(mirrored, "s-1") is None

    def test_an_adopters_deleted_ci_guard_workflow_reports(self, tree: Path) -> None:
        """An adopter has no packaged source, so 'the source is gone too'
        holds for every adopter: the deleted CI backstop read as a pruned
        mirror. Mutation: apply the mirror table on every tree."""
        (tree / _GUARD_WF).parent.mkdir(parents=True)
        (tree / _GUARD_WF).write_bytes(b"name: guard\n")
        assert zw.take_baseline(tree, "s-1")
        (tree / _GUARD_WF).unlink()
        assert f"removed {_GUARD_WF}" in _context(_post(tree, "Bash", {"command": "rm -r .github"}))


class TestTheMirrorTableIsTheRegistrys:
    """MIRROR_PAIRS is a hook-side copy (a hook imports nothing from
    espalier/), held equal to espalier/mirror_registry.py both ways."""

    @staticmethod
    def _watched_rows():
        from espalier import mirror_registry as reg
        for r in reg.MIRROR_ROWS:
            mirror = r.mirrors[0]
            probe = mirror + "probe.py" if mirror.endswith("/") else mirror
            if zw.is_watched(ROOT, probe):
                yield reg, r

    def test_every_watched_equality_row_is_in_the_table_and_nothing_else_is(self) -> None:
        expected = set()
        for reg, r in self._watched_rows():
            if r.kind in (reg.BYTE, reg.SUBSET):
                glob = reg.glob_row_parts(r.sot)
                expected.add((r.mirrors[0], glob[0] if glob else r.sot))
        assert set(zw.MIRROR_PAIRS) == expected

    def test_each_entry_maps_a_source_path_as_the_registry_does(self) -> None:
        for reg, r in self._watched_rows():
            if r.kind not in (reg.BYTE, reg.SUBSET):
                continue
            glob = reg.glob_row_parts(r.sot)
            source = (glob[0] + "x" + glob[1][0]) if glob else (r.sot + "x.md" if r.sot.endswith("/") else r.sot)
            assert zw.mirror_source(reg.counterpart(r, source)) == source, r.name


class TestTheTwinsAgree:
    def test_the_mid_operation_markers_are_checkout_syncs(self) -> None:
        spec = importlib.util.spec_from_file_location("_checkout_sync_a1", ROOT / "tools" / "cc" / "checkout_sync.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # its dataclasses resolve their module by name
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.modules.pop(spec.name, None)
        assert tuple(name for name, _ in mod._MID_OPERATION) == zw.MID_OPERATION


class TestTheOperatorLine:
    def test_a_hook_that_passes_no_operator_lines_prints_what_it_printed_before(self, capsys) -> None:
        hu.take_advisories()
        hu.emit_advisories("PostToolUse", ["a line"])
        assert capsys.readouterr().out.strip() == (
            '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "a line"}}')
        hu.emit_advisories("PostToolUse")
        assert capsys.readouterr().out == ""

    def test_an_operator_line_alone_is_its_own_object(self, capsys) -> None:
        hu.take_advisories()
        hu.emit_advisories("PostToolUse", (), ["for the operator"])
        assert capsys.readouterr().out.strip() == '{"systemMessage": "for the operator"}'


def test_a_deploy_without_the_helper_says_so_once_and_keeps_the_hook(tmp_path: Path) -> None:
    """A post_write_check beside a tree that predates _zone_watch.py keeps
    its other checks and says the zone check is off once, never every call."""
    cc = tmp_path / "deployed" / "tools" / "cc"
    shutil.copytree(ROOT / "tools" / "cc", cc, ignore=shutil.ignore_patterns("__pycache__"))
    (cc / "hooks" / "_zone_watch.py").unlink()
    tree = tmp_path / "work"
    (tree / "tools" / "cc" / "hooks").mkdir(parents=True)
    for _ in range(2):
        _post(tree, "Bash", _NO_OP, hooks_dir=cc / "hooks")
    assert _audit_types(tree).count("posttooluse_failed_open_zone_import") == 1


def test_the_helper_imports_standalone_under_both_spellings() -> None:
    """The loader contract: bare and dotted, each in a fresh process."""
    for code, cwd in (("import _zone_watch", HOOKS_DIR), ("import tools.cc.hooks._zone_watch", ROOT)):
        result = subprocess.run([sys.executable, "-c", code], cwd=str(cwd),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        assert result.returncode == 0, result.stderr
