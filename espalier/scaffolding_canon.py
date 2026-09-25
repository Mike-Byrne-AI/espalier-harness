"""Scaffolding-quality canon — reads raw blueprint JSON; never imports
any module that participates in /reflect's surface walker.

Pins the de-circularization: quality metrics for scaffolding must NOT route
through the same surface walker the scaffolding shapes the agent toward. See
docs/SHARP_EDGES.md "Closed-Loop Verification Trap" and the ESPALIER_MEMORY.md
de-circularization recipe.

Forbidden imports (enforced by AST in
tests/test_scaffolding_canon.py::TestIndependentImports):
  - espalier.reflect_protocol
  - espalier.reflection
  - espalier.models
  - espalier.cognitive_blueprint
  - espalier.cli
  - espalier.doctor
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FORBIDDEN_IMPORTS = frozenset({
    "espalier.reflect_protocol",
    "espalier.reflection",
    "espalier.models",
    "espalier.cognitive_blueprint",
    "espalier.cli",
    "espalier.doctor",
})

_SUBAGENT_PREFIX = "[subagent:"


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    value: float | None
    sample_size: int
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CanonReport:
    n_sessions: int
    signal_1_continuity: Signal
    signal_2_human_density: Signal
    signal_3_reflect_coverage: Signal
    per_session: list[dict] = field(default_factory=list)


def _blueprint_sort_key(d: dict) -> tuple[int, str]:
    """Type-stable sort key over (accumulated_depth, timestamp).

    The isinstance(dict) guard in ``_load_blueprints_raw`` stops the ``.get``
    AttributeError, but a valid-JSON dict whose
    ``accumulated_depth``/``timestamp`` values are the WRONG type (a string
    depth, a null timestamp, a list) still crashes the sort with an uncaught
    TypeError when Python compares heterogeneous types across blueprints. Coerce
    off-type values to the neutral default so a malformed blueprint sorts first,
    never crashes."""
    depth = d.get("accumulated_depth", 0)
    ts = d.get("timestamp", "")
    return (
        depth if isinstance(depth, int) and not isinstance(depth, bool) else 0,
        ts if isinstance(ts, str) else "",
    )


def _load_blueprints_raw(repo_root: Path, last_n: int) -> list[dict]:
    """Load the last N blueprint JSON files directly. Does NOT use
    espalier.cognitive_blueprint's loaders (forbidden import)."""
    bp_dir = repo_root / "cc" / "blueprints"
    if not bp_dir.is_dir():
        return []
    files = sorted(p for p in bp_dir.glob("*.json") if p.name != "latest.json")
    out: list[dict] = []
    for f in files:
        try:
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # A blueprint that is not UTF-8 is malformed like one that is not
            # JSON: skipped, never a crash (DEF-792 -- the read followed the
            # OS locale until 2026-09-14).
            continue
        # A valid-JSON but non-dict blueprint (`[]` / `"s"` / `42`) parses
        # cleanly here, then crashes the `d.get(...)` sort key below with
        # AttributeError — a fail-open. Treat a non-dict like a malformed file
        # and skip it. (espalier/ cannot import
        # tools/cc/_json_safe.load_json_dict_safe per the isolation rule, so the
        # guard is inline.)
        if isinstance(data, dict):
            out.append(data)
    out.sort(key=_blueprint_sort_key)
    if last_n > 0:
        out = out[-last_n:]
    return out


def _entry_description(entry: dict) -> str:
    """A reasoning entry's ``description`` as a string. ``.get`` with a ""
    default still returns ``None`` when the key is PRESENT but null (a
    hand-edited / corrupt blueprint), which crashes ``.startswith`` / a
    ``str.join``. Coerce any non-string (None / int / list) to "".
    """
    desc = entry.get("description")
    return desc if isinstance(desc, str) else ""


def _signal_1_continuity(blueprints: list[dict]) -> Signal:
    """For each (S, S+1), fraction of S's continuation_fragments whose
    body (post `[tag]` prefix) appears as substring in S+1's reasoning
    text (joined descriptions).

    continuation_fragments are auto-derived at S's cmd_finalize from S's
    own decisions/patterns/findings; they are the curated highlights S
    hands forward as priming for S+1. This signal measures: did S+1
    actually write reasoning about the topics S handed forward?

    The `[decision] `, `[pattern] `, `[alternative] `, `[insight] `,
    `[unresolved] `, `[warning] `, `[converged] ` prefixes added at finalize
    are stripped before matching — S+1's reasoning_entries don't carry those
    prefixes. Stripping is generic (`split("] ", 1)`), not an allowlist, so a
    new label added to `cognitive_blueprint.FRAGMENT_LABELS` reaches this
    reader safely; this list is documentation, and must grow with that map.
    `[alternative]` and `[insight]` arrived with pinned fragments — a
    `carry_forward` entry of ANY kind now reaches the next session, where
    previously only decisions and patterns did.

    A `[subagent:<type>] <lead>` fragment (up to two agent REPORTS the
    builder has carried after the patterns since 2026-09-11) is skipped
    outright, by the same prefix Signal 2 keys on: an agent's lead is not S's
    curated reasoning, and a formulaic lead recurs verbatim when S+1
    dispatches the same reviewer, which would re-arm the marker-matching-
    marker self-noise the 2026-08-16b filter removed (docs/CONVENTIONS.md,
    the Signal 1 interpretation guards).
    """
    pairs = list(zip(blueprints, blueprints[1:]))
    scores: list[float] = []
    for prior, current in pairs:
        # Guard off-type nested fields (a malformed blueprint may carry a
        # non-list continuation_fragments/reasoning_entries, or a non-dict /
        # non-string entry) so a signal degrades to "no usable entries" rather
        # than crashing the whole canon computation.
        fragments = prior.get("continuation_fragments", [])
        if not isinstance(fragments, list):
            fragments = []
        if not fragments:
            continue
        cur_entries = current.get("reasoning_entries", [])
        if not isinstance(cur_entries, list):
            cur_entries = []
        current_text = "\n".join(
            _entry_description(e) for e in cur_entries if isinstance(e, dict)
        )
        matched = 0
        usable = 0
        for f in fragments:
            if not isinstance(f, str):
                continue
            # An agent's report fragment is neither a match nor a miss: it is
            # not S's reasoning, and its lead recurs verbatim across sessions
            # (see the docstring). Same literal Signal 2 keys on.
            if f.startswith(_SUBAGENT_PREFIX):
                continue
            body = f.split("] ", 1)[-1] if f.startswith("[") and "] " in f else f
            # An empty-body fragment (a bare "[decision] " prefix, or "") makes
            # `body[:60] in current_text` trivially True — `"" in s` is always
            # True — which inflates the continuity score. Skip empty bodies and
            # divide only by the usable count.
            if not body.strip():
                continue
            usable += 1
            if body[:60] in current_text:
                matched += 1
        if usable:
            scores.append(matched / usable)
    if not scores:
        return Signal("continuity_1hop", None, 0, "no pairs with prior fragments")
    return Signal(
        "continuity_1hop",
        sum(scores) / len(scores),
        len(scores),
        notes=f"pairs={len(scores)}/{len(pairs)} had prior continuation_fragments",
    )


def _signal_2_human_density(blueprints: list[dict]) -> Signal:
    """For each session, count reasoning_entries that don't start with
    the [subagent:NAME] auto-record prefix. Reports median across the
    sample plus zero-count fraction."""
    counts: list[int] = []
    for bp in blueprints:
        # Coerce off-type reasoning_entries to empty and skip non-dict entries
        # (a 'str-entry' would crash e.get with AttributeError).
        entries = bp.get("reasoning_entries", [])
        if not isinstance(entries, list):
            entries = []
        n = sum(
            1 for e in entries
            if isinstance(e, dict)
            and not _entry_description(e).startswith(_SUBAGENT_PREFIX)
        )
        counts.append(n)
    if not counts:
        return Signal("human_density", None, 0, "no sessions")
    sorted_counts = sorted(counts)
    median = sorted_counts[len(sorted_counts) // 2]
    zero_fraction = sum(1 for c in counts if c == 0) / len(counts)
    return Signal(
        "human_density",
        float(median),
        len(counts),
        notes=f"zero_fraction={zero_fraction:.2f}",
    )


def _signal_3_reflect_coverage(blueprints: list[dict]) -> Signal:
    """Fraction of sessions with at least one reflect_pass. Reports
    coverage rate ONLY; never reads gap_count, cross_ref_density, or
    findings (those would be closed-loop with the surface walker)."""
    if not blueprints:
        return Signal("reflect_coverage", None, 0, "no sessions")
    flags = [1 if bp.get("reflect_passes") else 0 for bp in blueprints]
    return Signal(
        "reflect_coverage",
        sum(flags) / len(flags),
        len(flags),
    )


def _per_session_row(blueprint: dict) -> dict:
    # A present-but-non-list field (``continuation_fragments: 42``) otherwise
    # crashed compute_canon with an uncaught TypeError in len(). Treat a
    # non-list as len 0.
    def _n(field: str) -> int:
        v = blueprint.get(field)
        return len(v) if isinstance(v, list) else 0

    return {
        "session_id": blueprint.get("session_id"),
        "timestamp": blueprint.get("timestamp"),
        "accumulated_depth": blueprint.get("accumulated_depth"),
        "n_reasoning_entries": _n("reasoning_entries"),
        "n_continuation_fragments": _n("continuation_fragments"),
        "n_reflect_passes": _n("reflect_passes"),
    }


def compute_canon(repo_root: Path, *, last_n: int = 20) -> CanonReport:
    blueprints = _load_blueprints_raw(repo_root, last_n)
    return CanonReport(
        n_sessions=len(blueprints),
        signal_1_continuity=_signal_1_continuity(blueprints),
        signal_2_human_density=_signal_2_human_density(blueprints),
        signal_3_reflect_coverage=_signal_3_reflect_coverage(blueprints),
        per_session=[_per_session_row(b) for b in blueprints],
    )
