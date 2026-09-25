"""Accuracy-audit subsystem contracts.

Pins the claim-extractor, verification-dispatch, and orchestrator
behaviors that make `espalier audit` a trustworthy gate. Without this
suite the audit can silently regress to false-positive ("all clean")
or false-negative ("everything broken"), and the audit's job is exactly
to be the trustworthy signal — drift here defeats the gate's purpose.

Coverage:
- Claim extractor: pattern matching, mode classification, exclusion rules.
- Verification dispatch: live_repo paths run mechanically (no LLM); the
  external_pin path invokes the injected `dispatch` callable; unknown
  modes degrade to unverifiable.
- Orchestrator: counts, exit-code contract, JSON/markdown rendering,
  --no-llm mode (zero LLM calls).
- LLM dispatch path: mocked via dependency injection; we never make a
  real LLM call from a unit test.

Stem `test_audit_accuracy` registers under `unit` by default in
conftest.py; nothing here calls subprocesses.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


from espalier.audit_accuracy import (
    ClaimVerdict,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_UNVERIFIABLE,
    audit_accuracy,
    build_context,
    render_json,
    render_markdown,
    verify_claim,
)
from espalier.claim_extractor import (
    Claim,
    DEFAULT_DOC_GLOBS,
    EXCLUDED_DOC_GLOBS,
    MODE_EXTERNAL_PIN,
    MODE_LIVE_REPO,
    MODE_UNKNOWN,
    _claim_id,
    _classify_all,
    extract_claims,
)
from espalier.external_pins import ExternalPin


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Test fixtures ───────────────────────────────────────────────────


def _scaffold_repo(root: Path,
                    *,
                    hooks: int = 9,
                    agents: int = 6,
                    commands: int = 14,
                    skills: int = 6,
                    bypass_classes: int = 11) -> None:
    """Create the minimal repo shape the mechanical verifiers count against.

    Defaults track the live surface; update when a command/skill/agent/hook
    is added or removed so future fixture-default usage stays calibrated.
    """
    # TP-174a S1: _live_count_hooks now counts only canonical-roster names, so
    # synthetic h{i}.py names no longer count. Lay down real canonical names.
    from espalier.surface_contract import get_canonical_hook_scripts
    _canonical = get_canonical_hook_scripts()
    (root / "tools" / "cc" / "hooks").mkdir(parents=True)
    for i in range(hooks):
        name = _canonical[i] if i < len(_canonical) else f"h{i}.py"
        (root / "tools" / "cc" / "hooks" / name).write_text("# hook\n", encoding="utf-8")
    (root / ".claude" / "agents").mkdir(parents=True)
    for i in range(agents):
        (root / ".claude" / "agents" / f"a{i}.md").write_text(
            f"---\nname: a{i}\ndescription: x\n---\n", encoding="utf-8"
        )
    (root / ".claude" / "commands").mkdir()
    for i in range(commands):
        (root / ".claude" / "commands" / f"c{i}.md").write_text("# c\n", encoding="utf-8")
    (root / ".claude" / "skills").mkdir()
    for i in range(skills):
        (root / ".claude" / "skills" / f"s{i}").mkdir()
        (root / ".claude" / "skills" / f"s{i}" / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    (root / "bench" / "corpus").mkdir(parents=True)
    for i in range(bypass_classes):
        (root / "bench" / "corpus" / f"BC-{i:03d}-x.json").write_text("{}", encoding="utf-8")


def _write_doc(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── Claim extractor ─────────────────────────────────────────────────


class TestClaimExtractor:
    def test_extracts_numerical_hook_claim(self, tmp_path):
        _write_doc(tmp_path, "README.md", "Init deploys 9 hooks.\n")
        claims = extract_claims(tmp_path, doc_globs=["README.md"])
        assert len(claims) == 1
        assert claims[0].pattern == "num_hooks"
        assert claims[0].suggested_mode == MODE_LIVE_REPO

    def test_combined_count_line_extracts_all_nouns(self, tmp_path):
        """TP-176 W4-4: a line stating multiple counts must yield one claim
        per noun, not just the first. Pre-fix, only `num_agents` was extracted
        from a combined "8 agents, 15 commands, 10 skills" line, so the entire
        num_skills audit path got zero inputs."""
        _write_doc(
            tmp_path, "docs/QUICKSTART.md",
            "We ship 8 agents, 15 commands, 10 skills.\n",
        )
        claims = extract_claims(tmp_path, doc_globs=["docs/QUICKSTART.md"])
        patterns = {c.pattern for c in claims}
        assert {"num_agents", "num_commands", "num_skills"} <= patterns, (
            f"combined count line dropped nouns: {sorted(patterns)}"
        )

    def test_combined_line_stale_count_fails_audit(self, tmp_path):
        """TP-176 W4-4 end-to-end: a stale count sharing a combined line with
        correct counts must FAIL the audit. Pre-fix it passed clean because the
        stale noun's claim was never extracted (first-match-wins)."""
        from espalier.audit_accuracy import VERDICT_FAIL, audit_accuracy
        _scaffold_repo(tmp_path, agents=6, commands=14, skills=6)
        # agents/commands correct; skills stale (says 10, repo has 6).
        _write_doc(
            tmp_path, "docs/QUICKSTART.md",
            "We ship 6 agents, 14 commands, 10 skills.\n",
        )
        report = audit_accuracy(tmp_path, doc_globs=["docs/QUICKSTART.md"])
        fails = [v for v in report.verdicts if v.verdict == VERDICT_FAIL]
        assert len(fails) == 1, (
            f"expected exactly the stale skills count to fail; got {fails}"
        )

    def test_extracts_protocol_terms(self, tmp_path):
        _write_doc(tmp_path, "SHARP_EDGES.md",
                   "Hooks must use exit 2 to block; stdout is read.\n")
        claims = extract_claims(tmp_path, doc_globs=["SHARP_EDGES.md"])
        assert any(c.suggested_mode == MODE_EXTERNAL_PIN for c in claims)

    def test_extracts_schema_field_mentions(self, tmp_path):
        _write_doc(tmp_path, "CLAUDE.md",
                   "Returns a permissionDecision in the response.\n")
        claims = extract_claims(tmp_path, doc_globs=["CLAUDE.md"])
        patterns = {c.pattern for c in claims}
        assert "protocol_schema" in patterns

    def test_skips_external_pin_dir(self, tmp_path):
        _write_doc(tmp_path, "docs/external/cc-hook-protocol.md",
                   "## A\n\n8 hooks per session.\n")
        # Default globs include docs/*.md but EXCLUDED_DOC_GLOBS removes
        # docs/external/. The extractor must not pull claims from pins.
        claims = extract_claims(tmp_path, doc_globs=["docs/*.md"])
        assert claims == []

    def test_skips_code_blocks(self, tmp_path):
        _write_doc(tmp_path, "README.md",
                   "Run this:\n\n```\nThe code mentions 9 hooks.\n```\n\nDone.\n")
        claims = extract_claims(tmp_path, doc_globs=["README.md"])
        assert claims == []

    def test_skips_tilde_code_blocks(self, tmp_path):
        """TP-174b R21: ~~~ tilde fences toggle code-block skipping too,
        not just backtick fences."""
        _write_doc(tmp_path, "README.md",
                   "Run this:\n\n~~~\nThe code mentions 9 hooks.\n~~~\n\nDone.\n")
        claims = extract_claims(tmp_path, doc_globs=["README.md"])
        assert claims == []

    def test_skips_range_claims(self, tmp_path):
        _write_doc(tmp_path, "design.md", "Use 3-6 agents typically.\n")
        claims = extract_claims(tmp_path, doc_globs=["design.md"])
        assert claims == []

    def test_skips_per_minute_false_positive(self, tmp_path):
        _write_doc(tmp_path, "README.md", "Handles 5000 commands per minute.\n")
        claims = extract_claims(tmp_path, doc_globs=["README.md"])
        assert claims == []

    def test_claim_id_is_stable_across_runs(self):
        a = _claim_id("README.md", 42, "9 hooks installed")
        b = _claim_id("README.md", 42, "9 hooks installed")
        assert a == b
        assert len(a) == 12

    def test_default_globs_exclude_external_pins(self):
        assert "docs/external/*.md" in EXCLUDED_DOC_GLOBS
        assert "docs/external/*.md" not in DEFAULT_DOC_GLOBS

    def test_internal_narrative_docs_excluded(self):
        """TP-190: internal-classified narrative docs (never shipped to adopters)
        must not be audited as public-doc claims — their counts are point-in-time
        and SoT-pinned elsewhere. REDEFINED joined its already-excluded siblings."""
        for rel in (
            "docs/REDEFINED_INFORMATION_REGISTRY.md",
            "docs/RELEASE_FINDINGS_LEDGER.md",
        ):
            assert rel in EXCLUDED_DOC_GLOBS, f"{rel} must be audit-excluded"

    def test_excluded_doc_claims_not_extracted_end_to_end(self, tmp_path):
        """TP-191 W7: end-to-end proof that EXCLUDED_DOC_GLOBS membership actually
        suppresses extraction. The SAME claim-shaped line in an excluded internal-
        narrative doc and a non-excluded doc must yield a claim from the
        non-excluded doc ONLY. The pre-fix coverage was a constant-membership
        check that would still pass even if the exclusion were never wired into
        extract_claims's file enumeration."""
        from espalier.claim_extractor import extract_claims
        claim_line = "Espalier governs 10 hook scripts.\n"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "REDEFINED_INFORMATION_REGISTRY.md").write_text(
            claim_line, encoding="utf-8"
        )
        (docs / "CONVENTIONS.md").write_text(claim_line, encoding="utf-8")
        locations = [c.location for c in extract_claims(tmp_path)]
        # Control: the same line in a non-excluded doc IS extracted (so a
        # not-found result below means "excluded", not "unextractable").
        assert any(loc.startswith("docs/CONVENTIONS.md") for loc in locations), (
            f"control claim not extracted — test line is not extractable: {locations}"
        )
        assert not any(
            loc.startswith("docs/REDEFINED_INFORMATION_REGISTRY.md")
            for loc in locations
        ), f"excluded doc's claims were extracted end-to-end: {locations}"

    def test_classify_returns_none_for_non_claim_line(self):
        # TP-204g: _classify was a runtime-dead wrapper; inline its first-match-
        # or-None semantics onto _classify_all (no match -> empty list -> falsy).
        assert not _classify_all("This is just narrative prose.")

    def test_fraction_near_hook_not_extracted_as_count(self, tmp_path):
        """TP-53 M11: ``3/4 hook stdin parsers`` historically extracted
        ``4 hooks`` because the bare ``\\b`` regex boundary fires between
        ``/`` and a digit. Post-fix the negative lookbehind ``(?<![/0-9])``
        skips both N/M denominators AND mid-number digit splits. The
        verbatim docs/session-archive.md:13 phrasing is the regression
        anchor.
        """
        from espalier.audit_accuracy import extract_count_for_label
        line = (
            "UnicodeDecodeError uncaught in 3/4 hook stdin parsers; "
            "vacuous assert recurrence elsewhere."
        )
        result = extract_count_for_label(line, "hooks")
        assert result is None, (
            f"N/M denominator near 'hook' must not be extracted as a "
            f"count claim; got {result!r}"
        )

    def test_simple_count_still_extracts(self):
        from espalier.audit_accuracy import extract_count_for_label
        # The lookbehind must not over-reject normal claims.
        assert extract_count_for_label("9 hooks installed", "hooks") == 9
        assert extract_count_for_label("ten hooks", "hooks") is None
        assert extract_count_for_label("the 14 commands", "commands") == 14

    def test_adjective_slot_is_load_bearing_for_doctor(self):
        """TP-313b ITEM E (deferred as net-negative): the verifier's optional
        adjective slot is intentionally looser than claim_extractor's bare-noun
        form. doctor._check_doc_drift extracts adjective-phrased live counts
        through it — README's "45 in-scope bypass classes" resolves to 45 only
        because of the slot. Dropping it (to close the latent two-number
        divergence) would SILENTLY regress this live extraction from 45 to None.
        This locks the keep-the-slot decision so a future refactor cannot drop
        the slot without going red here."""
        from espalier.audit_accuracy import extract_count_for_label
        # The exact live README.md line doctor feeds under label "bypass classes".
        assert extract_count_for_label(
            "Tested against 45 in-scope bypass classes (plus 9 documented",
            "bypass classes",
        ) == 45

    def test_adjective_slot_does_not_overmatch_roster_nouns(self):
        """TP-217b: the num_agents/commands/skills patterns dropped the open
        adjective slot that turned 'chmod 444 on agent files' into a VERDICT_FAIL
        ('444 agents'). The strict bare-noun form must extract ZERO claims for
        prose where a number sits one adjective/preposition away from the roster
        noun."""
        overmatch_inputs = [
            "We provide 3 specialized agents",
            "Set chmod 444 on agent files",
            "chmod 444 on agent files",
            "run 9 background commands now",
            "10 extra skills available",
        ]
        for text in overmatch_inputs:
            live = [c for c in _classify_all(text) if c[0] == "live_repo"]
            assert live == [], (
                f"{text!r} still classifies as a live_repo count claim: {live}. "
                f"The adjective slot re-opened the chmod-444 false-positive class."
            )

        # Recall floor: bare-noun roster claims STILL classify (the fix must not
        # silence legitimate pinned counts).
        for text, noun in [("8 agents", "num_agents"),
                           ("12 commands", "num_commands"),
                           ("9 skills", "num_skills")]:
            names = {name for _mode, name in _classify_all(text)}
            assert noun in names, f"{text!r} no longer classifies as {noun}: {names}"


# ── TP-58 BC-029: Unicode-digit defeat ─────────────────────────────


class TestUnicodeDigitDefeat:
    """Pre-TP-58, ``\\d+`` in the extractor regex matched Unicode
    digit forms — fullwidth ASCII (U+FF10..U+FF19), NBSP-adjacent
    splits — so a doc containing ``" 4 hooks"`` (fullwidth 4)
    extracted ``4`` and triggered a false claim. The fix swaps
    ``\\d+`` for ``[0-9]+`` (ASCII-only) and adds ``re.ASCII`` for
    belt-and-suspenders on the lookbehind word boundaries.
    """

    def test_fullwidth_digit_rejected(self):
        from espalier.audit_accuracy import extract_count_for_label
        # U+FF14 = FULLWIDTH DIGIT FOUR. Written as \uXXXX so the
        # source is readable; the codepoint is what matters.
        fullwidth_four = "\uff14"
        text = f"{fullwidth_four} hooks installed"
        assert extract_count_for_label(text, "hooks") is None, (
            "fullwidth digit U+FF14 must not match [0-9]+; got non-None"
        )

    def test_fullwidth_multi_digit_rejected(self):
        from espalier.audit_accuracy import extract_count_for_label
        # Fullwidth "14"
        text = "\uff11\uff14 hooks"
        assert extract_count_for_label(text, "hooks") is None

    def test_nbsp_between_digit_and_label_rejected(self):
        from espalier.audit_accuracy import extract_count_for_label
        # NBSP (U+00A0) between digits and label. ``re.ASCII`` makes
        # ``\\s`` reject NBSP (Unicode whitespace), so the count
        # token does not bind to the label across an NBSP.
        text = "4\u00a0hooks"
        assert extract_count_for_label(text, "hooks") is None

    def test_fraction_denominator_still_rejected(self):
        from espalier.audit_accuracy import extract_count_for_label
        # Pre-existing TP-53 M11 exclusion must still hold.
        text = "uncaught in 2/4 hooks"
        assert extract_count_for_label(text, "hooks") is None


# ── TP-58 F5: alphabetic / dot-prefix defeat ───────────────────────


class TestVersionPrefixDefeat:
    """Pre-TP-58, the lookbehind ``(?<![/0-9])`` only excluded ASCII
    digits and ``/``. A version-string prefix like ``"v10 hooks"`` or
    a dotted token like ``"v.10 hooks"`` slipped through and extracted
    ``10`` as a hook count. The fix widens the lookbehind to
    ``(?<![./0-9A-Za-z])``.
    """

    def test_v_prefix_rejected(self):
        from espalier.audit_accuracy import extract_count_for_label
        assert extract_count_for_label("v10 hooks", "hooks") is None

    def test_dotted_prefix_rejected(self):
        from espalier.audit_accuracy import extract_count_for_label
        # Round-2 round added the dot to the lookbehind class.
        assert extract_count_for_label("v.10 hooks", "hooks") is None
        assert extract_count_for_label("mod.10 hooks", "hooks") is None
        assert extract_count_for_label("1.10 hooks", "hooks") is None

    def test_parenthesized_count_still_matches(self):
        from espalier.audit_accuracy import extract_count_for_label
        # The widened exclusion class must not block legitimate counts
        # appearing after punctuation like ``(`` or ``-``.
        assert extract_count_for_label("we ship (8 agents)", "agents") == 8
        assert extract_count_for_label("3 hooks", "hooks") == 3


# ── Verification dispatch ───────────────────────────────────────────


def _make_claim(text: str, *, pattern: str, mode: str = MODE_LIVE_REPO,
                location: str = "README.md:1") -> Claim:
    return Claim(
        claim_id="abc123def456",
        location=location,
        text=text,
        pattern=pattern,
        suggested_mode=mode,
    )


class TestVerificationDispatch:
    def test_live_repo_mode_does_not_call_llm(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        ctx = build_context(tmp_path)
        called: list = []
        def spy_dispatch(claim, pin):
            called.append((claim, pin))
            return None
        ctx_with_spy = build_context(tmp_path, dispatch=spy_dispatch)
        claim = _make_claim("9 hooks", pattern="num_hooks")
        verdict = verify_claim(claim, ctx_with_spy)
        assert called == [], "live_repo claims must not invoke the LLM dispatch"
        assert verdict.verdict == VERDICT_PASS

    def test_live_repo_pass_on_correct_count(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        ctx = build_context(tmp_path)
        claim = _make_claim("9 hooks total", pattern="num_hooks")
        assert verify_claim(claim, ctx).verdict == VERDICT_PASS

    def test_live_repo_fail_on_count_drift(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        ctx = build_context(tmp_path)
        claim = _make_claim("8 hooks total", pattern="num_hooks")
        verdict = verify_claim(claim, ctx)
        assert verdict.verdict == VERDICT_FAIL
        assert "8" in verdict.evidence
        assert "9" in verdict.evidence

    def test_test_count_claim_unverifiable_off_self_host(self, tmp_path):
        """TP-HARDEN-01 1-J + R3:NUM_TESTS_ADOPTER_FP: the 'docs must not pin
        exact test counts' rule is espalier's OWN convention. Off the self-host
        repo (an adopter), a 'N tests' mention is UNVERIFIABLE, not a hard FAIL
        citing a harness-internal file they don't have. The self-host FAIL is
        covered by TestNumTestsSelfHostGate.test_self_host_num_tests_still_fails."""
        _scaffold_repo(tmp_path)
        ctx = build_context(tmp_path)
        claim = _make_claim("1,431 tests pass", pattern="num_tests")
        verdict = verify_claim(claim, ctx)
        assert verdict.verdict == VERDICT_UNVERIFIABLE

    def test_external_pin_unverifiable_without_llm(self, tmp_path):
        _scaffold_repo(tmp_path)
        ctx = build_context(tmp_path)  # default _no_llm_dispatch
        claim = _make_claim(
            "Hooks must exit 2 to block",
            pattern="exit_code_near_hook",
            mode=MODE_EXTERNAL_PIN,
        )
        verdict = verify_claim(claim, ctx)
        # No matching pin in scaffolded repo; reports unverifiable
        # because there's nothing to dispatch against.
        assert verdict.verdict == VERDICT_UNVERIFIABLE

    def test_external_pin_with_llm_calls_dispatch(self, tmp_path):
        _scaffold_repo(tmp_path)
        # Inject a synthetic pin into the context.
        pin = ExternalPin(
            path=tmp_path / "docs" / "external" / "cc-hook-protocol.md",
            source_url="https://example.com/x",
            mirrors=(),
            fetched=date(2026, 4, 30),
            section="x",
            section_anchor=None,
            content_hash=None,
            refresh_policy="manual",
            purpose="test",
            body="test pin body",
        )
        called: list = []
        def stub_dispatch(claim, pin_arg):
            called.append((claim, pin_arg))
            return ClaimVerdict(
                claim_id=claim.claim_id, location=claim.location,
                claim_text=claim.text, verification_mode=MODE_EXTERNAL_PIN,
                verdict=VERDICT_PASS, evidence="LLM verified", evidence_source=pin_arg.path.name,
            )
        from espalier.audit_accuracy import VerificationContext
        ctx = VerificationContext(
            repo_root=tmp_path,
            pins_by_name={"cc-hook-protocol": pin},
            dispatch=stub_dispatch,
        )
        claim = _make_claim(
            "exit 0 with JSON",
            pattern="exit_code_near_hook",
            mode=MODE_EXTERNAL_PIN,
        )
        verdict = verify_claim(claim, ctx)
        assert len(called) == 1
        assert called[0][1].name == "cc-hook-protocol"
        assert verdict.verdict == VERDICT_PASS

    def test_unknown_mode_falls_back_to_unverifiable(self, tmp_path):
        ctx = build_context(tmp_path)
        claim = _make_claim("vague claim", pattern="unknown", mode=MODE_UNKNOWN)
        verdict = verify_claim(claim, ctx)
        assert verdict.verdict == VERDICT_UNVERIFIABLE


# ── Orchestrator ────────────────────────────────────────────────────


class TestAuditOrchestrator:
    def test_no_llm_mode_returns_zero_llm_calls(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        _write_doc(tmp_path, "README.md", "9 hooks.\n")
        report = audit_accuracy(tmp_path)
        assert report.llm_calls == 0
        assert report.estimated_cost_usd == 0.0

    def test_passing_claim_increments_passed_count(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        _write_doc(tmp_path, "README.md", "Init deploys 9 hooks.\n")
        report = audit_accuracy(tmp_path, doc_globs=["README.md"])
        assert report.claims_passed >= 1

    def test_failing_claim_increments_failed_count(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        _write_doc(tmp_path, "README.md", "Init deploys 8 hooks.\n")
        report = audit_accuracy(tmp_path, doc_globs=["README.md"])
        assert report.claims_failed >= 1

    def test_report_format_markdown_has_failures_section(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        _write_doc(tmp_path, "README.md", "Init deploys 8 hooks.\n")
        report = audit_accuracy(tmp_path, doc_globs=["README.md"])
        rendered = render_markdown(report)
        assert "# Accuracy Audit Report" in rendered
        assert "## Failures" in rendered
        assert "8 hooks" in rendered

    def test_claims_total_excludes_freshness_verdicts(self, tmp_path, monkeypatch):
        """TP-174a R19: 'Claims extracted' must count extracted doc-claims only,
        not freshness/pin verdicts folded into the verdict list. Pre-fix it was
        len(verdicts), so an injected freshness verdict inflated the number."""
        import espalier.audit_accuracy as aa
        _scaffold_repo(tmp_path, hooks=9)
        _write_doc(tmp_path, "README.md", "Init deploys 9 hooks.\n")
        fake = aa.ClaimVerdict(
            claim_id="freshness::x", location="a.md:1", claim_text="freshness:x",
            verification_mode=aa.MODE_FRESHNESS, verdict=aa.VERDICT_FAIL,
            evidence="", evidence_source=".espalier/freshness.json",
        )
        monkeypatch.setattr(aa, "_emit_freshness_verdicts", lambda *a, **k: [fake])
        report = aa.audit_accuracy(tmp_path, doc_globs=["README.md"])
        n_claims = len(aa.extract_claims(tmp_path, ["README.md"]))
        assert report.claims_total == n_claims
        # The freshness verdict still appears in the full verdict list.
        assert any(v.verification_mode == aa.MODE_FRESHNESS for v in report.verdicts)
        assert report.claims_total < len(report.verdicts)

    def test_full_audit_honours_excluded_docs_for_freshness_verdicts(
        self, tmp_path, monkeypatch
    ):
        """A frozen-record doc that QUOTES a fragment marker as an example is
        not making a live claim, and ``EXCLUDED_DOC_GLOBS`` already said so —
        but only the ``--doc`` path consulted it. A full audit passed
        ``doc_globs=None``, which ``_freshness_in_scope_files`` read as "no
        scope filter" and therefore also as "no exclusion", so a quoted example
        was audited as a real fragment.

        The discriminator is the second assertion: a fragment in a
        NON-excluded doc must still produce its verdict, so a fix that simply
        drops freshness verdicts on a full audit fails this test.
        """
        import espalier.audit_accuracy as aa
        import espalier.freshness as fr

        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "RELEASE_FINDINGS_LEDGER.md").write_text(
            "corpus\n", encoding="utf-8"
        )
        (tmp_path / "docs" / "CONVENTIONS.md").write_text("live\n", encoding="utf-8")

        cache = {
            "critical": [
                {
                    "id": "quoted-example",
                    "source": "docs/RELEASE_FINDINGS_LEDGER.md:329",
                    "reason": "unknown policy: '...'",
                },
                {
                    "id": "real-fragment",
                    "source": "docs/CONVENTIONS.md:10",
                    "reason": "drift detected",
                },
            ],
            "stale": [
                {
                    "id": "quoted-stale",
                    "source": "docs/RELEASE_FINDINGS_LEDGER.md:400",
                    "reason": "drift detected",
                },
            ],
        }
        monkeypatch.setattr(fr, "read_state_cache_safe", lambda root: cache)
        monkeypatch.setattr(
            fr, "is_state_cache_stale", lambda c, *, repo_root: False
        )

        verdicts = aa._emit_freshness_verdicts(tmp_path, None)
        ids = {v.claim_id for v in verdicts}
        assert "freshness::quoted-example" not in ids
        assert "freshness::quoted-stale" not in ids
        assert ids == {"freshness::real-fragment"}

    def test_report_format_json_is_parseable(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        _write_doc(tmp_path, "README.md", "Init deploys 9 hooks.\n")
        report = audit_accuracy(tmp_path, doc_globs=["README.md"])
        rendered = render_json(report)
        parsed = json.loads(rendered)
        assert parsed["claims_total"] >= 1
        for v in parsed["verdicts"]:
            assert "claim_id" in v
            assert "verdict" in v
            assert v["verdict"] in {"pass", "fail", "unverifiable"}

    def test_only_failing_omits_unverifiable_section(self, tmp_path):
        _scaffold_repo(tmp_path, hooks=9)
        # Two separate lines so each produces one claim (first-match-wins
        # per line means we'd only get one claim from a combined line).
        _write_doc(
            tmp_path, "README.md",
            "Init deploys 9 hooks total.\n\nReturns a permissionDecision in the response.\n",
        )
        report = audit_accuracy(tmp_path, doc_globs=["README.md"])
        # protocol_schema mention is unverifiable without LLM dispatch
        full = render_markdown(report, only_failing=False)
        only_fail = render_markdown(report, only_failing=True)
        assert "Unverifiable" in full
        assert "Unverifiable" not in only_fail


# ── LLM-dispatch contract (mocked) ──────────────────────────────────


class TestLLMDispatchContract:
    def test_dispatch_receives_claim_and_pin(self, tmp_path):
        _scaffold_repo(tmp_path)
        pin = ExternalPin(
            path=tmp_path / "docs" / "external" / "cc-hook-protocol.md",
            source_url="https://example.com",
            mirrors=(),
            fetched=date(2026, 4, 30),
            section="s",
            section_anchor=None,
            content_hash=None,
            refresh_policy="manual",
            purpose="p",
            body="pin body",
        )
        captured: dict = {}
        def dispatch(claim, pin_arg):
            captured["claim"] = claim
            captured["pin"] = pin_arg
            return None  # treat as unverifiable
        from espalier.audit_accuracy import VerificationContext
        ctx = VerificationContext(
            repo_root=tmp_path,
            pins_by_name={"cc-hook-protocol": pin},
            dispatch=dispatch,
        )
        claim = _make_claim(
            "exit 0 + JSON",
            pattern="exit_code_near_hook",
            mode=MODE_EXTERNAL_PIN,
        )
        verify_claim(claim, ctx)
        assert captured["claim"].text == claim.text
        assert captured["pin"].name == "cc-hook-protocol"

    def test_dispatch_returning_none_yields_unverifiable(self, tmp_path):
        _scaffold_repo(tmp_path)
        pin = ExternalPin(
            path=tmp_path / "docs" / "external" / "cc-hook-protocol.md",
            source_url="https://example.com",
            mirrors=(),
            fetched=date(2026, 4, 30),
            section="s",
            section_anchor=None,
            content_hash=None,
            refresh_policy="manual",
            purpose="p",
            body="pin body",
        )
        def dispatch(claim, pin_arg):
            return None
        from espalier.audit_accuracy import VerificationContext
        ctx = VerificationContext(
            repo_root=tmp_path,
            pins_by_name={"cc-hook-protocol": pin},
            dispatch=dispatch,
        )
        claim = _make_claim(
            "exit 0 + JSON",
            pattern="exit_code_near_hook",
            mode=MODE_EXTERNAL_PIN,
        )
        verdict = verify_claim(claim, ctx)
        assert verdict.verdict == VERDICT_UNVERIFIABLE


# ── Live-repo sanity ────────────────────────────────────────────────


def test_live_repo_audit_runs_clean():
    """The live espalier repo must currently audit clean (no failures).

    This is the gate that catches drift. If it fails, either a doc has
    drifted from reality or the auditor itself has a bug.
    """
    report = audit_accuracy(REPO_ROOT)
    # TP-174b R20: guard against vacuous green — if extract_claims regressed
    # to 0, verdicts would be empty and ``assert not failures`` would pass
    # while the drift gate is silently disarmed. claims_total counts EXTRACTED
    # claims (not the freshness/pin verdicts folded into verdicts), so it is
    # the correct disarm sentinel.
    assert report.claims_total > 0, (
        "audit extracted 0 claims — the drift gate is disarmed; "
        f"extract_claims likely regressed. report={report.to_dict()!r}"
    )
    failures = [v for v in report.verdicts if v.verdict == VERDICT_FAIL]
    assert not failures, (
        f"live repo audit found {len(failures)} failure(s):\n"
        + "\n".join(
            f"  - {v.location}: {v.claim_text!r} -> {v.evidence}"
            for v in failures
        )
    )


def test_malformed_pin_degrades_to_unverifiable(tmp_path: Path) -> None:
    """TP-152 B-2: one malformed external pin must degrade to a distinct
    `unverifiable` verdict, not abort the whole audit with an exit
    indistinguishable from real doc drift. Pre-fix `list_pins` raised
    ValueError out of build_context and the run exited 1."""
    ext = tmp_path / "docs" / "external"
    ext.mkdir(parents=True)
    # No YAML frontmatter -> parse_pin raises ValueError.
    (ext / "bad.md").write_text("no frontmatter, just prose\n", encoding="utf-8")
    report = audit_accuracy(tmp_path)  # must not raise
    bad = [v for v in report.verdicts if v.location == "docs/external/bad.md"]
    assert len(bad) == 1, f"expected one degraded verdict; got {report.verdicts}"
    assert bad[0].verdict == VERDICT_UNVERIFIABLE
    assert "malformed" in bad[0].evidence
    # otherwise-clean tree: the bad pin is not a hard FAIL -> cli exits 0
    assert report.claims_failed == 0


class TestNumTestsSelfHostGate:
    """R3:NUM_TESTS_ADOPTER_FP — the 'operator docs must not pin an exact test
    count' rule is ESPALIER'S OWN convention. It must hard-FAIL only on the
    self-host repo; an adopter's 'run the 3 tests' prose is unverifiable, not a
    violation citing a harness-internal file they don't have."""

    @staticmethod
    def _claim():
        from espalier.audit_accuracy import Claim
        return Claim(
            claim_id="x", location="README.md:1", text="run the 3 tests",
            pattern="num_tests", suggested_mode="live_repo",
        )

    def test_adopter_num_tests_is_unverifiable_not_fail(self, tmp_path):
        from espalier.audit_accuracy import _verify_against_repo, VERDICT_UNVERIFIABLE
        v = _verify_against_repo(self._claim(), tmp_path)
        assert v.verdict == VERDICT_UNVERIFIABLE, v.verdict

    def test_self_host_num_tests_still_fails(self):
        from espalier.audit_accuracy import _verify_against_repo, VERDICT_FAIL
        v = _verify_against_repo(self._claim(), REPO_ROOT)
        assert v.verdict == VERDICT_FAIL, v.verdict


class TestExtractCountForLabelIsPublic:
    """``doctor`` imports the count helper across modules, so it is public API
    of ``audit_accuracy``: the underscore name is gone, not aliased (DEF-532)."""

    def test_public_name_present_private_name_gone(self):
        from espalier import audit_accuracy
        assert callable(getattr(audit_accuracy, "extract_count_for_label", None))
        assert not hasattr(audit_accuracy, "_extract_count_for_label")

    def test_doctor_binds_the_public_name(self):
        from espalier import doctor
        from espalier.audit_accuracy import extract_count_for_label
        assert doctor.extract_count_for_label is extract_count_for_label

    def test_the_old_private_name_is_gone_from_every_tracked_python_file(self):
        """The rename sweep as an assert, not a plan sentence: the first sweep
        covered espalier/, tools/, scripts/ and tests/ and missed the five
        sites in bench/run_benchmark.py, whose try/except ImportError scored
        the release-gating BC-029 row as not blocked with a reason blaming the
        install (both reviewers, 2026-09-11). Tracked files only, this file
        excepted (it names the old spelling to assert its absence)."""
        from tests._git_oracle import require_tracked_paths
        old = "_extract" + "_count_for_label"
        # This file names the old spelling to assert its absence, and
        # tests/test_recall.py records the C17 task text verbatim as a recall
        # query (a _TASK_ARM row, appended at that lane's handoff after its tier
        # had run): a quotation of the name, not a reference to the symbol.
        quoters = {"tests/test_audit_accuracy.py", "tests/test_recall.py"}
        offenders = [
            rel for rel in require_tracked_paths(REPO_ROOT, "*.py", minimum=100)
            if rel not in quoters
            and old in (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        ]
        assert not offenders, offenders
