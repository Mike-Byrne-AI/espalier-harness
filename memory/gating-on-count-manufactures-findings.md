# Gating on count manufactures findings

**Status:** active

**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md` folder router and sibling cross-links (the ESPALIER_MEMORY.md hot index is at its 120-line cap; not indexed there).

A quality gate over a process whose **honest output can be zero** must gate on
**process + reproducibility, never on finding COUNT**. A count-floor (require N
findings / N blockers to "pass") inverts the null-is-the-signal principle and
*trains the agent to fabricate* — an honest null (the red-team ran and found zero
reproducible blockers) must PASS, or the gate is worse than no gate.

This is the design rule the `espalier/red_team_guard.py` build distilled (commit
`73a3308`; Integration A wired into `scripts/run_pack_chain.sh`, `574b7b8`):

- **Force what is mechanizable; never reward count.** For every finding that
  claims `blocks_release` / `severity: blocker`, the red-team must ship an
  EXECUTABLE repro `{id, argv, expect: "fail", match: <specific non-catch-all
  regex>}`; the gate *re-runs the argv in an external oracle* and the blocker
  passes only when the command **fails with that specific signature**.
  Re-execution is the teeth; the template is only the shell.
  `passed = no unverified blocker` → zero blockers ⇒ zero unverified ⇒ pass.
- **Diversity is a WARNING, never a block.** Coercing breadth via a hard
  finder-count floor is a count-gate in disguise; below the floor the guard warns
  but never flips `passed`.
- **The gate raises the FLOOR, it does not certify the CEILING** (direction ≠
  magnitude). It rejects no-repro / non-failing / unsigned / catch-all /
  wrong-signature / `expect: pass` / ambiguous-id / crash-the-gate blockers; it
  cannot prove a repro is *causally* the claimed bug (an `echo` of the signature
  passes) nor that real blockers were *missed*. The PASS report states this.

**The unifying law (BP-00 X3):** *a gate certifies only the mechanically-
witnessable; depth lives in the work-turn.* The `/goal` evaluator that accepts
"red-team ran" and the count-floor that manufactures findings are the *same*
failure — a gate reaching past what it can mechanically witness, where the
"certification" is hallucinated-from-prose (worse than not gating).

This is the gate-design dual of [[convergence-review-protocol]] (read BLOCKER-yield,
not finding count) and [[untrusted-oracle-protocol]] / [[complacent-oracle]]
(re-derive through an external oracle, never trust the rendered claim); it consumes
the wire-format in [[fan-out-finding-schema]]. Its coverage-side twin — a
completeness gate that *hand-lists* its population instead of discovering it, so it
witnesses only the listed members — is [[completeness-gate-must-discover-its-population]].
Its product-thesis sibling — the "make-it-prove-it moat" — lives in the private
working-memory store, not here.

*Source: BP-03 §3/§9 + BP-00 X3 (session 40fff742, 2026-06).*
