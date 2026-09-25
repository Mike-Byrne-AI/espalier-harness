"""Contract infrastructure for cross-source parity assertions.

Each ``*Contract`` dataclass pins one fact (number, string, set)
against a tuple of ``(relpath, regex)`` sources. Parametrized tests
in consumer modules walk the registry, extract each source's match,
and assert equality with the expected value.

The shared opt-out marker grammar ``# contract: ok <rule-id> <reason>``
plus the ``CONTRACT_CEILINGS`` dict in ``tests/_surface_expected.py``
give every rule a single chip-down knob — no per-pack ceiling
constant, no per-pack marker form.

Pack: TP-109b. Promoted from inline definitions across TP-29
(NumericContract) + TP-110/113/115 (StringContract / StringListContract).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class NumericContract:
    """Numeric-fact parity. Existing precedent (TP-29)."""
    name: str
    expected_value: int
    sources: tuple[tuple[str, str], ...]  # (relpath, regex)


@dataclass(frozen=True)
class NumericPopulation:
    """Whole-POPULATION parity for one number restated across many files.

    ``NumericContract`` binds ``(relpath, regex)`` pairs, so its unit is an
    OCCURRENCE. That unit has two blind spots, both measured on this repo:

    1. It is silent on a restatement nobody hand-wrote a row for.
    2. It leaks INSIDE a file it already declares. ``docs/SHARP_EDGES.md``
       had one bound cap statement and three unbound ones in the same file;
       raising the cap would have been *forced* through the bound line and
       left the other three silently false with the suite green.

    This binds each declared file's whole population of the fact instead.
    Two assertions per required file:

    * **anti-stale** — at least one cap-context occurrence of
      ``expected_value``. Raise the value and a file whose prose still says
      the old number yields zero, so it reds by name.
    * **completeness** — the occurrence COUNT equals the declared
      expectation, so a partial update (one site of four) reds too.

    Keyed on the expected VALUE, deliberately: an earlier design keyed on
    "every number on a cap-context line" produced 20 false positives,
    because these files legitimately discuss five different caps (skill
    bodies, folder routers, Claude Code's auto-memory, this cap's own
    superseded values, verbatim-move sizes). The number is not the
    discriminator; the subject is, and subject detection is semantic. Only
    a value-keyed scan is safe here.

    ``glob_populations`` are scanned in AGGREGATE (one total, no per-file
    pin) — a corpus where most members legitimately never mention the fact
    cannot carry a min-one rule without manufacturing a finding per member.
    """

    name: str
    # Keys into ``CONTRACT_CEILINGS`` so the exclusion list has a BUDGET.
    # Without it this dataclass would be a fresh allowlist mechanism with no
    # ceiling, no review, and no expiry — the shape this repo already learned
    # to bound for ``StringListContract``.
    rule_id: str
    expected_value: int
    # Each shape is a regex carrying a single ``{value}`` placeholder.
    context_shapes: tuple[str, ...]
    required: tuple[str, ...]
    glob_populations: tuple[str, ...] = ()
    # (relpath, line-regex, reason) — a line matching the regex in that file
    # is not a claim about this fact and is not counted.
    exclusions: tuple[tuple[str, str, str], ...] = ()

    def matcher(self) -> re.Pattern[str]:
        """Case-insensitive alternation of the shapes at the expected value.

        Case folding is load-bearing: the first census of this contract ran
        case-sensitively, missed the capitalised ``Bounded at <cap> lines``
        policy line in ``ESPALIER_MEMORY.md`` itself, and counted only a
        narrative mention — an undercount that would have pinned the wrong
        number. (Phrased without the literal value on purpose: a contract
        against unbound restatements should not add one to its own source.)

        A literal ``.replace`` rather than ``str.format``: these shapes are
        REGEXES, and a future one carrying a quantifier (``\\d{0,3}``) would
        make ``.format`` raise ``KeyError: '0,3'`` deep inside collection
        instead of reaching the carefully-worded assertions below. The
        docstring invites adding shapes, so the substitution must tolerate
        the braces regex authors actually write.
        """
        joined = "|".join(
            shape.replace("{value}", str(self.expected_value))
            for shape in self.context_shapes
        )
        return re.compile(joined, re.IGNORECASE)

    def excluded_line_res(self, relpath: str) -> list[re.Pattern[str]]:
        return [
            re.compile(pattern)
            for path, pattern, _reason in self.exclusions
            if path == relpath
        ]


def population_sites(
    root: Path, population: NumericPopulation, relpath: str
) -> list[tuple[int, str]]:
    """Return ``(lineno, matched_text)`` for one file's cap-context hits.

    Lines matching one of the population's exclusion patterns for this file
    are skipped — an exclusion carries its reason in the registry, so a
    silenced line is legible rather than an unexplained count adjustment.

    A missing file returns ``[]`` (the caller's ``.exists()`` check gives the
    better message), but an UNDECODABLE one RAISES. Swallowing it here would
    report "this file no longer states the cap" about a sentence sitting in
    plain view — a confidently wrong diagnosis that sends the reader hunting
    for a rewording that never happened. ``extract_matches`` below swallows
    both, which is fine for a presence check; for a COUNT contract the
    misdiagnosis is new, so this one differs deliberately.
    """
    path = root / relpath
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except UnicodeDecodeError as exc:
        raise AssertionError(
            f"{relpath} is not valid UTF-8, so its cap sites cannot be "
            f"counted. This is an ENCODING fault, not a stale claim — do not "
            f"'fix' it by editing the prose or the census. ({exc})"
        ) from exc
    matcher = population.matcher()
    skips = population.excluded_line_res(relpath)
    sites: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if any(skip.search(line) for skip in skips):
            continue
        sites.extend((lineno, m.group(0)) for m in matcher.finditer(line))
    return sites


@dataclass(frozen=True)
class StringContract:
    """Single-string-fact parity (e.g. canonical event name).

    The parametrized test asserts: for each source, ``len(matches)
    >= 1`` AND every match equals ``expected_value``. The length
    guard prevents vacuous-pass when a regex finds zero hits.
    """
    name: str
    expected_value: str
    sources: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class StringListContract:
    """Set-of-strings parity (e.g. test markers, mutation tools).

    Each source's regex returns ALL matches; the parametrized test
    asserts the extracted set equals ``expected_values``. The
    ``rule_id`` field keys into ``CONTRACT_CEILINGS`` for the
    per-rule opt-out chip-down.
    """
    name: str
    rule_id: str
    expected_values: frozenset[str]
    sources: tuple[tuple[str, str], ...]


# Single canonical marker grammar. Replaces per-pack `# tp-NNN: ok`
# variants. The `<rule-id>` token must match a key in
# ``CONTRACT_CEILINGS``; the `<reason>` is free text.
OPT_OUT_MARKER_RE = re.compile(
    r"#\s*contract:\s*ok\s+([a-z][a-z0-9\-]+)\s+(.+?)$",
    re.MULTILINE,
)


def find_opt_out_markers(text: str) -> list[tuple[str, str]]:
    """Return ``(rule_id, reason)`` pairs in source text.

    Used by ceiling tests to count opt-outs per rule_id without
    re-implementing the regex per consumer.
    """
    return [
        (m.group(1), m.group(2).strip())
        for m in OPT_OUT_MARKER_RE.finditer(text)
    ]


def count_opt_outs_for_rule(
    rule_id: str, paths: Iterable[Path]
) -> int:
    """Count opt-out markers for a specific rule across files."""
    count = 0
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count += sum(
            1 for rid, _ in find_opt_out_markers(text) if rid == rule_id
        )
    return count


def extract_matches(
    source_path: Path, pattern: str
) -> list[str]:
    """Read source + return all regex group(1) matches.

    Used by ``StringContract`` / ``StringListContract`` parametrized
    tests. ``re.MULTILINE`` is enabled so ``^`` / ``$`` anchors
    match per-line.
    """
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [m.group(1) for m in re.finditer(pattern, text, re.MULTILINE)]
