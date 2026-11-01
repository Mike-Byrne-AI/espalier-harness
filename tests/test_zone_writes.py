"""TP-476 wave A-1, accounting path 4: a harness writer records what it wrote.

Why: the zone after-check reports a protected-file change that nothing
accounts for. ``espalier upgrade``, ``integrity refresh``, ``freshness-pin``
and the transforming sync script rewrite protected files through a shell call
by design, so each brackets its own run and records what changed during it
(``espalier/zone_writes.py``); the hook reads the record
(``tools/cc/hooks/_zone_watch.py``). The engine never writes a session's
baseline: one writer per shared state (Core Rule 14).

Each earn-the-red test names the mutation it was seen red against; the twin
rows hold the engine's copy and the hook's equal.
"""
# slow-exempt: a few CLI and deployed-hook subprocesses over scratch trees, about a second each
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from espalier import zone_writes as ze
from tests._live_tree import checkout_glob

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "cc" / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_a1w", HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


zw = _load("_zone_watch")
_HOOK = "tools/cc/hooks/write_guard.py"
_MANIFEST = ".espalier/integrity.json"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    hooks = tmp_path / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "write_guard.py").write_bytes(b"print('guard')\n")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_bytes(b'{"hooks": {}}\n')
    return tmp_path


@pytest.fixture
def watched(tree: Path) -> Path:
    """The tree with a session watching it: a zone baseline on disk."""
    assert zw.take_baseline(tree, "s-1")
    return tree


def _bump(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    later = time.time_ns() + 5_000_000_000
    os.utime(path, ns=(later, later))


def _git(tree: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "core.autocrlf=false", *args],
                          cwd=str(tree), input=stdin, check=True, capture_output=True, timeout=30).stdout


def _commit(tree: Path) -> None:
    """The tree as a git repository with everything in it committed."""
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "tree"]):
        _git(tree, *args)


def _record(tree: Path, writer: str) -> dict:
    path = tree / ".espalier-state" / "zone_writes" / ze.record_name(writer)
    return json.loads(path.read_text(encoding="utf-8"))


class TestTheRecorder:
    def test_a_tree_no_session_watches_gains_no_state(self, tree: Path) -> None:
        with ze.recorded(tree, "espalier upgrade"):
            _bump(tree / _HOOK, b"print('upgraded')\n")
        assert not (tree / ".espalier-state").exists()

    def test_it_records_what_changed_during_the_run_with_the_hooks_digest(self, watched: Path) -> None:
        with ze.recorded(watched, "espalier upgrade"):
            _bump(watched / _HOOK, b"print('upgraded')\r\n")
            _bump(watched / "tools" / "cc" / "hooks" / "new_hook.py", b"x = 1\n")
            (watched / ".claude" / "settings.json").unlink()
        files = _record(watched, "espalier upgrade")["files"]
        assert set(files) == {_HOOK, "tools/cc/hooks/new_hook.py", ".claude/settings.json"}
        assert files[_HOOK][0] == zw.content_digest(watched / _HOOK)
        assert files[".claude/settings.json"][0] is None
        assert all(isinstance(entry[1], int) for entry in files.values())

    def test_a_writer_that_declares_over_recorded_files_still_records_their_changes(self, watched: Path) -> None:
        """A run that drops a bare `*` into a directory it began with (a venv
        made inside a source directory) keeps that directory in its
        after-stats, so a change it made there is recorded with its digest,
        not read as a removal. Mutation: take the after-stats with no prior."""
        with ze.recorded(watched, "espalier upgrade"):
            (watched / "tools" / "cc" / "hooks" / ".gitignore").write_bytes(b"*\n")
            _bump(watched / _HOOK, b"print('upgraded under the declaration')\n")
        files = _record(watched, "espalier upgrade")["files"]
        assert set(files) == {_HOOK, "tools/cc/hooks/.gitignore"}
        assert files[_HOOK][0] == zw.content_digest(watched / _HOOK)

    def test_a_change_made_before_the_run_is_not_recorded(self, watched: Path) -> None:
        """The slip just before the writer, in the same shell call, stays the
        hook's to report. Mutation: record every watched file whose mtime is
        recent (a racy window), not only what moved during the run."""
        (watched / _HOOK).write_bytes(b"print('a slip a moment before')\n")
        with ze.recorded(watched, "espalier integrity"):
            _bump(watched / _MANIFEST, b"{}\n")
        assert set(_record(watched, "espalier integrity")["files"]) == {_MANIFEST}

    def test_runs_of_one_writer_merge_and_the_newest_entry_wins(self, watched: Path) -> None:
        with ze.recorded(watched, "espalier upgrade"):
            _bump(watched / _HOOK, b"print('one')\n")
        with ze.recorded(watched, "espalier upgrade"):
            _bump(watched / _MANIFEST, b"{}\n")
        with ze.recorded(watched, "espalier upgrade"):
            _bump(watched / _HOOK, b"print('two')\n")
        files = _record(watched, "espalier upgrade")["files"]
        assert set(files) == {_HOOK, _MANIFEST}
        assert files[_HOOK][0] == zw.content_digest(watched / _HOOK)

    def test_a_writer_into_an_adopters_protected_path_records_it(self, watched: Path) -> None:
        """A seeded doc under a protected docs/ is the writer's, not a slip.
        Mutation: leave the adopter's protected_paths out of the recorder."""
        (watched / "espalier.toml").write_text('protected_paths = ["docs/"]\n', encoding="utf-8")
        with ze.recorded(watched, "espalier upgrade"):
            _bump(watched / "docs" / "HOOKS.md", b"# seeded\n")
        assert "docs/HOOKS.md" in _record(watched, "espalier upgrade")["files"]

    def test_the_running_marker_stands_for_the_run_and_goes_with_it(self, watched: Path) -> None:
        """A parallel check during the run holds its baseline. Mutation: no marker."""
        marker = watched / ".espalier-state" / "zone_writes" / (ze.record_name("espalier upgrade") + ze.RUNNING_SUFFIX)
        with ze.recorded(watched, "espalier upgrade"):
            assert marker.is_file()
            assert zw.writer_running(watched) == ze.record_name("espalier upgrade")
        assert not marker.exists()

    def test_a_record_that_cannot_be_written_never_costs_the_command(self, watched: Path, capsys) -> None:
        (watched / ".espalier-state" / "zone_writes").write_text("not a directory", encoding="utf-8")
        with ze.recorded(watched, "espalier upgrade"):
            _bump(watched / _HOOK, b"print('upgraded')\n")
        assert "could not record what espalier upgrade wrote" in capsys.readouterr().err


class TestTheTwinsAgree:
    def test_the_names_and_constants_are_one(self) -> None:
        for writer in ("espalier upgrade", "espalier integrity", "scripts/sync_selfcheck_tests.py", "a  b//c"):
            assert ze.record_name(writer) == zw.record_name(writer)
        hu = zw._hook_utils
        assert (ze.STATE_DIR, ze.RECORD_DIR, ze.SESSIONS_DIR, ze.BASELINE_SUFFIX) == (
            hu.STATE_DIR, zw.WRITE_RECORD_DIR, hu.SESSIONS_DIR, hu.ZONE_BASELINE_SUFFIX)
        assert ze.UNWATCHED_PREFIXES == zw.UNWATCHED_PREFIXES
        assert (ze.CACHE_DIR_NAMES, ze.CLUTTER_NAMES, ze.BIG_FILE_BYTES) == (
            zw.CACHE_DIR_NAMES, zw.CLUTTER_NAMES, zw.BIG_FILE_BYTES)
        assert (ze.RUNNING_SUFFIX, ze.RUNNING_MAX_S) == (zw.RUNNING_SUFFIX, zw.WRITER_RUNNING_MAX_S)
        for name in ("x.py", ".DS_Store", "a.swp", "a.swo", "a~", ".#a", ".a.1f2e.tmp", "a.tmp", ".env"):
            assert ze.is_clutter(name) == zw.is_clutter(name), name
        assert (ze.SELF_IGNORE_FILE, ze.SELF_IGNORE_READ_LIMIT) == (zw.SELF_IGNORE_FILE, zw.SELF_IGNORE_READ_LIMIT)

    def test_a_directory_that_ignores_itself_is_read_alike_and_pruned_on_both_sides(self, tree: Path) -> None:
        """The declaration is one predicate on both sides, over every shape
        it meets, and both walks prune what it names: a recorder that kept
        walking it would record what the hook never asks about, and a hook that
        kept walking it would ask about what no writer recorded. Mutations:
        prune it in the hook's walk only; in the recorder's only."""
        gen = tree / "tools" / "cc" / "gen"
        gen.mkdir()
        (gen / "a.d.ts").write_bytes(b"export {};\n")
        limit = zw.SELF_IGNORE_READ_LIMIT
        for raw, generated in (
            (b"*\n", True), (b"# made by a tool\n\n*\r\n", True), (b"\xef\xbb\xbf*\n", True),
            (b"*\n" + b"#" * (limit - 2), True),       # at the limit
            (b"*\n" + b"#" * (limit - 1), False),      # one byte past it
            (b"*\n!keep\n", False), (b"*.log\n", False), (b"", False), (b"\\*\n", False),
            (b"/*\n", False), (b"**\n", False), (b" *\n", False), (b"*\n*\n", False),
        ):
            (gen / ".gitignore").write_bytes(raw)
            assert ze.is_self_ignoring(gen) is zw.is_self_ignoring(gen) is generated, raw[:40]
            assert ("tools/cc/gen/a.d.ts" in ze._stats(tree)) is ("tools/cc/gen/a.d.ts" in zw.snapshot(tree)) is (not generated), raw[:40]
        (gen / ".gitignore").unlink()
        (gen / "elsewhere").write_bytes(b"*\n")
        try:
            os.symlink(gen / "elsewhere", gen / ".gitignore")
        except OSError:
            pass  # no symlink on this host: the regular-file arm above is the pin
        else:
            assert ze.is_self_ignoring(gen) is zw.is_self_ignoring(gen) is False  # a link is not git's file
        assert ze.is_self_ignoring(tree / "tools" / "cc" / "none") is zw.is_self_ignoring(tree / "tools" / "cc" / "none") is False

    def test_a_watched_top_never_prunes_itself_on_either_side(self, tree: Path) -> None:
        """A bare `*` at a zone's own root, the zone spelled as the adopter
        wrote it (`./vault`): both walks read the top by where the walk is,
        never by the prefix string. Mutations: drop the top test on the engine
        side; compare the top against the prefix string."""
        (tree / "espalier.toml").write_text('protected_paths = ["./vault"]\n', encoding="utf-8")
        (tree / "vault").mkdir()
        (tree / "vault" / ".gitignore").write_bytes(b"*\n")
        (tree / "vault" / "f.txt").write_bytes(b"x\n")
        (tree / "tools" / "cc" / ".gitignore").write_bytes(b"*\n")
        for side in (ze._stats(tree), zw.snapshot(tree)):
            assert "vault/f.txt" in side and _HOOK in side, sorted(side)

    def test_a_declaration_made_during_a_run_retires_nothing_on_either_side(self, watched: Path) -> None:
        """A writer (or a shell call) that drops a bare `*` into a directory
        the run began with keeps it walked on both sides: the recorder's
        after-stats and the hook's snapshot both still hold the hook.
        Mutations: take the after-stats with no prior; prune whatever the
        baseline holds."""
        before = ze._stats(watched)
        baseline = zw.read_baseline(zw.baseline_path(watched, "s-1"))["files"]
        (watched / "tools" / "cc" / "hooks" / ".gitignore").write_bytes(b"*\n")
        assert _HOOK in ze._stats(watched, before) and _HOOK not in ze._stats(watched)
        assert _HOOK in zw.snapshot(watched, baseline) and _HOOK not in zw.snapshot(watched)

    def test_a_declaration_older_than_the_run_keeps_tracked_files_on_both_sides(self, tree: Path) -> None:
        """DEF-4073 on the engine's side: a bare `*` already in tools/cc/hooks/
        over committed hooks is walked by the recorder's before-stats as by the
        hook's fresh baseline, so a writer's rewrite there is recorded, never
        read by the hook as a slip; an untracked declared directory prunes on
        both sides, from one tracked set. Mutation: take the before-stats with
        no tracked set."""
        _commit(tree)
        (tree / "tools" / "cc" / "hooks" / ".gitignore").write_bytes(b"*\n")
        types = tree / "tools" / "cc" / "mods" / "m" / ".claude-plugin" / "types"
        types.mkdir(parents=True)
        (types / ".gitignore").write_bytes(b"*\n")
        (types / "index.d.ts").write_bytes(b"export {};\n")
        for side in (ze._stats(tree), zw.snapshot(tree)):
            assert _HOOK in side and not [r for r in side if "/types/" in r], sorted(side)
        for tops in (["tools/cc/"], [":!tools/"]):  # the second a name, never git's exclusion
            assert ze._tracked_dirs(tree, tops) == zw.tracked_dirs(tree, tops), tops
        assert ze._tracked_dirs(tree, [":!tools/"]) == frozenset()
        assert zw.take_baseline(tree, "s-1")
        with ze.recorded(tree, "espalier upgrade"):
            _bump(tree / _HOOK, b"print('upgraded under an older declaration')\n")
        assert _HOOK in _record(tree, "espalier upgrade")["files"]

    def test_the_recorder_asks_once_reads_any_name_and_keeps_a_placeholder_generated(
            self, tree: Path, monkeypatch) -> None:
        """The engine's side of the review's rows: one `ls-files` for a run
        (the before-stats; the after-stats walk over them), a name in bytes
        that are not UTF-8 read without raising (the run's bracket must never
        raise), and a directory whose only tracked file is its own bare `*`
        pruned. Mutations: ask on the after-stats too; decode with
        os.fsdecode; count a directory's own .gitignore."""
        from espalier import _spawn

        _commit(tree)
        gen = tree / "tools" / "cc" / "gen"
        gen.mkdir()
        (gen / ".gitignore").write_bytes(b"*\n")
        _git(tree, "add", "-f", "tools/cc/gen/.gitignore")
        _git(tree, "commit", "-q", "-m", "placeholder")
        (gen / "out.json").write_bytes(b"{}\n")
        sha = _git(tree, "hash-object", "-w", "--stdin", stdin=b"x\n").strip()
        _git(tree, "update-index", "--index-info", stdin=b"100644 " + sha + b"\ttools/cc/odd/caf\xe9.py\n")
        (tree / "tools" / "cc" / "hooks" / ".gitignore").write_bytes(b"*\n")
        dirs = ze._tracked_dirs(tree, ["tools/cc/"])
        assert {"tools/cc/hooks", "tools/cc/odd"} <= dirs and "tools/cc/gen" not in dirs, sorted(dirs)
        assert not [r for r in ze._stats(tree) if r.startswith("tools/cc/gen/")]
        calls: list[list[str]] = []
        real = _spawn.run_no_stdin

        def counting(args, **kw):
            calls.append([str(a) for a in args])
            return real(args, **kw)

        monkeypatch.setattr(_spawn, "run_no_stdin", counting)
        assert zw.take_baseline(tree, "s-1")
        with ze.recorded(tree, "espalier upgrade"):
            _bump(tree / _HOOK, b"print('upgraded')\n")
        assert len([c for c in calls if "ls-files" in c]) == 1, calls
        assert _HOOK in _record(tree, "espalier upgrade")["files"]

    def test_a_large_file_has_the_same_identity_on_both_sides(self, tmp_path: Path) -> None:
        big = tmp_path / "weights.bin"
        with big.open("wb") as fh:
            fh.truncate(ze.BIG_FILE_BYTES)
        assert ze.content_digest(big) == zw.content_digest(big)
        assert ze.content_digest(big).startswith("stat:")

    def test_the_digest_is_the_hooks(self, tmp_path: Path) -> None:
        for i, raw in enumerate((b"a\nb\n", b"a\r\nb\r\n", b"\xef\xbb\xbfa\nb\n", b"\x00\xff binary")):
            path = tmp_path / f"f{i}"
            path.write_bytes(raw)
            assert ze.content_digest(path) == zw.content_digest(path)

    def test_the_engine_watches_everything_the_hook_watches_here(self) -> None:
        """The recorder must see every path the hook can report on this tree,
        or a harness write to it reads as unaccounted (the adopter's own
        protected_paths aside: no harness writer rewrites them)."""
        assert set(zw.snapshot(ROOT)) <= set(ze._stats(ROOT))

    @pytest.mark.parametrize("shape", ["directory", "gitlink file"])
    def test_both_walks_enter_a_nested_checkout_alike(self, tree: Path, shape: str) -> None:
        """Both walks enter a nested checkout under a protected path (its .git
        is pruned by name), so they see one set: a recorder that skipped it
        would leave a writer's change there unaccounted, and a hook that
        skipped it would ignore what the recorder recorded. Mutations: prune
        a nested checkout in the recorder's walk only; in the hook's only."""
        (tree / "espalier.toml").write_text('protected_paths = ["models/"]\n', encoding="utf-8")
        clone = tree / "models" / "clone"
        clone.mkdir(parents=True)
        if shape == "directory":
            (clone / ".git").mkdir()
            (clone / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
        else:
            (clone / ".git").write_bytes(b"gitdir: ../../.git/modules/clone\n")
        (clone / "weights.json").write_bytes(b"{}\n")
        (tree / "models" / "card.md").write_bytes(b"# card\n")
        engine = {rel for rel in ze._stats(tree) if rel.startswith("models/")}
        hook = {rel for rel in zw.snapshot(tree) if rel.startswith("models/")}
        expected = {"models/card.md", "models/clone/weights.json"}
        if shape == "gitlink file":
            expected.add("models/clone/.git")
        assert engine == hook == expected

    def test_the_script_writers_are_the_scripts_that_record(self) -> None:
        """Both ways: every script that brackets itself is a writer the hook
        reads, and every script writer the hook reads brackets itself."""
        recording = set()
        for script in sorted(checkout_glob(ROOT / "scripts", "*.py")):
            source = script.read_text(encoding="utf-8")
            if "zone_writes import recorded" in source:
                rel = script.relative_to(ROOT).as_posix()
                assert f'"{rel}"' in source, f"{rel} records under another name"
                recording.add(rel)
        assert recording == set(zw.SCRIPT_WRITERS)

    def test_every_watched_transforming_mirror_is_synced_by_a_recording_script(self) -> None:
        """Path 3 judges a mirror by equality; a row that transforms its source
        is accounted by its sync script's record instead."""
        from espalier import mirror_registry as reg
        transforming = {
            r.sync.split()[-1] for r in reg.MIRROR_ROWS
            if r.kind not in (reg.BYTE, reg.SUBSET)
            and zw.is_watched(ROOT, r.mirrors[0] + "probe.py" if r.mirrors[0].endswith("/") else r.mirrors[0])
        }
        # Both ways: a drained registry, or a script writer no watched row
        # names, reds as surely as a row whose sync script does not record.
        assert transforming == set(zw.SCRIPT_WRITERS)


class TestOnlyTheWritersAreBracketed:
    """A read-only command's run must not file a parallel slip as its own, so
    only the commands that rewrite protected files carry ``zone_writer``."""

    WRITERS = {
        ("init", "."), ("merge-settings", "."), ("upgrade", "."), ("clean-generated", "."),
        ("integrity", "refresh", "."), ("install-ci", "."), ("_refresh-self-host-pin", "."),
        ("freshness", "pin", "x"), ("freshness", "unpin", "x"),
    }

    @staticmethod
    def _parse(argv: tuple[str, ...]):
        from espalier.cli import build_parser
        return build_parser().parse_args(list(argv))

    def test_each_writer_is_marked(self) -> None:
        for argv in sorted(self.WRITERS):
            try:
                args = self._parse(argv)
            except SystemExit:
                pytest.fail(f"could not parse {argv}")
            assert getattr(args, "zone_writer", False), argv

    def test_a_read_only_command_is_not(self) -> None:
        for argv in (("audit", "."), ("doctor", "."), ("scan", "."), ("fingerprint", ".")):
            assert not getattr(self._parse(argv), "zone_writer", False), argv

    def test_main_brackets_a_writer_and_leaves_a_read_only_command_alone(
            self, tree: Path, monkeypatch) -> None:
        """Mutation: bracket every command that takes a repository."""
        import contextlib as _contextlib

        from espalier import cli

        bracketed: list[str] = []

        @_contextlib.contextmanager
        def spy(repo, writer):
            bracketed.append(writer)
            yield

        monkeypatch.setattr(ze, "recorded", spy)
        monkeypatch.chdir(tree)
        for argv in (["espalier", "recover", str(tree)], ["espalier", "integrity", "refresh", str(tree)]):
            monkeypatch.setattr(sys, "argv", argv)
            cli.main()
        assert bracketed == ["espalier integrity"]


def _run(tree: Path, argv: list[str], script: str | None = None, payload: dict | None = None):
    from tests._interpreter_hosts import HOOK_PYTHON

    env = {k: v for k, v in os.environ.items() if not k.startswith(("ESPALIER_", "CLAUDE_"))}
    env["CLAUDE_PROJECT_DIR"] = str(tree)
    env["ESPALIER_AUDIT_DIR"] = str(tree / ".audit")
    env["PYTHONPATH"] = str(ROOT)
    if script is not None:
        argv = [HOOK_PYTHON, str(HOOKS_DIR / script)]
    return subprocess.run(argv, input=json.dumps(payload) if payload is not None else None,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=50, env=env, cwd=str(tree))


def _shell_check(tree: Path) -> str:
    result = _run(tree, [], "post_write_check.py", {
        "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "espalier integrity refresh ."}, "session_id": "s-1", "cwd": str(tree)})
    assert result.returncode == 0, result.stderr
    obj = json.loads(result.stdout) if result.stdout.strip() else {}
    return obj.get("hookSpecificOutput", {}).get("additionalContext", "")


class TestPathFourEndToEnd:
    def _refresh(self, tree: Path) -> None:
        result = _run(tree, [sys.executable, "-m", "espalier", "integrity", "refresh", str(tree)])
        assert result.returncode == 0, result.stdout + result.stderr
        assert (tree / _MANIFEST).is_file()

    def test_a_harness_writers_rewrite_through_a_shell_call_is_silent(self, watched: Path) -> None:
        """Mutation: drop path 4. The writer's name comes from the CLI's own
        bracket, so this also pins it to the hook's ``espalier `` prefix."""
        self._refresh(watched)
        assert _record(watched, "espalier integrity")["writer"] == "espalier integrity"
        assert _shell_check(watched) == ""

    def test_a_slip_before_the_writer_in_the_same_call_still_reports(self, watched: Path) -> None:
        _bump(watched / _HOOK, b"print('the slip')\n")
        self._refresh(watched)
        text = _shell_check(watched)
        assert f"changed {_HOOK}" in text and _MANIFEST not in text

    def _forge(self, tree: Path, writer: str, written_ns: int, name: str | None = None) -> None:
        _bump(tree / _MANIFEST, b'{"forged": true}\n')
        directory = tree / ".espalier-state" / "zone_writes"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (name or ze.record_name(writer))).write_text(json.dumps(
            {"writer": writer, "files": {_MANIFEST: [zw.content_digest(tree / _MANIFEST), written_ns]}}),
            encoding="utf-8")

    def test_a_record_from_before_the_previous_check_accounts_for_nothing(self, watched: Path) -> None:
        """Mutation: drop the since-the-previous-check condition."""
        self._forge(watched, "espalier integrity", 1)
        assert f"added {_MANIFEST}" in _shell_check(watched)

    def test_a_writer_off_the_roster_accounts_for_nothing(self, watched: Path) -> None:
        """Mutation: read any writer's record."""
        self._forge(watched, "a session's own script", time.time_ns())
        assert f"added {_MANIFEST}" in _shell_check(watched)

    def test_a_record_filed_under_another_writers_name_accounts_for_nothing(self, watched: Path) -> None:
        """One file per writer, named by it. Mutation: drop the name check."""
        self._forge(watched, "espalier init", time.time_ns(), name=ze.record_name("espalier upgrade"))
        assert f"added {_MANIFEST}" in _shell_check(watched)
