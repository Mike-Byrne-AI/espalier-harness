# Task pack authoring

**Status:** active
**Linked from:** task-packs/CLAUDE.md ("Read first")

Accumulates load-bearing experience from authoring blueprint task
packs in this repo.

**See also:** [`git-artifact-hygiene.md`](git-artifact-hygiene.md) for
the `mv` vs `git mv` rule when archiving completed packs to `Done/` —
since 2026-09-21 the active pack is tracked and `Done/` is not, so `git mv` no longer
exits 128 -- it force-tracks the landed pack inside the ignored folder (the
tracked-noise gate reds). Land it as `git rm --cached -- "task-packs/TP-N-*.md"`, then
`mv`, with the deletion in the pack's commit.

## Pre-flight discipline (TP-62 pack-artifact review)

Every pack runs four pre-flight gates before any sub-task executes:

- **0-A — Pack-artifact review** (TP-62). Dispatch the `code-reviewer`
  agent with the pack body + the fixed checklist at
  `tools/cc/pack_artifact_checklist.md` (v2, 9 items). Severity labels
  are BLOCK / WARN / NIT / PASS; any BLOCK blocks execution, WARN/NIT
  are advisory (fold in and proceed).
- **0-B — Scope-check** (TP-38). `espalier scope-check <pack-path>`
  walks references for every symbol the pack declares to change.
  Exit 0 = clean; exit 1 = nothing parsed (no section declared, or a
  declared one that parsed to zero entries -- the cause is printed); exit 2 =
  scope gap (acknowledge with `--accept-scope-gap "<reason>"` or
  widen `Scope (in)`).
- **0-C — Compression probe.** `python tools/cc/sister_site_probe.py
  --json` flags canon-misses + 3+ identical cliques. Exit 2 =
  compression debt (`--accept-compression-debt "<reason>"`); DIVERGENT
  cliques are advisory. Ambient pre-existing dup is routinely accepted.
  The `scope` block names whose code was scanned: an adopter tree gates
  on its own source roots, with the deployed hooks' debt advisory.
- **0-D — Surface-impact.** `espalier surface-impact <pack-path>` reads
  the pack's `### Added-paths` (+ a new CLI verb) and prints the
  shipped-surface obligations each addition implies (count pins,
  mirrors, hygiene, provenance) before the build. Exit 2 = a public
  addition (`--accept-surface-gap "<reason>"`). Scopes to ADDED paths
  only — a CHANGED edit to an existing shipped file is out of scope;
  the full suite stays the gate for that class. [[class-fix-scope-all-shipped-surfaces]]

## What v1 reviews consistently miss (and v2 catches)

The reauthor → re-review cycle has been the v0.7.3 sprint's most
load-bearing pattern. v1 catches the obvious things; v2 catches
stragglers v1 left in places v1's grep didn't look:

- **TP-88 v2**: 4 blockers found by v1 (fake helper `_asset_path`;
  non-existent `--- SHARP_EDGES TOC` marker; wrong fixture line
  range `~410-450` vs actual 549; ESPALIER_MEMORY.md autoprune math collision)
  → all 4 patched → v2 reviewed → 0 new blockers. Clean convergence.
- **TP-89 v2**: 4 issues found by v1 (wrong test-class
  `TestScannerImports` vs actual `TestScannersStdlibOnly`; optimistic
  autoprune math; `task-packs/` gitignore blocker; unautomatable
  smoke) → all 4 patched → v2 reviewed → 1 MAJOR remaining (stale
  class name in the Motivation table that v1 patched only in the
  router body, not the table) → fixed → re-verified.

Lesson: when patching a finding, grep the WHOLE pack body for the
stale token. v1 fixes are surgical; v2 catches what surgery missed.

## Common pre-flight findings (TP-87..TP-91 baseline)

- **Line-number drift**: cited `tests/X.py:N` doesn't match HEAD.
  Always verify with `grep -n` against the live file before trusting
  the pack.
- **Scout fix-plan: observation sound, mechanism unverified**: when a
  re-verification scout (or fan-out) hands you a fix-plan, its *observation*
  (the bug exists, the earn-the-red reproduces) is trustworthy — but its
  *mechanism* ("the bug is at line X") and *completeness* (sister-sites, import
  cycles) are claims to re-derive before editing. Run the proposed earn-the-red
  and confirm WHICH branch fires it; re-grep for sisters/cycles yourself.
  TP-174b: a scout's T16 red fired at a different branch than its fix targeted,
  and it called a `pre_release`→`release_pack` import "safe" when the cycle
  already existed. See FAILURE_MODES §11.10.
- **Fake symbol names**: pack cites a helper that doesn't exist. The
  TP-62 checklist now requires symbol-name accuracy as item #2.
- **Missing `## Affected symbols` section**: post-TP-38 packs must
  have this section for scope-check to walk references.
- **Effort over-estimates**: pre-written content blocks are copy-paste
  operations (~2-5m each), not authoring time. Recalibrate before
  execution.
- **Adopter-fit drift**: asset bodies narrate as harness-internal — the path
  tokens appear OUTSIDE opt-in code-fence examples. This applies to the *whole*
  asset surface, not a subset: the deploy tier split was retired by TP-212
  (see [[asset-mirroring]]), so every asset now ships to every adopter. The
  mechanizable **negative** axis already ships in two contracts —
  `tests/test_init_tier_split.py::TestCommonTierAssetHygiene` forbids
  harness-only tool references and leaked pack identifiers, and
  `tests/test_common_tier_asset_availability.py` pins that every path an asset
  body references actually exists on an adopter's filesystem after
  `espalier init`. The **positive** assertion — that a body *reads* as
  adopter-fit — needs a human or LLM judge, so it is **struck, not queued**
  (FORWARD_LEDGER §6 `CLO-24`). Pass criterion (b) stays a manual grep.

## Denylist self-reference paradox (TP-92)

A denylist contract test must include itself in the exclusion list.

The one exception (DEF-708, 2026-09-21): the gate's gitignored local pattern
file is deliberately *not* self-excluded — it never reaches the walk
(gitignored, walker-pruned), and a force-added copy should red on its own
lines; `test_is_excluded` pins it. See [[local-codename-arm]].

The class: a test that walks tracked files looking for a forbidden
token cannot avoid containing the token — the codename appears in the
docstring describing what the test forbids, and in the
`FORBIDDEN_PATTERNS` constant defining the search. The moment the test
file is tracked, it fails against itself.

Invisible during 0-A pack-artifact review because the new test file
isn't tracked yet at review time; the `git ls-files` walk that drives
the assertion doesn't include the not-yet-committed file. The failure
only manifests post-commit when the now-tracked file enters the walk.

Pre-flight signal for future packs: when a sub-task adds a new test
that defines a denylist (substring scan, regex match, forbidden-import
check), confirm the test file path appears in its own exclusion list,
with a docstring sentence naming the structural reason.

Sister-shape: `tools/cc/hooks/_bash_patterns.py` contains the regexes
it pins; `docs/SHARP_EDGES.md` contains bypass-class descriptions.
Distinct from the tautological-test class (TP-12/16/24/74) where the
same function appears on both sides of an assertion — that one is
tripped by circular validation; this one is tripped by adding-the-file
itself. Both require the same answer: independent ground truth that
isn't the artifact under test.

## Cross-cutting blocker discovery: 4-agent pre-cut deep-dive

Per-pack reviews (0-A code-reviewer) catch line-number / symbol-name
errors. Cross-cutting blockers — where ONE class of edit applies
across multiple packs and a single pack's review can't see the
pattern — need a DIFFERENT review shape.

The 4-agent pre-cut deep-dive
(`code-reviewer + failure-mode-reviewer + architecture-analyst +
harness-config-advisor` in parallel) is the canonical shape. v0.7.3
example: TP-90 was authored AFTER the 4-agent review caught a
release-blocker no per-pack review could surface — the wheel
`pyproject.toml` package-data omission for the new `assets/memory/`
and `assets/docs/sharp-edges/` paths added by TP-88. Built wheel had
0 paths for either; adopter `pip install` would have failed at
cli.py's `as_file(source_node)` load with `FileNotFoundError`.

The failure-mode-reviewer agent's supply-chain-class instinct is the
most likely to surface this kind of gap.

## Scope-check parser limits (TP-38)

`espalier scope-check` parses two markdown shapes:

- Top-level `- ` bullets at the start of a line.
- `### h3` subheadings under `## Affected symbols` (the labels
  `Removed paths`, `Renamed symbols`, `Changed semantics`,
  `Added paths/symbols` — alias `Added` also accepted).

Nested bullets, prose-only sections, and other structures are NOT
parsed. Pack bodies that use these for narration are fine, but they
won't contribute to the scope reference graph.

**TP-174b:** the `## Affected symbols` header parser was fixed to tolerate a
NUMBERED heading (`## 5. Affected symbols`). It had silently matched ZERO symbols
on every numbered pack because only the sister `Scope (in)` parser got the
TP-151 F-2 numbered-heading widening (FAILURE_MODES §1.12 silent-no-op variant) —
scope-check exited "no Affected symbols section", which reads as authoring
guidance, not a tool bug. Also: §5 entries that are **file paths** (not symbol
names) make scope-check grep each path and report every doc / command-body
*mention* of it as an out-of-scope "gap" → exit 2 even with no real
code-dependency gap. That gap is benign noise; `--accept-scope-gap "<reason>"` is
the escape hatch. Prefer declaring actual symbols (functions/classes) over bare
file paths where the distinction matters.

## Single-atomic-commit-per-pack

The release workflow is "one pack = one commit." Stage only what the
pack touched (plus integrity manifest refresh if hooks edited).
Commit message shape:

- Subject: `<type-scope>: TP-NN — <one-line>`
- Body: multi-paragraph; explain WHAT changed, WHY, files touched,
  verification numbers, deferrals (scope-out with rationale), sprint
  coordination notes.
- Footer (self-host convention): `Co-Authored-By: Claude, Scion <claude@espalier.dev>`
  (drop the harness default's `(1M context)` + `noreply@anthropic.com`; the
  shipped skill bodies keep the adopter-neutral `noreply` default).

  **Exactly one backticked `Co-Authored-By:` line may appear in this file** --
  `scripts/check_handoff_landing.py` parses it as the canon rather than
  restating it, and refuses to enforce anything if it finds zero or several.

  The name carries no model version ON PURPOSE. The previous canon read
  `Claude Opus 4.8` and rotted the moment the model changed: a census on
  2026-09-01 found **four** spellings across 150 commits -- 119 of the harness
  default this line tells you to drop, 17 of an updated-model variant, 8 of
  `Claude, Scion`, 1 of the literal text above -- plus one commit carrying no
  trailer at all. A version baked into an identity is guaranteed to go stale in
  a record that cannot be edited. *Scion* is the grafted shoot that fruits on
  rootstock it did not grow from, which is what an espalier trains against a
  frame; it needs no version and cannot rot.

## Gitignore + task-packs/ gotcha (TP-89)

`task-packs/` is ignored by the CONTENT form `task-packs/*` so that named files
can be re-included: a directory-form `task-packs/` would forbid every later `!`,
because git never re-includes a file inside an excluded directory. TP-89 needed
only the folder router re-included; since 2026-09-21 the same shape re-includes
the forward ledger, its probes file, the active packs and, as a directory first,
`Deferred/` with its packs (an allow-list: a file nobody named stays ignored).
Verify with `git check-ignore -v <path>`; `Done/`, `Merged/`, `Scrapped/` and the
dated archive files must still print the `task-packs/*` rule.

## Pack-author hygiene

- TP-N pack files in active `task-packs/` root are work-in-flight.
- Landed packs move to `task-packs/Done/`.
- Abandoned packs move to `task-packs/Scrapped/`.
- Deferred packs move to `task-packs/Deferred/` — parked, NOT terminal, so no
  Landing stamp is owed.
- Superseded sources move to `task-packs/Merged/` — terminal, but preserved
  **unedited** as the provenance record (`Merged/README.md`), so a stamp must
  NOT be required there. "Terminal" and "stampable" are different questions and
  this folder is why: a fix that derived the terminal set from the filesystem
  would sweep it in and demand edits an invariant forbids.
- ⚠ All four folders are named here on purpose. This list read `Done/` +
  `Scrapped/` only while four existed on disk, and `scripts/check_pack_landing.py`
  scanned `Done/` alone — so a canon that was 50% short could not have corrected
  it (`DEF-624`, 2026-09-01). The script now classifies every folder and reds on
  one it does not recognise, which is the guard that lets a hand-written list
  stay hand-written.
- Since 2026-09-21 the ledger, its probes file, the router and the packs at the root
  and under `Deferred/` are tracked and ship; `Done/`, `Merged/`, `Scrapped/` and the
  dated archive files stay local-only (gitignored, carried on the record branch).

## See also

- `bench/corpus/` — class-of-bug catalog; pack-introduced regressions
  often map to existing BC-NNN classes.
- `docs/PACK_AUTHORING.md` — TP-38 + post-TP-62 canonical pack shape.
- `docs/CONVENTIONS.md` "Categorized memory + sharp-edges" — the
  hot/cool index/folder split this file participates in.

## TP-153/154/155 seed-pack review (2026-05-31) — verdicts + git-oracle pre-read discipline

Multi-agent adversarial review (19 agents, 4 lenses/pack + adversarial verification) of the three TP-151-retro seed packs.

**Verdicts:**
- **TP-154** (env-prefix guard quoted-arg over-match) → **REWORK**. Problem confirmed-real, but the pack named the wrong file: `_HARNESS_ENV_PREFIX_RE` lives in `tools/cc/hooks/write_guard.py::_HARNESS_ENV_PREFIX_RE`, NOT `_bash_patterns.py` (which has zero env tokens). It also reasoned from a command-position regex anchor that does not exist in live code, and its preferred quote-blanker fix re-opens a command-substitution bypass — `echo "$(ESPALIER_STOP_GATE=full evil)"` flips DENY→ALLOW. The deny-floor tests are `tests/test_hooks.py::TestWriteGuardBashPatterns`, not `tests/test_write_guard.py`.
- **TP-155** (untrusted-oracle protocol doc + CLAUDE.md Core Rule 8) → **SHIP-AFTER-FIXES**. Real uncodified discipline; honest instruction-layer. Must fix: a fabricated `ALLOWED_STATUS` citation (no such constant/set-check exists in `tests/test_categorized_memory_layout.py`), an inverted plan-gating claim (CLAUDE.md IS in `PLAN_REQUIRED_ROOT_FILES` in `plan_guard.py`, so 155-B runs under a plan, not maintenance mode), harden the red/green asymmetry to "a red is presumed REAL — never DISMISS, only RE-DERIVE", and caveat that a `/tmp` round-trip is a different rendering path, not an independent oracle.
- **TP-153** (flaky-oracle stop-condition escape hatch) → **CUT** (see pack header for full rationale). Lesson folded into TP-155 doctrine + a SHARP_EDGES one-liner; the mechanical `confirm_test_failure.py` form is deferred.

**Durable lesson — git-oracle pre-read before executing any pack drafted under a degraded tool channel.** The phantom tool-I/O channel (a Claude Code *runtime* defect: intermittent void/empty Bash/Read frames) was reproduced in-vivo during BOTH the originating TP-151 retro AND this review session. Packs drafted under it can encode fabricated facts — TP-154 cited a nonexistent regex anchor and the wrong file; TP-155 cited a nonexistent constant (ironic for a pack about not trusting fabricated reads). **Mitigation:** before executing ANY pack (especially one drafted under a flaky channel), re-verify every byte-exact claim — file paths, line refs, regex bodies, symbol names — via `git show HEAD:<path>` as a gating pre-step; never transcribe from a single interactive Read; triangulate across independent commands. This is the same independent-witness instinct the harness already embodies (dual-witness denylist, byte-equality, AST-over-substring), applied to the tool channel itself.

## "Independently landable" ≠ "order-free" — reconcile shared containers on second-land (2026-07-24 backlog runbook)

A pack backlog with **no hard `Depends on:` lines** is still not order-free. A mechanical **symbol-overlap** check (comparing identical symbol strings across packs' `## Affected symbols`) false-cleans the couplings that actually cause silent work-loss, because those couplings never share a symbol *string*:

- **rename-vs-caller** — pack A renames a symbol; pack B still calls the old name (e.g. `_project_root` → `_resolve_project_root`).
- **shared-list append** — two packs append to the same list (`session_start.py::_run_main`'s `_boot_warnings`; `conftest.py`'s `_MARKER_RULES`).
- **same-function multi-branch edits** — two packs edit different arms of one function (`cli.py::cmd_upgrade`'s dry-run vs execute arms).
- **tightened-gate-vs-new-surface** — pack A flips a probe to blocking (ceiling 0); pack B adds new surface *under* that probe.

A **file-overlap map + a source-reading judge** catches all four; the symbol map missed every one (07-24 runbook `wf_28216ecc`: 1 MUST-order + 5 shared-container pairs found, 0 by the symbol map). Discipline: for any shared-container pair, **reconcile-on-second-land** — re-read the shared file at HEAD and integrate; never author pack N+1 against a base that predates pack N's landed edit. Rebase-blind authoring is exactly what unattended / maintenance-mode runs skip. This is a **class, not an instance**: TP-131's "no file-overlap with TP-130/132/133/134" claim was itself false (a reframe-sentence collision the mechanical check couldn't see), two waves before the 07-24 finding.

**The data-loss face — a wholesale-REPLACE pack drops concurrent APPENDs.** A pack that REPLACES a gitignored tracked-state file wholesale from a pre-staged snapshot (TP-349's `FORWARD_LEDGER.md` reflatten) silently drops every APPEND that landed after the snapshot was cut — and there is **no git undo** because `task-packs/` is gitignored+local. Such a pack must (1) land STRICTLY LAST, (2) re-derive from the LIVE file, not the snapshot, (3) carry a mandatory concurrency-reconciliation step + a presence-grep pass criterion. Both faces trace to the same root: "independently landable" describes each pack as a valid standalone commit, not the order in which they may safely land.

**Authoring corollary — number collisions are routine; key deps on FILENAME.** Two `TP-337`s and two `TP-328`s have both existed. The driver halts mechanically on an ambiguous token (`docs/AUTONOMOUS_EXECUTION.md` "Ambiguous-token halt") and `task-packs/CLAUDE.md` pins the `TP-<n>-<slug>` filename format — but that mechanical guard fires only at driver *dispatch*. At *authoring* time it is on you: when a pack's prose cites "TP-316" as a dependency it may resolve to two files, so write every dep/chain reference by filename.

## Roadmap / author-and-stop packs must never enter the unattended chain

A `Kind: ROADMAP` pack (author-and-stop; its deliverable is the analysis, not an execution) is **trivially green** if chained — there is nothing to execute, so the receipt gate passes vacuously — AND it carries an **over-execution hazard**: a roadmap pack can contain third-party security-disclosure actions or external filings an autonomous session could fire. The remaining actions on such packs are operator-gated deliverables, not chainable work. The chain must never ingest them. [[make-a-pack-means-author-then-stop]]

## An earn-red / pass-criterion is a CLAIM — run it at HEAD before you trust it (2026-07-26 active-set review)

The active-set review of 11 packs found the dominant REWORK cause was **broken verification scaffolding, not broken fixes** — earn-reds and pass-criteria that can never go green even after a correct fix. Two mechanical footguns recurred across independent packs:

- **`git grep -E` is POSIX ERE — it does NOT honor `\s`, `\w`, `\d`.** A pass-criterion like `git grep -nE '\{[^}]+\}\s+\w+\(s\)'` returns **empty at HEAD regardless of file content**, so it is vacuously satisfied and verifies nothing — a born-green / fail-open gate. Bit two packs in one review (TP-368, TP-369). Use `git grep -nP` (PCRE) whenever the pattern needs `\s`/`\w`, and re-run it at HEAD to confirm it actually earns red first.
- **`espalier`'s `main()` does not take argv.** It reads `sys.argv` (zero positional params), so `cli.main(["x"])` raises **`TypeError`, never `SystemExit`** — an earn-red wrapping that call in `pytest.raises(SystemExit)` errors instead of asserting and stays red even after the correct fix (bit TP-365). Drive argparse via `build_parser().parse_args([...])` (the repo idiom).

The moat: **run every prescribed earn-red at HEAD and confirm WHICH branch/error fires before authoring the fix.** A pass-criterion grep that returns empty at HEAD is a fail-open gate, not a pass — the same born-weak class as a lock-test narrower than its class. Extends "a pack's prescribed fix code is a claim" from the fix to its *proof*. [[a-packs-prescribed-fix-code-is-a-claim]] [[measure-efficacy-not-just-correctness]]


## A pack is a working doc, not a record — file findings in a TRACKED home when you find them

An active pack is tracked (since 2026-09-21), but it lands in `task-packs/Done/`,
which is **gitignored**. Every correction, measurement and step record written into
a pack therefore leaves the tracked tree at unit close, no matter how carefully it
was written (the record branch keeps a snapshot; nothing on `main` does).

Attested: a single unit accumulated 13 pre-execution corrections and 6 step
records inside its pack. All of it was destined for a gitignored archive — the
orphaned-findings class the pre-flip runbook opens by diagnosing, reproduced
inside the unit that was reading that runbook. It surfaced only because the
operator asked whether the findings had actually been *filed*.

**The rule:** the moment a finding is durable, write it to a tracked home —
`FORWARD_LEDGER.md` for owed work, `memory/` for accumulated judgment,
`docs/FAILURE_MODES.md` for an adopter-facing class, `CHANGELOG.md` for what
shipped. Keep using the pack for working state, but treat anything you would be
sorry to lose as *not yet recorded* until it lands somewhere `git` can see.

## Pack pre-flights are tree-sensitive — a batched unit pre-flight measures a tree that will not exist

`espalier scope-check` walks the **live** reference graph and `espalier surface-impact`
reads **live** surface counts. Both go stale the moment an earlier pack in the same unit
lands. So does most of the 0-A checklist: items 1, 2, 5 and 9 all read the working tree.

**Batching a unit's pre-flight upfront therefore measures a tree that will not exist when
the later packs run** — which is precisely the question the per-pack re-run exists to
answer. Run the tree-sensitive items *per pack, immediately before that pack executes*.

The reverse holds for the rest. Items 3, 4, 6, 7 and 8 are tree-independent and are
**stronger** batched, because "does another in-flight pack reverse this?" cannot be
answered one pack at a time — it needs the whole unit in view at once.

Measure the overlap rather than assuming it, with a method the next author can re-run:
parse each pack's `## Files touched`, then count the paths that appear in two or more
packs of the same unit. Run that over the unit this note was written in and **13 of 30
distinct paths are shared**, two of them — the changelog and the forward ledger — touched
by all three packs. At that density, two packs in a unit touching disjoint files is the
exception, not the rule.

The figure this note originally carried for that unit was **6**, inherited from a pack and
never re-derived; it understated the real overlap by more than half. That is the more
useful half of the lesson: **state the method beside the number**, or the next author
inherits a precise-looking figure they cannot reproduce and will cite anyway.

Corollary worth stating separately: a pack that records a value another pack must consume
(a section number, an id range, a next-free counter) must write it into its own `## Landing`
stanza at execution time. The second pack reads the stanza; it does not re-infer the value.
A number inferred from the first pack's *draft* is a number measured against the wrong tree.

## Re-pin a row's probe BEFORE the first edit -- the repin verb cannot follow a fix (2026-09-12, the §C6 lane A)

`scripts/ledger_row.py repin` runs the row's probe from the checkout root and
refuses unless it prints the new open value now. After the fix has landed the
probe prints the *fixed* value, so a probe that the fix broke (DEF-770's parsed
doctor's JSON; the fixed doctor prints prose) or that the fix reshaped (DEF-772's
counted four verbs when only three were ever going to be listed) cannot be
re-pinned by the verb at all -- not from a worktree at the old head either, the
verb's cwd is the checkout. Two consequences. Re-pin to a driven instance before
the first edit, as the lane rule already says, and now for a mechanical reason as
well as an epistemic one. When you are already past that point, measure the
replacement probe by hand in a worktree at the pre-fix head and on the fixed
tree, and put the pair in the strike text; the strike verb retires the probe
without running it, so the record carries the measurement instead of the
probe. The `--strikes` check runs every remaining probe: expect the lane's own
test files to move DEF-665's count (subprocess timeouts above the 60 s ceiling)
if a new helper states a budget the ceiling fires before, and a TP-row rewrite to
move DEF-647's solo-cell count; explain each before re-pinning it.

**Earn the red in a HEAD worktree with `--continue-on-collection-errors`
(2026-09-12, the driven-verb lane).** `git worktree add <scratch> <old-head>`,
copy the lane's test files over it, run them there and count the reds -- never
by moving the live tree. Pass `--continue-on-collection-errors`: a test module
that imports a symbol the lane introduced reds at *collection* on the old head,
and without the flag pytest aborts the whole run on that one error, so the
count for every other file is never printed. That module's new tests count as
red (the import is the assertion); say so in the Landing line rather than
folding them into the measured number. Remove the worktree and `git worktree
prune` before the next filesystem scanner runs (the leftover-worktree footgun).

**`ledger_row.py repin` and `file` accept a probe that prints its open value
for the wrong reason (2026-09-12).** The first re-pin of a partially closed row
gave a probe that grepped a phrase the subject file does not carry; it printed
0, the tool recorded 0 as the open value, and the row would have read as
measured while measuring nothing. The tool drives the probe, but it only checks
that the command prints; it cannot know what the number means. Drive the probe
by hand and read WHY it prints that number before every `repin` and `file`.

**A probe pinned to a POPULATION count reads STRIKE_CANDIDATE on every
unrelated addition (2026-09-18).** `DEF-646` counted every `TP-*.md` in
`task-packs/` root and `DEF-648` every DRAFT pack there, so authoring a pack
moved both values while both defects stood -- `DEF-646` had already been
re-pinned once for exactly that (09-08, TP-449). Re-pinning the new number only
buys time until the next pack. Pin the CLAIM instead: `DEF-646` now reads the
folders the production guard test hands its orphan reader, and `DEF-648` counts
its five NAMED artifacts. The discriminator: a count of DEFECT SITES (files
carrying a marker) is a fine probe, because its moving means the defect moved;
a count of a POPULATION the defect merely lives in is not.

**The strike verb retires a row's probe whatever it reads (2026-09-12).** A
`--dry-run strike` on a row whose probe still printed its open value, and on
one whose probe now errored (it grepped a regex the fix deleted), both produced
the struck row and "1 probe(s) would retire". So a row closed by a fix that
replaced its probe's subject is struck directly, with the closing text saying
what the probe read and why the tests are the evidence now -- no repin-then-
strike dance. `--strikes` afterwards still reports any OTHER probe the lane
moved (a maintainer row underneath the class flipped this way and was struck
in-lane with its reasoning).

**A comment-level tier adjudication earns the slice plus the touched files, not
a second tier (precedent `0863d10`, repeated 2026-09-12).** A docstring citing
a pack id on a shipping surface red the provenance census twice in the full
run; the reword was proven by the two failing files, the touched module, and
`pytest -m contract -q` (3,142, four minutes). And in the pack parser itself:
a backticked token's parentheses and dashes are literal -- `` `check()` ``,
`` `setting(s)` ``, a regex -- and only a parenthesis or dash-tail OUTSIDE
backticks opens an annotation (five symbols and five literals changed before
that rule, zero after).

## A strike sweep can surface a sibling row the lane closed -- re-pin it, do not widen (2026-09-12, group 6)

`check_ledger_probes.py --strikes` after the lane's strikes printed a
STRIKE_CANDIDATE for a row the lane never named: `DEF-749`, the maintainer
twin of `DEF-788`, whose gitignore leg the lane had closed and whose probe
therefore flipped. Its third leg (the reset message names `_cold/` without
its `cc/` parent) was open and is one print line in a shipped file. Neither
striking it (a leg open) nor fixing it (a shipped-file change stales the tier
just run) is right after the tier: re-pin the row to the open leg with
`ledger_row.py repin --anchor --probe-cmd --text-file --open-value` and a
DRIVEN probe (run the verb on a scratch tree with `CLAUDE_PROJECT_DIR`
pointed at it -- the live plan is one env var away), and hand the leg to the
next lane that touches that surface. The sibling's flipped probe is the class
fix's receipt; the open leg is its own row.
