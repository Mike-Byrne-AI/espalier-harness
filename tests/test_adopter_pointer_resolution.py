"""Every pointer in a deployed doc must resolve on the tree an adopter gets.

**The class this closes** (ledger §C6, "authored against the self-host tree,
dead in the adopter deploy"). Content is written and verified where the
referent exists -- this repo -- and then shipped where it does not. The
canonical instance: nine-plus seeded docs cite sections of
``docs/SHARP_EDGES.md``, which ``init`` deploys as a 26-line stub against this
repo's 4,295-line document, so every one of those pointers dead-ends on a
fresh adopter tree while the suite stays green.

**Why no existing gate caught it.** Every doc-pointer checker in this suite
resolves against one of three wrong oracles:

- the self-host worktree -- ``test_ladder_claudemd_pointers``,
  ``test_md_heading_anchors``, ``test_doc_source_citations``,
  ``test_sharp_edges_forward_links``, ``reflection.py`` over ``REPO_ROOT``;
- a *path-string set* derived from ``get_seed_docs()`` with no bodies behind
  it -- ``test_deploy_doc_parity`` Arm A, ``test_shipped_asset_md_refs``;
- a shipping artifact whose ``espalier/assets/**`` templates are then
  allowlisted OUT precisely because they are deploy-context --
  ``test_git_archive_parity.ARTIFACT_LINK_ALLOWLIST``, ``test_wheel_payload``.

Four of those scope-outs hand the obligation to a gate by name. One
``ARTIFACT_LINK_ALLOWLIST`` entry is annotated *"verified in a driven init"* --
a human drove ``init`` once and wrote the result into a comment, with nothing
re-verifying it since. This is that gate.

**The oracle is the artifact.** The population is not an inventory of what
*should* deploy; it is every markdown file actually present after ``cmd_init``
runs on a foreign repo. An inventory can drift from the deploy loop. The tree
cannot -- it is what the adopter has.

**Three verdicts, not two.** RESOLVES / DEAD / declared-not-a-pointer. The
third is what keeps the gate readable: shipped prose legitimately *names*
files that are not pointers -- an adopter's own ``CONTRIBUTING.md``, a file a
command creates later. Without that verdict this gate reds on correct prose
and gets switched off, which is ledger class §C19 (an advisory whose own noise
makes it unreadable) and the same mistake §C9 records in a guard.

The exemption table is the §C1 hazard (a hand-kept set standing in for a
derived one), so every excusing enumerator here is bounded by a liveness
guard -- ``test_no_dead_exemptions``, ``test_no_dead_runtime_generated_exemption``
and ``test_every_marker_is_live``. A stale exemption silently widens the hole
it was scoped to, and the markers are the widest hole of the three because
they excuse across every carrier and target at once.

⚠ The runtime-generated bucket is DERIVED, but **not** from
``surface_contract.is_local_only`` -- that was the adjacent question ("must
this never ship?") and it disagreed with the one this gate needs ("will the
harness create it on their tree?") on ``cc/GOAL.md``, silently exempting a
dead pointer this repo had already shipped once. It now reads
``ADOPTER_RUNTIME_GENERATED``, whose membership requires a cited creating
call. And a declared row may carry a ``literal`` so it excuses ONE string
constant rather than blanketing a whole (carrier, target) pair -- without
that, a row added to close a defect re-blinds the gate to that defect's
recurrence.
"""
from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest

from espalier import surface_contract

from _adopter_tree import (
    _STUB_SEEDS,
    assert_is_adopter_tree,
    deployed_markdown,
    deployed_python,
)
from _artifact_links import artifact_members, iter_relative_links
from _doc_pointers import (
    bare_path_refs,
    exec_refs,
    plain_path_refs,
    readable_text,
    resolve_from_root,
    resolve_on_tree,
    section_citations,
    src_path_refs,
    wikilink_refs,
)
from _md_anchors import heading_anchors


@dataclasses.dataclass(frozen=True)
class NotAPointer:
    """A name in shipped prose that is not an instruction to open a file."""

    carrier: str   # deployed relpath of the doc containing the mention
    target: str    # the exact spelling that appears
    reason: str    # why a reader is not sent anywhere
    # Optional whole-constant discriminator (flattened + lowercased). When set,
    # the row excuses ONLY that exact string constant, never every mention of
    # `target` in `carrier`.
    #
    # ⚠ Without it a row is a blanket over the (carrier, target) pair, which
    # contradicts this file's own rule at "Per MENTION, never per
    # (carrier, target)" below — and it was measured switching the gate off for
    # the very defect it had just been used to close: with the session_start
    # row keyed only on the pair, re-adding `Read cc/GOAL.md for the current
    # objective.` to the unconditional orientation prose (DEF-424f, verbatim)
    # reported NOTHING, while the same line naming any other missing doc was
    # reported. Exact-match is deliberately brittle: if one of these constants
    # is reworded, the row stops matching and you are made to re-check whether
    # the new wording is still self-guarding.
    literal: str | None = None


# Prose that tells the reader, at the point of the mention, that the file is
# not theirs to open. This is the REMEDY as much as the exemption: a reader
# who is told "self-host only" is not stranded, and a reader who is not told
# is stranded whether or not a test agrees.
#
# The repo invented this idiom before the gate existed -- eight sites already
# carried one of these parentheticals, and every dead pointer found in the
# first sweep was that same class MINUS the parenthetical. Matching on the
# marker rather than listing the pointers is what makes the gate scale: a new
# citation that carries one passes without anybody touching this file.
# ⚠ Every entry must match something on the DRIVEN tree
# (`test_every_marker_is_live`). Three spellings were removed when that guard
# was added -- "source tree only", "in the espalier source" and the
# near-duplicate "if this repo keeps" -- because none appeared in any deployed
# file. A marker nothing uses is not inert: it is cross-carrier excusal power
# waiting for the first doc that happens to use the phrase for an unrelated
# reason, two lines from a real dead pointer.
_NOT_DEPLOYED_MARKERS: tuple[str, ...] = (
    "not deployed",
    "self-host only",
    "espalier source repo",
    "source repo only",
    "in the source tree",
    # The command bodies' own spelling for "this is the harness's tree, not
    # yours": `/implement-task` step 7 ("On the Espalier-Harness tree
    # `python scripts/proof_tier.py` prints ..."), `/preflight` twice,
    # `/implement-pack` step 6 -- every one beside an invocation of a script
    # `init` never deploys. Read as a marker because a reader told "on the
    # Espalier-Harness tree" knows the sentence is not about theirs; live
    # on the driven tree at the four sites above (the exec arm, DEF-622).
    "espalier-harness tree",
    "espalier-harness source",
    # `docs/ENV_CATALOG.md` on the release tooling: "`espalier init` does not
    # deploy `scripts/`". The same claim as "not deployed", in the active voice.
    "does not deploy",
)

# `.claude/settings.local.json` is the one target no derived exemption
# reaches: the reader's OWN TOOL creates it (Claude Code's `/permissions` and
# its local-settings UI), deployed code never writes it, and the docs name it
# flatly in lists of the paths `write_guard` protects. Four carriers name it;
# each gets its own row below, carrier-bound, rather than a target-wide tuple
# -- a future sentence "edit `.claude/settings.local.json` to add X" in some
# fifth doc IS a pointer at a file the reader may lack, and a blanket would
# have excused it.
_SETTINGS_LOCAL_REASON = (
    "A list of the exact files write_guard protects, beside `.claude/"
    "settings.json`. Claude Code itself creates this one when the reader "
    "uses its local-settings UI; the sentence says the guard covers it, "
    "not that the reader should open it."
)

# Conditional phrasing: the mention names a file the READER may or may not
# have, and says so. Not a pointer at anything on our side.
_CONDITIONAL_MARKERS: tuple[str, ...] = (
    "if you maintain",
    "if your project",
    "if the repo keeps",
    "your equivalent",
    "your project:",
    "whichever",
    "if it keeps one",
    "if one exists",
    # The clearest disclaimer in `handoff.md` was the one this list could not
    # read: "Repos without a `cc/GOAL.md` can skip this step." It states the
    # reader may not have the file more plainly than any spelling above, and
    # scored as an unmarked pointer purely because the vocabulary was narrower
    # than the prose. A marker list is a RECOGNISER — every spelling it misses
    # is a false red on correct text, which is how a gate gets switched off.
    "repos without",
)

# How far from the mention a marker may sit. A parenthetical usually lands on
# the same line, but a wrapped sentence pushes it to the next -- and the
# clause that governs `docs/HOOKS.md`'s See-also block sits one line above its
# second mention. Two lines each way covers every live spelling without
# reaching into an unrelated paragraph.
_MARKER_WINDOW = 2

# A CARRIER-LEVEL disclaimer for the source-path form only. A narrative
# catalogue (`docs/FAILURE_MODES.md`, 69 source citations on the driven tree;
# `docs/ENV_CATALOG.md`, 20) cites the test or module where each pattern was
# found, and the reader is told once, at the top, that those files are the
# Espalier source repo's and not theirs. One sentence in the head IS the
# remedy for that document -- eighty-nine parentheticals would be noise that
# gets the gate switched off (§C19) -- so the gate honours it, under four
# limits: the phrase must sit in the first `_BANNER_WINDOW` lines (a reader
# meets it before any citation); it excuses ONLY the `src-path` form (a dead
# `.md` pointer or a dead invocation in the same document is still reported,
# because a banner about source citations says nothing about those); it is
# BOUND TO ITS CARRIER -- keyed by deployed relpath, the way `_NOT_POINTERS`
# rows are -- because measured in review, the same sentence pasted into the
# head of `docs/WORKFLOW.md` silenced a real dead pointer there with no red,
# and a fourth carrier must be a decision taken here, not a side effect of
# copying a good sentence; and `test_every_banner_is_live` holds the set of
# deployed docs whose head carries a banner EQUAL to this table, both
# directions.
_SOURCE_CITATION_BANNER = (
    "source paths in this document name files in the espalier source repo"
)
_SOURCE_CITATION_BANNERS: dict[str, str] = {
    "docs/FAILURE_MODES.md": _SOURCE_CITATION_BANNER,
    "docs/ENV_CATALOG.md": _SOURCE_CITATION_BANNER,
    "docs/HOOK_ASSUMPTIONS.md": _SOURCE_CITATION_BANNER,
    # The fourth carrier, decided 2026-09-22 (TP-453 2-B): every "declared
    # limit" sentence in the hooks guide cites the pytest node id of the row
    # that pins it (tests/test_declared_limits_contract.py enforces the cite),
    # so the guide names `tests/...` files an adopter does not receive. The
    # banner in its head says so; the contract's form is the only one excused.
    "docs/HOOKS.md": _SOURCE_CITATION_BANNER,
}
_BANNER_WINDOW = 40


def _head(text: str) -> str:
    return " ".join(" ".join(text.splitlines()[:_BANNER_WINDOW]).lower().split())


def _carrier_disclaims_source_paths(carrier: str, text: str) -> bool:
    phrase = _SOURCE_CITATION_BANNERS.get(carrier)
    return bool(phrase) and phrase in _head(text)

# Declared non-pointers -- the residue no marker covers. Each states WHY a
# reader is not stranded. The runtime-generated bucket is deliberately absent:
# it is DERIVED below.
#
# The MARKDOWN arm still contributes none, and that is the design holding. The
# one row below belongs to the CODE arm, where the derived predicates cannot
# reach: `is_local_only` is the wrong axis for a file that is a self-host dev
# doc AND an adopter runtime artifact, and widening it to `internal` is
# foreclosed by `_is_runtime_generated`'s own docstring (it would silence two
# real findings). Better one row that names the creating call than a
# reclassification that quietly moves a shipped surface.
_NOT_POINTERS: tuple[NotAPointer, ...] = (
    NotAPointer(
        carrier="tools/cc/hooks/post_write_check.py",
        target="docs/session-archive.md",
        reason=(
            "Creation announcement, not a pointer: the line prints only on a "
            "zero returncode from `espalier memory prune`, and "
            "`cli.cmd_memory_prune` CREATES this exact path first -- mkdir "
            "the parent, atomic_write_text the archive, then return 0 -- "
            "using its own default because the hook passes no --archive. The "
            "file is on disk before the sentence naming it is on screen, so "
            "no reader is sent anywhere they cannot go."
        ),
    ),
    NotAPointer(
        carrier="tools/cc/hooks/session_start.py",
        target="cc/GOAL.md",
        literal=(
            "--- goal / progress (cc/goal.md -- the last handoff's snapshot, "
            "not live state; re-derive any figure before relying on it) ---"
        ),
        reason=(
            "Self-guarding section header, not a pointer: `_goal_section` "
            "returns '' on OSError and on empty text, so this heading is "
            "concatenated only AFTER a successful non-empty read, and the "
            "compact twin that rewrites it sits inside `if goal:`. It cannot "
            "reach a reader who lacks the file. Keyed to the exact constant "
            "so a NEW cc/GOAL.md mention in this hook is still reported -- "
            "which is what DEF-424f actually was. ⚠ DELIBERATELY A LITERAL, "
            "not a read of `session_start._GOAL_HEADER`: importing the "
            "constant would make this entry follow the header wherever it "
            "goes, which is precisely the tripwire this exemption exists to "
            "BE. It fired as intended on 2026-09-01 when the header gained "
            "its startup staleness hedge, and updating the copy here is the "
            "acknowledgement the design asks for."
        ),
    ),
    NotAPointer(
        carrier="tools/cc/hooks/session_start.py",
        target="cc/GOAL.md",
        literal="cc/goal.md",
        reason=(
            "The `_SECTION_SOURCE` mapping value -- data naming which file "
            "feeds the 'goal' banner section, consumed by the bounding code "
            "and never printed as prose. A reader is never shown this string "
            "as an instruction. Keyed to the bare constant so it excuses the "
            "mapping entry alone."
        ),
    ),
    NotAPointer(
        carrier=".claude/skills/reflect/SKILL.md",
        target=".espalier/memory_candidate_log.jsonl",
        reason=(
            "Created by the reader's own hand: the skill says 'Append one "
            "JSON line per disposition to' it, and the log has no Python "
            "writer by design (`reflect_protocol._read_disposition_log`). "
            "The first append creates the file; nobody is sent to open one."
        ),
    ),
    NotAPointer(
        carrier=".claude/commands/handoff.md",
        target=".espalier/memory_candidate_log.jsonl",
        reason=(
            "The landing check reads the log the reflect skill told the "
            "reader to append to (see the reflect SKILL row above); the "
            "sentence describes what is checked, not a file to open, and an "
            "absent log is a note there, never a red."
        ),
    ),
    NotAPointer(
        carrier=".claude/skills/reflect/SKILL.md",
        target=".espalier/reasoning_review_log.jsonl",
        reason=(
            "Same shape as the candidate log: 'track operator disposition per "
            "finding in' it, one hand-written JSON line per session. The "
            "reader's first line creates it."
        ),
    ),
    NotAPointer(
        carrier="docs/HOOKS.md",
        target="src/app.py",
        reason=(
            "An illustrative adopter file in the plan_guard worked example "
            "('If Claude tries to write `src/app.py` without first creating "
            "a plan') and its quoted deny text. The deny names whatever path "
            "was attempted; no reader is sent to this one."
        ),
    ),
    NotAPointer(
        carrier=".claude/skills/blueprint-authoring/SKILL.md",
        target="espalier/cli.py",
        reason=(
            "An example of the citation SHAPE the skill prescribes ('Cite by "
            "symbol, not by line: `espalier/cli.py::_detect_python_command` "
            "over `espalier/cli.py:NNN`'), drawn from this repo as the agent "
            "bodies' examples are. The reader is shown a form, not a file."
        ),
    ),
    NotAPointer(
        carrier="docs/INSTALL-CI.md",
        target="espalier/__init__.py",
        reason=(
            "A presence test, not a pointer: the detect-source job's gate is "
            "'true only when `espalier/__init__.py` is present AND the "
            "fusion marker is absent', evaluated on the reader's own tree. "
            "Its absence is the documented case for a plain adopter."
        ),
    ),
    NotAPointer(carrier=".claude/agents/code-reviewer.md",
                target=".claude/settings.local.json", reason=_SETTINGS_LOCAL_REASON),
    NotAPointer(carrier="docs/HOOKS.md",
                target=".claude/settings.local.json", reason=_SETTINGS_LOCAL_REASON),
    NotAPointer(carrier="docs/INSTALL-CI.md",
                target=".claude/settings.local.json", reason=_SETTINGS_LOCAL_REASON),
    NotAPointer(carrier="docs/TROUBLESHOOTING.md",
                target=".claude/settings.local.json", reason=_SETTINGS_LOCAL_REASON),
    NotAPointer(
        carrier=".claude/skills/reflect/SKILL.md",
        target="[[slug]]",
        reason=(
            "An instruction template, not a link: the sentence tells the "
            "reader to wire `[[slug]]` into the entry they are promoting, "
            "where `slug` is the name of THEIR new memory file. The wikilink "
            "arm reads it as `slug.md`, which no tree has, and it is the only "
            "wikilink in the deployed set -- so this row is what keeps that "
            "arm's population non-zero (`test_every_form_is_producing`). If "
            "the skill ever spells a real slug here, delete this row."
        ),
    ),
)


def _mention_lines(text: str, target: str, *, raw: bool = False) -> list[int]:
    """Lines mentioning ``target``, honouring name boundaries.

    A plain substring test is wrong here and was wrong in practice:
    ``MEMORY.md`` matches inside ``ESPALIER_MEMORY.md``, so every mention of
    the committed index counted as an unmarked mention of Claude Code's
    machine-local auto-memory file -- an unfixable red, because the text it
    was pointing at was about a different file entirely. Require a non-name
    character (or start-of-line) immediately before the match.

    ``raw`` selects the view. The prose forms read ``readable_text`` (the
    same view their EXTRACTORS use -- reading mentions from raw text while
    pointers come from the stripped view is a false-exempt seam: a marker
    inside a ``` fence could excuse a pointer found in prose, even though a
    fenced pseudo-pointer is never extracted). The invocation form is
    extracted FROM fences, so its mentions are read from the raw text for the
    same reason, in the other direction: the command line is the mention, and
    the `#` comment beside it is the prose a reader sees.
    """
    import re

    pattern = re.compile(rf"(?:(?<=^)|(?<=[^\w./-])){re.escape(target)}")
    view = text if raw else readable_text(text)
    return [i for i, line in enumerate(view.splitlines()) if pattern.search(line)]


def _marker_windows(text: str, target: str, *, raw: bool = False) -> list[str]:
    """One whitespace-collapsed, lowercased window per mention; [] if none."""
    lines = text.splitlines()
    out: list[str] = []
    for idx in _mention_lines(text, target, raw=raw):
        lo = max(0, idx - _MARKER_WINDOW)
        hi = min(len(lines), idx + _MARKER_WINDOW + 1)
        # Collapse whitespace before matching: a marker that wraps across a
        # line ("(Espalier source\n  repo ...") joins to "source   repo" and
        # silently stops matching, which reads as a missing disclaimer on
        # prose that has one -- the gate blaming correct text.
        out.append(" ".join(" ".join(lines[lo:hi]).lower().split()))
    return out


def _every_mention_is_marked(text: str, target: str, *, raw: bool = False) -> bool:
    """True iff EVERY mention of ``target`` sits near a disclaiming marker.

    Every, not any: a file mentioned twice where only the first is marked
    still strands the reader at the second. That is exactly the shape
    ``docs/PACK_AUTHORING.md`` had -- its sibling in ``scope-check.md``
    carried the disclaimer and it did not.
    """
    windows = _marker_windows(text, target, raw=raw)
    if not windows:
        return False
    return all(
        any(m in w for m in _NOT_DEPLOYED_MARKERS + _CONDITIONAL_MARKERS)
        for w in windows
    )


def _governing_comment(ref) -> str:
    """The prose a reader of a fence reads for THIS command: the `#` comment
    on its own line, plus the nearest run of `#` comment lines above it in
    the fence (skipping the commands between).

    A comment introduces the commands that follow it until the next comment.
    The line window is the wrong shape here -- four release commands under
    one comment put the fourth outside it, and the fix would be to repeat the
    comment -- and "anywhere in the fence" is the wrong shape too: measured in
    review, an 88-line reference fence let one comment at its top excuse a
    script 81 lines below it that the comment said nothing about, and a
    marker phrase inside an `echo` string (program output, not prose) marked
    the fence it sat in.
    """
    lines = ref.fence.splitlines()
    idx = ref.lineno - ref.fence_start
    own = lines[idx] if 0 <= idx < len(lines) else ""
    segments = [own[own.find("#"):] if "#" in own else ""]
    i = idx - 1
    while i > 0 and not lines[i].lstrip().startswith("#"):
        i -= 1
    while i > 0 and lines[i].lstrip().startswith("#"):
        segments.append(lines[i])
        i -= 1
    return " ".join(" ".join(segments).lower().split())


def _invocation_is_marked(text: str, ref) -> bool:
    """A fenced invocation is marked by its governing `#` comment; a prose
    one by its own ±2-line window, read on the raw view."""
    markers = _NOT_DEPLOYED_MARKERS + _CONDITIONAL_MARKERS
    if ref.fence is not None and ref.fence_start is not None:
        block = _governing_comment(ref)
        return any(m in block for m in markers)
    # THIS mention's window, not every mention's: each invocation is one
    # ExecRef and is judged once, here -- a fenced copy of the same command
    # elsewhere in the document is its own ref, judged by its own fence.
    lines = text.splitlines()
    idx = ref.lineno - 1
    lo, hi = max(0, idx - _MARKER_WINDOW), min(len(lines), idx + _MARKER_WINDOW + 1)
    window = " ".join(" ".join(lines[lo:hi]).lower().split())
    return any(m in window for m in markers)


# A path-shaped token, a comma, a semicolon or a closing parenthesis: the
# boundaries at which a parenthetical stops belonging to the path before it.
# `a.md (self-host only) and b.md` -- the note is a.md's, and the next path
# ends its slice; "(`a.md` -- plus, on the source repo only, `b.md`)" -- the
# comma ends a.md's slice before a note that belongs to b.md.
#
# The backticked alternatives are PATH-shaped only (a `/` inside, or an
# extension). The first cut matched any backticked span, and since every
# mention this reads is itself backticked, the slice began at the mention's
# own closing backtick and ran to the next one -- so "`x.py` (self-host only
# -- not deployed by `init`)", the house spelling, was never read (23 of 34
# live notes on the driven tree; the third the recogniser was blind to was
# the canonical one). The mention's own closing backtick is stripped first.
_PATH_TOKEN_RE = re.compile(
    r"`[^`]*/[^`]*`|`[^`]+\.\w{1,5}`|(?:[\w.-]+/)*[\w-]+\.\w{1,5}\b|[,;)]"
)


def _any_mention_says_not_deployed(text: str, target: str, *, raw: bool = False) -> bool:
    """True iff a not-deployed note is attached to ``target`` itself.

    The inverse question to ``_every_mention_is_marked``, for the leg-c pin:
    a note that says "not deployed by init" is a claim about the deploy set,
    and a claim is falsified the day the file starts shipping. Conditional
    markers ("if your project keeps one") are not claims about our deploy
    set and are not read here.

    Deliberately NARROWER than the excusing direction. That one reads a
    ±2-line window, which is the right shape for excusing (a wrapped
    sentence pushes the disclaimer to the next line) and the wrong shape for
    accusing: measured on the driven tree, the window attributed a table
    row's "(self-host only -- not deployed)" to the row above it and reported
    seventeen deployed files as falsely disclaimed, sixteen of them correct
    prose. So a note is read as THIS target's only when it sits on the same
    line, AFTER the mention, and BEFORE the next path-shaped token -- the
    place a parenthetical about a file actually goes.

    Limit, stated: a note on the line ABOVE the mention -- the `#` comment
    above a fenced command, the dominant exec-disclaimer shape -- is not read
    here. The excusing direction reads that comment; this direction does not
    accuse from it, because a comment governs a run of commands and the
    accusation would have to pick which of them it was about.
    """
    view = text if raw else readable_text(text)
    needle = re.compile(rf"(?:(?<=^)|(?<=[^\w./-])){re.escape(target)}(?![\w./-])")
    for line in view.splitlines():
        for m in needle.finditer(line):
            tail = line[m.end():]
            if tail.startswith("`"):
                tail = tail[1:]   # the mention's own closing backtick
            nxt = _PATH_TOKEN_RE.search(tail)
            slice_ = (tail[: nxt.start()] if nxt else tail).lower()
            if any(marker in slice_ for marker in _NOT_DEPLOYED_MARKERS):
                return True
    return False


def _is_runtime_generated(target: str) -> bool:
    """Exemption: deployed code CREATES this on the adopter's own tree.

    ⚠ This used to read ``surface_contract.is_local_only(target)``, and that
    was the adjacent question. ``is_local_only`` answers *"must this never
    ship?"*; the exemption needs *"will the harness write it on their tree?"*
    They agree on `cc/_working_summary.md` and `reports/strengthen_report.md`
    and DISAGREE on `cc/GOAL.md`, whose local-only entry exists as
    defense-in-depth against leaking espalier's OWN goal doc — nothing creates
    one for an adopter. The old predicate therefore exempted
    `session_start.py`'s banner line, which PRINTS `cc/GOAL.md` at a reader
    who will never have the file, and did so while the code arm's failure
    message declared that arm had "none by construction".

    ``surface_contract.ADOPTER_RUNTIME_GENERATED`` is the home, and membership
    requires a cited creating call rather than a classification.

    Still deliberately NOT derived from ``internal``: that would swallow
    `docs/REDEFINED_INFORMATION_REGISTRY.md` and
    `docs/RELEASE_FINDINGS_LEDGER.md`, which are real dead pointers a deployed
    doc makes at maintainer-only material. Widening this predicate to
    `classify_release_path(t) != "public"` would turn two findings into
    silence.
    """
    return surface_contract.is_adopter_runtime_generated(target)


def _exempt(carrier: str, target: str, text: str) -> bool:
    if _is_runtime_generated(target):
        return True
    if _every_mention_is_marked(text, target):
        return True
    return any(
        e.carrier == carrier and e.target == target and e.literal is None
        for e in _NOT_POINTERS
    )


@dataclasses.dataclass(frozen=True)
class Finding:
    carrier: str
    target: str
    form: str
    section: str | None = None
    lineno: int | None = None


# ── Code carriers ────────────────────────────────────────────────────────────
#
# A deployed `.py` is an adopter-facing surface too, and this is the arm that
# says so. `tools/cc/ci_guard.py` ends its Harness Guard failure with "See
# docs/INSTALL-CI.md for details." -- printed into a failing CI log, read by a
# contributor to the adopter's repo, pointing at a file `init` and `install-ci`
# both decline to deploy. That is DEF-503, and the markdown arm above cannot
# see it: its population is `.md` files.
#
# **A Python file has layers a markdown file does not, and only one of them is
# adopter-facing.** Every `.md` byte is read by somebody; a `.py` holds
# docstrings nobody opens, path constants the code joins onto `root`, and
# witness tables the harness matches against -- none of which instruct a
# reader to go anywhere. Measured on the driven tree: **157 `.md` mentions
# across 38 deployed `.py` files, of which 26 are adopter-visible.** A gate
# that reported all 157 would be switched off within a week (§C19), so the arm
# needs the same third verdict the markdown arm has, computed differently.
#
# **The verdict is REACHABILITY, and it is derived, not listed.** A mention is
# adopter-visible when it is emitted (inside an emitting call), returned
# (inside a `return` -- the shape every banner builder in `session_start.py`
# uses), or REFERENCED from either, and when the site that reads it is not
# self-host-gated. Everything else is furniture.
#
# Every number in this header is re-derivable from the counters
# `_code_mentions` returns; `test_no_counter_is_dead` asserts each is still
# non-zero, because a count in a comment is a drift class like any other.
#
# **Per MENTION, never per (carrier, target).** Deduplicating by target was a
# live false pass in this arm's own construction: `session_start`'s `_SECTION_SOURCE` holds
# an inert `_SECTION_SOURCE` entry for `docs/STANDING_PRINCIPLES.md` and
# `_standing_principles_index` emits the same path in banner prose. Collapsing them
# let the inert mention's verdict decide the emitted one's -- the gate's own
# bookkeeping waving a pointer through, which is `docs/FAILURE_MODES.md`
# §10.11 wearing a third face. One mention, one verdict.

# **Reachability must cross module boundaries, and that is not a refinement --
# it is the difference between reading the deny messages and not.** This repo
# keeps its deny STRINGS in one module and its deny CALLS in another, on
# purpose: `tools/cc/hooks/_denial_reasons.py` opens by saying so ("the
# deny()/block() FUNCTIONS stay per-hook ...; the REASON STRINGS centralize
# here"). So `config_guard` reads
# `block(_denial_reasons.KILL_SWITCH_DETECTED.format(...))` while the string
# itself is a module-level assignment in a different file. A per-file lexical
# rule sees all 31 of those templates as furniture -- an arm written to check
# hook deny messages, blind to every hook deny message that follows the
# project's own documented convention. Caught in review, before it shipped.
#
# The same resolution covers `session_start._SECTION_SOURCE` (a module-level
# dict whose values are interpolated into the banner's truncation notice at
# `:454-462`) and `plan_guard._PLAN_EXEMPT_HINT`. Grouping constants into a
# table is the normal way to write this code, so a rule that cannot follow one
# hop is a rule that will be wrong more often as the code gets tidier.

# Calls whose string arguments reach a human. `write` covers
# `sys.stderr.write` / `sys.stdout.write` without pinning the receiver's
# spelling; `deny`/`block`/`warn` are this repo's own emitters (see
# `tests/test_denial_reasons.py::DENY_FUNCS`). `append`/`extend` are here
# because accumulate-then-join is as common as printing in the deployed set --
# `session_resume.assess_repo_state` appends its recommendations and
# `render_recovery_report` prints them.
#
# `advise` was in this set on the first draft and is deliberately gone: a
# census of the deployed corpus found ZERO definitions and ZERO call sites. It
# read like coverage of the advisory surface while covering nothing -- the §C1
# hazard this file's own header warns about, in the set meant to detect it.
# `test_every_emit_verb_is_live` keeps the next phantom out.
_EMITTING_CALLS: frozenset[str] = frozenset(
    {"print", "deny", "block", "warn", "write", "append", "extend"}
)

# Prose that is CORRECT precisely when the file is missing. "No
# ESPALIER_MEMORY.md found" is not a pointer -- it is a report that the
# pointer's target is absent, and resolving it would demand the file exist so
# the message announcing its absence can be true. Same "the remedy IS the
# exemption" logic as `_NOT_DEPLOYED_MARKERS` above.
_ABSENCE_MARKERS: tuple[str, ...] = (
    "no ", "not found", "is empty", "absent", "missing", " yet", "if present",
)


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _string_constants(node: ast.AST) -> set[int]:
    return {
        id(n) for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _module_level_constants(module: ast.Module) -> dict[str, list[ast.Constant]]:
    """``NAME -> [string Constants]`` for module-level assignments.

    Both `NAME = ...` and the annotated `NAME: tuple[str, ...] = ...` this
    repo prefers. The whole assigned value is walked, so a name bound to a
    tuple/dict of strings yields every member -- which is the point: a
    registry read into a deny message is as adopter-visible as a scalar one.
    """
    out: dict[str, list[ast.Constant]] = {}
    for stmt in module.body:
        targets: list[ast.expr]
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        consts = [
            n for n in ast.walk(value)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        if not consts:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                out.setdefault(target.id, []).extend(consts)
    return out


def _parent_map(module: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(module):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _self_host_gate_names(module: ast.Module) -> set[str]:
    """Local names bound to an ``is_self_host_repo(...)`` result."""
    names: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _call_name(node.value) != "is_self_host_repo":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _is_self_host_test(test: ast.AST, gate_names: set[str]) -> bool:
    for node in ast.walk(test):
        if isinstance(node, ast.Name) and node.id in gate_names:
            return True
        if isinstance(node, ast.Call) and _call_name(node) == "is_self_host_repo":
            return True
    return False


def _self_host_only_functions(module: ast.Module) -> set[str]:
    """Functions whose EVERY call site sits behind a self-host test.

    One `session_start.py` renderer qualifies today: `_standing_principles_index`.
    Its prose names `docs/STANDING_PRINCIPLES.md`, which reaches no adopter path,
    and the banner correctly never shows that line there.

    Its two former companions -- `_footgun_pointer` and `_memory_toc` -- were
    exempt for the same reason until their gates were flipped from repo identity
    to an artifact test. They now have ungated call sites, drop out of this set
    BY DERIVATION, and their pointers are resolved like everyone else's. That is
    the argument for computing this set instead of listing it: the exemption
    expires on its own when its reason does, so the gate GAINS coverage from the
    fix rather than being re-blinded by a hand-kept carve-out.

    EVERY call site, not any: a renderer that gained one ungated caller is
    exactly the regression this should stop excusing. A function with no call
    sites in its own module is NOT self-host-only -- absence of evidence would
    otherwise read as a gate.
    """
    gate_names = _self_host_gate_names(module)
    if not gate_names:
        return set()
    parents = _parent_map(module)
    defined = {
        node.name for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    call_sites: dict[str, list[ast.Call]] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in defined:
                call_sites.setdefault(name, []).append(node)

    def gated(node: ast.AST) -> bool:
        cur: ast.AST | None = node
        while cur is not None:
            parent = parents.get(id(cur))
            if isinstance(parent, ast.If) and any(
                cur is stmt for stmt in parent.body
            ) and _is_self_host_test(parent.test, gate_names):
                return True
            if isinstance(parent, ast.IfExp) and _is_self_host_test(
                parent.test, gate_names
            ):
                return True
            cur = parent
        return False

    return {
        name for name, sites in call_sites.items()
        if sites and all(gated(site) for site in sites)
    }


def _self_host_only_spans(module: ast.Module) -> list[tuple[int, int]]:
    """Line spans that never execute on an adopter's tree.

    Two sources, both derived:

    1. Render functions of a ``face="sync"`` reinject rule -- but keyed on
       ``event == "PostToolUse"``, NOT on the face. `_reinject`'s sync-rule header comment
       explains the gate as a property of sync rules; it is really a property
       of ONE call site. Five hooks call `_reinject.check()` and only
       `post_write_check._run_main` wraps it in `is_self_host_repo`;
       the `write_guard`, `session_start`, `task_router` and
       `context_reinject_failure` call sites do not. A
       `face="sync"` rule registered on any other event fires on every adopter
       repo, and keying on the face would have excused its pointers as
       self-host-only. `tests/test_reinject_sync.py` pins
       ``PostToolUse => sync``; nothing pins the converse, which is the
       direction this needed. `test_sync_face_rules_are_all_posttooluse`
       below closes that gap.
    2. Functions whose every call site sits behind a self-host test.
    """
    spans: list[tuple[int, int]] = []
    gated_names: set[str] = set()

    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or _call_name(node) != "ReinjectRule":
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        event = kwargs.get("event")
        if not (isinstance(event, ast.Constant) and event.value == "PostToolUse"):
            continue
        render = kwargs.get("render")
        if isinstance(render, ast.Name):
            gated_names.add(render.id)

    gated_names |= _self_host_only_functions(module)

    for node in ast.walk(module):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in gated_names
        ):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def _reachable_constants(
    module: ast.Module,
    stem: str,
    corpus: dict[str, dict[str, list[ast.Constant]]],
    gated_spans: list[tuple[int, int]],
) -> tuple[set[int], set[int]]:
    """``(reachable_ungated, reachable_gated)`` string-constant ids.

    Reachable = emitted, returned, or REFERENCED from either. The reference
    clause is the cross-module hop: a `Name` or `<module>.<NAME>` inside an
    emitting call's arguments drags that module-level constant's strings in,
    wherever they are defined.

    **The gate travels with the reference, and it has to.** Gating was first
    keyed on the CONSTANT's own line, which is wrong for exactly the shape
    this resolution exists to find: `_reinject._HOOK_COUNT_WITNESSES` is
    defined at module level -- outside any function's span -- and read at
    `:259` inside `_render_new_hook_witness`, a self-host-gated PostToolUse
    render. Line-keyed gating called the definition ungated and reported its
    `docs/QUICKSTART.md` member as a dead adopter pointer, which it is not.
    A constant is only as visible as the site that reads it.

    Reached from both a gated and an ungated site, a constant counts as
    UNGATED. A shared template that any live path can print is adopter-facing,
    and the conservative direction here is the one that keeps a finding.
    """
    ungated: set[int] = set()
    gated: set[int] = set()
    refs: list[tuple[bool, str | None, str]] = []

    def absorb(node: ast.AST, is_gated: bool) -> None:
        bucket = gated if is_gated else ungated
        bucket.update(_string_constants(node))
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                refs.append((is_gated, sub.value.id, sub.attr))
            elif isinstance(sub, ast.Name):
                refs.append((is_gated, None, sub.id))

    for node in ast.walk(module):
        if isinstance(node, ast.Call) and _call_name(node) in _EMITTING_CALLS:
            site = node
        elif isinstance(node, ast.Return) and node.value is not None:
            site = node.value
        else:
            continue
        absorb(site, any(lo <= node.lineno <= hi for lo, hi in gated_spans))

    for is_gated, module_name, attr in refs:
        table = corpus.get(module_name if module_name else stem, {})
        for const in table.get(attr, ()):
            (gated if is_gated else ungated).add(id(const))

    return ungated, gated - ungated


def _code_mentions(tree: Path) -> tuple[list[Finding], dict[str, int]]:
    """Every ``.md`` mention in a deployed ``.py``, with a visibility verdict."""
    members = artifact_members(tree)
    dead: list[Finding] = []
    totals = {
        "carrier": 0,
        "mention": 0,
        "visible": 0,
        "x-module-ref": 0,
        "excl-self-host": 0,
        "excl-runtime": 0,
        "excl-absence": 0,
        "excl-declared": 0,
    }

    modules: dict[str, ast.Module] = {}
    for path in deployed_python(tree):
        carrier = path.relative_to(tree).as_posix()
        try:
            modules[carrier] = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a deployed file must parse
            raise AssertionError(
                f"{carrier} does not parse on the adopter's tree: {exc}. The "
                f"harness deployed a broken script, and every pointer in it is "
                f"invisible to this arm -- a silent hole, not a smaller one."
            ) from exc
        totals["carrier"] += 1

    corpus = {
        Path(carrier).stem: _module_level_constants(module)
        for carrier, module in modules.items()
    }

    for carrier, module in modules.items():
        stem = Path(carrier).stem
        lexical = _string_constants(module)
        gated_spans = _self_host_only_spans(module)
        reachable, gated = _reachable_constants(module, stem, corpus, gated_spans)
        # A constant reached only from ANOTHER module is the `_denial_reasons`
        # shape; counting it proves the cross-module hop is live rather than
        # decorative.
        totals["x-module-ref"] += len(reachable - lexical)

        for node in ast.walk(module):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            targets = plain_path_refs(node.value)
            if not targets:
                continue
            if id(node) in gated:
                totals["mention"] += len(targets)
                totals["excl-self-host"] += len(targets)
                continue
            if id(node) not in reachable:
                totals["mention"] += len(targets)
                continue
            haystack = " ".join(node.value.lower().split())
            for target in targets:
                totals["mention"] += 1
                totals["visible"] += 1
                if _is_runtime_generated(target):
                    totals["excl-runtime"] += 1
                    continue
                if any(marker in haystack for marker in _ABSENCE_MARKERS):
                    totals["excl-absence"] += 1
                    continue
                if any(
                    e.carrier == carrier and e.target == target
                    and (e.literal is None or e.literal == haystack)
                    for e in _NOT_POINTERS
                ):
                    totals["excl-declared"] += 1
                    continue
                if resolve_from_root(members, target) is not None:
                    continue
                dead.append(
                    Finding(carrier, target, "code-constant", lineno=node.lineno)
                )

    return dead, totals


def _derive(tree: Path) -> tuple[list[Finding], list[Finding], dict[str, int]]:
    """Return (dead file pointers, dead section citations, per-form totals)."""
    members = artifact_members(tree)
    dead_files: list[Finding] = []
    dead_sections: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    totals = {
        "md-link": 0, "bare-path": 0, "section-citation": 0, "anchor": 0,
        "src-path": 0, "exec": 0, "wikilink": 0,
    }

    for md in deployed_markdown(tree):
        carrier = md.relative_to(tree).as_posix()
        text = md.read_text(encoding="utf-8", errors="replace")

        # Source files: `tests/test_hooks.py`, `espalier/cli.py`,
        # `.espalier/freshness.json`. The DEF-626 arm. Same resolver, same
        # exemptions as the `.md` bare-path form, plus the carrier banner.
        banner = _carrier_disclaims_source_paths(carrier, text)
        for filename in src_path_refs(text):
            totals["src-path"] += 1
            if resolve_on_tree(members, carrier, filename) is not None:
                continue
            if banner or _exempt(carrier, filename, text):
                continue
            if (carrier, filename) in seen:
                continue
            seen.add((carrier, filename))
            dead_files.append(Finding(carrier, filename, "src-path"))

        # Invocations: `python scripts/x.py`, in prose AND fences. The DEF-622
        # arm. A fenced invocation is excused by a `-f` test on the same path
        # in the same fence (the reader's shell skips it), or by a marker
        # beside the mention read in the RAW view (a `#` comment in the fence
        # is prose). The banner does not apply: it disclaims citations, and
        # this is an instruction to run.
        for ref in exec_refs(text):
            totals["exec"] += 1
            if resolve_on_tree(members, carrier, ref.file) is not None:
                continue
            if ref.guarded or _invocation_is_marked(text, ref):
                continue
            if any(
                e.carrier == carrier and e.target == ref.file and e.literal is None
                for e in _NOT_POINTERS
            ):
                continue
            key = (carrier, f"{ref.file}@exec")
            if key in seen:
                continue
            seen.add(key)
            dead_files.append(Finding(carrier, ref.file, "exec", lineno=ref.lineno))

        # Wikilinks: `[[slug]]` resolves as `slug.md` anywhere on the tree.
        # The DEF-412i arm -- the one cross-reference spelling no other form
        # could see.
        for slug in wikilink_refs(text):
            totals["wikilink"] += 1
            spelled = f"[[{slug}]]"
            if resolve_on_tree(members, carrier, f"{slug}.md") is not None:
                continue
            if _exempt(carrier, spelled, text) or (carrier, spelled) in seen:
                continue
            seen.add((carrier, spelled))
            dead_files.append(Finding(carrier, spelled, "wikilink"))

        for filename, section in section_citations(text):
            totals["section-citation"] += 1
            target = resolve_on_tree(members, carrier, filename)
            if target is None:
                if not _exempt(carrier, filename, text) and (carrier, filename) not in seen:
                    seen.add((carrier, filename))
                    dead_files.append(Finding(carrier, filename, "section-citation"))
                continue
            if section in _headings(tree / target):
                continue
            # The same marker rule the file arm uses. A back-reference written
            # `... section "X" (if you maintain an index)` is a note about the
            # reader's OWN index, not a promise that a heading is there --
            # which is the honest shape for docs/sharp-edges/*.md, whose
            # "Linked from:" line points at the adopter's near-empty
            # SHARP_EDGES.md rather than at ours.
            if _every_mention_is_marked(text, filename):
                continue
            dead_sections.append(
                Finding(carrier, filename, "section-citation", section)
            )

        for filename in bare_path_refs(text):
            totals["bare-path"] += 1
            if resolve_on_tree(members, carrier, filename) is not None:
                continue
            if _exempt(carrier, filename, text) or (carrier, filename) in seen:
                continue
            seen.add((carrier, filename))
            dead_files.append(Finding(carrier, filename, "bare-path"))

        for raw, candidates, fragment in iter_relative_links(text, carrier):
            totals["md-link"] += 1
            landed = next((c for c in candidates if c in members), None)
            if landed is None:
                if _exempt(carrier, raw, text) or (carrier, raw) in seen:
                    continue
                seen.add((carrier, raw))
                dead_files.append(Finding(carrier, raw, "md-link"))
                continue
            # The file landed -- now the #anchor, which every other checker in
            # this suite drops on the floor. `iter_relative_links` returns the
            # fragment precisely so it can be validated, and on the deploy tree
            # it matters more than on ours: a heading that exists in this
            # repo's copy of a doc may be absent from the seeded one.
            if not fragment or not landed.endswith(".md"):
                continue
            totals["anchor"] += 1
            anchors = heading_anchors(
                (tree / landed).read_text(encoding="utf-8", errors="replace")
            )
            if fragment.lower() not in anchors and not _exempt(
                carrier, raw, text
            ):
                key = (carrier, f"{raw}#{fragment}")
                if key not in seen:
                    seen.add(key)
                    dead_sections.append(
                        Finding(carrier, landed, "md-anchor", f"#{fragment}")
                    )

    return dead_files, dead_sections, totals


def _false_notes(tree: Path) -> list[Finding]:
    """Pointers a deployed doc SAYS are not deployed that the tree HAS.

    DEF-382a leg c. The not-deployed markers are the gate's own excusal
    vocabulary, and each one is a claim about the deploy set: "(self-host
    only -- not deployed by `init`)" beside `scripts/check_pack_landing.py`
    is true today because nothing ships that script. Nothing tested the
    claim. The day a marked file joins the deploy set -- a script promoted
    into `INIT_TOOL_SCRIPTS`, a doc added to the seed set -- the note becomes
    a lie the reader acts on (they skip a step they now could run), and the
    excusing direction of this gate keeps passing, because a marked mention
    is never resolved at all.

    Read over the same three forms the markers excuse (bare `.md` paths,
    source paths, invocations), on the same views. Conditional markers are
    not read: "if your project keeps one" is about the reader's tree, not a
    claim about ours.
    """
    members = artifact_members(tree)
    out: list[Finding] = []
    for md in deployed_markdown(tree):
        carrier = md.relative_to(tree).as_posix()
        text = md.read_text(encoding="utf-8", errors="replace")
        candidates: list[tuple[str, bool]] = (
            [(f, False) for f in bare_path_refs(text)]
            + [(f, False) for f in src_path_refs(text)]
            + [(r.file, True) for r in exec_refs(text)]
        )
        seen: set[tuple[str, bool]] = set()
        for target, raw in candidates:
            if (target, raw) in seen:
                continue
            seen.add((target, raw))
            landed = resolve_on_tree(members, carrier, target)
            if landed is None:
                continue
            # The two Tier-3 stubs are a DIFFERENT document from the source
            # tree's copy of the same name: `docs/TROUBLESHOOTING.md` sends
            # the reader to "`docs/SHARP_EDGES.md` in the source tree if
            # you've cloned it", and that sentence is true precisely because
            # the deployed one is a 26-line stub. A note about the source
            # copy is not a false note about the stub.
            if landed in _STUB_SEEDS:
                continue
            if _any_mention_says_not_deployed(text, target, raw=raw):
                out.append(Finding(carrier, target, "exec" if raw else "path"))
    return out


def _headings(path: Path) -> set[str]:
    import re

    return {
        m.group(1).strip()
        for m in re.finditer(
            r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*$",
            path.read_text(encoding="utf-8", errors="replace"),
        )
    }


@pytest.fixture(scope="module")
def derived(adopter_tree):
    return _derive(adopter_tree)


@pytest.fixture(scope="module")
def false_notes(adopter_tree):
    return _false_notes(adopter_tree)


class TestAdopterPointerResolution:
    def test_the_oracle_is_an_adopter_tree(self, adopter_tree):
        """Meta-check: the whole gate is vacuous on a self-host tree.

        Seeds are skip-if-exists, so a self-host checkout keeps its own
        4,295-line ``SHARP_EDGES.md`` and every section citation resolves --
        green for the one reason that proves nothing.
        """
        assert_is_adopter_tree(adopter_tree)

    def test_every_form_is_producing(self, derived):
        """Per-FORM vacuity guard, not one assertion over the union.

        Any single form can go to zero -- a regex breaks, a helper is renamed
        -- while the other two keep a union non-empty, and the pointers only
        that form could see vanish from the population. That reads as "nothing
        dangling" rather than "the scanner broke", which is the failure this
        whole file exists to end.

        ``anchor`` IS EXPECTED TO BE TINY -- measured at exactly 1
        (``docs/WORKFLOW.md -> HOOKS.md#plan-status-and-the-mutation-window``)
        against ~194 bare-path and ~21 md-link. That is not a bug and not a
        thin-population smell to go hunting for: the self-host corpus has only
        6 ``.md#anchor`` links at all, and 5 of them point at docs
        (``QUICKSTART.md``, ``RELEASE_CHECKLIST.md``, ``SECURITY_TAXONOMY.md``)
        that are never seeded, so they cannot reach the deployed corpus this
        gate scans.

        The practical consequence, stated so the next person does not lose an
        hour: an ordinary reword of that ONE sentence in ``docs/WORKFLOW.md``
        zeroes this arm and fires the assertion below. The right response then
        is usually "the last anchored link in the deployed corpus went away",
        not "the scanner broke" -- check that first.

        ``wikilink`` is the same shape, at exactly 1: the reflect skill's
        ``[[slug]]`` instruction template (declared not-a-pointer above) is
        the only wikilink in the deployed set. A reword there zeroes this arm
        too; the response is the same -- confirm the population went away
        before suspecting the matcher.
        """
        _dead_files, _dead_sections, totals = derived
        for form, count in totals.items():
            assert count > 0, (
                f"zero {form!r} pointers derived from the deployed doc set. "
                f"Either every one was removed, or that arm is now vacuous "
                f"and its findings are silently gone."
            )

    def test_every_section_citation_resolves(self, derived):
        _dead_files, dead_sections, _totals = derived
        assert not dead_sections, (
            f"{len(dead_sections)} citation(s) name a section that does not "
            f"exist on the adopter's tree:\n"
            + "\n".join(
                f"  {f.carrier}\n      -> {f.target} § {f.section!r}"
                for f in sorted(
                    dead_sections, key=lambda f: (f.carrier, f.section or "")
                )
            )
            + "\n\nThe file lands; the section does not. For "
            "docs/SHARP_EDGES.md and docs/CONVENTIONS.md this is NOT fixable "
            "by shipping the content: both deploy as near-empty stubs on "
            "purpose, and each says so in its own body -- 'It is yours ... "
            "safe to rewrite completely'. Shipping this repo's copy would "
            "break that promise. De-reference the pointer instead: say what "
            "the reader needs inline, or drop it."
        )

    def test_every_file_pointer_resolves(self, derived):
        dead_files, _dead_sections, _totals = derived
        assert not dead_files, (
            f"{len(dead_files)} pointer(s) in deployed docs name a file that "
            f"is absent from the adopter's tree:\n"
            + "\n".join(
                f"  {f.target:44s} <- {f.carrier}   [{f.form}]"
                for f in sorted(dead_files, key=lambda f: (f.target, f.carrier))
            )
            + "\n\nFive fixes, in the order worth checking:\n"
            "  1. The target SHOULD ship -> add it to "
            "managed_inventory._SEED_DOC_REL_PATHS (a doc) or the deploy "
            "constants in espalier.cli (a script).\n"
            "  2. The pointer is real but the target is maintainer-only -> "
            "delete the pointer, or state the fact inline instead of "
            "sending the reader to a file they do not have; a mention that "
            "must stay says so beside itself ('Espalier source repo -- not "
            "deployed by `init`', within two lines).\n"
            "  3. [exec] A fenced invocation of a self-host script -> guard "
            "the block on the file (`if [ -f scripts/x.py ]; then ... fi`) "
            "so the reader's shell skips it, or put the marker in a `#` "
            "comment beside the command.\n"
            "  4. [src-path] A catalogue that cites the source file behind "
            "every entry -> one banner sentence in its head "
            "(_SOURCE_CITATION_BANNERS) says those files are the source "
            "repo's; it excuses this form only.\n"
            "  5. It is NOT a pointer -- shipped prose may legitimately NAME "
            "a file (an adopter's own CONTRIBUTING.md, a file a command "
            "creates later) -> add a NotAPointer row with the clause that "
            "makes it non-instructional. Never add a row to silence a real "
            "pointer; that is the defect this gate exists to catch."
        )

    def test_every_not_deployed_note_names_a_file_the_adopter_lacks(self, false_notes):
        """DEF-382a leg c: a 'not deployed' note is a claim, and the tree is
        its oracle. See ``_false_notes``."""
        assert not false_notes, (
            f"{len(false_notes)} note(s) say a file is not deployed, and the "
            f"adopter's tree has it:\n"
            + "\n".join(
                f"  {f.target:44s} <- {f.carrier}   [{f.form}]"
                for f in sorted(false_notes, key=lambda f: (f.carrier, f.target))
            )
            + "\n\nThe file started shipping and the disclaimer beside it did "
            "not follow. Delete the note (the reader can open the file now), "
            "or, if the file must NOT ship, take it back out of the deploy set."
        )

    def test_every_banner_is_live(self, adopter_tree):
        """The set of deployed docs whose head carries a banner sentence
        EQUALS the declared carrier table, both directions.

        A carrier banner is excusal power over a whole document's source
        citations. A declared carrier whose head no longer carries the
        phrase is a row that protects nothing; a deployed doc carrying the
        phrase without a row is the review-measured hole -- the sentence
        copied into another doc's head, excusing nothing yet, reading as if
        it did. Either way the table and the tree must agree.
        """
        carrying = {
            p.relative_to(adopter_tree).as_posix()
            for p in deployed_markdown(adopter_tree)
            if any(
                phrase in _head(p.read_text(encoding="utf-8", errors="replace"))
                for phrase in set(_SOURCE_CITATION_BANNERS.values())
            )
        }
        assert carrying == set(_SOURCE_CITATION_BANNERS), (
            f"banner carriers on the driven tree {sorted(carrying)} != "
            f"declared {sorted(_SOURCE_CITATION_BANNERS)}. A doc that gained "
            f"the sentence needs a row here (a decision); a row whose doc "
            f"lost it needs deleting."
        )

    def test_every_exemption_carries_a_reason(self):
        thin = [e for e in _NOT_POINTERS if len(e.reason.strip()) < 20]
        assert not thin, (
            f"exemption(s) with no usable reason: "
            f"{[(e.carrier, e.target) for e in thin]}. A row without a stated "
            f"reason is indistinguishable from a waved-through defect."
        )

    def test_no_dead_exemptions(self, adopter_tree):
        """A row that no longer matches anything is silently widening scope.

        The pointer it excused may have been fixed -- in which case the row
        should go -- or the carrier may have been renamed, in which case the
        row is now protecting nothing while reading as though it does.
        """
        dead: list[tuple[str, str]] = []
        for entry in _NOT_POINTERS:
            carrier = adopter_tree / entry.carrier
            if not carrier.is_file():
                dead.append((entry.carrier, "carrier absent from the deploy tree"))
                continue
            text = carrier.read_text(encoding="utf-8", errors="replace")
            if entry.target not in text:
                dead.append((entry.carrier, f"{entry.target} no longer appears"))
        assert not dead, (
            f"{len(dead)} exemption row(s) match nothing on the driven tree: "
            f"{dead}. Delete them -- a stale exemption widens the gate's blind "
            f"spot while reading like a considered decision."
        )

    def test_the_runtime_exemption_is_not_the_local_only_set(self):
        """Regression pin for the conflation that hid a printed dead pointer.

        The exemption asks *"does deployed code create this on their tree?"*
        and MUST NOT drift back to ``is_local_only``, which asks *"must this
        never ship?"*. `cc/GOAL.md` separates them: local-only as
        defense-in-depth against leaking espalier's own goal doc, and created
        by nothing on an adopter tree. If it ever exempts again, the banner
        line that prints it goes back to being invisible.
        """
        assert not _is_runtime_generated("cc/GOAL.md"), (
            "cc/GOAL.md is exempt again -- the predicate has drifted back to "
            "is_local_only. Nothing creates this file on an adopter's tree; "
            "see surface_contract.ADOPTER_RUNTIME_GENERATED."
        )
        assert surface_contract.is_local_only("cc/GOAL.md"), (
            "cc/GOAL.md stopped being local-only, so this test no longer "
            "discriminates between the two predicates. Pick another path "
            "that is local-only but not runtime-generated, or delete this."
        )
        for member in surface_contract.ADOPTER_RUNTIME_GENERATED:
            assert _is_runtime_generated(member), member

    def test_every_marker_is_live(self, adopter_tree):
        """The marker lists are the broadest excusal surface here, and were
        the only enumerator with no liveness guard.

        `_EMITTING_CALLS` has `test_every_emit_verb_is_live`; `_NOT_POINTERS`
        has `test_no_dead_exemptions`; `ADOPTER_RUNTIME_GENERATED` got one when
        it was added. These two had none — and a dead marker is not inert. It
        is cross-carrier, cross-target excusal power sitting in a ±2-line
        window, so the first doc to use the phrase for an unrelated reason
        silences whatever real dead pointer happens to sit beside it.
        Demonstrated on `docs/RELEASE_FINDINGS_LEDGER.md` — the path
        `_is_runtime_generated`'s own docstring names as a real dead pointer —
        which a sentence about monorepo layouts two lines away was enough to
        hide.

        Scoped to the DRIVEN tree, not this repo: a marker that appears only
        in self-host files excuses nothing an adopter ever reads, and counting
        it here would be the proxy-oracle mistake this gate exists to avoid.
        """
        corpus = [
            p.read_text(encoding="utf-8", errors="replace").lower()
            for p in adopter_tree.rglob("*")
            if p.is_file() and p.suffix in {".md", ".py"}
        ]
        assert corpus, "driven tree yielded no scannable files"
        dead = [
            m for m in _NOT_DEPLOYED_MARKERS + _CONDITIONAL_MARKERS
            if not any(m in text for text in corpus)
        ]
        assert not dead, (
            f"marker(s) matching nothing on the driven adopter tree: {dead}. "
            f"Delete them — an unused marker is excusal power with no live "
            f"justification, and the ±2-line window means it need not even "
            f"govern the pointer it silences."
        )

    def test_no_dead_runtime_generated_exemption(self, adopter_tree):
        """Every exempted path must still be cited by something deployed.

        An exemption for a path nobody mentions protects nothing while
        reading like a considered decision -- the same hazard
        ``test_no_dead_exemptions`` catches for the hand-written rows, applied
        to the derived set so it cannot grow silently.
        """
        assert surface_contract.ADOPTER_RUNTIME_GENERATED, (
            "the exemption set is empty -- either every runtime-generated "
            "citation is gone (delete the predicate) or the tuple was cleared "
            "by accident (the gate now reds on correct prose)."
        )
        haystacks = [
            p.read_text(encoding="utf-8", errors="replace")
            for p in adopter_tree.rglob("*")
            if p.is_file() and p.suffix in {".md", ".py"}
        ]
        uncited = [
            m for m in surface_contract.ADOPTER_RUNTIME_GENERATED
            if not any(m in h for h in haystacks)
        ]
        assert not uncited, (
            f"exempted but cited by nothing on the driven tree: {uncited}. "
            "Drop the row -- an exemption nobody needs is a blind spot "
            "waiting for a future citation to fall into."
        )


class TestPointerForms:
    """Must-find / must-not-find pins for the three matchers this lane added
    to `_doc_pointers`, in the style of the sibling matchers' pins. The
    population floor in `test_every_form_is_producing` only says each arm
    sees SOMETHING; these say what."""

    def test_exec_refs_reads_every_file_in_the_argument_run(self):
        refs = exec_refs("intro\n```bash\npytest -q tests/a.py tests/b.py\n```\n")
        assert [r.file for r in refs] == ["tests/a.py", "tests/b.py"], refs
        assert all(r.fence is not None and r.fence_start == 2 and r.lineno == 3 for r in refs)

    def test_exec_refs_ignores_a_fence_language_tag_and_a_commented_command(self):
        assert exec_refs("```python target=espalier/cli.py\nx = 1\n```\n") == []
        refs = exec_refs("```bash\n# python scripts/old.py   (retired)\npython scripts/new.py\n```\n")
        assert [r.file for r in refs] == ["scripts/new.py"], refs

    def test_exec_refs_marks_a_guarded_invocation_and_only_in_its_own_fence(self):
        text = (
            "```bash\nif [ -f scripts/x.py ]; then\n  python scripts/x.py\nfi\n```\n"
            "```bash\npython scripts/x.py\n```\n"
        )
        guarded = [r.guarded for r in exec_refs(text)]
        assert guarded == [True, False], guarded

    def test_exec_refs_does_not_read_a_shell_variable_as_a_path(self):
        assert exec_refs('```bash\npython "$CLAUDE_PROJECT_DIR/scripts/x.py"\n```\n') == []

    def test_exec_refs_reads_prose_without_a_fence(self):
        refs = exec_refs("Run `python scripts/x.py` first.\n")
        assert [(r.file, r.fence) for r in refs] == [("scripts/x.py", None)], refs

    def test_src_path_refs_reads_qualified_source_paths_only(self):
        text = (
            "`tests/test_hooks.py::TestX`, `docs/HOOKS.md`, `a/b/x.py`, "
            "`json.dump/pickle.dump`, `x.py`, `tools/cc/hooks/write_guard.py:42`\n"
        )
        assert src_path_refs(text) == ["tests/test_hooks.py", "tools/cc/hooks/write_guard.py"]

    def test_wikilink_refs_reads_prose_not_fences(self):
        assert wikilink_refs("[[a-b]] and `[[c]]`\n```\n[[not-this]]\n```\n") == ["a-b", "c"]

    def test_the_new_forms_report_on_a_synthetic_tree(self, tmp_path):
        """The reporting path of each arm, driven: on the real tree every
        finding is excused, so nothing there proves a Finding is produced."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "X.md").write_text(
            "See `scripts/nothing.py` and [[nothing-here]].\n"
            "```bash\npython scripts/nothing.py\n```\n",
            encoding="utf-8",
        )
        dead, _sections, totals = _derive(tmp_path)
        assert {(f.target, f.form) for f in dead} == {
            ("scripts/nothing.py", "src-path"),
            ("scripts/nothing.py", "exec"),
            ("[[nothing-here]]", "wikilink"),
        }, dead
        assert totals["src-path"] == totals["exec"] == totals["wikilink"] == 1


class TestNotDeployedNoteRecogniser:
    """The leg-c recogniser, pinned on the spellings the deployed set uses
    and on the attribution boundaries it must respect."""

    @pytest.mark.parametrize("line", [
        "`tools/cc/hooks/write_guard.py` is not deployed by `init`.",
        "`tools/cc/hooks/write_guard.py` (self-host only -- not deployed by `init`)",
        "`tools/cc/hooks/write_guard.py` -- Espalier source repo, not deployed by `init`",
        "`tools/cc/hooks/write_guard.py` is not deployed.",
    ])
    def test_a_note_beside_the_mention_is_read(self, line):
        assert _any_mention_says_not_deployed(line, "tools/cc/hooks/write_guard.py")

    @pytest.mark.parametrize("line", [
        "`a.md` (self-host only) and `tools/cc/hooks/write_guard.py`",
        "(`tools/cc/hooks/write_guard.py` -- plus, on the source repo only, `b.py`)",
        "`tools/cc/hooks/write_guard.py` and `b.py` (not deployed)",
    ])
    def test_a_note_belonging_to_a_neighbour_is_not_read(self, line):
        assert not _any_mention_says_not_deployed(line, "tools/cc/hooks/write_guard.py")

    def test_a_false_note_on_a_synthetic_tree_is_reported(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "HOOKS.md").write_text("# hooks\n", encoding="utf-8")
        (tmp_path / "docs" / "GUIDE.md").write_text(
            "See `docs/HOOKS.md` (self-host only -- not deployed by `init`).\n",
            encoding="utf-8",
        )
        found = _false_notes(tmp_path)
        assert [(f.carrier, f.target) for f in found] == [("docs/GUIDE.md", "docs/HOOKS.md")], found

    def test_a_true_note_on_a_synthetic_tree_is_silent(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "GUIDE.md").write_text(
            "See `docs/GONE.md` (self-host only -- not deployed by `init`).\n",
            encoding="utf-8",
        )
        assert _false_notes(tmp_path) == []


@pytest.fixture(scope="module")
def code_derived(adopter_tree):
    return _code_mentions(adopter_tree)


class TestCodeCarrierPointers:
    """DEF-503's arm: a pointer an adopter READS, in a file that is not `.md`."""

    def test_every_emitted_pointer_resolves(self, code_derived):
        dead, _totals = code_derived
        assert not dead, (
            f"{len(dead)} pointer(s) in adopter-visible harness OUTPUT name a "
            f"file that is absent from the adopter's tree:\n"
            + "\n".join(
                f"  {f.target:40s} <- {f.carrier}:{f.lineno}"
                for f in sorted(dead, key=lambda f: (f.target, f.carrier))
            )
            + "\n\nThese are strings the harness PRINTS -- a deny message, a "
            "CI failure, a banner line. The reader is looking at a terminal, "
            "so they cannot follow a link and cannot tell that the file was "
            "never deployed. Same three fixes as the markdown arm, same "
            "order: deploy the target (managed_inventory._SEED_DOC_REL_PATHS), "
            "or state the fact inline instead of naming a file they do not "
            "have. Do NOT reach for an exemption: this arm has none by "
            "construction, and a message nobody can act on is the defect."
        )

    def test_no_counter_is_dead(self, code_derived):
        """Every classifier must still be firing -- admits AND excludes.

        A zero admit-counter means the visibility rule broke and every emitted
        pointer is now invisible. A zero EXCLUDE-counter is the subtler one:
        it means an exclusion is dead, still reading like a considered
        decision while protecting nothing -- ``test_no_dead_exemptions``'s
        logic applied to DERIVED rules instead of declared rows. That is the
        check that would have caught ``advise``, a verb in the first draft's
        emit set with zero definitions and zero call sites in the deployed
        corpus: coverage-shaped, covering nothing.

        Realistic zeroing edits, so nobody reads a red here as mysterious:
        routing the ``post_write_check`` autoprune messages through one
        ``_report()`` helper, or moving the ``session_start`` renderer returns
        into a module-level template dict -- a pattern that file already uses
        twice.
        """
        _dead, totals = code_derived
        dead_counters = [name for name, count in totals.items() if count == 0]
        assert not dead_counters, (
            f"counter(s) at zero: {dead_counters}. Either the derivation "
            f"stopped looking (an admit counter) or an exclusion is now dead "
            f"weight (an excl- counter). Fix the rule; do not accept the "
            f"green -- a silent zero here reads as 'nothing dangling'."
        )

    def test_the_reachability_rule_still_discriminates(self, code_derived):
        """A guard on the DISCRIMINATOR, not just on the population.

        If ``visible`` ever equals ``mention``, the rule has collapsed to "any
        string constant" and every docstring and path literal is about to be
        reported as a dead pointer -- the noise state that gets a gate
        switched off (§C19). Both bounds matter, so both are asserted.
        """
        _dead, totals = code_derived
        assert 0 < totals["visible"] < totals["mention"], (
            f"visible={totals['visible']} of mention={totals['mention']}. "
            f"Zero means the reachability rule sees nothing; equal means it "
            f"discriminates nothing."
        )

    def test_the_cross_module_hop_is_live(self, code_derived):
        """The `_denial_reasons` shape, pinned.

        This repo splits deny CALLS from deny STRINGS by design
        (`tools/cc/hooks/_denial_reasons.py`, opening docstring), so a
        per-file lexical reachability rule cannot see a single hook deny
        message. The first draft of this arm could not, and review caught it.
        A zero here means the arm has regressed to that state: still green,
        still blind to the 31 templates it exists to read.
        """
        _dead, totals = code_derived
        assert totals["x-module-ref"] > 0, (
            "no constant was reached through a cross-module reference. The "
            "resolution in `_reachable_constants` has stopped working, and "
            "`_denial_reasons.py`'s templates are invisible again."
        )

    def test_every_emit_verb_is_live(self, adopter_tree):
        """No phantom verbs in ``_EMITTING_CALLS``.

        A verb nobody calls is a hand-maintained set pretending to be a
        derived one (§C1) -- it reads as coverage of a surface it does not
        touch. Census the deployed corpus and require each verb to appear.
        """
        seen: set[str] = set()
        for path in deployed_python(adopter_tree):
            module = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(module):
                if isinstance(node, ast.Call):
                    name = _call_name(node)
                    if name in _EMITTING_CALLS:
                        seen.add(name)
        assert seen == set(_EMITTING_CALLS), (
            f"emit verb(s) with no call site in the deployed corpus: "
            f"{sorted(set(_EMITTING_CALLS) - seen)}. Remove them -- a verb "
            f"that matches nothing widens nothing while reading as though it "
            f"covers a surface."
        )

    def test_sync_face_rules_are_all_posttooluse(self, adopter_tree):
        """The gate is the EVENT, not the face -- pinned in the safe direction.

        `_reinject.py` explains its self-host gating as a property of
        ``face="sync"`` rules. It is really a property of ONE call site:
        `post_write_check._run_main` wraps `check("PostToolUse", ...)` in
        `is_self_host_repo`, and the other four callers -- in
        `write_guard`, `session_start` (twice), `task_router` and
        `context_reinject_failure` -- do not.

        `tests/test_reinject_sync.py` pins ``PostToolUse => sync``. This
        pins ``sync => PostToolUse``, which is the direction this arm's
        exclusion depends on. Without it, a `face="sync"` rule added on
        `PreToolUse` would fire on every adopter tool call while this gate
        excused its pointers as self-host-only -- DEF-503 reborn inside the
        module whose comment the first draft trusted.
        """
        reinject = next(
            p for p in deployed_python(adopter_tree) if p.name == "_reinject.py"
        )
        module = ast.parse(reinject.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for node in ast.walk(module):
            if not isinstance(node, ast.Call) or _call_name(node) != "ReinjectRule":
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            face, event, rid = (
                kwargs.get("face"), kwargs.get("event"), kwargs.get("id")
            )
            if not (isinstance(face, ast.Constant) and face.value == "sync"):
                continue
            if not (isinstance(event, ast.Constant) and event.value == "PostToolUse"):
                offenders.append(
                    getattr(rid, "value", f"<line {node.lineno}>")
                )
        assert not offenders, (
            f"face='sync' rule(s) not on PostToolUse: {offenders}. Only the "
            f"PostToolUse call site is wrapped in is_self_host_repo, so these "
            f"fire on adopter repos -- and this arm would wrongly excuse "
            f"their pointers as self-host-only."
        )


class TestCodeCarrierMatchers:
    """The two ways a code carrier differs from a markdown one.

    Both are design decisions that a later "simplification" would undo
    silently, so each is pinned with the case that motivated it.
    """

    def test_plain_path_ref_finds_an_unbackticked_pointer(self):
        """The DEF-503 spelling, verbatim.

        ``ci_guard.py`` prints this into a failing CI log. Backticks would be
        noise there, so it has none -- and the markdown arm's matcher, which
        requires them, cannot see it.
        """
        text = (
            "To allow, include 'HARNESS-UPDATE-APPROVED' in the HEAD commit "
            "message\nor in the PR title. See docs/INSTALL-CI.md for details."
        )
        assert plain_path_refs(text) == ["docs/INSTALL-CI.md"]
        assert bare_path_refs(text) == [], (
            "the backtick-required matcher must NOT see this -- if it does, "
            "the two matchers have collapsed and the markdown arm has "
            "inherited the code arm's noise."
        )

    def test_root_resolver_refuses_the_carrier_relative_candidate(self):
        """§10.11: a fallback may only relax a dimension the input left open.

        A hook at ``tools/cc/hooks/`` printing "see docs/FOO.md" means
        ``<repo>/docs/FOO.md``. ``resolve_on_tree`` would offer
        ``tools/cc/hooks/docs/FOO.md`` first and report the pointer resolved
        against a file the message never named. The code arm must not.
        """
        members = {"tools/cc/hooks/docs/FOO.md"}
        assert resolve_on_tree(members, "tools/cc/hooks/x.py", "docs/FOO.md") == (
            "tools/cc/hooks/docs/FOO.md"
        ), "guard premise changed: resolve_on_tree no longer tries carrier-relative"
        assert resolve_from_root(members, "docs/FOO.md") is None

    def test_root_resolver_keeps_the_guarded_basename_fallback(self):
        """Unqualified names still resolve; qualified ones still may not."""
        members = {"docs/FOO.md"}
        assert resolve_from_root(members, "FOO.md") == "docs/FOO.md"
        assert resolve_from_root(members, "espalier/assets/docs/FOO.md") is None

    def test_root_resolver_ignores_an_ambiguous_basename(self):
        """Two files of one name resolve to neither -- picking one would be a
        coin flip reported as a fact."""
        members = {"docs/FOO.md", "memory/FOO.md"}
        assert resolve_from_root(members, "FOO.md") is None


class TestAdopterTreeIsTheWholeArtifact:
    def test_install_ci_artifacts_are_on_the_tree(self, adopter_tree):
        """``init`` is half the artifact; ``ci_guard.py`` arrives via
        ``install-ci`` and carries the most-read deny message the harness
        emits. A tree without it passes the code arm by not reading it."""
        assert (adopter_tree / "tools" / "cc" / "ci_guard.py").is_file()
        assert (
            adopter_tree / ".github" / "workflows" / "harness-guard.yml"
        ).is_file()

    def test_deployed_python_excludes_the_fixtures_own_files(self, adopter_tree):
        """The population is what espalier deployed, not what is on disk.

        The fixture authors a demo package to make the tree a plausible
        foreign repo; those files are props. Deriving from the deploy
        inventories keeps them out, so a ``.md`` mention in a prop can never
        read as a harness defect.
        """
        rels = {p.relative_to(adopter_tree).as_posix() for p in deployed_python(adopter_tree)}
        assert "tools/cc/ci_guard.py" in rels
        assert "tools/cc/hooks/write_guard.py" in rels
        assert not [r for r in rels if r.startswith(("src/", "tests/"))], (
            f"fixture-authored files leaked into the population: {sorted(rels)}"
        )


class TestSeedDocsCarryNoPersonalAddress:
    """No seeded doc body may ship a bare email address into an adopter tree.

    ``docs/FAILURE_MODES.md`` shipped the maintainer's personal address for
    months inside a ``.mailmap`` decision paragraph, and ``espalier init`` seeded
    it into every adopter repository. No gate saw it: the pointer contracts
    resolve *paths*, the provenance census matches *build tags*, and neither
    vocabulary contains an address. The pointer resolved; the content should not
    have been there.

    SCOPE IS THE WHOLE POINT, and a repo-wide rule was measured and rejected: a
    security-contact file, a code-of-conduct file and package metadata all carry
    a contact address **on purpose**, so "no personal addresses" reds on correct
    content and gets switched off. This is scoped to the seed set — bodies whose
    purpose is a decision record or a guide, never contact — where the live
    false-positive rate is zero.

    Population is DERIVED from ``managed_inventory.get_seed_docs()`` and resolved
    through ``get_seed_asset_source()``, so (a) a new seed enrolls automatically
    and (b) the stub-bodied seeds are read as the ~1KB stubs an adopter actually
    receives rather than their multi-thousand-line self-host namesakes — reading
    the repo-relative path instead inflates this population several-fold.

    Calibrated 2026-08-14: 20 seeds, 0 hits after the scrub; the identical regex
    finds exactly 1 in the pre-fix shipped body, so the contract is proven to
    catch the defect it was written for rather than merely passing.
    """

    #: Deliberately naive. It is allowed to be, because the population excludes
    #: every body that legitimately carries contact details. An obfuscated form
    #: ("name at example dot com") is NOT claimed to be caught -- this pins the
    #: shape that actually shipped, not every conceivable spelling.
    _EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

    def _seed_bodies(self):
        from espalier import managed_inventory

        assets = Path(__file__).resolve().parent.parent / "espalier" / "assets"
        for rel in managed_inventory.get_seed_docs():
            yield rel, assets / managed_inventory.get_seed_asset_source(rel)

    def test_population_resolves_and_is_not_vacuous(self):
        """A population that walked nothing would pass the contract below."""
        pairs = list(self._seed_bodies())
        assert len(pairs) >= 10, (
            f"only {len(pairs)} seed docs enumerated -- get_seed_docs() has "
            "narrowed or the asset root moved; the address contract below would "
            "pass by scanning almost nothing."
        )
        missing = [rel for rel, path in pairs if not path.is_file()]
        assert not missing, (
            f"{missing} are declared seeds whose asset body does not resolve "
            "under espalier/assets/. Fix the resolution before trusting a clean "
            "scan -- an unresolvable body is silently not scanned."
        )

    def test_no_seed_doc_ships_an_email_address(self):
        offenders: list[tuple[str, str]] = []
        for rel, path in self._seed_bodies():
            if not path.is_file():
                continue  # reported by the vacuity guard above
            body = path.read_text(encoding="utf-8", errors="replace")
            for match in self._EMAIL.finditer(body):
                offenders.append((rel, match.group(0)))
        assert not offenders, (
            f"{offenders} -- a seeded doc body carries an email address, and "
            "`espalier init` writes these into third-party repositories. State "
            "the fact without the address, or point at a body whose PURPOSE is "
            "contact. Do not add an allowlist entry to silence this: the class "
            "is 'a personal address in a body whose purpose is not contact', "
            "and every member of this population is such a body by construction."
        )
