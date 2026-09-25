"""TP-149 (149-F, L18) — catalog self-consistency for docs/FAILURE_MODES.md.

The failure-mode catalog is itself an enumeration that can drift out of
sync with its own structure — the very §10.8 enumeration-shadow / §4.6
vacuous-registry classes it documents. Before TP-149 it had NO mechanical
pin on its own shape. This contract closes that meta-gap with three checks:

(a) the §1 intro count word ("The thirteen modes …") equals the number of
    ``### 1.N`` sub-headings;
(b) every Table-of-contents entry ``N. [title](#…)`` resolves to a real
    ``## N. `` top-level heading, and vice versa (no orphans either way);
(c) the coinage-enumeration prose ("The named coinages in this catalog
    (…) are NOT industry-standard terms.") lists exactly the §1 named-mode
    titles, in order.

Earn-the-red: ``test_earn_the_red_*`` inject a fake ``### 1.14`` heading
into a copy and assert the count check fails on the mismatch (intro says
thirteen, the injected copy then has fourteen).
"""
from __future__ import annotations

import ast
import functools
import io
import re
import subprocess
import sys
import tokenize
import warnings
from pathlib import Path

import pytest

from tests._export_guard import pruned_from_this_tree

from espalier.canon_vocab import failure_mode_coinages
from espalier.claim_extractor import OUT_OF_DOMAIN
from espalier.surface_contract import is_shipped_pack

# slow-exempt: the one subprocess call is a single fast `git ls-files` enumeration
# (`_tracked_anchor_docs`, TP-373 3-A tree-wide anchor scan); the whole module runs in
# ~1.4s. It was <1s until the anchor population gained the ~500 tracked `.py` files:
# measured 0.73s before, 2.8s after, 1.4s once `_anchor_scan_text` was memoised across
# the three tests that walk the population. Re-measure before quoting a new figure.
REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "FAILURE_MODES.md"

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
}


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _section1_mode_headings(text: str) -> list[str]:
    return re.findall(r"^### 1\.\d+ (.+)$", text, re.MULTILINE)


def _normalize(title: str) -> str:
    """Lowercase and strip any trailing parenthetical clarifier."""
    return re.sub(r"\s*\(.*\)\s*$", "", title).strip().lower()


# --- reusable check bodies (raise AssertionError on violation) ---------------
def _check_count_word(text: str) -> None:
    headings = _section1_mode_headings(text)
    m = re.search(r"The (\w+) modes? in this section", text)
    assert m, "could not find the §1 intro count-word sentence"
    word = m.group(1).lower()
    assert word in _NUM_WORDS, f"unrecognized §1 count word: {word!r}"
    assert _NUM_WORDS[word] == len(headings), (
        f"§1 intro says {word!r} ({_NUM_WORDS[word]}) modes but there are "
        f"{len(headings)} `### 1.N` headings"
    )


def _check_toc_resolves(text: str) -> None:
    toc_m = re.search(r"## Table of contents\n(.*?)\n---", text, re.DOTALL)
    assert toc_m, "Table of contents block not found"
    toc_nums = re.findall(r"^(\d+)\. \[.+?\]\(#", toc_m.group(1), re.MULTILINE)
    heading_nums = re.findall(r"^## (\d+)\. ", text, re.MULTILINE)
    assert toc_nums, "no TOC entries found"
    missing = [n for n in toc_nums if n not in heading_nums]
    assert not missing, f"TOC entries with no matching `## N.` heading: {missing}"
    orphan = [n for n in heading_nums if n not in toc_nums]
    assert not orphan, f"`## N.` headings absent from the TOC: {orphan}"


def _check_coinage_enumeration(text: str) -> None:
    # Two independent witnesses: the §1 *headings* (derived here) vs the
    # *prose* enumeration (parsed by espalier.canon_vocab — the single source
    # for that parse, also used for named_unit validation). They must agree.
    norm_headings = [_normalize(h) for h in _section1_mode_headings(text)]
    coinages = failure_mode_coinages(text)
    assert coinages == norm_headings, (
        "coinage enumeration does not match §1 titles in order.\n"
        f"  coinages: {coinages}\n"
        f"  headings: {norm_headings}"
    )


_SECTION_REF_RE = re.compile(r"§(\d+\.\d+)\b")
_SUBSECTION_HEADING_RE = re.compile(r"^### (\d+\.\d+) ", re.M)


def _check_section_refs_resolve(text: str) -> None:
    """Every prose ``§N.M`` cross-reference names a live ``### N.M`` heading.

    The catalog's entries point at each other by number (``**Related.** §18.4
    ...``), and until 2026-09-04 nothing resolved those pointers: the ToC check
    covers ``## N.`` sections only, so renumbering a subsection would have left
    every reference to it dangling in a document that ships to adopters. Measured
    when added: 341 references to 111 distinct subsections, all resolving.
    """
    headings = set(_SUBSECTION_HEADING_RE.findall(text))
    dangling = sorted({ref for ref in _SECTION_REF_RE.findall(text) if ref not in headings})
    assert not dangling, (
        f"{len(dangling)} §-reference(s) name no `### N.M` heading in "
        f"docs/FAILURE_MODES.md: {dangling[:8]} -- renumbered or removed a "
        "subsection without updating the entries that cite it"
    )


# --- live-doc contracts ------------------------------------------------------
def test_section1_count_word_matches_heading_count():
    _check_count_word(_text())


def test_toc_entries_resolve_to_headings():
    _check_toc_resolves(_text())


def test_coinage_enumeration_matches_section1_titles():
    _check_coinage_enumeration(_text())


def test_section_references_resolve_to_headings():
    _check_section_refs_resolve(_text())


# --- earn-the-red ------------------------------------------------------------
def test_earn_the_red_fake_heading_breaks_count():
    """Inject a fake §1.14 heading (1.13 is now real); the count check must
    fail on the mismatch (intro says thirteen, structure now has fourteen)."""
    mangled = _text() + "\n\n### 1.14 Fake injected mode\n\n**Signature.** n/a.\n"
    with pytest.raises(AssertionError):
        _check_count_word(mangled)


def test_earn_the_red_dangling_section_ref_detected():
    """Cite a subsection that does not exist; the resolver must name it."""
    mangled = _text() + "\n\nSee §99.7 for the injected dangling reference.\n"
    with pytest.raises(AssertionError, match=r"99\.7"):
        _check_section_refs_resolve(mangled)


def test_earn_the_red_fake_heading_breaks_coinage_list():
    """The injected fake mode is also not in the coinage enumeration, so
    the (c) check fails too — the two checks are independent witnesses."""
    mangled = _text() + "\n\n### 1.14 Fake injected mode\n\n**Signature.** n/a.\n"
    with pytest.raises(AssertionError):
        _check_coinage_enumeration(mangled)


# =============================================================================
# TP-152 152-D — mechanical doc-anchor resolution contract.
#
# Doc anchors of the form ``symbol`` paired with a ``file.py:NN`` line rot the
# moment the code moves — and nothing resolved them, which is exactly why W23,
# W24, and four catalog NITs all pointed at the wrong line after TP-151 shifted
# code. This is the missing canon. Two complementary checks:
#
#   Mode 1 (auto-discover, anti-rot): scan the doc for any `symbol` adjacent to
#     a `file.py:NN` LINE anchor; resolve the symbol's live def line and assert
#     the cited line is within _DEF_TOLERANCE of it. Line anchors are the thing
#     that rots, so this is the gate whose absence let them all drift. The
#     drift-proof remedy is to drop the line number — which removes the anchor
#     from this scan — so a green live run with zero line anchors is the healthy
#     state, NOT a vacuous one: Mode 2 keeps it honest.
#
#   Mode 2 (explicit registry, non-vacuous): every drift-proof `symbol` + `file`
#     anchor we rely on is listed in _SYMBOL_ANCHORS; the contract asserts the
#     symbol still resolves to a def/class/assignment in that file (catches a
#     rename or file-move that a line-less anchor would otherwise hide) and that
#     the doc actually names both. Add a row when you add such an anchor.
#
# Earn-the-red: injection tests below prove both modes fire; and running this
# contract against the pre-152-D docs failed RED on the three stale FAILURE_MODES
# line anchors (cli.py:486→651, cognitive_blueprint.py:281→415, canon_verifier
# .py:425→459).
# =============================================================================

_DEF_TOLERANCE = 3  # a line anchor may sit within N lines of the symbol's def
_SOURCE_DIRS = ("espalier", "tools", "tests", "scripts", "bench")

# (doc relative to repo, backticked symbol as written, source file defining it)
_SYMBOL_ANCHORS = [
    ("docs/FAILURE_MODES.md", "_build_claude_md", "espalier/cli.py"),
    ("docs/FAILURE_MODES.md", "auto_continuation_fragments",
     "espalier/cognitive_blueprint.py"),
    ("docs/FAILURE_MODES.md", "canon_verifier._verify_test_canon",
     "espalier/scanners/canon_verifier.py"),
    ("docs/FAILURE_MODES.md", "REQUIRED_GITIGNORE", "espalier/cli.py"),
    ("docs/FAILURE_MODES.md", "task_router._has_active_plan",
     "tools/cc/hooks/task_router.py"),
    # ESPALIER_MEMORY.md rows removed 2026-07-05 (file curated to a stub), re-added
    # 2026-08-15 to give one cross-module citation a drift-proof form, and RETIRED
    # AGAIN 2026-08-29 as DEF-621. Do not re-add one: `ESPALIER_MEMORY.md` is a
    # declared rotating host (see `_ROTATING_ANCHOR_HOSTS`) and
    # `test_no_symbol_anchor_targets_a_rotating_host` now reds on it.
    #
    # Why the 2026-08-15 reasoning was sound and the row still failed: the row pinned
    # prose, and on a bounded log the prose is evicted. `6c8fdff` trimmed the very
    # 2026-08-15 entry the row was added to protect -- shedding the file's only
    # `doctor.py` mention while `run_doctor_check` survived in a NEIGHBOURING row --
    # so Mode 2's third assert failed on a commit that changed no code, and it was
    # pushed red because the green suite predated the memory commit.
]

# `symbol`(optional call) — short bridge — file.py:NN[-MM]. The bridge forbids a
# sentence break ('.') so a symbol is only paired with an anchor that directly
# follows it. TP-175 R9: a `:NN-MM` RANGE is now validated by its START line NN
# (the `(?:-\d+)?` consumes the suffix), since ranges rot exactly like single
# lines — the stale `:99-101` anchor for `_HARNESS_ENV_PREFIX_RE` (really at
# :148) proved it. Block references whose "symbol" is a usage, not a def, still
# resolve to "prose" via _resolve_source and are skipped, so this widening
# adds no false positives (measured 0 on the live catalog).
_LINE_ANCHOR_RE = re.compile(
    r"`(?P<sym>[A-Za-z_][\w.]*)(?:\([^`]*\))?`"
    r"[^`.]{0,40}?"
    r"`?(?P<file>[\w./-]+\.py):(?P<line>\d+)(?:-\d+)?`?"
)

# A code symbol never ends in a file extension. The `sym` group is permissive
# (it allows dotted names like ``os.replace`` / ``cli.cmd_init``), so it also
# matches a FILENAME name-dropped in prose -- e.g. ``setup.sh`` sitting 40 chars
# before ``run_benchmark.py:1859``. Those are not ``symbol``->def anchors; treat
# any `sym` ending in one of these (non-``.py``) extensions as prose and skip it.
# (Same class as the TP-171 1-A ambiguous-basename prose skip below; the trigger
# here was a ESPALIER_MEMORY.md LICENSE-1 row citing ``setup.sh`` next to a .py anchor.)
_NON_SYMBOL_SUFFIXES = (
    ".sh", ".md", ".json", ".yml", ".yaml", ".txt", ".toml",
    ".cfg", ".ini", ".bat", ".ps1", ".cmd", ".lock", ".csv", ".py",
)


def _resolve_source(file_ref: str, symbol: str | None = None) -> tuple[str | None, str]:
    """Map an anchor's file reference to a repo-relative source path.

    Returns ``(path, status)`` where ``status`` is one of:

      * ``"ok"``        -- resolved to a unique source path (in ``path``).
      * ``"missing"``   -- the basename matches no source file.
      * ``"prose"``     -- ambiguous basename AND ``symbol`` is defined in NONE
        of the matches: this is prose that name-drops a symbol and a file in one
        sentence, not a ``symbol``->def line anchor. The caller skips it.
      * ``"ambiguous"`` -- ambiguous basename AND ``symbol`` is defined in more
        than one match (or no ``symbol`` was supplied): a genuinely
        under-qualified anchor; the caller fails and asks the author to qualify
        the path.

    A full relative path resolves directly. A bare basename resolves if exactly
    one file under the source dirs carries that name. When the basename is
    ambiguous (TP-171 1-A: e.g. ``cognitive_blueprint.py`` exists in both
    ``espalier/`` and ``tools/cc/``), the candidate that actually DEFINES the
    symbol disambiguates. This is what separates a real anchor
    (``list_blueprint_chain`` -> cognitive_blueprint.py, defined only in
    espalier/) from prose like ``scaffolding_canon`` + sister
    ``cognitive_blueprint.py:212`` -- ``scaffolding_canon`` is defined in neither
    cognitive_blueprint.py, so resolution returns ``"prose"`` and the scanner
    does not read the sentence as a stale anchor (the pre-TP-171 behaviour --
    return None on any ambiguity -- hard-failed that prose).
    """
    if (REPO_ROOT / file_ref).is_file():
        return file_ref, "ok"
    base = Path(file_ref).name
    matches: set[str] = set()
    for d in _SOURCE_DIRS:
        root = REPO_ROOT / d
        if root.is_dir():
            for m in root.rglob(base):
                rel = m.relative_to(REPO_ROOT).as_posix()
                # TP-178: espalier/_vendor/cc/ is a byte-identical copy of
                # tools/cc/; anchors resolve to the canonical tools/ source,
                # never the vendored dup (which would make every shared
                # basename like write_guard.py ambiguous).
                if rel.startswith("espalier/_vendor/"):
                    continue
                matches.add(rel)
    if len(matches) == 1:
        return next(iter(matches)), "ok"
    if not matches:
        return None, "missing"
    if symbol is not None:
        defining = [m for m in sorted(matches) if _symbol_def_lines(m, symbol)]
        if len(defining) == 1:
            return defining[0], "ok"
        if not defining:
            return None, "prose"
    return None, "ambiguous"


def _symbol_def_lines(source_rel: str, symbol: str) -> list[int]:
    """All module-level def/class/assignment lines for ``symbol`` (the last
    dotted component) in the given source file."""
    name = symbol.split(".")[-1]
    tree = ast.parse((REPO_ROOT / source_rel).read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                lines.append(node.lineno)
        elif isinstance(node, ast.Assign):
            lines += [
                node.lineno
                for t in node.targets
                if isinstance(t, ast.Name) and t.id == name
            ]
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                lines.append(node.lineno)
    return sorted(lines)


# TP-373 3-A (Horn B): deliberately-frozen `symbol`+`file.py:NN` anchors -- past-tense
# war-stories / review-record snapshots whose citation is INTENTIONALLY historical, so
# rewriting them to a live line would falsify the record. Keyed `doc:<doc-line>::<symbol>`
# (the doc line the citation sits on, NOT the cited source line) so the same symbol cited
# afresh at a different site is NOT auto-skipped -- it must be re-registered (self-documenting
# maintenance cost). Sibling of _SYMBOL_ANCHORS; seeded from the 0-A tree-wide classification.
# EMPTIED 2026-08-09, and that is the healthy end state rather than a gap. Both entries
# existed to tolerate a citation that was deliberately historical, and BOTH were retired by
# converting the citation itself to a form that cannot rot:
#
#   docs/CONVENTIONS.md::MUTATION_TOOLS   -- the sentence cited write_guard.py:52 (unbackticked so this comment does not itself
#     mint an anchor), which
#     today is `from __future__ import annotations`. It cited a line, not a symbol, so there
#     was nothing to convert TO: de-anchored to `write_guard.py`.
#   memory/task-packs.md::_HARNESS_ENV_PREFIX_RE -- cited write_guard.py:99-101, which now
#     holds `_PERL_OPEN_RE`. Converted to `write_guard.py::_HARNESS_ENV_PREFIX_RE`, which is
#     both drift-proof AND factually right: the pack's error was naming the wrong FILE, and
#     the line range was never the point.
#
# The freeze mechanism is deliberately LEFT WIRED (see `_check_line_anchors_fresh`) so a
# genuinely-historical anchor can still be registered.
#
# RE-KEYED 2026-08-09 (ledger DEF-417i), and the old shape is why. Keys were
# `<doc>:<doc-line>::<symbol>` -- POSITIONAL in the citing doc -- so an edit ABOVE a frozen
# sentence shifted its line, the key stopped matching, and the intentionally-stale anchor
# resurfaced as a hard failure in a file the editor had no reason to think was involved. An
# allowlist for line-anchor rot that was itself subject to line-anchor rot. It drifted twice
# (465->475, 204->212), and its twin registry in the magic-depth scanner drifted the same way
# (131->133) four days later -- one class, two registries, both now retired.
#
# The key is now the citation's own TEXT:
#
#     <doc>::<symbol>::<cited-file>:<cited-line>
#
# Nothing about WHERE the sentence sits. Insert four hundred lines above it and the key is
# unchanged; reword the citation and the freeze lapses, which is correct -- a reworded
# war-story is a different claim and deserves re-registering. That is also what keeps this
# an allowlist rather than an unconditional mute: the key can still go stale, just never
# from an edit somewhere else in the file.
#
# The cited line stays IN the key on purpose. It is not a position we resolve against, it is
# part of what the sentence says, so the same symbol cited afresh at a different line is NOT
# auto-skipped -- it must be re-registered (self-documenting maintenance cost).
#
# Prefer converting the citation over registering it here; a row added back is a row someone
# must eventually re-read.
_FROZEN_ANCHORS: frozenset[str] = frozenset()

# Whole docs excluded wholesale from the tree-wide scan. THE TWO ENTRIES ARE HERE FOR
# DIFFERENT REASONS, and conflating them is what kept this open for two months:
#
#   ENV_CATALOG (+ twin) -- OUT OF DOMAIN. It lists env-var *strings* next to a read-site,
#   not AST symbols, so the resolver has nothing to resolve. A scanner-domain exclusion.
#
#   (The fan-out findings corpus was the other exclusion, as an append-only RECORD SURFACE
#   whose anchors were dated snapshots of where a finding was: a count of broken anchors
#   there was never a defect count -- see memory/classify-the-surface-before-measuring-it.md.
#   It retired to the record branch 2026-09-21.)
# Tagged per entry because this set has exempted docs for unrelated reasons, and a
# reconciliation that keyed on the prose above would be one reword away from
# reclassifying a document by accident. Membership reads (`in`, `set(...)`) are
# unchanged by the dict; only the class became mechanical.
_ANCHOR_SCAN_EXCLUDE_DOCS: dict[str, str] = {
    # Out of domain: env-var STRINGS beside a read-site, not AST symbols.
    "docs/ENV_CATALOG.md": OUT_OF_DOMAIN,
    "espalier/assets/docs/ENV_CATALOG.md": OUT_OF_DOMAIN,  # shipped twin
}

# The third exclusion is a PREDICATE, not an entry, because its members are a
# population that grows: the task packs that ship since 2026-09-21 (the active
# ones at task-packs/ root and the drafted ones under Deferred/). A pack is a
# dated PLAN, not live documentation: it cites the line it measured at authoring
# and the files it proposes to create, and its own Affected-symbols walk
# (scope-check, re-run by /implement-pack at execution) is what re-derives both.
# Measured when the packs first entered the tracked tree: 127 bare `path:NN`
# anchors and 10 stale symbol anchors across 17 drafts, none of them a defect a
# reader of the plan is misled by. The forward ledger itself is NOT a plan -- its
# rows are live claims -- so it stays in, with its anchors converted. The one
# home of the predicate is `espalier.surface_contract.is_shipped_pack`; this
# module and tests/test_doc_source_citations.py import it, never re-type it.


def _check_line_anchors_fresh(text: str, doc_rel: str | None = None) -> None:
    """Mode 1: every `symbol`+`file.py:NN` line anchor resolves within tolerance.

    ``doc_rel`` (TP-373 3-A, opt-in): when the caller passes the doc's repo-relative path,
    an anchor whose ``doc_rel::<symbol>::<file>:<line>`` key is in ``_FROZEN_ANCHORS`` is
    skipped (a deliberately-frozen war-story). The key is the citation's TEXT, never its
    position in the doc -- see ``_FROZEN_ANCHORS``. Left ``None`` -- the two pre-existing callers and
    ``tests/test_memory_anchor_freshness.py`` -- the resolver behaves exactly as before, so the
    ``(text)`` signature stays back-compatible (nothing downstream re-keys on the new arg)."""
    for m in _LINE_ANCHOR_RE.finditer(text):
        sym, file_ref, line = m.group("sym"), m.group("file"), int(m.group("line"))
        if doc_rel is not None and f"{doc_rel}::{sym}::{file_ref}:{line}" in _FROZEN_ANCHORS:
            # Keyed on what the citation SAYS, not where it sits: an edit above this
            # sentence must not un-key it (ledger DEF-417i).
            continue
        if sym.lower().endswith(_NON_SYMBOL_SUFFIXES):
            # `sym` is a filename name-dropped in prose (e.g. `setup.sh` next to
            # `run_benchmark.py:1859`), not a code symbol -- not a stale anchor.
            continue
        src, status = _resolve_source(file_ref, sym)
        if status == "prose":
            # Ambiguous basename whose symbol is defined in none of the matches:
            # a name-drop in one sentence, not a stale anchor (TP-171 1-A).
            continue
        assert status != "missing", (
            f"doc line anchor `{sym}` -> {file_ref}:{line} names a file that does "
            f"not exist under {_SOURCE_DIRS}"
        )
        assert src is not None, (
            f"doc line anchor `{sym}` -> {file_ref}:{line}: basename "
            f"{Path(file_ref).name!r} is AMBIGUOUS and `{sym}` is defined in more "
            f"than one match -- qualify the path (e.g. espalier/{Path(file_ref).name} "
            f"vs tools/cc/{Path(file_ref).name})"
        )
        defs = _symbol_def_lines(src, sym)
        assert defs, (
            f"doc line anchor `{sym}` -> {file_ref}:{line}, but {sym!r} is not "
            f"defined in {src} (renamed or moved?)"
        )
        assert any(abs(d - line) <= _DEF_TOLERANCE for d in defs), (
            f"stale line anchor: `{sym}` cites {file_ref}:{line} but {sym!r} is "
            f"defined at {defs} in {src} (tolerance ±{_DEF_TOLERANCE})"
        )


# DEF-621 (2026-08-29): docs whose CONTENT rotates cannot host a Mode-2 registry
# anchor. A registry row pins "the doc still backticks `sym` AND still names `src`";
# on a bounded log the row carrying that prose is evicted on a schedule, so the pin
# fails without any code change. This is Core Rule 13 -- classify the surface before
# you measure it: on a rotating record a vanished citation is expected aging, not a
# defect. Mode 1 (line anchors) is unaffected: it scans whatever the file currently
# holds, so eviction removes anchors rather than staling them.
_ROTATING_ANCHOR_HOSTS: dict[str, str] = {
    "ESPALIER_MEMORY.md": (
        "bounded Session Log -- capped at 120 lines, oldest rows evicted to "
        "docs/session-archive.md by `espalier memory prune`"
    ),
}


def _check_symbol_anchors_resolve(doc_rel: str) -> None:
    """Mode 2: every registered drift-proof anchor for ``doc_rel`` names a symbol
    that still resolves in its source file, and the doc mentions both.

    Refuses a rotating host (DEF-621): the third assert below pins PROSE, which a
    bounded log evicts on a schedule. Calling this on such a doc schedules a red.
    """
    assert doc_rel not in _ROTATING_ANCHOR_HOSTS, (
        f"{doc_rel} is a declared rotating host ({_ROTATING_ANCHOR_HOSTS[doc_rel]}), "
        "so Mode 2 cannot guard it -- its asserts pin prose that eviction removes. "
        "Use Mode 1 (line anchors), which self-adjusts as rows rotate out."
    )
    text = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
    for d, sym, src in _SYMBOL_ANCHORS:
        if d != doc_rel:
            continue
        defs = _symbol_def_lines(src, sym)
        assert defs, f"{doc_rel} anchors `{sym}` but it is not defined in {src}"
        # the symbol may appear backticked as `name` or `name(args)`
        assert re.search(rf"`{re.escape(sym)}(?:\(|`)", text), (
            f"{doc_rel} no longer backticks `{sym}` (registry row is stale)"
        )
        assert src.split("/")[-1] in text or src in text, (
            f"{doc_rel} no longer references {src} near `{sym}`"
        )


def test_doc_anchors_resolve_to_symbols():
    """FAILURE_MODES.md: line anchors fresh (Mode 1) + registered symbol anchors
    resolve (Mode 2)."""
    _check_line_anchors_fresh(_text())
    _check_symbol_anchors_resolve("docs/FAILURE_MODES.md")


def test_no_symbol_anchor_targets_a_rotating_host():
    """DEF-621: a Mode-2 registry row into a rotating host is a SCHEDULED failure.

    The row does not rot slowly -- it fails the day eviction reaches the entry
    carrying its prose. Driven 2026-08-29: `run_doctor_check` sat 11 rows from the
    bottom of a log already at its 120-line cap.
    """
    offenders = sorted({d for d, _, _ in _SYMBOL_ANCHORS if d in _ROTATING_ANCHOR_HOSTS})
    assert not offenders, (
        f"_SYMBOL_ANCHORS anchors into rotating host(s) {offenders}. Mode 2 asserts the "
        "doc still backticks the symbol AND still names the file; a bounded log evicts "
        "the row carrying that prose, so the anchor reds on a commit that changes no "
        "code (measured at 6c8fdff, pushed red). Use Mode 1, or cite from a doc that "
        "does not rotate."
    )
    # Self-expiry: a rule guarding a file that no longer exists silences nothing while
    # still reading as live judgement -- the same trap _ANCHOR_SCAN_EXCLUDE_DOCS pins.
    # On a release export a host can be absent by construction (ESPALIER_MEMORY.md is
    # an export-ignore sentinel); that is not the rule going dead (DEF-670).
    missing = sorted(h for h in _ROTATING_ANCHOR_HOSTS if not (REPO_ROOT / h).is_file())
    missing = sorted(set(missing) - pruned_from_this_tree(missing))
    assert not missing, (
        f"_ROTATING_ANCHOR_HOSTS names {missing}, which does not exist -- the rule "
        "guards nothing. Delete the entry, or repoint it if the file moved."
    )


def test_earn_the_red_stale_line_anchor_detected():
    """Mode 1 fires on a deliberately-stale line number."""
    mangled = "see `_build_claude_md` (`espalier/cli.py:1`) for details.\n"
    with pytest.raises(AssertionError):
        _check_line_anchors_fresh(mangled)


def test_earn_the_red_missing_symbol_detected():
    """Mode 1 fires when the cited symbol is not defined in the named file."""
    mangled = "see `totally_nonexistent_symbol_xyz` (`espalier/cli.py:1`).\n"
    with pytest.raises(AssertionError):
        _check_line_anchors_fresh(mangled)


def test_earn_the_red_missing_file_detected():
    """Mode 1 fires when the cited basename names no source file at all."""
    mangled = "see `some_symbol` (`no_such_module_xyz.py:1`) for details.\n"
    with pytest.raises(AssertionError, match="does not exist"):
        _check_line_anchors_fresh(mangled)


# TP-171 1-A: the anchor scanner must not read prose that name-drops a symbol
# and an ambiguous file in one sentence as a stale line anchor. The §7
# ESPALIER_MEMORY.md session-log row that triggered this (`scaffolding_canon` ...  sister
# `cognitive_blueprint.py:212`) was a self-inflicted red: `cognitive_blueprint.py`
# is an ambiguous basename and `scaffolding_canon` is defined in neither copy.
def test_ambiguous_basename_prose_is_not_an_anchor():
    """A symbol defined in NEITHER candidate of an ambiguous basename is prose,
    not an anchor -- the scanner skips it instead of hard-failing."""
    prose = (
        "type-stable keys in `scaffolding_canon` + sister "
        "`cognitive_blueprint.py:212` (chain-sort key).\n"
    )
    # No raise: scaffolding_canon is not defined in either cognitive_blueprint.py.
    _check_line_anchors_fresh(prose)
    assert _resolve_source("cognitive_blueprint.py", "scaffolding_canon") == (
        None,
        "prose",
    )


def test_filename_token_before_py_anchor_is_not_an_anchor():
    """A backticked FILENAME (``setup.sh``) sitting before a `.py:NN` anchor is
    prose, not a `symbol`->def anchor -- the scanner skips it. This reproduces the
    self-inflicted red from the ESPALIER_MEMORY.md LICENSE-1 row
    (``ships the `setup.sh` that `run_benchmark.py:1859` hard-requires``), where
    the permissive `sym` group matched the filename and the resolver then failed
    looking for a `setup.sh` symbol in bench/run_benchmark.py."""
    prose = (
        "the sdist ships the `setup.sh` that `run_benchmark.py:1859` "
        "hard-requires.\n"
    )
    _check_line_anchors_fresh(prose)  # no raise: setup.sh is a filename, not a symbol


def test_earn_the_red_genuinely_ambiguous_anchor_detected():
    """A symbol defined in BOTH copies of an ambiguous basename cannot be
    disambiguated -- the scanner fails and asks the author to qualify the path."""
    # `_load_json` is defined in espalier/cognitive_blueprint.py AND
    # tools/cc/cognitive_blueprint.py.
    mangled = "the `_load_json` helper at `cognitive_blueprint.py:1` parses it.\n"
    with pytest.raises(AssertionError, match="AMBIGUOUS"):
        _check_line_anchors_fresh(mangled)
    assert _resolve_source("cognitive_blueprint.py", "_load_json") == (
        None,
        "ambiguous",
    )


def test_ambiguous_basename_disambiguated_by_defining_symbol():
    """A symbol defined in exactly ONE candidate of an ambiguous basename
    resolves to that file -- a real anchor still works without a qualified path."""
    # `list_blueprint_chain` is defined only in espalier/cognitive_blueprint.py.
    path, status = _resolve_source("cognitive_blueprint.py", "list_blueprint_chain")
    assert status == "ok"
    assert path == "espalier/cognitive_blueprint.py"


# TP-373 (former TP-380): widen the Mode-1 line-anchor resolver beyond FAILURE_MODES.md /
# ESPALIER_MEMORY.md (its only two callers today) to the CURRENT-STATE reference docs that
# carry present-tense `symbol`+`file.py:NN` anchors. This curated tuple is belt-and-suspenders
# over the key reference surfaces; the whole-tree widen lives in
# test_tree_wide_line_anchors_fresh below, which skips the tense-blind false positives via the
# _FROZEN_ANCHORS baseline (memory/task-packs.md review-records, CONVENTIONS.md "was defined
# at" war-stories) and the out-of-domain _ANCHOR_SCAN_EXCLUDE_DOCS set (ENV_CATALOG.md env-var
# read-sites) that a naive docs/**+memory/** scan would
# false-flag -- measured at 0-A: 24 anchors, 4 live / 20 frozen-read-record.
_REFERENCE_ANCHOR_DOCS = (
    "docs/HOOKS.md",
    "docs/SHARP_EDGES.md",
    "memory/hook-authoring.md",
    "espalier/assets/docs/HOOKS.md",  # shipped byte-twin (parity-pinned; belt-and-suspenders)
)


@pytest.mark.parametrize("doc_rel", _REFERENCE_ANCHOR_DOCS)
def test_reference_doc_line_anchors_fresh(doc_rel):
    """Mode 1 over the curated present-state reference docs: every `symbol`+`file.py:NN`
    line anchor resolves within tolerance of the symbol's live def. Earn-the-red: at the
    pre-correction parent this REDs on HOOKS.md / SHARP_EDGES.md / hook-authoring.md (+twin);
    the resolver's own injection test (test_earn_the_red_stale_line_anchor_detected) proves
    the mechanism fires."""
    _check_line_anchors_fresh((REPO_ROOT / doc_rel).read_text(encoding="utf-8"))


# The vendored tree is a byte-identical copy of ``tools/cc/`` (parity is pinned by
# tests/test_package_resource_parity.py), so scanning it would report every finding
# twice and make each one-line fix read as two.
_ANCHOR_SCAN_PY_EXCLUDE_PREFIX = "espalier/_vendor/"


def _py_prose(source: str) -> str:
    """Comments + docstrings only, held at their original line positions.

    NOT the whole file, and the distinction is load-bearing rather than fastidious.
    A citation lives in prose; a ``path:NN`` inside an ordinary string literal is
    data. This module's own earn-the-red fixtures ARE deliberately-stale anchor
    strings -- ``test_earn_the_red_stale_line_anchor_detected`` here, and its twin
    in ``tests/test_ladder_claudemd_pointers.py`` -- so a whole-file scan reds on
    two fixtures whose staleness is the entire point of them. The only repair
    available at that point is an allowlist, and a gate that ships with an
    allowlist of its own findings is the born-weak shape this suite exists to
    catch (docs/FAILURE_MODES.md 2.8). Restricting the predicate to prose removes
    them structurally instead, which is why this helper exists at all.

    Line positions are preserved -- one output line per source line -- so the extracted
    prose stays line-aligned with its source and any position this module reports means
    something. This USED to be load-bearing: ``_FROZEN_ANCHORS`` keyed on the doc line a
    citation sat on, so a shifted extraction silently un-keyed a frozen war-story. That key
    is now the citation's text (ledger DEF-417i) and no consumer reads a doc position today,
    so the alignment is a property worth keeping rather than a contract someone depends on.
    Do not read it as dead: dropping it would make every future line this module prints wrong.
    """
    # Both anchor regexes require the literal `.py:` followed by a digit, so a source
    # carrying no such substring cannot contribute a match under either arm and the
    # tokenize+ast pass would be pure cost -- it is skipped for ~490 of the ~500 files
    # in the population, which is what keeps this module inside its <1s budget. This
    # short-circuit is COUPLED to that shared requirement: widening either regex to a
    # non-`.py` target means widening this test too, or the new targets are silently
    # never scanned.
    if ".py:" not in source:
        return ""
    keep: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                keep[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # unparseable file contributes no prose rather than failing collection
    try:
        # A scan is not an import: another module's invalid-escape SyntaxWarning is
        # that module's business, and re-emitting it once per consuming test turns one
        # honest warning into three misleading ones pointing at `<unknown>`.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            doc = ast.get_docstring(node, clean=False)
            if not doc or not node.body:
                continue
            start = node.body[0].lineno
            for offset, line in enumerate(doc.splitlines()):
                keep.setdefault(start + offset, line)
    total = source.count("\n") + 1
    return "\n".join(keep.get(n, "") for n in range(1, total + 1))


@functools.lru_cache(maxsize=None)
def _anchor_scan_text(rel: str) -> str:
    """The text the anchor arms read for one population member: the whole document
    for ``.md``, comments + docstrings only for ``.py`` (see ``_py_prose``).

    Cached because three tests in this module walk the same ~620-file population and
    would otherwise read and re-extract every one of them three times. Safe only
    because the population is git-TRACKED files that no test in this suite mutates
    (``conftest._no_live_tree_writes`` is the standing pin on that); a caller that
    ever needs to see edited content must clear the cache explicitly.
    """
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    return _py_prose(source) if rel.endswith(".py") else source


def _tracked_anchor_docs() -> list[str]:
    """Every git-tracked ``.md`` and ``.py`` file in the repo -- minus the out-of-domain
    ``_ANCHOR_SCAN_EXCLUDE_DOCS`` and the vendored byte-mirror
    ``_ANCHOR_SCAN_PY_EXCLUDE_PREFIX``.

    THERE IS NO ROOT TUPLE, DELIBERATELY. The population is the whole tracked tree by
    construction, so a surface nobody thought to declare -- root ``ESPALIER_MEMORY.md``,
    ``README.md``, the ``.claude/`` ladder that ships to every adopter -- is IN rather
    than invisible. It narrowed to four ``.md`` roots and three ``.py`` roots until
    2026-08-09, and its population pin restated the same two tuples: both sides shared
    the narrowing, so neither could see a surface outside the frame
    (docs/FAILURE_MODES.md 13.26 -- a duplication contract whose two sides are not
    independent). Measured at the widen: 626 -> 802 files for +0.06s, and two live
    blank-line citations in ``ESPALIER_MEMORY.md`` that had sat green since the arm was
    written. A narrowing is now reachable only by ADDING a named exclusion -- visible in
    review, and obliged to carry a reason.

    Uses ``git ls-files`` (NOT ``Path.rglob``) so gitignored scratch such as
    ``docs/session-archive.md`` -- which carries anchor-shaped matches -- is never
    scanned; only committed surface is guarded. Empty on a non-git tree (the caller
    SKIPS, fail-closed) rather than raising at collection.

    The ``.py`` side was added after measuring that Python comments and docstrings had
    NEVER been swept: 5 stale citations across 4 files were sitting green, including one
    pointing at line 370 of a 259-line file.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return sorted(
        f for f in out.split()
        if f not in _ANCHOR_SCAN_EXCLUDE_DOCS
        # Shipped task packs are dated plans, not live documentation; see the
        # note above _ANCHOR_SCAN_EXCLUDE_DOCS.
        and not is_shipped_pack(f)
        and (
            f.endswith(".md")
            or (
                f.endswith(".py")
                and not f.startswith(_ANCHOR_SCAN_PY_EXCLUDE_PREFIX)
            )
        )
    )


def test_tree_wide_line_anchors_fresh():
    """TP-373 3-A (Horn B): Mode 1 over the WHOLE git-tracked docs/+memory/ tree (+ asset
    twins), so a stale `symbol`+`file.py:NN` anchor reds *anywhere*, not just in the curated
    reference set -- closing the citation-rot class tree-wide. Anchors registered in
    _FROZEN_ANCHORS (past-tense war-stories) are skipped by their exact doc:line::symbol key.

    Single test + runtime enumeration + fail-closed skip (mirrors
    ``test_doc_test_citations.py::test_every_cited_test_file_exists``): a ``parametrize`` over
    the git result would generate ZERO cases in a non-git export and cover nothing SILENTLY --
    a false-green. Here an empty population SKIPS visibly, and every stale anchor is collected
    into one message instead of stopping at the first."""
    docs = _tracked_anchor_docs()
    if not docs:
        pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")
    failures: list[str] = []
    for rel in docs:
        try:
            _check_line_anchors_fresh(_anchor_scan_text(rel), doc_rel=rel)
        except AssertionError as exc:
            failures.append(f"{rel}: {exc}")
    assert not failures, (
        "tree-wide stale `symbol`+`file.py:NN` anchors (correct the line, or register a "
        "genuinely-frozen war-story in _FROZEN_ANCHORS):\n  " + "\n  ".join(failures)
    )


# A COLLAPSE DETECTOR, not a census. The live tree carries 854 tracked `.md`+`.py`
# (2026-08-09: 802 scanned + 3 named exclusions + 49 vendored). The floor sits well
# below that so ordinary churn never trips it, and its job is narrow: the closure
# assert below holds VACUOUSLY on an empty population (an empty scan closes over an
# empty tree), so something has to red BEFORE it. Every real narrowing is caught by
# closure, not by this number -- dropping the whole `.md` leg still leaves 582.
_MIN_ANCHOR_POPULATION = 500


def test_tree_wide_anchor_population_is_the_whole_tracked_tree():
    """TP-391 1-B / DEF-392d: pin the tree-wide guard's POPULATION, not just its verdict.

    ``test_tree_wide_line_anchors_fresh`` above asserts every scanned doc is fresh -- but
    nothing asserts the scanned set is actually tree-wide. Measured before this test existed:
    monkeypatching ``_tracked_anchor_docs`` to return ONE doc left it PASSING, and dropping the
    whole ``memory/`` prefix (116 docs -> 72) left it PASSING too. A guard that survives its own
    narrowing is a hand-list wearing a contract's label (docs/FAILURE_MODES.md 2.8).

    THIS IS A CLOSURE CONTRACT, NOT AN EQUALITY AGAINST A RESTATEMENT::

        every tracked .md/.py  ==  what the scan walks  +  what we excluded, with a reason

    It replaced (2026-08-09) a version that recomputed its "expected" set from a verbatim
    restatement of the subject's own ``md_roots``/``py_roots`` tuples, and argued for that
    restatement in capitals -- *THE DUPLICATION BELOW IS THE GATE*. Half of that was true: the
    restatement did catch a DROPPED root. It was structurally blind to a root that had never
    been DECLARED, because both sides narrowed identically -- a surface outside the frame was
    absent from the expectation exactly as it was absent from the scan. That is
    docs/FAILURE_MODES.md 13.26, a duplication contract whose two sides are not independent,
    and this test was its second live instance. Driven at the repair: the whole ``.claude/``
    ladder that ships to every adopter, all seven root docs (``ESPALIER_MEMORY.md``,
    ``README.md``, ...), plus ``scripts/``, ``bench/`` and ``examples/`` -- 176 files -- sat in
    neither side. Widening reached two blank-line citations in ``ESPALIER_MEMORY.md`` that had
    been green since the arm was written.

    WHAT IS STILL DELIBERATELY DUPLICATED, AND WHY IT IS INDEPENDENT NOW. This test re-types its
    own ``git ls-files`` call and restates the ``.md``/``.py`` extension rule rather than
    importing or sharing either. That reproduces the subject's DERIVATION from an independent
    angle instead of its NARROWING -- which is the distinction 13.26 turns on. The call carries
    NO pathspec, so there is no root list left for the two sides to share, and re-narrowing the
    subject pushes files into ``unaccounted`` here. Do not collapse this into a shared helper:
    sharing would move both sides together through the exact edit it exists to catch.

    THE EXCLUSION MAP IS THE ONE SHARED HALF, AND IT IS SHARED ON PURPOSE. Which files lie
    outside the resolver's domain is human judgement and cannot be derived from the tree, so
    both sides read the same constants. That is safe only because an exclusion is DECLARED --
    adding one is visible in review and obliged to carry a reason -- and because the self-expiry
    arm below deletes any that has stopped silencing something. Narrowing the scan is reachable
    ONLY through that declaration.

    Each mutation below was DRIVEN at the repair, not assumed (13.26: a guard observed only
    green has not been tested, it has been assumed)::

        subject re-narrowed to the old roots tuples  -> RED, 176 unaccounted
        subject drops the .py leg                    -> RED, 533 unaccounted
        subject drops just the memory/ root          -> RED, 197 unaccounted  (old pin: also RED)
        a tracked .md outside every old root         -> RED  (old pin: GREEN -- the blind spot)
        an exclusion naming no tracked file          -> RED on self-expiry
        an empty population                          -> RED on the floor, before closure

    Only the third of those was reachable by the version this replaced, so the new shape is
    strictly stronger rather than a trade.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("`git ls-files` unavailable -- not a dev tree / fresh clone")
    if not tracked:
        pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")

    population = {f for f in tracked if f.endswith(".md") or f.endswith(".py")}
    assert len(population) >= _MIN_ANCHOR_POPULATION, (
        f"the tracked .md/.py population is {len(population)}, below the floor of "
        f"{_MIN_ANCHOR_POPULATION}. The closure assert below would hold VACUOUSLY on a "
        "collapsed population, so this reds first. Either the enumeration broke, or the "
        "repo genuinely shed files and the floor moves DELIBERATELY, with a measurement."
    )

    named = set(_ANCHOR_SCAN_EXCLUDE_DOCS)
    vendored = {f for f in population if f.startswith(_ANCHOR_SCAN_PY_EXCLUDE_PREFIX)}
    plans = {f for f in population if is_shipped_pack(f)}
    excluded = named | vendored | plans
    scanned = set(_tracked_anchor_docs())
    # The plan exclusion must not be vacuous while packs ship: the ledger is
    # scanned, the packs beside it are not.
    if "task-packs/FORWARD_LEDGER.md" in population:
        assert "task-packs/FORWARD_LEDGER.md" in scanned
        assert plans, "the ledger is tracked but no shipped pack is -- re-derive the ship set"

    unaccounted = sorted(population - scanned - excluded)
    phantom = sorted(scanned - population)
    contradicted = sorted(scanned & excluded)
    assert not unaccounted and not phantom and not contradicted, (
        "the tree-wide anchor scan is no longer CLOSED over the tracked .md/.py tree.\n"
        f"  tracked {len(population)} = scanned {len(scanned)} + excluded {len(excluded)} "
        f"({len(named)} named + {len(vendored)} vendored + {len(plans)} shipped plans)\n"
        f"  TRACKED but neither scanned nor excluded ({len(unaccounted)}): {unaccounted[:10]}\n"
        f"  scanned but not tracked ({len(phantom)}): {phantom[:10]}\n"
        f"  scanned DESPITE being excluded ({len(contradicted)}): {contradicted[:10]}\n"
        "A file reaches the first list when the scan is narrowed. Do NOT narrow further to "
        "silence it: if it genuinely lies outside the resolver's domain, add it to "
        "_ANCHOR_SCAN_EXCLUDE_DOCS WITH A REASON, which is visible in review.\n"
        "Note: a docs/ file and its espalier/assets/docs/ twin are separate entries; "
        "excluding only one leg leaves the other scanned, which is intended, not a bug."
    )

    # Self-expiry: an exclusion that has stopped silencing anything is dead weight that still
    # reads as live judgement -- and the next author extends the list rather than pruning it.
    # On a release export an excluded doc can be absent by construction (an internal doc
    # the classifier withholds); that is not the exclusion going dead (DEF-670).
    stale = sorted(d for d in named if d not in population)
    stale = sorted(set(stale) - pruned_from_this_tree(stale))
    assert not stale, (
        f"_ANCHOR_SCAN_EXCLUDE_DOCS names {stale}, which no tracked .md/.py file matches -- "
        "the exclusion silences nothing. Delete the entry, or repoint it if the file moved."
    )
    assert vendored, (
        f"_ANCHOR_SCAN_PY_EXCLUDE_PREFIX {_ANCHOR_SCAN_PY_EXCLUDE_PREFIX!r} matches no tracked "
        "file -- the vendored byte-mirror moved or went away, so this carve-out now silences "
        "nothing while still reading as live judgement. Delete it, or repoint it."
    )


def test_earn_the_red_tree_wide_live_anchor_detected():
    """3-A earn-the-red (forward): the widened resolver still fires on a LIVE `.py:line` anchor
    whose cited line has drifted, and clears once corrected -- the tree-wide widen did not
    weaken the Mode-1 check, only broadened its population."""
    rel = "tests/test_catalog_self_consistency.py"
    sym = "_check_line_anchors_fresh"  # defined in THIS file
    stale = f"see `{sym}` (`{rel}:1`) for the resolver.\n"
    with pytest.raises(AssertionError, match="stale line anchor"):
        _check_line_anchors_fresh(stale, doc_rel="docs/SYNTHETIC.md")
    live = _symbol_def_lines(rel, sym)[0]
    fresh = f"see `{sym}` (`{rel}:{live}`) for the resolver.\n"
    _check_line_anchors_fresh(fresh, doc_rel="docs/SYNTHETIC.md")  # correct line -> no raise


def test_frozen_anchor_key_survives_an_edit_above_it(monkeypatch):
    """The re-key's earn-the-red (ledger DEF-417i), and it is SYNTHETIC on purpose.

    ``_FROZEN_ANCHORS`` is empty, so every live-tree assertion about it is vacuous; this
    drives the mechanism directly and keeps working at zero registered entries. It is the
    only proof the freeze still functions at all.

    The old key was positional in the citing doc, so inserting a line ABOVE a frozen
    citation shifted it, the key stopped matching, and the deliberately-historical anchor
    resurfaced as a failure in a file nobody had touched. Observed twice (465->475,
    204->212), plus once in the twin registry the magic-depth scanner used to carry.

    Three assertions, and the third is the one that stops this becoming a mute button:

      1. UNREGISTERED, the stale citation reds -- otherwise the freeze proves nothing.
      2. REGISTERED, it greens, AND STAYS green after 400 lines are inserted above it.
         Under the old key that insertion alone re-armed the failure.
      3. REGISTERED, a REWORDED citation reds again. A key that can never lapse is an
         unconditional silence, not an allowlist.
    """
    doc = "docs/SYNTHETIC.md"
    rel = "tests/test_catalog_self_consistency.py"
    sym = "_check_line_anchors_fresh"  # defined in THIS file
    cited_line = 1  # deliberately wrong; the symbol is nowhere near line 1
    text = f"see `{sym}` (`{rel}:{cited_line}`) for the resolver.\n"
    key = f"{doc}::{sym}::{rel}:{cited_line}"

    # (1) unregistered -> reds
    with pytest.raises(AssertionError, match="stale line anchor"):
        _check_line_anchors_fresh(text, doc_rel=doc)

    monkeypatch.setattr(
        sys.modules[__name__], "_FROZEN_ANCHORS", frozenset({key})
    )

    # (2) registered -> green, and an edit ABOVE it changes nothing
    _check_line_anchors_fresh(text, doc_rel=doc)
    _check_line_anchors_fresh("filler\n" * 400 + text, doc_rel=doc)

    # (3) but rewording the citation lapses the freeze
    moved = f"see `{sym}` (`{rel}:{cited_line + 1}`) for the resolver.\n"
    with pytest.raises(AssertionError, match="stale line anchor"):
        _check_line_anchors_fresh(moved, doc_rel=doc)


def test_frozen_anchors_are_genuinely_stale():
    """3-A earn-the-red (baseline): each _FROZEN_ANCHORS doc reds with the baseline OFF
    (doc_rel=None) and greens with it ON -- the baseline masks only genuinely-stale registered
    war-stories, never a live-correctable anchor. If a registered anchor is ever fixed in place
    (resolves cleanly), the baseline-ON pass still holds but the baseline-OFF raise flips, so
    this reds and the stale _FROZEN_ANCHORS entry gets pruned. That is exactly what happened on
    2026-08-09: converting both citations flipped both raises and emptied the set.

    THE EMPTY CASE IS ASSERTED, NOT SKIPPED. A `for` loop over an empty registry passes while
    checking nothing -- docs/FAILURE_MODES.md 13.25, a guard whose population dropped to zero.
    So emptiness is a branch with its own assertion rather than a silent no-op, and the two
    states are mutually exclusive by construction.
    """
    if not _FROZEN_ANCHORS:
        # §C21/`DEF-571`. The docstring above floors the REGISTRY being empty and
        # builds this whole branch for it -- then the branch's own population can
        # be empty too, and nothing asked. `_tracked_anchor_docs()` returns `[]`
        # both when git errors (rc 128) AND when it answers rc 0 with zero rows
        # inside a gitignored directory, so `live` is `[]` and this passes having
        # read nothing. The sibling at :771 already floors the identical
        # population at _MIN_ANCHOR_POPULATION; this arm simply never got one.
        #
        # ⚠ Found by STATIC CENSUS, not by measurement: it is silent at BOTH
        # extraction locations, so the two-location diff that caught its four
        # siblings is structurally blind to it -- a differential finds only what
        # DIFFERS. Recorded because the next reader will reasonably assume the
        # measurement was exhaustive.
        docs = _tracked_anchor_docs()
        assert len(docs) >= _MIN_ANCHOR_POPULATION, (
            f"anchor population collapsed to {len(docs)} (floor "
            f"{_MIN_ANCHOR_POPULATION}) -- a shallow checkout, or a tree whose "
            "git context is not its own. The empty-registry assertion below "
            "would pass having scanned nothing."
        )
        live = [
            rel for rel in docs
            if _BARE_LINE_ANCHOR_RE.search(_anchor_scan_text(rel))
            and rel not in _ANCHOR_CONVERSION_RESIDUE
        ]
        assert not live, (
            "_FROZEN_ANCHORS is empty, which asserts that no doc still needs a historical "
            "line anchor tolerated -- but these carry live `path:NN` anchors outside the "
            f"documented residue: {live}. Convert them, add them to _ANCHOR_CONVERSION_RESIDUE "
            "with a reason, or register a genuinely-historical one here."
        )
        return

    # Keys are `<doc>::<symbol>::<file>:<line>` -- split on the `::` separator, not on the
    # first bare colon, which would also match the one inside the cited `<file>:<line>`.
    frozen_docs = {key.split("::", 1)[0] for key in _FROZEN_ANCHORS}
    for doc_rel in sorted(frozen_docs):
        text = (REPO_ROOT / doc_rel).read_text(encoding="utf-8")
        with pytest.raises(AssertionError):  # baseline OFF -> the registered-stale anchor reds
            _check_line_anchors_fresh(text)
        _check_line_anchors_fresh(text, doc_rel=doc_rel)  # baseline ON -> skipped, GREEN


# ── Mode 3: the SYMBOL-LESS arm ──────────────────────────────────────────────
#
# Mode 1's `_LINE_ANCHOR_RE` pairs a backticked SYMBOL with a `file.py:NN`
# anchor across a gap that forbids a sentence break, because it resolves the
# anchor BY looking that symbol up in the AST. That predicate -- not the tree
# walk -- is what bounds the class it closes. An anchor a sentence boundary away
# from any symbol is unreachable no matter how wide the doc population gets:
#
#     **`ESPALIER_AUDIT_DIR` isolation pattern.** The autouse fixture in
#     `tests/conftest.py::_isolate_audit_dir` redirects ...
#
# The `pattern.**` period sits between symbol and anchor, so the pair never
# matches. Widening the population from 4 docs to 116 did not and could not
# help. This arm resolves a bare anchor on its own merits instead.
#
# It is deliberately a SEPARATE arm rather than a widening of `_LINE_ANCHOR_RE`:
# that regex is shared by six test functions across three files
# (`test_ladder_claudemd_pointers.py`, `test_memory_anchor_freshness.py`, and
# four here), so widening it in place changes five already-green checks at once.
# A separate arm carries its own earn-the-red, its own floor, and its own
# stated exclusions.
_BARE_LINE_ANCHOR_RE = re.compile(
    r"`(?P<file>[\w./-]+\.py):(?P<line>\d+)(?:-(?P<end>\d+))?`"
)

# A RATCHET, and it only ever moves DOWN. Was a floor (`_MIN_BARE_ANCHORS = 20`,
# "at least 20 anchors were evaluated") until 2026-08-09; the sign is inverted
# because the goal changed from policing this citation form to retiring it.
#
# WHY: a `path:NN` anchor rots on ANY edit above the cited line -- silently, and
# constantly. A `path::symbol` reference rots only on a rename, which is a
# deliberate act that greps. Measured across the two UNGUARDED populations:
# `docs/known-findings.md` carries 362 `:NN` anchors of which 26 are broken
# (7.2%), while the tree carries 336 `::symbol` refs of which 4 are broken
# (1.2%, and at least two of those are a deliberate placeholder and a past-tense
# war-story). Converting buys ~6x less rot with no guard at all, so the guard's
# job is now to stop the fragile form coming back, not to chase it forever.
#
# IT COUNTS MATCHES, NOT EVALUATIONS -- the exact inverse of what the floor
# counted, and deliberately. A floor HAD to count evaluations: a resolver that
# answered "missing" for everything left the regex matching while the predicate
# checked nothing, so counting matches would have called that full coverage. A
# ceiling has the opposite duty: an anchor that fails to resolve is still an
# anchor we do not want, so it must count against the cap. Lower this number
# whenever a batch is converted; never raise it.
#
# 77 -> 20 -> 7 (2026-08-09). First 57 anchors carrying an enclosing symbol converted to
# `path::symbol`; then 13 more, split by what the cited line actually held: 4 named a real
# symbol and converted, 9 pointed at a COMMENT, an import or a decorator -- prose has no
# name, so there was nothing to convert to and they were de-anchored to the bare filename.
#
# THE REMAINING 7 ARE A FLOOR, NOT A BACKLOG. Every one of them is documentation ABOUT this
# citation form, and prose that explains a form has to exhibit it. Converting them would
# destroy the thing they document. Do not "fix" them; see `_ANCHOR_CONVERSION_RESIDUE`.
_MAX_BARE_ANCHORS = 7

# The residue, by file, with the reason each is irreducible. This is an exclusion map in the
# sense of `test_tree_wide_anchor_population_is_the_whole_tracked_tree`: human judgement that
# cannot be derived, declared so that adding to it is visible in review. It is NOT consulted
# by the ceiling -- the ceiling counts every anchor including these, so growth still reds.
_ANCHOR_CONVERSION_RESIDUE = {
    # The resolver's own worked examples. run_benchmark.py:1859 is the canonical
    # "filename token before a .py anchor is NOT a symbol->def anchor" case, and
    # cognitive_blueprint.py:212 the canonical ambiguous-basename case. Both appear in
    # comments explaining why the predicate SKIPS them -- rewrite them and the comments
    # stop describing the code.
    "tests/test_catalog_self_consistency.py": "the predicate's own worked examples (5)",
    # Literally the counter-example in a doc whose subject is this failure: the sentence
    # reads "cite TestX in tests/test_y.py, NOT tests/test_y.py:58". The anchor is the
    # thing being argued against.
    "docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md": "the doc's counter-example",
    # A synthetic placeholder in a definition -- "you are fixing an instance when the work
    # is described by a site, foo.py:412. No such file exists, by design.
    "memory/fix-the-class-not-the-instance.md": "synthetic placeholder, no such file",
}


def _check_bare_line_anchors_resolve(
    text: str, doc_rel: str | None = None
) -> tuple[int, list[str]]:
    """Mode 3: every bare backticked ``path:NN`` / ``path:NN-MM`` anchor points
    at a line that exists and carries content.

    Raising form; returns ``(checked, skipped)`` when clean. The predicate
    itself lives in ``_bare_anchor_findings`` so the census can still count what
    a REDDENING doc walked.

    WHAT THIS ARM CHECKS -- the whole list, because a class-close claim is
    scoped by its PREDICATE, not by its tree walk, and the two previous
    closures of this class over-claimed by describing the traversal instead:

      1. the cited line exists in the cited file;
      2. the cited line is not blank.

    WHAT IT DOES NOT REACH, stated so no one reads this as a full class close:

      * **An anchor that drifted onto a different NON-blank line.** With no
        symbol to look up there is nothing to compare the line's content
        against. This is the commonest drift and it stays uncovered. A ``:NN``
        in prose is rot-in-waiting regardless -- see
        ``docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md``.
      * **An anchor whose file does not resolve at all** -- skipped, not
        failed, and this is the sharpest hole in the arm. A bare path with
        neither a symbol nor a resolvable file carries no evidence it was ever
        a citation (the live population's one instance is an illustrative
        counter-example in a doc about citation rot). But a RENAME produces the
        same status, so the commonest way a citation dies removes the anchor
        from this arm's population instead of reddening it -- and Mode 1 fails
        that exact status. The two arms disagree on purpose; the asymmetry is
        the price of having no symbol to corroborate with. ``_skipped_anchors``
        is returned by the census so a test can pin the skip list rather than
        let it drift silently.
      * **An anchor whose basename is AMBIGUOUS** (the same filename under two
        source roots). ``_resolve_source`` is called with no symbol here, so its
        disambiguation branch is unreachable and every such anchor returns
        ``"ambiguous"`` and is skipped. Counted in the skip list for the same
        reason.
      * **A prose claim carrying no anchor at all.** Unreachable by any anchor
        resolver, symbol-based or not.

    And the POPULATION exclusions, which belong in this list for exactly the
    reason the list exists -- the previous closures over-claimed by describing
    the traversal, and omitting the traversal's limits from a predicate list is
    the same error rotated:

      * The env-var catalog (+ its twin) is outside the scanned population --
        see ``_ANCHOR_SCAN_EXCLUDE_DOCS``, which states why: it is out of this
        resolver's domain. (The fan-out findings corpus was the other exclusion,
        as a RECORD SURFACE whose anchors were dated snapshots of where a
        finding was; it retired to the record branch 2026-09-21, and a count of
        its broken anchors was never a defect count -- see
        memory/classify-the-surface-before-measuring-it.md.)
      * Only ``*.md`` under ``docs/``, ``memory/`` and the asset twins is
        scanned, so a root-level doc is invisible here even when Mode 1 covers
        it.
      * The regex matches ``.py`` anchors only; ``.md`` / ``.toml`` / ``.js``
        anchors in the same docs are unchecked by either arm.

    Why "not blank" earns a gate on its own: an anchor pointing at whitespace is
    never what an author meant, so the false-positive rate is structurally zero
    -- nobody deliberately cites a blank line. Every live instance found when
    this arm landed was off-by-one drift onto the blank line directly above the
    thing the surrounding prose described.
    """
    checked, skipped, problems = _bare_anchor_findings(text)
    where = f"{doc_rel}: " if doc_rel else ""
    assert not problems, where + "; ".join(problems)
    return checked, skipped


def _bare_anchor_findings(text: str) -> tuple[int, list[str], list[str]]:
    """``(checked, skipped, problems)`` -- the Mode 3 predicate with no
    assertion, so a caller can read the counts whether or not it reds."""
    problems: list[str] = []
    checked = 0
    skipped: list[str] = []
    for m in _BARE_LINE_ANCHOR_RE.finditer(text):
        file_ref, start = m.group("file"), int(m.group("line"))
        end = int(m.group("end")) if m.group("end") else None
        src, status = _resolve_source(file_ref, None)
        if status != "ok" or src is None:
            skipped.append(f"{file_ref}:{start} ({status})")
            continue  # stated exclusion -- see the docstring
        # errors="replace" because this predicate only needs a line count and
        # `.strip()` truthiness: one non-UTF-8 byte in one cited source file
        # would otherwise raise out of the whole tree-wide gate with a
        # traceback instead of naming the doc that carries the bad anchor.
        lines = (REPO_ROOT / src).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        checked += 1
        # Both ends of a `NN-MM` span are checked: a span whose END overruns the
        # file is as broken as one whose start does, and `:22-9999` would
        # otherwise pass on the strength of its start line alone.
        for label, cited in (("", start), ("span end ", end)):
            if cited is None:
                continue
            # `\d+` admits 0, and line numbers are 1-based -- without the lower
            # bound `lines[0 - 1]` silently reads the LAST line of the file and
            # a `:0` anchor passes.
            if cited < 1 or cited > len(lines):
                problems.append(
                    f"`{file_ref}:{start}` {label}cites line {cited} but {src} "
                    f"has {len(lines)} lines (1-based)"
                )
                continue
            if not lines[cited - 1].strip():
                nearest = min(
                    (n for n, t in enumerate(lines, start=1) if t.strip()),
                    key=lambda n: abs(n - cited),
                    default=cited,
                )
                problems.append(
                    f"`{file_ref}:{start}` {label}points at a BLANK line "
                    f"({cited}) in {src}; the nearest line carrying content is "
                    f"{nearest} ({lines[nearest - 1].strip()[:60]!r})"
                )
    return checked, skipped, problems


def _bare_anchor_census(docs: list[str]) -> tuple[int, list[str], list[str]]:
    """``(anchors CHECKED, anchors skipped, per-doc failures)`` for Mode 3.

    Reports what the predicate actually EVALUATED, not what the regex matched.
    Those differ, and the difference is the whole value of the count: a
    regression in ``_resolve_source`` -- shared with Mode 1 and six other
    consumers -- makes every anchor resolve to ``"missing"``, at which point the
    regex still matches 40 tokens while the gate evaluates zero of them. Counting
    matches would call that full coverage.
    """
    checked = 0
    skipped: list[str] = []
    failures: list[str] = []
    for rel in docs:
        text = _anchor_scan_text(rel)
        try:
            c, s = _check_bare_line_anchors_resolve(text, doc_rel=rel)
        except AssertionError as exc:
            failures.append(str(exc))
            c, s, _ = _bare_anchor_findings(text)  # a reddening doc was still walked
        checked += c
        skipped += s
    return checked, skipped, failures


def test_tree_wide_bare_line_anchors_resolve():
    """Mode 3 over the whole tracked tree: the surviving `path:NN` anchors resolve,
    and the tree carries no MORE of them than the ratchet allows.

    Two assertions with different jobs. The ceiling retires the citation form; the
    resolve-check keeps the ones still in flight honest until they are converted.

    THE CEILING COUNTS MATCHES, NOT EVALUATIONS -- see ``_MAX_BARE_ANCHORS``. It is
    asserted BEFORE the failures because a converted tree eventually reports "no
    failures" trivially, and a bare "no failures" must never be the only signal.

    WHERE COLLAPSE DETECTION WENT. The floor this replaced doubled as the detector for
    a broken regex, a broken ``_resolve_source``, or a shrunken doc population. A
    ceiling cannot do that job -- every one of those failures makes the count go DOWN,
    which a ceiling reads as success. So the three moved, deliberately and separately:

      * doc population shrank -> ``test_tree_wide_anchor_population_is_the_whole_tracked_tree``
        (closure against ``git ls-files``, with its own floor)
      * regex or resolver broke -> ``test_earn_the_red_bare_anchor_on_a_blank_line`` and
        ``test_earn_the_red_bare_anchor_beyond_end_of_file``, which drive SYNTHETIC
        anchors and so keep working at zero live anchors --
        ``test_resolver_collapse_is_caught_by_the_synthetic_arms`` pins that dependency

    That division matters once the ratchet reaches zero: at that point this test has no
    live anchors left to evaluate, and the synthetic arms are the ONLY thing standing
    between a silently-broken predicate and a green run.
    """
    docs = _tracked_anchor_docs()
    if not docs:
        pytest.skip("`git ls-files` yielded nothing -- not a dev tree / fresh clone")
    checked, skipped, failures = _bare_anchor_census(docs)
    matched = checked + len(skipped)
    assert matched <= _MAX_BARE_ANCHORS, (
        f"the tree carries {matched} bare `path:NN` anchors across {len(docs)} files, "
        f"ABOVE the ratchet of {_MAX_BARE_ANCHORS}. This citation form is being retired: "
        "a line number rots on any edit above it, so a new one is a regression even when "
        "it is correct today. Cite the symbol instead -- `path/to/file.py::symbol` -- "
        "which rots only on a rename. If a batch was just converted, LOWER "
        "_MAX_BARE_ANCHORS to the new count in the same commit; never raise it."
    )
    assert not failures, (
        "bare `path:NN` anchors pointing at nothing (convert to `path::symbol`, or "
        "correct the line to the reported nearest content line):\n  " + "\n  ".join(failures)
    )


def test_earn_the_red_bare_anchor_on_a_blank_line():
    """Mode 3 fires on an anchor pointing at whitespace and clears when
    re-pointed at content -- the mutation that proves the arm, run against THIS
    file so it cannot rot."""
    rel = "tests/test_catalog_self_consistency.py"
    lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
    blank = next(n for n, t in enumerate(lines, start=1) if not t.strip())
    content = next(n for n, t in enumerate(lines, start=1) if t.strip())
    with pytest.raises(AssertionError, match="BLANK line"):
        _check_bare_line_anchors_resolve(f"see `{rel}:{blank}` for it.\n")
    _check_bare_line_anchors_resolve(f"see `{rel}:{content}` for it.\n")


def test_earn_the_red_bare_anchor_beyond_end_of_file():
    """Mode 3's second, orthogonal mutation: a cited line past EOF.

    Orthogonal to the blank-line red because it exercises the other branch. It
    is also the mutation that REPLACES the one this arm cannot have: re-pointing
    a corrected anchor N lines off does NOT red here (measured), because a
    re-pointed anchor almost always lands on another non-blank line -- the
    uncovered shape named in the predicate's docstring.
    """
    rel = "tests/test_catalog_self_consistency.py"
    n = len((REPO_ROOT / rel).read_text(encoding="utf-8").splitlines())
    with pytest.raises(AssertionError, match="1-based"):
        _check_bare_line_anchors_resolve(f"see `{rel}:{n + 1000}` for it.\n")


def test_earn_the_red_bare_anchor_line_zero():
    """`:0` must red. Line numbers are 1-based but ``\\d+`` admits 0, and
    ``lines[0 - 1]`` reads the LAST line of the file -- so without an explicit
    lower bound a `:0` anchor passes by wrapping around, which is how a
    0-indexed generator would mint one."""
    rel = "tests/test_catalog_self_consistency.py"
    with pytest.raises(AssertionError, match="1-based"):
        _check_bare_line_anchors_resolve(f"see `{rel}:0` for it.\n")


# RETIRED 2026-08-09: `test_bare_anchor_floor_reds_on_a_shrunken_doc_set` asserted that a
# one-doc population fell under `_MIN_BARE_ANCHORS`, i.e. that the floor discriminated a
# narrowed scan from a tree-wide one. The floor is now a ceiling, which a narrowed scan
# SATISFIES rather than trips, so the assertion could only ever pass -- a test that cannot
# fail, which is the shape this suite exists to catch. Its duty moved wholesale to
# `test_tree_wide_anchor_population_is_the_whole_tracked_tree`, whose closure contract
# catches a narrowing of any size (the old floor only caught narrowings below ~3 docs).


def test_bare_anchor_census_routes_every_doc_through_the_checker():
    """The census's value is the CALL, not the count beside it.

    Mutation that motivated this test: drop the
    ``_check_bare_line_anchors_resolve`` call from ``_bare_anchor_census`` and
    keep the tally. Measured -- every other Mode 3 test stayed GREEN, because
    both earn-the-red tests invoke the checker DIRECTLY and so witness the
    helper's body while never witnessing the wiring. A fix that is "a helper
    plus a call to it" has two failure surfaces, and the one the tests naturally
    aim at is the wrong one.
    """
    calls: list[str | None] = []
    real = _check_bare_line_anchors_resolve

    def spy(text, doc_rel=None):
        calls.append(doc_rel)
        return real(text, doc_rel=doc_rel)

    globals()["_check_bare_line_anchors_resolve"] = spy
    try:
        _bare_anchor_census(["docs/CONVENTIONS.md", "docs/SHARP_EDGES.md"])
    finally:
        globals()["_check_bare_line_anchors_resolve"] = real
    assert calls == ["docs/CONVENTIONS.md", "docs/SHARP_EDGES.md"], (
        "_bare_anchor_census no longer routes each doc through "
        f"_check_bare_line_anchors_resolve (saw {calls!r})"
    )


def test_resolver_collapse_is_caught_by_the_synthetic_arms():
    """A resolver collapse must still red once the ratchet reaches zero.

    ``_resolve_source`` is shared with Mode 1 and six other consumers. If it starts
    answering ``"missing"`` for everything, every anchor is SKIPPED rather than checked:
    the tree-wide arm finds no failures, and the ceiling -- which counts matches -- is
    satisfied by a number that only moved down. Nothing in the live-tree walk reds.

    The floor used to be that detector, and a floor cannot survive the ratchet: at zero
    live anchors there is nothing left to count. So the duty now rests entirely on the two
    SYNTHETIC earn-the-red arms, which drive anchors the tree does not have to contain.
    This test pins that dependency instead of leaving it as a comment, because the
    dependency is invisible at the call site -- someone deleting an "earn the red" test as
    redundant would silently remove the last collapse detector in this arm.

    It asserts the mechanism in both directions: healthy resolver -> the predicate rejects
    a bad anchor; collapsed resolver -> it stops rejecting, which is exactly the condition
    that reds ``test_earn_the_red_bare_anchor_on_a_blank_line``.
    """
    rel = "tests/test_catalog_self_consistency.py"
    lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
    blank = next(n for n, t in enumerate(lines, start=1) if not t.strip())
    bad_anchor = f"see `{rel}:{blank}` for it.\n"

    with pytest.raises(AssertionError, match="BLANK line"):
        _check_bare_line_anchors_resolve(bad_anchor)

    real = _resolve_source
    globals()["_resolve_source"] = lambda file_ref, symbol=None: (None, "missing")
    try:
        checked, skipped = _check_bare_line_anchors_resolve(bad_anchor)
        live_checked, live_skipped, live_failures = _bare_anchor_census(
            _tracked_anchor_docs()
        )
    finally:
        globals()["_resolve_source"] = real

    assert checked == 0 and skipped, (
        "with the resolver collapsed the predicate should evaluate nothing and skip the "
        f"anchor, got checked={checked} skipped={skipped!r}"
    )
    assert live_checked == 0 and not live_failures, (
        "a collapsed resolver is invisible to the live-tree walk -- that is the premise "
        f"of this test, and it no longer holds (checked={live_checked}, "
        f"failures={len(live_failures)}). Re-derive where collapse detection now lives."
    )
    assert live_checked + len(live_skipped) <= _MAX_BARE_ANCHORS, (
        "and the ceiling is SATISFIED by the collapse, which is why it cannot be the "
        "detector -- if this ever reds, the ceiling has grown teeth it is not designed "
        "to have and this test's reasoning needs re-deriving"
    )
