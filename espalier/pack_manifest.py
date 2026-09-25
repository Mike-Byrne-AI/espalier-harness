"""Parse a task pack's Scope (in) and Affected symbols sections.

A task pack is a markdown file. This module extracts two structured
views authors maintain in prose, without forcing authors to write JSON:

1. **Scope (in)** — bullets between ``## Scope (in)`` and
   ``## Scope (out)``. Backticked path-shaped tokens are extracted as
   the files/directories the author claims the pack will touch.
2. **Affected symbols** — bullets under ``## Affected symbols``
   subsections (``### Removed paths`` / ``### Renamed symbols`` /
   ``### Changed semantics`` / ``### Added paths/symbols``). Each
   bullet's first backticked token is the symbol; the dash-separated
   tail is the human-readable description.

The parser is forgiving: missing sections return empty lists. Callers
treat absence as "scope-check cannot run on this pack yet" — emit a
hint pointing at ``docs/PACK_AUTHORING.md`` rather than erroring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


REMOVED_PATH = "removed_path"
RENAMED = "renamed"
CHANGED_SEMANTICS = "changed_semantics"
ADDED = "added"

# Route a ``### <header>`` Affected-symbols subsection by its FIRST word, so the
# author's spelling routes identically regardless of hyphen-vs-space, a short
# form, or a trailing annotation: ``### Added paths/symbols``, ``### Added-paths``,
# ``### Added``, and ``### Changed semantics — command count 14→15`` all route by
# their first word. Routing by first word (rather than exact canonical strings)
# accepts the hyphen forms ``### Changed-semantics`` / ``### Added-paths`` and
# tolerates annotated headers. Canonical spellings: "Added paths/symbols",
# "Changed semantics", "Renamed symbols", "Removed paths".
_CHANGE_TYPE_BY_FIRST_WORD: dict[str, str] = {
    "added": ADDED,
    "changed": CHANGED_SEMANTICS,
    "renamed": RENAMED,
    "removed": REMOVED_PATH,
    # "deleted" is the near-miss synonym a real pack used (`### Deleted-paths`),
    # whose whole subsection routed to nothing and was silently skipped. Found
    # by censusing every unrouted heading across the tree: of 35 such headings
    # this is the ONLY one that meant a change type rather than a deliberate
    # context section (`### Referenced authorities (read-only)` and friends).
    "deleted": REMOVED_PATH,
}


# NOTE: AffectedSymbol intentionally omits ``frozen=True`` — the
# scope-check CLI mutates ``classification`` after construction (see
# espalier/cli.py::cmd_scope_check). ``slots=True`` is also omitted
# because it interacts with the post-init field assignment.
@dataclass
class AffectedSymbol:
    """One symbol the pack proposes to touch."""

    name: str
    change_type: str
    description: str = ""
    classification: str | None = None  # surface-matrix status, filled by caller


# AffectedLiteral is fully determined at parse time — unlike AffectedSymbol
# (whose ``classification`` the scope-check CLI mutates post-construction), a
# literal's fields are set once at parse and never rewritten — so it takes the
# project's dataclass default of ``frozen=True, slots=True``. ``exclude_globs``
# is an immutable tuple for the same reason.
@dataclass(frozen=True, slots=True)
class AffectedLiteral:
    """One raw literal/token a pack proposes to change tree-wide.

    A literal is a string whose rename/edit blast radius the symbol-walk
    cannot see: a filename (``ESPALIER_MEMORY.md``), an env var, a config key. The
    optional ``exclude_globs`` name files where the token legitimately
    appears unchanged (a homonym twin), so scope-check can partition the
    hits into target / excluded / ambiguous.
    """

    token: str
    description: str = ""
    exclude_globs: tuple[str, ...] = ()


# NOTE: PackManifest holds the post-parse model and is intentionally
# mutable so callers can attach additional state (e.g. scope-check
# results) without a ``dataclasses.replace`` round-trip.
@dataclass
class PackManifest:
    pack_path: Path
    pack_id: str
    scope_in_files: list[str] = field(default_factory=list)
    affected_symbols: list[AffectedSymbol] = field(default_factory=list)
    affected_literals: list[AffectedLiteral] = field(default_factory=list)
    #: The ``## Affected symbols`` heading as the pack spells it, or ``None``
    #: when the section is absent -- what scope-check says it matched.
    affected_symbols_heading: str | None = None


def parse_pack(path: Path) -> PackManifest:
    """Parse a pack markdown file into a structured manifest."""
    # A non-UTF-8 pack must not traceback `espalier scope-check` with
    # UnicodeDecodeError. The pack body is markdown prose, so replacing
    # undecodable bytes with U+FFFD is harmless to the section/symbol parse.
    text = path.read_text(encoding="utf-8", errors="replace")
    return PackManifest(
        pack_path=path,
        pack_id=_extract_pack_id(path),
        scope_in_files=parse_scope_in(text),
        affected_symbols=parse_affected_symbols(text),
        affected_literals=parse_affected_literals(text),
        affected_symbols_heading=affected_symbols_heading(text),
    )


def _extract_pack_id(path: Path) -> str:
    """Pull the TP-NN identifier from the filename stem."""
    stem = path.stem
    m = re.match(r"^(TP-[A-Z0-9]+(?:-\d+)?)", stem)
    return m.group(1) if m else stem


# One heading-prefix idiom, four regex sites across three parser functions
# (parse_scope_in owns TWO — its section start AND its section terminator).
# Hand-duplicating it is what silently no-oped scope-check once: a widening
# applied to one site and not the others turns a governance pre-flight into a
# 0-result silent PASS, which reads as a clean bill of health. Derive, never
# re-type. `#{2,3}` = h2 or h3 anchored to line start (unanchored, re.search
# would match 3 of the 4 hashes in an `#### Scope (in)` h4 and mis-detect it);
# the optional `\d+\.\s+` admits the numbered headings real packs use.
# Pinned in lockstep by tests/test_pack_manifest.py::TestHeadingPrefixParity.
# NOT used by the `### <subsection>` scanner in parse_affected_symbols — that
# is a different idiom (exactly h3, no numbering) and must stay separate.
_HEADING_PREFIX = r"(?m)^#{2,3}\s+(?:\d+\.\s+)?"


def parse_scope_in(text: str) -> list[str]:
    """Return the list of file-shaped tokens from ``## Scope (in)`` bullets.

    Heuristic: backticked tokens that contain ``/`` or end with a
    known extension. The pack format uses these to declare the files
    the pack will edit; scope-check uses the same list to classify
    references as in-scope vs out-of-scope.

    A ``:NNN`` line-column suffix (pack authors sometimes write
    ``path/to/file.py:NNN``) is stripped so the bare path matches the
    file shape ``scope_walker`` reports — without this step the
    classifier mismatches and every line-anchored entry falsely
    surfaces as a scope gap.
    """
    # BOTH the start and the end heading use _HEADING_PREFIX (see its comment
    # for why the shape is what it is). The pairing is the load-bearing part:
    # if the end heading is numbered (`## 4. Scope (out)`) but its pattern is
    # not, the section never terminates and slurps downstream path tokens into
    # scope-in. That is why the terminator is one of the four sites the parity
    # test pins, despite having no parser of its own to drive.
    section = _section_body(
        text,
        _HEADING_PREFIX + r"Scope \(in\)",
        _HEADING_PREFIX + r"Scope \(out\)",
    )
    if section is None:
        return []
    paths: set[str] = set()
    # Scan bullets (`- `) AND markdown-table rows (`| ... |`): both declare
    # scope-in files. The backtick + _looks_like_path filter drops non-path
    # tokens and table separators (`|---|`). Like the original bullet scan this
    # is a HEURISTIC — a path mentioned in prose on a `-`/`|` line still counts;
    # that over-inclusion is conservative for a pre-flight signal (a falsely
    # in-scope path just isn't flagged as a gap, never the reverse).
    # Read each bullet's FULL logical text — a long list item that wraps onto a
    # continuation line (no leading `-`/`|`) still declares any path on the
    # wrapped line. Scanning only the `-`/`|` line dropped it, so a pack could
    # list a file and still see scope-check flag it as a false gap.
    for bullet in _logical_bullets(section):
        for tick in re.finditer(r"`([^`]+)`", bullet):
            candidate = tick.group(1).strip()
            if _looks_like_path(candidate):
                paths.add(_strip_line_suffix(candidate))
    return sorted(paths)


def _strip_line_suffix(token: str) -> str:
    """Drop a trailing ``:NNN`` / ``:NNN:CCC`` (line / line:col) suffix.

    Skips URL-scheme tokens so that ``http://localhost:8080`` (which a
    pack author might legitimately reference) is not mangled into
    ``http://localhost``. Deterministic peel — strips trailing
    ``:digits`` groups iteratively, avoiding the super-linear regex
    backtracking shape on adversarially-long inputs.
    """
    if token.startswith(("http://", "https://", "ftp://", "file://", "git://", "ssh://")):
        return token
    while True:
        head, sep, tail = token.rpartition(":")
        if sep and tail.isdigit() and head:
            token = head
            continue
        return token


# An ordered-list marker opening a line: ``1.``, ``10.``, ``3)``. The trailing
# ``\s`` is load-bearing — without it a dotted version at line start
# (``0.8.0b1 ...``) reads as list item ``0.`` and splits a wrapped bullet.
_ORDERED_ITEM = re.compile(r"\d+[.)]\s")


def _logical_bullets(section: str) -> list[str]:
    """Group a section's lines into logical bullets, joining wrapped
    continuation lines back onto the bullet they belong to.

    A bullet starts at a line whose first non-space char is ``-`` (a list
    item) or ``|`` (a markdown-table row), or which opens with an ORDERED
    list marker (``1.`` / ``10.`` / ``3)``). A following line that does NOT
    start a new bullet is a lazy continuation (Markdown wraps a long list
    item this way) and is joined with a space, so a backticked path that
    spilled onto the second visual line is still seen. A blank line ends
    the current bullet; prose lines before the first bullet are ignored.

    The ordered-list arm is the third instance of one class: a real pack
    section that this parser sees as containing no bullets at all, so
    :func:`parse_scope_in` returns ``[]``, every reference classifies as a
    scope gap, and the pre-flight's report carries no signal. The first two —
    numbered HEADINGS (``## 3. Scope (in)``) and markdown TABLE rows — were
    closed earlier; ordered list ITEMS were not, and three in-flight packs
    plus one already-landed pack were affected (see the regression test
    ``test_parses_numbered_list_items``).

    ``_ORDERED_ITEM`` requires whitespace after the ``.``/``)`` so a wrapped
    continuation line opening with a dotted version (``0.8.0b1 ships it``)
    is NOT mistaken for a new list item — that would orphan the text before
    it. Over-inclusion stays the safe direction for paths, but splitting a
    bullet loses the join, which is why this one guard is tightened.

    This is the primitive behind :func:`parse_scope_in`'s continuation
    robustness and :func:`parse_affected_literals`' multi-line ``EXCLUDE:``
    clause. Over-inclusion stays the safe direction (a falsely in-scope
    path is looked up and never flagged as a gap), so joining lazy
    continuations cannot manufacture a false gap.
    """
    bullets: list[str] = []
    current: str | None = None
    for line in section.splitlines():
        stripped = line.lstrip()
        if (
            stripped.startswith("-")
            or stripped.startswith("|")
            or _ORDERED_ITEM.match(stripped)
        ):
            if current is not None:
                bullets.append(current)
            current = line
        elif stripped == "":
            if current is not None:
                bullets.append(current)
                current = None
        elif current is not None:
            current += " " + line
    if current is not None:
        bullets.append(current)
    return bullets


def parse_affected_symbols(text: str) -> list[AffectedSymbol]:
    r"""Return the structured ``Affected symbols`` entries.

    Looks for ``## Affected symbols`` and walks each ``### <subsection>``
    block, routing it to a change_type by the header's FIRST word (so
    ``### Added paths/symbols``, ``### Added-paths``, and ``### Added`` are
    equivalent — see :data:`_CHANGE_TYPE_BY_FIRST_WORD`). Bullets like
    ``- `name` — description`` become :class:`AffectedSymbol` instances.
    """
    # Tolerate a numbered heading (``## 5. Affected symbols``) the same way
    # the Scope (in)/(out) parser does, so scope-check finds symbols on a
    # real (numbered) pack.
    section = _section_body(
        text, _HEADING_PREFIX + r"Affected symbols", r"^## "
    )
    if section is None:
        return []
    symbols: list[AffectedSymbol] = []
    # Walk every ``### <header>`` subsection in order; a subsection's body runs
    # to the next ``### `` (or the section end). Routing by the header's first
    # word (split on whitespace / ``/`` / ``-``) tolerates every documented
    # spelling without a per-string match. Unknown first words are skipped.
    subs = list(re.finditer(r"(?m)^###[ \t]+(?P<header>\S.*?)[ \t]*$", section))
    for i, m in enumerate(subs):
        first = re.split(r"[\s/-]", m.group("header").strip(), maxsplit=1)[0].lower()
        change_type = _CHANGE_TYPE_BY_FIRST_WORD.get(first)
        if change_type is None:
            continue
        body_end = subs[i + 1].start() if i + 1 < len(subs) else len(section)
        # Read the subsection with its `~~struck~~` spans removed BEFORE the
        # per-line scan: a struck token is the record of a declaration the
        # pack withdrew, walking it aimed the pre-flight at code the pack no
        # longer touches, and a strike that wraps onto a continuation line
        # only closes when the text is read whole (CONV-2).
        sub = _live_text(section[m.end():body_end])
        for bullet in re.finditer(r"^- .+$", sub, re.MULTILINE):
            line = bullet.group(0)
            # `- (none — `path` ...)` declares NOTHING: the path inside is the
            # author saying what was considered, not what changes. Twelve packs
            # use the spelling; it was harmless while no reader turned a first
            # token into a prescription, and false the day one did (a renamed
            # `docs/TASK_RECIPES.md` reported as the removal of a file that
            # exists -- DEF-410j). A parenthesised aside is the same.
            if _declares_nothing(line):
                continue
            # The DECLARATION is the first token outside any annotation. Read
            # from the whole line, `- something happened (see `README.md` for
            # details)` declared `README.md` and no diagnostic fired
            # (DEF-778); read from a plain head cut at the first opener, a
            # bullet that OPENS with a label -- `- (A2) `espalier
            # propose-rules` ...`, ten live packs -- declared nothing.
            declared = _declaration_token(line)
            if declared is None:
                continue
            name, after = declared
            # The spaced form of the same convention, `` `path` :: `symbol` ``
            # (optionally `:: local `symbol``), names the SYMBOL too: the first
            # token is the file it lives in. A live pack wrote it that way and
            # was read as renaming the whole file.
            spaced = _SPACED_PATH_SYMBOL_RE.match(line[after:])
            if spaced:
                name = spaced.group(1).strip()
            # A `path/to/file.py::symbol` token is the pack-author convention;
            # scope_walker.walk_references greps the bare symbol, so store the
            # part after `::` (the literal `path::symbol` token never appears in
            # source). Mirrors the freshness gate's rpartition idiom.
            _path, _sep, _symbol = name.rpartition("::")
            if _sep:
                name = _symbol.strip()
            desc = ""
            desc_m = re.search(r"`[^`]+`\s*[—\-]\s*(.+)", line)
            if desc_m:
                desc = desc_m.group(1).strip()
            symbols.append(AffectedSymbol(
                name=name,
                change_type=change_type,
                description=desc,
            ))
    return symbols


def affected_symbols_diagnostics(text: str) -> list[str]:
    """Report what :func:`parse_affected_symbols` DROPPED — which its return
    value structurally cannot.

    Two measured silent losses, and the second is the dangerous one:

    - A ``### <subsection>`` whose first word is not a known change type is
      skipped ENTIRELY (the ``_CHANGE_TYPE_BY_FIRST_WORD`` miss executes
      ``continue``). An all-unrecognized section parses to 0 and at least looks
      wrong; ONE recognized heading plus one unrecognized parses to a plausible
      NON-ZERO number and trips nothing at all. A wrong number is worse than a
      missing one — the reader sees "4 symbols" and never learns 6 were dropped.
    - A bullet declaring several backticked tokens contributes only its FIRST
      (``ticks[0]``); the rest vanish with no signal.

    Returns human-readable loss lines for scope-check to print. A count is not a
    success signal unless something independently pins the expected count, so
    the honest fix is to name the loss rather than to widen the routing table
    and hope the next unanticipated heading is covered.
    """
    section = _section_body(text, _HEADING_PREFIX + r"Affected symbols", r"^## ")
    if section is None:
        return []
    notes: list[str] = []
    subs = list(re.finditer(r"(?m)^###[ \t]+(?P<header>\S.*?)[ \t]*$", section))
    for i, m in enumerate(subs):
        header = m.group("header").strip()
        first = re.split(r"[\s/-]", header, maxsplit=1)[0].lower()
        if _CHANGE_TYPE_BY_FIRST_WORD.get(first) is None:
            # NOT reported. Measured across every pack in the tree when this
            # check was written: an unrouted subsection is a deliberate
            # authoring convention (`### Referenced authorities (read-only)`,
            # `### Docs`, `### Unmodified-on-purpose`, `### Walked, no change
            # required`), and the one pack whose "5 declared -> 1 parsed"
            # motivated this check parks its extras under `### Read-only (0-B
            # does NOT walk these)` ON PURPOSE. Skipping them is correct
            # behaviour; flagging them would be a false fire per such heading.
            # The single genuine near-miss found -- `### Deleted-paths` -- is
            # fixed at the routing table instead.
            continue
        body_end = subs[i + 1].start() if i + 1 < len(subs) else len(section)
        # The same live read the parser does: a bullet struck whole has
        # vanished by here (withdrawn for the record), so nothing reports it.
        sub = _live_text(section[m.end():body_end])
        for bullet in re.findall(r"^- .+$", sub, re.MULTILINE):
            if _declares_nothing(bullet):
                continue  # declares nothing; the parser skips it too.
            if _UNHANDLED_STRIKE_RE.search(bullet):
                notes.append(
                    f"bullet under '### {header}' uses a strike spelling the "
                    f"parser does not honour (<del> or STRUCK:), so it is still "
                    f"walked: {bullet.strip()[:80]!r} (strike with ~~...~~, or delete it)"
                )
                continue
            span = _declaration_span(bullet)
            if _RENAME_ARROW_RE.search(span):
                continue  # `old` -> `new`: taking the first token is correct.
            # The same rule the parser reads: tokens in the declaration span,
            # so a label-opening bullet (`- (A2) `a` `b``) counts BOTH its
            # tokens here, where a head cut at the first `(` counted none.
            ticks = [t for t, _ in _declaration_tokens(bullet)]
            if not _TICK_RE.search(bullet):
                # The guard the class asked for: a bullet under a ROUTED
                # sub-heading that names no backticked token is one the
                # parser silently dropped -- a path the author typed bare
                # (`- README.md / docs/CONVENTIONS.md — regenerated`, an
                # archived pack), or prose where a declaration belongs. The
                # walk cannot see it, so say so, quoting the bullet itself (a
                # head cut at its first parenthesis can be a lone dash); the
                # none spellings above are the way to declare nothing on
                # purpose.
                notes.append(
                    f"bullet under '### {header}' declares no backticked "
                    f"token, so the walk cannot see it: {bullet.strip()[:80]!r} "
                    f"(declare a `path::symbol`, or write `- (none -- ...)`)"
                )
                continue
            if not ticks:
                # DEF-778: every token sits inside an annotation -- a
                # parenthesised aside or a dash-tail -- so the parser (which
                # reads the same rule) declares nothing, and the author is
                # told rather than left with a silently empty walk.
                notes.append(
                    f"bullet under '### {header}' names its only backticked "
                    f"token(s) inside an annotation, so the walk cannot see "
                    f"it: {bullet.strip()[:80]!r} (put the declared "
                    f"`path::symbol` before the parenthesis or the dash)"
                )
                continue
            # Only a run of DECLARATION-SHAPED tokens is an unambiguous
            # multi-entry bullet. This filter is what separates a real dropped
            # path from a prose aside that happens to backtick a symbol name:
            # unfiltered it fired 113 times across the tree for ~1 true
            # positive. A bare `/`-or-`::` test was too strict in the other
            # direction -- it dropped the motivating case, whose continuation
            # tokens are bare filenames (`subagent_start.py`) -- so a file
            # extension counts too.
            if len(ticks) > 1 and all(_is_declaration_shaped(t) for t in ticks):
                notes.append(
                    f"bullet under '### {header}' declared {len(ticks)} "
                    f"declaration-shaped tokens but contributed 1 "
                    f"({ticks[0]!r}); dropped: {ticks[1:]}"
                )
    return notes


def affected_symbols_subsections(text: str) -> list[tuple[str, bool]]:
    """Every ``### <header>`` under ``## Affected symbols``, in order, paired
    with whether the pre-flight ROUTES it (its first word names a change type
    in ``_CHANGE_TYPE_BY_FIRST_WORD``).

    The parser skips an unrouted sub-heading on purpose -- most are deliberate
    context sections -- and the diagnostics stay quiet about them for the same
    reason. But when a pack parses to ZERO entries, the reader needs to know
    whether that is because its bullets are malformed or because every one of
    them sits under a heading nobody routes (``### Fixed``); until 2026-09-11
    scope-check called the second case malformed bullets and sent an author who
    had followed the format back to the format (DEF-430). Returns ``[]`` when
    the section is absent.
    """
    section = _section_body(text, _HEADING_PREFIX + r"Affected symbols", r"^## ")
    if section is None:
        return []
    out: list[tuple[str, bool]] = []
    for m in re.finditer(r"(?m)^###[ \t]+(?P<header>\S.*?)[ \t]*$", section):
        header = m.group("header").strip()
        first = re.split(r"[\s/-]", header, maxsplit=1)[0].lower()
        out.append((header, _CHANGE_TYPE_BY_FIRST_WORD.get(first) is not None))
    return out


def affected_symbols_heading(text: str) -> str | None:
    """The ``## Affected symbols`` heading line as the pack spells it
    (``## 5. Affected symbols``, ``### Affected symbols``), or ``None``.

    What scope-check reports it matched, instead of a hard-coded name: the
    numbered and h3 spellings parse (``_HEADING_PREFIX``), so the line the
    reader is told about should be the line in their pack.
    """
    # The same start pattern ``_section_body`` accepts, extended to the end of
    # its line, so the heading reported is exactly the heading parsed. Its
    # whitespace is collapsed: the prefix's ``\s+`` spans a newline, and the
    # string reaches a print.
    m = re.search(_HEADING_PREFIX + r"Affected symbols[^\n]*", text)
    return " ".join(m.group(0).split()) if m else None


def affected_symbols_withdrawn(text: str) -> list[str]:
    """The backticked tokens struck out under the routed sub-headings of
    ``## Affected symbols``: what a strike withdrew, in order.

    So scope-check can say that a strike REGISTERED instead of leaving the
    reader to infer it from a count -- the mechanical signal the 2026-08-01
    strike fork asked for, which the fix that honours ``~~`` would otherwise
    have left indistinguishable from a strike the parser did not see.
    """
    section = _section_body(text, _HEADING_PREFIX + r"Affected symbols", r"^## ")
    if section is None:
        return []
    withdrawn: list[str] = []
    subs = list(re.finditer(r"(?m)^###[ \t]+(?P<header>\S.*?)[ \t]*$", section))
    for i, m in enumerate(subs):
        first = re.split(r"[\s/-]", m.group("header").strip(), maxsplit=1)[0].lower()
        if _CHANGE_TYPE_BY_FIRST_WORD.get(first) is None:
            continue
        body_end = subs[i + 1].start() if i + 1 < len(subs) else len(section)
        for struck in _STRUCK_RE.finditer(section[m.end():body_end]):
            ticks = re.findall(r"`([^`]+)`", struck.group(0))
            if ticks:
                withdrawn.append(ticks[0].strip())
    return withdrawn


def affected_symbols_all_declare_nothing(text: str) -> bool:
    """True when the routed sub-headings hold at least one bullet and every
    one of them declares nothing on purpose (a none spelling or a
    parenthesised aside).

    The pack has nothing to walk and said so, which is not the same as
    bullets that failed the format: DEF-430's fifth cause, made common the
    day the none rule learned the bare spellings, when the format message
    started telling the author of ``- none. The event is observational`` to
    fix bullets that were right.
    """
    section = _section_body(text, _HEADING_PREFIX + r"Affected symbols", r"^## ")
    if section is None:
        return False
    seen = False
    subs = list(re.finditer(r"(?m)^###[ \t]+(?P<header>\S.*?)[ \t]*$", section))
    for i, m in enumerate(subs):
        first = re.split(r"[\s/-]", m.group("header").strip(), maxsplit=1)[0].lower()
        if _CHANGE_TYPE_BY_FIRST_WORD.get(first) is None:
            continue
        body_end = subs[i + 1].start() if i + 1 < len(subs) else len(section)
        for bullet in re.findall(
            r"^- .+$", _live_text(section[m.end():body_end]), re.MULTILINE
        ):
            seen = True
            if not _declares_nothing(bullet):
                return False
    return seen


# Annotations -- a parenthesised aside, or everything after a dash-tail -- are
# PROSE about the entry, not further declarations. `_declaration_span` below
# is the one reader of that rule (DEF-778): the parser and the diagnostics
# both read tokens from it. Calibrated against the live population: counting
# ticks across the whole bullet fired 11 times on one real pack with ONE true
# positive, because packs routinely backtick symbols inside an explanatory
# aside; a head cut at the first `(` (the previous reader) dropped the ten
# bullets that OPEN with a label.

# `- `old` → `new`` / `- `old` -> `new``. Two tokens by design; the parser
# keeping the FIRST is the documented rename convention, not a drop.
_RENAME_ARROW_RE = re.compile(r"(?:→|->|⇒|=>)")

# A bullet that declares nothing: `- (none ...)`, `- *(none — ...)*`,
# `- _(none)_`, and the bare spellings the archive uses -- `- None.`,
# `- _None._`, `- None to production code`, `- (No new files ...)`. Skipped by
# the parser and its diagnostics alike; a backticked path inside it is what
# the author considered, not what the pack changes. Measured 2026-09-11 over
# every pack under task-packs/ (262): eleven routed bullets were
# none-declarations in a spelling the paren-only rule did not read (nine
# archived, one deferred, one active), and three of them had parsed as a
# symbol. Only `none` is accepted bare; `no` must be followed by `new`,
# because a sentence that merely opens with "No" is a declaration
# (`- No longer generated: `x.py``, `- No-op wrapper `a.py::f` removed`), and
# the review that widened this rule to bare `no` watched it swallow both with
# the diagnostic silenced too.
_NONE_BULLET_RE = re.compile(r"^-\s*[*_(]*\s*(?:none\b|no new\b)", re.IGNORECASE)

# A bullet that is one parenthesised aside -- `- (test functions only, see
# Files touched)`, `- *(2-A adds no symbol -- reuses `x.y`)*` -- declares
# nothing either. Three routed bullets in the archive have this shape, and the
# one carrying a backtick had parsed as a declaration of the symbol it said it
# reuses. Emphasis marks around the parentheses are tolerated; the whole
# bullet must be the aside.
_ASIDE_BULLET_RE = re.compile(r"^-\s*[*_]*\(.*\)[*_.]*\s*$", re.DOTALL)

# A `~~struck~~` span is dead text: the record of what a pack once declared,
# kept for the reader and invisible to the walk. Both parsers and the
# diagnostics remove the struck spans from a SECTION before they look for
# bullets, so a bullet struck whole vanishes -- including a strike that wraps
# onto a continuation line, which closes across the newline and which a
# per-line read cannot see -- and a struck span inside a live bullet is
# ignored. A strike never crosses a blank line or the start of another
# bullet, so a stray `~~` in one bullet's prose cannot pair with a strike
# further down and eat the text between. (CONV-2: two archived packs carried
# struck symbols the pre-flight still walked, and the sharp edge that
# documented it told authors only deletion works; since 2026-09-11 a strike
# is honoured.)
_STRUCK_RE = re.compile(r"~~(?:(?!\n[ \t]*\n)(?!\n- ).)*?~~", re.DOTALL)

# Strike spellings the parser does NOT honour, named by the diagnostics so an
# author learns it there rather than from a blast radius that never shrank.
_UNHANDLED_STRIKE_RE = re.compile(r"<del>|^-\s*STRUCK:", re.IGNORECASE)


def _live_text(text: str) -> str:
    """``text`` with every ``~~struck~~`` span removed."""
    return _STRUCK_RE.sub("", text)


def _declares_nothing(bullet: str) -> bool:
    """A none-declaration or a parenthesised aside: skipped by the parser,
    reported by nothing."""
    return bool(_NONE_BULLET_RE.match(bullet) or _ASIDE_BULLET_RE.match(bullet))

# The spaced spelling of `path::symbol`: the text right after the first
# backticked token is ` :: `, optionally a one-word qualifier (`local`), then
# the symbol in backticks. Anchored at the start of that remainder.
_SPACED_PATH_SYMBOL_RE = re.compile(r"\s*::\s*(?:\w+\s+)?`([^`]+)`")

# A trailing `.ext` (1-5 chars) reads as a filename. Bounded deliberately so a
# sentence-ending prose token cannot qualify, and checked only on tokens that
# already survived the annotation peel.
_FILE_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def _is_declaration_shaped(token: str) -> bool:
    """True if ``token`` reads as a declared path/symbol rather than prose."""
    return "/" in token or "::" in token or bool(_FILE_EXT_RE.search(token))


_TICK_RE = re.compile(r"`([^`]+)`")
_DASH_TAIL_OPENERS = (" — ", " -- ")


def _declaration_span(bullet: str) -> str:
    """``bullet`` with every parenthesised aside blanked and cut at the first
    dash-tail OUTSIDE one -- the text a declaration can live in.

    Blanked, not removed, so an offset into the span is an offset into the
    bullet. A parenthetical that closes is a label or an aside either way;
    the dash rule applies only at depth zero, because a dash inside a closed
    label (``- Rows kept, open (verified unbuilt — must NOT be struck):
    `first-row` ...``, a live pack's shape) is part of the label, not a
    tail. Inside a backticked token nothing is prose: `` `check()` ``, `` `setting(s)` ``
    and a regex literal keep their parentheses and dashes (measured: a first
    cut that read them as openers changed five symbol tokens and five
    literal tokens across the packs, every one a token with a paren in it).
    """
    out: list[str] = []
    depth = 0
    in_tick = False
    i = 0
    while i < len(bullet):
        ch = bullet[i]
        if depth == 0 and not in_tick and any(
            bullet.startswith(op, i) for op in _DASH_TAIL_OPENERS
        ):
            break
        if ch == "`" and depth == 0:
            in_tick = not in_tick
            out.append(ch)
        elif ch == "(" and not in_tick:
            depth += 1
            out.append(" ")
        elif ch == ")" and not in_tick and depth > 0:
            depth -= 1
            out.append(" ")
        else:
            out.append(ch if depth == 0 else " ")
        i += 1
    return "".join(out)


def _declaration_tokens(bullet: str) -> list[tuple[str, int]]:
    """Every backticked token in the declaration span, each with the bullet
    offset just past it. The parser reads the first; the diagnostics read
    the rest -- one rule, both readers."""
    return [(m.group(1).strip(), m.end()) for m in _TICK_RE.finditer(_declaration_span(bullet))]


def _declaration_token(bullet: str) -> tuple[str, int] | None:
    """The first backticked token that is a DECLARATION, with the offset just
    past it -- or None when every token sits inside an annotation.

    A token is inside an annotation when a parenthesis opened before it is
    still open at it (``(see `README.md` for details)``), or when a
    dash-tail opener at depth zero precedes it (``- prose — see `x.py```):
    both are the author explaining, not declaring. A parenthetical that
    CLOSES before the token is a label, not an annotation -- ``- (A2)
    `espalier propose-rules` ...`` declares the command, and ten live packs
    write that shape -- so a token after it is read normally. Measured over
    1,214 routed bullets (2026-09-12): every label-shaped bullet keeps its
    declaration, and the three that change are ones whose only token was
    parenthesised prose.

    Scope: the ``Affected symbols`` and ``Affected literals`` bullet
    grammars. A struck token (``withdrawn_symbol_tokens``) is read from the
    strike span itself, where an annotation cannot occur.
    """
    tokens = _declaration_tokens(bullet)
    return tokens[0] if tokens else None


def parse_affected_literals(text: str) -> list[AffectedLiteral]:
    r"""Return the declared ``## Affected literals`` entries.

    A literal is a raw string/token whose rename/edit blast radius the
    symbol-walk cannot see (a filename, an env var, a config key). Each
    bullet's first backticked token is the literal; the dash-tail (before any
    ``EXCLUDE:``) is its description; an optional ``EXCLUDE:`` clause
    (comma-separated globs, on the bullet or a wrapped continuation line)
    lists files where the token legitimately appears unchanged — a homonym
    twin — so scope-check can partition hits into target / excluded /
    ambiguous.

    Absent section → empty list (the same forgiving contract as the symbol
    parser). Tolerates a numbered heading (``## 6. Affected literals``) and
    stops at the next ``## `` header.
    """
    section = _section_body(
        text, _HEADING_PREFIX + r"Affected literals", r"^## "
    )
    if section is None:
        return []
    literals: list[AffectedLiteral] = []
    # A struck literal is withdrawn, the same as a struck symbol (CONV-2); the
    # section is read whole so a strike that wraps closes across the newline.
    for bullet in _logical_bullets(_live_text(section)):
        # Peel the EXCLUDE: clause off FIRST, then read the token/description
        # from the head (the text before it). Reading the token from the whole
        # bullet would let a backtick-quoted EXCLUDE glob shadow the real literal
        # (``ticks[0]`` would bind the glob), so scope-check would silently walk
        # the WRONG token and report a clean literal arm — the exact false
        # reassurance this arm exists to prevent. Globs after EXCLUDE are
        # comma-separated (backticks and surrounding whitespace tolerated).
        exclude_globs: tuple[str, ...] = ()
        head = bullet
        excl_m = re.search(r"EXCLUDE:\s*(.+)", bullet)
        if excl_m:
            exclude_globs = tuple(
                g.strip().strip("`")
                for g in excl_m.group(1).split(",")
                if g.strip().strip("`")
            )
            head = bullet[: excl_m.start()]
        # The same declaration rule the symbols parser reads (DEF-778): the
        # first token outside an annotation, so `- prose (see `x`)` declares
        # nothing here too and an author learns one grammar for both sections.
        declared = _declaration_token(head)
        if declared is None:
            continue
        token = declared[0]
        desc = ""
        desc_m = re.search(r"`[^`]+`\s*[—\-]\s*(.+)", head)
        if desc_m:
            desc = desc_m.group(1).strip()
        literals.append(AffectedLiteral(
            token=token,
            description=desc,
            exclude_globs=exclude_globs,
        ))
    return literals


def _section_body(
    text: str, start_pattern: str, end_pattern: str
) -> str | None:
    """Return the body between a ``start_pattern`` header and the next
    ``end_pattern`` (or end of text).

    ``end_pattern`` is anchored with ``^`` via MULTILINE; pass a literal
    string with a leading ``^`` if you want strict line-start matching.
    """
    m = re.search(start_pattern, text)
    if not m:
        return None
    rest = text[m.end():]
    end_m = re.search(end_pattern, rest, re.MULTILINE)
    return rest[: end_m.start()] if end_m else rest


def _looks_like_path(token: str) -> bool:
    """Heuristic: does this backticked token look like a file/path?

    Over-inclusion is safe here by contract: a falsely in-scope path is just
    looked up and never flagged as a gap, whereas DROPPING a real path is the
    cardinal sin — it mis-reports every reference under it as out-of-scope. So
    the ``/`` branch accepts any slash-bearing token (with no internal
    whitespace) as a path, EXCEPT a pure numeric ratio (``14/15`` / ``1/2``),
    which is never a path. This admits bare directory paths in their common
    no-trailing-slash shape (``tools/cc/hooks``, ``src/components``) — the case
    a prior extension-or-dot shape-gate wrongly dropped — and accepts
    slash-joined word pairs (``and/or`` / ``read/write``) as harmless in-scope
    entries (they get looked up, find nothing, and are never flagged as a gap).

    A leading-dot config dotfile (``.flake8``, ``.gitignore``, ``.editorconfig``)
    and the ``.cfg`` / ``.ini`` config extensions are recognized too — dropping
    them contradicted the cardinal-sin rule above. The dotfile branch is PRECISE
    on purpose: the remainder after the dot must read like a filename, so a prose
    method-call token (``.strip()``, ``.get(x)``) is NOT admitted. That precision
    matters because ``espalier.verify_landing`` shares this heuristic to extract
    landing-claim paths, and there an unresolvable false path claim manufactures a
    fake OWED blocker — the safe-over-inclusion contract does not hold in that
    caller, so the recognizer must not over-admit prose.
    """
    # Purpose-scoped sibling of scope_walker.INCLUDED_EXTS / surface_impact._PATH_SUFFIXES /
    # proofs.TEXT_SUFFIXES — same idea, token-recognizer form; not a collapse candidate.
    for ext in (".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt",
                ".cfg", ".ini"):
        if token.endswith(ext):
            return True
    if "/" in token:
        if any(c.isspace() for c in token):
            return False
        if token.endswith("/"):
            return True
        segments = [seg for seg in token.split("/") if seg]
        # A pure numeric ratio (`14/15`, `1/2/3`) is prose, never a path. Every
        # other slash shape is admitted (over-inclusion is the safe direction).
        if segments and all(seg.isdigit() for seg in segments):
            return False
        return True
    if re.fullmatch(r"\.[A-Za-z0-9][A-Za-z0-9._-]*", token):
        return True
    return False
