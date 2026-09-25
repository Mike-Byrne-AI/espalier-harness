# docs/

**Doing:** User + contributor documentation — usage guides, reference, conventions, and footgun catalogs. `README.md` is the index: it maps every doc to its audience and what it covers.
**Don't break:** `CONVENTIONS.md` documents THIS repo's actual patterns and `SHARP_EDGES.md` its real footguns — describe what's true, don't invent. Numeric claims are pinned (`FRESHNESS.md`), per-surface support tiers are normative (`SURFACE_SUPPORT_MATRIX.md`), and doc-vs-code parity is tested. Keep internal pack IDs out of adopter-facing docs.

## Before writing or editing in this folder:

1. Read [`README.md`](README.md) — the doc map (audience + scope per file).
2. For conventions/footguns, edit `CONVENTIONS.md` / `SHARP_EDGES.md` to match the live code, not an idealized version.
3. After edits, run the doc contracts: `pytest tests/test_operator_docs.py tests/test_surface_support_matrix.py tests/test_deploy_doc_parity.py` (the last is the one a mirrored-doc edit reds).

**Read first:** [`README.md`](README.md)
