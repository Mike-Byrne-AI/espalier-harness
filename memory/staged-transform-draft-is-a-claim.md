# A staged/prepared transform draft is a claim — re-derive at apply-time, verify it dropped nothing

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "A staged/prepared transform draft is a CLAIM — re-derive + verify-no-drops before applying"

When a transform is *prepared now and applied later* — a staged doc reflatten, a
pre-computed migration, a "here's the rewrite, apply when ready" draft — the staged
output is a **claim about a moving target**, not a finished deliverable. Two independent
things rot between staging and applying, and a blind copy-over swallows both:

1. **Staleness (the delta you know about).** Concurrent work keeps changing the source.
   TP-349's forward-ledger reflatten was frozen at ledger §1.26; by apply-time the live
   ledger had reached **§1.39** (13 more chronological sections + a whole new DEF-20 block)
   and **~18 packs had landed since**, each owed a "remove the landed rows, lift the
   deferred residue" edit. The pack *anticipated* "fold in §1.27"; the real reconciliation
   was 13 sections + a re-sweep for since-landed packs.

2. **Silent drops (the delta you DON'T know about).** The staged draft itself was lossy.
   An exhaustive item-ID diff (source-vs-applied) plus an **independent adversarial
   completeness critic** found the 07-24 draft had quietly dropped **~14 still-open items**
   from the source's low-salience tail (deferred ideas, future-investigation rows). Nobody
   decided to drop them; they just didn't survive the hand-authored condense. On a
   gitignored file (no git undo) that is permanent loss.

**The discipline:** treat apply-time as a *re-derivation*, not a `cp`.
- Diff the live source against the staged snapshot and fold in everything newer FIRST.
- Run a completeness oracle BEFORE overwriting: enumerate every still-open item in the
  source, confirm each survives (directly / renamed / merged / grouped) in the output.
  A mechanical ID-diff plus one adversarial critic beats either alone (the critic caught
  two the ID-diff's label-matching missed; the ID-diff caught what the critic skimmed).
- Back up the pre-apply source when the target is unrecoverable (gitignored / not tracked).
- The critic will over-flag from missing context (TP-349's critic "found" a dropped
  security disclosure that was in fact removed by explicit operator directive) — adjudicate
  each finding against the directives, don't auto-accept.

**Instance, 2026-09-20 (the third ledger rebuild's cut).** The pack's 1-D text, written
during 1-B, said to re-run the assembler with `--drop-previously-struck`. By the time 1-D ran,
1-C had filed eight rows and re-pinned three on the assembler's output; the assembler is
verdict-driven, so a re-run would have refused on the filed rows and discarded the rest. The
cut became its own pass over the file as it stood. Then the same shape one step later: the
first cut's artifact could not be reproduced from the script, because a hand strike on the
input was not in the flags (a code-review BLOCK); `--strike-id` carries the edit now. A
prepared artifact whose recipe is not entirely in its flags is a claim about how it was made.

This is the same shape as [[dedup-collapse-suggestions-are-claims]] (a collapse catalog's
"merge to canon" is a claim), [[a-packs-prescribed-fix-code-is-a-claim]] (a pack's fix code
is a claim), and the [[untrusted-oracle-protocol]] (a single rendered artifact is a claim
until an independent oracle confirms it). A prepared artifact is a hypothesis about a world
that kept moving; verify before you commit it.
