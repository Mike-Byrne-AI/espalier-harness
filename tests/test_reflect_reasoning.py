"""TP-63: reasoning-review sub-mode of ``/reflect`` (``--reasoning``).

Pins the testable surfaces of the reasoning-review feature:

- Checklist file exists at the expected path and is versioned.
- Reflect skill body contains the ``--reasoning`` section.
- Shipped asset matches the local copy (no SoT-mirror drift).
- ``.espalier/reasoning_review_log.jsonl`` is gitignored (the log
  is per-session operator output, not shared history).

Without this contract any one of those surfaces could silently
drift — the checklist could disappear, the skill could stop
mentioning ``--reasoning``, the mirror could go out of sync, or
the log could start landing in git history exposing private
session reasoning to every adopter.

The agent dispatch itself is Claude-Code-runtime; not testable in
pytest. The anti-theater calibration metric (acknowledge-rate
over the gitignored log) is operator-discipline, not asserted here.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
CHECKLIST = REPO / "tools" / "cc" / "reasoning_review_checklist.md"
SKILL = REPO / ".claude" / "skills" / "reflect" / "SKILL.md"
SHIPPED_SKILL = REPO / "espalier" / "assets" / "claude" / "skills" / "reflect" / "SKILL.md"
GITIGNORE = REPO / ".gitignore"


def _checklist_item_titles(path: Path) -> list[str]:
    """Item-header titles from the bold ``**N. Title.**`` reasoning checklist.

    Used to pin that every item is INLINED into the shipped skill body
    (TP-189 ARCH-1): the checklist used to be referenced by file path, which
    dangled for adopters who never receive ``tools/cc/*.md``. The standalone
    file stays the canonical version-stamped source; the body must carry its
    substance so the review is self-contained.

    Retained for the version-label and item-count assertions only. Item CONTENT
    is now compared in full by ``_checklist_item_bodies``: with titles alone, an
    item's entire elaboration could be replaced with nonsense and the suite
    stayed green — measured on both checklists, not supposed.
    """
    text = path.read_text(encoding="utf-8")
    return [
        m.group(1).strip()
        for m in re.finditer(r"(?m)^\s*(?:\*\*)?\d+\.\s+([A-Z][^.\n*]+)\.", text)
    ]


def _dequote(text: str) -> str:
    """Strip the blockquote prefix the reflect skill wraps its prompt in."""
    return "\n".join(re.sub(r"^\s*>\s?", "", ln) for ln in text.splitlines())


def _checklist_item_bodies(path: Path) -> list[str]:
    """Full item blocks (title + elaboration), whitespace-normalised.

    An INDEPENDENT oracle: the companion test compares the skill body against
    ``scripts/sync_checklist_regions.py``'s own render, which proves the region
    is in sync but not that the render is right -- the same code on both sides of
    the ``==`` (``docs/sharp-edges/closed-loop-verification-trap.md``).

    The ``end`` bound is load-bearing. Without it the last item absorbs the
    file's trailing ``Output format per item:`` block and never matches, which
    reads exactly like a drifted item -- a false positive I produced once by
    omitting it.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("**1."))
    end = next(
        i for i, ln in enumerate(lines) if ln.startswith("Output format per item:")
    )
    items: list[str] = []
    current: list[str] = []
    for ln in lines[start:end]:
        if re.match(r"^\*\*\d+\.", ln):
            if current:
                items.append(" ".join(" ".join(current).split()))
            current = [ln]
        elif ln.strip():
            current.append(ln)
    if current:
        items.append(" ".join(" ".join(current).split()))
    return items


def _load_sync_script():
    """Load ``scripts/sync_checklist_regions.py`` by path (scripts/ is not a package)."""
    import importlib.util

    path = REPO / "scripts" / "sync_checklist_regions.py"
    spec = importlib.util.spec_from_file_location("sync_checklist_regions", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReasoningReviewSurface:
    def test_checklist_file_exists(self):
        assert CHECKLIST.is_file(), f"missing checklist at {CHECKLIST}"

    def test_checklist_carries_version_header(self):
        body = CHECKLIST.read_text(encoding="utf-8")
        assert "TP-63 v1" in body, "checklist must declare its version"

    def test_checklist_lists_four_severities(self):
        body = CHECKLIST.read_text(encoding="utf-8")
        for sev in ("PASS", "GAP", "BIAS", "UNCHECKED"):
            assert sev in body, f"checklist must mention {sev} severity"

    def test_reasoning_section_in_skill_body(self):
        body = SKILL.read_text(encoding="utf-8")
        assert "--reasoning" in body, (
            "/reflect skill must reference the --reasoning sub-mode"
        )
        assert "advisory, not blocking" in body.lower(), (
            "skill must call out reasoning review is advisory"
        )

    def test_checklist_inlined_into_skill_body(self):
        # TP-189 ARCH-1: the checklist is INLINED into the skill body (it used
        # to instruct "read tools/cc/reasoning_review_checklist.md" -- a
        # dangling ref for adopters who never receive that file). Pin that the
        # body carries the version label and every canonical item title, so it
        # cannot silently drift back to a bare file reference.
        raw = SKILL.read_text(encoding="utf-8")
        # Version label WITHOUT the internal pack ID -- reflect is a common-tier
        # adopter skill; test_init_tier_split forbids `TP-NN` here. The canonical
        # file keeps the full `TP-63 v1` header; the inlined body drops the ID.
        assert "fixed checklist, v1" in raw, (
            "inlined checklist must carry its (pack-ID-free) version label"
        )
        # FULL item text, not titles. The title-only form this replaced was
        # measured blind: with only titles compared, every elaboration in the
        # source could be replaced with nonsense and the suite stayed green.
        body = " ".join(_dequote(raw).split())
        items = _checklist_item_bodies(CHECKLIST)
        assert len(items) == 7, f"expected 7 reasoning items, found {len(items)}"
        for item in items:
            assert item in body, (
                "checklist item text is in the canonical file but not inlined "
                "into the skill body (drift). Run "
                "`python3 scripts/sync_checklist_regions.py`.\n"
                f"  missing: {item[:120]}..."
            )

    def test_inlined_checklist_is_generated_from_source(self):
        """The inlined region equals what the sync script renders from the SoT.

        The companion assertion above re-slices the source with its own logic and
        its own de-quoting, so a bug in the script's extraction surfaces as a
        disagreement between the two rather than as a blind spot shared by both.
        """
        sync = _load_sync_script()
        region = next(r for r in sync.REGIONS if r.name == "reasoning-review-checklist")
        rendered = sync.render(
            region, sync.extract_items(region, CHECKLIST.read_text(encoding="utf-8"))
        )
        _, current = sync.splice(region, SKILL.read_text(encoding="utf-8"), rendered)
        assert current == rendered, (
            "the generated reasoning-checklist region is out of sync with "
            f"{CHECKLIST.name} -- run `python3 scripts/sync_checklist_regions.py`"
        )

    def test_generated_region_stays_inside_the_blockquoted_prompt(self):
        """The transform, pinned from the FILE rather than the constant.

        Neither companion assertion can see the prefix: the round-trip one calls
        ``render()`` for its expected value, and the independent one de-quotes
        before comparing. The prefix is not cosmetic -- this region sits inside a
        blockquoted agent prompt, and a line that loses its ``>`` ends the quote,
        splitting the template the skill tells Claude to paste.
        """
        raw = SKILL.read_text(encoding="utf-8").split("\n")
        b = next(i for i, ln in enumerate(raw)
                 if "reasoning-review-checklist: BEGIN" in ln)
        e = next(i for i, ln in enumerate(raw[b + 1:], b + 1)
                 if "reasoning-review-checklist: END" in ln)
        body = raw[b + 1:e]
        assert body, "the generated region is empty"
        stray = [ln for ln in body if not ln.startswith("   >")]
        assert not stray, (
            "every generated line must stay inside the blockquote (prefix '   >'); "
            f"a bare line terminates the prompt template. Offenders: {stray[:2]}"
        )

    def test_shipped_asset_matches_local(self):
        local = SKILL.read_text(encoding="utf-8")
        shipped = SHIPPED_SKILL.read_text(encoding="utf-8")
        assert local == shipped, (
            "shipped reflect skill asset must match local copy"
        )

    def test_reasoning_log_gitignored(self):
        body = GITIGNORE.read_text(encoding="utf-8")
        # Assert the SPECIFIC log entry, not `... or ".espalier/" in body`: the
        # generic ".espalier/" substring is matched by unrelated .gitignore
        # entries (integrity.json, the write lock, ...), so the old disjunct was
        # always true and stayed green even if this exact line were deleted.
        assert "reasoning_review_log" in body, (
            ".espalier/reasoning_review_log.jsonl must be covered by .gitignore"
        )


class TestReasoningReviewDocumented:
    """Operator-discipline checks: documentation must mention the
    advisory-only posture, the anti-theater calibration metric, and
    the agent-diversity discipline so reviewers can audit the design
    without reading the source pack."""

    def test_conventions_documents_reasoning_review(self):
        conventions = (REPO / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
        assert "### Reasoning review" in conventions, (
            "CONVENTIONS.md must carry a Reasoning review section"
        )
        for sev in ("GAP", "BIAS", "UNCHECKED", "PASS"):
            assert sev in conventions, (
                f"CONVENTIONS.md reasoning review section must explain {sev}"
            )

    def test_sharp_edges_documents_agent_diversity(self):
        sharp = (REPO / "docs" / "SHARP_EDGES.md").read_text(encoding="utf-8")
        assert "Reasoning-Review Agent Diversity" in sharp or \
               "diversity-of-context" in sharp.lower(), (
            "SHARP_EDGES.md must document the agent-diversity discipline"
        )
