"""TP-40: SubagentStop hook contract.

The hook appends subagent reasoning to the active blueprint chain.
It NEVER blocks the subagent (blocking would deadlock the parent
session waiting for agent completion). Contract:

- Exit 0 with no stdout JSON on normal completion (allow path).
- Exit 0 on malformed input (fail-open via the JSON parse except).
- ``stop_hook_active`` payload flag prevents recursive subagent loops.
- Maintenance mode short-circuits the blueprint append.

This hook fills a real coverage gap discovered by the TP-39 multi-agent
audit: the five specialist agents that ran (architecture-analyst,
code-reviewer, etc.) bypassed ``stop_gate.py`` entirely. Their
reasoning landed in the parent session's tool-result stream but no
gate finalized it into the blueprint chain.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_hook_module(name: str):
    """Load ``tools/cc/hooks/<name>.py`` in-process with its sibling imports
    resolvable -- via ``spec_from_file_location``, never a plain import, so
    espalier is never dragged into the hooks' zero-import graph. The loader
    shape is what the derived-population census binds a module alias to."""
    import importlib.util
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run_hook(payload: dict | bytes, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    if env_overrides:
        env.update(env_overrides)
    if isinstance(payload, dict):
        stdin = json.dumps(payload).encode("utf-8")
    else:
        stdin = payload
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "subagent_stop.py")],
        input=stdin,
        capture_output=True,
        timeout=15,
        env=env,
    )


class TestSubagentStopExitCode:
    def test_exits_zero_on_normal_payload(self, tmp_path):
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0, (
            f"subagent_stop must exit 0 on normal payload; got "
            f"rc={result.returncode} stderr={result.stderr!r}"
        )

    def test_exits_zero_on_empty_stdin(self, tmp_path):
        result = _run_hook(
            b"",
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_exits_zero_on_malformed_json(self, tmp_path):
        result = _run_hook(
            b"{this is not json",
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_exits_zero_on_invalid_utf8(self, tmp_path):
        """TP-39 hardening propagates here — ValueError catches UnicodeDecodeError."""
        result = _run_hook(
            b"\xff\xff\xff",
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode != 1, (
            f"subagent_stop crashed on invalid UTF-8 stdin; "
            f"stderr={result.stderr.decode('utf-8', errors='replace')!r}"
        )


class TestSubagentStopNeverBlocks:
    """SubagentStop blocking would deadlock the parent session waiting
    for agent completion. This hook must NEVER emit a `decision: "block"`
    JSON output regardless of payload shape.
    """

    @pytest.mark.parametrize("payload", [
        {"agent_type": "code-reviewer"},
        {"agent_type": "unknown"},
        {},
        {"agent_type": "code-reviewer", "stop_hook_active": True},
        {"agent_type": "x" * 1000},  # over-long agent_type
    ])
    def test_does_not_emit_block_decision(self, tmp_path, payload):
        result = _run_hook(payload, {"CLAUDE_PROJECT_DIR": str(tmp_path)})
        assert result.returncode == 0
        if result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                assert data.get("decision") != "block", (
                    f"subagent_stop must NEVER block the subagent; "
                    f"got {data!r}"
                )
            except json.JSONDecodeError:
                pytest.fail(
                    f"stdout present but not JSON: {result.stdout!r}"
                )


def _stub_record_cli(root: Path) -> Path:
    """Stage a ``tools/cc/cognitive_blueprint.py`` that drops a marker when run.

    TP-324: both short-circuit tests below assert on the ABSENCE of the
    blueprint append. ``_append_subagent_reasoning`` returns early when the
    script is missing, so an un-stubbed tmp_path makes "no append happened"
    true for the wrong reason and the assert vacuous. Staging a stub that WOULD
    fire makes the marker's absence attributable to the short-circuit alone.
    Returns the marker path (not yet created).
    """
    (root / "tools" / "cc").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "cc" / "cognitive_blueprint.py").write_text(
        "import pathlib, os\n"
        "pathlib.Path(os.environ['CLAUDE_PROJECT_DIR'],"
        " 'record_cli_ran.marker').write_text('fired')\n",
        encoding="utf-8",
    )
    return root / "record_cli_ran.marker"


class TestSubagentStopRecursionGuard:
    """``stop_hook_active=True`` indicates the parent is already in a
    stop-hook chain; the subagent_stop hook must short-circuit to avoid
    recursive blueprint appends.
    """

    def test_stub_record_cli_fires_without_a_short_circuit(self, tmp_path):
        """Control for the two short-circuit tests: with neither guard active
        the stub IS invoked. Without this, a stub that silently never runs
        (wrong path, bad argv) would make both absence-asserts vacuously green
        -- the exact failure class TP-324 exists to close."""
        marker = _stub_record_cli(tmp_path)
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert marker.exists(), (
            "the staged record-CLI stub must be reachable on the normal path, "
            f"else the absence-asserts prove nothing; stderr={result.stderr!r}"
        )

    def test_stop_hook_active_short_circuits(self, tmp_path):
        """TP-324: pre-fix this asserted only exit 0 + no block -- neither
        depends on the guard, so deleting ``if data.get("stop_hook_active"):
        return 0`` let the append path run with the test still green.

        Carries its OWN inline reachability control (not just the sibling
        ``test_stub_record_cli_fires_without_a_short_circuit``): under
        ``pytest -k test_stop_hook_active_short_circuits`` the sibling-class
        control never runs, which would leave the absence-assert below vacuously
        green if the stub were unreachable -- the exact honesty gap TP-324 closes
        for its twin ``test_maintenance_mode_short_circuits`` and now here too.
        """
        marker = _stub_record_cli(tmp_path)
        assert not marker.exists(), "fixture invariant: marker must start absent"

        # Control: with the guard OFF (stop_hook_active False) this same payload
        # DOES reach the record CLI -- proving the stub is reachable, so the
        # absence below is attributable to the guard, not an unreachable stub.
        control = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert control.returncode == 0
        assert marker.exists(), (
            "reachability control: without the recursion guard the record CLI must "
            f"run, else the absence-assert below proves nothing; stderr={control.stderr!r}"
        )
        marker.unlink()

        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": True},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # No stderr expected when the recursion guard fires (silent path).
        # We do not assert empty stderr because subprocess timing can
        # produce noise; we DO assert exit 0 + no JSON.
        assert not result.stdout.strip() or json.loads(result.stdout).get(
            "decision"
        ) != "block"
        # THE named effect: the recursion guard returned BEFORE the append,
        # so the record CLI was never invoked.
        assert not marker.exists(), (
            "stop_hook_active=True must short-circuit before the blueprint "
            "append; the record CLI ran anyway (recursive-append risk)."
        )


class TestSubagentStopMaintenanceMode:
    def test_maintenance_mode_short_circuits(self, tmp_path):
        """TP-324: pre-fix this asserted only exit 0 + no block, so deleting
        the ``_maintenance_mode.is_active(...)`` early-return let the append
        run in maintenance mode with the test still green.

        Carries its OWN reachability control rather than leaning on the one in
        TestSubagentStopRecursionGuard: tests/CLAUDE.md recommends a tight loop
        on the target test, and under `pytest -k test_maintenance_mode_short_
        circuits` a sibling-class control never runs -- leaving the absence-
        assert below vacuously green if the stub were unreachable. That is
        exactly the honesty gap TP-324 exists to close, so the control is
        scoped to the assert it protects.
        """
        marker = _stub_record_cli(tmp_path)
        assert not marker.exists(), "fixture invariant: marker must start absent"

        # Control: with the bypass OFF, this same payload DOES reach the
        # record CLI. (_run_hook pops ESPALIER_MAINTENANCE_MODE by default.)
        control = _run_hook(
            {"agent_type": "code-reviewer"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert control.returncode == 0
        assert marker.exists(), (
            "reachability control: without the bypass the record CLI must run, "
            f"else the absence-assert below proves nothing; stderr={control.stderr!r}"
        )
        marker.unlink()

        result = _run_hook(
            {"agent_type": "code-reviewer"},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_MAINTENANCE_MODE": "1",
            },
        )
        assert result.returncode == 0
        # Maintenance bypass logs a stderr line; just confirm no block.
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert data.get("decision") != "block"
        # THE named effect: the bypass fired (observable stderr line) and the
        # blueprint append was skipped.
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        assert "[subagent_stop] MAINTENANCE_MODE" in stderr_text, (
            f"maintenance bypass must be observable on stderr; got {stderr_text!r}"
        )
        assert not marker.exists(), (
            "MAINTENANCE_MODE must skip the blueprint append; the record CLI "
            "ran anyway."
        )


class TestSubagentStopRecordFailureVisibility:
    """M6 (TP-48): a non-zero non-2 exit from the cognitive_blueprint
    record CLI means the subagent's reasoning was lost — file lock
    contention, OOM, mid-rename JSON corruption. Pre-fix the hook
    swallowed the failure silently and the operator had no signal that
    the chain was diverging. Post-fix a ``[WARN]`` line lands on stderr.
    """

    def test_record_failure_emits_warn_to_stderr(self, tmp_path):
        """Stub a fake repo where the cognitive_blueprint.py at
        ``tools/cc/cognitive_blueprint.py`` exits 1 + stderr; the hook
        must surface that as a ``[WARN]`` stderr line."""
        repo = tmp_path / "repo"
        (repo / "tools" / "cc").mkdir(parents=True)
        # Stub cognitive_blueprint.py — exits 1 with a recognizable message.
        stub = repo / "tools" / "cc" / "cognitive_blueprint.py"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stderr.write('STUB: simulated blueprint write failure\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0, (
            f"subagent_stop must still exit 0 on record failure; "
            f"got rc={result.returncode} stderr={result.stderr!r}"
        )
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        assert "[WARN] subagent_stop" in stderr_text, (
            f"expected [WARN] subagent_stop line on stderr; got: {stderr_text!r}"
        )
        assert "exited 1" in stderr_text
        assert "STUB: simulated blueprint write failure" in stderr_text

    def test_record_returncode_two_is_silent(self, tmp_path):
        """returncode==2 means "no active session" — the documented
        opportunistic path. Must remain silent (no [WARN])."""
        repo = tmp_path / "repo"
        (repo / "tools" / "cc").mkdir(parents=True)
        stub = repo / "tools" / "cc" / "cognitive_blueprint.py"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stderr.write('No active session.\\n')\n"
            "sys.exit(2)\n",
            encoding="utf-8",
        )
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        assert "[WARN] subagent_stop" not in stderr_text, (
            f"rc=2 path must remain silent; got: {stderr_text!r}"
        )


class TestDocsMaintainerReliefFlag:
    """When SubagentStop fires with agent_type='docs-maintainer',
    the .espalier-state/docs_refreshed flag is created so stop_gate's
    Gate 2 passes on subsequent Stop events.

    Pre-fix bug: stop_gate.py:171 read the docs_refreshed flag but
    no production code ever wrote it. Gate 2 looped indefinitely once
    write_count crossed 10 (the gate's threshold). The relief signal
    landed via subagent_stop because it's the only hook that observes
    the agent_type in real time.
    """

    def test_docs_maintainer_creates_relief_flag(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _run_hook(
            {"agent_type": "docs-maintainer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        flag = repo / ".espalier-state" / "docs_refreshed"
        assert flag.exists(), (
            f"docs-maintainer should create {flag} so stop_gate Gate 2 "
            f"passes on the next Stop; stderr={result.stderr!r}"
        )

    def test_code_reviewer_does_not_create_the_docs_flag(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        flag = repo / ".espalier-state" / "docs_refreshed"
        assert not flag.exists(), (
            "Only docs-maintainer should set docs_refreshed; code-reviewer "
            "writes its own record (code_reviewed -- TestCodeReviewerReliefFlag)."
        )
        assert (repo / ".espalier-state" / "code_reviewed").exists()

    def test_unknown_agent_does_not_create_flag(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _run_hook(
            {"agent_type": "future-not-yet-mapped-agent", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        flag = repo / ".espalier-state" / "docs_refreshed"
        assert not flag.exists()

    def test_relief_flag_write_failure_warns_but_does_not_block(self, tmp_path):
        """If the flag write fails (read-only FS, permissions), the hook
        must still exit 0 — subagent_stop NEVER blocks. Failure surfaces
        on stderr as a [WARN]."""
        repo = tmp_path / "repo"
        repo.mkdir()
        # Pre-create .espalier-state as a FILE (not a directory) so the
        # mkdir(parents=True, exist_ok=True) call raises FileExistsError
        # (subclass of OSError).
        state_path = repo / ".espalier-state"
        state_path.write_text("blocking placeholder", encoding="utf-8")
        result = _run_hook(
            {"agent_type": "docs-maintainer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0, (
            "Hook must exit 0 even when flag write fails — never block "
            "the subagent stop."
        )
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        assert "[WARN] subagent_stop" in stderr_text
        # The flag-name + "relief flag" both appear in the warning;
        # assert the flag name verbatim (the prior disjunct was dead).
        assert "docs_refreshed" in stderr_text

    def test_relief_map_is_the_shared_table(self):
        """DEF-608: the reader (stop_gate), the writer (this hook) and the
        sweeper (session_start) all read ONE table in _hook_utils. This used
        to be a local copy guarded by a module assert that forbade a
        code-reviewer entry -- because stop_gate wrote that gate's flag
        itself. It no longer writes anything; the table is the contract."""
        mod = _load_hook_module("subagent_stop")
        hook_utils = mod._hook_utils
        assert mod._AGENT_RELIEF_FLAGS is hook_utils.RELIEF_FLAGS, (
            "subagent_stop keeps its own relief map; it must alias "
            "_hook_utils.RELIEF_FLAGS so the reader cannot drift from the writer."
        )
        assert "docs-maintainer" in hook_utils.RELIEF_FLAGS
        assert "code-reviewer" in hook_utils.RELIEF_FLAGS

    def test_relief_table_keys_are_roster_agents(self):
        """SubagentStop reports the agent's frontmatter `name:`; a key the
        roster does not carry is a gate no run can relieve (failure-mode
        review, 2026-09-07: rename an agent and Gate 3 blocks every turn while
        the remedy says it was driven)."""
        import re as _re
        names = set()
        for path in sorted((REPO_ROOT / ".claude" / "agents").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            block = text[3:text.find("\n---", 3)] if text.startswith("---") else ""
            m = _re.search(r"^name:\s*(\S+)\s*$", block, _re.M)
            if m:
                names.add(m.group(1))
        assert names, "no agent frontmatter names under .claude/agents"
        mod = _load_hook_module("subagent_stop")
        assert set(mod._hook_utils.RELIEF_FLAGS) <= names, (
            set(mod._hook_utils.RELIEF_FLAGS) - names
        )

    def test_stop_gate_hygiene_gates_only_read(self):
        """The invariant that replaced 'never map code-reviewer here': no
        stop_gate gate writes its own relief. Read off the AST of the gate
        functions and their record readers, so a comment cannot satisfy it and
        a write cannot hide behind one. Earn-the-red: HEAD before DEF-608 had
        `write_text` inside `_gate_code_review`."""
        import ast
        tree = ast.parse((HOOKS_DIR / "stop_gate.py").read_text(encoding="utf-8"))
        wanted = {
            "_gate_docs_refresh", "_gate_code_review", "_relief_record",
            "_docs_refresh_evidence", "_code_review_evidence", "_recorded_by_hand",
        }
        found = {
            n.name: n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in wanted
        }
        assert wanted <= set(found), f"stop_gate is missing {sorted(wanted - set(found))}"
        writers = {"write_text", "write_bytes", "mkdir", "touch", "replace", "rename", "unlink"}
        for name, fn in found.items():
            attr_calls = {
                n.func.attr for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            assert not (attr_calls & writers), (
                f"{name} writes to the state dir ({sorted(attr_calls & writers)}); "
                "the hygiene gates only read -- subagent_stop is the writer."
            )
            opens = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"
            ]
            assert not opens, f"{name} calls open(); the gates only read via read_text"


class TestCodeReviewerReliefFlag:
    """DEF-608: when SubagentStop fires with agent_type='code-reviewer', the
    code_reviewed record is written with the run's evidence and stop_gate Gate 3
    reads it. Before this, Gate 3 wrote `review_requested` itself on its first
    block and passed every later Stop of the session with no review run.
    """

    def _record(self, tmp_path, payload: dict) -> dict:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False, **payload},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0, result.stderr
        return json.loads(
            (repo / ".espalier-state" / "code_reviewed").read_text(encoding="utf-8")
        )

    def test_code_reviewer_creates_code_reviewed_with_evidence(self, tmp_path):
        record = self._record(tmp_path, {
            "agent_transcript_path": "/t/subagents/agent-1.jsonl",
            "last_assistant_message": "Reviewed 3 files.\n\nNo BLOCK findings;  one MINOR.",
        })
        assert record["agent"] == "code-reviewer"
        assert record["excerpt"] == "Reviewed 3 files. No BLOCK findings; one MINOR."
        assert record["last_message_chars"] == len(record["excerpt"])
        assert "transcript" not in record, "the path is long and nothing reads it"
        assert "changed_docs" not in record, "changed_docs is Gate 2's evidence, not a review's"

    def test_excerpt_is_capped_so_the_record_stays_a_record(self, tmp_path):
        record = self._record(tmp_path, {"last_assistant_message": "x" * 5000})
        assert len(record["excerpt"]) == 160
        assert record["last_message_chars"] == 5000
        # tests/test_state_file_flag_parity.py caps a relief record at 1 KiB.
        assert len(json.dumps(record, ensure_ascii=False)) < 1024

    def test_a_unicode_excerpt_is_not_ascii_escaped_past_the_cap(self, tmp_path):
        """`json.dumps` escapes an em-dash to six characters; 160 of them would
        have rendered a 160-char excerpt as ~1000 (code review, 2026-09-07).
        The record is written unescaped, so the cap holds for any script."""
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False,
             "last_assistant_message": "\u2014" * 400},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0, result.stderr
        text = (repo / ".espalier-state" / "code_reviewed").read_text(encoding="utf-8")
        assert "\u2014" in text and "\\u2014" not in text
        assert len(text) < 1024

    def test_a_missing_message_still_records_the_run(self, tmp_path):
        """A review that says nothing is still a run; the evidence Gate 3 reads
        is the agent name."""
        record = self._record(tmp_path, {})
        assert record["agent"] == "code-reviewer"
        assert record["excerpt"] == "" and record["last_message_chars"] == 0

    def test_the_record_routes_through_atomic_write_text(self, tmp_path, monkeypatch):
        """The gate PARSES this file; a torn write would read as a malformed
        record, not as the run that happened. Same pin shape as the counter
        writers (tests/test_reflect_trigger_concurrency.py)."""
        mod = _load_hook_module("subagent_stop")
        calls: list[tuple[Path, str]] = []
        monkeypatch.setattr(
            mod._hook_utils, "atomic_write_text",
            lambda path, content, **kw: calls.append((path, content)),
        )
        mod._set_relief_flag(tmp_path, "code-reviewer", {"last_assistant_message": "ok"})
        assert len(calls) == 1
        assert calls[0][0] == tmp_path / ".espalier-state" / "code_reviewed"
        assert json.loads(calls[0][1])["agent"] == "code-reviewer"

    def test_a_docs_heavy_session_keeps_the_record_under_the_cap(self, tmp_path):
        """`changed_docs` is unbounded and a docs-heavy session is exactly when
        the docs record is written (failure-mode review, 2026-09-07): the path
        list is trimmed to fit the parity cap, the total is kept, and the
        evidence Gate 2 reads (a non-empty list) survives."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "docs" / "sharp-edges").mkdir(parents=True)
        for i in range(40):
            (repo / "docs" / "sharp-edges" / f"a-long-descriptive-footgun-name-number-{i:02d}.md").write_text("# x\n", encoding="utf-8")
        result = _run_hook(
            {"agent_type": "docs-maintainer", "stop_hook_active": False, "last_assistant_message": "refreshed " * 40},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0, result.stderr
        text = (repo / ".espalier-state" / "docs_refreshed").read_text(encoding="utf-8")
        assert len(text) < 1024, len(text)
        record = json.loads(text)
        assert record["changed_docs_total"] == 40
        assert 0 < len(record["changed_docs"]) < 40


class TestReliefFlagCarriesEvidence:
    """DEF-495: the flag records what the agent CHANGED, not that it showed up."""

    def _git_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        (repo / "docs").mkdir()
        (repo / "docs" / "CONVENTIONS.md").write_text("# conventions\n", encoding="utf-8")
        (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
        return repo

    def test_records_changed_markdown(self, tmp_path):
        repo = self._git_repo(tmp_path)
        (repo / "docs" / "CONVENTIONS.md").write_text("# conventions\nnew line\n", encoding="utf-8")
        result = _run_hook(
            {"agent_type": "docs-maintainer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        payload = json.loads((repo / ".espalier-state" / "docs_refreshed").read_text(encoding="utf-8"))
        assert payload["changed_docs"] == ["docs/CONVENTIONS.md"], payload

    def test_records_empty_when_only_non_markdown_changed(self, tmp_path):
        """A docs-maintainer that touched only code has not refreshed docs."""
        repo = self._git_repo(tmp_path)
        (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
        result = _run_hook(
            {"agent_type": "docs-maintainer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        payload = json.loads((repo / ".espalier-state" / "docs_refreshed").read_text(encoding="utf-8"))
        assert payload["changed_docs"] == [], payload

    def test_non_git_tree_records_no_evidence_and_does_not_crash(self, tmp_path):
        repo = tmp_path / "bare"
        repo.mkdir()
        result = _run_hook(
            {"agent_type": "docs-maintainer", "stop_hook_active": False},
            {"CLAUDE_PROJECT_DIR": str(repo)},
        )
        assert result.returncode == 0
        payload = json.loads((repo / ".espalier-state" / "docs_refreshed").read_text(encoding="utf-8"))
        assert payload["changed_docs"] == []


# ── DEF-586: the entry carries the agent's reasoning, not a fixed sentence ────

def _stub_argv_cli(root: Path) -> Path:
    """Stage a ``tools/cc/cognitive_blueprint.py`` that dumps its argv, so a
    test can read exactly what the hook asked the record CLI to write.
    Returns the argv file path (not yet created)."""
    (root / "tools" / "cc").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "cc" / "cognitive_blueprint.py").write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['CLAUDE_PROJECT_DIR'], 'record_argv.json')"
        ".write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return root / "record_argv.json"


def _recorded(root: Path, payload: dict) -> dict:
    """Run the hook against the argv stub for a code-reviewer stop; return the
    record call's ``{flag: value}`` map (a flag with no value maps to True)."""
    argv_file = _stub_argv_cli(root)
    result = _run_hook(
        {"agent_type": "code-reviewer", "stop_hook_active": False, **payload},
        {"CLAUDE_PROJECT_DIR": str(root)},
    )
    assert result.returncode == 0, result.stderr
    assert argv_file.exists(), f"the record CLI never ran; stderr={result.stderr!r}"
    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert argv[0] == "record", argv
    flags: dict = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            flags[argv[i]] = argv[i + 1]
            i += 2
        else:
            flags[argv[i]] = True
            i += 1
    return flags


_PREFIX = "[subagent:code-reviewer] "


class TestSubagentReasoningIsKept:
    """DEF-586: the hook recorded a fixed sentence per stop ("Subagent X
    completed; output captured in parent tool-result stream") while the payload
    it already read for the relief record carried the agent's final message.
    A fan-out session's findings survived only in the parent's tool-result
    stream, which a compaction or a session end discards, so the next session
    saw nothing of what the reviewers found.

    Now the entry is the prefix plus the LEAD of ``last_assistant_message``
    (whitespace collapsed, cut on a word boundary at ``_LEAD_CHARS``), with the
    transcript it was cut from as evidence. A payload without a usable message
    records an anchor with NO evidence: the blueprint readers key on the
    evidence to keep reports and drop anchors, so an anchor that carried
    evidence would put a content-free line into the next session's banner.
    Both payload keys are the documented SubagentStop input
    (code.claude.com/docs/en/hooks#subagentstop, re-verified 2026-09-11).
    """

    def test_the_final_message_lead_is_the_entry(self, tmp_path):
        flags = _recorded(tmp_path, {
            "last_assistant_message": "## Verdict: REQUEST CHANGES\n\nTwo findings.  First: the cap.",
            "agent_transcript_path": "/t/subagents/agent-1.jsonl",
        })
        assert flags["--kind"] == "pattern_discovered"
        assert flags["--description"] == (
            _PREFIX + "## Verdict: REQUEST CHANGES Two findings. First: the cap."
        )
        assert flags["--evidence"] == "/t/subagents/agent-1.jsonl"

    def test_the_lead_is_cut_on_a_word_boundary_under_the_soft_target(self, tmp_path):
        mod = _load_hook_module("subagent_stop")
        words = " ".join(f"w{i}" for i in range(400))  # ~2 KB, a space every few chars
        flags = _recorded(tmp_path, {
            "last_assistant_message": words, "agent_transcript_path": "/t/a.jsonl",
        })
        desc = flags["--description"]
        assert desc.startswith(_PREFIX) and desc.endswith(" ...")
        lead = desc[len(_PREFIX):-len(" ...")]
        assert 0 < len(lead) <= mod._LEAD_CHARS
        # Whole words only: the lead is a prefix of the message that ends at a space.
        assert words.startswith(lead) and words[len(lead)] == " "
        # The record CLI's write-time advisory fires above 1000 chars; a hook
        # that trips it on every stop is stderr noise, so the entry stays under.
        assert len(desc) < 1000

    def test_a_message_with_no_spaces_is_hard_cut_at_the_cap(self, tmp_path):
        mod = _load_hook_module("subagent_stop")
        flags = _recorded(tmp_path, {
            "last_assistant_message": "x" * 5000, "agent_transcript_path": "/t/a.jsonl",
        })
        lead = flags["--description"][len(_PREFIX):-len(" ...")]
        assert len(lead) == mod._LEAD_CHARS

    def test_a_short_message_is_recorded_whole_with_no_marker(self, tmp_path):
        flags = _recorded(tmp_path, {
            "last_assistant_message": "APPROVE. Nothing to change.",
            "agent_transcript_path": "/t/a.jsonl",
        })
        assert flags["--description"] == _PREFIX + "APPROVE. Nothing to change."

    def test_a_missing_message_records_an_anchor_with_no_evidence(self, tmp_path):
        flags = _recorded(tmp_path, {"agent_transcript_path": "/t/subagents/agent-1.jsonl"})
        assert flags["--description"] == _PREFIX + "completed"
        assert "--evidence" not in flags, (
            "an anchor must carry no evidence: the readers treat an agent entry "
            "WITH evidence as a report and would carry this content-free line "
            "into the next session's banner"
        )
        assert "output captured in parent tool-result stream" not in flags["--description"]

    @pytest.mark.parametrize("message", [42, None, "", "   \n\t "])
    def test_a_non_string_or_blank_message_is_an_anchor(self, tmp_path, message):
        flags = _recorded(tmp_path, {
            "last_assistant_message": message, "agent_transcript_path": "/t/a.jsonl",
        })
        assert flags["--description"] == _PREFIX + "completed"
        assert "--evidence" not in flags

    def test_a_report_without_a_transcript_path_still_carries_evidence(self, tmp_path):
        """The report/anchor distinction IS the evidence field, so a report cut
        from a payload that names no transcript must still say where it came
        from, or the readers would drop it as an anchor."""
        flags = _recorded(tmp_path, {"last_assistant_message": "APPROVE. Nothing to change."})
        assert flags["--description"] == _PREFIX + "APPROVE. Nothing to change."
        assert flags.get("--evidence"), "a report with no transcript path must still carry evidence"

    def test_a_transcript_path_is_passed_through_verbatim(self, tmp_path):
        """The hook does not reshape the path, comma included. What the record
        CLI then does with a comma is that CLI's contract, driven in
        tests/test_cognitive_blueprint.py::TestAgentReportsAreKept."""
        flags = _recorded(tmp_path, {
            "last_assistant_message": "APPROVE. Nothing to change.",
            "agent_transcript_path": "/t/a,b/agent-1.jsonl",
        })
        assert flags["--evidence"] == "/t/a,b/agent-1.jsonl"

    def test_lead_helper_boundary_cases(self):
        mod = _load_hook_module("subagent_stop")
        assert mod._lead("alpha beta gamma", 10) == "alpha beta ..."
        assert mod._lead("alpha beta gamma", 9) == "alpha ..."
        assert mod._lead("alpha beta gamma", 16) == "alpha beta gamma"
        assert mod._lead("  a \n\n b\t c  ", 100) == "a b c"
        assert mod._lead("x" * 20, 5) == "xxxxx ..."
        assert mod._lead("", 5) == ""

    # -- review batch (2026-09-11): the holes both reviewers drove --------------

    def test_non_ascii_in_the_message_is_folded_to_printable_ascii(self, tmp_path):
        """The record CLI echoes the description to stdout; under the cp1252
        stdout Windows gives a piped child, an arrow or a tick in an agent's
        message crashed it AFTER the entry was saved, and this hook then printed
        a false 'reasoning lost' WARN on every fan-out stop. The lead is folded
        at the one producer: every char outside printable ASCII becomes a space
        and the run collapses (tools/cc/CLAUDE.md rule 4)."""
        mod = _load_hook_module("subagent_stop")
        flags = _recorded(tmp_path, {
            "last_assistant_message": "Verdict: APPROVE \u2192 two notes \u2014 one \u2713",
            "agent_transcript_path": "/t/a.jsonl",
        })
        assert flags["--description"] == _PREFIX + "Verdict: APPROVE two notes one"
        assert mod._lead("caf\u00e9 au lait", 100) == "caf au lait"
        assert mod._lead("a\u2192b", 100) == "a b"
        assert all(" " <= c <= "~" for c in mod._lead("\u2713" * 50 + "ok", 100))

    def test_a_transcript_path_without_a_message_string_warns_that_the_key_may_have_moved(self, tmp_path):
        """Both keys are documented together. A payload naming the transcript but
        carrying no message string means the message key moved (a Claude Code
        rename), not that the agent said nothing -- and without this line every
        stop would record an anchor and the corpus would stop gaining reports
        with no signal (the trigger-gated-defect shape)."""
        _stub_argv_cli(tmp_path)
        moved = _run_hook(
            {"agent_type": "code-reviewer", "stop_hook_active": False,
             "agent_transcript_path": "/t/a.jsonl"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert moved.returncode == 0
        err = moved.stderr.decode("utf-8", errors="replace")
        assert "[WARN] subagent_stop" in err and "last_assistant_message" in err
        for payload in ({}, {"last_assistant_message": "APPROVE.",
                             "agent_transcript_path": "/t/a.jsonl"}):
            quiet = _run_hook(
                {"agent_type": "code-reviewer", "stop_hook_active": False, **payload},
                {"CLAUDE_PROJECT_DIR": str(tmp_path)},
            )
            assert quiet.returncode == 0
            assert "last_assistant_message" not in quiet.stderr.decode("utf-8", errors="replace")

    def test_the_payload_keys_are_pinned_in_the_external_protocol_doc(self):
        """The dependency on the two SubagentStop keys used to live only in a
        dated code comment, which the hooks/CLAUDE.md protocol-refresh ritual
        never reaches. The pinned external truth carries them now."""
        doc = (REPO_ROOT / "docs" / "external" / "cc-hook-protocol.md").read_text(encoding="utf-8")
        assert "last_assistant_message" in doc and "agent_transcript_path" in doc

    def test_the_reviewer_bodies_open_with_the_verdict_the_lead_records(self):
        """Both reviewer specs prescribed per-finding blocks first and the
        verdict in a closing summary; the lead takes the head, so the entry
        captured the first finding and never the verdict. The bodies now say
        to open with it, and name the cap so the sentence stales loudly."""
        mod = _load_hook_module("subagent_stop")
        for name in ("code-reviewer", "failure-mode-reviewer"):
            body = (REPO_ROOT / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
            assert "Open with the verdict line" in body, name
            assert "subagent_stop" in body and str(mod._LEAD_CHARS) in body, name
