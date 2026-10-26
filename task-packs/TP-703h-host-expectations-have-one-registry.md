# TP-703h — Host expectations have one registry: an expected red is a row the suite applies, counts and reports

## Status

- Version target: self-host only. Everything here lives under `tests/`, which `espalier init`
  does not deploy; nothing under `tools/cc/` or `espalier/` changes.
- Type: test infrastructure plus process (the suite's own contract and `tests/README.md`).
- **Kind: PACK.** One lane, `lane/host-expectations-registry`. Parent: `TP-703`
  (`task-packs/TP-703-multi-seat-discipline.md`, Wave 3, item 8), whose roadmap Task 0 does not
  gate this child; this file's Task 0 can end it.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the lessons reviewer's unification U1 in the
  `/reflect` of the same day.
- **The sibling store, read first.** `tests/_axis_registry.py` (the adopter-axes registry,
  `DEF-975`) already answers a neighbouring question: at which `(axis, value)` does a test prove
  the harness, with a `host` axis whose values are the interpreter-name shapes of
  `tests/_interpreter_hosts.py`. Its contract (`tests/test_axis_registry.py`) refuses a proving
  node that carries a `skip` or `xfail` mark, so an expected red cannot be a cell there. This
  pack adds the other table beside it, sharing its vocabulary and its contract file's shape, and
  does not build a rival (`memory/grep-for-a-sibling-store-before-building-a-rival.md`, the first
  entry the recall query returned).
- Boundary with `TP-703b` Wave 3: that lane lands `DEF-2025`'s counted macOS skip as a small
  roster in `tests/conftest.py` first (expand); this pack moves it into the registry and removes
  the roster (contract). **Superseded in part, 2026-10-19 (`TP-703b` W3 landed it differently;
  read that pack's W3 and Cross-pack coordination before this one's Task 0):** the roster is
  `tests/conftest.py::PLATFORM_EXPECTED_FAILURES`, a NON-STRICT expected failure bounded to
  `tests/_nested_race.py::NestedControllerRaceLost`, not a skip; it covers six node ids (the
  anchor and the class `TestACrashedControllerStillPrintsWhatItSaw`), not the anchor alone; the
  row is `DEF-4032`, `DEF-2025`'s successor, and the completed-child count is `DEF-4033`; and
  contract tests in `tests/test_test_suite_contract.py` read the roster's names. Item 4's skip
  row for the macOS red, H-4's row and the Reach row below predate that, and this pack's
  registry needs a third kind (non-strict, run, counted) to take the roster whole. Boundary with
  `TP-703a`: the reader reports a red after the merge; this
  registry says which reds were expected, so the reader's "0 unexpected" is a sentence with a
  table behind it.
- Ledger: no row filed at authoring. The registry's rows must each name a ledger row, and at
  authoring no live row names either of the Air's two known reds (Motivation; Task 0 item 4), so
  the lane files those rows from its seat's block in-lane, as protocol item 8 says, before the
  registry can carry them.

## Motivation

**The suite registers no host expectation.** Measured 2026-10-18 on `main` at 397799c:

- `grep -nE 'pytest\.mark\.(skipif|xfail)' tests/*.py tests/_*.py | grep -E 'platform|os\.name|win32|darwin|linux|SIGALRM|fcntl|msvcrt'`
  reads 80 platform-conditional marks, and every one is a capability skip: POSIX symlinks, `sh`
  stubs, Windows-only semantics ("sh stub is POSIX", "POSIX symlink semantics", "the rename probe
  is Windows-only"). `grep -nE 'pytest\.mark\.xfail' tests/*.py tests/_*.py` reads 13 xfail marks,
  none conditional on a host. Over all those marks, `grep -E 'DEF-[0-9]|INV-[0-9]'` finds 0 marks
  naming a ledger row (two comments do). `xfail_strict = true` is already set
  (`pyproject.toml`, pinned by
  `tests/test_test_suite_contract.py::test_pyproject_declares_xfail_strict`), so a healed red
  would be loud if anything marked it. Nothing does.
- Where the expectations live instead: the last 100 merged pull-request bodies (2026-10-15 to
  10-18; `gh pr list --state merged --limit 100 --json number,body`, read by a text match whose
  patterns are this pack's Task 0 item 1). 49 of 100 bodies carry a known-red explanation. The
  Air's `tests/test_record_merge.py::TestTheShipBodysRecordFinish::test_a_record_file_staged_with_its_markers_is_refused_until_unresolved`
  (Apple Git 2.39.5's `update-index --unresolve` exits 1 mid-merge; `git --version` on the Air
  prints `git version 2.39.5 (Apple Git-154)`) is explained in 34 bodies. The Air's
  `tests/test_merge_settings.py::TestEnforcementClaimSurvivesRealSettingsShapes::test_legacy_quoted_shell_form_is_not_reported_as_disarmed`
  ("1 red that is this box's baseline, red on main's own sources too") is explained in 9 bodies,
  all from the Air's worker seat. The phrases "known red", "box-local" and "this box's baseline"
  appear in 38. (The docs reviewer's figures of 12 and 5, quoted in the roadmap, came from a
  narrower match over a shorter window; the deriving script here is the one to re-run.)
- `docs/*.md`, `docs/sharp-edges/*.md`, `memory/*.md`, `bench/*.md` and `tests/README.md` carry
  0 known-red sentences (`grep -rniE 'known red|known-red|box-local|red on this box|per-box'`).
  `bench/README.md`'s host notes are capability notes (the PowerShell differential runs only on
  a host that has a `pwsh`; a Windows pass reads a baseline from another host with `--baseline`),
  not expected reds. So the prose the registry replaces is not in the docs: it is in pull-request
  bodies, where no test reads it, and in gitignored local files (the dispatcher's `cc/GOAL.md`
  carried a "declared per-box baseline list" item; its auto-memory a banner-lean-floor note),
  where no other seat reads it.
- One more site the census found by its own gap list: `task-packs/TP-468-adopter-axes.md`'s
  foundation-lane record names `tests/test_stop_gate.py::TestEnvOverrideGate1::test_end_to_end_failing_override_blocks_under_full`
  as "on this host's baseline-red list (the operator's Windows baseline, last confirmed against
  HEAD on 2026-10-02 and 2026-10-04)". A Windows-box red, carried as prose in a pack, with no
  row and no mark: a fourth candidate row for the registry, its kind and predicate to be read
  on the win box at Task 0 item 4 (unmeasured here).
- `tests/README.md`'s skip-class table (interpreter-gated, tool-gated, session-state-gated,
  deliberate, dead) has no row for a test that is red on one host by a known defect. Today that
  case is a `FAILED` line every reader must recognise by heart, and no mechanism tells a reader
  which `FAILED` lines are the box's and which are the lane's.

**The named user (§16).** A seat reading its tier receipt on the Air, who must know two node
ids to call the run green and wrote them into 49 of 100 pull-request bodies; the dispatcher, who
read "one red, the box's baseline" at every tick and has no tool that says whether the one red
this time is that one (the account is the dispatcher's own, unmeasured beyond the bodies); and an
adopter on a Windows host during `DEF-939`'s three reds (2026-09-28 to 09-30, per that row), who
had no place to be told they were known. The cost is the same shape as `TP-703a`'s: a red whose
meaning lives in a person's memory.

**What the registry buys.** On the host where a known red applies, the test is a strict xfail
naming its row and its re-measure date, so the summary line reads `host expectations: 2 expected
on this host (DEF-xxxx, DEF-yyyy), 0 unexpected`, and a pull-request body pastes that line instead
of an explanation. On any other host the row is inert and the test runs. When the red heals (the
Air's git is upgraded; the merge-settings defect is fixed), the strict xfail fails loudly as an
XPASS, which is the signal to strike the row and delete the expectation: a healed red cannot be
forgotten. A tier run whose receipt names a `FAILED` line no row expects is a real red.

## Scope (in)

1. **The registry module**, `tests/_host_expectations.py` (new; standard library plus
   `pytest`): a frozen `HostExpectation` row (the node id, a named host predicate, the ledger row
   id, the reason, the kind `xfail` or `skip`, a re-measure date), the `HostFacts` the predicates
   read once per session (platform, `git --version`, which interpreter names answer, the CI
   runner label, whether a `pwsh` answers), `applies(row, facts)`, and `render_table(facts)`;
   `python3 tests/_host_expectations.py` prints the table for this host as
   `python3 tests/_axis_registry.py` prints its own.
2. **The wiring** in `tests/conftest.py`: `pytest_collection_modifyitems` applies each row whose
   predicate holds to its node as `pytest.mark.xfail(strict=True, reason=...)` (the `xfail`
   kind) or `pytest.mark.skip(reason=...)` (the `skip` kind, for an intermittent red, which
   strictness cannot express), the reason naming the row id and the date; a plugin object
   registered in `pytest_configure` beside `_never_ran` writes the summary line through
   `terminalreporter.write_line` so `-q` keeps it, and the `::warning::` form under
   `GITHUB_ACTIONS`, as `tests/_never_ran.py` does.
3. **The contract**, `tests/test_host_expectations.py` (new): every row's node id collects;
   every row names a ledger row that resolves under `task-packs/ledger.d/` and is live, or struck
   with a re-open note (self-host; the test skips where the ledger is absent, as
   `tests/test_forward_ledger_completeness.py` does); every `skip` row carries a date, and a row
   past its date is reported by the table and reds the contract after a grace the pack sets;
   the registry is the only source of host-conditional `xfail` marks (an AST census over
   `tests/*.py` in the shape of
   `tests/test_test_suite_contract.py::test_no_non_test_function_carries_a_skip_or_xfail_mark`:
   an `xfail` whose condition text names `sys.platform`, `os.name`, `platform.system`, a git
   version or `shutil.which` is a finding); no row names a proving node of
   `tests/_axis_registry.py::AXIS_REGISTRY` (its contract forbids the mark; this one refuses to
   add it).
4. **The rows.** The Air's two deterministic reds as `xfail` rows under a predicate "darwin and
   Apple Git 2.39" for the first and "darwin and the Air's interpreter spelling" for the second,
   each naming the row the lane files; `DEF-2025`'s macOS red as a `skip` row under "darwin and
   `GITHUB_ACTIONS`", moved from `TP-703b` Wave 3's conftest roster, which this lane deletes.
5. **The words.** `tests/README.md`'s skip-class table gains a `host-expected` row pointing at
   the registry and the summary line; the tier receipt needs no change, the line is pytest's own
   output; the seats' pull-request bodies paste the line (a sentence in
   `memory/parallel-work-protocol.md` item 9, proposed, since the protocol is the operator's).

## Scope (out)

- **Rows as cells of `tests/_axis_registry.py`.** Its rule reads a proving node's marks and
  refuses `skip` and `xfail`; an expectation is the opposite object. Two tables, one vocabulary.
- **Fixing the two Air reds.** Each is its own defect with its own row (filed in-lane here) and
  its own lane; the registry names them, never fixes them. `DEF-939`'s Windows reds are closed
  and are cited only as the shape.
- **Expectations for capability skips.** The 80 marks skip a test on a host where its premise
  does not hold; they are not reds, and they stay as they are. A later census may find one that
  is really an expectation in disguise; that is a row to add, not a rule to change.
- **An expiry mechanism past the date flag.** `DEF-347c`'s lesson stands: a policy with no
  mechanism is prose. The table flags a past-date row and the contract reds after the grace;
  what happens then is the seat's re-measure, by hand.
- **Deploying the registry to adopters.** `tests/` is not deployed. An adopter's suite is the
  adopter's.
- **The portability legs' own summary.** `TP-703a`'s reader prints the verdicts; `TP-703b`
  shapes the legs. This pack gives both the sentence "0 unexpected" to read.

## Task 0 — Verify (try to kill this pack)

Each item names the oracle, the result that ends the pack, and the exit, which is stop and
re-raise to the dispatcher, never adjust and continue.

1. *Oracle:* the census, re-run at execution: the three greps in Motivation over `tests/`, and
   the body match over `gh pr list --state merged --limit 100 --json number,body` with the three
   patterns (a merge-settings red tied to the host; `Apple Git`, `git 2.39` or
   `update-index --unresolve`; `known red`, `box-local`, `this box's baseline`). *Refuting
   result:* fewer than two distinct expected reds live on any seat's host, or fewer than ten of
   the last 100 bodies explaining one. *Exit:* a registry is heavier than the problem; one roster
   in `tests/conftest.py` (what `TP-703b` Wave 3 lands) is enough, and this pack is held. (The
   authoring brief set the line at five members; the measured population is three distinct
   reds, two deterministic and one intermittent, so a line at five would end the pack at
   authoring on a count while 49 of 100 bodies explain the same two reds by hand. The line is
   set here, before execution, at two reds and ten bodies, and the reason is written down.)
2. *Oracle:* can the applied marks be counted at collection, parametrised ids included:
   `tests/test_axis_registry.py::collected_items` (a child collection that reports each item's
   callspec and mark names) over a node id carrying a parametrised `xfail`. *Refuting result:*
   marks on parametrised ids are not enumerable there. *Exit:* the registry still applies by node
   id in `pytest_collection_modifyitems`, and the census reads the source by AST instead of the
   collection; the pack says which it did.
3. *Oracle:* does a strict `xfail` under a false condition leave the test running elsewhere: a
   scratch module with `pytest.mark.xfail(sys.platform == "darwin", strict=True, reason="probe")`
   run on the Air (XFAIL) and in one CI cell (PASS, no XPASS). *Refuting result:* pytest records
   a strict XPASS where the condition is false. *Exit:* the rows are applied by node id at
   collection only where the predicate holds, never as a source mark; the mark form is dropped.
4. *Oracle:* `grep -lE 'update-index --unresolve|Apple Git|legacy_quoted_shell_form|test_a_record_file_staged_with_its_markers' task-packs/ledger.d/*.md`.
   *Refuting result:* none for the live rows (at authoring the one hit, `DEF-5008`, is a closed
   row about the mail driver's tree read-back, not either red). *Exit:* not a stop; the lane files
   the two rows from its seat's block before the registry rows can name them, with the probe each
   needs (the git version string; the merge-settings run on this host).
5. *Oracle:* for `DEF-2025`'s row, the kind: over the portability macOS runs since its fix
   (`gh run list --workflow portability.yml --limit 100 --json conclusion,headSha`, each red run's
   failing test from `gh run view <id> --log-failed`), does the test pass on any run. *Refuting
   result for the `xfail` kind:* one green run. *Exit:* the row is a `skip` row with a date, as
   written; a `skip` row is never strict and the table says so beside it.

## Relevant memory

Recent pattern, measured: the two reds this pack registers have been explained by hand in half of
the last 100 pull-request bodies, and the dispatcher's one tool for the question, reading the
bodies, is the same tool that failed on 2026-10-18 when a real Windows red sat beside the known
ones for six hours (`TP-703a`'s motivation).

| Entry | Where |
|---|---|
| Grep for a sibling store before building a rival | `memory/grep-for-a-sibling-store-before-building-a-rival.md` |
| A gate can be blind along a whole dimension | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| 7. Earn the red | `docs/STANDING_PRINCIPLES.md` |
| Cross-platform Python invocation | `CLAUDE.md` (section of that title) |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "a known red on one host and the
registry of platform skips"`, which returned the sibling-store entry first, the Cross-platform
Python invocation section second, and two entries that do not bear (the convergence protocol and
a `Path.rglob` footgun: lexical proximity, not answers); re-run it rather than trusting this list
if the pack has been sitting.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
The code fences that prescribe NEW modules carry no `target=` tag, because
`scripts/check_pack_fences.py` resolves a fence against an existing module and a new file has
none; their names are the standard library's and `pytest`'s, and the sentence above each says so.

### H-1 The registry module *(fix shape, untested)*

A new module, `tests/_host_expectations.py`, in the shape of `tests/_axis_registry.py`: a frozen
dataclass row, one tuple of rows, pure functions over them, and a `__main__` that prints the
table. The predicates are names, not lambdas, so the contract can list them and the table can
print them. Refuted if `HostFacts` cannot be computed without a subprocess in a session that
forbids one (the `git --version` read is one spawn per session; the contract file is `slow`
exempt only if the suite's spawn census accepts it, which Task 0 item 2's run shows).

```python
"""Host expectations: the reds the suite expects on a named host, each owned by a ledger row."""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
import sys
from dataclasses import dataclass

XFAIL, SKIP = "xfail", "skip"
KINDS = (XFAIL, SKIP)


@dataclass(frozen=True)
class HostExpectation:
    node: str        # the pytest node id the row applies to
    where: str       # a predicate name in PREDICATES
    row: str         # the ledger row that owns the expectation (DEF-/INV-)
    reason: str      # one sentence, 7-bit ASCII
    kind: str        # XFAIL (deterministic; strict) or SKIP (intermittent; dated)
    remeasure: str   # YYYY-MM-DD: when the expectation is re-measured by hand


@dataclass(frozen=True)
class HostFacts:
    platform: str          # sys.platform
    git_version: str       # the first line of `git --version`, or ""
    answering: tuple[str, ...]   # interpreter names shutil.which finds: python, python3, py
    ci: str                # GITHUB_ACTIONS runner label, or ""


def read_facts() -> HostFacts: ...          # one `git --version` spawn per session
PREDICATES = {                              # name -> HostFacts predicate
    "darwin_apple_git_2_39": lambda f: f.platform == "darwin" and "Apple Git" in f.git_version and " 2.39." in f.git_version,
    "darwin_python3_only": lambda f: f.platform == "darwin" and f.answering == ("python3",),
    "darwin_github_actions": lambda f: f.platform == "darwin" and bool(f.ci),
}
HOST_EXPECTATIONS: tuple[HostExpectation, ...] = ()   # the rows land in H-4
def applies(row: HostExpectation, facts: HostFacts) -> bool: ...
def render_table(facts: HostFacts, today: _dt.date | None = None) -> str: ...
```

### H-2 The wiring and the summary line *(fix shape, untested)*

`tests/conftest.py::pytest_collection_modifyitems` already walks every item once (the export
auto-skip); the rows are applied in that walk. The summary line is a plugin object registered in
`tests/conftest.py::pytest_configure` beside `_never_ran`, on the controller only
(`not hasattr(config, "workerinput")`, the `_never_ran` test). Refuted if applying a mark at
collection does not reach xdist workers: the controller collects and the workers collect again,
so the hook must run in the workers too, and the summary reads the controller's reports, which
carry the mark's outcome. (Measured shape: `tests/_never_ran.py` already distinguishes the two.)

```python target=tests/conftest.py
from tests import _host_expectations, _never_ran, _timeout_backstop


def pytest_configure(config):
    """Register the timeout backstop and the never-ran count (the imports above
    say what each is for)."""
    _timeout_backstop.pytest_configure(config)
    _never_ran.pytest_configure(config)
    _host_expectations.pytest_configure(config)   # the summary line, controller only
```

In `pytest_collection_modifyitems`, after the export check, one call applies the rows:
`_host_expectations.apply(items, facts)`, which adds `pytest.mark.xfail(strict=True, reason=...)`
or `pytest.mark.skip(reason=...)` to each item whose node id a row names and whose predicate
holds, and records which rows applied for the summary. The reason text is
`<row>: <reason> (expected on <predicate>; re-measure <date>)`, 7-bit ASCII.

The summary line, written through `terminalreporter.write_line` at `pytest_terminal_summary`:
`host expectations: N expected on this host (<rows>), H healed (XPASS: strike the row), 0 unexpected`
where "unexpected" counts `FAILED` reports whose node no applied row names; it is a report, the
reds themselves are pytest's. Under `GITHUB_ACTIONS` the same text goes out as `::warning::` when
`N` or `H` is not zero.

### H-3 The contract *(fix shape, untested)*

`tests/test_host_expectations.py`, classified in `tests/conftest.py::_MARKER_RULES` (a new test
file must be, per `tests/CLAUDE.md`). Each test names the mutation it dies to:

- `test_every_row_names_a_live_or_reopened_ledger_row`: dies to a row pointing at `DEF-939`
  (struck, no re-open). Skips where `task-packs/ledger.d/` is absent, with the reason naming the
  gitignored-path class from `tests/README.md`.
- `test_every_row_collects`: dies to a node id with a typo (uses
  `tests/test_axis_registry.py::collected_items`).
- `test_every_skip_row_carries_a_date_and_none_is_past_grace`: dies to a `skip` row dated 90
  days back (the grace is a constant in the module, pre-registered at 30 days).
- `test_no_row_names_a_proving_node_of_the_axis_registry`: dies to a row on
  `tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::test_the_hooks_govern_a_session_on_the_tree[python]`.
- `test_the_registry_is_the_only_source_of_host_conditional_xfails`: the AST census; dies to a
  seeded `@pytest.mark.xfail(sys.platform == "darwin", ...)` in a scratch test module the test
  writes under `tmp_path` and points the census at (the census takes a root argument so the seed
  never touches the live tree).
- `test_an_applied_row_is_a_strict_xfail_here_and_inert_elsewhere`: drives a scratch pytest
  session with a planted expectation under a predicate that holds, then one that does not
  (`pytester`, or a subprocess run as `tests/test_axis_registry.py` does), and reads the outcome.
- `test_the_summary_line_counts_unexpected_reds`: a planted failing test no row names reads
  `1 unexpected`.

### H-4 The rows *(measured on the Air, 2026-10-18; the predicates untested)*

Three rows at landing. The two Air rows name the rows the lane files (Task 0 item 4); the third
moves from `TP-703b` Wave 3's conftest roster, which this lane deletes in the same change, so the
skip has one home at every commit (expand, then contract).

| node | where | kind | measured |
|---|---|---|---|
| `tests/test_record_merge.py::TestTheShipBodysRecordFinish::test_a_record_file_staged_with_its_markers_is_refused_until_unresolved` | `darwin_apple_git_2_39` | `xfail` | red on the Air on every run the 34 bodies report; `git version 2.39.5 (Apple Git-154)` |
| `tests/test_merge_settings.py::TestEnforcementClaimSurvivesRealSettingsShapes::test_legacy_quoted_shell_form_is_not_reported_as_disarmed` | `darwin_python3_only` | `xfail` | red on the Air "on main's own sources too" per the 9 bodies; the predicate is a guess at the mechanism and Task 0 item 4's probe decides it |
| `tests/test_xdist_never_ran.py::TestACrashedWorkerIsNamedOnlyWhereItsBuildCanBe::test_a_worker_that_dies_in_its_build_is_named_each_time` | `darwin_github_actions` | `skip` | `DEF-2025`: red through the retry cap on the macOS leg on every post-fix run read 2026-10-18; "intermittent on CI" per the row |

### H-5 The words *(fix shape)*

`tests/README.md`'s skip-class table gains `host-expected | the host the row names; inert
elsewhere | tests/_host_expectations.py`, and the paragraph under it says a `FAILED` line no row
expects is a real red. One sentence for `memory/parallel-work-protocol.md` item 9 is proposed to
the operator (the protocol is the operator's): a tier receipt in a pull-request body carries the
summary line, not an explanation of the box's reds.

### What this pack most likely got wrong, for the red-team to bite on

The `darwin_python3_only` predicate: the merge-settings red's mechanism was not read here, only
its 9 reports; if the red follows the git version or the macOS `sh` instead, the row applies
where it should not. And the xdist shape: a mark applied at collection on the controller but not
in a worker leaves the worker reporting a plain `FAILED`, which the summary then counts as
unexpected while the controller's view says expected.

## Affected symbols

`/scope-check` keys on bare names. `pytest_configure`, `pytest_collection_modifyitems` and `_MARKER_RULES` are named across the suite (every test file that quotes the conftest's marker rule, the never-ran and timeout-backstop plugins' own tests, the reinject advisory), so its gap list at authoring was collisions, not files this pack misses; re-run it at the lane's start and accept the collision gap by name.

### Changed-semantics
- `tests/conftest.py::pytest_configure` (registers the summary plugin)
- `tests/conftest.py::pytest_collection_modifyitems` (applies the rows)
- `tests/conftest.py::_MARKER_RULES` (classifies the new test file)

### Renamed
- None.

### Added-paths
- `tests/_host_expectations.py`
- `tests/test_host_expectations.py`

### Removed-paths
- (none at authoring: the roster `TP-703b` Wave 3 adds to `tests/conftest.py` is removed here
  under the name that pack gives it)

## Reach

Not a class pack: it closes no ledger class. The rows it touches, so no later pass reads them as
shut:

Members derived by: the Task 0 item 1 census (the three greps and the body match); re-run it.

| Item | Status | Evidence |
|---|---|---|
| `DEF-2025` | **REGISTERED, not closed**; its skip moves here from `TP-703b` | the row in H-4; the row's own state is `TP-703b`'s |
| the Air's Apple Git red (row filed in-lane) | **REGISTERED, not closed** | the `xfail` row; the strike comes when the Air's git moves or the merge finish stops calling `--unresolve` |
| the Air's merge-settings red (row filed in-lane) | **REGISTERED, not closed** | the `xfail` row; Task 0 item 4's probe names the mechanism |
| the win box's stop-gate override red (`TP-468`'s record) | **CANDIDATE**; a row and a registry row only if the win box still reads it red at execution | Task 0 item 4 on the win box |
| `DEF-939` | **NOT REACHED** (closed 2026-10-02) | cited as the shape only |
| `DEF-975` | **NOT REACHED** | the sibling store; its contract unchanged |

## Pass criteria

- `python3 tests/_host_expectations.py` on the Air prints the table naming the rows that apply
  here; on a Linux CI cell it prints none applying.
- The full tier on the Air (`python3 scripts/proof_tier.py --run --tier full`) ends with the
  summary line and no `FAILED` line for the two Air rows; a Linux cell applies no row and prints
  `0 expected`.
- On a host where an `xfail` row's test passes, the run fails with a strict XPASS whose reason
  names the row (driven with a planted row in H-3's scratch session).
- Earn-the-red recorded per contract test against the mutation H-3 names; a test that only ever
  passed does not count.
- No existing `skipif` or `xfail` is removed or loosened; no mark is added to any node
  `tests/_axis_registry.py::AXIS_REGISTRY` names as proving; `tests/test_axis_registry.py`
  stays green unchanged.
- `tests/README.md` names the new class and the registry; the two reflect link checks and
  `tests/test_operator_docs.py` stay green.
- The tier the lane earns is run with `--base origin/main` and its receipt is in the pull
  request body (`tests/conftest.py` is suite config, so expect the full tier); the reviewers the
  `review:` line names are run on a snapshot clone.
- Pre-registered re-measure (written into Landing when its window closes): over the 50 merged
  pull requests after landing, bodies explaining a known red by hand, from 49 of 100 to at most 5
  of 50, and the summary line present in the bodies that report a tier run on the Air.
- No criterion here licenses shipping a defect in the gate this pack delivers: a row whose
  predicate applies on a host where the test is green, or a summary that counts a worker's
  `FAILED` as expected, is a defect of this pack, not a scope-out.

## Files touched

**New:** `tests/_host_expectations.py`; `tests/test_host_expectations.py`; two ledger row files
under `task-packs/ledger.d/` (minted from the seat's block by `ledger_row.py file`), with their
probes under `task-packs/probes.d/`.

**Modified:** `tests/conftest.py` (two hooks, `_MARKER_RULES`, and the removal of `TP-703b`
Wave 3's roster); `tests/README.md`; `memory/parallel-work-protocol.md` only on the operator's
yes to the item 9 sentence.

**Deleted:** none.

**Unmodified on purpose:** `tests/_axis_registry.py` and `tests/test_axis_registry.py` (the
sibling store and its contract); `scripts/proof_tier.py` (the line is pytest's output);
`pyproject.toml` (`xfail_strict` is already on); `.github/workflows/*`; `tools/cc/` and
`espalier/`.

## Sub-task ordering

1. **Task 0**, items 1 to 5; items 1 to 3 can end or reshape the pack; item 4 files the two rows;
   item 5 fixes `DEF-2025`'s kind. Checkpoint: the results written into Landing.
2. **H-1** the module and its table (smallest; prints on this host). Checkpoint:
   `python3 tests/_host_expectations.py`.
3. **H-3** the contract, red first against each named mutation, then **H-2** the wiring, then
   **H-4** the rows, driven on the Air (two XFAIL, the summary line) and in one CI cell (inert).
   Checkpoint: the targeted files, then `pytest tests/test_axis_registry.py` unchanged green.
4. **H-5** the words. Checkpoint: the doc contracts in `docs/CLAUDE.md`'s list.
5. **Red-team**, both reviewers on a snapshot clone as the tier's `review:` line names; the two
   likely errors above are the brief's first lines.
6. **The tier**, once, with `--base origin/main`; the push through the ship driver; Landing.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Step | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | 1 h | | five oracles, two of them scratch sessions |
| H-1, H-2 | 2 to 3 h | | one module, two hooks, the summary plugin |
| H-3 | 2 h | | seven contract tests, each red first |
| H-4, H-5 | 1 h | | three rows, two filed; the README row |
| Review and tier | | 1.5 h plus the full tier | conftest is suite config |
| Total | 6 to 7 h | 1.5 h | expect the measured overrun |

## Landing
- State: HELD at Task 0 item 1 (2026-10-26 local, seat `air-work`, lane `lane/host-expectations-registry`
  at a020a586; re-raised to the dispatcher, request `20261026T053408Z-air-work-aa9122`, pending its ruling)
- Commits: none of the pack's; this Landing only
- Suite: not run (nothing built)
- Earn-the-red: not run (nothing built)
- Red-team: the 0-A code-reviewer (pack-artifact checklist v2, reads only): REQUEST CHANGES with
  three BLOCKs, each a reading of the same ground move -- deleting the roster reds 40 references in
  `tests/test_test_suite_contract.py` and `TP-703i`'s roster pin
  (`tests/test_axis_registry.py::TestTheTargetOsCellsHoldOnEveryHost`, which imports
  `tests.conftest::_expected_failures_for`); H-2's xdist premise is wrong (xdist 3.8.0's controller
  never runs `pytest_collection_modifyitems`, `xdist/dsession.py:102-105`; the roster counts from
  report node ids); the merge-settings row would XPASS the Air's own tier under `darwin_python3_only`;
  H-2's summary would be a second line beside `tests/conftest.py::report_platform_expected_failures`.
  Figures: platform-conditional marks 78 (not 80), xfail marks 20 (the pack's 13 is stale), none naming
  a platform or a ledger row; `DEF-5008` no longer matches item 4's grep.
- 2026-10-26, later the same day: `DEF-5025` healed the Apple Git red (the `/ship` body's recovery
  respelled, the drive test green on the Air), so H-4's first row and Task 0 item 4's grep now point
  at a struck row; un-holding this pack as written would XPASS that row's strict `xfail` on the Air.
- Reach: no row touched; the record-merge red's defect row is filed from the seat's block on the
  dispatcher's word (adopter-facing: the recovery the `/ship` body prints,
  `git update-index --unresolve`, exits 1 on Apple Git 2.39.5), not as an expectation
- Task 0 (2026-10-26 local, at a020a586): item 1 **refuted the pack**: distinct expected reds live on
  a seat's host, ONE. Measured on the Air (`git version 2.39.5 (Apple Git-154)`):
  `tests/test_record_merge.py::TestTheShipBodysRecordFinish::test_a_record_file_staged_with_its_markers_is_refused_until_unresolved`
  FAILED; `tests/test_merge_settings.py::TestEnforcementClaimSurvivesRealSettingsShapes::test_legacy_quoted_shell_form_is_not_reported_as_disarmed`
  PASSED, so it is a premise red of python-only and Windows hosts (its fixture rewires hooks to
  `python3`), not an expectation, by this pack's own Scope (out); `DEF-4032`'s six ids are a CI
  runner's (`macos-ci`), not a seat's host, and have their home in `tests/conftest.py::PLATFORM_EXPECTED_FAILURES`
  (non-strict, counted, its reporter wired); the win box's stop-gate red is a candidate only (the box
  offline; the leads read a fixture defect). Bodies, `gh pr list --state merged --limit 100`
  (#243..#344, 2026-10-15 to 2026-10-26): 49 explain a known red by hand, 37 of them the
  record-merge test, 9 the merge-settings test with a host word (none from the Air since #307), 39
  with the phrases; the ten-body line is met and the two-reds line is not, so the exit is the
  pack's: stop and re-raise, never adjust. Item 2: marks on parametrised ids are enumerable by
  `collected_items` (`tests/test_axis_registry.py`'s planted `test_xfailed[node]` row proves it).
  Item 3: a strict `xfail` under a false condition is inert (probed on this box: PASS, not XPASS),
  so the item is moot. Item 4: no live ledger row names either Air red (the grep prints nothing).
  Item 5: decided before execution by `TP-703b` Wave 3 (non-strict, run, counted; the leads' five
  macOS runs read the anchor red 5 of 5 and the siblings 4 of 5).
- Re-measure (bodies explaining a known red, next 50 merges): window opens at the merge
- Date: 2026-10-18 (authored, local)
