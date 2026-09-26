# Sharp Edges

Things Espalier-Harness trips on or will trip on. Each entry prevents a specific mistake.

For categorized long-form footgun docs, see [`docs/sharp-edges/`](sharp-edges/). Index sections in this file link to sub-docs when the body would exceed ~30 lines.

## A missing `write_guard.py` wedges the whole session, and the fix is not reachable from inside it

`write_guard.py` is wired as a **PreToolUse hook on the `*` matcher**, so Claude Code runs
it before *every* tool call. When the SCRIPT is absent, Python exits **2** — and 2 is the one
code the hook protocol treats as blocking, so the tool call is aborted.

⚠ **That block is luck, not design, and the sibling failure FAILS OPEN.** Per the pinned
contract (`docs/external/cc-hook-protocol.md`): *"only exit code 2 blocks the action… Claude
Code treats exit code 1 as a non-blocking error and proceeds"*, and **any other code is
non-blocking**. A missing *interpreter* exits **127**, so the tool call **proceeds unguarded**.
The wired interpreter lives in `.claude/settings.json`, which is gitignored and per-machine —
it records whatever was detected at `init`. Delete that venv, or upgrade the interpreter out
from under it, and `write_guard` stops guarding silently while every tool call succeeds. The
absent-script case is loud only because Python happens to exit 2; nothing chose that.

The consequence is that a single missing file blocks `Bash`, `Read`, `Write`, `Edit` and
`Agent` simultaneously. There is no in-session recovery: the assistant cannot read the
directory to confirm the file is gone, cannot restore it, and cannot even disable hooks,
because every one of those actions is itself a tool call. Observed 2026-08-20: the file
vanished mid-session during a red-team round and every agent in the fan-out wedged at the
same instant, each reporting the same ENOENT.

**Recovery — the operator must run it in their own terminal**, from the repo root: restore
the file from git (a checkout of that one path), or copy it back from the vendored
byte-identical mirror under `espalier/_vendor/cc/hooks/`.

⚠ **Do not prefix the recovery with `!` in a terminal.** The `!` form is for the Claude Code
prompt. In `zsh` a leading `!` negates the pipeline's exit status, so a restore chained with
`&&` runs, has its success inverted into a failure, and silently skips everything after it.

**Two diagnostics that discriminate the cause**, because the fix differs:

- List `tools/cc/hooks/` — if ONE file is missing, something targeted it. If several managed
  files are gone, suspect a cleanup/uninstall path pointed at the repo root, which is a far
  more serious defect.
- Directory permissions are a red herring unless they differ from the rest of the repo; on a
  machine where most of the tree is already `777`, `tools/` being `777` means nothing.

**The cause of the 2026-08-20 instance was never established.** Every candidate that deletes
this file by name was checked and each writes to a temp copy (`test_self_hosting.py`'s
`tmp_path / "broken"`, `test_integrity.py`'s `tmp_path`). Recorded as unexplained rather than
pinned on a plausible-looking suspect — the honest state, and the reason this entry leads
with recovery instead of prevention.

The standing lesson is structural, and holds regardless of cause: **`write_guard` protects
the `tools/cc/` zone from the assistant's tool calls, never from code the test suite runs.**
Pytest opens, writes and unlinks files in-process, entirely outside the hook. A "protected
zone" is protected from Claude, not from Python — the toolbelt-not-a-security-boundary frame
(`docs/STANDING_PRINCIPLES.md` §2) arriving as a concrete operational consequence.

**The sibling-edit variant (observed 2026-09-08) needs no missing file.** `write_guard`
imports its helpers from the LIVE tree on every call, so an edit to one of them that lands in
two steps — rename `check` to `check_fired` in step one, add the `check` wrapper in step two —
leaves the hook raising `AttributeError` between the steps. The crash guard in `main()` fails
closed with `WRITE_GUARD_INTERNAL_ERROR`, so step two is itself denied, and so is every
`Bash`, `Write`, `Edit` and `NotebookEdit` after it. How much you can still see depends on
WHERE the broken name is dispatched. `_speedbump` runs after the read-only early return, so
`Read`, `Grep` and `Glob` kept working — enough to see the breakage, not enough to mend it.
`_hook_utils`, `_integrity` and `_denial_reasons` are used BEFORE that return (stdin, the
kill-switch scan, the secret-path check), so breaking one of those is the total wedge above,
with no in-session read access at all. The recovery is the same operator-run checkout of the
one path.

The prevention is a CONVENTION, not a mechanism: **every edit to a module a hook imports is
ONE atomic write that leaves every imported name defined** — add the new function and the
compatibility wrapper in the same edit, never rename-then-add; when a refactor genuinely needs
two writes, the first adds and the second removes. `mypy tools/cc/hooks/` does catch the
dangling name, but at proof time, minutes after the wedge has already denied the `Bash` call
that would run it. The mechanical catch — a PostToolUse advisory in `post_write_check` that
re-resolves sibling attribute references the moment a hook file is written — is filed in the
ledger, not built. Since the same session, `write_guard` fails toward allow if the speed-bump
helper itself raises (matching that helper's own fail-toward-allow contract), so a skew in
THAT module no longer wedges anything; the three named above still do.

The working method that satisfies the convention (in use since 2026-09-09; no script is
shipped for it, the shape is short enough to write per lane): edit a COPY of each hook file
in the scratchpad; run a throwaway check that `py_compile`s the copies, puts the scratch
directory on `sys.path` ahead of the live hooks directory, imports the copies and then
imports the live `write_guard` on top (so its sibling graph resolves against the copies —
the exact path a PreToolUse call takes) and calls one predicate from each; only then `cp`
each copy over its live twin in dependency order, the imported module before its importer.
The Bash call that performs the `cp` is judged by the OLD modules; the next call runs on the
NEW ones, which the check has already loaded once. A wrong verdict after landing is a normal
red; only a syntax or name error wedges, and that is what the check catches.

## Stealth contracts are five categories, not one bug

Stealth contracts = coupling between modules expressed through
channels OTHER than imports. Five sub-categories:

1. **Subprocess calls** (CLI surface = contract) — the `subprocess_contracts` scanner
2. **Cross-module file writes** (schema = contract) — the `filesystem_contracts` scanner
3. **Env vars** (variable name = contract) — the §C env catalog
4. **Magic `parents[N]`** (depth = contract) — the `magic_depth` scanner
5. **State-file shapes** — the §C flag-file test

Architecture-analysis tools that walk imports find zero violations
because no imports exist. The walls hold; the doors don't show on
the floor plan.

Detection: `espalier scan .` runs all three scanners unconditionally
and emits `reports/scan_subprocess_contracts.json` /
`scan_filesystem_contracts.json` / `scan_magic_depth.json`. Each
scanner has INLINED registry (per TestScannerSelfContainment at
`tests/test_scanners.py::TestScannerSelfContainment` — scanners may not import from the
harness package) and an earn-the-gate fixture proving detection
capability before trust.

The subprocess scanner additionally has a parity test
(`test_subprocess_contracts_parity_with_pinned_tests`) — every
`SUBPROCESS_CONTRACTS` value must point at a real test function. Without
it the registry is prose-only and silently drifts.

Pragmas are reason-floored (`>=12` chars) and capped per scanner
(`MAX_PRAGMA_COUNT = 5` for subprocess/theater; 3 for magic-depth).
Raising the cap is a deliberate operator act. Anchor regex `^#` —
the pragma is recognized only on true source comments, not
f-strings or docstrings that quote the pragma syntax.

## Convergence theater is a class, not a bug

Convergence theater = any assertion where both sides ultimately
resolve to the same source. The test passes by construction.

Known shapes (the scanner detects via `==`-only equality):
- `assert X == X` (literal-pair, THEATER)
- `assert f(args) == f(args)` (same-call, THEATER — subsumes same-glob)
- `assert a.b.c == a.b.c` (same-attribute, THEATER)
- `self.assertEqual(X, X)` (assertEqual-self, THEATER)
- `assert len(producer) == EXPECTED_DERIVED` (derived-constant, SUSPECT)
- `assert X == pytest.approx(X)`, either operand order (approx-self, SUSPECT)
- `self.assertEqual(f(args), f(args))` (assertEqual-same-call, SUSPECT)

`>=` / `<=` / `!=` / `in` are NOT flagged — they represent floor /
ceiling / inequality contracts that are legitimately asymmetric.
The `assert len(agents) >= EXPECTED_AGENT_COUNT_MIN` floor-contract
pattern is preserved.

The scanner cross-references `tests/_surface_expected.py` to learn
which `EXPECTED_*` constants are `# class: literal` (hand-pinned
witnesses, valid) vs `# class: derived` (computed from producer,
theater). Literal constants are skipped from derived-constant
SUSPECT findings.

Detection: `espalier scan .` runs convergence_theater as the sixth
scanner; results land at `reports/scan_convergence_theater.json`.
Scanner is stdlib-only with INLINED registry (no cross-module
imports — required by `TestScannerSelfContainment` at
`tests/test_scanners.py::TestScannerSelfContainment`).

Exemption: `# theater: ok <reason ≥12 chars>` pragma above the
assertion (must be a real comment line, not inside a string literal —
both `_has_pragma_above` and `count_pragmas` normalize via the shared
`_pragma_in_line` helper (strip → match the `^#`-anchored pragma), so an
indented pragma is honored as an exemption AND counted toward the cap
consistently; see FAILURE_MODES §10.9), OR file
added to `EXEMPT_FILES` module constant
with inline rationale, OR file under `EXEMPT_PREFIXES` (default:
`tests/fixtures/`).

Pragma count is capped (`MAX_PRAGMA_COUNT=5`); EXEMPT_FILES is
capped (`MAX_EXEMPT_FILES=3`). Raising either cap is a deliberate
operator act that signals growing technical debt.

Earn-the-gate validation: `tests/fixtures/test_convergence_theater_positives.py`
contains at least one known-positive per shape (approx-self carries both
operand orders; do not "dedupe" it); the test
`test_earn_the_gate_detects_every_fixture_shape` asserts the scanner
finds them all. Without this, a scanner regression that silently
breaks detection passes CI.

## Public-facing claims drift when no external witness binds them

**What it is:** Internally consistent docs are not the same as accurate docs.
A README that quotes a stale count stays consistent with itself even when
`release_check.py` has fewer. The bug is the gap between layers — internal
layers agree with themselves; nothing reconciles them with each other.

**How you hit it:** v0.6.0 audit found 7+ instances of this shape:
- README check count was stale (claimed 22, actual was 20)
- QUICKSTART clone URL 404'd while pyproject's URL worked
- README doctor demo showed a `summary` key the live binary doesn't emit
- init's "Agents: N deployed" printed a different number than ls of the directory
- Schema declared 21 fields; runtime emitted 29
- External pin was incomplete: PostCompact and ConfigChange were missing from the documented events

**How to avoid it:** Bind every quantitative or named public claim to an
external witness. The witness can be:
- **Filesystem** — count files on disk, don't count an internal list
- **Regex audit** — `NumericContract` framework in `tests/test_documented_claims.py`
- **Parity test** — import both sides and compare (schema↔runtime)
- **Live subprocess** — run the binary, parse output, compare to README
- **Refreshed external pin** — canonical upstream docs in `docs/external/`

The general rule: **internal consistency is not enough.** Every public claim
needs a binding to something outside the layer making the claim. The
`NumericContract` framework (`tests/test_documented_claims.py`) is the
canonical pattern for quantitative claims; for shape/structural claims,
use a parity test that imports both sides.

**Receipt:** `tests/test_documented_claims.py` classes `TestNoStaleNumericContracts`,
`TestGitHubURLConsistency`, `TestReadmeDoctorExampleMatchesLiveOutput`,
`TestFingerprintMatchesSchema`, `TestHookProtocolStaleForms`,
`TestSpecificStaleClaims`. Audit infra added in an earlier release.

## Skill Triggering Reliability

**What it is:** Skills (under `.claude/skills/<name>/SKILL.md`) load only their
YAML frontmatter at session startup; the body loads when Claude detects a
relevant trigger or when the skill is invoked directly. Trigger detection is
a model-side judgment call against the `description` field.

**How you hit it:** Skill trigger reliability varies in practice; in some
configurations skills trigger correctly only a fraction of the time when
relying on the platform's automatic intent detection. A workflow that
*must* fire reliably when relevant — like a pre-PR gate or a deploy
command — sometimes silently doesn't.

**How to avoid it:**

1. Skills' `description` frontmatter must use **concrete trigger phrases**,
   not abstractions. "Use when reviewing harness configuration" beats
   "Use when reviewing things." Front-load the key use case — combined
   `description` + `when_to_use` is truncated at 1,536 characters in the
   skill listing.
2. Decision boundary: bodies **over 50 lines that run less than once a
   session** are skills; bodies **under 50 lines or run every session**
   stay as commands. Workflow-essential pieces (`/preflight`, `/commit`,
   `/implement-task`, `/smoke`) stay as commands precisely because they
   need to fire reliably when explicitly invoked.
3. If a skill seems to stop influencing behavior after the first response,
   the content is usually still in context but the model is choosing
   other approaches. Strengthen the `description` to keep it preferred,
   or wire a hook for deterministic enforcement.

## Hook Exit Codes — Channel XOR

Claude Code processes hook output via exactly one channel: JSON on
stdout is processed only on exit 0; on exit 2, stdout is ignored and
stderr is read instead. Mixing channels silently fails. Pinned by
`tests/test_hook_protocol.py::TestHookProtocolXOR`.

See [sharp-edges/hook-exit-codes-channel-xor.md](sharp-edges/hook-exit-codes-channel-xor.md)
for the full failure mode, worked fix, and rationale.

## Hook umbrellas are mandatory for blocking-eligible PreToolUse / ConfigChange hooks

Every governance hook that can BLOCK (PreToolUse via `deny()`,
ConfigChange via `block()`) must wrap `main()` in `try: return
_run_main(); except BaseException: ...; return deny(...)`. Without the
umbrella, any uncaught exception in `_run_main` propagates to
`sys.exit(1)`, which Claude Code's hook protocol treats as a
non-blocking script error — the tool call proceeds.

The contract is per-hook (no inheritance, no decorator dedupe at the
three-site scale). Three sites today:

- `tools/cc/hooks/write_guard.py::main` (original; `check_exception_policy.py`
  exempts `BaseException` at hook entrypoints)
- `tools/cc/hooks/plan_guard.py::main`
- `tools/cc/hooks/config_guard.py::main`

Mirror constant per hook: `_denial_reasons.<HOOK>_INTERNAL_ERROR` —
never inline the deny string; the constant signals "this hook has the
umbrella."

Test contract: `tests/test_hooks.py::Test<Hook>FailClosed` (or
`tests/test_plan_guard.py::TestPlanGuardFailClosed` for plan_guard)
injects an exception into `_run_main` and asserts `rc == 0`
(channel-XOR exit code) with the deny/block envelope on stdout. Add
this test the same session you add the umbrella; otherwise the
umbrella is unverified.

**Advisory hooks have the same umbrella, opposite polarity — and a
different failure symptom.** `task_router` (UserPromptSubmit) and the
other non-blocking hooks also wrap `main()` in `except BaseException`,
but they fail OPEN (`return 0`): an advisory hook cannot and must not
block, so any uncaught exception degrades to a no-op advisory plus an
`[ERROR] <hook> crashed` stderr line — NOT a denied or unblocked tool
call. Two consequences when you touch one: (1) a reader bug (e.g. a
`UnicodeDecodeError` on a non-UTF-8 `cc/blueprints/latest.json`) is
*already* swallowed by the umbrella — the visible symptom is a
lost advisory + transcript noise, never `exit 1` — so calibrate its
magnitude as class-consistency, not crash-prevention; (2) pin the
earn-the-red at the reader's return value (`0` / `False`) or the absence
of the `crashed` line, because asserting on the exit code proves nothing
(the umbrella already forced it to 0). Do NOT "fix" an advisory hook to
fail closed — fail-open is the contract.

## Hook Wiring vs. File Existence

**What it is:** A hook file existing in `tools/cc/hooks/` does NOT mean it runs.

**How you hit it:** Adding a new hook script but forgetting to register it in
`.claude/settings.json`. The file sits silently unused.

**How to avoid it:** After adding any hook, verify `settings.json` has the entry
under the correct event. Run `/design` to audit all twelve standard hooks.

## Every scanner must ship with an earn-the-gate fixture

**What it is:** A scanner authored or tuned against current HEAD will return 0 findings because the debt it targets was just cleaned up. The scanner is then validated against HEAD ("ran, found nothing, ships") without ever being validated against a state where the positive case existed. The validation is structurally unverified — FM-7 §1.7 "gate tuning-to-HEAD blind spot."

**How you hit it:** Adding a scanner module, running it against the live repo (clean), seeing 0 findings, calling it done. Six months later a refactor silently breaks the scanner's detection logic; the scanner still returns 0 findings and CI still passes.

**How to avoid it:** The earn-the-gate pattern:

1. **Fixture:** `tests/fixtures/test_<scanner>_positives.<py|md>` — one function or section per documented shape. Functions deliberately lack the `test_` prefix so pytest collection skips them.

2. **Scanner-module exemption:** Each scanner that walks `tests/` (most do, via `iter_py_files`) declares `EXEMPT_PREFIXES = ("tests/fixtures/",)` at module level; `scan_repo` filters the walk output via `os.path.relpath(f, root).replace("\\", "/").startswith(prefix)`. Mirrors `convergence_theater.scan_repo`.

3. **Earn-the-gate test:** `tests/test_scanner_<scanner>.py::test_earn_the_gate_detects_every_fixture_shape` — calls the scanner's `scan_file` (or `outline_file` / `parse_fragment_markers` for non-AST scanners) DIRECTLY with the fixture path. Direct-call bypasses `scan_repo`'s walk and the EXEMPT_PREFIXES filter, so the fixture's shapes do surface. Asserts every documented identifier (`"kind"` / `"rule"` / policy / etc.) appears.

4. **Cross-scanner contract:** `tests/test_scanner_earn_the_gate_parity.py::TestEveryScannerHasEarnTheGate` walks `espalier/scanners/*.py`; any new scanner without a paired `tests/test_scanner_*.py` containing `test_earn_the_gate` fails the contract.

5. **No-regression contract:** Each per-scanner test file also has a `test_fixture_skipped_by_live_scan` (or `_not_in_live_scan` for freshness) that runs the full `scan_repo` and asserts zero findings reference the fixture path — confirms the EXEMPT_PREFIXES filter or surface allowlist works.

Direct-call is required because (a) the dispatch return shape varies — `exceptions`/`prints` return `list[dict]`, `test_loosening`/`perf_smells` return `dict{"findings": [...]}`, `godfiles` returns `dict{"loc": ..., "files": [...]}`, `freshness` returns `list[FragmentState]` — no uniform `.shape` attribute exists; (b) the EXEMPT_PREFIXES filter sits in `scan_repo`, not the per-file dispatch, so direct-call sidesteps it cleanly.

Exception: `canon_verifier` uses `tests/test_canon_verifier_contract.py` for per-shape coverage (CLAIM_DISCOVERERS map, not positive-case fixture). The earn-the-gate parity contract exempts canon_verifier explicitly.

## Every scanner must also ship with a must-NOT-trip negative corpus

**What it is:** The earn-the-gate fixture (above) proves a scanner FIRES; nothing proved it STAYS SILENT on clean-but-tempting input. An over-broad detector, or a quietly-widened exemption that starts ignoring real hits, returns the "right" count today and drifts invisibly — the harness only ever measured the fire direction. The must-NOT-trip negative corpus closes the silent direction.

**How you hit it:** Adding a scanner with only a `_positives` fixture + earn-the-gate test. `tests/test_scanner_negative_corpus_parity.py::TestEveryScannerHasNegativeCorpus` then fails on first commit: `missing negatives corpus tests/fixtures/<name>_negatives.<ext>`.

**How to avoid it:** Mirror the earn-the-gate pattern on the negative axis:

1. **Negative fixture:** the positives basename with `_positives` → `_negatives` (e.g. `test_<scanner>_negatives.<py|md>`) — clean-but-tempting near-misses the scanner must report ZERO findings on (a logged/re-raising broad `except`; a `skip(reason=...)`; an `assert` over a runtime value; a file under the godfile LOC threshold; a marker inside a fenced block). Same `tests/fixtures/` placement → the same `EXEMPT_PREFIXES` keeps it out of live `scan_repo` runs.

2. **Per-scanner must-NOT-trip test:** `tests/test_scanner_<name>.py::test_does_not_trip_on_negatives` — DIRECT-CALL the scanner's per-file entrypoint on the negative fixture and assert zero findings (mirror the per-scanner return shape: `== []` vs `["findings"] == []` vs `loc < threshold`). Prove non-vacuity (earn-the-red): the same entrypoint must return >0 on an equivalent planted-positive variant.

3. **Cross-scanner contract:** `test_scanner_negative_corpus_parity.py` derives the negatives path from each test file's positives reference by swapping `_positives.` → `_negatives.`. **Gotcha:** it matches the fixture BASENAME, not the full `tests/fixtures/...` path, because some test files build the path via `Path` joins (`REPO_ROOT / "tests" / "fixtures" / "<x>_positives.py"`) so only the basename appears as a string literal. Keep the positives basename present as a literal in the test file or the derivation can't find it.

**No time-bomb:** for date-sensitive scanners (`freshness`), the negative must stay clean as wall-clock advances — verify the structural/parser axis (which does no date arithmetic), or restamp dates relative to now. A hardcoded "recent" date ages into a finding (see "Proof Artifacts Go Stale").

Exemption: `canon_verifier` is exempt on the negative axis too (registry-backed, no fixture corpus) — same as earn-the-gate, via `NEGATIVE_CORPUS_EXEMPT`.

**Conceptual parent:** this paired-fixture discipline is invariants (1), (2), and (5) of an *autoimmune-resistant guard* — own your trigger (scoped synthetic fixtures; never scan your own defining material), scope/justify/locate any suppression (never in scanner core), and keep the contract machine-checkable against effective behavior. The other two invariants — (3) weakening emits a visible event, (4) no guard born-and-narrowed in one change — are the *born-weak* slice, measured observe-first by `post_write_check`'s born-weak observer (self-host, OBSERVE-ONLY). See `docs/FAILURE_MODES.md` §1.13 (Autoimmune regression) for the full mode, the two-harm split (false-positive-on-seed vs false-negative-introduced-by-the-fix), and the recursive-risk principle.

## A new pattern-detector trips the harness's own defenses

**What it is:** Espalier is a scanner/guard harness, so a catalog of prohibited patterns is the densest concentration of exactly the strings its own checkers hunt — self-collision is near-certain, not a tail risk (the autoimmune mode, `docs/FAILURE_MODES.md` §1.13). Building ANY new scanner / guard / hook / detector here trips both (a) the harness's pattern-checks firing on the new code's pattern DATA, and (b) a fan of sister-site SoTs. The born-weak observer self-collided THREE times in one session and reded ~7 sister-site contracts before landing.

**How you hit it:** Adding a detector and running only the targeted tests. The green suite hides the collisions until a broader gate (or the live hook) fires. Observed shapes: a literal `return 2` / `sys.exit(2)` in a non-`_` hook (`check_hook_protocol_correct`); a dotstar regex (`test_redos`); a `parents[N]` line-pin shifted by added imports (`test_scanner_magic_depth`); a new `.espalier-state/` file (`test_state_file_flag_parity`); a new `tools/cc/hooks/_*.py` helper (its count is a multi-surface SoT — roughly eight sister-sites); a new FAILURE_MODES §1.x coinage (count words + prose enumeration + recall index/twin); the detector firing on its OWN test corpus / fixtures (invariant #1).

**How to avoid it:** Before declaring a new detector done, run the sweep:

- **Self-collision (invariant #1):** the detector must EXEMPT its own defining material — its test file + `tests/fixtures/` — or it fires on itself (Harm A).
- **No deny-token DATA in a non-`_` hook:** `check_hook_protocol_correct` greps `\breturn\s+2\b` / `\bsys\.exit\(\s*2\s*\)` and skips `_`-prefixed helpers. Keep pattern-token tuples in a `_`-helper, or omit the colliding literal.
- **Fixtures both ways:** scanners ship `_positives` + `_negatives` + the earn-the-gate + must-NOT-trip tests (the parity contracts red on a miss).
- **State files:** a new `.espalier-state/` file → register in `test_state_file_flag_parity` AND confirm `session_start._clean_state_flags` puts it in the right keep-vs-clean family (accumulators must persist).
- **Regex:** bound any dotstar or allowlist it in `test_redos`.
- **Line-pins / positional pins:** added or removed imports/lines shift `magic_depth`'s `parents[N]` pin and any `path:NN` registry key (the `write_guard` first-200-byte SHA pin is the byte-offset cousin). They do **not** "fail LOUD" — `test_scanner_magic_depth` is now wired into the core suite so a magic_depth shift reds fast, but other positional contracts (the SHA pin) stay full-suite-only, so don't trust a green 3-file run after a top-of-file or import-shifting edit. Update the pin, or migrate it to a content anchor. See `docs/FAILURE_MODES.md` §13.8.
- **Numeric / coinage surfaces:** a new §1.x coinage → the count words + the prose enumeration + the recall index-vs-twin decision (`_FM_COINAGE_TWINS`).
- **Mirrors:** agent / `.md` edits → hand-edit the **SoT** `.claude/{agents,commands,skills}` only, then run `python scripts/sync_claude_mirrors.py` to regenerate the two GENERATED mirrors (`espalier/assets/claude/`, `examples/dogfooding/.claude/`) — never hand-edit a mirror (`test_package_resource_parity` + `TestClaudeMirrorGenerator` red on drift). This is the `.claude` analog of `scripts/sync_vendor_cc.py` (`tools/cc/` → `espalier/_vendor/cc/`). Both are rows in the mirror census (`espalier/mirror_registry.py`), which is where to look up any other path's sync script and direction. A **command** body's first line *also* regenerates `cc/COMMANDS.md` + `cc/LIVE_SURFACE.md` via `render_surface` (`test_manifest_truth`) — so editing a command = SoT edit + mirror regen **plus** a surface regen, or the suite reds.
- **Dogfood it live:** an always-on instrument's failure modes (the self-collision) surface only when it RUNS — static review won't catch them. Run a full suite and let the live hook fire before trusting green.

## A command-detection regex must exclude `=`, not require whitespace, to skip a shell assignment

**What it is:** `write_guard`'s bash-pattern regexes (`tools/cc/hooks/_bash_patterns.py`)
extract write/hardlink/rm operands by anchoring the verb with a word boundary,
`\b<verb>\b`. Because `=` is a word boundary, a shell variable assignment whose name
collides with a verb (`ln=$(…)`, `rm=$(…)`, `install=$(…)`) false-matches the
*command*, and a path in the assignment's value is read as a write target — a
false-positive denial. The obvious fix — require whitespace after the verb,
`\b<verb>(?=\s)` — is WRONG: it is a detection *hole*.

**How you hit it:** A quote is also a command-word terminator, and shell quote-removal
collapses `'rm'`, `"rm"`, `rm''` back into the real `rm`. So `'rm' -rf /` is a working
root delete, but `\brm(?=\s)` (whitespace required after the verb) does NOT match it —
the catastrophic-`rm -rf` hard-deny goes blind. Trading a false-positive for a
false-*negative* in a fail-closed gate is strictly worse: the harness's frame is
"false-positives outrank bypass-closing," but a fail-closed miss is the one thing that
outranks the false-positive.

**How to avoid it:** Exclude ONLY the assignment operator — `\b<verb>\b(?!=)`. That is
the original `\b<verb>\b` matcher minus exactly the `<verb>=` case, so every real
invocation (quoted or whitespace-separated) still matches and only the assignment is
skipped. Never narrow a verb anchor to "followed by whitespace" when "not an assignment"
is what you mean. And pair every assignment-FP suppression with a must-STILL-fire
negative twin — a quoted-verb real command that must still deny — for each touched verb:
the FP-only test passes even when the detector has gone fully blind, so the twin is what
pins the retained detection (the born-weak-guard slice of `docs/FAILURE_MODES.md` §1.13).

**Receipt:** `tests/test_write_guard.py::TestCatastrophicRmFlagOrderIndependent` (quoted-verb
rows in `_CATASTROPHIC`) and `TestBashWriteVerbsExpanded::test_quoted_verb_write_still_denied`
(all nine touched verbs) — each RED under a `(?=\s)` guard, GREEN under `\b(?!=)`.

## Scanner Non-Stdlib Imports

**What it is:** `espalier/scanners/` modules must be stdlib-only — no third-party deps.

**How you hit it:** Adding `import rich` or `from pydantic import ...` at the top
of a scanner module. Works locally if the dep is installed, silently fails anywhere it isn't.

**How to avoid it:** All imports in scanners must be from:
`os, re, sys, ast, json, math, pathlib, typing, collections, itertools, functools, dataclasses`.
Put any third-party use in `espalier/` modules, not `espalier/scanners/`.

## Reasoning-Review Agent Diversity Matters

**What it is:** `/reflect --reasoning <pack-path>` is most
valuable when the reviewing agent DIFFERS from the agent(s) that
generated the pack. Same-agent self-review inherits the same blind
spots — the agent that chose to narrow scope to markdown-only
fragments will likely not flag that narrowing as a finding when
reviewing its own output.

**How you hit it:** Running reasoning review with the same agent
type that drafted the pack. The reviewer rationalizes the same
scope choices it would have made; findings come back as a string
of PASS lines and the gate becomes ceremonial.

**How to avoid it:** Pick a different-context agent. Default is
opus-class general-purpose with external-context posturing; for
hook / gate / governance packs, prefer `failure-mode-reviewer`
specifically — its lens differs maximally from generation lenses.
The advisory-only posture means there is no mechanical enforcement
of diversity; it is operator discipline, monitored via the
acknowledge-rate metric in `.espalier/reasoning_review_log.jsonl`
(thresholds documented in `docs/CONVENTIONS.md` Reasoning review
section).

## Pack-Artifact Review Is the Mechanical Gate

**What it is:** `/implement-pack` step 0-A runs the
code-reviewer agent on the pack file before any sub-task executes.
It catches: wrong line numbers, missing symbols, factually wrong
prose claims about code state, stdlib-rule violations in code
examples, cross-pack ordering omissions, mutually inconsistent
pass criteria.

**How you hit it:** Authoring a pack with a `file.py:N` reference
that drifted (the file was edited after the pack was drafted), or
citing a symbol that was renamed. Pre-fix these errors surfaced
mid-execution, after partial edits had landed; post-fix they
surface at step 0-A and block execution before any edits happen.

**How to avoid it:** Re-grep cited symbols and line numbers as the
last step of pack authoring. Pack-artifact review is the safety
net, not the substitute. The gate does NOT catch reasoning errors
— those need the orthogonal `/reflect --reasoning` review.
The two gates are complementary:

- **Mechanical review:** is the pack internally consistent?
- **Cognitive review:** is the thinking that produced the pack sound?

A pack can pass mechanical review and still fail cognitive review; internal consistency
does not imply the reasoning chain is valid.

## Espalier Scanners Are Python-AST-Specific

**What it is:** `espalier/scanners/{exceptions,prints,godfiles,perf_smells,test_loosening}.py`
walk `.py` files and parse them with the Python `ast` module. On a
TypeScript / Rust / Go / etc. repo they find zero Python files and
report zero findings — which is *not* the same as "your code is clean."

**How you hit it:** Running `espalier scan` (or `/scan`, `/preflight`'s
scan step, `/test-this`'s scaffold) against a non-Python repo and
reading "0 findings" as a clean signal.

**How to avoid it:** Post-fix cmd_scan emits a `[WARN]` line to
stderr when the fingerprint's primary language is not Python, and
writes a typed result envelope (`reports/scan_summary.json` with
`status: "skipped_no_python_files"` vs `"scanned"`). Treat the
typed status field as the source of truth for downstream automation
— "0 findings because not applicable" is distinct from "0 findings
because clean." Scanner ports for other languages are v0.8+ work,
not yet planned.

## tools/cc/ Importing espalier/

**What it is:** `tools/cc/` scripts have zero espalier imports — they run standalone.

**How you hit it:** Adding `from espalier.models import BuildPlan` to a hook script.
Works in development where espalier/ is installed, breaks in any environment where it isn't.

**How to avoid it:** Any import of `espalier.*` in `tools/cc/` is a deployment bug.
Copy what you need inline or restructure so the logic lives in espalier/.

## Blueprint JSON Accumulation

**What it is:** Without bounds, `cc/blueprints/` would grow one JSON per session.

**How it is handled:** `cognitive_blueprint._save` auto-prunes to the most-recent
`BLUEPRINT_RETENTION` (200, defined in `tools/cc/_blueprint_limits.py`) on every
write; `load` reads only the latest, so accumulation is bounded automatically.

**What you do:** Nothing by default. To keep more/less history, adjust
`BLUEPRINT_RETENTION`.

## Path Normalization on Windows

**What it is:** Path comparisons must use `.replace("\\", "/")` on Windows.

**How you hit it:** Comparing `str(Path(...))` directly on Windows returns
backslash-separated paths. String comparison against forward-slash patterns silently fails.

**How to avoid it:** Always normalize: `str(path).replace("\\", "/")` before
any string comparison. Store normalized from the start.

**The second spelling, and it is the native one (`DEF-731`, walk 2 finding 11).** Git Bash —
the shell behind the Bash tool on Windows — spells drive C as a one-letter first component,
and `/c/Users/<u>/...` is what its own `pwd` returns there, so any path an agent builds from
`pwd`, `$PWD` or a parent-directory move arrives in it. Neither `pathlib` nor `ntpath` knows
the spelling: to them a rooted, drive-less path is *not absolute*, so `root / leaf` and
`ntpath.realpath` both anchor it onto the current drive as the fabricated `C:/c/Users/<u>`,
`relative_to` raises, and every identity, ancestor or containment compare against the
drive-spelled home or repo root misses — with no error anywhere. Driven on a real host:
`rm -rf /c/Users/<u>` fell to the clearable soft tier while `C:/Users/<u>` and `~` were
refused; measured under emulation: a protected write in the same spelling came back from the
normaliser verbatim and matched no zone. Separator normalisation does nothing for this — the
string has no backslashes to replace. **Any normaliser that compares an agent's path against
a drive-spelled root must translate the prefix first, on BOTH sides of the compare**, on
Windows only: `_hook_utils._msys_drive_to_windows` is the shared helper (`/c/x` → `C:/x`;
`/c` → the drive ROOT `C:/`, never the drive-relative `C:` that `ntpath` reads as "the
current directory on C"), called at the write-guard chokepoint, on the `CLAUDE_PROJECT_DIR`
value the root comes from, and inside `_bash_patterns._posix` *before* `realpath`. The root
side is not optional: a root exported by hand from Git Bash (`CLAUDE_PROJECT_DIR=$(pwd)`) is
fabricated the same way, and against a fabricated root the untranslated leaf happened to
match while a translated one could not — translating one side turns a lucky DENY into an
ALLOW. On a POSIX host the helper is a no-op and `/c/...` stays the ordinary directory it
is; WSL, Cygwin and MSYS2's own Python all run as `posix`, with root and leaf in one native
spelling, so they need nothing. The PowerShell extractor shares the chokepoint and reads a
rooted drive-less token the Git Bash way; by PowerShell's grammar `/c/x` is `C:\c\x` on the
current drive, so the only verdict that can change is a DENY under a directory literally
named after the repo's drive letter — fail-closed, and a declared limit rather than a
carve-out, pinned by
`tests/test_write_guard.py::TestGitBashDrivePrefix::test_the_powershell_extractor_reads_the_git_bash_spelling_at_the_chokepoint`.
The both-sides convention itself (every normaliser calls the chokepoint) has no mechanical gate today (the sister-site probe is name-keyed and
cannot see a normaliser that merely omits the call); the ledger carries the row. Emulate
Windows on a Mac with `os.name = "nt"`, a backslash-spelled `USERPROFILE`, `os.path.expanduser`
replaced by `ntpath.expanduser`, and `os.path.realpath` replaced by
`ntpath.normpath(ntpath.join(<drive cwd>, p))` — `tests/test_write_guard.py::_emulate_windows_paths`
— which reproduces the fabricated form exactly and, through the real `expanduser`, caught a
second defect in the same chokepoint: the separator fold ran *before* `~` expansion, so the
backslashes `USERPROFILE` splices in were never folded and the FS-free layer read a `~`-spelled
protected path as relative. Under that emulation bare `Path(...)` builds a `WindowsPath` that
raises on a POSIX host, so the `Path.resolve()` layer is pinned on a real Windows host only —
the portability workflow's Windows cell.

## POSIX-only `os.O_*` flags need `getattr` guards for Windows

**What it is:** `os.O_NOFOLLOW` and `os.O_NONBLOCK` are POSIX-only attributes;
on Windows CPython they are not defined on the `os` module. An inline
expression like `os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC`
raises `AttributeError` at module-import time on Windows.

**How you hit it:** Adding hardened cache reads (fd-level
discipline) without a portability guard. Both `espalier/freshness.py` and
`tools/cc/_freshness_cache.py` are loaded by the statusline and
SessionStart hook on every prompt — the first session on Windows crashes.

**How to avoid it:** Build a module-level constant via `getattr`:
`os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)`.
The OR-with-zero is a no-op, so POSIX hardening is preserved where the
flag exists and the import succeeds where it does not. See
`tests/test_freshness_windows_compat.py` for the monkeypatched regression test.

## A Content-Hash Pin Over Raw Bytes Is CRLF-Sensitive — Pin `eol=lf` For Your Bytes, Normalize The Host's

**What it is:** Any integrity/identity check that hashes the **raw bytes** of a
tracked file (`path.read_bytes()` → SHA-256) silently breaks on a Windows
`core.autocrlf=true` checkout: git rewrites LF→CRLF on checkout, the bytes
change, and the hash no longer matches a value pinned against LF.

**Two answers, by whose bytes they are (DEF-725, 2026-09-10).** The self-host
fingerprint PINS: `.gitattributes` declares `eol=lf` for the hashed file
(below), because those bytes are ours to declare. The adopter-side integrity
manifest NORMALIZES instead: it hashes the canonical text form -- a leading
UTF-8 BOM stripped, CRLF and bare CR folded to LF, the one owner being
`tools/cc/hooks/_integrity.py::canonical_text_bytes` -- under the algorithm
name `sha256-lf`, and still verifies a manifest written under the raw-bytes
name `sha256` until its next refresh. The host owns its `.gitattributes`, and
the Git for Windows installer ships `core.autocrlf=true` at system scope, so a
raw-bytes manifest reported every managed file changed on a fresh fusion (28 of
28, driven 2026-09-09) while `refresh` only moved the wrongness to the next LF
checkout. `install-ci`'s workflow compare and `selfcheck`'s deployed-versus-
package hook compare read the same canon through the integrity bridge (which
backfills it on a pre-canon hook module, the bisect skew). An ending or a BOM
cannot change what a hook does: CPython decodes source with universal newlines
and hooks are launched by interpreter path, not by shebang; a UTF-16/32
re-encoding is not decoded (the fold only sees its `0x0D` bytes), so it stays
the drift it is. The name is a WIRE VALUE across two surfaces that upgrade by
different commands: the engine's vendored copy writes the manifest, the
DEPLOYED hooks read it, and `pip install -U` moves only the first. So the
writer follows the reader (`_writer_algorithm` reads the deployed copy's
constant statically and writes the legacy name with a warning to run
`espalier upgrade --execute`), and every remedy printer sends a protocol
sentinel (`<algorithm_unsupported:` / `<schema_version_unsupported:`) to the
redeploy, never to `refresh`, which would rewrite the same manifest. Reach
for the pin when the bytes are yours to declare, the canon when they are the
host's.

**The other way in — plain prose, no Windows required (2026-08-13).** Those 200
bytes are a shebang and an ordinary module docstring, so *reflowing a sentence*
is enough to flip the signal. Nothing about the text looked load-bearing, so
`write_guard.py` now carries a `DO NOT REFLOW` warning **inside** the hashed
region — self-protecting, since deleting it is itself a pin change — pinned by
`tests/test_self_host_fingerprint_parity.py::test_the_pinned_region_warns_its_own_editor`,
which fails if the warning drifts past byte 200 (text present, protection gone).
Stakes rose when the `provenance` / `pre-release` / `release-pack` verbs began
standing down on this predicate: a stale pin now makes them report "not
applicable" **on this repo**, so `/commit` and `/smoke` — which run no pytest —
report a census that never ran. Any pytest run still reds it in ~0.5 s.
⚠ `espalier _refresh-self-host-pin` rewrote only the **library** copy, leaving
the hook-side constant stale and the suite red on the very edit the warning
tells you to run it for; it now rewrites both carriers atomically and prints
each, pinned by `::test_the_refresh_verb_updates_every_pin_carrier`.

**How you hit it:** The self-host signal-5 fingerprint pins
`SHA-256(write_guard.py's first 200 bytes)` (`espalier/_self_host_fingerprint.py`,
mirrored in `tools/cc/hooks/_hook_utils.py`). On a CRLF checkout the hash
mismatches → `is_self_host_repo` returns False → the harness mistakes its own
source tree for an adopter repo (suppressing the harness-dev exemplar corpus,
mis-gating maintenance flows). The break only manifests on a Windows / autocrlf
runner, so an LF-only CI never sees it. The same pin fails for a session rooted
IN an older worktree of this repo (a detached walk checkout whose
`write_guard.py` predates the pinned bytes): there `espalier/` and
`.github/workflows/` drop out of the protected set, while a root-rooted session
reaching into that worktree protects them (DEF-743 keys the prefixes to the
root's identity and the path to the checkout containing it).

**How to avoid it:** Pin the on-disk EOL with `.gitattributes` — `*.py text
eol=lf` (at minimum for the hashed file) makes the bytes LF-deterministic on
every platform. The pinned hash is an LF hash, so the rule keeps it valid; do
NOT re-pin (the bytes don't change on an LF tree — re-pinning against a CRLF tree
would entrench the bug). Receipt: `.gitattributes` + the `eol=lf` / live-LF-hash
parity tests in `tests/test_self_host_fingerprint_parity.py`. Rejected
alternative *for this pin*: normalizing CRLF→LF *inside* the hash computation
silently changes the byte-exact detection contract — for bytes that are ours to
declare. The adopter-side integrity manifest takes exactly that alternative,
because its bytes are the host's (the two-answers paragraph above).

## `Path.exists()` answers a parent that denies traversal per interpreter -- and the engine's verdicts followed it

**What it is:** `Path.exists()`, `is_file()`, `is_dir()` and `is_symlink()` do not
agree across the interpreters the engine supports when a PARENT directory denies
search permission. CPython 3.10-3.13 let the stat's `PermissionError` escape;
3.14 routes the same call through `os.path.*` and swallows every `OSError` into
`False` (measured on real 3.10, 3.13 and 3.14 interpreters 2026-09-13, and
pinned by `tests/test_surface_contract.py`, which reds the cell where the claim
drifts -- the first cut of the fix wrote "3.13+" at eight sites on the strength
of a 3.10-vs-3.14 drive alone). So a `.claude` an adopter cannot search read as
a crash on four floors and as "absent" on the fifth -- and every verdict built
on that answer diverged with it. Driven (`DEF-763`): on 3.14 `doctor` listed
every deployed file as missing and offered `init` (which cannot write there
either), `audit` listed every manifest entry as promised-and-missing, `upgrade`
dry-ran green and exited 0, `merge-settings` said "no settings.json found"; on
3.10 and 3.13 each of them died at its first `exists()` with a bare
`Error: [Errno 13]` line, and `python -m espalier.self_hosting` with a traceback
out of the tree walk's own `.git` probe. The class is `docs/FAILURE_MODES.md`
§9.7 (version-gated stdlib semantics); this is its second in-repo instance, and
`tests/_legacy_pathlib.py`, written for the first, records two earlier bites of
the same table. The row had been filed as Linux-only for want of a Linux host;
a `uv` 3.10 venv reproduced it on macOS in one run.

**How you hit it:** Any yes/no question about a path under `.claude/` (or any
directory the adopter owns the permissions of) asked with a pathlib existence
method, on a dev host running 3.14. The dev run cannot show the raise, and the
3.14 CI cell cannot either; only the 3.10-3.13 cells red, and only on a fixture
that locks a directory. A green suite on this box says nothing about the floor
-- unless the test runs the product under `tests/_legacy_pathlib.py`'s
`legacy_pathlib_probes()`, which substitutes the 3.10-3.13 bodies on this host.

**The rule:** existence is classified by errno, in one place --
`surface_contract.path_presence` (`present` / `absent` / `unreadable` with the
OS's own detail; ENOENT and ENOTDIR are absence, everything else is something
you cannot see, deliberately narrower than pathlib's own table, which forgives
ELOOP) and `surface_contract.unreadable_harness_root` for the root question the
command layer asks first: in `cli._resolve_repo_arg` for every command that
resolves a repo argument, at the `init`, `upgrade` and `fuse` pre-flights for
the three that resolve their own, in the `self_hosting` and `recovery` module
entry points before their walks, and inside `run_doctor_check` and
`run_cc_surface_gate` so their reports carry the finding for any caller
(`docs/CLI_EXIT_CODES.md` says which exit each home gives; a repo-taking
command that asks at none of them reds
`tests/test_cli_commands.py::TestEveryRepoTakingCommandAsksTheClaudeQuestion`).
Sites that only need a uniform yes/no use `os.path.isfile` / `os.path.lexists`
/ `os.path.exists`, which swallow the same way on every floor -- the walk's
`.git` probes in `_safe_walk` included. Two nets pin it:
`tests/test_contracts.py::TestSettingsPresenceNeverAsksPathlib` derives its
population from every engine module by AST and reds on a settings-named
receiver asking pathlib (a receiver named `path` evades it, by construction),
and `TestTheEngineHoldsUnderLegacyPathlib` beside it runs the entry points
against a locked `.claude` under the legacy bodies, which catches any spelling
at the cost of covering only what it drives. Two residuals are named rather than
covered: the gate stops at `.claude` itself, so a locked `.claude/agents` still
answers per interpreter at the kind-directory walks behind it; and the hook
layer's settings probe (`_hook_utils.surface_status`, which PostCompact and
SessionStart run mid-session) is `os.path`, while the rest of the hooks are
reached only after Claude Code has itself read `.claude/`. When a row says "red
on a Linux cell", build the `uv` venv for that cell's interpreter before reaching
for a Linux host.

## `str(OSError)` renders the path through `repr` -- and the operator pastes a path that does not exist

**What it is:** `OSError.__str__` renders `filename` (and `filename2`) with
`repr`, so `[Errno 13] Permission denied: 'C:\\repo\\.claude'` is what a
Windows operator reads: every backslash doubled and the path quoted, and the
shell says no such file when they paste it (`DEF-799`; driven on the Windows
host 2026-09-14, walk 3 leg 5-D, an ACL-denied `.claude`). On POSIX the two
renders are indistinguishable from the path, which is why three interpreters'
worth of `DEF-763` evidence never saw it -- but the defect is reproducible
here: `repr` doubles on every platform, so an `OSError` constructed with a
backslash-carrying filename shows it, and the pins red without a Windows host.
The walk named five sites; the pins red on the prior head at 95 across the
engine, the hooks, `session_resume`, `statusline` and the scanners -- the
CLI's own top-level `Error: {exc}` line and every hook's `except Exception`
crash guard among them (a broad handler CATCHES an OSError, and the crash
guard fires on exactly the file read that fails) -- plus about twenty
explicit `!r` renders of a hook command or a resolved interpreter path (the
rewire report the walk quoted verbatim, with the doubled backslashes already
on screen). The first census stopped at handlers naming the OSError family
and missed the 21 broad ones; the failure-mode review widened it.

**How you hit it:** Writing `f"... {exc}"` or `str(exc)` in an `except OSError`
handler, or `{path!r}` / `{cmd!r}` for a value that is or may carry a path --
the natural spellings, and correct-looking on every dev host this repo has.

**The rule:** route the exception through `os_error_text(exc)`
(`espalier._text`; `tools/cc/_json_safe` for the hooks and scripts; the
scanners, which inline by contract, record `e.strerror` beside the path key
they already carry), and render a path or command plain inside backticks.
`docs/CONVENTIONS.md` has the section.

**Detection:** `tests/test_portability_contract.py::TestOsErrorsRenderAsPaths`
(any load of a name bound by a handler that can catch an `OSError` -- the
family, `Exception`, `BaseException` -- that is not structural or routed to a
roster renderer reds, whatever the sink; a roster helper must call the seam
in its own body) and `::TestPathsAreNotRenderedThroughRepr` (`!r` on a name
bound from a path source, or on the path vocabulary, reds; the vocabulary is
live-pinned both ways with a red fixture per name). Both earned their red on
`0743dd6`: 95 sites.

## A read-only file makes a bare `rmtree` stop on Windows -- and the best-effort rollback that swallows it leaves the state it exists to prevent

**What it is:** `shutil.rmtree` deletes a file with `os.unlink`. On Windows that
call raises `PermissionError` for a file carrying the read-only attribute: every
packfile git writes has it, and `shutil.copytree`'s default `copy2` preserves it
when `fuse` copies a host's `.git` into the fusion. On POSIX `unlink` is governed
by the parent directory's write bit, so a `0444` packfile deletes without
complaint and a green macOS delete is no evidence about the Windows one (ledger
`DEF-734`; recovered from walk 1's residue by the walk-2 audit, premise
re-verified at HEAD).

**How you hit it:** `fuse`'s two rollback deletes ran `rmtree(...,
ignore_errors=True)`, so on Windows a fault after the `.git` copy under-deleted
silently and left the partial fusion that fuse's own non-empty guard then refused
on retry -- the state the rollback comment says it exists to prevent.
`cleanup._delete_path` ran a bare `rmtree`, so an uninstall over a hook an
adopter had marked read-only (`attrib +R`, the walk's own probe) raised
mid-teardown. Neither site had an `onexc=` / `onerror=` handler; the class is "a
tree removal with no answer for the bits refusing", and it grows one call at a
time.

**How to avoid it:** every tree removal in `espalier/` goes through
`espalier/_rmtree.py::remove_tree`, and every file delete in the two teardown
modules (`cleanup`, the `fuse` rollback) through its sibling `remove_file` -- a
hook is a FILE, so the file arm is the one the walk's own probe actually runs;
the first cut of this fix covered `rmtree` alone and the failure-mode review
caught it. The handler clears the write bit and retries once, under one rule:
**clear bits only on what you were asked to delete** -- a locked directory
inside a tree is cleared (it is part of the ask), a tree's own parent and a
file's directory are not ours and the delete reports instead.
`tests/test_contracts.py::TestTreeRemovalClearsReadOnly` pins both shapes by
AST, with the population floor read from the same walker. Strict (the default)
re-raises a second refusal -- a teardown must report what it left;
`best_effort=True` swallows it, for a rollback that is already handling the
original fault and must not mask it with a second. The POSIX shape of the same
refusal (a directory without its write bit) is what this host can produce and
what `tests/test_rmtree.py` drives on both sides of the rule; the Windows
attribute itself is the walk's to witness, and the row is not struck on a POSIX
green.

## `Path.rglob` / recursive `Path.glob` follows directory symlinks on CPython < 3.13

**What it is:** `Path.rglob(...)` and literal-recursive `Path.glob("**/...")`
descend into symlinked directories on CPython 3.10–3.12 (`recurse_symlinks` only
became default-`False` at 3.13). On an adopter tree with a directory-symlink
**loop**, the first recursive walk raises `OSError(ELOOP)`; on a plain dir
symlink it silently inflates / double-counts. The engine supports 3.10+, so this
is a live first-run crash, not a theoretical one.

**How you hit it:** Calling a bare `rglob` / recursive `glob` on a path that may
be an adopter tree — the `fingerprint` / `scan` / scope walk — from any engine
module, scanner, or hook. A dev host on CPython 3.13+ (where the safe default
already applies) cannot reproduce it; the bug only shows on a 3.10–3.12 runner
with a symlinked subtree, so a green dev run and a 3.13+ CI leg both read "fine"
while it ships broken (the earn-the-red has a platform ceiling — FAILURE_MODES
§13.7).

**How to avoid it:** Never call a bare `rglob` / recursive `glob` on an adopter
path. Use `espalier/_safe_walk.safe_rglob` / `safe_glob`
(`os.walk(followlinks=False)`, safe on every version); scanners and `tools/cc`
carry an inline `_safe_rglob` because they cannot import `espalier/`. The
`filesystem_contracts.scan_recursive_walks` recurrence guard (`/scan
filesystem_contracts`, also at `stop_gate`) reds on any new unannotated bare
walk; a genuinely-self-host-only walk carries `# espalier:safe-walk-ok <reason>`.
Full convention: CONVENTIONS.md "Symlink-safe recursive walks"; class detail in
FAILURE_MODES §9.7 (version-gated stdlib semantics) and §2.8 (the narrow-lock
sweep this came from).

## Stop Gate Mode (Light vs Full)

**What it is:** `stop_gate.py` runs lightweight session hygiene by default. Gate 1 (core pytest) only fires when `ESPALIER_STOP_GATE=full` is set in the environment. Other values warn to stderr and fall back to light mode.

**Why:** Stop fires at the end of every turn. Running the full pytest suite on every Stop made the harness feel slow and overbearing for ordinary edits. Heavy proof belongs in `espalier pre-release` and CI.

**How to opt into full pytest on Stop:**

```bash
export ESPALIER_STOP_GATE=full
```

Set it per-shell, in your shell rc, or in `.claude/settings.json` under `env`.

## Stop Gate Timeout for Large Test Suites (full mode only)

**What it is:** When `ESPALIER_STOP_GATE=full`, Gate 1 runs `pytest tests/test_fingerprint.py tests/test_hooks.py tests/test_scanners.py tests/test_scanner_magic_depth.py -q` with a 60-second inner budget (`STOP_INNER_BUDGET` in `_hook_contract.py`). The stop_gate outer timeout in `settings.json` must be at least 90 seconds (`STOP_OUTER_TIMEOUT`) — `harness_config.py` generates this correctly, but a stale `settings.json` (pre-init) may have a lower value. If your core test suite grows past ~60 seconds, the gate will time out and silently pass rather than block.

**How to avoid it:** Keep the core test suite fast. If tests grow slow, split into a smoke subset and point `_HARNESS_DEFAULT_TESTS` in `stop_gate.py` at the fast smoke tests only. Or increase the stop hook `timeout` in `.claude/settings.json`. (`test_scanner_magic_depth` is in the set deliberately — at ~3s it's cheap insurance against the positional-pin false-green below; do NOT add `test_fuse`, which at ~17s would threaten the 60s budget.)

## The documented core test suite is a false-green floor for positional/overlay contracts

**What it is:** The "core test suite" documented in `CLAUDE.md`, `docs/CHEAT-SHEET.md`, and `ESPALIER_MEMORY.md`, and the `_HARNESS_DEFAULT_TESTS` fallback in `stop_gate.py`, are a *fast subset* — not the full suite. A refactor can pass this subset GREEN while a broader contract reds only under `pytest -q`.

**How you hit it:** Two shapes. (1) Removing an `import` shifts a `magic_depth` `parents[N]` line-pin (`post_write_check.py:127→126`); the targeted tests pass, the full suite catches it (now mitigated — `test_scanner_magic_depth` is wired into the core set). (2) A new module left `git`-untracked is excluded from `fuse`'s overlay and crashes post-overlay `fingerprint`; `test_fuse` is NOT in the core set (and at ~17s it cannot be — it would blow the 60s Gate-1 budget). So the core subset still cannot catch every positional/overlay contract.

**How to avoid it:** After any top-of-file edit, import change, or new-module add, run the FULL `pytest -q` — do not trust a green core run. Note that `ESPALIER_STOP_GATE=light` (the default, and what self-host sessions run) means Gate 1 does NOT run pytest at all; the catch-net is *you* running the full suite, not the harness enforcing it.

## A property-pinning test that feeds only conforming inputs falsely certifies the property

**What it is:** A test NAMED for a property gives false assurance if it only feeds inputs that *cannot* violate that property. The test passes, the suite is green, and the property reads as pinned — but the branch that would break it was never exercised.

**How you hit it:** `tests/test_session_banner.py::test_never_splits_mid_word` fed only whitespace-laden strings to `_truncate_on_boundary`, so its no-whitespace branch (a single over-budget token with no boundary → a raw mid-word byte-prefix leak, plus a `cut > 0` off-by-one at index 0) was never run. The suite was GREEN while the function's central honesty guarantee — its whole reason to exist over the lossy clip it replaced — was unpinned for exactly the case that broke it. A 16-agent adversarial pass, not the test, caught it (2026-06-29).

**How to avoid it:** A property test MUST feed the input that would *violate* the property (here: the wordless / boundary-less case), not just confirming inputs — this is earn-the-red applied to a *property*, not to a fix. When a function's docstring promises an invariant ("never mid-word"), grep for the adversarial input class and assert the invariant holds on it. Sister of "earn-the-red proves X, not not-also-Y": a green property test proves the conforming path, NOT the property.

## A newly-created file is invisible to `git ls-files`-derived gates until `git add`-ed (`fuse` overlay + shipping-surface contracts)

**What it is:** Several gates DERIVE their target set from `git ls-files`, not from a disk walk — so a file that exists on disk but is `git`-untracked is silently skipped by all of them. (Disk-walk scanners — the per-dir `glob`/`rglob` contracts in `tests/test_contracts.py` — still see it; the trap is specific to the `git ls-files`-derived family.) The blind family is:

- `espalier fuse` builds its overlay from `git ls-files -z` (`espalier/fuse.py`) — an untracked module is excluded from the fused tree.
- The production-code contracts whose surface comes from `_iter_production_py` (`tests/test_contracts.py`, "DERIVED from `git ls-files`") — e.g. the subprocess-encoding pin (`TestSubprocessEncodingPinned`).
- The provenance census (`tests/test_no_provenance_in_shipped_code.py`), which enumerates the shipping surface via `repo_mode.list_tracked_or_walked_files` (tracked files inside a git repo).

**How you hit it:**

- *fuse:* a refactor creates a NEW `espalier/` module (e.g. a consolidated `_report_io.py`) and another module imports it. The in-place suite is green, but the post-overlay `fingerprint`/import crashes because the new module was never copied into the overlay. Only the full suite (which exercises `fuse`) reds, and only if the new module is on an imported path.
- *contracts:* a pack adds a NEW shipped tool (e.g. a `tools/cc/` script) and you run the pre-commit FULL suite while the file is still `??`. The suite reads green even though the file carries provenance tags or an unpinned `subprocess(text=True)` — the `git ls-files` gates never scanned it. The violations fire only AFTER the commit makes the file tracked: a structural false-green, not a clean bill, and it can bite more than once in one file.

**How to avoid it:** `git add` a new tracked/shipped file the moment you create it, before running anything that exercises `fuse` or the production-code contracts. The plan/commit discipline normally covers this, but a mid-refactor or pre-commit run on an untracked file will not. After committing a new shipped file, re-run the cheap `git ls-files` gates explicitly — `pytest tests/test_contracts.py tests/test_no_provenance_in_shipped_code.py` (seconds, no full-suite round-trip) — and treat a post-commit red as expected-to-verify, not a surprise.

## "ZERO deny-predicate changes" can hold while a deny SURFACE is restructured

**What it is:** The standing "ZERO deny-predicate changes" attestation covers predicate/threshold/ordering logic in the guard hooks. It does NOT cover the protected-file/integrity *enumeration* in `espalier/surface_contract.py`, which also feeds write_guard / integrity / CI denials.

**How you hit it:** Moving that enumeration from hardcoded tuples to a `managed_inventory`-derived list (`_hook_protected_files()` lazy-imports `get_hook_entry_files()` + `get_hook_helper_files()`), preserving the exact set (0 drops) — a real change to a deny *surface* that is invisible if you only diff the deny *predicates*. The failure mode also shifts: a static tuple can never raise; the derived function throws if `managed_inventory` ever fails to import. (Low severity — the live runtime deny path uses independent hardcoded literals per the zero-import rule, not this derived function.)

**How to avoid it:** When a pack touches `surface_contract`'s protected lists, verify the *enumeration* (the set of protected paths) is unchanged — `test_integrity_contract_parity` pins `_integrity.MANIFEST_FILES == get_protected_integrity_paths()`. "I didn't touch a predicate" is not the same as "I didn't touch a deny surface."

## The Edit tool fails on mixed em-dash encoding; large verbatim lifts need a defensive transform

**What it is:** Two failure shapes during big behavior-preserving lifts. (1) A block that mixes a real U+2014 em-dash (`—`) with a literal-`—` typo (six ASCII chars) on a nearby line defeats the Edit tool's whole-block exact match — the harness's escape-swap can't reconcile both encodings, so the block "isn't found" though it looks identical on screen. (2) A 200+-line verbatim move (a de-indent lift, a block relocation) is impractical and error-prone via string matching.

**How you hit it:** Comments with mixed em-dash encoding, and large (~205–250-line) verbatim moves.

**How to avoid it:** For (1), split the edit into per-encoding regions. For (2), use a content-anchored Python transform run via Bash that asserts its markers are unique and `ast.parse()`s the result before writing. Do NOT hand-massage a 200-line block through repeated Edit calls.

## Plan Guard Exemption Prefix Matching

**What it is:** `plan_guard.py` resolves its exempt prefix list per-call from three sources, in precedence order: (1) universal — `tests/`, `tools/cc/`, `.claude/`, `cc/`, `reports/`, `memory/`, `docs/`, `task-packs/`, `.espalier-state/`; (2) self-host carve-out — `espalier/` adds when `_hook_utils.is_self_host_repo()` returns True (5-signal fingerprint detection); (3) adopter — flat top-level `plan_exempt_prefixes = [...]` in `espalier.toml`. Each source is checked with the same NFKC + casefold normalization. Root-level files are exempt only when they are not known source/config/project files (e.g. `ESPALIER_MEMORY.md` is exempt; `README.md` and `pyproject.toml` require a plan).

**How you hit it:** A source file at `tests/src/app.py` would be exempt because it starts with `tests/`. If your project nests source under test directories, those files would bypass the plan requirement. Adopters whose source lives at `src/myapp/` or `lib/` discover that every tiny Edit triggers the plan-required gate — the default exempt list deliberately omits these conventional layouts to keep discipline strict by default.

**How to avoid it:** Adopters use the `espalier.toml` knob — never edit `EXEMPT_PREFIXES` in the hook source:

```toml
# espalier.toml
plan_exempt_prefixes = ["src/", "lib/"]
```

The knob is opt-in, narrow (only relaxes plan_guard — does NOT touch write_guard's protected-zone check or stop_gate's docs-refresh and code-review gates), and validated (each entry must end with `/`; absolute paths and `..` traversal rejected; any invalid entry drops the whole list back to strict mode). Do NOT use `ESPALIER_MAINTENANCE_MODE=1` as a friction reliever — that env var also bypasses write_guard, stop_gate and subagent_stop's blueprint append from then on, silently turning the harness's discipline product advisory. See [sharp-edges/plan-guard-adopter-source-roots.md](sharp-edges/plan-guard-adopter-source-roots.md) for the full design and `MAINTENANCE_MODE` boundary table.

If a test fixture directory looks exempt by name (`tests/src/`), renaming the directory is the simpler fix than custom prefix gymnastics — most projects don't nest production source under `tests/` deliberately. Editing `EXEMPT_PREFIXES` or `_hook_utils.harness_exempt_prefixes()` in the hook source is a harness-maintainer last resort, not an adopter mechanism.

## UserPromptSubmit Fires on All Prompts

**What it is:** `task_router.py` runs on every user prompt, including conversational ones. It must be conservative about injecting guidance. False positives (routing guidance appearing on a simple question) waste context tokens. False negatives (missing a multi-step task) are low-cost because `plan_guard.py` will catch the write attempt anyway.

**How to avoid it:** If task_router fires too often, tighten `MULTI_STEP_KEYWORDS` or add more `QUICK_FIX_PREFIXES`. The router's role is a soft nudge, not enforcement — plan_guard is the enforcement layer.

## ESPALIER_MEMORY.md Line Limit

<!-- espalier:fragment id=memory-line-cap
     bound=tests/test_contracts.py::TestMemoryMdLineLimit::test_memory_md_within_cap
     policy=verify-on-touch -->
**What it is:** ESPALIER_MEMORY.md is loaded every session — it must stay at 120 lines or fewer.
The cap has been raised three times (60 → 75 → 80 → 120) as headers and the
permanent Decisions/Patterns tables crowded the Session Log.

**How you hit it:** Session log grows unbounded. After 10+ sessions the file
bloats past the cap and wastes context on stale history. Or: a single rich
session row pushes file length right at the cap so the next handoff fails
before any content is written.

**How to avoid it:** Run `espalier memory prune` at `/handoff`
when the file is at or near the cap. The verb moves the oldest Session
Log rows to `docs/session-archive.md` (gitignored local archive) under
a date-stamped heading and refuses to leave the table empty. Last
resort only: raise the cap by 5 in
`tests/test_contracts.py::TestMemoryMdLineLimit` — the cap exists to
keep the file bounded, and the multi-raise history (60 → 75 → 80 → 120) is
exactly the drift this section warns against.

## ESPALIER_MEMORY.md Autoprune Archives the Row You Just Added

**What it is:** `post_write_check.py` fires `espalier memory prune` whenever a
ESPALIER_MEMORY.md write pushes the file past the 120-line cap. Prune moves the *oldest*
Session Log rows (by leading `| YYYY-MM-DD` date, ascending) to the archive.

**✅ CLOSED 2026-08-20 for the primary trigger — kept because the reasoning is
still load-bearing and the second trigger below is still live.** The hook now
passes `--keep-newest 1` alongside `--allow-empty`, and the verb does not let
`--allow-empty` waive that reservation. The newest row is never evicted.
The fix was owed rather than optional: ESPALIER_MEMORY.md's own pruning policy
has said *"the newest rows are always kept"* in shipped prose the whole time,
while `tests/test_memory_autoprune.py` asserted the single row came back
archived — the code had drifted from its documented contract and a test held the
drift in place. **The trade, taken knowingly:** a file whose entire excess is one
fat log row can no longer self-heal; it falls to the residual-over-cap warning
and stays over cap until someone trims.

**How you used to hit it:** When the Session Log is empty or nearly empty — e.g.
right after the table has been curated down to a stub — writing one new row and
tripping the cap made autoprune archive *that just-added row*. With a
single-row log there is no "older" row to evict, so the row you just wrote was
the one that left. The net effect: your handoff note silently landed in the
gitignored archive instead of ESPALIER_MEMORY.md, and the file looked like
nothing was written.

**The same-date tiebreak used to be a second way in, and its sign is now
load-bearing (2026-08-16b).** `/handoff` PREPENDS, so within one date the
bottom-most row is the oldest. While `handoff.md` still said "append", prune's
tie-break was a plain ascending file index — top-of-table first — which is
correct under append and archives *the row you just wrote* under prepend.
Driven: three rows sharing today's date plus one from yesterday, `--rows 2`
archived yesterday's row **and** the just-written one, keeping both older
same-day rows. Corrected to a negated index (`espalier/cli.py::cmd_memory_prune`),
so bottom-most-within-a-date is now the oldest. ⚠ If the insertion convention
ever flips back, that sign must flip with it — the doc, the tie-break and the
digest's descending sort are one decision in three places.

**How to avoid it:** When the file is at or near the cap with a near-empty
Session Log, reclaim headroom from *other* lines (trim a stale Decisions or
Patterns row, tighten prose) **before** writing to the Session Log — not
after. Don't count on adding a row to an already-full file; the write and the
autoprune race, and the autoprune wins.

**The second trigger, and it does not look related at all (2026-08-09):** the cap
is on the **whole file** while only Session Log rows are ever evicted — so prose
growth in *any* section pays for itself out of the log. An 8-line addition to
`## Patterns Learned`, a pointer section near the TOP of the file, archived 8
session rows dated 2026-07-28..07-31. Nobody editing a prose section predicts
they are archiving July. Two consequences worth knowing: `docs/session-archive.md`
is **gitignored**, so evicted rows leave the tracked tree and survive only on that
disk plus git history; and **shrinking the addition afterwards does not bring them
back** — the prune already ran, and the freed lines are headroom for future rows,
not a restore. Budget the edit before making it, whichever section it lands in.

**This trigger is now REPORTED rather than silent (2026-08-20), which is not the
same as fixed.** When a prune leaves the file still over cap, the hook names the
three largest sections instead of guessing at the permanent tables — so the cost
is attributed to the section that actually grew rather than to session history.
The prune verb also names the DATES of the rows it archived, which is the only
handle you get: the destination is gitignored *and* `export-ignore`d, so those
rows exist on one disk and in git history and nowhere else. Attributing the cost
does not refund it; the eviction still happened.

## Five-Surface Command Sync

**What it is:** When a command is added or removed, five surfaces must stay in sync:
`CLAUDE.md` (command table), `docs/CHEAT-SHEET.md` (category listing), `cc/LIVE_SURFACE.md`
(command list), `cc/COMMANDS.md` (purpose table), and `cc/PACK_MANIFEST.txt` (file inventory).

**How you hit it:** Deleting a command file and updating CLAUDE.md, LIVE_SURFACE.md,
and COMMANDS.md — but forgetting docs/CHEAT-SHEET.md and PACK_MANIFEST.txt. The stale
references linger and confuse future sessions.

**How to avoid it:** After any command add/remove, grep for the command name across
all five surfaces. `managed_paths.py` discovers commands dynamically (glob), so init
stays correct automatically — but the doc surfaces are manually maintained.

## Path-Traversal Resolution in write_guard / plan_guard

**What it is:** `_normalize_path` in `write_guard.py`, `plan_guard.py`,
`post_write_check.py`, and `reflect_trigger.py` resolves `..` traversal
sequences before checking against protected/exempt prefixes. Without this,
`safe_dir/../tools/cc/hooks/write_guard.py` would not start with
`tools/cc/` and would slip past the guard while still landing at the
protected file on disk.

**How you hit it (pre-fix):** Any Write/Edit tool call with an
`<unprotected>/../<protected>` `file_path` value bypassed write_guard
entirely. The same shape bypassed plan_guard's exempt-prefix check
(e.g., `tests/../src/app.py` looked exempt under `tests/`).

**How to avoid breaking it:** Any new `_normalize_*` helper in `tools/cc/`
must resolve a non-absolute path against the root before relativising it,
not return it as-is -- and relativise against the checkout that CONTAINS the
result, not the root alone: `_hook_utils.resolve_in_checkout` (the owner
behind `normalize_path`, `normalize_path_str` and `normalize_bash_path`)
picks the deepest of the root and its registered git worktrees, read from
git's own registry on disk, so a target inside `.claude/worktrees/<name>`
reads `tools/cc/x.py` rather than the unprotected, plan-exempt
`.claude/worktrees/<name>/tools/cc/x.py` that `relative_to(root)` gave
(DEF-743: a session that entered a worktree kept `CLAUDE_PROJECT_DIR` at
the root, and both blocking guards covered nothing there). A site that
rejoins the relative path to a directory afterwards -- the hardlink
backstop's stat, post_write_check's read-back and memory prune -- joins it
to the returned base, never to the root. Regression coverage:
`tests/test_write_guard.py::TestPathTraversalBlocked`, the parametrised
case in `tests/test_hooks.py::TestPlanGuard`, and
`tests/test_hooks_worktree_checkouts.py` for the worktree half.

## Protected-Zone Path Spelling-Equivalence (Class-A1)

**What it is:** the friction layer compares a normalised path *string* against
the protected prefixes/files; any spelling the OS treats as the same file but
that differs as a string is a bypass. Eight known spellings (`.//`, env-var `//`,
trailing dot/space, backslash env-var, NTFS `::$DATA`, the traversable
directory stream `dir::$INDEX_ALLOCATION`, a `~`-relative Bash redirect, and
PowerShell's `$env:CLAUDE_PROJECT_DIR` spelling of the repo root, which the
strip did not know until `DEF-716`).

**The fix is one chokepoint, not per-spelling whack-a-mole:** separator-canon
+ `lstrip("/")`-after-each-strip + `expanduser` in
`_hook_utils.normalize_path`/`normalize_bash_path`, and a `_fs_equiv()`
canonicaliser (trailing-dot/space + ADS strip + NFKC/casefold) applied to both
input and set members in `_protected_zones`. The fold is **asymmetric and
fail-closed both ways**: all-component for `_is_protected` (over-protect),
basename-only for `_is_allowed` (never widen the allowlist by folding a forged
directory component).

**Known residuals (friction-layer only; CI still catches a committed write):**
Windows `\\?\`/`\\.\`/UNC device prefixes, bash `${VAR:-default}` parameter
expansion (documented OOS), and 8.3 short names.

Full write-up, the asymmetry rationale, the regression suites, and the re-attack
harness: [`docs/sharp-edges/protected-zone-path-equivalence.md`](sharp-edges/protected-zone-path-equivalence.md).

## Protected-Zone MCP Write Extraction (Class-A2)

**What it is:** an MCP `tool_input` can carry its write target under a
non-canonical key (`output_path`) or nested in a list/dict
(`{batch:{files:[{path}]}}`). The pre-fix branch swept only a finite top-level
field set, so every nested/non-canonical shape bypassed the protected-zone
check (the `{batch:…}` form was a verified live freeze-blocker).

**The fix is one structural move, not more field names:** a key-agnostic,
depth-bounded **leaf-walk** (`_hook_utils.iter_mcp_path_leaves`) over every
string leaf, normalised FS-free (`normalize_path_str`, no `resolve()` in a
loop). A finite key set / finite depth can never cover arbitrary keys +
nesting; the leaf-walk closes all shapes at once and **fails closed** past its
depth/node bounds. `write_guard` walks key-agnostically (security — skips only
`MCP_CONTENT_KEYS` data blobs); `plan_guard` gates on `key in MCP_PATH_FIELDS`
(friction — avoids over-firing on prose).

**Known residuals (friction-layer only; CI still catches a committed write):**
a path used as a *content-key value* or as a *dict key*, and a payload past the
depth/node bound (denied fail-closed).

Full write-up, the severity-matched asymmetry, the regression suites, and the
re-attack harness:
[`docs/sharp-edges/protected-zone-mcp-leaf-walk.md`](sharp-edges/protected-zone-mcp-leaf-walk.md).

## Protected-Zone Symlink Backstop (Class-A3)

**What it is:** a symlink is a two-way blind spot. *Reader:* `plan_guard` read
cc/execution_plan.json with `read_text()`, so a symlinked plan saying
`status=in_progress` opened the PreToolUse mutation gate (N3, freeze-blocker);
`O_NOFOLLOW` then guards only the final component, so a symlinked `cc/` PARENT
also slipped (N3-EXT). *Writer:* symlink creation into a governed zone was
denied only on Bash `ln` (R1 M-1) — MCP verbs, `cp -s`, PowerShell `New-Item
SymbolicLink` fell through.

**The fix:** a shared symlink-refusing reader `_hook_utils.read_text_nofollow(
path, within=root)` (fd-level `O_NOFOLLOW` + ancestor-symlink refusal; fail
closed) routed through `plan_guard` (`_integrity._load_manifest_unlocked` uses
an equivalent inline `is_symlink` + parent-`is_symlink` refusal, not the shared
reader); an allowlist-blind
symlink-linkname deny across **all** creation channels (Bash `ln`/`cp -s`, MCP
verbs, PowerShell), with `_is_protected` now matching the bare governed dir so
`ln -s evil cc` is denied. A related fix: `deny()`
returned a falsy `0`, so a command matching both the symlink and the write check double-printed a second
decision JSON; `deny()` now returns a truthy int-`0` sentinel (`_hook_utils.DENIED`)
so the `if rc:` dispatch short-circuits and exactly one JSON prints (exit 0).

**Known residuals (WRITE-side defense-in-depth only; the reader side is the
decisive, airtight defense; CI catches committed changes):** inline-interpreter
`os.symlink` (documented out-of-scope class); `ln`/`cp` `-t`/`--target-directory`
(the dir is the flag argument — needs a tokenizer, deferred). The common
spellings incl. `--` and multi-source-into-dir ARE caught.

Full write-up, the reader/writer mechanics, and the re-attack harness:
[`docs/sharp-edges/protected-zone-symlink-backstop.md`](sharp-edges/protected-zone-symlink-backstop.md).

## Protected-Zone Hardlink Backstop (Class-A4)

**What it is:** the inode sister of the symlink blind spot. A hardlink aliases
one inode under a second name, so `ln tools/cc/hooks/write_guard.py wg_alias;
echo evil > wg_alias` rewrites the protected file's BYTES while the write lands
on an unprotected path string — `Path.resolve()` cannot follow a hardlink, so the
path-string check is blind to it (R1 M-2). The dangerous positional is the SOURCE
(inverse of the symlink linkname capture), so `_LN_S_RE` does not cover it.

**The fix:** two layers. (1) **Decisive, channel-agnostic** — an inode-aware
write-through deny `_protected_zones.aliases_protected_inode` (target `nlink>=2`
regular file whose `(st_dev,st_ino)` is in the protected-not-allowed set), wired
into `check_write_edit`, `check_bash_for_protected_mutations`,
`check_powershell_for_protected_mutations`, and `check_mcp` canonical fields — fires
however the alias was created. (2) **Early friction** — `ln`/`cp -l`
creation-deny of a protected SOURCE via the `iter_hardlink_operands` tokenizer
(allowlist-AWARE). Fast-paths on `st_nlink<2`; POSIX-only (`getattr st_ino`).

**Known residuals (Part-B write-through is decisive for covered channels; CI
catches committed changes):** inode check is canonical-fields-only, NOT the
unbounded MCP leaf-walk (a nested non-canonical-key alias is the leaf-walk
residual's inode sibling); walk-budget exhaustion FAILS CLOSED but is not
session-reachable (flooding a protected prefix is itself denied); a pre-existing
out-of-session alias is creation-unchecked but write-through-caught; Windows
`st_ino` unreliable → no-op there. The MCP symlink-verb-gate that briefly
suppressed the canonical inode check (a write-semantics tool named
`write_symlink_data`) was found by the re-attack and closed (the inode check now
runs unconditionally on canonical fields). The re-attack ALSO surfaced that the
mutation-path extraction read only `file_path`, but **NotebookEdit carries its
target as `notebook_path`** (confirmed against the CC Agent SDK reference — an
external source, not the code under test) — so every NotebookEdit bypassed the
protected-zone, inode, AND plan-required checks; `write_guard.check_write_edit`
and `plan_guard` both now read `file_path` then `notebook_path`.

Full write-up, both layers, residual reasoning, and the re-attack harness:
[`docs/sharp-edges/protected-zone-hardlink-backstop.md`](sharp-edges/protected-zone-hardlink-backstop.md).

## Malformed / Non-Dict JSON Fail-Open (Class-B)

**What it is:** `data = json.loads(raw); data.get(...)` fails OPEN on valid-JSON-
but-non-dict input (`[]`, `"s"`, `42`, `null`). The value parses, the
`except json.JSONDecodeError` never fires, then `.get` raises `AttributeError`
past that handler → the hook exits 1 → Claude Code fail-opens. It crashed
SessionStart context injection on a `[]` package.json (**N4**), every
`cognitive_blueprint` mutator on a non-dict `latest.json` (**N5**), `cmd_chain`
(**M2**), plus loader-pattern siblings that `return json.loads(...)` raw.

**The fix:** one chokepoint — `tools/cc/_json_safe.load_json_dict_safe` (returns
the parse iff a dict, else a caller-chosen default; collapses every failure
shape) — applied to 10 sites, with 3 observability-preserving sites keeping
inline `json.loads` + an `isinstance(data, dict)` guard. The class is closed by
a regression **gate**: `tests/test_json_dict_safe.py::find_json_fail_opens`
AST-walks `tools/cc` and fails on any `json.loads`/`json.load` dict-dereffed or
returned without an `isinstance(x, dict)` guard (and not routed through the
chokepoint) — earn-the-red-validated, follows `B = A` aliases, flags
`from json import loads`, honours a `# json-dict-safe: ok` pragma. Adding the
chokepoint required registering it in `cli.INIT_TOOL_SCRIPTS` +
`managed_paths.STANDARD_MANAGED_TOOLS` (else fresh `init` → `ModuleNotFoundError`).

Full write-up, the missed-site finds, and known-limits:
[`docs/sharp-edges/malformed-json-fail-open.md`](sharp-edges/malformed-json-fail-open.md).

## `dict.get(key, default)` Returns `None` for a Present-But-Null Key

`d.get("k", "")` returns the default ONLY when `"k"` is **absent**. If `"k"` is
present with value `None` (a JSON `null`, a hand-edited config, a partial write),
`.get` returns `None` — the default is bypassed — and the next
`None.startswith(...)` / `"\n".join([None, …])` / `None + 1` raises. An
`isinstance(container, dict)` guard does **not** catch this: the container is a
valid dict; the *field value* is the wrong type. This is the field-level sibling
of the Class-B container guard above (FAILURE_MODES §10.10).

**Bit us:** `scaffolding_canon.py` signal functions read
`entry.get("description", "").startswith(_SUBAGENT_PREFIX)`; a blueprint entry
`{"description": null}` passes `isinstance(entry, dict)` but crashes on
`None.startswith`. A guard that checks the container type and trusts the
`.get` default misses the field-level gap.

**The fix:** coerce the *value* type, not just guard the container — a typed
reader returning the field as a `str` (`""` for absent / `None` / off-type),
e.g. `_entry_description(e)`. `(e.get("k") or "")` works when an empty default is
semantically safe (note `or` also collapses `0` / `[]` — use `isinstance` when
that distinction matters).

**Proof hint:** assert the signal/reader does not raise on `{"k": None}` and
`{"k": 7}`, not just on a missing key.

## Deleted-Governance-Event Fail-Open (N7)

**What it is:** deleting a whole governance EVENT key from
`.claude/settings.json` (`ConfigChange` / `Stop` / `PreToolUse`) silently
removes a DENY/blocking gate while the hook *files* stay on disk, so every
health signal stays green. `ci_guard`'s kill-switch scan loops
`hooks.items()` — it only sees PRESENT keys, so a DELETED key never enters the
loop; `doctor` never inspected on-disk event→script wiring. The real trigger is
an **approved** harness change (a `HARNESS-UPDATE-APPROVED` settings edit that
accidentally drops a key sails through the protected-path + approval gate).

**The fix:** a completeness oracle on two surfaces, keyed on the N7 mechanism
("the script file stays on disk"). SoT
`harness_config.GOVERNANCE_BLOCKING_HOOKS` (validated against
`CANONICAL_HOOK_WIRING`) maps each blocking hook to its event;
`doctor._check_governance_event_wiring` fails for any gate present on disk but
not **executably** wired under its event; `ci_guard` mirrors the logic inline
(zero-imports) and fails **unconditionally** (approval does not bypass — a
legitimate hook removal updates the SoT instead). The complementary "file
deleted too" case is caught by the pre-existing
PACK_MANIFEST/`run_cc_surface_gate` + protected-path layers.

"Path present" is too weak: a gate can
be dead while its path is bait (no-op command, `type≠command`, stale-copy path,
tool-excluding matcher, a `-c`/`-m` interpreter-flag prefix, a `&&`/`||`/`;`
shell short-circuit, or a malformed/non-dict settings.json).
Statically parsing arbitrary shell is undecidable, so the oracle whitelists the
**one canonical exec form** (`command` a bare python interpreter, `args[0]` the
canonical `tools/cc/hooks/<script>`, matcher `fullmatch`-covers the mutation
tools) and fails CLOSED on everything else — structurally convergent.

Full write-up, earn-the-red, and known-limits (extractor fail-closed,
matcher-neutering out of scope, settings-merge):
[`docs/sharp-edges/deleted-governance-event-fail-open.md`](sharp-edges/deleted-governance-event-fail-open.md).

## Variable-Indirect Bash Expansion (Narrow)

**What it is:** `write_guard.py` runs a `_expand_simple_var_assignments`
pre-pass that inlines literal `VAR=value` bindings on the same command
line before regex extraction. This catches `F=.claude/settings.json;
echo > "$F"` and similar. **The PowerShell tool has its twin since
2026-09-15** (`_expand_simple_ps_var_assignments`, ledger `DEF-801`): the
Windows walk drove `$p='<hook>'; Set-Content -Path $p` and the
`[IO.File]::WriteAllText($p, ...)` spelling ALLOWING while the Bash
spelling denied. The twin runs on the RAW command before the scan pair is
derived, so the masker's same-offset contract survives (both texts derive
from the expanded one). Outside a string it substitutes the bound literal
quotes and all — the .NET arm reads a string literal only, and a bound
literal that is merely mentioned stays a literal the masker blanks; inside
a double-quoted string it interpolates the value, escaped as PowerShell
spells it.

**Both pre-passes are sequential:** each reference takes the most recent
binding BEFORE it, and a later assignment with a computed value unbinds the
name. Until 2026-09-15 the Bash one let the last binding on the line win
for every reference, so `P=<hook>; echo x > $P; P=notes.txt` allowed, and
its `re.sub` replacement raised on a backslash in a value.

**Hard scope boundary:** the expander handles only:
- Bash: any shell name, in any case, bare or behind `export`, `local`,
  `declare`, `typeset` or `readonly` (flags included) — until 2026-09-19 only
  an uppercase name was read, so the lowercase spelling an agent writes most
  was not chased (DEF-847). PowerShell: any name, case-insensitive as the
  shell is, and never a scope-qualified one (`$script:p`, `$env:X`)
- Plain words, single-quoted, or double-quoted-no-`$` values (PowerShell: a
  quoted literal that ENDS the statement — a bare word is a command there)
- Bash: an assignment at a LIVE statement start — the start of the command,
  after `;`, `&&`, `||` or a newline, inside a `{ }` or `( )` group (never a
  `${`/`$(` expansion's brace or paren), or at the head of a program handed to
  `eval` or a shell's `-c` (read in place, so a double-quoted `-c` body binds
  even though the outer shell expands it first: the direction of error is a
  wall). Live means the masker left the anchor standing: a separator, group
  or exec opener inside a quoted argument or a comment binds nothing. A
  binding made in a child scope — a subshell, a command substitution, a
  `-c` program — ends where that scope ends; an `eval` program's stays, as
  it runs in this shell. PowerShell: after `;` or a newline

**An assignment's VALUE is data (2026-09-19, DEF-848).** Bash ends an
assignment word at the first unquoted blank, and the guard now reads it that
way at both of its layers: the command-position grammar
(`_CMD_POS_ENV_ASSIGN`) no longer reads a word inside a quoted value as a
command, and the masker walks the word to its real end and masks each quoted
piece of the value, so a separator inside it is not a statement. A value
stored by a statement with no head is inert in the current shell; a value the
shell goes on to RUN (`eval "$MSG"`, `bash -c "$msg"`, `$CMD`, an interpreter
program the value is expanded into) is read where it runs, through this
pre-pass. The same grammar reads a command after a prefix whose quoted value
holds a blank (`A='a b' <verb> ...`), which no verb arm read before. The
accepted cost, declared in `docs/HOOKS.md` and pinned by
`TestAnAssignmentValueIsReadAsTheShellReadsIt::test_the_declared_limit_stays_a_limit`:
a value the pre-pass cannot read — a command substitution or a `$` reference
inside it, a parameter expansion, an array, a second assignment in one
statement, a value that runs on past its quotes — that is later run through
`eval` or `-c` is not refused unless its own text puts the verb at a command
position; until the grammar fix it was refused when a word came before the
verb, only by the quote-blindness. And a value given to `export`, `local` or
`declare` is that builtin's argument: a separator inside it is still read
as a statement boundary (the builtins are on no masker roster).

**Out of scope, by design:** `$(...)` command substitution,
`${VAR:-default}` parameter expansion, arithmetic, arrays, a second
assignment in one statement (`A=1 B=/`); on PowerShell also concatenation, `-join`, a method call, a
here-string body, a subexpression inside a string, and a reference before
its binding or with none. These remain genuinely unhandled and are
exercised in
`TestVariableIndirectLiteral::test_complex_expansion_remains_out_of_scope`
and `TestPowerShellVariableIndirectLiteral::test_the_declared_limits_stay_limits`
to lock the boundary.

## Catastrophic `rm` hard-deny parses flags + target, it does not regex a fixed order

**What it is:** `write_guard.py`'s catastrophic recursive-delete hard-deny
(`_bash_patterns.has_catastrophic_recursive_rm`) **tokenizes** each `rm`
invocation instead of regex-matching one fixed surface. It fires on recursive
(`-r`/`-R`/`--recursive`), forced or not, in any flag order/spelling — until
2026-09-18 it required force as well, and the unforced spelling at the root,
home or the checkout met no tier at all, though `rm` prompts only for an
unwritable file and only on a terminal, so in an agent's shell it is the same
wipe (DEF-842; the CP-RMRF nudge reads the same threshold, and so does
PowerShell's `Remove-Item -Recurse` without `-Force`, whose TARGET is judged
differently from its force form's: a variable that names the home walls, any
other variable is one nudge, where the force form walls every absolute or
variable target — operator, 2026-09-18) —
against a target that — after the statically-decodable shell transforms — is
catastrophic **by meaning** (`_target_is_catastrophic`, re-tiered 2026-08-24):
the filesystem root, `$HOME` or the repo (or a parent of either), a shallow
system path such as `/etc` or `/usr/local`, or an absolute path with a `..`
step. A bare `*` glob is judged as the directory it expands in, and `$PWD` as
the directory the command runs in (DEF-849, DEF-843, 2026-09-18 -- until then a
leading glob walled wherever it ran, so clearing a build directory from inside
it met the wall) -- but only in a PLAIN command (2026-09-19): statements joined
by `;`, `&&`, `||` or newlines, each run by a command the guard knows hands
nothing to a shell, with no pipe, group, subshell, substitution, heredoc, loop
or program handed to another shell. On the PowerShell tool the relief reaches
the unforced `Remove-Item -Recurse` and the sweeps, not the forced
`Remove-Item -Recurse -Force`, whose bare leading glob walls wherever it runs
-- a declared limit (`DEF-859`; the reader fix is post-cut) pinned by
`tests/test_guard_false_positives.py::TestThePowerShellTierMatchesBash::test_the_glob_relief_is_withheld_from_the_forced_powershell_remove`,
so `*/build` is a nudge on Bash and unforced and a wall forced. In any other command the glob and `$PWD`
wall as they did before, so put a build-directory clean in its own command
(`_relief_applies`; docs/HOOKS.md item 3). A path *inside* the repo or home, or under a temp root,
falls to the CP-RMRF nudge instead. (Until the re-tier the test was "starts with
`/` or `*`", which refused `<repo>/build` and any temp-root path while `rm -rf ~`
fell to the nudge; the deny texts carried that older rule for two weeks after,
DEF-739.) A RELATIVE target is first read from the directory the command runs
in — the payload `cwd`, moved per statement by the command's own `cd` chain,
the same base the protected-write checks use (DEF-509) — and only then judged
by those rules, so `cd .. && rm -rf <repo>` names the repo and `cd / && rm -rf
etc` a shallow system path (DEF-790, 2026-09-13; until then the classifier
answered "relative, the soft tier's" before joining the operand to anything;
`has_catastrophic_recursive_rm` takes the `cwd` and places each delete in its
OWN statement's directories by slice, never by searching the operand's
spelling across the text — the first cut did, and walled `cd / ; ls usr ; cd
~ ; rm -rf usr`, a home-directory target, because `usr` was also mentioned at
`/`). Joined lexically by operator decision: `../scratch`
typed at the root lands beside the repo and stays soft, `../<repo>` lands on
it and is a wall. The PowerShell removal tier asks the same landing before its
ephemeral roster, and the CP-RMRF bump defers on the same reading. A
same-line literal binding (`X=/; rm -rf $X`) is inlined before the wall
judges — the rm tier and the three sweep walls read the text as spelled AND
with the binding inlined, a wall on either (DEF-846; until then only the
nudge fired there). The walls' reading binds a value only when it ends where
its literal ends, and reads a tilde as bash stores it; every other reader
keeps its older reading. Since 2026-09-19 (DEF-847) the pre-pass reads a
lowercase name, a declaration-builtin binding (`export`, `local`, `declare`,
`typeset`, `readonly`), a binding on an earlier line or inside a group, and
one inside a `bash -c` or `eval` body, so each walls as its uppercase
same-line twin does; before, they drew the nudge.
It fires **even under `ESPALIER_MAINTENANCE_MODE`** (safety, not friction).

**Why parse, not regex:** the two literal `BashPatternRecord` regexes
(`rm\s+-rf\s+/`, `rm\s+-rf\s+\*`) only caught the glued `-rf` order against a
bare `/`/`*`. Every other spelling bypassed them yet is a *working* root
delete: `rm -fr /`, `rm -r -f /`,
`rm --recursive --force /`, escaped `rm -rf \/`, quote-spliced `rm -rf '/'etc`,
brace `rm -rf {/bin,/etc}` (multi-group / nested / empty-alt, and ASCII-range
sequences like `rm -rf {.../}etc` → `/etc` on bash 4.0+/zsh), line-continuation
`rm -rf \<newline>/`, and uppercase `RM -rf /` on a case-insensitive FS. The
analysis is *structural*, not enumerative — it asks "can the leading char be
`/`/`*`?" by walking the brace structure, so it is immune to the cartesian
blowup and result-cap-padding evasions that sink an enumerate-then-check
approach (and fails **closed** on an unanalyzably-complex operand). The two
literal regexes are kept as a fail-safe backstop for the irreversible tier.

**Scope boundary (the same wall as the rest of the bash layer):** `$(...)`
command substitution, `${VAR:-default}` parameter expansion, `$'...'` ANSI-C
quoting, and two-step write-then-exec are NOT decoded — statically undecidable.
`rm -rf/` (target glued onto the flag cluster) is a shell *syntax error*, not a
bypass, and is intentionally not denied. Pinned by
`TestCatastrophicRmFlagOrderIndependent` in `tests/test_write_guard.py`.

**Two-tier split (re-tiered 2026-08-24):** this hard-deny owns the catastrophic
targets above (un-bypassable), and `~`/`$HOME` is one of them. Everything else —
a relative target once read from the directory the command runs in (DEF-790),
`$VAR` paths, and any absolute path inside the repo or home or under a temp
root — falls to the CP-RMRF soft speed-bump (deny-once-then-allow), not here. The temp-root carve-out is by location and is outranked by identity (a
repo checked out under `/tmp` is still the repo); an absolute target with a `..`
step is refused rather than resolved, so no carve-out can be escaped by traversal.

## write_guard Blocks Inline Python Mentioning Dangerous Patterns

**What it is:** `write_guard.py` pattern-matches the raw Bash command string,
including any inline Python passed via `-c "..."`. The pattern `rm\s+-rf\s+/`
matches the literal characters anywhere in the command — including inside a
string argument to Python.

**How you hit it:** Running a verification script like
`python -c "assert 'Bash(rm -rf /*)' in denies"` — the substring `rm -rf /`
appears in the Python source and triggers the DENY, even though the Python code
is inspecting a config value, not executing a shell command.

**How to avoid it:** Write verification logic to a temporary `.py` file and
`python verify.py`, or rephrase the inline check to avoid the literal pattern
(e.g., split the string: `'rm -rf' + ' /*'`).

## write_guard Latches Onto Protected Paths in Bash String Literals

**What it is:** `write_guard.py` extracts candidate write-target paths from
the *raw* Bash command via regexes for redirect, `tee`, `cp`/`mv`, `git
restore`/`checkout`, and inline-interpreter source. Any literal protected
path embedded in a string argument — JSON payloads in test probes, heredoc
bodies, `echo` debug output, fixture data — can be latched as if it were
the actual write target.

**How you hit it:** Writing a one-liner test probe that pipes JSON to the
hook for verification. A payload like `'{"tool_name":"Bash","tool_input":
{"command":"echo x | tee --append .claude/settings.json"}}'` contains
`tee --append .claude/settings.json` as a literal substring inside a JSON
string. The bash scanner sees the substring, parses it as a real `tee`
command, and DENIES the *outer* invocation — even though the outer
invocation is just `echo '<JSON>' | python write_guard.py`.

**How to avoid it:**
- Run hook tests via the `tests/test_write_guard.py` `run_bash_guard()`
  fixture (which pipes JSON over stdin without exposing it to a parent
  shell).
- For ad-hoc probes, write the JSON to a temp file under the project's
  build/test temp area and feed it from there — the scanner doesn't
  introspect file contents.
- Or construct the protected-path string at runtime by concatenation
  (`".claude/" + "settings.json"`) so the scanner regexes don't see a
  literal match.

The legitimate invocation form remains unchanged: a bare
`python tools/cc/hooks/write_guard.py` invocation and the
`"$CLAUDE_PROJECT_DIR/tools/cc/hooks/..."` form both pass cleanly. The
trigger is *what's in the command body around the invocation*, not the
invocation itself.

**Two consequences the above understates, both attested 2026-08-17 (four live
instances in one session, all against ordinary work rather than test probes):**

- **It is not limited to JSON probes — any prose payload triggers it.** A
  read-only census `grep`, a `git commit -m` message, a shell comment, a `sed`
  program, and a `--description` argument to `cognitive_blueprint.py record`
  were each denied as protected-zone *writes*. A note whose **body** documents a
  redirect recipe is denied even when its target is `/tmp`. The false deny fired
  on the session's own handoff.
- **The denial silently drops anything bundled into the same call.** A
  `cmd_a; cmd_b` Bash call denied on `cmd_a`'s text never runs `cmd_b`, with no
  separate signal — so a census reads as complete when only its first half ran.
  See `docs/sharp-edges/blocked-bash-call-skips-its-bundled-git-add.md`.

⚠ **The maintenance-mode escape does not cover the whole surface.** The
protected-zone tier *is* bypassed by `ESPALIER_MAINTENANCE_MODE=1`, but the
dangerous-pattern tier dispatches **before** the maintenance gate, so a prose
mention of the harness env var or of the guarded recursive-delete literal is
denied with **no escape at all** — and the protected-zone deny message itself
quotes the maintenance-mode remedy as a markdown code span, so echoing or
grepping the remedy the harness just printed is denied on the tier that remedy
cannot reach. Build such strings inside a Python file and run that file.

## Local Hooks Are Not a Sandbox

**What it is:** Hooks under `tools/cc/hooks/` run inside Claude Code's
process context. A user (or any process with local filesystem control)
who edits `.claude/settings.json` to set `"disableAllHooks": true` before
Claude Code reads that file disables every hook for the upcoming session.
No local hook code runs after that point.

**How you hit it:** Treating any hook event as a security boundary.
SessionStart is explicitly visibility-only per the Claude Code hook
protocol — it can warn, but it cannot block. PreToolUse and ConfigChange
*can* block, but only while they are active. If hooks are disabled before
Claude Code runs them, none of these surfaces fire.

**How to avoid it:** The honest enforcement boundary is one of:
- **CI + branch protection** (`tools/cc/ci_guard.py`) — fails the merge
  on an unapproved protected-path change, and backstops a *force-added*
  kill-switch setting (`.claude/settings.json` is gitignored, so the normal
  path can't commit one — the gitignore is the primary foreclosure).
  This is the only enforcement that does not depend on local hook code.
- **Claude Code managed `policy_settings`** — explicitly non-overridable
  by user/project/local settings. espalier does not ship this; it
  belongs to whoever runs the deployment.

Local hooks raise the cost of casual bypass and provide audit visibility.
They are not, and cannot be, a sandbox. Documentation, agents, and
release notes must not claim otherwise. This rule is enforced by
`tests/test_documented_claims.py::TestNoSessionStartBlocksClaim`.

<!-- espalier:fragment id=ci-trigger-aware-marker
     bound=tools/cc/ci_guard.py::_approval_marker_present
     policy=verify-on-touch -->
## CI Approval Marker — Trust the Trigger, Not the OR

`tools/cc/ci_guard.py` accepts the `HARNESS-UPDATE-APPROVED` marker
from different sources depending on the GitHub Actions trigger:

- **`pull_request` / `pull_request_target` / `merge_group` events:**
  ONLY `env.PR_TITLE`, and only a marker bound to the head under
  review (`HARNESS-UPDATE-APPROVED@<sha>`, see the closed residual
  below). The PR title is logged on the PR timeline and cannot be
  edited by force-pushing commits, so this closes the
  a prior bypass class force-push laundering window where an attacker could rewrite
  HEAD's commit message after a clean review.
- **`push` events (direct-to-main):** ONLY the HEAD commit message.
  `PR_TITLE` is unset for these events. Direct push to main is itself
  gated by GitHub branch protection (out of `ci_guard` scope).
- **`workflow_dispatch` / `repository_dispatch` / `schedule` / unknown
  / empty event:** REFUSE the marker. These triggers have no review
  context; accepting the marker would be unconditional laundering.

**Pre-fix (a prior bypass class active):** the check was a logical OR over
`(head_commit_message, env.PR_TITLE)` regardless of trigger. A PR
author could force-push a new HEAD with the marker text into the
commit message AFTER a clean review and merge protected-zone changes
the reviewer never saw. The trigger-aware allowlist closes this
window.

**Residual, closed 2026-09-11:** the title approved the PR, not a
commit, so a benign PR with an honest title marker, then a force-push
adding protected-zone changes AFTER review, still passed. On PR-like
events the title marker is now BOUND to the head under review:
`HARNESS-UPDATE-APPROVED@<sha>`, a 7-to-40-hex prefix (any case) of
`PR_HEAD_SHA`, which the workflow forwards from
`github.event.pull_request.head.sha`. A force-push changes the head,
so the same title goes red and the message names both heads and the
fragment to paste for the new one; the workflow lists `edited` among
its pull-request activity types so that a title edit re-runs the check
on the same head, or the red could never clear. The bare marker on a
pull request is refused for the same reason. A PR event with no
commit-shaped `PR_HEAD_SHA` fails closed and prints the exact line to
add — and names `harness-guard.yml.new`, because `install-ci` parks a
differing workflow rather than overwriting it. No GitHub API and no
token: whoever binds the title types the seven characters. Push events
still read the commit message, bare or bound — it travels with its
commit, and the posture rule governs that path. The merge-queue head is
forwarded as an alternate, but that event carries no title, so a
protected change in a merge queue denies as it did before.

**What the binding buys, honestly (STANDING_PRINCIPLES §2):** a
pull-request author can edit their own title, so the gate cannot tell
a reviewer's binding from the author's. Green CI after a force-push is
therefore NOT independent evidence that a reviewer approved that head:
it is evidence that someone with title-edit rights re-bound the title
to it, explicitly and on the PR timeline, instead of the force-push
passing silently. Reviewers MUST still re-review any force-push on a
PR that touches protected zones; the binding makes the omission
visible, not impossible.

**Workflow wiring:** `.github/workflows/harness-guard.yml` (generated
from its asset under `espalier/assets/github/workflows/`) exports
`GITHUB_EVENT_NAME` and `PR_HEAD_SHA` explicitly. Actions exposes
`github.event_name` as a context but does not auto-export it to the
environment; the explicit forwards are required for `ci_guard` to read
them via `os.environ`. `tests/test_ci_guard.py` derives every env key
the gate reads and asserts the asset forwards each one.

The regression contracts live at
`tests/test_ci_guard.py::TestApprovalMarkerForcePushResistance` (the
per-event channel and the no-review-context refusal list) and
`tests/test_ci_guard.py::TestApprovalBoundToHead` (the binding, the
force-push red, the refused bare form, the failed-closed missing head).

## Closed-Loop Verification Trap

When implementation, tests, contract tests, and project docs all
agree, the agreement is evidence of internal consistency, not
correctness. If the behavior depends on an external contract,
internal consistency cannot detect a misreading. Pin external
contracts in `docs/external/` and bind tests to those pins, not
to other project docs.

See [sharp-edges/closed-loop-verification-trap.md](sharp-edges/closed-loop-verification-trap.md)
for the full failure mode, sister-class relationships, and a
detection heuristic.

**2026-09-12, the pasteable-remedies lane: two more shapes of the same trap.**
(1) A contract pin keyed on ONE callee name is laundered by an alias. The first
cut of the remedy-interpreter pin walked the AST for `_detect_python_command`
calls, and a `--rewire-interpreter` re-run spelled through
`doctor._resolver_hint()` -- a one-line alias returning the same write answer --
went through green; both reviewers found it. The pin now polices every name that
answers with the write value AND any local bound from one, inside any f-string
that carries `-m espalier`. (2) A test that patches the resolver to a fake name
and asserts the fake in a remedy is green only on a host whose real interpreter
clears the floor: once the remedy reads a seam that probes the floor, the fake
fails it and the running interpreter is substituted, so the test was pinning
this Mac, not the contract. Patch the seam the code reads
(`cli._remedy_interpreter`), never the resolver it wraps. Both carry the trap's
signature: the oracle and the subject share a source of truth, so their
agreement proves nothing.


## A rendered test-failure frame is not a test result

A `FAILED ...` line in scrolled or batched tool output is **display, not a result.** The Claude Code tool-I/O channel can intermittently render a wedged, stale, or phantom frame — reporting a failure that never happened (and, rarely, a phantom *pass*). Only a cleanly-captured process **exit code** is a test result. This is an upstream Claude Code *runtime* behavior, not a harness logic gap.

**Red/green asymmetry (load-bearing).** A phantom *red* costs operator time but can never become drift — there is nothing real to build on. A phantom *green* is the dangerous case, and it is caught by CI / committed contracts regardless. So the rule is directional: **never *dismiss* a red as "probably phantom" and move on; *re-derive* it** via an independent out-of-band oracle — re-run the failing node, capture output to a file, and read the exit code through a second path — then act on the re-derived result. If you cannot re-derive it, treat it as real and stop.

**Do not let isolation override aggregate.** A test that fails in the full suite but passes when run alone is the textbook signature of a real order-dependent / shared-fixture / import-coupling bug — exactly the class this repo cares about. Treat an isolation/aggregate *mismatch* as its own stop condition ("investigate flaky/order-dependent or phantom"), never as proof the failure was phantom.

This is a **convention** (an operator habit), not a mechanical gate — a runtime that can fabricate a `FAILED` frame can equally mis-render that a prose precondition was followed. The mechanical Stop-event gate (`tools/cc/hooks/stop_gate.py` Gate 1) already adjudicates on a cleanly-captured subprocess exit code and is *not* phantom-vulnerable; an out-of-band `tools/cc/confirm_test_failure.py` helper (reading the captured exit code) is the only path to binding the in-loop case, and is deferred until phantom-reds recur often enough to justify it.

This is the same independent-witness instinct the harness already embodies (dual-witness denylist, byte-equality, AST-over-substring), applied to the tool channel itself: never let a producer validate its own output.

## Canon Must Read Raw Artifact; Cannot Import the Producer

A quality canon that imports any module participating in the
producer surface it intends to measure becomes closed-loop with
that producer. For Espalier's `/reflect` walker, the producer
modules are `espalier.reflect_protocol`,
`espalier.reflection`, `espalier.models` (ReflectPass dataclass),
`espalier.cognitive_blueprint` (writes `gap_convergence`), and
transitively `espalier.cli` + `espalier.doctor` (top-level imports
of the walker chain).

A canon module that wants to measure scaffolding quality must
read the producer's persisted artifacts (`cc/blueprints/*.json`)
directly via stdlib `json.load`, never through the producer's
loaders or dataclasses. The de-circularization contract is
pinned by an AST walk over the canon source asserting zero
imports from the forbidden set, with a negative-proof
sub-assertion (`test_negative_proof_check_fires`) confirming the
walker would catch a regression — without the negative-proof,
the positive test could pass for the wrong reason
(`FORBIDDEN_IMPORTS` emptied, wrong AST node type checked, etc.).

Sister-site: any hook-side twin under
`tools/cc/scaffolding_canon.py` needs the analogous
`tools.cc.*` forbidden set
(`tools.cc.reflect_protocol`, `tools.cc.cognitive_blueprint`,
`tools.cc.hooks.reflect_trigger`). a prior fix does NOT create the
hook-side twin — the canon runs offline via the CLI, not as a
hook.

Reference: `espalier/scaffolding_canon.py`,
`tests/test_scaffolding_canon.py`, `docs/CONVENTIONS.md`
"Scaffolding-quality canon".


## Tests Against the Live Self-Host Surface Need an Initialized Repo

**What it is:** Tests that call `surface_contract.discover_wired_hooks(...)`, `espalier doctor .`, or `scripts/release_check.py` against a target directory depend on `.claude/settings.json` and `reports/*.json` being present on disk. Those files are gitignored — they are runtime artifacts produced by `espalier init`. A fresh clone does not have them; CI does not have them; the release archive does not have them.

**How you hit it:** Writing a new test that uses `REPO_ROOT` and calls one of those functions. Locally the test passes because Mike's tree has been initialized. CI fails on the same test against a fresh checkout. Symptom: `discover_wired_hooks(REPO_ROOT)` returns `[]`, the doctor CLI exits with `status: fail`, `release_check.py` returns 1, and the harness-status `healthy` assertion misses.

**How to avoid it:** Use the `initialized_repo_root` session-scoped fixture from `tests/conftest.py`, not `REPO_ROOT`, when the test's intent is "doctor / release_check / surface_contract correctly read a properly initialized harness." The fixture clones REPO_ROOT into a tmp directory and runs `espalier init` against the copy so the runtime artifacts exist. Reserve `REPO_ROOT` for tests whose intent really is "this must hold of the source tree as committed" (e.g., `pyproject.toml` version truth, no tracked release noise, exact count of committed agent/command `.md` files).

**The counterpart trap — do NOT use it for an adopter-facing question.** The fixture clones
*this repo* and then runs `init` over the copy. Seeds are skip-if-exists, so the self-host
`docs/SHARP_EDGES.md` (4,295 lines) and `docs/CONVENTIONS.md` (1,999) survive and the Tier-3
**stubs an adopter actually receives are never written**. Any test asking "what does a stranger
get?" — does this pointer resolve, does this section exist, does this doc ship — passes on that
tree for the one reason that proves nothing: our own content was already sitting there. That is a
born-weak gate, and it hid 55 dead pointers until a gate resolved them against a **foreign** repo
with `init` driven onto it (`tests/_adopter_tree.py`, `tests/test_adopter_pointer_resolution.py`).
Rule of thumb: `initialized_repo_root` answers *"the self-host surface behaves"*;
`adopter_tree` answers *"what does a stranger get"*. They are not interchangeable, and the second
question is the one that silently passes on the wrong tree.


## Transition-Friendly Relaxation Followed by Tightening Strands Test Fixtures

**What it is:** When a contract function (e.g., `is_self_host_repo`) is *temporarily* relaxed to accept both legacy and new identifiers during a rename — and then tightened back to single-canonical at the end — any test fixture that quietly uses an in-between form is left stranded. The fixture passes during the relaxed window, then fails silently or with a misleading assertion when tightened.

**How you hit it:** the espalier-harness rename demonstrated this in practice. Phase A relaxed `is_self_host_repo` to accept `{cc-builder, espalier-harness, espalier}` so mid-pack test runs would stay green. Phase F tightened it to `{espalier-harness, espalier_harness}` only. Two test fixtures (`tests/test_pre_release.py`, `tests/test_diffing.py`) used `name = "espalier"` (the bare-package form, never an actual project name). They passed during the relaxed window. After tightening, those tests took a different code path through the gate and surfaced unrelated failures (`missing required file: SECURITY.md`) — the diagnostic message hid the real cause.

**How to avoid it:** When tightening a relaxed contract function, grep test fixtures for *every* variant the relaxed form accepted, not just the canonical one. Fix any fixture using a non-canonical form before the tightening lands. Alternatively, never relax the contract — apply the rename atomically across fixtures and contract in the same commit. The relaxation is a debt; tightening is the deadline.


## New Test Files Default to `unit` Silently

**What it is:** `tests/conftest.py::pytest_collection_modifyitems` assigns markers via `_MARKER_RULES` — a list of `(filename_patterns, marker)` tuples. Any test file whose stem does not match any entry silently receives the `unit` marker.

**How you hit it:** Adding `tests/test_release_noise.py` without adding its stem to `_MARKER_RULES`. The file runs with every `pytest -m unit` invocation and is invisible to `pytest -m release`. `tests/test_test_suite_contract.py::test_every_test_file_matches_a_marker_rule_or_defaults_to_unit` catches filenames that *look* like a non-unit category but are not registered.

**How to avoid it:** After adding a new test file, check whether its name pattern signals a non-`unit` category (hooks, security, release, contract, integration, slow). If so, add the stem to the matching tuple in `_MARKER_RULES` in `tests/conftest.py`. See `tests/README.md` for the taxonomy.

**⚠ Measured 2026-08-24: the `unit` slice did not do what its own description said — now enforced.** Because `unit` was the `for/else` fall-through rather than a curated set, `pyproject.toml`'s description of it — *"pure function/model tests; no subprocess, no filesystem-heavy work"* — was a claim nothing verified. Driven: `-m unit` ran **slower per test than the entire suite**, and roughly a third of the modules in the bucket spawned child processes, which the first clause of that very sentence forbids. `test_marker_taxonomy` enforced that every file is *deliberately* classified, but `# pytest-marker: default-unit` opted a file into `unit` whatever it did — so the guard secured deliberateness and not accuracy. With `EXPECTED_GRANDFATHER_CEILING` sitting at the live count with zero headroom, that reason-free comment had become the only route into the bucket. This matters beyond tidiness: the full suite is the honest gate at ~14 minutes, and a gate with no credible cheap precursor is one sessions route around — `382f725` shipped two broken contracts from a session run with `ESPALIER_STOP_GATE=light`.

**What closed it.** Two structural contracts in `tests/test_test_suite_contract.py`, each deriving its own population rather than checking a hand-written copy of it. `test_no_unit_module_spawns_a_child_process` answers clause 1 by reusing the `_module_spawns_child` AST detector that already lived in that file, resolving the marker through `tests/conftest.py`'s `_primary_marker` — the *same* function the collection hook calls, so the contract cannot answer a question the live dispatch would answer differently. `test_every_self_declared_slow_site_is_slow_or_exempt` answers clause 2 by asking each module what it declared about itself: a site that raises its own `pytest.mark.timeout` above pyproject's global ceiling has written down that it is heavy, and until now nothing read that. That second one is a **floor, not a fence**, and the docs say so: it enforces *self-declared-heavy implies marked slow*, which is strictly weaker than the clause it serves. A module that walks the tree in-process and never raises its timeout still passes — the census was findable only because its author happened to raise one. The offenders moved to `integration`, which is what the taxonomy always called them.

**The mechanism deliberately NOT taken.** The recorded proposal was a per-test duration cap. Wall-clock assertions have two false-fail incidents on record in this repo — `tests/README.md` records perf budgets that *"false-fail on scheduler wait, not on a real regression"* under `-n auto`, and `tests/test_derived_population_census.py`'s own timeout note records that module redding on a **clean tree** because a parallel-agent review round loaded the box. Neither new contract asserts a wall-clock number, and neither can. A gate that reds for load rather than for truth is one the reader learns to skip, and a skipped gate is worse than no gate: it still reads as enforcement.

**Three things only the measurement showed, each of which would have made the obvious fix wrong.** (a) Two of the three files the original diagnosis named were *already* in `_SLOW_FILES`; the slice anything mechanical runs is `-m "not slow"`, and only `tests/test_derived_population_census.py` leaked into it — at roughly a quarter of it, because it `exec_module`s the census script and walks the tree **in-process**, which the subprocess detector is structurally blind to. (b) A file-granular version of the timeout contract false-positived `tests/test_final_release_matrix.py`, whose one heavy test is `@pytest.mark.slow` **inline**; shipping it would have dragged that module's cheap siblings out of the pull-request slice — a coverage loss wearing a speed fix's clothes. Slowness is declared at two granularities, and a contract that knows only one is worse than none. (c) The census module's own opt-out sat **inside its module docstring**, so it was never a comment and never a real opt-out — `test_marker_taxonomy`'s substring check had been forgiving it on the strength of prose. That is the mention-versus-use class again — a matcher keyed on spelling where the question is role — and the fix is the same one it always is: ask the tokenizer, which knows a comment from a string, instead of asking `in`.

## `ESPALIER_STOP_GATE=full` Exported in Shell RC Runs Pytest on Every Turn

**What it is:** `stop_gate.py` reads `ESPALIER_STOP_GATE` from the environment on every Stop event. Stop fires at the end of every Claude Code turn, not just at end-of-session. If `full` is exported in your shell rc (`.zshrc`, `.bashrc`), Gate 1 (`pytest tests/test_fingerprint.py tests/test_hooks.py tests/test_scanners.py tests/test_scanner_magic_depth.py -q`) runs on every turn.

**How you hit it:** Following the SHARP_EDGES "opt in" instruction and adding `export ESPALIER_STOP_GATE=full` to your shell rc — then forgetting about it. Every subsequent turn incurs a full pytest run, making the harness noticeably slow for ordinary edits.

**How to avoid it:** Prefer setting the var for a bounded shell session (`ESPALIER_STOP_GATE=full`) rather than exporting it permanently. Or use `.claude/settings.json` under `env` so it's scoped to Claude Code only, not every terminal process.

## `ESPALIER_MAINTENANCE_MODE` Must Be Set Before Launch

**What it is:** `ESPALIER_MAINTENANCE_MODE=1` relaxes friction-only hook checks (`write_guard` protected zones, `plan_guard` plan requirement, `stop_gate` gates 2/3, `subagent_stop` blueprint append) for legitimate harness self-edits. Hooks read it via `os.environ.get` on every invocation. Hook subprocesses inherit env from the Claude Code process, which inherits from its launch shell.

**How you hit it:** Running `export ESPALIER_MAINTENANCE_MODE=1` in a Claude Code Bash tool call mid-session and then expecting the next Write to a protected path to succeed. The export modifies the Bash subprocess env only. The already-running Claude Code process is unchanged, so hook subprocesses spawned by it still see the var unset. The write is denied. Asking Claude to "set the flag" produces the same result for the same reason.

**How to avoid it:** Quit Claude Code and relaunch with the var set in the
parent shell (`--continue` keeps the session you were denied in):

```text
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude --continue
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue
cmd.exe:                 set ESPALIER_MAINTENANCE_MODE=1 && claude --continue
```

For a session-wide opt-in across both maintenance and operator workflows, put it in your shell rc — but treat it like `ESPALIER_STOP_GATE=full`: the relaxation is a debt, easy to forget, and makes the friction layer silent. Prefer per-launch opt-in. The bypass logs `[<hook>] MAINTENANCE_MODE — <action>` to stderr on every fire so the use is observable; if you stop seeing those lines mid-session, the flag isn't propagating.

## Harness env-var prefix in Bash tool body is denied

**What it is:** `write_guard.py` denies *some* Bash tool calls that inline-assign `ESPALIER_MAINTENANCE_MODE` or `ESPALIER_STOP_GATE`. Two different things are refused, for two different reasons, and this entry previously conflated them:

1. **Inert forms** — a bare `VAR=1`, `export`/`declare -x`, or `VAR=1 && cmd` / `VAR=1 ; cmd` where the variable is not passed past the separator. Nothing is reached. Friction against habit-formation.
2. **`VAR=1 claude …`** — a REAL reach, and the reason `bench/corpus/BC-028` treats this as a bypass class. It starts a NESTED session with the protected-zone check already bypassed, so an in-session actor can spawn an ungoverned agent to edit the files this hook protects. Matched by basename token scan, so wrappers (`npx`, `nohup`, `exec`, `env`, `command`, `time`, `xargs`, `sh -c`, `$(which claude)`) and case variants are covered too — `CLAUDE` resolves to the same binary on a case-insensitive filesystem.

⚠ **CORRECTION (2026-08-23).** This entry used to assert the prefix "is INERT for governance bypass anyway … so the block has no functional cost — only pedagogical value." **That is false for case 2**, and believing it is what nearly removed the guard: reading the deny as pure pedagogy makes carving out `claude` look obviously right.

**How you hit it:** `ESPALIER_MAINTENANCE_MODE=1` on its own, or launching the agent binary with it. What is **allowed**, and used to be denied: `VAR=1 pytest -q` and `VAR=1 python <hook>` — the variable genuinely reaches that process and loosens nothing, because the write_guard decision for the tool call is already made before the command runs. Denying those blocked the canonical maintenance loop (edit a hook, then run it to see whether the edit worked), and the suite never noticed because its tests pass an env dict to `subprocess` rather than writing the prefix.

**Refinement (command position, not mere presence):** The deny now requires the env-assignment to sit at a *command position* — start-of-line, after a separator (`;` `&` `|` newline `(` `{` backtick), behind an `env`/`sudo` prefix (including `/usr/bin/env`, `env -i`, and a chained `ENV=x VAR=1`), or inside a non-obfuscated `$(...)`/backtick substitution. The same literal sitting inside a *quoted argument* — a commit message, or a `--description "...ESPALIER_MAINTENANCE_MODE=1..."` — is data, not a prefix, and is no longer denied. (The bare-`\b` form false-positived on it, blocking the legitimate documentation of this very footgun.) The new regex is a strict *narrowing* (every form it still denies, the old `\b` form denied too — proven over 300k fuzzed strings), and it uses horizontal-only `[ \t]` anchors so a pasted multi-line body cannot trigger catastrophic backtracking (the naive anchor took ~26 s on a 50k-newline body; the landed form is ~20 ms). Pinned by `tests/test_hooks.py::TestWriteGuardBashPatterns` (both-direction earn-the-red + a ReDoS timing guard) and `tests/test_write_guard_pattern_message_coupling.py` (regex-source fixture).

**Why the inert half is still blocked:** The syntax teaches the wrong mental model. Operators internalize "inline prefix changes maintenance state for this run" and end up baking the pattern into committed scripts where it then fails silently. That half is friction against habit-formation, not against adversaries — but do not generalize it to the `claude` arm, which is the anti-self-disable property and not pedagogy at all.

⚠ **The reusable trap.** The deny message prescribes `ESPALIER_MAINTENANCE_MODE=1 claude --continue` (the PowerShell form on Windows) as the relaunch, so the guard refusing that exact string reads as self-contradiction. It is not: that advice is for the **operator at their own terminal**, where no hook is watching; the same text typed as a Bash tool call is an in-session actor. **A deny whose remedy looks self-contradictory may be distinguishing WHO is acting, not contradicting itself.** Review did not catch the regression this misreading caused — the release-gating benchmark did, dropping 153/153 to 150/153.

**Acknowledged limitation (documented bypass classes):** The command-position regex is still bypassable by *obfuscated* Bash shell expansion where the literal token never appears in the raw string — `$'\x45SPALIER_MAINTENANCE_MODE=1 ...'` (hex-escape decoded after the regex scan), `X=ESPALIER_MAINTENANCE_MODE; eval "${X}=1 ..."` (variable indirection), `eval $(echo ...)` (token reconstructed inside the substitution). A *non-obfuscated* `$(ESPALIER_STOP_GATE=full ...)` whose token is present stays denied (the command-substitution opener is a command-position boundary). Closing the obfuscated class requires Bash tokenization/AST analysis (out of scope). The defense remains useful as friction against the habit-formation case; motivated bypass falls into the generic-shell-expansion class documented in `bench/corpus/`.

**How to avoid it:** To run a single command under the var, just prefix it — `ESPALIER_MAINTENANCE_MODE=1 pytest -q` is allowed and works. To change **this** session, exit and relaunch from your own shell with `ESPALIER_MAINTENANCE_MODE=1 claude --continue` (PowerShell: `$env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue`); that is the one spelling the guard cannot let a tool call make on your behalf.

**Known remaining gap:** the obfuscated class below is unchanged, and closing the `export`/`declare -x` detour only closes the literal spellings — `bash -c 'export …; claude'` reconstructs the reach one level down. This is a friction layer, not a sandbox (`docs/STANDING_PRINCIPLES.md` §2); `.github/workflows/harness-guard.yml` remains the enforcement tier.

## Subprocesses Inheriting CLAUDE_PROJECT_DIR Mis-Route Harness Scripts

**What it is:** `tools/cc/cognitive_blueprint._repo_root()` reads `CLAUDE_PROJECT_DIR` from the environment before falling back to cwd. Claude Code always exports that var to the real repo root for every subprocess it spawns. So any test or helper that runs `cognitive_blueprint.py` (or any tools/cc/ script using the same resolver) with `cwd=<some-other-path>` but no `env=` override silently routes the script at the leaked CLAUDE_PROJECT_DIR, not the intended path. Reads return the wrong blueprint; writes land in the wrong repo.

**How you hit it:**
- **Tests:** `subprocess.run([sys.executable, ".../cognitive_blueprint.py", "start"], cwd=tmp_path, capture_output=True)` — looks self-contained but isn't. Two known instances of this pattern in `tests/test_hooks.py` failed only when the operator's shell exported `ESPALIER_STOP_GATE=full` (making the Stop hook run the suite) — they had been latent since the initial commit.
- **`tests/test_hooks.py::run_hook`:** copied `os.environ` unconditionally, so passing `{"CLAUDE_PROJECT_DIR": <tmp_path>}` worked, but there was no way to *unset* an inherited var. `test_default_mode_skips_pytest` couldn't model "no `ESPALIER_STOP_GATE` set" while the operator's shell exported it.
- **Production:** `tools/cc/session_resume.py::_blueprint_summary` and `_start_session` had the same shape. Calling `session_resume.py --mode normal /target/repo` while `CLAUDE_PROJECT_DIR=/other/repo` was set would START a new blueprint in `/other/repo`, not `/target/repo`. Rare in practice (operators almost always invoke `/context-load` against the current repo) but a real production correctness gap, not just a test fragility.

**How to avoid it:** Every test subprocess invoking a tools/cc/ script that uses `_repo_root()` must pass `env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}`. Every production helper invoking the same scripts on a chosen path must pass `env={**os.environ, "CLAUDE_PROJECT_DIR": str(chosen_root)}`. For tests that need to assert "no harness env var set" (the `ESPALIER_STOP_GATE=full` exported-in-shell-rc case), `run_hook()` now treats `None` as "delete this var from the subprocess env."

**Sites pinned by `tests/test_subprocess_env_isolation.py`:**
- `TestSessionResumeRoutingIsolation` — `session_resume.py --mode normal <path>` reads the blueprint at `<path>`, not at the leaked `CLAUDE_PROJECT_DIR`; `--mode normal` does not leak a new-blueprint write to the sentinel.
- `TestRunHookEnvOverrides` — `run_hook(env_overrides={"X": None})` deletes `X` from the subprocess env; `run_hook(env_overrides={"X": "y"})` sets it. The contract that makes `test_default_mode_skips_pytest` robust to operator shell-rc exports.

**Audit scope:** `tests/test_cognitive_blueprint.py` and `tests/test_cognitive_blueprint_schema_parity.py` are clean (every subprocess passes `env=` with explicit `CLAUDE_PROJECT_DIR`). `tests/test_session_resume.py` tests pass under contamination only because their assertions are weak (`"REPO:" in stdout`, `returncode == 0`); the underlying production bug they masked is now fixed.

## A one-shot `claude -p` has no loop to resume into — never background a gate

**What it is:** A one-shot `claude -p` invocation (no interactive session, no `/loop`) has no future turn to resume into. The moment the agent backgrounds a task and yields to wait on it — Monitor, ScheduleWakeup, or a background Workflow, the reflex carried over from interactive/loop mode — the session ends with a clean exit 0. Anything deferred, including the commit, is silently lost: the run "succeeds" yet HEAD never moved.

**How you hit it:** Running the autonomous driver (`scripts/run_pack_chain.sh`) or any unattended `claude -p` goal that says "run the full suite, then commit" — and the agent runs the suite as a background fan-out, expecting to read its result "next turn." There is no next turn. The first driver pilot did all the work, backgrounded the final suite, and exited 0 with nothing committed.

**How to avoid it:** In a one-shot `-p`, run EVERY gate (full suite, audit, fan-out) synchronously in the foreground and read its result in the SAME turn; carry through to the commit in one continuous run. Never background / Monitor / ScheduleWakeup / Workflow in `-p`. Defense in depth: the driver independently verifies the commit exists (`git log`) before advancing, so an exit-0-with-no-commit halts the chain instead of compounding. See `docs/AUTONOMOUS_EXECUTION.md` and FAILURE_MODES §7.9.

## `pipefail` + `grep -q` is a SIGPIPE race — capture-then-grep

**What it is:** Under `set -o pipefail`, a `cmd | grep -q PAT` check can intermittently false-fail. `grep -q` exits and closes the pipe on its first match while `cmd` is still writing; `cmd` then takes SIGPIPE (exit 141) and `pipefail` propagates the non-zero — so a check that *found* its pattern reports failure. It is time-of-write-dependent: a small output "wins the race" in a manual repro, a larger one loses it at runtime.

**How you hit it:** The driver's commit-verify was `git log --oneline -8 | grep -qi "$pack"` under `pipefail`. It passed in hand-testing and intermittently halted the chain at runtime even though the commit existed. The "timing" theory was disproved by reading the commit *timestamps* (the commit predated the check) — an untrusted-oracle move: the rendered "no match" was the unreliable frame.

**How to avoid it:** Drop the pipeline. Capture-then-grep via a here-string: `grep -qi "$pack" <<<"$(git log --oneline -8)"` — there is no pipeline, so `pipefail` cannot trip it (deterministic across re-tests). General rule: never put a short-circuiting consumer (`grep -q`, `head`) downstream of a still-writing producer under `pipefail`. See FAILURE_MODES §7.6.

**The sibling that bites without `pipefail` at all — a piped gate reports the WRONG COMMAND'S verdict.** `pytest -q | tail -25` exits with **`tail`'s** status, which is essentially always 0. The suite's own result is discarded before anyone reads it. This is not a race and needs no special shell option; it is just what a pipeline's exit status means.

⚠ **Measured 2026-08-18: this produced two consecutive false "green" reports in one session on a suite that was genuinely RED**, and the harness's own background-task notification repeated the same false `exit code 0` — because that notification also describes the *last* command in the chain. Two independent surfaces agreeing did not make it true; they were both reading the same wrong number. Assume the gate's own summary line looks fine too: `pytest -q` prints its `1 failed, N passed` tail whether you captured the status or not, so a skim of the output is not a substitute.

**Do this instead** — redirect, then read `$?` on its own line, and only then look at the text:

```bash
python -m pytest -q > pytest.log 2>&1; echo "PYTEST_RC=$?"; tail -3 pytest.log
```

Applies to every gate, not just pytest: `ruff`, `espalier audit`, a driver script. **Never read a chained command's exit code — including a background-task notification's — as the verdict of a command that was not last in the chain.**

⚠ **Recurred 2026-08-31, twice in one day, with this entry already written.** The same
rule above was in the catalog when `scope-check` and `sister_site_probe` were both read
as `rc=0` through a `| tail` — **both had exited 2.** The running total of false `exit
code 0` reports from background-task notifications reached **13**. The prescription in
this entry was never applied; knowing the rule and holding it at the keyboard are
different things. Read that as the argument for a mechanical check (a wrapper, a hook)
rather than for a fourth paragraph here — see FAILURE_MODES §5.22, "Documented is not
prevented."

⚠ **Recurred again 2026-09-03 and 2026-09-04 — two and then two more false `exit
code 0` notifications, running total 17 (the 09-03 session logged five wrong exit codes,
of which two were false zeros) — and the standard guard was blind too.**
`grep -c '^FAILED' pytest.log` returned **0 on a genuinely red log** because pytest was
writing colour: every `FAILED` line carried an ANSI prefix, so the anchored grep matched
nothing — the same defect as `f99aecc` fixed in code, hit by hand within the hour. Read a
suite log only after stripping colour, or better, never let colour in:

```bash
env -u FORCE_COLOR -u PY_COLORS NO_COLOR=1 python -m pytest -q > pytest.log 2>&1; echo "PYTEST_EXIT=$?" >> pytest.log
tr -d '\033' < pytest.log | sed 's/\[[0-9;]*m//g' | grep -cE '^(FAILED|ERROR) '; tail -1 pytest.log
```

`FORCE_COLOR=0` does **not** disable colour — pytest tests the variable's truthiness and
`"0"` is truthy, so on its own it forces colour ON (measured: 9 escape bytes and a
`grep -c` of 0 on a red log). Unset it, as `scripts/verify_pins.py` does; `NO_COLOR=1`
is checked first and wins only while it is present. The `PYTEST_EXIT` line the wrapper
wrote is the verdict; the grep is the diagnosis. A background-task notification is
neither.

## zsh does not word-split an unquoted parameter — a bash-idiom loop silently processes ONE item

**What it is:** in bash, `for p in $LIST` splits `$LIST` on whitespace into N words. **zsh does
not.** An unquoted scalar expands to a *single* word, so the loop body runs exactly once with the
entire string as its argument. `rm -- $LIST` in zsh is a request to delete one file whose name
contains spaces. Nothing errors; the loop simply does a fraction of the work and reports success.

**Why it matters here:** this repo's shell is **zsh** (see the SessionStart host line), while
almost every shell idiom in circulation — and in docs, packs, and AI-suggested snippets — is
written to bash's splitting rules. A bulk mutation authored as a bash one-liner will under-apply
silently. It was hit live on 2026-08-31 with `for p in $SETS`, and again on 2026-09-12 with
`git add $FILES` in a lane-split commit: git saw ONE pathspec and errored, the `set -e` chain did
not stop, the first commit carried three split hunks and `git add -u` swept the other seventy
files into the second. Recovered with `git reset --soft <base>` and redone under a `bash <<'EOF'`
heredoc; the post-condition to read before any commit is `git diff --cached --stat`.

**How to avoid it:**
- Iterate an **array**, not a scalar: `for p in "${(@f)LIST}"` (zsh) or build a real array.
- Or force the split explicitly: `for p in ${=LIST}` (zsh `SH_WORD_SPLIT` for one expansion).
- Or avoid the shell entirely for any multi-item mutation — a short `python -` heredoc has
  unambiguous iteration semantics on every platform, and this repo already prefers it.
- **Re-assert the post-condition after any bulk mutation.** A loop that ran once and a loop that
  ran N times produce the same exit code; only a count distinguishes them. This is the shell
  instance of FAILURE_MODES §5.22 — the output cannot tell you how much of the set it covered.

**The glob twin (2026-09-18).** zsh does not glob-expand a pattern held in a parameter either
(`GLOB_SUBST` is off): `ls somedir/$p` with `p='notes-*.md'` looks for a file literally named
`notes-*.md`, fails, and reads as "absent". Four files that sat in the directory were briefly
reported as moved out of it that way. When the pattern lives in a variable, use `find`, a
`pathlib` glob, or zsh's one-expansion `${~p}` -- and treat an "absent" from a shell glob as a
claim until something else confirms it.

**The general shape:** a portability assumption that fails *quietly and partially*. It does not
error, it does not warn, and the transcript looks like success. Compare the `python3` vs bare
`python` split already documented in this repo — same class, louder failure.

## Two operator-doc contracts can collide on one line — satisfying one breaks the other

**What it is:** several independent gates run over the same tracked docs, constraining different
properties of the *same characters*. A line can be legal under one and illegal under another, so a
fix aimed at one gate hands a violation to a second.

**Measured 2026-08-18.** A shell example in this file invoked the interpreter as `python3` and
redirected into the POSIX temp directory. `test_operator_docs_no_unix_only_default_workflows`
rejects both — it forbids `python3` followed by a space, and the temp path with its trailing
separator, because Windows hosts ship neither. Dropping the temp-directory prefix satisfied that
gate and left the redirect target as a bare filename **beginning with the word `suite`**, directly
after `tail -` and a digit. The release gate's count-claim extractor reads that digit-then-noun
adjacency as a claim about the test suite's size, compared it against the live figure (6028), and
`docs_count_claims` FAILed — reddening five tests across `test_release_check`,
`test_release_check_tp37_semantics` and `test_demo_end_to_end`. The directory prefix had been the
only thing keeping the numeral and the noun apart.

**Why it bites:** the two gates live in different files, neither names the other, and the second
fires through `scripts/release_check.py` rather than a doc test — so the failure surfaces far from
the edit, in suites whose names mention neither docs nor portability.

⚠ **This entry cannot quote its own counter-examples, and that is the tell.** The first draft
pasted the offending line in verbatim to illustrate it, and thereby committed *both* violations
inside the section warning against them — caught only by re-running the real gates. A doc that
documents a forbidden string generally cannot contain it; build such a string from fragments at
runtime, or describe it.

**Do this:** after editing any tracked operator doc, check the candidate line against *both* the
token list in `tests/test_portability_contract.py` and the seven audited nouns behind
`docs_count_claims` (`agents`, `commands`, `helpers`, `checks`, `bypass classes`, `hook scripts`,
and the test-suite noun), built by `espalier.surface_contract.make_count_claim_regex`. A filename,
flag value or version string sitting next to a numeral is enough to manufacture a claim:

```python
from espalier.surface_contract import make_count_claim_regex as mk
mk(r"(?:test\s+)?suite").search(your_line)   # None == safe
```

**Do not** verify with the targeted tests alone. Five tests passed on the repaired line while the
full suite was red; only a whole-suite run showed it.

A number *word* manufactures the claim as readily as a digit: a freshness sentence in this very
file, saying that a comparison stands down, put the word for a single unit directly before the
audited noun, and the gate read it as a claim about the release gate's size (2026-09-12; this
paragraph's first draft quoted the sentence and failed the same gate). Beside any of the seven
nouns, write the noun without a count or the count without the noun; the repair named the
thing standing down instead of counting it.

## An autonomous gate's green is env-relative — pin the install env

**What it is:** "The full suite is green" is not a portable fact. PYTHONPATH-green ≠ plain-green ≠ install-green ≠ CI-green. An unattended agent running the suite in a dev shell with a stale editable install (a `.pth` pointing at a moved/deleted path) can only satisfy the gate with `PYTHONPATH=repo`, which masks real reds that require a true install (e.g. the `selfcheck` subprocess tests).

**How you hit it:** An autonomous `-p` run reports "full suite green, committed" — but plain `pytest` (no `PYTHONPATH` help) is red, and so is a fresh `pip install`. The green was an artifact of the dev shell's broken install state, not the committed code.

**How to avoid it:** Pin the gate's env — build a clean venv, `pip install` the tree, and run the install-green oracle there (`scripts/run_pack_chain.sh::verify_install_green`). One subtlety verified while building that gate: re-running the *full pytest suite* in the venv is NOT sufficient, because `pythonpath = ["."]` in `pyproject.toml` keeps the source tree on `sys.path` — the suite passes even with the package uninstalled. `espalier selfcheck` (which resolves its bundled mirror from the INSTALLED package via `importlib.resources`), run from a foreign cwd, is the real install-green check. See `docs/AUTONOMOUS_EXECUTION.md` and FAILURE_MODES §9.4.

## `/clear` clears an active `/goal`; Esc stops a dynamic `/loop` but NOT a cron `/loop`

**What it is:** Two Claude Code automation-control facts that surprise. (1) `/clear` clears an active `/goal` — so you cannot reset the transcript mid-session while keeping one overarching goal (the per-unit-fresh-context driver pattern falls out of this). (2) The two `/loop` modes stop differently: a **dynamic** loop (`/loop` with no interval, self-paced via `ScheduleWakeup`) stops on **Esc** or by simply omitting the reschedule; an **interval** loop (`/loop 5m …`, a cron job) **ignores Esc** — it keeps firing until `CronDelete` (or "cancel the X job") or the 7-day auto-expiry.

**How you hit it:** Pressing Esc to stop a `/loop 10m …` and finding it still fires on the next cadence; or running `/clear` to trim context during a goal-driven run and losing the goal. Also: `/goal` auto-clears on success — telling the user to run `/goal clear` afterward is wrong (it already cleared).

**How to avoid it:** For an interval loop, use `CronDelete` / natural-language "cancel the X job" / the global `CLAUDE_CODE_DISABLE_CRON=1`; rely on the 7-day expiry as a backstop. For a goal, don't `/clear` mid-run; bound the goal with `or stop after N turns`. Full reference: `docs/CC_AUTOMATION.md`. The self-re-arming variant of the dynamic loop is its own footgun (FAILURE_MODES §7.10).

## Statusline reads blueprints with fd-level bounds

**What it is:** `tools/cc/statusline.py::_read_blueprint_safe` opens `cc/blueprints/latest.json` with `O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`, `fstat`s for regular-file shape, caps at `BLUEPRINT_MAX_SIZE` (128 KB; shared with `cognitive_blueprint` via `tools/cc/_blueprint_limits.py`), and passes the bytes to `_parse_blueprint_safe` for depth + per-string-bytes caps (10 levels, 4 KB). The reader-side guard is mirrored by a writer-side cap in `cognitive_blueprint._save` that truncates oldest `reasoning_entries` before write — the cap is bilateral.

**Why both halves are necessary:** Reader-only would let a legitimate long session cross 128 KB, fail the reader gate, and silently lose context AND the statusline visibility signal on next start. Writer-only would let an attacker plant an oversize blueprint that the writer never sees. Bilateral is the only correct shape.

**How you hit it:** You probably don't — the cap is well above current observed maximum (~12 KB) and the safe-read helpers exist precisely to make pathological cases silent rather than catastrophic. If your statusline degrades to bare `espalier`, check `cc/blueprints/latest.json`: is it a symlink (refused), is `stat -c '%s'` over 131072 bytes (refused), is any string field over 4096 UTF-8 bytes (refused), is nesting over 10 levels (refused), or is it not valid JSON at all (refused)?

**How to avoid it:** Don't symlink files under `cc/blueprints/`. Don't write your own JSON into `latest.json`. Let `cognitive_blueprint._save` be the only writer. The writer's truncate-oldest behavior preserves the most recent reasoning_entries; if you need older context, look in the per-session files (`cc/blueprints/<session_id>.json`) which are not capped because they're not the statusline read target.

## Managed-Marker Scan Window vs YAML Frontmatter

**What it is:** `espalier/managed_markers.py::has_managed_marker` scans
the first `MARKER_SCAN_BYTES` (600) bytes of a file for the
`espalier:managed` marker. Files with YAML frontmatter (agents under
`.claude/agents/`, skills under `.claude/skills/`) wrap the body in a
`---` block at the top, and the marker per convention lives **after**
the closing `---` so frontmatter parsers see a valid block. A large
frontmatter (the canonical `code-reviewer.md` runs ~700 bytes) pushes
the marker past the flat 600-byte window.

**How you hit it (pre-fix):** First a prior fix smoke test showed
`code-reviewer.md` not regenerating because the marker landed at byte
~720 — past the scan window — so init treated the managed file as a
user file and silently skipped it. The 3-state init policy
(`created` / `updated_managed` / `skipped_user_files`) misclassified
managed files as user files.

**How to avoid it:** `has_managed_marker` is now frontmatter-aware:
when a `---...---` block is detected at the top, the scan extends to
`max(scan_chars, frontmatter_end + POST_FRONTMATTER_SCAN_PADDING)`
(padding = 200). Any new marker check **must** go through
`managed_markers.has_managed_marker`, not a homemade
`"espalier:managed" in content[:600]` substring scan. The SoT is the
helper, not the byte count.

<!-- espalier:fragment id=marker-contract
     bound=espalier/managed_markers.py::_MARKER_LINE_RE,espalier/managed_markers.py::has_managed_marker
     bound_closure=true
     policy=verify-on-touch -->
## Substring Markers Are Forgeable — Anchor to Line Start

**What it is:** `espalier:managed` and any similar short token used
as an ownership signal MUST be matched as an anchored comment line,
not as a substring. A YAML scalar (`description: espalier:managed text`),
JSON string value, or prose paragraph referencing the marker as text
will trip a substring match.

**How you hit it (pre-fix):** `has_managed_marker` used a substring
scan (`MANAGED_MARKER in content[:scan]`) — a prior bypass class demonstrated that
a hostile asset shipped via PR could plant `description: espalier:managed`
in a YAML field. On the next `espalier init`, `_deploy_asset_md` saw
`has_managed_marker(content) == True` for the hostile file and either
overwrote operator-authored content (if the file masqueraded as
managed) OR regenerated a user-edited file whose docstring happened
to mention the marker substring.

**How to avoid it:** An earlier fix locked recognition to the regex
`^[ \t]*(?:#|<!--|::)[ \t]*espalier:managed\b` compiled with `re.ASCII`
(the `::` head is the batch-file comment, added 2026-09-13 when the
`.cmd` statusline asset joined the managed set).
A leading default-ignorable run (BOM, ZWSP, ZWJ, LRM, WORD JOINER,
bidi controls, LINE/PARAGRAPH SEPARATOR — categories
Cf/Cc/Cs/Cn/Zl/Zp) is stripped before the regex so an invisible
prefix cannot displace the `^` anchor. If a future helper recognizes
a different marker, use the same line-anchoring discipline.
`find_confusable_markers` surfaces Cyrillic / case-variant /
HTML-entity look-alikes as warnings — these are correctly *not*
recognized (the secure outcome) but operators reviewing a PR diff
need to see them so a confusable doesn't ship.

## `cc/PACK_MANIFEST.txt` Is a Report, Not the Iteration Source

**What it is:** `cc/PACK_MANIFEST.txt` enumerates files
`espalier init` deployed on a given install. `deploy_harness` writes
it as the *last* step (via `write_required_surface`). It is a
*report* of what was deployed, not the *authority* for what to
deploy.

**How you hit it (pre-fix risk):** If `deploy_harness` consulted
the on-disk manifest to decide what to (re)deploy, an attacker (or
hostile collaborator on a shared workstation) could prune a line
from the manifest, then no-op the corresponding hook body while
keeping its `# espalier:managed` marker. On the next `espalier init`,
the hand-disabled hook would never get re-deployed and the
kill-switch + protected-zone gates would remain silently broken
(a prior bypass class marker-preserving disable).

**How to avoid it:** An earlier fix codified the invariant in the
`deploy_harness` docstring: iteration is over `INIT_HOOK_SCRIPTS` +
`INIT_TOOL_SCRIPTS` (module-level constants enumerated at import
time) for `.py` and a glob over `espalier/assets/claude/` for `.md`.
The contract is mechanically enforced by
`tests/test_cli_deploy.py::TestDeployIterationInvariant` (pruned-
manifest + emptied-manifest behavioural tests plus a static AST
check that `deploy_harness` body does not contain `PACK_MANIFEST` +
`read_text` on the same line). When extending `deploy_harness`,
never add a `cc/PACK_MANIFEST.txt` read — derive the deploy set
from packaged sources.

## Release Archive Classifier Evaluation Order

**What it is:** `espalier/surface_contract.py::classify_release_path`
checks buckets in this priority order: **internal → transient →
local_only → public**. The first matching bucket wins. `_normalize`
strips a leading `./` and converts Windows backslashes before any
prefix check.

**How you hit it:** A path that matches multiple buckets gets the
first label, not the most-specific one. A doc under `docs/internal/`
that is also gitignored returns `internal`, not `local_only`. A new
prefix added to `_LOCAL_ONLY_PREFIXES` will be **shadowed** by any
overlapping entry in `_INTERNAL_PATH_PREFIXES` or
`RELEASE_NOISE_PATTERNS`. The order also pins the contract that
`is_public_release_allowed(p)` agrees with `classify_release_path(p)
== "public"` — both consume the same bucket cascade.

**How you hit it (variant — the `./` bug, later follow-up):**
`_normalize` originally only converted backslashes. A caller that
passed `"./reports/x.json"` (the natural shape from
`Path.relative_to()` on certain root configurations) silently
classified as `public` because `startswith("reports/")` failed on the
dotted prefix. The two production callers
(`scripts/build_release_archive.py` and `scripts/release_check.py`)
already strip the `./`, so the bug stayed latent until the public
predicates `is_release_included` / `is_release_excluded` were added.

**How to avoid breaking it:** Any new bucket prefix must be added to
the **most specific** category and tested with both bare and
`./`-prefixed inputs. `tests/test_release_archive_filtering.py::test_release_predicate_wrappers_match_classifier`
parametrizes both shapes; new predicates added to `surface_contract`
should reuse the same sample set. The classifier order itself is
load-bearing — do not reorder without re-running the full release
test slice.

## Hook Settings Written For Linux Assume Linux

**What it is:** A generated config file that hardcodes a Linux-shaped
hook command (`/usr/bin/python3` plus a quoted
`$CLAUDE_PROJECT_DIR/tools/cc/hooks/X.py` script path) silently assumes
the operator is on Linux. Windows users get a "command
not found" error on every hook spawn; macOS users whose Python lives at
`/opt/homebrew/...` get the same failure with a different path; any
user with spaces in their project path hits shell-tokenization issues.

The deeper trap is that internal consistency masks the problem — the
generator works on the host that produced it, tests pass on that host,
the bug only surfaces when someone clones the repo on a different OS.

**How you hit it (audit receipt):** Pre-fix `_build_settings_json`
emitted shell-form commands with `sys.executable` (an absolute
host-specific path) plus shell-quoted `$CLAUDE_PROJECT_DIR`. A later
change made it worse by adding shell-dispatch logic (bash vs PowerShell vs cmd)
to handle the variable-interpolation differences across shells. Both
fixes were treating symptoms, not the cause. The real cause was using
shell form at all.

**How to avoid it:** Use Claude Code's **exec form** for hook commands:

```json
{
  "type": "command",
  "command": "python",
  "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/X.py"]
}
```

Exec form passes `command` to Claude Code as the executable to spawn
and each `args` element as one verbatim argument. No shell is involved,
so:

- No shell tokenization (spaces in paths Just Work).
- No platform-specific variable syntax (`${CLAUDE_PROJECT_DIR}` is
  Claude Code's documented placeholder; resolved before any shell
  touches the args).
- No absolute interpreter paths (Claude Code resolves `python` on PATH
  on every supported OS).

**Resolver requirement.** A Python 3.10+ interpreter must be on PATH
as either ``python`` or ``python3``. later follow-up: ``espalier init``
detects which name is present at init time and writes that into the
generated `.claude/settings.json` (see ``cli._detect_python_command``).
macOS Homebrew installs (which ship only ``python3``) and Linux distros
that symlink ``python`` both work without operator action.

If you see ``Executable not found in $PATH: "python"`` from CC on every
hook fire, your `.claude/settings.json` was generated before this fix.
Re-run ``espalier init .`` (no flags needed) to regenerate it with the
detected interpreter. The file is gitignored, so the regeneration is
local-only.

The historical mitigation (a manual ``sudo ln -s "$(which python3)"
/usr/local/bin/python``) still works as an alternative — it gives every
tool on the machine a ``python`` name, not just espalier's hooks — but
it is no longer required.

`docs/HOOKS.md` (section "Hook command resolution and matcher rules
(a prior fix)") covers the per-platform notes.

**General rule:** A config file deployed cross-platform must not embed
platform-specific paths or rely on shell-specific quoting. If the
framework offers a no-shell execution mode (exec form, structured
args, IPC), prefer it over shell-form with portability workarounds.

**Existing installs are not migrated.** `.claude/settings.json` files
generated before this fix keep the shell-form shape. Re-run
`espalier init .` (after deleting the existing file) to regenerate
in exec form.

## "Active" Predicate That Includes a Closed State Weakens the Active Claim

**What it is:** A predicate named "has active X" or "is X open" that
returns True for both an open state *and* a closed state. The name
suggests strict semantics; the code accepts any recent state. Callers
that depend on the name's guarantee are silently weakened, and the
weakening is invisible because the "happy path" tests (write succeeds
during an in-progress task) still pass.

**How you hit it (audit receipt):** `plan_guard.py:_plan_exists`
returned True for both `status='in_progress'` and `status='complete'`.
A completed plan kept the mutation window open. The function's name
(`_plan_exists`) and the guard's public claim ("writes require an
active plan") both implied strict semantics; the predicate accepted
*any recent* plan. The leak shipped in v0.6.0 — every internal test
agreed the existing behavior was correct because no test parametrized
across the closed states.

**How to avoid it:**

1. **Predicate names must match enforced semantics.** If a function
   named `is_active` or `has_active_X` returns True for closed states,
   either rename it (`has_recent_X`) or tighten the predicate. Don't
   leave the name lying.
2. **Parametrize tests across the full state space, not just the
   happy path.** A passing `test_in_progress_allows_write` is not
   evidence that `complete` denies; you need an explicit case per
   closed state. Pattern: a single `@pytest.mark.parametrize` table
   listing every status the SoT enumerates, asserting the gate's
   response for each — including the empty string, unknown values,
   and case variants.
3. **Fail-closed defaults must be tested explicitly.** Missing file,
   malformed JSON, empty `status`, and missing `steps` are separate
   negative cases, not one "everything else" lump.
4. **The deny message should name the actual state.** Without that,
   the operator can't tell whether the plan is missing, complete, or
   in some other closed state — and the test that asserts a deny
   doesn't double as documentation of *why* it denied.

**Receipt files:** `tests/test_plan_guard.py::TestPlanGuardStatusPredicate`
parametrizes 7 closed-status cases + 6 negative cases.
`TestPlanGuardDenyReasonContent` pins the reason-text contract.
`_plan_state_label` in `tools/cc/hooks/plan_guard.py` is the
single source of truth for which state label appears in the deny
message.

<!-- espalier:fragment id=release-noise-patterns
     bound=espalier/release_noise.py
     policy=verify-on-touch -->
## Parallel Noise Inventories Drift Independently

**What it is:** When a project has multiple inventories of "things that
shouldn't ship" (a `.gitignore`, a release classifier, a CI noise scan),
each maintains its own pattern list. Patterns added to one don't
propagate to the others, and the first time you discover the divergence
is when a leak makes it past all the gates.

**How you hit it:** v0.6.0 shipped a 6 MB `project.zip` because
`surface_contract.RELEASE_NOISE_PATTERNS` and
`release_check._TRACKED_NOISE_PATTERNS` had no rule for top-level
archives, even though `.gitignore` did. Both classifiers passed; the
archive shipped. Gates that consume the same source they validate can
only catch what the source already knows.

**How to avoid it:** One SoT (`espalier/release_noise.py`), parity
test against `.gitignore` (the broader, human-curated list), and a
regression test parametrized on the false-positive class so the
specific leak can't return. The pattern: **break the closed loop with
an external witness** — `.gitignore` here is the witness that catches
the SoT undercovering.

**Count a rule's copies by driving the artifact, not by grepping the
pattern (2026-09-21).** The task-pack rule was ledgered as "one rule
kept in five places"; the sixth (`espalier/release_denylist.py`, the
archive scan's second witness) surfaced only when `scripts/release_check.py`
was run against an archive that actually carried a pack. A grep finds the
spellings you already know; the gate that reads the built artifact finds
the copy you did not. The same day taught the shape's limit: git cannot
re-include inside a pruned directory, so once part of a folder ships
(`task-packs/` since 2026-09-21) its `.gitattributes` wall is a named
deny-list forever, and a force-added stray outside those names reaches
`git archive` with every spelling test green. The catch-all has to be
derived — every tracked path under the folder is in the ship set, and no
`local_only`-classified path is in the archive — which is the `local_only`
twin of the `internal` gate `tests/test_git_archive_parity.py` already had.

## Proof Artifacts Go Stale If No Contract Pins Them

**What it is:** A "proof" file like a benchmark result, performance
metric, or evidence dump tends to drift from current state because
nothing tests it. The artifact ages silently; a release ships with
the proof still saying it covers v0.5.0 while the package is v0.6.0.

**How you hit it:** `bench/RESULTS.md` said "espalier version: 0.5.0"
in the v0.6.0 release archive. Nothing tested the parity.

**How to avoid it:** Every proof artifact that names an exact
version/date/checksum gets a parity test against the source of truth.
The test fails when the proof goes stale, prompting a refresh. If the
proof can't be refreshed in the current environment (e.g., benchmark
requires `ESPALIER_MAINTENANCE_MODE` unset), unset the env var in the
subprocess: `env -u ESPALIER_MAINTENANCE_MODE python3
bench/run_benchmark.py --update-canonical`.

## Init Suggestions Gated on File Existence Miss the Fresh-Repo Flow

**What it is:** A suggestion-emitting code path that gates on `if
file.exists():` will skip the suggestion entirely when the file is
absent — but absence is exactly the case where the user needs the
suggestion most.

**How you hit it:** The pre-fix gitignore handler (`REQUIRED_GITIGNORE`
in `espalier/cli.py`) gated on `gitignore.exists()`. A fresh repo with no `.gitignore` hit
the suggestion logic; the entire block was skipped; the user saw
nothing; `git add -A` after init staged four machine-specific files
(`.claude/settings.json`, `.espalier/integrity.json`,
`reports/harness_config.json`, `reports/repo_fingerprint.json`).

**How to avoid it:** Suggestion logic runs unconditionally; only the
*phrasing* depends on whether the target file exists. Test fixtures
must include the absent-file case for any "check if file needs
updating" code path. When writing a check that gates behavior on a
file's existence, ask "what's the right behavior if the file is
absent?" — the answer is rarely "do nothing silently."

## Audit Followups Produced in Separate Sessions Drift from Each Other

**What it is:** A multi-pack sprint produced across sessions can have
internal drift even when each individual pack is correct. Session A
writes a pack using convention X; session B writes a pack mandating
NOT-X. Neither session sees the other's work; the contradiction ships.

**How you hit it:** a prior fix (gitignore protection) was written with the
warning glyph `⚠` in its print statements. A later pack in a later session
was supposed to absorb the ASCII-portability concern but didn't
enumerate the runtime-output rule explicitly. The cross-check session
caught the earlier fix's `⚠` as a gap issue: the earlier fix was already prescribing what
a prior fix was supposed to disallow.

**How to avoid it:** Before considering a sprint complete, run a
cross-check pass: take the union of all pack content and grep for
contradictions against each pack's own conventions. Extract conventions
(ASCII tokens, file-path conventions, naming rules) into a shared
`docs/CONVENTIONS.md` that every pack references rather than restates.

## Renderers That Discard Fingerprint Data Fail Silently

**What it is:** A code path that consumes a structured fingerprint
(language, test command, source dirs) but hardcodes the output ignores
the structure. The fingerprint correctness is preserved upstream, so
static analysis doesn't catch the issue -- only runtime inspection of
the rendered artifact does.

**How you hit it:** `_build_claude_md` correctly received
`fp.test_commands = ['cargo test']` for a Rust target repo. The renderer
hardcoded `pytest -q`. The CLAUDE.md deployed to the user's repo told
them to run pytest in their Rust project. No test caught the regression
because no test exercised the renderer against non-Python fingerprints.

**How to avoid it:** Any function whose job is "render a per-repo
artifact" must be parametrized regression-tested against multiple
language fingerprints. If a `_build_*` or `_render_*` function takes a
fingerprint argument but its output contains no string interpolation
from that fingerprint, that's a smell. The contract: data flows into the
function, output reflects the data. See `tests/test_build_claude_md_uses_fingerprint.py`.

## A Directory Cannot Play Both "Dogfooding Artifact" and "Deployment Template"

**What it is:** When the same files serve as both (a) the project's own
dogfooding (lived-in, accurate to this codebase) and (b) a deployment
template for user repos (must be generic), the files inevitably
specialize over time toward dogfooding and the deployment half silently
becomes wrong.

**How you hit it:** Espalier-Harness's `espalier/assets/claude/` was
both. The bundled `architecture-analyst.md` deployed to user repos
verbatim, but its content described Espalier-Harness's own `tools/cc/`
<-> `espalier/` layer model. A Flask developer ran `espalier init` and
got an agent that thought their Flask app had layer rules from a tool
they'd never heard of. The README's "tailored to your repo" claim was
verifiably false against the deployed content.

**How to avoid it:** Keep the dogfooding files where they accurately
describe the dogfooded project (`examples/dogfooding/`). Build explicit
templates for the deployment surface. If templating is hard, deploy
nothing -- "we don't have language-aware agents yet" is better than
"here are agents that describe a different project."

**Rule of thumb:** If a file references the project that ships it
(file paths, layer names, internal conventions), it cannot be a
deployment template. It can be an example, a reference, or dogfooding
-- but the deploy path needs different content.

## Single-Signal Substring Detectors Over-Match

**What it is:** A classifier that returns True on any single token match
against a free-text source (pyproject description, README prose, file
name) fires on framework-shaped repos where the token appears
incidentally. The classifier reads the syntax, not the meaning.

**How you hit it (audit receipt):** The pre-fix `detect_ml_surface`
fired on:
- `models/` directory alone — Django, SQLAlchemy, and FastAPI standard
  layout.
- `notebooks/` directory alone — any tutorial-heavy library.
- The substring `"model"` in pyproject prose — Espalier-Harness's own
  `pyproject.toml` had `"unit: pure function/model tests"` in a pytest
  marker description, so the self-host fired its own ML detector.

The downstream effect: `experiment-analyst` and `data-engineer` agent
stubs were recommended on repos that had nothing to do with ML.

**How to avoid it:** Multi-signal co-occurrence with structural binding
on each signal:

1. Require evidence in 2+ independent dimensions before firing — each
   individual signal can be weak as long as the conjunction is strong.
2. Bind directory signals to evidence the directory is doing what its
   name implies — `notebooks/` must contain `.ipynb`, `models/` must
   contain weight files (`.pt` / `.h5` / `.safetensors` / `.onnx`).
3. Bind dependency signals to structured parsing of the dep section,
   not arbitrary prose. Use `tomllib` (via `espalier._compat.tomllib`)
   to read `project.dependencies` / `project.optional-dependencies` /
   `tool.poetry.dependencies` directly. A substring scan over the file
   body catches description strings and marker descriptions; a
   structured scan only catches actual declared deps.

The general rule: **directory names and prose substrings are
suggestions, not assertions.** Bind your detector to evidence the
directory or token is doing what its name implies, not just that it
exists.

**Receipts:** `espalier/analyze.py::detect_ml_surface` requires 2 of 4
signals (training scripts, dep imports, directories with content, ML
config files). Coverage in `tests/test_detect_ml_surface_false_positives.py`
(5 cases) and `tests/test_detect_ml_surface_true_positives.py` (6 cases).

**Directional substring containment is even sharper.** When a
classifier matches by `a in b or b in a` (the short token is a substring of the
longer), it over-fires on prefix/interior containment: `'main'` ⊂ `'mainframe'`,
`'tool'` ⊂ `'toolkit'`, `'set'` ⊂ `'settings'`. A length floor does not help —
the short string is a substring of a longer *token*, not noise. If the match you
actually want is a morphological one (e.g. `'agent'` ⊂ `'subagent'`, the `sub-X`
shape), constrain containment to a **suffix** check (`long.endswith(short)`), not
bare `in`: suffix-only preserves `agent`⊂`subagent` while killing the prefix
over-matches. `surface_matrix._suffix_overlap` is the receipt. (A literal
word-boundary rule would over-correct — it breaks `agent`/`subagent`, which are
not separate word segments.)

## Generated Settings With Zero Deny Rules Read As "Trusts Everything"

**What it is:** A governance tool whose first deployed config has
`permissions.deny: []` and a broad allow list reads — to anyone who
opens the file — as "this tool does not actually govern anything."
Internal consistency (the tool's *intent* is governance) does not
matter; the deployed artifact is the public face.

**How you hit it (audit receipt):** v0.6.x `espalier init` wrote
`permissions.deny: []` and an allow list including `Bash(pip *)`,
`Bash(git *)`, `Bash(python *)`. A user opening their new
`.claude/settings.json` and scanning for the governance saw nothing
in deny and broad allows. The harness *did* govern via hooks, but
the visible config read as permissive.

**How to avoid it:** Every governance tool whose output is a config
file should ship non-empty deny defaults that a human reader can see.
Profile defaults should match the tool's positioning: a "governance
harness" defaults to friction; a "power user automation" defaults to
broad allows. Make the choice explicit and document the trade-offs.

`espalier init` ships three profiles — `minimal` (read-only),
`workflow` (default; narrow test commands + governed `Write`), and
`full` (preserves v0.6.x broad-bash behavior). All three share the
deny list, which since 2026-09-03 is the dangerous **bash** patterns
only. Generated `settings.json` also carries a `$schema` link so
editors can flag schema-invalid keys before a silent typo ships.

## A `Read()` deny rule silently disables bypass mode for every Bash command that reads a file

**What it is:** `espalier init` used to emit five `Read()` deny rules
(`Read(./.env)`, `Read(./.env.*)`, `Read(./secrets/**)`,
`Read(./**/.aws/credentials)`, `Read(./**/credentials.json)`) on every profile.
Configuring **any** `Read()` deny rule arms a static-resolvability requirement
in Claude Code: before running a Bash command it must prove which files that
command reads, so that it can prove none of them is denied. A command whose
read set cannot be resolved statically — one containing a `cd`, a relative
`--include` glob, or a glob over a directory it cannot enumerate — gets an
interactive permission prompt instead. Verified from the client's own message
text: *"which file that is cannot be resolved statically while a `Read()` deny
rule is configured, so this needs approval."*

**How you hit it:** You run in `bypassPermissions` precisely so long sessions
don't stall, and they stall anyway — on ordinary greps and `cd`-prefixed
commands, several times an hour. Every obvious remedy fails, because **deny
outranks `allow` and outranks the permission mode**: adding `Bash` to the allow
list does nothing, `defaultMode` does nothing, and the prompt names the command
rather than the rule, so the deny list is the last place you look. One measured
session lost hours to it before the cause was found, and the rules in question
were guarding paths that did not exist in the repo.

**How to avoid it:** Keep sensitive-path denial at the **hook** layer, not the
permission layer — `write_guard.check_secret_path_access` denies the same five
shapes for the `Read` tool and for Bash read verbs, is not bypassed by
maintenance mode, and does not arm the prompt. Bash deny entries
(`Bash(rm -rf /)`, `Bash(curl * | sh)`) are safe to keep: the arming condition
names `Read()` specifically. `tests/test_settings_profiles.py` now fails if a
`Read()` rule reappears in `_DENY_DEFAULTS`, and
`tests/test_write_guard.py::TestSecretPathAccess` pins the coverage that moved.
Neither layer is a security boundary (`STANDING_PRINCIPLES` §2) — the
permission rules were not one either.

**Important:** settings profiles are governance defaults, not a
sandbox. A determined operator can bypass via `--permission-mode
bypassPermissions`, editing `settings.local.json`, or running with
`disableAllHooks: true`. Public docs must not imply otherwise. The
harness defends in depth (deny rules at the permission layer,
`write_guard.py` at the hook layer, `ci_guard.py` at CI) — no single
layer is a hard boundary.

## `disableSkillShellExecution` Is Not a Claude Code Setting

**What it is:** An earlier fix originally proposed setting
`disableSkillShellExecution: true` in the conservative settings
profiles (`minimal`, `workflow`) so skills could not run inline `!`
shell preprocessing before the rendered skill text reached Claude.
The pack flagged the key as "verify before shipping."

**How you hit it:** A WebFetch against the live schema at
`https://json.schemastore.org/claude-code-settings.json` on
2026-05-13 confirmed the key is **not** defined. The schema does
expose `disableAllHooks`, `disableBypassPermissionsMode`,
`disableAutoMode`, and `disabledMcpjsonServers` — but no equivalent
for skill shell preprocessing. Setting an undeclared key would
either be ignored by Claude Code or flagged by schema-aware
editors. Either way it would not deliver the intent.

**How to avoid it:** Espalier does NOT emit
`disableSkillShellExecution` on any profile. If Claude Code adds a
documented setting for this (or any equivalent), revisit
`espalier/settings_profiles.py` and add it under `minimal` and
`workflow`. Until then, the gap stands. Validating against the live
schema before adding a `disable*` field is the discipline — do not
trust pack-author wording on its own.

**Receipt:** `espalier/settings_profiles.py` has a top-of-file
comment recording the decision. The contract is tested only
indirectly: `tests/test_settings_profiles.py::TestProfile::test_has_schema`
asserts the `$schema` link is present, and schema-aware validators
catch foreign keys against it.

## A Claim Without a Contract Surface Gets Broader Every Release

**What it is:** A public claim like "X governs Y" gets read by users as
universal coverage. New audits arrive assuming the claim and discover
gaps; each gap becomes a finding; the finding gets fixed; the next
audit finds a different gap. The claim itself never changes scope, but
the implementation chases the audit horizon forever.

**How you hit it:** Espalier's README said "espalier governs Claude
Code." Five independent audit runs across four months found 60+ items
where Claude Code has a surface espalier doesn't actually govern
(deferred), or governs partially, or is documented-only, or is out of
scope entirely. Each audit closed some gaps; none of them narrowed the
claim. The first internal audit found 21 numbered drift items; the
Trust Cut audit found 12; the Release Candidate audit found 9; the
Final Sprint audit found 7; the unification pass found 11 more.

**How to avoid it:** Replace broad claims with a normative support
matrix. `docs/SURFACE_SUPPORT_MATRIX.md` lists every relevant Claude
Code surface and marks each as guarded, supported, documented-only,
deferred, or unsupported. Public docs are tested against the matrix
(`tests/test_surface_support_matrix.py::TestPublicDocsNoOverclaim`) so
overclaiming language fails at pytest time. When a new surface becomes
interesting, the matrix gets a row, not the claim.

The general rule: **make the contract the surface, not the surface the
contract.** A list of governed surfaces is finite and testable. A claim
like "governs Claude Code" is unbounded and unfalsifiable.

<!-- espalier:fragment id=surface-matrix-rows
     bound=docs/SURFACE_SUPPORT_MATRIX.md
     policy=verify-on-touch -->
**Receipt:** `docs/SURFACE_SUPPORT_MATRIX.md` (20 rows across 5 status
categories). `tests/test_surface_support_matrix.py` validates closed
vocabulary + required surfaces + anti-overclaim.
`tests/test_agent_frontmatter_contract.py` pins each bundled agent's
capability tier so silent Write/Bash escalation fails CI. Established
in an earlier release.

## Release Gates That Grade Themselves Through The Same Path They Validate

**What it is:** A release gate that consumes the same classifier or
inventory used to BUILD the release archive can only catch what that
classifier already knows. The classifier is the source of both
inclusion and validation; a blind spot in the classifier is invisible
to the gate. Internal consistency between "what shipped" and "what the
gate saw" is unfalsifiable when both views come from the same code.

**How you hit it:** v0.6.0's `check_release_archive_clean` walked the
built archive and consulted `espalier/surface_contract.py` to classify
each member. The classifier had no rule for top-level `*.zip` — it
defaulted to `public`. The gate consulted the same classifier;
`project.zip` was "public"; gate passed. The release shipped 6 MB of
dev state. An earlier fix fixed the inventory drift but left the architectural
flaw in place — the gate and the build still graded each other.

**How to avoid it:** Two independent witnesses on the same artifact,
with NO shared code between them. `espalier/release_denylist.py`
(a prior fix) is the second witness — a separate pattern list that imports
nothing from `release_noise.py` or `surface_contract.py`. Both must
clear every archive member; disagreement on a real file is an
investigation signal, not a rubber-stamp difference. Operators can
run the second witness against a downloaded archive with
`python scripts/release_check.py --validate-archive <path/to.zip>`,
which catches CI-rebuild drift between the local archive and what
GitHub publishes.

The general rule: **single-source verification is single-source
truth, not verification.** Two independent witnesses are not just
defense in depth — they are the difference between "the gate said
yes" and "the artifact is correct."

<!-- espalier:fragment id=release-denylist-patterns
     bound=espalier/release_denylist.py::DENIED_PATTERNS
     policy=verify-on-touch -->
**Receipts:** `espalier/release_denylist.py` (56 patterns, no shared
imports). `scripts/release_check.py::check_release_archive_builds_and_clean`
consults both witnesses. `--validate-archive` mode for external ZIPs.
Established in an earlier pack; pattern split refined in an earlier release to allow the
committed freshness manifest through.

## Markdown Escaped Pipes Silently Drop Matrix Rows

**What it is:** `espalier/surface_matrix.parse_matrix_rows` splits
table cells on bare `|` characters and does not honor `\|` (markdown
escaped pipe). A Notes cell containing `\|` produces one extra "cell"
from the parser's perspective; the row then has 6 fields instead of 5
and is silently dropped from the output. `load_matrix` and downstream
consumers (`espalier scope-check`) see one fewer surface than the
table renders.

**How you hit it:** Adding a row to `docs/SURFACE_SUPPORT_MATRIX.md`
whose Notes cell needs a literal `|` (e.g., describing pipe-to-shell
patterns) and writing it as `\|`. The Markdown viewer renders the
row; the parser drops it; the test suite stays green because
`test_required_surfaces_present` only verifies that named *required*
surfaces are present — a new row whose surface name is not in
`REQUIRED_SURFACES` vanishes invisibly. This is exactly how the
"Main session Bash" row was missing from `scope-check`'s classifier
output from a prior fix through three review rounds until
`/reflect` caught it (`9975f98`).

**How to avoid it:** Don't write `\|` inside table cells. Use prose
substitutes: `curl <pipe> sh (pipe-to-shell)` instead of `curl \| sh`.
After any edit to the matrix, the regression test
`tests/test_surface_support_matrix.py::TestMatrixFile::test_no_rows_silently_dropped_by_parser`
runs automatically — it counts pipe-led lines minus the GFM separator
rows and compares against `parse_matrix_rows`'s output. A future drop
fails CI immediately with a message naming the likely cause.

**Receipt:** `docs/SURFACE_SUPPORT_MATRIX.md:43` was rewritten in
commit `9975f98` (the only line of that file changed by the fix).
`tests/test_surface_support_matrix.py::TestMatrixFile::test_no_rows_silently_dropped_by_parser`
and `tests/test_surface_matrix_module.py::TestParseMatrixRows::test_mismatched_cell_count_row_is_silently_dropped`
together pin both the live-file and unit-level contracts. The reflect
pass that caught this is documented in ESPALIER_MEMORY.md Patterns Learned.

## Fingerprint Is Signal-Based, Not Census-Based

`reports/repo_fingerprint.json` captures signals (which frameworks, what
test command, which CI providers) — NOT census counts (how many tests,
how many modules, how many lines). The `espalier diff .` command reports
signal-level drift only.

**How you hit it:** Running `espalier diff .` between releases to ask
"did test count change?" returns no useful answer. The fingerprint's
purpose is to detect when the *kind* of repo changed (new framework
adopted, new CI provider added), not when the *size* did.

**How to avoid it:** For census drift (test count, module count, line
count), grep the live filesystem and compare to a pinned reference
rather than to the fingerprint. The doc-truth contracts in
`tests/test_documented_claims.py::TestNoStaleNumericContracts` provide
the canonical census via `NUMERIC_CONTRACTS`. If you need census in
fingerprint form, extend `espalier/models.py::RepoFingerprint` with
explicit fields and populate them in `espalier/analyze.py` (opt-in;
signals are intentionally compact) — don't read counts out of the
existing `signals` dict, which is a presence map.

**Receipt:** Fingerprint schema keys verified at HEAD: present keys are signals,
languages, profiles, runtime_surface, etc. — no `test_count` or
`module_count` field.

## Stale `.claude/settings.json` PreToolUse Matcher After Upgrade

**What it is:** When upgrading to v0.7 (a prior fix C2) from any earlier
release, the operator's existing `.claude/settings.json` carries a
narrowed PreToolUse matcher (typically
`"Write|Edit|NotebookEdit|Bash|PowerShell|ExitPlanMode|mcp__.*"`).
Claude Code filters hook invocations by this matcher BEFORE spawning
the subprocess, so `write_guard`'s kill-switch and protected-zone
gates never see Task / TodoWrite / SlashCommand / BashOutput
dispatches until the operator regenerates the settings file with the
post-fix `matcher: "*"`. MCP tool calls already worked under the
older matcher, but the broader tool surface (subagent dispatches via
`Task`) silently bypassed governance.

**How you hit it:** `pip install --upgrade espalier-harness`. The
package updates; the local `.claude/settings.json` does not. The next
session's first MCP tool call (e.g., `mcp__filesystem__write_file`)
runs without write_guard ever seeing it. The protected-zone branch at
`tools/cc/hooks/write_guard.py::check_powershell_for_protected_symlinks` is reachable in the source but
dead in production for that operator.

**How to avoid it:** After upgrading, run
`rm .claude/settings.json && espalier init .` to regenerate with the
current matcher, then `espalier integrity refresh .` to pick up the
new hook hashes. `cmd_init` now detects the stale matcher in
an existing settings.json and prints a `[WARN]` naming the refresh
command, so a re-run of `espalier init .` (without removing the file)
gives the operator the signal even without removing the existing file.
CI's `harness-guard` workflow does NOT catch this — it inspects
committed paths, not the operator's local settings.

**Matcher-scoping fix:** the `deploy_harness` detection is now
scoped to the `write_guard` entry via
`surface_contract.write_guard_matcher_excludes_mcp`. The pre-fix
heuristic scanned EVERY hook entry for `"Write" in matcher and "mcp__"
not in matcher`, so `plan_guard`'s and `context_reinject_failure`'s
narrow-by-design `Write|Edit|NotebookEdit` matchers tripped it on every
re-init of a CORRECT v0.7.x config — a false alarm whose advised remedy
(`rm + re-init`) is destructive. MCP-reachability is now decided by
`re.fullmatch` against a representative MCP tool name
(`_matcher_reaches_mcp`), NOT a substring test — the codebase's single
authoritative matcher model (same as `matcher_covers_mutations`), so a
`Write|Edit|mcp__` hand-edit typo (contains the substring, fullmatches
no real MCP tool) is correctly flagged. This WARN is the friendly,
init-time advisory; the load-bearing mechanical gate for an
MCP-incapable `write_guard` matcher is the **N7 oracle**
(`doctor._check_governance_event_wiring` + the `ci_guard` mirror), which
flags ANY `write_guard` matcher narrower than fire-on-all and reddens
CI — so a residual gap in this advisory is belt-to-suspenders, not a
silent hole.

**Receipt:** the matcher carries `mcp__.*`, and `deploy_harness` carries
stale-matcher detection. The Breaking-changes section of the v0.6.5
CHANGELOG entry documents this as required upgrade ceremony. The detection
is scoped to `write_guard` and uses the fullmatch model; earn-the-red:
the pre-fix predicate returns `True` on the live settings.json + all
four profiles + the default build.

## `Path.home()` Raises When `HOME` Is Unset

**What it is:** `Path.home()` raises `RuntimeError` on POSIX systems
when the `HOME` environment variable is unset AND the `pwd` database
has no entry for the current UID. `_audit_dir()` in
`tools/cc/hooks/_integrity.py` uses `Path.home()` directly. Pre-fix
the raise propagated up to the hook subprocess and exited with code 1
(script bug) on every tool call.

**How you hit it:** Minimal container or CI runner with stripped env
(`env -i sh`) AND no `/etc/passwd` entry for the running UID. On a
developer machine HOME-unset alone is usually not enough — POSIX
falls back to `pwd.getpwuid()` and returns the user's real home dir.
The combination is what makes `Path.home()` actually raise.

**How to avoid it:** A `RuntimeError` fall-through replaced the original
stable-name fallback with `tempfile.mkdtemp(prefix=".espalier-audit-")` and a
module-level cache: each process gets one unique, mode-0o700,
random-suffix directory shared across all `_audit_dir()` calls in
that process.

The original stable fallback (`gettempdir() / ".espalier-audit"`)
was symlink-attackable on a multi-tenant POSIX host with a
world-writable `/tmp` — an attacker could pre-place a symlink at the
predictable name, and `mkdir(exist_ok=True)` + `chmod(0o700)` would
then operate on the attacker-controlled target. `mkdtemp` uses
`O_EXCL` and a random suffix, closing the prediction window.

If you want persistent audit logs in such an environment, set `HOME`
explicitly before launching Claude Code. The fallback warning to
stderr names the per-process directory so the operator can find it.

**Three further hardening additions to the audit-log surface:**

1. **Override validation.** `ESPALIER_AUDIT_DIR` is inherited from the
   parent shell — a compromised parent could set it to `/etc/cron.d/`
   (or any sensitive location) so every blocked tool call writes JSON
   into the attacker's chosen directory. `_validate_audit_override`
   now rejects: (a) overrides that are symlinks, (b) overrides whose
   resolved path doesn't sit under `Path.home()` or
   `tempfile.gettempdir()`, (c) overrides that exist and are owned by
   a different user (POSIX). Rejections fall back to the default path
   with a stderr warning naming the rejection reason.

2. **Timestamp-based prune.** `_prune_old_audit_logs` previously used
   `f.stat().st_mtime` as the sole age signal. `touch -t 209901010000
   <log>` (or `touch` to today) could keep tampered logs alive past
   their cutoff or push fresh logs out of view. The primary age check
   now reads the first JSON line's `timestamp` field via
   `_parse_first_log_timestamp`; mtime is the fallback when the log
   body can't be parsed (truncated file, corrupted JSON).

3. **Iteration cap.** `_MAX_PRUNE_SCAN = 5000` caps the per-call
   iteration. An attacker spamming `~/.espalier/audit/` with empty
   `.log` files (cheap: a `for` loop) could otherwise slow
   `session_start` linearly with the file count. Above the cap, the
   sorted-first-N is processed and a stderr warning fires so the
   operator sees the flood.

**Receipt:** Coverage: `tests/test_audit_dir_home_unset.py` (17
tests including `TestAuditDirOverrideValidation`,
`TestPruneTimestampSemantics`, `TestPruneIterationCap`).

## Atomic Write Is Not Atomic Update

**What it is:** `tools/cc/hooks/_hook_utils.atomic_write_text` and its
inlined twin in `tools/cc/cognitive_blueprint._atomic_write_text`
guarantee that the FINAL write to a JSON state file isn't torn —
readers see the old contents or the new contents, never a partial
file. They do NOT guarantee that two concurrent load-modify-save
sequences both land their mutations. Two writers both reading the
same pre-state, both appending +1 mutation, then both writing back —
the second clobbers the first. The atomic-write contract protects
file integrity, not update sequence.

**How you hit it:** Multi-agent sessions. A Stop event fans out to
multiple subagents (code-reviewer, architecture-analyst, test-writer
running in parallel); each subagent calls
`cognitive_blueprint.py record …` to log its reasoning. Pre-fix
about 20% of entries silently dropped — the operator saw N-1 or N-2
reasoning entries with no warning and no recovery path. In
maintenance mode where Gate 4 auto-finalises the blueprint silently,
the loss was undiagnosable.

**How to avoid it:** An earlier fix wraps the load-modify-save window in
`_acquire_write_lock`, a context manager that takes `fcntl.flock`
LOCK_EX on a sibling `.write.lock` file. Mirrors the existing pattern
in `tools/cc/hooks/reflect_trigger._locked_increment`. Coverage:
`tests/test_cognitive_blueprint.py::TestConcurrentRecordNoLoss`
spawns 10 parallel records via `ThreadPoolExecutor` and asserts all
10 entries land. Windows lacks `fcntl`; the no-op fallback assumes
single-writer there (consistent with `_locked_increment`).

**Receipt:** The same pattern applies
to any future load-modify-save against a shared JSON file. Document
new consumers in `docs/CONVENTIONS.md` "Cross-session counter
atomicity via fcntl.flock" section.

## Agent Descriptions Need Plain ASCII in `.claude/agents/*.md`

**What it is:** An agent file in `.claude/agents/<name>.md` may have
valid YAML frontmatter (parses cleanly under `yaml.safe_load`), be
on disk before session start, and STILL not appear in the runtime
agent roster. Empirically observed 2026-05-15 with
`failure-mode-reviewer` (then named `adversarial-reviewer`) and
`release-verifier` — both added in commit
`4a92556`, both invisible to `Agent({subagent_type: "..."})`
calls for 6 days despite the files being present.

**How you hit it:** Both rejected agents used `description: >`
(YAML folded block scalar) with descriptions containing em dashes
(`—`), double-quoted phrases (`"what could an attacker do"`), and
parenthetical questions (`(do what shipped match what was said?)`).
The remaining agents that loaded successfully all used plain
single-line ASCII descriptions. Python's YAML parser accepts the
rich form; the Claude Code agent loader does not.

**How to avoid it:** Write agent descriptions as a single line of
plain ASCII. No `>` folded scalar, no double quotes, no em
dashes, no parenthetical questions. Concrete: replace
`description: >` + indented block with `description: <one
ASCII sentence>` on a single line. After editing, restart
Claude Code — the agent roster is captured at session start, not
hot-reloaded. The empirical fix applied 2026-05-15 (commit
`d9016b4`) simplified both agent descriptions; subsequent session
must verify the loader picks them up.

This may be a Claude Code platform parser quirk rather than an
espalier-specific constraint. Re-evaluate on each Claude Code
version bump; if upstream relaxes the constraint, this entry can
be retired.

**Receipt:** Discovered during the post-v0.6.6 multi-agent review
(2026-05-15). Empirical fix in commit `d9016b4`. Followup
documentation in an earlier release (this entry, plus a verify-after-restart
note in the operator's mental model). If the fix doesn't take
effect on next session start, escalate to a deeper platform
investigation pack.

## Convergence Is a Property of the Angle Set, Not the Implementation

A multi-round review chain that "converges" describes the review
angles it attacked, not the state of the code. Fresh angles re-open
findings the converged chain declared closed. Pre-commit to
angle-rotation and run a different-angle pass after the chain stops.

See [sharp-edges/convergence-is-an-angle-set-property.md](sharp-edges/convergence-is-an-angle-set-property.md)
for the canonical 14-round failure mode, the recommended angle
rotation set, and the post-asymptote audit pattern.

## Hook Fail-Open via Uncaught Exception (exit 1)

**What it is:** Claude Code treats exit code 1 from a hook subprocess as a
script error, not a governance decision. The hook runs but produces no block.
Any unhandled exception in a blocking hook (PreToolUse, ConfigChange) that
causes exit 1 silently allows the tool call through — the hook is as good as
absent for that invocation.

**How you hit it:** A PreToolUse hook receives a tool payload where
`tool_input["file_path"]` is an integer or list instead of a string. The
hook's first line does `rel = tool_input["file_path"].lower()`, which raises
`AttributeError`. Python exits with code 1. Claude Code logs the subprocess
error and continues — the protected-zone write succeeds (documented bypass class).

**How to avoid it:** Two defenses applied:

1. **Type-guard at entry.** `write_guard.check_write_edit` and
   `write_guard._normalize_path` both check `isinstance(file_path, str)`
   before any attribute access. Non-str payloads return the sentinel
   `"<invalid>"` (which matches no protected prefix) or emit a deny; they
   never raise.
2. **`BaseException` umbrella in `main()`.** `write_guard.main()` wraps its
   body in `except BaseException as exc: deny(...)` so any exception that
   slips past the type guards becomes a deny (exit 0 + block JSON) rather than
   a crash (exit 1 + allow). The umbrella is intentional: governance correctness
   outweighs crash transparency for a blocking hook.

Both defenses are required — the umbrella alone would mask bugs in non-blocking
code paths. The type-guard alone would miss novel exception classes.

**Receipt:** Coverage: `tests/test_hooks.py::TestWriteGuardTypeCoercion` — run via `pytest tests/test_hooks.py::TestWriteGuardTypeCoercion`.

## `tempfile.gettempdir()` Honors `$TMPDIR` — Override Validation Must Not Trust It

**What it is:** `tempfile.gettempdir()` returns `os.environ["TMPDIR"]` when
that variable is set (POSIX). `_validate_audit_override` in
`tools/cc/hooks/_integrity.py` previously added `Path(gettempdir()).resolve()`
to `safe_roots` unconditionally, which meant an attacker-controlled parent
shell that set `TMPDIR=/etc/cron.d` before launching Claude Code would
legitimize `ESPALIER_AUDIT_DIR=/etc/cron.d/silent` as a valid override.

**How you hit it:** Operator inherits a compromised shell environment (CI
misconfiguration, malicious shell profile, `sudo -E`) with `TMPDIR` pointing
at a sensitive POSIX directory. The validation that was supposed to restrict
`ESPALIER_AUDIT_DIR` to safe locations silently expanded the safe set to include
the attacker-controlled path.

**How to avoid it:** `_validate_audit_override` skips the
`gettempdir()` entry when `os.environ.get("TMPDIR")` is set. Hard-coded
fallbacks (`/tmp` on Linux, `/var/folders` on macOS) are always present and
do not consult the env. The pattern generalizes: **never add `gettempdir()`
to a trust list without first checking that `$TMPDIR` is not operator-set**.

**Receipt:** Coverage:
`tests/test_audit_dir_home_unset.py::TestTmpdirPoisoning`.

## `.lower()` Is ASCII-Only and Lies About Path Equivalence on NFKC-Aware Filesystems

**What it is (pre-fix):** `str.lower()` only folds ASCII letters
(A-Z to a-z). On macOS APFS, the filesystem case-folds via full Unicode
tables. A path containing fullwidth Latin letters or Turkish dotted-I
stays unchanged under `.lower()` while the OS resolves it to the
canonical ASCII form. A hook that compares via `.lower()` says
"not protected" for a path the filesystem treats as protected.

**How you hit it (pre-fix):** Submitting a Write tool call with a
`file_path` containing fullwidth Unicode equivalents of protected path
components. `write_guard._is_protected` ran `.lower()` on both sides,
found no match, and allowed the write. a prior bypass class documented 5 attempts in
this class.

**How to avoid it:** Use `unicodedata.normalize("NFKC", s).casefold()`.
NFKC collapses compatibility variants to canonical ASCII; `casefold`
handles the German sharp-s (ss fold) and other multi-char folds that
`.lower()` misses. This is the convention for all three sister sites:
`write_guard._is_protected`, `write_guard._is_allowed`,
`plan_guard._is_exempt`. **Any new protected-prefix check must use the
same pattern** — adding a new site with `.lower()` reintroduces the
bypass class.

**Receipt:** Coverage:
`tests/test_hooks.py::TestUnicodeNormalization` — run via
`pytest tests/test_hooks.py::TestUnicodeNormalization`.

## New Files Under `.espalier/` Need `surface_contract._LOCAL_ONLY_PATHS` Registration

**What it is:** `espalier/surface_contract.py::_LOCAL_ONLY_PATHS` lists
every gitignored per-session file that lives under `.espalier/`. The
release-archive classifier (`classify_release_path`) and the integrity
scanner both consult this list. A new file added to `.espalier/` that is
NOT in `_LOCAL_ONLY_PATHS` will be classified as `"public"` and will
appear as a release-archive denylist offender on the next
`scripts/release_check.py` run.

**How you hit it:** Adding a lock file (`.espalier/.manifest.write.lock`)
for concurrent write serialization without also registering it in
`_LOCAL_ONLY_PATHS`. The `.gitignore` entry keeps it out of source
control, but the classifier does not read `.gitignore` — it reads the
tuple.

**How to avoid it:** Any time a new ephemeral or lock file is placed under
`.espalier/` (or any other managed directory), add the exact relative
path to `_LOCAL_ONLY_PATHS` in `espalier/surface_contract.py` in the
same commit. The check in `tests/test_release_archive_filtering.py`
catches the gap on the next pytest run.

**Receipt:** Side fix (`.espalier/.manifest.write.lock`). The
pattern applies to any future file under `.espalier/`, `cc/`, or other
managed directories that should not appear in the release archive.

## Historical-Narrative Docs Must Be Excluded From `audit_accuracy`

**What it is:** `espalier/claim_extractor.py::EXCLUDED_DOC_GLOBS` lists
documents that the audit-accuracy pass must skip. Documents that capture a
point-in-time narrative (session archives, per-release notes, changelogs)
contain claims that are intentionally historical — they describe what was
true at the time they were written, not current state. Running the auditor
against them produces false positives on every drifted-but-correct historical
claim.

**How you hit it:** `docs/session-archive.md` is the pruned overflow tank for
ESPALIER_MEMORY.md — same release-by-release shape, same reason for exclusion as
`CHANGELOG.md`. Before its exclusion was added (2026-05-16 fix, commit
`6b790b9`), `/audit-accuracy` would FAIL on claims from past sessions that
accurately described the state at the time but had since drifted.

**How to avoid it:** Any doc with the narrative-snapshot shape — historical
session logs, per-release notes, `CHANGELOG-archive.md`, anything that is
"what was true then" rather than "what is true now" — must be added to
`EXCLUDED_DOC_GLOBS` in `espalier/claim_extractor.py` before the file is
committed. CHANGELOG.md and `docs/session-archive.md` are already excluded.
Future additions follow the same pattern.

**Receipt:** `espalier/claim_extractor.py` line ~40, `EXCLUDED_DOC_GLOBS`.
`tests/test_agent_contracts.py` carries the regression for the specific
false-positive that triggered this.

## Over-Permissive `\b(N)\b.*keyword` Pattern in NumericContract Regexes

**What it is:** A `NumericContract` regex of the form `r"\b(\d+)\b.*hook"`
binds a captured number to a keyword, but the `.*` between them matches
across arbitrarily long spans — including table-row boundaries in ESPALIER_MEMORY.md
and docs that list multiple unrelated numbers on the same rendered line.

**How you hit it:** the hook-count contract in
`tests/test_agent_contracts.py::TestHookCountConsistentAcrossDocs` once used this
shape (a single `\b(\d+)\b.*hook` regex, before it was split into the module-level
`_HOOK_NUMERIC_RE` / `_HOOK_WORD_RE` / `_HOOK_ALL_RE`). The `.*hook` tail matched
across entire ESPALIER_MEMORY.md table rows that happened to contain "hook" elsewhere
on the line, binding the wrong
number to the hook-count contract. The test registered false passes on stale
counts and false failures on correct entries. The same mis-shape recurred in
an earlier review's dot-separator finding (a dotted version prefix such as `v.10`
slipping past a previous lookbehind).

**How to avoid it:** Anchor the keyword IMMEDIATELY after the captured number
with at most one intervening adjective. Use the `_HOOK_WORD_RE` pattern shape at
`tests/test_agent_contracts.py::_HOOK_WORD_RE` as the reference. Specifically:

- BAD: `r"\b(\d+)\b.*hook"` — `.*` matches across table rows
- GOOD: `r"\b(\d+)\s+(?:\w+\s+)?hooks?\b"` — one optional adjective, then `hooks?`

For any new `NumericContract` that binds N to a keyword, test the regex
against a multi-line ESPALIER_MEMORY.md snippet containing the number in an unrelated
context before committing.

**Receipt:** `tests/test_agent_contracts.py::_HOOK_WORD_RE` (`_HOOK_WORD_RE` pattern).
Fix landed in commit `11b4e4d`.

## Pinning is verification, not modification

`espalier freshness pin <id>` records the current SHA as the operator's
assertion that the fragment is accurate. It does not verify anything
mechanically. Pinning a stale fragment without actually reading the
fragment + the bound code is the documented anti-pattern: it makes the
signal green without making the doc correct.

Pinning workflow:
1. Read the fragment.
2. Read the bound code at HEAD.
3. Confirm the fragment's claim matches.
4. If yes: `espalier freshness pin <id>` and commit the manifest change
   alongside the fragment edit.
5. If no: fix the fragment first, commit, *then* pin.

Step 5's order is enforced, not advised: the pin refuses while a bound
path has uncommitted changes (`--force` overrides), because a pin at HEAD
over a bound with uncommitted changes vouches for a verification that
never happened — and `check` read such a pin `fresh` for as long as the
change stayed uncommitted, since drift is counted in commits. The scan now
reads an uncommitted bound as `stale` with the paths named. On a tree that
commits its manifest (this one), a literal edited by hand in the manifest
beside an unchanged pin reads `stale` the same way, and `pin --all` refuses
to re-stamp it; `init` gitignores `.espalier/` on an adopter tree, so there
the hand-edit comparison stands down and `check` says so.

**Reason:** Same closed-loop-verification discipline as the
audit-accuracy contracts.

## Bound-change invalidates pin

Changing the `bound=` value in a fragment marker invalidates its pin,
regardless of whether the SHA in the manifest is current. The defense
has two halves — scan side and pin side — so the bound diff is visible
at the moment the operator is making a decision.

**Scan side** (`espalier/scanners/freshness.py::scan_repo`):
the scanner compares manifest-stored bound paths against fragment-marker
bound paths and forces state to `critical` on mismatch with a
`fragment-id rebinding attempt` message naming both bounds.

**Pin side** (`espalier/freshness.py::pin_fragment` and CLI
`espalier freshness pin --force`):
`pin_fragment` refuses to silently overwrite a different bound — it
raises `RebindingRefusedError`. Operator must explicitly pass
`force=True` (CLI: `--force`) to consent, after seeing the prior bound
and new bound side by side in the error message. `pin --all` does NOT
accept `--force`; it skips bound-drift cases, reports them with a
structured `skipped` list, and exits 1 — bulk seeding must not silently
rebind, so each rebind requires a per-fragment review.

The combined defense: an attacker (or a hurried edit by future-you)
cannot redirect a fragment to a never-changing path (e.g.,
`docs/external/cc-hook-protocol.md` or a deleted file) and then clear
the resulting critical finding by re-running `pin --all`. The signal
lying about freshness, and the operator clearing the signal without
seeing why, are blocked at separate points.

## Policy vocabulary is closed; unknown = critical

`policy=` values are enumerated: `verify-on-touch`, `weekly`,
`numeric-contract`. Any other value (typo, attacker-planted, future
policy not yet implemented) classifies the fragment as `critical` with
the message "unknown policy."

Fail-closed by design — an unknown policy must NOT default to `fresh`
because a typo or a malicious marker would suppress otherwise-valid
drift detection.

## ReDoS budget receipt

<!-- espalier:fragment id=redos-timeout-budget-ms
     bound=tests/test_redos.py::_BUDGET_MS
     policy=verify-on-touch -->
<!-- espalier:fragment id=redos-worst-case-payload
     bound=tests/test_redos.py::_WORST_CASE_BODY_LEN
     policy=verify-on-touch -->
**Receipts:** the ReDoS regression suite documents a 100 ms per-pattern
design budget on a 30000-byte worst-case payload; the line it asserts is
the CI-safe ceiling, a named constant no less than ten times a dated floor
(`tests/test_redos.py::_CI_SAFE_BUDGET_MS`; the rule is stated at that
file's constants block and derived by `tests/test_proof_tier.py`).
Constants live in `tests/test_redos.py::_BUDGET_MS` and
`tests/test_redos.py::_WORST_CASE_BODY_LEN`; freshness fragments
`redos-timeout-budget-ms` and `redos-worst-case-payload` pin both at
HEAD so a refactor that loosens either fails the freshness gate
instead of slipping in unnoticed.

**Reason:** a freshness fragment binds these ReDoS constants, which the
NumericContract registry could only pin against the test file itself.

**The ReDoS classes that lurk in `_bash_patterns.py` extraction regexes.**
Any regex run by `_candidate_paths_from_bash` over attacker-controlled command
text has these distinct super-linear traps, and the 32 KB `_cap_for_scan` budget
bounds *polynomial* cost but NOT catastrophic backtracking (a quadratic regex
still hangs for seconds well inside 32 KB):
1. **Multi-quantifier overlap within one regex.** `_PERL_OPEN_RE` needed THREE
   iterations — a tail whitespace overlap, then a mode-char overlap the first
   fix *introduced* (`[>+]` ⊂ `[^'"\s]`), then a prefix `\s*\(?\s*\S+` split.
   Rule: every adjacent quantifier pair must be **mutually exclusive** (the same
   discipline as the outer interpreter bodies' `\\.|(?!\1)[^\\]`).
2. **`finditer`-retry on a repeated verb-anchored regex.** `\bVERB…<span>…<token>`
   (sed -i / dd of= / tar -C / cp|mv|install -t / git checkout -- / PS -Path) is
   quadratic on `VERB VERB VERB…`: `finditer` retries at each space-separated
   verb, each scanning toward an ABSENT token. A word-boundary lookbehind does
   NOT help (space-separated verbs are all word-starts) — **bound the span**
   (`{0,512}` chars / `{0,64}` tokens). For a single repeated literal with no
   separator (`openopen…`), the lookbehind DOES help (one valid start).
3. **Consumer cost, with every regex linear.** A per-match consumer whose
   segment is the whole prefix before the match is O(n) per match and quadratic
   over a flood of matches; re-deriving that segment per match makes it cubic.
   Both PowerShell arms carried this for weeks — the pipe arm read the whole
   prefix per opener (7 s on an 856-byte command, past the hook timeout) and
   the masker's re-parse lookbehind sliced and end-anchored the whole prefix per
   literal span (1.6 s at 30 KB, and the masker fronts every PowerShell tier).
   An isolated-regex row cannot see it: bound the segment at the nearest real
   separator, build one boundary list per call and bisect it, cap the lookback,
   and time the flood **through the entry point the hook actually runs**
   (`tests/test_redos.py::_WALKER_CONSUMERS`), with a must-trip control so a
   consumer that short-circuits cannot pass on timing alone.

4. **A repeated group whose alternation carries a bare run arm.** A quote-aware
   target written as a repeated group of quoted arms plus one bare-run arm is
   `(a+)+`: the bare arm partitions one token every way, and the enclosing
   command-position repetition explores all of them on a failing match. An
   ordinary thirty-character redirect target wedged the PreToolUse path for
   over twenty seconds, and a wedged hook is not a deny (the tool times it out
   and runs the command). Spell the bare arm as a SINGLE character class, one
   character per iteration, so each position has one parse. The rows that
   prove it need a **failing** tail, a long **bare inner token** (not only a
   repeated short one, which is the axis every earlier row varied), and a
   witness that the pre-fix form blows the budget, which is the only thing that
   proves the row reaches the shape at all (2026-09-14).

⚠ **"Bound the span" is the remedy for class 2 only.** Where the cost is a
*product* — matchers × opener positions × run length — a token bound was
measured twice and failed both ways: it left a 28 KB opener-word flood at 20 s,
and it turned a real command carrying sixty-five switches before its payload
from a deny into an allow on both shell legs. What worked was removing the
ambiguity that gave a token two parses (a switch value may not be a re-parsing
opener word, `_PS_REPARSE_OPENER_WORDS`; a slash-led token is a switch lead XOR
a value lead): 24 s to 70 ms, run left unbounded. Rule: when a witness flood is
quadratic, find the token with two parses and take one away — a bound on a run
a real command can fill is a coverage hole with no receipt, and a must-deny row
at the padded length is what reds a future bound.

When adding/editing an extraction regex: add it to `tests/test_redos.py` and
earn-the-red the repeated-verb, unclosed-tail AND long-bare-inner-token shapes
BEFORE trusting it, each against a failing tail. The derived-regex row drives
`search`, so a pattern whose head can start at any position of a leading blank
run is quadratic on a blank flood even when the hook only calls `match`: refuse
the blank-led start with a lookbehind such as `(?<![ \t])` (2026-09-15). Do
NOT route the rm/symlink SAFETY checks through `_cap_for_scan` — they are
deliberately uncapped (linear-and-fast) because a head+tail cap would let a
catastrophic delete hide in the dropped middle.

## Rendered Template Output Is an Unaudited Surface

`espalier init` renders `CLAUDE.md` into adopter repos from a template
string in `espalier/cli.py::_build_claude_md` (wrapped by the public
helper `render_canonical_template("claude")`). Static-doc tests
(`tests/test_documented_claims.py`) audit *this repo's* docs — they do
NOT render the template and inspect its output. The rendered string is
what adopters see; this repo's CLAUDE.md is what tests see. Drift
between the two is invisible to the test suite.

Mitigation: render-time tests (`tests/test_render_template.py`) call
the public helper `render_canonical_template("claude")` and bind the
rendered output to external pins (`docs/external/cc-hook-protocol.md`).
Using the public helper (rather than the private `_build_claude_md`)
keeps the test stable across internal-signature refactors. New claims
in rendered templates need a render-time assertion alongside the
static-doc one.

History: fixed `"2 = block (JSON on stdout)"` shipping in every
adopter's CLAUDE.md since the template was authored — the opposite of
the project's own channel-XOR protocol.

## Folder CLAUDE.md ladder is instruction-layer, not hook-layer

Claude Code injects subfolder `CLAUDE.md` content when Claude touches
files in those subtrees. This is **instructional context**, not
mechanical enforcement. A router that says "Before writing or editing
in this folder: read X, run Y" is a hint to Claude — not a gate.

The actual mechanical gates remain `write_guard.py` (PreToolUse denial
of protected-zone mutations) and `plan_guard.py` (PreToolUse denial of
source edits without an active plan). Don't expect a router's preamble
to prevent a write — it can't.

**Test:** `tests/test_folder_claude_md_routers.py` pins router SHAPE
(size, headers, link integrity) but not router BEHAVIOR (it can't
assert "Claude followed the procedure"). Behavior is emergent from
instruction; enforcement is emergent from hooks.

**Mitigation:** when a router's procedure is genuinely critical
(must-run-before-mutation), back the instruction with a hook. Don't
rely on the router alone.

## Producer/consumer parity drift

When a producer module emits a token (config key, event name, file
extension, marker string) that a downstream consumer never reads, OR
when the consumer expects a token the producer never emits, the
divergence is silent. Each module looks internally consistent on
isolated review; the behavior just no-ops at runtime.

**Symptom:** a feature appears wired but doesn't fire. The producer
logs the token. The consumer's branch on that token never executes.
Integration tests pass because the path they exercise is the
*intersection* of the two vocabularies, not the symmetric difference.

**Observable signal:** registry-class contract — extract both
vocabularies via AST walk (not substring grep), assert set-equality.
See `tests/_contracts.py::StringListContract` and the earlier marker-
parity precedent.

**Mitigation:** when authoring a new producer/consumer pair, register
a parity contract in the same commit. Don't rely on integration tests to
discover the divergence — they only catch the case where the
intersection happens to include the token actually exercised.

## State-machine transition coverage

When a predicate references a state no transition reaches (phantom
predicate), or a transition leaves a state no predicate accepts
(orphan state), the contract is invisible. The predicate compiles,
type-checks, and may pass static review — but the runtime path it
claims to guard never fires.

**Symptom:** a guard helper named `gate_passed(gate)` exists, looks
sensible, and is referenced from callers. The state field it inspects
has domain `{"pass", "fail", "skipped", "pending"}` — but the
predicate returns `status == "passed"` (with the trailing 'ed') and no
transition ever writes that string. The guard returns `False`
everywhere, silently disabling the gate it was meant to enforce.

**Observable signal:** `tests/_state_machines.py::STATE_FIELDS`
registry — each state field's full value domain is enumerated, and
each predicate has a truth-table contract over that domain. Phantom-
predicate detection is mechanical.

**Reference:** Three phantom predicates were surfaced
(`gate_passed`, `is_kill_switch_set`, `_maintenance_mode_active`) and the
helpers authored inline. A registry that only **declares** truth tables —
where the contract test checks shape (value-in-domain,
expected-is-bool) but never **calls** the predicates — would pass even on a
flipped registry value (`gate_passed['pass']: True→False`).
`test_predicate_binding_matches_registry` calls each pure
predicate over its full domain and binds it to the registry, so the contract
genuinely binds them. The file-reading `_has_active_plan` twins stay bound by
the executing `tests/test_task_router.py::TestSisterPredicateParity`.

## Stop-gate dormancy on non-pytest fingerprints

When `reports/repo_fingerprint.json::test_commands` contains
non-pytest commands (`go test ./...`, `npm test`, `cargo test`),
Gate 1 of `stop_gate.py` previously fell back to harness-default
test paths that don't exist in adopter repos — pytest returned
`collected 0 items` and the gate reported pass. Same shape as
a prior fix a prior bypass class: fingerprint shape mismatch with hard-coded consumer
expectations silently no-ops the gate.

Post-fixb, dormancy is visible: `_resolve_core_tests` returns
a `ResolvedTests` tri-state with `status` in
`{"ok", "dormant_non_pytest", "dormant_no_paths", "ok_env_override"}`.
The Gate 1 caller writes the dormancy note to stderr, and the
SessionStart banner appends a one-line warning when
`ESPALIER_STOP_GATE=full` is set against a dormant fingerprint.

To enable Gate 1 for non-pytest repos, set
`ESPALIER_STOP_GATE_TEST_CMD=<your test command>` in the parent
shell before launching Claude Code. The command runs via
`subprocess.run(shlex.split(cmd))` — `shell=False`, no metacharacter
expansion. Pass arguments space-separated; quote strings that
contain spaces. Example:

```bash
ESPALIER_STOP_GATE_TEST_CMD="go test -short ./..." \
  ESPALIER_STOP_GATE=full \
  claude
```

**Threat model:** the env var is set in the parent shell BEFORE
`claude` launches; Claude Code inherits the env at spawn time. Mid-
session `export` does not reach already-spawned hooks. Same posture
as `disableAllHooks` / `ESPALIER_MAINTENANCE_MODE` — operator-side,
not LLM-injectable.

**Backed by:** `tests/test_stop_gate_dormancy.py`.

## JSON-in-`description:` is the wrong shape for structured reasoning

`ReasoningEntry.description: str` is rendered via
`_sanitize_for_priming(description)` with `_MAX_FRAGMENT_LEN=200` —
strings over the cap are truncated. Anyone who tries to overload
`description:` with a JSON blob (e.g., a fifth `kind` enum value
carrying a serialized dict) hits this footgun: the truncation cuts
the JSON mid-key, the next session's load fires
`json.JSONDecodeError` deep inside the priming render path, and the
fragment is silently dropped.

An earlier proposal floated exactly that shape (kind
`action_justification` with a JSON blob in `description:`). A later
revision instead added a typed `action_justifications: list[ActionJustification]`
field with 8 real columns and a validator. Every field has its own
length limit enforced at recording time; nothing goes through
`_sanitize_for_priming`.

**Sister-class:** the same shape problem hit blueprint storage in
an earlier stop-gate fingerprint review (Bash command strings as
"fingerprints" silently truncated).
The general rule: when an entry has multiple structured attributes,
use typed columns, not a string overload — even if the overload
"looks easier" in a quick draft.

**Backed by:**
`tests/test_action_justifications.py::TestNoJSONInDescription::test_no_kind_action_justification`
(scans argparse `--kind` choices for the rejected enum value).

## Annotate claims with canons or label them convention — don't leave them naked

A load-bearing claim (CLAUDE.md priority order, HOOK_ASSUMPTIONS
Backed-by, CONVENTIONS thresholds) must carry two annotations:

```markdown
<!-- canon: tests/test_x.py::TestY -->
<!-- claim-id: descriptive-slug -->
```

The pinned test must echo the slug:

```python
# pins: claim:descriptive-slug
class TestY:
    ...
```

The verifier (`espalier/scanners/canon_verifier.py`) walks
claims and verifies the bidirectional slug match exactly — no fuzzy
word overlap.

Allowed canon values:

- `tests/<path>::<name>` — real test (class or function)
- `espalier/<module>.<symbol>` — runtime canon (slash-separated path,
  single dot before symbol)
- `docs/external/<file>` — external pin
- `convention` — explicit honest non-canon
- `dormant: <reason >=12 chars>` — structurally prepared, unwired

Claim surfaces are explicitly registered in `CLAIM_SURFACES` —
adding a new claim surface requires explicit registry update (the
verifier flags `UNREGISTERED_SURFACE` for any doc with canon
annotations outside the registry). Docs that mention the annotation
syntax in PROSE (typically inside backticks) without carrying real
annotations are exempted via `EXEMPT_PROSE_FILES` (cap 5).

Enforcement is default-ON: the 7 enforcement tests under
`tests/test_canon_verifier_contract.py` run on every pytest invocation
(they were un-gated when the default flipped). The
`ESPALIER_CANON_VERIFIER=enforce` env var is retained only as a debug
re-gate opt-in — re-add `@enforcing_only` to a single test to skip it
while debugging. Do not read the env var as "off by default": the
backstop that catches a mismatched or dropped canon
(`test_no_pins_mismatch`) is live.

The v3 originating-failure-mode close: a NEW load-bearing claim
added with NO annotation is detected by `CLAIM_DISCOVERERS`
(per-surface structural shape walkers), so the annotation-driven
walk doesn't silently accept naked claims on registered surfaces.

Multi-pin caveat: `_extract_pins_slug` returns the FIRST pins-slug
within ±10 lines of a declaration. One test class can only be the
canon for ONE doc claim. If multiple doc claims need to point at the
same mechanical witness, annotate the strongest claim with the test
and the others with `convention` — same pattern as the Core Rule
1 / Priority 1 demotion to `convention` (Assumption 1 carries the
TestHookProtocolXOR pin).

Multi-canon ordering: order-independent. A claim needing MORE THAN ONE
canon may list its `<!-- canon: -->` lines and its `<!-- claim-id: -->`
in either order — `_find_adjacent_claim_id` binds each canon to the
claim-id in its own ANNOTATION BLOCK (the contiguous blank/comment run
between the claim text above and the next real line below), so a
canon-first block no longer mis-binds its top canon to the PREVIOUS
claim's claim-id. Core Rule 4 (the memory claim: line-cap +
SessionStart-digest) is the only multi-canon claim today and uses the
natural sibling order (canons, then claim-id). Its completeness pin
(`tests/test_core_rule_4_canon_completeness.py`) still asserts BOTH
canons resolve PINNED — that guards against a *dropped* canon, which the
generic contract cannot see (the surviving canon still covers the claim
line). Historical note: before this block-bounded bind the parser checked
the line ABOVE before below at each ±distance, so multi-canon claims had
to be written claim-id-FIRST; that workaround is retired.

Table-cell annotations: HTML comments INLINE in a markdown table row
are recognized — `_build_covered_claim_lines` detects embedded
annotations (canon comment with surrounding cell content) and binds
to the annotation's own line rather than the line above.

This is the structural close on canon-vs-claim drift (a live-fire
surprise → manual reconciliation → generative defense).

Related: NumericContract (numeric drift); RETIRED_TERMS
(lexical drift); the canon verifier is the epistemic analog.

## Fix without regression test entrenches the pattern

A fix that verifies via "re-render the doc" or "re-run scorecard"
confirms the *current* state, not the next drift. The same regression
re-enters on the next refactor unless a contract test pins the
expected-correct shape. Doc fixes are not exempt — they're the most-
drifted surface.

Higher-leverage form for lint findings: pin the rule code in
`pyproject.toml [tool.ruff.lint]` AND enforce in CI. One config change
blocks the whole bug *class* instead of one instance. See
`harness-guard.yml::ruff-lint` + `tests/test_ruff_config_includes_security_rules.py`.

When unit tests are still needed: for semantic concerns the linter
can't fully validate — URL-scheme allowlists,
member-validation depth for tar/zip extracts, audit-
swallow noqa-reason shape on hooks.

**Hook S110 caveat:** PreToolUse / ConfigChange / PostToolUse hooks
treat stderr as the deny reason per
[docs/external/cc-hook-protocol.md](external/cc-hook-protocol.md). A
naive S110 fix ("replace `except: pass` with `print(..., file=sys.stderr)`")
breaks the hook protocol's channel-XOR rule. The correct disposition
for `_integrity.append_audit` swallow sites is per-line
`noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise`.
An AST-walk contract
(`tests/test_hook_audit_noqa_annotations.py`) pins the noqa
reason shape so future ruff bumps can't silently strip the suppression.

Generalizable beyond Python/ruff: the same pattern applies to mypy
(type-error rule pinning), bandit (security rule), markdownlint (doc
formatting), codespell (typo classes), deptry (unused deps), vulture
(dead code), semgrep (custom AST patterns). Each new tool spike should: (1)
install + run, (2) fix HIGH findings, (3) pin the rule set in
pyproject + add CI gate, (4) write per-fix unit tests only where the
analyzer can't fully validate the fix. Step 3 is the regression test;
without it the bug class can re-introduce silently.

## The keystone speed-bump must be a syntactic proxy, cap-exempt, and per-file-keyed

CP-GATEWEAKEN (`tools/cc/hooks/_speedbump.py`) is the speed-bump that
fires when an edit weakens a blocking hook's deny path. Three mechanism settings
on its registry row are each load-bearing — drop any one and the gate-that-guards-
the-gates fails open:

- **Syntactic pre-edit proxy, not a "deny-count DROP."** The actual count delta
  is not cheaply computable at PreToolUse — the edit has not applied, and the
  read-the-file form was rejected. The predicate fires when `new_string`
  reduces a deny-token count vs `old_string` (`any(old.count(t) > new.count(t))`).
  Caveat: this is **removal-only** — a deny line *commented in place* keeps the
  token substring, so its count is unchanged and the proxy does not fire (catching
  that cheaply would need a file read; the design accepts the gap).
- **`cap_exempt=True`.** The global session friction cap must never be able to
  suppress the keystone — else a storm of benign bumps fails it open (blueprint
  §11 #1). Pinned by `test_fires_after_cap_exhausted`.
- **Per-`(file)` flag-keying.** A `MAINTENANCE_MODE` edit-burst across the four
  guard files must fire once **per file**, not once total — a per-checkpoint-ID
  one-shot would fire on edit 1 and let edits 2..N weaken other gates silently
  (blueprint §11 #4). Pinned by `test_two_guard_files_fire_twice`.

And the call site is **before** the maintenance gate in `write_guard`, so
it fires in the exact session class — harness self-edit under MAINTENANCE_MODE —
where the protected-zone check is bypassed and gate edits arrive in bursts. Note
the `SpeedBump.fires_in_maintenance` field is **inert** (`check()` never reads it);
the property comes from call-site ordering, pinned by the integration test, not
the field. Mirror of the recall engine's defensive floor (the cap-exempt keystone: safety-critical fires are never budget-suppressed, keyed per-file).

## An MCP-tool speed-bump predicate must parse the `__` segments, match the verb as a leading token, and defer local-fs ops to write_guard

CP-MCP-SIDEEFFECT nudges before an MCP **external** side-effect write
(`send`/`delete`/`trigger`/`post`/...) because `plan_guard` does not gate `mcp__`
at all. Three traps, each pinned by `tests/test_speedbump_v1_1.py`:

- **Parse `__`, don't regex `\b` across it.** The v1 draft regex
  `mcp__[^_]+__.*\b(verb)` was dead twice over: `[^_]+` cannot match a server
  segment that contains underscores (`mcp__claude_ai_Gmail__send_email`), and `\b`
  never matches a verb right after `__`/`_` because underscore is a regex *word*
  character — so `\bsend` fails exactly where every real action verb sits. It
  false-silenced even the single-segment control `mcp__slack__send_message`. Fix:
  `tool_name.split("__")`, take the final (action) segment, `.match` the verb.
  Pinned by `TestCpMcpEarnedAgainstDeadRegex` (runs the dead regex inline and
  asserts it false-silences where the live predicate fires).
- **Match the verb as a complete leading token (`(?:_|$)`), not a bare stem.** A
  bare `(send|post|update|move|archive|...)` over-fires on read names that merely
  *start* with a verb substring — `postpone_event` (`post`), `updates_feed`
  (`update`), `movements` (`move`), `archived_items` (`archive`) — silently
  contradicting the predicate's own bias-toward-silent posture. `(?:_|$)` fires
  `update_record`/`create_preview` but stays silent on `updates_feed`. The accepted
  residual is the *other* direction: verb-not-leading forms (`bulk_delete`) fall
  silent — the intended v1.1 under-fire. Pinned by `TestCpMcpOverFireGuard`.
- **Defer local-filesystem MCP ops to write_guard.** `mcp__filesystem__move_file`
  matches the `move` verb but is a *local* op carrying a path-shaped field
  (`source`/`destination`) — write_guard's protected-zone domain
  (`write_guard.check_mcp` / `_deny_mcp`), not an external side effect. The
  speed-bump call site (`_speedbump.check` in `write_guard._run_main`) runs
  *before* that hard-deny, so without a guard the soft nudge preempts
  the security deny, producing a confusing soft-then-hard two-stage and a factually
  wrong "leaves the repo" reminder. Fix: if `tool_input` carries any
  `_hook_utils.MCP_PATH_FIELDS` value, return silent (defer) — sister to CP-RMRF
  deferring to the `rm` hard-deny. Pinned by `TestCpMcpDefersToWriteGuard` and the
  pre-existing `test_blocks_mcp_move_via_destination_field` (which now passes
  unchanged because the hard-deny owns the move in one round).

Posture: **bias toward silent** (under-fire) on the first ship — an MCP write is
external-irreversible but not the PyPI-burn tier, and a false nag on a benign read
trains re-issue-without-reading. Keying was id-only (one flag for the whole class,
one nudge per session) until 2026-09-13, when `flag_key` gained the tool name beside
the tool input and `_mcp_tool_key` keyed the row per full `mcp__<server>__<action>`
name (DEF-8): the second distinct side-effecting tool of a session now earns its own
nudge, an identical re-issue still passes, and the CP-GATEWEAKEN keystone's per-file
key moved to the new arity with it.

## A recall-engine rule is FRICTIONLESS — it injects, it never denies

`_reinject.py` and `_speedbump.py` are siblings with OPPOSITE postures riding the
same already-wired PreToolUse `*` call site in `write_guard`. The speed-bump *gates*
an action: `_speedbump.check(...)` returns a deny reason and the call site does
`return deny(...)`. The reinject *enriches* context: `_reinject.check(...)` returns
advisory `additionalContext` text and must NEVER convert to a deny — that would
double-spend the friction budget and break the per-turn ceiling. Keep the two channels
separate: in `write_guard._run_main`, `_reinject` emits ONLY on the fall-through allow
path, never beside the `_speedbump.check` call, because that point precedes
three deny branches and a second stdout JSON colliding with a later `return deny(...)`
is a channel-XOR violation.

Two further traps for the next reinject rule:
- **The allow side is multi-exit.** `write_guard._run_main` returns-allow at several
  points (read-only, maintenance, the mutation-tool branches, the fall-through
  allow-exit). A PreToolUse reinject payload emitted only at the fall-through
  allow-exit is BEST-EFFORT — a rule
  keyed on a read-only tool or a `Write`/`Edit` (which return earlier) silently drops and
  re-fires next turn. There are currently zero PreToolUse rows (a proven no-op); a later
  one must emit on that rule's actual trigger allow-exit, never beside a deny.
- **`additionalContext`-only, no `permissionDecision`.** Emit
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ...}}`
  WITHOUT `permissionDecision: "allow"` — per `docs/external/cc-hook-protocol.md`,
  `additionalContext` reaches the model on `PreToolUse` next to the tool result, while an
  explicit `allow` could auto-approve a tool that should have prompted the user.

The orientation row is ONE registry row whose render returns 1–3 conditional lines as a
SINGLE payload, NOT three rows — three same-event non-exempt rows at one priority
self-starve against `REINJECT_PER_TURN_CAP=2` (the 3rd is clipped). And the session
counter (`reinject_count`) MUST be cleared in `session_start._clean_state_flags`
(`reinject_*` glob, mirroring `speedbump_*`), else the non-exempt orientation row burns
one slot per session and goes permanently silent after ~`REINJECT_SESSION_CAP` sessions.

## Advisory reinject rules need the same self-host gate as observers

Any PostToolUse reinject rule whose witness names engine-internal paths
(`cli.py::…`, `examples/dogfooding/`, `tests/…`) is **self-host-only** guidance —
its triggers (creating a `.claude/commands/<name>.md`, a `tools/cc/hooks/<name>.py`)
exist in every adopter repo, so without a gate an adopter is injected mid-session
with a sister-site list about a source tree they do not have. Route the
`_reinject.check("PostToolUse", …)` **call site** through
`_hook_utils.is_self_host_repo(root)`, like the born-weak observer next to it in
`post_write_check._run_main`. The gate is on the *call site*, not inside `check()`:
the generic paths (SessionStart/UserPromptSubmit orientation, PostToolUseFailure
Rule A) ride *other* hooks and must stay ungated, so gating inside `check()` would
wrongly suppress them too. A new sync row inherits the gate for free — do not add
an adopter-generic rule to the PostToolUse set (it would be silenced off self-host).

## A multi-surface-sync reinject carries its witness set as DATA, not prose

The value of the sync rules (`_reinject.py` — new-hook-without-wiring,
command-file-sync, integrity-parity) is the COMPLETE enumerated sister-site list the model
receives mid-session, before the offline count contracts go red. A vague "remember to update
the other surfaces" is banner-noise; the `_HOOK_COUNT_WITNESSES` / `_HELPER_COUNT_WITNESSES` /
`_COMMAND_SURFACE_WITNESSES` data constants — earned against real repo history (the
10→12-hook diff) — are the payload.

The witness set is itself a multi-surface SoT (sister to the thing it guards), so it is
contract-bound, not hope-bound: `tests/test_reinject_sync.py::TestWitnessSetParity` reddens
when `_CANONICAL_HOOK_SCRIPT_NAMES` drifts from
`surface_contract.get_canonical_hook_scripts()` (the moment a 13th hook is wired), when a
named surface path stops resolving, or when a witness list is silently shortened. When a
future pack adds a surface to the hook-count contract, add it to the witness data too — the
parity test goes red if you forget.

Two predicate constraints, both forced by the PostToolUse event shape:
- **Post-state only.** The predicates read `content`/`new_string`; they MUST NOT depend on
  `old_string` — it is not pinned on PostToolUse (`docs/external/cc-hook-protocol.md` is
  silent) and no other hook reads it there. Differential cases (a DELETED assert, a WIDENED
  `raises`) belong to the offline `test_loosening` scanner, which has the git diff at `/scan`
  + stop_gate. A reinject that "detects a deletion" from post-state alone is structurally
  incapable — the CP-MCP "wired-but-dead" class.
- **`Write`-only for the new-file rules.** The new-hook and command-file rules fire on any `Write` to the path, not
  "new file" — that is unknowable post-write (the file always exists by then). `Write` is a
  full create-or-replace and typo fixes are `Edit`, so the witness checklist does not dump on
  a one-character edit; the small over-fire (a full rewrite of an existing hook) is itself
  drift-worthy.

## A pushed generative exemplar without a parity test is a drift bomb — and most "canonical shapes" have no single byte-source

The recall engine has a *generative* face (the inverse of the sync
face): at `UserPromptSubmit`, inject the canonical exemplar BEFORE the artifact is
born, so the model lands the right shape on the first draft. The value of an
auto-injected exemplar is that it matches the *current* canonical shape; a hardcoded
copy silently rots the moment the real artifact changes — the same multi-surface-drift
class the sync rules guard against, pointed inward.

The rail: a `ReinjectRule(face="generative")` may be
`push_eligible=True` (auto-inject) ONLY if a red-on-violation parity test re-derives it
from its canonical source. `tests/test_exemplar_parity.py::test_rail_holds_for_shipped_registry`
enforces `{pushed generative ids} ⊆ {parity-tested ids}`, and `test_rail_is_non_vacuous`
proves the gate BITES (a synthetic push-eligible rule with no parity test is flagged —
earn-the-gate, so the live pass is not vacuous). The gate is also MECHANICAL, not just
test-enforced: `_reinject.check()` skips any `face=="generative"` rule with
`push_eligible=False`, so a pull-only row mistakenly placed in `REINJECTS` never fires.

The trap: most canonical shapes have NO single byte-source. A scanner's contract lives
across the scanner + its earn-fixture + its negative corpus + its test; a hook's posture
across channel-XOR + stdin + zero-imports; a pack skeleton is per-pack-variable prose.
None can be byte-derived from one file, so none can be parity-pinned — they ship
**pull-only** (`_reinject.EXEMPLAR_MAP`, served by `/recall`, never auto-injected).
All five named exemplars ship pull-only for exactly this reason. Template-file
sourcing (a committed copy as the "canonical" source) was rejected: a template is a second
copy that itself drifts, relocating the drift rather than killing it. When a future pack
DOES add a push exemplar it must also intent-anchor the prompt predicate with a negative
test (UserPromptSubmit fires on EVERY prompt — a bare keyword false-fires on meta-prompts
that merely quote the trigger and trains the model to ignore the channel) and account for
the SHARED `REINJECT_SESSION_CAP` (a non-exempt generative fire consumes a session slot
shared with the sync witnesses).

## A pull-recall engine must SUPPRESS on no-match — and THIS one does not (DEF-609)

The failure mode of a naive top-1 retriever is confident-but-wrong: every query has
*some* highest-scoring doc, so a nonsense or near-miss query still "recalls" an
irrelevant snippet — and one bad recall trains the operator to distrust `/recall`
permanently. Suppression is therefore the load-bearing behavior, not ranking.

**⚠ That is the principle. This repo's engine does NOT achieve it, and the gap went
unnoticed for months because the test measured the easy half of its own contract
(`DEF-609`, 2026-08-19).** Keep the heading — it is the right thing to aim at — but read
the rest before trusting a `/recall` hit.

`_recall.py` gates on the **half-corpus document-frequency line**: a matched query term
counts as topical only if it appears in at most half the docs (`df ≤ N/2`). That
suppresses a query sharing NO vocabulary with the corpus. It does not suppress ordinary
off-topic English. **Measured on the live corpus: gibberish suppressed 1/1, ordinary
off-topic English leaked in full.** A baking-recipe query returns a `write_guard`
Bash-string-literal edge; a restaurant-review sentence outscores *every* legitimate query
in the test suite's own must-answer arm, by roughly an order of magnitude.

> **⚠ The example queries are deliberately NOT quoted verbatim here, and that is a
> load-bearing omission — not fussiness.** This section is itself part of the recall
> corpus. The first draft of this entry quoted its own off-topic examples in full, and
> the entry promptly became the top-1 hit for **6 of the 29** off-topic queries in the
> arm, including both of the ones it quoted — displacing the very documents it cites as
> evidence and invalidating three of its own numbers on landing. Caught in review, not by
> the author. The literal strings live in `tests/test_recall.py::_OFF_TOPIC_ENGLISH`,
> which is not corpus-scanned; `test_suppression_entry_does_not_capture_its_own_examples`
> pins the entry against re-acquiring them. **The general rule: a document inside a
> retrieval corpus cannot quote the queries it is about.** This is
> [§18](FAILURE_MODES.md) — the artifact you author to describe a fix is itself
> unverified — and the author committed it while writing the entry that names it.

**Why the old pin passed anyway:** gibberish tokens have `df=0` and are dropped *before*
the floor is consulted, so the floor was never exercised by the test that claimed to earn
it. A guard blind exactly the way it claims to see — see
[a new guard is blind the way it claims to see](sharp-edges/a-new-guard-is-blind-the-way-it-claims-to-see.md).

**AND NO FLOOR FIXES IT — this is a measured negative result, not a deferral.** Nine
mechanisms were driven through the real `recall()` path against two 26+ query arms.
Every one has a negative margin (the best off-topic query outscores the worst legitimate
one), so no threshold exists:

| mechanism | gap | why it fails |
|---|---|---|
| IDF coverage ≥ τ | −0.571 | suppresses on out-of-vocabulary tokens, not topic |
| whole-identifier / phrase floor | −1 | gates typing style, not subject |
| inverted `df ≥ K` (and two-sided band) | −164 | points the wrong way; refits unstably |
| score margin (`top1/top2`, z, n-within-5%) | −2.899 | inverted |
| query-shape (function words, code tokens) | −0.607 | no signal at all |
| doc-side title / filename anchor | −1 | deletes ~74% of real operator questions |
| boolean composition of the best two | ≤0 | `OR` unions the leaks, `AND` unions the misses |
| background-English surprisal | −6.000 | measures "is this specialist prose", not "is this *our* domain" |
| query-term PMI co-occurrence (joint) | −3.124 | an everyday breakdown-complaint sentence is a tighter co-occurrence cluster than a real question about the settings file |

**The cause is structural, and it generalises to any mono-domain corpus.** Every doc
is English prose about software process, so on-topic jargon (*gate, hook, mirror,
scanner*) is HIGH-`df`/LOW-IDF while incidental everyday words (*notice, simpler,
people*) are LOW-`df`/HIGH-IDF. **IDF points the wrong way for SEPARATING off-topic
from on-topic**, and every term statistic inherits that.

**⚠ Scope that sentence to SUPPRESSION. It is false about RANKING, and the looser
reading would foreclose the one fix that works.** These are different problems on the
same corpus and only the first is unfixable. Re-weighting term statistics — running a
second length normalisation calibrated for queries that *describe* rather than *name*
(`PARAPHRASE_NORM_EXPONENT`) alongside the shipped one and returning both — moved
paraphrase recall from 1/16 to 8/16 with each ranker contributing two candidates (the
up-to-four-line shape `/recall` ships), the naming floor held (measured 2026-08-19; with
one candidate each, and for the second normalisation alone, the figure is 6/16 — the one
`_recall.py`'s docstring quotes).
This entry is itself in the recall corpus, so an unscoped sentence
here is served by the tool it describes. Note the direction of the trap: the off-topic arm's median
`max_idf_matched` (3.39) is *higher* than the legitimate arm's (2.91).

**What is shipped instead.** The honest contract — out-of-vocabulary queries suppress,
everything else gets a **nearest neighbour** — is stated at every operator-facing site
and pinned three ways in `tests/test_recall.py`: a `_MUST_ANSWER` arm (any future floor
that silences a real question reds), a small `_MUST_RANK` arm (doc identity, only where
the match is unarguable — top-1/top-2 margins here are thin), and `_OFF_TOPIC_ENGLISH`
under a **characterization ratchet** that records today's leak count as a number so
improvement is allowed and silent regression is not. A docs-parity assert fails if any
operator-facing surface re-acquires the unqualified guarantee while the ratchet is above
zero — so the claim can become true again exactly when the behaviour does.

**The generalisable lesson, and the reason this entry keeps its prescriptive heading:**
if you cannot earn a guarantee, *say what you actually do* and pin the gap with a number.
A green test over a claim nobody re-derived is worse than no test — it converts an
unknown into a false known.

Two corollaries from building it: (1) raw TF-IDF has a frequency bias — it ranks "the
doc that says X most often" over "the doc *about* X" — so score by binary IDF (presence,
not count) and give a catalogued exemplar a deterministic trigger-match bonus, so
`recall("new hook")` surfaces the `GEN-NEW-HOOK` pointer rather than `hook-authoring.md`.
(2) Prove the engine RANKS, not points: factor the IDF weight into a module-level
`idf_weight` and, in an inject-and-restore test, flatten it to a constant and assert the
two-candidate winner changes — a gate that only checks "a hit came back" is satisfied by
a pointer.

## A `\bgit\s+push\b`-anchored predicate is bypassed by git global options

A guard/speed-bump regex that anchors `\bgit\s+push\b` assumes `push` sits immediately
after `git`. It does not: git accepts **global options between the program and the
subcommand** — `git -C <dir> push`, `git -c k=v push`, `git --git-dir=<d> push`,
`--work-tree`, `--namespace`, `--exec-path`. Every one of those evades the anchor, and so
did clustered short flags (`git push -fv` defeats a `-f\b` arm). For the keystone
force-push / release-tag checkpoints (`_speedbump.py`) that is the difference between
"never miss an unrecoverable remote burn" and a one-token bypass. The fix is a shared
prefix sub-pattern that consumes the global-option run (`git\s+(?:<preopt>\s+)*push`) and
a flag-cluster arm (`-[a-eg-z]*f[a-z]*` fires `-f`/`-fv`/`-vf` but not `-v`). Keep the
alternation prefix-disjoint (each arm starts with `-`, ends on a `\S+`/`\s+` over disjoint
classes) so the `*` introduces no ambiguous nesting — then **earn it against a bypass
corpus AND a ReDoS timing budget** (`"git " + " "*5000 + "push"` < 50 ms), because a
regex rewrite this central must prove both coverage and that it cannot catastrophically
backtrack. Generalizable to any git-subcommand guard: parse the global-option prefix and
match flag *clusters*, never a bare `git\s+<verb>`.

## `MCP_PATH_FIELDS` is a local-fs defer set, not an "is this a side-effect" filter

`_speedbump._pred_mcp_sideeffect` defers to write_guard when an MCP tool carries a
path-shaped field (a `mcp__filesystem__move_file` is write_guard's protected-zone domain,
not an external side effect). The trap: deferring on the *broad* `_hook_utils.MCP_PATH_FIELDS`
— which includes the generic external-payload fields `target` / `uri` / `target_uri` —
silently silenced real external side effects (`send_email{target}`, `trigger_webhook{uri}`,
`send_sms{target}` got no nudge from either tier). Defer ONLY on a local-filesystem subset
(`path`/`file_path`/`destination`/`new_path`/`src`/`dst`); a real local move still carries
`destination`, so it keeps deferring, while an external send carrying `target` now fires.
Do not narrow the shared `MCP_PATH_FIELDS` itself — other callers rely on its breadth;
narrow speed-bump-locally with a module-scope `_LOCAL_FS_FIELDS`.

## The recall corpus must gate harness-internal entries for adopters

`EXEMPLAR_MAP` (and any future harness-dev corpus source) describes how to extend
*Espalier itself* — it ships `espalier/scanners` / `task-packs/TP-…` pointers. Loaded
unconditionally in `_recall._load_corpus`, an adopter's first `/recall` surfaces those
Espalier-internal paths, out-ranking the adopter's own docs via the trigger bonus. Load
any harness-dev corpus source only under `is_self_host_repo(root)` (which returns False for
any adopter checkout). The self-host gate is the load-bearing line, not corpus emptiness —
prove it both ways: an adopter-fixture tmp repo returns `[]`, and forcing the gate open on
the same root leaks the pointer.

## A state-file allowed-set must glob dynamic flag families

`.espalier-state/` flag-parity tests enumerate an `allowed` set of known flag files. A
*dynamic* family — `speedbump_count[.lock]`, `speedbump_<CP-ID>[_<key>]` — only
materializes **after** a checkpoint fires, i.e. exactly when the operator is doing the
risky git op the gate exists for. A literal allowed-set therefore false-REDs precisely at
that moment, blocking the operator's own `/preflight` + `/commit`. Glob the dynamic family
(`name.startswith("speedbump_")`), don't enumerate one-shot keys. General rule: any
allowed-set that pins state files must glob families whose membership is produced at
runtime, not list a frozen snapshot.

## `named_unit=""` is not `null`

`fan_out_findings._dedupe_key` namespaces its two keyspaces (`("U", location, named_unit)`
vs `("C", location, claim)`) so a coinage string equal to another finding's claim cannot
collide. But the branch test was `if unit is not None` — so an **empty-string** `named_unit`
(schema-valid: the field is nullable but `""` passes validation) routed to the `("U", loc,
"")` branch and collapsed every distinct co-located finding into one. Treat falsy (`None`
OR `""`) as "no unit" in BOTH the dedupe key and the unknown-coinage loop. Found by
dogfooding `aggregate_findings` on its own review output — the method's first live caller
surfaced the bug in itself; normalize `"" → None` at the falsy boundary, not just at
`None`.

## The doc line-anchor scanner can read prose as a stale anchor

`_check_line_anchors_fresh` (`tests/test_catalog_self_consistency.py`) treats a
backticked symbol followed within ~40 non-period chars by a `file.py:NN`
reference as a "symbol defined here" line anchor and demands it resolve. A
ESPALIER_MEMORY.md / FAILURE_MODES.md session-log sentence that merely name-drops a
symbol and an unrelated file in the same breath — "type-stable keys in
scaffolding_canon + sister cognitive_blueprint.py (chain-sort key)" with a bare
line number — matches that shape, and because `cognitive_blueprint.py` is an
**ambiguous basename** (it exists in both `espalier/` and `tools/cc/`) a
basename-only resolver returns `None` on the ambiguity and the suite goes red on
the doc's own prose. The §7 row that did this auto-archived itself over the
ESPALIER_MEMORY.md 80-line cap before the reword landed, so the red was cleared by
*relocation*, not by fixing the mechanism — a footgun that would re-arm on the
next such sentence.

A symbol-aware `_resolve_source` fixes this: on an ambiguous
basename the candidate that actually *defines* the symbol wins, so a real
anchor resolves while prose whose symbol is defined in neither candidate is
classified `"prose"` and skipped (not failed). A genuinely ambiguous anchor
(symbol defined in *both* copies) still fails — now with an actionable
"qualify the path" message instead of "does not resolve." When you write a
session-log row, prefer a fully-qualified path over a bare basename, and avoid
the symbol-then-basename-then-line adjacency unless the symbol really is defined
at that line.

## A tracked internal doc needs a sister-site footprint — and part of it is conditional

Making a tracked `docs/*.md` internal is never one edit. This list read **"all
five"** until 2026-08-13, when reclassifying `RELEASE_CHECKLIST.md` and
`RELEASE_DECISIONS.md` hit three sites it never named and one it named
unconditionally that must not be. A checklist that reads as complete and is not
is worse than no checklist: it retires the question.

**Always, for a `docs/*.md`:**

1. `espalier/surface_contract.py::_INTERNAL_FILENAME_PATTERNS` — `classify_release_path` → `internal` (the bespoke release-zip walker keys off this)
2. `MANIFEST.in` `exclude <path>` — the recursive `docs *.md` sweep is not classify-derived, so it ships the file into the sdist otherwise
3. `.gitattributes` `<path> export-ignore` — keeps it out of `git archive` / GitHub "Download ZIP"
4. `tests/test_git_archive_parity.py::EXPORT_IGNORED_INTERNAL_DOCS` — binds (3) in **both** directions: listed docs must be absent from the archive, and `test_every_plain_file_export_ignore_is_registered` requires every plain-file `.gitattributes` entry to appear here. That reverse arm is the sister-site alarm — without it, adding an export-ignore line and forgetting every other site reds nothing.

(1) and (2) are **mutually co-required** and must land in one commit: (1) without
(2) reds `test_wheel_payload::test_sdist_excludes_internal_classified_files`; (2)
without (1) reds `test_git_archive_parity::test_manifest_single_file_excludes_classify_non_public`.

**Conditional — check each, do not assume:**

5. `espalier/claim_extractor.py::EXCLUDED_DOC_GLOBS` (plus its `LIVE_STATE_MAPS`/`FROZEN_RECORD_DOCS` partition) — **only if the doc is point-in-time narrative.** Not shipping a doc is not a reason to stop checking it: `RELEASE_CHECKLIST.md` is a *procedure someone executes*, so its counts are live and stay audited, while its twin `RELEASE_DECISIONS.md` is a *record of past choices* and is excluded. Same commit, opposite answers.
6. **Every shipped file that names the path** — not just `docs/README.md`. Two distinct jobs: (a) if a *markdown link* points at it, convert the row out of link form — an export-ignored target reds **two** dangling-link gates with **different** exclusion mechanisms, `test_git_archive_parity.py` (export-ignore) and `test_wheel_payload.py` (MANIFEST), so a doc can be clean in one and broken in the other; (b) **backtick prose and source comments are gated by nothing** — `dangling_links` walks markdown links only — so a `# see docs/FOO.md` in a shipped `.py`, or a "See docs/FOO.md" in a shipped workflow, silently becomes a pointer to a file the reader does not have. Add a "maintainer-only; read it on GitHub" clause. This bites the person doing the reclassification: writing the rationale into a shipped source comment *creates* a fresh instance of the class.
7. `tests/conftest.py::_FULL_TREE_NODEIDS` — **if any test reads the doc unconditionally.** `test_test_suite_contract::test_every_dev_tree_test_is_full_tree_or_exempt` derives dev-only status live from `.gitattributes`, so the registration becomes owed the moment (3) lands. `git archive` *does* ship `tests/`, so the underlying harm is real, not just a red. Measure the granularity against a built export — the registry says so and means it.

**Do not mistake a setup step for an alarm — the mistake was made here, in both
directions, on the same day.** `tests/test_self_hosting.py`'s sentinel prune was
five hand-written basenames; adding two export-ignore entries reddened it, which
looked like a §C1 declared-population defect, so it was rewritten to derive from
`.gitattributes`. That was worse: it made the fixture's oracle and its subject
read one source, so its assert became true by construction — the
closed-loop-verification trap, on the very test that had just *caught* something.
It is now a derivation **and explicitly labelled a setup step**, with the alarm
moved to `test_every_plain_file_export_ignore_is_registered`, where the two sides
are independently written (§C1 tier 2). `surface_contract.get_indexed_doc_relpaths()`
is a genuine derivation and needs no hand-editing — but its guard is
population-dependent, so it carries a monkeypatched twin that fails on a broken
derivation whatever the live list holds.

Rule of thumb: **derive a population, but never derive the thing that checks it
from the same source.** A hand-written list is sometimes not a defect — it is the
second, independent derivation a contract needs. Ask which one you are looking at
before you "fix" it.

**Proof hint:** `classify_release_path('docs/<doc>.md') == 'internal'`;
`pytest tests/test_git_archive_parity.py tests/test_wheel_payload.py
tests/test_audit_accuracy.py tests/test_test_suite_contract.py
tests/test_self_hosting.py` goes red if a sister site is missing. Precedents:
`session-archive.md`, `REDEFINED_INFORMATION_REGISTRY.md`,
`RELEASE_FINDINGS_LEDGER.md` and the two `RELEASE_*` docs.

## Blueprint file mtime is not a session-grouping signal

`cc/blueprints/<session>.json` files rotate at every SessionStart — compact,
resume, or new CC session, since `session_start.py` and `session_resume.py` both
shell `cognitive_blueprint start`. So one work session's reasoning scatters
across several per-session files. When you need to aggregate "this session"
across that rotation (as `/reflect --candidates` does via
`reflect_protocol._load_session_entries`), do NOT group the files by **mtime**:
the CURRENT blueprint is rewritten on every `record`/`finalize`, so its mtime is
"now," while a prior blueprint's mtime is frozen at its last touch. The
inter-file mtime gap therefore balloons during long mid-session waits — a 45-min
wait on background test suites + operator questions split one session in two,
observed live.

Two other tempting boundary signals also fail:

- **`continuation_fragments`** is NOT a handoff boundary. Stop-gate Gate 4
  auto-finalizes the active blueprint at *every* turn end, so a mid-session
  blueprint already carries fragments.
- A flat **last-K-files** scan pulls in genuinely-prior sessions.

**Do:** walk the `parent_session_id` lineage from the current blueprint, bounded
by a gap on the STABLE `timestamp` field (creation time — set once at
`cmd_start`, never rewritten). **Proof hint:** the earn-the-red is a subdir/long-wait
replay — `_load_session_entries` returns the full session, not just the
post-rotation slice.

## A text-mode subprocess decode uses the OS locale, not UTF-8

`subprocess.run(..., text=True)` (or `capture_output=True`, or a text-mode
`check_output`) WITHOUT `encoding=` decodes the child tool's stdout via
`locale.getpreferredencoding()` — NOT UTF-8. Invisible on a UTF-8 dev host
(macOS/Linux); on a stock Windows cp1252 console git/rg/build emit UTF-8 that
mis-decodes — silent mojibake on accented authors / CJK paths, or a hard
`UnicodeDecodeError` on a byte cp1252 leaves undefined. Every `read_text()`
already pins `encoding="utf-8"`; only the subprocess decodes had been left to
the locale (58 sites, zero previously pinned).

**Do:** pin `encoding="utf-8"` on every text-mode subprocess call. Then make
the decode GUARDED, by one of two arms (ledger `DEF-821`, 2026-09-16 — the
first cut of this rule left 78 sites on the derived surface with neither, and
`(OSError, SubprocessError)` tuples that let the decode error past, because
`UnicodeDecodeError` is a `ValueError`, not an `OSError`):

- `errors="replace"` where the text is names, lines or sentences — filenames
  (a `core.quotePath=false` or `-z` `ls-files` prints raw bytes, and a latin-1
  name on ext4 is a legitimate repository state, not corruption; the default
  quoted form is ASCII-safe, which is what the earlier "quoted paths stay
  strict" meant), `status`/`log` lines, branch names, tool output shown to a
  person — with `ValueError` beside the `OSError` in the handler. A replacement
  character where a path was is still a sentence; a traceback from `doctor`,
  `audit` or `init` on an otherwise healthy tree is not.
- A STRICT decode ONLY under a handler that names `ValueError` or
  `UnicodeDecodeError`, for structured answers (SHAs, refs, version banners,
  a stash object id) where `errors="replace"` would MASK real corruption — the
  corrupted answer becomes the site's own failure verdict instead of a crash.

The arm follows the CONSUMER, not the argv: a `rev-parse --show-toplevel`
that becomes a `Path`, or a branch name fed back to git, is a structured
answer (the sweep drifted two roots and two version banners onto replace
before review, so the pin refuses a tolerant `errors=` on `--version`,
`rev-parse HEAD`, `--show-toplevel` and `stash create`, and reads
`errors="strict"` / `errors=None` as no guard at all -- key presence is not a
value, the lesson the encoding pin learned first). Every strict-arm handler
carries `# strict decode: a structured answer (DEF-821)`. A call whose pipe is
never decoded (stdout inherited, or `input=` only) opts out with
`# decode-errors-ok: <reason>` on its own line. Mechanically enforced by
`tests/test_contracts.py::TestSubprocessDecodeGuarded` over the same derived
surface as the encoding pin below; the two earn-the-red oracles are a `git` on
PATH that prints a non-UTF-8 name (`tests/test_repo_mode.py`,
`tests/test_surface_contract.py`), since APFS cannot hold one.

**Mechanically enforced:** `tests/test_contracts.py::TestSubprocessEncodingPinned`
AST-sweeps every shipped/run root (`espalier/`, `tools/`, `scripts/`, `bench/`;
excludes `espalier/_vendor/` [parity-mirrored], `espalier/assets/`, `tests/`)
and fails on any text-mode `subprocess.*` call not pinning `encoding="utf-8"`.
It checks the VALUE, not just key presence (`encoding=None` / `"latin-1"` still
fails), and forbids `from subprocess import` / `import subprocess as` aliasing
that would hide a call from the AST. Opt a genuine locale-following call out
with a `# encoding-locale-ok: <reason>` pragma.

**Recurrence guard — no manual edge:** the contract's scan surface is DERIVED
from `git ls-files` (the repo's tracked-code SoT), not a hardcoded root list, so
a NEW dir that ships to or runs for an adopter is gated automatically — the
`bench/` + top-level `tools/` gap (the original fix scoped only to the engine
dirs) cannot silently reopen. A ship-manifest derivation was rejected: it drops
`scripts/` (maintainer/CI code that runs on the Windows legs but isn't shipped)
and misses not-yet-created dirs. The enumeration fails CLOSED — if `git ls-files`
returns nothing the contract SKIPS (never false-greens), guarded by a sentinel
(`espalier/cli.py` must be present); `test_scan_surface_covers_shipped_dirs_…`
pins the breadth + the test/`_vendor`/`assets` exclusions.

**Proof hint:** the host-independent earn-the-red is
`tests/test_git_conventions_encoding.py` — it forces `LC_ALL=C` + `PYTHONUTF8=0`
+ `PYTHONCOERCECLOCALE=0` in a child process to reproduce the
`UnicodeDecodeError` on a UTF-8 host (skips if the platform refuses to drop
UTF-8), so the class is pinned without a Windows runner. The contract was RED
on all 58 sites pre-fix.

**The `read_text` twin (ledger `DEF-829`, 2026-09-16).** The same escape on a
file: `Path.read_text(encoding="utf-8")` and a text-mode `open` raise
`UnicodeDecodeError` on a file that is not UTF-8, and an `except OSError:`
around the read lets it past -- a handler that promises the file's failure
path and does not keep it. Measured on the derived surface: 17 sites, seven
under `tools/cc/`, among them the three adopter-tree readers in the hooks
(`cc/COMMANDS.md` from the SessionStart banner, the fingerprint from the Stop
gate, the manifest from every integrity check), where the escape was the
banner lost on every session through the fail-open crash guard, or a Stop
blocked by the fail-closed one. The same two arms, keyed on the consumer, plus
two file-shaped spellings: bytes handed to `load_json_dict_safe` (it decodes
tolerantly itself; the strict `read_text` in front of it was the defect), and
Python source parsed from bytes, so a non-UTF-8 file is the `SyntaxError` the
handler already names. Pinned by
`tests/test_contracts.py::TestTextReadsDecodeGuarded` over the same derived
surface (`read_text`, `bytes.decode`, a text-mode `open` that reads, the
compressed openers with a `t` mode), with the inverse arm the subprocess pin
has -- a tolerant `errors=` on one of the lane's structured files (the
fingerprint, the manifests, the plan file, the probes, an allowlist) is an
offender -- and the marker `# strict decode: a structured answer` read as a
contract (it must sit on an `except` naming `ValueError`); the hook rows drive
the real hook on a latin-1 file. Declared limits, each re-derivable with the
pin's helpers (measured 2026-09-17, after the sweep; pinned by
`tests/test_contracts.py::TestTextReadsDecodeGuarded::test_the_census_reads_the_spelling_the_handler_and_the_try_body`): a strict read under no
try at all is not counted -- it is the site's stated crash only where nothing
promises otherwise, and the two readers of `cc/PACK_MANIFEST.txt` behind
`/status` and `doctor` were such a promise (the module says it "must not crash
/status") and now read with a replacement character; 78 remain, 14 of them
`bytes.decode` calls whose callers all catch. A `+`-mode text handle counts
only when its bound name is read (9 on the surface, the lock-file idiom, none
read). A read in an `else:` or `finally:` block reads as no-try; a handle read
outside its `with` is not followed.

## A mass freshness-pin is a 14-day time-bomb

`espalier freshness pin --all` stamps every fragment with the SAME
`last_verified_at`. Fourteen days later they ALL cross the re-verify timer at once
and `test_audit_accuracy::test_live_repo_audit_runs_clean` goes RED — with ZERO
code change. A work session spanning local midnight surfaces it mid-task, where
it LOOKS like a regression the current work introduced but is environmental
(none of the touched files are bound to the tripped fragments).

**The day axis now has a warning band, so the cohort warns before it blocks.**
`espalier/scanners/freshness.py::_classify` returns `fresh` while
`days <= STALE_THRESHOLD_DAYS` (14), `stale` between there and
`CRITICAL_THRESHOLD_DAYS` (28), and `critical` only past that. Since the CI
freshness job treats `stale` as a warning that never blocks, a cohort crossing
the first threshold buys a fortnight of notice instead of a wall. Before the
band existed the whole cohort stepped straight from green to blocking, which is
why this used to present as a sudden wall rather than a gradual drift.

The cohort itself is not dissolved by the band — every fragment sharing one pin
date still crosses BOTH thresholds together. `espalier freshness check` now says
so out loud whenever one date holds at least half the manifest
(`COHORT_WARN_FRACTION`), naming the count and the two dates they will cross, so
a bulk re-pin announces itself when it is made rather than a fortnight later. A
smaller cluster gets no advisory: six of fourteen re-pinned on 2026-09-15 went
unannounced, and the handoff carries their dates by hand (stale 2026-09-30,
critical 2026-10-14).

**Do:** when the audit-accuracy test reds and the only thing that moved is the
date, confirm the flagged fragments' values are still mechanically correct (the
rest of the suite is green), then re-pin — `espalier freshness pin --all` is
honest there. Don't chase it as a code bug. (All pins landing on one day is the
root shape. The warning band landed 2026-08-10 and defuses the *cliff*;
staggering the pins is what would defuse the *cohort*, and it stays an operator
action because writing spread `last_verified_at` values would assert
verifications that never happened.)

**Proof hint:** `git log -1 --format=%cd .espalier/freshness.json` near a 14-day
boundary + a green full suite ⇒ environmental, not regression.

## Pinning ONE freshness fragment reds its co-pinned siblings _(closed — behaviour changed)_

**Historical.** `espalier freshness pin <id>` once reddened every co-pinned
sibling, because the audit measured each fragment's staleness against the newest
pin in the manifest rather than its own. One precise pin produced a wall of
unrelated-looking failures, so `--all` was the only safe form and a
single-fragment pin was the trap.

**Not true today.** `espalier/scanners/freshness.py::scan_repo` groups bound paths
by *each fragment's own* `last_verified_sha` (`paths_by_sha`) and runs one
`git log` per *distinct* pin; each fragment's `days` comes from *its own*
`last_verified_at`; and `_classify` receives only that fragment's `commits` and
`days` — it has no cross-fragment term at all. Pinning one fragment moves one
fragment. **The single-fragment `pin` is now the correct minimal form** — reach
for it when exactly one fragment's content was re-verified, and reserve `--all`
for a genuine cohort re-attestation, which resets every clock and is therefore a
decision rather than a tidy-up. It resets them together or not at all: when any
fragment's bound has uncommitted changes (or, on a tree that commits its
manifest, a literal edited by hand), `--all` refuses before pinning anything and
names them — a partial re-attestation would split the cohort's clock, the very
trap the sibling entry above describes. Rebinds are still skipped one by one.

**Why this entry survives its own fix:** the co-pinned-sibling *shape* — one
shared clock making N independent things go red together — is exactly what the
sibling entry above ("a mass freshness-pin is a 14-day time-bomb") still
describes. A reader who met the old behaviour needs to be told it changed, rather
than finding no entry and assuming their memory still holds.

## A committed runtime marker silently re-classifies the repo's own mode

`repo_mode.detect_repo_mode` treats any `_RUNTIME_MARKERS` member's *presence*
as "init has run." If a marker is a *directory* (`.espalier`) or a file the repo
*commits* (`.espalier/freshness.json` is git-tracked), a fresh
`git clone` has the marker on disk → the repo misclassifies as `initialized_*`
instead of `source_checkout`, and `doctor`/`self-host-check` `mode=auto` then
false-fails the strict surface gate (masked only by undocumented CI flags). A
runtime marker MUST be a per-install artifact that *no project commits*
(gitignored), bound to a specific file — never a directory. The marker is
`.espalier/integrity.json`, not the `.espalier` directory; same class as the
`reports/` → `reports/repo_fingerprint.json` rebind.

**Proof hint:** `git archive HEAD | tar -x -C <tmp>` (tracked files only) then
`detect_repo_mode(<tmp>)` must return `source_checkout`; `git ls-files .espalier/`
should show no per-install artifact (`integrity.json`/`fingerprint.json`/`settings.json`).

## Engine ↔ hook copies share a concept but not bytes — a fix lands in one and rots the other

`espalier/<x>.py` (engine) and `tools/cc/<x>.py` (hook, re-vendored byte-for-byte
to `espalier/_vendor/cc/`) are deliberately *not* byte-parity for the
conceptually-mirrored pairs (`cognitive_blueprint` and `reflect_protocol`; an
earlier version of this list also named `post_compact` and `_freshness_cache`,
but neither has an engine twin — `post_compact.py` exists only under
`tools/cc/hooks/` and `_freshness_cache.py` only under `tools/cc/`). A hardening that lands on one side (the
STALE-1 basename guard; `KeyError`→`.get()`; `UnicodeDecodeError` widening)
silently misses the other, guarded only by a docstring saying "apply to both by
hand." For any conceptually-mirrored pair, a behavioral fix needs a
`test_*_parity` asserting both sides agree on the shared invariant (byte-parity
tests are off the table for these files — assert *behavior*, not bytes). Two live
instances surfaced in one round (`build_matrix` missing STALE-1,
`cmd_finalize` raw-subscripting); both are closed, and each real pair carries a
behavioural parity test today —
`tests/test_reflect_protocol.py::TestHookBuildMatrixStaleParity` for
`reflect_protocol`, `tests/test_cognitive_blueprint_schema_parity.py` for
`cognitive_blueprint`. The candidate set is derivable — the basenames shared by `espalier/*.py` and
`tools/cc/**/*.py` — and today it holds these two behavioural pairs plus two
constants modules (`_blueprint_limits`, `_self_host_fingerprint`) that their own
lockstep tests hold equal (`tests/test_library_hook_parity.py`,
`tests/test_ci_guard.py`); a new shared basename is a new pair to classify.

**Proof hint:** grep the engine twin for the guard you just added to the hook
(or vice-versa); if absent, add a behavioral-parity test exercising both.

## `git checkout <file>` to undo a change also nukes uncommitted work on that file

`git checkout <path>` / `git restore <path>` reverts the file to **HEAD** —
discarding ALL working-tree changes to it, not just the last edit. There is no
"undo only my most recent change." The classic way to get bitten: during an
earn-the-red you plant a temporary poison in a file, then `git checkout` it to
restore — but if that file also holds uncommitted work (a large rewrite not yet
committed), the checkout takes the rewrite down with the poison in one shot, and
there is no reflog for working-tree content.

**Do:** never `git checkout` / `git restore` a file that carries uncommitted
work. To undo a temporary poison, snapshot the pre-poison bytes (in memory or a
scratch file) and write them back, or run the poison inside a `try/finally` that
restores the saved original, or poison a *copy*. If it does happen and the lost
work was produced deterministically, re-run the deterministic step to reconstruct.

**This entry is now backed by a mechanism, because the rule alone was not
enough.** It was written, catalogued, and then walked into anyway — the guard
`CP-DISCARD` required `checkout` to be followed by `--` or `.`, so the bare
`git checkout <path>` form (the one most likely to be typed) passed **silently**
while `git checkout -- <same file>` fired. The omission was deliberate, to avoid
false-firing on a branch switch whose name matches a directory; that was right
about the regex and wrong about the conclusion, since git's own ambiguity is
mechanically resolvable. `_pred_discard` now resolves it: a token that is a
commit-ish is a branch switch (silent), a pathspec is checked with
`git diff --quiet` and fires **only when the path is dirty** — which also makes
it quieter than the `checkout .` arm, that fires on a spotless tree.

**And a reminder is not the real protection.** A speed-bump is
deny-once-then-allow, so re-issuing steps past it in one line. Every discard is
therefore preceded by `_speedbump.snapshot_discard`, which runs `git stash
create` (verified side-effect-free: the worktree stays byte-identical and
`git stash list` gains **zero** entries) and appends `timestamp / sha / command`
to `cc/discard_snapshots.log`.

**Recovery:** take the sha from the last line of that log and run
`git show <sha>:<path>`. Nothing else is needed; the content is a real git
object. The snapshot covers **tracked modifications only** — untracked files
(the `git clean -f` hazard `CP-GITCLEAN` guards) were never in git, so there is
no object to make and no recovery to offer.

**The same net under a delete, since 2026-09-15 (`DEF-802`).** The snapshot
was reached only through the git verbs, so `CP-DISCARD` had it while
`CP-RMRF` — the checkpoint whose target has no other net — took none: on the
Windows walk a recursive-force `Remove-Item` on a directory holding a dirty
tracked line destroyed it unsnapshotted, and the later discard snapshot
captured a tree that no longer had it. `snapshot_discard` now also runs for
any `rm` / `Remove-Item` whose target holds dirty tracked content inside this
checkout (each operand placed in its statement's directory, a nested `bash
-c` read too), and it records what it took so the nudge's text names a
snapshot **only for that command**: an untracked, clean or out-of-repo target
keeps the honest no-recovery wording, because the promise must be exactly as
wide as the net. `CP-DISCARD` likewise says "NO snapshot was taken" when git
could not answer, instead of claiming one.

**A loop's roots, and the net's own store (2026-09-18).** A shell loop that
removes each item (`for f in src; do rm -rf "$f"; done`, `find src | while
read f; do rm "$f"; done`) took no snapshot: the remove's operand is the loop
variable, which names nothing on disk. The arm now reads the loop's roots --
only those it takes WHOLE: a narrowed head (`find src -name '*.pyc'`)
removes only what its predicate selects, and an untracked-only listing
(`git ls-files -o`) takes no tracked content, so neither earns the promise.
And a command that deletes the snapshot's own store -- the checkout root,
`.git` or the snapshot log -- now earns NO promise, loop or direct
(`rm -rf .git src` used to promise a net its re-issue destroyed). A find with
a delete action and a pipeline into xargs are still not read: the same sweep
spelled that way takes no snapshot. A **declared limit** (2026-09-19), pinned
by `tests/test_speedbump_discard_snapshot.py::TestLoopRemovalSnapshot::test_the_find_and_carrier_sweeps_are_a_declared_limit`,
which reds the day the arm reads them. What it costs is an absent net, never a
false promise: the nudge still fires on those sweeps and its text names no
snapshot, because the promise is written to be exactly as wide as the net.

**Same shape, different verb — a tool writing a *tracked* file mid-stash.**
`.espalier/freshness.json` is the one git-tracked file under `.espalier/`, and
`espalier freshness pin` / `unpin` rewrite it. If you `git stash push` to isolate
an edit and a tool rewrites a tracked file while the stash is out, `git stash pop`
can conflict or silently strand the tool's write. **Do:** after every
`git stash pop`, run `git diff -- <file>` and confirm the hunk you expected is
still there — the pop *succeeding* is not the same as the content surviving. If
the pop conflicts, resolve by hand in favour of the stashed work; never
`git checkout` the file to "clean it up", which is this entry's original footgun
one level down. Note the narrow scope: the hazard is the two verbs that actually
rewrite the manifest — `pin` and `unpin` — not the read-only `check` verb, whose
derived cache is gitignored and which rewrites no manifest at all.

**Proof hint:** `git status --short <path>` shows the file dirty before you reach
for `git checkout`; if it is dirty, stash or snapshot first.

## An earn-the-red snapshot-restore is masked by stale bytecode for an imported module

The sibling hazard of the `git checkout` entry above. You took its advice —
snapshot the pre-poison bytes, poison the file, run the check, write the bytes
back — and the earn-the-red *still* reports the wrong result. The tell is a
**self-contradicting oracle**: the test fails AFTER you restore, while
`git diff` shows the file matches HEAD (the source is correct, yet the behavior
is wrong).

Cause: when the System-Under-Test is an **imported Python module** (not a
subprocess), the poisoned run compiled a `.pyc` into `__pycache__`. A plain
byte-restore (`shutil.copy`, or writing the saved bytes back) rewrites the
*source* but does not reliably invalidate that cached bytecode, so the next
`import` reuses the poisoned `.pyc`. The dangerous direction is the false
**GREEN**: a broken restore that keeps reporting "passes," so you trust a fix
that isn't there.

**Do:** run an imported-module earn-the-red with bytecode writing off and a
cleared cache — set `PYTHONDONTWRITEBYTECODE` in the environment, and clear
`__pycache__` between the poison and the restore. Clear it *via Python*
(`shutil.rmtree` over `pathlib.Path(pkg).rglob("__pycache__")`), not a shell
recursive delete, forced or not — the latter trips the harness's own
catastrophic-delete speed-bump.

**A subprocess is NOT immune (measured 2026-09-18, DEF-842's lane).** This entry
said a hook driven through its own `python` process recompiles from the source
every run. It does not: the interpreter reuses any `.pyc` whose recorded source
size and mtime (whole seconds) still match, and on the self-host tree the LIVE
guard imports the hook modules on every tool call — so the PreToolUse hook of an
Edit call compiles the cache from the pre-edit source, and a one-character
mutation (`<= 2` to `<= 1`: same size, same second) left both the hook
subprocesses and the in-process tests running the unmutated code. The witness
read green for the wrong reason; `dis` showed the old constant. Every mutation
that changes a file's size is safe; a same-size one is not. **Do:** after a
same-size mutation or revert of a hook module, clear `tools/cc/hooks/__pycache__`
(via Python, as above) before the run, and confirm the loaded code — not the
source — carries the change (`dis.get_instructions` on the function; an
`inspect.getsource` check is not enough, since it reads the source file).

**Proof hint:** if a restored earn-the-red disagrees with `git diff`, suspect the
cache before the source — `find <pkg> -name __pycache__` and clear it, then
re-run. If it agrees, the source really did change; look there.

**The edit class that hits this hardest: a REWRAP.** CPython validates a `.pyc`
against the source's mtime *and size*, so the mutations most likely to slip
through are the ones that reorder characters without changing how many there
are. Re-wrapping a line moves a newline and two spaces from one place to
another — **identical byte count** — which removes half the validation signal
and leaves only mtime. Measured (2026-08-13): a wrap mutation and its fix were
byte-for-byte the same length, and after restoring the correct file, the
imported module kept the mutated behaviour. `git diff` was clean, the source on
disk was verifiably right, and the test kept failing; deleting the `.pyc` files
fixed it immediately. The "restore failed" reading was believed for two rounds
before the cache was suspected. *(That size+mtime validation is the mechanism —
**probable**, not instrumented; the same-length property and the purge-fixes-it
behaviour are **verified**.)*

So: prose constants matched by substring are exactly the surface where a rewrap
is both a real behaviour change (see the sibling entry on wrapping) *and* the
mutation the cache cannot see. Purge or set `PYTHONDONTWRITEBYTECODE=1` before
believing **any** rewrap probe, in either direction.

## A hook-denied Bash call runs NONE of its commands — a bundled `git add` is skipped

When a governance hook DENIES a Bash tool call, the WHOLE call is blocked — none
of its commands run (all-or-nothing). So if you bundle `git add <file>` with
another command in the same call (via `&&`, `;`, or a newline) and that call gets
denied, the `git add` never runs. The index silently stays stale, and your NEXT
clean commit captures the stale content (or misses the file entirely).

**Do:** never bundle `git add` with a command that might be blocked (a dangerous
pattern, a protected-zone write, an inline env prefix a guard rejects). Stage
separately. After any commit, verify staging actually took: `git status --short`
should be clean for the intended paths, and `git show HEAD:<file>` should show the
content you meant to commit.

**Proof hint:** if a commit "succeeded" but a file looks wrong, `git show HEAD:<file>`
versus the working tree reveals a stale-index capture; re-stage and `--amend`
while unpushed.

## Code-clean is not narrative-clean — the never-attacked surface isn't converged

A review can drive correctness to zero findings across many rounds and still have
never touched a whole DIMENSION — the narrative surfaces (README, CHANGELOG, help
text, first-impression docs). Those can leak overclaims, stale pointers, or
dev-log residue while the CODE is spotless. "0 blockers for N rounds" measures the
attacked surface, not the un-attacked one; a fresh dimension is not converged just
because a different one is.

**Do:** when correctness has gone null for several rounds, re-point the review at
a surface it has never attacked — narrative/craft, packaging, first-run UX — rather
than reading the null as "done." The nulls signal that the CURRENT angle is
exhausted (change angles), not that the work is finished.

## Retired considerations

Design ideas that were considered, rejected, and documented so the
decision rationale survives — sub-docs in
[`docs/sharp-edges/`](sharp-edges/) capture the long-form reasoning.

- **chmod 444 on hook files.** Proposed: OS-level enforcement
  after `cmd_init` deploys hooks. Rejected: friction-layered-on-friction
  for a threat model already covered by the 3-tier defense; the
  proposal is itself bypassable via `chmod u+w`. See
  [`sharp-edges/chmod-444-decision.md`](sharp-edges/chmod-444-decision.md).


## The mirror whose SoT is the packaged copy

Eight of this repo's nine byte-mirror rows put the source of truth in the working
location and the copy under `espalier/assets/` or `espalier/_vendor/`. One —
`.github/workflows/harness-guard.yml` — is inverted: the packaged asset
`espalier/assets/github/workflows/harness-guard.yml` is the SoT and the root file
is generated. So the rule *"edit the file where it lives, sync the packaged
copy"* is right eight times and wrong once, and the wrong case is a workflow file
that looks exactly like every other workflow file in the same directory.

The tell is not in the file. It is in the parity test's failure text, which names
the direction (*"sync espalier/assets/… → .github/workflows/…"*), and now in
`espalier/mirror_registry.py`'s `direction` field. Read the direction off the
registry rather than inferring it from where the file sits.

A related trap: **a row with no sync script is not a row with no mirror** — it is
a row whose sync is a manual copy nobody scripted. This one went years that way,
which is why a hand-edit of the generated file surfaced only as a full-suite red
~6½ minutes later, with nothing to run as the fix. It now has
`scripts/sync_github_workflow_asset.py`.

## A prefix match that swallows a sibling names the wrong remedy — confidently

`espalier/surface_impact.py::classify_surface` keyed the `espalier/_vendor/`
prefix to the `tools/cc/` vendor family. When a **second** family later moved in
next door — `espalier/_vendor/selfcheck_tests/`, with its own sync script and its
own parity test — the prefix silently absorbed it, and the advisory began telling
operators to run `sync_vendor_cc.py` for a drift only `sync_selfcheck_tests.py`
can fix. Nothing reddened: the advisory is prose, no test consumed it, and the
wrong script exits 0 having changed nothing relevant.

Three things to carry:

1. **A missing advisory and a wrong advisory are not the same severity.** A
   missing one costs the minutes until the suite reds. A wrong one costs the
   debugging session, because the reader has already ruled the real cause out.
2. **A path-prefix classifier is a hand-list that does not look like one.** It
   under-enumerates exactly the way a bulleted list does, but it reads as code,
   so it escapes the enumeration-integrity reflex. When you add a subtree under
   an existing prefix, grep for who *else* matches that prefix.
3. **Drive the classifier, do not read it.** This was invisible to grep —
   `grep -c selfcheck espalier/surface_impact.py` → `0`, which reads as "no row
   yet", not as "another row is answering for it" — and obvious the moment
   `classify_surface` was actually called on the path.

## De-provenancing edits go to the SoT, never the mirror

`espalier/_vendor/cc/`, `espalier/assets/claude/`, and
`examples/dogfooding/.claude/` are *generated* mirrors
(`scripts/sync_vendor_cc.py`, `scripts/sync_claude_mirrors.py`). Edit the SoT
(`tools/cc/` / `.claude/`), then run the generator — a hand-edited mirror reds
its parity test (`tests/test_package_resource_parity.py`,
`tests/test_vendor_cc_parity.py`). Those three are examples, not the census:
nine rows are byte-pinned and their sole home is `espalier/mirror_registry.py`.
Check the direction there first — for `harness-guard` the SoT is the *packaged*
file and the working-tree copy is generated, so "edit the SoT" points the
opposite way. The
`tests/test_no_provenance_in_shipped_code.py` census keeps internal
build-history tags off the shipping surfaces going forward; add a load-bearing
entry to its `_ALLOWED_HITS` (with a reason) rather than disabling the gate.


## A broad-except in an *exempt* `tools/cc/` source still needs `# noqa: BLE001` — its `_vendor` mirror is not exempt

`scripts/check_exception_policy.py` keys its hook-entrypoint exemption on literal
`tools/cc/...` path prefixes (`HOOK_ENTRYPOINT_DIRS = ("tools/cc/hooks/",)`;
`HOOK_ENTRYPOINT_FILES` = `tools/cc/ci_guard.py`, `cognitive_blueprint.py`,
`execution_plan.py`, `reflect_protocol.py`, `statusline.py`,
`session_resume.py`), so `except BaseException:` at a hook entrypoint is allowed
without a marker. But the gate scans `SCAN_ROOTS = ("espalier", "tools/cc")`, and
`espalier/` includes the generated `espalier/_vendor/cc/` mirror. The mirror path
(`espalier/_vendor/cc/hooks/_hook_utils.py`,
`espalier/_vendor/cc/cognitive_blueprint.py`) does NOT start with `tools/cc/`, so
the *same bytes* that are exempt at the source are FLAGGED at the mirror. A
broad-except added to an exempt `tools/cc/` source therefore reds
`tests/test_exception_policy.py::test_no_new_unannotated_broad_except` the moment
`scripts/sync_vendor_cc.py` regenerates the mirror — even though the source
itself never needed annotating.

Fix: put a `# noqa: BLE001 -- <reason>` on the `except` line of the **source**
(never the mirror — that's a generated file; see "De-provenancing edits go to the
SoT, never the mirror"). The marker rides into the mirror via the generator, and
the gate's `_has_noqa_marker` check is path-agnostic, so it skips the mirror too.
This is already why exempt hook files (`stop_gate.py`, `write_guard.py`,
`subagent_start.py`, …) carry the marker despite the exemption. The allowlist
(`scripts/exception_policy_allowlist.json`) is the wrong tool — it is empty by
policy and shrinks over time; do not grow it for new sites. Ruff-safe: `BLE001`
and `RUF100` are both unselected, so the marker is never flagged as unused.

**Proof hint:** after adding any `except BaseException:` / `except Exception:` in
`tools/cc/`, run `python scripts/sync_vendor_cc.py` then `pytest
tests/test_exception_policy.py` — a mirror-only failure (a flagged
`espalier/_vendor/cc/...` path whose `tools/cc/` source is clean) means you
skipped the source-side `# noqa: BLE001`.

## PostCompact summary capture is write-only (BC-033)

`post_compact.py::_capture_compact_summary` persists the verbatim native
compaction summary (CC's `isCompactSummary` transcript entry) to
`cc/blueprints/compact_summaries/<session>.md` so the "pick up where we left
off" text survives after Claude Code GCs the transcript. That captured text is
operator-writable free text, so BC-033 forbids it from ever re-entering a
post-compaction priming channel. The priming channel has **three** limbs, not
one: the hook's stderr re-orientation block (typed-integer-only `bp=<hex>/d<int>`),
`cc/blueprints/latest.json` (which `session_start` surfaces), and the
`post_compact_pending` flag (empty-by-construction). The capture is write-only:
it appends to a *separate* file and is read only on explicit pull (`/handoff`
pointer, `/read-summary`) — never returned to the caller, added to `lines[]`, or
written into `latest.json`. The lock
(`tests/test_post_compact_capture.py::TestBC033Lock`) asserts a sentinel planted
in the captured summary is absent from **all three** limbs after the hook runs —
asserting stderr alone is insufficient, because the original BC-033 leak was via
`latest.json`, not stderr.

Two further footguns the helper closes: (1) the read is symlink-refused on BOTH
sides — `cc/blueprints/` is Write-allowed, so a planted symlink at the output
dir or `<stem>.md` dest would make `open("a")` write THROUGH it to an arbitrary
target; (2) the transcript stem is refused if it carries a path separator
(`/`, `\`) or is dot-only, so `out_dir / f"{stem}.md"` can never escape the
artifact dir on a Windows backslash path.

**Proof hint:** after touching the capture path, run `pytest
tests/test_post_compact_capture.py` and confirm `TestBC033Lock` is green AND
`TestCaptureWritesArtifact` proves the capture is non-vacuous — a capture that
silently writes nothing (e.g. the `read_stdin_safely()` returns-a-dict gotcha:
do NOT `json.loads` it again) makes the leak asserts pass vacuously.

## `classify_release_path` local-only ≠ git-ignored

`classify_release_path("cc/_working_summary.md") == "local_only"` reads like
"this can never escape," and that assurance is **false for git**. `local_only`
governs exclusion from the **release archive** (what ships in the sdist/wheel) —
it says nothing about whether git tracks the file. The `cc/_` prefix in
`surface_contract._LOCAL_ONLY_PREFIXES` keeps the file out of the *package*; the
committed `.gitignore` is a *separate* list that ignores specific `cc/_*` globs
hand-added per artifact (there is no blanket `cc/_*` rule). The two are
independent, so a file can be `local_only` AND fully git-trackable at the same
time. The independent oracle is `git check-ignore <path>` — trust it over the
classifier when the question is "will this get committed."

So a file the harness **writes at runtime** under `cc/_` and means to be a
disposable (e.g. the live working-summary doc `cc/_working_summary.md`) needs an
**explicit** entry in BOTH places, or it leaks into history:

- the committed **`.gitignore`** — else `/commit`'s `git add -A` stages a
  per-session disposable on the self-host repo;
- **`cli.py::REQUIRED_GITIGNORE`** — else a fresh `espalier init` never ignores
  it and the adopter commits it on day one.

**Anchor the entry unless any-depth is genuinely what you mean.** A pattern with
no leading or embedded separator matches at *every* depth, so a bare `logs/`
also excludes an adopter's `src/**/logs/` — silently, with no diagnostic, which
is exactly how `reports/` shipped. Write `/logs/`. The exceptions are entries
whose NAME cannot collide with adopter content (`__pycache__/`, `*.pyc`,
`.espalier*/`), where any-depth is the safer default and the constant says so.
`tests/test_init_gitignore_default.py::test_required_entry_shapes_are_covered`
enforces this — a new single-segment entry must be anchored or declared
any-depth on purpose, so getting it wrong reds rather than ships.

This is the inverse of a generated-*managed* file (`cc/PACK_MANIFEST.txt`,
`cc/LIVE_SURFACE.md`): those are public and tracked by design. The trap is
specific to harness-*written*, meant-to-be-ephemeral artifacts — the
classification answers "does it ship," not "is it ignored." Compare the
sibling-class footgun *New Files Under `.espalier/` Need
`surface_contract._LOCAL_ONLY_PATHS` Registration* (same shape: local-only
routing and the gitignore/registration that must accompany it are decoupled).

**Proof hint:** for any new local-only artifact the harness writes, run
`git check-ignore <path>` (NOT the classifier) to confirm it is ignored, and
lock the committed `.gitignore` with an assertion —
`tests/test_session_summary.py::TestArtifactRouting::test_working_summary_doc_is_gitignored`
is the pattern (read the `.gitignore` lines, assert the path is present).

**Two git-ignore oracles, opposite scoping, on purpose.**
`tests/_git_oracle.py::require_is_gitignored` asks what git does HERE --
`.git/info/exclude` and the global excludes included, the index consulted
first -- the right question for "will this machine commit it".
`espalier/cli.py::_git_covered_entries` (DEF-635) asks what the root
`.gitignore` ALONE does, in a scratch repository with no template and the
global excludes pointed at nothing -- the right question for "will every
clone ignore it", which is what a required entry promises. A refactor that
unifies them breaks one contract; the divergence is the point.

## The live working-summary doc is last-writer-wins under parallel sessions

`cc/_working_summary.md` is a single fixed-path doc overwritten at every boundary
(the PostCompact hook at compaction; `/handoff` by hand). Two Claude Code
instances on the SAME working tree both write that one path, so the live doc shows
whichever session wrote LAST — it is NOT a per-session view, and a fresh instance
pulling it may be reading another session's state.

This is a *view* ambiguity, not data loss. The per-session archive
`cc/blueprints/compact_summaries/<stem>.md` is keyed by the transcript stem, so
every session's compaction captures AND its handoff leg are preserved with zero
clobber — the archive is the per-session source of truth; the live doc is a
single-session convenience view. (Separate git worktrees have separate `cc/`
dirs and never collide; the clobber is specific to two sessions sharing one
checkout — two terminal tabs, an IDE + CLI.)

**Proof hint:** if the live doc looks like it belongs to a different session, it
does — pull the per-session record instead with `read_summary --session <stem>`
(or read `cc/blueprints/compact_summaries/<stem>.md` directly). Per-session
isolation of the *live* doc was considered and deliberately deferred (the archive
already makes the data parallel-safe; the convenience view is not worth the
self-identity machinery for a solo/small-team toolbelt).

## A build run concurrently with the full suite false-reds `copytree(REPO_ROOT)` tests

Some tests copy the whole repo tree — `shutil.copytree(REPO_ROOT, tmp)` (the
clean-checkout / source-checkout doctor tests). `copytree` scans the root, then
copies each child; if a child directory vanishes between the scan and the copy it
raises `shutil.Error: [(src, dst, "[Errno 2] No such file or directory: ...")]`.

`python -m build` (sdist) creates a transient `<name>-<version>/` staging
directory at the repo root and removes it when the build finishes. Run it while
the full suite is going and a `copytree(REPO_ROOT)` test can scan the root during
that window, then fail when the staging dir disappears mid-copy — a **false RED
that has nothing to do with your change** (it reproduces clean the instant nothing
else is touching the repo). The same hazard applies to anything that briefly
writes-then-deletes a top-level path during a suite run (a parallel `pip install
-e .` egg-info, a second pytest that builds, an editor autosave of a temp).

**Mitigation:** run the full suite alone. Do packaging/sdist spot-checks *before*
or *after* it, never overlapping.

**Reinforcement (a second trap in the same episode):** a backgrounded command's
REPORTED exit code is the *last chained command's*, not the one you care about.
`pytest -q > out; echo done; tail out` reports `tail`'s exit (0) even when pytest
failed with exit 1. Trust the captured summary line (`N failed, M passed`), not
the completion frame — the untrusted-oracle move (see "A rendered test-failure
frame is not a test result").

## A path in the seed list is not the content an adopter receives

`managed_inventory.get_seed_docs()` returns **repo-relative paths**, not
payloads. Several of those paths resolve, via `get_seed_asset_source()`, to a
deliberately near-empty **stub** under `espalier/assets/seed/` — the adopter is
meant to fill it with their own project's material. `docs/SHARP_EDGES.md` and
`docs/CONVENTIONS.md` are both this shape.

So "is this text adopter-facing?" cannot be answered from the path list. On
2026-08-15 a review lane reported a defect at `docs/SHARP_EDGES.md:514` on
exactly that reasoning; driving `init` refuted it — the adopter's copy is **27
lines** and carries **zero** occurrences of the flagged text, while the
self-host file is 4,371 lines.

The inverse of this has bitten too, which is why it is worth a section rather
than a note: `tests/test_denial_reasons.py` once built its population as
`REPO_ROOT / rel` and so derived its citations from the 4,295-line self-host
file instead of the stub the adopter actually gets — a gate reading the wrong
document entirely, and green because both existed.

**Rule:** resolve the SOURCE (`get_seed_asset_source`), or drive `init` onto a
throwaway tree and read the file there. Never reason from the rel-path list.

## Spawned agents share one worktree + index — isolate mutate-capable fan-outs

An Agent/Task sub-agent runs in the MAIN session's live worktree and git
index, NOT a sandbox — unless you launch it with `isolation: worktree`. A
git-capable agent's stash/reset/checkout mutates your staged state; a
verified-green suite can go red minutes later with no visible cause (a real
2026-06-23 instance flipped 25 `fuse` tests via an A/B stash experiment that
left staged deletions un-staged). Rule: spawn mutate-capable or concurrent
agents with `isolation: worktree`; keep review/audit agents read-only
(Explore, or Bash scoped to status/diff/log/show); re-verify `git status`
and re-run gates after any git-capable agent returns. See
`docs/FAILURE_MODES.md` §16.1.

**2026-08-15 — it is the whole WORKTREE, not just the index, and it poisons a
concurrent suite.** A `code-reviewer` agent ran a bare `git stash` to diff
against HEAD, taking all 20 modified files with it, then popped it. Every edit
survived byte-identical — but two full-suite runs overlapping that window each
reported a phantom failure that passes in isolation (a mirror-parity test, then
`test_reflect_protocol`), because the tree they were reading changed mid-run.
Two ten-minute runs discarded. So the rule has a second half: **never run the
full suite concurrently with a git-capable agent.** Sequence them, or give the
agent `isolation: worktree`. And when a post-agent grep says your edit is
missing, check for a line wrap before concluding it was reverted — a phrase that
spans a newline greps as absent.

## Interactive prompts on a default CLI command must be isatty-gated + default-NO

The espalier CLI is non-interactive on its command paths -- the only other
`input()` lives in an opt-in subcommand. A prompt added to a CI-reachable default
command (like `init`) would `EOFError` on a captured-subprocess pipe and raise
under pytest's stdin stub, breaking every non-interactive run -- unless it is
gated on `sys.stdin.isatty() and sys.stderr.isatty()` AND defaults to the
non-acting answer. `init`'s "wire hooks now?" offer (in
`_reconcile_existing_settings`, case b) follows this: off a TTY it never fires and
falls through to the preserve-and-warn default; `--wire-hooks` stays the
non-interactive way to say yes. Mirror the `isatty` discipline of
`_maybe_nudge_source_checkout`.

Test the gate DETERMINISTICALLY: force `sys.stdin.isatty` / `sys.stderr.isatty`
to fixed values rather than relying on pytest's capture mode (`-s` leaves a real
TTY on stderr and would flip the test), and monkeypatch `input()` to raise so a
regression that prompts off a TTY fails loudly instead of hanging.

## A Long-Latent Issue That Just-Now Bites Is a Class

When something that has "been around a while and just now bites" surfaces, it is
a new **class** of errors, not a single instance — the root cause is an
unforeseen, never-scoped gap, so "it only happened once" *is* the under-scoping.
Name the spirit, hunt siblings mechanically (the count is a floor), fix the class
with a pack.

See [sharp-edges/a-latent-issue-that-just-bit-is-a-class.md](sharp-edges/a-latent-issue-that-just-bit-is-a-class.md)

## A Hook-Blocked Bash Call Skips Its Bundled `git add`

A blocked Bash tool call is all-or-nothing: the harness denies the entire command
string, so a `git add` bundled (via `&&` or a newline) with a blocked `git commit`
never runs, and the next clean commit captures a stale index. Stage and commit as
separate calls; verify with `git status` + `git show HEAD:<file>` after.

See [sharp-edges/blocked-bash-call-skips-its-bundled-git-add.md](sharp-edges/blocked-bash-call-skips-its-bundled-git-add.md)

## A Rotted Citation's Fix Target Is Itself a Claim

When a doc→test citation rots into a phantom, the reflex "reword the claim to
match the lesser reality" is wrong about as often as right — the cited class may
be alive in a sibling file. Grep the symbol tree-wide (and the `/recall` corpus's
`documented_in`) before rewording: repoint (if it lives elsewhere) → restore the
test (if coverage was lost) → reword (genuine over-claim), last.

See [sharp-edges/citation-rot-verify-fix-target-tree-wide.md](sharp-edges/citation-rot-verify-fix-target-tree-wide.md)

## Pre-Delete Reference Sweep — Every Spelling, Full-Suite Gate

Deleting a tracked file has a blast radius wider than one grep. Two spellings hide
from a single-pattern search — `name.ext` and bare `name` (docs cite files without
the extension) — and the contracts that catch a missed citation or a provenance
leak in the *cleanup edit* fire only on a full-suite tree walk, not a targeted run.
Sweep both spellings, re-scan the cleanup edits as a new surface, and gate on the
whole suite before calling a deletion done.

See [sharp-edges/pre-delete-reference-sweep.md](sharp-edges/pre-delete-reference-sweep.md)

## `.github/workflows/` Is a Provenance Shipping Surface

`.github/workflows/*.yml` counts as a public shipping surface:
`tests/test_no_provenance_in_shipped_code.py::test_no_build_history_on_shipping_surfaces`
scans it and fails on any internal build-history tag (`TP-NNN`, `round-N`, `wf_…`)
in a workflow comment. It *feels* like private dev config, so it is easy to miss.

See [sharp-edges/github-workflows-are-a-shipping-surface.md](sharp-edges/github-workflows-are-a-shipping-surface.md)

## A Stale egg-info Makes a Packaging Gate Verify the Previous Config

setuptools caches the package file list in `*.egg-info/SOURCES.txt` and reuses it
on later builds after the config that produced it is gone. Delete a
`[tool.setuptools.package-data]` glob, rebuild without clearing the egg-info, and
the wheel still ships what the deleted glob matched — so the payload assertions
pass against the *previous* config. Clear `build/` **and** `*.egg-info/` before
trusting any packaging measurement.

This section previously claimed the reverse — that `include-package-data` ships
any git-tracked file, making the globs redundant and a drop-the-glob
earn-the-red impossible. Driven three ways, that is wrong: with no
`setuptools.file_finders` plugin installed, setuptools cannot see git at all, and
the globs are the only thing shipping `espalier/assets/**/*.md`. They are the
gate, and the red is earnable.

See [sharp-edges/include-package-data-ships-tracked-assets.md](sharp-edges/include-package-data-ships-tracked-assets.md)

## The Install Path Can Break While Every Test Is Green

A repo's documented primary install path can be **structurally broken for a fresh
adopter** while the dev machine and the entire suite report green. The masking
agent is Python's cwd shadowing: when the working directory *is* the source
checkout, `python -m <pkg>` resolves against `sys.path[0]` regardless of whether
the install works. Verify with a fresh-venv walk from a foreign cwd.

See [sharp-edges/install-path-green-masked-by-cwd-shadow.md](sharp-edges/install-path-green-masked-by-cwd-shadow.md)

## Shipping a Doc Verbatim Subjects It to Content Contracts

A change that byte-mirrors an internal doc verbatim as a shipped asset can clear
both pre-flight gates — the artifact review *and* scope-check — because both are
blind to doc-content contract collisions (hygiene IDs, broken links, mirror-link
parity). The full suite is the first oracle that sees them; pre-scan a
to-be-shipped doc against the live content contracts before landing.

See [sharp-edges/shipping-docs-verbatim-collides-with-content-contracts.md](sharp-edges/shipping-docs-verbatim-collides-with-content-contracts.md)

## A skipif→Marker Convert Drops Filter-less Consumers

Replacing a **self-detecting `skipif`** (e.g. "skip when `ESPALIER_MEMORY.md` is absent")
with a **marker** selected via `-m "not <marker>"` moves protection from "every
run self-skips" to "only runs that pass the filter skip." Any pytest consumer that
does not pass the filter (a bare `release_check` pytest, a fresh clone) now
**runs** the tests. Enumerate every consumer, or auto-skip at collection instead.

See [sharp-edges/skipif-to-marker-drops-filterless-consumers.md](sharp-edges/skipif-to-marker-drops-filterless-consumers.md)

## Classifying a New Test Grows the Frozen Marker Grandfather Tuple

`tests/conftest.py::_MARKER_RULES` classifies each `test_*.py` by name; its `unit`
tuple is a **frozen grandfather list** that `test_sister_site_probe_ceilings.py`
pins to chip DOWN, never grow. Adding a new test's name there to classify it reds
the ceiling contract (only the full suite counts the tuple), while marker-taxonomy
stays green. Give a fast unit test its marker with a `# pytest-marker: default-unit`
comment instead — the opt-out assigns `unit` without growing the tuple.

See [sharp-edges/marker-classification-grows-grandfather-tuple.md](sharp-edges/marker-classification-grows-grandfather-tuple.md)

## A Parity Contract That Pins Presence, Not Absence

**What it is:** A doc↔code parity test that asserts every *real* token in the code
set appears in the doc (doc ⊇ code) but never that every token in the doc is real
(doc ⊆ code) catches *drops* — a real member removed from the doc — while staying
blind to *additions/overstatements* — a fabricated member added to the doc. It is
green on a doc that names a superset of reality.

**How you hit it:** A parity contract over an enumeration — the protected zones, a
command list, a marker set — asserts each real member is present in the doc block.
Injecting a fabricated member into that block (a non-existent zone, a phantom
command) leaves it green, because the closed-world direction was never checked. A
presence-only pin certifies "the doc is not missing anything," never "the doc
invents nothing" — so an overstated doc reads as in-sync.

**How to avoid it:** Pin BOTH directions — code ⊆ doc (no drops) AND doc ⊆ code (no
inventions). Tokenize the doc's enumeration and assert each token is in the real set
(plus a calibrated non-member allowlist), and earn the closed-world arm's red by
injecting a fabricated member and confirming it reds. Sibling of "A property-pinning
test that feeds only conforming inputs falsely certifies the property" (a green
presence test proves the ⊇ direction, not the property) and of the must-NOT-trip
negative corpus (both close the *silent* direction). This is the one-directional
special case of "A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test
Rots Silently" below. Maps to `docs/FAILURE_MODES.md` §1.11 (absence-as-allow: the
unchecked direction reads as in-sync).

## A Closure Guard That Checks Name-Membership, Not Runtime Reachability

**What it is:** A guard that asserts a symbol / import / file is *named* in an
allowlisted set passes while the runtime path that would actually reach it is broken.
Membership in a set is not reachability at run time.

**How you hit it:** An import-closure guard globs a *flattened* deploy set and
asserts a script's bare `import _hook_utils` names a module present in that set —
green — while the deployed layout has no `sys.path` shim, so the same import raises
when it actually runs. The guard measured "the name is in the set," never "the
import resolves where it runs." Latent: nothing bites until the runtime path is
exercised in the deployed layout, so a green suite certifies a crash.

**How to avoid it:** A reachability guard must exercise the runtime resolution, not
the name membership — import the module in a subprocess with the *deployed*
`sys.path`, resolve the path against the deployed tree, or assert the shim that makes
the import work is present. "It's in the allowlist" is not "it resolves when run."
Sibling of `docs/FAILURE_MODES.md` §1.12 (sister-predicate domain blindness — the
predicate inspects a narrower domain than the one it claims) and of "'ZERO
deny-predicate changes' can hold while a deny SURFACE is restructured" (a name-set
check is not a live-behavior check).

## A Detector Scoped to One Store While Claiming Broader Coverage

**What it is:** A scanner/detector that walks a SINGLE store — one directory, one
config, one index — but whose name or docstring implies whole-surface coverage
silently misses every sibling store. It reports "0 findings across the surface"
having looked at a fraction of it.

**How you hit it:** A duplicate/parity detector walks one memory store and reports
clean, blind to sibling stores (a `docs/sharp-edges/` tree, a standing-principles
doc) that carry the very duplicates it hunts. "0 misses" is 0 misses *in the one
store it iterates*, presented as 0 across all of them — the un-walked stores'
misses are invisible, not absent.

**How to avoid it:** Make the detector's *iterated* domain equal to its *claimed*
domain — enumerate every store the name implies, or narrow the name/docstring to the
one store it actually walks. A "whole-surface" claim needs a whole-surface walk.
Sibling of `docs/FAILURE_MODES.md` §1.11 (absence-as-allow — the un-walked store
reads as clean) and §1.12 (the domain the detector iterates is narrower than the
domain it claims).

## check_pack_landing Sees Only Done/ Packs Stamped State: LANDED

**What it is:** `scripts/check_pack_landing.py` scans *only* `task-packs/Done/` and
reports any pack there whose `## Landing` `State:` is not `LANDED`/`SCRAPPED`.

**How you hit it:** A pack that landed but was never *moved* to `Done/` is outside
the scanned domain — the lint never sees it, so "0 unstamped" is silence, not proof.
An incomplete Landing stanza (no `State:` line) on a not-yet-moved pack is equally
invisible. Absence reads as allow (`docs/FAILURE_MODES.md` §1.11), made concrete in
the harness's own closeout tooling.

**How to avoid it:** Treat a clean `check_pack_landing` as covering *only moved*
packs. Move a pack to `Done/` as the last landing step (so it enters the domain), and
keep the Landing stanza complete at authoring time. `--strict` exits 1 but still only
over `Done/`; it does not widen the domain.

## A Hand-Maintained Doc Enumeration With No Code-Pinned Parity Test Rots Silently

**What it is:** A doc that RE-LISTS a set the code already owns (the protected zones,
the plan-exempt prefixes, a managed-file inventory) drifts the moment the code set
changes, because nothing binds the doc copy to the source of truth — and no test
fails, so the drift is invisible until a reader trusts a stale list. Worse, the
obvious fix (a parity test pinning doc→code) can carry the *same* shape one level up:
the test iterates a HAND-MAINTAINED list of enumeration SITES, and a newly authored
enumeration never registered in that list is silently unguarded.

**How you hit it:** A set the engine owns is re-listed by hand across several shipped
docs; the copies drift from the source when the engine's set changes, and nothing
reds. Then a parity test is added — but its site-list is itself a hand-maintained
enumeration, so a sibling doc that grows a *new* copy of the list is not among the
test's sites and goes unpinned.

**How to avoid it:** When a doc enumeration mirrors a code set, pin it to the code
source of truth at *authoring* time, and DERIVE the parity test's site-list from code
wherever possible (a walk, a glob) so a new site cannot be silently omitted. This is
the general parent of "A Parity Contract That Pins Presence, Not Absence" above (that
entry is "a parity test exists but pins only one direction"; this is "no code-pinned
parity test exists at all — or its site-list is an unpinned enumeration one level
up"). Sibling of `docs/FAILURE_MODES.md` §1.11 (a missing binding reads as "in
sync").

## A Link Check That Scans Link Text Mishandles a Literal `<`

**What it is:** A broken-link or citation checker that keys on `<...>`-delimited or
angle-bracket targets misfires on Markdown link *text* that contains a literal `<` —
e.g. `` `[/recall <topic>](...)` `` or `` `[a<b](...)` ``. The `<` in the visible
text is mistaken for (or collides with) the target-parsing span, so a genuinely
broken link hides in the guard's blind spot.

**How you hit it:** A checker scopes its `<` handling to the wrong span — link *text*
vs link *target* — so a link whose text carries a literal `<` is skipped or
mis-parsed, and a dead target behind it is never reported. The guard runs green
precisely on the links it cannot see.

**How to avoid it:** Parse the link's TARGET (the `(...)` half) independently of its
TEXT (the `[...]` half); a `<` in the text must not gate whether the target is
checked. Keep any literal `<` used to *document* this shape inside a code span, not
bare link text, so the checker does not false-positive on its own defining material
(the autoimmune footgun, `docs/FAILURE_MODES.md` §1.13). Dogfood the checker on the
doc that describes it.

## An Exported "Single Source of Truth" Constant That No Reader Imports

**What it is:** A module exports a named constant as *the* canonical value for a
contract — a settings-sentinel key, a marker string, a magic path — yet every actual
reader and writer hardcodes the underlying literal instead of importing it. The constant
*claims* a centralization the code does not have: renaming it changes nothing, and its
docstring may even credit a consumer that cannot reach it. It is worse than the bare
literal it purports to replace, because the diff reads as "handled."

**How you hit it:** The JSON settings-sentinel key lived in `managed_markers.py` with an
`__all__` export and a docstring naming `config_guard` as its consumer — while
`config_guard` (a stdlib-only hook that by contract cannot import `espalier`) never
touched it, and the real writers/readers (`cli.py`, `cleanup.py`) each hardcoded the
literal string. The "SoT" was a lie with a docstring, and the constant and the literal
could drift apart silently.

**How to avoid it:** Either wire every production reader/writer through the constant AND
add a test that the bare literal appears nowhere else (an AST scan for the string
`Constant` outside the definer file — with a scan-witness and a planted-positive fixture
so the gate is not vacuous), or delete the constant and keep the literal. Never ship a
lonely SoT constant. When a constant's docstring names a consumer, verify that consumer
actually imports it — a zero-import hook by definition cannot. (The born-weak-gate
discipline for the accompanying test lives in `docs/FAILURE_MODES.md`.)

## Renaming a file to end a naming collision — classify per-occurrence, and re-check the collision's own descriptions

**What it is:** When a rename exists to *end* a naming collision (the committed
`MEMORY.md` → `ESPALIER_MEMORY.md`, so it stops colliding with Claude Code's hardcoded
machine-local auto-memory `MEMORY.md`), a tree-wide find-replace is wrong in two distinct
ways. First, the old name still legitimately means the *other* file in many places —
`docs/MEMORY_SYSTEMS.md`, the `## Memory systems` block in `CLAUDE.md`, and
`memory_sort_audit.py`'s `entry.name == "MEMORY.md"` auto-memory guard — and those must
stay. Second, and easier to miss: the prose that *describes* the collision ("two files
both named `MEMORY.md`") gets flipped to nonsense ("two files both named
`ESPALIER_MEMORY.md`"), because the token there is technically the renamed file sitting
inside a sentence about the naming itself.

**How you hit it:** A mechanical `MEMORY.md → ESPALIER_MEMORY.md` pass across the tree.
A careful per-occurrence classification (committed → rename; auto-memory → keep) catches
the first class — but the collision-description corruption slips through *even* a careful
classification, because each such token genuinely *is* the committed name; only the
surrounding claim is now false. A historical `CHANGELOG.md` line was corrupted exactly
this way and only a follow-up sweep caught it.

**How to avoid it:** Classify every occurrence — never a tree-wide `sed`; the occurrences
that must stay are load-bearing. Then, after the rename, run a **collision-description
sweep**: `git grep '<new-name>'` filtered to `both named | shares the name | collision |
auto-memory`, and hand-check each hit — those are the sentences the rename just falsified.
The dual-sense docs (`docs/MEMORY_SYSTEMS.md`, `CLAUDE.md`, `docs/CHEAT-SHEET.md`,
`examples/auto-memory.template.md`) are where both senses coexist and every line is a
judgment, not a substitution. (When the rename is routed through a per-file constant, a
mechanical replace still can't see raw-string references in prose — declare the literal in
the pack's `## Affected literals` so the scope-walk surfaces them.)

## A prescribed-but-unbuilt companion test cited via a negation is invisible to the phantom-citation gate

**What it is:** `tests/test_doc_test_citations.py` asserts every `tests/test_<name>.py`
citation in a shipped doc resolves to a real, tracked file — but it deliberately *skips*
a citation whose own line (or the line directly above) carries a negation token, so it
never false-fires on "has **no** companion `tests/test_<name>.py`" prose. That exclusion
is correct. Its side effect: a doc that *prescribes* a future test in negated form —
"it has no companion `tests/test_<name>.py` … tracked as post-OSS hardening" — reads to a
human as live intent, yet is mechanically silent. Nothing reds on the missing file,
because the negation is exactly what suppresses the check.

**How you hit it:** You defer real work in a doc by describing the absent artifact ("it
has no companion X", "a later fix will…") and naming a tracker home that does not exist
("tracked as post-OSS hardening", "see the follow-up"). The phrase is a claim with no
reader: no ledger row, no pack, no issue, and — because it is negated — no mechanical
citation gate either. The intent rots in place until a human happens to re-read the
paragraph.

**How to avoid it:** Route deferred work to a *real* tracker at authoring time — a
`FORWARD_LEDGER.md` row or a `TP-*` pack — never a named-but-nonexistent home. When the
follow-up lands, flip the citation to its live (non-negated) form AND `git add` the new
file in the same change, so the phantom-citation gate resolves it instead of skipping it.
Treat the negated-citation form as a blind spot by design: it is the one shape of
forward-intent the doc-citation contract cannot see.

## An AST content-scanner gated on a call-name allowlist is blind to every user-facing sink the allowlist omits

**What it is:** The no-non-ASCII-in-runtime-output contract (`_collect_print_string_args`
in `tests/test_portability_contract.py`) walks the full AST — it has since it was first
written; it was never a line grep — but it only inspects the arguments of calls whose
name is in an allowlist (`_USER_FACING_CALLS = {print, sys.stderr.write, sys.stdout.write}`),
skipping every other `Call` node (`if name not in _USER_FACING_CALLS: continue`). A string
that reaches a reader through a sink NOT in that set is invisible to the scan *no matter
how it is laid out*. Two em-dashes lived in `CheckResult(..., detail=…)` strings — never a
direct `print()` argument, reaching a reader only through the `CheckResult` constructor's
`detail` field (rendered by `print_results` in `scripts/release_check.py`; serialized via
`json.dumps` in `espalier/selfcheck.py`) — and the green contract never saw either,
because `CheckResult` was not an allowlisted name. The fix was to add the constructor
(and its `detail` field) to the recognized sinks — a coverage-completeness fix, not a
change to how lines are read.

**How you hit it:** You trust a green content-contract (ASCII, secrets, i18n — whatever it
scans) as if it covers *all* user-facing output, when it actually covers only the specific
sinks its allowlist names. An indirect-print path — a result dataclass rendered later, a
logger wrapper, a `"\n".join(parts)` handed to `print` — carries the offending content to
the user through a call the scanner does not recognize, so the contract stays green while
the defect ships. The gap is completeness of the *sink* allowlist, not the parser: an AST
walk that gates on names is exactly as blind to an un-listed sink as a grep would be. (It
is tempting to blame line locality — a multi-line call — but that is not the mechanism
here: the walker parses the whole tree; it simply never looked at that `Call` node.)

**How to avoid it:** When a content-contract gates on a call-name allowlist, treat the
allowlist as the coverage boundary and keep it honest: enumerate the indirect-print sinks
(result constructors, join-then-print, wrapper functions) and either add them or document
— *at the allowlist* — that they are deliberately uncovered, so a green read is not
mistaken for "all output is covered." Auditing argument *content* still wants an AST walk
over a grep (a wrapped argument is reached the same as an inline one), but the
load-bearing question is "which sinks does the allowlist recognize," not "single-line vs
multi-line."

**Update 2026-09-03 (`DEF-677`) — the `join-then-print` instance named above is now
closed, and closing it exposed a second, worse shape: two contracts in one file that did
not share a collector.** Every widening of `_collect_indirect_operator_strings` — six
rounds, rules (a)–(f) — fed `_all_operator_strings`, which only the *interpreter-token*
contract consumed. `TestNoNonAsciiInRuntimePrints` called the direct-print collector,
so none of that work ever reached the ASCII contract. Result: 26 offending strings and 42
crash-capable characters across nine report renderers, all green, for the entire life of
the test. Rule (g) (accumulators reaching a `sep.join(...)`) plus pointing the ASCII test
at the union net was the fix — and note that **neither half reds alone**: without (g) the
union finds 0, and without the union swap (g) is collected by a contract that does not
check ASCII. Both halves are pinned by must-engage twins
(`test_collector_reaches_a_joined_accumulator`, `test_ascii_contract_consumes_the_union_net`),
because mutation testing showed both were silently deletable with the suite green.

**The first cut of rule (g) covered 3 of 13 live shapes, and its own docstring implied
completeness.** It anchored on `Return` → bare `Call`, which missed `sep.join(x) + "\n"`
— this repo's dominant renderer idiom at 20+ sites — and missed `print(sep.join(parts))`,
i.e. *the very instance this entry names*. The doc would have claimed a shape closed that
one grep falsified. The corrected rule walks the whole expression and adds an
assignment hop; **driven on a synthetic matrix, coverage is now 11/11**, including
`sys.stderr.write(sep.join(...))` and `out = sep.join(lines); print(out)`.

**Still open, measured not assumed** — two shapes remain blind, and they are named here so
the boundary is declared rather than implied:
1. **A literal in the return expression that never enters the accumulator** —
   `return "hdr — x\n" + "\n".join(lines)`. Live at `tools/cc/hooks/session_start.py::_memory_toc`
   (repaired by hand; the gate still cannot see it).
2. **Multi-hop** — helper returns, a second joins, a third prints. Rule (f) resolves one
   hop and only within the defining file.

**The generalisations worth carrying:** (1) an allowlist is one coverage boundary, but
*which test consumes the collector* is a second one, invisible at the allowlist — when you
widen a shared helper, grep its callers and confirm the contract you meant to strengthen is
among them; (2) enumerate the shape population **before** claiming a shape class is closed,
because a rule that catches the exemplar you wrote it against and misses the house idiom
reads exactly like coverage; (3) per `STANDING_PRINCIPLES` §11 the scope-out here ("FP-prone
dataflow with no cheap AST answer") was itself a claim, never measured, and fell with zero
false positives across the tree.

## A skip-if-exists deploy helper has no upgrade-drift path — an untouched template silently keeps stale bytes across versions

**What it is:** `_deploy_file`'s non-`.py` branch (the init seed-doc deploy; since 2026-09-05
that writer is `_write_seed`, fed by `managed_inventory.render_seed_body`) used a bare
`if dest.exists() and not overwrite: skip`. It was the only deploy helper with no drift
detection — `_deploy_managed_py` and `_deploy_asset_md` both compare a marker/hash and
regenerate a managed-but-stale copy, but `_deploy_file` kept whatever was on disk. So an
operator who never touched a seeded convention doc (`memory/README.md`, the `docs/`
scaffolds) kept the *old* packaged bytes forever — and `deploy_harness` never re-visits
the seed docs at all, so `espalier upgrade` could not fix it either. The bug bit on
re-init and stayed invisible on upgrade.

**How you hit it:** You add a new "deploy a template if it isn't there yet" helper (or
copy the shape of one). It reads correctly for the first install and for preserving an
operator's edits — but it has no answer for "the packaged content improved and the
operator never customized this file." That copy is now pinned to the version that first
wrote it, and nothing surfaces the staleness because the deploy silently skipped. Worse,
if the only refresh entry point (here `cmd_upgrade`) can't prove a legacy copy untouched,
it preserves it and reports "re-deployed 0" — a false "all current" for exactly the
long-lived installs that most need the refresh.

**How to avoid it:** Give a template-deploy helper a drift path. The pattern now used
here (`_seed_redeploy_decision`) writes a first-line provenance stamp recording the
sha256 of the bytes below it, and on re-deploy refreshes *only* a copy it can prove is
untouched (on-disk hash matches the stamp) whose packaged content actually changed —
preserving an operator edit (hash mismatch) or a legacy unstamped copy (can't prove
untouched). Use a token DISTINCT from `espalier:managed` (here `espalier:seed-version`)
so `cleanup._file_is_managed` still treats the file as operator-owned and
`clean-generated` never deletes it; and surface the count of legacy-unstamped copies so
a "0 refreshed" line isn't misread as "all current." Known not-yet-covered sibling of
this exact class: `fuse.py::_seed_bench_results` writes `bench/RESULTS.md` with the same
skip-if-exists, no-drift shape (and a non-atomic `write_text`) — lower stakes (fusion is
a one-time bootstrap, not re-visited by upgrade), but the next sweep should close it.

## A gitignored directory holding one tracked file breaks every skip predicate keyed on that directory

**What it is:** Self-host-only tests skip on adopter clones by probing for dev tooling
that is gitignored — `@pytest.mark.skipif(not _DIR.is_dir(), ...)`. That predicate is
wrong the moment the directory contains *any* tracked file. `task-packs/` was gitignored
**except `task-packs/CLAUDE.md`** (since 2026-09-21 the ledger and the active packs are
tracked too, while `Done/`, `Merged/` and `Scrapped/` still are not), so git materializes
the directory in every clone and CI checkout while the landed packs inside it are absent. `_PACKS.is_dir()` returns `True` there,
the skip never fires, and the test runs against an empty population — a guard whose
non-vacuity floor then reds across every CI job and Python version. The directory exists;
its contents do not; the predicate only asked about the directory.

**How you hit it:** You add a self-host-gated contract and verify the skip by driving the
detector against a `tmp_path` tree with no such directory. It skips cleanly, so criterion
"skips on an adopter clone" reads satisfied. **Two independent oracles hide the defect
here, which is why it survives review:** (1) a `tmp_path` fixture deletes the *whole*
tree, which a real clone does not — the fixture models "directory absent," but the real
failure is "directory present, empty"; (2) if the path also carries `export-ignore` in
`.gitattributes` (as `task-packs/Done/` does), then `git archive`, the sdist, and every
packaging-based probe omit the directory entirely and false-green too. `actions/checkout`
and `git clone` do **not** honour `export-ignore`. Only a real clone reproduces it.

**How to avoid it:** Gate on an artifact that is gitignored *in full* — a subdirectory or
a specific file — never on the mixed-tracking parent. `tests/test_cross_pack_assertions.py`
gates on `task-packs/Done/`; `tests/test_forward_ledger_completeness.py` gated on
`task-packs/Deferred/` **and** `FORWARD_LEDGER.md` together while both were untracked,
with the second conjunct present so a partial tree reached a clean skip rather than a
`FileNotFoundError`; both ship since 2026-09-21 and its gate is the ledger alone, an
absent `Deferred/` being an empty population. Confirm the discriminator mechanically — `git ls-files <dir>` must
print nothing for whatever you key on.

Then **extract the predicate into a named function** rather than inlining it in the
decorator, or the fix cannot be regression-tested: on the self-host tree the correct and
incorrect spellings both evaluate `True`, so only a test that *calls* the predicate with a
clone-shaped fixture can tell them apart. Verified by mutation — with the expression
inlined, reverting it to the broken form left the whole module green; with it extracted,
the same mutation dies. The same rule applies to any threshold a gate enforces: a test
that restates the constant in its own body is comparing constants, and the floor it claims
to prove can be lowered to zero with the suite still green.

## The source tree is not an oracle for the produced artifact

**What it is:** When the question is *what does a user actually get* — an adopter after
`init`, a cloner after `git clone`, a consumer after `pip install`, a reader of the
release archive — inspecting the source tree cannot answer it. The tree is the input; the
question is about the output. A grep, a file-existence test, or an archive listing returns
a confident, correct number that answers a *different* question, and nothing looks wrong.

**How you hit it:** the proxy is not broken. `grep -c` really did count; `git archive |
tar t` really did list the archive. The defect is that the oracle **cannot express the
failure you are hunting**, so it reports clean — and a clean report from a working command
reads as evidence. Attested five times here across four different delivery mechanisms:
a `tmp_path` fixture modelling "directory absent" when the real state is "present, empty";
`git archive` blind to `export-ignore`; `git archive` and the sdist *both* blind to
untracked files because both are index-based; asset-presence used to answer
adopter-reachability when there are four delivery paths; and `espalier <verb>` passing
only because the repo root shadows the install.

**How to avoid it:** produce the artifact and look at it — a real `init` into a scratch
repo, a real `clone`, a non-editable install run from outside the repo. Before trusting a
measurement, ask: *if the defect were present, would this command's output differ?* If you
cannot say yes, the number is decoration. Two proxies agreeing is not confirmation when
both read the same wrong source. **A proxy is usable for a floor, never for a null** —
"found 30" is a lower bound; "found 0, therefore clean" is the trap.

Full entry, with the instance table and the drive-it recipes:
[`docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md`](sharp-edges/source-tree-is-not-an-artifact-oracle.md).

## The Measuring Instrument Is a Claim Too

**What it is:** the probe you write to answer a question — a shell pipeline, a throwaway
script — is untested code, and when it is wrong it does not crash. It returns a plausible
number, usually a low or zero one, and a low number reads as *clean* and ends the
investigation. This is the other half of the entry above: that one covers *correct code
answering the wrong question*; this covers **incorrect code answering the right one**.

**Attested, one unit of work:** an extract-then-count probe reported `0 dangling` because
the extract had silently failed and it walked an **empty directory**; a link checker
flagged two "broken" links that were **inside fenced code blocks** (worked examples, which
cannot break); and a block enumerator claimed a doc lacked a disclaimer its siblings had —
it printed only fenced *contents*, and the disclaimer sat one line above the fence.

**How to avoid it:** assert a **population floor inside the probe, checked before its
answer** (`assert len(members) > 500` / `assert resolved >= 100`) — that turns a confident
null into a loud failure. Make the instrument fire on a case you know is there before
believing a null. Check the pipeline's exit status, not just its output. And suspect the
instrument hardest when its answer is convenient.

Full entry, with the instance table:
[`docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md`](sharp-edges/the-measuring-instrument-is-a-claim-too.md).

## A mutation proves what it kills, not what you meant it to kill

**What it is:** the third member of the family above. That pair covers *correct code
answering the wrong question* and *incorrect code answering the right one*. This is
**correct code, right question, wrong inference**: the mutation runs, the gate reds, and
the red is real — but it is caused by something other than the property you chose that
mutation to establish. "It went red" then reads as proof of a claim the run never tested.
**The tell is a missing control:** a mutation earns its red *for a reason*, and if the
variant you are ruling out also reds, the two are indistinguishable.

**Attested, one unit of work.** A guard was scoped to a section rather than a whole
document precisely because the wide scope would pass vacuously — and the mutation chosen
to prove that scoping mattered deleted a registry row carrying **both** occurrences of its
own identifier, so wide and narrow reddened identically. It proved the guard ranges over
its population and proved *nothing* about the scoping; a different row, whose identifier
appears elsewhere, discriminates. Separately, a prescribed proof was routed through the one
execution shape safe to mutate — that shape short-circuits earlier and **never reaches the
mutated region**, so the run came back green and green looked like "no defect". And a
harness pointed a test at a mutated copy by patching a module attribute, but patched a
**second module object** created by importing under a different name: `monkeypatch` raises
on a *missing* attribute, never on the right attribute in the wrong module, so the silent
no-op reported `1 passed` and looked clean.

**How to avoid it:** state the claim the mutation is meant to establish, then run **both
arms** and require them to disagree — red under the mutation *and* green without it. If
they agree, it is a tautology dressed as a discriminator; pick another. Make a patching
harness assert it patched something, because a no-op patch and a genuinely clean run are
the same observation. And treat an unexpected *pass* with the suspicion you would give an
unexpected failure — you only catch this one when you went in expecting red.

## A mutation proves nothing until its subject is committed

**What it is:** the fourth member of the family above, and the one that produces a
*green* run rather than a misread red. `git archive` reads the **committed**
`.gitattributes`, not the working tree. So a mutation that deletes an `export-ignore`
row, aimed at a file that is merely **staged**, changes nothing the gate can see: the
file was not in `HEAD` either way, the gate stays green, and the pass gets recorded as
an earned red. Nothing about the run looks wrong.

**Attested, twice in one session, in both directions.** A newly-authored doc was staged
with its `export-ignore` row and its `test_git_archive_parity.py::EXPORT_IGNORED_INTERNAL_DOCS`
pin. Removing the row → **15 passed**, read at the time as "the pin holds." After
committing the same file, removing the same row put it back in the archive and reds
**three** tests — including a dangling-link gate nobody predicted, because tracking the
file also made markdown links resolve into it. Same mutation, same tree, opposite
verdicts, and the only difference was `HEAD`.

**The general form, which reaches past git attributes:** *a mutation test must run
against the same state the gate's oracle reads.* Any gate whose oracle is a committed
artifact — `git archive`, `git ls-files`, a tag, a packed ref, a built wheel — is blind
to a working-tree mutation, and blindness presents as a pass. Ask what the oracle
actually reads **before** reading a green as evidence.

**The check:** before trusting a mutation, name the oracle's input. If it is `HEAD` and
your subject is not in `HEAD`, you have measured nothing. `git archive
--worktree-attributes` closes the attribute half of this specifically, but not the
membership half — an untracked file is absent from `git archive HEAD` no matter which
attributes are honoured.

**Related:** the three siblings above (wrong question / incorrect code / wrong
inference); `docs/FAILURE_MODES.md` §5 born-weak gates, of which this is the
*measurement-side* twin — there the gate cannot fail, here the *proof that it can* is
the thing that cannot fail.

## Resume picks the first *pending* step — a failed or running step is stepped over

**What it is:** `cmd_status` (`tools/cc/execution_plan.py::cmd_status`) computes the resume point
with `next((s for s in plan["steps"] if s["status"] == "pending"), None)`. That predicate
is an exact match, so a step in **any** other non-terminal state is passed over. Two
states qualify and both mean real work gets skipped: a step deliberately marked failed
(a session stopped on a blocker) and a step left running (a session died, was cleared, or
compacted mid-step). `/implement-pack --resume` then re-enters at the step *after* the
incomplete one, and every later gate runs on a foundation that was never laid.

**How you hit it:** the tracker looks healthy. `status` prints the failed step with its
note right there in the list — then prints a `Next:` line pointing somewhere else, and
`Next:` is the line you act on. Attested here: a unit's step 0 was left failed with a note
saying its fix was only half-landed, the handoff asserted "the execution plan is re-opened
at step 0 so --resume re-enters there", and `status` in fact reported `Next: step 2`. A
resume that trusted that line would have walked into the pre-flight step with the unit's
canary test still red. The prior session's claim was not careless — it described the
intent; nobody re-read the tracker to confirm the intent had been written down.

**How to avoid it:** read the **step list**, not the `Next:` line — the status header
prints `(N/M passed, F failed, P pending)`, and any nonzero `F`, or any `[>]` icon, means
`Next:` is understating where work stands. To genuinely re-enter an incomplete step you
must `mark <i> running` first; there is no `mark <i> pending`, so a failed step cannot be
returned to the queue by the obvious route. Corollary when *parking* a blocked step:
leave it pending and put the blocker in the preceding step's note — marking it failed for
visibility moves `Next:` past it and buries the very block you were advertising.

## Striking a pack's Affected-symbols entry with `~~` withdraws it from the walk — strike only what the pack no longer touches

_(was: "Striking a pack's Affected-symbols entry with `~~` does not remove it — only deletion
does" — the heading as filed on 2026-08-01. §C7 reversed the body on 2026-09-11 and the
heading followed on 2026-09-12, `DEF-779`, so a reader who trusts the title over the body
no longer deletes entries a strike would have withdrawn.)_

**What it is:** `espalier.pack_manifest.parse_affected_symbols` and `parse_affected_literals`
collect the `` - `path::symbol` `` bullets under a pack's `## Affected symbols` /
`## Affected literals` headings, and that is the set `espalier scope-check` walks to compute a
change's blast radius. Until 2026-09-11 neither parser interpreted Markdown: wrapping a bullet in
`~~strikethrough~~` changed how it *rendered* and nothing about how it *parsed* — the entry was
still collected, still walked, still reported. Since then (§C7) both parsers and the diagnostics
read a bullet with its struck spans removed, so a bullet struck whole is withdrawn from the walk
and a struck span inside a live bullet is ignored. The heading records what the footgun was; the
edge that remains is the one below.

**How you hit it (before the fix, and the instinct that survives it):** you strike a sub-task, and
because the pack file is also a record you keep its symbols in place with `~~` so a later reader
can see what was dropped. Before 2026-09-11 the pre-flight then walked symbols the pack no longer
touched: scope-check reported references into a subgraph nobody would edit, the operator read a
blast radius that overstated the change, and any stop condition keyed on the symbol count measured
a number the pack did not own — silently, and pointing the *wrong way*, because a pre-flight that
over-reports looks conscientious. Attested: five symbols and one literal were struck with `~~`;
all six still parsed, and the pack's symbol count only fell from 41 to 36 once the bullets were
deleted. That behaviour is gone, but the same instinct now cuts the other way: a struck bullet
disappears from the pre-flight entirely, so striking an entry the pack *still* touches — to mark
it done early, say — under-reports the blast radius as silently as the old behaviour over-reported
it.

**How to avoid it:** in these two sections strike only what the pack no longer touches, and keep
the record of *why* as prose above the list — a short note naming what was removed and where the
work went — which reads the same to a human and is invisible to the parser. A routed bullet that
names no backticked token at all (a path typed bare, a sentence where a declaration belongs) is
one the walk cannot see: `scope-check` prints it as a `!` line and the active-pack guard in
`tests/test_pack_manifest.py` reds on it; declare nothing on purpose with `- (none — ...)` or
`- None.`. Then verify mechanically rather than visually: parse the pack and confirm the count.
The general rule this is an instance of: **when a section is consumed by a parser, its formatting
carries no meaning, so "marked as removed" and "removed" are different states.** Any convention
that relies on a reader seeing a visual cue is unenforced.

## A stdlib function is not a stable test oracle

**What it is:** asserting that your implementation equals a standard-library call looks like
the strongest possible test — you are checking against the reference. What it actually pins is
**their changelog**. When the stdlib's behaviour changes in a release, your assertion changes
meaning with it, and the test now encodes *which interpreter ran it* rather than the contract
you meant to fix. It passes on the version you develop on and fails on the ones you support.

**Attested:** four tests asserted `safe_glob(root, pat) == root.glob(pat)`. Python 3.13 changed
a bare trailing `**` from matching directories only to matching files **and** directories. The
implementation was deliberately files+dirs on every supported version — it was correct
throughout and was never edited — but the oracle moved underneath it, so the suite was green on
3.13+ and red on 3.10–3.12. A local run on 3.14 passed for weeks while every older interpreter
in CI failed. The divergence was also **narrower than the symptom suggested**: only the
bare-trailing forms drifted, because a `**` followed by a filter behaves identically across the
boundary — so three quarters of the patterns in those loops were never version-coupled at all.

**How to avoid it:** assert the **explicit expected set**, enumerated in the test. It is longer
and it is the point: it states the contract instead of delegating it. Keep the non-drifting
cases rather than trimming to the one that broke — they are the regression coverage that proves
the fix was surgical. **The tell is a test named `*_matches_<stdlib>` or `*_like_<stdlib>`,** and
the deeper tell is any assertion whose right-hand side is a call you do not own. Kin to the
measuring-instrument family above: there the probe was wrong; here the probe is correct and
*mutable*, which is worse, because nothing about it ever looked broken.

## Every new tree-walking scanner re-implements the walk contract, and nothing enforces it

**What it is:** The engine's canonical walker is `espalier/_safe_walk.safe_rglob`, but
`espalier/scanners/` is stdlib-only and cannot import from `espalier/` — so each scanner that
walks a tree carries its own INLINE `_safe_rglob`. The duplication is by necessity, not
sloppiness. The consequence is that the walk contract lives in N copies with **no shared
enforcement point**: a new scanner satisfies it only because its author knew to.

**How you hit it:** Adding a tree-walking scanner and copying the nearest sibling's walker
without knowing which parts of it are load-bearing. There are **three** obligations, and each
was added by a different fix, so no single sibling is guaranteed to show you all of them:

- `os.walk(followlinks=False)` — a bare `rglob` / recursive `glob` follows directory symlinks
  below CPython 3.13 and raises `OSError(ELOOP)` on an adopter tree with a symlink loop.
- the inline `_skip_nested_repos` prune — an embedded repo otherwise gets walked as if it were
  the adopter's own source.
- a per-file `except OSError` read guard — one unreadable file (dangling symlink, permission,
  a path that vanished mid-walk) must not abort the whole scan.

Miss the first and you crash on someone else's tree; miss the second and you report findings
that are not theirs; miss the third and the scan aborts on a single bad file.

**How to avoid it:**

- Copy the walker from a scanner that has all three, then diff it against
  `espalier/_safe_walk.safe_rglob` — do not hand-write it.
- If your scanner returns a report dict, collect the unreadable files under a `"skipped"` key
  **and** make sure the CLI surfaces them. A shrunk scan that reports no casualties is
  indistinguishable from a clean one. `godfiles` is the deliberate exception: it carries the
  guard and reports no key, because a size report omits an unreadable file by design.
- Note the spelling. The canonical function is **`safe_rglob`**; there is no `safe_walk`
  function anywhere in the tree — `_safe_walk` is the MODULE name, and citing a
  `safe_walk` *function* creates a phantom symbol that reads as real.

**Receipt:** the inline copies are drift-pinned to the canonical by
`tests/test_safe_walk.py::test_inline_safe_rglob_copies_match_canonical_oswalk_loop`, which
AST-compares each `_safe_rglob` body against `safe_rglob`'s `os.walk` loop. That pin covers the
first obligation structurally; the prune and the read guard are convention, which is precisely
why they are written down here. The recurrence guard for bare walks is
`espalier/scanners/filesystem_contracts.scan_recursive_walks`.

## A bash function that `return 0`s on its non-success branch silently green-washes the caller

**What it is:** a bash helper whose failure path falls through to `return 0` (or
whose last command happens to succeed), called bare — `do_thing "$arg"` — leaves
`$?` at 0. The caller's status bookkeeping then records success for a step that
did not happen. Nothing reds: the suite passes, the report row says PASS, and the
only witness is the missing side effect.

**How you hit it:** a driver script that both *does* work and *reports* on it —
the two roles share one exit status, and the reporting half trusts it. Espalier
hit this in `scripts/run_pack_chain.sh`'s `finalize_landing`: the pack-chain
driver reported packs as landed whose Landing stamp had never been written.

**Do:** call the helper, capture `$?` immediately into a named local, and branch
on the value — never let a bare call's exit status flow into a report:

```bash
  local fin_rc
  finalize_landing "$file" "$commit"; fin_rc=$?
  if [[ $fin_rc -eq 3 ]]; then ... fi
```

Capture on the *same line* as the call. Any command in between — even an `echo` —
overwrites `$?` and reintroduces the bug in a form that looks careful.

**Why it is a *sharp edge* and not a bug:** the fix is one line per call site, but
the class is invisible to every gate the repo owns — a green suite is exactly
what it produces. The instance is closed; the class is why this entry exists.

## A state-dir cleanup glob silently eats a longitudinal log

`session_start._clean_state_flags` unlinks two filename *prefixes* under
`.espalier-state/` at every non-continuation SessionStart:

```python
for flag_path in state_dir.glob("speedbump_*"): flag_path.unlink()
for flag_path in state_dir.glob("reinject_*"):  flag_path.unlink()
```

Three files in that directory are cross-session rolling history and must persist:
`session_length_baseline`, `born_weak_observations.jsonl`, and
`recall_events.jsonl`. They survive **only because their names miss both globs** —
a naming coincidence carrying a durable invariant.

**How you hit it:** you add a new rolling-history file and give it the *obvious*
name. Recall-engine telemetry wants to be called `reinject_events.jsonl`; that
name is erased every session. So does any later tidy-up rename toward a prefix
that reads as a sensible namespace.

**Why it is expensive:** the symptom is an **empty file**, which is
indistinguishable from an instrument that never fired. You debug the writer —
the one part that is working — because the failure presents as "telemetry isn't
working," not as "telemetry is being erased." Nothing raises, nothing logs.

**Do:** pin the invariant behaviorally, over the whole persistence family, not
just the file you happened to add (`tests/test_reinject.py::test_state_dir_rolling_history_survives_a_session_boundary`).
Write the file, call `_clean_state_flags`, assert it survives — and in the same
run write a control file that *does* match the glob and assert it was deleted,
so a green cannot come from cleanup having silently not run at all.

**Do NOT** assert against a transcribed copy of the flag list: the named list and
both globs are inline literals inside the function body, so there is nothing
importable to compare against, and a hand-copied list is its own drift defect.

**The general shape:** a cleanup keyed on a name *prefix* creates an unwritten
naming contract for every file that shares its directory. Prefix collision with
a cleanup glob is a data-loss bug that presents as a measurement bug.

**The substring form is worse, and the collateral is not yours.**
`merge-settings --repair` decided which settings entries were espalier's own
with a containment test, so an operator's `my_plan_guard.py` read as a copy of
`plan_guard.py` and the repair removed it while reporting the entry preserved
(`DEF-618`, both reviewers, driven). The same test had a second reader — the
classifier that files a gate as legacy-form — so one false positive became a
misfiling *and* a deletion. Key anything that removes on an exact basename
token (`harness_config.blob_names_script`, now the one predicate both readers
call), and when a loose name test has two readers, fix the predicate rather than
the caller.

## `grep` in a Claude Code session is gitignore-blind, and this repo keeps its landed packs and session state in gitignored directories

`grep` inside a Claude Code Bash call is not the POSIX binary. The shell snapshot
defines it as a function (`# Shadow find/grep with embedded bfs/ugrep`) that
dispatches to `ugrep -G --ignore-files …`. **`--ignore-files` honors `.gitignore`.**

Measured on this repo, 2026-08-10 at `172e8bb`:

```
grep -rl "DEF-" .                              →  40 files
command grep -rl "DEF-" . --exclude-dir=.git   → 279 files
```

Invisible to the shimmed form: `task-packs/Done/` and its siblings, `cc/`,
`reports/`, `dist/`, `.espalier/` — which is to say every landed task pack, all
session state, and every analysis output this project reasons from (the forward
ledger and the active packs were in that set too, until they started shipping on
2026-09-21).

**How you hit it:** you run a census. "How many members does this class have,"
"did the rename reach every sister site," "does this doc mention X anywhere."
Class-fix work is census work almost entirely, and the landed packs it counts
against are gitignored (the ledger itself was, until 2026-09-21).

**Why it is expensive:** the failure is an **absence**. `grep -rl "DEF-547" .`
returns one file; the real binary returns six, one of which is
`task-packs/FORWARD_LEDGER.md` — the file that defines the row. Exit code 0,
well-formed output, no warning. An absence-proof is precisely the claim this shim
manufactures falsely, and "X appears nowhere" is the shape of many ledger rows.

**Do:** use `command grep` for any recursive search, census, or absence-proof.
The blast radius is *recursive directory walks only* — an explicitly named
gitignored file reads identically under both forms, so `grep -c X path/to/file`
is safe and `grep -rn X .` is not.

**And `command grep` is not sufficient — the shim is one of at least three ways
this repo has manufactured a false absence.** Measured 2026-08-22, both in a
single session, both relayed to the operator as settled before being checked:

- **Case.** `command grep -rn "rehearsal" .` returned nothing relevant, and the
  target was `WINDOWS_REHEARSAL_BRIEFING.md`. The search used the *operator's*
  vocabulary for a thing the repo names differently ("walk"), so even `-i` would
  have needed the right stem. Two independent reasons to miss, one report of
  "not found."
- **zsh globbing.** `command grep -rn "X" --include=*.md .` does not run — zsh
  expands `*.md` before grep sees it and errors `no matches found`. The failure
  is visible, but in a compound command its output scrolls past and the *next*
  grep's empty result reads as the answer.

**The rule that covers all three: before reporting a null, run the instrument
against a case you KNOW exists.** One extra invocation. In the measured case a
probe against a known-present path would have shown the search working and the
*vocabulary* wrong, which is the finding. An absence-proof whose instrument was
never positively controlled is not evidence — it is an untested tool reporting
its own silence. Cf. `STANDING_PRINCIPLES` §4 (verify tool output through an
independent oracle), of which this is the absence-shaped case.

**Do NOT** assume the sibling tools share the defect; they were checked and do
not. `find` is shimmed too, to `bfs`, but **without** `--ignore-files` — it sees
`task-packs/` fine. Repo Python never invokes `grep` as a subprocess (the one
hit is a string in a scanner allowlist), and `/bin/sh` resolves the real binary,
so **no shipped code path is affected**. This is a measurement hazard for
sessions, not a defect in the harness — it adds no member to any `§C` class.

**The general shape:** a tool *name* can resolve to an implementation with
different corpus semantics than the caller assumes. That is the sibling of
`FAILURE_MODES` §17.1 (a git query answering about the *enclosing* repository):
§17.1 is about **where** a tool looked, this is about **what the tool was**. Both
produce an exit-0, well-formed, silently wrong answer about a corpus you did not
name, which is the hardest shape to notice. When a search underpins a count, ask
not only "did it succeed" but "did it search the thing I named".


## The ledger verbs are unlocked read-modify-writes — never run two in parallel tool calls

**What it is:** `scripts/ledger_row.py file`, `strike` and `repin` each read
`task-packs/FORWARD_LEDGER.md` and `task-packs/LEDGER_PROBES.json`, rewrite the
row and the probe list in memory, and write both back (`_commit_both`) with no
lock and no re-read. Two verbs whose windows overlap leave the second writer's
view of the files as the only view: the first verb's row, probe entry and
`_count` vanish, and the loser still prints `regions converged`.

**How you hit it:** issuing a `file` and a `strike` (or two `file`s) as
parallel tool calls in one message, the way independent reads are batched. On
2026-09-09 two `file` verbs and the nested-repo-litter row's `strike` ran that
way and all three survived — ordering luck, verified afterwards by grepping
each id in both files and re-deriving the probe count (`_count` 223 = rows).
Nothing in the verbs would have said otherwise.

**How to avoid it:** sequence ledger verbs in one shell script, or one per
turn, and verify after any batch: `command grep -c '<id>'
task-packs/FORWARD_LEDGER.md` per id, then `python3
scripts/check_ledger_probes.py`, which refuses to report on a probe file whose
`_count` disagrees with its rows — that refusal is the only mechanical trace a
lost write leaves, and only when the loss changed the count — and when it fires,
the whole report goes dark until `--reconcile-count` re-derives the field
(`docs/FAILURE_MODES.md` §3.10, the reporter's wholesale refusal).

**And the working tree is a weak witness.** Until 2026-09-21 `task-packs/*` was
excluded with only the router re-included, so a filing never dirtied the tree at all;
the ledger and its probes file are tracked now, so `git diff` shows that *something*
changed, not that *your* row landed — a concurrent writer's row dirties the same file,
and a refused verb leaves it clean either way. Read the two files by id, never the tree.
And `strike` prepends the `CLOSED <date> —` prefix itself: a closing text that opens
with it lands doubled (2026-09-21, corrected by hand — a struck row carries no hash,
so the hand edit stales nothing; the dry run shows the doubled head if you read it).

## A New Guard Is Blind The Way It Claims To See

The artifact built to catch defect-class X is itself an instance of X: its
population or its predicate structurally excludes its own subject, so it ships
green and can never fire on the thing it names. Before moving on from any new
guard, test, gate, scanner, check or pin, ask **"what mutation leaves this green
while the defect it names is live?"** and drive it.

This is the spine the repo's many single-face entries hang off, and it recurs
*because the defect form is the shorter form* — writing the fix is the same
authoring task that produced the defect, so being primed on the class does not
change which road is cheap. Measured here: not caught at authoring time; caught
by an adversarial pass after the fix is green.

See [sharp-edges/a-new-guard-is-blind-the-way-it-claims-to-see.md](sharp-edges/a-new-guard-is-blind-the-way-it-claims-to-see.md)
for the strict test, the five avoidances, and pointers to every known face.

## A default that nothing calls is not a default

A module-level constant naming the conventional destination for a subsystem's
output read as *configuration* for the entire life of that subsystem, while
every single caller overrode it. The value was correct. The name was correct.
Nothing wrote it.

**The tell is mechanical and cheap:** grep the constant's name across production
code and count the callers that are not tests.

```bash
command grep -rn "DEFAULT_CORPUS_PATH" --include='*.py' espalier/ tools/ scripts/ \
  | command grep -v '^tests/' | command grep -v 'fan_out_findings.py'
```

Zero non-test callers means the constant is a *naming of intent*, not an
implementation of it. Reviewing the constant will never reveal this, because the
constant is fine — the defect lives in the gap between it and its callers, which
is exactly the place a per-file review does not look.

_The constant in that recipe, `DEFAULT_CORPUS_PATH`, retired on 2026-09-21 together
with the shared corpus it named, so the grep now prints nothing for a different
reason; substitute the name of whichever default you suspect. The lesson stands._

**Why it bites harder than an ordinary unused value.** A dead constant is
harmless. A dead *default* is actively misleading: it documents a wiring that
does not exist, so a reader tracing the dataflow concludes the hop is covered and
stops looking. Downstream, the symptom presents as something else entirely — here,
a cross-round dedup corpus that kept missing the previous round's entries, so each
round re-found them and reported them as new. That reads as productivity, which is
the most expensive way for a gap to present.

**Do:** when a subsystem has a "shared" or "canonical" destination, assert the
wiring rather than the constant — a test that the production path actually
resolves to it. A default is a claim about behaviour, and like any claim it is
unproven until something drives it.

**The general shape:** *correct-but-unreferenced* is invisible to every review
lens aimed at correctness. Ask of any default: not "is this value right?" but
"what happens if I delete it?" If the answer is "nothing", it was never wiring.

## Windows PowerShell `Set-Content` can report success and persist nothing on a same-file rewrite

**What it is:** on the Windows walk host, `(Get-Content $p -Raw).Replace(...) | Set-Content $p -NoNewline`
restored `.claude/settings.json` with no error and no change. The same command shape had
worked minutes earlier in another window. Diagnosed on the host: `Contains(...)` was True and
`Replace` changed the text, so the match was never the issue; `[IO.File]::WriteAllText` with a
full path then wrote it immediately. The mechanism is **UNRESOLVED** — a lingering
`Get-Content` handle and a `claude` or hook process holding the file are the candidates, and
neither raised — so this entry records the behaviour and the workaround, not a cause.
Attested: walk 3, 2026-09-14, row W3-P14.

**How you hit it:** editing a settings file from a PowerShell session while a Claude Code
session that reads it is open, then reading the next leg's green as proof of the edit. A
settings edit that reports success and does nothing makes every downstream leg green for the
wrong reason.

**Not a harness defect:** espalier's own writes go through the atomic temp-and-rename path and
never rewrite a file in place.

**How to avoid it:** on Windows, write settings through the .NET file API with an absolute
path, and read the file back before judging the leg — the edit is a claim until the bytes say so.

## `[IO.File]::*` resolves a relative path against the process directory, which PowerShell's `cd` does not move

**What it is:** the .NET file statics (`[IO.File]::ReadAllText`, `WriteAllText`, `Exists`)
resolve a relative path against the process working directory,
`[Environment]::CurrentDirectory`. `Set-Location` and `cd` change PowerShell's location, not
that directory. So `[IO.File]::ReadAllText(".\tools\cc\statusline.cmd")` after a `cd` into
the scratch repo read from the user's home directory instead, threw, and the leg's result line
still printed a plausible pass, because its precondition check was the thing that failed.
Attested: walk 3, 2026-09-14, row W3-P18, first in leg 1-G and again in leg 5-H of the same
walk — a hazard recorded only in a walk note did not reach the next leg of that walk, which is
why it is here.

**How you hit it:** any precondition or oracle spelled through `[IO.File]::` with a relative
path, inside a block that `cd`s first. The oracle measures the wrong directory and reports
confidently.

**How to avoid it:** every `[IO.File]::` call carries a full path, built from
`(Get-Location).Path` or `$PWD`, never a bare `.\`. Note the interaction with the entry above:
the .NET API is the right tool for a settings write on Windows, but only with an absolute path.

## pwsh's alias table is per platform: `rm`, `ls` and `find` are the native binaries on macOS and Linux

**What it is:** PowerShell 6+ removed the `rm`, `ls`, `cp`, `mv`, `rmdir`, `cat` and
friends aliases on non-Windows hosts so the native tools run; `ri`, `del`, `rd`, `gci`,
`dir` and `gi` stay aliases everywhere, and on Windows `rm` is still `Remove-Item`. So a
premise written from the Windows table -- "`rm` is aliased to Remove-Item, the bash spelling
does not execute there" -- is false on the two hosts the self-host box and CI run, and a
guard reasoned from it leaves `rm -rf ~` and `find . -delete` unread on the PowerShell tool
while `/bin/rm` and `/usr/bin/find` run them. Attested 2026-09-16: the DEF-824 row carried
that sentence; `Get-Command rm,find` under pwsh 7.6.5 on macOS answered `/bin/rm` and
`/usr/bin/find`, and a throwaway went.

**How you hit it:** any claim about what a bash-spelled verb does on the PowerShell tool
that was not driven on the platform in question. The Windows walk cannot vouch for the
POSIX table and the POSIX box cannot vouch for the Windows one; two more of the same
family from the same day: a bare `{}` behind `find -exec` is a script block to pwsh, so
`find . -exec rm -rf {} +` is inert as typed and only `'{}'` runs; an enumerator
pipeline (`gci ./v -Recurse | ri -r -fo`) removes a root's CHILDREN and leaves the root,
so an oracle that checks the root directory is gone reads every such wipe as not reaching;
a recursive enumeration into a plain remove (`gci -Recurse | ri -fo`) aborts on the
non-interactive prompt at the first directory with children, and everything enumerated
before it is already gone (a tree of empty directories goes whole); and PowerShell
continues a pipeline across a line break after the pipe, so a separator class that stops
at a blank reads the two-line spelling as two unrelated statements.

**How to avoid it:** drive the spelling on the real interpreter for THAT platform before
asserting what it resolves to (`Get-Command <verb>` names the resolution; a throwaway names
the effect), list a differential row only for the platforms it reaches on, and give a
pipeline row an oracle that reads what it actually removes. The guard reads the bash
spellings on the PowerShell tool on every platform, toward refusal: over-denying a command
that errors on Windows costs nothing, under-reading one that runs on POSIX costs a tree.

## A pasted block answers `init`'s `[y/N]` prompt with its next line, and the leg proceeds unwired

**What it is:** `espalier init .` on a tree whose `.claude/settings.json` exists but carries
no Espalier hooks — the state `clean-generated` leaves, since it preserves the file and strips
the hooks — asks `Wire them now? [y/N]` when both stdin and stderr are terminals. The prompt
is on stderr, so `| Out-Null` does not hide it, and the default is No. In a pasted multi-line
block the terminal feeds the NEXT LINE to that prompt: a stray command almost certainly
declines, and the leg continues with the hooks unwired while every later line runs normally.
Attested: walk 3, 2026-09-14, row W3-P15; legs 2-C, 5-D and 5-F all re-initialised a repo
that an uninstall had left in exactly that state.

**How you hit it:** re-running `init` after `clean-generated` inside a pasted block, or any
`init` on a preserved settings file that is not on its own line. Nothing fails; enforcement is
simply off.

**How to avoid it:** spell the intent — `espalier init . --wire-hooks` never prompts — and give
an `init` its own paste. The procedural hazard is the paste, not the prompt: off a terminal
the prompt is skipped and the file is preserved with a warning, which is the correct default.

## A default local `git clone` hardlinks the source's objects, so a leg that clears the read-only bit strips the live repo

**What it is:** `git clone <path>` of a repository on the same filesystem hardlinks the objects
and pack files instead of copying them (measured: shared inode, link count 3, 6,434 read-only
files). A leg that clears the read-only attribute on the clone — `remove_tree`'s job — clears it
on the SAME inodes in the live repository, and a re-run of the earlier leg then finds a writable
pack and banks a false "premise refuted" against a real defect. The obvious fix is the wrong
one: `--no-hardlinks` copies the objects at mode 0666, so the pack is writable from the start
and the read-only premise vanishes silently. Attested: walk 3, 2026-09-14, row W3-P19.

**How you hit it:** any fixture that clones the repo under test locally and then exercises a
permission- or attribute-clearing path, on either platform. The fixture shares bytes with the
thing under test, and the second run measures the first run's damage.

**How to avoid it:** clone with `--no-local`. It forces the regular transport, `index-pack`
writes the received pack read-only on its own inode, and the clone is a real copy that still
carries the premise (measured: own inode, link count 1, the pack and index read-only). Check
the clone's inode against the source's before trusting a red or a green from it.
