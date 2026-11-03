"""Unit tests for ``scripts/wheel_smoke.py`` helpers (TP-02 §5).

Pins the per-helper contracts without building an actual wheel:
``assert_surface`` fed synthetic deployed trees, ``count_wired_hooks``
fed synthetic settings dicts, ``locate_wheel`` against tmp dirs.
The full end-to-end smoke runs in release CI (and as the slow
integration test in
``tests/test_wheel_install_surface_parity.py``). Without this
contract a refactor of any helper could silently regress the
release-gate's wheel-smoke step without the failure surfacing
until cut-day — the unit tests catch the regression in seconds
instead of paying the multi-minute integration cost on every PR.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from espalier._safe_walk import visible

import pytest

from espalier.artifact_parity import clear_stale_packaging_state
from tests._live_tree import checkout_glob
from tests._locked import locked

REPO_ROOT = Path(__file__).resolve().parent.parent

# wheel_smoke lives in scripts/ (not a Python package). Load it by file path
# so we can unit-test its helpers without putting scripts/ on sys.path.
# scripts/ is dev tooling and is intentionally NOT included in the sdist
# (per MANIFEST.in); skip the file when running from a sdist install.
_WHEEL_SMOKE_PATH = REPO_ROOT / "scripts" / "wheel_smoke.py"
if not _WHEEL_SMOKE_PATH.is_file():
    pytest.skip(
        "scripts/wheel_smoke.py is dev tooling not shipped in sdist; "
        "this test file applies only to source-checkout / source-archive runs.",
        allow_module_level=True,
    )

spec = importlib.util.spec_from_file_location("wheel_smoke", _WHEEL_SMOKE_PATH)
assert spec is not None and spec.loader is not None
wheel_smoke = importlib.util.module_from_spec(spec)
sys.modules["wheel_smoke"] = wheel_smoke
spec.loader.exec_module(wheel_smoke)


# Marker assignment lives in tests/conftest.py::_MARKER_RULES (release).


# ---------------------------------------------------------------------------
# Canary — independently verify wheel_smoke's expected counts against the
# packaged asset tree. TP-RELEASE-24: closes the self-confirming-fixture
# pattern where test_wheel_smoke synthesized N commands matching the
# constant, regardless of whether the constant matched reality.
# ---------------------------------------------------------------------------

ASSETS_CLAUDE = REPO_ROOT / "espalier" / "assets" / "claude"
CC_COMMANDS_MD = REPO_ROOT / "cc" / "COMMANDS.md"
# A command row in cc/COMMANDS.md is `| `/<slug>` | ... |`. The "Stable
# actions" table below it uses `| `<name>` |` WITHOUT a leading slash, so
# this anchor matches only command rows.
_COMMAND_ROW_RE = re.compile(r"^\|\s*`/([a-z][\w-]*)`")


@pytest.mark.contract
class TestPackagedCommandsMatchDeclaredSurface:
    """De-circularize the command-count canary (TP-150 F-2). The pre-fix
    canary compared `EXPECTED_COMMAND_COUNT` against the SAME asset glob the
    constant derives from (`_count_packaged_assets`) -- a tautology that can
    never catch a packaging-vs-surface drift. This binds the packaged asset
    tree (`espalier/assets/claude/commands/`) to a SECOND, independently
    maintained witness: the committed `cc/COMMANDS.md` command table, which
    is rendered from `.claude/commands/` -- NOT from the package glob. A
    command added to one surface but not the other now fails the gate.
    """

    def test_packaged_commands_match_commands_md_table(self):
        packaged = {p.stem for p in visible(checkout_glob(ASSETS_CLAUDE / "commands", "*.md"), ASSETS_CLAUDE / "commands")}
        declared = {
            m.group(1)
            for line in CC_COMMANDS_MD.read_text(encoding="utf-8").splitlines()
            if (m := _COMMAND_ROW_RE.match(line))
        }
        assert packaged == declared, (
            "Drift between the packaged command assets and cc/COMMANDS.md.\n"
            f"  only in espalier/assets/.../commands/: {sorted(packaged - declared)}\n"
            f"  only in cc/COMMANDS.md command table:  {sorted(declared - packaged)}\n"
            "Regenerate cc/COMMANDS.md (or add the missing command asset) so "
            "the two independent witnesses agree."
        )


class TestExpectedCountsMatchPackagedAssets:
    """Each `EXPECTED_*` constant in wheel_smoke must agree with what's
    actually on disk in `espalier/assets/`.

    NOTE: EXPECTED_COMMAND_COUNT and EXPECTED_SKILL_COUNT are DERIVED at import
    from the same ``_count_packaged_assets()`` glob a ``constant == len(glob)``
    assertion would re-walk — so that shape is a self-comparison (X == X), not
    the independent canary an earlier docstring here claimed. Both the
    command-count (TP-326 G2-1) and the skill-count (TP-336) self-comparisons
    were removed on that basis: each packaged surface is honestly pinned
    elsewhere — the command surface against the hand-maintained ``cc/COMMANDS.md``
    witness by ``test_packaged_commands_match_commands_md_table`` above and the
    hand-set ``tests/_surface_expected.EXPECTED_COMMAND_COUNT`` literal by the
    surface-truth suite; the skill surface against the hand-set
    ``tests/_surface_expected.EXPECTED_SKILL_COUNT`` literal and its doc-claim pin
    ``test_skill_count_claims_match_inventory``. The agent-count method below is
    honest — a derived lower bound (MIN <= rich-agent count, both read from
    the packaged asset tree).
    """

    @pytest.mark.contract
    def test_expected_agent_count_min_at_most_packaged_rich_agents(self):
        """EXPECTED_AGENT_COUNT_MIN is a lower bound. It must be <= the
        count of rich (>= RICH_AGENT_MIN_BYTES) packaged agents."""
        # The asset tree ships the rich roster again (seven at HEAD); the
        # empty-tree branch below is the wheel-without-assets fallback.
        agents_dir = ASSETS_CLAUDE / "agents"
        if not agents_dir.is_dir():
            assert wheel_smoke.EXPECTED_AGENT_COUNT_MIN == 0
            return
        rich_agents = [
            p for p in visible(checkout_glob(agents_dir, "*.md"), agents_dir)
            if p.stat().st_size >= wheel_smoke.RICH_AGENT_MIN_BYTES
        ]
        assert wheel_smoke.EXPECTED_AGENT_COUNT_MIN <= len(rich_agents), (
            f"EXPECTED_AGENT_COUNT_MIN={wheel_smoke.EXPECTED_AGENT_COUNT_MIN} "
            f"exceeds {len(rich_agents)} rich agents in the asset tree."
        )

    def test_expected_hook_entry_count_matches_packaged_hooks(self):
        """Hook entry scripts live in tools/cc/hooks/ (not under
        espalier/assets/), so derive from there directly."""
        hook_entries = [
            p for p in checkout_glob(REPO_ROOT / "tools" / "cc" / "hooks", "*.py")
            if not p.name.startswith("_") and p.name != "__init__.py"
        ]
        assert wheel_smoke.EXPECTED_HOOK_ENTRY_COUNT == len(hook_entries), (
            f"EXPECTED_HOOK_ENTRY_COUNT={wheel_smoke.EXPECTED_HOOK_ENTRY_COUNT} "
            f"but {len(hook_entries)} hook entry scripts exist."
        )

    def test_expected_hook_helper_count_matches_packaged_helpers(self):
        helpers = [
            p for p in checkout_glob(REPO_ROOT / "tools" / "cc" / "hooks", "_*.py")
            if p.name != "__init__.py"
        ]
        assert wheel_smoke.EXPECTED_HOOK_HELPER_COUNT == len(helpers), (
            f"EXPECTED_HOOK_HELPER_COUNT={wheel_smoke.EXPECTED_HOOK_HELPER_COUNT} "
            f"but {len(helpers)} hook helpers exist."
        )


# ---------------------------------------------------------------------------
# locate_wheel
# ---------------------------------------------------------------------------


class TestLocateWheel:
    def test_missing_directory_raises_with_hint(self, tmp_path):
        with pytest.raises(wheel_smoke.SmokeFailure, match="wheel directory not found"):
            wheel_smoke.locate_wheel(tmp_path / "no-such-dir")

    def test_empty_directory_raises_with_hint(self, tmp_path):
        with pytest.raises(wheel_smoke.SmokeFailure, match="no espalier_harness"):
            wheel_smoke.locate_wheel(tmp_path)

    def test_picks_newest_wheel_when_multiple(self, tmp_path):
        older = tmp_path / "espalier_harness-0.4.0-py3-none-any.whl"
        newer = tmp_path / "espalier_harness-0.5.0-py3-none-any.whl"
        older.write_bytes(b"old")
        newer.write_bytes(b"new")
        assert wheel_smoke.locate_wheel(tmp_path) == newer

    def test_ignores_non_matching_files(self, tmp_path):
        wheel = tmp_path / "espalier_harness-0.5.0-py3-none-any.whl"
        wheel.write_bytes(b"")
        (tmp_path / "decoy.tar.gz").write_bytes(b"")
        (tmp_path / "espalier_harness-0.5.0.tar.gz").write_bytes(b"")
        assert wheel_smoke.locate_wheel(tmp_path) == wheel


# ---------------------------------------------------------------------------
# count_wired_hooks
# ---------------------------------------------------------------------------


class TestCountWiredHooks:
    def test_empty_settings(self):
        assert wheel_smoke.count_wired_hooks({}) == 0

    def test_no_hooks_section(self):
        assert wheel_smoke.count_wired_hooks({"permissions": {}}) == 0

    def test_counts_across_events(self):
        settings = {
            "hooks": {
                "SessionStart": [{"hooks": [{"command": "x"}]}],
                "PreToolUse": [{
                    "matcher": "*",
                    "hooks": [{"command": "a"}, {"command": "b"}],
                }],
                "Stop": [{"hooks": [{"command": "z"}]}],
            }
        }
        assert wheel_smoke.count_wired_hooks(settings) == 4

    def test_skips_entries_missing_command(self):
        settings = {
            "hooks": {
                "PreToolUse": [{
                    "hooks": [
                        {"command": "real"},
                        {"timeout": 5},  # no command — should be skipped
                    ]
                }]
            }
        }
        assert wheel_smoke.count_wired_hooks(settings) == 1

    def test_robust_to_malformed_shapes(self):
        # Each malformed shape should silently contribute 0, not crash.
        for bad in (
            {"hooks": "not-a-dict"},
            {"hooks": {"X": "not-a-list"}},
            {"hooks": {"X": [None, "string", {"hooks": None}]}},
            {"hooks": {"X": [{"hooks": ["not-a-dict"]}]}},
        ):
            assert wheel_smoke.count_wired_hooks(bad) == 0


# ---------------------------------------------------------------------------
# format_failure
# ---------------------------------------------------------------------------


class TestFormatFailure:
    def test_includes_msg_and_hint(self):
        out = wheel_smoke.format_failure("the bad thing", "the fix")
        assert "the bad thing" in out
        assert "hint:" in out
        assert "the fix" in out

    def test_two_lines(self):
        out = wheel_smoke.format_failure("x", "y")
        assert out.count("\n") == 1


# ---------------------------------------------------------------------------
# assert_surface — fixture builds a complete synthetic deployed surface
# ---------------------------------------------------------------------------


def _make_complete_target(target: Path) -> None:
    """Materialize a synthetic deployed surface that satisfies every assertion."""
    # Commands
    cmd_dir = target / ".claude" / "commands"
    cmd_dir.mkdir(parents=True)
    for i in range(wheel_smoke.EXPECTED_COMMAND_COUNT):
        (cmd_dir / f"cmd{i}.md").write_text(f"# cmd{i}\n", encoding="utf-8")

    # Skills
    skills_dir = target / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    for i in range(wheel_smoke.EXPECTED_SKILL_COUNT):
        sub = skills_dir / f"skill{i}"
        sub.mkdir()
        (sub / "SKILL.md").write_text(f"# skill{i}\n", encoding="utf-8")

    # Workflows (the fourth .claude kind): one .js body per expected count
    wf_dir = target / ".claude" / "workflows"
    wf_dir.mkdir(parents=True)
    for i in range(wheel_smoke.EXPECTED_WORKFLOW_COUNT):
        (wf_dir / f"_wf{i}.js").write_text(
            f"// espalier:managed\nexport const meta = {{ name: 'wf{i}', description: 'd' }}\n",
            encoding="utf-8",
        )

    # Agents — write one rich file per canonical name
    agents_dir = target / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    for name in wheel_smoke.CANONICAL_RICH_AGENTS:
        body = (
            "---\n"
            f"name: {name}\n"
            f"description: rich agent {name}\n"
            "model: opus\n"
            "---\n"
            "\n"
            "# Body\n"
            + ("filler line so the file clears the rich threshold.\n"
               * 100)
        )
        (agents_dir / f"{name}.md").write_text(body, encoding="utf-8")

    # Settings.json with 10 wired hooks (TP-40 added SubagentStop)
    settings = {
        "hooks": {
            "SessionStart": [{"hooks": [{"command": "x"}]}],
            "UserPromptSubmit": [{"hooks": [{"command": "x"}]}],
            "PreToolUse": [{
                "matcher": "*",
                "hooks": [{"command": "a"}, {"command": "b"}],
            }],
            "PostToolUse": [{
                "matcher": "*",
                "hooks": [{"command": "c"}, {"command": "d"}],
            }],
            "ConfigChange": [{"hooks": [{"command": "e"}]}],
            "Stop": [{"hooks": [{"command": "f"}]}],
            "SubagentStop": [{"hooks": [{"command": "h"}]}],
            "PostCompact": [{"hooks": [{"command": "g"}]}],
            "SubagentStart": [{"hooks": [{"command": "i"}]}],  # TP-163
            "PostToolUseFailure": [{  # TP-163
                "matcher": "Write|Edit|NotebookEdit",
                "hooks": [{"command": "j"}],
            }],
        }
    }
    (target / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8",
    )

    # tools/cc/hooks: 12 entry scripts + helpers (TP-40: +subagent_stop;
    # TP-163: +subagent_start +context_reinject_failure)
    hooks_dir = target / "tools" / "cc" / "hooks"
    hooks_dir.mkdir(parents=True)
    for name in (
        "session_start.py", "task_router.py", "write_guard.py",
        "plan_guard.py", "config_guard.py", "post_write_check.py",
        "reflect_trigger.py", "stop_gate.py", "subagent_stop.py",
        "post_compact.py", "subagent_start.py", "context_reinject_failure.py",
    ):
        (hooks_dir / name).write_text("", encoding="utf-8")
    for name in wheel_smoke.EXPECTED_HOOK_HELPERS:
        (hooks_dir / name).write_text("", encoding="utf-8")

    # install-ci surface
    workflow = target / ".github" / "workflows" / "harness-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: Harness Guard\n", encoding="utf-8")
    (target / "tools" / "cc" / "ci_guard.py").write_text("", encoding="utf-8")

    # cc/ surface
    cc_dir = target / "cc"
    cc_dir.mkdir()
    (cc_dir / "COMMANDS.md").write_text("# commands\n", encoding="utf-8")
    (cc_dir / "LIVE_SURFACE.md").write_text("# surface\n", encoding="utf-8")
    (cc_dir / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")

    # Integrity
    integ = target / ".espalier" / "integrity.json"
    integ.parent.mkdir(parents=True)
    integ.write_text("{}", encoding="utf-8")


class TestAssertSurfaceComplete:
    def test_complete_surface_passes(self, tmp_path):
        _make_complete_target(tmp_path)
        wheel_smoke.assert_surface(tmp_path)  # must not raise


def _real_init(target: Path, *extra: str, install_ci: bool = False) -> None:
    """Run the real ``espalier init`` (from this source checkout) into a fresh
    git repo at ``target``; optionally also ``install-ci`` (which assert_surface
    checks for via the harness-guard workflow + ci_guard.py)."""
    subprocess.check_call(["git", "init", "-q", str(target)])
    subprocess.check_call(
        [sys.executable, "-m", "espalier.cli", "init", str(target), *extra],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if install_ci:
        subprocess.check_call(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(target)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class TestRealInitFeedsAssertSurface:
    """TP-175 R1: run REAL ``espalier init`` and feed its deployed tree to
    ``assert_surface`` — the synthetic-tree fixtures above build exactly
    ``EXPECTED_*`` files, so they cannot catch a tier mismatch between what init
    deploys and what wheel_smoke asserts (the gap that left the wheel-smoke
    release gate structurally red)."""

    def test_default_init_satisfies_assert_surface(self, tmp_path):
        """A plain ``espalier init`` deploys the full packaged surface that
        ``assert_surface`` requires. The harness-dev deploy tier was retired,
        so every init deploys everything — there is no longer a tier mismatch
        between what init writes and what wheel_smoke asserts."""
        target = tmp_path / "repo"
        _real_init(target, install_ci=True)
        wheel_smoke.assert_surface(target)  # must not raise


class TestAssertSurfaceFailures:
    """Each missing class should raise SmokeFailure with an actionable hint."""

    def test_missing_commands(self, tmp_path):
        _make_complete_target(tmp_path)
        cmd_dir = tmp_path / ".claude" / "commands"
        next(cmd_dir.glob("*.md")).unlink()
        expected_pattern = rf"commands.*expected {wheel_smoke.EXPECTED_COMMAND_COUNT}"
        with pytest.raises(wheel_smoke.SmokeFailure, match=expected_pattern):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_skills(self, tmp_path):
        _make_complete_target(tmp_path)
        next((tmp_path / ".claude" / "skills").glob("*/SKILL.md")).unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match=f"skills.*expected {wheel_smoke.EXPECTED_SKILL_COUNT}"):
            wheel_smoke.assert_surface(tmp_path)

    # ── Removed by Round 3 wheel_smoke fix ────────────────────────────
    # ``test_missing_canonical_rich_agent`` and ``test_canonical_agent_is_stub``
    # pinned the CANONICAL_RICH_AGENTS enforcement block that was removed
    # post-TP-31. TP-31 (commit edd1c89) stripped the default agent
    # deployment (the roster has since been restored -- the assets tree
    # ships the rich agents again and step 3's floor is derived from it);
    # the hand-kept name list was a stale gate that turned
    # every release CI run red. The corresponding ``assert_surface``
    # block is gone — these tests asserted behavior that no longer
    # exists and were the only thing testing it, so deleting them is
    # the correct action (the floor-count check at step 3 of
    # ``assert_surface`` continues to gate "agents directory present at
    # all"; there's no remaining canonical-name enforcement to test).
    # See Round 3 audit and TP-31 (edd1c89) for the rationale.

    def test_settings_missing(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / ".claude" / "settings.json").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="settings.json missing"):
            wheel_smoke.assert_surface(tmp_path)

    def test_settings_bad_json(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / ".claude" / "settings.json").write_text("not json", encoding="utf-8")
        with pytest.raises(wheel_smoke.SmokeFailure, match="not valid JSON"):
            wheel_smoke.assert_surface(tmp_path)

    def test_wrong_hook_count(self, tmp_path):
        # TP-40: complete surface had 10 hooks; TP-163: 12 now.
        # Knocking one event (PostCompact) out yields 11.
        _make_complete_target(tmp_path)
        sp = tmp_path / ".claude" / "settings.json"
        settings = json.loads(sp.read_text(encoding="utf-8"))
        del settings["hooks"]["PostCompact"]
        sp.write_text(json.dumps(settings), encoding="utf-8")
        with pytest.raises(wheel_smoke.SmokeFailure, match="wires 11 hook commands"):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_hook_entry_script(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / "tools" / "cc" / "hooks" / "stop_gate.py").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="entry scripts"):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_hook_helper(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / "tools" / "cc" / "hooks" / "_integrity.py").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="helper module"):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_workflow(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / ".github" / "workflows" / "harness-guard.yml").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="harness-guard.yml missing"):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_ci_guard(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / "tools" / "cc" / "ci_guard.py").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="ci_guard.py missing"):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_cc_surface(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="PACK_MANIFEST.txt missing"):
            wheel_smoke.assert_surface(tmp_path)

    def test_missing_integrity_manifest(self, tmp_path):
        _make_complete_target(tmp_path)
        (tmp_path / ".espalier" / "integrity.json").unlink()
        with pytest.raises(wheel_smoke.SmokeFailure, match="integrity.json missing"):
            wheel_smoke.assert_surface(tmp_path)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


class TestArgParse:
    def test_defaults(self):
        ns = wheel_smoke.parse_args([])
        assert ns.wheel is None
        assert ns.skip_build is False
        assert ns.keep_temp is False
        assert ns.emit_json is False

    def test_skip_build_requires_wheel(self):
        ns = wheel_smoke.parse_args(["--skip-build"])
        # parse succeeds; the requirement is enforced inside run_smoke
        assert ns.skip_build is True

    def test_json_flag(self):
        ns = wheel_smoke.parse_args(["--json"])
        assert ns.emit_json is True


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


class TestSmokeReport:
    def test_status_pass_when_all_pass(self):
        r = wheel_smoke.SmokeReport()
        r.add(wheel_smoke.StepResult("a", "PASS"))
        r.add(wheel_smoke.StepResult("b", "PASS"))
        assert r.status == "PASS"

    def test_status_fail_when_any_fail(self):
        r = wheel_smoke.SmokeReport()
        r.add(wheel_smoke.StepResult("a", "PASS"))
        r.add(wheel_smoke.StepResult("b", "FAIL", "boom"))
        assert r.status == "FAIL"

    def test_to_dict_serializes_steps(self):
        r = wheel_smoke.SmokeReport(wheel_path="/tmp/w.whl", target="/tmp/t")
        r.add(wheel_smoke.StepResult("x", "PASS", "detail"))
        d = r.to_dict()
        assert d["status"] == "PASS"
        assert d["wheel_path"] == "/tmp/w.whl"
        assert d["steps"] == [{"name": "x", "status": "PASS", "detail": "detail"}]


class TestVersionParityAssertions:
    """TP-130 30-E: version-parity assertions across pyproject + CLI +
    __version__. Catches the silent-drift failure mode where a publish
    workflow uploads a wheel whose CLI / __version__ / pyproject disagree."""

    def test_read_pyproject_version_returns_string(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "0.8.0a1"\n', encoding="utf-8")
        assert wheel_smoke._read_pyproject_version(pyproject) == "0.8.0a1"

    def test_read_pyproject_version_raises_without_version(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with pytest.raises(wheel_smoke.SmokeFailure):
            wheel_smoke._read_pyproject_version(pyproject)

    def test_version_parity_raises_on_cli_mismatch(self, tmp_path, monkeypatch):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "0.8.0a1"\n', encoding="utf-8")
        # CLI returns a different version → mismatch.
        monkeypatch.setattr(
            wheel_smoke, "run_cli", lambda venv, *args: "espalier 9.9.9\n"
        )
        with pytest.raises(wheel_smoke.SmokeFailure) as exc:
            wheel_smoke.assert_version_parity(tmp_path / "venv", pyproject)
        assert "0.8.0a1" in str(exc.value)
        assert "9.9.9" in str(exc.value)

    def test_version_parity_raises_on_package_mismatch(
        self, tmp_path, monkeypatch
    ):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "0.8.0a1"\n', encoding="utf-8")
        # CLI agrees but __version__ disagrees.
        monkeypatch.setattr(
            wheel_smoke, "run_cli", lambda venv, *args: "espalier 0.8.0a1\n"
        )
        monkeypatch.setattr(
            wheel_smoke, "_venv_python", lambda venv: Path("/fake/python")
        )
        monkeypatch.setattr(
            wheel_smoke.subprocess,
            "check_output",
            # XPLAT-1: production pins encoding="utf-8"; DEF-821: a version
            # string is a structured answer, so the decode stays STRICT (no
            # errors=) under a handler naming ValueError. The mock takes exactly
            # the keywords production passes, so a keyword added or dropped
            # reds here rather than passing silently.
            lambda cmd, text, encoding: "0.7.0\n",
        )
        with pytest.raises(wheel_smoke.SmokeFailure) as exc:
            wheel_smoke.assert_version_parity(tmp_path / "venv", pyproject)
        assert "0.8.0a1" in str(exc.value)
        assert "0.7.0" in str(exc.value)

    def test_version_parity_passes_when_all_match(self, tmp_path, monkeypatch):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "0.8.0a1"\n', encoding="utf-8")
        monkeypatch.setattr(
            wheel_smoke, "run_cli", lambda venv, *args: "espalier 0.8.0a1\n"
        )
        monkeypatch.setattr(
            wheel_smoke, "_venv_python", lambda venv: Path("/fake/python")
        )
        monkeypatch.setattr(
            wheel_smoke.subprocess,
            "check_output",
            # XPLAT-1: production pins encoding="utf-8"; DEF-821: a version
            # string is a structured answer, so the decode stays STRICT (no
            # errors=) under a handler naming ValueError. The mock takes exactly
            # the keywords production passes, so a keyword added or dropped
            # reds here rather than passing silently.
            lambda cmd, text, encoding: "0.8.0a1\n",
        )
        assert wheel_smoke.assert_version_parity(
            tmp_path / "venv", pyproject
        ) == "0.8.0a1"


class TestBuildFailureCleanup:
    """TP-267 4-A: the build-failure path must not leak its scratch tempdir."""

    def test_run_smoke_cleans_scratch_dist_on_build_failure(self, monkeypatch):
        """When the wheel build raises CalledProcessError, run_smoke must remove
        the ``wheel-smoke-dist-*`` tempdir it created before re-raising
        SmokeFailure. RED before the fix: the dir leaks on every failed build.
        Asserts against the SPECIFIC path captured from mkdtemp, not a /tmp glob."""
        import argparse
        import subprocess
        import tempfile

        created: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def recording_mkdtemp(*a, **k):
            d = real_mkdtemp(*a, **k)
            created.append(Path(d))
            return d

        monkeypatch.setattr(wheel_smoke.tempfile, "mkdtemp", recording_mkdtemp)

        def boom(repo_root, dest_dir):
            raise subprocess.CalledProcessError(returncode=1, cmd=["python", "-m", "build"])

        monkeypatch.setattr(wheel_smoke, "build_wheel", boom)

        args = argparse.Namespace(wheel=None, skip_build=False, keep_temp=False, stack="none", spaced_root=False)
        with pytest.raises(wheel_smoke.SmokeFailure):
            wheel_smoke.run_smoke(args)

        dist_dirs = [d for d in created if d.name.startswith("wheel-smoke-dist-")]
        assert dist_dirs, "run_smoke did not create the expected scratch_dist tempdir"
        for d in dist_dirs:
            assert not d.exists(), f"scratch_dist leaked on build failure: {d}"


# ---------------------------------------------------------------------------
# _clear_stale_packaging_state: the stdlib twin of the engine helper
# ---------------------------------------------------------------------------


def _stale_packaging_tree(root: Path) -> None:
    """The shape the real build paths hit: both cached channels, a nested
    egg-info that must survive (only the top-level one is the package's own),
    a bystander file, a locked directory inside ``build/`` (on POSIX a
    directory without its write bit refuses every child's unlink; the engine
    helper unlocks it and retries, and the twin must too -- failure-mode
    review, TP-454 lane B), and a shut one (no bits at all: the walk cannot
    enter it, so each deleter gives it its owner bits back and walks it
    again, DEF-5062; on Windows the mode is the read-only attribute alone)."""
    (root / "build" / "lib").mkdir(parents=True)
    (root / "build" / "lib" / "x.py").write_text("x = 1\n", encoding="utf-8")
    locked = root / "build" / "lib" / "locked"
    locked.mkdir()
    (locked / "y.py").write_text("y = 1\n", encoding="utf-8")
    locked.chmod(0o500)
    shut = root / "build" / "lib" / "shut"
    (shut / "inner").mkdir(parents=True)
    (shut / "inner" / "z.py").write_text("z = 1\n", encoding="utf-8")
    shut.chmod(0o000)
    (root / "a.egg-info").mkdir()
    (root / "a.egg-info" / "SOURCES.txt").write_text("x.py\n", encoding="utf-8")
    (root / "pkg" / "b.egg-info").mkdir(parents=True)
    (root / "pkg" / "b.egg-info" / "SOURCES.txt").write_text("y.py\n", encoding="utf-8")
    (root / "keep.txt").write_text("keep\n", encoding="utf-8")


def _listing(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_clear_stale_packaging_state_parity_with_artifact_parity(tmp_path):
    """The twin cannot import the engine helper (the script is stdlib-only so it
    runs from a release-archive copy), so parity is DRIVEN: each runs on its
    own copy of one tree and both must remove the same paths and leave the
    same survivors. RED when either body loses the egg-info glob or the
    top-level bound."""
    twin_root, engine_root = tmp_path / "twin", tmp_path / "engine"
    for root in (twin_root, engine_root):
        root.mkdir()
        _stale_packaging_tree(root)
    twin_removed = [
        p.relative_to(twin_root).as_posix()
        for p in wheel_smoke._clear_stale_packaging_state(twin_root)
    ]
    engine_removed = [
        p.relative_to(engine_root).as_posix()
        for p in clear_stale_packaging_state(engine_root)
    ]
    assert twin_removed == engine_removed == ["build", "a.egg-info"]
    assert _listing(twin_root) == _listing(engine_root) == [
        "keep.txt", "pkg", "pkg/b.egg-info", "pkg/b.egg-info/SOURCES.txt",
    ]


@pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: a locked directory refuses the unlink; tests/test_rmtree.py holds the Windows link")
def test_neither_twin_lends_a_refused_links_target_the_write_bit(tmp_path):
    """DEF-5060 in both deleters, driven alike: a link inside a locked
    directory of ``build/`` names ``keep.txt``, which nothing was asked to
    delete. Each clears the directory (it is inside the tree), removes the
    link and the tree, and leaves ``keep.txt`` at 0o400. RED while either
    reads or sets the mode through the link."""
    modes = {}
    for name, clear in (("twin", wheel_smoke._clear_stale_packaging_state),
                        ("engine", clear_stale_packaging_state)):
        root = tmp_path / name
        locked_dir = root / "build" / "lib" / "locked"
        locked_dir.mkdir(parents=True)
        keep = root / "keep.txt"
        keep.write_text("keep\n", encoding="utf-8")
        os.chmod(keep, stat.S_IRUSR)
        (locked_dir / "link").symlink_to(keep)
        with locked(locked_dir, stat.S_IRUSR | stat.S_IXUSR):
            assert clear(root) == [root / "build"]
            assert not os.path.lexists(root / "build")
            locked_dir.mkdir(parents=True)  # for ``locked`` to restore onto
        modes[name] = stat.S_IMODE(os.stat(keep).st_mode)
    assert modes == {"twin": stat.S_IRUSR, "engine": stat.S_IRUSR}


@pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: a directory's write bit refuses its children's unlink")
@pytest.mark.parametrize("walk", ["fd", "scandir"])
def test_both_twins_remove_a_locked_build_holding_a_subdirectory(tmp_path, monkeypatch, walk):
    """DEF-3023 in both deleters, driven alike: ``build/`` at 0o500 holding
    ``lib/``. Its write bit refuses ``lib``'s ``rmdir``, and ``build`` is the
    tree's own root, which is part of the ask, so each gives it the bit and
    removes the tree; ``keep.txt`` stays. RED while the engine reads the root
    as outside the tree (a ``PermissionError`` on ``build/lib``). A root
    holding only files is no oracle from 3.12.4, whose fd walk hands the
    refused unlink back as a failure to enter the root, which the walk-again
    arm answers on every version."""
    from tests.test_rmtree import force_walk

    force_walk(walk, monkeypatch)
    for name, clear in (("twin", wheel_smoke._clear_stale_packaging_state),
                        ("engine", clear_stale_packaging_state)):
        root = tmp_path / name
        lib = root / "build" / "lib"
        lib.mkdir(parents=True)
        (lib / "x.py").write_text("x = 1\n", encoding="utf-8")
        (root / "keep.txt").write_text("keep\n", encoding="utf-8")
        with locked(root / "build", stat.S_IRUSR | stat.S_IXUSR):
            assert clear(root) == [root / "build"], name
            assert sorted(os.listdir(root)) == ["keep.txt"], name
            (root / "build").mkdir()  # for ``locked`` to restore onto


@pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: a directory's write bit refuses its children's unlink")
@pytest.mark.parametrize("walk", ["fd", "scandir"])
def test_both_twins_leave_a_locked_repository_root_and_report(tmp_path, monkeypatch, walk):
    """The tree's parent is not ours, in both deleters alike: with the
    repository root at 0o500 each empties ``build/`` (inside the ask), is
    refused the final ``rmdir`` and raises ``PermissionError``, and the root's
    bits are as set. RED while the twin reads that refusal's path as a str:
    ``rmtree`` hands the tree's own root back as the ``Path`` it was given
    (``AttributeError``, DEF-3023)."""
    from tests.test_rmtree import force_walk

    force_walk(walk, monkeypatch)
    for name, clear in (("twin", wheel_smoke._clear_stale_packaging_state),
                        ("engine", clear_stale_packaging_state)):
        root = tmp_path / name
        lib = root / "build" / "lib"
        lib.mkdir(parents=True)
        (lib / "x.py").write_text("x = 1\n", encoding="utf-8")
        with locked(root, stat.S_IRUSR | stat.S_IXUSR):
            with pytest.raises(PermissionError):
                clear(root)
            assert stat.S_IMODE(os.stat(root).st_mode) == stat.S_IRUSR | stat.S_IXUSR, name
            assert os.listdir(root / "build") == [], name


@pytest.mark.skipif(os.name != "nt", reason="the Windows arm: a directory's read-only attribute refuses its own removal")
def test_both_twins_remove_a_read_only_build_on_windows(tmp_path):
    """The twin's ``Path`` read on the host that runs the smoke by hand: a
    ``build/`` carrying the read-only attribute refuses its own final
    removal, ``rmtree`` hands that refusal back as the ``Path`` it was given,
    and each deleter clears the attribute on the root and removes it. RED
    while the twin reads the refused path as a str (``AttributeError``,
    DEF-3023)."""
    for name, clear in (("twin", wheel_smoke._clear_stale_packaging_state),
                        ("engine", clear_stale_packaging_state)):
        root = tmp_path / name
        lib = root / "build" / "lib"
        lib.mkdir(parents=True)
        (lib / "x.py").write_text("x = 1\n", encoding="utf-8")
        os.chmod(root / "build", stat.S_IREAD)
        try:
            assert clear(root) == [root / "build"], name
            assert sorted(os.listdir(root)) == [], name
        finally:
            if os.path.isdir(root / "build"):
                os.chmod(root / "build", stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.parametrize("no_follow,bare_is_the_links,link_calls,file_calls", [
    (True, False, [{"follow_symlinks": False}], [{"follow_symlinks": False}]),
    (False, True, [{}], [{}]),
    (False, False, [], [{}]),
], ids=["follow_symlinks_false", "windows_bare", "linux_link_left_alone"])
def test_both_twins_take_the_same_chmod_arm(tmp_path, monkeypatch, no_follow, bare_is_the_links,
                                            link_calls, file_calls):
    """The parity row above drives one arm, this host's; this one drives all
    three in both deleters through a fake ``os.chmod`` that records and
    changes nothing, so the twin cannot drop an arm the engine keeps (or the
    reverse) on a host that never takes it."""
    from espalier import _rmtree
    f = tmp_path / "f"
    f.write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(f)
    except OSError as exc:
        pytest.skip(f"this host cannot make a symlink: {exc}")
    seen = {}
    for name, module in (("twin", wheel_smoke), ("engine", _rmtree)):
        calls: list[tuple[str, dict]] = []
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: calls.append((str(p), k)))
        monkeypatch.setattr(module, "_CHMOD_NO_FOLLOW", no_follow)
        monkeypatch.setattr(module, "_BARE_CHMOD_IS_THE_LINKS", bare_is_the_links)
        module._add_write_bit(str(link))
        module._add_write_bit(str(f))
        seen[name] = (
            [k for p, k in calls if p == str(link)],
            [k for p, k in calls if p == str(f)],
        )
    assert seen == {"twin": (link_calls, file_calls), "engine": (link_calls, file_calls)}


@pytest.mark.parametrize("refusal", ["once", "always"])
@pytest.mark.parametrize("walk", ["fd", "scandir"])
def test_both_twins_walk_a_directory_they_could_not_enter_again(tmp_path, monkeypatch, walk, refusal):
    """DEF-5062 in both deleters, driven alike: the call that enters
    ``build/lib/shut`` refuses, as ``rmtree``'s ``os.open`` (the fd walk, on
    POSIX) or ``os.scandir`` (the walk Windows uses, on every host) refuses a
    directory with no read bit, a shape a Windows host cannot make with a
    mode. Refused ``once``, each gives the directory its owner bits back and
    walks it again, so the tree goes and the bystander stays: RED while the
    twin retries the refused call bare (``os.open`` without its flags raises
    ``TypeError``; a bare ``os.scandir`` of the fake lists nothing, so the
    directory's ``rmdir`` refuses it as not empty). Refused ``always`` (a
    directory whose bits are not ours to give back), each walks it again once
    and then raises the refusal: RED as a ``RecursionError`` while the twin
    walks again without remembering it already did."""
    from tests.test_rmtree import force_walk

    force_walk(walk, monkeypatch)
    enter = "open" if walk == "fd" else "scandir"
    real_enter = getattr(os, enter)
    outcome = {}
    for name, clear in (("twin", wheel_smoke._clear_stale_packaging_state),
                        ("engine", clear_stale_packaging_state)):
        root = tmp_path / name
        shut = root / "build" / "lib" / "shut"
        (shut / "inner").mkdir(parents=True)
        (shut / "b.py").write_text("b = 1\n", encoding="utf-8")
        (shut / "inner" / "c.py").write_text("c = 1\n", encoding="utf-8")
        (root / "keep.txt").write_text("keep\n", encoding="utf-8")
        refused: list[str] = []

        def refuse(path, *a, _refused=refused, **k):
            if (isinstance(path, (str, bytes, os.PathLike))
                    and (refusal == "always" or not _refused)
                    and os.path.basename(os.fsdecode(path)) == "shut"):
                _refused.append(os.fsdecode(path))
                raise PermissionError(errno.EACCES, "Permission denied", os.fsdecode(path))
            return real_enter(path, *a, **k)

        with monkeypatch.context() as m:
            m.setattr(os, enter, refuse)
            try:
                removed = [p.relative_to(root).as_posix() for p in clear(root)]
            except (OSError, TypeError, RecursionError) as exc:
                removed = [f"raised {type(exc).__name__}"]
        outcome[name] = (removed, len(refused), _listing(root))
    if refusal == "once":
        expected = (["build"], 1, ["keep.txt"])
    else:
        expected = (["raised PermissionError"], 2, [
            "build", "build/lib", "build/lib/shut", "build/lib/shut/b.py",
            "build/lib/shut/inner", "build/lib/shut/inner/c.py", "keep.txt",
        ])
    assert outcome == {"twin": expected, "engine": expected}


def test_build_wheel_clears_stale_state_before_the_builder(tmp_path, monkeypatch):
    """The twin's order row: RED with the call removed from ``build_wheel``."""
    calls: list[str] = []

    def recording_clear(repo_root):
        assert repo_root == tmp_path
        calls.append("clear")
        return []

    def recording_build(cmd, cwd=None):
        calls.append("build")
        (tmp_path / "dist").mkdir(exist_ok=True)
        (tmp_path / "dist" / "espalier_harness-0.0.0-py3-none-any.whl").write_bytes(b"")

    monkeypatch.setattr(wheel_smoke, "_clear_stale_packaging_state", recording_clear)
    monkeypatch.setattr(wheel_smoke.subprocess, "check_call", recording_build)
    wheel_smoke.build_wheel(tmp_path, tmp_path / "dist")
    assert calls == ["clear", "build"]


def test_kind_globs_pinned_to_the_owner():
    """wheel_smoke is stdlib-only and cannot import the kinds owner, so it holds
    its own per-kind glob table; this pins the two equal so a fifth kind added at
    the owner reds here instead of counting zero and passing vacuously."""
    from espalier import surface_contract
    assert wheel_smoke.KIND_GLOBS == surface_contract.CLAUDE_KIND_GLOBS


def test_the_local_hidden_name_twin_matches_the_engine_s(tmp_path):
    """wheel_smoke cannot import the engine, so it carries `_visible`, a twin of
    `espalier._safe_walk.visible`; the derived pin checks only that sites ROUTE
    through one of them, never that the two agree, so this row drives both over
    one planted tree (a body, a sidecar, a sidecar directory, a `.DS_Store`) and
    requires the same answer (§C28, the failure-mode review of 2026-10-06)."""
    from espalier._safe_walk import visible
    base = tmp_path / "skills"
    (base / "real").mkdir(parents=True)
    (base / "real" / "SKILL.md").write_text("real\n", encoding="utf-8")
    (base / "real" / "._SKILL.md").write_text("sidecar\n", encoding="utf-8")
    (base / "._real").mkdir()
    (base / "._real" / "SKILL.md").write_text("sidecar dir\n", encoding="utf-8")
    (base / ".DS_Store").write_bytes(b"\x00")
    assert wheel_smoke._visible(base.rglob("*"), base) == visible(base.rglob("*"), base)
    assert wheel_smoke._visible(base.rglob("*"), base) == [base / "real", base / "real" / "SKILL.md"]


class TestTheWorkDirsLock:
    """Both dirs the smoke makes (the built wheel's and the venv's) carry its
    pid lock while it runs, so a killed smoke's venv goes at the suite's next
    session start (``tests/_temp_sweep.py``); ``--keep-temp`` writes no lock,
    so a kept dir stays even when its run is killed."""

    def _drive(self, tmp_path, monkeypatch, keep_temp: bool) -> list:
        import argparse
        import tempfile

        from tests import _temp_sweep

        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        seen: list = []

        def build(repo_root, dest_dir):
            seen.append((dest_dir, _temp_sweep.lock_is_ours(dest_dir)))
            wheel = dest_dir / "espalier-0-py3-none-any.whl"
            wheel.write_bytes(b"")
            return wheel

        def install(wheel, venv_dir):
            seen.append((venv_dir.parent, _temp_sweep.lock_is_ours(venv_dir.parent)))
            raise wheel_smoke.SmokeFailure("stopped once the locks were read")

        monkeypatch.setattr(wheel_smoke, "build_wheel", build)
        monkeypatch.setattr(wheel_smoke, "install_wheel", install)
        with pytest.raises(wheel_smoke.SmokeFailure):
            wheel_smoke.run_smoke(argparse.Namespace(wheel=None, skip_build=False, keep_temp=keep_temp,
                                                     stack="none", spaced_root=False))
        return seen

    def test_both_dirs_are_locked_while_it_runs_and_go_after(self, tmp_path, monkeypatch):
        from tests import _temp_sweep

        seen = self._drive(tmp_path, monkeypatch, keep_temp=False)
        assert [ours for _d, ours in seen] == [True, True], "a dir the smoke made had no pid lock"
        assert all(d.name.startswith(_temp_sweep.OWNED_PREFIXES) and not d.exists() for d, _ours in seen)
        assert wheel_smoke.LOCK_NAME == _temp_sweep.LOCK_NAME

    def test_keep_temp_never_locks_so_a_killed_kept_run_keeps_both(self, tmp_path, monkeypatch):
        from tests import _temp_sweep

        seen = self._drive(tmp_path, monkeypatch, keep_temp=True)
        assert [ours for _d, ours in seen] == [False, False], "a --keep-temp run locked a dir it keeps"
        assert all(d.is_dir() and _temp_sweep.lock_pid(d) is None for d, _ours in seen), seen


class TestTheStackAndSpacedRootFlags:
    """TP-468 3-B: ``--stack`` writes the stack table's ``adopter-<stack>`` row
    into the target before its ``git init``, and ``--spaced-root`` puts the venv
    and the target under a directory whose name holds a space, the pid lock
    staying on the mkdtemp root the sweep reads. The default is today's run: an
    empty ``git init`` under the bare scratch, the table never read."""

    @staticmethod
    def _tree(root: Path) -> dict[str, str]:
        if not root.is_dir():
            return {}
        return {
            p.relative_to(root).as_posix(): p.read_bytes().decode("utf-8")
            for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts
        }

    @staticmethod
    def _args(tmp_path: Path, stack: str, spaced_root: bool):
        import argparse

        wheel = tmp_path / "espalier_harness-0-py3-none-any.whl"
        wheel.write_bytes(b"")
        return argparse.Namespace(wheel=str(wheel), skip_build=True, keep_temp=False,
                                  stack=stack, spaced_root=spaced_root)

    def _drive(self, tmp_path, monkeypatch, *, stack: str, spaced_root: bool) -> dict:
        import tempfile

        from tests import _temp_sweep

        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        seen: dict = {}
        real_git_init = wheel_smoke._git_init

        def git_init(target):
            seen["before_git_init"] = self._tree(target)
            real_git_init(target)

        def install(wheel, venv_dir):
            seen["venv"] = venv_dir
            venv_dir.mkdir(parents=True)

        def run_cli(venv_dir, *args, cwd=None):
            if args[:1] == ("init",):
                target = Path(args[1])
                seen["target"] = target
                seen["git_at_init"] = (target / ".git").is_dir()
                seen["locked"] = [d for d in target.parents
                                  if tmp_path in d.parents and _temp_sweep.lock_is_ours(d)]
            return "espalier 0.0.0\n"

        monkeypatch.setattr(wheel_smoke, "install_wheel", install)
        monkeypatch.setattr(wheel_smoke, "run_cli", run_cli)
        monkeypatch.setattr(wheel_smoke, "assert_version_parity", lambda venv_dir, pyproject: "0.0.0")
        monkeypatch.setattr(wheel_smoke, "assert_surface", lambda target: None)
        monkeypatch.setattr(wheel_smoke, "_git_init", git_init)
        seen["report"] = wheel_smoke.run_smoke(self._args(tmp_path, stack, spaced_root))
        return seen

    def test_the_flags_parse_and_every_stack_is_a_table_row(self):
        from tests import _stack_trees

        ns = wheel_smoke.parse_args([])
        assert (ns.stack, ns.spaced_root) == ("none", False)
        ns = wheel_smoke.parse_args(["--stack", "node", "--spaced-root"])
        assert (ns.stack, ns.spaced_root) == ("node", True)
        with pytest.raises(SystemExit):
            wheel_smoke.parse_args(["--stack", "cobol"])
        # The script reads the suite's own table, and each stack it offers is a
        # row there, so a renamed row reds here and not on the release matrix.
        assert wheel_smoke.STACK_TABLE == REPO_ROOT / "tests" / "_stack_trees.py"
        assert wheel_smoke.STACK_CHOICES == ("none", "python", "node", "go", "rust")
        offered = {f"{_stack_trees.ADOPTER_PREFIX}{s}" for s in wheel_smoke.STACK_CHOICES[1:]}
        assert offered <= set(_stack_trees.STACKS), offered - set(_stack_trees.STACKS)

    @pytest.mark.parametrize("stack", ["python", "node", "go", "rust"])
    def test_the_stack_row_is_written_under_a_spaced_root_before_git_init(self, tmp_path, monkeypatch, stack):
        from tests import _stack_trees

        seen = self._drive(tmp_path, monkeypatch, stack=stack, spaced_root=True)
        assert seen["before_git_init"] == _stack_trees.STACKS[f"adopter-{stack}"], (
            f"--stack {stack} did not write its adopter row before git init")
        assert seen["git_at_init"], "init ran on a target git never initialised"
        target, venv = seen["target"], seen["venv"]
        assert " " in target.parent.name and venv.parent == target.parent, (target, venv)
        # the lock is on the mkdtemp root, above the spaced dir, where the sweep reads
        assert seen["locked"] == [target.parent.parent], seen["locked"]
        assert not target.parent.parent.exists(), "the scratch outlived its run"
        assert seen["report"].status == "PASS"

    def test_the_default_is_an_empty_git_init_and_never_reads_the_table(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wheel_smoke, "STACK_TABLE", tmp_path / "absent" / "_stack_trees.py")
        seen = self._drive(tmp_path, monkeypatch, stack="none", spaced_root=False)
        assert seen["before_git_init"] == {} and seen["git_at_init"]
        assert seen["locked"] == [seen["target"].parent] and seen["venv"].parent == seen["target"].parent

    @pytest.mark.parametrize("planted", ["absent", "no_row"])
    def test_a_table_it_cannot_use_fails_before_the_install(self, tmp_path, monkeypatch, planted):
        """No silent fallback: an absent table (an archive without ``tests/``) or
        one without the row fails the run, naming the table, before the wheel
        is installed."""
        import tempfile

        table = tmp_path / "planted" / "_stack_trees.py"
        if planted == "no_row":
            table.parent.mkdir()
            table.write_text('ADOPTER_PREFIX = "adopter-"\nSTACKS = {"adopter-python": {}}\n'
                             "def write_stack(dest, row):\n    raise AssertionError(row)\n",
                             encoding="utf-8")
        monkeypatch.setattr(wheel_smoke, "STACK_TABLE", table)
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        installed: list = []
        monkeypatch.setattr(wheel_smoke, "install_wheel", lambda wheel, venv_dir: installed.append(venv_dir))
        with pytest.raises(wheel_smoke.SmokeFailure) as exc:
            wheel_smoke.run_smoke(self._args(tmp_path, "node", True))
        assert str(table) in str(exc.value) and "hint:" in str(exc.value), str(exc.value)
        assert not installed, "the wheel was installed before the table was read"
        assert not [d for d in tmp_path.iterdir() if d.name.startswith("wheel-smoke-")]
