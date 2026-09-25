"""Source-aware blueprint-chain advancement in ``session_start.py``.

The SessionStart hook fires on four sources (``startup``, ``resume``,
``clear``, ``compact`` — confirmed against the official CC hooks docs). Only
``startup``/``clear`` begin a NEW logical session and should advance the
blueprint chain (start a fresh node); ``resume``/``compact`` CONTINUE an
existing session, and ``compact`` fires mid-session on every compaction, so
advancing there would fragment the chain. This moves chain-advancement off the
operator's manual post-``/clear`` ``/context-load`` habit and into the hook.

These tests pin the source→advancement policy and guard against the
compact-fragmentation regression (advancing on every compaction) and the
clobber-a-present-but-unreadable-blueprint failure mode; without this contract
a refactor that drops the source gate would silently reintroduce both.

Earn-the-red: before this change ``_should_advance_chain`` did not exist
(AttributeError) and ``_load_blueprint`` started a node ONLY when ``load`` came
back empty — so a ``startup``/``clear`` with an existing prior never advanced,
and the integration tests below would see node_count stay flat on a
new-session source.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
SESSION_START = TOOLS_CC / "hooks" / "session_start.py"


def _import_session_start():
    """Load the hook module fresh with the correct sys.path discipline."""
    hooks_dir = TOOLS_CC / "hooks"
    tools_cc_dir = TOOLS_CC
    sys.path.insert(0, str(hooks_dir))
    sys.path.insert(0, str(tools_cc_dir))
    if "session_start" in sys.modules:
        del sys.modules["session_start"]
    import session_start  # type: ignore[import-not-found]
    return session_start


# ── unit: the policy ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,expected",
    [
        ("startup", True),
        ("clear", True),
        ("resume", False),
        ("compact", False),
        ("", False),
        ("bogus", False),
    ],
)
def test_should_advance_chain_policy(source, expected):
    ss = _import_session_start()
    assert ss._should_advance_chain(source) is expected


@pytest.mark.parametrize(
    "source,cleared",
    [
        ("startup", True), ("clear", True),
        ("compact", False), ("resume", False),
        ("", True), ("bogus", True),
    ],
)
def test_clean_state_flags_gated_on_new_session(tmp_path, source, cleared):
    """D-1: per-session gate counters (write_count, speedbump_*) are wiped on every
    source EXCEPT a mid-session compact/resume continuation, which must PRESERVE
    them (else stop_gate Gate 2/3 (write_count>=10) + shown speedbumps rewind).
    An unlabeled/unknown payload clears — a genuinely fresh session starts clean."""
    ss = _import_session_start()
    import _hook_utils  # type: ignore[import-not-found]

    state_dir = tmp_path / _hook_utils.STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "write_count").write_text("9", encoding="utf-8")
    (state_dir / "speedbump_x").write_text("1", encoding="utf-8")

    ss._clean_state_flags(tmp_path, source)

    wiped = not (state_dir / "write_count").exists()
    assert wiped is cleared, f"source={source!r}: write_count wiped={wiped}, expected {cleared}"
    assert (not (state_dir / "speedbump_x").exists()) is cleared
    # session_started is (re)written on EVERY source, gate or not.
    assert (state_dir / "session_started").exists()


def test_new_session_sources_pinned_against_protocol_doc():
    """Tripwire: the four `source` NAMES are unpinned CC behavior, so a rename
    is invisible at runtime (it manifests as silent chain stagnation). Assert
    the advance-set is exactly {startup, clear} and that the pinned protocol
    doc enumerates all four sources — so a protocol refresh that renames one
    forces a paired review of `_NEW_SESSION_SOURCES`."""
    ss = _import_session_start()
    assert ss._NEW_SESSION_SOURCES == frozenset({"startup", "clear"})
    protocol = (REPO_ROOT / "docs" / "external" / "cc-hook-protocol.md").read_text(
        encoding="utf-8"
    )
    for src in ("startup", "resume", "clear", "compact"):
        assert f"`{src}`" in protocol, f"protocol doc must enumerate source {src!r}"


# ── unit: the compact-orientation variant (TP-240) ──────────────────────────


def test_compact_source_selects_compact_variant():
    """source=="compact" -> the mid-session compact banner; any other source ->
    the normal banner. The compact variant signals the re-orient and OMITS the
    start-of-session MEMORY digest."""
    ss = _import_session_start()
    compact = ss._build_context(REPO_ROOT, True, False, "compact")
    normal = ss._build_context(REPO_ROOT, True, False, "startup")
    assert "POST-COMPACTION RE-ORIENT" in compact
    assert "POST-COMPACTION RE-ORIENT" not in normal
    assert "MEMORY (recent sessions" not in compact  # the stale digest is dropped


def test_noncompact_sources_keep_normal_banner_byte_identical():
    """Every NON-compact source yields the SAME normal banner (the `source` param
    is inert off the compact path). Neutralize the per-session _reinject host line
    first -- its counter makes two consecutive real calls differ for a reason
    unrelated to `source`."""
    ss = _import_session_start()
    ss._reinject.check = lambda *a, **k: []
    base = ss._build_context(REPO_ROOT, True, False, "")
    for src in ("startup", "clear", "resume", "bogus"):
        assert ss._build_context(REPO_ROOT, True, False, src) == base, (
            f"non-compact source {src!r} drifted from the baseline banner"
        )
    assert "POST-COMPACTION RE-ORIENT" not in base
    assert "ACTIVE PLAN (live" not in base


# ── integration: the wiring ──────────────────────────────────────────────────


def _scaffold(root: Path) -> None:
    """Minimal pieces ``session_start._load_blueprint`` needs to load+start a
    real blueprint: tools/cc with the real cognitive_blueprint + deps, the
    reports the start reads, and an empty blueprint dir."""
    (root / "tools" / "cc").mkdir(parents=True)
    for fname in ("cognitive_blueprint.py", "_blueprint_limits.py", "_json_safe.py", "_paths.py"):
        (root / "tools" / "cc" / fname).write_bytes((TOOLS_CC / fname).read_bytes())
    (root / "cc" / "blueprints").mkdir(parents=True)
    reports = root / "reports"
    reports.mkdir()
    (reports / "repo_fingerprint.json").write_text('{"repo_name": "t"}', encoding="utf-8")
    (reports / "harness_config.json").write_text("{}", encoding="utf-8")
    (reports / "cc_surface_gate.json").write_text('{"status": "pass"}', encoding="utf-8")


def _node_count(root: Path) -> int:
    bp = root / "cc" / "blueprints"
    if not bp.exists():
        return 0
    return len([p for p in bp.glob("*.json") if p.name != "latest.json"])


def _run_hook(root: Path, source: str) -> subprocess.CompletedProcess:
    # env= pins CLAUDE_PROJECT_DIR so the inner cognitive_blueprint subprocess
    # routes to ``root``, not an inherited repo (the env-isolation contract).
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    return subprocess.run(
        [sys.executable, str(SESSION_START)],
        input=json.dumps(
            {"hook_event_name": "SessionStart", "source": source, "cwd": str(root)}
        ),
        cwd=str(root), env=env, capture_output=True, text=True, timeout=20, encoding="utf-8",
    )


@pytest.mark.parametrize("source", ["startup", "clear"])
def test_new_session_source_advances_chain_even_with_prior(tmp_path, source):
    """The new behavior: startup/clear start a fresh node EVEN WHEN a prior
    node already exists (the old code only started when load was empty)."""
    _scaffold(tmp_path)
    # Seed a prior node (also via the hook, exercising the start path once).
    seed = _run_hook(tmp_path, "startup")
    assert seed.returncode == 0, seed.stderr
    before = _node_count(tmp_path)
    assert before >= 1, "precondition: a prior node exists"

    result = _run_hook(tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert _node_count(tmp_path) == before + 1, (
        f"source={source!r} must advance the chain by exactly one node"
    )


@pytest.mark.parametrize("source", ["resume", "compact", ""])
def test_continuation_source_does_not_advance_chain(tmp_path, source):
    """resume/compact/unknown CONTINUE the session — no new node."""
    _scaffold(tmp_path)
    seed = _run_hook(tmp_path, "startup")
    assert seed.returncode == 0, seed.stderr
    before = _node_count(tmp_path)

    result = _run_hook(tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert _node_count(tmp_path) == before, (
        f"source={source!r} must NOT advance the chain"
    )


@pytest.mark.parametrize("source", ["compact", "resume"])
def test_present_but_unreadable_blueprint_not_clobbered_by_continuation(tmp_path, source):
    """A present-but-UNREADABLE latest.json (here: oversize, which
    cognitive_blueprint._load_latest refuses → empty `load` output) must NOT be
    clobbered by a continuation source. The bootstrap keys on the file's
    PRESENCE, not on whether `load` returned text — so the corrupt file is left
    intact for recovery instead of being reset mid-compaction.

    Earn-the-red: under the prior `not prior_ctx` gate, the empty load output
    triggered a bootstrap `start` that overwrote latest.json with a fresh node.
    """
    _scaffold(tmp_path)
    latest = tmp_path / "cc" / "blueprints" / "latest.json"
    # Oversize the pointer past _BLUEPRINT_MAX_SIZE (128 KB) so _load_latest
    # refuses the read but the file is unmistakably PRESENT.
    sentinel = '{"session_id": "deadbeef", "x": "' + ("z" * 200_000) + '"}'
    latest.write_text(sentinel, encoding="utf-8")

    result = _run_hook(tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert latest.read_text(encoding="utf-8") == sentinel, (
        f"source={source!r} clobbered a present-but-unreadable latest.json"
    )
    # No sibling node was created either (the only file is the untouched pointer).
    assert _node_count(tmp_path) == 0


# ── TP-254 F5: main() fail-open umbrella ─────────────────────────────────────


def test_main_umbrella_degrades_run_main_crash_to_exit_zero(monkeypatch):
    """SessionStart is a REPORTER: an uncaught crash in the banner build must
    fail OPEN (exit 0, no traceback propagation) like every sibling hook, not
    surface a traceback and a non-zero SystemExit. RED against the pre-fix
    shape where ``main()`` was the bare body and any OSError propagated."""
    ss = _import_session_start()

    def _boom():
        raise OSError("simulated read-only .espalier-state")

    monkeypatch.setattr(ss, "_run_main", _boom)
    # Must NOT raise, and must return the fail-open code 0.
    assert ss.main() == 0


def test_main_umbrella_is_separate_from_run_main():
    """The umbrella must wrap a distinct ``_run_main`` — the fix's structure,
    not just its behavior. Guards against a refactor collapsing them back."""
    ss = _import_session_start()
    assert hasattr(ss, "_run_main"), "session_start must expose _run_main under the umbrella"
    assert ss.main is not ss._run_main
