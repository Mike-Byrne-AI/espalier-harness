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
  - The local-filesystem defer is read from the places a payload names, through
    the leaf walk, never from key names (DEF-5101): a move keyed from/to or a
    batch defers, a relative leaf or a URL is no evidence. `write` and `edit`
    lead a side effect as `send` does (DEF-876).
  - No write_guard dispatch change: `mcp__*` already passes the read-only
    early-return and reaches the speed-bump check. Shelled so the real call-site
    ordering, not the predicate alone, is under test.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _speedbump  # noqa: E402

from tests._hook_spawn import run_hook_through


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
        "mcp__x__writers_guild",      # `write` prefix, a read
        "mcp__x__editorial_calendar", # `edit`  prefix, a read
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


# ── Defer to write_guard on local-filesystem MCP ops (read from the leaves) ──

def _move(tool_input, root):
    """The predicate on a move: a side-effect verb, so only the defer silences it."""
    return _speedbump._pred_mcp_sideeffect("mcp__fs__move_file", tool_input, root)


class TestCpMcpDefersToWriteGuard:
    """A local-filesystem MCP op is write_guard's domain, not an external side
    effect, so CP-MCP stays silent and its body ("leaves the repo") stays true.
    The defer is read from what the payload names, through the leaf walk: a
    place spelled from a root (or drive) that lies inside a checkout. Until
    DEF-5101 it stepped aside only on six top-level keys, so a move keyed
    ``from``/``to`` or ``source``/``to``, a batch of moves, or a move naming its
    file under ``output_path`` was told it left the repo: those cells are RED against it.
    The six keys stay as cells, so the cells the old roster pinned still hold."""

    @pytest.mark.parametrize("shape", [
        "path", "file_path", "destination", "new_path", "src", "dst",
        "from_to", "source_to", "moves_batch", "output_path",
    ])
    def test_silent_when_the_payload_names_a_place_in_the_checkout(self, shape, tmp_path):
        r = tmp_path.resolve()
        here, there = str(r / "a.txt"), str(r / "sub" / "b")
        tool_input = {
            "from_to": {"from": here, "to": there},
            "source_to": {"source": here, "to": there},
            "moves_batch": {"moves": [{"source": here, "destination": there},
                                      {"from": str(r / "c"), "to": str(r / "d")}]},
            "output_path": {"output_path": there, "content": "x"},
        }.get(shape, {shape: here})
        assert _move(tool_input, r) is False

    def test_a_relative_spelling_is_no_evidence(self, tmp_path):
        """Declared: an MCP server resolves a relative path against its own
        working directory, which the hook never sees, so a relative leaf says
        nothing about where the call lands, and the move is nudged."""
        assert _move({"from": "a.txt", "to": "b"}, tmp_path.resolve()) is True
        assert _move({"path": "tools/cc/hooks/write_guard.py"}, tmp_path.resolve()) is True

    def test_a_remote_move_fires(self, tmp_path):
        # Nothing in the checkout is named: a URL, or ids. RED against the six
        # keys, which deferred the bucket move on its `destination` key.
        r = tmp_path.resolve()
        assert _move({"source": "s3://bucket/a", "destination": "s3://bucket/b"}, r) is True
        assert _move({"card_id": "abc", "list_id": "def"}, r) is True

    def test_a_place_outside_every_checkout_is_no_evidence(self, tmp_path):
        outside = tmp_path.resolve() / "elsewhere"
        checkout = tmp_path.resolve() / "repo"
        assert _move({"source": str(outside / "a"), "destination": str(outside / "b")}, checkout) is True

    def test_text_under_a_content_key_names_no_place(self, tmp_path):
        r = tmp_path.resolve()
        assert _move({"content": str(r / "a.txt")}, r) is True

    def test_a_payload_past_the_walk_bound_names_no_place(self, tmp_path):
        r = tmp_path.resolve()
        deep: dict = {"path": str(r / "a.txt")}
        for _ in range(_speedbump._hook_utils.MCP_LEAFWALK_MAX_DEPTH + 2):
            deep = {"next": deep}
        assert _move(deep, r) is True

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


# ── A write or an edit is a side-effect verb (DEF-876) ──────────────────────

class TestCpMcpWriteAndEditVerbs:
    """`write` and `edit` lead an action as `send` and `delete` do: a remote page
    write or a document edit names nothing in the checkout and is nudged (RED
    before DEF-876: the roster had neither verb, so both tiers were silent).
    A local write or edit names its file and still defers to write_guard, under
    any key, the edit's own oldText/newText beside it."""

    @pytest.mark.parametrize("tool_name, tool_input", [
        ("mcp__notion__write_page", {}),
        ("mcp__docs__edit_document", {}),
        ("mcp__notion__write_page", {"page_id": "abc123", "content": "x"}),
        ("mcp__docs__edit_document", {"document_id": "1xYz", "requests": [{"insertText": "hi"}]}),
    ])
    def test_a_remote_write_or_edit_fires(self, tool_name, tool_input, tmp_path):
        assert _speedbump._pred_mcp_sideeffect(tool_name, tool_input, tmp_path.resolve()) is True

    @pytest.mark.parametrize("tool_name, shape", [
        ("mcp__filesystem__write_file", "path"),
        ("mcp__fs__write_file", "output_path"),
        ("mcp__filesystem__edit_file", "edits"),
    ])
    def test_a_local_write_or_edit_stays_silent(self, tool_name, shape, tmp_path):
        r = tmp_path.resolve()
        tool_input = {
            "path": {"path": str(r / "a.py"), "content": "x"},
            "output_path": {"output_path": str(r / "src" / "a.py"), "content": "x"},
            # The edit's text is spelled from a root and lies outside the
            # checkout, and the walk reads it before the file the edit names:
            # text is not where the call lands, so it vetoes nothing.
            "edits": {"edits": [{"oldText": "/usr/bin/env python", "newText": "/etc/hosts"}],
                      "dryRun": False, "path": str(r / "a.py")},
        }[shape]
        assert _speedbump._pred_mcp_sideeffect(tool_name, tool_input, r) is False



# ── The anchor is the normaliser's own reading ─────────────────────────────

class TestCpMcpAnchorReadsLikeTheNormaliser:
    """A leaf is absolute as `normalize_path_str` reads it, on the cleaned
    spelling, and lies inside when the normalised text is not anchored. An id
    like `t:1`, and on POSIX a drive spelling, joins the root and comes back
    still anchored-looking, so it names no place and a remote delete keyed by
    it is nudged (RED against a placement read by shape, "no leading slash").
    A `file://` URI of a checkout file is absolute once cleaned and defers (RED
    against an anchor read on the spelling as typed)."""

    def test_a_drive_shaped_id_names_no_place(self, tmp_path):
        r = tmp_path.resolve()
        assert _speedbump._pred_mcp_sideeffect("mcp__x__delete_item", {"id": "t:1"}, r) is True

    @pytest.mark.skipif(os.name == "nt", reason="a drive spelling is absolute on Windows")
    def test_a_drive_spelling_on_posix_names_no_place(self, tmp_path):
        r = tmp_path.resolve()
        assert _speedbump._pred_mcp_sideeffect("mcp__x__delete_item", {"path": "C:/Users/x"}, r) is True

    @pytest.mark.skipif(os.name == "nt", reason="the file URI of a drive path is a separate spelling")
    def test_a_file_uri_in_the_checkout_defers(self, tmp_path):
        r = tmp_path.resolve()
        tool_input = {"from": (r / "a.txt").as_uri(), "to": (r / "b").as_uri()}
        assert _move(tool_input, r) is False


# ── An always-external verb never defers ───────────────────────────────────

class TestCpMcpAlwaysExternalVerbs:
    """send, post, publish and trigger leave the checkout whatever the call
    names: a file the call names is what it sends (RED against a defer read
    for every side-effect verb, which silenced both cells)."""

    @pytest.mark.parametrize("tool_name, shape", [
        ("mcp__x__send_file", "path"),
        ("mcp__claude_ai_Gmail__send_email", "attachment"),
        ("mcp__x__post_message", "file"),
        ("mcp__x__publish_page", "path"),
    ])
    def test_it_fires_though_the_call_names_a_checkout_file(self, tool_name, shape, tmp_path):
        r = tmp_path.resolve()
        tool_input = {shape: str(r / "a.pdf"), "to": "x@example.com"}
        assert _speedbump._pred_mcp_sideeffect(tool_name, tool_input, r) is True


# ── A deferrable verb's nudge spends its own budget ─────────────────────────

class TestCpMcpDeferrableBudget:
    """A deferrable verb's nudge (a write, edit, move, create, update, delete,
    remove or archive the defer could not place) spends its own session
    counter, so a run of them never takes the slots CP-COMPACT and the
    always-external verbs share (RED against one shared counter: after four
    such nudges the send and the compaction checkpoint were both suppressed)."""

    def test_deferrable_nudges_leave_the_shared_slots(self, tmp_path):
        root = tmp_path.resolve()
        mcp = (_speedbump.CP_MCP_SIDEEFFECT,)
        for verb in ("write", "edit", "move", "create"):
            fired = _speedbump.check(f"mcp__x__{verb}_thing", {}, root, bumps=mcp)
            assert fired is not None and "CP-MCP-SIDEEFFECT" in fired, verb
        # its own budget is spent: a fifth distinct deferrable tool is suppressed
        assert _speedbump.check("mcp__x__delete_thing", {}, root, bumps=mcp) is None
        # the shared slots are whole: a send and a compaction still nudge
        assert _speedbump.check("mcp__x__send_message", {}, root, bumps=mcp) is not None
        state = root / _speedbump.STATE_DIR
        (state / "post_compact_pending").write_text("1", encoding="utf-8")
        compact = _speedbump.check("Write", {"file_path": str(root / "a.py")}, root, bumps=(_speedbump.CP_COMPACT,))
        assert compact is not None and "CP-COMPACT" in compact

    def test_the_budget_follows_the_verb(self):
        assert _speedbump._mcp_budget("mcp__x__send_message", {}) == _speedbump.SPEEDBUMP_COUNTER
        assert _speedbump._mcp_budget("mcp__x__write_page", {}) == _speedbump._MCP_DEFERRABLE_COUNTER
        assert _speedbump._MCP_DEFERRABLE_COUNTER.startswith("speedbump_")  # SessionStart's sweep clears it


# ── What a fire says, and the review's pins ────────────────────────────────

class TestCpMcpWhatTheNudgeSays:
    """A deferrable verb fires only when its input names no place inside the
    checkout by an absolute path, so its reminder says that and never that the
    call "leaves the repo", the false text the row was about (RED against the
    static body on every fire). An always-external verb keeps the static text."""

    def test_a_relative_local_move_is_not_told_it_leaves_the_repo(self, tmp_path):
        reason = _speedbump.check("mcp__fs__move_file", {"from": "a.txt", "to": "b"}, tmp_path.resolve(),
                                  bumps=(_speedbump.CP_MCP_SIDEEFFECT,))
        assert reason is not None and "names no place inside the checkout" in reason
        assert "leaves the repo" not in reason

    def test_a_send_is_told_it_leaves_the_repo(self, tmp_path):
        reason = _speedbump.check("mcp__slack__send_message", {}, tmp_path.resolve(),
                                  bumps=(_speedbump.CP_MCP_SIDEEFFECT,))
        assert reason is not None and "leaves the repo" in reason


class TestCpMcpReviewPins:
    """Pins the failure-mode review drove as unpinned or open on the lane."""

    def test_the_checkout_root_itself_is_no_evidence(self, tmp_path):
        # A cwd or repo_path is the call's context, not where it lands (RED
        # against counting it: a release cut from the checkout went silent).
        r = tmp_path.resolve()
        assert _speedbump._pred_mcp_sideeffect("mcp__gh__create_release", {"repo_path": str(r), "tag": "v1"}, r) is True

    def test_a_capitalised_content_key_is_still_content(self, tmp_path):
        r = tmp_path.resolve()
        assert _move({"Content": str(r / "a.txt")}, r) is True

    def test_the_defer_is_read_after_the_verb(self, tmp_path, monkeypatch):
        # A read, a no-verb name and an always-external verb never ask the
        # defer: it is not called for them at all.
        def refuse(*_a, **_k):
            raise AssertionError("the defer was read before the verb decided")
        monkeypatch.setattr(_speedbump, "_mcp_names_a_place_in_the_checkout", refuse)
        r = tmp_path.resolve()
        assert _speedbump._pred_mcp_sideeffect("mcp__gh__list_issues", {"path": str(r)}, r) is False
        assert _speedbump._pred_mcp_sideeffect("mcp__x__ping", {"path": str(r)}, r) is False
        assert _speedbump._pred_mcp_sideeffect("mcp__x__send_file", {"path": str(r / "a")}, r) is True

    @pytest.mark.skipif(os.name == "nt", reason="the home directory is read from USERPROFILE there")
    def test_a_home_spelling_in_the_checkout_defers(self, tmp_path, monkeypatch):
        r = tmp_path.resolve()
        monkeypatch.setenv("HOME", str(r.parent))
        assert _move({"from": f"~/{r.name}/a.txt", "to": f"~/{r.name}/b"}, r) is False

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
        return run_hook_through(
            [sys.executable, str(HOOKS_DIR / "write_guard.py")],
            input=json.dumps(payload),
            env=env,
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
