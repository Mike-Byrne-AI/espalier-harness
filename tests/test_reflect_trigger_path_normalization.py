"""TP-39: ``reflect_trigger._normalize_path`` must apply the R12
W4/W5 contract — tilde expansion + ``$CLAUDE_PROJECT_DIR/`` prefix
strip — the same way ``write_guard``, ``plan_guard``, and
``post_write_check`` do.

Pins the path-normalization parity across all four hooks. R13's
"sister-site sweep" missed this site; the post-v0.6.5 multi-agent
audit surfaced the gap. Without this contract ``reflect_trigger``
could silently classify the same file under two different relative
paths depending on whether the operator's CWD matches
``$CLAUDE_PROJECT_DIR``, causing the every-10th-write counter to
double-count writes and fire the reflect protocol on a wrong
cadence. The failure mode is invisible at runtime — the cadence
just becomes wrong.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import reflect_trigger  # type: ignore  # noqa: E402


class TestReflectTriggerNormalizePath:
    def test_strips_claude_project_dir_brace_form(self, tmp_path):
        result = reflect_trigger._normalize_path(
            "${CLAUDE_PROJECT_DIR}/espalier/cli.py", tmp_path
        )
        assert result == "espalier/cli.py", (
            f"${{CLAUDE_PROJECT_DIR}}/ prefix not stripped — got {result!r}"
        )

    def test_strips_claude_project_dir_dollar_form(self, tmp_path):
        result = reflect_trigger._normalize_path(
            "$CLAUDE_PROJECT_DIR/espalier/cli.py", tmp_path
        )
        assert result == "espalier/cli.py", (
            f"$CLAUDE_PROJECT_DIR/ prefix not stripped — got {result!r}"
        )

    def test_expands_tilde(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # os.path.expanduser reads USERPROFILE on Windows, HOME on POSIX.
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        result = reflect_trigger._normalize_path("~/foo.py", tmp_path)
        # After tilde expansion, ~ becomes tmp_path; the relative form is "foo.py"
        # (root == tmp_path so resolve().relative_to(root) yields "foo.py").
        assert result == "foo.py", (
            f"~ not expanded — got {result!r}"
        )

    def test_relative_path_untouched(self, tmp_path):
        """Bare relative paths still pass through normalization."""
        result = reflect_trigger._normalize_path("espalier/cli.py", tmp_path)
        assert result == "espalier/cli.py"

    def test_falsy_path_does_not_crash(self, tmp_path):
        """Empty input does not raise — Path("") resolves to root, returns "."."""
        result = reflect_trigger._normalize_path("", tmp_path)
        # Path("") → Path(".") → resolves to root → relative_to(root) = "."
        # Behavior matches the sister-site helpers in write_guard/plan_guard.
        assert result == "."


class TestIsSourceFileRootContainment:
    """``_is_source_file`` must not count a write OUTSIDE the repo root.

    The every-10th-write reflect counter feeds ``stop_gate`` Gate 2, which
    blocks on "significant changes that may require doc updates". The predicate
    checked only the harness-excluded prefixes and the file extension -- never
    whether the path was inside the repo at all -- so an out-of-root ``.py``
    write incremented a counter meant to track *this project's* source churn.

    Observed three times independently. The sharpest instance: a session whose
    ``git status`` was byte-identical to its start, with ZERO tracked source
    files changed, was blocked by Gate 2 at ``write_count`` = 11. All 11 were
    out-of-root scratch ``.py`` writes.

    Scoped to root-containment ON PURPOSE, not to "tracked source". A true
    tracked-source predicate needs ``git check-ignore`` -- a subprocess per
    Write inside a PostToolUse hook that runs on every tool call -- plus a
    non-git-repo failure path. Measured, the residual it would additionally
    catch is empty: every in-root gitignored directory that could hold a ``.py``
    is a cache or build artifact written only by subprocesses, and the counter
    is structurally unreachable from Bash (only Write/Edit/NotebookEdit and MCP
    write verbs increment it). Reopen only if a real in-root gitignored ``.py``
    write is ever observed.
    """

    def test_out_of_root_source_file_is_not_counted(self, tmp_path):
        # THE earned red: True at HEAD, False after. This is the entire defect.
        assert reflect_trigger._is_source_file("/tmp/x.py", tmp_path) is False

    def test_absolute_path_inside_root_is_still_counted(self, tmp_path):
        # The orthogonal mutation: root-containment must not become a blanket
        # "reject absolute paths" rule, or a legitimately-absolute in-root write
        # stops counting and the counter under-fires instead of over-firing.
        inside = tmp_path / "pkg" / "mod.py"
        inside.parent.mkdir(parents=True)
        inside.write_text("x = 1\n", encoding="utf-8")
        assert reflect_trigger._is_source_file(str(inside), tmp_path) is True

    def test_relative_source_file_is_still_counted(self, tmp_path):
        assert reflect_trigger._is_source_file("pkg/mod.py", tmp_path) is True

    def test_parent_escape_is_not_counted(self, tmp_path):
        # `..` traversal reaches outside the root without being absolute.
        assert reflect_trigger._is_source_file("../outside/mod.py", tmp_path) is False

    def test_harness_excluded_prefix_still_wins(self, tmp_path):
        # Pre-existing behaviour must survive the new check.
        assert reflect_trigger._is_source_file("tests/test_x.py", tmp_path) is False

    def test_non_source_extension_still_not_counted(self, tmp_path):
        # `.md` was never a source extension -- the falsified half of the
        # original evidence. Pinned so the claim cannot be re-asserted.
        assert reflect_trigger._is_source_file("task-packs/TP-1.md", tmp_path) is False
