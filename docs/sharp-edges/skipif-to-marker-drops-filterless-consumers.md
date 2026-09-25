# Converting a self-detecting skipif to a marker drops every filter-less consumer

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "A skipif→Marker Convert Drops Filter-less Consumers"

**What it is:** Replacing a **self-detecting `skipif`** (e.g. "skip when
`ESPALIER_MEMORY.md` is absent") with a **marker** selected via `-m "not <marker>"` moves
the protection from *"every run self-skips"* to *"only runs that pass the filter
skip."* Any pytest consumer that does not pass the filter now **runs** the tests
— and fails.

**How you hit it:** A release-matrix rescope moved its stages to
`-m "not slow and not full_tree"` and assumed that covered export verification.
The matrix went `FINAL: FAIL` on a **third** consumer the hunt under-enumerated:
`scripts/release_check.py`'s opt-in `tests_pass` runs its *own*
`pytest -m "not slow"` over the extracted export, so the now-unguarded seeds ran
there and failed on a pruned `ESPALIER_MEMORY.md`/docs tree. The per-site count was a
floor, not a total (`docs/STANDING_PRINCIPLES.md` §8).

**How to avoid it:** When you convert skipif → marker, either

- **(a)** enumerate *every* site that runs the suite in the protected context —
  matrix stages, `release_check`, bare `pytest`, CI, adopter smoke — and add the
  `-m` carve to each; or, better,
- **(b)** add a collection-level auto-skip in
  `conftest.pytest_collection_modifyitems`: detect the context **once** via the
  correct discriminator (`is_release_export`, *not* the layout-only
  `is_self_host_repo`) and `item.add_marker(pytest.mark.skip(...))` for the
  marked items.

(b) self-protects every current *and future* consumer in one place. Keep the
marker as well, for explicit fast `-m` selection where you control the runner.

**Note the oracle:** what surfaced this was running the real release matrix to
completion — not the unit suite. A green unit suite is not evidence about a
consumer the unit suite never invokes.
