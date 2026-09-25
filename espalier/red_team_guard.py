"""Red-team quality guard: re-execute blocker repros so ``externally_verified``
is a COMPUTED fact, not an LLM claim.

A fan-out red-team returns ``FINDING_SCHEMA`` findings
(:mod:`espalier.fan_out_findings`). That schema already carries an
``externally_verified`` boolean — "true when a non-LLM oracle confirmed this
finding against ground truth, not merely LLM-asserted" — but nothing today
*computes* it, so a finding can claim ``blocks_release`` with a prose repro that
was never run. That is the gate-gaming surface this guard closes.

For every finding that claims ``blocks_release``, the red-team must ship an
EXECUTABLE repro: an argv command, the expected outcome, and a *specific failure
signature* (a non-catch-all ``match`` regex). The guard re-runs the command, and
a blocker passes only when the command FAILS and emits exactly that signature —
raising the bar from a prose assertion to a reproduced, signature-matched
failure. A trivially-failing command (``/usr/bin/false``) emits no signature and
is rejected. This generalises the earn-the-red discipline into a gate:
re-execution is the teeth, the template is only the shell.

What the guard does NOT prove (stated honestly, because a green gate must not be
over-read): it cannot prove the failure is *causally* the claimed bug — an agent
could author a command that emits the signature — nor that real blockers were
*missed*. Those residuals stay with strong-model adversarial passes and human
review. The guard raises the floor (no-repro, non-failing, unsigned, or
ambiguous-id blockers are rejected); it does not certify depth or completeness.

Design choices follow the governing frame (a workflow toolbelt, not a security
boundary — false-positives and friction outrank closing fake-classes):

* Gate on PROCESS + REPRODUCIBILITY, never on finding COUNT. An honest null — a
  red-team that ran and found zero reproducible blockers — PASSES. Requiring a
  minimum finding count would *manufacture* findings, inverting the
  null-result-is-the-signal principle the convergence discipline rests on.
* The diversity-of-passes signal (distinct finder identities >= a floor) is a
  WARNING, never a hard block: breadth is encouraged, not coerced.
* A present-but-unrun repro proves nothing; only the re-execution counts.

Stdlib + ``espalier`` only. ``subprocess`` runs each repro as an argv list (never
a shell string) with the output encoding pinned.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from espalier._text import os_error_text, plural

REPRO_EXPECT: tuple[str, ...] = ("fail", "pass")
# A match that matches (almost) anything carries no signal — a blocker's
# signature must be specific, so these are rejected as malformed.
_CATCH_ALL_MATCHES: frozenset[str] = frozenset({"", ".*", ".+", ".*?", "(.*)", "^.*$"})
_DEFAULT_TIMEOUT_S: int = 120
_DEFAULT_MIN_FINDERS: int = 3


@dataclass(frozen=True)
class ReproVerdict:
    """The outcome of independently re-running one finding's repro."""

    id: str
    ran: bool
    observed: str  # "fail" | "pass" | "error"
    expected: str  # "fail" | "pass" | "" when the entry was malformed
    verified: bool
    exit_code: int | None
    match_required: str | None
    match_ok: bool
    detail: str


@dataclass(frozen=True)
class GuardResult:
    """Aggregate gate decision over a red-team's findings + repros."""

    passed: bool
    blocker_count: int
    verified_blockers: tuple[str, ...]
    unverified_blockers: tuple[str, ...]
    verdicts: tuple[ReproVerdict, ...]
    finder_count: int
    min_finders: int
    diversity_ok: bool
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]


def _is_blocker(finding: dict) -> bool:
    """A finding claims a release blocker via ``blocks_release`` OR ``severity``."""
    if finding.get("blocks_release") is True:
        return True
    return finding.get("severity") == "blocker"


def _is_specific_match(value: object) -> bool:
    """A usable failure signature: a compilable regex that fires on SPECIFIC output.

    Rejected as catch-all (it carries no signal): a non-string / blank value; a
    known catch-all spelling in ``_CATCH_ALL_MATCHES`` (``.+`` / ``.*?`` fire on
    any *non-empty* output, which the empty-string test below does not catch); an
    uncompilable regex; or — the class the literal set missed — any pattern that
    ``re.search``-matches the EMPTY string (``Z*``, ``.*.*``, ``$``, ``^``,
    ``\\d*``, ``(foo)?``, ``(?:)`` …), which therefore fires on any, even empty,
    output. The empty-string net subsumes every literal that matches ``""`` and
    generalises to unseen spellings, while the literal set still handles the
    non-empty-matching catch-alls (``.+``, ``.*?``).
    """
    if not isinstance(value, str):
        return False
    if not value.strip() or value.strip() in _CATCH_ALL_MATCHES:
        return False
    try:
        compiled = re.compile(value)
    except re.error:
        return False
    return compiled.search("") is None


def verify_repro(
    entry: dict,
    *,
    root: Path | str = ".",
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> ReproVerdict:
    """Re-run one repro entry and judge it against its own claim.

    ``entry`` shape::

        {"id": str, "argv": list[str], "expect": "fail" | "pass",
         "match": optional regex the combined stdout+stderr must contain}

    ``expect="fail"`` means the command must exit non-zero (the bug reproduces /
    the catching test is red); ``"pass"`` means it must exit zero. ``verified``
    is true only when the OBSERVED outcome equals ``expect`` and, if ``match`` is
    given, the combined output contains it. A catch-all or non-compiling ``match``
    is malformed. Never raises: a malformed entry, a missing binary, an invalid
    regex, or a timeout yields ``observed="error", verified=False``.
    """
    raw_id = entry.get("id")
    eid = raw_id if isinstance(raw_id, str) and raw_id else "<no-id>"
    argv = entry.get("argv")
    expect = entry.get("expect")
    match = entry.get("match")
    match_field = match if isinstance(match, str) else None

    def _err(detail: str, expected: str = "") -> ReproVerdict:
        return ReproVerdict(
            id=eid,
            ran=False,
            observed="error",
            expected=expected,
            verified=False,
            exit_code=None,
            match_required=match_field,
            match_ok=False,
            detail=detail,
        )

    if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
        return _err("repro 'argv' must be a non-empty list of strings")
    if expect not in REPRO_EXPECT:
        return _err(f"repro 'expect' must be one of {REPRO_EXPECT}")
    if match is not None and not isinstance(match, str):
        return _err("repro 'match' must be a string or absent", expected=expect)
    if match_field is not None:
        if not _is_specific_match(match_field):
            return _err("repro 'match' must be specific, not empty/catch-all", expected=expect)
        try:
            re.compile(match_field)
        except re.error as exc:
            return _err(f"repro 'match' is not a valid regex: {exc}", expected=expect)

    try:
        # subprocess-contract: ok dynamic-repro-runner; verify_repro runs a caller-supplied red-team repro argv (a list, never a shell string) — re-running that dynamic command is the guard's entire purpose
        proc = subprocess.run(
            argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _err(f"repro timed out after {timeout}s", expected=expect)
    except (OSError, ValueError) as exc:
        return _err(f"repro could not run: {os_error_text(exc)}", expected=expect)

    observed = "pass" if proc.returncode == 0 else "fail"
    output = (proc.stdout or "") + (proc.stderr or "")
    match_ok = True if match_field is None else bool(re.search(match_field, output))
    verified = observed == expect and match_ok
    detail = f"exit={proc.returncode} observed={observed} expected={expect}"
    if match_field is not None:
        detail += f" match={'ok' if match_ok else 'MISSING'}"
    return ReproVerdict(
        id=eid,
        ran=True,
        observed=observed,
        expected=expect,
        verified=verified,
        exit_code=proc.returncode,
        match_required=match_field,
        match_ok=match_ok,
        detail=detail,
    )


def _finder_identities(findings: list[dict]) -> list[str]:
    """Distinct ``rule_or_scanner`` values — the diversity-of-passes signal."""
    seen: list[str] = []
    for finding in findings:
        who = finding.get("rule_or_scanner")
        if isinstance(who, str) and who and who not in seen:
            seen.append(who)
    return seen


def guard_findings(
    findings: list[dict],
    repros: list[dict],
    *,
    root: Path | str = ".",
    min_finders: int = _DEFAULT_MIN_FINDERS,
    timeout: int = _DEFAULT_TIMEOUT_S,
) -> GuardResult:
    """Gate a red-team's output: every CLAIMED blocker must independently reproduce.

    A blocker verifies only when it has a usable, unique ``id`` and a matching
    repro that uses ``expect="fail"``, carries a specific failure signature
    (``match``), and — when run — fails with that signature. ``passed`` is true
    iff there are no *unverified* blockers. ZERO blockers passes: an honest null
    is never penalised. The finder-diversity check only adds a WARNING.

    A malformed ``findings`` payload (not a list) fails CLOSED: a truncated or
    corrupt findings file must NOT be silently treated as an honest null (which
    would report ``passed=True``) — it returns ``passed=False`` with a reason.
    """
    if not isinstance(findings, list):
        return GuardResult(
            passed=False,
            blocker_count=0,
            verified_blockers=(),
            unverified_blockers=(),
            verdicts=(),
            finder_count=0,
            min_finders=min_finders,
            diversity_ok=False,
            warnings=(),
            reasons=(
                f"malformed findings payload (expected list, got "
                f"{type(findings).__name__}) -- cannot verify; failing closed",
            ),
        )
    if not isinstance(repros, list):
        repros = []

    repro_by_id: dict[str, dict] = {}
    for repro in repros:
        if not isinstance(repro, dict):
            continue
        rid = repro.get("id")
        if isinstance(rid, str) and rid and rid not in repro_by_id:
            repro_by_id[rid] = repro

    verdicts: list[ReproVerdict] = []
    verified: list[str] = []
    unverified: list[str] = []
    reasons: list[str] = []

    blockers = [f for f in findings if isinstance(f, dict) and _is_blocker(f)]
    blocker_ids = [f["id"] for f in blockers if isinstance(f.get("id"), str) and f["id"]]
    duplicate_ids = {i for i, n in Counter(blocker_ids).items() if n > 1}

    def _reject(fid: str, reason: str) -> None:
        unverified.append(fid)
        reasons.append(f"blocker {fid!r}: {reason}")

    for finding in blockers:
        raw_id = finding.get("id")
        if not (isinstance(raw_id, str) and raw_id):
            _reject("<no-id>", "no usable string id — cannot bind a repro")
            continue
        fid = raw_id
        if fid in duplicate_ids:
            _reject(fid, "duplicate blocker id — ambiguous repro binding")
            continue
        repro = repro_by_id.get(fid)
        if repro is None:
            _reject(fid, "no executable repro supplied — unverified claim")
            continue
        if repro.get("expect") != "fail":
            _reject(fid, "repro must use expect='fail' (a blocker reproduces by failing)")
            continue
        if not _is_specific_match(repro.get("match")):
            _reject(fid, "repro must assert a specific (non-catch-all) failure signature via 'match'")
            continue
        verdict = verify_repro(repro, root=root, timeout=timeout)
        verdicts.append(verdict)
        if verdict.verified:
            verified.append(fid)
        else:
            _reject(fid, f"repro did not reproduce ({verdict.detail})")

    finders = _finder_identities([f for f in findings if isinstance(f, dict)])
    diversity_ok = len(finders) >= min_finders
    warnings: list[str] = []
    if not diversity_ok:
        warnings.append(
            f"only {plural(len(finders), 'distinct finder')} "
            f"({', '.join(finders) or 'none'}); below the diversity floor of "
            f"{min_finders} — breadth not coerced, advisory only"
        )

    passed = not unverified
    if passed and not blockers:
        reasons.append("no release-blocking findings claimed — honest null passes")

    return GuardResult(
        passed=passed,
        blocker_count=len(blockers),
        verified_blockers=tuple(verified),
        unverified_blockers=tuple(unverified),
        verdicts=tuple(verdicts),
        finder_count=len(finders),
        min_finders=min_finders,
        diversity_ok=diversity_ok,
        warnings=tuple(warnings),
        reasons=tuple(reasons),
    )


def format_report(result: GuardResult) -> str:
    """Render a ``GuardResult`` as a human-readable report (caller prints it)."""
    lines = [f"red_team_guard: {'PASS' if result.passed else 'FAIL'}"]
    if result.passed:
        lines.append(
            "  note: PASS = every CLAIMED blocker reproduced its signature; it "
            "does NOT certify completeness, depth, or that a repro is causally "
            "the claimed bug"
        )
    lines.append(
        f"  blockers: {result.blocker_count} "
        f"(verified {len(result.verified_blockers)}, "
        f"unverified {len(result.unverified_blockers)})"
    )
    diversity = "ok" if result.diversity_ok else f"BELOW floor {result.min_finders}"
    lines.append(f"  finders: {result.finder_count} (diversity {diversity})")
    for warning in result.warnings:
        lines.append(f"  WARN: {warning}")
    for reason in result.reasons:
        lines.append(f"  - {reason}")
    return "\n".join(lines)
