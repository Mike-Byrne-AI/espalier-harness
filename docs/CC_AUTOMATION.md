# Claude Code Automation Primitives (`/goal`, `/loop`, `/schedule`, ScheduleWakeup, auto-mode)

**Audience:** contributors driving long or unattended sessions.
**Pinned to Claude Code 2.1.214 (2026-07). Re-audited 2026-07-20** against
`code.claude.com/docs` (every claim below re-verified; verdicts folded in) and
cross-checked against the live in-session tool contracts (`ScheduleWakeup`,
`TaskStop`, `Cron*`). A few facts are **empirical** or **tool-contract-sourced**,
not re-derived against the running binary except where tagged. CC moves fast —
**re-verify any number before encoding it as a contract**, and re-pin the version
when you cite one.

These are first-party CC primitives the harness *composes with*; none is a
harness feature. The autonomous loop-over-`claude -p` driver that rides on them
is documented separately in [AUTONOMOUS_EXECUTION.md](AUTONOMOUS_EXECUTION.md).

---

## 1. `/goal` — a session-scoped Stop hook judged by a *separate* small model

The single most load-bearing mechanic.

- **What it is.** `/goal <condition>` installs a **session-scoped, prompt-based
  Stop hook**. After every turn, the condition + the conversation-so-far go to a
  **separate small fast model (Haiku by default)** for a yes/no decision. "No" →
  Claude starts another turn with the evaluator's reason as guidance; "yes" → the
  goal **auto-clears** and records an "achieved" entry. [doc-sourced; empirically
  confirmed: running `/goal` prints that a session-scoped Stop hook is active and
  "auto-clears once the condition is met"]
- **Decision-maker ≠ worker.** Completion is judged by a fresh model with no
  stake, so the worker can't rubber-stamp its own done-ness. [doc-sourced]
- **The evaluator runs NO tools.** It can only judge **what Claude has already
  surfaced in the conversation** — it does not run commands or read files. **This
  is the constraint behind the keep-the-condition-mechanical principle (§2).**
  [doc-sourced]
- **Front-gate vs back-gate:** plan mode gates the *front* (whether you start);
  `/goal` gates the *back* (won't let you stop until the condition holds).
- **Lifecycle:** setting a goal immediately starts a turn; `/goal` (no arg) shows
  status; `/goal clear` (aliases `stop`/`off`/`reset`/`none`/`cancel`) clears
  early — **don't tell the user to clear after success; auto-clear already
  fired.** Condition ≤ 4,000 chars. Session-scoped (restores on
  `--resume`/`--continue`, but turn/timer/token baselines reset). Survives
  compaction within a session [probable — inferred from resume-restore].
- **`-p` runs the whole goal loop to completion in one invocation.** [doc-sourced
  — load-bearing for the driver.]
- **Block cap:** a Stop hook is overridden after **8 consecutive blocks without
  progress**; raise via `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`. A `/goal` can
  therefore self-escape after 8 stuck turns even with no `or stop after N` clause
  — a runaway *floor*, not a designed bound. [**empirical — NOT in the 2.1.214
  public docs**; the 2026-07-20 re-audit could not re-confirm the number or the
  env var against `code.claude.com/docs`. Treat as unverified until re-checked
  against the running binary.]
- **Requirements:** workspace trust + hooks enabled; unavailable under
  `disableAllHooks` / `allowManagedHooksOnly`. Requires CC **≥ 2.1.139**.

## 2. Keep the condition MECHANICAL — deep judgment belongs in the work-turn

The keystone principle, forced by the tool-less evaluator (§1):

- **Mechanical scaffold → goal-able.** Every step that produces *visible proof a
  tool-less judge can read* is reliably automatable: scope-check printed, edits
  applied, earn-the-red shown (mutate→RED→revert is in the transcript), full
  pytest green (output), `espalier audit` clean, one atomic commit (`git log`).
  Haiku is reliable at "is this artifact present/green?" — not "is this work
  good?".
- **Judgment depth → NOT goal-verifiable.** No evaluator can judge whether a
  red-team was *rigorous*; it sees only "a workflow ran and returned 0 blockers."
  Accepting "red-team ran" as proof of done is the **automation-layer form of
  convergence theater** (FAILURE_MODES §1.1).
- **Therefore:** require the hard artifacts (earn-the-red shown, suite green,
  audit clean, atomic commit), never "red-team ran"; keep depth-judgment +
  adversarial refuters in the work-turn. A *smarter* evaluator is the wrong fix —
  it still can't run tools, so its "judgment" would be hallucinated-from-prose.
- **The evaluator MODEL is not independently configurable.** There is no
  `goalEvaluatorModel`/`smallModel` settings key; the only lever is the session's
  small-model slot (defaults to Haiku), governed by the primary `model` setting.
  [re-confirmed absent 2026-07-20 — still no `goalEvaluatorModel`/`smallModel`
  key in the docs; remains inferred-from-absence, not a positive statement.]

## 3. `/loop` — interval vs dynamic (two different runtime mechanisms)

- **INTERVAL** (`/loop 5m <prompt>`) = a recurring **cron** job (`CronCreate`,
  5-field expression; units rounded to a cron step). Fixed cadence.
- **DYNAMIC** (`/loop`, no interval) = **self-paced** via `ScheduleWakeup`. After
  each iteration Claude picks a `delaySeconds` **clamped to [60, 3600]** and
  reschedules; the prompt is the sentinel **`<<autonomous-loop-dynamic>>`** (vs
  `<<autonomous-loop>>` for cron) or the original prompt. [The clamp bounds and
  both sentinels are confirmed **verbatim against the live `ScheduleWakeup` tool
  contract** this session; the public `scheduled-tasks` docs only say "between one
  minute and one hour" and do not name the sentinels.]
- **A `/loop` prompt can be a slash command or skill** (since **2.1.196**), e.g.
  `/loop 20m /review-pr 1234` — the interval form reruns that command each tick.
- **Stopping (asymmetric — a footgun):** dynamic stops on **Esc** *or* by simply
  omitting the `ScheduleWakeup` call; a cron loop **ignores Esc** — use
  `CronDelete` (or "cancel the X job"). Both: **7-day auto-expiry**; global kill
  `CLAUDE_CODE_DISABLE_CRON=1`.
- **Durability:** session-scoped by default; `CronCreateInput.durable=true`
  persists to `.claude/scheduled_tasks.json` [**implementation detail — NOT a
  documented user contract** as of 2.1.214; the flag name and file path are
  observed, not published]. Times are **local timezone**. Scheduler fires
  **only between turns, never mid-response**; no catch-up; max **50
  tasks/session**.
- **`.claude/loop.md`** customizes the bare-`/loop` prompt (project > user; max
  25 KB; live-editable — next iteration picks up edits).
- **`Monitor`** is a dynamic-loop alternative to polling: a persistent background
  script streaming stdout; stop via `TaskStop`.
- **Cloud-backend caveat:** on Bedrock/Vertex/Foundry, dynamic `/loop` runs a
  **fixed 10-minute schedule** and **`loop.md` is ignored**. [doc-sourced;
  untested on first-party API — flag for adopters on those backends.]
- **`/schedule` (cloud Routines) is a *separate* scheduler** — new in this
  window, distinct from `/loop`'s local scheduled tasks. It creates
  cron-scheduled **cloud agents** ("routines") that run **server-side**, with
  API and GitHub triggers, managed via `/schedule` (create/update/list/run).
  Since **2.1.214** a routine's prompt is framed as **pre-authorized, not
  untrusted**. Because it runs off-box it does **NOT** ride the local
  `claude -p` disk-baton driver in
  [AUTONOMOUS_EXECUTION.md](AUTONOMOUS_EXECUTION.md) — treat it as a different
  execution surface. [doc-sourced 2026-07-20.]

## 4. Composition — `/goal` × `/loop` × auto-mode are orthogonal

- `/goal` (within-turn: don't stop until proven done) and `/loop` (across-turn:
  wake again later) are complementary. One active `/goal` + multiple `/loop`
  tasks can coexist. Use `/goal` for a verifiable end-state (no waiting between
  iterations); `/loop` for *waiting* on async/idle work (polling CI).
- **Auto-mode** is the third layer: `permissions.defaultMode="auto"` removes
  per-tool prompts; `/goal` removes per-turn prompts. Both → unattended.
  **Since 2.1.207 auto mode is available by default on all providers** (the
  former `CLAUDE_CODE_ENABLE_AUTO_MODE` gate was removed) — `auto` is now a
  ready permission mode, not an opt-in-flagged one. Budget cap
  `--max-budget-usd` is **`-p`-only**.
- **`/goal` cannot override mechanical gates.** It only *restarts turns* — it does
  not approve tool calls or bypass `write_guard`/`config_guard`/permissions. **The
  harness's anti-self-disable floor holds unchanged under a goal** — this is the
  safety story for unattended runs.
- **`/clear` clears an active `/goal`** [empirical]. So you can't reset the
  transcript mid-session while keeping one overarching goal — which is *why* the
  token-optimal shape is one `claude -p "/goal …"` per unit with the on-disk
  blueprint as the baton (the driver in [AUTONOMOUS_EXECUTION.md](AUTONOMOUS_EXECUTION.md)).

## 5. Footguns (full entries cross-referenced)

- **Self-perpetuating heartbeat loop** — a fallback `ScheduleWakeup` sentinel
  turns a session into a timer-driven loop with no `/loop` toggle (FAILURE_MODES
  §7.10; SHARP_EDGES).
- **Goal-gate convergence theater** — a tool-less evaluator can't certify
  red-team quality (FAILURE_MODES §1.1; §2 above).
- **Cron `/loop` you can't Esc away** — use `CronDelete` (SHARP_EDGES).
- A copy-ready mechanical `/goal` condition template lives in
  [TASK_RECIPES.md](TASK_RECIPES.md) ("A mechanical `/goal` for pack execution").

## Open / re-verify before contract

**2026-07-20 re-audit (vs CC 2.1.214).** Most claims re-confirmed against
`code.claude.com/docs`; nothing was found *changed to a wrong value*. Still open:

- **Block cap 8 / `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (§1)** — no longer findable
  in the public docs; downgraded to **empirical/unverified** until re-checked
  against the running binary.
- **Evaluator-model non-configurability (§2)** and **goal-survives-compaction
  (§1)** remain **inferred-from-absence** — re-confirmed absent 2026-07-20, still
  not a positive statement.
- **`CronCreateInput.durable` + `.claude/scheduled_tasks.json` (§3)** are
  observed implementation details, not a documented user contract.
- **The `/goal` × `stop_gate.py` interaction** — the one composition the harness
  directly owns — is still **unverified**; confirm a `/goal` and `stop_gate`
  don't deadlock (esp. under `ESPALIER_STOP_GATE=full`) before asserting safety.

Re-verified numeric facts (clamp [60,3600], 25 KB, 50 tasks, 7-day expiry,
≥2.1.139, ≤4,000-char condition) hold at 2.1.214 — re-confirm on use. Folded in
this pass: skills-in-`/loop` (2.1.196), auto-mode default-on (2.1.207),
`/schedule` cloud Routines, routine prompt-framing change (2.1.214).
