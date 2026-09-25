"""Cognitive blueprint system — the cross-session reasoning layer.

This module implements the full blueprint system described in DEEP-WORK.md:

1. **Reasoning capture** — structured entries for decisions made,
   alternatives rejected, patterns discovered, and reflect-derived insights.

2. **Session chain** — each blueprint records its parent session,
   accumulated depth, and continuation fragments that seed the next session.

3. **Quality metrics** — gap convergence (intended to decrease per pass)
   and cross-ref density trend (intended to increase). These are mechanism
   signals the reflect protocol emits for inspection, not a validated
   measurement of an effect.

The state-snapshot blueprint (what exists, what passed) is the foundation.
The reasoning-capture layer adds WHY decisions were made, so the next
session can re-engage with prior reasoning rather than re-deriving it.

Storage: cc/blueprints/{session_id}.json
Latest:  cc/blueprints/latest.json (copy of most recent)

This is the library version of cognitive_blueprint. The hook-side
standalone CLI lives at `tools/cc/cognitive_blueprint.py` and exposes a
narrower action surface. Bug fixes that affect both concerns must
land in both files; there is no whole-file parity test; the axes
that MUST agree are pinned individually by
`tests/test_cognitive_blueprint_schema_parity.py`.
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from espalier._atomic_io import atomic_write_text
from espalier._blueprint_limits import (
    BLUEPRINT_COLD_DIR_NAME,
    BLUEPRINT_MAX_SIZE,
    BLUEPRINT_MIN_PRUNE_AGE_S,
    BLUEPRINT_RETENTION,
    BLUEPRINT_STUB_MAX_BYTES,
)
from espalier._report_io import load_report_json

from espalier.models import (
    CognitiveBlueprint,
    ReasoningEntry,
    ReflectPass,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def _load_json(path: Path) -> dict[str, Any]:
    """Best-effort JSON loader for sidecar reports.

    Wraps reads in ``OSError`` / ``UnicodeDecodeError`` / ``JSONDecodeError``
    so a corrupt or unreadable sidecar (denied permission, mid-rename,
    BOM-prefixed UTF-16) returns ``{}`` instead of bubbling and crashing the
    caller. The contract lives in ``espalier._report_io.load_report_json``;
    the hook-side ``tools/cc/cognitive_blueprint.py::_load_json`` remains a
    SEPARATE owner by the zero-import boundary.
    """
    return load_report_json(path)


def _blueprints_dir(repo_root: Path) -> Path:
    return repo_root / "cc" / "blueprints"


# ── Load / Save ──────────────────────────────────────────────────────

def load_latest_blueprint(repo_root: Path) -> CognitiveBlueprint | None:
    """Load the most recent cognitive blueprint, if any.

    Routes the read through ``_load_json`` so OSError /
    UnicodeDecodeError / JSONDecodeError all degrade to ``None`` (no
    active blueprint) rather than crashing the caller — an OSError on the
    read (permission, mid-rename via ``atomic_write_text``, transient FS)
    must not propagate and crash SessionStart.

    BC-038 library-side parity: refuse symlinks and cap reads at
    ``BLUEPRINT_MAX_SIZE``. ``cc/blueprints/`` is in
    ``write_guard.ALLOWED_PREFIXES_IN_PROTECTED``, so a stray or
    hand-edited symlink at ``latest.json`` could point off-path, and a
    corrupted/oversize file could OOM the reader. Degrading to no-summary
    here protects the continuity chain (the workflow), never crashing
    SessionStart. Mirrors the hook-side guards in
    ``tools/cc/cognitive_blueprint.py::_load_latest``.
    """
    path = _blueprints_dir(repo_root) / "latest.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        if path.stat().st_size > BLUEPRINT_MAX_SIZE:
            return None
    except OSError:
        return None
    data = _load_json(path)
    if not data:
        return None
    try:
        return CognitiveBlueprint.from_dict(data)
    except (KeyError, TypeError, AttributeError):
        # AttributeError guards a non-dict nested element (producer drift → a
        # `findings` entry that is a str/None), so the reader degrades to None
        # rather than crashing the SessionStart.
        return None


def _truncate_blueprint_to_cap(blueprint: CognitiveBlueprint) -> CognitiveBlueprint:
    """Writer-side size cap, mirroring hook ``_truncate_to_cap``.

    The reader (``load_latest_blueprint``) rejects blueprints over
    ``BLUEPRINT_MAX_SIZE``; without a writer-side cap a legitimate long session
    that crosses the cap writes a file its own reader silently refuses, losing
    the whole accumulated chain on next SessionStart. Drop oldest first so the
    most recent reasoning survives; then cap ``reflect_passes`` /
    ``action_justifications`` / ``continuation_fragments`` / ``gap_convergence``
    / ``cross_ref_density_trend`` so the cap can't be defeated once one field is
    empty. Measure with the EXACT ``json.dumps`` kwargs
    the real write uses (``indent=2, sort_keys=True``) so a serializer mismatch
    can't re-open the >cap-write-then-unreadable hole.
    """
    def _size(bp: CognitiveBlueprint) -> int:
        data = json.dumps(bp.to_dict(), indent=2, sort_keys=True) + "\n"
        return len(data.encode("utf-8"))

    if _size(blueprint) <= BLUEPRINT_MAX_SIZE:
        return blueprint

    bp = blueprint
    dropped = {
        "reasoning_entries": 0, "reflect_passes": 0, "action_justifications": 0,
        "continuation_fragments": 0, "gap_convergence": 0, "cross_ref_density_trend": 0,
    }
    for field_name in (
        "reasoning_entries", "reflect_passes", "action_justifications",
        "continuation_fragments", "gap_convergence", "cross_ref_density_trend",
    ):
        items = list(getattr(bp, field_name))
        while _size(bp) > BLUEPRINT_MAX_SIZE and items:
            items.pop(0)
            dropped[field_name] += 1
            bp = replace(bp, **{field_name: items})

    total = sum(dropped.values())
    if total:
        print(
            f"[WARN] save_blueprint: truncated {total} oldest entries to fit the "
            f"{BLUEPRINT_MAX_SIZE}-byte cap ({dropped})",
            file=sys.stderr,
        )
    return bp


def _prune_blueprints(bp_dir: Path) -> None:
    """Bound per-session blueprint accumulation.

    save_blueprint writes one ``{session_id}.json`` per session and never
    reclaims them, so a long-lived checkout grows without limit (the
    self-host tree hit ~350 files). Keep the ``BLUEPRINT_RETENTION``
    most-recent per-session files; DEMOTE older ones into
    ``BLUEPRINT_COLD_DIR_NAME`` — never delete them, never ``latest.json``,
    and never a file modified within ``BLUEPRINT_MIN_PRUNE_AGE_S`` (a
    concurrent session may still be writing it). Best-effort hygiene: any
    error is swallowed so a prune failure never breaks a blueprint write.

    The cap bounds the WORKING SET, not the record. It deleted until
    2026-08-31, by which point the chain had already lost ~2 months with no
    alarm — deleting and retaining were indistinguishable at every
    observable the tooling had.

    Mirrors ``_save``'s prune in ``tools/cc/cognitive_blueprint.py``.
    """
    try:
        files = [
            p for p in bp_dir.glob("*.json")
            if p.name != "latest.json" and p.is_file() and not p.is_symlink()
        ]
        if len(files) <= BLUEPRINT_RETENTION:
            return
        now = time.time()
        # Substantive nodes (larger than an empty-session stub) sort first, so
        # files[BLUEPRINT_RETENTION:] — the eviction tail — is stubs first, then
        # only the oldest substantive nodes. Stubs are reclaimed before reasoning.
        files.sort(
            key=lambda p: (p.stat().st_size > BLUEPRINT_STUB_MAX_BYTES, p.stat().st_mtime),
            reverse=True,
        )
        # Sort key is st_mtime, deliberately. A filename-derived key would be
        # restore-invariant (git clone and shutil.copy reset mtime, collapsing
        # this to a constant) -- but two attempts at one broke a different
        # existing test each time, and DEMOTION REMOVED THE STAKES: a
        # mis-ordered eviction tail now moves the wrong node into the cold
        # store, it does not destroy one. Revisit only with a reason that
        # survives that.
        cold_dir = bp_dir / BLUEPRINT_COLD_DIR_NAME
        for p in files[BLUEPRINT_RETENTION:]:
            try:
                if now - p.stat().st_mtime < BLUEPRINT_MIN_PRUNE_AGE_S:
                    continue
                cold_dir.mkdir(parents=True, exist_ok=True)
                p.replace(cold_dir / p.name)
            except OSError:
                continue
    except OSError:
        return


def save_blueprint(repo_root: Path, blueprint: CognitiveBlueprint) -> Path:
    """Save a cognitive blueprint and update the latest pointer."""
    bp_dir = _blueprints_dir(repo_root)
    bp_dir.mkdir(parents=True, exist_ok=True)
    blueprint = _truncate_blueprint_to_cap(blueprint)
    data = json.dumps(blueprint.to_dict(), indent=2, sort_keys=True) + "\n"
    # Save timestamped copy
    session_file = bp_dir / f"{blueprint.session_id}.json"
    atomic_write_text(session_file, data, encoding="utf-8")
    # Update latest pointer — atomic replace prevents torn JSON if a
    # concurrent reader (next-session SessionStart) races us mid-write.
    latest = bp_dir / "latest.json"
    atomic_write_text(latest, data, encoding="utf-8")
    _prune_blueprints(bp_dir)
    return session_file


def list_blueprint_chain(repo_root: Path) -> list[dict[str, Any]]:
    """List all blueprints in chronological order with summary metadata."""
    bp_dir = _blueprints_dir(repo_root)
    if not bp_dir.exists():
        return []
    chain: list[dict[str, Any]] = []
    for path in sorted(bp_dir.glob("*.json")):
        if path.name == "latest.json":
            continue
        if path.is_symlink():
            continue
        try:
            if path.stat().st_size > BLUEPRINT_MAX_SIZE:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            # A non-dict blueprint would crash data.get past the
            # (JSONDecodeError, KeyError, OSError) except.
            if not isinstance(data, dict):
                continue
            chain.append({
                "session_id": data.get("session_id", path.stem),
                "timestamp": data.get("timestamp", ""),
                "parent_session_id": data.get("parent_session_id", ""),
                "accumulated_depth": data.get("accumulated_depth", 1),
                "reasoning_count": len(data.get("reasoning_entries", [])),
                "reflect_pass_count": len(data.get("reflect_passes", [])),
                "continuation_fragment_count": len(data.get("continuation_fragments", [])),
                "gap_convergence": data.get("gap_convergence", []),
            })
        # read_text raises UnicodeDecodeError (a ValueError, not OSError) on a
        # BOM/non-UTF8 blueprint, before the except below — so a bad-bytes
        # sidecar would crash chain-walk. _load_json already catches it on the
        # latest-pointer path; this is the chain-path sister.
        except (json.JSONDecodeError, KeyError, OSError, UnicodeDecodeError):
            continue
    # Coerce off-type values so a blueprint whose accumulated_depth/timestamp
    # is the wrong JSON type (str depth, null timestamp, …) can't crash this
    # sort with an uncaught TypeError on heterogeneous comparison — same
    # fail-open class closed in scaffolding_canon._load_blueprints_raw (kept
    # inline; these two modules do not share loaders by design).
    def _key(e: dict) -> tuple[int, str]:
        depth = e.get("accumulated_depth", 0)
        ts = e.get("timestamp", "")
        return (
            depth if isinstance(depth, int) and not isinstance(depth, bool) else 0,
            ts if isinstance(ts, str) else "",
        )

    chain.sort(key=_key)
    return chain


# ── Blueprint Construction ───────────────────────────────────────────

def start_session(repo_root: Path) -> CognitiveBlueprint:
    """Start a new cognitive session, chaining from the latest blueprint.

    If a prior blueprint exists, inherit its accumulated_depth + 1 and
    carry forward its continuation_fragments as starting context.
    """
    repo_root = repo_root.resolve()
    session_id = _new_session_id()
    prior = load_latest_blueprint(repo_root)

    # Load project state from reports
    fp_data = _load_json(repo_root / "reports" / "repo_fingerprint.json")
    plan_data = _load_json(repo_root / "reports" / "harness_config.json")
    gate_data = _load_json(repo_root / "reports" / "cc_surface_gate.json")

    agents = plan_data.get("agents", []) if isinstance(plan_data.get("agents"), list) else []
    stable_actions = plan_data.get("stable_actions", {}) if isinstance(plan_data.get("stable_actions"), dict) else {}
    commands = [
        {"action": str(name), "command": str(cmds[0]) if isinstance(cmds, list) and cmds else ""}
        for name, cmds in stable_actions.items()
    ]

    blueprint = CognitiveBlueprint(
        session_id=session_id,
        repo_name=str(fp_data.get("repo_name", "") or plan_data.get("repo_name", "") or repo_root.name),
        timestamp=_iso_now(),
        parent_session_id=prior.session_id if prior else "",
        accumulated_depth=(prior.accumulated_depth + 1) if prior else 1,
        languages=[str(x) for x in fp_data.get("languages", [])] if isinstance(fp_data.get("languages"), list) else [],
        profiles=[str(x) for x in plan_data.get("profiles", [])] if isinstance(plan_data.get("profiles"), list) else [],
        gate_status=str(gate_data.get("status", "unknown")),
        agents=[
            {"name": str(a.get("name", "")), "scope": str(a.get("scope", ""))}
            for a in agents[:10] if isinstance(a, dict)
        ],
        commands=commands,
    )

    return blueprint


# ── Mutation-vs-replace API note ────────────────────────────────────────────
#
# CognitiveBlueprint is `@dataclass(frozen=True, slots=True)`. Frozen blocks
# attribute reassignment (`bp.foo = x` raises FrozenInstanceError) but does
# NOT block in-place mutation of mutable field values (`bp.list_field.append(x)`
# is fine). The helpers below use the cheaper pattern where it's correct:
#
#   - `add_reasoning` and `record_reflect_pass` append to list fields. They
#     return None and mutate in-place — preserves the existing call-site
#     ergonomics for code that records many entries during a session.
#   - `set_continuation_fragments` REPLACES a list field's contents. The "set"
#     semantic forces a `replace()` call (you can't `.append` your way to a
#     replacement), so it returns a new blueprint and callers must rebind.
#
# The split is deliberate. If a future field needs full immutability (e.g.,
# rebinding a scalar like `accumulated_depth`), use `replace()` and follow the
# `set_continuation_fragments` pattern.


def add_reasoning(blueprint: CognitiveBlueprint, kind: str, description: str,
                  evidence: list[str] | None = None,
                  carry_forward: bool = False) -> None:
    """Append a reasoning entry to `blueprint.reasoning_entries` (in-place).

    Kinds:
      - decision: a choice that was made and why
      - alternative_rejected: an option considered and why it was dropped
      - pattern_discovered: a pattern observed in the code or workflow
      - reflect_insight: an insight from a reflect pass

    `carry_forward` pins the entry so the reinjection selection prefers it over
    pure recency.

    `CognitiveBlueprint` is frozen but list-field append is allowed — see the
    "Mutation-vs-replace API note" above.
    """
    blueprint.reasoning_entries.append(ReasoningEntry(
        kind=kind,
        description=description,
        evidence=evidence or [],
        session_id=blueprint.session_id,
        timestamp=_iso_now(),
        carry_forward=carry_forward,
    ))


# Action-grain rationale capture. Mirrors the hook-side
# tools/cc/cognitive_blueprint.py::cmd_justify path; both must agree on
# every (tool, content_hash) input pair — pinned by
# TestParity::test_hook_and_library_agree.
_AJ_PROSE_FIELDS = ("goal", "step_rationale", "expected_outcome", "not_doing")
_AJ_MAX_FIELD_CHARS = 500
_AJ_HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _validate_action_justification(*, goal: str, step_rationale: str,
                                    expected_outcome: str, not_doing: str,
                                    tool: str, content_hash: str) -> None:
    """Validate ActionJustification field values. Raises ValueError on
    any violation; callers MUST NOT write on validation failure."""
    values = {"goal": goal, "step_rationale": step_rationale,
              "expected_outcome": expected_outcome, "not_doing": not_doing}
    for name in _AJ_PROSE_FIELDS:
        v = values[name].strip()
        if not v:
            raise ValueError(f"action_justification.{name} is empty")
        if len(v) > _AJ_MAX_FIELD_CHARS:
            raise ValueError(
                f"action_justification.{name} exceeds "
                f"{_AJ_MAX_FIELD_CHARS} chars"
            )
    from espalier.harness_config import MUTATION_TOOLS_TOKENS
    # mcp__* is open-ended; the literal tuple cannot enumerate every
    # MCP write tool name. The hook-side validator carries the same
    # prefix relaxation; both must accept/reject identically.
    if tool not in MUTATION_TOOLS_TOKENS and not tool.startswith("mcp__"):
        raise ValueError(
            f"action_justification.tool {tool!r} not in "
            "MUTATION_TOOLS_TOKENS"
        )
    if not _AJ_HASH_RE.match(content_hash):
        # Kept worded the same as the tools/cc twin: the two validators are
        # pinned on decisions, and a reader who meets one message should not
        # have to wonder whether the other says something different.
        raise ValueError(
            f"action_justification.content_hash malformed: {content_hash!r} "
            "-- expected 'sha256:' followed by 64 lowercase hex chars. Pass "
            "--from-tool-input-file <path> to compute it from the file "
            "instead of building the string by hand."
        )


def add_action_justification(blueprint_path: Path, *,
                              goal: str, step_rationale: str,
                              expected_outcome: str, not_doing: str,
                              tool: str, content_hash: str) -> None:
    """Append a validated ActionJustification to the blueprint at
    `blueprint_path`.

    Atomic write via atomic_write_text (espalier._atomic_io).
    Validation raises ValueError on field violations; the entry is NOT
    appended on validation failure.
    """
    _validate_action_justification(
        goal=goal, step_rationale=step_rationale,
        expected_outcome=expected_outcome, not_doing=not_doing,
        tool=tool, content_hash=content_hash,
    )
    blueprint = _load_json(blueprint_path)
    entry = {
        "goal": goal.strip(),
        "step_rationale": step_rationale.strip(),
        "expected_outcome": expected_outcome.strip(),
        "not_doing": not_doing.strip(),
        "tool": tool,
        "content_hash": content_hash,
        "timestamp": _iso_now(),
        "session_id": blueprint.get("session_id", ""),
    }
    blueprint.setdefault("action_justifications", []).append(entry)
    atomic_write_text(
        blueprint_path,
        json.dumps(blueprint, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def show_recent(blueprint: dict[str, Any], n: int = 5,
                kind_filter: str | None = None) -> list[dict[str, Any]]:
    # Library twin of tools/cc/cognitive_blueprint.py::cmd_show_recent.
    # Pure function over the raw blueprint dict shape (same shape
    # tools/cc/cognitive_blueprint.py::_load_latest returns), so the hook-side
    # CLI's --json output and this helper return identical lists for the same
    # input — TestShowRecentParity pins that.
    # The selection (drop-malformed + noise-filter + pins-before-recency) MUST
    # stay identical to the hook-side cmd_show_recent so TestShowRecentParity holds.
    entries = blueprint.get("reasoning_entries", [])
    # Tolerate a malformed blueprint (a non-dict entry) -- skip it, never crash.
    entries = [e for e in entries if isinstance(e, dict)]
    if kind_filter:
        entries = [e for e in entries if e.get("kind") == kind_filter]
    # Drop the auto [subagent:<type>] anchors -- not decisions, noise in the
    # reinjected selection -- but keep an agent REPORT (DEF-586): after a
    # mid-fan-out compaction the reviewers' leads are the freshest reasoning.
    # At most MAX_AGENT_FRAGMENTS of them, chosen the way the fragment builder
    # chooses (pinned first, then newest, one per description): subagent stops
    # cluster at the end of a fan-out, and on pure recency five reports took
    # all five slots from the session's own decisions -- the DEF-584 shape at
    # this reader.
    kept = _select_agent_reports(entries)
    entries = [e for e in entries if not _is_activity_log(e) or any(e is k for k in kept)]
    # n <= 0 returns none, not all (`entries[-0:]` would be the whole list).
    if n <= 0:
        return []
    # Importance over recency (§9 salience != importance): pinned entries first,
    # newest-first; then recency backfill with the rest, newest-first, to n total.
    pinned = [e for e in reversed(entries) if e.get("carry_forward")]
    backfill = [e for e in reversed(entries) if not e.get("carry_forward")]
    selected = pinned[:n]
    if len(selected) < n:
        selected += backfill[: n - len(selected)]
    return selected


def record_reflect_pass(blueprint: CognitiveBlueprint, reflect_pass: ReflectPass) -> None:
    """Append a reflect pass to `blueprint.reflect_passes` and update
    convergence metrics in place.

    `CognitiveBlueprint` is frozen but list-field append is allowed — see the
    "Mutation-vs-replace API note" above.
    """
    blueprint.reflect_passes.append(reflect_pass)
    blueprint.gap_convergence.append(reflect_pass.gap_count)
    blueprint.cross_ref_density_trend.append(reflect_pass.cross_ref_density)


def set_continuation_fragments(blueprint: CognitiveBlueprint, fragments: list[str]) -> CognitiveBlueprint:
    """Return a new blueprint with continuation fragments — top insights to
    seed the next session.

    These should be the 3-7 most important things the next session needs
    to know that aren't captured in the project's existing docs. Think:
    - Decisions that aren't in ESPALIER_MEMORY.md yet
    - Patterns that emerged during reflect but haven't been codified
    - Risks identified but not yet mitigated
    - Next steps that depend on context only this session has

    Unlike `add_reasoning` / `record_reflect_pass` (which append to list
    fields in place), this REPLACES the field. `CognitiveBlueprint` is frozen,
    so callers must rebind: `bp = set_continuation_fragments(bp, fragments)`.
    See the "Mutation-vs-replace API note" above.
    """
    return replace(blueprint, continuation_fragments=list(fragments))


#: Fragment label per entry kind. The prefix is stripped generically by
#: :mod:`espalier.scaffolding_canon` (``split("] ", 1)``), so this map may grow
#: without breaking that reader -- but its docstring enumerates the vocabulary
#: and must grow with it.
#:
#: sister-site: ok forced copy across the no-import boundary -- the standalone
#: twin is ``tools/cc/cognitive_blueprint.py::_FRAGMENT_LABELS``, which cannot
#: import espalier. Pinned by tests/test_cognitive_blueprint_schema_parity.py.
FRAGMENT_LABELS = {
    "decision": "decision",
    "pattern_discovered": "pattern",
    "alternative_rejected": "alternative",
    "reflect_insight": "insight",
}
#: Cap on pinned fragments, mirroring the reinjection selection's own bound.
#: sister-site: ok forced copy -- twin is ``_MAX_PINNED_FRAGMENTS``.
MAX_PINNED_FRAGMENTS = 5

#: ``subagent_stop`` records one auto entry per subagent stop, prefixed
#: ``[subagent:<type>]``. It is an AGENT's entry, not the operator's reasoning:
#: either an ANCHOR (``completed``, no evidence -- the run happened, nothing to
#: keep) or, since DEF-586, a REPORT (the lead of the agent's final message,
#: with the transcript it was cut from as evidence).
#:
#: The SELECTION readers drop both from the operator's own selections -- pins,
#: decisions, patterns (``auto_continuation_fragments``, ``render_context_load``,
#: ``show_recent``) -- so a fan-out never crowds them; a REPORT then comes back
#: through ``_is_agent_report``: kept by ``show_recent`` and carried by
#: ``auto_continuation_fragments`` in its own bounded slot
#: (``_select_agent_reports``). ``render_blueprint_md`` filters nothing,
#: deliberately: it is the full archive of a session rather than a selection
#: from it, and ``test_render_blueprint_md_keeps_the_full_archive`` pins that so
#: the divergence between this module's two human-facing renderers is a recorded
#: choice and not the next silent omission.
#:
#: sister-site: ok forced copy across the no-import boundary -- the standalone
#: twin is ``tools/cc/cognitive_blueprint.py::_ACTIVITY_LOG_PREFIX``, which
#: cannot import espalier. Pinned by tests/test_cognitive_blueprint_schema_parity.py.
_ACTIVITY_LOG_PREFIX = "[subagent:"

#: How many agent REPORTS ``auto_continuation_fragments`` carries into the next
#: session (DEF-586). Two matches the repo's own two-reviewer dispatch; each is
#: a lead of at most ``subagent_stop._LEAD_CHARS`` (600), so the slot spends
#: about a fifth of session_start's 6 KB blueprint share. The rest of a fan-out
#: is in the archive and in ``show_recent``.
#:
#: sister-site: ok forced copy across the no-import boundary -- the standalone
#: twin is ``tools/cc/cognitive_blueprint.py::_MAX_AGENT_FRAGMENTS``, which
#: cannot import espalier. Pinned by tests/test_cognitive_blueprint_schema_parity.py.
MAX_AGENT_FRAGMENTS = 2


def _is_activity_log(entry) -> bool:
    """True for ANY ``[subagent:<type>]`` entry -- an anchor or a report; see
    :func:`_is_agent_report` for the split. Every operator selection (pins,
    decisions, patterns) excludes both.

    The retyped form is exactly what broke: this predicate was hand-spelled at
    the reinjection selection and at ``_recent_entries`` but omitted from
    ``auto_continuation_fragments`` -- the function that builds what the NEXT
    session reads -- and nothing compared the three. Add a reader by CALLING
    this, never by copying the prefix.

    ⚠ THE CLASS IS NOT CLOSED, and an earlier draft of this docstring claimed it
    was. Live census is FOUR definitions, not two: this one and
    ``tools/cc/cognitive_blueprint.py`` (a forced pair -- ``tools/cc/`` may not
    import ``espalier/``); ``tools/cc/reflect_protocol.py`` (**not** forced -- it
    already imports ``cognitive_blueprint`` as a sibling, so that collapse is
    merely untaken); and ``espalier/scaffolding_canon.py::_SUBAGENT_PREFIX``,
    which IS forced because ``espalier.cognitive_blueprint`` is listed in that
    module's ``FORBIDDEN_IMPORTS`` de-circularization set.

    Accepts BOTH shapes this module handles -- the dataclass entries and the raw
    dicts read off a hand-edited blueprint -- because the two omitted sites used
    different accessors, and a predicate that only knew one of them would have
    left the other retyped.
    """
    description = (
        entry.get("description", "")
        if isinstance(entry, dict)
        else getattr(entry, "description", "")
    )
    return str(description).startswith(_ACTIVITY_LOG_PREFIX)


def _is_agent_report(entry) -> bool:
    """True for a ``[subagent:<type>]`` entry that carries EVIDENCE: the
    agent's final-message lead with the transcript it was cut from (DEF-586).

    The split is structural -- not a length floor, not a second literal.
    ``subagent_stop`` records evidence with a lead and never with an anchor
    (``completed``), so a marker written by a pre-DEF-586 hook (a fixed
    sentence, no evidence) still reads as an anchor and is dropped, while a
    report is kept by :func:`show_recent` and carried by
    :func:`auto_continuation_fragments` through :func:`_select_agent_reports`.
    To every OTHER selection a report is still an activity-log entry: it never
    takes a pin, decision or pattern slot, and reflect never offers it as a
    memory candidate -- an agent's report is a claim, not the operator's
    reasoning. Accepts both entry shapes, like :func:`_is_activity_log`.
    """
    if not _is_activity_log(entry):
        return False
    evidence = (
        entry.get("evidence")
        if isinstance(entry, dict)
        else getattr(entry, "evidence", None)
    )
    return bool(evidence)


def _select_agent_reports(entries, n: int = MAX_AGENT_FRAGMENTS) -> list:
    """The ``n`` reports to carry forward: pinned first, then the newest, both
    newest-first -- the importance-over-recency shape every other selection
    here uses (§9), so an operator's pin on a report is not inert -- and one
    slot per distinct description: two agents returning the same boilerplate
    are distinct entries to the record CLI (its identity includes the
    evidence, and the transcript path differs per instance) and would
    otherwise spend the whole slot on one sentence."""
    def _pinned(e) -> bool:
        return bool(
            e.get("carry_forward") if isinstance(e, dict)
            else getattr(e, "carry_forward", False)
        )

    def _desc(e) -> str:
        return str(
            e.get("description", "") if isinstance(e, dict)
            else getattr(e, "description", "")
        )
    reports = [e for e in entries if _is_agent_report(e)]
    pinned = [e for e in reversed(reports) if _pinned(e)]
    backfill = [e for e in reversed(reports) if not _pinned(e)]
    seen: set[str] = set()
    out: list = []
    for e in pinned + backfill:
        desc = _desc(e)
        if desc in seen:
            continue
        seen.add(desc)
        out.append(e)
        if len(out) == n:
            break
    return out


def auto_continuation_fragments(blueprint: CognitiveBlueprint) -> list[str]:
    """Generate continuation fragments from the blueprint's content.

    This is the automatic version — extracts the most important
    reasoning entries and reflect findings. For higher quality,
    use set_continuation_fragments() with manually curated entries.
    """
    fragments: list[str] = []

    # PINNED FIRST, any kind. Without this the carry_forward mechanism was inert
    # in the function that builds what the NEXT session reads: `add_reasoning
    # (..., carry_forward=True)` sets it, the reinjection selection below honours
    # it, and this one never looked. An `alternative_rejected` entry was dropped
    # outright, since only `decision` and `pattern_discovered` were collected.
    # Same importance-over-recency shape as the pinned/backfill selection at
    # _recent_entries (§9).
    # Filtered ONCE at the source: three selections read the entries below
    # (pinned-any-kind, decisions, patterns) and each is an independent way for
    # an auto-marker to reach the next session. Binding the filtered list here
    # closes all three and leaves no fourth for a later selection to miss.
    entries = [e for e in blueprint.reasoning_entries if not _is_activity_log(e)]

    emitted: set[tuple[str, str]] = set()
    for e in [e for e in reversed(entries)
              if e.carry_forward][:MAX_PINNED_FRAGMENTS]:
        fragments.append(
            f"[{FRAGMENT_LABELS.get(e.kind, e.kind or 'entry')}] {e.description}"
        )
        emitted.add((e.kind, e.description))

    # Pull decisions (most important for continuity)
    decisions = [e for e in entries
                 if e.kind == "decision" and ("decision", e.description) not in emitted]
    for d in decisions[-3:]:
        fragments.append(f"[decision] {d.description}")

    # Pull high-severity reflect findings
    if blueprint.reflect_passes:
        latest = blueprint.reflect_passes[-1]
        high = [f for f in latest.findings if f.severity == "high"]
        for h in high[:3]:
            fragments.append(f"[unresolved] {h.description}")

    # Pull pattern discoveries
    patterns = [e for e in entries
                if e.kind == "pattern_discovered"
                and ("pattern_discovered", e.description) not in emitted]
    for p in patterns[-2:]:
        fragments.append(f"[pattern] {p.description}")

    # Agent REPORTS (DEF-586): the leads a fan-out left, in their own bounded
    # slot AFTER the operator's patterns. Read off the UNFILTERED list on
    # purpose: `entries` above has every agent entry removed, which is right for
    # the three operator selections, and this slot is the one deliberate
    # exception. The description already carries its `[subagent:<type>]` label.
    for r in _select_agent_reports(blueprint.reasoning_entries):
        fragments.append(r.description)

    # Gap convergence note
    if len(blueprint.gap_convergence) >= 2:
        trend = blueprint.gap_convergence
        if trend[-1] > trend[-2]:
            fragments.append(f"[warning] Gap count increased: {trend[-2]} -> {trend[-1]}")
        elif trend[-1] == 0:
            fragments.append("[converged] Gap count reached zero")

    return fragments


# ── Rendering ────────────────────────────────────────────────────────

def render_blueprint_md(blueprint: CognitiveBlueprint) -> str:
    """Render a cognitive blueprint as markdown for human reading."""
    lines = [
        "# COGNITIVE BLUEPRINT",
        "",
        "## Session Identity",
        f"- Session: `{blueprint.session_id}`",
        f"- Timestamp: {blueprint.timestamp}",
        f"- Parent session: `{blueprint.parent_session_id or 'none (first session)'}`",
        f"- Accumulated depth: {blueprint.accumulated_depth}",
        "",
        "## Project State",
        f"- Repo: {blueprint.repo_name}",
        f"- Languages: {', '.join(blueprint.languages) or 'unknown'}",
        f"- Profiles: {', '.join(blueprint.profiles) or 'unknown'}",
        f"- Gate status: {blueprint.gate_status}",
        "",
    ]

    # Reasoning entries
    if blueprint.reasoning_entries:
        lines.extend(["## Reasoning Captured", ""])
        by_kind: dict[str, list[ReasoningEntry]] = {}
        for entry in blueprint.reasoning_entries:
            by_kind.setdefault(entry.kind, []).append(entry)
        for kind in ("decision", "alternative_rejected", "pattern_discovered", "reflect_insight"):
            entries = by_kind.get(kind, [])
            if entries:
                lines.append(f"### {kind.replace('_', ' ').title()}")
                for e in entries:
                    evidence = f" (evidence: {', '.join(e.evidence)})" if e.evidence else ""
                    lines.append(f"- {e.description}{evidence}")
                lines.append("")

    # Reflect pass history
    if blueprint.reflect_passes:
        lines.extend(["## Reflect History", ""])
        lines.extend([
            "| Pass | Gaps | Orphans | Cross-ref density | Findings |",
            "|------|------|---------|-------------------|----------|",
        ])
        for rp in blueprint.reflect_passes:
            lines.append(
                f"| {rp.pass_number} | {rp.gap_count} | {rp.orphan_count} "
                f"| {rp.cross_ref_density} | {len(rp.findings)} |"
            )
        lines.append("")

        # Convergence assessment
        if len(blueprint.gap_convergence) >= 2:
            trend = blueprint.gap_convergence
            if all(trend[i] >= trend[i + 1] for i in range(len(trend) - 1)):
                lines.append("**Convergence:** Gap count is decreasing (healthy).")
            elif trend[-1] > trend[0]:
                lines.append("**Warning:** Gap count increased over passes (surface may be degrading).")
            lines.append("")

    # Continuation fragments
    if blueprint.continuation_fragments:
        lines.extend([
            "## Continuation Fragments",
            "",
            "Top insights for the next session:",
            "",
        ])
        for frag in blueprint.continuation_fragments:
            # One-line (mirror the hook cmd_load). NOTE: these engine renders are
            # the non-load-bearing CLI path; BC-033 control-strip closure lives in
            # the HOOK cmd_load (sanitized) + the post_compact typed-integer path,
            # not here (the engine module has no sanitizer, and this output is not
            # fed through session_start's block-bound). Toolbelt frame: BC-033 is
            # defense-in-depth, not a boundary.
            lines.append(f"- {str(frag).replace(chr(10), ' ')}")
        lines.append("")

    # Quality metrics
    if blueprint.cross_ref_density_trend:
        lines.extend([
            "## Quality Metrics",
            f"- Gap convergence: {' → '.join(str(g) for g in blueprint.gap_convergence)}",
            f"- Cross-ref density trend: {' → '.join(str(d) for d in blueprint.cross_ref_density_trend)}",
            "",
        ])

    return "\n".join(lines)


def render_context_load(blueprint: CognitiveBlueprint) -> str:
    """Render the context-load priming document from a blueprint.

    This is what the next session reads at /context-load to inherit
    the prior session's accumulated context.
    """
    lines = [
        f"# Session Context (depth {blueprint.accumulated_depth})",
        "",
        f"Continuing from session `{blueprint.session_id}` ({blueprint.timestamp}).",
        "",
    ]

    if blueprint.continuation_fragments:
        lines.extend([
            "## What the prior session wants you to know",
            "",
        ])
        for frag in blueprint.continuation_fragments:
            # One-line (mirror the hook cmd_load). NOTE: these engine renders are
            # the non-load-bearing CLI path; BC-033 control-strip closure lives in
            # the HOOK cmd_load (sanitized) + the post_compact typed-integer path,
            # not here (the engine module has no sanitizer, and this output is not
            # fed through session_start's block-bound). Toolbelt frame: BC-033 is
            # defense-in-depth, not a boundary.
            lines.append(f"- {str(frag).replace(chr(10), ' ')}")
        lines.append("")

    # Carry forward unresolved gaps
    if blueprint.reflect_passes:
        latest = blueprint.reflect_passes[-1]
        high_gaps = [f for f in latest.findings if f.severity == "high"]
        if high_gaps:
            lines.extend([
                "## Unresolved high-severity findings",
                "",
            ])
            for gap in high_gaps[:5]:
                lines.append(f"- [{gap.kind}] {gap.description}")
            lines.append("")

    # (a) reinjection selection -- pins (any kind) before recent decisions, both
    # newest-first, noise-filtered -- mirrors the hook cmd_load so a pinned
    # best-bit reaches the next session. Next steps is rendered ABOVE the
    # decisions so the session_start block-bound sheds the oldest decisions first.
    _entries = [e for e in blueprint.reasoning_entries if not _is_activity_log(e)]
    _pinned = [e for e in reversed(_entries) if e.carry_forward]
    _recent = [e for e in reversed(_entries)
               if not e.carry_forward and e.kind == "decision"]
    recent_decisions = (_pinned + _recent)[:5]

    lines.extend([
        "## Next steps",
        "",
        "See your GOAL / PROGRESS (cc/GOAL.md, if present) for the curated next "
        "action; the continuation fragments above are your starting context.",
        "",
    ])
    if recent_decisions:
        lines.extend([
            "## Recent reasoning -- pinned + recent decisions "
            "(do not re-litigate without new evidence)",
            "",
        ])
        for d in recent_decisions:
            lines.append(f"- {str(d.description).replace(chr(10), ' ')}")
        lines.append("")

    return "\n".join(lines)
