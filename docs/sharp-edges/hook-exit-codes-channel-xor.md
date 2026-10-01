# Hook Exit Codes — Channel XOR

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Hook Exit Codes — Channel XOR" (if you maintain an index)

**What it is:** every harness hook carries a deny on exactly one channel
per invocation: the structured deny is JSON on stdout with exit 0, the
simple block is plain text on stderr with exit 2 and nothing on stdout.
Upstream recommends the same split, as advice rather than a limit — per the
pinned excerpt (`docs/external/cc-hook-protocol.md`, "Hook input and
output"), Claude Code "reads JSON output fields from stdout on every exit
code, not just 0", and "Exit 2's block is the one outcome JSON can't
override."

**How you hit it:** Writing `print(json.dumps(...))` followed by
`return 2` — looks like belt-and-suspenders, is actually two voices. The
block fires (exit 2 alone is sufficient) *and* the structured reason is
read, so the deny now exists twice and the hook surfaces only one of the
two.

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
JSON deny payload with a precise reason, prints it to stdout, writes a
shorter generic line to stderr for the terminal, then exits 2 because
"exit 2 also blocks." The block fires — and the reason Claude is shown is
the JSON decision's, because upstream takes "the reason from your JSON's
blocking decision when it makes one, and your stderr text otherwise." The
stderr line is not the blocking message; upstream does not say where it goes
from there, so nothing promises it reaches anyone. The deny the author wrote
for the human is the one nobody is shown.

An earlier version of this entry described the opposite loss — the JSON
reason discarded on exit 2 — and the 2026-09-28 refresh of the pinned
excerpt refuted it. The rule and the fix below are unchanged; only the
mechanism is.

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
