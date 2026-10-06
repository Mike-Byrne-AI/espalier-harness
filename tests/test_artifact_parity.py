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
import fnmatch
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


# ---------------------------------------------------------------------------
# DEF-1138: a build stages a copy of the tree and never writes the root
# ---------------------------------------------------------------------------


def _root_snapshot(root: Path) -> dict[Path, tuple[bytes, int]]:
    """Every file under ``root`` with its bytes and its mtime: a build that
    rewrote a file with the same bytes, or only touched it, still differs
    (the code review's mutation: an ``os.utime`` between the build and the
    second read passed a bytes-only snapshot)."""
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


class TestBuildsStageACopyAndNeverWriteTheRoot:
    """The suite's builds used to run in the live tree: ``build_wheel`` cleared
    the root's ``build/`` and ``*.egg-info`` and built there, and setuptools
    staged the sdist's release tree under the root for the length of the
    build, so a tree-walking test on another xdist worker could see either
    (``DEF-1138``: a red required cell on a pull request whose diff never
    touched the file named). Now the builder copies the working tree into a
    per-call temp root with the never-shipped names left out and builds
    there: the root is read, never written. The litter pin reds against the
    old builder three times over -- the recorded cwd was the root, the root's
    ``build/`` and ``*.egg-info`` were gone afterwards, and the "copy" (the
    root) was still there."""

    #: what a working tree carries that no build may read into the artifact
    #: or touch on the way: a stale build tree, an old dist, a cached
    #: manifest, the git store, a bytecode cache; and, by path, the session
    #: state a live session rotates while the copy runs
    _LITTER = ("build", "dist", "a.egg-info", ".git", "pkg/__pycache__")

    @staticmethod
    def _tree(root: Path) -> dict[Path, tuple[bytes, int]]:
        (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg" / "__pycache__").mkdir()
        (root / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"\x00")
        (root / "build" / "lib").mkdir(parents=True)
        (root / "build" / "lib" / "stale.py").write_text("stale = 1\n", encoding="utf-8")
        (root / "a.egg-info").mkdir()
        (root / "a.egg-info" / "SOURCES.txt").write_text("stale.py\n", encoding="utf-8")
        (root / "dist").mkdir()
        (root / "dist" / "old.whl").write_bytes(b"old")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (root / "cc" / "blueprints").mkdir(parents=True)
        (root / "cc" / "blueprints" / "node.json").write_text("{}\n", encoding="utf-8")
        (root / "cc" / "COMMANDS.md").write_text("# c\n", encoding="utf-8")
        return _root_snapshot(root)

    @staticmethod
    def _recording_builder(seen: dict, artifact: str):
        """Stand in for ``python -m build``: record the cwd and what it holds,
        then drop one artifact where ``--outdir`` points."""
        def build(cmd, cwd=None):
            cwd_path = Path(cwd)
            seen["cmd"] = list(cmd)
            seen["cwd"] = cwd_path
            seen["entries"] = sorted(
                p.relative_to(cwd_path).as_posix() for p in cwd_path.rglob("*")
            )
            out = Path(cmd[cmd.index("--outdir") + 1])
            seen["outdir"] = out
            out.mkdir(parents=True, exist_ok=True)
            (out / artifact).write_bytes(b"")
        return build

    def test_build_wheel_runs_in_a_copy_with_the_payload_and_none_of_the_litter(
        self, tmp_path, monkeypatch,
    ):
        from espalier import artifact_parity
        root = tmp_path / "root"
        root.mkdir()
        before = self._tree(root)
        seen: dict = {}
        monkeypatch.setattr(
            artifact_parity.subprocess, "check_call",
            self._recording_builder(seen, "espalier_harness-0.0.0-py3-none-any.whl"),
        )
        wheel = build_wheel(root, tmp_path / "out")
        cwd = seen["cwd"]
        assert cwd.resolve() != root.resolve() and root.resolve() not in cwd.resolve().parents, cwd
        assert "pyproject.toml" in seen["entries"] and "pkg/__init__.py" in seen["entries"]
        litter = [e for e in seen["entries"] if e.startswith(self._LITTER)]
        assert litter == [], litter
        assert "cc/COMMANDS.md" in seen["entries"] and not any(
            e.startswith("cc/blueprints") for e in seen["entries"]
        ), "the churning session state rode into the copy"
        after = _root_snapshot(root)
        assert after == before, "the build wrote the root"
        assert not cwd.exists(), "the staged copy outlived the build"
        assert "--wheel" in seen["cmd"] and wheel.name.endswith(".whl")

    def test_build_sdist_asks_for_an_sdist_and_finds_the_tarball(self, tmp_path, monkeypatch):
        from espalier import artifact_parity
        from espalier.artifact_parity import build_sdist
        root = tmp_path / "root"
        root.mkdir()
        before = self._tree(root)
        seen: dict = {}
        monkeypatch.setattr(
            artifact_parity.subprocess, "check_call",
            self._recording_builder(seen, "espalier_harness-0.0.0.tar.gz"),
        )
        sdist = build_sdist(root, tmp_path / "out")
        assert "--sdist" in seen["cmd"] and "--wheel" not in seen["cmd"]
        assert sdist.name == "espalier_harness-0.0.0.tar.gz"
        assert seen["cwd"].resolve() != root.resolve() and not seen["cwd"].exists()
        assert _root_snapshot(root) == before

    def test_a_relative_output_directory_resolves_against_the_caller_not_the_copy(
        self, tmp_path, monkeypatch,
    ):
        """Red against the old builder too: it passed ``--outdir rel-out`` as
        typed, and a build in the root put the wheel under the root."""
        from espalier import artifact_parity
        root = tmp_path / "root"
        root.mkdir()
        self._tree(root)
        seen: dict = {}
        monkeypatch.setattr(
            artifact_parity.subprocess, "check_call",
            self._recording_builder(seen, "espalier_harness-0.0.0-py3-none-any.whl"),
        )
        monkeypatch.chdir(tmp_path)
        wheel = build_wheel(root, Path("rel-out"))
        assert seen["outdir"].is_absolute(), seen["outdir"]
        assert seen["outdir"].resolve() == (tmp_path / "rel-out").resolve()
        assert wheel.resolve().parent == (tmp_path / "rel-out").resolve()

    def test_the_copy_is_removed_and_the_root_untouched_when_the_build_fails(
        self, tmp_path, monkeypatch,
    ):
        from espalier import artifact_parity
        root = tmp_path / "root"
        root.mkdir()
        before = self._tree(root)
        seen: dict = {}

        def failing_build(cmd, cwd=None):
            seen["cwd"] = Path(cwd)
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(artifact_parity.subprocess, "check_call", failing_build)
        with pytest.raises(subprocess.CalledProcessError):
            build_wheel(root, tmp_path / "out")
        assert not seen["cwd"].exists(), "the staged copy outlived the failed build"
        assert _root_snapshot(root) == before


class TestTheSkipSetDropsOnlyWhatNoArtifactShips:
    """``BUILD_TREE_SKIP_NAMES`` is a hand-kept list, so it is pinned to the
    two files that decide what a build may read: every name is pruned or
    globally excluded by ``MANIFEST.in`` or kept out of a fresh clone by a
    ``.gitignore`` directory rule, and no tracked path carries one (a tracked
    ``build/`` somewhere would vanish from the copy, and so from the sdist
    built in it). The list may shrink or grow; it may not name something an
    artifact ships."""

    @staticmethod
    def _manifest_tokens() -> set[str]:
        """The basenames ``prune`` and ``global-exclude`` rules name."""
        tokens: set[str] = set()
        for raw in (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
            parts = raw.split("#", 1)[0].split()
            if len(parts) >= 2 and parts[0] in {"prune", "global-exclude"}:
                tokens.update(t.rsplit("/", 1)[-1] for t in parts[1:])
        return tokens

    @staticmethod
    def _gitignore_directory_patterns() -> list[str]:
        """The rules that end in a slash: a directory, at any depth unless
        anchored, and anchoring does not matter to a name match."""
        patterns: list[str] = []
        for raw in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.endswith("/") and not line.startswith("!"):
                patterns.append(line.strip("/"))
        return patterns

    def test_every_skip_name_is_pruned_excluded_or_ignored(self):
        from espalier.artifact_parity import BUILD_TREE_SKIP_NAMES, BUILD_TREE_SKIP_SUFFIX
        rules = self._manifest_tokens() | set(self._gitignore_directory_patterns())

        def covered(name: str) -> bool:
            return any(fnmatch.fnmatchcase(name, rule) for rule in rules)

        uncovered = sorted(n for n in BUILD_TREE_SKIP_NAMES if not covered(n))
        assert uncovered == [], uncovered
        assert covered("x" + BUILD_TREE_SKIP_SUFFIX)

    def test_every_skip_path_is_a_prune_rule_and_an_ignore_rule(self):
        """A whole-subtree skip is matched exactly, so it is pinned exactly:
        ``prune <path>`` in ``MANIFEST.in`` and ``<path>/`` in ``.gitignore``,
        both verbatim (a churning directory the sdist shipped would be a
        different problem, and one the copy must not hide)."""
        from espalier.artifact_parity import BUILD_TREE_SKIP_PATHS
        manifest = {
            line.split("#", 1)[0].strip()
            for line in (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        }
        gitignore = {
            line.split("#", 1)[0].strip()
            for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        }
        unpinned = sorted(
            path for path in BUILD_TREE_SKIP_PATHS
            if f"prune {path}" not in manifest or f"{path}/" not in gitignore
        )
        assert unpinned == [], unpinned
        assert all("/" in path and not path.endswith("/") for path in BUILD_TREE_SKIP_PATHS)

    def test_no_tracked_path_carries_a_skip_name_or_lies_under_a_skip_path(self):
        from espalier.artifact_parity import (
            BUILD_TREE_SKIP_NAMES, BUILD_TREE_SKIP_PATHS, BUILD_TREE_SKIP_SUFFIX,
        )
        from tests._git_oracle import require_tracked_paths  # never a silently empty set
        tracked = require_tracked_paths(REPO_ROOT, minimum=500, what="the whole tracked tree")
        hits = sorted(
            path for path in tracked if any(
                part in BUILD_TREE_SKIP_NAMES or part.endswith(BUILD_TREE_SKIP_SUFFIX)
                for part in path.split("/")[:-1]
            ) or any(path.startswith(f"{skip}/") for skip in BUILD_TREE_SKIP_PATHS)
        )
        assert hits == [], hits[:10]

    def test_the_git_store_and_both_build_channels_are_in_the_set(self):
        """Without these three the copy is the whole clone and the build in it
        starts from the last build's leftovers: the two reasons to copy."""
        from espalier.artifact_parity import BUILD_TREE_SKIP_NAMES
        assert {".git", "build", "dist"} <= BUILD_TREE_SKIP_NAMES
