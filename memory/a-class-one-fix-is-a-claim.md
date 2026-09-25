# A class's "one fix" is a claim, and it can be several fixes wearing one name

**Status:** active
**Linked from:** [[fix-the-class-not-the-instance]] (this is its downstream half — that note
                 decides the *unit* of work, this one tests the *prescription*) ·
                 [[a-packs-prescribed-fix-code-is-a-claim]] (same discipline at pack scope) ·
                 `docs/session-archive.md` row "§C9's ONE FIX WAS FALSIFIED BY DRIVING IT"
                 — authored 2026-08-17 into the hot index, aged out of it by
                 `espalier memory prune` in `dfd13f3` (2026-08-31) and now living in the
                 archive, which is that index's declared overflow tank. Repointed rather
                 than re-inserted: the index is bounded by design, so a restored row is
                 re-pruned at the next handoff and asserts a placement that is no longer
                 true.

**What happened.** `FORWARD_LEDGER.md` §C9 carried a single prescription — *"one shared
tokenizing pass … consumed by EVERY BashPatternRecord, every write-target extractor, the
PowerShell twin and the speed-bump"* — and it read as settled because it was specific,
mechanistic, and had survived several convergence rounds unchallenged. Driven, it was
**four independent fixes bundled under one name**, and three of them were not parsing
problems at all: a right-hand anchor on one literal, five target character-class
narrowings, and a **tier-placement policy decision**. Two members matched *correctly* —
no parser change reaches a correct match.

**Why the ledger's own structure did not catch it.** The class stanza asks *"what single
change closes every member?"*, which is the right question, and a plausible answer to it
is self-ratifying: once written, every new member gets filed under the class rather than
tested against the prescription. The members were re-verified across rounds; **the
prescription never was**.

**The tell.** Read the fix sentence and the member rows as two populations and ask whether
they name the *same mechanism*. Here the fix named a tokenizer while the members named a
missing anchor, a leaking character class, a flag-order bug and a dispatch order — four
mechanisms, one sentence. When a fix sentence has to say "and also" more than once, or
reaches a second subsystem via a parenthetical, it is a roadmap, not a fix.

**The measurement that decides it, and it is cheap.** Implement the prescription's
*mechanism* against 2–3 members in a throwaway copy and see how many actually close. Here:
the reduced pass closed **one** of thirteen, and a blanket application fail-opened five
driven true positives plus six documented safety cases — i.e. the prescription was not
merely narrow, it was **harmful at the stated scope**.

**Corollary worth keeping separate.** All 13 member symptoms reproduced exactly; nothing
was fabricated. Every error was in the step *after* the observation — cause attribution
and severity. A symptom survives re-driving far more often than the consequence inferred
from it, so budget the adversarial pass against **consequences and causes**, not against
"did this reproduce."

**How to apply:** before scoping a pack to a class fix, drive the class's stated
prescription against a sample of its members and report the reach as a number. If it
closes one member of thirteen, the honest deliverable is a re-derived fix set and a
re-raise — not a large pack executing a refuted sentence. Related: [[fix-the-class-not-the-instance]],
[[a-packs-prescribed-fix-code-is-a-claim]], [[verify-a-packs-scope-out-rationale]].

**Second worked example, and it is the sharper one — the class was REAL, all members
confirmed, and the fixes still differed.** §C9's failure was a prescription that named a
mechanism its members did not share. This one had no such tell: a command-position anchor
carried three structurally identical unanchored alternation arms, and the class question
correctly identified all three. The right action was **different for every one**.

| Arm | Verdict | Why |
|---|---|---|
| reserved words (`then`/`do`/`else`/`elif`) | **delete** | a redundant restatement — the shell only recognises them at a command position, and every opener is already in the separator class |
| privilege wrappers (`sudo`/`env`/`xargs`/…) | **narrow** | the word boundary also fires after a space, but a PATH-QUALIFIED wrapper (`/usr/bin/env VAR=1`) is a genuine command position whose preceding character is `/` |
| shell-exec openers (`eval`, `sh -c`) | **keep untouched** | driven: it carries no false positive at all, because those mentions are relieved by the masking pass instead |

Deleting the second arm by analogy with the first **opened a live bypass of the harness's
own maintenance-mode env prefix**, and exactly one pinned regression row caught it — a row
an adversarial pass had added long before, for a reason nobody had needed since.

**The rule this adds.** *Fix the class, not the instance* decides the **unit** of work.
It does not decide the **verdict**, and there is no discount for the second member: a
shared shape is evidence the sites are worth **looking at**, never evidence they take the
same edit. Drive each member on its own and expect the answers to disagree — a class where
every member takes an identical fix is the lucky case, not the definition. When they do
disagree, the spread is itself the finding worth recording, because it is what stops the
next reader applying the first member's fix to the rest.

**How to apply:** after the class question yields N members, write the N verdicts down
**before** editing anything, and require a driven reason per member. If you find yourself
writing "same as above" for a member you have not driven, that is the fail-open.

_Attested 2026-08-17, §C9 / TP-440._
