# TP-258 — Golden-injection backbone (ship espalier's lived wisdom at the moment of highest forgetting-cost)

## Status

- **State: DRAFT — DEFERRED (post-launch). A 0-B re-review (2026-07-08) found
  TWO structural blocks + a scoping gap; the pack is NOT executable as drafted.
  Read [Review blocks](#review-blocks-0-b-re-review-2026-07-08--must-resolve-before-execution)
  FIRST and resolve both blocks (and the two open design forks) before executing.**
- Version target: next minor (Wave 1); later waves gated on telemetry
- Kind: PACK  (W1–W3 executable; W4 is a gated ROADMAP wave)
- **Depends on: TP-257 — ✓ SATISFIED** (landed at `task-packs/Done/TP-257-*.md`;
  the PULL-ONLY lessons now ship via the catalogs). This dependency is clear.
- Type: feature (activate the injection rail) + safety-critical enforcement
- Change class: adds a SMALL, curated set of always-on advisory injections +
  one speedbump; no generative/topical auto-push, no runtime signature mining.

## Review blocks (0-B re-review, 2026-07-08) — MUST resolve before execution

A fan-out verification of every load-bearing claim in this pack against HEAD
(6 finders → adversarial refute → completeness critic; every claim grep-confirmed)
found the pack un-executable as drafted. Two structural blocks, one major, four
minors, two open design forks.

**BLOCK 1 — the "no new dispatch" wiring premise is FALSE (headline mechanism is
dead).** `_reinject.check("PreToolUse", …)` at `write_guard.py:687` is reached
ONLY by `mcp__*` tools: the `Write/Edit/NotebookEdit` branch returns at :641,
`Bash` at :656, `PowerShell` at :666 — all *before* :687 (see the code's own
comment, :677-682). G0/G1/G2 key on Write/Edit/Bash, so appended to `REINJECTS`
as drafted they are **dead in a live session** while their `_reinject.check()`-level
unit fixtures still go green — the repo's own `trigger-gated-defect` /
`false-green-lock-test` class. `REINJECTS` holds **zero** PreToolUse rows today
(`_reinject.py:337-342`) — there is no working precedent. **Resolution:** factor
the current :687-695 emit into an `_emit_reinject(...)` helper returning 0; call it
on the `rc == 0` ALLOW branch of the Write/Edit path (post-:641) and the Bash write
path (post-:656) — `rc = check_X(...); if rc: return rc; return _emit_reinject(...)`.
This IS new dispatch in `write_guard.py` (+ its `espalier/_vendor/cc/` mirror) —
now scoped into Affected symbols / Files touched / Estimated effort below. Decide
whether PowerShell is in scope (no golden row keys on it today → default: no).

**BLOCK 2 — guardrail #1 (the admission floor) is not buildable against the
current data model.** This is W1 / sub-task #1, *"the gate every later row
passes,"* built FIRST. It requires each advisory row to expose
`event AND (path_glob OR content-signature) AND ≥1 discriminator`. But
`ReinjectRule` (`_reinject.py:40-49`) has only
`id/event/render/face/cap_exempt/priority/push_eligible` — **no `path_glob`, no
`content_signature`, no discriminator field**; the entire trigger lives inside the
opaque `render` callable. A static assertion cannot prove "≥1 discriminator" or
"does not read prompt text" without AST-inspecting the function body or adding
structured predicate fields (a schema change beyond this pack's budget).
**OPEN FORK — decide before building W1:** (a) add structured predicate fields to
`ReinjectRule` and gate on them, or (b) redefine guardrail #1 as a per-rule
behavioral must-FIRE/must-NOT-FIRE fixture battery (no schema change). *Lean: (b).*

**MAJOR — earn-the-red is false-green-prone.** Every existing reinject test calls
`_reinject.check()` directly; none drives `write_guard.main()`. A must-FIRE fixture
written to that precedent goes green while production stays dead (BLOCK 1).
Reflected into Pass criteria: each must-FIRE fixture must feed a real
Write/Edit/Bash `tool_input` on stdin to `write_guard.main()` and assert
`hookSpecificOutput.additionalContext` is present + exit 0.

**MINORS (fold into the fix):**
- **Channel-XOR negative fixture** — a protected-zone Edit that ALSO matches a
  golden trigger must emit exactly one stdout JSON (the deny), no
  `additionalContext`. The new call-points sit on branches that CAN `deny()`;
  split `rc` first, emit only on `rc == 0`.
- **Global session cap cannibalization** — `REINJECT_PER_TURN_CAP` and the session
  counter are GLOBAL, shared with `ORIENT` + the 7 PostToolUse sync rows; three new
  hot-path rows eat that budget and erode the "rare enough to read as insight"
  thesis. Guardrail #5 caps BYTES, not COUNT — add a count re-think (per-event
  sub-cap?).
- **Maintenance-mode suppression** — the maintenance early-return
  (`write_guard.py:637-638`) also precedes any reinject, so the self-host dev (the
  lived-origin author of every row) gets none. Decide: emit BEFORE the maintenance
  gate (justified — reinject is advisory/frictionless, not the friction the bypass
  targets) or bank the limitation with a Scope note.
- **CP-GITCLEAN under-fire** — the bare `\bgit\s+clean\b` anchor misses
  `git -C <dir> clean -fdx`; reuse `_GIT_PREOPT` (`_speedbump.py:71-80`) or bank the
  under-fire (matches CP-DISCARD's accepted posture) in the must-not-fire notes.

**Confirmed TRUE by the review (do NOT re-touch):** CP-GITCLEAN genuinely absent
from `_DISCARD_RE`/`_bash_patterns` (real new coverage); the
`_assert_search_under_budget` SIGALRM helper exists in `test_redos.py` and is
reusable; the TP-257 dependency is landed (`task-packs/Done/TP-257-*.md`).

**OPEN FORK — is this pack still worth building post-launch?** The "cheap
append-only, ~11h" premise is dead; the real cost is hot-path `write_guard` surgery
+ the guardrail-#1 schema/fixture decision + a cap re-think, for the honest ~4
injections — when `/recall` already ships the deep judgment and TP-257 shipped the
catalogs. G1's per-Edit `git grep` on the PreToolUse hot path is the worst
cost/benefit in the set. Reconsider a trim (keep `CP-GITCLEAN` + the pull-side;
drop or thin the G-rows, G1 first) before committing the effort.

## Motivation

Espalier's injection rail is fully scaffolded and switched off. The value is
not a destructive-command safety net (**System A** — mostly already built:
`CP-DISCARD`/`CP-RMRF`/`CP-FORCEPUSH`), it is **System B: inject what espalier
LEARNED, at the exact moment the chance or cost of forgetting is highest.**

A multi-workflow design + adversarial-mining pass (2026-07-08) converged, via
several corrections, on the defining shape of a worthwhile injection — the
**golden litmus**, which is this pack's standing admission test:

> A golden espalier injection fires at the exact tool-call moment a claim or
> artifact is emitted, on a **clean structural token that a linter proves
> *well-formed* but never proves *true-against-reality*,** gated by an "unless
> the proof is present nearby" suppressor, and carries its own remedy — rare
> enough to read as insight, not nag.
> **Litmus: *the checker is green precisely because nothing checks THIS.***

This is knowledge only espalier can offer, because it accumulated the specific
places where *form is green but reality is red* by shipping into each one. The
mining was deliberately ruthless — a lesson a linter/senior-review would catch
is GENERIC (rejected); a lesson that only fires on espalier-internal plumbing is
SELF-HOST (rejected); a deep lesson with no emit-moment is PULL-ONLY (→ `/recall`,
shipped by TP-257 once it lands, not pushed here). **Honest count: ~4 genuine
golden injections.** A small set of gems is the win; padding is the failure.

Corrections banked along the way (do not relitigate): the destructive-command
"family" (git clean/dd/find-delete/checkout-f) is one theme, not five — System A
collapses to `CP-GITCLEAN` (the one irreversible gap `CP-DISCARD` misses) or
nothing. The self-host-contract rules (doc-token, tools/cc-import, write_guard-
200-byte, untracked-at-commit) are "building-espalier" events, not user events →
cut. "Earn-the-red on a test write" is the noisiest possible rule (fires on 100%
of test edits) → pull-only. "A subagent finding is a claim" (D) is too frequent →
cut.

## The golden set (with lived origin — the unique value)

| id | Lesson (injected) | Moment / trigger | Must-NOT-fire | Lived origin |
|---|---|---|---|---|
| **G0 (C)** | A number (`×`/`%`/`faster`) **or** an efficacy adjective (`cleaner`/`leaner`/`improves`/`reduces`) on a claim surface is *measured (cite)* or *asserted (cut)* | PreToolUse · a Write/Edit to README/CHANGELOG **OR** a `git commit`/`gh pr create` Bash body adds the token, no measurement cited in-block | measurement cited nearby; design-doc intent prose; bare counts; version numbers; token inside code/identifiers | tp204 "oversold frame" — 9 packs claimed big cleaner-wins; measured, the metric barely moved |
| **G1** | You changed this construct at ONE site, but its pre-image still appears at N others — you fixed 1 of a *class* | PreToolUse · an Edit's `old_string`→`new_string` swaps a token-pattern X, and `grep X` still hits tracked non-test/non-vendor source (excluding the edit target) | remaining X only under `tests/`/`_vendor/`/overlay-exempt; a local logic change with no repeating pre-image *(the "deliberately-different sibling" case is an ACCEPTED non-suppressible false positive — see Implementation, not a testable negative)* | TP-194 (1→33 rglob sites), TP-189 (11→58) — a one-site fix + one-site lock test false-greened the class |
| **G2** | A text-mode `subprocess` without `encoding="utf-8"` decodes via the OS locale — green on your host, mojibake on Windows | PreToolUse · diff adds `subprocess.(run\|check_output\|check_call\|Popen\|call)(` with `text=True`/`universal_newlines=True`/str-decoded `capture_output` AND no `encoding=` | `encoding=` present (any value); binary mode; the existing `# contract: ok` opt-out grammar | `session_summary.py` shipped green on a UTF-8 dev host, broke a Windows operator; ruff/pylint cover `open()`, not subprocess |
| **G3** *(Wave 4)* | An AI-written regex/extraction into a surface no test runs is untested intent — run it on the REAL data, confirm the match *set* | PreToolUse · Write/Edit adds a regex char-class/quantifier or `grep -oE`/`sed -E`/`jq`/`re.compile` to `.claude/agents`, `.claude/skills`, `.github/workflows/*.yml`, a pack, or a runnable doc | pattern inside a source module or test (test-covered); a fixed-string grep with no classes/quantifiers; a companion test already asserts the match set | TP-211 — a pasted `[A-Z0-9-]` dropped every lowercase slug; the 5727-green suite was structurally blind |

Deferred-optional (only after the core proves out): **C2** commit/PR
"tested/verified" claim (clean moment, WEAK suppressor — the hook can't see from
text whether the gate ran); **C7** bare POSIX `os.O_NOFOLLOW/O_DIRECTORY/O_NONBLOCK`
(clean, but tiny audience). Both parked in Scope (out).

## Scope (in)

- **W1 — the admission floor + litmus (build FIRST; gates every push).** The 6
  guardrails below, as parity-suite assertions, plus the golden litmus recorded
  as the standing admission test for any future row.
- **W2 — the 3 Wave-1 golden rows + CP-GITCLEAN.** G0(C), G1, G2 as
  `reinject-advisory` rows via `write_guard` PreToolUse(`*`) — **ungated/generic,
  so they reach adopters.** `CP-GITCLEAN` as the lone System-A speedbump.
- **W3 — observe-only telemetry.** `reinject_telemetry.jsonl` fire-log + a
  mechanical per-rule heeded-predicate. No injected text, no LLM. Gates all
  future promotion (W4).

### The 6 guardrails (W1 — mandatory before ANY push fires)

1. **Specificity-floor admission assertion. ⚠ BLOCKED — see [Review blocks],
   BLOCK 2.** As written this is NOT buildable: `ReinjectRule` (`_reinject.py:40-49`)
   has no `path_glob`/`content_signature`/discriminator field — the trigger is an
   opaque `render` callable, so a static assertion cannot prove "≥1 discriminator"
   or "does not read prompt text." Resolve the open fork (schema fields vs
   behavioral fixture battery; lean: behavioral) before building this guardrail.
   Intended behavior once buildable: the assertion walks **every advisory/defensive
   `PreToolUse` row in `REINJECTS`** (NOT `push_eligible=True` rows — `push_eligible`
   is generative-only in the live code, `_reinject.py:47-49, 437`, so a
   `push_eligible` filter would iterate zero advisory rows and vacuously pass). For
   each such row, require `event AND (path_glob OR command/content-signature) AND ≥1
   discriminator`, and reject any predicate that reads prompt text. (Structurally
   bars the topical UserPromptSubmit family.)
2. **Per-rule must-FIRE + must-NOT-FIRE fixtures in CI** (extend the
   `tests/test_reinject_sync.py` parity discipline to the firing predicate —
   closes trigger-rot).
3. **ReDoS budget** — extend `tests/test_redos.py` with a NEW sibling target list
   for the G0/G2/CP-GITCLEAN regexes, reusing its existing SIGALRM per-pattern
   budget helper (do not hand-roll a second timer).
4. **Self-exclusion** — no rule fires on edits to `_reinject.py`/`_recall.py`/its
   registry (heartbeat-self-bootstrap prior).
5. **Per-payload byte ceiling + pointer-over-body** — a NEW byte cap, motivated by
   the §15.4 "per-turn aggregate load" dilution principle (which caps COUNT, not
   bytes — this adds the byte dimension).
6. **`is_self_host_repo` inheritance** asserted per row (adopter-boundary).

## Scope (out)

- **The PULL-ONLY deep wisdom** — "verify the load-bearing premise before you
  build the fix," "the tool you trust most is audited least," "a passing test
  proves the fix did X, never that it didn't *also* do Y," "hedge absolutes about
  a guard," "a subprocess in a loop over an unbounded set is O(n²)," "a site
  count is a FLOOR." These have no clean emit-moment; **pushing them is the noise
  the operator forbade.** They already ship (some are already in the catalogs,
  e.g. the "did-X-not-also-Y" lesson at FAILURE_MODES §11.11) or will via TP-257,
  and surface on demand via `/recall`. Push for the detectable gems; pull for the
  judgment.
- **C2 (commit verification-claim), C7 (POSIX os.O_*)** — deferred: C2's
  suppressor is weak (nag risk), C7's audience is tiny. Revisit after W3 telemetry
  shows the Wave-1 set is low-noise.
- **Every self-host-contract rule** (doc python-token, `tools/cc` zero-import,
  `write_guard` 200-byte, untracked-at-commit) — "building-espalier" events, not
  user events. If wanted as an operator aid, a separate self-host-gated pack.
- **D (subagent-finding-is-a-claim), G (make-a-pack), the generative/topical
  auto-push rail, the self-mining signature↔lesson loop** — deferred/cut per the
  design pass; the learning loop (W4-B) imports ReDoS/Goodhart/trigger-rot at
  once and is gated on demonstrated per-rule lift.
- **System A beyond CP-GITCLEAN** — the destructive core is already built;
  five variations of "don't lose files" is one over-injected theme.

## Implementation

All three Wave-1 rows are appended `ReinjectRule`s in
`tools/cc/hooks/_reinject.py` (+ vendor mirror). **CORRECTION (see [Review blocks],
BLOCK 1): the original "fired via `write_guard.py:687`, no new dispatch, no
hook-count change" claim is FALSE** — :687 is reached only by `mcp__*` tools, so
G0/G1/G2 (keyed on Write/Edit/Bash) never fire through it. The rows require NEW
channel-XOR-safe reinject dispatch on the Write/Edit allow-return (post-:641) and
the Bash write-path allow-return (post-:656) in `write_guard.py` (+ vendor mirror)
— factor the current emit into an `_emit_reinject(...)` helper and call it only on
the `rc == 0` branch. Each carries a ≤N-byte advisory naming the lesson + its
remedy, and reads only `tool_input` (`content`/`new_string`/`command`).

**G0 (C) — un-measured claim.** Two input arms sharing one suppressor:
(a) a claim-surface Write/Edit (README*/CHANGELOG*) — content-regex on the added
text; (b) a Bash `git commit`/`gh pr create` call — content-regex on
`tool_input.get("command","")` (the message/body). Fires on a magnitude token
`[0-9]+(\.[0-9]+)?\s*(x|×|%)` or `\b(faster|slower|cleaner|simpler|leaner|lighter|
improves?|reduces?|streamlines?)\b`, **suppressed** when the same hunk/message
carries a measurement (`measured|benchmark|\b\d+\s*(s|ms|µs)\b|before/after`).
Curate the adjective list tight; do not split the arms — one rule, one suppressor,
or the qualitative half slips. Both arms need a fixture (a doc edit AND a
`git commit -m` with a magnitude claim).

**G1 — one-site class fix.** On an Edit with `old_string`/`new_string`, derive the
changed token-pattern X (the sub-span that differs), then `git grep`/`rg` X across
tracked source **excluding** `tests/`, `espalier/_vendor/`, overlay-exempt paths,
AND the current edit target. Fire (advisory, listing the remaining sites) only
when ≥1 other hit remains. Bound the grep (timeout + head) — it rides the
PreToolUse hot path (see the freshly-catalogued `measure-headline-command-wall-clock`
lesson; this is exactly that risk class). **Accepted limitation:** a bounded grep
cannot tell a "deliberately-different sibling" from a "missed class-fix site" — that
residual false positive is accepted, NOT encoded as a negative fixture.

**G2 — text-mode subprocess.** Content-regex on the added hunk: a
`subprocess.(run|check_output|check_call|Popen|call)(` call whose args contain
`text=True`/`universal_newlines=True`/`capture_output=True` AND no `encoding=` in
the same call. Must-not-fire on `encoding=` present, binary mode, or a
`# contract: ok <rule-id> <reason>` opt-out on the line (reuse the existing
grammar, `docs/CONVENTIONS.md`; do not invent a new pragma).

**CP-GITCLEAN — System A.** New `_speedbump.py` checkpoint, `cap_exempt`:
`Bash` + `\bgit\s+clean\b` + a force flag (`-f`/`-fd`/`-xdf`/`--force`) + NOT
`-n`/`--dry-run`. Deny-once-then-allow; must-not-fire on `git clean -n` / bare
`git clean`. Reuse the existing tokenizer conventions; no new parser. (Verified
genuinely absent from `_DISCARD_RE` and `_bash_patterns` — real new coverage.)

**W3 telemetry.** `check()` (and the speedbump path) append
`{ts, rule_id, signature_hash, event, session_id}` per emitted payload to
`.espalier-state/reinject_telemetry.jsonl` (bounded ~2000 rows, flock/STATE_DIR).
This is a **parallel `tools/cc`-local reimplementation** of the
`espalier/scan_telemetry.py` bounded-JSONL pattern — it CANNOT import that module
(the `tools/cc` zero-espalier-import rule). Each rule declares a
`heeded_predicate` backfilled at `stop_gate` by scanning the session's
`append_audit`/tool stream for the prescribed follow-up. **Invariant: the
telemetry append (success OR failure) must never alter the returned advisory
payload** — test with a forced-failure fixture (unwritable state dir / mocked
`OSError` on append), asserting the payload is unchanged.

## Affected symbols

### Added-paths
- `tools/cc/hooks/_reinject.py` — `G0_RULE`, `G1_RULE`, `G2_RULE`;
  `_LEARNED_SPECIFICITY_FLOOR` admission helper; `_SELF_EXCLUDE` set; per-payload
  byte-cap. (+ `espalier/_vendor/cc/` byte-parallel mirror.)
- `tools/cc/hooks/_speedbump.py` — `CP-GITCLEAN` checkpoint (+ mirror).
- telemetry writer (inline in `_reinject` or a `_reinject_telemetry.py` sibling —
  a `tools/cc`-local reimplementation of the `scan_telemetry` bounded-JSONL shape).
- `tests/test_reinject_golden.py` — the 6 admission contracts + per-rule fixtures.
  Test names follow the sibling convention: `test_g0_fires_on_*` /
  `test_g0_silent_on_*`, `test_g1_*`, `test_g2_*`, `test_cp_gitclean_*`,
  `test_admission_floor_reds_on_*` (no class prefix per CONVENTIONS.md).

### Changed-semantics
- `tools/cc/hooks/write_guard.py::_run_main` — **(BLOCK 1, load-bearing)** add
  channel-XOR-safe PreToolUse reinject dispatch on the Write/Edit allow-return
  (post-:641) and the Bash write-path allow-return (post-:656); factor the current
  :687-695 emit into an `_emit_reinject(...)` helper returning 0. (+ its
  `espalier/_vendor/cc/hooks/write_guard.py` byte-parallel mirror.)
- `tools/cc/hooks/_reinject.py::check` — append a telemetry row; enforce byte
  ceiling + self-exclusion. `ReinjectRule` gains structured predicate fields IFF
  BLOCK-2 fork resolves to (a).
- `tools/cc/hooks/stop_gate.py` — heeded-predicate backfill (**net-new surface** —
  no reinject/heeded wiring exists there today; scope as new, not a tweak).

## Pass criteria

- **Per rule (earn-the-red):** each of G0/G1/G2 fires on its must-FIRE fixture
  and stays silent on its must-NOT-FIRE near-miss (both RED before the rule
  exists). G0 needs BOTH a doc-edit fixture AND a `git commit -m` fixture.
  CP-GITCLEAN fires on `git clean -fdx`, allows on re-issue, silent on `-n`/bare.
  **The must-FIRE fixture MUST drive `write_guard.main()` end-to-end** (real
  Write/Edit/Bash `tool_input` on stdin → assert `additionalContext` in stdout,
  exit 0) — a bare `_reinject.check()` call is a false-green (BLOCK 1 / MAJOR).
- **Channel-XOR (new):** a protected-zone Edit that ALSO matches a golden trigger
  emits exactly one stdout JSON (the deny) and NO `additionalContext`.
- **Litmus admission floor:** the specificity assertion (walking the advisory
  PreToolUse rows — NOT `push_eligible`) goes RED on a synthetic advisory row that
  (a) lacks a discriminator or (b) reads prompt text; every trigger regex passes
  the extended `test_redos`; self-exclusion verified on a `_reinject.py` edit;
  self-host gate no-ops the self-host-scoped rows on an adopter fixture tree.
- **Telemetry never alters the payload:** with the state dir unwritable (mocked
  `OSError` on append), the returned advisory payload is byte-identical to the
  writable case; the log is bounded; heeded backfill works on a fixture session.
- **Adopter reach:** G0/G1/G2 fire on a non-self-host fixture repo (they are
  generic; the gate must NOT suppress them the way it suppresses self-host rows).
- **Regression floor:** `pytest -q` green; `ruff check .` clean; `espalier audit .`
  0/0; vendor mirror byte-parallel (mirror-parity contract);
  `pytest tests/test_hooks.py tests/test_hook_protocol.py tests/test_reinject*.py`.

## Files touched

**New:** `task-packs/TP-258-*`; `tests/test_reinject_golden.py`; the telemetry writer.
**Modified:** `tools/cc/hooks/write_guard.py` (BLOCK 1 — new reinject dispatch on
the Write/Edit + Bash allow-returns), `_reinject.py`, `_speedbump.py`, `stop_gate.py`
+ `espalier/_vendor/cc/**` mirrors (incl. `write_guard.py`); `docs/SHARP_EDGES.md`
(record the golden litmus
+ the new rows — **land AFTER TP-257's SHARP_EDGES.md edits are committed** to
avoid stacked-uncommitted coupling on the same file).
**Unmodified on purpose:** every generative `EXEMPLAR_MAP` row (stays
`push_eligible=False`); the 6 hand-tuned rules; the pull `/recall` corpus; the
existing `CP-*` speedbumps.

## Sub-task ordering

0. **Resolve BLOCK 1 + BLOCK 2 forks FIRST** → (a) `write_guard` call-point surgery:
   add channel-XOR-safe `_emit_reinject(...)` on the Write/Edit (post-:641) and Bash
   (post-:656) allow-returns + vendor mirror; checkpoint = a golden trigger fired via
   `write_guard.main()` end-to-end (stdin → `additionalContext` in stdout, exit 0) AND
   a protected-zone Edit that also matches a trigger emits exactly ONE stdout JSON (the
   deny). (b) decide guardrail-#1 mechanism (schema fields vs behavioral fixtures).
   Until step 0 is green, every later "fixture" that calls `_reinject.check()` directly
   is a false-green.
1. **W1 admission floor + litmus + fixtures scaffold** (the gate every later row
   passes — buildable only after BLOCK-2 fork is decided) → checkpoint: the
   specificity assertion reddens on a bad advisory row.
2. **G2** (cleanest content-regex, tight must-not-fire) → checkpoint: fixtures + `test_redos`.
3. **G0(C)** (two-arm claim rule — doc + Bash-commit — + shared suppressor) → checkpoint: both fixtures; suppressor verified.
4. **G1 — grep construction** → checkpoint: fixtures (fires / silent).
5. **G1 — hot-path latency proof** (separate step; the subprocess-in-hot-path risk) → checkpoint: bounded-grep latency on the real tree.
6. **CP-GITCLEAN** (System-A speedbump) → checkpoint: positive/negative fixtures.
7. **W3 telemetry** → checkpoint: payload-unchanged-on-append-failure; bounded log.
8. **Vendor-sync + verify + tag** → full suite, ruff, audit, mirror parity.

## Estimated effort

**Revised after the 0-B re-review (the "~11h append-only" figure assumed the
disproven no-new-dispatch premise).** Step-0 `write_guard` dispatch surgery +
channel-XOR fixture + drive-`main()` fixtures 2h · BLOCK-2 fork (behavioral-fixture
route) 1.5h, or +2-3h if the schema-field route (a) is chosen · W1 floor+fixtures
2h · G2 0.75h · G0 1.25h (two arms) · G1 2.5h (grep + latency proof) · CP-GITCLEAN
1h · W3 telemetry 2.5h · vendor-sync/verify/tag 1h.
**Total ≈ 14.5–17h** (was 11h; the delta is the newly-scoped hot-path surgery +
fork resolution). (W4 is a separate pack.) NOTE: weigh this against the trim option
in [Review blocks] before committing.

## Landing
- State: DRAFT — DEFERRED (post-launch). 0-B re-review 2026-07-08 found 2
  structural blocks (BLOCK 1 dead wiring, BLOCK 2 unbuildable admission floor) +
  1 major + 4 minors + 2 open forks; scope corrected in-pack. Do NOT execute
  until both blocks + both forks are resolved.
- Commits:
- Suite:
- Earn-the-red: (each rule RED on its must-FIRE fixture — driven through
  `write_guard.main()`, NOT `_reinject.check()` — AND on its must-NOT-FIRE
  fixture-if-too-loose before it exists; the channel-XOR negative fixture RED
  before the split; the admission floor RED on a bad synthetic advisory row
  before the assertion exists)
- Date:

## Wave 4 (deferred ROADMAP — gated on W3 telemetry showing Wave-1 is low-noise)

- **G3** (AI-written-regex-into-untested-surface) — proxy detectability; ship once
  the surface-location inference is tuned and W3 shows Wave-1 heeded-rates hold.
- **C2** (commit verification-claim), **C7** (POSIX `os.O_*`) — optional.
- **The self-mining loop** (capture→signature→`learned_signatures.jsonl`→data-driven
  `check()`→auto-retire) — the genuine "self-learning" finale; imports
  ReDoS/Goodhart/trigger-rot/corpus-collapse together, so it ships LAST, only
  after observe-only telemetry demonstrates per-rule lift. Direction sound;
  magnitude must be measured first.

## The standing admission test (record in docs/SHARP_EDGES.md)

Any future injection MUST pass the golden litmus: fires at an emit-moment, on a
clean structural token a linter proves *well-formed* but not *true-against-reality*,
with an "unless the proof is present" suppressor and a self-carrying remedy —
*the checker is green precisely because nothing checks THIS.* If a linter would
catch it → generic, reject. If no emit-moment → `/recall`, not push. If only
espalier-internal → self-host-gate or reject.
