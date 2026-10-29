"""Shared hygiene predicates for adopter-facing shipped bodies (SoT).

Consumed by ``tests/test_init_tier_split.py`` (the full-suite
``TestCommonTierAssetHygiene`` contract) AND ``espalier surface-impact``
(the pre-flight content scan), so the pre-flight and the shipped-surface
contract cannot drift on what counts as an internal-ID or self-host-vocab
leak — one oracle, two callers.

Two data objects are the source of truth:

- :data:`SPECIFIC_ID_RE` — a digit-bearing ``TP`` / ``TASK_PACK`` / ``BC``
  pack identifier. Generic placeholders that carry no digit (``TP-NN``,
  ``BC-NNN``) are documentation vocabulary and are deliberately NOT
  matched — only IDs with an embedded digit trip the contract.
- :data:`FORBIDDEN_SELF_HOST_PATTERNS` — ``(label, pattern)`` pairs for
  prose that frames the harness as the adopter's own development target
  rather than a tool they installed.

The two ``*_hits`` helpers are the convenience surface the pre-flight
calls (whole-text scan, returns the offending strings/labels). The
full-suite contract keeps its own richer line-by-line + wrapped-text
scan for line-number reporting, but sources these same patterns.

A third object asks a wider question -- who the text is addressed to:
:data:`MAINTAINER_MARKER_PATTERNS` and :func:`maintainer_marker_hits`, read by
``tests/test_deployed_text_audience.py`` over everything ``init`` deploys and
by ``espalier surface-impact`` on the self-host tree.

A fourth is the seeded docs' walk: :data:`SEED_ROOTS`, :data:`SEED_TEXT_SUFFIXES`,
:data:`SEED_BASELINE` and :func:`seeded_marker_hits`, read by that gate (over
git's view of the checkout) and by ``scripts/sync_asset_docs.py`` after every
copy, so the fold into a seeded doc is judged where it is written and the two
readers cannot hold different roots or ceilings.

Stdlib-only by contract: importable from both ``espalier/`` and the test
tree without pulling a third-party dependency into the pre-flight path.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

# Specific IDs contain at least one digit (a real pack number). Generic
# placeholders without a digit (``TP-NN``, ``BC-NNN``) are explicitly
# allowed as documentation vocabulary and must not match.
SPECIFIC_ID_RE = re.compile(
    r"\b(?:TP|TASK_PACK|BC)-[A-Z0-9_-]*\d[A-Z0-9_-]*\b",
)

# Forbidden self-host vocabulary in common-tier asset bodies. The
# specific-ID sweep above catches digit-bearing pack-ID leaks; this
# catches the prose that survives because it carries no embedded digit:
#
#  - "Self-host meaning:" -- review-pass narrative that frames each
#    pattern through the harness's own development experience.
#  - "THIS harness" / "this harness's own" -- emphatic self-reference
#    that reads as "the harness you just installed" rather than "the
#    source repo we extracted examples from."
#  - an "R" + one-or-two digits adjacent to "round" / "review" --
#    references to internal review iterations adopters never saw.
FORBIDDEN_SELF_HOST_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("Self-host meaning:", re.compile(r"Self-host meaning:", re.IGNORECASE)),
    ("THIS harness", re.compile(r"\bTHIS\s+harness\b")),
    ("this harness's own", re.compile(r"this\s+harness'?s\s+own", re.IGNORECASE)),
    # Catch the plain lowercase "this harness" variant that the
    # uppercase-emphatic and possessive patterns above miss. Order
    # matters: this entry sits AFTER the more-specific "this harness's
    # own" so error messages report the more-specific label when both
    # match.
    ("this harness", re.compile(r"\bthis\s+harness\b", re.IGNORECASE)),
    # A deployed body that names the harness's own repository as the thing under
    # review reads as the adopter's: a workflow scope default did exactly that.
    ("project name as the reviewed repo", re.compile(r"Espalier-Harness repo")),
    (
        "R-NNN review-round ref",
        re.compile(r"\bR\d{1,2}\b(?=[^.]{0,80}\b(?:round|review)\b)", re.IGNORECASE),
    ),
)


def internal_id_hits(text: str) -> list[str]:
    """Return the specific (digit-bearing) internal pack IDs in ``text``.

    De-duplicated and sorted so a caller printing the hits gets a stable
    order. An empty list means clean.
    """
    return sorted(set(SPECIFIC_ID_RE.findall(text)))


def self_host_vocab_hits(text: str) -> list[str]:
    """Return the labels of forbidden self-host-vocab patterns in ``text``.

    Whole-text scan — the pre-flight's cheap check. The full-suite
    contract additionally reports line numbers and catches phrases that
    wrap across a line break; that richer scan stays in the test.
    """
    return [label for label, pat in FORBIDDEN_SELF_HOST_PATTERNS if pat.search(text)]


#: The trailing label that marks a line in a deployed body as this repository's
#: own example, kept on purpose: the proof line itself
#: (``pytest -q   # Espalier-Harness tree: the full suite``) or the comment that
#: quotes it (``# Espalier-Harness tree: pytest tests/test_x.py -q``). Its readers
#: import it rather than spell it: the portability contract over the deployed
#: bodies (``tests/test_portability_contract.py``, through ``self_hosting``'s
#: re-export) and :func:`maintainer_marker_hits` below. A label on another line,
#: or any other spelling, is not a label: a per-line reader cannot see it.
SELF_HOST_EXAMPLE_LABEL = "# Espalier-Harness tree:"

#: Top-level directories of the harness's own repository that ``init`` never
#: deploys. A ``.py`` path under one, shown to an adopter, names a file they do not
#: have. The test derives the live set: each root must be a directory here that
#: no deployed prefix covers, and :func:`self_host_path_roots` drops a root the
#: moment a deployed prefix starts covering it.
SELF_HOST_PATH_ROOTS: tuple[str, ...] = ("scripts", "tests", "bench", "espalier")

#: Maintainer-addressed markers, ``(family, pattern)``; the path family is built
#: per call by :func:`maintainer_marker_hits` from :data:`SELF_HOST_PATH_ROOTS`.
#: Calibrated on a fresh ``init`` + ``install-ci`` of a Node tree (2026-10-12:
#: 117 files, every hit read by hand): ledger ids, 8 of 85 false positives
#: (examples of the id grammar); self-host paths, about a quarter overall but all
#: 78 in deployed Python strings, which are path DATA (mirror maps, scope lists),
#: so the test reads that family on text bodies only; the retired-pack folder 1
#: of 5; the trailer 0 of 1; dated measurements about 4 of 16, at the first,
#: lowercase-only spelling (widened in review: "Measured 2026-09-06" and
#: "measured twice on 2026-09-06" passed it). Rejected on measurement, not to be
#: re-added without new numbers: the approval marker (22 of 22 hits are the
#: adopter's own CI mechanism: the CI gate requires it, and every writer of a
#: gated path names it).
MAINTAINER_MARKER_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    # The id grammar the ledger tools issue: an uppercase prefix, a hyphen, digits
    # and an optional lowercase suffix. TP/BC ids are SPECIFIC_ID_RE's, above.
    ("ledger-id", re.compile(r"\b(?:DEF|DEC|INV|LG|EI)-\d+[a-z]?\b")),
    ("retired-pack-folder", re.compile(r"task-packs/Done/")),
    ("co-author-trailer", re.compile(r"Co-Authored-By: Claude, Scion")),
    # "measured", any case, then a date within the next forty characters of the
    # line: a dated timing of this repository's own suite or lanes.
    ("dated-measurement", re.compile(r"\bmeasured\b[^\n]{0,40}?\b20\d\d-\d\d-\d\d\b", re.IGNORECASE)),
)

#: The two markers that fence a block a ``.claude`` body keeps for this
#: repository's own sessions; ``init`` strips the block on every other tree
#: (``espalier.cli._asset_transform``), so a mirror stays byte-equal to its source.
SELF_HOST_BLOCK_OPEN = "<!-- espalier:self-host-only -->"
SELF_HOST_BLOCK_CLOSE = "<!-- /espalier:self-host-only -->"
#: One block: the opener's line, the closer's line and everything between,
#: whatever comment carries the markers (an HTML comment in markdown, ``//`` in a
#: workflow, ``#`` in a shell fence). The block may hold no second opener, so a
#: stray opener pairs with nothing and strips nothing, rather than with the next
#: block's closer and everything between (the fence grammar is pinned in
#: ``tests/test_deployed_text_audience.py``).
SELF_HOST_BLOCK_RE = re.compile(
    r"^[^\n]*" + re.escape(SELF_HOST_BLOCK_OPEN)
    + r"(?:(?!" + re.escape(SELF_HOST_BLOCK_OPEN) + r").)*?"
    + re.escape(SELF_HOST_BLOCK_CLOSE) + r"[^\n]*(?:\n|\Z)",
    re.DOTALL | re.MULTILINE,
)


def strip_self_host_blocks(body: str) -> str:
    """``body`` as ``init`` writes it off this repository: its self-host blocks gone."""
    return SELF_HOST_BLOCK_RE.sub("", body)

#: The family name :func:`maintainer_marker_hits` reports a self-host path under.
SELF_HOST_PATH_FAMILY = "self-host-path"


def self_host_path_roots(deployed_prefixes: Iterable[str] = ()) -> tuple[str, ...]:
    """:data:`SELF_HOST_PATH_ROOTS` minus any root a deployed prefix covers.

    A prefix covers a root when it is the root or lies under it
    (``scripts/`` or ``scripts/x/``): a path there may be one the adopter has.
    """
    prefixes = [p.replace("\\", "/").rstrip("/") for p in deployed_prefixes]
    return tuple(
        root for root in SELF_HOST_PATH_ROOTS
        if not any(p == root or p.startswith(root + "/") for p in prefixes)
    )


def self_host_path_re(deployed_prefixes: Iterable[str] = ()) -> "re.Pattern[str] | None":
    """The ``.py``-path pattern over the roots ``init`` does not deploy, or None."""
    roots = self_host_path_roots(deployed_prefixes)
    if not roots:
        return None
    alternation = "|".join(re.escape(r) for r in roots)
    return re.compile(rf"(?<![\w/.])(?:{alternation})/[\w\-/]+\.py\b")


def maintainer_marker_hits(
    text: str,
    *,
    deployed_prefixes: Iterable[str] = (),
    skip: Iterable[str] = (),
) -> list[tuple[str, str]]:
    """``(family, match)`` for every maintainer-addressed marker in ``text``.

    Read line by line. A line carrying :data:`SELF_HOST_EXAMPLE_LABEL` is a
    self-host example kept on purpose, so its paths are no hit; an id or the
    trailer on it still is. ``skip`` names families not to read (the test skips
    the path family on Python strings, see :data:`MAINTAINER_MARKER_PATTERNS`).
    """
    skipped = set(skip)
    path_re = None if SELF_HOST_PATH_FAMILY in skipped else self_host_path_re(deployed_prefixes)
    families = [(f, p) for f, p in MAINTAINER_MARKER_PATTERNS if f not in skipped]
    hits: list[tuple[str, str]] = []
    for line in text.splitlines():
        for family, pat in families:
            hits.extend((family, m.group(0)) for m in pat.finditer(line))
        if path_re is not None and SELF_HOST_EXAMPLE_LABEL not in line:
            hits.extend((SELF_HOST_PATH_FAMILY, m.group(0)) for m in path_re.finditer(line))
    return hits


#: The packaged directories ``init`` seeds an adopter's tree from, read whole by
#: the audience gate (``tests/test_deployed_text_audience.py``) and by the asset
#: sync (``scripts/sync_asset_docs.py``) after every copy: one roster, two readers.
SEED_ROOTS: tuple[str, ...] = (
    "espalier/assets/docs",
    "espalier/assets/memory",
    "espalier/assets/seed",
    "espalier/assets/task-packs",
)
#: The suffixes the seeded walk reads as text.
SEED_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".js", ".yml", ".yaml", ".json", ".toml", ".txt"}
)
#: The seeded docs' maintainer-addressed hit count on the date it was taken: a
#: ceiling, not an exact pin. Two lanes that each remove a hit would both write
#: the same lowered pair and red main on the merge, so a cleanup leaves headroom
#: rather than a chore; lower the pair by hand when a cleanup lane wants the
#: floor to follow it. Never raised: a body over it is reworded at its source.
SEED_BASELINE: tuple[str, int] = ("2026-10-12", 266)


def seeded_text_files(
    repo_root: Path, *, walk: Callable[[Path], Iterable[Path]] | None = None,
) -> list[Path]:
    """Every text file under :data:`SEED_ROOTS`, sorted.

    ``walk(base)`` yields the candidates under one root (default:
    ``base.rglob("*")``; the audience gate passes git's view of the checkout). A
    root that is not there yields nothing: the gate holds its own floor on each
    root's presence.
    """
    out: list[Path] = []
    for root in SEED_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        candidates = (
            base.rglob("*")  # espalier:safe-walk-ok the packaged assets of this checkout, never an adopter tree
            if walk is None else walk(base)
        )
        out.extend(
            p for p in candidates
            if p.is_file() and p.suffix in SEED_TEXT_SUFFIXES and "__pycache__" not in p.parts
        )
    return sorted(out)


def seeded_marker_hits(
    repo_root: Path,
    *,
    deployed_prefixes: Iterable[str] = (),
    walk: Callable[[Path], Iterable[Path]] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Repo-relative POSIX path -> its :func:`maintainer_marker_hits`, for every
    seeded text file that carries one. The sum of the lengths is the count
    :data:`SEED_BASELINE` holds."""
    prefixes = tuple(deployed_prefixes)
    out: dict[str, list[tuple[str, str]]] = {}
    for path in seeded_text_files(repo_root, walk=walk):
        hits = maintainer_marker_hits(
            path.read_text(encoding="utf-8", errors="replace"), deployed_prefixes=prefixes,
        )
        if hits:
            out[path.relative_to(repo_root).as_posix()] = hits
    return out
