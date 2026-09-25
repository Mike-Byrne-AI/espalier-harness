---
source_url: https://code.claude.com/docs/en/hooks.md
fetch_note: |
  The `.md` suffix is LOAD-BEARING -- do not "tidy" it to the bare page URL.
  Without it the origin serves the rendered Mintlify page, and the refresher has
  no HTML-to-markdown step: it stores the response body verbatim, so every
  candidate it wrote from 2026-07-06 onward was a ~3,800-line HTML dump
  (doctype, Next.js chunk tags, font preloads) under this frontmatter. The page
  advertises the markdown twin itself via
  `<link rel="alternate" type="text/markdown" href="/docs/en/hooks.md">`, and
  that URL returns HTTP 200 `text/markdown` under the fetcher's own Accept
  header. Only `source_url` is ever fetched -- `mirrors` is documentation, not a
  fallback -- so this line is the whole difference between a reviewable
  candidate and an unusable one.
redirect_note: |
  As of the 2026-07-20 refresh, the former primary
  https://docs.claude.com/en/docs/claude-code/hooks 301-redirects to
  https://code.claude.com/docs/en/hooks. The mirror is now the canonical
  origin; the docs.claude.com URL is retained below only as the redirect entry.
mirrors:
  - https://docs.claude.com/en/docs/claude-code/hooks
fetched: 2026-07-20
section: "Common output behavior — exit codes and stdout/stderr semantics"
section_anchor: "common-output-behavior"
content_hash: ""
refresh_policy: weekly
purpose: |
  Verification target for Espalier-Harness's hook implementations and any
  espalier doc claim that mentions hook exit codes, stdout, stderr,
  or the structured JSON schema.
---

# Claude Code Hook Protocol — Pinned Excerpt

**Source:** https://docs.claude.com/en/docs/claude-code/hooks (and mirrors at code.claude.com/docs/en/hooks)
**Fetched:** 2026-06-02
**Section:** "Common output behavior" — exit codes and stdout/stderr semantics
**Purpose:** Verification target for Espalier-Harness's hook implementations and any espalier doc claim that mentions hook exit codes, stdout, stderr, or the structured JSON schema.

---

## Channel and exit code semantics

> The exit code from your hook command tells Claude Code whether the action
> should proceed, be blocked, or be ignored.
>
> **Exit 0** means success. Claude Code parses stdout for JSON output fields.
> JSON output is **only** processed on exit 0. For most events, stdout is
> written to the debug log but not shown in the transcript. The exceptions
> are UserPromptSubmit, UserPromptExpansion, and SessionStart, where stdout
> is added as context that Claude can see and act on.
>
> **Exit 2** means a blocking error. Claude Code **ignores stdout and any
> JSON in it**. Instead, **stderr text is fed back to Claude as an error
> message**. The effect depends on the event: PreToolUse blocks the tool
> call, UserPromptSubmit rejects the prompt, and so on.
>
> **Any other exit code** is a non-blocking error for most hook events.
> Execution continues; the transcript shows a `<hook name> hook error`
> notice followed by the first line of stderr, and the full stderr is written
> to the debug log.

The live doc calls out the common trap explicitly: **exit 1 does not block.**

> "For most hook events, only exit code 2 blocks the action. Claude Code treats
> exit code 1 as a non-blocking error and proceeds with the action, even though
> 1 is the conventional Unix failure code."

So a hook that means to deny but returns 1 (e.g. an uncaught exception, or a
naive `sys.exit(1)`) **fails open** — the action proceeds. Only exit 2 (simple
block) or exit 0 + decision JSON (structured block) actually stops it.

## The XOR rule

> You must choose one approach per hook, not both: either use exit codes
> alone for signaling, or exit 0 and print JSON for structured control.
> Claude Code only processes JSON on exit 0. If you exit 2, any JSON is
> ignored. Your hook's stdout must contain only the JSON object.

## PreToolUse decision schema (exit 0 path)

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "<human-readable reason>"
  }
}
```

`permissionDecision` accepts `"allow"`, `"deny"`, `"ask"`, or `"defer"`.
The live doc enumerates them as `permissionDecision (allow/deny/ask/defer)`
(2026-07-20 refresh — `"defer"` is newer than the 2026-06-02 pin's
three-value set). `"defer"` hands off to the normal permission flow (as
though the hook expressed no opinion), distinct from `"ask"`, which forces
an interactive prompt. Espalier's deny paths use `"deny"` only; the added
value does not change the XOR rule above.

## Stop decision schema (exit 0 path)

```json
{
  "decision": "block",
  "reason": "<reason — REQUIRED when decision is block>"
}
```

Note: top-level fields, **not** nested under `hookSpecificOutput`. This
differs from PreToolUse and is a distinct subtle bug class.

## Per-event exit-2 behavior

| Event | Exit 2 effect |
|---|---|
| PreToolUse | Blocks tool call; stderr → Claude |
| PostToolUse | Shows error to Claude (tool already ran) |
| PostToolUseFailure | Shows error to Claude (tool already failed) |
| Stop / SubagentStop | Blocks stoppage; stderr → Claude (forces continuation) |
| SubagentStart | N/A (nothing to block at subagent start); stderr → user |
| UserPromptSubmit | Rejects prompt; stderr → user |
| SessionStart | N/A (nothing to block); stderr → user |
| Notification | N/A; stderr → user |
| ConfigChange | Blocks the settings change; stderr → user |
| PostCompact | N/A (nothing to block post-compaction); stderr → user |

## SessionStart `source` field

> The `SessionStart` hook input carries a `source` field naming what triggered
> the event. The four values are:
>
> - `startup` — a fresh Claude Code launch.
> - `resume` — `--resume`, `--continue`, or `/resume`.
> - `clear` — the `/clear` command.
> - `compact` — context compaction (auto or manual), which fires **mid-session**.

So `SessionStart` is **not** once-per-logical-session: `compact` re-fires it on
every compaction. A hook that mutates per-session state (e.g. advancing a
blueprint chain) must branch on `source` rather than assume a single firing.
These four values are current Claude Code behavior; re-verify on protocol
refresh (a rename is invisible to in-repo tests).

## SubagentStop input fields (verified 2026-09-07, re-verified 2026-09-11)

> Beside the common fields (`session_id`, `transcript_path`, `cwd`,
> `hook_event_name`, `stop_hook_active`), the `SubagentStop` hook input
> carries the subagent's own:
>
> - `agent_id` — unique identifier for the subagent.
> - `agent_type` — the agent name (for example `"Explore"` or
>   `"security-reviewer"`).
> - `agent_transcript_path` — "Path to the subagent's conversation JSON".
> - `last_assistant_message` — "The subagent's final assistant message text".

`subagent_stop.py` reads `agent_type`, `last_assistant_message` and
`agent_transcript_path`: the stop-gate relief record quotes the message's
head, and the blueprint entry carries its lead with the transcript path as
evidence. A rename of either key is invisible to in-repo tests — the hook
then records a content-free anchor per stop — so it prints a `[WARN]` when
the transcript is named but the message is not. Re-verify on protocol
refresh (code.claude.com/docs/en/hooks#subagentstop).

## Context injection: plain stdout vs the `additionalContext` JSON field (2026-06-02 refresh)

The live protocol distinguishes **two** ways a hook puts text in front of the
model, which are easy to conflate:

1. **Plain stdout** (exit 0, no JSON) is added as context the model can act on
   **only** on `UserPromptSubmit`, `UserPromptExpansion`, and `SessionStart`
   (see "Channel and exit code semantics" above). On every other event, plain
   stdout goes to the debug log.
2. **The `hookSpecificOutput.additionalContext` JSON field** (exit 0) is a
   *separate, broader* mechanism. Per the live doc, "where the reminder appears
   depends on the event":
   - `SessionStart`, `Setup`, `SubagentStart` → at the start of the conversation;
   - `UserPromptSubmit`, `UserPromptExpansion` → alongside the submitted prompt;
   - **`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch` → next
     to the tool result;**
   - **`Stop`, `SubagentStop` → at the end of the turn (2026-07-20 refresh).**
     The live doc: "Stop and SubagentStop also accept
     `hookSpecificOutput.additionalContext` for non-error feedback that
     continues the conversation." The turn does not end — Claude continues so it
     can act on the feedback. This is a *second, non-blocking* way for a Stop
     hook to speak, distinct from the top-level `decision: "block"` schema below
     (which forces continuation as an error).

   So `additionalContext` **does** reach the model on `PreToolUse` and
   `PostToolUse` — this is newer than the 2026-05-26 pin and corrects the older
   "PostToolUse is not a first-class context-injector" reading. (Operational
   consequence + the bearing on `docs/HOOK_ASSUMPTIONS.md` Assumption 2 is
   tracked in `docs/HOOK_ASSUMPTIONS.md` → "Resolved open questions".)

   **Large-payload spill (2026-07-20 refresh):** the live doc adds that when
   several hooks return `additionalContext` for the same event, Claude receives
   all of them; and "if a value exceeds 10,000 characters, Claude Code writes
   the full text to a file in the session directory and passes Claude the file
   path with a short preview instead." A hook that emits large context can no
   longer assume the whole string lands inline.

## PostToolUse vs PostToolUseFailure (success / failure split)

The live protocol splits the post-tool boundary into two distinct events:

| Event | Fires |
|---|---|
| `PostToolUse` | After a tool call **succeeds** |
| `PostToolUseFailure` | After a tool call **fails** (e.g. an `Edit` whose `old_string` is not found) |

Both support `additionalContext` (delivered next to the tool result). A hook that
needs to react to a *failed* tool call (e.g. an errored `Edit`) must wire
`PostToolUseFailure`, **not** `PostToolUse` — `PostToolUse` does not fire on tool
errors. (Espalier currently wires neither beyond its existing `PostToolUse`
visibility hooks; this row documents the surface for future use.)

## Event-catalog expansion (2026-07-20 refresh — advisory, not pinned)

Since the 2026-06-02 pin, the live protocol's hook-event catalog has grown well
beyond the ~11 events this excerpt tables. Espalier governs only the subset it
wires (`espalier.harness_config.HOOK_EVENTS`); the rest are out of scope but
worth knowing about when reasoning about the surface. Events the current live
doc lists that are **not** tabled above include, at least: `Setup`,
`UserPromptExpansion`, `PostToolBatch`, `StopFailure`, `PreCompact`,
`PermissionRequest`, `PermissionDenied`, `SubagentStop`, `TaskCreated`,
`TaskCompleted`, `TeammateIdle`, `InstructionsLoaded`, `CwdChanged`,
`FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `MessageDisplay`,
`Elicitation`, `ElicitationResult`, and `SessionEnd`.

**This list is deliberately not exhaustive and no count is pinned.** Two
independent summarizer passes over the same live page disagreed on the total
(one reported 30 events, one 39), so the exact roster is treated as unverified.
Re-derive the authoritative set directly from the source on the next refresh
before relying on any specific event name or count here. The per-event exit-2
and success/failure tables above remain the pinned, test-asserted portion of
this excerpt; this section is orientation only.

## What espalier asserts against this excerpt

- Hook scripts in `tools/cc/hooks/` use exactly one channel per deny path
  (XOR rule). Verified by `tests/test_hook_protocol.py::TestHookProtocolXOR`
  (Espalier source repo).
- `docs/sharp-edges/hook-exit-codes-channel-xor.md` is consistent
  with the channel rule above. Verified by
  `tests/test_documented_claims.py::TestSharpEdgesMatchesProtocol` (Espalier source repo).
- `stop_gate.py` block JSON uses the top-level Stop schema, not the nested
  PreToolUse schema. Verified by
  `tests/test_hook_protocol.py::TestStopGateBlockSchema` (Espalier source repo).
