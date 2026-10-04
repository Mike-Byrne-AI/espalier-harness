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

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _reinject  # noqa: E402
from tests._interpreter_hosts import shell_resolver_line  # noqa: E402
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
                     "new_string": shell_resolver_line()}, tmp_path)
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


class TestGuardPatternClassify:
    """A module-level compiled pattern added to a guard module must be anchored
    at a command position or declared. The contract that says so
    (`tests/test_speedbump_irreversible.py::TestCommandPositionClassClose`) runs
    only in the full tier's serial leg, so on 2026-10-03 a lane's targeted
    proofs and both its reviews passed two such patterns and the full tier was
    the first net to catch them. This row names the contract at the edit."""

    _CONTRACT = REPO / "tests" / "test_speedbump_irreversible.py"

    @staticmethod
    def _root(tmp_path, *names):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        for name in names:
            (hooks / name).write_text("x", encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize("module", ["write_guard.py", "_bash_patterns.py", "_speedbump.py"])
    def test_fires_on_a_module_level_compile_in_a_walked_module(self, tmp_path, module):
        root = self._root(tmp_path, module)
        out = _fire("Edit", {"file_path": f"tools/cc/hooks/{module}",
                             "new_string": '_NEW_RE = re.compile(r"x")\n'}, root)
        assert "test_every_pattern_is_anchored_or_classified" in out
        assert "_UNANCHORED_BY_DESIGN" in out and "_CMD_POS" in out

    def test_an_annotated_binding_fires_too(self, tmp_path):
        root = self._root(tmp_path, "write_guard.py")
        out = _fire("Write", {"file_path": "tools/cc/hooks/write_guard.py",
                              "content": 'import re\n_X: "re.Pattern[str]" = re.compile("x")\n'}, root)
        assert "_UNANCHORED_BY_DESIGN" in out

    def test_silent_on_an_indented_compile_and_off_the_walked_modules(self, tmp_path):
        root = self._root(tmp_path, "write_guard.py", "_reinject.py")
        assert "_UNANCHORED_BY_DESIGN" not in _fire(
            "Edit", {"file_path": "tools/cc/hooks/write_guard.py",
                     "new_string": 'def f():\n    rx = re.compile("x")\n'}, root)
        assert "_UNANCHORED_BY_DESIGN" not in _fire(
            "Edit", {"file_path": "tools/cc/hooks/_reinject.py",
                     "new_string": '_X_RE = re.compile("x")\n'}, root)
        mirror = tmp_path / "espalier" / "_vendor" / "cc" / "hooks"
        mirror.mkdir(parents=True)
        (mirror / "write_guard.py").write_text("x", encoding="utf-8")
        assert "_UNANCHORED_BY_DESIGN" not in _fire(
            "Edit", {"file_path": "espalier/_vendor/cc/hooks/write_guard.py",
                     "new_string": '_X_RE = re.compile("x")\n'}, root)

    def test_a_carried_or_anchored_binding_neither_fires_nor_spends_the_flag(self, tmp_path):
        """The once flag is for a pattern the contract will judge. An Edit whose
        context carries an existing binding unchanged, and a new binding that
        already composes the anchor, must leave it unspent: the failure-mode
        review drove a tweak spending it and the next new pattern drawing nothing."""
        root = self._root(tmp_path, "_speedbump.py")
        fp = "tools/cc/hooks/_speedbump.py"
        carried = '_RM_RE = re.compile(r"rm")\n'
        assert "_UNANCHORED_BY_DESIGN" not in _fire(
            "Edit", {"file_path": fp, "old_string": carried, "new_string": carried + "# note\n"}, root)
        assert "_UNANCHORED_BY_DESIGN" not in _fire(
            "Edit", {"file_path": fp, "new_string": '_A_RE = re.compile(\n    _CMD_POS + r"x")\n'}, root)
        out = _fire("Edit", {"file_path": fp, "new_string": '_BRAND_NEW_RE = re.compile(r"y")\n'}, root)
        assert "_UNANCHORED_BY_DESIGN" in out and "`_BRAND_NEW_RE`" in out

    def test_a_changed_binding_that_drops_its_anchor_fires(self, tmp_path):
        root = self._root(tmp_path, "write_guard.py")
        out = _fire("Edit", {"file_path": "tools/cc/hooks/write_guard.py",
                             "old_string": '_X_RE = re.compile(_CMD_POS + r"a")\n',
                             "new_string": '_X_RE = re.compile(r"a")\n'}, root)
        assert "`_X_RE`" in out

    def test_every_pattern_the_contract_walks_has_a_binding_the_row_sees(self):
        """The row approximates the contract's population with a source regex.
        Pinned to the population itself, so a binding form the regex misses (an
        aliased `re`, a parenthesised call, a pattern imported from a module the
        row does not watch) reds here instead of leaving the row silent."""
        from tests.test_speedbump_irreversible import TestCommandPositionClassClose
        found = TestCommandPositionClassClose._all_module_patterns()
        assert len(found) >= 55, "the contract's population collapsed; this pin would pass vacuously"
        seen = {
            mod: {m.group("name") for m in _reinject._MODULE_LEVEL_COMPILE_RE.finditer(
                (HOOKS_DIR / f"{mod}.py").read_text(encoding="utf-8"))}
            for mod in _reinject._GUARD_PATTERN_MODULES
        }
        missed = sorted(k for k in found if k.split(".", 1)[1] not in seen[k.split(".", 1)[0]])
        assert missed == [], missed

    def test_the_module_roster_is_the_contracts_own(self):
        """Read from the contract's source, never restated here: the tuple of
        modules `_all_module_patterns` walks is the population the row names."""
        tree = ast.parse(self._CONTRACT.read_text(encoding="utf-8"))
        walk = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_all_module_patterns")
        loops = [n for n in ast.walk(walk) if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)]
        assert len(loops) == 1, "the contract's module walk changed shape: re-derive this pin"
        walked = {e.id for e in loops[0].iter.elts if isinstance(e, ast.Name)}
        assert walked == set(_reinject._GUARD_PATTERN_MODULES)
        # the path pattern is a literal (test_redos proves only those): it must
        # match exactly the roster's modules
        rx = _reinject._GUARD_PATTERN_MODULE_RE
        assert all(rx.search(f"tools/cc/hooks/{m}.py") for m in walked)
        assert not any(rx.search(f"tools/cc/hooks/{m}.py")
                       for m in ("_reinject", "_hook_utils", "write_guard_x", "x_speedbump"))

    def test_the_referents_the_row_names_exist(self):
        tree = ast.parse(self._CONTRACT.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "TestCommandPositionClassClose")
        members = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        members |= {t.id for n in cls.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        members |= {n.target.id for n in cls.body
                    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        assert {"test_every_pattern_is_anchored_or_classified", "_UNANCHORED_BY_DESIGN"} <= members
        import _bash_patterns
        assert hasattr(_bash_patterns, "_CMD_POS") and hasattr(_bash_patterns, "_PS_CMD_POS")
        # "only in the full tier's serial leg": the file is a serial-leg file
        spec = importlib.util.spec_from_file_location("_proof_tier_pin", REPO / "scripts" / "proof_tier.py")
        assert spec is not None and spec.loader is not None
        proof_tier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proof_tier)
        assert "tests/test_speedbump_irreversible.py" in proof_tier.SERIAL_FILES


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

    @staticmethod
    def _scratch_self_host(tmp_path):
        """A git tree the hook reads as the self-host repo (the five signals of
        `_hook_utils.is_self_host_repo`), so the drive writes nothing into this
        checkout. It used to write its probe into the live `tests/` and spend the
        operator's once flags; the probe raced every scanner of that directory
        under xdist (three `test (3.x)` cells of PR #81, 2026-10-03, three
        different scanners hitting FileNotFoundError on the vanished file)."""
        import shutil
        import subprocess
        for d in ("espalier", "tools/cc/hooks", "bench", "tests"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "espalier-harness"\n', encoding="utf-8")
        shutil.copy2(HOOKS_DIR / "write_guard.py", tmp_path / "tools" / "cc" / "hooks" / "write_guard.py")
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        return tmp_path

    def test_the_end_to_end_hook_emits_for_a_bash_write(self, tmp_path):
        """Drive the real hook: a Bash tool call whose command wrote a new test
        file, in a scratch self-host tree, because the bridge fires only for a
        path that exists."""
        from _hook_utils import is_self_host_repo
        from tests.test_hooks import run_hook
        root = self._scratch_self_host(tmp_path)
        assert is_self_host_repo(root), "the scratch tree must read as self-host, or the drive is vacuous"
        probe = root / "tests" / "test_zz_probe_only_pins_drive.py"
        probe.write_text("# scratch\n", encoding="utf-8")
        res = run_hook("post_write_check.py", {
            "tool_name": "Bash",
            "tool_input": {"command": f"cat > tests/{probe.name} <<'EOF'\nx\nEOF"},
        }, env_overrides={"CLAUDE_PROJECT_DIR": str(root)})
        assert res.returncode == 0
        payload = json.loads(res.stdout) if res.stdout.strip() else {}
        ctx = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "_MARKER_RULES" in ctx, res.stdout[:300] + res.stderr[:300]


class TestAMentionOfATrackedUnchangedFileSpendsNothing:
    """The hand-off filtered a Bash-derived path on existence alone, so a
    read-only chain naming a tracked file it never touched drew the sync
    advisory for an edit that did not happen. A tracked path now needs git's
    word that it changed; an untracked one is a new file and still counts."""

    @pytest.fixture
    def pwc(self):
        import importlib
        return importlib.import_module("post_write_check")

    @staticmethod
    def _repo_with_a_tracked_hook(tmp_path):
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        hook = tmp_path / "tools" / "cc" / "hooks" / "x.py"
        hook.parent.mkdir(parents=True)
        hook.write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
        return hook

    # The hand-off reads the command TEXT and the disk; it never runs the
    # command. A write-shaped spelling is what the extractor yields on, and
    # the file's state after the call is what decides -- the sed chain of
    # DEF-966 was exactly this: an extraction naming a tracked file that the
    # call left byte-identical.
    _WRITE_SHAPED = "cat > tools/cc/hooks/x.py <<'EOF'\nx = 1\nEOF"

    def test_an_extraction_naming_a_clean_tracked_file_fires_nothing(self, pwc, tmp_path):
        self._repo_with_a_tracked_hook(tmp_path)
        assert pwc._bash_derived_payloads({"command": self._WRITE_SHAPED}, tmp_path, already=0) == []

    def test_the_same_extraction_after_a_real_change_still_reaches_the_sync_row(self, pwc, tmp_path):
        hook = self._repo_with_a_tracked_hook(tmp_path)
        hook.write_text("x = 2\n", encoding="utf-8")
        out = pwc._bash_derived_payloads({"command": self._WRITE_SHAPED}, tmp_path, already=0)
        assert any("sync_vendor_cc" in t for t in out), out
