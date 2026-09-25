# pytest-marker: default-unit
"""Engine tests for espalier/strengthen.py (P1 enumeration, P2 cross-ref, P3 rank).

These guard the strengthen engine's contract: enumeration must respect __all__
and skip dunders/underscores, the cross-reference must not regress to the
module::name walk bug (which false-reports every symbol untested), and the risk
ranking must order exported I/O gaps above trivial pure helpers. They earn the
red — a tested fixture symbol MUST resolve to a real reference.

The strengthen_fixture is a synthetic repo:
- sample_module.py: __all__ = ["kept", "writer"]; kept (tested, pure),
  writer (untested, I/O), helper (not exported), _private (underscore).
- pkg_util.py: no __all__ → small_helper is public, untested, trivial, pure.
- tests/uses_kept.py: a non-collected reference file exercising kept().
"""
from __future__ import annotations

import ast
from pathlib import Path, PureWindowsPath

from espalier.strengthen import (
    PublicSymbol,
    RankedGap,
    _W_EXPORTED,
    _W_FANIN_CAP,
    _W_FANIN_PER_REF,
    _identify_tested_symbols,
    _posix_relpath,
    _rank_gaps,
    _symbols_from_tree,
    build_strengthen_report,
    enumerate_public_surface,
    render_strengthen_md,
)

FIXTURE = Path(__file__).parent / "fixtures" / "strengthen_fixture"


def _by_name(symbols: list[PublicSymbol]) -> dict[str, PublicSymbol]:
    return {s.name: s for s in symbols}


def _extract(source: str, module_path: str) -> list[PublicSymbol]:
    """Parse ``source`` → its public symbols, returning [] on SyntaxError.

    Test-local convenience over ``_symbols_from_tree`` (which takes an
    already-parsed tree). Mirrors the string→symbols, SyntaxError→[] behavior
    the enumeration path itself relies on — ``enumerate_public_surface`` inlines
    the same parse+``_symbols_from_tree``, so no production wrapper is needed."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return _symbols_from_tree(tree, module_path)


class TestPublicSurfaceEnumeration:
    def test_all_gates_the_public_surface(self):
        symbols, _ = enumerate_public_surface(FIXTURE)
        names = {s.name for s in symbols}
        assert "kept" in names          # exported
        assert "writer" in names        # exported
        assert "helper" not in names    # public-looking but not in __all__
        assert "_private" not in names  # underscore

    def test_dunder_all_itself_is_not_a_symbol(self):
        symbols, _ = enumerate_public_surface(FIXTURE)
        assert "__all__" not in {s.name for s in symbols}

    def test_no_all_falls_back_to_non_underscore(self):
        symbols, _ = enumerate_public_surface(FIXTURE)
        assert "small_helper" in {s.name for s in symbols}

    def test_is_exported_and_io_flags(self):
        symbols, _ = enumerate_public_surface(FIXTURE)
        by = _by_name(symbols)
        assert by["kept"].is_exported is True
        assert by["kept"].does_io is False
        assert by["writer"].does_io is True       # open()/write()
        assert by["small_helper"].is_exported is False

    def test_module_path_is_posix_normalized(self):
        # On-host arm: enumerated paths are forward-slash. This is a TAUTOLOGY on
        # POSIX (the walk never yields backslashes); the real guard is the
        # negative arm below.
        symbols, _ = enumerate_public_surface(FIXTURE)
        assert all("\\" not in s.module_path for s in symbols)

    def test_posix_relpath_normalizes_windows_separators(self):
        # Real negative arm (earn-the-red): module_path normalization must STRIP
        # separators, not inherit the host's. On POSIX the walk can't produce a
        # backslash, so exercise the `_posix_relpath` seam directly with a
        # Windows-flavored path. This RED-goes if `.as_posix()` is dropped from
        # `_posix_relpath` (strengthen.py) — it would then return "pkg\\sub\\mod.py".
        root = PureWindowsPath("C:/repo")
        win = PureWindowsPath("C:/repo/pkg/sub/mod.py")
        assert "\\" in str(win.relative_to(root))  # precondition: raw path HAS separators
        rel = _posix_relpath(win, root)
        assert "\\" not in rel
        assert rel == "pkg/sub/mod.py"

    def test_earn_the_red_removing_from_all_drops_symbol(self):
        # Present in __all__ -> enumerated.
        with_kept = _extract(
            '__all__ = ["kept"]\ndef kept():\n    return 1\n', "m.py"
        )
        assert "kept" in {s.name for s in with_kept}
        # Removed from __all__ -> drops out (RED without the __all__ gate).
        without_kept = _extract(
            '__all__ = ["other"]\ndef kept():\n    return 1\n', "m.py"
        )
        assert "kept" not in {s.name for s in without_kept}

    def test_syntax_error_is_safe(self):
        assert _extract("def (:\n", "broken.py") == []

    def test_unparseable_files_reported_not_crashed(self, tmp_path):
        (tmp_path / "ok.py").write_text("def good():\n    return 1\n", encoding="utf-8")
        (tmp_path / "bad.py").write_text("def (:\n", encoding="utf-8")
        symbols, unparseable = enumerate_public_surface(tmp_path)
        assert "good" in {s.name for s in symbols}
        assert "bad.py" in unparseable


class TestTestReferenceCrossRef:
    def test_tested_symbol_has_high_confidence_ref(self):
        # Guards the ::-bug regression: kept() is referenced under tests/, so a
        # >=1-high-confidence-ref cross-ref MUST mark it tested. Under the buggy
        # module::name walk form every symbol would read untested.
        symbols, _ = enumerate_public_surface(FIXTURE)
        tested = _identify_tested_symbols(symbols, FIXTURE)
        assert any(k.endswith("::kept") for k in tested)

    def test_untested_symbol_absent_from_tested_set(self):
        symbols, _ = enumerate_public_surface(FIXTURE)
        tested = _identify_tested_symbols(symbols, FIXTURE)
        assert not any(k.endswith("::writer") for k in tested)

    def test_mode_b_when_no_test_infrastructure(self, tmp_path):
        (tmp_path / "lib.py").write_text(
            "def alpha():\n    return 1\ndef beta():\n    return 2\n", encoding="utf-8"
        )
        report = build_strengthen_report(tmp_path)
        assert report["mode"] == "b"
        # Every public symbol is reported untested in mode-b.
        assert report["total_untested"] == report["total_public"] == 2

    def test_mode_a_when_test_tree_present(self):
        report = build_strengthen_report(FIXTURE)
        assert report["mode"] == "a"


class TestRiskRanking:
    def test_exported_io_outranks_trivial_pure_helper(self):
        report = build_strengthen_report(FIXTURE)
        scores = {g["name"]: g["risk_score"] for g in report["gaps"]}
        assert scores["writer"] > scores["small_helper"]

    def test_ranked_list_is_score_descending(self):
        symbols, _ = enumerate_public_surface(FIXTURE)
        ranked = _rank_gaps(symbols, {}, skip_fan_in=True)
        assert isinstance(ranked[0], RankedGap)
        assert [g.risk_score for g in ranked] == sorted(
            (g.risk_score for g in ranked), reverse=True
        )

    def test_scope_bound_line_emitted_when_over_top_n(self):
        # Fixture has 2 untested public symbols (writer, small_helper).
        report = build_strengthen_report(FIXTURE, top_n=1)
        assert report["bounded"] == 1
        assert "bounded 1" in report["scope_note"]
        assert len(report["gaps"]) == 1

    def test_render_markdown_smoke(self):
        report = build_strengthen_report(FIXTURE)
        md = render_strengthen_md(report)
        assert "# Strengthen report" in md
        assert "characterization" in md.lower()  # honesty caveat present


class TestFacadeReexportEnumeration:
    """B-2: __all__ names bound by imports (re-exports) + augmented += are surface."""

    def test_reexports_and_augmented_all_are_public_surface(self):
        # A facade __init__.py: A,B bound by imports (re-exports), C a local def,
        # D added via augmented `__all__ +=`. All four are declared public API.
        src = (
            "from .sub import A\n"
            "import othermod as B\n"
            '__all__ = ["A", "B", "C"]\n'
            '__all__ += ["D"]\n'
            "\n"
            "def C():\n"
            "    return 1\n"
        )
        by = {s.name: s for s in _extract(src, "pkg/__init__.py")}
        assert set(by) == {"A", "B", "C", "D"}      # RED pre-fix: only {"C"}
        assert by["A"].kind == "reexport" and by["A"].is_exported
        assert by["A"].lineno == 1                   # `from .sub import A`
        assert by["B"].lineno == 2                   # `import othermod as B`
        assert by["C"].kind == "function"            # local def resolved normally
        assert by["D"].is_exported                   # augmented `+=` accounted

    def test_augmented_all_accumulates_onto_base(self):
        src = '__all__ = ["a"]\n__all__ += ["b"]\ndef a():\n    return 1\ndef b():\n    return 1\n'
        names = {s.name for s in _extract(src, "m.py")}
        assert names == {"a", "b"}


class TestFanInCrossModule:
    """B-3: fan-in proxies CROSS-module blast radius (same-module refs excluded)."""

    def _sym(self, name, *, exported=True):
        return PublicSymbol(
            module_path="pkg/mod.py", name=name, kind="class", lineno=1,
            end_lineno=2, is_exported=exported, does_io=False,
        )

    def test_same_module_refs_excluded_from_fan_in(self):
        # 12 refs, ALL inside the symbol's own module -> cross-module fan-in 0.
        ranked = _rank_gaps(
            [self._sym("Internal")], {"Internal": 12},
            self_ref_by_module={"pkg/mod.py": {"Internal": 12}},
        )
        assert "fan-in" not in ranked[0].reason
        assert ranked[0].risk_score == _W_EXPORTED   # exported only, no fan-in

    def test_cross_module_reason_shows_capped_value(self):
        # 10 total refs, 2 in own module -> 8 cross-module; score credits the cap.
        ranked = _rank_gaps(
            [self._sym("Hub", exported=False)], {"Hub": 10},
            self_ref_by_module={"pkg/mod.py": {"Hub": 2}},
        )
        assert "capped" in ranked[0].reason and "8 cross-module" in ranked[0].reason
        assert ranked[0].risk_score == _W_FANIN_CAP * _W_FANIN_PER_REF


class TestTopNHonesty:
    """B-1: a bounded/empty shown-slice must not read as a false all-clear."""

    def _report(self, *, total_untested, top_n, gaps=None):
        gaps = gaps or []
        return {
            "repo": "/x", "mode": "a", "total_public": 9,
            "total_untested": total_untested, "top_n": top_n,
            "bounded": max(0, total_untested - len(gaps)),
            "scope_note": "…", "gaps": gaps, "unparseable": [], "caveats": [],
        }

    # Both assertions key on the ASCII marker "ALL CLEAR", not on the emoji they
    # carried until 2026-09-03 (DEF-677). The emoji was deleted rather than
    # transliterated -- the one repair in that batch that removed a character
    # instead of substituting one -- and a deletion has a wider blast radius than
    # a substitution: this pair is a TWO-SIDED contract (celebrate iff genuinely
    # zero), so repointing only the failing half would have left the surviving
    # half asserting the absence of a character that no longer exists anywhere,
    # i.e. permanently, vacuously green. Keep both keyed on the same marker.
    def test_top_n_zero_does_not_false_all_clear(self):
        md = render_strengthen_md(self._report(total_untested=3, top_n=0))
        assert "ALL CLEAR" not in md
        assert "bounded out by" in md
        assert "3 untested" in md

    def test_zero_untested_still_celebrates(self):
        assert "ALL CLEAR" in render_strengthen_md(
            self._report(total_untested=0, top_n=20))

    def test_negative_top_n_is_clamped(self):
        # A negative top_n must not slice off the LAST (lowest-risk) gaps; it is
        # clamped to 0 so the report is honest ("none shown"), never a partial view.
        report = build_strengthen_report(FIXTURE, top_n=-1)
        assert report["top_n"] == 0
        assert report["gaps"] == []
        assert report["bounded"] == report["total_untested"]


class TestHarnessOutputIsNotTheAdoptersSurface:
    """DEF-410f sister site, driven 2026-09-12 on a fresh init: the adopter's
    report enumerated 395 public symbols, every one under tools/cc/, and their
    own module was nowhere in the top twenty. Harness output is skipped by
    ``analyze.is_harness_output`` on an adopter tree and kept on the self-host
    tree, where tools/cc/ is this repo's own source."""

    @staticmethod
    def _tree(root: Path) -> None:
        (root / "src").mkdir()
        (root / "src" / "app.py").write_text("def theirs():\n    return 1\n", encoding="utf-8")
        for rel in (
            "tools/cc/hooks/write_guard.py", "tools/cc/execution_plan.py",
            "reports/probe.py", ".claude/helper.py",
        ):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("def ours():\n    return 0\n", encoding="utf-8")

    def test_an_adopter_tree_enumerates_only_the_adopters_symbols(self, tmp_path):
        self._tree(tmp_path)
        symbols, _unparseable = enumerate_public_surface(tmp_path)
        assert sorted(s.module_path for s in symbols) == ["src/app.py"]

    def test_the_self_host_tree_keeps_its_own_hooks(self, tmp_path, monkeypatch):
        import espalier.strengthen as strengthen_module

        self._tree(tmp_path)
        monkeypatch.setattr(strengthen_module, "is_self_host_repo", lambda root: True)
        symbols, _unparseable = enumerate_public_surface(tmp_path)
        assert {s.module_path for s in symbols} >= {"src/app.py", "tools/cc/hooks/write_guard.py"}
