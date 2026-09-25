Reasoning review — fixed checklist (TP-63 v1)

For each item below, evaluate the pack's generation process and
report one of: PASS, GAP, BIAS, UNCHECKED.

**1. Agent composition adequacy.**
What review angles did the generation pass? What angles are
conspicuously missing for this pack's domain?

- Failure-mode-sensitive packs (hooks, gates, governance changes)
  MUST have had failure-mode-reviewer.
- Cross-module packs MUST have had architecture-analyst.
- OSS-surface packs MUST have had consumer-UX review (general-
  purpose simulating downstream).
- Net-new-subsystem packs MUST have had at least 3 angles.

Report GAP if any required angle is missing.

**2. Premise inheritance.**
List claims the pack imports from prior context (ESPALIER_MEMORY.md,
prior packs, the user's framing) and used without independent
verification.

Each unchecked premise = UNCHECKED finding.

**3. Synthesis validity.**
List the synthesis leaps the generation made. For each: is it
evidence-backed (concrete agent finding citations) or
pattern-matched (the shape feels familiar from training)?

Pattern-matched synthesis = BIAS finding.

**4. Scope-narrowing choices.**
What was implicitly excluded from consideration? Per scope-out
entry: is the reason given a substantive justification ("would
require X cost not warranted by Y benefit") or a default
("seemed out of scope")?

Default-scoped-out = GAP finding.

**5. Counterfactual checks.**
For the pack's two or three central design choices: what would
the conclusion be if a key premise were inverted? Are there
premises whose negation would invert the conclusion?

If no counterfactual was considered for a load-bearing choice =
UNCHECKED finding.

**6. Diversity-of-context check.**
Did the generation use the same agent type multiple times, or
multiple agent types? Single-agent reasoning chains inherit
that agent's blind spots.

Single-agent dominance = BIAS finding.

**7. Alternative framings.**
Were 2+ design alternatives considered for major decisions, or
was one path treated as obvious?

Single-path reasoning without alternatives weighed = GAP finding.

Output format per item: SEVERITY • CATEGORY • FINDING •
EVIDENCE • SUGGESTED_ADDRESS.

Severity must be one of: PASS, GAP, BIAS, UNCHECKED.
