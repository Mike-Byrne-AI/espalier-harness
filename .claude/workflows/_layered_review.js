export const meta = {
  name: 'layered-review',
  description: 'Seat-by-body layered review: generic breadth finders run ALONGSIDE scoped repo-specialist FIND lanes (failure-mode-reviewer over the self-inflicted-failure surface; architecture-analyst over layer boundaries) plus a generic narrative/overclaim lane; survivors are adversarially refuted on the proven default-refuted general-purpose spine, with code-reviewer routed in to adjudicate correctness-category survivors; then a survivor-fed completeness critic (with a blind module-map fallback on a 0-survivor round) names the uncovered surface. Each agent is seated where its body actually fires. Findings emit FINDING_SCHEMA, refuted (default refuted, oracle-confirmed), survivors persisted via the two-hop bridge. Returns ONLY a compact summary + survivors-slim + corpus path. Optional args: a string scoping the review (default: the whole repo at rest).',
  phases: [
    { title: 'Find' },
    { title: 'Refute' },
    { title: 'Persist' },
  ],
}

// FINDING_SCHEMA v2 — in-sync with espalier/fan_out_findings.py SoT (pinned by
// tests/test_contracts.py::TestFanoutSchemaParity). Keep current; do not hand-edit fields.
// ---------------------------------------------------------------------------
// SCHEMA — verbatim copy of espalier/fan_out_findings.py::FINDING_SCHEMA (SoT).
// Drift is caught at PERSIST: aggregate_findings re-validates against the real
// schema and reports invalid>0. additionalProperties:false, so the refuter may
// merge ONLY fields that exist below (memory: fanout-refute-fields-must-subset).
// ---------------------------------------------------------------------------
const FINDING = {
  type: 'object',
  additionalProperties: false,
  required: [
    'id', 'title', 'rule_or_scanner', 'violated_invariant', 'category',
    'location', 'claim', 'minimal_repro', 'verification', 'confidence',
    'proposed_fix', 'severity', 'blocks_release',
  ],
  properties: {
    id: { type: 'string', description: 'stable handle; namespace as LR:LABEL' },
    title: { type: 'string', description: '<=8-word triage label, distinct from claim' },
    rule_or_scanner: { type: 'string', description: 'the lens / agent / oracle that surfaced this' },
    violated_invariant: { type: 'string', description: 'the rule or contract this finding breaks' },
    category: { type: ['string', 'null'], description: 'one of knownCategories or null' },
    location: { type: 'string', description: 'path:line' },
    claim: { type: 'string', description: 'one sentence' },
    minimal_repro: { type: 'string', description: 'the command / steps that show it (terse)' },
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
    refutation_reason: { type: 'string' },
    externally_verified: { type: 'boolean' },
    corrected_confidence: { type: 'string', enum: ['high', 'med', 'low'] },
  },
}

const CORPUS_PATH = 'reports/layered-review-findings.md'
const INPUT_PATH = 'reports/.layered_review_input.json'
// 2-B: the generic-lens categories + the seat-by-body lane categories
// ('failure-mode','layer-boundary','overclaim') + the critic's 'completeness'
// must all be known so aggregate_findings does not flag unknown_categories.
const KNOWN_CATEGORIES = [
  'correctness', 'edge-case',
  'failure-mode', 'layer-boundary', 'overclaim',
  'completeness',
]

// Shared finder preamble: the governing frame, the dedup gate, the schema rails.
const SCOPE = (typeof args === 'string' && args.trim()) ? args.trim() : 'the whole Espalier-Harness repo at rest'
const PRE =
  'cwd = the Espalier-Harness repo root. You are a FINDER in a LAYERED REVIEW (seat-by-body): generic ' +
  'breadth finders run alongside scoped repo-specialist lanes; survivors are adversarially refuted; a ' +
  'completeness critic closes the gap. REVIEW SCOPE: ' + SCOPE + '.\n\n' +
  'GOVERNING FRAME: Espalier is a workflow toolbelt, not a security boundary — the threat model is ' +
  'operator/AI *mistakes*, not malice. A finding that only bites under adversarial malice, or is ' +
  'workflow-friction / a false-positive dressed as a bug, is NOT a blocker.\n\n' +
  'DEDUP (mandatory): before emitting, grep task-packs/FORWARD_LEDGER.md (if that file is absent, as on a clean clone, ' +
  'write ABSENT-LEDGER in verification.negative and mark the finding UN-DEDUPED, not new; live rows + the section-6 ' +
  'do-not-rediscover list). Do NOT re-raise a live row; do NOT reopen a section-6 entry without NEW evidence. Only emit a ' +
  'genuinely NEW finding (id it "LR:<label>"; say "extends <existing-id>" in violated_invariant for a variant).\n\n' +
  'GROUND EVERY FINDING: read the actual bytes (the file at path:line on HEAD) and give a minimal_repro ' +
  'that is a real command or concrete steps — not speculation. Prefer running espalier\'s own oracles ' +
  '(python3 -m espalier <cmd>, the scanner modules, git, pytest) over reasoning from memory. Do NOT ' +
  'manufacture findings to look productive — the null IS the signal.\n\n' +
  'SCHEMA: set blocks_release=true only for a real release-blocker; severity in {blocker,major,minor,nit}; ' +
  'confidence in {high,med,low}; set externally_verified only if you confirmed it with a git/file/run ' +
  'oracle. Return {findings:[...]}.\n\n'

// ---- GENERIC BREADTH FINDERS (bare general-purpose; breadth is their job) ----
const GENERIC_FINDERS = [
  {
    id: 'G1', label: 'find:correctness', category: 'correctness',
    prompt: PRE +
      'GENERIC BREADTH LENS — CORRECTNESS. Sweep the engine (espalier/) + hooks (tools/cc/) for real ' +
      'bugs: wrong logic, an off-by-one, a mishandled return shape, a guard that does not guard what it ' +
      'claims, an inverted predicate, a default that silently drops data. Emit FINDING_SCHEMA objects ' +
      'with category="correctness"; ground each in path:line + a minimal repro.',
  },
  {
    id: 'G2', label: 'find:edge-cases', category: 'edge-case',
    prompt: PRE +
      'GENERIC BREADTH LENS — EDGE CASES & CONDITIONALS. Hunt the inputs that are NOT exercised: empty ' +
      'string / empty list / None / unicode / very-long / a path with spaces; boundary values (==cap, ' +
      'len 0/1); an else-branch never tested; a too-broad except masking a real failure; a 0-denominator ' +
      'division. Emit FINDING_SCHEMA objects with category="edge-case"; ground each in path:line + a tiny repro.',
  },
]

// ---- DELTA 1: SCOPED REPO-AGENT FIND LANES (the seat-by-body core) ----
// Each lane dispatches the FIND call to the repo specialist via agentType (the
// option is plumbed at the Find stage; the dated round script that first proved it
// was retired to the archive at the 2026-09-25 seed, and this file is the standing user).
// Both prompts redirect the agent AWAY from its body's default `git diff HEAD`
// step (the review is the repo AT REST, not a pending change).
const REPO_FIND_LANES = [
  { id: 'FM', label: 'find:failure-modes', category: 'failure-mode',
    agentType: 'failure-mode-reviewer',
    prompt: PRE +
      'You are running as a FAN-OUT FINDER over the repo AT REST (there is no pending git diff to ' +
      'review — do NOT start with `git diff HEAD`; apply your failure-tree / sister-site / ' +
      'documented-but-not-enforced cognition to THIS SCOPE across the current tree). SCOPE: the ' +
      'self-inflicted-failure surface — hooks in tools/cc/hooks/, the guard predicates, freshness/state ' +
      'writers, and any documented contract with no mechanical enforcement. Emit FINDING_SCHEMA objects ' +
      'with category="failure-mode"; ground each in path:line + a concrete trigger sequence.' },
  { id: 'AR', label: 'find:layer-boundaries', category: 'layer-boundary',
    agentType: 'architecture-analyst',
    prompt: PRE +
      'You are running as a FAN-OUT FINDER over the repo AT REST. SCOPE: layer boundaries / import ' +
      'direction / isolation (espalier/ imports espalier/ only; tools/cc/ has zero espalier imports; ' +
      'scanners stdlib-only; hook exit-code channel-XOR). IMPORTANT: your tool grant has NO Bash(grep *) — ' +
      'use the Grep TOOL (not shell grep) plus `git`/`python` to confirm import-direction / layer claims, ' +
      'or you hit a permission wall and miss the finding. Emit FINDING_SCHEMA objects with ' +
      'category="layer-boundary"; ground each in path:line.' },
]

// ---- DELTA 1 (cont): GENERIC NARRATIVE/OVERCLAIM LANE (release-verifier nugget) ----
// Generic agent — no agentType; the lens is a prompt, not a roster agent. The
// numeric-claim half is already covered mechanically by espalier/audit_accuracy.py
// (NumericContracts), so this steers to PROSE overclaims + cross-surface drift only.
const NARRATIVE_LANE = {
  id: 'OC', label: 'find:overclaim', category: 'overclaim',
  prompt: PRE +
    'You are a NARRATIVE/CLAIMS-CONSISTENCY finder. Hunt QUALITATIVE overclaims and cross-surface ' +
    'drift — do NOT re-derive numeric-count drift (espalier/audit_accuracy.py already covers numbers). ' +
    'Look for: (a) prose that claims more than the code does ("robust", "comprehensive", "fully handles", ' +
    '"guaranteed", "always/never") with no enforcing code/test; (b) a behavior documented in one surface ' +
    'that the code or another surface contradicts; (c) a README/CHANGELOG/QUICKSTART statement that the ' +
    'repo no longer bears out. Emit FINDING_SCHEMA objects with category="overclaim"; cite path:line AND ' +
    'the contradicting surface. An empty findings array is honest.',
}

const FINDERS = GENERIC_FINDERS.concat(REPO_FIND_LANES, [NARRATIVE_LANE])

// ---- DELTA 2: REFUTE — proven generic default-refuted spine, PLUS code-reviewer
// for correctness-category survivors. The explicit allowlist (NOT a free-text
// regex) + the observable log line are the lesson from the DECLINED design's
// 1/11 silent no-op: routing must be observable and verified.
// agentType selects COGNITIVE MODE; schema selects OUTPUT CONTRACT — orthogonal, both set.
const CORRECTNESS_CATEGORIES = new Set(['correctness', 'bug', 'logic', 'convention', 'code-review'])
function pickRefuter(category) {
  return CORRECTNESS_CATEGORIES.has((category || '').toLowerCase()) ? 'code-reviewer' : 'general-purpose'
}

// Refuter-only fields a FINDER/CRITIC must not pre-populate: corrected_* belong
// to the refute stage. aggregate_findings' _eff_category/_eff_confidence honor
// corrected_* over the original, so a finder emitting corrected_category=null
// sinks its finding into the null bucket (observed in the 2-A live run — the
// completeness findings vanished from by_category). Strip them from finder +
// critic output; a refuter's legitimate corrected_confidence still rides through
// the {...x, ...v} merge below, because it comes from the REFUTE_RESULT result v.
const stripRefuterFields = (x) => {
  const { corrected_category, corrected_confidence, ...rest } = x
  return rest
}

const refutePrompt = (f) =>
  'REFUTE this code-review finding. DEFAULT = refuted — it SURVIVES only if you confirm it against the ' +
  'actual bytes on HEAD (or a real re-run of its repro). cwd = repo root.\n\n' +
  'STEPS:\n' +
  '1. Read the exact location (path:line) on HEAD (git show HEAD:<path> or Read the file). If the cited ' +
  'code/behavior is not actually there, or says otherwise -> refuted.\n' +
  '2. If minimal_repro is a command, RUN it. If it does not reproduce the claimed bug -> refuted.\n' +
  '3. Check task-packs/FORWARD_LEDGER.md: if this duplicates a live row or known entry (not a genuine new ' +
  'variant) -> refuted; if it reopens a section-6 do-not-rediscover entry without NEW evidence -> refuted.\n' +
  '4. GOVERNING FRAME: Espalier is a workflow toolbelt, not a security boundary (threat model = ' +
  'operator/AI mistakes, not malice). A finding that only bites under adversarial malice, or is ' +
  'workflow-friction / a false-positive, survives at most as a downgraded severity with blocks_release=false.\n' +
  '5. Re-judge severity via blocks_release ONLY. Do NOT add a corrected_severity field — the schema is ' +
  'additionalProperties:false and any extra key invalidates the finding (you MAY set corrected_confidence).\n' +
  'Set externally_verified=true ONLY on a git/file/run-oracle-confirmed survivor.\n\n' +
  'If you are the code-reviewer, adjudicate this as a CORRECTNESS claim against the cited bytes on HEAD — ' +
  'give FACT/INFERENCE and the smallest proof; default refuted unless the repro confirms it.\n\n' +
  'FINDING:\n' + JSON.stringify(f, null, 2) + '\n\n' +
  'Return {refutation_outcome, refutation_reason (cite the bytes you read or the command output), ' +
  'externally_verified, corrected_confidence}.'

phase('Find')
log(`layered-review: ${FINDERS.length} finders (${GENERIC_FINDERS.length} generic + ${REPO_FIND_LANES.length} repo-agent lanes + 1 narrative); scope="${SCOPE}"; corpus=${CORPUS_PATH}`)

let routedToCodeReviewer = 0
let routedToGeneral = 0
const piped = await pipeline(
  FINDERS,
  (f) => agent(f.prompt, { label: f.label, phase: 'Find', schema: FINDINGS, agentType: f.agentType })
    .then((r) => ({ finder: f, findings: ((r && r.findings) || []) })),
  (res, f) => {
    const items = res.findings.map((x) => ({ ...stripRefuterFields(x), category: x.category || f.category, _finder: f.id }))
    if (!items.length) return []
    return parallel(items.map((x, i) => () => {
      const rt = pickRefuter(x.category)
      if (rt === 'code-reviewer') routedToCodeReviewer++; else routedToGeneral++
      return agent(refutePrompt(x), { label: `refute:${f.id}#${i}`, phase: 'Refute', schema: REFUTE_RESULT, agentType: rt })
        .then((v) => ({ ...x, ...(v || {}) }))
        .catch(() => ({ ...x, refutation_outcome: 'unattempted', refutation_reason: 'refuter errored' }))
    }))
  },
)

// pipeline returns one array-per-finder (the refute stage returns an array); flatten,
// then strip EVERY private `_*` tag before the schema-validated persist — not
// `_finder` by name. FINDING_SCHEMA is additionalProperties:false and declares no
// underscore-prefixed property, so "drop what starts with _" IS the schema boundary
// rather than an approximation of it, and it cannot go stale as new tags are added.
let findings = piped.filter(Boolean).flat().filter(Boolean)
findings = findings.map(f =>
  Object.fromEntries(Object.entries(f).filter(([k]) => !k.startsWith('_'))))
const survivorCount = findings.filter((f) => f.refutation_outcome === 'survived').length
log(`layered-review: ${findings.length} candidates, ${survivorCount} survivor(s) after refute`)
// Observable routing (the explicit guard against re-shipping the declined design's silent no-op).
log(`refute routing: ${routedToCodeReviewer} candidate(s) -> code-reviewer, ${routedToGeneral} -> general-purpose`)

// ---- DELTA 3: SURVIVOR-FED COMPLETENESS CRITIC (with empty-survivor fallback) ----
// The critic INGESTS the survivors (not a blind re-derivation) so it names what
// the surviving findings did NOT cover; on a 0-survivor round it degenerates, so
// fall back to a BLIND module-map sweep. Findings must be schema-clean.
const survivors = findings.filter((f) => f.refutation_outcome !== 'refuted')
const slim = survivors.map((f) => ({ id: f.id, title: f.title, location: f.location, category: f.category }))
log(`layered-review: feeding ${slim.length} survivor(s) to the completeness critic`)
const criticPrompt = survivors.length
  ? 'You are a completeness critic. Below are the SURVIVING findings from a layered review of this ' +
    'repo. Name what surface these findings did NOT cover — a subsystem, a failure class, an unrun ' +
    'modality. Emit FINDING_SCHEMA objects with category="completeness" for each genuine gap (ground ' +
    'each in a path/command; the null result is honest). Survivors:\n' + JSON.stringify(slim, null, 2)
  : 'You are a completeness critic. This round produced ZERO surviving findings. Do a BLIND module-map ' +
    'sweep: name the subsystems / failure classes / modalities a generic fan-out most often misses on ' +
    'this repo, and emit FINDING_SCHEMA objects with category="completeness" for any genuine gap (ground ' +
    'each in a path/command). An empty findings array is an honest result.'
const critic = await agent(criticPrompt,
  { label: 'critic:completeness', phase: 'Refute', schema: FINDINGS, agentType: 'failure-mode-reviewer' })
const criticFindings = ((critic && critic.findings) || []).map(stripRefuterFields)
log(`layered-review: completeness critic emitted ${criticFindings.length} gap finding(s)`)

// Persist ALL candidates + critic findings: the python filters refuted ones out
// of the corpus append, but keeping them in the aggregate keeps survival_rate /
// by_refutation_outcome honest. Critic findings carry no refutation_outcome, so
// they ride through as survivors.
const allFindings = findings.concat(criticFindings)

// --- PERSIST (two-hop bridge) ------------------------------------------------
phase('Persist')
if (!allFindings.length) {
  // persistError is null, not a message: nothing failed because the persist step never ran.
  return { findersRun: FINDERS.length, candidates: 0, summary: { total: 0 }, appended: 0, persistError: null, persistWarnings: [], corpusPath: CORPUS_PATH, survivors: [] }
}
const persistPayload = JSON.stringify({ findings: allFindings, known_categories: KNOWN_CATEGORIES, corpus_path: CORPUS_PATH })
// ONE DESTINATION plus the summary ledger. The per-round report (CORPUS_PATH, under
// reports/) is this round's record, immutable and cited by the convergence ledger;
// finding_ledger.append_summary writes the per-run structured row the convergence-critic
// reads. The shared cross-round dedup corpus was retired 2026-09-21: a survivor reaches
// task-packs/FORWARD_LEDGER.md only through a verify pass that files a row, a section-6
// do-not-rediscover entry, or nothing -- never by append.
const persistCmd =
  `python3 -c '\n` +
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
  `Persist the layered-review findings and return the compact summary. cwd = repo root.\n\n` +
  `STEP 1 — Use the Write tool to write the JSON below VERBATIM (do not edit, summarize, or re-key it) to:  ${INPUT_PATH}\n\n` +
  `<<<FINDINGS_JSON\n${persistPayload}\nFINDINGS_JSON\n\n` +
  `STEP 2 — Run this command EXACTLY as written:\n\n${persistCmd}\n\n` +
  `STEP 3 — Return the JSON object the command printed on stdout. If json.load raised (file corrupted on write), ` +
  `say so plainly instead of fabricating a summary.`

const persistResult = await agent(persistPrompt, {
  label: 'persist:corpus', phase: 'Persist',
  schema: {
    type: 'object', additionalProperties: true,
    required: ['total', 'appended', 'corpus_path', 'survivors_slim'],
    properties: {
      total: { type: 'integer' }, valid: { type: 'integer' }, invalid: { type: 'integer' },
      unique: { type: 'integer' }, corroborated: { type: 'integer' },
      externally_verified: { type: 'integer' }, survival_rate: { type: ['number', 'null'] },
      by_category: { type: 'object', additionalProperties: true },
      by_refutation_outcome: { type: 'object', additionalProperties: true },
      unknown_categories: { type: 'array', items: { type: 'string' } },
      appended: { type: 'integer' },
      warnings: { type: 'array', items: { type: 'string' } },
      ledger: { type: 'integer' }, corpus_path: { type: 'string' },
      survivors_slim: { type: 'array', items: { type: 'object', additionalProperties: true } },
    },
  },
}).catch(() => ({ total: allFindings.length, appended: 0, persist_error: 'persist agent errored (fail-open)', corpus_path: CORPUS_PATH, survivors_slim: [] }))

return {
  findersRun: FINDERS.length,
  candidates: findings.length,
  criticGaps: criticFindings.length,
  refuteRouting: { codeReviewer: routedToCodeReviewer, generalPurpose: routedToGeneral },
  summary: {
    total: persistResult.total, valid: persistResult.valid, invalid: persistResult.invalid,
    unique: persistResult.unique, corroborated: persistResult.corroborated,
    externally_verified: persistResult.externally_verified, survival_rate: persistResult.survival_rate,
    by_category: persistResult.by_category, by_refutation_outcome: persistResult.by_refutation_outcome,
    unknown_categories: persistResult.unknown_categories,
  },
  appended: persistResult.appended,
  persistError: persistResult.persist_error || null,
  persistWarnings: persistResult.warnings || [],
  corpusPath: persistResult.corpus_path,
  survivors: persistResult.survivors_slim,
}
