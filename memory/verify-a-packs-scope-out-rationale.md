# Verify a pack's scope-out rationale, not just its prescriptions

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Verify a pack's scope-OUT rationale, not just prescriptions"

A pack's **"don't touch this, it's intentional"** justifications are claims,
exactly like its prescribed changes — and they are *easier* to accept unchecked,
because "leave it alone" feels like the safe default.

## The evidence (TP-270, 2026-07-12)

TP-270 asserted that three standalone `pyproject`-version readers are "different
execution environments with different available dependencies" and must stay
independent. But `final_release_matrix._load_version`'s own module **already
imports `espalier`** (via `_archive_safety`) — so its claimed "zero-dep
independence" is **not load-bearing**; it could simply call
`espalier.version_surfaces`.

The same pack named **2** `_venv_python` copies to reconcile. A `grep -rn` found
**3** — the third, `espalier/artifact_parity.py`, already used the target idiom.

## Why it matters

The existing discipline ([[a-packs-prescribed-fix-code-is-a-claim]] and
`docs/STANDING_PRINCIPLES.md` §3, a finding is a claim until grep-verified)
targets what a pack tells you
**to do**. An unverified scope-out fails twice over: it leaves real consolidation
on the table, **and** it misstates *why* — which becomes an honesty defect on a
shipping surface the moment you echo the false rationale into a code comment.

## How to apply

1. Before honoring a scope-out, grep the actual imports and sites it rests on
   (`grep -rn <symbol> <dirs>`); check the module's real dependency set.
2. Confirm the site **count** independently — the pack's number is a floor
   (`docs/STANDING_PRINCIPLES.md` §8).
3. Then act **within** scope, but **surface the gaps** as follow-up candidates in
   the pack's Landing stanza. Propose, don't silently expand scope mid-pack.
   ⚠ **Subject to the carve-out below — step 3 does NOT apply to a defect in the
   pack's own deliverable.**

## ⚠ The carve-out: your own output is never "out of scope" (added 2026-08-01)

**Step 3 above caused a defect to ship.** Read it before applying it.

Scope-out governs **adjacent** work — the consolidation you notice in a
neighbouring module, the sister-site you spot in passing. It has **no authority
over the artifact the pack itself produces.** If executing a pack reveals a flaw
in the gate, test, or mechanism that pack is *delivering*, fixing it **is** the
pack. Amend the criterion, record the amendment in Landing, and proceed.

**The evidence (TP-417, 2026-07-31).** The pack re-anchored three release-surface
assertions from a proxy (`skipped_entries` membership) to the fact (real archive
membership). While applying it, the executor noticed the **fourth** method in the
same class carried the identical defect inverted — and deferred it as `DEF-417d`,
because pass criterion 6 pinned that file as *"unmodified apart from Fix 3's three
methods."* Honouring the scope contract was the whole reason it was deferred.

**Within the hour, an adversarial mutation dropped 47 files — the entire vendored
hook layer — out of the release archive, and the full suite stayed green at 7,051
passed.** The single test that should have caught it named the affected path in its
own sample list and passed anyway, because the proxy it asserted is satisfied *for
free* by a pruned path. The deferred row was the exact hole.

**How to tell you are in the carve-out.** You are about to write a `DEF-*` row
against a file this pack is changing, in the session that changes it. That is not a
backlog item — it is an unfinished fix. Filing it forward converts a defect you
already understand into one a future session must rediscover, in a gate that reports
green the entire time.

**And check the criterion that is binding you.** A pass criterion phrased as
immutability (*"passes unmodified"*, *"stays byte-unchanged"*, *"must not be
edited"*) almost always *intends* "do not weaken this gate to clear a red" — a real
and hard-won rule. But immutability forbids **strengthening** too, and that is the
half that bites. When such a criterion blocks a genuine strengthening, the criterion
is mis-phrased: fix the artifact, then restate the criterion monotonically ("no
assertion weakened, no sample removed"). Do not treat the wording as the contract
when the intent is plainly narrower.

Canon: `docs/STANDING_PRINCIPLES.md` §11.

Dual of [[a-packs-prescribed-fix-code-is-a-claim]].
