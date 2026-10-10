"""Write a stand-in for a file the harness deploys, carrying the managed marker.

A doctor fixture that models deployed surface by hand -- one ``cc/`` doc, one
hook script left behind -- must write it the way a deploy does: MARKED. Since
TP-474 2-C (2026-10-10) an unmarked file under a harness-owned root is the
adopter's and not deployed surface, so doctor reads a tree whose only harness
files are unmarked as uninstalled; a fixture written unmarked then turns its
test's sub-check assertions vacuous rather than red. Measured on a real init +
install-ci tree: the only unmarked files under the owned roots are the goal
snapshot (runtime state), install-ci's ``tools/cc/ci_guard.py`` (unmarked by
design) and ``.claude/settings.json`` (the adopter's). Model one of THOSE by
writing it plain, on purpose, and say so beside the write.
"""
from __future__ import annotations

from pathlib import Path

from espalier.managed_markers import apply_marker_to_md, apply_marker_to_text


def write_deployed(path: Path, text: str) -> Path:
    """Write ``text`` at ``path`` with the managed marker a deploy would add:
    the HTML comment form for Markdown, the hash comment form otherwise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    marked = apply_marker_to_md(text) if path.suffix == ".md" else apply_marker_to_text(text)
    path.write_text(marked, encoding="utf-8")
    return path
