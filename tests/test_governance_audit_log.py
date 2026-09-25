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
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _site_path import site_path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _run_hook(script: str, payload: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # The host may run MAINTENANCE=on, which bypasses the protected-zone and
    # plan-required checks; delete it so the denial (and its audit record) fires.
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
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
    for hook in sorted(HOOKS_DIR.glob("*.py")):
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
    def _doc_rows() -> list[tuple[str, str]]:
        import re

        text = (REPO_ROOT / "docs" / "HOOKS.md").read_text(encoding="utf-8")
        start = text.index("## Governance audit log")
        end = text.find("\n## ", start + 1)
        section = text[start:end if end != -1 else None]
        return re.findall(r"^\| `([a-z_]+)` \| (refusal|pause) \|", section, flags=re.M)

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
    return {hook.name: ast.parse(hook.read_text(encoding="utf-8")) for hook in sorted(HOOKS_DIR.glob("*.py"))}


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
    for hook in sorted(HOOKS_DIR.glob("*.py")):
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
            if const == "KILL_SWITCH_DETECTED":
                if any(ev.endswith("_blocked_kill_switch") for ev in _audit_event_literals(fn, call)):
                    continue
                offenders.append(where + " -- kill-switch emitter with no audit of its event on the emit's path")
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
        for hook in sorted(HOOKS_DIR.glob("*.py")):
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

        def _mentions_protected_zone(node: ast.AST) -> bool:
            return any(
                isinstance(a, ast.Attribute) and a.attr.startswith("PROTECTED_ZONE")
                for a in ast.walk(node)
            )

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
            f'{sys.executable} -c "import sys; sys.exit(3)"',
        )
        result = _run_stop_hook(tmp_path, ESPALIER_STOP_GATE="full")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["decision"] == "block"
        records = [r for r in _audit_records() if r["event_type"] == "stop_blocked_pytest"]
        assert len(records) == 1, [r["event_type"] for r in _audit_records()]
        assert records[0]["details"] == {"gate": 1, "rule": "GATE_ENV_OVERRIDE_FAILED", "returncode": 3}
        assert records[0]["repo_path"] == str(tmp_path.resolve())

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
        allowed = {"gate", "rule", "write_count", "returncode"}
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
        assert pauses.startswith("# pauses today: "), pauses
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
        assert result.stdout.startswith("(no governance denials recorded for this repo today"), result.stdout
        assert "1 pause record today" in result.stdout and "--all" in result.stdout, result.stdout

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
    for hook in sorted(HOOKS_DIR.glob("*.py")):
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
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / script)],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=60, env=env, encoding="utf-8",
        )

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
            hook.stem for hook in HOOKS_DIR.glob("*.py")
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
        assert "3 maintenance-bypass records today" in plain.stdout, plain.stdout
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
    for hook in sorted(HOOKS_DIR.glob("*.py")):
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
        assert set(details) <= {"hook", "rule", "error"}, details
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
