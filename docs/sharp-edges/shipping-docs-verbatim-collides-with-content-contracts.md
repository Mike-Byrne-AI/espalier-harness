# Shipping an internal doc verbatim subjects it to every adopter-facing content contract

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Shipping a Doc Verbatim Subjects It to Content Contracts"

**What it is:** A change that "byte-mirrors internal docs verbatim as shipped
assets" can clear both pre-flight gates — the artifact review *and* scope-check —
because **both are blind to doc-content contract collisions**. The full suite is
the first oracle that sees them.

**How you hit it:** A change seeding 15 knowledge docs on `init` passed both
pre-flight gates clean, then the full suite found six failures:

- **Hygiene** (`test_common_tier_assets_have_no_internal_pack_ids`) — two docs
  carried internal bypass-class IDs. This was first missed because the hand-grep
  pattern covered only pack-style tags, not the `BC-` family; the test's own
  `_SPECIFIC_ID_RE` is the real oracle.
- **Broken links** (reflect + fuse) — a shipped doc linked to a doc `init` does
  not deploy. Separately, the reflect scan flagged deploy-context relative links
  inside the `espalier/assets/` mirror tree, which resolve at deploy time but not
  in the mirror — a false positive, fixed by excluding the mirror tree from the
  scan.
- **`doctor` fresh-init** failed downstream of the broken links.

**How to avoid it:** For any ship-these-docs-to-adopters change, **pre-scan each
doc against the live contracts** before trusting "verbatim is fine":

- import the hygiene `_SPECIFIC_ID_RE` rather than hand-grepping,
- run the `reflect_repo` broken-links scan,
- run the onboarding-honesty scan.

A doc that links to a non-seeded doc is adopter-broken. A doc's byte-mirror links
are deploy-context and must be excluded from link scans.

**Closed (annotated 2026-09-14):** `tests/test_deploy_doc_parity.py::test_seeded_doc_links_resolve_to_deployed_targets`
proves every markdown link in an init-seeded doc points at something `init`
deploys; the fuse test still covers the wider fuse tree, not this narrower invariant.
