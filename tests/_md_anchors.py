"""GitHub-compatible heading slugs, so a ``#fragment`` can actually be validated.

Not a test module (leading underscore) -- no marker classification needed.

Every link checker in this repo threw the fragment away before validating, so a
heading rename silently rotted every link pointing at it, tree-wide, forever. The
target file still existed, so every checker said the link was fine. This module is
the missing half: resolve the fragment against the target's real headings.

GitHub's rule (``github-slugger``), applied to a heading's RENDERED text:

1. lowercase and trim;
2. drop every character that is not alphanumeric, ``_``, ``-`` or a space;
3. spaces become hyphens;
4. a repeated slug gets ``-1``, ``-2``, ... appended in document order.

CALIBRATION NOTES -- each of these was measured against this repo's live headings,
not assumed, because a slugifier that is subtly wrong produces false findings and
false findings are what get a guard neutered:

* **Markdown markers need no special handling except links.** Backticks and
  asterisks are already punctuation, so step 2 removes them: ``## The **bold** bit``
  and ``## The `code` bit`` slug correctly for free.
* **Underscores must survive.** A paired-emphasis regex (``_([^_]*)_``) looks like
  the right way to strip ``_italics_``, but it mangles every ``snake_case``
  identifier in a heading -- ``foo_bar_baz`` becomes ``foobarbaz`` -- and this repo's
  headings are full of them. GitHub keeps underscores; so do we, and ``_italics_``
  slugs to ``_italics_``, which is what GitHub produces too.
* **Links must contribute only their text.** ``[Foo](bar.md)`` renders as ``Foo``,
  so the URL must be removed BEFORE step 2 -- otherwise it slugs to ``foobarmd``.
  This is the one markdown construct that genuinely needs unwrapping.
* **Trailing ``#`` closers are stripped** (``## Title ##``), and setext headings
  (``Title`` over ``=====``) are not supported: this repo uses ATX exclusively.

ONE PREMISE IS DELIBERATELY NOT ASSERTED. When punctuation removal leaves a RUN of
spaces -- ``## Step 1 — Identify`` becomes ``step 1  identify`` once the em-dash goes
-- GitHub maps each space to its own hyphen (``step-1--identify``) rather than
collapsing the run (``step-1-identify``). That is what ``github-slugger`` does, but
this tree cannot confirm it: 614 headings are affected and NOT ONE of them is linked
to by anchor, so the live population is silent and there is no oracle here to settle
it. Guessing wrong in either direction produces false findings on 614 headings, and
false findings are what get a guard neutered.

So ``heading_anchors`` emits BOTH spellings for such a heading and
``test_md_anchors.py`` pins that it does. The cost is precise and small: a link that
uses the wrong NUMBER of hyphens inside an otherwise-correct anchor is not caught. The
class this module exists to close -- a heading renamed or deleted out from under its
citers -- is caught either way. Collapse this to one spelling only after checking a
GitHub-rendered anchor for a heading with a punctuation-separated run.
"""

from __future__ import annotations

import re

# ``[text](url)`` and ``![alt](url)`` -> their text. The only markdown construct
# whose markup would otherwise leak into the slug; see the module docstring.
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")

# Everything GitHub discards: not alphanumeric (unicode), not ``_``, ``-`` or space.
_DROP = re.compile(r"[^\w\- ]", re.UNICODE)

# An ATX heading, with any trailing ``#`` closers removed.
_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*$")

# A fenced code block delimiter. A ``#`` inside a fence is a shell comment or a
# Python comment, not a heading -- counting it would invent anchors that GitHub
# never renders and, worse, would shift the ``-1``/``-2`` de-duplication suffix of
# every real heading after it.
_FENCE = re.compile(r"^\s*(?:```|~~~)")


def slugify(heading_text: str) -> str:
    """The anchor GitHub would generate for one heading's text.

    One space -> one hyphen, so a run of spaces left by removed punctuation yields a
    run of hyphens. See ``slug_variants`` for the spelling this module does not commit
    to, and the module docstring for why.
    """
    text = _MD_LINK.sub(r"\1", heading_text)
    text = _DROP.sub("", text).strip().lower()
    return text.replace(" ", "-")


def slug_variants(heading_text: str) -> set[str]:
    """Every spelling a link to this heading may legitimately use.

    Normally one. Two when punctuation removal left a run of spaces -- the
    one-hyphen-per-space form and the collapsed form -- because this tree cannot
    establish which one GitHub renders (module docstring). Accepting both keeps a
    rename detectable while refusing to invent 614 findings on an unverified premise.
    """
    exact = slugify(heading_text)
    collapsed = re.sub(r"-{2,}", "-", exact)
    return {s for s in (exact, collapsed) if s}


def heading_anchors(markdown: str) -> set[str]:
    """Every anchor a GitHub-rendered copy of this document would expose.

    De-duplication is positional, so headings are walked in document order and
    fenced blocks are skipped -- a stray ``# comment`` inside a fence would not just
    add a phantom anchor, it would consume the un-suffixed spelling and push the
    real heading to ``-1``.
    """
    seen: dict[str, int] = {}
    out: set[str] = set()
    fenced = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING.match(line)
        if not m:
            continue
        variants = slug_variants(m.group("text"))
        if not variants:
            continue
        # De-duplication is keyed on the canonical spelling so the ``-1``/``-2``
        # counter cannot be advanced twice by one heading that happens to emit two
        # variants -- the counter must track HEADINGS, not spellings.
        base = slugify(m.group("text"))
        n = seen.get(base, 0)
        seen[base] = n + 1
        for variant in variants:
            out.add(variant if n == 0 else f"{variant}-{n}")
    return out
