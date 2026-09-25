# Prefer deleting a cross-citation to tracking it

**Status:** active

**Kin:** [classify-the-surface-before-measuring-it](classify-the-surface-before-measuring-it.md) — measuring this population is exactly where that trap fires, see *Measuring it* below. [the-comparison-operator-decides-how-a-gate-degrades](the-comparison-operator-decides-how-a-gate-degrades.md) — the gate built instead of deleting, and the operator that makes deleting free. [a-bounded-index-guarantees-its-inbound-citations-rot](a-bounded-index-guarantees-its-inbound-citations-rot.md) — the case where deleting is *not* the answer: the pointer names a real home that expired on a schedule, and the fix is a home that cannot.

**Linked from:** memory/ cool-store — reached on demand via the [`memory/CLAUDE.md`](CLAUDE.md) folder router and sibling cross-links; not rowed in the root `ESPALIER_MEMORY.md` session log.

A reference that names a **section inside another document** — `see FOO.md "Bar"`
— is a hyperlink with nothing checking the link. Sections get reworded during
ordinary cleanup by people who cannot see who depends on the heading. Measured on
this repo: **147 section-level cross-citations across 88 files.**

When one of these dangles, there are two fixes, and the reflex is the wrong one:

- **Add the missing section** — closes this instance, keeps the coupling, and
  invites machinery to police it.
- **Delete the citation** — closes the instance *and* the coupling.

Reach for deletion first. It is the option that shrinks the hazard rather than
instrumenting it.

## The discriminator — not a blanket ban

Some citations are worth keeping. The test is **whether the reference resolves for
free for whoever actually hits it.**

| citation | reader | resolves for free? | verdict |
|---|---|---|---|
| a runtime deny naming a root `CLAUDE.md` section | Claude, mid-task | **yes** — SessionStart already loaded that file into context | keep |
| prose in doc A naming a section of doc B | a human, later | no — they must go open it, and nothing checks it | **delete** |
| anything naming content the tool never deploys to that tree | anyone downstream | never — dead by construction | **delete** |

Same syntax, opposite failure profile. Deleting the live ones trades a *checked*
reference for no reference at all, and a three-line message can carry a remedy but
not a model — that is what the section is for.

## Measuring it — the trap

Count against **what the tool actually deploys**, never the repo-relative path.
The naive sweep here returned ~230 dead test-path citations across seeded docs.
The real number was **49**. The gap was two files that ship as near-empty *stubs*
from an assets directory while their self-host copies run to thousands of lines —
so their content reaches nobody and cannot dangle for anybody. A ~5× inflation,
one command before it would have been reported. Resolve each path through the
deploy inventory first. This is [classify-the-surface-before-measuring-it](classify-the-surface-before-measuring-it.md)
with a different surface.

## Why the reflex goes the other way

The dangling citation is usually *found* by a gate, and a gate's failure message
frames the fix as "make the target exist" — that is the branch its author had in
mind. Write the other branch into the message explicitly, or every future reader
takes the coupling-preserving path by default. Deleting a citation should also be
a **no-op against your own contracts**; if a cleanup reds your gate, the gate is
punishing the work you want done — see
[the-comparison-operator-decides-how-a-gate-degrades](the-comparison-operator-decides-how-a-gate-degrades.md).


## The third branch: disclose in place

Delete-or-deploy is not the whole space. A citation can also stay and become
**honest** — `docs/CC_AUTOMATION.md` (Espalier source repo — not deployed by
`init`). The reader is no longer stranded, which was the actual harm, and the
coupling stays visible instead of being quietly severed.

This branch is worth reaching for when the citation carries real meaning for a
maintainer and the cost was only that an adopter followed it into nothing. It
also turned out to be **mechanizable in a way the other two are not**: because
the marker lives in the prose next to the mention, a gate can require it, and
the exemption then scales without anybody maintaining a list. Every one of the
55 dead pointers found in the 2026-08-12 sweep was this same shape *minus the
parenthetical* — the repo had already invented the idiom at eight sites without
noticing it was a policy. See `tests/test_adopter_pointer_resolution.py`.

The ordering that fell out: **deploy** if the content is genuinely theirs;
**disclose** if it is genuinely ours and the pointer still means something;
**delete** otherwise — which is still the common case.
