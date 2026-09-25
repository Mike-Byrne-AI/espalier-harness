"""TP-124: independent scaffolding-quality canon contract tests.

Pins the de-circularization the New TP/TP-124 rejection identified
and that TP-124 v1's BLOCK confirmed: quality metrics for scaffolding
must NOT route through the same surface walker the scaffolding shapes
the agent toward. Without these contracts, a future refactor could
silently route the canon through `espalier.reflect_protocol` (or any
walker participant) and recreate the closed-loop trap that the canon
is the entire reason for existing — agreement between canon and
walker would then become consistency, not correctness. See
docs/SHARP_EDGES.md "Closed-Loop Verification Trap" and
docs/CONVENTIONS.md "scaffolding-quality canon".
"""
from __future__ import annotations

import ast
import io
import json
import tokenize
from dataclasses import asdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CANON_PATH = REPO_ROOT / "espalier" / "scaffolding_canon.py"


class TestIndependentImports:
    """Pin de-circularization: scaffolding_canon must not import any
    module that participates in /reflect's surface walker.

    AST walk (not substring) — substring would false-fire on the
    docstring + FORBIDDEN_IMPORTS frozenset literals naming the
    modules. The negative-proof subtest (`test_negative_proof_check_fires`)
    catches the silent failure mode where the AST walker no longer
    detects forbidden imports (test passes for the wrong reason).
    """

    def test_no_forbidden_imports(self):
        from espalier.scaffolding_canon import FORBIDDEN_IMPORTS

        src = CANON_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in FORBIDDEN_IMPORTS, (
                    f"scaffolding_canon imported forbidden module "
                    f"{node.module!r}; de-circularization broken. The "
                    f"canon must NOT route through any /reflect walker "
                    f"participant — otherwise it measures itself."
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in FORBIDDEN_IMPORTS, (
                        f"scaffolding_canon imported forbidden module "
                        f"{alias.name!r}; de-circularization broken."
                    )

    def test_negative_proof_check_fires(self):
        """Confirm the walker would catch a regression by checking a
        synthetic bad module. Without this, the positive test could pass
        because the walker silently no-ops (e.g., wrong node type checked,
        FORBIDDEN_IMPORTS empty), giving false confidence."""
        from espalier.scaffolding_canon import FORBIDDEN_IMPORTS

        bad_src = "from espalier.models import ReflectPass\n"
        tree = ast.parse(bad_src)
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module in FORBIDDEN_IMPORTS:
                    violations.append(node.module)
        assert violations == ["espalier.models"], (
            "negative-proof failed: the AST walker did not catch a "
            "synthetic forbidden import. TestIndependentImports gives "
            "false confidence — it would silently pass on a real "
            "regression."
        )

    def test_forbidden_set_pins_six_walker_modules(self):
        """The FORBIDDEN_IMPORTS frozenset itself is part of the
        contract — if a future edit shrinks it, the AST walker has
        fewer modules to check and the canon could import a newly
        un-forbidden walker module without tripping. The architecture-
        analyst survey identified exactly these 6 walker participants;
        all 6 must be enumerated."""
        from espalier.scaffolding_canon import FORBIDDEN_IMPORTS

        expected = frozenset({
            "espalier.reflect_protocol",
            "espalier.reflection",
            "espalier.models",
            "espalier.cognitive_blueprint",
            "espalier.cli",
            "espalier.doctor",
        })
        assert FORBIDDEN_IMPORTS == expected, (
            f"FORBIDDEN_IMPORTS drifted from the 6-module walker map. "
            f"Missing: {expected - FORBIDDEN_IMPORTS}. "
            f"Unexpected: {FORBIDDEN_IMPORTS - expected}. Any change "
            f"requires re-running the architecture-analyst walker survey."
        )


class TestNoLLMCalls:
    """Pin the stays-out-of-LLM-judge constraint. The rejected
    `New TP/TP-122` proposed Anthropic-API-in-PreToolUse; TP-124 is the
    *opposite* design — purely structural signals from persisted data.
    If a future edit imports any LLM client, the canon stops being
    falsifiable from deterministic inputs and the methodology collapses
    silently. Catches both AST-import form and string-form evasion."""

    BANNED = ("anthropic", "openai", "httpx", "requests", "urllib3")

    def test_no_llm_imports_in_canon(self):
        tree = ast.parse(CANON_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                assert root not in self.BANNED, (
                    f"scaffolding_canon imported LLM client "
                    f"{node.module!r}; the canon must remain stdlib-only "
                    f"and deterministic from persisted data."
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    assert root not in self.BANNED, (
                        f"scaffolding_canon imported LLM client "
                        f"{alias.name!r}; canon must remain stdlib-only."
                    )

    def test_no_string_form_llm_evasion(self):
        """Catch `importlib.import_module('anthropic')` and friends —
        string-form imports that hide from AST checks. Strips comments
        and docstrings via `tokenize` so legitimate docstring mentions
        of "anthropic" don't trip the scan."""
        text = CANON_PATH.read_text(encoding="utf-8")
        code_only_chunks: list[str] = []
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except tokenize.TokenizeError:
            tokens = []
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.string.startswith(('"""', "'''")):
                continue
            code_only_chunks.append(tok.string)
        code_only = " ".join(code_only_chunks)
        for banned in self.BANNED:
            assert banned not in code_only, (
                f"scaffolding_canon code-only text contains {banned!r} — "
                f"likely a string-form LLM import evasion that AST checks "
                f"would miss. Canon must remain deterministic."
            )


class TestRawJSONLoading:
    """Pin the raw-load discipline: scaffolding_canon must read
    `cc/blueprints/*.json` directly via `json.load`, NOT through any
    `espalier.cognitive_blueprint` loader (which is in FORBIDDEN_IMPORTS
    for the import-level contract, but a future refactor could pull the
    loader into a non-forbidden module and bypass the AST check). This
    test asserts the call shape independently — the canon source must
    contain `json.load(...)` and must NOT contain any call to a
    cognitive_blueprint loader."""

    def test_uses_json_load_directly(self):
        tree = ast.parse(CANON_PATH.read_text(encoding="utf-8"))
        json_load_call_sites = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in ("load", "loads")
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "json"
                ):
                    json_load_call_sites += 1
        assert json_load_call_sites >= 1, (
            "scaffolding_canon must call json.load or json.loads "
            "directly on raw blueprint files; without this the canon "
            "could silently route through espalier.cognitive_blueprint's "
            "loaders (which is the closed-loop trap the canon exists to "
            "prevent)."
        )

    def test_no_cognitive_blueprint_loader_calls(self):
        """Even if a future refactor moved the loader out of
        `espalier.cognitive_blueprint`, calling it by its method name
        would still be the closed-loop trap. Scan for any `Call(...)`
        whose attribute name matches the known loader API."""
        forbidden_call_names = {
            "load_chain",
            "load_blueprint",
            "iter_blueprints",
            "iter_session_blueprints",
            "iter_blueprint_chain",
        }
        tree = ast.parse(CANON_PATH.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_call_names:
                    offenders.append(func.attr)
                elif isinstance(func, ast.Name) and func.id in forbidden_call_names:
                    offenders.append(func.id)
        assert not offenders, (
            f"scaffolding_canon called cognitive_blueprint loader-shape "
            f"functions: {offenders}. Even via a non-forbidden import, "
            f"this is the closed-loop trap — the canon must consume only "
            f"raw JSON via json.load."
        )


# pins: claim:scaffolding-signal-1-threshold
class TestSignalContinuity:
    """Signal 1 is the load-bearing 1-hop continuity metric. The shape
    measured: for each (S, S+1), what fraction of S's
    continuation_fragments (curated at S's finalize as priming for S+1)
    appear as substrings in S+1's reasoning_entries text? In other
    words: did S+1 actually write reasoning about the topics S handed
    forward? Without this contract, a refactor could silently reverse
    the direction (S.reasoning ∈ S+1.fragments — the v1 pack draft's
    formula) which is structurally impossible to satisfy because
    S+1.fragments come from S+1's own reasoning, not S's. The 124-G
    live-fire validation caught this exact mistake mid-execution."""

    def test_returns_half_when_two_of_four_fragments_match_current(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": [
            "[decision] " + "A" * 60,
            "[pattern] " + "B" * 60,
            "[unresolved] " + "C" * 60,
            "[converged] " + "D" * 60,
        ]}
        current = {"reasoning_entries": [
            {"description": "A" * 60 + " extra context"},
            {"description": "B" * 60 + " extra context"},
            {"description": "totally different topic 1"},
            {"description": "totally different topic 2"},
        ]}
        s = _signal_1_continuity([prior, current])
        assert s.value == 0.5
        assert s.sample_size == 1

    def test_returns_null_when_no_pair_has_prior_fragments(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": []}
        current = {"reasoning_entries": [{"description": "whatever"}]}
        s = _signal_1_continuity([prior, current])
        assert s.value is None
        assert s.sample_size == 0
        assert "no pairs" in s.notes

    def test_empty_body_fragment_does_not_inflate_score(self):
        """TP-176 W4-3: a bare-prefix (empty-body) continuation fragment must
        not count as a trivial match (`'' in current_text` is always True).
        Here one real fragment is unmatched and one is an empty-body prefix —
        the score must be 0.0, not 0.5."""
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": [
            "[decision] ",                 # empty body — must be skipped
            "[pattern] " + "Z" * 60,       # real body, unmatched below
        ]}
        current = {"reasoning_entries": [
            {"description": "an unrelated topic with no Z-run"},
        ]}
        s = _signal_1_continuity([prior, current])
        assert s.value == 0.0, f"empty-body fragment inflated score: {s.value}"
        assert s.sample_size == 1

    def test_all_empty_body_fragments_pair_is_skipped(self):
        """A pair whose only fragments have empty bodies has nothing usable to
        measure — it contributes no score rather than a spurious 1.0/0.0."""
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": ["[decision] ", "[warning] "]}
        current = {"reasoning_entries": [{"description": "anything"}]}
        s = _signal_1_continuity([prior, current])
        assert s.value is None
        assert s.sample_size == 0

    def test_averages_across_multiple_pairs(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        bp1 = {"continuation_fragments": [],
               "reasoning_entries": []}
        bp2 = {"continuation_fragments": ["[decision] " + "X" * 60],
               "reasoning_entries": []}
        bp3 = {"continuation_fragments": ["[decision] " + "Y" * 60],
               "reasoning_entries": [{"description": "X" * 60 + " carried"}]}
        bp4 = {"continuation_fragments": [],
               "reasoning_entries": [{"description": "didnt carry Y"}]}
        s = _signal_1_continuity([bp1, bp2, bp3, bp4])
        # pair (bp1, bp2): bp1 has no fragments → skip
        # pair (bp2, bp3): bp2 fragment X×60 IS in bp3 reasoning → 1/1
        # pair (bp3, bp4): bp3 fragment Y×60 NOT in bp4 reasoning → 0/1
        # average: (1.0 + 0.0) / 2 = 0.5
        assert s.value == 0.5
        assert s.sample_size == 2

    def test_strips_tag_prefix_before_matching(self):
        """Auto fragments come with `[decision] `, `[pattern] `, etc.
        prefixes added at finalize. S+1's reasoning_entries don't carry
        those prefixes — comparison must strip before substring match,
        otherwise the metric is always 0 due to prefix mismatch."""
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": [
            "[decision] TP-X shipped: full description here",
        ]}
        current = {"reasoning_entries": [
            {"description": "TP-X shipped: full description here and more"},
        ]}
        s = _signal_1_continuity([prior, current])
        assert s.value == 1.0


class TestSignalContinuityHandlesBlueprintWithoutReasoning:
    """Edge case: when S+1 has no `reasoning_entries` key, score must
    be 0.0 (matched=0 over non-zero fragment count) — not None and not
    a KeyError. Without this contract, a v1 schema-shape edit that
    removed the key would crash the canon mid-chain instead of cleanly
    reporting "S+1 wrote nothing referencing S's handoff"."""

    def test_zero_score_when_reasoning_key_missing(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": ["[decision] anything"]}
        current = {}  # no reasoning_entries key at all
        s = _signal_1_continuity([prior, current])
        assert s.value == 0.0
        assert s.sample_size == 1


# pins: claim:scaffolding-signal-2-threshold
class TestSignalHumanDensity:
    """Signal 2 is meaningless if [subagent: autorecords aren't
    filtered — the repo-analyst survey found recent latest.json had
    5 reasoning_entries all of which were subagent autorecords. Without
    the prefix filter, the metric reports "ritual recording" not
    "human reasoning" and silently looks healthy on dead-from-human-
    input sessions."""

    def test_returns_three_when_two_of_five_are_subagent_autorecords(self):
        from espalier.scaffolding_canon import _signal_2_human_density

        bp = {"reasoning_entries": [
            {"description": "[subagent:code-reviewer] found 3 issues"},
            {"description": "human decision to ship v0.7.9"},
            {"description": "[subagent:repo-analyst] surfaced drift"},
            {"description": "human pattern: autoprune date-aware"},
            {"description": "human: investigated TP-124 v1 BLOCK"},
        ]}
        s = _signal_2_human_density([bp])
        assert s.value == 3.0
        assert s.sample_size == 1

    def test_zero_fraction_reported(self):
        from espalier.scaffolding_canon import _signal_2_human_density

        # 4 sessions: 2 with zero human entries (all subagent), 2 with some
        bps = [
            {"reasoning_entries": [{"description": "[subagent:x] auto"}]},
            {"reasoning_entries": [{"description": "[subagent:y] auto"}]},
            {"reasoning_entries": [{"description": "human thing"}]},
            {"reasoning_entries": [
                {"description": "human a"},
                {"description": "human b"},
            ]},
        ]
        s = _signal_2_human_density(bps)
        assert "zero_fraction=0.50" in s.notes


# pins: claim:scaffolding-signal-3-threshold
class TestSignalReflectCoverage:
    """Signal 3 reports coverage ONLY — never reads inside reflect_passes
    (gap_count / cross_ref_density / findings). Reading those would
    close the loop with the surface walker; reading only "did /reflect
    fire" preserves independence. Without this contract, a well-meaning
    refactor that aggregated `gap_count` for "richer signal" would
    silently re-introduce the closed-loop trap."""

    def test_returns_three_tenths_for_ten_chain_with_three_non_empty(self):
        from espalier.scaffolding_canon import _signal_3_reflect_coverage

        chain = [
            {"reflect_passes": [{"x": 1}]} if i < 3 else {"reflect_passes": []}
            for i in range(10)
        ]
        s = _signal_3_reflect_coverage(chain)
        assert s.value == 0.3
        assert s.sample_size == 10


class TestEmptyChainGracefulNull:
    """When `cc/blueprints/` is empty (fresh-clone state), the canon
    must report n_sessions=0 and all signals None — not raise.
    Without this contract, an adopter running `espalier
    scaffolding-bench` immediately after `espalier init .` would hit a
    crash before any blueprints exist; the failure mode is
    "tool appears broken to first-time user"."""

    def test_empty_blueprints_dir_returns_null_signals(self, tmp_path):
        from espalier.scaffolding_canon import compute_canon

        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        report = compute_canon(tmp_path, last_n=20)
        assert report.n_sessions == 0
        assert report.signal_1_continuity.value is None
        assert report.signal_2_human_density.value is None
        assert report.signal_3_reflect_coverage.value is None
        assert report.per_session == []

    def test_missing_blueprints_dir_returns_null_signals(self, tmp_path):
        from espalier.scaffolding_canon import compute_canon

        report = compute_canon(tmp_path, last_n=20)
        assert report.n_sessions == 0
        assert report.signal_1_continuity.value is None

    def test_report_is_json_serializable(self, tmp_path):
        """Adopters use `--json` to feed the canon into downstream
        tools. The CanonReport dataclass + asdict must produce a
        round-trippable JSON payload — without this, --json crashes
        silently on first run."""
        from espalier.scaffolding_canon import compute_canon

        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        report = compute_canon(tmp_path, last_n=20)
        payload = asdict(report)
        round_trip = json.loads(json.dumps(payload))
        assert round_trip["n_sessions"] == 0

    def test_load_tolerates_non_dict_and_off_type_blueprints(self, tmp_path):
        """TP-170 §7a (Class-B) + §7a-followup: a valid-JSON NON-dict blueprint
        must be skipped (not crash the `.get` sort key), and a dict blueprint
        whose accumulated_depth/timestamp is the wrong TYPE must not crash the
        sort with an uncaught heterogeneous-comparison TypeError. Both were
        fail-opens (AttributeError / TypeError escaping past the load except)."""
        from espalier.scaffolding_canon import _load_blueprints_raw

        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "a.json").write_text(
            json.dumps({"accumulated_depth": 2, "timestamp": "2026-01-02"}), encoding="utf-8")
        (bp_dir / "b.json").write_text(
            json.dumps({"accumulated_depth": "oops", "timestamp": None}), encoding="utf-8")
        (bp_dir / "c.json").write_text(
            json.dumps({"accumulated_depth": None, "timestamp": 42}), encoding="utf-8")
        (bp_dir / "d.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")  # non-dict
        out = _load_blueprints_raw(tmp_path, last_n=20)  # must not raise
        assert len(out) == 3  # the non-dict d.json is skipped (§7a)


class TestSignal1PrefixGrammarPin:
    """FM-16 close (TP-144): the set of prefixes emitted by the
    continuation-fragments emitter in ``cmd_finalize`` MUST all conform
    to the ``[tag] body`` shape that ``_signal_1_continuity``'s split
    recognizes (``f.split("] ", 1)[-1]`` at scaffolding_canon.py:100).

    Pins the prefix grammar against the producer. If a future TP
    introduces a new tag form (e.g., ``[blueprint::rationale]:body``
    with ``:`` separator), this test catches the asymmetry before the
    canon silently goes blind to that fragment shape.

    Why source-grep rather than runtime invocation: the emitter is
    inline in ``cmd_finalize`` (tools/cc/cognitive_blueprint.py around
    lines 359-372), not a named importable function. Driving it
    requires a synthetic blueprint, a writable tmp directory, and a
    write-lock dance -- all just to recover hardcoded literals from the
    source. Reading the source text and matching ``frags.append("[...] ...")``
    literals is the structurally honest binding: producer-source =
    consumer-source.
    """

    _RECOGNIZED_SEPARATOR = "] "
    _DOCUMENTED_PREFIXES = (
        "[decision] ", "[pattern] ", "[unresolved] ",
        "[warning] ", "[converged] ",
    )

    def test_every_documented_prefix_matches_split_shape(self) -> None:
        """Each documented prefix must start with ``[`` and contain
        ``] `` so the split at scaffolding_canon.py:100 recovers the
        body. Self-check on the _DOCUMENTED_PREFIXES tuple itself."""
        for prefix in self._DOCUMENTED_PREFIXES:
            assert (
                prefix.startswith("[")
                and self._RECOGNIZED_SEPARATOR in prefix
            ), (
                f"Documented prefix {prefix!r} does not match the "
                f"`[tag] body` shape Signal 1 expects."
            )

    def test_emitter_prefixes_match_split_shape(self) -> None:
        """Walk the cmd_finalize source; for every
        ``frags.append(...)`` whose appended string begins with ``[``,
        assert the literal contains ``] `` separator. Catches a future
        tag form that uses a different separator (``:``, no-space,
        etc.) before the canon silently goes blind.

        Producer is ``tools/cc/cognitive_blueprint.py::cmd_finalize``
        (the fragment-building inline loop). Consumer is
        ``espalier/scaffolding_canon.py::_signal_1_continuity`` (the
        split at line 100). They MUST share the prefix grammar.
        """
        import re

        producer = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"
        source = producer.read_text(encoding="utf-8")
        # Capture ONLY the `[<tag>] ` prefix portion (bracket + word +
        # bracket + space). The f-expression body that follows often
        # contains nested quote chars (e.g., `d['description']`), so
        # capturing the full string literal would trip on those quotes
        # -- we don't need the body, only the prefix grammar.
        pattern = re.compile(
            r'''frags\.append\(\s*f?["'](\[\w+\]\s)''',
            re.MULTILINE,
        )
        emitted_prefixes = pattern.findall(source)
        assert emitted_prefixes, (
            "Emitter scan recovered zero "
            "`frags.append(f\"[<tag>] ...\")` calls. The regex "
            "assumption is broken -- check that cmd_finalize still "
            "uses `frags.append(...)` with bracketed prefix literals."
        )
        # Every captured prefix must contain `] ` so the consumer's
        # split shape recovers the body. Guaranteed by the regex shape
        # but asserted explicitly so a future loosening of the regex
        # doesn't quietly drop this guarantee.
        for prefix in emitted_prefixes:
            assert self._RECOGNIZED_SEPARATOR in prefix, (
                f"Emitted prefix {prefix!r} lacks "
                f"{self._RECOGNIZED_SEPARATOR!r} -- "
                f"`_signal_1_continuity` will not strip the prefix and "
                f"the body match falls through to verbatim text. Either "
                f"use the `[tag] body` shape consistently OR widen the "
                f"split shape in scaffolding_canon.py:100 (and update "
                f"this test's _RECOGNIZED_SEPARATOR)."
            )
        # Belt + suspenders: every documented prefix must appear in the
        # emitter source (catches a producer that silently drops a
        # category like `[unresolved]` after a refactor).
        emitted_set = set(emitted_prefixes)
        for documented in self._DOCUMENTED_PREFIXES:
            assert documented in emitted_set, (
                f"Documented prefix {documented!r} not found in "
                f"emitter source. Either the producer dropped this "
                f"category OR the _DOCUMENTED_PREFIXES tuple is stale "
                f"relative to cmd_finalize. Emitted: "
                f"{sorted(emitted_set)}"
            )


class TestSignalsToleratesOffTypeNestedFields:
    """TP-174b T06: the signal functions deref nested
    ``reasoning_entries`` / ``continuation_fragments`` — a malformed
    blueprint with an off-type value there must degrade, not crash."""

    def test_signal_2_tolerates_off_type_reasoning_entries(self):
        from espalier.scaffolding_canon import _signal_2_human_density
        # non-list reasoning_entries, and a list with a non-dict entry —
        # both crashed e.get(...).startswith pre-fix.
        _signal_2_human_density([{"reasoning_entries": "not-a-list"}])
        _signal_2_human_density([{"reasoning_entries": ["str-entry"]}])
        # present-but-None description: .get("description","") returns None
        # (not the "" default), which crashed None.startswith pre-fix.
        _signal_2_human_density([{"reasoning_entries": [{"description": None}]}])
        _signal_2_human_density([{"reasoning_entries": [{"description": 7}]}])

    def test_signal_1_tolerates_off_type_nested_fields(self):
        from espalier.scaffolding_canon import _signal_1_continuity
        # off-type reasoning_entries on the "current" side, and a non-string
        # fragment (int) on the "prior" side — both crashed pre-fix.
        _signal_1_continuity([
            {"continuation_fragments": ["[d] " + "X" * 60]},
            {"reasoning_entries": "oops"},
        ])
        _signal_1_continuity([
            {"continuation_fragments": [123]},
            {"reasoning_entries": [{"description": "x"}]},
        ])
        # present-but-None description on the "current" side crashed the
        # str.join pre-fix (TypeError: expected str, got NoneType).
        _signal_1_continuity([
            {"continuation_fragments": ["[d] " + "X" * 60]},
            {"reasoning_entries": [{"description": None}]},
        ])

    def test_per_session_row_tolerates_off_type_counts(self):
        """TP-192 W3-4: ``_per_session_row`` called ``len()`` on
        reasoning_entries / continuation_fragments / reflect_passes with no list
        guard — a present-but-non-list value (``continuation_fragments: 42``)
        crashed compute_canon with an uncaught TypeError. The one deref site the
        T06 sweep skipped. Treat a non-list as len 0."""
        from espalier.scaffolding_canon import _per_session_row

        row = _per_session_row({
            "session_id": "s",
            "continuation_fragments": 42,     # not a list
            "reasoning_entries": "oops",      # not a list
            "reflect_passes": None,           # not a list
        })
        assert row["n_continuation_fragments"] == 0
        assert row["n_reasoning_entries"] == 0
        assert row["n_reflect_passes"] == 0

    def test_compute_canon_tolerates_off_type_session(self, tmp_path):
        """compute_canon must not crash on a blueprint with off-type count
        fields (the integrating path through _per_session_row)."""
        from espalier.scaffolding_canon import compute_canon

        bp = tmp_path / "cc" / "blueprints"
        bp.mkdir(parents=True)
        (bp / "20260101-000000-aaaaaa.json").write_text(
            json.dumps({"session_id": "s", "continuation_fragments": 42}),
            encoding="utf-8",
        )
        report = compute_canon(tmp_path)  # pre-fix: TypeError in len()
        assert report.per_session


def test_scaffolding_bench_out_outside_repo_does_not_crash(tmp_path):
    """TP-174b: `scaffolding-bench --out <abs path outside repo>` must print
    the absolute path and exit 0, not crash on out_json.relative_to(repo_root)
    (ValueError → "malformed data" rc=1 pre-fix, after writing the artifacts)."""
    import subprocess
    import sys
    repo = tmp_path / "repo"
    (repo / "cc" / "blueprints").mkdir(parents=True)
    (repo / ".git").mkdir()
    outside = tmp_path / "outside.json"
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "scaffolding-bench",
         "--repo", str(repo), "--out", str(outside)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "[ok] wrote" in result.stdout


class TestSchemaParity:
    """Guard docs/schemas/scaffolding_canon.schema.json against silent drift
    from the CanonReport/Signal dataclasses that CLI `scaffolding-bench`
    serializes via `asdict`.

    The schema is otherwise only prose-pinned (docs/CONVENTIONS.md
    'scaffolding-quality canon'); nothing loaded it at runtime, so a field
    added to or removed from the dataclasses would leave the schema wrong
    with no test to notice. This asserts the emitted key sets equal the
    schema's declared `properties` at all three levels — hermetically
    (constructed dataclasses, no live-blueprint dependency, works at
    n_sessions == 0)."""

    SCHEMA = REPO_ROOT / "docs" / "schemas" / "scaffolding_canon.schema.json"

    def _payload(self) -> dict:
        from espalier.scaffolding_canon import (
            CanonReport,
            Signal,
            _per_session_row,
        )

        sig = Signal(
            name="continuity_1hop", value=None, sample_size=0, notes=""
        )
        report = CanonReport(
            n_sessions=0,
            signal_1_continuity=sig,
            signal_2_human_density=sig,
            signal_3_reflect_coverage=sig,
            # a non-empty row so the per_session item keys are observable
            # regardless of how many blueprints exist on disk.
            per_session=[_per_session_row({})],
        )
        return asdict(report)

    def test_top_level_keys_match_schema(self):
        schema = json.loads(self.SCHEMA.read_text(encoding="utf-8"))
        emitted = set(self._payload().keys())
        declared = set(schema["properties"].keys())
        assert emitted == declared, (
            f"scaffolding_canon report top-level keys drifted from schema.\n"
            f"  emitted-not-declared: {sorted(emitted - declared)}\n"
            f"  declared-not-emitted: {sorted(declared - emitted)}\n"
            f"Update docs/schemas/scaffolding_canon.schema.json to match "
            f"CanonReport."
        )
        # every declared required key must actually be emitted
        assert set(schema.get("required", [])) <= emitted

    def test_signal_keys_match_schema(self):
        schema = json.loads(self.SCHEMA.read_text(encoding="utf-8"))
        sig_schema = schema["$defs"]["signal"]
        declared = set(sig_schema["properties"].keys())
        payload = self._payload()
        for key in (
            "signal_1_continuity",
            "signal_2_human_density",
            "signal_3_reflect_coverage",
        ):
            emitted = set(payload[key].keys())
            assert emitted == declared, (
                f"{key} keys drifted from schema $defs/signal.\n"
                f"  emitted-not-declared: {sorted(emitted - declared)}\n"
                f"  declared-not-emitted: {sorted(declared - emitted)}\n"
                f"Update docs/schemas/scaffolding_canon.schema.json to match "
                f"the Signal dataclass."
            )
        assert set(sig_schema.get("required", [])) <= declared

    def test_per_session_row_keys_match_schema(self):
        schema = json.loads(self.SCHEMA.read_text(encoding="utf-8"))
        item_schema = schema["properties"]["per_session"]["items"]
        declared = set(item_schema["properties"].keys())
        emitted = set(self._payload()["per_session"][0].keys())
        assert emitted == declared, (
            f"per_session row keys drifted from schema.\n"
            f"  emitted-not-declared: {sorted(emitted - declared)}\n"
            f"  declared-not-emitted: {sorted(declared - emitted)}\n"
            f"Update docs/schemas/scaffolding_canon.schema.json to match "
            f"_per_session_row."
        )
        assert set(item_schema.get("required", [])) <= declared


class TestSignalContinuityIgnoresAgentReports:
    """Since 2026-09-11 `cmd_finalize` carries up to two `[subagent:<type>]`
    report fragments (an agent's final-message lead) into S's
    continuation_fragments. Signal 1 asks whether S+1 re-engaged with what S
    handed forward; an agent's lead is not S's curated reasoning, and a
    formulaic lead (`APPROVE. Nothing to change.`) recurs verbatim when S+1
    dispatches the same reviewer, so counting it would re-arm the
    marker-matching-marker self-noise the 2026-08-16b filter removed
    (inflation) and penalise S+1 for not restating a reviewer's verdict
    (deflation). Both directions driven."""

    def test_a_recurring_agent_lead_does_not_inflate(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": [
            "[decision] " + "A" * 60,
            "[subagent:code-reviewer] APPROVE. Nothing to change.",
        ]}
        current = {"reasoning_entries": [
            {"description": "[subagent:code-reviewer] APPROVE. Nothing to change."},
            {"description": "an unrelated topic"},
        ]}
        s = _signal_1_continuity([prior, current])
        assert s.value == 0.0, f"a reviewer's boilerplate matched itself: {s.value}"

    def test_an_unrestated_agent_lead_does_not_deflate(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": [
            "[decision] " + "A" * 60,
            "[subagent:failure-mode-reviewer] two GAPs, one ROUGH-EDGE, both closed in-lane",
        ]}
        current = {"reasoning_entries": [{"description": "A" * 60 + " carried forward"}]}
        s = _signal_1_continuity([prior, current])
        assert s.value == 1.0, f"S+1 was penalised for not restating a reviewer: {s.value}"

    def test_a_pair_with_only_agent_leads_is_skipped(self):
        from espalier.scaffolding_canon import _signal_1_continuity

        prior = {"continuation_fragments": ["[subagent:code-reviewer] APPROVE. Nothing to change."]}
        current = {"reasoning_entries": [{"description": "anything"}]}
        s = _signal_1_continuity([prior, current])
        assert s.value is None and s.sample_size == 0


class TestScaffoldingBenchWriteHygiene:
    """DEF-567 (TP-449 Tier 2, 2026-09-12): the verb wrote three report files
    plus a new timestamped snapshot on EVERY run, with nothing to report
    included -- driven on a fresh init tree: two runs, zero sessions, two
    snapshots. Now: the current json/md are rewritten only when their bytes
    change, a snapshot lands only for a report that differs from the newest
    one, and never when there is nothing to report; the printed line says
    which happened. The args come from the parser, not a hand-built Namespace.
    """

    def _run(self, repo: Path, capsys) -> tuple[int, str]:
        from espalier.cli import build_parser, cmd_scaffolding_bench
        args = build_parser().parse_args(["scaffolding-bench", str(repo)])
        rc = cmd_scaffolding_bench(args)
        return rc, capsys.readouterr().out

    @staticmethod
    def _blueprint(repo: Path, name: str, depth: int) -> None:
        bp_dir = repo / "cc" / "blueprints"
        bp_dir.mkdir(parents=True, exist_ok=True)
        (bp_dir / f"{name}.json").write_text(json.dumps({
            "session_id": name, "accumulated_depth": depth,
            "timestamp": f"2026-09-12T00:00:0{depth}",
            "reasoning_entries": [{"description": "a human note"}],
            "continuation_fragments": [], "reflect_passes": [],
        }), encoding="utf-8")

    def test_nothing_to_report_writes_the_report_and_no_snapshot(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        rc, out = self._run(tmp_path, capsys)
        assert rc == 0, out
        assert (tmp_path / "reports" / "scaffolding_canon.json").is_file()
        assert (tmp_path / "reports" / "scaffolding_canon.md").is_file()
        assert not (tmp_path / "reports" / "scaffolding_canon").exists(), (
            "a snapshot was written for a report with nothing in it"
        )
        assert "[ok] wrote" in out and "nothing to report" in out, out
        assert "no readable blueprint" in out, out

    def test_a_rerun_with_nothing_new_rewrites_nothing(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        self._run(tmp_path, capsys)
        current = tmp_path / "reports" / "scaffolding_canon.json"
        summary = tmp_path / "reports" / "scaffolding_canon.md"
        before = (current.stat().st_mtime_ns, current.read_bytes(),
                  summary.stat().st_mtime_ns, summary.read_bytes())
        rc, out = self._run(tmp_path, capsys)
        assert rc == 0, out
        assert (current.stat().st_mtime_ns, current.read_bytes(),
                summary.stat().st_mtime_ns, summary.read_bytes()) == before, (
            "an unchanged report was rewritten"
        )
        assert "[ok] unchanged" in out, out
        assert not (tmp_path / "reports" / "scaffolding_canon").exists()

    def test_the_summary_regenerated_alone_is_a_write(self, tmp_path, capsys):
        """The verb reads both files: a missing .md put back is `wrote`."""
        (tmp_path / ".git").mkdir()
        self._run(tmp_path, capsys)
        (tmp_path / "reports" / "scaffolding_canon.md").unlink()
        rc, out = self._run(tmp_path, capsys)
        assert rc == 0 and "[ok] wrote" in out, out
        assert (tmp_path / "reports" / "scaffolding_canon.md").is_file()

    def test_unreadable_blueprints_are_not_called_absent(self, tmp_path, capsys):
        """Four states read as zero sessions; the note is true of all four."""
        (tmp_path / ".git").mkdir()
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "latest.json").write_text("{}", encoding="utf-8")
        (bp_dir / "session_a.json").write_text("{not json", encoding="utf-8")
        rc, out = self._run(tmp_path, capsys)
        assert rc == 0 and "no readable blueprint" in out, out
        assert "no blueprints" not in out, out

    def test_the_collision_suffix_sorts_after_its_stamp(self, tmp_path):
        """`_newest_snapshot` reads newest by name; the same-second suffix
        must sort AFTER the bare stamp (`_` > `.`), or the older payload is
        read as newest and every run snapshots again."""
        from espalier.cli import _newest_snapshot
        history = tmp_path / "scaffolding_canon"
        history.mkdir()
        stamp = "20260912T000000Z"
        (history / f"{stamp}.json").write_text("1", encoding="utf-8")
        (history / f"{stamp}_2.json").write_text("2", encoding="utf-8")
        assert f"{stamp}_2.json" > f"{stamp}.json"
        newest = _newest_snapshot(history)
        assert newest is not None and newest.name == f"{stamp}_2.json", newest

    def test_one_snapshot_per_distinct_report(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        history = tmp_path / "reports" / "scaffolding_canon"
        self._blueprint(tmp_path, "a", 1)
        rc, out = self._run(tmp_path, capsys)
        assert rc == 0 and "snapshot " in out, out
        assert len(list(history.glob("*.json"))) == 1
        rc, out = self._run(tmp_path, capsys)
        assert len(list(history.glob("*.json"))) == 1, "a second run with nothing new added a snapshot"
        assert "no snapshot: unchanged since" in out, out
        self._blueprint(tmp_path, "b", 2)
        rc, out = self._run(tmp_path, capsys)
        assert len(list(history.glob("*.json"))) == 2, "a changed report earned no snapshot"
        assert "snapshot " in out, out

    def test_the_json_arm_writes_nothing(self, tmp_path, capsys):
        from espalier.cli import build_parser, cmd_scaffolding_bench
        (tmp_path / ".git").mkdir()
        args = build_parser().parse_args(["scaffolding-bench", str(tmp_path), "--json"])
        assert cmd_scaffolding_bench(args) == 0
        assert not (tmp_path / "reports").exists()
