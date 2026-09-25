# Recall-engine extension gotchas

**Status:** active
**Linked from:** (unlinked) — standalone reference for anyone extending
`tools/cc/hooks/_recall.py`'s pull corpus (surfaced via `/reflect --candidates`,
TP-187/188).

The pull-recall engine (`_recall.py`, TP-167) scores a query by IDF-weighted
*binary* term overlap over an in-loop corpus (`memory/*.md` + `docs/SHARP_EDGES.md`
sections + `docs/sharp-edges/*.md` + `docs/STANDING_PRINCIPLES.md` sections +
self-host `FAILURE_MODES` § 1 coinages + exemplars). It returns `[]` only when the
query shares no usable vocabulary with the corpus — **it does NOT reject ordinary
off-topic English**, and no floor can (nine mechanisms measured, every one with a
negative margin; the full record is the pull-recall entry in `docs/SHARP_EDGES.md`).
These bite when you add a source or consume its output:

1. **Relatedness, not duplication.** A recall hit means the query is *topically
   related* to a doc, NOT that the doc *duplicates* the query. Measured (TP-188-A):
   a genuinely novel insight AND a pure session-history line BOTH clear the floor
   by matching a tangentially-related note (shared `render`/`parse`/`corpus`
   vocab). So treat the nearest hit as **advisory context**, never as a
   novel-vs-covered classifier — that judgment is the LLM/operator's.

2. **The tie-break sorts `docs/FAILURE_MODES.md` last.** On a score TIE, the old
   `(score, source)` reverse-sort decided by reverse-lexicographic source, so a
   `FAILURE_MODES` coinage lost a tie to a `SHARP_EDGES`/`memory/` doc of equal
   score. The fix is a TIE-BREAK edge — `(score, is_canonical_footgun, source)` —
   NOT a score bonus. A bonus would inflate a doc above genuinely-better matches
   and can pull a suppressed query above the floor (the § 5.2 suppress-floor
   erosion risk); a tie-break is score-primary and post-floor, so it does
   neither (TP-187 ranking-edge).

3. **Shard, don't blob.** Indexing a whole multi-section doc as one `_Doc` makes
   it match nearly any query's terms → inflated base score → a spurious top-1
   that clears the floor. Index per-section (one `_Doc` per `### `).

4. **Metaphor prose erodes the floor even when sharded.** A coinage body's
   `**Mental model.**` analogy (a thermometer, toddlers on stairs, business
   letterhead) imports everyday words that are `df==1` in the corpus → high-IDF
   triggers that surface the doc for OFF-topic queries. Strip the pure-analogy
   block before tokenizing; keep the technical sections (`**Industry analogs.**`
   is misnamed — it carries real technical terms, so do NOT strip it).

5. **A new footgun source often DUPLICATES existing ones.** `FAILURE_MODES` § 1
   substantially overlaps the already-indexed `SHARP_EDGES` (same footguns, two
   docs). Indexing the overlap just adds competing duplicates that lose the
   tie-break. Index only the entries WITHOUT a twin already in the corpus —
   classify the overlap before adding.

**Self-host gating.** Harness-internal corpus sources (exemplars, `FAILURE_MODES`
coinages) load only when `is_self_host_repo(root)` — an adopter's `/recall` must
not surface espalier-internal docs over their own.

6. **Gate on the ARTIFACT when it is adopter-writable; on repo IDENTITY when the
   content is ours.** The exemplars and the `FAILURE_MODES` coinages are gated on
   `is_self_host_repo` because they are espalier-internal vocabulary pointing at
   paths an adopter's tree lacks. `docs/STANDING_PRINCIPLES.md` is gated on
   `sp.is_file()` instead, and the difference is deliberate: an adopter who writes
   their own standing principles SHOULD get them back from `/recall`, and `init`
   does not seed the file — so the existence check and the intent coincide and no
   repo-identity condition is needed. Picking the wrong one of these locks an
   adopter out of their own document. ⚠ The gate must also be WITNESSABLE: `_read`
   swallows `OSError`, so a missing file yields zero docs whether or not the
   `is_file()` check exists, and a test asserting "no docs" cannot tell the two
   apart. Make `_read` explode for that path to prove the gate short-circuits.
7. **Attribute a moved pin before you re-pin it.** The blind held-out count has
   three causes and only one is a gain, so the commit must say which -- and the
   cheap oracle is a detached worktree at the last green commit, the per-row hit
   map run there and on HEAD, and a diff of the two miss lists: about ten
   seconds, and it names the row that moved. Measured 2026-09-10: the pin went
   16 to 17 deterministically at a commit that added two memory notes and
   touched no alias or fixture, so the cause was corpus drift -- the IDF shift
   lifted a standing-principle section into the top four for one query -- and
   the move was worth zero.
   Budget the move for any edit to a corpus DOCUMENT, not only an added note:
   the comment-correction lane of 2026-09-14 rewrote two `docs/SHARP_EDGES.md`
   entries and took the same knife-edge row (`STANDING_PRINCIPLES` §8) 16 -> 17
   again. When a lane edited several corpus files at once, the cheaper bisect is
   local: restore each edited file to its committed version in turn and re-read
   the count; only one returns the old value, and it names the file. A
   corpus-doc edit therefore costs a re-pin plus its dated provenance line, not
   only the recall tier.

## Two loaders, and a guard on the tie window (2026-09-12)

- **`_load_corpus` is the PULL corpus; `_load_full_corpus` is everything.**
  `PULL_EXCLUDED_MEMORY_NOTES` (the convergence ledger as a record surface, the
  pack-authoring note as an aggregate) is applied inside `_iter_corpus` only
  when its `exclude` argument is left at the default. `recall`, `recall_union`,
  the CLI shim, the eval and its labels read the pull corpus;
  `nearest_by_title` -- the reflect protocol's fold-here hint -- reads the full
  one, because the two excluded notes are exactly the canon homes a pack- or
  convergence-shaped insight must be folded into. A new reader decides which
  loader it wants and says why; a new excluded note carries a reason
  (`record` is bound to `espalier.claim_extractor.RECORD_SURFACES` over every
  canon key the loader could read, FAILURE_MODES excepted; anything else is a
  measured call). Membership is case-folded.
- **The canonical-coinage promotion never displaces a leader the query
  names.** `CANON_TIE_EPSILON` is a RELATIVE one percent, and after the
  2026-09-11 catalog fold a memory note out-scored FAILURE_MODES §1.12 by 0.2
  percent on its own title query and lost the slot. `_names` (every content
  token of the leader's title in the query, at least two) stands the promotion
  down for that case; an exact float tie still resolves through `_rank_key`,
  canonical first. Before trusting any such guard, measure its blast radius
  over every labelled query -- 357 here (own-title, paraphrase, task), exactly
  one cell moved. Alpha 0.15 would have lost six heading queries; epsilon zero
  one stripped query.
- **A corpus edit earns the recall slice.** `scripts/proof_tier.py` prints
  `recall` for any changed file the loader reads and runs the four
  `tests/test_recall*.py` after the contract slice; a doc-only fold landed with
  five pins red under the contract slice on 2026-09-11 and nobody saw them until
  the next lane's full tier (DEF-775).
