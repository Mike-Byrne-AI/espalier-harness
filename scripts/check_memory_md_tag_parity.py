#!/usr/bin/env python3
"""CI gate: every released ``v*`` git tag must be mentioned in either
``ESPALIER_MEMORY.md`` (Session Log) or ``CHANGELOG.md`` (every version cut
earns a ``[X.Y.Z]`` section + footer-link row).

Without this gate a tag can be cut before its ESPALIER_MEMORY.md Session Log
row lands, leaving a permanent narrative gap in the tagged tree that
is hard to detect.

The dual-corpus design — ESPALIER_MEMORY.md + CHANGELOG.md — matches the
repo's existing tracked-doc surface. ``docs/session-archive.md`` is
gitignored (per-developer state) and not available in CI checkouts;
CHANGELOG.md is the canonical tracked record of every released
version, with both a section heading and a footer-link line per
tag, so checking it covers historical tags pruned out of ESPALIER_MEMORY.md.

Behavior:
- ``git tag --list 'v*'`` enumerates the tag set.
- ``ESPALIER_MEMORY.md`` and ``CHANGELOG.md`` are read as text and searched
  for each tag string.
- Exit 0 if every tag is mentioned in either file; exit 1 with the
  list of missing tags otherwise.

The script reads the **live files at HEAD**, not the tagged-tree
copies. The contract is "the tag appears in ESPALIER_MEMORY.md or CHANGELOG.md
by PR-time" — typically because the version-bump commit added the
row and the CHANGELOG section in the same diff as the bump. The
recovery path is a follow-up ``chore(release):`` patch commit that
closes the gap retroactively.

Stdlib-only. No espalier imports.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def list_release_tags() -> list[str]:
    """Return git tag names starting with ``v``. Empty list on git
    failure — that lets the script no-op cleanly in shallow clones or
    detached states rather than fail spuriously."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            cwd=REPO_ROOT,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return []
    return [t.strip() for t in result.stdout.splitlines() if t.strip().startswith("v")]


def memory_log_text() -> str:
    memory = REPO_ROOT / "ESPALIER_MEMORY.md"
    if not memory.is_file():
        return ""
    return memory.read_text(encoding="utf-8")


def changelog_text() -> str:
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        return ""
    return changelog.read_text(encoding="utf-8")


def _mentions_tag(corpus: str, tag: str) -> bool:
    """True iff ``tag`` appears NOT immediately followed by a version-continuing
    char — so ``v0.9.0`` does not count as mentioned by a ``v0.9.0a1`` row, and
    ``v0.9.0.1`` does not satisfy ``v0.9.0``, while a trailing sentence period
    (``…v0.9.0.``) still counts as a mention.
    Closes the substring-forgeability hole a bare ``in`` would leave open."""
    return re.search(re.escape(tag) + r"(?![0-9A-Za-z])(?!\.[0-9A-Za-z])", corpus) is not None


def missing_tag_rows(tags: list[str], memory_text: str, changelog_corpus: str = "") -> list[str]:
    """Return tags that are NOT mentioned in either body of text.

    The dual-corpus lookup uses ESPALIER_MEMORY.md (recent rows) +
    CHANGELOG.md (every released version's section + footer link).
    A tag mentioned in either file is "documented." Matching uses a
    trailing-boundary anchor (see ``_mentions_tag``) so a tag that is a
    prefix of a longer version string is not silently satisfied.
    """
    return [
        t for t in tags
        if not _mentions_tag(memory_text, t) and not _mentions_tag(changelog_corpus, t)
    ]


def main() -> int:
    tags = list_release_tags()
    if not tags:
        # No tags (fresh clone, shallow CI fetch) -> nothing to check.
        return 0
    memory_text = memory_log_text()
    cl_text = changelog_text()
    missing = missing_tag_rows(tags, memory_text, cl_text)
    if missing:
        print(
            "tag(s) not mentioned in ESPALIER_MEMORY.md "
            f"Session Log or CHANGELOG.md: {missing}. Add a row in "
            "ESPALIER_MEMORY.md before tagging, fold the version section into "
            "CHANGELOG.md, or recover via a `chore(release): ESPALIER_MEMORY.md "
            "row for ...` commit. CHANGELOG.md tracks every released "
            "version structurally; ESPALIER_MEMORY.md tracks recent narrative.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
