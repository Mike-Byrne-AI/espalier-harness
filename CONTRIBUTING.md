# Contributing to Espalier-Harness

## Setup

> **On macOS, type `python3`.** Stock macOS ships only `python3`, not a bare
> `python`, so the `python -m …` commands below (including `python -m pip`)
> fail with `command not found` unless you substitute `python3`. (Espalier
> detects and pins the right
> interpreter when it writes your hooks; this only affects these bootstrap
> commands. On Windows the launcher is usually `python`.)

```bash
git clone https://github.com/Mike-Byrne-AI/espalier-harness.git
cd espalier-harness
python -m venv .venv
. .venv/bin/activate          # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'   # quotes required for zsh; installs pytest + dev tooling
pytest -q
```

> The bare `pip install -e .` installs only the runtime (no `pytest`); use
> `'.[dev]'` for the test/lint toolchain. The runtime-only path is what an
> *adopter* installs to run the `espalier` CLI.

## Release Artifacts

Always use the Espalier-Harness CLI to produce release artifacts — never use Finder, File
Explorer, or manual zip. Manual zips include `.git/`, `__pycache__/`, `.DS_Store`,
local settings, and other junk that must not ship.

```bash
espalier pre-release . --output dist/espalier.zip  # full gate + clean zip
espalier release-pack . --output dist/espalier.zip # zip only (no gate)
```

## Making Changes

1. Fork and branch from `main`.
2. Write or update tests for your change.
3. Run the full suite: `python scripts/proof_tier.py --run --tier full` (the
   parallel default: xdist, then the three wall-clock-budget files serially,
   one receipt; `pytest -q` is the serial form; both need `pip install -e '.[dev]'`)

   > **Never collect `espalier/_vendor/selfcheck_tests/` alongside `tests/`.**
   > The mirror has no `__init__.py` and 8 of its 9 files share a basename with
   > `tests/` (all 7 test modules plus `conftest.py`), so `pytest .` or
   > `pytest tests/ espalier/_vendor/selfcheck_tests/` aborts with
   > `import file mismatch` — and because `espalier/` sorts before `tests/`, the
   > vendored copies import first and pytest blames `tests/test_scanners.py`
   > et al. for a collision that is not theirs. Bare `pytest` is safe
   > (`testpaths = ["tests"]` scopes it); the mirror runs in isolation via
   > `espalier selfcheck`. The basenames cannot be renamed —
   > `tests/test_selfcheck_tests_parity.py` pins the mirror byte-for-byte
   > against the `tests/` subset.

4. Run the harness audit to verify your changes don't break the surface:
   ```bash
   espalier audit .
   ```
5. Open a PR with a clear description of what changed and why.

## Conventions

[`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) is the sole home for this
project's actual patterns, and this file does not restate them: the layer
rules (`espalier/` imports `espalier/` only; `tools/cc/` has zero espalier
imports and runs standalone; `espalier/scanners/` is stdlib-only), the hook
contract (the exit-code channels and per-event block JSON, pinned from the
protocol excerpt in `docs/external/cc-hook-protocol.md`), the code style, and
the test naming and fixture patterns. The copy that used to live here drifted
— its one style rule asked for comment labels nothing in the tree uses — which
is why it is a link now. Read it before a first change.

## Hook Rules

⚠ **A PR that touches a CI-gated path needs `HARNESS-UPDATE-APPROVED@<sha>` in
its TITLE, where `<sha>` is the head commit the reviewer looked at, or the
required status check rejects it.** `harness-guard` (`tools/cc/ci_guard.py`)
reads the marker from the PR **title**, not the commit message, binds it to the
head under review, and fails the merge without it; a force-push after approval
goes red until a reviewer re-binds the title, and the gate's output prints the
exact fragment to paste. The check is required, so the PR cannot merge and the
README's CI badge shows the failure. The gated set:

<!-- BEGIN GENERATED: ci-gated-paths — rendered from tools/cc/ci_guard.py + tools/cc/hooks/_protected_zones.py, do not hand-edit -->
- `tools/cc/hooks/` — prefix: every path under it
- `.github/workflows/` — prefix: every path under it
- `.espalier/integrity.json`
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.github/workflows/harness-guard.yml`
- `tools/cc/ci_guard.py`

`write_guard` protects a WIDER zone at RUNTIME — a different policy, not this
one restated. `tools/cc/`, `cc/`, `espalier/`, `.espalier/freshness.json` are
runtime-protected but are NOT themselves in the CI-gated set above, so a PR
touching one needs no marker unless it also matches a row above.
<!-- END GENERATED: ci-gated-paths -->

Put the bound marker in the title when your change lands in any of those — e.g.
`fix(hooks): tighten the path guard HARNESS-UPDATE-APPROVED@1a2b3c4`, where
`1a2b3c4` is `git rev-parse --short HEAD` on the branch as reviewed.

⚠ **Do not widen that list from memory.** The RUNTIME hook (`write_guard`)
protects a *larger* zone than CI gates — the generated block above names exactly
which paths those are, so it does not have to be retyped here — and the two are
deliberately different policies, not one fact stated twice.
`tools/cc/ci_guard.py::PROTECTED_PREFIXES` / `PROTECTED_FILES` is the authority
for what blocks a MERGE; quoting the runtime zone here would demand a marker for
PRs that do not need one.

The hook contract itself is under [Conventions](#conventions) above; a
hook that imports `espalier` is a deployment bug, not a style issue.

## Versioning

Espalier-Harness uses [Semantic Versioning](https://semver.org/). While pre-1.0, minor
version bumps may include breaking changes.

- **Patch** (`0.3.x`) — bug fixes, doc corrections, test additions.
- **Minor** (`0.x.0`) — new commands, new hooks, new agents. May include
  breaking changes to hook JSON format or CLI flags while pre-1.0.
- **Major** (`x.0.0`) — reserved for post-1.0 stability guarantees.

To bump the version: update `pyproject.toml`, add a `[x.y.z]` section to
`CHANGELOG.md`, and tag the commit with an ANNOTATED tag
(`git tag -a vX.Y.Z -m "vX.Y.Z: <one-line summary>"`). A plain tag will not
propagate with `--follow-tags` and leaves the release notes with no message
to render.

## Releasing a new version

1. Complete and verify all release-blocking work for the cycle; each change
   lands with its verification passing before the commit lands.
2. Bump the version across all five surfaces:
   - `pyproject.toml` `version = "x.y.z"`
   - `espalier/__init__.py` `__version__ = "x.y.z"`
   - `bench/RESULTS.md` — a declared version surface (`espalier/version_surfaces.py`);
     regenerate it with `python bench/run_benchmark.py --update-canonical`
   - `CHANGELOG.md` — fold `[Unreleased]` into a new dated `[x.y.z] — YYYY-MM-DD` section
   - `CHANGELOG.md` footer — add the version-comparison link
   The `version_consistent` release check enforces the three file surfaces
   the `VERSION_SURFACES` registry declares (`pyproject.toml`, `__version__`,
   `bench/RESULTS.md`), and asserts the new dated section is not empty —
   so a header minted without its notes fails the gate. It does **not**
   verify the fold is *complete*: `[Unreleased]` legitimately carries the
   dev record between releases, and the check runs on every push to `main`,
   so an emptiness assertion there would red `main` for the whole
   pre-release period (see `DEF-669`; a `DEF-NNN` names a row of
   `task-packs/FORWARD_LEDGER.md`, the forward-work tracker, which ships in
   the public repository and is not deployed by `init`). The footer
   compare-link is covered by `tests/test_changelog_footer.py`. Steps 3-4
   remain a human check.
3. Run the final proof matrix:

   ```bash
   python scripts/final_release_matrix.py
   ```

   The script exercises every install path Espalier supports — source
   checkout, source archive, sdist, wheel-into-fresh-venv — plus a
   cross-artifact cleanliness scan. Every stage must `PASS`. If any
   stage `FAIL`s, do not tag — fix the root cause and re-run. The full
   matrix takes roughly 5–10 minutes; iterate on individual stages
   during development with `--skip 02 --skip 03 ...`.

4. Tag the release with an **annotated** tag — `git tag -a vX.Y.Z -m "vX.Y.Z:
   <one-line summary>"`. Annotated is required: `--follow-tags` ignores a
   lightweight tag, and the release notes render from the tag message.
5. **Push the tag — naming it explicitly.** Nothing publishes until the tag
   reaches origin, and `publish.yml` triggers on the tag push itself:
   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```
   ⚠ Never `git push --tags` here. GitHub creates no tag events when more than
   three tags are pushed at once, so a bulk push lands the tag while the publish
   workflow never fires — the push succeeds and the release silently does not
   ship. The full ritual, its failure modes and the recovery route live in the
   maintainer release runbook, `docs/RELEASE_CHECKLIST.md`, which is kept in the
   maintainers' private development archive and is part of neither this
   repository nor the sdist — a plain reference, not a link. This section is
   the short form.
6. **Publication is automatic from step 5 — you do not upload anything.**
   The tag push triggers `publish.yml`, which walks the release gate and then
   builds and uploads the wheel + sdist in CI from a clean checkout, via the
   OIDC trusted publisher. The artifacts the matrix left in
   `dist/final-release-matrix/` are a local VERIFICATION record — compare
   against the published files if you want — not the payload that ships.
   Watch the run rather than re-building anything locally.

## How we test

Espalier-Harness's test suite is sliced by `pytest` markers (see
[`tests/README.md`](tests/README.md) for the full taxonomy):

- `unit` — pure function/model tests against real filesystem fixtures.
- `integration` — subprocess, CLI, hook, filesystem, or rendered-surface
  integration tests. Runs hooks and CLI as subprocesses via
  `sys.executable`, piping JSON to stdin — the same way Claude Code
  invokes them in production.
- `contract` — self-hosting, docs, generated-surface, and public-claim
  truth tests. Catches drift between code and operator-facing docs.
- `security` — bypass, write-guard, plan-guard, kill-switch, and
  enforcement regression tests. Each test is named after a specific
  attack vector or historical incident and reproduces the exact command
  or bypass that caused it. A failure here means a known bug has returned.
- `release` — packaging, artifact parity, version, and benchmark tests.
- `slow` — additive marker for tests that build wheels or run heavy
  subprocesses. Combine with another marker (e.g., `release and slow`).

Marker assignment is centralized in `tests/conftest.py` based on
filename patterns. When you add a new test file:

- Use one of the established filename patterns so `conftest.py` can
  assign the right marker automatically (`test_write_guard_*` →
  `security`, `test_release_*` → `release`, etc.).
- If your file fits a new category, add a pattern to `_MARKER_RULES` in
  `tests/conftest.py` and document the new marker in `tests/README.md`.
- Adversarial/security tests must each name a distinct attack vector.
  Do not consolidate them into parametrized smoke tests; each name is
  part of the regression narrative.

Run the relevant slice before submitting a PR:

```bash
python -m pytest -m security              # if you touched hooks or guards
python -m pytest -m release               # if you touched packaging or surface
python -m pytest -m "not slow"            # fast local loop
python scripts/proof_tier.py --run --tier full   # full suite, the parallel default (about 6.5 min here)
python -m pytest                          # full suite, serial form, if you're not sure
```

## Security Reports

**Do not open a public issue, public pull request, or public discussion
with vulnerability details.** Use the private reporting instructions in
[`SECURITY.md`](SECURITY.md). The preferred path is the repository
Security tab → `Report a vulnerability`. If private reporting is
unavailable, open a public issue **only to ask for a private security
contact** and omit all technical details.

## Reporting Issues

For non-security bugs, open an issue with:
- What you ran (`espalier audit .`, `espalier fingerprint .`, etc.)
- What you expected
- What happened instead
- Output of `pytest tests/ -q` if tests are failing
