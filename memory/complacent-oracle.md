# Complacent oracle

**Status:** active
**Linked from:** ESPALIER_MEMORY.md
**Canon:** [docs/FAILURE_MODES.md §13.9](../docs/FAILURE_MODES.md) — the shipped catalog
carries this lesson in full. That section does not link back here: it *is* the canon, and
the pointer was removed because the shipped doc reaches readers who have no `memory/`.

**Kin:** [stateful-oracle-consumes-what-it-measures](stateful-oracle-consumes-what-it-measures.md) — the inverse failure: that oracle is caught *because* it is inconsistent between runs, this one hides *because* it is consistent.

A tool that never crashes, never returns empty, and emits confident,
well-formed output earns standing trust — and that trust suppresses the audit
that would reveal it is wrong. The dangerous failure is not the loud one (a
crash announces itself) or the empty one (absence announces itself) but the
**plausible** one: output wrong enough to mislead yet plausible enough to be
mistaken for signal, so nothing trips. It runs for an unknown duration; the
cost is every decision quietly made on degraded output. The tools most exposed
are the ones you BUILT and trust most — they are audited least.

**Why (the asymmetry):** detection cost ≫ fix cost. When a long-"working"
tool's flaw turns out trivial to fix, the bug was cheap and the *noticing* was
the rare, dear thing — which means nothing was surfacing it. The structural
root is usually recall-without-precision: the tests assert "does it find the
true thing" (recall) but never "how much of what it finds is junk" (precision),
so a tool with great recall and terrible precision ships green and floods you
with plausible noise.

**Mental model — a compass a few degrees off.** It always gives a confident,
plausible reading; you trust it *because* it is consistent; you only catch the
error by checking against an external landmark — which you rarely do, because
you trust the compass. The more you trust it, the farther off course you drift
before checking.

**How to apply.** Periodically take a load-bearing tool you trust, read its RAW
output (not the rendered summary), and hand-check a sample against ground truth
— "what fraction is true signal vs plausible noise?" If you have never asked,
you know the tool RUNS, not that it WORKS. Every detector/reporter ships a
known-NEGATIVE fixture (a thing it must NOT flag), not just a known-positive
one — the precision twin of earn-the-gate.

The DUAL of [[untrusted-oracle-protocol]]: that protocol fires when tool output
LOOKS fabricated, empty, or stale; the complacent oracle is the case its
trigger MISSES — output that looks fine. Sibling of
[[convergence-review-protocol]] (read a pass by its BLOCKER-yield, not its
finding count — repeatedly finding nothing is the signal; and a tool can be
correct-by-tests yet low-efficacy).

Origin (2026-06-23): `espalier/scope_walker.py` matched affected-symbols as
bare substrings, so `/scope-check`'s `main` matched `maintain` /
`docs-maintainer` — 391 plausible false-positive "gap" files on TP-214, trusted
as "integration depth" until a raw-output audit against ground truth surfaced
it. The fix (word boundaries) was one commit. Mechanism: FAILURE_MODES §10.1;
detection discipline: §13.9.

**Self-example (same session, within the hour of pinning this).** While
deciding whether `retired_vocab` was an adopter false-positive landmine, I ran a
probe — `_scan_file` on a fixture named `CHANGELOG.md` with `- MAJOR crash
fixed` — got `0 flags`, and told the operator the `fusion_manifest.py`
landmine comment was *stale*. It wasn't. `CHANGELOG.md` is one of the scanner's
*context-exempt* surfaces; the same `MAJOR`/`BLOCKER` input fires on a
normal adopter doc (`ROADMAP.md` → 2 flags). A **confounded probe** produced a
plausible-but-wrong null, and I trusted it without an independent oracle —
committing the exact failure this entry names, by its own author, the same
session. A fix-pack authoring agent caught it by probing `_fires_as_label`
directly. Lesson sharpened: **a probe is itself a tool whose output is a claim**
— control for the conditions (here, the filename triggering a context
exemption) before trusting a null. The dual of [[untrusted-oracle-protocol]]
applies recursively to your own verification steps. And when a gate *does*
surface a red, remember it is only the **top** layer if something upstream
aborted the run — keep re-running until the sequence completes clean
([[find-all-the-reds]]).
