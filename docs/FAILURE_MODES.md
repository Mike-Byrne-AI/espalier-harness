# Failure Mode Cheat Sheet

A self-contained catalog of generative patterns that produce bugs.
Each entry names a **class** of failure — not a single instance, but
the *shape* that generates instances. In-repo examples are inlined;
the document does not require chasing references to other docs to
understand the pattern.

Source paths in this document name files in the Espalier source repo
(`tests/…`, `espalier/…`, `scripts/…`): they say where each pattern was
found, and `init` does not deploy them. A `DEF-NNN` names a row of the
source repo's `task-packs/FORWARD_LEDGER.md`, the forward-work tracker,
which ships in the public repository and is not deployed by `init` either.

## How to read this

Three levels of abstraction matter:

```
Level 3 — FAILURE MODE / DEFECT CLASS
          "Convergence theater"
                ↑ "what shape generates these?"
Level 2 — SISTER SITES
          test_corpus_count_parity, test_manifest_truth, ...
                ↑ "what other places have this same bug?"
Level 1 — INSTANCE
          test_corpus_count_parity.py:80-88
```

**Sister sites** = same bug at another address.
**Failure mode** = the grammar that generates the bug in the first place.

Naming the mode lets you (1) find sister sites mechanically, (2)
predict where future instances will appear, (3) write contracts that
prevent the shape from recurring.

## Terminology provenance

| Term | Source |
|---|---|
| Failure mode | FMEA (Failure Mode and Effects Analysis), US military/aerospace 1940s–50s; standard in systems engineering |
| Defect class | QA / testing literature (NIST, IEEE, ISTQB) |
| Anti-pattern | Brown, Malveau, McCormick, Mowbray, *AntiPatterns* (1998); term coined by Andrew Koenig (1995) |
| Code smell | Kent Beck (coined); popularized by Fowler, *Refactoring* (1999) |
| Connascence | Meilir Page-Jones, *The Practical Guide to Structured Systems Design* (1988) — the most rigorous taxonomy of coupling |
| Goodhart's law | Charles Goodhart (1975); restated by Marilyn Strathern (1997) |
| TOCTOU | Security literature; formalized ~1996 |
| Vulnerability class | MITRE CWE — formal security taxonomy |

The named coinages in this catalog (convergence theater, stealth
contracts, doc-surface propagation, canon-vs-claim, relaxation-tightening
contract drift, habit-formation against friction, gate tuning-to-HEAD
blind spot, predicate-name semantics creep, nested file-existence
trap, canon formula structural impossibility, gate credibility,
sister-predicate domain blindness, autoimmune regression) are
NOT industry-standard terms. Their underlying concepts exist in
literature in fragmentary form; the labels are ours. (§10.8
enumeration-shadow leak and §13.9 complacent oracle are further
catalog-internal coinages outside the §1 set.)

---

## Table of contents

1. [Major named failure modes (full detail)](#1-major-named-failure-modes)
2. [Test and assertion failure modes](#2-test-and-assertion-failure-modes)
3. [Architectural and coupling failure modes](#3-architectural-and-coupling-failure-modes)
4. [Documentation and information drift failure modes](#4-documentation-and-information-drift-failure-modes)
5. [Epistemic and measurement failure modes](#5-epistemic-and-measurement-failure-modes)
6. [Security failure modes](#6-security-failure-modes)
7. [Distributed and reliability failure modes](#7-distributed-and-reliability-failure-modes)
8. [Observability failure modes](#8-observability-failure-modes)
9. [Platform and encoding failure modes](#9-platform-and-encoding-failure-modes)
10. [Detector and scanner failure modes](#10-detector-and-scanner-failure-modes)
11. [AI-collaboration failure modes](#11-ai-collaboration-failure-modes)
12. [Process and organizational failure modes](#12-process-and-organizational-failure-modes)
13. [Detection methodology](#13-detection-methodology)
14. [Adopter-experience and OSS-boundary failure modes](#14-adopter-experience-and-oss-boundary-failure-modes)
15. [Recall-engine and context-injection failure modes](#15-recall-engine-and-context-injection-failure-modes)
16. [Multi-agent / concurrent shared-tree failure modes](#16-multi-agent--concurrent-shared-tree-failure-modes)
17. [Shelling out to git from the wrong directory](#17-shelling-out-to-git-from-the-wrong-directory)
18. [The artifact you author to prove or describe a fix is itself unverified](#18-the-artifact-you-author-to-prove-or-describe-a-fix-is-itself-unverified)

---

## 1. Major named failure modes

The thirteen modes in this section are documented at full detail because
each names a recurring class of self-inflicted defect that ordinary
review processes miss. The shorter entries in §2–§12 follow the same
template but with less elaboration where the pattern is already
well-known in industry.

### 1.1 Convergence theater

**Signature.** An assertion `X == Y` where X and Y ultimately resolve
to the same source. The test passes by construction.

**Mental model.** A courtroom where the prosecution and defense call
the same witness. You can't lose, but you also can't establish truth.

**Industry analogs.** Tautological test. Self-verifying test. Circular
validation. None is dominant.

**Shapes.**
- `assert X == X` (literal identity)
- `assert f(args) == f(args)` (same callable + args both sides)
- `assert a.b.c == a.b.c` (same attribute path)
- `assert len(producer) == EXPECTED_DERIVED` where `EXPECTED_DERIVED = len(producer)`
- `self.assertEqual(X, X)` (unittest)
- `assert X == pytest.approx(X)`, either operand order (tolerance against self)

**In-repo example.** A v0.6.0 audit found four independent canon-circle
instances — README claimed 22 checks when the live binary emitted 20,
QUICKSTART's clone URL 404'd, README's doctor demo showed a `summary`
key the live binary never emits, and `init` printed agent counts that
disagreed with directory listings. All four were structurally similar:
internal documents agreed with each other but external reality
disagreed with all of them. The fix was binding documented claims to
external witnesses via the `NumericContract` framework in
`tests/test_documented_claims.py`, which AST-extracts the live binary
output and compares to documented numbers each test run. Separately,
the scaffolding canon at `espalier/scaffolding_canon.py` is forbidden
from importing `espalier.reflect_protocol`, `espalier.reflection`, or
`espalier.models.ReflectPass` when reading blueprint JSON — must use
stdlib `json.load` instead. The contract is pinned by
`tests/test_scaffolding_canon.py` with an AST walk asserting zero
imports from the forbidden set plus a negative-proof sub-assertion.
A third instance: v0.6.0's `check_release_archive_clean` walked the
built archive and consulted `espalier/surface_contract.py` to classify
each member; the classifier had no rule for top-level `*.zip`,
defaulted to `public`, the gate passed, and a 6 MB dev-state
`project.zip` shipped. Fixed by introducing `espalier/release_denylist.py`
as an independent witness (56 patterns, AST-asserted zero shared
imports with the classifier).

**Detection.** AST walk: classify `assert` and `assertEqual` nodes;
flag any where both sides share an import chain or evaluate to the
same expression. Cross-reference the canon's own dependency closure
against the producer module's closure — overlap signals theater.

**Contract.** Independent witnesses. Two legitimate shapes: (a)
committed file on disk vs live render of producer; (b) AST-extracted
strings or values from two distinct producer modules. The forbidden
shape is `assert len(producer.X) == EXPECTED_X` where
`EXPECTED_X = len(producer.X)`.

**Why it generates instances.** Consolidation (DRY) gone wrong: when
you extract `EXPECTED_X = derive(producer)` to remove hand-maintained
counts, downstream tests using `EXPECTED_X` as a witness against the
producer fuse into theater. Every good consolidation pack ships latent
theater unless witnesses are marked explicitly. The instinct to
deduplicate is correct; the failure mode is consuming the deduplicated
constant from a position where independence was the point.

**Automation-layer rider (goal-gate convergence theater).** When a convergence
or red-team pass is driven by a `/goal` (a session-scoped Stop hook judged by a
*separate tool-less* model — see `docs/CC_AUTOMATION.md`, Espalier source repo — not deployed by `init`),
the evaluator can only
see *that* a workflow ran and *what* it reported, never *whether* the review was
rigorous. A loop produces thorough-looking activity; the gate sees "0 blockers";
the BLOCKER-yield trend (the real correctness signal) goes unwatched. Accepting
"red-team ran" as proof of done is convergence theater at the automation layer.
Mitigation: a goal condition must require the *harder visible artifacts*
(earn-the-red shown, suite green, audit clean, atomic commit), never "red-team
ran"; keep depth-judgment in the work-turn; re-execute blocker repros mechanically
(§11.12); glance at the BLOCKER-yield trend by hand.

**Related.** §10.1 single-signal detector over-match. §5.4
self-verifying canon. §5.7 producer/consumer parity drift. §11.12
count-gating manufactures findings (the automation-layer anti-pattern).

---

### 1.2 Stealth contracts

**Signature.** Two modules behave as if they import each other but
don't. The coupling is real — rename one side and the other breaks —
but invisible to import-graph tools.

**Mental model.** Two friends in different cities who text constantally. 
They rely on each other for information, but neither of their teams know where the info comes from.
One friend looses his phone, the team of the other friend is effected.

**Industry analogs.** Connascence of name / position / algorithm
(Page-Jones 1988 — the most rigorous taxonomy of coupling forms).
Stamp coupling (Yourdon & Constantine 1979). Implicit interface
(Domain-Driven Design literature).

**Shapes (five sub-categories).**
1. **Subprocess invocation** — module M shells out to module N's
   CLI; CLI flag surface = contract; rename → silent no-op.
2. **Filesystem state** — M writes a file; N reads it; schema =
   contract; no test pins it.
3. **Environment variable** — M sets `$X`; N reads `$X`; variable
   name = contract.
4. **Magic `parents[N]`** — `Path(__file__).parents[N]` encodes a
   depth assumption about sibling directories.
5. **JSON / state-file format** — shared serialization between modules
   without a schema validator.

**In-repo examples.**

- *Subprocess + env coupling.* Two tests in `tests/test_hooks.py`
  invoked `subprocess.run([sys.executable, ".../cognitive_blueprint.py",
  "start"], cwd=tmp_path, capture_output=True)` without an explicit
  `env=` override. The hook subprocess inherited the operator's
  `CLAUDE_PROJECT_DIR` from the parent process, routing to the wrong
  path. The bug only surfaced when the operator's shell exported
  `ESPALIER_STOP_GATE=full`. Fixed by mandating
  `env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}` for every
  subprocess invocation of harness scripts in tests.

- *Env-var + lifecycle coupling.* Running `export ESPALIER_MAINTENANCE_MODE=1`
  mid-session inside Claude Code's Bash tool does not reach the
  already-running Claude Code process. Hook subprocesses spawn from
  the parent and see the variable unset; writes to protected harness
  paths are denied despite the operator believing maintenance mode
  is active. The variable must be set in the parent shell *before*
  launching Claude Code (`ESPALIER_MAINTENANCE_MODE=1 claude --continue`; PowerShell:
  `$env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue`).

- *Subprocess + platform coupling.* Pre-fix `_build_settings_json`
  emitted hook commands like `/usr/bin/python3 "$CLAUDE_PROJECT_DIR/tools/cc/hooks/X.py"`
  — failed on Windows (command not found) and macOS Homebrew (Python
  resolves at `/opt/homebrew/...`). Fixed by switching to Claude Code's
  exec-form: `"command": "python"` and `"args": ["${CLAUDE_PROJECT_DIR}/..."]`
  with no shell involved.

- *Bash variable-indirect expansion.* `write_guard.py` expands lines
  like `F=.claude/settings.json; echo > "$F"` by inlining `VAR=value`
  bindings in the same command before regex extraction. Hard scope: any
  shell name (bare or behind a declaration builtin), plain/single/double-
  quoted values, an assignment at a statement start (uppercase and
  same-line only until 2026-09-19). Out of scope: `$(...)`,
  `${VAR:-default}`, arrays, a second assignment in one statement.
  Expanding outside that scope produces over-broad blocks and false denies.

**Detection.** AST scanner per sub-category. Each registers a known
catalog of pinned contracts; live calls outside the catalog are
UNPINNED findings. Subprocess scanner walks
`subprocess.run/check_output/check_call/Popen/Popen.communicate`,
`os.system`, `os.popen`. Filesystem scanner walks
`.write_text/.write_bytes`, `json.dump/pickle.dump/yaml.dump`,
`with open(p, "w") as f: ...` blocks, and wrapper functions named
`atomic_write_*`. Env-var scanner greps every `os.environ.get("ESPALIER_*")`
against a documented catalog.

**Contract.** Either pin the surface (registry + sister test that
exercises the CLI / schema / env variable) or declare the contract
explicit (inline pragma plus reason). The five sub-categories are
not exhaustive; new coupling channels (named pipes, sockets, shared
memory) get their own scanner when they appear.

**Why it generates instances.** Imports are the language we use to
*talk* about coupling. Anything that couples WITHOUT an import is
invisible to our talking-about-coupling tools. The walls hold; the
doors don't show on the floor plan. Every new feature that adds
inter-module coordination tends to cut another door.

**Related.** §3.2 connascence. §9 platform-implicit coupling. §3.7
inappropriate layer leak.

---

### 1.3 Doc-surface propagation

**Signature.** A decision changed N-of-M doc sites. The remaining
M−N sites still describe the old state. The system works (live code
reflects the decision); the documentation is split-brain.

**Mental model.** A change of office address that hit the letterhead,
the website, and the business cards — but not the legal filings.
Most things route correctly. The residual creates a trust gap that
compounds.

**Industry analogs.** Shotgun surgery (Fowler 1999) applied to docs.
Documentation rot. Single-source-of-truth violation. DRY violation.

**Shapes.**
- Retired vocabulary surviving past its retirement pack.
- Numeric counts that propagated to N−1 of N documenting surfaces.
- Within-doc contradictions (one section says X, another says ¬X).
- Cross-doc contradictions (different doc files give incompatible
  facts).
- Folder-router pointers that resolve to wrong targets.
- Public-facing claims drift when no external witness binds them.

**In-repo examples.**

- *Untethered public claims.* A v0.6.0 audit found the README
  claimed "22 checks" when the live binary emitted 20, the QUICKSTART
  clone URL 404'd, the README's doctor demo showed a `summary` key
  the live binary doesn't emit, and `init`'s "Agents: N" printed
  a different number than a directory listing. None of these failed
  any test until the audit-accuracy framework was built. The fix:
  the `NumericContract` framework at `tests/test_documented_claims.py`
  binds each documented claim to a witness — either AST-extracted
  live output, or filesystem state.

- *Broad claims that drift.* The README once said "espalier governs
  Claude Code" without scope boundaries. Five audits across four
  months found 60+ surfaces espalier doesn't govern. First audit:
  21 drift items. Then 12, 9, 7, 11. The fix: replace the broad
  claim with a normative `docs/SURFACE_SUPPORT_MATRIX.md` (Espalier source
  repo; 20 rows,
  5 status categories) tested against public docs at pytest time.
  When a claim has a contract surface, it can't drift broader; it
  can only fail.

- *Parallel inventories drifting.* v0.6.0 shipped a 6 MB `project.zip`
  because two inventory tables —
  `surface_contract.RELEASE_NOISE_PATTERNS` and
  `release_check._TRACKED_NOISE_PATTERNS` — had no rule for top-level
  archives, even though `.gitignore` did. Fixed via one SoT
  (`espalier/release_noise.py`) plus a parity test against `.gitignore`.

- *Multi-surface command edits.* Deleting a command file and
  updating CLAUDE.md, LIVE_SURFACE.md, COMMANDS.md — but forgetting
  CHEAT-SHEET.md and PACK_MANIFEST.txt — leaves stale references
  that confuse readers and break the integrity check. Mitigation:
  any command add/remove is followed by a grep for the command name
  across all five surfaces.

- *Stale config matchers post-upgrade.* Upgrading from pre-v0.7
  leaves an operator's `.claude/settings.json` with a narrowed
  PreToolUse matcher (`"Write|Edit|..."` rather than `"*"`), so
  Task/TodoWrite/SlashCommand dispatches bypass `write_guard`
  entirely. Fixed by detecting the stale matcher in `cmd_init` and
  emitting a `[WARN]` directing the operator to delete
  `.claude/settings.json` and re-run `espalier init .`.

**Detection.** Closed-vocabulary registry of retired terms plus
scanner that walks doc surfaces flagging occurrences outside allowed
historical contexts. Numeric drift caught by `NumericContract`
registry. Five-surface grep enforced as part of command-add/remove
workflow.

**Contract.** Every vocabulary retirement and every multi-surface
numeric must register itself. The registry is self-documenting
provenance (which pack retired the term) plus auditable exceptions.
Every claim is bound to a witness — external pin, AST extraction
from live binary, or filesystem state.

**Why it generates instances.** Most non-trivial decisions touch ≥3
doc surfaces. The retirement pack updates the load-bearing surface;
the others wait for someone to notice. Tests rarely fail on docs,
so doc drift is silent until an audit surfaces it.

**Related.** §4 entire category. §3.4 shotgun surgery. §1.4
canon-vs-claim (sister shape where the doc claim disagrees with the
canon rather than another doc).

---

### 1.4 Canon-vs-claim

**Signature.** The system measures something. The system also claims
something inconsistent with what it measured. Both statements coexist
in the repository; nothing surfaces the contradiction.

**Mental model.** A scale reading 200 lbs next to a chart that says
"patient weighs 180." Both are in the file. Neither has been updated
to reconcile. 

**Industry analogs.** Goodhart's law (1975) — when a measure becomes
a target it ceases to be a good measure. Vanity metrics (Eric Ries,
*The Lean Startup* 2011). Cargo-cult metrics (informal). No mainstream
SE term for the specific shape "measurement contradicts documented
claim."

**Shapes.**
- A canon (scanner, gate, signal) consistently returns results that
  contradict a documented invariant.
- A "Backed by:" line names a test that exists but doesn't actually
  exercise the named property.
- A claim path returns `unverifiable` by construction.
- A threshold set at the empirical historical mean (passes by
  construction, fails by impossibility).
- A default-mode configuration silently disables a documented behavior.
- An "accept and document" closure that closed the metric record
  but left the claim it refutes standing.
- Skill trigger-phrase claims a behavior fires; trigger detection is
  unreliable in practice so the claim is silently wrong most sessions.

**In-repo examples.**

- *Signal 1 refutes its top-3 invariant.* `espalier/scaffolding_canon.py`
  Signal 1 measures cross-session reasoning re-engagement: the fraction
  of session S's `continuation_fragments` whose body appears as
  substring in session S+1's `reasoning_entries`. The live-fire
  result is 0.0 across 17 pairs (and 0/85 across a prefix-sensitivity
  sweep). The documented threshold for "real" is `Mean < 0.10`. The
  threshold is breached. Meanwhile CLAUDE.md lists "Session continuity
  (blueprints and memory must be maintained)" as the priority-3
  invariant. The harness's own canon refutes one of its top-3
  declared invariants. The fix is to update the claim to match the
  measurement, not to hide the measurement.

- *Skill triggering reliability.* Skills activate via trigger-phrase
  detection in the description frontmatter. In practice, triggers
  fire unreliably — a skill registered to handle "X" may silently
  no-fire when the operator types something that should match. The
  decision boundary documented in SHARP_EDGES: skills over 50 lines
  that run less than once per session should be skills; workflow-
  essential under 50 lines (`/preflight`, `/commit`) stay as commands
  for deterministic invocation. The claim "X triggers Y" is a
  canon-vs-claim risk whenever trigger reliability is below ~70%.

- *Gate-1 dormancy on non-pytest fingerprints.* When
  `reports/repo_fingerprint.json::test_commands` contains non-pytest
  commands (e.g., `go test`, `npm test`), the Stop hook's Gate 1
  previously fell back to invoking pytest in adopter repos, which
  returned `collected 0 items` and passed silently. The claim "Gate 1
  enforces tests" was true on Python repos and false everywhere else.
  Fixed by returning a tri-state with
  `status in {"ok", "dormant_non_pytest", ...}` and a stderr warning.

- *Hook wiring vs. file existence.* Adding a new hook script under
  `tools/cc/hooks/` but forgetting to register it in
  `.claude/settings.json` leaves the file unused. The CLAUDE.md
  claim "10 hooks operate" is canon-true at the file level and
  canon-false at the wiring level. Fixed by an integrity audit
  walking the canonical hook wiring against both the file inventory
  and the settings.json registration.

- *"Active" predicate including a closed state.* See §1.8
  predicate-name semantics creep — a closely related shape where
  the canon's NAME claims one semantic and the implementation provides
  a looser one.

- *JSON in a description field.* An earlier proposal floated an
  `action_justification` blueprint kind that would carry a JSON blob
  inside the `description:` field. `_sanitize_for_priming` truncates
  descriptions at 200 chars — the JSON would be cut mid-key, the
  next session's load would fire `JSONDecodeError`, and the fragment
  would silently drop. The claim "structured reasoning is preserved"
  would be canon-false. Fixed by adding a typed
  `action_justifications: list[ActionJustification]` field with eight
  explicit columns and per-field length validators.

**Detection.** Walk every load-bearing claim; require an explicit
`<!-- canon: <id> -->` annotation pointing at a test that pins the
property, OR `<!-- canon: convention -->` for honest non-canon. For
canon-backed claims, verify the named test actually exercises the
claimed property (not just exists).

**Contract.** Bidirectional claim-id ↔ pins linking: doc claim
declares `<!-- claim-id: slug -->`, the canon-pinning test declares
`# pins: claim:slug`. Verifier enforces exact slug match. Threshold
adjustments that lower the bar to pass on near-historical data are
forbidden without explicit operator decision.

**Why it generates instances.** Measurement results live in metric
files / blueprint notes. Claims live in CLAUDE.md / README /
CONVENTIONS — the *front* of the system. The two surfaces are
reviewed by different cognitive modes (metrics by "is this number
right?", claims by "is this prose accurate?"). Nobody reviews them
*against each other*.

**Related.** §5 entire category. §1.1 convergence theater (special
sub-case where the canon and claim collapse into the same source).
§1.10 canon formula structural impossibility (sister shape where
the canon's output is meaningless by construction).

---

### 1.5 Relaxation-tightening contract drift

**Signature.** A contract or predicate is temporarily relaxed to
accept multiple forms (legacy + canonical) during a migration, then
tightened back to a single canonical form. Test fixtures and call
sites that passed during the relaxed window silently take different
code paths after tightening — sometimes failing on unrelated
preconditions, sometimes silently no-op'ing.

**Mental model.** A door that's propped open during a moving day,
then closed afterward. Furniture parked just beyond the threshold
during the open period gets locked outside; nobody notices until
they need it.

**Industry analogs.** Migration debt. Temporal coupling (Pragmatic
Programmer, 1999) — a sub-shape where the temporal ordering of
changes matters. No mainstream SE term for the specific
relaxation-then-tightening pattern.

**Shapes.**
- A predicate accepts `{old_name, new_name, transitional_alias}`
  during the rename pack; tests use the alias; tightening drops the
  alias and the tests strand.
- A schema validator accepts both fields during a JSON field rename;
  consumers continue emitting the old field after the validator
  tightens.
- A regex accepts both old and new path layouts during a directory
  reorganization; tightening exposes that some call sites still
  produce the old layout.

**In-repo example.** During the espalier-harness rename, `is_self_host_repo`
was relaxed to accept the legacy project name alongside `espalier-harness`
and `espalier`. Two test fixtures hard-coded `name = "espalier"` — a
value that was never actually used as a project name in any deployed
configuration. The fixtures passed because they hit the relaxed
predicate. Phase F of the rename tightened the predicate to
`{espalier-harness, espalier_harness}`. After tightening, the fixtures
hit the non-self-host code path. The downstream failure surfaced as
`missing required file: SECURITY.md` — an unrelated precondition that
only fires on non-self-host repos. The real cause (the rename
relaxation window had hidden the fact that `name = "espalier"` never
matched a real configuration) was masked.

**Detection.** When relaxing a contract, record the set of accepted
forms in a comment or constant. At tightening, grep every test fixture
and call site for each accepted form; convert any using the dropped
forms before tightening lands.

**Contract.** Two options. (a) Apply the rename atomically across all
fixtures and the contract simultaneously — no relaxation window. (b)
Maintain an explicit `_DEPRECATED_FORMS: tuple[str, ...]` constant
in the contract module with a sunset date; a parity test asserts no
caller uses any value from the deprecated set.

**Why it generates instances.** Relaxation is a kindness during
migration — but the kindness has a half-life. Once tightening
lands, anything that depended on the relaxed form is broken in a
shape that doesn't surface as "contract violation" but as "unrelated
downstream symptom." The original cause is two packs and one week
upstream; debugging walks the symptom, not the relaxation history.

**Related.** §1.3 doc-surface propagation (sister: docs can drift
across the same temporal window). §3.4 shotgun surgery.

---

### 1.6 Habit-formation against friction

**Signature.** A safety mechanism uses friction (a denial, a prefix,
a multi-step ceremony) to discourage an unsafe pattern. Operators
internalize the workaround anyway; the workaround gets baked into
committed scripts or muscle memory, where it later runs in contexts
the friction was designed to prevent and fails silently.

**Mental model.** A child gate at the top of the stairs. Adults
learn the special lift-and-step to clear it; toddlers eventually
learn the same motion. The gate now protects no one.

**Industry analogs.** Cognitive re-entrancy. "Workaround calcification"
(informal). The Linux community calls one variant "muscle memory
debt." No dominant term.

**Shapes.**
- A denial prefix that operators learn to bypass; the bypass becomes
  the default mental model.
- A confirmation prompt that gets `y`-mashed and ends up scripted as
  `yes | command`.
- A multi-step ceremony that gets aliased; the alias ships in
  someone's dotfiles and runs in CI.
- Inline env-var prefixes that work in one tool but not another;
  operators paste the pattern into the wrong tool.
- *Friction fires on MENTION, not just use.* A guard that denies any
  command merely CONTAINING a banned token (rather than its active use)
  blocks documenting, grepping, or committing about the token. The
  operator/AI cannot even write down why the token is dangerous without
  tripping the guard — so the reflex becomes "hide the token," not
  "learn the rule." In-repo: `write_guard._HARNESS_ENV_PREFIX_RE`
  (`write_guard.py::_HARNESS_ENV_PREFIX_RE`) used to match any in-string occurrence of
  `ESPALIER_MAINTENANCE_MODE=` **or** `ESPALIER_STOP_GATE=` (a two-token
  alternation), so `grep -rn "ESPALIER_MAINTENANCE_MODE=1"
  docs/` and `git commit -m "...ESPALIER_MAINTENANCE_MODE=1..."` were
  denied with a message that misattributes the cause. The fix is to
  anchor the regex to an actual leading inline-assignment position
  (command start / `env`-prefix / `;`/`&&` boundary) and exclude
  occurrences inside quoted strings — denying the dangerous *use* without
  blocking the harmless *mention*. The regex is now anchored to command
  position, so the dangerous *use* is denied while a bare *mention* —
  `grep` / `git commit` — passes; `bench/corpus` pins the use shape.

**In-repo example.** Espalier's `write_guard.py` denies Bash tool
calls that inline the `ESPALIER_MAINTENANCE_MODE=1 <cmd>` env-prefix
syntax. The denial fires because the env var has to be set before
launching Claude Code — it does not reach already-running hook
subprocesses if set mid-session. The intent of the denial is to teach
the correct mental model. But operators internalize the inline env-prefix
syntax from external Bash habits, paste it into the harness
Bash tool, hit the denial, paste it again into a committed script
where the denial doesn't fire (because committed scripts aren't
gated by `write_guard`). The script then ships, runs in a context
where maintenance mode isn't actually active, and fails silently.
The denial taught the wrong pattern by giving the operator the
satisfying experience of "I know the syntax" without delivering the
guarantee.

**Detection.** Post-PR audit of committed scripts for any pattern
the harness denies inline. Friction-layer testing that deliberately
exercises the incorrect-usage path and asserts the correct guidance
appears in the denial message.

**Contract.** Friction should be accompanied by explicit anti-pattern
examples in the denial message AND positive examples of the correct
form. "Don't do X (here's what it looks like); do Y instead (here's
what it looks like)." The asymmetry — denying without modeling —
creates the habit-formation trap.

**Why it generates instances.** Friction shapes behavior. If the
friction is silent ("nope") or generic ("denied for safety"), the
operator's reflex is to find a path around the friction, not to
internalize why the friction exists. The first reflex wins because
it's reinforced every time the friction fires.

**Related.** §11 AI-collaboration failure modes (the AI variant of
this is sycophancy + bypass-learning). §10.6 pragma escape-hatch
over-use (a specialization where the friction has an explicit bypass).

---

### 1.7 Gate tuning-to-HEAD blind spot

**Signature.** A pre-flight gate (enforcement probe, denylist, quality
canon, scanner) is authored or tuned against the current HEAD state
and ships clean. It will silently fail to catch the NEXT instance of
the debt it was designed to prevent because it was never validated
against a historical pre-state where that debt actually existed.

**Mental model.** A metal detector tuned and tested at an empty
threshold. It passes its self-test (zero alarms) and ships. The
first time a metal object actually crosses, the detector's behavior
is unknown — it might have been mis-tuned all along, but the
self-test couldn't tell.

**Industry analogs.** "Untested test." Cargo-cult test. The specific
shape — gates earned against post-cleanup state — has no dominant
industry name.

**Shapes.**
- A scanner that returns 0 findings on current HEAD because the
  problem it targets was just cleaned up; the operator declares the
  scanner working without ever validating it fires on a positive case.
- A denylist that passes against current `.gitignore` because all
  noise has already been removed.
- A quality canon that hits its threshold on current data because the
  data was recently massaged to clear the threshold.
- A regression test added to lock in a fix; the test was authored
  against the post-fix code and never run against the pre-fix code,
  so its discriminating power is unverified.

**In-repo example.** A sister-site probe (`sister_site_probe.py`)
was added to detect duplicate `_project_root` patterns across hook
scripts. The probe ran against current HEAD and reported zero
findings — because the consolidation pack had just landed and merged
the duplicates. The probe could have shipped with zero validation
of its detection capability. The "earn the gate" pattern made this
explicit: the probe was checked out against the pre-consolidation
git tag and run against the historical state where the duplicates
still existed. The probe correctly fired (reporting "9 sites" — the
pre-consolidation count). Only after that validation was the probe
trusted as a future gate. Without this step, the probe could have
been mis-tuned (wrong AST pattern, wrong file-glob scope, wrong
severity threshold) and nobody would have known until the next
generation of duplicates accumulated.

**Detection.** Before landing any gate, check it out against a known
pre-state commit and confirm it fires with the expected finding count.
Capture the historical finding output as a fixture file (e.g.,
`tests/fixtures/<scanner>_known_positives.txt`). A regression test
re-runs the scanner against the fixture and asserts the count.

**Contract.** Every new gate ships with an "earned against" comment
naming the historical commit it was validated on and the expected
finding count. The fixture file is committed alongside the gate.

**Why it generates instances.** Gates are usually added IMMEDIATELY
after fixing the debt they're supposed to prevent. The fix removes
the positive cases from HEAD. The gate is then validated against
HEAD (zero findings, passes) without ever being validated against
the state where the positive cases existed. The validation appears
clean but is structurally unverified.

**Related.** §5.6 dormant canon (sister: gates that exist but don't
run; this mode is gates that run but were never validated). §10.3
detector self-flagging.

---

### 1.8 Predicate-name semantics creep

**Signature.** A predicate named for strict semantics (`is_active`,
`has_active_X`, `is_valid_Y`) gradually accepts looser and looser
conditions in its implementation. The name's implication (active =
currently running) diverges from the predicate's behavior (active =
any recent state). Happy-path tests only exercise the strictly-true
case, so the leak is invisible.

**Mental model.** A doorbell button labeled "ring." Over time, someone
wires it to also ring on motion, then on email arrival, then on a
scheduled timer. The label still says "ring" but the meaning has
diffused. Visitors press the button expecting one thing; the system
does five.

**Industry analogs.** Naming-semantics drift. Stale interface. "Method
name lies" (informal). No dominant single term.

**Shapes.**
- `is_X()` returns True for states that aren't actually X but are
  "X-adjacent" (recently X, soon-to-be X, partially X).
- `has_active_X` returns True for `status in {active, complete,
  archived}` instead of just `active`.
- Validator names suggest strict checks but pass on transitional
  forms.

**In-repo example.** `plan_guard.py` had a function `_plan_exists`
that returned True for both `status='in_progress'` AND
`status='complete'`. The function was the predicate driving the
"writes require an active plan" gate. Because completed plans returned
True, the mutation window stayed open after a plan was finished —
silently. The function name (`_plan_exists`) was strictly accurate
("a plan exists in the file"), but the gate message and operator
mental model said "active plan." When the plan was complete, writes
proceeded without an active plan despite the gate's claim. The bug
shipped in v0.6.0 because no test parametrized across closed states
— all tests exercised the in-progress happy path. The fix tightened
the predicate to strictly in-progress, renamed it to `_has_active_plan`
(name now matches enforced semantic), and added parametrized tests
across the full state space: `status in {in_progress, complete,
missing, malformed, no-steps}`.

**Detection.** Parametrize tests across the full state space of the
predicate's input type — not just the happy path. For predicates
named with strict semantics, enumerate every state value and assert
the predicate's return per state explicitly.

**Contract.** Predicate names must be refactored or tightened when
the behavior changes. Never leave the name lying. A single source
of truth (`_plan_state_label`) drives both the predicate AND the
deny-reason text — the operator sees the same state label the
predicate is checking against.

**Why it generates instances.** Predicates accumulate scope. The
first version handles the obvious case. Edge cases get added later;
each addition feels small. The cumulative effect is a predicate
whose name has drifted from its behavior. Happy-path tests don't
catch the drift because they only exercise the obviously-strictly-true
input.

**Related.** §1.4 canon-vs-claim (the predicate's name is the
claim; the implementation is the canon; they disagree). §4.3 stale
comments.

---

### 1.9 Nested file-existence trap

**Signature.** Suggestion / initialization / safety logic gated on
`if file.exists()` skips its work when the file is absent. Absence
is the exact case where the user needs the suggestion most — but
the absence branch is treated as "skip this check."

**Mental model.** A "did you remember your keys?" sign at the front
door that only triggers if it detects keys in your pocket. People
who left their keys inside walk right past it.

**Industry analogs.** Dual-case logic inversion. No dominant term;
"happy-path-only check" comes close.

**Shapes.**
- `if config.exists(): suggest_X()` — fresh repos with no config
  miss the suggestion entirely.
- `if not file.exists(): return` — early return swallows the case
  that needs handling.
- `try: open(f); ... except FileNotFoundError: pass` — silent
  swallow of the absence case.

**In-repo example.** Pre-fix the gitignore handler (`REQUIRED_GITIGNORE`
in `espalier/cli.py`) was gated on `gitignore.exists()`. A fresh repository (no `.gitignore`
present) hit the conditional and skipped the entire suggestion
block. The user saw nothing. A subsequent `git add -A` after init
then staged four machine-specific files —
`.claude/settings.json`, `.espalier/integrity.json`,
`reports/harness_config.json`, `reports/repo_fingerprint.json` —
none of which should have been committed. The suggestion that would
have prompted the user to create a `.gitignore` was gated on the
file the user lacked. Fixed by running the suggestion logic
unconditionally; only the *phrasing* depends on whether the file
exists ("Add to your existing .gitignore" vs "Create a .gitignore").

**Detection.** Grep for `if .*\.exists()` patterns in init /
suggestion / safety code. For each, ask: "what's the right behavior
when the file is absent?" If the answer is "the user needs this MORE,
not less," the gate is inverted.

**Contract.** Suggestion logic runs unconditionally. Only the prompt
text depends on existence. Helpful errors prefer to over-suggest than
silently skip.

**Why it generates instances.** The natural reflex when writing a
"check if X exists" branch is to treat existence as the precondition.
That mental model works for read paths ("can I read this file?") but
inverts for suggestion paths ("should I tell the user about this
file?"). The two paths share the `.exists()` check but want opposite
behaviors on the absence branch.

**Related.** §10.4 hook fail-open via uncaught exception (sister
shape: error path treated as success path). §1.6 habit-formation
against friction.

---

### 1.10 Canon formula structural impossibility

**Signature.** A quality canon's formula is structurally impossible
to satisfy: its left-hand side and right-hand side derive from
disjoint code paths that can never align. The canon passes on current
HEAD by accident (or returns 0.0) but would silently miss any real
regression because the formula doesn't measure what it claims to.

**Mental model.** A thermometer that reads ambient air temperature
but is labeled "patient temperature." It produces a number; the
number is meaningful (the room is 72°F); but the relationship
between the number and the labeled quantity is broken. Doctors
trust the label and prescribe based on the wrong reading.

**Industry analogs.** "Wrong-quantity metric." Domain-mismatch
impossibility. No dominant SE term — related to Goodhart's law and
vanity metrics but structurally distinct (those measure something
real that diverges from intent; this measures something disjoint
from intent by construction).

**Shapes.**
- A canon's LHS derives from data set A; its RHS derives from data
  set B; A and B are produced at different lifecycle points and
  can never overlap.
- A canon expects to find substring X in Y, but X is normalized
  before storage and Y is read raw — the substring can never match.
- A canon computes a ratio whose numerator and denominator come
  from different aggregation windows.

**In-repo example.** A v2 proposal for the scaffolding-quality canon's
Signal 1 formula was `S.reasoning ∈ S+1.fragments` — the fraction of
session S's reasoning entries that appear as substring in session S+1's
continuation fragments. This formula is structurally impossible. The
function `auto_continuation_fragments(bp)` at
`espalier/cognitive_blueprint.py` derives S+1's fragments from S+1's OWN
decisions/patterns at S+1's finalize step — not from S's hand-off.
There is no code path that places S's reasoning into S+1's fragments;
the proposed formula would always return 0.0 not because re-engagement
is broken but because the formula's LHS and RHS come from disjoint
producer flows. The correct form is the reverse:
`S.fragments ∈ S+1.reasoning` (strip the `[tag] ` prefix; check
whether S's curated highlights appear as substring in S+1's
reasoning_entries text). A live-fire validation caught the
inverted formula before it shipped. Without that validation the
canon would have read 0.0 forever, the operator would have adjusted
the threshold downward to "make it pass," and the harness would
have shipped a credibility-zero quality metric.

**Detection.** AST-trace the canon formula's LHS and RHS through
their respective producer code paths. If the two paths originate
in different lifecycle points (different finalize / persist / read
boundaries) and there is no code path moving data from one to the
other, the formula is impossible. Run live-fire validation against
a known-historical state where the canon SHOULD report a non-zero
value; if it doesn't, investigate the formula structure before
adjusting thresholds.

**Contract.** When a canon's value is implausible (consistently 0,
consistently 1, narrow distribution far from declared threshold),
the FIRST diagnostic is to investigate the formula structure and
the producer/consumer code paths — NOT to adjust the threshold.
Threshold adjustments before formula validation hide the impossibility
behind a more permissive bar.

**Why it generates instances.** Canon authors typically reason about
the conceptual property they want to measure ("re-engagement of
prior reasoning") and write a formula that LOOKS like it captures
the property. They don't always trace the actual producer flows
that emit the data. The formula and the producer flows are written
by different humans (or the same human at different times); the
mismatch is invisible until live-fire runs.

**Related.** §1.4 canon-vs-claim (the canon's output contradicts
the documented claim; this mode is a special sub-case where the
canon couldn't have measured the claim even in principle). §5.4
self-verifying canon.

---

### 1.11 Gate credibility (authoritative gate green on a red tree)

**Signature.** An authoritative pre-flight gate (release check, smoke,
audit) reports PASS on a commit whose own ground truth — the test suite
it claims to summarize, or the artifact it claims to validate — is RED.
The gate enumerates a SUBSET of the truth surfaces, so a failure on a
surface it doesn't wire to is invisible to it.

**Mental model.** A pre-flight inspection that signs off the aircraft
while a warning light it was never wired to read is lit on the panel.
The sign-off is sincere; the wiring is the lie.

**Industry analogs.** Goodhart's law (the gate becomes the target).
"Green build, broken product." No dominant SE term for the specific
shape "authoritative gate passes on a ground-truth-failing HEAD."

**Shapes.**
- A release gate checks version consistency across SOME files but not
  all version surfaces; a skew on an unlisted surface ships.
- A "tests pass" gate runs a marker-filtered subset; a failure in the
  excluded set is green at the gate, red in CI.
- A smoke check greps a rendered artifact for a table the renderer
  doesn't produce — the check is a silent no-op (always green).
- A doc-claim gate pins N of M claim surfaces; the M−N drift freely.
- **The gate's acceptance criterion is a LITERAL STRING lifted from the
  population it grades — so that population's current defect *satisfies* it,
  and fixing the defect is what turns the gate red.** Measured 2026-08-22: a
  denial-message actionability check accepted the literal phrase `narrow the
  target` as proof that a denial names a concrete next step. On one of the two
  shells the matcher denied every target, so that phrase named an action **no
  input could perform** — the gate built to keep denial messages honest was
  accepting the dishonest phrase as its evidence. Correcting the message
  reddened the gate. Distinct from the subset shapes above: the wiring is
  complete and the criterion itself is wrong, having been derived from the
  artifact rather than from the property. **Hunt it by grepping gates for
  literal-string acceptance tokens and asking, for each, whether the string
  proves the property or merely quotes today's output.**
- *Binding-coverage erosion (N-of-M where N shrinks, M grows).* A
  hardening pass drops a noisy/auto-pruned surface from a count
  contract's `sources` tuple instead of fixing it; the now-unbound
  surface re-drifts silently while new doc surfaces accrete unbound.
- *Absence-as-allow.* A completeness oracle iterates the keys PRESENT in
  a live config and validates each, holding no expected-complete
  reference to diff against; a DELETED key (or a malformed config that
  early-returns `[]`) drops out of the iteration domain, so absence
  reads as ALLOW.

**In-repo example.** At the v0.8.0a12 cut, `bench/RESULTS.md` (Espalier
source repo) was
stamped `0.8.0a11` while `pyproject.toml` and `espalier/__init__.py`
were `0.8.0a12`. Two parity tests fail, so `pytest -q` (CI's command,
and the documented full-suite command) is RED on `main`. Yet
`scripts/release_check.py::check_version_consistent` inspects only the
CHANGELOG, so `release_check OK` prints on the red tree. The gate that
exists to certify release-readiness certifies a tree that fails its own
tests. The multi-angle audit that found this instanced the shape
repeatedly — the version skew, the `/smoke` no-op checks, the
`memory-tag-parity` job that can't run on adopters — but the catalog had
no §-class naming it; this entry is that class.

**Detection.** For every authoritative gate, ask: "does it actually
run, or assert against, the full ground truth it claims to summarize?"
Earn the gate against a deliberately-failing HEAD — a gate that has
never been observed to go red has undemonstrated discriminating power
(§1.7). Bind the gate's surface list to a single registry (§4.5) so
"the gate's surfaces" and "the truth's surfaces" cannot diverge.

**Contract.** The authoritative gate fails when ground truth fails: the
release check goes red if the suite is red; the version check enumerates
from the same `VERSION_SURFACES`-style registry the parity test uses;
the smoke check reads the same SoT the renderer writes. Every gate ships
with an earn-the-red demonstration (skew a surface, observe the gate
fail) committed as proof.

**Related.** §1.7 gate tuning-to-HEAD (the gate was never validated
against a positive/red case). §5.4 self-verifying canon. §5.6 dormant
canon (a gate that doesn't run; this is a gate that runs but reads the
wrong surface). §14.3 README/RESULTS credibility gap (the public-facing
instance of the same divergence).

**Inverse-polarity instance — corpus scope-metadata drift.** A regression/
benchmark corpus tags each case with `in_scope` AND `expected_outcome=blocked`,
and a gate asserts the enforcer blocks every in-scope case. Cases enter the
in-scope set carrying `expected=blocked` faster than the enforcer (or its runner
wiring) learns to block them, so the all-in-scope-blocked predicate becomes
unsatisfiable and the gate goes permanently RED — and because the corpus is ALSO
the public marketing surface, the contradiction reads as "the harness is broken"
rather than "the corpus over-claims." (This is the §1.11 polarity flipped: not
green-on-a-subset but red-by-construction. In-repo: `bench/run_benchmark.py`
required N/N while in-scope attempts used verifier names the espalier invoker map
never wired.) Sister-link: §14.3 README/RESULTS credibility gap.

**Absence-polarity instance — deleted-event completeness oracle.** A
governance-completeness oracle iterated the hook entries PRESENT in a
live `.claude/settings.json`, validating each — but held no
expected-complete reference, so deleting an entire blocking-event key
(the only `ConfigChange`/config_guard DENY, say) dropped that event out
of the iteration domain and the oracle reported clean. Absence read as
ALLOW; a malformed (non-dict) settings file that early-returned `[]` did
the same. The fix iterates the SoT, not the present set:
`harness_config.GOVERNANCE_BLOCKING_HOOKS` is the expected-complete
reference, and `espalier/doctor.py` plus the zero-import
`tools/cc/ci_guard.py` each walk it and fail-closed on a malformed config.
Distinct from the
green-on-a-subset shape above: the gate is complete over what it SEES,
but what it sees is the present set, which a deletion silently shrinks.

**Binding-coverage-erosion instance — count gate where N shrinks, M
grows.** A multi-surface numeric (the `DENIED_PATTERNS` count in
`espalier/release_denylist.py`) was bound on exactly one surface
(`docs/SHARP_EDGES.md`, pinned by `tests/test_release_denylist.py`) while
three other surfaces restating it drifted freely —
`docs/FAILURE_MODES.md`, `docs/REDEFINED_INFORMATION_REGISTRY.md` (Espalier
source repo), and
`ESPALIER_MEMORY.md` each carried a stale value. The `NumericContract` that should
have caught it existed with the right `expected_value` but listed only
the one bound surface in its `sources`; a prior pass had REMOVED
`ESPALIER_MEMORY.md` from a sibling contract's `sources` with the rationale "no
longer a reliable signal-count surface" rather than re-binding it. The
drift survived a 71-finding hardening pass that flagged it, *because
nothing bound it*. Fix: a commit that removes a `sources` entry must
delete/normalize the surface or re-bind it elsewhere — never leave it
unbound.

---

### 1.12 Sister-predicate domain blindness

**Signature.** Two predicates declared to "agree" are aligned by a consolidation
pack on the cell that motivated it (and a regression test is added for THAT
cell), but their implementations still diverge on a DIFFERENT cell no party
enumerated — the non-dict / malformed-parse cell, or a future status value. The
truth-table / state-machine registry meant to be the mechanical backstop has a
hand-curated `domain` tuple missing exactly the divergent cell AND registers
only the canonical predicate, so the "every predicate covers full domain"
contract passes green while the real divergence ships.

**Mental model.** Two clerks told to "apply the same rule." They're checked
against a list of the cases someone thought of — but the list is the same list
that omits the case where they disagree.

**Industry analogs.** Incomplete case analysis. Missing `default:` branch.
Connascence of algorithm (Page-Jones) without a shared implementation.

**In-repo example.** `plan_guard` handles a non-dict parse safely: its
`_plan_state_label` helper (which `_has_active_plan` delegates to) returns
`"malformed"` for a non-dict JSON value (plan_guard.py:398), and `main` sits
under an umbrella try/except. Its twin `task_router._has_active_plan`
(`tools/cc/hooks/task_router.py`) caught only `(JSONDecodeError, OSError)` then called
`data.get(...)` — so a valid-JSON non-dict (`[{...}]`) raised `AttributeError`,
crashing the UserPromptSubmit hook (exit 1, fail-open). An earlier fix aligned the twins
on the empty-`steps` cell and added a regression test for it; the non-dict cell
was never enumerated. `tests/_state_machines.py` declared the plan-status
domain as `(in_progress, complete, blocked, missing)` — neither the no-steps
cell that fix covered nor the non-dict crash cell was in it — and the predicates
registry bound only plan_guard's predicate, never task_router's twin. The fix:
isinstance guard + umbrella on the twin, the non-dict cell added to
both predicate truth tables, the sister predicate registered, and a parametrized
test that *executes* both predicates on the same non-dict input.

**Second in-repo example (silent-no-op, parser pair — no state machine).**
`espalier/pack_manifest.py` recognizes pack headings with two sister functions,
`parse_scope_in` and `parse_affected_symbols`. Scope-in was widened to
tolerate a numbered heading (`## 3. Scope (in)`) via the prefix idiom
`(?m)^#{2,3}\s+(?:\d+\.\s+)?…`, but left affected-symbols on the bare
`## Affected symbols` form. Every real pack numbers its headings, so
`parse_affected_symbols` returned `[]` on every numbered pack — `scope-check`, a
governance pre-flight, was a **structural no-op for an unknown duration**, and it
exited with *"no Affected symbols section"*: a message that reads as
pack-authoring guidance, not a tool bug, actively misdirecting diagnosis. Unlike
the plan_guard/task_router crash above, **nothing raised** — the divergence is a
0-result silent pass. The backstop §1.12 normally prescribes (a domain tuple + a
sister-predicate registry) has no analog for parsers; the equivalent is (a) ONE
shared heading-prefix constant the parsers derive from instead of the
`(?:\d+\.\s+)?` idiom hand-duplicated across the scope-in, scope-out, and
affected-symbols patterns, and (b) a *parity* test driving BOTH parsers on the
same numbered/unnumbered fixtures. A later fix widened the affected-symbols pattern
and added a per-parser test — but not the parity test or the shared constant, the
same lockstep gap that produced the bug (both were still owed when this was
written). _Annotated 2026-09-14: both shipped since — the shared constant is
`espalier/pack_manifest.py::_HEADING_PREFIX`, which `cli.py`'s literals parser
derives from, and `tests/test_pack_manifest.py::TestHeadingPrefixParity` drives
every section parser on the same numbered and unnumbered fixtures._

**Third shape: two classifiers of one string, differing only in where they
look.** Two readers answered the same yes/no about an interpreter's version
banner — one searched the whole output for the version token, the other tested a
prefix of the stripped output — so an interpreter whose wrapper prints a line
before its banner was "a version 3 below the floor" to one reader and "not a
version 3" to the other, and the setup command printed both *the guards keep
working* and *the guards fail open* about that one interpreter in one run.
Neither reader was parsing a marker and no domain tuple would have enumerated
it: the question itself had two homes. When two modules answer the same yes/no
about one string, give the question **one owner** every reader routes through,
mirror it across the library/hook boundary under a parity pin, and pin agreement
with a driven corpus that includes the awkward spelling — here, a banner with a
line in front of it. The symptom to watch for is neither a crash nor a zero
result: it is **one command contradicting itself about one input**.

**Detection.** For each state field read by >1 predicate, assert the declared
`domain` includes the structural-malformity cells (non-dict, non-parse) AND that
every sister predicate appears in `field.predicates`. For sister **parsers** that
recognize the same structural marker (heading shape, delimiter, prefix), the
parser analog of the domain tuple is a single shared pattern/constant; a
hand-duplicated regex idiom across N call sites is an N-way domain one widening
can desync. Add a parity test driving every sister parser with the same
marker-shape fixtures (numbered/unnumbered, h2/h3).

**Contract.** Domains for shared state fields MUST enumerate the malformed/
non-dict/unparseable cells; every sister predicate is registered; a parametrized
test drives ALL sister predicates with the SAME inputs across the full domain.
For sister **parsers**: when one is widened to accept a new marker shape, widen
the others in the SAME commit or extract the shape to one constant — and pin it
with a *parity* test, not a single-parser regression test. A 0-result on a
pre-flight whose failure message reads as user guidance is the silent-no-op tell.

**Related.** §1.8 predicate-name semantics creep (one predicate's NAME drifts —
distinct: here the locus is the registry's domain omission + an unregistered
sister). §1.11 gate credibility (a structurally-defeated pre-flight reporting
clean is the silent-no-op shape; this is its sister-parser cause). §5.4
self-verifying canon. §10.4 hook fail-open. §1.7 gate tuning-to-HEAD.

---

### 1.13 Autoimmune regression (born-weak guard)

**Signature.** A pattern-based guard (scanner, lint, "make sure this never
happens again" test) fires on the very material that *defines* the pattern it
prohibits — the catalog entry, the task pack, the FAILURE_MODES coinage —
because that material must contain the pattern in order to describe it. Whoever
resolves the red (increasingly an agent) carves out an exception that is too
broad, located in the wrong layer (scanner *core* rather than a corpus
boundary), and emits no signal. The guard stays green and still "exists," but
its effective coverage has silently, permanently shrunk. Two harms, kept
separate: **Harm A — collision** (the guard fires on benign seed material; a
*false positive* on self — annoying, not dangerous) and **Harm B — silent
permanent weakening** (the carve-out over-suppresses; a *false negative*
introduced by the fix). Harm B is the real failure and a **doc-truth
violation**: the contract says "ensure X never recurs," the behavior says
"…except anything resembling the seed" — and it survives review precisely
because the guard looks present, runs, and passes.

**Mental model.** An immune system that misfires on the body's own tissue — the
documentation of the disease — and a treatment for that misfire that suppresses
the immune response so far it can no longer detect the real pathogen. The name
captures both halves: the autoimmune trigger, and the over-suppression that is
its "cure."

**Industry analogs.** Goodhart's law / specification gaming (the parent class:
"test passes" became the target instead of "test correctly guards").
Secret-scanner fixture collision (the *established, solved* version of Harm A
*only* — gitleaks / trufflehog ship fixtures full of fake credentials their own
engines would flag, and handle it with fixture isolation + per-finding
allowlists). Test tampering / assertion erosion (Harm B is a species, with the
distinguishing twist that the **seed material itself supplies the pretext** for
the erosion — pretextual weakening is the kind that passes human review).

**In-repo example (the defenses converged; the harm is unmeasured).** Espalier
independently derived this mode's defenses before the concept was named: (1) the
**paired-fixture parity contracts**
(`tests/test_scanner_negative_corpus_parity.py` + `…_earn_the_gate_parity.py`)
make every scanner own its trigger via `tests/fixtures/<scanner>_positives` /
`_negatives` and forbid it from scanning its own defining material
(`EXEMPT_PREFIXES = ("tests/fixtures/",)`) — this *dissolves Harm A*; (2) the
per-scanner exemption caps (`MAX_EXEMPT_PREFIXES` / `MAX_EXEMPT_FILES` /
`MAX_PRAGMA_COUNT` — each scanner carries the subset it needs, not all three)
make every exemption a deliberate, git-visible act (raising a cap surfaces the
debt) — *distributed-capped exemptions are safer here than a single shared
boundary*, which would itself be the over-suppression vector (one added prefix
blinds every scanner at once); (3) `CP-GATEWEAKEN` (`tools/cc/hooks/_speedbump.py`)
is `cap_exempt=True` and fires even under maintenance mode — the **recursive-risk
principle made live** (the keystone meta-guard is never itself budget-suppressed).
The one *uncovered* slice — a guard + a same-material suppression *born together*
in one change to scanner/test material — is now **measured, not blocked** by the
born-weak observer (`post_write_check`, self-host-gated, OBSERVE-ONLY, logging to
`.espalier-state/born_weak_observations.jsonl`). Magnitude is **unmeasured**:
zero recorded instances in git history — which is *why* the enforcing form stays
demoted (see §C.4 of `docs/RELEASE_FINDINGS_LEDGER.md`, Espalier source repo — not deployed by `init`).

**Detection (the fingerprint).** A guard is added AND a suppression / exclusion
referencing the same material is added **in the same change**, without a paired
must-NOT-trip negative fixture proving the guard still fires on a non-exempt
twin. A guard that arrives pre-defanged. This co-occurrence — rare in honest
work — is the diagnostic signature of Harm B, and is what the born-weak observer
counts.

**Invariants (definition of an autoimmune-resistant guard).** A guard is
autoimmune-resistant iff: (1) **it owns its trigger** — asserts detection on
scoped synthetic fixtures, never scans its own defining material; (2) **any
suppression is scoped, justified, and correctly located** — narrow match,
required reason string, in the corpus-boundary config, never in scanner core;
(3) **weakening it emits a visible event**; (4) **it cannot be born and narrowed
in the same change**; (5) **its contract is machine-checkable against its
effective behavior** (doc-truth). These are the definition-of-done any new guard
should pass — folded into the SHARP_EDGES scanner-fixture entries as their
conceptual parent.

**Contract (enforcement is observe-first).** Under the workflow-partner
governing frame (threat = operator/AI *mistakes* not malice; false-positives /
friction OUTRANK closing bypass classes), a *blocking* born-weak guard is
rejected — "guard + suppression born together" is overwhelmingly the
**competent** pattern when no adversary is present (it is Espalier's own mandated
convention: every scanner ships a fixture + an EXEMPT carve-out in one change),
so a block would red-flag the repo's own definition-of-done and would be the
sixth deny-predicate revert (§6.10; ledger §D records the five). The sanctioned posture is:
own-the-trigger + caps + visible weakening events, and **measure** the Harm-B
base rate before any enforcing form ships. Promotion past observe-only requires
data, not a plausible mechanism (direction ≠ magnitude — the epistemic core; §5 measure).

**Related.** §1.1 convergence theater (a guard that fakes passing status — the
sibling "looks-green" mode). §1.7 gate tuning-to-HEAD (a guard validated only on
current state). §1.11 gate credibility (a structurally-defeated guard reporting
clean). §2 test/assertion weakening. §5 self-verifying canon. §10.4 hook
fail-open.

---

## 2. Test and assertion failure modes

### 2.1 Mock drift

**Signature.** Mocked dependency diverges from the real one without
the test catching it. Mock returns the shape the real producer USED
to emit before a refactor; tests pass; production fails.

**Industry analog.** Mock drift; brittle mock; over-mocking.

**Detection.** Integration tests against real dependencies on a
schedule. Contract tests exercising the real producer to assert the
mock's expected shape matches.

**Contract.** Schema-parity test between mock fixture and real
producer. Mocks at process boundaries only; never within the same
module.

**Related.** §2.7 fixture drift. §1.1 convergence theater (when the
mock IS the test, both halves can converge).

---

### 2.2 Brittle assertion

**Signature.** Test over-specifies implementation details; breaks on
refactor that preserves observable behavior.

**Example.** `assert response.body == "exact string with timestamp"`
when the timestamp is irrelevant. A change to the timestamp format
breaks the test even though the response is correct.

**Industry analog.** Brittle test (Fowler, *Refactoring*).

**Detection.** Code review checklist item. Watch for tests that
break on refactors that didn't change observable behavior.

**Contract.** Assert on behavior, not representation. Use matchers
that ignore irrelevant fields. Prefer "contains" over "equals" for
prose outputs. Scope that containment to the line the change owns: a
token asserted against a whole captured stream can be satisfied by an
unrelated line the change never touched, which is the same false pass
with the looseness moved from the comparison to the population.

---

### 2.3 Coverage trap

**Signature.** High line/branch coverage with weak assertions. Code
executes during tests but nothing meaningful is checked.

**Example.** Test calls a function and asserts no exception was
thrown, without verifying the function's actual output or side effect.
Coverage report shows 100%; the function could return any value and
the test would pass.

**Industry analog.** Goodhart's law applied to coverage. "Test
coverage is not test quality" (informal).

**Detection.** Mutation testing — flip a constant, run tests; if
tests still pass, coverage is theater. Code review for assert density.

**Contract.** Require at least N meaningful assertions per test. Run
mutation testing on critical paths in CI.

**Related.** §5.2 Goodhart's law. §1.1 convergence theater.

---

### 2.4 Flakiness

**Signature.** Test passes or fails non-deterministically given the
same code.

**Sub-shapes.** Race conditions in async tests; time-of-day dependence;
shared global state; non-deterministic iteration order; flaky network;
filesystem timing variation; clock-skew-sensitive comparisons.

**Industry analog.** Flaky test. "Don't ignore failing tests" (Kent
Beck).

**Detection.** Retry-loop in CI; track per-test pass rate over many
runs.

**Contract.** A test that fails once in N runs is broken, not
unreliable. Quarantine, fix, restore. Retries-as-mitigation hide
the underlying non-determinism.

---

### 2.5 Slow-test escape

**Signature.** A test is marked `@slow` (or `@integration`, or
excluded from default run) to keep CI fast. Subsequent regressions
go undetected because the slow test no longer runs by default.

**In-repo example.** A pack removed a `clean-generated` CLI flag (the
old explicit dry-run flag; dry-run is now the default). A slow +
integration-tagged test
(`tests/test_managed_cleanup_parity._run_clean`) was still passing
the flag in its invocation. The Stop hook's non-slow filter ran
green because it skipped the slow tests. A code review caught the
breakage post-merge, only because a human happened to read the
test fixture. The pattern: any pack that removes a CLI flag must
run `pytest -m slow` once before declaring victory, because the
default-suite filter routinely excludes integration tests that
exercise CLI surfaces.

**Detection.** Periodic full-suite run (including slow tests) on a
schedule; diff against default-suite results to flag regressions
hidden behind markers.

**Contract.** Any pack that removes a CLI flag or renames a function
must run the full suite (including slow + integration markers) once
before declaring victory. A self-grep — "is this symbol used
anywhere?" — is necessary but not sufficient.

**Related.** §5.6 dormant canon. §1.7 gate tuning-to-HEAD blind spot.

---

### 2.6 Test pollution

**Signature.** Tests interact through shared global state — order of
execution affects results.

**Industry analog.** Test interdependence; order-dependent test.

**Detection.** Random test order in CI (e.g., `pytest-randomly`);
parallel execution via `pytest-xdist` surfaces races.

**Contract.** Each test sets up its own state, uses `tmp_path`
fixture for filesystem isolation, never mutates module-level globals.
Singleton state (caches, registries) reset in a fixture teardown.

---

### 2.7 Fixture drift

**Signature.** A fixture's output shape diverges from what the
production-side producer emits. Tests use the fixture; production
uses the producer. Bug shape matches the fixture shape, so the test
passes; bug shape doesn't match production, so the bug ships.

**In-repo example.** The Stop hook's Gate 1 calls a helper
`_resolve_core_tests` that loads test commands from
`reports/repo_fingerprint.json`. A unit test
`test_resolves_from_fingerprint_when_present` fabricated `test_commands`
fixtures with shape `["tests/test_foo.py", "tests/test_bar.py"]` —
file path lists. The producer `espalier.analyze.detect_tests` never
emits this shape; it writes shell strings (`"pytest -q"`). Gate 1
silently no-oped on every host repo because the fixture-shape was
never what production produces. The fix: a parity test
(`test_resolves_from_real_fingerprint_output`) drives
`_resolve_core_tests` with REAL output from the producer via the
`initialized_repo_root` fixture, asserting the helper handles the
real shape correctly.

**Detection.** Parity test that drives test code with REAL producer
output, not hand-fabricated shapes.

**Contract.** Fixtures derived from real producer output, not
hand-fabricated. If a fixture must be hand-built, a parity test
asserts the hand-built shape matches the producer's contract.

**Related.** §5.7 producer/consumer parity drift. §2.1 mock drift.

### 2.8 Lock-test narrower than its class (false-green sibling mask)

**Signature.** A one-site fix is locked by a contract test scoped to
*that one site*. The assertion is strong and the test is green — but the
defect is a **class** with sibling sites the test never reaches, so the
green reads "class closed" while the siblings ship broken. The strength
of the assertion disguises the narrowness of its scope.

**In-repo example.** A fix closed the directory-symlink-following
`rglob` in `analyze._iter_files` and locked it with
`test_analyze_symlink_safe_walk.py` scoped to `_iter_files` alone. The
green CI matrix (which *does* run 3.10/3.11/3.12) and the green lock test
both read "closed" — but 42 sibling bare-`rglob` sites across the engine,
the scanners, `tools/cc/`, and the `_vendor/` mirror stayed broken, four
of them on the same `fingerprint_repo` first-run path the fix protected.
The dev host (3.14) could not reproduce the crash either. A follow-up swept
the whole class and replaced the narrow lock with a **structural
recurrence guard** (§10): an AST scanner that flags *every* unannotated
bare recursive walk, so the lock now covers the class, not one site.

*Second instance.* An `except` was widened to catch
`UnicodeDecodeError` in two of the four `latest.json` readers (`post_compact`,
`post_write_check`); `task_router`'s two readers of the **same file** were the
unswept siblings — green because nobody re-grepped every reader of that path
when widening the format's error handling. Lesson: when you widen an `except`
for a file *format*, grep every reader of that path, not just the one you
touched.

> Scanner blind spot worth naming: the guard detects a `glob` only when
> its pattern is a string *literal* containing `**`. A `glob(pattern)`
> whose pattern is a runtime **variable** (e.g. `freshness.discover_fragments`
> iterating an allowlist) is invisible to the static check and must be
> converted by hand — the guard is a recurrence net, not a completeness
> proof.

**Detection.** When fixing one site of a pattern, grep the whole
codebase for siblings and make the lock cover the **class** — a scanner
or a parametrized test over every site — not the single instance. Treat
a pack's hand-listed site count as a FLOOR, not the surface.

**Related.** §13.5 earn-the-gate (the positive — the guard is one).
§3.4 shotgun surgery (the source-side companion). §2.3 coverage trap
(adjacent but distinct: there the assertion is weak; here the assertion
is strong but its *scope* is too narrow). §9.7 (the class this masked).

---

### 2.9 Timing-based concurrency test (false-green with the lock removed)

**Signature.** A test for a lock / critical section / atomic operation asserts
correctness via WALL-CLOCK TIMING — it widens a window with `sleep` and checks
that the observed interleaving "looks serialized." Such a test passes even when
the lock is removed: timing is probabilistic, so on a fast, quiet machine the
unprotected code happens not to interleave, and the test greens on a broken
implementation. It proves a coincidence, not the mechanism.

**Example.** A file-lock test started thread B, slept, then asserted B's write
landed after A's — deleting the lock, it still passed (the sleep made the race
window not materialize). The fix proves the MECHANISM deterministically, two ways:
(a) a mutex proof — event-coordinated threads where B provably blocks while A
holds the lock, and which goes RED when the lock is replaced with a `nullcontext`;
(b) a wrap-order proof — a spy context manager that records call order and asserts
enter < protected-op < exit. No `sleep` decides correctness.

**Contract.** A concurrency test must FAIL when the synchronization is removed.
Coordinate threads with events (not sleeps), and assert the ordering the lock
guarantees — its own red-with-the-lock-gone is the earn-the-red.

**Related.** §2.8 lock-test narrower than its class. §2.4 flakiness. §13.5
earn-the-gate validation.

---

### 2.10 Recognizer under-scans its input population (matcher shape gap)

**Signature.** A guard resolves inputs by first *recognizing* them with a matcher
(a regex, a heading parser, a glob) and then applying a strong check to each
match. The check is correct and the run is green — but the matcher's
recognized-shape set is narrower than the shapes actually present in the live
input population, so a whole shape is silently never *visited*. The green reads
"every input passed" when it means "every input the matcher deigned to look at
passed." No sibling is required: a single matcher under-scans its own domain.

**Mental model.** A spell-checker whose word regex doesn't match hyphenated
words. Every word it *finds* is spelled right; it never looks at the hyphenated
ones. The report says "no errors."

**Industry analogs.** Silent input-validation bypass by an unhandled format.
A tokenizer that drops a token class off-by-one. "Parse, don't validate" (Alexis
King) — an under-covering parser is worse than none because it looks
authoritative.

**In-repo example.** The source-citation contract added to close doc citation rot
(`tests/test_doc_source_citations.py`) resolves every backtick production-source
citation in a live-state map. Its `_SOURCE_CITATION_RE` tolerated a single `:NN`
line suffix but not a `:NN-MM` *range* — and on a range the WHOLE backtick span
failed to match, so the citation was skipped entirely, not merely resolved with
the line ignored. That shape was already in the live population: the
redefined-information registry cited `pyproject.toml:70-76`, doubly stale (the
markers list had moved, and the count had drifted 6→8). The contract greened on
"all resolve" because it never *visited* the one drifted citation it was built to
catch — the guard's own matcher was the blind spot. The earn-the-red (inject a
phantom into a copy of the real doc) passed too, because the injected phantom
used a shape the matcher *did* recognize. Only an orthogonal-context code review
caught it. Fix: widen the suffix to `(?::[0-9]+(?:-[0-9]+)?)?`, correct the
drifted citation, and lock the shape with a regex unit test asserting the range
form matches.

**Detection.** Enumerate the *shapes* an input can take in the live population
(not just the shapes your fixtures happen to use) and assert the matcher visits
each — a parametrized test over every shape, or a probe that logs what the
matcher SKIPPED, not only what it flagged. A green "all resolve" is worthless
without a companion count of "how many did we look at." Earn-the-red witnesses
*mechanism* (does a phantom of a recognized shape get flagged?), never *coverage*
(does every shape reach the check?) — budget a separate check for coverage.

**Contract.** A matcher-based guard MUST be exercised against every input SHAPE
present in the population it scans before "green" is trusted. When a guard's
green result is `all X resolved`, pair it with `N of N visited` so a
skip-by-shape cannot masquerade as a pass. This is a false-NEGATIVE by shape,
distinct from the coverage trap (§2.3, weak assertion) and the narrow lock
(§2.8, unswept sibling *sites*): here the assertion is strong and the sites are
in scope, but the recognizer never delivers a whole shape class to it.

**Second instance — the recognizer is a TEST'S OWN substring, and the unseen
shape is a line wrap.** Prose assembled from a wrapped source literal contains a
newline where the author reads a space, so `assert "no recent-session digest
reached this banner" not in output` can never match and never fire — the
assertion is vacuous while looking deliberate and specific. It was caught only
because the mutation it was written to kill *still survived* after the assertion
was added. Same mechanism as above, one level in: the matcher (a substring) does
not recognize the shape the population actually has (wrapped). Fix: flatten
whitespace on both sides (`" ".join(text.split())`) before comparing, or assert
on a fragment you can see is single-line. Headings are wrap-immune by
construction and make safer anchors than sentences. Worth a mechanical sweep
rather than a spot-check: extract every multi-word string compared with
`in`/`not in` and test each against the flattened *and* raw forms of the
constants it targets.

**Related.** §1.12 sister-predicate domain blindness (the sister-*pair* variant —
a widened parser desyncing from its twin; here there is no twin, one matcher
under-covers its own domain). §2.8 lock-test narrower than its class (narrow by
*site*; this is narrow by input *shape*). §2.3 coverage trap (weak assertion —
adjacent but distinct). §2.13 only-negative coverage (the sibling failure in the
same suite: this one cannot *match*, that one cannot *observe absence*). §13.5
earn-the-gate (proves mechanism, not shape coverage).

---

### 2.11 Mutation kills the helper, not the wiring

**Signature.** A fix adds a helper *and* a call to it — two failure surfaces. The
tests target the helper, because the helper is the interesting code. You verify
the gate by mutating the helper, it reds, and you record an earned red. But
**deleting the CALL leaves every one of those tests green**, because none of them
ever went through the wiring. The gate proves the helper is correct; it proves
nothing about whether anything invokes it.

**Mental model.** Testing that a smoke detector's alarm works by pressing its
test button, then concluding the building is protected — while the detector sits
in a drawer, wired to nothing. Every assertion about the alarm is true.

**Industry analogs.** Unit-tested-but-unregistered handler / route / listener.
Dependency injected but never bound. A feature flag whose evaluation is covered
but whose call site was removed. Mockist testing that verifies collaborators in
isolation and never exercises the composition.

**Example.** Two independent instances in one change set. (1) A summary line was
converted from a hardcoded literal to a derived value; three tests covered the
deriving function and all three stayed green when the print statement was reverted
to the literal. (2) A backwards-compatibility shim was added to a module loader;
three tests called the shim directly and all three stayed green when the call was
deleted from the loader. In both cases the helper had an earned red and the wiring
had none.

**Why it hides.** The call site is one line and feels too trivial to pin. It is
also frequently *invisible to a black-box test on current inputs* — a compatibility
shim is a no-op on a current module, so loading a real one cannot distinguish
"backfill ran" from "backfill was deleted."

**Detection.** For any helper-plus-call-site fix, run the mutation that **deletes
the call**, not the one that breaks the helper. If nothing reds, the wiring is
unpinned. Two repairs, in preference order: drive the real entry point and assert
on its observable output; or, when the helper's effect is invisible from outside,
spy on the invocation (substitute a recorder for the helper and assert it was
called). A test that never names the entry point is a test of the helper only.

**Related.** §2.3 coverage trap (weak assertion — this is a *strong* assertion
pointed at the wrong surface). §13.5 earn-the-gate (proves mechanism, not
coverage). §2.10 recognizer under-scans its population (narrow by input shape;
this is narrow by *code path*).

---

### 2.12 The red that lived only in the transcript

**Signature.** You write a gate, run it against the unfixed tree, and watch it
fail on exactly the cases it should. The red is real; you saw it. Then you fix
the tree, the gate goes green, and you ship. **Nothing in the suite encodes that
red.** The gate can now be neutered — its threshold widened, its comparison
inverted, its assertion deleted — and the suite stays green, because the only
input that ever made it fail was the pre-fix state of the tree, and that state is
gone.

**Mental model.** Calibrating a scale by watching the needle move when you set a
known weight on it, then shipping the scale with the weight thrown away. The
calibration happened. It is simply not repeatable by anyone else, including you
next month.

**Industry analogs.** Manual QA sign-off with no regression test. A bug fixed
after reproducing it by hand, with no test written from the reproduction. Mutation
testing run once during development and never wired into CI. "I tested it locally."

**Example.** A freshness gate compared each cited line against the nearest live
occurrence of its symbol, with a tolerance. It was written before the citations
were corrected and reddened on exactly the drifted ones — a textbook earned red.
But the comparison lived **inline in the test function**, so the only way to
exercise it was through the live data, and once that data was correct there was no
input left that could fail. Setting the tolerance to a billion left the test
green. The floor guarding the *parse* was fine; nothing guarded the *comparison*.

**Why it hides.** The earned red is genuinely evidence — it is exactly what
discipline asks for — so it feels like the obligation is discharged. The gap is
between *having verified the gate* and *the suite being able to re-verify it*, and
nothing in a green run distinguishes those. It is worst for a gate whose entire
population is the live tree, because success removes the failing input as a side
effect.

**Detection.** After earning a red by hand, ask: **what in the suite would fail if
this check stopped firing?** If the answer is "nothing", the red was a measurement,
not a test. The repair is usually structural — extract the predicate so it accepts
constructed input, then encode the red as an injection test with a known-bad case
and a known-good one. Then mutate the tuned constants themselves: if the fixture's
bad case is *derived from* the constant it pins, it scales with the mutation and
still cannot catch it, so hold at least one reference value fixed.

**Related.** §2.11 mutation kills the helper, not the wiring (that aims the
mutation at the wrong surface; this never retains it at all). §1.13 autoimmune
regression / born-weak guard. §13.5 earn-the-gate validation. §11.11 earn-the-red
is necessary, not sufficient.

---

### 2.13 Only-negative coverage (the suite cannot see a gate that withholds)

**Signature.** A behaviour is covered exclusively by assertions of the form
`assert X not in output`. Every one of them passes, and they look like real
coverage because they were written deliberately, name the right string, and
would red if someone shipped `X` unconditionally. But a `not in` assertion can
only observe the *presence* of `X`. The moment the defect you actually fear is
"a gate WITHHOLDS `X` from someone who should get it", the entire arm is blind —
and so is the suite. The tell is a mutation that makes the feature *never ship
at all* (`if False:`) passing untouched.

**Mental model.** A smoke alarm tested only by confirming it stays silent in
clean air. Every test passes; nobody ever lit a match. Unplugging it passes too.

**Industry analogs.** Assertions on absence in permission tests (`assert 403`)
with no matching `assert 200` for the authorized user — the classic way a
too-strict authz change ships as a green suite. Negative-only schema validation.
Feature-flag tests that only cover the off state.

**In-repo example.** A banner section was gated on repo identity (`if self_host`)
rather than on the artifact it names, so adopters were denied content their tree
actually carried. Every test covering it asserted the adopter *did not* receive
it — which was the defect, encoded as the contract. After inverting those tests
to `assert ... in`, an adversarial mutation battery still found three survivors
across a 8,000-test suite: re-adding `self_host and` to the health flag, reverting
the orientation tail to an identity fork, and — most telling — replacing the whole
condition with `if False:`. All three left the suite green, because the remaining
arms were still only checking that the line did not ship *unconditionally*.

**Detection or fix.** For every behaviour, ask "which mutation makes this
*disappear*?" and confirm something reds. Concretely: pair each `assert X not in`
with an `assert X in` on the tree where `X` is *earned*. One positive arm killed
two of the three survivors above. Cheap mechanical smell: a symbol whose only
test references are inside `not in` assertions. Note this is the mirror image of
the scanner rule "every scanner ships a must-NOT-trip negative corpus" — that one
adds the negative to a positive-only suite; this adds the positive to a
negative-only one. A suite needs both directions for the same reason.

**Related.** §2.11 mutation kills the helper, not the wiring. §2.3 coverage trap.
§1.13 autoimmune regression / born-weak guard. §13.5 earn-the-gate validation.

---

### 2.14 An early-return guard silently hollows out the tests below it

**Shape.** You add a guard near the top of a function — a precondition, a
feature flag, a "not applicable here" stand-down — and the suite stays green.
Some tests that exercised the code *below* the guard now never reach it. They
still pass, because the guard's return value happens to satisfy the assertion
they make. Nothing reds, so nothing tells you coverage just evaporated.

**Why the green is misleading.** A test's assertion is usually far weaker than
its intent. `assert rc == 2` was written to prove *one specific refusal path*
fires, but it is equally true when a brand-new guard refuses for an unrelated
reason. `assert rc in (0, 1)` — the "finishes without crashing" shape — absorbs
literally any early return. The looser the assertion, the more silently it is
hollowed. The tests that *do* go red are the ones whose assertions were tight;
they get noticed and fixed, which creates a false sense that the sweep is done.

**Worked example.** Gating three CLI verbs to stand down outside their intended
repo made four tests fail loudly — all retro-fitted with a fixture asserting the
precondition. Two more kept passing and were found only by an adversarial pass
that spied on whether the function under test was *called at all*:

    as-shipped   rc=2  artifact intact=True  create_release_zip called= 0
    precondition rc=2  artifact intact=True  create_release_zip called= 1

Identical verdict, opposite coverage. The invariant that test documented — a
no-clobber guarantee inside the function — could have been reverted wholesale
and it would still have passed.

**Detection or fix.** When adding any early-return guard, enumerate every test
that calls the guarded function and ask not *"does it still pass"* but **"does
it still reach the code it names"**. A call-spy (monkeypatch the inner function
to record invocation) answers that in one line and does not depend on the
assertion's tightness. Then give each such test an explicit fixture that
establishes the precondition, so it states the world it needs instead of relying
on the guard not existing yet. The mechanical version, for a guard you expect to
spread: an AST contract over the test tree requiring every caller of the guarded
symbol to either request that fixture or carry an explicit opt-out comment —
derived from the test tree, so a new call site forces a decision rather than
joining the silent majority.

**Adjacent trap, same session.** The set a guard applies to is easy to key on
the wrong property. Membership keyed on an *incidental* attribute ("the command
is hidden from `--help`") rather than the *defining* one ("the command applies
this standard to foreign content") will structurally exclude real members —
there, a fully visible command doing exactly the same harmful thing. Derive the
set from consumers of the shared predicate, not from a proxy attribute.

**Related.** §2.13 only-negative coverage. §1.13 autoimmune regression /
born-weak guard. §2.3 coverage trap. §13.5 earn-the-gate validation.

---

### 2.15 A population floor cannot see a keying defect

**What it is.** A contract that compares two derived sets by NAME, guarded
against vacuity by a floor on how many items it found. The floor counts
POPULATION; the comparison is keyed by NAME. They are different properties, so
a change that leaves the population intact while altering the keys passes the
floor and empties the comparison. Both halves report healthy and nothing is
checked.

**Attested.** A contract compared per-class declared counts against parsed
sections, floored at "at least 20 classes and at least 150 rows" against live
values of 26 and 263 -- comfortable margins. Widening the section-heading
regex's capture group to include the heading's title text, a natural "make the
error message nicer" edit, left both numbers unchanged: still 26 sections, still
263 rows, floor green. But the declared side keyed on the bare token and the
parsed side now keyed on the full heading, so every `name in sections` lookup
was false, both drift dictionaries were unconditionally empty, and two of the
three contracts passed having compared nothing. Only the third, which never
does a name-keyed lookup, could still fail.

**How to avoid it.** Assert the KEY SETS are equal before comparing values:
`assert set(a) == set(b)`, with a message saying that until they match every
per-key comparison below is vacuous rather than merely incomplete. A bigger
floor cannot help -- the population was never wrong. Pair it with a synthetic
fixture that exercises the parser on a small deterministic string, because a
contract whose only proof ran against live data cannot re-earn its red once
that data changes.

**Related.** §2.13 only-negative coverage. §1.13 born-weak guard.
§2.16 the fixture that cannot take the target's shape.

---

### 2.16 The fixture cannot take the shape of the tree it certifies

**What it is.** A test builds a fixture, asserts a behaviour, and passes -- but
the fixture is a shape the real target can never have, so the assertion is
about a world that does not exist. Distinct from a wrong fixture: this one is
internally valid and locally green. The defect is that the property under test
is reachable only in the fixture.

**Attested.** A session-end sweep printed a warning when it had nothing to
persist, on the argument that a routine which silently does nothing is
indistinguishable from a broken one. The branch keyed on "deposit plus
harvested items are both zero". Harvested items came from a directory of
committed reports -- a STANDING inventory of several hundred, never zero on the
repo the sweep runs against -- so the branch was unreachable in production and a
run that found nothing new reported "already current", the exact inverse of the
intended signal. The test passed because its fixture built a tree with no
reports directory at all. A second instance the same day: a write channel was
denied by a protected-zone guard in every normal session, and was validated
end-to-end in a session running with the guard's bypass enabled.

**How to avoid it.** Ask what shapes the real target can take, then check the
fixture can take one of them -- especially for a branch that fires on an EMPTY
or ABSENT condition, where "nothing there" is easy to build in a fixture and
often impossible in production. When a guard has a bypass mode, validate it at
least once with the bypass OFF: a mechanism proven only under the bypass has
been proven only where it does not run.

**Related.** §2.15 population floor vs keying defect. §1.13 born-weak guard.
§13.7 the earn-the-red platform ceiling.

---

## 3. Architectural and coupling failure modes

### 3.1 Stealth contracts

See §1.2 for full detail. Listed here for category completeness.

---

### 3.2 Connascence

**Signature.** Two software elements are *connascent* if a change in
one requires the other to be changed to maintain correctness.
Page-Jones (1988) taxonomized 9 forms; strongest forms (algorithm,
timing, position, identity) are the dangerous ones.

**Industry term.** Connascence (Meilir Page-Jones, *The Practical
Guide to Structured Systems Design*, 1988).

**Forms (Page-Jones taxonomy).**
- Static (visible at code-read time): Name, Type, Meaning, Position,
  Algorithm
- Dynamic (visible only at runtime): Execution order, Timing, Values,
  Identity

The strength progresses: name is weakest (rename to fix), identity
is strongest (object identity tracked across boundaries).

**In-repo example.** When `tools/cc/` invokes
`python tools/cc/cognitive_blueprint.py record --kind decision
--description "..."`, the calling hook and the called CLI share
connascence of *position* (argument order) and connascence of
*name* (`--kind`, `--description`). Renaming `--kind` to `--type`
in the CLI would silently break every hook that invokes it. The
contract that pins this shared surface is the test
`test_subprocess_cli_contract.py` — it asserts the CLI accepts the
exact flags the hooks pass.

**Detection.** Manual audit; code review checklist; some static
analyzers support a subset (e.g., position connascence between
function definitions and call sites).

**Contract.** Prefer weaker connascence (name) over stronger
(position). Refactor away strong connascence as it appears. Where
strong connascence is unavoidable (CLI surfaces, file schemas),
pin it via contract test.

**Related.** §1.2 stealth contracts (a category of connascence
without an import expressing it). §3.4 shotgun surgery.

---

### 3.3 God class / God file

**Signature.** Single module / file does too many things; becomes
the dependency of everything else; rate of change of the file is
disproportionately high.

**Industry term.** God class (AntiPatterns 1998); God object
(informal); The Blob.

**In-repo detection.** `espalier scan godfiles` flags files above a
configurable line count (default threshold 750). The scanner walks
the source tree, counts logical lines (excluding blank/comment),
and reports any file above threshold with severity rising as size
grows. Threshold-based scanners are coarse but effective: 750 LOC
empirically correlates with files that should be split.

**Contract.** Threshold-based scanner + refactor when threshold is
crossed. The threshold is a heuristic — a file just under threshold
isn't healthy, just smaller. Watch for files that grow with each
change (the rate-of-change signal is stronger than the absolute size).

**Related.** §3.4 shotgun surgery (god files often produce shotgun
surgery as their interface is used everywhere).

---

### 3.4 Shotgun surgery

**Signature.** A single conceptual change requires edits to many
unrelated places. The cost of the change is proportional to the
number of edit sites, not the conceptual complexity.

**Industry term.** Shotgun surgery (Fowler, *Refactoring* 1999).

**In-repo example.** A hook-count change requires updating
`surface_contract._CANONICAL_HOOK_SCRIPTS`, `cli.INIT_HOOK_SCRIPTS`,
`harness_config.CANONICAL_HOOK_WIRING`, `.claude/settings.json`,
multiple test `EXPECTED_HOOK_COUNT` constants, plus the CLAUDE.md
hook table, CHEAT-SHEET.md, and ESPALIER_MEMORY.md. A single conceptual
change ("add a hook") fans out to ~10 edit sites. The risk: forget
one site, the harness ships internally consistent at most sites but
broken at one. The mitigation: the `NumericContract` registry binds
the hook count across sites with parity tests; the missing site
fails the test rather than silently shipping.

**Detection.** Watch for changes that touch ≥3 unrelated files
together in git history. Use `git pickaxe` (`-S<string>`) to find
files co-changed across many commits.

**Contract.** Consolidate the SoT. `NumericContract` registry makes
the multi-surface coupling explicit and pinned. Or extract a single
authoritative source that other sites derive from.

**Related.** §3.3 god class. §1.3 doc-surface propagation (the doc
side of the same problem).

---

### 3.5 Hidden cycles via tests

**Signature.** Module A and module B share no direct imports, but
both are imported by a test that creates a contract surface neither
module sees. The test is a load-bearing integration point that
neither module's owner is aware of.

**In-repo example.** `tests/test_session_resume.py` imports from BOTH
`espalier/` AND `tools/cc/`. The architecture rule forbids `tools/cc/`
from importing `espalier`. The test is the privileged exception
(tests can import everything). But the test EXERCISES interactions
between the two layers — changes to either side can break the test,
and neither side's code review will notice. The test becomes an
undocumented contract.

**Detection.** Static import-graph analysis treating tests as nodes;
flag tests that import from multiple top-level layers.

**Contract.** Document cross-layer test files explicitly. Their
existence is a real contract; treat them as architecture, not
test-suite plumbing.

---

### 3.6 Distributed monolith

**Signature.** Multiple services that must deploy together to
function; every change requires coordinated release across services.
The services appear independent but are operationally one unit.

**Industry term.** Distributed monolith (informal; widely cited in
microservices literature).

**Detection.** Deployment dependency analysis. If service A's release
notes routinely include "requires service B at version X.Y," the
services are not independent.

**Contract.** Each service can be deployed independently;
backwards-compatible API changes only; consumer-driven contract
tests prove independence.

---

### 3.7 Inappropriate layer leak

**Signature.** A lower layer (engine) imports from an upper layer
(enforcement / instrumentation / hooks). The dependency direction
violates the declared architecture.

**In-repo example.** Espalier's architectural rule: `espalier/`
imports from `espalier/` only; `tools/cc/` (the hook scripts) has
ZERO espalier imports — scripts are copied verbatim and run
standalone. The rule lets adopters deploy hooks without depending
on the espalier package. A violation — say, a hook script doing
`from espalier.scanners import _foo_registry` — silently breaks the
adopter deployment because the import doesn't resolve. The contract
test `TestScannerSelfContainment` at `tests/test_scanners.py` walks
every file under `espalier/scanners/` and asserts no `from espalier`
or `import espalier` line appears (excluding comments).

**Detection.** Import-graph analyzer with declared layer ordering;
contract test per layer asserting no upward imports.

**Contract.** Layer-boundary test that walks imports per module.
The test is the operational definition of the layer; if the test
passes, the layer holds.

---

### 3.8 Relaxation-tightening contract drift

See §1.5 for full detail.

---

### 3.9 Predicate-name semantics creep

See §1.8 for full detail.

---

### 3.10 Fail-closed blocks the repair path

**Signature.** A check cannot answer its own question — the file will not parse,
the manifest is unreadable, the probe timed out — and it returns "nothing to
report," which downstream reads as "clean." The obvious repair is to make it fail
CLOSED and report. That is right when the consumer is a **reporter** and wrong
when the consumer is a **blocker whose denial covers the repair action itself**:
the stricter check now prevents the edit that would fix the condition it fired on.
The system deadlocks in the name of safety.

**The reporter is not automatically safe either — ask what the refusal costs the
rest of the population.** A probe runner refused its *whole* report whenever the
roster's declared count disagreed with the rows it carried, on the correct
ground that a file disagreeing with itself is not an honest null; one field
drifted by three, undated, and for an unknown span every probe in the file went
unreported — including the one stale pin the run would have surfaced. A reporter
may fail closed on the member it cannot answer for, but refusing the entire
report over one inconsistent field converts a single stale field into total
blindness: give the refusal a one-command reconcile path, name that path in the
refusal text, and report the members the inconsistency does not touch.

**Mental model.** A smoke alarm wired to the door locks. It cannot tell smoke from
a failed sensor, so on sensor failure it seals the building — with the technician
outside.

**Industry analogs.** Fail-secure vs fail-safe in access control (a fire door must
fail *safe*, a vault door fail *secure* — the same failure, opposite correct
answers). A config validator that rejects the config file you need to edit to
satisfy it. Certificate pinning that bricks the update channel shipping the new
pin. Locking yourself out with the firewall rule you were about to fix.

**Example.** A kill-switch scanner returned "no findings" for a settings file it
could not parse — a real fail-open, and the same collapse of *cannot tell* into
*nothing to tell* that the surrounding work existed to close. The obvious fix was
to report the parse failure. But that verdict is consumed by a pre-tool-use guard
that denies **every** mutating tool call on any finding, and a settings file is
most likely to be unparseable precisely while someone is mid-edit — so reporting
would have denied the edit that repairs it. Shipped instead: the extra verdict is
**opt-in**. Blockers keep the previous behaviour; reporters and the non-interactive
merge gate — which has nobody to lock out — opt in. The fail-open is closed on
every surface where closing it cannot trap the operator.

**Detection.** Before widening what any check reports, enumerate its consumers and
ask of each: *does this consumer block, and does its denial cover the action that
fixes the condition?* Where it does, the new verdict needs a channel that consumer
does not read — a separate scan, an opt-in parameter, or a distinct severity.
Corollary: "fail closed" is not a universally safe default; it is safe only where
the actor retains a path to act.

**A second instance, and the rule it yields.** A live pre-tool-use guard (matcher
`*`, so it runs on every tool call) was edited in two steps: the first edit
referenced a new constant, the second was to define it. Between the two the guard
raised `NameError`; its umbrella handler failed closed — correct behaviour — and
denied every subsequent tool call, including the edit that would have defined the
constant. Total lockout; the repair required an out-of-band paste by the operator.
Rule: **edit a guard that gates its own repair atomically** — one write of the
whole file, or define-before-reference within a single edit — and re-verify with a
piped probe (`echo '<payload>' | python <hook>`) after every change, before
issuing another tool call through it. A guard whose fail-closed path covers its
own repair is the vault door of the mental model above, with you inside.

**Related.** §1 fail-open gates (the defect this repair addresses — and
over-applying the repair is this entry). §3.7 inappropriate layer leak (one
verdict serving consumers with incompatible contracts).

---

### 3.11 Class-fix population scoped to a module instead of an idiom

**Shape.** You find a defect that is really a *class* — the same idiom repeated
across several call sites — and you fix every instance you can see. To stop the
class recurring you add a guard that derives its own population, so a new site
enrols automatically. The guard is genuinely self-enrolling, the class is
genuinely closed, and you stamp it closed. Then a sibling turns up that was
never in frame, because the population was derived from **a module** (or a file,
or a hand-written list of names) rather than from **the idiom itself**.

**Why it survives review.** The guard looks exactly like the strong version. It
walks a namespace, it asserts an exact population, it reds on a rename — every
property you wanted. What it cannot do is notice a member living outside the
namespace it was pointed at, and nothing in its output says which namespace that
was. A reviewer reading the guard sees rigour; only someone asking *"what is the
population, stated independently of where I looked?"* sees the hole.

**The compounding form is worse.** A partial class-fix removes the symptom at
every site you did fix, so the evidence that would have led you to the remainder
is gone. The next person to look sees a closed class and a passing guard.

**Two symptoms worth naming, because both read as thoroughness:**

- *The population is a namespace walk.* `vars(<module>)` filtered by a
  predicate. Correct for that module, blind to a sibling that imports from it —
  including, characteristically, the module that **defines** the shared fragment
  everyone else composes.
- *The population is a hand-written list.* A tuple of tokens, paths or flag
  names, usually with a docstring asserting it is complete. The assertion is the
  tell: a list that has to *claim* completeness is one nothing derives.

**Check.** For every class-fix guard, ask what would have to be true for the
population to be wrong, and answer it mechanically rather than by inspection:

1. Grep the **idiom** across the whole tree — the regex shape, the call
   signature, the verb — not the directory you fixed. Compare that count to the
   guard's population.
2. Where the class spans a shared fragment, walk the fragment's **consumers**,
   including cross-module importers. An edit↔depend relation is invisible to a
   file-overlap scan.
3. Where the population is a literal list, ask whether it can be derived from
   the thing it describes. If it can, derive it; if it genuinely cannot, say so
   in the docstring instead of claiming coverage.

**Corollary.** A guard's docstring must describe the population it *actually*
derives, not the population you wish it covered. "Every X is driven here" is a
claim like any other, and it is the claim most likely to be believed without
being checked — including by the person who wrote it.

**Related.** §2 born-weak gates (a guard that cannot red). §3.2 connascence
(shared idiom across modules). §13 detection methodology (deriving a population
rather than asserting one).

---

### 3.12 A budget test whose population cannot express the failure

**Shape.** A performance or complexity budget — a regex ReDoS bound, a query
count, an allocation ceiling — is pinned by a test that drives a population of
inputs. The budget holds, the test is green, and a pathological input of the
same class still blows up, because the population varies the wrong axis.

**The concrete pattern.** A regex budget built from inputs that vary the
*payload* — a long quoted body, a deep nesting, a big file — will not detect
catastrophic backtracking that needs a repeated **prefix**. The two are
different axes of the same input, and a harness that grew up around one has no
reason to have ever tried the other.

**The second half, and it is the part that hides it.** Backtracking is only
exhaustive when the overall match **fails**. Drive a pathological prefix against
an input that still *matches* and the engine short-circuits on the first
success — fast, green, and completely uninformative. A budget test must pair its
pathological input with a **failing** tail, or it measures the happy path under
a scary-looking name.

**Why this class is worth a catalog entry.** The failure mode of a wedged regex
is a **hang**, not an exception. A top-level `except BaseException` crash guard —
the standard defence for a hook or middleware on a hot path — catches nothing,
because nothing is raised. The call simply never returns, which presents as the
tool, editor or request being broken rather than as a caught error with a
message.

**Check.**
- Enumerate the input's *axes* (prefix, payload, separator, repetition count),
  and confirm the population varies each one — not just the one that motivated
  the harness.
- Assert every pathological case against a tail that **fails to match**.
- Derive the population from the pattern's own components where possible, so a
  component added later is measured without anyone remembering to enrol it.
- Scale N and read the **curve**, not one number. Linear is fine; a jump of
  ~1000× per doubling is catastrophic backtracking and no single-N budget will
  tell you which you have.

**Related.** §2 born-weak gates. §3.11 population scoped to a module
(the same defect at the level of *which inputs* rather than *which sites*).
§5 measurement (direction ≠ magnitude — a passing budget is not a measured
bound unless the population could have failed it).

---

## 4. Documentation and information drift failure modes

### 4.1 Doc-surface propagation

See §1.3 for full detail.

---

### 4.2 Retired-vocabulary residue

**Signature.** A retired term survives at one or more doc sites past
its retirement pack. The retirement updates the canonical surface;
incidental mentions in other docs are forgotten.

**In-repo example.** A severity-vocabulary consolidation pack retired
the labels `WRONG / CONFLICTING / VAGUE / CORRECT / BLOCKER / MAJOR /
MINOR` in favor of `BLOCK / WARN / NIT / PASS`. The pack updated
`docs/CONVENTIONS.md`'s severity section, the code-reviewer agent
body, and the pack-artifact checklist. It missed
`docs/CONVENTIONS.md:742` (the pack-artifact review section, same
file as the canonical section, ~250 lines below) and
`docs/REDEFINED_INFORMATION_REGISTRY.md` (Espalier source repo; the registry's C-F01
resolution status row). Both sites continued to describe the
pre-retirement state for two refinement rounds. The fix: a
closed-vocabulary registry + scanner that walks doc surfaces and
flags retired-term occurrences outside allowed historical contexts.
The registry doubles as provenance — which pack retired each term —
and as an audit trail of accepted exemptions.

**Detection.** Closed-vocabulary registry + scanner. Match on the
severity-label USAGE SHAPE (`**WRONG**` bold markdown, `WRONG:`
label prefix, `| WRONG |` table cell) case-insensitively, not on
the bare word — bare-word case-sensitive matching misses mixed-case
residue while case-insensitive bare-word over-matches prose use.

**Contract.** Every vocabulary retirement pack adds entries to the
registry as part of its scope. The scanner runs against the live
repo and fails the pack if residue remains.

**Related.** §1.3 doc-surface propagation. §10.1 single-signal
detector over-match (the case-sensitive vs case-insensitive trap).

---

### 4.3 Stale comments

**Signature.** Comment describes behavior the code no longer
exhibits. The comment was correct when written; the code drifted.

**Industry term.** Stale comments / code smell: comments (Fowler).

**Detection.** Hard to detect mechanically — comments are natural
language. Code review with specific focus on comment-vs-code
alignment.

**Contract.** Prefer self-documenting code; treat comments as a hint
about *why*, not *what*. Update comments when behavior changes.
"Comments don't lie if they don't exist" — heuristic in favor of
deleting drift-prone comments.

---

### 4.4 Tribal knowledge

**Signature.** Critical operational knowledge lives only in one
person's head and is not written down. The team functions because
that person is available; their absence (vacation, departure)
exposes the gap.

**Industry term.** Tribal knowledge; bus factor.

**Detection.** "What happens if person X is hit by a bus?" thought
experiment. Audit who-knows-what across critical operations.

**Contract.** Write it down. Onboarding-test: can a new contributor
do this from docs alone? If not, the missing context is tribal.

**Related.** §12.2 bus factor.

---

### 4.5 SoT proliferation

**Signature.** The same fact is stored in multiple places (config
files, docs, code constants) with no link between them. Each storage
location is a candidate for drift.

**Industry analog.** Single-source-of-truth violation; DRY violation.

**In-repo example.** Multi-surface numeric constants — hook count
appears in `surface_contract._CANONICAL_HOOK_SCRIPTS`,
`cli.INIT_HOOK_SCRIPTS`, multiple test constants, plus several doc
tables. Pre-`NumericContract`, raising the hook count from 9 to 10
required hand-editing ~7 sites; any miss left the harness internally
inconsistent. The `NumericContract` registry binds all sites together
and a parity test asserts they remain in sync; a single SoT (the
registry entry) is the surface that gets edited, and the test
catches any forgotten site.

**Detection.** `NumericContract` registry (for numeric drift).
Closed-vocab registry (for term drift). Generally: when the same
fact appears in N>2 places, add a parity test.

**Contract.** One canonical surface; others derive from it OR are
pinned by a parity test. Avoid hand-maintained parallel inventories.

**Related.** §3.4 shotgun surgery. §1.3 doc-surface propagation.

---

### 4.6 Vacuous registry entry

**Signature.** An entry exists in a registry but points at nothing
that pins it — pure documentation. The registry appears complete;
the contract appears enforced; in reality there is no contract.

**In-repo example.** An early draft of a subprocess-contracts registry
had string values like `"tests/test_subprocess_cli_contract.py::test_memory_prune"`
documenting which test pinned each CLI surface. The scanner read
these strings but never verified the named test actually existed.
A typo (`test_meory_prune`) or rename (the test got moved without
the registry being updated) would silently drop the contract — the
registry would still LIST a pin, but no pin would actually exist.
The fix: a registry-parity test imports each registered value and
verifies the named test function or class is defined.

**Detection.** Walk registry values; resolve each to its claimed
artifact; fail if any value points at nothing.

**Contract.** Every registry value resolves to a real artifact, and
a contract test enforces this. Bidirectional checks where possible
(the test names what it pins; the registry names which test pins it;
both must agree).

**The inverse shape: a registry of recommendations read as an inventory of
deployables.** A configuration builder recorded seven profile-conditional agent
names that no release packages a body for — they are suggestions the advisor
makes, not artifacts — while the ownership check read every saved-plan agent as
a path that ought to exist on disk. Every fresh setup of a project whose
fingerprint tripped one of those profiles then reported a managed file missing,
with two offered remedies that both re-claimed the same path, and a later
reviewer read one of the names as a *retired* agent when it had never shipped.
Fix it at the reader, not the registry: an entry the current builder still
recommends but nothing packages is reported apart from a packaged file that is
genuinely absent, and apart from a name no builder recommends any more. Before
any check treats a list's entries as paths, ask what the list's entries
**denote**.

**Related.** §1.4 canon-vs-claim. §1.7 gate tuning-to-HEAD blind
spot.

---

### 4.7 Historical-section over-permissive predicate

**Signature.** A "this content is historical, skip it" predicate is
too loose, exempting current content. The historical-context heuristic
catches more than intended.

**In-repo example.** An early draft of the retired-vocab scanner had
a predicate `_historical_section` that joined the full heading stack
with `>` and substring-matched against historical markers (`History`,
`Migration`, `Retired`). A document with `## Historical context` at
the top followed by `## Current production state` containing retired
terms would pass the predicate because "Historical" was still
somewhere in the joined string. Effectively the entire document
became exempt. The fix: the predicate checks ONLY the IMMEDIATE
parent heading (last stack entry), not the joined stack. A historical
section ends when its sibling-level section begins.

**Detection.** Test predicates against fixtures with nested headings;
include both expected-allowed and expected-flagged cases.

**Contract.** Context predicates check the most specific scope, not
the broadest. Joined-stack substring matching is almost always too
permissive.

---

### 4.8 Audit drift across sessions

**Signature.** Sessions produce parallel audit outputs that drift from
each other. The harness ships internally consistent within each
session and incoherent across sessions.

**In-repo example.** A multi-pack sprint ran across multiple
sessions. Session A wrote a pack using a warning glyph (`⚠`). A
later session B was supposed to absorb an ASCII-portability concern
but didn't enumerate the runtime-output rule explicitly. A
cross-check pass caught session A's `⚠` as a gap issue contradicting
session B's prior prescription. The fix: extract conventions into
a shared `docs/CONVENTIONS.md` so subsequent sessions read the same
canonical surface rather than inferring from session-local context.

**Detection.** Cross-session drift surfaces when audits run; the
audit comparing two sessions is the gate.

**Contract.** Conventions live in canonical surfaces, not session
context. New sessions begin by reading the conventions, not by
re-deriving them from prior session output.

---

### 4.9 Renderer discards fingerprint data

**Signature.** A code generator receives detailed input but renders
a hardcoded default, silently discarding the input.

**In-repo example.** `_build_claude_md` correctly received
`fp.test_commands = ['cargo test']` for a Rust target repo from the
fingerprinter. The renderer hardcoded `pytest -q` in its template
output. CLAUDE.md deployed to the user's repo told them to run
`pytest` in a Rust project. No test caught the regression because
no test exercised the renderer against non-Python fingerprints. The
fix: parametrized regression tests against multiple language
fingerprints, asserting the rendered output reflects the input data.

**Detection.** Parametrize renderer tests across the input shape
space; assert input flows through to output.

**Contract.** Renderers that accept structured input must use it.
Hardcoded defaults are smells; if a default is needed, it should
appear in the input contract, not silently in the renderer.

---

### 4.10 The cross-artifact assertion nothing checks

**Signature.** One planning artifact declares a change of state about another —
*"that item is struck," "superseded by the merged unit," "the other one owns this
now"* — and the named artifact is never edited to agree. Both then read as
internally complete. A reviewer reading the first sees the coordination handled
and moves on; a reviewer reading the second sees a live, well-formed, un-struck
item. **Only a reader holding both at once sees the gap, and per-artifact review
is by construction never that reader.** The claim was filed in the wrong
document, and nothing asserts it was ever delivered. Naming the class does not
close it: it recurs inside the very sessions that are correcting it, because an
author fixes the document in front of them.

**Example.** A work unit's document declared a sub-item of a sibling unit struck
and superseded. The sibling was never told, still prescribed the work in full,
and was itself scheduled — so the same change would have been applied twice, the
second time against a tree the first had already moved. In the same document set,
three separate units named a fourth as owner of a release-blocking item whose own
header disclaimed the work: each believed it was handled, so an executor obeying
any one of them would have dropped it. A variant carries **measured facts instead
of assertions** — a count corrected in one document and left stale in the sibling
that reasons from it, leaving a threshold calibrated against a dead number.

**Detection / Contract.** *An assertion about another artifact is a claim until
that artifact agrees.* Mechanize it rather than relying on care: scan the artifact
set for cross-references of the form *struck / superseded / owned by / merged into
/ handled by*, and for each, require the **named target to carry the reciprocal**.
Separately flag references to artifacts that exist under no name at all — a merge
or a rename leaves citations pointing at identifiers nothing answers to. Scope
enforcement to pairs where **both artifacts are still live**: once one has landed
or been archived, a missing reciprocal is unactionable history, and enforcing it
there teaches people to suppress the check. Two properties keep such a guard
honest — a **non-vacuous floor**, so that a green means *"reciprocated"* and never
*"found nothing to scan"*; and a population defined **by content rather than by
filename convention**, since a guard keyed on naming can never see the artifact
that broke the naming.

**A variant in the perfect tense: the record claims the write, and the file was
never written.** A wrap-up record states that an item was *logged*, *filed* or
*recorded*, and the named store holds no such row — the same gap with the second
artifact reduced to a single line, which is why it is harder to see: there is no
sibling document to read beside it, only a file nobody opened. Measured: a
session record called five identifiers "logged" in a disposition store that held
none of them, and the reader that consults only that store surfaced nothing the
following session. Two properties close it cheaply — any past-tense verb about
another file is a claim, so the writing step must read that file before the verb
lands; and where the identifier is *derived from the content it names*, the
derivation is a second oracle independent of whatever printed it, so recomputing
it from the source checks the claim without trusting the store at all.

**Related.** §4.1 doc-surface propagation. §4.5 SoT proliferation. §4.8 audit
drift across sessions. §13.13 dedup corpus staleness.

---

### 4.11 The required-state check wired only to the first-run verb

**Shape.** A tool keeps a set of things every installation must have — ignore
entries, config keys, a directory, a settings block. The set grows over time.
The check that reconciles it is called from the setup command, and only from
there. Everyone who installs *after* an addition gets it. Everyone who
installed *before* never does, and never will, because the command they run
from then on is the update verb — which does not perform the check at all.

**Why it survives review.** The addition itself is obviously correct and its
test passes: a fresh install gets the new entry. The population that does not
get it has no fresh install to test, so nothing reds. The defect is invisible
in the diff that introduces the entry *and* in the diff that introduced the
one-sided wiring, because neither is wrong on its own — only their combination
is. It compounds silently: every subsequent addition inherits the same gap, so
by the time anyone notices, the installed base is missing not one item but all
of them added since their setup date.

**The tell, and it is usually already in the file.** A sibling repair for the
same class often sits within a few lines. In the case that produced this entry,
the update command already invoked a *documentation* nudge, with a comment
explaining that the update verb is the one an existing user actually reaches
for — the identical reasoning, applied to a neighbouring concern months
earlier, while the required-state check beside it stayed on the setup-only
route.

**Detection or fix.** When adding to a required-state set, do not stop at
"does setup write it?". Ask **"who delivers this to someone who already
installed?"** — then grep the reconciling function's call sites *before*
touching the set. If it has exactly one caller and that caller is setup, the
wiring is the defect, not the entry.

Two corollaries worth carrying:

- **A claim of completeness must be true when it is made.** If the update
  command short-circuits with *"already current, nothing to do"*, run the
  required-state check *before* that line. The version stamp answers "is the
  code stale?", which is orthogonal to "is the required state present?" — a
  user can be perfectly current and still missing an item.
- **Test both branches of the early return.** A test that sets up by running
  setup will find the deployed version already current, so it exercises only
  the short-circuit path — and the population the fix exists for is, by
  definition, on the *other* branch. Parametrize over current and stale, or
  the wiring on the path that matters stays unpinned while the suite reads
  green. (Measured: removing the main-path call was a mutation that survived
  until the stale case was added.)

**Related.** §2.14 an early-return guard hollows out the tests below it. §4.10
the cross-artifact assertion nothing checks. §1.13 born-weak guard.

---

## 5. Epistemic and measurement failure modes

### 5.1 Canon-vs-claim

See §1.4 for full detail.

---

### 5.2 Goodhart's law

**Signature.** When a measure becomes a target, it ceases to be a
good measure.

**Industry term.** Goodhart's law (Charles Goodhart 1975, restated
by Marilyn Strathern 1997).

**Example.** A code coverage target hits 100% by adding meaningless
tests (e.g., tests that exercise a function but assert nothing). The
metric is achieved; the goal (quality) is not.

**Attested example, retrieval pins.** A one-slot equality pin on a
paraphrase-retrieval curve broke when a new catalog entry entered the corpus. The
fastest green was to fold the new entry into an adjacent section — an A/B confirmed
it restored the curve exactly. Rejected, because it shapes the documentation to
satisfy the test, and the curve had moved for a real reason: a document that
*cites* a principle was outranking the principle, a ranking defect the pin had just
detected (since fixed at the retrieval front door). The fold would have hidden it
behind a green suite. Re-derive the pin's
*claim* (there: a shape, climb-then-flat) or fix the defect; never edit the
measured input so the metric holds.

**Detection.** Watch for metrics that incentivize the wrong behavior.
Periodically ask: "if someone optimized for this number, would the
underlying quality improve or degrade?"

**Contract.** Multiple orthogonal metrics; require all to move
together for the claim to be honest. Track the metric AND its
correlations to outcomes; if correlation breaks, the metric is
captured.

**Related.** §2.3 coverage trap. §5.3 vanity metric.

---

### 5.3 Vanity metric

**Signature.** A number that looks good but doesn't predict the
outcome you care about. Easy to grow without doing real work.

**Industry term.** Vanity metric (Eric Ries, *The Lean Startup*, 2011).

**Example.** Pageviews on a docs site — high pageviews don't mean
the docs are useful; could mean people are lost and refreshing
repeatedly. Lines of code shipped — high LOC isn't quality.

**Detection.** Ask: "what decision changes when this number changes?"
If no decision changes, it's vanity.

**Contract.** Metrics tied to specific operator decisions or
pre-declared outcomes. If the team wouldn't change behavior based on
the metric's value, drop it.

---

### 5.4 Self-verifying canon

**Signature.** A canon (scanner / test / probe) whose results are
generated by the same code path it's supposed to verify. The canon
verifies itself by walking its own discovery rules.

**In-repo example.** An early draft of a canon-vs-claim verifier
used a hardcoded `_is_claim_marker` heuristic to find claim lines in
docs. The heuristic was the verifier's own definition of "what
counts as a claim." A claim outside the heuristic was silently
not-counted, and the contract test "every claim has a canon" passed
because the verifier didn't see the un-canonized claims. The
verifier verified itself: its inputs came from its own discovery
code, and its outputs were "every input has a canon." A genuine
test would have used an INDEPENDENT enumeration of claim sites and
asked "does the verifier find each of them?"

**Detection.** Cross-check the canon's input set against an
independent enumeration. The canon should not be the source of
truth for what it measures.

**Contract.** Registry-based enumeration + drift contract: if a
claim/case is found outside the registry, the test fails (forcing
operator awareness). The registry is the input set; the canon
operates on it; the canon does not invent the registry.

**Related.** §1.10 canon formula structural impossibility (sister
shape where the canon's structure is broken, not just its input
set).

---

### 5.5 Threshold at noise baseline

**Signature.** A falsifiability threshold is set at the empirical
historical mean. The canon cannot fail on near-historical data
because the threshold IS the noise floor.

**Mental model.** A pass-fail line drawn at the class average.
Everyone who scores anywhere near typical performance passes;
the line doesn't discriminate.

**In-repo example.** A scaffolding-quality canon defined Signal 3
(reflect coverage) with falsifiability "Coverage stays < 20% steady
state → `/reflect` is nominal, not real." Historical coverage
across deployed sessions was 21.7%. The threshold sits right at
the baseline; treats noise as the floor; can't fail on near-historical
data. A change that drove coverage to 15% would correctly trigger;
a change that drove it to 21% wouldn't, even though 21% is the
status quo the threshold is supposed to gate against.

**Detection.** Compare threshold to historical distribution. If the
threshold sits within ~1 standard deviation of the empirical mean,
it's at the noise baseline.

**Contract.** Threshold tied to operator intent (a declared target),
not historical baseline. Document the rationale for the threshold
value alongside its definition.

---

### 5.6 Dormant canon

**Signature.** A canon exists structurally but doesn't actually run
in the configurations where the claim would be tested.

**In-repo examples.**

- *External-pin LLM dispatch.* An audit-accuracy framework supports
  `external_pin` claims that should cross-check against pinned
  external excerpts (e.g., `docs/external/cc-hook-protocol.md`).
  The framework is structurally prepared but the LLM-dispatch
  callable is not currently registered. Every `external_pin` claim
  returns `unverifiable` with reason "LLM dispatch not configured."
  The claim "external pins are verified" is true at the framework
  level and false at the operational level.

- *Stop gate Gate 1.* The Stop hook's Gate 1 runs pytest only when
  `ESPALIER_STOP_GATE=full` is set. The default `light` mode silently
  skips Gate 1. CLAUDE.md's hook table presents Gate 1 as if it
  always fires. The dormancy is intentional (full pytest on every
  Stop is slow) but the documented claim doesn't reflect it.

**Detection.** Canon-output-distribution analysis: a canon that has
returned 0 findings across many runs (or returned `unverifiable`
universally) may not be running. Check the default configuration
of each canon — does its claim hold under default settings?

**Contract.** Earn-the-gate validation — every canon demonstrates
it has fired on at least one known positive case before being
trusted as a future gate. Document default-mode behavior explicitly
alongside the canon's claim.

**Related.** §1.7 gate tuning-to-HEAD blind spot. §2.5 slow-test
escape.

---

### 5.7 Producer/consumer parity drift

**Signature.** Producer module changes its output shape; consumer
module doesn't update; tests use the (stale) consumer-side shape;
bug shape matches the consumer's stale view.

**In-repo example.** A registry-class contract emerged after several
instances: a producer emits a token (config key, event name,
fingerprint field), a downstream consumer never reads it, divergence
is silent, the feature appears wired but doesn't fire, integration
tests pass because they only exercise the intersection. The fix
shape: a registry-parity contract via AST walk that extracts producer
output tokens and consumer input tokens and asserts set-equality.

**Detection.** Set-equality test between producer outputs and
consumer inputs.

**Contract.** Both modules import a shared schema definition, OR a
parity test pins the contract by walking both sides.

**Related.** §1.1 convergence theater (sister shape where the
parity test fuses to one side). §2.7 fixture drift.

---

### 5.8 Gate tuning-to-HEAD blind spot

See §1.7 for full detail.

---

### 5.9 Canon formula structural impossibility

See §1.10 for full detail.

---

### 5.10 Validation-ritual presence vs firing

**Signature.** A meta-gate enforces that each governed object carries its
prescribed validation ARTIFACT (an earn-the-gate test function, a `# pins:`
annotation, a fixture) by checking the artifact's EXISTENCE — declaration found,
name-substring present, slug matches — without ever confirming the artifact
DISCRIMINATES (asserts a non-zero finding, exercises the claimed property, fires
on a positive case). The strongest "green" verdict is reachable by performing
the ceremony, not by demonstrating the capability.

**In-repo example.** `canon_verifier._verify_test_canon` (`espalier/scanners/canon_verifier.py`)
returned its strongest `PINNED` verdict on declaration-existence + slug-match
alone (line 497). The scaffolding-signal-threshold claims carried non-stub
`# pins:` yet the pinned test bodies asserted arithmetic *shape*, never the named
threshold literal — §1.4's own Detection text promises "verify the named test
actually exercises the claimed property (not just exists)," which the verifier
did not deliver. Convergent second instance: a scanner earn-the-gate parity
check asserts each scanner HAS a `test_earn_the_gate*` function (name-substring)
without confirming it asserts a non-zero finding. The recursion is the novel
core: the anti-blind-spot mechanism is itself a presence-check satisfiable by an
empty ritual. The fix: numeric/threshold claims drop `PINNED` →
`PINNED-STUB` unless the pinned test body references the threshold literal.

**Contract.** A meta-gate enforcing a validation artifact must assert the
artifact DISCRIMINATES — asserts a non-zero finding, references the claimed
threshold/property, or fires on a known positive case — not merely that it
exists or is named correctly.

**Related.** §1.7 gate tuning-to-HEAD (base gate never red). §1.11 gate
credibility (gate inspects a subset of surfaces). §5.4 self-verifying canon.
§5.6 dormant canon.

---

### 5.11 Unmeasured command latency

**Signature.** A command a human runs and waits on ships with its performance
*asserted* rather than *measured* — green unit tests on a small fixture say
nothing about wall-clock on a real tree. The recurring shape is a per-item
subprocess (a `ripgrep`, a `git` call, a shell-out) inside a loop over an
unbounded set: that is O(items × files), quadratic, while the surrounding comment
often claims "fast" or "O(n)". "Fast" is a direction; the run time is a magnitude,
and only the magnitude is the property that matters to the person waiting.

**Industry term.** Accidentally quadratic (a.k.a. Schlemiel-the-painter's
algorithm).

**Example.** A cross-reference feature implemented as one full-tree text search
*per symbol*. On a real repository with ~1000 symbols it took minutes
(O(symbols × files)), while the design note claimed "O(files), fast." Replacing
the per-symbol search with a single pass that parses each file once and buckets
the referenced identifiers dropped it to sub-second — and was more correct
(mentions inside comments/strings excluded, the definition site not self-counted).
The green fixture tests had never exercised a tree large enough to feel it.

**Detection.** For any command a human invokes interactively, add a real-tree
wall-clock smoke to the acceptance pass — treat latency as a first-class gate,
not an afterthought. Smell test: a subprocess inside a loop over an unbounded set
is almost always the wrong shape.

**Contract.** Verify a complexity/performance property by measurement on a real
tree before shipping, exactly as you would verify a correctness property. Index
once, then look up; do not shell out per item.

**Related.** §5.2 Goodhart's law. §5.12 unmeasured efficacy. §1.4 canon-vs-claim
(a stated property is a claim until verified).

---

### 5.12 Unmeasured efficacy (direction mistaken for magnitude)

**Signature.** A campaign with a quantitative goal — reduce duplication, shrink a
god-file, speed something up — is graded "landed green, zero regressions." That
proves CORRECTNESS (nothing broke); it says nothing about EFFICACY (whether the
metric the campaign targeted actually moved). A plausible mechanism ("this should
reduce duplication") is reported as if it were a measured result.

**Industry term.** Direction ≠ magnitude; plausibility substituted for
measurement.

**Example.** A multi-part "code-health / de-duplication" effort was framed as a
large win. Re-running the repo's own health scanners at the base commit versus
HEAD showed the targeted metric barely moved — duplication clusters nearly flat,
the god-file count unchanged, net lines slightly *up*. No review lens caught the
overstatement until someone re-measured the metric at the base commit; the
verification that mattered was re-measuring, not re-confirming the green suite.
(Calibration cuts both ways: the effort's genuine latent-bug and hot-path wins
were real and deserved precise credit — only the headline magnitude was inflated.)

**Detection.** Before claiming a metric win, run the scanner that *defines* the
metric at the base commit (a detached `git worktree`) and at HEAD, and report the
measured delta. Specific trap: "decompose a god-file" by extracting nested
branches into IN-FILE helpers does not shrink a file-size metric — it often grows
the file. Extract into a new module, or expect the count to stay flat.

**Contract.** Grade a campaign on the metric it targeted, measured before/after,
and record the delta — not on "tests pass / landed green."

**Related.** §5.11 unmeasured command latency. §5.2 Goodhart's law. §1.4
canon-vs-claim.

---

### 5.13 An exit code read through a pipe is the pipe's

**Signature.** A verification step runs `cmd | tail` (or `| head`, `| grep`, `| jq`)
and reads the exit status. In every POSIX shell that status belongs to the **last
stage of the pipeline**, not to `cmd`. Without `set -o pipefail` a command that
exited non-zero is recorded as `0`. The measurement is then carried forward — into
a report, a document, a decision — as if the command had passed.

**Mental model.** Asking someone to relay a message and grading the *messenger's*
delivery. The messenger always succeeds.

**Industry term.** Pipeline exit-status masking. The classic instance is
`curl … | bash`, where a failed download still "succeeds"; `set -o pipefail`
(bash/zsh) or `PIPESTATUS`/`pipestatus` exists precisely to recover the real status.

**Direction matters, and this is the dangerous one.** The better-known pipeline
hazard is the opposite sign: under `pipefail`, an early-exiting reader (`grep -q`)
closes the pipe, the writer takes SIGPIPE (141), and a *passing* check reports
failure — noisy, self-announcing, quickly diagnosed. This entry is the silent
direction: a **real failure reads as a clean pass**, and nothing ever announces it.

**Example.** A pre-flight gate was invoked as `<tool> check <target> | tail` and
recorded as `rc=0`. Run unpiped, the same command exits **2** — a genuine gap it
had been written to surface. The `0` was `tail`'s. The false reading reached a
planning document before it was re-measured, and every downstream statement built
on it inherited the error.

**Why it hides.** Verification discipline — including elsewhere in this catalog —
says to trust a process's exit code over its rendered output, because rendered
output can be stale or fabricated. That advice is correct, and it is exactly what
makes this sharp: **the exit code you read was never the command's.** The most
reliable-looking signal available is the one that lied.

**Same class, second carrier: a compound sequence read through a task notification.**
A pipeline is not the only way to lose a command's status. `cmd; echo $?; tail log;
grep -c FAILED log` reports the status of **`grep`**, and a backgrounded job's
completion notice reports the status of the whole sequence — a surface where the
wrapper is not visible to whoever reads the result. Measured, twice in one session
and in both directions: a run ending in `tail` reported **success** over two real
test failures, and the corrected wrapper ending in `grep -c` reported **failure**
over a fully green suite (`grep` exits 1 when it matches nothing). Both readings
were wrong, and the second is the one that wastes an hour debugging a healthy tree.
The rule generalises: **the status you are shown belongs to the last thing that
ran, and "the last thing that ran" is rarely the thing you care about.** Put the
command of interest last, or capture its status into a variable immediately and
assert on that — and on any run whose verdict matters, read the tool's own result
line rather than any status reported about it.

**Detection.** Never interpret `$?` after a pipeline you did not explicitly write
`pipefail` for. Capture first, then filter:
`out=$(cmd); rc=$?; printf '%s\n' "$out" | tail`. In review, treat any
`cmd | head/tail/grep` whose status is being interpreted as unverified until
re-run bare. When a probe reports suspiciously clean, re-run it with nothing
attached to its stdout before believing it.

**Related.** §5.10 validation-ritual presence vs firing (the ritual ran; it
measured the wrong thing). §7 SIGPIPE under `pipefail` (same plumbing, opposite
sign, loud instead of silent). §13 detection methodology (re-derive a measurement
through an independent oracle before acting on it).

### 5.14 The fixture is clean because you built it

**Symptom.** An install, setup or onboarding path is verified repeatedly, over
months, by a suite that stays green — and then the first run on someone else's
real machine produces a cluster of defects, several of which are not
platform-specific at all and would have reproduced on the verifier's own
laptop.

**Mechanism.** Every fixture is constructed by someone who already knows the
answer. They build the tree the software expects: one version of the tool
installed, the default branch named what the docs assume, no prior config in
the way, no spaces in the paths, and each command adapted on the fly when it
does not quite work. That adaptation is invisible — it never reaches the
fixture, because the person doing it did not experience it as a defect. So the
population under test drifts toward *the environment the software already
handles*, and the defects that only a **dirty** environment produces are
structurally unreachable: they are not rare, they are un-sampled.

The tell is the composition of the eventual finding set. If a real-machine run
surfaces N defects and a large fraction of them are **platform-independent**,
the platform was never the variable — the *cleanliness* was. Measured instance:
of thirteen findings from the first espalier install driven on a real
third-party Windows host, five were fully platform-independent (a stale
installation of the tool winning on PATH; no documented step verifying which
build is running; a subcommand that vanishes silently on ImportError; a
finish-up checklist that does not scale down to a non-Python adopter; a
start-here instruction not anchored to the directory it refers to). Every one
would have reproduced on the maintainer's own macOS box. None had been found in
months of green verification, because the verification had only ever run on
trees the maintainer built.

**Why it survives review.** The suite is not weak and the coverage numbers are
not lying — the assertions are real and they pass. The gap is in the
**population**, not the assertions, and a coverage metric computed over that
population cannot see its own sampling bias. "We verify the install on every
release" and "we have never verified the install against a dirty machine" are
both true simultaneously, and only the first one is ever said out loud.

**Fix.** Make the dirty state a *constructed fixture* rather than a lucky
encounter. Enumerate the ways a real machine differs from your tree and build
them deliberately: a stale version of the tool earlier on PATH, a default
branch that is not the one your docs name, pre-existing configuration the
installer must merge rather than create, a path containing spaces, and a
consumer who runs commands **verbatim** instead of adapting them. That last one
is the highest-yield and the easiest to omit, because adapting a command is
exactly the reflex an author cannot notice themselves performing.

Prefer this to acquiring more platforms. A dirty-machine fixture is CI-shaped —
it costs one fixture and runs everywhere — whereas "verify on a real Windows
host" requires a host, and stays owed for as long as it takes to get one.

**Related.** §5.10 validation-ritual presence vs firing (the ritual ran; it
measured the wrong thing — here it measured the wrong *population*). §13
detection methodology. The source tree is not an oracle for the produced
artifact — same family, one layer down: there the wrong *artifact* is measured,
here the right artifact is measured in the wrong *environment*.

### 5.15 An A/B at an unmatched budget is void, and the knob is not the budget

**Symptom.** A comparison shows a new mechanism beating the incumbent by a wide
margin. The numbers were really measured and they reproduce — but the two arms were
not given the same resources, so the result cannot separate *the mechanism works*
from *the winner was handed more*. Review passes it, because both arms were
configured with what looks like the same setting.

**Mechanism.** Two forms, and the second is the dangerous one.

*Overt.* The arms get literally different budgets — a two-candidate retriever scored
against a one-candidate control. Visible on inspection, once anyone looks.

*Covert.* The arms get the same **parameter value**, and the parameter means
different things to them. Measured instance, in this repo: `recall(top=k)` returns up
to k hits, while `recall_union(top=k)` scores under two normalisations and returns up
to **2k**. Both arms were configured `top=2`; they delivered **3.69** candidates per
query against **2.00** — 84% more for the winner. (Those two figures are the
measurement *as taken on 2026-08-19*; the corpus moves, and a catalog entry that
chases it would be perpetually stale. The live numbers are pinned in
`tests/test_recall.py`.) The test carrying the comparison
was *named* `..._at_the_same_candidate_budget` and its docstring promised "a control
that gets the SAME number of slots". Both were false, and both were written by the
same author who had, hours earlier and in the same file, corrected the overt form of
this exact defect.

The rule both forms violate: **match on the resource the consumer pays, not on the
knob the author turned.** The knob is the author's unit. Delivered candidates,
tokens, wall-clock, API calls, retries, agents dispatched — those are the consumer's.
Whenever the two units differ, the knob will eventually lie about the budget.

**Why it survives review.** An unmatched-budget A/B is not weak evidence, it is
**void** — it bears on no hypothesis, so re-running it, adding queries, or computing
a significance test narrows nothing. Yet it reads as strong, because everything a
reviewer actually checks is sound: the measurement ran, the numbers reproduce, the
arms are named, the constant is pinned with `==`. The budget is nowhere in the
artifact, so there is nothing for a reader to disagree with. In the covert form the
artifact goes further and asserts the opposite — a reviewer who trusts a test name
has been told the check already happened.

**⚠ The conclusion surviving does not make the correction optional.** Measured, on
both instances. Fixing the overt one left the union ahead *and surfaced a strictly
dominant configuration that no lane and neither reviewer had proposed* — it was found
only by chasing the honest control. Fixing the covert one left the headline number
byte-identical — but only because the loser's curve happens to **plateau**
(`recall()` scores 4/16 at top=2, top=3 and top=4 alike). Had it not plateaued, the
headline would have been wrong as well as unearned. A number that survives on a
property of the corpus survived on luck, and luck does not transfer to the next
measurement. Correct it anyway; the *method* is what carries forward.

**⚠ And the correction has its own failure mode, committed while this entry was
being written.** Fixing the covert instance above meant rewriting a results table. In
the rewrite the table was pruned from three columns to one — and the surviving column
was *paraphrase*, the single axis on which the corrected comparison still won. Scored
honestly on the axis that was dropped, the result is not dominance at all but a
**trade**: at a matched budget the challenger takes +4 paraphrase for −7 on naming.
The prose still said "strictly dominant", two lines below a column that contradicted
it. So the same mechanism recurred one level up: an unmatched *budget* was corrected
into an unmatched *reporting surface*, which is the same act of comparing on ground
the winner chose. When you correct a comparison, check what the correction stopped
reporting — and prefer stating the trade, which is usually the more defensible claim
anyway (here: naming was already at 95.6% and paraphrase at 25%, so the trade is
obviously worth taking, and saying "dominant" bought nothing but exposure).

**Fix.** Four, in increasing strength — the first is nearly free, so there is no
excuse for stopping before it.

1. **Report the consumed resource beside every arm.** A table with a `cost/query`
   column cannot hide an unmatched budget; a table of scores can. Catches both forms.
2. **Over-budget the control.** Hand the incumbent *more* than the challenger and let
   it lose anyway. An a fortiori result is immune to a later argument about whether
   the match was exact — this repo's control is `recall(top=4)` at 4.00 candidates
   against the union's 3.69.
3. **Assert the match mechanically.** A budget claim in a docstring or a test name is
   a claim; an assertion comparing the two arms' *delivered* cost is a gate. Worked
   example: `tests/test_recall.py::test_the_control_is_not_under_budgeted`, which
   also carries a non-vacuity leg so it cannot pass by the challenger collapsing to
   the control's size, and asserts the property per-item rather than on a mean.
4. **Name the budget on BOTH arms in one constant each.** The first revision of that
   guard threaded a named constant through the control and left the challenger's
   budget as two independent literals — so raising the shipped configuration to a
   wider setting left the guard green while the challenger ran 39% over. A guard that
   reads one arm from a constant and the other from a literal only watches one arm.

And when a comparison turns out void, **re-derive the whole table, not the one row**.
The honest control is often a different configuration rather than the same one
rescored, and that is precisely where the better option tends to be hiding.

**Related.** §5.3 vanity metric — a number measuring nothing; here, a number
measuring something against nothing comparable. §5.12 unmeasured efficacy (direction
mistaken for magnitude) — the sibling in which the magnitude is measured but the
baseline is not. §5.10 validation-ritual presence vs firing: the comparison ran, and
could not answer the question it was run to answer. §2 test and assertion failure
modes, for the general case of a test *name* asserting a property the body does not
check. `STANDING_PRINCIPLES` §1 (make it prove it) and §9 (fast earns scrutiny) — a
headline that feels decisive is the cue to check what each arm was given.

### 5.16 The benchmark was built where it was cheap, and then it chose the work

**Symptom.** A metric improves round after round — honestly measured, guarded,
reproducible — while the behaviour a user actually sees does not change. Each round
looks like progress and the aggregate looks like a trend.

**Mechanism.** A benchmark gets built where building one is *cheapest*: the surface
that is already small, already structured, already enumerable. Nothing about that
surface's share of real usage enters the decision, because at authoring time the
question is "what can I key an answer set against?", not "what do people ask about?"

Once it exists, it silently becomes the objective. Every later round is aimed at the
benchmark, because the benchmark is what renders progress legible — and each of those
rounds is individually sound. The drift is not in any step; it is that the benchmark's
population and the usage population were never compared, and the gap between them is
invisible from inside the loop.

**Measured instance.** A lexical recall engine's paraphrase benchmark was built
against a 16-section principles document — clean numbered headings, trivially keyable.
Three successive rounds of work improved it. Then the usage log was read for the first
time: of the documents real queries actually resolved to, **40%** were one tier, **30%**
another, and **12%** the tier every round had targeted, which was **6%** of the corpus.
The most recent round moved the benchmark by a third and changed the top answer for
**1 of 60** real queries — and that one change was arguably a regression.

**Why it survives review.** Nothing a reviewer checks is wrong. The measurement is
honest, the arm is blind, the guards fire, the gain reproduces and survives an
adversarial pass. There is no step at which "is this benchmark representative?" is
anyone's job. Two further things hide it:

* **Usage data often already exists and is simply unread.** Here 518 telemetry events
  had accumulated over twelve days. Reading them took one command and reframed the
  entire workstream.
* **Activity instrumentation reads as outcome instrumentation.** The telemetry recorded
  whether a call *returned something* — and this engine returns a nearest neighbour for
  almost any input, so that field was true for 63 of 65 calls and could not distinguish
  a good answer from a bad one. The one signal that might have raised the alarm was
  measuring the wrong thing, and its name did not say so.

**Fix.**

1. **Compare the benchmark's target distribution against the usage distribution before
   optimising, not after.** One join. If it cannot be done because no usage data
   exists, that is the first task, ahead of any mechanism work.
2. **Build the benchmark from logged usage**, not from whichever surface is easiest to
   enumerate. Convenience of keying is a property of the author's afternoon, not of
   the problem.
3. **Instrument outcome, not activity.** "Returned something", "ran without error" and
   "was invoked" are activity. Whether the result was *used* is the cheap outcome proxy
   most systems can record and most do not.
4. **When a metric moves and behaviour does not, suspect the population before the
   mechanism.** The mechanism is usually fine — that is exactly why the metric moved.

**Related.** §5.14 the fixture is clean because you built it — the sibling, one axis
over: there the *environment* under test is unrepresentative, here the *target
distribution* is, and both are sampling bias that no assertion inside the sample can
see. §5.3 vanity metric (a number that measures nothing; this one measures something
real about a slice nobody uses). §5.12 unmeasured efficacy. §13 detection methodology.

---

### 5.17 The assertion nobody perturbed, and the measurement nobody re-ran

**Symptom.** A change set tightens a gate — an exact equality replaces a looser
check, a new dimension joins a swept range — and the suite stays green. The
tightening is described in the commit as a strengthening. Some weeks later the
gate reds on a change that altered no behaviour, and there is no constant to
adjust, because the thing it pinned was never a property of the system: it was a
property of the tree on the day it was written.

**Mechanism, and it has two layers that fail the same way.**

*The assertion layer.* Asserting a relation exactly is a claim that the relation
is stable. Stability is measurable — hold each input out in turn and see whether
the relation survives — and it is almost never measured, because the relation is
true right now and the reasoning for why it should stay true is easy to write.
The reasoning is the tell. A comment of the form "these move together and cancel"
is a hypothesis about a mechanism; it earns an exact assertion only after
something has tried to break it.

*The measurement layer.* The number that justified the gate was produced by an
instrument, and instruments have parameters. When the gate changes, the
instrument's parameters often change with it — especially when the instrument
*derives* them from the artifact under test, which is the good design. Re-running
is then free and is exactly what nobody does, because the recorded figure is
still plausible. A stale measurement does not look stale.

**What makes it hard to catch.** The full suite cannot see either layer. The
assertion passes because the relation holds *today*; the recorded number is prose,
which no test evaluates. Both are invisible to every green run, and a green run is
what the author checks before writing the commit message that calls it a
strengthening.

**Driven.** A sweep gained a fourth leg and the new leg was given the same exact
equality as the three that preceded it, justified by a written argument that a
shift in the underlying corpus would move all legs together and cancel. A
leave-one-out census over all 258 corpus documents refuted it: the three original
legs never once disagreed, while six documents moved the new leg *alone* — and all
six lived in the single directory the project writes to most often. The
"strengthening" was, by a wide margin, the most fragile assertion in the module,
and it was aimed at the highest-churn surface in the corpus. Separately, the same
census had been run before the sweep gained its fourth leg, so every figure quoted
from it described a superseded instrument: seven sites understated the movement
rate by 30% and understated the worst-affected tier by 2x, and two of those sites
shipped.

**Countermeasures.**
1. **Before asserting a relation exactly, name the dimension you perturbed.** If
   the answer is "none", the honest instrument is a bound, not an equality. Split
   the assertion along what you measured: exact where perturbation found no
   movement, relational or banded where it did.
2. **Audit where your mutation effort went.** Effort follows doubt, and defects
   follow confidence. If every drive you ran targeted the part you were unsure of,
   the part you were sure of is unverified by construction.
3. **Re-run the instrument when the subject changes, before quoting it.** If the
   instrument derives its parameters from the subject — and it should — then a
   subject change silently invalidates every figure taken from it.
4. **Never transcribe a number you have already superseded.** Copying from an
   earlier summary rather than from the current measurement is how a file comes to
   contradict itself in two places, both written by the same author, one hour apart.

**Related.** §5.14 (the fixture is clean because you built it) is the sibling for
inputs; this is the same defect for *assertions* and for the *numbers that justify
them*. §5.15 is the family for a claim outliving the evidence that earned it.

---

### 5.18 The red you earned against a synthetic defect proves nothing about the real one

**The shape.** You fix a defect, write a regression test, and prove the test works by
re-introducing the defect *by hand*. It goes red. You ship. Later, someone restores the
**actual pre-fix file** from version control — and the test passes.

**Measured, 2026-08-21.** A contributor doc had conflated two different protected-path
policies (a runtime guard's zone and a CI gate's, which are deliberately different sets).
The fix corrected three files and added a test asserting no doc may present a runtime-only
path as merge-gated. The red was earned by typing an over-claim into one of those files:
red, as expected. Then an adversarial pass restored the genuine pre-fix text out of git
(`git show <fix-commit>^:<path>`) — and the suite went **8 passed**. Two causes, both
structurally invisible to a hand-written red:

1. **The real defect used a different grammar.** It named the zone *by reference*
   ("see `<guard>.py` protected zones") rather than by listing paths, so the test's
   path-token matcher found nothing to object to. The synthetic version listed paths,
   because that is how the author happened to be thinking about it.
2. **The exemption was keyed on the defect's own vocabulary.** The test exempted any
   paragraph naming the runtime guard, reasoning such a paragraph must be drawing the
   contrast deliberately. The defective paragraph names it too. The exemption exempted
   the bug.

**Why the usual disciplines miss it.** "Earn the red" was satisfied — the test did fail
before it passed. Mutation-testing the FIX also passes: delete the guard and the synthetic
case still reds. What goes untested is the only thing that matters — whether the test
recognises the defect that actually occurred.

**The rule.** For any fix to a defect that exists in version control, earn the red against
the **real prior artifact**, never a reconstruction: restore the pre-fix file from the
commit's parent, confirm the new test fails *and fails for its own reason*, then restore
the tree. If the pre-fix state was never committed, write the test first and watch it fail
on the live defect — the same property, obtained in the other order.

**The generalisation.** A synthetic reproduction is authored by the same mental model that
wrote the fix, so it inherits that model's blind spots. The historical artifact is the only
version of the defect that no one's model had a hand in shaping. See §5.19: this is one
instance of validating a fix against a model instead of against the artifact.

### 5.19 The fix was verified against your model of the problem, not against the artifact

**The shape.** Four generations of repair in one session, each generation's defects found
only by the *next* fresh reviewer, and every one traceable to a single mechanism: the fix
was checked against what its author believed the artifact does.

**Measured, 2026-08-20/21.** A repair batch, then a stage that attacked the repairs (4
majors), then a stage that attacked *those* (4 majors), then an adversarial verify of the
result (3 of 4 claims defective). Representative instances:

| the model said | the artifact does |
|---|---|
| "this command measures the pending-tag count" | writes to **stderr**; the shipped recipe piped stdout only, printing `0` at any count |
| "the protected zone" | there are **two** zones — a runtime guard's and a CI gate's — with different members and different consequences |
| "a corrupt file must fail closed" | a file can also parse **and be empty**, which reported "0 checked" and exited 0 |
| "this fixture exercises the guard" | a sibling check fired first; deleting the guard left the suite green |

**The tell.** In every case the verification and the artifact diverged in a way the author
could not see, because both came from the same understanding. The stderr instance is the
cleanest: the author's *verification* included the stream redirect and the *shipped doc*
did not. The idea was verified; the artifact was not.

**What does not fix it.** Adding review stages. Each stage is pointed at code frozen when
it was dispatched, so it is structurally blind to defects introduced by the fix that
follows it. Four stages ran; the per-generation defect count did not fall.

**What does.**

1. **Extract the command you test from the artifact.** Read the literal string out of the
   file and run *that* — never type an equivalent alongside it.
2. **A fix that states a fact must import it, or be pinned by a test that imports it.** Any
   restatement of something code owns is a future divergence.
3. **Enumerate the class before editing one site** — and validate the enumerator against a
   known-answer control first, because an unanchored matcher yields a confident wrong count
   (a substring search for `cc/` matches inside `tools/cc/hooks/`).
4. **Prove a guard by deleting it**, and check the test fails *for that guard's reason*
   rather than a neighbour's.
5. **Have a different context verify the fix than wrote it**, before commit rather than at
   review time — the only item here that addresses the cause rather than a symptom.

### 5.20 Re-running the finder's reproduction is not a closure oracle

**The shape.** A defect is filed with a `minimal_repro`. Someone fixes it, re-runs that
reproduction, sees it no longer fire, and marks the row closed. The reproduction is the
*finder's* artifact, and it can stop firing for reasons that have nothing to do with the
defect: a line moved, a file was renamed, a guard now exists but cannot fire, a pin was
added that is green against its own subject. The finding's literal wording stops being
true while the defect is untouched.

**Measured, 2026-08-21.** Thirty-one closure verdicts were re-driven with the burden
inverted — default *not closed*, each earned against the genuine prior artifact. Five were
overturned. **Every deviation ran the same direction, over-crediting the fix, with zero
counter-examples in thirty-one rows.** A unanimous direction is a structural bias, not
carelessness, and bias accumulates with volume rather than averaging out. All five
overturns were one shape: a two-limb defect with one limb closed and a pin that made the
pair read as handled. In all five the filed `proposed_fix` was un- or half-implemented,
and in two, implementing it went red at HEAD.

**The rule.** Drive the `proposed_fix`, not the `minimal_repro`. If applying the proposed
fix would still change something, the mechanism is open however quiet the reproduction has
gone. And test the pin the other way round: restore the real pre-change artifact
(`git show <sha>^:<path>`), leave the tests at their new state, and confirm something
**reds**. Reverting the tests alongside the fix makes every change trivially green — that
asymmetry is the whole check.

**Mechanised here**, which is why this section is not advice: `scripts/verify_pins.py`
performs exactly that revert-and-assert-red on a commit or a working tree, in a throwaway
clone, and reports `PINNED` / `UNPINNED`. It is advisory by design — calibration against
twenty real commits found *no* clean rule separating changes that owe a pin from changes
that do not, so it reports honest buckets rather than a hand-written allowlist, and says
so in its own output. That script is Espalier-Harness's own dev tooling and is not
deployed; the procedure above is portable without it.

**The same rule one level up: a review's RECOMMENDATION is a claim too.** Everything
above is about not trusting a *fix*'s own proof. The identical trap sits one altitude
higher, and it is easier to fall into because the recommendation arrives with a
diagnosis attached and feels like a conclusion rather than a proposal.

Measured, 2026-08-21. A multi-agent diagnostic run over this repo produced three
concrete remediations. All three were driven before shipping, and **all three were
wrong** — each for a different reason, and none of them visible without opening the
artifact:

- One fought a *deliberate* design decision. The field it proposed to make required is
  optional on purpose, and the test that says so states the reason in a comment. The
  recommendation had read the schema and not the test.
- One sat on a code path the harm never travelled. The function it proposed to gate has
  zero production callers; the damage had been done by hand-editing the file the function
  writes. Gating it would have felt like a fix and changed nothing.
- One proposed deleting a tool as "runs nowhere." It runs — from a slash command, not
  from CI, and the audit had only enumerated CI. Deleting it would also have demoted a
  section that says *"mechanised here, which is why this section is not advice"* back to
  advice.

Three for three, on recommendations produced by an expensive, adversarially-refuted
review. The cost of checking was minutes each; the cost of shipping any one of them was
a fix that carries the defect it fixes — which is the failure this whole section exists
to describe, arriving through the door marked *solution*.

**The remedy has a shape: extend a check that already runs; never add one that has to
be invoked.** A gate nobody calls is worse than no gate, because it manufactures the
belief that the property is checked. Prefer, in order: widen an existing test's matcher
or fixture; drive the real function as its own oracle; add a case to a suite that
already runs on every change. Reach for a new script only when none of those can express
the property — and treat that inability as evidence the property may not be
machine-decidable at all, in which case the honest move is to **delete or de-scope it
rather than gate it**. Every mechanism that has to be *remembered* competes with every
other rule in the repository for one reader's attention, and that competition is a race
the newest rule loses.

### 5.21 The mutation perturbed the site you were already looking at

**Shape.** You fix a defect, write a regression test, and prove it load-bearing by
mutating the code and watching the test go red. It goes red. The test is still
inert: your mutation perturbed the line you had just edited, so what you proved is
that the test observes *that line* — not that it observes the defect.

**Why it survives review.** Every visible ritual was performed. There is a fix, a
test, and an earned red, and the earned red is the step people trust most.
Reviewers check that a mutation was run, rarely that it was the *right* mutation.

**Measured instance.** A helper gained a new parameter, and two call sites were
updated to pass it. The regression test exercised the helper directly. Neutering
the parameter's use *inside* the helper reddened the test, so the fix was declared
proven. Reverting both **call sites** — the actual pre-fix state — restored the
original defect with every test green: the test pinned the parameter and never the
wiring. Found by an adversarial pass, not by the suite.

**The tell.** Ask which edit the mutation undid. If it is the same edit the fix
made, at the same place, the mutation and the fix are testing each other. A real
mutation reconstructs the *pre-fix state*, which for a multi-site change means
reverting every site, not the most interesting one.

**Related shape — the green negative-twin.** The same session shipped a guard whose
test suite asserted one spelling of an attack was an *accepted gap* while the guard
denied a sibling spelling that delivered identical reach. A passing test asserted
the opposite of the guard's own contract. Whenever a test's job is to document
something as deliberately-not-closed, re-derive that it is still equivalent to
nothing you *have* closed.

**Practice.**
- Mutate the **callers**, not just the callee.
- For a fix that touched N sites, the mutation reverts N sites.
- Prefer tests that drive the real entry point over tests that drive the helper.
- Where the roster of call sites matters, derive it (parse the source) rather than
  hand-listing it — a hand list is a snapshot that stales silently.

**Cross-ref.** §5.10 validation-ritual presence vs firing (the ritual ran; it did
not fire) is the parent shape; this is the case where the ritual fires and still
proves the wrong thing.

### 5.22 The view was bounded, and a bound is indistinguishable from a population

**Signature.** A count is taken from the output of a command that silently limited
what it emitted — `head`, `tail`, `-A/-B/-C`, `sed -n 'a,bp'`, `grep -m`, a paged
viewer — and the number is then carried forward as *the* population. Nothing in the
output marks where the bound fell. A truncated view of a large set and a complete
view of a small set render identically.

**Mechanism.** The bound lives in the *command*, not in the *result*. By the time
the number reaches a document, a decision, or a pack's justification, the bounding
argument is gone and the figure looks like a census. The reader — including the
author, minutes later — has no local evidence that anything was cut.

**Measured instances.** Four in two days, three of them by the same author, each
load-bearing at the moment it was wrong:

| Bound | Claimed | Actual |
|---|---|---|
| `command grep -A 200` | "171 of 173 machine-local offenders are one file; ~2 remain" | **197 files / 1,206 lines** |
| first pattern arm only | "`tracked_noise` flags 215" | **585** (independently re-derived at 589 incl. `.DS_Store`); the largest arm, `^cc/blueprints/` at 370 files, was never counted |
| `sed -n '137,145p'` over a data tuple | "4 retired terms registered" | **7** — caught only because a test was named `test_all_seven_…` |
| `head -12` over a **superseded** pack | "this repo is scheduled to flip public" | the framing had been retired 11 days earlier; the tree is never published |

**The temporal variant is the same failure.** The fourth row bounds in *time*, not
position: `head -12` returned a complete, well-formed, correctly-quoted answer from
a file whose premise had been retracted. Truncation and supersession share the
signature — the output carries no marker of what was cut, whether the cut was
"the rest of the matches" or "the decision that replaced this." A stale artifact is
a bounded view of the repo's history.

**Why it survives review.** The number is *real*. It was produced by a real command
over real data, and re-reading it reproduces it exactly. Re-running the same bounded
command is not an independent check — it is the same instrument, and it agrees with
itself every time. Only a differently-shaped command disagrees.

**Documented is not prevented.** §5.13 (an exit code read through a pipe is the
pipe's) was already in this catalog when the same author read `rc=0` through `| tail`
**twice in one day**, on two gates that had both exited 2. A prose entry did not stop
a live recurrence. Treat that as the argument for a mechanical check rather than a
third catalog row.

**Detection.**
- After any bounding argument, the figure you hold is a **floor**, never a population.
  Label it as one or re-derive it.
- Re-derive with a *counter* over the unbounded stream — `wc -l`, `grep -c`,
  `len()` — not by re-reading the bounded output.
- Prefer a command whose shape cannot truncate. `grep -c` has no `-A`; `len(tuple)`
  has no slice.
- When a count comes from an enumerated structure (a tuple, a table, a config list),
  ask the structure, not a text view of it.

**Contract.** A number that enters a decision record, a pack justification, or a
memory row must come from a command whose output was not bounded — or be written
down as a floor, with the bound named.

**Cross-ref.** §5.13 (pipeline exit-status masking) is the same shape applied to
*status* rather than to *counts* — the pipe bounds which command's result you see.
§18.4 (a derived population blind in exactly one direction) is the sibling where the
population is complete but the *derivation* is one-sided. The temporal variant has a propagation mechanic of its own: a
retraction does not retract the superseded claim's copies, so the retired framing
stays readable — and reconstructable — at every site the retraction did not visit.

### 5.23 The predicate a fix's own paperwork keeps true

**Symptom.** A check is written to detect a defect. The defect is then fixed --
correctly, completely -- and the check goes on reporting it as open. Nobody
distrusts the check, because it fired for a real reason once. The row it guards
is triaged again every review round and survives every time.

**Mechanism.** The predicate matches text that the FIX ITSELF puts on disk. Three
independent instances, all measured on one repo in one day:

* A probe counted how many files contained a retired identity literal. The fix
  replaced that literal everywhere it shipped -- and added a sentence explaining
  *why the literal was retired*, which contains the literal. The count could
  never reach zero, so the fix was structurally unable to report itself.
* A gate asked whether a workflow file contained the string ``schedule:``. The
  workflow had no schedule, and said so, in a comment reading ``NO `schedule:`
  -- DISPATCH-ONLY``. The detector read *documentation of the absence* as
  evidence of the presence, and reported clean across the whole tree.
* Two tracker rows carried probes that asked whether the tracker mentioned the
  work. Filing the rows made both true, so each probe went quiet at the exact
  moment its row was created.

The shape is one step removed from the familiar "test that tests the mock". Here
the subject is real and the predicate is real; what is wrong is that the
predicate's population includes the artifacts a fix produces. Prose about a
thing is not the thing.

**Why review does not catch it.** At authoring time the predicate is correct --
it fires, on the real defect, for the real reason. It only goes false later, and
the later state is the one nobody re-derives. It also fails in the *safe-looking*
direction: a stuck-open check reads as diligence, not as a bug, so the cost is
paid in repeated triage of already-closed work rather than in a visible red.

**Detection.** Before writing a check, ask what the repository will look like
AFTER the fix -- including the changelog entry, the comment explaining the change,
the doc that records the decision, and the tracker row -- and ask whether the
predicate survives it. Prefer a predicate that reads the SUBJECT (the symbol, the
key, the wired behaviour) over one that counts mentions of a string. Where a
string count is the only available oracle, exclude the surfaces on which a fix
writes prose, and say in the check why they are excluded.

**Corollary.** An absence claim needs an oracle that can see structure. Asking
whether a file *contains* a token cannot distinguish a declaration from a comment
denying it; parse for the key.

### 5.24 A leave-one-out census proves robustness to removal, and the next document is an addition

**Symptom.** A pinned measurement over a growing document set — a retrieval
curve, a ranking, a hit count — is declared stable because a census held every
document out in turn and the pin never moved. Then one ordinary document lands
and the pin reds.

**Mechanism.** Removal and addition are different perturbations. Removing any one
document leaves every other competitor in place, so a pin that depends on the
*presence* of several near-equal competitors survives every single removal.
Adding a document introduces a competitor that was not in the census's universe
at all; if it lands near the top of the ranking it displaces one slot, and nothing
in the leave-one-out result bears on that. Measured instance: a slot-equality pin
on a paraphrase-retrieval curve survived a leave-one-out census across every
document in the corpus (258 testable of 285) with zero movement; a single new
catalog entry moved the curve from `[6, 8, 8, 8]` to `[6, 7, 8, 8]`, confirmed
by an A/B on that one file. The census had measured the wrong direction. Volume
alone does not do it — eight synthetic documents added at once moved nothing,
while the one recorded mover shared no token with the row's answer: the effect
ran through a *competitor*, not through the answer. The exposure is
single-document competition for the top slots.

**Why it survives review.** The census is real, exhaustive and reproducible, and
"held out every document" reads as the strongest possible robustness claim. It is
the strongest claim *about removal*. The word "robust" does the smuggling.

**Detection / contract.** Before trusting a corpus-sensitive pin, perturb in the
direction the corpus actually moves: for a growing corpus, *inject* near-competitors
— documents that contend for the pinned queries' top slots — and watch the pin,
rather than (only) holding real ones out; volume without competition proves
nothing. When a pin must survive additions, pin a *shape* — the curve climbs
then flattens — rather than an equality at one slot; and when re-deriving after a
red, do not relocate the equality onto the slot the census itself showed to be the
least stable.

**Related.** §18.4 is the mirror — a population derived from the source under
test sees additions and is blind to removals. §5.15 (an A/B at an unmatched
budget) and §5.21 (the mutation perturbed the site you were already looking at)
for the same family of measurement pins.

### 5.25 The dry run answers for a tree an earlier stage rewrites

**Signature.** A multi-stage command has a preview mode. One stage renders
its output from the tree; an earlier stage writes to the tree. The preview
runs the renderer's classifier against the tree as it is, the executor runs
it against the tree after the earlier stage landed, and the two name
different files for the same run — or the executed run leaves a stage one
round behind, and the next preview reports the command's own work as drift.

**In-repo example.** `upgrade`'s preview classifies the three rendered cc/
docs before the asset writes it is previewing, so on a tree missing one
packaged agent it names `cc/LIVE_SURFACE.md`, which `--execute` then finds
unchanged once the agent lands. The same command seeded the convention docs
*after* rendering the manifest that lists them, where `init` seeds them
before; an adopter who ran `--execute` and re-ran the preview to confirm was
told the upgrade had not taken, and a second `--execute` converged. Both were
driven by the failure-mode review of the `DEF-726` fix (2026-09-10): the
ordering was fixed, the render caveat is declared where the sentence is made
and pinned (`DEF-757`).

**Detection.** For every stage that renders from the tree, ask what an
earlier stage writes that the render reads. Drive it: the preview's named
set against the executor's written set on the same tree, and one `--execute`
followed by a preview that must say "nothing to do".

**Contract.** Order the stages so nothing renders before its inputs land
(`init`'s order is the reference); where a preview cannot render the future
tree, declare the caveat where the sentence is made and pin the convergence.

**Related.** §5.7 producer/consumer parity drift (the sibling where two
modules diverge rather than two modes of one command). §7.4 idempotency
missing.

## 6. Security failure modes

### 6.1 Time-of-check vs time-of-use (TOCTOU)

**Signature.** A security check passes at time T1; the protected
resource is used at T2; between T1 and T2, the resource changed.

**Industry term.** TOCTOU (security literature, formalized ~1996).

**Example.** Check that `path` is safe → open `path` → attacker
symlinks `path` to a target file between the check and the open;
the open hits the attacker's file. Classic suid race.

**Detection.** Static analysis flags `os.path.exists(p)` followed
by `open(p)`; any check-then-use sequence on user-controlled paths.

**Contract.** Use atomic operations: `open(p, O_NOFOLLOW)` checks
and opens atomically. Pass file descriptors, not paths, across
operations.

---

### 6.2 Injection

**Signature.** Untrusted input is concatenated into a structured
string (SQL, shell, HTML, template) without escaping; the input is
parsed as structure.

**Industry term.** Injection (SQL injection, command injection, XSS,
template injection). OWASP Top 10.

**In-repo relevance.** `write_guard` defends against the
bash-injection class for the harness's PreToolUse surface — Bash
tool calls are parsed to extract path targets, and any path matching
a protected zone results in denial. The defense has known scope
limits (see §6.3 path traversal and the variable-indirect expansion
shape under §1.2).

**Detection.** Static analyzers; input-flow analysis. Parameterized
queries / ORMs for SQL. Auto-escaping templates for HTML.

**Contract.** Parameterized queries. Escape at the boundary. Never
concatenate untrusted input into structured strings.

---

### 6.3 Path traversal

**Signature.** User-supplied path component allows escaping the
intended directory (e.g., `../../etc/passwd`).

**Industry term.** Path traversal; CWE-22.

**In-repo example.** Pre-fix, a malicious Bash invocation like
`safe_dir/../tools/cc/hooks/write_guard.py` could bypass the
write_guard's protected-zone check because the normalization
function didn't resolve `..` traversal — the input path didn't
start with `tools/cc/` before the check, but the resolved path
landed at the protected file on disk. The fix: `_normalize_path`
applies `(root / p).resolve().relative_to(root)`, raising
`ValueError` if the resolved path escapes the root; the gate then
checks the resolved path against the protected-zone prefix list.

**Detection.** Code review for any path concatenation with user
input; static analyzers; runtime path-confinement libraries.

**Contract.** Resolve paths and check `is_relative_to(allowed_root)`
before use. Never trust the un-resolved form.

---

### 6.4 Hard-coded credentials

**Signature.** Secrets embedded in source code (API keys, passwords,
tokens, private keys).

**Industry term.** Hard-coded credentials (CWE-798).

**Detection.** Secret scanners (truffleHog, gitleaks). Pre-commit
hooks. Repository-level secret detection.

**Contract.** Secrets in environment variables or secret stores;
never in repo. Rotation policies. Use detection at commit time.

---

### 6.5 ReDoS (regex denial of service)

**Signature.** A regex with catastrophic backtracking takes
exponential time on adversarial input. Worst-case input is often
short and pathological (alternations + nested quantifiers).

**Industry term.** ReDoS.

**In-repo example.** A ReDoS regression suite at `tests/test_redos.py`
enforces a 100 ms per-pattern budget on a 30000-byte worst-case
payload. Constants `_BUDGET_MS` and `_WORST_CASE_BODY_LEN` are
pinned, with freshness fragments pinning both at HEAD so a refactor
that loosens either constant fails the freshness gate. This is a
ReDoS budget receipt — the contract is "every regex used at hook
runtime evaluates in bounded time."

**Detection.** Regex linters that detect nested quantifiers
(`(a+)+`). Time-budget enforcement in test suite for any regex on
user input.

**Contract.** Avoid nested quantifiers. Impose timeout / iteration
budget on regex evaluation. ReDoS budget receipt: an explicit pin
that the regex set evaluates within budget against worst-case
input.

---

### 6.6 Insecure deserialization

**Signature.** Untrusted data is deserialized via a format that
allows code execution (Python pickle, YAML with default loader,
deprecated `eval()` for "config").

**Industry term.** Insecure deserialization (OWASP Top 10).

**Detection.** Static analysis flags `pickle.load`, `yaml.load`
without `safe_load`, any `eval`/`exec` on input.

**Contract.** Only deserialize trusted data with these formats; use
JSON or schema-validated formats for untrusted data; explicit
allowlist of classes for any deserializer that supports class
instantiation.

---

### 6.7 Path spelling-equivalence bypass (CWE-41)

**Signature.** A security deny matches a protected path by an exact (or
lightly-normalized) string, but the operating system resolves a
*different spelling* to the same file. The check says "not protected";
the OS opens the protected byte.

**Industry term.** Improper resolution of path equivalence (CWE-41).
Distinct from CWE-22 traversal (§6.3): no `..`, no directory escape —
the same file under a cosmetically-different name.

**Shapes.**
- Trailing dot / trailing space on a component (`settings.json.` and
  `settings.json ` open the same file on Windows/NTFS).
- NTFS Alternate Data Stream suffix (`file::$DATA`, and the traversable
  directory stream `dir::$INDEX_ALLOCATION`).
- Case folding on a case-insensitive filesystem (`/Users` vs `/users` on
  APFS/NTFS; `relative_to`/`startswith` are case-sensitive).
- Redundant separators (`tools//cc`, a leading `.//`).
- A separator-class the normalizer strips on only one spelling (a
  forward-slash-only env-var/`./` strip that misses the backslash form).
- A `file://` / `vscode://file/` URI scheme on a path field.

**In-repo example.** A hardening pass found ten instances of this shape across
`write_guard`'s protected-zone deny — each a different spelling that
canonicalized to a protected harness file the exact-match check let
through. Whack-a-mole on spellings never ends, so the durable fix is a
single canonicalize-or-fail-closed chokepoint: `normalize_path` /
`normalize_bash_path` apply `replace("\\","/")` then `lstrip("/")` after
every prefix strip plus `expanduser`; `_protected_zones._fs_equiv`
strips trailing-`. ` + ADS + NFKC/casefold per component. The fold is
**asymmetric** — all components for the *protected* test, basename-only
for the *allowed* test — so a forged directory component can never widen
the allowlist (`bench/corpus` entries pin the slash
and fs-spelling shapes).

**Detection.** Earn the gate with each spelling against a known-protected
path — a deny validated only on the canonical spelling has undemonstrated
discriminating power (§1.7). Drive the canonicalizer with the spelling
families, not one literal.

**Contract.** One canonicalize-or-fail-closed chokepoint shared by every
path-deny reader; never compare an un-canonicalized path. Each new
spelling earns a corpus row.

**Status: the chokepoint landed, but two shapes it listed were not actually
closed by it.** An adversarial pass on the MCP leaf-walk
found two of the spellings enumerated above live against `check_mcp` — on the
*canonical* path fields, not just keys:

- **`file://` URI scheme** — `normalize_path`/`normalize_path_str` never
  stripped a scheme, so `file:///<root>/tools/cc/hooks/write_guard.py` survived
  `normpath` as a literal `file:` first component, failed the under-root test,
  and read as out-of-repo → **ALLOW** (including the kill-switch flip via
  `file:///<root>/.claude/settings.json`).
- **Fullwidth-solidus `..` traversal** — the NFKC fold ran in
  `_fs_equiv` *after* `normpath`, so `safe／..／tools／cc／…` (U+FF0F separators)
  reached `_fs_equiv` with `..` un-collapsed and read as unprotected. (Distinct
  from §9.3, which folds fullwidth *component names* correctly — the gap was
  fullwidth used as a *separator* for traversal.)

The fix: moved the NFKC fold into the shared `_clean_path_prefixes`
chokepoint **before** `normpath`, and added a `file://` scheme strip there, so
both normalizers (resolve-based and FS-free) close both shapes. Pinned by
`tests/test_write_guard.py::TestClassA1PathCanonicalization`
(`test_file_uri_scheme_protected_denied`, `test_fullwidth_solidus_traversal_denied`).

**Residuals (open):**
- **MCP key-as-path WRITE bypass** — a path→content-map tool keyed by a
  protected path (`{"changes": {"<protected>": "<bytes>"}}`). An
  attempt to close it (emit dict keys as candidate leaves) was reverted: with
  no reliable write-intent classification, `check_mcp` (which runs on *every*
  `mcp__*` tool) over-blocked benign reads that key data by filename. Closing it
  needs a write-intent model. It was consciously
  **frozen** under the workflow-toolbelt governing frame — a crafted bypass,
  not a plausible operator slip — rather than closed (see §6.10). Not owed work.
- Other path-bearing URI schemes / percent-encoded keys (downstream-MCP-server
  dependent — only exploitable if the server decodes before writing).
- ~~The Bash-channel `normalize_bash_path` fullwidth sister-site~~ — closed
  (annotated 2026-09-14): the Bash channel now NFKC-folds before
  `normpath` like the Write channel; pinned over both channels by
  `tests/test_write_guard.py::TestClassA1PathCanonicalization::test_fullwidth_solidus_traversal_denied`.
- Windows device/extended-length/UNC prefixes (`\\?\`, `\\.\`, `\\?\UNC\`) —
  exploitability unverified on POSIX, owes a Windows-host check.

**Related.** §6.3 path traversal (CWE-22 `..`; there `resolve()` is the
fix). §6.8 filesystem-alias identity bypass (CWE-59 — same goal via an
alias, not a spelling). §9.1 path normalization. §9.3 ASCII-only string
ops (the `.lower()`-vs-NFKC sub-case).

---

### 6.8 Filesystem-alias identity bypass (CWE-59)

**Signature.** A protection checks identity by **name/path** when the OS
resolves identity by **inode/target**. An alternate filesystem reference
to the same object — a symlink, a hardlink, a parent-directory symlink —
is a different name for the same protected bytes, so the name-based check
never fires.

**Industry term.** Improper link resolution / link following (CWE-59).
Distinct from §6.1 TOCTOU: that requires a *race* (the target is swapped
between check and use); these aliases are **static** — check and use see
identical filesystem state.

**Shapes.**
- A reader opens a governed file with `exists()` + `read_text()` (follows
  a symlink); the symlinked content drives a gate decision.
- A write lands on an unprotected name that is a **hardlink** to a
  protected file — `resolve()` cannot follow a hardlink, so a
  resolve-based check passes while the write rewrites protected bytes.
- A **symlink is created into** a governed zone, defeating the name-based
  `_is_protected AND NOT _is_allowed` predicate.
- A final-component-only `O_NOFOLLOW` is defeated by a symlinked
  **ancestor** directory.

**In-repo example.** A hardening pass closed two halves of this. Reader side: a
single symlink-refusing reader `read_text_nofollow` bounded to the root
(fd-level `O_NOFOLLOW` + ancestor-symlink refusal) routed through every
gate-opening governed-path reader, so a symlinked `execution_plan.json`
reads as "malformed" and the plan-gate stays closed. Write side: an
inode-keyed deny `aliases_protected_inode` — a write whose existing
target is an `nlink>=2` regular file whose `(st_dev,st_ino)` is in the
protected-not-allowed inode set is denied on all write channels — plus
an allowlist-blind symlink-creation deny. The
write-side verb-name enumeration is a documented inherent heuristic,
reader-mitigated.

**Detection.** Forge each alias (symlink, hardlink, parent-symlink) at a
protected path and assert the reader refuses / the write is denied — with
a control that proves the same channel CAN open a legitimate file, so the
refusal isn't vacuous (§5.10).

**Contract.** Gate-opening readers use a symlink-refusing reader bounded
to the root; write denies key on inode identity, not just the path
string; a symlink may never land in a governed zone on any channel,
allowlist-blind.

**Related.** §6.1 TOCTOU (the racing cousin; symlink there is the swap
vehicle, here a static alias). §6.3 path traversal (`resolve()` is the
fix there, but it *follows* a symlink and *cannot* follow a hardlink, so
it is the attack vector here). §9.2 POSIX-only file flags (`O_NOFOLLOW`
needs a Windows guard — the inverse concern).

---

### 6.9 Closed-set under-extraction in a deny path

**Signature.** A sound downstream deny is fed candidate targets by an
extractor that surfaces only a **closed enumeration** — a finite key
tuple, a top-level-scalar-only walk, a single-extension glob, a finite
verb list — over a domain that is structurally **open** (arbitrary keys,
arbitrary nesting, every valid extension). A valid-but-unenumerated
member is never inspected, so the per-member deny never fires and the
operation fails **open**. Per-member patching is whack-a-mole; only a
domain-complete walk closes it.

**Shapes.**
- A closed path-field tuple (`MCP_PATH_FIELDS`) misses a tool whose path
  key is outside the set (`output_path`, `dest`, …).
- A top-level-scalar extractor misses paths nested in a list of objects
  (`files=[{path: …}]`, `batch.files[*].path`).
- A single-extension glob (`glob('*.yml')`) misses the sibling extension
  (`security.yaml`).
- A finite verb list (a symlink-verb enumeration) misses a synonym.

**In-repo example.** An MCP write extractor checked only a closed
10-field tuple read at the top level, so a write tool with an
unenumerated key — or a path nested one level down — slipped past
`write_guard`'s protected-zone deny (a live freeze-blocker). The durable
fix is a key-agnostic, depth-bounded leaf-walk `iter_mcp_path_leaves`
that yields every path-shaped leaf and fails **closed** on an
unverifiable payload. The sibling instance — the
public-vuln-template scan globbing `*.yml` only — was closed separately:
`_check_security_policy` now globs `*.yml` **and** `*.yaml`.

**Detection.** For each closed allow/extract set feeding a deny, ask: "is
the inspected domain finite or open?" If open, an enumeration is a
fail-open — drive it with an unenumerated member and watch the deny miss.

**Contract.** When the deny domain is open, the extractor must be
domain-complete (key-agnostic bounded walk; glob the extension family)
and fail **closed** on anything it cannot verify — never a finite
enumeration.

**Related.** §1.11 gate credibility (a gate over a *finite, knowable*
surface set — distinct: there the fix is a surface registry; here the
domain is open and only a walk closes it). §10.8 enumeration-shadow leak
(a too-strict *denylist* near-miss — inverse polarity). §6.7 path
spelling-equivalence (the sibling string-level under-match).

---

### 6.10 Accept-and-leave: governing-frame-bounded non-fixes

**Signature.** A genuine latent gap whose *fix* costs more than the gap
costs — because closing it would add false-positive friction, or because
it is unreachable by the actual threat model (operator / AI **mistakes**,
not a motivated attacker — see the workflow-toolbelt frame in
`docs/POSITIONING.md` (Espalier source repo — not deployed by `init`) and the
workflow-toolbelt frame). Espalier records these as deliberate non-fixes
rather than pretending they don't exist or shipping an inert "fix" that
reads as coverage.

**In-repo accept-and-leave register.**
- **Plan-hook symlink-resolution divergence** — a divergence in the plan-hook
  pair, **inverted** from how it was first recorded here: `plan_guard` (the
  **blocking** PreToolUse
  hook) resolves symlinks on the edited path via `_normalize_path` and refuses
  on the canonical path, while `task_router` (the **advisory** UserPromptSubmit
  hook) does no such per-file resolution — it routes on prompt scope + plan
  state. Because the looser side is the advisory one, the divergence has no
  enforcement consequence. Leave.
- **Grouped-quantifier ReDoS-scanner gap** — `_BARE_DOTSTAR_RE` (the
  ReDoS-budget scanner) misses grouped
  `(.)*`. A gate-*gap* in a detector, not a live ReDoS: no
  catastrophic-backtracking regex is reachable in the shipped code. Leave
  until a real instance appears (then earn the gate against it).
- **Speedbump/plan TOCTOU lost-update across sessions** — speedbump-flag and
  execution-plan TOCTOU **lost-update**
  across CONCURRENT sessions. The atomic write already prevents
  *corruption*; the residue is only a lost update that self-heals next
  run. Not a single-operator slip (the governing threat). Leave. (See
  §6.1 TOCTOU for the racing-corruption cousin that IS defended.)
- **Predicate-flip detection in guard helper files** — adding
  `_protected_zones.py` / `_bash_patterns.py`
  to the CP-GATEWEAKEN keystone's `_GUARD_FILES` is **inert**: those files
  deny via bare `return True` from named predicates, carrying no
  deny-token substring, so the removal proxy never fires on them. The
  only token that *would* fire (`return True`) over-fires on every benign
  `return True` removal across all guard files — a soft-checkpoint storm
  (false-positive friction = the cardinal sin). Only the safe half shipped
  (`block(` / `return block` added to `_DENY_TOKENS`, catching
  the real `config_guard` / `stop_gate` deny-removal). Detecting a
  predicate-flip in the helper files needs a separate **named-predicate
  allowlist** mechanism, deferred — not a token bolted onto a proxy whose
  whole value is staying quiet on benign edits.
- **Freshness `oldest_sha` chronological-min window** — the proposed fix (a
  chronological-min freshness window) was **dropped** after an adversarial pass
  found it introduces a critical false-positive; per-fragment-pin
  counting shipped instead. The chronological-min approach is the accept-and-leave
  residue — not re-litigated without new evidence. (The rationale is the prose
  above + `espalier/scanners/freshness.py`.)

**Post-snapshot accept-and-leave (deferred ledger).**
The register above is the original snapshot; later rounds added these, each
re-verified as still-correctly-deferred under the same frame:
- **Count-claim regex widening** — widening over-fires on subset-prose ("4 of the
  hooks"); the measured false-positive rate makes the widen net-negative. Leave.
- **`magic_depth` chained-`.parent` widening** — trips the zero-UNPINNED
  gate on ~228 benign sites. Leave.
- **Vacuous str-contains-Path detector** — low-signal, friction-or-noise
  to close. Leave.
- **espalier → tools/cc forward import guard** — *not* deferred. The forward AST
  guard already
  exists as
  `tests/test_contracts.py::test_espalier_does_not_import_tools_cc_except_sanctioned`.
  Earlier bundled with the str-contains-Path detector as "leave"; corrected
  here — this is **CLOSED**.
- **Freshness rel-import under-count** — `freshness._resolve_bound_closure` (in
  `espalier/scanners/freshness.py`, not the top-level shim) under-counts
  relative-import callers (`from .x import f`). A friction-FREE
  false-negative that only bites an adopter using relative imports AND
  `bound_closure=true` (FRESHNESS.md says use sparingly); in-tree impact is zero
  (espalier/ has no relative imports). Named here (node.level package-path
  reconstruction is the mechanism) so a future pack can pick it up — not worth
  the closure-reconstruction code now. **CLOSED 2026-09-08** (ledger
  `DEF-410m`): the walker resolves `node.level` against the importer's package
  and reads `node.names`, and the zero-impact claim above was wrong on the
  second spelling — `from espalier import managed_markers` in `fuse.py` and its
  test were invisible to the `marker-contract` closure (21 files, now 23).
- **`.mailmap` identity** — the private-hostname author identity
  (`<…@PRIVATE-HOST.local>`, hostname redacted — this file ships in the sdist +
  every fusion) is an outward-facing operator IDENTITY decision: a
  committed `.mailmap` *publishes* a chosen public address, so it is left to the
  operator rather than auto-applied. Distinct from the personal-address-in-package-
  metadata decision.
  **RESOLVED, THEN REVERSED — and the reversal is why this entry still earns its
  place.** A `.mailmap` did land, mapping the laptop identity to the operator's
  published address. It was removed again in `46af0e6`, for a reason worth stating
  precisely: the mapped address appeared in **zero** commits, so the file was a
  no-op. Its one real residue was the tagger field on 19 annotated tags — which
  `.mailmap` does **not** remap at all; those tags were re-created instead. There
  is no `.mailmap` in this tree today.

  Treat that as a *dated* status, not a permanent one. At the time of removal every
  commit carried one identity; a name-only variant has since appeared, so
  `git shortlog -sne` currently reports two rows for the same address. That is
  precisely the shape a `.mailmap` line would collapse — which leaves the decision
  live, still an operator call, still not auto-applied.

  The address itself is deliberately **not** quoted here any more. This file is a
  seed `espalier init` writes into an adopter repository, so anything in it lands in
  third-party trees. A contact address belongs only in a body whose *purpose* is
  contact — a security-contact file, a code-of-conduct file, package metadata —
  never in a decision record that merely mentions one. Note the shape of the
  near-miss: the stale **RESOLVED** claim was what kept the address looking
  load-bearing, so a false status line was holding a privacy leak in place.

  The decision-shape is preserved because it is an operator call, not a defect — a
  future fusion/adopter faces the same choice, and `fuse` must not auto-apply one.
- **Vuln-template redirect window** — a proposal scoped the
  issue-template redirect-excusal check (`"do not"`) to a window around the
  "report a vulnerability" solicitation, to close a false-negative (an unrelated
  "do not" elsewhere excuses a genuinely-leaky template). An adversarial pass
  found the window *widens* this release gate's deny predicate: a legitimate
  multi-section template whose redirect sits outside the window would
  false-fail. Reverted to the whole-file check (fires only when NO redirect
  appears anywhere — never false-positives on a template that has one). The
  trivial-defeatability is the accepted residue under the frame (a false-negative
  in a controlled-template gate beats a false-positive); a real fix needs a
  redirect-detection mechanism with its own false-positive analysis, not a window
  bolted onto a docs-and-tests pack.
- **PowerShell target-aware delete (REVERTED)** — a plan replaced
  write_guard's target-BLIND `Remove-Item -Recurse
  -Force` deny (which denies *every* recursive force delete) with a target-aware
  PowerShell tokenizer, to stop false-firing on a benign `Remove-Item -Recurse
  -Force node_modules` (the bash `rm -rf node_modules` is allowed). The mandatory
  adversarial pass (17 agents, empirical re-runs) returned **12 confirmed
  survivors**: catastrophic FALSE-NEGATIVES the narrowing let through —
  `HKLM:\`/`Cert:\`/`WSMan:\` PSDrive provider ROOTS (registry-hive / cert-store
  wipe; `_PS_ROOT_RE` matched only single-letter `X:` drives), `-fo`/`-for`/
  `-recu` parameter-PREFIX abbreviations (PowerShell resolves any unambiguous
  prefix; the flag regexes matched only `force|f` / `recurse|recur|rec|r`),
  `@params` splat, and `../../../..` traversal — PLUS cardinal-sin
  FALSE-POSITIVES (`-Confirm:$false` idiomatic suppression and `-fi *.tmp`
  abbreviated `-Filter` both mis-parsed as catastrophic targets). **Root cause:**
  a PowerShell-faithful predicate (provider drives, prefix-abbreviation
  disambiguation, splatting) cannot be developed OR verified on the maintainer's
  Darwin host — there is no PowerShell to test against, and the pass found 6+
  false-negatives the author could not have caught by inspection. **Resolution:**
  reverted to the original target-blind deny. Its failure mode is the SAFE
  direction for an irreversible op — it over-denies benign Windows deletes
  (friction, with the maintenance-mode escape hatch) but has **zero**
  false-negatives. A correct target-aware PS predicate needs a real Windows
  runner (the pack's explicit Scope-out: "execution on a real Windows host").
  The three sibling deny-predicate changes (`.github/workflows/` self-host-only
  prefix, `git reset --hard` → CP-DISCARD soft tier, `cc/` reserved-dir note) all
  passed the same adversarial pass with **0 survivors** and landed. Lesson: a
  deny-predicate
  *narrowing* trades a false-positive for false-negative risk; never ship one you
  cannot empirically test on its target platform — the adversarial-pass gate is
  load-bearing, not ceremonial.
- **`fuse` bench `--update-canonical` → finish-up, NOT `fuse_repos`** —
  the operator chose "run install-ci + analyze + bench inside `fuse_repos`" (one
  command wires everything). install-ci + fingerprint landed there cleanly, but
  running the real `bench/run_benchmark.py --update-canonical` against a FRESH
  fusion fail-closes by design: the bench corpus is espalier-self-referential (it
  attacks espalier's own self-host protected surface), so a fusion that has not
  yet repurposed the corpus legitimately scores <100% (measured: 13/155 unblocked),
  and the canonical-update guard correctly REFUSES to write a regression into the
  credibility surface. Baking a step that always fails into the core command is
  worse than not running it. **Resolution:** install-ci + fingerprint run in
  `fuse_repos`; the bench scoreboard became an explicit FINISH_UP step (repurpose
  the corpus for the host FIRST, then `--update-canonical`). The operator's intent
  (don't surprise the operator with manual steps) is honored by the printed
  finish-up checklist. Lesson: "run it in the bootstrap" is sound only for steps
  that can SUCCEED in a fresh fusion — verify by running the real thing, not the
  earn-the-red proxy (the untrusted-oracle discipline caught this).
- **`_matches` prefix-fragment matching is intentional, NOT a bug** —
  an adversarial pass flagged `fuse._matches` for matching a string-prefix
  without a path separator (`'scripts/release_check.py'` would match a
  hypothetical `.pyx`) and a bare dir name against a `dir/` pattern. Both are
  REFUTED: the `HARNESS_EXCLUDE` design deliberately uses bare prefix FRAGMENTS
  (`.claude/workflows/_tp1` matches `_tp169_*`, `_tp171_*`), so the proposed
  "require `pat + '/'`" fix returns False and would un-exclude all 19 tp-workflow
  one-shots (a real leak). The looseness is load-bearing. The genuine
  component-boundary refinement (distinguish prefix-fragment from exact-file
  EXCLUDEs) is deferred; it needs its own design + tests, not a naive
  separator append. Recorded so a future reviewer does not re-flag the intentional
  shape. (A finding is a claim until it is independently verified: an
  adversarially-"confirmed" finding is still a claim — the verifier missed the
  EXCLUDE-fragment design.)
  **Update — the deferred file refinement has since landed.** `fuse._matches`
  now matches a non-`/` (file) pattern by EQUALITY — a sibling like
  `scripts/release_check.py.bak`/`.pyx` no longer over-matches — while the
  trailing-`/` DIR branch is unchanged. The `_tp1`-FRAGMENT premise above is now
  STALE: `HARNESS_EXCLUDE` excludes the workflows via the whole-dir
  `.claude/workflows/` prefix (+ `bench/demo/`) and six EXACT `scripts/*.py`
  paths, so nothing relied on file-pattern `startswith`. Behavior-preserving —
  the overlay set is byte-identical across all 814 tracked files. Net: the refute
  correctly protected the dir-fragment exclusions, but the file/exact looseness it
  deferred was a latent bug, now closed.
- **`python3` headline DECLINED — collides with the operator-docs
  portability contract** — a proposal swapped `python -m espalier fuse` →
  `python3 …` in the README + QUICKSTART headlines, on the reasoning that bare
  `python` is "command not found" on stock macOS. But `python3 ` is a Unix-only
  token: the operator-docs portability contract forbids it in tracked operator
  docs (stock Windows has no `python3` shim), and the settled convention is
  bare `python` in doc bodies plus a "try `python3` first, fall back to `python`"
  prose note. Mechanical contract beats instruction-layer suggestion, so the swap was
  REVERTED (both headlines kept bare `python`). The macOS-stock-`python`-missing
  concern is real but left UNRESOLVED here — reconciling it (a per-OS note, a `py`
  launcher, or amending the portability contract to allow `python3` in
  fusion-install docs specifically) is its own decision, outside the narrow
  doc-parity scope. The pack-artifact review rated checklist item 6
  ("conflicting prescriptions") PASS; it did not cross-check the swap against the
  portability contract — the full suite did. (Again: a
  "confirmed" finding is still only a claim until independently verified.)
- **`_is_pytest_shaped` reconciliation — `startswith` → exact, a
  deliberate advisory-set widening** — a refactor unified the two divergent
  pytest-shape sniffers in `stop_gate.py`: `_parse_pytest_positional_args` used
  exact `tokens[0] == "pytest"`, while `_resolve_core_tests`'s inline
  `has_pytest_shaped` used the looser `c.strip().startswith("pytest")`. The shared
  `_is_pytest_shaped` predicate keeps the STRICT (exact first-token / exact
  `-m pytest` prefix) rule. This is a deliberate behavior change in ONE direction:
  a fingerprint `test_command` like `"pytest-randomly -p no:foo"` was previously
  classified pytest-shaped by `startswith` and therefore SUPPRESSED the
  `dormant_non_pytest` advisory; under the exact rule it is correctly NON-pytest
  and the advisory FIRES. The conservative direction is correct because
  `has_pytest_shaped` gates only an advisory (not a deny/run path), and stop_gate
  is a blocking gate where a false "pytest-shaped" verdict silently hides a real
  Gate-1 dormancy. No Gate-1 deny or run behavior changes. Recorded so a future
  reviewer reads the widened-advisory set as intentional, not a regression.

**Detection.** When a fix is proposed for a low-severity gap, ask two
questions before writing it: (1) does the fix add friction on benign
edits or a false deny? (2) is the gap reachable by an operator/AI
*mistake*, or only by a deliberate attacker? A "yes" to (1) or a "no" to
(2) is a candidate for accept-and-leave — record it here with the
reasoning, don't ship an inert or noisy fix.

**Contract.** An accept-and-leave decision is documented (here + the
governing memory), not silent. A deferred fix names the mechanism the
real fix would need so a future pack can pick it up; it never ships an
inert change that reads as coverage.

**Related.** §1.11 gate credibility (an inert fix is a gate that grades
itself green). §11 AI-collaboration (a plausible-but-inert "fix" is the
shape an over-eager collaborator ships). The workflow-toolbelt governing
frame in `docs/POSITIONING.md` (Espalier source repo — not deployed by `init`).

---

## 7. Distributed and reliability failure modes

### 7.1 Cascading failure

**Signature.** Failure in one component overloads downstream
components, which fail and overload further downstream. The system
moves from one healthy state to one degraded state in seconds.

**Industry term.** Cascading failure; circuit breaker pattern is
the mitigation.

**Detection.** Chaos engineering. Load testing under partial failure.

**Contract.** Circuit breakers. Bulkheads (isolated thread pools).
Timeout discipline. Each component must degrade gracefully without
propagating its own load to its peers.

---

### 7.2 Retry storm / thundering herd

**Signature.** Many clients retry at the same time after a failure,
causing the recovering service to fail again.

**Industry term.** Thundering herd; retry storm.

**Detection.** Load tests with synchronized retry start. Production
telemetry showing retry-induced second-wave failures.

**Contract.** Exponential backoff with jitter. Coordinated retry
budget. Server-side rate limiting per client.

---

### 7.3 Split-brain

**Signature.** A distributed system partitions; two halves each
think they're authoritative. Subsequent partition heal creates
conflicting state.

**Industry term.** Split-brain.

**Detection.** Chaos engineering: induce partitions.

**Contract.** Quorum-based decisions. Fencing tokens (a monotonic
ID that increments per leadership change). CAP theorem discipline
(CP or AP, declared not both).

---

### 7.4 Idempotency missing

**Signature.** Replaying the same request twice produces different
state than playing it once.

**Industry term.** Non-idempotent operation.

**Detection.** Test: send same request twice; assert state is
identical.

**Contract.** Idempotency keys. Operations designed to be
replayable. State changes recorded in append-only logs that allow
re-reading without re-applying.

---

### 7.5 Clock skew assumption

**Signature.** Code assumes clocks are synchronized across nodes.

**Industry term.** Distributed time problem.

**Detection.** Test with deliberately skewed clocks.

**Contract.** Logical clocks (Lamport, vector). Never trust
`time.time()` for ordering across nodes. NTP is necessary but not
sufficient.

---

### 7.6 Race condition

**Signature.** Two concurrent operations interleave in a way that
violates an invariant.

**Industry term.** Race condition.

**In-repo example.** Multi-agent sessions where the Stop hook fans
out to code-reviewer, architecture-analyst, and test-writer in
parallel. Each subagent calls
`cognitive_blueprint.py record --kind decision --description "..."`.
About 20% of records were silently dropped pre-fix because three
processes simultaneously load-modify-saved the same blueprint JSON.
Fixed by wrapping load-modify-save in `_acquire_write_lock`, using
`fcntl.flock` LOCK_EX on a sibling `.write.lock` file. The
load-modify-save sequence becomes atomic; concurrent recorders
queue up behind the lock.

**In-repo example (shell layer).** The autonomous-execution driver
(`scripts/run_pack_chain.sh`) verified each pack's commit with
`git log --oneline -8 | grep -qi "$pack"` under `set -o pipefail`. `grep -q`
exits and closes the pipe on its first match while `git log` is still writing;
`git log` then takes SIGPIPE (exit 141) and `pipefail` propagates the
non-zero, intermittently false-failing the check though the commit existed.
The "timing" theory was disproved by reading the commit *timestamps* (an
untrusted-oracle move — the rendered "no match" was the unreliable frame).
Fixed by dropping the pipeline: capture-then-grep via a here-string
(`grep -qi "$pack" <<<"$(git log --oneline -8)"`) — no pipeline, so `pipefail`
cannot trip it.

**Detection.** Stress test with many threads. Thread sanitizers.
Logging at lock acquisition / release to detect contention.

**Contract.** Locks. Atomics. Lock-free data structures with
proper memory ordering. For file I/O: filesystem-level locking
(`fcntl.flock`) wrapped in helper functions.

---

### 7.7 Timeout misconfiguration

**Signature.** Timeout too short → false failures on
slow-but-correct operations. Too long → resource leak on hung
operations.

**Detection.** Production telemetry: track operation duration
distribution. Compare timeout to p99 latency.

**Contract.** Timeout = p99 latency × 2 (or some empirically-tuned
multiple); review periodically. Document the rationale.

---

### 7.8 Atomic write vs atomic update

**Signature.** "Atomic write" creates a tmp file + rename — this is
an atomic CREATE but NOT atomic UPDATE if multiple writers race.
The rename is atomic per syscall, but two concurrent
write-tmp-then-rename sequences can produce a lost-write race.

**In-repo example.** Same as §7.6 — the multi-agent blueprint
recording case. The atomicity of the rename hid the race because
operators thought "atomic write = safe under concurrency." It isn't.
Concurrent updates require explicit locking around the
load-modify-save sequence, not just atomic-write on the final step.

**Detection.** Stress test with concurrent writers. Document the
distinction in the helper module that exposes the atomic-write
primitive.

**Contract.** `fcntl.flock` (or proper file locking) around the
full read-modify-write cycle. Helper module exposes a single
`atomic_update` function that wraps lock acquisition, load, modify,
save, lock release.

---

### 7.9 Deferred work silently lost in a one-shot `claude -p`

**Signature.** A one-shot `claude -p` agent (no interactive session, no
`/loop`) runs its final gate — the full suite, a fan-out review — as a
*background* task and yields to wait on it (Monitor / ScheduleWakeup / a
background Workflow), the reflex carried over from interactive or loop mode.
The moment it yields, the session ends with a clean exit 0. Everything
deferred — including the commit — is silently lost. The run "succeeds"
(exit 0, not a budget cap) yet HEAD never moved.

**Mental model.** A relay runner who lets go of the baton to check the
scoreboard — there is no next leg to receive it, so the baton just drops. A
one-shot has no loop to resume *into*; backgrounding assumes a future turn
that never comes.

**In-repo example.** The autonomous pack-execution driver
(`scripts/run_pack_chain.sh`) runs each pack as its own fresh `claude -p`
session. The first pilot did all the work, backgrounded the final suite, and
exited 0 with nothing committed — each pack "passed" while HEAD stayed put.
Fixed at two layers: (1) the goal text instructs the agent to run EVERY gate
synchronously in the foreground and read its result in the same turn, carrying
through to the commit in one continuous run — never background, Monitor,
ScheduleWakeup, or Workflow in `-p`; (2) defense in depth — the driver
independently verifies the commit exists (`git log`) before advancing, so an
exit-0-with-no-commit halts the chain instead of compounding.

**Detection.** For any unattended one-shot agent, assert the *side effect*
(the commit, the written artifact) exists after exit — never trust exit 0 as
proof of completion. Grep the agent's transcript for backgrounding tool calls
made in a one-shot context.

**Contract.** In a one-shot `-p`, every gate runs synchronous/foreground
inline and the run carries through to its durable side effect in one
continuous pass; an independent post-run check verifies that side effect.
Exit 0 alone is not acceptance. See `docs/AUTONOMOUS_EXECUTION.md`
(Espalier source repo — not deployed by `init`).

**Related.** §1.1 convergence theater (a green signal that proves nothing);
the untrusted-oracle discipline (verify the side effect, not the reported
status).

---

### 7.10 Self-perpetuating heartbeat loop

**Signature.** A workflow arms a "fallback heartbeat" `ScheduleWakeup` with
`prompt: "<<autonomous-loop-dynamic>>"` (a hang-safety net), then the session
continues. The sentinel fires → Claude Code injects an "Autonomous loop tick"
prompt that instructs the agent to *reschedule the same sentinel at end of turn*
→ the loop self-perpetuates with no `/loop` command, no cron, and no obvious user
toggle. The operator may not realize the session is now timer-driven.

**Mental model.** A thermostat someone wired to its own switch — each cycle arms
the next, and nobody remembers flipping it on.

**In-repo example.** A `ScheduleWakeup` heartbeat armed during a prior workflow
(as a hang-fallback) kept re-arming across legs/compactions; the operator asked
"please explain this loop, I either turned it on without knowing, or something we
built activated it." It was never a `/loop` command. Recognize it by the repeated
"Autonomous loop tick" prose opening turns + a `ScheduleWakeup` call with the
sentinel prompt at end of turn. Stop it by **omitting the reschedule** (or Esc),
`TaskStop`-ing any armed `Monitor`, or letting the 7-day auto-expiry catch it
(there is no cron to `CronDelete`).

**Detection.** Watch for turns opened by loop-tick prose rather than a user
prompt; grep the transcript for `ScheduleWakeup` calls carrying the sentinel.

**Contract.** Don't arm hang-fallback heartbeats casually; if you must, log them
visibly and prefer a bounded one-shot over a self-re-arming sentinel. See
`docs/CC_AUTOMATION.md` §3 (Espalier source repo — not deployed by `init`) and `docs/SHARP_EDGES.md`.

**Related.** §7.9 deferred work lost in a one-shot `-p` (the other autonomous-loop
control surprise); the untrusted-oracle discipline (you're being re-invoked on a
timer — verify *why* a turn started).

---

## 8. Observability failure modes

### 8.1 Missing correlation IDs

**Signature.** A request's path through the system can't be
reconstructed from logs because no unique ID flows through. Debugging
requires temporal correlation, which is fragile.

**Detection.** Random log audit: pick a transaction, try to find
every log line related to it. If you can't, correlation is broken.

**Contract.** Inject correlation ID at the boundary; propagate
through all calls; log it on every entry.

---

### 8.2 Mean over percentile

**Signature.** Aggregate metrics report mean, hiding tail behavior.
The mean response time looks healthy; p99 is catastrophic.

**Industry term.** Tail latency hiding.

**Detection.** Compare mean vs p95/p99/p99.9. If the spread is
large, the mean is misleading.

**Contract.** Report distribution, not mean. Default to percentiles
on latency dashboards.

---

### 8.3 Alert fatigue

**Signature.** So many false-positive alerts that all alerts are
ignored. The signal-to-noise ratio approaches zero.

**Industry term.** Alert fatigue.

**Detection.** Alert resolution rate. If most alerts are
"acknowledge and ignore," they're noise. Time-to-action per alert.

**Contract.** Every alert is actionable. Periodic alert audit:
which alerts fire and result in operator action? Which don't?
Mute or remove the latter.

---

### 8.4 Sampling that misses tails

**Signature.** Sampling reduces volume but loses the rare events
that matter most.

**Detection.** Compare sampled to full data on critical metrics.
Errors and slow requests are the events you want; sampling them
out is exactly wrong.

**Contract.** Tail-aware sampling. Always sample errors and slow
requests; sample-rate normal traffic.

---

### 8.5 Vanity dashboard

**Signature.** Dashboard looks good but doesn't predict outcomes.

**Industry term.** Vanity metric (Ries 2011) at dashboard scale.

**Detection.** Ask: "if every number on this dashboard improved
10%, would the system be better?" If no, the dashboard is vanity.

**Contract.** Dashboards tied to declared user outcomes. Cut
metrics that don't change decisions.

---

## 9. Platform and encoding failure modes

### 9.1 Path normalization

**Signature.** Code that works on POSIX paths breaks on Windows
(backslash separator, case-insensitive filesystem, drive letters,
UNC paths).

**In-repo example.** Espalier's architectural rule mandates
`.replace("\\", "/")` for any path comparison. Pre-rule, comparing
`str(Path(...))` directly on Windows returned backslash-separated
paths; string comparison against forward-slash patterns silently
failed. The fix is small: every path comparison runs through a
normalization step. The discipline is universal — even internal
comparisons go through the same normalizer.

**Detection.** CI on Windows. Path-handling test fixtures with
explicit Windows-shape inputs.

**Contract.** Use `pathlib.Path` consistently. Normalize at
boundaries via `str(p).replace("\\", "/")`. The normalizer is a
single helper function that every comparison goes through.

---

### 9.2 POSIX-only file flags

**Signature.** Code uses POSIX-specific flags (`os.O_NOFOLLOW`,
`os.O_DIRECTORY`, `os.O_NONBLOCK`) that don't exist on Windows.

**In-repo example.** `os.O_NOFOLLOW` and `os.O_NONBLOCK` are
undefined on Windows CPython. An inline use like
`os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK` raises
`AttributeError` at module import time on Windows. Two modules —
`espalier/freshness.py` and `tools/cc/_freshness_cache.py` — are
loaded by the statusline and SessionStart hook respectively, so a
Windows operator's first session crashes during the session-start
hook execution. The fix: `getattr(os, "O_NOFOLLOW", 0)` pattern,
which falls back to 0 (no flag) on Windows. A test asserts the
fallback path produces correct behavior.

**Detection.** CI on Windows. Static analysis for direct `os.O_*`
references that aren't `getattr`-guarded.

**Contract.** `getattr(os, "O_FLAG", 0)` pattern for any POSIX-only
flag. Test that the fallback path (0) produces correct, secure
behavior on Windows.

---

### 9.3 ASCII-only string operations

**Signature.** `.lower()`, `.upper()`, `.title()` claim to be
locale-agnostic but are ASCII-only; non-ASCII strings produce
surprising results. Especially dangerous on case-insensitive
filesystems where the comparison needs to be NFKC-aware.

**In-repo example.** Pre-fix `write_guard._is_protected` ran
`.lower()` on both sides of the protected-path comparison. A
fullwidth Unicode equivalent of a protected path component (e.g.,
`ｔｏｏｌｓ／ｃｃ` instead of `tools/cc`) stayed unchanged under
`.lower()`, while APFS resolves both to the same file. The hook
said "not protected" for a path the filesystem treated as
protected. Fixed via `unicodedata.normalize("NFKC", s).casefold()`,
which folds the Unicode equivalents to the canonical ASCII form
AND lowercases according to Unicode rules. A test asserts the
fullwidth bypass no longer works.

**Detection.** Test with Unicode fixtures (full repertoire of
case-foldable characters).

**Contract.** Use `unicodedata.normalize('NFKC', s).casefold()`
before comparing path components. `.lower()` is for display, not
for equivalence.

---

### 9.4 Implicit environment dependence

**Signature.** Code reads `$HOME`, `$TMPDIR`, `$PATH`, etc. without
guarding against absent or malicious values.

**In-repo examples.**

- *`Path.home()` raises on unset HOME.* `Path.home()` raises
  `RuntimeError` on POSIX when `HOME` is unset AND the pwd database
  has no entry for the current UID. The integrity helper at
  `tools/cc/hooks/_integrity.py` uses `Path.home()` to locate its
  audit directory. Pre-fix, in minimal container environments where
  HOME is unset, the raise propagated and the hook exited with
  code 1 on every tool call. The fix: a defensive helper that tries
  `Path.home()`, falls back to `tempfile.mkdtemp` with a stable
  prefix, caches the result at module scope, and validates overrides
  per a strict allowlist.

- *`tempfile.gettempdir()` honors $TMPDIR.* The override validator
  for the audit directory once added
  `Path(tempfile.gettempdir()).resolve()` to its `safe_roots`
  unconditionally. An attacker-controlled shell setting
  `TMPDIR=/etc/cron.d` before launching Claude Code would
  legitimize `ESPALIER_AUDIT_DIR=/etc/cron.d/silent` — the gate
  trusts an attacker-supplied value. Fixed by skipping the
  `gettempdir()` entry when `TMPDIR` is explicitly set; hard-coded
  fallbacks (`/tmp`, `/var/folders` on macOS) are always present
  regardless of TMPDIR.

- *Autonomous "full suite green" can be env-relative.* When an unattended
  agent runs the suite in a dev shell with a stale editable install (a `.pth`
  pointing at a moved/deleted path), `import espalier` fails from a foreign
  cwd, so the agent satisfies the gate only with `PYTHONPATH=repo` — making
  "green" PYTHONPATH-green, not install-green or CI-green, masking real reds
  that require a true install. Mitigation: pin the gate's env — build a clean
  venv, `pip install` the tree, and run the install-green oracle there
  (`scripts/run_pack_chain.sh::verify_install_green`). A subtlety verified
  while building that gate: re-running the *full pytest suite* in the venv is
  NOT sufficient — `pythonpath = ["."]` keeps the source tree on `sys.path`,
  so the suite passes even with the package uninstalled; `espalier selfcheck`
  (which resolves its bundled mirror from the INSTALLED package) run from a
  foreign cwd is the real install-green check. See
  `docs/AUTONOMOUS_EXECUTION.md` (Espalier source repo — not deployed by `init`).

**Detection.** Test with env vars deliberately absent / weird /
hostile.

**Contract.** Default + validate at entry. Don't trust env values
to be safe paths. When an env var influences a security-relevant
decision, treat it as untrusted input.

---

### 9.5 Atomic write vs atomic update

See §7.8. The pattern crosses both reliability and platform
categories.

---

### 9.6 Hook environment inheritance

**Signature.** Hook subprocesses inherit env from the parent
process at launch time, not from the current shell. Mid-session
`export` doesn't reach already-running hooks.

**In-repo examples.**

- See §1.2 ESPALIER_MAINTENANCE_MODE — set before launch, not
  mid-session.

- *Shell-rc `ESPALIER_STOP_GATE=full` runs pytest every turn.* An
  operator who follows "opt in to full stop gate" instructions and
  adds `export ESPALIER_STOP_GATE=full` to their shell rc, then
  forgets about it — every subsequent Claude Code session incurs
  a full pytest run on every Stop event. The harness is noticeably
  slow for ordinary edits, the operator wonders why, and the cause
  is the rc export from months ago. The pattern: prefer bounded
  session scope (`ESPALIER_STOP_GATE=full claude` for one shell; PowerShell:
  `$env:ESPALIER_STOP_GATE="full"; claude`)
  or `.claude/settings.json` under `env` (scoped to the project)
  rather than global rc exports.

**Detection.** Document the lifecycle in the harness's
TROUBLESHOOTING. Test launcher scripts.

**Contract.** Environment configuration belongs in launchers /
project-scoped settings, not in global shell rc files. The
denial-message in `write_guard` for inline env-var prefixes (see
§1.6) actively teaches this distinction.

### 9.7 Version-gated stdlib semantics (supported-runtime behavior skew)

**Signature.** A stdlib API changes behavior across Python versions
*within the supported range*, and the dev host happens to sit on the
version with the safe default — so the bug ships green. Distinct from
§9.1–9.3 (cross-OS / encoding skew on the *same* interpreter): here the
OS is constant and the **interpreter version** is the variable.

**In-repo example.**

- *`Path.rglob` / recursive `glob` follow directory symlinks on CPython
  < 3.13.* `recurse_symlinks` only became default-`False` at 3.13. On a
  directory-symlink **loop** a bare `rglob` raises `OSError(ELOOP)`
  (crash) before any per-path `is_symlink()` filter runs; on a plain dir
  symlink it inflates / double-counts. `pyproject.toml` pins
  `requires-python = ">=3.10"`, so 3.10–3.12 are supported adopter
  runtimes — a first-run crash on a supported version. A first fix patched
  one site (`analyze._iter_files`) on a 3.14 dev host that already has
  the safe default, so the fix could not earn its red locally and the
  CI 3.10/3.12 legs passed because the lock test reached only that one
  function (see §2.8). A follow-up swept the remaining 42 sites to the
  symlink-safe `safe_rglob` (`os.walk(followlinks=False)`, safe on
  **all** versions) and added the §10 recurrence guard.

- *`Path.exists()` / `is_file()` / `is_dir()` / `is_symlink()` raise
  through a parent that denies traversal on CPython 3.10–3.13 and return
  `False` on 3.14.* Every existence check on `.claude/settings.json`
  answered per interpreter: on a locked `.claude`, `doctor` on the 3.14
  dev host listed every deployed file as missing and offered `init`,
  while the 3.10–3.13 CI cells died at the first `exists()` with a bare
  errno line (`DEF-763`, 2026-09-13). The row had been filed as
  Linux-only for want of a Linux host; a `uv` 3.10 venv reproduced it on
  macOS in one run, and a real 3.13 placed the boundary at 3.14, not at
  3.13 as the first cut of the fix assumed (§13.7's ceiling was never
  the obstacle — the interpreter was a minute away). Fixed as a class:
  one errno-classified oracle (`surface_contract.path_presence`),
  `os.path.*` at the uniform yes/no sites, one gate at the command
  layer, and `tests/_legacy_pathlib.py` running the engine under the
  3.10–3.13 bodies on the 3.14 host so every spelling is caught, not
  only the ones a static matcher can name.

**Detection.** When an API's behavior is version-gated within the
supported range, pick the version-agnostic spelling rather than relying
on the host's default. A structural guard (the bare-`rglob` scanner)
catches the *direction* on any host even when the *magnitude* (the crash)
reproduces only on the gated versions — see §13.7.

**Contract.** Code that runs on a `requires-python` range must behave
correctly on the **whole** range, not just the dev host's interpreter.
Prefer the spelling that is safe on every supported version.

---

### 9.8 A stored command *name* is resolved in a different environment than the one that wrote it

**Signature.** A config artifact records a bare executable **name**
(`python`, `node`, `ruby`) chosen by probing PATH at write time, and
something spawns it much later from a different shell. Between the two
moments the name can bind to a different file — or to a stub that is not
an interpreter at all. Distinct from §9.4 (implicit environment
dependence): there the dependence is unrecorded; here it *is* recorded,
correctly, and the recorded thing still resolves to something else.

**Why the name and not a path.** Storing an absolute path is worse, not
better: the obvious candidate is the virtualenv's interpreter, and that
path dies at `deactivate` while the config outlives the shell. So the
name is the right call — which is exactly why the residual risk needs a
check rather than a redesign.

**In-repo example.** `cli._detect_python_command` probes `python` then
`python3`, rejects a venv-only shim (`_resolves_only_inside_a_virtualenv`),
and writes the surviving bare name into `.claude/settings.json` for twelve
hook entries. On Windows the failure completes: the OS ships a Microsoft
Store *App Execution Alias* `python.exe`/`python3.exe` in
`%LOCALAPPDATA%\Microsoft\WindowsApps`, on PATH by default. If the only
real interpreter lives inside the venv, `init` still writes `python`; when
Claude Code later launches from a plain shell, the stub wins, every hook
exits non-`{0,2}`, and per the hook protocol a non-`{0,2}` exit is
**non-blocking** — so `write_guard`, `plan_guard`, `config_guard` and
`stop_gate` all fail **open**. A related gap compounds it: the
detector's only version test is `startswith("Python 3.")`, with no
`>=3.10` floor despite `requires-python`, so a 3.9 host is accepted and
then dies on a `match` statement inside a subprocess whose stderr is
discarded — surfacing as a bare *"auto-start failed"*.

**Where the silence actually was — corrected.** This entry originally said
the guards fail open *"silently"*. They do not: a non-`{0,2}` exit raises a
`<hook name> hook error` notice on **every tool call**
(`docs/external/cc-hook-protocol.md`), so the session is loud. What was
silent is the pair that should have diagnosed it — `init` reported success
and `doctor` reported nothing — which is worse than silence in the
transcript, because the operator is told the install is fine. *Loud but
misdiagnosed*, not silent.

**Why both health checks missed it — the generalizable part.**
`session_start` warned only when `shutil.which(interp) is None`, and the
stub **is** found. `doctor`'s check asked whether the name resolves outside
the venv, and the stub **does**. Both probes were satisfied by the impostor,
because both asked *"does something answer to this name?"* — a
**resolvability** question — when the property that matters is
**identity**.

**Status: implemented.** For two releases this section described the failure
in full while **no code implemented the contract below** — the catalog knew
and the tree did not, which is its own failure mode (a documented remedy
nobody built reads as coverage). Now closed at four sites: the resolver
warns on stderr instead of returning an unvalidated name in silence,
`doctor` gained a third state distinguishing *absent* from *resolves but is
not Python*, and both hook-side probes route through one shared identity
helper. ⚠ **The `>=3.10` floor named in the paragraph above is NOT closed** —
every probe here still tests `startswith("Python 3.")`, so a 3.9 host is
still accepted. That half remains owed.

> **Contract.** A resolvability check is not an identity check. Where a
> stored name is spawned later, verify what the name *is* — run it and
> assert on its self-report (`--version`, a probe line) — not merely that
> `which` returned a path. And run that verification in the environment
> the consumer will use, not the one that wrote the config.

**Detection.** From a shell with **no** virtualenv active, in the target
repo: confirm the interpreter's own version output, and confirm the name
recorded in the config resolves to that same file. On Windows, disable the
Store aliases (*Settings → Apps → Advanced app settings → App execution
aliases*) so a mis-resolved name fails loudly instead of silently. Note
`python3` is the likelier stub there — the portability contract bans the
literal `python3 ` from adopter-facing docs for this reason.

---

### 9.9 A config file your tool wrote is not the encoding your tool will read back

Every settings file starts life as your own UTF-8 write, which is why a reader
that assumes UTF-8 survives review: on the machine where it was written, it is
correct. Then the operator's editor adds a byte-order mark, or a Windows shell
rewrites the file — PowerShell's `Out-File` defaults to UTF-16LE — and the same
bytes are still valid JSON that your reader can no longer parse.

**The shape.** A codebase accumulates N readers of the same config file. Most
route through a BOM-tolerant decoder, because each was fixed the day someone hit
the bug. The next reader is written from scratch by someone solving a different
problem, uses a plain UTF-8 read, and is correct in every test — because every
fixture writes the file the way the tool writes it. Measured in this repo:
sixteen readers of one settings file, six of them plain-UTF-8, against a
paragraph asserting there were seven and that all of them were tolerant.

**Why it stays hidden.** Both failure directions are quiet. A byte-order mark
raises a JSON parse error, which lands in an `except` clause written for
malformed input and returns the empty/default value — so the caller reads
"nothing here" and proceeds. UTF-16 raises `UnicodeDecodeError`, which is a
`ValueError` and NOT a `JSONDecodeError`, so an `except (OSError,
JSONDecodeError)` misses it entirely and the command dies with an opaque codec
message on a perfectly healthy repo. Neither shape appears in a suite whose
fixtures all write UTF-8.

**What it costs.** In this repo, driven: an uninstall silently left every hook
wired in the operator's settings and reported success (0 entries removed against
12), because the read failed into "no entries of ours here". A session-start
warning about a broken interpreter could never fire for the Windows population
it was written for. And a valid file was reported as malformed — a loud alarm at
someone who did nothing wrong.

**Detection.** A prose claim ("all readers decode tolerantly") cannot notice the
next reader; it was wrong here in both directions and enforced by nothing. Make
it a contract: walk the source for reads of that config shape and require each
to route through the shared decoder or carry a written exemption naming why not.
An exemption with no reason is a suppression. See
`tests/test_settings_reader_bom_contract.py` for the census form; it covers the
records an operator is invited to write by hand as well as the settings file,
and it reads the enclosing function's name because a helper's target is named
at its call sites, not at its read -- the site that widening was for was
invisible to a window-only census. And it judges the guard by where the
read's bytes go (the read call inside the helper's argument, or the name it
is bound to consumed by the helper while that binding is live), not by the
helper's name appearing somewhere in the function -- under the name rule a
second strict read added beside a guarded one reported guarded.

**Related:** §9.8 (a stored command name resolved in a different environment),
§18.x (the artifact written to describe a fix is itself unverified).

### 9.10 A cloud-synced filesystem evicts file contents, and `stat` reports the size it no longer has

**Signature.** The OS reclaims space by evicting a file's *contents* while
leaving its metadata intact (macOS iCloud Drive sets `flags=compressed,dataless`;
other sync clients have equivalents). `stat` still reports the true size and
mtime, so every size- or mtime-based check calls the file unmodified. Reads
rehydrate on demand *while the file is still cloud-backed*, which hides the
condition from casual inspection — but a process that `mmap`s the file rather
than reading it (git, for its object store) faults on an unmaterialised page and
dies with **SIGBUS** and an empty stderr.

**In-repo example.** Measured on the maintainer's tree, 2026-08-27 to 08-29. The
repo lived in `~/Desktop` with iCloud Desktop-and-Documents sync on and the disk
at 94%. 48 tracked files and 32 git objects were evicted; `git status` reported
the tree clean throughout. `git push --dry-run` **succeeded on a repo that could
not push**, because dry-run skips packing — the honest oracle is
`git bundle create --all` plus `git bundle verify`, which exercises the same path
a real push does. Two further findings inverted the response:

- **Rehydration works** while the file is still cloud-backed. Forcing a read of
  an evicted file cleared `compressed,dataless` and returned all 32,053 bytes.
  A handoff doc asserting the opposite sent a later session hunting a recovery
  that was never needed.
- **Copying the tree is what makes the loss permanent.** A "backup" taken while
  objects were hollow captured the holes, and outside the sync container there is
  nothing left to rehydrate from. The result inverted the incident's premise: the
  recovery copy was the broken artifact (`git bundle` rc=128, "Could not read
  <oid>") and the original was intact (rc=0, "records a complete history").

Re-measured 2026-08-29 with `optimize-storage` set to `0` and the disk down to
37%: **1,112 files were still evicted.** Neither the setting nor the reclaimed
space stopped it. The working tree was clean only because it was being read
constantly — its protection was *attention*, not configuration, which is exactly
the protection that lapses when a project is archived or set aside.

**Detection.** `find <tree> -type f -flags +dataless` on macOS. Never a size or
mtime comparison — that is the check the failure mode is defined to defeat. For a
git tree specifically, `git bundle create --all`: a proxy that skips packing
cannot answer whether the object store is whole.

**Contract.** Keep a git repo — or SQLite, `node_modules`, VM images — out of a
cloud-synced folder. A `stat`-based freshness or integrity check *cannot* see a
hollow file, so where that honesty is load-bearing, read bytes. And never copy a
tree you suspect is evicted: the copy is the step that converts a recoverable
condition into a permanent one.

**Related:** §9.2 (POSIX-only file flags), §18 (the artifact you author to
describe a fix is itself unverified), and the standing rule that a proxy oracle
is usable for a floor, never for a null.

---

## 10. Detector and scanner failure modes

### 10.1 Single-signal detector over-match

**Signature.** A detector with one weak signal flags too many false
positives; gets disabled or ignored. The detector's claim is
"detects X"; its behavior is "fires on anything resembling X."

**In-repo examples.**

- *`detect_ml_surface` over-firing.* Pre-fix, the ML-surface
  detector fired on `models/` directory alone (matching the
  standard Django / SQLAlchemy / FastAPI layout). It fired on
  `notebooks/` alone (matching tutorial-heavy libraries). It fired
  on the substring `"model"` in `pyproject.toml` (Espalier's own
  pyproject had `"unit: pure function/model tests"` in a pytest
  marker description). Three false positives across three different
  signal types. The fix: require 2+ co-occurring independent
  signals — training scripts present AND ML-dependency imports
  present AND model-config files present (any two of three) — with
  structural binding per signal (e.g., dep imports parsed via
  `tomllib`, not substring grep).

- *NumericContract `\b(N)\b.*keyword` regex over-match.* A doc-claim
  binding test used pattern `r"\b(\d+)\b.*hook"` to extract hook
  counts from doc tables. The `.*` matched across entire ESPALIER_MEMORY.md
  table rows containing "hook" elsewhere — binding the wrong
  number to the contract. Subsequent stale-doc counts registered
  false passes. Fixed by anchoring the keyword immediately:
  `r"\b(\d+)\s+(?:\w+\s+)?hooks?\b"` requires the digit to be
  within ≤2 tokens of `hooks`.

- *write_guard inline-Python false denies.* Verification scripts
  like `python -c "assert 'Bash(rm -rf /*)' in denies"` contain
  the substring `rm -rf /` literally. write_guard's bash-injection
  scanner sees the substring inside the Python code argument and
  fires DENY, even though the Python code is INSPECTING the
  config value, not executing the shell command. Fixed by either
  writing the verification to a temp `.py` file (the scanner
  doesn't open arbitrary files) or rephrasing to split the string
  literal (`'rm -rf ' + '/'`).

- *write_guard latch on protected paths in Bash string literals.*
  Writing a test probe like
  `'{"command":"echo x | tee --append .claude/settings.json"}'` —
  the JSON contains `tee --append .claude/settings.json` as a
  literal substring. The Bash scanner sees the substring, parses
  it as a real `tee` command, and DENIES the outer invocation —
  even though the outer is just `echo '<JSON>' | python
  write_guard.py`. Fixed by running via a `run_bash_guard()`
  fixture that constructs the protected-path string at runtime
  via concatenation, breaking the literal substring.

- *scope-check `walk_references` identifier over-match (a complacent-oracle
  instance — §13.9).* `espalier/scope_walker.py` matched an affected-symbol as
  a bare SUBSTRING (ripgrep `--fixed-strings`; Python `symbol in line`), so a
  generic entry-point name like `main` matched `maintain`, `domain`,
  `docs-maintainer`, `main.py` — flooding `/scope-check` with false-positive
  "gap" files (391 flagged; `main` alone 1869 raw hits). Unlike the
  cases above it did NOT get "disabled or ignored": the noise was plausible
  enough to read as integration *depth*, so the tool was trusted, not
  distrusted, for an unknown duration. Fixed via §10.2's contract —
  word-boundary matching for identifier symbols (`\b…\b` / ripgrep
  `--word-regexp`), paths stay substring. `tests/test_scope_walker.py::TestWordBoundaryMatching`
  is the known-negative fixture this Detection section always prescribed
  (`main` must NOT match `maintain`); gap files 391→206. Polarity pair:
  §1.12's second example is the SAME tool's UNDER-match (its parser → `[]`).

**Detection.** False-positive rate audit. Run the detector against
known-negative fixtures and measure false-fire rate.

**Contract.** Multi-signal classifiers. Pattern that matches USAGE
SHAPE (markdown bold, table cell, label prefix), not just substring.
Threshold of ≥2 co-occurring independent signals before flagging.

---

### 10.2 Substring marker forgeability

**Signature.** A marker (`# DO NOT EDIT`, ID tag, "managed-by" stamp)
detected via substring search; trivially bypassed by including the
marker text in unrelated context.

**In-repo example.** Pre-fix, the "managed marker" check used a
substring scan: `if "espalier:managed" in source: ...`. A hostile
asset shipped via PR could plant `description: espalier:managed`
inside a YAML field — perfectly innocuous-looking. On the next
`espalier init`, the file masquerades as managed; operator-edited
content gets overwritten, or a user-edited file gets regenerated.
The fix: anchor the marker to line start via regex
`^[ \t]*(?:#|<!--|::)[ \t]*espalier:managed\b` (a shell, HTML or
batch-file comment head). The marker must be
the entire content of a comment at the start of a line — the YAML
field shape no longer matches.

**Sister sites (the bare `token in text` membership shape).** The same
forgeability appears wherever a presence/parity check tests membership
of a token in a free-text blob with Python's `in` operator. A token that
is a prefix/substring of an unrelated token silently passes:
- `check_memory_md_tag_parity.missing_tag_rows` — GA tag `v0.9.0`
  counted as "documented" by an existing `v0.9.0a1` row (the gate cannot
  catch its own motivating incident).
- `proofs.py` LIVE_SURFACE / COMMANDS presence checks — a short action
  name like `review` satisfied by an unrelated `code-review` mention, so
  a genuinely-missing action passes the surface proof.
- `cli.py` gitignore-suggestion check — `reports/` satisfied by a
  `reports/sub/` line, so the needed entry isn't suggested.
The fix is the same as the marker case: anchor each check to a token
boundary (`(?<![\w-])TOKEN(?![\w-])`, or a trailing version-boundary
`TOKEN(?![0-9A-Za-z.])` for version strings) or test line-exact
membership rather than substring containment.

**Detection.** Adversarial-input test: include the marker text in
unrelated places (comments mid-line, YAML fields, prose) and
assert the detector doesn't fire. For membership checks, add a
prefix-collision fixture (a longer token that contains the one being
sought) and assert the shorter token is still reported missing.

**Contract.** Anchor regex to line start (`^`); structural match,
not substring. Markers are STRUCTURE, not content.

---

### 10.3 Detector self-flagging

**Signature.** A scanner's self-tests / fixtures contain examples
of what the scanner is supposed to detect; scanning the repo
naively flags the scanner's own test files.

**In-repo example.** A retired-vocab scanner walks `docs/` and
`.claude/` for the strings `WRONG`, `MAJOR`, `MINOR`, etc. Its own
test fixture file `tests/fixtures/retired_vocab_positives.md` (Espalier
source repo)
contains every retired term as known-positive examples. Without
explicit exemption, running the scanner against the live repo
flags its own fixture, the scanner's contract test fails, and
nothing else can be done with the scanner. The mitigation: an
`EXEMPT_FILES` registry that lists the scanner's self-test and
fixture paths.

**Detection.** Run scanner against repo; check if any of its own
files appear in findings.

**Contract.** Explicit `EXEMPT_FILES` registry covering self-tests
and fixtures, with a one-line rationale comment per entry.

---

### 10.4 Hook fail-open via uncaught exception

**Signature.** A hook's exit code on uncaught exception is 1
(script error); the protocol treats exit 1 as "fail-open" and
allows the operation. The hook becomes a security gap, not a gate.

**In-repo example.** Pre-fix, a PreToolUse hook received
`tool_input["file_path"]` as an integer (rather than the expected
string) from the runtime. The first line did `.lower()`, raising
`AttributeError`. The exception propagated to the script's exit,
which exited with code 1. Claude Code logged the subprocess error
to its debug channel and CONTINUED — exit 1 is "script error,
fail-open" per the protocol. The protected-zone write succeeded
because the hook crashed before checking. Fixed by a type-guard
at hook entry (assert the field is a string) AND a `BaseException`
umbrella in `main()` that catches everything, emits a clear stderr
message, and exits with code 2 (block).

A sister instance is non-hook but the same exit-1-is-fail-open class:
`cognitive_blueprint._acquire_write_lock`. Pre-fix, the acquisition block
(`tools/cc/cognitive_blueprint.py::_acquire_write_lock` — the `bp_dir.mkdir(...)` /
`open(.write.lock)` / `fcntl.flock(LOCK_EX)` calls, NOT the safe
`if not _HAS_FCNTL: yield` early-return above them) raised an uncaught
`OSError` when the blueprint directory was read-only or on a filesystem
without `flock` support. The lifecycle that calls it then died the same way
an uncaught hook exception would, on a host the harness should degrade
gracefully on (minimal containers, network mounts). The fix:
the acquisition is wrapped in `try/except OSError` that falls through to a
best-effort no-lock yield (single-agent assumption) instead of raising —
losing the advisory lock only reintroduces the rare multi-agent
clobber race, never drops the write. The sister-site
`reflect_trigger._locked_increment` got the same degrade (returns a
best-effort read count instead of crashing the PostToolUse hook).

**Detection.** Inject deliberate exceptions in hook scripts;
observe whether they block or allow. The expected behavior is
block. For non-hook lock/IO helpers, run them with a read-only target
directory and a `flock`-less filesystem and assert they degrade rather
than raise.

**Contract.** Top-level `try/except BaseException` in every hook;
exit 2 (block) on internal error, never 1. Hooks fail-closed.

---

### 10.5 Detector deferred indefinitely

**Signature.** A detector flags items as "deferred" / "review later";
the deferred queue grows without bound; effectively the detector
is silenced.

**Detection.** Deferred-queue size over time. A growing queue is a
silenced detector.

**Contract.** Deferred items have deadlines; exceeding the deadline
re-promotes to BLOCK. Periodic queue audit.

---

### 10.6 Pragma escape-hatch over-use

**Signature.** A scanner has an inline pragma (`# theater: ok`,
`# noqa`, `# type: ignore`, etc.) to exempt one-off cases.
Operators sprinkle the pragma to silence findings instead of
fixing the underlying issue.

**Detection.** Pragma-count audit. Per-scanner cap on total pragma
usage across the repo.

**Contract.** Pragma requires a non-empty reason (e.g., ≥12 chars
after the marker). Per-repo cap with deliberate raises that show
in git log. Raising the cap is an explicit operator act that
surfaces accumulating technical debt.

---

### 10.7 Nested file-existence trap

See §1.9 for full detail.

---

### 10.8 Enumeration-shadow leak

**Signature.** A closed-list cleanliness gate (denylist, transient-path
inventory, exempt-set) matches EXACT literal names and is blind to a
near-miss sibling name that carries the identical risk. The list names
`build/`; the artifact is `build_orig_stale/`. The shadow — the
near-miss the enumeration doesn't cast over — leaks.

**Mental model.** A guest list at the door checked by exact name.
"Robert Smith" is on it; "Robert Smithe" walks right in. The list is
precise and useless against a one-character variation.

**Industry analogs.** Denylist incompleteness (security). Allowlist/
denylist asymmetry. The structural inverse of §10.2 (that mode is a
marker matched too LOOSELY by substring; this is a cleanliness list
matched too STRICTLY by exact literal).

**In-repo example.** The release archive shipped 96 stale `.py` files
from an untracked `build_orig_stale/` directory — an old mirror of the
whole `espalier/` + `tools/` tree. `espalier/release_noise.py` and
`espalier/release_denylist.py` prune `build/`, `dist/`, `*.egg-info/`;
none matched `build_orig_stale/`, so `classify_release_path` defaulted
it to `public` and 96 dev-state duplicates landed in the public `.zip`.
This is the v0.6.0 `project.zip` leak (§1.1 in-repo example) replaying:
an artifact whose name no inventory anticipated ships into the public
download.

**Detection.** Earn the gate with a RENAMED sibling fixture — not just
the canonical name. If the denylist matches `build/`, prove it also
matches `build_orig_stale/` / `build2/` before trusting it. Prefer
prefix/glob families (`build*`, `*.egg-info`) to exact literals for any
artifact class whose naming is operator-chosen. Cross-check archive
members against `git ls-files` (only tracked-or-intended files ship).

**Contract.** Closed-list cleanliness gates use family patterns, not
exact literals, for operator-named artifact classes; the gate's
earn-the-gate fixture includes a near-miss name. A dual witness
(denylist AND an allowlist of intended members) catches what either
alone misses.

**Status: the class fix landed.** `release_denylist.py` now uses
the family-glob `(?:^|/)build[^/]*/` ("build\* directory family") instead
of the exact `build/` literal, so `build_orig_stale/` / `build2/` are
denied; `tests/test_release_denylist.py::test_denied_shape_caught` carries
the renamed-sibling regression cases. The first dual witness
(`release_noise.py` → `classify_release_path`) was deliberately left on the
exact `build/` glob: the denylist (second witness) is the catching gate by
design, and `.gitignore` already lists `build_orig_stale/` explicitly, so
the leak path is closed without forcing an out-of-scope `.gitignore`
parity change.

**Related.** §1.1 convergence theater (the `project.zip` leak). §4.6
vacuous registry. §10.2 substring marker forgeability (the over-loose
inverse). §1.7 gate tuning-to-HEAD.

---

### 10.9 Effect-path vs accounting-path normalization asymmetry

**Signature.** One marker, two readers. The *enforcement/exemption* path
normalizes the line (`.strip()` / lowercase / de-dent) before matching and
fires generously; the *cap/audit/inventory* path skips normalization and
matches strictly — so the marker is honored for its EFFECT but is invisible to
the governance ACCOUNTING meant to surface its accumulating use. The cap-gate
stays green because the count it guards is structurally pinned near zero.

**In-repo example.** `count_pragmas` in `convergence_theater.py` and
`magic_depth.py` searched the RAW line against the `^#`-anchored `PRAGMA_RE`,
while their own `_has_pragma_above` and the correct sibling
`subprocess_contracts` `.strip()` first. Every real pragma in the repo is
indented, so the exemption path silenced findings while the cap counter read
~0 — `MAX_PRAGMA_COUNT` (5 / 3) was unreachable and the discipline it encodes
went unenforced.

**Detection.** For each marker constant, enumerate every call site that matches
it; flag any divergence in pre-normalization (`.strip()`/`.lower()`/raw).

**Contract.** Every marker has exactly ONE normalization helper shared by all
readers, pinned by a test that the cap counter and the exemption check return
**consistent membership** on the SAME indented fixture.

**Counter-case — one shared helper is necessary, NOT sufficient; ask what each
side already IS.** The contract above is right about *sameness* and silent about
*arity*, and the gap is load-bearing. When the two readers are not raw inputs but
already **products** of that same normalization, applying it again is not
symmetry — it is double-normalization, and a normalizer run twice can move data
**across a field boundary** rather than merely widen or narrow a match.

Measured instance. A completeness gate compared per-run report entries against a
shared corpus; both were parse-products of one line grammar
(`` - `<location>` [<severity>] <claim> ``), and the parser projects `severity`
away. Three keyings were driven against live data, and the two obvious ones are
wrong in **opposite** directions:

- *Normalize neither side the same way* (the shipped state — one side re-rendered,
  one not) → **false RED.** A `location` containing the delimiter character is
  truncated at the collision, so its parsed value legitimately ends in the space
  that preceded it; re-rendering one side collapsed that space away and entries
  the corpus genuinely held reported permanently absent. No amount of appending
  could clear it.
- *Normalize BOTH sides by re-rendering* (the naive repair, and what the contract
  above reads as prescribing) → **false GREEN**, which is strictly worse. The
  re-render of a parse-product has no `severity`, so a `claim` that happens to
  begin with a bracketed severity word is re-absorbed into the vacated slot and
  silently dropped from the claim. A genuinely ABSENT record then matches a
  DIFFERENT stored record and reports present.
- *Normalize both sides' stored fields once, never re-parsing* → correct.

**Refined contract.** One helper, shared — **and applied exactly once per side.**
Before choosing it, classify each side as RAW or DERIVED. A comparison between
two DERIVED sides must normalize their fields directly; only a RAW side may be
put through the producer's render step to reach the other's space. Pin it with a
fixture whose two sides are deliberately **divergent** — a clean fixture cannot
distinguish any of the three keyings above, so an equality assertion over
well-formed inputs passes while proving nothing.

**A third shape: the compare whose two sides were wrong together.** When only
one operand of an equality or prefix compare is translated, the untranslated
pair may have been matching by *coincidence* — both spellings fabricated the
same way by the same missing translation — so the one-sided repair converts a
deny that happened to hold into an allow. Before normalising one operand, trace
what the other one went through; if the answer is "the same wrong thing", the
fix is both sides in one edit, and the case to drive is the one that used to
pass.

**Tell.** A test named for an equivalence ("X matches Y's own notion of Z") whose
fixture contains only well-formed rows. The name carries a property the fixture
cannot exercise; it goes green on the day the property stops holding.

**Status: closed.** All three scanners route `count_pragmas` and
`_has_pragma_above` through one shared strip-then-match helper; a parity test on
an indented-pragma fixture pins consistent membership across the cap counter and
the exemption check.

**Related.** §10.6 pragma escape-hatch over-use (assumes one consistent
counter). §10.2/§10.8 (single matcher too loose/too strict — distinct: here the
matcher is identical, the *normalization* diverges). §5.7 producer/consumer
parity drift.

---

### 10.10 Parse-success type-confusion fail-open

**Signature.** `json.load`/`json.loads` sits inside a `try` guarded only
by `except (JSONDecodeError[, OSError])`, then the result is dereferenced
as a mapping (`.get` / `[...]` / `.items` / `.pop` / `.update`) or
returned raw. A **valid-JSON but non-dict** value (`[]` / `null` / `"s"`
/ `42`) parses cleanly — the decode handler never fires — and the mapping
deref raises `AttributeError`, which escapes as exit 1, so the hook
**fails open**.

**Mental model.** A bouncer who checks IDs for forgery but not for age:
the ID is real, so it passes — then the drink is served to a minor. The
parse succeeded; the *shape* was never checked.

**Shapes.**
- `data = json.loads(s); data.get(...)` with only a decode-error guard.
- A loader that `return json.loads(...)`s raw and lets callers deref.
- The parse **collected** into a container then element-dereffed
  (`out.append(json.load(f))` … `out.sort(key=lambda d: d.get(...))`) —
  the deref is one level removed from the parse.
- Missing `UnicodeDecodeError` / BOM handling at the same boundary.
- The container IS a dict but a **present-but-null field** defeats the
  default: `entry.get("k", "")` returns `None` (not `""`) when `"k"` exists
  with value `null`, so a downstream `.startswith` / `str.join` / arithmetic
  raises — `isinstance(entry, dict)` passes, the *field* deref still fails.

**In-repo example.** A hardening pass closed ~13 sites with a typed chokepoint
`load_json_dict_safe` (returns the parse iff a dict, else a
caller-chosen default; collapses decode / non-dict / `RecursionError`)
plus an AST gate `find_json_fail_opens` that earns-the-red on the pre-fix
tree. The gate walks `tools/cc/` and `espalier/`; `espalier/` cannot
import the chokepoint (isolation rule), so its sites satisfy the gate via
inline `isinstance(x, dict)` guards. A later pass extended the
classifier to the indirect-deref shapes the first pass missed —
append-into-container, walrus, `import_module('json')` — after the
blueprint loader `_load_blueprints_raw` in `scaffolding_canon.py` proved
the gate's "0 findings" meant "0 of the shapes the classifier
recognized," not "0 instances" (§1.7). A still-later pass then found the
**field-level** shape one layer deeper in the *same* file: signal
functions read `entry.get("description", "").startswith(...)` on
blueprint entries, so a `{"description": null}` entry passed the dict
guard but `.get` returned `None` → `AttributeError`. Fixed with a typed
field reader (`_entry_description`) that coerces any non-string to `""`.

**Detection.** AST-walk for `json.load*` dict-dereffed or returned raw
without an `isinstance(x, dict)` guard, including indirect derefs
(container elements, walrus bindings, dynamic-import aliases). Earn the
gate against the pre-fix tree.

**Contract.** A typed safe-default chokepoint that degrades to `{}`/`None`
and continues — the **opposite polarity** to §10.4: §10.4 fails *closed*
(exit 2) on an uncaught exception; here the parse already succeeded, so
the remedy is to absorb the wrong *shape* and degrade, not to block.
Deliberately non-dict parses (JSONL) keep an inline guard or a pragma.

**Related.** §10.4 hook fail-open via uncaught exception (the genus —
this is the parse-success sibling, opposite remedy polarity). §1.12
sister-predicate domain blindness (the non-dict cell one site shared).
§9.3 ASCII-only string ops (the BOM/encoding edge the chokepoint folds
in).

### 10.11 The detector's own resolver manufactures the pass

**Shape.** A checker that must decide "does X exist?" grows a *fallback* — a
near-match, a normalization, a basename lookup — so that legitimate shorthand
does not report as broken. The fallback then relaxes a dimension the citation
actually *specified*, finds something else, and reports success. The check now
cannot fail on precisely the input class it was written for, and it reports
green rather than silent, so nothing looks wrong.

**In-repo example.** A gate proving every pointer in a shipped doc resolves on
the tree a user receives fell back to matching by *basename anywhere on the
tree* when the full path missed. A doc cited the harness's own package-data
mirror of this very file (an `espalier/assets/docs/` path, self-host only —
not deployed by `init`) — absent from a user's tree, which has no `espalier/`
directory at all. The fallback matched the one file named `FAILURE_MODES.md`
that was present, an unrelated shipped doc, and called the pointer resolved.
The dead pointer sat inside the gate's own population, in a file the same
change edited three lines away from, and only an adversarial review pass
surfaced it.

**The rule.** A fallback may only relax a dimension the input left
unspecified. A bare filename says "find this for me"; a path-qualified one asserts a
location, and collapsing it to a basename does not locate the file — it changes
which file is meant. Gate the fallback on the input actually being unqualified.

**The sibling shape: a narrowing that takes real findings with it.** The same
instinct — suppress noise — produces the inverse defect at extraction time.
Two narrowings in that gate each removed a genuine finding along with the
noise: requiring pointers to be path-qualified silenced shorthand *and* a real
dead reference cited twice as fact; stripping fenced code silenced shell
variables *and* a `#` comment a reader follows. **Tell: when a narrowing makes
reds go away, enumerate which reds went with them.** The fix is usually to
handle the noise at *resolution* rather than to stop *extracting*, so the
suppressed cases stay visible and countable.

**Detection.** Mutate: plant an input that must fail, in the exact shape the
fallback handles, and confirm the red. A fallback that never produced a
distinguishable failure in testing has not been tested.

---

### 10.12 The reachability rule stops at the file boundary

**Shape.** A detector decides whether a string matters by asking "can a user
see this?" — and answers it by looking *within one file*: is the literal
inside a `print(...)`, a `return`, an emitting call. That is correct only if
the codebase keeps its messages next to its message-sending. Any codebase that
centralizes strings — a constants module, a template table, a registry — puts
the literal in one file and the call in another, and the rule reports the
entire centralized surface as unreachable. The detector is then **most blind
exactly where the code is best organized**, and it fails green.

**In-repo example.** The arm added to close DEF-503 checked `.md` pointers in
deployed hook scripts. Its first draft computed reachability per file. This
repo deliberately splits deny CALLS from deny STRINGS — `_denial_reasons.py`
opens by saying so — so all 31 message templates were module-level assignments
with no emitting call anywhere near them. The gate written to check hook deny
messages could not see one hook deny message. Caught in adversarial review,
before it shipped; the arm now resolves `Name` / `<module>.<NAME>` references
across the whole deployed corpus.

**The paired half: the exclusion must travel with the reference.** Once
references resolve across files, any *gate* on the reading site has to follow
the same edge. Keying the self-host exclusion on the constant's own location
put a module-level witness table outside every gated function's line span, so
a table read only by a self-host-gated renderer was judged as if an adopter
could see it — a false red that arrived as a direct consequence of fixing the
false green. **A constant is only as visible as the site that reads it**; when
a value is reached from both a gated and an ungated site, the ungated verdict
must win, because the conservative direction is the one that keeps a finding.

**The generalization.** Before trusting a visibility analysis, ask what
*architectural* convention would defeat it, then check whether this repo uses
that convention. A rule that assumes co-location is a bet on the code never
being refactored into tables — a bet this repo had already lost, in writing,
in the file's own docstring.

**Detection.** Count what the analysis reached *through* an indirection and
assert it non-zero — the arm keeps an `x-module-ref` counter for this. A
per-classifier counter, admits *and* excludes, catches both directions: a dead
admit-counter means the rule stopped seeing, a dead exclude-counter means an
exclusion is protecting nothing while still reading as a considered decision.

---

### 10.13 A gate that covers half its class, under a comment claiming the whole one

An absent gate is a known gap. A gate whose *scope* is narrower than its stated
scope is worse: it converts "nobody checked this" into "something checks this",
and the next maintainer reads the comment rather than the predicate.

**The shape.** A detector is written against the population the author is
looking at, and described against the population the author is thinking about.
Both feel identical while writing. Measured here twice in one change: a ratchet
counting `warnings.append`/`extend` inside one function carried the comment "so
this stays complete", and was blind to `warnings += [...]` (an augmented
assignment, not a call) and to the entire sibling `failures` list — which was the
*larger* population and the more damaging one, because the report's headline is
`failures[0]`, so an unpaired failure branch IS the whole answer with an empty
action list. Separately, a deliberate exclusion described in a comment as "on
purpose" was pinned by nothing at all: the full suite stayed green with it
deleted, because the shared fixture could not reach the state it guards.

**The deeper version, and the uncomfortable one.** Gates get built where
attention already is, and attention is where the defects already are not. In one
measured change: the defect the author was consciously fixing received a gate
that redded on every mutation with per-case precision; a helper written *in
passing to support that fix* received two poles of coverage and carried both
shipped blockers. A tally of "defects our gates caught" and a list of "defects an
adversarial pass found" are then drawn from **disjoint populations** — the gates
never had jurisdiction over the survivors — so the tally cannot be evidence that
the gates are working. That reasoning is survivorship, and it reads as rigour.

**The asymmetry to watch for.** Gates written this way tend to pin *mutations of
the implementation* (a type changed, a branch deleted, a constant moved) and to
miss *variations of the input* (an encoding, a quoting style, a path shape, a
partially-populated state). Both blockers in the measured case were input shapes;
every defect the gates caught was an implementation mutation.

**Addendum, measured on the next change — the input-shape half needs a DEPTH
discipline, not just a category.** The obvious response to the asymmetry above is
"add input-shape coverage", and a following change did exactly that: a
parametrized class driving malformed shapes of the config value the readers
consume. An adversarial pass then found a crash regression in that same change
which *is* an input shape — and every row of the new class varied the value at
the TOP level while the surviving defect sat three levels down, inside a nested
list of records. Same category, same population, missed by nesting depth alone.

Two things follow. First, the disjointness claim above is falsified in this
direction: a gate CAN be aimed at the survivor population, so the honest reading
is that the tally has no jurisdiction over survivors, not that coverage is
unreachable. Second, "vary the input" is under-specified as a discipline. A
config shape has an axis per level of nesting, and a guard applied at the
shallowest level reads as coverage of the whole structure. The sharpest form of
this: the defective reader's own docstring, eight lines above the defect, warned
that a falsy-default idiom "is not a guard" for exactly this reason — and the
author applied that warning at depth one and not at depth two, in a function they
were writing at the time.

**Detection.** Before trusting the sentence beside a detector, inject the shape
it claims to catch and watch it red. For a structured input, do it at EVERY level
the reader walks, not just the outermost. Do this for the spellings you did NOT think
of first — the augmented assignment, the sibling list, the other encoding. And
when a detector legitimately does not cover part of its class, name the
uncovered part in the code rather than leaving it to the reader's inference; a
declared gap is a gap, an undeclared one is a false claim.

**Related:** §1.11 (gate credibility — authoritative gate green on a red tree),
§10.12 (the reachability rule stops at the file boundary).

### 10.14 The tier is assigned on spelling, and the spelling is anti-correlated with the danger

A guard with more than one severity tier has to decide which tier an input lands
in. That decision is usually made on a cheap lexical property — a leading
character, a prefix, whether a token appears — because the expensive question
("does this actually destroy anything?") is not available where the decision is
made. The proxy then drifts away from the property it stands for, and nothing
notices, because **a tier assignment produces no failure when it is wrong in the
lenient direction and only produces friction when it is wrong in the strict one.**

Attested: a recursive-delete guard tiered on `operand.startswith("/")`. Measured
against matched pairs, the unbypassable tier fired on a build directory named by
absolute path, on the session's own mandated scratch directory, and on a
suffix-bounded glob — while `rm -rf ~` and `rm -rf $HOME`, which really do wipe a
home directory, merely failed to start with a slash and fell to a
deny-once-then-allow nudge the actor clears by re-issuing. Twelve rows too
strict, two too lax, out of thirty. The tier was not merely imprecise; on the
cases that mattered it was **inverted**.

**Why it survives review.** Each individual rule reads as reasonable, and the
strict direction is the only one anyone experiences. Nobody files a report saying
"the guard let me delete my home directory with one extra keystroke", so the
lenient half accumulates in silence while the strict half is argued about.

**The diagnostic.** Do not evaluate a tiered guard on a list of hazards; evaluate
it on **matched pairs**, and count both directions separately. Ask for each tier:
what is the most benign thing that lands here, and what is the most destructive
thing that does not? If the answers embarrass each other, the tier is keyed on
the wrong property. A guard that is 100% correct on hazards and untested on
benign inputs has not been measured at all.

**The fix shape.** Resolve the input to the property you actually care about and
tier on that. For paths that means: normalise, expand, resolve symlinks, then ask
containment questions (is this the root, is it an ancestor of something I must
not lose, is it inside a region that is scratch by construction). Three traps in
that resolution, all attested in one sitting:

- **Ordering.** An identity match must outrank a location heuristic. A
  "scratch by construction" carve-out placed before the identity check waves
  through the deletion of a repository that happens to be checked out under a
  temp root — which CI runners and driven-install fixtures do routinely.
- **Symlinks.** On macOS `/tmp` resolves to `/private/tmp` and `/var` to
  `/private/var`. Without resolution the typed path and the resolved one are
  different strings for the same directory, and every identity rule silently
  never fires — a fix that looks correct and does nothing.
- **Resolution changes depth.** Once you resolve symlinks, any rule keyed on path
  depth sees a different number: `/etc` becomes `/private/etc` and a
  two-component system path reads as three. Judge depth on the form the user
  typed, or on whichever form is shallower, and fail toward the refusal.

**Related:** §10.11 (the detector's own resolver manufactures the pass) is the
sibling where resolution creates a false negative rather than a mis-tier.

## 11. AI-collaboration failure modes

These emerged as LLM-assisted coding became common. Less
industry-codified than the older categories.

### 11.1 Hallucinated API

**Signature.** AI confidently calls a library function that doesn't
exist; code looks plausible at read time.

**Detection.** Type-check / import-check before trusting AI-generated
code. Run the code, don't just review it.

**Contract.** Verification by execution, not by reading.

---

### 11.2 Sycophancy / agreement bias

**Signature.** AI agrees with whatever the user says, including
wrong premises. The agreement biases the rest of the conversation.

**Detection.** Operator self-discipline: state premises and ask AI
to challenge them. Watch for "great point" / "absolutely" patterns
without substantive engagement.

**Contract.** Explicit "challenge this" or "find the flaw" prompts.
Adversarial review agents (see §11.6 closed-loop AI verification).

---

### 11.3 Context drift across turns

**Signature.** Over many conversation turns, the AI gradually loses
track of earlier constraints; introduces patterns that violate
them.

**Detection.** Periodically restate constraints. SessionStart hooks
that inject persistent context. Track conversation depth.

**Contract.** Persistent context (CLAUDE.md, ESPALIER_MEMORY.md). PostCompact
re-injection. Folder-router CLAUDE.md files that auto-inject when
the AI touches subdirectories.

---

### 11.4 Context window saturation

**Signature.** Long conversation; earlier context summarized /
compressed; critical detail lost. The AI doesn't know what it has
forgotten.

**Detection.** Track conversation length; force re-orient at
thresholds. PostCompact hooks.

**Contract.** Auto-compact protocols. Re-orient on PostCompact via
hook that reinjects critical context.

---

### 11.5 AI-generated boilerplate without comprehension

**Signature.** AI produces code that looks idiomatic but doesn't
fit the project's actual conventions. The code-shaped output passes
read-review; only when the project's own scanners run does the
mismatch surface.

**Detection.** Convention scanner. Code review against living
conventions doc.

**Contract.** Living conventions doc (CONVENTIONS.md) referenced
during reviews. Automated convention scanner that matches the
project's actual patterns.

---

### 11.6 Closed-loop AI verification

**Signature.** AI generates code AND the test for the code. Both
match each other (the AI's mental model), neither matches reality.

**In-repo analog.** Convergence theater (§1.1) is a sister shape
but not exactly AI-specific. The AI variant is more general: any
AI-led verification where the AI controls both halves.

**Detection.** Independent witness — humans review the test, OR
independent test infra exercises the code without the AI seeing
the test source during generation.

**Contract.** Test infra separated from code-generation context.
Adversarial-review agents (`failure-mode-reviewer`) operate
without seeing the AI's correctness rationale.

---

### 11.7 Prompt injection

**Signature.** Untrusted content in a tool result (web page, MCP
response, file content) contains instructions the AI executes.

**Industry term.** Prompt injection.

**Detection.** Audit AI behavior after consuming untrusted content.

**Contract.** Treat tool results as data, not instructions. Flag
suspicious patterns (instruction-like text in result bodies) to the
user.

---

### 11.8 Mock-as-test

**Signature.** AI generates a test that mocks every dependency,
then asserts on the mock's output. Test passes; production fails.

**In-repo analog.** Convergence theater (§1.1) extended to mocks
specifically.

**Detection.** Code review; integration tests against real
dependencies.

**Contract.** Tests assert on REAL behavior at integration
boundaries; mocks only at process boundaries.

**Related.** §1.1 convergence theater. §2.1 mock drift.

---

### 11.9 Habit-formation against friction

See §1.6 for full detail. The AI variant: an AI repeatedly hits a
denial and learns the bypass shape from the denial message rather
than the lesson.

---

### 11.10 Fan-out fix-plan: observation sound, mechanism unverified

**Signature.** A read-only scout / fan-out agent returns a finding whose
OBSERVATION is empirically correct (the bug exists; the earn-the-red
reproduces it) but whose MECHANISM ATTRIBUTION (which line/branch causes it)
or COMPLETENESS (sister-sites, import cycles) is wrong. Applying the fix-plan
verbatim ships a fix whose own earn-the-red fails, or that misses a parallel
site, or that re-creates a cycle.

**Mental model.** A witness who correctly saw the crash but wrongly named which
car ran the light — the event is real, the causal account is not.

**In-repo example.** A pack ran a scout fan-out (re-verify each pack item vs
HEAD) before editing. Twice the observation was trustworthy but the account was
not: (a) one finding — the scout's earn-the-red `classify('tool')` vs
`'zzzz toolkit'` actually fires at `surface_matrix.py`'s full-string substring
branch, NOT the stem branch its fix-plan targeted; applying it verbatim would
have shipped an incomplete fix whose own red failed. (b) The scout said
"importing `pre_release` into `release_pack` is acceptable if kept minimal" — but
`pre_release` ALREADY imports `release_pack` (a real cycle); only the executor's
independent grep caught it, forcing a hoist to `surface_contract` instead. (The
adversarial pass separately found a guard the same fix-plan under-specified — the
present-but-null field case.)

**Detection.** For each scout/fan-out fix-plan, before editing: re-derive WHICH
branch/line actually fires the proposed earn-the-red (run it), and re-run the
sister-site + import-cycle sweep independently. Treat "the bug is at line X" and
"importing Y is safe" as claims to verify, not facts.

**Contract.** A fan-out scout's *observation* (bug exists, red reproduces) is
trusted; its *mechanism* and *completeness* are re-derived by the executor
before the edit lands. The earn-the-red must be confirmed to fail pre-fix at the
site actually changed.

**Related.** §11.5 boilerplate without comprehension (the executor's blind spot;
here the upstream scout's). §11.6 closed-loop AI verification (one agent owns
code+test; here two agents split observation vs execution). §1.1 convergence
theater (the test, not the fix-plan handoff). The untrusted-oracle discipline
(verify a rendered frame against an independent mechanical oracle) applied to a
*scout fix-plan* rather than to tool I/O.

### 11.11 Earn-the-red is necessary, not sufficient — verify even "trivial" batches

**Signature.** A small, low-risk change (a polish batch, a one-line guard, a
cleanup) ships with a passing earn-the-red test and a green full suite, so it
*feels* done — and the adversarial / skeptic pass is skipped because the batch
looks too trivial to warrant one. The fix does what its test proves; it ALSO
does something the test was never written to check.

**Instance.** Seven polish fixes, each
earn-the-red'd, full suite 5654 green. An 8-agent adversarial pass (one skeptic
per fix) then found **4 real defects** no earn-the-red could have caught: a
`release-pack` guard whose message ("refusing to write an empty archive") was
false — it had already written *and clobbered* a pre-existing valid artifact; a
`doctor` exit code (2) that violated the documented `{0,1}` contract; an flock
fallback that double-appended a torn record on a mid-write error AND leaked an
fd; and a class-fix that missed its own documented sister-site. Each
earn-the-red proved its fix did X; none proved the fix did not *also* do Y.

**Instance (the verifier that needed its own discipline).** The first draft of
`espalier/red_team_guard.py` — the gate built to force re-execution on red-team
claims — passed its own 22-test suite and was green, yet an adversarial
failure-mode pass reproduced a real bypass the green suite missed: a repro
shipping `/usr/bin/false` (any trivially-failing command) "verified" any blocker,
because the guard checked *that* the command failed, not that it failed *as
claimed*. The same pass found three more defects (an invalid-regex crash
violating the guard's own never-raises contract; `expect="pass"` repros accepted
for blockers; `<no-id>`/duplicate-id collisions). A second, structurally
different instance from the polish batch — a security gate built to enforce the
adversarial-verify discipline itself needed it — which is what makes this entry
general, not a one-off.

**Detection.** Run the implement → adversarial-verify → fix-survivors loop on
EVERY substantive batch, not only on blockers or large diffs. Diff size is not a
proxy for risk. The skeptic prompt attacks for false-positives, contract
violations, missed sister-sites, and regressions the author's own test could not
see because it shares the author's blind spot.

**Contract.** A passing earn-the-red and a green suite are necessary gates, not
the final word: they verify the *intended* behavior, never the *absence* of
unintended side-effects. The adversarial pass is load-bearing, not ceremonial
(cf. the §6.10 PowerShell-delete entry, "the adversarial-pass gate is
load-bearing, not ceremonial").

**Related.** §11.6 closed-loop AI verification (the author's test shares the
author's blind spot). §1.1 convergence theater. §13 detection methodology. The
dual of "agent blocker citations are claims, not results" — turned on one's OWN
fixes, not a subagent's.

---

### 11.12 Verification theater at the automation layer (count-gating manufactures findings)

**Signature.** An autonomous/red-team pipeline ships a `blocks_release` finding
whose repro was never independently run — or is a trivially-failing
`/usr/bin/false`-class command that fails for the wrong reason — and a gate
accepts it. OR a quality gate requires a *minimum finding count* to pass,
pressuring the agent to fabricate findings to open it.

**Mental model.** A metal detector you "pass" by handing the guard a beep. The
gate wanted evidence of *absence of weapons*; it got evidence of *a beep*. And a
quota of "must find ≥N threats per shift" trains the guard to plant them.

**In-repo example.** `espalier/red_team_guard.py` closes both holes. For every
finding claiming `blocks_release`, the red-team must ship an executable repro
`{id, argv, expect, match}`; the guard **re-runs the argv** and a blocker passes
only when the command fails *with that specific, non-catch-all signature*
(`expect="fail"` + a non-`.*` `match` + a unique id + a compiling regex). The
artifacts it reads are `cc/red_team_findings.json` + `cc/red_team_repros.json`
(both tracked-able; the gitignored `cc/finding_ledger.jsonl` is a separate
telemetry decoy, not the gate input). Critically, **an honest null PASSES** —
zero reproducible blockers ⇒ zero unverified ⇒ pass. Requiring a minimum count
would invert *null-is-the-signal* and train fabrication; diversity-of-finders is
a *warning*, never a block. The re-execution lives in an INDEPENDENT oracle
(the driver / CI), never an in-agent hook the agent could satisfy with prose.

**Detection.** Re-execute every claimed blocker's repro in an independent oracle;
assert it fails *with* its specific signature; never gate on finding-count — an
honest null must pass. See §13.10.

**Contract.** `externally_verified` is *computed* by re-execution, not asserted.
Gate on process + reproducibility, never on count. The honest residual stands on
every PASS: re-execution proves a claimed blocker reproduced its signature; it
does NOT certify completeness, depth, or that the repro is *causally* the bug.

**Related.** §11.6 closed-loop AI verification (the oracle re-runs the repro the
AI never saw it author). §11.11 earn-the-red necessary-not-sufficient (this
mechanizes the adversarial-verify loop). §1.1 convergence theater (the automation
layer). §13.5 earn-the-gate. §13.10 re-execute the repro.

---

### 11.13 AI-authored extraction in an untested surface (well-formed ≠ correct)

**Signature.** An AI writes a regex, a shell-extraction command, or a snippet
into a surface that NO test executes — an agent/prompt body, a skill, a CI YAML
step, a "runnable" doc, a task description. It is untested authorial intent. A
green suite says nothing about it, because the suite never runs that surface. A
linter proves the pattern is WELL-FORMED (it compiles); nothing proves it matches
the right SET against real data.

**Example.** A prescribed `grep -oE "[A-Z0-9-]+"` pasted verbatim into an agent
body silently dropped every lowercase item (the character class excluded
lowercase), systematically false-negating real references — and the full suite
stayed green because the regex lived in instruction prose no test exercised. Only
running the command against the real corpus and diffing the match SET exposed it.

**Detection / Contract.** Treat any AI-authored extraction on an untested surface
as a claim: run it against the REAL data and confirm the match set (and the
non-matches), not that it exits clean. If the surface can carry a companion test
that asserts the output, add one; otherwise the reviewer executes it by hand
before trusting it.

**Related.** §11.5 boilerplate without comprehension. §11.10 observation sound,
mechanism unverified. §5.11 unmeasured command latency.

---

### 11.14 Unattended landing is mechanically green but incomplete

**Signature.** A full test suite passing plus a clean audit certifies a change as
"landed" — yet those gates enforce only the *suite-checked* half of "done." The steps
no test runs (a pre-flight artifact review, a red-team, moving a finished artifact to
its done state, a changelog entry, propagating a fix to sibling sites) are invisible
to "green." "Green" is a *subset* of "done to the manual standard," presented as the
whole.

**Mental model.** A pre-flight panel where only the items wired to a sensor have a
light. The panel reads "all green" and says nothing about the items it doesn't wire
to — and a pilot who reads "all green" as "all done" skips exactly those.

**In-repo example.** An unattended nine-pack chain landed with zero regressions and a
green full suite — yet every non-suite-enforced step (the pre-flight artifact review,
the scope-check, the inline red-team, moving each finished pack to its done folder,
the changelog, sibling-site propagation) was skipped, because the driver goal
*paraphrased* the command it was meant to run and executed under a maintenance-mode
env var that disables the enforcing hooks. The suite certified the enforced half; the
gap lived entirely in the unenforced half, invisible to every gate that ran.

**Detection.** Enumerate the *completion* surface (every step the manual standard
requires) and mark which steps a test actually enforces; the unenforced steps are
where an unattended run silently under-delivers. Audit them by hand *after* a green
landing — do not read "suite green" as "workflow complete."

**Contract.** "Suite green + audit clean" certifies the suite-enforced subset of
"landed," never the whole. A workflow's completion surface is larger than its
enforcing surface, so a gap on an unwired step is invisible by construction. This is
§1.11's absence-as-allow raised to workflow scale: the enforcing surface enumerates a
subset of the completion surface, so an unwired step's gap reads as done.

**Related.** §1.11 gate credibility (absence-as-allow, here at workflow scale). §11.12
verification theater at the automation layer. §11.15 (the command-paraphrase cause of
this incompleteness).

---

### 11.15 A paraphrased command-goal skips the command's non-named steps

**Signature.** Telling a session — or an autonomous driver's goal string — to work
`` `via /command: <checklist>` `` runs the *checklist*, not the *command*. A command
is a CLOSED procedure: its steps are fixed and complete. A paraphrase is an OPEN one
that silently loses exactly the steps the author forgot to transcribe. The steps
present in the command body but absent from the paraphrase simply don't happen, and
nothing flags their absence.

**Mental model.** Handing someone a recipe's ingredient list and saying "make the
cake." The steps not on the list — preheat, rest, cool — are the ones that don't
happen, and the batter looks done in the bowl.

**In-repo example.** An unattended driver goal paraphrased a multi-step
pack-execution command as an inline checklist. The command's own body carries steps
the paraphrase omitted (a non-skippable artifact pre-review, a move-to-done, a
sibling-propagation step); the driven sessions ran the checklist faithfully and
skipped precisely the omitted steps — the automation-layer cause of the
green-but-incomplete landing above.

**Detection.** When a goal invokes a procedure by paraphrase, diff the paraphrase
against the actual command body: the steps in the body but not the paraphrase are the
silent drops. Prefer invoking the command *by name* (deterministic — every step it
defines runs) over transcribing it (lossy).

**Contract.** A command invoked by NAME runs every step it defines; a command
PARAPHRASED runs only the steps transcribed. If a driver must inline a goal, that goal
is only as complete as its transcription — treat any paraphrase of a closed procedure
as lossy and reconcile it against the source before trusting it.

**Related.** §11.14 (the completion gap this produces). §11.6 closed-loop AI
verification. A command invoked by name is deterministic; a paraphrase is not.

---

### 11.16 Maintenance mode bypasses the enforcing hooks — goal-text completeness becomes load-bearing

**Signature.** A scoped friction-opt-out env var (`ESPALIER_MAINTENANCE_MODE=1`)
early-returns the enforcing hooks: the plan-required check, the protected-zone check,
and two Stop-gate gates (docs refresh, code review). An edit made under it rests
ENTIRELY on the goal text plus the opt-in test gate; the mechanical floor the harness
normally provides is off. Under the bypass, the *completeness of the instruction* is
the only thing standing where the hooks used to stand.

**Mental model.** Turning off the guardrails to move furniture, then walking the same
ledge in the dark. The rails were what made "walk to the wall" safe without measuring;
without them, only the instruction's precision keeps you on the floor.

**In-repo example.** An unattended chain ran under the maintenance-mode env var so the
harness could edit its own protected zones without friction. That same var disabled
the plan-required and protected-zone checks and the docs-refresh + code-review
Stop-gate gates — so the run's correctness rested on the paraphrased goal plus the
(opt-in) suite gate alone. The env-var LIFECYCLE half of this is a stealth-contract
cousin: it must be set in the parent shell BEFORE launch; a mid-session export never
reaches the already-running hooks.

**Detection.** When a bypass env var is active, treat the goal text as load-bearing
and re-run the bypassed gates by hand afterward (the code review, the docs refresh).
Each bypass emits a maintenance-mode log line to stderr — grep the transcript for them
to see exactly where the floor was off.

**Contract.** A maintenance/friction-bypass flag trades enforcement for speed; under
it, instruction completeness is the only remaining floor for the checks it disables.
Use it only for the narrow self-edit it exists for, and re-assert the bypassed gates
independently — never let the bypass stand in for the review it removed.

**Related.** §1.2 stealth contracts (the env-var-must-be-set-before-launch lifecycle
half). The bypass scope table — which gates each mode suspends and which keep
running. §11.14 (the incompleteness this enables).

---

### 11.17 The review loop that generates its own work

**Signature.** An AI review pass runs over a planning DOCUMENT rather than over the
code the document describes. Findings arrive; they are answered by *editing the
document*; the edits are new prose, so the next pass has more surface to review and
returns more findings. The loop has no termination condition — it converges only when
someone notices the artifact under review is not the deliverable.

**Mental model.** Sharpening a pencil to write a sentence you could have already
written. Each pass is genuinely productive — the findings are real — and the total is
still zero, because the thing being improved is not the thing that ships.

**Why it is hard to see from inside.** Every individual round looks like diligence. The
findings are true, the reviewers are correct, and the document measurably improves. The
signal is not finding quality but finding *provenance*: when a round's findings target
text written in answer to the previous round, the loop is feeding on itself. Two cheap
tells — the artifact grows monotonically while the code does not change at all, and a
round's findings cluster in the sections most recently rewritten.

**In-repo example.** A plan for a ~12-line interpreter fix went through four review
rounds. Every round the headline diagnosis held and a prescription broke, so the
prescription was rewritten; the document went 586 → 1076 lines and the code stayed
unwritten. One round returned 25 findings of which *all 25* targeted amendments authored
in response to the previous round. The plan document was gitignored — it shipped
nowhere and had one reader. When the loop was abandoned and the fix written directly,
the test suite found four real contract violations in eight minutes that no review round
had mentioned, including one *inside the process note* the reviews had produced.

**Detection.** Ask what oracle is judging the artifact. A mechanical one (a test, a
contract, a lint rule) terminates: it is either green or it names a file and a line. An
LLM reading prose does not terminate, because more prose is always available to critique.
If the artifact is not itself a deliverable, the loop has no natural stopping point and
must be given one from outside.

**Contract.** Review a document only for as long as the document is what ships. When the
deliverable is code and a mechanical oracle exists, prefer running the oracle over
reviewing a description of what the oracle would say. Size the ceremony to the change:
a small edit to one or two files should be implemented and tested, not planned and
re-planned. Related: §11.6 (closed-loop AI verification) and §11.12 (verification
theater) are the same family — this is the planning-artifact member.

### 11.18 A subagent's scoped measurement, relayed without its scope

**Signature.** A subagent measures something accurately, states plainly which
oracle it ran, and the orchestrator relays the RESULT while dropping the SCOPE.
The number is real; the claim built on it is not, because it was only ever true
of the thing that was actually run.

**Distinct from §11.10.** There the agent's causal account is wrong. Here the
agent is *right, and says exactly how far right* — the loss happens on the way
up, when a bounded measurement is repeated as an unbounded one.

**Concrete repo example.** A failure-mode reviewer proposed collapsing a
one-line wrapper, reporting *"collapsed task_router written; lines removed: 15"*
and *"NEW probe on COLLAPSED tree — EXIT=0"*. Both true. Its coverage line named
what it ran: the probe. It never claimed the test suite passed. The orchestrator
relayed this to the operator as "a 15-line deletion", the operator approved that,
and applying it turned **28 tests red** — the symbol was half of a declared
sister-predicate pair asserted by two contracts, plus a state-space pin and a
catalog anchor resolving to it by name.

**Why the obvious guards miss it.** Nothing in the finding is false, so
verifying the finding passes. Re-reading the agent's report passes — the scope
is right there. The defect is in the summarization step, which is exactly the
step no oracle covers. And a well-written agent report makes this *more* likely,
not less: the more confident and specific the measurement, the more it reads as
a general verdict.

**The fix.** Before relaying a subagent's cost or safety estimate as your own,
ask which oracle produced it and whether that oracle covers the claim you are
about to make. If the agent ran a linter, you may relay a lint verdict, not a
correctness one. Where the relayed claim is what an approval will rest on, run
the missing oracle first — applying a proposed deletion and running the suite
costs one command and converts an inherited estimate into a measurement.

**Generalisation.** Delegation compresses evidence, and compression is lossy at
the boundary, not in the middle. A subagent that reports its scope honestly can
still produce a false claim upstream, because the orchestrator is the one making
the claim. Treat an inherited cost estimate as a hypothesis carrying the
provenance of whichever oracle actually ran — and note that approving work on a
falsified premise is the operator-facing version of the same failure: when the
measurement kills the stated reason, re-raise rather than execute.


## 12. Process and organizational failure modes

### 12.1 Conway's law

**Signature.** Software architecture mirrors organizational
communication structure. Two-team product? Two-service architecture.

**Industry term.** Conway's law (1968).

**Implication.** Reorganize the team and the architecture will
follow. Conversely: architecture changes that fight the org
structure tend to fail.

---

### 12.2 Bus factor

**Signature.** Knowledge concentrated in N people; if those N
disappear, the project stalls.

**Industry term.** Bus factor.

**Detection.** Knowledge audit; pairing / documentation gaps.

**Contract.** Document. Cross-train. Target bus factor ≥3 for
critical paths.

---

### 12.3 Premature optimization

**Signature.** Optimizing code before measuring; complexity added
for performance that doesn't matter.

**Industry term.** Premature optimization (Knuth: "the root of all
evil").

**Detection.** Profile before optimizing.

**Contract.** Measure first. Optimize the hot path, not the cold
path.

---

### 12.4 YAGNI violations

**Signature.** Code added "in case we need it"; never used; adds
maintenance burden.

**Industry term.** YAGNI (You Aren't Gonna Need It); Extreme
Programming principle.

**Detection.** Dead-code analysis. Coverage measurement.

**Contract.** Add code only when there's a current need.

---

### 12.5 Sunk-cost fallacy

**Signature.** Continuing a failing approach because of effort
already invested.

**Industry term.** Sunk-cost fallacy.

**Detection.** Periodic "should we keep going?" reviews.

**Contract.** Decision criteria for continuing vs cutting losses
declared in advance.

---

### 12.6 Cargo-cult engineering

**Signature.** Adopting practices that worked elsewhere without
understanding why they worked.

**Industry term.** Cargo cult (Feynman, 1974).

**Detection.** Ask "why" repeatedly.

**Contract.** Adopt practices because they solve a problem you
actually have.

---

### 12.7 Best-practice misapplication

**Signature.** Following "best practice" recommendations in
contexts where they hurt more than help.

**Detection.** Outcome measurement. Compare to no-practice
baseline.

**Contract.** Practices justified by local-context outcome metrics.

---

### 12.8 A workflow writes tracked files after its own gate

**Shape.** A command runs its verification early and its writes late. Every
artifact produced after the gate is, by construction, unverified — and because
the gate already reported green, nothing downstream disagrees. The tree is left
broken by a command whose whole purpose was to leave it clean.

**In-repo example.** `/handoff` runs no test of its own: the suite last ran at
`/preflight`, *before* step 2 appends a Session Log row to the project memory
and step 5 commits it. The Stop hook does not compensate — its pytest gate is
opt-in. One handoff appended four bare `path:NN` citations to that row, pushing
the tree past the citation-anchor ceiling and leaving the default branch red at
a commit whose message reported a green suite. It was found a session later, by
a full run that happened for an unrelated reason, and confirmed on a pristine
checkout of that commit.

**Why it recurs rather than being a one-off.** The content a handoff writes is
exactly the content most likely to trip a content gate: a session summary cites
the files and lines it just changed. The trigger is not rare — it is the normal
output of the step.

**The trap in the reporting.** The commit message said the suite was green. That
was *true when measured* and false when committed, which is worse than a wrong
claim: it is a correct claim with an expired premise, and it reads as evidence
to the next session.

**Contract.** Either the gate runs last, or the write is validated where it
happens. Prefer the second — a check at the moment of the write catches the
problem while the fix is one edit, rather than at the next full run when the
context is gone. A hook that already validates written files is the cheap home
for it.

---

### 12.9 The check exists, is well-tested, and nothing ever runs it

A failure mode gets diagnosed, an instrument gets built to catch it, the
instrument gets its own tests — and no hook, no CI step and no command ever
invokes it. It then runs when somebody remembers, which is to say it runs
during the investigation that produced it and approximately never again. Every
artifact around it reads as coverage: the tool is present, its tests are green,
the class is documented. The one thing missing leaves no trace, because *not
being scheduled* is an absence and absences are invisible to every check that
looks at what is there.

**Attested.** A checker that re-derives each tracked issue's claim against the
live tree was written during a tracker rebuild, where it found **41 of 222 rows
already dead**. It was unit-tested against four failure modes a live run had
actually hit. It was never wired to anything. Run weeks later it reported five
live rows whose claims no longer reproduced — one of them a row written into a
class as current **that same day, by the session doing the rewriting**. Nothing
had regressed; the tool had simply not been asked.

**Why it survives review.** A reviewer checks that the instrument is correct,
which it was. Scheduling is not a property of the instrument, so it is not in
the diff, not in the tests, and not in the file anyone opens to evaluate it. The
question "what invokes this?" is answered by a *different* file, and usually by
no file at all.

**The diagnostic.** For every gate, probe or checker in the repo, grep for its
own filename outside its own directory. A tool that nothing names is a tool that
nothing runs. Do this as a census rather than per-tool: the ones you remember to
check are the ones already wired.

**And the corollary that decides where it goes.** Prefer wiring it *advisory*
into an existing routine command over adding a blocking gate. A check that reds
on correct work gets switched off, and a check that never runs and a check that
was switched off are the same thing with different paperwork. Report loudly,
exit clean, and make the count part of a report somebody already reads.

## 13. Detection methodology

How to identify a new failure mode you haven't seen before.

### 13.1 The abstraction move

1. Start with an instance (a bug, a drift, a finding).
2. Ask "what's the SHAPE here?" — strip the specifics.
3. Name the shape — give it 2–4 words you can use in conversation.
4. Build a detection — query / scanner / test that finds *any*
   instance of the shape.
5. Build a contract — rule / test that stops new instances.

The name is doing real work — it lets the team talk about the
class without re-explaining.

### 13.2 Cross-discipline analogy

Has another community named this? "Stamp coupling" came from
Yourdon's 1979 structured-design work. "Goodhart's law" came from
economics. "TOCTOU" from security. "Connascence" from Page-Jones'
1988 work. Stretching across disciplines often surfaces names
that already exist.

### 13.3 Adversarial cognitive mode

Ask: "what could pass review and still let the system fail to
deliver its claimed value?" Different from "what could be a bug" —
focuses on the gap between what passes and what works.

### 13.4 Diff drift over time

Files that get touched together across many commits but aren't
pinned together: candidates for shotgun-surgery / SoT-proliferation
failure modes.

`git pickaxe` / `git log -- <file1> <file2>` for co-change
frequency.

### 13.5 Earn-the-gate validation

Before trusting a new gate / scanner / canon, validate it against
a historical state where the target debt actually existed. A gate
authored against the post-cleanup HEAD has no demonstrated
detection capability. See §1.7 gate tuning-to-HEAD blind spot for
the full discussion.

### 13.6 Convergence indicators (when have we found enough?)

Adversarial review rounds asymptote at sister-site / doc-drift work.
Practical asymptote: ~7–13 rounds with FRESH angles per round; the
angle-discovery cost dominates the find-discovery cost. If two
consecutive rounds with NEW angles surface no new findings, you're
done for that mode.

The "Convergence Is a Property of the Angle Set, Not the
Implementation" insight: a review that runs the same angle 10 times
isn't 10 rounds, it's 1 round of confirmation. New rounds require
new angles — security, concurrency, AI-collaboration, sister-site
sweep, doc-vs-code, platform variation. Allocate budget across the
angle catalog; stop when each remaining angle produces no fresh
findings.

### 13.7 Earn-the-red platform ceiling (direction proven, magnitude unverifiable on a safe-default host)

A bug whose magnitude is gated to a platform/version the dev host is not
on cannot "earn its red" locally — the host already has the safe default,
so the failing test can't fail here. The discipline: do **not** fake the red.
Instead ship the **version/platform-agnostic fix** (safe on every
supported target), add a **contract-lock test** that exercises the fixed
behavior on any host, and find a **host-observable proxy** for the red —
then label the gated crash magnitude *unverified-on-host* honestly.

Worked example: the directory-symlink `rglob` ELOOP crash
reproduces only on CPython 3.10–3.12; the dev host is 3.14 (safe
default). The version-agnostic fix is `os.walk(followlinks=False)`; the
host-observable red→green is the §10 recurrence scanner going **42
flags → 0**; the gated crash itself stays labelled unverified-on-host.
Direction is code-confirmed (a bare recursive walk over an adopter tree,
traced caller-by-caller); magnitude awaits a non-Darwin / 3.11 dynamic
round. Complements §13.5 (earn-the-gate); see §9.7 for the underlying
version skew.

### 13.8 Positionally-anchored contract drift (line-pins and byte-offset pins)

A contract that pins a site by POSITION — a `path:NN` line-number key, a
byte-offset hash, a hardcoded line reference — silently breaks when an innocent
edit shifts the position. Removing or adding a line ABOVE the pinned site moves
it; the pin now names the wrong line and the site it pinned reads as
"unpinned." Two enforced positional pins exist in this repo:
`magic_depth.MAGIC_DEPTH_SITES` (keyed `tools/cc/hooks/<file>.py:NN` — a pack once
shifted `post_write_check.py:127→126` by removing one unused `import re`) and
the `write_guard` first-200-byte self-host SHA pin
(`espalier/_self_host_fingerprint.py`; an edit to the top of `write_guard.py`
re-hashes those bytes).

The trap is *visibility*: both are full-suite-only. The documented core 3-file
suite does not collect `test_scanner_magic_depth` (nor the SHA-pin parity
test), so a shifted pin shows FALSE-GREEN on the fast path — only `pytest -q`
reds. One pack proved it (the magic_depth shift passed the targeted tests; the
full suite caught it) and another nearly proved it on the SHA pin (a
`write_guard.py` edit that happened to land BELOW byte 200). The pins do
**not** "fail LOUD."

Mitigation, in order: (a) prefer a CONTENT anchor over a positional one — the
freshness `::symbol` pins and the integrity manifest already do this; (b) where
the pin must stay positional, wire its contract test into the core suite so a
shift reds fast (`test_scanner_magic_depth` is now wired; the SHA-pin parity
test is not); (c) on any top-of-file or import-shifting edit, re-run the full
suite — never trust a green 3-file run. Cousin of §13.4 (diff drift over time)
and §13.7 (direction proven, visibility/magnitude gated). A documented
"core suite" shortcut is a false-green floor: it proves those files pass,
never that the change is safe.

**A content anchor has a granularity, and the wrong one re-creates the problem
it replaced.** Hashing a whole record line rather than the claim inside it makes
a structural edit indistinguishable from a semantic one: adding a column to the
table re-pinned every row at once, so a re-classification read exactly like a
rewritten claim, and a staleness signal that fires on edits the claim survived
trains its reader to discount the next real one. Pin the cell that carries the
claim and let structure move around it — and when a re-classification is a
legitimate operation, give it a verb that re-pins as it writes, instead of
leaving it a hand edit that stales the pin.

---

### 13.9 Complacent oracle (audit a trusted tool's output against ground truth)

A tool that never crashes, never returns empty, and emits confident,
well-formed output earns standing trust — and standing trust suppresses the
audit that would reveal it is wrong. The dangerous failure is not the tool that
breaks loudly (a crash announces itself) or returns nothing (absence announces
itself), but the one whose output is **plausible enough to be mistaken for
signal**: §10.1 over-match noise that reads as integration *depth*, a classifier
confidently miscategorizing, a metric a few degrees off. Nothing trips — not the
tests (which assert RECALL, "does it find the true thing", not PRECISION, "how
much of what it finds is junk"), not casual use, not review. The flaw runs for
an unknown duration; the cost is every decision quietly made on degraded output.

Mental model: a compass a few degrees off. It always gives a confident,
plausible reading; you trust it *because* it is consistent; you only catch the
error by checking against an external landmark — which you rarely do, because
you trust the compass. The more you trust it, the farther off course you drift
before checking. The tools most exposed are the ones you BUILT and trust most,
because they are audited least.

**The detection-cost asymmetry is the tell.** When the FIX is trivial but the
tool has "worked" for a long time, the bug was cheap to fix and dear to
*notice* — which means nothing was surfacing it. Discipline: periodically take a
load-bearing tool you trust, read its RAW output (not the summary), and check a
sample against ground truth by hand — "what fraction is true signal vs plausible
noise?" If you have never asked, you know the tool RUNS, not that it WORKS.
Structural contract: every detector/reporter ships a known-NEGATIVE fixture (a
thing it must NOT flag), not just a known-positive one — the precision twin of
§13.5's earn-the-gate (which proves recall).

This is the DUAL of the untrusted-oracle discipline: that one fires
when output LOOKS fabricated,
empty, or stale; the complacent oracle is the case its trigger MISSES — output
that looks fine. Worked example: §10.1's scope-check `walk_references` matched a
symbol as a bare substring, so `main` matched `maintain` / `docs-maintainer` and
flooded `/scope-check` with plausible false-positive "gap" files (391;
`main` alone 1869 hits). It was trusted as integration *depth* for an unknown
duration; an adversarial read of the raw gap list against ground truth surfaced
it; the fix (word boundaries, §10.2's contract) was one commit.

**Related.** §10.1 single-signal detector over-match (the mechanism this
discipline catches). §13.3 adversarial cognitive mode (what passes review yet
fails to deliver value). §13.5 earn-the-gate (the recall twin; this is the
precision/audit twin). §5.10 validation-ritual presence vs firing (a gate green
by ceremony, not capability). §1.11 gate credibility. §5.12 unmeasured
efficacy (correct-by-tests ≠ useful).

---

### 13.10 Re-execute the repro, don't trust the citation

For any `blocks_release` / blocker claim, an independent oracle re-runs the
repro's `{argv, expect="fail", match}` and a **specific, non-catch-all**
signature must appear in `stdout+stderr` — the citation that "this fails" is a
claim until the oracle reproduces it. This is the detection method behind §11.12:
the only un-fakeable proof is re-execution, and "the only way to fake it is to
actually do it" holds *precisely where the artifact is re-runnable and the gate
re-runs it* — and nowhere else (template-presence ≠ quality). Reject empty /
`.*` / `.+`-class matches (a trivially-failing command emits no signature), bind
to a unique id, and place the re-execution in an EXTERNAL oracle (driver / CI),
never an in-agent hook the agent could satisfy with prose. Host caveat (§13.7): a
repro only earns its red on a host where the bug reproduces. In-repo:
`espalier/red_team_guard.py`. Cross-link §13.5 earn-the-gate; §13.7 platform
ceiling; §11.12 the failure mode this detects.

### 13.11 Forensically audit the workflow execution, not just the end-state

When an autonomous (`-p`) or sub-session asserts it verified its own work, the
**end-state** (green suite, a commit in `git log`) does not prove the *process*
was honest — the agent could have authored prose describing a RED it never
produced (process theater, the automation twin of §1.1 convergence theater). The
detection method: open the **nested sub-session's own transcript** and audit its
`tool_result` records — confirm a real `pytest`/command result actually showed
`FAILED` on the mutated code (not a prose assertion of it), and that the
execution-plan tracker advanced step-by-step. The oracle is the nested
transcript's `tool_result` records (a mechanical artifact the agent cannot
retroactively forge), not the agent's summary. Load-bearing principle:
**process-honesty on a pack you CAN verify is the proxy for trustworthiness on
packs you can't** — you audit a verifiable run to calibrate how much to trust the
channel. This is the untrusted-oracle discipline pushed one level deeper (not "is
the *output* fabricated?" but "is the *work that produced it* fabricated?").
Sibling of §13.9 (audit a trusted tool's output) and §1.1; the mechanical form is
§11.12's re-execution gate.

---

### 13.12 Trigger-gated defect (a bug the normal loop never reaches)

**Signature.** A defect exists only under a runtime condition the normal
development loop never enters, so every hypothetical check passes — none exercises
the code in that condition. A common sub-case is a "bypass mask": a privileged or
always-on setting (a maintenance/debug mode, a feature flag left on) silently
suppresses the very guard that would catch the bug, so a long run of green
sessions never touches the failing path. This generalizes §13.7's single
platform/version axis to ANY seldom-entered condition axis.

**Example.** A guard that must refresh a set of files was, for a long stretch,
never exercised WITH the guard active — a maintenance-mode bypass was on in every
session that touched it, so the guard blocking its own refresh went unseen until
the bypass was finally off.

**Detection / Contract.** Exercise a new gate or guard under CURATED adversarial
condition axes with pinned outcomes — bypass OFF, fresh clone, degraded surface,
each governed OS — not just under the convenient default. The oracle is the hard
80%: writing the axes that actually enter the failing condition is the work; green
under the default axis proves nothing about the others.

**Related.** §13.7 earn-the-red platform ceiling (the version/OS special case).
§5.10 validation-ritual presence vs firing. §1.7 gate tuning-to-HEAD.

---

### 13.13 Dedup corpus staleness — a review converges to false silence

**Signature.** A repeated (convergence-style) review deduplicates every pass
against a "known findings" corpus so it doesn't re-report what's already triaged.
If that corpus is never re-verified against the current code, it rots: entries
stay marked "open" after the code that caused them was fixed. The finders are then
steered *away* from live code by a stale memory, and the review converges to
"nothing new" regardless of ground truth — silence becomes an artifact of the
stale dedup set, not evidence of a clean codebase.

**Example.** A review that deduped against a findings file re-pointed one round at
its own trusted state and found the corpus badly stale: most "surviving major"
entries had already been fixed — the code had moved on, the file had not. The one
genuine issue that round surfaced came from a deliberately un-primed lane that did
NOT read the corpus and assumed a defect existed; the primed rounds structurally
could not find it, because it was not in the corpus to be un-deduped.

**Detection / Contract.** A dedup corpus is an oracle, and an un-audited oracle
drifts. Before a round trusts "known," re-verify a *sample* of the corpus against
HEAD with an independent check (grep the cited fix), and periodically run a full
corpus-vs-HEAD audit as its own lane. Always keep one un-primed, inverted-prior
finder that does not read the corpus, so the review can find what the corpus
cannot point at. "Repeatedly finding nothing new" is the correctness signal only
when the dedup set reflects ground truth.

**Related.** §13.15 is the inverse — the corpus that stops being WRITTEN, where
the same broken bridge presents as a rising finding count instead of silence.
§13.9 complacent oracle (audit a trusted tool's output). §5.2 Goodhart's law.
§13.6 convergence indicators.

---

### 13.14 Verify the load-bearing premise before authoring the fix

**Signature.** Every fix rests on a premise — "this is broken BECAUSE X." If X is
wrong, the fix is a correct solution to the wrong problem: it lands green, passes
review, and changes nothing that matters, while the real defect persists. The
premise lives one layer ABOVE where tests look — tests check that the fix does
what it claims, not that the claim was the right one — so a false premise is
silent, and the whole effort is wasted.

**Example.** A change was designed around "this is slow because of X." X turned
out not to be the cause; the reworked code shipped green while the actual latency
source was untouched. Every test passed — they verified the new code, not the
diagnosis behind it.

**Detection / Contract.** Push make-it-prove-it UPSTREAM from verification to
diagnosis: before building a fix, state its load-bearing premise in one sentence
("this works because X is true") and verify X against an INDEPENDENT oracle first
— reproduce the failure and confirm the mechanism, don't infer it. The cheapest
place to catch a wrong fix is before you write it.

**Related.** §13.9 complacent oracle. §13.10 re-execute the repro, don't trust the
citation. §11.10 observation sound, mechanism unverified.

---

### 13.15 The dedup corpus stops being WRITTEN — every review re-finds everything

**Signature.** The inverse of §13.13, and the more expensive of the pair. A
repeated review persists each round's survivors to a dedup corpus so the next
round recognises them as already known. That persist step is the LAST hop of a
round, it produces no output anyone reads, and nothing asserts it ran. When it
silently stops, the corpus does not rot — it FREEZES. Later rounds dedup against
a snapshot from before the intervening work, re-find everything discovered since,
and report it as new.

**Why it hides, and why it is worse than staleness.** A stale corpus makes a
review go quiet, and quiet eventually gets questioned. A corpus that stopped
being written makes a review look *productive*: the finding count goes UP. Rising
yield reads as a regression in the codebase or as a sharper review, and both
readings send you looking for causes in the wrong place. The measurement
instrument is broken in the direction that flatters it.

**Example.** A review round reported a sharp severity jump over its predecessor.
The jump was largely a RE-COUNT: the corpus's newest entry predated the round by
ten days, so everything three intervening review passes had found was invisible
to it. Re-measuring on an exact key showed the leak was far older and total —
every round going back five weeks had persisted nothing, including one report
that had already flagged a headline defect as "known, not new." The persist hop
was implemented inside the saved review workflows; every recent round had been
launched ad-hoc and skipped it. Nobody had noticed, because a corpus that is not
written looks exactly like a corpus with nothing to add.

**Detection / Contract.** Assert the write, not the intent. A completeness
contract whose population is discovered from the round ARTIFACTS — every report
carrying findings — and which checks each one's survivors are represented in the
corpus, reds the moment the hop stops. Two properties make it hold:

- **Define the population by CONTENT, never by filename.** A guard scoped by a
  naming convention cannot catch the orphan that breaks the convention; it is
  born weak. Prefer the wider reading when in doubt — silently excluding a report
  is the failure being fixed, while a visibly exempted one is auditable.
- **Key the guard through the WRITER'S own notion of "already present."** If the
  gate and the writer answer that question separately, they will eventually
  disagree, and the gate will assert something the substrate does not do.

Then read a rising finding count as a hypothesis about the instrument before
accepting it as a fact about the code.

**Related.** §13.13 dedup corpus staleness (the same broken bridge, opposite
symptom). §4.10 the cross-artifact assertion nothing checks. §13.9 complacent
oracle. §5.12 measure efficacy, not just correctness.

---

### 13.16 A prescribed earn-the-red is a claim, not an instruction

**Signature.** A spec, plan or review says *how* to prove a gate works: "break X
and confirm it fails", "re-point the reference N units off and watch it red". That
sentence looks procedural, but it is an **assertion about the gate's discriminating
power** — and like any assertion it can be false. When it is, the executor faces a
mutation that does not red and has three bad options: widen the gate until it
does, conclude the gate is broken, or quietly skip the step and call it done.

**Mental model.** A recipe that says "bake until the skewer comes out clean" for a
custard. The instruction is fine for cake and simply wrong here — a set custard
never gives a clean skewer, so following it faithfully ruins the dish. The
instruction encodes an assumption about the medium, not just a procedure.

**Industry analogs.** A test plan prescribing a fault-injection the system is
architecturally immune to. Chaos-engineering runbooks that assume a failure domain
the deployment does not have. A security checklist step that cannot apply to the
chosen auth model. Any "verify by doing X" written by someone modelling a
different implementation than the one that shipped.

**Two ways it goes wrong, and they need different responses:**

- **Impossible in principle.** The prescribed mutation targets a property the
  gate's predicate structurally cannot observe. Example: a resolver that
  deliberately works *without* symbol information was told to prove itself by
  re-pointing a reference so it lands on the wrong target — but distinguishing a
  wrong target from a right one is precisely what requires the symbol it does not
  have. No implementation of that gate could satisfy the instruction. **Response:**
  the spec is wrong. Substitute a mutation on a branch the predicate *can* see,
  record why the prescribed one is unsatisfiable, and track the uncovered property
  rather than pretending the class is closed.
- **Contingently unreliable.** The mutation works, but only for some inputs or in
  some direction, because the data has structure the spec did not model. Example:
  a fixed-size offset applied to a line reference greened, because references to a
  given name **cluster**, so the shifted anchor landed near a neighbouring
  occurrence. The same mutation reddened in the other direction, and the smallest
  effective shift varied by a factor of 1.5 across rows. **Response:** the spec is
  under-specified, not wrong. Derive the mutation from the data (shift clear of
  every occurrence) instead of hard-coding a magnitude.

**Why it hides.** The prescription arrives with authority — it was written during
design, often by someone who understood the problem well — and a failing mutation
reads as *your* bug, not the instruction's. The pressure is toward loosening the
gate to produce the promised red, which is the exact inversion of the discipline
the step exists to enforce (§13.5, and never tune a gate to manufacture a result).

**Detection.** Treat every prescribed mutation as a claim to be run before it is
trusted, exactly like prescribed fix code. Run it **first**, against the unfixed
tree, and record what actually happened. If it does not red, ask whether the
property it targets is one the predicate can see at all *before* touching the
gate. When authoring: prescribe the *property* to falsify ("prove it distinguishes
a stale reference from a fresh one"), not the keystrokes ("shift it 20 lines") —
the property survives an implementation the author did not foresee.

**Related.** §13.5 earn-the-gate validation. §13.7 earn-the-red platform ceiling
(a red unearnable on *this host* — same symptom, environmental cause rather than
predicate scope). §2.12 the red that lived only in the transcript. §11.11
earn-the-red is necessary, not sufficient. Prescribed fix *code* is a claim for
the same reason prescribed fix *mutations* are.

---

### 13.17 A stale exclusion inside a mechanical gate

**Signature.** A gate discovers its own population and asserts a floor over it, so
it reads as a class fix rather than a spot fix. But it carries a carve-out — a
subtree skipped, a path family excluded, a `continue` on one branch — whose
justifying rationale has since been voided. The exclusion outlives its reason.
Everything behind it is ungated, and the gate keeps reporting green, because a
gate cannot observe the part of its domain it was told to skip.

**Example.** A prune contract excluded one source tree on the stated grounds that
modules there are stdlib-only and cannot import the engine's prune predicate.
A later change gave that tree its own stdlib-only prune helper — voiding the
rationale exactly. The exclusion stayed. Every walker behind it was unpruned from
that day on, while the contract that existed to prevent unpruned walkers reported
green over a population it had been narrowed out of.

**Detection / Contract.** An exclusion inside a mechanical gate is an **un-tested
assertion**, and it is the one part of a gate no earn-the-red ever exercises —
mutating the excluded region proves nothing, because the gate is not looking.

- Pin the *reason* for each exclusion to a live fact, not to prose. If the
  rationale is "these modules cannot import X", the exclusion's own test should
  fail when they can.
- Re-audit every exclusion whenever the fact it rests on changes. The change that
  voids a rationale is almost never the change that touches the gate, which is why
  this survives review: the two edits are in different files, different packs,
  often different weeks.
- When a gate's scope is narrowed, **the narrowing needs its own earn-the-red** —
  plant a violation inside the excluded region and confirm the gate stays green
  *on purpose*, so the carve-out is recorded as deliberate rather than inherited.
- Prefer a narrow, dated exclusion with a stated expiry condition over a broad
  permanent one. An exclusion nobody can date is an exclusion nobody will revisit.

**Related.** The half-landed fix (§13.19 — a partial fix removes the evidence
that would have located the remainder) is the upstream cousin: there the author never knew it
was a class; here the author knew, drew a boundary, and the boundary went stale.
See also the born-weak gate — a gate authored after its defect is fixed lands
green-by-construction; a gate whose exclusion has rotted becomes born-weak
retroactively.

---

### 13.18 A shared single-file artifact consumed out-of-band green-washes across subjects

**Signature.** One well-known location — a scratch results file, a lock, a
"latest run" pointer, a receipt — is written by one code path and read by
another. The reader
trusts *presence* and never checks *whose*. A run for subject B then reads
subject A's artifact and reports A's proof as B's.

**Example.** A re-gate path reused a shared receipt file without checking which
subject the receipt named, so a re-invoke could land one unit of work on
another's attestation — a green verification for work that was never verified.
Nothing was missing and nothing was corrupt: the file existed, parsed cleanly,
and said PASS. It simply said it about something else.

**Detection / Contract.** Presence is not identity. Any artifact reused by a path
other than the one that wrote it must carry an **identity field the reader
asserts against its own subject**, and a mismatch must be a hard error rather
than a warning.

- Put the subject *inside* the artifact, not only in its filename. A path that
  encodes the subject invites the reader to trust the path instead of the
  payload, and a correct filename over stale contents is exactly the case that
  bites.
- The assertion belongs on the **read** side. A writer that stamps identity
  faithfully proves nothing if no reader ever checks it.
- Earn the red by writing an artifact under one subject and reading it as
  another. If that path comes back green, the binding does not exist yet.
- Treat a shared artifact carrying no identity field as unowned. The operable
  form: list every writer and every reader of that location; if any reader cannot
  name the subject it expects, that reader is the defect.

**Related.** Adjacent to the class-fix-misses-a-sibling family (§1.12, §2.8) but
not a member of it: there a fix misses a site and the gap is an *absence*. Here
the artifact is present, parses cleanly, and reports PASS — about a different
subject. Note that the seed instance of this class surfaced *as* a sibling-miss,
so the two are easy to conflate in a project's own record even though the shapes
differ; check which one you have before reaching for the other's remedy.

---

### 13.19 A partial fix removes the evidence that would have located the remainder

**Signature.** A defect is found at one site and fixed there. The symptom
disappears — and with it the signal that would have pointed at the siblings. The
remainder is not merely unfixed; it is **unfindable by the route that found the
first half**, because that route *was* the symptom.

**Example.** A commit edited four sibling regexes and applied the fix to only one
of them. The reported misbehaviour stopped, so nothing pointed at the other
three — the commit had the whole population open in front of it and still landed
a spot fix. Separately, a commit removed an over-claim from code and left the same
over-claim standing in the doc it edited in that very commit — the code no
longer contradicted anything, so no later reader had cause to check the prose.

**Detection / Contract.** The moment a fix works, ask what *else* the failing
observation was evidence of.

- Enumerate the population by searching the **shape**, not by listing the sites
  you already know. The known site is the one that happened to have a symptom;
  the siblings are defined by not having had one.
- Do that enumeration *before* applying the fix, while the signal still exists.
  Afterwards the cheapest oracle is gone and the search costs far more.
- After the fix, grep the **uncorrected** form tree-wide — not the corrected one.
  A hit means the fix was partial. A cheap companion tell: when a commit edits a
  file that it also cites, diff that file for the string it was supposed to change.
- A fix and its sibling sweep belong in the same change, or the sweep needs its
  own tracked obligation. "Grep for the others later" is the step that reliably
  does not happen.

**Related.** §2.8 carries the remedy *once you know it is a class* — treat a
hand-listed site count as a floor, and scope the fix to every surface that shares
the shape. This entry is the failure one step earlier: never knowing. §13.17 (a stale exclusion inside a mechanical
gate) is the downstream cousin: there the author knew it was a class, drew a
boundary, and the boundary went stale.

---

### 13.20 A skip-on-absence guard cannot catch the absence it was written to catch

**Signature.** A test pins something outside its own source tree — a tag, a fixture corpus,
a generated artifact, a network resource. To stay runnable in degraded environments it
opens with a skip-on-absence guard. But "absent" has two causes the guard cannot tell
apart: the environment legitimately lacks it, and **someone removed it**. The second is
very often the exact failure the test was written to catch, so the assertion converts its
own subject into a silent skip.

**Example.** A regression suite pinned an external anchor's identity, and its docstring
stated that the assertion "catches rebases, deletions, and force-moves". A housekeeping
sweep later deleted that anchor as apparent scaffolding. The suite moved from *N passed /
M skipped* to *N−2 passed / M+2 skipped* and **still exited 0** — green, with a
security-marked class dark, and nothing in the output naming what had gone quiet. The loss
was found only by diffing two runs' progress streams positionally against the collection
order.

**Detection / Contract.** A skip is a state change that reports as success. Treat it as an
outcome to be asserted, not as a neutral default.

- **Separate the two absences.** Probe for the degraded-environment condition specifically
  — a shallow checkout, an offline runner, a missing optional dependency — and skip only on
  *that*. If the environment is whole and the artifact is gone, **fail**: that is the case
  the test exists for.
- **Pin the skip count, or name the skip.** An unexplained move in the skipped tally is the
  only signal this failure emits. A suite that asserts its skip count, or a guard whose
  reason string distinguishes "no corpus in this environment" from "corpus deleted", turns
  a silent loss into a visible one.
- **Ask what each new `skipif` swallows.** Every portability guard buys reach and spends
  coverage. Write down which real failure now passes through it. If the answer is "the one
  named in the docstring", the guard is in the wrong place.
- **Enumerate consumers before deleting a shared artifact.** Anything a test resolves *by
  name* — a tag, a branch, a fixture path — has readers no directory listing will show, so
  grep the test tree for the name first. Note also that an artifact's **form** can be
  load-bearing, not merely its existence: restoring the right name in the wrong shape can
  leave the test just as broken.

**Related.** §13.17 (a stale exclusion inside a mechanical gate) is the sibling where the
carve-out's *rationale* has rotted; here the rationale is still perfectly valid and the
carve-out is merely wider than intended, which makes it harder to see. §13.5
(earn-the-gate) is the remedy at authoring time — a guard never observed failing for the
reason it names has not been shown to catch it. §1.13 (born-weak guard) is what this
becomes when it ships unexercised.

### 13.21 A guard validated only at the population's current size

**Signature.** A guard is written over a set — rows in a registry, sites in a doc list,
cases in a matrix — and it needs a *discriminator*: some key that says which member a given
observation belongs to. At the set's present size several candidate discriminators agree,
because no two members yet differ on them. The author picks one, the guard goes green, and
nothing in the run distinguishes a key that is unique **by construction** from one that is
unique **by coincidence at N**. The guard is not wrong yet. It is unvalidated, and it will
be wrong at N+1 — which is the moment a new member arrives and the guard is the only thing
watching.

**Example.** A census of seven mirrored source/mirror pairs gained a guard requiring every
declared row to have an edit-time advisory of its own. The guard asserted that the advisory
named the row's **sync script**. At seven rows that read like row identity — but two scripts
served four rows between them, so a neighbouring rule naming the shared script satisfied the
assertion for a row that had no advisory at all, and sent the reader to a parity test that
could not fail for their file. In the same change, a second guard checked eight documents
for a stale count and passed while being **unable to read three of them**: one stated the
number in bold, which broke the pattern, and two stated it in a form the pattern never
matched. The tuple advertised eight sites of coverage and delivered five. Both guards were
green; both were green *for the wrong reason*; and the single number that would have exposed
all of it — an eighth row — was the one nobody had run.

**Detection / Contract.** Green at the current size is the weakest evidence a guard can
offer. Ask what it would do at N+1 *before* trusting it.

- **Add a synthetic member and require the red.** The cheapest possible probe: construct one
  more element, wire it in the way a real one would arrive, and confirm the guard fails. If
  it passes, the guard is describing the set rather than constraining it. This is
  earn-the-red (§13.5) aimed at the guard's *population* instead of its subject.
- **Prefer a discriminator that is unique by construction.** A path, an identity, a primary
  key — something whose uniqueness follows from what the thing *is*. A shared script name, a
  shared prefix, an ordinal, or a human-assigned label are unique only until they are not.
  When two members already collide on a key, that key was never the discriminator; it just
  had not been asked a distinguishing question yet.
- **Assert coverage per member, never in aggregate.** A member the guard cannot read is not
  covered, and a list that names it reads as though it were — the most expensive shape,
  because it looks like the work was done. Make "this declared member yielded no
  observation" a failure in its own right, so an unreadable entry reds instead of quietly
  shrinking the population.
- **A homogeneous or empty population has never discriminated.** If every member currently
  takes the same branch, the other branch is untested no matter how many members there are.
  Drive it directly with a constructed case rather than waiting for reality to supply one.
- **Count what the guard actually inspected, not what it was pointed at.** The gap between
  "eight sites declared" and "five sites read" is invisible in a pass/fail result and
  trivially visible in a count.

**Related.** §13.20 (skip-on-absence) is the same illusion one level down — there a member
silently leaves the population; here the population is too small to tell two keys apart.
§13.5 (earn-the-gate) supplies the remedy and this section supplies the case that is easiest
to skip, since the guard already passes. §1.13 (born-weak guard) is the outcome if it ships
unexercised.

### 13.22 A comparison whose slicer has a start and no end

**Signature.** Two copies of a structured text are compared element by element — items in a
checklist, rows in a table, sections in a document. The extractor anchors the *start* of the
element list and walks to the end of the file. Everything after the last element — a trailer,
a footer, an output-format note — is absorbed into the final element, which then matches
nothing. One element of N fails to compare, and the report reads exactly like a partial
content drift: plausible, specific, and wrong.

**Example.** A checker split a document into items from the first item marker onward and
compared each against a second copy. Six of seven matched; the seventh did not. That was
reported as a live divergence and used as evidence in a scoping decision. A full-region diff
taken afterwards showed the two copies were semantically identical: the seventh item had
swallowed the file's trailing block, so it could never have matched. The defect was in the
extractor, not the data — and the shape of the result actively concealed that, because
"one item of seven drifted" is a far more ordinary finding than "the parser is wrong."

**Detection / Contract.** A start bound without an end bound corrupts exactly one element,
always the last, and never announces itself.

- **Bound both ends, and fail loudly if the terminator is missing.** An extractor that cannot
  locate its end marker should raise, not silently run to EOF. The extent of the region is a
  fact to establish, not a default to assume.
- **Read a one-of-N mismatch as a parser tell first.** Real content drift is distributed by
  the edit that caused it; it rarely lands on precisely the final member. When the single
  failing element is the last one, suspect the slice before the content.
- **Diff the whole region before reporting per-element results.** A full-region diff is cheap
  and answers a different question than N per-element comparisons — it shows the *shape* of
  the difference, which is what distinguishes rewrapping from divergence from a bad bound.
- **State the correction as loudly as the finding.** A comparison result that reached a
  decision and later proves to be a parser artifact must be retracted explicitly, to whoever
  acted on it. A quietly-dropped claim stays in the record as evidence.

### 13.23 A transform that both of its guards normalise away

**Signature.** A derived artifact is produced from a source by applying some transform — an
indent, a prefix, a wrapper, an encoding. Two guards protect it. The first compares the
artifact against the generator's own output, which proves they agree but not that either is
right: the same code sits on both sides of the equality. The second is written deliberately
*independent* of the generator, re-deriving the expected content by its own route — and to
do that it must normalise away exactly the thing the transform applies, because otherwise
the transform reads as a content difference. The result is a pair of guards that between
them cannot see the transform at all. Change it and both stay green.

**Example.** A region generated into a host document carried a constant line prefix that kept
it nested inside an enclosing structure. The round-trip guard called the generator to build
its expected value, so the prefix constant appeared on both sides of the comparison. The
independent guard collapsed whitespace before matching, precisely so the prefix would not
count as a difference. Substituting the constant with several different values — including
one that changed the document's structure by un-nesting the region entirely — left both
guards passing.

**Detection / Contract.** The escape from a closed-loop verification can itself be blind on
the axis it was built to escape.

- **Name the transform, then ask which guard would see it change.** If the answer is "none",
  that is a third assertion waiting to be written — not a gap the existing two cover between
  them.
- **Pin the transform from the artifact's raw bytes.** Read the file, not the generator's
  constant; importing the constant rebuilds the closed loop one level up.
- **Prove it by substitution.** Vary the transform through several values, including a
  degenerate one, and require a red. A transform nobody has ever perturbed is unverified
  regardless of how many guards surround it.
- **Expect independence and completeness to trade off.** A guard made independent by
  normalising is, by construction, blind to whatever it normalised. That is not a flaw in the
  guard; it is the reason a third one is needed.


### 13.24 The defect you found is real, and it is not the one that was reported

**Signature.** A symptom is reported. Investigation finds a genuine defect nearby
— measurable, fixable, worth fixing — and it is fixed, with evidence. The symptom
persists, because the reported behaviour and the found defect live in different
components. The danger is not the wasted work; the work was good. It is that a
well-evidenced fix reads like a resolution, so the report gets closed by
association and nobody re-checks the thing that was actually asked about.

**Example.** A ranking hint always named the same document. The scorer was found
to have a real, unacknowledged bias: it summed matched-term weights with no
normalisation for document size, so the largest document won on breadth. That was
measured (75 of 246 labelled queries returned some larger document), corrected,
and the correction verified (+19.5 points of top-1 accuracy). The reported symptom
did not change at all — because its cause was a *caller* handing the ranker a
whole paragraph where the ranker was built for a short phrase. The bias scales
with matched-term count, so no setting sane for a real query could absorb a
paragraph. Two defects, one component apart; fixing the deeper one left the
visible one exactly where it was.

**Detection / Contract.** Re-run the original reproduction, not the new test.

- **Close the loop on the SYMPTOM, not on the fix.** A fix earns its own tests;
  the report needs the thing that was reported to change. Run it and look.
- **State the gap out loud when it exists.** "This is a real improvement and it
  does not resolve what you reported" is a complete, honest result. Silence
  invites the reader to assume otherwise, and a good measurement attached to the
  wrong claim is more misleading than no measurement.
- **Suspect a contract violation when a mechanism misbehaves only for one
  caller.** If the same mechanism is fine everywhere else, the input is the
  outlier — look at what that caller passes before re-tuning what everyone uses.
- **Ask which component the evidence actually indicts.** Measuring a component
  proves things about that component. It says nothing about the one upstream of
  it, however satisfying the numbers are.


### 13.25 A guard written for a shape its subject no longer has

**Signature.** A pattern-matching guard is written against the shape its subject
has today. The subject's shape later changes — a heading style, a command form, a
file's conventions — and the guard is not updated with it. It does not degrade
gracefully or half-fire: its population drops to **zero**, it can no longer fail,
and a check that cannot fail is indistinguishable from a check that passes. It
then reports success on every run, indefinitely, over exactly the defects it was
written to catch. Reading the code will not reveal this, because the code is
correct for the shape it was written for; only counting what it matches *today*
will.

**Examples.** Three, found in one session, none by reading:

- A contract forbidding duplicate changelog categories matched `^### Fixed`. The
  changelog had switched to `**Fixed**` bold labels and contained **zero** h3
  headings, so the predicate had never matched anything since the switch — while
  green over two live duplicates. Its sibling check, guarding the same file for a
  related property, shared the identical blind spot.
- A checkpoint warning before uncommitted work is discarded required the verb to
  be followed by `--` or `.`, so the bare `<verb> <path>` form — the one most
  likely to be typed — passed silently while the explicit form fired on the same
  file. Here the omission was *deliberate*, taken to avoid a false positive; the
  reasoning was right about the regex and wrong about the conclusion, because the
  ambiguity it avoided was mechanically resolvable.
- A numeric contract binding a value across many documents bound **one of four**
  restatements inside a file it already declared, so raising the value would have
  been forced through the bound line and left three statements false.

**Why it survives.** Every other signal points the wrong way. The test is green.
The code reads correctly. The guard appears in the suite, in the coverage count,
and in any inventory of "what protects this." Its very existence is taken as
evidence the hazard is handled, which is why the hazard goes unhandled for so
long: nobody writes a second guard for something already guarded.

**How to detect.** Count the population, do not read the predicate. For any
pattern-matching gate, run its matcher against the live tree and look at the
number of hits. **Zero is the alarm; near-zero on a subject that should be
plentiful is the same alarm quieter.** Two cheap habits catch the class:

- When you change a subject's *shape* — a heading convention, a label style, a
  command idiom — grep for guards keyed to the old shape in the same commit.
- When a guard is deliberately narrowed, record what the narrowing gives up. A
  documented omission is reviewable; an undocumented one becomes invisible the
  moment its author moves on.

**Not to be confused with** §1.7 (a gate tuned to HEAD, which fires but only for
today's population) or §13.21 (a guard validated only at the population's current
size). Both of those still *match* something. This one matches nothing at all.

### 13.26 A duplication contract whose two sides are not independent

**Signature.** A guard checks a declared thing against an "independently computed"
expectation, and the expectation is not independent — it is derived from the same
source, the same glob, or the same constant as the thing under test. Both sides then
move together through exactly the edit the guard exists to catch, and it stays green.
Unlike §13.25 the population is healthy and the predicate matches plenty; the guard
runs, compares real values, and agrees with itself. Every observable signal is
indistinguishable from a working contract.

**The attestation.** A scan-target drift test (2026-08-09) advertised two silent drift
modes in its own docstring and could reach neither. Its expected set restated the two
globs the scanner itself used, and it subtracted the same `CANONICAL_FILES` frozenset
the scanner subtracted internally — imported from the scanner. So a new directory under
the scanned tree was absent from the expectation exactly as it was absent from the
scanner, and editing the canonical set moved both sides in lockstep. Driven on a
synthetic tree, planting a new module inside a new directory — verbatim the case its
docstring named — left it **GREEN**. The only edit it could ever have caught was
someone changing one hand-copy of the globs and not the other, which is not a drift
mode anyone had worried about.

It had been that way since it was written, and a pack was mid-flight to promote its
shape to a shared registry across the whole defect class.

**Why it survives review.** The word *independently* appears in the docstring, and a
reader takes it as a description rather than a claim. The two sides are also spelled
differently enough to look distinct — one is a `glob` chain, the other a function call
returning the same paths — so the shared origin is visible only if you resolve both to
their source. Reading either side alone shows nothing wrong.

**It duplicates the narrowing, not the derivation.** That is the compressed diagnosis.
Deliberate duplication is a legitimate and powerful gate — the folder-router population
contract in this repo re-types its `git ls-files` call rather than calling the discovery
helper, and says why in capitals — but the duplication has to reproduce the *derivation*
from an independent angle. Reproducing the same *narrowing* buys nothing and costs the
appearance of safety.

**The tell:** the expected side imports from, or globs the same paths as, the code under
test. Grep the guard for imports of its own subject. A stronger, mechanical form: assert
that a registered derivation's source does not reference the symbol it audits.

**Detection.** Reading will not find it; both sides are correct in isolation. Perturb
the *subject* — plant the drift the docstring claims to catch — and confirm the guard
reds. A guard that has only ever been observed green has not been tested, it has been
assumed. This is §7 (earn the red) applied after the fact, and it is the only reliable
detector for this class.

**The repair shape.** Replace equality-against-a-restatement with a **closure**
property: everything in the population equals what was enrolled plus what was excluded,
each exclusion carrying its reason. The population comes from an oracle the subject does
not use (`git ls-files` where the subject uses `Path.glob`), so it cannot inherit the
subject's shape, and narrowing becomes reachable only by adding a named exclusion, which
is visible in review. Pair it with a floor so the population cannot silently collapse,
and a self-expiry so an exclusion that no longer silences anything is deleted.

**Not to be confused with** §13.25 (a guard whose population has dropped to zero — it
matches *nothing*; this one matches normally and is wrong anyway) or §2.8 (a lock test
narrower than its class, which fires correctly but over too small a set).

### 13.27 A threshold whose sign was inverted, silently orphaning what it doubled as

**Signature.** A guard asserts a minimum — "at least N of the thing were checked" — and
that minimum is quietly load-bearing for several unrelated regressions, because *every*
way the mechanism can break makes the count fall. Later the policy changes and the
minimum becomes a **maximum**: a ratchet driving the population toward zero. The
assertion still reads as a threshold on the same number, so the inversion looks like a
one-character change. It is not. Every regression the floor caught now makes the count
go *down*, which a ceiling reads as **success**. The guard keeps passing and has stopped
watching.

**The attestation.** A citation-anchor scan (2026-08-09) carried
`_MIN_BARE_ANCHORS = 20`, whose comment named three regressions it detected: the regex
stopped matching, the resolver stopped resolving, or the document population shrank. When
the project decided to retire the citation form rather than police it, the floor became
`_MAX_BARE_ANCHORS`. All three detections were orphaned in the same edit, and nothing
failed — a resolver answering `missing` for everything now yields *zero* matches
evaluated, no failures reported, and a ceiling comfortably satisfied.

**It also changes what the number must count.** A floor had to count *evaluations*: a
broken resolver left the regex matching happily while the predicate checked nothing, so
counting matches would have scored full coverage. A ceiling has the opposite duty and
must count *matches*, because an item that fails to resolve is still an item you do not
want. The two directions are not symmetric and the correct denominator flips with the
sign.

**The repair shape.** Rehome each orphaned detection explicitly rather than assuming the
new assertion inherits it, and rehome it to something that survives the ratchet reaching
zero — at zero live items there is nothing left to count, so any live-population check is
already dead. Population collapse goes to a closure contract with its own floor;
predicate health goes to **synthetic** fixtures that supply the item themselves. Then
*pin the dependency*, because it is invisible at the call site: a future reader deleting
an "earn the red" test as redundant would be removing the last detector without any
signal saying so.

**Corollary — the floor of a ratchet is rarely zero.** Documentation *about* a banned
form has to exhibit the form: the guard's own worked examples, a doc's explicit
counter-example, a synthetic placeholder. In the attestation the irreducible residue was
7, and the comment block written to document the retirement itself minted 6 fresh
instances and reddened the ceiling that had just been lowered. Declare the residue with a
per-item reason, and do **not** exempt it from the count — an exempted residue is an
allowlist that grows silently, whereas a counted one means any growth still reds.

**Not to be confused with** §13.25 (a population that dropped to zero and matches
nothing — here the population is *deliberately* driven toward zero and that is the goal)
or §2.8 (a correct assertion over too small a set). The defect here is a correct-looking
assertion that changed meaning when its sign flipped.


### 13.28 A guard whose population excludes its subject

**Signature.** A check is correct, thoroughly tested, and pointed at the wrong
set. Not the wrong *shape* (13.25) and not an inverted *threshold* (13.27) — the
mechanism does exactly what it says, and the population it runs over simply does
not contain the thing it exists to protect. It therefore passes forever, and it
passes *honestly*: every assertion in it is true of everything it looked at. The
defect is not in the check and not in the subject; it is in the relation between
them, which is the one place a per-file review lens cannot look, because every
file involved is individually fine.

**Attestations.** Two, found in one session (2026-08-11), neither by reading:

- A ledger guard reported rows tagging an already-landed pack. It matched *prose*
  ownership tags — `LANDED`, `owned:`, `drafted-pack (...)`. The row form that
  actually accumulates in that file is a member-table **id cell**, which carries
  no prose tag at all, so the dominant shape had never been in the population.
  The guard had returned `[]` for its whole life and two genuinely stale rows sat
  behind that green.
- An integrity-manifest test file carried a dozen thorough arms — tampering,
  truncation, symlink refusal, absent-vs-unreadable sentinels — and **every one
  called the verifier against a `tmp_path` fixture.** The live repository, the
  only tree that can actually drift, was in no test's population. Real drift in
  six files consequently survived a full green suite and was found only when an
  unrelated command ran the check explicitly.

**A variant worth recognising: the population of READERS.** The same session found
a detector that ran every session, correctly, and wrote its finding to stderr —
while the only consumer of that hook reads a different channel. The check's inputs
were right; its *audience* excluded the reader. "Who or what actually receives
this output?" is the same question asked at the other end.

**The tell, and why reading will not produce it.** Reviewing the guard confirms
the guard. Reviewing the subject confirms the subject. The gap only appears when
you **drive the predicate over the real population and count what it matched** —
and then ask whether that number can possibly be right. A guard that has never
fired is not evidence of a clean tree; it is an unanswered question. Any assertion
of the form "no problems found" is worth exactly as much as the population behind
it, so state the population, not just the verdict.

**Countermeasure.** For any guard, ask two questions in this order — the second is
the one that gets skipped: *is this check correct?* and *what is it pointed at, and
is my subject inside that set?* When a guard's population is derived (from
`git ls-files`, a folder walk, a registry) rather than restated, this class largely
closes itself — which is the same reasoning as `STANDING_PRINCIPLES` §14, arrived at
from the opposite direction.

**⚠ That last sentence is true only of a guard whose halves are BOTH derived, and
the half-derived case is the one that survives everything above.** Three further
attestations, all in one session (2026-08-12), all in guards written *for*
enumeration integrity — and all three paired a **derived expectation with a
declared population**:

- A sub-mode gate AST-walked the CLI for its canonical set — genuinely derived,
  genuinely auto-updating — while hand-listing the five documents it checked
  against it. A sixth document showed 3 of 10 for its entire life, green
  throughout.
- A roster pin iterated a six-name tuple beneath its own comment reading *"All 5
  standard checks present."*
- A renderer built to close this very class printed *"5 files"* above a list of
  three, having drawn the count from one population and the names from another.

**Why the half-derived case is worse than the fully-declared one.** A guard that
derives its *expectation* **reads as derived** — the AST walk or the registry
lookup is right there in the body — so the review question *"what is this pointed
at?"* gets answered *"the live source"* and stops one step early. The declared
half is never examined, because the derived half already supplied the reassurance.
So ask it twice, once per half: *what is the expected value derived from?* and,
separately, *what is the set of things being checked derived from?*

**And a derived population still needs calibrating.** Intent is not a rule.
Measured on the same corpus: a naive membership test (*does this document mention
two or more of the names?*) flagged 20 of 278 tracked files with 13 false
positives — including a declared record surface that policy forbids enrolling at
all. The rule that actually distinguishes an enumeration from a passing mention
keyed on **contiguity** — two or more distinct items inside a single block — and
flagged exactly 5, none spurious. A discovery arm is an enforcement contract:
calibrate it against the live population before trusting it, or its own noise gets
it switched off in the first week.

### 13.29 Automation inherits the code, not the operator

**Signature.** A write that had been run by hand gains an automated caller. No
line of the write changes; it stays correct, tested and idempotent. What expires
is everything the *person* was supplying without writing it down — and because
none of it was ever in the code, none of it leaves a diff to review. The sibling
of §13.28: there a guard's population excluded its subject, here a change's
review scope excludes the only thing that changed.

**The tell is mechanical.** When a change moves an operation from manual to
automatic, enumerate what the human was providing and ask which of them the code
now supplies:

| The human silently supplied | The code must now supply |
|---|---|
| Never two at once | Mutual exclusion across the read-modify-write — an atomic *replace* is not an atomic *update* |
| A correct working directory | A resolved destination, and a refusal to CREATE what should already exist |
| Eyes on stderr | A reader — a channel the calling runtime actually consumes |
| Judgement not to run in a broken state | An explicit precondition check |
| "Nobody else reads what I write by hand" | A classification — the artifact is now an *input* to every tool that walks its surface |

Each row the code does not supply is a hazard that fires on the first unattended
run, which is precisely the run nobody is watching.

**Why row 2 bites hardest.** A relative default plus an atomic writer that calls
`mkdir(parents=True, exist_ok=True)` does not error on a wrong working
directory — it creates a second copy of the file, writes everything into it, and
returns a success count. The run reports that it appended 151 entries; the real
file never changed; nothing downstream can tell, because a count is not a
destination. Make the operation report *where* it wrote, not only how much.

**Attestation — one firing, one preemption, and the distinction matters.** A
machine-appended dedup corpus is the worked example. Commit `09be6f5` added it to
a freshness scanner's surface denylist after a corpus line quoting marker syntax
parsed as a live marker and reported a critical finding: a **real firing**, and
the reason row 5 exists. Be precise about two things the temptation is to
overstate:

- That commit **predates the automated writer by a week**, so it attests row 5
  and *not* the automation thesis. Conflating them lets the class borrow evidence
  it has not got.
- The matching exemption in a vocabulary scanner is a **preemption, not a second
  firing** — driven: with the entry removed, the live corpus produces zero
  findings, because no stored claim currently carries a severity label in the
  shape that scanner detects. The hazard is reachable, not realised.

One firing and one preemption in two scanners is enough to justify a class-level
guard and not enough to call it a pattern with two data points. A class entry
that overstates its own attestations is the same defect it describes.

**Countermeasure.** Review the *caller's new operating envelope*, not the
callee's correctness — the callee is usually fine, which is what makes this
invisible to a per-file lens. Ask what the loop around it used to be made of.
Enforcement for the worked example: `espalier/fan_out_findings.py::_corpus_write_lock`
(row 1), `espalier/fan_out_findings.py::append_findings_to_corpus` via its
`require_existing` argument (row 2), and the persist payload's `warnings` field
(row 3). Rows 4 and 5 -- the shared write's `shared_error` field and the
doc-walking-scanner corpus check -- retired with the shared corpus on
2026-09-21. One tracked surface still receives agent-composed prose: the
convergence ledger, a maintainer-side memory record that the convergence-critic
appends a row to each round. It sits in every record-surface roster and, since
the same date, in the retired-vocab scanner's exempt list -- the sibling of the
false-fire the corpus once produced -- so the class has one declared instance
left, not none.


### 13.30 A guard green because git shows the author a file no clone has

**Signature.** A contract enumerates a set of paths and asserts something about
each. Every path is real, the assertion is correct, and the suite is green — on
the machine where the set was written. One member is **gitignored**, so it exists
in the author's working tree and in no clone at all. The contract then reds on
every fresh checkout and every CI cell, and it reds for a reason no amount of
re-reading the code reveals, because the code is fine and the *environment* is
the input that differs.

**Why the usual proof misses it.** "Full suite green" is the strongest routine
evidence available, and it is measured on exactly the one tree that cannot
exhibit the failure. Running the suite again is not a second opinion — it is the
same observation repeated. The distinguishing act is to obtain a tree built the
way CI builds one:

```bash
git clone --local --no-hardlinks . /tmp/probe && cd /tmp/probe && pytest -q
```

**The assertion to write instead.** `Path.exists()` answers *is this file on this
disk*, which is a dev-tree fact. The honest question for a registry of names is
*does git know this name* — tracked, **or** deliberately ignored:

```python
tracked = set(subprocess.run(["git", "ls-files"], ...).stdout.split())
if not tracked:
    pytest.skip("not a dev tree / fresh clone")     # fail closed, never open
ignored = {p for p in REGISTRY
           if subprocess.run(["git", "check-ignore", "-q", p], ...).returncode == 0}
assert not set(REGISTRY) - tracked - ignored
```

`check-ignore` answers for a path whether or not it is present, which is what
makes it survive the clone. Off a git work tree it returns 128 and contributes
nothing, which *shrinks* the allowed set and makes the assertion stricter — the
direction to preserve if this is ever refactored.

**The mirror-image sibling, and why both are the same family.** A **new untracked**
file makes `git ls-files`-based contracts pass by never scanning it (a
false-green that fires only after the commit makes it tracked). A **gitignored**
file makes an existence-based contract pass by being present only for the author
(a false-green that fires only when someone else checks out). One is invisible to
git and visible to you; the other is visible to git-as-a-name and absent from
every clone. Both are the same question asked at the wrong altitude: *whose view
of the repository is this assertion actually about?*

**Attestation — one firing, and the aggravating detail is the point.** A record
registry listed a gitignored, never-committed session archive; the arm asserted
`.exists()`; the full suite reported 8115 passed and the commit landed. Reproduced
by cloning the repo and running the committed code against it: red, immediately,
on that one member. The sibling module in the same repository had already met this
failure and carried a `_gitignored_record_surfaces()` helper written for it, a
hundred lines from where the new arm was authored. Prior art existing is not the
same as prior art being reached for — which is the practical argument for
searching the neighbours before writing a new guard, not merely before writing a
new *rule*.

### 13.31 Closing a fail-open opens its fail-closed twin

**Signature.** A gate is found to accept something it should refuse, and is
tightened. The tightening is correct in the case that motivated it, and it
introduces the opposite error in a case nobody enumerated: the gate now refuses,
or discards, something it should have kept. Both faults share one root — a
predicate that cannot distinguish two conditions — so fixing the direction that
was noticed, without separating the conditions, relocates the defect rather than
removing it.

**The tell is a return value carrying two meanings.** Watch for a single code,
flag or sentinel that stands for more than one situation:

| The caller believes | The value also means | Consequence of conflating |
|---|---|---|
| "the payload was rejected" | "the store was unavailable" | a *valid* record is discarded |
| "no results" | "the query failed" | absence is reported as a clean result |
| "not permitted" | "permission could not be determined" | a legitimate actor is refused |

None of these is visible from the caller. The discrimination has to exist at the
source — a distinct code, a typed result — and the caller must key on **the
value, never the message text**, or a wording change silently reroutes the branch.

**The question to ask before shipping the repair.** State the fault as a
direction, then invert it:

> I stopped X from claiming *more* than Y. Can X now claim *less* than Y?

If the answer is not a confident no with a test behind it, the repair is half
done. Note that the inverted failure is usually *quieter* than the original: the
first fault leaves an artifact that looks wrong on inspection, while the second
leaves nothing at all — and an absent record is indistinguishable from work that
was never done.

**Attestation.** A planner recorded a justification its validator had refused,
because it wrote the field and validated afterwards — a presence check could not
tell a refused payload from an accepted one. The fix wrote only after acceptance.
But the validator's CLI exited with the same code for *"refused"* and for *"no
active session"*, so re-running the documented resume step with the store absent
now **deleted a justification that had already been accepted and written**. Driven
on both sides of the commit: before, the record survived; after, it was gone while
the store still held it. The repair had preserved the disagreement it was written
to remove and merely swapped which side was lying. Separated by giving the store's
unavailability its own exit code, with the two pinned unequal by contract.


### 13.32 A suppression that silences a true positive

**Signature.** A test fails in one environment and not another. It is marked,
skipped or excluded there on the reasoning that the environment is different —
and the failure was correct. The environment was not the problem; the test was
wrong, and that environment was the only one asking it the right question.

**The discriminator, before any suppression.** Two questions that sound alike
and are not:

| Ask | Suppress if | Fix if |
|---|---|---|
| Is the INVARIANT unanswerable here? | yes — the data it needs is genuinely absent | — |
| Is the TEST's own definition narrower than the code's? | — | yes — it disagrees with production everywhere, and this environment merely exposed it |

Only the first justifies a marker. The second is a defect the environment
surfaced, and marking it converts a working detector into permanent silence
— the failure stops being visible in the one place it was visible.

**Why it is easy to get wrong.** Suppression is cheap, arrives with a plausible
story ("that invariant only holds on a full tree"), and turns a red into a green
immediately. Reading the assertion is the whole defence: if the test computes a
policy — a threshold, an accept-set, an expected exit code — check whether the
code under test computes the same one, or whether the test has quietly forked
its own copy. A forked policy disagrees with production on *every* tree; the
environment that failed is just where the disagreement became observable.

**Attestation.** A test derived a pass/fail expectation from one status value
while the shipped code routed through a four-value accept-set. On the usual tree
both agreed by coincidence, because the extra values never occurred there. In a
reduced environment the code legitimately produced one of them, the test computed
the opposite, and it went red — correctly. The first response registered it as an
environment-only invariant. Review found the fork: the test was the fifth
independent copy of a policy whose own documentation said it had exactly one
home. Routing the test through that home made it hold everywhere and the
suppression went away. The guard that existed to forbid a second copy had scanned
only the implementation package, so it could not see a copy living in the test
file forty lines below itself.

### 13.33 A rule stated in the tracker, enforced nowhere

**Signature.** A class of defect is fixed and the fix is written up with a rule
for the future — "route every caller through the helper", "always pass the
flag", "this guard is load-bearing, do not remove it". The rule is correct. It
lives in a commit message, a ledger row or a code comment, and nothing executes
it. The class reopens, usually with the same words already written down.

**The tell.** Any sentence in a fix's own description that generalizes beyond
the lines it touched. If the repair says *"so a third caller cannot do this"*,
ask what stops the third caller — and if the honest answer is "someone will read
this", the class is not closed, it is deferred.

**Three shapes of the same absence:**

| Written down | Nothing enforces | Add |
|---|---|---|
| "route every site through the helper" | a new raw site | a per-module ratchet: reds when a count rises AND when it falls, so a freed slot cannot absorb a replacement |
| "this guard is load-bearing, do not remove" | its deletion | a test asserting the guard fires — drive the condition, assert the skip/raise |
| "this suppression is needed because X" | X ceasing to be true | an audit mode that RUNS the suppressed cases in the environment they were suppressed for; anything that passes is stale |

**A guard nothing witnesses is also unenforced.** A new check can be surrounded
by tests that all pass for a *different* reason — a floor, an exception type, an
error code — leaving the check itself unpinned and its deletion invisible.
Mutation is the only honest test: remove the guard, run its own suite, and see
what dies. If almost nothing does, the tests are witnessing something else.

**Attestation.** A class was closed with the note "apply it from one helper so a
third caller cannot re-introduce the distinction". No helper was built; the rule
stayed in the tracker; five further sites re-introduced the defect and the class
reopened months later. The helper was then written — and the routing rule was
again left as prose, with more than twenty unrouted call sites, until review
caught the repeat. Separately, deleting the new helper's central guard left
24 of its 26 tests green, because every refusal they asserted was reachable
through a size floor instead; the case only the guard could catch had no test at
all.


### 13.34 A floor that counts the population cannot see a key that stopped matching

**Signature.** A guard walks a population, and for each member it inspects only
the items that match some *key* — a name, a path, a command string, an id. Its
author knows a guard can pass vacuously, so it carries a floor. But the floor
counts the **population** (how many members were examined) or a **global total**
of matches across all of them. Neither can see a key that stopped matching for
*one* member: that member is silently skipped, its share of the total is small,
and the threshold still clears. The guard reports full coverage over a member it
never actually inspected.

**The tell.** Any floor of the form `assert total_hits >= N`. Ask one question:
*if exactly one member stopped keying, would this still pass?* If the answer is
"the total drops a little and the assert survives", it is a population floor —
whatever its comment says it is.

**Why it is specifically hard to see.** The floor is usually written by someone
who has just been bitten by vacuity, so it arrives wearing the right vocabulary.
The docstring says *"this is the keying floor"* and the assertion is a count.
Naming the hazard correctly is not the same as measuring it, and the name makes
the code read as though it were.

**The shape that works.** A **per-member** floor: every member must contribute at
least one keyed hit, or appear on an explicit exemption list *with its reason
stated inline*. The exemption list is the point — it converts "this member
produced nothing" from an invisible arithmetic fact into a decision somebody
wrote down.

**Related keying hazards.** A key that is *more specific than the thing it
identifies* fails the same way: keying on a full path (`a/b/x.py`) misses
a payload that names the same thing by basename (`x.py`), and both spellings
are usually already live in the codebase. Prefer the least-specific spelling that
is still unambiguous, and check what the neighbouring guards key on before
choosing — a sibling assertion in the same file often already made this choice
correctly.

**Attestation.** A guard was written specifically to close a keying-blindness
class. Its floor asserted a global count of at least four against a live twelve,
and its own failure message read *"a population floor cannot see a keying defect;
this is the keying floor."* It was a population floor. Re-introducing the very
defect it was written to catch — with the payload naming the command by basename
rather than by path — left the guard **green**, because one member's keying loss
cost two hits out of twelve. The correctly-keyed expression already existed in a
sibling assertion ten lines below. This was the second occurrence of the class in
consecutive work sessions; the first had been written up in prose, which did not
prevent the second (see §13.33).

### 13.35 An ordering oracle asked a question about content

**Signature.** The real question is *"does side A carry work that side B never
received?"* — a question about **content**. The implementation reaches instead
for an **ordering** oracle: timestamps, ancestry, sequence numbers, "which one
changed last". Ordering is cheap, available, and feels equivalent. It is not.
Ordering answers *precedence*; the question was about *divergence*.

**Two failure directions, and you will usually only see one.**

| Ordering says | Reality | Result |
|---|---|---|
| the two events are **equal** (same second, same commit, same revision) | unresolvable — ordering has no answer here | the tie gets defaulted, almost always to "safe", and the dangerous case passes silently |
| one side is **permanently ahead** after a legitimate operation touched it alone | nothing is wrong; the skew is an artifact of a normal workflow | the guard refuses **forever**, with a stated reason that is false, and the only exit is the override flag — which trains the operator past the guard entirely (see §13.33 on unenforced rules, and note the override disables protection for the case the guard exists for) |

**The strongest tell in this catalog.** *Two independent reviews blocking on the
same site in opposite directions.* That is not two bugs. It is one wrong
abstraction, and each review has found the end of it that its lens reaches.
Patching either direction ships the other. When it happens, stop patching and
ask what question the code is actually answering.

**The shape that works.** Ask about **content at the boundary**: were the two
sides already different *at the last event that touched the side in question?*
This is immune to clock granularity, to rebases and history rewrites, and to
both failure directions above — because the legitimate operation leaves the two
sides equal at that boundary, and the divergent one leaves them different,
regardless of ordering.

**Attestation.** A guard protecting a generated file from being overwritten went
through three oracles. (1) **Commit timestamps** — two commits made in the same
second compare equal, so the dangerous case passed in the guard's own
red-earning exercise. (2) **Ancestry** — an adversarial review found it refuses
forever after an ordinary regenerate-and-commit, with a false stated reason; an
independent correctness review found the opposite hole, that two changes landing
in a single broad commit read as "did not move after" and were silently
discarded. (3) **Content at the boundary commit** — resolved all ten driven
scenarios. Ordering felt correct three times and was wrong three times.

### 13.36 A guard introduced later than the thing it guards refuses its own history

**Signature.** A tool maintains an artifact that accumulates across runs. A new
invariant is added to the tool — a provenance trailer, a schema version, a
required field — and the check is applied unconditionally to whatever it finds.
Everything written *before* the invariant existed now fails it. The tool refuses
the exact artifact it was built to maintain, and the refusal is correct by the
rule as written.

**Mechanism.** The guard's validity window opens at the commit that introduced
it; the artifact's opened earlier. Telling "foreign" from "ours, written before
we started marking our work" requires evidence the older state cannot carry, by
construction — the marker is precisely what is missing. So the predicate
collapses two conditions and refuses both. Unlike 13.25 and 13.28, which fail
*open* and stay green for months, this one fails **closed** and is found within
minutes: the tool bricks on first use. The danger is not that it hides — it is
what the obvious repair does.

**Measured instance (2026-09-01).** `scripts/record_snapshot.py` writes chained
snapshots to `refs/heads/record`. Mid-session it gained `RECORD_TRAILER =
"Espalier-Record: v1"` and an ownership check, so the tool would refuse an
unrelated branch of the same name rather than move it and replace its content.
Two records had already been written, without the trailer. The check refused the
tool's own ref, and the builder could not run on the repository it was written
for.

**The repair that would have destroyed data.** The obvious fix is delete the ref
and rebuild — the artifact is *generated*, so it should be reproducible. It was
not. Checked before acting: the ref held
`cc/blueprints/20260708-025726-20d8c7.json`, which no longer exists on disk. The
record had already preserved something the working tree dropped, before the tool
that maintains it was finished. A rebuild from the current tree would have
succeeded, exited 0, and produced a *smaller* artifact that looked complete.

**Why "just regenerate it" feels free and is not.** For a derived artifact the
intuition is that content is a function of the current source, so the copy is
redundant. That holds only while nothing has been lost. An accumulating record's
entire purpose is to diverge from the current tree — it exists to hold what the
tree no longer does. For exactly the artifacts this failure mode strikes, the
reproducibility assumption is false *by design*, and it is false silently: the
rebuild does not report what it could not find.

**Detection.**
- When adding an invariant to a tool that maintains persistent state, ask what
  the state written *before this commit* does when the check runs. If the answer
  is "fails it", the invariant is incomplete until it ships with a migration.
- Adoption must **chain, never replace**. Replacing discards the parent history —
  which is the operation that would have lost the blueprint above. Earn the red
  on that specific mutant, not only on the refusal.
- Keep adoption explicit and one-time. An automatic fallback to "accept
  untrailered" is not a weakened guard, it is no guard: it restores exactly the
  case the check exists to refuse.
- Before deleting anything that has been accumulating, do not ask *"can I
  regenerate this?"* — ask *"is anything in here no longer present in the source
  I would regenerate it from?"* The two questions have different answers, and
  only the second one is about data loss.

**Contract.** A guard added to a tool with persistent state ships with a stated
path for the state that predates it — an explicit, one-time, chaining adoption —
or a recorded reason why refusing forever is safe. Until the old artifact has
been shown to hold nothing unique, "delete and start over" is a data-loss
operation, not a reset.

**Cross-ref.** §13.31 (closing a fail-open opens its fail-closed twin) is the
adjacent shape: there a predicate conflates two conditions after a tightening;
here the two conditions are separated by *time*, and one of them is the tool's
own past. The mirror image is worth holding alongside it — a carve-out whose
justifying reason expires while the carve-out itself stands. Both are ordering
faults between a rule and its subject: one rule arrives too late to recognise
what it governs, the other outlives the reason it was granted.

### 13.37 An oracle keyed on a name or a spelling, asked a question about identity or behaviour

**Signature.** A check keys on the *token* something is written as — a regex
mirrored from another module, a literal path compared as a string, a whitespace
split of an argument list, a substring search over a whole file, a directory
name collapsed from a manifest entry — while the question it answers turns on
what the thing *is* or *does*: the same inode, the same engine behaviour, one
operand, one section of a document, one entry of a manifest. The check is green
on every input its author typed and wrong on the first input that spells the
same thing differently. Nothing fails loudly; the guard reports the safe
answer for the spelling it was shown.

**Mechanism.** Spelling is the cheap proxy for identity and it is usually
right, so the proxy gets written first and the question it stands in for is
never named. The inputs that break it are not adversarial — a filesystem that
folds case, a path with a space, a Unicode prefix, a comment on the same line,
a sub-directory under a name the manifest also uses — so they arrive from
ordinary use, and the test corpus, written by the same hand, spells everything
the same way the code does. Five instances landed in one day, across two
changes, each found by a review pass driving inputs the author had not:

- a managed-marker regex mirrored byte-for-byte from the engine, while the
  engine's *behaviour* was to strip a run of default-ignorable codepoints
  first; a zero-width space before the marker read a deployed hook as unmarked
  and flipped the tool's whole mode;
- a harness zone compared as the literal `tools/cc` against the directory
  name a walk met, on a filesystem that folds case; a repo that already had
  `Tools/` received the harness inside it, and 38 of 39 files the walk called
  the adopter's own were the harness's — `os.path.samefile` was the question;
- an argument span split on whitespace, with a docstring that called the
  split "conservative — a false negative would leak"; a quoted Windows path
  with a space became two fake operands and the real path left the match,
  the exact direction the docstring said could not happen; then, once the
  bare-token arm was made quote-aware, the regex engine re-read a quoted
  operand as a bare token to satisfy a later mandatory part, because the bare
  arm still admitted the quote character;
- a documentation gate that searched a whole file for a label, so a label
  named only in a negative sentence elsewhere satisfied it; the question was
  "does the exit table name it", which needs the block sliced first;
- a manifest-parity test that collapsed every entry to its top directory, so
  a wholesale prune of `bench/` passed the reverse check while hiding the
  host's own files under a label calling them the harness's.

**The tell.** The author cannot say, in one sentence, what the check would
answer on an input that spells the same thing another way — and has not tried
one. The remedy is the same every time: name the question (identity? behaviour?
membership at *this* granularity?), then key the check on that — `samefile`,
the engine's own function driven on the same bytes, one operand tokenizer,
a sliced block, the manifest entry itself — and add the differently-spelled
input to the corpus before the fix, so it goes red first.

**Detection, before a reviewer does it for you.** Mutate the spelling and keep
the meaning: change case, quote an operand with a space, prepend an invisible
codepoint, add a trailing comment, nest under a directory the manifest names.
A check that survives all of those was asking the right question. A check
that survives none of them was asking about the token.

**Related.** §13.34 (a floor that counts the population cannot see a key that
stopped matching — the census form of the same proxy), STANDING_PRINCIPLES §14
(derive the list, don't test a hand-written copy of it), and the sharp edge
"A Closure Guard That Checks Name-Membership, Not Runtime Reachability".

### 13.38 A hand-kept set inside a guard is a fail-open waiting for the member nobody listed

**Signature.** A guard decides a write's target by consulting a small
hand-maintained set — flags that take a value, options that take none, an
exemption for one spelling — and the set is complete for every member its
author thought of. The first member nobody listed does not fail loudly: the
guard reads the input under the wrong rule and answers *allow*. Each fix adds
the missing member, each review pass finds the next one, and the sets multiply
in the direction the review pressure pushes them, right for the corpus and
short for the platform.

**Mechanism.** Ten review passes on one question — how a write guard reads the
operands of `cp`, `mv` and `install` — ran this to its end. A comment scanner
reused the masker's opener set by *name* and cut a span at the `)` of a live
`$(...)`. A `-t` skip read the raw token stream, which did not know that `--`
ends option parsing, so a file named `-t` after `--` disarmed the leg. The
value-flag roster was right for GNU and short for BSD `install`, whose `-B`
took `-t` as a suffix. An exemption set held one exact spelling where the
collision surface was every shorter abbreviation of the same no-value option
(`--st`, `--str`, `--stri`). Four of those were regressions introduced by the
previous pass's fix, and three shared one shape: a rule right at its site and
blind at the view one call away. Extending a set never ended it, because the
next platform, the next abbreviation and the next call site were all outside
the corpus the set was checked against.

**What ended it.** Not a longer roster. Three structural moves, each of which
made incompleteness fail *safe*: the tokenizer named its two end-of-options-
aware views and documented the raw stream as one no consumer may ask a flag or
positional question of; an ambiguous parse *reported* both readings instead of
resolving one, so the consumer took every candidate and the positional pick
too; and the sets were placed where a missing member costs a denied read (a
flag not *known* valueless makes the span ambiguous) rather than a missed
write (a flag not known to take a value would have let its value stand in for
the target). After that the rosters were precision, not safety: a reviewer's
letter-by-letter audit of both platforms' option tables changed nothing the
guard would allow, only what it would over-ask about, and the next pass was
null.

**The tell.** The fix under review adds a member to a set, and the reviewer's
question is "what about the member after that one?" — answered by another
member. Ask instead where the set *sits*: if an omission makes the guard
answer the permissive way, the set is load-bearing and no roster will finish
the job; move the ambiguity to the consumer and let it over-yield. A docstring
that calls a set "precision, never safety" is a claim to drive, not a
description: find one omission, and see which way the guard answers.

**Related.** §13.37 (the proxy that started each of these: a spelling where
behaviour was the question), §2.8 (the corpus that could not see the missing
member because the same hand wrote both), STANDING_PRINCIPLES §14 (derive the
population, do not test a hand-written copy) and §18 (the sibling sites were
in-lane; the count of passes was the class refusing to be patched one member
at a time).

### 13.39 A remedy sentence in operator-facing text is a claim nobody drove

**Signature.** A diagnostic names a cause correctly and then tells the
operator what to do about it, and the instruction is the part nobody ran. It
reads right, it is short, and it is the highest-blast-radius sentence in the
change, because an adopter follows it verbatim on the tree that has the
problem — an edited copy, a legacy copy, an uncommitted copy — not on the
fresh fixture the author tested.

**Mechanism.** A fifteen-line change to `doctor`, graded a nit, took four
review passes because each cut shipped a remedy sentence with a different
untested claim in it. "Re-run `upgrade`" re-seeded nothing: an unstamped copy
is preserved by design, and a version-current `upgrade` returns before the
seed loop. "Delete the file and re-run `init`" worked, and discarded
sixty-one lines the adopter had written, because the packaged body for the
two grounding docs is a near-empty stub. "Restore the committed first line"
was right for one of three reachable states and returned exit 0 with a
plausible wrong line — the adapt header, or the doc's own heading — in the
other two; and it carried a POSIX pipe into text a PowerShell adopter pastes.
The tests asserted the *sentence* every time. The test that would have caught
each cut performs the remedy on the edited copy and asserts the content
survives, the count drops to zero and a later `init` still preserves the file.

**The tell.** The test for a diagnostic checks that a string appears. The
remedy names a verb (`upgrade`, `init`, `git show`, `fingerprint`) that the
test never invokes. Or the remedy is unconditional where the state it
addresses has a branch the operator cannot tell apart from the tree in front
of them ("only if you never edited it" is a question the harness itself
answers with *cannot prove*). Drive the remedy on the *worst* copy — edited,
legacy, uncommitted — before the sentence lands; where a remedy cannot be
made to work in every reachable state, put the acceptance test in the
sentence ("the line must start with ...") so a wrong result is visible, and
say which state has no remedy rather than letting exit 0 stand in for one.

**Related.** §13.37 (a remedy that reads right is matched by spelling; whether
it works is behaviour), §14.2 (denial-reason opacity is the same failure one
tier down), and the standing principle that self-report is a hypothesis: the
author's belief that a remedy works is the weakest evidence in the change.

**Measured again, 2026-09-12 (the read-only diagnostics lane).** Drive the
remedy to its *terminal* state, not its first step. `doctor` on an uninstalled
tree named the three runtime files left behind and said "delete them to finish
the uninstall". Deleting them left the adopter's own unwired `settings.json`,
which is a runtime marker, so the tree still detected as initialized while the
plan file's absence failed the new branch's own gate -- one step later the
adopter was back on the `fail` wall at exit 1, the verdict the sentence existed
to remove. Both reviewers drove it; the lane's own driven module had run
`doctor` once. The test that catches this performs the remedy and then runs the
diagnostic *again*, asserting the second answer is the terminal one. The fix
re-keyed the branch so that an empty leftover list *is* the never-initialized
report, and the sentence stopped claiming "finish": it names what is still
there, says the settings file stays, and points at the uninstall report's own
preserved-file list for the rest.

**Measured again, 2026-09-12 (the driven-verb lane).** Two checks that wrap
one gate are one fact, and the diagnostic should say it once, with the
finding. `doctor` ran the surface gate as its audit, then ran the self-host
check, which wraps the same gate, and listed both: a nameless verdict ("audit
(surface gate) did not pass") and, beside it, "self-host surface gate: fail",
so one deleted command file counted as three errors with the recovery check's
line, and the headline was the nameless one. Now the audit line carries the
gate's first error-level finding through one owner, the wrapper's line is
withheld when the audit already failed (its verdict stays in the report's
checks block), and the wrapper stands down where the audit does. The second
lesson rode on the first: a name derived from the *mode* is not the fact it
stands for. The gate's label read "self-host" for every mode but the consumer
one, and an adopter's fresh clone of a repo that commits its surface is a
`source_checkout` too, so the label now reads a flag the producer records
from `is_self_host_repo` rather than the mode. The tell for both: a failure
list an adopter counts, where two lines name one file, or a line names a
check that is not theirs.

### 13.40 A liveness check aggregated one level above the thing that dies is a comforting zero

**Signature.** A gate asserts that *some* member of a population reaches
the state it is meant to prove, and reports green. A single member can
fall silent — a spelling that exits non-zero, a row that never runs, a
flag nobody set — and the aggregate does not move, because the assertion
was never about that member. The number stays exactly as reassuring as it
was the day the member died.

**Mechanism.** The metamorphic bench asserted, per *separator*, that at
least one row reached its delete; the rows were head × separator, and a
head whose no-op spelling exited non-zero lost only its `&&` row while
every other head's `&&` row kept the aggregate green. Measured on the day
a per-head check was added: 25 of 68 present heads had been dead on that
axis for as long as the table had existed, and the quick sample CI ran had
dropped the axis entirely, so the new check was unreachable in any
automated run until a test pinned the axis. The same shape sat in the
recall engine: a session cap counted total fires, so a push side that
fired three times in a day looked "under the cap" rather than dormant.

**The tell.** Read a green aggregate as a question, not an answer: *what
is the smallest unit that can die under this number without moving it?*
If the answer is "one row" or "one head" or "one rule", the gate is one
level too high. The repair is the same each time: a hand-kept table made
total over its canon with no default and a pin; one declared exception
with its reason written beside it (`false` cannot reach behind `&&`);
the platform-absent case named apart from the dead case; and the check
placed at the granularity that fails.

**Related.** §13.38 (a hand-kept set fails open for the member nobody
listed — the table this check found was one); §18.4 (a population derived
from the constant it polices shrinks in lockstep); `STANDING_PRINCIPLES`
§5 (the null result is the signal) and §14 (derive the list, don't test a
hand-written copy of it).

**The neighbouring shape (2026-09-06).** The granularity fix above left a
second question the same table answered twice more: *what does each member's
"alive" actually depend on?* A probe exits 0 because of the tool alone, or
because a file exists, or because of a file's CONTENT, or because of state the
probe itself creates, or a permission on the working directory, or a name
database. Only the first is portable; the rest are facts about one machine
wearing the tool's name. The bench's grep rows searched `/etc/passwd` for a
dot (content: a Linux runner's file has none, a Mac's comment block has four),
and its `chown`/`chgrp` rows resolved the user and group NAMES (a database: a
container running an arbitrary UID has no entry). Ask the question per row and
repair in this order: tool-only, then self-created state, then an external
file with the required property named beside it. And carry the exit code into
the failure, so a missing precondition (rc 2, rc 127) is told from a dead
spelling (rc 1) before the repair loop starts in the wrong place.

### 13.41 An excusal scoped to a container widens with the container

**Signature.** A gate needs a way to say "this mention is fine", and the
cheapest scope for that excusal is a container the text already has: the
fenced block, the document, the file. The excusal is written for the one
instance in view and it works. Then the container grows, or the sentence
is copied into another container, and the excusal now covers things its
author never read — silently, because the gate reports fewer findings,
which is the direction nobody investigates.

**Mechanism.** Two instances on one day, both found in review by driving
them rather than reading them. A gate over shipped bodies excused a fenced
command when a disclaimer sat *anywhere* in its fence; the same rule
excused an 88-line reference fence from one comment at its top, and a
disclaimer phrase inside an `echo` string — program output, not prose —
marked the fence it sat in. The same gate let a document opt its source
citations out with one sentence in its head; pasting that sentence into a
second document's head silenced a real dead pointer there, and the
liveness check (does the phrase appear in *some* deployed doc?) stayed
green because it bounded the phrase, not the carriers.

A sibling: a recogniser that scans forward from a mention must first step
past the mention's *own* delimiter. One that read the disclaimer after a
backticked path started at the path's closing backtick and ran to the
next backtick on the line, so the house spelling — `` `x.py` (self-host
only -- not deployed by `init`) `` — was invisible: a third of the live
notes, and the canonical third.

**The tell.** Ask what the smallest unit is that a reader actually reads
as one thing, and scope the excusal to that: the comment that introduces a
run of commands (its own trailing comment plus the nearest comment run
above), not the fence; a table of carriers held equal to the tree in both
directions, not a phrase that may appear somewhere. Then drive the
excusal's *finding* path on a synthetic input — on the real tree every
instance is excused by construction, so nothing there proves the gate can
still find anything.

### 13.42 A rule justified per target, applied per copy

**Signature.** A behaviour is decided by asking *whose file is this* -- the
adopter's own file is edited where it lives, the harness's state is the
harness's -- and then implemented at the level the code is organised in:
per copy of a helper, per module, per side of an isolation boundary. The
copy that serves the adopter's files also serves the harness's state, so
the rule now applies to targets its justification never covered, and the
readers of those targets were written for the old behaviour.

**Mechanism.** The atomic writer exists once on the engine side and three
times under `tools/cc/`. A symlinked target was replaced by a regular file
everywhere, silently; the first fix decided that the engine's copy should
follow the link (its targets include a dotfiles-managed `.gitignore` and
`settings.json`) and the `tools/cc` copies keep replacing it (their readers
refuse a symlinked state file). The justification was per target; the
implementation was per copy. The engine's copy also writes
`.espalier/freshness.json`, whose reader in the same module opens with
`O_NOFOLLOW`: with the old behaviour a symlink there was severed on the next
write and the reader recovered; with the per-copy rule the link survived
every write and the reader returned an empty result forever, with no error.
The failure-mode review measured it on a scratch tree before the change
landed.

**The fix shape.** The default follows the readers (replace a link, so every
symlink-refusing reader can read what the write leaves) and the exception is
an opt-in keyword at the call sites whose target is the adopter's own file,
with a test that pins that set of sites by AST -- a new site that follows a
link is a decision, not a side effect. Every copy's docstring and the
conventions doc state the rule per target, and the note the next author of a
state reader or writer reads (`memory/hook-authoring.md`, self-host only --
not deployed by init) says why the reader and the writer of one file are a
pair.

**How to catch it.** When a rule's justification names a *kind of target*
("the adopter's file", "our state"), find where the code branches: if the
branch is on the copy, the module or the side and not on the target, list
every target that copy writes and check each one's reader. A reader that
refuses what the writer now leaves fails silently in the direction nobody
investigates -- fewer results, not an error. Sibling of 13.41 (an excusal
scoped to a container widens with the container): both are a rule attached
to the wrong unit, and both were found by driving the unit's other members
rather than the instance in view.

### 13.43 A gate whose trigger was widened before its operand worked

**Signature.** A gate has two halves: a **trigger** that decides *when* it fires, and an
**operand** — the value, predicate or corpus it reasons over once it does. They are
usually built in that order, because the trigger is the visible half and the operand
feels like an implementation detail. When the operand is wrong, incomplete or not yet
present, a narrow trigger hides it: the gate fires rarely, agrees with the world by
accident, and nobody looks. Widening the trigger is then experienced as *increasing
coverage*, and it does the opposite — it converts **silent zero-enforcement into loud
wrong-enforcement**, at a moment when the change looks like unambiguous progress and the
suite goes green in both states.

The tell is that the gate's failure is not "it did not fire". It is "it fired, and was
confidently wrong", arriving in a commit whose message reads *broaden*, *widen*, *extend*
or *now also covers*.

**Why it survives review.** The two halves are reviewed against different questions. A
trigger is reviewed against *"does this fire on the cases we care about?"* — answerable
by reading the trigger alone. An operand is reviewed against *"is this the right thing to
reason over?"* — answerable only by driving it. A reviewer who checks the first and
assumes the second signs off on a widening that has no working half underneath it. The
ordering is invisible in a diff, because both halves are present in the final state.

**Remedy — and it is an ordering rule, not a vigilance rule.**

1. **Give the gate a working operand first, and prove it on the narrow trigger.** Drive
   the operand against known-good and known-bad inputs while the trigger is still small
   enough that a wrong answer is cheap.
2. **Widen the trigger as its own change**, with its own before/after count. A widening
   whose only evidence is "the suite is still green" has measured nothing: the suite was
   green when the gate enforced nothing at all.
3. **Ask what the gate would say if its operand were empty or absent.** If the answer is
   "it passes", the operand is not load-bearing yet and widening the trigger will
   propagate that emptiness across every newly covered case. An operand that cannot fail
   is not an operand.
4. **Check the precondition the obligation itself assumes.** A gate that emits a demand
   ("this surface must also declare X") should first verify that the demand is applicable
   here — otherwise widening its population manufactures false obligations that read, to
   whoever receives them, exactly like real ones.

**Attestation.** Observed four times in a single session, in four unrelated subsystems,
which is what moved it from an incident to a class. (1) A planned change was sequenced so
that a broadening step preceded the step that made the broadened thing correct; caught in
planning only because the two steps happened to be numbered. (2) An obligation emitter
gained new surfaces before it checked whether its obligations applied to them, and emitted
two long-standing false demands — driven, the full suite passed *with* the supposedly
forbidden condition present. (3) A workflow gate relieved itself on **having asked** for a
review rather than on a review having occurred: it wrote its own satisfaction marker, so
every subsequent run passed regardless. Its sibling gate had been repaired years earlier
to require evidence; this one never was, and the difference was invisible because both
were green. (4) A retrieval engine's relevance floor was scheduled to have its corpus
widened before the floor itself was fixed — measurement showed the widening would have
increased wrong answers while the floor was known not to work, and the ordering rule is
what caught it before the work was done.

A fifth instance, from the session that wrote this entry, is the sharpest: the floor in
(4) turned out to be **unfixable** — nine candidate mechanisms all measured with a
negative margin. Had the corpus been widened first, the extra wrong answers would have
been attributed to the new corpus rather than to a floor that never worked, and the real
finding would have been buried under a plausible false cause. **Getting the order right
is not only about avoiding harm; it is about keeping the diagnosis available.**

### 13.44 A wall-clock ceiling sized on one host

**Signature.** A timing row asserts that a call finishes inside a wall-clock
ceiling, and the ceiling was set as a small multiple of a floor measured on the
author's machine — twice, three times, "generous". The row is green on that
machine for months. The first time it runs on a host whose speed is not the
author's — a shared CI runner, a laptop under a review fan-out — it reds on a
row that measures the runner, not the tree, and the reader spends a run
bisecting a regression that is not there. The next timing row is written the
same way, because the rule lived in a comment beside one constant and nowhere
a new row had to pass through.

**Mechanism.** Wall time on a shared 2-core runner is not wall time on the box.
Measured 2026-09-23/24 across two CI runs on this repository, the runners read
about **1.65x** the self-host box on ordinary rows and **over 3x** on one: a
walker consumer at 605 ms here crossed a line set at twice that floor there,
and a PowerShell extractor row at 335 ms here crossed a 1 s line the box had
never approached. Four such ceilings redded on the first day CI ran again and
a fifth on the release tree's closing witness — none a regression, each fixed
at its site by the rule the file already stated for its regex rows (a ceiling
ten times the recorded floor, the alarm as the runaway detector, a scaling arm
as the shape detector) — and the rule was applied by hand five times and
pinned nowhere. The contract that finally answered it
(`tests/test_proof_tier.py::test_every_wall_clock_ceiling_is_ten_times_a_dated_floor`,
2026-09-24) read the three serial timing files by AST and found the class the
hand sweeps had missed: 65 bound sites on the unfixed tree, twenty of them
literals; nine chain-driving rows sharing a line at three to eight times their
floors behind the regex rows it was sized for; a must-trip control whose own
stand-in sat at 3.5x the line it was timed against; and a design budget
asserted directly at 6.6x its floor on the reading that the probes were
"single-digit milliseconds" — they read 7.6 ms. The review of that contract
found the shape one level down: a population keyed on a variable-name
vocabulary (`elapsed*`) rather than the timing idiom, and derived ceilings
that would follow a floor re-measured on a faster host *downward* with the
contract green — the exact failure the rule exists to end, re-opened by its
own re-pin path.

**Detection.** Any `elapsed < N` or `setitimer(..., N)` where `N` is a
literal; a named ceiling with no recorded floor beside it; a constant shared
by rows whose floors differ by an order of magnitude — a shared line is only
as safe as its slowest row. A ceiling under ten times its floor on the
author's box is a red waiting for a slower host, and a control whose stand-in
cost scales with the host is the same shape one level down.

**Contract.** The design budget stays documented by name; the asserted
ceiling is a named constant no less than ten times a named, dated floor (the
slowest row's timed window, the minimum of three serial passes, with the load
it was read at); the alarm catches a runaway and a scaling arm catches shape;
and the rule is derived from the files by a contract, never restated per row —
a literal bound, a ceiling no pairing lists, a pair no row asserts, a ceiling
under the multiple, or a floor without a date, reds. A must-trip witness whose
pass is the alarm opts out on its own line with its reason.

**Related.** §13.21 (a guard validated only at the population's current size),
§13.38 (a hand-kept set inside a guard), §3.12 (a budget test whose population
cannot express the failure), §2.9 (timing-based concurrency test), and the
sharp edge *The measuring instrument is a claim too* (check the load average
before trusting a duration; the probe that reads a floor is code you have
never tested).

## 14. Adopter-experience and OSS-boundary failure modes

The catalog surfaces these as a distinct family because they only
become visible when a project crosses the self-host → adopter
boundary. The first four rounds of the v0.8 review chain
missed them; a later sweep
caught them because the angles were *adopter first-impression*,
*public-facing claim accuracy*, and *catalog self-consistency*.

Cross-link: §1.4 (canon-vs-claim) is the upstream cause — public
claims drift from artifact reality when no external witness binds
them. §1.6 (habit-formation against friction) is the upstream cause
for §14.4 — the right governance ergonomics for self-host operators
turn into governance hostility for adopters when the self-host
defaults ship as adopter defaults.

### 14.1 Fresh-repo onboarding cliff

**Definition.** A self-host residue contaminates adopter first
impression. The adopter runs `init`, then a smoke check, and gets
a result that is technically correct (the harness installed
correctly) but presents as a failure (counts mismatch, paths
missing, prompts asking the wrong question). Trust erodes inside
60 seconds.

**When this fires.** When the rendered output for the adopter
references something the adopter doesn't have yet — self-host
inventory counts, self-host paths, self-host directory structure.

**Concrete repo example.** A pre-fix `_build_claude_md`
(`espalier/cli.py`) rendered only the hook
table; no command/agent/skill tables. The adopter's first `/smoke`
ran the count check in `.claude/commands/smoke.md` (the "CLAUDE.md
command count matches files" step) against the
just-deployed CLAUDE.md, found 0 backtick-prefixed command rows,
and reported `CLAUDE.md: 0, Files: 10 [FAIL]`. The hooks worked
correctly; the experience read as broken.

**Mitigation.** Asset-SoT renderers must produce output that
references only what the adopter's filesystem actually contains at
the moment of render. When the renderer reads a different surface
than the verification check, surfaces drift. Bind both to the same
SoT (here: `managed_inventory.get_managed_public_files`). The
fix is the live instance; the binding contract is the
generalizable pattern.

### 14.2 Denial-reason UX opacity

**Definition.** A blocked tool call surfaces a "denied" result but
the message lacks the actionable shape: what was denied, why, what
the operator can do next. The hook is correct in policy; the
hook's output is wrong in UX.

**When this fires.** When the denial-reason emitter is built
inside-out from the policy logic ("which rule fired?") instead of
outside-in from the operator's question ("what do I do next?").

**Concrete repo example.** `tools/cc/hooks/_denial_reasons.py`
exists as a registry of pre-canned reason strings. Its companion
`tests/test_denial_reason_actionability.py` walks every
operator-facing entry (the `_OPERATOR_FACING_TEMPLATES` registry)
for the four required UX elements (what was attempted, what rule
fired, what the operator can do, and what env-var/flag or concrete
next step clears the block) and forbids a raw-regex `{pattern}`
field from leaking into the reader-facing text. A review surfaced
this as a watch item; the fix built the walk and brought the single
worst offender — the PowerShell dangerous-command fallback, which
had leaked its raw regex source into the operator-facing reason —
under the existing both-markers template contract.

**Mitigation.** Treat denial-reason text as a tested surface, not
debug output. Each registered reason gets an actionability
assertion. New entries fail-fast if they don't include all four
shape elements.

### 14.3 README/RESULTS credibility gap

**Definition.** Public-facing claims drift from on-disk artifact
counts. The text says "tested against N classes" but the corpus
holds N±k. A first-page reader greps the repo, sees the
mismatch, and discounts every other claim in the document.

**When this fires.** When marketing-shape prose (prose that's
ranked, counted, or framed as a metric) lives in a doc surface
that's not bound to a NumericContract. Drift accumulates silently
until a public eye catches it.

**Concrete repo example.** A pre-fix README claimed "Tested
against 45 bypass classes" but `bench/corpus/` held 49 files (45
in-scope + 4 documented out-of-scope). The pre-existing
"bypass class count" NumericContract pinned the 45 number against
the regex `Tested against (\d+) bypass classes` — but the prose
didn't acknowledge the out-of-scope cases. A reader sees
mismatch; the README looks unmaintained. The fix reworded
to "45 in-scope bypass classes (plus 4 documented out-of-scope)"
and updated the regex to accept either form.

**Mitigation.** Every counted claim binds to a NumericContract.
For claims that include both in-scope and out-of-scope, the prose
must enumerate both — counting "everything in the corpus" without
acknowledging out-of-scope sub-folders is the failure shape.
Sister-link: §1.4 canon-vs-claim is the parent mode.

### 14.4 Trust-perimeter at TP-pack boundary

**Definition.** A contributed task pack runs end-to-end with
`/implement-pack`; the harness has no audit gate on what the pack
mutates *during* execution. A pack could include a step that
patches `.claude/settings.json`, lowers a `permissions:` block,
or adds a denylist exemption — and the harness wouldn't notice
until post-pack `audit .` or the next `kill-switch` scan.

**When this fires.** Forward-looking. No live instance in the
current corpus; the pack-artifact review gate in
`/implement-pack` inspects the pack's *prose* but not its
*runtime effect*.

**Concrete repo example (counterfactual).** A pack drafts a
sub-task "tighten settings.json by removing unused deny rules";
the implementation step actually removes a load-bearing rule. The
pack-artifact review sees a plausible motivation; the actual mutation lands
during step execution; `audit .` only fires post-pack.

**Mitigation (post-OSS design candidate).** Mid-execution
kill-switch detection: every settings.json mutation during a
`/implement-pack` run goes through a pre-write gate that re-runs
the `kill-switch` scan before the write commits. Bypassable only
via explicit `--accept-kill-switch-change "<reason>"`. Not yet
implemented; the category is documented here so the angle is
remembered for the next adversarial round.

---

## 15. Recall-engine and context-injection failure modes

*The failure-mode classes specific to the context-reinjection + exemplar engine
(`tools/cc/hooks/_reinject.py`, `_recall.py`, the EXEMPLAR_MAP). Salvaged from
the retired `blueprint.md` §6 (Espalier source repo) — the WHY/antidote
reasoning that the operational
guards (`tests/test_exemplar_parity.py`, `REINJECT_PER_TURN_CAP`) enforce but do
not explain.*

### 15.1 Over-steering / homogenization

An injected exemplar is a **strong attractor** — surface it indiscriminately and
every artifact converges on it. The real antidote is the §3.2 lift condition:
**inject only a shape a parity test would go red on** (a single canonical
byte-source), enforced by `test_exemplar_parity.py`. *Do not lean this guardrail
on a different road:* the meta-cognitive speed-bump fires at consequential
chokepoints (force-push, gate-weaken), **none of which is the generative creation
surface** where homogenization happens — the parity test is the guard, the
speed-bump is a different job.

### 15.2 Stale exemplars

An exemplar must be a **fire-time read of the pinned slice plus a drift-guard
test** — never an inlined frozen copy. The drift-guard must catch **line-range
drift** (the pinned slice shifts when the exemplar file is edited), not only
content-hash drift.

### 15.3 Banner-blindness

Rarity rails + the two per-session caps exist because a **storm of injections
trains reflexive dismissal**. For the speed-bump specifically, a deny-storm trains
reflexive re-issue-without-reading — the cardinal failure the friction budget
guards against (and the thing a planned false-fire counter would
measure).

### 15.4 Per-turn aggregate load

All caps are **per-session**; nothing counts a *turn*. Multiple injectors
(`task_router` + a generative front-load + a next-turn message + a speed-bump) can
co-fire in one turn and **dilute each other** — reproducing the exact "instructions
dilute under load" pathology the engine cites against `CLAUDE.md`. Mitigation: a
per-turn aggregate ceiling (shipped as `REINJECT_PER_TURN_CAP`), with
safety-critical defensive injections + speed-bump denies exempt.

*(The deepest related risk — the **reliability trap**, where a comprehensive
harness invites both parties to check out — is a partnership/mindset risk
rather than a mechanical failure mode, so it sits outside this catalog.)*

---

## 16. Multi-agent / concurrent shared-tree failure modes

### 16.1 Spawned agent mutates the shared worktree + index

**Definition.** A sub-agent (Agent/Task tool) granted `Bash(git *)` — or
any Write/Edit — operates on the SAME working tree and git index as the
main session, not a copy, unless launched with `isolation: worktree`. Its
git side-effects (stash, reset, checkout, branch switch) mutate the
operator's live staged state.

**When this fires.** Any spawn of a mutate-capable agent without worktree
isolation; the damage is invisible until the operator re-checks `git
status` / re-runs a gate.

**Concrete repo example.** On 2026-06-23 a spawned `failure-mode-reviewer`
ran `git stash` / `git stash pop` to A/B-isolate a test failure. The pop
restored file contents but left the main session's staged deletions
un-staged; `fuse` builds its file set from `git ls-files` (the index), so
the reappeared files flipped 25 tests green->red. The main session's
verified green suite was true when run and false minutes later — caught
only by re-running the suite after the agent returned.

**Mitigation.** (1) Spawn mutate-capable / concurrent agents with
`isolation: worktree`. (2) Prefer read-only agents (Explore; Bash scoped
to non-mutating verbs like status/diff/log/show) for review/audit. (3)
After a git-capable agent returns, re-verify `git status` + `git diff
--cached` and re-run the relevant gate before trusting a pre-agent green.
Dual of "agent output is a claim to verify": output is a claim; a
side-effect on shared state is real and can silently invalidate verified
state.

---

### 16.2 Per-repo session state with no session identity — a second instance silently takes ownership

**Definition.** Harness state that is logically *per-session* is stored at a
single fixed per-repo path with no session key. A second Claude Code instance on
the same tree then writes that path, and the first instance keeps operating —
against the second one's state. Nothing errors, because both writes are valid.

**When this fires.** Any moment a second instance reaches `SessionStart` on a
tree where one is already live. Only sources `startup` and `clear` advance state
(`resume`/`compact` load read-only), so this is *opening another window* or
running `/clear` — not resuming.

**Why it is worse than last-writer-wins.** The abandoned state can look
*complete*. The blueprint's Stop-gate auto-finalize runs at every turn end, so an
orphaned node usually already carries continuation fragments from an earlier
turn — generated before the session's real reasoning existed. It reads as a
finalized node with content. A "does it have fragments?" check therefore
under-reports the loss by an order of magnitude; the honest probe is *"is every
entry explicitly marked carry-forward actually present in that node's
fragments?"*

**Concrete repo example.** 2026-08-11: mid-`/handoff`, a parallel instance's
`SessionStart` shelled `cognitive_blueprint start`, which minted a node and
repointed `cc/blueprints/latest.json`. The live session's next `record` wrote
into the *other* instance's node; `finalize` then finalized that node, leaving
five entries — three of them explicitly pinned `--carry-forward` — in a node that
was never re-finalized. Measured across the full 201-node chain: **295 pinned
entries ever recorded, 28 nodes where a pin never reached its fragments, 46 pins
lost (15.6%).** Every one was something a past session had explicitly marked
*carry this forward*. Three members of the class were attested the same day:
`cc/blueprints/latest.json`; `cc/_working_summary.md` (last-writer-wins under
parallel sessions); and the resume index's transcript picker, which selects by
newest mtime **across the machine** rather than by the running session, so it
named a different instance's transcript and the handoff leg was filed under the
wrong stem.

**Mitigation.** (1) Key session-scoped state by session identity, not by a fixed
path — `CLAUDE_CODE_SESSION_ID` is available to tool subprocesses and hook
payloads carry `session_id`, so the key exists on both sides. Verify the two
agree before relying on it: a child-session context can expose a different id
than the parent, which would split one instance across two keys. (2) Until then,
**after finalizing, verify the state you wrote is the state the next session will
read** — the write succeeding is not evidence it landed where you think. (3) A
repair pass that re-finalizes any ancestor holding a pinned entry absent from its
own fragments is idempotent and recovers historical loss. (4) Separate git
worktrees do not collide; one tree with two windows does.

**Generalisation.** Any fixed-path file the harness treats as "the current X"
is a shared mutable singleton. Ask of each one: *if a second instance started
right now, which session would own this, and would the other find out?* If the
answer is "silently, no", the path needs a session key or a staleness check.

---

### 16.3 An empty link terminates a lineage — a chain reader that does not walk past a barren node

**Definition.** §16.2 is the *write* side of the shared singleton: two instances
race for ownership. This is the **read** side, and it needs no race at all. A
chain reader that resolves "the current node" and reads its payload — rather than
walking ancestors until it finds one — treats an **empty** node as a terminus
instead of a pass-through. One barren link severs everything behind it.

**When this fires.** Whenever a fresh session *advances* the chain by design and
then reads it. Two sessions started minutes apart produce two empty nodes; the
last node holding real content is then two hops back and unreachable, with no
error, no warning, and a plausible-looking header naming a real ancestor.

**Concrete repo example.** An operator opened a second Claude Code window on this
repo intending to park the first. `SessionStart` advances the blueprint chain on
every `startup`, so both windows minted empty nodes 21 seconds apart. The reader
resolves the newest node and reads `continuation_fragments` and
`reasoning_entries` off *that node only* — no ancestor walk — so the second
session inherited a depth counter and nothing else, while an 18 KB reasoning
payload with six curated fragments sat two links back on disk, intact and unread.
Worse, the inheritance went to the *wrong* window: the first one, opened to be
kept clean, was the one that loaded the prior session's context.

⚠ **The carry-forward pin does not survive this either.** Pinning exists precisely
so a best-bit reaches the *next* session over pure recency — but pin selection also
runs against the resolved node's own entries, so a pin cannot cross an empty node.
The one feature built for this failure fails in the same direction as the bug.

**Why it hid.** The write path *already* anticipated concurrency: the code comments
name the singleton "the collision point" and use atomic replace so a reader never
sees torn content. That defence is real and it is about **byte integrity**, which
is a different property from **lineage**. Solving one reads as solving both.

**Detection.** Ask of any chain, history, or parent-linked store: *what does the
reader do when the resolved node is empty?* If it returns empty rather than
continuing to the nearest non-empty ancestor, the structure is a linked list being
read as if it were a lookup.

**Remedy.** Walk to the nearest ancestor with content (and say how far it walked),
or refuse to advance onto a node whose parent is still empty. Until then, two
mitigations, in order of strength:

- **Structural:** run the second instance from a **detached git worktree outside
  the repo directory**. The settings file and the chain directory are both
  gitignored, so a worktree receives neither — no hooks fire, no chain exists to
  advance, and pollution is impossible rather than merely requested. Keep it a
  *sibling* of the repo, never a child: a worktree under the repo root is a
  duplicate tree that filesystem scanners walk. "No hooks fire" holds for the
  session rooted in the worktree; from the primary session that sibling is a
  governed checkout since DEF-743 — the path guards resolve a target against
  the worktree containing it (see `docs/HOOKS.md`).
- **Manual:** the content is never lost, only unread. Read the ancestor's payload
  directly and re-prime from it.

**Generalisation.** "The write landed" and "the next reader will find it" are
different claims, and atomicity only ever establishes the first.

---

## 17. Shelling out to git from the wrong directory

### 17.1 A git query answers about the ENCLOSING repository

**Definition.** `git` commands resolve the repository by walking UP from the
working directory. A tool that runs `git ls-files` / `git check-ignore` /
`git status` against a directory which is not itself a repository root does not
get an error — it gets a confident answer *about some ancestor repository*, with
paths and verdicts that are meaningless for the directory asked about.

**When this fires.** Any code that accepts a path argument and shells out to git
with `cwd=` that path: archive builders, scanners, cleanliness gates, anything
that asks "what does git think about this tree". It fires hardest on a tree
extracted or copied INSIDE another repository, which is the normal shape for a
build workspace, a test fixture, or an unpacked artifact.

**Concrete repo example.** On 2026-08-10 a release-archive builder was taught to
exclude gitignored local state (untracked scratch was shipping in the ZIP,
carrying an absolute home directory). The exclusion consulted
`git ls-files --others --ignored --exclude-standard` with `cwd` set to the tree
being packaged. The release matrix extracts each candidate archive under the
repo's own gitignored `dist/`, so when the check ran *inside* the extracted copy
it answered about the PARENT repo — where every extracted file is ignored. The
archive filtered itself down to nothing and the `release_check` running inside it
failed on missing required content. The first symptom looked like a content bug,
not a cwd bug.

**Why the obvious guards miss it.** There is no non-zero exit to catch: git
succeeded. There is no exception to handle. A `returncode != 0` branch, a
`try/except OSError`, and a timeout guard all pass cleanly. The answer is
well-formed and wrong, which is the hardest shape to notice.

**The fix.** Assert repository IDENTITY before trusting a git answer, not merely
that git ran. Confirm the directory owns its own `.git` (a directory or a gitlink
file — worktrees and submodules use the latter), and treat "not a repository
root" as *no information*, distinct from *an empty answer*. Conflating those two
is the same absence-versus-emptiness error catalogued elsewhere in this file, one
level up.

**Generalisation.** Any subprocess that resolves its own context from the
filesystem — git, package managers, config loaders walking parent directories —
can answer about an ancestor rather than the target. When a tool takes a path
argument and shells out, the question is not only "did it succeed" but "did it
answer about the thing I named".

## 18. The artifact you author to prove or describe a fix is itself unverified

Every part of a change is checked by something except the parts you write to do the
checking. The code is checked by the tests; the tests are checked by the code under
test; **the fixture, the docstring and the probe are checked by nobody.** That is a
structural blind spot, not carelessness, which is why attention does not close it and
why it recurs in the same session that names it.

Three faces, all observed in one session:

### 18.1 The docstring describes the fix you intended, not the state you measured

Prose written while designing a fix slides into the tense of something already
established. Three shipped in one session, and the third contradicted a census the same
author had written an hour earlier — a comment asserting a class was closed at two sites
while four existed. The measurement was available every time; it simply was not re-read
before the sentence was written.

**Remedy:** after writing any load-bearing claim in a comment or docstring, re-run the
oracle that would falsify it *before* committing the prose. Treat it as authoring, not
review.

### 18.2 The fixture is built to a shape the real artifact does not have

A test whose fixture models the wrong shape passes while proving nothing, and — worse —
can read as a defect in the code under test. Observed four times in one session: a
fixture seeded in ascending order against a descending artifact (which let a live defect
ship for ten days); a fixture placed a new section after the sections a parser reads
when the format puts it before; a fixture omitting the very section a parser bounds on,
which made a healthy parser look broken; and a fixture whose token was a command where
the extractor only accepts a bare path.

**Remedy:** build the fixture from the real artifact's shape, and make position and value
*disagree* wherever the code could confuse them. If a mutation of the implementation
leaves the test green, the fixture — not the assertion — is usually why.

### 18.3 The probe is anchored on the content it is checking

A contract test that collected producer strings matching `startswith("[subagent")` could
not see the producer being renamed to `[agent:` — the renamed literal dropped out of the
collected set before any comparison ran, so the test stayed green on precisely the
mutation it existed to catch. The first version had the opposite fault (too broad,
sweeping in an unrelated error string), and narrowing to fix that created the blindness.

**Remedy:** key a probe **structurally** — scope to the producing function and the
assignment target, and collect whatever literal it builds — never on the literal's own
text. A probe that filters on the thing it is testing for cannot observe that thing
changing.

**The generalisation, and the cheapest form of it.** Before trusting any guard, measure
its trigger's population in the live artifact: *a gate whose trigger token occurs zero
times in the real artifact is not a weak gate, it is an absent one wearing a gate's
name.* That single measurement catches most of this section.

### 18.4 A derived population is blind in exactly one direction — it sees an addition and cannot see a removal

The standing advice is to derive a test's population rather than hand-write it, and it is
good advice: a hand-kept list stales, and a derived one enrols new members for free. But
deriving the population **from the constant under test** buys that enrolment at the price
of the other direction. Adding a member is caught. **Deleting one is invisible**, because
the population shrinks in lockstep with the thing it was supposed to police — and the
suite still reports green, with a *smaller* test count that nobody reads as a failure.

Measured instance: a guard module enumerated command wrappers in a constant, and a
sibling test derived its parametrized rows from that same constant. Deleting 11 of the 22
wrappers opened 11 genuine writes into the protected zone the guard exists to defend, and
**nothing reddened** — the behavioural suites passed, the release benchmark passed, and
the derived suite passed while silently dropping parametrizations (measured across the
four relevant files: 1025 → 992). A reader checking for green got green.

_(The first write-up of this section said 10 of 21. Re-deriving the roster from the
loaded module rather than from the filed row found **22** members and **11** unpinned —
`exec` was in the constant, in nobody's list, and pinned by nothing. A count quoted from
a finding is itself a claim.)_

**Remedy — and note the obvious fix has the same blindness.** Regenerating the population
from the constant so a new member self-enrols does nothing for removal; it is the defect
with better ergonomics.

**This is not an argument against deriving.** The discriminator is not how messy the
derivation is — it is which side of the assertion the derivation lands on:

> Derive the population and a narrowing is silent. Derive the expectation and a narrowing
> is loud.

So the fix is not *stop deriving* — it is *move the derivation to the other side of the
assertion*. Hand-write the population, derive the **actual**, and assert the two are equal.
Concretely, as landed on the attested instance:

- a **hand-written literal roster**, and per-member correctness rows parametrized **from
  that roster** — never from the subject, or a member's row is deleted along with the
  member;
- a **set-equality** assertion between roster and live constant. Prefer this to the
  `assert len(POPULATION) >= N` floor an earlier draft of this section recommended: a
  `>=` floor is satisfied by any deletion that stays above it. Live example, re-measured:
  `tests/test_sister_site_probe_ceilings.py` floors `_hook_utils.py`'s public surface at
  `EXPECTED_HOOK_UTILS_PUBLIC_COUNT = 11` against **24** live exports — **13 of slack** —
  and the site is genuinely unpinned, because its only other consumer parametrizes over
  `_hook_utils_public_names()` *derived from the live module*, so deleting an export
  deletes its own shadow row. Both halves of this section in one site;

  _(This bullet previously cited `len(_PARITY_CONCEPTS) >= 2` "over a nine-member set"
  that "cannot see a deletion of six". Re-measured: that constant holds **2** keys against
  a floor of **2** — **zero** slack — and the site is REMEDIED, not vacuous: forty lines
  up, `unclaimed_bash`/`unclaimed_ps` assert every live guard record is claimed by a
  concept or exempted, so deleting a concept reds by name. The example was wrong in its
  size **and** in its classification, and it survived because a shipped catalog entry is
  read as settled. This section's own warning — a count quoted from a finding is a claim —
  applied to the section, which is the third time it has had to say so.)_

**⚠ And the examples inside a catalog entry are claims with the same status as the entry.**
The retraction above stood in a shipped document for two sessions and was repeated into a
tracker twice before anyone measured it. It survived for a structural reason worth naming: an
illustrative example reads as *decoration* rather than as an assertion, so the scrutiny that
lands on a rule does not land on the case cited to support it — while a reader who checks the
example and finds it false discounts the rule it was there to justify. Re-derive an entry's
examples on the same schedule as its claims, and when one turns out to be wrong, record the
correction in place rather than swapping the example silently: the fact that it was wrong is
usually more instructive than the replacement.

- a **literal count** beside the roster, as the tripwire on the *wrong fix* — it is what
  reds when someone regenerates the roster from the subject and makes the equality
  tautological. Measured counterfactual: with that row absent, regenerating the roster
  **and** deleting a wrapper runs fully green (227 passed) with a real hole open;
- an **AST check** that the roster and the count are still literals. The three bullets
  above are undone by one plausible edit, and a comment saying "keep this literal" is
  advice a future editor may silently decline.

**The tell, generalised.** Ask of any derived population: *what happens if the source
shrinks?* If the honest answer is "the test also shrinks, and passes," the derivation is
load-bearing in one direction only. Deriving the **expectation** is nearly always right;
deriving the **population** from the subject is what carries this hazard.

**⚠ The tell is not always available, and the worst members are the ones without it.**
The shrinking row count is how the attested instance was caught. Two shapes in this repo
have the identical blindness and do not move the count at all:

- **A `for` loop over an imported container, asserting inside the body.** There is no
  parametrize, so there are no rows to lose — the suite reports the same number before and
  after. A census found **49** such sites; they are filed undriven, as candidates rather
  than defects, because the discriminator above has to be applied per site.
- **A constant nothing derives from at all.** `_CMD_POS_EXEC_QUOTE` enumerated six
  shell-exec openers and three (`zsh -c`, `ksh -c`, `dash -c`) were covered by no row
  anywhere. Dropping them opened three genuine protected-zone writes with the declared
  oracle **bit-identically green** — 232 passed before and after. Found only by an
  adversarial pass over the *finished fix* for the sibling constant eleven lines away.

**The addition direction can be blind too — including inside the fix.** The remedy above
was landed with a roster extractor that scraped `[a-z]+` runs out of the constant. Any
member carrying a digit or hyphen decomposes, and if its leading run collides with a name
already pinned, the addition is invisible: adding `proxychains4` beside the existing
`proxychains` left the extractor returning 22 members, the roster row green, and a live
functional wrapper covered by nothing — the same defect, in the direction the fix's own
docstring claimed to cover. Parse the alternation structurally and **red on a shape the
extractor cannot read**, rather than returning whatever it managed to find.

**Do not read a closed site as a closed class.** On the attested instance the member count
rose at every level of scrutiny applied: **1** filed, **2** after asking the class question
one constant over, **3** after an adversarial pass over the finished fix, **6** after a
repo-wide fan-out. Nothing in that sequence indicates the last number is the true one.

**A documented impossibility is a claim, and it forecloses its own fix more durably than
a missing test does.** The remedy above shipped, in its first form, with a comment
explaining that one row *could not* be pinned — that the member was redundant in the
subject, so no per-row check could ever cover it. It was measured, it was written in good
faith, and it was **wrong**: a different shape put the verb at that member's position
directly, and the row became load-bearing. The asymmetry is what matters. A missing test
is found by the next person who looks; a comment saying "we looked, and it cannot be done"
is *why the next person does not look*. So:

- Before writing that a property cannot be tested, try to write the test that would refute
  you, and say which shapes you tried. "No shape I tried does X" is honest and invites a
  retry; "no shape can do X" is a claim about all shapes, which is almost never what was
  measured.
- Where the note survives, prefer a **mechanical check over the prose**. The rule here —
  *each row's payload must sit at the position that row is named for* — became an
  assertion over the shape table, so the inert row cannot be written again. A sentence
  asking future editors to remember something is the weakest form of every rule in this
  catalog.

**⚠ A NAME IS NOT A POPULATION: check what your identity check actually CONTAINS one
hop out.** The remedy above says to compare a hand-written expectation against a derived
actual. Whatever you derive the actual *from* becomes the real subject of the check, and an
identity built on the wrong fields is blind in exactly the way the population was.

Measured instance, found by an adversarial pass over the finished remedy and worth recording
because it landed on the site the class is named after. A census of derived populations pinned
each file with a sha256 over `(shape, iterated-expression, binding-route)`. For a **one-hop
alias** the iterated expression is just the alias's NAME:

```python
_TEMPLATE_NAMES = list(mod._OPERATOR_FACING_TEMPLATES)   # the alias
@pytest.mark.parametrize("name", _TEMPLATE_NAMES)        # what the census sees
```

Narrowing the alias to `list(...)[:1]` took five parametrized classes from nine members to one
— and the digest was **bit-identical**, the health check returned **0**, and the roster entry
naming that very site still passed, because the *name* never moved. The right-hand side, which
is where the narrowing lives, was in no hashed field at all.

The fix was to put the indirection's source text into the binding-route field, which was
already hashed — no new field, no new artefact. The generalisation is the diagnostic:

- For every field your identity/expectation is built from, ask **what a reader would have to
  change to narrow the population without changing that field.** If the answer exists, the
  field set is incomplete.
- Indirection is where this hides: an alias, an accessor function, a helper that loops
  internally, a container passed as a parameter. Each hop moves the narrowable text out of the
  expression you can see and into one you did not think to hash.
- Assert the mechanism, not just the outcome: *every* indirect binding must carry the text
  behind it. That row fails the moment a new indirection shape is added and forgotten, which a
  digest-equality row cannot do.

**Most sites with this shape are not defects, and the ratio matters.** A census of one
repo returned 206 candidate sites; of the 71 adjudicated, **70 were correct** — and most
were correct because *an independent pin already existed, usually one file over*:
hand-written exact sets, doc-prose parity, filesystem-derived reverse ratchets. A
shape-keyed census cannot see the pin next door, so it over-reports by construction.
Two consequences, both cheap:

- **Never read a census row as a defect.** It is a candidate, and the discriminator above
  is semantic. A probe that printed a verdict on a shape match would manufacture exactly
  the false confidence this section is about.
- **Before grading a site DEFECT, grep for a pin on the same constant elsewhere.** That
  single step moved multiple verdicts in the attested run — including one site whose
  "silent" result came from a *too narrow* consumer sweep, not from a missing pin. Drive
  the full suite, not a hand-assembled list of plausible consumers: such a list is itself
  a derived population, and one under-counted the real pin set by 25%.

**And the shape is really two mechanisms.** They share the symptom — a check that stops
checking, with nothing red — but not the cause, and a fix aimed at one does nothing for
the other:

| Mechanism | What happens | Tell |
|---|---|---|
| **Population shrinks with the subject** | the test's rows are generated from the constant, so deleting a member deletes its own row | the row count drops (and on the loop/comprehension forms, not even that) |
| **Fail-open registry lookup** | `handler = REGISTRY.get(key)` then `if handler is None: return` — nothing shrinks, a lookup simply misses and the check disables itself | nothing at all; the count is unchanged |

The second is easy to miss precisely because it has no population to inspect. Search for
it by grepping the `.get(` sites of any dispatch registry and asking what the `None`
branch does: if the answer is "return", the registry's completeness is load-bearing and
almost certainly unpinned. Two live instances were found this way, one of which silently
retired the naked-claim gate for **18 of 26** claims across three documents.

_(That figure read "8 of 26" until it was re-derived by calling each walker over its live
surface: 18 / 5 / 3. The original was carried from a finding rather than measured, and it
understated the blast radius by more than a factor of two. A count quoted from a finding is
a claim — the second time this one section has had to say so.)_

**The prior question, which the discriminator above cannot answer: is this test worth
having at all?** The discriminator tells you whether a derived population is blind. It
does not tell you whether the property is one anybody wants. Asked in the wrong order, the
result is a correctly-built pin around a requirement that should not exist. On the attested
run, putting this question first left the work count unchanged — five of seven sites still
warranted a pin — while changing **six of the seven fixes**:

- **The rule can be wrong, not just the detector.** A release gate keyed on `### Heading`
  over a changelog that has never used h3 looks like a regex bug; repointing the regex at
  bullets would have reddened the default branch on every push, because the *specification*
  was wrong. Pinning such a population hardens the error.
- **The property may have no consumer.** If nothing in the world breaks when it fails,
  delete or downgrade — do not pin. Name the user and what they were doing; "a maintainer
  might be confused" is not a user.
- **The harm as filed may be false.** One site's recorded harm was that an adopter is told
  a surface audit passes. Driven on a real adopter tree, the audit still exits non-zero via
  a second arm *in the same command's output*. The fix changed shape entirely once that was
  measured, from "add a protection floor" to "replace a tautology".

**A third axis: the walker that still runs but no longer engages.** Both mechanisms in the
table assume the population or the lookup moves. There is a quieter one — a live, non-stub
discoverer whose *trigger* stops occurring. A walker keying on the literal substring
`Core Rules` yields nothing once a heading is retitled `Core rules`; one character, an
ordinary prose tidy, and the yield fell from 18 claims to 5 with the full suite
**bit-identical**. Afterwards an unannotated claim in that section is accepted in silence.
This is indistinguishable in effect from the `return []` stub that a sibling contract
already banned — the stub was pinned, this route was not.

⚠ **A non-emptiness floor cannot see it.** The document carried *two* headings matching the
trigger, so retitling one left five claims, not zero. `assert yield > 0` stays green. The
`>=`-with-slack warning above lands here too, one level up: on the fix. What works is the
**exact per-surface yield**, asserted rather than recorded in prose — which is the shape
this catalog's own §18.1 demands, and which the first draft of that fix violated by writing
the three measured counts into a docstring and asserting none of them. Also assert that
every registered surface *exists*: a verifier that skips an absent file is a second
fail-open, and a moved document then stops being policed with nothing red.

**⚠ The instrument built for this section inherited the section — a third time, and on two
axes at once.** A census enumerating this shape has to pin its own coverage, and
`scripts/derived_population_census.py` pins it two ways, both of which are themselves §18.4 members:

- **`check_health`'s per-shape floors are `>=`, and the slack is not small.** Measured 2026-08-18
  against the live tree, yield/floor: `parametrize` 18/10, `for-assert` 52/45, `for-plain` 38/32,
  `comprehension` 94/70, `all-any` 5/3 — slack **8 / 7 / 6 / 24 / 2**. Driven by dropping exactly
  the slack and re-calling `check_health`, **every shape returns rc=0**; draining all five at once
  retires **47 of 207 rows (22.7%) with nothing red**. The one shape that appears to red does so
  only when the dropped rows happen to include one of the **6** matched by the two-entry
  hand-written `SELF_CHECK_MUST_SEE` roster — choose the other 12 and it is silent too. That roster
  is the remedy this section prescribes, and it covers **2 files**, not one shape per declared shape.
- **Its file selection is `TESTS_DIR.rglob("test_*.py")`,** so 15 non-fixture modules under `tests/`
  are never parsed — including `tests/_surface_expected.py`, where this repo's literal pins live.
  The file most often cited as the remedy is the one the instrument cannot read. Widening to
  `*.py` surfaces exactly one new member (`tests/_adopter_tree.py`, deriving from
  `get_install_ci_artifacts()`), and the residue guarantee does not cover the gap because
  `_files_with_only_scratch_bindings()` uses the same glob.

**The generalisable half:** a census's own coverage is a derived population, and a `>=` floor over
it is this section's own retracted remedy, applied to the instrument. Pin the **exact per-shape
yield**, or carry one literal roster entry per declared shape — a floor with 24 rows of headroom
answers *"did a handler go dark"* and cannot answer *"did this handler narrow"*.

**And the population was not where the remaining defects were.** All **207** census rows have now
been adjudicated for **one nit-grade defect** — 70 driven, 137 read-only — and of the 137, most
were correct because an independent pin already existed. That extends the ratio in *"Most sites
with this shape are not defects"* above by one step: once a class has been swept, the next marginal
finding is likelier to sit in the **instrument** than in another row of its output. ⚠ The 137 were
adjudicated by reading and grep, **not by mutation** — a read-only clean sweep is evidence, not
permission, and does not close the class.

### 18.5 The claim you retire is retired at one site, and the pinned one is rarely the read one

A measured claim rarely lives in one place. When it is falsified, the instinct is to correct
the site you were working in — and that site is usually the *detailed* one, deep in a member
row or a docstring, because that is where the work was. The **summary** site, higher up and
more read, keeps stating the retired claim.

Measured instance: a tracker's detail row carried "135 of 206 rows (66%) were never
adjudicated". Measurement retired it; the detail row was struck and rewritten. The same claim
sat in bold in the summary section ~720 lines above, and stayed. A reader who reads only the
summary — which is most readers, that being what a summary is for — leaves with the retired
claim, stated more confidently than the correction.

**The trap is that a partial retraction can be *greener* than no retraction.** In that
instance the summary's live-issue COUNT was contract-pinned and the correction updated it, so
the suite went green on an edit that left the surrounding paragraph false. A pinned number
beside unpinned prose reads as coverage and is not: the gate proves the digit, and the
sentence around the digit is unguarded. That is §18.3's shape — the probe anchored on the
content it is checking — applied to a document rather than to code.

- **When you retire a claim, grep the whole document for it before you call the edit done** —
  the phrasing, the number, and the framing sentence separately, because a summary paraphrases
  rather than quotes. An assertion that the retired string appears zero times is cheap and is
  the only form of this that does not rot.
- **Prefer correcting the summary first.** If effort runs out, a stale detail under a correct
  summary misleads fewer readers than the reverse.
- Related: `STANDING_PRINCIPLES` §8 — a class-fix's scope is every shipped surface. A claim is
  a class; its sites are the places it is stated.

### 18.6 The regression test exercises the shared helper while the defect lives in the wiring

A fix lands in a module that several call sites consume. The regression test
imports that module and asserts on its function directly, because that is the
cheapest place to assert. The test passes, the fix ships — and reverting the fix
leaves the test **green**, because the defect was never in the helper's return
value. It was in which caller passes what, in which of two records the dispatch
consults, or in whether the call site is reached at all.

This is not the same as a weak assertion. The assertion can be exact and the
test still prove nothing, because it is pointed one layer below the defect.

Attested three times in one project, each time in the same shape as the bug it
covered:

1. A parameter-passing defect whose test drove the shared invoker directly, so
   reverting BOTH call sites restored the original bug with every test green: it
   pinned the parameter and never the wiring.
2. A guard whose accepted-gap twin asserted one spelling was an accepted gap,
   while that spelling delivered byte-identical reach to the form denied as a
   real bypass.
3. Two literal deny records that only fire through the dispatch. The regression
   test called the *classifier* those records duplicate, so un-anchoring the
   records reddened nothing at all.

**The diagnostic, and it is mechanical.** After writing the test, revert the fix
and run it. If it does not red, the test is inert — no matter how precise it
looks. Then ask *where the defect actually lives*: if the answer is "in the
relationship between two things", the test has to drive both. Reverting only the
site you were already looking at proves the test sees THAT SITE, not the defect.

**Prefer end-to-end at the dispatch boundary.** For a guard, that means driving
the real entry point with a real payload rather than calling the predicate. It is
slower and it is the only version that can see a wiring defect. Where a helper
test is genuinely wanted, keep it *in addition to* the dispatch test, never
instead of it.

**Related:** §18.4 (a derived population blind in one direction) is the
neighbouring shape where the test's *population* is wrong rather than its layer.

### 18.7 The test population is derived from the same premise as the code

You write a fix and a regression file together. Both come out of one head, in one
sitting, from one model of what the defect is. The tests pass. They would pass
whether or not the model is right — because the roster you wrote **is** the model,
written out a second time. It cannot fail where the premise is wrong, because
every row was chosen by that premise.

Attested, with the numbers that make it concrete. A change to a shell-command
guard rested on the premise *a separator inside a quoted span is inert*. Under
that premise a single-statement body is a complete test case, so every one of the
roster's exec-quote rows used a single statement. The premise was wrong — a span
handed to `eval`, to any `-c` shell, or to a heredoc fed to a shell is
**re-parsed**, so those separators are live — and 63 of 140 command shapes stopped
being denied. At that moment ALL of the following were green:

* the 80-row regression file written specifically for the change
* 8 mutations, every one reddening its intended arm
* an 84-attempt differential over a curated corpus
* the release-gating benchmark, at full marks

**Mutation testing does not close this, and that is the counter-intuitive part.**
Mutation asks *would my tests notice the code being broken as written*. It never
asks *is the code's premise true*. Both the code and the tests are downstream of
the same assumption, so a mutation that respects the assumption is caught and the
assumption itself is never on trial.

**The diagnostic.** Ask what would have to be true for your test rows to be
representative, then ask who chose them. If the answer to both is "me, from the
model I am testing", the suite is a mirror. The fix is not more rows — it is a
population you did not choose and a verdict you do not supply:

* **generate the population** combinatorially (shape × payload), so cases you
  would not have thought of appear anyway;
* **take ground truth from the system itself**, not from an expected-value table —
  for a delete guard, run the command against a throwaway victim and ask the
  filesystem whether it is gone;
* **classify differentially** against a baseline revision, so each case reports
  *changed and dangerous* / *changed and safe* rather than pass/fail.

A roster still has a job: once a shape is known, pin it. The point is that a
roster cannot **discover** the shape that the premise hid.

**Related:** §18.4 (a derived population blind in one direction), §18.6 (the test
pointed one layer below the defect), and §18.8 — the instrument that reports a
comforting answer because it is broken.

### 18.8 The probe returns a reassuring answer because it cannot report the other one

An instrument that is broken rarely announces it. It returns the *comfortable*
verdict — no findings, nothing blocked, all clear — which is indistinguishable
from a genuine null and reads as confirmation of whatever you already believed.

Four in a single session, each one flattering the conclusion already held:

1. **Read the wrong channel.** The guard denies via exit 0 plus JSON on stdout.
   The probe checked the return code, so it reported 12 correct denials as allows.
2. **Swallowed the type error.** The function takes a string; the probe passed a
   dict. The caught exception became a truthy sentinel that printed as *deny* for
   every row, including the ones that must allow.
3. **Copied a module without its siblings.** The baseline tree was extracted as
   one subdirectory, omitting a sibling the script imports. It died on import,
   wrote nothing, every row read as *allowed* — and the run reported **zero**
   problems while 63 were live.
4. **Trusted a `finally` block.** A mutation harness restored the file it
   mutated, except twice it did not; the next run reported a red baseline and the
   corruption was found only by diffing against a byte-mirror.

**The rule: an instrument must prove it can report BOTH verdicts before you trust
either.** Two assertions, run before the real population:

```python
assert probe(known_bad) is True    # it can say yes
assert probe(known_good) is False  # it can say no
```

A probe that cannot fail cannot report a null. Add to that: let exceptions
propagate rather than converting them to a value, and verify every restore by
comparing a hash rather than assuming the `finally` ran.

**Related:** §18.7 (the population that shares the code's premise) — a live
instrument over a mirrored population is still blind; the two failures compose.

### 18.9 The population's TEMPLATE cannot express the axis, so adding rows never helps

§18.7 is about a population that shares the code's premise. This one is narrower
and harder to see: the population's *shape* — the template each row is stamped
from — has no slot for the axis that breaks. Every row varies something, so the
matrix looks rich; but the axis under test is a constant of the template, and no
number of additional rows can vary it.

The tell is a gate that reports a confident zero while the defect is live, and
stays at zero after you add rows to it.

**Attested twice in one session, on the same surface.**

A differential fuzzer generated wrapper × body combinations and took its ground
truth from a real shell — a genuinely strong design. Every heredoc wrapper in it
was written with the consuming command at the start of its own statement and
nothing between the heredoc operator and the body:

```
"bash <<'EOF'\n%s\nEOF"
"cat <<'EOF' | bash\n%s\nEOF"
```

The `%s` substitution point is the *body*. A row that appends anything after the
operator — `bash <<'EOF' && ls` — is not a row you forgot to write. It is
**inexpressible in the template**. When a change mis-attributed which command
owned a heredoc body, that gate reported *288 shapes, 0 fail-open* while 23 were
live, six of them writing a kill switch into settings. Adding bodies would never
have found it; the operator line had to become a substitution point.

The same session, the same shape at a different scale: every must-allow roster in
the repo placed an inert container's opener at offset 0 of the command. A defect
in how a span *opens* — a comment opener glued to the previous token opens
nothing in that language — was therefore invisible to all of them, and shipped a
hard-tier fail-open.

**The diagnostic.** Before trusting a table-driven gate, ask what its rows hold
*constant*, not what they vary. Write out one row and mark every position that is
literal text rather than a substitution point; each of those is an axis the gate
cannot fail on. Then ask whether the property under test lives in one of them.

**The fix is not "add a row."** It is to promote the frozen position to a
generated one, and — where the axis has a canonical alphabet in the code —
derive that alphabet from the source rather than listing it, so a later widening
enrols itself. Both gates above were repaired that way: the separator alphabet
now comes from the guard's own character class, and the container opener is
prefixed from the same derived set.

**Related:** §18.7 (the population derived from the code's own premise) and
§18.4 (a derived population blind to a removal). All three are the same question
asked at different layers — *what can this population not say?* — and they
compose: a live instrument, over a mirrored population, stamped from a template
that freezes the axis, is blind three times over and green throughout.

### 18.10 The axis IS a substitution point, but its alphabet is uniform on the property under test

§18.9 is about an axis the template cannot express. This one is the level below,
and it wears the disguise of having already taken §18.9's advice: the position IS
generated, the matrix IS a cross-product, the row count IS large — and the
alphabet filling that slot happens to carry one value of the property that
breaks. Size then reads as exhaustiveness, because the count is genuinely driven
by the *other* axes being rich.

**A cross-product is only as wide as its narrowest axis.**

**Attested.** An extractor for in-place stream edits was rebuilt around a
generated population: pre-flag run × in-place spelling × script delivery × target
count, 333 rows, driven against a real interpreter. It reported full coverage —
and the class was still open, because every script in the alphabet used one
delimiter. Substitution scripts routinely use another (that is the whole point of
choosing one: to avoid escaping the other), and the segment span truncated on
exactly those characters. The alphabet also carried no uppercase in-place flag
and no verb-spelling variation, both of which really write. A hand-written roster
of 14 had been the *stated* defect the 333 rows were built to fix; the rebuild
moved the hand-writing from the sentences to the alphabet and kept the blindness.

**The diagnostic — count distinct values PER AXIS, never rows.** Write the axes
down one per line with their cardinality. An axis at 1, or an axis whose values
all share the property under test, is the gate's blind spot no matter what the
product is. `6 × 8 × 6 = 288` and `6 × 8 × 1 = 48` are both "a cross-product";
only the second announces itself.

**When §18.9's fix is unavailable, say so in the gate.** §18.9 prescribes
deriving the alphabet from the source, which works when the axis has a canonical
alphabet in the code (a character class, a registry, an enum). Some axes have
none — a stream editor's delimiter is *any* character, so there is nothing to
derive from and the alphabet is irreducibly a judgement. That is not a reason to
skip the axis; it is a reason to record the residual where the next reader meets
it, so the gate claims "derived from a declared alphabet, and the alphabet is the
thing to attack" rather than "exhaustive."

**Related:** §18.9 (the axis frozen by the template), §18.7 (the population
sharing the code's premise), §18.4 (blind to a removal). The progression is
worth reading in order — each one is the previous one's *fix* having been applied
and having moved the blindness down a layer rather than removing it.

### 18.11 The rows split cleanly, and the variable that splits them is not the one the report names

§18.9 and §18.10 are about a population too narrow to catch the defect. This one
is the opposite failure and it is more dangerous, because the population *did*
catch it. The rows reproduce, the split between passing and failing is crisp, and
the report attributes that split to an axis it merely *co-varied* with. You then
fix the named axis, the rows go green for an unrelated reason, and the real cause
survives with a passing gate on top of it.

**The shape.** A report arrives with N shapes: some refused, some allowed, and a
stated cause that explains the difference. The stated cause is a *claim*, and it
is the one part of a reproduction that nothing mechanical checks — the rows are
verifiable, the verdicts are verifiable, and the sentence joining them is prose.

**Attested.** A guard finding was filed as "the masking pass desyncs on nested
punctuation inside a double-quoted span", with nine driven shapes: six refused,
three allowed. Every refused shape contained the English connector *then*; none
of the allowed ones did. Driven as a **matrix of connector against punctuation**,
the punctuation column was flat at every setting *including no punctuation at
all* — the shell's reserved words refused everywhere and ordinary words allowed
everywhere. The cause was an unanchored alternation over reserved words, and the
masking pass could not have relieved it in principle: that pass neutralises
*characters* in a set, and a reserved word is not a character. The prescribed
repair — "make the mask hold its span" — was the right shape at the wrong layer,
and the oracle the report supplied to gate that repair would have certified it.

**Why the wrong axis is so plausible.** The author varied one thing and watched
the verdict move. That is a real observation; the error is inferring which thing
moved it. Every shape in that report placed its punctuation and its connector in
the same clause, so the two axes were perfectly confounded, and a perfectly
confounded pair reads as a single well-isolated variable.

**The diagnostic, and it costs one command.** When the rows split cleanly into
refused and allowed, **diff the two groups for anything the report does not
mention** before accepting its axis. Then vary the suspected axis and the named
axis *independently* and look at the resulting table rather than a list. A flat
column is proof the named axis carries no signal; you cannot see a flat column in
a one-dimensional list of shapes, which is the form findings arrive in.

**The control column is the durable fix to the instrument.** A probe whose rows
all carry the interesting value of an unstated variable can never separate the
two axes. Add values that are *ordinary* on the suspected axis — here, connectors
that are not reserved words — and keep them as a permanent column. They cost
nothing on a green run and they are the only rows that can falsify the axis.

**Corollary — a reproduction can be right and its explanation wrong, and the
verdict of the pack or ticket must record which one you verified.** "The premise
still reproduces" licenses doing the work; it does not license the stated
mechanism. Re-derive the mechanism even when the rows are green-for-red exactly
as filed, because the fix is chosen from the mechanism, never from the rows.

### 18.12 The sibling's passing row is cited as proof the fix transfers, and it passes for a reason that does not

§18.11 is about a stated cause that co-varies with the real one. This is its
cousin at the level of *evidence*: the fix is justified not by a measurement of
your own case but by pointing at a neighbour that already works. "The answer was
already in the repo" is one of the most persuasive sentences available to a
reviewer, and it is an argument about the neighbour, not about you.

**The shape.** Two consumers, A and B, are meant to satisfy the same property. A
satisfies it and has a passing row proving so. B does not. The repair is derived
by making B look like A — and A's row passes for a reason that is a property of
A's *payload*, not of the mechanism you copied. B gets the mechanism, still
fails, and the failure is surprising in proportion to how good the argument was.

**Attested.** Two guard records were meant to treat a re-parsing wrapper
(`eval`-alike) as a live command position. One composed the shared
command-position constant and had passing rows for every wrapper spelling; the
other hand-inlined a near-copy and allowed all of them. The repair — compose the
shared constant — was correct, landed, and closed four separator members. The
wrapper spellings still allowed. The reason: the scanner reads a *masked* copy of
the command in which syntax characters inside a string literal are blanked, and
the two records match on different text. The passing record's payload was a
cmdlet name and two flags, which contains **no maskable character**, so the mask
left it whole. The failing record matches an assignment, whose `=` is exactly a
maskable character — deleted from the scanned copy before the record ever ran.
Anchoring cannot reach a token the scanner never receives.

**Why it is so easy to make.** The neighbour's green is real, its mechanism is
the right mechanism, and the difference that matters is not in either record —
it is in a third component, upstream of both, interacting with a property of the
payload nobody wrote down. Nothing in the diff shows it.

**The diagnostic, and it costs one command.** Before citing a sibling's passing
row as evidence that a fix transfers, **print what the scanner actually receives
for both payloads.** Not the input, not the pattern — the intermediate the
matcher is handed. If the two intermediates differ in a way the two patterns care
about, the sibling's green is not evidence about your case and the citation must
be withdrawn.

**Corollary — a two-cause defect will present as a one-cause defect, and the
half you fix first is the half you had a name for.** Landing the named half is
not wrong; reporting the defect closed on the strength of it is. State which
causes were measured and which were inferred, and re-drive the symptom after the
fix rather than the rows that motivated it — the rows can go green while the
symptom survives, and here they did.

**Corollary — a classification category that means "restates the shared
constant" is a resting place, not a decision.** The failing record above sat in
its gate's exemption table under a category naming the very defect ("a
hand-rolled near-copy of the shared separator class") and was accepted for
months, because the gate checked that a restatement *existed* and never that it
was faithful. Any category whose definition is "does the right thing its own
way" should be read as a fix that has not been done yet, and should carry the
diff against the thing it restates.

**⚠ Addendum, 2026-08-26 — the attested case above was itself half-diagnosed, and
the correction strengthens the rule rather than weakening it.** The repair
derived from the neighbour was written, landed, and reported as leaving one leg
open, with the residue attributed to the masking pass deleting a character the
matcher needed. A real interpreter was installed on the development machine for
the first time the following day and refuted the residue in one command: the
spelling filed as the surviving hole is *inert*. The language interpolates the
variable at parse time, before the re-parsing wrapper receives the string, so
nothing is set and allowing it was correct all along. The genuinely live
spellings were the ones nobody had tried — the *literal* quote forms — and they
were allowed.

So the diagnosis was right that the neighbour's green was a property of its
payload, and wrong about which property. It is not that the payload carried no
maskable character; it is that the payload carried no *interpolatable* one. The
first is a fact about the guard, the second a fact about the language, and only
the second decides what actually runs. **When you catch yourself explaining a
neighbour's green with a property of your own tooling, check whether the runtime
has a simpler explanation** — the tooling is the thing you can read, which is
exactly why it is the first place you will look and the wrong place to stop.

**The durable form of this: a premise about a language nobody has run is not
evidence, however many artifacts restate it.** That premise survived an
adversarial refute pass, a tracker row, a changelog paragraph, five
`strict=True` expected-failures and a corpus deferral before an interpreter saw
it. None of those are checks on the premise; they are copies of it. The number of
places a claim appears is a measure of how far it travelled, never of whether it
is true.

### 18.13 The absence proof has no positive control, so "nothing found" and "nothing looked" are the same output

§18.8 is about a probe that cannot report the other answer. This is the case
where it can, and nobody checked that it ever would. A search that finds nothing
produces the identical result whether the thing is absent or the search is
broken, and only one of those is a finding. A presence proof announces its own
failure -- you were looking for something and did not get it. An absence proof
*is* the null, so a broken query is indistinguishable from a clean tree, and it
arrives wearing the costume of good news.

**The shape.** You assert something is missing -- a message is not emitted, a
mechanism does not exist, a violation is not present -- on the strength of a
query returning empty. The query is wrong: the vocabulary differs, the file is
excluded, the harness never reached the code, the fixture is malformed. The
conclusion is stated with the confidence the empty result seemed to license.

**Attested, three times in one session, in three different instruments.**
A review lane concluded that nothing warned the operator about a condition,
grepped for its vocabulary, found zero hits, and filed it -- the warning existed
under different words and the finding was refuted. A scanner defect was
"confirmed" by driving the real verb and getting all zeros; the positive control
in the same tree also returned zero, which meant the probe had never triggered
the rule and the zeros carried no information at all. A hook test built its
fixture with Python `repr` instead of `json.dumps`, producing single-quoted and
therefore invalid JSON, so the hook silently skipped the file and the warning
under test never fired -- two assertions passed over an event that never
happened.

**Why the instrument does not help.** Every one of those greens is a *correct*
report of what the instrument saw. The suite cannot distinguish an empty
population from an unreached one, which is the same reason a coverage gate over
an empty set reports green (§18.9). The failure is not in the tool; it is that
the question was asked in a form whose negative answer is unfalsifiable.

**The diagnostic, and it costs one extra command.** Before believing any empty
result, run the same query against something you KNOW is present -- in the same
file, through the same harness, in the same run. If the control also comes back
empty, the query is broken and the original result means nothing. For a driven
probe, prefer a **matched pair**: the identical input in two locations where the
mechanism should treat them differently. One finding and one silence is evidence;
two silences is a broken oracle.

**Corollary.** A gitignore-blind or scope-limited search tool makes every absence
proof written with it unsound by default, and the failure is silent. This repo
already carries that specific instance for `grep`; the general rule is that the
population a search actually covers must be established before its emptiness is
interpreted, not after.

### 18.14 The widening lands in a collector the contract never reads, and reads as coverage

**Symptom.** A coverage contract stays green through round after round of
widening its input collector. Each round is real work — new source shapes
recognised, more strings gathered — and each round's own test passes. The
contract the widening was meant to strengthen never sees any of it.

**Mechanism.** Two contracts in one file grew two collectors, and the widening
fed the one the *other* contract consumed. The regression test for each widening
asserted on the collector's output — correct, precise, and one call away from the
contract. Nothing asserted that the strengthened contract's *population* had
grown. Measured instance: six rounds of widening an operator-string collector,
rules (a) through (f), all fed a helper only the interpreter-token contract
consumed; the ASCII contract called a different collector and had been green, with
26 offending strings and 42 crash-capable characters across nine output renderers,
for its entire life. The null result — widening the rule the filed cause named and
finding the contract still green — is what relocated the root cause.

**A second shape in the same repair.** The first cut of the eventual fix covered
3 of 13 live source shapes: it anchored on the one form the bug report named and
missed the house idiom that made up twenty-plus sites. A shape class is closed
when the shape *population* has been enumerated and every member is reached — not
when the reported instance is.

**Detection / contract.** When you widen a shared helper, grep its callers and
confirm the contract you meant to strengthen is among them — then prove it by
count: the contract's population must be larger after the widening than before,
and a test can pin that. Before claiming a shape class closed, enumerate the
population of shapes in the tree (a syntax-tree census, not the bug report's
example) and reach each one. §18.6's mechanical diagnostic applies unchanged:
revert the widening and run the *contract*; if it does not red, the widening
reached something else.

**Related:** §18.6 (the test one layer below the defect) is the mirror: there
the *test* points at the helper, here the *fix* does. §18.4 (a derived population
blind in one direction). §18.13 (an absence proof with no positive control — a
green contract over an unmeasured population is the same shape).

### 18.15 A per-site classifier keyed on a token found anywhere in the enclosing function greens every site once one site is compliant

*The title names one direction; this entry now holds two. The over-credit
direction is below; "The second direction" is the under-reach twin, where the
census loses the site instead of greening it. The heading is kept as written
because code and ledger rows cite this section by number and paraphrase.*

A census walks a tree and asks, per site, "is this one guarded?" — is the
JSON deref type-checked, is the crash-guard emit recorded, is the deny's
reason text actionable. The cheap implementation of "guarded" is a token
search over the enclosing function: `any(... for n in ast.walk(fn))`. It is
right on the day it is written, because every function then holds one site.
The mutation it cannot see is the second site: a second crash-guard arm added
beside one that records, a second `json.load` deref beside a checked one, a
second `reason =` beside a marker-carrying one. The function-wide token is
found; the new site is greened by its sibling's compliance; and the contract
reads as if it checked exactly that.

**Measured in this repo.** Four instruments, one shape, found in three
successive lanes on one day (2026-09-16): the BOM census
(`tests/test_settings_reader_bom_contract.py::_readers_in`, `DEF-820` — a
decoder name anywhere in the function guarded every read in it); the
bare-emitter census (`tests/test_governance_audit_log.py::_classify_bare_emitters`,
`DEF-828` — an audit literal anywhere in the function recorded every emit in
it; driven: two handlers, one record, zero offenders); and, from that lane's
failure-mode review, the JSON dict-safety census
(`tests/test_json_dict_safe.py::_classify`, `DEF-833` — a guard
in a sibling branch, or after the deref, greens it) and the deny-marker census
(`tests/test_deny_markers.py::_collect_deny_sites`, `DEF-834` — every deny in a
function resolves its reason from one last-assignment-wins map, so a second
arm's text is never checked). `tools/cc/sister_site_probe.py` does not reach
`tests/`, so the class had no mechanical oracle until it was named here. The
last two closed on 2026-09-17, and closing them lifted the ascent into one
shared helper (below) with the three censuses on it.

**Why it stays hidden.** The instrument's own rows drive one site per
function, because that is what the tree held when the rows were written; the
synthetic with two sites and one guard is the only row that reds, and nobody
writes it until the second site exists in the tree and is missed.

**The fix shape.** Key the guard on the site's own dataflow or control-flow
path, not on the function: the read whose bytes reach the decoder (`DEF-820`:
nested, or bound and still reaching), the record on the statements that run
on the way to the emit (`DEF-828`: block-prefix ascent bounded at the handler,
leaving branches pruned, dead code never credited). Land the
two-sites-one-guard row as the must-red twin beside the single-site rows, and
pin the hand-kept helper roster the rule now leans on: a wrapper name appended
to silence a red must be shown to reach the helper it stands in for.

The ascent is one helper, `tests/_site_path.py` (`site_path(fn, site)`): the
statements before the site in execution order, the headers of the compound
statements around it (a guard written as the `if` around a deref), the site's
statement whole; the `try` body above a handler and a nested `def`'s outer
scope off it; a `finally` and the handler bound as opt-ins only the record
semantic takes. A fourth census reaches for it instead of a second copy; its
decisions are pinned once, in `tests/test_site_path.py`. Moving a guard onto
the path can move the live population: on the day the JSON census moved, one
engine site reddened that the proxy had masked, and the cause was the census's
own escape rule reading a call argument inside a `return` as the loader-return
shape. Read the site before deciding which of the rule and the site is wrong;
a pragma at the site is neither. Three holes the shared walker grew on
the day it was lifted, each a check for the next one: a closure body on the
path (a `lambda` or a nested `def` in a preceding statement) was walked as if
it ran, so a guard inside one was credited; one rule was stated for a bound
name and another for the same value spelled inline (`return helper(d)` against
`return helper(json.loads(s))`), so hoisting the parse to a local flipped the
verdict; and a docstring claimed execution order over a breadth-first walk
while a consumer's sort silently made it true. Prune called scopes, state a
rule once over a predicate both spellings reach, and pin the walk's order in
the helper's own rows so no consumer sorts.

**The second direction: the site the census stops recognising.** The shape
above over-credits — the guard is found where it does not run. The same proxy
fails the opposite way: the census keys on the *spelling at the site*, so when
the spelling moves the site leaves the population and the instrument reports a
smaller, cleaner tree. Both are §13.37 (an oracle keyed on a name or a spelling,
asked a question about behaviour); this entry is where the two meet in one
instrument family, and a fix for one direction does not touch the other. Keying
a guard on the site's own path, the remedy above, is still frame-local.

Five instruments, measured and driven 2026-09-17 while checking `DEF-835`'s
premise. Each was driven against its own live helper on a synthetic, and each
returned zero where the same defect spelled at the site returns one:

- the decode-guard census (`tests/test_contracts.py::_text_reads_under_a_handler_that_lets_the_decode_error_past`,
  `DEF-835`): `json.loads(decode_bom(p.read_bytes()))` under `except OSError:`
  is silent where `json.loads(p.read_text(encoding="utf-8"))` under the same
  handler reds. The helper's own docstring states the unenforced contract:
  "callers already catch it";
- the JSON dict-safety census (`tests/test_json_dict_safe.py::_returned_raw`):
  a parse returned bare reds, the same parse wrapped in a call
  (`return _wrap(json.loads(s))`) or bound and handed one frame on
  (`d = json.loads(s); return use(d)`) is silent. The narrowing that opened
  this was adjudicated the day before, on its own merits, for a live site;
- the structured-argv arm (`tests/test_contracts.py::_text_subprocess_calls_not_decode_guarded`):
  a tolerant `errors=` on a literal argv reds; hoist the argv to a local or a
  module constant and it is silent, on both spellings;
- the subprocess-env census (`tests/test_subprocess_env_isolation.py`), twice:
  the script name through a module constant (`DEF-839`, filed as "not the
  §18.15 shape" — it is this direction of it), and a file skip on
  `name.startswith("_")` that hides five private hook helpers holding nine
  `subprocess.run` calls;
- the write-guard scan-reader census (`tests/test_write_guard.py::_SCAN_READERS`):
  a four-name hand roster against a module where 46 functions hold a `finditer`
  loop and 22 off-roster ones also read `.group(`, with a floor (`seen >= 12`)
  counting loops rather than enrolled functions, so one enrolled function can
  satisfy it alone.

**The discriminator, and it is the useful half.** Frame-locality alone does not
make an instrument a member. A census is a member when its verdict is
*relational* (site plus context) **and** its "no context found" branch is
*safe*. Then moving the site into another frame separates it from its context
and the verdict flips green. A census whose verdict is *site-local* ("this
spelling is forbidden, full stop") is immune: extraction carries the site and
its red together — driven on the subprocess decode-guard twin, whose offender
simply moves to the helper's line. So is a census whose incompleteness costs a
false **red**: `tests/test_settings_reader_bom_contract.py` declares the identical
limit in its own docstring ("calls are not followed into other functions") and is
not a member, because a missing decoder makes it fail loud and
`test_every_bom_helper_is_a_decoder` pins that direction.

**What this costs if it is closed one instrument at a time.** On 2026-09-17 one
lane closed the over-credit direction in the JSON census and, in the same helper,
opened the under-reach direction. Closing a direction in one census is not
closing the class; `STANDING_PRINCIPLES` §18 says a class is never patched one
instance at a time, and this family has now produced three ledger ids
(`DEF-835`, `DEF-838`, `DEF-839`) for one mechanism.

**Detection / contract.** For every per-site classifier in `tests/`, drive
both mutations on a synthetic module. Over-credit: the two-sites-one-guard
shape — if the offender count is zero, the instrument is that direction.
Under-reach: move the site one frame out behind a helper, and name the value
the key reads (a literal to a local, a local to a module constant) — if the
offender count drops to zero, it is this direction. The grep that finds
over-credit candidates is `ast.walk(fn)` beside an `any(`. The grep for
under-reach candidates is a key built from a call's own `.attr`/`.id` or from
a string literal. Both have the weakness `DEF-838` records -- they hand the
next maintainer a grep, not an oracle -- and, measured 2026-09-17, neither
grows into one.

**Do not clear a union derivation. That sentence used to stand here and it was
wrong.** It read: *a set derivation that unions over a function is not that
shape and is cleared in one line.* Driven against the pre-fix source of the
three members, the union derivation turns out to be **half the defect**. The
over-credit shape does not live in one function at all: it lives in a seam
between two. `_func_dict_guarded_names(fn) -> set[str]` walks the whole
enclosing function and returns every guarded name; a separate consumer then
asks `tgt not in _func_dict_guarded_names(fn)` per site. Neither half is a
per-site classifier on its own, and the cleared half is the one that makes the
verdict function-wide.

**Three candidate oracles, three measurements, none of them an oracle.**
Recorded so the next attempt starts here rather than at the beginning
(`STANDING_PRINCIPLES` §5 -- the null result is the signal):

- the over-credit triple `DEF-838` proposes (a parameter handed to
  `ast.walk`, a second node-typed parameter never containment-checked against
  it, a boolean result): calibrated clean on the live tree -- 60 walkers, 24
  answering a verdict, 5 never containment-checking, 0 after the node-typed
  arm -- and then driven against the pre-fix source of `DEF-833`, `DEF-834`
  and `DEF-828`: **0 offenders on all three**. It describes a classifier
  nobody wrote;
- a spelling-keyed predicate for the under-reach direction: **7 candidates
  catching none of the members**; adding binding resolution took it to **92**
  -- most of the AST helpers in `tests/` -- while still catching only 2 of the
  4 function-shaped members;
- the corrected seam predicate (a membership test whose right side is a
  function-wide derivation): catches `DEF-833` and **misses the other two**,
  with 2 false positives on the post-fix tree.

**Why the syntactic family fails, which is the first finding.** The members
share a mechanism and not a syntax. Their consumers differ: `DEF-833` tests
membership against a set, `DEF-834` resolves against a last-write-wins map,
`DEF-828` searches for a literal. Their signatures differ too, and that is what
kills a signature-keyed rule: `_classify(call, stmt, fn, parents) -> str | None`
carries no annotations and returns a label, while `_collect_deny_sites()` takes
no parameters at all and reads its directory directly. A matcher keyed on any
one spelling is a roster wearing a predicate's clothes.

**The acceptance test must be split by direction, and asking one direction's
question of the other rejects sound candidates by construction.** The pre-fix
sources of `DEF-833`, `DEF-834` and `DEF-828` are all OVER-CREDIT instances,
and over-credit appears to be population-invariant: all three rows record their
live population unchanged across the fix (`DEF-833` 169 files and no offender,
`DEF-834` 35 resolved sites / 28 texts / 3 declared producers, `DEF-828` 8 bare
sites and 0 offenders, on HEAD and after). **That is an observation over the
three fixes this entry has, not a proven property of the direction** -- it is
the load-bearing claim here and the softest one, so drive it before leaning on
it. If an over-credit fix is ever found that DOES move its population, a
population-keyed candidate is back in scope and attempt 4 below was rejected
correctly after all. On the three measured, any population-keyed candidate
fails that test whatever its merits. Over-credit candidates are
judged against those three; under-reach candidates against `DEF-835`, `DEF-839`
and the argv-hoist twin. Attempt 4 below was rejected on the wrong test.

**The assumption every failed attempt shared, and the instrument it excluded.**
Each took THE CENSUS as the subject under test -- its source, its live output,
or its file inventory. None took the census's own FIXTURE CORPUS, which is
exactly where this entry's prescribed fix leaves its signature ("land the
two-sites-one-guard row as the must-red twin beside the single-site rows"). No
instrument reading the classifier's source can see a property of its fixtures.

**Two candidate families that pass the split test, both driven 2026-09-17.**

- **A fixture-corpus positive control.** Run each census's own site enumerator
  over its own fixtures and require at least one fixture holding two sites with
  a mixed verdict. Driven over the three pre-fix sources: 21 fixtures and 0
  multi-site in the JSON census, 0 fixtures at all in the deny-marker census, 3
  fixtures and 0 multi-site in the bare-emitter census -- **red on all three,
  green on all three post-fix**. Caveat carried on purpose: the predicate
  driven ("two calls to one callee in distinct statements") is itself
  spelling-keyed and greened one post-fix census on an accidental pair of
  `print` calls. The family passes; that instance is partly accidental, and the
  non-accidental form is the self-referential one above.
- **Metamorphic relations, one per direction.** Over-credit: duplicate the site
  or move the guard off its path, and the offender count must RISE.
  Under-reach: apply a semantics-preserving refactor -- hoist a literal to a
  module constant, bind an inline call to a local, move a read behind a helper
  -- and the verdict must NOT change. The second needs no oracle at all. This
  repo already ships the instrument for a different subject:
  `bench/guard_metamorphic.py` (`R1` prefix invariance, `R2` inert-span
  invariance, `R3a` explicitly "invariance, no oracle needed"). Point it at a
  census instead of at the guard.

**A floor is not the instrument; a two-sided ratchet is.** Attempt 4 tested a
floor, which sits deliberately below the live count and therefore cannot see
one site leave (176 strict reads become 175). `tests/test_test_suite_contract.py::test_raw_git_population_sites_only_shrink`
is the shape that works: a per-module pin that reds on GROWTH and on SHRINK,
with a vacuity guard above it and a remedy naming the entry to lower. Under-
reach is a shrink. Its volatility over this surface is unmeasured and is the
number that decides adoption.

**Crossed off, so nobody spends a session on them.** A differential between two
independently written censuses: refuted by this repo's own record, where a
from-scratch reimplementation reproduced the decode census's figures exactly,
including `0 live offenders`, while the under-reach hole was present in both --
"the sweep's blind spots are the net's too". Off-the-shelf mutation testing of
the census's own source: its operators do not synthesize "a second unguarded
site beside a guarded one", and run against a census whose canaries already
cover every branch it scores near-perfect, a green that proves nothing.

**One granularity correction that would otherwise cost a session.** "Every
census carries a synthetic-fed must-red twin" is GREEN on the pre-fix source:
the JSON census carried `TestGateEarnsRed` with eight must-red rows and had
`DEF-833` anyway. The twin's EXISTENCE is not the property. The twin's fixture
being multi-site is.

**Related:** §13.37 (the parent mechanism: a spelling proxy for a question
about behaviour — both directions here are instances). §13.38 (the hand-kept
set inside a guard, and its sentence for this family: "a rule right at its site
and blind at the view one call away"). §18.4 (a derived population blind in one
direction — this is the per-site twin: the population is complete and the
per-member check is blind to the second member). §18.13 (an absence proof with
no positive control — the two-sites row is the positive control).
`STANDING_PRINCIPLES` §17 (when the expensive net catches it, sweep the class).

## Notes on this catalog

- **Not exhaustive.** This is a working catalog. New failure modes
  surface regularly. The methodology in §13 is the durable
  contribution; the entries are the snapshot.

- **Coined terms.** The thirteen named modes in §1 are coinages, not
  industry-standard. When citing externally, label them as
  catalog-internal terminology, not industry authority.

- **The map is not the territory.** A bug may fit multiple
  categories; the catalog is for thinking, not classification. Use
  the entry that most clarifies the fix.

- **Living document.** Update when a new failure mode is named.
  See §13.1 for the abstraction move.
