# Hook-Protocol Assumptions

Espalier's enforcement guarantees rest on five empirically-established properties of the Claude Code hook system. These properties are not contractually stable across Claude Code versions — Anthropic could change any of them without violating their documented spec. This page names each assumption, states what it implies for the harness, and points at the surface that backs it today.

This is a catalog, not a contract. Where an assumption has a runtime pin, it is identified. Where an assumption is convention-only (no Espalier-side test catches drift), this is stated plainly so future maintainers and external reviewers can see the actual coverage shape.

Source paths in this document name files in the Espalier source repo (`tests/…`): they say which test pins an assumption, and `init` does not deploy them.

Companion surfaces:
- [docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md) — pinned external excerpt of the Claude Code hook protocol.
- `docs/sharp-edges/hook-exit-codes-channel-xor.md` — the operational consequence of Assumption 1. (Your own `docs/SHARP_EDGES.md` is the index to keep alongside it.)

---

## Scope

Espalier governs a **subset** of Claude Code's hook surface. The 10 events Espalier uses are:

| Event | Tier | Purpose |
|---|---|---|
| SessionStart | reporting | inject orientation + integrity status |
| UserPromptSubmit | advisory | classify prompt scope (`task_router`) |
| PreToolUse | guarantee | `write_guard` / `plan_guard` deny enforcement |
| ConfigChange | guarantee | `config_guard` settings.json safety |
| PostToolUse | visibility | `post_write_check` + `reflect_trigger` |
| PostToolUseFailure | reporting | re-inject untrusted-oracle re-derivation on a failed edit (Rule A, `context_reinject_failure`) |
| Stop | guarantee | `stop_gate` four-gate sequence |
| SubagentStart | reporting | inject cold-subagent orientation + finding-schema pointer (`subagent_start`) |
| SubagentStop | reporting | append subagent reasoning to active blueprint |
| PostCompact | reporting | re-inject critical context |

In code the three non-guarantee tiers above are one: `harness_config.GOVERNANCE_REPORTER_HOOKS`
is every canonical hook not in the blocking four (`GOVERNANCE_BLOCKING_HOOKS`), derived rather
than typed. `espalier doctor` fails on a deployed blocking gate with no executable wiring and
warns on a deployed reporter in the same state; `init`, `merge-settings` and `fuse` name the dead
reporters beside their armed claim.

Claude Code supports additional events Espalier does not govern (Setup, SessionEnd, PreCompact, PermissionRequest, TaskCreated, FileChanged, and others — exact list at the [pinned external excerpt](external/cc-hook-protocol.md)). Espalier's omission is deliberate:

- Friction floor (write_guard / plan_guard) is already covered by PreToolUse and ConfigChange; adding PermissionRequest would duplicate deny enforcement.
- Visibility floor (reflect_trigger / post_write_check) runs on PostToolUse; PreCompact and PostCompact already give us the conversation-compression boundary we need.
- Reporting tier (SessionStart / SubagentStop) covers the surfaces adopters typically extend. Adopters who want Setup or SessionEnd hooks should add them to their fork — see `tools/cc/hooks/CLAUDE.md` (Espalier source repo — not deployed by `init`) for the hook-authoring contract.

The pinned excerpt at [docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md) covers only the channel and exit-code semantics for the 10 events in this subset, not the full event surface. This is the **verification target** for Espalier's hook claims, not a complete Claude Code reference.

**Two vocabularies, one model.** This page calls the local deny hooks (PreToolUse / ConfigChange / Stop) the **guarantee tier** in the hook-protocol sense — they are the strongest *in-process* enforcement Espalier has. In the workflow-positioning vocabulary (`docs/POSITIONING.md`, Espalier source repo — not deployed by `init`) those same hooks are the **friction** layer, and the **guarantee** is CI + branch protection — the only layer outside the agent's reach, applied at merge time. The mapping: reporting/advisory events → advisory; PreToolUse / ConfigChange / Stop deny (including the protected-zone anti-self-disable block) → friction; CI → the merge-time guarantee. "Guarantee tier" here means "the hooks we rely on to deny in-session," not "an un-bypassable boundary" — see the honest not-a-security-claim close at the end of this page.

---

## Coverage Shape

| Assumption | Canon-backed? | Backing surface |
|---|---|---|
| 1 — `stderr` + `exit 2` blocks PreToolUse | **YES** | `docs/external/cc-hook-protocol.md` + `tests/test_hook_protocol.py::TestHookProtocolXOR` + `::TestStopGateBlockSchema` |
| 2 — plain stdout receiver-blind on PreToolUse (not `additionalContext` JSON) | NO (convention) | pinned external excerpt only; no Espalier-side runtime probe |
| 3 — Stop fires on graceful exit | PARTIAL | excerpt + `::TestStopGateBlockSchema` for the `exit 0` + top-level `decision="block"` block path; **abnormal-termination boundary is convention** |
| 4 — `CLAUDE.md` in system prompt + survives compaction | NO (convention) | `post_compact.py` existence acknowledges the boundary; no probe of the property itself |
| 5 — `SessionStart` fires exactly once | PARTIAL | excerpt + negative-claim test (`::TestNoSessionStartBlocksClaim`); **firing cardinality is convention** |

**Coverage ratio: 1/5 fully canon-backed, 2/5 partial, 2/5 convention-only.**

This is honest disclosure, not a defect. The four not-fully-canon-backed surfaces (2 partial, 2 convention-only) are properties of Claude Code's runtime that Anthropic could change without violating their documented spec; testing them in-process would either require a Claude Code mock (loses fidelity) or a network-level integration test (loses isolation). Drift would surface as documented in each assumption's body.

The single canon-backed assumption (1) is the load-bearing one: a PreToolUse/ConfigChange deny channel that blocks the tool call is the foundation of the guarantee tier (`write_guard`, `plan_guard`, `config_guard`). Those hooks bind the `exit 0` + structured-decision form of that channel, not the `exit 2` + `stderr` form — see Assumption 1. Convention-only assumptions sit underneath the friction and visibility tiers, where soft drift is recoverable.

---

## Assumption 1 — `stderr` + `exit 2` from PreToolUse blocks the tool call

A hook script exiting with code 2 and writing to stderr causes Claude Code to block the originating PreToolUse tool call and feed the stderr text back to Claude as an error message. JSON written to stdout on exit 2 is ignored.

The **guarantee tier** — `write_guard`, `plan_guard`, `config_guard` — relies on a PreToolUse/ConfigChange deny channel that blocks the tool call. Claude Code offers two, and either blocks: `stderr` + `exit 2` (the simple block, this assumption) or `exit 0` + a structured decision JSON (the structured block). Espalier's guarantee-tier hooks bind the **structured** channel — `write_guard`/`plan_guard` emit `exit 0` + `hookSpecificOutput.permissionDecision="deny"`; `config_guard` emits `exit 0` + a top-level `decision="block"` (the Stop-style schema, `config_guard.py::block`). `stderr` + `exit 2` is the alternate channel they deliberately do **not** use — `tests/test_hook_protocol.py::TestHookProtocolXOR` pins that each deny path uses exactly one channel. Without a working deny channel the harness has only the friction and visibility tiers.

**Backed by:**
<!-- canon: tests/test_hook_protocol.py::TestHookProtocolXOR -->
<!-- claim-id: hook-assumption-1-stderr-exit-2 -->
- [docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md) — pinned excerpt of the Claude Code hook protocol with the exit-code and channel semantics ("Common output behavior" section).
- `tests/test_hook_protocol.py::TestHookProtocolXOR` — asserts each governance hook uses exactly one channel per deny path.
- `tests/test_hook_protocol.py::TestStopGateBlockSchema` — asserts `stop_gate` block JSON uses the top-level Stop schema (a related but distinct deny path).

---

## Assumption 2 — plain stdout from PreToolUse is receiver-blind (but `additionalContext` JSON is not)

A PreToolUse hook's **plain stdout** — text written on exit 0, *not* wrapped in the `hookSpecificOutput.additionalContext` JSON field — is written to the Claude Code debug log but **not** shown in the conversation transcript or system prompt. The agent cannot see it. The exceptions are SessionStart, UserPromptSubmit, and UserPromptExpansion, where plain stdout *is* added as context Claude can act on; PreToolUse is not among them.

The `additionalContext` JSON field is a **separate** mechanism and is **not** receiver-blind: the live protocol delivers `hookSpecificOutput.additionalContext` (exit-0 JSON) "next to the tool result" on PreToolUse (and PostToolUse / PostToolUseFailure / PostToolBatch). An earlier version of this assumption claimed `additionalContext` on PreToolUse was itself receiver-blind; a 2026-06-02 fetch of the live protocol corrected that (see "Resolved open questions" below), and this assumption now states the property that still holds — it is *plain stdout* on PreToolUse that the agent cannot see.

This rules out a class of "looks like it works" bugs where a hook author assumes plain stdout on PreToolUse will steer the agent. It will not: a message meant for the agent must go via `additionalContext` JSON, or — for a hard block — a deny decision (`exit 0` + `permissionDecision="deny"`, or the alternate `stderr` + `exit 2`). Espalier's guarantee-tier PreToolUse hooks message the agent through `permissionDecisionReason` (the `exit 0` + `permissionDecision="deny"` structured channel), not plain stdout and not the `exit 2` + `stderr` simple-block channel.

**Backed by:**
<!-- canon: convention -->
<!-- claim-id: hook-assumption-2-additional-context -->
- [docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md) — the "Channel and exit code semantics" section pins this property: **plain stdout** on most events goes to the debug log, with SessionStart / UserPromptSubmit / UserPromptExpansion as the named exceptions; PreToolUse is *not* in that list. The same excerpt lists PreToolUse among the events where `additionalContext` JSON *is* delivered next to the tool result — the two channels differ.
- No Espalier-side runtime probe. The harness's own `session_start.py` legitimately uses `additionalContext` (SessionStart *is* a plain-stdout exception and also delivers `additionalContext`), so the presence of that field in the codebase is not evidence about PreToolUse plain-stdout blindness. Drift would show up as a hook author writing PreToolUse plain stdout and being surprised when the agent doesn't act on it.

---

## Assumption 3 — Stop hook fires on graceful session exit

The `Stop` hook event fires when a session ends through the normal exit path, giving `stop_gate` its window to run the four-gate sequence (pytest → docs refresh → code review → blueprint finalize). Behavior on **abnormal** termination (crash, kill -9, OOM, network drop) is environment-dependent and not guaranteed by the hook protocol.

This is the basis of the "transcript-gated compulsion" primitive: a session cannot exit cleanly without satisfying the gates. The boundary is graceful exit only. A non-graceful termination skips the gate.

**Backed by:**
<!-- canon: tests/test_hook_protocol.py::TestStopGateBlockSchema -->
<!-- claim-id: hook-assumption-3-stop-fires -->
- [docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md) — pins the Stop event's block schemas. `stop_gate` uses `exit 0` + a top-level `decision="block"`/`reason` JSON (the Stop schema, distinct from PreToolUse's `permissionDecision`) — see `tools/cc/hooks/stop_gate.py::block`. `exit 2` + stderr is the alternate simple-block channel.
- `tests/test_hook_protocol.py::TestStopGateBlockSchema` — asserts the block-schema shape Stop returns.
- **No Espalier-side pin for the abnormal-termination boundary.** This is convention. If a session is killed before Stop fires, the gate is bypassed silently. Operationally documented but not testable in-process.

---

## Assumption 4 — `CLAUDE.md` is part of the system prompt and survives compaction

Repository `CLAUDE.md` content is injected into Claude Code's system prompt at session start and continues to be visible to the agent after conversation compaction. Folder-level `CLAUDE.md` files are auto-injected on file-tree traversal (the read-side router pattern).

This is the foundation of the **visibility tier**. Persistence across compaction is what makes `CLAUDE.md` content carry meaningfully through a long session — anything that needs to survive compaction goes here rather than in transcript-only scratchpads.

**Backed by:**
<!-- canon: convention -->
<!-- claim-id: hook-assumption-4-claude-md-persistence -->
- The `post_compact.py` hook exists *because* the harness treats post-compaction context as needing re-injection. Its existence is acknowledgment that compaction is a real boundary; it is not a probe of `CLAUDE.md` persistence per se.
- **No Espalier-side runtime pin** for `CLAUDE.md` being in the system prompt. This is current Claude Code behavior, not a documented contract. Drift would surface as agents losing track of harness conventions after a compaction.

---

## Assumption 5 — `SessionStart` fires once per session *boundary* (`startup` / `resume` / `clear` / `compact`)

The `SessionStart` event fires once at each session *boundary*, carrying a `source` field of `startup`, `resume`, `clear`, or `compact`. It is the canonical place to install per-session state — blueprint chain loading and advancement, integrity-drift reporting, kill-switch detection, the auto-orient context injection.

It is **not** once-per-logical-session: `compact` fires mid-session on *every* context compaction, and `clear`/`resume` fire when the operator resets or resumes. Espalier depends on this distinction — blueprint chain-*advancement* (starting a new node) is gated to `startup`/`clear` in `session_start._should_advance_chain` precisely *because* the event also fires on `compact`; advancing on every compaction would fragment one working session into many shallow nodes. `resume`/`compact` therefore load the chain read-only (bootstrapping only when no blueprint file exists). `post_compact.py` (the PostCompact hook) owns the compaction-specific re-orientation.

If `SessionStart` fired zero times, the auto-orient context would be missing and the session would start cold. The additionalContext payload **is** re-injected on each firing by design (e.g. after every compaction); the size budget (`_MAX_CONTEXT_BYTES`) bounds each injection so re-firing cannot grow the window unboundedly.

**Backed by:**
<!-- canon: tests/test_documented_claims.py::TestNoSessionStartBlocksClaim -->
<!-- claim-id: hook-assumption-5-session-start-cardinality -->
- [docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md) — pins SessionStart's per-event behavior (stdout → context the agent can see) and enumerates the four `source` values.
- `tests/test_documented_claims.py::TestNoSessionStartBlocksClaim` — asserts the *negative* invariant that no doc claims SessionStart can block (since it cannot, per protocol). This catches a related drift class but does not pin the firing cardinality.
- `tests/test_session_start_source_aware.py` — pins the source→advancement policy (`startup`/`clear` advance; `resume`/`compact`/unknown do not).
- **The four `source` NAMES are current Claude Code behavior, not Espalier-pinned.** A CC rename would manifest as silent chain stagnation (a new session no longer recognized as `startup`/`clear`), not a test failure — re-verify the names when bumping the pinned protocol excerpt.

---

## Resolved open questions (from the retired Recall Engine design §7, probed 2026-06-02)

The Recall Engine design (Trigger-Correlated Context Reinjection) left two hook-protocol
questions open. A direct fetch of the live protocol (code.claude.com/docs/en/hooks,
2026-06-02) resolves both; the [pinned excerpt](external/cc-hook-protocol.md) was
refreshed to match.

- **§7.1 — Does `PostToolUse` fire on a tool *error*?** No. The live protocol
  splits the post-tool boundary: `PostToolUse` fires after a tool call
  *succeeds*; a distinct `PostToolUseFailure` event fires after it *fails*. A
  hook reacting to an errored `Edit` (e.g. an "exact-match failure" trigger) must
  wire `PostToolUseFailure`, not `PostToolUse`.
- **§7.2 — Does `PostToolUse` `additionalContext` reach the model?** Yes. The
  live protocol delivers `hookSpecificOutput.additionalContext` (exit-0 JSON)
  "next to the tool result" on `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
  and `PostToolBatch` — a *separate* mechanism from **plain stdout**, which is
  still added as context only on `SessionStart` / `UserPromptSubmit` /
  `UserPromptExpansion`.

**Bearing on Assumption 2:** §7.2 established that `additionalContext` (exit-0
JSON) is delivered next to the tool result on PreToolUse, so the original
"`additionalContext` is receiver-blind on PreToolUse" claim was wrong. Assumption
2 has since been **revisited** (2026-07-21): it now states the property that does
hold — *plain stdout* on PreToolUse is receiver-blind — and the Coverage Shape row
matches. The guarantee-tier design is unaffected either way: it messages the agent
via `permissionDecisionReason` (the `exit 0` + `permissionDecision="deny"` structured channel), not `additionalContext`.

---

## Action-justification matching

Typed `action_justification` capture and auto-justification from plan metadata record a structured justification dict on the active cognitive blueprint when `execution_plan mark <i> running` fires with `--goal` and `--not-doing` populated. `post_write_check` then walks the blueprint after every mutation, looking for a matching AJ within the 60-second window.

**Matching criteria (v0.8.0a1):**
- The AJ has a parseable ISO-format `timestamp` field.
- The timestamp is within `_AJ_WINDOW_SECS` (60s) of the mutation.
- The AJ is a dict (malformed entries silently skipped).

**Not checked:**
- `content_hash` equality. The composer hashes plan metadata (`task|index|description`); the matcher would otherwise need to hash file bytes or command strings (the existing pattern). These two domains are disjoint by construction; coupling them would require the planner to anticipate the matcher's hash function.
- `tool` equality. The composer hardcodes `"Bash"`; many mutations are Write/Edit/PowerShell. Tool-equality gating would force per-tool composers.

**Trade-off:** a single AJ within the 60s window suppresses advisories for *all* mutations in that window, regardless of tool. Multi-mutation steps benefit (one declaration covers all edits). Misuse (declare intent, then unrelated mutations) gets spurious suppression. The window length (60s) is short enough that drift is bounded; tighten to 30s only if real-world data shows over-suppression.

**Audit trail integrity:** the recorded AJ still carries all six fields (`goal`, `step_rationale`, `expected_outcome`, `not_doing`, `tool`, `content_hash`) for downstream audit. The `action_justification_missing` audit-log entry still fires on every mutation that doesn't have an AJ within the window. Only the *advisory firing rate* changes.

**Feature status:** stable as of v0.8.0a1.

---

## Measured latency footprint (2026-07-24 snapshot — not continuously re-verified)

A one-off latency measurement, recorded here because it is the harness's only
answer to its own *direction ≠ magnitude* discipline on hook cost: prior review
established the *direction* (the `*`-matcher hooks do per-call I/O), and this
measures the *magnitude*. **It is a snapshot, not a pinned contract** — no test
asserts it, and it will drift as the hook layer changes.

- **~170 ms p50 / ~180 ms p95** of added wall-clock per `Edit`/`Write` tool call.
  This is a *serial upper bound across the four hooks on that path*, not any
  single hook.
- **~85% of it is Python interpreter startup + sibling-module import**, paid
  fresh four times — Claude Code spawns a new `python3` per hook call. The cost
  is import-bound, not logic-bound.
- **Check logic itself is under 10 ms per hook** (logic-only p95: write_guard ~4,
  plan_guard ~6, post_write_check ~5, reflect_trigger ~10). This is the number
  that matters for the import-bound conclusion — a looser "under 50 ms" bound is
  also true but understates it roughly fivefold.
- Stable across two independent passes (170.1 / 169.4 ms p50; 181.7 / 178.3 ms p95).
- **Every 10th source write costs about double, and the figures above do not
  cover it.** On that call `reflect_trigger` spawns `reflect_protocol.py`, so its
  own cost rises from ~40 ms to ~225 ms — which puts that write's *total* added
  wall-clock at roughly **~355 ms** across the four hooks, not ~225 ms. The p50 /
  p95 above describe the other nine writes in ten; a worst-case figure for the
  path must use ~355 ms.

Method: wall-clock around each hook subprocess on the Edit/Write path; N≥80 per
measurement with 5–8 warmup runs discarded; Python 3.14.2, Darwin. Re-measure
before quoting it; do not cite it as current.

---

## What this catalog is not

It is not a runtime probe harness. An earlier proposal for this catalog included a runtime probe module that would test each assumption in-process and return `HELD` / `VIOLATED` / `INCONCLUSIVE`. That proposal was rejected as over-engineered: the assumptions covered here are stable enough across Claude Code releases that a runtime probe surface (with its own maintenance cost and false-positive risk) is not justified by observed drift frequency. The naming and the honest "no pin" admissions in this doc are the smaller, sufficient version of that idea.

It is also not a security claim. Espalier governs Claude Code tool calls structurally; it is not a sandbox. The assumptions above are about how the harness's enforcement reaches the agent, not about what an adversarial agent could do outside that reach.
