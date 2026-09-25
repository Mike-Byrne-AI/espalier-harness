# The comparison operator decides how a gate degrades

**Status:** active

**Kin:** [completeness-gate-must-discover-its-population](completeness-gate-must-discover-its-population.md) — that one is *a member is missing from the list*. [a-gate-can-be-blind-along-a-whole-dimension](a-gate-can-be-blind-along-a-whole-dimension.md) — that one is *a whole axis is untested*. This one is the third sibling: the population is right, the axis is right, and the **relation between the two sides is wrong**, so the gate fires correctly and then tells you to do the damaging thing.

**Linked from:** memory/ cool-store — reached on demand via the [`memory/CLAUDE.md`](CLAUDE.md) folder router and sibling cross-links; not rowed in the root `ESPALIER_MEMORY.md` session log.

A contract that pins a hand-written list against a derived one has a choice most
authors never make consciously:

```python
assert declared == derived     # mirror
assert derived <= declared     # ratchet
```

They catch the same *addition*. They differ entirely on *removal*, and removal is
where the damage is.

## The failure

Under `==`, losing a member of the derived set **forces** the corresponding entry
out of the declared list. That is not a warning you can decline — it is a red
build, and the cheapest way to clear it is to delete the entry. So the gate's own
remedy is *"delete the thing the gate exists to protect."*

Worse, it makes whatever generates the derived set load-bearing for the thing it
describes. Real instance: a contract required every CLAUDE.md section named by a
harness message to actually render. One section was named by exactly one clause,
in a prose doc that gets reworded routinely. Four individually reasonable steps:

1. someone rewords the clause during ordinary doc cleanup
2. the derived set shrinks, the gate reds
3. the mechanical remedy shrinks the declared list — the section is now unrequired
4. a later "this file is too long" pass deletes it; the only remaining pin was a
   byte snapshot whose own failure message says *regenerate*

No step is wrong. The chain is. And prose edits are a weekly event, so this is a
question of when.

## The fix, and the fix that was wrong first

Under `<=`, a new member must be added; losing one never forces anything out. The
entry stays, the thing stays protected, and **there is no red to answer wrongly**
— the hazard is gone structurally rather than mitigated by a better error message.

The first attempt here was to keep `==` and add a second hand-maintained list as a
"floor" of things that must survive regardless. It worked, and it was byte-identical
to the first list with nothing keeping the two in step — i.e. exactly the
enumeration-drift shape the contract existed to close, rebuilt one layer up. The
`==` was the thing *creating* the force the second list resisted. Weakening the
operator gave the same floor with one list.

## How to choose

Ask which direction of drift should red, then pick the weakest relation that reds
on that one only.

| you want to catch | operator |
|---|---|
| additions only; removals are cleanup you want to encourage | `derived <= declared` |
| both, and a stale entry is genuinely costly | `==`, but write the failure message to name *both* directions and put the diagnostic step before any edit |

`==` is right when a stale declared entry has real cost. Say what that cost is. If
you cannot, you want the ratchet. Here the cost was "a slightly longer generated
file, visible in a snapshot diff" — nowhere near the price of the chain above.

## The tell

**If a plausible response to your gate's red is "delete the thing being
protected", the operator is wrong — not the wording.** Rewording buys a reader who
is paying attention; the operator fixes the one who is not. This generalizes past
list-pinning to any contract that couples a declaration to a derivation: parity
tests, count pins, allowlists checked against a scan.

A corollary worth its own line: **an assertion's failure message is part of the
mechanism, not commentary on it.** It is the only instruction most readers will
receive at the moment they act, so a message naming the wrong side of the
comparison converts a working detector into a delivery system for the defect.
