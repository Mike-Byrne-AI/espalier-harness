# Removing an information leak can break a contract that silently rode on it

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Removing a leak can break a contract that rode on it"

A "leak" you set out to delete may be doing **two** jobs: the bad one you see
(exposing raw internals to a reader) and a legitimate one you don't (carrying
information some downstream contract quietly depends on). Fix only the first
framing and the second breaks — usually in a test you didn't think you were
touching.

## The evidence (TP-343, 2026-07-25)

The PowerShell dangerous-command denial rendered its **raw regex source** into
the operator-facing reason (`matches pattern '<regex>'`) — the exact TP-189
opacity footgun, and the whole point of the pack was to remove it. But the raw
regex was *also* the only thing making each PS pattern's deny message
**distinct**. A live coupling contract
(`test_every_ps_record_emits_its_own_message_on_match`) asserted per-record
discrimination and had been satisfied **entirely by the leak**. Removing the
leak collapsed both PS denials to one generic string and broke two safety
tests (the coupling contract + `test_blocks_powershell_rm`, which needed
`"Remove-Item"` in the reason).

The real fix was to give the leaked information a **non-leaky carrier**: a
`DANGEROUS_PS_PLAIN` pid→plain-English map (mirroring the already-fixed Bash
side), so each pattern keeps a distinct, honest description without exposing
the regex. The leak's *second* job had to be re-homed, not just deleted.

## Why it matters

The pack had explicitly **scoped this out** ("defer the PS plain-English map —
a separate concern"). That rationale was **falsified by the full suite,
mid-execution** — not by pre-flight reasoning, and not by the 0-A pack review.
The two concerns (remove the leak / build the map) were bound by a contract
nobody saw, because the binding only surfaces when every test runs together. A
green *targeted* run is therefore not evidence the boundary holds — the
mechanical oracle only counts if it actually exercised the binding
([[untrusted-oracle-protocol]]).

## How to apply

1. Before deleting a leak or a redundancy, ask **"what legitimately reads
   this?"** — grep the consumers, and treat every downstream test that inspects
   the leaked value as a contract the fix must satisfy some *other* way.
2. If a value serves a real second purpose, **re-home it** (a plain-English
   map, a stable id) rather than dropping it. Parity with how a sibling surface
   already solved the same problem is the tell for the right carrier.
3. When a scope-out says "separable, defer it," don't trust a targeted green —
   run the **full suite** before honoring the boundary. The binding you can't
   see is exactly the one a targeted run hides.
4. On a mid-pack falsification, surface the fork to the operator (expand vs.
   split) instead of silently expanding; record the deviation + any deferred
   items in the Landing stanza.

The full-suite form of [[verify-a-packs-scope-out-rationale]] (a scope-out is a
claim like any other — here refutable only by the whole oracle); instance of
[[a-packs-prescribed-fix-code-is-a-claim]] and `docs/STANDING_PRINCIPLES.md` §1
(make it prove it).
