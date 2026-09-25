"""Audit documented claims against live repo state.

Pipeline:
  claim_extractor.extract_claims()
    → verify_claim() per Claim (mechanical or LLM-dispatch)
    → AuditReport (markdown / json renderer)

The mechanical path is exact, fast, and zero-cost. It handles every
`live_repo` claim (numerical drift in agent/command/hook/test counts).

External-pin verification (claims tagged for cross-check against pinned
external excerpts like ``docs/external/cc-hook-protocol.md``) is
structurally prepared but the LLM-dispatch callable is not currently
registered. External-pin claims report ``unverifiable`` with reason
"LLM dispatch not configured" — this is the *current* coverage shape,
not a TODO. Wiring is tracked as a follow-up pack when external-pin
volume justifies it.

This is the layer the pack calls "Layer 1+2 of the accuracy stack."
Layer 3 (end-to-end behavior tests via real Claude Code subprocesses)
is deferred.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from espalier.claim_extractor import (
    Claim,
    MODE_EXTERNAL_PIN,
    MODE_LIVE_REPO,
    MODE_UNKNOWN,
    extract_claims,
)
from espalier.external_pins import ExternalPin, list_pins_lenient

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_UNVERIFIABLE = "unverifiable"

MODE_FRESHNESS = "freshness"


@dataclass(frozen=True)
class ClaimVerdict:
    """Result of verifying one claim against evidence."""

    claim_id: str
    location: str
    claim_text: str
    verification_mode: str
    verdict: str
    evidence: str
    evidence_source: str

    @classmethod
    def from_claim(
        cls,
        claim: Claim,
        *,
        verification_mode: str,
        verdict: str,
        evidence: str,
        evidence_source: str,
    ) -> "ClaimVerdict":
        """Build a verdict for a real extracted claim, filling claim_id /
        location / claim_text from the claim.

        The synthetic-id verdicts (freshness::… / external_pin::…) have no
        Claim object and construct ClaimVerdict directly — do not route them
        through this helper.
        """
        return cls(
            claim_id=claim.claim_id,
            location=claim.location,
            claim_text=claim.text,
            verification_mode=verification_mode,
            verdict=verdict,
            evidence=evidence,
            evidence_source=evidence_source,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "location": self.location,
            "claim_text": self.claim_text,
            "verification_mode": self.verification_mode,
            "verdict": self.verdict,
            "evidence": self.evidence,
            "evidence_source": self.evidence_source,
        }


@dataclass(frozen=True, slots=True)
class AuditReport:
    repo_root: Path
    started_at: datetime
    claims_total: int
    claims_passed: int
    claims_failed: int
    claims_unverifiable: int
    verdicts: list[ClaimVerdict]
    elapsed_seconds: float
    llm_calls: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, object]:
        return {
            "repo_root": str(self.repo_root),
            "started_at": self.started_at.isoformat(),
            "claims_total": self.claims_total,
            "claims_passed": self.claims_passed,
            "claims_failed": self.claims_failed,
            "claims_unverifiable": self.claims_unverifiable,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "llm_calls": self.llm_calls,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "verdicts": [v.to_dict() for v in self.verdicts],
        }


# ── Mechanical verifiers (no LLM) ─────────────────────────────────────────────────


def _live_count_hooks(repo_root: Path) -> int:
    hooks_dir = repo_root / "tools" / "cc" / "hooks"
    if not hooks_dir.is_dir():
        return 0
    # Intersect with the canonical roster so a stray non-canonical
    # .py cannot inflate the live hook count (sister-site of doctor._check_doc_drift).
    from espalier import surface_contract
    canonical = set(surface_contract.get_canonical_hook_scripts())
    return len([
        p for p in hooks_dir.glob("*.py")
        if p.name in canonical
    ])


def _live_count_agents(repo_root: Path) -> int:
    # Delegate to surface discovery so the live count and
    # discover_installed_agents can't drift (the latter adds an is_file()
    # guard via _list_dir_relative, which is strictly safer than the bare glob).
    from espalier import surface_contract
    return len(surface_contract.discover_installed_agents(repo_root))


def _live_count_commands(repo_root: Path) -> int:
    # Delegate to surface discovery (see _live_count_agents).
    from espalier import surface_contract
    return len(surface_contract.discover_installed_commands(repo_root))


def _live_count_skills(repo_root: Path) -> int:
    d = repo_root / ".claude" / "skills"
    if not d.is_dir():
        return 0
    return sum(1 for child in d.iterdir() if child.is_dir() and (child / "SKILL.md").exists())


def _live_count_bypass_classes(repo_root: Path) -> int:
    """Count in-scope BC corpus entries. The ``BC-[0-9]*.json`` glob
    excludes the ``BC-OOS-*`` variants by name — matches the convention
    in ``scripts/release_check.py`` (the ``BC-[0-9]*.json`` glob) and the NUMERIC_CONTRACTS SoT
    comment ("OOS variants excluded"). A bare ``BC-*.json`` glob would
    over-count by the OOS variants and make ``audit_accuracy`` disagree
    with ``release_check`` on the same SoT.
    """
    d = repo_root / "bench" / "corpus"
    if not d.is_dir():
        return 0
    return len([p for p in d.glob("BC-[0-9]*.json")])


def _label_word_re(label: str) -> str:
    """Render a regex fragment matching a count label's singular/plural form.

    "commands" -> "command(s?)", "bypass classes" -> "bypass\\s+classes?"
    """
    if label == "bypass classes":
        return r"bypass\s+classes?"
    if label.endswith("s"):
        return re.escape(label[:-1]) + "s?"
    return re.escape(label)


def extract_count_for_label(text: str, label: str) -> int | None:
    """Extract the number that immediately precedes the label.

    The label-anchored regex pins the number to the same span that
    triggered classification, so a stray earlier number on the line (e.g.
    the year-prefix of a date in ``| 2026-05-10 | ... 14 commands now ...``)
    is not mistaken for the claim.

    The leading negative lookbehind ``(?<![./0-9A-Za-z])`` rejects a number
    preceded by another digit, ``/`` (fraction denominator), ``.`` (e.g.
    ``v.10 hooks`` / ``1.10 hooks``), or a letter (``v10 hooks``); multi-digit
    literals are handled by the greedy ``[0-9]+,?[0-9]*``.

    The ``[0-9]`` digit class is ASCII-only: Python's ``\\d`` matches Unicode
    digits including fullwidth forms (``＄`` U+FF14 etc.), so an explicit
    ``[0-9]`` class drops every non-ASCII digit form. The ``re.ASCII`` flag
    forces ``\\b`` to ASCII word semantics so any ``\\w`` / ``\\s`` in the
    pattern stays ASCII-bound.
    """
    word_re = _label_word_re(label)
    # The optional adjective slot ``(?:[a-z\-]+\s+)?`` is DELIBERATELY looser
    # than claim_extractor's bare-noun ``num_*`` patterns, and that asymmetry is
    # load-bearing for the doctor consumer: ``doctor._check_doc_drift`` feeds
    # live doc lines like README's "45 in-scope bypass classes" through
    # ``extract_count_for_label(line, "bypass classes")`` — the slot is what
    # recovers the 45. Dropping the slot to match the extractor would SILENTLY
    # narrow doctor's drift detection (45 -> None; 45 == the live corpus, so
    # nothing would go red), while only closing a two-numbers-on-one-line
    # divergence that has no live trigger. Pinned by
    # test_adjective_slot_is_load_bearing_for_doctor. A genuine alignment must
    # thread the extractor-matched number through the Claim object, not loosen
    # or tighten this regex (deferred: dropping the slot is net-negative).
    full_re = re.compile(
        rf"(?<![./0-9A-Za-z])\b([0-9]+(?:,[0-9]+)?)\s+(?:[a-z\-]+\s+)?{word_re}\b",
        re.IGNORECASE | re.ASCII,
    )
    m = full_re.search(text)
    if m is None:
        return None
    return int(m.group(1).replace(",", ""))


def _verify_count_claim(
    claim: Claim,
    *,
    actual: int,
    label: str,
    source: str,
) -> ClaimVerdict:
    """Compare a numerical claim to a live filesystem count."""
    stated = extract_count_for_label(claim.text, label)
    if stated is None:
        return ClaimVerdict.from_claim(
            claim,
            verification_mode=MODE_LIVE_REPO,
            verdict=VERDICT_UNVERIFIABLE,
            evidence=f"could not parse {label!r} count out of {claim.text!r}",
            evidence_source=source,
        )
    if stated == actual:
        return ClaimVerdict.from_claim(
            claim,
            verification_mode=MODE_LIVE_REPO,
            verdict=VERDICT_PASS,
            evidence=f"{label} count matches: {actual}",
            evidence_source=source,
        )
    return ClaimVerdict.from_claim(
        claim,
        verification_mode=MODE_LIVE_REPO,
        verdict=VERDICT_FAIL,
        evidence=f"claim states {stated} {label}; live count is {actual}",
        evidence_source=source,
    )


_FALSE_POSITIVE_LINE_MARKERS = ("per minute", "per second", "concurrent")


def _verify_against_repo(claim: Claim, repo_root: Path) -> ClaimVerdict:
    """Mechanical verification for live_repo claims. No LLM."""
    text_lower = claim.text.lower()
    if any(s in text_lower for s in _FALSE_POSITIVE_LINE_MARKERS):
        return ClaimVerdict.from_claim(
            claim,
            verification_mode=MODE_LIVE_REPO,
            verdict=VERDICT_UNVERIFIABLE,
            evidence="line contains a phrase that suggests this is not a roster claim",
            evidence_source="none",
        )

    if claim.pattern == "num_hooks":
        return _verify_count_claim(
            claim, actual=_live_count_hooks(repo_root), label="hooks",
            source="tools/cc/hooks/",
        )
    if claim.pattern == "num_agents":
        return _verify_count_claim(
            claim, actual=_live_count_agents(repo_root), label="agents",
            source=".claude/agents/",
        )
    if claim.pattern == "num_commands":
        return _verify_count_claim(
            claim, actual=_live_count_commands(repo_root), label="commands",
            source=".claude/commands/",
        )
    if claim.pattern == "num_skills":
        return _verify_count_claim(
            claim, actual=_live_count_skills(repo_root), label="skills",
            source=".claude/skills/",
        )
    if claim.pattern == "num_bypass_classes":
        return _verify_count_claim(
            claim, actual=_live_count_bypass_classes(repo_root), label="bypass classes",
            source="bench/corpus/",
        )
    if claim.pattern == "num_tests":
        # The "operator docs must not pin an exact test count" rule is ESPALIER'S
        # OWN convention (test_test_suite_contract.py). It must NOT hard-FAIL an
        # ADOPTER whose doc legitimately says e.g. "run the 3 smoke tests" — that
        # cites a harness-internal file they don't have. On a non-self-host repo,
        # report an adopter test-count mention as unverifiable, not a violation.
        from espalier import surface_contract
        if not surface_contract.is_self_host_repo(repo_root):
            return ClaimVerdict.from_claim(
                claim,
                verification_mode=MODE_LIVE_REPO,
                verdict=VERDICT_UNVERIFIABLE,
                evidence="adopter test-count mention; no count convention applies off self-host",
                evidence_source="",
            )
        # Self-host: the convention applies — a surviving "N tests" claim broke it.
        return ClaimVerdict.from_claim(
            claim,
            verification_mode=MODE_LIVE_REPO,
            verdict=VERDICT_FAIL,
            evidence=(
                "operator docs must not pin an exact test count "
                "(see test_test_suite_contract.py); "
                "use marker-based slice guidance instead"
            ),
            evidence_source="tests/test_test_suite_contract.py",
        )

    return ClaimVerdict.from_claim(
        claim,
        verification_mode=MODE_LIVE_REPO,
        verdict=VERDICT_UNVERIFIABLE,
        evidence=f"no mechanical verifier for pattern {claim.pattern!r}",
        evidence_source="none",
    )


# ── LLM-dispatch path ────────────────────────────────────────────────────────────


# An LLMDispatch is `(claim, pin) -> ClaimVerdict` (or None if it cannot
# verify). Production wiring will invoke the `accuracy-auditor` agent;
# tests inject a callable that returns a canned verdict. Until the agent
# is wired, the default returns None which yields VERDICT_UNVERIFIABLE.
LLMDispatch = Callable[[Claim, ExternalPin | None], ClaimVerdict | None]


def _no_llm_dispatch(claim: Claim, pin: ExternalPin | None) -> ClaimVerdict | None:
    """Default: do not call an LLM. Caller treats None as unverifiable."""
    return None


def _select_pin_for_claim(claim: Claim, pins_by_name: dict[str, ExternalPin]) -> ExternalPin | None:
    """Heuristic: protocol-shaped claims map to cc-hook-protocol; no other
    pins are wired yet. New pins extend this dispatch table."""
    if claim.pattern in {"exit_code_near_hook", "hook_near_exit_code",
                         "protocol_schema", "claude_code_protocol"}:
        return pins_by_name.get("cc-hook-protocol")
    return None


def _verify_against_pin(
    claim: Claim,
    pins_by_name: dict[str, ExternalPin],
    dispatch: LLMDispatch,
) -> ClaimVerdict:
    pin = _select_pin_for_claim(claim, pins_by_name)
    if pin is None:
        return ClaimVerdict.from_claim(
            claim,
            verification_mode=MODE_EXTERNAL_PIN,
            verdict=VERDICT_UNVERIFIABLE,
            evidence="no matching pin for this claim's pattern",
            evidence_source="none",
        )
    verdict = dispatch(claim, pin)
    if verdict is None:
        return ClaimVerdict.from_claim(
            claim,
            verification_mode=MODE_EXTERNAL_PIN,
            verdict=VERDICT_UNVERIFIABLE,
            evidence=(
                "LLM dispatch not configured "
                "(--no-llm or accuracy-auditor agent not yet wired); "
                f"pin available at {pin.path.name}"
            ),
            evidence_source=str(pin.path.name),
        )
    return verdict


# ── Top-level dispatch + orchestrator ──────────────────────────────────────────


@dataclass(frozen=True)
class VerificationContext:
    repo_root: Path
    pins_by_name: dict[str, ExternalPin]
    dispatch: LLMDispatch
    # (name, error) for each pin that failed to parse — surfaced as
    # `unverifiable` verdicts rather than aborting the whole audit.
    pin_errors: tuple[tuple[str, str], ...] = ()


def verify_claim(claim: Claim, ctx: VerificationContext) -> ClaimVerdict:
    if claim.suggested_mode == MODE_LIVE_REPO:
        return _verify_against_repo(claim, ctx.repo_root)
    if claim.suggested_mode == MODE_EXTERNAL_PIN:
        return _verify_against_pin(claim, ctx.pins_by_name, ctx.dispatch)
    return ClaimVerdict.from_claim(
        claim,
        verification_mode=MODE_UNKNOWN,
        verdict=VERDICT_UNVERIFIABLE,
        evidence=f"suggested_mode {claim.suggested_mode!r} has no verifier",
        evidence_source="none",
    )


def build_context(
    repo_root: Path,
    *,
    dispatch: LLMDispatch | None = None,
) -> VerificationContext:
    pins, pin_errors = list_pins_lenient(repo_root)
    return VerificationContext(
        repo_root=repo_root,
        pins_by_name={p.name: p for p in pins},
        dispatch=dispatch or _no_llm_dispatch,
        pin_errors=tuple(pin_errors),
    )


def _freshness_in_scope_files(
    repo_root: Path, doc_globs: list[str] | None
) -> set[str] | None:
    """Repo-relative files in audit scope, or None for a full audit
    (no scope filter). Mirrors claim extraction's file enumeration so
    `--doc` scopes freshness verdicts the same way it scopes claims."""
    if doc_globs is None:
        return None
    from espalier.claim_extractor import _enumerate_files
    return {
        str(p.relative_to(repo_root)).replace("\\", "/")
        for p in _enumerate_files(repo_root, doc_globs)
    }


def _freshness_excluded_files(repo_root: Path) -> set[str]:
    """Repo-relative files whose fragments are audit-excluded.

    `EXCLUDED_DOC_GLOBS` is applied to claim extraction on EVERY run
    (`_enumerate_files` takes it as a default argument), but the freshness pass
    used to consult it only under `--doc`, where the scope set happens to be
    built by that same enumerator. A full audit passes `doc_globs=None`, which
    `_freshness_in_scope_files` reads as "no scope filter" — and, because scope
    was the only channel exclusion travelled on, that also meant "no exclusion".
    So a frozen-record doc QUOTING a fragment marker as an example (a corpus
    entry citing `policy=...`) was audited as a live fragment, exactly backwards
    from the narrow/broad intuition: the scoped audit honoured the exclusion and
    the full audit did not.

    Kept separate from the scope set so a full audit still reports fragments
    living outside `DEFAULT_DOC_GLOBS`; this subtracts the exclusions and
    nothing else.
    """
    from espalier.claim_extractor import EXCLUDED_DOC_GLOBS
    out: set[str] = set()
    for pattern in EXCLUDED_DOC_GLOBS:
        for path in repo_root.glob(pattern):
            if path.is_file():
                out.add(str(path.relative_to(repo_root)).replace("\\", "/"))
    return out


def _entry_in_scope(
    entry: dict, in_scope: set[str] | None, excluded: set[str] | None = None
) -> bool:
    source = str(entry.get("source", ""))
    rel = source.rsplit(":", 1)[0].replace("\\", "/")  # drop trailing :line
    if excluded and rel in excluded:
        return False
    if in_scope is None:
        return True
    return rel in in_scope


def _emit_freshness_verdicts(
    repo_root: Path, doc_globs: list[str] | None = None
) -> list[ClaimVerdict]:
    """Return one ClaimVerdict per critical (FAIL) or stale
    (UNVERIFIABLE) fragment, or [] when the state cache is
    missing or stale (cache-staleness is surfaced via session_start).

    When ``doc_globs`` is set (e.g. ``--doc <file>``), only fragments
    whose source file is in scope are emitted — a single-file audit
    must not exit 1 on unrelated repo-wide freshness drift."""
    from espalier.freshness import (
        is_state_cache_stale,
        read_state_cache_safe,
    )

    cache = read_state_cache_safe(repo_root)
    if cache is None or is_state_cache_stale(cache, repo_root=repo_root):
        return []
    in_scope = _freshness_in_scope_files(repo_root, doc_globs)
    excluded = _freshness_excluded_files(repo_root)
    out: list[ClaimVerdict] = []
    # read_state_cache_safe coerces only the `counts` subfield, not
    # `critical`/`stale` or their items. A hand-edited / corrupted
    # state-cache file whose `critical`/`stale` is a non-list, or whose items are
    # non-dicts (string, list), would otherwise char-iterate or raise
    # AttributeError on entry.get(...) — crashing `espalier audit-accuracy`
    # (exit 1) on an operator-corrupt file. Coerce the container to a list and
    # skip non-dict items (mirrors the freshness.py fragment guard).
    critical = cache.get("critical")
    for entry in critical if isinstance(critical, list) else []:
        if not isinstance(entry, dict):
            continue
        if not _entry_in_scope(entry, in_scope, excluded):
            continue
        out.append(ClaimVerdict(
            claim_id=f"freshness::{entry.get('id', '<unknown>')}",
            location=entry.get("source", ""),
            claim_text=f"freshness:{entry.get('id', '<unknown>')}",
            verification_mode=MODE_FRESHNESS,
            verdict=VERDICT_FAIL,
            evidence=entry.get("reason", ""),
            evidence_source=".espalier/freshness.json",
        ))
    stale = cache.get("stale")
    for entry in stale if isinstance(stale, list) else []:
        if not isinstance(entry, dict):
            continue
        if not _entry_in_scope(entry, in_scope, excluded):
            continue
        out.append(ClaimVerdict(
            claim_id=f"freshness::{entry.get('id', '<unknown>')}",
            location=entry.get("source", ""),
            claim_text=f"freshness:{entry.get('id', '<unknown>')}",
            verification_mode=MODE_FRESHNESS,
            verdict=VERDICT_UNVERIFIABLE,
            evidence=entry.get("reason", ""),
            evidence_source=".espalier/freshness.json",
        ))
    return out


def audit_accuracy(
    repo_root: Path,
    *,
    doc_globs: list[str] | None = None,
    dispatch: LLMDispatch | None = None,
    estimated_cost_per_llm_call_usd: float = 0.02,
) -> AuditReport:
    """Run claim extraction + verification across the doc surface."""
    repo_root = repo_root.resolve()
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    claims = extract_claims(repo_root, doc_globs)
    ctx = build_context(repo_root, dispatch=dispatch)

    verdicts: list[ClaimVerdict] = []
    # A malformed pin degrades to a distinct `unverifiable` verdict instead
    # of aborting the whole run with an exit indistinguishable from drift.
    for pin_name, pin_err in ctx.pin_errors:
        verdicts.append(ClaimVerdict(
            claim_id=f"external_pin::{pin_name}",
            location=f"docs/external/{pin_name}",
            claim_text=f"external pin {pin_name}",
            verification_mode=MODE_EXTERNAL_PIN,
            verdict=VERDICT_UNVERIFIABLE,
            evidence=f"malformed pin (degraded, not a hard blocker): {pin_err}",
            evidence_source="docs/external/",
        ))
    llm_calls = 0
    is_no_llm = dispatch is None or dispatch is _no_llm_dispatch
    for claim in claims:
        v = verify_claim(claim, ctx)
        verdicts.append(v)
        if (
            claim.suggested_mode == MODE_EXTERNAL_PIN
            and not is_no_llm
            and v.verification_mode == MODE_EXTERNAL_PIN
            and v.verdict != VERDICT_UNVERIFIABLE
        ):
            llm_calls += 1

    verdicts.extend(_emit_freshness_verdicts(repo_root, doc_globs))

    passed = sum(1 for v in verdicts if v.verdict == VERDICT_PASS)
    failed = sum(1 for v in verdicts if v.verdict == VERDICT_FAIL)
    unverifiable = sum(1 for v in verdicts if v.verdict == VERDICT_UNVERIFIABLE)
    elapsed = time.monotonic() - t0

    return AuditReport(
        repo_root=repo_root,
        started_at=started_at,
        # "Claims extracted" must count the doc-claims actually
        # extracted, not the freshness/pin-error verdicts also folded into the
        # verdict list. A freshness or malformed-pin verdict is not an extracted
        # claim; counting it would inflate the number. The "Verdicts" render line
        # (passed/failed/unverifiable) still reflects every verdict.
        claims_total=len(claims),
        claims_passed=passed,
        claims_failed=failed,
        claims_unverifiable=unverifiable,
        verdicts=verdicts,
        elapsed_seconds=elapsed,
        llm_calls=llm_calls,
        estimated_cost_usd=llm_calls * estimated_cost_per_llm_call_usd,
    )


# ── Renderers ──────────────────────────────────────────────────────────────────────────────────


def render_markdown(report: AuditReport, *, only_failing: bool = False) -> str:
    lines: list[str] = []
    lines.append("# Accuracy Audit Report")
    lines.append("")
    lines.append(f"**Repo:** {report.repo_root}")
    lines.append(f"**Date:** {report.started_at.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Claims extracted:** {report.claims_total}")
    lines.append(
        f"**Verdicts:** {report.claims_passed} pass, "
        f"{report.claims_failed} fail, {report.claims_unverifiable} unverifiable"
    )
    if report.llm_calls:
        lines.append(
            f"**LLM calls:** {report.llm_calls} "
            f"(~ ${report.estimated_cost_usd:.2f})"
        )
    else:
        lines.append("**LLM calls:** 0 (mechanical-only mode)")
    lines.append(f"**Elapsed:** {report.elapsed_seconds:.2f}s")
    lines.append("")

    failing = [v for v in report.verdicts if v.verdict == VERDICT_FAIL]
    if failing:
        lines.append(f"## Failures ({len(failing)})")
        lines.append("")
        for v in failing:
            lines.append(f"### {v.location}")
            lines.append(f"**Claim:** {v.claim_text}")
            lines.append(
                f"**Verdict:** FAIL ({v.verification_mode}: {v.evidence_source})"
            )
            lines.append(f"**Evidence:** {v.evidence}")
            lines.append("")
    else:
        lines.append("## Failures (0)")
        lines.append("")
        lines.append("No claim failures -- every binding claim is consistent with evidence.")
        lines.append("")

    if only_failing:
        return "\n".join(lines)

    unverifiable = [v for v in report.verdicts if v.verdict == VERDICT_UNVERIFIABLE]
    if unverifiable:
        lines.append(f"## Unverifiable ({len(unverifiable)})")
        lines.append("")
        lines.append("_Claims the auditor could not bind to evidence (mode + reason)._")
        lines.append("")
        for v in unverifiable:
            lines.append(
                f"- **{v.location}** ({v.verification_mode}): "
                f"{v.evidence}"
            )
        lines.append("")

    passing = [v for v in report.verdicts if v.verdict == VERDICT_PASS]
    if passing:
        lines.append(f"## Passing ({len(passing)})")
        lines.append("")
        lines.append("_Claims verified against live filesystem state or pins._")
        lines.append("")
        for v in passing:
            lines.append(f"- **{v.location}**: {v.evidence}")
        lines.append("")

    return "\n".join(lines)


def render_json(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2)


def cli_main(args) -> int:
    """Entry point invoked by espalier/cli.py::cmd_audit_accuracy."""
    repo_root = Path(getattr(args, "repo", ".")).resolve()

    doc_globs = None
    doc_arg = getattr(args, "doc", None)
    if doc_arg:
        doc_globs = [doc_arg]

    no_llm = getattr(args, "no_llm", False)
    dispatch: LLMDispatch | None = _no_llm_dispatch if no_llm else None

    report = audit_accuracy(repo_root, doc_globs=doc_globs, dispatch=dispatch)

    if getattr(args, "json", False):
        print(render_json(report))
    else:
        print(render_markdown(report, only_failing=getattr(args, "only_failing", False)))

    if report.claims_failed > 0:
        return 1
    return 0
