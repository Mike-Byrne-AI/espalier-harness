# The pizza-test review lens — hunt the singular out-of-place error

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Pizza-test review lens — hunt the singular out-of-place error"

When a repo has **converged on correctness** — many rounds finding the same class
repeated, the last one "already 99% contained" — the remaining launch risk has a
different shape. It is not a weak-but-fine detail repeated everywhere (6/10
sauce). It is a **singular category error** an expert winces at in seconds: a
pancake crust for a pizza base, soda for sauce. Every individual part is
well-built; one thing is fundamentally **out of place**.

## Why correctness rounds structurally cannot find it

The real launch fear is not distributed weakness — that improves post-launch. It
is the one glaring thing "any chef would notice" that a still-learning operator
cannot yet spot. Correctness rounds hunt **bugs**, and a category or taste error
is individually *valid*. No correctness finder is looking at the axis it lives
on.

## How to apply

- **Invert the search.** Past rounds: find a class → cast back → count instances.
  Pizza-test: find the **wince first** (what is out of place?), *then* class-cast
  (singular vs class). A lone pancake crust is still launch-blocking at count = 1.
- **Seat divergent expert personas**, each in a genuinely different chair —
  senior-first-glance, promise-vs-delivery, proportionality, OSS-hygiene,
  domain-expert-with-web, voice/register, fresh-adopter end-to-end. Force a new
  route through the state; do not re-run the same correctness finders with new
  wording.
- **Read the result by the new-dimension yield, not the correctness null.** The
  correctness lanes returning null *under a genuinely new framing* is
  **confirmation** — the strongest signal available
  (`docs/STANDING_PRINCIPLES.md` §5, the null result is the signal). The value is
  whatever the never-attacked dimension surfaces.

## The evidence (2026-07-16)

The run proved the method: 9 of 12 findings refuted (correctness had genuinely
converged), and the live class was **self-hosting register bleed** —
concentrated, not sprawling. Exactly the shape the lens predicts.

Related: [[craft-surface-is-not-converged-unlike-correctness]] ·
[[a-latent-issue-that-just-bit-is-a-class]]
