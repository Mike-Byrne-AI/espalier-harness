# Pre-delete reference sweep — every spelling, gate on the full suite

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Pre-Delete Reference Sweep — Every Spelling, Full-Suite Gate"

**What it is:** A tracked file's reference surface is wider than the one grep you
reach for. Two spellings routinely hide from a single-pattern search, and two of
the contracts that catch the fallout fire only on a full-tree walk — so a green
*targeted* run is not proof a deletion is clean.

**How you hit it:** Pruning a batch of internal review scripts from
`.claude/workflows/` looked like a pure delete. Two blast-radius surprises
followed, each caught only because the *whole* suite ran:

1. **Spelling-incomplete sweep.** The pre-delete grep searched `name.js`. But a
   durable doc cited the script *without* the extension — bare `` `_some_review` ``
   in prose, not `` `_some_review.js` `` — and was in fact the documented subject
   of a whole schema-history section. The `.js`-suffixed sweep reported "no
   bindings"; the extensionless citations were real. Sweep both `name.ext` **and**
   bare `name`.

2. **A cleanup edit that re-introduces a leak.** Rewording a now-rotted citation
   to *explain* a deletion ("this harness was retired…") injected an internal
   pack-ID token onto an adopter-facing shipping doc — the exact class the
   provenance scanner (`tests/test_no_provenance_in_shipped_code.py`) exists to
   catch. The original path fragment never tripped it; the explanatory prose did.
   A deletion's *cleanup edits* are themselves a new surface to scan.

Both were invisible to the targeted tests run right after the edit (dozens green)
and surfaced only under the full suite — the provenance and doc→citation contracts
(`tests/test_doc_test_citations.py`) walk the doc tree, which a focused run skips.

**How to avoid it:** Before deleting a tracked file, and before trusting the
result:

1. **Sweep every spelling.** Grep the basename with its extension *and* without it
   (docs cite files bare), across both the shipping and internal doc trees. A "no
   bindings" from one pattern is a claim, not a fact — this is
   `docs/STANDING_PRINCIPLES.md` §3 applied to a filename.
2. **Treat the cleanup edits as a new surface.** Retiring or repointing a citation
   is an edit to a scanned doc — re-check it for tokens the surface forbids
   (internal IDs, build-history vocab), not just for behavioral correctness.
3. **Gate on the full suite, not targeted tests.** Citation and provenance
   contracts fire on a tree walk; a green subset proves the code path, not the
   surface. Run the whole suite before calling a deletion done.

**Class signature:** treating a single-pattern grep as the complete reference
surface of a file you are about to delete — and a green *targeted* run as proof
the deletion was clean. Sibling to the fix-side discipline in
[citation-rot-verify-fix-target-tree-wide.md](citation-rot-verify-fix-target-tree-wide.md):
that one guards *rewording* a rot; this one guards *creating* one.
