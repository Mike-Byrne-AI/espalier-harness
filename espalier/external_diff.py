"""Pin diff/review workflow.

Distinguishes cosmetic drift (whitespace, anchor IDs, punctuation) from
semantic drift (sentence meaning changed). Cosmetic drift is the
"safe to ignore" case; semantic drift is the closed-loop trap warning.

The heuristic is intentionally cautious: false positives (cosmetic
flagged as semantic) are tolerable, false negatives (semantic missed)
are not. Any non-empty normalized diff is reported as semantic; the
magnitude classification distinguishes >=10% body changes ("high")
from smaller ("low").

`write_candidate` writes to `<pin>.candidate.md` and never overwrites
the original pin — auto-apply is the failure mode this whole TP exists
to prevent.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from espalier._atomic_io import atomic_write_text
from espalier.external_fetch import FetchResult
from espalier.external_pins import ExternalPin, _frontmatter_block, compute_body_hash

DRIFT_NONE = "none"
DRIFT_COSMETIC = "cosmetic"
DRIFT_SEMANTIC = "semantic"
DRIFT_FETCH_ERROR = "fetch_error"

# A diff is "high magnitude" when changed-line ratio exceeds this threshold.
HIGH_MAGNITUDE_THRESHOLD = 0.10


@dataclass(frozen=True)
class DriftReport:
    pin_path: Path
    source_url: str
    drift_kind: str
    unified_diff: str
    summary: str
    candidate_path: Path | None


def _normalize(text: str) -> str:
    """Aggressive normalization for the cosmetic vs semantic comparison.

    Lowercases, collapses whitespace, strips markdown formatting markers,
    drops anchor IDs and link URLs (which churn without semantic change).
    """
    t = text.lower()
    # Strip URLs in parens (markdown links): `[text](url)` → `[text]`
    t = re.sub(r"\]\([^)]*\)", "]", t)
    # Strip anchor refs like `{#anchor-id}`
    t = re.sub(r"\{#[^}]+\}", "", t)
    # Strip markdown emphasis / code spans
    t = re.sub(r"[*_`]+", "", t)
    # Collapse all whitespace runs to single space
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _changed_line_ratio(a: str, b: str) -> float:
    """Roughly: fraction of lines that differ between a and b.

    Used only as a magnitude hint; the binary semantic-vs-cosmetic decision
    happens on the normalized form.
    """
    a_lines = a.splitlines() or [""]
    b_lines = b.splitlines() or [""]
    sm = difflib.SequenceMatcher(None, a_lines, b_lines)
    return 1.0 - sm.ratio()


def compare_pin_to_fetched(pin: ExternalPin, fetched: FetchResult) -> DriftReport:
    """Compute the drift report for a pin against fetched upstream content."""
    if fetched.error is not None or not fetched.ok:
        return DriftReport(
            pin_path=pin.path,
            source_url=pin.source_url,
            drift_kind=DRIFT_FETCH_ERROR,
            unified_diff="",
            summary=f"fetch failed: {fetched.error}",
            candidate_path=None,
        )

    pin_body = pin.body
    fetched_body = fetched.content

    # Same content hash → drift_none (covers the common "weekly cron, nothing
    # changed upstream" case without doing string diff work).
    if compute_body_hash(pin_body) == compute_body_hash(fetched_body):
        return DriftReport(
            pin_path=pin.path,
            source_url=pin.source_url,
            drift_kind=DRIFT_NONE,
            unified_diff="",
            summary="content_hash unchanged; no drift",
            candidate_path=None,
        )

    norm_pin = _normalize(pin_body)
    norm_fetched = _normalize(fetched_body)

    unified = "".join(
        difflib.unified_diff(
            pin_body.splitlines(keepends=True),
            fetched_body.splitlines(keepends=True),
            fromfile=str(pin.path.name),
            tofile=f"{pin.path.name} (fetched)",
            n=3,
        )
    )

    if norm_pin == norm_fetched:
        # Body changed but normalization erased the difference → cosmetic.
        return DriftReport(
            pin_path=pin.path,
            source_url=pin.source_url,
            drift_kind=DRIFT_COSMETIC,
            unified_diff=unified,
            summary="cosmetic only (whitespace/markdown formatting/anchor IDs)",
            candidate_path=None,
        )

    # Compute the magnitude on the RAW bodies. _normalize collapses
    # every newline to a space, so the normalized form is a single line and
    # _changed_line_ratio always returns 1.0 ("high") for any non-cosmetic
    # change. The raw bodies retain line structure, so a 1-of-100-line change
    # correctly reads "low". The binary semantic-vs-cosmetic decision above
    # still uses the normalized form (untouched).
    ratio = _changed_line_ratio(pin_body, fetched_body)
    magnitude = "high" if ratio >= HIGH_MAGNITUDE_THRESHOLD else "low"
    return DriftReport(
        pin_path=pin.path,
        source_url=pin.source_url,
        drift_kind=DRIFT_SEMANTIC,
        unified_diff=unified,
        summary=f"semantic drift, magnitude={magnitude} ({ratio:.1%} of lines)",
        candidate_path=None,
    )


def write_candidate(pin: ExternalPin, fetched_content: str) -> Path:
    """Write fetched content to `<pin>.candidate.md` next to the pin.

    Reconstructs the candidate file with the pin's frontmatter (so the
    pin stays self-describing) and the fetched body. The fetched content
    is the new body. The frontmatter is copied VERBATIM — including the
    now-stale `fetched` and `content_hash` — so the operator refreshes
    those two fields by hand when renaming the candidate over the pin.

    Never overwrites the original pin.
    """
    candidate_path = pin.path.with_name(f"{pin.path.stem}.candidate.md")
    # We just write the new body, prefixed by a copy of the original
    # frontmatter — content_hash and fetched included as-is (the operator
    # refreshes those stale fields by hand when accepting). The
    # frontmatter bytes are taken verbatim from the
    # source pin so we don't have to round-trip through the parser
    # (which discards comments and reorders keys).
    original = pin.path.read_text(encoding="utf-8")
    # Re-extract the literal frontmatter block (both delimiters) via the shared
    # writers' helper; this site keeps its own no-frontmatter guard + message.
    if not original.startswith("---\n"):
        raise ValueError(f"pin {pin.path} has no frontmatter — cannot write candidate")
    frontmatter_block = _frontmatter_block(
        original, malformed_msg=f"pin {pin.path} has malformed frontmatter"
    )
    candidate_text = frontmatter_block + "\n\n" + fetched_content
    atomic_write_text(candidate_path, candidate_text)
    return candidate_path
