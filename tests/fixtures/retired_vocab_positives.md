<!-- TP-140 earn-the-gate fixture. The scanner is pointed at this
file by test_earn_the_gate_detects_severity_labels via direct
_scan_file invocation (the fixture lives outside DOC_SURFACES, so
scan_repo cannot reach it). Each section here exhibits ONE
expected detection shape. -->

# Retired-Vocabulary Positives

## Severity Labels (should be flagged)

- **WRONG** — example bold form
- **CONFLICTING** — example bold form
- **VAGUE** — example bold form
- **CORRECT** — example bold form
- **BLOCKER** — example bold form
- **MAJOR** — example bold form (severity, not release)
- **MINOR** — example bold form

| BLOCKER | first table cell form |
| MAJOR | second table cell form |

WRONG: bullet-prefix form
MAJOR: another bullet form

## Historical Section (should NOT flag — predicate exemption)

The pre-TP-114 vocabulary was **WRONG** / **CONFLICTING** / **VAGUE** / **CORRECT**,
since superseded by BLOCK / WARN / NIT / PASS.

This entire paragraph is allowed because its immediate parent is
"Historical Section".

## Prose Use (should NOT flag — pattern doesn't match)

You wrote a wrong answer. The major release went out. A vague
description was provided. The minor patch addressed it.
