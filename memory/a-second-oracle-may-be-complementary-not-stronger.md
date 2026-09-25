# A second oracle may be COMPLEMENTARY, not stronger — check the matrix before you substitute

**Status:** active

**Linked from:** [[fix-the-class-not-the-instance]] (this is a failure mode of the class-fix itself — the moment you reach for a better oracle to close a class, this is the check that stops you swapping a blind spot for a blind spot).

**Shape.** You have an oracle. You find a better-looking one that catches a case
the first misses. The natural move is to swap it in. Do not — until you have
driven both against the same tree set and read the matrix. "Catches something the
other misses" is equally consistent with *strictly stronger* and with
*complementary*, and those two have opposite correct actions: substitute, or
union. Guessing wrong silently reopens whatever the replaced oracle was closing.

**Attested, 2026-08-27, `espalier/cli.py` + `espalier/doctor.py`.** A fix plan
read `doctor._check_governance_event_wiring` (executability) as a strengthening
of `cli._missing_wired_hook_scripts` (path existence). Driven across four trees:

| tree | path-existence | executability |
|---|---|---|
| healthy | 0 | 0 |
| hook tree absent | **12** | 0 |
| gates wired to `echo` | 0 | **4** |
| event key deleted | 0 | **2** |

Each is blind exactly where the other sees. The executability oracle returns
**zero** on the absent-tree case *by design* — it skips gates whose file is not
on disk, so a repo that never installed the harness is not flagged. Substituting
it would have restored the original defect (`DEF-427`) in full, inside the diff
written to close it. Only the union is safe, and a mutation pass confirmed each
arm reds exactly its own rows.

**Why the wrong read is the tempting one.** The two oracles had a
weak/strong *shape* — one is older and cruder, one is newer and more careful — and
that shape is doing the persuading, not evidence. The blindness was in a
deliberate `continue` with a comment explaining why, several call levels down.

**Diagnostic, cheap.** Build the smallest tree set that separates the failure
modes you know about, run BOTH oracles on all of them, and print the matrix. If
any row has the new oracle at 0 and the old one non-zero, they are complementary
and substitution is a regression. This costs minutes and is the difference
between a class fix and a swapped blind spot.

**The sibling defect that produced it.** The class underneath was **one predicate
answering two questions**: `_settings_has_espalier_hooks` was authored as an
*upgrade discriminator* (its own docstring says so) where permissiveness is
correct, and reused as an *is-enforcement-armed* oracle where permissiveness is a
lie. When a predicate is reused for a second question, permissive-vs-strict is
rarely right for both. Split it, and say at the definition which question it
answers — see [[fix-the-class-not-the-instance]].

**Policy vs classification.** The union needed one forgiving carve-out (a legacy
spelling the strict oracle cannot parse). That carve-out was put in the CLAIM
only, never in the shared predicate: the predicate is count-parity-locked to a
zero-import mirror in `tools/cc/`, and relaxing it there would have weakened a
deny path in order to soften a message. **Keep the classifier pure and put the
forgiveness at the call site that can afford it.**
