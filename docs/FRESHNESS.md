# Document Freshness Signal — Operator Guide

> The freshness signal is the harness's mechanism for binding doc-side
> claims to live code paths and tracking their verification SHA so the
> next refactor surfaces drift instead of papering over it.

This guide is for operators who need to **add a freshness fragment**,
**re-pin one after a verified change**, or **interpret a critical
state** during a session.

It assumes you have already read the high-level description in
your repo's conventions doc, if it records document freshness, and the
freshness-signal
history in this repo's changelog, if it keeps one. This document is the
day-to-day reference.

## 1. What freshness fragments are

A **freshness fragment** is a tiny machine-readable comment in a doc
file that pins one specific claim to:

- a `bound` — one or more code paths or symbols the claim depends on;
- a `policy` — how to interpret drift on those paths;
- a `last_verified_sha` — the HEAD a human operator confirmed the
  claim at, stored in `.espalier/freshness.json`.

Drift detection works like this: when any commit since the pin SHA
touches a bound path, the fragment's state advances from `fresh` to
`stale` (a few commits, advisory) to `critical` (many commits or many
days, release-blocking).

Fragments are NOT a substitute for tests. They are an attention
mechanism for claims tests can't easily encode — narrative invariants,
multi-surface counts, behavioural contracts where the assertion has
to live in prose.

## 2. Anatomy of a fragment marker

A marker is an HTML comment in any file inside the allowlist
(`FRAGMENT_SURFACE_ALLOWLIST` in the engine's `freshness` scanner):

```markdown
<!-- espalier:fragment id=memory-line-cap
     bound=tests/test_contracts.py::TestMemoryMdLineLimit::test_memory_md_within_cap
     policy=verify-on-touch -->
Keep this file to at most 120 lines (cap history: 60 → 75 → 80 → 120; TestMemoryMdLineLimit gates it).
```

Required fields:

| Field | Meaning |
|---|---|
| `id` | Unique fragment identifier (kebab-case). |
| `bound` | Comma-separated `path[::symbol]` entries that the claim depends on. |
| `policy` | One of `verify-on-touch`, `weekly`, `numeric-contract`. |

Optional fields:

| Field | Meaning |
|---|---|
| `bound_closure=true` | Widen `--changed-files` intersection to include files that *import* the bound symbol. Use sparingly — closure adds scan cost and can produce false-positive findings; reserve for fragments where the caller-side surface materially affects the claim. |

The scanner refuses markers inside YAML frontmatter or fenced code
blocks. It refuses bound entries starting with `-`
(git-pathspec safety).

## 3. States and their meaning

| State | Meaning | Block CI? |
|---|---|---|
| `fresh` | `commits_since=0` AND `days_since≤14`, AND the bound has no uncommitted changes, AND (on a tree that commits its manifest) the entry's `expected_value` matches the committed one. The pin SHA still describes reality. | No |
| `stale` | Pinned, and neither `fresh` nor `critical`: `commits_since∈[1..5]` with `days_since≤28`, or `commits_since=0` with `14<days_since≤28`, or — inside the fresh band — a bound with uncommitted changes (drift that has not landed) or a literal edited by hand. Small drift, or ageing past the day threshold; re-verify when convenient. | No (warn) |
| `critical` | `commits_since>5` OR `days_since>28`. Substantial drift against the bound source, or a pin more than 28 days old. Also forced when the policy is unknown. | **Yes** (when `--critical-only`) |
| `unpinned` | Marker exists but no manifest entry, or the entry does not match. | No |

Threshold constants:

- `STALE_THRESHOLD_COMMITS = 5`
- `STALE_THRESHOLD_DAYS = 14` — where the day axis leaves `fresh`.
- `CRITICAL_THRESHOLD_DAYS = 28` — where it starts blocking.

The gap between the last two is the warning band (§C22): on the day axis a
fragment warns for a fortnight before it reds, so a cohort sharing one pin date
gets notice instead of a wall. **The commit axis has no such band** — more than
`STALE_THRESHOLD_COMMITS` commits against a bound path blocks immediately,
because heavy drift is evidence the claim is wrong *now* rather than ageing.

A fragment can also be forced to `critical` independent of drift:

- The fragment's marker `bound` does not normalize-equal the manifest
  entry's `bound`. This is the **fragment-id rebinding attempt** — see
  a bound change invalidating the pin. Operator must
  `espalier freshness unpin <id>` before adding a marker with a
  different bound.
- The fragment's `policy` is not in the closed vocabulary.
  Either typo or attacker-planted; investigate.

## 4. Policies

### `verify-on-touch`

Any commit to the bound paths stales the fragment. Semantic
fragments (behavioural claims, architectural invariants) use this
policy. Conservative by design — re-pinning after every touch is the
intended workflow: the act of re-verification IS the pin.

A bound that names a symbol (`path.py::symbol`) counts only the commits
that changed that symbol's own lines: the scanner reads the file at
HEAD, takes the span of the top-level `def`, `class` or assignment
(decorators included), and follows it back with `git log -L`, so a
function's whole body and a tuple's every row are in the span and the
rest of the file is not; the repo's diff driver plays no part. A bound
that names a file counts every commit to it. A symbol the scanner
cannot place (nested, renamed away, or in a file that is not Python)
and any git error fall back to the file count, so the fallback is
always the conservative one; the walk runs only when the file has
drifted at all.

A symbol bound is narrower than its file. Where a claim spans more than
one symbol, name each one (`a.py::x,a.py::y`) or bind the file, and
re-pin after widening: a bound change is a rebind.

### `numeric-contract`

Adds an `expected_value` to the manifest entry: the number the claim
displayed when the operator pinned it, recorded so a reader of the
manifest sees it without opening the doc. The number is given on the
fragment's first pin (`--expected-value`; a first pin without one is
allowed and says so). A later pin given none carries the recorded
number across a bound nothing has touched since the pin that verified
it -- a re-pin refreshes the clock, not the number -- and refuses to
carry one whose bound moved, whose marker was rebound, or that was
edited by hand, so the number is restated exactly when it may have
changed. Nothing compares it mechanically -- the scan tracks the
bound paths, not the literal, and `audit-accuracy` reads only the
scan's state. A count that a test can
derive from its source belongs under `verify-on-touch`, with that test
as the verifier of the displayed number (the harness's own tree derives
each such count in `tests/test_documented_claims.py`, Espalier source repo, and holds the doc
sentence to it); the one `numeric-contract` fragment left on that tree,
`hook-count`, is the policy's live instance.

### `weekly`

Reserved for cron-style cadence checks. **Not yet given distinct
semantics:** a `weekly` fragment currently shares the default staleness
thresholds (stale after 14 days *or* 5 commits of drift), because no
semantic fragment uses it today. The dedicated "fresh for 7 days
regardless of commit activity" behavior is **not implemented** —
`espalier.scanners.freshness._classify` takes no per-policy branch. If a
real `weekly` fragment is ever added, implement the 7-day age gate in
`_classify` and update this section.

## 5. CLI workflow

```bash
# Pin a fragment to the current HEAD after verifying the claim:
espalier freshness pin hook-count --expected-value 12

# Re-pin after intentionally changing a fragment's bound paths
# (e.g., the claim's load-bearing file moved). --force is required
# because pin_fragment refuses to silently overwrite a different
# manifest bound — see "Pin-time rebinding defense" below.
espalier freshness pin memory-line-cap --force

# Bulk-seed every discoverable fragment at HEAD. Skips bound-drift
# cases (does not accept --force) and exits 1 if any were skipped:
espalier freshness pin --all

# Check all fragments:
espalier freshness check

# JSON output (used by audit_accuracy, session_start, statusline):
espalier freshness check --json

# Filter to criticals (used by CI gate):
espalier freshness check --critical-only

# CI gate scoped to changed files (PR-aware):
espalier freshness check --critical-only --changed-files "src/foo.py,docs/bar.md"

# Remove a fragment from the manifest (alternative to --force when
# the operator wants to start fresh with a different bound):
espalier freshness unpin memory-line-cap
```

Exit codes:

- `0` — no blocking criticals (repo-wide if no `--changed-files`,
  scoped if provided); pin succeeded.
- `1` — pin/unpin operation failed (fragment not discoverable,
  manifest unreadable, bound-rebind without `--force`, or
  `pin --all` skipped at least one fragment due to drift).
- `2` — freshness scan failed OR `--critical-only` found a
  blocking critical fragment.

### Pin-time rebinding defense (pin side)

`pin_fragment` mirrors the scanner's rebinding-attempt critical at
the pin call site. If an existing manifest entry's normalized
`bound` differs from the marker's current `bound`, the CLI refuses
with a message naming both bounds. Operator must either:

1. Pass `--force` to consent (after verifying the new bound is
   correct);
2. Run `espalier freshness unpin <id>` first, then re-pin (clears
   the manifest entry so the next pin is a "first pin"; a
   `numeric-contract` fragment loses its literal with the entry, so
   give that pin `--expected-value` -- `unpin` names the number it
   discarded).

`pin --all` does NOT accept `--force` — bulk seeding must not
silently rebind. Drift cases are reported in the `skipped` block
of the JSON output; operator reviews each, then re-pins
individually with `--force`.

### Pin-time uncommitted-bound defense (pin side)

A pin records HEAD as the point where the claim was verified. When a
bound path carries uncommitted changes, HEAD is not the tree the
operator looked at, and the manifest would vouch for a verification
that never happened — for a `numeric-contract` fragment, a literal
that is false at the SHA it names, which `check` then reads `fresh`
because drift is counted in commits (measured 2026-09-06: a count
pinned at 47 against a HEAD where the answer was 46). `pin_fragment`
refuses with a message naming the paths; commit the bound first,
then pin, or pass `--force` to record the pin at HEAD anyway. The
check is narrowed the way the commit walk is: for a bound that names
a `::symbol`, only a working-tree change to that symbol's own lines
counts. `pin --all` (which takes no `--force`) refuses before pinning
anything when any fragment's bound is dirty, so a cohort re-attestation
resets every clock together or not at all; the `skipped` rows name the
paths and the remedy is one commit, or a single pin with `--force`.

The scan side is the same rule: a pinned fragment whose bound has
uncommitted changes reads `stale` (never `critical` on that ground
alone) with a message naming the paths. On a tree that commits its
manifest — the harness's own — a `numeric-contract` entry whose
`expected_value` differs from the committed manifest's beside an
unchanged pin (a literal edited by hand) reads `stale` too, and a pin
given no `--expected-value` -- `pin <id>` or `pin --all` -- refuses to
carry it. `init` gitignores `.espalier/` on an
adopter tree, so there the manifest is never at HEAD, the hand-edit
comparison stands down, and `check` says so in its advisory. A checkout that
generates files under a directory bound before it scans reads that
bound dirty; a tree whose `git status` reports a file changed on line
endings alone reads it dirty too, and the remedy there is to normalise
the endings, not to commit.

## 6. State cache and consumers

`espalier freshness check` writes a derived `state_cache` to a
gitignored per-install file, `.espalier/.freshness_state_cache.json`,
carrying counts + critical/stale lists + the computed-at SHA. **Consumers
only read this cache**; only `freshness check` writes it. The whole file
body IS the cache object (there is no `state_cache` wrapper key).

Consumers:

- `tools/cc/hooks/session_start.py` — prints a stderr banner at
  session start when `critical > 0` OR `stale >= 3`.
- `tools/cc/statusline.py` — appends `fresh:N crit:M` (or
  `fresh:N stale:M`) to the per-prompt statusline when there is
  signal worth showing.
- `espalier audit-accuracy .` (MODE_FRESHNESS) — emits one ClaimVerdict
  per in-scope fragment the cache lists as critical (`FAIL`) or stale
  (`UNVERIFIABLE`); a fresh fragment emits nothing, and `--doc <file>`
  scopes the set to that file. `espalier audit .`, the harness integrity
  audit, emits no freshness verdict at all.

The cache lives in its OWN gitignored file, separate from the committed
`.espalier/freshness.json` manifest. The manifest carries only the
authoritative, committed SoT (the `fragments` pins + `schema_version`)
and is intentionally public; the derived cache is a per-install
read-performance artifact regenerated on demand, so a `freshness check`
never dirties the tracked working tree. Nothing in CI depends on a
committed cache: the gate recomputes drift via `scan_repo` (see §7), and
`espalier audit-accuracy .` emits no freshness verdicts when the cache is
absent or stale.

Cache staleness: if the cache was computed against a SHA that is no
longer an ancestor of HEAD (within the last 50 commits) or is more
than 24 hours old, consumers treat it as missing and silently
degrade. Run `espalier freshness check` to re-warm.

## 7. CI gate semantics

`.github/workflows/harness-guard.yml` runs:

```bash
espalier freshness check --critical-only \
  --changed-files "$CHANGED_FILES"
```

where `$CHANGED_FILES` is the PR's `git diff --name-only` against
the base SHA. Exit semantics:

- Exit `0`: no critical fragment's bound (or closure, for
  `bound_closure=true` fragments) intersects `$CHANGED_FILES`.
- Exit `2`: at least one critical fragment is bound to a file the
  PR touched.

Stale fragments NEVER block merge. They appear in the normal
`freshness check` output as advisory signal.

Adding the freshness job to required-status-checks is a one-time
operator action in GitHub branch protection; see
`docs/RELEASE_CHECKLIST.md` (self-host only — not deployed by `init`).

## 8. When to add a fragment

A claim is freshness-worthy when ALL of:

1. It's a **doc-side claim** (prose, table count, narrative
   invariant) — not a test assertion.
2. The claim is **bound to specific code paths** — drift detection
   makes sense.
3. The claim is **non-obvious from tests alone** — a future reader
   could be misled by a stale version. (Those filenames are the allowlist
   shape, whichever of them your repo keeps.)
4. The claim is **on a surface in the allowlist** — `README.md`,
   `CHANGELOG.md`, `ESPALIER_MEMORY.md`, `CLAUDE.md`, `docs/**/*.md`, or
   `.claude/**/*.md`. The allowlist denies `examples/**`,
   `docs/external/**`, `task-packs/**`, and `.espalier/**`.

A claim is NOT freshness-worthy when:

- A test can mechanically enforce it (write the test instead).
- It's a release-history entry (CHANGELOG sections describing the
  past don't drift in the relevant sense).
- It's transient session state.

## 9. Relationship to `TestNoStaleNumericContracts`

`tests/test_documented_claims.py::NUMERIC_CONTRACTS` (Espalier source repo) is the registry of
numeric claims: a tuple of `NumericContract` entries that each hold a
number's doc surfaces (by regex) to its value. Where the number can be
asked of its source, the registry derives it (the in-scope corpus glob,
a tuple's length) and the doc sentence is the one place a human edits.

A freshness fragment on the same source is the second, coarser signal:
it records that an operator re-verified the claim at a SHA and drifts
when the bound moves. Several registry entries carry such a twin.
**Derive the current membership — do not read a count here:**

```bash
grep -c 'NumericContract(' tests/test_documented_claims.py   # registry entries
python3 -c "import json;print(len(json.load(open('.espalier/freshness.json'))['fragments']))"
```

| Surface | Mechanism | Lifecycle |
|---|---|---|
| `hook-count` | registry (`canonical hook count`) + a `numeric-contract` fragment | Live: the policy's one instance on this tree |
| other registry entries with a source fragment | registry (derived where the source allows) + a `verify-on-touch` fragment | Live; no scheduled removal |
| Future numeric claims | registry contract derived from the source, plus a `verify-on-touch` fragment on that source; `numeric-contract` only where no test can derive the number | Default |
| Future semantic claims | Freshness fragment only | Default |

## 10. Troubleshooting

**"fragment <id> not pinned" message:**
The marker is discoverable but no manifest entry exists. Run
`espalier freshness pin <id>` after verifying the claim still
holds.

**"fragment-id rebinding attempt" message (from `check`):**
The marker's `bound` does not match the manifest entry's `bound`.
Either (a) the marker was edited intentionally and the operator
needs to consent to the new bound, or (b) the change is wrong.
Compare the two bound values, then either `pin <id> --force` to
consent or revert the marker.

**"refusing to silently rebind fragment" message (from `pin`):**
Pin-time defense fired. The manifest entry's bound is different
from the marker's current bound, so a silent overwrite would hide
the change from the scan-side critical. Re-read the diff in the
error message; if the new bound is correct, re-run with `--force`.
If you intended to unpin first, run `espalier freshness unpin <id>`
and then re-pin (the next pin will be a "first pin" with no prior
bound to compare against). `pin --all` cannot consent on your
behalf — review and re-pin each rebinding individually.

**State cache appears stale or missing:**
Consumers (session_start banner, statusline segment) silently skip
when the cache is older than 24 hours or pre-dates a fast-forward
that moved off the recorded SHA. Run `espalier freshness check` to
re-warm. The gitignored cache file is per-install (a fresh clone has
none until the first local `freshness check`) — consumers degrade to
no-signal rather than inventing a default.

**`bound_closure=true` produces unrelated-cause findings:**
The closure walks every Python importer of the bound symbol; a PR
that touches an importer file will trip the gate even when the
substantive claim isn't affected. This is by design (the importer
COULD affect the claim) — calibrate by removing `bound_closure=true`
from fragments where the closure surface is too wide.

**Adding a fragment marker to a file that's outside the allowlist:**
The scanner won't discover it. Either move the claim to an
allowlist surface, or extend `FRAGMENT_SURFACE_ALLOWLIST` (with a
test asserting the new path is allowed; see
`tests/test_freshness_scanner.py::TestSurfaceAllowlist`, Espalier source repo).

**Re-pin after a refactor:**
```bash
# verify the claim still holds — re-read the bound paths, confirm
# the claim's prose still matches what the code does:
espalier freshness pin <id> --expected-value <N>  # numeric-contract: the refactor moved the bound, so restate the number
espalier freshness pin <id>                         # verify-on-touch (a numeric-contract fragment whose bound did not move carries its literal)
```

The pin is operator-confirmation, not automated. The harness will
never auto-pin on commits to bound paths — that would defeat the
purpose (the act of verification IS the pin).
