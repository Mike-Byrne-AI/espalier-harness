# TP-321d — `espalier hook-profile`: turn the asserted injection tax into a measured per-hook number

## Status
- Version target: current (self-host, pre-OSS-launch)
- Change type: FEATURE — new `espalier` CLI surface (measurement/visibility tool); no hook behavior change
- **Kind: PACK**
- Derived from: TP-321 **U4a** (`task-packs/TP-321-internal-upgrades-from-oss-read.md`), the roadmap's
  highest-value borrow. Sized by a **live feasibility probe** (2026-07-24) — the probe is the pack's
  ground truth, TP-321a-style; see Motivation.
- The **only** TP-321 sub-pack carried forward — U2/U3/U4b–e were scrapped by operator decision
  (2026-07-24). TP-321 → `Deferred/` (U4b/U4c retain future merit; U2/U3 are unresolved honesty
  gaps flagged in FORWARD_LEDGER, not fixed by scrapping their packs).

## Motivation

The SessionStart/UserPromptSubmit **injection tax** — the bytes hooks push into the context window
every firing — is something we currently only **assert** ("injection tax unchanged"). There is a hard
backstop (`session_start.py:_MAX_CONTEXT_BYTES = 16_000`) but **no tool that reports the actual
per-hook cost**, so the assertion is unfalsifiable in practice: nobody can see that session_start
injects 8.5KB and task_router injects 0 for a conversational prompt. This is the exact class the
harness exists to catch — a stated property with no measurement behind it (§4 "verify through an
independent oracle"; §8 "turn claims into numbers"). claudekit ships a `profile.ts`; Espalier has no
equivalent. `espalier hook-profile` makes the tax a measured, watchable number.

**Sized by a live probe (2026-07-24), not estimate.** Driving hooks as subprocesses with
side-effect-free payloads, 5 iterations each:

| Hook | latency min/med/max (ms) | output bytes | channel |
|---|---|---|---|
| task_router (conversational) | 36 / 39 / 45 | 0 | (none) |
| write_guard (allow) | 42 / 44 / 48 | 64 | stderr |
| session_start (`source=resume`) | 182 / **203** / 240 | **8470** | stdout JSON `additionalContext` |

Three findings shaped this pack's scope:
1. **session_start is the cost center** — ~5× the latency of the others and ~53% of the 16KB byte
   budget. The profiler's job is to make that visible per-hook, not to gate it.
2. **Channel heterogeneity** (design-critical). Injection lands in stdout-JSON (session_start),
   raw-stdout (task_router advisories — `task_router.py:247`: "NOT a JSON additionalContext
   envelope"), OR stderr (write_guard). A measure that reads only `additionalContext` reports
   task_router as `0B` **falsely** — the profiler MUST sum all three output channels to report a
   true tax.
3. **The payload catalog is load-bearing** — my quick `task_router` payload did not trigger its
   classifier, so it measured 0. A profiler is only as honest as the payload that makes each hook do
   its **real** work; a too-thin payload reports a falsely-cheap number. Building a representative,
   side-effect-free payload per hook is the pack's hardest sub-task, not an afterthought.

## Scope (in)

1. **A new flat CLI subcommand `espalier hook-profile`** (flat to match the existing `diff` / `scan` /
   `strengthen` / `self-host` subcommand style — NOT a nested `hooks profile` group, which would be a
   new dispatch pattern; the roadmap's `hooks profile` spelling is noted but flat is the house style).
   Lives in a new `espalier/hook_profile.py` module; `cli.py` gets the subparser + a thin dispatch.
2. **Subprocess-drive, not import.** The profiler invokes each hook as
   `python3 tools/cc/hooks/<hook>.py` with a payload on stdin — exactly how the hooks run live and how
   `tests/test_hook_protocol.py:34` drives them. This (a) respects the `espalier/ ↛ tools/cc/`
   isolation contract (no import across the layer) and (b) measures the **true** invocation cost,
   interpreter startup included.
3. **A side-effect-free payload catalog** — one representative payload per profileable hook, each
   chosen to trigger the hook's real work WITHOUT mutating state (e.g. session_start `source=resume`,
   a read-only load that does NOT advance the blueprint chain; task_router with a payload that
   actually classifies as multi-step so its advisory fires). The catalog documents, per hook, why its
   payload is inert.
4. **Measure across ALL output channels** — sum stdout (both the JSON `additionalContext` field AND
   raw non-JSON advisory text) + stderr bytes. Report the per-channel breakdown so a hook's tax is
   attributed to the right channel.
5. **Report the spread, not one frame** (§8). N iterations (default 7), report latency
   min/median/max — a single latency reading is noise (the probe saw session_start vary 182–240ms).
6. **Honest token accounting.** Bytes + latency are **measured**; the token figure is an explicitly
   **labeled ESTIMATE** (chars/4 heuristic, stdlib-only — no tokenizer dependency). Do not print a
   token number that reads as measured (§3 direction ≠ magnitude, §6 strip the flattering evidence).
7. **Human table + `--json`.** Default: a readable per-hook table (latency spread, per-channel bytes,
   estimated tokens, total tax). `--json` for machine consumption / a future regression harness.

## Scope (out)

- **A gate.** This is a visibility/measurement tool, NOT an enforcement gate. Latency is
  machine-relative and noisy — gating on it is a false-positive cannon. A byte-budget gate on
  session_start already exists (`_MAX_CONTEXT_BYTES`); a per-hook budget gate is a possible follow-on
  (note it in FORWARD_LEDGER), not this pack. Ship the number first; gate later, calibrated, if ever.
- **Profiling the two side-effecting hooks in their real mode.** `stop_gate.py` runs pytest (Gate 1)
  and `session_start.py` with `source=startup` advances the blueprint chain. The catalog either
  profiles them in an inert mode (session_start `source=resume`) or marks them `skipped: side-effecting`
  with the reason — the profiler must NOT run pytest or advance the chain as a measurement side effect.
  Named explicitly so a future contributor doesn't "complete" the catalog by adding a mutating payload.
- **A real tokenizer dependency** (tiktoken / transformers) — violates the stdlib-only spirit for a
  number that is inherently an estimate anyway. chars/4, labeled.
- **Replacing / merging with `bench/`.** `bench/run_benchmark.py` is the adversarial-bypass corpus — a
  different concern (does the guard block?). The profiler measures cost, not correctness. No overlap.
- **Any change to hook behavior or the injected content.** Read-only measurement.
- **Absolute latency SLAs.** Report is comparative (which hook is the cost center on THIS machine),
  not an absolute performance contract.

## Affected symbols

### Added paths/symbols
- `espalier/hook_profile.py` — the profiler: payload catalog (per-hook inert payloads),
  subprocess driver, multi-iteration timing, all-channel byte accounting, table + JSON rendering.
- `espalier/cli.py` — `p_profile = sub.add_parser("hook-profile", ...)` sibling to the existing flat
  subparsers (near `p_scan`/`p_strengthen`, ~cli.py:4518), plus the dispatch branch that calls into
  `hook_profile`.
- `tests/test_hook_profile.py` — new. Must be classified in `tests/conftest.py::_MARKER_RULES` (or
  carry the `# pytest-marker: default-unit` opt-out) and `git add`-ed before gating (the git-ls-files
  contracts are blind to an untracked file — it false-greens; see `tests/CLAUDE.md`).

### Referenced authorities (read-only)
- `tools/cc/hooks/*.py` — the 12 `main()` entry points being driven (NOT imported).
- `tools/cc/hooks/session_start.py:1300-1306` (`additionalContext` emit + `_MAX_CONTEXT_BYTES`),
  `tools/cc/hooks/task_router.py:247` (raw-stdout advisory channel) — the two channels the byte
  accounting must cover.
- `tests/test_hook_protocol.py:34` — the canonical `subprocess.run(..., input=json.dumps(payload))`
  hook-driving shape to reuse.

### Changed semantics
_None. New read-only command; no existing symbol's behavior changes._

## Implementation

### Sub-task 1 — the payload catalog (hardest first, per finding #3)
Build one side-effect-free payload per profileable hook that triggers its real work. Mine the shapes
from `tests/test_hook_protocol.py` / `tests/test_hooks.py`. For each hook record `(payload, why_inert)`.
Explicitly mark `stop_gate` and any hook that cannot be driven inertly as `skipped` with a reason —
a partial-but-honest catalog beats a complete-but-mutating one. **Verify inertness**: run the catalog,
then `git status` / check the blueprint chain head is unchanged (the profiler ran the hooks for real).

### Sub-task 2 — the driver + all-channel byte accounting
`subprocess.run([sys.executable, "tools/cc/hooks/<hook>.py"], input=json.dumps(payload), ...)`.
Byte tax = `len(additionalContext-from-parsed-stdout-JSON)` + `len(raw-non-JSON-stdout)` + `len(stderr)`.
Parse stdout as JSON when it is JSON (structured channel), else treat the whole stdout as raw-advisory
bytes — so task_router's raw advisory is counted, not reported as 0.

### Sub-task 3 — timing spread + estimate labeling
N iterations (default 7, `--iterations` override); report latency min/median/max. Token column is
`round(total_bytes/4)` with a header/legend marking it **`~est`**, never bare. Bytes + latency carry no
such marker (they are measured).

### Sub-task 4 — rendering
Default readable table (hook, lat min/med/max ms, bytes by channel, total, `~est` tokens, or `skipped:
<reason>`). `--json` emits the same data as a JSON object. Sort by total tax descending so the cost
center surfaces at the top (session_start will).

### Sub-task 5 — test + earn-the-red (see Pass criteria)
Pin (a) all-channel attribution and (b) the estimate labeling; both must earn their red.

## Pass criteria

1. `espalier hook-profile` runs, drives the catalog's hooks as subprocesses, and prints a per-hook
   table sorted by total tax (session_start at/near the top); `--json` emits the same data.
2. **Inertness proven:** running the profiler leaves `git status` clean and the blueprint chain head
   unchanged (no hook mutated state as a measurement side effect). A test asserts a representative
   run is side-effect-free.
3. **Earn-the-red (all-channel attribution — the finding-#2 defense):** a test drives a hook whose
   injection rides **raw stdout** (task_router with a classifying payload) and asserts the profiler
   reports its byte tax as **non-zero**. Break the accounting to `additionalContext`-only → the test
   REDs (reports 0, the false-cheap bug this pack exists to avoid). Restored to green.
4. **Earn-the-red (estimate honesty):** a test asserts the token figure is rendered with the `~est`
   marker (or equivalent) and the byte/latency figures are NOT so marked. Drop the marker → REDs.
5. Full pytest suite green (new `espalier/` module + CLI surface → provenance/anchor/doc-parity fire
   only in a full run). `espalier audit .` 0/0. Integrity refreshed + verified (`espalier/` changed).
6. Surface-impact obligations for a new CLI subcommand satisfied (check `espalier/surface_impact.py`
   / `tests/test_surface_impact.py` for a CLI-command count or help-doc pin; update
   `docs/CHEAT-SHEET.md` + its mirror if it enumerates `espalier` subcommands).

## Files touched
- `espalier/hook_profile.py` (new).
- `espalier/cli.py` (subparser + dispatch).
- `tests/test_hook_profile.py` (new) + `tests/conftest.py` (classify it).
- `docs/CHEAT-SHEET.md` (+ its byte-mirror, if it enumerates `espalier` CLI subcommands).
- `.espalier/integrity.json` (refreshed; gitignored on self-host — local only).
- **Owed:** `task-packs/FORWARD_LEDGER.md` pointer — U4a landed; the per-hook byte-budget **gate** is
  the deferred follow-on (calibrate before gating).

## Sub-task ordering
1 → 2 → 3 → 4 → 5. The payload catalog (1) is the load-bearing, hardest step and defines what every
later step measures — do it first and prove inertness before building on it. Executes under
`ESPALIER_MAINTENANCE_MODE=1` (writes `espalier/` — a protected zone on self-host). `/scope-check
TP-321d` is the pre-flight.

## Landing
- **State: DRAFT**
- Commits: none yet.
- Suite: N/A (not executed). `/scope-check TP-321d` is the pre-flight.
- Earn-the-red: (a) all-channel byte attribution — `additionalContext`-only accounting reports a
  raw-stdout injector as 0B → test REDs; (b) estimate labeling — dropping the `~est` marker → test
  REDs. Both restored to green.
- Owed: FORWARD_LEDGER pointer (+ the deferred per-hook byte-budget gate).
- Date: 2026-07-24.
</content>
</invoke>
