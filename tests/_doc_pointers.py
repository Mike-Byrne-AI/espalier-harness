"""Cross-document pointer derivation, shared by the deploy-tree gates.

Three FORMS reach a reader as "go look at that":

1. a markdown link -- ``[text](docs/FOO.md)``, optionally ``#anchored``;
2. a bare-prose path -- ``see `docs/FOO.md` for the list``;
3. a quoted-section citation -- ``docs/FOO.md "Some Heading"``.

Form 1 is NOT re-implemented here. ``_artifact_links.iter_relative_links``
already owns it (fence stripping, ``<placeholder>`` rejection, citer-relative
plus repo-root candidates, and the ``#fragment`` returned rather than
discarded), and the repo already carries six spellings of that regex -- a
seventh would be the rival this module exists to avoid.

Forms 2 and 3 are derived here because nothing owns them against a deploy
tree. Form 3 in particular exists in the suite exactly once
(``test_denial_reasons._CLAUDE_MD_SECTION_CITATION``) with the filename
hard-coded to ``CLAUDE.md``; ``section_citations`` is that matcher with the
filename generalized, and that module now specializes this one rather than
keeping a second spelling.

**Why the section matcher accepts only double quotes.** The CLAUDE.md-only
ancestor accepted ``'`` too, which was safe while the filename was fixed --
almost nothing writes ``CLAUDE.md's``. Generalized across every ``*.md``
name it is not safe: ``` `cc/GOAL.md`s owed-list ``` reads the possessive
apostrophe as an opening quote and derives a section named
``s owed-list and any``. Measured on the live deploy set, that one spelling
produced three phantom pointers. A possessive is common; a single-quoted
section title is not, so the narrowing costs less than it saves. Typographic
``"`` / ``"`` ARE accepted -- prose in this repo uses them.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from _artifact_links import strip_fenced_blocks

# Illustrative spellings that are not real names. Same rule `_artifact_links`
# applies to link targets; shared here so both arms agree on what a
# placeholder is.
PLACEHOLDER_RE = re.compile(r"[<>]")

# A markdown filename, optionally path-qualified, optionally backticked.
_MD_NAME = r"(?:[\w.-]+/)*[\w.-]+\.md"

# The extension-less shorthand a doc uses for a sibling it names constantly:
# `SHARP_EDGES section "..."`. Deliberately narrow -- all-caps, three or more
# characters -- and only ever honoured when the literal word `section` follows,
# because a bare CAPS token on its own is far too common in this corpus to
# treat as a file reference.
_CAPS_DOC = r"[A-Z][A-Z0-9_]{2,}"

# A quoted heading. ONE soft wrap is allowed, because a citation that breaks
# across a line is the same citation -- but a blank line ends it, so an
# unbalanced quote cannot swallow a paragraph and invent a 400-character
# "heading".
_SECTION = r'["“](?P<section>[^"”\n]{2,120}(?:\n[ \t]*[^"”\n]{1,80})?)["”]'

# THREE spellings, not one. The single-pattern form below (3a) was the whole
# matcher until 2026-08-21, and it was green while SEVEN dead citations stood
# in the deployed set. Each survivor named the same file the gate exists to
# police, in a spelling the pattern could not express:
#
#   3b  `SHARP_EDGES section "Stop Gate Timeout ..."`   -- no `.md`
#   3c  `The "Skill Triggering Reliability" entry in `docs/SHARP_EDGES.md``
#                                                      -- heading BEFORE file
#   3a  a heading wrapped across a line, and `(` before the quote
#
# Separate patterns rather than one alternation: `re` forbids a duplicate
# group name, and three readable regexes beat one unreadable one.

# form 3a: `docs/FOO.md "Heading"` / `docs/FOO.md` section "Heading" /
#          `docs/FOO.md`\n("Heading")
_SECTION_AFTER_FILE = re.compile(
    rf"""`?(?P<file>{_MD_NAME})`?
        [ \t]*(?:\n[ \t]*)?        # a citation may wrap across one line
        (?:section[ \t]+)?
        [([]?                      # a bracket may open before the quote
        {_SECTION}
    """,
    re.VERBOSE | re.IGNORECASE,
)

# form 3b: the extension-less shorthand. NOT case-insensitive -- the all-caps
# shape is the only thing separating a file reference from ordinary prose.
_SECTION_AFTER_CAPS = re.compile(
    rf"""(?<![\w/.])(?P<file>{_CAPS_DOC})(?:\.md)?
        [ \t]*(?:\n[ \t]*)?
        [Ss]ection[ \t]+           # REQUIRED here: the disambiguator
        [([]?
        {_SECTION}
    """,
    re.VERBOSE,
)

# form 3c: the heading comes FIRST -- `The "A" and "B" entries in `docs/X.md``.
#
# Anchored on the TAIL (`entries in <file>`) and resolved by scanning backwards,
# rather than as one left-to-right pattern. A single pattern cannot do this: one
# sentence may name several headings for the same file, `finditer` returns
# non-overlapping matches, so the first match would consume the file reference
# and every later heading on that line would go unreported. Undercounting is the
# specific failure this whole gate exists to stop, so it does not get to
# reappear inside the gate's own matcher.
_CITED_FILE_TAIL = re.compile(
    rf"""\b(?:entry|entries|section|sections)\b
        \s{{0,4}}
        (?:in|of|from)
        \s{{0,4}}
        `?(?P<file>{_MD_NAME})`?
    """,
    re.VERBOSE | re.IGNORECASE,
)

# How far back from that tail a heading may sit and still belong to it. Two
# headings plus their connective run to roughly 130 characters; 220 leaves room
# without reaching the previous sentence.
_BACKSCAN = 220

_QUOTED = re.compile(r'["“]([^"”\n]{2,120})["”]')

SECTION_CITATION_RES: tuple[re.Pattern[str], ...] = (
    _SECTION_AFTER_FILE,
    _SECTION_AFTER_CAPS,
)

# Retained name: form 3a alone, for anything that imported the original.
SECTION_CITATION_RE = _SECTION_AFTER_FILE

# form 2: a backticked markdown file, e.g. `docs/HOOKS.md` or `RUNBOOK.md`.
#
# Bare basenames are IN, and that was not the first cut. Requiring a `/`
# suppressed the noise (`SHARP_EDGES.md`, `MEMORY.md` written as shorthand for
# a file one directory away) but also suppressed `POSITIONING.md` -- cited
# twice as fact from the deployed FAILURE_MODES.md, resolvable on the
# self-host tree, absent from every adopter's. That is a confirmed member of
# the very class this gate exists to close, so the narrowing was buying
# quiet at the cost of the finding. The noise is handled where it belongs
# instead: `resolve_on_tree` falls back to basename-anywhere, so shorthand
# for a file that IS on the tree resolves rather than being reported.
BARE_PATH_RE = re.compile(r"`(?P<file>(?:[\w.-]+/)*[\w.-]+\.md)`")

# form 2', for CODE carriers: the same path, backticks OPTIONAL.
#
# A deny message is plain prose on a terminal -- `ci_guard.py`'s ends
# "See docs/INSTALL-CI.md for details." with no markup at all, because
# backticks would be noise in a CI log. Requiring them (as the markdown arm
# does, where they are the convention) would miss every such pointer, which is
# precisely how DEF-503 survived a gate written to catch it.
#
# This is deliberately NOT merged into `bare_path_refs`. On markdown the
# backtick is doing real work: it separates `docs/FOO.md` (a path the reader
# should open) from an ordinary sentence that happens to name a file. Dropping
# it there would re-import the noise `resolve_on_tree`'s fallback was built to
# absorb. Two carriers, two conventions, two matchers.
# The trailing `(?!\w)` is doing the job the backtick does for `BARE_PATH_RE`.
# Without a right-hand boundary, `notes.mdx` and `checksums.md5` each yield a
# phantom `*.md` target -- which either false-flags a dead pointer or, worse,
# resolves onto a real file of that name the text never mentioned. Dormant
# today (no `.md` followed by a word character anywhere in the deployed set),
# fixed anyway because it is the §10.11 class exactly: a matcher inventing a
# citation the author did not write.
PLAIN_PATH_RE = re.compile(r"(?P<file>(?:[\w.-]+/)*[\w.-]+\.md)(?!\w)")


def readable_text(text: str) -> str:
    """Blank fenced code, but KEEP ``#`` comment lines inside a fence.

    Fences must be excluded, because a shell snippet is an instruction to the
    shell rather than a pointer at a document -- ``test -f
    ".claude/commands/$cmd.md" && echo "[OK]"`` alone produced two phantom
    targets (``cmd.md``, ``agent.md``) and a phantom section (``&& echo``).

    But blanking the WHOLE fence overshoots. A ``#`` comment inside a ```bash
    block is prose: a reader reads it and follows what it names. Measured, the
    plain fence strip silently dropped a real dead pointer -- CHEAT-SHEET's
    ``# ... see docs/SHARP_EDGES.md "ESPALIER_STOP_GATE=full Exported in Shell
    RC"`` -- which is exactly the false silence this gate exists to end. The
    comment marker is the discriminator: it separates what the reader reads
    from what the shell runs.

    Limit, stated: ``#`` only. A ``//`` comment in a fenced JS block is not
    recovered. Every fence in the deployed set today is shell or python.
    """
    stripped = strip_fenced_blocks(text)
    out: list[str] = []
    for original, blanked in zip(text.splitlines(), stripped.splitlines()):
        keep = original.lstrip().startswith("#") and not blanked
        out.append(original if keep else blanked)
    return "\n".join(out)


def section_citations(text: str) -> list[tuple[str, str]]:
    """``(filename, section)`` pairs cited in ``text``.

    A section name carrying ``<`` or ``>`` is an illustrative placeholder, not
    a heading -- ``docs/sharp-edges/README.md`` documents its own convention as
    ``docs/SHARP_EDGES.md section "<exact heading>"``. Same rule
    ``_artifact_links`` already applies to link targets, applied here so the
    case is handled by the matcher rather than by an exemption row that would
    read as a real dead pointer somebody had waved through.

    Whitespace in the heading is COLLAPSED, not merely stripped: form 3a now
    accepts a heading wrapped across a line, and the newline plus its indent
    have to become one space or the result never matches the real ``##`` it
    names -- turning a live citation into a phantom dead one.

    The three forms are deduped against each other. They overlap by design
    (``SHARP_EDGES.md`` satisfies both 3a and 3b), and a citation reported
    twice would double-count in ``totals`` and read as two defects.
    """
    readable = readable_text(text)
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(raw_name: str, raw_section: str) -> None:
        section = " ".join(raw_section.split())
        if PLACEHOLDER_RE.search(section):
            return
        name = raw_name if raw_name.lower().endswith(".md") else raw_name + ".md"
        if (name, section) in seen:
            return
        seen.add((name, section))
        out.append((name, section))

    for pattern in SECTION_CITATION_RES:
        for m in pattern.finditer(readable):
            add(m.group("file"), m.group("section"))

    # form 3c, resolved backwards from its tail so EVERY heading in a
    # multi-heading sentence is reported, not just the one nearest the file.
    for m in _CITED_FILE_TAIL.finditer(readable):
        window = readable[max(0, m.start() - _BACKSCAN) : m.start()]
        for q in _QUOTED.finditer(window):
            add(m.group("file"), q.group(1))

    return out


def bare_path_refs(text: str) -> list[str]:
    """Backticked path-qualified ``*.md`` references."""
    return [m.group("file") for m in BARE_PATH_RE.finditer(readable_text(text))]


def plain_path_refs(text: str) -> list[str]:
    """``*.md`` references with or without backticks -- for code carriers.

    ``readable_text`` still applies: a hook advisory may embed a fenced block
    of commands to run, and a path inside one is an argument to a shell, not a
    document to open -- the same distinction the markdown arm draws, for the
    same reason.
    """
    return [m.group("file") for m in PLAIN_PATH_RE.finditer(readable_text(text))]


# form 2'': a backticked, PATH-QUALIFIED reference to a file that is not
# markdown -- `tests/test_hooks.py`, `.espalier/freshness.json`,
# `scripts/run_pack_chain.sh`, `espalier/cli.py::cmd_init`,
# `tools/cc/hooks/write_guard.py::check_secret_path_access`.
#
# Path-qualified ONLY, and the limit is stated here rather than discovered
# later. The `.md` arm admits bare basenames because a real dead pointer
# (`POSITIONING.md`) hid behind that narrowing. Measured over the deployed set
# (2026-09-12, 392 non-markdown references), the bare-basename population for
# source files is the opposite shape -- `x.py`, `test_foo.py`, `conftest.py`,
# `main.py`, `package.json` -- every one an illustrative example or shorthand
# for a qualified path cited beside it, and none a place a reader is sent. A
# directory in the spelling is the author asserting a location; that is what
# this arm resolves.
#
# `.md` is excluded by the reader, not the pattern: `BARE_PATH_RE` owns it,
# with the section citations and the basename fallback that arm needs. One
# target, one owner.
#
# A `::symbol` or `:NN` suffix inside the backticks is tolerated and dropped.
# The file is what a reader opens; the symbol and the line number rot on their
# own schedule and carry no deploy-tree signal (the self-host sibling
# `tests/test_doc_source_citations.py` says the same of line anchors).
SRC_PATH_RE = re.compile(
    r"`(?P<file>(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,5})(?::\d+|::[\w.]+)*`"
)


def is_illustrative_path(target: str) -> bool:
    """A path-shaped token that is a SHAPE, not a citation.

    Two rules, both measured on the deployed set and each stated here so the
    next reader knows what is excused and why:

    - a single-character stem (`a/b/x.py`, `tools/cc/x.py`) -- the docs
      demonstrate path-equivalence attacks with deliberately fake paths; the
      same rule `tests/test_doc_source_citations.py` applies;
    - a slash-separated ALTERNATION whose every segment carries the same
      extension (`json.dump/pickle.dump/yaml.dump`) -- prose listing sibling
      calls with `/` as "or", which the path regex cannot tell from a
      directory. A real path never repeats one extension on every segment.
    """
    segments = target.split("/")
    stem = segments[-1].rsplit(".", 1)[0]
    if len(stem) == 1:
        return True
    exts = {s.rsplit(".", 1)[-1] if "." in s else "" for s in segments}
    return len(exts) == 1 and "" not in exts


def src_path_refs(text: str) -> list[str]:
    """Backticked path-qualified non-markdown references, in prose."""
    return [
        m.group("file") for m in SRC_PATH_RE.finditer(readable_text(text))
        if not m.group("file").lower().endswith(".md")
        and not is_illustrative_path(m.group("file"))
    ]


# form 5: an INVOCATION -- `python scripts/x.py`, `python3 tools/cc/y.py
# --flag`, `"$PY" scripts/z.py`, `pytest tests/test_a.py tests/test_b.py`.
#
# An instruction to run, so FENCES ARE INCLUDED. Every other form here strips
# ``` blocks because a shell snippet is an argument to the shell rather than
# a pointer at a document; this form exists for exactly that argument. The
# whole point of a ```bash block in a command body is that the reader's
# Claude runs it, and a script that is not on their tree ends the step with
# No-such-file (DEF-622's named user: an adopter whose `/handoff` step invokes
# `scripts/record_snapshot.py`, a file `init` never deploys).
#
# The interpreter is a closed set on purpose. `python` / `python3` are the
# repo's two documented spellings, `"$PY"` is the resolved form
# `/preflight` writes, and `pytest` is a runner whose argument is a file the
# reader must have. A bare `./script.py` is not an invocation this repo
# writes in a shipped body (measured zero), so it is not admitted -- adding
# it would be a matcher inventing a form the author never wrote.
#
# Every `.py` path in the argument run is reported, not only the first:
# `pytest tests/test_redos.py tests/test_hooks.py` names two files the reader
# needs, and a matcher that saw one would undercount, which is the specific
# failure the section-citation matcher above refused to reproduce.
#
# Two boundaries keep the matcher from inventing invocations the author never
# wrote: a fence language tag (```python) is three backticks and a word, not a
# command, so the interpreter may not follow ```; and the argument run stops
# at a backtick or a parenthesis, so a table cell reading "pytest
# (`tests/test_x.py::fixture`)" names a fixture's home rather than running
# it. A `<placeholder/path.py>` is a shape, not a script -- the same `<>`
# rule the link and section matchers apply -- and is not reported. A path
# that opens with a shell variable (`"$CLAUDE_PROJECT_DIR/scripts/x.py"`) is
# not a path this matcher can resolve, so `$` is a boundary too: without it
# the variable's NAME became the first segment of a phantom path.
_INTERPRETER = r'(?:python3?|pytest|"?\$PY"?)'
_EXEC_LINE_RE = re.compile(
    rf"(?<![\w.\-/])(?<!```){_INTERPRETER}[ \t]+(?P<args>[^\n|;&`()]*)"
)
_PY_ARG_RE = re.compile(
    r"(?<![\w.\-/<$])(?P<file>(?:[\w.-]+/)+[\w.-]+\.py)(?![\w.\-/>])"
)

# A shell test that makes an invocation conditional on the file it runs:
# `if [ -f scripts/x.py ]; then python scripts/x.py; fi`. The reader whose
# tree lacks the script skips the step instead of erroring, so the pointer is
# honest -- the fence itself says "if you have it". Only a test on the SAME
# path in the SAME fence counts; a guard elsewhere in the document says
# nothing about this block.
_FILE_TEST_RE = re.compile(
    r"(?:\[\[?|\btest)[ \t]+-[fex][ \t]+\"?(?P<file>(?:[\w.-]+/)*[\w.-]+\.\w+)\"?"
)
_FENCE_RE = re.compile(r"(?ms)^[ \t]*```[^\n]*\n.*?^[ \t]*```[ \t]*$")


class ExecRef(NamedTuple):
    file: str
    lineno: int
    guarded: bool             # a -f/-e/-x test on this path in the same fence
    fence: str | None         # the whole enclosing fence, or None for a prose mention
    fence_start: int | None   # 1-based line number of the fence's opening ``` line


def _fence_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _FENCE_RE.finditer(text)]


def exec_refs(text: str) -> list[ExecRef]:
    """Every script a shipped body tells the reader to RUN, prose and fences.

    ``guarded`` is true when the enclosing fence tests for the same path
    (``[ -f <path> ]`` / ``test -f <path>``) before running it. ``fence`` is
    the enclosing block's full text and ``fence_start`` its first line, so a
    caller can find the ``#`` comment that introduces the command -- the
    prose a reader of a fence actually reads.

    A command on a ``#`` line inside a fence is commented OUT, not run, and is
    not reported: the same channel the marker rule reads is the one a reader
    uses to retire a command in place.
    """
    spans = _fence_spans(text)
    guards_by_span: dict[tuple[int, int], set[str]] = {
        span: {
            g.group("file") for g in _FILE_TEST_RE.finditer(text[span[0]:span[1]])
        }
        for span in spans
    }
    out: list[ExecRef] = []
    for m in _EXEC_LINE_RE.finditer(text):
        span = next((s for s in spans if s[0] <= m.start() < s[1]), None)
        line_start = text.rfind("\n", 0, m.start()) + 1
        if span and text[line_start:m.start()].lstrip().startswith("#"):
            continue
        guards = guards_by_span.get(span, set()) if span else set()
        fence = text[span[0]:span[1]] if span else None
        fence_start = text.count("\n", 0, span[0]) + 1 if span else None
        lineno = text.count("\n", 0, m.start()) + 1
        for p in _PY_ARG_RE.finditer(m.group("args")):
            out.append(
                ExecRef(p.group("file"), lineno, p.group("file") in guards,
                        fence, fence_start)
            )
    return out


# form 6: a wikilink -- `[[some-slug]]`, the repo's own cross-reference
# spelling between memory entries. Resolved as `<slug>.md` anywhere on the
# tree, which is how the reader's own `/recall` and the folder ladder find
# one. Fenced occurrences are not links (a Python list literal `[[` is the
# same two characters), so this reads the same `readable_text` view as the
# other prose forms.
WIKILINK_RE = re.compile(r"\[\[(?P<slug>[\w-]+)\]\]")


def wikilink_refs(text: str) -> list[str]:
    """Slugs of every ``[[wikilink]]`` in prose."""
    return [m.group("slug") for m in WIKILINK_RE.finditer(readable_text(text))]


def resolve_on_tree(tree_members: set[str], carrier_relpath: str, target: str) -> str | None:
    """Resolve ``target`` the way a reader on that tree would, or ``None``.

    Order matters and the third step is load-bearing: carrier-relative, then
    repo-root, then **basename anywhere on the tree**. Without the third,
    ``docs/sharp-edges/README.md`` citing bare ``SHARP_EDGES.md`` reads as
    dead when the file it means is one directory up and plainly findable.
    """
    from pathlib import PurePosixPath

    base = PurePosixPath(carrier_relpath).parent
    candidates = [_normalize(str(base / target)), _normalize(target)]
    for cand in candidates:
        if cand and cand in tree_members:
            return cand
    return _basename_anywhere(tree_members, target)


def resolve_from_root(tree_members: set[str], target: str) -> str | None:
    """Resolve ``target`` for a CODE carrier -- repo-root-relative only.

    Deliberately NOT ``resolve_on_tree``, and the difference is the whole
    point. That function tries carrier-relative FIRST, which is right for
    markdown: a link in ``docs/sharp-edges/README.md`` is authored and read
    relative to its own directory.

    A string constant in a hook is not read that way. It is printed to a
    terminal or a CI log and read by somebody standing at the repo root --
    ``ci_guard.py`` saying "See docs/INSTALL-CI.md" means ``<repo>/docs/``, not
    ``tools/cc/docs/``. Offering the carrier-relative candidate would relax a
    dimension the citation never left open, and could resolve a pointer onto a
    file the message did not mean. That is the failure this suite already
    records at ``docs/FAILURE_MODES.md`` §10.11 -- a gate's own resolver
    manufacturing the pass it exists to prevent -- so the code arm does not
    get that candidate at all.

    The basename fallback IS kept, under its existing guard: an unqualified
    ``FOO.md`` in a deny message asks the reader to find a file, and finding it
    anywhere on the tree is what they would do.
    """
    cand = _normalize(target)
    if cand and cand in tree_members:
        return cand
    return _basename_anywhere(tree_members, target)


def _basename_anywhere(tree_members: set[str], target: str) -> str | None:
    """Last-resort match on an UNQUALIFIED name, never a path-qualified one.

    A citation that spells a directory is asserting a location; collapsing it
    to a basename does not "find" the file -- it changes which file is meant.

    This was a live false pass, caught in review: ``.claude/commands/handoff.md``
    cites ``espalier/assets/docs/FAILURE_MODES.md``, a package-data mirror that
    exists on NO adopter tree (there is no ``espalier/`` directory there at
    all). The unguarded fallback matched the one file named
    ``FAILURE_MODES.md`` on the tree -- ``docs/FAILURE_MODES.md``, an unrelated
    seeded doc -- and reported it resolved, so the pointer was waved through by
    the very mechanism written to catch it. Canon: ``docs/FAILURE_MODES.md``
    §10.11, "a fallback may only relax a dimension the input left unspecified".

    Shared by both resolvers so the guard cannot be present on one path and
    quietly missing on the other.
    """
    from pathlib import PurePosixPath

    if "/" in target:
        return None
    matches = sorted(m for m in tree_members if PurePosixPath(m).name == target)
    return matches[0] if len(matches) == 1 else None


def _normalize(joined: str) -> str | None:
    parts: list[str] = []
    for part in joined.split("/"):
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts) or None
