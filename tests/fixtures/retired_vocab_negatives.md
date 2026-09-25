<!-- TP-156 must-NOT-trip negatives fixture for the retired_vocab
scanner. The scanner is pointed at this file by
test_does_not_trip_on_negatives via direct _scan_file invocation
(the fixture lives under tests/fixtures/, inside EXEMPT_PREFIXES, so
scan_repo cannot reach it — the same reach path the positives test
uses). Every construct below is a CLEAN-BUT-TEMPTING variant of a
shape the positives fixture flags, defanged so the scanner reports
ZERO findings. Each one sits near the boundary on purpose. -->

# Retired-Vocabulary Negatives

## Prose Use Of Retired Terms (clean — pattern is label-shape only)

The scanner matches a severity LABEL shape, not the words themselves.
These sentences use every retired term as ordinary prose and must stay
clean: you wrote a wrong answer, the conflicting reports were
reconciled, a vague description was sharpened, the correct fix landed,
a blocker was cleared, the major release shipped, and the minor patch
followed. None of these are label-shaped, so none fire.

A wrong turn, conflicting evidence, vague wording, correct premises, a
blocker bug, a major refactor, a minor nit — all inline, all clean.

## Mid-Sentence Bold (clean — bold not wrapping a bare term)

<!-- precision-boundary: bold wrapping a PHRASE, not a bare retired label — the
nearest near-miss to the bold-label shape the matcher flags; it must stay clean -->

Treat this as **a wrong assumption** rather than a bare label; the bold
spans a phrase, not the lone token, so the bare-term bold shape never
matches. Likewise **the conflicting branch** and **a vague spec** stay
clean because the bold wraps surrounding words.

## Line-Wrapped Prose (clean — colon/em-dash anchor not at line start)

The reviewer flagged the change as wrong. Then a conflicting note
arrived. The premise was vague. The patch was correct. A blocker
surfaced. The release was major. The follow-up was minor. Each term
ends a wrapped clause; none begins a line followed by a colon or
em-dash, so the line-start anchor never engages.

## Replacement Vocabulary (clean — uses the current closed vocab)

Severity labels now use the live closed vocabulary instead of the
retired terms:

- **BLOCK** — halt execution
- **WARN** — surface but continue
- **NIT** — cosmetic only
- **PASS** — no action needed

| BLOCK | first table cell form |
| WARN | second table cell form |

BLOCK: bullet-prefix form using the live label
PASS: another live-label bullet form

## Historical Section (clean — immediate-parent predicate exemption)

The pre-TP-114 vocabulary was **WRONG** / **CONFLICTING** / **VAGUE** /
**CORRECT**, since superseded by BLOCK / WARN / NIT / PASS. This is
allowed because its immediate parent heading marks history, mirroring
the same exemption shape the positives fixture relies on.

- **BLOCKER** — historical label, allowed under this heading
- **MAJOR** — historical label, allowed under this heading

## Migration Notes (clean — Migration marker exempts immediate parent)

During the migration we replaced **WRONG** with BLOCK and **MAJOR**
with WARN. The "Migration" heading is in the historical-marker set, so
these label-shaped occurrences are exempt by the same predicate.

## Quoted Term Names (clean — backticked, not label-shaped)

The retired terms were `WRONG`, `CONFLICTING`, `VAGUE`, `CORRECT`,
`BLOCKER`, `MAJOR`, and `MINOR`; backticked code spans are not the
bold / bullet-colon / table-cell label shape, so they never fire.
