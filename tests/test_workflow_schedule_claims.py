"""No shipped doc may claim a schedule its workflow does not have.

Why this exists
---------------
The class decayed twice inside one day. On 2026-09-01 commit ``7a533c9`` retired
the ``schedule:`` block from ``portability.yml`` and ``test.yml`` and touched no
prose; ``135ad32`` then corrected two docs the same session had made false. The
``[Unreleased]`` CHANGELOG kept two more, and ``§C1``'s unit of work folds that
section into published release notes -- so the false claims were queued to ship.

``cc/GOAL.md`` named this as the class to convert first, and said why: a doc
claiming a schedule its workflow lacks is *mechanically checkable*, and a test
asserting it would have caught every site at authoring time.

Calibrating the net (all four cuts were driven against the live tree)
--------------------------------------------------------------------
This detector was wrong three times before it was right, and each failure is a
shape worth keeping:

1. **Line-scoped** -- found ``CHANGELOG.md:36`` and MISSED ``:45``, where
   ``test.yml`` sits on one line and "weekly" on the next. A line is not a
   sentence.
2. **Paragraph-scoped** -- 12 hits, nearly all noise: any workflow name sharing a
   paragraph with the word "weekly" fired, including four workflows merely
   mentioned near ``portability.yml``'s claim.
3. **Sentence-scoped with a blanket negation filter** -- ZERO hits. "moves
   **off** ``push`` **onto** a weekly schedule" is a POSITIVE claim, but the word
   "off" anywhere in the sentence suppressed it. A gate that reports clean
   because it is blind is worse than no gate.
4. **The oracle itself was fooled.** Asking ``"schedule:" in workflow_text``
   returns True for ``portability.yml`` -- because it carries the comment
   ``# NO `schedule:` -- DISPATCH-ONLY UNTIL THIS REPO IS PUBLIC``. The detector
   was reading *documentation of the absence* as evidence of the presence, the
   same shape as ``DEF-583``'s probe counting the prose that retired its own
   literal. The oracle now matches a real top-level YAML key.

Final shape: sentence-scoped across line wraps, negation windowed to +-45
characters of the schedule word, record surfaces excluded, oracle keyed on the
YAML key. Live population at 2026-09-02: exactly the two real CHANGELOG defects,
zero false positives across every tracked markdown file.

⚠ ``_NEGATION`` IS CALIBRATED, NOT OPEN-ENDED. It was widened once, for
``bench/end_to_end/README.md``'s correct statement that a trigger is "commented
out". Widening it again to clear a red is how a classifier grows a grandfather
tuple until it matches everything. Re-measure against the whole tree first: if
the new term suppresses a real claim anywhere, it is the wrong term.
"""
from __future__ import annotations

import bisect
import re
from pathlib import Path

import pytest

from tests._git_oracle import require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: Declared record surfaces plus the session log: evidence about the past, never
#: an instruction for the present (root CLAUDE.md Core Rule 13). A dated row
#: saying a cron existed was true when written.
_RECORD_SURFACES = frozenset({
    "docs/session-archive.md",
    "memory/CONVERGENCE_LEDGER.md",
    "ESPALIER_MEMORY.md",
})

#: A REAL top-level trigger key -- not the string anywhere in the file. See the
#: module docstring, failure 4.
_SCHEDULE_KEY = re.compile(r"^\s{2}schedule:\s*$", re.M)
_SCHEDULE_WORD = re.compile(r"\b(weekly|nightly|daily|cron)\b", re.I)
_NEGATION = re.compile(
    r"\b(no|not|never|without|neither|retired|removed|dropped|zero"
    r"|commented|disabled|pending|manual)\b",
    re.I,
)
#: How far from the schedule word a negation still governs it.
_NEGATION_WINDOW = 45


def _scheduled_workflows() -> dict[str, bool]:
    """``{filename: has_a_real_schedule_key}``."""
    return {
        p.name: bool(_SCHEDULE_KEY.search(p.read_text(encoding="utf-8")))
        for p in sorted(_WORKFLOWS.glob("*.yml"))
    }


def _tracked_markdown() -> list[str]:
    """Tracked markdown, minus the record surfaces.

    Routed through ``tests/_git_oracle`` rather than a raw ``git ls-files``: the
    oracle RAISES on an unanswerable query instead of returning an empty list,
    so a git that answered about the wrong worktree cannot read as "no docs
    make schedule claims" -- a clean green over a question nobody asked.
    """
    tracked = require_tracked_paths(
        REPO_ROOT, "*.md", minimum=20, what="tracked markdown"
    )
    return [p for p in tracked if p not in _RECORD_SURFACES]


def _sentences_with_lines(text: str):
    """Yield ``(sentence, line_number)`` with sentences joined across line wraps."""
    offsets: dict[int, int] = {}
    off = 0
    for n, ln in enumerate(text.splitlines(keepends=True), 1):
        offsets[off] = n
        off += len(ln)
    starts = sorted(offsets)
    for para in re.finditer(r"[^\n]+(?:\n[^\n]+)*", text):
        line = offsets[starts[max(0, bisect.bisect_right(starts, para.start()) - 1)]]
        flat = re.sub(r"\s+", " ", para.group(0))
        for sent in re.split(r"(?<=[.;])\s+", flat):
            yield sent, line


def find_false_schedule_claims() -> list[tuple[str, int, str, str]]:
    """``(path, line, workflow, sentence)`` for every unbacked schedule claim."""
    workflows = _scheduled_workflows()
    found: list[tuple[str, int, str, str]] = []
    for rel in _tracked_markdown():
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for sent, line in _sentences_with_lines(text):
            hit = _SCHEDULE_WORD.search(sent)
            if not hit:
                continue
            lo = max(0, hit.start() - _NEGATION_WINDOW)
            hi = hit.end() + _NEGATION_WINDOW
            if _NEGATION.search(sent[lo:hi]):
                continue
            for name, has_schedule in workflows.items():
                if name in sent and not has_schedule:
                    found.append((rel, line, name, sent.strip()[:160]))
    return found


class TestTheOracleIsSound:
    """The detector's own instrument, checked before its verdict is trusted."""

    def test_at_least_one_workflow_exists(self):
        assert _scheduled_workflows(), (
            "no workflows discovered -- the glob has broken and the gate below "
            "would pass vacuously"
        )

    def test_the_oracle_reads_a_key_not_a_mention(self, tmp_path, monkeypatch):
        """``portability.yml`` documents its own ABSENT schedule in a comment.
        A substring oracle reads that as presence -- failure 4 in the docstring."""
        wf = tmp_path / "workflows"
        wf.mkdir()
        (wf / "decoy.yml").write_text(
            "# NO `schedule:` -- dispatch only\non:\n  workflow_dispatch:\n",
            encoding="utf-8",
        )
        (wf / "real.yml").write_text(
            "on:\n  schedule:\n    - cron: '0 0 * * 0'\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "tests.test_workflow_schedule_claims._WORKFLOWS", wf, raising=False
        )
        import tests.test_workflow_schedule_claims as mod
        monkeypatch.setattr(mod, "_WORKFLOWS", wf)
        assert mod._scheduled_workflows() == {"decoy.yml": False, "real.yml": True}

    def test_a_negation_only_governs_its_own_neighbourhood(self):
        """"moves OFF push ONTO a weekly schedule" is a positive claim.
        A blanket sentence-wide negation filter suppressed it -- failure 3."""
        sent = "`x.yml` moves off `push` onto a weekly schedule plus dispatch."
        hit = _SCHEDULE_WORD.search(sent)
        window = sent[max(0, hit.start() - _NEGATION_WINDOW):hit.end() + _NEGATION_WINDOW]
        assert not _NEGATION.search(window), (
            "the negation vocabulary has been widened until it suppresses a real "
            "positive claim; re-measure against the whole tree"
        )


class TestNoDocClaimsAScheduleItsWorkflowLacks:
    def test_the_live_tree_carries_no_unbacked_schedule_claim(self):
        claims = find_false_schedule_claims()
        assert not claims, (
            "shipped prose claims a schedule its workflow does not have:\n"
            + "\n".join(
                f"  {rel}:~{line} names {wf} -- {sent}" for rel, line, wf, sent in claims
            )
            + "\n\nEither restore the workflow's `schedule:` trigger or correct the "
            "sentence. This class decayed twice in one day (7a533c9 retired both "
            "crons and touched no prose), which is why it is gated rather than "
            "reviewed."
        )

    @pytest.mark.parametrize("sentence,expected", [
        ("`portability.yml` runs on a weekly schedule.", True),
        ("`portability.yml` has no cron at all.", False),
        ("`portability.yml` no longer runs nightly.", False),
        ("Both weekly crons were retired, so `test.yml` runs on push.", False),
    ])
    def test_the_predicate_separates_a_claim_from_a_denial(self, sentence, expected):
        """A gate that cannot tell "runs weekly" from "has no cron" would force
        every honest denial to be reworded around it."""
        hit = _SCHEDULE_WORD.search(sentence)
        assert hit is not None
        lo = max(0, hit.start() - _NEGATION_WINDOW)
        negated = bool(_NEGATION.search(sentence[lo:hit.end() + _NEGATION_WINDOW]))
        assert (not negated) is expected, f"misjudged: {sentence!r}"
