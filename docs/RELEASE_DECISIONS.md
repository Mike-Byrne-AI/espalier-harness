# Release Decisions

A chronological log of decisions that shape the public release path. Each
entry locks in a choice so future contributors don't re-litigate it
without an explicit revisit trigger.

---

## 2026-09-08 — Scan-credibility constants are calibrated; the 2026-08-05 hold's revisit condition fired

**Decision:** the thresholds in `espalier/scan_credibility.py` are pinned
against a dated snapshot of this tree's own telemetry history (740 rows, 74
runs, 2026-06-10 to 2026-09-08; the file is gitignored and every `espalier
scan` appends a run, so the constants' comment carries the re-derive command),
each constant carrying the measurement that set it, and the wallpaper bucket
reads candidate findings per distinct run instead of a strict-zero total. The 2026-08-05 entry below held them "uncalibrated until real history
exists"; that history now exists, so the hold closes rather than being
re-litigated (ledger `DEF-410e`, TP-449).

**Why:** the strict-zero cliff could not tell a dead rule from one that fired
once: `test_loosening` at one fire in 74 runs read `healthy` while
`retired_vocab` at zero read `candidate-wallpaper`. Measured on the snapshot,
the per-run rule changes exactly that one verdict and the other nine stand;
every scanner's verdict has agreed with its final value from run 5 onward,
which is what keeps `WALLPAPER_MIN_RUNS` at 5. The exemption-rate budget of
0.5 has 0.44 of margin below it (`magic_depth` at 0.06) and, above it,
`convergence_theater` at 0.80 is seven exemption-free firing runs from
crossing down to `healthy`; that crossing is the classifier reading new
evidence (its exemptions are old, its one live finding is not pragma'd), not a
mis-calibration, and it is the expected way a verdict moves. The module still
never gates. The three sibling `uncalibrated` markers in
`tools/cc/hooks/stop_gate.py` (the session-trajectory constants) stay
deferred: their history file, `session_length_baseline`, has never been
written on this tree, so there is nothing to calibrate them against.

**Conditions to revisit:** a scanner crosses a threshold for a reason other
than new evidence, the snapshot's margins stop describing the history (the
constants list them), or an adopter's history shows a scanner mis-bucketed at
these values.

**Amended 2026-09-26 — the revisit clock restarted at the seed.** The snapshot this
entry calibrated against is a gitignored scan-telemetry file on the private development
machine, and the history behind it is in the archive, not in the public repository; a
re-check reads it there, or the public history once enough has accumulated. The
recorded text is left as written.

---

## 2026-08-13 — This file and RELEASE_CHECKLIST.md are maintainer-only; a 2026-07-05 refusal is overturned

**Decision:** `docs/RELEASE_CHECKLIST.md` and `docs/RELEASE_DECISIONS.md` (this
file) classify `internal`. They stay tracked, and are excluded from the sdist,
the bespoke release archive, and GitHub's "Download ZIP". `RELEASE_CHECKLIST.md`
remains **audited** for claim drift despite that; this file does not, because a
chronological log of past choices is a record and auditing its historical counts
as live claims is a category error.

**Why:** neither doc ever reached an adopter — `init` deploys neither and the
wheel carries neither — but both still shipped in three surfaces nobody intended:
the sdist (`MANIFEST.in`'s `recursive-include docs *.md` is not classify-derived),
the release zip, and the Download ZIP. They are ritual for this repo specifically,
naming the maintainer's own accounts, settings, and one-time pre-flip sequence.

**Overturns a prior refusal.** `reports/deep-review-round2-findings.md` (2026-07-05)
filed *"RELEASE_CHECKLIST.md ships to adopters"* under **"Refuted at adjudication
(do-not-reopen)"**, reasoning that the doc is *"intentionally allowlisted in
`surface_contract.py` `_PUBLIC_DOC_RELPATHS` as operator-facing/normative."* That
was right that the doc is normative and wrong in the inference: `_PUBLIC_DOC_RELPATHS`
meant **two** things at once — *"audit this doc's counts"* and *"docs/README.md must
link this"* — so membership granted for the first silently bought the second.
The two axes are now split (`get_indexed_doc_relpaths()` derives INDEXED from
AUDITED by dropping `internal`), which is that distinction made mechanical. The
do-not-reopen marker is spent, not ignored.

**Note on provenance:** `reports/` is gitignored (`.gitignore:74`), so the
overturned finding exists on one machine and in no clone. This entry is the
tracked record; a future finder who re-raises "the release checklist ships"
should land here.

**Conditions to revisit:** a decision to publish a contributor-facing `RELEASING.md`
— the short mechanical subset someone other than the maintainer would need.
That was scoped out here, not refused.

**Amended 2026-09-26 — both files are now tracked in the public repository.** The
2026-09-25 seed dropped every `export-ignore`d file, and `TP-457` (the `DEC-33` fork,
branch (a)) adopted these two back as tracked, public files. The mechanical half of the
decision stands unchanged: they classify `internal` and stay out of the sdist, the
release archive and Download ZIP; "maintainer-only" now means "not shipped", not "not
visible". The sentence above naming the maintainer's own accounts, settings and
pre-flip sequence was read against both files in full on 2026-09-26: no account,
address or machine identity beyond the public org, the two repository slugs and the
PyPI project; the one repository-setting instruction was generalised in the checklist
the same day. The provenance note's `.gitignore:74` is `.gitignore:79` today. The
recorded text is left as written.

---

## 2026-09-24 — The licence is MIT, chosen on purpose

**Decision:** Espalier-Harness ships under the MIT licence, for the 0.8.0b1 seed
and the public repository that grows from it. Recorded as a decision rather than
a default: the pre-door review (Round 12, `memory/CONVERGENCE_LEDGER.md`) asked
whether anything in the tree should be held back or licensed differently, and
the operator chose MIT with the reasoning below.

**Reason:** The one component with standalone pricing power is the command-intent
extractor, `tools/cc/hooks/_bash_patterns.py`; a reviewer lifted it into an empty
directory and had a working classifier in under a minute. Withholding it is not
executable: 87 files reference it and the README's one-sentence pitch is the
guard. Its case list is public in `bench/corpus/` and in the test names whatever
the licence says. A source-available licence that restricts commercial use would
kill adoption in a category where adoption is the whole game, would sit badly
with the channels the launch plan relies on, and would make a trust tool whose
deciding component cannot be read a contradiction in its own terms. MIT prices
the shipped code at zero and keeps the copyright line. It does not prevent a paid
layer later, because such a layer would be new code, licensable on its own terms;
what it forecloses is taking back anything already released.

**Conditions to revisit:** a commercial layer is being built (hosted policy, fleet
views, audit aggregation): license that NEW work deliberately and take counsel
before it ships. A NOTICE file carving the pinned third-party doc excerpts under
`docs/external/` out of the blanket grant is hygiene, not exposure, and lands in
0.8.0b2 (a new root file is a test-pinned packaging change on the release commit).

**Enforcement:** none mechanical. `LICENSE` at the root is the text; this entry
is the record that it was a choice.

**Amended 2026-09-26 — this file is public.** The reasoning above was written for a
private record and is published as written: the licence choice is stronger for its
reasoning being visible, and the sentences on a component's pricing power, the launch
channels and a possible later paid layer are the reasoning behind a past choice, not a
plan or an announcement. The recorded text is left as written.

**Amended 2026-09-27 — the `NOTICE` file landed.** `NOTICE` at the repository root
carves the pinned excerpts under `docs/external/` (and the hook-protocol excerpt's packaged
mirror under `espalier/assets/docs/external/`) out of the MIT grant, names their owner and says the
project grants no licence to them. It ships in the sdist through `MANIFEST.in` and in
the wheel's licence metadata through setuptools' default `NOTICE*` glob, both verified
on the built artifacts, in the 0.8.0b2 release commit.

## 2026-08-05 — Scaffolding tags are deleted at the flip; version tags are re-annotated

**Decision:** Of the 42 lightweight local tags, the 34 pre-execution
scaffolding tags are deleted before the repository goes public, and the 8
lightweight `v*` version markers are **re-annotated** rather than deleted.

**Why:** The checklist instructs deleting every lightweight tag so a stray
`git push --tags` cannot leak development scaffolding. Scaffolding tags are that
leak risk; version tags are not — they are historical anchors that `git
describe` and any bisect narrative rely on, and an undiscriminating loop over
"is it lightweight" takes both. Two measurements decided the form. First, 19 of
the 27 `v*` tags are **already annotated**, including the two most recent
alphas, so the 8 lightweight ones are stragglers from before the convention
settled rather than a deliberate category — re-annotating finishes a convention
already in force. Second, `git ls-remote --tags origin` returns **zero**: every
tag is local-only, so this is a purely local operation and the leak it guards
against is entirely prospective.

**Amended 2026-08-20 — one of the 34 is a KEEP.** `pre-pack-TP-104` is
lightweight and pre-execution, so the rule above sweeps it into the delete set.
It is not scaffolding: `tests/test_sister_site_probe_regression.py` checks that
tag out as its fixture state, and the test **skips** rather than fails when the
tag is absent — so deleting it removes the coverage silently and leaves the
suite green. Delete 33; keep `pre-pack-TP-104`. It is unreachable from `main`,
so it never propagates via `--follow-tags` and carries no leak risk that would
justify the trade.

**Operational note:** delete the 34 one at a time. `zsh` does not word-split
unquoted parameters, so a bulk `git tag -d $LIST` passes the whole list as a
single tag name, deletes nothing, and reports success.

**Conditions to revisit:** the ritual ever needs a pre-`v0.7` tag present on the
remote.

**Amended 2026-09-26 — retired.** `DEC-31` moved development into the seeded public
repository, so no tag from the private tree ever reached a public remote and the
delete-stray-lightweight-tags sweep was retired (checklist, First publish step 7);
`git ls-remote --tags origin` on the public repository returns `v0.8.0b1`. The recorded
text is left as written.

---

## 2026-08-05 — God-file decomposition stays deferred (trigger measured, unmet)

**Decision:** The three largest hook-layer modules are not split. The deferral's
own trigger — "splitting is net-negative until one becomes an **edit hotspot**"
— was measured against the actual criterion (change frequency, not size) and is
unmet.

**Why:** Over the 101 commits since the deferral was recorded, the three files
took **9 / 4 / 3** commits. The busiest sits at 8.9% and ranks fourth, behind a
5,364-line CLI module that is 3.6x more churned and that nobody proposes
splitting. Size is independently not the signal: the god-file scanner's own hint
threshold is 1,500 lines, and the largest of the three, at 1,490, still
classifies as "monitor" rather than "review for split". The standing cost
argument is unchanged — each split adds a sibling import, a copied-subset
fixture entry, and a vendor-mirror obligation.

**Conditions to revisit:** any of the three exceeds ~15% of commits in a
100-commit window, or crosses 1,500 lines.

**Amended 2026-09-26 — the revisit clock restarted at the seed.** The 100-commit window
this condition measures is private history, in the archive; the public repository's
history starts at the 2026-09-25 seed, so measure there until the public history is
long enough. The recorded text is left as written.

---

## 2026-08-05 — The hook table stays in the project charter

**Decision:** The hook summary table is not routed out of the root project
charter into the generated live-surface document.

**Why:** The destination has **no auto-pull trigger** — it is read only by
internal machinery and one command body — and an unpulled document that never
loads is worse than a resident one. The scope is also smaller than it first
appears: the agent-roster half is **foreclosed by a gate rather than deferred**,
because the smoke command greps and counts those rows and asserts each one
resolves. Even the hook table is not free, since a surface-impact module names
the charter as a hardcoded hook-count site, and the detailed hook reference the
table points at already exists elsewhere. Honest saving: one summary table.

**Amended 2026-09-14 — the surface-impact clause above was wrong when written.**
`espalier/surface_impact.py` deliberately does NOT list the charter as a hardcoded
hook-count site: its own comment says the charter's only numeral (the count of
governed hook events) does not move with the hook count, and the `## Hooks`
table's row count is pinned by a different contract. The decision stands on the
other two reasons; the recorded text is left as written.

**Conditions to revisit:** the live-surface document is given a firing pull
trigger.

---

## 2026-08-05 — Scan-credibility constants stay uncalibrated until real history exists

**Decision:** The two scan-credibility calibration constants remain at their
documented defaults. Recorded as a locked decision, not as debt.

**Why:** Both constants are named, documented, unit-tested, and — by the
module's own contract — drive **advisory text only, never a gate**; the module
cannot fail a build on them. There is nothing an executor could act on today
even with a pack, because the calibration input does not exist. Two details
sharpen the tracking point rather than the decision: the obligation is older
than any sweep that has since rediscovered it, and the original marker was a
literal `TODO(calibration)` later rewritten into prose — which is precisely what
made a code-comment grep lane blind to it thereafter.

**Conditions to revisit:** enough real scan-telemetry history accumulates to
calibrate against. This is never a build pack.

**Amended 2026-09-26 — the revisit clock restarted at the seed.** The scan-telemetry
history this condition waits for accumulated on the private tree and stays in the
archive; on the public repository it restarts from the seed. The recorded text is left
as written.

---

## 2026-06-10 — Fusion plan-gates the adopter's source (do NOT auto-exempt)

**Decision:** A fused / adopter repo plan-gates the host's own source by
default. `espalier fuse` does **not** seed an active
`plan_exempt_prefixes`; it seeds a *commented* stub in the fusion's
`espalier.toml` plus welcome copy in the seeded `CLAUDE.md` / quickstart.
The existing per-deny `_PLAN_EXEMPT_HINT` remains the at-friction
discoverability path.

**Why:** Plan-gating the user's source *is* the core value prop. The
codebase already encodes this — `_hook_utils.harness_exempt_prefixes(root)`
adds `espalier/` to the exempt set **only** when `is_self_host_repo(root)`;
for a user repo it returns the universal set, and `plan_guard.py`
states: "a user repo with its own `espalier/` directory MUST NOT skip plan
discipline — that would silently disable the gate for user code." Lever 1
(`is_self_host_repo()==False` for a fusion) exists precisely to turn adopter
behavior **on**; auto-exempting the host source would spend Lever 1 and then
immediately undo what it turns on.

**Why not auto-seed:** An earlier spec called for seeding `espalier.toml`
with `plan_exempt_prefixes = [<detected host source root>]`. That line is
**corrected here** — it contradicts the plan-gating design decision and
would gut the gate on exactly the code the adopter writes most. The good
version of that idea is a *commented* stub (opt-in), never an active
exemption.

**Residual / onboarding:** the only real cost is the first-touch deny on the
adopter's first source edit. Mitigated by (a) welcome copy that sets the
expectation *before* the first deny, (b) the commented stub one uncomment
away, (c) the existing at-friction `_PLAN_EXEMPT_HINT`. **Zero deny-predicate
change.**

**Conditions to revisit:** if adopter feedback shows the first-session plan
requirement is a material drop-off, reconsider a lighter default (e.g. a
`fuse --lenient` flag that *activates* the stub) — but never silently
auto-exempt the host source.

---

## 2026-05-13 — Bundled-asset strategy (Path B)

**Decision:** Strip default deploy of agents/commands/skills. Move the
existing bundled files to `examples/dogfooding/.claude/` where they
accurately describe Espalier-Harness's own use. Announce language-aware
agent templates as a v0.7 feature.

**Why not Path A (genericize):** 2-3 weeks of work for v0.6.1 vs. a
2-3 day path to honest v0.6.1 plus v0.7 with a clean feature story.

**Why not Path C (ship with disclaimer):** The bundled
`architecture-analyst.md` literally says "Understands how Espalier-
Harness's modules connect." A disclaimer in the README doesn't prevent
the agent from making category-error statements in conversation. The
deployed content needs to either be generic or absent.

**What still deploys:** Hooks (`tools/cc/hooks/`), `.claude/settings.json`,
`CLAUDE.md`, `ESPALIER_MEMORY.md`, `.espalier/integrity.json`. The mechanical
enforcement layer.

**What was true before this pack:** README claimed agents were "tailored
to your repo." This was verifiably false -- the agents described
Espalier-Harness's own architecture and deployed verbatim to every user
repo. The claim is removed; the deploy path is removed; the bundled files
are repositioned at `examples/dogfooding/`.

**Conditions to revisit:** none were recorded when this decision was logged
(label added 2026-09-14; the decision text above is unchanged).

---

## 2026-05-13 — Fresh-repo gitignore protection

**Decision (v0.7.0..v0.7.8):** Default to suggest-only (print copy-paste
block); add opt-in `--write-gitignore` flag for active append.

**v0.7.9 update:** Default-flipped — `espalier init .` now
writes the entries automatically; `--no-write-gitignore` is the new
opt-out. The original opt-in framing relied on operator discipline
that QUICKSTART-followers reliably skipped (the "Init Suggestions
Gated on File Existence Miss the Fresh-Repo Flow" failure class).
Auto-write closes the loop for the common case; existing users with
a curated `.gitignore` get APPEND (never overwrite) behavior so the
mutation is non-destructive.

**Required-ignore set:** `.claude/settings.json` (machine-detected
interpreter name), `.espalier/` (integrity manifest, per-install),
`.espalier-state/` (session flags), `reports/` (fingerprint output),
`cc/blueprints/` (cognitive blueprint state). Both `.espalier/` and
`.espalier-state/` are listed because both directories exist with
different writers (integrity vs stop_gate).

**Root cause fixed:** the `REQUIRED_GITIGNORE` handler in `espalier/cli.py`
gated the suggestion on `gitignore.exists()` — a fresh repo with no `.gitignore` got zero
guidance. Unconditional check; presence only affects phrasing.

**Conditions to revisit:** none were recorded when this decision was logged
(label added 2026-09-14; the decision text above is unchanged).

---

## 2026-05-13 — v0.6.1 audit-followup baseline lock

Five independent audit runs converged on the v0.6.0 release-readiness
issues. Before any fixes land, `reports/ultimate_baseline_*` captures
the pre-edit state:

- `ultimate_baseline_evidence.json` — full JSON inventory of the
  state the follow-up packs will fix.
- `ultimate_baseline_archive_members.txt` — proof the shipped
  release archive contained `project.zip`.
- `ultimate_baseline_init_output.txt` — proof the init flow gave
  no gitignore guidance on fresh repos.
- `ultimate_baseline_release_check.txt` — proof the release gate
  reported green despite the archive leak.
- `ultimate_merge_scope.json` — the merge ledger across all five
  audits.

This evidence is referenceable from any follow-up TP. After the v0.6.1
release ships, the same capture commands re-run produce the after-state
for diff.

**Conditions to revisit:** none were recorded when this decision was logged
(label added 2026-09-14; the decision text above is unchanged).

---

## 2026-05-12 — Plugin manifest removed entirely

**Decision:** The `.claude-plugin/plugin.json` manifest is removed from
the repo. The CLI-first install path (`pip install espalier-harness`
plus `espalier init`) is now the sole supported install narrative.
References to `.claude-plugin/` are scrubbed from active code, tests,
docs, and the surface-contract classifier. Historical CHANGELOG entries
and the 2026-04-30 decision below are preserved as record.

**Reason:** The plugin shape is a poor structural fit for Espalier,
not just unvalidated. Three concrete misfits:

1. **Hooks invoke `$CLAUDE_PROJECT_DIR/tools/cc/hooks/...`.** The hook
   scripts live in the user's repo because `espalier init` deploys
   them there. A plugin lives in `~/.claude/plugins/`, so a real
   plugin install would either rewrite the hook commands to
   plugin-local paths or still have to write into the user repo on
   activation — which is the CLI's job.
2. **The harness is stateful per-repo.** It writes to `cc/blueprints/`,
   `reports/`, `ESPALIER_MEMORY.md`, and the integrity manifest at the repo
   root. Plugins are designed as horizontal capability bundles, not
   stateful governance with on-disk session continuity.
3. **`espalier init` already exists for a reason.** The CLI is the
   harness's deploy mechanism. Adding a plugin path would duplicate
   that role or paper over it; neither outcome is good.

The 2026-04-30 entry framed the plugin path as "unvalidated, ship the
validated path first." This entry promotes the underlying objection
from implicit ("we haven't validated it") to explicit ("the shape
doesn't fit"). Keeping a parked manifest invited future contributors
to revisit it; removing the manifest closes the question.

**Conditions to revisit:** A future Claude Code plugin protocol that
natively supports per-repo state, hook scripts that live in the user
repo, and a deploy-into-target-repo step would warrant reconsidering.
Until then, the question is closed.

**Enforcement:** `scripts/release_check.py` no longer has a
`check_plugin_status` gate (no manifest to check). The
`espalier.surface_contract` classifier no longer lists `.claude-plugin/`
as `local_only` — defense-in-depth against a re-introduction is
deferred to the PR review that would re-add the directory.

---

## 2026-04-30 — CLI-first install path

> **⚠ SUPERSEDED 2026-05-12 (manifest removed entirely, above) — and EXECUTED. Kept as record; do not act on its plugin-manifest clauses.** Verified 2026-08-04: `.claude-plugin/` is **not on disk and not tracked**, and `git grep -c "claude-plugin" -- espalier/surface_contract.py` is **0**, so the scrub the 2026-05-12 entry describes did happen.
>
> **This entry also contradicted ITSELF, which is why it is annotated rather than left alone.** Its *Enforcement* paragraph says `.claude-plugin/` *"currently classifies as a `public` shipping surface"*; its *Operational notes* paragraph says the classifier *"classifies `.claude-plugin/` as `local_only`"*. Both cannot be true, and the second is the wrong one — measured today, `classify_release_path(".claude-plugin/plugin.json")` returns **`public`**, precisely *because* the classifier no longer names the prefix at all and the path falls through to the default. An internally inconsistent decision record is worse than a stale one: a reader resolving the conflict by picking either sentence would act on a surface that no longer exists.
>
> Both clauses are now moot — there is no manifest to classify. The CLI-first decision this entry actually settles still stands and is untouched.

**Decision:** Espalier-Harness ships and is installed as a CLI/Python package
(`pip install espalier-harness` and `pip install -e .`). The project-local
`.claude/` assets ride along with the package and are activated by the
existing `espalier init` flow when applied to a target repo. The
Claude plugin manifest at `.claude-plugin/plugin.json` is kept in the
repo but treated as experimental, not advertised in the public
quickstart, and excluded from the public release archive built by
`scripts/build_release_archive.py`.

**Reason:** The CLI/Python path is already production-quality —
`pyproject.toml` is correct, the package shape is verified by
`tests/test_artifact_parity.py`, and the source-vs-wheel parity gate
catches regressions in the install path before they ship. The plugin
manifest, by contrast, has not been validated end-to-end against a
clean Claude Code install. A broken plugin surface is worse than no
plugin surface for a first-OSS impression: it implies the harness is
authoring-grade for Claude Code plugins when in fact the install
behavior is unverified. Shipping with a single working install
narrative is the conservative choice.

**Conditions to revisit:**

- A future task pack lands a real, end-to-end-validated
  plugin install path, including a `docs/PLUGIN_SMOKE_TEST.md` that
  documents `claude plugin install/list/run` against a known-good
  Claude Code version.
- A user-reported issue confirms the plugin manifest works as-is
  against current Claude Code AND someone is willing to own the
  validation cadence.
- Claude Code's plugin protocol changes substantially enough that the
  current `.claude-plugin/plugin.json` shape becomes a release liability
  even when treated as experimental — at that point, removing or
  rewriting the manifest is preferable to silently shipping it.

**Enforcement:** this is a review discipline, not an automated gate. The
README makes no "plugin install" claim today; if one is added it must sit
inside an "experimental" caveat window — no test enforces this. Note
`.claude-plugin/` currently classifies as a `public` shipping surface (it
is not in the release-excluded prefixes), so treating it as excluded from
the published `.zip` by `scripts/build_release_archive.py` is not currently
guaranteed.

**Operational notes:** The plugin manifest
(`.claude-plugin/plugin.json`) is kept in the repo for development
purposes — it lets contributors iterate on the plugin shape against
working Claude Code installs without first reverse-engineering it from
scratch. It is excluded from the published release archive
(`scripts/build_release_archive.py` → `surface_contract.classify_release_path`
classifies `.claude-plugin/` as `local_only`). Public-facing
documentation reflects this posture: README's Quick Start ends with a
one-line footnote pointing here for the rationale, not a
full subsection that could imply the plugin path is supported. The
validated install path is CLI-first
(`pip install espalier-harness`) plus project-local `.claude/` assets
deployed by `espalier init`, with parity gated by
`tests/test_artifact_parity.py` and the matrix-cell wheel smoke
(`scripts/wheel_smoke.py`). Promoting the plugin path
requires landing a `docs/PLUGIN_SMOKE_TEST.md` per the conditions to
revisit above — at which point this footnote can be expanded back into
a full Quick Start subsection.
