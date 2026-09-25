# TP-261 — Footgun-shape → memory surface (M1)

## Status

- **State: DRAFT — execution-ready for the chosen exemplar; carries two design
  forks (rail-reach + which footguns).** The mechanism rides the *existing*
  PostToolUse sync rail with no `write_guard` surgery.
- **Review verdict (2026-07-09, `wf_9d4d2eb4`): SOUND-TO-EXECUTE (not fully
  deep-dived).** Its load-bearing precondition — the PostToolUse reinject rail it
  rides is self-host-gated — is VERIFIED (`post_write_check.py:423`) and already
  test-pinned (`tests/test_reinject.py:297/307`), so the adopter-reach reasoning
  rests on solid ground and the CP-DISCARD dedup claim holds. Caveat: no review
  lane deep-dived M1's own mechanism → treat as sound-pending-its-own-scope-walk.
  Parked (Deferred) post-launch.
- Version target: next minor
- Kind: PACK
- Type: feature (surface accumulated `memory/` judgment at the moment its
  footgun-shape recurs — the memory twin of the goal-anchor)
- Change class: appends one `ReinjectRule` to the existing PostToolUse sync rail.
  Frictionless. No new hook, no new dispatch.

## Motivation

Goal-anchor family — shared frame in
[TP-259](TP-259-goal-anchor-opportunistic-scope.md#motivation). Where G1/G2 anchor
to the *project goal*, M1 anchors to *accumulated project judgment*: when an action's
shape matches a footgun the project already paid for, surface that one `memory/`
lesson at the moment of the edit — a speed-bump, not the whole catalog.

The existing PostToolUse sync rows already do exactly this for *sister-site* footguns
("you wrote a hook → close these 12 witnesses"). M1 extends the same rail to
*memory-backed* footguns that aren't sister-site-sync.

## Grep-verified constraints (read before scoping the exemplar)

Two HEAD-checks done before authoring (the TP-258 dead-wiring discipline):

1. **The flagship footgun is ALREADY enforced.** `CP-DISCARD`
   ([_speedbump.py:117-131]) already denies `git checkout -- <path>` / `git restore`
   / `git reset --hard` — i.e. the [git-checkout-nukes-uncommitted-rewrite] memory is
   a *shipped speedbump*, not a gap. M1 must NOT re-implement it. (Same for
   `CP-GITCLEAN`, `CP-RMRF`, `CP-FORCEPUSH`, `CP-GATEWEAKEN`.)
2. **PreToolUse-advisory footguns are BLOCK-1 dead.** A footgun surfaced *before* a
   `Bash`/`Write`/`Edit` runs would need `_reinject.check("PreToolUse", …)`, which is
   reached only by `mcp__*` tools (`write_guard.py:687`; Write/Edit/Bash return
   earlier). Same block TP-258 hit. So M1 v1 lives on **PostToolUse** (rail already
   wired), i.e. footguns whose remedy is a *follow-up action after the edit*, not a
   pre-empt of a destructive command.

Net: M1 v1 = a PostToolUse advisory for a **non-destructive, uncovered, follow-up-
shaped** footgun.

## Fork A — the rail-reach gate

The PostToolUse reinject rail is self-host-gated at the call site (`post_write_check`
calls `check("PostToolUse", …)` only when `is_self_host_repo`). So a PostToolUse M1
row is self-host-only unless the call site changes. For the v1 exemplar below (a
self-host-internal footgun) that gate is *correct* — an adopter never hits it. If a
later M1 row targets an adopter-relevant footgun, revisit. **Lean: accept self-host
scope for v1, banked here (not silently shipped).**

## Fork B — which footgun is the v1 exemplar

Candidate memory-backed footguns with a clean PostToolUse edit-shape (all verified
NOT already covered by a speedbump or an existing sync row):

| exemplar | trigger shape | memory | note |
|---|---|---|---|
| **freshness re-pin (recommended)** | Write/Edit to `.espalier/freshness.json` | [freshness-repin-cohort-clock-trap] | high-value, real scar; "bump `expected_value` in place, keep the cohort date/sha — a fresh `pin` flips co-pinned siblings to critical" |
| write_guard top-200-bytes | Edit to `tools/cc/hooks/write_guard.py` (header region) | [write-guard-first-200-bytes-selfhost-signal] | real, but byte-offset detection at PostToolUse is heuristic (fires on any write_guard.py edit) |
| bundled git-add | Bash containing both `git add` and a maybe-blocked `git commit` | [blocked-bash-call-skips-bundled-git-add] | Bash → PreToolUse → BLOCK-1 dead for advisory; would need the surgery |

**Recommended v1: freshness re-pin** — cleanest edit-shape (a single file path),
genuine scar, no BLOCK-1, and the advisory is useful regardless of which way the edit
went (a reminder at the moment of touching the file).

## Scope (in)

- **1. One PostToolUse footgun-memory row.** `_render_footgun_freshness_repin`: on a
  `Write`/`Edit` to `.espalier/freshness.json`, emit the cohort-clock-trap lesson
  (one line + the remedy), registered as a `face="sync"` `ReinjectRule` on the
  existing rail.
- **2. Self-exclusion + gate parity.** The row self-excludes edits to `_reinject.py`
  (heartbeat prior) and inherits the shared session/per-turn caps.

## Scope (out)

- **The destructive-Bash footgun family** (git checkout/clean/rmrf/forcepush) —
  already speedbumps (CP-*); re-adding them is the "five variations of don't-lose-
  files" over-injection TP-258 rejected.
- **PreToolUse-advisory footguns** (pipefail+`grep -q`, bundled git-add, and the
  general "about to run a scarred command" class) — deferred, **explicitly to avoid
  duplicating the `write_guard` BLOCK-1 dispatch surgery TP-258 owns.** If TP-258
  builds that dispatch, M1's PreToolUse rows become cheap follow-ons; until then,
  don't rebuild it here.
- **A generic "memory → trigger" mining loop** (auto-derive triggers from `memory/`
  frontmatter) — that's the self-mining rail TP-258 W4 defers; M1 v1 is one
  hand-authored row, deliberately.

## Implementation

**Fix — the row** (sibling of `_render_vendor_sync`, `_reinject.py`):

```python
_FRESHNESS_JSON_RE = re.compile(r"(^|/)\.espalier/freshness\.json$")

def _render_footgun_freshness_repin(tool_name: str, tool_input: dict, root: Path) -> "str | None":
    if tool_name not in ("Edit", "Write"):
        return None
    if not _FRESHNESS_JSON_RE.search(_fp(tool_input)):
        return None
    return ("You edited .espalier/freshness.json. Cohort-clock trap: audit_accuracy "
            "measures staleness against the NEWEST pin, so a fresh `espalier freshness "
            "pin <one>` stamps today and flips every co-pinned sibling to critical. To "
            "bump a value, edit `expected_value` IN PLACE and KEEP the cohort date/sha.")

FOOTGUN_FRESHNESS_RULE = ReinjectRule(
    id="REINJECT-FOOTGUN-FRESHNESS-REPIN", event="PostToolUse",
    render=_render_footgun_freshness_repin, face="sync", priority=52,
)
```

Append `FOOTGUN_FRESHNESS_RULE` to `REINJECTS`. **Vendor mirror:**
`python3 scripts/sync_vendor_cc.py`.

## Affected symbols

### Added-paths
- `tools/cc/hooks/_reinject.py` — `_FRESHNESS_JSON_RE`,
  `_render_footgun_freshness_repin`, `FOOTGUN_FRESHNESS_RULE` (+ vendor mirror).
- `tests/test_reinject_footgun.py` — must-fire (edit `.espalier/freshness.json`) /
  must-not-fire (edit another JSON; self-exclusion on `_reinject.py`) fixtures.

### Changed-semantics
- `tools/cc/hooks/_reinject.py::REINJECTS` — one appended row (no new wiring; the
  module's design is "append rows only").

## Pass criteria

- **Earn-the-red (drive the hook):** a PostToolUse `Edit` to `.espalier/freshness.json`
  driven through `post_write_check.main()` (on a self-host fixture tree) emits the
  cohort-clock advisory; an edit to `.espalier/state.json` or any other JSON stays
  silent. RED-provable before the row exists.
- **Self-host gate honesty:** the row no-ops on a non-self-host fixture tree (Fork A
  lean (accept) — asserted, not assumed).
- **Cap accounting:** M1 consumes one shared reinject slot; priority 52 (below the
  SoT-sync rows) so a co-fire drops M1 before a sister-site data-loss nudge.
- **Regression floor:** `pytest tests/test_reinject*.py tests/test_hooks.py -q`
  green; ruff clean; vendor parity; `espalier audit .` 0/0.

## Files touched

**New:** `task-packs/TP-261-*`; `tests/test_reinject_footgun.py`.
**Modified:** `tools/cc/hooks/_reinject.py` + `espalier/_vendor/cc/hooks/_reinject.py`.
**Unmodified on purpose:** every `_speedbump.py` CP-* (M1 does not touch the
destructive family — already covered); `post_write_check.py` call site (rides the
existing self-host-gated call under Fork-A lean).

## Sub-task ordering

0. **Confirm Fork A (self-host scope) + Fork B (freshness exemplar)** with the
   operator → checkpoint: decisions recorded.
1. **The row + registry append** → checkpoint: must-fire/​must-not-fire through
   `post_write_check.main()`; self-exclusion verified.
2. **Vendor-sync + verify + tag.**

## Estimated effort

Fork decisions 0.25h · row + fixtures 1h · vendor-sync/verify/tag 0.5h.
**Total ≈ 1.75h.** (Each *additional* footgun row later is ~0.5h on this rail.)

## Landing
- State: DRAFT — execution-ready for the freshness exemplar; 2 forks (rail-reach
  self-host scope; exemplar choice) with leans recorded. CP-DISCARD dedup verified.
- Commits:
- Suite:
- Earn-the-red: the freshness-json edit fires the advisory through
  `post_write_check.main()`; other-JSON + self-exclusion near-misses stay silent
- Date:
