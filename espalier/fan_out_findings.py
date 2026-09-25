"""Fan-out finding schema + aggregation for multi-agent review/audit workflows.

A *fan-out finding* is the structured shape an LLM review/audit subagent
returns one result in, so a parent orchestrator can aggregate and
adversarially refute across many agents cheaply. ``FINDING_SCHEMA`` is the
single source of truth for that shape — pass it as the ``schema:`` value on a
Workflow ``agent()`` call (StructuredOutput), or as the return contract for a
review subagent dispatched by name.

This is the *agent-finding* wire format. It is distinct from the *mechanical*
finding model (:class:`espalier.models.ReflectFinding`, the reflect pass's
deterministic hit; each scanner carries its own ``*Finding`` dataclass) — see
``memory/fan-out-finding-schema.md`` for why the two are not bridged.

Stdlib-only: the schema is a pure ``dict`` literal (a JSON-Schema draft-2020-12
document); no ``jsonschema`` dependency. Validation here is hand-rolled with
``json``/set ops, matching the repo's prevailing schema-check style.
"""
from __future__ import annotations

import contextlib
import json
import re
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from espalier._atomic_io import atomic_write_text
from espalier.canon_vocab import load_failure_mode_coinages
from espalier._text import os_error_text

# POSIX advisory locking for the corpus read-modify-write window. Absent on
# Windows / flock-less filesystems, where the RMW degrades to best-effort
# unlocked -- the atomic rename in ``atomic_write_text`` still prevents torn
# reads; only the lost-update race is unguarded there. Same precedent as
# ``espalier.freshness._freshness_write_lock`` and
# ``tools/cc/hooks/_integrity.write_manifest``.
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover -- Windows
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

_REFUTATION_OUTCOMES: tuple[str, ...] = ("unattempted", "survived", "refuted")
_SEVERITIES: tuple[str, ...] = ("blocker", "major", "minor", "nit")
_CONFIDENCES: tuple[str, ...] = ("high", "med", "low")
# Permissive id pattern: accepts the legacy ``{path:line}`` handle, the
# namespaced ``TP-N:LABEL`` that doesn't collide across packs,
# and any colon-free token. Enforced at the StructuredOutput layer via the
# schema ``pattern``; ``iter_finding_errors`` stays a light validator and does NOT
# re-check it (an over-strict regex would false-reject real corpus ids on the
# aggregation path — the field is for the future finding->commit join, not dedup).
_ID_PATTERN: str = r"^(?:TP-\d+:[A-Za-z]\w*|[^:]+:\S+|[^:]+)$"
# NOTE: there is deliberately NO module-level FINDING_CATEGORIES constant. The
# category vocabulary is DOMAIN-SUPPLIED (passed to aggregate_findings as
# known_categories), mirroring named_unit/known_units. A hardcoded enum was
# tried and falsified: a blueprint-review vocabulary piled 46% of pack-artifact
# findings into one catch-all bucket. See memory/fan-out-finding-schema.md.

# JSON-Schema (draft 2020-12) describing one fan-out finding. Usable directly
# as a StructuredOutput schema. The markdown reference doc
# (memory/fan-out-finding-schema.md) cites this constant rather than embedding
# the literal, so there is exactly one copy of the shape.
FINDING_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Fan-out finding",
    "description": (
        "One structured result from an LLM review/audit subagent in a "
        "multi-agent fan-out, shaped for cheap aggregation + adversarial "
        "refutation."
    ),
    "type": "object",
    "additionalProperties": False,
    # CORE (required) — what the FINDER must supply; the substance of a finding.
    # The remaining properties are OPTIONAL: accreted downstream by the refuter
    # (refutation_*, corrected_*, externally_verified) or the aggregator
    # (corroboration_count), and absent at finder time. See the lifecycle notes
    # in memory/fan-out-finding-schema.md.
    "required": [
        "id",
        "title",
        "rule_or_scanner",
        "violated_invariant",
        "category",
        "location",
        "claim",
        "minimal_repro",
        "verification",
        "confidence",
        "proposed_fix",
        "severity",
        "blocks_release",
    ],
    "properties": {
        "id": {
            "type": "string",
            "pattern": _ID_PATTERN,
            "description": (
                "stable handle; namespace pack-item ids as TP-N:LABEL "
                "so they don't collide across packs; the legacy "
                "{file}:{line} form is still accepted"
            ),
        },
        "title": {
            "type": "string",
            "description": (
                "a short (<=8-word) label for triage tables / roadmap rows, "
                "distinct from the one-sentence claim"
            ),
        },
        "rule_or_scanner": {
            "type": "string",
            "description": "the lens / agent / scanner that surfaced this finding",
        },
        "violated_invariant": {
            "type": "string",
            "description": "the rule or contract this finding breaks",
        },
        "category": {
            "type": ["string", "null"],
            "description": (
                "coarse aggregation bucket from a DOMAIN-SUPPLIED controlled "
                "vocabulary (validate via aggregate_findings(known_categories=...)), "
                "or null when the finding fits none. NOT a hardcoded enum."
            ),
        },
        "location": {"type": "string", "description": "path:line"},
        "claim": {"type": "string", "description": "one sentence"},
        "minimal_repro": {"type": "string"},
        "verification": {
            "type": "object",
            "additionalProperties": False,
            "required": ["positive", "negative"],
            "properties": {
                "positive": {"type": "string", "description": "catches the bad"},
                "negative": {"type": "string", "description": "clears the good"},
            },
        },
        "confidence": {
            "type": "string",
            "enum": list(_CONFIDENCES),
            "description": (
                "the FINDER's confidence; a refuter may supply corrected_confidence"
            ),
        },
        "proposed_fix": {"type": "string"},
        "severity": {
            "type": "string",
            "enum": list(_SEVERITIES),
            "description": "triage rank; 'blocker' implies blocks_release=true",
        },
        "blocks_release": {
            "type": "boolean",
            "description": (
                "the single canonical release-gate flag (replaces the re-invented "
                "blocks_b1 / blocks_oss_cut / launch_relevance==blocker)"
            ),
        },
        # ---- OPTIONAL: accreted downstream, absent at finder time ----
        "named_unit": {
            "type": ["string", "null"],
            "description": (
                "a docs/FAILURE_MODES.md §1 coinage this finding instantiates "
                "(see espalier.canon_vocab), or null if novel. Optional: a generic "
                "agent without the harness coinage vocabulary simply omits it."
            ),
        },
        "refutation_outcome": {
            "type": "string",
            "enum": list(_REFUTATION_OUTCOMES),
            "description": (
                "adversarial-verify result set by the REFUTER (unattempted | "
                "survived | refuted); absent at finder time"
            ),
        },
        "refutation_reason": {
            "type": "string",
            "description": (
                "the refuter's why-it-survived-or-was-refuted, citing the real "
                "bytes read"
            ),
        },
        "corrected_confidence": {
            "type": "string",
            "enum": list(_CONFIDENCES),
            "description": (
                "the refuter's post-review confidence; overrides confidence for "
                "aggregation when present"
            ),
        },
        "corrected_category": {
            "type": ["string", "null"],
            "description": (
                "the refuter's re-bucketed category; overrides category for "
                "aggregation when the key is present (may re-bucket to null)"
            ),
        },
        "externally_verified": {
            "type": "boolean",
            "description": (
                "true when a non-LLM oracle (grep / test / git / a real run) "
                "confirmed this finding against ground truth -- not merely "
                "LLM-asserted. Operationalizes the untrusted-oracle discipline."
            ),
        },
        "corroboration_count": {
            "type": "integer",
            "minimum": 1,
            "description": (
                "number of independent agents whose findings collapsed to this "
                "one (AGGREGATOR-populated, not agent-supplied); >1 means "
                "independently corroborated"
            ),
        },
    },
}


# Fields whose check combines TYPE and RANGE in one message, so the derived
# type loop in iter_finding_errors must not also fire on them and emit a
# second, weaker error. A range bound is not expressible in the schema shapes
# this validator derives from, so these keep a bespoke check by design.
#
# Defined BELOW FINDING_SCHEMA deliberately: several docs cite that constant by
# line number, and inserting anything above it silently invalidates every one
# of those anchors (test_memory_anchor_freshness reds, in a file the editor had
# no reason to think was involved). Third occurrence of that class this pack --
# see also MAGIC_DEPTH_SITES and _FROZEN_ANCHORS.
_RANGE_CHECKED_FIELDS: frozenset[str] = frozenset({"corroboration_count"})


def iter_finding_errors(finding: object) -> list[str]:
    """Light structural validation of one finding against ``FINDING_SCHEMA``.

    Returns ``[]`` for a conforming finding, else a list of human-readable
    problems. Intentionally not a full JSON-Schema validator (no ``jsonschema``
    dependency) — it checks required keys, no-extra keys, the string enums
    (``confidence``, ``corrected_confidence``, ``severity``,
    ``refutation_outcome``), the ``verification`` sub-object including its
    sub-value types, the nullable-string fields, the boolean flags, and the
    ``corroboration_count`` integer.

    DELIBERATELY NOT ENFORCED here — a decision, not an omission, so the next
    reader does not have to guess which is which:

    * the ``id`` ``pattern`` — lives at the StructuredOutput layer only
      (see ``_ID_PATTERN``).
    * value RANGES — not expressible in the schema shapes derived from here.
      ``corroboration_count``'s ``>= 1`` bound is therefore a named check, and
      the field is listed in ``_RANGE_CHECKED_FIELDS`` so the derived type loop
      does not also fire on it with a weaker message.

    That list is exhaustive. Everything else the schema declares is checked,
    and the checks are derived from ``FINDING_SCHEMA`` rather than restated,
    so a field added to the schema is validated without editing this function.
    A gap that is NOT on the list above is a bug: ``verification.positive`` /
    ``.negative`` were type-unchecked for exactly that reason — presence was
    verified, type was not, and nothing recorded the difference.
    """
    if not isinstance(finding, dict):
        return ["finding is not an object"]
    props = FINDING_SCHEMA["properties"]
    errors: list[str] = []
    for key in FINDING_SCHEMA["required"]:
        if key not in finding:
            errors.append(f"missing required field: {key}")
    for key in finding:
        if key not in props:
            errors.append(f"unexpected field: {key}")
    # Required string-typed fields must actually be strings: the dedupe key
    # (location, claim) and routing rely on it, and a null/non-str value slips
    # past the presence check otherwise. Derived from the schema (plain
    # type == "string"; enum and string-or-null fields are checked separately).
    for prop_key, prop_spec in props.items():
        if prop_spec.get("type") == "string" and "enum" not in prop_spec:
            if prop_key in finding and not isinstance(finding[prop_key], str):
                errors.append(f"{prop_key} must be a string")
    if "confidence" in finding and finding["confidence"] not in _CONFIDENCES:
        errors.append(f"confidence not in enum: {finding['confidence']!r}")
    if (
        "corrected_confidence" in finding
        and finding["corrected_confidence"] not in _CONFIDENCES
    ):
        errors.append(
            f"corrected_confidence not in enum: {finding['corrected_confidence']!r}"
        )
    if "severity" in finding and finding["severity"] not in _SEVERITIES:
        errors.append(f"severity not in enum: {finding['severity']!r}")
    # Nullable-string, boolean and integer fields, all DERIVED from the schema
    # exactly as the plain-string loop above is. These were three hand-kept
    # tuples restated beside the schema they describe — the same shape this
    # module's docstring claims not to have, and the reason a boolean or
    # integer field added to FINDING_SCHEMA would have been accepted with any
    # type at all: it is a declared property, so the no-extra-keys check lets
    # it through, and nothing else looked at it.
    for prop_key, prop_spec in props.items():
        if prop_key not in finding or prop_key in _RANGE_CHECKED_FIELDS:
            continue
        spec_type = prop_spec.get("type")
        value = finding[prop_key]
        if spec_type == ["string", "null"] and not (
            value is None or isinstance(value, str)
        ):
            errors.append(f"{prop_key} must be a string or null")
        # bool is a subclass of int, so isinstance(x, bool) is the precise test
        # for a flag (an int 1 must NOT pass) and the explicit bool rejection
        # below is required for an integer (True must NOT pass as a count).
        elif spec_type == "boolean" and not isinstance(value, bool):
            errors.append(f"{prop_key} must be a boolean")
        elif spec_type == "integer" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            errors.append(f"{prop_key} must be an integer")
    if "corroboration_count" in finding and (
        isinstance(finding["corroboration_count"], bool)
        or not isinstance(finding["corroboration_count"], int)
        or finding["corroboration_count"] < 1
    ):
        errors.append("corroboration_count must be an integer >= 1")
    if (
        "refutation_outcome" in finding
        and finding["refutation_outcome"] not in _REFUTATION_OUTCOMES
    ):
        errors.append(
            f"refutation_outcome not in enum: {finding['refutation_outcome']!r}"
        )
    if "verification" in finding:
        verification = finding["verification"]
        if not isinstance(verification, dict):
            errors.append("verification must be an object")
        else:
            # Derived from the verification sub-schema, not a hand-kept copy
            # of ("positive", "negative"): the tuple used to be repeated at
            # every check below, so a sub-schema field added later would be
            # silently unvalidated in all of them.
            sub_spec = props["verification"]
            sub_props = sub_spec.get("properties", {})
            for sub in sub_spec.get("required", ()):
                if sub not in verification:
                    errors.append(f"verification.{sub} missing")
            # additionalProperties:false INSIDE verification too (mirror the
            # top-level unexpected-field check). The real schema + the
            # StructuredOutput layer reject extra sub-keys; without this the
            # light validator counts an injected verification sub-key as valid.
            for key in verification:
                if key not in sub_props:
                    errors.append(f"verification unexpected field: {key!r}")
            # Sub-VALUE types, derived exactly as the top-level string loop
            # derives from `props`. Presence was checked here and type was
            # not, so a finding with verification.positive = 1 and
            # .negative = None returned zero errors, counted as `valid`, and
            # flowed on into dedup, corroboration and the persisted corpus --
            # even though the StructuredOutput layer would have rejected it.
            for sub, spec in sub_props.items():
                if (
                    spec.get("type") == "string"
                    and sub in verification
                    and not isinstance(verification[sub], str)
                ):
                    errors.append(f"verification.{sub} must be a string")
    return errors


@dataclass(frozen=True, slots=True)
class FindingsSummary:
    """Aggregated view over a fan-out's findings (see :func:`aggregate_findings`)."""

    total: int
    valid: int
    invalid: int
    unique: int
    duplicates: int
    corroborated: int
    externally_verified: int
    by_category: dict
    by_confidence: dict
    by_refutation_outcome: dict
    survival_rate: float | None
    unknown_named_units: list
    vocab_checked: bool
    unknown_categories: list
    categories_checked: bool
    findings: list


# A stored resolution annotation, normalized OUT of the dedup key. A bulk
# migration prefixed ``**[RESOLVED ...]**`` INTO the claim text of part of the
# corpus, and the claim IS the key's third element — so a fresh re-find of an
# annotated defect keys differently from the stored entry and re-appends as new,
# forever. Stripping it for KEY PURPOSES ONLY makes the two sides agree again.
#
# NON-GREEDY (``.*?``) to the FIRST ``]**``, deliberately: an annotation whose body
# contains a ``]`` is real and present, and a negated class ``[^\]]*`` silently
# misses exactly one live entry — the one whose body holds ``cleaned[2:]``. That
# single miss is this normalization's own subject in miniature: a hand-written
# pattern failing on the one input that contains its delimiter.
#
# MONOTONIC BY CONSTRUCTION: a freshly-found finding never carries the annotation,
# so stripping can only MERGE two keys that should have been one, never SPLIT one
# into two. Nothing that binds today comes unbound. The corpus grammar — the file,
# the bullet regex, the renderer — is untouched.
_KEY_ANNOTATION_RE = re.compile(r"^\s*\*\*\[(?:RESOLVED|FIXED)\b.*?\]\*\*\s*", re.S)


def _dedupe_key(f: dict) -> tuple:
    """The dedup identity of a finding, shared by :func:`aggregate_findings` and
    the corpus persister so both agree on what 'the same finding' is.

    The (location, named_unit) and (location, claim) keyspaces are namespace-
    tagged DISJOINT — else a coinage string equal to another finding's claim
    collides and silently collapses two distinct findings.

    The claim is keyed with any stored resolution annotation normalized out (see
    :data:`_KEY_ANNOTATION_RE`), so an annotated stored entry and its bare re-find
    share one key instead of accreting a duplicate on every round.
    """
    unit = f.get("named_unit")
    # Falsy (None OR "") means "no unit": an empty-string named_unit must route
    # to the (location, claim) branch, not the (location, "") branch — else two
    # distinct co-located findings with named_unit="" collapse to a single
    # ("U", location, "") key.
    if unit:
        return ("U", f.get("location"), unit)
    claim = f.get("claim")
    # isinstance-guarded: a malformed payload may carry a non-str claim, and this
    # function must key it rather than raise — the callers treat a key as total.
    if isinstance(claim, str):
        claim = _KEY_ANNOTATION_RE.sub("", claim)
    return ("C", f.get("location"), claim)


def _unknown_against_vocab(findings, known_vocab, extract):
    """Values (case-insensitive) absent from ``known_vocab``, first-seen casing
    kept for display, normalized-deduped. ``extract(finding)`` returns the value
    to test (or a falsy/non-str sentinel to skip). Single-owns the dedupe shape
    the named-unit and category scans both need so the two can't hand-mirror drift.
    """
    known = {v.strip().lower() for v in known_vocab}
    seen_norm: set = set()
    out: list = []
    for finding in findings:
        value = extract(finding)
        if not value or not isinstance(value, str):
            continue
        norm = value.strip().lower()
        if norm in known or norm in seen_norm:
            continue
        seen_norm.add(norm)
        out.append(value)
    return sorted(out)


def _dedupe_with_corroboration(valid):
    """Dedupe valid findings (first occurrence wins) and attach
    ``corroboration_count`` to a COPY of each survivor (never mutates input).
    Returns ``(unique_findings, corroborated)``.

    This multiplicity was previously computed (the ``duplicates`` total) and
    discarded; preserving it per-finding lets synthesis rank by independent
    discovery, a stronger signal than any single agent's confidence.
    """
    seen: dict = {}
    order: list = []
    counts: dict = {}
    for finding in valid:
        key = _dedupe_key(finding)
        counts[key] = counts.get(key, 0) + 1
        if key not in seen:
            seen[key] = finding
            order.append(key)
    unique_findings = []
    for key in order:
        survivor = dict(seen[key])
        survivor["corroboration_count"] = counts[key]
        unique_findings.append(survivor)
    corroborated = sum(
        1 for f in unique_findings if f["corroboration_count"] > 1
    )
    return unique_findings, corroborated


def aggregate_findings(
    findings: list, *, known_units: object = None, known_categories: object = None
) -> FindingsSummary:
    """Collapse a fan-out's findings into a summary for triage.

    Input is partitioned through :func:`iter_finding_errors` first: only
    schema-valid dict findings are aggregated (``valid``); malformed elements
    (non-dict, missing/extra keys, bad enums) land in ``invalid`` rather than
    crashing the batch — the documented use case is aggregating many independent
    LLM returns, where one may be malformed.

    - **Dedupe** the valid findings, first occurrence wins. The key is
      ``(location, named_unit)`` when ``named_unit`` is set (the routing case),
      else ``(location, claim)`` so two distinct novel findings at the same
      location are not silently collapsed. Each survivor (a copy — the caller's
      input is never mutated) carries ``corroboration_count`` = how many
      independent findings collapsed to it; ``>1`` means independently
      corroborated, the strongest real-vs-hallucinated signal a fan-out gives.
      ``corroborated`` counts the survivors with ``corroboration_count > 1``.
    - **Count** the deduped findings by ``category`` and ``confidence`` using the
      EFFECTIVE (post-refutation) value — a refuter's ``corrected_category`` /
      ``corrected_confidence`` overrides the finder's original when present — and
      by ``refutation_outcome`` (raw). ``externally_verified`` counts survivors a
      non-LLM oracle confirmed.
    - **survival_rate** = survived / (survived + refuted); ``None`` when nothing
      was contested (distinguishes 'no refuter ran' from 'all refuted'). A
      degenerate refuter that never overturns anything still reads 1.000 — this
      is a signal about refuter outcomes, not a guarantee of finding quality.
    - **Unknown named units / categories** = values (case-insensitive) absent
      from the supplied vocabulary. ``known_units=None`` loads the harness
      coinage set (degrading to ``vocab_checked=False`` if unreadable);
      ``known_categories=None`` simply skips the category check
      (``categories_checked=False``) — there is no canonical category SoT.
    """
    findings = list(findings)
    total = len(findings)
    valid = [f for f in findings if isinstance(f, dict) and not iter_finding_errors(f)]
    invalid = total - len(valid)

    unique_findings, corroborated = _dedupe_with_corroboration(valid)
    unique = len(unique_findings)

    # Aggregate on the EFFECTIVE (post-refutation) value: a refuter's
    # corrected_* overrides the finder's original when the key is present (so a
    # refuter may even re-bucket category to null), so the distribution reflects
    # the reviewed state, not the first guess.
    def _eff_category(f: dict):
        return f["corrected_category"] if "corrected_category" in f else f.get("category")

    def _eff_confidence(f: dict):
        if "corrected_confidence" in f:
            return f["corrected_confidence"]
        return f.get("confidence", "")

    by_category = Counter(_eff_category(f) for f in unique_findings)
    by_confidence = Counter(_eff_confidence(f) for f in unique_findings)
    externally_verified = sum(
        1 for f in unique_findings if f.get("externally_verified") is True
    )

    by_outcome = Counter(f.get("refutation_outcome", "") for f in unique_findings)
    contested = by_outcome.get("survived", 0) + by_outcome.get("refuted", 0)
    survival_rate = by_outcome.get("survived", 0) / contested if contested else None

    if known_units is None:
        try:
            known_units = load_failure_mode_coinages()
        except (FileNotFoundError, ValueError, OSError):
            known_units = None

    vocab_checked = known_units is not None
    unknown: list = []
    if vocab_checked:
        unknown = _unknown_against_vocab(
            unique_findings, known_units, lambda f: f.get("named_unit")
        )

    # Same DOMAIN-SUPPLIED-vocab dedupe as named units, via the shared
    # _unknown_against_vocab helper (single-owns the case-insensitive normalized
    # dedupe — replaces the hand-mirrored loop the 5fe6a69 comment warned about).
    categories_checked = known_categories is not None
    unknown_categories: list = []
    if categories_checked:
        unknown_categories = _unknown_against_vocab(
            unique_findings, known_categories, _eff_category
        )

    return FindingsSummary(
        total=total,
        valid=len(valid),
        invalid=invalid,
        unique=unique,
        duplicates=len(valid) - unique,
        corroborated=corroborated,
        externally_verified=externally_verified,
        by_category=dict(by_category),
        by_confidence=dict(by_confidence),
        by_refutation_outcome=dict(by_outcome),
        survival_rate=survival_rate,
        unknown_named_units=unknown,
        vocab_checked=vocab_checked,
        unknown_categories=unknown_categories,
        categories_checked=categories_checked,
        findings=unique_findings,
    )


# ---------------------------------------------------------------------------
# Persisting findings to a markdown findings file: a fan-out round's per-round
# report under reports/. The shared cross-round dedup corpus this section once
# wrote by default (a tracked file under docs/, now on the record branch) was
# retired 2026-09-21 -- a survivor reaches the forward ledger only through a
# verify pass, never by append.
#
# The file is human-readable markdown: one bullet per finding, grouped under
# a ``## SURVIVED`` / ``## REFUTED`` heading. It stores only ``location`` + the
# one-line ``claim`` — NOT named_unit or the full schema — so corpus dedup is
# keyed on (location, claim), the projection that survives the round-trip.
# ``_corpus_dedupe_key`` reuses ``_dedupe_key`` for that, so the persisted
# corpus and the live aggregator agree on identity.
# ---------------------------------------------------------------------------

# A corpus bullet: ``- `<location>` [<severity>] <claim>``. Severity is optional
# (the seeded REFUTED entries carry none); the location is the first backticked
# token, the claim is the trailing prose (may itself contain backticks).
#
# The severity group is constrained to the KNOWN severity words, NOT ``[^\]]+``:
# a claim that itself begins with a bracket (``[State: LANDED] but x is OWED`` —
# the shape the landing-audit finder emits) would otherwise be mis-read AS the
# severity on the dedup round-trip. The stored entry re-renders WITHOUT its real
# ``[severity]`` (``_parse_corpus_findings`` recovers only location+claim),
# which exposes the claim's leading bracket to the severity group, so the key
# diverges from the fresh finding's and the entry re-appends every run (corpus
# inflation). ``critical`` is a legacy severity in the seeded corpus; the rest
# track ``_SEVERITIES`` so the parser never drifts from the schema.
_CORPUS_SEVERITIES = "|".join(re.escape(s) for s in (*_SEVERITIES, "critical"))
_CORPUS_BULLET_RE = re.compile(
    rf"^- `(?P<location>[^`]+)`(?: \[(?P<severity>{_CORPUS_SEVERITIES})\])? ?(?P<claim>.*)$"
)
# Bound on ``_parse_corpus_findings``'s split-bullet recovery scan. A pre-fix
# newline in ``location`` split a bullet across exactly two physical lines, so
# any real case closes on the first continuation; the slack absorbs a location
# that carried several newlines. It exists to stop an unterminated backtick from
# joining unbounded prose into a fabricated entry.
_MAX_CORPUS_BULLET_CONTINUATION_LINES = 10


def _corpus_dedupe_key(f: dict) -> tuple:
    """Corpus identity for a finding: keyed on what survives the markdown
    round-trip (render -> parse).

    Called on a FRESH finding only. It renders the would-be-written bullet (the
    full finding, severity included — exactly what ``append_findings_to_corpus``
    writes) and parses it back, so the key is keyed on what survives the
    render->parse round-trip — robust to trailing/collapsed whitespace, embedded
    newlines in EITHER single-line field (both of which ``_render_finding_bullet``
    now collapses — it collapsed only ``claim`` until the ``location`` half landed,
    and the gap made a newline-bearing location re-append forever), and a backtick
    in a field (which ``_CORPUS_BULLET_RE`` truncates). The seen-set side does NOT call
    this: a parsed corpus entry is ALREADY ``parse(written-bullet)``, so it is
    keyed directly via :func:`_dedupe_key` (re-rendering it would move a real
    ``[severity]`` bracket and desync it from this fresh side — the
    corpus-double-write-on-re-run bug). Reuses :func:`_dedupe_key` on the
    projection (always its (location, claim) branch — named_unit is not stored in
    the markdown).
    """
    roundtrip = _parse_corpus_findings(_render_finding_bullet(f))
    if roundtrip:
        return _dedupe_key(roundtrip[0])
    # Degenerate finding (empty/whitespace location or claim -> unparseable
    # bullet). This USED to fall back to the raw projection — a key no parsed
    # corpus entry can ever equal, i.e. "re-appends forever", expressed silently.
    #
    # That silence is the bug class this module exists to end, so it RAISES now.
    # Raising is safe because the only production caller guards the shape first:
    # append_findings_to_corpus rejects an empty/whitespace/backtick-only location
    # before it ever asks for a key. The raise therefore fires on PROGRAMMER ERROR
    # — a new caller that skipped the guard — never on data flowing the intended
    # path. A future caller that genuinely needs tolerance must ask for it
    # explicitly, which is a visible decision rather than an inherited one.
    #
    # History worth keeping: a newline-bearing location once passed the guard
    # (``"a\nb".strip()`` is truthy), rendered a split bullet, round-tripped to [],
    # and landed here — re-appending every run. The renderer now collapses
    # ``location``, so that shape no longer reaches this branch. Keep the guard and
    # the collapse in agreement; a field that can reach a bullet unnormalised
    # re-opens the hole, and now does so loudly instead of quietly.
    raise ValueError(
        "finding does not survive the corpus round-trip and would re-append on "
        f"every run: location={f.get('location')!r}. append_findings_to_corpus's "
        "guard rejects this shape before it persists; a caller reaching here has "
        "bypassed that guard."
    )


def _parse_corpus_findings(text: str) -> list:
    """Parse a markdown findings file back into minimal finding dicts.

    Recovers only the fields the corpus stores — ``location`` and ``claim`` —
    one per matched bullet. Non-bullet lines (headings, blockquote, blanks) are
    skipped.

    RECOVERY OF PRE-FIX SPLIT BULLETS. ``_render_finding_bullet`` now collapses
    newlines in ``location``; it did not always, so a corpus may already hold an
    entry written across TWO physical lines. Such an entry matches nothing
    line-by-line, so it never enters the caller's seen-set and re-appends on every
    run while inflating the section's ``(N)``. The continuation scan below
    salvages one by joining the split lines on a single space — the SAME
    normalisation the fixed renderer applies — so a recovered entry keys
    identically to a freshly-rendered one and the re-append stops. Sanitizing on
    write cannot do this on its own: it prevents new corruption and leaves
    existing corruption immortal.

    The scan is deliberately bounded — it stops at a blank line, a heading, the
    start of another bullet, or :data:`_MAX_CORPUS_BULLET_CONTINUATION_LINES`.
    An unbounded join would swallow neighbouring entries and silently shrink the
    corpus, which is a worse failure than the one it repairs.
    """
    out = []
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        m = _CORPUS_BULLET_RE.match(line)
        if m is None and line.startswith("- `") and "`" not in line[3:]:
            # Unterminated location backtick: a candidate pre-fix split bullet.
            joined = line
            window = lines[i + 1 : i + 1 + _MAX_CORPUS_BULLET_CONTINUATION_LINES]
            for nxt in window:
                stripped = nxt.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("- `"):
                    break
                joined = f"{joined} {stripped}"
                if "`" in stripped:
                    m = _CORPUS_BULLET_RE.match(joined)
                    break
        if m:
            out.append(
                {"location": m.group("location"), "claim": m.group("claim").strip()}
            )
    return out


def _normalize_location(value) -> str:
    """Normalize a ``location`` into a form that survives the corpus bullet's own
    backtick delimiters.

    TWO normalisations, both load-bearing, both about the SAME failure — a bullet
    that ``_CORPUS_BULLET_RE`` cannot match never enters the seen-set and
    re-appends on every run:

    * **Whitespace collapse.** A bullet is one physical line by construction; a
      newline splits it in two and the regex matches neither half.
    * **LEADING backtick removal.** ``location`` is written between backticks, so
      a backtick inside it collides with the delimiter — but the two positions
      fail differently, and only one of them is a defect. An INTERIOR backtick
      truncates the field, and that is survivable by design: the dedup key is
      taken from the render->parse round-trip, so the fresh side and the stored
      side agree on the truncated value (``test_idempotent_location_with_backtick``
      pins it). A LEADING one is not survivable: the bullet renders ``- ``x`` …``,
      where ``[^`]+`` has no character to match, so it parses to NOTHING and
      re-appends forever. Measured against a temp corpus: three appends of one
      such finding returned ``[1, 1, 1]`` with ``_parse_corpus_findings``
      recovering ``0`` entries.

    Deliberately narrow — strip the LEADING run only, never every backtick.
    Removing all of them looks tidier and is wrong: the per-round reports under
    ``reports/`` are immutable records already rendered with truncated locations,
    so a corpus keyed on the de-backticked form no longer binds to them.
    Measured against a real review report: the broad version left 10 of its 151
    survivors unbound under the report-to-corpus binding test (retired with the
    shared corpus, 2026-09-21). Match the net to the hole.

    Shared with :func:`append_findings_to_corpus`'s degenerate-finding guard ON
    PURPOSE. The guard used to test the RAW value while the renderer normalised,
    so a location the renderer could empty (``"``"``) still passed — the exact
    guard/normalisation disagreement the ``location``-newline hole was made of.
    One function, both callers, no gap to re-open.
    """
    return re.sub(r"^[`\s]+", "", " ".join(str(value or "").split()))


def _render_finding_bullet(f: dict) -> str:
    """Render one finding as a corpus bullet: ``- `<location>` [<sev>] <claim>``.

    BOTH single-line fields collapse their whitespace. A bullet is a single line
    by construction, so a newline in either field would split it across two
    physical lines — which ``_CORPUS_BULLET_RE`` then matches neither half of,
    making the entry permanently invisible to dedup and re-appended on every run.
    ``location`` additionally sheds a LEADING backtick run — see
    :func:`_normalize_location` for why interior ones are left alone.
    """
    location = _normalize_location(f.get("location"))
    severity = f.get("severity")
    claim = " ".join((f.get("claim") or "").split())  # collapse any newlines
    sev = f" [{severity}]" if severity else ""
    return f"- `{location}`{sev} {claim}".rstrip()


def _bump_heading_count(heading: str, delta: int) -> str:
    """Increment the first ``(N)`` count in a section heading by ``delta``.

    No-op when the heading carries no parenthesised count.
    """
    m = re.search(r"\((\d+)\)", heading)
    if not m:
        return heading
    new = int(m.group(1)) + delta
    return heading[: m.start(1)] + str(new) + heading[m.end(1) :]


def _warn_never_raise(message: str) -> None:
    """Emit a ``RuntimeWarning`` that CANNOT become an exception.

    ``warnings.warn`` obeys the ambient filter list, and ``-W error`` /
    ``PYTHONWARNINGS=error`` / a ``filterwarnings = ["error"]`` in pyproject all
    turn every warning into a raise. For a channel whose entire contract is
    "report, never raise", inheriting that setting converts the report INTO the
    failure it was built to report on — and it does so in the fallback handler,
    outside any ``try``, where it propagates to a caller with no reason to expect
    it. Forcing a local filter is what makes the contract structural instead of
    conditional on how the process was launched.

    ``catch_warnings`` saves and restores the filter list only; it leaves
    ``showwarning`` alone, so an enclosing ``catch_warnings(record=True)`` (and
    therefore ``pytest.warns``) still captures what is emitted here.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.warn(message, RuntimeWarning, stacklevel=4)


def _report_unbound_after_write(path, expected_keys) -> list:
    """Re-parse the just-written corpus and REPORT any appended finding that does
    not come back under its own dedupe key. Returns the unbound keys.

    WHY POST-WRITE. The writer's dedup runs against what it *read*; nothing
    verified what it *wrote*. A finding rendered to a bullet the parser cannot
    read back is stored but unfindable — so the next round re-finds it, re-appends
    it, and reports it as new. That is invisible from the writer's own return
    value, which counts what it *meant* to append.

    REPORTS, NEVER RAISES — and structurally, not by good intentions:

    * The expected keys are the ones computed BEFORE the write and handed in, so
      this never calls ``_corpus_dedupe_key`` (which raises on a degenerate
      finding). The re-parsed side goes through ``_dedupe_key``, which has no
      error path at all.
    * The whole body is wrapped anyway. A verification step that can throw would
      destroy the very thing it is verifying — the round's survivors are already
      on disk, and an exception here would propagate out of a function whose
      caller has no reason to expect one. Belt and braces, because the failure it
      guards against is exactly "the instrument loses its own output".
    * Both reports go through :func:`_warn_never_raise`, so an ambient
      warnings-as-error filter cannot turn either of them into the exception this
      function promises never to produce. The fallback report is the one that
      matters: it lives OUTSIDE the ``try`` by necessity, so a bare
      ``warnings.warn`` there would escape under ``-W error``.
    """
    try:
        written = _parse_corpus_findings(path.read_text(encoding="utf-8"))
        reparsed = {_dedupe_key(entry) for entry in written}
        unbound = [k for k in expected_keys if k not in reparsed]
        if unbound:
            _warn_never_raise(
                f"{len(unbound)} of {len(expected_keys)} finding(s) appended to "
                f"{path} did not re-parse under their own dedupe key and will be "
                f"re-appended on the next run: {unbound[:5]!r}"
                f"{' …' if len(unbound) > 5 else ''}"
            )
        return unbound
    except Exception as exc:  # noqa: BLE001 — see the contract above: never raise.
        _warn_never_raise(
            f"post-write corpus verification failed for {path} ({os_error_text(exc)}); the "
            "append itself succeeded and is unaffected."
        )
        return []


@contextlib.contextmanager
def _corpus_write_lock(path: Path):
    """Serialize one corpus's read-modify-write window across processes.

    WHY A LOCK AT ALL. :func:`append_findings_to_corpus` reads the whole file,
    splices, and ``os.replace``s it. That is an atomic *replace*, not an atomic
    *update*: two rounds can both read, both compute against the same
    pre-state, and both replace — the first writer's appends vanish with no
    error while BOTH report success. That is the "review instrument loses its
    own output" failure with a new cause, and it became reachable the moment
    the corpus gained an automated caller. A human running a migration twice,
    by hand, never ran two at once; the code now must supply the mutual
    exclusion the human was silently providing.

    WHY A SIBLING DOTFILE rather than ``.espalier/``. The two precedents
    (``.espalier/.manifest.write.lock``, ``.espalier/.freshness.write.lock``)
    guard manifests at fixed repo-root-relative paths, so a repo-root-anchored
    sentinel fits. This writer takes an ARBITRARY path — the per-round report
    under ``reports/`` is the production caller, and any path can be handed in —
    and has no repo root to anchor to. A sibling keyed to the file being
    written is also strictly more correct: two DIFFERENT corpora do not
    serialize against each other.

    WHY NOT FLOCK THE CORPUS ITSELF. ``atomic_write_text`` replaces the file by
    rename, so the inode a second process holds a lock on is not the inode that
    survives. A separate sentinel is what makes flock-plus-rename sound — the
    same reason both precedents use one.

    NEVER RAISES ON A LOCK IT CANNOT TAKE. A round losing its survivors to a
    locking failure would be the very failure this guards against, so every
    unavailable path yields UNLOCKED rather than erroring. There are THREE such
    paths, not two — the third is the one that is easy to miss: ``flock`` itself
    raises ``OSError`` (ENOTSUP / ENOLCK) on flock-less mounts (NFS, SMB, some
    FUSE and bind mounts), so importing ``fcntl`` successfully does not mean the
    syscall works. ``tools/cc/execution_plan.py`` and four sibling hook modules
    all guard the syscall; guard it here too.

    Each degrade path WARNS. A lock that is silently never taken is a mechanism
    with no reader, which is the same defect the persist payload's warnings
    array exists to close — and on Windows the unlocked path is every run,
    forever. The warning rides the channel the persisters already capture.
    """
    if not _HAS_FCNTL:
        _warn_never_raise(
            f"corpus lock unavailable for {path} (no fcntl on this platform); "
            "the read-modify-write is UNLOCKED — concurrent rounds can lose "
            "appends."
        )
        yield
        return
    lock_path = path.parent / f".{path.name}.write.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = open(lock_path, "a+", encoding="utf-8")
    except OSError as exc:
        _warn_never_raise(
            f"corpus lock file {lock_path} could not be opened ({os_error_text(exc)}); the "
            "read-modify-write is UNLOCKED."
        )
        yield
        return
    acquired = False
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        acquired = True
    except OSError as exc:
        # flock-less filesystem. Degrade to an unlocked RMW rather than costing
        # the round its survivors -- but say so.
        _warn_never_raise(
            f"flock is unsupported for {lock_path} ({os_error_text(exc)}); the "
            "read-modify-write is UNLOCKED."
        )
    try:
        yield
    finally:
        try:
            # Only unlock what was actually locked: on the degrade path above,
            # LOCK_UN would raise the very OSError this contract promises never
            # to produce -- out of a `finally`, where it would mask anything the
            # body raised.
            if acquired:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)
        finally:
            lock_fh.close()


def append_findings_to_corpus(
    corpus_path,
    findings,
    *,
    section: str = "SURVIVED",
    require_existing: bool = False,
) -> int:
    """Append genuinely-new findings to a markdown findings file (a round's
    per-round report); return the count actually appended.

    Findings already present (same :func:`_corpus_dedupe_key` as a parsed corpus
    bullet) and intra-batch duplicates are dropped, so re-running a review is
    idempotent. New findings are rendered as bullets at the end of the named
    ``section`` (``SURVIVED`` / ``REFUTED``), the section's ``(N)`` count is
    bumped, and the section is created at EOF if absent. The write is atomic.

    A finding without a non-empty string ``location`` AND ``claim`` is skipped:
    those are the only two fields a bullet stores, and persisting a degenerate
    ``- `` [sev] ...`` / claimless bullet would corrupt the corpus (and break its
    own re-parse). ``iter_finding_errors`` permits empty strings, so the check
    lives here. ``location`` is tested through :func:`_normalize_location` — the
    SAME normalisation the renderer applies — so a value the renderer would empty
    (``"`"``) is rejected here rather than written as an unparseable bullet.

    ``corpus_path`` is an explicit path (no cwd-relative default — callers
    resolve it against the repo root). There is no shared default: the
    cross-round dedup corpus this writer once fed was retired 2026-09-21.

    ``require_existing`` refuses to CREATE the file, raising
    :class:`FileNotFoundError` naming the resolved path and the cwd. Pass it
    from any caller writing a file that must already be present; leave it off
    for callers whose file is legitimately new each round (the per-round
    report, the only production caller). See the comment at the check for why
    creating-by-accident is the failure worth a hard stop.

    After the write, :func:`_report_unbound_after_write` re-parses the file and
    WARNS about any appended finding that does not come back under its own dedupe
    key (it would otherwise be re-appended on every subsequent run). That check
    only reports — it never raises and never changes this function's return value.
    """
    path = Path(corpus_path)
    if require_existing and not path.exists():
        # WHY THIS IS OPT-IN RATHER THAN THE RULE. Two caller shapes exist and
        # they have OPPOSITE correct behaviour on a missing file:
        #
        #   * The per-round report (``reports/<round>.md``) is NEW every round.
        #     Creating it is the whole point, so it must keep the default.
        #   * A file that must already be present (the shared cross-round
        #     corpus was one, until it was retired 2026-09-21) cannot
        #     legitimately be absent, so absence means the
        #     caller resolved a relative path against the wrong working
        #     directory — and ``atomic_write_text`` calls
        #     ``mkdir(parents=True, exist_ok=True)``, so that does not error:
        #     it silently FORKS a second corpus, writes every survivor into it,
        #     and returns a success count. The round reports 151 appended and
        #     the real corpus never changes. Nothing downstream can tell.
        #
        # Resolved path and cwd both go in the message because the whole class
        # of bug is "I do not know where this actually wrote."
        import os

        raise FileNotFoundError(
            f"corpus `{path}` does not exist (resolved to "
            f"{path.resolve()}; cwd is {os.getcwd()}). This caller passed "
            f"require_existing=True, meaning it targets a file that "
            f"must already be present — so an absent file is a wrong-working-"
            f"directory bug, not a first run. Refusing to create a second "
            f"corpus that nothing reads."
        )
    with _corpus_write_lock(path):
        return _append_within_lock(path, findings, section)


def _append_within_lock(path: Path, findings, section: str) -> int:
    """The corpus read-modify-write itself. Split out of
    :func:`append_findings_to_corpus` ONLY so the lock can wrap read THROUGH
    post-write verification without re-indenting the whole body — the seam is
    mechanical, not a boundary anyone should call across.

    THE LOCK MUST SPAN THE WHOLE OF THIS FUNCTION. The lost-update window opens
    at ``path.read_text`` below and does not close until ``atomic_write_text``
    has landed; a lock held only across the write closes nothing.

    THE POST-WRITE RE-READ IS DELIBERATELY INSIDE IT TOO, and the choice is
    recorded rather than left implicit. Outside the lock, another round
    can complete a full read-modify-write between our write and our re-read.
    That case is *survivable* — a round that read after our write produces a
    superset, so our keys still re-parse — but it is survivable only by an
    ordering argument the next reader of this code would have to reconstruct,
    and the docstring of :func:`_report_unbound_after_write` promises it
    re-parses *the just-written corpus*. Inside the lock the interleaving
    cannot occur at all, and the cost is one file read while holding a lock
    nobody contends for in the common case.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    # A parsed corpus entry is ALREADY ``parse(written-bullet)`` (location+claim,
    # no severity), so it is keyed DIRECTLY via _dedupe_key. Re-rendering it (the
    # old ``_corpus_dedupe_key`` path) would re-attach a synthetic bullet without
    # the severity the bullet was written with, moving a claim's leading bracket
    # under the severity slot and desyncing it from the fresh side — the
    # audit-corpus double-write. The fresh side keys via ``_corpus_dedupe_key``,
    # which parses ``render(finding)`` (the would-be-written bullet) the same way.
    seen = {_dedupe_key(f) for f in _parse_corpus_findings(existing)}

    fresh = []
    # The fresh-side keys, captured AS THEY ARE COMPUTED below rather than
    # recomputed after the write. See _report_unbound_after_write: recomputing
    # them would mean calling _corpus_dedupe_key a second time, and that function
    # RAISES on a degenerate finding — turning a verification step into something
    # that can lose the whole batch. Capturing here makes that unreachable.
    fresh_keys = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        location = f.get("location")
        claim = f.get("claim")
        # The isinstance checks are LOAD-BEARING, not belt-and-braces. The old
        # inline `(location or "").split()` raised AttributeError on a non-str;
        # _normalize_location stringifies instead, so a malformed agent payload
        # ({"location": 5}) would render "5" as a bullet if this guard went away.
        if not (
            isinstance(location, str)
            and _normalize_location(location)
            and isinstance(claim, str)
            and claim.strip()
        ):
            continue
        key = _corpus_dedupe_key(f)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(f)
        fresh_keys.append(key)
    if not fresh:
        return 0

    bullets = [_render_finding_bullet(f) for f in fresh]
    lines = existing.splitlines() if existing else []

    heading_re = re.compile(rf"^##\s+{re.escape(section)}\b")
    hidx = next((i for i, ln in enumerate(lines) if heading_re.match(ln)), None)

    if hidx is None:
        # Section absent: create it at EOF (with a blank separator if needed).
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"## {section} ({len(bullets)})")
        lines.append("")
        lines.extend(bullets)
    else:
        lines[hidx] = _bump_heading_count(lines[hidx], len(bullets))
        # Section runs until the next '## ' heading (or EOF).
        eidx = next(
            (i for i in range(hidx + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        # Append after the last non-blank line within the section.
        insert_at = hidx + 1
        for i in range(hidx + 1, eidx):
            if lines[i].strip():
                insert_at = i + 1
        # A section with no bullets yet needs a blank line after its heading.
        prefix = [] if insert_at > hidx + 1 else [""]
        lines[insert_at:insert_at] = prefix + bullets

    atomic_write_text(path, "\n".join(lines) + "\n")
    _report_unbound_after_write(path, fresh_keys)
    return len(fresh)


def finding_schema_json(*, indent: int = 2) -> str:
    """The real FINDING_SCHEMA as JSON, for JS Workflow consumers that cannot
    import Python. Emit on demand (``python -m espalier.fan_out_findings``); do
    NOT commit the output — the constant stays the only copy of the shape.
    """
    return json.dumps(FINDING_SCHEMA, indent=indent, sort_keys=True)


if __name__ == "__main__":
    import sys

    print(finding_schema_json())
    sys.exit(0)

