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
  candidate and an unusable one. CONFIRMED WORKING at the 2026-09-28 refresh:
  the candidate is 3,867 lines of real markdown (three stray JSX/`<span>`
  artefacts, no doctype), so the suffix fix held.
redirect_note: |
  As of the 2026-07-20 refresh, the former primary
  https://docs.claude.com/en/docs/claude-code/hooks 301-redirects to
  https://code.claude.com/docs/en/hooks. The mirror is now the canonical
  origin; the docs.claude.com URL is retained below only as the redirect entry.
mirrors:
  - https://docs.claude.com/en/docs/claude-code/hooks
fetched: 2026-09-28
section: "Hook input and output — Exit code output, JSON output, Decision control (the 2026-09-28 page renamed the former 'Common output behavior' section and split it in two)"
section_anchor: "hook-input-and-output"
content_hash: ""
refresh_policy: weekly
purpose: |
  Verification target for Espalier-Harness's hook implementations and any
  espalier doc claim that mentions hook exit codes, stdout, stderr,
  or the structured JSON schema.
---

# Claude Code Hook Protocol — Pinned Excerpt

**Source:** https://code.claude.com/docs/en/hooks.md (formerly docs.claude.com/en/docs/claude-code/hooks, now a 301)
**Fetched:** 2026-09-28
**Section:** "Hook input and output" — "Exit code output", "JSON output", "Decision control", plus the per-event rows espalier wires
**Purpose:** Verification target for Espalier-Harness's hook implementations and any espalier doc claim that mentions hook exit codes, stdout, stderr, or the structured JSON schema.

> ⚠ **THIS REFRESH IS A CONTRACT CHANGE, NOT A RE-WORD.** The 2026-09-28 page
> **inverts** the single sentence this pin existed to carry. The pin's prior
> body said *"JSON output is **only** processed on exit 0"* and *"If you exit 2,
> any JSON is ignored."* Upstream now says the opposite: JSON on stdout is read
> on **every** exit code, and an exit-2 hook's JSON is still read (exit 2's
> *block* is the one thing the JSON cannot override). The channel-XOR rule
> survives only as **advice**, demoted from a protocol constraint to a `<Note>`.
> Read "Channel and exit code semantics" below before trusting any in-repo
> sentence about exit 2 and stdout; the harness's own rationale was corrected
> in the change that landed this excerpt (the note at the end of the file).

---

## Channel and exit code semantics

Upstream, verbatim (the section's opening paragraph):

> The exit code from your hook command tells Claude Code whether the action
> should proceed, be blocked, or be ignored. The exit code doesn't act alone.
> Claude Code reads [JSON output fields](https://code.claude.com/docs/en/hooks#json-output) from stdout on every
> exit code, not just 0, and for events that use the standard decision model, a
> parsed object that passes schema validation takes effect alongside the code.
> Exit 2's block is the one outcome JSON can't override.

**Exit 0** (verbatim):

> Exit 0 means success, and is the intended exit code when you print JSON for
> structured control.
>
> For most events, Claude Code writes stdout to the debug log and doesn't show
> it in the transcript. The exceptions are `UserPromptSubmit`,
> `UserPromptExpansion`, `SessionStart`, and `PostModelSwitch`, where Claude
> Code adds plain-text stdout as context that Claude can see and act on.

Whether stdout is read as JSON or as plain text is now a **syntactic** test, not
a channel declaration (verbatim):

> Whether Claude Code reads your stdout as [JSON output](https://code.claude.com/docs/en/hooks#json-output) or as
> plain text depends on how it starts and ends, ignoring surrounding whitespace:
>
> * **Starts with `{` and ends with `}`**: Claude Code parses it as JSON. When
>   the output is two or more lines that each parse as JSON on their own, and no
>   line is a [JSON output](https://code.claude.com/docs/en/hooks#json-output) object that sets a field, Claude Code
>   treats the whole output as plain text. When one of those lines does set a
>   field, the whole output is a parse failure, described below.
> * **Starts with `{` but doesn't end with `}`**: Claude Code treats it as plain text.
> * **Starts with anything else**: Claude Code treats it as plain text, a JSON
>   array or a quoted JSON string included.

A malformed or schema-invalid JSON object is now itself an error class
(verbatim):

> For events that use the standard decision model, exit 0 with a parsed object
> that fails schema validation is a non-blocking error: the action proceeds, and
> the transcript shows a `<hook name> hook error` notice with the validation
> message. The same happens on any exit code other than 2, while
> [exit 2 still blocks](https://code.claude.com/docs/en/hooks#exit-code-2).
>
> For events that use the standard decision model, when Claude Code tries to
> parse your stdout as JSON and can't, it reports a non-blocking error on every
> exit code other than 2. The transcript shows a `<hook name> hook error` notice
> with the parse message. On the events that add plain-text stdout as context,
> Claude Code doesn't add the text. Before v2.1.248, Claude Code treated that
> stdout as plain text.

**Exit-0 stderr is debug-log-only. This is now stated outright** (verbatim — the
sentence to quote whenever an espalier doc claims a hook's stderr is visible):

> Stderr from a hook that exits 0 goes to the debug log only, never the
> transcript, and Claude never sees it. To read it yourself, enable
> [debug logging](https://code.claude.com/docs/en/hooks#debug-hooks). To surface a warning to Claude from a
> `PostToolUse` or `PostToolUseFailure` hook, exit 2 instead so
> [Claude sees the stderr](https://code.claude.com/docs/en/hooks#exit-code-2-behavior-per-event) even though the tool
> already ran.

**Exit 2** (verbatim):

> Exit 2 means a blocking error. On [events that can block](https://code.claude.com/docs/en/hooks#exit-code-2-behavior-per-event),
> exit 2 blocks whether or not you print JSON: even a JSON `permissionDecision`
> of `"allow"` can't override it. Claude Code still reads any valid
> [JSON output](https://code.claude.com/docs/en/hooks#json-output) on stdout. On `Elicitation` and
> `ElicitationResult`, an exit-2 hook's `hookSpecificOutput` is ignored.
>
> The blocking message is the reason from your JSON's blocking decision when it
> makes one, and your stderr text otherwise. What the block does varies by
> event: `PreToolUse` blocks the tool call, `UserPromptSubmit` rejects the
> prompt, and so on.
>
> A hook that exits 2 while printing JSON that fails [JSON output](https://code.claude.com/docs/en/hooks#json-output)
> schema validation still blocks: Claude Code uses stderr as the blocking reason
> and records the validation failure in the debug log. Before v2.1.214, Claude
> Code treated that combination as a non-blocking error and the action proceeded.

**Any other exit code** no longer "fails open" unconditionally — a valid JSON
object now *overrides* the code (verbatim):

> Any other exit code doesn't block on its own for most hook events. What
> happens depends on your stdout:
>
> * With a parsed object that passes schema validation, for events that use the
>   standard decision model, Claude Code ignores the exit code and the JSON
>   alone decides the outcome:
>   * Each field the event supports is honored, including `permissionDecision`,
>     `additionalContext`, `updatedInput`, and `systemMessage`, and the hook
>     isn't reported as an error.
> […]
> * With a parsed object that fails schema validation […] the action proceeds,
>   and the `<hook name> hook error` notice carries the validation message.
> * With stdout that Claude Code [tries to parse as JSON](https://code.claude.com/docs/en/hooks#exit-code-0) and
>   can't, Claude Code reports the same non-blocking error as on exit 0 […].
> * With stdout that Claude Code [treats as plain text](https://code.claude.com/docs/en/hooks#exit-code-0), or with
>   empty stdout, it's a non-blocking error for most hook events: the action
>   proceeds, and the transcript shows a `<hook name> hook error` notice
>   followed by the first line of stderr, prefixed with
>   `Failed with non-blocking status code:`.

The live doc still calls out the common trap explicitly: **exit 1 does not
block** — but it now scopes the warning to the no-valid-JSON case (verbatim,
from the page's `<Warning>` block):

> For most hook events, exit code 2 is the only exit code that blocks through
> the code alone. Without valid JSON on stdout, Claude Code treats exit code 1
> as a non-blocking error and proceeds with the action, even though 1 is the
> conventional Unix failure code. If your hook is meant to enforce a policy, use
> `exit 2`. The worktree events differ: any non-zero exit code from
> `WorktreeCreate` aborts worktree creation, and any non-zero exit code from
> `WorktreeRemove` makes worktree removal fail if the directory still exists
> afterward.

So a hook that means to deny but returns 1 **with no stdout JSON** (e.g. an
uncaught exception, or a naive `sys.exit(1)`) still **fails open** — the action
proceeds, and the `Failed with non-blocking status code:` notice is the tell.
This is the behaviour espalier's per-hook `BaseException` umbrellas exist for;
it is unchanged. What *has* changed is that exit 1 is no longer *categorically*
fail-open: exit 1 plus a schema-valid deny object is now honoured.

A hook that cannot start lands in the same bucket (verbatim):

> When the script path doesn't exist or isn't executable, the shell exits with a
> code like 127 and you see the same notice with the interpreter's message, for
> example `Failed with non-blocking status code: /bin/sh: /path/to/hook.sh: No
> such file or directory`. For most hook events, the action proceeds. When you
> set up a policy hook, watch for this notice on its first run: a mistyped path
> in `settings.json` leaves the gate silently disabled.

## Timeouts (new section, 2026-09-28)

> Apart from a command hook you run with [`async: true`](https://code.claude.com/docs/en/hooks#run-hooks-in-the-background),
> Claude Code cancels a `command`, `http`, or `mcp_tool` hook that reaches its
> [`timeout`](https://code.claude.com/docs/en/hooks#common-fields), discarding the hook's output, so on most events a
> timed-out hook renders no decision.
>
> On [`PreModelSwitch`](https://code.claude.com/docs/en/hooks#premodelswitch), a hook canceled at its timeout blocks
> the model switch. On `PreToolUse`, the two hook families differ:
>
> * A timed-out `command`, `http`, or `mcp_tool` hook doesn't block the tool
>   call. The call continues through the normal [permission flow](https://code.claude.com/docs/en/permissions),
>   so don't count on a stalled hook to act as a gate.
> * An [Agent SDK callback hook](https://code.claude.com/docs/en/agent-sdk/hooks) that exceeds its
>   timeout [blocks the tool call](https://code.claude.com/docs/en/hooks#pretooluse).

A timed-out espalier `command` guard therefore **fails open** on `PreToolUse`,
with no notice beyond the debug log. `write_guard` keeps its own time budget,
3.5 s from the hook's start and below its wired 5 s `timeout`, and denies
(its usual deny decision, the reason asking for the command to be split) a
call whose judgment is still running when the budget runs out, so its
judgment never reaches the timeout. `plan_guard` and `config_guard` keep no budget:
their judgments read one path or one settings file. No in-repo test pins a hook's wall-clock
cost against the configured `timeout`.

## The XOR rule (now ADVICE, not a protocol constraint)

The 2026-09-28 page keeps the one-channel recommendation but reverses its
mechanical justification. Verbatim, the `<Note>` under "JSON output":

> Choose one approach per hook: either use exit codes alone for signaling, or
> exit 0 and print JSON for structured control. If you mix them, exit 2 keeps
> its [blocking effect](https://code.claude.com/docs/en/hooks#exit-code-2-behavior-per-event), and Claude Code still
> reads the JSON fields, with the one elicitation exception noted under
> [Exit code 2](https://code.claude.com/docs/en/hooks#exit-code-2).

And, still verbatim:

> Your hook's stdout must contain only the JSON object. If your shell profile
> prints text on startup, it can interfere with JSON parsing.

**What this means for espalier.** The *advice* espalier follows is still the
documented advice, and every espalier hook still picks exactly one channel, so
no hook's behaviour changes. But the *failure mode* the harness documents —
"exit 2 + stdout JSON silently discards the reason" — is **no longer the live
behaviour**: upstream now reads the JSON and, when it carries a blocking
decision, prefers that decision's `reason` over stderr as the blocking message.
`TestHookProtocolXOR` remains a legitimate house-style gate (one channel per
deny path is still what every espalier hook does, and the mixed form is still
discouraged upstream); it is no longer a gate against *data loss*.

## PreToolUse decision schema (the structured path)

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "<human-readable reason>"
  }
}
```

`permissionDecision` accepts `"allow"`, `"deny"`, `"ask"`, or `"defer"` —
unchanged from the 2026-07-20 pin. Upstream, verbatim on the fields espalier
uses:

> `"deny"` prevents the tool call. […] [Deny and ask rules](https://code.claude.com/docs/en/permissions#manage-permissions)
> are still evaluated regardless of what the hook returns

> `permissionDecisionReason` — For `"allow"` and `"ask"`, shown to the user but
> not Claude. For `"deny"`, shown to Claude. For `"defer"`, ignored

New since the 2026-07-20 pin, and relevant to a multi-hook `*` matcher:

> When multiple PreToolUse hooks return different decisions, precedence is
> `deny` > `defer` > `ask` > `allow`.

> A hook that blocks by exiting 2 routes the same way as `"deny"`: Claude sees
> the stderr message as the denial reason.

> PreToolUse previously used top-level `decision` and `reason` fields, but these
> are deprecated for this event. […] The deprecated values `"approve"` and
> `"block"` map to `"allow"` and `"deny"` respectively. Other events like
> PostToolUse and Stop continue to use top-level `decision` and `reason` as
> their current format.

`"defer"` is honoured **only** in non-interactive `-p` mode and only when Claude
makes a single tool call in the turn; in an interactive session upstream "logs a
warning and ignores the hook result." Espalier's deny paths use `"deny"` only.

## Stop decision schema (the structured path)

```json
{
  "decision": "block",
  "reason": "<reason — REQUIRED when decision is block>"
}
```

Note: top-level fields, **not** nested under `hookSpecificOutput`. This differs
from PreToolUse and is a distinct subtle bug class. Still true at 2026-09-28 —
upstream's Decision-control table puts Stop in the "Top-level `decision`" row,
and its own example is the two-key object above.

New since the 2026-07-20 pin, and load-bearing for `stop_gate`'s re-block loop
(verbatim):

> The `stop_hook_active` field is `true` when Claude Code is already continuing
> as a result of a stop hook. Check this value or process the transcript to
> avoid blocking on a condition that will never resolve. Claude Code applies an
> 8-consecutive-continuation cap: after stop hooks have continued the turn eight
> times in a row, Claude Code overrides the next block and ends the turn. To
> raise the cap, set [`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`](https://code.claude.com/docs/en/env-vars).

> A hook that blocks by exiting 2 routes the same way as `reason`: Claude
> receives the stderr message as the explanation for why it should continue.

The `additionalContext` alternative is unchanged in substance and now carries a
named transcript label (verbatim):

> `hookSpecificOutput.additionalContext` — Non-error feedback for Claude. The
> conversation continues so Claude can act on it, but unlike `decision: "block"`
> it is shown in the transcript as hook feedback rather than a hook error
>
> […] It keeps the conversation going through the same loop protections as
> `decision: "block"`, namely the `stop_hook_active` input and the
> 8-consecutive-continuation cap, but the transcript labels it
> `Stop hook feedback` and no hook error notification is shown

## Per-event exit-2 behavior

Upstream's table, restricted to the ten events espalier wires plus the two the
old pin tabled. Rows are verbatim from the 2026-09-28 "Exit code 2 behavior per
event" table.

| Event | Can block? | What happens on exit 2 |
|---|---|---|
| `PreToolUse` | Yes | Blocks the tool call |
| `UserPromptSubmit` | Yes | Blocks prompt processing and erases the prompt |
| `PostToolUse` | No | Shows stderr to Claude; the tool already ran |
| `PostToolUseFailure` | No | Shows stderr to Claude; the tool already failed |
| `Stop` | Yes | Prevents Claude from stopping, continues the conversation |
| `SubagentStop` | Yes | Prevents the subagent from stopping |
| `SubagentStart` | No | Shows stderr to user only |
| `SessionStart` | No | Shows stderr to user only |
| `ConfigChange` | Yes | Blocks the configuration change from taking effect (except `policy_settings`) |
| `PostCompact` | No | Shows stderr to user only |
| `Notification` | No | Exit code and stderr are ignored |
| `PostToolBatch` | Yes | Stops the agentic loop before the next model call |

⚠ **"Shows stderr to user only" is narrower than it reads, and the 2026-09-28
page says so explicitly** (verbatim):

> For `SessionStart`, `SubagentStart`, and `PostModelSwitch`, Claude Code
> renders the exit code 2 stderr in the transcript as a `<hook name> hook error`
> notice, the same way it renders a [non-blocking error](https://code.claude.com/docs/en/hooks#exit-code-output).
> Claude doesn't see it, and the session or subagent proceeds. For
> `SubagentStart`, the notice appears in the subagent's own transcript, not in
> the parent conversation.

So a SessionStart hook's stderr reaches the **operator's screen only on exit 2**,
dressed as a hook *error*. On exit 0 — which every espalier reporter uses — it
reaches the debug log and nothing else.

`ConfigChange`'s block is now documented as silent (verbatim):

> Claude Code acts on the blocking decision from a ConfigChange hook's JSON
> output and discards `systemMessage` and `continue`. A blocked change surfaces
> no message to you or to Claude, whether you block with `reason` or with stderr
> on exit 2. Claude Code only writes a line to the debug log.

> `reason` — Accepted but never shown

`PostCompact` likewise: "Claude Code discards a PostCompact hook's
`systemMessage` and `continue` fields" and "PostCompact hooks have no decision
control."

## SessionStart `source` field

The 2026-07-20 pin's four values are now **five** (verbatim):

> | Matcher   | When it fires |
> | `startup` | New session |
> | `resume`  | `--resume`, `--continue`, or `/resume` |
> | `clear`   | `/clear` |
> | `compact` | Auto or manual compaction |
> | `fork`    | A new session forked from an existing one: `--fork-session` with `--resume` or `--continue`, the `/fork` background copy, or `/branch` |
>
> Before v2.1.214, forked sessions reported source `"resume"`.

So `SessionStart` is **not** once-per-logical-session: `compact` re-fires it on
every compaction. A hook that mutates per-session state (e.g. advancing a
blueprint chain) must branch on `source` rather than assume a single firing.

⚠ **`"fork"` is a FIFTH value the harness has never seen, and it SPLITS the two
source predicates in `session_start.py`.** Both predicates are closed sets with
deliberate, documented defaults, and `"fork"` falls on opposite sides of each:
`_NEW_SESSION_SOURCES = {"startup", "clear"}` gates blueprint-chain advance, so
a fork does **not** start a new node (the comment: "An unknown/absent source
fails toward NOT advancing"); `_CONTINUATION_SOURCES = {"resume", "compact"}`
gates per-session flag preservation, so a fork **does** clear the stop-gate,
speedbump and reinject counters (the comment: "an unlabeled/unknown payload —
clears"). A fork is therefore continuation-shaped for the chain and
fresh-session-shaped for the gates. That may well be the right mix — a forked
session legitimately continues the parent's blueprint — but the split is now
reachable by a *named* source rather than only by a malformed payload, and no
in-repo test exercises it. Re-verify both predicates on the next refresh; a new
enum member is invisible to in-repo tests.

Also new and relevant to the SessionStart banner (verbatim):

> When you start an interactive session, resume a conversation at launch with
> `--continue` or `--resume`, or run `/clear`, SessionStart hooks run in the
> background. You can type right away […] Claude's first response still waits
> for the hooks to finish, so their context reaches Claude.
>
> […] If you run `/clear` or switch to another conversation while background
> hooks are still running, nothing they return applies to the session.

And the eight-second banner budget now has a stated consequence: a `/clear`
during a slow SessionStart drops the hook's whole output.

SessionStart's own JSON fields are now five, three of them new since the
2026-07-20 pin: `additionalContext`, `initialUserMessage`, `sessionTitle`,
`watchPaths`, `reloadSkills`. Espalier uses `additionalContext` only.

## SubagentStop input fields (verified 2026-09-07, re-verified 2026-09-11, re-verified 2026-09-28)

Upstream, verbatim:

> In addition to the [common input fields](https://code.claude.com/docs/en/hooks#common-input-fields), SubagentStop
> hooks receive `stop_hook_active`, `agent_id`, `agent_type`,
> `agent_transcript_path`, and `last_assistant_message`. The `agent_type` field
> is the value used for matcher filtering. The `transcript_path` is the main
> session's transcript, while `agent_transcript_path` is the subagent's own
> transcript stored in a nested `subagents/` folder. The `last_assistant_message`
> field contains the text content of the subagent's final response, so hooks can
> access it without parsing the transcript file.

All four keys `subagent_stop.py` reads are still present and still spelled the
same. Two new facts bear on it (verbatim):

> Not every SubagentStop event comes from a subagent Claude spawned. Claude Code
> also runs internal agents for some of its own features, such as
> [prompt suggestions](https://code.claude.com/docs/en/interactive-mode#prompt-suggestions) and
> [`/btw` side questions](https://code.claude.com/docs/en/interactive-mode#side-questions-with-%2Fbtw),
> and SubagentStop fires when one of those finishes too. For those events,
> `agent_type` is the agent name the session itself runs as […] and an empty
> string when the session runs without one.

> On Claude Code v2.1.271 or later, a subagent that runs with the
> [`SubagentHandback`](https://code.claude.com/docs/en/tools-reference) tool delivers its report through
> that tool before it stops. The `last_assistant_message` field then holds the
> subagent's closing text, if any, which is not the delivered report. The report
> is that call's `message` input, which a `PreToolUse` or `PostToolUse` hook
> matched on `SubagentHandback` receives as `tool_input.message`.

⚠ Both are blueprint-pollution shapes for `subagent_stop.py`. The hook reads
`agent_type = str(data.get("agent_type", "")) or "unknown"`
(`tools/cc/hooks/subagent_stop.py::_run_main`), so a `/btw` side question or a prompt-suggestion
agent — neither of which the operator dispatched — now appends a
`[subagent:unknown] <lead>` entry to the active blueprint; and a
`SubagentHandback` subagent's recorded lead is its closing chatter rather than
its report. Neither is pinned by any in-repo test.

## Context injection: plain stdout vs the `additionalContext` JSON field

The live protocol still distinguishes **two** ways a hook puts text in front of
the model, which are easy to conflate:

1. **Plain stdout** (exit 0, no JSON) is added as context the model can act on
   **only** on `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and
   — new at 2026-09-28 — `PostModelSwitch`. On every other event, plain stdout
   goes to the debug log.
2. **The `hookSpecificOutput.additionalContext` JSON field** is a *separate,
   broader* mechanism. Per the live doc, "Where the reminder appears depends on
   the event":
   - `SessionStart`, `SubagentStart` → "at the start of the conversation, before the first prompt";
   - `UserPromptSubmit`, `UserPromptExpansion` → "alongside the submitted prompt";
   - **`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch` → "next to the tool result";**
   - **`Stop`, `SubagentStop` → "at the end of the turn. The conversation continues so Claude can act on the feedback."**
   - `PostModelSwitch` → "with the next request after the switch."

   Note the 2026-09-28 wording drops `Setup` from the start-of-conversation row
   that the 2026-07-20 pin listed; `Setup` now sits in the Decision-control
   table's "None / No decision control" row.

   So `additionalContext` **does** reach the model on `PreToolUse` and
   `PostToolUse` — unchanged since the 2026-07-20 pin, and still the correction
   of the older "PostToolUse is not a first-class context-injector" reading.
   (Operational consequence + the bearing on `docs/HOOK_ASSUMPTIONS.md`
   Assumption 2 is tracked in `docs/HOOK_ASSUMPTIONS.md` → "Resolved open
   questions".)

   New mechanics, verbatim:

   > Claude Code wraps the string in a [system reminder](https://code.claude.com/docs/en/glossary#system-reminder)
   > and inserts it into the conversation at the point where the hook fired.
   > Claude reads the reminder on the next model request, but it doesn't appear
   > as a chat message in the interface.

   > When several hooks return `additionalContext` for the same event, Claude
   > receives all of the values.

   **Large-payload spill (now a general 10,000-character cap, measured per
   string).** The 2026-07-20 pin recorded this for `additionalContext` only; it
   now covers `additionalContext`, `systemMessage`, `initialUserMessage` **and
   plain stdout** (verbatim):

   > A hook's `additionalContext`, `systemMessage`, and `initialUserMessage`
   > strings, and its plain stdout, are capped at 10,000 characters:
   >
   > * **Scope**: Claude Code measures each string on its own, even when several
   >   hooks run for the same event. For JSON output, each field is measured
   >   separately; plain stdout is measured whole.
   > * **Over the limit**: Claude Code saves the output to a file in the session
   >   directory and replaces it with the file path and a preview of up to the
   >   first 2,000 characters. […] Unlike that Bash ceiling, this cap has no
   >   setting or environment variable to raise it.
   > * **Reading the file**: Claude Code doesn't ask Claude to read the file, so
   >   keep anything Claude must always see within the cap.

   ⚠ This is the sharpest operational change in the refresh for espalier: the
   SessionStart banner is **plain stdout**, now explicitly capped at 10,000
   characters *measured whole*, with the overflow replaced by a file path Claude
   is **not** asked to read. A banner that grows past the cap degrades silently
   to a pointer.

   Two further new facts about `additionalContext` (verbatim):

   > Write the text as factual statements rather than imperative system
   > instructions. […] Text framed as out-of-band system commands can trigger
   > Claude's prompt-injection defenses, which causes Claude to surface the text
   > to you instead of treating it as context.

   > Claude Code saves the injected text in the session transcript. For
   > mid-session events like `PostToolUse` or `UserPromptSubmit`, when you resume
   > with `--continue` or `--resume`, Claude Code replays the saved text rather
   > than re-running the hook for past turns, so values like timestamps or commit
   > SHAs become stale.

`suppressOutput` is now documented as inert (verbatim):

> `suppressOutput` […] — Has no effect: Claude Code accepts the field but doesn't
> act on it. A successful hook's stdout is never shown in the transcript and is
> recorded in the debug log

## PostToolUse vs PostToolUseFailure (success / failure split)

Unchanged in substance, and now with an explicit non-firing clause.

| Event | Fires |
|---|---|
| `PostToolUse` | "Runs immediately after a tool completes successfully." |
| `PostToolUseFailure` | "Runs when a tool that started executing fails: the tool threw an error, or an MCP tool returned an error result." |

Both support `additionalContext` (delivered next to the tool result). New,
verbatim, and load-bearing for `context_reinject_failure.py`:

> This event doesn't fire for tool calls rejected before execution: an unknown
> tool name, input that fails schema or tool-specific validation, or a
> permission denial. Validation rejections are returned as `tool_use_error`
> results and happen before hooks run, so they fire neither `PreToolUse` nor
> `PostToolUseFailure`. Permission denials fire `PreToolUse` but not this event;
> see [PermissionDenied](https://code.claude.com/docs/en/hooks#permissiondenied).

Also new, and relevant to `post_write_check.py`'s `Bash` matcher:

> To run a hook when a specific file changes on disk, whatever wrote it, use
> [FileChanged](https://code.claude.com/docs/en/hooks#filechanged). Claude Code doesn't run a `PostToolUse` hook
> matching `Edit|Write` when a `Bash` command or a process outside Claude Code
> rewrites the same file.

## Worktree events: `WorktreeCreate` and `WorktreeRemove`

<!-- re-excerpt 2026-10-10, scoped to these two events and read by hand off
     the page fetched that day. The rest of this excerpt is NOT re-verified,
     so `fetched` above stays 2026-09-28: upstream has since rewritten "Exit
     code output", and 12 of the 32 passages quoted above no longer appear
     on the page word for word (read as a reword of the contract recorded
     above, not a reversal). The refresh loop's quote check is the forward
     ledger's DEF-744. The closed 2026-10-05 refresh pull request carried these
     events as a raw page diff; the page has moved since (WorktreeRemove,
     below). -->

Espalier wires neither event (`espalier.harness_config.HOOK_EVENTS`). This
section is the verification target for why a worktree session's seat name is
set by the SessionStart hook (`tools/cc/hooks/session_start.py::_seat_line`)
rather than by a `WorktreeCreate` hook: see "Observed" at its end.

The page's event table:

> | Event | When it fires |
> | :- | :- |
> | `WorktreeCreate` | When a worktree is being created via `--worktree`, `isolation: "worktree"`, or for a background session. Replaces default git behavior |
> | `WorktreeRemove` | When a worktree that a `WorktreeCreate` hook created is being removed |

### `WorktreeCreate` replaces git's creation and must print the path

> By default Claude Code creates the isolated working copy with `git worktree`.
> Configuring a WorktreeCreate hook replaces that default git behavior, letting
> you use a different version control system like SVN, Perforce, or Mercurial.
>
> Because the hook replaces the default behavior entirely, `.worktreeinclude` is
> not processed. If you need to copy local configuration files like `.env` into
> the new worktree, do it inside your hook script.

Its input, beyond the common fields:

> In addition to the common input fields, WorktreeCreate hooks receive the
> `name` field. This is a slug identifier for the new worktree, either
> specified by the user or auto-generated, for example `bold-oak-a3f2`.

Its output, and what fails it:

> * **Command hooks** (`type: "command"`): print the path as the last non-empty
>   line of stdout. Claude Code strips ANSI escape codes before reading that
>   line, so shell startup banners printed before your `echo` are ignored.
>   Redirect any other hook output to stderr.
> * **HTTP hooks** (`type: "http"`): return `{ "hookSpecificOutput": { "hookEventName": "WorktreeCreate", "worktreePath": "/absolute/path" } }` in the response body.
>
> If the hook fails or produces no path, worktree creation fails with an error.

> * **`WorktreeCreate`**: any non-zero exit code makes worktree creation fail,
>   whatever your JSON says.

> Claude Code refuses an absolute path that contains `.` or `..` segments, and
> any path that passes through a symlink below the repository root, because a
> symlink committed to the repository could redirect the worktree outside it.
> […] Before v2.1.216, worktree creation followed the hook's path without this
> screening.

### `WorktreeRemove` fires only for a worktree the hook created

> Runs when Claude Code cleans up a worktree that your `WorktreeCreate` hook
> created. The event fires when:
>
> * You exit an interactive worktree session and choose to remove the worktree
>   when Claude Code prompts you
> * You exit an interactive worktree session you haven't named, Claude Code
>   finds no changed or untracked files, and it removes the worktree without
>   prompting you
> * You delete a background session that runs in the worktree
>
> Claude Code uses git to look for changed or untracked files, so it finds none
> in a worktree that isn't a git checkout or inside one, even when the
> directory holds uncommitted work. Check for that work in your WorktreeRemove
> hook before it deletes anything.

> * **No WorktreeRemove hook**: when Claude Code removes the worktree as you exit
>   a worktree session, it falls back to `git worktree remove --force` on the
>   path your WorktreeCreate hook returned, so a worktree git recognizes is
>   removed. […]
> * **Hook exits 0**: the worktree counts as removed. Claude Code reads nothing
>   else from the hook, so make sure your hook deleted the directory.
> * **Hook exits non-zero**: the removal fails if the directory at
>   `worktree_path` still exists afterward, and the worktree stays on disk with
>   no git fallback. […]

> In addition to the common input fields, WorktreeRemove hooks receive the
> `worktree_path` field, which is the absolute path to the worktree being
> removed.

> Claude Code discards a WorktreeRemove hook's JSON output fields, such as
> `systemMessage` and `continue`.

**Changed since the 2026-10-05 refresh candidate:** its event table row read
"When a worktree is being removed at session exit, when a subagent finishes,
or when you delete a background session", and its trigger list included "a
subagent with `isolation: "worktree"` finishes". The 2026-10-10 page scopes the
event to worktrees a `WorktreeCreate` hook created and drops the subagent
trigger; the unnamed-session auto-removal and the git-detection warning are
new.

### Observed, not quoted (driven 2026-10-09)

Windows host, Claude Code 2.1.295, git 2.52.0: headless
`claude -p --worktree <name>` sessions in throwaway repositories, with logging
hooks on SessionStart, UserPromptSubmit, Stop, WorktreeRemove and, where
configured, WorktreeCreate.

- A configured `WorktreeCreate` hook fired before any other hook, with the
  session's own `session_id`; its payload's `cwd` and `CLAUDE_PROJECT_DIR` both
  named the main checkout. SessionStart then ran inside the worktree.
- A `WorktreeCreate` hook that exits 1 ends the run before it starts:
  `Error creating worktree: WorktreeCreate hook failed: ...`, the child exits
  1, and no session begins.
- Claude Code held no `git worktree lock` on a worktree the hook made, though
  it did on the ones it made with git.
- No headless session removed its worktree at exit, and `WorktreeRemove` never
  fired, which matches the trigger list above (interactive exits and
  background-session deletes only).

Hence the choice of SessionStart: a `WorktreeCreate` hook would have to rebuild
creation (the branch, the base, the settings copy, the cleanup), would lose the
lock, and would fail closed, so a traceback or a missing interpreter in it
would stop every `--worktree` session, subagent worktree and background session
from starting.

## Event-catalog expansion (advisory, not pinned)

The live protocol's hook-event catalog continues to exceed the subset this
excerpt tables. Espalier governs only the subset it wires
(`espalier.harness_config.HOOK_EVENTS`); the rest are out of scope but worth
knowing about when reasoning about the surface. The 2026-09-28 page's `###`
event headings, read directly off the candidate rather than summarized, are:
`SessionStart`, `Setup`, `InstructionsLoaded`, `UserPromptSubmit`,
`UserPromptExpansion`, `MessageDisplay`, `PreToolUse`, `PermissionRequest`,
`PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `PermissionDenied`,
`Notification`, `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`,
`Stop`, `StopFailure`, `TeammateIdle`, `ConfigChange`, `CwdChanged`,
`DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`,
`PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`, `SessionEnd`,
`Elicitation`, `ElicitationResult` — **33 events**.

**No count is pinned.** The 2026-07-20 pin recorded two summarizer passes
disagreeing (30 vs 39) and treated the roster as unverified; this refresh's
33 is a mechanical heading count off the saved candidate (grep of `^### ` under
`## Hook events`), which is a better oracle than a summary but still a page
snapshot, not a contract. `DirectoryAdded`, `PreModelSwitch` and
`PostModelSwitch` are new since that pin; `TaskCreated`/`TaskCompleted`/
`TeammateIdle` are now fully specified rather than list-only. The per-event
exit-2 and success/failure tables above remain the pinned, test-asserted portion
of this excerpt; this section is orientation only.

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

<!-- re-excerpt 2026-10-01: upstream's rewrite of this page inverted the
exit-code contract (stdout JSON is read on every exit code; exit 2's block is
the one outcome JSON cannot override; an exit-0 hook's stderr never reaches the
transcript). The harness's house rule -- one channel per deny -- stands as
style; its written rationale, five observability claims and three tests were
corrected in the change that landed this excerpt. The refresher's bound tests
read this pin, never a candidate; the forward ledger carries that row. -->
