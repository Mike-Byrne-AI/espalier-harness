# Forensically audit the workflow execution, not just the end-state

**Status:** active

**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md` folder router and sibling cross-links (the ESPALIER_MEMORY.md hot index is at its 120-line cap; not indexed there).

When an autonomous (`claude -p`) sub-session claims it earn-the-red'd a fix, the
**end-state does not prove the process was honest**. A green suite and a commit in
`git log` are consistent with both real work and "process theater" — the agent
writing prose describing a RED it never actually produced.

The discipline (used this session as a "4-lens forensic transcript audit", e.g.
TP-222): open the **nested sub-session's own transcript** and audit its tool calls
— confirm a real `pytest` `tool_result` actually showed `FAILED` on the mutated
code (not a prose assertion of it), and that the execution-plan tracker stepped
`0/N → N/N`. The oracle is the nested transcript's `tool_result` records — a
mechanical artifact the agent cannot retroactively forge — not the agent's summary.

The load-bearing principle: **process-honesty on a pack you CAN verify is the
proxy for trustworthiness on packs you can't.** You cannot forensically audit
every future autonomous run; you audit a verifiable one to calibrate how much to
trust the channel. This is [[untrusted-oracle-protocol]] pushed one level deeper —
not "is the *output* fabricated?" but "is the *work that produced it* fabricated?"

Pairs with the mechanical re-verification gate
([[gating-on-count-manufactures-findings]]: `red_team_guard.py` re-runs each
blocker's repro in an external oracle): the forensic audit is the *manual*
calibration; the guard is the *mechanized* re-execution. Both refuse the agent's
self-report. A `tools/cc/forensic_run_audit.py` that mechanizes this (extract the
`tool_result` records, assert the claimed RED actually appeared, assert the
plan-tracker advanced) is a proposed follow-up, not yet built.

*Source: BP-06 D1 (session 40fff742, 2026-06).*
