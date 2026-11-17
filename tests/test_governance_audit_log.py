"""TP-330 — governance action-log completeness.

Earn-the-red: the three everyday enforcement denials must each append a
well-formed record to the ``~/.espalier/audit`` log, the same way the
kill-switch path already does. Before TP-330 only the kill-switch path
logged; these three left no watchable record:

  - ``write_guard`` protected-zone deny   -> ``pretooluse_blocked_protected_zone``
  - ``write_guard`` dangerous-command deny -> ``pretooluse_blocked_dangerous_command``
  - ``plan_guard`` no-active-plan deny     -> ``pretooluse_blocked_no_active_plan``

The audit dir is redirected to ``tmp_path/audit`` by the autouse
``_isolate_audit_dir`` fixture (tests/conftest.py); the hook subprocess
inherits ``ESPALIER_AUDIT_DIR``. ``ESPALIER_MAINTENANCE_MODE`` is deleted
from the child env — the host may run with MAINTENANCE=on, which bypasses
the protected-zone and plan-required checks and would un-earn the red.

``--log`` tail coverage lives in ``TestStatusLogTail`` below.
"""
from __future__ import annotations

import ast
import functools
import itertools
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from _site_path import site_path
from tests._live_tree import checkout_glob
from tests._hook_runner import run_hook
from tests._hook_spawn import not_a_budget_miss, run_hook_through

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

# `/status --log`'s window, read from the line by its shape: the reader dates it
# by its own clock, so a date the test computed would race it at 00:00Z, the
# flake DEF-1152 names.
_WINDOW = r"since \d{4}-\d{2}-\d{2} 00:00Z"


def _run_hook(script: str, payload: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # The host may run MAINTENANCE=on, which bypasses the protected-zone and
    # plan-required checks; delete it so the denial (and its audit record) fires.
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    return run_hook_through(
        [sys.executable, str(HOOKS_DIR / script)],
        input=json.dumps(payload),
        env=env,
    )


def _audit_records() -> list[dict]:
    """Every JSON record across the redirected audit dir (autouse fixture)."""
    audit_dir = Path(os.environ["ESPALIER_AUDIT_DIR"])
    records: list[dict] = []
    for log in sorted(audit_dir.glob("*.log")):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


class TestEnforcementDenialAudit:
    """Each of the three unlogged denial paths appends an audit record."""

    def test_protected_zone_denial_logs_audit(self, tmp_path):
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/foo.py"}},
            tmp_path,
        )
        assert result.returncode == 0
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        # Discriminating: it is the PROTECTED-ZONE deny (path named in the
        # reason), not a speed-bump or other deny masking it.
        assert "tools/cc/hooks/foo.py" in decision["permissionDecisionReason"]

        records = _audit_records()
        events = [r["event_type"] for r in records]
        assert "pretooluse_blocked_protected_zone" in events, events
        rec = next(r for r in records if r["event_type"] == "pretooluse_blocked_protected_zone")
        # metadata only — the target path, never file contents. Check the
        # SERIALIZED blob (not dict-key membership, which is vacuous here).
        blob = json.dumps(rec["details"])
        assert "foo.py" in blob
        assert "content" not in blob

    def test_dangerous_command_denial_logs_audit(self, tmp_path):
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            tmp_path,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

        events = [r["event_type"] for r in _audit_records()]
        assert "pretooluse_blocked_dangerous_command" in events, events

    def test_plan_guard_denial_logs_audit(self, tmp_path):
        result = _run_hook(
            "plan_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}},
            tmp_path,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

        events = [r["event_type"] for r in _audit_records()]
        assert "pretooluse_blocked_no_active_plan" in events, events


def _run_status_log(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Mirror production: ``/status --log`` runs ``session_resume.py --log``
    with cwd = repo root and NO positional (repo_root defaults to ".")."""
    env = os.environ.copy()
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
         "--log", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


class TestStatusLogTail:
    """``session_resume.py --log [N]`` prints the current repo's audit tail,
    read-only, resolving the path the same way the writer does."""

    def _run_log(self, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
        return _run_status_log(tmp_path, *args)

    def test_log_tails_the_repo_audit_records(self, tmp_path):
        # Arm two real denials so audit records exist for this repo today.
        _run_hook(
            "plan_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
            tmp_path,
        )
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            tmp_path,
        )
        result = self._run_log(tmp_path, "10")
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert "pretooluse_blocked_no_active_plan" in out
        assert "pretooluse_blocked_dangerous_command" in out

    def test_log_empty_when_no_records(self, tmp_path):
        # No denials armed → the tail is empty but must exit 0 (read-only).
        result = self._run_log(tmp_path)
        assert result.returncode == 0, result.stderr
        assert "no governance denials" in result.stdout.lower()

    def test_log_shows_denials_not_advisory_noise(self, tmp_path):
        # The shared log also carries advisory records (post_write_check writes
        # `action_justification_missing` on every un-justified write). `--log`
        # must surface DENIALS, not let them be buried under that noise.
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            tmp_path,
        )
        audit_dir = Path(os.environ["ESPALIER_AUDIT_DIR"])
        logs = list(audit_dir.glob("*.log"))
        assert logs, "the denial should have created today's log"
        noise = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "event_type": "action_justification_missing",
            "repo_path": str(tmp_path),
            "details": {"tool": "Bash", "target": "secret-command-body-xyz"},
        }
        with logs[0].open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(noise) + "\n")

        result = self._run_log(tmp_path, "5")
        assert result.returncode == 0, result.stderr
        assert "pretooluse_blocked_dangerous_command" in result.stdout
        # The advisory record (and its command text) is filtered out.
        assert "action_justification_missing" not in result.stdout
        assert "secret-command-body-xyz" not in result.stdout

    def test_log_survives_non_utf8_line(self, tmp_path):
        # A partial/interleaved multi-byte append (documented for the lock-free
        # Windows path) leaves non-UTF8 bytes on a line; `--log` must degrade,
        # not crash with a traceback.
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            tmp_path,
        )
        logs = list(Path(os.environ["ESPALIER_AUDIT_DIR"]).glob("*.log"))
        assert logs
        with logs[0].open("ab") as fh:
            fh.write(b"\xff\xfe not valid utf8\n")

        result = self._run_log(tmp_path, "10")
        assert result.returncode == 0, result.stderr  # must NOT crash
        assert "pretooluse_blocked_dangerous_command" in result.stdout

    # -- the repo_root positional after --log (ledger row TP-330, residual 1) --
    #
    # ``--log`` takes an OPTIONAL count, so argparse hands it whatever token
    # follows. Before the fix ``--log /path/to/repo`` died with ``invalid int
    # value`` (exit 2) instead of tailing that repo: the one CLI shape where the
    # documented positional and the documented option meet. These drive the CLI
    # from a DIFFERENT cwd than the repo, so the root has to be honoured for the
    # armed denial to appear at all.

    def _run_log_from(self, cwd: Path, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("ESPALIER_MAINTENANCE_MODE", None)
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--log", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            env=env, encoding="utf-8",
        )

    def _arm_denial_in(self, repo: Path) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            repo,
        )

    def test_log_reads_a_repo_root_given_right_after_it(self, tmp_path):
        repo = tmp_path / "repo"
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        self._arm_denial_in(repo)
        result = self._run_log_from(elsewhere, str(repo))
        assert result.returncode == 0, result.stderr
        assert "invalid int value" not in result.stderr
        # The record lives under REPO's slug; seeing it proves the root was
        # read as the root, not rejected as a malformed count.
        assert "pretooluse_blocked_dangerous_command" in result.stdout

    def test_log_count_then_root_keeps_both(self, tmp_path):
        repo = tmp_path / "repo"
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        self._arm_denial_in(repo)
        result = self._run_log_from(elsewhere, "10", str(repo))
        assert result.returncode == 0, result.stderr
        assert "pretooluse_blocked_dangerous_command" in result.stdout

    def test_log_with_two_roots_is_a_usage_error_not_a_traceback(self, tmp_path):
        repo = tmp_path / "repo"
        other = tmp_path / "other"
        repo.mkdir()
        other.mkdir()
        result = self._run_log_from(tmp_path, str(repo), str(other))
        assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
        assert "Traceback" not in result.stderr
        # argparse's own usage error, naming the option and the collision --
        # not the type-coercion message the swallowed positional used to trip.
        assert "--log" in result.stderr
        assert "repo root" in result.stderr
        assert "invalid int value" not in result.stderr

    # -- a token that is neither a count nor a root is an error, never a root --
    #
    # The first cut read ANY non-integer as the swallowed root, so ``--log 2O``
    # (digit-two, letter-O) and ``--log /no/such/dir`` both answered "(no
    # governance denials recorded ...)" at exit 0: a confident wrong answer to
    # "what did the harness block", where the old ``type=int`` at least failed
    # loudly. A root must exist; a count must be positive.

    @staticmethod
    def _usage_error(result: subprocess.CompletedProcess) -> None:
        assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
        assert "Traceback" not in result.stderr
        assert "no governance denials" not in result.stdout
        assert "invalid int value" not in result.stderr

    def test_log_rejects_a_count_typo_instead_of_reading_it_as_a_root(self, tmp_path):
        result = self._run_log(tmp_path, "2O")
        self._usage_error(result)
        assert "expected a count" in result.stderr and "'2O'" in result.stderr

    def test_log_rejects_a_root_that_does_not_exist(self, tmp_path):
        result = self._run_log(tmp_path, str(tmp_path / "no" / "such" / "repo"))
        self._usage_error(result)
        assert "existing repo root" in result.stderr

    def test_log_rejects_a_non_positive_count(self, tmp_path):
        for bad in ("0", "-5"):
            result = self._run_log(tmp_path, bad)
            self._usage_error(result)
            assert "positive count" in result.stderr, (bad, result.stderr)

    # -- the tail is THIS checkout's, and it says what the window left out --

    def test_log_keeps_only_this_roots_records_when_two_checkouts_share_a_basename(self, tmp_path):
        # The file is keyed by basename: a/myrepo and b/myrepo share it. Every
        # record carries the writer's repo_path for exactly this reason.
        armed = tmp_path / "a" / "myrepo"
        other = tmp_path / "b" / "myrepo"
        other.mkdir(parents=True)
        self._arm_denial_in(armed)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        seen = self._run_log_from(elsewhere, str(armed))
        assert seen.returncode == 0, seen.stderr
        assert "pretooluse_blocked_dangerous_command" in seen.stdout
        unseen = self._run_log_from(elsewhere, str(other))
        assert unseen.returncode == 0, unseen.stderr
        assert "no governance denials" in unseen.stdout.lower(), unseen.stdout
        assert "pretooluse_blocked_dangerous_command" not in unseen.stdout

    def test_log_counts_every_denial_type_for_the_day_above_the_tail(self, tmp_path):
        # Two kinds armed; a window of ONE shows one record, and the count
        # line above it still names both kinds -- the window cannot hide the
        # rarer denial without a trace.
        _run_hook(
            "plan_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
            tmp_path,
        )
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            tmp_path,
        )
        result = self._run_log(tmp_path, "1")
        assert result.returncode == 0, result.stderr
        header, by_type, *records = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert header.startswith("# governance audit log -- last 1 of 2 denial records")
        assert by_type.startswith("# by type: ")
        assert "pretooluse_blocked_no_active_plan 1" in by_type
        assert "pretooluse_blocked_dangerous_command 1" in by_type
        assert len(records) == 1, records
        assert result.stdout.isascii()

    def test_a_record_in_yesterdays_log_and_one_in_todays_are_both_counted(self, tmp_path):
        """DEF-1152's CI cell: two hook calls seconds apart straddled 00:00Z
        on #512's `test (3.14)`, and a read of today's log alone counted one of
        the two. One record in yesterday's log and one in today's drive it
        without waiting for midnight. Dies to: a reader of today's log alone
        (`last 1 of 1`)."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        # This test's own clock and the reader's must see one UTC date; a run
        # across 00:00Z is cannot-tell, not a red (the race this row names).
        crossed = lambda: (datetime.now(timezone.utc) - timedelta(days=1)).date() != yesterday.date()  # noqa: E731
        integ.audit_path(tmp_path, yesterday).parent.mkdir(parents=True, exist_ok=True)
        integ.audit_path(tmp_path, yesterday).write_text(json.dumps({
            "timestamp": yesterday.isoformat(), "event_type": "pretooluse_blocked_no_active_plan",
            "repo_path": str(tmp_path.resolve()), "details": {"tool": "Edit"},
        }) + "\n", encoding="utf-8")
        _run_hook("write_guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, tmp_path)
        result = self._run_log(tmp_path, "1")
        if crossed():
            pytest.skip("the run crossed 00:00Z: yesterday's log left the reader's window")
        assert result.returncode == 0, result.stderr
        header, by_type, *records = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert re.match(rf"# governance audit log -- last 1 of 2 denial records for this repo {_WINDOW}: ", header), header
        assert "pretooluse_blocked_no_active_plan 1" in by_type and "pretooluse_blocked_dangerous_command 1" in by_type
        # The tail is the newest: today's record, read after yesterday's.
        assert len(records) == 1 and "pretooluse_blocked_dangerous_command" in records[0], records


def _load_hook_module(name: str):
    """Load a hook in-process the way the hooks load each other: the hooks dir
    on ``sys.path`` for the sibling imports, then ``spec_from_file_location``
    (never a plain import, which would drag espalier into the zero-import
    graph -- tests/CLAUDE.md)."""
    import importlib.util

    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _function_body_dump(path: Path, name: str) -> tuple[str, str]:
    """``(signature, body)`` AST dumps of the top-level function ``name`` in
    ``path``, with a leading docstring dropped so prose can differ freely."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            sig = ast.dump(node.args)
            if node.returns is not None:
                sig += "|" + ast.dump(node.returns)
            return sig, ast.dump(ast.Module(body=body, type_ignores=[]))
    raise AssertionError(f"{path.name} has no top-level def {name}")


class TestDenyFunnelParity:
    """Ledger row TP-330, residual 2: the PreToolUse audited-deny funnel exists
    TWICE -- ``write_guard.deny``/``_audit_deny`` and ``plan_guard.deny``/
    ``_audit_deny`` -- because a shared owner in ``_hook_utils`` would cycle
    (``_integrity`` imports it; plan_guard's own docstring says so). A twin the
    isolation rule forces gets PINNED, not noted (the ``_has_active_plan`` and
    ``decode_bom`` parity precedents), or the two hooks drift and the adopter's
    audit log tells two stories about one kind of denial.

    Two pins. The ``deny`` emitters are the same code modulo docstring (they
    print the decision the protocol reads, so a divergence there is a silent
    non-deny in one hook). The ``_audit_deny`` funnels are pinned by
    BEHAVIOUR, not text -- their bodies are legitimately shaped differently
    (write_guard splits the swallow into ``_audit``) -- under both audit
    outcomes: the write raises, the write works. Channel XOR on both: one
    stdout JSON, empty stderr, ``_hook_utils.DENIED`` back.
    """

    WG = HOOKS_DIR / "write_guard.py"
    PG = HOOKS_DIR / "plan_guard.py"

    def test_deny_emitters_are_the_same_code_modulo_docstring(self):
        wg_sig, wg_body = _function_body_dump(self.WG, "deny")
        pg_sig, pg_body = _function_body_dump(self.PG, "deny")
        assert wg_sig == pg_sig, "deny() signatures differ between write_guard and plan_guard"
        if wg_body != pg_body:
            import difflib

            def _src(path: Path) -> list[str]:
                tree = ast.parse(path.read_text(encoding="utf-8"))
                node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "deny")
                return ast.unparse(node).splitlines()

            diff = "\n".join(difflib.unified_diff(_src(self.WG), _src(self.PG), "write_guard.deny", "plan_guard.deny", lineterm=""))
            raise AssertionError(
                "write_guard.deny and plan_guard.deny have drifted -- the two PreToolUse "
                "deny emitters must stay the same code (docstrings may differ):\n" + diff
            )

    @staticmethod
    def _one_decision(captured_out: str) -> dict:
        lines = [ln for ln in captured_out.splitlines() if ln.strip()]
        assert len(lines) == 1, f"expected exactly one stdout JSON decision, got {lines!r}"
        return json.loads(lines[0])

    def _drive_both(self, tmp_path: Path, capsys, event_type: str, reason: str) -> tuple[dict, dict]:
        wg = _load_hook_module("write_guard")
        pg = _load_hook_module("plan_guard")
        results = []
        for mod in (wg, pg):
            rc = mod._audit_deny(tmp_path, event_type, reason, channel="Edit", path="src/a.py")
            captured = capsys.readouterr()
            assert captured.err == "", f"{mod.__name__}: stderr on the deny path breaks channel XOR: {captured.err!r}"
            assert rc == 0 and rc, f"{mod.__name__}: _audit_deny must return the truthy-zero DENIED sentinel"
            decision = self._one_decision(captured.out)["hookSpecificOutput"]
            assert decision["hookEventName"] == "PreToolUse"
            assert decision["permissionDecision"] == "deny"
            assert decision["permissionDecisionReason"] == reason
            results.append(decision)
        return results[0], results[1]

    def test_funnels_stay_silent_when_the_audit_dir_cannot_be_created(self, tmp_path, capsys, monkeypatch):
        # A REAL OSError inside the writer -- its own branch warns on stderr
        # unless the funnel tells it to stay quiet -- not a monkeypatched
        # raise, which never reaches that branch. The audit dir is asked for
        # under a file.
        (tmp_path / "blocker").write_text("not a directory\n", encoding="utf-8")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "blocker" / "audit"))
        self._drive_both(
            tmp_path, capsys, "pretooluse_blocked_no_active_plan", "reason under an unwritable audit dir"
        )
        assert _audit_records() == []

    def test_funnels_agree_when_the_audit_write_raises(self, tmp_path, capsys, monkeypatch):
        _load_hook_module("write_guard")  # ensures _integrity is importable/loaded
        integrity = sys.modules["_integrity"]

        def _boom(*_a, **_k):
            raise RuntimeError("audit sink unavailable")

        monkeypatch.setattr(integrity, "append_audit", _boom)
        wg_decision, pg_decision = self._drive_both(
            tmp_path, capsys, "pretooluse_blocked_protected_zone", "reason under a failing audit sink"
        )
        assert wg_decision == pg_decision
        assert _audit_records() == []  # nothing could be written; nothing was

    def test_funnels_agree_when_the_audit_write_works(self, tmp_path, capsys):
        wg_decision, pg_decision = self._drive_both(
            tmp_path, capsys, "pretooluse_blocked_no_active_plan", "reason under a working audit sink"
        )
        assert wg_decision == pg_decision
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_blocked_no_active_plan"]
        assert len(records) == 2, records
        wg_rec, pg_rec = records
        assert set(wg_rec) == set(pg_rec) == {"timestamp", "event_type", "repo_path", "details"}
        assert wg_rec["details"] == pg_rec["details"] == {"channel": "Edit", "path": "src/a.py"}
        assert wg_rec["repo_path"] == pg_rec["repo_path"] == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Ledger row TP-330, residual 3: every denial the hooks make reaches the
# ``/status --log`` reader. Two ways one did not: written under an event type
# the reader's filter set lacks (the secret-path read deny, landed 2026-09-03
# after the set was written), or never written (the speed-bump deny). The set
# claims to be the single owner keeping "the reader filter, the docs table,
# and the writers" aligned; nothing derived it from the writers, so it drifted.
# The pins below make the set the OUTPUT of a search over the hooks, both
# directions, with a floor -- and pin the shipped HOOKS.md table to it.
# ---------------------------------------------------------------------------

_BLOCKED_EVENT_RE = re.compile(r"[a-z0-9]+_blocked_[a-z0-9_]+")
#: The calls that WRITE an audit record. Only a literal inside one of these is
#: an emitted event type; a hook that merely reads the log and names a type in
#: a filter tuple is not an emitter. ``_audit_block`` is the Stop hook's
#: funnel (record, then ``block``), the twin of the PreToolUse ``_audit_deny``.
_AUDIT_WRITERS = frozenset({"_audit", "_audit_deny", "_audit_block", "append_audit"})


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _blocked_literals(node: ast.AST) -> set[str]:
    return {
        c.value for c in ast.walk(node)
        if isinstance(c, ast.Constant) and isinstance(c.value, str) and _BLOCKED_EVENT_RE.fullmatch(c.value)
    }


def _writer_event_literals_over(nodes: list[ast.AST]) -> set[str]:
    """Every ``<event>_blocked_<what>`` literal that REACHES an audit writer
    inside ``nodes``: the literals in the writer call's own arguments
    (positional, keyword, inside a dict literal or a conditional expression),
    plus the literals assigned within ``nodes`` to a name the call's arguments
    reference -- config_guard picks its type in a conditional bound to a local
    first, then passes the local. Derived from the calls that write, not from
    string presence, so a reader that names a type in a filter is not an
    emitter. ``nodes`` is the node population read, already flattened: every
    node of a function for the set contract, the nodes on the emit's own path
    for the bare-emitter census (DEF-828)."""
    assigned: dict[str, set[str]] = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            lits = _blocked_literals(node.value)
            if lits:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, set()).update(lits)
    out: set[str] = set()
    for node in nodes:
        if not (isinstance(node, ast.Call) and _call_name(node) in _AUDIT_WRITERS):
            continue
        out |= _blocked_literals(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in assigned:
                out |= assigned[sub.id]
    return out


def _writer_event_literals(fn: ast.AST) -> set[str]:
    """``_writer_event_literals_over`` every node of one whole function."""
    return _writer_event_literals_over(list(ast.walk(fn)))


def _emitted_denial_event_types() -> set[str]:
    """The union of ``_writer_event_literals`` over every function in every
    hook except ``_integrity.py`` -- the set's own home, excluded so the
    comparison cannot be a tautology."""
    found: set[str] = set()
    for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
        if hook.name == "_integrity.py":
            continue
        tree = ast.parse(hook.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found |= _writer_event_literals(node)
    return found


class TestEveryDenialReachesTheStatusLog:
    """Driven end to end: the hook denies, the record lands, ``--log`` shows it."""

    def test_secret_path_read_denial_shows_in_the_log(self, tmp_path):
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Read", "tool_input": {"file_path": ".env"}},
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert ".env" in decision["permissionDecisionReason"]
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_blocked_secret_path"]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        # Metadata only: the tool and the matched rule. The target path stays
        # in the reason the agent sees, never in the log.
        assert records[0]["details"] == {"tool": "Read", "shape": ".env / .env.*"}
        tail = _run_status_log(tmp_path, "10")
        assert tail.returncode == 0, tail.stderr
        # Written is not shown: the reader filters on the declared set.
        assert "pretooluse_blocked_secret_path" in tail.stdout, tail.stdout

    def test_speed_bump_denial_is_audited_with_its_checkpoint_and_shows_in_the_log(self, tmp_path):
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}},
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        decision = json.loads(result.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "Speed-bump [CP-GITCLEAN]" in decision["permissionDecisionReason"]
        records = [r for r in _audit_records() if r["event_type"] == "pretooluse_blocked_speed_bump"]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        # Metadata only: the tool and the matched rule (the checkpoint id) --
        # never the reminder text, never the command.
        assert records[0]["details"] == {"tool": "Bash", "checkpoint": "CP-GITCLEAN"}
        # A speed-bump fire is a pause (the re-issued command proceeds): the
        # default tail counts it on the pauses line and shows the record only
        # under ``--all``.
        plain = _run_status_log(tmp_path, "10")
        assert plain.returncode == 0, plain.stderr
        assert "pretooluse_blocked_speed_bump 1" in plain.stdout
        assert "CP-GITCLEAN" not in plain.stdout
        tail = _run_status_log(tmp_path, "10", "--all")
        assert tail.returncode == 0, tail.stderr
        assert "pretooluse_blocked_speed_bump" in tail.stdout
        assert "CP-GITCLEAN" in tail.stdout
        assert "git clean" not in tail.stdout


class TestBlockedEventTypesAreDerivedAndTiered:
    """The two declared tiers in ``_integrity`` -- ``DENIAL_EVENT_TYPES`` (a
    refusal: the call did not run) and ``PAUSE_EVENT_TYPES`` (once-then-
    continue: a speed-bump fire lets the re-issued command proceed, a Stop-gate
    block is let through by the protocol's loop signal on the next Stop) --
    are disjoint, their union ``BLOCKED_EVENT_TYPES`` equals what the hooks
    write both ways (a type a hook writes that neither tier names is a record
    the reader hides; a type a tier names that no hook writes is a dead row in
    the shipped table), and the tier assignment is pinned so it changes in
    the open (ledger rows DEF-723, DEF-724)."""

    def test_emitted_types_equal_the_union_both_ways_and_the_tiers_are_disjoint(self):
        integ = _load_hook_module("_integrity")
        refusals = set(integ.DENIAL_EVENT_TYPES)
        pauses = set(integ.PAUSE_EVENT_TYPES)
        assert refusals & pauses == set(), f"a type in both tiers: {sorted(refusals & pauses)}"
        assert set(integ.BLOCKED_EVENT_TYPES) == refusals | pauses
        emitted = _emitted_denial_event_types()
        assert len(emitted) >= 9, f"discovery floor: found only {sorted(emitted)}"
        declared = refusals | pauses
        assert emitted - declared == set(), (
            f"written by a hook but in neither tier of /status --log: {sorted(emitted - declared)}"
        )
        assert declared - emitted == set(), (
            f"declared as a blocked type but no hook writes it: {sorted(declared - emitted)}"
        )

    def test_the_stop_hook_types_and_the_speed_bump_are_the_pause_tier(self):
        # A decision, pinned: every type the Stop hook writes is a pause (the
        # loop signal lets the next Stop through), and so is the speed bump
        # (deny once, the re-issued command proceeds). Everything else refuses.
        integ = _load_hook_module("_integrity")
        emitted = _emitted_denial_event_types()
        stop_types = {t for t in emitted if t.startswith("stop_")}
        assert stop_types, "no Stop-hook type is written -- the gate records are gone"
        assert set(integ.PAUSE_EVENT_TYPES) == stop_types | {"pretooluse_blocked_speed_bump"}


class TestHooksDocDenialTableIsPinned:
    """The ``event_type`` table under HOOKS.md "Governance audit log" re-lists
    the declared tiers. Pinned both ways (no drops, no inventions) and per tier
    (a row's tier cell equals the set it is in); the doc ships from
    ``espalier/assets/docs/`` and its byte parity is a sibling contract."""

    @staticmethod
    def _doc_rows(tiers: str = "refusal|pause") -> list[tuple[str, str]]:
        import re

        text = (REPO_ROOT / "docs" / "HOOKS.md").read_text(encoding="utf-8")
        start = text.index("## Governance audit log")
        end = text.find("\n## ", start + 1)
        section = text[start:end if end != -1 else None]
        return re.findall(rf"^\| `([a-z0-9_]+)` \| ({tiers}) \|", section, flags=re.M)

    @pytest.mark.contract
    def test_every_other_row_names_a_type_of_the_family_its_tier_cell_says(self):
        """The rows in no block tier (DEF-3093): a ``report`` row names a
        channelled advisory, a ``fail-open`` row a type the fail-open predicate
        admits, and no row's tier cell is a word outside the four."""
        rows = self._doc_rows("[a-z-]+")
        assert sorted({tier for _t, tier in rows} - {"refusal", "pause", "report", "fail-open"}) == []
        integ = _load_hook_module("_integrity")
        channelled = getattr(integ, "CHANNELLED_ADVISORY_EVENT_TYPES", frozenset())
        others = [(t, tier) for t, tier in rows if tier in ("report", "fail-open")]
        assert others, "the table holds no report or fail-open row"
        wrong = [(t, tier) for t, tier in others
                 if not (t in channelled if tier == "report" else integ.is_fail_open_event(t))]
        assert wrong == []

    @pytest.mark.contract
    def test_table_rows_equal_the_declared_tiers_both_ways(self):
        rows = self._doc_rows()
        types = [t for t, _tier in rows]
        assert len(types) == len(set(types)), f"duplicate rows: {types}"
        integ = _load_hook_module("_integrity")
        declared = set(integ.BLOCKED_EVENT_TYPES)
        assert set(types) - declared == set(), f"HOOKS.md names a type no hook declares: {set(types) - declared}"
        assert declared - set(types) == set(), f"HOOKS.md is missing a declared type: {declared - set(types)}"
        assert {t for t, tier in rows if tier == "pause"} == set(integ.PAUSE_EVENT_TYPES)
        assert {t for t, tier in rows if tier == "refusal"} == set(integ.DENIAL_EVENT_TYPES)

    def test_status_command_points_at_the_table_instead_of_re_listing_it(self):
        # The /status body is the OTHER place an adopter reads what --log shows;
        # it hand-listed four kinds when the set had six. One enumerator.
        text = (REPO_ROOT / ".claude" / "commands" / "status.md").read_text(encoding="utf-8")
        start = text.index("## `--log")
        end = text.find("\n## ", start + 1)
        section = text[start:end if end != -1 else None]
        assert "HOOKS.md" in section, section
        assert not re.search(r"protected-zone\s*/\s*dangerous-command", section), section


#: Hooks whose ``deny``/``block`` emitter writes NO audit record, as a filed
#: gap; a hook here is exempt from the classifier by an explicit, reasoned row
#: rather than by omission, and must still define an emitter (self-expiry).
#: Empty since the Stop hook's gates started writing records (DEF-723); the
#: roster stays so a future blocking hook is exempted in the open, never by
#: omission.
_UNLOGGED_BLOCKERS: dict[str, str] = {}


def _exemption_offenders(exemptions: dict[str, str], defining: set[str]) -> list[str]:
    """An exemption row that names a hook defining no emitter (delete it), or
    one whose reason cites no ledger row. An exemption is filed, not typed:
    the cheapest green for a new blocking hook must not be one line with any
    string. Pure over its arguments so the check stays witnessed while the
    live dict is empty."""
    out: list[str] = []
    for name, reason in exemptions.items():
        if name not in defining:
            out.append(f"{name} is exempt but defines no emitter -- delete its row")
        elif not re.search(r"\b(DEF|TP)-\d+\b", reason):
            out.append(f"{name}'s exemption cites no ledger row: {reason!r}")
    return out


def _hook_trees() -> dict[str, ast.Module]:
    """hook filename -> its parsed module, every hook under ``HOOKS_DIR``."""
    return {hook.name: ast.parse(hook.read_text(encoding="utf-8")) for hook in sorted(checkout_glob(HOOKS_DIR, "*.py"))}


def _unbacked_audit_writers(roster: frozenset[str], trees: dict[str, ast.Module]) -> list[str]:
    """Roster names no hook backs with a definition that reaches the log:
    ``append_audit`` must be defined in ``_integrity.py`` (the writer), and
    every other roster name must be defined at top level in at least one
    hook, each definition calling another roster name, so the chain bottoms
    out at the writer. Under the path rule the writer's NAME is all that
    marks a record, so appending a local wrapper's name to silence a red
    would green emits the wrapper never records (DEF-828's review; the twin
    of the BOM census's ``test_every_bom_helper_is_a_decoder``)."""
    out: list[str] = []
    for name in sorted(roster):
        defs = [
            (file, fn) for file, tree in trees.items() for fn in tree.body
            if isinstance(fn, ast.FunctionDef) and fn.name == name
        ]
        if name == "append_audit":
            if not any(file == "_integrity.py" for file, _fn in defs):
                out.append("append_audit is not defined in _integrity.py -- the roster's writer is gone")
            continue
        if not defs:
            out.append(f"{name} is on the writer roster but no hook defines it")
            continue
        for file, fn in defs:
            calls = {_call_name(n) for n in ast.walk(fn) if isinstance(n, ast.Call)}
            if not calls & (roster - {name}):
                out.append(f"{file}::{name} calls no other roster writer -- it cannot reach the log")
    return out


def _hooks_defining_an_emitter() -> dict[str, set[str]]:
    """hook filename -> the emitter names (``deny``, ``block``) it defines at
    top level. Derived: a new blocking hook joins the population the moment it
    defines one, instead of waiting to be typed into a list."""
    out: dict[str, set[str]] = {}
    for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
        tree = ast.parse(hook.read_text(encoding="utf-8"))
        names = {
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in {"deny", "block"}
        }
        if names:
            out[hook.name] = names
    return out


def _reason_constant(arg: ast.AST) -> str | None:
    """``_denial_reasons.X`` or ``_denial_reasons.X.format(...)`` -> ``X``."""
    node = arg
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        node = arg.func.value  # the template ``.format`` is called on
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "_denial_reasons":
        return node.attr
    return None


def _audit_event_literals(fn: ast.FunctionDef, emit: ast.Call) -> set[str]:
    """The event literals that reach a writer on ``emit``'s own path -- the
    derivation the set contract reads over a whole function, restricted to the
    statements that run on the way to this one emit (DEF-828: keyed on the
    function, a second arm's emit was greened by its sibling's record). The
    path is ``tests/_site_path.py``'s, with both of its opt-ins: bounded at
    the nearest except handler's body (a crash guard's record belongs in the
    handler itself, so nothing above the ``try`` is credited) and the
    ``try``'s ``finally`` credited on the way out (a flag-guarded record
    there reaches every arm)."""
    return _writer_event_literals_over(site_path(fn, emit, bound_at_handler=True).nodes(with_finally=True))


#: A governance deny whose record its emitter writes on the emit's own path:
#: reason constant -> the suffix of the event that must be recorded there.
_RECORDED_REASON_EVENTS = {
    "KILL_SWITCH_DETECTED": ("_blocked_kill_switch", "kill-switch"),
    # TP-476 A-0: config_guard's project-settings change that unwires a gate.
    "GOVERNANCE_GATES_UNWIRED": ("_blocked_unwired", "unwired-gate"),
}


def _classify_bare_emitters(
    tree: ast.Module,
    hook_name: str,
    emitters: set[str],
    fail_closed: frozenset[str],
    audited_by_dispatch: frozenset[str],
) -> tuple[list[str], list[str], set[str]]:
    """``(sites, offenders, fail_closed_used)`` over every bare emitter call in
    ``tree`` -- a call to ``deny``/``block`` outside the funnels' own bodies.

    A site passes when its reason is a fail-closed constant, when it is the
    kill-switch deny and a ``*_blocked_kill_switch`` record is written on the
    emit's own path, when it is a crash guard's ``*_INTERNAL_ERROR`` emit and
    a ``*_blocked_internal_error`` record is written on the emit's own path
    (DEF-803; the path, not the function, since DEF-828), or when its
    function's return value is audited by the dispatcher. Pure over the tree
    so the detector can be proven on a synthetic module."""
    funnels = emitters | {"_audit_deny", "_audit_block"}
    sites: list[str] = []
    offenders: list[str] = []
    used: set[str] = set()
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef) or fn.name in funnels:
            continue
        for call in ast.walk(fn):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in emitters
            ):
                continue
            arg_text = ast.unparse(call.args[0]) if call.args else ""
            where = f"{hook_name}:{call.lineno} in {fn.name}(): {call.func.id}({arg_text})"
            sites.append(where)
            const = _reason_constant(call.args[0]) if call.args else None
            if const in fail_closed:
                used.add(const)
                continue
            if const in _RECORDED_REASON_EVENTS:
                suffix, label = _RECORDED_REASON_EVENTS[const]
                if any(ev.endswith(suffix) for ev in _audit_event_literals(fn, call)):
                    continue
                offenders.append(where + f" -- {label} emitter with no audit of its event on the emit's path")
                continue
            if const is not None and const.endswith("_INTERNAL_ERROR"):
                # A crash guard (DEF-803). The funnelled ones (write_guard,
                # plan_guard, stop_gate) are not bare sites at all; config_guard
                # has no funnel and writes its record in its handler, beside
                # the emit -- on the emit's path, which is what is read.
                if any(ev.endswith("_blocked_internal_error") for ev in _audit_event_literals(fn, call)):
                    continue
                offenders.append(where + " -- crash-guard emitter with no audit of its event on the emit's path (DEF-803)")
                continue
            if fn.name in audited_by_dispatch:
                continue
            offenders.append(where + " -- neither fail-closed, audited on the emit's path, nor dispatch-audited")
    return sites, offenders, used


class TestBareDenySitesAreClassified:
    """Every ``deny``/``block`` call in every hook that defines one, outside the
    audited funnel, is discovered and must be one of four things: a member of
    the SHIPPED ``_denial_reasons.FAIL_CLOSED_REASONS`` (the hook could not
    read its payload -- no governance rule matched, nothing to record; widening
    that set means editing a protected hook file, where the reviewer and the
    gate-weakening speed bump both see it), the kill-switch deny with its
    record written on the emit's own path, a crash guard's emit whose handler
    writes its ``*_blocked_internal_error`` record on the emit's own path
    (DEF-803: a crash is a block like any other, and the four hooks' crash
    reasons left the fail-closed roster when their guards started writing
    records; DEF-828: the path, never the whole function, so a second arm
    cannot ride its sibling's record), or a check whose
    return the dispatcher audits. A new bare emitter
    outside those is exactly the residual this row recorded (the speed-bump
    deny sat there unlogged). The population is derived, ``stop_gate`` is
    exempt by a reasoned row, the allowlist self-expires, and the detector is
    proven on a synthetic site rather than by pinning today's count."""

    #: check function -> the tool label ``write_guard._run_main`` audits its
    #: return under ``pretooluse_blocked_dangerous_command``. Any deny inside
    #: one of these IS a dangerous-command deny by the function's contract:
    #: the dispatcher audits whenever the return is truthy.
    AUDITED_BY_DISPATCH = {"check_bash_dangerous_patterns": "Bash", "check_powershell": "PowerShell"}

    @staticmethod
    def _fail_closed() -> frozenset[str]:
        return frozenset(_load_hook_module("_denial_reasons").FAIL_CLOSED_REASONS)

    def test_population_is_derived_and_exemptions_still_apply(self):
        defining = _hooks_defining_an_emitter()
        assert {"write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"} <= set(defining), defining
        assert _exemption_offenders(_UNLOGGED_BLOCKERS, set(defining)) == []

    def test_an_exemption_without_a_ledger_row_or_without_an_emitter_is_refused(self):
        # The live exemption dict is empty (DEF-723), so the check above runs
        # over nothing; this keeps it witnessed: the cheapest green for a new
        # blocking hook must not be one line with any string.
        offenders = _exemption_offenders(
            {"new_hook.py": "because it is noisy", "gone_hook.py": "DEF-1: reasoned"}, {"new_hook.py"}
        )
        assert len(offenders) == 2, offenders
        assert "new_hook.py" in offenders[0] and "cites no ledger row" in offenders[0], offenders
        assert "gone_hook.py" in offenders[1] and "defines no emitter" in offenders[1], offenders

    def test_every_bare_emitter_is_fail_closed_or_audited(self):
        fail_closed = self._fail_closed()
        all_sites: list[str] = []
        offenders: list[str] = []
        used: set[str] = set()
        dispatch_audits: set[str] = set()
        for hook_name, emitters in _hooks_defining_an_emitter().items():
            if hook_name in _UNLOGGED_BLOCKERS:
                continue
            tree = ast.parse((HOOKS_DIR / hook_name).read_text(encoding="utf-8"))
            sites, bad, used_here = _classify_bare_emitters(
                tree, hook_name, emitters, fail_closed, frozenset(self.AUDITED_BY_DISPATCH)
            )
            all_sites += sites
            offenders += bad
            used |= used_here
            if hook_name != "write_guard.py":
                continue
            for fn in tree.body:
                if not (isinstance(fn, ast.FunctionDef) and fn.name == "_run_main"):
                    continue
                for node in ast.walk(fn):
                    if (
                        isinstance(node, ast.Call)
                        and _call_name(node) == "_audit"
                        and len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value == "pretooluse_blocked_dangerous_command"
                    ):
                        for kw in node.keywords:
                            if kw.arg == "tool" and isinstance(kw.value, ast.Constant):
                                dispatch_audits.add(str(kw.value.value))
        assert all_sites, "discovery found no bare emitter site anywhere -- the walk is broken"
        assert dispatch_audits == set(self.AUDITED_BY_DISPATCH.values()), (
            f"write_guard._run_main must audit each dispatch-audited check under its "
            f"tool label; saw {sorted(dispatch_audits)}"
        )
        assert not offenders, "unclassified bare emitter site(s):\n  " + "\n  ".join(offenders)
        stale = sorted(fail_closed - used)
        assert not stale, (
            f"FAIL_CLOSED_REASONS names reasons no bare emitter uses: {stale} -- delete "
            "them; an allowlist that outlives its sites grows without review"
        )

    def test_detector_fires_on_a_synthetic_unclassified_site(self):
        # Earn the red without pinning today's count: a governance-shaped deny
        # in a function nothing audits must be reported.
        src = (
            "def deny(reason):\n"
            "    return 0\n"
            "def check_new_rule(root):\n"
            "    return deny(_denial_reasons.SOME_NEW_GOVERNANCE_RULE)\n"
        )
        sites, offenders, used = _classify_bare_emitters(
            ast.parse(src), "synthetic.py", {"deny"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == 1 and len(offenders) == 1, (sites, offenders)
        assert "check_new_rule" in offenders[0] and not used

    def test_detector_classifies_a_crash_guard_only_when_it_records_on_the_emit_path(self):
        # DEF-803: an internal-error emit with no record beside it is an
        # offender; the same emit with its ``*_blocked_internal_error``
        # record written on the emit's path is classified.
        bare = (
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n"
        )
        audited = (
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "    return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n"
        )
        sites, offenders, _used = _classify_bare_emitters(
            ast.parse(bare), "synthetic.py", {"deny"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == 1 and len(offenders) == 1 and "crash-guard" in offenders[0], offenders
        sites, offenders, _used = _classify_bare_emitters(
            ast.parse(audited), "synthetic.py", {"deny"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == 1 and offenders == [], offenders

    def test_a_second_crash_guard_arm_without_its_own_record_is_an_offender(self):
        # DEF-828: the record is keyed on the emit's own path, never on a
        # literal anywhere in the enclosing function. Two arms, one record:
        # the arm that records is classified; the arm that forgot is the
        # offender this census exists to name (the maintainer who adds a
        # second crash-guard arm to config_guard and forgets its record).
        two_arms = (
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except ValueError:\n"
            "        return deny(_denial_reasons.FIRST_ARM_INTERNAL_ERROR)\n"
            "    except Exception:\n"
            "        append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "        return deny(_denial_reasons.SECOND_ARM_INTERNAL_ERROR)\n"
        )
        sites, offenders, _used = _classify_bare_emitters(
            ast.parse(two_arms), "synthetic.py", {"deny"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == 2, sites
        assert len(offenders) == 1, offenders
        # Keyed on the arm's own reason, not a line number: a reflowed
        # synthetic stays green, a classifier that flags the recorded arm reds.
        assert "FIRST_ARM_INTERNAL_ERROR" in offenders[0] and "crash-guard" in offenders[0], offenders

    def test_a_second_kill_switch_arm_without_its_own_record_is_an_offender(self):
        # DEF-828, the kill-switch emitter under the same rule: the record in
        # the first arm's body does not reach the second arm's emit.
        two_arms = (
            "def deny(reason):\n"
            "    return 0\n"
            "def _run_main(data, root):\n"
            "    findings = scan(root)\n"
            "    if findings:\n"
            "        _audit(root, 'pretooluse_blocked_kill_switch', findings=findings)\n"
            "        return deny(_denial_reasons.KILL_SWITCH_DETECTED.format(context='', findings=findings))\n"
            "    local = scan(data['cwd'])\n"
            "    if local:\n"
            "        return deny(_denial_reasons.KILL_SWITCH_DETECTED.format(context=' in cwd', findings=local))\n"
            "    return 0\n"
        )
        sites, offenders, _used = _classify_bare_emitters(
            ast.parse(two_arms), "synthetic.py", {"deny"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == 2, sites
        assert len(offenders) == 1, offenders
        assert "in cwd" in offenders[0] and "kill-switch" in offenders[0], offenders

    OFF_PATH = [
        (
            "record-in-the-try-body-above-the-handler",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "        return _run_main()\n"
            "    except Exception:\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
        ),
        (
            "record-after-the-return-in-the-handler",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except Exception:\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n"
            "        append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n",
        ),
        (
            "record-dead-after-a-return-in-a-preceding-arm",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except Exception:\n"
            "        if quiet:\n"
            "            return 0\n"
            "            append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
        ),
        (
            "record-after-an-if-else-whose-arms-both-return",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except Exception:\n"
            "        if quiet:\n"
            "            return 0\n"
            "        else:\n"
            "            return 1\n"
            "        append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
        ),
    ]

    @pytest.mark.parametrize("shape, src", OFF_PATH, ids=[shape for shape, _ in OFF_PATH])
    def test_a_record_off_the_emit_path_does_not_audit_it(self, shape, src):
        # DEF-828: source order inside the function is not the path. A record
        # in the try body runs before the crash, not on the way to the emit;
        # a record after a return never runs, whether the return is the
        # emit's own, one in a preceding arm, or an if/else whose arms both
        # return (the code review's two driven false greens).
        sites, offenders, _used = _classify_bare_emitters(
            ast.parse(src), "synthetic.py", {"deny"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == 1 and len(offenders) == 1 and "crash-guard" in offenders[0], (shape, offenders)

    ON_PATH = [
        (
            "config-guard-crash-shape-the-record-in-a-nested-try-in-the-handler",
            "def block(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except Exception as exc:\n"
            "        try:\n"
            "            root = _resolve_project_root()\n"
            "        except BaseException:\n"
            "            root = Path('.')\n"
            "        try:\n"
            "            append_audit(root, {'event_type': 'configchange_blocked_internal_error', 'details': {}}, quiet=True)\n"
            "        except Exception:\n"
            "            pass\n"
            "        return block(_denial_reasons.CONFIG_GUARD_INTERNAL_ERROR)\n",
            1,
        ),
        (
            "a-record-above-a-nested-if-in-the-handler-reaches-both-emits",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except BaseException as exc:\n"
            "        append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "        if isinstance(exc, KeyboardInterrupt):\n"
            "            return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
            2,
        ),
        (
            "config-guard-kill-switch-shape-the-literal-bound-to-a-local-on-the-path",
            "def block(reason):\n"
            "    return 0\n"
            "def _run_main(source, findings):\n"
            "    audit_event = (\n"
            "        'configchange_blocked_kill_switch'\n"
            "        if source not in AUDIT_ONLY_SOURCES\n"
            "        else 'configchange_policy_settings_kill_switch_detected'\n"
            "    )\n"
            "    try:\n"
            "        append_audit(root, {'event_type': audit_event, 'details': {'findings': findings}})\n"
            "    except Exception:\n"
            "        pass\n"
            "    if source in AUDIT_ONLY_SOURCES:\n"
            "        return 0\n"
            "    return block(_denial_reasons.KILL_SWITCH_DETECTED.format(context='', findings=findings))\n",
            1,
        ),
        (
            "a-flag-guarded-record-in-the-shared-finally-reaches-both-arms",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    crashed = False\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except ValueError:\n"
            "        crashed = True\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n"
            "    except Exception:\n"
            "        crashed = True\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n"
            "    finally:\n"
            "        if crashed:\n"
            "            append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n",
            2,
        ),
        (
            "a-conditional-record-above-the-emit-is-accepted-block-prefix-not-control-flow",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except Exception:\n"
            "        if _audit_enabled():\n"
            "            append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
            1,
        ),
        (
            "a-record-in-a-retry-loop-after-a-continue-survives-past-the-loop",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    try:\n"
            "        return _run_main()\n"
            "    except Exception:\n"
            "        for candidate in roots:\n"
            "            if not writable(candidate):\n"
            "                continue\n"
            "            append_audit(candidate, {'event_type': 'pretooluse_blocked_internal_error'})\n"
            "            break\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
            1,
        ),
        (
            "a-record-in-the-enclosing-header-reaches-the-emit",
            "def deny(reason):\n"
            "    return 0\n"
            "def main():\n"
            "    if append_audit(root, {'event_type': 'pretooluse_blocked_internal_error'}):\n"
            "        return deny(_denial_reasons.NEW_HOOK_INTERNAL_ERROR)\n",
            1,
        ),
    ]

    @pytest.mark.parametrize("shape, src, emits", ON_PATH, ids=[shape for shape, _, _ in ON_PATH])
    def test_a_record_on_the_emit_path_audits_every_emit_it_reaches(self, shape, src, emits):
        # Two live shapes and four generalizations, as synthetic twins so a
        # refactor of the hook cannot move the pin: config_guard's crash
        # guard records inside a nested try in its handler, and its
        # kill-switch binds the event to a local before the record (live);
        # a record above a nested if reaches both emits below it; a
        # flag-guarded record in the try's finally reaches every arm (the
        # de-duplication a maintainer would reach for); a record under a
        # condition above the emit is accepted -- the rule is block-prefix,
        # not control flow, and this row is that decision; a record before a
        # continue in a retry loop survives past the loop, which is why a
        # continue is not a terminator; and a record written in the header
        # of the compound statement around the emit is on its path (the
        # shared ascent's headers, taken by this census with the lift).
        # None is an offender.
        sites, offenders, _used = _classify_bare_emitters(
            ast.parse(src), "synthetic.py", {"deny", "block"}, self._fail_closed(), frozenset(self.AUDITED_BY_DISPATCH)
        )
        assert len(sites) == emits and offenders == [], (shape, offenders)


class TestAuditWriterRosterIsBacked:
    """``_AUDIT_WRITERS`` is the one hand-kept name set in the bare-emitter
    census, and under the path rule the writer's NAME is all that marks a
    record: the cheapest green for a hook that records through its own
    wrapper is one more name on the roster. Every name must reach the log."""

    def test_every_roster_name_is_defined_in_a_hook_and_reaches_the_writer(self):
        assert _unbacked_audit_writers(_AUDIT_WRITERS, _hook_trees()) == []

    def test_a_name_no_hook_defines_or_a_wrapper_that_records_nothing_is_refused(self):
        trees = _hook_trees()
        assert _unbacked_audit_writers(_AUDIT_WRITERS | {"_note"}, trees) == [
            "_note is on the writer roster but no hook defines it"
        ]
        trees["synthetic.py"] = ast.parse("def _note(root, event_type):\n    print(event_type)\n")
        assert _unbacked_audit_writers(_AUDIT_WRITERS | {"_note"}, trees) == [
            "synthetic.py::_note calls no other roster writer -- it cannot reach the log"
        ]


class TestSpeedBumpFireIsGuarded:
    """A fault in the speed-bump helper at the write_guard call boundary fails
    toward allow -- the helper's own contract on every internal path -- and
    never reaches main()'s crash guard, which would deny every tool call
    including the Bash that could repair it (observed 2026-09-08 with a
    sibling module one step behind)."""

    def test_a_raising_check_fired_allows_the_call(self, tmp_path, capsys, monkeypatch):
        wg = _load_hook_module("write_guard")
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)

        def _skewed_sibling(*_a, **_k):
            raise AttributeError("module '_speedbump' has no attribute 'check_fired'")

        monkeypatch.setattr(wg._speedbump, "check_fired", _skewed_sibling)
        monkeypatch.setattr(
            wg._hook_utils, "read_stdin_safely",
            lambda: {"tool_name": "Bash", "tool_input": {"command": "echo ok"}},
        )
        monkeypatch.setattr(wg, "_resolve_project_root", lambda: tmp_path)
        rc = wg._run_main()
        captured = capsys.readouterr()
        assert rc == 0 and not rc, "a helper fault must fall through to allow, not deny"
        assert "permissionDecision" not in captured.out, captured.out
        assert "internal error" not in captured.out.lower()

    def test_a_raising_snapshot_allows_the_call(self, tmp_path, capsys, monkeypatch):
        """The 2026-09-08 fix's missed sibling, one call above it: the discard
        snapshot's own try covers git, not a name the module no longer has,
        and on 2026-09-13 a half-landed rename inside it raised before that
        try and wedged every mutating tool call (Edit and Write included, so
        nothing in the session could repair it). RED at HEAD: the call was
        unguarded and this deny reached stdout."""
        wg = _load_hook_module("write_guard")
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)

        def _half_landed_rename(*_a, **_k):
            raise NameError("name '_discard_texts' is not defined")

        monkeypatch.setattr(wg._speedbump, "snapshot_discard", _half_landed_rename)
        monkeypatch.setattr(
            wg._hook_utils, "read_stdin_safely",
            lambda: {"tool_name": "Edit", "tool_input": {"file_path": "notes.md"}},
        )
        monkeypatch.setattr(wg, "_resolve_project_root", lambda: tmp_path)
        rc = wg._run_main()
        captured = capsys.readouterr()
        assert rc == 0 and not rc, "a snapshot fault must fall through to allow, not deny"
        assert "permissionDecision" not in captured.out, captured.out
        assert "internal error" not in captured.out.lower()


class TestNoHookCallsTheReasonOnlySpeedBumpView:
    """``_speedbump.check`` reports a fire with no checkpoint id, so a hook
    calling it cannot audit the deny -- the residual this row closed. Tests may
    read it; every hook goes through ``check_fired``."""

    @staticmethod
    def _speedbump_calls(tree: ast.AST, attr: str) -> list[int]:
        return [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "_speedbump"
        ]

    def test_no_hook_calls_check_and_write_guard_calls_check_fired(self):
        offenders: list[str] = []
        fired_callers: list[str] = []
        for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
            if hook.name == "_speedbump.py":
                continue
            tree = ast.parse(hook.read_text(encoding="utf-8"))
            offenders += [f"{hook.name}:{ln}" for ln in self._speedbump_calls(tree, "check")]
            if self._speedbump_calls(tree, "check_fired"):
                fired_callers.append(hook.name)
        assert not offenders, f"a hook calls the reason-only _speedbump.check: {offenders}"
        assert fired_callers == ["write_guard.py"], fired_callers


class TestProtectedZoneDenialsAreAudited:
    """Enumeration-integrity contract (TP-330): every protected-zone denial in
    write_guard must route through ``_audit_deny`` — never a bare ``deny(...)``
    — so a future protected-zone site can't silently skip the audit log. The
    reference set is the ``PROTECTED_ZONE_*`` reason family (canon-derived): a
    newly-added protected-zone reason auto-joins the contract."""

    def test_no_protected_zone_reason_via_bare_deny(self):
        import ast

        src = (REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        # A reason bound from `_zone_reason` is a protected-zone reason too: the
        # adopter arms (DEF-995) and the full-template channels deny with one, and
        # a bare deny(reason) of it would leave the log as surely as a template's.
        # Bound per function: `reason` is a common name, and only the function
        # that bound it from `_zone_reason` denies a zone with it.
        zone_reason_at: dict[int, str] = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            bound = {
                target.id
                for node in ast.walk(fn)
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "_zone_reason"
                for target in node.targets if isinstance(target, ast.Name)
            }
            for call in ast.walk(fn):
                if isinstance(call, ast.Call):
                    for arg in ast.walk(call):
                        if isinstance(arg, ast.Name) and arg.id in bound:
                            zone_reason_at[id(call)] = arg.id

        def _mentions_protected_zone(node: ast.AST) -> bool:
            return id(node) in zone_reason_at or any(
                isinstance(a, ast.Attribute) and a.attr.startswith("PROTECTED_ZONE")
                for a in ast.walk(node)
            )

        assert zone_reason_at, "no call denies with a `_zone_reason` result: did the zone deny's shape change?"
        offenders: list[int] = []
        audited = 0
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "deny" and _mentions_protected_zone(call):
                offenders.append(call.lineno)
            if name == "_audit_deny" and _mentions_protected_zone(call):
                audited += 1

        assert not offenders, (
            f"write_guard.py has bare deny(PROTECTED_ZONE_*) at line(s) {offenders} "
            "-- route every protected-zone denial through _audit_deny so it reaches "
            "the ~/.espalier/audit log (TP-330 completeness contract)."
        )
        assert audited >= 10, (
            f"expected >=10 protected-zone denials routed via _audit_deny, found "
            f"{audited} -- did the audit routing regress?"
        )


# ---------------------------------------------------------------------------
# Ledger row DEF-723: the Stop hook's gate blocks reach the log. A gate block
# is once-then-continue (the protocol's loop signal lets the next Stop
# through), and until this row it wrote no record, so ``/status --log`` could
# not say why a session was returned. Each gate lands one record, typed per
# gate, carrying the gate number, the rule constant and the write count --
# never the reason text (a pytest tail can carry paths and file lines).
# ---------------------------------------------------------------------------


def _load_stop_gate():
    """``_load_hook_module`` for the Stop hook. Registered in ``sys.modules``
    BEFORE exec: the hook's ``@dataclass`` under ``from __future__ import
    annotations`` resolves its field types through ``sys.modules[__module__]``
    and raises on an unregistered module (the shape ``tests/test_stop_gate.py``
    uses for the same reason)."""
    import importlib.util

    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    name = "stop_gate_audit_under_test"
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / "stop_gate.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_stop_hook(tmp_path: Path, **env_overrides: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        timeout=30,
        env=env, encoding="utf-8",
    )


class TestStopGateBlocksReachTheLog:
    def test_the_override_gate_block_lands_a_pytest_record_end_to_end(self, tmp_path, monkeypatch):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        monkeypatch.setenv(
            "ESPALIER_STOP_GATE_TEST_CMD",
            f'"{sys.executable}" -c "import sys; sys.exit(3)"',
        )
        result = _run_stop_hook(tmp_path, ESPALIER_STOP_GATE="full")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["decision"] == "block"
        records = [r for r in _audit_records() if r["event_type"] == "stop_blocked_pytest"]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        assert records[0]["details"] == {
            "gate": 1, "rule": "GATE_COMMAND_FAILED", "returncode": 3, "source": "env",
        }
        assert records[0]["repo_path"] == str(tmp_path.resolve())

    def test_an_override_that_cannot_start_lands_a_record_naming_the_rule(self, tmp_path, monkeypatch):
        """It wrote nothing: the spawn failure was an allow, and only a block
        is recorded, so the log could not show a gate that had stopped
        running. Metadata only, as every record: the rule and the exception's
        class, never the command text."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        monkeypatch.setenv("ESPALIER_STOP_GATE_TEST_CMD", "espalier-no-such-command-xyz --run")
        result = _run_stop_hook(tmp_path, ESPALIER_STOP_GATE="full")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["decision"] == "block"
        records = [r for r in _audit_records() if r["event_type"] == "stop_blocked_pytest"]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        # Since the chokepoint (2026-09-30) argv[0] is resolved before any spawn:
        # a program that is not on PATH is `Unresolved`, the resolver's own class,
        # and never reaches the OSError the spawn used to raise.
        assert records[0]["details"] == {
            "gate": 1, "rule": "GATE_COMMAND_SPAWN_FAILED", "error": "Unresolved", "source": "env",
        }
        assert "espalier-no-such-command-xyz" not in json.dumps(records[0])

    def test_gate_two_and_three_blocks_land_typed_records_with_the_rule(self, tmp_path, capsys):
        sg = _load_stop_gate()
        assert sg._gate_docs_refresh(tmp_path, 10) == 1
        assert sg._gate_code_review(tmp_path, 10) == 1
        out = capsys.readouterr()
        decisions = [json.loads(ln) for ln in out.out.splitlines() if ln.strip()]
        assert [d["decision"] for d in decisions] == ["block", "block"]
        assert out.err == "", out.err
        by_type = {
            r["event_type"]: r for r in _audit_records() if r["event_type"].startswith("stop_")
        }
        assert by_type["stop_blocked_docs_refresh"]["details"] == {
            "gate": 2, "rule": "GATE_DOCS_REFRESH_NEEDED", "write_count": 10,
        }
        assert by_type["stop_blocked_code_review"]["details"] == {
            "gate": 3, "rule": "GATE_CODE_REVIEW_BLOCK", "write_count": 10,
        }

    def test_a_short_session_passes_the_hygiene_gates_and_writes_nothing(self, tmp_path, capsys):
        sg = _load_stop_gate()
        assert sg._gate_docs_refresh(tmp_path, 3) == 0
        assert sg._gate_code_review(tmp_path, 3) == 0
        assert capsys.readouterr().out == ""
        assert [r for r in _audit_records() if r["event_type"].startswith("stop_")] == []

    def test_the_block_funnel_blocks_whether_or_not_the_record_lands(self, tmp_path, capsys, monkeypatch):
        sg = _load_stop_gate()

        def _raise(*_a, **_k):
            raise RuntimeError("sink down")

        monkeypatch.setattr(sg._integrity, "append_audit", _raise)
        assert sg._gate_code_review(tmp_path, 10) == 1
        out = capsys.readouterr()
        assert json.loads(out.out)["decision"] == "block"
        assert out.err == "", "a failing record write must not put text on the block path"
        assert [r for r in _audit_records() if r["event_type"].startswith("stop_")] == []

    def test_the_record_carries_no_reason_text(self, tmp_path, capsys):
        # The reason the operator sees can quote a pytest tail; the record is
        # metadata only, like every other row in the log.
        sg = _load_stop_gate()
        assert sg._gate_docs_refresh(tmp_path, 10) == 1
        capsys.readouterr()
        rec = next(r for r in _audit_records() if r["event_type"] == "stop_blocked_docs_refresh")
        assert set(rec["details"]) == {"gate", "rule", "write_count"}
        assert all(isinstance(v, (int, str)) for v in rec["details"].values())

    def test_a_crash_lands_an_internal_error_record_with_the_exception_class(
        self, tmp_path, capsys, monkeypatch
    ):
        """DEF-803: the crash guard's block was the one block outside the funnel
        (three Stop blocks on the Windows host 2026-09-14, two in the log). It
        now records the internal-error rule and the exception's class -- never
        the message, which can quote a path -- and still re-blocks with exit 0
        and the stderr line."""
        sg = _load_stop_gate()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setattr(sg, "_gate_finalize_blueprint", lambda *a, **k: None)

        def _boom():
            raise AttributeError("simulated internal crash at /secret/path")

        monkeypatch.setattr(sg, "_run_main", _boom)
        assert sg.main() == 0
        out = capsys.readouterr()
        assert json.loads(out.out)["decision"] == "block"
        assert "[ERROR] stop_gate crashed: AttributeError" in out.err
        records = [r for r in _audit_records() if r["event_type"] == "stop_blocked_internal_error"]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        assert records[0]["details"] == {"rule": "STOP_GATE_INTERNAL_ERROR", "error": "AttributeError"}
        assert records[0]["repo_path"] == str(tmp_path.resolve())
        assert "secret" not in json.dumps(records[0])

    def test_a_crash_while_resolving_the_root_still_blocks_and_records(self, capsys, monkeypatch):
        # The record and Gate 4 both want a root, and the crash may have been
        # in resolving it: the guard falls back to the cwd the resolver would
        # have used and never masks the block.
        sg = _load_stop_gate()
        monkeypatch.setattr(sg, "_gate_finalize_blueprint", lambda *a, **k: None)

        def _boom(*_a, **_k):
            raise RuntimeError("root resolution failed")

        monkeypatch.setattr(sg, "_run_main", _boom)
        monkeypatch.setattr(sg, "_resolve_project_root", _boom)
        assert sg.main() == 0
        out = capsys.readouterr()
        assert json.loads(out.out)["decision"] == "block"
        records = [r for r in _audit_records() if r["event_type"] == "stop_blocked_internal_error"]
        assert [r["details"] for r in records] == [{"rule": "STOP_GATE_INTERNAL_ERROR", "error": "RuntimeError"}]
        assert records[0]["repo_path"] == str(Path.cwd().resolve())

    def test_every_funnel_call_site_carries_only_metadata_keywords(self):
        # The spot-check above covers one site; this pins all of them: the
        # details are metadata keys only, each a literal, a name or an
        # attribute -- never a ``.format(...)`` (the reason text) or a call.
        tree = ast.parse((HOOKS_DIR / "stop_gate.py").read_text(encoding="utf-8"))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _call_name(n) == "_audit_block"
        ]
        assert len(calls) >= 9, f"expected every gate site and the crash guard, found {len(calls)}"
        # ``error`` is an exception's CLASS, as on the crash guard below: the
        # override that could not be started records which OSError it met,
        # never the message, which can carry a path.
        # ``source`` is one of three fixed words (env, espalier.toml, fingerprint):
        # where Gate 1's command came from, never the command itself.
        # ``ahead`` is Gate 5's count of commits the upstream lacks: an
        # integer, never the branch name or the plan's title.
        allowed = {"gate", "rule", "write_count", "returncode", "error", "source", "ahead"}
        for call in calls:
            text = ast.unparse(call)
            assert len(call.args) == 3, text  # root, event_type, reason
            assert isinstance(call.args[1], ast.Constant), text  # the type, inline for discovery
            names = {kw.arg for kw in call.keywords}
            if call.args[1].value == "stop_blocked_internal_error":
                # The crash guard (DEF-803): no gate was reached; ``rule`` is the
                # internal-error reason's name and ``error`` the exception's class.
                assert names == {"rule", "error"}, text
            else:
                assert {"gate", "rule"} <= names <= allowed, text
            for kw in call.keywords:
                assert isinstance(kw.value, (ast.Constant, ast.Name, ast.Attribute)), text

    def test_the_funnel_stays_silent_when_the_audit_dir_cannot_be_created(self, tmp_path, capsys, monkeypatch):
        # A REAL OSError inside the writer (its own branch warns on stderr
        # unless told to stay quiet), not a monkeypatched raise: the audit
        # dir is asked for under a file.
        (tmp_path / "blocker").write_text("not a directory\n", encoding="utf-8")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "blocker" / "audit"))
        sg = _load_stop_gate()
        assert sg._gate_code_review(tmp_path, 10) == 1
        out = capsys.readouterr()
        assert json.loads(out.out)["decision"] == "block"
        assert out.err == "", out.err
        # The stressor fired: nothing could be created under the file.
        assert not Path(os.environ["ESPALIER_AUDIT_DIR"]).exists()


# ---------------------------------------------------------------------------
# Ledger row DEF-724: the tail tiers pauses from refusals. The default view
# shows the refusals; the pauses are counted on their own line for the day so
# a window of N can never lose one without a trace; ``--all`` widens the tail.
# ---------------------------------------------------------------------------


class TestStatusLogTiers:
    @staticmethod
    def _arm_one_refusal_and_one_pause(tmp_path: Path) -> None:
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}},
            tmp_path,
        )
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            tmp_path,
        )

    def test_default_tail_shows_refusals_and_counts_pauses_on_their_own_line(self, tmp_path):
        self._arm_one_refusal_and_one_pause(tmp_path)
        result = _run_status_log(tmp_path, "10")
        assert result.returncode == 0, result.stderr
        header, by_type, pauses, *records = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert header.startswith("# governance audit log -- last 1 of 1 denial record "), header
        assert "pretooluse_blocked_dangerous_command 1" in by_type, by_type
        assert re.match(rf"# pauses {_WINDOW}: ", pauses), pauses
        assert "pretooluse_blocked_speed_bump 1" in pauses and "--all" in pauses, pauses
        assert len(records) == 1 and "speed_bump" not in records[0], records
        assert result.stdout.isascii()

    def test_all_widens_the_tail_to_the_pauses(self, tmp_path):
        self._arm_one_refusal_and_one_pause(tmp_path)
        result = _run_status_log(tmp_path, "10", "--all")
        assert result.returncode == 0, result.stderr
        header, by_type, *records = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert header.startswith("# governance audit log -- last 2 of 2 blocked records"), header
        assert "pretooluse_blocked_speed_bump 1" in by_type and "pretooluse_blocked_dangerous_command 1" in by_type
        assert sum("pretooluse_blocked_speed_bump" in ln for ln in records) == 1, records
        assert len(records) == 2, records

    def test_a_day_of_only_pauses_is_named_instead_of_reported_as_nothing(self, tmp_path):
        _run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}},
            tmp_path,
        )
        result = _run_status_log(tmp_path, "10")
        assert result.returncode == 0, result.stderr
        assert re.match(rf"\(no governance denials recorded for this repo {_WINDOW}", result.stdout), result.stdout
        assert re.search(rf"1 pause record {_WINDOW}", result.stdout) and "--all" in result.stdout, result.stdout

    def test_all_without_log_is_a_usage_error(self, tmp_path):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"), "--all"],
            cwd=str(tmp_path), capture_output=True, text=True, timeout=15, env=env, encoding="utf-8",
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "--all: requires --log" in result.stderr, result.stderr



_BYPASS_EVENT_RE = re.compile(r"[a-z0-9]+_bypassed_[a-z0-9_]+")


def _emitted_bypass_event_types() -> set[str]:
    """Every ``<event>_bypassed_<what>`` literal that reaches an audit writer in
    any hook -- the same derivation as the blocked types, on the bypass shape."""
    found: set[str] = set()
    for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
        if hook.name == "_integrity.py":
            continue
        tree = ast.parse(hook.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _call_name(node) in _AUDIT_WRITERS):
                continue
            found |= {
                c.value for c in ast.walk(node)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
                and _BYPASS_EVENT_RE.fullmatch(c.value)
            }
    return found


class TestMaintenanceBypassIsRecorded:
    """DEF-789: under ``ESPALIER_MAINTENANCE_MODE=1`` each hook the flag
    switches a check off in -- write_guard (protected zone), plan_guard (plan
    required), stop_gate (Gates 2 and 3) -- lands ONE advisory record per
    session, so ``--log`` can say the floor was bypassed instead of reading a
    bypassed day as a clean one. The records are in neither tier (nothing was
    blocked): never in the tail, counted on their own line."""

    _STOP = "stop_bypassed_maintenance_mode"
    _PRE = "pretooluse_bypassed_maintenance_mode"

    @staticmethod
    def _run(script: str, payload: dict, tmp_path: Path, *, maintenance: bool) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("ESPALIER_MAINTENANCE_MODE", None)
        env.pop("ESPALIER_STOP_GATE", None)  # Gate 1 stays opt-in; light mode
        if maintenance:
            env["ESPALIER_MAINTENANCE_MODE"] = "1"
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        return not_a_budget_miss(subprocess.run(
            [sys.executable, str(HOOKS_DIR / script)],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=45, env=env, encoding="utf-8",
        ))

    def _run_stop(self, tmp_path: Path, *, maintenance: bool) -> subprocess.CompletedProcess:
        return self._run("stop_gate.py", {"stop_hook_active": False}, tmp_path, maintenance=maintenance)

    def _records(self, event_type: str, hook: str | None = None) -> list[dict]:
        return [
            r for r in _audit_records()
            if r["event_type"] == event_type and (hook is None or r["details"].get("hook") == hook)
        ]

    def test_first_stop_under_maintenance_lands_one_record_per_session(self, tmp_path):
        first = self._run_stop(tmp_path, maintenance=True)
        assert first.returncode == 0, first.stderr
        assert "MAINTENANCE_MODE" in first.stderr  # the stderr line still fires
        records = self._records(self._STOP)
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        # metadata only: which hook, which gates, how long the session was -- never text
        assert set(records[0]["details"]) == {"hook", "gates", "write_count"}
        assert records[0]["details"]["hook"] == "stop_gate" and records[0]["details"]["gates"] == "2,3"
        assert (tmp_path / ".espalier-state" / "maintenance_bypass_recorded_stop_gate").exists()
        second = self._run_stop(tmp_path, maintenance=True)
        assert second.returncode == 0, second.stderr
        assert len(self._records(self._STOP)) == 1, "a second Stop must not record again"

    def test_write_guard_records_its_protected_zone_bypass_once(self, tmp_path):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/x.py", "content": ""}}
        first = self._run("write_guard.py", payload, tmp_path, maintenance=True)
        assert first.returncode == 0 and first.stdout.strip() == "", (first.stdout, first.stderr)
        records = self._records(self._PRE, "write_guard")
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        assert records[0]["details"] == {"hook": "write_guard", "check": "protected-zone"}
        assert (tmp_path / ".espalier-state" / "maintenance_bypass_recorded_write_guard").exists()
        second = self._run("write_guard.py", payload, tmp_path, maintenance=True)
        assert second.returncode == 0 and second.stdout.strip() == ""
        assert len(self._records(self._PRE, "write_guard")) == 1

    def test_plan_guard_records_its_plan_required_bypass_once(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py", "old_string": "x", "new_string": "y"}}
        first = self._run("plan_guard.py", payload, tmp_path, maintenance=True)
        assert first.returncode == 0 and first.stdout.strip() == "", (first.stdout, first.stderr)
        records = self._records(self._PRE, "plan_guard")
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        assert records[0]["details"] == {"hook": "plan_guard", "check": "plan-required"}
        assert (tmp_path / ".espalier-state" / "maintenance_bypass_recorded_plan_guard").exists()
        second = self._run("plan_guard.py", payload, tmp_path, maintenance=True)
        assert second.returncode == 0 and second.stdout.strip() == ""
        assert len(self._records(self._PRE, "plan_guard")) == 1

    def test_no_record_without_maintenance_mode(self, tmp_path):
        assert self._run_stop(tmp_path, maintenance=False).returncode == 0
        self._run("write_guard.py", {"tool_name": "Read", "tool_input": {"file_path": "README.md"}}, tmp_path, maintenance=False)
        self._run("plan_guard.py", {"tool_name": "Read", "tool_input": {"file_path": "README.md"}}, tmp_path, maintenance=False)
        assert [r for r in _audit_records() if "_bypassed_" in r["event_type"]] == []
        assert not list((tmp_path / ".espalier-state").glob("maintenance_bypass_recorded_*")) if (tmp_path / ".espalier-state").is_dir() else True

    def test_the_written_set_equals_the_readers_set_and_sits_in_neither_tier(self):
        integ = _load_hook_module("_integrity")
        emitted = _emitted_bypass_event_types()
        assert emitted == {self._STOP, self._PRE}, sorted(emitted)
        assert set(integ.MAINTENANCE_BYPASS_EVENT_TYPES) == emitted
        assert not (set(integ.MAINTENANCE_BYPASS_EVENT_TYPES) & set(integ.BLOCKED_EVENT_TYPES))
        # A rename to a `_blocked_` spelling would pull a bypass into the tier
        # union and the tail; the advisory shape is pinned by the tier regex.
        assert not any(_BLOCKED_EVENT_RE.fullmatch(t) for t in emitted)
        # The three writers, by name -- one per hook the flag switches a check off in.
        writers = {
            hook.stem for hook in checkout_glob(HOOKS_DIR, "*.py")
            if hook.name != "_integrity.py" and "_bypassed_maintenance_mode" in hook.read_text(encoding="utf-8")
        }
        assert writers == {"write_guard", "plan_guard", "stop_gate"}, sorted(writers)

    def test_status_log_counts_every_hooks_bypass_on_its_own_line_and_keeps_them_out_of_the_tail(self, tmp_path):
        assert self._run_stop(tmp_path, maintenance=True).returncode == 0
        self._run("write_guard.py", {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/x.py", "content": ""}}, tmp_path, maintenance=True)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
        self._run("plan_guard.py", {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py", "old_string": "", "new_string": "x"}}, tmp_path, maintenance=True)
        plain = _run_status_log(tmp_path, "10")
        assert plain.returncode == 0, plain.stderr
        assert re.search(rf"3 maintenance-bypass records {_WINDOW}", plain.stdout), plain.stdout
        for phrase in ("write_guard (protected-zone check) 1", "plan_guard (plan requirement) 1", "stop_gate (Gates 2 and 3) 1"):
            assert phrase in plain.stdout, plain.stdout
        # Never a tail record: no type name is printed as a record line.
        assert self._STOP not in plain.stdout and self._PRE not in plain.stdout
        widened = _run_status_log(tmp_path, "10", "--all")
        assert widened.returncode == 0, widened.stderr
        assert self._STOP not in widened.stdout and self._PRE not in widened.stdout


# ---------------------------------------------------------------------------
# Ledger row DEF-803, the class: every fail-closed crash guard writes its
# record before it emits. The PreToolUse pair share one type and name the
# hook; the ConfigChange hook has no funnel and writes inline; a record that
# cannot be written puts nothing on stderr beside the decision JSON.
# ---------------------------------------------------------------------------


def _crash_guard_writers() -> list[tuple[str, str]]:
    """``(hook, event_type)`` for every hook whose source writes a
    ``*_blocked_internal_error`` record -- derived from the tree, so a fifth
    blocking hook joins the proof the moment it copies a crash guard, and the
    ``hook=`` literal it copied is checked against its own file name."""
    out: list[tuple[str, str]] = []
    for hook in sorted(checkout_glob(HOOKS_DIR, "*.py")):
        if hook.name == "_integrity.py":
            continue
        found = sorted(set(re.findall(r'"([a-z]+_blocked_internal_error)"', hook.read_text(encoding="utf-8"))))
        out.extend((hook.stem, ev) for ev in found)
    return out


class TestCrashGuardsReachTheLog:
    CASES = _crash_guard_writers()

    def test_the_population_is_every_hook_that_defines_an_emitter(self):
        # Derived both ways: the hooks that write a crash record are exactly
        # the hooks that define a deny/block emitter (the blocking hooks).
        assert {h for h, _ in self.CASES} == {n[:-3] for n in _hooks_defining_an_emitter()}, self.CASES
        assert len(self.CASES) >= 4, self.CASES

    @staticmethod
    def _crash(hook_name: str, exc: BaseException, monkeypatch):
        mod = _load_stop_gate() if hook_name == "stop_gate" else _load_hook_module(hook_name)
        if hasattr(mod, "_gate_finalize_blueprint"):
            monkeypatch.setattr(mod, "_gate_finalize_blueprint", lambda *a, **k: None)

        def _boom(*_a, **_k):
            raise exc

        monkeypatch.setattr(mod, "_run_main", _boom)
        return mod

    @pytest.mark.parametrize("hook_name,event_type", CASES)
    def test_a_crash_lands_a_typed_record_naming_the_hook_and_the_exception_class(
        self, hook_name, event_type, tmp_path, capsys, monkeypatch
    ):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        mod = self._crash(hook_name, AttributeError("simulated crash at /secret/path"), monkeypatch)
        assert mod.main() == 0
        out = capsys.readouterr()
        assert f"[ERROR] {hook_name} crashed: AttributeError" in out.err
        payload = json.loads(out.out)
        assert "internal error" in json.dumps(payload)
        records = [r for r in _audit_records() if r["event_type"] == event_type]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        details = records[0]["details"]
        assert details["error"] == "AttributeError", details
        # The PreToolUse hooks share one type, so the record must say which; a
        # copied crash guard that kept its sister's ``hook=`` literal reds here.
        assert details.get("hook", hook_name) == hook_name, details
        if event_type.startswith("pretooluse_"):
            assert "hook" in details, details
        # write_guard's record also places the fault (DEF-4025): the innermost
        # tools/cc file and its line, a harness path and a number, never the
        # message.
        assert set(details) <= {"hook", "rule", "error", "file", "line"}, details
        assert records[0]["repo_path"] == str(tmp_path.resolve())
        assert "secret" not in json.dumps(records[0])

    @pytest.mark.parametrize("hook_name,event_type", CASES)
    def test_the_record_write_stays_silent_when_the_audit_dir_cannot_be_created(
        self, hook_name, event_type, tmp_path, capsys, monkeypatch
    ):
        # A REAL OSError inside the writer, not a monkeypatched raise: the
        # audit dir is asked for under a file, so the mkdir raises in the
        # writer's own branch, which warns unless told to stay quiet.
        (tmp_path / "blocker").write_text("not a directory\n", encoding="utf-8")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "blocker" / "audit"))
        mod = self._crash(hook_name, RuntimeError("simulated crash"), monkeypatch)
        assert mod.main() == 0
        out = capsys.readouterr()
        assert out.err.strip().splitlines() == [f"[ERROR] {hook_name} crashed: RuntimeError: simulated crash"]
        assert "internal error" in out.out
        # The stressor fired: nothing could be created under the file.
        assert not Path(os.environ["ESPALIER_AUDIT_DIR"]).exists()


class TestFailOpenRecordsReachTheStatusLog:
    """The fail-open-with-voice family (``say_once``): a fault inside a guard
    that ALLOWED, said once a session. Advisory, in neither tier; ``/status
    --log`` counts it on its own line, by hook and type -- the pack's own pass
    criterion, which the 2-A review drove and found unmet (a day whose only
    event was a wedged kill-switch scan printed `no governance denials`)."""

    def test_a_driven_fault_is_counted_on_its_own_line_and_kept_out_of_the_tail(self, tmp_path):
        hu = _load_hook_module("_hook_utils")
        hu._SAID_THIS_PROCESS.clear()
        hu.say_once(tmp_path, "integrity-scan-OSError", "write_guard", "pretooluse_failed_open_integrity_scan",
                    "kill-switch scan failed (OSError)", fault="OSError")
        hu.say_once(tmp_path, "zone-protected_paths", "write_guard", "config_zone_ignored",
                    "protected_paths must be a list")
        plain = _run_status_log(tmp_path, "10")
        assert plain.returncode == 0, plain.stderr
        assert re.search(rf"2 voice-only records {_WINDOW}", plain.stdout), plain.stdout
        assert "write_guard: config_zone_ignored 1, pretooluse_failed_open_integrity_scan 1" in plain.stdout, plain.stdout
        assert "a fault inside a guard that allowed" in plain.stdout
        # Never a tail record, never a denial count.
        assert "no governance denials recorded" in plain.stdout

    def test_the_family_is_a_predicate_not_a_roster(self):
        integ = _load_hook_module("_integrity")
        assert integ.is_fail_open_event("stop_failed_open_pytest_spawn")
        assert integ.is_fail_open_event("config_zone_unreadable")
        assert not integ.is_fail_open_event("pretooluse_blocked_protected_zone")
        assert not integ.is_fail_open_event("pretooluse_bypassed_maintenance_mode")
        assert not integ.is_fail_open_event(None)
        # Every type that reaches say_once -- a literal, a keyword, or a
        # wrapper's parameter (say_crash, say_bad_stdin,
        # post_write_check._say_once_to_claude) -- is fail-open, or a
        # channelled advisory that reaches it through _say_once_to_claude,
        # which tells Claude before say_once records. Read through the census
        # (DEF-3093): the pin read only a literal fourth argument of a direct
        # call, so the wrapper's two types passed unread.
        census = _live_audit_census()
        reaching = census.domain_of("_hook_utils.py", "say_once", "event_type")
        told = census.domain_of("post_write_check.py", "_say_once_to_claude", "event_type")
        assert census.unread == []
        assert len(reaching) >= 60, f"discovery floor: found only {sorted(reaching)}"
        channelled = getattr(integ, "CHANNELLED_ADVISORY_EVENT_TYPES", frozenset())
        assert [t for t in sorted(reaching)
                if not (integ.is_fail_open_event(t) or (t in channelled and t in told))] == []


# ---------------------------------------------------------------------------
# Ledger row DEF-1152: a record that is a hook's only voice reaches the
# operator past its UTC day -- the next SessionStart names what was written
# since the previous start, and `/status --log` counts the family (the policy
# kill switch included) over two UTC days.
# ---------------------------------------------------------------------------

_POLICY = "configchange_policy_settings_kill_switch_detected"


def _voice_types_the_hooks_write() -> set[str]:
    """Every event-type literal in the hooks the voice-only predicate admits
    (a prefix token such as ``config_zone_`` left out by its trailing ``_``)."""
    integ = _load_hook_module("_integrity")
    found: set[str] = set()
    for hook in checkout_glob(HOOKS_DIR, "*.py"):
        if hook.name == "_integrity.py":
            continue
        for lit in re.findall(r'"([a-z][a-z0-9_]*[a-z0-9])"', hook.read_text(encoding="utf-8")):
            if integ.is_voice_only_event(lit):
                found.add(lit)
    return found


def _record(root: Path, when, event_type: str, **details) -> dict:
    return {"timestamp": when.isoformat() if hasattr(when, "isoformat") else when,
            "event_type": event_type, "repo_path": str(Path(root).resolve()), "details": details}


def _write_log(integ, root: Path, day, records: list[dict], *, filler: int = 0, noise_at=None) -> Path:
    """Write ``records`` into ``root``'s log for ``day``, after ``filler``
    bytes of advisory lines stamped ``noise_at`` (default ``day``) when asked
    (the shape a busy day's log has)."""
    path = integ.audit_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    noise = json.dumps(_record(root, noise_at or day, "action_justification_missing", tool="Bash"))
    while sum(len(ln) + 1 for ln in lines) < filler:
        lines.append(noise)
    lines += [json.dumps(r) for r in records]
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(ln + "\n" for ln in lines))
    return path


class TestVoiceOnlyRecordsOutliveTheirDay:
    """DEF-1152. The family is declared once (``_integrity.is_voice_only_event``:
    the fail-open predicate plus ``VOICE_ONLY_EVENT_TYPES``), and both readers
    select by it. Each reader is fed the records it must leave out, not only
    the ones it must name (docs/SHARP_EDGES.md, a property-pinning test that
    feeds only conforming inputs)."""

    def test_the_family_is_the_fail_open_predicate_plus_declared_types_a_hook_writes(self):
        integ = _load_hook_module("_integrity")
        assert integ.is_voice_only_event(_POLICY)
        assert integ.is_voice_only_event("stop_failed_open_pytest_did_not_run")
        assert integ.is_voice_only_event("config_zone_unreadable")
        assert not integ.is_voice_only_event("pretooluse_blocked_protected_zone")
        assert not integ.is_voice_only_event("pretooluse_bypassed_maintenance_mode")
        assert not integ.is_voice_only_event("configchange_blocked_kill_switch")
        assert not integ.is_voice_only_event(None)
        declared = set(integ.VOICE_ONLY_EVENT_TYPES)
        # A declared type is one the predicate would not already admit, in
        # neither block tier, and written by a hook (no dead entry).
        assert not any(integ.is_fail_open_event(t) for t in declared), sorted(declared)
        assert not declared & set(integ.BLOCKED_EVENT_TYPES), sorted(declared)
        assert declared <= _voice_types_the_hooks_write(), sorted(declared - _voice_types_the_hooks_write())

    def test_status_log_names_a_policy_kill_switch_config_guard_recorded(self, tmp_path, monkeypatch):
        """Driven through config_guard itself, so the record's own shape is
        read: the type `/status --log` showed in no line before, now counted
        under the hook that wrote it. Dies to: a reader without the policy
        type, or a record without its hook."""
        home = tmp_path / "home"
        home.mkdir()
        # The hook's HOME is this folder, and the audit store's override is
        # accepted only under the home or (TMPDIR unset) the temp dir: where
        # TMPDIR is set, as on CI, the suite's store fell outside both and the
        # record went to this home's default store. One store under it serves
        # the hook and every reader below.
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(home / ".espalier" / "audit"))
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
        result = run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange", "source": "policy_settings", "file_path": ".claude/settings.json"},
            {"ESPALIER_MAINTENANCE_MODE": None, "CLAUDE_PROJECT_DIR": str(tmp_path),
             "HOME": str(home), "USERPROFILE": str(home)},
        )
        assert result.returncode == 0 and not result.stdout.strip(), (result.stdout, result.stderr)
        assert [r["details"].get("hook") for r in _audit_records() if r["event_type"] == _POLICY] == ["config_guard"]
        plain = _run_status_log(tmp_path, "10")
        assert plain.returncode == 0, plain.stderr
        assert re.search(rf"1 voice-only record {_WINDOW} -- config_guard: {_POLICY} 1", plain.stdout), plain.stdout
        assert "kill switch in managed policy settings" in plain.stdout and plain.stdout.isascii()

    def test_the_since_reader_selects_by_family_root_and_time_not_by_date(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        now = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
        since = now - timedelta(hours=3)
        yesterday = now - timedelta(days=1)
        other = tmp_path / "elsewhere" / tmp_path.name
        other.mkdir(parents=True)
        kept_old = _record(tmp_path, since + timedelta(hours=1), "stop_failed_open_pytest_did_not_run")
        _write_log(integ, tmp_path, yesterday, [
            _record(tmp_path, since - timedelta(hours=1), "stop_failed_open_pytest_spawn"),  # before the start
            kept_old,
            _record(other, since + timedelta(hours=1, minutes=30), "stop_failed_open_counter"),  # another checkout
            _record(tmp_path, since + timedelta(hours=1, minutes=40), "pretooluse_blocked_protected_zone"),  # a refusal
            _record(tmp_path, "not-a-time", "stop_failed_open_counter"),  # cannot be placed
        ])
        kept_new = _record(tmp_path, now - timedelta(minutes=30), _POLICY)
        _write_log(integ, tmp_path, now, [kept_new])
        found, cut = integ.voice_only_since(tmp_path, since, now=now)
        assert (found, cut) == ([kept_old, kept_new], ""), found

    def test_the_read_stops_at_its_byte_bound_newest_first_and_says_so(self, tmp_path):
        """A log a wedged hook filled is read from its end, so the newest
        records survive the bound, and the reader names it. Dies to: an
        unbounded read (both records come back, no bound named)."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        since = now - timedelta(days=2)
        _write_log(integ, tmp_path, now - timedelta(days=1), [_record(tmp_path, now - timedelta(days=1), _POLICY)])
        early = _record(tmp_path, now - timedelta(hours=5), "stop_failed_open_counter")
        late = _record(tmp_path, now - timedelta(minutes=5), "stop_failed_open_pytest_did_not_run")
        path = _write_log(integ, tmp_path, now, [early])
        _write_log(integ, tmp_path, now, [late], filler=4096)
        assert path.stat().st_size > 4096
        found, cut = integ.voice_only_since(tmp_path, since, now=now, max_bytes=1024)
        assert (found, cut) == ([late], "1024 bytes"), (found, cut)
        whole, uncut = integ.voice_only_since(tmp_path, since, now=now)
        assert uncut == "" and [r["event_type"] for r in whole] == [_POLICY, early["event_type"], late["event_type"]]

    def test_the_read_stops_at_its_day_bound_and_says_so(self, tmp_path):
        """At the edge: the seventh day back is read, the eighth is not.
        Dies to: a bound one day off either way."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        assert integ.VOICE_READ_MAX_DAYS == 7
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        dropped = _record(tmp_path, now - timedelta(days=7) + timedelta(hours=1), _POLICY)
        kept = _record(tmp_path, now - timedelta(days=6) + timedelta(hours=1), "stop_failed_open_counter")
        _write_log(integ, tmp_path, now - timedelta(days=7), [dropped])
        _write_log(integ, tmp_path, now - timedelta(days=6), [kept])
        assert integ.voice_only_since(tmp_path, now - timedelta(days=10), now=now) == ([kept], "7 days")
        # A start inside the bound reads it all and names nothing.
        assert integ.voice_only_since(tmp_path, now - timedelta(days=6, hours=1), now=now) == ([kept], "")

    def test_the_byte_bound_is_shared_across_the_days_it_reads(self, tmp_path):
        """4 MB in all, never 4 MB a day: what today's log took is gone from
        yesterday's share. Dies to: a budget that is not spent across logs
        (yesterday's early record comes back)."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        yesterday = now - timedelta(days=1)
        early = _record(tmp_path, yesterday - timedelta(hours=10), "stop_failed_open_counter")
        late = _record(tmp_path, yesterday + timedelta(hours=10), "stop_failed_open_pytest_spawn")
        today_rec = _record(tmp_path, now - timedelta(hours=1), _POLICY)
        _write_log(integ, tmp_path, yesterday, [early])
        _write_log(integ, tmp_path, yesterday, [late], filler=300)
        today = _write_log(integ, tmp_path, now, [today_rec], filler=2000)
        bound = today.stat().st_size + len(json.dumps(late)) + 50
        assert integ.audit_path(tmp_path, yesterday).stat().st_size <= bound  # the whole log would fit a per-day budget
        assert integ.voice_only_since(tmp_path, now - timedelta(days=2), now=now, max_bytes=bound) == (
            [late, today_rec], f"{bound} bytes")

    def test_a_byte_bound_past_the_start_is_not_named(self, tmp_path):
        """The bound is named only where the unread head can hold a record
        after the start: here the oldest line read already predates it.
        Dies to: naming the bound whenever a log outgrows it (the line would
        say so at every start on a wedged hook's day)."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        old = _record(tmp_path, now - timedelta(hours=5), "stop_failed_open_counter")
        new = _record(tmp_path, now - timedelta(minutes=5), "stop_failed_open_pytest_did_not_run")
        _write_log(integ, tmp_path, now, [old])
        _write_log(integ, tmp_path, now, [new], filler=3000, noise_at=now - timedelta(hours=2))
        assert integ.voice_only_since(tmp_path, now - timedelta(hours=1), now=now, max_bytes=1024) == ([new], "")

    def test_an_unreadable_log_costs_its_own_records_and_is_named(self, tmp_path):
        """A log that exists and cannot be opened (here a directory where the
        day's file would be) is skipped, the other days still read. Dies to:
        a raise that throws the window's records away."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        integ.audit_path(tmp_path, now - timedelta(days=1)).mkdir(parents=True)
        kept = _record(tmp_path, now - timedelta(hours=1), _POLICY)
        _write_log(integ, tmp_path, now, [kept])
        assert integ.voice_only_since(tmp_path, now - timedelta(days=2), now=now) == ([kept], "an unreadable log")

    def test_every_voice_type_a_hook_writes_passes_the_pre_filter(self, tmp_path):
        """The substring pre-filter must admit everything the predicate does:
        one record of every voice type the hooks write, and one of each
        prefix shape. Dies to: a token dropped from the pre-filter (the
        `config_zone_` shape, an adopter's bad zone setting, read as no
        record)."""
        from datetime import datetime, timedelta, timezone

        integ = _load_hook_module("_integrity")
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        kinds = sorted(_voice_types_the_hooks_write() | {"config_zone_x", "config_recall_x", "x_failed_open_y"})
        assert len(kinds) > 20, kinds
        records = [_record(tmp_path, now - timedelta(seconds=len(kinds) - i), k) for i, k in enumerate(kinds)]
        _write_log(integ, tmp_path, now, records)
        found, cut = integ.voice_only_since(tmp_path, now - timedelta(hours=2), now=now)
        assert ([r["event_type"] for r in found], cut) == (kinds, "")

    def test_a_start_names_what_was_written_since_the_previous_start_and_nothing_older(self, tmp_path):
        """End to end, three starts: the first has no stamp and names the
        record from the fallback window; the second names nothing (the record
        predates the first start); a record written after it is named by the
        third, "since the last start". Dies to: a read after the state-flag
        cleanup rewrites the stamp (the third start reads its own, and names
        nothing), and to a date-only selection (the second start names the
        record again)."""
        integ = _load_hook_module("_integrity")
        # The operator's session variables stripped (the audit dir kept), so
        # the hook reads this scratch root alone.
        overrides: dict[str, str | None] = {
            k: None for k in os.environ if k.startswith(("CLAUDE_", "ESPALIER_")) and k != "ESPALIER_SESSION_CATCH_UP"}
        overrides["ESPALIER_AUDIT_DIR"] = os.environ["ESPALIER_AUDIT_DIR"]
        overrides["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        def start() -> list[str]:
            result = run_hook(
                "session_start.py", {"source": "startup", "hook_event_name": "SessionStart"}, overrides)
            assert result.returncode == 0, result.stderr
            context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            return [ln for ln in context.splitlines() if "voice-only record" in ln]

        integ.append_audit(tmp_path, {"event_type": "stop_failed_open_pytest_did_not_run", "details": {"hook": "stop_gate"}})
        first = start()
        assert len(first) == 1 and "(no earlier start here)" in first[0], first
        assert "stop_failed_open_pytest_did_not_run 1" in first[0], first
        assert start() == []
        integ.append_audit(tmp_path, {"event_type": _POLICY, "details": {"hook": "config_guard"}})
        third = start()
        assert len(third) == 1 and third[0].startswith("[WARN] espalier: 1 voice-only record since the last start ("), third
        assert f"{_POLICY} 1" in third[0] and "stop_failed_open" not in third[0], third

    def test_the_banner_line_fits_one_warning_line_with_the_longest_types_the_hooks_write(self, tmp_path, monkeypatch):
        """The banner has no room to give, so the line stays under the
        per-line cap with the adversarial input: the two longest types any
        hook writes, three-digit counts, more types than it names, and a
        stopped read. Dies to: naming a third type (the line overran the cap
        by 40 bytes, measured)."""
        ss = _load_hook_module("session_start")
        longest = sorted(_voice_types_the_hooks_write(), key=lambda t: (-len(t), t))[:4]
        # The two longest are the rarest, so the ranking names them.
        records = [{"event_type": t} for i, t in enumerate(longest) for _ in range(250 + 100 * i)]
        monkeypatch.setattr(ss._integrity, "voice_only_since", lambda *_a, **_k: (records, "4 MB"))
        ss._hook_utils.take_advisories()
        ss._report_voice_only_records(tmp_path)
        lines = ss._hook_utils.take_advisories()
        assert len(lines) == 1, lines
        line = lines[0]
        assert len(line.encode("utf-8")) <= ss._WARNING_LINE_MAX_BYTES, (len(line.encode("utf-8")), line)
        assert line.isascii(), line
        assert f"{longest[0]} 250" in line and f"{longest[1]} 350" in line, line
        assert "2 more types" in line and "(the read stopped at 4 MB)" in line, line

    def test_the_line_names_the_policy_type_then_the_rarest_and_folds_the_recurring(self, tmp_path, monkeypatch):
        """The Windows box's November logs: one type recurs at nearly every
        start, and the row's own victim is a single Stop-gate record. Dies
        to: ranking by count descending (the recurring type is named and the
        Stop record folds into the count)."""
        ss = _load_hook_module("session_start")
        mix = (["configchange_failed_open_settings_read"] * 22 + ["posttooluse_failed_open_zone_off"] * 3
               + ["stop_failed_open_pytest_did_not_run", _POLICY, "x_failed_open_\nTEXT"])
        monkeypatch.setattr(ss._integrity, "voice_only_since", lambda *_a, **_k: ([{"event_type": t} for t in mix], ""))
        ss._hook_utils.take_advisories()
        ss._report_voice_only_records(tmp_path)
        (line,) = ss._hook_utils.take_advisories()
        assert f": {_POLICY} 1, stop_failed_open_pytest_did_not_run 1, 3 more types --" in line, line
        assert "TEXT" not in line and "\n" not in line and "configchange_failed_open" not in line, line

    @pytest.mark.parametrize("stamp", ["garbage", "0001-01-01T00:00:00+05:00"], ids=["unparsed", "overflow"])
    def test_a_stamp_that_does_not_date_falls_back_to_the_status_window(self, tmp_path, stamp):
        """Dies to: a parse or overflow error escaping `_previous_start`
        (the job's line is lost to a WARN about the read)."""
        ss = _load_hook_module("session_start")
        (tmp_path / ".espalier-state").mkdir()
        (tmp_path / ".espalier-state" / "session_started").write_text(stamp, encoding="utf-8")
        _load_hook_module("_integrity").append_audit(
            tmp_path, {"event_type": "stop_failed_open_counter", "details": {"hook": "stop_gate"}})
        ss._hook_utils.take_advisories()
        ss._report_voice_only_records(tmp_path)
        (line,) = ss._hook_utils.take_advisories()
        assert "(no earlier start here)" in line and "stop_failed_open_counter 1" in line, line


# ---------------------------------------------------------------------------
# Ledger row DEF-3093: every audit type a hook writes sits in exactly one
# declared family -- a block tier, the maintenance-bypass set, the voice-only
# family, or one of the two advisory sets -- so a new type with no channel
# fails here instead of reaching neither reader.
# ---------------------------------------------------------------------------

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _target_names(target: ast.AST) -> set[str]:
    """Every plain name a binding target binds (``a``, ``a, b``, ``*rest``)."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(e) for e in target.elts))
    return set()


def _bindings(node: ast.AST):
    """``(name, value)`` for each name ``node`` binds to a value the census can
    read: a plain assignment, an annotated one, or a literal tuple unpacked
    into a tuple of names of the same length."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id, node.value
            elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List)) \
                    and len(target.elts) == len(node.value.elts) \
                    and not any(isinstance(e, ast.Starred) for e in (*target.elts, *node.value.elts)):
                for sub, value in zip(target.elts, node.value.elts):
                    if isinstance(sub, ast.Name):
                        yield sub.id, value
    elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
        yield node.target.id, node.value


def _binders(node: ast.AST) -> set[str]:
    """Every name ``node`` binds, by any form: the set ``_bindings`` must
    account for, so a binding it cannot read is named, never dropped."""
    if isinstance(node, ast.Assign):
        return set().union(*(_target_names(t) for t in node.targets))
    if isinstance(node, ast.AnnAssign):
        return _target_names(node.target) if node.value is not None else set()
    if isinstance(node, (ast.AugAssign, ast.For, ast.AsyncFor, ast.NamedExpr)):
        return _target_names(node.target)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return set().union(*(_target_names(i.optional_vars) for i in node.items if i.optional_vars))
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return set(node.names)
    return set()


def _local_bindings(scope: ast.AST, ident: str) -> tuple[list[ast.expr], list[int]]:
    """The values ``ident`` is assigned in ``scope`` itself, and the lines
    where it is bound by a form the census does not read (a loop target, an
    augmented assignment, a walrus, a ``with`` or ``except`` name, an unpacked
    call); the defs, classes and lambdas inside ``scope`` are scopes of their
    own and are left out. The values come in line order, so a rebinding that
    reads the name (``x = "a"; x = f"{x}_b"``) reads the earlier value."""
    values: list[tuple[int, int, ast.expr]] = []
    other: list[int] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (*_DEFS, ast.ClassDef, ast.Lambda)):
            continue
        read = [value for name, value in _bindings(node) if name == ident]
        values += [(v.lineno, v.col_offset, v) for v in read]
        if ident in _binders(node) and not read:
            other.append(node.lineno)
        stack.extend(ast.iter_child_nodes(node))
    return [v for _line, _col, v in sorted(values, key=lambda t: t[:2])], sorted(other)


def _self_attr(expr: ast.AST) -> str | None:
    """``attr`` for ``self.attr``, else None."""
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id == "self":
        return expr.attr
    return None


def _ref_name(node: ast.AST) -> str | None:
    """The name a load of ``node`` refers to: ``x`` or ``mod.x``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _AuditTypeCensus:
    """Every event type the hooks can hand ``append_audit``, read backwards
    from each of its calls: a literal, a conditional, a name bound to one in
    its function or in a def enclosing it (a closure), a module constant, a
    parameter (then every call of that function, or its default where a call
    leaves the argument out), ``.lower()``/``.upper()``, and an f-string over
    any of those. The writer set is not a roster: a new wrapper is read because
    its parameter reaches the slot, and ``traced`` names each function read
    that way. ``unread`` names each site the census cannot resolve, so a type it
    cannot read is said, never dropped."""

    def __init__(self, trees: dict[str, ast.Module]) -> None:
        self.trees = trees
        self.defs: dict[str, list[tuple[str, ast.FunctionDef]]] = {}
        self.enclosing: dict[int, ast.FunctionDef] = {}
        self.outer: dict[int, ast.FunctionDef] = {}
        self.consts: dict[str, dict[str, list[ast.expr]]] = {}
        self.calls: dict[str, list[tuple[str, ast.Call]]] = {}
        self.class_of: dict[int, ast.ClassDef] = {}
        for name, tree in trees.items():
            self.consts[name] = {}
            for node in tree.body:
                for ident, value in _bindings(node):
                    self.consts[name].setdefault(ident, []).append(value)
            for node in ast.walk(tree):  # breadth first: a def before the defs inside it
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, _DEFS):
                            self.class_of[id(item)] = node
                if isinstance(node, _DEFS):
                    self.defs.setdefault(node.name, []).append((name, node))
                    for sub in ast.walk(node):
                        self.enclosing[id(sub)] = node  # the innermost def is walked last, and wins
                        if sub is not node and isinstance(sub, _DEFS):
                            self.outer[id(sub)] = node
                if isinstance(node, ast.Call) and (callee := _call_name(node)):
                    self.calls.setdefault(callee, []).append((name, node))
        self.unread: list[str] = []
        self.traced: set[str] = set()
        self._domains: dict[tuple[int, str], set[str]] = {}
        self._names: dict[tuple[int, str], set[str]] = {}
        self._attrs: dict[tuple[int, str], set[str]] = {}
        self.written: dict[str, set[str]] = {}
        # The writer's calls, and its aliases: ``x = partial(append_audit, *bound)``
        # (or ``self.x = ...``) makes each call of ``x`` in that file, in the same
        # form, a write whose event is the argument after the bound ones. Any
        # other reference to the writer is named, since its calls go unread.
        writes: list[tuple[str, ast.Call, int]] = [(n, c, 1) for n, c in self.calls.get("append_audit", [])]
        for name, tree in trees.items():
            aliased: set[int] = set()
            for node in ast.walk(tree):
                value = node.value if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
                if not (isinstance(value, ast.Call) and _call_name(value) == "partial" and value.args
                        and _ref_name(value.args[0]) == "append_audit"):
                    continue
                target = node.targets[0]
                bound = value.args[1:]
                alias = target.id if isinstance(target, ast.Name) else _self_attr(target)
                if alias is None or len(bound) > 1 or any(isinstance(a, ast.Starred) for a in bound):
                    continue
                aliased.add(id(value.args[0]))
                for cname, call in self.calls.get(alias, []):
                    same_form = (isinstance(target, ast.Name) and isinstance(call.func, ast.Name)) or \
                        (_self_attr(target) is not None and _self_attr(call.func) == alias)
                    if cname == name and same_form:
                        writes.append((cname, call, 1 - len(bound)))
            callees = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for node in ast.walk(tree):
                if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load) \
                        and _ref_name(node) == "append_audit" and id(node) not in callees | aliased:
                    self.unread.append(f"{name}:{node.lineno}: append_audit is referenced, not called")
        for name, call, index in writes:
            site = f"{name}:{call.lineno}"
            event = call.args[index] if len(call.args) > index else next(
                (k.value for k in call.keywords if k.arg == "event"), None)
            slot, slot_at = None, None
            if isinstance(event, ast.Dict):
                slot_at = next((i for i, k in enumerate(event.keys)
                                if isinstance(k, ast.Constant) and k.value == "event_type"), None)
                slot = event.values[slot_at] if slot_at is not None else None
            if slot is None:
                self.unread.append(f"{site}: the event is not a dict literal with an event_type key")
                continue
            if any(k is None for k in event.keys[slot_at + 1:]):
                self.unread.append(f"{site}: a ** spread after event_type may replace it")
            for value in self.values(name, slot):
                self.written.setdefault(value, set()).add(site)
        self._name_unread_routes()

    def _name_unread_routes(self) -> None:
        """A writer the census traced reaches the slot only through the calls
        it reads by name: an ``import ... as`` alias of it, or a reference
        passed on (a callback), is a route those calls miss, so each is
        named. A name bound in the enclosing defs is a local, not the writer,
        and a module-level ``x = mod.x`` keeps the name its calls are read by."""
        writers = self.traced | {"append_audit"}
        for name, tree in self.trees.items():
            callees = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
            callees |= {id(n.value) for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name) and _ref_name(n.value) == n.targets[0].id}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in writers and alias.asname not in (None, alias.name):
                            self.unread.append(f"{name}:{node.lineno}: {alias.name} is imported as {alias.asname}")
                    continue
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr in writers \
                        and node.attr != "append_audit" and id(node) not in callees \
                        and isinstance(node.value, ast.Name) and f"{node.value.id}.py" in self.trees:
                    self.unread.append(f"{name}:{node.lineno}: {node.value.id}.{node.attr} is passed on, not called")
                    continue
                if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in writers
                        and node.id != "append_audit" and id(node) not in callees):
                    continue
                scope = self.enclosing.get(id(node))
                local = False
                while scope is not None and not local:
                    a = scope.args
                    local = node.id in {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs} \
                        or any(_local_bindings(scope, node.id))
                    scope = self.outer.get(id(scope))
                if not local and node.id in self.consts[name]:
                    local = True
                if not local:
                    self.unread.append(f"{name}:{node.lineno}: {node.id} is passed on, not called")

    def _targets(self, name: str, call: ast.Call) -> set[str]:
        """The hook files whose definition ``call`` (in hook ``name``) can
        reach: the module an attribute call names, the caller's own
        definition, else every hook defining the name (a ``from`` import)."""
        callee = _call_name(call)
        func = call.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and f"{func.value.id}.py" in self.trees:
            return {f"{func.value.id}.py"}
        defining = {hook for hook, _fn in self.defs.get(callee or "", [])}
        if isinstance(func, ast.Name) and name in defining:
            return {name}
        return defining

    def param_domain(self, name: str, fn: ast.FunctionDef, param: str) -> set[str]:
        """Every string ``param`` of ``fn`` (in hook ``name``) can hold, from
        every call of ``fn`` the hooks make."""
        key = (id(fn), param)
        if key in self._domains:
            return self._domains[key]
        self._domains[key] = out = set()  # a cycle reads what is known so far
        self.traced.add(fn.name)
        args = fn.args
        positional = [a.arg for a in args.posonlyargs + args.args]
        defaults = dict(zip(positional[len(positional) - len(args.defaults):], args.defaults))
        defaults.update({a.arg: d for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None})
        index = positional.index(param) if param in positional else None
        sites = [(cname, call) for cname, call in self.calls.get(fn.name, []) if name in self._targets(cname, call)]
        if not sites:
            self.unread.append(f"{name}:{fn.lineno}: no call of {fn.name}() gives {param} a value")
        for cname, call in sites:
            site = f"{cname}:{call.lineno}"
            arg = next((k.value for k in call.keywords if k.arg == param), None)
            if arg is None and index is not None and index < len(call.args):
                if any(isinstance(a, ast.Starred) for a in call.args[: index + 1]):
                    self.unread.append(f"{site}: {fn.name}() takes {param} from a starred argument")
                    continue
                arg = call.args[index]
            if arg is None:
                if any(k.arg is None for k in call.keywords):
                    self.unread.append(f"{site}: {fn.name}() may take {param} from **kwargs")
                    continue
                if param in defaults:
                    out |= self.values(name, defaults[param], fn)
                    continue
                self.unread.append(f"{site}: {fn.name}() is called without {param}")
                continue
            out |= self.values(cname, arg)
        return out

    def _name_values(self, name: str, scope: ast.FunctionDef, ident: str, is_param: bool) -> set[str]:
        """Every string ``ident``, local to ``scope``, can hold: its parameter
        domain first, then each value it is assigned (``x = x.lower()`` reads
        the parameter's values lowered; a deeper cycle reads what is known)."""
        key = (id(scope), ident)
        if key in self._names:
            return self._names[key]
        self._names[key] = out = set()
        if is_param:
            out |= self.param_domain(name, scope, ident)
        values, other = _local_bindings(scope, ident)
        if other:
            self.unread.append(f"{name}:{other[0]}: {ident} is bound by a form the census does not read")
        for value in values:
            out |= self.values(name, value)
        return out

    def _attr_values(self, name: str, fn: ast.FunctionDef, attr: str, site: str) -> set[str]:
        """Every string ``self.attr`` can hold inside a method of ``fn``'s
        class: each value assigned to ``self.attr`` in any of its methods, or
        to ``attr`` in the class body."""
        scope: ast.FunctionDef | None = fn
        while scope is not None and id(scope) not in self.class_of:
            scope = self.outer.get(id(scope))
        if scope is None:
            self.unread.append(f"{site}: self.{attr} is read outside a method")
            return set()
        cls = self.class_of[id(scope)]
        key = (id(cls), attr)
        if key in self._attrs:
            return self._attrs[key]
        self._attrs[key] = out = set()
        bound: list[ast.expr] = [v for item in cls.body for ident, v in _bindings(item) if ident == attr]
        for method in (item for item in cls.body if isinstance(item, _DEFS)):
            for node in ast.walk(method):
                if isinstance(node, ast.Assign) and any(_self_attr(t) == attr for t in node.targets):
                    bound.append(node.value)
                elif isinstance(node, ast.AnnAssign) and node.value is not None and _self_attr(node.target) == attr:
                    bound.append(node.value)
                elif isinstance(node, ast.AugAssign) and _self_attr(node.target) == attr:
                    self.unread.append(f"{name}:{node.lineno}: self.{attr} is bound by a form the census does not read")
        if not bound:
            self.unread.append(f"{site}: self.{attr} is assigned nowhere in its class")
        for value in bound:
            out |= self.values(name, value)
        return out

    def values(self, name: str, expr: ast.expr, fn: ast.FunctionDef | None = None) -> set[str]:
        """Every string ``expr`` (in hook ``name``) can evaluate to."""
        fn = fn or self.enclosing.get(id(expr))
        site = f"{name}:{getattr(expr, 'lineno', '?')}"
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        if isinstance(expr, ast.IfExp):
            return self.values(name, expr.body, fn) | self.values(name, expr.orelse, fn)
        if isinstance(expr, ast.Name):
            scope = fn
            while scope is not None:  # its own def, then each def enclosing it
                a = scope.args
                is_param = expr.id in {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs}
                if is_param or any(_local_bindings(scope, expr.id)):
                    return self._name_values(name, scope, expr.id, is_param)
                scope = self.outer.get(id(scope))
            if expr.id in self.consts[name]:
                return set().union(*(self.values(name, v) for v in self.consts[name][expr.id]))
            self.unread.append(f"{site}: {expr.id} is bound to nothing the census reads")
            return set()
        if (attr := _self_attr(expr)) is not None and fn is not None:
            return self._attr_values(name, fn, attr, site)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and not expr.args \
                and not expr.keywords and expr.func.attr in ("lower", "upper"):
            method = expr.func.attr
            return {getattr(v, method)() for v in self.values(name, expr.func.value, fn)}
        if isinstance(expr, ast.JoinedStr):
            parts: list[set[str]] = []
            for piece in expr.values:
                if isinstance(piece, ast.Constant):
                    parts.append({str(piece.value)})
                elif isinstance(piece, ast.FormattedValue) and piece.conversion == -1 and piece.format_spec is None:
                    parts.append(self.values(name, piece.value, fn))
                else:
                    self.unread.append(f"{site}: an f-string piece the census cannot read")
                    return set()
            return {"".join(p) for p in itertools.product(*parts)}
        self.unread.append(f"{site}: {ast.unparse(expr)[:60]!r} is not a form the census reads")
        return set()

    def domain_of(self, hook: str, fn_name: str, param: str) -> set[str]:
        """``param_domain`` of the one def named ``fn_name`` in ``hook``."""
        (fn,) = [fn for name, fn in self.defs.get(fn_name, []) if name == hook]
        return self.param_domain(hook, fn, param)


@functools.lru_cache(maxsize=1)
def _live_hook_trees() -> tuple[tuple[str, ast.Module], ...]:
    """The hooks parsed once a process; a census reads them and never edits."""
    return tuple((p.name, ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(checkout_glob(HOOKS_DIR, "*.py")))


def _live_audit_census(**extra: ast.Module) -> _AuditTypeCensus:
    """A fresh census of the live hooks (plus ``extra`` trees), so no test reads
    another's ``unread``."""
    return _AuditTypeCensus({**dict(_live_hook_trees()), **extra})


def _audit_families(integ) -> list[tuple[str, object]]:
    """The declared families, each with the predicate that admits a type. The
    two advisory sets are read by ``getattr`` so a tree without them fails the
    partition by its assertion, never by an ``AttributeError``."""
    channelled = getattr(integ, "CHANNELLED_ADVISORY_EVENT_TYPES", frozenset())
    raw_log_only = getattr(integ, "RAW_LOG_ONLY_EVENT_TYPES", frozenset())
    return [
        ("refusal", integ.DENIAL_EVENT_TYPES.__contains__),
        ("pause", integ.PAUSE_EVENT_TYPES.__contains__),
        ("maintenance bypass", integ.MAINTENANCE_BYPASS_EVENT_TYPES.__contains__),
        ("voice-only", integ.is_voice_only_event),
        ("channelled advisory", channelled.__contains__),
        ("raw log only", raw_log_only.__contains__),
    ]


_CHANNEL_CALLS = frozenset({"advise", "advise_warn", "_say_once_to_claude"})
_RECORD_CALLS = frozenset({"append_audit", "_say_once_to_claude"})

#: A channelled advisory whose channel is not a call beside its record, with
#: what the witness test reads for it instead.
_NAMED_CHANNEL_WITNESSES = {
    "stop_held_handoff": "a stop_gate function writes the hold file (_hold_write) beside the held record "
                         "(_say_held), and task_router reads HANDOFF_GATE_HOLD to name it on every prompt",
}

#: Each raw-log-only type, with where its by-design stderr voice is declared.
_RAW_LOG_ONLY_REASONS = {
    "action_justification_missing": "docs/HOOKS.md, post_write_check: the action-justification nudge "
                                    "stays on stderr, and /status --log does not count that type",
}


def _channel_beside_record(trees: dict[str, ast.Module]) -> set[str]:
    """Each string literal whose innermost statement list both writes a record
    (``append_audit``, ``_say_once_to_claude``) and calls a channel to Claude
    or the operator (``advise``, ``advise_warn``, ``_say_once_to_claude``)."""
    found: set[str] = set()
    for name, tree in trees.items():
        if name == "_integrity.py":
            continue
        parent = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        lists: dict[int, list] = {}
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                stmts = getattr(node, field, None)
                if isinstance(stmts, list):
                    lists.update({id(s): stmts for s in stmts if isinstance(s, ast.stmt)})
        speaks: dict[int, bool] = {}  # one walk a statement list, not one a literal
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            up = node
            while up is not None and id(up) not in lists:
                up = parent.get(id(up))
            if up is None:
                continue
            stmts = lists[id(up)]
            if id(stmts) not in speaks:
                calls = {_call_name(c) for s in stmts for c in ast.walk(s) if isinstance(c, ast.Call)}
                speaks[id(stmts)] = bool(calls & _RECORD_CALLS and calls & _CHANNEL_CALLS)
            if speaks[id(stmts)]:
                found.add(node.value)
    return found


def _family_offenders(written, integ) -> list[str]:
    """Each written type that sits in no family, or in more than one."""
    families = _audit_families(integ)
    out = []
    for event_type in sorted(written):
        held = [label for label, admits in families if admits(event_type)]
        if len(held) != 1:
            out.append(f"{event_type}: {', '.join(held) or 'no family'}")
    return out


_CENSUS_READS = {
    "_integrity.py": "def append_audit(root, event, *, quiet=False):\n    return True\n",
    "_hook_utils.py": textwrap.dedent('''\
        from _integrity import append_audit

        def say_once(root, key, hook, event_type, message, **details):
            append_audit(root, {"event_type": event_type, "details": details})
    '''),
    "hook_a.py": textwrap.dedent('''\
        import _hook_utils
        from _integrity import append_audit

        KIND = "a_module_constant"

        def _wrapper(root, event_type="a_default"):
            _hook_utils.say_once(root, "k", "hook_a", event_type, "said")

        def _composed(root, event):
            append_audit(root, {"event_type": f"{event}_blocked_composed"})

        def _closure(event):
            def _inner(root):
                append_audit(root, {"event_type": f"{event}_from_a_closure"})
            return _inner

        def _lowered(root, kind):
            append_audit(root, {"event_type": kind.lower()})

        def _rebound(root, kind):
            kind = kind.lower()
            append_audit(root, {"event_type": kind})

        def _self_ref(root):
            event = "a_seed"
            event = f"{event}_read"
            append_audit(root, {"event_type": event})

        def main(root, flag):
            _wrapper(root)
            _wrapper(root, event_type="a_keyword")
            _hook_utils.say_once(root, "k", "hook_a", event_type="a_say_once_keyword", message="said")
            picked = "a_branch_one" if flag else "a_branch_two"
            append_audit(root, {"event_type": picked})
            append_audit(root, event={"event_type": KIND})
            _composed(root, "pretooluse")
            _closure("stop")(root)
            _lowered(root, "A_LOWERED")
            _rebound(root, "A_REBOUND")
            _self_ref(root)
    '''),
    "hook_c.py": textwrap.dedent('''\
        import functools
        import _integrity

        class _Refusal:
            def __init__(self):
                self._event = "c_class_default"
                self._write = None

            def record(self, *, event="c_record_default"):
                self._event = event

            def build(self, root):
                self._write = functools.partial(_integrity.append_audit, root, quiet=True)
                self._write({"event_type": self._event})

        def run(refusal, flag):
            if flag:
                event, details = "c_unpacked", {}
            else:
                event = "c_plain"
            refusal.record(event=event)
            refusal.record()
    '''),
}

_CENSUS_SAYS_UNREAD = {
    "_integrity.py": _CENSUS_READS["_integrity.py"],
    "_hook_utils.py": _CENSUS_READS["_hook_utils.py"],
    "hook_b.py": textwrap.dedent('''\
        import _hook_utils
        from _integrity import append_audit

        def _forward(root, **details):
            _hook_utils.say_once(root, "k", "hook_b", message="said", **details)

        def _never_called(root, event_type):
            append_audit(root, {"event_type": event_type})

        def main(root, suffix):
            append_audit(root, {"event_type": "b_" + suffix})
            record = {"event_type": "b_prebuilt"}
            append_audit(root, record)
    '''),
    "hook_d.py": textwrap.dedent('''\
        import functools
        import _hook_utils
        from _integrity import append_audit
        from _hook_utils import say_once as _say

        def main(root, items, extra):
            _say(root, "k", "hook_d", "d_via_an_alias", "said")
            later = functools.partial(_hook_utils.say_once, root)
            later("k", "hook_d", "d_via_a_partial", "said")
            for looped in items:
                append_audit(root, {"event_type": looped})
            grown = "d_one"
            grown += "_more"
            append_audit(root, {"event_type": grown})
            append_audit(root, {"event_type": "d_spread", **extra})
            writer = append_audit
            writer(root, {"event_type": "d_aliased"})
    '''),
}


class TestEveryAuditTypeHasAFamily:
    """DEF-3093. The written set is derived from every ``append_audit`` call
    by ``_AuditTypeCensus``, which is fed both what it must read and what it
    must name as unread; every written type then sits in exactly one declared
    family, and the two advisory sets name only types a hook writes."""

    def test_the_census_reads_every_form_a_type_reaches_the_writer_by(self):
        census = _AuditTypeCensus({n: ast.parse(src) for n, src in _CENSUS_READS.items()})
        assert census.unread == []
        assert set(census.written) == {
            "a_default", "a_keyword", "a_say_once_keyword", "a_branch_one", "a_branch_two",
            "a_module_constant", "pretooluse_blocked_composed", "stop_from_a_closure", "a_lowered",
            # A name reads every value it is ever bound to, not their order: a
            # superset, never a dropped type.
            "A_REBOUND", "a_rebound", "a_seed", "a_seed_read",
            # A partial of the writer, a self attribute set in the class and
            # by a method's keyword, and a literal tuple unpacked.
            "c_class_default", "c_record_default", "c_unpacked", "c_plain",
        }
        assert census.traced >= {"say_once", "_wrapper", "_composed", "_closure", "_lowered", "_rebound", "record"}

    def test_the_census_names_each_site_it_cannot_read(self):
        census = _AuditTypeCensus({n: ast.parse(src) for n, src in _CENSUS_SAYS_UNREAD.items()})
        # What it can read beside a named gap stays read: said, never dropped.
        assert set(census.written) == {"d_one", "d_spread"}
        said = sorted(census.unread)
        assert len(said) == 10, said
        for phrase in ("say_once is imported as _say",
                       "_hook_utils.say_once is passed on, not called",
                       "say_once() may take event_type from **kwargs",
                       "no call of _never_called() gives event_type a value",
                       "'b_' + suffix",
                       "the event is not a dict literal with an event_type key",
                       "looped is bound by a form the census does not read",
                       "grown is bound by a form the census does not read",
                       "a ** spread after event_type may replace it",
                       "append_audit is referenced, not called"):
            assert sum(phrase in line for line in said) == 1, (phrase, said)

    def test_the_census_reads_the_live_hooks_whole(self):
        census = _live_audit_census()
        assert census.unread == []
        assert len(census.written) >= 95, f"discovery floor: found only {len(census.written)}"
        # It sees at least what the older readers see, and traces through each
        # writer the bare-emitter roster names.
        assert sorted(_emitted_denial_event_types() - set(census.written)) == []
        assert sorted(_emitted_bypass_event_types() - set(census.written)) == []
        assert sorted(_AUDIT_WRITERS - {"append_audit"} - census.traced) == []

    def test_every_written_type_sits_in_exactly_one_family(self):
        integ = _load_hook_module("_integrity")
        assert _family_offenders(_live_audit_census().written, integ) == []

    def test_a_new_type_outside_every_family_is_named(self):
        integ = _load_hook_module("_integrity")
        hook = ast.parse(textwrap.dedent('''\
            from _integrity import append_audit

            def main(root):
                append_audit(root, {"event_type": "postcompact_summary_unwritten"})
        '''))
        census = _live_audit_census(**{"zz_new_hook.py": hook})
        assert _family_offenders(census.written, integ) == ["postcompact_summary_unwritten: no family"]

    def test_the_two_advisory_sets_name_written_types_no_other_family_admits(self):
        integ = _load_hook_module("_integrity")
        written = set(_live_audit_census().written)
        channelled = set(getattr(integ, "CHANNELLED_ADVISORY_EVENT_TYPES", ()))
        raw_log_only = set(getattr(integ, "RAW_LOG_ONLY_EVENT_TYPES", ()))
        assert channelled and raw_log_only
        assert sorted((channelled | raw_log_only) - written) == [], "declared, but no hook writes it"
        assert channelled & raw_log_only == set()
        tiers = set(integ.BLOCKED_EVENT_TYPES) | set(integ.MAINTENANCE_BYPASS_EVENT_TYPES)
        assert sorted((channelled | raw_log_only) & tiers) == []
        assert [t for t in sorted(channelled | raw_log_only) if integ.is_voice_only_event(t)] == []

    def test_every_channelled_advisory_has_a_witnessed_channel(self):
        """The channelled set is no escape hatch: a type joins it only where a
        channel call sits beside its record, or under a named witness read
        here, so a type with no channel, or one whose channel is removed,
        fails instead of passing as channelled."""
        integ = _load_hook_module("_integrity")
        channelled = set(getattr(integ, "CHANNELLED_ADVISORY_EVENT_TYPES", ()))
        trees = dict(_live_hook_trees())
        beside = _channel_beside_record(trees)
        named = set(_NAMED_CHANNEL_WITNESSES)
        assert sorted(channelled - beside - named) == [], "declared channelled, with no channel beside its record"
        assert sorted(named - channelled) == []
        assert sorted(named & beside) == [], "a named witness for a channel the census already sees"
        held = [fn.name for fn in ast.walk(trees["stop_gate.py"]) if isinstance(fn, _DEFS)
                and {"_say_held", "_hold_write"} <= {_call_name(c) for c in ast.walk(fn) if isinstance(c, ast.Call)}]
        assert held, "no stop_gate function writes the hold file beside the held record"
        assert any(isinstance(n, ast.Name) and n.id == "HANDOFF_GATE_HOLD" and isinstance(n.ctx, ast.Load)
                   for fn in ast.walk(trees["task_router.py"]) if isinstance(fn, _DEFS) for n in ast.walk(fn))

    def test_every_raw_log_only_type_names_its_reason(self):
        integ = _load_hook_module("_integrity")
        assert set(getattr(integ, "RAW_LOG_ONLY_EVENT_TYPES", ())) == set(_RAW_LOG_ONLY_REASONS)
