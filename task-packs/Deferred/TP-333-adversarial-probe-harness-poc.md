# TP-333 — Adversarial probe harness (PoC): generalize `bench/` from write_guard to a second surface, agent-driven, hits→pins (G4, the real play)

## Status
- Version target: current (self-host, pre-OSS-launch)
- Change type: FEATURE (proof-of-concept) — extend the existing bypass benchmark to a new surface
- **Kind: PACK**
- Derived from: the G4 thread. The blindspot *review* agent was NO-GO (mining pass: correlated
  self-judgment, clones failure-mode-reviewer). This is the operator's stronger reframe: **don't ask
  the model to introspect its blind spots — task it to poke a surface until a mechanical invariant
  fires, and prove the red.** The oracle is the invariant, not the model's opinion, so a hit is a
  hit regardless of what the same-family generator is blind to.

## Motivation

`bench/` already IS this system for ONE surface. `run_benchmark.py` invokes a hook in an isolated
`tmp_project` via `_invoke_hook_stdin(script, payload, tmp_project)`, routes each attempt through a
per-surface verifier (`invoke_real_write_guard`, `invoke_killswitch_under_maintenance`, …), and
pins every bypass class as a `bench/corpus/BC-*.json` case carrying its own mechanical oracle
(`expected_outcome: blocked` / `expected_block_reason`). The corpus is hand-authored and confined to
the anti-self-disable / protected-zone surface.

This pack proves the generalization on ONE new surface: **`plan_guard`** (crisp oracle — a source
write with no active plan is blocked; an exempt path is allowed; high blast radius — it gates all
adopter source edits; not already covered by bench). Two things are new vs today's bench: (1) a
**second verifier surface**, and (2) an **agent-driven poke generator** that mutates seed attempts
and proposes novel ones, instead of a purely hand-authored corpus. Every confirmed hit persists as
a new corpus case — i.e. **the probe harness auto-generates mechanical contracts** (the exact
durable fix the mining pass said these classes need). This reconciles the whole thread: poking finds
*unknown* blind spots empirically; the pin closes each as an invariant.

**Why a PoC, not the full system.** The full vision (all high-blast-radius surfaces) is bounded by a
hard limit: **where a surface has no mechanical invariant, poking degrades back into self-judgment —
blind again.** plan_guard has a crisp invariant, so it's the honest place to prove the model works
before spending on the fuzzy-oracle surfaces (stop_gate degradation), which need known-bad fixtures
to have any oracle at all. Prove it cheap, then decide on expansion.

## Scope (in)

1. **A second verifier surface** — `invoke_real_plan_guard(attempt, tmp_project)` in the bench
   harness, following the existing disciplines verbatim: fail-closed-or-visibly-surfaced `except`
   arm, a **positive control** (a payload that MUST be blocked and MUST be allowed, proving the
   verifier discriminates rather than always-returning-one-answer), invocation via
   `_invoke_hook_stdin` in an isolated `tmp_project` seeded with / without an active plan.
2. **A seed corpus** — a small set of `bench/corpus/PG-*.json` (or BC-namespaced) cases in the
   existing schema: source-write-without-plan → `blocked`; exempt-prefix path (`tests/`, `tools/cc/`)
   → `allowed`; the `plan_exempt_prefixes` / root-source-sentinel edges.
3. **An agent-driven poke generator (bounded budget)** — a driver that (a) mutates the seed attempts
   (path variants, encoding, plan-state races) and (b) proposes novel attempts, seeded from the
   empirical miss-corpus (the mining output) + the BC corpus to widen past pure imagination. Each
   generated attempt runs through the verifier; a result that violates the invariant (a source write
   that slipped un-gated, or an exempt path wrongly gated) is a **hit**.
4. **Persist-hit-to-corpus** — a confirmed hit is written as a new pinned case + its `documented_in`
   regression test, exactly as a hand-authored BC-* would be. This is the auto-generated contract.
5. **Loop-until-dry termination** — stop when K rounds produce no new hit; record the round-by-round
   yield. The null result is a first-class outcome (plan_guard is well-covered).

## Scope (out)

- **Fuzzy-oracle surfaces** (stop_gate "let a bad change through", subtle degradation) — deferred
  until the PoC proves the model on a crisp oracle. They need a known-bad fixture to have any
  mechanical oracle; without one, poking them is self-judgment.
- **All other surfaces at once.** PoC is ONE surface. Expansion is a follow-on pack gated on this
  one finding signal (or a documented null).
- **Changing plan_guard's enforcement.** The probe reads the invariant; it does not modify the hook.
- **Cross-vendor / external-API generation.** Local-first; the generator is the same-family agent +
  mutation. The **generation-side correlation ceiling is acknowledged, not solved**: this finds blind
  spots the generator can *imagine probing* but would *miss judging*; mutation + corpus-seeding widen
  the imagination but do not eliminate the ceiling. Do not claim it does.
- **Un-isolated runs.** Every poke runs in a throwaway `tmp_project`; never against the live repo
  (poking plan_guard writes source files).

## Affected symbols

### Added
- `bench/` — `invoke_real_plan_guard` verifier + its positive control; `bench/corpus/PG-*.json` seed
  cases; the agent-driven generator/driver (new module under `bench/`); the persist-hit-to-corpus
  routine; regression tests for discovered hits.
- Tests: the verifier's positive-control test (it blocks what must block, allows what must allow);
  the loop's dry-termination test.

### Referenced authorities (read-only)
- `bench/run_benchmark.py` (`_invoke_hook_stdin`, the `invoke_*` verifier pattern, the except-arm +
  positive-control disciplines), `bench/corpus/BC-*.json` (the case schema), `tools/cc/hooks/
  plan_guard.py` (the surface under test — read to know its invariant, not to change it),
  `espalier.toml` (`plan_exempt_prefixes`), the mining-pass output (seed material for novel pokes).

## Implementation

1. **Positive control first (earn-the-red for the verifier).** Write `invoke_real_plan_guard` + a
   test asserting it BLOCKS a no-plan source write AND ALLOWS an exempt path. A verifier that can't
   discriminate is a blind oracle — this test proves it can, before any poking.
2. Author the seed corpus (scope-in 2) in the existing schema.
3. Build the bounded generator (scope-in 3), seeded from the miss-corpus + BC corpus; run isolated.
4. Wire persist-hit-to-corpus (scope-in 4) + loop-until-dry (scope-in 5).
5. Run the PoC. **Record the outcome either way:** a confirmed bypass → the model works, author the
   expansion pack; N dry rounds → the documented null (plan_guard well-covered), which is itself the
   correctness signal.
6. bench/ is not `tools/cc/` — no vendor mirror. Run the touched bench tests + full suite.

## Pass criteria
- `invoke_real_plan_guard` discriminates (positive control passes) and runs isolated in `tmp_project`.
- The generator produces + runs bounded pokes seeded beyond pure imagination; the loop terminates on
  dry rounds with a recorded per-round yield.
- Any confirmed hit is persisted as a pinned corpus case + a regression test (an auto-generated
  mechanical contract).
- The PoC outcome (hit-found → expand, or documented-null) is recorded with the round yields.
- Every poke ran isolated; the live repo is untouched.

## Files touched
- `bench/` (new verifier + generator + seed corpus + persist routine), new tests.
- **Owed:** `task-packs/FORWARD_LEDGER.md` pointer — the PoC outcome + the expansion decision
  (which surface next, gated on this result).

## Sub-task ordering
Verifier + positive control (1) → seed corpus (2) → generator (3) → persist + loop (4) → run &
record outcome (5). The expansion pack is authored only after (5) yields a hit or a considered null.

## Landing
- **State: DRAFT**
- Commits: none yet.
- Suite: N/A (not executed). `/scope-check TP-333` is the pre-flight.
- Earn-the-red: the verifier positive-control test (blocks what must block; allows what must allow),
  proven red before the verifier exists.
- Owed: FORWARD_LEDGER pointer.
- Date: 2026-07-23.
