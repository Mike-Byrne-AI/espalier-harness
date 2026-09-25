"""Earn-fixture for the speed-bump mechanism (TP-159-E).

Proves the mechanism against a SYNTHETIC canary registry (NOT the real
checkpoints — those ship in TP-160/161/162): deny-once-then-allow, the session
cap, the cap-exemption exhaustion regression (the keystone fix, blueprint §11 #1),
per-key flag namespacing, the reason-template shape, and predicate-error safety.
"""
# pytest-marker: default-unit  (in-process check() calls against a canary registry
# with tmp_path state dirs; no subprocess, no security/integration surface)
from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _speedbump  # noqa: E402


def _always(tool_name, tool_input, root, cwd=None):
    # The registry contract since DEF-790: `check_fired` hands every predicate
    # the directory the command runs in as a fourth argument.
    return True


def _bump(id_, *, cap_exempt=False, flag_key=None, predicate=_always, body="canary reminder"):
    return _speedbump.SpeedBump(
        id=id_, predicate=predicate, body=body,
        cap_exempt=cap_exempt, flag_key=flag_key,
    )


def test_deny_once_then_allow(tmp_path):
    bumps = (_bump("CP-CANARY"),)
    first = _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps)
    assert first is not None and "CP-CANARY" in first
    second = _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps)
    assert second is None  # flag set on the first fire IS the retry-allow


def test_session_cap_suppresses_nonexempt(tmp_path):
    # 5 distinct non-exempt canary bumps. check() fires the first un-flagged one
    # each call, so 5 calls walk CP-0..CP-4; the cap (4) suppresses the 5th.
    bumps = tuple(_bump(f"CP-{i}") for i in range(5))
    fired = [
        _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps)
        for _ in range(5)
    ]
    assert all(r is not None for r in fired[:4])  # counter climbs 1->4
    assert fired[4] is None  # cap reached -> 5th non-exempt bump suppressed


def test_cap_exempt_still_fires_after_exhaustion(tmp_path):
    # THE KEYSTONE REGRESSION (blueprint §11 #1): exhaust the cap with 4 non-exempt
    # bumps, then a cap_exempt bump MUST still fire. This goes RED against a design
    # where the global SPEEDBUMP_SESSION_CAP counts every fire (the pre-v6 defect).
    nonexempt = tuple(_bump(f"CP-{i}") for i in range(4))
    keystone = _bump("CP-KEYSTONE", cap_exempt=True)
    bumps = nonexempt + (keystone,)
    for _ in range(4):
        assert _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps) is not None
    # cap is now exhausted (4/4); a non-exempt 5th would be suppressed, but the
    # keystone is cap_exempt -> it STILL fires:
    reason = _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps)
    assert reason is not None and "CP-KEYSTONE" in reason


def test_cap_exempt_does_not_consume_a_slot(tmp_path):
    # A cap_exempt bump must NOT inflate the counter (else a storm of exempt fires
    # could still bury later non-exempt bumps). Fire the keystone first, then prove
    # all 4 non-exempt slots are still available.
    keystone = _bump("CP-KEYSTONE", cap_exempt=True)
    nonexempt = tuple(_bump(f"CP-{i}") for i in range(5))
    assert _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=(keystone,)) is not None
    fired = [
        _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=nonexempt)
        for _ in range(5)
    ]
    assert all(r is not None for r in fired[:4])  # exempt fire consumed no slot
    assert fired[4] is None


def test_flag_key_namespaces(tmp_path):
    # A per-file flag_key (the TP-161 hook): each distinct file fires once; the
    # same file twice fires once.
    bump = (
        _bump("CP-PERFILE",
              flag_key=lambda tn, ti: (ti.get("file_path") or "").rsplit("/", 1)[-1]),
    )
    a1 = _speedbump.check("Edit", {"file_path": "a/x.py"}, tmp_path, bumps=bump)
    b1 = _speedbump.check("Edit", {"file_path": "b/y.py"}, tmp_path, bumps=bump)
    a2 = _speedbump.check("Edit", {"file_path": "a/x.py"}, tmp_path, bumps=bump)
    assert a1 is not None and b1 is not None  # two different files each fire
    assert a2 is None  # x.py already fired -> distinct flag key from y.py


def test_reason_template_shape(tmp_path):
    bumps = (_bump("CP-SHAPE", body="do the thing"),)
    reason = _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps)
    assert reason == _speedbump._REASON_TEMPLATE.format(id="CP-SHAPE", body="do the thing")
    assert reason.startswith("Speed-bump [CP-SHAPE]:")
    assert "re-issue the same command to proceed" in reason  # the SOFT-deny clause
    assert len(reason.encode("utf-8")) <= 512


def test_body_for_is_preferred_and_falls_back_to_the_static_body(tmp_path):
    """DEF-802: a checkpoint may carry a per-fire body beside its static one
    (the two snapshot promises read what `snapshot_discard` recorded). The
    per-fire text wins on the fire; a fault in it never costs the fire, which
    falls back to the static body; a checkpoint without one is unchanged."""
    seen = []

    def _dynamic(tool_name, tool_input, root, cwd=None):
        seen.append((tool_name, tool_input["command"], root, cwd))
        return "the text for this fire"

    def _boom(tool_name, tool_input, root, cwd=None):
        raise RuntimeError("per-fire text blew up")

    dynamic = _speedbump.SpeedBump(id="CP-DYN", predicate=_always, body="static", body_for=_dynamic)
    faulty = _speedbump.SpeedBump(id="CP-FAULT", predicate=_always, body="static", body_for=_boom)
    reason = _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=(dynamic,), cwd=tmp_path / "sub")
    assert reason == _speedbump._REASON_TEMPLATE.format(id="CP-DYN", body="the text for this fire")
    assert seen == [("Bash", "x", tmp_path, tmp_path / "sub")]   # it sees what the predicate sees
    reason = _speedbump.check("Bash", {"command": "y"}, tmp_path, bumps=(faulty,))
    assert reason == _speedbump._REASON_TEMPLATE.format(id="CP-FAULT", body="static")
    assert _bump("CP-PLAIN").body_for is None   # the trailing default: positional shapes unchanged


def test_predicate_error_does_not_block(tmp_path):
    def _boom(tool_name, tool_input, root, cwd=None):
        raise RuntimeError("predicate blew up")

    bumps = (_bump("CP-BOOM", predicate=_boom),)
    assert _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps) is None


def test_non_matching_predicate_returns_none(tmp_path):
    bumps = (_bump("CP-NOPE", predicate=lambda t, i, r, cwd=None: False),)
    assert _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=bumps) is None


def test_empty_registry_returns_none(tmp_path):
    assert _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=()) is None


def test_every_registry_predicate_takes_the_four_argument_call(tmp_path):
    """`check_fired` hands every predicate the directory the command runs in
    as a fourth argument (DEF-790) inside an `except Exception` that reads a
    TypeError as "does not fire" -- so a predicate written to the older
    three-argument shape would go silently dead. Every registry entry is
    called the way the hook calls it, outside that net."""
    for bump in _speedbump.SPEEDBUMPS:
        for tool in ("Bash", "PowerShell", "Edit"):
            verdict = bump.predicate(tool, {"command": "", "file_path": ""}, tmp_path, None)
            assert verdict in (True, False), (bump.id, tool, verdict)
