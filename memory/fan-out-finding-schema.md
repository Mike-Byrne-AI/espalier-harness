# Fan-out finding schema

**Status:** active
**Linked from:** (unlinked) — standalone reference; salvaged from a dropped blueprint.

A shared structured-output contract for **workflow / fan-out agents** to
return findings in, so aggregation and adversarial refutation across many
agents are cheap. It is a *wire format*, not a paraphrase of any canon —
so it carries **no parallel-inventory drift hazard** (unlike a distilled
copy of `docs/FAILURE_MODES.md` etc.). Adopt by passing it as the `schema:`
option on `agent()` calls (the Workflow tool's StructuredOutput path), or as
the return shape for `Task`-tool review/audit subagents.

**The schema is code, not prose.** The single source of truth is
`FINDING_SCHEMA` in [`espalier/fan_out_findings.py`](../espalier/fan_out_findings.py)
— a JSON-Schema (draft 2020-12) `dict` literal, importable and usable directly
as a StructuredOutput schema. This doc deliberately does **not** re-embed the
JSON literal (that second copy would be the drift hazard this very doc warns
against); read the module for the exact shape.

**v2 (TP-185) — a finding accretes fields across its lifecycle.** The 13 CORE
fields are required (the FINDER supplies them); the 7 OPTIONAL fields are added
downstream and absent at finder time. Making the harness-specific fields optional
(rather than required) is what lets a *generic / external* review agent return a
valid finding without inventing harness coinages.

- **CORE (required):** `id`, `title`, `rule_or_scanner`, `violated_invariant`,
  `category` (string|null), `location`, `claim`, `minimal_repro`,
  `verification{positive,negative}`, `confidence` (`high|med|low`),
  `proposed_fix`, `severity` (`blocker|major|minor|nit`), `blocks_release` (bool).
- **OPTIONAL — refuter-set:** `named_unit` (string|null coinage),
  `refutation_outcome` (`unattempted|survived|refuted`), `refutation_reason`
  (citing the bytes read), `corrected_confidence`, `corrected_category`,
  `externally_verified` (bool — a non-LLM oracle confirmed it).
- **OPTIONAL — aggregator-set:** `corroboration_count` (int ≥1 — independent
  finders that collapsed to this one; >1 = corroborated).

## Field notes (the non-obvious ones)

- `named_unit` — the `docs/FAILURE_MODES.md` §1 coinage the finding
  instantiates (e.g. `"convergence theater"`), or `null` if novel.
  Lets the aggregator group findings by shape and route to sister sites.
  Validate it against the closed coinage set via
  `espalier.canon_vocab.load_failure_mode_coinages()`, which reads **only**
  the `docs/FAILURE_MODES.md` §1 registry — a `SHARP_EDGES`-only coinage is
  *not* in-vocabulary and `aggregate_findings` reports it in
  `unknown_named_units`.
- `category` — a coarse aggregation bucket from a **domain-supplied** controlled
  vocabulary (NOT a hardcoded enum), or `null` when the finding fits none.
  Validate it against a `known_categories` set passed to
  `aggregate_findings(known_categories=...)`, exactly as `named_unit` is
  validated against `known_units`; out-of-vocab values surface in
  `unknown_categories`. Each review *type* brings its own buckets — a hardcoded
  enum was tried and falsified (a blueprint-review vocabulary piled **46%** of
  pack-artifact findings into one catch-all). Two **example** vocabularies
  (non-canonical, ship none as authoritative): a blueprint-review set
  (`claim-accuracy`, `coherence`, `sovereignty`, `design_goal`, `honest_scope`)
  and a pack-review set (`unbuildable-code`, `false-green-gate`, `stale-prereq`,
  `sister-site`, `doc-drift`). `category=None` is one visible bucket, so the
  aggregation actually aggregates instead of yielding groups-of-1.
- `verification.positive` / `.negative` — the two-sided **earn-the-red** proof
  the repo already demands of every scanner gate (catches the bad / clears the
  good). Forcing it into the finding shape makes "did this agent actually
  verify?" a structural field, not a hope.
- `refutation_outcome` (`unattempted` | `survived` | `refuted`) — the
  adversarial-verify gate as an *outcome*, not a boolean. `aggregate_findings`
  reports `by_refutation_outcome` and `survival_rate` = survived / (survived +
  refuted), `None` when nothing was contested (distinguishes "no refuter ran"
  from "all refuted"). A degenerate refuter that never overturns anything still
  reads 1.000 — this measures refuter *outcomes*, not finding quality. (The
  predecessor `refutation_attempted` bool fed a `refutation_coverage` =
  fraction-attempted vanity metric, structurally 1.000 for an always-refute
  pipeline; replaced.)
- `title` — a short (≤8-word) label distinct from the one-sentence `claim`. It is
  what triage tables and roadmap rows display; before v2 reviewers re-coined it
  ad-hoc (it appeared in 3 of the 4 forked findings-JSON shapes).
- `severity` (`blocker|major|minor|nit`) + `blocks_release` (bool) — the triage
  rank and the *single* canonical release-gate flag. Before v2 these were
  re-invented across packs (`severity` 4 ways; the gate flag 3 ways as
  `blocks_b1` / `blocks_oss_cut` / `launch_relevance==blocker`). `blocker`
  severity implies `blocks_release=true`.
- `refutation_reason` / `corrected_confidence` / `corrected_category` — the
  refuter's output, which before v2 lived only in per-workflow `VERDICT_SCHEMA`
  copies (re-invented every fan-out). `aggregate_findings` aggregates `category`
  and `confidence` on the EFFECTIVE value — the `corrected_*` override wins when
  the key is present — so the distribution reflects the reviewed state.
- `externally_verified` (bool) — true only when a **non-LLM oracle** (grep / test
  / git / a real run) confirmed the finding against ground truth, not merely
  LLM-asserted. This operationalizes the untrusted-oracle discipline
  (`docs/STANDING_PRINCIPLES.md` §3, "A finding is a claim until grep-verified"):
  a fan-out finding is a *claim* until a mechanical oracle makes it a *result*.
  `aggregate_findings` reports the count.
- `corroboration_count` (int ≥1) — **aggregator-populated, not agent-supplied.**
  `aggregate_findings` previously *computed* duplicate multiplicity (the
  `duplicates` total) and discarded it; now each survivor (a copy — caller input
  is never mutated) carries how many independent findings collapsed to it. `>1`
  means independently corroborated, the strongest real-vs-hallucinated signal a
  fan-out produces — stronger than any single agent's `confidence`. The summary's
  `corroborated` counts survivors with `corroboration_count > 1`.

## Provenance / why only this survived

Salvaged from `task-packs/agent-thinking-helper-blueprint.md` (the "Agent
Thinking Helper"), **analyzed and dropped 2026-06-01**. The blueprint proposed
a persisted, LLM-distilled core+slices artifact to feed ultracode fan-outs.
Verdict on the rest: most of its machinery already ships under other names
(SessionStart `additionalContext` core-injection — at time of writing the
SHARP_EDGES TOC + `[recent:]` routing, RETIRED 2026-06-29 for a one-line
`/recall` pointer; TP-88/89 categorized-memory + folder routers; the
freshness staleness gate), its load-bearing cost premise ("redundant discovery
dominates a ~101-agent fan-out") was never measured (largest real fan-out on
record is 11 agents), and a persisted distilled artifact is a new instance of
the out-of-reach "semantic equivalence of doc claims" drift class
(`docs/REDEFINED_INFORMATION_REGISTRY.md` C-U03) — a parallel inventory the
harness cannot mechanically keep honest. This schema is the one separable,
zero-drift piece, so it is the only part kept.

## What now exists (made importable + consumable)

- `espalier/fan_out_findings.py` — `FINDING_SCHEMA` (SoT), `finding_schema_json()`
  + a `__main__` block (emit the schema as JSON for a JS Workflow consumer:
  `python -m espalier.fan_out_findings > /tmp/schema.json` — emit on demand, do
  NOT commit the output, the constant stays the only copy), `iter_finding_errors()`
  (light stdlib validation), `aggregate_findings()` → `FindingsSummary`
  (partitions input through `iter_finding_errors` into `valid`/`invalid` so one
  malformed return can't crash the batch; dedupes on `(location, named_unit)`,
  or `(location, claim)` when the unit is null, attaching `corroboration_count`
  to each survivor copy; counts `category`/`confidence` on the EFFECTIVE
  (corrected-when-present) value, plus `refutation_outcome`; `survival_rate`;
  `corroborated` + `externally_verified` counts; `unknown_named_units` /
  `unknown_categories`). `_dedupe_key` is module-level (hoisted in TP-185 W2) so
  the aggregator and the corpus persister share one identity definition.
- `append_findings_to_corpus(corpus_path, findings, *, section)` (TP-185 W2) —
  appends genuinely-new findings to a markdown findings file -- the round's report
  under `reports/` (the shared tracked corpus and its `DEFAULT_CORPUS_PATH`
  retired 2026-09-21), idempotently. Dedup keys on
  the **render→parse round-trip projection** (`_corpus_dedupe_key` →
  `_render_finding_bullet` → `_parse_corpus_findings` → `_dedupe_key`), so a
  re-run adds nothing even when a claim carries trailing/inner whitespace, an
  embedded newline, or a field carries a backtick — the markdown stores only
  `location` + `claim`, and keying on what survives the round-trip is what keeps
  re-append stable. Findings missing a non-empty `location`/`claim` are skipped
  (no degenerate bullets; `iter_finding_errors` permits empty strings, so the
  guard lives in the persister). Both behaviours were found by the W2 adversarial
  pass (6 confirmed, all fixed) and are pinned by negative-proof tests.
  **Footgun — both sides of the dedup must reduce through the SAME
  projection (TP-186 S1):** the round-trip is idempotent only when the
  "is this new?" test keys both sides one way. A fresh finding keys via
  `_corpus_dedupe_key` (render the full bullet → parse it back →
  `_dedupe_key`); existing corpus entries are keyed DIRECTLY via
  `_dedupe_key` because they are already `parse(written-bullet)` — never
  re-rendered. S1 broke exactly this: a claim *beginning* with a
  `[bracket]` was mis-parsed (the bracket read as a severity tag), so
  `render→parse` was not identity, the fresh key did not match the stored
  key, and every re-run **double-wrote**. Two defenses, both shipped:
  (a) make parse strict — `_CORPUS_BULLET_RE` constrains the severity
  group to the known vocab so claim content cannot masquerade as
  structure; (b) key existing entries on what is already parsed, never by
  re-rendering. Generalizes to any round-trip dedup: if `parse(render(x))`
  can differ from `x`, the dedup leaks — pin it with a
  `render → parse → key == key(x)` parity test.
- `espalier/canon_vocab.py` — `failure_mode_coinages(text)` /
  `load_failure_mode_coinages()`, the single coinage-vocab parser (also consumed
  by `tests/test_catalog_self_consistency.py`).
- Pinned by `tests/test_fan_out_findings.py` (schema parity + negative proof +
  aggregator behavior) and `tests/test_canon_vocab.py`.

**Caller status.** `aggregate_findings()` has been dogfooded on real fan-out
returns (the TP-185 W1/W2 adversarial passes). The honest measurement of whether
structured+aggregated beats prose is still the next *full* review that passes
`FINDING_SCHEMA` as the `agent()` `schema:`. `append_findings_to_corpus()` has no
*automatic* caller yet — a review persists survivors to its per-round report
by invoking it (or by hand) once they are confirmed. The reusable audit scaffold
`.claude/workflows/_fanout_audit.js` (TP-186) is the first standing caller: its
persist step invokes `append_findings_to_corpus` against the **audit** corpus
(see the dataflow section below).

## Delivering the schema to a JS Workflow (sandbox constraint)

The Workflow JS sandbox has **no filesystem, no `require`, no `child_process`** —
a `.claude/workflows/*.js` script **cannot** fetch the schema at runtime. So a JS
fan-out **must inline `FINDING_SCHEMA` as a literal**; there is no
`python -m espalier.fan_out_findings | JSON.parse` runtime path (TP-185 W1-E
corrected the roadmap's premise here — that conversion is not implementable). The
discipline is therefore *authoring-time*: when writing a new workflow, run
`python -m espalier.fan_out_findings` and paste the current output as the inline
`const FINDING_SCHEMA`. The **v1 (12-field)** literal was carried by a set of
one-shot historical scripts (the TP-169-era `_release_hardening_*`,
`_oss_sprint_review`, `_tp171_oss_readiness_review`) that captured the schema as
it was when they ran and never re-ran. Those have since been pruned from the
tracked corpus (their findings persist in docs/RELEASE_FINDINGS_LEDGER.md +
docs/known-findings.md), so every remaining `.claude/workflows/*.js` inlines the
go-forward **v2** schema and `test_contracts.TestFanoutSchemaParity` now pins an
empty `FROZEN_V1`. Python consumers (tests, future espalier modules) import the
constant directly and never inline.

**The parity gate pins `required[]` ONLY, and that is correct — do not "fix" it
(2026-08-09).** `test_contracts.TestFanoutSchemaParity::test_live_copies_track_sot`
set-compares the field NAMES in `required[]` and never compares descriptions, so
an edit to a description in the Python SoT leaves all nine JS copies untouched and
the suite green. That reads like a fail-open gate. It is not. **The descriptions
are supposed to diverge**: they are the prompt text a finder reads, tailored per
round. `id` is `TP-N:LABEL` in the SoT and `DR7:LABEL` / `R4:LABEL` / `ROUND:LABEL`
in the copies — deliberate per-round namespacing; `_fanout_audit.js` overrides
`location` to *"path:line — or the audited pack path"* on purpose; and
`minimal_repro` has **no** description in the SoT while all nine copies have one,
so the canonical side is the impoverished one. An equality gate would break the
tailoring that makes them work. `required[]` is the right thing to pin because
`additionalProperties: false` means the field *set* must match or every finding
fails validation at persist. I raised this as a defect and retracted it after
measuring all twenty properties against all nine copies — the contract was read
off the test's NAME rather than off what the copies are for. Genuine residue, a
nit and pointing the other way: `minimal_repro`, `verification` and `proposed_fix`
carry no `description` key at all in the SoT.

## The cross-pack dedup corpus (TP-185 W2; retired to the record branch 2026-09-21)

_Retired 2026-09-21: the tracked corpus moved to the record branch and
`task-packs/FORWARD_LEDGER.md` is the dedup source. What follows is the history of
how it was seeded and shaped, kept because the seeding decisions still explain the
schema._

The go-forward, **tracked** dedup corpus a review reads before raising (so the
same defect is not re-found across packs) and appends survivors to. `SURVIVED` =
do-not-re-raise; `REFUTED` = do-not-reopen without new evidence. Seeded by
migrating the TP-169 known-findings list **verbatim** (104 bullets = 71 + 33);
legacy `location:line`/`Nk` ids stay valid (the schema id pattern is permissive),
`TP-<n>:LABEL` is the convention going forward.

It is **internal historical narrative** (TP vocab, dead hashes, point-in-time
counts), so it carries the sister-site footprint every such doc needs (see
SHARP_EDGES "A tracked internal doc needs a sister-site footprint — and part of
it is conditional"): `surface_contract._INTERNAL_FILENAME_PATTERNS`, `MANIFEST.in`
exclude, `.gitattributes` export-ignore, `claim_extractor.EXCLUDED_DOC_GLOBS`,
`test_git_archive_parity.EXPORT_IGNORED_INTERNAL_DOCS`. Miss one and it either
ships to adopters or false-positives `audit_accuracy`; the parity tests catch it.
Read the footprint from SHARP_EDGES rather than this list — it grew three
conditional sites in 2026-08 and the `claim_extractor` entry turned out **not**
to be unconditional (a live procedure stays audited; only a record is excluded).

The `_release_hardening_conv2/conv3` + `_tp171` workflows' dedup-source
references had been repointed from the old gitignored `task-packs/TP-169-known-findings.md`
to this tracked path (faithful — the content was migrated verbatim). Those
workflows have since been pruned from the tracked corpus; the migration is noted
here because it explains how `known-findings.md` was seeded, not because the
scripts still exist.

## Fan-out dataflow: the two-hop anti-bloat return contract (TP-186)

The incident that motivated this: an archive-readiness audit hand-rolled a
bespoke per-pack schema, never aggregated, never persisted, and dumped 36 verbose
rationales (~817 lines / ~1.77M tokens) straight into the main window — the same
finding shape regenerated N times. Everything needed to avoid that already lived
in `fan_out_findings.py`; TP-186 makes reaching for it the **default** via one
reusable scaffold, **not** a schema change (zero change to `FINDING_SCHEMA`).

**The two-hop dataflow** (`.claude/workflows/_fanout_audit.js`):

1. **Finders/refuters return `FINDING_SCHEMA` objects to the workflow runtime** —
   never to the orchestrator chat. (The JS inlines the schema literal, per the
   sandbox constraint above; persist-time `aggregate_findings` validates each
   finding against the *real* Python schema, so a drifted inline copy shows up as
   `invalid > 0` in the summary — a soft parity rail.)
2. **An in-workflow persist step runs the Python the JS sandbox cannot** (no fs,
   no Python in `.js`): a final `agent()` writes the findings verbatim and runs
   `python3 -c "from espalier.fan_out_findings import aggregate_findings,
   append_findings_to_corpus; …"`. Operator decision D2 = persist **inside** the
   workflow (self-contained), not an orchestrator post-step.
3. **The main window reads ONLY** the `FindingsSummary` scalars, a survivors-slim
   list (`id`/`title`/`severity`/`location`/`category`), and the corpus path —
   **never** `minimal_repro`, `refutation_reason`, refuted rows, or clean/LANDED
   rows. Drill down by grepping the corpus or re-running the oracle for one
   target (O(1)); never re-ingest the batch.

**The audit corpus is `reports/audit-findings.md` — separate from, and shaped
differently than, the review-dedup corpus of the time** (operator decision D1;
that corpus retired 2026-09-21):

- the review-dedup corpus = the cross-pack **review-dedup** corpus, **tracked**
  (seeded verbatim from TP-169), so it carries the internal-doc sister-site
  footprint above.
- `reports/audit-findings.md` = the **audit** corpus, **gitignored** (`reports/`
  is already a `surface_contract` local-only prefix). It is deliberately *not*
  tracked: audit rows are more ephemeral than regression findings, and a gitignored
  file needs **no** sister-site footprint (it never ships, never trips
  `audit_accuracy` or export-parity). `append_findings_to_corpus` takes an
  explicit `corpus_path`, so the same idempotent persister serves both.

**`_fanout_audit.js` is fusion-excluded** (`fusion_manifest.HARNESS_EXCLUDE`,
pinned exhaustively by `test_fuse.py::test_no_workflow_oneshots_overlay`): like
every `.claude/workflows/*.js`, the scaffold audits espalier's own tree and does
not ship into an adopter's fusion — the **engine** ships (`fan_out_findings.py`)
and the operator authors host-specific workflows from it. The shipped `/adversarial`
skill documents the return *contract* generically (engine-only references), with
the espalier-internal scaffold path kept here.

Run it with no args for the task-packs landing audit (the earn-the-red), or pass
`{ finders, targets, knownCategories, corpusPath, refute }` for a different
fan-out.
