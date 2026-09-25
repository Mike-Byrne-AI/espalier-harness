"""Pin retired-vocab scanner contract: 7 terms registered, earn-the-gate,
heading-stack semantics, context predicates, exemption logic,
read-failure resilience, stdlib-only.

The earn-the-gate test (TP-105 pattern) calls ``_scan_file`` directly
against the fixture under ``tests/fixtures/`` -- the fixture sits
outside ``DOC_SURFACES`` and inside ``EXEMPT_PREFIXES``, so
``scan_repo`` cannot reach it. The direct-call pattern matches
``test_scanner_filesystem_contracts.py::test_earn_the_gate_detects_every_fixture_shape``.

``test_scanner_returns_clean_against_live_repo`` is a post-sweep gate
(140-H). It is expected to fail until residue cleanup completes; after
the sweep it stays green and catches future residue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from espalier.scanners import retired_vocab as rv


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REL = "tests/fixtures/retired_vocab_positives.md"
FIXTURE_PATH = REPO_ROOT / FIXTURE_REL
NEG_FIXTURE_REL = "tests/fixtures/retired_vocab_negatives.md"
NEG_FIXTURE_PATH = REPO_ROOT / NEG_FIXTURE_REL


def test_all_seven_tp114_terms_registered() -> None:
    """TP-114 retired 7 severity terms; registry must have all 7."""
    expected = {"WRONG", "CONFLICTING", "VAGUE", "CORRECT",
                "BLOCKER", "MAJOR", "MINOR"}
    actual = {t.term for t in rv.RETIRED_TERMS}
    missing = expected - actual
    assert not missing, f"Registry missing TP-114 terms: {missing}"


def test_earn_the_gate_detects_severity_labels() -> None:
    """Scanner detects severity-label-shape occurrences across all 7 terms.

    Calls ``_scan_file`` directly because the fixture lives in a
    directory outside ``DOC_SURFACES`` and inside
    ``EXEMPT_PREFIXES`` -- ``scan_repo`` cannot reach it by design.
    Mirrors the sibling pattern in
    ``test_scanner_filesystem_contracts.py``.
    """
    findings = list(rv._scan_file(FIXTURE_PATH, FIXTURE_REL))
    detected_terms = {f.term for f in findings}
    expected_terms = {"WRONG", "CONFLICTING", "VAGUE", "CORRECT",
                      "BLOCKER", "MAJOR", "MINOR"}
    missing = expected_terms - detected_terms
    assert not missing, (
        f"Scanner failed to detect retired severity labels: {missing}"
    )
    # Severity is the load-bearing signal, not just term detection: each finding
    # carries the RetiredTerm.severity that fired it (VocabFinding.severity). The
    # term-set assertion above does NOT pin the term->severity mapping, so a
    # registry relabel (e.g. WRONG's severity BLOCK -> PASS) survives it — the
    # A-6 class-closure find for this scanner. Pin the mapping so that flip reds.
    sev_by_term: dict[str, set[str]] = {}
    for f in findings:
        sev_by_term.setdefault(f.term, set()).add(f.severity)
    expected_sev = {
        "WRONG": {"BLOCK"}, "CONFLICTING": {"BLOCK"}, "VAGUE": {"WARN"},
        "CORRECT": {"PASS"}, "BLOCKER": {"BLOCK"}, "MAJOR": {"WARN"},
        "MINOR": {"NIT"},
    }
    assert sev_by_term == expected_sev, (
        f"term->severity drift: expected {expected_sev}, got {sev_by_term}"
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip negative corpus: zero findings on clean-but-tempting
    constructs.

    Mirrors the earn-the-gate reach path — direct ``_scan_file`` against a
    fixture under ``tests/fixtures/`` (inside ``EXEMPT_PREFIXES``, so
    ``scan_repo`` cannot reach it). Each construct in the fixture is a
    defanged near-boundary variant of a shape the positives fixture flags
    (prose use, mid-sentence bold, line-wrapped colon/em-dash, live
    replacement vocab, immediate-parent-historical exemption, backticked
    term names). A non-empty result means the scanner is over-firing.
    """
    findings = list(rv._scan_file(NEG_FIXTURE_PATH, NEG_FIXTURE_REL))
    assert findings == [], (
        "retired_vocab over-fired on the negatives corpus:\n"
        + "\n".join(
            f"  {f.path}:{f.lineno} — {f.term} — "
            f"under parent='{f.immediate_parent}' — '{f.line_snippet}'"
            for f in findings
        )
    )


def test_historical_section_exempts_immediate_parent_only() -> None:
    """Heading-stack predicate must check IMMEDIATE parent only.

    The v1 design joined the full stack and substring-matched, which
    leaked: a ``## Historical context`` at the top exempted every
    later section. v2 checks only the last stack entry.
    """
    findings = list(rv._scan_file(FIXTURE_PATH, FIXTURE_REL))
    historical_findings = [
        f for f in findings
        if "Historical" in f.immediate_parent
    ]
    assert not historical_findings, (
        "Immediate-parent-historical predicate failed: "
        f"flagged {len(historical_findings)} historical occurrences."
    )


def test_prose_use_does_not_match() -> None:
    """Severity-label-shape pattern must not match prose."""
    pattern = rv._severity_label_pattern("WRONG")
    assert not pattern.search("You wrote a wrong answer.")
    assert not pattern.search("The wrong direction was taken.")
    assert pattern.search("- **WRONG** — block execution")
    assert pattern.search("| WRONG | description |")
    assert pattern.search("WRONG: this fails")


def _entry(term: str) -> rv.RetiredTerm:
    return next(t for t in rv.RETIRED_TERMS if t.term == term)


def test_lowercase_bold_prose_does_not_fire() -> None:
    """TP-174a: adopter markdown emphasis of an ordinary English word
    (``**correct**``, ``**major**``) is prose, not a retired severity label.
    Pre-fix the IGNORECASE pattern made these fire as findings."""
    assert not rv._fires_as_label(_entry("CORRECT"), "use the **correct** pattern")
    assert not rv._fires_as_label(_entry("MAJOR"), "a **major** refactor lands")
    assert not rv._fires_as_label(_entry("MINOR"), "just a **minor** tweak")


def test_uppercase_and_titlecase_labels_still_fire() -> None:
    """The narrowing must NOT lose genuine retired labels: upper/title-case in
    the bold/cell shapes, and the bullet/section shapes at any case, still fire."""
    assert rv._fires_as_label(_entry("WRONG"), "- **WRONG** — block")
    assert rv._fires_as_label(_entry("WRONG"), "the **Wrong** premise here")
    assert rv._fires_as_label(_entry("MAJOR"), "| MAJOR | high impact |")
    assert rv._fires_as_label(_entry("WRONG"), "WRONG: this fails")


def test_read_text_failure_does_not_crash(tmp_path: Path) -> None:
    """Malformed UTF-8 in a doc file must not crash the scanner."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broken.md").write_bytes(b"\xff\xfe**WRONG**\x80\xc0")
    (docs / "ok.md").write_text(
        "- **WRONG** — bad severity label\n",
        encoding="utf-8",
    )
    findings = rv.scan_repo(tmp_path)
    assert any(f.term == "WRONG" for f in findings)


def test_scan_repo_respects_exempt_files(tmp_path: Path, monkeypatch) -> None:
    """``scan_repo`` must skip any file listed in ``EXEMPT_FILES``."""
    monkeypatch.setattr(
        rv, "DOC_SURFACES", ("docs/",),
    )
    monkeypatch.setattr(rv, "EXEMPT_PREFIXES", ())
    monkeypatch.setattr(rv, "EXEMPT_FILES", frozenset({"docs/exempt.md"}))
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "exempt.md").write_text(
        "- **WRONG** — should be skipped\n",
        encoding="utf-8",
    )
    (docs / "scanned.md").write_text(
        "- **BLOCKER** — should be flagged\n",
        encoding="utf-8",
    )
    findings = rv.scan_repo(tmp_path)
    terms = {f.term for f in findings}
    assert "BLOCKER" in terms, "scanned.md was not walked"
    assert "WRONG" not in terms, "exempt.md was not skipped"


def test_scan_repo_respects_exempt_dir_prefixes(tmp_path: Path, monkeypatch) -> None:
    """``scan_repo`` must skip any file whose rel path starts with an
    ``EXEMPT_PREFIXES`` entry."""
    monkeypatch.setattr(rv, "DOC_SURFACES", ("docs/",))
    monkeypatch.setattr(rv, "EXEMPT_FILES", frozenset())
    monkeypatch.setattr(rv, "EXEMPT_PREFIXES", ("docs/private/",))
    private = tmp_path / "docs" / "private"
    private.mkdir(parents=True)
    (private / "drop.md").write_text(
        "- **MAJOR** — should be skipped\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "public.md").write_text(
        "- **BLOCKER** — should be flagged\n",
        encoding="utf-8",
    )
    findings = rv.scan_repo(tmp_path)
    terms = {f.term for f in findings}
    assert "BLOCKER" in terms
    assert "MAJOR" not in terms


def test_build_report_normalizes_windows_paths(monkeypatch) -> None:
    """TP-192 W6-1: ``build_report`` must emit forward-slash paths like every
    sibling scanner's ``build_report`` (magic_depth/filesystem_contracts/
    subprocess_contracts/convergence_theater), even for a Windows-style finding
    path. Closes the docstring sibling-parity overclaim + known-finding line 119."""
    from pathlib import PureWindowsPath

    finding = rv.VocabFinding(
        path=PureWindowsPath("docs\\sub\\NOTES.md"),
        lineno=3,
        term="BLOCKER",
        retired_in="TP-114",
        severity="blocker",
        line_snippet="- **BLOCKER**",
        immediate_parent="",
    )
    monkeypatch.setattr(rv, "scan_repo", lambda root: [finding])
    report = rv.build_report(Path("/tmp/unused"))
    emitted = report["findings"][0]["path"]
    assert emitted == "docs/sub/NOTES.md", emitted
    assert "\\" not in emitted, "path must be normalized to forward slashes"


def test_build_report_shape(monkeypatch) -> None:
    """TP-192 W5-2: ``build_report`` had no direct test — the only path reaching
    it asserts ``scan_exceptions``/``scan_prints`` exist, never
    ``scan_retired_vocab``'s keys, so a typo in any key shipped undetected.
    Pin the exact 7-key finding shape + ``count == len(findings)`` (mirrors the
    other scanners' ``build_report`` shape tests)."""
    finding = rv.VocabFinding(
        path=Path("docs/x.md"),
        lineno=7,
        term="BLOCKER",
        retired_in="TP-114",
        severity="blocker",
        line_snippet="- **BLOCKER**",
        immediate_parent="",
    )
    monkeypatch.setattr(rv, "scan_repo", lambda root: [finding])
    report = rv.build_report(Path("/tmp/unused"))
    assert isinstance(report, dict)
    assert report["count"] == 1 == len(report["findings"])
    assert set(report["findings"][0]) == {
        "path",
        "lineno",
        "term",
        "retired_in",
        "severity",
        "line_snippet",
        "immediate_parent",
    }


def test_exempt_files_within_cap() -> None:
    actual = len(rv.EXEMPT_FILES)
    assert actual <= rv.MAX_EXEMPT_FILES, (
        f"EXEMPT_FILES count ({actual}) exceeds cap ({rv.MAX_EXEMPT_FILES})."
    )


class TestRetiredTermSeverityClosedVocab:
    """FM-10 close: every RetiredTerm.severity must be in the closed
    severity vocabulary. Pre-rename (TP-114..TP-143) the field was named
    ``replacement`` but every entry held a severity label — pinning the
    closed vocab makes the field name's semantic explicit and catches
    future entries that drift to free-form strings."""

    _CLOSED_SEVERITY_VOCAB = frozenset({"BLOCK", "WARN", "NIT", "PASS"})

    @pytest.mark.parametrize(
        "entry", list(rv.RETIRED_TERMS), ids=lambda e: e.term
    )
    def test_severity_in_closed_vocab(self, entry: rv.RetiredTerm) -> None:
        assert entry.severity in self._CLOSED_SEVERITY_VOCAB, (
            f"RetiredTerm({entry.term!r}).severity={entry.severity!r} is "
            f"not in {sorted(self._CLOSED_SEVERITY_VOCAB)}. The severity "
            f"field is a closed enumeration (TP-114); free-form strings "
            f"indicate the field is being mis-used for something other "
            f"than severity."
        )

    def test_dataclass_no_replacement_field(self) -> None:
        """Sister-site contract: after the TP-144 rename, no field named
        ``replacement`` exists on RetiredTerm or VocabFinding. Catches
        re-introduction of the old shape."""
        import dataclasses
        for cls in (rv.RetiredTerm, rv.VocabFinding):
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert "replacement" not in field_names, (
                f"{cls.__name__}.replacement was renamed to .severity in "
                f"TP-144 (FM-10 close). Re-adding `replacement` requires "
                f"a real replacement string for a retirement class that "
                f"has both — see TP-144 scope-out for the addition pattern."
            )


def test_exempt_prefixes_within_cap() -> None:
    actual = len(rv.EXEMPT_PREFIXES)
    assert actual <= rv.MAX_EXEMPT_PREFIXES, (
        f"EXEMPT_PREFIXES count ({actual}) exceeds cap "
        f"({rv.MAX_EXEMPT_PREFIXES})."
    )


def test_scanner_no_espalier_import() -> None:
    target = REPO_ROOT / "espalier" / "scanners" / "retired_vocab.py"
    source = target.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "from espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )
        # TP-176 W4-1: symmetry with the other four scanner self-containment
        # tests — guard `import espalier...` as well as `from espalier...`.
        assert "import espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )


def test_scanner_returns_clean_against_live_repo() -> None:
    """Zero-residue contract against the current repo.

    Post-sweep gate (140-H). Expected to fail until residue cleanup
    completes; afterwards stays green and catches future residue.
    """
    findings = rv.scan_repo(REPO_ROOT)
    if findings:
        msg = "\n".join(
            f"  {f.path}:{f.lineno} — {f.term} — "
            f"under parent='{f.immediate_parent}' — '{f.line_snippet}'"
            for f in findings
        )
        pytest.fail(
            f"{len(findings)} retired-vocab residue(s) outside allowed "
            f"context:\n{msg}"
        )


class TestBacktickedOccurrenceIsAMentionNotAUse:
    """A term inside inline code is prose ABOUT the label, not the label.

    Inline code renders as the literal characters, so a backticked ``**WRONG**``
    cannot function as a severity marker — which is exactly what the pattern's
    own docstring says it matches ("the term used as a severity LABEL, not as
    prose"). Before this, the scanner read documentation discussing the retired
    taxonomy as a use of it: a memory row stating that these terms appear in zero
    files was the only thing making them appear, and it reddened the live-repo
    gate. The recorded cost of the gap was compliance-by-rewriting — describing a
    term rather than naming it, paid at the instruction layer by every doc that
    needs to discuss the vocabulary at all.

    ⚠ The exclusion must not become a bypass: a term that really is being used as
    a label is never rendered as code, so :meth:`test_real_uses_still_fire` is the
    half that keeps this honest. Both halves are required — an exclusion with no
    use-side pin is indistinguishable from switching the rule off.
    """

    MENTIONS = [
        "yet `**BLOCKER**`/`**MAJOR**` appear in 0 files across the tree",
        "the retired label `**WRONG**` is no longer used anywhere",
        "write `**MINOR**` only inside a code span when discussing it",
    ]
    USES = [
        "**BLOCKER** the build is broken",
        "- BLOCKER: the build is broken",
        "| BLOCKER | something |",
        "BLOCKER: the build is broken",
        "severity **BLOCKER** applies to this finding",
    ]

    @pytest.mark.parametrize("line", MENTIONS)
    def test_backticked_mentions_are_allowed(self, line: str) -> None:
        for term in ("BLOCKER", "WRONG", "MINOR", "MAJOR"):
            assert not rv._severity_label_pattern(term).search(line), (term, line)

    @pytest.mark.parametrize("line", USES)
    def test_real_uses_still_fire(self, line: str) -> None:
        assert rv._severity_label_pattern("BLOCKER").search(line), line

    def test_every_registered_term_honours_the_distinction(self) -> None:
        """Derived over the whole roster, not a sample of it.

        The guard sits on the shared alternation precisely so all four arms
        inherit it; deriving the population from ``RETIRED_TERMS`` means a term
        added later is covered without anyone remembering to extend a list.
        """
        for entry in rv.RETIRED_TERMS:
            term = entry.term
            assert not entry.pattern.search(f"discussion of `**{term}**` here"), term
            assert entry.pattern.search(f"**{term}** something is wrong"), term

    def test_the_exemption_is_exact_wrapping_only(self) -> None:
        """The boundary, pinned so nobody assumes 'inline code is exempt'.

        The guard is a pair of lookarounds on the adjacent character, so it
        recognises ``` `**BLOCKER**` ``` — the shape the repo actually writes —
        but NOT a term sitting inside a longer code span. Closing that would need
        position-aware logic in the scan loop (count the backticks preceding the
        match) rather than a lookaround in the pattern; it is deliberately not
        done here, because this scanner is stderr-only advisory and widening a
        rule until it stops firing is how a guard goes blind.

        If someone later makes the span-aware fix, this test reds and asks them
        to update it — which is the intent.
        """
        pat = rv._severity_label_pattern("BLOCKER")
        assert not pat.search("`**BLOCKER**`"), "exact wrap must be exempt"
        assert pat.search("`see **BLOCKER** here`"), (
            "a longer code span is a KNOWN limit -- if this now passes, the "
            "scanner became span-aware and this test should be updated"
        )
