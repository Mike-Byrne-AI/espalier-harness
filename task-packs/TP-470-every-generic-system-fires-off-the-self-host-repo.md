# TP-470 — Every generic system fires off the self-host repo

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: three hook modules (`tools/cc/hooks/_reinject.py`, `tools/cc/hooks/post_write_check.py`,
  `tools/cc/hooks/session_start.py`; vendored mirror re-synced), one engine tuple
  (`espalier/cli.py::SELF_HOST_ONLY_SCANNERS`) and one scanner's walk scope, four shipped command
  bodies (`implement-task`, `preflight`, `implement-pack`, `scan`; two mirrors re-synced), one
  SHARP_EDGES entry rewritten, one HOOKS.md sentence (asset-docs mirror re-synced), the tests that
  encode the old gates, and one
  new class test that drives every un-gated feature on an init'd temp tree.
- **Kind: PACK**. Task 0 can end it, or shrink it to the sites that survive the drive.
- Gate: DRAFT, 2026-10-07. Authored at `febfcd4e` on the Air (`python3` only), against a scratch Node
  tree init'd today; every measured sentence names its command.
- Ledger: the unit of work for `DEF-1080` (the PostToolUse advisories), `DEF-1090` (the banner's
  standing-principles index) and `DEF-1115` (the encoding scanner). `DEF-1122` is a class member
  that is **not reached** (Reach says why). Two findings filed today ride as `DEF-1180` (closed by
  3-A) and `DEF-1181` (not reached).
- Cross-pack: §C58 and §C75 (`DEF-1002`, `DEF-1003`, `DEF-1158`, `DEF-1098`, `DEF-1099`) share this
  pack's oracle shape, an init'd temp tree, but their defect is the inverse one (a harness path
  presented as an adopter finding) and their unit is the agent and skill fences; not reached here.
  TP-468's `tests/_adopter_tree.py::build_adopter_tree` is the tree builder the class test uses.

## Motivation

The harness built several systems for every adopter and then put them behind the self-host
identity check, or behind a path list that names only the harness's own tree. Off the
Espalier-Harness repo they never fire, and no surface says so. The adopter who is hurt
(`docs/STANDING_PRINCIPLES.md` §16): one who adds a skip to a test and gets none of the push
advisories the maintainer's own tree gets (`DEF-1080`); one who writes
`docs/STANDING_PRINCIPLES.md` and sees it in `/recall` but never in the banner (`DEF-1090`); one on
a non-UTF-8 locale whose `/scan` reads `Encoding: n/a` (`DEF-1115`); and one whose `src/` change
goes to `/preflight` and is never reviewed, because the review trigger list is the harness's six
surfaces (`DEF-1180`).

**The predicate itself is right.** `tools/cc/hooks/_hook_utils.py::is_self_host_repo` and its
engine twin `espalier/surface_contract.py::is_self_host_repo` answer "is this the harness's own
tree", and most callers ask exactly that (deploy-source identity, mode labels, whose
`.github/workflows/` this is). The class is the callers that ask it in place of a different
question: "does the content I am about to render exist here", "is this row's text true on every
tree", "is this path adopter source". The fix at each such site asks the right question, with the
self-host answer unchanged.

**Measured today (2026-10-07) on an init'd scratch Node tree** (`is_self_host_repo` reads `False`
there; Task 0 names the drives):

| Drive | What was done | Result |
|---|---|---|
| A | PostToolUse `Edit` through `post_write_check.py`: `test.skip(` into `test/widget.test.js` | `0 B` stdout |
| B | the same hook, `@pytest.mark.skip` into `tests/test_widget.py` | `0 B` stdout |
| C | `_reinject.check("PostToolUse", "Edit", <A's input>, root)` asked directly | `0` rows render |
| D | `_reinject.check(..., <B's input>, root)` asked directly | `2` rows: `REINJECT-NEW-TEST-FILE-CLASSIFY` (names `tests/conftest.py::_MARKER_RULES`, which the adopter lacks) **then** `REINJECT-TEST-LOOSENING` |
| I | `check(..., "Bash", {"command": "git archive ..."}, root)` | `1` row, `REINJECT-ARTIFACT-PROXY-ORACLE`, generic text |
| J | `check(..., "Write", <the adopter's own new .claude/commands/deploy.md>, root)` | `2` rows, both about mirrors the adopter lacks |
| E | `session_start.py` with an adopter-written `docs/STANDING_PRINCIPLES.md` (two sections) | banner `3151` bytes, no `STANDING PRINCIPLES` section; the `/recall` bullet names the file as indexed |
| F | `session_start._standing_principles_index(root)` asked directly | `138` bytes, the two titles |
| G | `tools/cc/hooks/_recall.py "one writer per file"` on that tree | the principle is returned first |
| H | `espalier scan .` with a planted `src/tool.py` holding `open(p).read()` | `Encoding: n/a`; `reports/scan_encoding_contracts.json` reads `ran: false`; `Test-loosening: 2` (the offline scanner is generic and ran) |

Read together: B and D say the call-site gate is the only wall between `TEST_LOOSENING` and a
Python adopter; D and J say a bare flip of that gate would also inject harness-content rows,
which is the objection `docs/SHARP_EDGES.md :: Advisory reinject rules need the same self-host
gate as observers` records; C says the loosening row's own shape (`_TEST_PATH_RE` is
`(^|/)tests/`, `_TEST_LOOSEN_RE` is pytest's markers) is a **second** wall for a Node adopter
(`DEF-1181`). E and F say the banner withholds content its own renderer produces; G says
`/recall` already un-gated it. H says the encoding scanner stands down with a finding to make.

### The census, derived

The identity-gate sites are Appendix A, run from the repository root:

```bash
python3 <appendix-A-path>/census.py .      # path::enclosing-symbol, kind, line
```

At authoring it printed 54 lines across 19 source files (13 in `espalier/cli.py`). The two grep
forms are not the oracle: `grep -rl is_self_host_repo tools/cc/ | wc -l` read `19` today, ten of
them `__pycache__/*.pyc` (add `--include='*.py'`); `grep -rn is_self_host_repo tools/cc/hooks/`
names eight modules, three of which (`_reinject.py`, `_denial_reasons.py`, `write_guard.py`) carry
the name in comments only. Shipped bodies are a second population, derived by
`grep -nE 'self-host|is_self_host_repo|\[ -f (espalier|scripts)/' .claude/commands/*.md .claude/skills/*/SKILL.md`.
A citation correction for the ledger: `DEF-1080` names `post_write_check.py::_run_main`; the gate
sits in `tools/cc/hooks/post_write_check.py::_check`, which `_run_main` calls.

## Scope (in)

1. **1-A** A scope per PostToolUse advisory row, and a call site that lets an any-tree row fire on
   any tree (`DEF-1080`): `TEST_LOOSENING_RULE` and `ARTIFACT_PROXY_RULE` become any-tree; the other
   eighteen stay self-host. Files: `tools/cc/hooks/_reinject.py`, `tools/cc/hooks/post_write_check.py`,
   `docs/SHARP_EDGES.md` (the entry that forbids an any-tree row, rewritten); then
   `python3 scripts/sync_vendor_cc.py`.
2. **1-B** The content gate in place of `if self_host:` at both banner sites (`DEF-1090`). Files:
   `tools/cc/hooks/session_start.py`, `docs/HOOKS.md` (§1, one sentence),
   `tests/test_adopter_pointer_resolution.py` (the derived exemption), `tests/test_deploy_doc_parity.py`
   (one comment and one reason string), `tests/test_session_banner.py`; then
   `python3 scripts/sync_vendor_cc.py` and `python3 scripts/sync_asset_docs.py` (`docs/HOOKS.md` is on
   the `asset-docs` row of `espalier/mirror_registry.py`, mirrored to `espalier/assets/docs/HOOKS.md`;
   1-A's `docs/SHARP_EDGES.md` is not on that row, derived: `ls espalier/assets/docs/`).
3. **2-A** `encoding_contracts` out of the self-host tuple, its walk bounded off self-host
   (`DEF-1115`). Files: `espalier/cli.py`, `espalier/scanners/encoding_contracts.py`,
   `.claude/commands/scan.md`, `tests/test_cmd_scan_self_host_gate.py`; then
   `python3 scripts/sync_claude_mirrors.py`.
4. **3-A** The review trigger surface derived in the three ship-boundary bodies (`DEF-1180`).
   Files: `.claude/commands/implement-task.md`, `.claude/commands/preflight.md`,
   `.claude/commands/implement-pack.md`, `tests/test_documented_claims.py`; then
   `python3 scripts/sync_claude_mirrors.py`.
5. **4-A** The class test, `tests/test_adopter_generic_systems_fire.py`: an init'd temp tree on which
   each un-gated feature is driven and fires, and on which no self-host-scoped row fires.
6. **Pinned, read, unchanged unless the new rule reds them:** `tests/test_reinject.py`,
   `tests/test_reinject_pins.py`, `tests/test_reinject_sync.py`, `tests/test_scanner_encoding_contracts.py`,
   `tests/test_session_start_source_aware.py`, `tests/test_hooks.py`,
   `tests/test_hooks_worktree_checkouts.py` (calls `_bash_derived_payloads(..., already=0)`
   directly, so 1-A keeps that signature), `tests/test_exemplar_parity.py` (builds `ReinjectRule`
   by keyword, so `scope` keeps its default). `scripts/derived_population_census.py` derives rows
   from `SELF_HOST_ONLY_SCANNERS` and is re-run after 2-A. The vendored mirror
   `espalier/_vendor/cc/hooks/`, the two `.claude/` mirrors and `espalier/assets/docs/HOOKS.md` change
   only through the sync scripts.
7. **5-A** Red-team, one fix batch.

## Scope (out)

- `DEF-1087` (the `/recall` corpus is a fixed Espalier path list). Its fix is a corpus registry,
  not a gate flip; it is `TP-466b`'s unit (`task-packs/TP-466b-index-adopter-knowledge-in-place.md`,
  drafted in parallel today). This pack touches nothing in `tools/cc/hooks/_recall.py`.
- `DEF-5` (the generative push side ships with every exemplar `push_eligible=False`). Not this
  class: `_reinject.check` skips a generative row without `push_eligible` on **every** tree, and
  the registry holds zero generative rows (derived:
  `python3 -c "import sys; sys.path.insert(0,'tools/cc/hooks'); import _reinject as r; print([x.id for x in r.REINJECTS if x.face=='generative'], {e.push_eligible for e in r.EXEMPLAR_MAP.values()})"`
  printed `[] {False}` today). Its pull side's identity gate in `_recall.py::_iter_corpus` is
  harness-content (pointers at `espalier/scanners/`, `task-packs/`) and stays. For the coordinator,
  no edit here: the §3 row's site pointer `task-packs/FORWARD_LEDGER.md:1691` now lands on §C67.
- `DEF-1091` (recall telemetry hard-gated, no opt-in). A consent decision; its fix is an
  `espalier.toml` key, its own row.
- `DEF-1122` (load-bearing tool warnings self-host only). Right while the registry holds only
  ruff; the fix is a per-tool relevance predicate shared by `espalier/doctor.py` and
  `session_start.py`, a new rule rather than a flip. Reach names it NOT REACHED.
- §C58 / §C75 fences (`DEF-1002`, `DEF-1003`, `DEF-1158`, `DEF-1098`, `DEF-1099`): the inverse
  defect, in agent and skill bodies; one lane of their own on the same tree builder.
- Widening the loosening row's test-path and marker shapes to Node, Go and Rust idioms
  (`DEF-1181`): the stack table that landed with the stack-registry pack owns those idioms.
- The harness-only sites classified **keep** in Task 0's table: each already answers the right
  question.
- Files under the other machine's live claim are not edited. `tests/conftest.py` left that claim
  today (the coordinator); Risks 6 says why this pack still needs no row in it, names the one case
  that would, and the oracle to run before editing.

## Task 0 — Verify (may end this pack, or shrink it)

**Outcomes:** build; **partial** (a site re-classified harness-only or harness-content is dropped
with its measurement, and the rest continues); **do not build** (fewer than three generic-withheld
systems remain). On a refutation the exit is stop and re-raise with the measurement.

Run every step with `ESPALIER_*` stripped and against a throwaway tree, never this one. Records go
to `reports/tp470/` (gitignored).

### 0-A The census and the classification table

**Oracle:** Appendix A from the repository root, then the body grep above. Classify every line as
**H** harness-only (keep, with the reason), **W** generic-withheld (un-gate, with a scope or a
content gate), or **C** harness-content (rendered per tree already, or to be rendered or dropped).
At authoring (2026-10-07, `febfcd4e`) the table read as below; hook paths are under
`tools/cc/hooks/`, and `ci_guard.py`, `reflect_protocol.py`, `sister_site_probe.py` under `tools/cc/`.

| Site (`path::symbol`) | Class | Why |
|---|---|---|
| `post_write_check.py::_check` (the `check("PostToolUse", ...)` call and the Bash-derived path bridge beside it) | **W** | one gate over twenty rows; two rows' text is true everywhere (drives D, I) |
| `session_start.py::_build_context`, `::_build_compact_context` (the `if self_host:` around `_standing_principles_index`) | **W** | the renderer returns `''` without the file (drive F); `/recall` gates on existence |
| `espalier/cli.py::cmd_scan` via `SELF_HOST_ONLY_SCANNERS`, for `encoding_contracts` | **W** | generic AST shapes; the tuple's comment says the gate is for the walk's cost (drive H) |
| the step-6 review block of `implement-task.md`, `preflight.md`, `implement-pack.md` | **W** | a path list with the predicate's effect: adopter source never triggers a review (read; `fresh-init/REPORT.md` §9.7) |
| `session_start.py::_warn_if_load_bearing_tool_missing`; `espalier/doctor.py::run_doctor_check` (tool loop) | H today | the registry holds ruff only; `DEF-1122` |
| `_recall.py::indexes_failure_modes`, `::_iter_corpus` (exemplars); `post_compact.py::_run_main` | **C**, rendered | the banner asks the owner and says the shards are not indexed (drive E); the vocabulary line varies by tree |
| `_hook_utils.py::harness_protected_prefixes`, `::harness_exempt_prefixes`, `::harness_excluded_prefixes` | H | the adopter's `.github/workflows/` and `espalier/` are theirs |
| `_hook_utils.py::_telemetry_enabled`; `post_write_check.py::_check` (born-weak observer) | H | consent; `DEF-1091` |
| `ci_guard.py::approval_marker_required`; `reflect_protocol.py::_tree_identity`, `::_propose_ship_tier`; `sister_site_probe.py::_format_scope_lines` | H | marker required off self-host (the safe direction); a lesson routed to the adopter's catalog; a scope label |
| every `espalier/` site but `cmd_scan` (`espalier/cli.py::cmd_upgrade`, `::cmd_init`, `::_goal_seed_applies`, `::cmd_doctor`, `::_refresh_fingerprint_derivatives`; `doctor.py`, `managed_paths.py`, `diffing.py`, `repo_mode.py`, `pre_release.py`, `selfcheck.py`, `self_hosting.py`, `strengthen.py`, `audit_accuracy.py`, `surface_contract.py`) | H | ownership and deploy-source identity, mode labels, adopter-aware verdicts already in place |
| shipped bodies: `preflight.md` Steps 4 and 7, `handoff.md` 7b/7c, `implement-pack.md` self-host steps, `smoke.md`'s table check, `scope-check.md`'s matrix | H, labelled | each says it is self-host only; whether labelled text should ship at all is §C71's |
| `scan.md` rows marking the five scanners | **C** for `encoding_contracts` | follows 2-A |

**Refuting result:** a **W** site that, when driven on the init'd tree with its gate lifted, needs
state only the harness tree has. Drive D is the shape: lift the call-site gate and a
harness-content row fires. The exit is re-classify (here, to a per-row scope); if that leaves
fewer than three **W** systems, stop and re-raise.

### 0-B The drives

**Oracle:** `espalier init .` into a fresh git tree under a scratch path (a `package.json`, one
module under `src/`, one test under `test/`), then, with `CLAUDE_PROJECT_DIR` set to it and stdin
JSON per `docs/external/cc-hook-protocol.md`, the ten drives in Motivation, each a hook run as a
subprocess or a direct call on the deployed `tools/cc/hooks/` copy. The table carries hook, tool,
input and assertion; the script is reconstructed from it (60 lines), not carried.

**Refuting results:** D renders `TEST_LOOSENING` **alone** (then 1-A needs no scope, only a
call-site flip; Risks 1 falls away); F returns `''` (then 1-B's premise is wrong); H's
per-scanner report reads `ran: true` (2-A already landed); the deployed step-6 block names a path
outside the six harness surfaces (3-A already landed).

### 0-C The test the repair breaks first

**Oracle:** `pytest -q -m 'not heavy_e2e' tests/test_adopter_pointer_resolution.py` with 1-B's
three-line change applied in a throwaway copy. **Refuting result:** green with no test-side change,
in which case 1-B's test paragraph is dropped. **Expected (probable):**
`test_every_emitted_pointer_resolves` goes red, because `_self_host_only_functions` drops the
renderer by derivation and its emitted `docs/STANDING_PRINCIPLES.md` does not resolve on the
adopter tree. That red is the earn-the-red for 1-B's artifact-gated exemption.

## Relevant memory

Recent pattern: the last two flips of an identity gate to a content gate on this tree
(`_footgun_pointer`, `_memory_toc`) each dropped a renderer out of a **derived** test exemption and
were caught by the pointer-resolution arm, not by the banner tests
(`tests/test_adopter_pointer_resolution.py::_self_host_only_functions`, its docstring). The last gate
change to `_recall.py` shipped a doc-parity reason that said the opposite of the code until a
review caught it (`tests/test_deploy_doc_parity.py`, the `docs/STANDING_PRINCIPLES.md` entry still
carries the warning). The likeliest defect here is in the tests and docs that encode the **old**
gate, not in the flips.

| Entry | Where |
|---|---|
| Advisory reinject rules need the same self-host gate as observers | `docs/SHARP_EDGES.md :: Advisory reinject rules need the same self-host gate as observers` |
| The recall corpus must gate harness-internal entries for adopters | `docs/SHARP_EDGES.md :: The recall corpus must gate harness-internal entries for adopters` |
| A path in the seed list is not the content an adopter receives | `docs/SHARP_EDGES.md :: A path in the seed list is not the content an adopter receives` |
| Classify the surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Sister-site compression | `memory/sister-site-compression.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |

Resolved at authoring by `python3 tools/cc/hooks/_recall.py "<topic>"` with: `self-host gate
withholds a generic feature from an adopter`; `a shipped system that never fires off the self-host
repo and nothing says so`; `a whole-loop gate suppresses a new registry row for adopters`; `classify
the surface before measuring it`; `the content gate not the repo identity gate adopter authored the
file`. Re-run rather than trust this list if the pack has been sitting.

Folders touched, so the folder-`CLAUDE.md` ladder fires on entry: `tools/cc/hooks/` (vendored
mirror, `python3 scripts/sync_vendor_cc.py`); `.claude/commands/` (two mirrors,
`python3 scripts/sync_claude_mirrors.py`); `docs/` (`docs/HOOKS.md` is an asset-docs mirror,
`python3 scripts/sync_asset_docs.py`); `espalier/scanners/` (stdlib-only); `tests/` (a new module
is classified by `tests/conftest.py::_MARKER_RULES`; Risks 6).

## Implementation

Every fix below is a **fix shape, untested**, unless it says otherwise. Each names the mutation its
test must die to. Landing records that it did.

### 1-A A scope per advisory row (`DEF-1080`)

The row proposes a `scope` field read inside `check()`. The SHARP_EDGES entry's reason for gating at
the call site still holds for one case: the orientation and Rule A rows ride other hooks and must
stay ungated. A per-row scope satisfies both.

```python target=tools/cc/hooks/_reinject.py
    once_per_session: bool = False
    # Where the row may fire. "self_host": its witness names an Espalier internal
    # (the default -- see the SELF-HOST ONLY comment on the sync rows). "any": its
    # text is true on every tree; it rides the ungated call in post_write_check.
    scope: str = "self_host"
```

```python target=tools/cc/hooks/_reinject.py
TEST_LOOSENING_RULE = ReinjectRule(
    id="REINJECT-TEST-LOOSENING", event="PostToolUse",
    render=_render_test_loosening, face="sync", priority=60, scope="any",
)
```

The same one-token change on `ARTIFACT_PROXY_RULE`. Below `REINJECTS`:

```python target=tools/cc/hooks/_reinject.py
REINJECTS_ANY: tuple[ReinjectRule, ...] = tuple(r for r in REINJECTS if r.scope == "any")
REINJECTS_SELF_HOST: tuple[ReinjectRule, ...] = tuple(r for r in REINJECTS if r.scope != "any")
```

```python target=tools/cc/hooks/post_write_check.py
    _reinject_payloads = _reinject.check("PostToolUse", tool_name, tool_input, root_for_aj,
                                         rules=_reinject.REINJECTS_ANY)
    if _hook_utils.is_self_host_repo(root_for_aj):
        _reinject_payloads = _reinject_payloads + _reinject.check(
            "PostToolUse", tool_name, tool_input, root_for_aj,
            rules=_reinject.REINJECTS_SELF_HOST,
            budget=_reinject.REINJECT_PER_TURN_CAP - len(_reinject_payloads),
        )
```

The Bash-derived path bridge (`tools/cc/hooks/post_write_check.py::_bash_derived_payloads`) takes
the same two tuples. Then rewrite the `SELF-HOST ONLY` comment above the sync rows (its claim that
every witness names an Espalier internal is false for two rows) and the SHARP_EDGES entry, so a
row declares its scope and an any-tree row is allowed. Two tuples rather than a scope check inside
`check()` because the pointer-resolution arm reads AST reachability: today it sees every witness
constant in `_reinject.py` only through a call gated by `is_self_host_repo`, and keeping the
self-host rows behind a gated call keeps that model true without teaching the arm anything.

**Refutation:** if the arm resolves the whole module's constants through the ungated
`REINJECTS_ANY` call (it follows the module, not the tuple), the arm needs a derived rule and this
fix grows; 0-C's command with `-k code` decides before anything lands.

**Earn the red** (in 4-A, driven through the hook as a subprocess on the init'd tree): the
pytest-skip Edit yields exactly the loosening text and nothing naming
`tests/conftest.py::_MARKER_RULES`; the `git archive` Bash yields the artifact-proxy text; the
adopter's own `.claude/commands/deploy.md` Write yields nothing. Mutation 1: restore the single
gated call (the loosening assertion reds). Mutation 2: set `NEW_TEST_FILE_RULE` to `scope="any"`
(the negative half reds). Both reconstruct a real pre-fix or wrong-fix state.

### 1-B The content gate at both banner sites (`DEF-1090`)

```python target=tools/cc/hooks/session_start.py
    standing = _standing_principles_index(root)
    if standing:
        body_parts.append(_bounded("standing", standing, flags))
    if footgun_pointer:
        body_parts.append(footgun_pointer)
```

The same three lines replace the `if self_host:` block in `_build_compact_context`. Delete the two
comment blocks that record the deferral (their stated trigger has fired; drive G). In
`docs/HOOKS.md` §1, the sentence "STANDING PRINCIPLES is the one self-host-only section, because
`docs/STANDING_PRINCIPLES.md` reaches no adopter tree" becomes: the section renders wherever the
file has sections, which `init` never seeds, so an adopter sees it from the session after they
write it. In `tests/test_deploy_doc_parity.py`, the comment above the `docs/STANDING_PRINCIPLES.md`
entry says the index is rendered "ONLY when `is_self_host_repo`" and the reason string opens
"self-host standing-principles index; contributor lessons catalog, never adopter-deployed" (its own
⚠ clause already records that `/recall` gates on `sp.is_file()`); make the comment and that first
clause say the banner gates on the file too, and keep the ⚠ history. Then
`python3 scripts/sync_vendor_cc.py` and `python3 scripts/sync_asset_docs.py`; the latter's pin is
`tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity::test_source_asset_docs_are_byte_equal`,
red in the full tier if the `docs/HOOKS.md` edit lands without it.

**The test consequence (0-C):** `_self_host_only_functions` drops the renderer by derivation. Add
its sibling, derived not listed: a function whose every `return` of a non-empty string follows an
early `return ""` guarded by a read of the same path (`_safe_read(root / "docs" /
"STANDING_PRINCIPLES.md")`) is artifact-gated, and its emitted pointer resolves against the file's
presence, not the tree's inventory. If that cannot be derived in the arm's existing shape, say so
in Landing and take a hand-kept carve-out with the module's own warning beside it.

**Earn the red:** in `tests/test_session_banner.py::TestStandingPrinciplesIndex`, a new test builds
`_build_context(root, self_host=False, ...)` on a tree holding the file and asserts the index is in
the banner; mutation: restore `if self_host:` (red). In 4-A: drive E asserts the two titles appear.

### 2-A The encoding scanner runs everywhere, bounded (`DEF-1115`)

```python target=espalier/cli.py
SELF_HOST_ONLY_SCANNERS: tuple[str, ...] = (
    "subprocess_contracts", "filesystem_contracts", "magic_depth",
    "retired_vocab",
)
```

Then bound the walk off self-host: `espalier/scanners/encoding_contracts.py::_iter_scoped_files`
leaves out the vendored `tools/cc/` and the dependency directories
(`espalier/_safe_walk.py::dependency_dirs_for`, the stack table's list) when the tree is not the
harness, as `espalier/strengthen.py::_iter_repo_py` does; on the harness tree the walk is
unchanged. Edit `/scan`'s table row for `encoding_contracts` to drop "self-host only" and name the
exclusion. Amend `tests/test_cmd_scan_self_host_gate.py::test_pinned_scanners_emit_empty_reports_on_adopter`,
`::test_the_scan_body_marks_exactly_the_scanners_that_stand_down` and
`::test_gate_keeps_the_encoding_scanners_pragma_walks_off_an_adopter` to the four-scanner tuple;
the third's name records the cost reason, so its replacement asserts the bounded walk.

**Refutation:** if the scanner cannot tell the vendored `tools/cc/` from adopter code without an
import the scanner module may not take, un-gating turns `n/a` into a wall of findings about the
harness's own hooks (the `DEF-1158` shape), worse than today; then the exclusion belongs in
`cmd_scan` (pass the roots) and the scanner stays as it is.

**Earn the red:** on the init'd tree with `src/tool.py` holding `open(p).read()`,
`reports/scan_encoding_contracts.json` reads `ran: true` with `count >= 1`, no finding path starts
with `tools/cc/`, and `encoding_contracts` is absent from `scan_summary.json["not_run"]`. Mutation
1: re-add the key to the tuple (red). Mutation 2: drop the exclusion (the no-harness-path assertion
reds).

### 3-A The review trigger surface, derived (`DEF-1180`)

In the step-6 review block of `.claude/commands/implement-task.md`, `preflight.md` and
`implement-pack.md`, the fixed list (`tools/cc/`, `.claude/`, `.github/workflows/`, `bench/`,
`scripts/`, `espalier/`) becomes a two-branch rule: on the harness tree (the tell `/preflight` Step 4
uses, `[ -f espalier/surface_contract.py ]`) the six surfaces; on any other tree, the adopter's
source dispatches `code-reviewer`, and the branch's text names where that list comes from: the
`code-reviewer` agent's `primary_paths` in `reports/harness_config.json` when the file is present,
else every path the diff touches that is not harness-managed (`tools/cc/`, `cc/`, `.claude/`, the
seeded `docs/`, `memory/`, `task-packs/`, `ESPALIER_MEMORY.md`). `failure-mode-reviewer` keeps its
trigger (a hook, a gate, a body); the `.claude/` clause stays on both branches.

Why the complement is the fallback and not the only shape: `reports/harness_config.json` names
`code-reviewer -> ['README.md', 'src']` on the rehearsal tree (measured), but `/reports/` is
gitignored by `init` (measured on the scratch tree), so a teammate's clone lacks it until they run
`init` or `upgrade`. Why the text names the key at all: the filed `DEF-1180` probe reads the three
deployed bodies and counts those mentioning `tools/cc/` that name none of `harness_config.json`,
`primary_paths`, `package_roots`; a complement-only wording names none of them and leaves the
probe `STILL_OPEN` with the defect fixed (prescribed; refuted if the probe's key tuple in
`task-packs/LEDGER_PROBES.json` has moved -- read it before writing the block). Both shapes are
untested; if the complement proves too wide (Risks 7), `reports/harness_config.json` alone, with
one line saying what a clone without `reports/` does, is the narrower shape.

Amend `tests/test_documented_claims.py::TestShipBoundaryReviewWired::_assert_wired`, which pins
the literal fragment `` `bench/`, `scripts/`, ``; its negative twin
`test_pin_fires_when_trigger_surface_is_stripped` keeps discriminating.

**Body-lane order** (the coordinator's, 2026-10-07; every pack on these bodies states its side):
this sub-task lands **first** on the shared command and agent bodies, with nothing before it;
`TP-471` 3-A to 3-C follow (3-A on `implement-task.md`'s step 5, step 7 and Phase 3, other steps of
the file this sub-task edits at step 6; 3-B and 3-C on `test-this.md`, `test-writer.md`,
`docs-maintainer.md`); then `TP-474` 3-B (the four `.claude/agents/` bodies); then `TP-473` 1-B
**last**, because its audience gate reads the final text of every body, this block's adopter
branch included. Each lands in `.claude/` and re-runs `python3 scripts/sync_claude_mirrors.py`; a
hand resolve is made in the SoT and re-synced, never in a mirror.

**Earn the red:** 4-A reads the deployed step-6 block on the init'd tree and asserts it names the
adopter-source branch; mutation: restore the fixed list (red).

### 4-A The class test — `tests/test_adopter_generic_systems_fire.py`

One module, one init'd tree per module (`tests/_adopter_tree.py::build_adopter_tree`), Task 0's
drives as assertions, every hook run as a subprocess with `ESPALIER_*` stripped and
`CLAUDE_PROJECT_DIR` set: 1-A's three assertions, 1-B's banner assertion, 2-A's scan assertion,
3-A's body assertion. The module pins the class rule: **an identity gate that withholds content the
tree has is a defect**, and a new `scope="any"` row whose text names a harness path fails the
negative half. It should also assert a co-fire of the two calls never exceeds
`REINJECT_PER_TURN_CAP` (Risks 5).

### 5-A Red-team (budgeted; see Risks)

Dispatch `code-reviewer` and `failure-mode-reviewer` together, per `/preflight` step 6, and ask for
the mutation that survives 4-A: a self-host row reaching an adopter, an any-tree row whose text
names a harness path, a pointer the arm now excuses that an adopter cannot open.

## Affected symbols

Generic names are declared through a specific neighbour, as TP-468 did: `post_write_check.py::_check`
through `_bash_derived_payloads` (the bridge beside it), `_reinject.check` through `REINJECTS`, and
`encoding_contracts.scan_repo` through `_iter_scoped_files`.

### Changed-semantics

- `tools/cc/hooks/_reinject.py::ReinjectRule` — gains `scope` (default `"self_host"`)
- `tools/cc/hooks/_reinject.py::REINJECTS` — unchanged membership; two derived tuples hang off it
- `tools/cc/hooks/_reinject.py::TEST_LOOSENING_RULE` — `scope="any"`
- `tools/cc/hooks/_reinject.py::ARTIFACT_PROXY_RULE` — `scope="any"`
- `tools/cc/hooks/post_write_check.py::_bash_derived_payloads` — asks the registry per tuple, under the shared per-turn budget
- `tools/cc/hooks/session_start.py::_build_context` — content gate on the standing index
- `tools/cc/hooks/session_start.py::_build_compact_context` — the same
- `tools/cc/hooks/session_start.py::_standing_principles_index` — gains an ungated caller (no body change)
- `espalier/cli.py::SELF_HOST_ONLY_SCANNERS` — loses `encoding_contracts`
- `espalier/scanners/encoding_contracts.py::_iter_scoped_files` — leaves out `tools/cc/` and dependency dirs off self-host
- `tests/test_adopter_pointer_resolution.py::_self_host_only_functions` — gains an artifact-gated sibling, or its caller reads one
- `tests/test_cmd_scan_self_host_gate.py::test_pinned_scanners_emit_empty_reports_on_adopter` — four scanners
- `tests/test_cmd_scan_self_host_gate.py::test_the_scan_body_marks_exactly_the_scanners_that_stand_down` — four scanners
- `tests/test_cmd_scan_self_host_gate.py::test_gate_keeps_the_encoding_scanners_pragma_walks_off_an_adopter` — asserts the bounded walk instead
- `tests/test_documented_claims.py::TestShipBoundaryReviewWired` — pins the two-branch wording
- `tests/test_session_banner.py::TestStandingPrinciplesIndex` — gains the banner-level assertion

### Renamed

- (none.)

### Added-paths

- `tools/cc/hooks/_reinject.py::REINJECTS_ANY`
- `tools/cc/hooks/_reinject.py::REINJECTS_SELF_HOST`
- `tests/test_adopter_generic_systems_fire.py`
- `task-packs/TP-470-every-generic-system-fires-off-the-self-host-repo.md`

### Removed-paths

- (none -- the four registry scanners keep `_NOT_RUN_WHY` and their stand-down.)

## Reach

Members derived by: Appendix A from the repository root (every identity-gate call and every `if`
on a name bound from one, under `tools/cc/` and `espalier/`; mirrors and caches skipped), plus the
body grep in Motivation, plus
`grep -nE '^\| \`DEF-(1080|1090|1115|1122|5|1087|1091)\` ' task-packs/FORWARD_LEDGER.md` for the
rows that name a gate. The census is a lower bound: a path list that withholds a generic feature
without naming the predicate (`DEF-1180`'s shape) is invisible to it, and only the three command
bodies were read for that shape. Probes re-derived today:
`python3 tools/cc/check_ledger_probes.py --id DEF-1080` (and `1090`, `1115`, `1122`, `1180`, `1181`)
each printed `STILL_OPEN 1`. The SoT bodies' adopter-path-key count, derived:
`grep -cE 'harness_config\.json|primary_paths|package_roots' .claude/commands/implement-task.md .claude/commands/preflight.md .claude/commands/implement-pack.md`
printed `0` for each today, and each mentions `tools/cc/` (`grep -c 'tools/cc/'` on the same three:
`14 7 17`), which is the `3` the probe reads.

| Item | Status | Evidence |
|---|---|---|
| `DEF-1080` | **CLOSED by 1-A** | drives B and D (through the hook: nothing; directly: the generic row renders); 4-A's three assertions red on the two mutations |
| `DEF-1090` | **CLOSED by 1-B** | drives E, F, G; the banner assertion reds on the restored `if self_host:` |
| `DEF-1115` | **CLOSED by 2-A** | drive H (`ran: false` with a finding present); the `ran: true` assertion reds on the restored tuple |
| `DEF-1180` | **CLOSED by 3-A** | the filed probe, re-declared today: it reads the review step of all three deployed bodies and prints how many name no adopter path key (`harness_config.json`, `primary_paths`, `package_roots`), `3` while open (the derivation above); 3-A's branch text names `primary_paths` and `harness_config.json` in each body, so the count falls to `0` |
| `DEF-1181` | **NOT REACHED** | the filed probe prints `False False` (`_TEST_PATH_RE` on `test/widget.test.js`, `_TEST_LOOSEN_RE` on `test.skip(`), gate or no gate -- drive C; the stack table owns the idioms |
| `DEF-1122` | **NOT REACHED** | a per-tool relevance predicate shared across an engine module and a zero-import hook is a new rule; the class oracle cannot express it until "ruff is load-bearing here" is defined |
| `DEF-1091` | **NOT REACHED** | consent gate; its fix is an opt-in key |
| `DEF-5` | **NOT A MEMBER** | inert on every tree (derived in Scope (out)); its pull-side gate is harness-content, kept |
| `DEF-1087` | **NOT REACHED** | the recall-corpus pack's unit |
| the eighteen other `_reinject.py` PostToolUse rows | **KEPT self-host** | drives D and J: their text names mirrors, `tests/conftest.py`, `tests/_surface_expected.py`; §C71 decides whether such text ships at all |

## Pass criteria

- Every test this pack adds was seen red against its named mutation; Landing records each.
- **No assertion in an existing test is weakened.** The three `test_cmd_scan_self_host_gate.py`
  tests, `TestShipBoundaryReviewWired` and the pointer-resolution arm are amended to the new rule,
  never loosened to pass; the arm's `test_the_reachability_rule_still_discriminates` and the pin's
  `test_pin_fires_when_trigger_surface_is_stripped` stay green with no assertion weakened; a
  strengthening of either is recorded in Landing.
- On the init'd tree (4-A): the pytest-skip Edit yields the loosening text and nothing naming a
  harness path; the adopter's command-body Write yields nothing; the banner carries the adopter's
  principle titles; `reports/scan_encoding_contracts.json` reads `ran: true` with `count >= 1` and
  no `tools/cc/` finding; the deployed step-6 block names the adopter-source branch.
- On the harness tree: `tests/test_reinject_sync.py` is green with no assertion weakened (a
  strengthening is recorded in Landing); the banner is byte-identical for a tree that has
  `docs/STANDING_PRINCIPLES.md`.
- `python3 scripts/sync_vendor_cc.py --check`, `python3 scripts/sync_claude_mirrors.py --check` and
  `python3 scripts/sync_asset_docs.py --check` each exit 0: the `vendor-cc`, `claude-asset`,
  `claude-dogfooding` and `asset-docs` rows of `espalier/mirror_registry.py`, the four this pack
  touches.
- `mypy tools/cc/hooks/` reports no issues; `ruff check .` is clean.
- `python3 scripts/proof_tier.py --base origin/main` prints `full` (hooks and `espalier/` change),
  and it is green.
- `python3 tools/cc/check_ledger_probes.py --id DEF-1080` (and `1090`, `1115`, `1180`) print
  `STRIKE_CANDIDATE 1` after the lane lands; `DEF-1122`'s and `DEF-1181`'s still print `STILL_OPEN 1`.

## Files touched

- New: `tests/test_adopter_generic_systems_fire.py`; this pack.
- Modified: `tools/cc/hooks/_reinject.py`, `tools/cc/hooks/post_write_check.py`,
  `tools/cc/hooks/session_start.py` (+ `espalier/_vendor/cc/hooks/` by sync); `espalier/cli.py`,
  `espalier/scanners/encoding_contracts.py`; `.claude/commands/implement-task.md`,
  `.claude/commands/preflight.md`, `.claude/commands/implement-pack.md`, `.claude/commands/scan.md`
  (+ `espalier/assets/claude/` and `examples/dogfooding/.claude/` by sync); `docs/SHARP_EDGES.md`
  (one entry rewritten); `docs/HOOKS.md` (§1, one sentence; + `espalier/assets/docs/HOOKS.md` by sync);
  `tests/test_adopter_pointer_resolution.py`,
  `tests/test_cmd_scan_self_host_gate.py`, `tests/test_documented_claims.py`,
  `tests/test_deploy_doc_parity.py`, `tests/test_session_banner.py`; `task-packs/FORWARD_LEDGER.md`
  (four strikes -- `DEF-1080`, `DEF-1090`, `DEF-1115`, `DEF-1180` -- by the ledger verbs at landing).
- Read, unchanged unless a pin reds: `tests/test_reinject.py`, `tests/test_reinject_pins.py`,
  `tests/test_reinject_sync.py`, `tests/test_scanner_encoding_contracts.py`,
  `tests/test_session_start_source_aware.py`, `tests/test_hooks.py`,
  `tests/test_hooks_worktree_checkouts.py`, `tests/test_exemplar_parity.py`;
  `scripts/derived_population_census.py` re-run after 2-A.
- Deleted: none.
- Unmodified on purpose: `tools/cc/hooks/_recall.py`, `tools/cc/hooks/_hook_utils.py`,
  `tools/cc/hooks/post_compact.py`, `tools/cc/ci_guard.py`, `tools/cc/reflect_protocol.py`, every
  `espalier/` dispatch site, `espalier/doctor.py` (`DEF-1122`); `tests/conftest.py`, because the new
  module's stem `test_adopter_generic_systems_fire` matches no `_MARKER_RULES` entry and carries none
  of `TestSecurityMarkerCoverage`'s tokens (it classifies `unit`), and its hook subprocesses are
  declared by the `# slow-exempt: <reason, measured>` docstring line rather than a `_SLOW_FILES` row
  (Risks 6 names the one case that pulls a row in); and every file under the other machine's live
  claim.

## Sub-task ordering

0. Pre-flight, the four gates in `memory/task-packs.md`: `code-reviewer` with
   `tools/cc/pack_artifact_checklist.md`; `espalier scope-check` on this pack;
   `python3 tools/cc/sister_site_probe.py --json`; `espalier surface-impact` on this pack. Then
   `python3 tools/cc/execution_plan.py create`; the open-PR diff oracle on `tests/conftest.py` only if
   Risks 6's slow case bites.
1. Task 0 (0-A, 0-B, 0-C). Checkpoint: the table and the ten drive results in `reports/tp470/`.
   Stop on a refutation.
2. 1-B (the smallest change; it surfaces 0-C's test consequence first; first on the
   `session_start.py` seam, Risks 8). Checkpoint:
   `pytest -q -m 'not heavy_e2e' tests/test_session_banner.py tests/test_adopter_pointer_resolution.py tests/test_deploy_doc_parity.py`,
   then `python3 scripts/sync_asset_docs.py` (`docs/HOOKS.md`) and `python3 scripts/sync_vendor_cc.py`.
3. 1-A. Checkpoint: the pointer-resolution file again plus
   `tests/test_reinject.py tests/test_reinject_pins.py tests/test_reinject_sync.py`; then
   `python3 scripts/sync_vendor_cc.py`.
4. 2-A. Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_cmd_scan_self_host_gate.py tests/test_scanner_encoding_contracts.py`,
   then `python3 scripts/sync_claude_mirrors.py`.
5. 3-A, first in the body-lane order (3-A names the packs after it). Checkpoint:
   `pytest -q -m 'not heavy_e2e' tests/test_documented_claims.py -k ShipBoundary`, then the mirror
   sync again, then `python3 tools/cc/check_ledger_probes.py --id DEF-1180` (its tree builder runs
   `init` into a temp dir; set `TMPDIR` to a scratch path): `STRIKE_CANDIDATE 1`.
6. 4-A, each mutation driven and recorded. Checkpoint: the new module, then the enumerator pins
   (`tests/test_test_suite_contract.py tests/test_marker_taxonomy.py tests/test_portability_contract.py`).
7. 5-A red-team, one fix batch.
8. The tier the diff earns, under `nohup` with `EXIT=$?` appended; the four ledger strikes; the
   commit; `/handoff`, which ships.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 (re-run the drives, 0-C) | 1.5 h |
| 1-B | 2 h (3 h if the arm needs the derived sibling) |
| 1-A | 3 h |
| 2-A | 2 h |
| 3-A | 1.5 h |
| 4-A | 3 h |
| Red-team and fix batch | half a day |

Total about two days of lane time. Pack budgets on this tree ran about 2.7 times over on the one
pack measured, so read this as a floor.

## Risks — what this pack most likely got wrong

1. **The pointer-resolution arm's reachability model.** 1-A's reason for two tuples is that the arm
   sees `_reinject.py`'s witness constants only through a gated call. That is read from the arm's
   docstrings, not driven. If `_reachable_constants` follows the ungated call to every constant in
   the module, every self-host row's witness path reds on the adopter tree at once, and the fix
   needs a derived rule in the arm (the shape 1-B needs). Run 0-C's command first.
2. **1-B's artifact-gated exemption may not be derivable** in the arm's existing shape, and a
   hand-kept carve-out is what the module's docstring argues against. The fallback is licensed
   only with the warning beside it.
3. **2-A's walk may read the vendored hooks as adopter code** and replace a silent `n/a` with a
   wall of findings about `tools/cc/` (the `DEF-1158` shape). The no-harness-path assertion exists
   for this; if the scanner cannot exclude without an import it may not take, the exclusion moves
   to `cmd_scan`.
4. **The loosening row reaches Python adopters only.** Drive C is the measurement. A Node adopter
   who adds `test.skip(` still gets nothing after 1-A; `DEF-1181` says so, and the pack's wording
   must not read as if the skip advisory now fires for every adopter.
5. **The two-call budget.** `check()` cuts the per-turn slice where it marks once-per-session
   flags; two calls that each think they own the cap can emit three rows. 1-A passes the remaining
   budget to the second call, and 4-A asserts the co-fire never exceeds `REINJECT_PER_TURN_CAP`.
6. **The new test module and the suite contract.** `tests/conftest.py::_MARKER_RULES` routes an
   unmatched stem to `unit`, and `tests/test_documented_claims.py::TestSecurityMarkerCoverage` keys
   on the tokens `hook`, `guard`, `kill_switch`, `integrity`, `ci_guard`, `security`, `stop_gate`;
   `test_adopter_generic_systems_fire` matches no entry and carries no token (grepped today), so no
   conftest row. The module runs `init` and spawns hooks, so `tests/test_test_suite_contract.py`
   wants a `_SLOW_FILES` entry or the `# slow-exempt: <reason>` docstring line; it carries the line
   with its measured time, the idiom `tests/test_adopter_lifecycle_diagnostics.py` uses. The one
   case that pulls a row in: the module runs over the slow threshold on the Air. The other
   machine's claim on `tests/conftest.py` was released today (the coordinator), and a released
   claim does not free a file: the oracle before editing is each open PR's diff on it
   (`git diff --stat origin/main...origin/<branch> -- tests/conftest.py`, per branch the banner's
   `Open PRs:` line names).
7. **3-A's complement may be too wide** (a lockfile bump dispatches a reviewer). The second shape is
   named; the executor measures on the rehearsal tree's diff shapes before choosing.
8. **Seams on shared production symbols** (the landing order is prescribed; a hand resolve replays
   into `espalier/_vendor/cc/` through one `python3 scripts/sync_vendor_cc.py`).
   `tools/cc/hooks/session_start.py`: 1-B edits the standing-index block in `_build_context` and
   `_build_compact_context`; `TP-473` 1-E edits the kill-switch WARN's CI clause in the same module;
   `TP-474` names no edit to it (its Files touched, grepped today) but its Task 0 measures the hook's
   start on a kept helper (`import _reinject`), so the deployed `session_start.py` must still start
   after 1-B. Disjoint regions: `TP-470` 1-B first (ordering step 2), `TP-473` 1-E rebases on it.
   `tools/cc/hooks/_reinject.py`: 1-A adds `scope`, the two tuples and the comment rewrite beside
   `REINJECTS`; `TP-474` 2-A changes how `_is_tracked` reads `spawn_timeout` (an attribute read with
   a degrade). Disjoint: `TP-470` 1-A first (step 3), `TP-474` 2-A rebases. The shipped bodies'
   order is in 3-A.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: <per fix, the mutation and the red it produced>
- Red-team: <lanes run, verdicts, what they changed -- "none found" is a result>
- Reach: <closed / not reached, per the table above, as measured at landing>
- Date:

## Appendix A — the census instrument

Saved outside the tree and run from the repository root. One line per identity-gate site as
`path::enclosing-symbol<TAB>kind<TAB>Lnnn`; `kind` is `call` for a direct call of the predicate (or
its `ci_guard` / `reflect_protocol` twins) and `if-self_host` for a branch on a name bound from one.
Source `.py` only; the vendored mirror, packaged assets and `__pycache__` are skipped.

```python
import ast, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
ROOTS = ("tools/cc", "espalier")
SKIP = ("espalier/_vendor/", "espalier/assets/", "__pycache__")
GATE_NAMES = {"is_self_host_repo", "_ci_is_self_host_repo", "_routes_as_source_repo"}

def _callee(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""

def _walk(path):
    rel = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return
    bound = {"self_host", "_pinned_self_host"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _callee(node.value) in GATE_NAMES:
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    stack = []

    def enclosing():
        return "::".join(n.name for n in stack) or "<module>"

    def visit(node):
        scoped = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if scoped:
            stack.append(node)
        if isinstance(node, ast.Call) and _callee(node) in GATE_NAMES and not (stack and stack[-1].name in GATE_NAMES):
            print(f"{rel}::{enclosing()}\tcall\tL{node.lineno}")
        if isinstance(node, ast.If) and any(isinstance(n, ast.Name) and n.id in bound for n in ast.walk(node.test)):
            print(f"{rel}::{enclosing()}\tif-self_host\tL{node.lineno}")
        for child in ast.iter_child_nodes(node):
            visit(child)
        if scoped:
            stack.pop()

    visit(tree)

for r in ROOTS:
    for p in sorted((root / r).rglob("*.py")):
        if not any(s in p.relative_to(root).as_posix() for s in SKIP):
            _walk(p)
```
