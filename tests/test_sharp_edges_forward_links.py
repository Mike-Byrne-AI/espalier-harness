"""Every ``docs/sharp-edges/*.md`` (except ``README.md``) must be forward-linked
from ``docs/SHARP_EDGES.md`` — otherwise the footgun is reachable only if you
already know its filename, defeating the index monolith a developer browses.

Earn-the-red (TP-308-B): against HEAD this failed on exactly eight files that
carried the off-convention ``**Linked from:** ESPALIER_MEMORY.md row "…"`` form and had no
``## `` stub in the index. The fix repointed their ``Linked from:`` lines to the
``docs/SHARP_EDGES.md section "<heading>"`` convention and added the matching
forward-link stubs; this guard keeps every future sharp-edge index-linked.

The convention is ``docs/sharp-edges/README.md`` "Required structure":
``**Linked from:** docs/SHARP_EDGES.md section "<exact heading>"``. The population
is 0-false-positive: every non-``README.md`` sibling is expected to be linked, so
a new sharp-edge that is intentionally *not* index-linked declares its exemption
here (in this test), not silently.
"""
from __future__ import annotations

# pytest-marker: default-unit
#   A fast, stdlib-only docs-structure guard. Classified via the default-unit
#   fallthrough (not added to conftest._MARKER_RULES) so it does not grow the
#   frozen "unit" grandfather tuple, which test_sister_site_probe_ceilings pins
#   to chip down, never up.
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SHARP_EDGES = REPO_ROOT / "docs" / "SHARP_EDGES.md"
_SHARP_EDGES_DIR = REPO_ROOT / "docs" / "sharp-edges"


def _unlinked_sharp_edges() -> list[str]:
    """Names of sharp-edge docs with no forward link in the index monolith."""
    index = _SHARP_EDGES.read_text(encoding="utf-8")
    missing: list[str] = []
    for p in sorted(_SHARP_EDGES_DIR.glob("*.md")):
        if p.name == "README.md":
            continue
        # The `See [sharp-edges/<name>.md](sharp-edges/<name>.md)` stub — any
        # occurrence of the relative path is a forward link.
        if f"sharp-edges/{p.name}" not in index:
            missing.append(p.name)
    return missing


def test_every_sharp_edge_is_forward_linked_from_the_index():
    missing = _unlinked_sharp_edges()
    assert not missing, (
        "docs/SHARP_EDGES.md does not forward-link these sharp-edges files, so "
        "they are undiscoverable from the index monolith:\n  "
        + "\n  ".join(missing)
        + "\nAdd a `## <heading>` stub with a "
        "`See [sharp-edges/<name>.md](sharp-edges/<name>.md)` link "
        "(docs/sharp-edges/README.md 'Required structure')."
    )
