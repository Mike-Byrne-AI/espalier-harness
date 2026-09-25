"""Earn-fixtures for the recall-engine reinjection registry (TP-164).

Proves the mechanism against a SYNTHETIC canary registry (NOT the real
orientation / Rule-A rows — those are exercised by the orientation + Rule-A
parity tests further down once 164-C/D land): the per-turn ceiling, the flocked
session cap, cap-exemption (exempt counts against the per-turn slice but bypasses
the session cap), and render-error safety. Sibling of tests/test_speedbump.py.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

try:                       # POSIX-only, mirroring `_append_jsonl`'s own import
    import fcntl as _fcntl
except ImportError:        # pragma: no cover -- Windows
    _fcntl = None

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _hook_utils  # noqa: E402
import _reinject  # noqa: E402
import post_write_check as _pwc  # noqa: E402

_MAINT = "ESPALIER_MAINTENANCE_MODE"
_STOP = "ESPALIER_STOP_GATE"


def _rule(id_, *, event="SessionStart", cap_exempt=False, priority=50, text=None,
          face="defensive", push_eligible=False):
    """Canary rule whose payload is its id by default (so emitted ids are checkable).

    TP-166 added the ``face`` / ``push_eligible`` passthroughs so generative-rail
    tests can synthesize a ``face="generative", push_eligible=True`` rule.
    """
    payload = id_ if text is None else text
    return _reinject.ReinjectRule(
        id=id_, event=event, render=lambda tn, ti, root: payload,
        cap_exempt=cap_exempt, priority=priority,
        face=face, push_eligible=push_eligible,
    )


def test_reinjectrule_push_eligible_field_defaults_false():
    """TP-166 added the §11 #10 rail field. Default False (so every pre-166 row stays
    non-pushable); a generative push rule must opt in explicitly."""
    r = _reinject.ReinjectRule(id="X", event="UserPromptSubmit",
                               render=lambda tn, ti, root: None)
    assert r.push_eligible is False
    g = _reinject.ReinjectRule(id="Y", event="UserPromptSubmit",
                               render=lambda tn, ti, root: "x",
                               face="generative", push_eligible=True)
    assert g.push_eligible is True and g.face == "generative"


def test_default_registry_event_shape(tmp_path, monkeypatch):
    # The SHIPPED registry (guards the module-default `rules=REINJECTS`): ORIENT on
    # SessionStart, RULE-A on PostToolUseFailure, and the sync rows (every other
    # row in REINJECTS) on PostToolUse. The PostToolUse assertion
    # below still returns [] because every sync
    # predicate hard-gates on tool/path BEFORE reading content -- a Bash call with no
    # file_path matches none (the per-rule fire/silent matrix lives in
    # tests/test_reinject_sync.py). RULE-A's render is unconditional for its event --
    # the FIRING predicate lives in context_reinject_failure.py, so check() returns the
    # text directly here (the hook is the gate, see test_rule_a_* below).
    monkeypatch.delenv(_MAINT, raising=False)
    monkeypatch.delenv(_STOP, raising=False)
    assert _reinject.check("PreToolUse", "Bash", {"command": "x"}, tmp_path) == []
    assert _reinject.check("PostToolUse", "Bash", {"command": "x"}, tmp_path) == []
    session = _reinject.check("SessionStart", "", {}, tmp_path)
    assert len(session) == 1 and session[0].startswith("Host: OS=")
    assert _reinject.check("PostToolUseFailure", "Edit", {}, tmp_path) == [_reinject._RULE_A]


def test_event_filter(tmp_path):
    rules = (_rule("A", event="SessionStart"), _rule("B", event="PreToolUse"))
    assert _reinject.check("SessionStart", "", {}, tmp_path, rules=rules) == ["A"]
    assert _reinject.check("PreToolUse", "", {}, tmp_path, rules=rules) == ["B"]
    assert _reinject.check("PostToolUse", "", {}, tmp_path, rules=rules) == []


def test_silent_render_omitted(tmp_path):
    # A render that returns None (or "") does not emit and does not consume a slot.
    rules = (
        _reinject.ReinjectRule(id="SILENT", event="SessionStart",
                               render=lambda tn, ti, root: None),
        _rule("LOUD"),
    )
    assert _reinject.check("SessionStart", "", {}, tmp_path, rules=rules) == ["LOUD"]


def test_per_turn_ceiling_caps_emit(tmp_path):
    # 3 non-exempt rows, CAP=2 -> exactly the 2 highest-priority emit; the 3rd
    # (lowest priority) is clipped by the [:CAP] slice.
    rules = (
        _rule("HI", priority=90),
        _rule("MID", priority=80),
        _rule("LO", priority=70),
    )
    out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    assert out == ["HI", "MID"]  # sorted by priority, sliced to REINJECT_PER_TURN_CAP=2
    assert "LO" not in out


def test_per_turn_ceiling_is_the_limiter(tmp_path, monkeypatch):
    # Inject-and-restore: the [:CAP] slice (NOT some other mechanism) is what caps
    # the emit. Raise the ceiling and all 3 rows emit -> proves the ceiling earns
    # its place (removing/loosening it changes the result).
    monkeypatch.setattr(_reinject, "REINJECT_PER_TURN_CAP", 10)
    rules = (_rule("HI", priority=90), _rule("MID", priority=80), _rule("LO", priority=70))
    out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    assert out == ["HI", "MID", "LO"]


def test_cap_exempt_counts_against_per_turn_slice(tmp_path):
    # §6 criterion: CAP+1 non-exempt + 1 exempt on one event -> exactly CAP
    # payloads, the exempt among them, and exactly CAP-1 non-exempt. Proves the
    # exempt row consumes a slot in the slice (it is not a bonus); registering
    # >CAP exempt rows on one event would starve all non-exempt rows.
    rules = (
        _rule("N1", priority=90), _rule("N2", priority=85), _rule("N3", priority=80),
        _rule("EXEMPT", cap_exempt=True, priority=10),  # low priority, still sorts first
    )
    out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    assert len(out) == _reinject.REINJECT_PER_TURN_CAP  # 2
    assert "EXEMPT" in out                              # exempt sorts ahead of priority
    assert sum(1 for x in out if x.startswith("N")) == _reinject.REINJECT_PER_TURN_CAP - 1


def test_session_cap_suppresses_nonexempt(tmp_path):
    # One always-firing non-exempt rule fired SESSION_CAP+1 times (distinct check()
    # calls sharing tmp_path -> shared flocked counter): the first CAP emit, the
    # (CAP+1)th is suppressed.
    rules = (_rule("ORIENT", priority=90),)
    fired = [
        _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
        for _ in range(_reinject.REINJECT_SESSION_CAP + 1)
    ]
    assert all(r == ["ORIENT"] for r in fired[:_reinject.REINJECT_SESSION_CAP])
    assert fired[_reinject.REINJECT_SESSION_CAP] == []  # cap reached -> suppressed


def test_cap_exempt_still_fires_after_session_cap_exhausted(tmp_path):
    # THE KEYSTONE REGRESSION (mirror test_speedbump): exhaust the session cap with
    # a non-exempt row, then the cap_exempt row MUST still fire. Both fit the
    # per-turn slice (CAP=2), so each call evaluates both.
    rules = (_rule("NON", priority=90), _rule("SAFE", cap_exempt=True, priority=100))
    for _ in range(_reinject.REINJECT_SESSION_CAP):
        out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
        assert "SAFE" in out and "NON" in out
    # session cap now exhausted: NON is suppressed, SAFE (exempt) still fires.
    out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    assert out == ["SAFE"]


def test_render_exception_is_swallowed(tmp_path):
    # A reporter never crashes the hook: a render that raises is skipped, and other
    # rows still emit.
    def _boom(tn, ti, root):
        raise RuntimeError("render blew up")

    rules = (
        _reinject.ReinjectRule(id="BOOM", event="SessionStart", render=_boom),
        _rule("OK"),
    )
    assert _reinject.check("SessionStart", "", {}, tmp_path, rules=rules) == ["OK"]


def test_counter_file_is_reinject_keyed(tmp_path):
    # The flocked session counter writes reinject_count (+ .lock), NOT speedbump_count
    # -> no collision with the speed-bump registry on a shared state dir.
    _reinject.check("SessionStart", "", {}, tmp_path, rules=(_rule("X", priority=90),))
    state = tmp_path / _reinject.STATE_DIR
    assert (state / _reinject.REINJECT_COUNTER).exists()
    assert not (state / "speedbump_count").exists()


# ── 164-C: Tier-1 orientation render matrix (the SHIPPED ORIENT_RULE) ─────────

def _orient(monkeypatch, *, maint=None, stop=None, tmp_path=None):
    monkeypatch.delenv(_MAINT, raising=False)
    monkeypatch.delenv(_STOP, raising=False)
    if maint is not None:
        monkeypatch.setenv(_MAINT, maint)
    if stop is not None:
        monkeypatch.setenv(_STOP, stop)
    return _reinject._render_orientation("", {}, tmp_path or Path("."))


def test_orientation_default_is_one_host_line(monkeypatch, tmp_path):
    out = _orient(monkeypatch, tmp_path=tmp_path)
    assert out.count("\n") == 0  # exactly one line
    assert out.startswith("Host: OS=")
    assert "MAINTENANCE" not in out and "STOP_GATE" not in out  # no =off/=light noise


def test_orientation_maintenance_only_when_set(monkeypatch, tmp_path):
    assert "MAINTENANCE=on" in _orient(monkeypatch, maint="1", tmp_path=tmp_path)
    # any non-"1" value is NOT "on" -> silent
    assert "MAINTENANCE" not in _orient(monkeypatch, maint="0", tmp_path=tmp_path)


def test_orientation_stop_gate_only_when_nonlight(monkeypatch, tmp_path):
    assert "STOP_GATE=full" in _orient(monkeypatch, stop="full", tmp_path=tmp_path)
    assert "STOP_GATE" not in _orient(monkeypatch, stop="light", tmp_path=tmp_path)
    assert "STOP_GATE" not in _orient(monkeypatch, tmp_path=tmp_path)  # unset -> silent


def test_orientation_all_modes_three_lines_single_payload(monkeypatch, tmp_path):
    # The exact case the re-run flagged: maint + full-gate. A SINGLE payload of 3
    # lines -> the per-turn ceiling (CAP=2) can never clip the 3rd fact.
    out = _orient(monkeypatch, maint="1", stop="full", tmp_path=tmp_path)
    assert out.count("\n") == 2  # 3 lines in one payload
    assert "Host: OS=" in out and "MAINTENANCE=on" in out and "STOP_GATE=full" in out
    # and as a registry row it is a SINGLE matched payload (never ceiling-clipped):
    payloads = _reinject.check("SessionStart", "", {}, tmp_path,
                               rules=(_reinject.ORIENT_RULE,))
    assert len(payloads) == 1 and "STOP_GATE=full" in payloads[0]


# ── 164-D: Rule-A consolidation parity (the SHIPPED RULE_A via the hook) ──────

def test_rule_a_metadata():
    assert _reinject.RULE_A.event == "PostToolUseFailure"
    assert _reinject.RULE_A.cap_exempt is True  # safety: never session-cap-suppressed
    assert "stale or" in _reinject.RULE_A.render("", {}, Path("."))


def _run_failure_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "context_reinject_failure.py")],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30, encoding="utf-8",
    )


def test_rule_a_fires_once_on_old_string_failure():
    # Real Claude Code phrasing. Exactly ONE additionalContext block, correct event.
    r = _run_failure_hook({"tool_name": "Edit",
                           "tool_response": "String to replace not found in file"})
    assert r.returncode == 0
    blocks = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(blocks) == 1, r.stdout
    hso = json.loads(blocks[0])["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUseFailure"
    assert "re-anchor" in hso["additionalContext"]


@pytest.mark.parametrize("payload", [
    {"tool_name": "Write", "tool_response": "No such file or directory"},  # parent-dir
    {"tool_name": "Edit", "tool_response": "Permission denied"},           # permission
    {"tool_name": "Bash", "tool_response": "String to replace not found in file"},  # wrong tool
])
def test_rule_a_silent_on_unrelated_failures(payload):
    r = _run_failure_hook(payload)
    assert r.returncode == 0
    assert r.stdout.strip() == ""  # silent: no reinject next to an unrelated error


# ── TP-209: the PostToolUse reinject CALL SITE is self-host-gated ─────────────
# The PostToolUse sync rows surface SELF-HOST multi-surface-sync guidance
# whose witnesses name Espalier engine internals (cli.py::INIT_HOOK_SCRIPTS,
# examples/dogfooding/, tests/...). The gate lives in post_write_check._run_main
# at the call site -- NOT inside _reinject.check() -- so these tests must drive
# main() end-to-end, unlike the check()-level fixtures above. (The born-weak
# observer 28 lines below the call site is the gated exemplar this mirrors.)
def _run_post_write_check_capturing_reinject(tmp_path, monkeypatch, *, tool_name, file_path):
    """Drive ``post_write_check._run_main`` with stubbed stdin + project root and
    return the list of PostToolUse reinject ``additionalContext`` payloads emitted
    on stdout (``[]`` when none). TP-209 earn-the-red capture helper."""
    event = {"tool_name": tool_name,
             "tool_input": {"file_path": file_path, "content": "x"}}
    monkeypatch.setattr(_pwc, "_resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr(_hook_utils, "read_stdin_safely", lambda: event)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _pwc._run_main()
    out = []
    for line in buf.getvalue().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        hso = obj.get("hookSpecificOutput", {})
        if hso.get("hookEventName") == "PostToolUse" and hso.get("additionalContext"):
            out.append(hso["additionalContext"])
    return out


def test_postool_reinject_suppressed_off_self_host(tmp_path, monkeypatch):
    # Adopter repo: is_self_host_repo(root) is False -> the PostToolUse sync rows
    # (engine-internal witnesses) must NOT be injected into the adopter's session.
    # REDS against the ungated body (COMMAND_SYNC_RULE fires on a command Write).
    monkeypatch.setattr(_hook_utils, "is_self_host_repo", lambda root: False)
    payloads = _run_post_write_check_capturing_reinject(
        tmp_path, monkeypatch, tool_name="Write", file_path=".claude/commands/foo.md")
    assert payloads == []


def test_postool_reinject_fires_on_self_host(tmp_path, monkeypatch):
    # Self-host: the sync guidance is correct here, so the gate must NOT suppress it
    # (no self-host regression).
    monkeypatch.setattr(_hook_utils, "is_self_host_repo", lambda root: True)
    payloads = _run_post_write_check_capturing_reinject(
        tmp_path, monkeypatch, tool_name="Write", file_path=".claude/commands/foo.md")
    assert payloads  # the command five-surface-sync witness still fires




# ── recall-engine telemetry: the appender, the gates, the naming invariant ────


def _load_hook_module(name: str):
    """Load a ``tools/cc/hooks/<name>.py`` module with its sibling deps importable.

    Mirrors ``tests/test_state_file_flag_parity.py``: load through
    ``spec_from_file_location`` (never a plain import) so espalier is never
    dragged into the hooks' zero-import graph.
    """
    spec = importlib.util.spec_from_file_location(name, str(HOOKS_DIR / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def telemetry_on(monkeypatch):
    """Opt this test back into telemetry writes.

    BOTH gates suppress by default (`_hook_utils._telemetry_enabled`): a pytest
    run is not an operator session, and a tmp_path is not the self-host repo.
    A test that wants rows must say so explicitly — which is what keeps the
    suite from writing into the very instrument it is testing.
    """
    monkeypatch.setenv(_hook_utils.TELEMETRY_TEST_OPT_IN, "1")
    monkeypatch.setattr(_hook_utils, "is_self_host_repo", lambda root: True)


def _recall_rows(root):
    """Every telemetry row written under ``root``'s state dir (empty list if none)."""
    log = root / _hook_utils.STATE_DIR / _hook_utils.RECALL_LOG_NAME
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln]


# ── the two gates ────────────────────────────────────────────────────────────


def test_telemetry_is_suppressed_under_pytest(tmp_path, monkeypatch):
    """The suite must not write into the instrument it measures.

    Deliberately does NOT take the `telemetry_on` fixture. Measured before this
    gate existed: 89% of the live log's rows were suite artifacts, and
    conftest's autouse live-tree write guard does not watch STATE_DIR, so
    nothing else would have caught it. REDS if the PYTEST_CURRENT_TEST check is
    removed from `_telemetry_enabled`.
    """
    monkeypatch.setattr(_hook_utils, "is_self_host_repo", lambda root: True)  # isolate the pytest gate
    rules = (_rule("HI", priority=90),)
    out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    assert out == ["HI"]              # the advisory itself is unaffected
    assert not _recall_rows(tmp_path)  # ...but nothing was recorded


def test_telemetry_is_suppressed_off_self_host(tmp_path, monkeypatch):
    """Adopter repos record nothing.

    The pull side captures the operator's raw /recall query text; capturing an
    adopter's prompts — even to a gitignored local file — is a consent question
    this harness does not open unasked. Mirrors the born-weak observation log,
    which is self-host-gated for the same reason. REDS if the
    `is_self_host_repo` check is removed from `_telemetry_enabled`.
    """
    monkeypatch.setenv(_hook_utils.TELEMETRY_TEST_OPT_IN, "1")  # isolate the self-host gate
    monkeypatch.setattr(_hook_utils, "is_self_host_repo", lambda root: False)
    _reinject.check("SessionStart", "", {}, tmp_path, rules=(_rule("HI", priority=90),))
    assert not _recall_rows(tmp_path)


# ── the appender ─────────────────────────────────────────────────────────────


def test_append_jsonl_writes_one_row_per_call(tmp_path):
    # Happy path: two calls -> two parseable JSONL rows, in order, plus the
    # stable sibling lock file the flock is taken on. (_append_jsonl is the raw
    # helper and carries no gates of its own — those live in _telemetry_enabled.)
    _hook_utils._append_jsonl(tmp_path, "t.jsonl", {"a": 1})
    _hook_utils._append_jsonl(tmp_path, "t.jsonl", {"a": 2})
    rows = [json.loads(ln) for ln in
            (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["a"] for r in rows] == [1, 2]
    # The ROW assertions above are the cross-platform contract and hold
    # everywhere. The sentinel below is POSIX-only: `_append_jsonl` imports
    # fcntl and, on ImportError, takes a documented best-effort unlocked
    # append that never creates it. Asserting it unconditionally reddened on
    # Windows over a mechanism that is absent by design, not broken.
    if _fcntl is not None:
        assert (tmp_path / "t.jsonl.lock").exists()  # STABLE sibling, not the log fd


def test_append_jsonl_stamps_ts_and_session(tmp_path):
    """Every row carries a clock and a session key.

    Without both, the log cannot answer the question it exists for: the
    ceilings it measures are PER-SESSION quantities, so cross-session rows with
    no delimiter cannot be grouped — and a pile of byte-identical rows carrying
    only a count answers that question confidently WRONG. REDS if either
    setdefault is dropped.
    """
    (tmp_path / "session_started").write_text("2026-08-06T21:00:00+00:00", encoding="utf-8")
    _hook_utils._append_jsonl(tmp_path, "t.jsonl", {"a": 1})
    row = json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["ts"].startswith("20")                      # ISO-8601 UTC stamp
    assert row["session"] == "2026-08-06T21:00:00+00:00"   # groups rows by session
    assert row["a"] == 1                                   # caller's fields survive


def test_append_jsonl_survives_a_latin1_session_marker(tmp_path):
    """Ledger DEF-829: ``UnicodeDecodeError`` is a ``ValueError``, so the
    ``except OSError`` around the marker read let it past and the whole
    telemetry append died. The marker is a key, read with a replacement
    character; the row is still written and still grouped."""
    (tmp_path / "session_started").write_bytes(b"2026-08-06T21:00:00+00:00 caf\xe9")
    _hook_utils._append_jsonl(tmp_path, "t.jsonl", {"a": 1})
    row = json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["session"] == "2026-08-06T21:00:00+00:00 caf\ufffd"  # the replace arm, pinned


def test_append_jsonl_session_is_empty_when_marker_absent(tmp_path):
    # A hook firing before the first SessionStart must still record, not crash.
    _hook_utils._append_jsonl(tmp_path, "t.jsonl", {"a": 1})
    assert json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8"))["session"] == ""


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores directory write permissions",
)
def test_append_jsonl_read_only_dir_is_silent(tmp_path):
    # The fail-open contract, not just the happy path: telemetry is NEVER
    # load-bearing, so an unwritable state dir must return silently and write
    # nothing rather than raise an OSError that fail-opens the whole hook event.
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)  # read+exec only
    try:
        # PRECONDITION PROBE, not a platform skipif. `os.chmod` on Windows
        # only toggles the read-only FILE attribute, which does not apply to
        # directories -- so the deny this test needs was never staged, the
        # write below succeeded, and the assertion failed against a tree that
        # was never read-only. The safety contract did not break; its premise
        # was never established. Asked by DOING the write, the way
        # `tests/test_integrity.py::_traversal_denied` asks its question, so
        # root and permissive network mounts are covered by the same guard.
        probe = ro / ".write-probe"
        try:
            probe.touch()
        except OSError:
            pass                      # good -- the directory really is unwritable
        else:
            probe.unlink()
            pytest.skip("chmod did not deny writes on this platform")
        _hook_utils._append_jsonl(ro, "t.jsonl", {"a": 1})  # must not raise
        assert not (ro / "t.jsonl").exists()
    finally:
        ro.chmod(0o755)  # restore so tmp_path cleanup can unlink


# ── push-side dispositions ───────────────────────────────────────────────────


def test_per_turn_capped_rules_are_logged(tmp_path, telemetry_on):
    # THE gap this closes: a rule that matched but lost the [:CAP] race left NO
    # trace, so "matched and was throttled" and "never matched" were the same
    # observation. 3 rules, CAP=2 -> exactly one per_turn_capped row, naming the
    # LOSING rule.
    rules = (_rule("HI", priority=90), _rule("MID", priority=80), _rule("LO", priority=70))
    out = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    assert out == ["HI", "MID"]  # unchanged emit behavior
    capped = [r for r in _recall_rows(tmp_path) if r["disposition"] == "per_turn_capped"]
    assert len(capped) == 1, f"expected exactly 1 per_turn_capped row, got {capped}"
    assert capped[0]["rid"] == "LO"
    assert capped[0]["side"] == "push" and capped[0]["event"] == "SessionStart"


def test_emitted_rules_are_logged_with_rule_id(tmp_path, telemetry_on):
    # Per-rule attribution: `matched` carried no rule id before this landed, so
    # no rule could be named in telemetry at all.
    rules = (_rule("HI", priority=90), _rule("MID", priority=80))
    _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    emitted = [r for r in _recall_rows(tmp_path) if r["disposition"] == "emitted"]
    assert sorted(r["rid"] for r in emitted) == ["HI", "MID"]


def test_session_capped_rules_are_logged(tmp_path, telemetry_on):
    # The third disposition: suppressed by the SESSION cap, not the per-turn one.
    rules = (_rule("ORIENT", priority=90),)
    for _ in range(_reinject.REINJECT_SESSION_CAP + 1):
        _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    rows = _recall_rows(tmp_path)
    assert sum(1 for r in rows if r["disposition"] == "emitted") == \
        _reinject.REINJECT_SESSION_CAP
    assert sum(1 for r in rows if r["disposition"] == "session_capped") == 1


def test_telemetry_does_not_change_what_gets_injected(tmp_path, telemetry_on):
    # An instrument that changes the thing it measures is not an instrument:
    # check()'s return must be identical with telemetry writing and with the
    # emitter neutered.
    rules = (
        _rule("N1", priority=90), _rule("N2", priority=85), _rule("N3", priority=80),
        _rule("EXEMPT", cap_exempt=True, priority=10),
    )
    with_telemetry = _reinject.check("SessionStart", "", {}, tmp_path, rules=rules)
    silent = tmp_path / "silent"
    orig = _reinject._log_recall_event
    try:
        _reinject._log_recall_event = lambda *a, **k: None
        without_telemetry = _reinject.check("SessionStart", "", {}, silent, rules=rules)
    finally:
        _reinject._log_recall_event = orig
    assert with_telemetry == without_telemetry
    assert not _recall_rows(silent)  # the neutered emitter really wrote nothing


# ── the cleanup-glob naming invariant (the whole persistence family) ──────────


@pytest.mark.parametrize("persistent_name", [
    "session_length_baseline",        # stop_gate rolling history
    "born_weak_observations.jsonl",   # born-weak observer log
    _hook_utils.RECALL_LOG_NAME,      # recall-engine telemetry
])
def test_state_dir_rolling_history_survives_a_session_boundary(tmp_path, persistent_name):
    """Every cross-session rolling-history file must miss both cleanup globs.

    `session_start._clean_state_flags` unlinks `speedbump_*` and `reinject_*` at
    every non-continuation SessionStart. Three files in that directory are
    rolling history and survive ONLY because their names miss those globs — a
    naming coincidence carrying a durable invariant that was documented in a
    comment and asserted by no test. Parametrized over the whole family rather
    than the newest member: the defect is a CLASS, and pinning one instance
    would leave the other two exactly as unguarded as they were.

    Asserted BEHAVIORALLY, not against a transcribed copy of the flag list —
    the list and both globs are inline literals inside the function body, so
    there is nothing importable to compare to and a hand-copied list would be
    the very transcription defect this repo tracks.

    EARN THE RED: the `reinject_probe` control DOES match the glob. Renaming
    any member to a matching prefix reds this; the control's own deletion
    proves in the same run that cleanup actually executed, so a green here can
    never come from cleanup having silently not run at all.
    """
    session_start = _load_hook_module("session_start")
    state = tmp_path / _hook_utils.STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    (state / persistent_name).write_text("rolling history\n", encoding="utf-8")
    (state / "reinject_probe").write_text("x", encoding="utf-8")

    session_start._clean_state_flags(tmp_path)  # default source -> a NEW logical session

    assert (state / persistent_name).exists(), (
        f"{persistent_name} was erased by _clean_state_flags -- a cross-session "
        "rolling-history file must not match the speedbump_* or reinject_* cleanup "
        "globs, or its history is destroyed at every SessionStart and the symptom "
        "is an empty file, indistinguishable from an instrument that never fired"
    )
    assert not (state / "reinject_probe").exists(), (
        "control file survived -- the reinject_* glob did not run, so this test's "
        "green would not have proven anything"
    )
