# A dedup catalog's "collapse to canon" is a claim, not a prescription

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "A dedup catalog's 'collapse to canon' is a CLAIM"

When a duplication hunt produces a catalog of *"same concept in N places →
collapse to one canon,"* **every collapse line is a claim.** In the 2026-07-13
concept-duplication pass, a 14-validator per-case intentionality check **refuted
roughly 40%** of the naive collapses.

## The refutations (the seed refuted itself)

- **The seed case.** The `_looks_like_path` / extension-set family (4 sites) that
  *started* the hunt turned out purpose-scoped across two mechanisms — a
  `Path.suffix` walk-gate vs a token recognizer. Collapsing would make `proofs`
  read `.lock`/`.sh` as scan-text **and** make `surface_impact` drop shipped
  scripts. → leave-and-document.
- **`make_pragma_re` factory** would un-recognize 9 live inline `safe-walk`
  pragmas *and* break scanner self-containment (scanners are
  `inspect.getsource`-copied and import-free).
- **`is_test_path` ×3** are three deliberately-*opposite* predicates; a parity
  test would fail by design.
- **`DEFAULT_EXCLUDE` ×5** — the catalog's proposed `_common` home is
  unreachable, because scanners cannot import.

## The taxonomy that makes it safe

Rule every candidate **before** touching it:

1. **Forced** — copies span a no-import boundary (`tools/cc` ↔ `espalier`,
   `scanners` ↔ engine, the `_vendor` mirror, `inspect.getsource`-copied
   scanners). Cannot collapse → write a **parity test** instead.
2. **Unforced** — all copies live in one importable layer. Collapse — but
   **derive-from-core**, not force-merge, when the sets differ in breadth (else a
   breadth change made for one purpose silently shifts another). Prove the
   canon's output byte-identical on current inputs.
3. **Purpose-scoped** — they *should* differ. → **leave-and-document** with a
   comment, so the next reader or AI doesn't "fix" it. A parity test here would
   fail correctly.

## Relation to the rest of the discipline

Same discipline as [[a-packs-prescribed-fix-code-is-a-claim]] and
[[verify-a-packs-scope-out-rationale]], applied to dedup. It **extends**
`docs/STANDING_PRINCIPLES.md` §8: the site count is a floor for *finding*, but
each found site needs an intentionality ruling before *fixing*.

**Corollary (the tool gap):** `sister_site_probe` matches by name + exact value,
so it is structurally blind to concept-duplication (divergent name **and**
value). The TP-276 upgrade adds containment-overlap detection — advisory, and
self-silencing once a set is derived via comprehension.
