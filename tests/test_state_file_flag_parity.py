"""Pin .espalier-state/* flag-file schemas across hook producers and consumers.

Four flag files participate in the cross-hook signaling protocol:

    .espalier-state/write_count       — reflect_trigger writes; stop_gate,
                                         session_start read
    .espalier-state/docs_refreshed    — subagent_stop writes (docs-maintainer
                                         relief record); stop_gate Gate 2 reads
    .espalier-state/code_reviewed     — subagent_stop writes (code-reviewer
                                         relief record); stop_gate Gate 3 reads
    .espalier-state/session_started   — session_start writes per-session

write_count is integer-text; session_started is a short marker; the two relief
records are short JSON objects (agent + what the run produced) capped well under
1 KiB. This test pins the shape of each so a hook author who turns a flag into a
payload channel or a different encoding breaks the contract before merging.
(`review_requested`, which stop_gate used to write itself, retired with DEF-608;
session_start still sweeps the legacy name.)
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[1]
_FLAGS = _REPO / ".espalier-state"
_HOOKS_DIR = _REPO / "tools" / "cc" / "hooks"


def _load_hook_module(name: str):
    """Load a ``tools/cc/hooks/<name>.py`` module with its sibling deps importable.

    Hooks import siblings (``import _hook_utils``) that resolve via the hooks dir
    on ``sys.path``; load through ``spec_from_file_location`` (never a plain
    import) so espalier is never dragged into their zero-import graph.
    """
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(name, _HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _assert_write_count_shape(content: str) -> None:
    """write_count must be plain integer text (newline-terminated allowed),
    NOT json or any other encoding. Mirrors the on-disk shape produced by
    ``_hook_utils._write_counter`` → ``atomic_write_text(.., str(count))``.
    """
    stripped = content.strip()
    assert stripped.isdigit(), (
        f".espalier-state/write_count must be plain integer text; got: "
        f"{content[:50]!r}. Hook contract per TP-43 + TP-137 §C."
    )


def _assert_marker_shape(name: str, content: str, cap: int) -> None:
    """A marker flag carries no payload — empty or a short reason string.
    Reading >= ``cap`` bytes means a hook is using the marker as a payload
    channel, which is the wrong shape (the drift this contract pins).
    """
    assert len(content) < cap, (
        f".espalier-state/{name} is a marker file; reading >={cap}B "
        f"suggests a hook is using it as a payload channel — wrong shape."
    )


def test_write_count_shape() -> None:
    """write_count is integer-text (newline-terminated allowed). NOT json.

    Live-dir lane — skips when the flag is absent this session. The
    unconditional contract is ``test_write_count_shape_synthetic``.
    """
    target = _FLAGS / "write_count"
    if not target.exists():
        pytest.skip("write_count not yet written this session")
    _assert_write_count_shape(target.read_text(encoding="utf-8"))


def test_code_reviewed_shape() -> None:
    """code_reviewed is the subagent_stop relief record for code-reviewer —
    a short JSON object, never a payload channel.

    Live-dir lane; unconditional contract is the ``_synthetic`` sibling.
    """
    target = _FLAGS / "code_reviewed"
    if not target.exists():
        pytest.skip("code_reviewed not currently set")
    _assert_marker_shape(
        "code_reviewed", target.read_text(encoding="utf-8"), 1024
    )


def test_docs_refreshed_shape() -> None:
    """docs_refreshed is the subagent_stop relief flag for docs-maintainer —
    empty marker.

    Live-dir lane; unconditional contract is the ``_synthetic`` sibling.
    """
    target = _FLAGS / "docs_refreshed"
    if not target.exists():
        pytest.skip("docs_refreshed not currently set")
    _assert_marker_shape(
        "docs_refreshed", target.read_text(encoding="utf-8"), 1024
    )


def test_session_started_shape() -> None:
    """session_started is a per-session marker — short content.

    Live-dir lane; unconditional contract is the ``_synthetic`` sibling.
    """
    target = _FLAGS / "session_started"
    if not target.exists():
        pytest.skip(".espalier-state/session_started not present")
    _assert_marker_shape(
        "session_started", target.read_text(encoding="utf-8"), 1024
    )


# ── Unconditional synthetic-fixture lane ──────────────────────────────────────
# The live-dir tests above skip on a clean checkout / in CI (the gitignored
# .espalier-state/ is empty there), so the "pin the flag shape before merge"
# contract never actually ran where it must (TP-222 / TQ-drift-1). These tests
# construct the real on-disk shape in tmp_path and assert the schema every run.


def test_write_count_shape_synthetic(tmp_path: Path) -> None:
    """Pin write_count's integer-text shape unconditionally (TP-222).

    Drives the REAL writer (``_hook_utils._write_counter`` → ``str(count)``) and
    asserts the shape of the file IT wrote — RED if a hook author switches the
    counter to JSON or any non-integer encoding. The old version wrote
    ``str(12)`` itself and so could not discriminate a writer change.
    """
    hook_utils = _load_hook_module("_hook_utils")
    state_dir = tmp_path / ".espalier-state"
    hook_utils._write_counter(state_dir, 12)
    _assert_write_count_shape(
        (state_dir / "write_count").read_text(encoding="utf-8")
    )


def test_code_reviewed_shape_synthetic(tmp_path: Path) -> None:
    """Pin code_reviewed's short-record shape unconditionally.

    Drives the REAL writer -- ``subagent_stop._set_relief_flag(root,
    "code-reviewer", payload)``, the only writer since DEF-608 (stop_gate's
    Gate 3 used to write ``review_requested`` itself) -- with a long final
    message, and asserts the file it wrote stays under the cap: the excerpt is
    truncated, the length is recorded as a number.
    """
    subagent_stop = _load_hook_module("subagent_stop")
    subagent_stop._set_relief_flag(
        tmp_path, "code-reviewer", {"last_assistant_message": "finding " * 2000}
    )
    _assert_marker_shape(
        "code_reviewed",
        (tmp_path / ".espalier-state" / "code_reviewed").read_text(encoding="utf-8"),
        1024,
    )


def test_docs_refreshed_shape_synthetic(tmp_path: Path) -> None:
    """Pin docs_refreshed's empty-marker shape unconditionally (TP-222).

    Drives the REAL writer (``subagent_stop._set_relief_flag(root,
    "docs-maintainer")`` → a short JSON record) and asserts the shape of the
    file it wrote. RED if it becomes a payload channel. The old version wrote
    ``""`` itself.
    """
    subagent_stop = _load_hook_module("subagent_stop")
    subagent_stop._set_relief_flag(tmp_path, "docs-maintainer")
    _assert_marker_shape(
        "docs_refreshed",
        (tmp_path / ".espalier-state" / "docs_refreshed").read_text(encoding="utf-8"),
        1024,
    )


def test_session_started_shape_synthetic(tmp_path: Path) -> None:
    """Pin session_started's short-marker shape unconditionally (TP-222).

    Drives the REAL writer (``session_start._clean_state_flags`` →
    ``atomic_write_text(.., datetime.now(..).isoformat())``) and asserts the
    shape of the file it wrote. RED if a hook starts writing a >=1KB payload
    there. The old version wrote a hardcoded timestamp string itself.
    """
    session_start = _load_hook_module("session_start")
    session_start._clean_state_flags(tmp_path)
    _assert_marker_shape(
        "session_started",
        (tmp_path / ".espalier-state" / "session_started").read_text(encoding="utf-8"),
        1024,
    )


_ALLOWED_FLAGS = {
    "write_count",       # reflect_trigger counter
    "write_count.lock",  # TP-151 D-2: reflect_trigger._locked_increment
                         # stable sibling flock (serializes the RMW so the
                         # counter write can be atomic temp+os.replace).
    "docs_refreshed",    # subagent_stop relief record for docs-maintainer (Gate 2)
    "code_reviewed",     # subagent_stop relief record for code-reviewer (Gate 3)
    "review_requested",  # LEGACY: pre-DEF-608 stop_gate wrote it; session_start
                         # sweeps it, so it can exist only until the next
                         # SessionStart on an upgraded tree. Drop with the sweep.
    "session_started",   # session_start per-session marker
    # TP-157 157-F/G session-trajectory signals (reflect_trigger writes
    # tool_call_count + last_tool every tool call; stop_gate reads them and
    # writes session_length_baseline/recorded). session_start clears all
    # but session_length_baseline (the cross-session rolling history).
    "tool_call_count",        # reflect_trigger._record_tool_call odometer
    "tool_call_count.lock",   # its stable flock sibling (157-F)
    "last_tool",              # reflect_trigger consecutive-tool streak (json)
    "session_length_baseline",  # stop_gate 157-G rolling history (PERSISTS)
    "session_length_recorded",  # stop_gate 157-G once-per-session guard
    # TP-164: the recall-engine reinjection session counter. _reinject's
    # SessionStart orientation row (non-exempt) writes reinject_count via
    # _hook_utils._locked_increment each session; session_start._clean_state_flags
    # globs reinject_* at the next SessionStart. Consumer: the REINJECT_SESSION_CAP
    # bound in _reinject.check. (Unlike speedbump_count, which only appears when a
    # checkpoint fires, the orientation row fires every SessionStart, so
    # reinject_count routinely exists mid-session.)
    "reinject_count",        # _reinject session-cap odometer (TP-164)
    "reinject_count.lock",   # its stable flock sibling
    # post_compact writes this on PostCompact so the next Stop knows a
    # compaction happened (post_compact.py:171); _speedbump reads it as a
    # cap-exempt trigger (_speedbump.py:277). Routinely present mid-session.
    "post_compact_pending",  # post_compact -> stop_gate / _speedbump signal
    # The born-weak observer (post_write_check, self-host-gated, OBSERVE-ONLY)
    # appends one JSON line per logged guard+suppression co-occurrence (§1.13).
    # No runtime consumer (future base-rate analysis); materializes only on the
    # self-host repo when a co-occurrence is observed.
    "born_weak_observations.jsonl",  # born-weak observer log (autoimmune §1.13)
    "born_weak_observations.jsonl.lock",  # its stable flock sibling (TP-196 added
    # the flock; the append serializes under a .lock like reinject_count.lock above)
    # TP-429 recall-engine telemetry. Two writers: _reinject._log_recall_event
    # (push -- one row per matched rule, tagged emitted / per_turn_capped /
    # session_capped) and the _recall.py CLI shim (pull -- one row per /recall
    # invocation, carrying the hit/miss). Cross-session rolling history like
    # born_weak_observations.jsonl above, and it PERSISTS for the same reason:
    # the name deliberately does NOT match _clean_state_flags' reinject_* glob,
    # which would erase it every SessionStart. No runtime consumer -- the future
    # cap-tuning pack reads it to decide whether REINJECT_SESSION_CAP /
    # REINJECT_PER_TURN_CAP are throttling real signal.
    "recall_events.jsonl",  # recall-engine telemetry (TP-429)
    "recall_events.jsonl.lock",  # its stable flock sibling
}


#: Flag families that cannot be enumerated because their names carry a key.
#: The speedbump family (speedbump_count[.lock], speedbump_<ID>[_<key>]) only
#: materializes AFTER a checkpoint fires -- exactly when the operator is doing
#: the risky git op the gate exists for; a literal allowed set would false-RED
#: that moment, blocking /preflight + /commit (TP-168 168-D / Fix 8). The
#: reinject once-per-session rows (reinject_once_<RULE-ID>, _reinject._mark_once)
#: are the same shape: measured 2026-09-14, the new-test-file classify row reded
#: this contract on the very session that added a test file. The maintenance-
#: bypass guards (maintenance_bypass_recorded_<hook>, DEF-789) are one per hook.
#: session_start clears each family by the same glob.
_DYNAMIC_FLAG_FAMILIES: tuple[str, ...] = (
    "speedbump_",
    "reinject_once_",
    "maintenance_bypass_recorded_",
)


def _is_documented_flag(name: str) -> bool:
    return name in _ALLOWED_FLAGS or name.startswith(_DYNAMIC_FLAG_FAMILIES)


def test_no_unexpected_flag_files() -> None:
    """Anything in .espalier-state/ must be in the documented set."""
    if not _FLAGS.exists():
        pytest.skip(".espalier-state/ not present")
    unexpected = [p.name for p in _FLAGS.iterdir() if not _is_documented_flag(p.name)]
    assert not unexpected, (
        f".espalier-state/ contains undocumented files: {unexpected}. "
        "Either add the new flag to the allowed set in this test "
        "(and document the writer / consumer), or remove the file."
    )


def test_the_flag_predicate_admits_each_family_and_rejects_a_stray(tmp_path: Path) -> None:
    """The negative twin of test_no_unexpected_flag_files, which skips on a fresh
    clone and can only ever be seen passing on the live tree: prove the
    predicate still rejects, so a widened family glob (a typo that admits the
    whole reinject_* prefix, say) cannot turn the contract into an allow-all."""
    assert _is_documented_flag("write_count")
    assert _is_documented_flag("speedbump_CP-GITCLEAN_x")
    assert _is_documented_flag("reinject_once_REINJECT-NEW-TEST-FILE-CLASSIFY")
    assert _is_documented_flag("maintenance_bypass_recorded_write_guard")
    assert not _is_documented_flag("reinject_bogus")
    assert not _is_documented_flag("maintenance_bypass_recorded")
    assert not _is_documented_flag("stray_flag")
    state = tmp_path / ".espalier-state"
    state.mkdir()
    for name in ("write_count", "speedbump_CP-X", "reinject_once_R", "stray_flag"):
        (state / name).write_text("", encoding="utf-8")
    assert sorted(p.name for p in state.iterdir() if not _is_documented_flag(p.name)) == ["stray_flag"]
