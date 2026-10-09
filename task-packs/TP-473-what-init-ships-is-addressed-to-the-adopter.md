# TP-473 — What init ships is addressed to the adopter

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: one gate (an audience contract over the deploy inventory, vocabulary in
  `espalier/surface_hygiene.py`), a body sweep over the `.claude/` kinds and the two rendered
  `cc/` headers, two small hook rewrites (`post_compact`, the kill-switch deny), one CLI
  template clause with its `render-template` arm reading the saved fingerprint, a one-line
  `/handoff` body fix, and -- behind an operator checkpoint -- the seed list. No guard predicate
  changes. After a `.claude/` edit: `python3 scripts/sync_claude_mirrors.py`; after a
  `tools/cc/` edit: `python3 scripts/sync_vendor_cc.py`; after a `docs/` or seed-list edit:
  `python3 scripts/sync_asset_docs.py` (rows `claude-asset`, `vendor-cc`, `asset-docs`,
  `task-packs-router` of `espalier/mirror_registry.py::MIRROR_ROWS`).
- **Kind: PACK.** Task 0 can end it. 0-D is an **operator-decision checkpoint**: the
  inventory half (2-A, 2-B) waits on `DEC-30` and `DEC-38`.
- Ledger: the unit of work for §C71 (`DEF-1075` the gate, `DEF-1076` the capture rewrite;
  `DEF-1074` only on the fence-and-strip fork, otherwise it waits on `DEC-32`), the §C72
  member `DEF-1082`, the §C54 member `DEF-987` (instrumented here, decided by the operator),
  and the first-run rows `DEF-1005`, `DEF-1006`, `DEF-1028`, `DEF-1186`, `DEF-1187`. Reach names
  what it does not close.
- Authored 2026-10-07 on the Air (python3-only) at `febfcd4e`, against a real `espalier init`
  on a throwaway Node tree under the author's scratch directory. Every measured sentence names
  its command; execution re-runs them. Gate: **not yet approved** (questions under *Decisions*).

## Motivation

The bodies, docs and headers `init` deploys are byte-copies of the maintainer's tree:
`espalier/cli.py::_deploy_asset_md` writes the packaged body through a marker with one render
(`espalier/cli.py::_asset_transform`, the runner agents' `tools:` line) and no audience step;
`espalier/cli.py::_packaged_md_assets` enumerates `espalier/assets/claude/`, which the
`claude-asset` mirror row pins byte-equal to the self-host `.claude/`. So the adopter reads
procedure written for the maintainer: ledger ids, `scripts/` and `tests/` paths they never
receive, the approval marker, a named co-author trailer, "this repo" meaning Espalier's.

**Measured 2026-10-07**, each by the command beside it:

- The rehearsal's mechanical pass, re-derived from its log:
  `awk 'NR>1 && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ {m+=$3; a+=$4; n++} END {print n, m, a}' fresh-init/logs/02-marker-counts.txt`
  -> `66 1175 100` (bodies, maintainer-marker hits, adopter-marker hits).
- Appendix A on a fresh `espalier init` of a four-file Node tree
  (`python3 audience_scan.py <tree> --top 20 --per-marker`): 111 deployed text files, 70 with
  hits, **806 hits**. By root: `.claude/agents` 7 files / 76 hits / 0 clean; `.claude/commands`
  18 / 152 / 3 clean; `.claude/skills` 9 / 46 / 1; `.claude/workflows` 3 / 21 / 0; the rendered
  `cc/` docs 4 / 12 / 0; `docs/` 18 / 364 / 2; `tools/cc/*.py` non-docstring strings 45 / 106 / 33.
  The `.claude/` bodies carry 31 `DEF-` and 1 `DEC-` occurrences;
  `espalier/surface_hygiene.py::SPECIFIC_ID_RE` matches none (the `DEF-1075` probe prints `False`).
- The deployed-text gates that exist are green over that population:
  `python3 -m pytest -q -m 'not heavy_e2e' tests/test_init_tier_split.py::TestCommonTierAssetHygiene tests/test_deployed_assets_home_path_shapes.py`
  -> 9 passed. Narrower than the class, not absent (0-A).
- The seed set, cwd an init'd tree:
  `python3 -c "import os;from espalier.managed_inventory import get_seed_docs as g;s=g();print(len(s),sum(os.path.getsize(p) for p in s))"`
  -> `23 873882`. `DEC-30`'s 2026-09-05 figure was 20 seeds, about 1.09 MB: three stubs joined,
  the bytes fell. Largest five: `docs/FAILURE_MODES.md` 521,721; `docs/HOOKS.md` 108,854;
  `docs/external/cc-hook-protocol.md` 33,403; `docs/HOOK_ASSUMPTIONS.md` 25,005;
  `docs/TROUBLESHOOTING.md` 24,331.
- `docs/FAILURE_MODES.md`, the banner's footgun pointer: 247 `##`/`###` sections, **49** citing
  an Espalier internal under Appendix A's marker set (split `(?m)^(?=#{2,3} )`). The rehearsal's
  reader counted 80 of 246 with a broader set (bare `pytest`, `ruff`, `mypy`). The ratio moves
  with the marker set; 0-C calibrates before anything is pinned.
- `render-template claude` says `**Languages:** python` on any tree:
  `python3 -c "from espalier.cli import _canonical_template_fingerprint as f; print(f().languages == ['python'])"`
  -> `True`; `init`'s NOTE (the `render-template claude` remedy line in `espalier/cli.py`) sends
  a Node adopter to copy sections from it (`DEF-1187`).
- `/handoff` step 6 appends into `cc/blueprints/compact_summaries/<stem>.md` with no `mkdir`:
  `grep -c 'mkdir -p cc/blueprints/compact_summaries' .claude/commands/handoff.md` -> `0`; after
  `init` the directory is absent (`ls cc/blueprints/compact_summaries` -> `No such file`); only
  `tools/cc/hooks/post_compact.py::_capture_compact_summary` creates it, at a compaction (`DEF-1186`).

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16): the adopter opening `/handoff` or
`/implement-pack` for the first time, paying tokens for another project's steps, trailer and
timings; the one meeting `DEF-412a` in a verb's stderr and the approval marker in
`docs/INSTALL-CI.md`; the one told by the always-loaded `CLAUDE.md` and the kill-switch deny
that "CI will still fail the merge" on a tree where plain `init` installed no CI gate
(`DEF-1082`); the one whose first `/handoff` step 6 errors on a directory nothing created.

## Scope (in)

Each item maps to a sub-task and to *Files touched*.

1. **Task 0** -- re-derive the counts, run Appendix A on a fresh init, check what the existing
   gates already cover, calibrate each marker's false-positive share, hold the checkpoint (0-D).
2. **1-A** The audience gate: a derived maintainer-marker vocabulary in
   `espalier/surface_hygiene.py` beside `SPECIFIC_ID_RE`; a contract test over the whole deploy
   inventory (every packaged `.claude` kind, `espalier/assets/` docs, memory, seed and task-packs
   bodies, the rendered `cc/LIVE_SURFACE.md` and `cc/PACK_MANIFEST.txt` of a tmp tree, and the
   non-docstring strings of `espalier/_vendor/cc/` through `ast`); a per-body allowlist with a
   reason each; a dated ratchet floor that only falls. A proof line carrying the trailing
   `# Espalier-Harness tree:` label (`TP-471` 3-D's grammar) is the self-host example and is no
   `self-host-path` hit. `espalier/surface_impact.py::_scan_existing` reads the same vocabulary.
3. **1-B** Drive `.claude/`, the two rendered headers and the emitted strings to zero
   unallowlisted hits: reword or delete; fence the self-host blocks `/handoff` 7b/7c and
   `/implement-pack` step 10 already label; neutral headers in
   `espalier/render_surface.py::render_live_surface` and `::render_pack_manifest`; a placeholder
   for the `DEF-412a` in `tools/cc/ledger_row.py`'s stderr; a generic
   `tools/cc/hooks/_speedbump.py::CP_RELEASE` body; the retirement folder derived at
   `/implement-pack` step 12 (`DEF-988`, since the gate sees its literal). Sync the mirrors.
   Lands last on the shared bodies, after `TP-470` 3-A, `TP-471` 3-A to 3-C and `TP-474` 3-B
   (Risks 7).
4. **1-C** (Decision 2) `espalier/cli.py::_asset_transform` strips fenced self-host blocks at
   deploy; the self-host tree keeps them; mirror parity untouched.
5. **1-D** `tools/cc/hooks/post_compact.py::_capture_compact_summary` rewrites the native
   "read the full transcript at: <home path>" sentence before both writes (`DEF-1076`).
6. **1-E** The CI clause in `tools/cc/hooks/_denial_reasons.py::KILL_SWITCH_DETECTED`, the
   SessionStart kill-switch WARN (`tools/cc/hooks/session_start.py::_report_integrity_state`) and
   `espalier/cli.py::_build_claude_md` is presence-gated on `tools/cc/ci_guard.py` plus
   `.github/workflows/harness-guard.yml` (`DEF-1082`); `_build_claude_md` takes the tree root
   explicitly, and `espalier/cli.py::cmd_render_template` renders against the saved
   `reports/repo_fingerprint.json` of the tree it runs in, the canonical fingerprint as the
   fallback (`DEF-1187`).
7. **1-F** `.claude/commands/handoff.md` step 6 creates `cc/blueprints/compact_summaries/` before
   its first append; mirror sync (`DEF-1186`).
8. **2-A** (after 0-D) The seed list per the operator's answers:
   `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS`, `::_SEED_DOCS_WITH_ADAPT_HEADER`,
   `scripts/sync_asset_docs.py::_MIRRORED`, and the link re-anchoring the parity test demands.
9. **2-B** (after 0-D) `DEF-987`'s fifteen passages: the pack prints the per-seed, per-section
   census; the operator answers move / strip / attribute per block.
10. **2-C** First-run text: the workflows kind in `README.md`, `docs/CHEAT-SHEET.md` and the
   uninstall paragraphs (`DEF-1028`); `blob/main` -> `blob/v<version>` through
   `espalier/version_surfaces.py::VERSION_SURFACES` (`DEF-1005`); the `docs/CLI_EXIT_CODES.md`
   cites in `espalier/cli.py::build_parser` dropped (`DEF-1006`).
11. **3-A** Red-team, one fix batch.

Paths these touch, for the scope walk:

- `espalier/surface_hygiene.py`, `espalier/cli.py`, `espalier/render_surface.py`,
  `espalier/version_surfaces.py`, `espalier/surface_impact.py`, `espalier/managed_inventory.py`
- read, not edited: `espalier/surface_contract.py` and `espalier/fuse.py` (both read
  `_SEED_DOC_REL_PATHS`, so a 2-A drop reaches them), `espalier/mirror_registry.py`,
  `scripts/release_check.py` and `scripts/build_release_archive.py` (both read `VERSION_SURFACES`,
  so a 2-C registration is verified at the cut)
- `espalier/assets/` and `espalier/_vendor/cc/` (by the syncs)
- `.claude/` and `examples/dogfooding/.claude/`
- `tools/cc/` (the hooks under `tools/cc/hooks/`, `tools/cc/ledger_row.py`)
- `tests/`
- `docs/`, `README.md`, `scripts/sync_asset_docs.py`
- `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`, this pack

## Scope (out)

- **`DEF-1074` as a template-is-source redesign.** The row says decide with `DEC-32` (tracked
  byte-mirrors or build-time generation; filed 2026-09-07, open). This pack offers the
  `DEC-32`-neutral half (1-C) and leaves the template fork to that decision.
- **`DEF-1077` and the upgrade mechanics** (overwrite of an adopter-edited body, overlay,
  preserved region): `TP-474` owns them.
- **`DEF-1080`** (PostToolUse advisories gated on `is_self_host_repo`): *every generic system fires off the self-host repo* (landed 2026-10-08 on lane/generic-systems-fire-off-self-host) owns it. For
  1-A: `tools/cc/hooks/_reinject.py` is the heaviest Python file in the scan (63 string hits),
  every one inside a rule gated to self-host; the allowlist records it as "strings gated to
  self-host", not a reword, until the generic-systems lane (*every generic system fires off the self-host repo*, landed 2026-10-08) flips the gate.
- **The recall corpus** on an adopter tree: `TP-466b` owns it.
- **Bare `python` in command bodies.** A documented decision, root `CLAUDE.md`
  "Cross-platform Python invocation": bodies spell `python` and the reader tries `python3`,
  `python`, `py -3`. The adopter-shaped fix, if any, is a rendering question for the same
  audience scanner (render the interpreter the tree's `settings.json` wires), not a reword.
  `DEF-1049`'s skills arm is folded into the axes pack (its Decision 6).
- **Behaviour defects in deployed bodies the gate cannot see**, each with its own oracle:
  `DEF-944` (`/commit` ignores `git_conventions`), `DEF-1040` (a stale protocol sentence; home
  `tests/test_documented_claims.py::TestHookProtocolStaleForms`), `DEF-1141` (stamp-then-amend),
  `DEF-1148` (`tools/cc/ship.py::open_pr` title), `DEF-901` (two Purpose readers disagree).
  A positive-match scanner cannot express a behaviour; these stay rows.
- **First-run rows that are not audience-shaped:** `DEF-993` (help wraps at hyphens),
  `DEF-912` (bare repo path in remedies), `DEF-994` (a venv line in source-checkout docs `init`
  never deploys), `DEF-996` (a `.bak` promise true on no tree: stale, not mis-addressed),
  `DEF-903` (sdist membership), `DEF-889` (an unindexed public doc; gate
  `tests/test_operator_docs.py::TestDocIndexCompleteness`).
- **The six-phrase and TP/BC denylists** stay as they are; the maintainer twice declined to
  widen them over false positives (`DEF-1075`), so 1-A's additions are derived and calibrated
  (0-C), never listed.
- **Another machine's claim:** nothing here touches `bench/guard_equivalence.py`,
  `tests/test_guard_equivalence.py`, `bench/guard_metamorphic.py`, `bench/README.md` or
  `CHANGELOG.md`. The claim on `tests/conftest.py` was released today, and this pack still owes
  it no row: the new module `tests/test_deployed_text_audience.py` carries no `hook` token
  (`tests/conftest.py::_MARKER_RULES` reads it as `unit`) and spawns no hook (the adopter-tree
  helper runs `init` in-process and spawns `git` only), so neither the security tuple nor the
  `# slow-exempt:` idiom applies; if 0-E's slow fork makes the test spawn `init`, the in-module
  idiom is the fix, never a conftest row (Risks 9).

## Task 0 — Verify (may end this pack)

Outcomes: **build**; **re-scope** (the existing gates cover more than measured; narrow to
what they miss); **do not build** (every family is gated, or calibration leaves none). On a
refutation: **stop and re-raise with the measurement**. Records go to scratch, never the
tree. Never run the full tier for Task 0. **0-A is the step that can end the pack.** 0-B is a
measurement recorded for Landing: its thresholds sit an order of magnitude below the figures
and could only confirm, so it is not a kill.

### 0-A The refutation: does a shipped audience gate already exist?

**Oracle:** `grep -lE 'audience|maintainer|self-host' tests/test_*.py`, a read of each hit that
scans deployed assets, `espalier/surface_contract.py` for an audience predicate; then plant a
`DEF-123`, a `scripts/<planted>.py`, the approval marker's literal and a
`Co-Authored-By: Claude, Scion` in a temporary asset copy and run the candidates by node id.
**Refuting result:** an existing test reds on the plants. Then 1-A is a duplicate: stop.
**Measured 2026-10-07:** four scanners exist, none audience-shaped.
`tests/test_init_tier_split.py::TestCommonTierAssetHygiene` reads TP/BC/TASK_PACK ids and six
phrases over `espalier/assets/`; `tests/test_deployed_assets_home_path_shapes.py` reads
home-path shapes and five id-bearing artefact shapes (a pull-request number, a dated branch, a
blueprint id) over `espalier/_vendor/cc`, `espalier/assets`, `espalier/_vendor/selfcheck_tests`;
`tests/test_portability_contract.py::TestOperatorDocsPortability` reads `python3 ` and `/tmp/`;
`tests/test_adopter_pointer_resolution.py` resolves pointers and accepts a "self-host only" /
"not deployed" disclaimer within two lines. All green at HEAD over a population carrying 806
hits. **Build, extending that family:** the vocabulary lands in `espalier/surface_hygiene.py`
(the SoT the tests and `surface-impact` share); the test takes the deployed-roots-plus-floor
shape of the home-path gate.

### 0-B Re-derive the counts (a measurement for Landing, not a kill)

**Oracle:** the `awk` line in Motivation; then `env -u ESPALIER_MAINTENANCE_MODE python3 -m espalier init .`
on a fresh four-file Node tree under scratch, then Appendix A over it.
**Refuting result:** none -- 0-A is the kill. A population under 60 files or under 100 hits is a
stale premise (`init` already renders, or the deploy set shrank): pause, re-read
`_packaged_md_assets`, report the delta. The figures feed 0-C and Landing either way.
**Measured 2026-10-07:** 66 / 1175 / 100 from the log; 111 / 70 / 806 from the scanner.

### 0-C Calibrate each marker before it pins anything

**Oracle:** for each Appendix A marker, list every hit with its line and classify by hand:
addressed to the maintainer, or not. **Bound:** a marker whose false-positive share exceeds one
third on the population is narrowed or dropped, the count recorded in the test's docstring the
way the home-path gate records its rejected shapes.
**Pre-registered false positives from the authoring run:** the seeded
`task-packs/FORWARD_LEDGER.md`'s 13 `§C<n>` hits are the ledger's own section grammar and its
11 "this repo" say the adopter's repository; the "Espalier-Harness header" shape (130 hits, 33
files) matches the honest product name in prose ("uses Espalier-Harness for governance") and
needs narrowing to a title or possessive. The `tests/test_*.py` shape (179 hits, 23 files) is
the heaviest true-positive family: a test node id offered as evidence the adopter cannot run.
**Refuting result:** fewer than four families survive the bound. Then the class is mostly
judgment (`DEF-987`'s reading); 1-A shrinks to the id families and the trailer; say so in Landing.

### 0-D Checkpoint: present `DEC-30` and `DEC-38`

Before 2-A or 2-B runs, present the two forks under *Decisions* with the seed-size command
re-run and Appendix A's per-seed table. The gate half (1-A to 1-E) may land first on its own
lane; it does not depend on the answer.

### 0-E Cost

**Oracle:** time the new test's rendered `cc/` docs. If a driven `init` exceeds 10 s on the Air,
render through `render_live_surface` and `render_pack_manifest` directly instead of spawning it.

## Relevant memory

Recent pattern: the defects reviewers find on this tree sit in the repair and in the test
that proves it. The home-path gate's history records three shapes rejected on measurement
after they dominated the yield; `DEF-1075` records the maintainer twice declining a wider
phrase list for the same reason. The likeliest repair defect here is a marker clean on the
`.claude/` bodies and flooding the seeded docs, or an allowlist reason that is a disclaimer.

| Entry | Where |
|---|---|
| Shipping a Doc Verbatim Subjects It to Content Contracts | `docs/SHARP_EDGES.md :: Shipping a Doc Verbatim Subjects It to Content Contracts` |
| A path in the seed list is not the content an adopter receives | `docs/SHARP_EDGES.md :: A path in the seed list is not the content an adopter receives` |
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |
| The mirror whose SoT is the packaged copy | `docs/SHARP_EDGES.md :: The mirror whose SoT is the packaged copy` |
| 8. Class-fix scope = every shipped surface | `docs/STANDING_PRINCIPLES.md :: 8. Class-fix scope = every shipped surface` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |

Resolved at authoring by `python3 tools/cc/hooks/_recall.py "<topic>"` with
`maintainer-addressed content shipped to an adopter`, `deployed asset byte mirror sync`,
`seeded docs land in the adopter's docs folder`; re-run if the pack has been sitting. Folders
touched, so the folder-`CLAUDE.md` ladder fires: `.claude/` (sync after every edit; never the
mirror), `tools/cc/` (vendor sync; zero espalier imports), `espalier/`, `tests/`.

## Implementation

Every fix is a **fix shape, untested**, unless it says otherwise. Each names its mutation.

### 1-A The audience gate -- `espalier/surface_hygiene.py`, `tests/test_deployed_text_audience.py`

```python target=espalier/surface_hygiene.py
MAINTAINER_MARKER_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("ledger-id", re.compile(r"\b(?:DEF|DEC|INV|LG|EI)-\d+[a-z]?\b")),
    ("self-host-path", re.compile(r"(?<![\w/.])(?:scripts|tests|bench|espalier)/[\w\-/]+\.py\b")),
    ("approval-marker", re.compile(r"HARNESS-UPDATE-" "APPROVED")),  # split so this pack carries no literal
    ("retired-pack-folder", re.compile(r"task-packs/Done/")),
    ("co-author-trailer", re.compile(r"Co-Authored-By: Claude, Scion")),
    ("dated-measurement", re.compile(r"\bmeasured (?:on )?20\d\d-\d\d-\d\d\b")),
)

#: The trailing label TP-471 3-D's contract puts on a proof line kept as the self-host example
#: (``pytest tests/test_x.py -q   # Espalier-Harness tree: ...``). Such a line is addressed to
#: the maintainer on purpose and contributes no ``self-host-path`` hit.
SELF_HOST_EXAMPLE_LABEL_RE = re.compile(r"#\s*Espalier-Harness tree:")


def maintainer_marker_hits(text: str) -> list[tuple[str, str]]:
    """``(label, match)`` for every maintainer-addressed marker in ``text``, read line by line."""
    hits: list[tuple[str, str]] = []
    for line in text.splitlines():
        labelled = SELF_HOST_EXAMPLE_LABEL_RE.search(line) is not None
        for label, pat in MAINTAINER_MARKER_PATTERNS:
            if labelled and label == "self-host-path":
                continue
            hits.extend((label, m.group(0)) for m in pat.finditer(line))
    return hits
```

The path family is *derived* at test time: the test asserts each prefix is a directory of this
repository that `espalier/managed_inventory.py::get_managed_public_prefixes` does not deploy,
so a prefix that starts shipping drops out by itself. The id family is pinned to the grammar
`tools/cc/ledger_row.py` issues. The label exemption is decision-bound: a proof line carrying
the trailing `# Espalier-Harness tree:` label is the self-host example `TP-471` 3-D's contract
permits in a deployed body, so the `self-host-path` family skips it and the two gates agree on
the same lines; the `DEF-1182` and `DEF-1184` probes count unlabelled lines only (the filed
probe, unlabelled lines). The other families still read a labelled line: an id or the trailer
on it is a hit.

The test, in the shape of `tests/test_deployed_assets_home_path_shapes.py` (deployed roots, a
floor per root, the red names the source and its sync): population = every
`espalier/surface_contract.py::CLAUDE_KIND_GLOBS` body under `espalier/assets/claude/`
(rendered through `cli._asset_transform` on the strip fork), `espalier/assets/` docs, memory,
seed and task-packs bodies, the rendered `cc/LIVE_SURFACE.md` and `cc/PACK_MANIFEST.txt` of a
tmp tree, and the non-docstring strings of `espalier/_vendor/cc/**/*.py`.
`ALLOWLIST: dict[str, str]` maps a deployed path to a one-sentence reason (the seeded ledger's
section grammar; `_reinject.py`'s self-host-gated strings; a seed kept under `DEC-30` with its
adapt header); an empty reason fails. `BASELINE = (date, count)` for the seeded docs only, and
it may only fall; the `.claude/` kinds, the two `cc/` headers and the Python strings are held
at **zero** outside the allowlist. Each root exists and holds a floor of text files.

**Mutations:** plant `DEF-123` in a temporary asset copy -> red. Blank one allowlist reason ->
red. Delete a deployed root -> the floor reds. Add `scripts/` to a tmp inventory's deployed
prefixes -> that family drops and a planted path passes (the derivation is seen). Strip the
label from one `implement-task.md` proof line -> red on that file (the line `TP-471` 3-D's
earn-the-red removes, seen from the other side).
**Refutation of the shape:** 0-C leaves fewer than four families.

### 1-B The body sweep (`.claude/`, the two headers, emitted strings)

One body at a time; the gate's red is the list. Shapes:

- `/handoff` 7b and 7c, `/implement-pack` step 10's trailer sentence and every `scripts/` line
  in `handoff.md`: fence as `<!-- espalier:self-host-only -->` ... `<!-- /espalier:self-host-only -->`
  (stripped by 1-C; allowlisted as fenced until it lands). The trailer sentence stops calling a
  named trailer the adopter-neutral default: "set your project's co-author trailer, if any".
- `hook-authoring` "Every hook script in this repo" -> "every hook script `init` deploys".
- `render_live_surface`: "Canonical index for the Espalier-Harness governance harness" ->
  "Canonical index of the harness surface deployed to this repository"; `render_pack_manifest`:
  "shipped self-host surface files" -> "the files `espalier init` manages in this repository".
  `tests/test_render_surface.py` gains the two header pins.
- `tools/cc/ledger_row.py`: `(DEF-412a)` in its strike stderr -> "(the row's own Scope (out)
  rule)"; `CP_RELEASE` body: "publish.yml burns a PyPI version" -> "a release tag reaching the
  remote publishes a version that cannot be replaced" (true wherever a publish workflow exists).
- `/implement-pack` step 12: derive the retirement folder (an existing `done/`, `Done/`,
  `completed/` or `archive/` sibling holding `TP-*.md` wins; `Done/` only when none exists) and
  say the adopter's own promote tooling is not run. Land with a fixture tree carrying `done/`
  (`DEF-988`).

Then both syncs. **Mutation:** revert one reword and the gate reds on that file.

**Lane order (the coordinator's decision 2):** 1-B lands **last** on the shared bodies, after
`TP-470` 3-A (the step-6 review block of `implement-task.md`, `preflight.md`,
`implement-pack.md`), then `TP-471` 3-A to 3-C (the proof fences of `implement-task.md`,
`implement-pack.md`, `debug/SKILL.md`, `test-this.md`, `test-writer.md`, `docs-maintainer.md`),
then `TP-474` 3-B (the four agents' `Adapting me` sections). Nothing lands after it: the gate
reads the final text, so a body edit after 1-B is a re-run of 1-B's checkpoint. Rebase on each
merge and re-read the gate's red; never carry the list forward.

### 1-C Fence-and-strip at deploy (Decision 2) -- `espalier/cli.py::_asset_transform`

```python target=espalier/cli.py
_SELF_HOST_BLOCK_RE = re.compile(
    r"<!-- espalier:self-host-only -->.*?<!-- /espalier:self-host-only -->\n?", re.DOTALL,
)


def _strip_self_host_blocks(body: str) -> str:
    return _SELF_HOST_BLOCK_RE.sub("", body)
```

`_asset_transform` composes it with the runner render for every `.claude` body on a
non-self-host tree (`espalier/surface_contract.py::is_self_host_repo`); the `upgrade` preview
takes the same transform. Mirror rows untouched: asset equals source; the strip is a
deploy-time render like the `tools:` line. **Mutation:** remove the compose -> the gate reds on
`handoff.md`'s 7b block. **Refutation:** `_deploy_asset_md`'s no-drift compare already runs on
the transformed body; if an adopter's on-disk body reads as drifted after every `init`, the
transform is not idempotent and 1-C is re-raised.

### 1-D `DEF-1076` -- `tools/cc/hooks/post_compact.py::_capture_compact_summary`

Rewrite the native `read the full transcript at: <path>` sentence to the
`tools/cc/session_summary.py::_transcript_ref` form before the append and the overwrite; pin
with a compaction fixture carrying the real boilerplate; extend
`tests/test_deployed_assets_home_path_shapes.py`'s `HOME_SHAPES` to the two files a driven
compaction writes. **Mutation:** skip the rewrite -> the pin reds on `cc/_working_summary.md`.

### 1-E `DEF-1082`, `DEF-1187` -- the CI clause is presence-gated; the template reads the tree

`KILL_SWITCH_DETECTED` gains a `{ci_clause}` slot filled from a presence read of
`tools/cc/ci_guard.py` and `.github/workflows/harness-guard.yml`: "CI will still fail the
merge" when both exist, "nothing downstream re-checks this on this repository" otherwise. The
SessionStart kill-switch WARN in `tools/cc/hooks/session_start.py::_report_integrity_state`
("tracked protected changes are enforced by CI") and `_build_claude_md`'s "CI guarantees" and
"...and CI" sentences take the same predicate
(`espalier/managed_inventory.py::get_install_ci_artifacts` is the engine's read).

**The root is passed, never read off the fingerprint.** `RepoFingerprint.to_dict` writes
`repo_root` as `.` (`espalier/models.py`), so a predicate keyed on `fp.repo_root` resolves
against the process cwd, not the tree, and `espalier upgrade /path` run from elsewhere answers
for the wrong tree. `_build_claude_md(fp, harness, *, root: Path | None = None)`:
`deploy_harness` passes its `repo_root`; `render_canonical_template` passes nothing and the
neutral clause renders, so `tests/test_documented_claims.py::TestDeployTemplateSnapshots`
(which calls `render_canonical_template` directly) does not move.

`DEF-1187`: `cmd_render_template` -- the arm `init`'s NOTE sends an adopter with a tracked
`CLAUDE.md` to -- reads `reports/repo_fingerprint.json` under the cwd when present
(`RepoFingerprint.from_dict`; the read `espalier/cli.py::_saved_test_commands` already makes)
and renders `_build_claude_md(saved_fp, plan, root=cwd)`; absent or unreadable, the canonical
render as today. A `--canonical` flag forces the fixed fingerprint; the snapshot recipe the test
prints (`python3 -m espalier.cli render-template claude > examples/CLAUDE.template.md`) gains
it, because this tree holds a gitignored `reports/repo_fingerprint.json` and would otherwise
regenerate the self-host render. `docs/CHEAT-SHEET.md`'s preview line and `tests/test_init.py`'s
two NOTE asserts name the command without a flag and stay as they are.

**Mutations:** format the deny on a tmp tree without the two files and assert the clause -> red
before the fix; `render-template claude` run in the scratch Node tree after `init` ->
`**Languages:** python` present before the fix, absent after; `--canonical` there -> present.
**Refutation:** a third caller of `_build_claude_md` with no root in scope
(`grep -n '_build_claude_md(' espalier/cli.py` prints two call sites today) needs the keyword's
default to be the neutral clause, never a cwd read. Vendor sync after.

### 1-F `DEF-1186` -- `/handoff` step 6 creates its summary directory

> **Landed 2026-10-09 on `lane/first-week-papercuts`, pulled forward:** the body
> creates the directory before its first append, pinned by
> `tests/test_command_surface_truth.py::TestHandoffCreatesTheSummaryDirectory`;
> `DEF-1186` is struck. Nothing left for this task.

In `.claude/commands/handoff.md`, the step-6 fence gains `mkdir -p cc/blueprints/compact_summaries`
as the line before its `printf ... >>` append (idempotent; `cc/blueprints/` is gitignored, so the
directory is created on every tree and committed on none). Then `python3 scripts/sync_claude_mirrors.py`.
Pin: `tests/test_handoff_mechanics.py` gains one test reading the deployed body's step-6 fence
on an init'd Node tree (`tests/_adopter_tree.py::build_adopter_tree`) and asserting a `mkdir`
naming the directory precedes the first `>>` into it -- the filed probe's own read.
**Mutation:** drop the `mkdir` line -> red; the filed probe reads `False` -> `True`.

### 2-A The seed list (after 0-D)

Per the operator's answers: edit `_SEED_DOC_REL_PATHS` and `_SEED_DOCS_WITH_ADAPT_HEADER`,
then `scripts/sync_asset_docs.py::_MIRRORED`, run the asset-docs sync, re-anchor
`tests/test_deploy_doc_parity.py::test_seeded_doc_links_resolve_to_deployed_targets` for a
dropped seed; its links from kept seeds are deleted or re-pointed (§C18's ship-or-delete rule).
`espalier/fuse.py` and `espalier/surface_contract.py` read the list too (the authoring
scope-check found them); run `tests/test_cli_deploy.py` and the fuse tests after a drop.
**Mutation:** drop a seed and leave one link -> the parity test reds.

### 2-B `DEF-987`'s fifteen passages (after 0-D)

Appendix A prints, per kept seed, the sections with hits. The operator marks each block
move / strip / attribute; the executor applies them in `docs/` (the SoT) and syncs. The row says
no probe separates a kept register from a leaked one; the pack adds none and records the
answers in Landing.

### 2-C First-run text

- `DEF-1028`: name `.claude/workflows/` in `README.md#quick-start`, `#project-structure`,
  `docs/CHEAT-SHEET.md#commands-by-category`, the two uninstall paragraphs, and
  `espalier/cli.py::_build_asset_tables` (a fourth table); add a README source to the
  `review workflow count` entry of `tests/test_documented_claims.py::NUMERIC_CONTRACTS`.
  Measured: `grep -c '\.claude/workflows' README.md docs/CHEAT-SHEET.md docs/TROUBLESHOOTING.md` -> `0 0 0`.
- `DEF-1005`: register the four `blob/main` sites in `VERSION_SURFACES` as `blob/v{version}`;
  `scripts/release_check.py` and `scripts/build_release_archive.py` read that registry, so the
  cut verifies them.
- `DEF-1006`: drop the two `docs/CLI_EXIT_CODES.md` cites in `build_parser` (the codes are
  printed inline) -- the delete side of §C18's rule.
  Each row's probe flips.

### 3-A Red-team (budgeted; see Risks)

`code-reviewer` and `failure-mode-reviewer` on a snapshot clone built from the diff against
HEAD, edits frozen. Ask for the mutation that survives: a marker green on `.claude/` and
flooding `docs/`; an allowlist reason that is a disclaimer; a strip not idempotent across
`init` -> `upgrade`; a presence read keyed on the wrong CI file.

## Affected symbols

### Changed-semantics

Two declarations the walk does not carry as symbols. The `.claude/commands/handoff.md` step-6
body edit (1-F, `DEF-1186`) has no symbol; the file is in Scope (in)'s paths. The
`tools/cc/ledger_row.py` edit is keyed on `strike`, whose bare name is the ledger's own verb and
matches about 1,300 prose lines tree-wide (the authoring scope-check's count), so its bullet is
struck from the walk and the file, too, is in Scope (in)'s paths.

- `espalier/surface_hygiene.py::internal_id_hits` (its module gains the maintainer vocabulary beside it; callers unchanged)
- `espalier/cli.py::_asset_transform` (composes the self-host-block strip on a non-self-host tree; 1-C)
- `espalier/render_surface.py::render_live_surface` (adopter-neutral header)
- `espalier/render_surface.py::render_pack_manifest` (adopter-neutral header)
- `tools/cc/hooks/post_compact.py::_capture_compact_summary` (rewrites the transcript sentence before both writes)
- `tools/cc/hooks/_denial_reasons.py::KILL_SWITCH_DETECTED` (CI clause presence-gated)
- `tools/cc/hooks/session_start.py::_report_integrity_state` (the kill-switch WARN's CI clause presence-gated; `DEF-1082`)
- `tools/cc/hooks/_speedbump.py::CP_RELEASE` (body generic off self-host)
- ~~`tools/cc/ledger_row.py::strike`~~ (withdrawn from the walk only, per the note above; the edit stands: the `DEF-412a` literal in `strike`'s stderr and in `main`'s `--despite-deferrals` help becomes the rule's name)
- `espalier/cli.py::_build_claude_md` (CI clauses presence-gated through an explicit `root` keyword, default neutral; `deploy_harness` passes its `repo_root`, `render_canonical_template` passes nothing and its output does not move; `DEF-1082`)
- `espalier/cli.py::cmd_render_template` (renders against the cwd's saved fingerprint when present; `--canonical` forces the fixed one; `DEF-1187`)
- `espalier/surface_impact.py::_scan_existing` (reads `maintainer_marker_hits` beside `internal_id_hits`, under the same `off_self_host` gate)
- `espalier/cli.py::_build_asset_tables` (a fourth kind, workflows; `DEF-1028`)
- `espalier/cli.py::build_parser` (the two `docs/CLI_EXIT_CODES.md` cites dropped; `DEF-1006`)
- `espalier/version_surfaces.py::VERSION_SURFACES` (the four link sites; `DEF-1005`)
- `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS` (only under 2-A, per the operator)
- `espalier/managed_inventory.py::_SEED_DOCS_WITH_ADAPT_HEADER` (only under 2-A)
- `tests/test_init_tier_split.py::TestCommonTierAssetHygiene` (docstring points at the new module; its two checks stay)

### Renamed

- (none -- the existing denylists keep their names.)

### Added-paths

- `espalier/surface_hygiene.py::MAINTAINER_MARKER_PATTERNS`
- `espalier/surface_hygiene.py::SELF_HOST_EXAMPLE_LABEL_RE`
- `espalier/surface_hygiene.py::maintainer_marker_hits`
- `espalier/cli.py::_SELF_HOST_BLOCK_RE` (1-C only)
- `espalier/cli.py::_strip_self_host_blocks` (1-C only)
- `tests/test_deployed_text_audience.py`
- `task-packs/TP-473-what-init-ships-is-addressed-to-the-adopter.md`

### Removed-paths

- (none at authoring -- a seed dropped under 2-A is the operator's call, declared in Landing.)

## Reach

Members derived by: the §C71, §C72 and §C54 sections
(`grep -nE '^### §C7[12] |^### §C54 ' task-packs/FORWARD_LEDGER.md`), the §4A pair the brief
named, and the §C0 rows sited on deployed bodies or first-run text
(`grep -nE '^\| \`DEF-(944|988|999|1040|1141|1148|901|1049|903|912|994|996|1005|993|1006|1028|889|1186|1187)\` ' task-packs/FORWARD_LEDGER.md`).
Not an absence proof: a row may name this shape in words no grep reads, and Appendix A is a
first-cut regex set calibrated in 0-C.

| Item | Status | Evidence |
|---|---|---|
| `DEF-1075` | **CLOSED by 1-A, 1-B** | the gate reds on a planted id, path, marker and trailer; `.claude/`, the two headers and the Python strings at zero outside the allowlist; its probe flips to `True` |
| `DEF-1076` | **CLOSED by 1-D** | the home-path pin over a driven compaction reds without the rewrite; its probe falls from `1` |
| `DEF-1074` | **CLOSED by 1-B, 1-C on the fence-and-strip fork; NOT REACHED otherwise** | waits on `DEC-32` for the template-is-source redesign, as the row says |
| `DEF-1082` | **CLOSED by 1-E** | deny, WARN and template take the presence predicate; its probe flips |
| `DEF-987` | **INSTRUMENTED by 2-B; decided by the operator** | fifteen per-block answers in Landing; the row says no probe can judge them |
| `DEC-30`, `DEC-38` | **PRESENTED at 0-D** | the size command and the per-seed table; a recommended default; 2-A executes the answer |
| `DEF-1028`, `DEF-1005`, `DEF-1006` | **CLOSED by 2-C** | each probe flips |
| `DEF-1186` | **CLOSED by 1-F** | the deployed body creates the directory before its first append; the filed probe reads `False` -> `True` on an init'd Node tree |
| `DEF-1187` | **CLOSED by 1-E** | `render-template claude` in a tree holding a Node fingerprint prints no `Languages: python`; the filed probe reads the canonical fallback, which this fix keeps, so it cannot flip -- the coordinator re-declares it to 1-E's render oracle |
| `DEF-988` | **CLOSED by 1-B** | the literal is a gate hit; the fixture tree with `done/` reds it |
| `DEF-1049` | **NOT REACHED** | folded into the axes pack (its Decision 6) |
| `DEF-1077`, `DEF-1080` | **NOT REACHED** | owned by `TP-474` and `TP-470` (Scope (out)) |
| `DEF-944`, `DEF-1040`, `DEF-1141`, `DEF-1148`, `DEF-901` | **NOT REACHED** | behaviour-shaped; a positive-match scanner cannot see them |
| `DEF-993`, `DEF-912`, `DEF-994`, `DEF-996`, `DEF-903`, `DEF-889` | **NOT REACHED** | not audience-shaped (Scope (out)) |

## Pass criteria

- `tests/test_deployed_text_audience.py` is green and was seen red against each 1-A mutation
  (in Landing). `.claude/`, the two `cc/` headers and the vendored Python strings carry zero
  unallowlisted hits; the seeded-docs count is at or below its dated floor.
- Every allowlist reason is a judgment, never a disclaimer sentence quoted from the body.
- **No assertion in an existing test is weakened**; `TestCommonTierAssetHygiene`'s two checks
  and the home-path gate's shape sets keep every pattern. Strengthening is allowed and recorded.
- `python3 scripts/sync_claude_mirrors.py --check`, `python3 scripts/sync_vendor_cc.py --check`
  and `python3 scripts/sync_asset_docs.py --check` each exit 0; the `claude-asset`,
  `claude-dogfooding`, `vendor-cc` and `asset-docs` pins named in `MIRROR_ROWS` are green.
- The `DEF-1075`, `DEF-1076`, `DEF-1082`, `DEF-1005`, `DEF-1006`, `DEF-1028`, `DEF-1186` probes
  flip (`python3 tools/cc/check_ledger_probes.py --id <id>`); `DEF-1187`'s render oracle (1-E)
  prints no `Languages: python` in the scratch Node tree and does print it under `--canonical`.
- The `self-host-path` family reports nothing on a line carrying `# Espalier-Harness tree:`, and
  the gate was seen red with that label stripped from one `implement-task.md` proof line.
- A fresh `espalier init` on the scratch Node tree, re-scanned with Appendix A, reports the
  `.claude/` roots at zero hits outside fenced blocks (zero, on the strip fork).
- `python3 scripts/proof_tier.py --base origin/main` names the tier (expect `full`:
  `tools/cc/hooks/` changes), and it is green.

## Files touched

- **New:** `tests/test_deployed_text_audience.py`; this pack.
- **Modified:** `espalier/surface_hygiene.py`, `espalier/cli.py`, `espalier/render_surface.py`,
  `espalier/version_surfaces.py`, `espalier/surface_impact.py`; `tools/cc/hooks/post_compact.py`,
  `tools/cc/hooks/_denial_reasons.py`, `tools/cc/hooks/_speedbump.py`,
  `tools/cc/hooks/session_start.py` (the WARN), `tools/cc/ledger_row.py`, and
  `espalier/_vendor/cc/` by the sync; `.claude/commands/handoff.md`,
  `.claude/commands/implement-pack.md`, `.claude/skills/hook-authoring/SKILL.md` and the bodies
  1-A names, with `espalier/assets/claude/` and `examples/dogfooding/.claude/` by the sync;
  `tests/test_render_surface.py`, `tests/test_deployed_assets_home_path_shapes.py`,
  `tests/test_documented_claims.py` (the `NUMERIC_CONTRACTS` source and the snapshot recipe's
  `--canonical`), `tests/test_init_tier_split.py` (docstring), `tests/test_handoff_mechanics.py`
  (the 1-F pin); `README.md`,
  `docs/CHEAT-SHEET.md`, `docs/TROUBLESHOOTING.md`, `docs/QUICKSTART.md` and `espalier/assets/docs/`
  by the sync; under 2-A only: `espalier/managed_inventory.py`, `scripts/sync_asset_docs.py`,
  `tests/test_deploy_doc_parity.py`; `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`
  (the strikes, by the coordinator's verbs).
- **Unmodified on purpose:** `SPECIFIC_ID_RE` and `FORBIDDEN_SELF_HOST_PATTERNS`;
  `tests/conftest.py` (its claim was released today; no row is owed -- Scope (out), Risks 9);
  `bench/`, `CHANGELOG.md` (claimed); the guard predicates in `tools/cc/hooks/write_guard.py`
  and `tools/cc/hooks/plan_guard.py`.

**Authoring scope-check** (2026-10-07, after the review fold; `python3 -m espalier scope-check`
on this file): exit 2, 51 files declared, 115 in scope, 24 symbols walked and one withdrawn by
strike (`tools/cc/ledger_row.py::strike`, the note under Changed-semantics). The gap lines left
are: the gitignored runtime records under `cc/blueprints/` and `cc/execution_plan.json`; record
surfaces (`memory/CONVERGENCE_LEDGER.md`, `task-packs/Done/`, `task-packs/Deferred/`,
`task-packs/Merged/`, the two pre-rebuild ledgers, the 2026-08-05 archives, the pre-cut RUNBOOK);
prose mentions in `CONTRIBUTING.md`, `WINDOWS_FUSE_NOTES.md`, `examples/README.md` and three
`memory/` entries; two self-host scripts (`scripts/derived_population_census.py` reads
`build_parser`, `scripts/sync_checklist_regions.py` names `TestCommonTierAssetHygiene` in a
comment); and the sibling packs `TP-471` and `TP-472`, which cite `_asset_transform` and
`_build_claude_md` in prose (Risks 7). Accept the gap with this reason only if the list is
unchanged in kind at execution.

## Sub-task ordering

0. Pre-flight per `memory/task-packs.md`: `code-reviewer` with `tools/cc/pack_artifact_checklist.md`;
   `python3 -m espalier scope-check task-packs/TP-473-what-init-ships-is-addressed-to-the-adopter.md`;
   `python3 tools/cc/sister_site_probe.py --json`; `python3 -m espalier surface-impact <pack>`;
   then `python3 tools/cc/execution_plan.py create`.
1. **Task 0** 0-A (may end the pack), 0-B, 0-C, 0-E. Stop on 0-A's refutation; pause and
   report on 0-B's drift.
2. **1-A.** Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_deployed_text_audience.py tests/test_surface_hygiene_parity.py`
   (red first, listing the bodies).
3. **1-B,** last on the shared bodies (after `TP-470` 3-A, `TP-471` 3-A to 3-C and `TP-474` 3-B
   have merged; 1-B's lane order), both syncs. Checkpoint: 1-A's test plus
   `tests/test_package_resource_parity.py tests/test_vendor_cc_parity.py tests/test_render_surface.py`.
4. **1-C** (Decision 2), **1-D**, **1-E** (after `TP-472` 1-B, `TP-470` 1-B and `TP-474` 2-A have
   merged; Risks 7), **1-F,** vendor sync and the claude-mirror sync. Checkpoint:
   `tests/test_cli_deploy.py tests/test_deployed_assets_home_path_shapes.py tests/test_denial_reasons.py tests/test_handoff_mechanics.py tests/test_documented_claims.py`,
   then `python3 tools/cc/check_ledger_probes.py --id DEF-1186` and 1-E's render oracle.
5. **0-D** with the operator. The gate lane may ship here (`/handoff`, one push).
6. **2-A, 2-B,** asset-docs sync. Checkpoint: `tests/test_deploy_doc_parity.py` and 1-A's test.
7. **2-C.** Checkpoint: `tests/test_documented_claims.py tests/test_cli_commands.py`, three probes.
8. **3-A** red-team, one fix batch.
9. The tier the diff earns under `nohup` with `EXIT=$?` appended; the strikes; `/handoff`.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 (0-C's hand classification is the bulk) | 3 h |
| 1-A | 3 h |
| 1-B | half a day (one body at a time, the gate as the list) |
| 1-C, 1-D, 1-E (`DEF-1187`'s arm and flag add an hour) | 4 h |
| 1-F | 0.5 h |
| 0-D | the operator's time |
| 2-A, 2-B | half a day plus the operator's fifteen answers |
| 2-C | 2 h |
| Red-team and fix batch | 3 h |

About three days of lane time in two lanes (gate; inventory). Pack budgets here have run about
2.7 times over on the one pack measured; read this as a floor.

## Risks — what this pack most likely got wrong

1. **The marker set is the author's, not derived.** 0-C's bound is the defence; a family that
   is clean on `.claude/` and floods `docs/` gets a per-root floor, not a drop.
2. **The strip is a third deploy-time render on one seam**, and `upgrade`'s re-render defect
   (`DEF-1063`, `TP-474`'s) sits on it. 1-C's refutation is the idempotence drive; if it
   fails, 1-C waits for `TP-474`.
3. **An allowlist is a disclaimer with a different name.** The reason field and the review are
   the only guard; the red-team is asked for an entry that reads as prose.
4. **The seed figure is a snapshot** (23 and 873,882 today); the pass criterion names the command.
5. **`DEF-1082`'s predicate may key on the wrong file.** `ci_guard.py` ships without a marker
   and survives `clean-generated` (`DEC-10`), so "present" can mean "left behind"; 1-E reads
   both files and says "the CI gate files are present" rather than "CI guarantees".
6. **Two writers on `docs/`.** 2-B edits the SoT under `docs/` while 1-B edits `.claude/`; both
   sync into `espalier/assets/`. One lane, or serialise the syncs.
7. **Shared production symbols: two hook modules and the body lane.**
   `tools/cc/hooks/_denial_reasons.py`: `TP-472` 1-B edits `HARNESS_ENV_PREFIX_INLINE`, 1-E edits
   `KILL_SWITCH_DETECTED` -- different constants in one module; `TP-472` lands first and 1-E
   rebases. `tools/cc/hooks/session_start.py`: `TP-470` 1-B edits `_build_context` and
   `_build_compact_context`; `TP-474` 2-A reaches this hook's import block if its kept-helper
   shape extends to the reporters (its Task 0 names this hook's exit 1 on the skew); 1-E edits
   the WARN in `_report_integrity_state` -- three regions; order `TP-470`, `TP-474`, then this
   pack. Both modules replay into `espalier/_vendor/cc/` through `sync_vendor_cc.py`: resolve in
   `tools/cc/` and re-sync, never in the mirror, and a hand resolve on either is the signal to
   re-read both packs before continuing. The shared bodies take decision 2's order (1-B's lane
   order: `TP-470` 3-A, `TP-471` 3-A to 3-C, `TP-474` 3-B, then 1-B last).
   `espalier/cli.py::_asset_transform` and `::_build_claude_md` are this pack's alone: `TP-471`
   scopes deploy-time rendering out and `TP-472` leaves `_build_claude_md` unmodified
   (`grep -n '_asset_transform\|_build_claude_md' task-packs/TP-471-*.md task-packs/TP-472-*.md`
   prints prose and an "Unmodified" line, no sub-task).
8. **The label exemption is a second reader of one grammar.** `TP-471` 3-D's `LABELS` tuple
   admits three spellings (`Espalier-Harness tree`, `Espalier source repo`, `use yours instead`);
   1-A's `SELF_HOST_EXAMPLE_LABEL_RE` reads the first, trailing, per decision 3. A proof line 3-D
   passes under the other two spellings and 1-A refuses is the divergence; once 3-D has landed,
   1-A's regex takes the tuple's spellings, and the red-team is asked for a line one gate passes
   and the other refuses.
9. **`tests/conftest.py` needs no row.** The new module is `unit` by name and spawns no hook; the
   1-F pin lands in an existing module. If 0-E's slow fork makes 1-A's test spawn `init`, the
   `# slow-exempt:` docstring idiom is the fix (`tests/test_test_suite_contract.py` reads it),
   not a conftest edit.

## Decisions (the 0-D checkpoint; recommended defaults in bold)

1. **`DEC-30` -- which seeds ship.** 23 seeds, 873,882 bytes on the rehearsal tree;
   `docs/FAILURE_MODES.md` is 60 % of it. The 2026-09-05 stance stands: `FAILURE_MODES.md` and
   `SHARP_EDGES.md` ship. For the other 21: (a) keep all, 1-A's floor ratcheting them down;
   (b) drop the seeds Appendix A scores wholly maintainer-addressed (today `docs/ENV_CATALOG.md`
   and `docs/TASK_RECIPES.md` lead; the per-seed table decides); (c) exclude at the public-repo
   boundary per `DEC-25`. **Recommended: (b) for the leaders, (a) for the rest** -- a drop is a
   2-A edit plus a link re-anchor, and the floor keeps the rest honest.
2. **`DEF-1074` mechanism.** (a) **fence-and-strip at deploy (1-C), `DEC-32`-neutral**;
   (b) wait for `DEC-32`, ship fenced-but-unstripped bodies under the allowlist. (a) lands
   without choosing `DEC-32` and retains both of its options.
3. **`DEC-38` -- where seeds land.** (a) namespace under `docs/espalier/` (283 occurrences in 58
   files to re-anchor at the row's measurement; `plan_guard`'s `docs/` exemption survives only
   under `docs/`); (b) **keep the placement**; (c) independently, let `clean-generated` delete
   provably untouched seeds. (b) now, (c) as its own row: the migration is a lane of its own
   and buys nothing the audience gate needs.
4. **`DEF-987`'s fifteen blocks:** move / strip / attribute, per block, from 2-B's table.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:

## Appendix A — the authoring scanner (an instrument, not a deliverable)

`<scratch>/pack-TP-473/audience_scan.py`, stdlib only:
`python3 audience_scan.py <init'd tree> --top 20 --per-marker`. Population: files carrying
`espalier:managed` or `espalier:seed`, plus `cc/**`, `ESPALIER_MEMORY.md`, `tools/cc/**/*.py`
(non-docstring strings through `ast`). Markers: `\b(?:DEF|DEC|INV|LG|TP|BC|EI)-\d+[a-z]?\b|§C\d+`;
`scripts/`, `espalier/`, `tests/`, `bench/` paths; the approval marker's literal; `task-packs/Done/`;
`self-host`; `this repo(sitory)`; `Espalier-Harness` within a line's first 80 characters;
`measured 20YY-MM-DD`; `Co-Authored-By: Claude, Scion`. Output, 2026-10-07:

```
population=111 files_with_hits=70 total_hits=806
by marker: tests/test_*.py=179, Espalier-Harness header=130, ledger-id=101, this repo(sitory)=96,
  self-host=89, scripts/=87, espalier/=72, bench/=16, approval-marker=15, dated measurement=15,
  task-packs/Done/=5, co-author trailer=1
top: docs/FAILURE_MODES.md 169; docs/HOOKS.md 66; tools/cc/hooks/_reinject.py 63;
  .claude/commands/preflight.md 37; .claude/skills/hook-authoring/SKILL.md 31; docs/ENV_CATALOG.md 29;
  .claude/commands/implement-pack.md 27; task-packs/FORWARD_LEDGER.md 24 (13 are §C grammar);
  docs/INSTALL-CI.md 23; .claude/commands/handoff.md 22; .claude/commands/implement-task.md 22
zero-hit files: 41
```

Section census: split `docs/FAILURE_MODES.md` at `(?m)^(?=#{2,3} )`; count sections matching the
id grammar, a `tests/`, `espalier/` or `tools/cc/` `.py` path, or `\b(?:pytest|ruff|mypy)\b`
-> 247 sections, 49 citing internals.
