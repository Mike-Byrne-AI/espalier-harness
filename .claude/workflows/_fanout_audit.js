export const meta = {
  name: 'fanout-audit',
  description: 'Reusable fan-out audit/review scaffold: finders emit FINDING_SCHEMA, refuters cull, survivors persist to a corpus, and ONLY a compact FindingsSummary + survivors-slim + corpus path return to the main window — never the N verbose rationales that bloat it. Args: an object carrying finders or targets; an args value it cannot use (a string that is not JSON, such as a bare pack path; a non-object; an unknown key) launches no agent and says why. With no args it is a dry run: it counts the task-packs/ landing-audit targets and the agent budget, and runs the audit only with confirm: true. More finders than maxFinders (default 25) refuses unless maxFinders is raised. Every lane that did not run is returned by name, never folded in as an empty result.',
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
//     refute:          true,                        // default true
//     model:           "sonnet",                    // applied to EVERY agent call (default: inherit the session model)
//     confirm:         true,                        // run the no-args landing audit instead of its dry run
//     maxFinders:      25 }                         // the finder cap; raise it to run a wider audit
// With NO args (or an object carrying neither finders nor targets) it discovers
// task-packs/**/TP-*.md, logs how many packs it found and the agents a run would
// launch, and stops: the landing audit runs only with `confirm: true`. An args value
// this scaffold cannot use launches no agent and says why, so a mistyped call never
// widens into the whole-tree audit. More finders than the cap refuse the same way.
//
// SCHEMA NOTE: FINDING_SCHEMA lives in the engine's fan_out_findings module (the SoT).
// The JS sandbox cannot import it, so the shape below is an inlined copy (the
// W1-E reality). Drift is caught at PERSIST time: aggregate_findings validates
// every finding against the REAL schema and reports `invalid` > 0 in the summary
// (a soft parity rail — a nonzero `invalid` means the inline copy drifted).
// ---------------------------------------------------------------------------

// `args` NORMALIZATION — sister-sited from _convergence_review_template.js (2026-09-26):
// some hosts forward the Workflow `args` value to the script global as a JSON-ENCODED
// STRING rather than a parsed object. Accept BOTH shapes, and REFUSE what is neither:
// a string that does not parse (a plain pack path is the likely one), a JSON value that
// is not an object, or an object carrying a key this scaffold does not read (`target`
// for `targets`). Each once fell through to {} and so to the widest run there is, a
// recursive audit of every pack with one finder per hit; now it launches no agent.
const KNOWN_ARGS = ['finders', 'targets', 'knownCategories', 'corpusPath', 'refute', 'model', 'confirm', 'maxFinders']
// A bound on an accidental wide run, not a measured budget: each finder spawns one
// refuter per candidate it returns, so the finder count is the run's multiplier.
const DEFAULT_MAX_FINDERS = 25
let A = {}
let argsRefusal = null
if (typeof args === 'string') {
  if (args.trim()) {
    try { A = JSON.parse(args) } catch (e) {
      A = null
      argsRefusal = `args is a string that does not parse as JSON (${JSON.stringify(args.slice(0, 80))}); pass an object such as { "targets": ["<pack path>"] }`
    }
  }
} else if (args !== undefined && args !== null) { A = args }
if (!argsRefusal) {
  if (!A || typeof A !== 'object' || Array.isArray(A)) {
    argsRefusal = `args resolved to ${A === null ? 'null' : Array.isArray(A) ? 'an array' : typeof A}, not an object; pass { "targets": [...] } or { "finders": [...] }`
  } else {
    const unknown = Object.keys(A).filter(k => !KNOWN_ARGS.includes(k))
    if (unknown.length) {
      argsRefusal = `args carries key(s) this scaffold does not read: ${unknown.join(', ')}; it reads ${KNOWN_ARGS.join(', ')}`
    } else if (A.finders !== undefined && !(Array.isArray(A.finders) && A.finders.length &&
        A.finders.every(f => f && typeof f === 'object' && typeof f.prompt === 'string' && f.prompt.trim()))) {
      argsRefusal = 'finders must be a non-empty array of { id, label, prompt } objects, each carrying a prompt'
    } else if (A.targets !== undefined && !(Array.isArray(A.targets) && A.targets.length &&
        A.targets.every(t => typeof t === 'string' && t.trim()))) {
      argsRefusal = 'targets must be a non-empty array of pack paths'
    } else if (A.maxFinders !== undefined && !(Number.isInteger(A.maxFinders) && A.maxFinders > 0)) {
      argsRefusal = 'maxFinders must be a positive integer'
    }
  }
}
if (argsRefusal) {
  log(`fanout-audit: refused, no agent launched -- ${argsRefusal}`)
  return { refused: argsRefusal, agentsLaunched: 0 }
}
const MAX_FINDERS = A.maxFinders || DEFAULT_MAX_FINDERS
const CONFIRMED = A.confirm === true

const CORPUS_PATH = A.corpusPath || 'reports/audit-findings.md'
const INPUT_PATH = 'reports/.fanout_audit_input.json' // gitignored scratch (reports/)
const REFUTE = A.refute !== false
const KNOWN_CATEGORIES = A.knownCategories || null
// One model for the whole run. Workflow agents inherit the session model unless each
// call overrides it; `args.model` is that override, routed through `opts()` at EVERY
// agent() call so a run never silently inherits a model the operator did not choose.
const MODEL = (typeof A.model === 'string' && A.model.trim()) ? A.model.trim() : null
const opts = (o) => (MODEL ? { ...o, model: MODEL } : o)
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
// LANES THAT DID NOT RUN. Under the Workflow API a skipped agent, or one that dies on
// a terminal error, resolves to null, and parallel() and pipeline() turn a thrown lane
// into null. Each such lane is recorded here by its label and returned, never folded
// into an empty result: a lane that found nothing and a lane that never ran must not
// read the same. A refuter that did not run leaves its finding `unattempted`.
const lanesNotRun = []
const refutersNotRun = []
const notRun = (phaseName, lane) => { lanesNotRun.push({ phase: phaseName, lane }) }
const notRunByPhase = () => lanesNotRun.reduce((acc, x) => {
  (acc[x.phase] = acc[x.phase] || []).push(x.lane)
  return acc
}, {})

// Inlined FINDING_SCHEMA v2 (SoT: the engine's fan_out_findings.FINDING_SCHEMA).
// Enums are verbatim: confidence ("high","med","low"), severity
// ("blocker","major","minor","nit"), refutation ("unattempted","survived","refuted").
// FINDING_SCHEMA v2 — in sync with the engine's SoT (pinned by
// TestFanoutSchemaParity). Keep current; do not hand-edit fields.
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
const DEFAULT_RUN = !A.finders && !A.targets
let finders = A.finders || null
if (!finders) {
  let targets = A.targets || null
  if (!targets) {
    const disco = await agent(
      'Run exactly: find task-packs -name "TP-*.md" | sort\n' +
      'Return ONLY the newline-separated list of repo-relative paths it prints, nothing else.',
      opts({
        label: 'discover:packs', phase: 'Discover',
        schema: { type: 'object', additionalProperties: false, required: ['paths'],
          properties: { paths: { type: 'array', items: { type: 'string' } } } },
      }),
    ).catch(() => null)
    if (disco == null) {
      notRun('Discover', 'discover:packs')
      log('fanout-audit: the discover lane did not run (skipped, errored, or died on an error); no finder launched')
      return { findersRun: 0, findersLaunched: 0, lanesNotRun: notRunByPhase(), agentsLaunched: 1 }
    }
    targets = disco.paths || []
  }
  finders = targets.map(p => ({ id: packId(p), label: `audit:${packId(p)}`, prompt: auditFinderPrompt(p) }))
}
const finderLabel = (f, i) => f.label || f.id || `finder#${i}`
// The no-args landing audit is a DRY RUN unless the caller confirms it: the host's
// approval prompt fires before the targets resolve, and an auto, bypass or headless
// run does not ask again, so the count is said here and the run stops.
if (DEFAULT_RUN && !CONFIRMED) {
  log(`fanout-audit: DRY RUN -- discovered ${finders.length} pack(s); a run would launch ${finders.length} finder(s), ` +
      `${REFUTE ? 'one refuter per candidate they return' : 'no refuter (refute is off)'} and 1 persist agent. ` +
      `Pass { "confirm": true } to run it` +
      (finders.length > MAX_FINDERS ? ` with { "maxFinders": ${finders.length} } to lift the finder cap of ${MAX_FINDERS}.` : '.'))
  return {
    dryRun: true, discovered: finders.length, finderCap: MAX_FINDERS,
    wouldLaunch: { finders: finders.length, refuters: REFUTE ? 'one per candidate' : 0, persist: 1 },
    agentsLaunched: 1,
  }
}
if (finders.length > MAX_FINDERS) {
  const why = `${finders.length} finder(s) exceed the cap of ${MAX_FINDERS}; pass { "maxFinders": ${finders.length} } to run them all`
  log(`fanout-audit: refused, no finder launched -- ${why}`)
  return { refused: why, findersLaunched: 0, agentsLaunched: DEFAULT_RUN ? 1 : 0 }
}
log(`fanout-audit: ${finders.length} finder(s); corpus=${CORPUS_PATH}; refute=${REFUTE}; model=${MODEL || 'inherited'}`)

// --- Phase 2 — FIND --------------------------------------------------------
// Each finder returns {findings:[FINDING_SCHEMA...]} to the runtime. A finder
// that resolved null or threw is a lane that did not run: parallel() hands back
// null at its index, and it is recorded by label, never read as an empty result.

phase('Find')
const finderResults = await parallel(finders.map((f, i) => () =>
  agent(f.prompt, opts({ label: finderLabel(f, i), phase: 'Find', schema: FINDINGS }))
    .then(r => (r == null ? null
      : (r.findings || []).map(x => ({ ...stripRefuterFields(x), rule_or_scanner: f.id, _finder: f.id }))))
))
finders.forEach((f, i) => { if (finderResults[i] == null) notRun('Find', finderLabel(f, i)) })
const findersRun = finders.length - lanesNotRun.filter(x => x.phase === 'Find').length
const found = finderResults.filter(Boolean).flat()
log(`fanout-audit: ${found.length} candidate finding(s) from ${findersRun} of ${finders.length} finder(s)` +
    (findersRun < finders.length ? `; did not run: ${notRunByPhase().Find.join(', ')}` : ''))

// --- Phase 3 — REFUTE ------------------------------------------------------
// Adversarially verify each candidate; merge the verdict into the finding.
// refuted findings keep refutation_outcome='refuted' so the persist filter and
// the aggregator's survival_rate both see them.

phase('Refute')
let findings = found
if (REFUTE && found.length) {
  findings = await parallel(found.map((f, i) => () =>
    agent(auditRefutePrompt(f), opts({
      label: `refute:${f._finder || 'x'}#${i}`, phase: 'Refute', schema: REFUTE_RESULT,
    }))
      .then(v => (v == null
        ? { ...f, refutation_outcome: 'unattempted', refutation_reason: 'refuter returned nothing (skipped, or died on an error)' }
        : { ...f, ...v }))
      .catch(() => ({ ...f, refutation_outcome: 'unattempted', refutation_reason: 'refuter errored' }))
      .then(r => {
        if (r.refutation_outcome === 'unattempted') refutersNotRun.push(`refute:${f._finder || 'x'}#${i}`)
        return r
      })
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
// No finder ran: there is no round to record. A zero-total summary row would read in
// the per-run ledger as a clean round, which it was not.
if (findersRun === 0) {
  log('fanout-audit: no finder lane ran; nothing persisted')
  return {
    findersRun: 0, findersLaunched: finders.length, lanesNotRun: notRunByPhase(),
    refutersNotRun, candidates: 0, appended: 0, persistError: null, persistWarnings: [],
    corpusPath: CORPUS_PATH, survivors: [],
  }
}
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
// the forward ledger (task-packs/FORWARD_LEDGER.md, or a row file under task-packs/ledger.d/
// where the repository keeps rows as files) only through a verify pass that files a row,
// a section-6 do-not-rediscover entry, or nothing -- never by append.
const persistCmd =
  `PY=; for c in 'python3' python 'py -3'; do $c -c 'import sys, espalier; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && { PY=$c; break; }; done; [ -n "$PY" ] || { echo 'no Python 3.10+ with espalier answered to python3, python or py -3' >&2; exit 1; }\n` +
  `$PY -c '\n` +
  `import json, sys, warnings\n` +
  `from espalier.fan_out_findings import aggregate_findings, append_findings_to_corpus\n` +
  `from espalier.finding_ledger import append_summary\n` +
  `data = json.load(open("${INPUT_PATH}", encoding="utf-8"))\n` +
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
  `Persist the fan-out findings and return the compact summary. cwd = repo root.\n\n` +
  `STEP 1 — Use the Write tool to write the JSON below VERBATIM (do not edit, ` +
  `summarize, or re-key it) to the file:  ${INPUT_PATH}\n\n` +
  `<<<FINDINGS_JSON\n${persistPayload}\nFINDINGS_JSON\n\n` +
  `STEP 2 — Run this command EXACTLY as written (it reads that file, aggregates ` +
  `via espalier.fan_out_findings, persists survivors to the corpus, and prints a ` +
  `JSON summary):\n\n${persistCmd}\n\n` +
  `STEP 3 — Return the JSON object the command printed on stdout. If json.load ` +
  `raised (the file was corrupted on write), say so plainly instead — do not ` +
  `fabricate a summary. ` +
  `If the command instead printed a line starting "no Python" and exited 1, ` +
  `no interpreter that imports espalier answered on this host: report that ` +
  `line as the persist error, never as an empty result.`

const persistRaw = await agent(persistPrompt, opts({
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
})).catch(() => null)
if (persistRaw == null) notRun('Persist', 'persist:corpus')
const persistResult = persistRaw || { total: findings.length, appended: 0, persist_error: 'the persist agent did not run (skipped, errored, or died on an error; fail-open): nothing was persisted', corpus_path: CORPUS_PATH, survivors_slim: [] }

// The ONLY thing the main window reads: scalars + survivors-slim + corpus path.
return {
  findersRun,
  findersLaunched: finders.length,
  lanesNotRun: notRunByPhase(),
  refutersNotRun,
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
