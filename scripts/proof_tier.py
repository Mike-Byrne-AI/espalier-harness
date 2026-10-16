#!/usr/bin/env python3
"""Which proof tier does this working tree earn -- and is every new file visible?

The proof-order bodies (`/implement-task` step 7, `/preflight` Step 2,
`/implement-pack` step 6) state one rule: a change that touched no engine code
and no hook runs the tree-wide contracts (`pytest -m contract -q`); a change
that touched a file the pull-recall corpus reads (``memory/``, the two
catalogs, ``docs/sharp-edges/``, the principles) runs those contracts and then
the recall engine's own tests, because a corpus edit moves the calibration
pins while touching no runtime path (five went red unseen on 2026-09-11 under
the contract slice -- DEF-775); a change on the shipped runtime, and every
handoff, runs the full suite. Stated in four places by hand, the boundary
drifted into three spellings within a day (failure-mode pass, 2026-09-06).
This script IS the boundary: the bodies cite it, and a test pins what it
answers.

It also names every untracked file it sees, because the gates that derive
their population from ``git ls-files`` (encoding pins, citation resolvers,
inventory counts) cannot see a file that has not been staged -- seven unpinned
subprocess encodings shipped in a commit that way on 2026-09-06, green in the
full run before the commit and red in the first contract run after it.
``git add -N <file>`` makes a new file visible without staging its content.
The twin: a tracked file deleted but not staged is still an index row, so
the same gates enumerate a file that is not there (the tracked-set oracle
leaves it out since 2026-10-01, which is how it stopped crashing them);
``git add -u <file>`` stages the deletion and the population is honest again.

The full tier's command lines are the hook type gate, the lint line, then the
parallel recipe: ``pytest -n auto`` with the five serial files left out, then
those five serially. The pytest pair is
the local default since 2026-09-06, after the two clean full runs
``tests/README.md`` pre-registered as the count the flip needed (6:31 and 6:12
on the 8 GB self-host box, against 18:41-19:52 serial -- the 2026-09-06 figures;
by 2026-09-23 the tier's floor was the stage-one smoke's nested serial not-slow
child, about twelve minutes on its own, so a full tier reads longer than either:
DEF-919). The contract slice's
own parallel form raced on the live tree the same day, so the slice stays
serial. A parallel full run that errors on a live-tree race is a loud error,
never a false green: rerun the failing file serially and add the date and the
test to the races line in ``tests/README.md`` (the flip rests on two clean
runs; the counter-evidence needs a home or it is rerun and forgotten).
``pytest-xdist`` ships in the ``dev`` extra; without it the ``-n`` flag is
rejected, loudly.

The full tier runs ``mypy tools/cc/hooks/`` FIRST. That near-strict type gate
existed only in CI (Harness Guard's ``mypy-hooks`` job) from 2026-07-23, and
the shape it exists to catch -- a hook typed ``-> bool`` that falls off the end
and fail-opens -- shares a gate with a plain missing annotation, which is what
landed unread twice: 2026-08-13 (DEF-544 filed then, naming the local gate as
the fix) and 2026-09-03, when the hook copy of ``parse_python_version`` was
authored unannotated and the job sat red across two pushes. Every hook or
engine change earns this tier, so the gate now fires on exactly the diffs that
can break it; a missing ``mypy`` is a loud exit 127, never a skipped line.

``--run`` executes the tier's command(s) in order and prints a receipt line per
command, then a summary naming how many ran and the worst exit code. The full
tier is four commands, the recall tier three and the contract tier two: the
lint line (``ruff check .``) sits in every tier, right after the type gate
where there is one, because a lane's lint red once reached the pull request
past a green full tier (no tier ran ruff, and the ruff-lint cell is not a
required check -- 2026-10-01). A session that pastes only one command
gets a green that never ran the rest -- one command with one receipt closes
that. ``--tier full`` forces the tier (the handoff's preflight runs the full
suite whatever the diff earned).

Beside the tier it prints the reviewers the diff's surface earns: the
``review:`` line (``review`` and ``review_earned_by`` in ``--json``), the
review rule of ``/implement-task`` and ``/preflight`` step 6 computed from the
same changed paths -- ``none``, ``code-reviewer`` or ``both`` -- with each path
that earned it. The bodies stated the rule in prose and the worker tick said
"both reviewers" for every lane, so a records lane ran two reviewers it had not
earned. A hook, a command / agent / skill / workflow body or a gate earns both;
a gate is the CI definition, ``bench/`` and every repo file a workflow at the
diff's head calls (its ``run:`` steps and local ``uses:``), read from the
workflows at classification time and never kept by hand. ``--quiet`` prints
the tier word alone and never reads the workflows.

Usage::

    python3 scripts/proof_tier.py                    # prints the tier, the review line and the command line(s)
    python3 scripts/proof_tier.py --run              # ...and runs them, one receipt
    python3 scripts/proof_tier.py --run --tier full  # the handoff's preflight form
    python3 scripts/proof_tier.py --json
    python3 scripts/proof_tier.py --base origin/main --quiet   # CI: one word, the PR's own diff

Exit codes: 0 = tier printed and every new file is visible to git;
2 = untracked files remain (they are listed; `git add -N` them first);
3 = ``--base`` could not be resolved against HEAD (a shallow checkout, a
missing ref) -- the CI tier job reads that as ``full``, never as cheaper.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

_ROOT = Path(__file__).resolve().parents[1]

#: The shipped runtime. ``espalier/assets/`` is a byte-mirror of `.claude/` and
#: `docs/` sources (a docs batch syncs into it); ``espalier/_vendor/cc/`` is a
#: byte-mirror of ``tools/cc/`` (which itself triggers). Neither is engine code.
_FULL_PREFIXES: tuple[str, ...] = ("tools/cc/",)
_ENGINE_PREFIX = "espalier/"
_ENGINE_MIRROR_PREFIXES: tuple[str, ...] = ("espalier/assets/", "espalier/_vendor/")

#: The CI definition. Not shipped runtime, but the thing a pull request's own
#: run executes: in ``--base`` mode (that run) a change here earns the full
#: tier, so the workflow under test runs its heaviest path on the very PR that
#: changes it. Locally the same edit earns the contract slice, which holds the
#: workflow-reading contracts; the suite cannot execute a workflow. The tier job
#: in .github/workflows/test.yml asks this script through ``--base``, so the
#: answer CI acts on and the answer the local run prints are one computation.
_CI_DEFINITION_PREFIXES: tuple[str, ...] = (".github/workflows/", ".github/actions/")

#: The suite's own configuration and shared test code. Not shipped runtime, but
#: a change here moves what EVERY test does -- the markers and slices
#: (pyproject.toml, tests/conftest.py), the helpers many modules import
#: (tests/_*.py), the harness config the runtime reads (espalier.toml) -- so it
#: earns the full tier everywhere: the contract slice cannot vouch for a suite
#: whose selection it no longer knows (failure-mode review, 2026-09-25).
_SUITE_CONFIG_FILES: tuple[str, ...] = ("pyproject.toml", "espalier.toml", "tests/conftest.py")

#: The review rule of ``/implement-task`` and ``/preflight`` step 6, computed
#: from the same changed paths as the tier (``review``): a path on the review
#: surface earns ``code-reviewer``; a hook, a command / agent / skill /
#: workflow body, or a gate earns ``failure-mode-reviewer`` beside it
#: (``both``); anything else earns ``none``. The bodies stated it in prose and
#: the worker tick said "both reviewers" for every lane, so records lanes ran
#: two reviewers they had not earned (review rounds per reviewed pull request
#: 1.8, then 2.6, over the 36 merges from 2026-10-14; air's assign, 2026-10-16).
#: The surface is the step 6 list: the shipped runtime (``is_runtime``) and
#: these roots, ``.github/actions/`` beside the workflows. The byte mirrors
#: decide nothing alone, as in the tier: their sources do.
_REVIEW_PREFIXES: tuple[str, ...] = (".claude/", "bench/", "scripts/") + _CI_DEFINITION_PREFIXES
_HOOK_PREFIX = "tools/cc/hooks/"
_BODY_PREFIXES: tuple[str, ...] = (
    ".claude/commands/", ".claude/agents/", ".claude/skills/", ".claude/workflows/",
)
#: A gate is what CI runs as one: the CI definition (``is_ci_definition``),
#: ``bench/`` (the release gate), and every repo file a workflow at the diff's
#: head calls (``workflow_named_files``) -- derived at classification time and
#: never kept by hand, so a script joins the moment a workflow calls it.
_BENCH_PREFIX = "bench/"
REVIEWS: tuple[str, ...] = ("none", "code-reviewer", "both")
#: The characters that end a shell word outside quotes (``_shell_words``).
_SHELL_OPERATORS = ";|&()<>`"

#: The files that assert wall-clock budgets (a regex must finish inside 100 ms,
#: a speed bump inside its window). Under ``-n auto`` the box is oversubscribed
#: and they fail on scheduler wait, not on a regression, so the full tier leaves
#: them out of the parallel run and runs them serially after it (16 s). The
#: audit that named them: ``tests/README.md``, "Parallel-safety". This tuple is
#: the list's one home; the bodies say "the two lines this script prints".
WALL_CLOCK_SERIAL_FILES: tuple[str, ...] = (
    "tests/test_redos.py",
    "tests/test_speedbump_irreversible.py",
    "tests/test_hooks.py",
)

#: The end-to-end gates whose serial duration sits inside the parallel load
#: factor of their timeout ceiling. Measured 2026-09-25 on ubuntu-latest: the
#: guard-metamorphic quick matrix 47 s against the 60 s global ceiling, the
#: PowerShell reachability gate 499 s against its 900; under ``-n auto`` on the
#: same runner every long test ran 1.3 to 1.8 times slower, and pytest-timeout's
#: thread method (then forced on every host; Windows-only since 2026-10-07)
#: exits the WORKER on expiry, so both read as a worker crash in all five cells
#: of the first parallel run there (PR #4). Alone on the serial
#: leg they run at their serial duration. Same one-home rule as the wall-clock
#: list above: the recipe ignores both lists in the parallel leg and runs both
#: serially after it; the PowerShell gate skips wherever ``pwsh`` is absent.
TIMEOUT_NEAR_SERIAL_FILES: tuple[str, ...] = (
    "tests/test_guard_metamorphic.py",
    "tests/test_powershell_reachability_differential.py",
)
#: Everything the parallel leg leaves out and the serial leg runs.
SERIAL_FILES: tuple[str, ...] = WALL_CLOCK_SERIAL_FILES + TIMEOUT_NEAR_SERIAL_FILES

#: The recall engine's own tests: the calibration pins, the eval instrument and
#: the pasted-table contracts. They score the corpus the tree holds, so a change
#: to a corpus file moves them while touching no runtime path -- on 2026-09-11 a
#: memory/ and docs/ fold landed on the contract slice with five of them red,
#: and the reds surfaced in the next lane's full tier (DEF-775). A change under
#: a corpus root earns this slice on top of the contract tier. Hand-kept like
#: ``WALL_CLOCK_SERIAL_FILES``; the derived complement (every
#: ``tests/test_recall*.py``) is pinned in tests/test_proof_tier.py.
RECALL_SLICE_FILES: tuple[str, ...] = (
    "tests/test_recall.py",
    "tests/test_recall_calibration.py",
    "tests/test_recall_eval.py",
    "tests/test_recall_pasted_counts.py",
)

#: The files the pull-recall corpus reads (``_iter_corpus`` in
#: tools/cc/hooks/_recall.py): every ``.md`` under the two directory roots, the
#: two catalogs, the principles and their aliases sidecar. Pinned both ways
#: against the live corpus in tests/test_proof_tier.py -- every indexed file
#: satisfies the predicate, every listed file is read. Over-inclusive on purpose
#: where the loader skips by NAME (a README, the notes it excludes): the slice
#: is cheap and a predicate that re-derived the loader's skips would be a copy.
# `.claude/rules/` is a corpus root the loader reads wherever it exists; this
# tree has none, and the twin tests below keep the list exact in both
# directions, so it joins the moment a rules directory appears here.
_RECALL_CORPUS_PREFIXES: tuple[str, ...] = ("memory/", "docs/sharp-edges/")
_RECALL_CORPUS_FILES: tuple[str, ...] = (
    "CLAUDE.md",  # the default roster's root file (indexed per section since 2026-10-08)
    "docs/SHARP_EDGES.md",
    "docs/STANDING_PRINCIPLES.md",
    "docs/STANDING_PRINCIPLES.aliases.md",
    "docs/FAILURE_MODES.md",
)

#: argv per command, per tier -- tuples of tokens, not strings. ``--run``
#: executes these tokens and the printed lines are ``shlex.join`` of the same
#: tokens, so the receipt and the execution cannot drift apart. A dict, so a
#: tier nobody wired raises instead of falling through to the cheaper one.
_PYTEST: tuple[str, ...] = ("pytest", "-q")
_CONTRACT_ARGV: tuple[str, ...] = ("pytest", "-m", "contract", "-q")
#: The heavy end-to-end stages (tests/conftest.py::_HEAVY_E2E_TESTS) leave the
#: per-pull-request tier: the stage-one smoke alone ran 848 s on one xdist
#: worker of a 992 s parallel leg (a CI cell, 2026-09-30), and one member lives
#: in a serial-leg file, so BOTH pytest lines of the full tier carry this
#: filter. The stages keep one CI home (the floor-version clean-checkout cell)
#: and one local home (the fresh-clone gate's first resolved leg); both pass
#: ``--heavy``, which drops the filter from every line. The cheaper tiers'
#: own-tests line carries it too: a changed heavy module rides along there, and
#: without the filter it would run the smoke in five required cells (both
#: reviews, 2026-09-30).
_NOT_HEAVY: tuple[str, ...] = ("-m", "not heavy_e2e")
#: The lint line every tier carries. The HIGH-severity rule set is pinned in
#: ``pyproject.toml [tool.ruff.lint]``; CI's ruff-lint cell runs the same
#: command, but that cell is not in the required set, so without this line a
#: lint red reaches the pull request past a green local tier (2026-10-01).
_RUFF_ARGV: tuple[str, ...] = ("ruff", "check", ".")
_TIER_ARGVS: dict[str, tuple[tuple[str, ...], ...]] = {
    "full": (
        ("mypy", "tools/cc/hooks/"),
        _RUFF_ARGV,
        _PYTEST + ("-n", "auto") + _NOT_HEAVY + tuple(f"--ignore={rel}" for rel in SERIAL_FILES),
        _PYTEST + _NOT_HEAVY + SERIAL_FILES,
    ),
    "recall": (_RUFF_ARGV, _CONTRACT_ARGV, _PYTEST + RECALL_SLICE_FILES),
    "contract": (_RUFF_ARGV, _CONTRACT_ARGV),
}
TIERS: tuple[str, ...] = tuple(_TIER_ARGVS)
FULL_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["full"])
RECALL_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["recall"])
CONTRACT_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["contract"])
INSTALL_HINT = "needs pytest-xdist, mypy and ruff (the `dev` extra: pip install -e '.[dev]')"
#: The legs ``--leg`` can run. ``serial`` is the ``SERIAL_FILES`` line where a
#: tier has one (only the full tier does); ``parallel`` is every other line, by
#: complement, so a cheaper tier's required cells run their whole tier under
#: ``parallel`` and nothing under ``serial``; ``both`` is the tier.
LEGS: tuple[str, ...] = ("parallel", "serial", "both")


def _is_serial_line(argv: tuple[str, ...]) -> bool:
    """The full tier's serial line: the one that ends with ``SERIAL_FILES``."""
    return len(argv) > len(SERIAL_FILES) and argv[-len(SERIAL_FILES):] == SERIAL_FILES


def _without_heavy_filter(argv: tuple[str, ...]) -> tuple[str, ...]:
    """``argv`` with its ``_NOT_HEAVY`` pair removed, when it carries one."""
    for i in range(len(argv) - 1):
        if argv[i:i + 2] == _NOT_HEAVY:
            return argv[:i] + argv[i + 2:]
    return argv
#: The runners a proof command may lead with. `run_commands` dispatches on the
#: head with one literal call per runner, so the receipt line (shlex.join of the
#: argv) and the spawned binary are the same token by construction -- a widened
#: allowlist over a hard-coded ["pytest"] would print one and run the other.
#: ``version_lines`` reads each runner's version the same way, and both refuse
#: a runner with no branch of its own. tests/test_external_tool_contract.py
#: holds this roster closed: a new runner is pinned in the dev extra or named
#: there as ranged with its reason.
_RUNNERS: tuple[str, ...] = ("mypy", "ruff", "pytest")


def own_tests(changed, root: Path = _ROOT) -> tuple[str, ...]:
    """``tests/test_<stem>.py`` for every changed ``scripts/<stem>.py`` that has
    one, and every changed ``tests/test_*.py`` itself (a test-only diff earned
    a tier that never ran the test it changed -- failure-mode review,
    2026-09-25) -- derived from the diff, never enumerated. The contract slice is the
    tree-wide truth tests, and a self-host script's own tests are classified
    ``integration`` (they drive the script by path against a scratch tree), so
    a ``scripts/`` diff earned a tier that ran none of the tests written for
    it: on 2026-09-20 the row tool's red-first rows were invisible to the
    receipt the proof-order bodies tell the operator to paste (failure-mode
    pass; DEF-775's shape, one directory over). The full tier already runs
    them, so the line rides along with the two cheaper tiers only."""
    out: list[str] = []
    for rel in changed:
        rel = rel.replace("\\", "/")
        if rel.startswith("scripts/") and rel.endswith(".py") and rel.count("/") == 1:
            test_rel = f"tests/test_{rel[len('scripts/'):]}"
            if (root / test_rel).is_file() and test_rel not in out:
                out.append(test_rel)
        if rel.startswith("tests/test_") and rel.endswith(".py") and rel.count("/") == 1:
            if (root / rel).is_file() and rel not in out:
                out.append(rel)
    return tuple(out)


def tier_argvs(which: str, changed=(), root: Path = _ROOT, *, heavy: bool = False,
               leg: str = "both") -> tuple[tuple[str, ...], ...]:
    """The argv list a tier runs for THIS diff: the tier's own commands, then
    one line for the changed scripts' own test files on the two cheaper tiers.
    ``KeyError`` on a tier nobody wired -- never a silent fall-through to the
    cheaper tier. ``heavy`` puts the heavy end-to-end stages back on both lines
    (the clean-checkout cell and the gate's first leg); ``leg`` selects by
    complement (see ``LEGS``), so the default form is always the whole tier and
    ``FULL_COMMANDS`` stays the four lines the receipts count."""
    argvs = _TIER_ARGVS[which]
    own = () if which == "full" else own_tests(changed, root)
    lines = argvs + ((_PYTEST + _NOT_HEAVY + own,) if own else ())
    if heavy:
        lines = tuple(_without_heavy_filter(argv) for argv in lines)
    if leg == "serial":
        lines = tuple(argv for argv in lines if _is_serial_line(argv))
    elif leg == "parallel":
        lines = tuple(argv for argv in lines if not _is_serial_line(argv))
    elif leg != "both":
        raise ValueError(f"leg must be one of {LEGS}, got {leg!r}")
    return lines


def commands(which: str, changed=(), root: Path = _ROOT, *, heavy: bool = False,
             leg: str = "both") -> tuple[str, ...]:
    """The command line(s) a tier runs for this diff, in order (``tier_argvs``
    rendered with ``shlex.join``, so the receipt and the execution cannot drift)."""
    return tuple(shlex.join(argv) for argv in tier_argvs(which, changed, root, heavy=heavy, leg=leg))


#: The flag each runner answers with its version. The receipt prints one
#: ``version:`` line per runner before the commands, read from the binary the
#: command spawns, because the dev extra pins the finding gates to one exact
#: version (tests/test_external_tool_contract.py) and a local ruff or mypy off
#: that pin lints differently from CI: a red there read as an ordinary
#: finding while the local tier stayed green (DEF-4014).
_VERSION_FLAG = "--version"


def dev_extra_pins(root: Path) -> dict[str, str]:
    """``{name: version}`` for each exact ``name==version`` spec in the dev
    extra. Empty when ``pyproject.toml`` cannot be read or no TOML reader is
    importable (3.10 without ``tomli``): the receipt then prints the versions
    and skips the comparison, never the run."""
    try:
        import tomllib
    except ImportError:  # Python 3.10: the base dependencies install tomli there
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return {}
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # TOMLDecodeError is a ValueError
        return {}
    pins: dict[str, str] = {}
    for spec in data.get("project", {}).get("optional-dependencies", {}).get("dev", []):
        name, sep, version = str(spec).replace(" ", "").partition("==")
        if sep and version and not any(c in version for c in ",;<>=!~"):
            pins[name.lower()] = version
    return pins


def version_lines(argvs, root: Path) -> list[str]:
    """One ``version:`` line per distinct runner, in first-use order, each read
    by the same literal call per runner that ``run_commands`` dispatches, so
    the version and the binary that runs are one token. A runner whose version
    is not the dev extra's exact pin is named with the reinstall line; the
    line is a diagnosis and never changes the verdict."""
    pins = dev_extra_pins(root)
    lines: list[str] = []
    for head in dict.fromkeys(argv[0] for argv in argvs):
        try:
            if head == "mypy":
                done = subprocess.run(["mypy", _VERSION_FLAG], cwd=root, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace")
            elif head == "ruff":
                done = subprocess.run(["ruff", _VERSION_FLAG], cwd=root, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace")
            elif head == "pytest":
                done = subprocess.run(["pytest", _VERSION_FLAG], cwd=root, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace")
            else:
                raise ValueError(f"no version read for runner {head!r}: give it its own branch here")
        except FileNotFoundError:
            lines.append(f"version: {head} not installed")
            continue
        said = (done.stdout or done.stderr or "").strip().splitlines()
        first = said[0].strip() if said else f"{head} printed no version (exit {done.returncode})"
        line = f"version: {first}"
        pinned = pins.get(head)
        if pinned and pinned not in first.split():
            # The tool alone, at the pin: `pip install -e '.[dev]'` would also
            # re-point the interpreter's espalier at the checkout it runs in.
            line += f" -- the dev extra pins {head}=={pinned}, which CI runs: python -m pip install {head}=={pinned}"
        lines.append(line)
    return lines


def run_commands(argvs, root: Path) -> int:
    """Run every command in order, one receipt line each, return the worst exit.

    Every command runs even after a failure, so the receipt always names all
    of them; the summary line says how many ran. Each argv leads with one of
    ``_RUNNERS`` (OS binaries the subprocess-contract scanner skips), and the
    dispatch below is one literal call per runner. A runner that is not
    installed is exit 127 with the install hint, never a silently skipped
    line. Each runner's version prints first (``version_lines``)."""
    worst = 0
    for argv in argvs:
        if argv[0] not in _RUNNERS:
            raise ValueError(f"proof commands lead with one of {_RUNNERS}, got {argv[0]!r}")
    if not argvs:
        # Emptiness-keyed, whatever leg or tier produced it: a receipt that
        # counts zero of zero is a reportable green that proves nothing, and
        # the sentence says so beside it (failure-mode review, 2026-09-30).
        print("no commands on this run -- the receipt below proves nothing", flush=True)
    for line in version_lines(argvs, root):
        print(line, flush=True)
    for argv in argvs:
        head, *rest = argv
        try:
            if head == "mypy":
                rc = subprocess.run(["mypy"] + rest, cwd=root).returncode
            elif head == "ruff":
                rc = subprocess.run(["ruff"] + rest, cwd=root).returncode
            elif head == "pytest":
                rc = subprocess.run(["pytest"] + rest, cwd=root).returncode
            else:
                raise ValueError(f"no dispatch for runner {head!r}: give it its own branch here")
        except FileNotFoundError:
            rc = 127
            print(f"{head}: not installed -- {INSTALL_HINT}", flush=True)
        print(f"exit {rc}: {shlex.join(argv)}", flush=True)
        worst = max(worst, rc)
    verdict = "PASS" if worst == 0 else f"FAIL (worst exit {worst})"
    print(f"proof: {verdict} -- {len(argvs)} of {len(argvs)} command(s) ran", flush=True)
    return worst


def changed_paths(root: Path) -> tuple[list[str], list[str]]:
    """``(changed, untracked)`` repo-relative paths: everything modified, staged
    or intent-added versus HEAD, and the ``??`` files git does not track."""
    porcelain = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    changed: list[str] = []
    untracked: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if code == "??":
            untracked.append(path)
        else:
            changed.append(path)
    return changed, untracked


def unstaged_deletions(root: Path) -> list[str]:
    """Tracked paths deleted from the worktree with the deletion NOT staged
    (porcelain `` D``): still index rows, so every ``git ls-files`` gate counts
    a file that is not there. The refusal twin of the untracked list."""
    porcelain = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    return [line[3:] for line in porcelain.splitlines() if line[:2] == " D"]


class BaseUnresolvable(Exception):
    """``--base`` names a ref git cannot relate to HEAD here."""


def changed_since(root: Path, base: str) -> list[str]:
    """Repo-relative paths that differ between ``HEAD`` and its merge-base with
    ``base``. On a pull request's own run HEAD is the merge ref (base tip plus
    the branch), so the merge-base is the base tip and the diff is exactly the
    branch's changes; on a local branch behind a base that moved on, the
    merge-base keeps the base's later commits off this branch's bill. Renames
    are read as a deletion plus an addition, so a hook moved out of
    ``tools/cc/`` still counts as a runtime change; an untracked file does not
    exist to a CI checkout and is not consulted."""
    # Literal argv lists on purpose: the subprocess-contract scanner resolves a
    # literal (and skips the git binary) but reads a concatenated list as
    # <dynamic> and refuses it.
    try:
        mb = subprocess.run(
            ["git", "-C", str(root), "merge-base", base, "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "--no-renames", mb, "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BaseUnresolvable(f"cannot diff HEAD against {base!r}: {detail.strip()}") from exc
    return [line for line in diff.splitlines() if line]


def is_runtime(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel.startswith(_FULL_PREFIXES):
        return True
    if rel.startswith(_ENGINE_PREFIX) and not rel.startswith(_ENGINE_MIRROR_PREFIXES):
        return rel.endswith(".py")
    return False


def is_ci_definition(rel: str) -> bool:
    return rel.replace("\\", "/").startswith(_CI_DEFINITION_PREFIXES)


def is_suite_config(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return rel in _SUITE_CONFIG_FILES or (rel.startswith("tests/_") and rel.endswith(".py"))


def is_recall_corpus(rel: str) -> bool:
    """A file the pull-recall corpus reads. Markdown only under the directory
    roots (a stray non-``.md`` under memory/ is not indexed); exact paths for
    the single-file sources."""
    rel = rel.replace("\\", "/")
    if rel.startswith(_RECALL_CORPUS_PREFIXES):
        return rel.endswith(".md")
    return rel in _RECALL_CORPUS_FILES


def tier(changed: list[str], *, workflows_are_runtime: bool = False) -> str:
    """``full`` when any path is the shipped runtime or the suite's own
    configuration (or, with ``workflows_are_runtime``, the CI definition --
    ``--base`` mode, a pull request's own run), else ``recall`` when any path
    is a recall-corpus file, else ``contract``. Ordered: a diff that touches
    both a hook and a memory note earns the whole suite, which already
    contains the recall slice."""
    if any(is_runtime(p) or is_suite_config(p) for p in changed):
        return "full"
    if workflows_are_runtime and any(is_ci_definition(p) for p in changed):
        return "full"
    if any(is_recall_corpus(p) for p in changed):
        return "recall"
    return "contract"


def is_review_surface(rel: str) -> bool:
    """A path on step 6's review surface: the shipped runtime (``tools/cc/``
    and the engine's own ``.py``, the byte mirrors left out) or a
    ``_REVIEW_PREFIXES`` root."""
    rel = rel.replace("\\", "/")
    return is_runtime(rel) or rel.startswith(_REVIEW_PREFIXES)


def _shell_words(script: str) -> list[str]:
    """The unquoted words of a ``run:`` script. A word holding a quoted string
    is dropped whole, and so is a comment (a path inside either is not a
    call); a backslash escapes the next character and drops a line break; a
    word ends at whitespace or a shell operator. An assignment word
    (``NAME=value``) stays one word, so an env value is never read as a path.
    A character scanner, not a regex: nothing here can backtrack."""
    words: list[str] = []
    cur: list[str] = []
    tainted = False
    i, n = 0, len(script)
    while i < n:
        c = script[i]
        if c == "\\":
            if i + 1 < n and script[i + 1] != "\n":
                cur.append(script[i + 1])
            i += 2
            continue
        if c in "'\"":
            close = script.find(c, i + 1)
            while c == '"' and close > 0 and script[close - 1] == "\\":
                close = script.find(c, close + 1)
            i = n if close < 0 else close + 1
            tainted = True
            continue
        if c == "#" and not cur and not tainted:
            newline = script.find("\n", i)
            i = n if newline < 0 else newline
            continue
        if c.isspace() or c in _SHELL_OPERATORS:
            if cur and not tainted:
                words.append("".join(cur))
            cur, tainted = [], False
            i += 1
            continue
        cur.append(c)
        i += 1
    if cur and not tainted:
        words.append("".join(cur))
    return words


def _scalar(value: str) -> str:
    """One inline YAML value: a pair of enclosing quotes removed, or a plain
    value's trailing `` #`` comment."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def _run_and_uses(text: str) -> tuple[list[str], list[str]]:
    """The ``run:`` scripts and the ``uses:`` values of one workflow or action
    file, read by line and indentation (stdlib only: the CI tier job runs this
    script before anything is installed). A block scalar (``key: |`` or
    ``key: >``) is every following line indented past its key, blank lines
    included, and is skipped whole unless the key is ``run``, so a line inside
    another key's block is never read as a key. Every other value -- an
    ``env:`` entry, a ``with:`` input, a comment -- is not a call."""
    runs: list[str] = []
    uses: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        body = line.lstrip(" ")
        col = len(line) - len(body)
        if body.startswith("- "):
            rest = body[2:].lstrip(" ")
            col += len(body) - len(rest)
            body = rest
        key, sep, value = body.partition(":")
        if not sep or key.startswith("#"):
            continue
        value = value.strip()
        if value[:1] in ("|", ">"):
            block: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= col:
                    break
                block.append(nxt)
                i += 1
            if key == "run":
                runs.append("\n".join(block))
        elif key == "run":
            runs.append(_scalar(value))
        elif key == "uses":
            uses.append(_scalar(value))
    return runs, uses


def _head_files(root: Path, at_head: bool) -> tuple[set[str] | None, Callable[[str], str | None]]:
    """``(files, read)`` at the diff's head: with ``at_head`` (``--base``), the
    files of ``HEAD``'s tree and a reader of their blobs; otherwise ``None``
    (ask the disk) and a reader of the working tree. Raises
    ``BaseUnresolvable`` when git cannot list ``HEAD``."""
    if not at_head:
        def read_disk(rel: str) -> str | None:
            path = root / rel
            return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
        return None, read_disk
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-r", "-z", "--name-only", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BaseUnresolvable(f"cannot list HEAD's files: {detail.strip()}") from exc
    files = {p for p in listing.split("\0") if p}

    def read_blob(rel: str) -> str | None:
        if rel not in files:
            return None
        out = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{rel}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return out.stdout if out.returncode == 0 else None
    return files, read_blob


def workflow_named_files(root: Path = _ROOT, *, at_head: bool = False) -> dict[str, str]:
    """Every repo file a workflow at the diff's head calls, mapped to the file
    that names it: a word of a ``run:`` script that is a file there, and a
    local action or reusable workflow (``uses: ./...``), whose own ``run:``
    steps are read in turn. The head is the working tree, or ``HEAD``'s tree
    with ``at_head`` (``--base``: a pull request's own run). A path a workflow
    names that is not a file at the head does not join; a remote ``uses:``
    is not a repo file."""
    files, read = _head_files(root, at_head)

    def is_file(rel: str) -> bool:
        if not rel or rel.startswith(("/", "../")) or ":" in rel or "/../" in rel:
            return False
        return rel in files if files is not None else (root / rel).is_file()

    if files is not None:
        sources = sorted(p for p in files if p.startswith(".github/workflows/")
                         and p.endswith((".yml", ".yaml")) and p.count("/") == 2)
    else:
        found = (root / ".github" / "workflows").glob("*.y*ml")
        sources = sorted(f".github/workflows/{p.name}" for p in found
                         if p.is_file() and p.suffix in (".yml", ".yaml"))
    named: dict[str, str] = {}
    seen = set(sources)
    queue = list(sources)
    while queue:
        src = queue.pop(0)
        text = read(src)
        if text is None:
            continue
        runs, uses = _run_and_uses(text)
        for script in runs:
            for word in _shell_words(script):
                rel = word[2:] if word.startswith("./") else word
                if is_file(rel):
                    named.setdefault(rel, src)
        for value in uses:
            if not value.startswith("./"):
                continue
            target = value[2:].rstrip("/")
            if target.endswith((".yml", ".yaml")):
                candidates: tuple[str, ...] = (target,)
            else:
                candidates = (f"{target}/action.yml", f"{target}/action.yaml")
            for cand in candidates:
                if is_file(cand):
                    named.setdefault(cand, src)
                    if cand not in seen:
                        seen.add(cand)
                        queue.append(cand)
    return named


def review(changed: Iterable[str], root: Path = _ROOT, *, at_head: bool = False) -> tuple[str, list[tuple[str, str]]]:
    """``(verdict, earned_by)``: the reviewers the diff's surface earns, one of
    ``REVIEWS``, and each path that earned the verdict with why. A hook, a
    body or a gate earns ``both``; else a path on the review surface earns
    ``code-reviewer``; else ``none``. The workflows are read only when a path
    is left that no prefix decides."""
    both: list[tuple[str, str]] = []
    surface: list[tuple[str, str]] = []
    named: dict[str, str] | None = None
    for rel in sorted({p.replace("\\", "/") for p in changed}):
        if rel.startswith(_HOOK_PREFIX):
            both.append((rel, "a hook"))
        elif rel.startswith(_BODY_PREFIXES):
            both.append((rel, "a command, agent, skill or workflow body"))
        elif is_ci_definition(rel):
            both.append((rel, "the CI definition"))
        elif rel.startswith(_BENCH_PREFIX):
            both.append((rel, "the release bench"))
        else:
            if named is None:
                named = workflow_named_files(root, at_head=at_head)
            if rel in named:
                both.append((rel, f"a gate: {named[rel]} runs it"))
            elif is_review_surface(rel):
                surface.append((rel, "on the review surface"))
    if both:
        return "both", both
    if surface:
        return "code-reviewer", surface
    return "none", []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tier", choices=("auto", *TIERS), default="auto",
                    help="force a tier (the handoff's preflight forces full); auto = what the diff earns")
    ap.add_argument("--run", action="store_true",
                    help="run the tier's command(s) in order and exit with the worst code")
    ap.add_argument("--base", metavar="REF",
                    help="classify the diff between HEAD and its merge-base with REF (a pull "
                         "request's own diff) instead of the working tree; exit 3 if REF "
                         "cannot be related to HEAD")
    ap.add_argument("--quiet", action="store_true",
                    help="print the tier word alone (for `$(...)` in a workflow step)")
    ap.add_argument("--heavy", action="store_true",
                    help="put the heavy end-to-end stages back on both pytest lines (the "
                         "clean-checkout cell and the fresh-clone gate's first leg run this form)")
    ap.add_argument("--leg", choices=LEGS, default="both",
                    help="run one leg of the tier: serial is the SERIAL_FILES line where one "
                         "exists, parallel is every other line; both (the default) is the tier")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.base:
        try:
            changed = changed_since(root, args.base)
        except BaseUnresolvable as exc:
            if args.tier == "auto":
                print(f"proof_tier: {exc}", file=sys.stderr)
                return 3
            # A forced tier does not need the diff to know what to run; the
            # diff only adds the changed test files. Warn and run the tier over
            # an empty diff rather than red five required cells with zero tests
            # run (code review, 2026-09-25).
            print(f"proof_tier: {exc}; running the forced {args.tier} tier over an empty diff",
                  file=sys.stderr)
            changed = []
        untracked = []
        deleted = []
    else:
        changed, untracked = changed_paths(root)
        deleted = unstaged_deletions(root)
    earned = tier(changed + untracked, workflows_are_runtime=bool(args.base))
    which = earned if args.tier == "auto" else args.tier
    verdict = ""
    earned_by: list[tuple[str, str]] = []
    if not args.quiet:
        # Not on --quiet: the CI tier job reads that one word and never pays for
        # the workflow read. Unreadable workflows read as both reviewers, never fewer.
        try:
            verdict, earned_by = review(changed + untracked, root, at_head=bool(args.base))
        except BaseUnresolvable as exc:
            print(f"proof_tier: {exc}; the review reads both", file=sys.stderr)
            verdict, earned_by = "both", [("(the workflows)", "unread at the head")]
    result = {
        "tier": which,
        "earned_tier": earned,
        "base": args.base,
        "runtime_paths": sorted(p for p in changed + untracked if is_runtime(p)),
        "ci_definition_paths": sorted(p for p in changed + untracked if is_ci_definition(p)),
        "suite_config_paths": sorted(p for p in changed + untracked if is_suite_config(p)),
        "corpus_paths": sorted(p for p in changed + untracked if is_recall_corpus(p)),
        "untracked": untracked,
        "review": verdict,
        "review_earned_by": [{"path": rel, "why": why} for rel, why in earned_by],
        "heavy": args.heavy,
        "leg": args.leg,
        "commands": list(commands(which, changed + untracked, root, heavy=args.heavy, leg=args.leg)),
    }
    if args.quiet:
        print(which)
        if untracked:
            print("untracked -- invisible to the git ls-files gates until staged:", file=sys.stderr)
            for p in untracked:
                print(f"  git add -N {p}", file=sys.stderr)
        if deleted:
            print("deleted but not staged -- the git ls-files gates still count the file:", file=sys.stderr)
            for p in deleted:
                print(f"  git add -u {p}", file=sys.stderr)
    elif args.json:
        print(json.dumps(result, indent=2))
    else:
        print(which + ("" if which == earned else f" (forced; the diff earned {earned})"))
        if result["runtime_paths"]:
            print("runtime changed: " + ", ".join(result["runtime_paths"]))
        if result["ci_definition_paths"]:
            print("workflow changed: " + ", ".join(result["ci_definition_paths"]))
        if result["suite_config_paths"]:
            print("suite config changed: " + ", ".join(result["suite_config_paths"]))
        if result["corpus_paths"]:
            print("recall corpus changed: " + ", ".join(result["corpus_paths"]))
        if earned_by:
            print(f"review: {verdict} -- " + ", ".join(f"{rel} ({why})" for rel, why in earned_by))
        else:
            print("review: none -- no changed path is on the review surface")
        for line in result["commands"]:
            print("run: " + line)
        if len(result["commands"]) > 1:
            # The recall tier's first two lines are byte-identical to the
            # contract tier's two, so a session that pastes a subset gets a
            # green indistinguishable from the tier it was meant to replace.
            if args.leg == "both":
                what = "the tier"
            elif args.leg == "parallel" and which != "full":
                what = "the whole tier (its parallel leg; this tier has no serial line)"
            else:
                what = f"the {args.leg} leg of the tier"
            print(f"all {len(result['commands'])} lines are {what} -- `--run` executes them under one receipt")
        if not result["commands"]:
            print(f"nothing to run: the {args.leg} leg of the {which} tier has no commands "
                  "(the serial files belong to the full tier)")
        if which == "full":
            print(INSTALL_HINT)
        if untracked:
            print("untracked -- invisible to the git ls-files gates until staged:")
            for p in untracked:
                print(f"  git add -N {p}")
        if deleted:
            print("deleted but not staged -- the git ls-files gates still count the file:")
            for p in deleted:
                print(f"  git add -u {p}")
    if untracked or deleted:
        return 2
    if args.run:
        argvs = tier_argvs(which, changed + untracked, root, heavy=args.heavy, leg=args.leg)
        if not argvs:
            # A required cell must report on every pull request: say, in words,
            # which leg of which tier has nothing to run, then let the receipt
            # count zero of zero rather than exit silently.
            print(f"nothing to run: the {args.leg} leg of the {which} tier has no commands "
                  "(the serial files belong to the full tier)", flush=True)
        rc = run_commands(argvs, root)
        if which != earned:
            # The forced-tier note printed at the top is four lines above the
            # receipt's summary; repeat it beside the verdict so a downgrade
            # (`--tier contract` on a runtime diff) cannot read as the earned run.
            print(f"forced: ran the {which} tier; the diff earned {earned}", flush=True)
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
