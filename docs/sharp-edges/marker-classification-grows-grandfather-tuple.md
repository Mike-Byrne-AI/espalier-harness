# Classifying a new test into `_MARKER_RULES` can grow a frozen grandfather tuple

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Classifying a New Test Grows the Frozen Marker Grandfather Tuple"

**What it is:** `tests/conftest.py::_MARKER_RULES` assigns every `test_*.py` file a
pytest marker (`security` / `release` / `contract` / `integration` / `unit`) by
name-prefix tuples. The last tuple — the `unit` one — is a **grandfather list**: a
frozen catch-all that `tests/test_sister_site_probe_ceilings.py::test_grandfather_tuple_does_not_grow`
pins to a ceiling and requires to **chip DOWN, never grow**. So the obvious way to
classify a new test — add its name next to its natural sibling in that tuple —
pushes the tuple one past the ceiling and reds the ceiling contract, even though
the marker-taxonomy check is perfectly happy.

**How you hit it:** classifying `test_sharp_edges_forward_links` alongside its
natural sibling `test_categorized_memory_layout` (both doc-layout guards, both
`unit`) added a 60th entry. The full suite went `1 failed` on
`test_grandfather_tuple_does_not_grow` (60 > ceiling 59) while
`test_marker_taxonomy` and the new test itself both passed. It is invisible to the
pack pre-flights (0-A/0-B/0-C/0-D) and to the targeted test run — **only the full
suite catches it**, because the ceiling contract is the only thing that counts the
tuple.

**How to avoid it:** a new `test_*.py` still needs a marker, but do **not** grow
the grandfather tuple to give it one:

- **(a) Best for a fast, stdlib-only unit test** — put `# pytest-marker: default-unit`
  as a comment in the test file. `test_marker_taxonomy` accepts that opt-out, and the
  default-unit fallthrough assigns the `unit` marker **without** adding the file to
  any `_MARKER_RULES` tuple, so the grandfather count is unchanged.
- **(b) If it genuinely belongs to a tagged class** (`security` / `release` /
  `contract` / `integration`) — add it to that tuple; those are not ceiling-frozen.

Only lower the grandfather ceiling when you are deliberately *migrating an entry
out of* it into a tagged tuple — the tuple is meant to shrink, so the ceiling
ratchets down with it, never up.

**Note the oracle:** the full suite, not the targeted test.
`pytest tests/test_marker_taxonomy.py` stays green with the test classified either
way; only `tests/test_sister_site_probe_ceilings.py` sees the growth. A green
targeted run is not evidence about a ceiling the targeted run never counts.
