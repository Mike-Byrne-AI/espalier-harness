"""Pin the magic-depth scanner's behavioral contract.

Two arms, and the split is load-bearing rather than tidy.

SYNTHETIC arm -- earn-the-gate (every documented parents[N] shape detected),
must-not-trip on the negatives corpus, multi-line attribution. These drive
fixtures under ``tests/fixtures/`` with ``EXEMPT_PREFIXES`` monkeypatched off,
so they keep working no matter what the live tree contains. They are the only
thing standing between a COLLAPSED scanner and a green file: every live-tree
assertion below is satisfied by a scanner that finds nothing at all.

LIVE-TREE arm -- zero-UNPINNED, the pragma cap, the EXEMPT_PREFIXES cap, and
the registry ratchet. These say what this repo currently contains, so each one
goes quiet as the population shrinks.

The one live depth>=2 site (``tools/cc/hooks/post_write_check.py``) is pinned by
a standalone pragma comment, NOT by a registry entry: the ``<file>:<line>`` key
form is retired here (ledger DEF-417j) because it un-keys on any edit above the
site. A new ``parents[3]`` without a pragma fails zero-UNPINNED on first commit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from espalier.scanners import magic_depth as md


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REL = "tests/fixtures/test_magic_depth_positives.py"
NEG_FIXTURE_REL = "tests/fixtures/test_magic_depth_negatives.py"


def test_earn_the_gate_detects_every_fixture_shape(monkeypatch) -> None:
    """Run scanner against the known-positives fixture (with
    EXEMPT_PREFIXES monkeypatched off) -- every documented shape must
    surface."""
    monkeypatch.setattr(md, "EXEMPT_PREFIXES", ())
    findings = md.scan_repo(REPO_ROOT)
    fixture_findings = [
        f for f in findings
        if str(f.path).replace("\\", "/") == FIXTURE_REL
    ]
    # 3 shapes: parents[2], parents[3], parents[<dynamic>]
    depths = {f.depth for f in fixture_findings}
    assert 2 in depths, "parents[2] not detected"
    assert 3 in depths, "parents[3] not detected"
    assert None in depths, "parents[<dynamic>] not detected"
    # Severity, not just depth: _classify has two UNPINNED returns — one for the
    # dynamic index (magic_depth.py:240) and one for a concrete over-threshold
    # depth (:248). A relabel-defang (UNPINNED -> PINNED) keeps the depths present
    # but empties the class the scanner flags. Pin each branch so either mutation
    # goes red here.
    dynamic = [f for f in fixture_findings if f.depth is None]
    concrete = [f for f in fixture_findings if f.depth == 3]
    assert dynamic and all(f.severity == "UNPINNED" for f in dynamic), (  # :240
        f"parents[<dynamic>] must classify UNPINNED, got "
        f"{[(f.depth, f.severity) for f in dynamic]}"
    )
    assert concrete and all(f.severity == "UNPINNED" for f in concrete), (  # :248
        f"parents[3] must classify UNPINNED, got "
        f"{[(f.depth, f.severity) for f in concrete]}"
    )


def test_multiline_parents_attributes_to_parents_line(monkeypatch) -> None:
    """A multi-line `.parents[N]` finding cites the `.parents` line, not the
    expression-start line (sweep T5) — so a pragma/registry entry on the real
    line is honored. Uses the depth-4 multi-line fixture shape."""
    monkeypatch.setattr(md, "EXEMPT_PREFIXES", ())
    findings = md.scan_repo(REPO_ROOT)
    src = (REPO_ROOT / FIXTURE_REL).read_text(encoding="utf-8").splitlines()
    parents_lines = {i for i, ln in enumerate(src, start=1) if ".parents[4]" in ln}
    cited = {
        f.lineno for f in findings
        if str(f.path).replace("\\", "/") == FIXTURE_REL and f.depth == 4
    }
    assert cited & parents_lines, (
        f"multi-line parents[4] finding cited {cited}, "
        f"expected one of the `.parents[4]` lines {parents_lines}"
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: clean-but-tempting constructs (parents[<2],
    deep non-`parents` subscripts, dynamic index on a non-`parents`
    attribute) yield ZERO findings. Direct-call on the negatives
    fixture path keeps this immune to live-tree drift -- the positive
    earn-the-gate test scans the whole tree, but silence must be proven
    against a fixed, known-clean file."""
    neg_path = REPO_ROOT / NEG_FIXTURE_REL
    findings = list(md._scan_file(neg_path, REPO_ROOT))
    assert findings == [], (
        f"magic_depth fired on the negatives corpus "
        f"({len(findings)} finding(s)): "
        + "; ".join(
            f"{f.path}:{f.lineno} depth={f.depth} {f.severity}"
            for f in findings
        )
    )


def test_pragma_count_within_cap() -> None:
    actual = md.count_pragmas(REPO_ROOT)
    assert actual <= md.MAX_PRAGMA_COUNT, (
        f"Magic-depth pragma count ({actual}) exceeds cap "
        f"({md.MAX_PRAGMA_COUNT}). Either close pragmas via refactor, "
        f"or raise MAX_PRAGMA_COUNT explicitly."
    )


def test_exempt_prefixes_within_cap() -> None:
    actual = len(md.EXEMPT_PREFIXES)
    assert actual <= md.MAX_EXEMPT_PREFIXES, (
        f"EXEMPT_PREFIXES count ({actual}) exceeds cap "
        f"({md.MAX_EXEMPT_PREFIXES}). Add prefix only when its scope "
        f"is justified."
    )


def test_registry_stays_empty_line_keys_are_retired():
    """MAGIC_DEPTH_SITES must stay EMPTY on this tree: the line-keyed form is
    retired (ledger DEF-417j) in favour of the pragma, which rides on the line
    it exempts and so cannot be separated from its site by any edit.

    REPLACES ``test_registry_has_no_orphan_line_keys``, which asserted that no
    key had gone stale. That was the right check while keys existed and it is
    strictly weaker than this one: it tolerated the fragile form and only caught
    it AFTER it drifted. Emptying the dict would also have made it vacuous -- it
    iterated the keys, so zero keys meant zero assertions -- which is the exact
    silent-orphan shape docs/FAILURE_MODES.md 13.27 was written about.

    WHAT THIS TEST DOES *NOT* DETECT, stated because the dependency is invisible
    from here: it cannot tell an empty registry from a COLLAPSED SCANNER. Every
    way the scanner could break -- regex, AST walk, classification -- leaves this
    assertion green. That detection lives in
    ``test_earn_the_gate_detects_every_fixture_shape`` and
    ``test_does_not_trip_on_negatives``, which drive a SYNTHETIC fixture and
    therefore keep working at zero live registry entries. Do not delete either as
    redundant; they are the only reason this file's silence means anything.
    """
    assert md.MAGIC_DEPTH_SITES == {}, (
        f"MAGIC_DEPTH_SITES is non-empty: {sorted(md.MAGIC_DEPTH_SITES)}. "
        f"The <file>:<line> key form is retired on this tree -- it un-keys on any "
        f"edit above the site (drifted 131 -> 133 in TP-399 from a comment edit "
        f"four lines up). Pin the site with a standalone `magic-depth: ok "
        f"<reason>` comment on the line above it instead. The registry stays wired "
        f"for ADOPTERS with un-annotatable generated files; this repo does not use it."
    )


def test_no_unpinned_magic_depth_sites() -> None:
    """Live-repo zero-UNPINNED: every parents[>=2] use must carry a standalone
    `magic-depth: ok <reason>` pragma on the line above it. (The registry is the
    other mechanism the scanner honours, but this tree keeps it empty -- see
    ``test_registry_stays_empty_line_keys_are_retired``.)

    This is also the guard that makes the pragma non-optional: delete the comment
    above the post_write_check site and this reds immediately."""
    findings = md.scan_repo(REPO_ROOT)
    unpinned = [
        f for f in findings
        if f.severity == "UNPINNED"
        and str(f.path).replace("\\", "/") != FIXTURE_REL
    ]
    if unpinned:
        msg = "\n".join(
            f"  {f.path}:{f.lineno} -- depth={f.depth}"
            for f in unpinned
        )
        pytest.fail(
            f"{len(unpinned)} unpinned parents[N] site(s):\n{msg}\n\n"
            f"Add MAGIC_DEPTH_SITES entry OR `# magic-depth: ok <reason>` "
            f"pragma with reason >=12 chars."
        )


def test_build_report_shape() -> None:
    report = md.build_report(REPO_ROOT)
    assert isinstance(report, dict)
    assert "count" in report
    assert "findings" in report
    assert isinstance(report["findings"], list)


def test_scanner_no_espalier_import() -> None:
    target = REPO_ROOT / "espalier" / "scanners" / "magic_depth.py"
    source = target.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "from espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )
        assert "import espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )
