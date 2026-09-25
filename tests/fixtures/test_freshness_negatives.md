---
title: <!-- espalier:fragment id=frontmatter-decoy bound=a.py policy=weekly -->
note: this YAML frontmatter block is skipped by parse_fragment_markers
---

# Known-negative freshness scanner fixtures

This file is the must-NOT-trip negatives corpus for the `freshness`
scanner. The contract test at
`tests/test_scanner_freshness.py::test_does_not_trip_on_negatives`
calls `parse_fragment_markers` directly with this file's content and
asserts it returns ZERO Fragments. Every construct below is a
*clean-but-tempting* near-miss: text that resembles an
`espalier:fragment` marker but is correctly suppressed by the parser
(fenced code blocks, YAML frontmatter, a foreign namespace, plain HTML
comments, or prose mentions with no marker syntax). TP-156 Tier 1.

This corpus pairs with the earn-the-gate fixture
(`tests/fixtures/test_freshness_positives.md`): that one proves
`parse_fragment_markers` FIRES (one real Fragment per policy); this one
proves it STAYS SILENT on clean input.

No time-bomb: `parse_fragment_markers` is purely structural — it does
no date arithmetic. The staleness / `_days_since` / `_classify` logic
lives only in `scan_repo`, which this corpus and its direct-call test
never exercise. So these negatives are permanently date-stable by
construction and cannot age into a finding as wall-clock advances.

Like the positives fixture, `tests/fixtures/*.md` is NOT in
`FRAGMENT_SURFACE_ALLOWLIST`, so this file is also structurally
invisible to `scan_repo` / `discover_fragments` — no `EXEMPT_PREFIXES`
addition is needed.

## Tempting-but-clean constructs

### 1. Marker inside a fenced code block (skipped — `in_fence`)

```
<!-- espalier:fragment id=fenced-decoy bound=tests/fixtures/x.py policy=weekly -->
```

### 2. Marker inside a tilde-fenced block (skipped — `in_fence`)

~~~
<!-- espalier:fragment id=tilde-fenced-decoy bound=tests/fixtures/y.py policy=numeric-contract -->
~~~

### 3. A plain HTML comment that is NOT a fragment marker

<!-- this is a normal HTML comment, not an espalier:fragment marker -->

### 4. A foreign namespace that only resembles the open token

<!-- otherproject:fragment id=foreign-decoy bound=z.py policy=weekly -->

<!-- espalier:freshness note=this is not the fragment open token -->

### 5. Prose mention with no marker syntax at all

This paragraph talks about an espalier fragment and its
`verify-on-touch` policy in plain prose, but contains no actual
HTML-comment marker syntax, so the parser extracts nothing from it.
(The open-token grammar is shown only inside fenced blocks below,
never bare in reachable prose, because inline-code backticks do NOT
exempt a marker-looking line — only fenced blocks and YAML
frontmatter do.)

### 6. A fenced block that itself shows the marker grammar (documentation)

```html
<!-- espalier:fragment id=doc-example bound=README.md policy=verify-on-touch -->
```

### 7. Opener near-misses on the trailing word boundary

<!-- precision-boundary: opener near-misses -- a token that shares the marker's
     prefix but breaks its trailing word boundary must NOT parse as a fragment -->

Prose mentioning fragmentation of a document, and a comment whose opener is a
near-miss: <!-- espalier:fragmentation notes follow -->
