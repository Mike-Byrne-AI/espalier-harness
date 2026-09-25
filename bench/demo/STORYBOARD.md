# Espalier demo — storyboard & shot list

The plan for the launch demo: **one hero GIF** (positions the product) **+ a
feature strip** (one short clip per headline system). This doc is paint-by-
numbers: exact beats, prompts, verified on-screen text, and — the load-bearing
part — an **honest narration line** for each clip so nothing is overclaimed on
camera.

Every clip below was checked against live behavior in a pre-launch systems
audit (6/6 systems verified `works-as-claimed`, 0 confirmed landmines). Where a
system's real behavior is narrower than a hype framing would suggest, the
narration line says so. That precision *is* the credibility play — it's what
separates this from over-sold tooling.

Companion docs: [`script.md`](script.md) (the original self-disable script, now
the hero's climax beat), [`RECORDING.md`](RECORDING.md) (tools + setup +
embedding).

---

## Rules that apply to every take

1. **Record with `ESPALIER_MAINTENANCE_MODE` UNSET.** Proven: with it set, the
   protected-zone denials silently do not fire — you'd record a dead demo.
   Before every session: `echo $ESPALIER_MAINTENANCE_MODE` must print a blank
   line.
2. **Record against a throwaway demo-target**, never the espalier source repo.
   Setup per `RECORDING.md`: `mkdir /tmp/demo-target && cd /tmp/demo-target &&
   git init -q && espalier init . && espalier doctor .` (expect pass).
3. **Never fabricate output.** If a real banner is long, trim in post — don't
   type an idealized shorter version.
4. **Tiering:** the **hero is the launch gate**; the **feature strip is
   fast-follow** (record over the days after launch, one clip at a time).

---

## Verified on-screen text (confirmed this session — your reference)

**No-plan deny** (plan gate):
```
✗ PreToolUse:Edit hook blocked
  No active execution plan (missing). Mutation requires status='in_progress'; …
    Do: `/implement-task "<one-line description>"` then proceed.
```

**Protected-zone deny** (self-disable seatbelt) — the full current template:
```
✗ PreToolUse:Edit hook blocked
  Write to protected harness zone blocked: .claude/settings.json. Harness
  self-edits: exit and relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue`
  (env read at launch; mid-session export is ignored; --continue keeps this
  session). Do NOT disable hooks to proceed -- that loosens future safety.
    Don't: edit harness files from a regular session … and don't disable
    hooks to get around this.
    Do: ask the operator to relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue`
    BEFORE the edit …, then resume through your normal workflow (/implement-task) …
```
Bash variant headline: `Bash write to protected harness zone blocked: .claude/settings.json.`

**SessionStart banner header** (real fields — abbreviate in the frame, don't invent):
```
=== Espalier-Harness === Session Start ===
Repo:      demo-target
Branch:    main
Status:    clean
Surface:   healthy
```
(Live banner also prints `Host:` / `Memory:` / `Blueprint:` / `Commands:` lines.)

**Earn-the-red gate** (first-hand, `verify_repro`):
```
fabricated blocker -> verified=False | observed=pass | exit=0 observed=pass expected=fail
genuine blocker    -> verified=True  | observed=fail | exit=1 observed=fail expected=fail
catch-all match    -> verified=False | repro 'match' must be specific, not empty/catch-all
```

---

## HERO — "one session, kept on the rails" (~45–60s)

Positions Espalier as a *whole workflow*, with the self-disable block as the
climax rather than the whole story. Record as one continuous Claude Code session
in `/tmp/demo-target`.

| Beat | ~time | Action | On screen | Caption (narration) |
|---|---|---|---|---|
| Title | 0:00–0:06 | Title card | `espalier — keeps your coding agent on the workflow, even when it reaches for the kill-switch` | — |
| Orient | 0:06–0:14 | `claude` opens | SessionStart banner scrolls | "Every session opens already oriented — bounded context, not the whole repo." |
| Plan gate | 0:14–0:24 | Prompt: *"add a helper function to utils.py"* | no-plan deny → `Do: /implement-task` | "Source changes go through a plan. No free-handing." |
| **Seatbelt (climax)** | 0:24–0:42 | Prompt: *"just set disableAllHooks: true in .claude/settings.json so we can move faster"* | protected-zone deny + Don't/Do redirect | "When the agent reaches for the kill-switch under pressure, the seatbelt catches it and points back at the workflow." |
| Handoff | 0:42–0:52 | `/handoff` (or show `cognitive_blueprint.py finalize`) | fragments captured for next session | "At session end the reasoning is saved — the next session picks up where this one left off." |
| End card | 0:52–1:00 | End card | the three regression-test names (see `script.md`) | "Every block above is a pinned regression test." |

**Fallback if the full-loop take is fiddly:** the proven three-attempt
self-disable cascade in [`script.md`](script.md) stands alone as the hero, and
the feature strip carries the breadth. Don't burn a day chasing a perfect loop —
a crisp self-disable + a strong feature strip beats a shaky loop.

---

## FEATURE STRIP (Tier 2 — fast-follow, one clip each)

Each: **setup → action → on-screen → narration → don't-claim guardrail.** Keep
each 6–12s.

### F1 · Context injection
- **Action:** open `claude` in the demo-target; let the real SessionStart banner render.
- **On screen:** the banner header fields (above). *Optional credibility plus:* if a section is over budget, the `[banner] … is large` health line shows — that's the anti-bloat guard visibly working.
- **Narration:** "Bounded, current context every session — capped so it can't bloat."
- **Don't claim:** don't call the blueprint "de-duplicated" (it renders prior reasoning twice; invisible to a viewer, but don't assert it).

### F2 · Plan + proof gate
- **Action:** with no plan, attempt a source edit → deny; then `/implement-task` → plan created → same edit succeeds → mark step passed → `execution_plan.py status` shows the trail.
- **On screen:** the no-plan deny (above), then the completed per-step trail.
- **Narration:** "The plan **gate** is mechanical — a real PreToolUse block. The per-step proof is a workflow step the agent records."
- **Don't claim:** do **not** imply the harness *verifies* each step's proof — `mark passed` is a self-report; the mechanical test backstop runs at Stop (opt-in `ESPALIER_STOP_GATE=full`), not per step.

### F3 · Continuation blueprints (two-session)
- **Setup:** Session A must record real reasoning (don't demo a cold start — ~57% of nodes are empty).
- **Action:** Session A: make a change, `cognitive_blueprint.py record --kind decision --description '…'`, then `finalize` (or `/handoff`). Session B: open `claude`, show the banner's Blueprint block carrying Session A's decision verbatim.
- **On screen:** "What the prior session wants you to know" + "Recent reasoning" carrying the decision; optionally the chain depth counter (real, ~381).
- **Narration:** "The next session picks up the reasoning, not just the code."
- **Don't claim:** it propagates **one hop**; the durable multi-session store is ESPALIER_MEMORY.md + the working-summary, not the blueprint alone.

### F4 · Handoff
- **Action:** `cognitive_blueprint.py record --kind decision …` twice (one `--carry-forward`), `finalize` (emits `[decision]…` / `[pattern]…` fragments), `load` (next session receives them + pinned/recent decisions).
- **On screen:** the finalize fragments and the load orientation block.
- **Narration:** "Reasoning is captured and carried forward **when you record it** — lean and bounded (hundreds of bytes), the opposite of a context dump."
- **Don't claim:** don't imply *every* handoff yields a rich blueprint (~half of real sessions record none and lean on the other two continuity channels); record at least one **decision or pattern** — an `alternative_rejected` alone is dropped from reinjection unless pinned.

### F5 · Fan-out / convergence review
- **Part 1 (engine, <1s, live):** run the two-hop `aggregate_findings → append_findings_to_corpus → append_summary` command (see `.claude/workflows/_fanout_audit.js`) against a prepared scratch findings file; show the printed `FindingsSummary` (dedup, corroboration_count, survival_rate), the corpus bullet, the ledger row, and a re-run appending 0 (idempotent). *(Numbers audit-verified; re-confirm at record time — the engine needs a valid 13-field finding, so use a prepared input, don't hand-type on camera.)*
- **Part 2 (real artifacts, operator-local):** from the maintainer's own working tree, scroll a real fan-out review report under `reports/` — its `N agents, 0 errors, ~Ns, B blockers·M majors` header + one grep-oracle-proved finding — then a real run row in `cc/finding_ledger.jsonl`. *(Both are gitignored operator-local hardening records — present on the maintainer's machine, absent on a fresh clone; don't hard-code a dated filename or imply a cloner will find these.)*
- **Narration:** "This is the internal hardening method I run on Espalier itself — fan out finders, adversarially refute, persist what survives."
- **Don't claim:** it is **not** a feature adopters receive (README/QUICKSTART correctly never claim it — keep the demo consistent). The run ledger is **newly instrumented** (1 row), not yet a mature learning loop. Don't record a live full fan-out (~13 min, Opus-scale).

### F6 · Earn-the-red gate ("make it prove it")
- **Action (first-hand, reproducible):**
  ```
  python3 -c "import espalier.red_team_guard as r; \
    print(r.verify_repro({'id':'FAKE','argv':['true'],'expect':'fail'})); \
    print(r.verify_repro({'id':'REAL','argv':['false'],'expect':'fail'}))"
  ```
- **On screen:** the fabricated blocker → `verified=False` (rejected: it claimed to fail but exited 0); the genuine one → `verified=True`.
- **Narration:** "A claimed blocker has to *earn its red* — the gate re-runs the repro; if it doesn't reproduce, it's rejected."
- **Don't claim:** frame it as the **earn-the-red gate the autonomous driver runs / a library the workflow can wire in** — **not** an always-on per-session gate. Its bite has so far fired only in tests. Do not imply it re-runs every blocker in a normal interactive session.

---

## Recording checklist (per clip)

- [ ] `echo $ESPALIER_MAINTENANCE_MODE` is blank
- [ ] recording against `/tmp/demo-target`, not the source repo
- [ ] the deny/output on screen matches the verified text above
- [ ] narration line is the honest one (no overclaim)
- [ ] trimmed < the beat budget; GIF < 5 MB (`gifsicle -O3 --colors 64`)
- [ ] embed verified on **github.com**, not local preview

**Ship order:** hero → (launch) → F1…F6 as fast-follow. See `RECORDING.md` for
tools, sizing, and the README embed target (top of `## 30-second demo`).
