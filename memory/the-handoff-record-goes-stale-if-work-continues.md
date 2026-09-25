# The handoff record goes stale if work continues

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "2026-07-31 — 0-A pass on the pre-flip set"

`/handoff` writes `cc/_working_summary.md` (step 6) and `cc/GOAL.md` (step 7) as its **last** steps.
That ordering assumes the session ends at handoff. **It often doesn't** — the operator approves one
more thing, and every claim those two files make about "what this session did" is silently false from
that moment on. **Nothing checks.**

If you keep working after `/handoff`, **re-run steps 6–7 before the session actually ends.**

## Why

`cc/GOAL.md` is injected into the banner at **every** SessionStart. A stale line in it does not sit
quietly in a file nobody opens — it becomes the *opening premise* of every subsequent session, and the
next session reasons forward from it rather than re-deriving it. That is not hypothetical: a previous
GOAL.md claimed *"active set CLEAR … only the RELEASE PHASE remains"* and was injected for **two days**
while 16 packs were open.

The failure is structural, not careless. The artifacts are accurate **when written**; they are
invalidated by work that happens **after** the step that writes them. No amount of care at write time
prevents it, because the invalidating event has not happened yet.

**Measured instance — 2026-07-31.** Handoff ran, then the operator approved promoting a failure class
to canon, which produced two commits and a full-suite run. Left behind in `cc/GOAL.md`:

| claimed | actual |
|---|---|
| "nothing tracked modified" | 4 tracked files, 2 commits |
| "Suite **not run**" | 6981 passed / 10 skipped |
| "121 ahead" | 123 ahead |

`cc/_working_summary.md` carried the same three, plus stale reasoning-entry counts and a
`## 6. All user messages` section missing its last six. **All of it was caught only because a second
`/reflect` was run** — the first pass had run before the invalidating work existed.

## How to apply

- **Cheap, immediate:** treat `/handoff` steps 6–7 as *re-runnable*, not one-shot. Any post-handoff
  work — a commit, an approval, a promotion — means running them again. Cheaper than the second
  `/reflect` that would otherwise have to catch it.
- **Durable:** have those steps **derive** the volatile facts mechanically rather than accept prose
  composed earlier in the same turn. Ahead-count (`git rev-list --count`), tracked-diff
  (`git status --porcelain`) and suite state are all one command each. A hand-written "nothing tracked
  modified" is an assertion about the future; `git status` is an observation.
- **Smell test:** any sentence in a wrap-up artifact phrased in the perfect tense — *"no code landed"*,
  *"suite not run"*, *"nothing modified"* — is a claim whose truth value can still change. Prefer a
  measured number with the command beside it.

## Kin, not duplicate

`docs/FAILURE_MODES.md` **§4.10** (*the cross-artifact assertion nothing checks*) covers the **spatial**
form: document A asserts something about document B and B is never told. **This is the temporal twin** —
document A is accurate about itself, and then time moves. Same remedy family (nothing asserts the record
still holds), different trigger, so both are worth carrying.

See also [[complacent-oracle]] — a trusted artifact's output audited against ground truth rather than
taken on faith. The GOAL banner is exactly such an artifact: authoritative-looking, injected everywhere,
and until now checked by nobody.
