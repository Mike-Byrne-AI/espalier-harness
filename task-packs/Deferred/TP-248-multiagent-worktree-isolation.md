# TP-248 — Multi-agent worktree isolation: policy, nudge, and the shared-tree failure mode

## Status
- Version target: next minor
- Change type: hardening (failure-mode capture + advisory-hook nudge + convention)
- **Kind: PACK**
- **Execution split (2026-07-03):** 248-B + 248-C (doc capture) **LANDED**;
  248-A + 248-D (advisory-hook nudge + vendor re-sync) **DEFERRED** to
  `FORWARD_LEDGER` **DEF-14** on signal-density grounds (revisit bar: a
  second real shared-tree incident). Pack relocated to `Deferred/`. See
  `## Landing`.

## Motivation

On 2026-06-23 (TP-212) a spawned `failure-mode-reviewer` agent with
`Bash(git *)` ran a `git stash` / `git stash pop` A/B experiment to
isolate a test failure. The pop restored file *contents* but silently
left the main session's staged deletions **un-staged**. `fuse` builds
its file set from `git ls-files` (the index), so the un-staged-but-
disk-deleted files reappeared → **25 tests flipped green→red**. The
"5690/0 green" the main session had verified was true when run and
false minutes later — caught only by re-running the suite after the
agent returned.

Root cause: **a spawned agent shares the main session's LIVE working
tree + git index unless launched with `isolation: worktree`.** Its git
side-effects (stash/reset/checkout/branch-switch) mutate the operator's
live staged state. This is not a hypothetical — it has one measured
instance, and the surface widens the moment concurrent fan-out agents
run on this repo.

The lesson lives in `memory/subagent-git-access-mutates-shared-tree.md`
but has **no repo-doc surface and no mechanical nudge**. This pack fixes
both, and encodes the isolation policy as a convention.

### Honest scoping (read before executing)

- **You cannot *force* isolation from a hook.** `isolation: worktree`
  is set by the *caller* at spawn time; no hook event can retroactively
  sandbox an already-launched agent. This pack delivers a **convention +
  an advisory nudge**, not a mechanical guarantee. Do not oversell it as
  enforcement (§3 direction ≠ magnitude).
- **NOT "all agents in worktrees."** Worktrees cost ~200–500ms + disk
  each. Read-only review/audit agents (Explore, code-reviewer, the
  fan-out finder lanes) must stay read-only — that is the existing
  correct pattern and cheaper. Isolation is for **mutate-capable agents
  that run concurrently OR whose git/file side-effects you cannot afford
  to land on your live tree.**

## Scope (in)

1. **248-A** — Advisory nudge in `subagent_start.py`: when the subagent
   shares the main worktree (detected via `git rev-parse --git-dir` vs
   `--git-common-dir`), append a caution telling it to keep git
   read-only. Fail-open; silent inside a linked worktree.
2. **248-B** — Document the failure mode in `docs/FAILURE_MODES.md`
   (new §16.1) and `docs/SHARP_EDGES.md`.
3. **248-C** — Encode the isolation policy in `docs/CONVENTIONS.md`
   under the existing *Agent Design Conventions* section.
4. **248-D** — Re-sync the vendored byte-copy
   (`espalier/_vendor/cc/hooks/subagent_start.py`) and confirm mirror
   parity + hook tests.

## Scope (out)

- **A `PreToolUse(Task)` gate that denies un-isolated mutate-capable
  spawns.** Deferred: the spawn payload does not reliably expose the
  child's tool grants or the `isolation` flag at the gate, and this repo
  is a *toolbelt, not a security boundary* — a hard deny on agent spawns
  is friction that outranks the class it closes. Revisit only if a
  second real incident lands. (`memory/espalier-is-workflow-toolbelt-not-security-boundary.md`)
- **Auto-worktree-wrapping of every spawned agent.** Deferred: cost
  (~200–500ms + disk per agent) and it breaks read-only review lanes
  that legitimately need to see the live diff. Isolation stays a
  per-spawn caller decision.
- **A concurrent "what's-changing" coordination board.** Separate,
  larger design (forward-ledger candidate); a board broadcasts *declared
  intent* but would not have caught TP-212's *undeclared* index mutation.
  Not this pack.
- **Retrofitting existing fan-out workflows.** The `.claude/workflows/*`
  finders are read-only reviewers (`agentType` review lanes) — already
  correct. No change needed; verified none pass `isolation` today.

## Implementation

### 248-A — Advisory nudge in `subagent_start.py`

The hook currently injects `_orientation_line()` + `_SCHEMA_POINTER`.
Add a shared-tree detector and a caution constant, and append the
caution only when in the shared main tree.

**Fix A-1 — add `subprocess` to the imports:**

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
```

**Fix A-2 — add the detector (fail-open) near the other helpers:**

```python
def _in_shared_main_tree() -> bool:
    """True when the subagent shares the operator's main worktree + index.

    A linked worktree (spawned with ``isolation: worktree``) has its own
    index: ``--git-dir`` (…/.git/worktrees/<name>) differs from
    ``--git-common-dir`` (…/.git). In the main tree both resolve to the
    same path. Fail-OPEN: any git error / non-repo context → ``False`` so
    we never manufacture a spurious caution. Paths normalized via
    ``as_posix()`` for Windows separator parity.
    """
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--git-dir", "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if cp.returncode != 0:
        return False
    lines = [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]
    if len(lines) != 2:
        return False
    git_dir, common_dir = (Path(p).resolve().as_posix() for p in lines)
    return git_dir == common_dir
```

**Fix A-3 — add the caution constant next to `_SCHEMA_POINTER`:**

```python
_SHARED_TREE_CAUTION = (
    "You share the operator's LIVE working tree + git index (you were NOT "
    "launched with isolation: worktree). Keep git READ-ONLY: use "
    "status / diff / log / show only. Do NOT run stash, reset, checkout "
    "<ref>, or branch switches — they mutate the operator's staged state "
    "and can silently invalidate a verified-green gate (this has happened: "
    "an A/B stash experiment once un-staged deletions and flipped 25 tests "
    "green->red). If you must mutate files in parallel, the operator should "
    "re-spawn you with isolation: worktree."
)
```

**Fix A-4 — append the caution conditionally in `_run_main`:**

```python
    read_stdin_safely()
    parts = [_orientation_line(), _SCHEMA_POINTER]
    if _in_shared_main_tree():
        parts.append(_SHARED_TREE_CAUTION)
    context = "\n".join(parts)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context,
        }
    }))
    return 0
```

> **Self-collision sweep (mandatory, per `tools/cc/hooks/CLAUDE.md` step 3):**
> the caution literal names `stash`, `reset`, `checkout` in a non-`_`
> hook. Before commit, run the `docs/SHARP_EDGES.md` "A new
> pattern-detector trips the harness's own defenses" sweep to confirm no
> dangerous-bash / subprocess-contract scanner treats these prose tokens
> as live commands. Expectation: clean (they are string-literal advisory
> text, not executed), but verify — do not assume.

### 248-B — Document the failure mode

**FAILURE_MODES.md** — new top-level section after §15, matching the
§14.4 entry shape (`**Definition.** / **When this fires.** / **Concrete
repo example.** / **Mitigation.**`):

```markdown
## 16. Multi-agent / concurrent shared-tree failure modes

### 16.1 Spawned agent mutates the shared worktree + index

**Definition.** A sub-agent (Agent/Task tool) granted `Bash(git *)` —
or any Write/Edit — operates on the SAME working tree and git index as
the main session, not a copy, unless launched with `isolation:
worktree`. Its git side-effects (stash, reset, checkout, branch switch)
mutate the operator's live staged state.

**When this fires.** Any spawn of a mutate-capable agent without
worktree isolation; the damage is invisible until the operator re-checks
`git status` / re-runs a gate.

**Concrete repo example.** TP-212 (2026-06-23): a `failure-mode-reviewer`
ran `git stash` / `git stash pop` to A/B a test failure. The pop
restored file contents but left staged deletions un-staged; `fuse`
(reads `git ls-files`) saw the reappeared files and 25 tests flipped
green->red. The main session's verified "5690/0 green" was false minutes
later, purely from the agent's side-effect.

**Mitigation.** (1) Spawn mutate-capable / concurrent agents with
`isolation: worktree`. (2) Prefer read-only agents (Explore; Bash scoped
to non-mutating verbs) for review/audit. (3) After a git-capable agent
returns, re-verify `git status` + `git diff --cached` and re-run the
gate before trusting a pre-agent green. (4) `subagent_start.py` emits a
shared-tree caution when the subagent is in the main tree (TP-248-A) —
advisory, not a lock. Dual of §-agent-output-is-a-claim: output is a
claim to verify; side-effects on shared state are real and can silently
invalidate verified state.

---
```

**SHARP_EDGES.md** — new `## ` section (prose style, matching existing
entries):

```markdown
## Spawned agents share one worktree + index — isolate mutate-capable fan-outs

An Agent/Task sub-agent runs in the MAIN session's live worktree and git
index, NOT a sandbox — unless you launch it with `isolation: worktree`.
A git-capable agent's stash/reset/checkout mutates your staged state; a
verified-green suite can go red minutes later with no visible cause (a
real TP-212 instance flipped 25 fuse tests via an A/B stash experiment).
Rule: spawn mutate-capable or concurrent agents with `isolation:
worktree`; keep review/audit agents read-only; re-verify `git status`
and re-run gates after any git-capable agent returns. See
FAILURE_MODES §16.1.
```

### 248-C — Encode the policy in CONVENTIONS.md

Extend the existing *Agent Design Conventions* section (do not create a
rival section) with:

```markdown
### Agent isolation

- Spawn a mutate-capable agent (Write / Edit / `Bash(git *)` or any
  file-writing Bash) with `isolation: worktree` when it runs concurrently
  with other work or when its side-effects must not touch your live tree.
- Keep review/audit agents read-only (Explore, or Bash scoped to
  status/diff/log/show) — do NOT worktree-wrap them; worktrees cost
  ~200-500ms + disk each and read-only lanes need the live diff.
- After any git-capable agent returns, re-verify `git status` /
  `git diff --cached` and re-run the relevant gate before trusting a
  pre-agent green result. See FAILURE_MODES §16.1.
```

### 248-D — Re-sync the vendored mirror

`tools/cc/` is vendored byte-for-byte to `espalier/_vendor/cc/`. After
editing `tools/cc/hooks/subagent_start.py`, re-copy it to
`espalier/_vendor/cc/hooks/subagent_start.py` (via the repo's vendor-sync
path) and run the mirror-parity contract so the wheel/fuse overlay ships
the identical hook. Byte-identical mirror required.

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/subagent_start.py::_run_main` — appends the shared-tree
  caution when in the main tree
- `espalier/_vendor/cc/hooks/subagent_start.py::_run_main` — vendored mirror

### Added-paths
- `tools/cc/hooks/subagent_start.py::_in_shared_main_tree`
- `tools/cc/hooks/subagent_start.py::_SHARED_TREE_CAUTION`

## Pass criteria

1. **Earn-the-red:** a new test asserts the caution string is ABSENT from
   the pre-change hook's output and PRESENT after — confirmed RED on the
   base commit before the fix lands.
2. `_in_shared_main_tree()` returns `True` in the repo's main tree,
   `False` when `git rev-parse` is monkeypatched to a differing
   dir/common-dir (worktree simulation) and when git errors (fail-open).
3. Hook still exits 0 with valid `hookSpecificOutput` JSON in all cases
   (channel-XOR intact; reporter never exits 2).
4. `pytest tests/test_hooks.py tests/test_hook_protocol.py` green.
5. Vendored-mirror parity test green (byte-identical copy).
6. Self-collision sweep clean (no scanner trips on the caution literal).
7. Full suite green; ZERO deny-predicate changes.
8. `espalier audit .` clean.

## Files touched

**Modified:**
- `tools/cc/hooks/subagent_start.py`
- `espalier/_vendor/cc/hooks/subagent_start.py` (vendored mirror)
- `docs/FAILURE_MODES.md`
- `docs/SHARP_EDGES.md`
- `docs/CONVENTIONS.md`
- `tests/test_hooks.py` (new tests for the caution + detector)

**New:** none.

**Unmodified on purpose:**
- `.claude/workflows/*` — finder lanes are read-only reviewers; verified
  none pass `isolation` today, so no retrofit needed.
- `memory/subagent-git-access-mutates-shared-tree.md` — the lesson SoT;
  this pack cross-references it, does not duplicate.

## Sub-task ordering

1. **248-A** (smallest concrete change first + surfaces the git-detection
   env early) — edit hook, add tests, confirm earn-the-red RED→green.
   Checkpoint: `pytest tests/test_hooks.py tests/test_hook_protocol.py`.
2. **248-D** — re-vendor the mirror. Checkpoint: mirror-parity test.
3. **248-B** — FAILURE_MODES §16.1 + SHARP_EDGES entry. Checkpoint:
   `espalier audit .` + doc-accuracy scan.
4. **248-C** — CONVENTIONS.md policy. Checkpoint: `espalier audit .`.
5. **Verify + tag** — full suite green, ZERO deny-predicate changes,
   self-collision sweep clean. Checkpoint: full `pytest -q`.

## Estimated effort

- 248-A: ~30 min (hook + tests + earn-the-red)
- 248-D: ~5 min (vendor sync + parity)
- 248-B: ~15 min (two doc entries)
- 248-C: ~10 min (one convention block)
- Verify + tag: ~10 min
- **Total: ~70 min**

## Pre-work / RUNBOOK notes

- **Read the live `subagent_start.py` first** — the Fix blocks above are
  a design snapshot; confirm the insertion points against current bytes
  before applying (`memory/pack-code-examples-are-claims-test-them.md`).
- Source edits under `tools/cc/` and `docs/` — `tools/cc/` is a
  plan-exempt prefix; `docs/` is NOT, so the RUNBOOK creates an execution
  plan via `tools/cc/execution_plan.py` before touching the doc files.
- Tag `pre-pack` at start; rollback via `git reset --hard pre-pack`.
- This is a harness self-edit → launch with
  `ESPALIER_MAINTENANCE_MODE=1 claude` in the parent shell (do not inline
  it on a git command — a blocked call skips its bundled `git add`,
  `memory/blocked-bash-call-skips-bundled-git-add.md`).

## Landing
- State: PARTIAL — 248-B + 248-C LANDED; 248-A + 248-D DEFERRED → FORWARD_LEDGER DEF-14
- Commits: B/C doc-capture in working tree (uncommitted at time of deferral); A/D unshipped
- Suite: docs-only change — provenance census 0 offenders, `test_operator_docs`/`test_surface_support_matrix` 37p, `test_no_provenance_in_shipped_code` 2p, doc-accuracy slice 55p, `espalier audit` 0/0 (2026-07-03)
- Earn-the-red: N/A for B/C (doc-only, no runtime surface). A/D (deferred): caution string ABSENT on base hook output, PRESENT after 248-A — assert RED on base commit first
- Date: 2026-07-03 (B/C)
