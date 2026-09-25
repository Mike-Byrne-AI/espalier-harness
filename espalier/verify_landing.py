"""Verify whether a pack's claimed files actually landed.

``espalier verify-landing <pack.md> [--repo .] [--json]`` parses a pack's
``## Files touched`` + ``## Pass criteria`` sections, extracts the backticked
path tokens (the same ``_looks_like_path`` heuristic the scope-check pre-flight
uses), and classifies each against the repository's git state:

    LANDED   — tracked in ``HEAD`` with no uncommitted change
    DRIFTED  — tracked in ``HEAD`` AND changed in the working tree vs ``HEAD``
    OWED     — not tracked in ``HEAD`` (the pack claims the file; it isn't there)

This is an **advisory** tool — it prints a table and exits 0; it does not gate;
it reads landing truth back from git. It is HEAD-only; a
``--check-working-tree`` mode (untracked-but-present) is a deliberate follow-up.

Zero ``tools/cc`` import (espalier-only), per the isolation rule.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from espalier.pack_manifest import _live_text, _looks_like_path, _section_body

LANDED = "LANDED"
DRIFTED = "DRIFTED"
OWED = "OWED"

# The pack sections whose backticked path tokens are the pack's file claims.
# "Files touched" / "Pass criteria" are the formal names; the alternates
# ("Surfaces to touch" / "Earn-the-red proofs") are the only other variants the
# existing corpus uses. Recognising them lets verify-landing work on the existing
# corpus rather than only on the formal layout. Tolerate a numbered heading
# (``## 7. Files touched``) and a trailing parenthetical (``(anticipated)``)
# the way ``pack_manifest.parse_affected_symbols`` does.
_CLAIM_SECTIONS = (
    "Files touched",
    "Surfaces to touch",
    "Pass criteria",
    "Earn-the-red proofs",
)


@dataclass(frozen=True)
class LandingEntry:
    """One claimed path and its landing classification."""

    path: str
    head_state: str  # "tracked" | "absent"
    status: str  # LANDED | DRIFTED | OWED


def _is_prose_token(token: str) -> bool:
    """True if a backticked token is prose/UI noise, not a real path claim.

    These pass ``_looks_like_path`` (they contain ``/`` or a known extension) but
    never denote a claimed repo file, so classifying them OWED manufactures
    false-OWED noise on nearly every pack:

      - an ellipsis placeholder: ``task-packs/TP-...``, ``espalier/assets/.../``
      - a slash-command / absolute ref: ``/scope-check``, ``/preflight``, ``/tmp``
        (a repo-relative claim never starts with ``/``)
      - a degenerate dots-and-slashes token with no name char: ``.//``, ``.///``

    Deliberately narrow + text-only: it rejects only structurally-impossible
    claims, so it never drops a real path. Bare basenames are NOT dropped here —
    they may be legit root-file claims; they are reconciled by basename in
    :func:`_resolve_matches` (via :func:`_classify_token`) against the git
    state instead.
    """
    if "..." in token:
        return True
    if token.startswith("/"):
        return True
    return not any(c.isalnum() for c in token)


def _extract_path_tokens(pack_text: str) -> list[str]:
    """Backticked tokens that look like paths, from the claim sections, deduped
    in first-seen order."""
    tokens: list[str] = []
    seen: set[str] = set()
    for header in _CLAIM_SECTIONS:
        body = _section_body(
            pack_text,
            rf"(?m)^#{{2,3}}\s+(?:\d+\.\s+)?{re.escape(header)}",
            # End at the next level-2 OR level-3 heading: a sibling `###`
            # subsection between a claim section and the next `##` would
            # otherwise bleed its path tokens into this section's extraction.
            # The claim sections hold tokens directly (under bold
            # `**Modified:**` labels), not under `###` subsections, so stopping
            # at `###` drops nothing real.
            r"^#{2,3}\s",
        )
        if body is None:
            continue
        # A `~~struck~~` claim is withdrawn, as it is for the pre-flight's
        # parsers (CONV-2): read as a claim it manufactured a fake OWED
        # blocker for a file the pack said it would no longer create.
        body = _live_text(body)
        # `[^`\n]+` (not `[^`]+`) so the match cannot span lines: a path token is
        # always single-line, and a multi-line capture would let a fenced code
        # block (```...```) shift the backtick pairing and silently swallow the
        # opening backtick of a real path token on a later line.
        for tok in re.findall(r"`([^`\n]+)`", body):
            tok = tok.strip()
            # A token with internal whitespace is a backticked command/phrase
            # (e.g. `grep -rL "State: LANDED" task-packs/Done/*.md`), not a path —
            # even though it may contain a '/'. Drop it before the path heuristic.
            if not tok or any(c.isspace() for c in tok):
                continue
            # Drop prose/UI noise that passes _looks_like_path but is not a claim
            # (ellipsis placeholders, slash-commands, dots-and-slashes).
            if _is_prose_token(tok):
                continue
            if tok not in seen and _looks_like_path(tok):
                seen.add(tok)
                tokens.append(tok)
    return tokens


def _resolve_matches(token: str, paths: set[str]) -> set[str]:
    """The members of ``paths`` a claimed path token resolves to.

    - exact equality (the common case);
    - a directory token (trailing ``/``) resolves to every path under it — packs
      legitimately claim ``tests/`` / ``scripts/``, and ``git ls-tree`` lists
      files, not directories, so a bare-equality check would always miss them;
    - a glob token (``*?[``) resolves to every fnmatched member (a pack may
      claim ``foo/*.md``);
    - a bare basename (no separator) resolves to every path with that basename —
      a pack writes `write_guard.py`, the tracked path is
      `tools/cc/hooks/write_guard.py`. A genuinely-new root file with no
      same-named tracked sibling resolves to nothing -> correctly OWED. Advisory
      tool: erring toward LANDED beats manufacturing a fake owed-blocker.
    """
    if token in paths:
        return {token}
    if token.endswith("/"):
        return {p for p in paths if p.startswith(token)}
    if any(ch in token for ch in "*?["):
        return {p for p in paths if fnmatch.fnmatch(p, token)}
    if "/" not in token:
        return {p for p in paths if p.rsplit("/", 1)[-1] == token}
    return set()


def _classify_token(token: str, tracked: set[str], modified: set[str]) -> LandingEntry:
    # HEAD-membership decides OWED first: a file can appear in `git diff HEAD`
    # while NOT being in HEAD (a staged-but-uncommitted *new* file). That is not
    # "drifted" (not landed at all) — it is OWED. So only a file that IS in HEAD
    # can be DRIFTED (in HEAD AND changed in the working tree) or LANDED.
    resolved = _resolve_matches(token, tracked)
    if not resolved:
        return LandingEntry(token, "absent", OWED)
    # DRIFTED only if one of the SPECIFIC tracked paths the token resolved to is
    # itself modified. Re-running `_resolve_matches(token, modified)` would report a
    # bare-basename token (`config.py`) as DRIFTED when an UNRELATED same-named
    # file (`scripts/config.py`) appeared in the diff while the resolved file
    # (`espalier/config.py`) was untouched. Intersecting the resolved tracked
    # paths with `modified` keys the drift to the right file.
    if resolved & modified:
        return LandingEntry(token, "tracked", DRIFTED)
    return LandingEntry(token, "tracked", LANDED)


def classify_against(
    pack_text: str, tracked: set[str], modified: set[str]
) -> list[LandingEntry]:
    """Pure classifier: classify a pack's claimed paths against explicit
    ``tracked`` (in HEAD) and ``modified`` (changed vs HEAD) path sets.

    Separated from git I/O so the classification is unit-testable without a
    repository fixture.
    """
    return [_classify_token(t, tracked, modified) for t in _extract_path_tokens(pack_text)]


def _git_lines(repo: Path, *args: str) -> list[str]:
    """Run ``git <args>`` in ``repo`` and return non-empty stdout lines, or
    ``[]`` on any git failure (advisory tool — never raise)."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            check=True,
            timeout=30,
        ).stdout
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired, ValueError):
        return []
    return [ln for ln in out.splitlines() if ln]


def classify_landing(pack_text: str, repo: Path) -> list[LandingEntry]:
    """Classify a pack's claimed paths against the git state of ``repo``."""
    tracked = set(_git_lines(repo, "ls-tree", "-r", "--name-only", "HEAD"))
    modified = set(_git_lines(repo, "diff", "--name-only", "HEAD"))
    return classify_against(pack_text, tracked, modified)


def render_table(entries: list[LandingEntry]) -> str:
    """Render the ``file | head-state | status`` table + a one-line summary."""
    if not entries:
        # Name ALL recognized claim sections, derived from the SoT tuple.
        sections = " / ".join(f"'## {header}'" for header in _CLAIM_SECTIONS)
        return f"No path tokens found in the pack's {sections} sections."
    width = max(len(e.path) for e in entries)
    width = max(width, len("FILE"))
    lines = [
        f"{'FILE':<{width}}  HEAD      STATUS",
        f"{'-' * width}  --------  -------",
    ]
    for e in entries:
        lines.append(f"{e.path:<{width}}  {e.head_state:<8}  {e.status}")
    counts = Counter(e.status for e in entries)
    lines.append("")
    lines.append(
        f"{counts.get(LANDED, 0)} landed | "
        f"{counts.get(DRIFTED, 0)} drifted | "
        f"{counts.get(OWED, 0)} owed"
    )
    return "\n".join(lines)
