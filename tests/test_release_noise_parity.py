"""TP-27: ``.gitignore`` must cover every pattern in
``RELEASE_NOISE_PATTERNS``.

Pins the SoT→consumer parity between the release classifier
(``espalier.release_noise.RELEASE_NOISE_PATTERNS``) and the
adopter-facing ``.gitignore``. The classifier is the SoT;
``.gitignore`` may be a strict superset (it covers dev-only
patterns the release classifier need not know about) but it MUST
cover everything the SoT lists. This test fires the moment either
side drifts. Without this contract a new noise pattern added to
the classifier but not to ``.gitignore`` would let adopters
silently stage and commit the very files the release machinery
will later refuse to ship — the noise enters git history despite
the harness having a rule against it.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
from pathlib import Path

import pytest

from espalier import release_denylist
from espalier.release_noise import RELEASE_NOISE_PATTERNS

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"


def _gitignore_globs() -> list[str]:
    """Return non-comment, non-empty .gitignore lines."""
    raw = GITIGNORE.read_text(encoding="utf-8").splitlines()
    return [
        line.strip()
        for line in raw
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _matches_gitignore(noise_pattern: str, gitignore: list[str]) -> bool:
    """Return True if .gitignore has a rule that subsumes noise_pattern."""
    # Strip trailing `/` for directory patterns when comparing — .gitignore
    # may write `build/` or `build` and both block the directory.
    needle = noise_pattern.rstrip("/")
    for entry in gitignore:
        entry_clean = entry.rstrip("/").lstrip("/")
        # Exact match
        if entry_clean == needle:
            return True
        # Glob match (e.g., .gitignore `*.zip` covers SoT `*.zip`).
        if fnmatch.fnmatchcase(needle, entry_clean):
            return True
        # Directory exact match
        if needle == entry_clean or needle == entry_clean + "/":
            return True
    return False


class TestGitignoreCoversSoT:
    @pytest.mark.parametrize("pattern", RELEASE_NOISE_PATTERNS)
    def test_gitignore_covers(self, pattern):
        gitignore = _gitignore_globs()
        assert _matches_gitignore(pattern, gitignore), (
            f".gitignore does not cover SoT pattern {pattern!r}. "
            f"Either add it to .gitignore, or remove it from "
            f"espalier/release_noise.py if .gitignore intentionally "
            f"diverges."
        )


# ── DEF-599: the floor above cannot see a DELETION ────────────────────
#
# ``docs/FAILURE_MODES.md`` §18.4. The parametrize derives its population from
# the very constant it polices, so removing a pattern removes its own row and
# the suite merely gets smaller. Measured before these rows existed: deleting 3
# of the SECRET_FILES patterns took this module from 47 passed to 44 passed at
# rc=0, with nothing red and the gitignore requirement silently retired.
#
# The property here is "everything required is present" -- a coverage FLOOR --
# which is the DEFECT side of §18.4's discriminator, so the expectation has to
# come from somewhere other than the subject.

#: Literal, and NOT ``len(RELEASE_NOISE_PATTERNS)``. This is the deletion
#: tripwire: the set-equality row below is satisfied by any subset, so without a
#: count the constant can shrink freely. Bump it consciously when a pattern is
#: legitimately added or removed.
_PINNED_PATTERN_COUNT = 48  # +1 on 2026-09-08: the bare `.git` gitlink file (§C13)

#: sha256 over the sorted patterns, one newline apart. This is the IDENTITY pin,
#: and it exists because a COUNT cannot see a SUBSTITUTION: dropping ``*.swo``
#: while adding ``cc/blueprints/`` holds the count at 47 and leaves the whole
#: suite bit-identically green -- not even a shrinking row count -- while
#: ``surface_contract.is_transient("notes.swo")`` flips True to False. §18.4
#: rates a defect with no shrinking-count tell as WORSE than the filed one.
#:
#: Deliberately a hash rather than a hand-written 47-member roster. A roster is
#: §18.4's attested remedy and would work -- an expectation compared by
#: set-equality cannot go stale silently, it reds -- but it duplicates the data,
#: has to move in lockstep, and its bulk is what invites the regenerate-from-the-
#: subject edit that TestThePinsAreLiteralsNotDerivations exists to forbid. One
#: literal carries the same guarantee with no second copy.
#:
#: The reverse assertion ("every release_denylist rule still has a noise pattern
#: pointing at it") was measured as the no-duplication alternative and REFUTED:
#: it protects 27 of 47, misses ``*.swo`` itself (it shares its rule with
#: ``*.swp``, so dropping one orphans nothing), leaves every private-key pattern
#: uncovered, and needs its own 16-member residue for denylist rules that have no
#: noise counterpart.
_PINNED_PATTERN_DIGEST = (
    "b0543a0a4404a80847e6ad26e26f58a589886579708b9838df04d6167e5e6868"
)

#: The component tuples `RELEASE_NOISE_PATTERNS` concatenates. Pinned as a SET,
#: not counted: the walk that finds them is derived (good), but nothing said what
#: it should have found, so a walk that read 1 of 4 passed identically to one
#: that read all 4. Literal, per TestThePinsAreLiteralsNotDerivations.
_PINNED_COMPONENT_TUPLES = frozenset({
    "TRANSIENT_DIRS",
    "TRANSIENT_FILES",
    "SECRET_FILES",
    "ARCHIVE_FILES",
})

#: The patterns with NO independent witness in ``espalier.release_denylist``.
#: Measured, not assumed -- every other pattern is re-covered there, so a
#: deletion of one of THOSE is caught by the second-witness row. These four have
#: only the gitignore parity row above standing between them and a silent drop.
#: (`.git/` left the residue on 2026-09-08 when the denylist gained a rule for
#: the repo's admin dir and the bare gitlink file together, §C13.)
#: Pinned as a literal so the residue cannot quietly grow: an unbacked exclusion
#: list is the hand-list moved from the population to the subtraction, which is
#: the same class one level up.
_NO_SECOND_WITNESS = frozenset({
    ".venv/",
    "venv/",
    "env/",
    "*.code-workspace",
})


def _sample_member_paths(pattern: str) -> list[str]:
    """Realistic archive member paths for a noise pattern.

    ⚠ Written deliberately as a SECOND, cruder implementation -- it must not
    import anything from ``release_denylist``. Two implementations that have to
    agree is the entire point.

    ⚠ The naive version of this helper is what lied during authoring: handing
    the denylist a bare directory NAME (``.pytest_cache``) instead of a path
    INSIDE it (``.pytest_cache/x.txt``) reported 29 of 47 re-covered when the
    true figure is 42, and would have justified a much heavier fix. A directory
    pattern must be sampled as a file within the directory.
    """
    out: list[str] = []
    if pattern.endswith("/"):
        stem = pattern.rstrip("/").replace("*", "x")
        out += [f"{stem}/file.txt", f"{stem}/nested/file.txt", f"pkg/{stem}/file.txt"]
    else:
        base = pattern.replace("*", "x")
        out += [base, f"pkg/{base}", f"a/b/{base}"]
    return out


def _has_second_witness(pattern: str) -> bool:
    """True if release_denylist independently flags this pattern's members."""
    return any(
        release_denylist.find_denied_members([sample])
        for sample in _sample_member_paths(pattern)
    )


class TestSoTIsPinnedAgainstDeletion:
    """A pattern removed from ``RELEASE_NOISE_PATTERNS`` must RED here."""

    def test_population_is_not_empty(self) -> None:
        """An emptied constant makes every parametrized row above vanish, and
        zero rows is a pass. This is the vacuity floor that costs nothing."""
        assert RELEASE_NOISE_PATTERNS, (
            "RELEASE_NOISE_PATTERNS is empty -- every gitignore-parity row above "
            "collapses to zero parametrizations and the module passes vacuously."
        )

    def test_pattern_count_matches_the_literal_pin(self) -> None:
        assert len(RELEASE_NOISE_PATTERNS) == _PINNED_PATTERN_COUNT, (
            f"RELEASE_NOISE_PATTERNS holds {len(RELEASE_NOISE_PATTERNS)} patterns "
            f"but the pin is {_PINNED_PATTERN_COUNT}. A REMOVAL is the dangerous "
            f"direction: it retires a gitignore requirement with no other row "
            f"failing. If the change is deliberate, update _PINNED_PATTERN_COUNT "
            f"-- do NOT replace it with len(RELEASE_NOISE_PATTERNS), which makes "
            f"this row tautological and blind to exactly what it exists to catch."
        )

    def test_pattern_identity_matches_the_digest(self) -> None:
        """A COUNT cannot see a SUBSTITUTION. This can.

        Swap one pattern for another and the count row above stays green, the
        parametrized rows stay green, and the full suite is bit-identically
        green -- while a real classification silently flips. This row is the
        only thing in the file that notices.
        """
        digest = hashlib.sha256(
            "\n".join(sorted(RELEASE_NOISE_PATTERNS)).encode("utf-8")
        ).hexdigest()
        assert digest == _PINNED_PATTERN_DIGEST, (
            "RELEASE_NOISE_PATTERNS changed identity, not just size. A pattern "
            "was added, removed, or SWAPPED -- and a swap holds the count "
            "constant, so this is the only row that fires.\n"
            f"  live digest: {digest}\n"
            f"  pinned     : {_PINNED_PATTERN_DIGEST}\n"
            f"  live set   : {sorted(RELEASE_NOISE_PATTERNS)}\n"
            "Diff espalier/release_noise.py against git to see WHICH pattern "
            "moved, confirm the change is intended (a dropped pattern retires a "
            "gitignore requirement AND a surface_contract.is_transient answer), "
            "then update _PINNED_PATTERN_DIGEST to the live value above."
        )

    def test_the_aggregate_covers_every_component_tuple(self) -> None:
        """``RELEASE_NOISE_PATTERNS`` is a hand-written concatenation.

        A new component tuple added to the module but never concatenated in is
        enforced by nothing and moves no count -- the aggregation expression is
        itself a hand-maintained enumerator. Derived by walking the module, so
        there is no list here to keep in step.
        """
        import ast as _ast

        tree = _ast.parse(
            (REPO_ROOT / "espalier" / "release_noise.py").read_text(encoding="utf-8")
        )
        components: dict[str, list[str]] = {}
        for node in tree.body:
            target = None
            if isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name):
                target, value = node.target.id, node.value
            elif isinstance(node, _ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], _ast.Name):
                target, value = node.targets[0].id, node.value
            if target is None or target == "RELEASE_NOISE_PATTERNS":
                continue
            if target.startswith("__"):
                continue
            if isinstance(value, _ast.Tuple) and value.elts and all(
                isinstance(e, _ast.Constant) and isinstance(e.value, str)
                for e in value.elts
            ):
                components[target] = [e.value for e in value.elts]

        # `assert components` only required >= 1 of 4 -- a 75%-blind walk and a
        # working walk were indistinguishable, which is the >= floor §18.4
        # retracted. Pin the SET, so a component that changes shape and goes
        # invisible reds, and so does one that appears and is never concatenated.
        appeared = sorted(set(components) - _PINNED_COMPONENT_TUPLES)
        vanished = sorted(_PINNED_COMPONENT_TUPLES - set(components))
        assert not vanished, (
            f"component tuple(s) the walk can no longer see: {vanished}. They did "
            f"not necessarily disappear -- more likely one changed shape (a list "
            f"instead of a tuple, or a non-literal element) and is now invisible "
            f"to this row while still being live policy."
        )
        assert not appeared, (
            f"new module-level string tuple(s) in espalier/release_noise.py: "
            f"{appeared}. If it is a genuine noise-pattern group, concatenate it "
            f"into RELEASE_NOISE_PATTERNS and add it to _PINNED_COMPONENT_TUPLES. "
            f"If it is NOT a pattern group (a `__all__` export list, say), it "
            f"must NOT be concatenated -- doing so would inject its strings into "
            f"the release classifier as literal globs."
        )
        live = set(RELEASE_NOISE_PATTERNS)
        for name, members in sorted(components.items()):
            missing = sorted(set(members) - live)
            assert not missing, (
                f"component tuple {name} defines pattern(s) that never reach "
                f"RELEASE_NOISE_PATTERNS: {missing}. The aggregate is a "
                f"hand-written concatenation -- add {name} to it, or the "
                f"patterns are dead code that reads as live policy."
            )

    def test_residue_without_a_second_witness_is_exactly_the_pinned_set(self) -> None:
        """Every pattern is re-covered by release_denylist OR named in the residue.

        This is the independent-axis half: the denylist is a separate module with
        a separate purpose, so deleting a pattern from RELEASE_NOISE_PATTERNS
        leaves its denylist rule standing and this row notices.
        """
        live = frozenset(RELEASE_NOISE_PATTERNS)
        live_residue = frozenset(p for p in live if not _has_second_witness(p))

        # Three distinct causes, and they need three distinct messages. Collapsing
        # them is not cosmetic: a residue member that was DELETED and one that
        # GAINED a witness both show up as "in the pin, not in live_residue", and
        # the remedy for one is the exact opposite of the remedy for the other.
        # Caught by driving this row, not by reading it -- the first version
        # reported a deleted `.git/` as "now DO have a denylist witness", which
        # would have sent the next reader to delete the residue entry and retire
        # the only coverage the pattern had left.
        deleted = sorted(_NO_SECOND_WITNESS - live)
        gained_witness = sorted((_NO_SECOND_WITNESS & live) - live_residue)
        newly_unbacked = sorted(live_residue - _NO_SECOND_WITNESS)

        assert not deleted, (
            f"pattern(s) REMOVED from RELEASE_NOISE_PATTERNS entirely: {deleted}. "
            f"These had NO independent release_denylist witness, so this row was "
            f"the last thing standing between them and a silent drop -- deleting "
            f"one retires a gitignore requirement outright. Restore the pattern. "
            f"Do NOT 'fix' this by removing the name from _NO_SECOND_WITNESS: "
            f"that deletes the alarm, not the cause."
        )
        assert not newly_unbacked, (
            f"pattern(s) lost their release_denylist witness: {newly_unbacked}. "
            f"Each now rests on the gitignore parity row alone. Restore the "
            f"denylist rule, or add the pattern to _NO_SECOND_WITNESS with a "
            f"written reason."
        )
        assert not gained_witness, (
            f"pattern(s) in _NO_SECOND_WITNESS now DO have a denylist witness: "
            f"{gained_witness}. Remove them from the residue -- a stale exclusion "
            f"understates the coverage that actually exists."
        )

    def test_the_witness_probe_is_not_vacuous(self) -> None:
        """The witness count must be EXACT, derived only from the two pinned literals.

        An earlier version asserted ``len(backed) > len(_NO_SECOND_WITNESS)`` --
        i.e. ``> 5``. Driven: reverting ``_sample_member_paths`` to the naive
        bare-directory-name sampler (the authoring-time defect) drops `backed`
        from 42 to 29, and ``29 > 5`` passes. The row's own failure text named
        the 29/47 defect it was threshold-blind to by a factor of six.

        Exact, and expressed as the two pins rather than a third literal, so it
        stays correct as either moves.
        """
        backed = [p for p in RELEASE_NOISE_PATTERNS if _has_second_witness(p)]
        expected = _PINNED_PATTERN_COUNT - len(_NO_SECOND_WITNESS)
        assert len(backed) == expected, (
            f"{len(backed)} pattern(s) resolved a denylist witness; expected "
            f"exactly {expected} (= _PINNED_PATTERN_COUNT - len(_NO_SECOND_WITNESS)). "
            f"If this is far BELOW expected, suspect _sample_member_paths before "
            f"suspecting the denylist: handing it bare directory names instead of "
            f"paths inside them reports 29 of 47 when the truth is 42."
        )


class TestThePinsAreLiteralsNotDerivations:
    """``docs/FAILURE_MODES.md`` §18.4 bullet 4, enforced mechanically.

    The comments on the pins say "a LITERAL, not len(...)". A comment is advice a
    future editor -- or an AI collaborator collapsing "magic numbers" -- may
    silently decline, and the decline is invisible: derive the pin from the
    constant it tracks and the deletion tripwire becomes tautological with every
    other row still green. Measured counterfactual on the predecessor: without
    this check, regenerating a pin AND deleting a member runs fully green.

    Shape ported from ``tests/test_write_guard_command_position.py``
    ``::TestThePinsAreLiteralsNotDerivations``, the attested instance.
    """

    @staticmethod
    def _module_level_assignments() -> dict[str, ast.expr]:
        # encoding pinned: a runner with an unset locale resolves a bare
        # read_text() to US-ASCII and reds on a CORRECT tree.
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        found: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    found[node.target.id] = node.value
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node.value
        return found

    def test_pattern_count_is_an_integer_literal(self) -> None:
        value = self._module_level_assignments()["_PINNED_PATTERN_COUNT"]
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            "_PINNED_PATTERN_COUNT must stay an integer literal. Written as "
            "len(RELEASE_NOISE_PATTERNS) it can never disagree with the constant "
            "it tracks -- and disagreeing is its entire job."
        )

    def test_pattern_digest_is_a_string_literal(self) -> None:
        value = self._module_level_assignments()["_PINNED_PATTERN_DIGEST"]
        assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
            "_PINNED_PATTERN_DIGEST must stay a string literal. Computed from "
            "RELEASE_NOISE_PATTERNS it agrees with whatever the live set is, "
            "which is the opposite of an identity pin."
        )

    def test_component_tuple_pin_is_a_literal_set(self) -> None:
        value = self._module_level_assignments()["_PINNED_COMPONENT_TUPLES"]
        why = (
            "_PINNED_COMPONENT_TUPLES must stay a hand-written frozenset({...}). "
            "Derived from the AST walk it polices, it would agree with whatever "
            "the walk managed to find -- including a walk that found one of four."
        )
        assert isinstance(value, ast.Call), why
        assert getattr(value.func, "id", None) == "frozenset", why
        assert len(value.args) == 1 and isinstance(value.args[0], ast.Set), why

    def test_residue_is_a_literal_set_of_string_constants(self) -> None:
        value = self._module_level_assignments()["_NO_SECOND_WITNESS"]
        why = (
            "_NO_SECOND_WITNESS must stay a hand-written frozenset({...}) of "
            "string literals. Computing it from RELEASE_NOISE_PATTERNS makes the "
            "residue row tautological -- it would agree with whatever the live "
            "population happens to be, which is the opposite of a pin."
        )
        assert isinstance(value, ast.Call), why
        assert getattr(value.func, "id", None) == "frozenset", why
        assert len(value.args) == 1 and isinstance(value.args[0], ast.Set), why
        assert all(
            isinstance(el, ast.Constant) and isinstance(el.value, str)
            for el in value.args[0].elts
        ), why
