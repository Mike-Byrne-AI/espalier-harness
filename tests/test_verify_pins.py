"""Contract for ``scripts/verify_pins.py`` -- driven against REAL prior commits.

Every control in this file is a real artifact reached through
``git show <sha>^:<path>``. Not one is a hand-typed reconstruction of what a
commit "looked like", and that is the whole subject of the tool under test:
``docs/FAILURE_MODES.md`` §5.18 -- "the red you earned against a synthetic
defect proves nothing about the real one" -- was itself committed one commit
after the broken pin it describes shipped. A synthetic fixture here would
reproduce the exact defect the tool exists to find.

THE HEADLINE SEPARATION
-----------------------
``3060e20`` is UNPINNED and the working tree is PINNED, and a gate that cannot
tell those two apart does not work. The hard half is ``3060e20``: it DID change
two test files, so every count-based check ("did this commit touch a test?")
calls it pinned. Its parity test is green against
``git show 3060e20^:.claude/agents/code-reviewer.md`` -- the pin cannot fail, so
the change it claims to pin is unpinned. Only reverting the real prior bytes and
re-running shows it.

``9b97e89`` is the same separation in COMMITTED form, so the discriminator keeps
a control after the working tree is committed and goes clean.

WHY THE VERDICTS ARE ASSERTED AS LITERALS
-----------------------------------------
A test that asserted only "the tool returns one of four strings" would pass
against a tool that always returns UNPINNED. Each control names the verdict it
must produce AND, where the reason is load-bearing, the specific test id that
must go red -- because a red for the wrong reason is an accidental pin, and
telling those apart is this tool's entire job.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from tests import test_protected_path_contract_parity as _parity

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = REPO_ROOT / "scripts" / "verify_pins.py"

# The repo-wide `timeout = 60` (pyproject.toml) is sized for in-process unit
# tests. Every control here clones the repo and runs pytest TWICE inside it --
# measured 2026-08-21: 1s (no selection) to 90s (the working-tree control, whose
# selection includes the tree-walking `test_derived_population_census.py`). The
# module-wide override is the same shape `test_derived_population_census.py` and
# `test_final_release_matrix.py` already use; it is a wall-clock budget, not a
# loosened assertion.
pytestmark = pytest.mark.timeout(1800)

# scripts/ is dev tooling and is intentionally NOT shipped in the sdist (per
# MANIFEST.in), so a sdist run must skip. A SOURCE CHECKOUT missing the script
# must NOT -- and the difference is load-bearing enough to spell out, because
# the sibling files that use a plain unconditional skip here have a hole this
# tool exists to find.
#
# `verify_pins` reverts non-test files. When the subject is the commit that ADDED
# `scripts/verify_pins.py`, the revert DELETES it. A module-level
# `if not script: skip` would then turn "the entire fix was deleted" into a
# green run -- the gate would report ITSELF unpinned, and the same shape masks
# any added-script fix on this repo (`tests/test_check_ledger_probes.py` lines
# 42-48 carry it today; `de32f81` is the artifact where it would bite).
#
# `.git/` is the discriminator: a sdist has none.
if not _SCRIPT.is_file():
    if (REPO_ROOT / ".git").exists():
        raise AssertionError(
            "scripts/verify_pins.py is MISSING from a source checkout. That is "
            "the subject of this test file being deleted, not an environment "
            "without it -- failing rather than skipping is the point."
        )
    pytest.skip(
        "scripts/verify_pins.py is dev tooling not shipped in sdist; this test "
        "file applies only to source-checkout runs.",
        allow_module_level=True,
    )

# RECURSION FUSE. `verify_pins` increments ESPALIER_VERIFY_PINS_DEPTH into every
# child pytest env. On the change that introduced this file the outer selection
# contained THIS module, so each control cloned and ran pytest, which ran the
# controls again: 17 live clones and a run that never terminated (measured
# 2026-08-21).
#
# The fuse is scoped to the CLONING controls only. The in-process ones still run
# at depth >= 1, deliberately: they are what makes the gate's verdict on its own
# change mean more than "the file exists".
_DEPTH = int(os.environ.get("ESPALIER_VERIFY_PINS_DEPTH", "0") or "0")
_no_recursion = pytest.mark.skipif(
    _DEPTH >= 1,
    reason=(
        f"running inside a verify_pins clone (depth={_DEPTH}); the cloning "
        "controls would recurse without bound. The in-process controls in this "
        "module still run at this depth."
    ),
)

# full-tree-exempt: every control reads git HISTORY, which survives a `git
# archive` export only if `.git/` came with it -- and it does not. The module
# guard below turns "no history" into a module-level skip with a reason rather
# than a wall of CalledProcessError.

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import verify_pins  # noqa: E402
from _git_oracle import require_tracked_paths  # noqa: E402
from verify_pins import (  # noqa: E402
    DEPTH_ENV,
    ERROR,
    NOT_APPLICABLE,
    PINNED,
    UNPINNED,
    commit_changes,
    declared_test_roots,
    is_test_path,
    run_pytest,
    select_tests,
)

# ── The real artifacts ──────────────────────────────────────────────────────
#
# Short shas, resolved through `git rev-parse` by the tool. Each is annotated
# with the property that makes it a control rather than a sample.

#: Changed 2 test files AND its pin is green against the real prior artifact.
#: The hard case: every "did a test change?" heuristic gets this one wrong.
UNPINNED_BUT_CHANGED_TESTS = "3060e20"

#: 7 files, 0 test files, 10 fix claims in its message.
UNPINNED_NO_TESTS_AT_ALL = "536a8c5"

#: Docs-only: 4 `.md` files, none carrying a source-language extension.
DOCS_ONLY = "7a533e3"

#: Committed PINNED control. Added `tests/test_check_ledger_probes.py` beside a
#: fix to `scripts/check_ledger_probes.py`; reverting the script reds the test.
PINNED_COMMIT = "9b97e89"

#: Changed only a test file -- the mechanic has no subject.
TEST_ONLY = "8bf7868"

#: ADDED a non-test file (`A scripts/check_ledger_probes.py`), so its revert is
#: a DELETE. The only real artifact in the recent window that exercises that arm.
ADDED_NON_TEST = "de32f81"

#: BOTH ADD a non-test file, and BOTH were FALSE PASSES before the index/HEAD
#: sync landed: `revert_to_base` deleted the added path from the worktree and
#: left it in the index, so `git archive HEAD` (which reads the INDEX) shipped a
#: file absent from the tree under test and
#: `test_git_archive_export_ignores_internal_docs` reddened off a phantom. That
#: single phantom was the ONLY red, so the verdict itself was manufactured --
#: 2 of the 7 PINNED rows in the tool's own calibration table.
#:
#: The honest answer was established INDEPENDENTLY of this tool, by an oracle
#: that reaches the same model without the contradiction: detach at `<sha>^`,
#: overlay the commit's new test blobs, run the same selection. 277 passed and
#: 15 passed, rc=0 -- UNPINNED both. Measured 2026-08-21.
ADD_REVERT_PHANTOM_A = "a198289"
ADD_REVERT_PHANTOM_B = "dec327f"

#: Touches `tools/cc/execution_plan.py`. 46 tests at HEAD isolate themselves by
#: `cwd=tmp_path` alone and read the plan path through `CLAUDE_PROJECT_DIR`, so
#: while `run_pytest` SET that variable to the clone the baseline was red with
#: the change fully applied and this commit -- a core-harness fix, exactly what
#: the gate exists to guard -- returned ERROR instead of a verdict.
CORE_HARNESS_COMMIT = "b4ef0c8"

#: Fixed SIX scanners; one of them is named `espalier/scanners/test_loosening.py`
#: and is a live engine module (imported at espalier/cli.py:3921). The old
#: `test_*.py`-anywhere basename glob classified it as TEST material, so the
#: revert put back five of the six and reported PINNED for a scanner change it
#: had silently held at its new state.
SIX_SCANNERS_ONE_NAMED_TEST = "45b24c7"

#: Raised `MAX_PRAGMA_COUNT` 6 -> 7 in the same commit that added the one new
#: pragma. `count_pragmas` is TREE-WIDE, so a whole-change revert drops the
#: measurement and the threshold together and they cancel -- the strongest
#: negative sentence the tool has, printed about a genuinely pinned change.
CAP_AND_MEASUREMENT_MOVED_TOGETHER = "de32f81"

#: Changed `docs/ENV_CATALOG.md`, whose name-derived candidate is
#: `tests/test_ENV_CATALOG.py` while the real file is `tests/test_env_catalog.py`.
#: On a case-insensitive filesystem `Path.is_file()` says the first one exists.
CASE_TRAP_COMMIT = "63beda2"


def _have_history() -> bool:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{UNPINNED_BUT_CHANGED_TESTS}^{{commit}}"],
        capture_output=True,
    )
    return proc.returncode == 0


if not _have_history():
    pytest.skip(
        f"the control commits ({UNPINNED_BUT_CHANGED_TESTS}, {PINNED_COMMIT}, ...) "
        "are not reachable from this checkout, so no real prior artifact can be "
        "restored. Run on a full clone.",
        allow_module_level=True,
    )


def _run(*args: str) -> tuple[int, dict]:
    """Drive the real CLI. Returns (rc, report). rc is read UNPIPED."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--json", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT), timeout=2400,
    )
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(
            f"verify_pins --json {' '.join(args)} did not emit JSON "
            f"(rc={proc.returncode})\nstdout:\n{proc.stdout[-2000:]}\n"
            f"stderr:\n{proc.stderr[-2000:]}"
        ) from exc


@pytest.fixture(scope="module")
def reports():
    """One run per subject, shared. Each clones the repo and runs pytest twice."""
    cache: dict[str, tuple[int, dict]] = {}

    def get(*args: str) -> tuple[int, dict]:
        key = " ".join(args)
        if key not in cache:
            cache[key] = _run(*args)
        return cache[key]

    return get


# Derived from the imported module, never typed: the guard's first gate asks
# whether THIS file is modified, and a hand-kept path would outlive a rename of
# the module behind a plausible skip reason while the import beside it failed
# loudly (the failure-mode review of the DEF-777 lane, 2026-09-14).
_PARITY_TEST = Path(_parity.__file__).resolve().relative_to(REPO_ROOT).as_posix()


def _head_text_of() -> "Callable[[str], str | None]":
    """``git show HEAD:<path>`` for the paths that carry the generated block in
    HEAD, None for every other path. One ``git grep`` finds the carriers, so
    the guard costs one subprocess per carrier rather than one per changed
    file -- an 816-file sweep is a real shape of this tree."""
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "grep", "-l", "-F", "-e", _parity.BLOCK_BEGIN, "HEAD"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    carriers = {
        line.partition(":")[2] for line in listed.stdout.splitlines() if line.startswith("HEAD:")
    }

    def head_of(rel: str) -> "str | None":
        if rel not in carriers:
            return None
        shown = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return shown.stdout if shown.returncode == 0 else None

    return head_of


def _work_text_of(rel: str) -> "str | None":
    try:
        return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _worktree_is_the_live_control(
    changes: "list[verify_pins.Change] | None" = None,
    head_of: "Callable[[str], str | None] | None" = None,
    work_of: "Callable[[str], str | None] | None" = None,
) -> bool:
    """The working tree only IS a control while it carries the parity REBUILD
    this file was calibrated on: the parity test file is modified, so the
    test holds new expectations, AND some changed path's generated
    ci-gated-paths block differs from HEAD's -- re-rendered, newly carried,
    removed, or carried under a new name -- so restoring HEAD's carriers has a
    block to put back.

    The block delta is the content the control's expected red depends on.
    Asking only whether the parity test file was modified took an unrelated
    edit to that file (a record-surface exemption, 2026-09-11) for the
    rebuild: the revert then reddened that lane's own new tests and the
    control failed with "PINNED for the WRONG reason" over tests pinned for
    exactly the right one. Skipping when the tree is not the control is
    honest; skipping SILENTLY would not be, which is why the committed pair
    (`3060e20` vs `9b97e89`) carries the same separation and never skips.

    The three readers default to the live tree -- the ``-z`` change parse the
    tool under test is trusted for, ``git show HEAD:``, the working file --
    and are injectable so every shape is driven through THIS entry point
    without dirtying the checkout (the row's own probe refused for the same
    reason, Core Rule 14): a revert to the file-modified rule reds the shapes.
    Carriers are derived from the sentinel, as the parity test derives them,
    never from a hand list.
    """
    if changes is None:
        changes = verify_pins.worktree_changes(REPO_ROOT)
    if head_of is None:
        head_of = _head_text_of()
    if work_of is None:
        work_of = _work_text_of
    if not any(change.path == _PARITY_TEST for change in changes):
        return False
    for change in changes:
        # A rename's block lived at the OLD path in HEAD, so a content-
        # preserving rename is no delta (the code review of this lane found
        # the first cut reading HEAD at the new path, i.e. reading nothing).
        head = head_of(change.old_path or change.path)
        work = work_of(change.path)
        head_block = _parity._extract_block(head) if head is not None else None
        work_block = _parity._extract_block(work) if work is not None else None
        if head_block is None and work_block is None:
            continue
        if head_block != work_block:
            return True
    return False


_worktree_control = pytest.mark.skipif(
    not _worktree_is_the_live_control(),
    reason=(
        "the working tree does not carry the parity rebuild (a modified "
        f"{_PARITY_TEST} beside a generated ci-gated-paths block that differs "
        "from HEAD), so it is not the PINNED control this file was calibrated "
        "on. The committed separation "
        f"({UNPINNED_BUT_CHANGED_TESTS} vs {PINNED_COMMIT}) still runs."
    ),
)


class TestTheLiveControlGuardKeysOnTheRebuild:
    """The guard decides from the rebuild's CONTENT, not from which file moved.

    Every shape is driven through the real entry point with fake readers,
    because the one honest way to reproduce the 2026-09-11 red on a real tree
    would be to dirty this checkout's parity test file (the row's own probe
    refused for the same reason). Driving the entry point rather than a
    helper means a revert to the file-modified rule reds every shape here.
    """

    _DOC = ".claude/agents/code-reviewer.md"

    @staticmethod
    def _carrier(rows: list[str]) -> str:
        block = "\n".join([_parity.BLOCK_BEGIN, *rows, "", "stanza", _parity.BLOCK_END])
        return "prose above\n" + block + "\nprose below\n"

    @staticmethod
    def _live(changes: list, head: dict, work: dict) -> bool:
        return _worktree_is_the_live_control(changes=changes, head_of=head.get, work_of=work.get)

    def test_the_guarded_path_is_the_imported_parity_module(self):
        """Derived, not typed: a rename of the module moves this with it."""
        assert (REPO_ROOT / _PARITY_TEST).is_file()
        assert (REPO_ROOT / _PARITY_TEST).resolve() == Path(_parity.__file__).resolve()

    def test_an_unrelated_edit_to_the_parity_test_is_not_the_rebuild(self):
        """The 2026-09-11 shape: the parity test file modified for its own
        reason, every carrier's block identical to HEAD's."""
        head = {_PARITY_TEST: "old test text", self._DOC: self._carrier(["- a"])}
        work = {_PARITY_TEST: "new test text", self._DOC: head[self._DOC]}
        assert self._live([verify_pins.Change("M", _PARITY_TEST)], head, work) is False

    def test_a_rerendered_block_beside_the_test_edit_is_the_rebuild(self):
        head = {_PARITY_TEST: "old", self._DOC: self._carrier(["- a"])}
        work = {_PARITY_TEST: "new", self._DOC: self._carrier(["- a", "- b"])}
        changes = [verify_pins.Change("M", _PARITY_TEST), verify_pins.Change("M", self._DOC)]
        assert self._live(changes, head, work) is True

    def test_a_rerendered_block_without_the_test_edit_is_not_the_rebuild(self):
        """New blocks with an unchanged test file: the revert restores carriers
        AND the renderer they were rendered from, so nothing can red."""
        head = {self._DOC: self._carrier(["- a"])}
        work = {self._DOC: self._carrier(["- a", "- b"])}
        assert self._live([verify_pins.Change("M", self._DOC)], head, work) is False

    def test_a_carrier_new_to_the_tree_counts_as_a_block_delta(self):
        """An untracked carrier has no HEAD text: its block is new by definition."""
        head = {_PARITY_TEST: "old"}
        work = {_PARITY_TEST: "new", "docs/NEW.md": self._carrier(["- a"])}
        changes = [verify_pins.Change("M", _PARITY_TEST), verify_pins.Change("A", "docs/NEW.md")]
        assert self._live(changes, head, work) is True

    def test_a_block_removed_from_a_carrier_is_also_the_rebuild(self):
        """A rebuild that retires a carrier strips its block; HEAD still has
        one to put back, so the revert has something to red on."""
        head = {_PARITY_TEST: "old", self._DOC: self._carrier(["- a"])}
        work = {_PARITY_TEST: "new", self._DOC: "prose only, block retired\n"}
        changes = [verify_pins.Change("M", _PARITY_TEST), verify_pins.Change("M", self._DOC)]
        assert self._live(changes, head, work) is True

    def test_a_deleted_carrier_is_also_the_rebuild(self):
        head = {_PARITY_TEST: "old", self._DOC: self._carrier(["- a"])}
        work = {_PARITY_TEST: "new"}
        changes = [verify_pins.Change("M", _PARITY_TEST), verify_pins.Change("D", self._DOC)]
        assert self._live(changes, head, work) is True

    def test_a_renamed_carrier_with_a_rerendered_block_is_the_rebuild(self):
        head = {_PARITY_TEST: "old", "docs/OLD.md": self._carrier(["- a"])}
        work = {_PARITY_TEST: "new", "docs/NEW.md": self._carrier(["- a", "- b"])}
        changes = [
            verify_pins.Change("M", _PARITY_TEST),
            verify_pins.Change("R", "docs/NEW.md", "docs/OLD.md"),
        ]
        assert self._live(changes, head, work) is True

    def test_a_content_preserving_rename_of_a_carrier_is_not_the_rebuild(self):
        """The code review's repro: the first cut read HEAD at the NEW path,
        found nothing, and called the rename a delta."""
        head = {_PARITY_TEST: "old", "docs/OLD.md": self._carrier(["- a"])}
        work = {_PARITY_TEST: "new", "docs/NEW.md": self._carrier(["- a"])}
        changes = [
            verify_pins.Change("M", _PARITY_TEST),
            verify_pins.Change("R", "docs/NEW.md", "docs/OLD.md"),
        ]
        assert self._live(changes, head, work) is False

    def test_the_skip_reason_names_the_block_delta_the_guard_wants(self):
        reason = _worktree_control.kwargs["reason"]
        assert "generated ci-gated-paths block" in reason
        assert _PARITY_TEST in reason


# ---------------------------------------------------------------------------
# The four mandated controls
# ---------------------------------------------------------------------------


@_no_recursion
class TestTheFourRealArtifactControls:
    def test_a_commit_that_changed_tests_can_still_be_unpinned(self, reports):
        """`3060e20` -- the hard one.

        It changed `tests/test_check_ledger_probes.py` AND
        `tests/test_protected_path_contract_parity.py`, so it looks pinned by
        every cheap heuristic. Restore the real
        `git show 3060e20^:.claude/agents/code-reviewer.md` and its parity test
        stays green: the pin cannot fail.
        """
        rc, rep = reports("--commit", UNPINNED_BUT_CHANGED_TESTS)
        assert rc == 0, "advisory by default"
        assert rep["verdict"] == UNPINNED, rep["reason"]
        # The selection must genuinely have RUN -- an empty selection would make
        # UNPINNED true for a boring reason and mask a broken revert.
        assert rep["selection"], rep
        assert rep["baseline"]["rc"] == 0, rep["baseline"]
        assert rep["after_revert"]["rc"] == 0, rep["after_revert"]
        assert "tests/test_protected_path_contract_parity.py" in rep["selection"]

    def test_a_commit_with_no_test_at_all_is_unpinned(self, reports):
        """`536a8c5` -- 7 files, 0 test files, 10 fix claims."""
        rc, rep = reports("--commit", UNPINNED_NO_TESTS_AT_ALL)
        assert rc == 0
        assert rep["verdict"] == UNPINNED, rep["reason"]
        assert rep["changed"]["test"] == []
        assert rep["selection"] == []
        assert "no test module" in rep["reason"]

    def test_a_docs_only_commit_is_reported_unpinned_with_its_buckets(self, reports):
        """`7a533e3` -- and this asserts the rule that was actually BUILT.

        No extension allowlist decides anything here. The verdict is UNPINNED,
        exactly as for a behaviour change with no pin, and the two evidence
        buckets are handed to the reader. Measured: no separator exists on this
        repo (see the module docstring of scripts/verify_pins.py), so
        auto-exempting would be a hand-tuned list pretending to be a rule.
        """
        rc, rep = reports("--commit", DOCS_ONLY)
        assert rc == 0
        assert rep["verdict"] == UNPINNED, rep["reason"]
        ev = rep["evidence"]
        # 0 of 4 -- the honest evidence a reader uses to wave it through.
        assert ev["source_ext_non_test"] == [], ev
        assert len(ev["other_non_test"]) == 4, ev
        assert ev["source_ext_owner"].endswith("SOURCE_LANGUAGE_EXTENSIONS")

    @_worktree_control
    def test_the_working_tree_is_pinned(self, reports):
        """The live control: the parity pin was rebuilt today and CAN fail.

        Restoring HEAD's `.claude/agents/code-reviewer.md` and the four doc
        surfaces reds the rebuilt block-parity tests at rc=1.
        """
        rc, rep = reports()
        assert rc == 0
        assert rep["verdict"] == PINNED, rep["reason"]
        assert rep["after_revert"]["rc"] != 0, rep["after_revert"]
        # NOT just "something went red". A red for the wrong reason is an
        # accidental pin, and telling those apart is this tool's whole job --
        # so the control names the pin that must fail. Measured: restoring
        # HEAD's `.claude/agents/code-reviewer.md` plus the four doc surfaces
        # reds the rebuilt generated-block parity tests.
        reds = rep["after_revert"]["failures"]
        assert any(
            "test_protected_path_contract_parity" in red for red in reds
        ), f"PINNED for the WRONG reason -- the parity pin did not red: {reds}"


@_no_recursion
class TestTheHeadlineSeparation:
    """If the gate cannot tell these apart it does not work."""

    @_worktree_control
    def test_the_unpinned_commit_and_the_pinned_working_tree_differ(self, reports):
        _, unpinned = reports("--commit", UNPINNED_BUT_CHANGED_TESTS)
        _, pinned = reports()
        assert (unpinned["verdict"], pinned["verdict"]) == (UNPINNED, PINNED), (
            f"the gate collapsed the two controls to "
            f"{unpinned['verdict']} / {pinned['verdict']}"
        )

    def test_the_committed_pair_carries_the_same_separation(self, reports):
        """Survives the working tree being committed and going clean.

        Both commits changed `scripts/check_ledger_probes.py` and both touched
        `tests/test_check_ledger_probes.py`'s file -- the only difference is
        whether the test can fail without the fix.
        """
        _, unpinned = reports("--commit", UNPINNED_BUT_CHANGED_TESTS)
        _, pinned = reports("--commit", PINNED_COMMIT)
        assert unpinned["verdict"] == UNPINNED, unpinned["reason"]
        assert pinned["verdict"] == PINNED, pinned["reason"]
        assert any(
            "test_check_ledger_probes" in red
            for red in pinned["after_revert"]["failures"]
        ), pinned["after_revert"]


# ---------------------------------------------------------------------------
# The mechanic's load-bearing details
# ---------------------------------------------------------------------------


class TestTestFilesAreNeverReverted:
    """The trap: revert the tests too and everything is trivially green."""

    @_worktree_control
    @_no_recursion
    def test_no_changed_test_file_appears_in_the_reverted_set(self, reports):
        _, rep = reports()
        # Non-vacuity: the control must actually HAVE changed test files,
        # otherwise "none were reverted" is true of nothing.
        assert rep["changed"]["test"], rep["changed"]
        reverted_blob = " ".join(rep["reverted"])
        for path in rep["changed"]["test"]:
            assert path not in reverted_blob, (
                f"{path} is a TEST file and was reverted. Reverting the tests "
                f"alongside the fix makes every change trivially green."
            )

    def test_the_partition_keeps_test_infrastructure_on_the_test_side(self):
        """`conftest.py` and `tests/_git_oracle.py` are as load-bearing as a
        `test_*.py`: reverting them re-opens the trap through the side door.
        Derived from the repo's declared `testpaths`, not a list written here.
        """
        roots = declared_test_roots(REPO_ROOT)
        assert "tests" in roots, roots
        for path in ("tests/conftest.py", "tests/_git_oracle.py",
                     "tests/_surface_expected.py", "tests/test_hooks.py"):
            assert is_test_path(path, roots), path
        for path in ("scripts/verify_pins.py", "espalier/cli.py",
                     ".claude/agents/code-reviewer.md", "docs/FAILURE_MODES.md"):
            assert not is_test_path(path, roots), path


@_no_recursion
class TestTheRevertArms:
    def test_an_added_non_test_file_is_reverted_by_deleting_it(self, reports):
        """`de32f81` ADDED `scripts/check_ledger_probes.py`. Its prior state is
        absence, so a revert that only ever overwrites bytes would leave the new
        file in place and silently under-report."""
        rc, rep = reports("--commit", ADDED_NON_TEST)
        assert rc == 0
        assert "delete scripts/check_ledger_probes.py" in rep["reverted"], rep["reverted"]

    def test_a_test_only_change_has_no_subject(self, reports):
        """`8bf7868` changed one test file and nothing else. NOT_APPLICABLE is
        the MECHANICAL answer -- there is nothing to revert -- and it is the only
        thing that earns that verdict. No content taxonomy decides it."""
        rc, rep = reports("--commit", TEST_ONLY)
        assert rc == 0
        assert rep["verdict"] == NOT_APPLICABLE, rep["reason"]
        assert rep["changed"]["non_test"] == []


class TestSelectionExistsWithExactCase:
    """macOS/APFS is case-insensitive; `Path.is_file()` is not an existence
    oracle there.

    Measured 2026-08-21 on the calibration sweep: `63beda2` changed
    `docs/ENV_CATALOG.md`, whose derived candidate is `tests/test_ENV_CATALOG.py`.
    `is_file()` returned True for it (the real file is `test_env_catalog.py`),
    pytest was handed a name it could not collect, exited rc=4 "no tests ran",
    and the commit became unanswerable. This runs in-process against the real
    commit's real changed set -- no clone, no pytest, milliseconds.
    """

    def test_no_selected_path_is_a_case_only_match(self):
        roots = declared_test_roots(REPO_ROOT)
        changes = commit_changes(REPO_ROOT, CASE_TRAP_COMMIT)
        assert changes, "the control commit resolved to an empty changed set"
        assert any(c.path == "docs/ENV_CATALOG.md" for c in changes), (
            "the case trap depends on docs/ENV_CATALOG.md being in this commit"
        )
        selection, _ = select_tests(REPO_ROOT, changes, roots, full=False)
        assert selection, "non-vacuity: this commit must select something"
        for rel in selection:
            parent, _, name = rel.rpartition("/")
            listing = {p.name for p in (REPO_ROOT / parent).iterdir()}
            assert name in listing, (
                f"{rel} was selected but does not exist with that exact case "
                f"(nearest: {sorted(n for n in listing if n.lower() == name.lower())}). "
                f"pytest will exit rc=4 and the commit becomes unanswerable."
            )

    def test_the_case_trap_candidate_is_specifically_excluded(self):
        roots = declared_test_roots(REPO_ROOT)
        changes = commit_changes(REPO_ROOT, CASE_TRAP_COMMIT)
        selection, _ = select_tests(REPO_ROOT, changes, roots, full=False)
        assert "tests/test_ENV_CATALOG.py" not in selection, selection


@_no_recursion
class TestTheBaselineGuardIsPresentAndGreen:
    """A red that predates the revert cannot be attributed to the revert.

    Without this the tool reports PINNED for an environmental failure -- which
    is exactly what the case-trap bug above produced before it was fixed
    (`--no-baseline` on pre-fix `63beda2` reports PINNED off an rc=4 that has
    nothing to do with the change).
    """

    def test_every_running_control_reports_a_green_baseline(self, reports):
        for args in (("--commit", UNPINNED_BUT_CHANGED_TESTS),
                     ("--commit", PINNED_COMMIT),
                     ("--commit", ADDED_NON_TEST)):
            _, rep = reports(*args)
            assert rep["baseline"] is not None, (args, rep["reason"])
            assert rep["baseline"]["rc"] == 0, (args, rep["baseline"])

    def test_a_red_baseline_becomes_error_rather_than_a_pin(self, monkeypatch):
        """The guard's EFFECT, not its presence.

        The control above asserts only `baseline is not None and rc == 0` --
        both satisfiable by a fabricated record, so it cannot tell "the baseline
        ran and was green" from "the baseline never ran". Measured 2026-08-21:
        replacing `pre = run_pytest(...)` with `pre = RunResult(0, [], "")` --
        the baseline never RUNS -- left all 21 controls green (52.8s against a
        ~99s control run, so the neutralisation demonstrably took effect). Every
        other neutralisation tried was caught; this one was not.

        Driven in-process against a REAL commit so the branch is exercised, not
        described. The first `run_pytest` call is the baseline.
        """
        calls: list[int] = []

        def _fake_run_pytest(clone, selection, timeout):
            calls.append(1)
            if len(calls) == 1:
                return verify_pins.RunResult(1, ["tests/test_x.py::test_y"], "")
            raise AssertionError(
                "the after-revert run must never happen once the baseline is "
                "red -- a red that predates the revert cannot be attributed to it"
            )

        monkeypatch.setattr(verify_pins, "run_pytest", _fake_run_pytest)
        rep = verify_pins.verify(REPO_ROOT, sha=PINNED_COMMIT)
        assert rep["verdict"] == ERROR, rep
        assert "ALREADY RED" in rep["reason"], rep["reason"]
        assert calls == [1], "non-vacuity: the baseline branch must have run"


#: Live-tree regions the HARNESS ITSELF writes while a Claude Code session is
#: open. Blueprint nodes land whenever the session machinery advances, which is
#: asynchronous to this test, so their mtimes move for reasons that have nothing
#: to do with the tool under test.
#:
#: ⚠ MEASURED, NEVER SPECULATIVE -- and the measurement is the whole point.
#: 2026-08-22: 40 targeted runs produced ONE failure (~2.5%, not the ~22% first
#: reported), and its two changed paths were `cc/blueprints/<node>.json` and
#: `cc/blueprints/latest.json`. TWO earlier diagnoses named `.espalier-state/`
#: and `.git/index`; both were plausible, both were wrong, and NEITHER was ever
#: observed changing. Grow this roster on an observed failure that names the
#: path, never on a mechanism that merely sounds right.
#:
#: Self-host only: no Claude Code session runs in CI, so this churn source does
#: not exist there and the control keeps its full reach on the CI tree.
_SESSION_CHURN_PREFIXES: tuple[str, ...] = ("cc/blueprints/",)


def _is_session_churn(rel: str) -> bool:
    """Prefix test for a repo-relative path, separator-normalized first.

    A free function rather than an inline clause so the WINDOWS arm is
    provable on a POSIX host: the roster is written with ``/`` separators, so
    without the normalization every prefix test silently returns False on
    Windows and the flake this exclusion exists for comes straight back --
    a failure mode no macOS/Linux run can observe. Cf. the repo rule pinned
    for ``espalier/`` at ``tests/test_contracts.py`` (path comparisons use
    ``.replace("\\", "/")``); that gate's population does not reach test
    helpers, so this one carries its own.
    """
    return rel.replace("\\", "/").startswith(_SESSION_CHURN_PREFIXES)


def _fs_manifest(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under `root`, by (size, mtime_ns). NOT git's view.

    `git status --porcelain -uall` -- what this control used to compare -- is
    blind by construction to anything under a gitignored path and to everything
    under `.git/`. That is not an arbitrary gap: `--carry` exists SPECIFICALLY to
    shuttle gitignored paths (`reports/`, `.espalier/`), so the one destructive
    code path in the tool lived entirely inside the one region its safety pin
    could not see. Measured 2026-08-21: with `verify()` patched to write
    `reports/LEAK.txt`, DELETE `reports/precious.md` and write
    `.git/LEAK_IN_GIT_DIR`, the git-status control passed green; the same
    neutralisation against a TRACKED file reddened it, which is what proves the
    boundary was exactly "tracked paths only" rather than the control being
    inert.
    """
    out: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if path.is_file() or path.is_symlink():
            rel = str(path.relative_to(root)).replace("\\", "/")
            if _is_session_churn(rel):
                continue
            st = path.lstat()
            out[rel] = (st.st_size, st.st_mtime_ns)
    return out


@_no_recursion
class TestIsolation:
    def test_the_session_churn_exclusions_stay_outside_the_tool(self):
        """The manifest may only skip regions verify_pins provably cannot write.

        ``--carry`` exists to shuttle GITIGNORED paths, so the one destructive
        code path in the tool lives inside gitignored regions -- which is
        exactly why ``_fs_manifest`` looks past git rather than using
        ``git status``. An exclusion is therefore safe only while the tool
        never names the excluded prefix. Derived from the source on every run,
        so teaching verify_pins to write there reds this instead of silently
        blinding the control.
        """
        src = (REPO_ROOT / "scripts" / "verify_pins.py").read_text(encoding="utf-8")
        assert _SESSION_CHURN_PREFIXES, (
            "an empty roster makes the loop below vacuous -- if the last "
            "exclusion is ever removed, delete this test with it"
        )
        for prefix in _SESSION_CHURN_PREFIXES:
            bare = prefix.rstrip("/")
            for token in (prefix, bare, bare.rsplit("/", 1)[-1]):
                assert token not in src, (
                    f"_fs_manifest excludes {prefix!r} from the isolation "
                    f"control, but verify_pins.py names {token!r} -- the tool "
                    f"can now write into a region the control cannot see."
                )

    def test_session_churn_prefix_test_is_separator_agnostic(self):
        """The Windows arm, provable on a POSIX host.

        ``_SESSION_CHURN_PREFIXES`` is written with ``/``. A Windows
        ``Path.relative_to`` yields ``cc\\blueprints\\node.json``, which
        matches no ``/`` prefix -- so dropping the normalization reopens the
        flake on Windows only, where nothing in this suite would ever see it.
        """
        assert _is_session_churn("cc/blueprints/node.json")
        assert _is_session_churn("cc\\blueprints\\node.json"), (
            "separator normalization was dropped: on Windows this returns "
            "False and the excluded region is watched again"
        )
        assert not _is_session_churn("reports/precious.md")
        assert not _is_session_churn("cc\\other\\thing.json")
        # ANCHORED at the repo root, not a substring. A path that merely
        # CONTAINS the roster entry is somebody else's file and the control
        # must keep watching it -- `startswith`, never `in`.
        assert not _is_session_churn("vendor/cc/blueprints/node.json"), (
            "the prefix test was loosened to a substring match: a nested "
            "path that only contains the roster entry is now unwatched"
        )

    def test_the_manifest_skips_session_churn_but_still_sees_everything_else(
        self, tmp_path
    ):
        """Non-vacuity: the exclusion must be narrow, not a blanket blindfold."""
        excluded = tmp_path / "cc" / "blueprints" / "node.json"
        excluded.parent.mkdir(parents=True)
        excluded.write_text("{}", encoding="utf-8")
        watched = tmp_path / "reports" / "precious.md"
        watched.parent.mkdir(parents=True)
        watched.write_text("keep me", encoding="utf-8")

        before = _fs_manifest(tmp_path)
        assert "reports/precious.md" in before, before
        assert "cc/blueprints/node.json" not in before, before

        excluded.write_text('{"grew": true}', encoding="utf-8")
        assert _fs_manifest(tmp_path) == before, "excluded churn leaked in"

        watched.write_text("mutated", encoding="utf-8")
        assert _fs_manifest(tmp_path) != before, (
            "the control went blind to a region --carry actually writes"
        )

    def test_a_run_does_not_touch_the_live_tree(self):
        """The clone is the whole safety argument, so this must be able to fail.

        TWO things had to change for that to be true.

        1. IT MUST ACTUALLY RUN THE TOOL. This used to call the module-scoped
           `reports` fixture, whose cache is keyed by argument -- and by the time
           this class runs, both subjects it asks for are already cached by
           earlier classes. ZERO subprocesses were spawned between the two
           snapshots and the assertion compared a snapshot to itself. Measured
           2026-08-21: with `verify()` patched to write a marker file into the
           LIVE tree on every invocation, the full module reported `21 passed`
           while SEVEN such markers accumulated. `_run` is the un-fixtured
           driver; it is used here deliberately.
        2. IT MUST LOOK WITH SOMETHING OTHER THAN GIT'S EYES -- see
           `_fs_manifest`.
        """
        before = _fs_manifest(REPO_ROOT)
        rc_a, rep_a = _run("--commit", TEST_ONLY)
        rc_b, rep_b = _run("--commit", DOCS_ONLY)
        after = _fs_manifest(REPO_ROOT)

        # NON-VACUITY. A run that never happened must not pass as one that did.
        assert (rc_a, rc_b) == (0, 0)
        for rep in (rep_a, rep_b):
            assert rep["verdict"] != ERROR, rep["reason"]

        changed = sorted(
            k for k in set(before) | set(after) if before.get(k) != after.get(k)
        )
        assert not changed, (
            f"verify_pins mutated {len(changed)} path(s) in the LIVE tree: "
            f"{changed[:20]}. The clone is the entire safety argument and this "
            f"session's working tree carries uncommitted work with no undo."
        )


@_no_recursion
class TestExitCodes:
    def test_advisory_by_default_and_nonzero_only_under_strict(self):
        """FAILURE_MODES §C19: a gate that reds on correct work gets switched
        off. This one exits 0 whatever it finds unless asked otherwise."""
        default = subprocess.run(
            [sys.executable, str(_SCRIPT), "--commit", TEST_ONLY],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600, encoding="utf-8",
        )
        assert default.returncode == 0, default.stdout[-2000:]

        strict = subprocess.run(
            [sys.executable, str(_SCRIPT), "--commit", DOCS_ONLY, "--strict"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600, encoding="utf-8",
        )
        assert strict.returncode == 1, (
            f"--strict must exit 1 on UNPINNED, got {strict.returncode}\n"
            f"{strict.stdout[-2000:]}"
        )

    def test_a_merge_commit_is_refused_rather_than_guessed(self):
        """'The change' has no single parent to revert to. Reported as ERROR,
        never resolved by silently picking parent 1."""
        merges = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "--merges", "--format=%h", "-1"],
            capture_output=True, text=True, encoding="utf-8",
        ).stdout.split()
        if not merges:
            pytest.skip("no merge commit in this history to drive the refusal")
        rc, rep = _run("--commit", merges[0])
        assert rep["verdict"] == ERROR, rep
        assert "merge commit" in rep["reason"], rep["reason"]
        assert rc == 0, "still advisory"


class TestTheReportIsHonestAboutItself:
    @_no_recursion
    def test_a_zero_test_change_carries_the_analytic_note(self, reports):
        """A commit that changed no test file reproduces its parent tree exactly
        when reverted, so no test in the SUITE can distinguish them. Saying that
        out loud stops a reader from mistaking UNPINNED for a sampling result --
        and tells them `--full` cannot change it."""
        _, rep = reports("--commit", UNPINNED_NO_TESTS_AT_ALL)
        assert any("ANALYTIC" in note for note in rep["notes"]), rep["notes"]

    @_no_recursion
    def test_the_evidence_bucket_refuses_to_be_a_verdict(self, reports):
        _, rep = reports("--commit", DOCS_ONLY)
        assert "NOT A VERDICT" in rep["evidence"]["note"]
        # The buckets must not smuggle a boolean back in.
        assert not any(
            isinstance(v, bool) for v in rep["evidence"].values()
        ), rep["evidence"]

    def test_explain_names_what_the_tool_cannot_detect(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--explain"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120, encoding="utf-8",
        )
        assert proc.returncode == 0
        for owed in ("PARTIAL COVERAGE", "WEAK ASSERTIONS", "PRE-EXISTING PIN",
                     "MERGE COMMITS", "RELATIONAL AND TREE-WIDE PINS",
                     "A DEATH IS NOT A RED"):
            assert owed in proc.stdout, owed


class TestTheRecursionFuse:
    """The child pytest must be told how deep it is.

    Without this the gate's own change selects its own test module, whose
    controls clone and run pytest, which runs the controls again. Measured
    2026-08-21 before the fuse existed: 17 live clones and a run that never
    terminated. In-process on purpose -- driving the real recursion to prove the
    fuse works would be driving the failure this fuse exists to prevent.
    """

    def test_every_child_pytest_env_carries_an_incremented_depth(
        self, monkeypatch, tmp_path
    ):
        captured: dict[str, str] = {}

        class _Completed:
            returncode = 0
            stdout = ""

        def _fake_run(cmd, **kwargs):
            captured.update(kwargs.get("env") or {})
            return _Completed()

        monkeypatch.setattr(verify_pins.subprocess, "run", _fake_run)
        monkeypatch.setenv(DEPTH_ENV, "3")
        run_pytest(tmp_path, ["tests"], 60)
        assert captured.get(DEPTH_ENV) == "4", (
            f"the child pytest env carried {DEPTH_ENV}="
            f"{captured.get(DEPTH_ENV)!r}; the fuse in tests/test_verify_pins.py "
            f"reads it to stop unbounded self-recursion."
        )

    def test_this_module_reads_the_same_variable_the_tool_writes(self):
        """One name, two sides. A rename on either side silently disarms the
        fuse, and the failure mode is a hang rather than a red."""
        assert DEPTH_ENV == "ESPALIER_VERIFY_PINS_DEPTH"
        source = Path(__file__).read_text(encoding="utf-8")
        assert f'os.environ.get("{DEPTH_ENV}"' in source


# ---------------------------------------------------------------------------
# The repairs of 2026-08-21, each against the artifact that exposed it
# ---------------------------------------------------------------------------


@_no_recursion
class TestTheRevertReconstructsATreeGitCouldProduce:
    """`revert_to_base` restores CONTENT. git's metadata has to be made to agree.

    Without the sync, an ADDED path is tracked-but-absent and a DELETED one is
    present-but-untracked after the revert -- a state git cannot reach on its
    own. Every test in this suite driving `git ls-files` or `git archive` is
    then answering a question about a tree that never existed.
    """

    @pytest.mark.parametrize(
        "sha", [ADD_REVERT_PHANTOM_A, ADD_REVERT_PHANTOM_B]
    )
    def test_an_add_revert_does_not_manufacture_a_phantom_red(self, reports, sha):
        rc, rep = reports("--commit", sha)
        assert rc == 0
        # Non-vacuity FIRST: the selection must have genuinely run both sides,
        # otherwise UNPINNED is true for a boring reason.
        assert rep["selection"], rep
        assert rep["baseline"]["rc"] == 0, rep["baseline"]
        assert rep["verdict"] == UNPINNED, (
            f"{sha} reported {rep['verdict']}. Both of these commits were FALSE "
            f"PASSES off a single phantom red from `git archive HEAD` reading an "
            f"index the revert never touched; an independent oracle puts both at "
            f"rc=0. reds={rep['after_revert']['failures']}"
        )
        assert rep["after_revert"]["rc"] == 0, rep["after_revert"]

    @pytest.mark.parametrize(
        "sha", [ADD_REVERT_PHANTOM_A, ADD_REVERT_PHANTOM_B, PINNED_COMMIT]
    )
    def test_the_reverted_clone_is_internally_consistent(self, reports, sha):
        """The invariant, asserted directly -- cheaper than any verdict.

        `verify()` runs `git_metadata_is_consistent` on the reverted clone and
        appends a WARNING note if any path is tracked-but-absent or restored-but-
        untracked. No control should ever see that note.
        """
        _, rep = reports("--commit", sha)
        bad = [n for n in rep["notes"] if n.startswith("WARNING: git metadata")]
        assert not bad, bad

    def test_the_sync_actually_fires_on_an_add_revert(self, reports):
        """Non-vacuity for the test above: silence must mean "consistent", not
        "the check never had anything to do"."""
        _, rep = reports("--commit", ADD_REVERT_PHANTOM_A)
        assert any("recorded the reverted tree as a commit" in n
                   for n in rep["notes"]), rep["notes"]


class TestADeathIsNotARed:
    """`subprocess.run` returns a NEGATIVE rc when the child dies by signal.

    `if post.rc != 0` blessed that as PINNED while the baseline branch turned
    the identical event into ERROR. Reachable and measured: a real `--full` run
    on this machine returned rc=-9, and driven end-to-end on a two-commit repo
    whose test SIGKILLs itself the verdict was `PINNED / reddened 1 test(s)`
    with an EMPTY failure list and not one RED line printed -- the count
    manufactured by a `len(...) or 1` fallback.

    In-process against a REAL commit: reproducing an actual SIGKILL would be
    nondeterministic, and the subject here is the tool's interpretation of a
    return code that was itself measured on a real run.
    """

    @pytest.mark.parametrize(
        ("rc", "why"),
        [(-9, "SIGKILL"), (-15, "SIGTERM"), (2, "pytest INTERRUPTED"),
         (4, "pytest USAGE ERROR"), (5, "pytest NO TESTS COLLECTED")],
    )
    def test_a_nonzero_rc_naming_no_failing_test_is_not_a_pin(
        self, monkeypatch, rc, why
    ):
        calls: list[int] = []

        def _fake_run_pytest(clone, selection, timeout):
            calls.append(1)
            if len(calls) == 1:
                return verify_pins.RunResult(0, [], "")      # baseline green
            return verify_pins.RunResult(rc, [], "")         # after revert: death

        monkeypatch.setattr(verify_pins, "run_pytest", _fake_run_pytest)
        rep = verify_pins.verify(REPO_ROOT, sha=PINNED_COMMIT)
        assert calls == [1, 1], "non-vacuity: both sides must have run"
        assert rep["verdict"] == ERROR, (
            f"rc={rc} ({why}) with ZERO named failures became "
            f"{rep['verdict']}: {rep['reason']}"
        )
        # TWO guards produce this verdict and they are NOT redundant: the
        # rc<0 branch is what makes the report say "killed by signal 9" instead
        # of the generic "exited rc=-9". Asserting the wording is what earns
        # that branch its own red -- measured 2026-08-21, neutralising it alone
        # left the class green because the second guard still returned ERROR.
        expected = "KILLED BY SIGNAL" if rc < 0 else "without naming"
        assert expected in rep["reason"], (rc, why, rep["reason"])

    def test_a_baseline_signal_death_is_not_called_already_red(self, monkeypatch):
        """The symmetric half. `rc=-9` on the baseline side used to report "the
        selection was ALREADY RED", which is not what a signal means and sends
        the reader to fix tests that are not failing."""
        def _fake_run_pytest(clone, selection, timeout):
            return verify_pins.RunResult(-9, [], "")

        monkeypatch.setattr(verify_pins, "run_pytest", _fake_run_pytest)
        rep = verify_pins.verify(REPO_ROOT, sha=PINNED_COMMIT)
        assert rep["verdict"] == ERROR, rep
        assert "KILLED BY SIGNAL 9" in rep["reason"], rep["reason"]
        assert "ALREADY RED" not in rep["reason"], rep["reason"]

    def test_the_red_count_is_never_manufactured(self, monkeypatch):
        """`len(post.failures) or 1` printed a count the tool never observed.

        The `or 1` fallback is now UNREACHABLE -- an empty failure list returns
        ERROR above before this branch is entered -- so removing it is a no-op
        and cannot be reddened by any input. Verified 2026-08-21 by putting it
        back: the class stayed green. What this control pins is therefore the
        thing that is still reachable and still worth pinning: the number
        printed is the number observed. Neutralising `len(post.failures)` to
        `len(post.failures) + 1` reds it.
        """
        calls: list[int] = []

        def _fake_run_pytest(clone, selection, timeout):
            calls.append(1)
            if len(calls) == 1:
                return verify_pins.RunResult(0, [], "")
            return verify_pins.RunResult(1, ["tests/a.py::x", "tests/b.py::y"], "")

        monkeypatch.setattr(verify_pins, "run_pytest", _fake_run_pytest)
        rep = verify_pins.verify(REPO_ROOT, sha=PINNED_COMMIT)
        assert rep["verdict"] == PINNED, rep["reason"]
        assert "2 test(s)" in rep["reason"], rep["reason"]


@_no_recursion
class TestTheRunnerEnvDoesNotManufactureRedness:
    """`run_pytest` used to SET `CLAUDE_PROJECT_DIR` to the clone.

    46 tests at HEAD isolate themselves by `cwd=tmp_path` alone and resolve the
    plan path through that variable, so the baseline was red with the change
    fully applied and the tool refused to answer -- on core harness files, and
    on every `--full` run without exception. The sharp edge it cited is closed
    by UNSETTING the variable, not by re-pointing it.
    """

    def test_a_core_harness_commit_gets_a_verdict_not_an_error(self, reports):
        rc, rep = reports("--commit", CORE_HARNESS_COMMIT)
        assert rc == 0
        assert rep["verdict"] != ERROR, (
            f"{CORE_HARNESS_COMMIT} touches tools/cc/execution_plan.py -- the "
            f"kind of file this gate exists to guard -- and returned no verdict: "
            f"{rep['reason'][:400]}"
        )
        assert rep["baseline"]["rc"] == 0, rep["baseline"]

    def test_the_child_env_does_not_carry_a_project_dir(self, monkeypatch, tmp_path):
        """Belt and braces: pinned at the env level, so a re-point cannot
        return quietly through a refactor."""
        captured: dict[str, str] = {}

        class _Completed:
            returncode = 0
            stdout = ""

        def _fake_run(cmd, **kwargs):
            captured.update(kwargs.get("env") or {})
            return _Completed()

        monkeypatch.setattr(verify_pins.subprocess, "run", _fake_run)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(REPO_ROOT))
        run_pytest(tmp_path, ["tests"], 60)
        assert captured, "non-vacuity: the fake runner must have been called"
        assert "CLAUDE_PROJECT_DIR" not in captured, (
            "the child pytest inherited CLAUDE_PROJECT_DIR; 46 tests at HEAD "
            "are not isolated against it and the baseline goes red"
        )


class TestThePartitionIsLocationOnly:
    """`testpaths` is the whole rule -- no basename glob beside it.

    The glob was not a derivation: pytest never collects outside `testpaths`, so
    `test_*.py`-anywhere had no basis in pytest's behaviour, and it was wrong on
    13 tracked paths including a live engine module.
    """

    def test_no_tracked_path_outside_the_declared_roots_is_test_material(self):
        """Derived, so it self-updates as the repo adds files. This would have
        reddened the day the basename clause was written."""
        roots = declared_test_roots(REPO_ROOT)
        # Through the oracle, not a raw `git ls-files` -- §C21, and the reason
        # is this file's own subject: a raw call that answers about a different
        # tree (or not at all) returns an empty list, and an empty list makes
        # the assertion below pass having checked nothing. `require_tracked_paths`
        # raises instead. The floor is well under the ~1.4k tracked paths here
        # and well over a collapsed population.
        tracked = require_tracked_paths(
            REPO_ROOT, minimum=500, what="tracked paths (test/non-test partition)"
        )
        stray = [
            f for f in tracked
            if is_test_path(f, roots)
            and not any(f == r or f.startswith(r + "/") for r in roots)
        ]
        assert stray == [], (
            f"{len(stray)} tracked path(s) outside {roots} are classified as "
            f"TEST material and would be exempted from the revert: {stray}"
        )

    @_no_recursion
    def test_a_production_module_named_test_something_is_reverted(self, reports):
        """The real artifact. Six scanners were fixed; five were reverted."""
        _, rep = reports("--commit", SIX_SCANNERS_ONE_NAMED_TEST)
        target = "espalier/scanners/test_loosening.py"
        assert target in rep["changed"]["non_test"], rep["changed"]
        assert f"restore {target}" in rep["reverted"], rep["reverted"]


class TestEvidenceIsNeverSilentlyUnavailable:
    """A failed derivation must not impersonate a measured zero."""

    def test_the_owner_read_and_the_owner_printed_are_one_value(self):
        assert verify_pins.SOURCE_EXT_OWNER.startswith(
            verify_pins.SOURCE_EXT_OWNER_REL)
        assert (REPO_ROOT / verify_pins.SOURCE_EXT_OWNER_REL).is_file(), (
            "the owner this tool loads its evidence from has moved; the "
            "provenance string is derived from the same value, so it moved too"
        )

    def test_an_unloadable_owner_returns_none_not_an_empty_set(self, tmp_path):
        assert verify_pins.source_language_extensions(tmp_path) is None
        real = verify_pins.source_language_extensions(REPO_ROOT)
        assert real is not None and ".py" in real, real

    @_no_recursion
    def test_a_source_bearing_change_reports_a_NON_empty_bucket(self, reports):
        """The docs-only control asserts the bucket is EMPTY -- which is exactly
        what a silently-broken loader also produces. This is the other half."""
        _, rep = reports("--commit", UNPINNED_NO_TESTS_AT_ALL)
        ev = rep["evidence"]
        assert ev["source_ext_non_test"], (
            f"{UNPINNED_NO_TESTS_AT_ALL} changes scripts/check_ledger_probes.py; "
            f"an empty bucket here means the derivation broke, not that no path "
            f"carries a source extension. owner={ev['source_ext_owner']}"
        )
        assert "UNAVAILABLE" not in ev["source_ext_owner"], ev


@_no_recursion
class TestCarryCannotReachIntoTheSourceRepo:
    """`Path(clone) / "/abs/path"` DISCARDS the left operand.

    An absolute `--carry` therefore made dest == src == the live path, and the
    "clear the destination first" `rmtree` deleted it FROM THE SOURCE REPO --
    driven 2026-08-21, removing a gitignored (git-unrecoverable) directory and
    then crashing with a raw traceback at exit 1. `--carry`'s documented targets
    are precisely the paths git cannot restore.

    Earned against a real throwaway clone of this repo, never against the live
    tree, and the assertion is on the FILE'S EXISTENCE rather than on
    `git status` -- which is blind to gitignored paths by construction.
    """

    @staticmethod
    def _throwaway(tmp_path: Path) -> Path:
        dest = tmp_path / "repo"
        subprocess.run(
            ["git", "clone", "--no-hardlinks", "-q", str(REPO_ROOT), str(dest)],
            check=True, capture_output=True,
        )
        (dest / "reports").mkdir(parents=True, exist_ok=True)
        (dest / "reports" / "precious.md").write_text("unrecoverable\n", encoding="utf-8")
        return dest

    def test_an_absolute_carry_does_not_delete_the_source_path(self, tmp_path):
        repo = self._throwaway(tmp_path)
        victim = repo / "reports" / "precious.md"
        rc, rep = _run("--repo", str(repo), "--commit", DOCS_ONLY,
                       "--carry", str(repo / "reports"))
        assert victim.is_file(), (
            "verify_pins DELETED a gitignored path from the SOURCE repo. git "
            "cannot restore it and no `git status` comparison can see it."
        )
        assert rc == 0, "advisory: a --carry mistake must not become an exit code"
        assert rep["verdict"] != ERROR, rep["reason"]
        assert any("carried" in n for n in rep["notes"]), rep["notes"]

    def test_a_carry_outside_the_repo_is_refused_as_a_verdict_not_a_traceback(
        self, tmp_path
    ):
        repo = self._throwaway(tmp_path)
        rc, rep = _run("--repo", str(repo), "--commit", DOCS_ONLY,
                       "--carry", "../../../etc")
        assert rc == 0, "still advisory"
        assert rep["verdict"] == ERROR, rep
        assert "OUTSIDE" in rep["reason"], rep["reason"]

    def test_an_unexpected_crash_is_an_error_verdict_not_exit_1(self, monkeypatch):
        """The contract is "exit 0 whatever the verdict". Only
        `VerifyPinsError` and `TimeoutExpired` were caught; everything else
        escaped as a traceback at exit 1, which under `--strict` is
        indistinguishable from a legitimate UNPINNED."""
        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(verify_pins, "make_clone", _boom)
        rep = verify_pins.verify(REPO_ROOT, sha=DOCS_ONLY)
        assert rep["verdict"] == ERROR, rep
        assert "OSError" in rep["reason"], rep["reason"]


@_no_recursion
class TestThePerFileProbe:
    """A whole-change revert can self-cancel a real pin.

    `de32f81` raised `MAX_PRAGMA_COUNT` 6 -> 7 in the same commit that added the
    single new pragma. The count is TREE-WIDE, so reverting everything drops the
    measurement and the threshold together: 60 passed, rc=0, and the tool prints
    its strongest negative sentence about a genuinely pinned change.
    """

    def test_the_cap_pin_the_whole_change_cancels_is_recovered(self, reports):
        _, rep = reports("--commit", CAP_AND_MEASUREMENT_MOVED_TOGETHER,
                         "--wide", "--per-file")
        assert rep["verdict"] == UNPINNED, rep["reason"]
        assert rep["after_revert"]["rc"] == 0, rep["after_revert"]
        alone = {r["path"]: r for r in rep["per_file"]}
        target = "espalier/scanners/subprocess_contracts.py"
        assert target in alone, list(alone)
        assert alone[target]["verdict"] == PINNED, alone[target]
        assert any("test_pragma_count_within_cap" in f
                   for f in alone[target]["failures"]), alone[target]
        # And it must DISCRIMINATE -- not just report everything as pinned.
        others = [p for p, r in alone.items()
                  if p != target and r["verdict"] == PINNED]
        assert others == [], others

    def test_the_probe_never_changes_the_verdict(self, reports):
        """`3060e20` is the discriminator this whole tool exists to produce.
        Reverting its mirror ALONE reds two parity controls (measured), so
        folding a per-file red into PINNED would collapse it against the
        working-tree control and destroy the gate."""
        _, plain = reports("--commit", UNPINNED_BUT_CHANGED_TESTS)
        _, probed = reports("--commit", UNPINNED_BUT_CHANGED_TESTS, "--per-file")
        assert plain["verdict"] == probed["verdict"] == UNPINNED, (
            plain["verdict"], probed["verdict"]
        )


class TestTheReportDoesNotSendTheReaderOnAPointlessRun:
    """Limit 4 names `--full` as the corrective. The ANALYTIC note, in the same
    report, states that `--full` cannot change the verdict. 40% of commits got
    both sentences; following the advice costs ~24 minutes for the identical
    answer, and that is how a reader learns to stop reading the report."""

    @_no_recursion
    def test_an_analytic_report_does_not_also_recommend_full(self, reports):
        _, rep = reports("--commit", UNPINNED_NO_TESTS_AT_ALL)
        assert any("ANALYTIC" in n for n in rep["notes"]), rep["notes"]
        assert "--full if you believe" not in rep["reason"], rep["reason"]
        assert "--full CANNOT change this" in rep["reason"], rep["reason"]


class TestTheWideningLadderIsDriven:
    """`--full` was shipped with no control at all -- one grep hit, inside a
    docstring. It is also the mode limit 4 names as its own corrective, so an
    undriven `--full` left limit 4 with no corrective.

    The end-to-end `--full` verdict is still not driven here (~23 min for both
    sides); what IS driven is the selection it produces and the measured fact
    that the full suite is green inside a clone -- 8510 passed / 0 failed /
    rc=0 in 693.84s, once `run_pytest` stopped setting CLAUDE_PROJECT_DIR.
    """

    def test_full_selects_the_declared_test_roots(self):
        roots = declared_test_roots(REPO_ROOT)
        changes = commit_changes(REPO_ROOT, DOCS_ONLY)
        selection, notes = select_tests(REPO_ROOT, changes, roots, full=True)
        assert selection == [r for r in roots if (REPO_ROOT / r).exists()], selection
        assert selection, "non-vacuity: --full must select something"
        assert any("--full" in n for n in notes), notes

    def test_the_default_selection_is_narrower_than_full(self):
        """Non-vacuity for the pair: if the two agreed, `--full` would be a
        no-op and limit 4 would not exist."""
        roots = declared_test_roots(REPO_ROOT)
        changes = commit_changes(REPO_ROOT, UNPINNED_BUT_CHANGED_TESTS)
        narrow, _ = select_tests(REPO_ROOT, changes, roots, full=False)
        wide, _ = select_tests(REPO_ROOT, changes, roots, full=True)
        assert narrow != wide, (narrow, wide)
