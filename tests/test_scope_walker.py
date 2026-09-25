"""TP-38: tests for the scope walker.

Use the pure-Python fallback (``use_ripgrep=False``) so the contract is
testable without depending on a system ``rg`` binary.

Note on path literals: assertions reference forward-slash forms
(``"src/a.py"``) rather than constructing platform-native paths. This is
valid because ``walk_references`` normalises every emitted ``file`` field
to forward slashes at emit time — pin maintained at
``espalier/scope_walker.py`` (``.replace("\\\\", "/")`` after relative_to).
A future refactor that removes the normalisation would surface as
Windows-only failures in this test module.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from espalier.scope_walker import (
    _is_identifier,
    _walk_with_ripgrep,
    classify_references,
    walk_references,
    walk_references_multi,
)


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """A tiny repo with deliberate string and import references."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "a.py").write_text(
        "from src.b import helper\n"
        "PATH = '.claude/agents/'\n"
        "def x():\n"
        "    return PATH\n",
        encoding="utf-8",
    )
    (src / "b.py").write_text(
        "# uses .claude/agents/ indirectly via the path constant in a.py\n"
        "def helper(): return 1\n",
        encoding="utf-8",
    )
    (src / "c.py").write_text(
        "import src.a\n"
        "VALUE = src.a.PATH\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "See `.claude/agents/` for the layout.\n",
        encoding="utf-8",
    )
    excluded = tmp_path / "__pycache__"
    excluded.mkdir()
    (excluded / "ignored.py").write_text(
        "PATH = '.claude/agents/'\n", encoding="utf-8",
    )
    return tmp_path


class TestWalkReferencesString:
    def test_finds_code_and_comment_refs(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        files = {r["file"] for r in refs}
        assert "src/a.py" in files
        assert "src/b.py" in files
        assert "docs/guide.md" in files

    def test_skips_excluded_dirs(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        files = {r["file"] for r in refs}
        assert "__pycache__/ignored.py" not in files

    def test_comment_refs_are_low_confidence(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        comment_refs = [r for r in refs if r["kind"] == "comment"]
        assert comment_refs, "expected at least one comment match"
        assert all(r["confidence"] == "low" for r in comment_refs)

    def test_code_refs_are_high_confidence(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        code_refs = [r for r in refs if r["kind"] == "string"]
        assert code_refs
        assert all(r["confidence"] == "high" for r in code_refs)

    def test_normalises_forward_slashes(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        assert all("\\" not in r["file"] for r in refs)

    def test_only_included_extensions(self, tmp_path):
        (tmp_path / "ok.py").write_text("X = '.claude/agents/'\n", encoding="utf-8")
        (tmp_path / "ignored.bin").write_text("X = '.claude/agents/'\n", encoding="utf-8")
        refs = walk_references(tmp_path, ".claude/agents/", use_ripgrep=False)
        files = {r["file"] for r in refs}
        assert "ok.py" in files
        assert "ignored.bin" not in files


class TestWordBoundaryMatching:
    """Identifier symbols match as whole words (so ``main`` does not match
    ``maintain``/``domain``/``docs-maintainer`` — the scope-check noise source);
    path/dotted symbols keep substring matching."""

    @pytest.fixture
    def noisy_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "real.py").write_text(
            "def main():\n"
            "    return 1\n"
            "if __name__ == '__main__':\n"
            "    main()\n",
            encoding="utf-8",
        )
        (tmp_path / "noise.py").write_text(
            "def maintain():  # keeps things tidy\n"
            "    domain = 'remaining'\n"
            "    return domain\n",
            encoding="utf-8",
        )
        (tmp_path / "agent.md").write_text(
            "The docs-maintainer agent maintains the domain docs.\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_identifier_matches_whole_word_only(self, noisy_repo):
        refs = walk_references(noisy_repo, "main", use_ripgrep=False)
        files = {r["file"] for r in refs}
        assert "real.py" in files, "must still find real def main / main() refs"
        assert "noise.py" not in files, "must NOT match maintain/domain/remaining"
        assert "agent.md" not in files, "must NOT match docs-maintainer/maintains"

    def test_underscore_identifier_is_a_whole_word(self, tmp_path):
        (tmp_path / "a.py").write_text("def _run_main():\n    pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text(
            "def my_run_main_helper():\n    pass\n", encoding="utf-8",
        )
        refs = walk_references(tmp_path, "_run_main", use_ripgrep=False)
        files = {r["file"] for r in refs}
        assert "a.py" in files
        assert "b.py" not in files, "_run_main must not match my_run_main_helper"

    def test_path_symbol_stays_substring(self, tmp_path):
        # Paths are not identifiers — keep substring matching (no word boundary).
        (tmp_path / "x.py").write_text("P = '.claude/agents/foo'\n", encoding="utf-8")
        refs = walk_references(tmp_path, ".claude/agents/", use_ripgrep=False)
        assert any(r["file"] == "x.py" for r in refs)

    def test_is_identifier_discriminates(self):
        assert _is_identifier("main")
        assert _is_identifier("_run_main")
        assert _is_identifier("EXPECTED_COMMAND_COUNT")
        assert not _is_identifier(".claude/agents/")
        assert not _is_identifier("espalier.cli")
        assert not _is_identifier("read-summary.md")

    def test_hyphen_is_a_word_boundary_documented(self, tmp_path):
        """A hyphen is a word boundary, so identifier ``main`` matches
        ``pre-main-hook``. Documented behavior, not a bug — pinned so a future
        matcher change is a conscious decision."""
        (tmp_path / "f.md").write_text("see the pre-main-hook step\n", encoding="utf-8")
        refs = walk_references(tmp_path, "main", use_ripgrep=False)
        assert any(r["file"] == "f.md" for r in refs), (
            "hyphenated mention `pre-main-hook` should match identifier `main`"
        )

    def test_same_name_symbol_matches_every_module(self, tmp_path):
        """A bare identifier greps every module — two different modules each
        defining ``main`` both surface. Documents the ``cli.py::main`` -> bare
        ``main`` same-name fan-out scope-check reports."""
        (tmp_path / "a.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def main():\n    return 2\n", encoding="utf-8")
        refs = walk_references(tmp_path, "main", use_ripgrep=False)
        files = {r["file"] for r in refs}
        assert {"a.py", "b.py"} <= files, (
            "bare `main` should match both modules (same-name fan-out is intended)"
        )


def test_walk_python_imports_removed_as_dead_surface():
    """TP-151 F-3: ``walk_python_imports`` had zero production callers, and its
    dotted-module input shape (``espalier.surface_contract``) does not match
    scope-check's bare-symbol affected-symbols (which ``walk_references``
    already covers textually, including ``from X import symbol`` edges).
    Removed as dead public surface; this pins that it stays removed (re-adding
    it needs a real production caller + a wire into ``cmd_scope_check``)."""
    import espalier.scope_walker as sw

    assert not hasattr(sw, "walk_python_imports"), (
        "walk_python_imports was removed as dead surface (TP-151 F-3)."
    )


class TestWalkReferencesEdgeCases:
    def test_zero_matches_returns_empty_list(self, synthetic_repo):
        refs = walk_references(
            synthetic_repo, "no_such_symbol_anywhere_xyz", use_ripgrep=False,
        )
        assert refs == []

    def test_walk_references_skips_symlinks(self, synthetic_repo, tmp_path):
        """Round-6: walk_references must not follow symlinks targeting
        files outside repo_root. The pure-Python fallback would
        otherwise read /etc/passwd or any sibling secret via
        path.read_text on the symlink target."""
        secret = tmp_path / "outside.py"
        secret.write_text("PATH = '.claude/agents/'  # secret content\n", encoding="utf-8")
        link = synthetic_repo / "src" / "linked.py"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("filesystem doesn't support symlinks")
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        assert all(r["file"] != "src/linked.py" for r in refs), (
            "walk_references followed a symlink outside repo_root"
        )


class TestClassifyReferences:
    def test_exact_file_match_is_in_scope(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        classified = classify_references(refs, scope_in=["src/a.py"])
        assert any(r["file"] == "src/a.py" for r in classified["in_scope"])
        assert all(r["file"] != "src/a.py" for r in classified["out_of_scope"])

    def test_directory_prefix_matches_subpaths(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        classified = classify_references(refs, scope_in=["src/"])
        for r in classified["in_scope"]:
            assert r["file"].startswith("src/")
        for r in classified["out_of_scope"]:
            assert not r["file"].startswith("src/")

    def test_directory_without_trailing_slash_also_matches(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        classified = classify_references(refs, scope_in=["src"])
        # Directory-shaped without trailing slash → prefix match still fires.
        assert any(r["file"].startswith("src/") for r in classified["in_scope"])

    def test_empty_scope_means_all_out_of_scope(self, synthetic_repo):
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        classified = classify_references(refs, scope_in=[])
        assert classified["in_scope"] == []
        assert len(classified["out_of_scope"]) == len(refs)

    def test_windows_backslash_in_scope_in_is_normalised(self, synthetic_repo):
        """Pack author writes ``src\\a.py`` on a Windows host; classifier
        must still match the forward-slash reference path."""
        refs = walk_references(synthetic_repo, ".claude/agents/", use_ripgrep=False)
        classified = classify_references(refs, scope_in=[r"src\a.py"])
        assert any(r["file"] == "src/a.py" for r in classified["in_scope"])


class TestRipgrepParityWithFallback:
    """Default invocation (ripgrep when available) returns the same file set
    as the fallback on the same input."""

    def test_default_and_fallback_agree(self, synthetic_repo):
        if shutil.which("rg") is None:
            pytest.skip(
                "ripgrep not installed; default/fallback parity needs the rg "
                "arm — without it the default path also uses _walk_with_python, "
                "so both operands are the same backend (X == X) and the parity "
                "this test names goes untested."
            )
        default_refs = walk_references(synthetic_repo, ".claude/agents/")
        fallback_refs = walk_references(
            synthetic_repo, ".claude/agents/", use_ripgrep=False
        )
        # Compare by (file, line) pairs since the two backends may differ
        # in trailing-whitespace handling of context.
        default_keys = {(r["file"], r["line"]) for r in default_refs}
        fallback_keys = {(r["file"], r["line"]) for r in fallback_refs}
        assert default_keys == fallback_keys


class TestRipgrepParityOnHiddenAndIgnored:
    """TP-174a (MAJOR, S3): the ``synthetic_repo`` parity fixture has no
    hidden dirs and no ``.gitignore``, so the original parity test was green
    even while the rg arm (pre ``--hidden --no-ignore``) silently dropped
    dotfiles and ``.gitignore``'d files that the Python arm walks. This
    fixture carries both, so the backends MUST agree — earning the red the
    original fixture could not.
    """

    @pytest.fixture
    def repo_with_hidden_and_ignored(self, tmp_path: Path) -> Path:
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        # Symbol inside a HIDDEN dotdir (.claude/ is walked by the Python arm,
        # skipped by rg without --hidden).
        claude = tmp_path / ".claude" / "agents"
        claude.mkdir(parents=True)
        (claude / "x.md").write_text(
            "references session_start here\n", encoding="utf-8"
        )
        # Symbol inside a .gitignore'd file (walked by the Python arm, skipped
        # by rg without --no-ignore).
        (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        (tmp_path / "ignored.py").write_text(
            "X = 'session_start'\n", encoding="utf-8"
        )
        # A normal tracked file (both arms always see this one).
        (tmp_path / "tracked.py").write_text(
            "Y = 'session_start'\n", encoding="utf-8"
        )
        return tmp_path

    def test_rg_argv_includes_hidden_and_no_ignore(self, tmp_path, monkeypatch):
        """Environment-independent earn-the-red: the rg invocation must carry
        ``--hidden`` AND ``--no-ignore`` so it walks the same tree as the
        Python arm. Captures the argv without needing a real ``rg`` binary —
        fails against pre-fix HEAD (flags absent) on any host."""
        import subprocess as _sp

        from espalier import scope_walker

        captured: dict[str, list[str]] = {}

        class _FakeProc:
            returncode = 1  # "no matches" — argv is what we assert on
            stdout = ""

        def _fake_run(argv, *a, **k):
            captured["argv"] = list(argv)
            return _FakeProc()

        monkeypatch.setattr(_sp, "run", _fake_run)
        scope_walker._walk_with_ripgrep(tmp_path, "session_start", True)
        argv = captured.get("argv", [])
        assert "--hidden" in argv, f"rg argv missing --hidden: {argv}"
        assert "--no-ignore" in argv, f"rg argv missing --no-ignore: {argv}"
        # The literal-symbol separator must still precede the operands.
        assert "--" in argv and argv.index("--") < argv.index("session_start")

    def test_rg_and_python_arms_agree(self, repo_with_hidden_and_ignored):
        import shutil

        if shutil.which("rg") is None:
            pytest.skip("ripgrep not installed; the parity test needs the rg arm")
        from espalier.scope_walker import _walk_with_python, _walk_with_ripgrep

        root = repo_with_hidden_and_ignored
        symbol = "session_start"
        rg_refs = _walk_with_ripgrep(root, symbol, True)  # session_start: identifier
        assert rg_refs is not None, "rg arm returned None despite rg present"
        py_refs = _walk_with_python(root, symbol, True)

        rg_keys = {(r["file"], r["line"]) for r in rg_refs}
        py_keys = {(r["file"], r["line"]) for r in py_refs}
        assert rg_keys == py_keys, (
            f"backend divergence: rg-only={rg_keys - py_keys}, "
            f"py-only={py_keys - rg_keys}"
        )
        # Anchor the red: the hidden + ignored files MUST be in the shared set
        # (pre-fix the rg arm dropped exactly these, so the sets diverged).
        files = {f for f, _ in rg_keys}
        assert ".claude/agents/x.md" in files, "hidden dotdir ref missing"
        assert "ignored.py" in files, "gitignored ref missing"


class TestRipgrepArgumentInjection:
    """TP-40: lock the contract that ``_walk_with_ripgrep`` passes
    user-supplied symbol names as positional arguments only, never as
    rg flags. ``--`` separates flags from operands; the call site uses
    ``[rg, ..., --fixed-strings, --null, --, symbol, repo_root]`` which
    is safe today. This test fails if a future refactor drops the
    ``--`` separator or moves the symbol before it.
    """

    def test_flag_shaped_symbol_passes_through_as_literal(self, tmp_path):
        """Symbol ``--type=py`` must be searched literally, not parsed by rg."""
        # Create files: one containing the literal "--type=py", one with
        # different content. If `--` correctly separates flags from operands,
        # rg matches only the literal occurrence.
        (tmp_path / "match.py").write_text("--type=py\n", encoding="utf-8")
        (tmp_path / "miss.txt").write_text("hello world\n", encoding="utf-8")

        # Public path: the literal occurrence is found, the miss file is not,
        # and no exception escapes from rg parsing the symbol as a flag.
        refs = walk_references(tmp_path, "--type=py")
        assert any("match.py" in r["file"] for r in refs)
        assert not any("miss.txt" in r["file"] for r in refs)

        # rg-path contract: when ripgrep is available, the `--` separator must
        # make rg treat the symbol literally — a non-None result (a flag-parse
        # error would return None and silently fall back to the Python walker).
        if shutil.which("rg"):
            rg_refs = _walk_with_ripgrep(tmp_path, "--type=py", False)  # not an identifier
            assert rg_refs is not None
            assert any("match.py" in r["file"] for r in rg_refs)
            # Absence arm. Without it this branch pinned only PRESENCE, so an rg
            # backend that returned every file would satisfy it — the born-weak
            # shape (a gate that cannot fail the way it claims to). The public
            # path above asserts both directions; the rg path must too, or the
            # two arms are not actually being held to the same contract.
            assert not any("miss.txt" in r["file"] for r in rg_refs)

    def test_double_dash_alone_does_not_crash(self, tmp_path):
        """Edge case: symbol literally is ``--``. Must not crash."""
        (tmp_path / "x.py").write_text("# noop\n", encoding="utf-8")
        refs = walk_references(tmp_path, "--")
        assert isinstance(refs, list)

    def test_dash_e_symbol_does_not_invoke_eval(self, tmp_path):
        """Symbol ``-e`` is a real rg flag (`--regexp=PATTERN`). Must not leak."""
        (tmp_path / "y.py").write_text("-e\n", encoding="utf-8")
        refs = walk_references(tmp_path, "-e")
        assert isinstance(refs, list)


class TestWalkReferencesMulti:
    """F: the batched multi-symbol walk is behavior-identical to per-symbol walks
    (the O(symbols x files) -> O(files) fix reads the tree ONCE, not once/symbol)."""

    SYMBOLS = ["helper", "PATH", "VALUE", ".claude/agents/", "src/a.py"]

    def test_python_arm_matches_per_symbol(self, synthetic_repo):
        per = {s: walk_references(synthetic_repo, s, use_ripgrep=False) for s in self.SYMBOLS}
        batched = walk_references_multi(synthetic_repo, self.SYMBOLS, use_ripgrep=False)
        assert set(batched) == set(self.SYMBOLS)
        for s in self.SYMBOLS:
            assert batched[s] == per[s], f"batched != per-symbol for {s!r}"

    @pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep not installed")
    def test_ripgrep_arm_matches_per_symbol(self, synthetic_repo):
        per = {s: walk_references(synthetic_repo, s, use_ripgrep=True) for s in self.SYMBOLS}
        batched = walk_references_multi(synthetic_repo, self.SYMBOLS, use_ripgrep=True)
        for s in self.SYMBOLS:
            assert batched[s] == per[s], f"rg batched != per-symbol for {s!r}"

    def test_ripgrep_arm_sorts_regardless_of_rg_output_order(self, synthetic_repo, monkeypatch):
        """The rg arm must impose (file, line) order, not inherit rg's.

        ``rg`` searches files in PARALLEL, so its cross-file output order is
        nondeterministic. ``walk_references_multi``'s docstring promises results
        "identical to walk_references ... same (file, line) ordering", and
        without an explicit sort that promise held only by luck: CI returned
        ``src/b.py`` before ``src/a.py`` and the parity gate failed on ordering
        alone, having passed on the previous commit with the same code.

        Driving ``_rg_multi`` directly instead of gating on
        ``shutil.which("rg")`` is deliberate — it makes this contract testable
        on hosts with no rg (which is every dev machine here, where rg resolves
        only as a shell function), rather than in one CI job.
        """
        from espalier import scope_walker as sw

        emitted = [
            ("src/b.py", 2, "def helper(): return 1"),
            ("src/a.py", 1, "from src.b import helper"),
        ]
        monkeypatch.setattr(sw, "_rg_multi", lambda root, group, wb: list(emitted))

        forward = sw._walk_multi_with_ripgrep(synthetic_repo, ["helper"])["helper"]
        emitted.reverse()
        reversed_ = sw._walk_multi_with_ripgrep(synthetic_repo, ["helper"])["helper"]

        order = [(r["file"], r["line"]) for r in forward]
        assert order == [("src/a.py", 1), ("src/b.py", 2)], (
            f"rg arm did not impose (file, line) order; got {order}"
        )
        assert forward == reversed_, (
            "rg arm's output depends on the order rg happened to emit — the "
            "same tree can produce different results run to run"
        )

    def test_duplicate_symbols_collapse_to_one_walk(self, synthetic_repo):
        batched = walk_references_multi(synthetic_repo, ["helper", "helper"], use_ripgrep=False)
        assert batched["helper"] == walk_references(synthetic_repo, "helper", use_ripgrep=False)

    def test_empty_symbol_list_is_empty_dict(self, synthetic_repo):
        assert walk_references_multi(synthetic_repo, [], use_ripgrep=False) == {}
