"""TP-364: every task-packs/Deferred/ pack is pinned to a FORWARD_LEDGER.md row.

A pack authored and parked in ``task-packs/Deferred/`` without a
``FORWARD_LEDGER.md`` reference is invisible to the single forward tracker --
exactly how TP-338 and TP-342 drifted for ~3 days across a reflatten that
claimed completeness. Hand-audits miss the class because they enumerate the
ledger's own ID set, not the ``Deferred/`` *folder*; a pack whose intent never
reached the ledger cannot show up as an ID-diff
(``memory/completeness-gate-must-discover-its-population.md``). This contract
makes the folder the population, so an untracked Deferred pack REDs instead of
silently drifting -- the recurrence guard for the orphan class the 2026-07-26
deep-dive review surfaced.

The population is every ACTIVE pack: the root of ``task-packs/`` (the packs
that ship) plus ``Deferred/`` (drafted packs held; they ship too since the
2026-09-20 ruling in TP-452 1-D). Until then the population was ``Deferred/``
alone and the live check was gated on that folder existing -- so it skipped on
exactly the tree it ships to, where ``Done/`` and its siblings never exist
(TP-452 Task 0's measured fail-open). The gate is the ledger alone now; an
absent ``Deferred/`` is an empty population, not a skip. The detector is
factored into ``_orphans(pack_dirs, ledger)`` so the earn-the-red drives a
synthetic tmp tree, never the live folder (mutating the live tree is the
strand-a-file anti-pattern).
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_PACKS = _ROOT / "task-packs"
_DEFERRED = _PACKS / "Deferred"
_LEDGER = _PACKS / "FORWARD_LEDGER.md"
_DONE = _PACKS / "Done"
#: The orphan guard's population: every folder whose packs are ACTIVE and ship.
#: Never Done/, Merged/ or Scrapped/ -- landed and dead work leaves the ledger
#: by contract rule 3, and the reverse guard (TestLandedRowLingering) is the
#: one that reads Done/. A folder absent from the tree is an empty population.
_ACTIVE_PACK_DIRS: tuple[Path, ...] = (_PACKS, _DEFERRED)  # re-bound below from the one home

# The recurrence guard (below) reuses the canonical Landing-stanza parser
# (scripts/check_pack_landing.landed_state) instead of a rival regex, so
# "is this pack landed?" is answered in ONE place -- scoped to the ``## Landing``
# stanza and tolerant of a bold ``**State:**`` value, which a bare
# ``re.search(r"State: LANDED")`` is not (it false-matches a prose / code-block
# ``State: LANDED`` decoy in a pack whose real stanza is DRAFT/SCRAPPED). scripts/
# is self-host dev tooling (absent from the sdist) and task-packs/Done/ is likewise
# self-host, so the guarded import and the tests that need it skip together off-host.
# The plain import (after a sys.path insert) mirrors tests/test_check_pack_landing.py's
# established idiom; check_pack_landing is a standalone scripts/ tool, not a tools/cc/
# module, so the spec_from_file_location rule (tests/CLAUDE.md) does not apply.
_CHECK_PACK_LANDING = _ROOT / "scripts" / "check_pack_landing.py"
if _CHECK_PACK_LANDING.is_file():
    sys.path.insert(0, str(_ROOT / "scripts"))
    from check_pack_landing import active_pack_dirs as _active_pack_dirs  # noqa: E402
    from check_pack_landing import landed_state as _landed_state  # noqa: E402
    from check_pack_landing import pack_files as _shared_pack_files  # noqa: E402
    from check_pack_landing import scope_out as _scope_out  # noqa: E402
    # One home for "which packs are in flight": the strike guard reads it through
    # the same function, so a folder added there reaches guard and gate together
    # (code review, 2026-09-21: the tuple above was a second hand-kept copy).
    _ACTIVE_PACK_DIRS = _active_pack_dirs(_PACKS)
else:  # adopter / fresh clone: dev tooling absent -> the recurrence-guard tests skip
    _landed_state = None
    _shared_pack_files = None
    _scope_out = None


def _pack_files(pack_dirs: Path | Iterable[Path]) -> list[Path]:
    """Every pack file (``.md``/``.markdown``, case-insensitive, ``tp-`` stem)
    directly under each of ``pack_dirs``; a directory that does not exist
    contributes nothing. One walk, shared by the detector and its baseline."""
    dirs = [pack_dirs] if isinstance(pack_dirs, Path) else list(pack_dirs)
    return sorted(
        p for d in dirs if d.is_dir() for p in d.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".md", ".markdown"}
        and p.stem.lower().startswith("tp-")
    )


def _orphans(pack_dirs: Path | Iterable[Path], ledger: Path) -> list[str]:
    """Active packs (``.md``/``.markdown``, case-insensitive) with no anchored ``FORWARD_LEDGER.md`` reference.

    ``pack_dirs`` is the folder (or folders) whose packs are the population --
    the SoT, never a hand-maintained list, which would recreate the very drift
    class. The live check passes ``_ACTIVE_PACK_DIRS``; a folder that does not
    exist is an empty population, so the check runs on a tree with no
    ``Deferred/`` instead of skipping. Each folder is scanned via ``iterdir()`` with
    explicit suffix/stem checks (not ``glob("TP-*.md")``) so an off-convention
    orphan -- a lowercase ``tp-`` prefix or a ``.markdown`` extension -- cannot
    silently escape (TP-372). The full ``TP-<n>`` token *including any alpha
    suffix* is matched on a word boundary, so ``TP-233b`` never truncates to a
    sibling-matching ``TP-233``; the ledger search is case-insensitive so a
    lowercase ``tp-999`` file resolves to a canonical ``TP-999`` row, and the
    token is reported as-captured. A bare ``<n>`` substring is deliberately NOT
    accepted: for an orphan *detector* the dangerous direction is a false-GREEN
    (an orphan wrongly counted as tracked), and a bare number false-matches
    inside commit hashes / dates / counts. A filename that carries no ``TP-<n>``
    token at all is itself un-trackable, so it is reported by name rather than
    silently skipped (nothing escapes the net).
    """
    text = ledger.read_text(encoding="utf-8")  # first: an absent ledger is an error, never an empty answer
    missing: list[str] = []
    # Population = every markdown file named on the TP- convention directly
    # under each folder, scanned case-INSENSITIVELY across .md/.markdown. A bare
    # glob("TP-*.md") let an off-convention orphan escape uncounted: a
    # `.markdown` extension (never matched by glob("TP-*.md") on any filesystem)
    # or a lowercase `tp-` name (glob-caught only on case-insensitive
    # filesystems, so that escape is platform-dependent). iterdir + explicit
    # suffix/stem checks close both (`_pack_files`).
    for pack in _pack_files(pack_dirs):
        m = re.match(r"(TP-\d+[a-z]*)", pack.name, re.IGNORECASE)  # suffix included
        if m is None:  # a tp-*.md* with no parseable TP-<n> token
            missing.append(pack.name)
            continue
        tok = m.group(1)  # AS-CAPTURED -- preserves the alpha suffix's case
        # Case-INSENSITIVE ledger search so a lowercase `tp-999` file resolves to
        # a canonical `TP-999` row (and `TP-233b` to a `TP-233b` row). The token
        # is reported AS-IS, never .upper()-normalized: a whole-token .upper()
        # would red-lock the 4 live Deferred packs whose ledger rows carry a
        # lowercase alpha suffix (TP-203a/203b/233b/321d) and break
        # test_alpha_suffix_not_truncated_to_sibling's ["TP-233b"] contract.
        if not re.search(rf"\b{re.escape(tok)}\b", text, re.IGNORECASE):  # anchored
            missing.append(tok)
    return missing


# The ledger's landed-row tag vocabulary (the SoT for this reverse-direction
# guard). Distinct job from ``check_pack_landing`` -- that reads a *pack's* Landing
# stanza; this reads the *ledger's* references to packs. Kept local for that reason.
# TP-391 2-A: the optional `[^)\s]*/` segment accepts a FOLDER-QUALIFIED id --
# `drafted-pack (Deferred/TP-N)` -- which is a live tag shape the original pattern
# missed entirely (it required `\s*TP-` straight after the paren). Measured at the
# time: three live rows used the blind form, so each would have gone untracked when
# its pack landed, while the docstring below advertised "the ledger's own tag set".
# The segment is `[^)\s]*` so it cannot run past the closing paren into an unrelated
# parenthetical; a `drafted-pack (Deferred/, harvested ...)` row carrying NO id still
# correctly does not match.
_LANDED_TAG_RE = re.compile(
    r"(?:LANDED|owned:\s*|drafted(?:-pack)?\s*\(\s*(?:[^)\s]*/)?)\s*(TP-\d+[a-z]*)"
)

# The member-table ID CELL -- the row shape that actually ACCUMULATES in this file,
# and the one `_LANDED_TAG_RE` above cannot read. That pattern matches PROSE tags
# (`LANDED`, `owned:`, `drafted-pack (...)`); a member row's first cell is nothing but
# backticked ids and carries no prose tag at all.
#
# SCOPE, STATED HONESTLY: this reads an OWNERSHIP PAIR -- `| `DEF-n` `TP-m` |`, "defect
# DEF-n, owned by pack TP-m" -- and nothing else. It is NOT a general "TP id in the id
# cell" scan, and the leading-id group is `+` rather than `*` on purpose.
#
# A SOLO `| `TP-330` |` FIRST CELL IS DELIBERATELY OUT OF SCOPE, and this is the
# non-obvious half. There the pack id is the DEFECT IDENTIFIER -- "the TP-330 residual
# class" -- not a pointer to an owner. Whether that pack landed says nothing about
# whether the residual closed. Measured when this was widened to `*` during review: it
# flagged exactly three such rows, and reading all three showed every one to be LIVE
# open work (one says in so many words that its residuals "all reproduce"). Striking
# them on the strength of a landed owner would have erased real backlog. The narrower
# form finds fewer rows because fewer rows are the thing this guard is about.
#
# Honest coverage note, so nobody re-derives it: this pattern matches a single-digit
# number of rows in a ~2900-line ledger. That is correct -- the ownership-pair shape is
# genuinely rare -- but do NOT read the comment above as "the id-cell doorway is now
# closed". The solo-TP population (33 rows) is out of scope BY DESIGN, not by oversight.
#
# ANCHORED to `^|` so a TP id in the row's WHAT cell, or in prose, is untouched --
# those are REFERENCES, not ownership tags. `(?:\s*\d+\s*\|)?` accepts the numbered
# section shape (`| 3 | `DEF-x` `TP-y` | ...`).
#
# NO STRIKETHROUGH ARM, DELIBERATELY. `~~` is this ledger's own "handled" marker, so
# matching THROUGH it would re-report rows already struck correctly. This function's
# contract is rows "never struck"; a struck cell is therefore not a match, by design.
# Adding a `~~` arm reads like a widening and is a false-positive generator.
#
# RESIDUAL, KNOWN, NOT CLOSED: a marker sitting BETWEEN two ids in the cell
# (`` | `DEF-9` **gate** `TP-8` | ``) is still missed; a marker AFTER the ids matches
# fine. Recorded so the next widening starts from here rather than re-discovering it.
_LANDED_ID_CELL_RE = re.compile(
    r"^\|(?:\s*\d+\s*\|)?\s*(?:`[A-Za-z]+-[0-9a-z]+`\s*)+`(TP-\d+[a-z]*)`", re.M
)

# Severity vocabulary terminating a MEMBER row. The id-cell pattern alone is not
# enough once solo TP ids are in scope: this file also carries a class-INDEX table
# (`| `TP-421` | §C12 | site |`) and a status table (`| `TP-420` | FIXED | ... |`),
# where a landed pack's presence is a legitimate cross-reference rather than an
# unstruck ownership row. Measured: widening the id cell without this filter flags 15
# rows of which only 3 are member rows -- so the shape check is what keeps the guard
# from becoming the false-positive machine the `~~` arm above was rejected for being.
_MEMBER_ROW_SEVERITIES = frozenset({"blocker", "major", "minor", "nit"})


def _is_member_row(line: str) -> bool:
    """True for a `| id | site | what | severity |` member-table row, or the
    MIXED-class shape `| id | site | what | severity | population | audience |`
    that §C0 carries since 2026-09-08.

    Keyed on the row's SHAPE (severity in the fourth cell; either nothing after
    it or the two tag cells) rather than on which section it appears under, so
    a new section inherits the guard automatically instead of needing to be
    added to a list.
    """
    # Split on UNESCAPED pipes, as `_ledger_sections` does: a `\|` inside a
    # cell is text (a closing text that spells a pipeline), and a naive split
    # pushed the severity out of the fourth cell -- the one disagreement the
    # ceiling below used to carry (DEF-414e), and a second one on 2026-09-08.
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
    if cells and cells[0].isdigit():
        cells = cells[1:]  # the numbered section shape carries an ordinal first
    return len(cells) in (4, 6) and cells[3].lower() in _MEMBER_ROW_SEVERITIES


def _pack_is_landed(done: Path, tok: str) -> bool:
    """True if a ``Done/<tok>-*.md`` exists whose Landing stanza is ``State: LANDED``.

    Delegates the stanza parse to the canonical ``check_pack_landing.landed_state``
    (scoped to the ``## Landing`` stanza, tolerant of a bold ``**State:**`` value) so
    a prose / code-block ``State: LANDED`` decoy elsewhere in the pack body does not
    false-match -- the failure mode a bare ``re.search(r"State: LANDED")`` has. Only
    ``LANDED`` counts, never ``SCRAPPED``: a follow-up owned by a *scrapped* pack is
    unfinished work whose ledger row should stay, not be struck.
    """
    for pack in sorted(done.glob(f"{tok}-*.md")):
        if _landed_state(pack.read_text(encoding="utf-8")) == "LANDED":
            return True
    return False


def _landed_still_listed(done: Path, ledger: Path) -> list[str]:
    """Ledger rows tagging a pack that has LANDED (in ``Done/``) but was never struck.

    The reverse-direction twin of ``_orphans``: that guards a ``Deferred/`` pack with
    no ledger row; this guards a ledger row for an already-landed pack. Population is
    the ledger's own tag set (the SoT), cross-checked against the ``Done/`` folder. A
    bare ``LANDED (TP-`` literal is ALWAYS reported (landed rows are *removed*, not
    marked-in-place, so the literal must never appear); an ``owned:`` / ``drafted-pack``
    tag is reported only when the pack actually shows ``State: LANDED`` in ``Done/`` --
    so a genuine open follow-up (fresh id, unlanded owner) never REDs. Factored (like
    ``_orphans``) so the earn-the-red drives a synthetic tmp tree, never the live folder.
    """
    text = ledger.read_text(encoding="utf-8")
    stale: list[str] = []
    if "LANDED (TP-" in text:
        stale.append("LANDED (TP-... literal present -- landed rows must be removed, not marked")
    for m in _LANDED_TAG_RE.finditer(text):
        tok = m.group(1)
        if m.group(0).lstrip().startswith("LANDED"):
            continue  # the bare-literal check above already covers this shape
        # A tag inside a STRUCK member row is history, not a lingering row: the
        # strike keeps PRIOR TEXT verbatim, and `drafted-pack (TP-N)` there records
        # which pack was to close the row. This function's contract is rows "never
        # struck"; the id-cell doorway below honours that by shape (`~~` is not a
        # backticked id) and this doorway did not until 2026-09-23, when the M3
        # release-gate pack landed and four struck rows' prior text named it.
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line = text[line_start : line_end if line_end != -1 else len(text)]
        if _is_member_row(line) and line.lstrip("| ").startswith("~~"):
            continue
        if _pack_is_landed(done, tok):
            stale.append(tok)
    # ...and the same check over the member-table id-cell shape, which carries no
    # prose tag for the pattern above to find. Same predicate, second doorway --
    # scoped by `_is_member_row` so the class-index and status tables, where a landed
    # pack is a legitimate cross-reference, do not read as unstruck ownership rows.
    for m in _LANDED_ID_CELL_RE.finditer(text):
        line = text[text.rfind("\n", 0, m.start()) + 1 : text.find("\n", m.start())]
        if _is_member_row(line) and _pack_is_landed(done, m.group(1)):
            stale.append(m.group(1))
    return sorted(set(stale))


def _pack_id_exists(packs: Path, tok: str) -> bool:
    """True if a ``<tok>-*.md`` file exists in a SHIPPED location (the root or ``Deferred/``).

    The status folders are DISCOVERED, never listed. A hand-written tuple here read
    ``("", "Done", "Deferred", "Merged")`` and silently omitted ``Scrapped/``, so a
    citation of a correctly-scrapped pack reported as dangling and the failure text
    advised re-keying a citation that was already right (2026-09-01, TP-443/TP-449
    were scrapped and cited by DEF-624).

    ⚠ DERIVING BREADTH WHILE HARDCODING DEPTH is the same defect one dimension over,
    and the first fix here did exactly that -- a one-level ``iterdir()``. ``rglob``
    derives both. Dot-directories are then excluded DELIBERATELY: ``iterdir()`` admits
    any subdirectory, so a ``task-packs/.attic/`` holding retired packs would resolve
    their ids and make the dangling-citation gate go FALSE-CLEAN -- quieter than the
    bug this replaced. The old hand-list could never admit a folder nobody wrote down;
    a derived walk can, so the exclusion has to be explicit.

    The one sibling that hand-lists this set, ``tests/test_cross_pack_assertions.py``,
    is complete AND pinned by a test that reds when an unclassified folder appears.
    ``scripts/check_pack_landing.py`` is NOT a third enumeration -- it scopes to a
    single ``DONE_DIR``, which is a scope decision (DEF-624), not a short list.
    """
    if not packs.is_dir():
        return False
    # NARROWED 2026-09-21 to the SHIPPED locations -- the folder root and
    # Deferred/, the same population `_orphans` walks -- because the reader this
    # gate serves is the reader of the public tree, where Done/, Merged/ and
    # Scrapped/ do not exist. Until then an rglob resolved a citation against
    # every status folder, so a row citing a landed pack was green on the dev
    # tree and dangling on the seed (TP-452 1-F measured three such ids in a
    # clone without Done/). The DEF-624 lesson above still governs: the two
    # locations are the declared shipped set, not a re-typed folder list, and
    # `is_shipped_pack` in espalier/surface_contract.py is their one home.
    for folder in (packs, packs / "Deferred"):
        if not folder.is_dir():
            continue
        for hit in folder.glob(f"{tok}-*.md"):
            if hit.is_file() and not hit.name.startswith("."):
                return True
    return False


def _exempt_ledger_lines(lines: list[str]) -> set[int]:
    """1-based line numbers whose TP-N mentions are legitimate, by SHAPE not by count.

    Two shapes, not three. An earlier reading counted the "combine map" separately
    from the dated *Removed as landed* block -- they are the SAME region: the combine
    map (``TP-385 via TP-377``) sits INSIDE that italic block. Counting them apart
    leads to writing two exemptions where one applies, and to hunting for a standalone
    combine-map line that does not exist.

    1. The dated ``_Removed as landed (...): ..._`` block -- a MULTI-LINE region that
       exists precisely to name ids that no longer have rows. Matched as a region: a
       line-scoped exemption anchored on the combine-map line alone would leave the
       block's other lines unexempted, and they are dense with ``via TP-NNN`` ids.
    2. ``_Source:`` attribution lines -- provenance pointers to where a row came from,
       not live citations.
    """
    exempt: set[int] = set()
    in_block = False
    for i, line in enumerate(lines, 1):
        if re.search(r"_Removed as landed \(", line):
            in_block = True
        if in_block:
            exempt.add(i)
            if line.rstrip().endswith("_"):
                in_block = False
        if "_Source:" in line:
            exempt.add(i)
    return exempt


def _dangling_id_references(packs: Path, ledger: Path) -> dict[str, list[int]]:
    """Ledger prose citing a ``TP-N`` id that resolves to NO pack file anywhere.

    A DIFFERENT predicate from :func:`_landed_still_listed`, and deliberately a
    separate helper. That one asks "does this row cite a pack that already LANDED?"
    and keys on ``_pack_is_landed``; this asks "does this row cite an id that names no
    artifact at all?" and keys on EXISTENCE. The distinction is load-bearing: the
    motivating case (a row calling ``TP-385`` a live sibling while the same file
    records it as merged away) can NEVER be reported by the landed predicate, because
    no ``TP-385-*.md`` exists for ``_pack_is_landed`` to find. Widening what is fed to
    that predicate would not have changed its answer -- the arm had to key on
    something else. Two classes, two messages.

    Returns ``{id: [line numbers]}`` so the failure message can point at rows.
    """
    lines = ledger.read_text(encoding="utf-8").splitlines()
    exempt = _exempt_ledger_lines(lines)
    found: dict[str, list[int]] = {}
    for i, line in enumerate(lines, 1):
        if i in exempt:
            continue
        # The lookbehind keeps a pack id EMBEDDED in a longer hyphenated identifier
        # out of the population. `\b` matches after the `-` in `pre-pack-TP-104`, so
        # the plain pattern read the scaffolding git TAG as a citation to a pack that
        # does not exist -- and the row naming that tag is the one saying "do not
        # delete this one tag". A citation always opens on whitespace, `(`, `` ` ``
        # or `*`, none of which the lookbehind excludes.
        for match in re.finditer(r"(?<![-\w])TP-(\d+[a-z]*)\b", line):
            tok = f"TP-{match.group(1)}"
            if not _pack_id_exists(packs, tok):
                found.setdefault(tok, []).append(i)
    return found


@pytest.mark.skipif(
    # The ledger alone: a missing pack folder is an empty population, a missing
    # ledger would reach read_text() -> FileNotFoundError, a pytest *error*
    # rather than a clean skip. See TestSelfHostGate below. Until 2026-09-20
    # this also required Deferred/ to exist, so the live check skipped on the
    # tree it ships to (TP-452 Task 0 measured it; 1-D dropped the folder gate).
    not _LEDGER.is_file(),
    reason="self-host only: FORWARD_LEDGER.md absent",
)
def test_every_active_pack_is_ledger_tracked():
    """Every ACTIVE pack -- at task-packs/ root or held in Deferred/ -- has a row.

    EXACT dated baseline, the dangling-citation test's shape. Widening the
    population to the root on 2026-09-20 (TP-452 1-D) found `TP-452` itself
    there -- the pack running the rebuild -- cited by no row of the LIVE
    ledger, which predates its filings; the rebuilt file in
    reports/ledger-rebuild-2026-09-20/ cites it five times through 1-C's rows.
    (The same measurement showed the 1-B rewrite of `DEF-841` had dropped its
    `TP-450` citation -- a root pack, so it ships -- which 1-D restores on the
    rebuilt file as `drafted-pack (TP-450)`.) The live write that lands the
    rebuilt file makes `repaired` red, and that red says delete the entry. A
    pack that leaves the population (landed to Done/) leaves the baseline
    quietly.
    """
    orphans = _orphans(_ACTIVE_PACK_DIRS, _LEDGER)
    # Emptied 2026-09-20 at the live write (TP-452 1-D session 3): the rebuilt
    # file cites TP-452 through 1-C's rows, and `repaired` said delete it.
    baseline: set[str] = set()
    present = {
        m.group(1) for p in _pack_files(_ACTIVE_PACK_DIRS)
        if (m := re.match(r"(TP-\d+[a-z]*)", p.name, re.IGNORECASE))
    }
    new = sorted(set(orphans) - baseline)
    repaired = sorted((baseline & present) - set(orphans))
    assert not new and not repaired, (
        "active packs with no FORWARD_LEDGER.md reference moved off the 2026-09-20 baseline.\n"
        f"  NEW orphans (author a ledger row for each, or drop the pack): {new}\n"
        f"  Now referenced (DELETE these from `baseline` in this test): {repaired}"
    )


def _make_tree(tmp_path: Path, pack_names: list[str], ledger_text: str) -> tuple[Path, Path]:
    """A throwaway task-packs/ tree for the fixture-driven earn-red."""
    deferred = tmp_path / "task-packs" / "Deferred"
    deferred.mkdir(parents=True)
    for name in pack_names:
        (deferred / name).write_text("# stub pack\n", encoding="utf-8")
    ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
    ledger.write_text(ledger_text, encoding="utf-8")
    return deferred, ledger


class TestOrphanDetection:
    def test_orphan_detected_on_synthetic_tree(self, tmp_path):
        # Earn-the-red: a known-orphan Deferred pack + an empty ledger. The
        # helper names the orphan (RED-equivalent) -- the sole deterministic
        # red-earner, since TP-338/TP-342 are already ledger-tracked at HEAD.
        deferred, ledger = _make_tree(
            tmp_path, ["TP-999-orphan.md"], "# ledger\n(nothing tracked)\n"
        )
        assert _orphans(deferred, ledger) == ["TP-999"]

    def test_orphan_cleared_when_referenced(self, tmp_path):
        # GREEN once the ledger references the pack (anchored token present).
        deferred, ledger = _make_tree(
            tmp_path, ["TP-999-orphan.md"], "# ledger\n- TP-999 tracked here\n"
        )
        assert _orphans(deferred, ledger) == []

    def test_alpha_suffix_not_truncated_to_sibling(self, tmp_path):
        # TP-233b must NOT be satisfied by a bare TP-233 row -- distinct packs.
        deferred, ledger = _make_tree(
            tmp_path, ["TP-233b-x.md"], "# ledger\n- TP-233 (a different pack)\n"
        )
        assert _orphans(deferred, ledger) == ["TP-233b"]

    def test_bare_number_substring_is_not_a_false_green(self, tmp_path):
        # A bare number living inside a commit hash / count must NOT count as
        # tracking the pack -- the false-GREEN direction the anchoring forecloses.
        deferred, ledger = _make_tree(
            tmp_path, ["TP-338-x.md"], "# ledger\n- landed in 9e363e8 (338 refs)\n"
        )
        assert _orphans(deferred, ledger) == ["TP-338"]

    def test_nonconforming_name_is_reported_not_skipped(self, tmp_path):
        # A TP-*.md file with no TP-<n> token is un-trackable -> surfaced by
        # name, never silently dropped (the guard against .group(1) on None).
        deferred, ledger = _make_tree(
            tmp_path, ["TP-notes-scratch.md"], "# ledger\n(empty)\n"
        )
        assert _orphans(deferred, ledger) == ["TP-notes-scratch.md"]

    def test_multiple_orphans_all_reported(self, tmp_path):
        # The full orphan set is returned, not just the first.
        deferred, ledger = _make_tree(
            tmp_path,
            ["TP-901-a.md", "TP-902-b.md", "TP-903-c.md"],
            "# ledger\n- TP-902 tracked\n",
        )
        assert _orphans(deferred, ledger) == ["TP-901", "TP-903"]

    def test_offconvention_markdown_orphan_reported(self, tmp_path):
        # 1-B earn-red (TP-372): an off-convention Deferred pack -- lowercase
        # `tp-` prefix AND a `.markdown` extension -- with no ledger row must
        # still be caught. The `.markdown` extension makes RED-before
        # deterministic on every filesystem: the pre-fix glob("TP-*.md") never
        # matches `.markdown`, so the pack silently escaped (returned []). A
        # lowercase-`.md` fixture would be ambiguous -- Path.glob("TP-*.md") is
        # case-insensitive on macOS/APFS but case-sensitive on Linux CI. Reported
        # AS-CAPTURED (`tp-999`), per the anchored-token convention above.
        deferred, ledger = _make_tree(
            tmp_path, ["tp-999-x.markdown"], "# ledger\n(nothing tracked)\n"
        )
        assert _orphans(deferred, ledger) == ["tp-999"]

    def test_a_root_pack_with_no_ledger_reference_is_reported(self, tmp_path):
        # TP-452 1-D: the population is every ACTIVE pack -- the root of
        # task-packs/ (the packs that ship) plus Deferred/ -- so the live check
        # runs on the seed, where Done/ never exists. The red was earned on the
        # real tree: TP-450 sat at the root cited by no row (the live test's
        # baseline); this row pins the shape on a tree it was not written on.
        packs = tmp_path / "task-packs"
        packs.mkdir()
        (packs / "TP-999-root.md").write_text("# stub pack\n", encoding="utf-8")
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n(nothing tracked)\n", encoding="utf-8")
        assert _orphans((packs, packs / "Deferred"), ledger) == ["TP-999"]

    def test_a_done_pack_is_never_an_orphan(self, tmp_path):
        # Landed work leaves the ledger by contract rule 3, so a Done/ pack with
        # no row is the CORRECT state; the reverse guard (TestLandedRowLingering)
        # is the one that reads Done/. The root folder's subdirectories and its
        # non-pack files (the ledger itself) are not population either.
        packs = tmp_path / "task-packs"
        (packs / "Done").mkdir(parents=True)
        (packs / "Done" / "TP-999-landed.md").write_text("# stub pack\n", encoding="utf-8")
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n(nothing tracked)\n", encoding="utf-8")
        assert _orphans((packs, packs / "Deferred"), ledger) == []


class TestSelfHostGate:
    def test_an_absent_deferred_folder_is_an_empty_population_not_a_skip(self, tmp_path):
        # The seed, and any clone before 1-F lands Deferred/: the live check
        # RUNS over the root packs. Until 2026-09-20 the gate required Deferred/
        # to exist, so the check skipped on exactly the tree it ships to.
        packs = tmp_path / "task-packs"
        packs.mkdir()
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n", encoding="utf-8")
        assert not (packs / "Deferred").is_dir() and ledger.is_file()
        assert _orphans((packs, packs / "Deferred"), ledger) == []

    def test_gate_false_when_ledger_absent_and_orphans_would_error(self, tmp_path):
        # Partial checkout: packs present, ledger absent. The guard (the ledger
        # alone) is False (skip) AND _orphans would FileNotFoundError without
        # it -- proof the gate is load-bearing, not decoration: without it a
        # partial tree is a pytest error.
        deferred = tmp_path / "task-packs" / "Deferred"
        deferred.mkdir(parents=True)
        (deferred / "TP-1-x.md").write_text("# stub pack\n", encoding="utf-8")
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        assert not ledger.is_file()
        with pytest.raises(FileNotFoundError):
            _orphans((tmp_path / "task-packs", deferred), ledger)


def _make_done_tree(
    tmp_path: Path, done_names_states: list[tuple[str, str]], ledger_text: str
) -> tuple[Path, Path]:
    """A throwaway task-packs/ tree with a Done/ folder for the recurrence earn-red.

    ``done_names_states`` is ``(filename, state)`` pairs; each Done/ pack gets a
    minimal ``## Landing`` stanza carrying that ``State:`` so the canonical parser
    resolves it exactly as it would a real pack. Never touches the live tree.
    """
    done = tmp_path / "task-packs" / "Done"
    done.mkdir(parents=True)
    for name, state in done_names_states:
        (done / name).write_text(
            f"# stub pack\n\n## Landing\n- State: {state}\n", encoding="utf-8"
        )
    ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
    ledger.write_text(ledger_text, encoding="utf-8")
    return done, ledger


@pytest.mark.skipif(
    _landed_state is None,
    reason="self-host only: scripts/check_pack_landing.py (dev tooling) absent off-host",
)
class TestLandedRowLingering:
    """The reverse-direction recurrence guard: a ledger row for an already-landed pack."""

    def test_bare_landed_literal_is_reported(self, tmp_path):
        # Earn-the-red: a synthetic Done/TP-999 LANDED + a ledger carrying the bare
        # `LANDED (TP-999` marker-in-place anti-pattern -> RED (non-empty). Landed
        # rows are REMOVED, so the literal must never survive in the ledger body.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-999-x.md", "LANDED")],
            "# ledger\n- **TP-999 - thing.** `LANDED (TP-999, abc1234).` shipped\n",
        )
        assert _landed_still_listed(done, ledger)  # RED-equivalent: non-empty

    def test_green_once_landed_row_struck(self, tmp_path):
        # GREEN once the LANDED row is removed (the sweep's post-state) -- proves the
        # detector flips, not that it always reds.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-999-x.md", "LANDED")],
            "# ledger\n(the TP-999 row was struck when it shipped)\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_earn_the_red_id_cell_row_naming_a_landed_pack_is_reported(self, tmp_path):
        """THE DEFECT, asserted as an asymmetry rather than described.

        ``_LANDED_TAG_RE`` reads PROSE tags. A member-table row whose first cell is
        just backticked ids carries no prose tag at all -- and that is this file's
        DOMINANT row shape, so the one form that actually accumulates was the one
        form the guard could not see. The same landed pack, in the same ledger, is
        flagged in ``owned:`` prose and invisible in an id cell.
        """
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-555-z.md", "LANDED")],
            "# ledger\n| `DEF-1` `TP-555` | `some/file.py::sym` | still listed | minor |\n",
        )
        assert _landed_still_listed(done, ledger) == ["TP-555"]

        # ...and the prose form of the SAME pack was always caught. That is the
        # asymmetry: one shape seen, one shape blind, one ledger.
        _, prose = _make_done_tree(
            tmp_path / "prose",
            [("TP-555-z.md", "LANDED")],
            "# ledger\n- **DEF-1.** `open (owned: TP-555, DRAFT).` follow-up\n",
        )
        assert _landed_still_listed(done, prose) == ["TP-555"]

    def test_a_solo_tp_id_cell_is_deliberately_NOT_an_ownership_tag(self, tmp_path):
        """A solo `| `TP-330` |` first cell must stay quiet -- and this is a
        DELIBERATE scope boundary, not the detector being narrow by accident.

        In that shape the pack id is the DEFECT IDENTIFIER ("the TP-330 residual
        class"), not a pointer to an owning pack. Whether the pack landed says
        nothing about whether the residual closed. This arm was written the other
        way round first -- asserting the solo shape IS reported -- on a review
        finding that the detector was too narrow. Driving it against the live
        ledger flagged three such rows and ALL THREE were live open work; one
        states outright that its residuals "all reproduce". Striking them on the
        strength of a landed owner would have deleted real backlog.

        So the arm is inverted, and kept: it pins the boundary, and it records why
        the obvious widening is wrong so the next reader does not re-attempt it.
        """
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-559-z.md", "LANDED")],
            "# ledger\n| `TP-559` | `a/b.py::sym` | residual still reproduces | major |\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_numbered_id_cell_row_is_read(self, tmp_path):
        # The numbered section shape carries an ordinal before the ids. Same
        # ownership tag, same treatment -- the ordinal is not part of the identity.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-556-z.md", "LANDED")],
            "# ledger\n| 3 | `DEF-2` `TP-556` | `a/b.py::s` | open | nit |\n",
        )
        assert _landed_still_listed(done, ledger) == ["TP-556"]

    def test_a_class_index_row_is_not_an_ownership_row(self, tmp_path):
        """A landed pack in the class-INDEX table is a cross-reference, not debt.

        The ledger carries `| `TP-421` | §C12 | site |` mapping packs to sections,
        and `| `TP-420` | FIXED | ... |` recording status. Both legitimately name
        landed packs forever. Measured when the id cell was widened to accept solo
        TP ids: without a shape filter the guard flags 15 rows of which only 3 are
        member rows -- so this arm is what stops the widening from becoming the
        false-positive machine the strikethrough arm was rejected for being.
        """
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-560-z.md", "LANDED")],
            "# ledger\n"
            "| `TP-560` | §C12 | `a/b.py::sym` |\n"          # 3-cell class index
            "| `TP-560` | FIXED | done | 2026-08-01 |\n",     # 4-cell, no severity
        )
        assert _landed_still_listed(done, ledger) == []

    def test_a_struck_id_cell_stays_quiet(self, tmp_path):
        """A row already struck the ledger's way must NOT be re-reported.

        ``~~`` is this file's own "handled" marker. A widening that matched THROUGH
        it would re-surface rows that were closed correctly -- turning the guard
        into a demand for cosmetic edits on finished records, and burying the live
        rows it exists to find. This docstring's own predicate says it: rows tagging
        a landed pack *that were never struck*.
        """
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-557-z.md", "LANDED")],
            "# ledger\n| 1 | ~~`DEF-3`~~ `TP-557` | CLOSED, evidence retained |\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_a_drafted_pack_tag_inside_a_struck_row_stays_quiet(self, tmp_path):
        """The prose-tag doorway's twin of the row above. A strike keeps the
        row's PRIOR TEXT verbatim, and a `drafted-pack (TP-N)` tag there names
        the pack that was to close it -- history about an id, in a row already
        struck. Until 2026-09-23 this doorway read it as a lingering row the day
        that pack landed (measured: four struck rows named the M3 release gate
        in their prior text), while the id-cell doorway excluded a struck cell
        by shape. The same tag in a LIVE member row is still reported."""
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-559-z.md", "LANDED")],
            "# ledger\n| ~~`DEF-5`~~ | `a/b.py::sym` | ✅ **CLOSED 2026-09-23 — done.** "
            "PRIOR TEXT: open. `drafted-pack (TP-559)`: closes this at landing. | minor |\n",
        )
        assert _landed_still_listed(done, ledger) == []
        _, live = _make_done_tree(
            tmp_path / "live",
            [("TP-559-z.md", "LANDED")],
            "# ledger\n| `DEF-5` | `a/b.py::sym` | open. `drafted-pack (TP-559)`: "
            "closes this at landing. | minor |\n",
        )
        assert _landed_still_listed(done, live) == ["TP-559"]

    def test_id_cell_widening_does_not_fire_on_a_mere_reference(self, tmp_path):
        # A TP id in prose, or in a row's WHAT cell, is a REFERENCE, not an
        # ownership tag. A bare `TP-\d+` anywhere would fire on every live mention
        # of an open pack; the `^|` anchor is what keeps those quiet.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-558-z.md", "LANDED")],
            "# ledger\nProse mentioning `TP-558` in passing.\n"
            "| `DEF-4` | `a/b.py::sym` | superseded by `TP-558` |\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_landed_draft_tag_reported(self, tmp_path):
        # An `owned: TP-N, DRAFT` tag whose pack has since LANDED in Done/ must be
        # reported (strike the row, or strip the tag if the work is genuinely open).
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-888-y.md", "LANDED")],
            "# ledger\n- **DEF-x.** `open (owned: TP-888, DRAFT).` follow-up\n",
        )
        assert _landed_still_listed(done, ledger) == ["TP-888"]

    def test_path_qualified_drafted_pack_tag_reported(self, tmp_path):
        # TP-391 2-A. A `drafted-pack (Deferred/TP-N)` tag whose pack has since LANDED
        # must be reported exactly like the unqualified form. Committed on purpose: 2-A's
        # only other proof was a tmp copy of the live ledger, which vanishes with the run
        # -- leaving the widened tag shape as the sole accepted form with NO pin, so a
        # later narrowing of _LANDED_TAG_RE would silently re-open the blind spot. A gate
        # that survives its own narrowing is not pinned.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-777-z.md", "LANDED")],
            "# ledger\n- **DEF-x.** `drafted-pack (Deferred/TP-777).` follow-up\n",
        )
        assert _landed_still_listed(done, ledger) == ["TP-777"]

    def test_path_qualified_tag_without_id_not_reported(self, tmp_path):
        # The FP boundary of the widening: a `drafted-pack (Deferred/, ...)` row that
        # carries a folder but NO id (a live shape in the ledger) must stay unreported.
        # Without this, `[^)\s]*/` could be loosened to swallow the following prose and
        # nobody would notice.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-777-z.md", "LANDED")],
            "# ledger\n- **TP-x.** `drafted-pack (Deferred/, harvested from TP-777).` note\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_open_followup_of_unlanded_owner_not_reported(self, tmp_path):
        # FP-calibration: a genuine open follow-up whose owner pack is NOT in Done/
        # (still open) must NOT red -- the convention the guard rests on.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-888-y.md", "LANDED")],
            "# ledger\n- **DEF-z.** `open (owned: TP-777, DRAFT).` unlanded owner\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_scrapped_owner_does_not_trigger(self, tmp_path):
        # A follow-up owned by a SCRAPPED pack is unfinished work; its row stays
        # (only State: LANDED counts, not SCRAPPED) -- so it must NOT be reported.
        done, ledger = _make_done_tree(
            tmp_path,
            [("TP-666-s.md", "SCRAPPED")],
            "# ledger\n- **DEF-w.** `open (owned: TP-666, DRAFT).` scrapped owner\n",
        )
        assert _landed_still_listed(done, ledger) == []

    def test_prose_state_landed_decoy_not_a_false_positive(self, tmp_path):
        # The canon-reuse payoff: a Done/ pack whose BODY carries a line-anchored
        # `- State: LANDED` (an earn-red EXAMPLE) but whose real ## Landing stanza is
        # DRAFT must NOT read as landed. A bare re.search(r"^\s*-?\s*State:\s*LANDED",
        # ..., re.M) would match the example line and false-report landed; the
        # stanza-scoped canonical parser reads only the Landing stanza (-> DRAFT).
        done = tmp_path / "task-packs" / "Done"
        done.mkdir(parents=True)
        (done / "TP-555-d.md").write_text(
            "# pack\n\nExample landed stanza (from the authoring guide):\n"
            "- State: LANDED\n\n## Landing\n- State: DRAFT\n",
            encoding="utf-8",
        )
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.write_text(
            "# ledger\n- **DEF-q.** `open (owned: TP-555, DRAFT).` still open\n",
            encoding="utf-8",
        )
        assert _landed_still_listed(done, ledger) == []


@pytest.mark.skipif(
    not (_DONE.is_dir() and _LEDGER.is_file() and _landed_state is not None),
    reason="self-host only: task-packs/Done/ + FORWARD_LEDGER.md + dev tooling absent",
)
def test_no_landed_pack_row_lingers_in_ledger():
    # Standing proof the U8 sweep was complete: run the guard against the LIVE
    # ledger + Done/ folder. GREEN means no landed pack still carries a tracking row.
    stale = _landed_still_listed(_DONE, _LEDGER)
    assert not stale, (
        "FORWARD_LEDGER.md carries rows for packs already LANDED in Done/ "
        "(the ledger's own rule is remove-when-shipped). Strike them (see the "
        "U8 ledger-integrity sweep): " + ", ".join(stale)
    )


class TestDanglingIdReferences:
    """TP-391 2-B: ledger prose citing an id that names no pack artifact at all."""

    def test_dangling_reference_reported_on_synthetic_tree(self, tmp_path):
        # Earn-the-red: a row citing TP-404, which exists nowhere in the pack tree.
        # Note this is UNREACHABLE by _landed_still_listed -- its _pack_is_landed can
        # only answer for ids that HAVE a file. Two predicates, two classes.
        packs = tmp_path / "task-packs"
        (packs / "Done").mkdir(parents=True)
        (packs / "Done" / "TP-777-z.md").write_text("# p\n\n## Landing\n- State: LANDED\n",
                                                    encoding="utf-8")
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n- **DEF-x.** Robustness sibling = TP-404.\n",
                          encoding="utf-8")
        assert _dangling_id_references(packs, ledger) == {"TP-404": [2]}
        # And the landed-arm stays silent on it -- the proof the redesign was needed.
        assert _landed_still_listed(packs / "Done", ledger) == []

    def test_resolvable_reference_not_reported(self, tmp_path):
        # GREEN when the cited id names a real pack file -- proves the helper flips.
        packs = tmp_path / "task-packs"
        (packs / "Deferred").mkdir(parents=True)
        (packs / "Deferred" / "TP-404-real.md").write_text("# p\n", encoding="utf-8")
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n- **DEF-x.** sibling = TP-404.\n", encoding="utf-8")
        assert _dangling_id_references(packs, ledger) == {}

    @pytest.mark.parametrize("folder", ["Done", "Merged", "Scrapped", "Deferred/old"])
    def test_a_pack_outside_the_shipped_locations_does_not_resolve(self, tmp_path, folder):
        # Earn-the-red for the 2026-09-21 narrowing: the rglob resolver read a
        # citation of a landed / merged / scrapped pack as fine, and the public
        # tree has none of those folders, so the same row dangles there. The
        # root and Deferred/ are the shipped locations; nothing else resolves.
        packs = tmp_path / "task-packs"
        (packs / folder).mkdir(parents=True)
        (packs / folder / "TP-404-landed.md").write_text("# p\n", encoding="utf-8")
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n- **DEF-x.** sibling = TP-404.\n", encoding="utf-8")
        assert _dangling_id_references(packs, ledger) == {"TP-404": [2]}
        (packs / "TP-404-active.md").write_text("# p\n", encoding="utf-8")
        assert _dangling_id_references(packs, ledger) == {}

    def test_removed_as_landed_block_is_exempt_across_all_its_lines(self, tmp_path):
        # The exemption is a REGION, not a line. A dangling id on the block's LAST
        # line must be exempt just like one on its first -- the shape that a
        # combine-map-line-only exemption would have missed.
        packs = tmp_path / "task-packs"
        packs.mkdir(parents=True)
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text(
            "# ledger\n"
            "_Removed as landed (2026-01-01, sweep): TP-404 via TP-405;\n"
            "TP-406 via TP-407; TP-408 via TP-409._\n"
            "- **DEF-live.** cites TP-410 in live prose\n",
            encoding="utf-8",
        )
        found = _dangling_id_references(packs, ledger)
        assert found == {"TP-410": [4]}, (
            "the dated Removed-as-landed block must be exempt across ALL its lines, "
            f"and live prose outside it must still report. Got: {found}"
        )

    def test_source_attribution_line_is_exempt(self, tmp_path):
        packs = tmp_path / "task-packs"
        packs.mkdir(parents=True)
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text("# ledger\n- **DEF-x.** note. _Source: TP-404 review._\n",
                          encoding="utf-8")
        assert _dangling_id_references(packs, ledger) == {}


@pytest.mark.skipif(
    not (_PACKS.is_dir() and _LEDGER.is_file()),
    reason="self-host only: the pack folder or the ledger is absent on this tree",
)
def test_live_ledger_grows_no_new_dangling_id_references():
    """TP-391 2-B, calibrated against the live population rather than an ideal.

    Measured at authoring: 18 distinct ids / 26 mentions cite a TP-N that names no
    pack file. They are historical -- ids merged away, renumbered, or never packed --
    and predate this guard. Asserting zero would red the suite for work this pack
    does not own, so the invariant is "no NEW ones", pinned by an exact baseline.

    EXACT, not a subset floor: a subset check lets the baseline rot silently as
    citations are repaired, which is the same fail-open shape this pack exists to
    close (an exclusion inside a mechanical gate is itself an untested assertion).
    Removing an id from the baseline is a one-line edit and the message says so.

    Hand-off (TP-391 -> TP-394): TP-385 is here deliberately. It was the live drift
    TP-394 repairs.

    ⚠ THE HAND-OFF'S PREDICTION WAS WRONG, and TP-394 resolved it by MEASUREMENT
    rather than by following it. This docstring said: when TP-394's repair lands,
    this test REDs with "no longer dangling" and TP-394 drops the entry in the same
    commit. It does not. TP-394 repaired the TP-355 row's "Robustness sibling =
    TP-385" claim on 2026-08-04 and TP-385 stayed dangling, because this guard keys
    on ANY mention of an id resolving to no pack file, and two legitimate mentions
    survive that no repair should remove: the combine-map note recording "TP-385 via
    TP-377" (correct history) and DEF-416b's own record naming "TP-412 -> TP-385" as
    its only live instance. Both are records ABOUT the id, not open work citing it.

    So TP-385 STAYS in this baseline, and deleting it would red the suite rather
    than green it. The prediction was written from the shape of the fix, not from
    this predicate's actual population -- the same class of unverified load-bearing
    premise that TP-394 item 1-A exists to correct, recurring in the hand-off that
    set up 1-A's own sibling. A prediction inside a shipped test is a claim; measure
    it before acting on it.

    The lesson generalizes past this pair: a guard that keys on MENTIONS cannot be
    discharged by repairing one CITATION SITE. If an id must leave this set, every
    mention has to go -- including the correct historical ones -- which is usually
    the wrong trade.
    """
    # Shrunk 2026-08-05 by the root-cause rebuild of FORWARD_LEDGER.md. Twelve
    # entries -- TP-12, TP-87, TP-153, TP-156, TP-163, TP-169, TP-170, TP-179,
    # TP-194, TP-202, TP-233, TP-359x -- left this set because the prose citing
    # them was struck when their rows were verified dead or absorbed into a §C
    # class. Removing them TIGHTENS the guard: each is now a citation the ledger
    # may not reintroduce without this test reding.
    #
    # Shrunk again 2026-08-20 by the second rebuild, from ten entries to one.
    # TP-176, TP-182, TP-225, TP-227, TP-237, TP-375, TP-376, TP-380 and TP-385
    # left this set for a DIFFERENT reason than the 08-05 twelve, and the
    # difference matters: their citations were not repaired and the packs still
    # do not exist. The prose carrying them moved wholesale into
    # `task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-08-20.md`, a declared RECORD
    # surface this guard does not sweep. So the live tracker no longer cites a
    # pack that was never created -- which is the property this test defends --
    # while the provenance each citation carried is preserved verbatim next
    # door. Re-introducing any of them into the LIVE file must red.
    #
    # Emptied 2026-09-20 by the third rebuild's live write (TP-452 1-D). The one
    # survivor, TP-35, sat in §1A row 1's struck prose (the absolute-path fix
    # "re-introduces the exact regression TP-35 exists to pin"); the structural
    # cut dropped that row with the sixteen closed launch gates, and the prose
    # is on the record branch's FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md. The
    # invariant it named is still pinned by tests/test_hook_exec_form.py. The
    # live file now cites no pack that does not exist; any id entering must red.
    #
    # Two entries added 2026-09-21 (TP-452 1-H): the struck `DEF-648` row records the
    # dispositions of TP-439 (SCRAPPED) and TP-441 (LANDED by measurement) by name, in
    # its PRIOR TEXT and its closing text and in its Appendix B index row, and both
    # packs left the shipped locations by that very decision. These are records ABOUT
    # an id (the TP-385 shape above), not open work citing it, and the row cites the
    # commits that landed TP-441's work. They leave this set when the next structural
    # cut moves the struck row to the record file -- never by editing PRIOR TEXT
    # (the ledger's one carve-out, never-ship material, is recorded in its contract).
    # TP-371 likewise: the struck `DEF-412a` row names the origin case of the
    # class it closed (a landed pack whose Scope (out) parked a remainder nothing
    # read) -- history about an id, in a closed row.
    # TP-452 added 2026-09-22 at its own landing (1-I measured, the full tier
    # green): the pack left the shipped locations for Done/. Its five live citing
    # rows (DEF-841, DEF-913, DEF-914, DEF-519, SUP-2) were re-keyed through the
    # verb to the pack's title and landing date, per this gate's message, and the
    # ledger header's rebuild note by hand (prose, not a row). The mentions that
    # remain are records about the id: the struck rows DEF-412a, DEF-646, DEF-648
    # (member and index), DEF-707 and DEF-708, in closing text and PRIOR TEXT and
    # never edited (the rule above); the INV-3/INV-4 three-cell row the verb
    # refuses by shape; and INV-26's folded label. They leave this set when the
    # next structural cut moves the struck rows to the record file.
    # TP-453 joined 2026-09-22 at its landing: the struck `DEF-709` row keeps the
    # id in its prior text, and the pack left the shipped locations for Done/.
    # TP-454 and TP-455 joined 2026-09-23 at their joint landing (the M3 release
    # gate and the archive-tree class, both to Done/). TP-454: its one live citing
    # row (DEF-915) was re-keyed through the verb to the pack's title and landing
    # date; the four mentions that remain are `drafted-pack (TP-454)` tags in the
    # PRIOR TEXT of the struck rows DEF-817, DEF-870, DEF-419a and DEF-262a --
    # records about the id, never edited. TP-455: the struck DEF-916 row keeps the
    # id in its prior text ("corrected at the authoring of TP-455"). Both leave
    # this set when the next structural cut moves the struck rows to the record file.
    # TP-319 joined 2026-09-24 at the pre-door review before the 0.8.0b1 seed: the
    # roadmap named third parties with figures it declared stale, so the file left
    # the shipped locations for Scrapped/ (the TP-439 shape). Its §3 row is struck
    # by hand (the verb refuses the three-cell shape) and keeps the id in its
    # closing text and PRIOR TEXT -- a record about the id, edited only under the
    # ledger's never-ship carve-out. It leaves
    # this set when the next structural cut moves the struck row to the record file.
    baseline: set[str] = {
        "TP-319", "TP-371", "TP-439", "TP-441", "TP-452", "TP-453", "TP-454", "TP-455",
    }
    found = _dangling_id_references(_PACKS, _LEDGER)
    # A pack withheld from the seed by an export-ignore row (.gitattributes,
    # `/task-packs/TP-<n>-*.md`) is absent on an export BY DECLARATION, so its
    # citations dangle there and nowhere else: derive those ids from the rows the
    # export ships with, on an export only. On a development tree the pack is
    # present and resolves. Driven 2026-09-24 on the extracted archive
    # (scripts/archive_probe.py, the oracle for this shape): the TP-456
    # withholding made ten citations dangle there while this tree stayed green.
    # When the public repository drops the row after the seed, the id joins
    # `baseline` in the same commit -- a record about a pack that never existed there.
    from espalier import surface_contract
    expected = set(baseline)
    if surface_contract.is_release_export(_ROOT):
        expected |= {
            m.group(0)
            for pat in surface_contract.export_ignore_patterns(_ROOT)
            if pat.startswith("/task-packs/")
            for m in re.finditer(r"TP-\d+[a-z]?", pat)
        }
    new = {k: v for k, v in found.items() if k not in expected}
    repaired = sorted(expected - set(found))
    assert not new and not repaired, (
        "FORWARD_LEDGER.md dangling-citation baseline moved.\n"
        f"  NEW dangling ids (a row cites a pack that is in neither shipped location, "
        f"task-packs/ or task-packs/Deferred/ -- it may have just landed in Done/; re-key "
        f"the citation to the pack's title or its commit through scripts/ledger_row.py, "
        f"do not add a back-reference): { {k: v for k, v in new.items()} }\n"
        f"  No longer dangling (citation repaired or the pack now exists -- DELETE "
        f"these from `baseline` in this test): {repaired}\n"
        "Note: TP-385 leaving this set is the expected result of TP-394 landing."
    )


# ---------------------------------------------------------------------------
# DEF-412e: work a pack DEFERS into has a reader.
#
# `_orphans` asks "does every active pack have a row?"; nothing asked the
# converse -- "does every pack an active pack's Scope (out) points AT exist?".
# A Scope (out) naming a future `TP-` id with no file and no row was invisible
# to every assertion in this module, so the only record of the deferral was a
# sentence in a pack that later landed. The reader is
# `check_pack_landing.scope_out` -- the same one `scripts/ledger_row.py strike`
# reads before it closes a row (DEF-412a) -- so the guard and the gate cannot
# disagree about where a deferral lives or which packs are in flight.
# ---------------------------------------------------------------------------

def _unresolved_scope_out_deferrals(
    pack_dirs: Iterable[Path], packs_root: Path, ledger: Path
) -> dict[str, list[str]]:
    """``{TP-id: [citing pack filenames]}`` for every pack id an ACTIVE pack's
    Scope (out) names that resolves to neither a pack file in a SHIPPED location
    (the root or ``Deferred/``, via `_pack_id_exists`) nor a live MEMBER row
    whose id cell carries it.

    The SHIPPED locations, deliberately, and for the reason `_pack_id_exists` was
    narrowed at TP-452 1-F: the verdict must be the same on the dev tree and on
    the seed, where ``Done/`` never exists. The first cut here resolved against
    any status folder and was green on the dev tree while red on a ``--shared``
    clone without ``Done/`` (2026-09-21) -- the tree-dependent answer TP-452
    Task 0 measured for `_orphans`, in the other direction.

    What the gate READS is every pack id in a Scope (out), whatever the sentence
    around it: the failure-mode pass (2026-09-21) showed the live population is
    nine prior-art mentions ("unchanged from TP-432's grammar") and one
    ownership pointer, and not one forward deferral ("the rest goes to TP-999"
    -- the fixture idiom, and DEF-412e's class, which has zero live instances).
    So the gate serves DEF-914 (a shipped pack citing a pack id the public tree
    cannot resolve) and, by containment, DEF-412e (a deferral into a pack nobody
    wrote is one such id); `_deferral_kind` names the remedy per entry from the
    folders when they are visible, never from the verdict. Live ids come from
    the class sections' member rows only: the Appendix A crosswalk and the
    drafted-pack index also open ``| `TP-...` |`` and would keep resolving a pack
    after it lands (code review, 2026-09-21).
    """
    text = ledger.read_text(encoding="utf-8")
    live_ids: set[str] = set()
    for rows in _ledger_sections(text).values():
        for row in rows:
            if not _is_struck(row):
                live_ids.update(re.findall(r"`([A-Za-z]+-\d+[a-z]*)`", row.split("|")[1]))
    out: dict[str, list[str]] = {}
    for pack in _shared_pack_files(pack_dirs):
        body = _scope_out(pack.read_text(encoding="utf-8"))
        for match in re.finditer(r"(?<![-\w])TP-(\d+[a-z]*)\b", body):
            tok = f"TP-{match.group(1)}"
            if tok in live_ids or _pack_id_exists(packs_root, tok):
                continue
            citing = out.setdefault(tok, [])
            if pack.name not in citing:
                citing.append(pack.name)
    return out


def _deferral_kind(packs_root: Path, tok: str) -> str:
    """The remedy for an unresolved id, READ FROM THE FOLDERS WHEN VISIBLE:
    a pack that landed (Done/, Merged/, Scrapped/ on the dev tree) is re-keyed
    to its title or its landing commit, 1-F's rule; an id that names no pack
    file on this tree is cited by the event's date, dropped, or -- if it really
    is a deferral into a pack nobody wrote yet -- the pack is authored. Message
    text only: the verdict above never depends on a folder the seed tree lacks."""
    if packs_root.is_dir():
        for hit in sorted(packs_root.rglob(f"{tok}-*.md")):
            parts = hit.relative_to(packs_root).parts
            if any(part.startswith(".") for part in parts) or len(parts) < 2:
                continue
            return f"landed in {parts[0]}/ -- cite its title or landing commit"
    return "no pack file on this tree -- cite the event by its date or drop the id; author the pack only if this is a deferral into one"


_SCOPE_OUT_READER_ABSENT = _scope_out is None  # scripts/ is dev tooling; absent off-host

#: A one-section ledger in the generator's grammar, for the gate's fixtures.
_SECTION_LEDGER = "# ledger\n\n### §C1 - A class\n\n| id | site | what | sev |\n|---|---|---|---|\n{row}\n"


@pytest.mark.skipif(_SCOPE_OUT_READER_ABSENT, reason="self-host only: scripts/check_pack_landing.py absent")
class TestScopeOutDeferralsResolve:
    @staticmethod
    def _tree(tmp_path, rel, scope_out, ledger_text="# ledger\n(nothing)\n", extra=()):
        packs = tmp_path / "task-packs"
        (packs / "Deferred").mkdir(parents=True)
        path = packs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # the Reach names TP-777, which exists nowhere: ownership, not deferral
        path.write_text(f"# stub\n\n## Scope (out)\n{scope_out}\n## Reach\n- TP-777 owned here\n",
                        encoding="utf-8")
        for e in extra:
            (packs / e).parent.mkdir(parents=True, exist_ok=True)
            (packs / e).write_text("# stub\n", encoding="utf-8")
        ledger = packs / "FORWARD_LEDGER.md"
        ledger.write_text(ledger_text, encoding="utf-8")
        return packs, ledger

    def test_a_deferral_into_a_pack_nobody_wrote_is_reported(self, tmp_path):
        packs, ledger = self._tree(tmp_path, "Deferred/TP-1-a.md", "- the rest goes to TP-999\n")
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {
            "TP-999": ["TP-1-a.md"]}

    def test_a_pack_file_in_a_shipped_location_resolves_it(self, tmp_path):
        packs, ledger = self._tree(tmp_path, "TP-1-a.md", "- the rest goes to TP-999\n",
                                   extra=("Deferred/TP-999-parked.md",))
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {}

    def test_a_landed_pack_does_not_resolve_it_and_is_named_as_landed(self, tmp_path):
        # The seed tree has no Done/, so the verdict cannot read it; the message can.
        packs, ledger = self._tree(tmp_path, "TP-1-a.md", "- the rest goes to TP-999\n",
                                   extra=("Done/TP-999-landed.md",))
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {
            "TP-999": ["TP-1-a.md"]}
        assert _deferral_kind(packs, "TP-999").startswith("landed in Done/")
        assert _deferral_kind(packs, "TP-998").startswith("no pack file on this tree")

    def test_a_live_ledger_row_resolves_it(self, tmp_path):
        packs, ledger = self._tree(tmp_path, "TP-1-a.md", "- the rest goes to TP-999\n",
                                   ledger_text=_SECTION_LEDGER.format(row="| `TP-999` | site | drafted, unwritten | minor |"))
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {}

    def test_a_struck_row_does_not_resolve_it(self, tmp_path):
        packs, ledger = self._tree(tmp_path, "TP-1-a.md", "- the rest goes to TP-999\n",
                                   ledger_text=_SECTION_LEDGER.format(row="| ~~`TP-999`~~ | site | closed | minor |"))
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {
            "TP-999": ["TP-1-a.md"]}

    def test_a_mention_outside_scope_out_is_not_a_deferral(self, tmp_path):
        packs, ledger = self._tree(tmp_path, "TP-1-a.md", "- nothing deferred\n")
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {}

    def test_a_prior_art_mention_of_a_vanished_pack_is_reported_too(self, tmp_path):
        # The LIVE shape (failure-mode pass, 2026-09-21): nine of the ten
        # baselined ids are prose like this, not forward deferrals. The gate
        # reads the id, whatever the sentence; the message names the remedy.
        packs, ledger = self._tree(tmp_path, "TP-1-a.md",
                                   "- the grammar is unchanged from TP-999's 999-F\n")
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {
            "TP-999": ["TP-1-a.md"]}
        assert _deferral_kind(packs, "TP-999").startswith("no pack file on this tree")

    def test_a_crosswalk_row_does_not_resolve_a_pack_id(self, tmp_path):
        # Only a class section's live member row counts as "a live row"; an
        # Appendix A crosswalk row that opens the same way must not keep
        # resolving a pack after it lands (code review, 2026-09-21).
        packs, ledger = self._tree(tmp_path, "TP-1-a.md", "- the rest goes to TP-999\n",
                                   ledger_text="# ledger\n\n## Appendix A\n\n| `TP-999` | crosswalk | x |\n")
        assert _unresolved_scope_out_deferrals((packs, packs / "Deferred"), packs, ledger) == {
            "TP-999": ["TP-1-a.md"]}


@pytest.mark.skipif(_SCOPE_OUT_READER_ABSENT or not _LEDGER.is_file(),
                    reason="self-host only: FORWARD_LEDGER.md or scripts/ absent")
def test_every_pack_an_active_scope_out_defers_into_resolves():
    """EXACT dated baseline, the dangling-citation test's shape, same on every tree.

    Measured 2026-09-21 (TP-452 1-H) on the 27 active packs under the shipped-location
    rule: ten ids in ten citing packs, seven of them in Deferred/. Eight name packs
    that LANDED and so left the shipped locations (TP-257, TP-266, TP-272, TP-327,
    TP-340, TP-432, TP-436, TP-447); two are dated references to ids that name no
    pack file on this tree (TP-212, a 2026-06-23 incident, in TP-248; TP-130, a
    fan-out, in TP-338). Read line by line (failure-mode pass), nine are prior-art
    prose and one (TP-447) an ownership pointer to a pack that landed: NOT ONE is a
    forward deferral into a pack nobody wrote, so the class DEF-412e names has zero
    live instances and every entry here is `DEF-914`'s (1-F's re-key class, applied
    to packs). An entry leaves this set when its citation is re-keyed to the pack's
    title or commit, to the event's date, or dropped -- the message says which per
    entry; a NEW entry is a citation the public reader cannot follow.
    """
    found = _unresolved_scope_out_deferrals(_ACTIVE_PACK_DIRS, _PACKS, _LEDGER)
    baseline = {"TP-130", "TP-212", "TP-257", "TP-266", "TP-272", "TP-327", "TP-340",
                "TP-432", "TP-436", "TP-447"}
    new = {k: (v, _deferral_kind(_PACKS, k)) for k, v in found.items() if k not in baseline}
    repaired = sorted(baseline - set(found))
    assert not new and not repaired, (
        "active packs' Scope (out) pack citations moved off the 2026-09-21 baseline.\n"
        f"  NEW (each entry names its remedy): {new}\n"
        f"  Now resolved (DELETE these from `baseline` in this test): {repaired}"
    )


@pytest.mark.skipif(_SCOPE_OUT_READER_ABSENT or not _LEDGER.is_file(),
                    reason="self-host only: FORWARD_LEDGER.md or scripts/ absent")
def test_every_active_pack_has_a_scope_out_the_readers_can_find():
    """The two readers above are calibrated on a heading spelling (217 of 221
    packs exact, 27 of 27 active); a pack that drops the section or spells it
    `## Out of scope` would be read as having no deferrals -- the strike guard
    allows, the gate finds nothing, no red. This pins the population the
    calibration rests on (failure-mode pass, 2026-09-21): 27 of 27 today."""
    silent = sorted(p.name for p in _shared_pack_files(_ACTIVE_PACK_DIRS)
                    if not _scope_out(p.read_text(encoding="utf-8")).strip())
    assert not silent, (
        "active packs whose Scope (out) the readers cannot find (spell the heading "
        f"`## Scope (out)`, or write the section): {silent}"
    )


# ---------------------------------------------------------------------------
# Count consistency: the ledger as an instance of its own §C11.
#
# §C11 is "a tracker row states a measurement nothing re-derives, so its status
# goes false silently", and the ledger has been the largest live instance of it:
# 40 tests in this module and, until now, ZERO count assertions. Measured on
# 2026-08-15, the §2 headline overstated live issues by ~17 while the member
# column UNDERSTATED total rows by ~15 -- drift in both directions at once,
# because rows get appended without bumping a header and struck without
# decrementing one.
#
# These derive BOTH sides and compare. They never hard-code a number, so they
# cannot themselves go stale (STANDING_PRINCIPLES §14, "derive the list, don't
# test a hand-written copy of it").
# ---------------------------------------------------------------------------

# The ledger's grammar has ONE home: scripts/generate_ledger_regions.py, the
# generator that writes these regions. Re-implementing the parsers here would
# have created a second hand-kept copy of the grammar -- which is the defect
# class that generator exists to close, reproduced inside its own contract.
# Importing them also means this suite validates the generator's parsing.
_GEN = _ROOT / "scripts" / "generate_ledger_regions.py"
if _GEN.is_file():
    sys.path.insert(0, str(_ROOT / "scripts"))
    from generate_ledger_regions import _is_struck, ledger_sections as _ledger_sections  # noqa: E402
    from generate_ledger_regions import (  # noqa: E402
        _CLASS_TABLE_ROW,
        _FLOOR_AUDIENCE,
        _FLOOR_POPULATION,
        _FLOOR_ROWS,
        _FLOOR_SECTIONS,
        _MEMBER_ROW,
        _SECTION_HEADING,
        declared_class_table as _declared_class_table,
        derive as _derive,
        live_cell_ids as _live_cell_ids,
        live_member_ids as _live_member_ids,
    )
else:  # adopter / fresh clone: dev tooling absent -> the ledger tests skip anyway
    _CLASS_TABLE_ROW = _MEMBER_ROW = _SECTION_HEADING = None
    _declared_class_table = _ledger_sections = _live_member_ids = _derive = None
    _live_cell_ids = None
    _FLOOR_ROWS = _FLOOR_SECTIONS = _FLOOR_POPULATION = _FLOOR_AUDIENCE = None

# The anti-vacuity floors below are the generator's, not this file's: one dated
# snapshot dict there, every floor derived as HALF of it, re-derived from the
# pre-rebuild record file by tests/test_generate_ledger_regions.py. A literal
# here was the class the 2026-09-20 rebuild tripped on -- five `>= 150`/`>= 100`
# pins over a file the cut left at exactly 150 member rows, every one of them a
# target the next honest strike would cross (TP-452 1-D).


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_class_table_member_counts_match_their_sections():
    """Every `members` cell in §2's class table equals the rows in that section."""
    text = _LEDGER.read_text(encoding="utf-8")
    declared = _declared_class_table(text)
    sections = _ledger_sections(text)
    assert len(declared) >= _FLOOR_SECTIONS and sum(len(v) for v in sections.values()) >= _FLOOR_ROWS, (
        f"the parser found {len(declared)} declared classes and "
        f"{sum(len(v) for v in sections.values())} member rows, which cannot be right -- "
        "the matcher has broken and every assertion below would pass vacuously. "
        "Fix _CLASS_TABLE_ROW / _MEMBER_ROW, do not weaken this floor."
    )
    # The floor above counts POPULATION, and a population count is structurally
    # blind to a KEYING defect. Proven: widening `_SECTION_HEADING`'s capture
    # group to include the section title -- a natural "nicer error message"
    # edit -- keeps 26 sections and 263 rows, so the floor stays green, while
    # every `name in sections` lookup below goes false and the drift dict is
    # unconditionally empty. Both name-keyed tests then pass having checked
    # nothing. Comparing the key SETS is the only thing that catches it.
    assert set(declared) == set(sections), (
        "the class table and the section headings no longer agree on class "
        f"KEYS. Only in the table: {sorted(set(declared) - set(sections))}. "
        f"Only as a section: {sorted(set(sections) - set(declared))}. Until "
        "these match, every per-class comparison below silently checks nothing "
        "-- so fix the keying (usually `_CLASS_TABLE_ROW` or `_SECTION_HEADING` "
        "capturing different text), never the assertions."
    )
    unparseable = sorted(n for n, (total, _l) in declared.items() if total is None)
    assert not unparseable, (
        f"class table cells with no readable member count: {unparseable}. A "
        "placeholder there removes that class from every check below, so fill "
        "the count in rather than leaving it to be derived later."
    )
    drift = {
        name: (n, len(sections.get(name, [])))
        for name, (n, _live) in declared.items()
        if name in sections and n != len(sections[name])
    }
    assert not drift, (
        f"§2 class-table member counts disagree with their sections, "
        f"class -> (declared, actual): {drift}. RE-DERIVE the cell from the section; "
        "do not adjust the section to match the cell. A row was almost certainly "
        "appended or struck without the table being touched -- which is §C11, the "
        "class this very file documents."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_declared_live_splits_match_the_struck_rows():
    """Where a class cell declares `(N live, M closed)`, N must be the unstruck rows.

    A struck id (`| ~~`) is the file's own closed marker -- the same signal
    `How to read a status tag` describes.

    The rule is mechanical on purpose: several rows describe one closed arm and
    one open one in prose (`DEF-410i` is the live example), and the strike is
    the only signal a parser can trust. Those rows are correctly counted LIVE
    because they are not struck -- checked, rather than assumed: an earlier
    draft of this docstring cited one as "struck in one arm", and it carries no
    `~~` at all. A rule that tried to read the prose would be guessing.
    """
    text = _LEDGER.read_text(encoding="utf-8")
    sections = _ledger_sections(text)
    declared = _declared_class_table(text)
    assert set(declared) == set(sections), (
        "class keys disagree between the table and the section headings; see "
        "test_class_table_member_counts_match_their_sections for why that makes "
        "this comparison vacuous rather than merely incomplete."
    )
    drift = {}
    for name, (_total, live) in declared.items():
        if live is None or name not in sections:
            continue
        actual = sum(1 for r in sections[name] if not r.lstrip("| ").startswith("~~"))
        if actual != live:
            drift[name] = (live, actual)
    assert not drift, (
        f"declared live counts disagree with the unstruck rows, "
        f"class -> (declared, actual): {drift}. If a member was closed, STRIKE the "
        "id and fix the cell in the same edit -- the two halves drifting apart is "
        "how the count goes false silently."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_headline_live_total_matches_the_sections():
    """§2's `N LIVE issues` header equals the unstruck rows across all classes."""
    text = _LEDGER.read_text(encoding="utf-8")
    m = re.search(r"##\s*§2[^\n]*?\((\d+) LIVE issues", text)
    assert m, (
        "§2's header no longer states a live count in the form "
        "'(N LIVE issues in ...)'. If the wording moved, re-point this regex; if "
        "the number was DELETED to dodge the drift, put it back -- an unstated "
        "total is not an accurate one."
    )
    sections = _ledger_sections(text)
    actual = sum(
        1 for rows in sections.values() for r in rows if not r.lstrip("| ").startswith("~~")
    )
    assert int(m.group(1)) == actual, (
        f"§2 declares {m.group(1)} LIVE issues; the sections carry {actual} unstruck "
        "member rows. Re-derive the header from the sections. This drifted by 17 "
        "once already because nothing re-computed it."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_every_live_row_has_a_population_and_an_audience_and_each_is_counted_once():
    """Both directions of the audience/population vocabulary, on the live file.

    The §2 audience figure read 62 from 2026-08-31 through 63 closures because
    it was typed, not derived. Derivation alone is not enough: a row whose tag
    nothing recognises would simply not be counted, and the table would be
    exact over a population that silently lost members. So: every live row
    resolves to one population and one audience (the closed-world arm --
    `tag_problems` is empty), and the per-token counts sum to the live total
    (every row counted exactly once). The generator's `--check` gate holds
    the printed tables to these numbers.
    """
    d = _derive(_LEDGER.read_text(encoding="utf-8"))
    assert d["live_total"] >= _FLOOR_ROWS, "live-row floor collapsed; the parser has broken"
    assert d["tag_problems"] == [], (
        "live rows that resolve to no population or audience:\n  "
        + "\n  ".join(d["tag_problems"])
        + "\nA MIXED-class row (§C0) carries its own `pop | aud` cells; a classed "
        "row inherits from the class index. Fix the row or the index cell -- never "
        "widen the vocabulary to make a misspelling count."
    )
    assert sum(d["population_live"].values()) == d["live_total"]
    assert sum(d["audience_live"].values()) == d["live_total"]
    # Parse-sanity floors, not targets: they catch the tags being read as
    # something other than what the rows say (a vocabulary rename, a cell
    # shift), which collapses a figure to zero. The ADOPTER floor was 30 when
    # the audience held 60-odd rows; TP-449 trimmed it to 19 live rows by
    # 2026-09-12 (28 -> 16 minors and nits in one group), so 30 became a
    # target the trimming was always going to cross. Ten still separated a
    # parser collapse from a roster until 2026-09-13, when group 9 left 7 live
    # ADOPTER rows, and ONE still separated "the tags parsed as something else"
    # (which reads zero) from a roster.
    #
    # ⚠ THE ROSTER REACHED ZERO ON 2026-09-19, which is what the note above
    # said to watch for. The last eight live ADOPTER rows (DEF-836, 844, 845,
    # 851, 852, 853, 854, 855 -- every one of them on the delete guard's reader
    # surface) were struck as DECLARED LIMITS rather than fixed: each is now
    # named in `docs/HOOKS.md` or `docs/SHARP_EDGES.md` and pinned by a row
    # that reds the day a reader closes it. So a live-ADOPTER floor now asserts
    # a roster that is deliberately empty, and lowering it to zero would assert
    # nothing. It moved to the STRUCK side on 2026-09-19 (`audience_struck`).
    #
    # ⚠ THE STRUCK SIDE LEFT THE FILE ON 2026-09-20. The rebuild (TP-452 1-D)
    # moves every struck row to the record branch, so `audience_struck` is all
    # zeros on the file that ships and the struck-side floor was a false red on
    # it. The floors now sit where the generator puts them: on the tag each
    # axis carries MOST (MAINTAINER, HYGIENE -- 141 and 104 at the rebuild's
    # snapshot), at half that figure, derived from the record file. A
    # vocabulary rename or a cell shift reads as zero there while the row
    # total stays put, which is the collapse this ever watched for; a LOGIC_BUG
    # floor of 30 was four rows from a target (34 live) and is retired with it.
    pop_tag, pop_floor = _FLOOR_POPULATION
    aud_tag, aud_floor = _FLOOR_AUDIENCE
    assert d["population_live"][pop_tag] >= pop_floor and d["audience_live"][aud_tag] >= aud_floor, (
        f"a tag floor collapsed ({pop_tag} {d['population_live'][pop_tag]} against {pop_floor}; "
        f"{aud_tag} {d['audience_live'][aud_tag]} against {aud_floor}) -- the tags parsed as "
        "something other than what the rows say. The floors are the generator's, derived "
        "from the pre-rebuild record; do not raise or retype them here"
    )


class TestLedgerCountParsers:
    """Synthetic battery for `_ledger_sections` / `_declared_class_table`.

    The convention every other parser in this file already follows
    (`TestOrphanDetection`, `TestLandedRowLingering`, `TestDanglingIdReferences`):
    prove the parsing logic red and green against a small deterministic string,
    so the proof survives independently of whatever the live ledger currently
    contains. The live-ledger tests above cannot do that -- the ledger is
    gitignored, so the drift they were written against is already gone and not
    reproducible by anyone else.

    That gap was not theoretical. Without these, a widening of
    `_SECTION_HEADING`'s capture group left two of the three live tests passing
    while checking nothing, and the anti-vacuity floor stayed green throughout
    because it counts population and the defect was in the KEYS.
    """

    _DOC = (
        "## §2 — Open fixes, by root cause (3 LIVE issues in 2 classes)\n"
        "\n"
        "| § | class | members | gating | effort |\n"
        "|---|---|---|---|---|\n"
        "| [§C1](#c1) | first class | 2 | — | small |\n"
        "| [§C2](#c2) | second class | 2 (**1 live**, 1 closed) | — | small |\n"
        "\n"
        "### §C1 — first class\n"
        "\n"
        "| id | site | what | severity |\n"
        "|---|---|---|---|\n"
        "| `DEF-1` | `a.py` | one | minor |\n"
        "| `DEF-2` | `b.py` | two | nit |\n"
        "\n"
        "### §C2 — second class\n"
        "\n"
        "| `DEF-3` | `c.py` | three | major |\n"
        "| ~~`DEF-4`~~ | `d.py` | ✅ **CLOSED** four | major |\n"
        "\n"
        "## §3 — New features\n"
        "\n"
        "| `TP-9` | `e.py` | not a member of any class | nit |\n"
    )

    def test_sections_are_bounded_by_the_next_class_heading(self):
        s = _ledger_sections(self._DOC)
        assert sorted(s) == ["§C1", "§C2"]
        assert len(s["§C1"]) == 2

    def test_the_last_section_stops_at_the_next_h2_not_at_eof(self):
        """The bug this battery exists for. §C0 is the last class section and
        the file continues into §3..§7 and an appendix index of several hundred
        rows; a boundary that runs to EOF swept them all in and counted 627
        members against a true 212."""
        s = _ledger_sections(self._DOC)
        assert len(s["§C2"]) == 2, "the §3 row leaked into the last class section"
        assert not any("TP-9" in r for r in s["§C2"])

    def test_struck_and_unstruck_rows_are_told_apart(self):
        s = _ledger_sections(self._DOC)
        live = [r for r in s["§C2"] if not r.lstrip("| ").startswith("~~")]
        assert len(live) == 1 and "DEF-3" in live[0]

    def test_both_declared_cell_shapes_parse(self):
        d = _declared_class_table(self._DOC)
        assert d["§C1"] == (2, None), "a bare total should declare no live split"
        assert d["§C2"] == (2, 1), "an annotated cell should yield total and live"

    def test_an_unparseable_members_cell_is_recorded_not_dropped(self):
        """Dropping it removed the class from every downstream comparison,
        silently and permanently."""
        doc = self._DOC.replace("| [§C1](#c1) | first class | 2 |",
                                "| [§C1](#c1) | first class | — |")
        d = _declared_class_table(doc)
        assert "§C1" in d, "the class vanished from the declared set"
        assert d["§C1"] == (None, None)

    def test_the_key_sets_agree_so_a_keying_defect_cannot_pass(self):
        """Directly pins the mutation the population floor cannot see: if the
        table and the headings key differently, every per-class lookup goes
        false and the drift dicts are empty for the wrong reason."""
        d = _declared_class_table(self._DOC)
        s = _ledger_sections(self._DOC)
        assert set(d) == set(s)

    def test_header_and_separator_rows_are_not_counted_as_members(self):
        s = _ledger_sections(self._DOC)
        assert not any(r.startswith("| id |") or "---" in r for r in s["§C1"])


# Rows where `_MEMBER_ROW` (used by the count contracts) and `_is_member_row`
# (used by the landed-row guard) disagree about what a member row is. Both live
# in this file and were authored independently, which is the "one policy, N
# independently-authored predicates" shape the ledger itself catalogues.
#
# `_MEMBER_ROW` is the correct side on every current disagreement.
# `_is_member_row` splits naively on `|`, so a row whose prose contains a pipe
# (a regex character class, say) mis-splits and fails its 4-or-6-cell check; and
# its severity vocabulary omits two tokens the file actually uses. Both are
# false NEGATIVES, and today they are unreachable in its only caller, which
# pre-filters to rows carrying a `TP-` id. So this is a ratchet, not a fix:
# reconciling the predicates means changing a guard with its own synthetic
# battery and live baseline, which is its own piece of work.
# Lowered 7 -> 1 by the 2026-08-20 rebuild: every generated member row now
# carries the pinned shape (4 cells, or 6 with the MIXED-class tags since
# 2026-09-08; severity in the fourth cell either way), so the two predicates
# disagree on exactly one legacy row. Lowered per this test's own ratchet
# instruction, so the freed space cannot silently absorb a NEW disagreement.
_PREDICATE_DISAGREEMENT_CEILING = 0  # reconciled 2026-09-08: both split on unescaped pipes


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_the_two_member_row_predicates_do_not_diverge_further():
    """Two definitions of "member row" in one file, pinned against each other.

    Neither is asked to be right here -- only to stay as far apart as they are.
    Without this the divergence is invisible: each predicate has its own tests,
    both pass, and nothing compares them.
    """
    rows = [r for v in _ledger_sections(_LEDGER.read_text(encoding="utf-8")).values() for r in v]
    disagreements = [r for r in rows if not _is_member_row(r)]
    assert rows, "no member rows parsed at all -- the matcher broke"
    assert len(disagreements) <= _PREDICATE_DISAGREEMENT_CEILING, (
        f"the two member-row predicates now disagree on {len(disagreements)} rows "
        f"(ceiling {_PREDICATE_DISAGREEMENT_CEILING}). Examples: "
        f"{[r[:70] for r in disagreements[:3]]}. Reconcile them -- do NOT raise "
        "this ceiling to make the red go away; that is how two rival definitions "
        "of the same concept drift apart permanently."
    )
    if len(disagreements) < _PREDICATE_DISAGREEMENT_CEILING:
        pytest.fail(
            f"the predicates now agree on more rows ({len(disagreements)} < "
            f"{_PREDICATE_DISAGREEMENT_CEILING}). Good -- lower "
            "_PREDICATE_DISAGREEMENT_CEILING to the new count in this commit, so "
            "the ratchet cannot silently absorb a NEW disagreement in the space "
            "you just freed."
        )


# ---------------------------------------------------------------------------
# Id uniqueness -- an id must name exactly one row, and Appendix B must resolve
# it to the section that actually holds it.
#
# Appendix A2 already states this rule for section numbers ("retired, NOT
# reused, so an archival citation fails to resolve rather than silently
# resolving to a different topic"); ids were never held to it. Two collisions
# (`DEF-583` across §C2/§C14 and `DEF-556` across §C0/§C17) were minted eleven
# days after a census row recorded "3 lines are duplicate definitions (`DEF-20`
# at least)" and hedged it into invisibility, and one recurred the day after
# being deferred.
#
# NOTHING ABOVE COULD SEE THEM. The count contracts compare a declared total
# against len(rows), and a duplicate id does not change a row count -- §C14 read
# 5 rows against 5 declared while carrying two rows under one key. The damage is
# in the KEY, so only a key-shaped assertion reaches it (the same lesson
# `test_class_table_member_counts_match_their_sections` records above).
#
# The prefix is deliberately NOT enumerated. A hand-listed
# (DEF|DEC|INV|TP|LG|...) alternation is the "declared population" class this
# ledger tracks as §C1 -- a first cut of it silently scored `SUP-2` as owning no
# id at all. Match the SHAPE.
# ---------------------------------------------------------------------------

_OWNED_ID_LEAD = re.compile(r"^\s*(?:~~)?`([A-Z][A-Z0-9]{1,6}-\d+[a-z]*)`(?:~~)?\s*")
_ID_IN_CELL = re.compile(r"`([A-Z][A-Z0-9]{1,6}-\d+[a-z]*)`")
_APPENDIX_B_ROW = re.compile(
    r"^\|\s*(?:~~)?`([A-Z][A-Z0-9]{1,6}-\d+[a-z]*)`(?:~~)?"
    r"(?:\s+(?:~~)?`([A-Z][A-Z0-9]{1,6}-\d+[a-z]*)`(?:~~)?)?\s*\|\s*(§C\d+)\s*\|"
)


def _first_cell(row: str) -> str:
    """The first cell, split on the first `|` OUTSIDE a backtick code span.

    `row.split("|")[1]` truncates a cell whose prose quotes a `|` in backticks,
    which this ledger does -- the same naive-split bug class the file already
    records for `_is_member_row` at `_PREDICATE_DISAGREEMENT_CEILING`. Measured:
    0 of 264 live rows split differently, so this guards the convention rather
    than repairing a live break.

    ⚠ RESIDUAL, KNOWN, NOT CLOSED -- it deliberately does NOT rescue a cell that
    joins two owned ids with a pipe (``| `DEF-582`|`LG-18` |`` yields only
    `DEF-582`). An unquoted `|` IS a markdown cell boundary, so that row is a
    malformed FIVE-cell row against a four-cell schema, not a mis-extraction;
    rescuing it here would mean this helper deciding that some cell boundaries
    are not boundaries. The cost is real and worth stating plainly: a co-owned id
    lost that way is invisible to BOTH assertions below -- the row still yields
    an id, so the non-vacuity floor stays green, and the dropped id never enters
    the uniqueness comparison. Row-shape validation is `_is_member_row`'s job and
    it has its own ratchet. `test_a_pipe_joined_id_cell_is_a_malformed_row`
    pins this so the blind spot stays tested rather than merely true.
    """
    in_span = False
    for i, ch in enumerate(row[1:], start=1):  # row[0] is the opening pipe
        if ch == "`":
            in_span = not in_span
        elif ch == "|" and not in_span:
            return row[1:i]
    return row[1:]


def _owned_ids(row: str) -> list[str]:
    """The ids a member row ASSIGNS, not every id its first cell mentions.

    Consumes the leading run of backticked ids and stops at the first token that
    is not one. A row legitimately owns several (`| \\`DEF-582\\` \\`LG-18\\` |`;
    one §C24 row owns three), but a row may also CITE another id in prose after its
    own -- ``~~`DEF-425`~~ - CLOSED (with `DEF-455`; ...)`` owns one id and
    mentions a second. Taking every id in the cell reads that as a collision and
    invites a hand-written exception for the one row it misreads; consuming only
    the leading run is the rule that needs no exception list.
    """
    owned, rest = [], _first_cell(row)
    while (match := _OWNED_ID_LEAD.match(rest)):
        owned.append(match.group(1))
        rest = rest[match.end():]
    return owned


def _ids_with_strike(cell: str) -> list[tuple[str, bool]]:
    """[(id, struck), ...] for a cell, resolving strike PER ID.

    The obvious spelling -- one `line.startswith("~~")` applied to every id the
    row owns -- is wrong on a mixed row, and wrong in both directions. Driven:
    ``| ~~`DEF-3`~~ `DEF-4` |`` marked BOTH struck, which makes the dangling
    check skip a genuinely broken pointer; ``| `DEF-1` ~~`DEF-2`~~ |`` marked
    both live, which makes it demand a "fix" to a correctly-authored tombstone.
    The second is the worse half: a false negative in the exact class the check
    exists to catch.

    Scanned rather than regexed because ``~~`` binds three different ways in the
    live file -- per id (``~~`A`~~ ~~`B`~~``), around a group (``~~`A` `B`~~``,
    which §C4 uses), and asymmetrically. Toggling on each ``~~`` and reading the
    state at each id resolves all three; a per-id regex group cannot see the
    group form at all. Same shape as ``_first_cell``'s backtick scan.
    """
    out: list[tuple[str, bool]] = []
    in_strike, i = False, 0
    while i < len(cell):
        if cell.startswith("~~", i):
            in_strike = not in_strike
            i += 2
            continue
        if (match := _ID_IN_CELL.match(cell, i)):
            out.append((match.group(1), in_strike))
            i = match.end()
            continue
        i += 1
    return out


def _appendix_b_rows(text: str) -> list[tuple[str, str, bool]]:
    """Every index assignment as (id, section, struck), in file order.

    A LIST, not a dict, and that is the whole point: a dict keyed by id
    reproduces the exact collapse Appendix A4 records as this defect's ROOT
    CAUSE -- the index could hold only one of the two rows sharing an id, so it
    kept the later one and silently dropped the earlier, and §C0 declared 26
    members against 25 indexed for as long as that lasted. A checker built to
    catch a keying collapse must not be built on one.

    A struck row is indexed on purpose (Appendix B says so: a closed entry is
    kept "so a citation to it resolves to its class instead of dead-ending"), so
    strikethrough is PARSED and carried, never skipped -- the flag is what lets
    the dangling check below tell a deliberate tombstone from a broken pointer.
    """
    rows: list[tuple[str, str, bool]] = []
    for line in text.splitlines():
        if (match := _APPENDIX_B_ROW.match(line)):
            for ident, struck in _ids_with_strike(_first_cell(line)):
                rows.append((ident, match.group(3), struck))
    return rows


def _appendix_b_index(text: str) -> dict[str, str]:
    """{id: '§CN'}. Collapses duplicates last-wins by construction -- which is
    why `test_appendix_b_assigns_each_id_exactly_once` guards the list form
    separately rather than trusting this dict to notice."""
    return {ident: section for ident, section, _struck in _appendix_b_rows(text)}


def _id_homes(text: str) -> dict[str, list[str]]:
    """{id: [section, ...]} across every §C member row. A well-formed ledger
    gives every id exactly one home."""
    homes: dict[str, list[str]] = {}
    for section, rows in _ledger_sections(text).items():
        for row in rows:
            for ident in _owned_ids(row):
                homes.setdefault(ident, []).append(section)
    return homes


class TestLedgerIdUniqueness:
    """The extractor and both live invariants, driven on synthetic trees.

    These synthetic cases are the reason the helpers are module-level functions
    rather than expressions inlined in the assertions: on the real ledger the
    correct and the naive spelling now BOTH read green, so only a test that
    calls the predicate with a hand-built collision can tell them apart.
    """

    _INDEX_HEAD = "## Appendix B -- id index\n\n"

    def _tree(self, sections: str, index: str = "") -> str:
        return f"{sections}\n{self._INDEX_HEAD}{index}"

    def test_duplicate_id_across_two_sections_is_reported(self):
        text = self._tree(
            "### §C1 - first\n"
            "| `DEF-1` | `a.py` | a thing | major |\n"
            "\n### §C2 - second\n"
            "| `DEF-1` | `b.py` | a different thing | nit |\n"
        )
        assert _id_homes(text)["DEF-1"] == ["§C1", "§C2"]

    def test_duplicate_id_within_one_section_is_reported(self):
        text = self._tree(
            "### §C1 - first\n"
            "| `DEF-1` | `a.py` | a thing | major |\n"
            "| `DEF-1` | `b.py` | a different thing | nit |\n"
        )
        assert _id_homes(text)["DEF-1"] == ["§C1", "§C1"]

    def test_a_distinct_id_per_row_is_clean(self):
        text = self._tree(
            "### §C1 - first\n"
            "| `DEF-1` | `a.py` | a thing | major |\n"
            "| `DEF-2` | `b.py` | another | nit |\n"
        )
        assert all(len(v) == 1 for v in _id_homes(text).values())

    def test_a_prose_citation_after_the_owned_id_is_not_an_assignment(self):
        """The live shape that a naive "every id in the cell" reading misreads."""
        row = "| ~~`DEF-425`~~ CLOSED (with `DEF-455`; `tests/t.py`) | `cli.py` | x | major |"
        assert _owned_ids(row) == ["DEF-425"]

    def test_a_row_owning_several_ids_is_read_as_owning_all_of_them(self):
        assert _owned_ids("| `DEF-582` `LG-18` | `-` | x | major |") == ["DEF-582", "LG-18"]
        assert _owned_ids("| ~~`DEF-417i` `DEF-417j`~~ | `-` | x | nit |") == [
            "DEF-417i",
            "DEF-417j",
        ]

    def test_a_backticked_pipe_in_cell_prose_does_not_truncate_the_cell(self):
        """The naive `row.split("|")[1]` face. This ledger quotes regexes."""
        row = "| `DEF-1` `LG-2` (see `a|b`) | `x.py` | t | nit |"
        assert _first_cell(row) == " `DEF-1` `LG-2` (see `a|b`) "
        assert _owned_ids(row) == ["DEF-1", "LG-2"]

    def test_a_pipe_joined_id_cell_is_a_malformed_row(self):
        """Pins the documented blind spot in `_first_cell` so it stays tested.

        An unquoted `|` is a real cell boundary, so this row has five cells
        against a four-cell schema and `LG-18` is not in cell one at all. The
        extractor reports what the markdown says; it is NOT this helper's job to
        rule some boundaries out. If this ever starts mattering, fix it in row
        validation -- do not teach `_first_cell` to ignore pipes.
        """
        assert _owned_ids("| `DEF-582`|`LG-18` | `a.py` | t | major |") == ["DEF-582"]

    def test_an_unenumerated_prefix_still_yields_an_owned_id(self):
        """`SUP-2` is a live first-cell id. A hand-listed prefix alternation
        scored this row as owning nothing, which is how a uniqueness gate goes
        quietly blind to a whole prefix."""
        assert _owned_ids("| `SUP-2` | `x.py` | reachability | minor |") == ["SUP-2"]

    def test_index_pointing_at_the_wrong_section_is_reported(self):
        text = self._tree(
            "### §C1 - first\n| `DEF-1` | `a.py` | a thing | major |\n",
            "| `DEF-1` | §C9 | `a.py` |\n",
        )
        assert _appendix_b_index(text) == {"DEF-1": "§C9"}
        assert _id_homes(text)["DEF-1"] == ["§C1"]

    def test_index_spacing_is_tolerated_but_the_section_cell_is_not_guessed(self):
        """Cell padding varies under hand-editing; the §CN cell must still be a
        §CN. Loosening the spacing must not loosen what counts as a section."""
        text = self._tree("### §C1 - x\n| `DEF-1` | `a.py` | t | nit |\n",
                          "|  `DEF-1`  |  §C1  | `a.py` |\n")
        assert _appendix_b_index(text) == {"DEF-1": "§C1"}
        loose = self._tree("### §C1 - x\n| `DEF-1` | `a.py` | t | nit |\n",
                           "| `DEF-1` | see §C1 | `a.py` |\n")
        assert _appendix_b_index(loose) == {}, "a prose section cell is not an index entry"

    def test_two_index_rows_for_one_id_are_both_kept(self):
        """The dict form collapses them last-wins; the list form must not."""
        text = self._tree(
            "### §C1 - x\n| `DEF-1` | `a.py` | t | nit |\n",
            "| `DEF-1` | §C1 | `a.py` |\n| `DEF-1` | §C9 | `b.py` |\n",
        )
        assert [r[:2] for r in _appendix_b_rows(text)] == [("DEF-1", "§C1"), ("DEF-1", "§C9")]
        assert _appendix_b_index(text) == {"DEF-1": "§C9"}, "the dict loses the first"

    def test_struckness_is_carried_so_a_tombstone_differs_from_a_broken_pointer(self):
        text = self._tree(
            "### §C1 - x\n| `DEF-2` | `a.py` | t | nit |\n",
            "| ~~`DEF-1`~~ | §C1 | `a.py` |\n| `DEF-3` | §C1 | `c.py` |\n",
        )
        by_id = {i: struck for i, _s, struck in _appendix_b_rows(text)}
        assert by_id == {"DEF-1": True, "DEF-3": False}, (
            "DEF-1 is a deliberate tombstone, DEF-3 is a dangling pointer; the "
            "dangling check can only tell them apart if struckness survives parsing"
        )

    def test_strike_is_resolved_per_id_not_per_row(self):
        """A two-id row with MIXED strike state, both orderings.

        A per-line flag gets one of these wrong whichever way it guesses, and the
        second case is the dangerous one: marking a live id struck makes the
        dangling check skip a genuinely broken pointer.
        """
        assert _ids_with_strike(" `DEF-1` ~~`DEF-2`~~ ") == [("DEF-1", False), ("DEF-2", True)]
        assert _ids_with_strike(" ~~`DEF-3`~~ `DEF-4` ") == [("DEF-3", True), ("DEF-4", False)]

    def test_a_group_strike_marks_every_id_it_wraps(self):
        """`~~`A` `B`~~` -- the §C4 form. A per-id regex group cannot see it:
        the closing `~~` belongs to the second id and the opening to the first."""
        assert _ids_with_strike(" ~~`DEF-417i` `DEF-417j`~~ ") == [
            ("DEF-417i", True), ("DEF-417j", True),
        ]
        assert _ids_with_strike(" `DEF-582` `LG-18` ") == [("DEF-582", False), ("LG-18", False)]

    def test_a_mixed_strike_index_row_reaches_the_dangling_check_correctly(self):
        """End-to-end through `_appendix_b_rows`, not just the scanner: the live
        struck id is a tombstone, the live unstruck one with no member row is a
        broken pointer, and the two must not share a verdict."""
        text = self._tree(
            "### §C1 - x\n| `DEF-9` | `a.py` | t | nit |\n",
            "| ~~`DEF-7`~~ `DEF-8` | §C1 | `a.py` |\n",
        )
        assert sorted(_appendix_b_rows(text)) == [
            ("DEF-7", "§C1", True), ("DEF-8", "§C1", False),
        ]

    def test_a_struck_index_row_is_parsed_not_skipped(self):
        text = self._tree("### §C1 - x\n| `DEF-1` | `a.py` | t | nit |\n",
                          "| ~~`DEF-1`~~ | §C1 | `a.py` |\n")
        assert _appendix_b_index(text) == {"DEF-1": "§C1"}


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_every_member_row_assigns_at_least_one_id():
    """Non-vacuity floor for the two assertions below, derived from the row
    population rather than restated as a constant.

    If `_OWNED_ID_LEAD` stops matching a cell shape, that row contributes no ids
    and simply drops out of the uniqueness comparison -- silently, and exactly
    where a new collision would hide. Requiring every parsed member row to yield
    an id makes that failure loud instead. Do not exempt a row here; fix the
    regex, or the ledger row whose first cell is malformed.
    """
    text = _LEDGER.read_text(encoding="utf-8")
    rows = [r for v in _ledger_sections(text).values() for r in v]
    assert rows, "no member rows parsed at all -- the matcher broke"
    idless = [r[:90] for r in rows if not _owned_ids(r)]
    assert not idless, (
        f"{len(idless)} of {len(rows)} member rows assign no id: {idless[:3]}. "
        "Every one of those is invisible to the uniqueness check below."
    )
    # CONSERVATION IDENTITY. Everything above is a PER-ROW floor, and the
    # assertion it protects consumes `_id_homes`, a PER-ID aggregate -- so the
    # floor guards a different function than the one under test. Driven: three
    # separate narrowings of `_id_homes` (skip struck rows, take `_owned_ids(r)[:1]`,
    # skip §C0) each left the whole file GREEN while silently shrinking the
    # comparison population from 282 ids to as few as 220. The first is the one a
    # future session actually writes -- "closed rows shouldn't count for
    # uniqueness" -- and it is exactly backwards, because archival citations point
    # at CLOSED work, so that narrowing blinds the gate precisely where its stated
    # harm lives. Both sides derive from the same live file, so this cannot stale.
    assert sum(len(_owned_ids(r)) for r in rows) == sum(len(v) for v in _id_homes(text).values()), (
        "_id_homes dropped ids that the row population assigns, so the "
        "uniqueness comparison below is narrower than the ledger it claims to "
        "check. Do not exempt rows in _id_homes -- a struck row's id is exactly "
        "what an archival citation resolves to."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_every_ledger_id_names_exactly_one_row():
    """An id resolves to one row, or a citation to it resolves to the wrong work.

    Worse than a dead pointer: a dead one announces itself, a collided one reads
    as a successful lookup. See Appendix A4 for the two that shipped.
    """
    homes = _id_homes(_LEDGER.read_text(encoding="utf-8"))
    collisions = {k: v for k, v in homes.items() if len(v) > 1}
    assert not collisions, (
        f"ids assigned to more than one member row, id -> sections: {collisions}. "
        "RE-KEY the later claimant to a fresh id and record the move in Appendix "
        "A4. The first claimant by discovery date keeps the id. Do NOT repoint an "
        "archival citation to match -- `espalier.claim_extractor.RECORD_SURFACES` "
        "is the single home for which surfaces are records (ESPALIER_MEMORY.md and "
        "the blueprints are in it; note that `test_doc_source_citations."
        "_RECORD_SURFACE_DOCS` is a NARROWER, different-purpose set and answers "
        "this question wrongly). A live pointer -- cc/GOAL.md, cc/_working_summary.md "
        "-- does get updated."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_appendix_b_resolves_every_id_to_the_section_that_holds_it():
    """Appendix B calls itself "the lookup that replaces section-number
    navigation", so a wrong or missing entry is a broken lookup.

    ⚠ This arm did NOT catch the two collisions, and was driven against the
    unfixed tree to find that out rather than assumed to. The index is keyed by
    id, so when two rows shared one it held the later find and silently dropped
    the earlier -- §C0 declared 26 members against 25 indexed. But the surviving
    entry still resolved to a section that genuinely held a row with that id, so
    both assertions below passed. The collision MASKED its own second symptom;
    the symptom only became visible once `test_every_ledger_id_names_exactly_one_row`
    forced the re-key. This arm holds the index correct from here, and its own
    red was earned by mutation (mispoint, dropped entry, strikethrough-blind
    regex, and a parser matching nothing) -- not by the defect that motivated it.
    """
    text = _LEDGER.read_text(encoding="utf-8")
    homes, index = _id_homes(text), _appendix_b_index(text)
    assert len(index) >= _FLOOR_ROWS, (
        f"only {len(index)} Appendix B rows parsed -- _APPENDIX_B_ROW has broken "
        "and both assertions below would pass vacuously."
    )
    mispointed = {
        i: (index[i], homes[i][0]) for i in index if i in homes and index[i] not in homes[i]
    }
    assert not mispointed, (
        f"Appendix B sends a reader to a section that does not hold the row, "
        f"id -> (index says, actually in): {mispointed}. Repoint the INDEX."
    )
    unindexed = sorted(i for i in homes if i not in index)
    assert not unindexed, (
        f"{len(unindexed)} live ids have no Appendix B entry: {unindexed[:8]}. "
        "Every member row is reachable through the index or it is not reachable."
    )
    # The REVERSE direction, which the two assertions above cannot see: they walk
    # homes->index and skip any index id with no home (`if i in homes`), so an
    # entry pointing at a section that holds no such row passes silently -- the
    # precise thing this test's NAME promises does not happen. A struck entry
    # with no row is the file's deliberate tombstone ("kept so a citation
    # resolves to its class instead of dead-ending"); an UNSTRUCK one is just a
    # broken pointer, and six shipped that way.
    dangling = sorted(
        {i for i, _sec, struck in _appendix_b_rows(text) if not struck and i not in homes}
    )
    assert not dangling, (
        f"{len(dangling)} unstruck Appendix B entries point at a section that "
        f"holds no such row: {dangling}. STRIKE the entry when its row is closed "
        "and removed -- Appendix B's own convention -- or delete it. Do not "
        "delete the member row and leave a live-looking index entry behind."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
def test_appendix_b_assigns_each_id_exactly_once():
    """Two index rows for one id is the collision, one level up.

    Guarded on the LIST rather than `_appendix_b_index`, because that dict
    resolves a duplicate last-wins and would report the file clean -- the same
    silent collapse Appendix A4 records as the root cause. Latent today (zero
    duplicates); the trigger is a session appending a second entry while
    re-keying, which is the natural move, and a later one repairing only the row
    it happened to read first.
    """
    rows = _appendix_b_rows(_LEDGER.read_text(encoding="utf-8"))
    assert len(rows) >= _FLOOR_ROWS, (
        f"only {len(rows)} Appendix B assignments parsed -- _APPENDIX_B_ROW has "
        "broken and the assertion below would pass vacuously."
    )
    counts: dict[str, int] = {}
    for ident, _section, _struck in rows:
        counts[ident] = counts.get(ident, 0) + 1
    duplicated = {k: v for k, v in counts.items() if v > 1}
    assert not duplicated, (
        f"Appendix B lists these ids more than once, id -> rows: {duplicated}. "
        "The index is a lookup keyed by id; a second row for one id means a "
        "reader's answer depends on file order. Keep one entry per id."
    )


# ── Tier 2: every live row is re-measurable, or says why it is not ──────────
#
# ⚠ WHY THIS GATE EXISTS, and it is not hypothetical. `scripts/check_ledger_probes.py`
# has re-derived ledger rows since the 2026-08-20 rebuild, where it found 41 of
# 222 rows already dead. It works. What it could not do was notice a row that
# never got a probe: `LEDGER_PROBES.json` is a SNAPSHOT (`_generated`), so every
# row minted after it was written was invisible to the instrument by
# construction — including, on 2026-08-26, two rows minted an hour before this
# gate was authored, while re-cutting the very class they belong to.
#
# Same shape as the anchor census in tests/test_speedbump_irreversible.py, and
# the same rule: **probed OR declared, no third bucket.** A row with no local
# oracle is a real category — "re-enable Actions at the repo level" cannot be
# re-derived from this tree — so `why_not` is the honest half, not a loophole.
# What is forbidden is silence.

_PROBE_FILE = _LEDGER.parent / "LEDGER_PROBES.json"


def _probe_index() -> dict[str, dict]:
    import json
    return {p["id"]: p for p in json.loads(
        _PROBE_FILE.read_text(encoding="utf-8"))["probes"] if p.get("id")}


# _live_member_ids is imported above from the generator (single home).


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
@pytest.mark.skipif(not _PROBE_FILE.is_file(), reason="LEDGER_PROBES.json is self-host only")
def test_every_live_row_is_probed_or_declared():
    """No live row may be silently un-re-measurable."""
    text = _LEDGER.read_text(encoding="utf-8")
    live, probes = _live_member_ids(text), _probe_index()
    assert len(live) >= _FLOOR_ROWS, (
        f"only {len(live)} live member ids parsed -- the section walker has "
        "broken and this gate would pass vacuously. Fix the parser, do not "
        "weaken this floor."
    )
    unprobed = sorted(live - set(probes))
    assert not unprobed, (
        f"{len(unprobed)} live ledger row(s) have no entry in "
        f"{_PROBE_FILE.name}: {unprobed}.\nEvery row states a claim about this "
        "tree, and nothing re-measures a row that has no probe -- that is the "
        "DEF-546 stale-shape class, and it has a live instance every time this "
        "list is non-empty. Add a probe with `cmd` + `open_value`, or declare "
        "`why_not` if the claim has no local oracle. There is no third option."
    )
    silent = sorted(
        i for i in live
        if not probes[i].get("cmd") and not (probes[i].get("why_not") or "").strip()
    )
    assert not silent, (
        f"probe entries with neither a `cmd` nor a `why_not`: {silent}. "
        "An entry that measures nothing and explains nothing is worse than no "
        "entry -- it makes the row look covered."
    )


@pytest.mark.skipif(not _LEDGER.is_file(), reason="FORWARD_LEDGER.md is self-host only")
@pytest.mark.skipif(not _PROBE_FILE.is_file(), reason="LEDGER_PROBES.json is self-host only")
def test_every_probed_live_row_carries_a_row_hash():
    """Tier 3's drift signal is only as complete as its coverage.

    A probe with no `row_sha` can never report STALE_CLAIM, so an un-stamped
    entry is a silent hole in the staleness axis rather than a loud one.
    """
    text = _LEDGER.read_text(encoding="utf-8")
    # The population is every id a live row carries (`live_cell_ids`), not the
    # first id of each row: a co-id owns its own probe, and a probe with no hash
    # is the hole whichever id it hangs on.
    live, probes = _live_cell_ids(text), _probe_index()
    unstamped = {
        i for i in live
        if i in probes and probes[i].get("cmd") and not probes[i].get("row_sha")
    }
    # EXACT dated baseline, the dangling-citation test's shape. Measured
    # 2026-09-20 (TP-452 1-D) the moment `live_member_ids` learned to read a
    # row whose id cell carries a second id: seven two-id rows had carried a
    # probe with a `cmd` and no hash since they were filed, because the
    # enumerator never listed them and `ledger_row.py`'s verbs could not
    # address a two-id row (`DEF-863`) -- so nothing could ever stamp them. A
    # gate whose population skips a row shape is silent on exactly that shape.
    # The same day, DEF-863's fix widened this population from first ids to
    # every id of a live row (the failure-mode review's BLOCK: the fix made the
    # co-ids' probes stampable and this gate would never have asked), which
    # added the eight co-ids below -- the seven rows' partners, LG-8 among them
    # (DEF-451's), on the live file. Retirement: the live write's re-pin pass
    # runs one verb per ID that owns a probe (thirteen on the file that ships),
    # then `repaired` reds and says delete the ids. An id that leaves the live
    # population (struck) leaves the baseline quietly -- the file that ships
    # has already struck DEF-451 and, with it, LG-8.
    #
    # Emptied 2026-09-20 at the live write (1-D session 3): the re-pin pass ran
    # one `repin` per id that owns a probe -- thirteen verbs over the six live
    # two-id rows -- and `repaired` named all thirteen; DEF-451 and LG-8 had
    # left with the cut. Every probed live row carries a hash from here on.
    baseline: set[str] = set()
    new = sorted(unstamped - baseline)
    repaired = sorted((baseline & live) - unstamped)
    assert not new and not repaired, (
        f"probed live row(s) carrying no `row_sha` moved off the 2026-09-20 baseline.\n"
        f"  NEW unstamped (stamp it: `ledger_row.py repin <id> --reason ...`): {new}\n"
        f"  Now stamped (DELETE these from `baseline` in this test): {repaired}\n"
        "Without a hash, editing the row's prose and leaving the probe alone is "
        "undetectable -- which is exactly how DEF-493 carried a refuted cause "
        "for five days while its probe reported STILL_OPEN."
    )
