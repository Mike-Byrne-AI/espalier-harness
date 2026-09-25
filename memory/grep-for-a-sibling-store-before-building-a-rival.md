# Grep for a sibling store before building a rival

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Grep for a sibling store before building a rival"

**Kin:** [fix-the-class-not-the-instance](fix-the-class-not-the-instance.md) §"Then check whether the class is already known" — the same shape applied to a *taxonomy entry* rather than a durable store: "no class covers this" is as unverified a claim as "no store serves this role".

When a pack — or your own plan — proposes a **new durable store** (a ledger, a
tracked doc, a corpus), treat *"this doesn't already exist"* as an **unverified
claim**. Grep the codebase for an existing store serving the same role before
building a rival.

## The evidence (TP-287, 2026-07-16)

TP-287 proposed a per-round convergence ledger (`memory/CONVERGENCE_LEDGER.md`)
unaware that `cc/finding_ledger.jsonl` (`espalier/finding_ledger.py`) already
existed — a per-run structured ledger built expressly "for the learning loop."
Neither the pack **nor** the 0-A `code-reviewer` pass caught it. It surfaced only
by reading the persist stage of the reference workflow, where `_fanout_audit.js`
imports `finding_ledger.append_summary`.

A second store built blind to the first is a rival-doc footgun. The pack's own
pass-criterion ("no rival doc") named only the *corpus*, not the jsonl — so the
criterion was satisfiable while the defect stood.

## How to apply

1. Before adding a store, grep the engine **and** the reference workflows for the
   same role: `grep -rn "append_\|ledger\|corpus\|_store\|jsonl"`.
2. If one exists, position the new one as a **complementary layer** and state the
   altitude difference explicitly — per-finding vs per-run vs per-round.
3. Have the new consumer **read** the existing structured store rather than
   re-deriving from prose. Mechanize, don't self-report.

## Finding the store is step one; reading its membership contract is step two

Attested 2026-09-03, and the second half cost more than the first. A widened
portability net needed to know which module-level constants in a hook module are
operator-facing text. The module already published a list, which is exactly what
this note says to look for -- and the list was keyed on a different property.
`_denial_reasons._OPERATOR_FACING_TEMPLATES` is the parametrize source for the
**Don't/Do pairing** contract, and the module says so at its `CATASTROPHIC_RM`
definition: *"intentionally NOT in `_OPERATOR_FACING_TEMPLATES` -- no Don't/Do
habit pair."* Keying on membership covered 9 of 27 constants and **inverted the
incentive**: a hard-stop message deliberately written without a pair became
permanently exempt from portability checking.

The fix was not a different store but a different reading of the same one:
**declaring the registry marks the MODULE as holding operator text; every
module-level string constant in it is then in scope.** That took the net from 0
to 50 strings and immediately surfaced two live non-ASCII escapes in shipped
denial text.

**How to apply.** When you find the sibling store, do not adopt its membership as
your predicate until you have read what admission to it *means*. Two questions,
both cheap: what test or contract consumes this list, and is there a comment
explaining why something is deliberately absent? A deliberate exclusion is the
tell -- it means membership encodes a property, and that property is probably not
yours. Use the store's EXISTENCE as the signal where you can; use its MEMBERSHIP
only when the criterion is the one you actually need.

## The same shape for test tooling: `tests/_*.py` is a store too

Attested 2026-09-13 (`DEF-763`). A class of version-gated pathlib behaviour
needed a way to reproduce the 3.10-3.13 raise on the 3.14 dev host. The lane
wrote a five-line probe, installed two interpreters and built the fix without
finding `tests/_legacy_pathlib.py`, which already transcribed those bodies for
exactly this class and recorded two earlier bites. The failure-mode reviewer
found it; the behavioural net for the lane then took ten lines instead of an
emulator. The recall query had returned lexical neighbours only, and the
"read the neighbours" habit was applied to product code, not to the suite's
shared helper modules -- which are this repo's idiom for exactly that kind of
machinery (`_git_oracle`, `_export_guard`, `_legacy_pathlib`, now `_locked`).

**How to apply.** At scoping, `ls tests/_*.py` and grep them for the class's
vocabulary (the API name, the errno, the platform word) before writing any
probe or fixture. If a helper exists, the lane's proof runs the product under
it on this host, before reaching for another interpreter or invoking the
earn-the-red platform ceiling (`docs/FAILURE_MODES.md` 13.7).

## Why the review gate won't catch it for you

The 0-A review checks the pack's claims **against HEAD**; it does not hunt for
sibling systems the pack is *silent* about. An unstated assumption has no claim
for the reviewer to verify. That hunt is yours.

Related: [[verify-a-packs-scope-out-rationale]] ·
[[dedup-collapse-suggestions-are-claims]] ·
[[a-packs-prescribed-fix-code-is-a-claim]]
