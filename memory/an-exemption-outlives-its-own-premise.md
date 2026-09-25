# An exemption outlives its own premise, and the guard on exemptions cannot see it

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "An exemption outlives its own premise"

A declared carve-out is written against a reason. The reason has a lifetime. The
carve-out does not — nothing re-reads it, and every later reader takes it as a
standing decision rather than a claim that expired.

Measured 2026-08-25 closing TP-445's Finding 5.

## The instance

`tests/test_speedbump_irreversible.py::_ANCHOR_EXEMPT` excused three PowerShell
write-extractors from the command-position anchor. Its reason read:

> *PowerShell has no `_CMD_POS` equivalent — the anchor machinery is
> posix-shell-shaped and the PS leg cannot share it without introducing a
> fail-open.*

That was **true when written and false one day later**, when `_PS_CMD_POS_SEP`
landed in the same week's work. The capability arrived; nobody re-read the
exemption that existed only because it was missing.

Cost, driven against the live hook with `ESPALIER_MAINTENANCE_MODE` cleared:
**4 of 4 plain MENTIONS** of a protected write were refused — a single-quoted
string, a `#` comment, a `$doc = "…"` assignment — on the tier maintenance mode
cannot relieve. The Bash siblings, anchored all along, scored **0 of 4**.

The stated fail-open risk did not materialise: 20 genuine invocations reached
from 20 distinct command positions all still deny.

**All four entries were stale, not three.** `_RM_SEGMENT_RE` had already been
anchored too, and its ledgered friction (DEF-498 — quoting the recursive-delete
spelling in a grep, an echo or a commit message being refused) is likewise gone:
0 of 4 such mentions refused now, 3 of 3 real invocations still denied. The set
is now **empty**.

## The structural half — this is the part worth carrying

`test_no_stale_anchor_exemptions` existed already, and it could not see any of
this. It asked one question:

> does the exempt NAME still resolve to a live pattern?

It never asked the other:

> has that pattern since BEEN GIVEN the thing it was excused from?

Those fail differently. The first catches a rename. The second catches an
exemption that has been *earned out of existence* — and while such an entry
stands, **removing the anchor again is a regression the whole gate waves
through, because an exempt name is never checked.** The carve-out silently
converts into cover for the very regression the gate exists to catch.

Both arms are now present.

## The rules

1. **An exemption written against a MISSING CAPABILITY must be re-read the day
   that capability arrives.** Put the dependency in the reason text so the
   re-read has a trigger: *"excused until X exists"* beats *"X does not exist"*.
2. **A guard over exemptions must test whether each one is still NEEDED**, not
   merely whether its subject still exists. An exemption that no longer binds is
   not untidy — it is a hole with a label on it.
3. **An exemption must expire the moment it is earned.** Deleting the entry is
   the act that re-arms the gate.
4. When a carve-out cites a ledger row for its consequence, **re-drive that
   consequence** before believing it. Two of the four here cited friction that
   had already been fixed.

Related: [[calibrate-an-enforcement-contract-against-the-live-population]],
[[fix-the-class-not-the-instance]], [[a-fixed-fail-open-can-move-rather-than-close]].
