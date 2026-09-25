# Completeness gate must discover its population

**Status:** active

**Kin:** [a-gate-can-be-blind-along-a-whole-dimension](a-gate-can-be-blind-along-a-whole-dimension.md) — deriving the population does not help when every member is identical along the axis under test. [the-comparison-operator-decides-how-a-gate-degrades](the-comparison-operator-decides-how-a-gate-degrades.md) — nor does it help when the population and the axis are both right and the *relation* between the declared and derived sides is wrong.

**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md` folder router and sibling cross-links (notably [[gating-on-count-manufactures-findings]]); not rowed in the root `ESPALIER_MEMORY.md` session log.

A test whose docstring promises "**every** X reds here if it regresses" is only
as complete as *how it finds its Xs*. If the population is a **hand-maintained
list**, the gate witnesses exactly the items on the list — a new sibling that
skips the discipline is simply absent from the list and **passes silently**,
which is the precise regression the gate claims to prevent. The forward
guarantee ("a future walker added without the skip reds here") is then **prose
the mechanism cannot keep** — an "anti-whack-a-mole gate" that is itself
whack-a-mole.

The fix is to make the population the **OUTPUT of a search**, not a literal:

- **Discover** mechanically (AST over the source, a filesystem walk,
  `git ls-files`) so a new member is auto-enrolled the moment it is added.
- **Floor** the discovery (`assert len(found) >= N`) so a discovery bug that
  silently finds zero cannot vacuously pass.
- Assert each discovered member satisfies the invariant **OR** carries an
  explicit opt-out pragma (`# <thing>-ok <reason>`). A greppable opt-out forces
  a conscious "this one is exempt because…", never silent omission.

**TP-277 is the worked example.** The "4-A anti-whack-a-mole gate" was a
hand-curated dict of 7 repo-root walkers; a future bare-`os.walk` walker — the
one recursive-walk shape the `filesystem_contracts` recurrence scanner does NOT
flag (it flags only `followlinks=True` and raw `rglob`/`glob`) — would evade
both the dict AND the scanner, reintroducing the nested-repo class the gate
exists to prevent. Replaced with an AST test that DISCOVERS every `os.walk` loop
in non-scanner `espalier/` and asserts each prunes-or-annotates (floor 3). The
repo already had the pattern right one file over: the drift-pin
`test_inline_safe_rglob_copies_match_canonical_oswalk_loop` DISCOVERS the inline
`_safe_rglob` copies (floor ≥ 8) instead of hand-listing them — copy that shape.

**The tell:** a docstring says "every / all / any future X" but the body
iterates a **literal collection**. The guarantee is theater until that
collection is computed by a search with a floor.

## The second-order trap: the discovered population OVER-includes

Switching from a hand-list to discovery fixes the *under*-count, but a naive
`discovered == required` assertion then **over**-counts and self-reds: a
`git ls-files "*.md"`-derived doc set drags in generated mirror trees, fixture
corpora, and illustrative scaffolds — none of them a real member of the population
the gate is *about*. Two moves keep the discovery honest:

- **Key the assertion on the RISK-BEARING subset, not the raw discovery.** The gate
  is about a *specific* rot (a citation that can go stale, a marker that can be
  dropped); assert only over the members that actually *carry that risk*. TP-334's
  doc-citation completeness gate
  (`tests/test_doc_test_citations.py::TestSweepCompleteness`)
  keys on the citation-bearing subset: it reds on a `.md` that carries a live
  test-file citation outside the sweep, because a citation-free doc has nothing to
  rot. The naive "every tracked `.md` is swept" reading would have self-red on ~112
  files, ~89 of them mirror-tree copies.
- **Subtract only a BACKED residue — never a fresh hand-list.** Each exclusion needs
  a mechanical backstop (a generated mirror is byte-pinned by a parity contract, so
  the swept SOURCE covers it transitively) or a not-a-real-member rationale (a
  fixture `.md` embeds citation-shaped text as scanner *input*; a golden scaffold
  names a demo test that never resolves). An unbacked exclusion list is the hand-list
  moved from the population to the subtraction — **the same class one level up**, the
  discrete-item cousin of the `# thing-ok <reason>` opt-out above.

Done this way the gate **earns its keep on the first run**
([[calibrate-an-enforcement-contract-against-the-live-population]] §3): TP-334's
contract surfaced two *live* gaps — `bench/README.md` and `examples/README.md` cite
real enforcement tests yet sat outside the sweep — closed by sweeping them in, not
excluding them away. Probe the live population first and adjudicate every flag as a
possible real miss; the framing (risk-bearing subset vs. raw file set) is invisible
from the spec, and only the live run shows it. *Source: TP-334 doc-citation sweep
coverage, commit `ae125f3`, 2026-07-25 — the DOMINANT enumeration-integrity class
(`memory/CONVERGENCE_LEDGER.md` R5), first target closed.*

This is the coverage-side dual of [[gating-on-count-manufactures-findings]] — *a
gate certifies only the mechanically-witnessable.* A hand-list "certifies EVERY
walker" but witnesses only the listed ones; certification of the unlisted is
hallucinated-from-prose, the same failure as a `/goal` judge that accepts
"red-team ran." It is also the mechanical form of the *instance-count-is-a-FLOOR*
discipline (a roadmap's named sites are a floor — AST-enumerate the real surface,
never trust the count): a hand-list freezes the floor as if it were the ceiling.

*Source: TP-277 nested-repo hardening — adversarial diff review
(`wf_0986573a-c78`) flagged the hand-list; fixed in commit `e366dea`,
2026-07-14.*


## When the population CANNOT be discovered, classify it exhaustively instead

The prescription above — make the population the output of a search — assumes a
mechanical property exists that selects the members. Sometimes none does, and the
honest move is not to invent a worse filter.

**Attested.** An anchor census selected hook patterns whose *source named a verb*
from a hand-written roster. The roster omitted one cmdlet, so four matchers sat
outside the population while the gate reported "every command matcher is
anchored, zero exceptions" — true of what it could see, false of the module.
The obvious repair was a better derivation, and it was **measured and refuted**:
four candidate properties scored against all 59 distinct patterns (41 command
matchers, 18 not) —

- *is fed the raw command* — misses 25; every anchored extractor reads the masked copy
- *contains a bare literal word token* — wrongly selects 6, and still misses the
  redirect matcher, a real write detector with **no verb in it at all**
- *boolean search vs iterating extraction* — not even a function of the pattern;
  one matcher is used both ways
- *carries a command-position anchor* — circular, selecting exactly the already-compliant set

So the filter was removed rather than improved. Population = **every** module-level
pattern in the modules, deduped by object identity (one module re-exported 18 of
them, inflating every floor by a third), each either compliant **or declared with
a category and a reason**. No third bucket, so a new member lands in neither and
reds the gate until its author answers the question. Mutation-proven: an
unanchored matcher carrying a novel verb passes the old gate and fails the new one.

**The trade is real and worth naming.** Exhaustive classification costs a written
declaration per exempt member (here ~27) and it is the only shape that cannot be
escaped by a member the vocabulary never imagined. A declaration that must be
written is a decision; an omission that falls out of a filter is an accident that
reads like one.

## A population bounded by a NEIGHBOUR's name has a silent-empty direction

A related and cheaper trap. A source-level gate sliced a function body from
`def <this_one>` to `def <the_next_one>`. Relocating an unrelated block between
the two enrolled a foreign call site — **loud**, and caught immediately. But
reorder the two functions and the slice returns **empty**, and an empty
population satisfies every assertion over it.

Bound a slice by its own end (the next top-level definition), and pair it with a
**non-vacuity assertion** — something the correct slice always contains. Any
population whose bounds are expressed in terms of a sibling's *name* inherits
this direction, and only the loud half is ever discovered by accident.

## A typed grep is a hand-list one level up (2026-09-21)

The roster for retiring `docs/known-findings.md` was derived by the pack's own
command, a `grep -rl` with an `--include` list of eight file types. It missed
`MANIFEST.in` (no listed type), two tests that named the file by bare basename,
and every scaffold that reached the file through a constant
(`DEFAULT_CORPUS_PATH`) and so never contained the path at all. The `--include`
list is the hand-maintained population in disguise: it enumerates *kinds* of
member instead of members, and a kind nobody thought of passes silently. Derive
a retirement roster by the bare token with no type filter, then grep for the
symbol names that stand in for the path — and read the proof's reds as the
lower bound moving, not as noise (three of the four reds that session were
exactly the misses).
