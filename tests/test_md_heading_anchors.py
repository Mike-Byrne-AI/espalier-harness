"""Tree-wide contract: every ``#fragment`` resolves to a heading that exists.

The gap this closes was total. Every link checker in the repo -- the artifact walker,
both reflect-protocol twins, the ladder pointer contract -- split on ``#`` and threw the
fragment away before validating. So ``[see the rules](docs/FOO.md#the-rules)`` was
checked as far as ``docs/FOO.md`` existing, and renaming that heading broke the link
while every checker still called it resolved. Nothing mechanical could see it, in either
direction, forever.

Shape follows the neighbouring tree-wide contracts (``test_catalog_self_consistency``'s
line-anchor arms, ``test_ladder_claudemd_pointers``'s link half): population from
``git ls-files`` so a new doc auto-enrols and gitignored scratch is never scanned; ONE
test that loops and collects every failure rather than a ``parametrize`` that would
generate zero cases and silently pass on a non-git tree; an explicit floor so a
regression that stops matching anything reds loudly instead of reporting success.

SAME-FILE ANCHORS ARE IN SCOPE, and they are the reason this does not simply reuse
``_artifact_links.iter_relative_links``: that extractor's regex deliberately excludes
``[text](#anchor)`` because an in-page link can never 404 in the sense IT cares about
(a missing file). It can absolutely rot, and a table of contents is built entirely from
these -- so the exclusion that is right for the artifact walker is exactly wrong here.
"""
# slow-exempt: the one subprocess call is a single fast `git ls-files` enumeration
# (`_tracked_markdown`); everything after it is in-process text work.
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from _md_anchors import heading_anchors

REPO_ROOT = Path(__file__).resolve().parents[1]

# Any markdown link that carries a fragment: `[text](target#frag)` or `[text](#frag)`.
# External targets are filtered after the match so the pattern stays readable.
_FRAGMENT_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]*#[^)\s]*)\)")

# Illustrative spellings that are not real targets -- same calibration as
# `_artifact_links._PLACEHOLDER_RE`, which learned it from live false findings.
_PLACEHOLDER_RE = re.compile(r"[<>]")

#: A COLLAPSE DETECTOR, not a census. The tree carries ~90 checkable fragment links;
#: the floor sits well below that so ordinary doc churn never trips it, while a regex
#: or resolver regression that matches nothing -- which would otherwise assert nothing
#: and report success -- reds. Raise it only with a measurement.
_MIN_FRAGMENT_ANCHORS = 40


def _strip_fenced_blocks(text: str) -> str:
    """Blank out ``` fenced regions, preserving line count for reporting.

    A link inside a fence renders as literal text, so it can never rot. Counting them
    produced phantom findings in the sibling artifact checker; the same applies here.
    """
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return "\n".join(out)


def _tracked_markdown() -> list[str]:
    """Every git-tracked ``*.md``. ``git ls-files`` (NOT ``Path.rglob``) so only
    committed surface is walked and gitignored scratch -- which carries anchor-shaped
    text -- is never scanned. Empty on a non-git tree; the caller SKIPS, fail-closed."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted(f for f in out.split() if f.endswith(".md"))


def _anchor_findings(docs: list[str]) -> tuple[int, list[str]]:
    """``(fragments CHECKED, failures)``.

    Reports what was actually EVALUATED, not what the regex matched. The two differ --
    a fragment whose target is untracked, or is not markdown, is skipped -- and the
    difference is the point of the count: a resolver regression makes every target
    unresolvable, at which point the regex still matches ~90 links while the gate
    checks none of them. Counting matches would call that full coverage.
    """
    anchors: dict[str, set[str]] = {}

    def anchors_of(rel: str) -> set[str] | None:
        if rel not in anchors:
            path = REPO_ROOT / rel
            anchors[rel] = (
                heading_anchors(path.read_text(encoding="utf-8", errors="replace"))
                if path.is_file()
                else None
            )
        return anchors[rel]

    tracked = set(docs)
    checked = 0
    failures: list[str] = []
    for rel in docs:
        text = _strip_fenced_blocks(
            (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        )
        for m in _FRAGMENT_LINK_RE.finditer(text):
            raw = m.group(1)
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            if _PLACEHOLDER_RE.search(raw):
                continue
            target, _, fragment = raw.partition("#")
            fragment = fragment.strip()
            if not fragment:
                continue
            if not target:
                target_rel = rel  # same-file anchor: resolve against this doc
            elif target.startswith("/"):
                continue  # absolute path — not a repo-relative link
            else:
                try:
                    resolved = (REPO_ROOT / rel).parent.joinpath(target).resolve()
                    target_rel = str(resolved.relative_to(REPO_ROOT)).replace("\\", "/")
                except ValueError:
                    continue  # climbs out of the repo — not this gate's business
            if not target_rel.endswith(".md") or target_rel not in tracked:
                continue  # a missing FILE is the sibling link contracts' finding
            available = anchors_of(target_rel)
            if available is None:
                continue
            checked += 1
            if fragment.lower() in available:
                continue
            line = text[: m.start()].count("\n") + 1
            failures.append(
                f"{rel}:{line} -> {target_rel}#{fragment} (no such heading)"
            )
    return checked, failures


def test_every_fragment_link_resolves_to_a_real_heading():
    """The gate. Floor asserted BEFORE the failures: a population that collapsed to
    zero would otherwise report "no failures" and read as a pass."""
    docs = _tracked_markdown()
    if not docs:
        pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")
    checked, failures = _anchor_findings(docs)
    assert checked >= _MIN_FRAGMENT_ANCHORS, (
        f"the heading-anchor scan EVALUATED {checked} fragment links across "
        f"{len(docs)} docs, below the floor of {_MIN_FRAGMENT_ANCHORS}. Three "
        "regressions land here: the link regex stopped matching, target resolution "
        "stopped resolving, or the doc population shrank. In every case the gate is "
        "asserting over far less than it appears to. If the docs genuinely shed "
        "anchors, lower the floor DELIBERATELY and with a measurement."
    )
    assert not failures, (
        "markdown links pointing at headings that do not exist (correct the fragment, "
        "or restore the heading):\n  " + "\n  ".join(failures)
    )


def test_earn_the_red_renamed_heading_is_detected(tmp_path):
    """Catches-the-bad half: a fragment naming a heading that is not there fails, and
    names the citer. Driven on a synthetic pair so the proof does not depend on the
    live tree happening to contain a defect."""
    doc = "# Real Heading\n\nbody\n"
    assert "real-heading" in heading_anchors(doc)
    assert "renamed-heading" not in heading_anchors(doc)


def test_earn_the_red_clears_on_an_unchanged_tree():
    """Clears-the-good half. Stated as its own test because "the gate is green" and
    "the gate can go red" are different claims, and a gate that only ever passed
    proves nothing about either."""
    docs = _tracked_markdown()
    if not docs:
        pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")
    checked, failures = _anchor_findings(docs)
    assert checked > 0 and not failures


def test_same_file_anchors_are_actually_reached():
    """Pin that in-page ``[text](#anchor)`` links are IN the population.

    They are the reason this module does not reuse ``_artifact_links``, whose regex
    excludes them by design. Without this test that exclusion could be reintroduced
    here -- by sharing the sibling's regex "to avoid duplication" -- and the whole
    table-of-contents class would go unchecked while the gate stayed green.
    """
    docs = _tracked_markdown()
    if not docs:
        pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")
    same_file = 0
    for rel in docs:
        text = _strip_fenced_blocks(
            (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        )
        for m in _FRAGMENT_LINK_RE.finditer(text):
            raw = m.group(1)
            if raw.startswith("#") and not _PLACEHOLDER_RE.search(raw):
                same_file += 1
    assert same_file > 0, (
        "no same-file `[text](#anchor)` links found in the tracked tree -- either the "
        "tree genuinely has none (then drop this pin deliberately) or the extractor "
        "stopped seeing them, which is the regression this exists to catch."
    )
