"""TP-107: per-mode unit tests for sister-site probe internal helpers.

Direct calls to ``_hash_body``, ``_opt_out_marker_above``,
``_is_one_line_call``, and ``_default_scan_targets``. Each helper is the
load-bearing primitive of a detection mode; this file pins their
externally-observable semantics so a refactor that subtly changes a
return shape (e.g., normalizing identifier renames out of the hash, or
letting decorators NOT break the opt-out walk) is caught at unit-test
granularity before the integration tests see it.

Without these, behavioral drift in a helper would only surface as a
silent regression in the synthetic harness or the live probe — harder
to localize.

Test naming follows ``test_{specific_behavior}`` per docs/CONVENTIONS.md.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PROBE_PATH = REPO_ROOT / "tools" / "cc"
sys.path.insert(0, str(PROBE_PATH))
from sister_site_probe import (  # noqa: E402
    CANONICAL_FILES,
    MODE_ADOPTER,
    MODE_SELF_HOST,
    _ENGINE_SIGNATURE,
    _FUSED_OVERLAY_DIRS,
    _FUSED_OVERLAY_FILES,
    _FUSED_OVERLAY_PATHS,
    _FUSION_MARKER_FILE,
    _MANAGED_MARKER_RE,
    _MANAGED_MARKER_SCAN_CHARS,
    _adopter_scan_targets,
    _hooks_are_deployed_copies,
    _default_scan_targets,
    _hash_body,
    _is_one_line_call,
    _opt_out_marker_above,
    _self_host_scan_targets,
    probe_mode,
)


def _fn(src: str) -> ast.FunctionDef:
    """Parse a top-level function and return the FunctionDef node itself.

    ``_is_one_line_call`` takes the node rather than the body: it must see the
    signature to refuse a callee that is one of the function's own parameters
    (``def _apply(fn, x): return fn(x)`` names no owner).
    """
    tree = ast.parse(src)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    return func


def _body(src: str) -> list[ast.stmt]:
    """Parse a top-level function and return its body."""
    tree = ast.parse(src)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    return func.body


@pytest.mark.security
class TestHashBody:
    def test_same_statements_same_hash(self):
        a = _hash_body(_body("def f():\n    return 42\n"))
        b = _hash_body(_body("def g():\n    return 42\n"))
        assert a == b

    def test_different_statements_different_hash(self):
        a = _hash_body(_body("def f():\n    return 42\n"))
        b = _hash_body(_body("def f():\n    return 43\n"))
        assert a != b

    def test_comment_only_diff_same_hash(self):
        a = _hash_body(_body("def f():\n    return 42\n"))
        b = _hash_body(_body("def f():\n    # explainer\n    return 42\n"))
        assert a == b

    def test_whitespace_only_diff_same_hash(self):
        a = _hash_body(_body("def f():\n    return 42\n"))
        b = _hash_body(_body("def f():\n\n\n    return 42\n"))
        assert a == b

    def test_identifier_rename_different_hash(self):
        a = _hash_body(_body("def f():\n    x = 1\n    return x\n"))
        b = _hash_body(_body("def f():\n    y = 1\n    return y\n"))
        assert a != b


@pytest.mark.security
class TestOptOutMarkerAbove:
    def test_marker_directly_above_def_returns_reason(self):
        lines = [
            "# sister-site: ok deliberate dup",
            "def f():",
            "    return 1",
        ]
        # func_lineno is 1-based; def is on line 2
        assert _opt_out_marker_above(lines, 2) == "deliberate dup"

    def test_blank_lines_between_marker_and_def_still_returns(self):
        lines = [
            "# sister-site: ok intentional",
            "",
            "",
            "def f():",
            "    return 1",
        ]
        # def on line 4 (1-based)
        assert _opt_out_marker_above(lines, 4) == "intentional"

    def test_decorator_between_marker_and_def_returns_none(self):
        lines = [
            "# sister-site: ok wrapped",
            "@some_decorator",
            "def f():",
            "    return 1",
        ]
        # def on line 3; line above (decorator) breaks the search
        assert _opt_out_marker_above(lines, 3) is None

    def test_marker_on_def_line_returns_none(self):
        lines = [
            "",
            "def f():  # sister-site: ok inline-marker",
            "    return 1",
        ]
        # Walker only inspects lines above; def line itself is never read.
        assert _opt_out_marker_above(lines, 2) is None


@pytest.mark.security
class TestIsOneLineCall:
    def test_return_call_no_args_true(self):
        assert _is_one_line_call(_fn("def f():\n    return target()\n"), "target") is True

    def test_return_call_with_args_true(self):
        assert _is_one_line_call(_fn("def f(a, b):\n    return target(a, b)\n"), "target") is True

    def test_multi_statement_body_false(self):
        assert _is_one_line_call(_fn("def f():\n    x = 1\n    return target(x)\n"), "target") is False

    def test_call_no_return_false(self):
        assert _is_one_line_call(_fn("def f():\n    target()\n"), "target") is False

    def test_return_name_not_call_false(self):
        assert _is_one_line_call(_fn("def f():\n    return target\n"), "target") is False

    def test_call_to_different_name_false(self):
        assert _is_one_line_call(_fn("def f():\n    return other()\n"), "target") is False

    def test_leading_docstring_does_not_hide_the_call(self):
        """A docstring is not logic — the body hash already ignores one."""
        src = 'def f(p):\n    """Doc."""\n    return target(p)\n'
        assert _is_one_line_call(_fn(src), "target") is True

    def test_expression_argument_false(self):
        """Logic inside the parentheses is still logic."""
        src = "def f(items):\n    return target({i.k: i.v for i in items})\n"
        assert _is_one_line_call(_fn(src), "target") is False

    def test_keyword_expression_argument_false(self):
        src = "def f(items):\n    return target(items, base=sum(items) or 1)\n"
        assert _is_one_line_call(_fn(src), "target") is False

    def test_starred_expression_argument_false(self):
        src = "def f(items):\n    return target(*build(items))\n"
        assert _is_one_line_call(_fn(src), "target") is False

    def test_constant_argument_true(self):
        src = 'def f(p):\n    return target(p, "utf-8", 3)\n'
        assert _is_one_line_call(_fn(src), "target") is True

    def test_callee_that_is_own_parameter_false(self):
        """``def _apply(fn, x): return fn(x)`` names no owner at all."""
        assert _is_one_line_call(_fn("def f(target, x):\n    return target(x)\n"), "target") is False


@pytest.mark.security
class TestDefaultScanTargets:
    def test_excludes_canonical_files(self, tmp_path):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (tmp_path / "espalier").mkdir()  # the engine package: self-host shape
        # Author one canonical (_hook_utils.py) + one ordinary hook
        (hooks / "_hook_utils.py").write_text("# canonical\n", encoding="utf-8")
        (hooks / "foo_hook.py").write_text("# regular\n", encoding="utf-8")

        targets = _default_scan_targets(tmp_path)
        rels = {p.relative_to(tmp_path).as_posix() for p in targets}
        assert "tools/cc/hooks/_hook_utils.py" not in rels
        assert "tools/cc/hooks/foo_hook.py" in rels

    def test_excludes_espalier_scanners_subdir(self, tmp_path):
        esp = tmp_path / "espalier"
        (esp / "scanners").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)  # self-host shape
        (esp / "top_module.py").write_text("# top\n", encoding="utf-8")
        (esp / "scanners" / "sub.py").write_text("# sub\n", encoding="utf-8")

        targets = _default_scan_targets(tmp_path)
        rels = {p.relative_to(tmp_path).as_posix() for p in targets}
        assert "espalier/top_module.py" in rels
        assert "espalier/scanners/sub.py" not in rels

    def test_includes_hooks_and_top_level_espalier(self, tmp_path):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "alpha.py").write_text("# alpha\n", encoding="utf-8")
        esp = tmp_path / "espalier"
        esp.mkdir()
        (esp / "beta.py").write_text("# beta\n", encoding="utf-8")

        targets = _default_scan_targets(tmp_path)
        rels = {p.relative_to(tmp_path).as_posix() for p in targets}
        assert "tools/cc/hooks/alpha.py" in rels
        assert "espalier/beta.py" in rels

    def test_canonical_files_membership(self):
        """``CANONICAL_FILES`` is the SoT for excluded canonical-defining paths.

        Pins the membership so a tightening pack (e.g. 107-K) that drops
        an entry is reflected in the unit-level expectation, not just
        integration tests.
        """
        assert "tools/cc/hooks/_hook_utils.py" in CANONICAL_FILES


_MARKER = "# espalier:managed v0.0.0 sha256:0000\n"


def _hooks(tmp_path: Path, *names: str, marked: bool) -> Path:
    hooks = tmp_path / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    for name in names:
        body = f"def {name}_fn():\n    return 1\n"
        (hooks / f"{name}.py").write_text(
            (_MARKER if marked else "") + body, encoding="utf-8",
        )
    return hooks


@pytest.mark.security
class TestProbeMode:
    """DEF-673: whose code is under scan is decided by the managed marker.

    ``espalier init`` writes every deployed ``.py`` with an anchored
    ``# espalier:managed`` line; the harness's own sources never carry one.
    So marked hooks mean "this is an adopter's tree and these files are
    Espalier's", and the probe's gating scope moves to the adopter's code.
    """

    def test_marker_regex_mirrors_managed_markers(self):
        """The inline mirror must not drift from the engine's recogniser --
        a marker the engine writes that the probe cannot read would leave an
        adopter in self-host mode, gated on debt they cannot edit."""
        from espalier import managed_markers

        assert _MANAGED_MARKER_RE.pattern == managed_markers._MARKER_LINE_RE.pattern
        assert _MANAGED_MARKER_RE.flags == managed_markers._MARKER_LINE_RE.flags
        assert _MANAGED_MARKER_SCAN_CHARS == managed_markers.MARKER_SCAN_BYTES

    @pytest.mark.parametrize("prefix,label", [
        ("", "plain"),
        ("#!/usr/bin/env python3\n", "shebang"),
        ("\ufeff", "BOM"),
        ("\u200b", "ZWSP (Cf)"),
        ("\x00", "NUL (Cc)"),
        ("\u200e", "LRM (Cf)"),
        ("\u2028", "LINE SEPARATOR (Zl)"),
        ("\u200b\ufeff\u200e", "stacked ignorables"),
        ("x", "a real character -- displaces the anchor"),
        ("# " + "x" * 70 + "\n", "a comment line first"),
        # Round-two code-reviewer input: a 20-codepoint ignorable prefix plus
        # filler that leaves the marker just inside the engine's 600-char
        # window AFTER stripping -- and just outside a window taken BEFORE.
        ("\u200b" * 20 + "x" * 569 + "\n", "prefix pushes the marker to the window edge"),
    ])
    def test_marker_prefix_normalisation_matches_the_engine(self, tmp_path, prefix, label):
        """Behavioural parity with ``managed_markers.has_managed_marker`` on the
        same bytes, not just regex equality: the first cut mirrored the regex
        and stripped only a BOM, so a ZWSP/NUL/LRM prefix read a MARKED hook
        as unmarked (failure-mode pass, 09-05). Direction matters: unmarked
        flips an adopter out of adopter mode."""
        from espalier.managed_markers import MARKER_HASH_COMMENT, has_managed_marker

        body = prefix + MARKER_HASH_COMMENT + "\nX = 1\n"
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "write_guard.py").write_text(body, encoding="utf-8")
        assert _hooks_are_deployed_copies(tmp_path) is has_managed_marker(body), label

    def test_frontmatter_widening_is_a_recorded_divergence(self, tmp_path):
        """The engine widens its window past a YAML frontmatter block; the
        probe does not mirror that, on purpose: the glob is ``*.py`` and
        ``---`` is not valid Python. Asserted so the comment's parity claim
        cannot be read wider than the mirror (failure-mode pass, round two)."""
        from espalier.managed_markers import MARKER_HASH_COMMENT, has_managed_marker

        body = "---\n" + "k: v\n" * 400 + "---\n" + MARKER_HASH_COMMENT + "\nX = 1\n"
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "write_guard.py").write_text(body, encoding="utf-8")
        assert has_managed_marker(body) is True
        assert _hooks_are_deployed_copies(tmp_path) is False

    def test_hooks_written_by_the_real_marker_helper_read_as_adopter(self, tmp_path):
        """Drive the exact bytes ``init`` produces, not a hand-typed marker."""
        from espalier.managed_markers import apply_marker_to_text

        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "write_guard.py").write_text(
            apply_marker_to_text("def main():\n    return 0\n"), encoding="utf-8",
        )
        assert probe_mode(tmp_path) == MODE_ADOPTER

    def test_marked_hooks_read_as_adopter(self, tmp_path):
        _hooks(tmp_path, "write_guard", marked=True)
        assert probe_mode(tmp_path) == MODE_ADOPTER

    def test_unmarked_hooks_beside_the_engine_read_as_self_host(self, tmp_path):
        """The source tree -- and every synthetic fixture in this suite."""
        _hooks(tmp_path, "write_guard", marked=False)
        (tmp_path / "espalier").mkdir()
        assert probe_mode(tmp_path) == MODE_SELF_HOST

    def test_unmarked_hooks_without_the_engine_read_as_adopter(self, tmp_path):
        """A pre-marker install, or hand-copied hooks: no engine package, so
        this is an adopter's tree and write_guard still keeps tools/cc/
        read-only for them. Reading it as self-host would reproduce DEF-673
        for exactly the adopter least able to fix it (code-reviewer, 09-05)."""
        _hooks(tmp_path, "write_guard", marked=False)
        assert probe_mode(tmp_path) == MODE_ADOPTER

    def test_engine_package_beside_a_hooks_tree_reads_as_self_host(self, tmp_path):
        (tmp_path / "espalier").mkdir()
        (tmp_path / "espalier" / "cli.py").write_text("X = 1\n", encoding="utf-8")
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        assert probe_mode(tmp_path) == MODE_SELF_HOST

    def test_vendored_engine_without_a_hooks_tree_reads_as_adopter(self, tmp_path):
        """An offline engine copy, or ``install-ci`` alone (it deploys no
        hook): reading this as self-host scanned 74 engine files as theirs
        and never their code (failure-mode pass, round two)."""
        for rel in _ENGINE_SIGNATURE:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("X = 1\n", encoding="utf-8")
        assert probe_mode(tmp_path) == MODE_ADOPTER

    def test_fusion_marker_wins_over_unmarked_hook_copies(self, tmp_path):
        """``fuse --no-init``: the overlay's hooks are unmarked byte copies,
        the engine package is present, and the tracked marker says whose
        tree this is."""
        _hooks(tmp_path, "write_guard", marked=False)
        (tmp_path / "espalier").mkdir()
        (tmp_path / _FUSION_MARKER_FILE).write_text("# fusion\n", encoding="utf-8")
        assert probe_mode(tmp_path) == MODE_ADOPTER

    def test_bare_tree_reads_as_adopter(self, tmp_path):
        """No harness in the tree at all: a pre-init adopter, or DEF-673's
        own scratch tree. Their code is the only code there is."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def f():\n    pass\n", encoding="utf-8")
        assert probe_mode(tmp_path) == MODE_ADOPTER

    def test_marker_wins_over_an_engine_copy(self, tmp_path):
        """The fused shape: ``espalier/`` is a vendored engine copy AND the
        hooks are marked. The engine copy is not the adopter's code -- and
        the CONSEQUENCE is asserted too, not just the mode: the copy is
        pruned from the gating scope."""
        _hooks(tmp_path, "write_guard", marked=True)
        for rel in _ENGINE_SIGNATURE:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("def f():\n    pass\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def g():\n    pass\n", encoding="utf-8")
        assert probe_mode(tmp_path) == MODE_ADOPTER
        files, _labels, pruned = _adopter_scan_targets(tmp_path, None)
        assert {p.relative_to(tmp_path).as_posix() for p in files} == {"src/app.py"}
        assert "espalier/ (vendored engine)" in pruned

    def test_marker_token_in_prose_is_not_a_marker(self, tmp_path):
        """The BC-026 forgery class: the token inside a docstring or a string
        literal is not an anchored comment line, so it cannot flip the mode."""
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (tmp_path / "espalier").mkdir()
        (hooks / "write_guard.py").write_text(
            '"""Files written by init carry espalier:managed on line one."""\n'
            'MARK = "espalier:managed"\n',
            encoding="utf-8",
        )
        assert probe_mode(tmp_path) == MODE_SELF_HOST

    def test_marker_past_the_scan_window_is_not_seen(self, tmp_path):
        """The mirror honours the engine's own window: a marker buried past
        MARKER_SCAN_BYTES is not what ``init`` writes and is not recognised."""
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (tmp_path / "espalier").mkdir()
        filler = "# " + "x" * 70 + "\n"
        (hooks / "write_guard.py").write_text(
            filler * 12 + _MARKER + "X = 1\n", encoding="utf-8",
        )
        assert probe_mode(tmp_path) == MODE_SELF_HOST

    def test_this_repo_is_self_host_and_its_targets_are_unchanged(self):
        """Self-host is the pre-DEF-673 behaviour, byte for byte."""
        assert probe_mode(REPO_ROOT) == MODE_SELF_HOST
        assert _default_scan_targets(REPO_ROOT) == _self_host_scan_targets(REPO_ROOT)


@pytest.mark.security
class TestAdopterScanTargets:
    """DEF-673: on an adopter tree the gating scope is THEIR source."""

    def _tree(self, tmp_path: Path) -> Path:
        _hooks(tmp_path, "write_guard", marked=True)
        for rel in (
            "src/pkg/a.py", "src/pkg/sub/b.py", "lib/c.py", "top.py",
            # pruned: junk, tests, dot-dirs, the harness's zones, egg-info
            ".venv/lib/x.py", "venv/y.py", "build/z.py", "dist/d.py",
            "node_modules/n.py", "__pycache__/p.py", "tests/t.py",
            "src/pkg/test/u.py", ".claude/hooks/h.py", ".espalier/e.py",
            "cc/blueprints/q.py", "pkg.egg-info/i.py", "_vendor/v.py",
            # case-insensitive names -- chosen so no lowercase twin exists in
            # this fixture (APFS/NTFS would fold `Tests/` into `tests/`) --
            # and a nested repo (dir .git + file .git)
            "Third_Party/tp.py", "Vendored/vd.py", "TEST/q.py",
            "subproject/lib/z.py", "wt/m.py",
        ):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("def f():\n    pass\n", encoding="utf-8")
        (tmp_path / "src" / "pkg" / "notes.txt").write_text("not python\n", encoding="utf-8")
        (tmp_path / "subproject" / ".git").mkdir()
        (tmp_path / "wt" / ".git").write_text("gitdir: ../.git/worktrees/wt\n", encoding="utf-8")
        return tmp_path

    def test_default_walk_finds_source_and_prunes_junk(self, tmp_path):
        tree = self._tree(tmp_path)
        rels = {p.relative_to(tree).as_posix() for p in _default_scan_targets(tree)}
        assert rels == {"src/pkg/a.py", "src/pkg/sub/b.py", "lib/c.py", "top.py"}

    def test_pruned_directories_are_named(self, tmp_path):
        """A clean exit must be readable: the walk says what it skipped."""
        tree = self._tree(tmp_path)
        _files, labels, pruned = _adopter_scan_targets(tree, None)
        assert labels == (".",)
        for expected in (
            ".venv/", "venv/", "build/", "dist/", "node_modules/", "tests/",
            "src/pkg/test/", ".claude/", ".espalier/", "cc/", "tools/cc/",
            "pkg.egg-info/", "_vendor/", "Third_Party/", "Vendored/", "TEST/",
            "subproject/ (nested repo)", "wt/ (nested repo)",
        ):
            assert expected in pruned, f"{expected} not reported as pruned: {pruned}"

    def test_roots_narrow_the_scope(self, tmp_path):
        tree = self._tree(tmp_path)
        rels = {
            p.relative_to(tree).as_posix()
            for p in _default_scan_targets(tree, (tree / "lib",))
        }
        assert rels == {"lib/c.py"}

    def test_a_pruned_directory_named_as_a_root_is_walked(self, tmp_path):
        """Pruning applies BELOW a start: ``--roots tests`` opts tests in."""
        tree = self._tree(tmp_path)
        rels = {
            p.relative_to(tree).as_posix()
            for p in _default_scan_targets(tree, (tree / "tests",))
        }
        assert rels == {"tests/t.py"}

    def test_a_file_root_is_scanned_by_itself(self, tmp_path):
        tree = self._tree(tmp_path)
        rels = {
            p.relative_to(tree).as_posix()
            for p in _default_scan_targets(tree, (tree / "top.py",))
        }
        assert rels == {"top.py"}

    def test_canonical_file_is_dropped_even_under_explicit_roots(self, tmp_path):
        """``--roots tools/cc/hooks`` on a self-host tree must keep
        ``_hook_utils.py`` out of clique detection -- it is the canon."""
        hooks = _hooks(tmp_path, "write_guard", marked=False)
        (tmp_path / "espalier").mkdir()
        (hooks / "_hook_utils.py").write_text("def canon():\n    return 1\n", encoding="utf-8")
        rels = {
            p.relative_to(tmp_path).as_posix()
            for p in _default_scan_targets(tmp_path, (hooks,))
        }
        assert rels == {"tools/cc/hooks/write_guard.py"}

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
    def test_walk_follows_neither_symlinked_dirs_nor_files(self, tmp_path):
        tree = tmp_path / "tree"
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "real.py").write_text("def f():\n    pass\n", encoding="utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "o.py").write_text("def g():\n    pass\n", encoding="utf-8")
        (tree / "src" / "linked_dir").symlink_to(outside, target_is_directory=True)
        (tree / "src" / "linked.py").symlink_to(outside / "o.py")
        rels = {p.relative_to(tree).as_posix() for p in _default_scan_targets(tree)}
        assert rels == {"src/real.py"}

    def test_harness_zone_is_pruned_by_identity_not_spelling(self, tmp_path):
        """A repo that already has ``Tools/`` on a case-insensitive filesystem:
        ``init`` lands the harness in ``Tools/cc/``, the walk meets the
        capitalised spelling, and a literal compare against ``tools/cc``
        missed the zone -- 38 of 39 gating files were Espalier's, the exact
        DEF-673 harm (failure-mode pass, round two). Identity, not spelling.
        On a case-sensitive filesystem the two are separate directories and
        the adopter's ``Tools/`` is simply scanned."""
        (tmp_path / "Tools").mkdir()
        (tmp_path / "Tools" / "buildhelper.py").write_text("def h():\n    pass\n", encoding="utf-8")
        _hooks(tmp_path, "write_guard", "plan_guard", marked=True)  # lands in Tools/cc on APFS
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def g():\n    pass\n", encoding="utf-8")
        files, _labels, pruned = _adopter_scan_targets(tmp_path, None)
        rels = {p.relative_to(tmp_path).as_posix() for p in files}
        assert "src/app.py" in rels
        assert "Tools/buildhelper.py" in rels
        assert not any("cc/hooks/" in r for r in rels), rels
        assert any(label.lower().startswith("tools/cc/") for label in pruned), pruned

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
    def test_a_dangling_git_symlink_still_marks_a_nested_repo(self, tmp_path):
        """A worktree removed from disk leaves ``.git`` as a dangling symlink;
        ``exists()`` follows it and says False, so the foreign checkout
        entered the gating scope (failure-mode pass, round two)."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "ok.py").write_text("def f():\n    pass\n", encoding="utf-8")
        gone = tmp_path / "symsub"
        gone.mkdir()
        (gone / "n.py").write_text("def f():\n    pass\n", encoding="utf-8")
        (gone / ".git").symlink_to(tmp_path / "no-such-admin-dir")
        files, _labels, pruned = _adopter_scan_targets(tmp_path, None)
        assert {p.relative_to(tmp_path).as_posix() for p in files} == {"src/ok.py"}
        assert "symsub/ (nested repo)" in pruned

    def test_ledger_probe_shape_sees_the_adopters_source(self, tmp_path):
        """DEF-673's own probe, verbatim: a tree holding only ``src/app.py``
        yielded ZERO targets before the fix."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def f():\n    pass\n", encoding="utf-8")
        assert len(_default_scan_targets(tmp_path)) == 1



def _live_tools_py() -> set[str]:
    """Every .py under the whole-tree ``tools/`` manifest entry except the
    deploy zone ``tools/cc/`` (pruned on every adopter tree already)."""
    return {
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "tools").rglob("*.py")
        if not p.relative_to(REPO_ROOT).as_posix().startswith("tools/cc/")
        and "__pycache__" not in p.parts
    }


@pytest.mark.security
class TestFusedOverlay:
    """DEF-673, failure-mode pass: on a fused tree the harness OVERLAY is
    Espalier's, not the adopter's source -- and it is pruned at the
    manifest's own granularity, so the host's neighbours under ``bench/`` and
    ``tools/`` stay in scope. Driven before the prune existed: 97 of the 98
    files the walk called "your source" were Espalier's and three of them
    gated; driven after the first cut: a wholesale ``bench/`` prune hid two of
    the host's own cliques under a label calling them Espalier's."""

    def _fused(self, tmp_path: Path) -> Path:
        (tmp_path / _FUSION_MARKER_FILE).write_text("# fusion\n", encoding="utf-8")
        _hooks(tmp_path, "write_guard", marked=True)
        for rel in (
            # the overlay
            "tools/__init__.py", "tools/review_agent_audit.py", "espalier/cli.py",
            "espalier/managed_markers.py", "espalier/scanners/prints.py",
            "bench/run_benchmark.py", "bench/end_to_end/verify.py",
            "bench/corpus/gen.py", "bench/baselines/mk.py",
            "scripts/check_exception_policy.py",
            "scripts/check_memory_md_tag_parity.py",
            # the host's own, beside the overlay
            "tools/host_tool.py", "bench/host_bench.py", "scripts/mine.py", "src/app.py",
        ):
            q = tmp_path / rel
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text("def f():\n    pass\n", encoding="utf-8")
        return tmp_path

    def test_fusion_marker_prunes_the_overlay_and_only_the_overlay(self, tmp_path):
        tree = self._fused(tmp_path)
        files, _labels, pruned = _adopter_scan_targets(tree, None)
        rels = {p.relative_to(tree).as_posix() for p in files}
        assert rels == {"tools/host_tool.py", "bench/host_bench.py", "scripts/mine.py", "src/app.py"}
        for expected in (
            "espalier/ (fused harness overlay)",
            "bench/end_to_end/ (fused harness overlay)",
            "bench/corpus/ (fused harness overlay)",
            "bench/baselines/ (fused harness overlay)",
            "bench/run_benchmark.py (fused harness overlay)",
            "tools/__init__.py (fused harness overlay)",
            "tools/review_agent_audit.py (fused harness overlay)",
            "scripts/check_exception_policy.py (fused harness overlay)",
            "scripts/check_memory_md_tag_parity.py (fused harness overlay)",
            "tools/cc/",
        ):
            assert expected in pruned, f"{expected} missing from {pruned}"
        assert not any(label.startswith("bench/ ") or label.startswith("tools/ ") for label in pruned), (
            f"a wholesale bench/ or tools/ prune hides the host's own files: {pruned}"
        )

    def test_vendored_engine_is_pruned_without_the_marker(self, tmp_path):
        """A hand-vendored engine copy carries the signature and no marker."""
        tree = self._fused(tmp_path)
        (tree / _FUSION_MARKER_FILE).unlink()
        files, _labels, pruned = _adopter_scan_targets(tree, None)
        rels = {p.relative_to(tree).as_posix() for p in files}
        assert "espalier/cli.py" not in rels and "espalier/scanners/prints.py" not in rels
        assert "espalier/ (vendored engine)" in pruned
        # Without the marker the rest of the overlay is indistinguishable from
        # the adopter's own files, and is scanned -- said here so the limit is
        # a recorded choice, not a surprise.
        assert "tools/review_agent_audit.py" in rels

    def test_overlay_mirror_matches_fusion_manifest(self):
        """Derived, not hand-listed twice, in BOTH directions and at the
        manifest's granularity: every .py-bearing HARNESS_INCLUDE entry is
        pruned on a fused tree, and every prune entry is something the
        manifest really overlays -- a prune wider than its manifest entry
        (a wholesale ``bench/``) would hide the host's own files, and the
        first cut of this test collapsed entries to their top directory and
        could not see that."""
        from espalier.fusion_manifest import HARNESS_INCLUDE

        # A floor, so a shrunken signature (one module) cannot pass as a
        # weaker but still-green check -- the census's §18.4 shape.
        assert len(_ENGINE_SIGNATURE) >= 2
        for rel in _ENGINE_SIGNATURE:
            assert (REPO_ROOT / rel).is_file(), f"engine signature file gone: {rel}"

        pruned_dirs = {d + "/" for d in _FUSED_OVERLAY_DIRS}
        pruned_paths = {p + "/" for p in _FUSED_OVERLAY_PATHS}
        uncovered: list[str] = []
        for entry in HARNESS_INCLUDE:
            if entry.startswith("."):
                continue  # dot-directories are pruned by name everywhere
            if entry.endswith(".py"):
                if entry not in _FUSED_OVERLAY_FILES and not any(
                    entry.startswith(d) for d in pruned_dirs | pruned_paths
                ):
                    uncovered.append(entry)
                continue
            if not entry.endswith("/") or not any((REPO_ROOT / entry).rglob("*.py")):
                continue
            if entry in pruned_dirs or entry in pruned_paths:
                continue
            if entry == "tools/":
                # Whole-tree entry the host may share: tools/cc is a deploy-zone
                # prune, and every other live .py under it -- at ANY depth; a
                # non-recursive glob let a new tools/analysis/foo.py into the
                # host's gating scope with this test green (third failure-mode
                # pass) -- must be a file or path prune.
                uncovered.extend(sorted(_live_tools_py() - _FUSED_OVERLAY_FILES - {
                    f for f in _live_tools_py()
                    if any(f.startswith(p + "/") for p in _FUSED_OVERLAY_PATHS)
                }))
                continue
            uncovered.append(entry)
        assert not uncovered, (
            f"HARNESS_INCLUDE entries that carry .py but are not pruned on a fused "
            f"tree: {uncovered}. Extend _FUSED_OVERLAY_DIRS / _FUSED_OVERLAY_PATHS / "
            f"_FUSED_OVERLAY_FILES."
        )
        # Reverse: every prune entry is exactly a manifest entry (or a live
        # tools/*.py under the whole-tree `tools/` entry) -- never wider.
        manifest = set(HARNESS_INCLUDE)
        live_tools = _live_tools_py()
        stale = sorted(
            [d for d in pruned_dirs | pruned_paths if d not in manifest]
            + [f for f in _FUSED_OVERLAY_FILES if f not in manifest and f not in live_tools]
        )
        assert not stale, (
            f"prune entries the manifest does not overlay at that granularity: {stale}"
        )
