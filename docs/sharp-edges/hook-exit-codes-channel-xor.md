# Hook Exit Codes — Channel XOR

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Hook Exit Codes — Channel XOR" (if you maintain an index)

**What it is:** Claude Code processes structured hook output via exactly
one channel per hook invocation. Mixing channels silently fails. Per the
official docs: JSON on stdout is **only** processed on exit 0; on exit 2,
stdout is ignored and stderr is fed back to Claude.

**How you hit it:** Writing `print(json.dumps(...))` followed by
`return 2` — looks like belt-and-suspenders, is actually neither. The
block fires (exit 2 alone is sufficient) but the structured reason
never reaches Claude.

**How to avoid it:** Pick one path per hook:

- **Structured (preferred):** `exit 0` + valid JSON on stdout with the
  event-specific decision schema
  (`hookSpecificOutput.permissionDecision` for PreToolUse; top-level
  `decision: "block"` + `reason` for Stop).
- **Simple:** `exit 2` + plain reason on stderr, no stdout JSON.

`sys.exit(1)` is reserved for script bugs, never for governance
decisions.

**How it's enforced:** `tests/test_hook_protocol.py::TestHookProtocolXOR`
(Espalier source repo) asserts each hook obeys exactly one channel. The test runs against
pinned external excerpts in `docs/external/cc-hook-protocol.md`.

**Worked failure mode:** A PreToolUse hook decides to deny, builds a
JSON deny payload, prints it to stdout, then exits 2 because "exit 2
also blocks." Claude Code sees exit 2, reads stderr (empty), and
surfaces a generic "hook denied" message. The carefully-crafted JSON
reason is in stdout but discarded. The operator sees the block but
not the why; the audit trail loses the reason field.

**Worked fix:** Replace `print(json.dumps(deny_payload)); sys.exit(2)`
with `print(json.dumps(deny_payload)); sys.exit(0)`. Same block
outcome, structured reason preserved, audit trail intact.

**Why this class recurs:** The exit-code conventions across most
Unix tooling — `0 = success / allow`, `1 or 2 = failure / deny` —
make exit 2 + JSON feel correct. Claude Code's protocol inverts
the convention specifically because hooks can be advisory (exit 0
with no JSON = no decision, just observability). Pinning the
contract as a file in `docs/external/` and binding tests to that
pin is the structural fix; instinct alone won't catch the inversion.
