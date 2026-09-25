# A memory note can be too long to be recalled

**Status:** active
**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md` folder router
                 and sibling cross-links ([[re-measure-a-calibrations-premise-when-its-key-changes]] ·
                 [[recall-keys-on-the-hazard-not-the-task]]); not rowed in `ESPALIER_MEMORY.md` (at its cap).
**About:** `tools/cc/hooks/_recall.py::_vocab_norm` · `tools/cc/hooks/_recall.py::LENGTH_NORM_ALPHA`

Writing a note is not the same as making it findable, and the miss is silent: `/recall`
answers confidently with something else, so nothing signals it.

**Mechanism.** Scoring is **binary IDF — presence, not frequency**. Every doc holding all
the query terms gets the same numerator, over a length norm with `LENGTH_NORM_ALPHA=0.05`.
At that exponent the field is nearly flat: six docs matching one two-word query landed
within 4%. Ranking is a near-tie broken by **distinct-vocabulary size**. Repeating a term
cannot help. Size is the only lever.

**Measured 2026-09-09.** A note carried the corpus's highest density of both query terms
and still returned nothing. Cut from 298 distinct tokens to 150, it took **first on four
of five** phrasings.

**⚠ Budget in the right unit — the first version of this note got this wrong.** The lever
is `len(d.tokens)`, **distinct** vocabulary. Medians diverge by unit and population:
**157 distinct** over 306 docs, but **237 total**, and `memory/` alone **283 distinct**.
Aim at 157. Sizing against total length — or against what neighbouring notes weigh —
lands you far above the winning budget, unfindable, which is the failure this prevents.

**What sinks a note is reference material.** Tables, id maps, enumerations are nearly pure
vocabulary; keep them in the artifact the note points to.

**Verify.** Run the retriever and read the ranking. Existing is not reachable — and the
corpus builds live from the tree you run in, so a worktree measures a different one.
