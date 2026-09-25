"""Mechanical claim extractor for accuracy auditing.

Walks a configured set of doc globs and emits `Claim` objects keyed by
file:line. Pattern-driven; no LLM. The orchestrator (`audit_accuracy.py`)
dispatches each claim to either the mechanical verifier (live repo) or
the LLM-dispatch path (pinned external excerpt).

Why mechanical extraction first: deciding which sentences are claims is
not an LLM task. If we let the model pick claims, scope drifts and the
audit becomes "review the docs," not "verify documented facts." Regex
gives us a deterministic, tunable surface.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Operator-facing docs that pin facts about the current state. These are
# the surfaces an audit verifies. CHANGELOG.md and ESPALIER_MEMORY.md are
# *historical narratives* (release-by-release and session-by-session
# logs); the numbers in those files describe past state and shouldn't be
# audited against current state. Likewise, docs/external/ holds the
# verification targets, not claims (excluded via EXCLUDED_DOC_GLOBS).
DEFAULT_DOC_GLOBS: tuple[str, ...] = (
    "README.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "docs/*.md",
    ".claude/agents/*.md",
    ".claude/commands/*.md",
    ".claude/skills/*/SKILL.md",
)

# Globs whose matches are *verification targets* or *historical
# narratives*, not claims. Pinned external excerpts under
# docs/external/ are the source of truth — we don't extract claims
# from them. docs/session-archive.md is the pruned overflow tank for
# ESPALIER_MEMORY.md (same release-by-release / session-by-session narrative
# shape that already excludes ESPALIER_MEMORY.md and CHANGELOG.md from
# DEFAULT_DOC_GLOBS): its numbers describe past state and shouldn't
# be audited against the current surface.
# sister-site: ok purpose-scoped: don't-AUDIT-as-claim globs, not surface_contract._INTERNAL_FILENAME_PATTERNS (don't-SHIP)
EXCLUDED_DOC_GLOBS: tuple[str, ...] = (
    "docs/external/*.md",
    "docs/session-archive.md",
    # docs/FAILURE_MODES.md is a failure-mode CATALOG: its "Concrete repo
    # example" entries quote point-in-time counts (e.g. an old README
    # claiming "45 bypass classes") that are historically accurate but drift
    # from the live surface by design. Same narrative-snapshot shape as
    # session-archive / CHANGELOG -- audit current-state surfaces, not the
    # historical examples a failure-mode catalog exists to record.
    "docs/FAILURE_MODES.md",
    # docs/RELEASE_FINDINGS_LEDGER.md is the finding->commit ledger:
    # point-in-time narrative (commit hashes, "still a13", per-review counts) that
    # is historically accurate but drifts from the live surface by design -- same
    # snapshot shape as session-archive above. Classified `internal` in
    # surface_contract (never ships); excluded here so audit_accuracy does not
    # extract claims from it.
    "docs/RELEASE_FINDINGS_LEDGER.md",
    # docs/REDEFINED_INFORMATION_REGISTRY.md is the SoT-redefinition registry:
    # internal-narrative (classified `internal` + export-ignored + MANIFEST-
    # excluded, never ships to adopters) whose cells cite point-in-time roster
    # counts that are SoT-pinned elsewhere (NumericContract). Same internal /
    # non-shipped class as the ledger above; excluded so a
    # future roster change does not false-fail the public-doc audit here while the
    # real binding lives in tests/test_documented_claims.py.
    "docs/REDEFINED_INFORMATION_REGISTRY.md",
    # docs/RELEASE_DECISIONS.md is the chronological release-decision log: each
    # entry locks a past choice and cites the counts that were true when it was
    # made ("42 lightweight local tags", "the 8 version markers"). Same
    # point-in-time narrative shape as the ledger above -- auditing those as live
    # claims is the category error this partition exists to name.
    #
    # Its twin docs/RELEASE_CHECKLIST.md is DELIBERATELY ABSENT from this tuple.
    # Both were classified `internal` together on 2026-08-13, so the symmetry is
    # tempting and wrong: the checklist is a PROCEDURE someone executes, not a
    # record of one. Its counts describe the surface as it must be TODAY, so they
    # must keep drifting-red -- it stays in surface_contract._PUBLIC_DOC_RELPATHS
    # (AUDITED) and leaves only the derived INDEXED set. Not shipping a doc is
    # not a reason to stop checking it.
    "docs/RELEASE_DECISIONS.md",
)

# Docs that classify `internal` (they ship nowhere) yet are DELIBERATELY still
# audited. Declared as a constant rather than left as a comment because the
# asymmetry is the fragile part: adding a member here to EXCLUDED_DOC_GLOBS is
# the obvious "fix the inconsistency" edit, and before this tuple existed that
# edit was fully green -- it silently stopped auditing a live procedure. Bound by
# tests/test_doc_maintenance_classes.py::test_deliberately_audited_docs_stay_audited.
#
# docs/RELEASE_CHECKLIST.md is one because it is a PROCEDURE someone executes,
# while its twin docs/RELEASE_DECISIONS.md is a RECORD of past choices. Same
# commit, opposite answers, and the distinction is the reason -- not the
# file-name symmetry.
#
# MEASURED, 2026-08-13, so the rationale is not overclaimed: extract_claims()
# yields **0** claims on RELEASE_CHECKLIST today (peers yield 1-6), so membership
# is NOT currently buying count-drift detection. What it does buy, now, is two
# phrase sweeps that walk get_public_doc_relpaths():
# tests/test_surface_support_matrix.py (overclaim phrasing) and
# tests/test_documented_claims.py (forbidden SessionStart phrasing) -- plus the
# count channel arming itself the moment someone writes a count into the file.
# Defend the membership on those, not on drift that measures zero.
AUDITED_INTERNAL_DOCS: tuple[str, ...] = (
    "docs/RELEASE_CHECKLIST.md",
)

# Partition of the *exact-path* entries of EXCLUDED_DOC_GLOBS by WHY each doc is
# audit-excluded, so a future exclusion must declare its class (enforced by
# tests/test_doc_maintenance_classes.py). A LIVE_STATE_MAP makes current-state source
# citations and is guarded by tests/test_doc_source_citations.py. A FROZEN_RECORD_DOC is
# an append-only log/catalog whose point-in-time content is correct-by-design and must
# NOT be rewritten to chase renames. docs/external/*.md is a third class (externally
# pinned; own freshness manifest) -- a glob, deliberately outside this partition.
LIVE_STATE_MAPS: tuple[str, ...] = (
    "docs/REDEFINED_INFORMATION_REGISTRY.md",
)
FROZEN_RECORD_DOCS: tuple[str, ...] = (
    "docs/session-archive.md",
    "docs/FAILURE_MODES.md",
    "docs/RELEASE_FINDINGS_LEDGER.md",
    "docs/RELEASE_DECISIONS.md",
)

# ── The record/claim axis ───────────────────────────────────────────────────
# One question, previously answered in five places and never in one: does this
# document assert what is true NOW -- a CLAIM surface, where a pointer that stops
# resolving is rot and should be fixed -- or what was true THEN -- a RECORD,
# where the same broken pointer is expected aging and "correcting" it falsifies
# the log? Root CLAUDE.md Core Rule 13 turns entirely on that answer.
#
# Before this constant, a guard needing the answer reached for whichever
# adjacent exclusion list it happened to import, and those lists are NOT
# interchangeable -- they answer five different questions that merely overlap.
# FROZEN_RECORD_DOCS above is the sharpest example: it is a PARTITION of
# EXCLUDED_DOC_GLOBS's exact-path entries (bound by
# tests/test_doc_maintenance_classes.py), so it structurally cannot hold a
# document that is not audit-excluded by path. ESPALIER_MEMORY.md -- a record on
# any reading -- was therefore named by no registry at all, and a guard that
# imported the nearest one silently ran over a population excluding its subject
# (docs/FAILURE_MODES.md 13.28; measured on tests/test_required_status_checks.py,
# 2026-08-13).
#
# This is the axis and ONLY the axis. It replaces nothing: each purpose-scoped
# list keeps its own membership and its own reasons, and consults this for the
# record question alone. Reconciliation is pinned by
# tests/test_record_axis_reconciliation.py.
#
# Note what is deliberately ABSENT: docs/REDEFINED_INFORMATION_REGISTRY.md is
# audit-excluded and is NOT a record -- LIVE_STATE_MAPS classifies it as making
# current-state citations, so its pointers must keep drifting red.
RECORD_SURFACES: dict[str, str] = {
    "ESPALIER_MEMORY.md":
        "session-by-session narrative; its numbers describe past state",
    "CHANGELOG.md":
        "release-by-release narrative; entries stay correct as history once "
        "the value moves",
    "docs/session-archive.md":
        "pruned overflow tank for ESPALIER_MEMORY.md; same narrative shape",
    "docs/FAILURE_MODES.md":
        "failure-mode catalog; its concrete examples quote point-in-time counts "
        "that are historically accurate and drift by design",
    "docs/RELEASE_FINDINGS_LEDGER.md":
        "finding-to-commit ledger; commit hashes and per-review counts",
    "docs/RELEASE_DECISIONS.md":
        "chronological decision log; each entry locks the counts that were true "
        "when the choice was made",
    "memory/CONVERGENCE_LEDGER.md":
        "appended once per convergence round by the convergence-critic",
}

# Class tokens for registries whose members are exempt for MIXED reasons. Keying
# a reconciliation on prose lets a reword silently change a classification; these
# make the class mechanical. RECORD members must appear in RECORD_SURFACES above.
RECORD = "record"
MIRROR = "mirror"
OUT_OF_DOMAIN = "out-of-domain"

MODE_LIVE_REPO = "live_repo"
MODE_EXTERNAL_PIN = "external_pin"
MODE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Claim:
    """A claim-shaped sentence extracted from a project doc."""

    claim_id: str
    location: str  # "<rel-path>:<line>"
    text: str
    pattern: str
    suggested_mode: str


# Each pattern is (regex, mode, name). Order matters only for the `pattern`
# label assigned to each Claim — first match wins for labelling.
# Negative lookbehind `(?<!\.)` blocks the regex from matching a digit
# that follows a literal period — without it, headings like "### 2.6 Test
# pollution" extract "6 Test" because `\b` sits between `.` (non-word) and
# `6` (word). Same shape was at risk for num_hooks / num_bypass_classes.
#
# Every num_* pattern uses the strict bare-noun `(?<!\.)\b\d+\s+<noun>` form
# with NO `(?:[a-z]+\s+)?` adjective slot. Against this repo's doc corpus the
# slot matched a preposition or noun modifier ("chmod 444 on hook files" -> 444
# hooks; "116 contract test"; "Set chmod 444 on agent files" -> 444 agents),
# turning a low-harm false negative into a higher-harm false positive — the
# agents/commands/skills slot reproduced an end-to-end VERDICT_FAIL on
# "chmod 444 on agent files". False positives are the high-severity class.
# Recall for adjective-phrased roster claims ("7 governance agents", "22 slash
# commands") lives in tests/test_count_claims.py via make_count_claim_regex,
# which gates those mechanically without exposing this runtime auditor to the
# false-positive class.
_NUM_HOOKS = re.compile(r"(?<!\.)\b\d+\s+hooks?\b", re.IGNORECASE)
_NUM_TESTS = re.compile(r"(?<!\.)\b\d+,?\d*\s+tests?\b", re.IGNORECASE)
_NUM_BYPASS_CLASSES = re.compile(
    r"(?<!\.)\b\d+\s+(?:documented\s+)?bypass\s+classes?\b", re.IGNORECASE
)
_NUM_AGENTS = re.compile(r"(?<!\.)\b\d+\s+agents?\b", re.IGNORECASE)
_NUM_COMMANDS = re.compile(r"(?<!\.)\b\d+\s+commands?\b", re.IGNORECASE)
_NUM_SKILLS = re.compile(r"(?<!\.)\b\d+\s+skills?\b", re.IGNORECASE)
_EXIT_CODE_NEAR_HOOK = re.compile(
    r"\bexit\s+\d.{0,80}\b(?:hook|protocol|stdout|stderr)\b", re.IGNORECASE
)
_HOOK_NEAR_EXIT_CODE = re.compile(
    r"\b(?:hook|protocol|stdout|stderr)\b.{0,80}\bexit\s+\d", re.IGNORECASE
)
_PROTOCOL_SCHEMA = re.compile(
    r"\b(?:permissionDecision(?:Reason)?|hookSpecificOutput|hookEventName)\b"
)
_CLAUDE_CODE_PROTOCOL = re.compile(
    r"\bClaude Code\b.{0,120}\b(?:hook|protocol|exit code|stdout|stderr|JSON)\b",
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (_NUM_HOOKS, MODE_LIVE_REPO, "num_hooks"),
    (_NUM_TESTS, MODE_LIVE_REPO, "num_tests"),
    (_NUM_BYPASS_CLASSES, MODE_LIVE_REPO, "num_bypass_classes"),
    (_NUM_AGENTS, MODE_LIVE_REPO, "num_agents"),
    (_NUM_COMMANDS, MODE_LIVE_REPO, "num_commands"),
    (_NUM_SKILLS, MODE_LIVE_REPO, "num_skills"),
    (_EXIT_CODE_NEAR_HOOK, MODE_EXTERNAL_PIN, "exit_code_near_hook"),
    (_HOOK_NEAR_EXIT_CODE, MODE_EXTERNAL_PIN, "hook_near_exit_code"),
    (_PROTOCOL_SCHEMA, MODE_EXTERNAL_PIN, "protocol_schema"),
    (_CLAUDE_CODE_PROTOCOL, MODE_EXTERNAL_PIN, "claude_code_protocol"),
)

# Lines containing these markers are skipped — they're code blocks /
# instructions / examples, not claims. Reduces noise.
_SKIP_LINE_MARKERS: tuple[str, ...] = (
    "```",
    "<!--",
    "-->",
    "per minute",
    "per second",
    "concurrent",
)

# Lines that talk about counts as a *range* (e.g. "3-6 agents",
# "10-15 commands") are meta-guidance about count discipline, not pinned
# claims about the live surface. The agent docs and design skill use
# this shape extensively.
_RANGE_RE = re.compile(r"\b\d+\s*[\u2013\u2014\-]\s*\d+\s+\w+")


def _claim_id(rel_path: str, line: int, text: str) -> str:
    h = hashlib.sha256(f"{rel_path}:{line}:{text[:64]}".encode("utf-8")).hexdigest()
    return h[:12]


def _is_skippable(line_text: str) -> bool:
    # Markdown blockquote lines starting with ">" are typically quoted
    # examples, sample-output, or paraphrased doc text, not pinned claims.
    # The audit-accuracy slash command itself contains example wording
    # like "Change CLAUDE.md:42 from 8 hooks to 9 hooks" — those are not
    # claims this repo makes, just example output the operator might see.
    if line_text.lstrip().startswith(">"):
        return True
    lower = line_text.lower()
    if any(marker in lower for marker in _SKIP_LINE_MARKERS):
        return True
    return False


def _mask_ranges(line_text: str) -> str:
    """Blank out range tokens like '3-6 agents' so the count regexes
    don't match them, while leaving legitimate counts elsewhere on the
    line intact. Replaces only the range substring, not the whole line.
    """
    return _RANGE_RE.sub("", line_text)


def _classify_all(line_text: str) -> list[tuple[str, str]]:
    """Return the (suggested_mode, pattern_name) claims for a line.

    Emits one claim per matching noun on the line so a line stating multiple
    counts (e.g. "8 agents, 15 commands, 10 skills") has each count audited
    rather than only the first match.

    Multi-emission is scoped to the label-anchored ``MODE_LIVE_REPO`` (num_*)
    patterns ONLY: each noun anchors to a distinct count, so
    audit_accuracy.extract_count_for_label pins each number to its own noun
    and emitting one claim per noun carries no false-positive risk. The
    ``MODE_EXTERNAL_PIN`` protocol patterns are NOT label-anchored and several
    overlap on one line (e.g. the symmetric ``exit_code_near_hook`` /
    ``hook_near_exit_code`` pair), so they keep first-match-wins — multi-emitting
    them would just produce redundant ``unverifiable`` verdicts for one line.
    """
    live: list[tuple[str, str]] = []
    pins: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pattern, mode, name in _PATTERNS:
        if pattern.search(line_text):
            key = (mode, name)
            if key in seen:
                continue
            seen.add(key)
            (live if mode == MODE_LIVE_REPO else pins).append(key)
    # All num_* counts on the line, else the single first protocol match.
    if live:
        return live
    return pins[:1]


def _enumerate_files(repo_root: Path,
                     doc_globs: Iterable[str],
                     excluded: Iterable[str] = EXCLUDED_DOC_GLOBS) -> list[Path]:
    """Resolve doc_globs to concrete files, with exclusion."""
    excluded_paths: set[Path] = set()
    for ex in excluded:
        excluded_paths.update(repo_root.glob(ex))
    out: list[Path] = []
    seen: set[Path] = set()
    for pattern in doc_globs:
        for path in repo_root.glob(pattern):
            if not path.is_file():
                continue
            if path in excluded_paths:
                continue
            if path in seen:
                continue
            seen.add(path)
            out.append(path)
    return sorted(out)


def extract_claims(
    repo_root: Path,
    doc_globs: list[str] | None = None,
) -> list[Claim]:
    """Walk doc files and extract claim-shaped sentences."""
    repo_root = repo_root.resolve()
    globs = tuple(doc_globs) if doc_globs is not None else DEFAULT_DOC_GLOBS
    files = _enumerate_files(repo_root, globs)
    claims: list[Claim] = []
    for path in files:
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        in_code_block = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Recognize tilde fences (~~~) as well as backtick
            # fences, matching the freshness scanner's toggle — numeric/protocol
            # claims inside a ~~~ block must not be extracted.
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                continue
            if in_code_block or _is_skippable(stripped):
                continue
            if not stripped:
                continue
            # Blank out range tokens before pattern matching so
            # "3-5 scenarios but exactly 9 hooks" still emits the
            # legitimate `9 hooks` claim.
            scan_target = _mask_ranges(stripped)
            # Emit one claim per matching noun on the line, not
            # just the first — a combined "8 agents, 15 commands, 10 skills"
            # line must audit all three counts.
            for mode, name in _classify_all(scan_target):
                claims.append(
                    Claim(
                        claim_id=_claim_id(rel, lineno, stripped),
                        location=f"{rel}:{lineno}",
                        text=stripped,
                        pattern=name,
                        suggested_mode=mode,
                    )
                )
    return claims
