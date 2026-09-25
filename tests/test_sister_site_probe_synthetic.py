"""TP-107: synthetic injection harness for sister-site probe.

Parametrized over 5 cases that author small Python trees in ``tmp_path``
and assert the probe's report shape per case. The cases exercise the
probe's externally-observable contract — IDENTICAL/DIVERGENT clique
classification, body-match and alias-call CANON-MISS detection, and
opt-out marker suppression — without dependence on this repo's live
hook state.

Pins the detection-mode behavioral contract so a future probe refactor
cannot silently weaken any of the five modes; without this harness,
107-A only proves the calibration corpus still fires.

TP-108 extends this harness with new detection modes; do not re-author
the file structure when extending.

Test naming follows ``test_{specific_behavior}`` per docs/CONVENTIONS.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PROBE_PATH = REPO_ROOT / "tools" / "cc"
sys.path.insert(0, str(PROBE_PATH))
from sister_site_probe import probe_compression_debt, report_has_debt  # noqa: E402


def _make_hooks_tree(tmp_path: Path) -> Path:
    """Materialize an empty ``tools/cc/hooks/`` under tmp_path and return it.

    The probe's default scan targets are ``tools/cc/hooks/*.py`` (excluding
    CANONICAL_FILES) + ``espalier/*.py``. Synthetic files must live under
    this exact path for the probe to find them.
    """
    hooks_dir = tmp_path / "tools" / "cc" / "hooks"
    hooks_dir.mkdir(parents=True)
    # The engine package is what marks a tree as the harness SOURCE
    # (``probe_mode``); without it these unmarked hooks would read as an
    # adopter's pre-marker install and their findings would move to the
    # advisory ``harness_internal`` sub-report.
    (tmp_path / "espalier").mkdir(exist_ok=True)
    return hooks_dir


@pytest.mark.security
class TestSyntheticDetection:
    def test_identical_3_clique_fires_warn(self, tmp_path):
        """Three hooks with byte-identical bodies fire WARN-identical."""
        hooks = _make_hooks_tree(tmp_path)
        body = "def shared_helper():\n    return 42\n"
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [c for c in report.cliques if c.name == "shared_helper"]
        assert len(cliques) == 1, (
            f"Expected one shared_helper clique; got {len(cliques)}"
        )
        clique = cliques[0]
        assert clique.severity == "WARN", (
            f"Expected WARN for 3-site clique; got {clique.severity}"
        )
        assert not clique.divergent, (
            "Expected non-divergent (identical bodies); got divergent=True"
        )
        assert len(clique.sites) == 3

    def test_same_name_divergent_fires_warn_divergent(self, tmp_path):
        """Three hooks share a name but have different bodies — advisory."""
        hooks = _make_hooks_tree(tmp_path)
        bodies = [
            "def shared_helper():\n    return 1\n",
            "def shared_helper():\n    return 2\n",
            "def shared_helper():\n    x = 3\n    return x\n",
        ]
        for name, body in zip(("hook_a", "hook_b", "hook_c"), bodies):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [c for c in report.cliques if c.name == "shared_helper"]
        assert len(cliques) == 1
        clique = cliques[0]
        assert clique.severity == "WARN"
        assert clique.divergent, (
            "Expected divergent (different bodies); got divergent=False"
        )

    def test_canon_miss_body_match_fires(self, tmp_path):
        """A shadow function with different name + identical body fires."""
        hooks = _make_hooks_tree(tmp_path)
        canonical_body = (
            "def canonical_foo(x):\n"
            "    y = x + 1\n"
            "    return y\n"
        )
        (hooks / "_hook_utils.py").write_text(canonical_body, encoding="utf-8")
        shadow = (
            "def shadow_foo(x):\n"
            "    y = x + 1\n"
            "    return y\n"
        )
        (hooks / "some_hook.py").write_text(shadow, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        body_matches = [
            m for m in report.canon_misses if m.shape == "body-match"
        ]
        assert len(body_matches) == 1, (
            f"Expected one body-match canon_miss; got {len(body_matches)}"
        )
        miss = body_matches[0]
        assert miss.canonical_name == "canonical_foo"
        assert miss.shadow_name == "shadow_foo"

    def test_canon_miss_alias_call_fires(self, tmp_path):
        """A shadow that one-line-calls the canonical fires (alias-call)."""
        hooks = _make_hooks_tree(tmp_path)
        canonical = (
            "def canonical_foo(x):\n"
            "    return x * 2\n"
        )
        (hooks / "_hook_utils.py").write_text(canonical, encoding="utf-8")
        shadow = (
            "def shadow_foo(x):\n"
            "    return canonical_foo(x)\n"
        )
        (hooks / "some_hook.py").write_text(shadow, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        assert all(isinstance(m.canonical_file, str) for m in report.canon_misses), (
            "canonical_file must be the file path, not the (file, hash) tuple "
            "the alias-call arm used to leak (pre-existing; a --json contract now)"
        )
        alias_calls = [
            m for m in report.canon_misses if m.shape == "alias-call"
        ]
        assert len(alias_calls) == 1, (
            f"Expected one alias-call canon_miss; got {len(alias_calls)}"
        )
        miss = alias_calls[0]
        assert miss.canonical_name == "canonical_foo"
        assert miss.shadow_name == "shadow_foo"

    def test_opt_out_marker_suppresses_detection(self, tmp_path):
        """``# sister-site: ok <reason>`` above each def suppresses cliques."""
        hooks = _make_hooks_tree(tmp_path)
        body_with_optout = (
            "# sister-site: ok deliberate dup for synthetic test\n"
            "def shared_helper():\n"
            "    return 42\n"
        )
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(body_with_optout, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [c for c in report.cliques if c.name == "shared_helper"]
        assert cliques == [], (
            f"Opt-out marker should suppress all sites; got {len(cliques)} "
            f"cliques. Probe opt-out semantics broke."
        )

    # ---------------- TP-108 cases ----------------

    def test_alias_miss_fires_on_name_divergence(self, tmp_path):
        """``_my_normalize = _hook_utils.normalize_path`` (rename) fires."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "import _hook_utils\n"
            "_my_normalize = _hook_utils.normalize_path\n"
        )
        (hooks / "some_hook.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        hits = [
            m for m in report.alias_misses
            if m.lhs_name == "_my_normalize"
        ]
        assert len(hits) == 1, (
            f"Expected one alias-miss for rename drift; got "
            f"{len(report.alias_misses)} alias_misses: {report.alias_misses}"
        )
        assert hits[0].rhs_attr == "normalize_path"
        assert hits[0].rhs_module == "_hook_utils"

    def test_alias_miss_underscore_rename_does_not_fire(self, tmp_path):
        """``_X = M.X`` (prefix-underscore privatization) is OK — not a miss."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "import _hook_utils\n"
            "_normalize_path = _hook_utils.normalize_path\n"
        )
        (hooks / "some_hook.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        hits = [
            m for m in report.alias_misses
            if m.lhs_name == "_normalize_path"
        ]
        assert hits == [], (
            "Underscore-prefix rename is the legitimate convention; should "
            f"NOT fire alias-miss. Got {len(hits)} hits: {hits}"
        )

    def test_alias_miss_both_underscored_does_not_fire(self, tmp_path):
        """``_X = M._X`` (both privatized — common re-export shape used by
        ``write_guard`` for ``_bash_patterns`` regexes) does NOT fire.

        Regression for the "strip both sides" fix landed during
        TP-108-Audit. The pre-fix code stripped only LHS, treating
        ``_REDIRECT_RE = _bash_patterns._REDIRECT_RE`` as a rename drift
        when it is the legitimate symmetric-private re-export shape.
        """
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "import _bash_patterns\n"
            "_REDIRECT_RE = _bash_patterns._REDIRECT_RE\n"
        )
        (hooks / "some_hook.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        hits = [
            m for m in report.alias_misses
            if m.lhs_name == "_REDIRECT_RE"
        ]
        assert hits == [], (
            "``_X = M._X`` re-export should NOT fire alias-miss after the "
            f"strip-both-sides fix; got {len(hits)} hits: {hits}"
        )

    def test_alias_miss_import_from_fires(self, tmp_path):
        """TP-350: ``from M import Attr as _Other`` (import-form rename drift)
        fires alias-miss with shape import-from — the same drift the
        assignment form catches, in the second spelling."""
        hooks = _make_hooks_tree(tmp_path)
        (hooks / "importer_hook.py").write_text(
            "from _hook_utils import normalize_path as _canonicalize\n",
            encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        hits = [m for m in report.alias_misses if m.lhs_name == "_canonicalize"]
        assert len(hits) == 1, (
            f"import-form rename drift should fire alias-miss; got "
            f"{report.alias_misses}"
        )
        assert hits[0].shape == "import-from"
        assert hits[0].rhs_attr == "normalize_path"

    def test_alias_miss_import_underscore_privatize_does_not_fire(self, tmp_path):
        """TP-350: ``import stat as _stat`` / ``from M import X as _X`` (same
        basename, privatized) is the legitimate rename-for-private convention —
        no fire, symmetric with the assignment form."""
        hooks = _make_hooks_tree(tmp_path)
        (hooks / "priv_hook.py").write_text(
            "import stat as _stat\n"
            "from _hook_utils import normalize_path as _normalize_path\n",
            encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        hits = [
            m for m in report.alias_misses
            if m.lhs_name in {"_stat", "_normalize_path"}
        ]
        assert hits == [], (
            f"underscore-privatize import alias should NOT fire; got {hits}"
        )

    def test_alias_miss_opt_out_marker_suppresses(self, tmp_path):
        """``# sister-site: ok <reason>`` above an alias suppresses detection."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "import _hook_utils\n"
            "# sister-site: ok deliberate rename for synthetic test\n"
            "_my_normalize = _hook_utils.normalize_path\n"
        )
        (hooks / "some_hook.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        assert report.alias_misses == (), (
            f"Opt-out marker should suppress alias-miss; got "
            f"{report.alias_misses}"
        )

    def test_alias_miss_import_form_opt_out_marker_suppresses(self, tmp_path):
        """TP-350: ``# sister-site: ok <reason>`` above an IMPORT-form alias
        suppresses it too — pins that the opt-out check (moved to the top of
        the loop) reaches the import spelling, not only the assignment form."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "# sister-site: ok deliberate rename for synthetic test\n"
            "from _hook_utils import normalize_path as _canonicalize\n"
        )
        (hooks / "importer_hook.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        assert report.alias_misses == (), (
            f"Opt-out marker should suppress an import-form alias-miss; got "
            f"{report.alias_misses}"
        )

    def test_alias_miss_gates_after_flip(self, tmp_path):
        """TP-341: a rename alias now makes main() exit 2 (blocking)."""
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        (hooks / "some_hook.py").write_text(
            "import _hook_utils\n"
            "_my_normalize = _hook_utils.normalize_path\n",
            encoding="utf-8",
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, (
            f"alias-miss must gate (exit 2) after the advisory→blocking flip; "
            f"got exit {exit_code}"
        )

    def test_class_method_clique_fires_qualified(self, tmp_path):
        """Two classes in different files with same method-name + body fire
        a clique under qualified name ``ClassName.method_name``."""
        hooks = _make_hooks_tree(tmp_path)
        body_a = (
            "class HookA:\n"
            "    def _load_config(self):\n"
            "        return {'k': 1}\n"
        )
        body_b = (
            "class HookB:\n"
            "    def _load_config(self):\n"
            "        return {'k': 1}\n"
        )
        (hooks / "hook_a.py").write_text(body_a, encoding="utf-8")
        (hooks / "hook_b.py").write_text(body_b, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        # Same method name across two classes — qualified names differ,
        # so each is its own (1-site) — should NOT collide cross-class.
        # The clique fires only when the qualified name matches: i.e.,
        # two classes with the SAME name in different files (unusual but
        # the pattern the probe pins). With HookA + HookB the qualified
        # names are different (HookA._load_config vs HookB._load_config)
        # so no clique. This guards against unintended cross-class
        # collision via bare-name matching.
        cross_class = [
            c for c in report.cliques if c.name == "_load_config"
        ]
        assert cross_class == [], (
            "Bare _load_config should not collide across classes; got "
            f"{len(cross_class)} cliques on bare name."
        )

        # Same class name in two files DOES produce a clique. Rewrite
        # both files with the same class name.
        body_same_a = (
            "class SharedClass:\n"
            "    def _load_config(self):\n"
            "        return {'k': 1}\n"
        )
        body_same_b = (
            "class SharedClass:\n"
            "    def _load_config(self):\n"
            "        return {'k': 1}\n"
        )
        (hooks / "hook_a.py").write_text(body_same_a, encoding="utf-8")
        (hooks / "hook_b.py").write_text(body_same_b, encoding="utf-8")

        report2 = probe_compression_debt([tmp_path])
        qualified = [
            c for c in report2.cliques
            if c.name == "SharedClass._load_config"
        ]
        assert len(qualified) == 1, (
            f"Same class.method across 2 files should fire one clique; "
            f"got {len(qualified)}: {report2.cliques}"
        )
        assert qualified[0].severity == "INFO"
        assert not qualified[0].divergent

    def test_class_method_dunder_skipped(self, tmp_path):
        """``__init__`` and other dunders are excluded from class-method
        scanning to avoid the universal ``__init__`` noise."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "class SharedClass:\n"
            "    def __init__(self):\n"
            "        self.x = 1\n"
        )
        (hooks / "hook_a.py").write_text(body, encoding="utf-8")
        (hooks / "hook_b.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        dunders = [
            c for c in report.cliques
            if c.name == "SharedClass.__init__" or c.name == "__init__"
        ]
        assert dunders == [], (
            "Dunder methods should be excluded from class-method clique "
            f"detection; got {len(dunders)} cliques: {dunders}"
        )

    def test_constant_clique_3_site_fires_warn(self, tmp_path):
        """Three modules with the same-name same-value constant fire WARN."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "SHARED_SET = {\"a\", \"b\", \"c\"}\n"
        )
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [
            c for c in report.constant_cliques if c.name == "SHARED_SET"
        ]
        assert len(cliques) == 1, (
            f"Expected one SHARED_SET clique; got {len(cliques)}: "
            f"{report.constant_cliques}"
        )
        clique = cliques[0]
        assert clique.severity == "WARN"
        assert not clique.divergent
        assert len(clique.sites) == 3

    def test_constant_clique_2_site_fires_info(self, tmp_path):
        """Two modules with the same-name same-value constant fire INFO."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "SHARED_LIST = [1, 2, 3]\n"
        )
        for name in ("hook_a", "hook_b"):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [
            c for c in report.constant_cliques if c.name == "SHARED_LIST"
        ]
        assert len(cliques) == 1
        assert cliques[0].severity == "INFO"
        assert not cliques[0].divergent

    def test_constant_clique_divergent_marked_divergent(self, tmp_path):
        """Two modules with the same-name DIFFERENT-value constant: divergent."""
        hooks = _make_hooks_tree(tmp_path)
        (hooks / "hook_a.py").write_text(
            "SHARED_DICT = {\"k\": 1}\n", encoding="utf-8")
        (hooks / "hook_b.py").write_text(
            "SHARED_DICT = {\"k\": 2}\n", encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [
            c for c in report.constant_cliques if c.name == "SHARED_DICT"
        ]
        assert len(cliques) == 1
        assert cliques[0].divergent, (
            "Same-name different-value constants should be divergent"
        )

    def test_constant_opt_out_marker_suppresses(self, tmp_path):
        """``# sister-site: ok <reason>`` above the constant suppresses."""
        hooks = _make_hooks_tree(tmp_path)
        body = (
            "# sister-site: ok deliberate dup for synthetic test\n"
            "SHARED_FROZEN = frozenset({\"a\", \"b\"})\n"
        )
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        cliques = [
            c for c in report.constant_cliques if c.name == "SHARED_FROZEN"
        ]
        assert cliques == [], (
            f"Opt-out marker should suppress constant clique; got "
            f"{len(cliques)} cliques"
        )

    def test_alias_miss_message_names_opt_out_and_no_leading_dot(self, tmp_path):
        """The ALIAS-MISS remediation names the ``# sister-site: ok`` escape
        (the legitimate out for a deliberate/conventional alias), and a
        single-component ``import numpy as np`` renders ``numpy`` — not
        ``.numpy`` (an empty ``rhs_module`` must not leave a leading dot)."""
        import sister_site_probe as ssp

        hooks = _make_hooks_tree(tmp_path)
        (hooks / "conv_hook.py").write_text(
            "import numpy as np\n", encoding="utf-8"
        )
        report = probe_compression_debt([tmp_path])
        assert report.alias_misses, (
            "fixture should produce an alias-miss for `import numpy as np`"
        )
        text = ssp._format_report_text(report, include_info=False)
        assert "`numpy`" in text and "`.numpy`" not in text, (
            f"single-component import should render `numpy`, not `.numpy`:\n{text}"
        )
        assert "# sister-site: ok" in text, (
            f"remediation should name the opt-out escape:\n{text}"
        )


@pytest.mark.security
class TestConceptOverlapDetection:
    """The concept-overlap detector: two str-element sets with DIFFERENT names
    whose elements overlap by containment >= K. Advisory-only (never gates)."""

    @staticmethod
    def _espalier(tmp_path: Path) -> Path:
        d = tmp_path / "espalier"
        d.mkdir(parents=True)
        return d

    def test_wide_and_narrow_subset_fire_one_cluster(self, tmp_path):
        """A wide dotted set + a narrow un-dotted near-subset, divergent names,
        cluster into exactly one concept-overlap — containment catches the
        near-subset that Jaccard (5/15) would miss, and ``.py`` == ``py`` after
        normalization."""
        esp = self._espalier(tmp_path)
        (esp / "wide.py").write_text(
            'WIDE_EXTS = {".py", ".md", ".json", ".toml", ".yaml", ".txt"}\n',
            encoding="utf-8",
        )
        (esp / "narrow.py").write_text(
            'NARROW_EXTS = {"py", "md", "json", "toml"}\n', encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        assert len(report.concept_overlaps) == 1, (
            f"Expected one concept-overlap cluster; got "
            f"{len(report.concept_overlaps)}"
        )
        names = {s.name for s in report.concept_overlaps[0].members}
        assert names == {"WIDE_EXTS", "NARROW_EXTS"}

    def test_disjoint_sets_do_not_cluster(self, tmp_path):
        """Two disjoint 5-element sets share nothing → no concept-overlap."""
        esp = self._espalier(tmp_path)
        (esp / "a.py").write_text(
            'SET_A = {"aaa", "bbb", "ccc", "ddd", "eee"}\n', encoding="utf-8",
        )
        (esp / "b.py").write_text(
            'SET_B = {"fff", "ggg", "hhh", "iii", "jjj"}\n', encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        assert report.concept_overlaps == ()

    def test_derived_set_self_heals(self, tmp_path):
        """Deriving the narrow set via a comprehension (not a literal) makes the
        advisory disappear — an ast.SetComp is not a collected literal, so no
        whack-a-mole once a duplicate is fixed by deriving from the canon."""
        esp = self._espalier(tmp_path)
        (esp / "wide.py").write_text(
            'WIDE_EXTS = {".py", ".md", ".json", ".toml", ".yaml", ".txt"}\n',
            encoding="utf-8",
        )
        (esp / "narrow.py").write_text(
            "from espalier.wide import WIDE_EXTS\n"
            "NARROW_EXTS = {e[1:] for e in WIDE_EXTS}\n",
            encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        assert report.concept_overlaps == (), (
            "A comprehension-derived set is an ast.SetComp, not a literal, so it "
            "must not be a concept-overlap candidate."
        )

    def test_concept_overlap_is_advisory_not_blocking(self, tmp_path):
        """A seeded concept-overlap keeps the probe's exit at 0 — the finding is
        advisory (excluded from has_debt). Alias-misses, by contrast, now gate."""
        import sister_site_probe

        esp = self._espalier(tmp_path)
        (esp / "wide.py").write_text(
            'WIDE_EXTS = {".py", ".md", ".json", ".toml", ".yaml", ".txt"}\n',
            encoding="utf-8",
        )
        (esp / "narrow.py").write_text(
            'NARROW_EXTS = {"py", "md", "json", "toml"}\n', encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        assert len(report.concept_overlaps) == 1
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 0, (
            f"concept-overlap must not gate; got exit {exit_code}"
        )


@pytest.mark.security
class TestDelegatingCliqueCalibration:
    """A clique of one-line delegations to a shared owner is not debt.

    The probe's blocking rule was ``WARN and not divergent`` — which fires on
    N sites whose bodies are all ``return owner(arg)``. Those sites are the
    *result* of compression, not the absence of it: the logic lives once, in
    the owner, and each module keeps a local name for it. Counting them as
    debt makes the probe demand that a caller un-delegate.

    Measured on this repo at the time of writing: both blocking cliques
    (``_load_json`` x5, ``_safe_text`` x3) were this shape, so the gate's
    false-positive rate on the live corpus was 2 of 2.
    """

    def test_delegating_clique_does_not_gate(self, tmp_path):
        """Three modules aliasing one owner keep the probe's exit at 0."""
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(
                "from _owner import load_report_json\n"
                "def _load_json(path):\n"
                "    return load_report_json(path)\n",
                encoding="utf-8",
            )

        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 0, (
            "A clique whose every site is a one-line call to the SAME shared "
            f"owner is already compressed; got exit {exit_code}"
        )

    def test_delegating_clique_is_still_reported(self, tmp_path):
        """Excluded from the gate, but never silently dropped."""
        hooks = _make_hooks_tree(tmp_path)
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(
                "from _owner import load_report_json\n"
                "def _load_json(path):\n"
                "    return load_report_json(path)\n",
                encoding="utf-8",
            )

        report = probe_compression_debt([tmp_path])
        cliques = [c for c in report.cliques if c.name == "_load_json"]
        assert len(cliques) == 1, "the clique must still appear in the report"
        assert cliques[0].delegating is True, (
            "a clique of one-line calls to one shared owner must be marked "
            "delegating so the reason it does not gate is legible"
        )

    def test_documented_delegation_is_still_a_delegation(self, tmp_path):
        """A docstring is not logic, so it must not hide the delegation.

        Regression: the delegation check read `len(body) != 1` while the body
        HASH stripped a leading docstring first. Five real sites that were all
        `return load_report_json(path)` therefore hashed identical (not
        divergent) while only the undocumented ones read as delegating, so the
        clique kept gating. Caught by driving the live repo, not by the
        synthetic cases above -- none of which had a docstring.
        """
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        bodies = [
            'from _owner import load_report_json\n'
            'def _load_json(path):\n'
            '    """Best-effort loader for sidecar reports."""\n'
            '    return load_report_json(path)\n',
            'from _owner import load_report_json\n'
            'def _load_json(path):\n'
            '    return load_report_json(path)\n',
            'from _owner import load_report_json\n'
            'def _load_json(path):\n'
            '    # a comment is not a statement\n'
            '    return load_report_json(path)\n',
        ]
        for name, body in zip(("hook_a", "hook_b", "hook_c"), bodies):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        clique = [c for c in report.cliques if c.name == "_load_json"][0]
        assert clique.delegating is True, (
            "a docstring above the delegating return must not mask it"
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 0, f"expected advisory; got exit {exit_code}"

    def test_real_duplication_still_gates(self, tmp_path):
        """Control: the fix must not disarm the detector it calibrates."""
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        body = (
            "def _classify(rec):\n"
            "    total = 0\n"
            "    for k in rec:\n"
            "        total += len(k)\n"
            "    return total\n"
        )
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(body, encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        clique = [c for c in report.cliques if c.name == "_classify"][0]
        assert clique.delegating is False, (
            "a genuinely duplicated multi-statement body is not a delegation"
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, (
            f"real duplication must still gate; got exit {exit_code}"
        )

    def test_builtin_wrapper_clique_still_gates(self, tmp_path):
        """A builtin target is not a shared owner, so it must not excuse.

        The exclusion rests on the duplication having MOVED to the target,
        which the clique pass then judges on its own merits. A builtin has no
        clique to move it to, so the one-line wrapper IS the duplicated thing.
        Found by attacking the first version of this fix, which exited 0 here.
        """
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(
                "def _norm(x):\n    return dict(x)\n", encoding="utf-8",
            )

        report = probe_compression_debt([tmp_path])
        clique = [c for c in report.cliques if c.name == "_norm"][0]
        assert clique.delegating is False, (
            "`dict` is a builtin, not a shared owner this repo defines"
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, f"expected gate; got exit {exit_code}"

    def test_locally_defined_target_is_not_a_shared_owner(self, tmp_path):
        """A target bound by a local `def` is a PER-FILE owner, not a shared one.

        Three files each defining their own `_helper` and forwarding to it are
        three owners, not one. Under a name-only rule this exited 0 while the
        probe simultaneously printed those `_helper`s as DIVERGENT -- the
        report contradicting itself in a single frame.
        """
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        for i, name in enumerate(("hook_a", "hook_b", "hook_c")):
            (hooks / f"{name}.py").write_text(
                "def _helper(x):\n"
                f"    return len(x) + {i}\n"
                "\n"
                "def _entry(x):\n"
                "    return _helper(x)\n",
                encoding="utf-8",
            )

        report = probe_compression_debt([tmp_path])
        entry = [c for c in report.cliques if c.name == "_entry"][0]
        assert entry.delegating is False, (
            "`_helper` is defined locally in each file, so it names three "
            "owners, not one shared owner"
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, f"expected gate; got exit {exit_code}"

    def test_logic_inside_call_arguments_is_not_a_delegation(self, tmp_path):
        """Logic that rides along inside the parentheses is still logic.

        Five byte-identical copies of a comprehension, a generator-sum and an
        arithmetic expression -- living nowhere else -- were measured exiting
        0 while the report claimed "the logic already lives once".
        """
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        for name in ("hook_a", "hook_b", "hook_c", "hook_d", "hook_e"):
            (hooks / f"{name}.py").write_text(
                "from _owner import _weighted\n"
                "def _severity_rank(items):\n"
                "    return _weighted(\n"
                "        {i.name: i.count for i in items if i.count > 3},\n"
                "        base=sum(len(i.tags) for i in items) or 1,\n"
                "    )\n",
                encoding="utf-8",
            )

        report = probe_compression_debt([tmp_path])
        clique = [c for c in report.cliques if c.name == "_severity_rank"][0]
        assert clique.delegating is False, (
            "a comprehension and a generator-sum in the argument list are "
            "duplicated logic, not a pass-through"
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, f"expected gate; got exit {exit_code}"

    def test_target_that_is_a_parameter_is_not_a_delegation(self, tmp_path):
        """`def _apply(fn, x): return fn(x)` names no owner at all."""
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(
                "def _apply(fn, x):\n    return fn(x)\n", encoding="utf-8",
            )

        report = probe_compression_debt([tmp_path])
        clique = [c for c in report.cliques if c.name == "_apply"][0]
        assert clique.delegating is False
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, f"expected gate; got exit {exit_code}"

    def test_self_named_call_is_not_a_delegation(self, tmp_path):
        """``return _helper(x)`` inside ``_helper`` compresses nothing."""
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        for name in ("hook_a", "hook_b", "hook_c"):
            (hooks / f"{name}.py").write_text(
                "def _helper(x):\n    return _helper(x)\n", encoding="utf-8",
            )

        report = probe_compression_debt([tmp_path])
        clique = [c for c in report.cliques if c.name == "_helper"][0]
        assert clique.delegating is False, (
            "a call to the clique's OWN name names no shared owner"
        )
        exit_code = sister_site_probe.main(["--root", str(tmp_path), "--json"])
        assert exit_code == 2, f"expected gate; got exit {exit_code}"


_MARKER = "# espalier:managed v0.0.0 sha256:0000\n"


def _make_adopter_tree(tmp_path: Path) -> Path:
    """An adopter's tree as ``init`` leaves it, in miniature: MARKED hooks
    (one canonical ``_hook_utils.py`` plus two hooks that body-match it --
    Espalier's own compression debt, deployed verbatim) and an empty
    ``src/pkg/`` for the adopter's code. Returns ``src/pkg``."""
    hooks = tmp_path / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "_hook_utils.py").write_text(
        _MARKER + "def normalize_path(p):\n    return p.replace('\\\\', '/')\n",
        encoding="utf-8",
    )
    for name in ("write_guard", "plan_guard"):
        (hooks / f"{name}.py").write_text(
            _MARKER + "def _norm(p):\n    return p.replace('\\\\', '/')\n",
            encoding="utf-8",
        )
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    return src


def _plant_clique(src: Path, *names: str) -> None:
    for name in names:
        (src / f"{name}.py").write_text(
            "def helper():\n    return 42\n", encoding="utf-8",
        )


@pytest.mark.security
class TestAdopterScope:
    """DEF-673: on an adopter tree the gate is THEIR duplicates, never the
    harness's; the report says whose code it read and what it skipped.

    Every case drives ``main`` -- the exit code is the contract step 0-C
    reads -- and reads the same report through the library API.
    """

    def test_adopter_clique_gates_and_harness_debt_does_not(self, tmp_path, capsys):
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        _plant_clique(src, "a", "b", "c")

        report = probe_compression_debt([tmp_path])
        assert report.scope is not None and report.scope.mode == "adopter"
        assert [c.name for c in report.cliques] == ["helper"]
        assert report.canon_misses == (), (
            "the deployed hooks' canon-miss leaked into the ADOPTER's findings"
        )
        assert report.harness_internal is not None
        assert {m.shadow_file for m in report.harness_internal.canon_misses} == {
            "tools/cc/hooks/plan_guard.py", "tools/cc/hooks/write_guard.py",
        }
        assert report_has_debt(report) is True
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 2
        out = capsys.readouterr().out
        assert "SCOPE: adopter tree" in out
        assert "HARNESS-INTERNAL (advisory, never gates this run)" in out
        assert "re-implements `normalize_path`" in out

    def test_harness_debt_alone_exits_zero(self, tmp_path, capsys):
        """The defect as driven on a wheel install: rc=2 on debt the adopter
        cannot edit. Now the deployed hooks' canon-misses are listed and the
        exit code ignores them."""
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        (src / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        assert report_has_debt(report) is False
        assert report.harness_internal is not None
        assert report_has_debt(report.harness_internal) is True, (
            "fixture drift: the planted harness canon-miss is gone, so this "
            "test no longer proves harness debt is ignored by the gate"
        )
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 0
        captured = capsys.readouterr()
        assert "CANON-MISS  tools/cc/hooks/plan_guard.py" in captured.out
        assert "not gating" in captured.err

    def test_adopter_import_alias_is_not_rename_drift(self, tmp_path):
        """``import numpy as np`` is idiom, not the harness's rename-drift
        class; the alias-miss arm runs only over harness files."""
        src = _make_adopter_tree(tmp_path)
        (src / "app.py").write_text(
            "import numpy as np\nfrom os import path as p\n", encoding="utf-8",
        )
        report = probe_compression_debt([tmp_path])
        assert report.alias_misses == ()
        assert report_has_debt(report) is False

    def test_scope_says_what_was_scanned_and_pruned(self, tmp_path, capsys):
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        (src / "app.py").write_text("X = 1\n", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("X = 1\n", encoding="utf-8")
        (tmp_path / ".venv" / "lib").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "junk.py").write_text("X = 1\n", encoding="utf-8")

        assert sister_site_probe.main(["--root", str(tmp_path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        scope = payload["scope"]
        assert scope["mode"] == "adopter"
        assert scope["explicit_roots"] is False
        assert scope["roots"] == ["."]
        assert scope["scanned"] == ["src/pkg/app.py"]
        assert scope["scanned_count"] == 1
        assert set(scope["pruned"]) == {".venv/", "tests/", "tools/cc/"}
        assert scope["harness_files"] == [
            "tools/cc/hooks/plan_guard.py", "tools/cc/hooks/write_guard.py",
        ]
        assert payload["has_debt"] is False
        assert payload["harness_internal"]["has_debt"] is True
        assert payload["harness_internal"]["scope"] is None

    def test_scanned_nothing_is_said_out_loud(self, tmp_path, capsys):
        """A tree with no Python source in scope: rc 0, but the report says
        it never looked -- the original DEF-673 lie was a silent rc 0."""
        import sister_site_probe

        _make_adopter_tree(tmp_path)  # src/pkg exists but is empty
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("X = 1\n", encoding="utf-8")

        assert sister_site_probe.main(["--root", str(tmp_path)]) == 0
        captured = capsys.readouterr()
        assert "SCANNED NOTHING" in captured.out
        assert "says nothing about your code" in captured.out
        assert "[scope] adopter: 0 file(s)" in captured.err
        assert "SCANNED NOTHING" in captured.err
        assert (captured.out + captured.err).isascii(), "rendered output must be 7-bit ASCII"
        # The --json consumer (step 0-C) gets the same fact as a key, not prose.
        assert sister_site_probe.main(["--root", str(tmp_path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["scanned_nothing"] is True and payload["has_debt"] is False

    def test_self_host_shape_with_nothing_to_scan_is_loud_too(self, tmp_path, capsys):
        """An engine dir with no modules and an empty hooks tree: self-host
        mode, zero files. Used to print ``0 file(s)`` then CLEAN (failure-mode
        pass)."""
        import sister_site_probe

        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 0
        captured = capsys.readouterr()
        assert "SCOPE: harness source tree -- 0 file(s)" in captured.out
        assert "SCANNED NOTHING" in captured.out
        assert "says nothing about this tree" in captured.out
        assert "point the probe at it with --roots" in captured.out
        assert (captured.out + captured.err).isascii(), "rendered output must be 7-bit ASCII"

    def test_scanned_nothing_under_explicit_roots_does_not_prescribe_roots(self, tmp_path, capsys):
        """``--roots docs`` on the source tree: the remedy used to tell the
        operator to do what they had just done (failure-mode pass, round two)."""
        import sister_site_probe

        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.md").write_text("# x\n", encoding="utf-8")
        assert sister_site_probe.main(["--root", str(tmp_path), "--roots", "docs"]) == 0
        captured = capsys.readouterr()
        assert "SCANNED NOTHING" in captured.out
        assert "the --roots you named hold no .py source" in captured.out
        assert "point the probe at it with --roots" not in captured.out
        assert (captured.out + captured.err).isascii()

    def test_adopter_report_never_points_at_hook_utils(self, tmp_path, capsys):
        """The remediation for an identical constant clique used to say
        "promote to _hook_utils.X" four lines above the tail that says
        write_guard keeps that file read-only."""
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        for name in ("a", "b", "c"):
            (src / f"{name}.py").write_text(
                'DEFAULT_EXCLUDE = ["build", "dist", "node_modules", ".git"]\n',
                encoding="utf-8",
            )
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 2
        out = capsys.readouterr().out
        assert "CONSTANT-CLIQUE WARN" in out
        assert "one shared module" in out
        assert "_hook_utils" not in out

    def test_concept_overlap_only_report_is_not_clean(self, tmp_path, capsys):
        """Advisory, no exit-code impact -- but a report whose only content
        is a concept overlap printed CLEAN and dropped the section."""
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        elems = '"alpha", "beta", "gamma", "delta", "epsilon"'
        for name, const in (("a", "SKIP_DIRS"), ("b", "IGNORE_DIRS"), ("c", "EXCLUDE_DIRS")):
            (src / f"{name}.py").write_text(f"{const} = {{{elems}}}\n", encoding="utf-8")
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "CONCEPT-OVERLAP" in out
        assert "CLEAN --" not in out

    def test_self_host_roots_say_they_bypass_the_scope_outs(self, tmp_path, capsys):
        """``--roots`` on the source tree WIDENS into deliberately scoped-out
        code (espalier/scanners/); the SCOPE block must say so."""
        import sister_site_probe

        (tmp_path / "espalier" / "scanners").mkdir(parents=True)
        (tmp_path / "espalier" / "scanners" / "x.py").write_text("X = 1\n", encoding="utf-8")
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        assert sister_site_probe.main(["--root", str(tmp_path), "--roots", "espalier"]) == 0
        out = capsys.readouterr().out
        assert "note: --roots bypasses the self-host scope-outs" in out

    def test_roots_narrow_the_gating_scope(self, tmp_path):
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        _plant_clique(src, "a", "b", "c")
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "clean.py").write_text("X = 1\n", encoding="utf-8")

        assert sister_site_probe.main(["--root", str(tmp_path), "--roots", "lib"]) == 0
        assert sister_site_probe.main(["--root", str(tmp_path), "--roots", "src"]) == 2
        report = probe_compression_debt([tmp_path], scan_roots=(Path("lib"),))
        assert report.scope is not None and report.scope.explicit_roots is True
        assert report.scope.roots == ("lib/",)
        assert report.scope.scanned == ("lib/clean.py",)

    def test_bad_roots_exit_one_not_clean(self, tmp_path, capsys):
        """A typo'd root must not read as a clean run."""
        import sister_site_probe

        _make_adopter_tree(tmp_path)
        assert sister_site_probe.main(["--root", str(tmp_path), "--roots", "nope"]) == 1
        assert "does not exist" in capsys.readouterr().err
        outside = tmp_path.parent
        assert sister_site_probe.main(
            ["--root", str(tmp_path), "--roots", str(outside)],
        ) == 1
        assert "outside --root" in capsys.readouterr().err

    def test_info_only_report_still_prints_clean(self, tmp_path, capsys):
        """A 2-site clique prints only with --include-info; hiding it used to
        hide the CLEAN line too, leaving a bare header."""
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        _plant_clique(src, "a", "b")
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "CLEAN" in out
        assert "1 2-site INFO clique(s) hidden" in out
        assert sister_site_probe.main(["--root", str(tmp_path), "--include-info"]) == 0
        out = capsys.readouterr().out
        assert "INFO cliques (1 -- 2 sites)" in out
        assert "hidden" not in out

    def test_pre_marker_install_gates_on_their_code_not_the_hooks(self, tmp_path, capsys):
        """Unmarked hooks with REAL harness debt and no engine package: an
        adopter whose hooks predate the marker. Their code is the gate; the
        hooks' canon-miss is advisory. (The code-reviewer drove the inverse
        on the first cut of this change: rc=2, mode=self-host.)"""
        import sister_site_probe

        src = _make_adopter_tree(tmp_path)
        for p in (tmp_path / "tools" / "cc" / "hooks").glob("*.py"):
            p.write_text(p.read_text(encoding="utf-8").replace(_MARKER, ""), encoding="utf-8")
        (src / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")

        report = probe_compression_debt([tmp_path])
        assert report.scope is not None and report.scope.mode == "adopter"
        assert report.canon_misses == ()
        assert report.harness_internal is not None
        assert report_has_debt(report.harness_internal) is True
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 0
        assert "HARNESS-INTERNAL" in capsys.readouterr().out

    def test_engine_beside_unmarked_hooks_is_the_source_tree(self, tmp_path, capsys):
        """Same files plus the engine package: now it is the harness's own
        tree and its debt gates, exactly as before this change."""
        import sister_site_probe

        _make_adopter_tree(tmp_path)
        for p in (tmp_path / "tools" / "cc" / "hooks").glob("*.py"):
            p.write_text(p.read_text(encoding="utf-8").replace(_MARKER, ""), encoding="utf-8")
        (tmp_path / "espalier").mkdir()

        report = probe_compression_debt([tmp_path])
        assert report.scope is not None and report.scope.mode == "self-host"
        assert report.harness_internal is None
        assert {m.shadow_file for m in report.canon_misses} == {
            "tools/cc/hooks/plan_guard.py", "tools/cc/hooks/write_guard.py",
        }
        assert sister_site_probe.main(["--root", str(tmp_path)]) == 2
        assert "HARNESS-INTERNAL" not in capsys.readouterr().out

    def test_self_host_shape_carries_no_harness_section(self, tmp_path, capsys):
        """Unmarked hooks beside the engine package are the source tree (and
        every other fixture in this file): one scope, everything gates, no
        advisory tail."""
        import sister_site_probe

        hooks = _make_hooks_tree(tmp_path)
        (hooks / "hook_a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        report = probe_compression_debt([tmp_path])
        assert report.scope is not None and report.scope.mode == "self-host"
        assert report.harness_internal is None
        sister_site_probe.main(["--root", str(tmp_path)])
        out = capsys.readouterr().out
        assert "SCOPE: harness source tree" in out
        assert "HARNESS-INTERNAL" not in out
