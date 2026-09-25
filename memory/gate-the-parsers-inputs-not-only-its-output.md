# Gate the parser's inputs, not only its output

**Status:** active
**Linked from:** memory/ cool-store via the folder router and kin cross-links; promoted
                 2026-09-04 from the reflect candidate pass (key `8c0c57061b76`),
                 not rowed in the `ESPALIER_MEMORY.md` hot index.
**Kin:** [a-gate-can-be-blind-along-a-whole-dimension](a-gate-can-be-blind-along-a-whole-dimension.md)
— that one is *the corpus has no variation on the axis under test*; this one is
*the gate reads the parser's output, and the parser's input is the axis*.
[completeness-gate-must-discover-its-population](completeness-gate-must-discover-its-population.md)
— deriving the population is necessary here and still not sufficient. See
"Not the same failure".

When a parser becomes more semantic, a malformed input stops being a local typo
and becomes a **global amputation** — and a gate that only counts the parser's
output cannot tell "the document shrank" from "the parser stopped reading". The
count moves in the same direction for both. Pair every gate over a parser's
OUTPUT with a gate over the well-formedness of the INPUTS it reads.

## Attested (DEF-565, 2026-09-04)

The recall corpus's section splitter became fence-aware: `iter_doc_sections` in
`tools/cc/hooks/_hook_utils.py` walks each line through `next_fence_state`
(CommonMark: a run of three or more backticks or tildes with at most three spaces
of indent opens; only a run of the same character, at least as long, alone on its
line closes) so a `#` inside a code block is no longer a heading.

The cost, measured before wording the change: **one stray fence opener at ~85%
of `docs/SHARP_EDGES.md` dropped the corpus from 179 to 161 sections with every
existing gate green.** Under the old backtick-only toggle the same typo hid one
section; under the fence-aware parser it hid everything below it, because an
unclosed fence never closes.

The gates that closed it, both in `tests/test_recall.py`:

- `test_every_corpus_doc_closes_its_fences` walks **every file the corpus
  reads** and reds on the first that ends inside a fence — the gate over the
  inputs.
- a per-family floor inside `test_every_corpus_doc_names_its_family`
  (`docs/SHARP_EDGES.md` ≥ 150 sections) — the gate over the output, which on
  its own would have let the amputation through at 161.

The floor is the weaker half. It reds only once the loss exceeds the slack, and
the slack has to exist or every legitimate edit reds. The input gate reds on the
first malformed file and names it.

## Not the same failure

| | undiscovered population | blind dimension | unguarded input |
|---|---|---|---|
| defect | a member the list never enrolled | every member identical on the axis | the parser's input is malformed |
| symptom | new sibling passes silently | the number does not move at all | **the number moves, plausibly, in the wrong direction** |
| fix | derive the population | author new kinds of input | **gate the inputs' well-formedness separately** |
| tell | list literal in the test | differential yields 0 changed | a stricter parser landed and only its outputs are pinned |

Deriving the corpus file list (which the fence gate does) is what makes the
input gate complete; it does not replace it. A derived list of files that are
all half-read is a complete list of amputations.

## The check

When you make a parser stricter, or teach it a construct it used to ignore:

1. Name the input shape that the new rule turns from local into global (an
   unclosed fence, an unterminated string, an unbalanced bracket, a missing
   sentinel).
2. Inject exactly one instance into a live input and measure the output count.
   If the loss is larger than the instance, the rule amputates.
3. Add a gate that walks the parser's real inputs and reds on that shape, in the
   same change as the parser — and keep the output floor as the second net, not
   the first.

## Generalisation

Any consumer that reads a stateful grammar — fences, heredocs, nesting, a
front-matter block, a `BEGIN`/`END` pair — has this property: the state machine
can enter a mode it never leaves. A gate over what the consumer emits sees the
truncation as a smaller result, which is also what a correct result looks like
on a smaller input. Only a gate over the input can tell them apart.

A second way the mode opens, from the same family: the consumer scanned its
input **line by line**, so a quoted span opened on an earlier line hid nothing
from it, and a heredoc operator merely *mentioned* inside a multi-line commit
message opened a body that never closed — after which nothing downstream was
spliced at all, and a copy into a governed file was allowed. Read a stateful
grammar's operators on a quote-blanked twin of the WHOLE input, sliced per line
by offset, never on each line's own text: a per-line scan of a multi-line
grammar is an input gate that cannot see the state it is gating.

Sibling lesson from the same review: *a measurement printed is not a measurement
read* — the classifier that partitioned the alpha-0 misses printed
`bigger_vocab=True … 460 vs 209` and the annotation beside it said "fewer
tokens"; the code-reviewer caught it by recomputing. See
[re-measure-a-calibrations-premise-when-its-key-changes](re-measure-a-calibrations-premise-when-its-key-changes.md).
