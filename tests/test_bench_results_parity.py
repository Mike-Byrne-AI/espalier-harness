"""TP-96: bench/RESULTS.md parity contract.

Independent witness on the bench canonical document. The bench runner
(`bench/run_benchmark.py`) is the SoT generator; this test is the SoT
audit. Two witnesses, no shared code: the test parses RESULTS.md as
markdown text and asserts that the published numeric claims match the
on-disk corpus, independent of how the runner produced them.

Catches the class of drift that motivated TP-96: header N-in-scope
out of sync with the table denominator after corpus expansion (the
runner had been hand-skipped on local cuts).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# pyproject declares requires-python >= 3.10 but tomllib is stdlib only from
# 3.11. Use the project compat shim so 3.10 hosts (with tomli installed) don't
# crash at test-collection time. None when neither parser is available — the
# version-stamp test below skips in that case.
from espalier._compat import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "bench" / "RESULTS.md"
CORPUS_DIR = REPO_ROOT / "bench" / "corpus"

_HEADER_RE = re.compile(
    r"^Bypass attempts:\s+(\d+)\s+in-scope,\s+(\d+)\s+documented out-of-scope",
    re.MULTILINE,
)
_SUMMARY_ROW_RE = re.compile(
    r"^\|\s*(no-governance|settings-deny-only|minimal-hooks|espalier)\s*\|"
    r"\s*(\d+)\s*/\s*(\d+)\s*\|"
    r"\s*(\d+)\s*/\s*(\d+)\s*\|",
    re.MULTILINE,
)
_DETAIL_ROW_RE = re.compile(
    r"^\|\s*(BC-[A-Za-z0-9_-]+?)\s*\|"
    r"\s*(\d+)/(\d+)\s+(blocked|allowed)\s*\|"
    r"\s*(\d+)/(\d+)\s+(blocked|allowed)\s*\|"
    r"\s*(\d+)/(\d+)\s+(blocked|allowed)\s*\|"
    r"\s*(\d+)/(\d+)\s+(blocked|allowed)\s*\|",
    re.MULTILINE,
)


@pytest.fixture(scope="module")
def results_text() -> str:
    assert RESULTS_PATH.exists(), f"bench/RESULTS.md missing at {RESULTS_PATH}"
    return RESULTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def corpus_files() -> dict[str, list[Path]]:
    """Split corpus into in-scope (BC-NNN) and out-of-scope (BC-OOS) buckets."""
    in_scope: list[Path] = []
    oos: list[Path] = []
    for path in sorted(CORPUS_DIR.glob("BC-*.json")):
        if path.name.startswith("BC-OOS-"):
            oos.append(path)
        else:
            in_scope.append(path)
    return {"in_scope": in_scope, "oos": oos}


class TestBenchResultsParity:
    """Cross-document numeric claims on bench/RESULTS.md must match the
    on-disk corpus. See TP-96 motivation: the pre-OSS review flagged
    header "134 in-scope" vs table "/ 127" — 7 attempts short, with 3
    corpus files (BC-041, BC-041b, BC-043) entirely absent from the
    table. The runner is correct; the canonical file just wasn't being
    regenerated. This contract catches the same drift class on the
    next BC-NNN add.
    """

    def test_header_n_equals_table_denominator(
        self, results_text: str, corpus_files: dict[str, list[Path]]
    ):
        header_match = _HEADER_RE.search(results_text)
        assert header_match is not None, (
            "RESULTS.md is missing the 'Bypass attempts: N in-scope, "
            "M documented out-of-scope' header line"
        )
        header_in_scope = int(header_match.group(1))
        header_oos = int(header_match.group(2))

        # Header in-scope total must equal the sum of canonical_attempts
        # across in-scope corpus files. The runner derives the denominator
        # from corpus content, so this anchors the header to corpus reality.
        expected_in_scope = sum(
            len(json.loads(p.read_text(encoding="utf-8")).get("canonical_attempts", []))
            for p in corpus_files["in_scope"]
        )
        expected_oos = sum(
            len(json.loads(p.read_text(encoding="utf-8")).get("canonical_attempts", []))
            for p in corpus_files["oos"]
        )
        assert header_in_scope == expected_in_scope, (
            f"RESULTS.md header in-scope total {header_in_scope} != corpus "
            f"canonical_attempts sum {expected_in_scope}"
        )
        assert header_oos == expected_oos, (
            f"RESULTS.md header OOS total {header_oos} != corpus "
            f"canonical_attempts sum {expected_oos}"
        )

        # Every Summary table baseline row's in-scope denominator must
        # equal header_in_scope; OOS denominator must equal header_oos.
        summary_rows = _SUMMARY_ROW_RE.findall(results_text)
        assert len(summary_rows) == 4, (
            f"RESULTS.md Summary table has {len(summary_rows)} baseline "
            f"rows, expected 4 (no-governance, settings-deny-only, "
            f"minimal-hooks, espalier)"
        )
        for baseline, _blocked, in_denom, _allowed, oos_denom in summary_rows:
            assert int(in_denom) == header_in_scope, (
                f"Summary table row for {baseline!r}: in-scope denominator "
                f"{in_denom} != header N {header_in_scope}"
            )
            assert int(oos_denom) == header_oos, (
                f"Summary table row for {baseline!r}: OOS denominator "
                f"{oos_denom} != header M {header_oos}"
            )

    def test_all_corpus_files_present_in_table(
        self, results_text: str, corpus_files: dict[str, list[Path]]
    ):
        detail_rows = _DETAIL_ROW_RE.findall(results_text)
        bc_ids_in_table = {row[0] for row in detail_rows}

        for path in corpus_files["in_scope"] + corpus_files["oos"]:
            bc_id = path.stem  # e.g. "BC-041-test-shaped-fixture-bypasses-real-format"
            assert bc_id in bc_ids_in_table, (
                f"Corpus file {path.name} is absent from the Detail table. "
                f"Run `python3 bench/run_benchmark.py --update-canonical` "
                f"to regenerate bench/RESULTS.md."
            )

        # Inverse: no Detail row references a corpus file that doesn't exist.
        all_corpus_stems = {
            p.stem for p in corpus_files["in_scope"] + corpus_files["oos"]
        }
        for bc_id in bc_ids_in_table:
            assert bc_id in all_corpus_stems, (
                f"Detail table references {bc_id!r} but no matching "
                f"bench/corpus/{bc_id}.json exists on disk."
            )

        # Exactly-once: catches duplicate rows.
        seen: dict[str, int] = {}
        for row in detail_rows:
            seen[row[0]] = seen.get(row[0], 0) + 1
        dupes = {k: v for k, v in seen.items() if v > 1}
        assert not dupes, f"Detail table has duplicate BC rows: {dupes}"

    def test_baseline_row_counts_equal(
        self, results_text: str, corpus_files: dict[str, list[Path]]
    ):
        detail_rows = _DETAIL_ROW_RE.findall(results_text)
        expected_total = len(corpus_files["in_scope"]) + len(corpus_files["oos"])
        assert len(detail_rows) == expected_total, (
            f"Detail table has {len(detail_rows)} rows but corpus has "
            f"{expected_total} files. Mismatch indicates the table is "
            f"out of sync with bench/corpus/."
        )

        # Each row has 4 baseline cells (one per column). Confirm none are
        # missing by re-counting the cell tuples in each row.
        for row in detail_rows:
            # row tuple shape: (bc_id, c1n, c1d, c1verb, c2n, c2d, c2verb, ...)
            # = 1 + 4 * 3 = 13 elements
            assert len(row) == 13, (
                f"Detail row {row[0]!r} has {len(row)} captured fields; "
                f"expected 13 (BC id + 4 baseline cells of 3 fields each)"
            )

    def test_does_not_prove_disclaimer_present(self, results_text: str):
        """TP-27 contract: bench/RESULTS.md must carry the disclaimer
        that the benchmark does not prove security. Regression check
        in case --update-canonical ever stops writing the section.
        """
        assert "## What this benchmark does NOT prove" in results_text, (
            "RESULTS.md is missing the 'What this benchmark does NOT prove' "
            "H2 section. The TP-27 contract requires this disclaimer on every "
            "canonical regeneration."
        )
        assert "does not prove" in results_text, (
            "RESULTS.md missing 'does not prove' phrase in the disclaimer body"
        )

    def test_version_stamp_matches_pyproject(self, results_text: str):
        """Pin: bench/RESULTS.md "espalier version: X" line == pyproject version.

        Forces operators to run `python3 bench/run_benchmark.py
        --update-canonical` whenever pyproject is bumped. Without this
        contract, RESULTS.md drifts across releases (e.g., v0.7.4
        ships with a v0.7.3 version stamp because the regen step is
        a manual checklist item that gets missed). Failure message
        is the exact command an operator runs to fix it.
        """
        if tomllib is None:
            pytest.skip(
                "tomllib unavailable (Python <3.11 without tomli installed); "
                "install tomli to run this version-stamp parity test"
            )

        pyproject_path = REPO_ROOT / "pyproject.toml"
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
        pyproject_data = tomllib.loads(pyproject_text)
        live_version = pyproject_data["project"]["version"]

        match = re.search(r"^espalier version:\s+(\S+)", results_text, re.MULTILINE)
        assert match is not None, (
            "bench/RESULTS.md is missing the 'espalier version: X' header line"
        )
        stamped_version = match.group(1)
        assert stamped_version == live_version, (
            f"bench/RESULTS.md version stamp {stamped_version!r} != pyproject "
            f"version {live_version!r}. Run "
            f"`python3 bench/run_benchmark.py --update-canonical` from the "
            f"repo root to regenerate RESULTS.md against the current corpus "
            f"and pyproject version."
        )


class TestSummaryHasReadingGloss:
    """TP-99 B3: bench/RESULTS.md must carry the "by construction" gloss
    above the Summary table.

    Pre-TP-99 the table read as a self-indictment to a skeptic: a row
    showing "26 / 134" looks like a 19% block rate. The corpus is bypass
    classes by construction (the disclaimer above already says this in
    H2 prose, and the per-row Notes column says it for the no-effect
    baselines), but neither surfaced inline at the table where a first
    reader's eye lands. The gloss makes the framing impossible to miss.
    """

    def test_reading_gloss_present_above_summary(self, results_text: str):
        # The gloss must precede the Summary table's column header.
        summary_idx = results_text.find("## Summary")
        assert summary_idx != -1, "RESULTS.md missing '## Summary' section header"

        header_row_idx = results_text.find("| Baseline | In-scope blocked")
        assert header_row_idx != -1, "RESULTS.md missing Summary table header row"
        assert header_row_idx > summary_idx, (
            "Summary table header must come AFTER '## Summary'"
        )

        between = results_text[summary_idx:header_row_idx]
        assert "How to read this table" in between, (
            "Summary section must include 'How to read this table' gloss "
            "before the table header. Pre-TP-99 the table read as a "
            "self-indictment to skeptics."
        )
        assert "by construction" in between, (
            "Gloss must include the phrase 'by construction' to surface "
            "the corpus framing inline."
        )
        assert "delta" in between.lower(), (
            "Gloss must direct readers to compare deltas between rows, "
            "not interpret absolute numerators."
        )


class TestTomllibCompatShim:
    """Pin: this module must use the espalier._compat shim, never `import tomllib`.

    pyproject.toml declares `requires-python = ">=3.10"` but stdlib `tomllib`
    only exists from 3.11. A bare `import tomllib` crashes test collection on
    any Python 3.10 CI matrix row, killing every parity test in this file.
    The fix is the established shim in espalier/_compat.py.
    """

    def test_no_bare_tomllib_import_in_this_module(self):
        source = Path(__file__).read_text(encoding="utf-8")
        bare = re.findall(r"^\s*import\s+tomllib\b", source, re.MULTILINE)
        assert not bare, (
            "Bare `import tomllib` found in tests/test_bench_results_parity.py "
            "— crashes on Python 3.10. Use `from espalier._compat import tomllib` "
            "(the shim falls back to `tomli` on 3.10)."
        )
