"""Every required status check a doc instructs must be a name GitHub can report.

Branch protection's required-checks list matches **check runs**, which are named
after JOBS -- not after the workflow, not after the workflow FILE, and not after
a matrix job's bare id. A required check that never reports does not fail the
PR; it parks it on *"Expected — waiting for status to be reported"* forever, with
no route to merge but deleting the rule. So this class of error is silent until
the one moment it is most expensive: configuring branch protection on a repo
going public.

The three spellings that never report, all of which have shipped here:

1. the WORKFLOW name (``Harness Guard``) -- fixed previously in
   ``espalier/cli.py`` and ``docs/INSTALL-CI.md``;
2. the workflow FILE slug (``harness-guard``) -- the surviving instance this
   contract was written against, in the pre-launch branch-protection step;
3. a MATRIX job's bare id (``test``) -- ``test.yml``'s ``test`` job is a 5-cell
   ``python-version`` matrix, so its check runs are ``test (3.10)`` … ``test
   (3.14)``. The bare name looks correct, resolves to a real job id, and still
   never reports. This is the spelling a job-id-membership check would miss,
   which is why the resolver below models matrices and job-level ``name:``
   rather than asking "is this a job?".

Scope note -- BOTH halves are derived, and that is the point. The expectation
comes from the workflow YAML below. The POPULATION comes from
``claim_extractor``'s audited-claim globs unioned with the recursive ``docs/``
walk; no list of files is written here. A guard that derives only its
expectation still *reads* as derived -- the resolver is right there in the body
-- so the review question "what is this pointed at?" gets answered by the half
that was already fine and stops one step early (``docs/FAILURE_MODES.md``
13.28). This file had exactly that shape: it walked ``docs/`` and nothing else,
so ESPALIER_MEMORY.md -- which quotes ``Harness Guard`` verbatim while
describing this very defect -- was outside the scan by accident of where the
walk started rather than by any classification.

Records stay out for a reason someone wrote down instead: they are absent from
``DEFAULT_DOC_GLOBS`` as historical narratives, or excluded by name as frozen
records. That is what keeps a fix from being chased into a document whose
entries are correct as history (root ``CLAUDE.md`` Core Rule 13).
"""
from __future__ import annotations

import re
import sys
from fnmatch import fnmatch
from pathlib import Path

import pytest

# PyYAML is a dev extra: `pip install -e .` (no `[dev]`) lacks it, so a bare
# `import yaml` is a collection ERROR for the whole run (the shape TP-181 fixed
# once in test_e2e_bench.py). Skip this module instead.
yaml = pytest.importorskip(
    "yaml", reason="PyYAML not installed — run `pip install -e .[dev]`")

# ``_enumerate_files`` is private and imported deliberately: it is the only seam
# that resolves the audited-claim globs, and restating those globs here would
# rebuild the declared half this module exists to remove. Promote it to a public
# accessor when a second guard needs the same population -- one consumer does not
# earn a new public surface on ``espalier/`` (see espalier/CLAUDE.md).
from espalier.claim_extractor import (
    DEFAULT_DOC_GLOBS,
    EXCLUDED_DOC_GLOBS,
    FROZEN_RECORD_DOCS,
    RECORD_SURFACES,
    _enumerate_files,
)
from tests._git_oracle import require_is_gitignored, require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.

# A check can only be *required* if it reports on a pull request; a job in a
# workflow that never triggers on `pull_request` parks the PR exactly like a
# nonexistent one.
_PR_TRIGGER = "pull_request"

# Anchored instruction forms. Kept narrow deliberately: a loose pattern over
# prose would sweep ordinary mentions of a job name and turn this contract into
# a noise generator. `_FLOOR` below is what keeps the narrowness honest.
_LIST_FORM = re.compile(r"required status checks?\s*:", re.IGNORECASE)
_SINGLE_FORM = re.compile(
    r"""(?:require\s+status\s+check|status\s+check\s+named)\s*
        [:\s]*\**[`'"]([^`'"]+)[`'"]""",
    re.IGNORECASE | re.VERBOSE,
)
_BACKTICKED = re.compile(r"`([^`]+)`")
# Shapes a required-checks list is actually written in. The first version of this
# contract consumed continuation lines until one matched `\s*[-*\d]`, which is the
# START of a markdown bullet -- so a bullet list, the most natural rendering, broke
# the scan on its first item and yielded NOTHING. Measured after the population was
# widened to README.md: bullet, asterisk, numbered, table and fenced forms all
# extracted zero names, so the widening bought reach without recognition.
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_ROW = re.compile(r"^\s*\|")
_FENCE = re.compile(r"^\s*```")

# Non-vacuity floor. Every extractor over prose can silently stop matching -- a
# heading reworded, a colon dropped -- and then this file passes by finding nothing
# at all.
#
# MEASURED, and reproducible: `sum(len(_instructed_checks(t)) for _, t in _sources())`
# is 10 on 2026-08-13. The previous value of 5 was calibrated on the PRE-FIX text and
# never re-measured by the same commit that doubled the count, leaving 2x slack on the
# guard whose whole job is noticing silence. Its comment also described a
# "minus one duplicate" step the code does not perform -- the sum is per-source with
# no cross-source dedup.
_FLOOR = 10

# The surfaces that instruct TODAY. A hand-written list is correct *here* and nowhere
# else in this file: this is a must-not-go-silent WITNESS, not a population. The floor
# above is a repo-wide total, and 8 of the 10 come from one maintainer document -- so
# both adopter-facing surfaces could be reworded into phrasings nothing anchors, the
# total would still clear the floor, and the guard would say nothing while an adopter
# was told to require a check that parks every PR forever. Measured by executing that
# rewording: total 8, all arms green.
_MUST_YIELD = ("docs/INSTALL-CI.md", "docs/RELEASE_CHECKLIST.md", "espalier/cli.py")


@pytest.fixture(scope="module")
def check_run_resolver():
    return _build_resolver()


class Job:
    """One workflow job, and what its check runs can actually be called."""

    def __init__(self, workflow: str, job_id: str, spec: dict, on_pr: bool):
        self.workflow = workflow
        self.job_id = job_id
        self.on_pr = on_pr
        self.display_name = spec.get("name") if isinstance(spec, dict) else None
        strategy = spec.get("strategy") if isinstance(spec, dict) else None
        self.matrix = bool(
            isinstance(strategy, dict) and strategy.get("matrix")
        )

        self._matrix_spec = (
            strategy.get("matrix") if isinstance(strategy, dict) else None
        )

    @property
    def reports_bare(self) -> str | None:
        """The exact check-run name, when it is a single fixed string.

        A matrix job has one check run PER CELL, named ``<base> (<values>)``, so
        no bare name reports. A job-level ``name:`` containing a `${{ }}`
        expression is likewise per-cell.
        """
        base = self.display_name or self.job_id
        if self.matrix or "${{" in str(base):
            return None
        return str(base)

    def cell_names(self) -> list[str]:
        """Concrete per-cell check-run names, when the matrix is resolvable.

        GitHub renders ``<base> (<v1>, <v2>, …)`` with the values in matrix-key
        order. Only plain scalar lists are expanded; a matrix using
        ``include``/``exclude``, or a ``name:`` carrying an expression, is left
        unresolved rather than guessed -- an over-confident expansion here would
        invent names and green-light a doc that is wrong.
        """
        base = self.display_name or self.job_id
        if not self.matrix or "${{" in str(base):
            return []
        spec = self._matrix_spec
        if not isinstance(spec, dict):
            return []
        axes = []
        for key, values in spec.items():
            if key in ("include", "exclude"):
                return []
            if not isinstance(values, list) or any(
                isinstance(v, (dict, list)) for v in values
            ):
                return []
            axes.append([str(v) for v in values])
        if not axes:
            return []
        combos = [[]]
        for axis in axes:
            combos = [combo + [value] for combo in combos for value in axis]
        return [f"{base} ({', '.join(combo)})" for combo in combos]

    def describe(self) -> str:
        where = f"{self.workflow}:{self.job_id}"
        if self.matrix:
            base = self.display_name or self.job_id
            return (
                f"{where} is a MATRIX job, so its check runs are "
                f"'{base} (<cell>)', never bare '{base}'"
            )
        if self.display_name:
            return (
                f"{where} sets `name:` — its check run is "
                f"'{self.display_name}', not the job id"
            )
        return f"{where} reports as '{self.job_id}'"


def _build_resolver() -> tuple[dict[str, Job], list[Job]]:
    """Return (reportable-name -> Job) and every PR-triggered job."""
    reportable: dict[str, Job] = {}
    pr_jobs: list[Job] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # `on:` parses as the boolean True in YAML 1.1 unless quoted.
        triggers = data.get("on", data.get(True)) or {}
        # Normalised across all three spellings. Reading only the dict form made
        # `on: [push, pull_request]` -- a routine style edit -- silently drop every
        # job in that workflow from `reportable`, which then reported correct docs
        # as naming checks that "match no job".
        if isinstance(triggers, dict):
            trigger_names = set(triggers)
        elif isinstance(triggers, list):
            trigger_names = {str(t) for t in triggers}
        else:
            trigger_names = {str(triggers)}
        on_pr = _PR_TRIGGER in trigger_names
        for job_id, spec in (data.get("jobs") or {}).items():
            job = Job(path.name, str(job_id), spec or {}, on_pr)
            if not on_pr:
                continue
            pr_jobs.append(job)
            name = job.reports_bare
            if name is not None:
                reportable.setdefault(name, job)
            for cell in job.cell_names():
                reportable.setdefault(cell, job)
    return reportable, pr_jobs


def _scannable_docs() -> list[Path]:
    """Every surface the repo already treats as asserting something live.

    Two derived enumerations, unioned. Neither names a file, so a new document
    is covered the moment it lands and a record stays out for a stated reason:

    1. ``claim_extractor``'s audited-claim globs -- the place this repo already
       answers *"does this document assert something about current state?"*.
       README.md, CLAUDE.md, CONTRIBUTING.md and the ``.claude/`` bodies arrive
       through it. The historical narratives (ESPALIER_MEMORY.md, CHANGELOG.md)
       are absent from ``DEFAULT_DOC_GLOBS`` by that same classification, with
       the reason stated where the tuple is defined.
    2. the recursive ``docs/`` walk minus ``FROZEN_RECORD_DOCS`` -- ``docs/*.md``
       in (1) is NOT recursive, so this keeps ``docs/sharp-edges/**`` and any
       future subdirectory that (1) alone would silently drop.

    Not included, deliberately: ``espalier/assets/docs/`` mirrors. Each is a
    byte-copy of its ``docs/`` original enforced by ``scripts/sync_asset_docs.py
    --check``, so scanning the source covers the shipped twin; scanning both
    would double-report one defect.
    """
    frozen = set(FROZEN_RECORD_DOCS)
    seen: dict[str, Path] = {}

    def _add(path: Path) -> None:
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        # (2) restores RECURSION under docs/, not audit-excluded documents. Without
        # this the walk would re-admit exactly what (1) classified out -- the
        # external pins and the narrative logs -- and the two halves would disagree
        # about the same file.
        if rel in frozen or any(fnmatch(rel, g) for g in EXCLUDED_DOC_GLOBS):
            return
        seen.setdefault(rel, path)

    for path in _enumerate_files(REPO_ROOT, DEFAULT_DOC_GLOBS, EXCLUDED_DOC_GLOBS):
        _add(path)
    for path in REPO_ROOT.joinpath("docs").rglob("*.md"):
        _add(path)
    return [seen[rel] for rel in sorted(seen)]


def _collect_block(lines: list[str], start: int) -> tuple[list[str], list[str]]:
    """Lines belonging to the required-checks instruction beginning at ``start``.

    Returns (quoted_lines, bare_lines): text to mine for backticked names, and
    fenced-code lines whose content IS the name, one per line.

    Two shapes, distinguished by whether the header line already carries names:

    * **inline** (``Required status checks: `a`, `b`,``) -- the list wraps, so only
      lines indented DEEPER than the header continue it. A sibling list item at the
      header's own indent ends the block. This is what stops the scan swallowing the
      explanatory paragraph that follows, which otherwise contributes fictional
      names like ``Settings -> Branches`` from ordinary prose.
    * **block** (header ends at the colon) -- the names are in the list, table or
      fence that follows, possibly after a blank line. Ordinary prose at the
      header's indent ends it.
    """
    header = lines[start]
    match = _LIST_FORM.search(header)
    assert match is not None
    tail = header[match.end():]
    header_indent = len(header) - len(header.lstrip())
    inline = bool(_BACKTICKED.search(tail))

    quoted: list[str] = [tail]
    bare: list[str] = []
    in_fence = False

    for nxt in lines[start + 1:]:
        if _FENCE.match(nxt):
            if in_fence:
                break
            in_fence = True
            continue
        if in_fence:
            if nxt.strip():
                bare.append(nxt.strip())
            continue
        if not nxt.strip():
            if inline:
                break
            continue
        indent = len(nxt) - len(nxt.lstrip())
        if inline:
            if indent > header_indent and not _LIST_ITEM.match(nxt):
                quoted.append(nxt)
                continue
            break
        if _LIST_ITEM.match(nxt) or _TABLE_ROW.match(nxt) or indent > header_indent:
            quoted.append(nxt)
            continue
        break
    return quoted, bare


def _instructed_checks(text: str) -> set[str]:
    """Check names a reader is told to enter into branch protection."""
    found: set[str] = set()
    for match in _SINGLE_FORM.finditer(text):
        found.add(match.group(1).strip())
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _LIST_FORM.search(line):
            continue
        quoted, bare = _collect_block(lines, i)
        for name in _BACKTICKED.findall(" ".join(quoted)):
            found.add(name.strip())
        found.update(bare)
    # Table rows contribute their separator cells (`---`); a fence contributes any
    # decoration on its own line. Neither is a check name, and neither is anything
    # a reader would type into the branch-protection box.
    return {n for n in found if n and not set(n) <= set("-|: ")}


def _sources() -> list[tuple[str, str]]:
    """(label, text) for every surface that instructs a required check."""
    out = [
        (str(p.relative_to(REPO_ROOT)).replace("\\", "/"), p.read_text(encoding="utf-8"))
        for p in _scannable_docs()
    ]
    # Code prints branch-protection instructions too, and that text reaches an
    # adopter who has no docs/ at all -- `espalier install-ci`'s banner, and
    # `ci_guard`'s exit-2 output, which a contributor meets in a CI log.
    #
    # DERIVED, not the single `cli.py` this listed until 2026-08-13. The docstring
    # above claims both halves are derived while a hand-written entry sat here --
    # the one place no arm examined, which is the exact shape the population fix
    # was written to remove, one function below it.
    for root in ("espalier", "tools/cc"):
        for path in sorted((REPO_ROOT / root).glob("*.py")):
            out.append((
                str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                path.read_text(encoding="utf-8"),
            ))
    return out


class TestRequiredStatusCheckNamesResolve:
    def test_extractor_is_not_vacuous(self):
        total = sum(len(_instructed_checks(text)) for _, text in _sources())
        assert total >= _FLOOR, (
            f"found only {total} instructed status-check names across the repo "
            f"(floor {_FLOOR}). The extractor is anchored on narrow phrasings, so "
            "a reworded heading makes this whole contract pass by matching "
            "nothing. Re-anchor the patterns or lower the floor deliberately."
        )

    def test_each_instructing_surface_still_matches(self):
        """Per-surface, because a repo-wide total hides a surface going silent."""
        by_label = {label: _instructed_checks(text) for label, text in _sources()}
        silent = [rel for rel in _MUST_YIELD if not by_label.get(rel)]
        assert not silent, (
            f"{silent} instructed a required status check and now yields none, so "
            "this contract no longer reads them. Re-anchor the patterns against how "
            "the text is written now -- do NOT drop the surface from the witness or "
            "lower the floor, which is how a guard converges to checking nothing."
        )

    def test_the_markdown_forms_a_list_is_written_in_are_all_read(self):
        """The population reaching a document is not the same as reading it.

        Until 2026-08-13 the block scan stopped on the first line matching
        ``\\s*[-*\\d]`` -- the start of a bullet -- so every list form except the one
        inline spelling this repo happens to use extracted NOTHING. Widening the
        population to README.md therefore bought reach without recognition: a
        branch-protection section written there as a bullet list, the obvious way,
        would have shipped bad names green.
        """
        cases = {
            "inline": "Required status checks: `verify`, `test`.\n",
            "hyphen bullets": "Required status checks:\n\n- `verify`\n- `test`\n",
            "asterisk bullets": "Required status checks:\n\n* `verify`\n* `test`\n",
            "numbered": "Required status checks:\n\n1. `verify`\n2. `test`\n",
            "fenced": "Required status checks:\n\n```\nverify\ntest\n```\n",
        }
        for label, text in cases.items():
            assert _instructed_checks(text) == {"verify", "test"}, (
                f"the {label} form extracted {sorted(_instructed_checks(text))}, "
                "not the two names it states"
            )
        table = "Required status checks:\n\n| check |\n|---|\n| `verify` |\n"
        assert "verify" in _instructed_checks(table), "table form extracted nothing"

    def test_prose_after_an_inline_list_is_not_mined_for_names(self):
        """Over-consumption invents names, and a false RED trains people to delete guards."""
        # The following line carries NO bullet. That matters: the old consumer broke
        # on `\s*[-*\d]`, so a bulleted paragraph happened to stop it and only
        # unbulleted prose leaked. A fixture using a bullet here would pass against
        # the defect and pin nothing.
        found = _instructed_checks(
            "Required status checks: `verify`\n"
            "Enter it under `Settings -> Branches` in the `Actions` tab.\n"
        )
        assert found == {"verify"}, (
            f"adjacent prose contributed {sorted(found - {'verify'})} as check "
            "names; a maintainer would be told a correct document is wrong"
        )

    def test_at_least_one_workflow_reports_on_pull_requests(self, check_run_resolver):
        reportable, pr_jobs = check_run_resolver
        assert pr_jobs, "no job in .github/workflows triggers on pull_request"
        assert reportable, "no PR-triggered job has a fixed check-run name"

    def test_every_instructed_check_can_actually_report(self, check_run_resolver):
        reportable, pr_jobs = check_run_resolver
        by_job_id = {}
        for job in pr_jobs:
            by_job_id.setdefault(job.job_id, job)
        workflow_names = {p.stem for p in WORKFLOW_DIR.glob("*.yml")}

        problems: list[str] = []
        for label, text in _sources():
            for name in sorted(_instructed_checks(text)):
                if name in reportable:
                    continue
                if name in by_job_id:
                    problems.append(
                        f"{label}: '{name}' — {by_job_id[name].describe()}"
                    )
                elif name in workflow_names:
                    problems.append(
                        f"{label}: '{name}' is a workflow FILE name, not a check "
                        "run. Branch protection lists check runs, which are named "
                        "after jobs."
                    )
                else:
                    problems.append(
                        f"{label}: '{name}' matches no job in any PR-triggered "
                        "workflow, so no check run will ever report under it."
                    )

        # A job this resolver could not model contributes NO name, so an instruction
        # naming it looks identical to an instruction naming nothing. Saying so
        # turns "your document is wrong" into "I could not check this one", which
        # is the difference between fixing a doc and breaking a correct one.
        unresolved = [
            j.describe() for j in pr_jobs
            if j.reports_bare is None and not j.cell_names()
        ]
        caveat = (
            "\n\nNOTE: these jobs could not be modelled (include/exclude matrix, or "
            "an expression in `name:`), so a name that should have matched one of "
            "them is reported above as matching nothing — check these before "
            "editing any document:\n  " + "\n  ".join(sorted(unresolved))
        ) if unresolved else ""

        assert not problems, (
            "these docs instruct required status checks that GitHub will never "
            "report, so a maintainer configuring branch protection as written "
            "parks every PR on 'Expected — waiting for status to be reported':\n  "
            + "\n  ".join(problems)
            + "\n\nReportable names today: "
            + ", ".join(sorted(reportable))
            + caveat
        )


class TestPopulationIsDerived:
    """The half a review skips: not *is the check correct* but *what is it
    pointed at, and is my subject inside that set?* (docs/FAILURE_MODES.md 13.28)."""

    # Historical narratives: each says what was true on a date, and several quote a
    # bad check name verbatim while describing this defect. They are out of the
    # population by CLASSIFICATION -- absent from DEFAULT_DOC_GLOBS, or named in
    # FROZEN_RECORD_DOCS -- and this is the assertion's SUBJECT, never the
    # mechanism that excludes them.
    #
    # Derived from the record axis rather than hand-listed. A local tuple here
    # would be a sixth private answer to the question the axis exists to hold
    # once, and it would go stale in exactly the direction that hurts: a record
    # added elsewhere but forgotten here is one this scan stops protecting.
    _RECORDS = tuple(sorted(RECORD_SURFACES))

    @staticmethod
    def _scanned() -> set[str]:
        return {
            str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in _scannable_docs()
        }

    def test_historical_narratives_stay_outside_the_population(self):
        """Widening this scan to all tracked markdown is the tempting wrong fix.

        It reds immediately -- on records that are CORRECT as written -- and the
        obvious way to clear that red is to edit the record, which falsifies it.
        """
        leaked = sorted(rel for rel in self._RECORDS if rel in self._scanned())
        assert not leaked, (
            "record surfaces entered the scanned population: "
            f"{leaked}. They quote bad check names while DESCRIBING the defect; "
            "an entry is correct as of its date and editing one to clear this "
            "check falsifies the record (root CLAUDE.md Core Rule 13). If the "
            "population needed widening, widen it and classify these out -- do "
            "not rewrite them."
        )

    def test_the_record_boundary_is_load_bearing(self, check_run_resolver):
        """An exclusion protecting nothing should say so rather than pass quietly.

        If no record still quotes an unreportable name, this boundary has gone
        inert and the next reader inherits a skip that buys nothing -- the
        `_RECORDS` tuple above would then be dead weight defended by habit.

        A fresh clone is not that case. The record that carries the quote today
        is gitignored dev-tree state (`docs/session-archive.md`), so on a clone
        the witness is ABSENT, not inert: for a record missing from disk this
        row asks git whether it is ignored and untracked -- never the disk
        alone, the born-weak shape fixed once at `14f834e` -- and skips naming
        it. Where every record is present the assertion keeps its full
        strength (measured 2026-09-22: the row was the one red of the full
        suite in a fresh clone on both 3.14 and 3.10).

        Reach, stated so nobody reads the skip as coverage: the quote lives in
        a gitignored archive, so this row can only JUDGE on a checkout that has
        it -- the maintainer's tree. On every clone it skips, by design and
        out loud; it is a dev-tree maintenance signal for the `_RECORDS`
        exclusion, not a CI gate. The exclusion itself is principled (records
        are not audited surfaces -- root `CLAUDE.md` Core Rule 13), so a red
        here means "retire the exclusion or find the witness", never "put a
        quote in a tracked record to green the row". The skip fires only when
        NO present record fires, EVERY absent record is gitignored and
        untracked, and at least one tracked record was present and read -- a
        checkout with a missing tracked record is a different failure and
        reds like one.
        """
        reportable, _ = check_run_resolver
        firing: list[str] = []
        absent_local: list[str] = []
        absent_other: list[str] = []
        present_tracked = 0
        for rel in self._RECORDS:
            path = REPO_ROOT / rel
            tracked = bool(require_tracked_paths(REPO_ROOT, rel, minimum=0, what=rel))
            if not path.exists():
                if not tracked and require_is_gitignored(REPO_ROOT, rel):
                    absent_local.append(rel)
                else:
                    absent_other.append(rel)
                continue
            present_tracked += tracked
            names = _instructed_checks(path.read_text(encoding="utf-8"))
            if any(name not in reportable for name in names):
                firing.append(rel)
        assert not absent_other, (
            f"tracked (or unignored) records missing from disk: {absent_other} -- not the "
            "fresh-clone shape; this checkout is broken, not clean"
        )
        if not firing and absent_local and present_tracked:
            pytest.skip(
                f"{', '.join(absent_local)}: gitignored and untracked, absent on this "
                "checkout (a fresh clone) -- the boundary's witness is missing here, not "
                "inert; a dev-tree maintenance signal, judged only where the archive exists"
            )
        assert firing, (
            "no record surface quotes an unreportable check name any more, so "
            f"excluding {list(self._RECORDS)} from the scan is now inert. Either "
            "a record was rewritten (which this suite exists to prevent) or the "
            "quotes aged out of the bounded logs -- confirm which, then retire "
            "this boundary rather than leaving an exclusion nobody can justify."
        )

    def test_the_population_reaches_the_front_door(self):
        """A branch-protection step is at least as likely to land in README.

        The population walked only `docs/` until 2026-08-13, so an instruction
        added to either of these would have been unguarded while the contract
        went on reporting green.
        """
        scanned = self._scanned()
        for rel in ("README.md", "CONTRIBUTING.md"):
            assert (REPO_ROOT / rel).exists(), f"{rel} vanished -- update this pin"
            assert rel in scanned, (
                f"{rel} is outside the scanned population, so a required-status-"
                "check instruction added there is unguarded. The population is "
                "derived from claim_extractor's audited-claim globs; if this "
                "reds, that classification moved and the reason should be read "
                "before it is worked around."
            )


class TestEveryMatrixReadsEveryCell:
    """`fail-fast: false` on every matrix, derived from the workflow glob. The
    2026-09-24 closing witness on the release tree lost three of its five
    clean-checkout cells to fail-fast on one runner-relative red, so the
    matrix read three interpreters not at all (DEF-922); the fix went on
    every matrix and this row keeps it there -- a YAML tidy-up or a copied
    job would otherwise restore the cancellation silently (failure-mode
    review)."""

    @staticmethod
    def _matrices() -> list[tuple[str, str, dict]]:
        out: list[tuple[str, str, dict]] = []
        for path in sorted(WORKFLOW_DIR.glob("*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for job_id, spec in (data.get("jobs") or {}).items():
                strategy = spec.get("strategy") if isinstance(spec, dict) else None
                if isinstance(strategy, dict) and "matrix" in strategy:
                    out.append((path.name, str(job_id), strategy))
        return out

    def test_the_population_is_not_vacuous(self):
        """Four matrices on 2026-09-24 (test.yml x2, portability.yml,
        release.yml); a glob that finds none is a broken glob, not a repo
        without matrices."""
        assert len(self._matrices()) >= 4, [f"{w}:{j}" for w, j, _ in self._matrices()]

    def test_every_matrix_declares_fail_fast_false(self):
        offenders = [f"{wf}:{job}" for wf, job, strategy in self._matrices() if strategy.get("fail-fast") is not False]
        assert not offenders, (
            f"matrices that cancel their sibling cells on one red: {offenders} -- "
            "add `fail-fast: false` under `strategy:` so one dispatch reads every cell"
        )

    def test_the_rule_reds_on_a_matrix_without_fail_fast(self, tmp_path, monkeypatch):
        """The must-trip twin: a workflow whose matrix omits the key, or sets it
        true, is an offender."""
        (tmp_path / "w.yml").write_text(
            "on: push\njobs:\n  a:\n    strategy:\n      matrix:\n        x: [1, 2]\n"
            "  b:\n    strategy:\n      fail-fast: true\n      matrix:\n        x: [1]\n"
            "  c:\n    strategy:\n      fail-fast: false\n      matrix:\n        x: [1]\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(sys.modules[__name__], "WORKFLOW_DIR", tmp_path)
        offenders = [f"{wf}:{job}" for wf, job, strategy in self._matrices() if strategy.get("fail-fast") is not False]
        assert offenders == ["w.yml:a", "w.yml:b"]
