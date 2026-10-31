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
    DRIFT_FETCH_ERROR,
    DRIFT_NONE,
    DRIFT_SEMANTIC,
    DRIFT_UNVERIFIABLE,
    compare_pin_to_fetched,
    normalize_quote_text,
    quoted_passages,
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
from espalier.refresh_externals import (
    BASE_BOUND_TESTS,
    PinReport,
    RefreshReport,
    bound_test_files,
    exit_code,
    run_bound_tests,
    run_refresh,
)


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
                       body: str = "## Section\n\n> Quoted excerpt from the upstream page.\n") -> Path:
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
    """Drift is read off the pin's quotes (DEF-744): every `>` passage must be
    on the fetched page, once pin and page pass through one normalisation. A
    whole-body diff reported high drift on every refresh, because a pin is a
    curated excerpt and never equals the page."""

    PAGE = (
        "# Hooks\n\nIntro prose the pin does not quote.\n\n"
        "Exit 0 means success. Exit 2 means a blocking error.\n\n"
        "Claude never sees stderr from a hook that exits 0.\n"
    )

    def _pin(self, tmp_path, body):
        return parse_pin(_scaffold_pin_dir(tmp_path, body=body))

    def test_every_quote_on_the_page_is_none(self, tmp_path):
        pin = self._pin(tmp_path, "## Exit codes\n\n> Exit 0 means success. Exit 2 means a blocking error.\n\n"
                                  "Espalier's own prose here is never compared.\n")
        report = compare_pin_to_fetched(pin, _fetch(self.PAGE))
        assert (report.drift_kind, report.summary) == (DRIFT_NONE, "all 1 quoted passages found upstream")

    def test_a_moved_sentence_is_semantic_and_named_by_its_file_line(self, tmp_path):
        """The red the old diff could not give: the quote is gone, and the
        report says which line of the pin to re-read."""
        pin = self._pin(tmp_path, "## Exit codes\n\n> Exit 1 blocks the tool call.\n")
        report = compare_pin_to_fetched(pin, _fetch(self.PAGE))
        assert report.drift_kind == DRIFT_SEMANTIC
        quote_line = pin.path.read_text(encoding="utf-8").splitlines().index("> Exit 1 blocks the tool call.") + 1
        assert f"(lines {quote_line})" in report.summary
        assert f"test-pin.md:{quote_line}: Exit 1 blocks the tool call." in report.unified_diff

    def test_a_pin_that_quotes_nothing_is_unverifiable_never_none(self, tmp_path):
        """A null must not read as clean: with no quote there is nothing upstream to check."""
        pin = self._pin(tmp_path, "## Notes\n\nOnly espalier's prose.\n")
        report = compare_pin_to_fetched(pin, _fetch("anything at all"))
        assert report.drift_kind == DRIFT_UNVERIFIABLE

    @pytest.mark.parametrize("quoted,page", [
        # a link keeps its text, whatever the text holds (`<` included)
        ("> Run [/recall <topic>](https://x/y#a) first.", "Run [/recall <topic>](/docs/r) first."),
        # emphasis and code ticks
        ("> The **only** way is `exit 2`.", "The *only* way is exit 2."),
        # a Markdown escape
        ("> The stop\\_hook\\_active field is set.", "The `stop_hook_active` field is set."),
        # a table row flattened with an em dash
        ("> `cwd` — Current working directory when the hook is invoked",
         "| `cwd` | Current working directory when the hook is invoked |"),
        # typographic quotes and a re-wrapped line
        ("> Claude Code’s “block”\n> outcome holds.", "Claude Code's \"block\" outcome holds."),
        # an HTML-ish block tag around the sentence
        ("> Without valid JSON, exit 1 is a non-blocking error.",
         "<Warning>\n  Without valid JSON, exit 1 is a non-blocking error.\n</Warning>"),
    ])
    def test_formatting_alone_is_not_drift(self, tmp_path, quoted, page):
        pin = self._pin(tmp_path, f"## S\n\n{quoted}\n")
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_NONE

    def test_an_elision_splits_a_quote_and_each_side_must_stand(self, tmp_path):
        page = "Alpha sentence stands here. Some middle text. Omega sentence stands too."
        pin = self._pin(tmp_path, "## S\n\n> Alpha sentence stands here. […] Omega sentence stands too.\n")
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_NONE
        gone = page.replace("Omega sentence stands too.", "")
        assert compare_pin_to_fetched(pin, _fetch(gone)).drift_kind == DRIFT_SEMANTIC

    def test_table_rows_are_judged_alone_and_a_bare_alignment_row_not_at_all(self, tmp_path):
        """A pin may quote two rows of a long table that are not adjacent on the
        page; a row of bars and colons has no words to find."""
        page = ("| Event | When it fires |\n| :---- | :---- |\n| `Setup` | First run |\n"
                "| `WorktreeCreate` | When a worktree is being created |\n| `Stop` | At the end |\n"
                "| `WorktreeRemove` | When a hook-made worktree is removed |\n")
        pin = self._pin(tmp_path, "## S\n\n> | Event | When it fires |\n> | :- | :- |\n"
                                  "> | `WorktreeCreate` | When a worktree is being created |\n"
                                  "> | `WorktreeRemove` | When a hook-made worktree is removed |\n")
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_NONE

    def test_a_quote_inside_a_code_fence_or_a_comment_is_not_a_quote(self, tmp_path):
        pin = self._pin(tmp_path, "## S\n\n> Exit 0 means success.\n\n```text\n> a shell redirect example\n```\n\n"
                                  "<!--\n> an editorial aside in a comment\n-->\n")
        passages = quoted_passages(pin)
        assert [q.text for q in passages] == ["Exit 0 means success."]

    def test_a_quote_from_another_source_counts_on_that_page(self, tmp_path):
        pins_dir = tmp_path / "docs" / "external"
        pins_dir.mkdir(parents=True)
        path = pins_dir / "two.md"
        path.write_text(
            "---\nsource_url: https://example.com/contract\nfetched: 2026-04-30\nsection: x\npurpose: x\n"
            "quote_sources:\n  - https://example.com/other\n---\n\n"
            "> Exit 0 means success.\n\n> A sentence only the other page prints, in full.\n",
            encoding="utf-8",
        )
        pin = parse_pin(path)
        assert pin.quote_sources == ("https://example.com/other",)
        other = _fetch("A sentence only the other page prints, in full.")
        assert compare_pin_to_fetched(pin, _fetch(self.PAGE)).drift_kind == DRIFT_SEMANTIC
        assert compare_pin_to_fetched(pin, _fetch(self.PAGE), others=[other]).drift_kind == DRIFT_NONE
        failed = _fetch("", status=404, error="HTTP 404")
        assert compare_pin_to_fetched(pin, _fetch(self.PAGE), others=[failed]).drift_kind == DRIFT_FETCH_ERROR

    def test_a_quote_source_must_be_https(self, tmp_path):
        pins_dir = tmp_path / "docs" / "external"
        pins_dir.mkdir(parents=True)
        bad = pins_dir / "bad.md"
        bad.write_text("---\nsource_url: https://example.com/x\nfetched: 2026-04-30\nsection: x\npurpose: x\n"
                       "quote_sources:\n  - http://example.com/plain\n---\n\nbody\n", encoding="utf-8")
        with pytest.raises(ValueError, match="quote_sources"):
            parse_pin(bad)

    def test_a_clause_added_before_the_period_is_drift(self, tmp_path):
        """A paragraph keeps its closing punctuation, so a qualifier upstream
        slips in before it is a moved quote (the failure-mode review drove
        nine such additions through the first cut as `none`)."""
        pin = self._pin(tmp_path, "## S\n\n> A timed-out hook doesn't block the tool call.\n")
        page = "A timed-out hook doesn't block the tool call unless onFailure is block."
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_SEMANTIC

    def test_a_row_is_not_satisfied_by_a_longer_names_row(self, tmp_path):
        """A row keeps its cell bars and a match needs word boundaries, so the
        `Stop` row is not found inside the `SubagentStop` row."""
        pin = self._pin(tmp_path, "## S\n\n> | `Stop` | Yes | Prevents the subagent from stopping |\n")
        page = "| `SubagentStop` | Yes | Prevents the subagent from stopping |\n"
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_SEMANTIC
        assert compare_pin_to_fetched(pin, _fetch(page + page.replace("SubagentStop", "Stop"))).drift_kind == DRIFT_NONE

    def test_a_quote_across_two_lines_of_a_callout_is_one_paragraph(self, tmp_path):
        """A callout's line-leading `>` is the page's markup, as the pin's own
        `>` is the pin's (DEF-3020): the worktrees page's two bullets, quoted
        as one passage, read as moved while the page kept `checkout. > cwd
        follows`. A word moved inside the callout is still drift, and a `>`
        inside a line is still text."""
        page = ("> [!NOTE]\n> **Hook paths don't follow the worktree.** After Claude enters one:\n>\n"
                "> * **`${CLAUDE_PROJECT_DIR}` stays put**: a hook still runs the script in the main checkout.\n"
                "> * **`cwd` follows Claude**: the `cwd` field in the input is the worktree root.\n")
        pin = self._pin(tmp_path, "## S\n\n"
                                  "> * **`${CLAUDE_PROJECT_DIR}` stays put**: a hook still runs the script\n"
                                  ">   in the main checkout.\n"
                                  "> * **`cwd` follows Claude**: the `cwd` field in the input is the worktree root.\n")
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_NONE
        moved = page.replace("the worktree root", "the project root")
        assert compare_pin_to_fetched(pin, _fetch(moved)).drift_kind == DRIFT_SEMANTIC
        assert normalize_quote_text("Run 2>&1 > out, then a → b.") == "run 2>&1 > out, then a -> b."

    def test_a_nested_quote_loses_every_marker_on_every_line(self, tmp_path):
        """The pin side of the same rule: a `> >` quote kept its inner `>` on
        every line after its first, where the page loses it on all of them."""
        page = "> > Exit 0 means success for the hook.\n> > Exit 2 means a blocking error.\n"
        pin = self._pin(tmp_path, f"## S\n\n{page}")
        assert compare_pin_to_fetched(pin, _fetch(page)).drift_kind == DRIFT_NONE
        assert [q.text for q in quoted_passages(pin)] == [
            "Exit 0 means success for the hook. Exit 2 means a blocking error."]

    def test_a_comment_opener_inside_a_fence_is_fence_text(self, tmp_path):
        """A fence is read first: a `<!--` inside one used to switch the
        parser into comment mode and swallow every quote after the fence."""
        pin = self._pin(tmp_path, "## S\n\n```html\n<!-- an example comment\n```\n\n> Exit 0 means success here.\n")
        assert [q.text for q in quoted_passages(pin)] == ["Exit 0 means success here."]

    def test_a_comment_splits_two_quotes_and_an_inline_one_is_dropped(self, tmp_path):
        pin = self._pin(tmp_path, "## S\n\n> First quoted sentence stands.\n<!-- an aside -->\n"
                                  "> Second quoted sentence stands. <!-- a note -->\n")
        assert [q.text for q in quoted_passages(pin)] == [
            "First quoted sentence stands.", "Second quoted sentence stands."]

    def test_fragments_too_short_to_check_are_counted_not_hidden(self, tmp_path):
        """The 12-character floor keeps a two-word quote from matching by
        chance; the summary says how many it skipped, and a pin whose every
        quote is that short is unverifiable, not clean."""
        pin = self._pin(tmp_path, "## S\n\n> Exit 0 means success here.\n\n> Exit 2 blocks.\n")
        report = compare_pin_to_fetched(pin, _fetch(self.PAGE.replace("success.", "success here.")))
        assert report.drift_kind == DRIFT_NONE and "1 quoted fragments too short to check" in report.summary
        short_only = self._pin(tmp_path / "b", "## S\n\n> Exit 2 blocks.\n")
        assert compare_pin_to_fetched(short_only, _fetch(self.PAGE)).drift_kind == DRIFT_UNVERIFIABLE

    @pytest.mark.parametrize("content,said", [
        ("<!DOCTYPE html><html><body>rendered</body></html>", "HTML"),
        ("   \n  ", "empty"),
    ])
    def test_a_page_that_is_html_or_empty_is_a_fetch_error(self, tmp_path, content, said):
        """Without the `.md` twin every quote would read as moved, and the
        candidate would be the rendered page."""
        pin = self._pin(tmp_path, "## S\n\n> Exit 0 means success.\n")
        report = compare_pin_to_fetched(pin, _fetch(content))
        assert report.drift_kind == DRIFT_FETCH_ERROR and said in report.summary

    def test_every_live_pin_quotes_something_checkable(self):
        """An unverifiable pin fails the weekly job; hold the live ones here,
        where a re-excerpt that turned every quote into prose is made."""
        repo_root = Path(__file__).resolve().parent.parent
        unchecked = [p.name for p in list_pins(repo_root) if not any(q.fragments for q in quoted_passages(p))]
        assert not unchecked, unchecked

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
        path = _scaffold_pin_dir(tmp_path, body="> A static upstream sentence.\n")
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
        path = _scaffold_pin_dir(tmp_path, body="> A static upstream body sentence.\n")
        def mock(url, **_):
            return _fetch("totally different upstream content.\n")
        # Bypass bound-tests subprocess (no test files in tmp_path).
        from espalier import refresh_externals
        monkeypatch.setattr(
            refresh_externals, "run_bound_tests",
            lambda root, pins=None: ("pass", "stubbed"),
        )
        report = run_refresh(tmp_path, apply=True, fetcher=mock)
        assert report.pins[0].candidate_path is not None
        candidate = tmp_path / report.pins[0].candidate_path
        assert candidate.exists()
        assert candidate.name.endswith(".candidate.md")
        # Original pin unchanged
        assert "A static upstream body sentence." in path.read_text(encoding="utf-8")
        # Bound tests ran and were captured.
        assert report.bound_tests_status == "pass"

    def test_apply_with_no_drift_skips_candidate(self, tmp_path, monkeypatch):
        path = _scaffold_pin_dir(tmp_path, body="> An exact upstream match sentence.\n")
        pin = parse_pin(path)
        def mock(url, **_):
            return _fetch(pin.body)
        from espalier import refresh_externals
        monkeypatch.setattr(
            refresh_externals, "run_bound_tests",
            lambda root, pins=None: ("pass", "stubbed"),
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
            lambda root, pins=None: ("pass", "stubbed"),
        )
        report = run_refresh(tmp_path, apply=False, pin_name="alpha", fetcher=mock)
        names = {p.pin_name for p in report.pins}
        assert names == {"alpha"}


class TestBoundTestsAreDerivedFromThePins:
    """DEF-744: the refresh ran a hardcoded two-file list while each pin's
    "What espalier asserts" section names its own tests, so two of three pins
    were never held to theirs. The set is now derived from the pin bodies."""

    def test_each_cited_test_joins_the_two_base_files(self, tmp_path):
        a = parse_pin(_scaffold_pin_dir(tmp_path, pin_name="a", body=(
            "> A quoted upstream sentence.\n\n## What espalier asserts against this excerpt\n\n"
            "- Verified by `tests/test_alpha.py::TestX` and tests/sub/test_beta.py.\n")))
        b = parse_pin(_scaffold_pin_dir(tmp_path, pin_name="b", body="> Another quoted sentence.\n"))
        assert bound_test_files([a, b]) == tuple(sorted(
            {"tests/test_alpha.py", "tests/sub/test_beta.py", *BASE_BOUND_TESTS}))

    def test_every_test_a_live_pin_cites_exists(self):
        """A pin citing a test that was renamed would fail every refresh by name;
        hold the live pins to it here, where the rename happens."""
        repo_root = Path(__file__).resolve().parent.parent
        files = bound_test_files(list_pins(repo_root))
        assert set(BASE_BOUND_TESTS) < set(files), files
        missing = [f for f in files if not (repo_root / f).is_file()]
        assert not missing, f"a pin cites a test file that does not exist: {missing}"

    def test_the_run_passes_the_derived_files_to_pytest(self, tmp_path, monkeypatch):
        pin = parse_pin(_scaffold_pin_dir(tmp_path, body="> Quote.\n\nSee tests/test_gamma.py.\n"))
        for rel in ("tests/test_gamma.py", *BASE_BOUND_TESTS):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("def test_x():\n    pass\n", encoding="utf-8")
        seen = {}

        class _Done:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def _run(cmd, **_kw):
            seen["cmd"] = cmd
            return _Done()

        from espalier import refresh_externals
        monkeypatch.setattr(refresh_externals.subprocess, "run", _run)
        assert run_bound_tests(tmp_path, [pin]) == ("pass", "ok")
        assert "tests/test_gamma.py" in seen["cmd"] and set(BASE_BOUND_TESTS) <= set(seen["cmd"])

    def test_a_tree_without_the_cited_tests_skips_them_and_says_so(self, tmp_path):
        """An adopter tree carries the seeded pins, not espalier's tests: a run
        there is not a failed claim. Files that exist still run."""
        pin = parse_pin(_scaffold_pin_dir(tmp_path, body="> Quote.\n"))
        status, output = run_bound_tests(tmp_path, [pin])
        assert status == "skipped" and "tests/test_documented_claims.py" in output

    def test_a_page_several_pins_quote_is_fetched_once(self, tmp_path):
        for name in ("one", "two"):
            pins_dir = tmp_path / "docs" / "external"
            pins_dir.mkdir(parents=True, exist_ok=True)
            (pins_dir / f"{name}.md").write_text(
                f"---\nsource_url: https://example.com/{name}\nfetched: 2026-04-30\nsection: x\npurpose: x\n"
                "quote_sources:\n  - https://example.com/shared\n---\n\n> A sentence the shared page prints.\n",
                encoding="utf-8")
        calls = []

        def mock(url, **_):
            calls.append(url)
            return _fetch("A sentence the shared page prints.")

        report = run_refresh(tmp_path, apply=False, fetcher=mock)
        assert [p.drift_kind for p in report.pins] == [DRIFT_NONE, DRIFT_NONE]
        assert sorted(calls) == ["https://example.com/one", "https://example.com/shared", "https://example.com/two"]

    def test_the_report_says_what_a_pass_means(self, tmp_path, monkeypatch):
        _scaffold_pin_dir(tmp_path, body="> A static upstream sentence.\n")
        from espalier import refresh_externals
        monkeypatch.setattr(refresh_externals, "run_bound_tests", lambda root, pins=None: ("pass", "stubbed"))
        report = run_refresh(tmp_path, apply=True, fetcher=lambda url, **_: _fetch("something else entirely"))
        assert report.pins[0].drift_kind == DRIFT_SEMANTIC
        bound = report.to_dict()["bound_tests"]
        assert bound["files"] == list(BASE_BOUND_TESTS) and "not these tests" in bound["meaning"]


class TestExitCode:
    """A pin the refresh could not check fails the run; moved quotes do not
    (the candidate and the report are the action)."""

    def _report(self, *kinds, status=None):
        pins = [PinReport(pin_name=f"p{i}", source_url="u", drift_kind=k, summary="", age_days=0)
                for i, k in enumerate(kinds)]
        return RefreshReport(pins=pins, bound_tests_status=status)

    def test_an_unverifiable_or_unreadable_pin_fails_and_moved_quotes_do_not(self):
        assert exit_code(self._report(DRIFT_NONE, DRIFT_SEMANTIC), apply=False) == 0
        assert exit_code(self._report(DRIFT_NONE, DRIFT_UNVERIFIABLE), apply=False) == 1
        assert exit_code(self._report(DRIFT_FETCH_ERROR), apply=False) == 1

    def test_failed_bound_tests_fail_an_applied_run_and_skipped_ones_do_not(self):
        assert exit_code(self._report(DRIFT_SEMANTIC, status="fail"), apply=True) == 1
        assert exit_code(self._report(DRIFT_SEMANTIC, status="skipped"), apply=True) == 0


class TestInteractiveLoop:
    def test_only_moved_quotes_are_offered(self, tmp_path, monkeypatch, capsys):
        """Accept replaces the pin with the raw page; an unverifiable pin has
        nothing to decide, so the prompt is never reached."""
        _scaffold_pin_dir(tmp_path, pin_name="quiet")
        from espalier import refresh_externals

        class _Drift:
            drift_kind = DRIFT_UNVERIFIABLE
            summary = "nothing quoted"
            unified_diff = ""

        monkeypatch.setattr(refresh_externals, "refresh_pin", lambda pin: (_Drift(), None))

        def _never(*_a, **_k):
            raise AssertionError("the prompt was offered for an unverifiable pin")

        monkeypatch.setattr("builtins.input", _never)
        assert refresh_externals._interactive_loop(tmp_path, None) == 0
        assert "unverifiable" in capsys.readouterr().out

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
