"""Single source of truth for the CHANGELOG.md structural regexes.

The release gate (``scripts/release_check.py``) and the documented-claims tests
both parse ``CHANGELOG.md`` for dated version headers and the ``[Unreleased]``
section body. This canon lives in ``espalier/`` (not ``scripts/``) because
``scripts/`` has no ``__init__`` and the engine may not import scripts — so the
importable owner both surfaces consume must live here.

**Why the substance helpers live here too.** The module owned the two *header*
regexes from the start, but the expression that actually drifted — "does this
section body carry content?" — was hand-rolled inline at every consumer as
``^###``. ``CHANGELOG.md`` has never contained an h3: it labels groups with
``**Bold**``. So the detector matched nothing, everywhere, while reporting
success. That blindness was fixed twice in ``tests/test_documented_claims.py``
and both times the sister site in ``scripts/release_check.py`` was missed
(``DEF-457`` / ``DEF-591``, the same defect filed twice as the line number
drifted). The lesson is not "fix the third site" — it is that a
single-source-of-truth module which owns only the easy half of a parse invites
exactly this. Content detection is canon here now; consumers must not re-roll it.
"""
from __future__ import annotations

import re

DATED_VERSION_RE = re.compile(
    r"^##\s*\[(?P<version>[^\]]+)\]\s*[—\-]\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.MULTILINE,
)
"""A dated release header — ``## [<version>] — YYYY-MM-DD``. Captures the
``version`` and ``date`` groups."""

UNRELEASED_BODY_RE = re.compile(
    r"##\s*\[Unreleased\](?P<body>.*?)(?=^##(?!#)|\Z)",
    re.DOTALL | re.MULTILINE,
)
"""The ``[Unreleased]`` section body (the ``body`` group), captured up to the
next h2 or end-of-file.

Shares :data:`SECTION_BOUNDARY_RE`'s rule rather than stopping only at
``^##\\s*\\[``. Under the bracket-only form, a plain ``## Migration guide``
inserted above the first dated section would be absorbed into this body —
inflating every count taken from it. Inert on the live file today (``[Unreleased]``
is followed by a bracket h2), which is exactly why it needed fixing before it
was not."""

CATEGORY_LABEL_RE = re.compile(r"^### (\w+)|^\*\*(\w+)[\w ]*\*\*\s*$")
"""A release-section category label, in EITHER shape this project has used.

``### Added`` is the Keep-a-Changelog shape; ``**Added**`` is the shape
``CHANGELOG.md`` has used since the style switch. The bold arm requires the
label to be the WHOLE line, so a bold lead-in inside a bullet (``**Why:** …``)
is not mistaken for a category. First word only, so a qualified label
("Breaking changes (pre-1.0)") still collides with its own kind.

Line-oriented — apply with ``.match()`` per line, not against a whole body.
"""

SECTION_BOUNDARY_RE = re.compile(r"^##(?!#)", re.MULTILINE)
"""Where any CHANGELOG section ends — the next h2, at ANY spacing.

Derived deliberately rather than spelled ``^## ``. ``DATED_VERSION_RE`` accepts
``^##\\s*\\[``, so ``##[0.2.0] — 2026-05-02`` is a valid dated header *per this
very module* — and a boundary requiring a literal space would not stop there,
letting an empty release section swallow the next one whole. That is not
hypothetical: it made :func:`has_content` return True for a section with
nothing in it, so the release gate passed on precisely the slip it exists to
catch. A boundary must never be narrower than the header pattern it bounds.

``(?!#)`` keeps h3/h4 out, so category subheadings do not end a section.
"""

_BULLET_RE = re.compile(r"^\s*[-*]\s+\S")
_SUBHEADING_RE = re.compile(r"^#{3,4}\s+\S")
_LINK_REF_RE = re.compile(r"^\[[^\]]+\]:\s*\S")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def category_label(line: str) -> str | None:
    """Return the category name on this line, in either shape, else ``None``."""
    m = CATEGORY_LABEL_RE.match(line)
    if not m:
        return None
    return m.group(1) or m.group(2)


def substantive_entries(body: str) -> list[str]:
    """Return the lines of a section body that carry a discrete changelog entry.

    An entry is a bullet, an h3/h4 subheading, or a bold category label —
    whichever shape the file happens to use. This is the "has work accumulated
    here?" question, and it is deliberately shape-agnostic: keying it on any
    single shape is the defect this module exists to prevent.

    NOTE this is narrower than :func:`has_content`. A section of pure prose
    has no *entries* but is very much not empty — which is exactly what
    ``CHANGELOG.md``'s dated sections look like, so the two questions must not
    be conflated.

    The count is of STRUCTURAL LINES, not of changes: a group label counts
    alongside the bullets beneath it, and a nested bullet counts as its own
    entry. Read it as a floor on structure. Callers that surface the number to
    a human should say "entries", not "changes".
    """
    return [
        line
        for line in body.splitlines()
        if _BULLET_RE.match(line)
        or _SUBHEADING_RE.match(line)
        or category_label(line) is not None
    ]


def has_content(body: str) -> bool:
    """True when a section body carries anything a reader would call content.

    Prose counts — ``CHANGELOG.md``'s dated sections are prose summaries with
    zero bullets, so an entry-only test would call a perfectly good release
    section empty. What does NOT count: blank lines, horizontal rules, and
    link-reference definitions (``[0.8.0a13]: https://…``), which are file
    furniture rather than release notes.

    ⚠ DELIBERATELY WEAK, and pinned as such by
    ``test_a_pointer_line_satisfies_has_content_by_design``: ONE non-furniture
    line is enough, so ``TBD`` or ``See [Unreleased].`` satisfies it. That is
    not an oversight — a defer-pointer is a legitimate mid-alpha section, and
    the live ``## [0.8.0a13]`` ends with exactly such a sentence. This answers
    "is the section empty", never "are the notes good". Substance stays a
    human judgement at the cut.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HORIZONTAL_RULE_RE.match(line):
            continue
        if _LINK_REF_RE.match(stripped):
            continue
        return True
    return False


def section_body(text: str, version: str) -> str | None:
    """Return the body of the dated section for ``version``, or ``None``.

    ``None`` means the version has no dated header at all — a distinct
    condition from "has a header but the body is empty", which returns ``""``
    (or whitespace) and is what :func:`has_content` is for.

    The section ends at :data:`SECTION_BOUNDARY_RE` — the next h2 of ANY shape
    and ANY spacing, not merely the next ``## [``. ``CHANGELOG.md`` carries a
    ``## Pre-0.8 alpha — …`` section that is a real boundary and matches no
    bracket form; stopping only at ``## [`` would swallow it, and the 30
    link-reference lines below it, into the preceding release's body — making
    an empty section look populated.

    NOT fence-aware: a ``##`` line inside a code fence terminates the section.
    That can only truncate a body, never extend one, so it cannot manufacture
    a false "has content" — but a consumer extracting release notes verbatim
    should know.
    """
    for match in DATED_VERSION_RE.finditer(text):
        if match.group("version") != version:
            continue
        rest = text[match.end():]
        next_header = SECTION_BOUNDARY_RE.search(rest)
        return rest[: next_header.start()] if next_header else rest
    return None
