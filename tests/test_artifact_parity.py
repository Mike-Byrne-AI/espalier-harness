"""Structural source-vs-wheel parity contract for espalier.artifact_parity.

Pins that `.claude/settings.json` rendered from a source checkout is
structurally identical to the same file rendered from an installed
wheel — modulo the platform-specific interpreter name (macOS vs Linux vs
Windows shebangs). Without this contract an adopter pip-installing the
wheel could get a hook wiring that diverges from what the test suite
exercises against the source tree, and CI would stay green while
downstream installs silently used the old wiring.

The platform-tolerant differ extracts `command` interpreter prefixes
before comparing so a wheel built on macOS still matches a Linux
source checkout in structure.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

from espalier import hook_contract
from espalier.artifact_parity import (
    build_wheel,
    check_source_vs_wheel,
    clear_stale_packaging_state,
    extract_script_arg,
    run_init_in_clean_venv,
    structural_diff,
)
from espalier.cli import _build_settings_json


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# extract_script_arg
# ---------------------------------------------------------------------------


class TestExtractScriptArg:
    def test_macos_interpreter(self):
        cmd = '/opt/homebrew/opt/python@3.14/bin/python3.14 "$CLAUDE_PROJECT_DIR/tools/cc/hooks/session_start.py"'
        assert extract_script_arg(cmd) == '"$CLAUDE_PROJECT_DIR/tools/cc/hooks/session_start.py"'

    def test_windows_quoted_interpreter(self):
        cmd = '"C:\\Program Files\\Python312\\python.exe" "$CLAUDE_PROJECT_DIR/tools/cc/hooks/stop_gate.py"'
        assert extract_script_arg(cmd) == '"$CLAUDE_PROJECT_DIR/tools/cc/hooks/stop_gate.py"'

    def test_linux_venv_interpreter(self):
        cmd = '/tmp/venv/bin/python "$CLAUDE_PROJECT_DIR/tools/cc/hooks/plan_guard.py"'
        assert extract_script_arg(cmd) == '"$CLAUDE_PROJECT_DIR/tools/cc/hooks/plan_guard.py"'

    def test_missing_anchor_raises(self):
        with pytest.raises(ValueError, match="CLAUDE_PROJECT_DIR"):
            extract_script_arg("/usr/bin/python3 script.py")


# ---------------------------------------------------------------------------
# structural_diff — happy path uses the real generator on both sides
# ---------------------------------------------------------------------------


def _fake_wheel_settings_with_different_interpreter() -> dict:
    """Return _build_settings_json() output reshaped to legacy shell form.

    TP-35: the renderer now emits exec form (``command: "python"``,
    ``args: [script_path]``). Post-TP-35, source-path and wheel-install
    init produce byte-identical settings — there is no longer an
    interpreter token to differ. This helper still exists so the
    structural-diff tests can pin "the diff tolerates legacy
    shell-form settings on the wheel side." It rebuilds each hook
    entry in shell form with a fake interpreter and the same script
    path, then `structural_diff` should still report parity because
    the script paths normalise to the same value.
    """
    settings = _build_settings_json()
    new = copy.deepcopy(settings)
    for event_cfg in new["hooks"].values():
        for entry in event_cfg:
            for hook in entry.get("hooks", []):
                script_path = hook.get("args", [None])[0]
                if not script_path:
                    continue
                # Rewrite to shell form with a fake interpreter — the
                # historical wheel-install shape pre-TP-35 used bare
                # $CLAUDE_PROJECT_DIR (no curly) embedded in a quoted
                # path inside the command string.
                legacy_path = script_path.replace(
                    "${CLAUDE_PROJECT_DIR}", "$CLAUDE_PROJECT_DIR"
                )
                hook.pop("args", None)
                hook["command"] = f'/tmp/fake-venv/bin/python "{legacy_path}"'
    return new


class TestStructuralDiff:
    def test_same_settings_no_diff(self):
        a = _build_settings_json()
        b = _build_settings_json()
        assert structural_diff(a, b) == []

    def test_tolerates_legacy_shell_form(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        # textually different: exec form vs legacy shell form (post-TP-35 both
        # sides wire the same bare interpreter NAME, so the token itself does
        # not differ -- see the helper's docstring)
        assert source != wheel
        # but structural diff finds no real divergence
        assert structural_diff(source, wheel) == []

    def test_detects_matcher_divergence(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        wheel["hooks"]["PreToolUse"][0]["matcher"] = "Write"
        diffs = structural_diff(source, wheel)
        assert any("matcher" in d for d in diffs)

    def test_detects_timeout_divergence(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        wheel["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 999
        diffs = structural_diff(source, wheel)
        assert any("timeout" in d for d in diffs)

    def test_detects_missing_user_prompt_submit(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        del wheel["hooks"]["UserPromptSubmit"]
        diffs = structural_diff(source, wheel)
        assert any("UserPromptSubmit" in d for d in diffs)

    def test_detects_missing_canonical_hook(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        # remove task_router.py from UserPromptSubmit
        ups = wheel["hooks"]["UserPromptSubmit"]
        ups[0]["hooks"] = []
        diffs = structural_diff(source, wheel)
        assert any("task_router.py" in d or "missing canonical hooks" in d for d in diffs)

    def test_detects_event_count_mismatch(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        # add an extra hook to PostToolUse
        wheel["hooks"]["PostToolUse"][0]["hooks"].append({
            "type": "command",
            "command": '/tmp/fake/python "$CLAUDE_PROJECT_DIR/tools/cc/hooks/extra.py"',
            "timeout": 5,
        })
        diffs = structural_diff(source, wheel)
        assert any("hook count differs" in d for d in diffs)

    def test_detects_event_missing_entirely(self):
        source = _build_settings_json()
        wheel = _fake_wheel_settings_with_different_interpreter()
        del wheel["hooks"]["Stop"]
        diffs = structural_diff(source, wheel)
        assert any("events only on source side" in d and "Stop" in d for d in diffs)


# ---------------------------------------------------------------------------
# Integration — actually build the wheel. Gated by BUILD availability.
# ---------------------------------------------------------------------------


def _build_available() -> bool:
    """True only when `python -m build` can be executed by this interpreter."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--help"],
            capture_output=True, text=True, timeout=10, check=False, encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0 or "usage" not in (result.stdout + result.stderr).lower():
        return False
    # `build --help` succeeds even without a build backend; the real build
    # (`--no-isolation`) needs setuptools.build_meta, which 3.12+ venvs no
    # longer bundle -- assert it so the skip-guard stops green-washing (W0-2).
    backend = subprocess.run(
        [sys.executable, "-c", "import setuptools.build_meta"],
        capture_output=True, text=True, timeout=10, check=False, encoding="utf-8",
    )
    return backend.returncode == 0


def _require_build_or_skip() -> None:
    """Hard-fail when `python -m build` is missing unless an explicit opt-out is set.

    Wheel-vs-source drift is a known release footgun; a silent skip in CI is a
    silent failure mode. Set ESPALIER_ALLOW_PARITY_SKIP=1 to skip explicitly
    in environments that legitimately cannot build (e.g., constrained CI).
    """
    if _build_available():
        return
    if os.environ.get("ESPALIER_ALLOW_PARITY_SKIP") == "1":
        pytest.skip(
            "python -m build unavailable; ESPALIER_ALLOW_PARITY_SKIP=1 set"
        )
    pytest.fail(
        "python -m build is required for artifact parity tests. "
        "Install with: pip install build. "
        "If this CI environment legitimately cannot build, set "
        "ESPALIER_ALLOW_PARITY_SKIP=1 explicitly."
    )


class TestCheckSourceVsWheel:
    def test_happy_path_parity(self):
        """Fresh wheel built from current source should structurally match source-path init."""
        _require_build_or_skip()
        report = check_source_vs_wheel(REPO_ROOT)
        assert report["parity"] is True, (
            f"Parity failed unexpectedly: {report['diffs']}"
        )


# ---------------------------------------------------------------------------
# Pack 6 Task 6-G — Wheel parity canary for the April 2026 stale-wheel bug
# ---------------------------------------------------------------------------


def test_regression_stale_wheel_april_2026(tmp_path):
    """Narrow canary for the specific April 2026 stale-wheel divergence.

    Hard-fails when `python -m build` is missing (no silent skip) unless
    ESPALIER_ALLOW_PARITY_SKIP=1 is set explicitly.

    Historical bug: `dist/espalier_harness-0.3.0-py3-none-any.whl` was published
    missing the `UserPromptSubmit` event entirely and carrying a stale Stop
    timeout that did not match the source. Downstream repos installing the
    wheel got a silently degraded harness.

    This canary asserts two specific properties on the freshly-built wheel's
    generated settings.json — it is narrower and faster than the full
    structural_diff parity check because the fault modes to catch are known:

      1. `UserPromptSubmit` is wired to `task_router.py`.
      2. Stop-hook timeout equals `hook_contract.STOP_OUTER_TIMEOUT`.
    """
    _require_build_or_skip()
    wheel_path = build_wheel(REPO_ROOT, tmp_path / "dist")
    wheel_target = tmp_path / "wheel-repo"
    wheel_settings = run_init_in_clean_venv(wheel_path, wheel_target)

    # (1) UserPromptSubmit wired to task_router.py
    ups = wheel_settings.get("hooks", {}).get("UserPromptSubmit")
    assert ups, (
        "wheel-generated settings.json is missing UserPromptSubmit entirely "
        "— exact April 2026 regression"
    )
    # TP-35: exec form puts the script path in `args`, not in `command`.
    # Inspect both shapes to survive the shell-form -> exec-form switch.
    script_refs = []
    for entry in ups:
        for hook in entry.get("hooks", []):
            script_refs.append(hook.get("command", ""))
            for arg in hook.get("args", []) or []:
                script_refs.append(arg)
    assert any("task_router.py" in s for s in script_refs), (
        f"UserPromptSubmit is present but not wired to task_router.py. "
        f"Refs: {script_refs}"
    )

    # (2) Stop timeout matches the canonical contract
    stop_entries = wheel_settings.get("hooks", {}).get("Stop", [])
    stop_timeouts = [
        hook.get("timeout")
        for entry in stop_entries
        for hook in entry.get("hooks", [])
    ]
    assert stop_timeouts, "wheel-generated settings.json has no Stop hook wired"
    for timeout in stop_timeouts:
        assert timeout == hook_contract.STOP_OUTER_TIMEOUT, (
            f"Stop timeout in wheel settings is {timeout}, expected "
            f"{hook_contract.STOP_OUTER_TIMEOUT} (STOP_OUTER_TIMEOUT). "
            "This is the exact stale-wheel regression."
        )


class TestNullHooksResilience:
    """TP-313b ITEM A: an explicit ``"hooks": null`` in a settings dict must
    not crash the parity helpers. ``d.get("hooks", {})`` returns None when the
    key is present-but-null, so ``None.get(...)`` / ``... in None`` raise. The
    null-safe ``(d.get("hooks") or {})`` idiom — already the convention
    elsewhere in the module — is the fix. Earn-the-red: these RAISE (Attribute/
    TypeError) on the pre-fix code and return a list on the fixed code.
    """

    def test_event_hooks_null_hooks_returns_empty(self):
        from espalier.artifact_parity import _event_hooks
        # Pre-fix: settings.get("hooks", {}) -> None, then None.get(...) raises.
        assert _event_hooks({"hooks": None}, "Stop") == []

    def test_structural_diff_null_hooks_side_reports_not_crashes(self):
        valid = _build_settings_json()
        # Pre-fix: the event loop (_event_hooks) and the UserPromptSubmit
        # presence checks raise on a null-hooks side; post-fix a null side is
        # reported as a diff, not a crash.
        diffs_left = structural_diff({"hooks": None}, valid)
        assert isinstance(diffs_left, list)
        assert any("UserPromptSubmit" in d for d in diffs_left)
        diffs_right = structural_diff(valid, {"hooks": None})
        assert isinstance(diffs_right, list)
        assert any("UserPromptSubmit" in d for d in diffs_right)


# ---------------------------------------------------------------------------
# clear_stale_packaging_state: the one home for the two cached channels
# ---------------------------------------------------------------------------


class TestClearStalePackagingState:
    """``build/lib`` (never pruned by build_py) and ``*.egg-info/SOURCES.txt``
    (a cached manifest setuptools reuses) each re-ship what the current
    config dropped; every build path clears both through this helper before
    it calls the builder."""

    @staticmethod
    def _stale_tree(root: Path) -> None:
        (root / "build" / "lib").mkdir(parents=True)
        (root / "build" / "lib" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (root / "a.egg-info").mkdir()
        (root / "a.egg-info" / "SOURCES.txt").write_text("x.py\n", encoding="utf-8")
        (root / "pkg" / "b.egg-info").mkdir(parents=True)
        (root / "pkg" / "b.egg-info" / "SOURCES.txt").write_text("y.py\n", encoding="utf-8")
        (root / "keep.txt").write_text("keep\n", encoding="utf-8")

    def test_removes_build_and_the_top_level_egg_info_only(self, tmp_path):
        root = tmp_path / "repo"  # its own root: a session fixture seeds tmp_path
        root.mkdir()
        self._stale_tree(root)
        removed = clear_stale_packaging_state(root)
        assert [p.relative_to(root).as_posix() for p in removed] == ["build", "a.egg-info"]
        survivors = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        assert survivors == ["keep.txt", "pkg", "pkg/b.egg-info", "pkg/b.egg-info/SOURCES.txt"]

    def test_a_clean_tree_is_a_no_op(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        assert clear_stale_packaging_state(root) == []

    def test_a_symlinked_build_is_unlinked_not_followed(self, tmp_path):
        root, target = tmp_path / "repo", tmp_path / "elsewhere"
        root.mkdir()
        target.mkdir()
        (target / "x").write_text("x", encoding="utf-8")
        try:
            (root / "build").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:  # a host without symlink rights
            pytest.skip(f"symlinks unavailable here: {exc}")
        removed = clear_stale_packaging_state(root)
        assert [p.name for p in removed] == ["build"]
        assert not (root / "build").exists() and (target / "x").exists()

    def test_build_wheel_clears_stale_state_before_the_builder(self, tmp_path, monkeypatch):
        """The order row: RED with the call removed from ``build_wheel``."""
        from espalier import artifact_parity

        calls: list[tuple[str, object]] = []

        def recording_clear(repo_root):
            calls.append(("clear", repo_root))
            return []

        def recording_build(cmd, cwd=None):
            calls.append(("build", list(cmd)))
            (tmp_path / "dist").mkdir(exist_ok=True)
            (tmp_path / "dist" / "espalier_harness-0.0.0-py3-none-any.whl").write_bytes(b"")

        monkeypatch.setattr(artifact_parity, "clear_stale_packaging_state", recording_clear)
        monkeypatch.setattr(artifact_parity.subprocess, "check_call", recording_build)
        build_wheel(tmp_path, tmp_path / "dist")
        assert [c[0] for c in calls] == ["clear", "build"], calls
        assert calls[0][1] == tmp_path and "build" in calls[1][1]
