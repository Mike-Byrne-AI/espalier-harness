# TP-203a — Learning loop: persist the fan-out signal, then propose rules (PACK)

## Status

- **Kind: PACK** (executable; the W1 child of the TP-203 roadmap).
- **Version target:** post-0.8.0b1 (NOT a cut blocker; value accrues with fan-out usage).
- **Type:** feature — the offline learning loop that lets the recall corpus grow
  from real fan-out signal instead of pure hand-curation.
- **Provenance:** machinery + free-lunch grounding wf (`wf_f793cc78-363`, 2026-06-25,
  5 finders) over the live `fan_out_findings` / `_reinject` / corpus surface. The
  design is salvaged in `memory/injection-opportunity-atlas.md` ("fan_out_findings
  closed loop"); blueprint.md §9. **This pack supersedes the roadmap's framing on
  one point** (see Motivation) and inherits two atlas corrections (verification
  seam; the corpus is not a recurrence source).

## Motivation

The fan-out **producer** is battle-tested and already computes everything the
learning loop needs — *per run*. `aggregate_findings()`
(`espalier/fan_out_findings.py:370`) returns a `FindingsSummary` carrying
`by_category`, `by_refutation_outcome`, `survival_rate`
(`=survived/(survived+refuted)`, `None` when uncontested), and per-survivor
`corroboration_count`. Every fan-out review computes this — **and then throws it
away to stdout** (the JS persist agent prints the scalars; only survivors are
written, as 3-field markdown bullets, to the corpus).

**The roadmap (and the synthesis lens) assumed `propose_rules` could read the
existing corpus (`docs/known-findings.md`). It cannot.** The corpus bullet stores
only `location + severity + claim` (`_render_finding_bullet:551`); it **drops**
category, refutation_outcome, survival_rate, the `verification{positive,negative}`
object, corroboration_count, run-id, and all producer identity. Worse, it is
**deduped on (location, claim) with no run boundary** — so it physically cannot
express "this class recurred across ≥3 distinct runs" (you can't tell 3 runs that
each found it once from 1 run that found it 3×). The corpus is free for *dedup*
(its real job), not for *recurrence*.

So the irreducible foundation is a **structured, append-only, run-boundaried
ledger** — exactly what the atlas always specced (`finding_ledger.append_summary →
finding_ledger.jsonl`). The free lunch is that **capturing it is nearly one line at
the existing persist point** (the summary is already in memory there), and that
three of the loop's gates are free reads of already-computed fields. The new work
is the writer, the cross-run roll-up, and the proposal report.

Read through the governing frame: **toolbelt, not security boundary.** The output
is always a *report a human applies* — `propose_rules` never auto-writes a hook.

---

## Scope (in)

| Phase | Sub-task | Free lunch | New work |
|---|---|---|---|
| **A1** | Persist the per-run signal: `espalier/finding_ledger.py::append_summary()` writes one JSONL record per fan-out run; wire it into the fan-out persist step | the `FindingsSummary` is already in memory at persist; producer identity is the existing required `rule_or_scanner` field | the JSONL writer + run-wrapper schema + import firewall |
| **A2** | Propose: `espalier propose-rules` reads the accumulated ledger, computes cross-run recurrence, emits a `RuleCandidate` **report** | report container clones `cmd_scaffolding_bench`; survival/lazy-refuter gates are free reads | cross-run roll-up; author-identity guard; the report content |

## Scope (out)

- **Reading the markdown corpus for recurrence.** Dropped: deduped, no run
  boundary, lossy (location+claim+severity only). It cannot seed a candidate or run
  the gates. The ledger is the source. (The corpus keeps its current dedup job.)
- **Auto-writing `_reinject.py` / applying a candidate.** Forbidden by the
  architecture rule (`espalier/` never imports `tools/cc/`) and by design — the
  human stays the predicate author. `propose_rules` emits a report only.
- **Adding fields to `FINDING_SCHEMA`.** `additionalProperties:false` + the 13
  inlined JS copies pinned by `TestFanoutSchemaParity` make schema fields expensive.
  run-id / promoter / predicate-author live on the **ledger wrapper**, never on the
  finding. Producer identity reuses the existing `rule_or_scanner` field.
- **The W2 effect-measurement counter.** Separate pack (TP-203b); the two share
  only the read-only-CLI pattern, not a data store.

---

## Affected symbols

> Prospective until built. Listed for scope-check.

### Added paths
- `espalier/finding_ledger.py` — `append_summary()` (A1) + `propose_rules()` + `RuleCandidate` (A2) + JSONL I/O
- `cc/finding_ledger.jsonl` — the run-boundaried ledger (commit-vs-gitignore: gitignore; it is per-machine accreting signal — register in `surface_contract._LOCAL_ONLY_PATHS` like the other `.jsonl` rolling logs)
- `tests/test_finding_ledger.py` — A1 writer + A2 proposer earn-the-red
- (A2) `espalier propose-rules` subcommand in `espalier/cli.py`

### Changed semantics
- `.claude/workflows/_fanout_audit.js` (+ the sister review workflows' persist step) — the persist agent prompt gains one `append_summary(...)` call alongside the existing `append_findings_to_corpus(...)`. **No** `FINDING_SCHEMA` change.

---

## Implementation

### A1 — Persist the per-run signal (the foundation; cheap; do first)

The persist agent in every fan-out workflow already holds the full findings list
**and** the computed `FindingsSummary` in memory
(`_fanout_audit.js:230-272`). Add a second sink there.

- **`espalier/finding_ledger.py::append_summary(summary, *, run_id, ts, root)`** —
  serialise one JSONL **wrapper** record per run:
  ```
  {run_id, ts, finder_identities: [<rule_or_scanner values>],
   summary: {by_category, by_refutation_outcome, survival_rate, corroborated, total},
   findings: [<the deduped survivor dicts, raw — verification{positive,negative} and
              corroboration_count included>]}
  ```
  Atomic append (reuse `espalier/atomic_io`); one line per run; never raises on a
  malformed element (mirror `scan_telemetry.append_run`).
  - **run_id + identity live on the wrapper, not the finding** — so the schema and
    the 13 JS copies are untouched. `finder_identities` is read from each finding's
    existing required `rule_or_scanner` field (`fan_out_findings.py:97`) — the
    *producer* axis, for free.
- **Import firewall.** Clone `espalier/scaffolding_canon.py`'s `FORBIDDEN_IMPORTS`
  frozenset + the AST test so `finding_ledger.py` can import `fan_out_findings`
  (espalier→espalier, desired) but the offline/in-loop split stays physical
  (`tools/cc/` can never import it; pinned by `TestToolsCcNoEspalierImports`).
- **Wire it in:** the fan-out persist step gains one `append_summary(...)` call.
  The JS workflows are not vendored/integrity-managed, so this is a prompt edit, no
  mirror/manifest cost.

**A1 pass-criteria seeds:**
- A run with N findings → exactly one JSONL line; re-reading it round-trips
  `survival_rate`, `by_category`, and each finding's `verification` object verbatim
  (earn-the-red: the markdown corpus path loses all three — assert the ledger does not).
- `append_summary` on a malformed finding element drops that element, still writes
  the line, never raises (fail-open writer).
- `tools/cc/` importing `finding_ledger` fails the firewall test (earn-the-red on
  the offline/in-loop boundary).
- `cc/finding_ledger.jsonl` classifies `local_only` via
  `surface_contract.classify_release_path` (not shipped in the wheel/archive).

### A2 — Propose rules from the accumulated ledger (after signal accrues)

- **`propose_rules(ledger)`** in `espalier/finding_ledger.py`: read the N wrapper
  records; compute **cross-run recurrence** — for each `category` (or
  `(location,category)`), the count of **distinct `run_id`s** it appeared in. This
  is genuinely new (a `Counter` + `_dedupe_key` one level up over runs;
  `aggregate_findings` is single-run only). Emit a `RuleCandidate` for any category
  with **recurrence ≥ 3 distinct runs** AND **per-category survival ≥ 0.6**.
- **The author-identity guard (mandatory).** Three distinct actors:
  - *producer* = the finding's `rule_or_scanner` (on the ledger record);
  - *promoter* = whoever invokes `propose_rules` (recorded by the command at run time);
  - *predicate-author* = the eventual human who writes the hook (a downstream
    commit/PR author — not a ledger fact).
  Refuse a candidate whose producer == promoter (self-promotion), and refuse any run
  with **zero `refuted`** findings (lazy-refuter floor —
  `summary.by_refutation_outcome.get("refuted",0)==0`, a free read; distinguish
  "refuter never attempted" from "attempted, refuted nothing" via the `survived`
  count).
- **The report (clone `cmd_scaffolding_bench`, `cli.py:3091`).** A frozen dataclass
  → `asdict` → (`--json` to stdout | atomic-write `reports/rule_candidates.json` +
  a `.md` stub + timestamped history). **Do not invent a format.** Per row, by sink:
  - a recurring **generative** authoring-class → a *paste-ready* `Exemplar(...)`
    literal (data-only, `push_eligible=False`, safe-by-default);
  - a recurring **defensive** finding-class → a *descriptive proposal row* ("class
    X recurred in N runs, survival S; propose a PostToolUse render guarding it;
    exemplar finding = <id>"). The report **cannot** author the `render()` predicate
    (it is hand-written Python in `tools/cc/`); claiming otherwise oversells.
- **verification is an INTENT seed, not the fixture.** Carry
  `verification{positive,negative}` into the candidate as human-readable test-intent
  (per the atlas correction: ReinjectRule has no `verification` field, and a real
  rule fixture asserts against a reconstructed event payload, not finding prose).

**A2 pass-criteria seeds:**
- Category C in 3 runs all survival ≥ 0.6 → exactly one `RuleCandidate` for C;
  C in 2 runs or survival < 0.6 → none (threshold earn-the-red).
- producer == promoter → candidate REFUSED with a reported reason.
- A run with 0 refuted promotes nothing even if recurrence/survival pass.
- A generative class → a paste-ready `Exemplar(...)`; a defensive class → a
  descriptive row (NOT a fabricated `render()`).
- `propose_rules` consumes the ledger JSON, never `docs/known-findings.md` (assert
  it ignores a corpus-only class).

## Pass criteria

1. A1: fan-out runs persist a round-trippable per-run ledger record; the firewall
   + local_only classification hold.
2. A2: `espalier propose-rules` emits the candidate report from the ledger with the
   recurrence × survival gates and the author-identity + lazy-refuter guards.
3. Full suite green; `espalier audit .` 0/0; no `FINDING_SCHEMA` change (the 13 JS
   copies + `TestFanoutSchemaParity` untouched).

## Files touched

**New:** `espalier/finding_ledger.py`, `tests/test_finding_ledger.py`, `cc/finding_ledger.jsonl` (gitignored), `task-packs/TP-203a-...md` (this file).
**Changed:** `espalier/cli.py` (A2 subcommand), the fan-out workflow persist step(s) (A1 wiring), `espalier/surface_contract.py` (`_LOCAL_ONLY_PATHS` entry), CHANGELOG.

## Sub-task ordering

1. **A1 first** — it is cheap and the value accrues over time (the ledger must
   collect runs before recurrence means anything). Ship it whenever; it starts the
   clock.
2. **A2 second** — only once the ledger has ≥3 runs of real signal; otherwise
   `propose_rules` has nothing to promote.

## Estimated effort

- A1: ~1 day (writer + wrapper schema + firewall + tests + persist wiring).
- A2: ~1.5 days (cross-run roll-up + author-identity guard + report + tests).
  The hard part is guard *correctness*, not lines.

## Build notes — A1 grounding corrections (wf_a2e70092-5b7, 2026-06-25)

The machinery-grounding pass corrected four A1 claims (reality honored over the
pack prose — *a pack's prescribed fix is a claim*):

1. **`espalier/atomic_io` → `espalier/_atomic_io.py`** (underscore), AND it is a
   whole-file `tempfile + os.replace` *overwrite*, not an append. Append-only
   JSONL uses a plain `open(path, "a")` single-line write — mirror
   `scan_telemetry.append_run`, not `_atomic_io`. (Both pack phrasings — "reuse
   atomic_io" and "mirror append_run" — described two different mechanisms.)
2. **Import firewall already exists.** The stated need ("tools/cc can never import
   finding_ledger") is enforced with ZERO new code by
   `TestToolsCcNoEspalierImports.test_tools_cc_has_zero_espalier_imports` — a
   glob-wide scan matching the whole `espalier.` namespace. The
   `scaffolding_canon.FORBIDDEN_IMPORTS` clone the pack prescribed is the WRONG
   model (file-specific de-circularization, opposite direction). Instead A1 makes
   `finding_ledger.py` a **stdlib leaf** (no runtime espalier import — the
   `FindingsSummary` import is `TYPE_CHECKING`-only; `append_summary` duck-types
   the summary) and pins it with an AST runtime-import test + a namespace
   negative-proof.
3. **`_LOCAL_ONLY_PATHS` needs an EXACT entry**, never a `cc/` prefix (cc/ carries
   committed public surfaces: COMMANDS.md, LIVE_SURFACE.md, PACK_MANIFEST.txt).
4. **Five sister workflows carry the persist bridge, but only `_fanout_audit.js`
   was wired.** It is the generic *standing* fan-out caller; the other four
   (`_deep_review_2026_06_18`, `_deep_review_round7`, `_oss_convergence_round4`,
   `_layered_review`) are dated one-off review snapshots — re-running one and
   logging it as a fresh run would **double-count** that past review's findings
   into the cross-run recurrence signal. Wiring only the standing scaffold is the
   correct scoping, not a shortcut. (`summ` — the all-findings summary, incl.
   refuted — is recorded, not survivors-only; the corpus still gets survivors.)

`read_ledger()` (malformed-tolerant, mirrors `read_history`) was added alongside
`append_summary` — A2 reads the ledger through it.

## Landing

- State: A1 LANDED (A2 still DRAFT)
- Commits:               # filled at commit
- Suite:                 # filled at commit (full green + 13 new tests in test_finding_ledger.py)
- Earn-the-red: fail-open (narrowed except → OSError propagates); stdlib-leaf
  (runtime espalier import → AST test flags it); round-trip + malformed-drop
  proven against the real `aggregate_findings` producer.
- Date: 2026-06-25
