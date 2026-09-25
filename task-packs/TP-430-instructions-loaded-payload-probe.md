# TP-430 — `InstructionsLoaded` payload probe (discovery, machine-local)

## Status

- Kind: PACK
- State: **DRAFT** — authored 2026-08-06, not executed
- Author: 2026-08-06
- Target: post-launch (does not block the OSS flip)
- Provenance: **spun out of `TP-429` Fix 4** during that pack's step 0-A review. It was
  removed from TP-429 because it closes none of that pack's three observability gaps (its
  own Reach row read "NOT CLOSED — measured"), cannot complete in one session, and — as
  measured, not reasoned — carried a 13-test blast radius that TP-429's telemetry work does
  not.
- Launch requirement: **`ESPALIER_MAINTENANCE_MODE=1 claude`** — the wiring edits
  `.claude/settings.json`, a `write_guard`-protected exact file. Mid-session `export` does
  not reach already-running hooks.

## Motivation

Claude Code fires an `InstructionsLoaded` event when a `CLAUDE.md`, `CLAUDE.local.md`, or
`.claude/rules/*.md` file loads, carrying a load reason: `session_start` |
`nested_traversal` | `path_glob_match` | `include` | `compact`. The event is **purely
observational** — its exit code is ignored and it has no decision control.

**The input schema is not published.** The field names for the load reason and the file
path are inferred, not documented, and the introducing version is unstated. `INV-6`
(`FORWARD_LEDGER §3`) owns this event along with `PreCompact` and `WorktreeCreate/Remove`,
and *means wiring* — but INV-6 cannot be scoped at all until someone records what the
payload actually contains on the installed Claude Code build.

So the first step is discovery, not design. **This pack produces a recorded schema (or a
recorded negative), and nothing else.**

Why it matters beyond curiosity: the harness's folder-`CLAUDE.md` ladder is load-bearing
and can stale, and `.claude/rules/` adoption is deferred to post-launch. A `path_glob_match`
load reason would instrument the ladder directly — which is an argument for sequencing
rules *after* this probe, not for bundling them.

## Scope (in)

- A throwaway stdin dumper wired machine-locally for one session, recording the verbatim
  `InstructionsLoaded` payload.
- A recorded outcome — populated *or* absent — written into this pack's Landing stanza.
- Unwiring and deleting the probe at pack close.

## Scope (out)

- **Governing `InstructionsLoaded` as an 11th hook event.** Graduating it means
  `EXPECTED_HOOK_COUNT` / `EXPECTED_HOOK_ENTRY_COUNT` (both `12`), `CANONICAL_HOOK_WIRING`,
  the root `CLAUDE.md` hooks table, and the "governs 10 of Claude Code's hook events" claim
  in `CLAUDE.md` + `docs/HOOK_ASSUMPTIONS.md`. Out of scope until the probe proves the event
  fires and carries useful fields. `TP-342`'s 10→12 event-count reconciliation is the
  template to follow *if* it graduates.
- **Closing `INV-6`.** This probes one leg of a three-event row and wires nothing durably.
- **Any adopter-facing artifact.** The wiring is machine-local by construction.

## Implementation

### ⚠ The probe must NOT live under `tools/cc/` or `espalier/`

This is the whole reason the pack exists separately, and it was measured during TP-429's
0-A review, not reasoned about. Creating `tools/cc/hooks/_probe_instructions_loaded.py`
reds **13 tests** for the entire "run one ordinary session" collection window:

`count_claims`, `wheel_smoke`, `manifest_truth`, `vendor_cc_parity`, `selfcheck` ×2,
`release_check` ×3, `release_check_tp37`, `demo_end_to_end`, plus
`test_state_dir_single_source` (on a raw `".espalier-state"` literal) and
`test_exception_policy` (on an unannotated `except Exception:`).

Worst of all, the vendor-parity failure message *instructs* running
`scripts/sync_vendor_cc.py` — which would copy the throwaway into the git-tracked,
wheel-shipped `espalier/_vendor/cc/hooks/` tree. A throwaway probe would ship to adopters.

**Put it in `scripts/` instead**, which is not vendor-mirrored and not hook-enumerated.
Note `scripts/` carries its own `EXPECTED_SCRIPT_COUNT` / `EXPECTED_SCRIPT_NAMES` pins —
verify against `python3 -m espalier surface-impact` before writing, and prefer a path that
is gitignored outright if one exists.

### The probe

```python
#!/usr/bin/env python3
"""THROWAWAY probe -- records the real InstructionsLoaded payload. Delete after TP-430."""
import json
import sys
from pathlib import Path

try:
    payload = json.load(sys.stdin)
except Exception:  # noqa: BLE001 -- a probe never crashes the event it observes
    payload = {"_unparseable": True}
root = Path(__file__).resolve().parents[1]   # <- RECALIBRATE for the chosen location
d = root / ".espalier-state"
d.mkdir(parents=True, exist_ok=True)
with (d / "instructions_loaded_probe.jsonl").open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(payload, sort_keys=True) + "\n")
sys.exit(0)
```

⚠ `parents[N]` is depth-calibrated. The original draft used `parents[3]` for
`tools/cc/hooks/`; a `scripts/` home needs `parents[1]`. Verify by running the file
directly and printing `root` before wiring it.

⚠ `instructions_loaded_probe.jsonl` lands in `.espalier-state/`, which
`tests/test_state_file_flag_parity.py::test_no_unexpected_flag_files` allowlists against a
literal set. Either add it to that set for the duration (and remove it at close), or write
the probe log somewhere outside `.espalier-state/` — the latter is cleaner for a throwaway.

### Wiring

Add an `InstructionsLoaded` entry in `.claude/settings.json`. That file is **gitignored and
guard-protected**: the wiring is machine-local by design and will not travel to adopters or
reach a commit — correct for a throwaway.

### Stop condition (mandatory)

Run one ordinary session, then inspect the log:

- **File absent or empty** → the event does not fire on this build. **Stop.** Record the
  negative result in the Landing stanza, unwire, and do not build on it.
- **File populated** → record the verbatim field names in the Landing stanza. That record is
  the deliverable; wiring a governed hook is a *separate* pack (see Scope out).

Record the Claude Code version the probe ran against, from `claude --version`. A schema
observation without its build number is not reusable.

## Affected symbols

### Added-paths
- *(none — the probe script's location is decided at execution per the constraint
  above; it and its JSONL log are throwaway, deleted at pack close, so neither is a
  path the pre-flight can walk)*

### Changed-semantics
- none. The event is observational; nothing in the harness reads the probe's output.

## Pass criteria

1. The probe's location is outside `tools/cc/` and `espalier/`, verified by
   `python3 -m espalier surface-impact` reporting no vendor-mirror or hook-count obligation.
2. `pytest -q` green **while the probe exists** — not merely after it is deleted. This is the
   criterion TP-429's draft lacked, and the reason this work was split out.
3. `ruff check .` clean while the probe exists.
4. The stop condition is executed and its outcome — populated *or* absent — recorded
   verbatim in the Landing stanza, together with the `claude --version` it ran against.
   **An unrecorded probe result fails this pack; a negative result passes it.**
5. At close: the probe file and its log are deleted, the `.claude/settings.json` entry is
   removed, and `git status` shows no new tracked files.
6. `EXPECTED_HOOK_COUNT` / `EXPECTED_HOOK_ENTRY_COUNT` (both 12) unchanged — this pack
   governs no new event.

## Files touched

**New (throwaway, both deleted at pack close):**
- the probe script
- its JSONL log

**Modified (machine-local, gitignored, not committed):**
- `.claude/settings.json` — wired at 430-A, unwired at 430-C

**Unmodified on purpose:**
- everything under `tools/cc/` and `espalier/` — see the constraint above
- `EXPECTED_HOOK_*` count pins and the `CLAUDE.md` hooks table — graduating the event is a
  separate pack

## Sub-task ordering

- **430-A** Choose the location, recalibrate `parents[N]`, write the probe, verify
  `pytest -q` + `ruff check .` stay green **with the file present**, then wire
  `.claude/settings.json`. → both gates green before the session starts
- **430-B** Run one ordinary session. *(Wall-clock, not effort — nothing to do but work
  normally.)*
- **430-C** Apply the stop condition. Record the verbatim schema or the negative, plus
  `claude --version`, in the Landing stanza. Unwire, delete the probe and its log, confirm
  `git status` clean.

**430-B cannot be compressed.** A pack that stamps LANDED without a recorded outcome fails
Pass criterion 4.

## Estimated effort

| Sub-task | Estimate |
|---|---|
| 430-A | 25 min |
| 430-B | one session of wall-clock (0 min active) |
| 430-C | 20 min |
| **Total** | **~45 min active, spanning two sessions** |

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Date:
- InstructionsLoaded probe outcome:
- Claude Code version probed:
