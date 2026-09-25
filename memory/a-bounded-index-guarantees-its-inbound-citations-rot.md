# A bounded index guarantees its inbound citations rot

**Status:** active

**Kin:** [prefer-deleting-a-cross-citation-to-tracking-it](prefer-deleting-a-cross-citation-to-tracking-it.md)
— the same question asked at the pointer, where deleting is the usual answer; this
note is about the pointers you *cannot* delete because they name a real home that
moved. [classify-the-surface-before-measuring-it](classify-the-surface-before-measuring-it.md)
— `ESPALIER_MEMORY.md` is a declared record surface, which is what rules out the
obvious repair.

**Linked from:** memory/ cool-store — reached on demand via the
[`memory/CLAUDE.md`](CLAUDE.md) folder router and sibling cross-links; **deliberately
not rowed in the root `ESPALIER_MEMORY.md` session log**, because a row-keyed home is
precisely the thing this note is about.

**The shape.** `ESPALIER_MEMORY.md` is bounded (120 lines) and `post_write_check`
auto-archives its oldest row into `docs/session-archive.md` on overflow. Any entry
whose `**Linked from:**` header names *"`ESPALIER_MEMORY.md` row …"* therefore has a
home with a scheduled expiry. When the row ages out,
`tools/cc/memory_sort_audit.py::_audit_unlinked` reds
`tests/test_memory_sort_audit.py::TestSuppressOnClean` with `[unlinked-repo-memory] …
citation rot`. **Measured 2026-08-31: 17 entries currently declare such a home.** One
had already rotted. The other sixteen are correct today and will rot the same way; the
mechanism guarantees it and only the timing varies.

**Both obvious repairs are wrong, for different reasons.**

*Restoring the row* fails twice over. The index is bounded by design, so the row is
pruned again at the next handoff — and `ESPALIER_MEMORY.md` is a declared member of
`claim_extractor.RECORD_SURFACES` (*"session-by-session narrative"*), so re-inserting a
row asserts a placement that is no longer true of a record. Core Rule 13.

*Repointing to the archive* fails once, and less obviously. `docs/session-archive.md`
is the index's own declared overflow tank — and it is **gitignored** (`.gitignore:111`),
so a fresh clone does not have it. The auditor catches this too and names it exactly:
a **dead breadcrumb**, not a home. `_audit_unlinked` extracts path homes from the
header and, when every one of them is dead, falls through to the same reachability
check a headerless entry gets.

**What actually holds** is an inbound link from another **tracked** file —
`_has_inbound_link` accepts a mention by filename or `[[slug]]` from any tracked file.
Two tracked notes cross-linking each other survive every prune, because nothing prunes
them. That is the repair that landed (`5b67bf8`): a `[[…]]` pair between two notes that
were genuinely related, one deciding the *unit* of work and the other testing the
*prescription*.

**So: give a new entry a home that cannot expire.** The convention already existed
before this was understood — see the sibling above, whose header declares the folder
router as its home and says in as many words that it is *not* rowed in the session log.
Copy that. A session-log row is a fine *announcement*; it is a poor *address*.

**The durable class fix, not built.** Teach `_audit_unlinked` that a row which aged
into `docs/session-archive.md` still satisfies an `ESPALIER_MEMORY.md row` claim — the
archive is the index's declared continuation, so the citation is not actually rotten,
only relocated. That closes all sixteen remaining at once instead of one per red. It
was scoped out here only because the session had already committed its work and this
is a change to an auditor's semantics, which wants its own earned red.

**Why it kept biting.** The last act of a session writes the memory row, *after* the
gate that would catch it has already run. `main` has now been red at HEAD three times
in this same file for that reason. No repair in this note addresses that; it wants the
memory write to happen before the final suite, or a gate that fires on the memory edit
itself.
