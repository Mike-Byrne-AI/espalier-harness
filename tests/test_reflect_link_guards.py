"""Broken-link guard + blueprint-archive exclusion parity across the three
reflect entrypoints.

``espalier/reflection.py`` (the mature reference) skips three link shapes that
are documentation *of* the link syntax rather than navigable links — trailing-
slash directory links, ``<placeholder>`` targets, and bare ``...`` targets — and
restricts its walk to release-``public`` files. Its two structured twins
(``espalier/reflect_protocol.py`` and the standalone
``tools/cc/reflect_protocol.py``) were copied from it without either
protection, so every reflect pass re-emitted 8 phantom high-severity gaps.

Phantom gaps are not merely noise: a genuinely broken link is camouflaged by
them, which is the exact failure the reflect pass exists to catch. True
code-sharing across the ``espalier/`` ↔ ``tools/cc/`` isolation boundary is
impossible, so this shared-corpus test is the anti-re-drift mechanism — it
asserts all three entrypoints agree on the same fixture.

The positive control is load-bearing: "zero broken links" is also what a
*disabled* detector returns, so every guard assertion is paired with a real
broken link that must still fire.
"""
from __future__ import annotations

# slow-exempt: the one subprocess test is a single `--pass 1 --json` invocation
# of the standalone walker over a three-file temp repo (~0.05s). Keeping it in
# the fast slice is deliberate — this is a twin-parity lock, and parity drift
# should surface on the common run, not only under `-m slow`.

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from espalier.reflect_protocol import (
    LOCAL_ONLY_PREFIXES,
    run_reflect_pass,
)
from espalier.reflection import reflect_repo

REPO_ROOT = Path(__file__).resolve().parent.parent
STANDALONE = REPO_ROOT / "tools" / "cc" / "reflect_protocol.py"

# Link shapes that must NOT be reported — each is documentation of the link
# shape, not a navigable target. Drawn from the live false positives this
# guard was written to kill (docs/CONVENTIONS.md, docs/session-archive.md).
# The angle-bracket skip is scoped to the TARGET: a placeholder link carries
# `<` in its target (`(memory/<slug>.md)`), not merely in its display text —
# see TestAngleBracketInTextOnly for the real-broken-link counter-case.
FP_CORPUS = """\
1. Read [`memory/<slug>.md`](memory/<slug>.md) — accumulated experience.
2. Packs live in [task-packs/](task-packs/) (gitignored).
3. An elided target looks like [example](...) in prose.
"""
# The positive control — a real broken link that every entrypoint must flag.
REAL_BROKEN = "See [the guide](definitely-missing-target.md) for details.\n"


@pytest.fixture()
def surface_repo(tmp_path: Path) -> Path:
    """A minimal repo carrying the FP corpus, a real broken link, and an
    archive file whose prose discusses link syntax."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "cc" / "blueprints" / "compact_summaries").mkdir(parents=True)

    (tmp_path / "CLAUDE.md").write_text("# Root\n\nSee [ESPALIER_MEMORY.md](ESPALIER_MEMORY.md).\n",
                                        encoding="utf-8")
    (tmp_path / "ESPALIER_MEMORY.md").write_text("# Memory\n\nSee [CLAUDE.md](CLAUDE.md).\n",
                                        encoding="utf-8")
    (tmp_path / "docs" / "CONVENTIONS.md").write_text(FP_CORPUS + REAL_BROKEN,
                                                      encoding="utf-8")
    # Historical session prose: talks *about* `[text](path)` markdown links.
    (tmp_path / "cc" / "blueprints" / "compact_summaries" / "archive.md").write_text(
        "Wrote a `[text](path)` markdown link and a [url](url) reference.\n",
        encoding="utf-8",
    )
    return tmp_path


def _engine_links(repo: Path) -> list[str]:
    return [f.description for f in run_reflect_pass(repo, 1).findings
            if "Broken link" in f.description]


def _standalone_links(repo: Path) -> list[str]:
    proc = subprocess.run(
        [sys.executable, str(STANDALONE), "--pass", "1", "--json"],
        cwd=repo, capture_output=True, text=True, timeout=120, encoding="utf-8",
    )
    assert proc.returncode == 0, f"standalone failed: {proc.stderr}"
    report = json.loads(proc.stdout)
    return [f["description"] for f in report["findings"]
            if "Broken link" in f["description"]]


def _reference_links(repo: Path) -> list[str]:
    return [b["target"] if "target" in b else str(b)
            for b in reflect_repo(repo)["broken_markdown_links"]]


def _read_prefixes(src: str) -> tuple[str, ...]:
    """Extract the LOCAL_ONLY_PREFIXES tuple from module source — multi-line-
    safe, evaluates no code (``ast.literal_eval`` on the assignment RHS). The
    old ``startswith``-line + ``exec`` scan truncated a multi-line tuple to its
    opening ``(`` (a SyntaxError) or a partial first line, a born-weak parity
    gate that false-greened exactly when the tuple grew past one entry."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "LOCAL_ONLY_PREFIXES"
            for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("LOCAL_ONLY_PREFIXES assignment not found in source")


# ─── guards ──────────────────────────────────────────────────────────────────

class TestBrokenLinkGuards:
    """The three documentation-of-link-shape forms are skipped by every
    entrypoint, while a real broken link still fires."""

    def test_engine_skips_false_positives_but_flags_real(self, surface_repo):
        links = _engine_links(surface_repo)
        assert not [d for d in links if "<slug>" in d or "task-packs/" in d
                    or "(...)" in d], f"guard leaked: {links}"
        assert any("definitely-missing-target.md" in d for d in links), \
            "positive control lost — the detector is disabled, not guarded"

    def test_standalone_skips_false_positives_but_flags_real(self, surface_repo):
        links = _standalone_links(surface_repo)
        assert not [d for d in links if d.endswith(": memory/<slug>.md")
                    or d.endswith(": task-packs/") or d.endswith(": ...")], \
            f"guard leaked: {links}"
        assert any("definitely-missing-target.md" in d for d in links), \
            "positive control lost — the detector is disabled, not guarded"

    def test_reference_implementation_still_agrees(self, surface_repo):
        """espalier/reflection.py is the copy-source and stays unmodified —
        this pins that the twins were aligned *to* it, not away from it."""
        targets = " ".join(_reference_links(surface_repo))
        assert "definitely-missing-target.md" in targets
        assert "task-packs/" not in targets


# ─── archive exclusion ───────────────────────────────────────────────────────

class TestBlueprintArchiveExclusion:
    """cc/blueprints/ is a non-navigable local-only record; link-checking its
    prose yields only phantom gaps."""

    def test_engine_excludes_archive(self, surface_repo):
        assert not [d for d in _engine_links(surface_repo) if "blueprints" in d]

    def test_standalone_excludes_archive(self, surface_repo):
        assert not [d for d in _standalone_links(surface_repo) if "blueprints" in d]

    def test_live_cc_docs_are_not_collateral(self, surface_repo):
        """The exclusion is prefix-scoped, not a blanket release-class gate:
        live cc/ docs classify local_only, so gating on `public` would drop
        real surface. A navigable cc/ doc must stay analyzed."""
        (surface_repo / "cc" / "LIVE_SURFACE.md").write_text(
            "See [gone](no-such-file.md).\n", encoding="utf-8")
        assert any("LIVE_SURFACE.md" in d for d in _engine_links(surface_repo))
        assert any("LIVE_SURFACE.md" in d for d in _standalone_links(surface_repo))


# ─── regenerated-summary exclusion ───────────────────────────────────────────

class TestRegeneratedSummaryExclusion:
    """The cc/_ underscore class (auto-regenerated summaries + gitignored review
    scratch) and cc/SURFACE_HANDOFF.md are excluded — a moved-file link in that
    transient prose is a phantom gap, not a real one, and the reference
    reflection.py excludes the same set via classify_release_path (the cc/_
    prefix plus the exact cc/SURFACE_HANDOFF.md entry). cc/GOAL.md is curated and
    stays scanned: a broken link in it is a genuine defect."""

    @pytest.fixture()
    def regen_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "_working_summary.md").write_text(
            "Resume: see [moved doc](../docs/gone-summary.md).\n", encoding="utf-8")
        (tmp_path / "cc" / "SURFACE_HANDOFF.md").write_text(
            "Handoff: [absent](also-gone.md).\n", encoding="utf-8")
        # A gitignored review-scratch doc (the cc/_ underscore class) — excluded
        # by the cc/_ prefix, converging with the reference reflection.py, which
        # excludes all cc/_* as local_only. Exact-string entries would miss it.
        (tmp_path / "cc" / "_pack_review_scratch.md").write_text(
            "Review note: [dead link](vanished.md).\n", encoding="utf-8")
        # Curated — a broken link here IS a real defect and must still fire.
        (tmp_path / "cc" / "GOAL.md").write_text(
            "Goal: [the plan](definitely-missing-goal-link.md).\n", encoding="utf-8")
        return tmp_path

    def test_engine_excludes_regenerated_summaries_but_scans_goal(self, regen_repo):
        links = _engine_links(regen_repo)
        assert not any("gone-summary.md" in d or "also-gone.md" in d
                       or "vanished.md" in d for d in links), \
            f"regenerated-summary / cc/_ scratch broken link leaked: {links}"
        assert any("definitely-missing-goal-link.md" in d for d in links), \
            f"curated cc/GOAL.md must stay scanned: {links}"

    def test_standalone_excludes_regenerated_summaries_but_scans_goal(self, regen_repo):
        links = _standalone_links(regen_repo)
        assert not any("gone-summary.md" in d or "also-gone.md" in d
                       or "vanished.md" in d for d in links), \
            f"regenerated-summary / cc/_ scratch broken link leaked (standalone): {links}"
        assert any("definitely-missing-goal-link.md" in d for d in links), \
            f"curated cc/GOAL.md must stay scanned (standalone): {links}"


# ─── angle-bracket in display text only ──────────────────────────────────────

class TestAngleBracketInTextOnly:
    """A real broken link whose *display text* — not its target — carries a `<`
    must still be flagged. The placeholder skip is scoped to the target, not a
    blanket `<`-anywhere-in-the-span gate; the old whole-span check silently
    dropped `[a<b](gone.md)`, a fail-open on the exact defect the scan exists to
    catch."""

    @pytest.fixture()
    def text_angle_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "note.md").write_text(
            # Real broken link; `<` lives only in the display text, target is a
            # real (missing) path — must be REPORTED.
            "See [a<b](definitely_absent.md) for the comparison.\n"
            # Control: `<` in the TARGET => genuine placeholder, still skipped.
            "Template: [x](memory/<slug>.md) shows the shape.\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_engine_flags_angle_bracket_text(self, text_angle_repo):
        links = _engine_links(text_angle_repo)
        assert any("definitely_absent.md" in d for d in links), \
            f"fail-open: real broken link with `<` in text was skipped: {links}"
        assert not any("<slug>" in d for d in links), \
            f"target-placeholder link must still be skipped: {links}"

    def test_standalone_flags_angle_bracket_text(self, text_angle_repo):
        links = _standalone_links(text_angle_repo)
        assert any("definitely_absent.md" in d for d in links), \
            f"fail-open (standalone): {links}"
        assert not any("<slug>" in d for d in links), \
            f"target-placeholder link must still be skipped (standalone): {links}"

    def test_reference_flags_angle_bracket_text(self, text_angle_repo):
        targets = " ".join(_reference_links(text_angle_repo))
        assert "definitely_absent.md" in targets, \
            f"fail-open (reference reflection.py): {targets}"
        assert "<slug>" not in targets, \
            f"target-placeholder link must still be skipped (reference): {targets}"


# ─── twin parity ─────────────────────────────────────────────────────────────

class TestTwinParity:
    """The prefix tuple is a forced twin across the no-import boundary."""

    def test_local_only_prefixes_match_across_twins(self):
        assert _read_prefixes(STANDALONE.read_text(encoding="utf-8")) == \
            LOCAL_ONLY_PREFIXES

    def test_read_prefixes_reads_a_multiline_tuple_whole(self):
        """Witness for the parser hardening (I5): a multi-line constant is read
        in full. The old ``startswith``+``exec`` line-scan truncated it — a
        born-weak parity gate that false-greened precisely when the tuple grew
        past one entry (which I4 does). AST parse reads the whole assignment;
        the first-line ``exec`` raises."""
        multiline = (
            'LOCAL_ONLY_PREFIXES = (\n'
            '    "a/",\n'
            '    "b/",\n'
            '    "c/",\n'
            ')\n'
        )
        assert _read_prefixes(multiline) == ("a/", "b/", "c/")
        first_line = next(ln for ln in multiline.splitlines()
                          if ln.startswith("LOCAL_ONLY_PREFIXES"))
        with pytest.raises(SyntaxError):
            exec(first_line, {})  # noqa: S102 — demonstrates the old gate's blindness

    def test_blueprint_prefix_is_covered(self):
        assert "cc/blueprints/" in LOCAL_ONLY_PREFIXES

    def test_local_only_prefixes_documented_in_conventions(self):
        """I6: the third zero-import forced twin is documented in the conventions
        doc's 'Library / hook parity' section. A plain substring assert so a
        future reword that drops the term reds honestly."""
        conv = (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
        assert "LOCAL_ONLY_PREFIXES" in conv, (
            "LOCAL_ONLY_PREFIXES (the third zero-import forced twin) is "
            "undocumented in docs/CONVENTIONS.md — see 'Library / hook parity'"
        )
