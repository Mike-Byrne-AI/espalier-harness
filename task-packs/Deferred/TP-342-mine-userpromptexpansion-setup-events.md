# TP-342 — Mine the UserPromptExpansion and Setup hook events

## Status
- Version target: current (self-host; a platform-surface expansion, not a release gate)
- Change type: FEATURE — wire two live stdout/`additionalContext`-injecting Claude Code
  hook events the injection atlases flagged as "never mined": `UserPromptExpansion`
  (slash-command-expansion-time discipline) and `Setup` (one-time first-run calibration)
- **Kind: PACK** (two independent sub-tasks over one shared multi-surface substrate;
  either event could land alone — see Scope-out on why the pack is heavier than it looks)
- Derived from: the orphan-intent net `wf_252b9580` + the source store
  `memory/injection-opportunity-atlas.md`
  (rescued-rule #2: "`UserPromptExpansion` and `Setup` were never mined") +
  `memory/generative-injection-atlas.md`
  (completeness gap #5: "Unmined live `Setup` event"; both atlases are
  maintainer-only and not in the source archive). Both are experimental research
  notes with **no tracker reader** — the intent never reached
  `task-packs/FORWARD_LEDGER.md` (its INV-6 planned-events lane lists only PreCompact /
  InstructionsLoaded / WorktreeCreate, not these two).

## Motivation

Two of Claude Code's context-injecting hook events are live and unmined:

- **`UserPromptExpansion`** — fires when a slash command expands. Per the pinned
  protocol (`docs/external/cc-hook-protocol.md`), it is one of only three events on
  which **plain stdout is added as context the model can act on** (with
  `UserPromptSubmit` and `SessionStart`), and it also delivers
  `hookSpecificOutput.additionalContext` **alongside the submitted prompt**. It is the
  natural home for slash-command disciplines — e.g. surfacing the `/implement-pack`
  git-oracle byte-verify pre-read at expansion time.
- **`Setup`** — fires at conversation start and delivers `additionalContext` "at the
  start of the conversation" (same placement bucket as SessionStart / SubagentStart per
  the pinned excerpt). The atlas intent: carry one-time adopter first-run calibration
  here instead of paying it on every SessionStart.

Neither is wired today (`espalier/harness_config.py::CANONICAL_HOOK_WIRING` has 12
scripts across 10 events; `git grep` confirms zero `UserPromptExpansion`/`Setup`
references in the wiring, settings builder, or scope docs). The gap is **live**.

**Resolving the "omitted vs. planned" contradiction (required reconciliation).**
`docs/HOOK_ASSUMPTIONS.md` → *Scope* lists `Setup` among events "Espalier's omission is
deliberate" and tells adopters to "add them to their fork." But **`PreCompact` sits in
that *same* deliberately-omitted list** and is *simultaneously* an INV-6 **planned** item
in FORWARD_LEDGER. So "omitted for now" and "planned to wire" already coexist in the repo
— the omitted-list is a *snapshot of what is unwired today*, not a permanent verdict.
This pack performs exactly that transition for `Setup` + `UserPromptExpansion`:
**omitted → wired**, and updates `HOOK_ASSUMPTIONS.md`'s scope prose + event count
(10 → 12) so the doc stops describing them as out of scope. On landing, INV-6's
planned-events lane gains these two (a landing action, not this draft's edit — the main
session owns ledger rows).

**Value, weighed honestly (the efficacy claim is tempered on purpose).**
This is a large multi-surface investment for a modest, partly-speculative payoff. Three
honest deflators the operator should weigh before executing:

1. **The channel is measured low-value.** `UserPromptSubmit` — the sibling stdout-inject
   channel — is described as "the lowest-value measured injection event." The atlases did
   not rate these two events as high-value omissions; they surfaced as **rescued
   over-rejections** (things the refuter *never mined*), i.e. low-priority build-later,
   not build-now.
2. **The `UserPromptExpansion` git-oracle payload has a cheaper alternative.** A slash
   command's `.md` body *is* its expansion. The git-oracle pre-read could simply be a line
   in `.claude/commands/implement-pack.md` (zero hook-count cost) and reach the model at
   the same moment. The event hook earns its slot only for **dynamic or cross-command**
   injection the command author can't statically write. This pack wires the *event*
   (infrastructure); if the only ever-payload is one static discipline, the command-body
   edit wins — flagged in Scope-out.
3. **The `Setup` "pay once" premise is partially stale and unverified.** SessionStart
   re-fires on `resume`/`compact`/`clear` (continuation sources) where `Setup` does **not**
   fire; the SessionStart host-fact line is therefore **load-bearing** for a
   resumed/compacted agent and cannot be removed. So `Setup` can carry *additive* one-time
   onboarding — **not** a replacement for the SessionStart calibration. And the pinned
   excerpt pins only channel/exit-code semantics; it does **not** pin `Setup`'s firing
   *cardinality* (once-per-install vs. every-conversation). The whole "pay once" saving
   depends on cardinality that must be **fetched from the live protocol as pre-work** — if
   `Setup` fires every conversation, the Setup half is a no-op and should be dropped.

Given all three, the pack is authored so the operator can execute it with eyes open; it is
not sold as a high-lift win.

## Scope (in)

### Sub-task 1-A — Author the two reporter hook scripts + earn-red unit tests (smallest; do first)
Two new **non-blocking reporter** hook scripts modelled byte-for-byte on the existing
`tools/cc/hooks/subagent_start.py` reporter (stdin-safe read, exit 0 +
`hookSpecificOutput.additionalContext` JSON, fail-open `main()` umbrella, zero espalier
imports). Self-contained: each is driveable via stdin in a unit test **before** any wiring
exists, so this sub-task surfaces the write_guard/maintenance-mode execution wrinkle early
(writing under `tools/cc/hooks/` on the self-host trips write_guard's protected-zone block
— set `ESPALIER_MAINTENANCE_MODE=1` in the launching shell).

- **`tools/cc/hooks/userprompt_expansion.py`** — reads the UserPromptExpansion payload;
  when the expanded command is `/implement-pack` (or the folder/`--resume` forms), emits
  the git-oracle byte-verify pre-read discipline; stays **silent** (no JSON emit, or an
  empty-context no-op consistent with the protocol) for any non-matching expansion.
- **`tools/cc/hooks/setup_calibration.py`** — emits a one-time adopter first-run
  calibration block (host orientation via `_hook_utils.host_orientation_line()` + the
  workflow-loop pointer: `/status` → `/implement-task` → `/preflight` → `/commit` →
  `/handoff`; read `docs/CONVENTIONS.md`/`docs/SHARP_EDGES.md`). Additive — it does **not**
  remove anything from SessionStart (see 1-A note + Scope-out).

**Hard pre-work gate for the Setup half:** fetch the live hook protocol
(`code.claude.com/docs/en/hooks`) and confirm (a) `Setup`'s firing cardinality and (b) the
`UserPromptExpansion` input schema (which field carries the expanded command name). Pin
the deltas into `docs/external/cc-hook-protocol.md`. If `Setup` fires per-conversation
rather than once-per-install, drop the Setup half to the follow-up ledger and land
`UserPromptExpansion` alone.

### Sub-task 1-B — The multi-surface hook-count bump (12 → 14 hooks / 10 → 12 events)
Any new hook entry script is a hard multi-surface numeric contract. Two scripts double it.
Drive `python3 -m espalier surface-impact` (per `espalier/surface_impact.py::_hook_demands`)
for the authoritative obligation list and satisfy every site:
- `espalier/harness_config.py::CANONICAL_HOOK_WIRING` — two new entries (auto-extends
  `HOOK_EVENTS` 10 → 12).
- `espalier/cli.py::INIT_HOOK_SCRIPTS` — two new script paths.
- `espalier/cli.py::_build_settings_json` — two new event blocks in the `hooks` dict.
- `espalier/surface_contract.py::_CANONICAL_HOOK_SCRIPTS` — two new script names.
- `tests/_surface_expected.py::EXPECTED_HOOK_COUNT` / `EXPECTED_HOOK_ENTRY_COUNT` (12 → 14).
- `.espalier/freshness.json` hook-count fragment; `scripts/wheel_smoke.py` packaged-hook SoT.
- Hardcoded hook-count doc sites: `README.md`, root `CLAUDE.md`, `docs/CHEAT-SHEET.md`,
  `docs/HOOKS.md` (if it carries a count/row), `.claude/skills/design/SKILL.md`
  ("Standard 12 hooks").
- Byte-mirror the two new scripts to `espalier/_vendor/cc/hooks/` via
  `python3 scripts/sync_vendor_cc.py`; re-sync `.claude` asset mirrors via
  `python3 scripts/sync_claude_mirrors.py` (design SKILL.md edit); `espalier integrity
  refresh .` (two new shipped files + mirrors).

### Sub-task 1-C — HOOK_ASSUMPTIONS scope reconciliation (must land WITH 1-B or the doc lies)
- `docs/HOOK_ASSUMPTIONS.md` → *Scope*: change "The 10 events Espalier uses" → 12; add the
  two rows to the scope table; **remove** `Setup` and `UserPromptExpansion` from the
  deliberately-omitted prose (leave PreCompact / SessionEnd / PermissionRequest / etc.),
  and add a one-line note that these two moved omitted → wired in this pack (the same
  transition PreCompact is still mid-way through). Update the count in line 36's pinned
  reference. Keep the honest "no runtime pin for firing cardinality" disclosure — extend
  Assumption 5's re-verify note to cover `Setup`.

## Scope (out)

- **Removing the host-fact line from `session_start.py`.** Deliberately NOT done. SessionStart
  re-fires on `resume`/`compact`/`clear`, where `Setup` does not fire; the host-fact line is
  load-bearing for a resumed/compacted agent. `Setup` is **additive** one-time onboarding, not
  a replacement — this corrects the source brief's "instead of re-emitting every SessionStart"
  framing. Reason: a wrong runtime outcome (a resumed session loses its orientation) if removed.
- **Editing `.claude/commands/implement-pack.md` to carry the git-oracle pre-read statically.**
  The cheaper zero-hook alternative for the *specific* example. Deferred, not folded, because
  the pack's purpose is to wire the *event* for dynamic/cross-command use; if the operator
  judges the event not worth its multi-surface cost, this command-body edit is the honest
  fallback and should be chosen *instead of* landing `UserPromptExpansion`. Reason: cost/value —
  the operator's call, surfaced not buried.
- **Wiring PreCompact / InstructionsLoaded / WorktreeCreate (the other INV-6 planned events).**
  Each is its own event with its own payload design and firing semantics. Reason: scope
  containment — one multi-surface bump at a time.
- **Routing the two payloads through `_reinject.py`'s session-cap machinery.** The registry
  gives session/per-turn caps that matter for high-frequency events; `Setup` fires ~once and
  `UserPromptExpansion` fires only on matching commands, so the cap adds coupling (and the
  `session_start._clean_state_flags` reset ordering question) without benefit. Inline payloads
  (the `subagent_start.py` model) keep each hook self-contained and unit-testable. Reason: no
  benefit, added coupling. (If a *second* dynamic UserPromptExpansion rule ever lands, revisit.)
- **`GOVERNANCE_BLOCKING_HOOKS` / `tools/cc/ci_guard.py` mirror.** Untouched — both new hooks
  are non-blocking reporters (exit 0 + `additionalContext`), never deny gates, so they are not
  fail-open blocking hooks. Reason: not applicable.

## Implementation

**Fix 1-A-1 — `tools/cc/hooks/userprompt_expansion.py` (new file, modelled on
`subagent_start.py`):** the load-bearing shape is the stdin-safe read, the command match,
the single JSON emit, and the fail-open umbrella. The command-detection field name is
**pre-work-verified** against the live schema (placeholder `expanded_command` below —
confirm before landing):

```python
def _run_main() -> int:
    payload = read_stdin_safely()
    # Field name pending pre-work schema fetch; normalize for match.
    expanded = ""
    if isinstance(payload, dict):
        expanded = str(payload.get("expanded_command") or payload.get("prompt") or "")
    if "/implement-pack" not in expanded:
        return 0  # silent: no context for a non-matching expansion
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptExpansion",
            "additionalContext": _GIT_ORACLE_PREREAD,
        }
    }))
    return 0
```

**Fix 1-A-2 — `tools/cc/hooks/setup_calibration.py` (new file, modelled on
`subagent_start.py`):** unconditional one-time calibration; `hookEventName` **must** be the
protocol's exact `Setup` string (verify in pre-work):

```python
def _run_main() -> int:
    read_stdin_safely()  # stdin-discipline contract (tests/test_hook_contracts.py)
    context = "\n".join([host_orientation_line(), _FIRST_RUN_CALIBRATION])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Setup",
            "additionalContext": context,
        }
    }))
    return 0
```

**Fix 1-B-1 — `CANONICAL_HOOK_WIRING` two new entries** (`espalier/harness_config.py`, after
the `context_reinject_failure.py` entry, preserving the trailing-comma dict style):

```python
    "context_reinject_failure.py": {
        "event": "PostToolUseFailure", "matcher": "Write|Edit|NotebookEdit", "timeout": 5,
        "reason": "On a failed Edit/Write (old_string-not-found), injects untrusted-oracle re-derivation (Rule A)",
    },
    "userprompt_expansion.py": {
        "event": "UserPromptExpansion", "matcher": "", "timeout": 5,
        "reason": "Injects slash-command disciplines at expansion time (e.g. the /implement-pack git-oracle byte-verify pre-read)",
    },
    "setup_calibration.py": {
        "event": "Setup", "matcher": "", "timeout": 5,
        "reason": "One-time adopter first-run calibration (host facts + workflow-loop orientation)",
    },
}
```

**Fix 1-B-2 — `_build_settings_json` two new event blocks** (`espalier/cli.py`, in the
`hooks` dict, after the `PostToolUseFailure` block):

```python
            "UserPromptExpansion": [{
                "hooks": [_hook("tools/cc/hooks/userprompt_expansion.py")],
            }],
            "Setup": [{
                "hooks": [_hook("tools/cc/hooks/setup_calibration.py")],
            }],
        },
    }
```

**Fix 1-B-3 — count literals** (one bump each; `tests/_surface_expected.py`):

```python
EXPECTED_HOOK_COUNT = 14  # class: literal  (TP-342: +userprompt_expansion.py, +setup_calibration.py)
EXPECTED_HOOK_ENTRY_COUNT = 14  # class: literal
```

Remaining 1-B sites (`INIT_HOOK_SCRIPTS`, `_CANONICAL_HOOK_SCRIPTS`, `freshness.json`,
`wheel_smoke.py`, the doc count strings) and 1-C: apply the review's cited edits;
`espalier surface-impact` enumerates the complete obligation set — treat its output as the
checklist, not this prose. `.claude/settings.json` on the self-host is gitignored +
guard-protected, so the live self-host wiring comes from **re-running `espalier init .`**
(an operator step in 1-D), not a hand-edit; the committed change is the `_build_settings_json`
source path above.

## Affected symbols

### Added-paths
- `tools/cc/hooks/userprompt_expansion.py::main` — new UserPromptExpansion reporter hook
- `tools/cc/hooks/setup_calibration.py::main` — new Setup reporter hook
- `espalier/_vendor/cc/hooks/userprompt_expansion.py` — byte-mirror (via sync_vendor_cc.py)
- `espalier/_vendor/cc/hooks/setup_calibration.py` — byte-mirror (via sync_vendor_cc.py)
- `tests/test_hooks.py::` (new unit tests for both scripts — earn-red)

### Changed-semantics
- `espalier/harness_config.py::CANONICAL_HOOK_WIRING` — add two event entries (extends `HOOK_EVENTS` 10 → 12)
- `espalier/cli.py::INIT_HOOK_SCRIPTS` — add two hook script paths
- `espalier/cli.py::_build_settings_json` — add UserPromptExpansion + Setup hook blocks
- `espalier/surface_contract.py::_CANONICAL_HOOK_SCRIPTS` — add two script names

## Affected literals
- `EXPECTED_HOOK_COUNT` `12` → `14` (`tests/_surface_expected.py`)
- `EXPECTED_HOOK_ENTRY_COUNT` `12` → `14` (`tests/_surface_expected.py`)
- `"12 hooks across 10 events"` → `"14 hooks across 12 events"` (`docs/CHEAT-SHEET.md`)
- `"12 hook entry scripts"` / tree `"12 hook scripts"` → `14` (`README.md`)
- `"Standard 12 hooks"` → `"Standard 14 hooks"` (`.claude/skills/design/SKILL.md` + mirrors)
- `"governs 10 of Claude Code's hook events"` → `"governs 12"` (root `CLAUDE.md`)
- `"The 10 events Espalier uses"` / `"the 10 events in this subset"` → `12` (`docs/HOOK_ASSUMPTIONS.md`)
- `.espalier/freshness.json` hook-count fragment (`12` → `14`)

## Pass criteria
- `pytest -q` green in a FULL run (the count-pin, doc-parity, provenance, vendor-parity, and
  package-resource-parity contracts fire only in a full run — a shipping-surface edit
  invalidates a targeted pass).
- `ruff check .` clean; `python3 -m espalier audit .` 0/0; `espalier doctor .` clean.
- **1-A UserPromptExpansion earn-red:** a unit test drives `userprompt_expansion.py` with an
  `/implement-pack …` expansion stdin payload → asserts the git-oracle discipline appears in
  `hookSpecificOutput.additionalContext`; a `/status` payload → **no injection** (silent).
  RED before the fix: the test imports/executes a script that does not exist.
- **1-A Setup earn-red:** a unit test drives `setup_calibration.py` → asserts the one-time
  calibration text, `exit 0`, and `hookEventName == "Setup"`. RED before: script absent.
  (Honest note: the source brief's "Setup re-emits every SessionStart → fires once" earn-red
  is re-scoped — the SessionStart host-fact line **stays** load-bearing; the real RED is
  "the `Setup` event has no hook → no first-run onboarding fires" flipping to "the Setup hook
  emits onboarding at conversation start.")
- **1-B earn-red:** with both scripts on disk but the counts still `12`, the surface-count test
  (`EXPECTED_HOOK_COUNT` vs `len(managed_inventory.get_hook_entry_files())`) reds; after the
  bump it greens. `espalier surface-impact` reports every hook-count obligation satisfied.
- **1-B wiring proof:** `espalier init <fresh-fixture>` writes `UserPromptExpansion` and `Setup`
  blocks into the generated `settings.json` (was: absent). Vendor parity
  (`pytest tests/test_vendor_cc_parity.py`) + claude-mirror parity
  (`python3 scripts/sync_claude_mirrors.py --check`) + integrity both green.
- **1-C:** `docs/HOOK_ASSUMPTIONS.md` scope table lists 12 events; `Setup`/`UserPromptExpansion`
  no longer in the deliberately-omitted prose; the doc-parity tests
  (`tests/test_operator_docs.py`, `tests/test_documented_claims.py`) green.

## Files touched
- **New:** `tools/cc/hooks/userprompt_expansion.py`, `tools/cc/hooks/setup_calibration.py`,
  their byte-mirrors `espalier/_vendor/cc/hooks/userprompt_expansion.py` +
  `espalier/_vendor/cc/hooks/setup_calibration.py` (generated — never hand-edit;
  `python3 scripts/sync_vendor_cc.py`), and unit tests in `tests/test_hooks.py`.
- **Modified:** `espalier/harness_config.py`, `espalier/cli.py`, `espalier/surface_contract.py`,
  `tests/_surface_expected.py`, `.espalier/freshness.json`, `scripts/wheel_smoke.py` (if it
  pins a hook count), `README.md`, `CLAUDE.md`, `docs/CHEAT-SHEET.md`, `docs/HOOKS.md`
  (if it carries a count/row), `docs/HOOK_ASSUMPTIONS.md`,
  `.claude/skills/design/SKILL.md` (+ its mirrors via `python3 scripts/sync_claude_mirrors.py`),
  `.espalier/integrity.json` (via `espalier integrity refresh .`).
- **Vendor mirror:** the two new `tools/cc/hooks/*.py` → `espalier/_vendor/cc/hooks/` — run
  `python3 scripts/sync_vendor_cc.py` before commit (`tests/test_vendor_cc_parity.py` reds on drift).
- **On landing (NOT this draft — main session owns ledger rows):** add
  `UserPromptExpansion` + `Setup` to `task-packs/FORWARD_LEDGER.md` INV-6's planned/wired lane
  (they graduate from unmined → wired).
- **Unmodified-on-purpose:** `tools/cc/hooks/session_start.py` (host-fact line stays — load-bearing
  for resume/compact); `espalier/harness_config.py::GOVERNANCE_BLOCKING_HOOKS` +
  `tools/cc/ci_guard.py` (new hooks are non-blocking reporters); `.claude/commands/implement-pack.md`
  (the static-body alternative is Scope-out); `tools/cc/hooks/_reinject.py` (payloads inlined, not
  registry-routed — Scope-out).

## Sub-task ordering
1. **Pre-work** — fetch live protocol; pin `Setup` firing cardinality + `UserPromptExpansion`
   input-schema field into `docs/external/cc-hook-protocol.md`. If `Setup` fires per-conversation,
   drop the Setup half here and land UserPromptExpansion alone. → `git diff docs/external/`
2. **1-A** author both scripts + earn-red unit tests (needs `ESPALIER_MAINTENANCE_MODE=1` to write
   under `tools/cc/hooks/`) → `pytest tests/test_hooks.py -k "expansion or setup"` (RED→GREEN on the
   two new tests; scripts unit-driven, no wiring yet)
3. **1-B** multi-surface bump: CHW + settings builder + INIT/_CANONICAL lists + count literals +
   freshness + docs + vendor re-sync + claude-mirror re-sync + integrity refresh →
   `python3 -m espalier surface-impact` clean + `pytest tests/test_hooks.py tests/test_hook_protocol.py
   tests/test_hook_event_contracts.py tests/test_vendor_cc_parity.py tests/test_package_resource_parity.py`
4. **1-C** HOOK_ASSUMPTIONS scope reconciliation → `pytest tests/test_operator_docs.py tests/test_documented_claims.py`
5. **final** re-run `espalier init .` (regenerate the gitignored self-host settings.json so the two
   events fire locally) → full `pytest -q` + `ruff check .` + `espalier audit .` + `espalier doctor .`;
   stamp Landing; (on landing) update FORWARD_LEDGER INV-6.

## Estimated effort
- Pre-work (live-doc fetch + pin): ~30 min · 1-A (two scripts + earn-red): ~45 min ·
  1-B (multi-surface bump — the bulk; ~18 surfaces): ~2 h · 1-C (doc reconciliation): ~30 min ·
  verify + init-regen + land: ~40 min. **Total ≈ 4.5–5 h.** (If the Setup half is dropped after
  pre-work, ≈ 3 h.)

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: 1-A UserPromptExpansion unit test reds (script absent) then greens injecting the git-oracle discipline on an `/implement-pack` expansion + silent on `/status`; 1-A Setup unit test reds then greens emitting first-run calibration; 1-B surface-count test reds while scripts exist but counts say 12, greens at 14.
- Date:

## Sharp-edge entry to add
Candidate footgun (add only if pre-work confirms it): **"A new stdout-injecting hook event's
firing *cardinality* is not pinned by the protocol excerpt."** `docs/external/cc-hook-protocol.md`
pins channel + exit-code semantics for the wired-event subset, but says nothing about how *often*
`Setup` (or any newly-mined event) fires. Designing a "pay it once" saving on an assumed
once-per-install cardinality is a claim that must be fetched-and-verified from the live protocol
before it is relied on — the same class as Assumption 5's un-pinned SessionStart `source` names.
