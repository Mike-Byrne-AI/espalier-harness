export const meta = {
  name: 'fanout-audit',
  description: 'Reusable fan-out audit/review scaffold: finders emit FINDING_SCHEMA, refuters cull, survivors persist to a corpus, and ONLY a compact FindingsSummary + survivors-slim + corpus path return to the main window — never the N verbose rationales that bloat it. Default with no args: the task-packs/ landing audit.',
  phases: [
    { title: 'Discover' },
    { title: 'Find' },
    { title: 'Refute' },
    { title: 'Persist' },
  ],
}

// ---------------------------------------------------------------------------
// Make the ultracode fan-out tooling the DEFAULT path (the on-ramp).
//
// The incident this fixes: an archive-readiness audit hand-rolled a bespoke
// per-pack schema, never aggregated, never persisted, and dumped 36 verbose
// rationales (~817 lines / ~1.77M tokens) straight into the main window.
//
// The two-hop anti-bloat dataflow (pack §5.2) — the actual fix:
//   1. Finders / refuters return FINDING_SCHEMA objects to the WORKFLOW RUNTIME
//      (never to the orchestrator chat).
//   2. A persist+aggregate step runs the Python this JS sandbox cannot (it has
//      no filesystem and no Python): espalier.fan_out_findings.aggregate_findings
//      + append_findings_to_corpus. This is an in-workflow agent (operator D2).
//   3. The main window reads ONLY: the FindingsSummary scalars, a survivors-slim
//      list (id/title/severity/location/category), and the corpus path. NOT
//      minimal_repro, refutation_reason, refuted rows, or LANDED/clean rows.
//   4. Drill-down is O(1): grep the corpus by id/location, or re-run the oracle
//      for one target — never a batch re-ingest.
//
// Parametric via `args` (every key optional):
//   { finders:         [{ id, label, prompt }],   // fully generic: your finder prompts
//     targets:         ["task-packs/TP-x.md", …],  // audit these packs (built-in finder)
//     knownCategories: ["landed","owed-residual","ledger-gap"],
//     corpusPath:      "reports/audit-findings.md",
//     refute:          true }                       // default true
// With NO args it discovers task-packs/**/TP-*.md and runs the landing audit —
// the exact incident that motivated this scaffold (this scaffold's own earn-the-red).
//
// SCHEMA NOTE: FINDING_SCHEMA lives in espalier/fan_out_findings.py (the SoT).
// The JS sandbox cannot import it, so the shape below is an inlined copy (the
// W1-E reality). Drift is caught at PERSIST time: aggregate_findings validates
// every finding against the REAL schema and reports `invalid` > 0 in the summary
// (a soft parity rail — a nonzero `invalid` means the inline copy drifted).
// ---------------------------------------------------------------------------

// `args` NORMALIZATION — sister-sited from _convergence_review_template.js (2026-09-26):
// some hosts forward the Workflow `args` value to the script global as a JSON-ENCODED
// STRING rather than a parsed object; reading `args.finders` off a string yields
// undefined, so every caller parameter binds to its default and the run silently
// becomes the default landing audit. Accept BOTH shapes; no-args still yields {} ->
// the defaults below.
let A = {}
if (typeof args === 'string') { try { A = args.trim() ? JSON.parse(args) : {} } catch (e) { A = {} } }
else if (args && typeof args === 'object') { A = args }

const CORPUS_PATH = A.corpusPath || 'reports/audit-findings.md'
const INPUT_PATH = 'reports/.fanout_audit_input.json' // gitignored scratch (reports/)
const REFUTE = A.refute !== false
const KNOWN_CATEGORIES = A.knownCategories || null

// Inlined FINDING_SCHEMA v2 (SoT: espalier/fan_out_findings.py::FINDING_SCHEMA).
// Enums are verbatim: confidence ("high","med","low"), severity
// ("blocker","major","minor","nit"), refutation ("unattempted","survived","refuted").
// FINDING_SCHEMA v2 — in-sync with espalier/fan_out_findings.py SoT (pinned by
// tests/test_contracts.py::TestFanoutSchemaParity). Keep current; do not hand-edit fields.
const FINDING = {
  type: 'object',
  additionalProperties: false,
  required: [
    'id', 'title', 'rule_or_scanner', 'violated_invariant', 'category',
    'location', 'claim', 'minimal_repro', 'verification', 'confidence',
    'proposed_fix', 'severity', 'blocks_release',
  ],
  properties: {
    id: { type: 'string', description: 'stable handle; namespace as TP-N:LABEL' },
    title: { type: 'string', description: '<=8-word triage label, distinct from claim' },
    rule_or_scanner: { type: 'string', description: 'the lens / agent / oracle that surfaced this' },
    violated_invariant: { type: 'string', description: 'the rule or contract this finding breaks' },
    category: { type: ['string', 'null'], description: 'domain-supplied bucket (validated via knownCategories) or null' },
    location: { type: 'string', description: 'path:line — or the audited pack path' },
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
    externally_verified: { type: 'boolean', description: 'true ONLY on a git-oracle-confirmed survivor' },
    corrected_confidence: { type: 'string', enum: ['high', 'med', 'low'] },
  },
}

// --- The built-in landing-audit finder/refuter prompts (used when the caller --
// --- passes `targets` or no args; ignored when the caller passes `finders`). --

function auditFinderPrompt(pack) {
  return (
    `You are auditing whether task pack \`${pack}\` actually LANDED, for an ` +
    `archive-readiness review. cwd = the repository root.\n\n` +
    `1. Run the non-LLM git oracle:  python -m espalier verify-landing ${pack} --json\n` +
    `   (it classifies each backticked path token LANDED / DRIFTED / OWED vs git HEAD).\n` +
    `2. Read \`${pack}\`'s "## Landing" stanza (State / Commits) and its claimed files.\n` +
    `3. Emit a FINDING ONLY for a genuine residual:\n` +
    `   - an OWED token that is a REAL claimed deliverable (NOT prose / ellipsis /\n` +
    `     slash-command / a bare basename that exists deeper in the tree — the\n` +
    `     verify_landing already drops those, so a surviving OWED is real);\n` +
    `   - a DRIFTED token that contradicts a "State: LANDED" Landing stanza;\n` +
    `   - a Landing/ledger claim the oracle contradicts (State: LANDED yet OWED remains).\n` +
    `   A cleanly-LANDED pack yields an EMPTY findings array — that is the EXPECTED\n` +
    `   honest result; do NOT manufacture a finding.\n\n` +
    `For each finding: id = "${packId(pack)}:archive"; category ∈ {owed-residual,\n` +
    `ledger-gap}; location = "${pack}" or "${pack}:<token>"; rule_or_scanner =\n` +
    `"verify-landing"; set externally_verified=true ONLY when the git oracle\n` +
    `(verify-landing --json / git ls-files) confirms the specific token — never off a\n` +
    `bare heuristic. severity reflects archive-safety (blocker = a real owed deliverable).\n` +
    `Return {findings: [...]}.`
  )
}

function auditRefutePrompt(finding) {
  return (
    `REFUTE this archive-audit finding (DEFAULT = refuted). cwd = repo root.\n` +
    `It SURVIVES only if the git oracle confirms a REAL residual:\n` +
    `  - re-run  python -m espalier verify-landing <pack> --json  and  git ls-files\n` +
    `    for the specific token named in the finding;\n` +
    `  - a token that IS tracked, or a false-OWED (prose / ellipsis / slash-command /\n` +
    `    bare-basename) → refuted;\n` +
    `  - a Landing-stanza claim that the oracle actually contradicts → survived.\n` +
    `Set externally_verified=true ONLY on a git-confirmed survivor.\n\n` +
    `FINDING:\n${JSON.stringify(finding, null, 2)}\n\n` +
    `Return {refutation_outcome, refutation_reason (cite the bytes), externally_verified}.`
  )
}

function packId(pack) {
  const m = pack.match(/TP-\d+/)
  return m ? m[0] : 'TP-?'
}

// --- Phase 1 — DISCOVER ----------------------------------------------------
// Build the finder list. Precedence: explicit finders > explicit targets >
// auto-discovered task-packs (the default landing audit).

phase('Discover')
let finders = A.finders || null
if (!finders) {
  let targets = A.targets || null
  if (!targets) {
    const disco = await agent(
      'Run exactly: find task-packs -name "TP-*.md" | sort\n' +
      'Return ONLY the newline-separated list of repo-relative paths it prints, nothing else.',
      {
        label: 'discover:packs', phase: 'Discover',
        schema: { type: 'object', additionalProperties: false, required: ['paths'],
          properties: { paths: { type: 'array', items: { type: 'string' } } } },
      },
    )
    targets = (disco && disco.paths) || []
  }
  finders = targets.map(p => ({ id: packId(p), label: `audit:${packId(p)}`, prompt: auditFinderPrompt(p) }))
}
log(`fanout-audit: ${finders.length} finder(s); corpus=${CORPUS_PATH}; refute=${REFUTE}`)

// --- Phase 2 — FIND --------------------------------------------------------
// Each finder returns {findings:[FINDING_SCHEMA...]} to the runtime. A finder
// that errors drops to [] (filtered), never to the chat.

phase('Find')
const finderResults = await parallel(finders.map(f => () =>
  agent(f.prompt, { label: f.label, phase: 'Find', schema: FINDINGS })
    .then(r => ((r && r.findings) || []).map(x => ({ ...x, _finder: f.id })))
    .catch(() => [])
))
const found = finderResults.filter(Boolean).flat()
log(`fanout-audit: ${found.length} candidate finding(s) from ${finders.length} finder(s)`)

// --- Phase 3 — REFUTE ------------------------------------------------------
// Adversarially verify each candidate; merge the verdict into the finding.
// refuted findings keep refutation_outcome='refuted' so the persist filter and
// the aggregator's survival_rate both see them.

phase('Refute')
let findings = found
if (REFUTE && found.length) {
  findings = await parallel(found.map((f, i) => () =>
    agent(auditRefutePrompt(f), {
      label: `refute:${f._finder || 'x'}#${i}`, phase: 'Refute', schema: REFUTE_RESULT,
    })
      .then(v => ({ ...f, ...(v || {}) }))
      .catch(() => ({ ...f, refutation_outcome: 'unattempted', refutation_reason: 'refuter errored' }))
  ))
}
// Strip EVERY private `_*` tag before the schema-validated persist, not `_finder`
// by name. FINDING_SCHEMA is additionalProperties:false and declares no
// underscore-prefixed property, so "drop what starts with _" IS the schema
// boundary rather than an approximation of it. A one-name enumeration goes stale
// the moment a second tag is stamped — which is how a sibling runner silently
// lost 69 of 181 records.
findings = findings.map(f =>
  Object.fromEntries(Object.entries(f).filter(([k]) => !k.startsWith('_'))))
const survivorCount = findings.filter(f => f.refutation_outcome !== 'refuted').length
log(`fanout-audit: ${survivorCount} survivor(s) of ${findings.length} after refute`)

// --- Phase 4 — PERSIST (in-workflow, the two-hop bridge) -------------------
// The JS sandbox has no Python; this agent writes the findings verbatim and runs
// the real espalier machinery, then returns ONLY the compact summary. json.load
// turns any transcription corruption into a LOUD failure (not silent drift).

phase('Persist')
// ALL caller-suppliable values (findings, knownCategories, corpusPath) travel
// through the JSON input file the persist agent writes with the Write tool — they
// are NEVER interpolated into the shell command. So a category or corpus path
// containing a quote / apostrophe ("won't-fix") can't break the  python -c '...'
// quoting or inject (the adversarial review lane). The ONLY value interpolated into the
// -c is INPUT_PATH, a hardcoded constant with no shell-special chars.
const persistPayload = JSON.stringify({
  findings,
  known_categories: KNOWN_CATEGORIES,
  corpus_path: CORPUS_PATH,
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
  `    "category": f.get("category"),\n` +
  `    "externally_verified": bool(f.get("externally_verified"))}\n` +
  `    for f in survivors],\n` +
  `}))\n` +
  `'`

const persistPrompt =
  `Persist the fan-out findings and return the compact summary. cwd = repo root.\n\n` +
  `STEP 1 — Use the Write tool to write the JSON below VERBATIM (do not edit, ` +
  `summarize, or re-key it) to the file:  ${INPUT_PATH}\n\n` +
  `<<<FINDINGS_JSON\n${persistPayload}\nFINDINGS_JSON\n\n` +
  `STEP 2 — Run this command EXACTLY as written (it reads that file, aggregates ` +
  `via espalier.fan_out_findings, persists survivors to the corpus, and prints a ` +
  `JSON summary):\n\n${persistCmd}\n\n` +
  `STEP 3 — Return the JSON object the command printed on stdout. If json.load ` +
  `raised (the file was corrupted on write), say so plainly instead — do not ` +
  `fabricate a summary.`

const persistResult = await agent(persistPrompt, {
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
}).catch(() => ({ total: findings.length, appended: 0, persist_error: 'persist agent errored (fail-open)', corpus_path: CORPUS_PATH, survivors_slim: [] }))

// The ONLY thing the main window reads: scalars + survivors-slim + corpus path.
return {
  findersRun: finders.length,
  candidates: found.length,
  summary: {
    total: persistResult.total,
    valid: persistResult.valid,
    invalid: persistResult.invalid,
    unique: persistResult.unique,
    corroborated: persistResult.corroborated,
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
}
