# Espalier-Harness Release Checklist

## Current tag posture (as of 2026-09-27)

The v0.8.0 series has left its alpha ladder: the tree carries `0.8.0b2`,
the second beta, whose release commit is dated 2026-09-27 and lands on
`main` through the pull-request flow, the tag following the merge (the
"Release procedure" below). `0.8.0b1`, the first beta and the first public release,
was cut on 2026-09-24 from the tree the release matrix proved before the
fold, and its tag and publish went through the "First publish" sequence
below on 2026-09-25; that section is now the record of the ritual. The alpha cadence was one task pack per tag. From here: fold `[Unreleased]` → `[0.8.0b{N+1}]`, then
`[0.8.0]` GA once the beta has held, only when there is shipping content
to fold; do NOT tag empty narrative deltas. The historical decisions
appendix at the bottom of this file documents the specific gates that
gated the alphas — keep them for archaeology; do not re-litigate.

Three release-validation tiers, fastest to most thorough. Each tier has
a different goal — use the tier that matches the stage of work, not the
fastest tier as a substitute for a slower one.

## Tier 1 — Fast local signal (seconds bare -- 1.5 s measured 2026-09-23; about ten minutes with the tests opt-in)

```bash
python scripts/release_check.py
```

Use during development. Catches obvious drift: stale doc counts, archive
leak, classifier mismatches, sharp-edges entries falling out of sync,
license/security/contributing/changelog file presence.

The summary line reports `N passed, M skipped`. `SKIP` indicates an
opt-in check whose env var wasn't set (currently `tests_pass` and
`wheel_smoke`). Exit code stays 0 when no `FAIL` regardless of `SKIP` —
this is the "fast signal green" semantic, not publish proof.

> CHANGELOG footer monotonicity (newest-first; `[Unreleased]` base
> matches newest stable tag) is enforced by
> `tests/test_changelog_footer.py` — runs in `pytest -q` and
> surfaces as part of the full pytest gate.

To run the full ladder locally:

```bash
ESPALIER_RELEASE_CHECK_WITH_TESTS=1 \
ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE=1 \
python scripts/release_check.py
```

## Tier 2 — Local readiness gate (about 45 minutes serial with tests on; seconds with `--skip-tests`, which is signal, not proof)

```bash
espalier pre-release .
```

Use before opening a release PR. Runs the fast signal plus targeted
tests. The `--skip-tests` and `--skip-parity` flags
exist for narrow debug loops; they produce fast signal, **not publish
proof**. Treat the unflagged invocation as the actual readiness gate.

## Tier 3 — Publish gate (about two hours on the self-host box: step 0 about 25 minutes per interpreter, then the matrix, measured 55:39 wall on 2026-09-23 with stage 02 alone 45:14; `DEF-918` and `DEF-919` row the two levers that halve it)

**Step 0 — the suite on a tree it was not written on.** Before the matrix, the
full proof tier runs in a fresh clone of HEAD, once on the floor interpreter and
once on this box's own, each under its own venv and a whitelisted environment.
The gate proves HEAD (it refuses a dirty tree), resolves `pytest` and `mypy`
under the venv before running, and reads the tier's receipt by its tail so a
leg that ran nothing cannot read as a test failure; exit 70 means the gate
itself refused. It runs alone on the box (never beside another suite), about
25 minutes per interpreter at 4 xdist workers; `PYTEST_ADDOPTS=-rfEs` passes
through when you want the skips enumerated beside the failures (`-rs` alone
replaces the default `-rfE` and hides the failed names from the summary).

```bash
# 0. The gate: HEAD in a fresh clone, the floor interpreter and this one (exit 70 = the gate refused)
python scripts/fresh_clone_gate.py --python 3.10 --python "$(command -v python3)"
```

```bash
# No opt-in exports: the matrix strips the three ESPALIER_RELEASE_CHECK_WITH_* flags
# from every child that would act on them (both pytest legs, both release_check.py
# calls; anti-recursion, 2026-09-23), so they act only on a direct
# `python scripts/release_check.py` run (Tier 1 above)
python scripts/final_release_matrix.py
```

Required before tagging. Runs:

1. Source checkout non-slow tests
2. Source release archive build + extracted smoke
3. Sdist build + install smoke
4. Wheel build + install smoke
5. Artifact cleanliness (classifier + independent denylist)
6. Surface support matrix validation

Writes:

- `reports/final_release_candidate_report.json` — per-stage status with
  durations and `ready_to_tag` flag.
- `reports/final_release_candidate_archive_members.txt` — sorted member
  list from the freshly built archive (audit trail for what shipped).

Exit 0 with no `--skip` ⇒ `ready_to_tag: true` ⇒ publish-ready. A `--skip` run
exits 0 for the stages it ran, lists the skipped ids under `skipped`, and
writes `ready_to_tag: false`: a stage nobody executed is neither PASS nor
FAIL, and the flag covers only a run in which every stage ran.

## Dual-witness archive validation

Tier 1 and Tier 3 both run the dual-witness pattern: classifier
(`espalier.surface_contract.classify_release_path`) AND independent
denylist (`espalier.release_denylist.find_denied_members`) must both
clear every archive member. Two witnesses with no shared code are
harder to fool than one. The v0.6.0 `project.zip` leak shipped because
the classifier (the only witness at the time) had no rule for top-level
archives; the gate consulted the same classifier and saw nothing wrong.

To independently validate an already-built or already-downloaded ZIP:

```bash
python scripts/release_check.py --validate-archive <path/to.zip>
```

Use against `dist/*.zip` to catch what users would download, or against
`gh release download` output to catch CI-rebuild drift.

## Release narrative parity (manual judgment)

`scripts/release_check.py` mechanizes every parity check that reduces to
a rule: numeric-count propagation across docs (`check_docs_count_claims`),
version-truth across `pyproject` / `__init__` / footer
(`check_version_consistent`), doc overclaims (`check_docs_no_overclaim`),
referenced-file existence (`check_docs_no_phantom_files`), and CHANGELOG
presence (`check_changelog_present`). Two narrative judgments remain
irreducibly manual — confirm both by hand before publishing:

1. **CHANGELOG completeness.** Does the `[<new-version>]` section name
   every behavior-affecting change that landed since the previous tag?
   Walk the commit chain and reconcile against the changelog:

   ```bash
   git log --oneline <prev-tag>..HEAD
   ```

   A landed fix the CHANGELOG omits is a narrative gap — the changelog is
   the adopter's only view of what changed.

2. **Tag-message faithfulness.** Does the annotated tag message
   (`git tag -a vX.Y.Z -m "..."`) summarize the commit chain honestly —
   no overclaim, no omitted breaking change? The tag message is what the
   GitHub release publishes verbatim (via the `--notes-from-tag` flag).

These are operator-judgment steps, not gates; there is no green/red for
"faithful." Read them as the final narrative pass before the tag becomes
public.

## Pre-tag dry run protocol

```bash
# 1. Clean state
git stash               # if any in-progress work
rm -rf dist/ build/

# 1b. The gate: the full tier in a fresh clone of HEAD, per interpreter (Tier 3 step 0)
python scripts/fresh_clone_gate.py --python 3.10 --python "$(command -v python3)"

# 2. Run the full ladder (no opt-in exports: the matrix strips them from every child that would act on them)
python scripts/final_release_matrix.py
echo "Final matrix exit: $?"

# 3. Validate the built archive directly (second witness) -- the archive THE RUN
#    built: the matrix builds it inside stage 02's work directory and never
#    writes dist/espalier-harness-<version>-release.zip (that path is the
#    standalone builder's default, step 2 of First publish below)
python scripts/release_check.py --validate-archive \
    "$(ls dist/final-release-matrix/source_archive_work/archive_out/*.zip)"

# 4. Inspect the final report
python -m json.tool reports/final_release_candidate_report.json

# 5. Inspect the archive member list
head -30 reports/final_release_candidate_archive_members.txt

# 6. If all green and ready_to_tag is true, proceed to tag.
```

### Trigger the dispatch-only CI jobs (2026-09-01)

⚠ **Neither job runs on a push, and neither is dispatch-only any more (corrected
2026-09-26, after the public seed).** On the public repository `test.yml` and
`portability.yml` run on every `pull_request` against `main` (`portability.yml`
path-filtered to `**.py`, `pyproject.toml` and its own file) and on
`workflow_dispatch`; neither has a push trigger (`release.yml` alone runs its readiness
gate on a push to `main`). The one cron in the tree belongs to `refresh-externals.yml`.
The `tier` job decides which cells a PR earns
(`scripts/proof_tier.py --base`): the contract slice for docs, tests and scripts;
the full parallel tier, with `clean-checkout` alongside, for engine, hook and
workflow changes. `publish.yml` calls `release.yml` only; neither invokes these two.

Until the seed both jobs were dispatch-only on the private development tree, for
cost, and this step was the only cross-OS and multi-interpreter coverage in CI.
That is no longer so, but a release commit whose own PR ran the cheaper tier still
has **no macOS signal, no Windows signal, and no 3.11/3.12/3.13/3.14 signal** newer
than the last full-tier PR. This is the same blind spot that let 24 Windows
failures accumulate unseen through August. **Before a tag, dispatch both on `main`
unless the release commit's PR ran the full tier. Do not skip it.**

The static tier — mypy, ruff, freshness, workflow-lint, the audits, the benchmark —
runs on every PR whatever the tier, so it needs no dispatch.

```bash
gh workflow run portability.yml --ref main
gh workflow run test.yml --ref main
gh run list --workflow=portability.yml -L1
gh run list --workflow=test.yml -L1
```

Wait for both green before pushing the tag. A `workflow_dispatch` run of `test.yml`
runs `clean-checkout` across the full interpreter matrix, as the full tier does on
a PR.

On the portability run's Windows cell, look for the two `real_windows_host` tests in
`tests/test_write_guard.py::TestGitBashDrivePrefix` reported as PASSED, not skipped:
they are the only coverage of the `Path.resolve()`-based normalisers and the root
producer under the Git Bash drive spelling (the `/c/Users/<u>` form the Bash tool's own
`pwd` returns there), and they are skipped on every other cell by construction. A green
run that skipped them proved nothing about that layer.

## After-tag protocol

```bash
git tag -a v<version> -m "v<version>: <one-line>"
git push origin v<version>

# Confirm the tag triggers the release workflow
gh run watch
```

The publish workflow parks on the `pypi` environment until its required
reviewer (the operator) approves the deployment in the run's page; the upload
and the attestation follow in about two minutes. Then verify what was
published as the "Release procedure" step 9 below says: the files PyPI
serves, the wheel's attestation, and a fresh-venv install. The GitHub release
page carries no assets, so there is nothing to download from it.

## CI tier mapping

See [INSTALL-CI.md](INSTALL-CI.md#which-jobs-run-on-your-repo) for which
GitHub Actions workflow runs which tier.

## Required status checks — freshness gate

The `freshness` job in `.github/workflows/harness-guard.yml` runs
`espalier freshness check --critical-only --changed-files <PR diff>`.
For it to actually block merges, the operator must add it to GitHub
branch protection's required-status-checks list.

One-time setup (per protected branch):

(Done on the public repository on 2026-09-25: branch protection on `main` lists
`freshness` among its required status checks and enforces on admins. The steps stay
for a re-seed.)

1. **Settings → Branches → Branch protection rules → main**.
2. Under "Require status checks to pass before merging", search for
   `freshness` and check the box.
3. Save.

Verification:

- Open any PR that touches a fragment's bound path; the gate must
  appear in the PR's status checks panel as a required check.
- Submit a PR that intentionally moves a fragment to `critical`
  state on a bound path the PR touches; the `freshness` job MUST
  fail with exit 2 and the merge button MUST stay disabled.

Stale fragments do not block — see `docs/FRESHNESS.md` §7 for the
exit-code matrix.

### Re-pin the cohort at the cut

Run `espalier freshness pin --all` before tagging.

Every fragment sharing one pin date crosses both day thresholds together,
so a cohort that is `fresh` when a release starts can be `stale` — and
then blocking — partway through the next one. Re-pinning at the cut resets
those clocks deliberately, in one place, rather than as a surprise red on
somebody's unrelated PR a fortnight later.

Treat it as a **re-attestation, not a tidy-up**: `--all` asserts that every
bound claim still holds. Confirm the fragments are mechanically correct
first — a green suite plus `espalier freshness check` — and never re-pin to
clear a red you have not read. Staggering the dates is *not* the fix; writing
spread `last_verified_at` values would assert verifications that never
happened.

## Trusted-publisher setup for PyPI

One-time configuration to enable `.github/workflows/publish.yml` to
publish to PyPI via OIDC. No API tokens involved.

### Pre-publish PyPI namespace probe

Confirm the namespace is unowned before reserving it (done 2026-09-25: `espalier-harness`
is claimed, its first upload `0.8.0b1`; this probe is for a re-seed under a new name):

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/espalier-harness/json
# 404 = namespace available
```

Record the timestamp + response in the commit body that lands the
publish workflow. This is the audit trail.

### PyPI maintainer-side setup (browser, one-time)

1. **Reserve the project name** at https://pypi.org/account/login →
   "Your projects" → "Project reservation" → enter `espalier-harness`.
   Reserves the namespace without uploading any artifact. Rejects
   approach (a) (`twine upload` placeholder, which would require an
   API token); rejects approach (c) (race for namespace at first
   publish, which is observable to anyone watching the PyPI feed).
2. **Add the trusted-publisher relationship**: Project → Settings →
   Publishing → "Add a new publisher". Fill in:
   - Owner: `Mike-Byrne-AI`
   - Repository name: `espalier-harness`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`

The subject claim PyPI binds is automatic from those fields; the
following claims are pinned end-to-end:

- `repository_owner: Mike-Byrne-AI`
- `repository: espalier-harness`
- `workflow_ref: .github/workflows/publish.yml@refs/tags/v*`
- `environment: pypi`
- `job_workflow_sha` (the commit SHA `publish.yml` was at when the
  job ran — required so a malicious tag pointing at a different
  `publish.yml` content cannot publish under this relationship).

### GitHub Environment setup (browser, one-time)

Settings → Environments → New environment → `pypi`. Configure:

- **Required reviewers**: at least one maintainer approves each
  deployment before the publish job runs.
- **Wait timer**: 5 minutes. Lets the maintainer abort a runaway
  workflow before any upload happens.
- **Deployment branches and tags**: add a rule for the **tag** pattern
  `v*`. `publish.yml` triggers on `push: tags: ['v*']`, so the deployment
  ref is a tag, not a branch — a `main`-only branch rule blocks every
  legitimate publish. (A fork PR cannot push a tag to this repo at all,
  so there is no fork-PR tag threat to defend against here; the real
  protections are the required reviewer and the wait timer above.)

### Action SHA pin

`.github/workflows/publish.yml` pins the publish action to a 40-char commit
SHA rather than a floating tag:
`pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33` (v1.14.2).
`tests/test_publish_workflow.py::TestUsesAreSHAPinned`
enforces that the `uses:` ref is a 40-char SHA, so a regression to a floating
tag fails CI. To re-pin to a newer action release, resolve its tag to a SHA and
substitute it:

```bash
gh api repos/pypa/gh-action-pypi-publish/commits/v1.14.2 --jq '.sha'
# Substitute the printed SHA into publish.yml (and update the tag comment
# beside it, plus every narrative "is SHA-pinned below to vX" sentence in
# that file: tests/test_publish_workflow.py::TestUsesAreSHAPinned binds each
# one to its uses: tag comment, so a missed sentence reds instead of aging).
```

⚠ **Use the `commits/<ref>` endpoint, not `git/refs/tags/<ref>`.** These
release tags are ANNOTATED, so `git/refs/tags/...` returns the sha of the tag
OBJECT — a different sha from the commit it points at. GitHub Actions cannot
resolve a tag-object sha, so pinning the value that recipe prints silently
breaks publishing at the next run. `commits/<ref>` dereferences to the commit.

### First-time verification ritual

> ⚠ **Under DEC-25 this ritual ran in the SEEDED PUBLIC repo, between steps 6
> and 7 of [First publish](#first-publish-one-time--seeds-a-new-public-repo) , on
> 2026-09-25; the repository you are reading is that one (corrected 2026-09-26).** It exercises the trusted-publisher handshake, which binds
> `Mike-Byrne-AI/espalier-harness` + `publish.yml` + environment `pypi`; none of
> those existed on the private development repo, so running it there proved nothing
> about the thing being rehearsed and burned metered private-repo minutes. Its step-5
> cleanup (`git push origin :refs/tags/v0.0.0a0`) also requires that tag
> protection is not yet applied — see the split note in step 4. The claim below
> that the `pypi` environment "currently has no required reviewers and no wait
> timer" describes the OLD repo; on the new one step 6 creates it fresh.

Before the first real `vX.Y.Z` tag, dry-run the publish pipeline against a
throwaway tag.

⚠ **As written, this ritual verifies the tag/version guard — NOT the OIDC
handshake.** It was authored to prove the trusted-publisher binding end-to-end,
and the only way to reach the handshake is to make `pyproject.toml` agree with
the throwaway tag. That step was prescribed here on 2026-08-20 and **withdrawn
the same day**, because agreeing versions would publish `0.0.0a0` as this
project's first PyPI release, immutably (see step 3 for the full reasoning). Do
not reinstate it.

**The success criterion is therefore inverted from the usual one: this run is
CORRECT when it stops RED at "Verify tag matches the built version".** A run that
goes green past that step means the guard did not hold — stop and investigate
before anything else. The unproven handshake is a real remaining gap, tracked as
`DEF-449`.

1. **Confirm the PyPI namespace is reserved** (per the "PyPI
   maintainer-side setup" subsection above). The reservation must be
   active before any tag-push triggers the publish workflow.
2. **Confirm the GitHub `pypi` environment exists** (per the "GitHub
   Environment setup" subsection above) with required reviewers, a wait
   timer, and a deployment rule for the **tag** pattern `v*`. ⚠ Not a
   `main`-branch rule: `publish.yml` triggers on `push: tags`, so the
   deployment ref is a tag, and a branch-only rule blocks every legitimate
   publish — as that subsection states.
3. **Push a throwaway test tag.** From a non-`main` branch:
   ```bash
   git checkout -b publish-dry-run
   git tag v0.0.0a0
   git push origin publish-dry-run v0.0.0a0
   ```
   ⚠ **DO NOT make `pyproject.toml` match this tag.** The version guard
   ("Verify tag matches the built version") rejecting `v0.0.0a0` against the real
   project version is the ONLY thing standing between this rehearsal and a real
   upload, and the note below about a PyPI-side failure is **wrong**: `0.0.0a0`
   is a valid PEP 440 version, `espalier-harness` does not exist on PyPI yet, and
   a pending trusted publisher CREATES the project on first use. The `pypi`
   environment currently has no required reviewers and no wait timer, so nothing
   else would stop it. Making the versions agree would publish `0.0.0a0` as the
   project's first release, immutably, from a throwaway branch — while you sat
   watching for a red step that had quietly gone green.
   ⚠ **Consequence, stated honestly: as written, this ritual stops at the version
   guard and does NOT exercise the OIDC handshake it was written to prove.** That
   is a real gap, not a solved problem — it is tracked as `DEF-449`. Closing it
   needs an upload target that cannot burn the namespace (TestPyPI via
   `repository-url`, or a re-publish of an already-published version), which is a
   design decision, not a text fix. Do not "fix" it by aligning the versions.

4. **Watch the publish workflow.**
   ```bash
   gh run watch
   ```
   ⚠ **Expect the run to stop RED at "Verify tag matches the built version",
   before the OIDC step. That red is the PASS.** It confirms the guard that
   stands between this rehearsal and a real upload is live.

   It does NOT reach `pypa/gh-action-pypi-publish`, and it does NOT prove the
   trusted-publisher binding — the earlier claim that the upload "will fail
   PyPI-side" was wrong: `0.0.0a0` is a valid PEP 440 version, `espalier-harness`
   does not exist on PyPI, and a pending trusted publisher CREATES the project on
   first use.

   **If the run gets PAST the version guard, abort the workflow immediately** —
   the only thing that could let it through is a `pyproject.toml` that agrees
   with the throwaway tag, which is the withdrawn step 3 warns about.
5. **Clean up the throwaway tag and branch.**
   ```bash
   git tag -d v0.0.0a0
   git push origin :refs/tags/v0.0.0a0
   git checkout main
   git branch -D publish-dry-run
   git push origin :publish-dry-run
   ```
6. **Proceed to the real tag-push.** From this point, pushing the
   release tag from the "Tag decision" section near the top of this
   file triggers the real publish.

## First publish (one-time) — seeds a NEW public repo

> **Executed 2026-09-25 (`v0.8.0b1`; root commit `d00f6de4`). You are reading this
> section inside the repository it created.** It stays as the record of that ritual
> and the recipe for any re-seed, not as a live instruction. Throughout it, "this
> tree" and "the development tree" name the private tree that existed before the
> seed, now the read-only archive `Mike-Byrne-AI/espalier_harness_dev_private`;
> "the NEW public repo" is this one. Development moved here under `DEC-31`
> (note added 2026-09-26).
>
> ⚠ **`DEC-25` (2026-08-20) retired the "flip this repo public" model, and
> `DEC-31` (2026-09-07) decided where development goes afterwards; this section
> is the executable form of both.** This tree's history is **never** published.
> The public artifact is a **new** repository whose initial commit is the output
> of `scripts/build_release_archive.py` plus the seeded memory file, followed by
> one re-pin commit (step 5), so the seeded history is TWO commits. Under `DEC-31` this tree renames away
> and becomes a read-only private archive that hosts the record branch through
> a second remote; development moves into the public repo, and the forward-work
> tracker (`task-packs/FORWARD_LEDGER.md`, its probes file and the active packs)
> ships with it.
>
> Reasons, measurements and the evidence behind every warning below live in
> the `DEC-25` memo, `memory/publish-from-a-generated-public-repo.md`, kept in the
> maintainers' archive (`Mike-Byrne-AI/espalier_harness_dev_private`) by that
> decision's own rule — not in this repository, not deployed by `init`. **That file holds the why; this
> section holds the steps.** Cleanup-in-place is unavailable rather than merely
> undesirable — see it for why only a fresh repo achieves a rewrite.

### ⚠ The one-way door is `origin` — not any command in this section

The irreversible act is **step 4 creating the public repo at the slug this
tree's `origin` already points at**. From that moment an un-repointed `origin`
resolves to the **public** repository, and a routine `git push` transfers the
full private history plus the 19 files `.gitattributes` withheld at the seed (2026-09-24; eighteen once
`ESPALIER_MEMORY.md` returned in PR #3; thirteen since 2026-09-26, when the two release
docs and three review scaffolds returned: 19 − 1 − 2 − 3) —
`export-ignore` binds `git archive`, never `git push`, and no local guard
inspects a push destination.

Step 3 therefore repoints `origin` **before** step 4 exists. **Do not reorder
them, and do not skip step 3 because the rename redirect keeps `origin` working
— that it keeps working is precisely the hazard.**

Sequence (each step verifies the previous):

1. **Confirm the working tree is at the cut state** —
   ```bash
   git log -1 --oneline           # expect: a handoff or docs commit atop the release commit -- /handoff lands after it by construction (DEC-31)
   grep -m1 '^version = ' pyproject.toml   # expect: the cut version; no v-tag exists here and none is created here -- step 7 tags the SEEDED tree
   git status                     # expect: clean
   python3 -m espalier.cli freshness check --critical-only; echo "RC=$?"
   python3 scripts/check_handoff_landing.py --skip-tests --skip-trailer --skip-shape --skip-owed --skip-keys
                                  # expect: clean + "local arm: N pattern(s)" -- the codename gate's
                                  # local terms are armed on THIS tree (memory/local-codename-arm.md)
   python3 -m pytest tests/test_no_internal_codenames.py -q   # expect: green with the arm on
   ```
   ⚠ **`critical` must be 0.** `freshness` is one of the required status checks
   step 4 sets. On the public repo's first push the guard runs scoped to the
   re-pin commit's one file (the seeded history is two commits, so `HEAD~1`
   resolves); it took the fail-safe path when the seed was a single commit.
   Either way any critical fragment trips exit 2 there. The
   fragment cohort shares one pin date and goes stale on a known clock — re-pin
   before seeding if this returns anything.

2. **Build the public tree and read what it actually contains.**
   ```bash
   python3 scripts/build_release_archive.py
   ```
   Emits `dist/espalier-harness-<version>-release.zip`, members prefixed
   `espalier-harness-<version>/`. Read the printed counts rather than assuming.
   *Driven 2026-09-02 at v0.8.0a13:* `Included files: 1006`. Do not pin the
   `transient` count — it moves with whatever build output happens to exist.

   ⚠ **The forward-work tracker must be in the zip** (`DEC-31`: the public repo
   is the development tree from the seed on). Read the listing; do not assume:
   ```bash
   unzip -l dist/espalier-harness-*-release.zip | grep -c 'task-packs/FORWARD_LEDGER.md'   # expect: 1
   unzip -l dist/espalier-harness-*-release.zip | grep -c 'task-packs/LEDGER_PROBES.json'  # expect: 1
   ```

   ⚠ **If `ESPALIER_MEMORY.md` or either release doc appears in the zip, STOP** —
   the two exclusion boundaries (classify and export-ignore) have disagreed, which
   the `DEC-25` memo defines as a defect.

   ⚠ **Hand-check the citation gate here; a green suite is not the evidence.**
   Deleting the withheld set makes `is_release_export` return True, which
   auto-skips every `full_tree` item — a scrub-and-publish route then reports
   green *because the gate switched itself off* (`docs/FAILURE_MODES.md` §5).
   Re-derive the gated count yourself; do not trust a number this file asserts:
   ```bash
   python3 -m pytest -m full_tree --collect-only -q | tail -1
   ```

3. **Rename this repo away, and repoint `origin` in the same sitting.**
   Settings → General → Repository name → `espalier_harness_dev_private`.
   ```bash
   find "$HOME" -maxdepth 14 -path '*/.git/config' -print0 2>/dev/null \
     | xargs -0 grep -l 'Mike-Byrne-AI/espalier-harness'   # null-delimited: a path with a space cannot hide a clone; grep errors stay loud
   git remote set-url origin \
     https://github.com/Mike-Byrne-AI/espalier_harness_dev_private.git
   git remote -v    # expect: espalier_harness_dev_private, NOT espalier-harness
   ```
   ⚠⚠ **`origin` in THIS tree is not the only door — derive the list, never
   trust a written one.** Every other clone on the machine has its own
   `.git/config`, and `set-url` here does not reach them. Run the `find` **before**
   the `set-url` to see the population and **after** to require **zero** lines.
   For each extra clone: `git -C <path> remote set-url origin <private-url>`, or
   `remote remove origin` if it is an archive you never push from. A *linked*
   worktree (its `.git` is a small `gitdir:` file) shares this config and needs
   nothing. Measured 2026-09-02: three configs matched, two of them full clones.

   ⚠ Between this step and step 4 the old slug redirects to the private repo, so
   `pyproject.toml`'s five project URLs are briefly wrong. **Do not upload to
   PyPI inside that window** — release metadata is immutable per version.

   ⚠ **From step 4 on, the old slug names the PUBLIC repository, and nothing
   mechanical reads a push destination** — no speed-bump checkpoint looks at
   the remote (measured 2026-09-24, Round 12). Read `git remote -v` before every
   `git push` in this sitting, in every checkout you push from, and push nothing
   by hand from the development tree after this step.

4. **Create the new public repository at the inherited slug** (browser,
   one-time) — `Mike-Byrne-AI/espalier-harness`, public.

   The slug is inherited by design: 89 occurrences across 21 files (2026-09-24) inside the
   generated artifact hardcode it, so a different name 404s every one of them
   and inheriting costs zero source edits.

   ⚠ **Split this step around the seed.** Create the repo now with everything
   below EXCEPT branch protection, required status checks and tag protection —
   all three have step 5 as their precondition:
   - GitHub lists a required check name only after it has seen it report, so the
     eight names are unselectable until step 5's push.
   - "Require PR review for direct pushes" cannot be satisfied by the seed — you
     cannot open a PR against a repo with no base branch, so step 5 **must** be a
     direct push.
   - Tag protection on `v*` blocks the delete-and-re-push the
     [First-time verification ritual](#first-time-verification-ritual) performs.

   Come back and apply those three immediately after step 5's push lands.

   Repo settings to enable up front:
   - Default branch: `main` (matches the generated tree's default).
   - Branch protection on `main`: require status checks, require
     PR review for direct pushes, require the branch to be up to date
     before merging (on since 2026-09-27: a trailing pull request then
     waits for `/ship` step 5's catch-up and re-bind), disallow
     force-push. **(after step 5)**
   - Required status checks: `verify`, `benchmark`, `freshness`,
     `test (3.10)`, `test (3.11)`, `test (3.12)`, `test (3.13)`,
     `test (3.14)`. **(after step 5)**
   - Those are **check-run** names, which GitHub derives from **jobs** — not
     from the workflow, not from its filename, and not from a matrix job's bare
     id. A required check that never reports does not fail the PR; it parks it
     on *"Expected — waiting for status to be reported"* with no route to merge
     but deleting the rule. Pinned by `tests/test_required_status_checks.py`;
     see the [CI tier mapping](#ci-tier-mapping) above.
   - Tag protection on `v*` (prevents accidental tag delete / overwrite once
     published). **(after step 5)**
   - **Actions → General: grant the workflow token the pull-request permission
     `refresh-externals.yml` needs** (generalised 2026-09-26). It carries the
     artifact's only live cron and opens a PR on drift; a new repository does not
     grant that by default, so without it the job reds on every scheduled run — the
     "trains reviewers to ignore red CI" failure `end-to-end-bench.yml` names.
   - Issues + Discussions: enabled.
   - Security advisories: enabled (links to SECURITY.md).
   - **Private vulnerability reporting: enabled** (Settings → Code security).
     `SECURITY.md`'s preferred `Report a vulnerability` link 404s until it is on.
     Draft advisories are always available to maintainers, so this is a separate
     switch from the bullet above, not a restatement.

     ⚠ **Enable it on the NEW public repo** — doing it on the development tree
     accomplishes nothing, since `SECURITY.md` and the issue-template
     `contact_link` both point at the public slug.

     1. Go to `https://github.com/Mike-Byrne-AI/espalier-harness/settings/security_analysis`
     2. Find **Private vulnerability reporting** → **Enable**.
     3. Confirm the **Security** tab now shows a `Report a vulnerability` button.
     4. Confirm an admin or security manager receives security alert email.

     Do not announce (step 10) until this is complete. `run_cleanliness_gate`
     catches most ways `SECURITY.md` drifts into public-issue routing, but it
     cannot detect whether the GitHub flow is enabled — only a human can.

5. **Seed the new repo from the built artifact.** Unpack outside this tree so
   nothing can be committed from the wrong working directory.
   ```bash
   DEV=$(git rev-parse --show-toplevel)
   ZIP=$(ls -t "$DEV"/dist/espalier-harness-*-release.zip | head -1)
   echo "$ZIP"      # confirm: this is the archive step 2 produced
   ```
   ```bash
   WORK=$(mktemp -d) && cd "$WORK"
   unzip -q "$ZIP"
   cd espalier-harness-*/ && pwd    # confirm you are OUTSIDE the dev tree
   git init -q .
   ```
   ⚠ **Nothing is staged yet, and that ordering IS the fix.** The first cut of
   this step ran `git add -A` here — before the two edits below — and then
   `git commit`, which commits the **index**. Both edits would have been on disk
   and in neither the index nor the commit, so the public repo's very first
   commit would have shipped the narrowed CI gates: every required check
   dispatch-only, on a repo whose branch protection (step 4) requires them. Stage
   **after** the tree is finished, never before.

   ⚠ **Undo the CI cost gates HERE, in the unpacked tree, before the commit —
   not in the development tree** (`DEF-633`). Under `DEC-31` the development
   tree stays private but stops being where development happens: after the seed
   it is a read-only archive whose workflows are never turned back on, so the
   gates in it are never undone. `COST GATE` alone finds 4 of the 6 sites and
   would leave both workflows dispatch-only; the crons carry a different marker:
   ```bash
   grep -rnE "COST GATE|DISPATCH-ONLY UNTIL THIS REPO IS PUBLIC" .github/workflows/ tests/README.md
   ```
   Undo every hit (the `tests/README.md` paragraph describes the narrowed arrangement
   in prose: rewrite it to the restored one). Then prove the RESULT, not just the markers — the
   required-status-check test cannot see this tree (the doc it derives the
   names from does not ship). Run it HERE, in the unpacked tree, borrowing the
   test module and this checklist from `$DEV`:
   ```bash
   python3 -c "import sys, pathlib; sys.path.insert(0, '$DEV/tests'); import test_required_status_checks as t; t.WORKFLOW_DIR = pathlib.Path('.github/workflows').resolve(); assert (t.WORKFLOW_DIR / 'test.yml').exists(), t.WORKFLOW_DIR; assert '$DEV' not in str(t.WORKFLOW_DIR), 'run this in the UNPACKED tree, not the development tree'; r, _ = t._build_resolver(); need = t._instructed_checks(pathlib.Path('$DEV/docs/RELEASE_CHECKLIST.md').read_text(encoding='utf-8')); print(sorted(n for n in need if n not in r or not r[n].on_pr))"   # expect: []
   ```
   A name printed here is a required check that will never report on the public
   repository's first pull request; fix the workflow before the commit. (Driven
   2026-09-24: renaming one job in a scratch copy prints that job's name.)

   **Only now stage the finished tree, check the ordering, and commit.** The
   suite runs AFTER the commit — the order `scripts/final_release_matrix.py`
   stage 02 drives (`DEF-670`): with 0 tracked paths three shipped node ids raise
   `GitAnswerUnavailable`, so a suite run before the seed reds on the oracle,
   not on the tree.
   ```bash
   cp examples/ESPALIER_MEMORY.template.md ESPALIER_MEMORY.md   # the public tree is the development tree from here (DEC-31): seed its memory
   python3 -c "import pathlib; p = pathlib.Path('ESPALIER_MEMORY.md'); t = p.read_text(encoding='utf-8'); t = t.replace('# your-repo — Project Memory', '# espalier-harness — Project Memory', 1).replace('**Repo:** your-repo', '**Repo:** espalier-harness', 1); assert 'your-repo' not in t, 'template header not rewritten -- the template changed'; p.write_text(t, encoding='utf-8')"
   python3 -c "import pathlib; from espalier.surface_contract import is_release_export; print(is_release_export(pathlib.Path('.').resolve()))"   # expect: True -- the memory file is not a sentinel (DEC-31; pinned by tests/test_export_guard.py::TestIsReleaseExport)
   head -5 ESPALIER_MEMORY.md                        # expect: the espalier-harness header, not your-repo
   git add -A
   git add -f examples/ESPALIER_MEMORY.template.md ESPALIER_MEMORY.md   # NOT optional -- see below; the seeded file matches the same ignore line
   git status --porcelain --ignored | grep '^!!'     # expect: NO output
   git diff --name-only                              # expect: NO output (nothing edited after staging)
   git diff --cached --name-only | wc -l             # expect: the step-2 count + 1 (the seeded memory file)
   git diff --cached --name-only task-packs/ | wc -l # expect: >= 2 (the ledger and its probes file; DEC-31)
   VER=$(basename "$ZIP"); VER=${VER#espalier-harness-}; VER=${VER%-release.zip}
   echo "$VER"        # confirm: matches [project].version in pyproject.toml
   git config --local user.name "<the identity the public tree shows>"    # DECIDE it: the seed commit
   git config --local user.email "<its address>"                          # otherwise carries whatever this shell's git config holds
   git var GIT_COMMITTER_IDENT                                            # expect: the name and address you just chose -- what git will USE,
                                                                          # after any GIT_AUTHOR_*/GIT_COMMITTER_* the environment carries
   git branch -M main
   git commit -qm "espalier-harness v$VER"
   ```
   ⚠ **`git add -A` silently drops `examples/ESPALIER_MEMORY.template.md` and
   the seeded `ESPALIER_MEMORY.md` with it** —
   `.gitignore`'s `espalier_*.md` matches it under `core.ignorecase=true`, with
   no error. Driven 2026-09-02 at a13: 1,006 on disk, `git add -A` staged 1,005; with
   the seeded memory file (2026-09-24) the same rule drops two, and the `-f`
   restores both. The `--ignored` line is the proof — run it, do not assume.

   `git diff --name-only` is the ordering check: any output means a file was
   edited after staging, and the commit would have left it behind. (A bare
   `git status --porcelain` stood here before the commit and always had output —
   the untracked tree itself — so it checked nothing.)

   ⚠ **Run the suite here, on the committed tree. This tree IS the public repo.**
   ```bash
   python3 -m pytest -q -m "not slow" -p no:cacheprovider   # expect: 0 failed
   git status --porcelain                                   # expect: NO output (the suite left nothing behind)
   # If there IS output: do NOT stage it and do NOT push. Record the paths and
   # decide at M3-A -- an amend here breaks "initial commit == archive output plus the seeded memory file"
   # and the file-count expectation above, and `git clean` destroys copied-in state.
   ```
   **Driven 2026-09-02 and it was RED** (`3 failed` on a `not slow` selection of
   about 5,500 then; the selection is about 8,600 at 0.8.0b1) on three
   self-expiry arms that fire only in the export. Until 2026-09-13
   `scripts/final_release_matrix.py` structurally could not see them — it ran
   pytest on the extract with no `.git`, where they skipped fail-open (and,
   since the test tree's git oracle landed, the git-asking arms failed loudly
   instead). Stage 02 now seeds git in the extract before the suite (`init`,
   `add -A`, a force-add of whatever the archive's own `.gitignore` withholds,
   one commit, and a tracked-equals-on-disk check), so the matrix sees what
   this manual run sees. Keep this run: it is the second witness, and an
   unfixed red here is a red `test (3.10)` required check on the public repo's
   first push. The porcelain line after it is the matrix's tracked-equals-on-disk
   check in prose. ⚠ *Verify at M3:* if the suite legitimately writes runtime
   files on the seeded tree, this line must name the expected droppings instead
   of expecting none — M3-A's stage 02 log is where that is measured; do not
   guess it here.

⚠ **The `not slow` slice is NOT the witness -- run the WHOLE suite here.** Driven 2026-09-25: the slice was green on the seeded tree and the public repository's first whole-suite CI runs still found two dev-tree facts asserted on a seeded one -- the recall corpus's reach pin and the changelog's alpha-mention check against a one-tag history. Both live in modules `tests/conftest.py::_SLOW_FILES` names, so no `not slow` selection can reach them, and neither stage 02 nor `scripts/archive_probe.py` sees them: the seed is a third tree shape, with a seeded memory file, a two-commit history and one tag. Run `python3 -m pytest -q -p no:cacheprovider` and read it before the push.


   **Then re-pin freshness as the seeded repository's second commit.** Every
   fragment in the archived `.espalier/freshness.json` pins a commit of the
   development tree, which this history does not contain, and the scanner reads
   an unknown sha as zero drift forever (the commit axis goes dead while the
   calendar axis keeps ticking — Round 12, 2026-09-24). Re-pin against the seed
   commit before anything is pushed; the cohort clock restarts, which is fine:
   ```bash
   python3 -m espalier.cli freshness pin --all
   python3 -m espalier.cli freshness check --critical-only; echo "RC=$?"   # expect: RC=0, every fragment fresh
   git add .espalier/freshness.json && git commit -qm "chore: pin freshness to the seeded history"
   git log --oneline | wc -l                                              # expect: 2
   ```

   Then add both remotes and push `main` to the public one:
   ```bash
   GITHUB_EVENT_NAME=push python3 tools/cc/ci_guard.py; echo "RC=$?"
   git remote add origin https://github.com/Mike-Byrne-AI/espalier-harness.git
   git remote add archive https://github.com/Mike-Byrne-AI/espalier_harness_dev_private.git
   git config --local espalier.recordRemote archive   # the record branch pushes to the archive, never to origin (DEC-31)
   git remote -v                     # confirm: origin = espalier-harness (PUBLIC); archive = the renamed private tree
   git push -u origin main
   ```
   `archive` is the second remote `DEC-31` names: the renamed private tree hosts
   the record branch, and `scripts/handoff_mechanics.py after-goal` reads the
   `espalier.recordRemote` key (checkout-local, so it is not cloned) to push the
   record there; unset, it pushes to `origin`, which on the public checkout would
   publish the record. Set it in this sitting, before the first handoff.
   `git branch -M main` is defensive — a fresh `git init` takes its branch from
   `init.defaultBranch`, and step 4 protects `main`. This `git remote add` is
   correct **because the tree it runs in is the fresh unpacked one**; running it
   in the development tree is the defect this section was rewritten to remove.

   **The harness-guard approval marker is a non-event here** — on the seeded
   repo `ci_guard.py` finds no base ref and diffs against the root commit (the
   seed); with the re-pin as the second commit that diff is the one freshness
   file. Driven on the single-commit shape: two WARN lines, `RC=0`; read the
   lines again on the two-commit shape and record them here. The unconditional kill-switch
   and governance scans still run, so an `RC=2` is real — read the findings, and
   read them **before** `git push`, which is why that line sits above the push in
   the block rather than in this note. It was below it in the first cut: a
   "check before pushing" printed thirteen lines after the push had happened.

   **If you enabled branch protection at step 4** so the seed lands via a PR, the
   marker must be in the **PR title** — `ci_guard.py` routes PR events to
   `PR_TITLE`, not the commit message.

6. **Claim the PyPI namespace and configure the `pypi` environment —
   BEFORE any tag reaches the new origin.** Follow
   [Trusted-publisher setup for PyPI](#trusted-publisher-setup-for-pypi)
   above: namespace probe, maintainer-side setup, GH Environment
   configuration. The trusted-publisher OIDC flow needs no API token —
   PyPI verifies the workflow's GitHub identity via the `publisher`
   claim — but the project must EXIST for that claim to bind.

   ⚠ **Configure the environment on the NEW public repo —
   `https://github.com/Mike-Byrne-AI/espalier-harness/settings/environments`.**
   Doing it on the development tree fails *open*: GitHub creates an environment
   implicitly on first reference, so `publish.yml` still resolves and the publish
   **succeeds** with the required reviewer and wait timer silently absent.
   Confirm Environments → `pypi` shows **1 required reviewer and a 5-minute wait
   timer**.

   ⚠ **Ordering is the whole point of this step.** `publish.yml` fires on the tag
   push in step 7, not on the release in step 8 (`on: push: tags: ['v*']`). If
   the namespace is unclaimed when that tag lands, the first publish runs against
   a project that does not exist and the version is burned.

7. **Tag HEAD of the seeded tree (the re-pin commit) and push the tag BY ITSELF.**
   ```bash
   pwd && git remote -v && git log --oneline -2
   # expect: the SEEDED tree; origin = espalier-harness (PUBLIC); TWO commits,
   # HEAD = "chore: pin freshness to the seeded history". The tag goes on HEAD --
   # the seed commit's freshness manifest still pins the development tree's shas.
   # $WORK is a mktemp dir -- purged on reboot and after ~3 days idle. If it is
   # gone, do NOT paste this in the dev tree; clone the public repo instead:
   #   git clone https://github.com/Mike-Byrne-AI/espalier-harness.git && cd espalier-harness
   #   git remote add archive https://github.com/Mike-Byrne-AI/espalier_harness_dev_private.git
   #   git config --local espalier.recordRemote archive   # every fresh clone starts unset; the handoff refuses until this is set
   #   git config --local user.name "<the identity the public tree shows>"   # a fresh clone has no local identity either, and the
   #   git config --local user.email "<its address>"                         # annotated tag below records a TAGGER -- the same door as step 5
   #   git var GIT_COMMITTER_IDENT                                           # expect: the identity you chose at step 5
   # Re-derive VER from THIS tree. A fresh shell -- and the fresh clone the line
   # above sends you to -- has no $VER, and `git tag -a "v$VER"` then creates a
   # tag named literally `v`, pushes it, and the old verification line
   # (`grep "refs/tags/v$VER"`) MATCHED it, so the step green-lit its own
   # malformed tag. `publish.yml` fires on that push.
   VER=$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)
   [ -n "$VER" ] && echo "v$VER" || echo "VER IS EMPTY -- STOP, do not tag"
   git tag -a "v$VER" -m "v$VER: <one-line summary>"
   git push origin "v$VER"
   git ls-remote --tags origin | grep "refs/tags/v$VER$"  # anchored: this tag only
   ```
   Annotate the tag — the object type must be `tag`, not `commit`.
   **Do not use `--follow-tags`, and do not use `--tags`.** GitHub creates no tag
   events when more than three tags are pushed at once, so a bulk push suppresses
   the `push` event for **every** tag, `publish.yml` never fires, and the release
   silently does not publish while the push reports success. The generated repo
   starts with zero tags, so this is precautionary here and live on every later
   release.

   ⚠ **`pre-pack-TP-104` is a KEEP.** Under `DEC-31` what leaves this tree is
   the record branch (pushed to the record remote by the handoff's after-goal
   step), never `main` and never a tag, so the old "delete stray lightweight
   tags" sweep is retired. If you
   ever run one for local hygiene: that tag is lightweight but not a stray — it
   is the fixture `tests/test_sister_site_probe_regression.py` checks out, and
   deleting it does not RED that test (it skips when absent), so the coverage
   disappears silently.

⚠ **If a day-one fix lands between the seed and the tag, the tag goes on the FIX commit, not on the re-pin commit.** `publish.yml` runs the readiness gate's near-full suite AT the tag, so a tag that predates the fix reds there. Driven 2026-09-25: the seeded repository's first whole-suite runs reddened on two dev-tree facts, the fix merged through a pull request, and the tag went on that merge commit -- three commits in, not the two the `git log --oneline -2` expectation above prints. Read that expectation as *HEAD carries the freshness re-pin and every fix since*, and re-read `git log` before `git tag -a`.


8. **Create the GitHub release for the cut tag** —
   ```bash
   gh release create "v$VER" --notes-from-tag
   ```
   This MUST follow the tag push in step 7. See
   [Recovery](#recovery-gh-release-create-ran-before-tags-pushed)
   below for the failure mode if you reverse the order.

9. **Post-publish smoke** — verify the published artifact installs cleanly from a
   fresh environment with no link to the dev checkout.
   ```bash
   python3 -m venv /tmp/espalier-smoke && \
     /tmp/espalier-smoke/bin/pip install espalier-harness && \
     /tmp/espalier-smoke/bin/espalier --version && \
     /tmp/espalier-smoke/bin/espalier doctor /tmp 2>&1 | tail -5
   rm -rf /tmp/espalier-smoke
   ```

   - **Verify the build-provenance attestation.** `publish.yml` emits a signed
     SLSA attestation before upload, so a broken attest fails the job. This
     sub-step proves the other half — that the artifact a **consumer** downloads
     carries it. `gh attestation verify` does not accept a PyPI URL, so fetch
     locally first; `gh auth` must be live against the repo.
     ```bash
     pip download --no-deps --only-binary=:all: espalier-harness -d /tmp/att
     gh attestation verify /tmp/att/espalier_harness-*.whl \
       --repo Mike-Byrne-AI/espalier-harness
     rm -rf /tmp/att
     ```

10. **Announce only after step 9 is green** — README + QUICKSTART already
    describe the project; an HN / Reddit / social post can point at the repo with
    confidence once the install path is verified end-to-end.

This sequence runs once. Subsequent releases follow the recurring
[Release procedure](#release-procedure-stable-direct-default) below (no repo
creation, no PyPI namespace claim), executed against the generated public repo.
**The development tree is never a push target for a release.**

⚠ **If a later release re-seeds from the archive, the step-5 cost-gate undo does
not survive it and nothing reds when it reverts** — the check runs still report,
they just stop doing work. Re-apply the step-5 grep on any reseed. No cost gate remains
in this tree (2026-09-26); the archive's workflows still carry them.

## Release procedure (stable-direct, default)

1. **Bump version surfaces** — `pyproject.toml`,
   `espalier/__init__.__version__`, `bench/RESULTS.md` (regenerate via
   `python bench/run_benchmark.py --update-canonical`), `CHANGELOG.md`
   section fold (move `[Unreleased]` content into `[<new-version>] - <date>`),
   and CHANGELOG footer link (add a new row in monotonic newest-first
   position — enforced by `tests/test_changelog_footer.py`).
   The authoritative list of files carrying the version literal is
   `espalier/version_surfaces.py::VERSION_SURFACES`; `scripts/release_check.py`
   and `tests/test_version_surfaces_parity.py` both consume it, so any
   surface added there is enforced everywhere at once.

   `cc/PACK_MANIFEST.txt`'s `# espalier-version:` stamp is deliberately NOT on
   that roster: it records the engine that deployed the surface, so an adopter's
   copy legitimately lags a newly installed engine until `upgrade --execute`.
   On this tree re-render it in the release commit, or `espalier upgrade .`
   reads the self-host deployment as stale on a bump that deployed nothing:
   `python -c "from pathlib import Path; from espalier.render_surface import render_pack_manifest; Path('cc/PACK_MANIFEST.txt').write_text(render_pack_manifest(Path('.')), encoding='utf-8')"`.

   **CHANGELOG fold (detail).** `[Unreleased]` is large at cut time — it
   accumulates every dev bullet between releases — so fold it in two pieces.
   (The in-file `## [0.6.6-folded-from-unreleased]` block that once modelled
   this was condensed into the `Pre-0.8 alpha` prose for the public launch on
   2026-07-06; the record now lives off the tracked tree, below.)
   - **Adopter-facing release section** — create `## [<new-version>] — <date>`
     with terse, user-facing bullets. Strip the dev-process vocabulary that
     means nothing to an adopter: `earn-the-red`, `deny-predicate`, `ZERO …`,
     `convergence`, and the per-TP "Full suite NNNN passed" narration.
   - **Verbatim record, off the public surface** — move the original
     `[Unreleased]` prose, unedited, to
     `task-packs/Done/CHANGELOG_archive_<date>.md` under a
     `## [<new-version>-folded-from-unreleased]` heading, with a short header
     saying what it is. `task-packs/Done/` is gitignored on `main` and carried
     by the record branch, so the record never reaches the seeded repository,
     the sdist or the wheel (DEC-31's boundary), and no internal-doc roster,
     MANIFEST or export-ignore row is owed; `scripts/check_handoff_landing.py`
     reds on the operator's tree while a parked record is not yet on the
     `record` ref (`python3 scripts/record_snapshot.py` puts it there, handoff
     step 7b). The 2026-07-05 curation parked the
     earlier history there as `CHANGELOG_archive_20260705.md`; the 0.8.0b1 cut
     followed it (`CHANGELOG_archive_20260924.md`), as did the 0.8.0b2 cut
     (`CHANGELOG_archive_20260927.md`), after a first attempt at b1 kept
     the record inside this file, which would have shipped 7,600 lines of
     development narration on the page a reader scrolls after the README.
     The public section's closing sentence says the record is kept in the
     maintainers' tree; it names no path an adopter does not receive.
   - ⚠ **THE FOLD REDS THE SUITE BY DESIGN — three edits move in the fold
     commit: the new dated section, the `pyproject.toml` version bump, and the
     tripwire's marker coming off.** `TestVersionConsistency::test_unreleased_section_is_empty` is
     `@pytest.mark.xfail(strict=True)` under `xfail_strict = true`: it is an
     inverted tripwire, not a guardrail, and the moment the fold succeeds it
     XPASSes and fails the suite. That is deliberate — it forces the marker off
     once the gate can pass honestly — but it means the fold commit must ALSO
     remove that `xfail` marker (the third edit).
     `tests/test_changelog_canon.py::TestAgainstTheLiveChangelog` needs no touch:
     its two live-`[Unreleased]` assertions are conditional and skip on an
     emptied section. The marker comes BACK with the first
     post-cut `[Unreleased]` entry: re-arm `@pytest.mark.xfail(strict=True, reason=...)`
     on the test rather than emptying the section (the assert message says the same;
     it last came off at the 0.8.0b2 cut, 2026-09-27). Re-point any older section
     that still says "See [Unreleased]" at the new dated section (the a13 entry
     did until 2026-09-24). Note the test counts **substantive
     entries** (bullets, `###`/`####` subheadings, `**Bold**` group labels via
     `espalier.changelog`), not `###` — the `###`-only form is the DEF-591
     blindness and no longer exists anywhere.
   - **Guardrails (test-enforced; re-derive the `[Unreleased]` line span
     from current bytes — do not trust a stale count):** the next
     `## [` header is a SemVer release (`TestChangelogStructure`); footer
     compare-links stay monotonic newest-first (`tests/test_changelog_footer.py`);
     every `vX.Y.Z*` mention names a real tag (`tests/test_version_truth.py`,
     `TestVersionConsistency::test_changelog_body_v8_alpha_mentions_match_pyproject_or_tags`).
     Do NOT edit already-released `## [X.Y.ZaN]` sections or an archive
     file's `-folded-from-unreleased` block.
2. **Run the pre-tag gate** — `python scripts/release_check.py` must
   show all gates green (`N passed, M skipped`; the exact counts
   drift as gates are added). For high-confidence releases also run
   `python scripts/final_release_matrix.py` (Tier 3).
3. **Commit the version bump + CHANGELOG fold on a release branch** —
   `git commit -m "release: vX.Y.Z — <headline, at most 72 characters>"` (the
   narrative goes in the body; the landing check reds a longer subject). Then, still on
   the branch: re-pin the freshness cohort as its own commit (the "Re-pin the
   cohort at the cut" section above; the pin refuses over uncommitted bounds,
   which is why it follows the fold commit), push the branch and open the
   pull request (root `CLAUDE.md` Core Rule 10). ⚠ A release diff touches a
   CI-gated path nearly every time (`.github/workflows/` at least; the set is
   the CI guard's `PROTECTED_PREFIXES` and `PROTECTED_FILES`), so the PR **title** carries
   `HARNESS-UPDATE-APPROVED@<head7>` bound to the FINAL head: the ship driver
   binds it when it creates the pull request, and a push after that needs
   the driver's `rebind` verb — the `verify` check reads the title as it is
   at check time, so the re-bind clears the red whichever of the push's run
   and the edit's run GitHub kept. Arm auto-merge with a merge commit and
   wait for the merge. `/ship` runs this step's push, pull request, marker
   binding and auto-merge through the ship driver (one push, the marker bound
   at creation), and `/ship --release vX.Y.Z` — the driver's `release` verb,
   which checks the tag against the tree's version, the merge, and the tag's
   absence before anything leaves the machine — continues with steps 4 to 8
   once the merge lands.
4. **Tag the merge commit** — from the lane branch (the driver names the
   pull request from it), the ship driver's `release vX.Y.Z` verb does
   steps 4 to 6: it fetches the merge commit, tags it, pushes that one tag
   and creates the release; switch to `main` after, not before. By hand
   instead: `git switch main && git pull --ff-only origin main`, then
   `git tag -a vX.Y.Z -m "vX.Y.Z: <one-line>"`.
   Always annotated (`-a`); lightweight tags don't propagate via
   `--follow-tags` in step 5. Never tag the branch commit before the merge:
   `publish.yml` fires on any `v*` tag push with no on-`main` check, and a
   PyPI upload is immutable.
5. **Push the named tag** — under the pull-request flow `main` is already on
   origin, so this step is `git push origin vX.Y.Z` alone. The measurements
   below apply when a branch push carries tags (`--follow-tags` pushes
   annotated tags pointing at commits on the pushed branch). Caveats:
   - Lightweight (non-annotated) tags don't propagate via
     `--follow-tags`. Step 4 uses `git tag -a`, so the standard path
     is covered.
   - Side-branch tags (e.g., a hotfix branch in the Hotfix-cadence
     section below) are NOT picked up by `--follow-tags` on a main
     push. Name those tags explicitly — never `--tags`.
   ⚠ **Never `git push --tags` here.** GitHub creates no tag events when
     more than three tags are pushed at once, and this machine carries many
     local `v*` tags origin does not have. A bulk push therefore succeeds,
     `publish.yml` never fires, and the release silently does not publish —
     see the "Recovery: the tag is on origin but nothing published" section
     below. Name the tags you mean.
   ⚠ **`--follow-tags` is NOT the safe sibling of `--tags` — measure before you
     trust it.** It pushes every annotated tag reachable from the branch, and on
     the private development machine that was **27** of them in one push (2026-09-24),
     which suppresses the tag events exactly as `--tags` would; on the public repository
     one tag, `v0.8.0b1`, is reachable from `HEAD` (2026-09-26), and the calibration tags
     that point into private history are never pushed. Measure your own exposure first;
     if the count is above three, the branch and the tag must go separately:
   ```bash
   # 1. ALWAYS measure. Anything above three suppresses the events.
   #    `2>&1` is LOAD-BEARING: git writes the `[new tag]` lines to STDERR, so
   #    piping stdout alone prints 0 at ANY tag count -- which would send you
   #    straight to branch 2a and the bulk push this whole section forbids.
   git push --dry-run --follow-tags origin main 2>&1 | grep -c 'new tag'
   # 2a. Count is 0: the branch carries no pending tags, so this is safe.
   git push origin main --follow-tags
   # 2b. Count is 1..3: still under the limit, also safe.
   # 2c. Count is 4+: push the branch WITHOUT tags, then name the release tag.
   git push origin main
   git push origin vX.Y.Z
   ```
6. **Verify the tag is on origin** —
   `git ls-remote --tags origin | grep vX.Y.Z` must show the SHA.
7. **Create the GitHub release** —
   ```bash
   gh release create vX.Y.Z --notes-from-tag
   # OR with explicit notes file:
   # gh release create vX.Y.Z --notes-file release-notes-vX.Y.Z.md
   ```
8. **Watch the publish workflow** — `gh run watch`. Confirms the
   environment-approval gate fires and the upload completes.
9. **Verify what was published, from PyPI itself** — the GitHub release page
   carries no assets (the release workflow keeps its build as a run artifact
   only; neither 0.8.0b1 nor 0.8.0b2 had one), so the published files are the
   ones PyPI serves. PyPI's JSON lists a version a minute or so before the
   simple index serves it, so a `pip download` that says "no matching
   distribution" right after the upload is lag, not a failed publish.
   ```bash
   pip download "espalier-harness==X.Y.Z" --no-deps --only-binary :all: -d dist-pypi   # the wheel
   pip download "espalier-harness==X.Y.Z" --no-deps --no-binary :all: -d dist-pypi     # the sdist
   gh attestation verify dist-pypi/espalier_harness-X.Y.Z-py3-none-any.whl --repo Mike-Byrne-AI/espalier-harness
   python3 -m venv /tmp/espalier-verify && /tmp/espalier-verify/bin/pip install "espalier-harness==X.Y.Z" \
       && /tmp/espalier-verify/bin/espalier --version
   ```
   The attestation proves the wheel came from this repository's publish
   workflow; the fresh install proves the version resolves and runs. If a
   packaging change shipped, compare the sdist's member list against a local
   `python -m build --sdist` (names, not hashes: a rebuild is not
   byte-identical). A difference is an investigation signal. (Measured
   2026-09-27 on 0.8.0b2: attestation verified, install reported the version
   with `LICENSE` and `NOTICE` in the licence metadata.)

## Historical: alpha-cadence ritual

The v0.6.x → v0.7.0 series followed a publish-then-promote ladder.
Each alpha (`v0.7.0a1`, `v0.7.0a2`) was published to
TestPyPI for adopter pre-validation, then promoted via a stable
tag at the same commit. The original ritual was:

1. Push a temporary `v0.7.0a0` tag (alpha, never publish-target).
   The publish workflow should reach the `gate` job
   (release.yml as reusable workflow), reach the `publish` job's
   environment-approval gate, then the maintainer rejects the
   deployment from the GitHub UI — no upload happens. Confirms the
   environment-protection rules wired correctly.
2. Delete the temporary tag locally and remotely.
3. The first real publish is the v0.7.0a1 tag push; expect the
   publish workflow to walk all the way through to a successful
   PyPI upload.

The stable-direct ritual above supersedes this for routine cuts.
The alpha ladder remains valid for **high-risk releases** requiring
adopter pre-validation — in that case, substitute `vX.Y.Za0` for
`vX.Y.Z` in step 4 of the stable-direct procedure and add a TestPyPI
publish step between 8 and 9.

### Recovery: the tag is on origin but nothing published

Symptom: `git ls-remote --tags origin` shows the release tag, but the Actions
tab has no `publish` run for it, and PyPI has no new version.

Cause: the tag reached origin inside a push that carried more than three tags
at once (`--tags`, or several explicit tags together). GitHub creates no tag
events for such a push, so `publish.yml` never fired. The push succeeded, which
is why this reads as a shipped release.

⚠ **Do not try to re-push the tag.** Pushing a ref origin already has emits no
event, so nothing happens. Do not delete and re-push it either — tag protection
(the "Protect the release tags" step above) blocks that by design, and deleting
a published tag breaks every release link that points at it.

Recovery, in order:

1. **Confirm the tag's commit is what you meant to ship.**
   ```bash
   git ls-remote --tags origin | grep vX.Y.Z
   ```
2. **Re-run the publish against the existing tag.** `publish.yml` carries a
   `workflow_dispatch` trigger for exactly this case.
   ⚠ **This only works for tags cut AFTER that trigger landed.** A dispatch runs
   the workflow file as it exists at the SELECTED REF, and every older tag carries
   a copy of `publish.yml` with no `workflow_dispatch` — dispatching against one
   is inert. Check before relying on it:
   ```bash
   git show vX.Y.Z:.github/workflows/publish.yml | grep -c workflow_dispatch
   ```
   If that prints `0`, this route is unavailable for that tag: move the tag to a
   commit that carries the trigger, or cut the next patch version. Run it and, in the
   "Use workflow from" ref selector, choose **the tag** — not a branch:
   ```bash
   gh workflow run publish.yml --ref vX.Y.Z
   gh run watch
   ```
   The tag/version guard, the release gate and the OIDC handshake all behave
   as they do on the push path, because the run's ref IS the tag.
3. **If the version was already burned on PyPI**, no re-run helps — PyPI
   uploads are immutable. Cut the next patch version instead.

Prevention is one line: never push tags in bulk. The tag-push steps above name
the tags explicitly for this reason.

### Recovery: `gh release create` ran before tags pushed

Symptom: GitHub release-notes body contains 404 compare links (e.g.,
`compare/v0.7.0a1...v0.7.0a2`).

Recovery:

1. `git push origin vA vB` — name the missing alpha/beta tags explicitly.
   Do **not** use `--tags`: a bulk push suppresses the tag events, which is
   what strands a release in the first place.
2. `gh release edit vX.Y.Z --notes-file CHANGELOG.md` — re-renders
   the notes body against the now-resolvable links.

The release tag itself doesn't need recreating; only the notes-body
rendering needs to walk the new tag state.

## Hotfix cadence (patch-of-patch)

When a post-tag bug requires a hotfix on top of an already-tagged
release. Worked example: v0.7.1.1 (commit 89fd68b, 2026-05-19) was
a hotfix on top of v0.7.1 covering a stop_gate regression caught in
post-tag review.

The hotfix tag uses an extra `.N` suffix on the base version
(`v0.7.1` → `v0.7.1.1`). PEP-440 parses these as standard
release-version forms; `packaging.version.Version` orders them
strictly above the base.

Procedure (default: main-line hotfix, matches v0.7.1.1's actual flow):

1. **Hotfix on main (default)** — if main hasn't diverged from the
   tagged release in ways the hotfix must NOT pick up, commit the
   fix directly on main. This is what v0.7.1.1 (89fd68b) did: its
   parent chain is `89fd68b ← bdf600f ← 6cecec3=v0.7.1`. The hotfix
   tag points at a commit two ahead of the base tag on the main
   line. Simpler than branching; no merge ceremony.

   **Alternative — hotfix branch from prior stable tag**: required
   if main has accumulated work the hotfix must not include (e.g.,
   v0.7.1.1 needs to fix the bug AT v0.7.1's tree shape, not at
   current main):
   ```bash
   git checkout vX.Y.Z
   git checkout -b hotfix/vX.Y.Z.1
   ```
   Cherry-picking back to main after release is the operator's
   responsibility.
2. **Apply the fix + tests** — keep scope tight. A hotfix that
   grows beyond one BC-NNN corpus row is not a hotfix; it's a point
   release.
3. **Bump version surfaces** — `pyproject.toml`,
   `espalier/__init__.__version__`, `bench/RESULTS.md` (regenerate via
   `python bench/run_benchmark.py --update-canonical`; authoritative list
   in `espalier/version_surfaces.py::VERSION_SURFACES`). **CHANGELOG**:
   add a NEW `[X.Y.Z.N] - <date>` section ABOVE the existing `[X.Y.Z]`
   section; preserve the base entry verbatim. Add a footer link
   `[X.Y.Z.N]: .../compare/vX.Y.Z...vX.Y.Z.N` in monotonic position
   above `[X.Y.Z]` (enforced by `tests/test_changelog_footer.py`).
4. **Pre-tag gate** — `python scripts/release_check.py` must show
   all gates green (`N passed, M skipped`).
5. **Commit** — `git commit -m "release+fix: vX.Y.Z.N — <regression
   description>"`.
6. **Tag** — `git tag -a vX.Y.Z.N -m "vX.Y.Z.N: <one-line>"`.
7. **Push the branch + tags** — if both the base tag (vX.Y.Z) and
   the hotfix tag (vX.Y.Z.N) are push-pending, push them together:
   ```bash
   git push origin vX.Y.Z vX.Y.Z.N
   ```
   Name both tags. `--tags` would push every local tag, and GitHub creates
   no tag events past three in one push — the hotfix would land on origin
   without ever triggering `publish.yml`.
8. **Create the GitHub release** —
   ```bash
   gh release create vX.Y.Z.N --notes-from-tag
   ```
   The base-tag release notes are unaffected; the hotfix gets its own
   release.

If the base tag (`vX.Y.Z`) is itself still local-only (push-pending),
push it FIRST in a separate command — the hotfix's compare URL
(`compare/vX.Y.Z...vX.Y.Z.N`) is unresolvable until the base reaches
origin. v0.7.1.1's actual flow encountered this exact state (both
v0.7.1 and v0.7.1.1 tags were push-pending when the hotfix landed,
before either was pushed to origin).

## Historical decisions

Decisions that gated specific releases. Kept for archaeology; do not
re-litigate without new evidence.

### 2026-05-26 → v0.8.0a1 (alpha cycle)

The first OSS-rebrand tag was **v0.8.0a1** (alpha), not v0.7.11
(patch). Rationale:

- Auto-justification shipped with a known structural
  hash-domain mismatch (composer hashes `task|index|desc`; matcher
  hashes `sha256(file_bytes)` / `sha256(cmd)` — disjoint domains).
  A follow-up fixed the mismatch. Alpha framing bought the time for
  that fix to land without a patch release advertising a
  known-broken feature.
- The OSS rebrand cycle naturally maps to a major-version cadence.
- README's `Development Status :: 4 - Beta` classifier already
  signals pre-stable; an alpha tag is consistent.

Items that were deferred from v0.8.0a1 to a later v0.8.0bN / v0.8.0
GA: the auto-justification hash-domain MAJORs; promotion of
`action_justification` from `experimental` to `stable`.
