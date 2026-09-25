"""Tests for the refresh-externals subsystem — TP-11 §H.

Pins the parser, the diff heuristic, and the dry-run / apply CLI
flows that keep ``docs/external/*`` files in sync with their
upstream sources. The fetcher is always mocked — these tests must
run hermetically; the real-network refresh happens in
``.github/workflows/refresh-externals.yml``. Without this contract
a parser regression could silently let a malformed upstream
document apply cleanly into the local copy, polluting downstream
contract tests that read those files for ground truth (e.g.,
``test_hook_event_contracts`` parses ``cc-hook-protocol.md`` for
the official event list).

Stem ``test_refresh_externals`` is registered under ``integration``
in ``tests/conftest.py::_MARKER_RULES``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from espalier.external_diff import (
    DRIFT_COSMETIC,
    DRIFT_FETCH_ERROR,
    DRIFT_NONE,
    DRIFT_SEMANTIC,
    compare_pin_to_fetched,
    write_candidate,
)
from espalier.external_fetch import FetchResult
from espalier.external_pins import (
    _frontmatter_block,
    _split_frontmatter,
    compute_body_hash,
    list_pins,
    parse_pin,
)
from espalier.refresh_externals import run_refresh


# ── Frontmatter extraction (TP-313c C-2) ────────────────────────────


class TestFrontmatterBlockHelper:
    """The two pin *writers* (write_candidate, _rebuild_with_new_body) share
    ``_frontmatter_block`` (raw block WITH delimiters; raises on malformed with
    the caller's own message). The *parser* ``_split_frontmatter`` deliberately
    does NOT reuse it — it returns the inner yaml and never raises. Pin both so
    the consolidation stays behavior-preserving and the intentional twin split
    stays honest.
    """

    GOLDEN = "---\nname: x\nfetched: 2026-01-01\n---\n\n# Body\n\ntext\n"

    def test_block_is_whole_block_with_delimiters(self):
        block = _frontmatter_block(self.GOLDEN, malformed_msg="bad")
        assert block == "---\nname: x\nfetched: 2026-01-01\n---"
        assert block.startswith("---\n") and block.endswith("\n---")

    def test_malformed_raises_the_callers_message(self):
        with pytest.raises(ValueError, match="CALLER MSG"):
            _frontmatter_block("---\nno closing delimiter\n", malformed_msg="CALLER MSG")

    def test_writer_helper_and_parser_are_distinct_shapes(self):
        block = _frontmatter_block(self.GOLDEN, malformed_msg="bad")
        fm, body = _split_frontmatter(self.GOLDEN)
        # writer helper keeps the delimiters; parser returns the inner yaml only
        assert block == "---\nname: x\nfetched: 2026-01-01\n---"
        assert fm == "name: x\nfetched: 2026-01-01"
        assert "# Body" in body
        # the reason they are not merged: parser never raises on malformed,
        # the writer helper does.
        assert _split_frontmatter("---\nno closing\n") == ("", "---\nno closing\n")


# ── Fixtures ────────────────────────────────────────────────────────


def _scaffold_pin_dir(tmp_path: Path, pin_name: str = "test-pin",
                       fetched: str = "2026-04-30",
                       body: str = "## Section\n\nQuoted excerpt.\n") -> Path:
    """Create docs/external/<name>.md with valid frontmatter."""
    pins_dir = tmp_path / "docs" / "external"
    pins_dir.mkdir(parents=True, exist_ok=True)
    pin_path = pins_dir / f"{pin_name}.md"
    pin_path.write_text(
        f"""---
source_url: https://example.com/contract
fetched: {fetched}
section: "Test section"
purpose: |
  Testing pin parser.
refresh_policy: weekly
---

{body}""",
        encoding="utf-8",
    )
    return pin_path


def _fetch(content: str, *, status: int = 200, error: str | None = None) -> FetchResult:
    return FetchResult(
        url="https://example.com/contract",
        status_code=status,
        content=content,
        fetched_at=datetime.now(timezone.utc),
        final_url="https://example.com/contract",
        error=error,
    )


# ── Pin parser ──────────────────────────────────────────────────────


class TestPinParser:
    def test_parses_valid_pin(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path)
        pin = parse_pin(path)
        assert pin.source_url == "https://example.com/contract"
        assert pin.fetched == date(2026, 4, 30)
        assert pin.section == "Test section"
        assert pin.refresh_policy == "weekly"
        assert "Quoted excerpt" in pin.body

    def test_rejects_missing_required_field(self, tmp_path):
        pins_dir = tmp_path / "docs" / "external"
        pins_dir.mkdir(parents=True)
        bad = pins_dir / "bad.md"
        # Missing `purpose`.
        bad.write_text(
            "---\nsource_url: https://example.com/x\nfetched: 2026-04-30\n"
            "section: x\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=r"missing \d+ required frontmatter field"):
            parse_pin(bad)

    def test_rejects_missing_frontmatter(self, tmp_path):
        pins_dir = tmp_path / "docs" / "external"
        pins_dir.mkdir(parents=True)
        bad = pins_dir / "bad.md"
        bad.write_text("# no frontmatter\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no YAML frontmatter"):
            parse_pin(bad)

    def test_rejects_invalid_refresh_policy(self, tmp_path):
        pins_dir = tmp_path / "docs" / "external"
        pins_dir.mkdir(parents=True)
        bad = pins_dir / "bad.md"
        bad.write_text(
            "---\nsource_url: https://example.com/x\nfetched: 2026-04-30\n"
            "section: x\npurpose: x\nrefresh_policy: hourly\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="refresh_policy"):
            parse_pin(bad)

    def test_skips_readme_in_list_pins(self, tmp_path):
        _scaffold_pin_dir(tmp_path)
        readme = tmp_path / "docs" / "external" / "README.md"
        readme.write_text("# index\n", encoding="utf-8")
        pins = list_pins(tmp_path)
        assert len(pins) == 1
        assert pins[0].path.name == "test-pin.md"

    def test_skips_candidate_files(self, tmp_path):
        _scaffold_pin_dir(tmp_path)
        cand = tmp_path / "docs" / "external" / "test-pin.candidate.md"
        cand.write_text("---\n---\n\nbody\n", encoding="utf-8")
        pins = list_pins(tmp_path)
        # Only the original pin — candidate files are review artifacts.
        assert len(pins) == 1

    def test_compute_body_hash_normalizes_trailing_whitespace(self):
        a = "line one\nline two\n"
        b = "line one  \nline two\n\n"
        assert compute_body_hash(a) == compute_body_hash(b)


# ── Drift detection ─────────────────────────────────────────────────


class TestDriftDetection:
    def test_identical_content_drift_kind_none(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path, body="## Title\n\nThe contract.\n")
        pin = parse_pin(path)
        report = compare_pin_to_fetched(pin, _fetch(pin.body))
        assert report.drift_kind == DRIFT_NONE

    def test_emphasis_change_is_cosmetic(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path, body="## Title\n\nThe **only** way.\n")
        pin = parse_pin(path)
        modified = pin.body.replace("**only**", "*only*")
        report = compare_pin_to_fetched(pin, _fetch(modified))
        assert report.drift_kind == DRIFT_COSMETIC

    def test_anchor_id_added_is_cosmetic(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path, body="## Title\n\nText.\n")
        pin = parse_pin(path)
        modified = pin.body.replace("## Title", "## Title {#title}")
        report = compare_pin_to_fetched(pin, _fetch(modified))
        assert report.drift_kind == DRIFT_COSMETIC

    def test_sentence_meaning_change_is_semantic(self, tmp_path):
        path = _scaffold_pin_dir(
            tmp_path, body="## Title\n\nExit 0 means success. Exit 2 means block.\n"
        )
        pin = parse_pin(path)
        modified = pin.body.replace("Exit 0 means success", "Exit 0 means failure")
        report = compare_pin_to_fetched(pin, _fetch(modified))
        assert report.drift_kind == DRIFT_SEMANTIC
        assert "magnitude" in report.summary

    def test_large_rewrite_is_semantic_high_magnitude(self, tmp_path):
        path = _scaffold_pin_dir(
            tmp_path, body="## A\n\nshort body.\n",
        )
        pin = parse_pin(path)
        modified = "## A\n\n" + "completely different content.\n" * 20
        report = compare_pin_to_fetched(pin, _fetch(modified))
        assert report.drift_kind == DRIFT_SEMANTIC
        assert "high" in report.summary

    def test_small_semantic_change_is_low_magnitude(self, tmp_path):
        """TP-174a: a 1-of-21-line semantic change must read magnitude 'low'.
        Pre-fix the ratio was computed on the normalized single-line form, so
        SequenceMatcher always returned 1.0 ('high') for any non-cosmetic edit."""
        body = "## A\n\n" + "".join(f"line {i}\n" for i in range(20))
        path = _scaffold_pin_dir(tmp_path, body=body)
        pin = parse_pin(path)
        modified = body.replace("line 5\n", "line 5 changed materially\n")
        report = compare_pin_to_fetched(pin, _fetch(modified))
        assert report.drift_kind == DRIFT_SEMANTIC
        assert "low" in report.summary
        assert "high" not in report.summary

    def test_fetch_error_drift_kind_fetch_error(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path)
        pin = parse_pin(path)
        report = compare_pin_to_fetched(
            pin, _fetch("", status=500, error="HTTP 500: server"),
        )
        assert report.drift_kind == DRIFT_FETCH_ERROR
        assert "fetch failed" in report.summary


# ── write_candidate ─────────────────────────────────────────────────


class TestWriteCandidate:
    def test_candidate_has_pin_frontmatter_and_new_body(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path, body="old body.\n")
        pin = parse_pin(path)
        cand = write_candidate(pin, "## NEW\n\nnew body.\n")
        text = cand.read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "source_url:" in text
        assert "## NEW" in text

    def test_candidate_does_not_overwrite_pin(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path, body="old body.\n")
        pin = parse_pin(path)
        original = path.read_text(encoding="utf-8")
        write_candidate(pin, "totally different.\n")
        assert path.read_text(encoding="utf-8") == original


# ── run_refresh (dry-run + apply, both with mocked fetcher) ─────────


class TestRefreshDryRun:
    def test_dry_run_writes_no_files(self, tmp_path):
        path = _scaffold_pin_dir(tmp_path, body="static.\n")
        pin = parse_pin(path)
        # Mock fetcher returns drift-inducing content
        def mock(url, **_):
            return _fetch("totally different content.\n")
        report = run_refresh(tmp_path, apply=False, fetcher=mock)
        assert len(report.pins) == 1
        assert report.pins[0].drift_kind == DRIFT_SEMANTIC
        # No candidate written; bound tests not run.
        assert report.pins[0].candidate_path is None
        assert report.bound_tests_status is None
        candidates = list((tmp_path / "docs" / "external").glob("*.candidate.md"))
        assert candidates == []

    def test_dry_run_reports_age(self, tmp_path):
        _scaffold_pin_dir(tmp_path, fetched="2026-04-01")
        def mock(url, **_):
            return _fetch("static.\n")  # cosmetic at most
        report = run_refresh(tmp_path, apply=False, fetcher=mock)
        # Today (2026-05-01 per env) − 2026-04-01 = 30 days; allow ±2d slack.
        age = report.pins[0].age_days
        assert age >= 28, f"unexpected age_days: {age}"


class TestRefreshApply:
    def test_apply_writes_candidate_for_drift(self, tmp_path, monkeypatch):
        path = _scaffold_pin_dir(tmp_path, body="static body.\n")
        def mock(url, **_):
            return _fetch("totally different upstream content.\n")
        # Bypass bound-tests subprocess (no test files in tmp_path).
        from espalier import refresh_externals
        monkeypatch.setattr(
            refresh_externals, "run_bound_tests",
            lambda root: ("pass", "stubbed"),
        )
        report = run_refresh(tmp_path, apply=True, fetcher=mock)
        assert report.pins[0].candidate_path is not None
        candidate = tmp_path / report.pins[0].candidate_path
        assert candidate.exists()
        assert candidate.name.endswith(".candidate.md")
        # Original pin unchanged
        assert "static body." in path.read_text(encoding="utf-8")
        # Bound tests ran and were captured.
        assert report.bound_tests_status == "pass"

    def test_apply_with_no_drift_skips_candidate(self, tmp_path, monkeypatch):
        path = _scaffold_pin_dir(tmp_path, body="exact match.\n")
        pin = parse_pin(path)
        def mock(url, **_):
            return _fetch(pin.body)
        from espalier import refresh_externals
        monkeypatch.setattr(
            refresh_externals, "run_bound_tests",
            lambda root: ("pass", "stubbed"),
        )
        report = run_refresh(tmp_path, apply=True, fetcher=mock)
        assert report.pins[0].drift_kind == DRIFT_NONE
        assert report.pins[0].candidate_path is None
        # No candidate files written
        candidates = list((tmp_path / "docs" / "external").glob("*.candidate.md"))
        assert candidates == []
        # Bound tests NOT re-run when nothing was written.
        assert report.bound_tests_status is None

    def test_apply_pin_filter(self, tmp_path, monkeypatch):
        _scaffold_pin_dir(tmp_path, pin_name="alpha")
        _scaffold_pin_dir(tmp_path, pin_name="beta")
        def mock(url, **_):
            return _fetch("changed.\n")
        from espalier import refresh_externals
        monkeypatch.setattr(
            refresh_externals, "run_bound_tests",
            lambda root: ("pass", "stubbed"),
        )
        report = run_refresh(tmp_path, apply=False, pin_name="alpha", fetcher=mock)
        names = {p.pin_name for p in report.pins}
        assert names == {"alpha"}


class TestInteractiveLoop:
    def test_no_stdin_aborts_cleanly(self, tmp_path, monkeypatch, capsys):
        """TP-275 3-A: under ``--interactive`` with no stdin the bare ``input()``
        raises ``EOFError``; ``_interactive_loop`` must catch it, print a clean
        message, and return 1 instead of propagating a raw traceback."""
        _scaffold_pin_dir(tmp_path, pin_name="drifter")
        from espalier import refresh_externals

        class _Drift:
            drift_kind = "semantic"  # not DRIFT_NONE / DRIFT_FETCH_ERROR -> prompts
            summary = "upstream changed"
            unified_diff = "- old\n+ new"

        class _Fetched:
            content = "new body\n"
            fetched_at = datetime.now(timezone.utc)

        monkeypatch.setattr(
            refresh_externals, "refresh_pin", lambda pin: (_Drift(), _Fetched()),
        )

        def _no_input(*_a, **_k):
            raise EOFError

        monkeypatch.setattr("builtins.input", _no_input)
        rc = refresh_externals._interactive_loop(tmp_path, None)
        assert rc == 1
        assert "no input" in capsys.readouterr().out.lower()


# ── Live-repo sanity ────────────────────────────────────────────────


def test_live_repo_pins_parse_cleanly():
    """The current cc-hook-protocol pin must parse without error."""
    repo_root = Path(__file__).resolve().parent.parent
    pins = list_pins(repo_root)
    assert pins, "live repo should have at least one pin"
    by_name = {p.name for p in pins}
    assert "cc-hook-protocol" in by_name
