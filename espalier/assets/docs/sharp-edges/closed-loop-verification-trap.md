# Closed-Loop Verification Trap

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "Closed-Loop Verification Trap"; docs/CONVENTIONS.md section "Closed-loop verification — producer/consumer parity" (if you maintain those indexes)

**What it is:** When implementation, tests, contract tests, and project
docs all agree with each other about a behavior, that agreement is not
evidence of correctness — it is evidence of internal consistency. If the
behavior depends on an external contract (a protocol, a third-party API,
a docs page), internal consistency cannot detect a misreading of that
contract.

**How you hit it:** You write code that emits X. You write a test that
asserts the code emits X. You write a contract test that asserts X is
the right thing to emit. You write a docs entry that explains X is the
right thing to emit. Six months later, the test suite passes, the
contract test passes, the docs are coherent, and X is wrong.

**How to avoid it:** Pin external contracts as files in `docs/external/`
with source URL + fetch date. Write tests (in the Espalier source repo,
`tests/test_documented_claims.py`) that bind project docs (and key
behavior assertions) to those pins, not to other project docs. Treat
any project doc as a *claim that owes a test*, not a source of truth.

**Receipts:** This entry exists because espalier shipped the hook
protocol bug from early development through the first
mechanically-pinned protocol contract — every internal layer agreed
it was correct, no test bound to the external contract. See
`docs/external/`, `tests/test_documented_claims.py`, and
`tests/test_hook_protocol.py` (Espalier source repo) for the structural fix.

**Class signature:** "the artifact under test validates the assertion
about itself." Sister-class to the tautological-test pattern (a test
that calls the function it claims to verify) and the denylist
self-reference paradox (a contract test whose own definition trips
its own assertion). All three share the same root: the verification
loop closes on itself instead of an independent ground truth.

**Detection heuristic:** For any "X is correct" claim, ask "what
independent surface — outside this repo's tree — would notice if X
were wrong?" If the answer is "nothing," the claim is closed-loop;
either pin an external witness or downgrade the claim from "verified"
to "self-consistent."
