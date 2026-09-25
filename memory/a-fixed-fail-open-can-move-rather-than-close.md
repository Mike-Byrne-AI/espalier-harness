# A fixed fail-open can move rather than close

**Status:** ACTIVE — landed 2026-08-25 (`8c61431`). The gates that caught it are
`bench/reachability_differential.py` and `bench/powershell_reachability_differential.py`.

**Linked from:** `ESPALIER_MEMORY.md` session log (2026-08-25 row).

**Kin:** [a-friction-fix-and-a-fail-open-are-one-edit](a-friction-fix-and-a-fail-open-are-one-edit.md)
— that note says relieving friction widens what you permit. This one is its
downstream half: **the repair for the resulting fail-open is itself an edit of
the same kind**, and the second attempt is not safer than the first for having
been prompted by a real defect. **Sole home for the moved-fail-open rule**; the
gate-blindness that hides it is `docs/FAILURE_MODES.md` §18.9, not restated here.

## The rule

When a fail-open is found and fixed, re-run the *whole* oracle, not the shape
that failed. A fix aimed at one end of a boundary routinely relocates the defect
to the other end, and the relocated form is a fresh defect with none of the
attention the original earned.

The discriminator: if the fix changes **when** or **where** a decision is read
rather than **what** it decides, suspect relocation. Moving a read earlier or
later swaps which inputs are visible at that moment, and the inputs that
disappear are as load-bearing as the ones that appear.

## What happened

Scoping a quoted heredoc body to the pipeline that owns it, three attempts:

| Attempt | Owner read | Breaks on | Result |
|---|---|---|---|
| 1 | at the `<<` operator, by value | `cat <<'EOF' \| bash` | operator parsed before `\| bash`; snapshot held only `cat`, body masked into a shell |
| 2 | at consume time, by value | `bash <<'EOF' && ls` | `&&` discarded `bash`; `ls` vouched for a script bash executes |
| 3 | **by reference**, plus depth and substitution checks | — | 0 fail-open |

Attempt 2 was written *as the fix for attempt 1* and shipped **23** DENY→ALLOW
shapes — six of them writing `disableAllHooks` into settings or overwriting
`write_guard.py`, on the tier `ESPALIER_MAINTENANCE_MODE=1` cannot bypass.
Attempt 1's own gate had gone green on the fix that produced them.

By reference is what gets both ends: a `|` keeps extending the same set, and a
statement separator rebinds `current_pipeline` to a fresh one, leaving a pending
heredoc pointing at the owner it actually had. **Rebind, never `.clear()`** — a
pending heredoc holds a reference, and clearing in place empties the owner out
from under it.

## How to apply

1. **Re-run the full oracle after a fail-open fix**, never the failing row alone.
   Both relocations here were caught in one run of the complete matrix and would
   have been invisible to a targeted re-test.
2. **Mutation-check each clause of the repair.** Removing any one must red the
   gate. Here: by-reference reds the new wrappers, the depth check 14 fail-opens,
   the substitution predicate 7. A clause that reds nothing is either dead or
   untested, and you cannot tell which without trying.
3. **Write the rejected attempts into the code**, not just the accepted one. The
   comment at the `<<` handler names both wrong readings and why each is wrong,
   because the next reader's instinct will be one of them — attempt 2 was the
   obvious repair for attempt 1, and obviousness is what made it dangerous.
