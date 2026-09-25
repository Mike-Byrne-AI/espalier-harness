"""Earn-the-red + must-NOT-trip for the born-weak co-occurrence OBSERVER.

The observer (inlined in ``post_write_check``) is itself a guard, so per the
recursive-risk principle it ships BOTH directions of the Tier-1 discipline it
embodies: it FIRES on a planted born-weak co-occurrence (non-vacuous green) and
it STAYS SILENT on born-RIGHT work (a suppression shipped with a paired negative
fixture / reasoned skip, a new scanner carrying only the mandated
``tests/fixtures/`` quarantine, a normal refactor). It is OBSERVE-ONLY: these
tests assert detection + logging, never a block.
"""
# pytest-marker: default-unit  (in-process pure-function + tmp_path log/orchestrator
# calls; no subprocess, no security/integration surface)
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import post_write_check as p  # noqa: E402

_SCANNER = "espalier/scanners/foo.py"


# --- EARN-THE-RED: the detector FIRES on real born-weak co-occurrence ---------
def test_fires_scanner_grows_broad_exempt_and_adds_rule():
    old = 'EXEMPT_PREFIXES = ("tests/fixtures/",)\n'
    new = 'EXEMPT_PREFIXES = ("tests/fixtures/", "espalier/")\nfindings.append(x)\n'
    rec = p.observe_born_weak(_SCANNER, old_content=old, new_content=new)
    assert rec is not None
    assert rec["co_occurrence"] is True
    assert "scanner_rule_added" in rec["guard_signals"]
    assert "exempt_list_grew" in rec["suppression_signals"]


def test_fires_annotated_tuple_exempt_grows():
    # the REAL scanner convention is the ANNOTATED form, NOT the bare form.
    # v1 of the regex matched only the bare form -> the signal was dead in
    # production (the observer's own born-weak collision). Pin the live form.
    # old has no rule; new adds BOTH a finding rule (guard born) and a broad
    # non-fixture exempt (suppression) -> the born-weak co-occurrence.
    old = 'EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/",)\n'
    new = 'EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/", "espalier/")\nfindings.append(x)\n'
    rec = p.observe_born_weak(_SCANNER, old_content=old, new_content=new)
    assert rec is not None and "exempt_list_grew" in rec["suppression_signals"]


def test_fires_frozenset_exempt_grows():
    old = 'EXEMPT_FILES: frozenset[str] = frozenset({"a.py"})\n'
    new = 'EXEMPT_FILES: frozenset[str] = frozenset({"a.py", "espalier/cli.py"})\nfindings.append(x)\n'
    rec = p.observe_born_weak(_SCANNER, old_content=old, new_content=new)
    assert rec is not None and "exempt_list_grew" in rec["suppression_signals"]


def test_exempt_counter_matches_live_scanner_convention():
    # Regression against the dead-regex bug: the counter must see a non-fixture
    # carve-out in the exact annotated/frozenset forms the real scanners use.
    assert p._bw_count_exempt_entries(
        'EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/", "espalier/")') == 1
    assert p._bw_count_exempt_entries(
        'EXEMPT_FILES: frozenset[str] = frozenset({"a.py"})') == 1
    # the mandated fixture-only exemption still counts zero (born-RIGHT).
    assert p._bw_count_exempt_entries(
        'EXEMPT_PREFIXES: tuple[str, ...] = ("tests/fixtures/",)') == 0


def test_fires_test_born_with_assertion_removed():
    old = "def test_a():\n    assert foo()\n    assert bar()\n"
    new = "def test_a():\n    assert foo()\ndef test_b():\n    pass\n"
    rec = p.observe_born_weak("tests/test_thing.py", old_content=old, new_content=new)
    assert rec is not None
    assert "test_function_born" in rec["guard_signals"]
    assert "assertion_removed" in rec["suppression_signals"]


def test_fires_guard_hook_deny_added_with_skip():
    old = "def check():\n    pass\n"
    new = "def check():\n    return deny('x')\n@pytest.mark.skip\ndef test_z():\n    pass\n"
    rec = p.observe_born_weak("tools/cc/hooks/write_guard.py", old_content=old, new_content=new)
    assert rec is not None
    assert "deny_path_added" in rec["guard_signals"]
    assert "skip_or_xfail_added" in rec["suppression_signals"]


# --- MUST-NOT-TRIP: silent on born-RIGHT work + non-targets -------------------
def test_silent_when_paired_negative_fixture_added():
    # the BLESSED pattern: broad exempt grows BUT a negative fixture ships too.
    old = 'EXEMPT_PREFIXES = ("tests/fixtures/",)\nfindings.append(x)\n'
    new = ('EXEMPT_PREFIXES = ("tests/fixtures/", "espalier/")\nfindings.append(x)\n'
           '# see foo_negatives.py proving it still fires on a non-exempt twin\n_negatives\n')
    assert p.observe_born_weak(_SCANNER, old_content=old, new_content=new) is None


def test_silent_on_reasoned_skip():
    old = "def test_a():\n    assert foo()\n"
    new = "def test_a():\n    assert foo()\n@pytest.mark.skip(reason='tracked in TP-999')\ndef test_b():\n    pass\n"
    assert p.observe_born_weak("tests/test_thing.py", old_content=old, new_content=new) is None


def test_silent_new_scanner_with_only_mandated_fixture_exemption():
    # a brand-new scanner shipping ONLY the standard tests/fixtures/ quarantine
    # is born-RIGHT, not born-weak -- the non-fixture exempt count is zero.
    new = 'EXEMPT_PREFIXES = ("tests/fixtures/",)\nfindings.append(x)\n'
    assert p.observe_born_weak(_SCANNER, old_content="", new_content=new) is None


def test_silent_on_non_guard_path():
    old = 'EXEMPT_PREFIXES = ("tests/fixtures/",)\n'
    new = 'EXEMPT_PREFIXES = ("tests/fixtures/", "espalier/")\nfindings.append(x)\n'
    assert p.observe_born_weak("espalier/cli.py", old_content=old, new_content=new) is None


def test_silent_guard_material_without_suppression():
    assert p.observe_born_weak(_SCANNER, old_content="", new_content="findings.append(x)\n") is None


def test_silent_suppression_without_born_guard():
    # a broad exempt grows but NO new detection surface -> not "born" weak.
    old = 'EXEMPT_PREFIXES = ("tests/fixtures/",)\nfindings.append(x)\n'
    new = 'EXEMPT_PREFIXES = ("tests/fixtures/", "espalier/")\nfindings.append(x)\n'
    assert p.observe_born_weak(_SCANNER, old_content=old, new_content=new) is None


def test_silent_on_normal_refactor():
    old = "def helper():\n    return compute()\n"
    new = "def helper():\n    return compute() + 1\n"
    assert p.observe_born_weak("tests/test_thing.py", old_content=old, new_content=new) is None


def test_the_observer_is_inside_its_own_population():
    """Harm B, applied to the observer itself.

    This module's declared subject is "a guard born blind -- green but never
    catching". Its guard-material population was a five-name tuple
    (write_guard, plan_guard, config_guard, stop_gate, _speedbump), and the two
    hook files it omitted were THIS observer and its host, post_write_check.py.
    Measured before the fix: 215 recorded observations, zero for either path. No
    edit to the observer had ever been eligible for observation -- the exact
    shape it exists to catch, in the instrument built to catch it.

    Note this is NOT in tension with `test_silent_on_own_defining_material`
    below. That pins Harm A (a guard firing on the material that DEFINES its
    pattern) for the fixture corpus and this test file, whose content IS the
    pattern. The observer's source is different: `_bw_guard_signals` is a count
    delta, so carrying the tokens as literals cannot fire it -- only ADDING one
    does, and adding a deny path to the observer is real guard development.

    Derivation, not enumeration: a re-added name tuple reds this.
    """
    assert p._bw_is_guard_material("tools/cc/hooks/_born_weak.py"), (
        "the born-weak observer excludes ITSELF from the population of files it "
        "watches for born-weak guards"
    )
    assert p._bw_is_guard_material("tools/cc/hooks/post_write_check.py"), (
        "the observer excludes its own HOST hook, so an edit that weakens the "
        "call site is invisible to it"
    )
    # The previously-enumerated five must still qualify -- widening, not swapping.
    for name in ("write_guard.py", "plan_guard.py", "config_guard.py",
                 "stop_gate.py", "_speedbump.py"):
        assert p._bw_is_guard_material(f"tools/cc/hooks/{name}"), name
    # And the widening must not swallow non-guard material.
    assert not p._bw_is_guard_material("espalier/cli.py")
    assert not p._bw_is_guard_material("tools/cc/hooks/notes.md")


def test_silent_on_own_defining_material():
    # Invariant #1 (own your trigger; never scan your own DEFINING material): the
    # scanner fixtures and the observer's OWN test carry born-weak example tokens,
    # so observing them self-collides (Harm A). This is the live false-positive the
    # full-suite gate caught -- the observer logged on its own test file.
    bw = 'EXEMPT_PREFIXES = ("espalier/",)\nfindings.append(x)\ndef test_z(): pass\n'
    assert not p._bw_is_guard_material("tests/fixtures/foo_negatives.py")
    assert not p._bw_is_guard_material("tests/test_born_weak_observer.py")
    assert p.observe_born_weak("tests/test_born_weak_observer.py", old_content="", new_content=bw) is None
    assert p.observe_born_weak("tests/fixtures/x_negatives.py", old_content="", new_content=bw) is None


# --- LOG + ORCHESTRATOR -------------------------------------------------------
def test_log_observation_appends_timestamped_jsonl(tmp_path):
    rec = {"path": _SCANNER, "guard_signals": ["scanner_rule_added"],
           "suppression_signals": ["exempt_list_grew"], "co_occurrence": True}
    fixed = datetime(2026, 6, 15, tzinfo=timezone.utc)
    p.bw_log_observation(tmp_path, rec, now=fixed)
    p.bw_log_observation(tmp_path, rec, now=fixed)
    log = tmp_path / ".espalier-state" / "born_weak_observations.jsonl"
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["ts"] == fixed.isoformat()
    assert first["path"] == _SCANNER


def test_orchestrator_logs_born_weak_new_file(tmp_path):
    # new file (no git -> HEAD show fails -> old=''); a broad non-fixture exempt
    # + a born scanner with no paired negative -> a logged observation.
    rel = "espalier/scanners/foo.py"
    (tmp_path / "espalier" / "scanners").mkdir(parents=True)
    (tmp_path / rel).write_text(
        'EXEMPT_PREFIXES = ("espalier/",)\nfindings.append(x)\n', encoding="utf-8")
    rec = p._observe_born_weak(tmp_path, rel)
    assert rec is not None and rec["co_occurrence"] is True
    assert (tmp_path / ".espalier-state" / "born_weak_observations.jsonl").exists()


def test_orchestrator_silent_on_born_right_new_scanner(tmp_path):
    rel = "espalier/scanners/bar.py"
    (tmp_path / "espalier" / "scanners").mkdir(parents=True)
    (tmp_path / rel).write_text(
        'EXEMPT_PREFIXES = ("tests/fixtures/",)\nfindings.append(x)\n', encoding="utf-8")
    assert p._observe_born_weak(tmp_path, rel) is None
    assert not (tmp_path / ".espalier-state" / "born_weak_observations.jsonl").exists()


def test_orchestrator_never_raises_on_missing_file(tmp_path):
    # best-effort contract: a guard-material path that does not exist -> None, no raise.
    assert p._observe_born_weak(tmp_path, "espalier/scanners/ghost.py") is None


def test_orchestrator_rejects_out_of_repo_paths(tmp_path):
    # Containment: the observer runs BEFORE post_write_check's _is_harness_file
    # gate, so an absolute / parent-relative path must NOT read out-of-repo content
    # or log an out-of-boundary record (adversarial review).
    outside = tmp_path.parent / "sibling" / "espalier" / "scanners" / "x.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text('EXEMPT_PREFIXES = ("espalier/",)\nfindings.append(x)\n', encoding="utf-8")
    assert p._observe_born_weak(tmp_path, str(outside)) is None                # absolute
    assert p._observe_born_weak(tmp_path, "../sibling/espalier/scanners/x.py") is None  # ../
    assert not (tmp_path / ".espalier-state" / "born_weak_observations.jsonl").exists()


def test_bw_log_observation_serializes_under_flock(tmp_path):
    """DR7 round-7 (TP-196) earn-the-red: the JSONL append must be serialized
    under an fcntl.flock on a STABLE sibling lock file so two concurrent
    PostToolUse hooks (parent repo + a worktree sharing one .espalier-state)
    cannot interleave a partial >512-byte record into one malformed line.
    Pre-fix the append was unlocked → no lock sibling. Pins: the record lands
    intact AND the serialization point (the .lock) exists on POSIX."""
    p.bw_log_observation(tmp_path, {"rel_path": "x", "kind": "y"})
    state = tmp_path / ".espalier-state"
    lines = (state / p._BW_LOG_NAME).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["rel_path"] == "x" and "ts" in rec
    try:
        import fcntl  # noqa: F401  availability probe; Windows skips the lock sibling
    except ImportError:
        return
    assert (state / (p._BW_LOG_NAME + ".lock")).exists(), \
        "flock sibling missing — the append is not serialized"
