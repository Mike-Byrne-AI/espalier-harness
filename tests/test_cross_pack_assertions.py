"""A cross-pack assertion is a claim until the target agrees (class C7).

Pack A states that pack B is struck, superseded, merged, or owned elsewhere --
and B is never told. Both documents then read as complete: a reviewer holding A
sees the coordination handled and moves on; a reviewer holding B sees a live,
well-formed, internally consistent block. **Only a reader holding both at once
sees the gap, and per-pack review is by construction never that reader.**

This is the class that orphaned ``BLIND2-01`` -- the pre-flip set's only
release-blocking finding -- where three packs each named a fourth as owner while
that fourth's own header disclaimed the work. It then recurred four more times
*inside the review set that diagnosed it*, and the review still missed the five
live pairs this module was written against. Finding them cost a three-lane agent
review; checking them costs a grep over the pack corpus. That asymmetry is the
whole argument for mechanizing it.

Canon: ``docs/FAILURE_MODES.md`` §4.10 "The cross-artifact assertion nothing
checks" is the durable, adopter-facing definition of the class and of the guard
properties below (non-vacuous floor; population by content, not by hand-list;
enforce only while both artifacts are live). This module is its implementation
-- if the two ever drift, canon wins.

**Two DECLARED divergences from §4.10.** Recorded here because a module that
says "canon wins" while quietly diverging is itself the class it polices --
neither is an oversight, both are scoped out with a ledger row:

1. §4.10 says to *"separately flag references to artifacts that exist under no
   name at all -- a merge or a rename leaves citations pointing at identifiers
   nothing answers to."* This module does **not**: a missing target is silenced
   by ``_is_enforceable_target``. That is citation rot -- a different assertion
   shape (existence, not reciprocity) with a different fix (re-key the citation,
   never add a back-reference). Measured 2026-07-31: **6 instances, 5 of them in
   ``Done/``, 1 live.** Folding it in would have doubled the false-positive
   calibration surface for one live instance. **``DEF-416b``.**
2. §4.10 says the population should be defined *"by content rather than by
   filename convention."* ``_PACK_FILE_RE`` **is** a filename convention, so
   ``RUNBOOK*.md`` is invisible -- and runbooks do assert about live packs (4
   such spans measured). Deferred because runbooks are transient per-cut
   artifacts whose assertion shape differs; the durable fix is the declared
   syntax in **``DEF-416c``**, which removes the need to regex prose at all.

Structural twin of ``docs/STANDING_PRINCIPLES.md`` §3 (*a finding is a claim
until grep-verified*), re-aimed from findings onto **coordination**.

Self-host only: ``task-packs/Done/`` is gitignored, so on an adopter clone or fresh
checkout every check here skips cleanly rather than failing. Detectors take
their roots as parameters so the domain proofs drive synthetic ``tmp_path``
trees -- the live pack folder is never mutated (it has no git undo net, and
``TP-391``'s earn-the-red depends on one of its rows surviving intact).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_PACKS = _ROOT / "task-packs"

# Reuse the canonical Landing-stanza parser rather than forking a rival regex,
# so "has this pack landed?" is answered in ONE place -- the same reason
# test_forward_ledger_completeness.py imports it. scripts/ is self-host dev
# tooling (absent from the sdist), so the guarded import and the checks that
# need it skip together off-host. check_pack_landing is a standalone scripts/
# tool, not a tools/cc/ module, so the spec_from_file_location rule in
# tests/CLAUDE.md does not apply.
_CHECK_PACK_LANDING = _ROOT / "scripts" / "check_pack_landing.py"
if _CHECK_PACK_LANDING.is_file():
    sys.path.insert(0, str(_ROOT / "scripts"))
    from check_pack_landing import landed_state as _landed_state  # noqa: E402
else:  # adopter / fresh clone: dev tooling absent
    _landed_state = None

# ---------------------------------------------------------------------------
# Population: where a pack can live, and whether an assertion ABOUT it is
# enforceable. Every exclusion carries its REASON -- an unexplained exclusion
# inside a mechanical gate is itself an un-tested assertion.
# ---------------------------------------------------------------------------
_LOCATION_DIRS = {
    # in-flight -> unlanded, still executable, therefore still EDITABLE: a
    #              missing reciprocal is a live coordination hole someone can
    #              still act on. The only enforceable location.
    "in-flight": (),
    # Done/     -> landed. A reciprocal would be archaeology: nobody will
    #              re-open a shipped pack to add a back-reference, and the
    #              coordination it would have enabled is already spent.
    "Done": ("Done",),
    # Deferred/ -> parked by design. Silence about an asserter is LEGITIMATE
    #              here -- a parked pack is meant to say nothing until revived.
    "Deferred": ("Deferred",),
    # Merged/   -> marked do-not-execute; the bodies live on inside the merged
    #              successor pack. Editing one would contradict that marker.
    "Merged": ("Merged",),
    # Scrapped/ -> deliberately abandoned (memory/task-packs.md: "Abandoned packs
    #              move to task-packs/Scrapped/"). Listed even though the folder
    #              does not exist yet: the documented convention is what a future
    #              session will follow, and an unlisted folder drains the
    #              population SILENTLY. test_every_pack_subfolder_is_classified
    #              reds if a sibling folder appears that is not named here.
    "Scrapped": ("Scrapped",),
}
_ENFORCEABLE_LOCATIONS = frozenset({"in-flight"})

# Floors for the non-vacuity check, kept as named constants so the domain suite
# can drive the REAL predicate instead of restating the literals (a test that
# re-asserts `2 < 150` in its own body proves nothing about the gate).
# Measured 2026-07-31: 178 distinct ids across 183 files, 45 assertion pairs.
_MIN_PACKS = 150
_MIN_PAIRS = 30

# Landing states that mean "this pack is finished" even though the file has not
# been moved to Done/ yet. The window between the landing commit and the `mv`
# is real, and an assertion about a pack that is done-but-unfiled is no more
# actionable than one about a pack already in Done/.
_TERMINAL_STATES = frozenset({"LANDED", "SCRAPPED"})

# Precision measured 2026-07-31 over the live corpus (183 packs, 69 raw
# matches), by hand-classifying every match:
#
#     whole corpus              54 true / 15 false -> 78.3%
#     asserter in Done/         32 true / 12 false -> 73%
#     asserter in-flight        20 true /  3 false -> 87%
#     ENFORCED domain           9 true /  1 false -> 90.0%   <- what this gate acts on
#
# The detector is least accurate exactly where the exclusions above already
# silence it, so the scope-out and the precision profile agree.
#
# Widening this pattern without re-running that measurement re-opens the
# cry-wolf failure mode -- a guard that is routinely wrong gets suppressed.
#
# Tightening was MEASURED and rejected: narrowing the verb->id gap to 20 chars
# buys 82.7% precision but drops 11 of 54 true positives, and a "skip spans
# containing 'not'" filter deletes TP-414's genuine *"NOT merged into this
# file: TP-410's Block 4"* -- one of the five pairs this guard was written to
# catch. Both are losing trades; do not re-introduce either without new numbers.
#
# ``|`` joins ``.`` and ``\n`` as a span terminator: these packs are dense with
# markdown tables, and a verb in one cell has no relationship to an id in the
# next. Measured -- it removes a real self-inflicted false positive (a
# co-tenancy row whose "no existing row is edited or struck" cell was being
# joined to the neighbouring cell's pack id) at a cost of one corpus pair.
_ASSERTION_RE = re.compile(
    r"(struck|strike|supersed|merged into|owned by|owner|handled by|belongs to)"
    r"[^.\n|]{0,120}?(TP-\d+[a-z]*)",
    re.IGNORECASE,
)

# A pack id carries an optional alpha suffix (TP-233b). Matching the FULL token
# on a word boundary is what stops TP-233b truncating to a sibling-matching
# TP-233 -- the trap already solved in test_forward_ledger_completeness.py.
# The trailing separator is deliberately NOT required. An earlier draft used
# ``^(TP-\d+[a-z]*)-`` and silently dropped ``TP-420.md`` / ``TP-420_slug.md`` /
# ``TP-420 slug.md`` from the population -- and a pack outside the population is
# one an assertion about it can never be enforced against, i.e. a false GREEN.
# The sibling's matcher is likewise separator-agnostic.
_PACK_FILE_RE = re.compile(r"^(TP-\d+[a-z]*)\b", re.IGNORECASE)
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})


def _pack_index(packs_root: Path) -> dict[str, list[tuple[str, Path]]]:
    """Map ``TP-<n>`` -> every file claiming that id, with its location.

    Population is the FOLDER, never a hand-maintained list -- the same rule
    ``test_forward_ledger_completeness.py`` follows, for the same reason: a
    hand-list recreates the drift class the guard exists to close.

    Scanned via ``iterdir()`` with explicit suffix/stem checks rather than
    ``glob("TP-*.md")`` so an off-convention pack -- a lowercase ``tp-`` prefix
    or a ``.markdown`` extension -- cannot silently escape the population.

    Returns a LIST per id because the mapping is not 1:1: measured 2026-07-31,
    183 pack files carry only 178 distinct ids (``TP-233b`` lives in BOTH
    ``Done/`` and ``Deferred/``; ``TP-247``/``293``/``327``/``328`` each appear
    twice inside ``Done/``). Collapsing that to one file would silently pick an
    enforceability verdict -- see ``_is_enforceable_target``.
    """
    index: dict[str, list[tuple[str, Path]]] = {}
    for location, parts in _LOCATION_DIRS.items():
        directory = packs_root.joinpath(*parts)
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _MARKDOWN_SUFFIXES:
                continue
            match = _PACK_FILE_RE.match(path.name)
            if not match:
                continue
            pack_id = match.group(1).upper()
            index.setdefault(pack_id, []).append((location, path))
    return index


def _token_re(pack_id: str) -> re.Pattern[str]:
    """Word-boundary matcher for a full ``TP-<n>`` token, alpha suffix included."""
    return re.compile(rf"\b{re.escape(pack_id)}\b", re.IGNORECASE)


def _is_enforceable_target(pack_id: str, index: dict[str, list[tuple[str, Path]]]) -> bool:
    """Is an assertion ABOUT ``pack_id`` something a human can still act on?

    False when the target does not exist (citation rot -- a different class,
    deliberately out of scope), when it lives outside ``_ENFORCEABLE_LOCATIONS``,
    or when its Landing stanza already reads a terminal state (done but not yet
    filed to ``Done/``).

    **An AMBIGUOUS target is not enforceable.** With two files claiming one id
    in different folders, "is the target still in-flight?" has two answers, and
    a lookup that takes the first match silently picks one -- a C5 (silent
    partial success) wearing a reciprocity costume. Refusing to guess is the
    conservative direction: the dangerous failure for a coordination guard is a
    false RED on a pair nobody can fix.
    """
    homes = index.get(pack_id, [])
    if len(homes) != 1:
        return False
    location, path = homes[0]
    if location not in _ENFORCEABLE_LOCATIONS:
        return False
    if _landed_state is not None:
        state = _landed_state(path.read_text(encoding="utf-8", errors="replace"))
        if state is not None and state.upper() in _TERMINAL_STATES:
            return False
    return True


def _cross_pack_assertions(packs_root: Path) -> list[tuple[str, str]]:
    """Every ``(asserter, target)`` pair the heuristic matches, corpus-wide.

    Deliberately UNFILTERED by enforceability -- this is the population the
    non-vacuity floor pins, and it must include the archived majority so the
    floor does not decay to nothing as packs land.
    """
    index = _pack_index(packs_root)
    pairs: set[tuple[str, str]] = set()
    for pack_id, homes in index.items():
        for _location, path in homes:
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _ASSERTION_RE.finditer(text):
                target = match.group(2).upper()
                if target != pack_id:
                    pairs.add((pack_id, target))
    return sorted(pairs)


def _unreciprocated_assertions(packs_root: Path) -> list[tuple[str, str]]:
    """Enforceable assertions whose target never references the asserter back.

    An assertion is enforceable when the asserter AND the target are both
    in-flight -- both still editable, so the coordination hole is still real.
    """
    index = _pack_index(packs_root)
    gaps: list[tuple[str, str]] = []
    for asserter, target in _cross_pack_assertions(packs_root):
        if not _is_enforceable_target(asserter, index):
            continue
        if not _is_enforceable_target(target, index):
            continue
        _location, target_path = index[target][0]
        target_text = target_path.read_text(encoding="utf-8", errors="replace")
        if not _token_re(asserter).search(target_text):
            gaps.append((asserter, target))
    return sorted(gaps)


def _vacuity_failures(packs_root: Path) -> list[str]:
    """Reasons the guard would be passing without actually checking anything.

    Extracted so the domain suite can drive the REAL floors. Inlining the
    literals in a test body instead produces a comparison between constants
    that stays green when the floors themselves are lowered to zero -- the
    born-weak shape this whole module exists to close, aimed at itself.

    Both floors are pinned to the WHOLE corpus, never to the enforceable
    subset. That subset legitimately drains to zero as the in-flight set lands,
    so a floor on it would false-red by design -- while the corpus half does
    not shrink: a landed pack's assertions become ``Done -> Done``, they do not
    disappear. Every reason is collected (never short-circuited) so one run
    reports both failures rather than hiding the second behind the first.
    """
    failures: list[str] = []
    packs = _pack_index(packs_root)
    if len(packs) < _MIN_PACKS:
        failures.append(
            f"only {len(packs)} packs discovered under {packs_root} (floor "
            f"{_MIN_PACKS}) -- the population rule has silently narrowed. "
            "A guard that scans nothing passes everything."
        )
    found = _cross_pack_assertions(packs_root)
    if len(found) < _MIN_PAIRS:
        failures.append(
            f"only {len(found)} cross-pack assertions detected across "
            f"{len(packs)} packs (floor {_MIN_PAIRS}) -- the pattern or the "
            "population rule has silently narrowed. A count is not a success "
            "signal unless something pins the expected count."
        )
    return failures


def _is_self_host_tree(packs_root: Path) -> bool:
    """Is this a real pack tree, or just the tracked shell of one?

    ``task-packs/`` itself is NOT a usable signal: ``CLAUDE.md`` inside it is
    **tracked**, so the directory is present in every clone and CI checkout
    while every pack is gitignored and absent. A gate keyed on
    ``packs_root.is_dir()`` therefore sails past the skip and reds on an empty
    population in each CI job and Python version -- the fresh-clone-red class
    the ``clean-checkout`` workflow exists to catch.

    The subfolders are gitignored in full, so ``Done/`` is the honest
    discriminator. Same discipline as the sibling, which gates on ``Deferred/``
    plus the ledger.

    This is a NAMED PREDICATE rather than an inline expression so the domain
    suite can drive it against a clone-shaped fixture. Inlining it back into
    the decorator makes the mutation untestable: on the self-host tree both
    spellings are True, so only a test that calls this function can tell them
    apart. Verified by mutation -- do not "simplify" it away.
    """
    return (packs_root / "Done").is_dir()


_requires_packs = pytest.mark.skipif(
    not _is_self_host_tree(_PACKS),
    reason="self-host only: task-packs/Done/ absent (gitignored dev tooling)",
)


@_requires_packs
def test_in_flight_cross_pack_assertions_are_reciprocated():
    """An in-flight pack asserting about another in-flight pack must be referenced back."""
    gaps = _unreciprocated_assertions(_PACKS)
    assert not gaps, (
        "In-flight pack(s) assert a state change about another in-flight pack "
        "that never references them back (class C7):\n  "
        + "\n  ".join(f"{a} asserts about {t} -- {t} never mentions {a}" for a, t in gaps)
        + "\n\nFix EITHER by adding the reciprocal to the target OR by deleting a "
        "stale assertion. Do not assume the first -- a declared dependency needs "
        "a back-reference; a superseded claim needs removal."
    )


@_requires_packs
def test_guard_population_is_non_vacuous():
    """A green above must mean 'reciprocated', never 'found nothing to check'."""
    failures = _vacuity_failures(_PACKS)
    assert not failures, "The reciprocity guard is running vacuously:\n  " + "\n  ".join(failures)


@_requires_packs
def test_every_pack_subfolder_is_classified():
    """A new sibling folder must RED loudly, not drain the population quietly.

    ``_LOCATION_DIRS`` is hand-maintained, so it can fall behind the convention
    it models -- ``Scrapped/`` was documented in ``memory/task-packs.md`` long
    before it was listed here. An unlisted folder is invisible to the population
    scan, and the non-vacuity floor has ~28 packs of slack before it notices, so
    the drain is silent for exactly as long as it takes to matter.
    """
    classified = {name for name in _LOCATION_DIRS if name != "in-flight"}
    actual = {p.name for p in _PACKS.iterdir() if p.is_dir() and not p.name.startswith(".")}
    unclassified = actual - classified
    assert not unclassified, (
        f"Pack subfolder(s) not named in _LOCATION_DIRS: {sorted(unclassified)}. "
        "Packs there are invisible to the reciprocity guard -- classify the "
        "folder (with its enforceability REASON) rather than letting the "
        "population shrink silently."
    )


def _write_pack(directory: Path, pack_id: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{pack_id}-fixture.md"
    path.write_text(body, encoding="utf-8")
    return path


class TestReciprocityGuardDomain:
    """Prove the guard on a synthetic tree, not only on the corpus it was written against.

    A gate proven solely against its motivating population is not proven: it may
    be matching those five specific pairs rather than the *property*. Every case
    here drives a ``tmp_path`` tree, so the live pack folder -- gitignored, with
    no git undo net -- is never mutated.
    """

    def test_removing_a_reciprocal_reds_the_guard(self, tmp_path: Path):
        """The orthogonal mutation: a correctly-coordinated pair reds once the back-reference goes."""
        _write_pack(tmp_path, "TP-901", "Block 1 is **struck**, superseded by TP-902.\n")
        target = _write_pack(tmp_path, "TP-902", "This pack absorbs TP-901's Block 1.\n")

        assert _unreciprocated_assertions(tmp_path) == []

        target.write_text("This pack absorbs an earlier block.\n", encoding="utf-8")
        assert _unreciprocated_assertions(tmp_path) == [("TP-901", "TP-902")]

        target.write_text("This pack absorbs TP-901's Block 1.\n", encoding="utf-8")
        assert _unreciprocated_assertions(tmp_path) == []

    def test_alpha_suffix_target_is_not_truncated(self, tmp_path: Path):
        """``TP-233b`` must not be satisfied by a mention of its sibling ``TP-233``."""
        _write_pack(tmp_path, "TP-901", "Block 2 is **owned by** TP-902b.\n")
        # Cites the SIBLING id only -- a truncating matcher would read this as
        # a satisfied reciprocal and false-GREEN.
        _write_pack(tmp_path, "TP-902b", "Body citing TP-9011 and TP-90 only.\n")
        assert _unreciprocated_assertions(tmp_path) == [("TP-901", "TP-902B")]

    def test_ambiguous_target_is_not_enforceable(self, tmp_path: Path):
        """Two files claiming one id: refuse to guess which one the assertion meant."""
        _write_pack(tmp_path, "TP-901", "Block 3 is **struck**, now owned by TP-902.\n")
        _write_pack(tmp_path, "TP-902", "Body with no back-reference.\n")
        assert _unreciprocated_assertions(tmp_path) == [("TP-901", "TP-902")]

        # A second home for the same id in a different enforceability class.
        _write_pack(tmp_path / "Deferred", "TP-902", "A parked twin.\n")
        assert _unreciprocated_assertions(tmp_path) == []

    def test_excluded_locations_are_not_enforced(self, tmp_path: Path):
        """Done/, Deferred/, Merged/ and Scrapped/ targets are excluded, and for their stated reasons.

        The asserted id MUST be the literal the target file is written under: an
        earlier draft computed it as ``f"TP-90{len(sub)}"``, which named a pack
        that did not exist, so every case passed through the *missing-target*
        silencing path instead of the location exclusion it claims to test --
        green, and blind to ``_ENFORCEABLE_LOCATIONS`` being widened.
        """
        for sub in ("Done", "Deferred", "Merged", "Scrapped"):
            tree = tmp_path / sub.lower()
            _write_pack(tree, "TP-901", "Block 4 is **struck**, owned by TP-903.\n")
            _write_pack(tree / sub, "TP-903", "No back-reference here.\n")
            # Sanity: the target really is discoverable, so a [] verdict below
            # can only come from the exclusion under test.
            assert "TP-903" in _pack_index(tree), f"{sub}: fixture target not in population"
            assert _unreciprocated_assertions(tree) == [], f"{sub}/ should be excluded"

    def test_landed_but_unfiled_target_is_not_enforceable(self, tmp_path: Path):
        """The window between the landing commit and the `mv` to Done/ is not a coordination hole."""
        _write_pack(tmp_path, "TP-901", "Block 5 is **struck**, owned by TP-902.\n")
        target = _write_pack(tmp_path, "TP-902", "No back-reference.\n")
        assert _unreciprocated_assertions(tmp_path) == [("TP-901", "TP-902")]

        target.write_text(
            "No back-reference.\n\n## Landing\n\n- State: LANDED\n- Date: 2026-07-31\n",
            encoding="utf-8",
        )
        if _landed_state is None:
            pytest.skip("scripts/check_pack_landing.py absent -- adopter clone")
        assert _unreciprocated_assertions(tmp_path) == []

    def test_off_convention_pack_files_are_still_population(self, tmp_path: Path):
        """A lowercase stem or a .markdown suffix must not escape the net."""
        (tmp_path / "tp-901-fixture.markdown").write_text(
            "Block 6 is **struck**, owned by TP-902.\n", encoding="utf-8"
        )
        _write_pack(tmp_path, "TP-902", "No back-reference.\n")
        assert _unreciprocated_assertions(tmp_path) == [("TP-901", "TP-902")]

    def test_non_vacuity_floor_reds_on_a_narrowed_population(self, tmp_path: Path):
        """The floor must fire when the detector is green only because it found nothing.

        Drives ``_vacuity_failures`` itself rather than restating ``150``/``30``
        as literals -- a test that compares constants stays green when the real
        floors are lowered to zero, which is the born-weak shape this module
        exists to close. Both reasons must surface, not just the first.
        """
        _write_pack(tmp_path, "TP-901", "Block 7 is **struck**, owned by TP-902.\n")
        _write_pack(tmp_path, "TP-902", "TP-901 is referenced here.\n")

        assert _unreciprocated_assertions(tmp_path) == []  # reciprocity: green...
        failures = _vacuity_failures(tmp_path)  # ...but on a vacuous population.
        assert len(failures) == 2, failures
        assert any("packs discovered" in f for f in failures)
        assert any("cross-pack assertions detected" in f for f in failures)

    def test_live_corpus_clears_the_floor_by_a_real_margin(self):
        """The floors must be live-satisfiable, not merely satisfiable in a fixture."""
        if not (_PACKS / "Done").is_dir():
            pytest.skip("self-host only")
        assert _vacuity_failures(_PACKS) == []


class TestSelfHostGate:
    """The skip predicate itself, pinned.

    ``task-packs/CLAUDE.md`` is TRACKED (and since 2026-09-21 the ledger and the active
    packs are too) while the landed packs are gitignored, so the directory is present
    in each clone and CI checkout without ``Done/``.
    An earlier draft gated on ``_PACKS.is_dir()``, which is True there -- the
    module would have sailed past the skip and red on an empty population across
    every CI job and Python version. The gate must key on a subfolder, which is
    gitignored in full.
    """

    def test_bare_pack_dir_without_subfolders_does_not_look_self_hosted(self, tmp_path: Path):
        """A clone-shaped tree: task-packs/ exists, carries only the tracked CLAUDE.md."""
        clone_shaped = tmp_path / "task-packs"
        clone_shaped.mkdir()
        (clone_shaped / "CLAUDE.md").write_text("# task-packs/\n", encoding="utf-8")

        assert clone_shaped.is_dir(), "the naive predicate would say 'self-host' here"
        assert not _is_self_host_tree(clone_shaped), (
            "A clone carries task-packs/CLAUDE.md and no packs. The gate must "
            "read that as 'not self-host' and skip -- otherwise every CI job "
            "reds on an empty population."
        )
        assert _pack_index(clone_shaped) == {}
        assert _vacuity_failures(clone_shaped), "an empty tree must look vacuous, not healthy"

    def test_self_host_tree_is_recognised(self):
        """And the live tree must still be recognised, or the gate skips everything forever."""
        if not _is_self_host_tree(_PACKS):
            pytest.skip("self-host only")
        assert len(_pack_index(_PACKS)) >= _MIN_PACKS

    def test_missing_pack_folder_yields_no_findings(self, tmp_path: Path):
        """Criterion 7: an adopter clone has no task-packs/ -- degrade to empty, never error."""
        absent = tmp_path / "no-such-tree"
        assert _pack_index(absent) == {}
        assert _cross_pack_assertions(absent) == []
        assert _unreciprocated_assertions(absent) == []
