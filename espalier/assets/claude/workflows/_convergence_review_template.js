export const meta = {
  name: 'convergence-review-template',
  description: 'Scope-breaker-complete convergence-review scaffold. The successor to _fanout_audit.js: the same finders -> refute -> persist two-hop bridge, PLUS the four mandatory scope-breakers (penumbra / actionable-critic / corpus-blind / delta-attacker) and a terminal convergence-critic that appends a cross-round row to memory/CONVERGENCE_LEDGER.md. Copy this file, rename it, and swap DIMENSIONS for your lens. See memory/convergence-review-protocol.md "Scope-breakers (mandatory floor)".',
  phases: [
    { title: 'Find' },
    { title: 'Penumbra' },
    { title: 'Refute' },
    { title: 'Actionable-critic' },
    { title: 'Delta-attacker' },
    { title: 'Persist' },
    { title: 'Convergence-critic' },
  ],
}

// ---------------------------------------------------------------------------
// Make scope-breakers a STANDING FLOOR of every convergence review.
//
// Iterated scoped review converges to silence BY CONSTRUCTION: each round scopes
// off the prior round, so the blind spot is the intersection of every lens's
// exclusions, and the dedup corpus inherits prior framing. This scaffold bakes in
// the four scope-breakers so a copy cannot silently forget them, and closes the
// loop with a convergence-critic that gives the review cross-round sight.
//
//   Find (scoped lanes + a CORPUS-BLIND lane in parallel)   [scope-breaker 3]
//     -> Penumbra (ring just outside each finding's lens)    [scope-breaker 1]
//     -> Refute (default-refuted, oracle-confirmed vs HEAD)
//     -> Actionable-critic (the critic's gaps become a 2nd finder wave, same run)
//                                                            [scope-breaker 2]
//     -> Delta-attacker (git diff -> sister-sites the change did NOT update)
//                                                            [scope-breaker 4]
//     -> Persist (append_findings_to_corpus + append_summary; two-hop bridge)
//     -> Convergence-critic (read ledger + cc/finding_ledger.jsonl, emit verdict,
//        APPEND one row to memory/CONVERGENCE_LEDGER.md)     [terminal stage]
//
// Parametric via `args` (every key optional):
//   { finders:     [{ id, category, title, body, agentType? }],  // swap the lens
//     lens:        "one-line description of this round",
//     baseRef:     "c8d7175",           // delta-attacker git range base (default HEAD~1)
//     corpusPath:  "reports/<round>-findings.md",
//     ledgerPath:  "memory/CONVERGENCE_LEDGER.md",  // scratch path for a smoke/test run
//     knownCategories: [...],
//     refute:      true,
//     model:       "sonnet",          // applied to EVERY agent call (default: inherit the session model)
//     smoke:       true }              // bound the open-ended lanes so a smoke run stays under ten agents
// With `smoke: true` every stage still fires and logs its phase while the open-ended
// lanes return empty, so the scaffold is safe to smoke-run end-to-end for under ten
// agents. Without it a no-args run is a real review of the host repository: the
// corpus-blind lane, the critic's second wave and the delta-attacker are unbounded.
//
// SCHEMA NOTE: FINDING_SCHEMA lives in espalier/fan_out_findings.py (the SoT). The
// JS sandbox cannot import it, so the shape below is an inlined copy pinned to the
// SoT by tests/test_contracts.py::TestFanoutSchemaParity (this file is in LIVE_V2).
// Drift is caught at PERSIST: aggregate_findings validates every finding and reports
// `invalid` > 0 in the summary. Do not hand-edit the schema fields.
// ---------------------------------------------------------------------------

// `args` NORMALIZATION — some hosts forward the Workflow `args` value to the script
// global as a JSON-ENCODED STRING rather than a parsed object; reading `args.finders`
// off a string silently yields undefined, so a real round smoke-defaults (observed
// 2026-07-17: a 30-lane round ran the smoke lens because the finders array never bound).
// Accept BOTH shapes. No-args still yields {} -> the smoke defaults below, so the scaffold
// stays SAFE TO SMOKE-RUN end-to-end (deliberately NO fail-fast here — a dated COPY that
// requires a real lens adds its own guard; the template itself must run on a trivial lens).
let A = {}
if (typeof args === 'string') { try { A = args.trim() ? JSON.parse(args) : {} } catch (e) { A = {} } }
else if (args && typeof args === 'object') { A = args }
const CORPUS_PATH = A.corpusPath || 'reports/convergence-review-findings.md'
const LEDGER_PATH = A.ledgerPath || 'memory/CONVERGENCE_LEDGER.md'
const INPUT_PATH = 'reports/.convergence_review_input.json' // gitignored scratch (reports/)
const BASE_REF = A.baseRef || 'HEAD~1' // delta-attacker git-diff base
const LENS = A.lens || 'trivial-lens smoke (swap DIMENSIONS for a real round)'
const REFUTE = A.refute !== false
const KNOWN_CATEGORIES = A.knownCategories || null
// One model for the whole run. Workflow agents inherit the session model unless each
// call overrides it; `args.model` is that override, routed through `opts()` at EVERY
// agent() call so a run never silently inherits a model the operator did not choose.
const MODEL = (typeof A.model === 'string' && A.model.trim()) ? A.model.trim() : null
const opts = (o) => (MODEL ? { ...o, model: MODEL } : o)
// `args.smoke`: the default lens is trivial, but the corpus-blind lane, the critic's
// second wave and the delta-attacker are open-ended by design, so a "smoke" run of the
// scaffold was a real review of the host repository. Under smoke each open-ended lane
// is told to run one cheap oracle and return empty, so the stage graph is exercised
// end-to-end for under ten agents.
const SMOKE = A.smoke === true
const SMOKE_CLAUSE = SMOKE
  ? `\n\nSMOKE RUN: this run exercises the stage graph only. Run ONE cheap oracle (for example, confirm README.md exists), then return an EMPTY findings array.`
  : ''
// Fields the refute stage and the aggregator accrete; a FINDER must not pre-populate
// them. aggregate_findings' _eff_category honours a present corrected_category over the
// original even when it is null, so a finder echoing the schema's optional keys sinks
// its finding into the null bucket (16 of 38 records in one round), and a finder-set
// externally_verified would survive a refute-off run as a verified claim nobody made.
// The three scaffolds carry this helper with one field set; keep them identical.
const stripRefuterFields = (x) => {
  const { corrected_category, corrected_confidence, externally_verified, ...rest } = x
  return rest
}

// --- Inlined FINDING_SCHEMA v2 (SoT: espalier/fan_out_findings.py::FINDING_SCHEMA).
// Verbatim copy of the LIVE_V2 shape; pinned by TestFanoutSchemaParity. -----------
const FINDING = {
  type: 'object',
  additionalProperties: false,
  required: [
    'id', 'title', 'rule_or_scanner', 'violated_invariant', 'category',
    'location', 'claim', 'minimal_repro', 'verification', 'confidence',
    'proposed_fix', 'severity', 'blocks_release',
  ],
  properties: {
    id: { type: 'string', description: 'stable handle; namespace as ROUND:LABEL' },
    title: { type: 'string', description: '<=8-word triage label, distinct from claim' },
    rule_or_scanner: { type: 'string', description: 'the lens / agent / oracle that surfaced this' },
    violated_invariant: { type: 'string', description: 'the rule or contract this finding breaks' },
    category: { type: ['string', 'null'], description: 'domain-supplied bucket (validated via knownCategories) or null' },
    location: { type: 'string', description: 'path:line' },
    claim: { type: 'string', description: 'one sentence' },
    minimal_repro: { type: 'string', description: 'the command / steps that show it (keep terse)' },
    verification: {
      type: 'object', additionalProperties: false, required: ['positive', 'negative'],
      properties: {
        positive: { type: 'string', description: 'catches the bad' },
        negative: { type: 'string', description: 'clears the good' },
      },
    },
    confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    proposed_fix: { type: 'string' },
    severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'nit'] },
    blocks_release: { type: 'boolean' },
    // OPTIONAL — accreted downstream by the refuter/aggregator; absent at finder time.
    named_unit: { type: ['string', 'null'] },
    refutation_outcome: { type: 'string', enum: ['unattempted', 'survived', 'refuted'] },
    refutation_reason: { type: 'string' },
    corrected_confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    corrected_category: { type: ['string', 'null'] },
    externally_verified: { type: 'boolean' },
    corroboration_count: { type: 'integer', minimum: 1 },
  },
}

const FINDINGS = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: FINDING } },
}

const REFUTE_RESULT = {
  type: 'object', additionalProperties: false,
  required: ['refutation_outcome', 'refutation_reason', 'externally_verified'],
  properties: {
    refutation_outcome: { type: 'string', enum: ['survived', 'refuted'] },
    refutation_reason: { type: 'string', description: 'why it survived or was refuted, citing the bytes read' },
    externally_verified: { type: 'boolean', description: 'true ONLY on an oracle-confirmed survivor' },
    corrected_confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    // ONLY FINDING_SCHEMA fields here — verdict is merged {...f, ...v} into an
    // additionalProperties:false schema; a non-schema key invalidates every finding.
    blocks_release: { type: 'boolean', description: 're-judged through the governing frame' },
  },
}

// --- Shared preamble: the governing frame + the review discipline ----------------
const FRAME =
  `GOVERNING FRAME — read every finding through the threat model this repository declares. The\n` +
  `harness that ships this scaffold is a WORKFLOW + coding TOOLBELT, and NOT a security\n` +
  `boundary. The threat model is operator/AI *mistakes*, not malice. A false-positive denial,\n` +
  `a confusing error, install friction, or a crash on a fresh adopter's first run is a HIGHER-\n` +
  `severity finding than an un-closed crafted-malice bypass. Do NOT report adversarial bypasses.\n` +
  `blocks_release=true ONLY for what takes a fresh adopter OUT of a top-tier OSS release.\n\n`

const DISCIPLINE =
  `DISCIPLINE (non-negotiable):\n` +
  `1. DEDUP: before emitting, grep task-packs/FORWARD_LEDGER.md for the file + symbol (if that file is\n` +
  `   absent, as on an adopter tree that keeps no ledger, write ABSENT-LEDGER in verification.negative and\n` +
  `   mark the finding UN-DEDUPED, not new: absence is not clearance). If the finding\n` +
  `   or its CLASS is a live row or a section-6 do-not-rediscover entry, DROP it: a re-find is un-deduped, not new.\n` +
  `2. EARN-THE-RED: a citation is a CLAIM until an oracle confirms it. RUN something — grep, git,\n` +
  `   python -m espalier <cmd>, python -c '<exec the path>', parse the file — and quote the\n` +
  `   exact bytes (path:line) in minimal_repro. NEVER report from memory or one rendered frame.\n` +
  `3. CLASSIFICATION GUARD — deferred-intentional != abandoned: before flagging a half-finished /\n` +
  `   abandoned / supplanted item, cross-reference task-packs/FORWARD_LEDGER.md, if the repository keeps one (DEF-* / drafted-\n` +
  `   pack entries) + in-code dormant notes. A documented deferral is a KEEP, not rot.\n` +
  `4. A clean area yields an EMPTY findings array. Finding NOTHING NEW is the correctness signal,\n` +
  `   not a failure. Do NOT manufacture findings.\n\n`

function finderPrompt(d) {
  return FRAME + DISCIPLINE +
    `YOUR DIMENSION: ${d.title}\n\ncwd = the repository root.\n\n${d.body}\n\n` +
    `Return {findings: [ ...FINDING_SCHEMA objects... ]} (empty array if the area is clean).`
}

function refutePrompt(f) {
  return FRAME +
    `REFUTE this convergence finding. DEFAULT = refuted. cwd = repo root.\n` +
    `It SURVIVES only if you reproduce it against HEAD with an ORACLE (re-read the cited\n` +
    `location; run the minimal_repro or an equivalent grep / git / python -m espalier /\n` +
    `python -c exec / file-parse). If it does not reproduce, is already a live row or a\n` +
    `section-6 do-not-rediscover entry in task-packs/FORWARD_LEDGER.md (grep it, if the repository keeps one) -> refuted.\n` +
    `RE-JUDGE blocks_release through the FRAME. Set externally_verified=true ONLY on an oracle-\n` +
    `confirmed survivor. Quote the bytes you read.\n\n` +
    `FINDING:\n${JSON.stringify(f, null, 2)}\n\n` +
    `Return {refutation_outcome, refutation_reason (cite bytes), externally_verified,\n` +
    `optionally corrected_confidence / blocks_release}.`
}

// --- The finder dimensions (SWAP THESE for your round) ---------------------------
// The default is a tiny smoke lens so the scaffold runs end-to-end out of the box.
const DIMENSIONS = A.finders || [
  { id: 'SMOKE', category: 'completeness', agentType: 'general-purpose',
    title: 'trivial-lens smoke — confirm the scaffold wiring',
    body:
      `This is the DEFAULT smoke lens (no real round configured). Do a single cheap oracle check:\n` +
      `confirm memory/convergence-review-protocol.md exists and names the four scope-breakers\n` +
      `(grep -c "scope-breaker" or the section header). Emit an EMPTY findings array unless that\n` +
      `grep returns zero (which WOULD be a real finding). This lens exists only to exercise the\n` +
      `stage graph; a real review replaces DIMENSIONS via args.finders.` },
]

// =============================================================================
// Phase 1 — FIND: the scoped lanes, PLUS a SCOPE-BREAKER 3 (CORPUS-BLIND) lane
// running IN PARALLEL — no scope, no corpus, no known-list, allowed to re-find
// "known-good" things (the temporal blind-spot breaker).
// =============================================================================
phase('Find')
log(`convergence-review: lens="${LENS}"; ${DIMENSIONS.length} scoped dim(s) + 1 corpus-blind; corpus=${CORPUS_PATH}; model=${MODEL || 'inherited'}; smoke=${SMOKE}`)

const scopedThunks = DIMENSIONS.map(d => () =>
  agent(finderPrompt(d), opts({
    label: `find:${d.id}`, phase: 'Find', schema: FINDINGS,
    ...(d.agentType ? { agentType: d.agentType } : {}),
  }))
    .then(r => ((r && r.findings) || []).map(x => ({ ...stripRefuterFields(x), rule_or_scanner: d.id, _lane: d.id, category: x.category || d.category })))
    .catch(() => [])
)

// SCOPE-BREAKER 3 — CORPUS-BLIND parallel deep-dive.
const corpusBlindThunk = () =>
  agent(
    FRAME +
    `You are the CORPUS-BLIND lane. Do NOT read the repository's forward ledger (task-packs/FORWARD_LEDGER.md where one exists) and do NOT assume any\n` +
    `prior round caught anything. cwd = repo root. Re-examine the codebase with fresh eyes — you\n` +
    `are explicitly ALLOWED to re-find "known-good" things, because the whole point is to catch\n` +
    `a broadly-visible problem that every scoped lens assumed was handled earlier. Still EARN-THE-\n` +
    `RED with an oracle and still honor the classification guard (a documented deferral is a KEEP).\n` +
    `Emit an EMPTY array if genuinely nothing.\n\n` +
    `Return {findings: [ ...FINDING_SCHEMA objects... ]}.` + SMOKE_CLAUSE,
    opts({ label: 'find:corpus-blind', phase: 'Find', schema: FINDINGS }),
  )
    .then(r => ((r && r.findings) || []).map(x => ({ ...stripRefuterFields(x), rule_or_scanner: 'corpus-blind', _lane: 'corpus-blind', category: x.category || 'completeness' })))
    .catch(() => [])

const finderResults = await parallel([...scopedThunks, corpusBlindThunk])
let found = finderResults.filter(Boolean).flat()

// CROSS-LANE COLLAPSE — key on NORMALIZED CLAIM TEXT, never on `id`.
// Lanes run in parallel from one starting point, so three of them finding the
// same defect emit three records. Keying on `id` does not collapse them: ids are
// lane-local, and a harness whose schema example is a copyable literal gets that
// literal echoed back by several lanes at once — which then cross-wires records,
// so a refuter receives a title from one finding and a claim from another.
// (Measured, 2026-07-31, from the opposite direction: retro-filling the corpus
// from a past round's report collapsed 5 findings that had been emitted 3-4x each,
// all carrying placeholder lane ids rather than real locations.)
//
// CORROBORATION IS PRESERVED, and that is the point of merging rather than
// dropping: independent lanes converging on one defect is EVIDENCE. Collapsing to
// a bare first-wins record would silently destroy the strongest signal the fan-out
// produces, which is a worse bug than the double-count it fixes.
const _claimKey = (f) =>
  String((f && f.claim) || '').toLowerCase().replace(/\s+/g, ' ').replace(/[`"'*_]/g, '').trim()
const _byClaim = new Map()
for (const f of found) {
  const k = _claimKey(f)
  if (!k) { _byClaim.set(`__empty:${_byClaim.size}`, { ...f, _lanes: [f._lane] }); continue }
  const prior = _byClaim.get(k)
  if (prior) prior._lanes.push(f._lane)
  else _byClaim.set(k, { ...f, _lanes: [f._lane] })
}
const _rawCount = found.length
found = [..._byClaim.values()]
const _corroborated = found.filter(f => f._lanes.length > 1)
if (_rawCount !== found.length) {
  log(`convergence-review: collapsed ${_rawCount} -> ${found.length} on normalized claim; ` +
      `${_corroborated.length} corroborated by 2+ lanes ` +
      `(${_corroborated.map(f => `${f._lanes.length}x`).join(' ') || '-'})`)
}

log(`convergence-review: ${found.length} candidate(s) from ${DIMENSIONS.length} scoped + corpus-blind`)

// =============================================================================
// Phase 2 — SCOPE-BREAKER 1 — PENUMBRA: after finders, hunt the ring JUST OUTSIDE
// each finding's lens — per-finding sister-sites / callers the finder did not walk.
// =============================================================================
phase('Penumbra')
const penumbra = await parallel(found.map((f, i) => () =>
  agent(
    FRAME +
    `You are the PENUMBRA lane for one finding. cwd = repo root. Given the finding below, hunt the\n` +
    `RING JUST OUTSIDE its lens: the sister-sites, callers, and parity-locked twins the original\n` +
    `finder did NOT walk (grep the fixed pattern / symbol repo-wide — the finder's site count is a\n` +
    `FLOOR). Emit a NEW FINDING_SCHEMA object ONLY for a genuine un-covered sibling, oracle-\n` +
    `confirmed; empty array if the penumbra is clean. Honor the classification guard.\n\n` +
    `SEED FINDING:\n${JSON.stringify(f, null, 2)}\n\n` +
    `Return {findings: [...]}.`,
    opts({ label: `penumbra:${f._lane || 'x'}#${i}`, phase: 'Penumbra', schema: FINDINGS }),
  )
    .then(r => ((r && r.findings) || []).map(x => ({ ...stripRefuterFields(x), rule_or_scanner: `penumbra:${f._lane}`, _lane: `penumbra:${f._lane}` })))
    .catch(() => [])
))
found = found.concat(penumbra.filter(Boolean).flat())
log(`convergence-review: ${found.length} candidate(s) after penumbra`)

// =============================================================================
// Phase 3 — REFUTE: adversarially verify each candidate (default-refuted).
// =============================================================================
phase('Refute')
let findings = found
if (REFUTE && found.length) {
  findings = await parallel(found.map((f, i) => () =>
    agent(refutePrompt(f), opts({ label: `refute:${f._lane || 'x'}#${i}`, phase: 'Refute', schema: REFUTE_RESULT }))
      .then(v => ({ ...f, ...(v || {}) }))
      .catch(() => ({ ...f, refutation_outcome: 'unattempted', refutation_reason: 'refuter errored' }))
  ))
}

// =============================================================================
// Phase 4 — SCOPE-BREAKER 2 — ACTIONABLE-CRITIC: a completeness critic maps what
// the lanes did NOT cover, and its named gaps become a SECOND finder wave in the
// SAME run (not just a report). Second-wave findings refute inline.
// =============================================================================
phase('Actionable-critic')
const GAPS = {
  type: 'object', additionalProperties: false, required: ['gaps'],
  properties: { gaps: { type: 'array', items: {
    type: 'object', additionalProperties: false, required: ['surface', 'why', 'oracle'],
    properties: {
      surface: { type: 'string', description: 'the uncovered surface / lens' },
      why: { type: 'string', description: 'why it matters for this review' },
      oracle: { type: 'string', description: 'the concrete oracle a finder should run on it' },
    },
  } } },
}
const critic = await agent(
  FRAME +
  `You are the COMPLETENESS CRITIC. cwd = repo root. Do NOT re-find the lanes above. Instead map\n` +
  `what they did NOT cover for lens "${LENS}": name each uncovered surface, WHY it matters, and\n` +
  `the concrete ORACLE a follow-up finder should run. Return up to 5 highest-value gaps (fewer is\n` +
  `fine; empty if the coverage is genuinely complete).\n\n` +
  `Return {gaps: [{surface, why, oracle}, ...]}.` +
  (SMOKE ? `\n\nSMOKE RUN: name at most ONE gap, with a cheap oracle.` : ''),
  opts({ label: 'actionable-critic', phase: 'Actionable-critic', schema: GAPS }),
).catch(() => ({ gaps: [] }))

const gaps = (critic && critic.gaps) || []
log(`convergence-review: actionable-critic named ${gaps.length} gap(s) -> second finder wave`)
if (gaps.length) {
  const secondWave = await parallel(gaps.map((g, i) => () =>
    agent(
      finderPrompt({ title: `gap: ${g.surface}`, body: `${g.why}\n\nRun this oracle: ${g.oracle}` + SMOKE_CLAUSE }),
      opts({ label: `find2:${i}`, phase: 'Actionable-critic', schema: FINDINGS }),
    )
      .then(r => ((r && r.findings) || []).map(x => ({ ...stripRefuterFields(x), rule_or_scanner: `gap:${i}`, _lane: `gap:${i}`, category: x.category || 'completeness' })))
      .catch(() => [])
  ))
  const wave2 = secondWave.filter(Boolean).flat()
  const wave2Refuted = (REFUTE && wave2.length)
    ? await parallel(wave2.map((f, i) => () =>
        agent(refutePrompt(f), opts({ label: `refute2:${i}`, phase: 'Actionable-critic', schema: REFUTE_RESULT }))
          .then(v => ({ ...f, ...(v || {}) }))
          .catch(() => ({ ...f, refutation_outcome: 'unattempted', refutation_reason: 'refuter errored' }))))
    : wave2
  findings = findings.concat(wave2Refuted)
}

// =============================================================================
// Phase 5 — SCOPE-BREAKER 4 — DELTA-ATTACKER: derive the ripple from the DIFF, not
// from operator prediction. From git diff BASE_REF..HEAD, hunt sister-sites /
// contracts / docs the change TOUCHED but did NOT update (class-fix-scope as a stage).
// =============================================================================
phase('Delta-attacker')
const deltaRaw = await agent(
  FRAME +
  `You are the DELTA-ATTACKER lane. cwd = repo root. A static HEAD snapshot cannot see a\n` +
  `supplanted-twin-still-wired; you derive the ripple from the DIFF. Run:\n` +
  `  git diff ${BASE_REF}..HEAD --stat   then   git diff ${BASE_REF}..HEAD -- <path>\n` +
  `For every symbol / contract / doc the diff TOUCHED, ask: is there a SISTER-SITE, a parity-\n` +
  `locked twin, a contract, or a doc that references it and was NOT updated in the same diff?\n` +
  `(grep the changed symbol repo-wide; the diff's own site count is a FLOOR.) Emit a FINDING_\n` +
  `SCHEMA object for each un-updated sister, oracle-confirmed (quote the stale line). Honor the\n` +
  `classification guard. Empty array if the diff has no un-updated ripple (or there is no diff).\n\n` +
  `Return {findings: [...]}.` + SMOKE_CLAUSE,
  opts({ label: 'delta-attacker', phase: 'Delta-attacker', schema: FINDINGS }),
).catch(() => ({ findings: [] }))
const deltaFound = ((deltaRaw && deltaRaw.findings) || []).map(x => ({ ...stripRefuterFields(x), rule_or_scanner: 'delta-attacker', _lane: 'delta-attacker', category: x.category || 'completeness' }))
const deltaRefuted = (REFUTE && deltaFound.length)
  ? await parallel(deltaFound.map((f, i) => () =>
      agent(refutePrompt(f), opts({ label: `refute-delta:${i}`, phase: 'Delta-attacker', schema: REFUTE_RESULT }))
        .then(v => ({ ...f, ...(v || {}) }))
        .catch(() => ({ ...f, refutation_outcome: 'unattempted', refutation_reason: 'refuter errored' }))))
  : deltaFound
findings = findings.concat(deltaRefuted)

// Strip the internal _lane AND _lanes tags before the schema-validated persist
// (additionalProperties:false marks either one invalid). `_lanes` is stamped by
// the corroboration merge above; omitting it here invalidated 69 of one round's
// 181 records at the LEDGER hop — total=181 valid=112 invalid=69 — while the
// corpus persisted fine, so nothing surfaced it and the critic's own
// "computed, not recalled" premise silently became false.
//
// NOT A NAMED LIST, DELIBERATELY. FINDING_SCHEMA is additionalProperties:false and
// declares no underscore-prefixed property, so "drop what starts with _" IS the
// schema boundary rather than an approximation of it. The hand-named form was
// wrong twice: once naming only `_lane` while the corroboration merge stamped
// `_lanes`, and again as a two-name list that a third tag would slip past. A
// generic filter cannot go stale as new private tags are added.
// Pinned by tests/test_finding_ledger.py::test_runnable_persisters_strip_every_private_lane_key.
findings = findings.map(f =>
  Object.fromEntries(Object.entries(f).filter(([k]) => !k.startsWith('_'))))
const survivorCount = findings.filter(f => f.refutation_outcome !== 'refuted').length
log(`convergence-review: ${survivorCount} survivor(s) of ${findings.length} after all lanes`)

// =============================================================================
// Phase 6 — PERSIST (two-hop bridge; the JS sandbox has no Python/FS). Calls BOTH
// append_findings_to_corpus (the per-round report) AND finding_ledger.append_summary (the
// per-run structured ledger the convergence-critic reads) — this is a STANDING
// persister (tests/test_finding_ledger.py::TestStandingCallerLedgerWiring).
// =============================================================================
phase('Persist')
const persistPayload = JSON.stringify({
  findings, known_categories: KNOWN_CATEGORIES, corpus_path: CORPUS_PATH,
})
// ONE DESTINATION plus the summary ledger. The per-round report (CORPUS_PATH, under
// reports/) is this round's record, immutable and cited by the convergence ledger;
// finding_ledger.append_summary writes the per-run structured row the convergence-critic
// reads. The shared cross-round dedup corpus was retired 2026-09-21: a survivor reaches
// task-packs/FORWARD_LEDGER.md only through a verify pass that files a row, a section-6
// do-not-rediscover entry, or nothing -- never by append.
const persistCmd =
  `PY=python3; command -v "$PY" >/dev/null 2>&1 || PY=python\n` +
  `"$PY" -c '\n` +
  `import json, sys, warnings\n` +
  `from espalier.fan_out_findings import aggregate_findings, append_findings_to_corpus\n` +
  `from espalier.finding_ledger import append_summary\n` +
  `data = json.load(open("${INPUT_PATH}"))\n` +
  `findings = data["findings"]\n` +
  `corpus = data["corpus_path"]\n` +
  `summ = aggregate_findings(findings, known_categories=data.get("known_categories"))\n` +
  `survivors = [f for f in findings if f.get("refutation_outcome") != "refuted"]\n` +
  `with warnings.catch_warnings(record=True) as _w:\n` +
  `    warnings.simplefilter("always")\n` +
  `    appended = append_findings_to_corpus(corpus, survivors)\n` +
  `    ledger = append_summary(summ, root=".")\n` +
  `for _x in _w:\n` +
  `    print("WARNING: " + str(_x.message), file=sys.stderr)\n` +
  `print(json.dumps({\n` +
  `  "total": summ.total, "valid": summ.valid, "invalid": summ.invalid,\n` +
  `  "unique": summ.unique, "duplicates": summ.duplicates,\n` +
  `  "corroborated": summ.corroborated, "externally_verified": summ.externally_verified,\n` +
  `  "survival_rate": summ.survival_rate, "by_category": summ.by_category,\n` +
  `  "by_refutation_outcome": summ.by_refutation_outcome,\n` +
  `  "unknown_categories": summ.unknown_categories,\n` +
  `  "appended": appended,\n` +
  `  "warnings": [str(_x.message) for _x in _w],\n` +
  `  "ledger": ledger, "corpus_path": corpus,\n` +
  `  "survivors_slim": [{"id": f.get("id"), "title": f.get("title"),\n` +
  `    "severity": f.get("severity"), "location": f.get("location"),\n` +
  `    "category": f.get("category"), "blocks_release": bool(f.get("blocks_release")),\n` +
  `    "externally_verified": bool(f.get("externally_verified"))}\n` +
  `    for f in survivors],\n` +
  `}))\n` +
  `'`
const persistPrompt =
  `Persist the convergence-review findings and return the compact summary. cwd = repo root.\n\n` +
  `STEP 1 — Use the Write tool to write the JSON below VERBATIM (do not edit / summarize / re-key\n` +
  `it) to the file:  ${INPUT_PATH}\n\n<<<FINDINGS_JSON\n${persistPayload}\nFINDINGS_JSON\n\n` +
  `STEP 2 — Run this command EXACTLY as written:\n\n${persistCmd}\n\n` +
  `STEP 3 — Return the JSON object the command printed on stdout. If json.load raised (the file\n` +
  `was corrupted on write), say so plainly — do not fabricate a summary.`

const persistResult = await agent(persistPrompt, opts({
  label: 'persist:corpus', phase: 'Persist',
  schema: {
    type: 'object', additionalProperties: true,
    required: ['total', 'appended', 'corpus_path', 'survivors_slim'],
    properties: {
      total: { type: 'integer' }, valid: { type: 'integer' }, invalid: { type: 'integer' },
      unique: { type: 'integer' }, corroborated: { type: 'integer' },
      externally_verified: { type: 'integer' },
      survival_rate: { type: ['number', 'null'] },
      by_category: { type: 'object', additionalProperties: true },
      by_refutation_outcome: { type: 'object', additionalProperties: true },
      unknown_categories: { type: 'array', items: { type: 'string' } },
      appended: { type: 'integer' },
      warnings: { type: 'array', items: { type: 'string' } },
      ledger: { type: 'integer' }, corpus_path: { type: 'string' },
      survivors_slim: { type: 'array', items: { type: 'object', additionalProperties: true } },
    },
  },
})).catch(() => ({ total: findings.length, appended: 0, persist_error: 'persist agent errored (fail-open)', corpus_path: CORPUS_PATH, survivors_slim: [] }))

// =============================================================================
// Phase 7 — CONVERGENCE-CRITIC (terminal, mandatory). Stateless: reads the durable
// convergence ledger (prior rows) + the structured per-run ledger cc/finding_ledger.jsonl
// (via espalier.finding_ledger.read_ledger — so yield/recurrence are COMPUTED, not
// recalled) + this round's summary; computes the cross-round view; and APPENDS one
// new row to LEDGER_PATH (append-only — never rewrites a prior row). See
// memory/convergence-review-protocol.md "The convergence-critic".
// =============================================================================
phase('Convergence-critic')
const roundSummary = JSON.stringify({
  lens: LENS, corpus_path: persistResult.corpus_path,
  by_refutation_outcome: persistResult.by_refutation_outcome,
  by_category: persistResult.by_category,
  survivors_slim: persistResult.survivors_slim,
})
const criticVerdict = await agent(
  FRAME +
  `You are the CONVERGENCE-CRITIC — the terminal stage. cwd = repo root. Your job is CROSS-ROUND\n` +
  `sight, then APPEND one row to the ledger. Do NOT rewrite any existing row.\n\n` +
  `STEP 1 — Read the durable ledger's prior rows:  the file ${LEDGER_PATH}  (use Read).\n` +
  `  READ EACH ROW WHOLE. A row may end with a "⚠ CORRECTED <date>" bullet that supersedes the\n` +
  `  fields above it; the superseded text is left standing on purpose. Never quote a field from a\n` +
  `  corrected row without reading the correction — one prior row's per-lane yield reads "down 35%"\n` +
  `  and its correction reads "up ~44%". A "file:NN" in a row is a PRE-FIX line number.\n` +
  `STEP 2 — Read the structured per-run substrate (yield/recurrence are computed, not recalled):\n` +
  `  python -c 'import json; from espalier.finding_ledger import read_ledger; print(json.dumps(read_ledger()[-6:]))'\n` +
  `STEP 3 — Compute, using STEP 1 + STEP 2 + THIS ROUND (below): (a) yield trend vs prior rows;\n` +
  `  (b) refutation-recurrences (a finding refuted 2+ times); (c) confirmed-after-refuted; (d) cross-\n` +
  `  round classes (N isolated same-shape nits); (e) the cumulative never-covered coverage map;\n` +
  `  (f) scope-narrowing. GATE the word "converged": permit it ONLY if a corpus-blind pass produced\n` +
  `  the null AND the coverage map has no high-value never-covered surface; otherwise the verdict\n` +
  `  is "coverage-null, not convergence-null".\n` +
  `STEP 4 — Compose ONE new row matching the ledger's "## Row schema" (### Round <N> — <date> — ...),\n` +
  `  where <N> = (highest prior round number) + 1. Use today's date if visible in STEP 1/2 timestamps,\n` +
  `  else leave the date as "unrecorded". APPEND it to the END of ${LEDGER_PATH} using Edit (do not\n` +
  `  touch any prior line). Confirm the append by re-reading the file tail.\n` +
  `  Cite code in the house form path::symbol (:NN) — a bare path:NN is a pre-fix line number\n` +
  `  that rots, and tests/test_catalog_self_consistency.py reds on it.\n\n` +
  `THIS ROUND:\n${roundSummary}\n\n` +
  `Return {round_appended: bool, new_round_number: int, convergence_read: string,\n` +
  `converged_word_used: bool, coverage_gaps: [string]}.`,
  opts({ label: 'convergence-critic', phase: 'Convergence-critic', schema: {
    type: 'object', additionalProperties: true,
    required: ['round_appended', 'convergence_read'],
    properties: {
      round_appended: { type: 'boolean' },
      new_round_number: { type: ['integer', 'null'] },
      convergence_read: { type: 'string' },
      converged_word_used: { type: 'boolean' },
      coverage_gaps: { type: 'array', items: { type: 'string' } },
    },
  } }),
).catch(() => ({ round_appended: false, convergence_read: 'convergence-critic errored (fail-open)' }))

// The ONLY thing the main window reads: compact scalars + survivors-slim + the verdict.
return {
  lens: LENS,
  candidates: findings.length,
  summary: {
    total: persistResult.total, valid: persistResult.valid, invalid: persistResult.invalid,
    unique: persistResult.unique, corroborated: persistResult.corroborated,
    externally_verified: persistResult.externally_verified,
    survival_rate: persistResult.survival_rate,
    by_category: persistResult.by_category,
    by_refutation_outcome: persistResult.by_refutation_outcome,
    unknown_categories: persistResult.unknown_categories,
  },
  appended: persistResult.appended,
  persistError: persistResult.persist_error || null,
  persistWarnings: persistResult.warnings || [],
  corpusPath: persistResult.corpus_path,
  survivors: persistResult.survivors_slim,
  convergence: {
    read: criticVerdict.convergence_read,
    rowAppended: criticVerdict.round_appended,
    ledgerPath: LEDGER_PATH,
    coverageGaps: criticVerdict.coverage_gaps || [],
  },
}
