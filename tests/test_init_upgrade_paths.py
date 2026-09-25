"""TP-51 — init / upgrade-path hardening.

Four upgrade-path failure modes pinned by this suite:

- H3 hook drift detection — `deploy_harness` compares the deployed hook
  body against the expected (source + marker) output. Managed copies
  regenerate on drift; user-patched copies preserve with a stderr warn.
- H4 settings.json side-by-side render — when `.claude/settings.json`
  exists, the new template is rendered to `settings.json.new` instead of
  silently skipping.
- H6 blueprint symlink advisory — `tools/cc/cognitive_blueprint._bp_dir`
  emits a one-shot stderr advisory when `cc/blueprints/` or its parent
  is symlinked (POSIX flock is host-local).
- M9 manifest schema_version + algorithm validation —
  `tools/cc/hooks/_integrity` writes `schema_version: 1` and refuses
  manifests with schema_version > 1 or an unsupported algorithm.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._symlink_support import requires_symlink


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_integrity_module():
    """Import _integrity.py directly so tools/cc/ stays zero-espalier-import."""
    spec = importlib.util.spec_from_file_location(
        "_tp51_integrity", HOOKS_DIR / "_integrity.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# target\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


def _run_init(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(target)],
        capture_output=True, text=True, timeout=120, check=True, encoding="utf-8",
    )


pytestmark = [pytest.mark.integration]


# ── H3 hook drift detection ────────────────────────────────────────────────


class TestHookDriftDetection:
    def test_hook_drift_warns_and_preserves(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        hook_path = target / "tools" / "cc" / "hooks" / "write_guard.py"
        # Strip the managed marker line — simulates a user editing the file
        # and removing the marker so they own it.
        body = hook_path.read_text(encoding="utf-8")
        without_marker = "\n".join(
            line for line in body.splitlines() if "espalier:managed" not in line
        ) + "\n"
        hook_path.write_text(without_marker, encoding="utf-8")
        result = _run_init(target)
        assert hook_path.read_text(encoding="utf-8") == without_marker, (
            "user-patched hook (marker stripped) was clobbered by reinit; "
            "expected preserve"
        )
        assert "hook drift" in result.stderr, (
            "expected stderr WARN 'hook drift' line:\n--- stderr ---\n"
            + result.stderr
        )
        assert "write_guard.py" in result.stderr

    def test_hook_drift_replaces_when_managed(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        hook_path = target / "tools" / "cc" / "hooks" / "write_guard.py"
        # Append a no-op comment INSIDE the file but keep the marker.
        # This is a developer-side edit pattern: the file is still the
        # harness's managed copy; the marker remains; re-init should
        # regenerate so canonical content wins.
        body = hook_path.read_text(encoding="utf-8")
        tampered = body + "\n# user-injected line — should be regenerated away\n"
        hook_path.write_text(tampered, encoding="utf-8")
        _run_init(target)
        after = hook_path.read_text(encoding="utf-8")
        assert "user-injected line" not in after, (
            "managed hook (marker present) was NOT regenerated on reinit"
        )
        assert "espalier:managed" in after


# ── R52 retired-managed-script orphan detection ────────────────────────────


class TestManagedOrphanReporting:
    def test_init_reports_retired_managed_hook(self, tmp_path):
        """R52: a managed `.py` left in a deploy dir by an older version (no
        longer in the current INIT_* set) is REPORTED on reinit with a
        copy-paste removal hint — and never auto-deleted."""
        target = _make_target(tmp_path)
        _run_init(target)
        orphan = target / "tools" / "cc" / "hooks" / "retired_hook.py"
        orphan.write_text("# espalier:managed\nprint('retired')\n", encoding="utf-8")
        result = _run_init(target)
        assert "retired_hook.py" in result.stderr, (
            "reinit did not name the retired managed hook:\n--- stderr ---\n"
            + result.stderr
        )
        assert "rm " in result.stderr  # copy-paste removal hint
        # Report-only: the file must still exist (init never auto-deletes).
        assert orphan.exists(), "init auto-deleted an orphan — must report only"

    def test_init_ignores_unmarked_user_script(self, tmp_path):
        """A user-authored `.py` WITHOUT the managed marker in a deploy dir is
        never named (no false positive — the cardinal constraint)."""
        target = _make_target(tmp_path)
        _run_init(target)
        user_file = target / "tools" / "cc" / "my_helper.py"
        user_file.write_text("print('mine')\n", encoding="utf-8")  # no marker
        result = _run_init(target)
        assert "my_helper.py" not in result.stderr

    def test_init_reports_retired_managed_claude_asset(self, tmp_path):
        """W5-1 (TP-177): a marker-carrying `.claude/commands/*.md` the package
        no longer ships at ANY tier is named on re-init (report-only)."""
        target = _make_target(tmp_path)
        _run_init(target)
        orphan = target / ".claude" / "commands" / "retired-cmd.md"
        orphan.write_text(
            "<!-- espalier:managed -->\n# retired command\n", encoding="utf-8"
        )
        result = _run_init(target)
        assert "retired-cmd.md" in result.stderr, (
            "reinit did not name the retired managed .claude asset:\n"
            "--- stderr ---\n" + result.stderr
        )
        assert orphan.exists(), "init auto-deleted a .claude orphan — must report only"

    def test_init_ignores_unmarked_user_claude_asset(self, tmp_path):
        """A user-authored `.claude/commands/*.md` WITHOUT the managed marker is
        never named — the cardinal no-false-positive constraint, extended to
        the W5-1 .claude scan."""
        target = _make_target(tmp_path)
        _run_init(target)
        user_cmd = target / ".claude" / "commands" / "my-own-command.md"
        user_cmd.write_text("# my own command\n", encoding="utf-8")  # no marker
        result = _run_init(target)
        assert "my-own-command.md" not in result.stderr


# ── H4 settings.json side-by-side render ───────────────────────────────────


class TestSettingsJsonSideBySide:
    def test_no_new_render_when_settings_identical(self, tmp_path):
        """W5-3 (TP-177): a no-op re-init (settings.json already equals what a
        fresh init emits) must NOT render a .new -- the empty-diff artifact was
        getting staged by `git add -A` and churned on every re-init."""
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        assert settings_path.exists()
        result = _run_init(target)
        new_path = target / ".claude" / "settings.json.new"
        assert not new_path.exists(), (
            "settings.json.new was rendered on an identical re-init (W5-3 "
            "regression: empty-diff artifact).\n--- stderr ---\n" + result.stderr
        )
        assert "settings.json.new" not in result.stderr

    def test_new_rendered_when_settings_differs(self, tmp_path):
        """The side-by-side .new render still fires when the existing
        settings.json genuinely differs from a fresh init (the real upgrade
        case): the operator gets a template to diff + merge."""
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        # Make the on-disk settings differ from what a fresh init emits.
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        data["_stale_user_key"] = "from an older deployment"
        settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result = _run_init(target)
        new_path = target / ".claude" / "settings.json.new"
        assert new_path.is_file(), (
            "expected .claude/settings.json.new on a rerun where settings.json "
            "differs from a fresh init.\n--- stderr ---\n" + result.stderr
        )
        rendered = json.loads(new_path.read_text(encoding="utf-8"))
        assert "hooks" in rendered, "rendered .new template missing hooks block"
        assert rendered.get("_espalier_managed") is True, (
            "rendered .new template missing _espalier_managed sentinel"
        )
        assert "diff" in result.stderr and "settings.json.new" in result.stderr


# ── H6 blueprint symlink advisory ──────────────────────────────────────────


class TestBlueprintSymlinkAdvisory:
    @requires_symlink
    def test_blueprint_symlink_advisory(self, tmp_path, capsys):
        # Lay out a fake repo root that has a symlinked cc/ folder pointing
        # at a sibling so _bp_dir's "or parent is a symlink" branch fires.
        real_cc = tmp_path / "real_cc"
        (real_cc / "blueprints").mkdir(parents=True)
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pyproject.toml").write_text("", encoding="utf-8")
        (repo / "tools" / "cc").mkdir(parents=True)
        (repo / "cc").symlink_to(real_cc, target_is_directory=True)

        # Reload cognitive_blueprint with this repo's pyproject as anchor.
        # _maybe_warn_symlink latches once per process, so reload to reset.
        spec = importlib.util.spec_from_file_location(
            "_tp51_blueprint",
            REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py",
        )
        bp_mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = bp_mod
        spec.loader.exec_module(bp_mod)
        bp_mod._SYMLINK_ADVISORY_EMITTED = False

        import os
        orig_cwd = Path.cwd()
        try:
            os.chdir(repo)
            bp_mod._bp_dir()
        finally:
            os.chdir(orig_cwd)
        captured = capsys.readouterr()
        assert "symlinked" in captured.err, (
            f"expected symlink advisory on stderr; got: {captured.err!r}"
        )
        # Second call within the same process must NOT re-emit
        # (the module-level latch is the test target).
        try:
            os.chdir(repo)
            bp_mod._bp_dir()
        finally:
            os.chdir(orig_cwd)
        captured2 = capsys.readouterr()
        assert "symlinked" not in captured2.err, (
            "advisory re-emitted on second call; expected one-shot latch"
        )


# ── TP-169 §13 #9 / 169-D stale-matcher WARN scoping ───────────────────────


class TestStaleMatcherWarn:
    """The re-init stale-matcher WARN must NOT fire on a correct config (the 169-D
    false positive) but MUST fire on a genuinely pre-v0.6.5 settings.json. This is
    the end-to-end earn-the-red: against pre-fix HEAD the first test fails because
    the WARN false-fires on every re-init of a canonical config."""

    def test_reinit_over_canonical_settings_does_not_warn(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)              # writes a canonical settings.json
        result = _run_init(target)     # re-init over it
        assert "STALE MATCHER" not in result.stderr, (
            "stale-matcher WARN false-fired on a correct re-init (169-D):\n"
            "--- stderr ---\n" + result.stderr
        )
        assert "pre-v0.6.5" not in result.stderr, (
            "pre-v0.6.5 WARN false-fired on a correct re-init (169-D):\n"
            "--- stderr ---\n" + result.stderr
        )

    def test_reinit_over_stale_settings_warns(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        # Narrow write_guard's matcher to a pre-v0.6.5 combined form with no mcp__.
        narrowed = False
        for entries in data["hooks"].values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    args = hook.get("args", [])
                    if any("write_guard.py" in a for a in args):
                        entry["matcher"] = "Write|Edit|NotebookEdit|Bash|PowerShell"
                        narrowed = True
        assert narrowed, "fixture setup: write_guard entry not found in settings.json"
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
        result = _run_init(target)
        assert "STALE MATCHER" in result.stderr or "pre-v0.6.5" in result.stderr, (
            "stale-matcher WARN failed to fire on a genuinely stale "
            "settings.json:\n--- stderr ---\n" + result.stderr
        )
        # TP-189-D (Task 3): the WARN now recommends the non-destructive
        # `espalier upgrade`, not destructive `rm + re-init`.
        assert "-m espalier upgrade" in result.stderr, (
            "stale-matcher WARN should recommend `espalier upgrade`:\n" + result.stderr
        )
        assert "rm .claude/settings.json && python -m espalier init" not in result.stderr, (
            "stale-matcher WARN still recommends destructive rm + re-init:\n" + result.stderr
        )


# ── TP-176 W2-2 recall-hook-wiring WARN ────────────────────────────────────


class TestRecallHookWiringWarn:
    """Re-init over a pre-TP-163 settings.json (no SubagentStart /
    PostToolUseFailure events) must emit a non-blocking WARN naming the
    missing recall-engine events; a canonical re-init must stay silent."""

    def test_reinit_over_canonical_settings_does_not_warn_recall(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)           # canonical settings.json has both events
        result = _run_init(target)
        assert "recall-engine hook event" not in result.stderr, (
            "recall-hook WARN false-fired on a correct re-init:\n"
            "--- stderr ---\n" + result.stderr
        )

    def test_reinit_over_pre_tp163_settings_warns_recall(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        # Simulate a pre-TP-163 deployment: drop the recall-engine events.
        for ev in ("SubagentStart", "PostToolUseFailure"):
            data["hooks"].pop(ev, None)
        settings_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
        result = _run_init(target)
        assert "recall-engine hook event" in result.stderr, (
            "recall-hook WARN failed to fire on a pre-TP-163 settings.json:\n"
            "--- stderr ---\n" + result.stderr
        )
        assert "SubagentStart" in result.stderr
        assert "PostToolUseFailure" in result.stderr


# ── M9 manifest schema_version + algorithm ─────────────────────────────────


class TestManifestSchemaVersion:
    def test_manifest_schema_version_round_trip(self, tmp_path):
        """write_manifest stores schema_version=1 and verify accepts it."""
        target = _make_target(tmp_path)
        _run_init(target)
        manifest_path = target / ".espalier" / "integrity.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        integ = _load_integrity_module()
        assert manifest.get("schema_version") == integ.MANIFEST_SCHEMA_VERSION
        assert manifest.get("algorithm") == integ.MANIFEST_HASH_ALGORITHM
        ok, mismatched = integ.verify_integrity(target)
        assert ok, f"verify_integrity unexpectedly mismatched: {mismatched}"

    def test_manifest_forward_version_refuses(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        manifest_path = target / ".espalier" / "integrity.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Bump schema_version above the verifier's supported value to
        # simulate a future manifest read by an older verifier.
        manifest["schema_version"] = 99
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        integ = _load_integrity_module()
        ok, mismatched = integ.verify_integrity(target)
        assert ok is False, "verify_integrity must refuse forward schema_version"
        assert mismatched and "schema_version_unsupported" in mismatched[0], (
            f"expected schema_version_unsupported sentinel; got {mismatched}"
        )

    def test_manifest_unsupported_algorithm_refuses(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        manifest_path = target / ".espalier" / "integrity.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["algorithm"] = "blake3"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        integ = _load_integrity_module()
        ok, mismatched = integ.verify_integrity(target)
        assert ok is False, "verify_integrity must refuse unsupported algorithm"
        assert mismatched and "algorithm_unsupported" in mismatched[0], (
            f"expected algorithm_unsupported sentinel; got {mismatched}"
        )


# ── B-1 new-adopter settings honesty (OSS-launch blocker) ──────────────────


class TestNewAdopterSettingsHonesty:
    """A repo that already uses Claude Code brings its OWN .claude/settings.json
    (permissions, no Espalier hooks). init/fuse preserves it (sovereignty), so no
    hooks get wired — the harness ships disarmed. The operator must be told the
    honest truth (enforcement NOT active + how to activate), NOT the upgrade-framed
    recall WARN that mis-reads a brand-new adopter as a pre-TP-163 Espalier user."""

    @staticmethod
    def _make_adopter_target(tmp_path: Path) -> Path:
        target = _make_target(tmp_path)
        claude = target / ".claude"
        claude.mkdir(exist_ok=True)
        # The adopter's own settings.json: permissions only, NO Espalier hooks.
        (claude / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def test_init_over_adopter_settings_warns_enforcement_not_active(self, tmp_path):
        target = self._make_adopter_target(tmp_path)
        result = _run_init(target)
        assert "NOT active" in result.stderr and "merge-settings" in result.stderr, (
            "honest enforcement-not-active WARN missing for a new adopter whose "
            "own settings.json blocks hook wiring:\n--- stderr ---\n" + result.stderr
        )

    def test_init_over_adopter_settings_does_not_misfire_recall_warn(self, tmp_path):
        # earn-the-red: against pre-fix HEAD the recall-engine WARN false-fires
        # here, framing a brand-new adopter as a pre-TP-163 Espalier user missing
        # 2 reporters when in fact ALL hooks are absent.
        target = self._make_adopter_target(tmp_path)
        result = _run_init(target)
        assert "recall-engine hook event" not in result.stderr, (
            "recall-engine upgrade WARN mis-fired on a brand-new adopter "
            "(no Espalier hooks at all):\n--- stderr ---\n" + result.stderr
        )

    def test_init_over_adopter_settings_preserves_their_file(self, tmp_path):
        # Sovereignty: the adopter's settings.json is left untouched (the
        # chosen "honest + merge helper" behavior never auto-edits their file).
        target = self._make_adopter_target(tmp_path)
        settings = target / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        _run_init(target)
        after = settings.read_text(encoding="utf-8")
        assert before == after, "adopter's settings.json was modified by init"
        assert json.loads(after).get("permissions", {}).get("allow") == ["Bash(ls:*)"]

    def test_banner_honest_when_hooks_unwired(self, tmp_path):
        # earn-the-red: pre-fix the banner unconditionally prints "Hooks now
        # intercept ..." even though no hooks were wired — the governance tool
        # claiming it is armed when it is not.
        target = self._make_adopter_target(tmp_path)
        result = _run_init(target)
        assert "Hooks are NOT yet active" in result.stdout, (
            "banner did not state the honest unwired state:\n" + result.stdout
        )
        assert "merge-settings" in result.stdout, (
            "banner did not point at the activation command:\n" + result.stdout
        )
        assert "Hooks now intercept" not in result.stdout, (
            "banner falsely claims hooks intercept when they are unwired:\n"
            + result.stdout
        )

    def test_plain_init_leaves_existing_settings_disarmed(self, tmp_path):
        # TP-271b earn-the-red / disarm pin: plain `init` (no --wire-hooks) over a
        # hookless settings.json ships the harness DISARMED. Green today; it is also
        # the non-TTY regression anchor for the 2-A interactive prompt — a subprocess
        # pipe is not a TTY, so the prompt must no-op here and this must STAY green.
        target = self._make_adopter_target(tmp_path)
        before = (target / ".claude" / "settings.json").read_bytes()
        out = _run_init(target)  # plain init, no --wire-hooks; returns CompletedProcess
        settings = json.loads(
            (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        # (a) hooks NOT wired — the on-disk oracle
        from espalier.cli import _settings_has_espalier_hooks

        assert _settings_has_espalier_hooks(settings) is False
        assert "tools/cc/hooks" not in json.dumps(settings.get("hooks", {}))
        # (b) banner honesty — the banner prints via plain print() -> stdout (assert on
        #     out.stdout: _run_init returns a CompletedProcess, not a str)
        assert "Hooks are NOT yet active" in out.stdout
        assert "Hooks now intercept" not in out.stdout
        # (c) sovereignty — the operator's file is byte-identical
        assert (target / ".claude" / "settings.json").read_bytes() == before

    def test_banner_truthful_when_hooks_wired_fresh(self, tmp_path):
        # A fresh repo (no pre-existing settings.json) wires the full hooks block,
        # so the original celebratory banner is the TRUTH and must still print.
        target = _make_target(tmp_path)
        result = _run_init(target)
        assert "Hooks now intercept" in result.stdout, (
            "banner lost the truthful wired-state message:\n" + result.stdout
        )
        assert "Hooks are NOT yet active" not in result.stdout


class TestWireHooksFlag:
    """TP-183: `--wire-hooks` is the opt-in complement to B-1. With the flag,
    init runs the same merge `espalier merge-settings` uses when an existing
    settings.json has no Espalier hooks, arming the harness in ONE command.
    WITHOUT it, the B-1 safe default (preserve + WARN + point at merge-settings)
    is unchanged. A malformed file is refused, never overwritten."""

    @staticmethod
    def _adopter(tmp_path: Path, settings: dict) -> Path:
        target = _make_target(tmp_path)
        claude = target / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        return target

    @staticmethod
    def _run_init_wire(target: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target),
             "--wire-hooks"],
            capture_output=True, text=True, timeout=120, check=True, encoding="utf-8",
        )

    def test_wire_hooks_arms_in_one_shot(self, tmp_path):
        # earn-the-red: pre-TP-183 init rejects `--wire-hooks` (unknown arg);
        # post-fix it wires the hooks while preserving every operator key.
        target = self._adopter(
            tmp_path,
            {"permissions": {"allow": ["Bash(ls:*)"]}, "env": {"FOO": "bar"}},
        )
        settings = target / ".claude" / "settings.json"
        result = self._run_init_wire(target)
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "tools/cc/hooks" in json.dumps(data.get("hooks", {})), (
            "hooks not wired by --wire-hooks"
        )
        # Operator keys preserved verbatim.
        assert data["permissions"]["allow"] == ["Bash(ls:*)"]
        assert data["env"]["FOO"] == "bar"
        # The file stays the operator's: never stamped harness-managed.
        assert "_espalier_managed" not in data
        # Backup written so the operator can revert.
        assert (target / ".claude" / "settings.json.bak").exists(), (
            ".bak backup not written by --wire-hooks"
        )
        # Banner tells the truth: armed.
        assert "Hooks now intercept" in result.stdout, result.stdout
        assert "Hooks are NOT yet active" not in result.stdout
        # No misleading .new render once we wired the live file in place.
        assert not (target / ".claude" / "settings.json.new").exists(), (
            ".new render should be suppressed after a one-shot wire"
        )

    def test_without_flag_default_unchanged(self, tmp_path):
        # The regression pin: WITHOUT the flag the B-1 safe path still fires —
        # file preserved untouched, honest WARN + merge-settings pointer, banner
        # honest. Proves the new flag did not move the default.
        target = self._adopter(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        settings = target / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        result = _run_init(target)
        assert settings.read_text(encoding="utf-8") == before, (
            "default init (no --wire-hooks) modified the adopter's settings.json"
        )
        assert "NOT active" in result.stderr and "merge-settings" in result.stderr
        assert "Hooks are NOT yet active" in result.stdout

    def test_wire_hooks_idempotent_on_already_wired(self, tmp_path):
        # Second --wire-hooks run on an already-wired file is a no-op: the
        # already-wired settings.json is left byte-for-byte unchanged (no re-merge,
        # no duplicated Espalier hook events).
        target = self._adopter(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        settings = target / ".claude" / "settings.json"
        self._run_init_wire(target)
        after_first = settings.read_text(encoding="utf-8")
        self._run_init_wire(target)
        after_second = settings.read_text(encoding="utf-8")
        assert after_second == after_first, (
            "second --wire-hooks churned an already-wired settings.json"
        )
        # write_guard is wired exactly once — the merge was not re-applied.
        assert after_second.count("write_guard.py") == 1, (
            "Espalier hook duplicated on re-wire"
        )

    def test_wire_hooks_tops_up_partial_upgrade(self, tmp_path):
        """TP-192 M3 sister-site: `init --wire-hooks` over a settings wired by an
        OLDER engine (missing a newer canonical event, e.g. PostToolUseFailure)
        must TOP UP the missing event — pre-fix the `not settings_hooks_wired`
        (ANY event wired) gate skipped the merge and only WARNed to run
        `upgrade`, the exact gap the M3 merge core closes."""
        from espalier.cli import _build_settings_json, _event_groups_have_espalier_hook

        canonical = _build_settings_json(profile_name="workflow", repo_root=tmp_path)
        older = {k: v for k, v in canonical["hooks"].items() if k != "PostToolUseFailure"}
        assert "PostToolUseFailure" not in older
        target = self._adopter(tmp_path, {"hooks": older})
        self._run_init_wire(target)
        after = json.loads(
            (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        )["hooks"]
        # the missing newer event is topped up...
        assert _event_groups_have_espalier_hook(after.get("PostToolUseFailure")), list(after)
        # ...and an already-wired event was NOT double-appended.
        assert len(after["PreToolUse"]) == len(older["PreToolUse"])

    @staticmethod
    def _adopter_raw(tmp_path: Path, raw: str) -> Path:
        """An adopter whose settings.json is RAW text (may be unparseable / a
        non-object top level — the shapes a dict-only fixture can't express)."""
        target = _make_target(tmp_path)
        claude = target / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "settings.json").write_text(raw, encoding="utf-8")
        return target

    def test_wire_hooks_refuses_malformed_without_clobber(self, tmp_path):
        # decision 3: a malformed settings.json (non-object `hooks`) is REFUSED,
        # never overwritten. The operator's content survives; banner stays honest.
        target = self._adopter(
            tmp_path,
            {"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": 42},
        )
        settings = target / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        result = self._run_init_wire(target)
        assert settings.read_text(encoding="utf-8") == before, (
            "--wire-hooks clobbered a malformed settings.json (must refuse)"
        )
        assert "could not wire" in result.stderr and "bad_hooks" in result.stderr, (
            "no honest refusal message on a non-object 'hooks' file:\n"
            + result.stderr
        )
        assert "Hooks are NOT yet active" in result.stdout

    def test_wire_hooks_refuses_unparseable_without_clobber(self, tmp_path):
        # The adversarial-review gap (TP-183): an UNPARSEABLE settings.json sets
        # `existing = None`, so the dict-guarded branch would skip the honest
        # refusal and fall through to the generic message. The flag must STILL
        # name the parse failure (and never clobber).
        target = self._adopter_raw(tmp_path, "{not valid json")
        settings = target / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        result = self._run_init_wire(target)
        assert settings.read_text(encoding="utf-8") == before, (
            "--wire-hooks clobbered an unparseable settings.json (must refuse)"
        )
        assert "could not wire" in result.stderr and "parse_error" in result.stderr, (
            "unparseable file did not get the honest --wire-hooks refusal:\n"
            + result.stderr
        )
        assert "Hooks are NOT yet active" in result.stdout

    def test_wire_hooks_refuses_nondict_without_clobber(self, tmp_path):
        # Sister shape: a top-level JSON array/string/number is valid JSON but not
        # a settings object. Same honest-refusal-without-clobber contract.
        target = self._adopter_raw(tmp_path, "[1, 2, 3]\n")
        settings = target / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        result = self._run_init_wire(target)
        assert settings.read_text(encoding="utf-8") == before, (
            "--wire-hooks clobbered a non-object settings.json (must refuse)"
        )
        assert "could not wire" in result.stderr and "not_object" in result.stderr, (
            "non-object top-level did not get the honest --wire-hooks refusal:\n"
            + result.stderr
        )
        assert "Hooks are NOT yet active" in result.stdout

    def test_wire_hooks_default_unchanged_on_unparseable(self, tmp_path):
        # Regression pin: WITHOUT the flag, an unparseable settings.json path is
        # byte-identical to pre-TP-183 — no --wire-hooks message leaks in.
        target = self._adopter_raw(tmp_path, "{not valid json")
        settings = target / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        result = _run_init(target)
        assert settings.read_text(encoding="utf-8") == before
        assert "wire-hooks" not in result.stderr and "wire-hooks" not in result.stdout

    def test_wire_hooks_delivers_the_statusline(self, tmp_path):
        """DEF-798, driven 2026-09-15 on a POSIX throwaway: a permissions-only
        file under --wire-hooks got ten events, the shim and the script on
        disk, and NO statusLine -- the fresh path alone rendered it. The
        merge now adds espalier's key when it is absent, the wired line says
        so, and the .new render stays suppressed (nothing left to diff)."""
        from espalier.cli import _build_settings_json

        target = self._adopter(tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}})
        result = self._run_init_wire(target)
        data = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        fresh = _build_settings_json(profile_name="workflow", repo_root=target)
        assert data.get("statusLine") == fresh["statusLine"], data.keys()
        assert data["permissions"]["allow"] == ["Bash(ls:*)"]
        assert "added espalier's statusLine" in result.stderr, result.stderr
        assert "Espalier hook event" in result.stderr and " and added" in result.stderr, result.stderr
        assert not (target / ".claude" / "settings.json.new").exists()

    def test_wire_hooks_statusline_only_topup_claims_no_transition(self, tmp_path):
        """DEF-798 (both reviewers): a re-run of --wire-hooks over a file wired
        by an older engine -- every event current, no statusLine -- writes only
        the key. That is not a transition: the sentence says "was already
        active", the guard merge-settings has carried since DEF-427, never
        "now". The first cut shared the did-phrase and kept an unconditional
        "now"."""
        target = _make_target(tmp_path)
        _run_init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        del data["statusLine"]
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result = self._run_init_wire(target)
        assert "added espalier's statusLine" in result.stderr, result.stderr
        assert "Enforcement was already active." in result.stderr, result.stderr
        assert "now active" not in result.stderr, result.stderr

    def test_wire_hooks_keeps_an_adopters_own_statusline(self, tmp_path):
        own = {"type": "command", "command": "my-prompt --short"}
        target = self._adopter(
            tmp_path, {"permissions": {"allow": ["Bash(ls:*)"]}, "statusLine": own},
        )
        result = self._run_init_wire(target)
        data = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert data["statusLine"] == own
        assert "statusLine" not in result.stderr, result.stderr


class TestEmptySettingsJsonIsAbsent:
    """DEF-700, second leg: init preserved a 0-byte settings.json as
    operator-edited, rendered settings.json.new beside it and warned that hooks
    were not active -- a move-aside round trip for a file with no content to
    preserve. An effectively-empty file (0 bytes, whitespace, a bare BOM) is
    now absent for that decision; any non-empty bytes keep the preserve rule."""

    @pytest.mark.parametrize(
        "raw",
        [b"", b" \n\t\n", b"\xef\xbb\xbf", b"\xff\xfe", b"\xff\xfe\x00\x00"],
        ids=["zero-bytes", "whitespace", "utf8-bom-only", "utf16-bom-only", "utf32-bom-only"],
    )
    def test_empty_settings_is_rewritten_in_place(self, tmp_path, raw):
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        settings_path.write_bytes(raw)
        result = _run_init(target)
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" in data and data.get("_espalier_managed") is True, data
        assert not (target / ".claude" / "settings.json.new").exists(), (
            "an empty file still went through the preserve + .new path\n" + result.stderr
        )
        assert "preserved" not in result.stderr, result.stderr
        assert "was empty" in result.stderr, result.stderr

    def test_a_truncated_file_is_still_preserved(self, tmp_path):
        """The control: content, however broken, is never overwritten."""
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        broken = b'{"hooks": {"PreToolUse": ['
        settings_path.write_bytes(broken)
        result = _run_init(target)
        assert settings_path.read_bytes() == broken
        assert (target / ".claude" / "settings.json.new").is_file(), result.stderr
        assert "was empty" not in result.stderr, result.stderr

    def test_upgrade_dry_run_names_the_in_place_rewrite(self, tmp_path):
        """`upgrade .` is the preview the docs send an operator to before
        `--execute`; the one exception to the preserve rule must be visible
        there, not only on stderr after the write has happened."""
        target = _make_target(tmp_path)
        _run_init(target)
        settings_path = target / ".claude" / "settings.json"
        settings_path.write_bytes(b"")
        # A version-current tree returns "nothing to do" before the preview or
        # the deploy; the rewrite only happens on a stale tree, so stage one.
        manifest = target / "cc" / "PACK_MANIFEST.txt"
        stamped = manifest.read_text(encoding="utf-8")
        assert "# espalier-version:" in stamped, stamped[:200]
        manifest.write_text(
            "\n".join(
                "# espalier-version: 0.0.0" if line.startswith("# espalier-version:") else line
                for line in stamped.splitlines()
            ) + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "upgrade", str(target)],
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "would rewrite an EMPTY .claude/settings.json" in result.stdout, result.stdout
        assert settings_path.read_bytes() == b"", "a dry run wrote the file"



class TestInitBannerNamesDeadReporters:
    """DEF-619: "Hooks now intercept ..." is a sentence about the blocking
    gates. A reporter neutered in an existing settings.json used to hide
    behind it; the banner now names the dead reporters on the armed branch
    and points at doctor, which carries the remedy per hook."""

    def test_fresh_init_prints_no_reporter_line(self, tmp_path):
        target = tmp_path / "fresh"
        target.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
        result = _run_init(target)
        assert "Hooks now intercept" in result.stdout, result.stdout
        assert "NOT wired:" not in result.stdout, result.stdout

    def test_shell_form_reporters_are_not_called_dead(self, tmp_path):
        """Driven by the failure-mode pass: on a pre-v0.6.5 shell-form file the
        enforcement claim forgives the gates (a shape the oracle cannot read),
        so the banner said "Hooks now intercept" and then named all eight
        reporters as dead in the next line. The claim and the caveat must
        forgive the same shape."""
        target = tmp_path / "fresh"
        target.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
        _run_init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        for groups in data["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    hook["command"] = hook["command"] + " " + " ".join(hook.pop("args"))
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = _run_init(target)
        assert "Hooks now intercept" in result.stdout, result.stdout
        assert "NOT wired:" not in result.stdout, result.stdout

    def test_narrowed_gate_matcher_is_not_forgiven_by_the_armed_claim(self, tmp_path):
        """Driven 2026-09-07 on this exact tree: `init` printed "Hooks now
        intercept" over a plan_guard whose matcher had been narrowed to
        `Write`, because the shape classified as legacy_form and the claim
        forgives legacy_form. A readable entry that does not fire is dead."""
        target = tmp_path / "fresh"
        target.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
        _run_init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        for entry in data["hooks"]["PreToolUse"]:
            if "plan_guard.py" in json.dumps(entry):
                entry["matcher"] = "Write"
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = _run_init(target)
        assert "Hooks now intercept" not in result.stdout, result.stdout
        assert "Hooks are NOT yet active" in result.stdout, result.stdout
        assert "plan_guard.py" in result.stdout, result.stdout

    def test_neutered_reporter_is_named_beside_the_armed_claim(self, tmp_path):
        target = tmp_path / "fresh"
        target.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
        _run_init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"]["PostCompact"][0]["hooks"][0]["command"] = "echo"
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = _run_init(target)
        assert "Hooks now intercept" in result.stdout, result.stdout
        assert "NOT wired: post_compact.py is a reporter hook" in result.stdout, result.stdout
        assert "doctor" in result.stdout, result.stdout


class TestUpgradeDoesNotCallADisarmedTreeCurrent:
    """DEF-618 (driven by the failure-mode pass): `upgrade --execute` on a tree
    with a neutered gate printed "settings.json hooks already current" -- the
    merge's word for "every event carries an espalier entry", which an `echo`
    entry satisfies. The enforcement claim decides now, and the disarmed
    narration names --repair."""

    def test_neutered_gate_is_narrated_not_called_current(self, tmp_path):
        target = tmp_path / "fresh"
        target.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
        _run_init(target)
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"]["Stop"][0]["hooks"][0]["command"] = "echo"
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "upgrade", str(target), "--execute"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        assert "already current" not in result.stdout, result.stdout
        assert "stop_gate.py" in result.stderr and "--repair" in result.stderr, result.stderr



class TestUpgradeNamesAnAbsentStatusLine:
    """DEF-798: a version-current install whose settings.json was wired before
    the merge learned to add the key has no statusLine, and the
    version-current branch never merges -- so it must NAME the state and the
    verb that adds it, the way it names missing allow rules and a disarmed
    tree, instead of saying "nothing to do"."""

    @staticmethod
    def _drop_statusline(target: Path) -> Path:
        settings = target / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        del data["statusLine"]
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return settings

    @staticmethod
    def _upgrade(target: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "espalier.cli", "upgrade", str(target), *extra],
            capture_output=True, text=True, timeout=60, encoding="utf-8",
        )

    def test_version_current_preview_names_the_absent_key_and_the_verb(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        self._drop_statusline(target)
        dry = self._upgrade(target)
        assert dry.returncode == 0, dry.stderr
        assert "nothing to do" not in dry.stdout, dry.stdout
        assert "has no statusLine" in dry.stdout, dry.stdout
        assert "merge-settings ." in dry.stdout and "never touches one of yours" in dry.stdout, dry.stdout
        # The branch is read-only in both modes; the verb it names adds the key.
        done = self._upgrade(target, "--execute")
        assert "has no statusLine" in done.stdout, done.stdout
        merged = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "merge-settings", str(target)],
            capture_output=True, text=True, timeout=60, encoding="utf-8",
        )
        assert "added espalier's statusLine" in merged.stdout, merged.stdout
        data = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert data["statusLine"]["command"], data.keys()

    def test_a_present_statusline_is_not_named(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        dry = self._upgrade(target)
        assert "statusLine" not in dry.stdout and "nothing to do" in dry.stdout, dry.stdout


class TestUpgradePreviewNamesTheSeedsItWouldRefresh:
    """DEF-774, the widened shape: a seed doc whose packaged content changed
    without a version bump (the 2026-09-11 banner rewording did exactly
    that) is refreshed by ``init`` and by the seed stage of ``upgrade``, but
    the version-current branch said "nothing to do" without asking, and the
    stale branch's preview was one static sentence -- so the preview an
    adopter ran promised nothing and ``git status`` then showed the modified
    docs. The preview now reads the decision the write uses and names them.
    """

    @staticmethod
    def _age_one_seed(target: Path) -> str:
        from espalier.managed_inventory import get_seed_docs, seed_stamp_line
        rel = next(r for r in get_seed_docs() if r.startswith("docs/"))
        (target / rel).write_text(seed_stamp_line("older\n") + "older\n", encoding="utf-8")
        return rel

    @staticmethod
    def _upgrade(target: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "espalier.cli", "upgrade", str(target), *extra],
            # 60: the suite's own ceiling; a larger budget cannot fire first (DEF-665).
            capture_output=True, text=True, timeout=60, encoding="utf-8",
        )

    def test_version_current_dry_run_names_the_seed_and_execute_refreshes_it(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        rel = self._age_one_seed(target)
        dry = self._upgrade(target)
        assert dry.returncode == 0, dry.stderr
        assert "nothing to do" not in dry.stdout, dry.stdout
        assert "init-seeded doc behind the packaged copy" in dry.stdout, dry.stdout
        assert "would re-deploy init-seeded docs: 1 seed doc refreshed" in dry.stdout, dry.stdout
        assert rel in dry.stdout, dry.stdout
        assert (target / rel).read_text(encoding="utf-8").endswith("older\n"), "the dry run wrote"
        done = self._upgrade(target, "--execute")
        assert done.returncode == 0, done.stderr
        assert "re-deployed init-seeded docs: 1 seed doc refreshed" in done.stdout, done.stdout
        assert rel in done.stdout, done.stdout
        assert not (target / rel).read_text(encoding="utf-8").endswith("older\n")

    def test_a_current_tree_still_says_nothing_to_do(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        dry = self._upgrade(target)
        assert dry.returncode == 0, dry.stderr
        assert "nothing to do" in dry.stdout, dry.stdout


class TestUpgradePreviewSurvivesAMissingPackagedSeed:
    """The read-only preview renders the packaged seeds to decide what it
    would refresh; on an engine install without its package data that read
    raises, and `upgrade .` -- the verb an adopter runs to diagnose exactly
    that install -- died with a traceback where it had printed a sentence
    (the failure-mode review drove it). The preview degrades to the WARN the
    branch already prints for the managed surface; the write arms still
    raise, because a write that cannot render has nothing honest to write."""

    def test_dry_run_warns_and_exits_zero_when_the_seed_source_is_missing(
        self, tmp_path, monkeypatch, capsys,
    ):
        import argparse
        from espalier import cli, managed_inventory
        target = _make_target(tmp_path)
        _run_init(target)

        def _missing(rel: str) -> str:
            raise FileNotFoundError(f"assets/{rel}")

        monkeypatch.setattr(managed_inventory, "render_seed_body", _missing)
        rc = cli.cmd_upgrade(argparse.Namespace(repo=str(target), execute=False))
        captured = capsys.readouterr()
        assert rc == 0, captured.err
        assert "packaged seed source is missing" in captured.err, captured.err
        assert "Traceback" not in captured.err
        assert "nothing to do" in captured.out or "[upgrade]" in captured.out, captured.out
