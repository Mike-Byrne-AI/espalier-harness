# pytest-marker: default-unit
"""Contract for ``scripts/check_pack_fences.py``.

The checker resolves a pack's PRESCRIBED python fences against the module they
land in. Every assertion here was written against a behaviour the checker got
wrong first -- the dedent, the nesting, and the do-not-blame-the-pack rule each
have a measured failure behind them, recorded in the test that pins it.
"""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load():
    path = REPO / "scripts" / "check_pack_fences.py"
    spec = importlib.util.spec_from_file_location("check_pack_fences", path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load()


def _pack(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "TP-999-fixture.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


class TestPrescribedFenceResolution:
    def test_flags_a_name_the_target_module_never_binds(self, tmp_path):
        """The shape this checker exists for.

        A pack prescribed ``sqlite3.connect`` for ``espalier/cli.py``, which does not
        import ``os`` -- it appears there once, inside a comment, so a grep would
        have said yes. A NameError plus ruff F821 that nothing else catches.
        """
        pack = _pack(tmp_path, """
            Fix 1 — add the helper:

            ```python target=espalier/cli.py
            def _stripped_path() -> str:
                return sqlite3.connect(":memory:")
            ```
            """)
        findings, cov = C.check_pack(pack)
        assert cov["checked"] == 1
        assert any("'sqlite3' is not bound anywhere in espalier/cli.py" in f
                   for f in findings), findings

    def test_quiet_when_the_name_is_bound_only_inside_a_function(self, tmp_path):
        """The false positive a module-level-only scan would produce.

        ``espalier/cli.py`` imports ``subprocess`` inside two functions and
        nowhere at module level. A prescribed fragment destined for one of those
        functions legitimately reads it, so the namespace test is deliberately
        "bound anywhere", not "bound at module level".
        """
        pack = _pack(tmp_path, """
            ```python target=espalier/cli.py
            probe = subprocess.run(["x"], capture_output=True)
            ```
            """)
        findings, cov = C.check_pack(pack)
        assert cov["checked"] == 1
        assert not findings, findings

    def test_indented_fragment_is_parsed_after_dedent(self, tmp_path):
        """A prescribed fence is usually lifted from inside a function, so it
        carries that function's indent. Before the dedent, ``ast.parse`` rejected
        it at line 1 and the fence was written off as an unparseable fragment --
        the checker declining to look at the only thing it was built for."""
        pack = _pack(tmp_path, """
            ```python target=espalier/cli.py
                conn = sqlite3.connect(":memory:")
                return conn
            ```
            """)
        findings, cov = C.check_pack(pack)
        assert cov["unparseable"] == 0
        assert cov["checked"] == 1
        assert any("'sqlite3'" in f for f in findings), findings

    def test_nested_markdown_fence_is_not_truncated(self, tmp_path):
        """The documented example form wraps ```python inside ````markdown. A
        closer matched on any run of three would end the outer fence at the inner
        one and silently truncate the example."""
        pack = _pack(tmp_path, """
            ````markdown
            **Fix 3 — the prescribed change:**

            ```python target=espalier/cli.py
            value = sqlite3.connect(":memory:")
            ```
            ````
            """)
        findings, cov = C.check_pack(pack)
        assert cov["total"] == 1, cov
        assert cov["checked"] == 1, cov
        assert any("'sqlite3'" in f for f in findings), findings


class TestNamespaceApproximation:
    def test_match_case_captures_are_bound_not_free(self):
        """Structural pattern matching binds outside the Name/Store walk.

        A bare capture, a star pattern and a mapping rest all bind a name without
        producing a Store Name node. Before this, a fence using `match` reported
        its OWN captures as unbound in the target -- a false BLOCK, and a false
        BLOCK is the one failure a gate like this cannot afford: it is how the
        gate gets suppressed.
        """
        import ast
        cases = [
            ("match p:\n case [a, b]:\n  print(a, b)", {"a", "b"}),
            ("match p:\n case {'k': a, **rest}:\n  print(a, rest)", {"a", "rest"}),
            ("match p:\n case Point(x=x):\n  print(x)", {"x"}),
        ]
        for src, captured in cases:
            free = C.free_names(ast.parse(src))
            assert not (captured & free), (
                f"capture(s) {sorted(captured & free)} read as FREE in: {src!r}"
            )

    def test_skip_filter_matches_path_segments_not_substrings(self):
        """`"build/" in "prebuild/helper.py/"` is True. A substring test would
        skip a real file under a future `prebuild/` and then report a well-formed
        pack's declared target as missing."""
        assert not (set(C._RESOLVE_SKIP) and
                    C.resolve_target("cli.py")[0] is None), (
            "a real target became unresolvable via the skip filter"
        )
        path, status = C.resolve_target("cli.py")
        assert status == "ok" and path.as_posix().endswith("espalier/cli.py")


class TestCoverageHonesty:
    def test_untagged_fence_is_skipped_never_cleared(self, tmp_path):
        """A pack quotes existing source and prescribes new source in the same
        syntax. Untagged means unknown, and unknown must not read as clean."""
        pack = _pack(tmp_path, """
            ```python
            value = totally_undefined_name
            ```
            """)
        findings, cov = C.check_pack(pack)
        assert cov["skipped"] == 1 and cov["checked"] == 0
        assert not findings, "an untagged fence must not produce a verdict"

    def test_an_inferred_target_that_misses_is_not_blamed_on_the_pack(self, tmp_path):
        """Measured: 95 of 123 --infer reports over the Done corpus were
        'target does not exist' -- this script guessing badly and billing the
        pack for it. A guess that does not resolve is our failure, silently."""
        pack = _pack(tmp_path, """
            Some prose mentioning `no_such_module_anywhere.py` first.

            ```python
            x = 1
            ```
            """)
        findings, cov = C.check_pack(pack, infer=True)
        assert cov["no_target"] == 1
        assert not findings, findings

    def test_a_declared_target_that_misses_IS_reported(self, tmp_path):
        """The other half: an author's declaration is a claim, and a claim that
        does not resolve is a finding."""
        pack = _pack(tmp_path, """
            ```python target=no_such_module_anywhere.py
            x = 1
            ```
            """)
        findings, _ = C.check_pack(pack)
        assert any("declared target is missing" in f for f in findings), findings

    def test_bare_basename_resolves_to_a_unique_repo_file(self, tmp_path):
        """Packs cite ``cli.py``, not ``espalier/cli.py``. A literal root-join
        answers 'does not exist' for a file that plainly does."""
        path, status = C.resolve_target("cli.py")
        assert status == "ok" and path is not None
        assert path.as_posix().endswith("espalier/cli.py")

    def test_main_says_nothing_was_resolved_even_with_no_python_fences(
        self, tmp_path, capsys
    ):
        """The NOTE used to be gated on "there were some fences", which silenced
        it in the case where "nothing was verified" is most obviously true."""
        pack = _pack(tmp_path, """
            A pack with prose only.
            """)
        rc = C.main([str(pack)])
        out = capsys.readouterr().out
        assert "NOTHING WAS RESOLVED" in out, out
        assert rc == 0, "without --require-coverage, zero coverage is not an error"

    def test_require_coverage_exits_nonzero_when_nothing_was_checked(
        self, tmp_path, capsys
    ):
        """Automation cannot read a coverage line the way a human can. Without
        this, a driver reads exit 0 from a run that resolved nothing and reports
        the step clean -- FAILURE_MODES §13.20 wearing a different hat."""
        pack = _pack(tmp_path, """
            ```python
            x = undefined_thing
            ```
            """)
        assert C.main([str(pack), "--require-coverage"]) == 2
        assert "exit 2" in capsys.readouterr().err

    def test_require_coverage_is_satisfied_by_a_tagged_fence(self, tmp_path):
        """The other half: coverage exists, so the flag must not fire."""
        pack = _pack(tmp_path, """
            ```python target=espalier/cli.py
            value = shutil.which("x")
            ```
            """)
        assert C.main([str(pack), "--require-coverage"]) == 0

    def test_an_ambiguous_basename_is_not_guessed(self):
        """Resolving a multi-hit basename would make the answer depend on walk
        order -- a different verdict on a different filesystem."""
        _, status = C.resolve_target("__init__.py")
        assert status == "ambiguous"


class TestResolveLeavesSecondCopiesOut:
    """A bare basename resolves to this tree's one file, never to a second copy
    of it: a linked worktree under `.claude/worktrees/` (a gitlink `.git`; the
    full tier beside a live worktree session redded the two `cli.py` rows above,
    measured 2026-10-10), or the vendored mirror the skip list names. Either
    made a declared target read `ambiguous`, which `check_pack` reports as a
    BLOCK. Each on a scratch root, with a real two-copy control beside it."""

    def _root(self, tmp_path, monkeypatch, *files):
        for rel in files:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(C, "_ROOT", tmp_path)
        return tmp_path

    def test_a_linked_worktree_is_not_a_second_copy(self, tmp_path, monkeypatch):
        root = self._root(tmp_path, monkeypatch, "espalier/cli.py",
                          ".claude/worktrees/probe/espalier/cli.py")
        (root / ".claude" / "worktrees" / "probe" / ".git").write_text(
            "gitdir: /elsewhere/.git/worktrees/probe\n", encoding="utf-8")
        path, status = C.resolve_target("cli.py")
        assert (status, path) == ("ok", root / "espalier" / "cli.py")

    def test_an_embedded_clone_is_not_a_second_copy(self, tmp_path, monkeypatch):
        root = self._root(tmp_path, monkeypatch, "espalier/cli.py", "vendor/clone/cli.py")
        (root / "vendor" / "clone" / ".git").mkdir()
        assert C.resolve_target("cli.py") == (root / "espalier" / "cli.py", "ok")

    def test_the_vendored_mirror_is_skipped_by_its_two_segment_entry(self, tmp_path, monkeypatch):
        """`espalier/_vendor/` names two segments; matched against one segment
        at a time it never fired, so every tools/cc script a pack cites by
        basename read `ambiguous` on every machine (`write_guard.py`,
        `ledger_row.py`, measured on the live tree 2026-10-10)."""
        root = self._root(tmp_path, monkeypatch, "tools/cc/hooks/write_guard.py",
                          "espalier/_vendor/cc/hooks/write_guard.py",
                          "espalier/assets/claude/x.md", "docs/x.md")
        assert C.resolve_target("write_guard.py") == (root / "tools/cc/hooks/write_guard.py", "ok")
        assert C.resolve_target("x.md") == (root / "docs" / "x.md", "ok")

    def test_a_two_segment_entry_is_anchored_at_the_root(self, tmp_path, monkeypatch):
        """The control: `espalier/_vendor` deeper in the tree is not the mirror,
        and two real copies of a name still read `ambiguous`."""
        self._root(tmp_path, monkeypatch, "a/espalier/_vendor/y.py", "b/y.py")
        assert C.resolve_target("y.py") == (None, "ambiguous")

    @pytest.mark.parametrize("entry", C._RESOLVE_SKIP)
    def test_every_skip_entry_skips_its_directory(self, entry, tmp_path, monkeypatch):
        """Derived from the list, so a dead entry reds by name: two of these were
        dead for as long as the filter compared one segment at a time. The
        `.claude/worktrees/` row is the worktree folder whose `.git` link is gone,
        which the nested-repo rule cannot see."""
        root = self._root(tmp_path, monkeypatch, f"{entry}probe_target.py", "src/probe_target.py")
        assert C.resolve_target("probe_target.py") == (root / "src" / "probe_target.py", "ok")

    def test_every_skip_entry_is_a_plain_directory_path(self):
        """`/build/`, `./dist/` or `*.egg-info/` would split into segments that
        never match: as dead as the two-segment entries were."""
        malformed = [e for e in C._RESOLVE_SKIP
                     if not e.endswith("/") or e.startswith(("/", "./")) or any(c in e for c in "*?[\\")]
        assert not malformed, malformed

    def test_a_worktree_folder_whose_link_is_gone_is_skipped_by_name(self, tmp_path, monkeypatch):
        """The `.claude/worktrees/` entry pinned by name, since the derived rows
        above cannot see an entry dropped from the list: an interrupted removal
        leaves a worktree folder without its `.git` (`tools/cc/checkout_sync.py`
        reports that state), and the nested-repo rule no longer sees it."""
        root = self._root(tmp_path, monkeypatch, "espalier/cli.py", ".claude/worktrees/old/espalier/cli.py")
        assert C.resolve_target("cli.py") == (root / "espalier" / "cli.py", "ok")
