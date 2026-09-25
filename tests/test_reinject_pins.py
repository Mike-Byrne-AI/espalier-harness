"""Fire/silent matrices for the event-keyed pointer rows in ``_reinject.py``,
plus the referent pins that keep each pointer honest.

These rows exist because, measured on 2026-09-06, the pull side of the recall
engine returned none of four applicable catalog entries for a lane's task text
while returning all four for the hazard's own words -- so the push side keys on
the EVENT that carries the hazard. Each test here guards one way a pointer could
drift into a lie: firing on an edit to a tracked file (noise), staying silent on
the new-file event it exists for, naming a test file, a constant or a catalog
heading that no longer exists, or firing twice in one session. The last class
also pins that ``post_write_check`` derives written paths from a Bash command,
because a heredoc edit carries no ``file_path`` and the whole registry was
silent for such edits before this landed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _reinject  # noqa: E402
from _hook_utils import STATE_DIR  # noqa: E402


def _fire(tool, tool_input, root):
    out = _reinject.check("PostToolUse", tool, tool_input, root)
    return "\n".join(out)


@pytest.fixture
def untracked(monkeypatch):
    monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: False)


@pytest.fixture
def tracked(monkeypatch):
    monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: True)


class TestNewTestFile:
    def test_fires_on_an_untracked_test_file(self, tmp_path, untracked):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_zzz_probe.py").write_text("x", encoding="utf-8")
        out = _fire("Write", {"file_path": "tests/test_zzz_probe.py", "content": "x"}, tmp_path)
        assert "_MARKER_RULES" in out and "_SLOW_FILES" in out
        assert "New Test Files Default to `unit` Silently" in out

    def test_silent_on_a_tracked_test_file(self, tmp_path, tracked):
        assert "_MARKER_RULES" not in _fire(
            "Edit", {"file_path": "tests/test_hooks.py", "new_string": "x"}, tmp_path)

    def test_silent_on_a_non_test_path_and_on_a_mirror(self, tmp_path, untracked):
        assert "_MARKER_RULES" not in _fire("Write", {"file_path": "tests/conftest.py", "content": "x"}, tmp_path)
        assert "_MARKER_RULES" not in _fire(
            "Write", {"file_path": "espalier/_vendor/selfcheck_tests/test_x.py", "content": "x"}, tmp_path)


class TestNewScript:
    def test_fires_on_an_untracked_script(self, tmp_path, untracked):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "zzz_probe.py").write_text("x", encoding="utf-8")
        out = _fire("Write", {"file_path": "scripts/zzz_probe.py", "content": "x"}, tmp_path)
        assert "EXPECTED_SCRIPT_COUNT" in out and "EXPECTED_SCRIPT_NAMES" in out
        assert "A Hand-Maintained Doc Enumeration" in out

    def test_silent_on_a_tracked_script(self, tmp_path, tracked):
        assert "EXPECTED_SCRIPT_COUNT" not in _fire(
            "Edit", {"file_path": "scripts/sync_vendor_cc.py", "new_string": "x"}, tmp_path)


class TestOperatorDocInterpreter:
    def test_an_absolute_path_outside_the_root_is_never_read(self, tmp_path):
        """A Bash-derived candidate can be absolute and elsewhere; `root / rel`
        would escape the root (code-review pass, driven on a /tmp README)."""
        outside = tmp_path / "elsewhere" / "README.md"
        outside.parent.mkdir()
        outside.write_text("python3 x\n", encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()
        assert _fire("Bash", {"file_path": str(outside), "command": "x"}, root) == ""

    def test_fires_on_python3_in_a_command_body(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "commit.md").write_text("x", encoding="utf-8")
        out = _fire("Edit", {"file_path": ".claude/commands/commit.md",
                             "new_string": "run python3 scripts/x.py"}, tmp_path)
        assert "test_operator_docs_no_unix_only_default_workflows" in out
        assert "Two operator-doc contracts can collide" in out

    def test_reads_the_file_when_the_edit_came_through_bash(self, tmp_path):
        doc = tmp_path / ".claude" / "commands" / "zzz.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("```bash\npython3 scripts/x.py\n```\n", encoding="utf-8")
        out = _fire("Bash", {"file_path": ".claude/commands/zzz.md", "command": "printf x >> .claude/commands/zzz.md"}, tmp_path)
        assert "test_operator_docs_no_unix_only_default_workflows" in out

    def test_silent_on_the_py_shape_and_on_a_non_operator_doc(self, tmp_path):
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "commit.md").write_text("x", encoding="utf-8")
        assert "portability" not in _fire(
            "Edit", {"file_path": ".claude/commands/commit.md",
                     "new_string": 'PY=python3; command -v "$PY" >/dev/null 2>&1 || PY=python'}, tmp_path)
        assert "portability" not in _fire(
            "Edit", {"file_path": "docs/HOOKS.md", "new_string": "python3 x"}, tmp_path)

class TestLedgerParser:
    def test_the_rules_own_module_is_exempt(self, tmp_path):
        """`_reinject.py` names both ledger files in its own source; a detector
        exempts its defining material (SHARP_EDGES: a new pattern-detector
        trips the harness's own defenses)."""
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "hooks" / "_reinject.py").write_text(
            'x = open("task-packs/FORWARD_LEDGER.md"); y = a.split("|")\n', encoding="utf-8")
        assert "UNESCAPED" not in _fire("Edit", {"file_path": "tools/cc/hooks/_reinject.py",
                                                  "new_string": "x"}, tmp_path)

    def test_fires_on_a_pipe_split_over_the_ledger(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "zzz.py").write_text("x", encoding="utf-8")
        out = _fire("Write", {"file_path": "scripts/zzz.py",
                              "content": 'text = open("task-packs/FORWARD_LEDGER.md").read()\ncells = line.split("|")\n'}, tmp_path)
        assert "UNESCAPED" in out and "generate_ledger_regions.py" in out
        assert "Markdown Escaped Pipes Silently Drop Matrix Rows" in out

    def test_silent_without_the_ledger_or_without_the_split(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "zzz.py").write_text("x", encoding="utf-8")
        assert "UNESCAPED" not in _fire("Write", {"file_path": "scripts/zzz.py", "content": 'x = "a|b".split("|")'}, tmp_path)
        assert "UNESCAPED" not in _fire("Write", {"file_path": "scripts/zzz.py", "content": 'open("task-packs/FORWARD_LEDGER.md")'}, tmp_path)


class TestOncePerSession:
    def test_a_pointer_fires_once_then_is_suppressed_and_logged(self, tmp_path, untracked):
        (tmp_path / "scripts").mkdir()
        for name in ("zzz_probe.py", "yyy_probe.py"):
            (tmp_path / "scripts" / name).write_text("x", encoding="utf-8")
        first = _fire("Write", {"file_path": "scripts/zzz_probe.py", "content": "x"}, tmp_path)
        second = _fire("Write", {"file_path": "scripts/yyy_probe.py", "content": "x"}, tmp_path)
        assert "EXPECTED_SCRIPT_COUNT" in first and "EXPECTED_SCRIPT_COUNT" not in second
        assert (tmp_path / STATE_DIR / "reinject_once_REINJECT-NEW-SCRIPT-INVENTORY").exists()

    def test_a_scratch_root_that_is_not_a_repo_stays_silent(self, tmp_path):
        """The sibling sync tests drive rules from a tmp_path that is not a git
        repo; git answering 'not a repository' is a non-answer and must read
        as tracked (silent), never as a new file. Driven: the first cut fired
        on every sibling fixture."""
        assert _reinject._is_tracked(tmp_path, "scripts/x.py") is True

    def test_pointers_are_cap_exempt_so_their_scarcity_is_the_flag(self, tmp_path, untracked):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "zzz.py").write_text("x", encoding="utf-8")
        for _ in range(_reinject.REINJECT_SESSION_CAP + 2):
            _reinject._locked_increment(tmp_path / STATE_DIR, _reinject.REINJECT_COUNTER)
        assert "EXPECTED_SCRIPT_COUNT" in _fire("Write", {"file_path": "scripts/zzz.py", "content": "x"}, tmp_path)

    def test_session_start_clears_the_flags_on_startup_and_keeps_them_on_a_continuation(self, tmp_path):
        import importlib
        ss = importlib.import_module("session_start")
        flag = tmp_path / STATE_DIR / "reinject_once_PROBE"
        flag.parent.mkdir(parents=True)
        flag.write_text("1", encoding="utf-8")
        ss._clean_state_flags(tmp_path, source="compact")
        assert flag.exists(), "a compaction must not re-arm a spent pointer"
        ss._clean_state_flags(tmp_path, source="startup")
        assert not flag.exists()

    def test_a_session_capped_once_row_is_not_spent(self, tmp_path):
        """Marking happens after the emit decision: a non-exempt once row that
        loses to the session cap keeps its flag and fires when the cap frees
        (failure-mode pass, driven: the first cut marked it, then dropped it)."""
        probe = _reinject.ReinjectRule(
            id="PROBE-ONCE-NONEXEMPT", event="PostToolUse",
            render=lambda *a: "probe text", face="sync", once_per_session=True,
        )
        for _ in range(_reinject.REINJECT_SESSION_CAP + 1):
            _reinject._locked_increment(tmp_path / STATE_DIR, _reinject.REINJECT_COUNTER)
        assert _reinject.check("PostToolUse", "Write", {}, tmp_path, rules=(probe,)) == []
        assert not (tmp_path / STATE_DIR / "reinject_once_PROBE-ONCE-NONEXEMPT").exists()

    def test_a_budget_below_the_matches_marks_only_what_it_emits(self, tmp_path):
        a = _reinject.ReinjectRule(id="PROBE-A", event="PostToolUse", render=lambda *x: "a",
                                   face="sync", cap_exempt=True, priority=90, once_per_session=True)
        b = _reinject.ReinjectRule(id="PROBE-B", event="PostToolUse", render=lambda *x: "b",
                                   face="sync", cap_exempt=True, priority=80, once_per_session=True)
        assert _reinject.check("PostToolUse", "Write", {}, tmp_path, rules=(a, b), budget=1) == ["a"]
        assert (tmp_path / STATE_DIR / "reinject_once_PROBE-A").exists()
        assert not (tmp_path / STATE_DIR / "reinject_once_PROBE-B").exists()


class TestBashDerivedPaths:
    """post_write_check asks the registry per path a Bash or PowerShell command
    actually wrote, as the write it was."""

    @pytest.fixture
    def pwc(self):
        import importlib
        return importlib.import_module("post_write_check")

    def test_a_heredoc_creating_a_test_file_reaches_the_new_test_row(self, pwc, monkeypatch, tmp_path):
        monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: False)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_zzz_probe.py").write_text("x", encoding="utf-8")
        out = pwc._bash_derived_payloads(
            {"command": "cat > tests/test_zzz_probe.py <<'EOF'\nx\nEOF"}, tmp_path, already=0)
        assert any("_MARKER_RULES" in t for t in out)

    def test_a_path_that_was_only_mentioned_fires_nothing_and_spends_nothing(self, pwc, monkeypatch, tmp_path):
        """The extractor over-yields on purpose (a literal inside a `python -c`
        body); a path that is not on disk after the call was not written."""
        monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: False)
        cmd = 'python3 -c "print(\'cat > scripts/a.py <<EOF\'); open(\'tests/test_b.py\')"'
        assert pwc._bash_derived_payloads({"command": cmd}, tmp_path, already=0) == []
        assert not list((tmp_path / STATE_DIR).glob("reinject_once_*")) if (tmp_path / STATE_DIR).is_dir() else True

    def test_a_written_path_reaches_the_sync_rows_as_the_write_it_was(self, pwc, monkeypatch, tmp_path):
        """The fourteen sync renders gate on the Write/Edit tool names; a
        heredoc into a hook must reach the vendor-sync row (the one guarding
        'self-host's single most-missed step'), which the first cut's bare
        `Bash` name never did (failure-mode pass, driven)."""
        monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: True)
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "hooks" / "x.py").write_text("x", encoding="utf-8")
        out = pwc._bash_derived_payloads(
            {"command": "cat > tools/cc/hooks/x.py <<'EOF'\nx\nEOF"}, tmp_path, already=0)
        assert any("sync_vendor_cc" in t for t in out), out

    def test_the_powershell_twin_derives_paths_too(self, pwc, monkeypatch, tmp_path):
        monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: False)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_ps_probe.py").write_text("x", encoding="utf-8")
        out = pwc._bash_derived_payloads(
            {"command": "Set-Content -Path tests/test_ps_probe.py -Value 'x'"}, tmp_path,
            already=0, tool_name="PowerShell")
        assert any("_MARKER_RULES" in t for t in out), out

    def test_respects_the_per_turn_ceiling_and_dedupes(self, pwc, monkeypatch, tmp_path):
        monkeypatch.setattr(_reinject, "_is_tracked", lambda root, rel: False)
        for rel in ("scripts/a.py", "scripts/b.py", "tests/test_c.py"):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x", encoding="utf-8")
        cmd = "cat > scripts/a.py <<'EOF'\nx\nEOF\ncat > scripts/b.py <<'EOF'\nx\nEOF\ncat > tests/test_c.py <<'EOF'\nx\nEOF"
        out = pwc._bash_derived_payloads({"command": cmd}, tmp_path, already=0)
        assert 1 <= len(out) <= _reinject.REINJECT_PER_TURN_CAP
        assert pwc._bash_derived_payloads({"command": cmd}, tmp_path, already=_reinject.REINJECT_PER_TURN_CAP) == []

    @pytest.fixture
    def live_once_flags_restored(self):
        """The end-to-end drive runs the real hook against THIS repo, whose state
        dir is the operator's. Snapshot the once flags, clear the one the drive
        will spend, and put everything back -- the first cut left the operator's
        new-test-file pointer spent for the session and was red on any second
        run (failure-mode pass, driven)."""
        d = REPO / STATE_DIR
        before = {p.name for p in d.glob("reinject_once_*")} if d.is_dir() else set()
        for p in d.glob("reinject_once_*") if d.is_dir() else ():
            p.unlink()
        yield
        if d.is_dir():
            for p in d.glob("reinject_once_*"):
                p.unlink()
            for name in before:
                (d / name).write_text("1", encoding="utf-8")

    def test_the_end_to_end_hook_emits_for_a_bash_write(self, live_once_flags_restored, tmp_path):
        """Drive the real hook: a Bash tool call whose command wrote a test file
        under this repo. The file is created in a scratch name and removed after,
        because the bridge fires only for a path that exists."""
        from tests.test_hooks import run_hook
        probe = REPO / "tests" / "test_zz_probe_only_pins_drive.py"
        probe.write_text("# scratch, removed by the test\n", encoding="utf-8")
        try:
            res = run_hook("post_write_check.py", {
                "tool_name": "Bash",
                "tool_input": {"command": f"cat > tests/{probe.name} <<'EOF'\nx\nEOF"},
            })
        finally:
            probe.unlink(missing_ok=True)
        assert res.returncode == 0
        payload = json.loads(res.stdout) if res.stdout.strip() else {}
        ctx = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "_MARKER_RULES" in ctx, res.stdout[:300] + res.stderr[:300]
