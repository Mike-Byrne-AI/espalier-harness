# TP-203b — Effect measurement: the false-fire counter (PACK)

## Status

- **Kind: PACK** (executable; the W2 child of the TP-203 roadmap).
- **Version target:** post-0.8.0b1 (NOT a cut blocker).
- **Type:** feature/observability — turn "is this speed-bump crying wolf?" from a
  guess into a number, paying down the recall engine's `imagined`/`probable`
  effect-claims (user §3: a sound mechanism is not a measured effect).
- **Provenance:** machinery + free-lunch grounding wf (`wf_f793cc78-363`,
  2026-06-25). Design salvaged in `memory/speedbump-checkpoint-atlas.md` ("Effect
  measurement"); blueprint.md §11. **The grounding both refuted a seam the roadmap
  relied on AND found a cheaper one** (see Motivation).

## Motivation

The roadmap proposed measuring effect by logging every reinject fire **and** every
speed-bump deny, then reusing the 157-F `last_tool` tracker to tell whether the
operator changed course. The grounding **refuted the 157-F join**: the speed-bump
fires at PreToolUse and 157-F at PostToolUse (no shared turn-order), `last_tool`
records tool-NAME not command-identity, and both stores are glob-WIPED at every
SessionStart — so a cross-session rate is unobtainable that way.

But the grounding found a **cheaper, sharper** path for the metric the operator
actually wants (false-fire = friction): **deny-once-then-allow is already the retry
detector.** When the operator re-issues the *identical* action after a deny,
`_speedbump.check()` finds `flag.exists()` and falls through to allow
(`_speedbump.py:534`). That short-circuit *is* the false-fire signal — visible at
the speed-bump site itself, no sequel-observer, no 157-F join. Log a `retried` event
there (paired with the original `deny`) and:

```
false-fire-rate(checkpoint) = retried / denied      # operator re-issued the same thing → bump caught nothing
catch(checkpoint)           = denied − retried       # deny with no matching retry in-session (inferred)
```

Two more free lunches make this cheap: the **producer already exists**
(`_integrity.append_audit` — flock-safe, never-raises, `$HOME`-persisted so it
survives the SessionStart wipe, auto-pruned, already called *beside* the speed-bump
deny in `write_guard`), and the **analyzer reader already exists as a template**
(`espalier/scan_telemetry.py::read_history`).

Read through the governing frame: **toolbelt, not security boundary.** This is
pure observability — fail-open, never blocks a tool or a deny.

---

## Scope (in)

| Phase | Sub-task | Free lunch | New work |
|---|---|---|---|
| **B1** | Producer: append `speedbump_deny` + `speedbump_retried` events inside `_speedbump.check()` via `append_audit`, keyed on a generalised `_discard_key` command hash | `append_audit` is shipped, fail-open, `$HOME`-durable, auto-pruned; the retry short-circuit already exists | thread `root` into `check()`; generalise the command hash; the event schema |
| **B2** | Analyzer: `espalier recall-stats` reads the audit log, reports false-fire-rate + catch per checkpoint over a pre-registered window | clone `scan_telemetry.read_history`; 5-line read-only subparser trips no count test | the cross-event pairing (deny↔retried) + the endpoint constant |

## Scope (out)

- **Reinject-fire utilisation logging.** Deferred: 6 `_reinject.check` call sites,
  and it is a *different* metric (which advisory is wallpaper), not false-fire-rate.
  An advisory has no deny and no retry, so the catch/false-fire dichotomy doesn't
  apply. Clean follow-up, reuses the same `append_audit` producer.
- **The full catch-rate "study."** Deferred (user §3/§8): n=1 operator, behaviour-
  change hard to attribute. Ship the *counter*; the *study* is over-built. catch is
  the inferred half (deny with no retry); the deny↔retried pair is the strong half.
- **Reusing the 157-F `last_tool` join / a PostToolUse sequel-observer.** Dropped —
  refuted by grounding (different events, no turn-order, tool-name granularity,
  per-session wipe). The retry short-circuit replaces it.
- **Putting the durable log in `.espalier-state/`.** Forbidden: glob-wiped every
  SessionStart. The log is `$HOME` (`append_audit`) or a wipe-exempt store.

---

## Affected symbols

> Prospective until built. Listed for scope-check.

### Added paths
- `espalier/recall_telemetry.py` — `recall-stats` analyzer (reads audit log, pairs deny↔retried)
- `tests/test_recall_telemetry.py` — B1 producer + B2 analyzer earn-the-red
- `espalier recall-stats` subcommand in `espalier/cli.py`

### Changed semantics
- `tools/cc/hooks/_speedbump.py::check()` — two `append_audit(...)` calls (at the deny write and the `flag.exists()` retry short-circuit); `root` threaded in if not present. **Governed surface: 3 edits** — source + the byte-identical `espalier/_vendor/cc/hooks/_speedbump.py` mirror + a `.espalier/integrity.json` refresh (`_speedbump.py` is a `MANIFEST_FILES` entry).
- `tools/cc/hooks/_speedbump.py` command-hash helper — generalise `_discard_key` (`:135`) from CP-DISCARD-only to an all-bumps episode key.

## Implementation

### B1 — Producer (3 governed surfaces; put the append INSIDE `check`)

- In `_speedbump.check()`:
  - at the **deny** path (after `flag.write_text(bump.id)`, `:543`):
    `append_audit(root, {"event_type": "speedbump_deny", "id": bump.id,
    "command_hash": <hash>})`.
  - at the **retry short-circuit** (the `if flag.exists(): ... allow` branch,
    `:534`): `append_audit(root, {"event_type": "speedbump_retried", "id": bump.id,
    "command_hash": <hash>})`.
- Keep the append **inside `check`** (not at the `write_guard.py:629` call site) so
  the call site is unchanged → **3 governed surfaces, not 6** (avoids editing
  `write_guard.py` source + mirror + manifest).
- `_speedbump.py` is zero-espalier-import; `append_audit` lives in
  `tools/cc/hooks/_integrity.py` (also zero-espalier) — same-layer import, allowed
  (it already imports `STATE_DIR` from `_hook_utils`). Thread `root` into `check()`
  if it isn't already in scope.
- **Generalise the episode key:** `_discard_key` (`:135`, currently CP-DISCARD-only)
  becomes the command-hash for all bumps, so a deny and its retry share a key.
- **Fail-open:** `append_audit` already never raises; a logging error must never
  affect the deny/allow decision.

**B1 pass-criteria seeds:**
- First match for (checkpoint, command) → one `speedbump_deny` record + a deny
  returned. Identical re-issue → `flag.exists()` → one `speedbump_retried` record +
  allow (earn-the-red: assert both records land with the same `command_hash`).
- A different command after a deny → no `retried` for that key (it is a catch, not a
  false-fire).
- A simulated `append_audit` failure does NOT change the deny/allow decision
  (fail-open earn-the-red).
- Records go to the `$HOME` audit path family (redirected by `ESPALIER_AUDIT_DIR` in
  tests), NOT to `.espalier-state/` (assert survival across a simulated SessionStart
  wipe).
- `_speedbump.py` source + vendor mirror stay byte-identical (`test_vendor_cc_parity`);
  `integrity verify` passes after refresh.

### B2 — Analyzer (`espalier recall-stats`, espalier-layer, 0 vendor/integrity cost)

- `espalier/recall_telemetry.py`: clone `scan_telemetry.read_history` (malformed-
  line-tolerant per-line `json.loads` + `isinstance(dict)` filter). Read the audit
  log, filter `event_type in {speedbump_deny, speedbump_retried}`, pair by
  `command_hash`/`id` per checkpoint, compute `false-fire-rate = retried/denied` and
  `catch = denied − retried`.
- **Pre-register the endpoint** as a config constant *before* collecting:
  `RECALL_FALSE_FIRE_CEILING = X over N fires` — `recall-stats` flags any checkpoint
  exceeding it. Not derived from the data (user §8).
- **Architecture fork (decide before building):** `recall-stats` reading the hook's
  `$HOME` audit log crosses the documented "espalier never touches the hook-side
  audit log" boundary (`scan_telemetry.py` docstring). Either (a) `recall-stats`
  re-derives `audit_path(repo_root)` independently (one small duplicated path
  function, no import), or (b) the B1 producer also drops an espalier-readable copy
  under `reports/`. **Recommend (a)** — smaller, keeps one producer.
- 5-line read-only subparser; trips no command-count test (`EXPECTED_COMMAND_COUNT`
  is slash commands), correctly nudge-exempt-by-omission (read-only, doesn't
  wire/validate the harness — TP-220 `_maybe_nudge_source_checkout`).

**B2 pass-criteria seeds:**
- A log with 5 denies / 2 retries for CP-X → `recall-stats` reports
  false-fire-rate 0.4, catch 3 for CP-X (earn-the-red on the arithmetic).
- A checkpoint exceeding `RECALL_FALSE_FIRE_CEILING` is flagged; one under is not.
- A malformed JSONL line is skipped, not fatal (reader robustness).
- The endpoint is a constant, not computed from the window.

## Pass criteria

1. B1: deny and retry both append fail-open `$HOME`-durable records keyed by a
   shared command hash; 3 governed surfaces stay consistent (parity + integrity).
2. B2: `espalier recall-stats` computes false-fire-rate + catch per checkpoint
   against the pre-registered ceiling.
3. Full suite green; `espalier audit .` 0/0; `integrity verify` clean after refresh.

## Files touched

**New:** `espalier/recall_telemetry.py`, `tests/test_recall_telemetry.py`, `task-packs/TP-203b-...md` (this file).
**Changed:** `tools/cc/hooks/_speedbump.py` (+ vendor mirror), `.espalier/integrity.json`, `espalier/cli.py` (B2 subcommand), CHANGELOG.

## Sub-task ordering

1. **B1 first** (the producer — start collecting; the rate needs data over time).
2. **B2 second** (the analyzer — meaningful only once denies/retries have accrued).

## Estimated effort

- B1: ~1 day (2 appends + command-hash generalisation + root threading + 3-surface
  sync + integrity refresh + tests).
- B2: ~½–1 day (clone the reader + pairing + endpoint constant + subparser + tests).

## Landing

- State: DRAFT
- Commits:               # not executed
- Suite:                 # n/a until executed
- Earn-the-red:          # per phase (B1, B2)
- Date: 2026-06-25
