# A probe's silence is not a null

**Status:** active — named 2026-09-01 after four false nulls in a single session
**Linked from:** `docs/STANDING_PRINCIPLES.md` §5 (the null result is the signal — this is
                 its precondition)
**See also:** `docs/STANDING_PRINCIPLES.md` §4 (verify tool output through an independent
              oracle) · [[untrusted-oracle-protocol]] ·
              `docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md`

A probe that returns nothing and a probe that *found* nothing are the same output. Before a
null counts as evidence, the probe has to prove it ran.

`STANDING_PRINCIPLES` §5 says the null result is the signal. That is true only once the
probe is known to be live. An unverified null is not a weak signal — it is **no signal
wearing the costume of a strong one**, because a clean sweep is exactly what you were
hoping to see.

## Measured, one session, four instances

All four read as clean. None had checked anything.

| Probe | What it printed | What was actually wrong |
|---|---|---|
| Blob scan for withheld content over a git tree | empty (read as "no leaks") | ~700 `command not found` — `command grep` lost resolution inside a `while read` subshell |
| Mutation harness over a test module | "GREEN — test did not earn its red" | the mutation string never matched; the file was unchanged |
| Mutation harness, second run | "the mutant survived" | the mutant was applied *after* the call site it targeted had already run — a no-op |
| Non-ASCII sweep over two edited files | "clean (only em-dashes)" | BSD `grep` has no `-P`; it errored and the `\|\|` fallback printed the clean message |

The fourth is the sharpest: the real sweep, once written in Python, immediately found a
Russian word that had been typed into a task pack. The broken probe had reported clean on a
file that was not clean.

Note the shape the first three share with a *weak test*. "The mutation didn't red the test"
and "the mutation never applied" produce identical output, so a false null here is
indistinguishable from a real finding about test quality — and the natural next move
(rewrite the test) is work spent on a test that was already fine.

## The rule

Before trusting a null, make the probe prove two things:

1. **A positive control.** Run it against a case you *know* is true. If the carrier scan
   cannot find a carrier you planted, its clean result is worthless.
2. **A count.** Have it report how many items it examined, and check that number against
   what you expected. `716 blobs scanned, 0 hits` is evidence; `0 hits` is not.

For a mutation harness specifically, add a third: **assert the mutation applied** — compare
the file before and after, and fail loudly if the target string was absent. A harness that
silently no-ops reports every test as weak.

## The producer side: refuse, don't report, when the artifact IS the deliverable

The same two-states-one-output shape sits on the writing end, and there it is worse:
the record a run emits is the only witness, so a run that did the wrong thing and a
run that did the right thing read identically and nothing reds. Three faces, one
failure-mode review of a new assembler, 2026-09-20 (`TP-452` 1-B):

1. **A second run into an out dir that already held a rebuild** emptied its 948 KB
   record payload and exited **0**.
2. **A run that rewrote nothing returned the same schema** as one that rewrote every
   row, so the caller could not tell the two apart.
3. **A refusal arrived as a pass.** The generator's `--check` refuses a sub-floor
   file *before* checking anything, and the run's own instructions had
   pre-authorised that exit code as expected.

Each closed as a **refusal, not a report line** — exit 3 with the ids on stderr, an
existing-output refusal, and a floor-free second oracle that can still answer on a
file the floor rejects — plus a **required schema field** a do-nothing run cannot
fill. Rule 2's count is the consumer-side ancestor of that field; on the producing
end it has to be mandatory, because an omitted count reads as a small one.

The opposite error is real and lives at `docs/FAILURE_MODES.md` §3.10: a *reporter*
that refuses its whole report over one inconsistent field converts a stale field
into total blindness. The line between them is ownership — refuse when the run's own
output is the deliverable the next step consumes; report the members you can answer
for when the run only describes someone else's tree.

## Why this keeps happening

The failure is asymmetric and the asymmetry hides it. A probe that breaks *loudly* costs a
minute. A probe that breaks *quietly* returns the answer you were already leaning toward,
in the format you expected, and nothing about it invites a second look. §9 of the standing
principles — fast earns scrutiny — applies to probes, not just conclusions: **a sweep that
comes back clean faster or more easily than you expected is the one to re-run with a
control.**

Related but distinct: `docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md` covers a
probe that runs correctly and answers the *adjacent* question. This note covers a probe that
does not run at all.
