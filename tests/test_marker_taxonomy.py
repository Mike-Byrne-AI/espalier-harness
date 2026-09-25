"""TP-105: every test file gets a deliberate marker assignment.

The default-unit fallthrough in tests/conftest.py:_MARKER_RULES means
silent misclassification: a new contract test lands in the `unit`
bucket and runs in the fast slice (correct) OR a new security test
lands in `unit` and is invisible to `pytest -m security` (wrong).
This contract pins the assignment as explicit.

Prevents new test files defaulting silently to `unit`. Catches the
"new file lands in wrong slice" failure mode without requiring
contributors to know the marker taxonomy by heart.
"""
from __future__ import annotations

import io
import tokenize
from pathlib import Path

TESTS_DIR = Path(__file__).parent

_OPT_OUT_MARKER = "# pytest-marker: default-unit"


def _carries_default_unit_optout(text: str) -> bool:
    """True only when the opt-out appears as a real COMMENT token.

    Substring matching cannot tell a USE from a MENTION. This module and
    tests/test_test_suite_contract.py both discuss the marker in prose, and a
    substring test matches them against themselves -- which is how the
    redundant-opt-out contract below flagged its own author on first run.

    The same shape has now cost this repo four separate defects in a month:
    the Bash guards read prose ABOUT a command as the command, the
    retired-vocab scanner read a backticked severity term as a use of the
    label, the bench overclaim gate could not see a negation written in bold,
    and this. Whenever a guard fires on documentation, the question is role,
    not spelling -- so ask the tokenizer, which knows the difference between a
    comment and a string, instead of asking `in`.

    A file that does not tokenize returns False rather than guessing; pytest
    will fail its collection loudly, so this is not a silent hole.
    """
    try:
        return any(
            tok.type == tokenize.COMMENT and tok.string.startswith(_OPT_OUT_MARKER)
            for tok in tokenize.generate_tokens(io.StringIO(text).readline)
        )
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return False


class TestMarkerTaxonomyMembership:
    def test_every_test_file_is_classified(self):
        """Every tests/test_*.py file is named in _MARKER_RULES or carries
        an explicit `# pytest-marker: default-unit` opt-out comment.
        """
        from tests.conftest import _MARKER_RULES

        all_stems = {f.stem for f in TESTS_DIR.glob("test_*.py")}
        classified = {stem for tup, _marker in _MARKER_RULES for stem in tup}
        unclassified = all_stems - classified

        forgiven: set[str] = set()
        for stem in unclassified:
            text = (TESTS_DIR / f"{stem}.py").read_text(encoding="utf-8")
            # Token-level, not substring: a file that merely MENTIONS the
            # marker in prose must not be forgiven by it.
            if _carries_default_unit_optout(text):
                forgiven.add(stem)
        truly_unclassified = unclassified - forgiven

        assert not truly_unclassified, (
            "New test files default to `unit` marker silently. Either add "
            "the stem to the appropriate tuple in tests/conftest.py "
            "_MARKER_RULES, or add `# pytest-marker: default-unit` to opt "
            "out explicitly:\n  " + "\n  ".join(sorted(truly_unclassified))
        )

        # Reverse direction: a rule naming a file that no longer exists is
        # dead weight (a removed test file leaves an orphaned stem behind).
        orphaned = classified - all_stems
        assert not orphaned, (
            "tests/conftest.py _MARKER_RULES names test files that no longer "
            "exist:\n  " + "\n  ".join(sorted(orphaned))
        )

    def test_no_classified_file_also_carries_the_opt_out(self):
        """A file named in `_MARKER_RULES` must NOT also carry
        `# pytest-marker: default-unit`.

        The comment is inert while the stem is classified, which is exactly
        why it rots unseen: it keeps asserting the file is a default-unit
        fall-through long after the tuples say otherwise, and several such
        comments were found in 2026-08-24 still claiming "no subprocess" for
        modules that shell out two lines later. Worse, it is a LATENT
        re-forgiveness -- remove the stem from its tuple and the stale comment
        silently waves the file back into `unit` instead of redding the sibling
        assertion above.

        One statement, one owner: the tuples classify, the comment opts out,
        and no file gets to do both.
        """
        from tests.conftest import _MARKER_RULES

        classified = {stem for tup, _marker in _MARKER_RULES for stem in tup}
        both = sorted(
            stem for stem in classified
            if (TESTS_DIR / f"{stem}.py").exists()
            and _carries_default_unit_optout(
                (TESTS_DIR / f"{stem}.py").read_text(encoding="utf-8")
            )
        )
        assert not both, (
            "These files are classified in tests/conftest.py::_MARKER_RULES "
            "AND still carry a `# pytest-marker: default-unit` opt-out. The "
            "comment is stale and re-forgives the file into `unit` the moment "
            f"the stem leaves its tuple -- delete it: {both}"
        )
