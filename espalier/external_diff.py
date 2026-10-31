"""Pin drift: do the upstream sentences a pin quotes still stand?

A pin is a curated excerpt -- upstream's sentences quoted as Markdown
blockquote (`>`) lines, and espalier's own prose around them -- so diffing
the whole pin body against the whole fetched page reported high drift on
every refresh whether or not a quoted sentence moved (DEF-744). Drift is
instead read off the quotes: every `>` passage, split at its elisions and
paragraph breaks, must appear in the fetched page (or in one of the pin's
`quote_sources`) once both sides pass through the one normalisation below.

- `none`: every quoted passage was found upstream.
- `semantic`: one or more were not; the report names each by pin line.
- `unverifiable`: the pin quotes nothing long enough to check.
- `fetch_error`: a page could not be fetched, came back empty, or came back
  as HTML rather than the Markdown twin the pin names.

What the check cannot see: text upstream adds AROUND a quote that still
stands (a new sentence after it, a clause before it). Each fragment is
matched at word boundaries, a paragraph keeps its closing punctuation, and a
table row keeps its cell bars, so a clause added inside a quoted sentence or
before its period, and a row that only a longer name's row would contain,
are caught; an addition beside the quote is not drift by this measure.

`write_candidate` writes to `<pin>.candidate.md` and never overwrites
the original pin — auto-apply is the failure mode this whole TP exists
to prevent.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from espalier._atomic_io import atomic_write_text
from espalier.external_fetch import FetchResult
from espalier.external_pins import ExternalPin, _frontmatter_block

DRIFT_NONE = "none"
DRIFT_SEMANTIC = "semantic"
DRIFT_UNVERIFIABLE = "unverifiable"
DRIFT_FETCH_ERROR = "fetch_error"

#: A fragment with fewer letters and digits than this, once normalised, is too
#: short to judge (it would match by chance, and a table's alignment row has
#: none). It is counted, and the summary says how many were skipped.
MIN_FRAGMENT_CHARS = 12


@dataclass(frozen=True)
class DriftReport:
    pin_path: Path
    source_url: str
    drift_kind: str
    #: For `semantic`, the moved passages, one per line (`<pin>:<line>: text`);
    #: the name is kept from the whole-body diff it replaced.
    unified_diff: str
    summary: str
    candidate_path: Path | None


@dataclass(frozen=True)
class QuotedPassage:
    """One `>` blockquote of a pin: the 1-based file line it starts on, its
    text, the fragments (paragraphs, table rows, and the runs between
    elisions) each of which must be found upstream, and how many of its
    fragments were too short to judge."""

    line: int
    text: str
    fragments: tuple[str, ...]
    too_short: int = 0


# One pass per rule, each a single linear scan: no two adjacent quantifiers
# can match the same characters (the ReDoS rule). The characters the patterns
# and the fold table name are built with chr(), so an invisible one (the
# no-break space) is spelled out rather than pasted.
_ELLIPSIS = chr(0x2026)
# [text](target) -> text. Each class stops at the bracket that opens the next
# attempt: a text class admitting `[` (or a target class admitting `(`)
# swallows a run of them at every start and fails on the missing closer,
# which is quadratic (driven: 47 s on 20,000 `[`, 29 s on 37,500 `[x](`).
_LINK = re.compile(r"\[([^\[\]\n]*)\]\([^()\s]*\)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>\n]{0,200}>")    # <Warning>, </Note>, <br>
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+.!|-])")       # \_ -> _
_ELISION = re.compile(r"\[(?:" + _ELLIPSIS + r"|\.\.\.)\]|" + _ELLIPSIS + r"|\.\.\.")
_INLINE_COMMENT = re.compile(r"<!--.*?-->")
# A line's blockquote markers, nested ones included: a callout's `>` is the
# page's markup as the pin's own `>` is the pin's (DEF-3020). Each repeat ends
# at a `>`, so the two runs of spaces never meet.
_QUOTE_MARK = re.compile(r"^[ \t]*>(?:[ \t]*>)*", re.MULTILINE)
_UNICODE = str.maketrans({
    chr(0x2014): " -- ", chr(0x2013): "-", chr(0x2018): "'", chr(0x2019): "'",
    chr(0x201C): '"', chr(0x201D): '"', chr(0x2192): "->", chr(0x00A0): " ",
})


def normalize_quote_text(text: str) -> str:
    """The one normalisation a pin's quote and the fetched page both pass
    through, so a match never depends on which side was formatted how:
    a line's blockquote markers go (a callout's `> [!NOTE]` lines read as one
    paragraph; a `>` inside a line stays text); a link keeps its text and
    loses its target (parsed apart, so a `<` in the text does not matter);
    HTML-ish tags (`<Warning>`) go; Markdown escapes, emphasis and code ticks
    go; a table's cell bars and an em dash both become ` -- `, so a pin that
    flattens a table row into "name — text" matches the row; typographic
    quotes and dashes fold to ASCII; whitespace collapses; case folds."""
    t = text.translate(_UNICODE)
    t = _QUOTE_MARK.sub(" ", t)
    t = _LINK.sub(r"\1", t)
    t = _HTML_TAG.sub(" ", t)
    t = _ESCAPE.sub(r"\1", t)
    t = t.replace("*", "").replace("`", "").replace("|", " -- ")
    # Whitespace first, so each side of a `--` holds at most one space and the
    # run below has no two adjacent quantifiers over the same characters.
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(?: ?-- ?)+", " -- ", t)
    return t.strip().lower()


def _judgeable(fragment: str) -> bool:
    return sum(c.isalnum() for c in fragment) >= MIN_FRAGMENT_CHARS


def _paragraph_fragments(paragraph: str) -> list[str]:
    """A prose paragraph split at its elisions. Punctuation is trimmed only
    where an elision cut, so the paragraph's own closing punctuation stays
    and a clause upstream adds before its period is drift."""
    pieces = _ELISION.split(paragraph)
    out = []
    for i, piece in enumerate(pieces):
        f = normalize_quote_text(piece)
        if i > 0:
            f = f.lstrip(" .,;:-")
        if i < len(pieces) - 1:
            f = f.rstrip(" .,;:-")
        out.append(f)
    return out


def quoted_passages(pin: ExternalPin) -> list[QuotedPassage]:
    """Every `>` blockquote in the pin body, outside fenced code and HTML
    comments. A line loses every marker (`> >` included, as the page's lines
    do); a bare `>` line, or a comment, breaks a passage; a `> |` table
    row stands alone (a pin may quote two rows that are not adjacent on the
    page) and keeps its cell bars; an elision (`[…]`, `…`, `...`) breaks a
    paragraph into fragments. Every `>` line in a pin is read as an upstream
    quote -- the convention docs/external/README.md states."""
    out: list[QuotedPassage] = []
    fence: str | None = None
    comment = False
    start = 0
    paragraphs: list[list[str]] = []
    rows: list[str] = []

    def close() -> None:
        texts = [" ".join(p) for p in paragraphs if p]
        if texts or rows:
            frags = [f for para in texts for f in _paragraph_fragments(para)]
            frags += [normalize_quote_text(r) for r in rows]
            kept = tuple(f for f in frags if _judgeable(f))
            out.append(QuotedPassage(line=start, text=" ".join([*texts, *rows]),
                                     fragments=kept, too_short=len(frags) - len(kept)))
        paragraphs.clear()
        rows.clear()

    for n, line in enumerate(pin.body.splitlines(), pin.body_line):
        stripped = line.lstrip()
        # A fence first: inside one, `<!--` and `>` are the fence's text.
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if comment:
            comment = "-->" not in line
            continue
        if stripped.startswith(("```", "~~~")):
            close()
            fence = stripped[:3]
            continue
        if stripped.startswith("<!--"):
            close()
            comment = "-->" not in stripped
            continue
        if stripped.startswith(">"):
            content = _INLINE_COMMENT.sub(" ", _QUOTE_MARK.sub("", stripped)).strip()
            if not paragraphs and not rows:
                start, paragraphs[:] = n, [[]]
            if content.startswith("|"):
                rows.append(content)
                paragraphs.append([])
            elif content:
                paragraphs[-1].append(content)
            elif paragraphs[-1]:
                paragraphs.append([])
        elif paragraphs or rows:
            close()
    close()
    return out


def _found(fragment: str, page: str) -> bool:
    """``fragment`` occurs in ``page`` at word boundaries: neither the
    character before it nor the one after is a letter or digit, so a `Stop`
    row is not satisfied by a `SubagentStop` row, nor `the hook` by `the
    hooks`."""
    i = page.find(fragment)
    while i >= 0:
        before = page[i - 1] if i > 0 else " "
        end = i + len(fragment)
        after = page[end] if end < len(page) else " "
        if not before.isalnum() and not after.isalnum():
            return True
        i = page.find(fragment, i + 1)
    return False


def missing_passages(passages: Sequence[QuotedPassage], pages: Sequence[str]) -> list[QuotedPassage]:
    """The passages with a fragment found on none of ``pages``."""
    normalized = [normalize_quote_text(p) for p in pages]
    return [q for q in passages if any(not any(_found(f, page) for page in normalized) for f in q.fragments)]


def _unusable(page: FetchResult) -> str | None:
    """Why a fetched page cannot be read for quotes, or None: a failed fetch,
    an empty body, or HTML where the pin names a Markdown twin (every quote
    would read as moved, and the candidate would be the rendered page)."""
    if page.error is not None or not page.ok:
        return f"fetch failed: {page.url}: {page.error}"
    head = page.content.lstrip()[:200].lower()
    if not head:
        return f"fetch returned an empty page: {page.url}"
    if head.startswith(("<!doctype", "<html")):
        return f"fetch returned HTML, not Markdown: {page.url} (is the .md suffix still served?)"
    return None


def compare_pin_to_fetched(
    pin: ExternalPin, fetched: FetchResult, *, others: Sequence[FetchResult] = (),
) -> DriftReport:
    """Read the pin's drift off its quotes: every `>` passage against the
    fetched source page and the pin's other ``quote_sources`` (``others``)."""
    problems = [p for p in (_unusable(f) for f in (fetched, *others)) if p]
    if problems:
        return DriftReport(
            pin_path=pin.path,
            source_url=pin.source_url,
            drift_kind=DRIFT_FETCH_ERROR,
            unified_diff="",
            summary="; ".join(problems),
            candidate_path=None,
        )

    every = quoted_passages(pin)
    passages = [q for q in every if q.fragments]
    too_short = sum(q.too_short for q in every)
    skipped = f"; {too_short} quoted fragments too short to check" if too_short else ""
    if not passages:
        return DriftReport(
            pin_path=pin.path,
            source_url=pin.source_url,
            drift_kind=DRIFT_UNVERIFIABLE,
            unified_diff="",
            summary=f"the pin quotes no upstream passage long enough to check{skipped}",
            candidate_path=None,
        )
    missing = missing_passages(passages, [fetched.content, *(o.content for o in others)])
    if not missing:
        return DriftReport(
            pin_path=pin.path,
            source_url=pin.source_url,
            drift_kind=DRIFT_NONE,
            unified_diff="",
            summary=f"all {len(passages)} quoted passages found upstream{skipped}",
            candidate_path=None,
        )
    listing = "\n".join(f"{pin.path.name}:{q.line}: {q.text[:300]}" for q in missing)
    return DriftReport(
        pin_path=pin.path,
        source_url=pin.source_url,
        drift_kind=DRIFT_SEMANTIC,
        unified_diff=listing,
        summary=(
            f"{len(missing)} of {len(passages)} quoted passages not found upstream "
            f"(lines {', '.join(str(q.line) for q in missing)}){skipped}"
        ),
        candidate_path=None,
    )


def write_candidate(pin: ExternalPin, fetched_content: str) -> Path:
    """Write fetched content to `<pin>.candidate.md` next to the pin.

    The candidate is the fetched page under a copy of the pin's frontmatter,
    kept so the moved passages can be re-excerpted from it by hand. It is the
    raw page, not an excerpt, so it is never renamed over the pin.

    Never overwrites the original pin.
    """
    candidate_path = pin.path.with_name(f"{pin.path.stem}.candidate.md")
    # The frontmatter bytes are taken verbatim from the source pin so we don't
    # have to round-trip through the parser (which discards comments and
    # reorders keys).
    original = pin.path.read_text(encoding="utf-8")
    # Re-extract the literal frontmatter block (both delimiters) via the shared
    # writers' helper; this site keeps its own no-frontmatter guard + message.
    if not original.startswith("---\n"):
        raise ValueError(f"pin {pin.path} has no frontmatter — cannot write candidate")
    frontmatter_block = _frontmatter_block(
        original, malformed_msg=f"pin {pin.path} has malformed frontmatter"
    )
    candidate_text = frontmatter_block + "\n\n" + fetched_content
    atomic_write_text(candidate_path, candidate_text)
    return candidate_path
