"""Mechanical contracts for the SessionStart banner + orientation surface.

These GUARD the banner against silent regression -- the kind we caught only
because nothing tested the budget (three live truncations went unnoticed). They
PIN that the machinery works AS STATED: byte budgets, honest boundary truncation
(never mid-word), the visible bloat flag, the section allowlist, airtight
self-host gating, and no-duplicate-content. They deliberately do NOT judge
relevance/completeness -- that is the operator's handoff Notes + periodic review,
because relevance is a judgment a scanner cannot make.

The module is loaded by path (tools/cc/ has zero espalier imports and runs
standalone), mirroring the loader in test_hooks.py::TestSessionStart.
"""
# slow-exempt: the one subprocess call is a single `git show HEAD:<one hook module>`
# read (~10 ms) in TestSeedHistoryOnlyGrows; it skips on a git-less tree.
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from _git_oracle import _git_env  # noqa: E402

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"


def _load():
    spec = importlib.util.spec_from_file_location("_ss_banner", HOOKS_DIR / "session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── _truncate_on_boundary: honest, never mid-word ──────────────────────────

class TestTruncateOnBoundary:
    def test_under_budget_unchanged(self):
        mod = _load()
        text = "short enough\nto fit"
        assert mod._truncate_on_boundary(text, 10_000, "[cut]") == text

    def test_over_budget_respects_ceiling_and_marks(self):
        mod = _load()
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
        out = mod._truncate_on_boundary(text, 30, "\n[cut]")
        assert out.endswith("[cut]"), "truncation must announce itself"
        # body (without the marker) must fit the budget
        body = out[: -len("\n[cut]")]
        assert len(body.encode("utf-8")) <= 30

    def test_never_splits_mid_word(self):
        mod = _load()
        # a single long word past the budget: cutting must NOT leave a partial word
        text = "wordone wordtwo wordthree wordfour wordfive"
        out = mod._truncate_on_boundary(text, 20, " ...")
        body = out[: -len(" ...")].strip()
        # every retained token is a whole word from the source
        source_words = set(text.split())
        for tok in body.split():
            assert tok in source_words, f"mid-word fragment leaked: {tok!r}"

    def test_prefers_newline_boundary(self):
        mod = _load()
        text = "line one here\nline two here\nline three here"
        out = mod._truncate_on_boundary(text, 18, "\n[cut]")
        body = out[: -len("\n[cut]")]
        # cut lands on a newline boundary -> no trailing partial line
        assert body == "line one here"

    def test_wordless_token_over_budget_never_leaks_a_fragment(self):
        """The honesty contract's hardest case: an over-budget ASCII token with
        NO whitespace boundary must NOT emit a mid-word byte-prefix. (Regression
        for the adversarial finding: the old `cut > 0` skip leaked a half-word.)
        This pure-ASCII case still drops the fragment WHOLE — the #7 space-less
        fallback below is script-aware and does not touch it."""
        mod = _load()
        out = mod._truncate_on_boundary("antidisestablishmentarianism", 10, " …")
        body = out[: -len(" …")].strip()
        assert body == "", f"leaked a mid-word fragment: {body!r}"
        assert out.endswith("…")

    def test_spaceless_cjk_headline_keeps_head_not_emptied(self):
        """#7: a space-less SCRIPT (CJK/Thai) over budget must NOT vanish to just
        the marker — every char is whole, so keep the head via a mid-char-safe
        byte cut. Pre-fix the no-boundary branch set clipped='' and the entire
        headline content disappeared."""
        mod = _load()
        cjk = "日本語のヘッドラインで空白がないためバジェットを超える長い見出し"
        out = mod._truncate_on_boundary(cjk, 20, " …")
        body = out[: -len(" …")].strip()
        assert body, "space-less CJK headline vanished entirely"
        assert cjk.startswith(body), f"kept head is not a clean prefix: {body!r}"
        # Output is valid UTF-8 (never a split multibyte sequence).
        out.encode("utf-8").decode("utf-8")
        assert out.endswith("…")

    def test_spaceless_url_headline_keeps_head(self):
        """#7 sister: a long URL/token with no whitespace keeps a meaningful
        prefix rather than vanishing."""
        mod = _load()
        url = "https://example.com/a/very/long/path/that/exceeds/the/byte/budget/xyz"
        out = mod._truncate_on_boundary(url, 25, " …")
        body = out[: -len(" …")].strip()
        assert body.startswith("https://example.com"), body
        assert out.endswith("…")

    def test_boundary_at_index_zero_is_honored(self):
        """A leading-space then a long wordless token: the only boundary is at
        index 0 and must be honored (the `>= 0` fix), not skipped."""
        mod = _load()
        out = mod._truncate_on_boundary(" verylongtokenwithnospaces", 12, " …")
        body = out[: -len(" …")].strip()
        assert body == "", f"index-0 boundary skipped -> mid-word leak: {body!r}"


# ─── _bounded: generous soft budget + VISIBLE flag, never silent ────────────

class TestBounded:
    def test_under_soft_budget_passes_whole_no_flag(self):
        mod = _load()
        flags: list[str] = []
        text = "a normal-length section"
        assert mod._bounded("goal", text, flags) == text
        assert flags == []

    def test_over_soft_budget_truncates_and_flags(self):
        mod = _load()
        flags: list[str] = []
        soft = mod._SOFT_BUDGETS["memory"]
        text = "word " * (soft)  # comfortably over the soft budget
        out = mod._bounded("memory", text, flags)
        assert len(out.encode("utf-8")) <= soft + 80, "must be bounded to ~soft budget"
        # The inline trim marker names the CORRECT source for this section.
        assert "trimmed to fit" in out and "ESPALIER_MEMORY.md" in out
        # Flag names the section, signals bloat, AND points at the CORRECT source
        # file for THIS section (memory -> ESPALIER_MEMORY.md, not a hardcoded cc/GOAL.md).
        assert len(flags) == 1 and "memory" in flags[0] and "is large" in flags[0]
        assert "ESPALIER_MEMORY.md" in flags[0]

    def test_unknown_section_passes_through_unbounded(self):
        mod = _load()
        flags: list[str] = []
        text = "x" * 50_000
        assert mod._bounded("not_a_section", text, flags) == text
        assert flags == []

    def test_empty_text_is_noop(self):
        mod = _load()
        flags: list[str] = []
        assert mod._bounded("goal", "", flags) == ""
        assert flags == []

    def test_goal_over_soft_under_hard_rides_whole(self):
        # TP-241: GOAL is FLAGGED at soft but rides through WHOLE up to the hard
        # cap, so the goal-proper (below the perishable Notes head) is not cut.
        mod = _load()
        flags: list[str] = []
        soft = mod._SOFT_BUDGETS["goal"]
        hard = mod._GOAL_HARD_CAP
        text = "word " * (((soft + hard) // 2) // 5)  # strictly between soft and hard
        assert soft < len(text.encode("utf-8")) < hard
        out = mod._bounded("goal", text, flags, hard_cap=hard)
        assert out == text, "over-soft-but-under-hard goal must ride through whole"
        assert len(flags) == 1 and "is large" in flags[0], "still flagged"
        assert "cc/GOAL.md" in flags[0]

    def test_goal_over_hard_cap_still_truncates(self):
        mod = _load()
        flags: list[str] = []
        hard = mod._GOAL_HARD_CAP
        text = "word " * ((hard + 3_000) // 5)  # well over the hard cap
        out = mod._bounded("goal", text, flags, hard_cap=hard)
        assert len(out.encode("utf-8")) <= hard + 80
        assert "trimmed to fit" in out and "cc/GOAL.md" in out

    # ── keep_tail: the goal-proper must survive, at ANY source size ──────────
    #
    # Every assertion below exists because a WRONG implementation passed without
    # it. The first cut of this test passed a raw byte-tail, a whole-sections-only
    # impl, a drop-the-middle impl and a reverse-order impl; only "just raise the
    # cap" reddened. These pin the docstring's honesty claims, not just the
    # headline behaviour.

    @staticmethod
    def _goal_text(notes_body: str) -> str:
        # Header read from the MODULE, never re-typed. The startup hedge and the
        # compaction rewrite share `_GOAL_HEADER`, and a literal copied here
        # would let this fixture keep passing against a header the banner no
        # longer emits -- the same exact-string drift the constants removed.
        return (
            _load()._GOAL_HEADER + "\n"
            "# Project Goal & Build Progress\n\n_Updated: 2026-08-22._\n\n"
            "## Notes to next session\n\n" + notes_body +
            "\n\n## Next gate\n\nthe one thing standing between HEAD and a cut.\n"
            "\n## How close\n\nthe honest distance to done.\n"
        )

    @staticmethod
    def _headings(text: str) -> "list[str]":
        return [ln for ln in text.splitlines() if ln.startswith("## ")]

    def test_goal_over_hard_cap_keeps_the_goal_proper_not_the_notes_head(self):
        """cc/GOAL.md is newest-PERISHABLE-first: the handoff Notes block heads the
        file and the goal-proper trails it, so a head-keeping cut delivers exactly
        the part that does not matter. TP-241 mitigated this with a hard cap, which
        holds only while the file stays under the number -- cc/GOAL.md outgrew it
        (6,785B vs 4,500B) and the banner shipped 0 bytes of goal-proper for weeks.
        Raising the cap re-arms the same trap, so the contract is DIRECTIONAL.
        """
        mod = _load()
        flags: "list[str]" = []
        hard = mod._GOAL_HARD_CAP
        text = self._goal_text("perishable handoff prose that must yield first.\n" * 120)
        assert len(text.encode("utf-8")) > hard, "fixture must exceed the hard cap"

        out = mod._bounded("goal", text, flags, hard_cap=hard, keep_tail=True)

        assert "## Next gate" in out and "## How close" in out, (
            "the goal-proper was cut instead of the perishable Notes head"
        )
        assert "the honest distance to done." in out, "trailing section body lost"
        assert "_Updated:" in out, "the preamble's staleness signal was dropped"
        assert "trimmed" in out, "the cut must announce itself"
        assert len(out.encode("utf-8")) <= hard + 120, "still bounded"
        assert len(flags) == 1 and "cc/GOAL.md" in flags[0], "still flagged at soft"

    def test_keep_tail_emits_whole_sections_in_source_order(self):
        """Kills a raw byte-tail, a reverse-order impl, and a drop-the-middle impl.

        The docstring promises 'whole sections only ... a reader never meets a
        section that begins mid-sentence'. Nothing pinned that until this."""
        mod = _load()
        hard = mod._GOAL_HARD_CAP
        text = self._goal_text("wrapped perishable note line.\n" * 150)
        out = mod._bounded("goal", text, [], hard_cap=hard, keep_tail=True)

        kept, source = self._headings(out), self._headings(text)
        assert kept, "no section survived"
        for h in kept:
            assert h in source, f"emitted a heading absent from the source: {h!r}"
        assert kept == [h for h in source if h in kept], (
            f"sections were reordered: {kept} vs source order {source}"
        )
        for h in kept:
            body_out = out.split(h, 1)[1]
            body_src = text.split(h, 1)[1]
            head = body_out.split("\n[goal section", 1)[0].rstrip()
            assert body_src.startswith(head), (
                f"section {h!r} does not begin at its source start -- a mid-section "
                f"cut leaked; got {head[:60]!r}"
            )

    def test_keep_tail_spends_its_budget_on_an_unwrapped_notes_block(self):
        """The bare-heading regression, driven.

        _truncate_on_boundary cuts to the LATEST whitespace boundary. When that
        preferred newlines unconditionally, a Notes block written as one long
        unwrapped line left only the newline ENDING THE HEADING inside the window
        -- a 4,183-byte allowance returned 24 bytes and the banner delivered 322B
        of a 4,500B budget with an empty '## Notes' heading, while passing green.
        Nothing enforces that cc/GOAL.md stays hard-wrapped, so this is the shape
        that must not regress."""
        mod = _load()
        hard = mod._GOAL_HARD_CAP
        text = self._goal_text("perishable handoff prose that must yield first. " * 140)
        out = mod._bounded("goal", text, [], hard_cap=hard, keep_tail=True)

        assert "## Next gate" in out and "## How close" in out, "goal-proper lost"
        assert "perishable handoff prose" in out, (
            "the Notes section came back as a BARE HEADING -- the partial path "
            "delivered no body"
        )
        assert len(out.encode("utf-8")) >= hard * 0.8, (
            f"only {len(out.encode('utf-8'))}B of a {hard}B budget was spent -- the "
            f"perishable head was dropped wholesale instead of yielding gradually"
        )

    def test_keep_tail_never_emits_a_heading_with_no_body(self):
        """The honesty contract 'a section is never emitted empty', pinned.

        Even with the latest-whitespace boundary, a section whose body carries NO
        whitespace at all leaves the heading's own newline as the only boundary in
        the window, so the partial path can still come back as a bare heading. The
        allowance is therefore not the gate -- DELIVERED bytes are. A heading
        followed immediately by the trim marker is content-free noise that spends
        the reader's attention and the banner's budget on nothing."""
        mod = _load()
        hard = mod._GOAL_HARD_CAP
        text = (
            "hdr\n_Updated: x._\n\n## Notes to next session\n"
            + ("x" * 6_000)                      # one space-less run: no boundary
            + "\n\n## Next gate\n\nthe real trailing body.\n"
        )
        out = mod._bounded("goal", text, [], hard_cap=hard, keep_tail=True)
        assert "the real trailing body." in out, "goal-proper lost"
        for line in out.splitlines():
            if line.startswith("## "):
                rest = out.split(line, 1)[1].lstrip()
                assert not rest.startswith("[goal section"), (
                    f"emitted {line!r} as a BARE HEADING -- a section with a marker "
                    f"and no body. Gate the partial path on delivered bytes, not on "
                    f"the allowance."
                )

    def test_keep_tail_last_section_alone_over_budget_keeps_that_section(self):
        """The last-resort branch must head-keep the FINAL SECTION, not the whole
        document. Head-keeping the document restores this function's own defect:
        the perishable head survives and the goal-proper does not. Driven before
        the fix: 0 bytes of goal-proper, full Notes retained."""
        mod = _load()
        hard = mod._GOAL_HARD_CAP
        text = (
            "preamble\n_Updated: x._\n\n## Notes\n\n"
            + ("perishable note. " * 260)
            + "\n\n## Where we are\n\n"
            + ("the real goal-proper body. " * 300) + "\n"
        )
        out = mod._bounded("goal", text, [], hard_cap=hard, keep_tail=True)
        assert "the real goal-proper body." in out, (
            "the sole trailing section was dropped -- the original defect, restored"
        )
        assert "perishable note." not in out, "the perishable head survived instead"

    def test_keep_tail_ignores_a_heading_inside_a_fenced_block(self):
        """Sister-site rule: post_write_check.py and _recall.py both track fences
        because a '## ' inside ``` is prose ABOUT a heading. _recall.py records the
        measured harm -- a phantom section that also STOLE a genuine bullet. A
        fence-blind split here also emits an unbalanced ``` that swallows the rest
        of the banner for any markdown-aware reader."""
        mod = _load()
        hard = mod._GOAL_HARD_CAP
        text = (
            "hdr\n\n## Notes\n\n```\n## this is inside a fence\n```\n"
            + ("wrapped note line here.\n" * 300)
            + "\n## Next gate\n\nthe real trailing body.\n"
        )
        out = mod._bounded("goal", text, [], hard_cap=hard, keep_tail=True)
        assert "the real trailing body." in out, "goal-proper lost"
        assert out.count("```") % 2 == 0, (
            "emitted an unbalanced code fence -- the cut split a fenced block"
        )

    def test_every_soft_budget_section_is_generous(self):
        """Soft budgets must be generous enough that normal content rides whole
        -- a guard against silently re-tightening into the lossy-clip regime."""
        mod = _load()
        for name, soft in mod._SOFT_BUDGETS.items():
            assert soft >= 1_000, f"{name} soft budget {soft} is too tight to be 'generous'"


# ─── _memory_headline: honest headline, not a mid-word byte slice ────────────

class TestMemoryHeadline:
    def test_bold_lead_extracted_whole_words(self):
        mod = _load()
        row = (
            "| 2026-06-29 **SessionStart priming phase shipped four commits "
            "with a great many words that run well past the headline cap so the "
            "truncation behaviour is actually exercised here** | body body body | more |"
        )
        out = mod._memory_headline(row)
        assert out.startswith("- 2026-06-29 ")
        assert "**" not in out, "bold markers must be stripped"
        assert "body body" not in out, "the long body cell must NOT leak into the headline"
        # whatever survived the cap must be whole words from the bold lead
        lead_words = set(row.split("**")[1].split())
        for tok in out.replace("- 2026-06-29 ", "").replace("...", "").split():
            assert tok in lead_words, f"mid-word fragment leaked: {tok!r}"

    def test_long_row_capped_but_present(self):
        mod = _load()
        row = "| 2026-06-28 " + "x" * 3000 + " | note |"
        out = mod._memory_headline(row)
        assert out.startswith("- 2026-06-28")
        assert len(out.encode("utf-8")) <= mod._MEMORY_HEADLINE_BYTES + 32

    def test_plain_row_no_bold_uses_first_cell(self):
        mod = _load()
        out = mod._memory_headline("| 2026-06-15 a plain entry | note |")
        assert out == "- 2026-06-15 a plain entry"


# ─── _footgun_pointer: name a catalog only when it HAS something ────────────

class TestFootgunPointerContentOracle:
    """The pointer NAMES a catalog to the model, so presence is the wrong test.

    ``init`` seeds ``docs/SHARP_EDGES.md`` as a near-empty scaffold. A pointer
    that names it advertises an empty file -- and the banner's own line tells the
    reader to go pull it. The oracle is per-file content, derived, so a doc that
    ships full (``docs/FAILURE_MODES.md``) passes on its own sections whether or
    not the operator has touched it.
    """

    def _seed_body(self) -> str:
        """The LIVE seeded scaffold, not a hand-copy of it -- so a reseed that
        changes the stub's shape is exercised here rather than drifting."""
        repo = HOOKS_DIR.parent.parent.parent
        return (repo / "espalier" / "assets" / "seed" / "SHARP_EDGES.md").read_text(
            encoding="utf-8"
        )

    def test_seeded_scaffold_is_not_named(self, tmp_path):
        """The exact body `init` deploys must NOT be advertised as a catalog."""
        mod = _load()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(
            self._seed_body(), encoding="utf-8"
        )
        out = mod._footgun_pointer(tmp_path)
        assert "SHARP_EDGES.md" not in out, (
            "the seeded scaffold was named as a footgun catalog; an adopter is "
            f"sent to pull an empty file. Got: {out!r}"
        )

    def test_one_real_edge_alongside_the_placeholder_is_named(self, tmp_path):
        """Filling the scaffold in is enough -- deleting the placeholder section
        is NOT required. Guards the over-correction of the fix above."""
        mod = _load()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(
            self._seed_body() + "\n## zsh does not word-split\n\nbody\n",
            encoding="utf-8",
        )
        out = mod._footgun_pointer(tmp_path)
        assert "SHARP_EDGES.md" in out, (
            "an operator who wrote a real edge but kept the placeholder lost "
            f"their catalog. Got: {out!r}"
        )

    def test_full_catalog_is_named_even_when_untouched(self, tmp_path):
        """docs/FAILURE_MODES.md is pristine on a fresh adopter AND ships full.
        A 'skip seeds the operator has not edited' rule would drop it -- the
        discriminator is content, not pristineness."""
        mod = _load()
        (tmp_path / "docs").mkdir()
        repo = HOOKS_DIR.parent.parent.parent
        (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
            (repo / "espalier" / "assets" / "docs" / "FAILURE_MODES.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        out = mod._footgun_pointer(tmp_path)
        assert "FAILURE_MODES.md" in out
        assert "SHARP_EDGES.md" not in out, "absent catalog must not be named"

    def test_bare_tree_yields_empty(self, tmp_path):
        mod = _load()
        assert mod._footgun_pointer(tmp_path) == ""

    def test_never_promises_recall_for_a_catalog_the_corpus_cannot_reach(self, tmp_path):
        """NAMING a catalog and being able to PULL it are different facts.

        `docs/FAILURE_MODES.md` ships in full to every adopter, but `_recall`
        indexes its shards only where `indexes_failure_modes` says so. The
        pointer said "Retrieve the relevant one with /recall <topic>" while
        naming it -- so every adopter's first banner advertised a retrieval that
        returned []. Every adopter fixture in this file seeded SHARP_EDGES and
        never FAILURE_MODES, which is precisely why nothing caught it.
        """
        mod = _load()
        repo = HOOKS_DIR.parent.parent.parent
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
            (repo / "espalier" / "assets" / "docs" / "FAILURE_MODES.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        out = mod._footgun_pointer(tmp_path)
        assert "docs/FAILURE_MODES.md" in out, "the catalog they own must still be named"

        assert not mod._recall.indexes_failure_modes(tmp_path), (
            "fixture must be adopter-shaped for this to bite"
        )
        assert "/recall does not index it" in out, (
            "the banner promised /recall for a catalog this tree's corpus never "
            f"indexes. Got: {out!r}"
        )
        assert "/recall <topic>" not in out, (
            f"the pull instruction survived beside an unpullable catalog: {out!r}"
        )

    def test_still_promises_recall_where_the_corpus_does_reach(self):
        """The positive arm, on the live self-host tree: both catalogs are
        indexed there, so the pointer keeps the simple retrieval wording."""
        mod = _load()
        out = mod._footgun_pointer(HOOKS_DIR.parent.parent.parent)
        assert "Retrieve the relevant one with /recall" in out
        assert "directly" not in out

    def test_a_real_edge_written_under_the_seeded_heading_is_kept(self, tmp_path):
        """The scaffold's heading LITERALLY invites you to write there.

        Filtering on the title alone would hide the operator's first real sharp
        edge from the banner AND from /recall, with no warning -- strictly worse
        than not filtering. Suppression is content-aware: the section has to
        say something beyond the seed body to count as filled in, and whether
        the sentinel sentence survived no longer decides it (DEF-560 -- see
        TestSeededPlaceholderSurvivesRealisticEdits for both directions).
        """
        mod = _load()
        (tmp_path / "docs").mkdir()
        kept = self._seed_body().replace(
            mod._hook_utils.SEEDED_PLACEHOLDER_SENTINEL,
            "zsh does not word-split unquoted parameters; loop per item.",
        )
        assert mod._hook_utils.SEEDED_PLACEHOLDER_SENTINEL not in kept
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(kept, encoding="utf-8")
        out = mod._footgun_pointer(tmp_path)
        assert "SHARP_EDGES.md" in out, (
            "an operator who wrote their first edge INSIDE the seeded section "
            f"had it suppressed. Got: {out!r}"
        )

    def test_a_rewrapped_sentinel_still_reads_as_the_scaffold(self, tmp_path):
        """Wrapping is not content. Without whitespace-blind matching the
        suppression silently turned OFF the moment a formatter rewrapped the
        sentinel across a newline, and the scaffold got advertised as a real
        catalog. Measured: dropping the normalization left the whole suite
        green, so the defense was unowned. The seed-residual predicate counts
        words, so a rewrap adds none -- this test is what says so."""
        mod = _load()
        (tmp_path / "docs").mkdir()
        sentinel = mod._hook_utils.SEEDED_PLACEHOLDER_SENTINEL
        wrapped = sentinel.replace(" once you have", "\nonce you have")
        assert wrapped != sentinel and sentinel not in wrapped
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(
            self._seed_body().replace(sentinel, wrapped), encoding="utf-8"
        )
        assert mod._footgun_pointer(tmp_path) == "", (
            "a rewrapped sentinel stopped reading as the scaffold, so the "
            "seeded placeholder was advertised as a real catalog"
        )

    def test_placeholder_titles_match_the_seed_corpus(self):
        """ANTI-VACUITY, derived from canon rather than from one file.

        Walks EVERY seeded doc and collects the sections that still carry the
        scaffold sentinel. Those are exactly the sections the filter must know
        about -- so removing or rewording THIS scaffold reds here instead of
        silently re-admitting it. ⚠ Scoped honestly: the reference set is keyed
        on the sentinel sentence, so a NEW scaffold in another seed asset that
        closes with a different line is invisible to it (the seeded
        CONVENTIONS.md's "What belongs here" already does, and neither consumer
        reads that file). Widen the key before pointing a consumer at a new seed.
        """
        mod = _load()
        repo = HOOKS_DIR.parent.parent.parent
        seed_dir = repo / "espalier" / "assets" / "seed"
        scaffolded = {
            title: body
            for path in sorted(seed_dir.glob("*.md"))
            for title, body in mod._hook_utils.iter_doc_sections(
                path.read_text(encoding="utf-8")
            )
            if mod._hook_utils.SEEDED_PLACEHOLDER_SENTINEL in body
        }
        assert scaffolded, (
            "no seeded doc carries the scaffold sentinel any more -- either the "
            "seeds were reworded or SEEDED_PLACEHOLDER_SENTINEL is stale"
        )
        # Titles: every LIVE scaffold heading must be a key, and the key set is an
        # append-only history -- a reworded heading is ADDED beside the old one,
        # never swapped in, because deployed adopters keep the heading their init
        # wrote (the body axis had this defect first; the title axis is the same
        # defect one level up, found by the adversarial pass).
        assert set(scaffolded) <= set(mod._hook_utils.SEEDED_PLACEHOLDER_TITLES), (
            "a live seeded scaffold heading is missing from SEEDED_PLACEHOLDER_BODIES: "
            f"{sorted(set(scaffolded) - set(mod._hook_utils.SEEDED_PLACEHOLDER_TITLES))}. "
            "ADD it as a new key in tools/cc/hooks/_hook_utils.py and KEEP the old key; "
            "then add the title to _SEED_TITLES_EVER_SHIPPED here."
        )
        assert set(mod._hook_utils.SEEDED_PLACEHOLDER_TITLES) == _SEED_TITLES_EVER_SHIPPED, (
            "the seeded-title history changed. Growing it is a reseed (add the title to "
            "the pin); shrinking it drops a heading some adopter still has."
        )
        # The BODY too: the predicate measures what a section says beyond the
        # seed, so a reworded seed with a stale embedded copy would count the
        # rewording as the operator's content and advertise the scaffold. The
        # live body must be the LAST element of an append-only history -- never
        # a replacement -- because an edited or unstamped copy (a fusion's stub,
        # a pre-2026-07-25 install) keeps the body its init wrote, so a matcher
        # pinned to HEAD alone would re-admit every such scaffold on the next
        # upgrade (an untouched stamped copy is refreshed to HEAD, DEF-432).
        flat = mod._hook_utils._flatten_ws
        # Iterated through the MODULE binding on purpose: the derived-population
        # census (scripts/derived_population_census.py) keys on it, and this pin
        # is a census row that was adjudicated -- a local alias would hide it.
        assert {
            t: flat(b[-1])
            for t, b in mod._hook_utils.SEEDED_PLACEHOLDER_BODIES.items()
            if t in scaffolded
        } == {t: flat(b) for t, b in scaffolded.items()}, (
            "the LIVE seed body is not the last entry of SEEDED_PLACEHOLDER_BODIES. "
            "APPEND it (tools/cc/hooks/_hook_utils.py) and bump "
            "_SEED_BODY_HISTORY_LENGTHS here; never replace an older body -- "
            "deployed adopters still have it."
        )
        assert {
            t: len(b) for t, b in mod._hook_utils.SEEDED_PLACEHOLDER_BODIES.items()
        } == _SEED_BODY_HISTORY_LENGTHS, (
            "the seed-body history changed length. Growing it is a reseed (bump the "
            "pin with the new body); shrinking it drops a body some adopter still has."
        )



# ─── is_seeded_placeholder: the seed-residual rule, both directions (DEF-560) ──

_SEED_PATH = HOOKS_DIR.parent.parent.parent / "espalier" / "assets" / "seed" / "SHARP_EDGES.md"

#: How many bodies each seeded scaffold has ever shipped -- bump when the seed is
#: reworded and its new body is APPENDED to SEEDED_PLACEHOLDER_BODIES.
_SEED_BODY_HISTORY_LENGTHS = {"Add your first sharp edge here": 1}

#: Every heading a seeded scaffold has ever shipped under -- ADD when the seed
#: heading is reworded; nothing is ever removed.
_SEED_TITLES_EVER_SHIPPED = frozenset({"Add your first sharp edge here"})

#: A first sharp edge as an operator would actually write one: one sentence,
#: a command, a symptom, a consequence.
_A_REAL_EDGE = ("`pipefail` with `grep -q` races SIGPIPE; buffer the producer "
                "before the grep.")
#: The same kind of edge in scripts written without spaces between words --
#: "clear the cache before building, or the build errors" -- which `\w+` returns
#: as one or two tokens. The adversarial pass on the first cut drove both hidden.
_A_CHINESE_EDGE = "\u6784\u5efa\u524d\u5fc5\u987b\u6e05\u7f13\u5b58\uff0c\u5426\u5219\u4f1a\u62a5\u9519\u3002"
_A_JAPANESE_EDGE = "\u30d3\u30eb\u30c9\u524d\u306b\u30ad\u30e3\u30c3\u30b7\u30e5\u3092\u6d88\u3059\u3053\u3068\u3002"


def _seed_sections(text: str):
    """iter_doc_sections, re-stated so the fixture needs no module import at
    collection time; test_placeholder_titles_match_the_seed_corpus drives the
    real one."""
    title, body = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if title is not None:
                yield title, "\n".join(body)
            title, body = line[3:].strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        yield title, "\n".join(body)


def _seed_variants() -> tuple[dict[str, str], dict[str, str]]:
    """(still_the_scaffold, real_content): whole-file variants of the LIVE seed.

    Every scaffold edit is one an operator plausibly makes to a section they
    have not filled in; every real-content edit is a first edge written the
    way the seeded heading invites. Driven against the sentinel-only predicate
    before the fix, over the first thirteen: seven read wrongly -- five scaffolds
    advertised as catalogs, and the edge written above a forgotten sentinel
    hidden from the banner and from /recall. The rest were added from review of
    the first cut: four heading-punctuation edits (question mark, quotes, bold,
    em-dash) leaked through its hand-picked punctuation class, and two CJK
    first edges plus a code-fence-only edge were HIDDEN by its space-delimited
    word count -- a regression the old sentinel rule did not have.
    """
    seed = _SEED_PATH.read_text(encoding="utf-8")
    [(title, _body)] = list(_seed_sections(seed))  # _body: the seed's own prose
    sentinel = "Delete this placeholder section once you have a real one."
    heading = f"## {title}"
    assert sentinel in seed and heading in seed
    scaffold = {
        "untouched": seed,
        "title-cased heading": seed.replace(heading, f"## {title.title()}"),
        "closing ATX hashes": seed.replace(heading, f"{heading} ##"),
        "trailing colon on heading": seed.replace(heading, f"{heading}:"),
        "trailing question mark on heading": seed.replace(heading, f"{heading}?"),
        "heading wrapped in quotes": seed.replace(heading, f'## "{title}"'),
        "heading in bold": seed.replace(heading, f"## **{title}**"),
        "em-dash after heading": seed.replace(heading, f"{heading} \u2014"),
        "todo in chinese": seed + "\n\u5f85\u529e\n",
        "empty fence appended": seed + "\n```\n```\n",
        "fence characters in prose": seed + "\nuse ``` to fence\n",
        # ordinary markdown indentation is not code (a first cut read it as such)
        "nested list under the scaffold": seed + "\n- outer\n    - inner\n",
        "list continuation indented": seed + "\n- a point\n    continued here\n",
        "seed prose re-indented four spaces": seed.replace(
            _body, "\n".join(("    " + ln) if ln.strip() else ln for ln in _body.splitlines())),
        "sentinel lost its full stop": seed.replace(sentinel, sentinel.rstrip(".")),
        "sentinel reworded once->when": seed.replace(
            sentinel, sentinel.replace("once you have", "when you have")),
        "TODO line added": seed + "\nTODO\n",
        "sentinel deleted, nothing written": seed.replace(sentinel, ""),
        "sentinel rewrapped": seed.replace(" once you have", "\nonce you have"),
    }
    real = {
        "edge replaces the sentinel": seed.replace(sentinel, _A_REAL_EDGE),
        "edge above a forgotten sentinel": seed.replace(
            sentinel, f"{_A_REAL_EDGE}\n\n{sentinel}"),
        "edge after the seed prose, sentinel deleted":
            seed.replace(sentinel, "") + f"\n{_A_REAL_EDGE}\n",
        "edge replaces the whole body":
            seed[:seed.index(heading)] + f"{heading}\n\n{_A_REAL_EDGE}\n",
        # scripts written without spaces: `\w+` sees a clause as one token
        "chinese first edge": seed.replace(sentinel, _A_CHINESE_EDGE),
        "japanese first edge": seed.replace(sentinel, _A_JAPANESE_EDGE),
        # the seed's own advice is "a one-line way to prove you have hit it"
        "code-fence-only edge": seed.replace(sentinel, "```\npytest -x\n```"),
        "tilde-fence-only edge": seed.replace(sentinel, "~~~\npytest -x\n~~~"),
        "fence opened with a blank line": seed.replace(sentinel, "```\n\npytest -x\n```"),
    }
    return scaffold, real


_SCAFFOLD_IDS = (
    "untouched", "title-cased heading", "closing ATX hashes",
    "trailing colon on heading", "trailing question mark on heading",
    "heading wrapped in quotes", "heading in bold", "em-dash after heading",
    "todo in chinese", "empty fence appended", "fence characters in prose",
    "nested list under the scaffold", "list continuation indented",
    "seed prose re-indented four spaces", "sentinel lost its full stop",
    "sentinel reworded once->when", "TODO line added",
    "sentinel deleted, nothing written", "sentinel rewrapped",
)
_REAL_IDS = (
    "edge replaces the sentinel", "edge above a forgotten sentinel",
    "edge after the seed prose, sentinel deleted", "edge replaces the whole body",
    "chinese first edge", "japanese first edge", "code-fence-only edge",
    "tilde-fence-only edge", "fence opened with a blank line",
)


class TestSeededPlaceholderSurvivesRealisticEdits:
    """DEF-560. The scaffold is recognised by what it SAYS relative to the seed
    the harness deployed, not by one sentinel sentence surviving verbatim.

    Two consumers share the predicate and both are driven here: the banner
    (may it NAME the catalog?) and the recall corpus builder (may the section
    be RETRIEVED?). A scaffold edit must be invisible to both; a real edge must
    reach both.
    """

    @staticmethod
    def _write(tmp_path, text: str):
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(text, encoding="utf-8")

    @staticmethod
    def _sharp_edge_docs(mod, root) -> list[str]:
        return [d.source for d in mod._recall._load_corpus(root)
                if d.source.startswith("docs/SHARP_EDGES.md ::")]

    def test_the_variant_sets_are_the_ones_parametrised(self):
        scaffold, real = _seed_variants()
        assert tuple(scaffold) == _SCAFFOLD_IDS and tuple(real) == _REAL_IDS

    @pytest.mark.parametrize("case", _SCAFFOLD_IDS)
    def test_a_scaffold_edit_is_not_advertised_by_the_banner(self, tmp_path, case):
        mod = _load()
        self._write(tmp_path, _seed_variants()[0][case])
        out = mod._footgun_pointer(tmp_path)
        assert "SHARP_EDGES.md" not in out, (
            f"{case!r}: an unfilled scaffold was named as a footgun catalog; the "
            f"operator is sent to pull an empty file. Got: {out!r}"
        )

    @pytest.mark.parametrize("case", _SCAFFOLD_IDS)
    def test_a_scaffold_edit_is_not_retrievable(self, tmp_path, case):
        mod = _load()
        self._write(tmp_path, _seed_variants()[0][case])
        assert self._sharp_edge_docs(mod, tmp_path) == [], (
            f"{case!r}: /recall would answer a footgun question with the placeholder"
        )

    @pytest.mark.parametrize("case", _REAL_IDS)
    def test_a_real_edge_reaches_the_banner(self, tmp_path, case):
        mod = _load()
        self._write(tmp_path, _seed_variants()[1][case])
        out = mod._footgun_pointer(tmp_path)
        assert "SHARP_EDGES.md" in out, (
            f"{case!r}: the operator's first sharp edge was hidden from the banner. "
            f"Got: {out!r}"
        )

    @pytest.mark.parametrize("case", _REAL_IDS)
    def test_a_real_edge_is_retrievable(self, tmp_path, case):
        mod = _load()
        self._write(tmp_path, _seed_variants()[1][case])
        assert len(self._sharp_edge_docs(mod, tmp_path)) == 1, (
            f"{case!r}: the operator's first sharp edge was hidden from /recall"
        )

    def test_the_floor_names_its_mutation_on_both_sides(self):
        """The constant separates annotation from prose, and the boundary is
        pinned from both sides so a drift in either direction reds: two new
        words under the seeded heading are still the scaffold, three are not."""
        mod = _load()
        h = mod._hook_utils
        [(title, body)] = list(_seed_sections(_SEED_PATH.read_text(encoding="utf-8")))
        assert h.SEEDED_NEW_CONTENT_FLOOR == 3
        assert h.is_seeded_placeholder(title, body + "\nWIP later\n")
        assert not h.is_seeded_placeholder(title, body + "\nstash before switching\n")

    def test_an_unrelated_heading_is_never_a_scaffold(self):
        """The residual rule applies only under a seeded heading; a section the
        operator titled themselves is theirs whatever its body says, even the
        seed body verbatim."""
        mod = _load()
        h = mod._hook_utils
        [(_title, body)] = list(_seed_sections(_SEED_PATH.read_text(encoding="utf-8")))
        assert not h.is_seeded_placeholder("zsh does not word-split", body)
        assert not h.is_seeded_placeholder("Add your first sharp edge here, then this one", body)


class TestBrokenRetrieverImportSaysNothingAboutRecall:
    """DEF-563. When `_recall` failed to import, the banner used to route every
    catalog to the 'read it directly' arm and print `/recall does not index it
    on this tree` -- a specific false fact from a process that never consulted
    the corpus -- or, with SHARP_EDGES present, to promise `/recall` for it
    from a process that had just watched the retriever fail to load. Now it
    names the catalogs, points at their tables of contents, and says nothing
    about /recall in either direction.
    """

    @staticmethod
    def _both_catalogs(tmp_path):
        repo = HOOKS_DIR.parent.parent.parent
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(
            "# Sharp Edges\n\n## zsh does not word-split\n\n"
            "`rm -- $LIST` in zsh deletes one file named after the whole list; "
            "loop per item.\n",
            encoding="utf-8",
        )
        (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
            (repo / "espalier" / "assets" / "docs" / "FAILURE_MODES.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

    def test_adopter_tree_with_both_catalogs(self, tmp_path, monkeypatch):
        mod = _load()
        self._both_catalogs(tmp_path)
        monkeypatch.setattr(mod, "_recall", None)
        out = mod._footgun_pointer(tmp_path)
        assert "docs/SHARP_EDGES.md" in out and "docs/FAILURE_MODES.md" in out, (
            f"the catalogs the tree owns must still be named: {out!r}"
        )
        assert "at their tables of contents" in out, out
        assert "/recall" not in out, (
            "a banner whose retriever failed to import asserted something about "
            f"/recall: {out!r}"
        )

    def test_self_host_tree(self, monkeypatch):
        """The positive arm's twin: on the live tree both catalogs are indexed,
        and with the retriever gone the banner must not say so."""
        mod = _load()
        monkeypatch.setattr(mod, "_recall", None)
        out = mod._footgun_pointer(HOOKS_DIR.parent.parent.parent)
        assert "docs/SHARP_EDGES.md" in out and "docs/FAILURE_MODES.md" in out
        assert "/recall" not in out

    def test_the_negative_fact_is_still_stated_when_the_corpus_was_consulted(self, tmp_path):
        """The boundary from the other side: `does not index it` is the RIGHT
        thing to say when `_recall` loaded and reported the catalog unindexed.
        Only the unconsulted case goes quiet."""
        mod = _load()
        repo = HOOKS_DIR.parent.parent.parent
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "FAILURE_MODES.md").write_text(
            (repo / "espalier" / "assets" / "docs" / "FAILURE_MODES.md").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        assert mod._recall is not None
        assert "/recall does not index it" in mod._footgun_pointer(tmp_path)



class TestSeedHistoryOnlyGrows:
    """The append-only invariant, enforced by an oracle rather than a message.

    The two history pins above compare the hook's constant against constants
    in THIS file, so a maintainer who reseeds, hits the red, and replaces the
    body (or the heading) in both places is green -- and every adopter on the
    old seed has their untouched scaffold advertised. The previous value has to
    come from somewhere the same edit cannot touch: the last commit. A
    pre-commit guard by construction (CI compares HEAD with itself); it reds
    on the working tree the moment a shipped body or heading is edited or
    dropped instead of appended.
    """

    _REL = "tools/cc/hooks/_hook_utils.py"

    @staticmethod
    def _bodies_literal(source: str) -> dict | None:
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SEEDED_PLACEHOLDER_BODIES" for t in node.targets
            ):
                return ast.literal_eval(node.value)
        return None

    def test_head_history_is_a_prefix_of_the_working_tree(self):
        repo = HOOKS_DIR.parent.parent.parent
        try:
            shown = subprocess.run(
                ["git", "show", f"HEAD:{self._REL}"], cwd=repo, capture_output=True,
                text=True, check=False, env=_git_env(), encoding="utf-8",
            )
        except OSError:
            pytest.skip("git unavailable")
        if shown.returncode != 0:
            pytest.skip("no HEAD copy of the hook (git-less or shallow tree)")
        prev = self._bodies_literal(shown.stdout)
        if prev is None:
            pytest.skip("SEEDED_PLACEHOLDER_BODIES is not at HEAD yet (the commit introducing it)")
        now = self._bodies_literal((repo / self._REL).read_text(encoding="utf-8"))
        assert now is not None, "SEEDED_PLACEHOLDER_BODIES vanished from the hook"
        for title, bodies in prev.items():
            assert title in now, (
                f"seeded heading {title!r} was removed from SEEDED_PLACEHOLDER_BODIES. "
                "Deployed adopters still have it: ADD the new heading, keep this one."
            )
            assert tuple(now[title][: len(bodies)]) == tuple(bodies), (
                f"the body history under {title!r} is no longer a prefix of what HEAD "
                "shipped: a body was edited or dropped. APPEND the new body; never "
                "replace one an adopter's tree may carry."
            )


# ─── _standing_principles_index: compact always-on frame index ──────────────

class TestStandingPrinciplesIndex:
    def test_renders_titles_only_not_bodies(self, tmp_path):
        mod = _load()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "STANDING_PRINCIPLES.md").write_text(
            "# Standing Principles\n\nintro prose\n\n"
            "## 1. Make it prove it\n\nbody of one that must NOT appear\n\n"
            "## 2. Toolbelt, not security boundary\n\nbody two\n",
            encoding="utf-8",
        )
        out = mod._standing_principles_index(tmp_path)
        assert "STANDING PRINCIPLES" in out
        assert "- 1. Make it prove it" in out
        assert "- 2. Toolbelt, not security boundary" in out
        assert "body of one" not in out, "bodies must not be dumped -- titles only"
        assert "docs/STANDING_PRINCIPLES.md" in out  # pointer to the bodies

    def test_absent_doc_yields_empty(self, tmp_path):
        mod = _load()
        assert mod._standing_principles_index(tmp_path) == ""

    def test_index_surfaces_every_live_principle(self):
        """Doc-derived, not a hardcoded 9: the index must surface every title the
        live doc defines, counted by the SAME rule the renderer selects them with
        (a line starting ``"## "``). A 10th principle tracks automatically and a
        benign non-numbered ``## `` heading does NOT false-alarm; the assert reds
        only when the renderer's output diverges from the doc's heading count -- a
        dropped or mangled title, the real regression.
        """
        mod = _load()
        repo = HOOKS_DIR.parent.parent.parent
        doc = (repo / "docs" / "STANDING_PRINCIPLES.md").read_text(encoding="utf-8")
        n_titles = sum(1 for ln in doc.splitlines() if ln.startswith("## "))
        assert n_titles > 0, "doc title shape changed -- no '## ' headings found"
        out = mod._standing_principles_index(repo)
        rendered = out.count("\n- ")
        assert rendered == n_titles, (
            f"index must surface every live principle: doc defines {n_titles}, "
            f"index rendered {rendered}"
        )


# ─── Degraded + health self-check (C2) ──────────────────────────────────────

class TestDegradedAndHealth:
    def test_degraded_surface_carries_recovery_action(self, tmp_path):
        """A bare tree (no CLAUDE.md / .claude / tools/cc) is DEGRADED -- the
        Surface line must NAME the recovery command so a session that no longer
        types /context-load still learns when to run it."""
        mod = _load()
        banner = mod._build_context(tmp_path, False, False)
        assert "DEGRADED" in banner
        assert "/context-load --mode recover" in banner

    def test_healthy_surface_has_no_recovery_noise(self, tmp_path):
        """A surface with all core infra present (CLAUDE.md, .claude/settings.json,
        tools/cc/) is healthy -- the Surface line must NOT carry the recovery
        action, which appears only when degraded.

        Built on a CONSTRUCTED tree, not the live checkout: `espalier init`
        gitignores .claude/settings.json (machine-detected interpreter name), so a
        fresh clone -- every CI runner -- legitimately lacks it and the live
        surface reads DEGRADED there. Asserting the live repo is healthy only
        held on a machine where init had run. surface_status() keys 'healthy'
        off exactly these three paths (tools/cc/hooks/_hook_utils.py)."""
        mod = _load()
        (tmp_path / "CLAUDE.md").write_text("# stub\n", encoding="utf-8")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        banner = mod._build_context(tmp_path, True, False)
        assert "Surface:   healthy" in banner
        assert "--mode recover" not in banner

    def test_blueprint_failure_is_flagged(self, tmp_path):
        """A failed continuity load surfaces a visible health flag rather than
        injecting a silently-missing blueprint.

        TP-324: the failure state is DRIVEN. Pre-fix this asserted only a
        static-constant membership plus a healthy-repo negative -- deleting the
        ``flags.append("[banner] blueprint continuity unavailable: ...")`` line
        outright left it green, because nothing here ever built a banner from a
        failed continuity load. A bare tmp_path has no
        ``tools/cc/cognitive_blueprint.py``, so ``_load_blueprint`` returns the
        "No blueprint system" failure state and the flag must fire.
        """
        mod = _load()
        # direct contract: a known failure string lands in the flag set
        assert "No blueprint system" in mod._BLUEPRINT_FAILURE_STATES
        # POSITIVE: a tree with no blueprint system IS a failure state.
        assert not (tmp_path / "tools" / "cc" / "cognitive_blueprint.py").exists()
        degraded = mod._build_context(tmp_path, True, False)
        assert "Blueprint: No blueprint system" in degraded, (
            f"fixture invariant: expected the failure state in the banner:\n{degraded}"
        )
        assert "--- BANNER HEALTH ---" in degraded
        assert "blueprint continuity unavailable" in degraded, (
            "a failed continuity load must surface a visible health flag; "
            f"banner:\n{degraded}"
        )
        # ADOPTER ARM: the flag rides the blueprint STATE, not repo identity.
        # Both arms above passed self_host=True, so re-wrapping the condition in
        # `self_host and ...` left the whole suite green -- an adopter whose
        # continuity chain broke would go back to being told nothing.
        adopter = mod._build_context(tmp_path, False, False)
        assert "blueprint continuity unavailable" in adopter, (
            "an adopter's broken blueprint chain must surface the same health "
            f"flag; banner:\n{adopter}"
        )
        # NEGATIVE: the live healthy repo must NOT trip it
        repo = HOOKS_DIR.parent.parent.parent
        assert "blueprint continuity unavailable" not in mod._build_context(repo, True, False)


# ─── Whole-banner contracts: allowlist, gating, no-dup, lean, flag ──────────

import re  # noqa: E402

# Every "--- X ---" section the banner is allowed to emit. A header outside this
# set means a rogue/unexpected injection.
_ALLOWED_SECTIONS = {
    "BANNER HEALTH",
    "OPEN PLAN",
    "GOAL / PROGRESS",
    "MEMORY (recent sessions",
    "STANDING PRINCIPLES",
    "FOOTGUNS & FAILURE MODES",
}
_SECTION_RE = re.compile(r"^--- (.+?) ---", re.MULTILINE)


def _sections(banner: str):
    return _SECTION_RE.findall(banner)


class TestBannerContracts:
    def _repo(self):
        return HOOKS_DIR.parent.parent.parent

    def test_every_section_is_on_the_allowlist(self):
        mod = _load()
        banner = mod._build_context(self._repo(), True, False)
        for header in _sections(banner):
            assert any(header.startswith(a) for a in _ALLOWED_SECTIONS), (
                f"rogue/unexpected banner section: {header!r}"
            )

    def test_no_section_header_appears_twice(self):
        mod = _load()
        banner = mod._build_context(self._repo(), True, False)
        seen = [h.split(" (")[0].strip() for h in _sections(banner)]
        assert len(seen) == len(set(seen)), f"duplicate section header: {seen}"

    def test_adopter_banner_has_zero_harness_internal_sections(self, tmp_path):
        """Self-host gating must be airtight: an adopter banner carries NONE of
        the harness-internal sections."""
        mod = _load()
        banner = mod._build_context(tmp_path, False, False)
        for internal in ("STANDING PRINCIPLES", "FOOTGUNS & FAILURE MODES",
                         "MEMORY (recent sessions", "[recent:"):
            assert internal not in banner, f"adopter banner leaked {internal!r}"
        # adopter still gets orientation + the MEMORY fallback line
        assert "Orientation (on first response" in banner
        assert "Consult ESPALIER_MEMORY.md" in banner

    def test_banner_stays_lean(self):
        """The whole point: the redesigned self-host banner is far under the 16KB
        outer ceiling (escaping the lost-in-the-middle zone). The bound is the
        per-section soft-budget COMPOSITION (not a magic number), so it tracks the
        budgets and a section blowing its budget -- or a new unbounded tenant --
        still fails. The blueprint continuity is the dominant tenant BY DESIGN
        (it is CONTENT, not index), so it accumulates toward its 6KB soft cap."""
        mod = _load()
        banner = mod._build_context(self._repo(), True, False)
        nbytes = len(banner.encode("utf-8"))
        assert nbytes <= mod._MAX_CONTEXT_BYTES
        # Effective-cap sum (bounded sections) + slack for the header/tail/footgun.
        # GOAL rides to its hard cap (TP-241: the goal-proper must be visible, not
        # cut under the perishable Notes head), so the bound uses _GOAL_HARD_CAP,
        # not the goal soft budget.
        effective = dict(mod._SOFT_BUDGETS)
        effective["goal"] = mod._GOAL_HARD_CAP
        lean_ceiling = sum(effective.values()) + 2_500
        assert nbytes < lean_ceiling, (
            f"banner is {nbytes}B vs lean ceiling {lean_ceiling}B -- a section blew "
            f"its cap or an unbounded tenant crept in"
        )
        # Still a clear win vs the old 15.9KB bloat (and the ~87K full reads we
        # dropped). The goal-visible design raised the floor from the old 0.8*MAX.
        assert nbytes < 0.9 * mod._MAX_CONTEXT_BYTES

    def test_orientation_tail_always_present(self):
        mod = _load()
        banner = mod._build_context(self._repo(), True, False)
        assert "Orientation (on first response" in banner
        assert "first-thoughts" in banner
        assert "confirm or redirect" in banner
        assert "/implement-task" in banner

    def test_orientation_omits_goal_when_no_goal_was_injected(self, tmp_path):
        """DEF-424f: the orientation must not source from a section that is
        not in the banner.

        `cc/GOAL.md` is espalier's own local snapshot — `init` deploys no such
        file and nothing creates one — so on an adopter tree the GOAL section
        never appears, while the orientation told the first response to read
        it and to build a state line "from GOAL". The instruction has to match
        what was actually injected.
        """
        mod = _load()
        assert not (tmp_path / "cc" / "GOAL.md").exists()
        banner = mod._build_context(tmp_path, False, False)
        assert "GOAL" not in banner, (
            "the orientation still names GOAL on a tree that has none — an "
            "adopter's first response is sent to a section that is not there"
        )
        # The block itself must survive; omission is the failure mode that
        # would make this test pass for the wrong reason.
        assert "Orientation (on first response" in banner
        assert "one-glance state line" in banner

    def test_orientation_names_goal_when_one_was_injected(self, tmp_path):
        """The negative control: where a GOAL exists, keep instructing it.

        Without this arm the fix could satisfy its sibling by deleting every
        GOAL reference outright, silently costing the self-host session the
        state line it is built around.
        """
        mod = _load()
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "GOAL.md").write_text(
            "# Project Goal\n\nShipping the thing.\n", encoding="utf-8"
        )
        banner = mod._build_context(tmp_path, False, False)
        assert "Working on / Next / Owed, from\n  GOAL" in banner, (
            "a tree WITH a GOAL lost the instruction to source from it"
        )
        assert "Notes to next session + GOAL" in banner

    def test_matched_phrases_survive_both_orientation_branches(self):
        """A rewrap is a behaviour change when the prose is matched by
        substring — and adding the no-GOAL branch proved it the hard way.

        The first cut of that branch wrapped the ending as "confirm or\\n
        redirect?", which reddened three tests in ``test_hooks.py`` with every
        word still present and the meaning unchanged. Any future edit to
        either branch has to keep these contiguous; a conditional block
        doubles the number of renderings each phrase has to survive, and only
        one of them is the one you are looking at while editing.
        """
        mod = _load()
        phrases = (
            "Orientation (on first response",
            "first-thoughts",
            "confirm or redirect",
            "one-glance state line",
        )
        for has_goal in (True, False):
            rendered = mod._orientation_common(has_goal)
            for phrase in phrases:
                assert phrase in rendered, (
                    f"{phrase!r} is absent or line-wrapped in the "
                    f"has_goal={has_goal} branch. Check for a newline inside "
                    f"the phrase before assuming it was deleted."
                )

    def test_orientation_gates_on_the_file_not_on_self_host(self, tmp_path):
        """Keyed on the injected section, not the repo identity.

        `cc/GOAL.md` is gitignored, so even the self-host tree can be without
        one — a self_host gate would keep instructing a read of a file this
        very repo does not currently have.
        """
        mod = _load()
        assert "GOAL" not in mod._build_context(tmp_path, True, False)

    def test_oversize_section_surfaces_a_visible_flag(self, tmp_path):
        """An oversize section trips a VISIBLE banner-health flag (never silent)."""
        mod = _load()
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "GOAL.md").write_text("word " * 1000, encoding="utf-8")  # over the goal soft budget
        banner = mod._build_context(tmp_path, False, False)
        assert "--- BANNER HEALTH ---" in banner
        assert "goal section" in banner and "is large" in banner


# ─── TP-240: the compact (mid-session) orientation variant ──────────────────

import json  # noqa: E402


class TestCompactVariant:
    def _repo(self):
        return HOOKS_DIR.parent.parent.parent

    def test_compact_banner_reshape(self):
        mod = _load()
        c = mod._build_context(self._repo(), True, False, "compact")
        # the re-orient signal + the compact orientation tail
        assert "POST-COMPACTION RE-ORIENT" in c
        assert "compaction summary" in c
        assert "confirm or redirect" in c
        # durable layer kept (compaction dropped it)
        assert "STANDING PRINCIPLES" in c
        assert "FOOTGUNS" in c
        # stale / redundant sections dropped
        assert "MEMORY (recent sessions" not in c            # start-of-session digest
        assert "Orientation (on first response" not in c     # normal orientation replaced

    def test_compact_flags_goal_as_snapshot(self, tmp_path):
        mod = _load()
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "GOAL.md").write_text("## At a glance\nshipping\n", encoding="utf-8")
        c = mod._build_context(tmp_path, False, False, "compact")
        assert "session-start SNAPSHOT" in c
        assert "shipping" in c  # the GOAL body still rides through, just flagged

    def test_active_plan_status_live_and_failopen(self, tmp_path):
        mod = _load()
        assert mod._active_plan_status(tmp_path) == ""  # no plan -> ''
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "execution_plan.json").write_text(json.dumps({
            "task": "T", "status": "in_progress",
            "steps": [{"index": 0, "description": "first", "status": "passed"},
                      {"index": 1, "description": "second step", "status": "running"}],
        }), encoding="utf-8")
        out = mod._active_plan_status(tmp_path)
        assert "ACTIVE PLAN" in out and "[>] step index 1 of 2" in out and "second step" in out
        # a COMPLETE plan is not "live"
        (tmp_path / "cc" / "execution_plan.json").write_text(json.dumps({
            "task": "T", "status": "complete", "steps": []}), encoding="utf-8")
        assert mod._active_plan_status(tmp_path) == ""

    def test_compact_banner_keeps_the_footgun_layer_for_an_adopter(self, tmp_path):
        """The durable layer must survive compaction on an ADOPTER tree too.

        `_build_compact_context` carries its own copy of the banner's gate, and
        it had no coverage in either direction -- so a fix landed in
        `_build_context` alone would leave post-compaction adopter-blind at
        exactly the moment the durable layer exists to survive.
        """
        mod = _load()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "SHARP_EDGES.md").write_text(
            "## A real edge\n\nbody\n", encoding="utf-8"
        )
        c = mod._build_context(tmp_path, False, False, "compact")
        assert "FOOTGUNS" in c, (
            "post-compaction re-orient dropped the footgun layer for an adopter "
            "who owns the catalog it names"
        )

    def test_compact_banner_omits_footgun_layer_without_catalogs(self, tmp_path):
        """The negative arm -- nothing to point at, so no pointer."""
        mod = _load()
        c = mod._build_context(tmp_path, False, False, "compact")
        assert "FOOTGUNS" not in c

    def test_recent_commits_failopen_on_non_git(self, tmp_path):
        mod = _load()
        assert mod._recent_commits(tmp_path) == ""  # no .git -> '' (fail-open)

    def test_blueprint_recent_failopen_on_absent(self, tmp_path):
        mod = _load()
        assert mod._blueprint_recent(tmp_path) == ""  # no cognitive_blueprint.py -> ''


class TestActivePullTail:
    """TP-241: the normal-session orientation tail nudges an ACTIVE read of the
    working summary on resume (self-pull primes better than a passive inject),
    rather than permanently injecting the full summary into the banner."""

    def test_normal_tail_nudges_working_summary_read(self):
        mod = _load()
        assert "_working_summary.md" in mod._ORIENTATION_TAIL
        assert "/read-summary" in mod._ORIENTATION_TAIL


class TestDropWholeEntries:
    """TP-241 Phase 3b: the blueprint block bound drops WHOLE entries (never
    slices one mid-thought); a single runaway entry falls back to an honest cut."""

    def test_drops_whole_trailing_blocks_keeps_header(self):
        import re
        mod = _load()
        entry_re = re.compile(r"^\[\d+\] ")
        text = "# header\n[1] newest\n    short body\n[2] oldest\n    " + ("x" * 400)
        out = mod._drop_whole_entries(text, 80, entry_re, "\n[dropped]")
        assert "# header" in out          # prefix kept
        assert "[1] newest" in out and "short body" in out  # newest entry kept WHOLE
        assert "[2] oldest" not in out    # oldest entry dropped WHOLE (not sliced)
        assert out.endswith("[dropped]")

    def test_single_runaway_newest_keeps_head_not_lost_whole(self):
        # Phase-3b MAJOR: when even the NEWEST entry alone exceeds budget, its HEAD
        # survives (byte-cut) with an honest marker -- never lost whole (the
        # cap-raise re-enabled this monopolization edge).
        import re
        mod = _load()
        entry_re = re.compile(r"^\[\d+\] ")
        text = "# header\n[1] " + ("N" * 5000)  # no-whitespace runaway body
        out = mod._drop_whole_entries(text, 200, entry_re, "\n[older dropped]")
        assert "N" * 50 in out, "the newest entry's head must survive, not vanish"
        assert "newest entry truncated" in out  # honest marker, not "older dropped"
        assert "older dropped" not in out
        assert len(out.encode("utf-8")) <= 200 + len(mod._NEWEST_ENTRY_MARKER)

    def test_cross_session_runaway_newest_keeps_head_and_handoff(self):
        # Phase-3b MAJOR (cross-session): a runaway newest decision keeps its head
        # AND the curated handoff (Next steps) -- the section is never emptied.
        mod = _load()
        budget = mod._SOFT_BUDGETS["blueprint"]
        cs = ("# Session Context\n\n## Next steps\nGOAL pointer\n\n"
              "## Recent reasoning -- pinned\n"
              "- " + ("N" * (budget - 100)) + "\n- OLD short")
        out = mod._bound_blueprint_context(cs)
        assert "GOAL pointer" in out          # curated handoff survives
        assert "N" * 50 in out                # newest decision head survives (not empty)
        assert len(out.encode("utf-8")) <= budget + len(mod._NEWEST_ENTRY_MARKER)

    def test_bound_blueprint_context_drops_whole_lines_keeps_handoff(self):
        mod = _load()
        budget = mod._SOFT_BUDGETS["blueprint"]
        head = "# Session Context\n\n## Next steps\nGOAL pointer\n\n## Recent reasoning\n"
        entries = "\n".join(f"- decision {i} " + ("y" * 200) for i in range(60))
        text = head + entries
        assert len(text.encode("utf-8")) > budget
        out = mod._bound_blueprint_context(text)
        assert len(out.encode("utf-8")) <= budget + len("\n[blueprint context truncated]")
        assert "## Next steps" in out and "GOAL pointer" in out  # curated handoff survives
        assert out.endswith("[blueprint context truncated]")

    def test_under_budget_passes_whole(self):
        mod = _load()
        text = "# Session Context\n\n## Next steps\nGOAL pointer\n"
        assert mod._bound_blueprint_context(text) == text


# ─── Integrity reaches the banner, not only stderr ──────────────────────────


class TestIntegrityReachesTheBanner:
    """Tamper state must arrive in the channel the session actually reads.

    ``session_start`` writes two streams: the boot warnings go to STDERR, and the
    injected context is the ``additionalContext`` JSON on stdout. Nothing threaded
    one into the other, so a session whose only view of the repo is the banner was
    never told about drift. Observed: a live 6-file drift sat behind a banner
    reading ``Surface: healthy`` for an entire session, and was found hours later
    only because an unrelated command ran the check explicitly.

    These arms pin the summary STRING that ``_report_integrity_state`` returns --
    the value the banner renders -- across every state, plus the rendering itself.
    """

    def _summary(self, monkeypatch, *, ok, mismatched, kill=(), raises=False):
        mod = _load()

        class _Stub:
            MANIFEST_ABSENT = mod._integrity.MANIFEST_ABSENT
            # the real predicate: the stub fakes the VERDICT, not the reading of it
            is_protocol_mismatch = staticmethod(mod._integrity.is_protocol_mismatch)

            def scan_for_kill_switches(self, root, include_unreadable=False):
                return list(kill)

            def verify_integrity(self, root):
                if raises:
                    raise RuntimeError("verify exploded")
                return (ok, list(mismatched))

            def append_audit(self, root, payload):
                return None

        monkeypatch.setattr(mod, "_integrity", _Stub())
        return mod, mod._report_integrity_state(Path("."))

    def test_clean_reports_ok_not_silence(self, monkeypatch):
        # "ok" and "no line at all" must not look the same: if the check ever
        # stops running, a missing line would read as a pass.
        _mod, summary = self._summary(monkeypatch, ok=True, mismatched=[])
        assert summary == "ok"

    def test_drift_names_the_count_and_the_remedy(self, monkeypatch):
        _mod, summary = self._summary(
            monkeypatch, ok=False, mismatched=["a.py", "b.py", "c.py"]
        )
        assert "DRIFT" in summary and "3 files" in summary
        assert "integrity refresh" in summary, "a drift report must carry its fix"

    def test_absent_manifest_is_guidance_not_drift(self, monkeypatch):
        # The manifest is gitignored and per-install, so a cloned-but-un-inited
        # tree legitimately has none. Same exemption the stderr warning applies,
        # and the same call `audit` and `doctor` make.
        mod = _load()
        _mod, summary = self._summary(
            monkeypatch, ok=False, mismatched=[mod._integrity.MANIFEST_ABSENT]
        )
        assert "DRIFT" not in summary
        assert "init" in summary

    def test_a_protocol_sentinel_is_a_redeploy_not_drift(self, monkeypatch):
        # DEF-725: a manifest this deployed copy cannot read was written by a
        # newer engine; `refresh` would rewrite the same manifest, so the line
        # names the redeploy and never counts the sentinel as a file.
        _mod, summary = self._summary(
            monkeypatch, ok=False,
            mismatched=["<algorithm_unsupported: manifest='sha256-future' verifier='sha256-lf'>"],
        )
        assert "MANIFEST NEWER THAN HOOKS" in summary
        assert "upgrade --execute" in summary
        assert "DRIFT" not in summary and "refresh" not in summary

    def test_kill_switch_outranks_drift(self, monkeypatch):
        # Drift means a protected file changed; a kill-switch means enforcement is
        # off entirely. The more severe fact must be the one shown.
        _mod, summary = self._summary(
            monkeypatch, ok=False, mismatched=["a.py"], kill=["disableAllHooks"]
        )
        assert "KILL-SWITCH" in summary and "DRIFT" not in summary

    def test_a_failed_check_never_reports_ok(self, monkeypatch):
        # The blind-detector guard: a check that raised has verified NOTHING, and
        # must not be rendered with a green label.
        _mod, summary = self._summary(monkeypatch, ok=True, mismatched=[], raises=True)
        assert summary == "unverified (check failed)"
        assert summary != "ok"

    def test_the_summary_is_rendered_into_the_banner(self, monkeypatch, tmp_path):
        # End of the wire: the string above must actually appear in the injected
        # context. Pinning the return value alone would leave the banner free to
        # drop it -- which is the bug this fixes, one layer up.
        mod = _load()
        monkeypatch.setattr(mod, "surface_status", lambda root, **kw: "healthy")
        ctx = mod._build_context(
            tmp_path, False, False, "", integrity="DRIFT (6 files)  ->  run x"
        )
        assert "Integrity: DRIFT (6 files)" in ctx, (
            "the summary never reached additionalContext -- the exact gap this closes"
        )

    def test_the_post_compaction_banner_carries_it_too(self, monkeypatch, tmp_path):
        # Sister site: `source="compact"` returns a DIFFERENT builder. A fix that
        # reached only the normal banner would leave every post-compaction
        # re-orient blind, which is the moment a session most needs live state.
        mod = _load()
        monkeypatch.setattr(mod, "surface_status", lambda root, **kw: "healthy")
        ctx = mod._build_context(tmp_path, False, False, "compact", integrity="ok")
        assert "POST-COMPACTION" in ctx, "fixture did not reach the compact builder"
        assert "Integrity: ok" in ctx

    def test_absent_integrity_arg_keeps_the_banner_byte_identical(
        self, monkeypatch, tmp_path
    ):
        # The shorter-arity callers must be unaffected: no arg, no line.
        mod = _load()
        monkeypatch.setattr(mod, "surface_status", lambda root, **kw: "healthy")
        assert "Integrity:" not in mod._build_context(tmp_path, False, False)


class TestSectionSplitterIsFenceAware:
    """DEF-565. ``iter_doc_sections`` is the ONE section splitter for the hook
    stack (``_recall`` read the corpus through its own copy until the collapse),
    and neither copy knew about fenced code: a documented example of a heading
    inside a three-backtick fence started a new section in the recall corpus and a new "real
    section" in the banner's catalog check. The corpus on the live tree was
    byte-identical before and after the collapse (298 docs, same token bags),
    so the pins here are synthetic by necessity -- no tracked doc carries a
    fenced ``## `` line today, which is exactly why nothing had reddened.
    """

    _FENCED = (
        "# Doc\n\n## Real\n\nprose\n\n```md\n## Not a section\nmore\n```\n\n"
        "## Also real\n\nbody\n"
    )

    def test_a_heading_inside_a_fence_is_body_not_a_section(self):
        mod = _load()
        got = mod._hook_utils.iter_doc_sections(self._FENCED)
        assert [t for t, _ in got] == ["Real", "Also real"], got
        assert "## Not a section" in got[0][1], got[0][1]

    @pytest.mark.parametrize("opener, closer, closes", [
        ("```", "```", True),
        ("~~~", "~~~", True),
        ("````", "````", True),
        ("```", "`````", True),      # a longer run of the same char closes
        ("  ```", "  ```", True),    # an indented fence is still a fence
        ("```", "~~~", False),       # a different char never closes
        ("````", "```", False),      # a shorter run never closes
        ("```", "``` trailing", False),  # a closer carries no info string
    ])
    def test_fence_grammar(self, opener, closer, closes):
        """CommonMark's closing rule, shared with the alias loader in _recall:
        same character, at least as long, alone on its line."""
        mod = _load()
        text = f"## A\n\n{opener}\n## Inside\n{closer}\n## After\n"
        titles = [t for t, _ in mod._hook_utils.iter_doc_sections(text)]
        # "Inside" is fenced either way; "After" is a section only if the
        # fence actually closed before it.
        assert titles == (["A", "After"] if closes else ["A"]), (opener, closer, titles)

    def test_the_banner_does_not_count_a_fenced_heading_as_a_real_section(self, tmp_path):
        """The consumer-level red: a catalog whose ONLY ``## `` line is a
        documented example inside a fence has no section to name, and the
        banner must not point at it. The old splitter read the example as a
        real section with a non-seed title, so the pointer named the file."""
        mod = _load()
        doc = tmp_path / "SHARP_EDGES.md"
        doc.write_text(
            "# Sharp Edges\n\nHow to add one:\n\n```\n## Your edge title\n\nwhy it bites\n```\n",
            encoding="utf-8",
        )
        assert mod._hook_utils.iter_doc_sections(doc.read_text(encoding="utf-8")) == []
        assert mod._hook_utils.has_real_sections(doc) is False

    def test_the_restated_splitter_matches_the_real_one_on_every_seed(self):
        """``_seed_sections`` above restates the splitter WITHOUT the fence rule
        so the fixture needs no module import at collection time. That is only
        honest while no seed carries a fence, so pin the two to each other on
        the seed corpus the restatement is used against."""
        mod = _load()
        seed_dir = HOOKS_DIR.parent.parent.parent / "espalier" / "assets" / "seed"
        seeds = sorted(seed_dir.glob("*.md"))
        assert seeds, "seed corpus vanished; the parity assertion would be vacuous"
        for path in seeds:
            text = path.read_text(encoding="utf-8")
            assert list(_seed_sections(text)) == mod._hook_utils.iter_doc_sections(text), (
                f"{path.name}: the restated splitter and iter_doc_sections disagree -- "
                "a seed now carries a fence; teach _seed_sections the rule or drop it"
            )

    def test_a_four_space_indented_run_is_not_a_fence(self):
        """CommonMark caps a fence's indent at three spaces; four is an indented
        code block, whose backticks are literal. The old toggles lstripped any
        indent, so this is the one place the grammar is STRICTER than before."""
        mod = _load()
        text = "## A\n\n    ```\n## Inside\n    ```\n## After\n"
        titles = [t for t, _ in mod._hook_utils.iter_doc_sections(text)]
        assert titles == ["A", "Inside", "After"], titles


class TestOrientationFootgunLineIsDerived:
    """DEF-562. The orientation bullet that teaches /recall said what it indexes
    as a hand-written constant -- "memory/ + the SHARP_EDGES sections +
    docs/sharp-edges/" -- and the retriever had since started indexing
    docs/STANDING_PRINCIPLES.md wherever the file exists. The bullet is now
    rendered from ``_recall.indexed_sources(root)``, the families the corpus
    actually yielded on this tree, so it cannot name a source that did not
    yield and cannot miss one that did.
    """

    @staticmethod
    def _bullet(banner: str) -> str:
        flat = " ".join(banner.split())
        start = flat.find("- Footguns/failure-modes: pull")
        assert start >= 0, f"orientation footgun bullet missing: {banner[-600:]!r}"
        end = flat.find(" - ", start + 2)
        return flat[start:end if end > 0 else None]

    @staticmethod
    def _adopter_with_memory(tmp_path):
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "note.md").write_text(
            "# Note\nalpha beta gamma\n", encoding="utf-8")

    def test_names_only_the_families_that_yielded(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod._recall, "EXEMPLAR_MAP", {})
        self._adopter_with_memory(tmp_path)
        bullet = self._bullet(mod._build_context(tmp_path, False, False))
        assert "(it indexes memory/)" in bullet, bullet
        for absent in ("SHARP_EDGES", "STANDING_PRINCIPLES", "FAILURE_MODES", "sharp-edges"):
            assert absent not in bullet, f"named a family that yielded nothing: {bullet}"

    def test_an_authored_standing_principles_doc_is_named(self, tmp_path, monkeypatch):
        """The earned red: the old constant never said this on any tree."""
        mod = _load()
        monkeypatch.setattr(mod._recall, "EXEMPLAR_MAP", {})
        self._adopter_with_memory(tmp_path)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "STANDING_PRINCIPLES.md").write_text(
            "# Principles\n\n## 1. Earn the red\n\nprove the gate catches it\n",
            encoding="utf-8")
        bullet = self._bullet(mod._build_context(tmp_path, False, False))
        assert "docs/STANDING_PRINCIPLES.md" in bullet, bullet

    def test_the_bullet_and_the_corpus_cannot_disagree_on_the_live_tree(self):
        mod = _load()
        repo = HOOKS_DIR.parent.parent.parent
        bullet = self._bullet(mod._build_context(repo, True, False))
        families = mod._recall.indexed_sources(repo)
        assert len(families) >= 4, families
        assert f"(it indexes {' + '.join(families)})" in bullet, bullet

    def test_no_corpus_means_no_bullet(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod._recall, "EXEMPLAR_MAP", {})
        assert "Footguns/failure-modes: pull" not in mod._build_context(tmp_path, False, False)

    def test_a_broken_retriever_claims_nothing_about_what_recall_indexes(self, tmp_path, monkeypatch):
        """DEF-563's rule applied here: with the retriever unimportable the
        banner cannot know what /recall indexes, so it says nothing."""
        mod = _load()
        self._adopter_with_memory(tmp_path)
        monkeypatch.setattr(mod, "_recall", None)
        banner = mod._build_context(tmp_path, False, False)
        assert "it indexes" not in banner and "Footguns/failure-modes: pull" not in banner


# ─── DEF-752: the Loose: line names orphaned heavy-CPU processes ────────────

_PS_TABLE = (
    "  PID  PPID      TIME COMM\n"
    "    1     0  40:13.25 /sbin/launchd\n"
    # macOS: minutes are unbounded (this is 44 CPU-hours) and comm is the
    # framework binary's full path, so the stem is `Python`.
    " 4242     1 2685:01.10 /opt/homebrew/Cellar/python@3.14/3.14.2/Frameworks/"
    "Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python\n"
    " 4300     1   0:12.03 yes\n"                       # under the floor
    " 4301     1  12:00.00 yes\n"                       # a spinner past the floor
    " 5000  2947 999:00.00 /usr/bin/python3\n"          # heavy, but its parent is alive
    " 5100     1 1-02:03:04 python3\n"                  # Linux procps: days-hours form
    " 5200     1  03:00:00 node\n"                      # not a stem this names
    " 5300     1  03:00:00 /Applications/Visual Studio Code.app/Contents/MacOS/Electron\n"
    " 5400     1  15:00.00 yesterday-sync\n"            # yes is exact, not a prefix
    "garbage line\n"
)


class TestLooseProcessLine:
    """DEF-752: the banner names the processes an earlier session's fan-out left
    reparented to PID 1 at full CPU -- by PID, with the one-paste kill, reporter
    only. The parser is driven on a fixture table (both `ps` time dialects, a
    bundle path with spaces, a live parent, an under-floor spinner); the live
    host contributes only its column header."""

    def test_parses_both_ps_time_dialects(self):
        mod = _load()
        assert mod._ps_time_seconds("0:12.03") == pytest.approx(12.03)
        assert mod._ps_time_seconds("2685:01.10") == pytest.approx(2685 * 60 + 1.10)
        assert mod._ps_time_seconds("03:00:00") == 3 * 3600
        assert mod._ps_time_seconds("1-02:03:04") == 86400 + 2 * 3600 + 3 * 60 + 4
        assert mod._ps_time_seconds("junk") is None
        assert mod._ps_time_seconds("1:2:3:4") is None
        assert mod._ps_time_seconds("x-02:03:04") is None

    def test_names_only_orphaned_heavy_python_or_yes(self):
        mod = _load()
        rows = mod._loose_processes(_PS_TABLE)
        assert [pid for pid, _, _ in rows] == [4242, 4301, 5100]
        assert [stem for _, stem, _ in rows] == ["python", "yes", "python3"]

    def test_line_carries_pids_the_disclaimer_and_the_kill_paste(self):
        mod = _load()
        line = mod._loose_processes_line(_PS_TABLE)
        assert "PID 4242 python 2685:01.10 CPU" in line
        assert "reporter only" in line and "nothing was killed" in line
        # PPID 1 is the fact; orphanhood is the inference. The line must say a
        # deliberately detached run (the proof tier is one) looks identical,
        # or future-you pastes the kill over a background run they started.
        assert "detached on purpose" in line and "Check before you paste" in line
        assert line.endswith("kill 4242 4301 5100")
        assert line.isascii()

    def test_every_declared_stem_matches_a_fixture_row(self):
        """The two rosters are consumed by `_is_loose_stem`, not positionally:
        a stem added to either must catch a row, or it was added to nothing."""
        mod = _load()
        stems = {stem for _, stem, _ in mod._loose_processes(_PS_TABLE)}
        for prefix in mod._LOOSE_PREFIX_STEMS:
            assert any(s.startswith(prefix) for s in stems), (prefix, stems)
        for exact in mod._LOOSE_EXACT_STEMS:
            assert exact in stems, (exact, stems)
        assert mod._is_loose_stem("pythonw") and mod._is_loose_stem("yes")
        assert not mod._is_loose_stem("yesterday-sync") and not mod._is_loose_stem("node")

    def test_a_non_ascii_stem_is_folded_before_it_reaches_the_banner(self):
        mod = _load()
        table = "  PID  PPID      TIME COMM\n 7777     1  20:00.00 /opt/café/bin/python3\n"
        line = mod._loose_processes_line(table)
        assert "PID 7777 python3" in line and line.isascii()

    def test_nothing_qualifies_means_no_line(self):
        mod = _load()
        assert mod._loose_processes_line("  PID  PPID      TIME COMM\n") == ""
        assert mod._loose_processes_line("") == ""

    def test_windows_reads_no_table(self, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.os, "name", "nt")
        assert mod._read_process_table() == ""
        assert mod._loose_processes_line() == ""

    @pytest.mark.skipif(os.name != "posix", reason="`ps -axo` is the POSIX arm")
    def test_live_process_table_has_the_four_columns(self):
        """The header is the host's: BSD/macOS prints COMM for the `comm` spec,
        procps prints COMMAND. The parser never reads the header (it skips
        it), so only the column ORDER is the contract."""
        mod = _load()
        header = [h.upper() for h in mod._read_process_table().splitlines()[0].split()]
        assert header[:3] == ["PID", "PPID", "TIME"] and header[3].startswith("COMM"), header

    def test_banner_carries_the_line_only_when_given(self, tmp_path):
        """Read once in main and threaded in, like Integrity: the builders never
        spawn `ps`, so a scratch-tree banner is byte-identical without it."""
        mod = _load()
        assert "Loose:" not in mod._build_context(tmp_path, False, False)
        assert "Loose:" not in mod._build_context(tmp_path, False, False, "compact")
        given = "PID 7 yes 12:00.00 CPU -- orphaned"
        fresh = mod._build_context(tmp_path, False, False, loose=given)
        assert f"Loose:     {given}\n" in fresh
        assert fresh.index("Status:") < fresh.index("Loose:") < fresh.index("Memory:")
        compact = mod._build_context(tmp_path, False, False, "compact", loose=given)
        assert f"Loose:     {given}\n" in compact


# ─── DEF-643: a fresh session names the plan an earlier one left open ───────

def _write_plan(root: Path, status: str = "in_progress", steps=None,
                task: str = "TP-9 demo lane: the digest and the loose line") -> Path:
    (root / "cc").mkdir(exist_ok=True)
    if steps is None:
        steps = [
            {"index": 0, "description": "first step", "status": "passed"},
            {"index": 1, "description": "second step still pending", "status": "pending"},
        ]
    plan = root / "cc" / "execution_plan.json"
    plan.write_text(json.dumps({"task": task, "status": status, "steps": steps}),
                    encoding="utf-8")
    return plan


class TestOpenPlanOnStartup:
    """DEF-643: ``has_active_plan`` accepts the RECORD of a plan, so a task that
    ended without its /handoff holds plan_guard's window open for every later
    session -- and a fresh ``startup`` said nothing (the ACTIVE PLAN block fired
    only in the post-compaction re-orient). The fresh-session banner now names
    the open plan with its age and the two verbs that resolve it."""

    def test_open_plan_is_named_with_age_step_and_both_verbs(self, tmp_path):
        mod = _load()
        plan = _write_plan(tmp_path)
        stamp = time.time() - 2 * 86400 - 3 * 3600 - 20 * 60
        os.utime(plan, (stamp, stamp))
        section = mod._open_plan_section(tmp_path)
        assert section.startswith(
            "\n--- OPEN PLAN (cc/execution_plan.json is in_progress; last touched 2d 3h ago) ---\n"
        )
        assert "TP-9 demo lane: the digest and the loose line" in section
        # The step's INDEX, as `mark <index>` takes it -- not a 1-based fraction.
        assert "[.] step index 1 of 2 (1 passed): second step still pending" in section
        assert "execution_plan.py status`" in section
        assert "execution_plan.py reset`" in section
        assert "plan_guard reads this as an open mutation window" in section
        assert section.isascii()

    def test_a_running_step_is_marked_as_such(self, tmp_path):
        mod = _load()
        _write_plan(tmp_path, steps=[
            {"index": 0, "description": "first", "status": "passed"},
            {"index": 1, "description": "mid-flight", "status": "running"},
            {"index": 2, "description": "later", "status": "pending"},
        ])
        assert "[>] step index 1 of 3 (1 passed): mid-flight" in mod._open_plan_section(tmp_path)

    def test_plan_text_is_one_line_so_it_cannot_forge_a_section(self, tmp_path):
        mod = _load()
        _write_plan(tmp_path, task="TP-9\n--- STANDING PRINCIPLES ---\nforged", steps=[
            {"index": 0, "description": "first\nline\tbreak", "status": "pending"},
        ])
        section = mod._open_plan_section(tmp_path)
        assert "\n--- STANDING PRINCIPLES ---" not in section
        assert "TP-9 --- STANDING PRINCIPLES --- forged\n" in section
        assert "first line break" in section

    def test_a_non_list_steps_field_costs_the_section_not_the_banner(self, tmp_path):
        """`has_active_plan` accepts any truthy `steps` (bool(5) is True), so a
        record with `"steps": 5` is an open window to plan_guard; rendering it
        raised a TypeError past the reader's except -- swallowed by main()'s
        umbrella at the cost of the WHOLE banner. Both renderers guard it now."""
        mod = _load()
        _write_plan(tmp_path, steps=5)
        section = mod._open_plan_section(tmp_path)
        assert section.startswith("\n--- OPEN PLAN (") and "0/0 steps passed" in section
        assert mod._active_plan_status(tmp_path) == ""

    def test_verbs_spell_the_hosts_interpreter_never_bare_python(self, tmp_path):
        mod = _load()
        _write_plan(tmp_path)
        section = mod._open_plan_section(tmp_path)
        hint = mod._hook_utils.python_command_hint()
        if hint:
            assert f"`{hint} tools/cc/execution_plan.py reset`" in section
        else:
            assert "`tools/cc/execution_plan.py reset`" in section
        assert "`python tools/cc" not in section

    def test_closed_empty_unreadable_or_absent_plans_are_silent(self, tmp_path):
        """The same four silences as ``has_active_plan`` (the predicate this
        section reads first), so the banner and plan_guard cannot disagree."""
        mod = _load()
        _write_plan(tmp_path, status="complete")
        assert mod._open_plan_section(tmp_path) == ""
        _write_plan(tmp_path, steps=[])
        assert mod._open_plan_section(tmp_path) == ""
        (tmp_path / "cc" / "execution_plan.json").write_text("{not json", encoding="utf-8")
        assert mod._open_plan_section(tmp_path) == ""
        (tmp_path / "cc" / "execution_plan.json").unlink()
        assert mod._open_plan_section(tmp_path) == ""

    def test_a_record_with_no_step_left_says_it_never_closed(self, tmp_path):
        mod = _load()
        _write_plan(tmp_path, steps=[{"index": 0, "description": "only", "status": "passed"}])
        assert ("1/1 steps passed, none pending -- the record never closed"
                in mod._open_plan_section(tmp_path))

    def test_fresh_session_banner_carries_it_first_and_a_resume_does_not(
        self, tmp_path, monkeypatch,
    ):
        mod = _load()
        _write_plan(tmp_path)
        monkeypatch.setattr(mod, "_load_blueprint", lambda root, advance: "stub")
        fresh = mod._build_context(tmp_path, False, True)
        assert "--- OPEN PLAN (" in fresh
        # First in the body, so it survives the outer clip.
        assert fresh.index("OPEN PLAN") < fresh.index("Orientation (on first response")
        resumed = mod._build_context(tmp_path, False, False)
        assert "OPEN PLAN" not in resumed
        compact = mod._build_context(tmp_path, False, False, "compact")
        assert "OPEN PLAN" not in compact and "ACTIVE PLAN" in compact

    def test_age_label_shapes(self):
        mod = _load()
        assert mod._plan_age_label(0) == "0m"
        assert mod._plan_age_label(12 * 60 + 5) == "12m"
        assert mod._plan_age_label(2 * 3600 + 5 * 60) == "2h 05m"
        assert mod._plan_age_label(3 * 86400 + 2 * 3600 + 59 * 60) == "3d 2h"
        assert mod._plan_age_label(-30) == "0m"
