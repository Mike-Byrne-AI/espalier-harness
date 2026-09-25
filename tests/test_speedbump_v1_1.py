"""Earn-fixtures for the TP-162 v1.1 rescued speed-bump tier: CP-MCP-SIDEEFFECT.

MCP external-side-effect writes (send/delete/trigger/post/...) reach OUTSIDE the
repo and plan_guard does not gate `mcp__` at all. CP-MCP-SIDEEFFECT is a
cap-GOVERNED (`cap_exempt=False`) soft nudge to confirm the target + payload.

Load-bearing regressions pinned here:
  - The underscored-server-name regression (`mcp__claude_ai_Gmail__send_email`)
    and the single-segment control (`mcp__slack__send_message`) FIRE. Both go RED
    against the dead v1 regex `mcp__[^_]+__.*\\b(verb)` -- `[^_]+` cannot match an
    underscored server segment, and `\\b` never matches a verb right after `__`.
    The earn-fixture below runs the dead regex inline and asserts it false-silences
    both, proving this test pins the deep-review fix.
  - The token-boundary over-fire guard: a bare verb stem over-fires on read names
    that merely START with a verb substring (`postpone_event`, `updates_feed`,
    `movements`, `archived_items`). `(?:_|$)` keeps those silent while still firing
    `update_record` / `create_preview` -- making the silent-bias posture honest.
  - The accepted under-fire: verb-not-leading forms (`bulk_delete`, `batch_send`)
    fall silent (the v1.1 posture; tighten from observed data).
  - cap-GOVERNED: 4 non-exempt canaries exhaust the session cap -> CP-MCP suppressed
    (the acceptable drop -- an MCP write is not the irreversible tier).
  - per-TOOL keying (DEF-8, 2026-09-13): each distinct mcp__<server>__<action>
    tool earns its own nudge under the session cap; an identical re-issue passes.
    Until then the row was id-only and the second different side-effecting
    tool of a session went unchallenged.
  - No write_guard dispatch change: `mcp__*` already passes the read-only
    early-return and reaches the speed-bump check. Shelled so the real call-site
    ordering, not the predicate alone, is under test.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _speedbump  # noqa: E402


def _pred(tool_name):
    """The CP-MCP-SIDEEFFECT predicate in isolation (tool_input unused, root unused)."""
    return _speedbump._pred_mcp_sideeffect(tool_name, {}, Path("/tmp"))


def _check_mcp(tool_name, root):
    """check() scoped to CP-MCP-SIDEEFFECT only (registry-independent)."""
    return _speedbump.check(tool_name, {}, root, bumps=(_speedbump.CP_MCP_SIDEEFFECT,))


# ── CP-MCP-SIDEEFFECT: the FIRE set ─────────────────────────────────────────

class TestCpMcpFires:
    @pytest.mark.parametrize("tool_name", [
        "mcp__slack__send_message",                 # single-segment control
        "mcp__gh__delete_release",
        "mcp__claude_ai_Gmail__send_email",         # the underscored-server regression
        "mcp__claude_ai_Google_Drive__create_file",
        "mcp__x__update_record",                    # verb leads a real token
        "mcp__x__create_preview",                   # `create` leads -> a real fire
        "mcp__x__trigger",                          # bare verb, no suffix
    ])
    def test_fires_on_side_effect_action(self, tool_name):
        assert _pred(tool_name) is True


# ── CP-MCP-SIDEEFFECT: the SILENT set (read / auth / non-mcp) ────────────────

class TestCpMcpSilent:
    @pytest.mark.parametrize("tool_name", [
        "mcp__gh__list_issues",
        "mcp__drive__search",
        "mcp__claude_ai_Gmail__authenticate",
        "mcp__claude_ai_Google_Calendar__complete_authentication",
        "mcp__x__get_status",
        "mcp__x__describe_resource",
    ])
    def test_silent_on_read_or_auth(self, tool_name):
        assert _pred(tool_name) is False

    @pytest.mark.parametrize("tool_name", ["Bash", "Edit", "Write", "ExitPlanMode", "Read"])
    def test_silent_on_non_mcp(self, tool_name):
        assert _pred(tool_name) is False


# ── Token-boundary OVER-FIRE guard (deep-review fold) ───────────────────────

class TestCpMcpOverFireGuard:
    """A bare verb stem over-fires on read names that merely START with a verb
    substring. The `(?:_|$)` token boundary keeps these silent -- making the
    silent-bias posture honest. RED against a bare `(send|post|update|...)` regex."""

    @pytest.mark.parametrize("tool_name", [
        "mcp__x__postpone_event",     # `post`  prefix, not a real post
        "mcp__x__updates_feed",       # `update` prefix, a read feed
        "mcp__x__movements",          # `move`  prefix, a read
        "mcp__x__archived_items",     # `archive` prefix, a read
        "mcp__x__sender_profile",     # `send`  prefix, a read
    ])
    def test_prefix_collision_stays_silent(self, tool_name):
        assert _pred(tool_name) is False

    def test_degenerate_short_name_is_silent(self):
        # len(parts) < 3 -> action == "" -> neither regex matches -> silent
        assert _pred("mcp__weird") is False
        assert _pred("mcp__") is False


# ── Documented UNDER-FIRE (accepted v1.1 posture) ───────────────────────────

class TestCpMcpDocumentedUnderFire:
    @pytest.mark.parametrize("tool_name", ["mcp__x__bulk_delete", "mcp__x__batch_send"])
    def test_verb_not_leading_falls_silent(self, tool_name):
        # accepted: the verb is not the leading token, so it falls silent. This is
        # the v1.1 silent-bias -- an under-fire is the cheaper error for MCP writes.
        assert _pred(tool_name) is False


# ── Defer to write_guard on local-filesystem MCP ops (path-bearing) ─────────

class TestCpMcpDefersToWriteGuard:
    """A local-fs MCP op carries a path-shaped field and is write_guard's
    protected-zone domain (write_guard.py:449), NOT an external side effect.
    CP-MCP stays silent so the hard-deny owns it in ONE round. RED against a
    predicate that ignores tool_input (the original draft over-fired on
    mcp__filesystem__move_file, preempting the protected-zone 'destination' deny)."""

    # 441-E / §18.4: hand-authored, NOT derived from _speedbump._LOCAL_FS_FIELDS.
    # The parametrize below used to read the live tuple, so deleting a member
    # deleted its own test row (measured: 48 -> 45 passed, rc=0, silent). Only the
    # "destination" member is pinned anywhere else -- by a real
    # mcp__filesystem__move_file deny in tests/test_hooks.py -- so five of the six
    # had no correctness row at all. (Deliberately no `symbol`+file:line anchor
    # here: "destination" is an asserted STRING over there, not a defined symbol,
    # and the tree-wide anchor freshness gate correctly reds on that pairing.)
    _EXPECTED_LOCAL_FS_FIELDS = (
        "path", "file_path", "destination", "new_path", "src", "dst",
    )

    def test_local_fs_field_roster_is_pinned_against_deletion(self):
        """The independent axis: hand-written roster vs the live tuple.

        Failure direction here is an OVER-fire, not a protection hole --
        write_guard still hard-denies the protected-zone write either way. What
        a silent deletion costs is a redundant CP-MCP speedbump whose body
        falsely tells the operator the write "leaves the repo". That is a
        message-accuracy regression, which is why this is graded nit and pinned
        rather than left to a count.
        """
        live = tuple(_speedbump._LOCAL_FS_FIELDS)
        assert live == self._EXPECTED_LOCAL_FS_FIELDS, (
            "_speedbump._LOCAL_FS_FIELDS drifted from the pinned roster.\n"
            f"  live   : {live}\n"
            f"  pinned : {self._EXPECTED_LOCAL_FS_FIELDS}\n"
            "Add or remove the member HERE too, deliberately -- the "
            "parametrize below derives from this roster, so an un-mirrored "
            "deletion would otherwise retire its own coverage silently."
        )
        assert len(live) == 6, (
            f"expected 6 local-fs fields, found {len(live)} -- the literal "
            "count is the tripwire on the obvious wrong fix (regenerating the "
            "roster from the constant, which is blind in the same direction)"
        )

    def test_the_expected_roster_is_still_a_hand_written_literal(self):
        """441-E: the count pin above catches a SHRINKING roster; it cannot
        catch one COLLAPSED back into a derivation.

        Writing ``_EXPECTED_LOCAL_FS_FIELDS = tuple(_speedbump._LOCAL_FS_FIELDS)``
        keeps the count at 6, keeps the suite green, and quietly restores the
        original defect -- the parity assertion becomes ``x == x`` and the
        parametrize goes back to deriving from the subject under test. AST-level
        because the runtime value would be byte-identical.
        """
        import ast
        from pathlib import Path

        source = Path(__file__).resolve().read_text(encoding="utf-8")
        node = None
        for stmt in ast.walk(ast.parse(source)):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if (isinstance(target, ast.Name)
                            and target.id == "_EXPECTED_LOCAL_FS_FIELDS"):
                        node = stmt.value
        why = (
            "_EXPECTED_LOCAL_FS_FIELDS must stay a literal tuple of string "
            "literals. Deriving it from _speedbump._LOCAL_FS_FIELDS is the "
            "obvious wrong fix §18.4 names explicitly: it enrols an addition "
            "and stays blind to a deletion, which is where this started."
        )
        assert isinstance(node, (ast.Tuple, ast.List)), why
        assert node.elts, why
        for element in node.elts:
            assert (
                isinstance(element, ast.Constant) and isinstance(element.value, str)
            ), why

    @pytest.mark.parametrize("field", list(_EXPECTED_LOCAL_FS_FIELDS))
    def test_silent_when_any_local_fs_field_present(self, field):
        # `move` is a side-effect verb, but a LOCAL-fs path field means write_guard owns it.
        ti = {field: "tools/cc/hooks/write_guard.py"}
        assert _speedbump._pred_mcp_sideeffect("mcp__filesystem__move_file", ti, Path("/tmp")) is False

    @pytest.mark.parametrize("field", ["target", "uri", "target_uri", "source"])
    def test_generic_external_field_still_fires(self, field):
        # TP-168 #6: target/uri/target_uri/source are NOT local-fs fields — an external
        # send/trigger/post carrying them must STILL be nudged, not silently deferred.
        # RED against the pre-fix defer that keyed on the broad MCP_PATH_FIELDS.
        ti = {field: "https://example.com/webhook"}
        assert _speedbump._pred_mcp_sideeffect("mcp__x__trigger_webhook", ti, Path("/tmp")) is True

    def test_external_side_effect_without_path_still_fires(self):
        # no local path field -> a genuine external write -> still fires.
        ti = {"to": "x@example.com", "subject": "hi", "body": "..."}
        assert _speedbump._pred_mcp_sideeffect("mcp__claude_ai_Gmail__send_email", ti, Path("/tmp")) is True

    def test_empty_path_field_does_not_defer(self):
        # an empty/falsey path value is not a real local op -> verb logic applies.
        ti = {"path": ""}
        assert _speedbump._pred_mcp_sideeffect("mcp__slack__send_message", ti, Path("/tmp")) is True


# ── The earn-fixture: RED against the dead v1 regex ─────────────────────────

class TestCpMcpEarnedAgainstDeadRegex:
    """The whole point of the rewrite: the dead v1 regex false-SILENCED real MCP
    side effects. Run it inline and assert it fails exactly where the live
    predicate succeeds. If someone reverts to the bare/`\\b` form, this goes RED."""

    DEAD_V1_RE = re.compile(
        r"mcp__[^_]+__.*\b(send|delete|remove|trigger|post|create|update|publish|archive|move)",
        re.I,
    )

    @pytest.mark.parametrize("tool_name", [
        "mcp__slack__send_message",            # single-segment: \b after __ kills it
        "mcp__gh__delete_release",
        "mcp__claude_ai_Gmail__send_email",    # underscored server: [^_]+ kills it too
    ])
    def test_dead_regex_false_silences_but_live_predicate_fires(self, tool_name):
        assert self.DEAD_V1_RE.search(tool_name) is None, (
            "dead v1 regex unexpectedly matched -- the earn premise is broken"
        )
        assert _pred(tool_name) is True, "live predicate must fire where v1 was dead"


# ── Mechanism integration: cap, deny-once, keying, registry shape ───────────

class TestCpMcpCapGoverned:
    def test_registry_row_is_cap_governed_and_keyed_per_tool(self):
        bump = next(b for b in _speedbump.SPEEDBUMPS if b.id == "CP-MCP-SIDEEFFECT")
        assert bump.cap_exempt is False          # the one v1.1 checkpoint the cap bounds
        assert bump.flag_key is _speedbump._mcp_tool_key   # per tool (DEF-8)

    def test_suppressed_after_cap_exhausted(self, tmp_path):
        """cap-GOVERNED: 4 non-exempt canaries exhaust the session cap, then
        CP-MCP-SIDEEFFECT is suppressed (RED against cap_exempt=True)."""
        canaries = tuple(
            _speedbump.SpeedBump(id=f"CP-CANARY-{i}", predicate=lambda *a: True,
                                 body="canary", cap_exempt=False)
            for i in range(_speedbump.SPEEDBUMP_SESSION_CAP)
        )
        for _ in range(_speedbump.SPEEDBUMP_SESSION_CAP):
            _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=canaries)
        reason = _check_mcp("mcp__slack__send_message", tmp_path)
        assert reason is None  # cap reached -> the MCP nudge is suppressed


class TestCpMcpDenyOnceThenAllow:
    def test_deny_once_then_allow(self, tmp_path):
        first = _check_mcp("mcp__slack__send_message", tmp_path)
        assert first is not None and "CP-MCP-SIDEEFFECT" in first
        second = _check_mcp("mcp__slack__send_message", tmp_path)
        assert second is None  # flag set on the first fire IS the retry-allow


class TestCpMcpKeying:
    def test_each_distinct_tool_earns_its_own_nudge(self, tmp_path):
        """DEF-8: the row was id-only until 2026-09-13, so after the first MCP
        side-effect nudged, a DIFFERENT side-effecting tool was silent for the
        rest of the session (RED against that: the second call returned None).
        Per-tool keying: the second distinct tool nudges too, the identical
        re-issue of the first is the retry-allow, and the cap still bounds the
        total (two fires here, under the cap of four)."""
        first = _check_mcp("mcp__claude_ai_Gmail__send_email", tmp_path)
        assert first is not None and "CP-MCP-SIDEEFFECT" in first
        other = _check_mcp("mcp__gh__delete_release", tmp_path)
        assert other is not None and "CP-MCP-SIDEEFFECT" in other   # its own flag
        assert _check_mcp("mcp__claude_ai_Gmail__send_email", tmp_path) is None
        assert _check_mcp("mcp__gh__delete_release", tmp_path) is None

    def test_the_key_is_the_whole_tool_name(self):
        """Two servers' `send` are two tools (the MCP predicate sharp edge:
        parse the `__` segments, never the action alone); the suffix is part
        of a flag FILE name, so operator-chosen server text is folded to a
        safe, bounded spelling."""
        key = _speedbump._mcp_tool_key
        assert key("mcp__slack__send_message", {}) != key("mcp__teams__send_message", {})
        assert key("mcp__slack__send_message", {}) == key("mcp__slack__send_message", {"x": 1})
        odd = key("mcp__my server/v2__send", {})
        assert "/" not in odd and " " not in odd and len(odd) <= 96


class TestRegistryShape:
    def test_mcp_is_last_and_irreversible_tier_still_leads(self):
        ids = [b.id for b in _speedbump.SPEEDBUMPS]
        assert ids[-1] == "CP-MCP-SIDEEFFECT"
        # CP-GITCLEAN joined the irreversible tier (between CP-DISCARD and CP-RMRF);
        # CP-FETCHEXEC closes it (after CP-RMRF).
        assert ids[:6] == ["CP-FORCEPUSH", "CP-RELEASE", "CP-DISCARD",
                           "CP-GITCLEAN", "CP-RMRF", "CP-FETCHEXEC"]
        assert "CP-MCP-SIDEEFFECT" in ids


# ── No write_guard dispatch change: mcp__ reaches the speed-bump (subprocess) ─

class TestNoDispatchChange:
    """The pack ships ZERO write_guard edits. `mcp__*` tools already fall through
    the read-only early-return (`write_guard.py::_run_main`) and reach the speed-bump
    check (`write_guard.py::_run_main`) before the maintenance gate. Shell write_guard so
    the real call-site ordering -- not check() alone -- is the thing under test."""

    def _run(self, payload, tmp_path):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env.pop("ESPALIER_MAINTENANCE_MODE", None)
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / "write_guard.py")],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=15, env=env, encoding="utf-8",
        )

    def test_mcp_side_effect_denied_via_write_guard(self, tmp_path):
        payload = {"tool_name": "mcp__slack__send_message", "tool_input": {}}
        result = self._run(payload, tmp_path)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        hso = output["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "CP-MCP-SIDEEFFECT" in hso["permissionDecisionReason"]

    def test_mcp_read_passes_through_write_guard(self, tmp_path):
        # a read MCP tool must NOT be denied by the speed-bump (and has no protected
        # path field), so write_guard allows it (exit 0, no deny JSON).
        payload = {"tool_name": "mcp__gh__list_issues", "tool_input": {}}
        result = self._run(payload, tmp_path)
        assert result.returncode == 0
        # allow path: either bare exit 0 (no stdout) or an approve/empty decision,
        # never a CP-MCP-SIDEEFFECT deny.
        assert "CP-MCP-SIDEEFFECT" not in result.stdout
