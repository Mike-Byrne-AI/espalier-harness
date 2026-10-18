### Fixed

- **`/recall` no longer reads HTML comments as part of a section's text**
  (DEF-982). A docs fragment marker sits above its own heading, so the section
  splitter gave the marker's comment to the section before it. The paths in
  its `bound=` list then counted toward that section's ranking.
  - **How it was found:** on 2026-09-30, one path added to a marker moved the
    paraphrase table.
  - **Measured before the fix:** 17 of the 336 indexed documents carried a
    comment outside code, 7 of them fragment markers.
- **Now:** each document's token bag reads its text as a reader sees it.
  - **What is dropped:** every HTML comment outside fenced code and inline code
    spans.
  - **Precedence:** whichever of a code span and a comment starts first wins.
  - **Where a comment ends:** one that starts a line may run across blank
    lines; one that starts mid-line cannot leave its paragraph. An opener with
    no close stays text.
  - **Untouched:** queries and titles, so a question that spells a marker still
    finds it.
  - **Scaffold check:** the seeded-placeholder test uses the same strip, so a
    TODO left as a comment under the seeded heading is still the scaffold.
  - **Docs:** `docs/MEMORY_SYSTEMS.md` says so.
- **For adopters:** a word that appears only inside an HTML comment in a
  recall source no longer makes that section findable. Write it as prose, or in
  code, to keep it searchable.
