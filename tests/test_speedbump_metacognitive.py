"""Earn-fixtures for the TP-161 meta-cognitive speed-bump tier:
CP-GATEWEAKEN (the keystone) and CP-COMPACT.

Load-bearing regressions pinned here:
  - CP-GATEWEAKEN is `cap_exempt` (NEVER budget-suppressed) -- RED against a
    `cap_exempt=False` keystone (blueprint §11 #1: a storm of benign bumps can
    never fail-open the gate that guards the gates).
  - CP-GATEWEAKEN is keyed per FILE -- a maintenance edit-burst across the four
    guard files fires once PER FILE, not once total (blueprint §11 #4). RED
    against per-checkpoint-ID keying.
  - CP-GATEWEAKEN fires under MAINTENANCE_MODE -- the write_guard speed-bump call
    site precedes the maintenance-bypass gate (TP-159). Shelled so the real
    call-site ordering, not the predicate alone, is under test.
  - The removal-only proxy: it fires on deny-token REMOVAL/replacement but NOT on
    in-place commenting (the token substring survives the `#`). A documented gap.
  - CP-COMPACT consumes the post-compaction window only on a MUTATING action; a
    read-only Bash/Read must NOT fire or consume it. It is cap-GOVERNED
    (`cap_exempt=False`) -- the one v1 checkpoint the cap still bounds.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _speedbump  # noqa: E402


def _check_gw(tool_name, tool_input, root):
    """check() scoped to CP-GATEWEAKEN only (registry-independent)."""
    return _speedbump.check(tool_name, tool_input, root, bumps=(_speedbump.CP_GATEWEAKEN,))


def _gw_edit(fname):
    return {"file_path": f"tools/cc/hooks/{fname}",
            "old_string": "    return deny(reason)", "new_string": "    return 0"}


# ── CP-GATEWEAKEN: predicate ────────────────────────────────────────────────

class TestCpGateweakenPredicate:
    def test_fires_on_deny_removal(self, tmp_path):
        assert _speedbump._pred_gateweaken("Edit", _gw_edit("write_guard.py"), tmp_path)

    def test_fires_on_config_guard_block_removal(self, tmp_path):
        # R10: config_guard.py denies via `return block(...)`, not `deny(...)`.
        # Removing it must trip the keystone (pre-fix _DENY_TOKENS missed block().
        ti = {"file_path": "tools/cc/hooks/config_guard.py",
              "old_string": "    return block(_denial_reasons.KILL_SWITCH_DETECTED)",
              "new_string": "    return 0"}
        assert _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    def test_fires_on_stop_gate_block_removal(self, tmp_path):
        # R10: stop_gate.py also denies via `return block(...)`.
        ti = {"file_path": "tools/cc/hooks/stop_gate.py",
              "old_string": "            return block(_denial_reasons.GATE_PYTEST_FAILED)",
              "new_string": "            return 0"}
        assert _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    def test_block_removal_stays_soft_one_shot(self, tmp_path):
        # R10 widening must NOT change disposition: still a soft re-issue
        # checkpoint (reason returned, not a hard block) and per-file one-shot.
        ti = {"file_path": "tools/cc/hooks/config_guard.py",
              "old_string": "    return block(reason)", "new_string": "    return 0"}
        first = _check_gw("Edit", ti, tmp_path)
        second = _check_gw("Edit", ti, tmp_path)
        assert first is not None and "CP-GATEWEAKEN" in first
        assert second is None  # same-file flag key -> nags exactly once

    def test_fires_on_settings_disable_all_hooks_edit(self, tmp_path):
        ti = {"file_path": ".claude/settings.json",
              "old_string": "{}", "new_string": '{"disableAllHooks": true}'}
        assert _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    def test_fires_on_settings_disable_all_hooks_write(self, tmp_path):
        # a Write carries `content`, not new_string
        ti = {"file_path": "x/.claude/settings.json", "content": '{"disableAllHooks": true}'}
        assert _speedbump._pred_gateweaken("Write", ti, tmp_path)

    def test_silent_on_benign_comment_edit(self, tmp_path):
        # deny-token counts unchanged -> the removal proxy does not fire
        ti = {"file_path": "tools/cc/hooks/write_guard.py",
              "old_string": "# old explanation", "new_string": "# new, longer explanation"}
        assert not _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    def test_silent_on_in_place_comment_of_deny(self, tmp_path):
        # commenting a deny line in place keeps the token substring -> count
        # unchanged -> the removal-only proxy does NOT fire (documented gap).
        ti = {"file_path": "tools/cc/hooks/write_guard.py",
              "old_string": "    return deny(reason)",
              "new_string": "    # return deny(reason)"}
        assert not _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    def test_silent_on_non_guard_file(self, tmp_path):
        ti = {"file_path": "espalier/cli.py",
              "old_string": "    return deny(x)", "new_string": "    return 0"}
        assert not _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    def test_silent_on_a_test_file_named_after_a_guard(self, tmp_path):
        # A suffix match read `tests/test_write_guard.py` as the guard itself
        # (driven 2026-09-13): the keystone bumped an edit that dropped a deny
        # token from a TEST. The guard file is matched by its own path; the
        # real guard, by any path spelling, still fires.
        ti = {"file_path": "tests/test_write_guard.py",
              "old_string": "    return deny(reason)", "new_string": "    return 0"}
        assert not _speedbump._pred_gateweaken("Edit", ti, tmp_path)
        assert _speedbump._pred_gateweaken("Edit", _gw_edit("write_guard.py"), tmp_path)
        absolute = {**_gw_edit("write_guard.py"),
                    "file_path": str(tmp_path / "tools" / "cc" / "hooks" / "write_guard.py")}
        assert _speedbump._pred_gateweaken("Edit", absolute, tmp_path)

    def test_silent_on_bash(self, tmp_path):
        assert not _speedbump._pred_gateweaken("Bash", {"command": "x"}, tmp_path)

    def test_silent_when_deny_added_not_removed(self, tmp_path):
        # strengthening a gate (token count goes UP) must not fire
        ti = {"file_path": "tools/cc/hooks/plan_guard.py",
              "old_string": "    pass", "new_string": "    return deny(reason)"}
        assert not _speedbump._pred_gateweaken("Edit", ti, tmp_path)

    @pytest.mark.parametrize("guard", _speedbump._GUARD_FILES)
    def test_fires_for_each_guard_file(self, tmp_path, guard):
        assert _speedbump._pred_gateweaken("Edit", _gw_edit(guard), tmp_path)


class TestCpGateweakenWriteArm:
    """P5 — the precision was inverted, and the SILENT half was the worse one.

    The predicate read `old_string` directly. A full-file `Write` carries none,
    so it compared 0 against N and could never fire: driven with flags cleared, a
    Write of `def main(): return 0` over `write_guard.py` — deleting every deny
    path in the keystone — was SILENT, while narrow Edits that merely reflowed a
    docstring containing a deny token FIRED.

    The comment that shipped with that behaviour called a full-file Write not
    "cheaply comparable" and reasoned that "the realistic weakening vector is a
    targeted Edit". `Write` is the ordinary way to rewrite a file, so the arm
    dismissed as unrealistic was the one that removed the most.

    These cases need the REAL guard files on disk, because the Write arm's
    pre-image now comes from disk rather than from the tool payload — a fixture
    stub would make the comparison vacuous in the direction being tested.
    """

    GUT = "def main():\n    return 0\n"

    @pytest.fixture
    def guarded_root(self, tmp_path):
        hooks_src = Path(__file__).resolve().parents[1] / "tools" / "cc" / "hooks"
        dest = tmp_path / "tools" / "cc" / "hooks"
        dest.mkdir(parents=True, exist_ok=True)
        for guard in _speedbump._GUARD_FILES:
            src = hooks_src / guard
            if src.exists():
                (dest / guard).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize("guard", _speedbump._GUARD_FILES)
    def test_full_file_write_that_guts_a_guard_fires(self, guarded_root, guard):
        ti = {"file_path": f"tools/cc/hooks/{guard}", "content": self.GUT}
        assert _speedbump._pred_gateweaken("Write", ti, guarded_root), guard

    def test_absolute_path_spelling_also_fires(self, guarded_root):
        """`file_path` arrives absolute from the real tool; the pre-image lookup
        must resolve it, not fall through to an empty read."""
        target = guarded_root / "tools" / "cc" / "hooks" / "write_guard.py"
        ti = {"file_path": str(target), "content": self.GUT}
        assert _speedbump._pred_gateweaken("Write", ti, guarded_root)

    def test_write_that_preserves_the_file_is_silent(self, guarded_root):
        """A round-trip rewrite removes nothing and must not nudge."""
        live = (guarded_root / "tools/cc/hooks/write_guard.py").read_text(
            encoding="utf-8")
        ti = {"file_path": "tools/cc/hooks/write_guard.py", "content": live}
        assert not _speedbump._pred_gateweaken("Write", ti, guarded_root)

    def test_write_that_adds_a_deny_is_silent(self, guarded_root):
        """Strengthening a gate must stay silent through the Write arm too."""
        live = (guarded_root / "tools/cc/hooks/write_guard.py").read_text(
            encoding="utf-8")
        ti = {"file_path": "tools/cc/hooks/write_guard.py",
              "content": live + "\n    return deny(extra)\n"}
        assert not _speedbump._pred_gateweaken("Write", ti, guarded_root)

    def test_creating_a_new_file_is_silent(self, guarded_root):
        """A file that does not exist yet cannot have its gate weakened.

        The pre-image read must fail toward NO fire, never toward a nudge — and
        never toward an exception, since a speed-bump is a lever and not a wall.
        """
        ti = {"file_path": "tools/cc/hooks/write_guard.py.new", "content": self.GUT}
        assert not _speedbump._pred_gateweaken("Write", ti, guarded_root)

    def test_unreadable_pre_image_does_not_fire_or_raise(self, tmp_path):
        """No guard file on disk at all: the read fails and the predicate must
        degrade to silence rather than propagate an OSError into PreToolUse."""
        ti = {"file_path": "tools/cc/hooks/write_guard.py", "content": self.GUT}
        assert _speedbump._pred_gateweaken("Write", ti, tmp_path) is False

    def test_edit_arm_still_reads_its_own_pre_image(self, guarded_root):
        """An Edit states `old_string`; it must NOT be overridden by a disk read.

        The stated pre-image is the hunk being replaced, which is a subset of the
        file — comparing the whole file against a hunk would fire on every Edit
        that shortens anything.
        """
        assert _speedbump._pred_gateweaken(
            "Edit", _gw_edit("write_guard.py"), guarded_root)
        benign = {"file_path": "tools/cc/hooks/write_guard.py",
                  "old_string": "# recieves the reason",
                  "new_string": "# receives the reason"}
        assert not _speedbump._pred_gateweaken("Edit", benign, guarded_root)


# ── CP-GATEWEAKEN: cap-exemption (blueprint §11 #1) ─────────────────────────

class TestCpGateweakenCapExempt:
    def test_fires_after_cap_exhausted(self, tmp_path):
        """RED against cap_exempt=False: 4 non-exempt canaries exhaust the
        session cap, then the keystone edit MUST still fire."""
        canaries = tuple(
            _speedbump.SpeedBump(id=f"CP-CANARY-{i}", predicate=lambda *a: True,
                                 body="canary", cap_exempt=False)
            for i in range(_speedbump.SPEEDBUMP_SESSION_CAP)
        )
        for _ in range(_speedbump.SPEEDBUMP_SESSION_CAP):
            _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=canaries)
        reason = _check_gw("Edit", _gw_edit("write_guard.py"), tmp_path)
        assert reason is not None and "CP-GATEWEAKEN" in reason

    def test_registry_row_is_cap_exempt(self):
        bump = next(b for b in _speedbump.SPEEDBUMPS if b.id == "CP-GATEWEAKEN")
        assert bump.cap_exempt is True
        assert bump.flag_key is _speedbump._gateweaken_key


# ── CP-GATEWEAKEN: per-file keying (blueprint §11 #4) ───────────────────────

class TestCpGateweakenPerFileKeying:
    def test_two_guard_files_fire_twice(self, tmp_path):
        """RED against per-checkpoint-ID keying: editing write_guard.py then
        plan_guard.py in one session yields TWO fires (distinct flag keys) --
        else edits 2..N weaken other gates silently."""
        first = _check_gw("Edit", _gw_edit("write_guard.py"), tmp_path)
        second = _check_gw("Edit", _gw_edit("plan_guard.py"), tmp_path)
        assert first is not None and "CP-GATEWEAKEN" in first
        assert second is not None and "CP-GATEWEAKEN" in second

    def test_same_guard_file_fires_once(self, tmp_path):
        first = _check_gw("Edit", _gw_edit("write_guard.py"), tmp_path)
        second = _check_gw("Edit", _gw_edit("write_guard.py"), tmp_path)
        assert first is not None
        assert second is None  # same (file) flag key -> one-shot

    def test_flag_key_is_basename(self):
        assert _speedbump._gateweaken_key(
            "Edit", {"file_path": "tools/cc/hooks/write_guard.py"}) == "write_guard.py"
        assert _speedbump._gateweaken_key(
            "Write", {"file_path": "x/.claude/settings.json"}) == "settings.json"


# ── CP-GATEWEAKEN: fires under MAINTENANCE_MODE (write_guard integration) ────

class TestCpGateweakenUnderMaintenance:
    """The keystone must fire under MAINTENANCE_MODE -- the speed-bump call site
    in write_guard precedes the maintenance-bypass gate (TP-159). This shells
    write_guard so the real call-site ordering, not the predicate alone, is the
    thing under test."""

    def _run(self, payload, tmp_path, mode):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        if mode is not None:
            env["ESPALIER_MAINTENANCE_MODE"] = mode
        else:
            env.pop("ESPALIER_MAINTENANCE_MODE", None)
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / "write_guard.py")],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=15, env=env, encoding="utf-8",
        )

    def _payload(self):
        return {"tool_name": "Edit", "tool_input": _gw_edit("write_guard.py")}

    def test_gateweaken_denies_under_maintenance(self, tmp_path):
        result = self._run(self._payload(), tmp_path, mode="1")
        assert result.returncode == 0
        output = json.loads(result.stdout)
        hso = output["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "CP-GATEWEAKEN" in hso["permissionDecisionReason"]

    def test_gateweaken_denies_without_maintenance_too(self, tmp_path):
        # the speed-bump precedes BOTH the maintenance gate and the
        # protected-zone check, so it is the first responder either way.
        result = self._run(self._payload(), tmp_path, mode=None)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "CP-GATEWEAKEN" in output["hookSpecificOutput"]["permissionDecisionReason"]


# ── _is_writing_bash heuristic ──────────────────────────────────────────────

class TestIsWritingBash:
    @pytest.mark.parametrize("cmd", [
        "echo x > out.txt", "a >> b.log", "tee file", "sed -i 's/a/b/' f.py",
        "cp a b", "mv a b", "mkdir d", "touch f", "dd if=a of=b", "ln -s a b",
    ])
    def test_writing_commands(self, cmd):
        assert _speedbump._is_writing_bash({"command": cmd})

    @pytest.mark.parametrize("cmd", [
        "grep -n foo bar.py", "cat x.py", "ls -la", "git status",
        "python -c 'print(1)'", "find . -name x", "git log --oneline",
    ])
    def test_reading_commands(self, cmd):
        assert not _speedbump._is_writing_bash({"command": cmd})


# ── CP-COMPACT ──────────────────────────────────────────────────────────────

def _drop_pending(root):
    flag = root / _speedbump.STATE_DIR / "post_compact_pending"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("", encoding="utf-8")
    return flag


def _check_compact(tool_name, tool_input, root):
    return _speedbump.check(tool_name, tool_input, root, bumps=(_speedbump.CP_COMPACT,))


class TestCpCompact:
    def test_fires_on_first_edit_after_compaction(self, tmp_path):
        _drop_pending(tmp_path)
        reason = _check_compact("Edit", {"file_path": "x.py", "new_string": "y"}, tmp_path)
        assert reason is not None and "CP-COMPACT" in reason

    def test_one_shot_then_allow(self, tmp_path):
        _drop_pending(tmp_path)
        ti = {"file_path": "x.py", "new_string": "y"}
        assert _check_compact("Edit", ti, tmp_path) is not None
        assert _check_compact("Edit", ti, tmp_path) is None  # nags exactly once

    def test_no_fire_without_producer_flag(self, tmp_path):
        # the producer never ran -> no post-compaction window
        assert _check_compact("Edit", {"file_path": "x.py", "new_string": "y"}, tmp_path) is None

    def test_readonly_bash_does_not_fire_or_consume_window(self, tmp_path):
        _drop_pending(tmp_path)
        # a read-only Bash must NOT fire (re-orienting before a read is friction-negative)
        assert _check_compact("Bash", {"command": "grep -n foo bar.py"}, tmp_path) is None
        assert _check_compact("Bash", {"command": "cat x.py"}, tmp_path) is None
        # ...and must NOT have consumed the window: the next mutating Edit still fires
        reason = _check_compact("Edit", {"file_path": "x.py", "new_string": "y"}, tmp_path)
        assert reason is not None and "CP-COMPACT" in reason

    def test_writing_bash_fires(self, tmp_path):
        _drop_pending(tmp_path)
        reason = _check_compact("Bash", {"command": "echo x > out.txt"}, tmp_path)
        assert reason is not None and "CP-COMPACT" in reason

    def test_cap_governed_suppressed_when_exhausted(self, tmp_path):
        """§6: RED against cap_exempt=True. CP-COMPACT is the one cap-GOVERNED v1
        checkpoint -- with the session cap exhausted it is suppressed (the
        acceptable drop of a low-stakes re-orient), proving the cap still governs
        something in v1."""
        _drop_pending(tmp_path)
        canaries = tuple(
            _speedbump.SpeedBump(id=f"CP-CANARY-{i}", predicate=lambda *a: True,
                                 body="canary", cap_exempt=False)
            for i in range(_speedbump.SPEEDBUMP_SESSION_CAP)
        )
        for _ in range(_speedbump.SPEEDBUMP_SESSION_CAP):
            _speedbump.check("Bash", {"command": "x"}, tmp_path, bumps=canaries)
        assert _check_compact("Edit", {"file_path": "x.py", "new_string": "y"}, tmp_path) is None

    def test_registry_row_is_cap_governed(self):
        bump = next(b for b in _speedbump.SPEEDBUMPS if b.id == "CP-COMPACT")
        assert bump.cap_exempt is False


# ── 161-D: PostCompact -> first-PreToolUse ordering earn-fixture ─────────────

class TestPostCompactOrdering:
    """Assert against a RECONSTRUCTED sequence, not the protocol's prose (§7 #4 /
    mech-2). The live protocol does not contractually guarantee the ordering;
    this reconstructs PostCompact (which drops the producer flag) followed by the
    first mutating PreToolUse (which reads it), and pins that the flag is present
    at check time -- the precondition CP-COMPACT's window rests on."""

    def _run_post_compact(self, tmp_path):
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / "post_compact.py")],
            input="{}", capture_output=True, text=True, timeout=15, env=env, encoding="utf-8",
        )

    def test_postcompact_drops_flag_before_first_mutation(self, tmp_path):
        # 1. PostCompact runs to completion (the real producer, shelled).
        result = self._run_post_compact(tmp_path)
        assert result.returncode == 0
        flag = tmp_path / _speedbump.STATE_DIR / "post_compact_pending"
        # 2. the flag is present at the moment the first PreToolUse would read it.
        assert flag.exists(), "PostCompact must drop the flag before the next PreToolUse"
        # 3. the first mutating PreToolUse consumes the window.
        reason = _check_compact("Edit", {"file_path": "x.py", "new_string": "y"}, tmp_path)
        assert reason is not None and "CP-COMPACT" in reason

    def test_session_start_clears_the_producer_flag(self, tmp_path):
        # a fresh session must not start inside a stale post-compaction window.
        import session_start  # noqa: PLC0415
        _drop_pending(tmp_path)
        session_start._clean_state_flags(tmp_path)
        assert not (tmp_path / _speedbump.STATE_DIR / "post_compact_pending").exists()
