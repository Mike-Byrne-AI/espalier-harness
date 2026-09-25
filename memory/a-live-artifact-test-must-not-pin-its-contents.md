# A live-artifact test must not pin its contents

**Status:** active
**Linked from:** `tests/test_changelog_canon.py::TestAgainstTheLiveChangelog` ·
                 `task-packs/FORWARD_LEDGER.md` §C5 (`DEF-592`, the fixture-shape class) ·
                 [[ask-whether-the-rule-is-wrong-not-just-the-detector]] ·
                 [[classify-the-surface-before-measuring-it]]

A test that reads a **live, mutable** artifact to prove a detector is not vacuous must
assert **conditionally** — *whatever* qualifying content the artifact happens to hold
must be visible to the detector — never that the artifact currently holds some. The
unconditional form is green today and reds on the exact day the artifact legitimately
changes, which is usually the day you most need the suite.

## The failure it names

Closing `DEF-591` meant proving the new content-detector was not blind, and the obvious
proof is to drive it against the real `CHANGELOG.md`:

```python
entries = substantive_entries(unreleased_body)
assert entries                                     # WRONG
assert {"Added", "Changed", "Fixed", "Removed"} <= found   # WRONG
```

Both pass. Both pin the *current accidental contents* of a section the release procedure
is **documented to empty**. At the fold they fail — and `tests/test_changelog_canon.py`
is not in `_SLOW_FILES`, so it rides the `-m "not slow"` slice that
`release_check.check_tests_pass` runs with `ESPALIER_RELEASE_CHECK_WITH_TESTS=1`. The
red lands on the **publish-proof gate**, on the one commit the whole module exists to
protect. The set-containment form is worse still: it reds on any patch-only cycle with
no removals, on a perfectly valid file.

This is the fixture-shape class (`DEF-592`) inverted. That class is *a guard built to a
shape the real artifact does not have*; this is *a guard built to the contents the real
artifact happens to have today*. Same root — the guard encodes an accident of the
artifact rather than the property under test.

## The correct shape

```python
body = self._unreleased_body()
naive = [ln for ln in body.splitlines() if self._NAIVE_ENTRY.match(ln)]
if not naive:
    pytest.skip("no entry-shaped lines (folded or prose-only)")
assert len(substantive_entries(body)) >= len(naive)
```

Three properties, all load-bearing:

- **Conditional.** An emptied artifact skips, which is correct — there is nothing to be
  blind to.
- **Directional.** It asserts the canon sees *at least* what a crude scan sees. That is
  the actual anti-vacuity property; a detector scoring lower than a two-line regex is
  keyed on the wrong shape.
- **Independently computed.** `_NAIVE_ENTRY` is spelled out **in the test**, never
  imported from the module under test.

## The independence rule is the subtle half

If the expectation is derived from the canon it checks, the two agree by construction
and the probe is blind to the drift it exists to catch. This repo has already been bitten
by the precise mechanism: a contract test collected f-strings matching
`startswith('[subagent')`, so mutating the producer to `'[agent:'` dropped the renamed
literal out of the collected set *before any comparison ran*, and the test stayed green
on exactly the mutation it was written for.

Two implementations that must agree is the point. Deliberately write the cruder one
badly-but-differently — it only has to be wrong in a different direction.

## How it was caught, and what that says

Not by review and not by the suite — the suite was green, 8388 tests. It surfaced in an
adversarial pass that *drove the documented fold* on a scratch copy and re-ran the
slice. Reading the test cannot reveal this; you have to put the artifact into the state
the procedure will put it in.

So: when a test reads a live artifact, find the documented procedure that mutates that
artifact and run the suite against the post-procedure state. For anything the release
runbook touches, that is one `sed` and one `pytest -m "not slow"`.

## Residue worth knowing

Some tripwires red at the fold **on purpose** — between releases
`test_unreleased_section_is_empty` carries `xfail(strict=True)` under `xfail_strict = true`
precisely so the fold forces its marker off (it came off at the 0.8.0b1 cut, 2026-09-24;
the first post-cut `[Unreleased]` entry is what re-arms it). That is a designed red, not
this defect.
Tell them apart by asking whether the red *teaches the operator something they must
act on*. `docs/RELEASE_CHECKLIST.md` now names which reds at the fold are intentional
and what moves with them.
