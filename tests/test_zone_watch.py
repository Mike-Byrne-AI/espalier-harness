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
import types
from pathlib import Path

import pytest
from tests._live_tree import copy_checkout

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

    def test_the_exact_protected_files_the_check_keeps_are_pinned_and_watched(self, tree: Path) -> None:
        """The exact-file arm: PROTECTED_FILES less the two settings files, pinned
        by name (2026-10-11) because a parser row's re-scope rests on them being
        watched (DEF-1171), and each in the snapshot once present. Mutation:
        add one of the three to UNWATCHED_FILES."""
        assert set(zw.watched_files()) == {
            ".espalier/integrity.json", ".espalier/freshness.json", ".github/workflows/harness-guard.yml",
        }
        for rel in zw.watched_files():
            _bump(tree / rel, "x\n")
        snap = zw.snapshot(tree)
        assert all(rel in snap for rel in zw.watched_files()), [r for r in zw.watched_files() if r not in snap]

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

    def test_a_directory_that_ignores_itself_is_generated_and_never_snapshotted(self, tree: Path) -> None:
        """What Claude Code writes beside a mod it loads (`.claude-plugin/types/`,
        its own `.gitignore` a bare `*`, rewritten at a launch) and what pytest,
        ruff, mypy and uv write the same way under a name no roster holds: a
        directory that declares itself generated is pruned wherever it sits
        below a watched top, and a path inside it is not watched before it
        exists (the ledger's probe). Mutations: drop the self-ignore prune from
        the walk; from is_watched."""
        mod = tree / "tools" / "cc" / "mods" / "m"
        types = mod / ".claude-plugin" / "types"
        (types / "claude-code").mkdir(parents=True)
        (types / ".gitignore").write_bytes(b"*\n")
        (types / "tsconfig.json").write_bytes(b"{}\n")
        (types / "claude-code" / "index.d.ts").write_bytes(b"export {};\n")
        (mod / "hooks").mkdir()
        (mod / "hooks" / "register.ts").write_bytes(b"export {};\n")
        cache = tree / "tools" / "cc" / ".tool_cache"
        (cache / "v1").mkdir(parents=True)
        (cache / ".gitignore").write_bytes(b"# Created by a tool automatically.\r\n\r\n*\r\n")
        (cache / "v1" / "x.json").write_bytes(b"{}\n")
        snap = zw.snapshot(tree)
        assert "tools/cc/mods/m/hooks/register.ts" in snap
        generated = [r for r in snap if r.startswith(("tools/cc/mods/m/.claude-plugin/types/", "tools/cc/.tool_cache/"))]
        assert generated == [], generated
        assert zw.is_watched(tree, "tools/cc/mods/m/hooks/register.ts")
        assert not zw.is_watched(tree, "tools/cc/mods/m/.claude-plugin/types/claude-code/index.d.ts")
        assert not zw.is_watched(tree, "tools/cc/mods/m/.claude-plugin/types/claude-code-mcp/probe.d.ts")
        assert not zw.is_watched(tree, "tools/cc/.tool_cache/v1/x.json")

    @pytest.mark.parametrize("rules", [
        b"*\n!keep.py\n",                 # a kept file: a rule set
        b"*.log\n",                       # a pattern
        b"",                              # nothing declared
        b"# only a comment\n",
        b"\\*\n",                         # a literal asterisk, escaped
        b"*\n" + b"# padding\n" * 600,    # past the read limit: a rule set, whatever its first line
    ])
    def test_a_gitignore_that_is_not_the_bare_star_prunes_nothing(self, tree: Path, rules: bytes) -> None:
        """A rule set under a zone is a rule set, and the files beside it stay
        watched. Mutation: read any .gitignore as the declaration."""
        sub = tree / "tools" / "cc" / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_bytes(rules)
        (sub / "x.py").write_bytes(b"x\n")
        assert "tools/cc/sub/x.py" in zw.snapshot(tree)
        assert zw.is_watched(tree, "tools/cc/sub/x.py")

    def test_a_watched_top_never_prunes_itself(self, tree: Path) -> None:
        """A bare `*` at a zone's own root (tools/cc/.gitignore, or an adopter's
        protected_paths top) leaves the zone watched: the declaration is read
        below a top only. Mutation: read the top's own .gitignore."""
        (tree / "tools" / "cc" / ".gitignore").write_bytes(b"*\n")
        (tree / "espalier.toml").write_text('protected_paths = ["vault/"]\n', encoding="utf-8")
        (tree / "vault").mkdir()
        (tree / "vault" / ".gitignore").write_bytes(b"*\n")
        (tree / "vault" / "f.txt").write_bytes(b"x\n")
        snap = zw.snapshot(tree)
        assert _HOOK in snap and "tools/cc/.gitignore" in snap and "vault/f.txt" in snap
        assert zw.is_watched(tree, _HOOK) and zw.is_watched(tree, "vault/f.txt")

    def test_a_self_ignore_written_under_the_hooks_mid_session_reads_as_the_hooks_removed(self, tree: Path) -> None:
        """The one way the rule could hide a zone -- a bare `*` dropped into
        tools/cc/hooks/ by a shell call -- is loud by construction: the next
        check finds every hook gone from the watched set and reports each as
        removed. Mutation: carry a pruned directory's prior entries forward."""
        assert zw.take_baseline(tree, "s-1")
        (tree / "tools" / "cc" / "hooks" / ".gitignore").write_bytes(b"*\n")
        text = _context(_post(tree, "Bash", _FORMATTER))
        assert f"removed {_HOOK}" in text and f"removed {_OTHER}" in text, text
        assert "Stop and tell the operator" in text

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

    def test_a_change_to_an_exact_protected_file_is_reported(self, tree: Path) -> None:
        """The exact-file arm of the layer (`.espalier/integrity.json` here): a
        shell call that names no zone and leaves it changed is reported like a
        prefix-zone change. Mutation: drop the watched_files() loop from snapshot."""
        _bump(tree / ".espalier" / "integrity.json", "{}\n", ago_s=60)
        assert zw.take_baseline(tree, "s-1")
        _bump(tree / ".espalier" / "integrity.json", '{"files": {}}\n')
        text = _context(_post(tree, "Bash", _FORMATTER))
        assert "changed .espalier/integrity.json" in text and "Stop and tell the operator" in text

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


def _gx(cwd: Path, *args: str, check: bool = True) -> "subprocess.CompletedProcess[str]":
    """git with this box's own config shut out, and a local path allowed as a
    submodule's source (git refuses one since 2.38.1)."""
    from tests._git_oracle import _git_env

    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false",
         "-c", "protocol.file.allow=always", "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        env={**_git_env(), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    assert not check or result.returncode == 0, (args, result.stderr)
    return result


@pytest.fixture
def upstream(tmp_path_factory) -> Path:
    """A bare origin a nested checkout is cloned from, at c1: ``weights.json``,
    ``old.txt`` and ``src/api.h``. ``_advance`` pushes c2, which changes the
    first and the third, adds ``new.txt`` and removes ``old.txt``: a pull is
    all three kinds at once."""
    base = tmp_path_factory.mktemp("upstream")
    origin = base / "up.git"
    _gx(base, "init", "-q", "--bare", str(origin))
    work = base / "work"
    _gx(base, "clone", "-q", str(origin), str(work))
    (work / "weights.json").write_bytes(b'{"v": 1}\n')
    (work / "old.txt").write_bytes(b"old\n")
    (work / "src").mkdir()
    (work / "src" / "api.h").write_bytes(b"int v1;\n")
    (work / "weights.bin").write_bytes(bytes(range(200)))
    _gx(work, "add", ".")
    _gx(work, "commit", "-q", "-m", "c1")
    _gx(work, "push", "-q", "origin", "HEAD:main")
    return origin


def _advance(origin: Path) -> None:
    work = origin.parent / "work"
    (work / "weights.json").write_bytes(b'{"v": 2}\n')
    (work / "src" / "api.h").write_bytes(b"int v2;\n")
    (work / "weights.bin").write_bytes(bytes(range(199, -1, -1)))
    (work / "new.txt").write_bytes(b"new\n")
    (work / "old.txt").unlink()
    _gx(work, "add", "-A")
    _gx(work, "commit", "-q", "-m", "c2")
    _gx(work, "push", "-q", "origin", "HEAD:main")


class TestANestedCheckoutsOwnGitAccountsForItsFiles:
    """A clone, a submodule, or a protected top that is itself a checkout,
    under an adopter's protected path: the outer HEAD never holds its files,
    so the after-check asks that checkout's own git (DEF-4012). Each shape was
    driven against the unfixed check first, which reported every file a pull
    moved and told Claude to stop."""

    def _clone(self, repo: Path, origin: Path, where: str = "models", name: str = "clone",
               protected: str = "models/") -> Path:
        (repo / "espalier.toml").write_bytes(f'protected_paths = ["{protected}"]\n'.encode())
        (repo / where).mkdir(parents=True, exist_ok=True)
        _gx(repo / where, "clone", "-q", str(origin), name)
        return repo / where / name

    @staticmethod
    def _only_the_hand_file(text: str, hand: str) -> None:
        """The pull's three kinds silent, the file made by hand in the same call
        reported: silence by accounting, never by a hold or a skip."""
        assert hand in text, text
        assert not any(n in text for n in ("weights.json", "weights.bin", "old.txt", "new.txt", "api.h")), text

    def test_a_pull_inside_a_clone_is_silent(self, repo: Path, upstream: Path) -> None:
        """Mutations: path 2 asking the outer HEAD alone (the defect); a removal
        judged without the nested checkout's HEAD at the previous check; every
        nested path held or skipped."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(clone, "pull", "-q", "--ff-only")
        (clone / "hand.txt").write_bytes(b"made by hand\n")
        self._only_the_hand_file(_context(_post(repo, "Bash", {"command": "git -C models/clone pull"})),
                                 "models/clone/hand.txt")

    def test_a_pull_inside_a_submodule_is_silent(self, repo: Path, upstream: Path) -> None:
        """A submodule's `.git` is a file naming its git dir under the outer
        one's. Mutation: a checkout found by a `.git` directory alone."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        _gx(repo, "submodule", "add", "-q", str(upstream), "models/sub")
        _gx(repo, "commit", "-q", "-m", "sub")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(repo / "models" / "sub", "pull", "-q", "--ff-only", "origin", "main")
        (repo / "models" / "sub" / "hand.txt").write_bytes(b"made by hand\n")
        self._only_the_hand_file(_context(_post(repo, "Bash", {"command": "git -C models/sub pull"})),
                                 "models/sub/hand.txt")

    def test_a_pull_inside_a_protected_top_that_is_itself_a_checkout_is_silent(
            self, repo: Path, upstream: Path) -> None:
        """The third shape the withdrawn prune got wrong. Mutation: a checkout
        sought only below the protected prefix, never at it."""
        lib = self._clone(repo, upstream, where="vendor", name="lib", protected="vendor/lib/")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(lib, "pull", "-q", "--ff-only")
        (lib / "hand.txt").write_bytes(b"made by hand\n")
        self._only_the_hand_file(_context(_post(repo, "Bash", {"command": "git -C vendor/lib pull"})),
                                 "vendor/lib/hand.txt")

    def test_a_protected_path_inside_a_checkout_is_judged_by_that_checkout(
            self, repo: Path, upstream: Path) -> None:
        """The prefix sits below the checkout's top (`vendor/lib/src/`, the clone
        at `vendor/lib`): the defect's sibling shape both reviews drove. Mutation:
        the search for a checkout stopped at the protected prefix."""
        lib = self._clone(repo, upstream, where="vendor", name="lib", protected="vendor/lib/src/")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(lib, "pull", "-q", "--ff-only")
        (lib / "src" / "hand.h").write_bytes(b"int by_hand;\n")
        self._only_the_hand_file(_context(_post(repo, "Bash", {"command": "git -C vendor/lib pull"})),
                                 "vendor/lib/src/hand.h")

    def test_new_content_beside_a_nested_pull_still_reports(self, repo: Path, upstream: Path) -> None:
        """Mutation: any blob the nested checkout has accounts for a path,
        whatever its content."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(clone, "pull", "-q", "--ff-only")
        _bump(clone / "new.txt", "not what the pull brought\n")
        text = _context(_post(repo, "Bash", _FORMATTER))
        assert "models/clone/new.txt" in text, text
        assert "weights.json" not in text and "old.txt" not in text, text

    def test_an_edit_in_a_nested_repository_with_no_commits_still_reports(self, repo: Path) -> None:
        """No git move made it, so nothing accounts for it (Task 0's fourth
        shape). Mutation: an unborn nested HEAD read as holding the file."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        empty = repo / "models" / "empty"
        empty.mkdir(parents=True)
        _gx(empty, "init", "-q")
        (empty / "data.json").write_bytes(b"{}\n")
        assert zw.take_baseline(repo, "s-1")
        _bump(empty / "data.json", '{"edited": true}\n')
        assert "changed models/empty/data.json" in _context(_post(repo, "Bash", _FORMATTER))

    @pytest.mark.parametrize("protected", [None, "tools/", "tools/cc/hooks/"],
                             ids=["no-adopter-prefix", "an-adopter-prefix-enclosing-the-zone", "the-zone-itself"])
    def test_a_checkout_planted_in_a_harness_zone_is_never_asked(self, repo: Path, protected: str | None) -> None:
        """The harness's own zones never hold a checkout, and one planted there
        would account for whatever its own commit holds -- under an adopter
        prefix that encloses the zone too (both reviews drove `tools/` and
        `.github/`). Mutations: the nested git asked outside an adopter's
        protected paths; the exclusion judged on the prefix, not the path."""
        if protected:
            (repo / "espalier.toml").write_bytes(f'protected_paths = ["{protected}"]\n'.encode())
        hooks = repo / "tools" / "cc" / "hooks"
        _gx(hooks, "init", "-q")   # planted before the session, so a check has seen it
        _gx(hooks, "add", "write_guard.py")
        _gx(hooks, "commit", "-q", "-m", "planted")
        assert zw.take_baseline(repo, "s-1")
        _bump(hooks / "write_guard.py", "print('committed in a planted repository')\n")
        _gx(hooks, "commit", "-q", "-am", "the slip, committed where only the planted repository holds it")
        assert f"changed {_HOOK}" in _context(_post(repo, "Bash", _FORMATTER))

    def test_a_nested_merge_stopped_on_a_conflict_holds_that_checkout_alone(
            self, repo: Path, upstream: Path) -> None:
        """While a nested checkout is mid-merge its paths are held, judged once
        git is done there, and everything else is judged now (both reviews: a
        hold over the whole check hid a hook slip for as long as a vendored
        clone stayed mid-operation). Mutations: the hold reads the outer git dir
        alone; the hold covers every zone; the hold never releases."""
        clone = self._clone(repo, upstream)
        (clone / "weights.json").write_bytes(b'{"v": "local"}\n')
        _gx(clone, "commit", "-q", "-am", "local")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        assert _gx(clone, "pull", "-q", "--no-rebase", check=False).returncode != 0  # stops on the conflict
        (clone / "hand.txt").write_bytes(b"made during the merge\n")
        _bump(repo / _HOOK, "print('a slip while the clone is mid-merge')\n")
        text = _context(_post(repo, "Bash", {"command": "git -C models/clone pull"}))
        assert f"changed {_HOOK}" in text and "models/clone" not in text, text
        (clone / "weights.json").write_bytes(b'{"v": 2}\n')
        _gx(clone, "add", "weights.json")
        _gx(clone, "commit", "-q", "--no-edit")
        self._only_the_hand_file(_context(_post(repo, "Bash", {"command": "git -C models/clone commit"})),
                                 "models/clone/hand.txt")

    def test_a_nested_operation_left_standing_holds_no_other_zone(self, repo: Path, upstream: Path) -> None:
        """A bisect left running in a vendored clone before the session began,
        which nobody watches: a hook rewritten in a later call is reported
        during that call, Claude asked to stop. Mutation: the hold covers every
        zone (the hook slip held, then reported late as the operator's alone)."""
        clone = self._clone(repo, upstream)
        _gx(clone, "bisect", "start")
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('a slip beside a bisect')\n")
        text = _context(_post(repo, "Bash", _FORMATTER))
        assert f"changed {_HOOK}" in text and "Stop and tell the operator" in text, text

    def test_a_baseline_without_the_nested_heads_still_reads(self, tree: Path) -> None:
        """The key is optional: a baseline written before it is kept (expand,
        then contract). Mutations: the key required, so every baseline from
        before the upgrade reads as none; a malformed one read as usable."""
        path = zw.baseline_path(tree, "s-1")
        record = zw.new_baseline(tree, zw.snapshot(tree), 1)
        record.pop("nested", None)
        zw.write_baseline(path, record)
        assert zw.read_baseline(path) is not None
        for malformed in (["not", "a", "map"], {"models/x": 1}):
            record["nested"] = malformed
            zw.write_baseline(path, record)
            assert zw.read_baseline(path) is None, malformed

    def test_a_checkout_that_appears_reports_its_files_once_then_its_pulls_are_silent(
            self, repo: Path, upstream: Path) -> None:
        """A copy carrying its `.git` into a protected path is the copy slip the
        check exists for: the new checkout vouches for nothing until a check has
        seen it (option A, the dispatcher's 761e87). Mutation: any checkout
        found is asked, known or not."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        elsewhere = upstream.parent / "elsewhere"
        _gx(upstream.parent, "clone", "-q", str(upstream), str(elsewhere))
        assert zw.take_baseline(repo, "s-1")
        shutil.copytree(elsewhere, repo / "models" / "copy")
        text = _context(_post(repo, "Bash", {"command": "cp -r ../elsewhere models/copy"}))
        assert "models/copy/weights.json" in text and "models/copy/old.txt" in text, text
        _advance(upstream)
        _gx(repo / "models" / "copy", "pull", "-q", "--ff-only")
        assert _context(_post(repo, "Bash", {"command": "git -C models/copy pull"})) == ""

    def test_a_directory_that_becomes_a_checkout_with_nothing_moving_is_recorded(self, repo: Path) -> None:
        """`git init` and a commit over files already there move nothing on disk,
        so only the peek's nested-head read records the checkout; its next
        removal is then judged against that commit. Measured on the peek: 1.3
        to 1.8 ms per 1,000 watched files under an adopter prefix and 6.4 to
        14.6 ms per 10,000 (two runs, two loads), nothing without one.
        Mutations: the peek blind to the nested heads; the record's heads never
        refreshed."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        vend = repo / "models" / "vend"
        vend.mkdir(parents=True)
        (vend / "a.txt").write_bytes(b"a\n")
        (vend / "b.txt").write_bytes(b"b\n")
        assert zw.take_baseline(repo, "s-1")
        _gx(vend, "init", "-q")
        _gx(vend, "add", "-A")
        _gx(vend, "commit", "-q", "-m", "vend")
        assert _context(_post(repo, "Bash", {"command": "git init models/vend"})) == ""
        _gx(vend, "rm", "-q", "b.txt")
        _gx(vend, "commit", "-q", "-m", "drop b")
        assert _context(_post(repo, "Bash", {"command": "git -C models/vend rm b.txt"})) == ""

    def test_a_nested_git_that_cannot_answer_reports_and_names_the_checkout(
            self, repo: Path, upstream: Path, monkeypatch) -> None:
        """The file made by hand was reported once, so its content is known; its
        removal is still git's to confirm (absent at HEAD), and git cannot say.
        Mutations: a nested git's failure read as 'accounted' or as asked; the
        note dropped."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        (clone / "hand.txt").write_bytes(b"made by hand\n")
        assert "models/clone/hand.txt" in _context(_post(repo, "Bash", _FORMATTER))
        _advance(upstream)
        _gx(clone, "pull", "-q", "--ff-only")
        (clone / "hand.txt").unlink()
        from tests._interpreter_hosts import HOOK_PYTHON
        monkeypatch.setenv("PATH", str(Path(HOOK_PYTHON).parent))
        text = _context(_post(repo, "Bash", _NO_OP))
        assert "models/clone/weights.json" in text and "removed models/clone/hand.txt" in text, text
        assert "the git of models/clone/ could not be asked" in text, text

    def test_a_nested_checkout_moved_away_whole_reports_its_files(self, repo: Path, upstream: Path) -> None:
        """No git move removed them, so they report, and from the outer git: a
        checkout gone since the previous check is asked of nothing. Mutation: the
        gone checkout's git asked, so the note says its git could not be asked."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        os.rename(clone, upstream.parent / "moved-away")
        text = _context(_post(repo, "Bash", {"command": "mv models/clone ../moved-away"}))
        assert "models/clone/weights.json" in text and "models/clone/old.txt" in text, text
        assert "could not be asked" not in text, text

    def test_a_pull_in_the_inner_of_two_clones_is_the_inner_ones(self, repo: Path, upstream: Path) -> None:
        """Mutation: the outermost known checkout asked, not the nearest."""
        clone = self._clone(repo, upstream)
        _gx(clone, "clone", "-q", str(upstream), "inner")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(clone / "inner", "pull", "-q", "--ff-only")
        (clone / "inner" / "hand.txt").write_bytes(b"made by hand\n")
        self._only_the_hand_file(_context(_post(repo, "Bash", {"command": "git -C models/clone/inner pull"})),
                                 "models/clone/inner/hand.txt")

    def test_an_inherited_git_dir_does_not_send_the_nested_ask_elsewhere(self, repo: Path, upstream: Path) -> None:
        """Mutation: the nested spawn keeps GIT_DIR, so the outer git answers
        for the nested checkout's files (code review, driven)."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(clone, "pull", "-q", "--ff-only")
        assert _context(_post(repo, "Bash", {"command": "git -C models/clone pull"},
                              extra_env={"GIT_DIR": str(repo / ".git")})) == ""

    def test_a_nested_pull_landing_beside_the_locked_snapshot_is_judged_next_call(
            self, repo: Path, upstream: Path, monkeypatch) -> None:
        """The nested heads are read before the locked snapshot, as the outer
        HEAD is. Mutation: read after it, so a parallel call's pull landing
        between the two paired the new head with the old files and the next
        call reported the pull's removal (code review, driven)."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _bump(repo / _HOOK, "print('a slip that makes the call take the lock')\n")
        real, calls = zw.snapshot, []

        def snapshot(*args, **kwargs):
            got = real(*args, **kwargs)
            calls.append(1)
            if len(calls) == 2:   # the locked pass's: a parallel call's pull lands now
                _gx(clone, "pull", "-q", "--ff-only")
            return got

        monkeypatch.setattr(zw, "snapshot", snapshot)
        first = zw.after_shell_call(repo, "s-1")
        assert first is not None and _HOOK in first["during"]["changed"], first
        monkeypatch.setattr(zw, "snapshot", real)
        assert zw.after_shell_call(repo, "s-1") is None

    def test_nested_checkouts_past_the_budget_report_and_are_named(
            self, repo: Path, upstream: Path, monkeypatch) -> None:
        """A call over many clones must not cost the hook its timeout (about
        12 ms each). Mutations: no budget; the late checkouts read as asked."""
        clone = self._clone(repo, upstream)
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(clone, "pull", "-q", "--ff-only")
        monkeypatch.setattr(zw, "NESTED_ASK_BUDGET_S", -1.0)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and "models/clone/weights.json" in got["during"]["changed"], got
        assert any("not asked within" in n and "models/clone/" in n for n in got["notes"]), got


_BIG = "tools/cc/hooks/big.bin"


class TestAFileTooBigToReadIsGitsToo:
    """A file of BIG_FILE_BYTES or more is identified by its stat and never
    read, so path 2 never matched it against git's blob and a pull or checkout
    of a big file reported (DEF-5017). Git now hashes it through the
    checkout's filters and the hook matches the id at HEAD; no big blob is
    read into the hook. Driven in-process with the threshold lowered, so no
    test writes 4 MiB."""

    @pytest.fixture(autouse=True)
    def _small_threshold(self, monkeypatch) -> None:
        monkeypatch.setattr(zw, "BIG_FILE_BYTES", 64)

    def _commit_big(self, repo: Path, data: bytes) -> Path:
        (repo / _BIG).write_bytes(data)
        _git_ok(repo, "add", _BIG)
        _git_ok(repo, "commit", "-q", "-m", "big")
        return repo / _BIG

    def test_a_big_file_brought_back_to_its_committed_content_is_silent(self, repo: Path) -> None:
        """The row's probe shape: an edit before the session, then the committed
        bytes written back. Mutations: a big file never matched (the defect); a
        big file judged by the index's stat rather than its content (a stat
        that moved reads as a change)."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_big_file_pulled_in_a_known_clone_is_silent(self, repo: Path, upstream: Path) -> None:
        """DEF-4012's own user: a weights file pulled inside a vendored clone."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        (repo / "models").mkdir()
        _gx(repo / "models", "clone", "-q", str(upstream), "clone")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(repo / "models" / "clone", "pull", "-q", "--ff-only")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_big_file_edited_by_hand_still_reports(self, repo: Path) -> None:
        """Mutation: any big file present at HEAD accounted, whatever it holds."""
        big = self._commit_big(repo, bytes(range(100)))
        assert zw.take_baseline(repo, "s-1")
        _bump(big, "not what was committed" * 5)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _BIG in got["during"]["changed"], got

    def test_an_untracked_big_file_never_reads_as_clean(self, repo: Path) -> None:
        """Absent at HEAD, there is nothing for its content to match. Mutation:
        a big file git has no blob for read as clean."""
        (repo / _BIG).write_bytes(bytes(range(100)))
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _BIG, "rewritten by hand" * 6)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _BIG in got["during"]["changed"], got

    def test_big_files_past_the_hash_budget_report_and_are_named(self, repo: Path, monkeypatch) -> None:
        """Mutations: no budget; a file past it read as hashed."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", 10)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _BIG in got["during"]["changed"], got
        assert any("one call may hash" in n and _BIG in n for n in got["notes"]), got

    def test_no_big_or_removed_files_blob_is_read_into_the_hook(self, repo: Path, monkeypatch) -> None:
        """A removal and a big file are asked for presence alone (a removed
        100 MB blob was streamed twice, measured). Mutation: either sent
        through the content batch."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        _git_ok(repo, "rm", "-q", _OTHER)
        _git_ok(repo, "commit", "-q", "-m", "drop plan_guard")
        real, contents = zw._git_objects, []

        def spy(root, requests, **kw):
            if not kw.get("check_only"):
                contents.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        assert zw.after_shell_call(repo, "s-1") is None
        assert not [r for r in contents if r.endswith((_BIG, _OTHER))], contents

    def _restored_pair(self, repo: Path, names: tuple[str, str], data: tuple[bytes, bytes]) -> tuple[Path, Path]:
        """Two big files committed, edited before the session, and the
        baseline taken: each is ready to be brought back."""
        files = tuple(repo / n for n in names)
        for f, d in zip(files, data):
            f.write_bytes(d)
        _git_ok(repo, "add", *names)
        _git_ok(repo, "commit", "-q", "-m", "two big files")
        for f in files:
            _bump(f, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        return files[0], files[1]

    def test_the_hash_runs_past_gits_own_big_file_threshold(self, repo: Path, monkeypatch) -> None:
        """Past core.bigFileThreshold (512 MiB by default, lower where a
        repository sets it) hash-object streams and compresses: 513 MiB took
        9.3 s against 233 ms at 511 MiB, so every such file met the timeout and
        reported (both reviews, driven). Mutation: the hash run without the
        threshold raised past the budget."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        real, argvs = hu.spawn_checked, []

        def spy(argv, **kw):
            argvs.append(list(argv))
            return real(argv, **kw)

        monkeypatch.setattr(hu, "spawn_checked", spy)
        assert zw.after_shell_call(repo, "s-1") is None
        hashes = [a for a in argvs if "hash-object" in a]
        assert hashes and all(a[1:3] == ["-c", f"core.bigFileThreshold={zw.BIG_HASH_BUDGET_BYTES + 1}"]
                              for a in hashes), argvs

    def test_a_big_file_restored_through_its_eol_filter_is_silent(self, repo: Path) -> None:
        """Git hashes the file as it would commit it: CRLF on disk under
        `eol=crlf` is LF in the blob. Mutation: the hash run with
        --no-filters (code review: it turns every filtered shape loud)."""
        (repo / ".gitattributes").write_bytes(b"*.bin text eol=crlf\n")
        (repo / _BIG).write_bytes(b"a line of committed text\n" * 4)
        _git_ok(repo, "add", ".gitattributes", _BIG)
        _git_ok(repo, "commit", "-q", "-m", "a big text file")
        _bump(repo / _BIG, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", _BIG)
        assert (repo / _BIG).read_bytes().count(b"\r\n") == 4   # the filter really ran
        assert zw.after_shell_call(repo, "s-1") is None

    def test_the_budget_is_spent_file_by_file(self, repo: Path, monkeypatch) -> None:
        """Mutations: the budget never spent (every file hashed); a file the
        exact size of what is left read as past it."""
        a, b = self._restored_pair(repo, ("tools/cc/hooks/a.bin", _BIG), (bytes(range(100)), bytes(range(100, 200))))
        a.write_bytes(bytes(range(100)))
        b.write_bytes(bytes(range(100, 200)))
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", 100)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == [_BIG], got
        assert any("one call may hash" in n and _BIG in n for n in got["notes"]), got

    def test_each_hash_is_matched_with_its_own_file(self, repo: Path) -> None:
        """Two files in one hash: one brought back, one edited by hand.
        Mutation: the hashes paired with the wrong paths (code review)."""
        a, b = self._restored_pair(repo, ("tools/cc/hooks/a.bin", _BIG), (bytes(range(100)), bytes(range(100, 200))))
        a.write_bytes(bytes(range(100)))
        _bump(b, "not what was committed" * 5)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == [_BIG], got

    def test_an_untracked_big_file_spends_none_of_the_budget(self, repo: Path, monkeypatch) -> None:
        """Mutation: a file absent at HEAD hashed anyway, so the budget runs
        out before the committed one (code review)."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        loose = repo / "tools/cc/hooks/a.bin"
        loose.write_bytes(bytes(range(100)))
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        _bump(loose, "r" * 100)   # within the budget: hashed, it would spend all of it
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", 100)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == ["tools/cc/hooks/a.bin"], got

    def test_the_budget_is_the_calls_not_each_checkouts(self, repo: Path, upstream: Path, monkeypatch) -> None:
        """Mutation: the budget restarted for each checkout (code review)."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        (repo / "models").mkdir()
        _gx(repo / "models", "clone", "-q", str(upstream), "clone")
        weights = repo / "models" / "clone" / "weights.bin"
        _bump(weights, "edited before the session" * 10)
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        _gx(repo / "models" / "clone", "checkout", "--", "weights.bin")
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", 200)   # each alone fits; together they do not
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == ["models/clone/weights.bin"], got
        assert any("one call may hash" in n and "models/clone/weights.bin" in n for n in got["notes"]), got

    @pytest.mark.parametrize(("timed_out", "says"), [(False, "could not hash"), (True, "did not finish hashing")])
    def test_a_hash_git_does_not_give_names_its_files_and_says_why(
            self, repo: Path, monkeypatch, timed_out: bool, says: str) -> None:
        """Mutations: the note dropped; one wording for a failure and a
        timeout; the files left unnamed (code review)."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        monkeypatch.setattr(zw, "_hash_objects", lambda *a, **kw: (None, timed_out))
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _BIG in got["during"]["changed"], got
        assert any(n.startswith(f"git {says} 1 file(s)") and _BIG in n for n in got["notes"]), got

    def test_a_hash_with_no_time_left_is_not_started(self, repo: Path, monkeypatch) -> None:
        """Path 2's spawns share GIT_ASK_BUDGET_S: three of them a checkout
        could each take 5 s before, past the hook's own 10 s (code review).
        The asks are made to take the whole budget on a clock run ahead, no
        sleep. Mutation: the hash given a timeout of its own."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        skew = _clock_run_ahead(monkeypatch)
        real = zw._git_objects

        def slow(*args, **kw):
            got = real(*args, **kw)
            skew[0] += zw.GIT_ASK_BUDGET_S
            return got

        monkeypatch.setattr(zw, "_git_objects", slow)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _BIG in got["during"]["changed"], got
        assert any(n.startswith("git did not finish hashing 1 file(s)") for n in got["notes"]), got

    def test_a_slow_hash_never_costs_a_nested_checkout_its_asks(
            self, repo: Path, upstream: Path, monkeypatch) -> None:
        """The outer checkout's hash ran before the nested asks and spent
        their budget, so a pull in a known clone reported again (failure-mode
        review: a 608 MiB file, driven). A clock run ahead stands in for the
        slow hash. Mutation: each checkout hashed in its turn."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        (repo / "models").mkdir()
        _gx(repo / "models", "clone", "-q", str(upstream), "clone")
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        _advance(upstream)
        _gx(repo / "models" / "clone", "pull", "-q", "--ff-only")
        skew = _clock_run_ahead(monkeypatch)
        real = zw._hash_objects

        def slow(root, paths, *, cwd=None, **kw):
            if cwd is None:
                skew[0] += zw.NESTED_ASK_BUDGET_S + 0.5
            return real(root, paths, cwd=cwd, **kw)

        monkeypatch.setattr(zw, "_hash_objects", slow)
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_big_file_cut_short_reads_no_blob_and_reports(self, repo: Path, monkeypatch) -> None:
        """Big at HEAD and at the previous check, small now (a failed
        download): its blob can never match, and a 400 MiB one cost 1.7 s and
        1.6 GB (code review, driven). Mutation: sorted by its size now alone."""
        self._commit_big(repo, bytes(range(100)))
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _BIG, "cut\n")
        real, contents = zw._git_objects, []

        def spy(root, requests, **kw):
            if not kw.get("check_only"):
                contents.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _BIG in got["during"]["changed"], got
        assert not [r for r in contents if r.endswith(_BIG)], contents

    def test_a_file_that_becomes_a_directory_is_gits_removal(self, repo: Path) -> None:
        """A tree at HEAD is no blob there. Mutation: a tree or a gitlink
        answered by the presence check read as the file still committed."""
        lib = "tools/cc/hooks/lib"
        (repo / lib).write_bytes(b"a file\n")
        _git_ok(repo, "add", lib)
        _git_ok(repo, "commit", "-q", "-m", "lib file")
        _git_ok(repo, "switch", "-q", "-c", "dir")
        _git_ok(repo, "rm", "-q", lib)
        (repo / lib).mkdir()
        (repo / lib / "a.py").write_bytes(b"print('a')\n")
        _git_ok(repo, "add", lib)
        _git_ok(repo, "commit", "-q", "-m", "lib directory")
        _git_ok(repo, "switch", "-q", "main")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "merge", "-q", "--ff-only", "dir")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_an_inherited_git_dir_does_not_send_the_nested_hash_elsewhere(
            self, repo: Path, upstream: Path, monkeypatch) -> None:
        """The clone's own config (`core.autocrlf`) decides its hash, as its
        own git would. Mutation: the hash spawn keeps GIT_DIR, so the outer
        repository's config hashes the clone's file (code review)."""
        work = upstream.parent / "work"
        (work / "notes.txt").write_bytes(b"a line of committed text\n" * 4)
        _gx(work, "add", "notes.txt")
        _gx(work, "commit", "-q", "-m", "notes")
        _gx(work, "push", "-q", "origin", "HEAD:main")
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        (repo / "models").mkdir()
        _gx(repo / "models", "clone", "-q", str(upstream), "clone")
        clone = repo / "models" / "clone"
        _gx(clone, "config", "core.autocrlf", "true")
        _bump(clone / "notes.txt", "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        _gx(clone, "-c", "core.autocrlf=true", "checkout", "--", "notes.txt")
        assert (clone / "notes.txt").read_bytes().count(b"\r\n") == 4   # the clone's own setting ran
        monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_big_files_stash_and_pop_are_silent_and_read_no_blob(self, repo: Path, monkeypatch) -> None:
        """A big file's content before is its stat, which a pop's new
        modification time never matches, so its pop reported (DEF-5019): the
        stash is asked for its blob id, matched with git's hash of the file.
        Mutations: the stash never asked; a big file's stash asked for its
        content."""
        big = self._commit_big(repo, bytes(range(100)))
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        real, contents = zw._git_objects, []

        def spy(root, requests, **kw):
            if not kw.get("check_only"):
                contents.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        _git_ok(repo, "stash", "-q")
        assert zw.after_shell_call(repo, "s-1") is None
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None
        assert not [r for r in contents if r.endswith(_BIG)], contents


def _clock_run_ahead(monkeypatch) -> list[float]:
    """The zone module's monotonic clock, run ahead by the list's one value:
    a stand-in for a spawn that took that long, with no sleep."""
    skew = [0.0]
    real = time.monotonic
    monkeypatch.setattr(zw, "time", types.SimpleNamespace(monotonic=lambda: real() + skew[0],
                                                          time_ns=time.time_ns, time=time.time))
    return skew


class TestAStashPopOfAnEditMadeBeforeTheSessionIsKnown:
    """A changed path git accounted for keeps its content before as known when
    the checkout's stash took that content, so the pop of a stash that took a
    pre-session edit back to HEAD reads as known (DEF-5018; docs/HOOKS.md says
    a stash and its pop stay quiet). Only what the stash took: the first fix
    kept every git-accounted path's content before, and a slip git restored
    then written again went silent (failure-mode review, driven)."""

    def test_the_stash_and_its_pop_are_both_silent(self, repo: Path) -> None:
        """Mutation: only a moved path's new content remembered (the defect)."""
        _bump(repo / _HOOK, "print('an edit made before the session')\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "-q")
        assert _context(_post(repo, "Bash", {"command": "git stash"})) == ""
        _git_ok(repo, "stash", "pop", "-q")
        assert _context(_post(repo, "Bash", {"command": "git stash pop"})) == ""

    def test_the_same_inside_a_known_nested_checkout(self, repo: Path, upstream: Path) -> None:
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        (repo / "models").mkdir()
        _gx(repo / "models", "clone", "-q", str(upstream), "clone")
        clone = repo / "models" / "clone"
        _bump(clone / "weights.json", '{"v": "edited before the session"}\n')
        assert zw.take_baseline(repo, "s-1")
        _gx(clone, "stash", "-q")
        assert _context(_post(repo, "Bash", {"command": "git -C models/clone stash"})) == ""
        _gx(clone, "stash", "pop", "-q")
        assert _context(_post(repo, "Bash", {"command": "git -C models/clone stash pop"})) == ""

    def test_a_return_to_content_git_never_moved_still_reports(self, repo: Path) -> None:
        """Known grows only by git's own accounting: a slip by hand over a
        pre-session edit, then the edit written back by hand, reports both
        times. Mutation: every moved path's old content remembered."""
        _bump(repo / _HOOK, "print('an edit made before the session')\n")
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('a slip')\n")
        assert f"changed {_HOOK}" in _context(_post(repo, "Bash", _FORMATTER))
        _bump(repo / _HOOK, "print('an edit made before the session')\n")
        assert f"changed {_HOOK}" in _context(_post(repo, "Bash", _FORMATTER))

    def test_a_slip_git_restored_then_written_again_still_reports(self, repo: Path) -> None:
        """A formatter's slip left from an earlier session, restored with git,
        then the same formatter run again: no stash took it, so it is not
        known. Mutation: every git-accounted path's content before kept (the
        first fix; failure-mode review W1)."""
        slip = "print('a formatter slip from an earlier session')\n"
        _bump(repo / _HOOK, slip)
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", _HOOK)
        assert _context(_post(repo, "Bash", {"command": "git checkout -- ."})) == ""
        _bump(repo / _HOOK, slip)
        assert f"changed {_HOOK}" in _context(_post(repo, "Bash", _FORMATTER))

    def test_a_stash_beside_a_pull_keeps_only_what_the_stash_took(self, repo: Path) -> None:
        """The stash holds every tracked file, so a file the pull moved is in
        it unchanged: its content before (what the pull replaced) is the
        stash parent's too and is not kept, and a script writing it back
        reports; the stashed edit's pop stays quiet. Mutation: the stash's
        content alone, without its parent, taken as what it took."""
        _git_ok(repo, "switch", "-q", "-c", "fix")
        _bump(repo / _HOOK, "print('the fix')\n")
        _git_ok(repo, "commit", "-q", "-am", "fix")
        _git_ok(repo, "switch", "-q", "main")
        _bump(repo / _OTHER, "print('an edit made before the session')\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "-q")
        _git_ok(repo, "merge", "-q", "--ff-only", "fix")
        assert _context(_post(repo, "Bash", {"command": "git stash && git merge --ff-only fix"})) == ""
        _bump(repo / _HOOK, "print('guard')\n")   # the content the merge replaced
        assert f"changed {_HOOK}" in _context(_post(repo, "Bash", _FORMATTER))
        _git_ok(repo, "stash", "pop", "-q")
        assert _context(_post(repo, "Bash", {"command": "git stash pop"})) == ""

    @staticmethod
    def _stamp_stash(repo: Path, when_ns: int) -> None:
        """The newest stash's reflog line given another time: the check reads
        when a stash was made from that line, git's own whole seconds."""
        log = repo / ".git" / "logs" / "refs" / "stash"
        lines = log.read_text(encoding="utf-8").splitlines()
        head, tab, message = lines[-1].partition("\t")
        parts = head.split(" ")
        parts[-2] = str(when_ns // 1_000_000_000)
        lines[-1] = " ".join(parts) + tab + message
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_a_stash_from_before_the_session_costs_no_ask(self, repo: Path, monkeypatch) -> None:
        """A stash kept for days is not asked on every call git moves a file:
        only one made since the previous check is. Mutation: any stash
        asked, made since or not."""
        _bump(repo / _OTHER, "print('an edit stashed long ago')\n")
        _git_ok(repo, "stash", "-q")
        self._stamp_stash(repo, time.time_ns() - 60_000_000_000)
        _bump(repo / _HOOK, "print('a slip')\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", _HOOK)
        real, asked = zw._git_objects, []

        def spy(root, requests, **kw):
            asked.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        assert zw.after_shell_call(repo, "s-1") is None
        assert asked and not [r for r in asked if not r.startswith("HEAD:")], asked

    def test_a_stash_stamped_in_the_second_of_the_check_still_counts(self, repo: Path) -> None:
        """git stamps a stash's reflog line in whole seconds, floored, so one
        made just after a check can carry the check's own second: it is made
        since, and what it took is checked then. Mutation: the reflog's whole
        second compared with the check's nanoseconds."""
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('written and stashed in the second of the check')\n")
        _git_ok(repo, "stash", "-q")
        taken = zw.read_baseline(zw.baseline_path(repo, "s-1"))["taken_ns"]
        self._stamp_stash(repo, taken)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got


def _state_ignored(repo: Path) -> None:
    """The session state ignored, as `init` leaves it: a `git stash -u` would
    otherwise take the baseline with the untracked files."""
    (repo / ".gitignore").write_bytes(b".espalier-state/\n")
    _git_ok(repo, "add", ".gitignore")
    _git_ok(repo, "commit", "-q", "-m", "ignore the state")


class TestWhatAStashHoldsIsGits:
    """Path 2 asks the stash the previous check saw for what a pop or an apply
    brings back, and the stash made since for what it took (DEF-5019): each
    shape was driven against #297's check first, which reported it and told
    Claude to stop. Only what a stash changed at a path vouches for it."""

    def test_the_pop_of_a_stash_made_before_the_session_is_silent(self, repo: Path) -> None:
        """Mutation: the stash the previous check saw never asked."""
        _bump(repo / _HOOK, "print('an edit stashed yesterday')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_the_same_inside_a_known_nested_checkout(self, repo: Path, upstream: Path) -> None:
        """Mutation: the outer checkout's stash asked for a nested one's file."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        (repo / "models").mkdir()
        _gx(repo / "models", "clone", "-q", str(upstream), "clone")
        clone = repo / "models" / "clone"
        _bump(clone / "weights.json", '{"v": "stashed yesterday"}\n')
        _gx(clone, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _gx(clone, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    @pytest.mark.parametrize("staged", [False, True])
    def test_a_new_file_stashed_and_popped_is_silent(self, repo: Path, staged: bool) -> None:
        """`stash -u` keeps a new file in its untracked-files parent, a stash
        of a staged one in its worktree commit; either way its stash read as
        a removal and its pop as an addition. Mutations: the untracked parent
        never asked; the stash made since never asked for what it took."""
        _state_ignored(repo)
        new = "tools/cc/hooks/new_hook.py"
        (repo / new).write_bytes(b"print('a hook made before the session')\n")
        if staged:
            _git_ok(repo, "add", new)
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "-q", *([] if staged else ["-u"]))
        assert zw.after_shell_call(repo, "s-1") is None
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_the_pop_of_a_stashed_deletion_is_silent(self, repo: Path) -> None:
        """The stash recorded the file as deleted (absent from its worktree
        commit, present in its parent). Mutation: a deletion the stash
        recorded not asked."""
        (repo / _OTHER).unlink()
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "-q")
        assert zw.after_shell_call(repo, "s-1") is None
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_write_back_of_what_a_stash_carried_unchanged_still_reports(self, repo: Path) -> None:
        """A stash holds every tracked file, so what a pull replaced is in it,
        unchanged: a script writing that back is no pop. Mutation: the stash's
        first parent not compared, so whatever it holds vouches."""
        _git_ok(repo, "switch", "-q", "-c", "fix")
        _bump(repo / _HOOK, "print('the fix')\n")
        _git_ok(repo, "commit", "-q", "-am", "fix")
        _git_ok(repo, "switch", "-q", "main")
        _bump(repo / _OTHER, "print('an edit stashed for the pull')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "merge", "-q", "--ff-only", "fix")
        assert zw.after_shell_call(repo, "s-1") is None
        _bump(repo / _HOOK, "print('guard')\n")   # what the merge replaced
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got

    def test_a_hand_edit_beside_a_stash_still_reports(self, repo: Path) -> None:
        _bump(repo / _OTHER, "print('stashed')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('a slip')\n")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got

    def test_a_stash_dropped_with_nothing_moving_is_recorded(self, repo: Path) -> None:
        """The check that changed nothing reads each stash too, so a dropped
        stash is not the one the next call asks. Mutation: the peek blind to
        the stash, which then vouches for its content written by hand."""
        _bump(repo / _HOOK, "print('an edit stashed yesterday')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "drop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None
        _bump(repo / _HOOK, "print('an edit stashed yesterday')\n")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got

    def test_the_stash_is_asked_inside_the_shared_budget_and_a_skip_says_so(self, repo: Path, monkeypatch) -> None:
        """A stash ask is a spawn of path 2, inside GIT_ASK_BUDGET_S. The HEAD
        asks are made to take it all on a clock run ahead, no sleep; the pop
        of a stashed deletion reads no blob, so nothing later masks the ask.
        Mutations: the stash asked with a timeout of its own; a skip silent."""
        (repo / _OTHER).unlink()
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "-q")
        assert zw.after_shell_call(repo, "s-1") is None
        _git_ok(repo, "stash", "pop", "-q")
        skew = _clock_run_ahead(monkeypatch)
        real, calls = zw._git_objects, []

        def slow(root, requests, **kw):
            got = real(root, requests, **kw)
            calls.append(requests)
            if len(calls) == 1:   # the HEAD asks, the first spawn
                skew[0] += zw.GIT_ASK_BUDGET_S
            return got

        monkeypatch.setattr(zw, "_git_objects", slow)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _OTHER in got["during"]["removed"], got
        assert any(n.startswith("the stash was not asked within") for n in got["notes"]), got
        assert len(calls) == 1, calls

    def test_with_no_stash_nothing_more_is_asked(self, repo: Path, monkeypatch) -> None:
        """The cost: a report with no stash in the checkout spends no stash
        ask. Mutation: the stash asked for whatever reports."""
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('a slip')\n")
        real, asked = zw._git_objects, []

        def spy(root, requests, **kw):
            asked.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        assert zw.after_shell_call(repo, "s-1") is not None
        assert asked and all(r.startswith("HEAD:") for r in asked), asked

    def test_a_baseline_without_the_stash_still_reads(self, repo: Path) -> None:
        """Expand only: a baseline written before the key reads as no stash."""
        assert zw.take_baseline(repo, "s-1")
        path = zw.baseline_path(repo, "s-1")
        record = json.loads(path.read_text(encoding="utf-8"))
        for key in ("stash", "stash_ok", "session_ns"):
            del record[key]
        path.write_text(json.dumps(record), encoding="utf-8")
        assert zw.read_baseline(path) is not None
        _bump(repo / _HOOK, "print('a slip')\n")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got

    # -- round 1's findings, each driven against commit A first --

    def test_a_tracked_file_deleted_beside_a_new_stash_still_reports(self, repo: Path) -> None:
        """A stash resets a file HEAD holds; it never removes one, so a
        deletion beside it is no stash of a new file (both reviews: silent
        on commit A). Mutation: the made stash vouching whatever HEAD holds."""
        _bump(repo / _HOOK, "print('an edit made before the session')\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "-q")
        (repo / _HOOK).unlink()
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["removed"], got

    def test_another_worktrees_stash_vouches_for_nothing_here(self, repo: Path, tmp_path: Path) -> None:
        """refs/stash belongs to the whole repository: a linked worktree's
        pop of the main checkout's stash reports (failure-mode review, silent
        on commit A). Mutation: any stash in refs/stash taken as this one's."""
        other = tmp_path / "seat-b"
        _git_ok(repo, "worktree", "add", "-q", "-b", "seat-b", str(other))
        _bump(repo / _HOOK, "print('seat a stashed this')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(other, "s-b")
        _git_ok(other, "stash", "pop", "-q")
        got = zw.after_shell_call(other, "s-b")
        assert got is not None and _HOOK in got["during"]["changed"], got

    def test_a_detached_checkouts_stash_vouches_for_nothing(self, repo: Path) -> None:
        """Its reflog line names (no branch), which no worktree is (a named
        limit: the loud side). Mutation: a detached HEAD matched to the line."""
        _git_ok(repo, "switch", "-q", "--detach")
        _bump(repo / _HOOK, "print('stashed while detached')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got

    def test_a_stash_made_with_a_message_is_this_checkouts_too(self, repo: Path) -> None:
        """`git stash -m` writes "On <branch>:", not "WIP on <branch>:".
        Mutation: one message shape read."""
        _bump(repo / _HOOK, "print('an edit stashed with a message')\n")
        _git_ok(repo, "stash", "push", "-q", "-m", "before the pull")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_change_written_and_stashed_in_one_call_reports_then(self, repo: Path) -> None:
        """`ruff format . && git stash` leaves the tree as it was, and the
        pop would bring the rewrite back as the stash's: the call that first
        sees a new stash compares what it took with what the previous check
        saw (failure-mode review, silent on commit A). Mutation: a new stash
        never checked."""
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('a formatter rewrote this')\n")
        _git_ok(repo, "stash", "-q")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got
        assert any("took content no check saw" in n for n in got["notes"]), got
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_deletion_stashed_in_the_call_that_made_it_reports(self, repo: Path) -> None:
        """Mutation: a stash's recorded deletion of a file the previous check
        saw read as taken from the session's tree."""
        assert zw.take_baseline(repo, "s-1")
        (repo / _OTHER).unlink()
        _git_ok(repo, "stash", "-q")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _OTHER in got["during"]["changed"], got

    def test_a_new_file_made_and_stashed_in_one_call_reports(self, repo: Path) -> None:
        """Mutation: a file no check saw, in the untracked-files parent, not checked."""
        _state_ignored(repo)
        assert zw.take_baseline(repo, "s-1")
        new = "tools/cc/hooks/new_hook.py"
        (repo / new).write_bytes(b"print('made and stashed in one call')\n")
        _git_ok(repo, "stash", "-q", "-u")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and new in got["during"]["added"], got

    def test_an_older_stash_a_pop_exposes_is_no_new_one(self, repo: Path) -> None:
        """Popping the newest stash exposes an older one, made before the
        previous check: it took no new file now (code review MINOR-1, silent on
        commit A). Mutation: any stash other than the recorded one read as
        made since."""
        _state_ignored(repo)
        new = "tools/cc/hooks/new_hook.py"
        (repo / new).write_bytes(b"print('stashed with -u')\n")
        _git_ok(repo, "stash", "-q", "-u")
        _git_ok(repo, "stash", "apply", "-q")
        _bump(repo / _HOOK, "print('a second stash')\n")
        _git_ok(repo, "stash", "push", "-q", "--", _HOOK)
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        (repo / new).unlink()
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and new in got["during"]["removed"], got

    def test_a_hand_delete_of_a_file_no_stash_deleted_still_reports(self, repo: Path) -> None:
        """An untracked protected file removed beside a stash that never held
        it. Mutation: a deletion read from the stash alone, its parent not
        asked."""
        loose = repo / "tools/cc/hooks/local_only.py"
        loose.write_bytes(b"print('never committed')\n")
        _bump(repo / _OTHER, "print('stashed')\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        loose.unlink()
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and "tools/cc/hooks/local_only.py" in got["during"]["removed"], got

    def test_a_big_new_files_stash_reads_no_blob(self, repo: Path, monkeypatch) -> None:
        """A big file's content before is its stat: its stash with -u is
        matched by size, never read (a named limit: its pop reports). Mutation:
        the stash asked for a big removal's content."""
        monkeypatch.setattr(zw, "BIG_FILE_BYTES", 64)
        _state_ignored(repo)
        big = "tools/cc/hooks/big_new.bin"
        (repo / big).write_bytes(bytes(range(100)))
        assert zw.take_baseline(repo, "s-1")
        real, contents = zw._git_objects, []

        def spy(root, requests, **kw):
            if not kw.get("check_only"):
                contents.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        _git_ok(repo, "stash", "-q", "-u")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and big in got["during"]["removed"], got
        assert not [r for r in contents if r.endswith(big)], contents

    def test_a_stash_blob_far_bigger_than_the_file_is_not_read(self, repo: Path, monkeypatch) -> None:
        """No small file can equal a blob twice its size and more, so such a
        stash blob is never streamed (code review: a 300 MiB one cost 749 MiB).
        Mutation: a small file's stash blob read whatever its size."""
        monkeypatch.setattr(zw, "BIG_FILE_BYTES", 64)
        _bump(repo / _HOOK, "w" * 300)          # a version far past the file's size, stashed before the session
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        stash = zw.stash_tops(repo, [])[""]
        _bump(repo / _HOOK, "a slip, small")
        real, contents = zw._git_objects, []

        def spy(root, requests, **kw):
            if not kw.get("check_only"):
                contents.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got
        assert not [r for r in contents if r.startswith(stash)], contents

    def test_a_clone_appearing_with_a_stash_has_it_asked_next_call(
            self, repo: Path, upstream: Path) -> None:
        """A checkout found only in the snapshot has its stash read then, so
        its pop on the next call is asked. Mutation: the stash read only for
        the checkouts known before the snapshot."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        work = upstream.parent / "work"
        _bump(work / "weights.json", '{"v": "stashed in the clone"}\n')
        _gx(work, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        (repo / "models").mkdir()
        shutil.copytree(work, repo / "models" / "clone")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None, "a checkout that appears reports its files once"
        _gx(repo / "models" / "clone", "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    # -- the mutants' round: each pins a line no row above could fail --

    _stamp_stash = staticmethod(TestAStashPopOfAnEditMadeBeforeTheSessionIsKnown._stamp_stash)

    def test_a_baseline_without_the_stash_keys_takes_an_older_stash_as_there_before(self, repo: Path) -> None:
        """A session begun before the check read the stash has a baseline
        without its keys: a stash made before that baseline is no new one, so
        a call that moves nothing reports nothing, and its pop is git's.
        Mutation: a stash made before the previous check read as made since."""
        _bump(repo / _HOOK, "print('an edit stashed yesterday')\n")
        _git_ok(repo, "stash", "-q")
        self._stamp_stash(repo, time.time_ns() - 60_000_000_000)
        assert zw.take_baseline(repo, "s-1")
        path = zw.baseline_path(repo, "s-1")
        record = json.loads(path.read_text(encoding="utf-8"))
        for key in ("stash", "stash_at", "stash_ok", "session_ns"):
            del record[key]
        path.write_text(json.dumps(record), encoding="utf-8")
        assert zw.after_shell_call(repo, "s-1") is None
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_the_older_of_two_stashes_made_in_one_call_reports_at_its_pop(self, repo: Path) -> None:
        """Only the newest stash is checked in the call that makes it, so the
        older one a pop exposes vouches for nothing (a named limit: the loud
        side). Mutations: every stash vouching; the stash the previous check
        saw vouching though no check trusted it."""
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "print('the first stash')\n")
        _git_ok(repo, "stash", "-q")
        _bump(repo / _OTHER, "print('the second stash')\n")
        _git_ok(repo, "stash", "-q")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == [_OTHER], got
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None
        _git_ok(repo, "stash", "pop", "-q")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got

    def test_two_stashes_from_before_the_session_pop_one_after_the_other(self, repo: Path) -> None:
        """An older stash made before the session, which a pop exposes, is
        trusted as the newest one was. Mutation: only the stash the session
        began with trusted."""
        _bump(repo / _HOOK, "print('the older stash')\n")
        _git_ok(repo, "stash", "-q")
        self._stamp_stash(repo, time.time_ns() - 120_000_000_000)
        _bump(repo / _OTHER, "print('the newer stash')\n")
        _git_ok(repo, "stash", "-q")
        self._stamp_stash(repo, time.time_ns() - 60_000_000_000)
        assert zw.take_baseline(repo, "s-1")
        for _ in range(2):
            _git_ok(repo, "stash", "pop", "-q")
            assert zw.after_shell_call(repo, "s-1") is None

    def test_a_big_file_changed_and_stashed_in_one_call_reports_then(self, repo: Path, monkeypatch) -> None:
        """A big file's content before is its stat, so its new stash blob is
        compared by size (a same-size change is a named limit). Mutation: the
        size not compared."""
        monkeypatch.setattr(zw, "BIG_FILE_BYTES", 64)
        big = repo / "tools/cc/hooks/big.bin"
        big.write_bytes(bytes(range(100)))
        _git_ok(repo, "add", "tools/cc/hooks/big.bin")
        _git_ok(repo, "commit", "-q", "-m", "big")
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(150)))
        _git_ok(repo, "stash", "-q")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == ["tools/cc/hooks/big.bin"], got
        _git_ok(repo, "stash", "pop", "-q")
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_new_stashs_blob_far_bigger_than_the_file_is_not_read(self, repo: Path, monkeypatch) -> None:
        """What a new stash took is compared with what the previous check saw,
        and no small file can equal a blob twice its size and more, so that
        blob reports unread. Mutation: the new stash's blob read whatever its
        size."""
        monkeypatch.setattr(zw, "BIG_FILE_BYTES", 64)
        assert zw.take_baseline(repo, "s-1")
        _bump(repo / _HOOK, "w" * 300)
        _git_ok(repo, "stash", "-q")
        blob = _git(repo, "rev-parse", f"stash@{{0}}:{_HOOK}").stdout.strip().decode("ascii")
        real, contents = zw._git_objects, []

        def spy(root, requests, **kw):
            if not kw.get("check_only"):
                contents.extend(requests)
            return real(root, requests, **kw)

        monkeypatch.setattr(zw, "_git_objects", spy)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and _HOOK in got["during"]["changed"], got
        assert blob not in contents, contents

    def test_a_submodule_a_stash_records_is_no_file_it_took(self, repo: Path, upstream: Path) -> None:
        """A stash of the outer checkout records a submodule's staged move as a
        commit id at its path, no file the check watches: the submodule's
        files are its own git's. git stashes it only beside another change,
        here an edit a check already reported. Mutation: a gitlink in the
        stash read as a file it took."""
        (repo / "espalier.toml").write_bytes(b'protected_paths = ["models/"]\n')
        _gx(repo, "submodule", "add", "-q", str(upstream), "models/sub")
        _gx(repo, "commit", "-q", "-m", "sub")
        assert zw.take_baseline(repo, "s-1")
        _advance(upstream)
        _gx(repo / "models" / "sub", "pull", "-q", "--ff-only", "origin", "main")
        assert zw.after_shell_call(repo, "s-1") is None
        _bump(repo / _OTHER, "print('an edit a check saw')\n")
        assert zw.after_shell_call(repo, "s-1") is not None
        _gx(repo, "add", "models/sub")
        _gx(repo, "stash", "-q")
        assert "160000" in _gx(repo, "diff-tree", "-r", "stash^1", "stash").stdout, "the stash recorded the move"
        assert zw.after_shell_call(repo, "s-1") is None


_FAKE_LFS = b'''import hashlib, os, sys
mode, store = sys.argv[1], sys.argv[2]
data = sys.stdin.buffer.read()
POINTER = b"version https://git-lfs.github.com/spec/v1\\n"
if mode == "clean" and not data.startswith(POINTER):
    oid = hashlib.sha256(data).hexdigest()
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, oid), "wb") as fh:
        fh.write(data)
    data = POINTER + b"oid sha256:" + oid.encode() + b"\\nsize " + str(len(data)).encode() + b"\\n"
elif mode == "smudge" and data.startswith(POINTER):
    with open(os.path.join(store, data.split(b"oid sha256:")[1].split()[0].decode()), "rb") as fh:
        data = fh.read()
sys.stdout.buffer.write(data)
'''


class TestAFileGitCallsCleanUnderItsFiltersIsGits:
    """A file whose working copy is not its committed form under the
    checkout's own filters was matched one way only, so git bringing it back
    reported (DEF-5020): a small one is hashed through the filters when its
    bytes miss, a big one with none when its filtered hash misses. Only on
    the report path. BIG_FILE_BYTES lowered, so no test writes 4 MiB."""

    @pytest.fixture(autouse=True)
    def _small_threshold(self, monkeypatch) -> None:
        monkeypatch.setattr(zw, "BIG_FILE_BYTES", 64)

    @staticmethod
    def _lfs(repo: Path, tmp_path: Path) -> Path:
        """A clean/smudge filter in the git-lfs shape (content in, pointer
        out), git-lfs itself not being on every runner."""
        script = tmp_path / "fake_lfs.py"
        script.write_bytes(_FAKE_LFS)
        run = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'
        store = (tmp_path / "lfs-store").as_posix()
        _git_ok(repo, "config", "filter.fake.clean", f'{run} clean "{store}"')
        _git_ok(repo, "config", "filter.fake.smudge", f'{run} smudge "{store}"')
        _git_ok(repo, "config", "filter.fake.required", "true")
        (repo / ".gitattributes").write_bytes(b"*.bin filter=fake\n")
        weights = repo / "tools/cc/hooks/w.bin"
        weights.write_bytes(b"small weights\n")
        _git_ok(repo, "add", ".gitattributes", "tools/cc/hooks/w.bin")
        _git_ok(repo, "commit", "-q", "-m", "a filtered file")
        return weights

    def test_a_clean_filtered_small_file_brought_back_is_silent(self, repo: Path, tmp_path: Path) -> None:
        """Its blob is the pointer, its working copy the content. Mutations:
        a small file never hashed the other way; hashed with no filters."""
        weights = self._lfs(repo, tmp_path)
        assert _git(repo, "cat-file", "-p", "HEAD:tools/cc/hooks/w.bin").stdout.startswith(b"version https://git-lfs")
        _bump(weights, "edited before the session\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", "tools/cc/hooks/w.bin")
        assert weights.read_bytes() == b"small weights\n"
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_hand_edit_of_a_filtered_file_still_reports(self, repo: Path, tmp_path: Path) -> None:
        """Neither way matches content git never held. Mutation: any file
        hashed the other way read as committed."""
        weights = self._lfs(repo, tmp_path)
        assert zw.take_baseline(repo, "s-1")
        _bump(weights, "not what was committed, by hand\n")
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and "tools/cc/hooks/w.bin" in got["during"]["changed"], got

    def test_a_big_crlf_text_under_autocrlf_brought_back_is_silent(self, repo: Path) -> None:
        """Committed with CRLF line ends, then core.autocrlf: git calls it
        clean, while its filtered hash is the LF form's. Mutation: a big file
        never hashed with no filters."""
        text = repo / "tools/cc/hooks/table.csv"
        text.write_bytes(b"a,b,c\r\n" * 20)
        _git_ok(repo, "add", "tools/cc/hooks/table.csv")
        _git_ok(repo, "commit", "-q", "-m", "a CRLF table")
        _git_ok(repo, "config", "core.autocrlf", "true")
        _bump(text, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", "tools/cc/hooks/table.csv")
        assert text.read_bytes() == b"a,b,c\r\n" * 20
        assert zw.after_shell_call(repo, "s-1") is None

    def test_the_other_way_counts_in_the_byte_budget(self, repo: Path, tmp_path: Path, monkeypatch) -> None:
        """Mutation: the second hash taken whatever is left of the budget."""
        weights = self._lfs(repo, tmp_path)
        _bump(weights, "edited before the session\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", "tools/cc/hooks/w.bin")
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", 1)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and "tools/cc/hooks/w.bin" in got["during"]["changed"], got
        assert any("one call may hash" in n and "w.bin" in n for n in got["notes"]), got

    def test_the_second_hash_spends_the_budget_file_by_file(self, repo: Path, tmp_path: Path, monkeypatch) -> None:
        """Mutation: the second hash's bytes never counted (code review MI)."""
        weights = self._lfs(repo, tmp_path)
        more = repo / "tools/cc/hooks/x.bin"
        more.write_bytes(b"small weights\n")
        _git_ok(repo, "add", "tools/cc/hooks/x.bin")
        _git_ok(repo, "commit", "-q", "-m", "a second filtered file")
        for f in (weights, more):
            _bump(f, "edited before the session\n")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "checkout", "--", "tools/cc/hooks/w.bin", "tools/cc/hooks/x.bin")
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", len(b"small weights\n"))
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == ["tools/cc/hooks/x.bin"], got
        assert any("a second time" in n and "x.bin" in n for n in got["notes"]), got

    def test_a_git_lfs_files_stash_pop_is_silent(self, repo: Path, tmp_path: Path) -> None:
        """Its stash holds the pointer, so its content never matches: the
        pointer earns the hash through the filters (both reviews, loud on
        commit A). Mutation: the stash's id left out of the second hash."""
        weights = self._lfs(repo, tmp_path)
        _bump(weights, "weights edited before the session\n")
        _git_ok(repo, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        assert weights.read_bytes() == b"weights edited before the session\n"
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_big_crlf_texts_stash_pop_is_silent(self, repo: Path) -> None:
        """Its stash holds CRLF, its filtered hash is the LF form's: its hash
        with no filters matches the stash (both reviews, loud on commit A)."""
        text = repo / "tools/cc/hooks/table.csv"
        text.write_bytes(b"a,b,c\r\n" * 20)
        _git_ok(repo, "add", "tools/cc/hooks/table.csv")
        _git_ok(repo, "commit", "-q", "-m", "a CRLF table")
        text.write_bytes(b"x,y,z\r\n" * 20)
        _git_ok(repo, "stash", "-q")
        _git_ok(repo, "config", "core.autocrlf", "true")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        assert text.read_bytes() == b"x,y,z\r\n" * 20
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_hand_edit_under_a_lossy_filter_still_reports(self, repo: Path) -> None:
        """`ident` collapses $Id$ on the way in, so an edit inside it hashes
        to HEAD's blob though git status calls it modified: only a git-lfs
        pointer earns the hash through the filters (failure-mode review).
        Mutation: any small file hashed through the filters."""
        (repo / ".gitattributes").write_bytes(b"*.ini ident\n")
        conf = repo / "tools/cc/hooks/guard.ini"
        conf.write_bytes(b"# $Id$\nmode = strict\n")
        _git_ok(repo, "add", ".gitattributes", "tools/cc/hooks/guard.ini")
        _git_ok(repo, "commit", "-q", "-m", "an ident file")
        assert zw.take_baseline(repo, "s-1")
        conf.write_bytes(b"# $Id: written by hand $\nmode = strict\n")   # ident's clean collapses it to $Id$
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and "tools/cc/hooks/guard.ini" in got["during"]["changed"], got

    def test_a_git_lfs_file_brought_back_in_a_sha256_repository_is_silent(self, tmp_path: Path) -> None:
        """The blob id a pointer's bytes give is taken in the repository's own
        hash. Mutation: a blob id always taken in SHA-1."""
        root = tmp_path / "sha256"
        (root / "tools" / "cc" / "hooks").mkdir(parents=True)
        (root / "tools/cc/hooks/write_guard.py").write_bytes(b"print('guard')\n")
        _git_ok(root, "init", "-q", "--object-format=sha256", "-b", "main")
        _git_ok(root, "add", "tools")
        _git_ok(root, "commit", "-q", "-m", "hooks")
        weights = self._lfs(root, tmp_path)
        _bump(weights, "edited before the session\n")
        assert zw.take_baseline(root, "s-1")
        _git_ok(root, "checkout", "--", "tools/cc/hooks/w.bin")
        assert zw.after_shell_call(root, "s-1") is None

    def test_the_budget_note_names_only_what_still_reports(self, repo: Path, monkeypatch) -> None:
        """A small slip beside a big file that spent the budget is no file
        "past the budget": its bytes were compared (code review MINOR-4).
        Mutation, since only a git-lfs pointer earns the second hash: any
        small file sent to it, which the spent budget then names."""
        big = repo / "tools/cc/hooks/big.bin"
        big.write_bytes(bytes(range(100)))
        _git_ok(repo, "add", "tools/cc/hooks/big.bin")
        _git_ok(repo, "commit", "-q", "-m", "big")
        _bump(big, "edited before the session" * 4)
        assert zw.take_baseline(repo, "s-1")
        big.write_bytes(bytes(range(100)))
        _bump(repo / _HOOK, "print('a slip')\n")
        monkeypatch.setattr(zw, "BIG_HASH_BUDGET_BYTES", 100)
        got = zw.after_shell_call(repo, "s-1")
        assert got is not None and got["during"]["changed"] == [_HOOK], got
        assert not any("one call may hash" in n for n in got["notes"]), got

    # -- the mutants' round: each pins a line no row above could fail --

    def test_a_big_text_autocrlf_normalized_pops_quietly(self, repo: Path) -> None:
        """Committed under core.autocrlf, the blob and the stash hold the LF
        form, which the hash through the filters matches, while the working
        copy is CRLF. Mutation: a big file's stash blob compared with HEAD's
        id, not with git's hash of the file."""
        _git_ok(repo, "config", "core.autocrlf", "true")
        crlf = ("-c", "core.autocrlf=true")   # _git pins it false for every other row
        text = repo / "tools/cc/hooks/table.csv"
        text.write_bytes(b"a,b,c\r\n" * 20)
        _git_ok(repo, *crlf, "add", "tools/cc/hooks/table.csv")
        _git_ok(repo, *crlf, "commit", "-q", "-m", "a table, normalized")
        assert _git(repo, "cat-file", "-p", "HEAD:tools/cc/hooks/table.csv").stdout == b"a,b,c\n" * 20
        text.write_bytes(b"x,y,z\r\n" * 20)
        _git_ok(repo, *crlf, "stash", "-q")
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, *crlf, "stash", "pop", "-q")
        assert text.read_bytes() == b"x,y,z\r\n" * 20
        assert zw.after_shell_call(repo, "s-1") is None

    def test_a_new_git_lfs_file_stashed_with_u_pops_quietly(self, repo: Path, tmp_path_factory) -> None:
        """HEAD holds no pointer for it; its stash's untracked-files parent
        does, and that pointer earns the hash through the filters (the filter
        kept outside the repository, which `-u` would stash). Mutation: only
        HEAD's blob read as a git-lfs pointer."""
        self._lfs(repo, tmp_path_factory.mktemp("lfs"))
        _state_ignored(repo)
        new = repo / "tools/cc/hooks/new.bin"
        new.write_bytes(b"new weights\n")
        _git_ok(repo, "stash", "-q", "-u")
        assert not new.exists()
        assert zw.take_baseline(repo, "s-1")
        _git_ok(repo, "stash", "pop", "-q")
        assert new.read_bytes() == b"new weights\n"
        assert zw.after_shell_call(repo, "s-1") is None


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
    copy_checkout(ROOT / "tools" / "cc", cc, ignore=shutil.ignore_patterns("__pycache__"))
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
