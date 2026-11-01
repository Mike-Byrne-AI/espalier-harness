#!/usr/bin/env python3
"""Which proof tier does this working tree earn -- and is every new file visible?

The proof-order bodies (`/implement-task` step 7, `/preflight` Step 2,
`/implement-pack` step 6) state one rule: a change that touched no engine code
and no hook runs the tree-wide contracts (`pytest -n auto -m contract -q`); a change
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
those five at one xdist worker (``-n 1`` since DEF-2017: on a thread-method
host a ceiling crossing then names its test). The pytest pair is
the local default since 2026-09-06, after the two clean full runs
``tests/README.md`` pre-registered as the count the flip needed (6:31 and 6:12
on the 8 GB self-host box, against 18:41-19:52 serial -- the 2026-09-06 figures;
by 2026-09-23 the tier's floor was the stage-one smoke's nested serial not-slow
child, about twelve minutes on its own, so a full tier reads longer than either:
DEF-919). The contract slice's
own parallel form raced on the live tree the same day, and the slice stayed
serial until 2026-10-16 (DEF-2017). Its races were the
``reports/.cc_surface_gate.json`` temp file a suite gate run wrote into the live
checkout, closed at its writer on 2026-10-14 (DEF-973), and the staged release
tree, closed on 2026-10-06 (DEF-1138); its tests had run under ``-n auto``
inside the full tier's parallel leg in every cell since the CI flip; so the
contract and recall lines run at ``-n auto`` too, and a recurrence goes to the
races line in ``tests/README.md``. A parallel full run that errors on a live-tree race is a loud error,
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
diff's head calls (its ``run:`` steps and local ``uses:``), a hook is also
every ``tools/cc/`` module a hook loads, and ``espalier.toml`` and
``pyproject.toml`` (configuration a hook or a gate reads) earn both too; each
set is read from the head at classification time and never kept by hand, and
a mirror-registry source earns what its mirrors earn. What cannot be read --
the head, an unresolved ``--base`` -- reads both, never fewer. ``--quiet``
prints the tier word alone and never reads any of it.

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
import ast
import fnmatch
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import AbstractSet, Callable, Iterable, NamedTuple

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
#: The harness's own configuration that a hook or a gate reads: plan_guard's
#: exemptions, write_guard's zones and the dispatcher (``espalier.toml``); the
#: hook type gate's mypy overrides and the ruff set CI blocks on
#: (``pyproject.toml``). Both reviewers (air, 2026-10-16); the suite's shared
#: test code (``is_suite_config``'s other members) earns the code reviewer.
_CONFIG_BOTH_FILES: tuple[str, ...] = ("espalier.toml", "pyproject.toml")
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
    # The seeded reference docs (`_recall.REFERENCE_DOCS`) index only on an
    # adopter's tree, so the forward pin below cannot see them here; their rows in
    # tests/test_recall.py read the shipped copies, which an edit to either moves.
    "docs/HOOKS.md",
    "docs/TROUBLESHOOTING.md",
    "espalier/assets/docs/HOOKS.md",
    "espalier/assets/docs/TROUBLESHOOTING.md",
)

#: argv per command, per tier -- tuples of tokens, not strings. ``--run``
#: executes these tokens and the printed lines are ``shlex.join`` of the same
#: tokens, so the receipt and the execution cannot drift apart. A dict, so a
#: tier nobody wired raises instead of falling through to the cheaper one.
_PYTEST: tuple[str, ...] = ("pytest", "-q")
#: Every pytest line a tier runs is under xdist (DEF-2017, after DEF-979's
#: portability cell): where pytest-timeout uses its thread method (Windows, a
#: seat's own box) a test that crosses the per-test ceiling then fails by name
#: and its worker is replaced, where one session would end with no summary and
#: no test named. That holds up to xdist's restart cap, four per worker by
#: default: past it the run stops scheduling, and ``-q`` hides xdist's line
#: saying so (failure-mode review, 2026-10-16), so the suite's own summary
#: counts the tests that never ran (``tests/_never_ran.py``, DEF-2020). The
#: serial files keep one worker (their placement was measured: wall-clock
#: budgets and timeout-near gates, kept off parallel load); every other line
#: runs at ``-n auto``.
_PARALLEL: tuple[str, ...] = ("-n", "auto")
_ONE_WORKER: tuple[str, ...] = ("-n", "1")
_CONTRACT_ARGV: tuple[str, ...] = ("pytest", "-n", "auto", "-m", "contract", "-q")
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
        _PYTEST + _PARALLEL + _NOT_HEAVY + tuple(f"--ignore={rel}" for rel in SERIAL_FILES),
        _PYTEST + _ONE_WORKER + _NOT_HEAVY + SERIAL_FILES,
    ),
    "recall": (_RUFF_ARGV, _CONTRACT_ARGV, _PYTEST + _PARALLEL + RECALL_SLICE_FILES),
    "contract": (_RUFF_ARGV, _CONTRACT_ARGV),
}
TIERS: tuple[str, ...] = tuple(_TIER_ARGVS)
FULL_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["full"])
RECALL_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["recall"])
CONTRACT_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["contract"])
INSTALL_HINT = "needs pytest-xdist, mypy and ruff (the `dev` extra: pip install -e '.[dev]')"
#: Why a leg can be empty: only the full tier has a serial leg (``LEGS``); a
#: cheaper tier runs a changed serial file on its own-tests line at one
#: worker, inside its parallel leg (``tier_argvs``).
_EMPTY_LEG_WHY = ("only the full tier has a serial leg; a cheaper tier runs a changed serial "
                  "file in its parallel leg, at one worker")
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


#: The tests written for the shipped agent, command and skill bodies, and the
#: bodies they read, as ``(kind, glob)`` under each root. A body is not a
#: script, so its tests cannot be derived from its name, and this file is
#: integration-classified: a diff that edits only a body earned the contract
#: tier, whose ``-m contract`` deselected every row of it, so the first-contact
#: diagnostics could regress with every pull-request cell green (DEF-4067).
#: The kinds are the file's own walk (its ``BODY_KINDS``); the roots are this
#: checkout's bodies and the deploy source ``espalier init`` copies into the
#: adopter tree the file builds. Hand-kept like ``SERIAL_FILES``; pinned to the
#: file's walk in tests/test_proof_tier.py.
BODY_TEST_FILES: tuple[str, ...] = ("tests/test_first_contact_diagnostics.py",)
BODY_KINDS: tuple[tuple[str, str], ...] = (("agents", "*.md"), ("commands", "*.md"), ("skills", "*/SKILL.md"))
BODY_ROOTS: tuple[str, ...] = (".claude/", "espalier/assets/claude/")


def is_body(rel: str) -> bool:
    """A shipped agent, command or skill body: under a ``BODY_ROOTS`` root, one
    of ``BODY_KINDS`` matched segment by segment (a glob's ``*`` never crosses
    a ``/``, so a nested agent or a skill's other file is not one)."""
    rel = rel.replace("\\", "/")
    for root in BODY_ROOTS:
        if not rel.startswith(root):
            continue
        parts = rel[len(root):].split("/")
        if not all(parts):
            continue
        for kind, pattern in BODY_KINDS:
            want = [kind, *pattern.split("/")]
            if len(parts) == len(want) and all(fnmatch.fnmatchcase(p, w) for p, w in zip(parts, want)):
                return True
    return False


#: The type names a ``/`` join can start from with a literal (``Path(".claude")
#: / "commands"``): the one-argument call reads as its argument.
_PATH_TYPES: frozenset[str] = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"})
#: A string longer than this, or on more than one line, is prose, never a path.
_NAME_MAX = 255
#: The ``os.path`` spellings whose ``join`` builds a path from its arguments.
_PATH_MODULES: frozenset[str] = frozenset({"os.path", "path", "posixpath", "ntpath"})
#: The ``Path`` methods that write, move or remove the path they are called
#: on: a join that is their receiver names a file the test puts into a tree,
#: and the text this checkout holds under that name is not read there
#: (DEF-5042). ``replace`` is left out: on an ``os.path.join`` it is
#: ``str.replace``, a separator swap before a read.
_WRITE_METHODS: frozenset[str] = frozenset({"write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir",
                                            "rename", "symlink_to", "hardlink_to", "chmod"})
#: The calls whose second positional argument is the path they write.
_COPY_CALLS: frozenset[str] = frozenset({"shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree",
                                         "shutil.move"})


class _Module(NamedTuple):
    """What one parsed test module or helper names (``_parsed``)."""
    names: frozenset[str]
    #: ``(module, name)`` for each ``from <...>.<module> import <name>``
    imports: frozenset[tuple[str, str]]
    #: each module-level ``NAME = <value>`` whose value names a path
    constants: dict[str, frozenset[str]]


#: ``(text, module)`` per file parsed, keyed by its path: the pins ask once per
#: body, and a file whose text is unchanged is not parsed again. Keyed on the
#: text, not the mtime: two writes inside one tick of a coarse filesystem clock
#: keep one mtime, and the second would read stale.
_NAMES_CACHE: dict[str, tuple[str, _Module]] = {}


def _norm_name(text: str) -> str:
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted_name(node.value)}.{node.attr}"
    return ""


def _call_join(node: ast.Call) -> str | None:
    """The string constants that end a path-building call's arguments:
    ``Path(ROOT, ".claude", "commands")``, ``root.joinpath(".claude", ...)``,
    ``os.path.join(ROOT, ".claude", ...)``; the operands before them drop, as
    in a ``/`` join."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    joins = name in _PATH_TYPES or name == "joinpath" or (
        name == "join" and isinstance(func, ast.Attribute) and _dotted_name(func.value) in _PATH_MODULES)
    if not joins or node.keywords:
        return None
    parts: list[str] = []
    for arg in reversed(node.args):
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            break
        parts.append(arg.value)
    return "/".join(reversed(parts)) if parts else None


def _literal(node: ast.AST) -> str | None:
    """A string constant, or a one-argument ``Path``-type call on one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name in _PATH_TYPES:
            return _literal(node.args[0])
    return None


def _is_join(node: ast.AST) -> bool:
    return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)) or (
        isinstance(node, ast.Call) and _call_join(node) is not None)


def _writes_mode(call: ast.Call, at: int) -> bool:
    """Whether an ``open`` call's mode, at position ``at`` or by keyword,
    writes without reading first (``w``, ``a`` or ``x``; ``r+`` reads)."""
    mode = call.args[at] if len(call.args) > at else next(
        (kw.value for kw in call.keywords if kw.arg == "mode"), None)
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax")


def _is_written(node: ast.AST, parent: dict[int, ast.AST]) -> bool:
    """Whether ``node`` is used as a path a write is made to: the receiver of
    one of ``_WRITE_METHODS`` (``.parent.mkdir`` included: the tree the write
    goes into), of ``.open`` in a mode that writes, the first argument of
    ``open`` in one, or the second of one of ``_COPY_CALLS``."""
    up = parent.get(id(node))
    if isinstance(up, ast.Attribute) and up.value is node:
        above = parent.get(id(up))
        if up.attr == "parent":
            return isinstance(above, ast.Attribute) and above.attr == "mkdir"
        if up.attr == "open":
            return isinstance(above, ast.Call) and above.func is up and _writes_mode(above, 0)
        return up.attr in _WRITE_METHODS
    if isinstance(up, ast.Call) and any(arg is node for arg in up.args):
        name = _dotted_name(up.func)
        if name in ("open", "io.open"):
            return up.args[0] is node and _writes_mode(up, 1)
        if name in _COPY_CALLS:
            return len(up.args) > 1 and up.args[1] is node
    return False


def _written_joins(tree: ast.AST) -> set[int]:
    """The ids of every node inside a join a module only writes to
    (``_is_written``): the join itself, or each join a function binds to a
    name by a plain assignment, every load of that name in the function a
    write. A name loaded any other way (read, passed on, returned), or shared
    with another function (``global``, ``nonlocal``), keeps its joins; so does
    a join on a scratch tree the test's own text reads back, since ``espalier
    init`` copies this checkout's files into the tree (DEF-5042). A read the
    code under test makes from that tree is spelled nowhere, so it is not
    seen either way (``path_readers``)."""
    parent = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    out: set[int] = set()
    for node in ast.walk(tree):
        if _is_join(node) and _is_written(node, parent):
            out.update(id(n) for n in ast.walk(node))
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        stores: dict[str, list[ast.Name]] = {}
        loads: dict[str, list[ast.Name]] = {}
        shared: set[str] = set()   # global or nonlocal: loaded in another function too
        for node in ast.walk(func):
            if isinstance(node, ast.Name):
                (loads if isinstance(node.ctx, ast.Load) else stores).setdefault(node.id, []).append(node)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                shared.update(node.names)
        for name, bound in stores.items():
            uses = loads.get(name)
            if name in shared or not uses or not all(_is_written(use, parent) for use in uses):
                continue
            for store in bound:
                assign = parent.get(id(store))
                if (isinstance(assign, ast.Assign) and len(assign.targets) == 1 and assign.targets[0] is store
                        and _is_join(assign.value)):
                    out.update(id(n) for n in ast.walk(assign.value))
    return out


def _module_names(tree: ast.AST) -> set[str]:
    """Every path a test module names: each one-line string constant, and the
    string constants that end each ``/`` join (``REPO_ROOT / ".claude" /
    "commands" / "inbox.md"`` names ``.claude/commands/inbox.md``; the operand
    before them is dropped, so a tree ``espalier init`` built names the
    deployed path, which is the source's own), outside the joins the module
    only writes to (``_written_joins``: a file a test puts into a tree it
    built is not one it reads)."""
    written = _written_joins(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in written:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, ast.Call):
            joined = _call_join(node)
            if joined:
                names.add(joined)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts: list[str] = []
            left: ast.AST = node
            while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
                right = _literal(left.right)
                if right is None:
                    break
                parts.append(right)
                left = left.left
            else:
                head = _literal(left) or (_call_join(left) if isinstance(left, ast.Call) else None)
                if head is not None:
                    parts.append(head)
            if parts:
                names.add("/".join(reversed(parts)))
    return {_norm_name(n) for n in names if n and "\n" not in n and len(n) <= _NAME_MAX}


def _read_module(path: Path) -> tuple[str, bytes] | None:
    """A file's text and bytes; a BOM is read past, as Python's import does."""
    try:
        data = path.read_bytes()
        return data.decode("utf-8-sig"), data
    except (OSError, UnicodeDecodeError):
        return None


def _parsed(path: Path, text: str, data: bytes) -> _Module:
    """``_module_names`` of one file, its ``from ... import`` names and its
    module-level path constants, parsed once per text (from the bytes, so a
    BOM parses). A file that does not parse names nothing: the suite's own
    collection reports it."""
    key = str(path)
    hit = _NAMES_CACHE.get(key)
    if hit is not None and hit[0] == text:
        return hit[1]
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError):
        module = _Module(frozenset(), frozenset(), {})
    else:
        imports = frozenset((node.module.rsplit(".", 1)[-1], alias.name) for node in ast.walk(tree)
                            if isinstance(node, ast.ImportFrom) and node.module for alias in node.names)
        constants: dict[str, frozenset[str]] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                targets, value = stmt.targets, stmt.value
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                targets, value = [stmt.target], stmt.value
            else:
                continue
            named = frozenset(_module_names(value))
            for target in targets:
                if isinstance(target, ast.Name) and named:
                    constants[target.id] = named
        module = _Module(frozenset(_module_names(tree)), imports, constants)
    _NAMES_CACHE[key] = (text, module)
    return module


def _names_path(names: AbstractSet[str], rel: str) -> bool:
    """``rel`` itself, or a suffix of it two segments or longer (a join from a
    directory variable: ``claude_dir / "commands" / "inbox.md"``); a bare file
    name matches only a top-level path."""
    if rel in names:
        return True
    parts = rel.split("/")
    return any("/".join(parts[i:]) in names for i in range(1, len(parts) - 1))


def path_readers(changed, root: Path = _ROOT) -> tuple[str, ...]:
    """Every top-level ``tests/test_*.py`` that names a changed path
    (``_module_names``), in the order the paths came. A body, a doc or a
    memory note is not a script, so its tests cannot be read from its name,
    and the files that read one are integration-classified: a diff that edited
    only such a file earned a cheaper tier, whose ``-m contract`` deselected
    every row of them, and their reds arrived on ``main`` (DEF-5040 for the
    bodies, DEF-5042 for the rest: tests/test_mail.py reads docs/WORKFLOW.md).
    Every changed path is looked up as it is, so the asset copy's own readers
    come with it. A file a test only writes into a tree it builds is not a
    read (``_written_joins``): that is what narrows ``README.md``, which half
    the suite puts into a scratch tree. Derived from the test files at each
    call, never kept. What this cannot read: a name built at run time (an
    f-string, a glob, a file name held in a variable), which for the bodies
    is the walk ``BODY_TEST_FILES`` keeps by hand; and a file the code under
    test reads (a check run on the repository root, ``git``, an ``init``-built
    tree the engine reads back), which no name in the test spells (DEF-5043).
    The contract slice's own doc-reader census
    (tests/test_marker_taxonomy.py::TestDocReadersRunInTheContractTier) is the
    other mechanism for the same reds, by test function rather than file. A
    path constant a module imports by name from a ``tests/_*.py`` helper
    counts as its own."""
    wanted: list[str] = []
    for rel in changed:
        rel = _norm_name(rel)
        if rel and rel not in wanted:
            wanted.append(rel)
    tests_dir = root / "tests"
    if not wanted or not tests_dir.is_dir():
        return ()
    # a literal or a join that names the path spells its file name: only a
    # module whose text holds one, or names a helper that does, is parsed
    bases = {rel.rsplit("/", 1)[-1] for rel in wanted}
    helpers: dict[str, dict[str, frozenset[str]]] = {}
    for path in sorted(tests_dir.glob("_*.py")):
        read = _read_module(path)
        if read is not None and any(base in read[0] for base in bases):
            constants = _parsed(path, *read).constants
            if constants:
                helpers[path.stem] = constants
    found: dict[str, list[str]] = {rel: [] for rel in wanted}
    for path in sorted(tests_dir.glob("test_*.py")):
        read = _read_module(path)
        if read is None:
            continue
        text, data = read
        via = [stem for stem in helpers if stem in text]
        named = wanted if via else [rel for rel in wanted if rel.rsplit("/", 1)[-1] in text]
        if not named:
            continue
        module = _parsed(path, text, data)
        names = set(module.names)
        for stem, name in module.imports:
            names |= helpers.get(stem, {}).get(name, frozenset())
        for rel in named:
            if _names_path(names, rel):
                found[rel].append(f"tests/{path.name}")
    return tuple(dict.fromkeys(t for rel in wanted for t in found[rel]))


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
    them, so the line rides along with the two cheaper tiers only. A changed
    agent, command or skill body brings ``BODY_TEST_FILES``, which is
    enumerated, not derived: a body's tests cannot be read from its name, so
    the roster is hand-kept and pinned to that file's walk (DEF-4067: a
    body-only diff ran none of the tests written for the bodies). Every test
    file that names a changed path, short of writing it into a tree it built,
    follows (``path_readers``, derived)."""
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
        if is_body(rel):
            out.extend(t for t in BODY_TEST_FILES if (root / t).is_file() and t not in out)
    out.extend(t for t in path_readers(changed, root) if t not in out)
    return tuple(out)


def tier_argvs(which: str, changed=(), root: Path = _ROOT, *, heavy: bool = False,
               leg: str = "both") -> tuple[tuple[str, ...], ...]:
    """The argv list a tier runs for THIS diff: the tier's own commands, then
    one line for the diff's own test files (``own_tests``) on the two cheaper tiers.
    ``KeyError`` on a tier nobody wired -- never a silent fall-through to the
    cheaper tier. ``heavy`` puts the heavy end-to-end stages back on both lines
    (the clean-checkout cell and the gate's first leg); ``leg`` selects by
    complement (see ``LEGS``), so the default form is always the whole tier and
    ``FULL_COMMANDS`` stays the four lines the receipts count."""
    argvs = _TIER_ARGVS[which]
    own = () if which == "full" else own_tests(changed, root)
    own_parallel = tuple(rel for rel in own if rel not in SERIAL_FILES)
    own_serial = tuple(rel for rel in own if rel in SERIAL_FILES)
    lines = (argvs
             + ((_PYTEST + _PARALLEL + _NOT_HEAVY + own_parallel,) if own_parallel else ())
             + ((_PYTEST + _ONE_WORKER + _NOT_HEAVY + own_serial,) if own_serial else ()))
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
        if head == "pytest" and rc == 4 and "-n" in rest:
            # pytest's usage error: without pytest-xdist, `-n` is an argument
            # it does not know, and every tier's pytest lines carry it.
            print(f"pytest: exit 4 is a usage error; an unrecognized `-n` means pytest-xdist "
                  f"is missing -- {INSTALL_HINT}", flush=True)
        print(f"exit {rc}: {shlex.join(argv)}", flush=True)
        worst = max(worst, rc)
    verdict = "PASS" if worst == 0 else f"FAIL (worst exit {worst})"
    print(f"proof: {verdict} -- {len(argvs)} of {len(argvs)} command(s) ran", flush=True)
    return worst


def changed_paths(root: Path) -> tuple[list[str], list[str]]:
    """``(changed, untracked)`` repo-relative paths: everything modified, staged
    or intent-added versus HEAD, and the ``??`` files git does not track."""
    porcelain = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    changed: list[str] = []
    untracked: list[str] = []
    # -z: one NUL-ended field per entry, the path unquoted (a hook path with a
    # space or a non-ASCII character read as typed; review, 2026-10-16), and a
    # rename's or copy's original path as the next field, skipped here.
    fields = porcelain.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            if "R" in code and i < len(fields) and fields[i]:
                # a rename deletes its original: that path's tier and readers
                # count, as the --base diff's delete-plus-add reads it
                changed.append(fields[i])
            i += 1
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
        ["git", "-C", str(root), "status", "--porcelain", "-z"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    return [field[3:] for field in porcelain.split("\0") if field[:2] == " D"]


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


#: A GitHub Actions expression (``${{ github.workspace }}``), read as one
#: expansion before the words are split: its value is the runner's, unknown here.
_ACTIONS_EXPRESSION_RE = re.compile(r"\$\{\{[^}\n]*\}\}")
#: Where a quoted span that held an expansion ended inside a word: the shell's
#: boundary between the expansion and the literal after it, which dequoting
#: would otherwise lose (``python "$PREFIX"scripts/x.py``).
_EXPANSION_END = "\0"


def _shell_statements(script: str) -> list[list[tuple[str, bool]]]:
    """The statements of a ``run:`` script, each its words as ``(word,
    quoted)``: a quoted span joins its word unquoted (``quoted`` says it held
    one), a ``$(...)`` inside double quotes is a script of its own whose
    statements join the list (``tier="$(python scripts/proof_tier.py ...)"``),
    a comment is dropped, a backslash escapes the next character and drops a
    line break, and a word ends at whitespace while a statement ends at a
    shell operator or a line break. An unterminated quote is read as a literal
    character, so an apostrophe in heredoc prose cannot hide the calls after
    it (review, 2026-10-16). A character scanner, not a regex."""
    statements: list[list[tuple[str, bool]]] = []
    words: list[tuple[str, bool]] = []
    cur: list[str] = []
    state = {"open": False, "quoted": False}

    def flush() -> None:
        if state["open"]:
            words.append(("".join(cur), state["quoted"]))
        cur.clear()
        state["open"] = state["quoted"] = False

    def end() -> None:
        flush()
        if words:
            statements.append(list(words))
            words.clear()

    script = _ACTIONS_EXPRESSION_RE.sub("${GHA}", script)
    i, n = 0, len(script)
    while i < n:
        c = script[i]
        if c == "\\":
            if i + 1 < n and script[i + 1] != "\n":
                cur.append(script[i + 1])
                state["open"] = True
            i += 2
            continue
        if c == "'":
            close = script.find("'", i + 1)
            if close < 0:
                cur.append(c)
                state["open"] = True
                i += 1
                continue
            cur.append(script[i + 1:close])
            state["open"] = state["quoted"] = True
            i = close + 1
            continue
        if c == '"':
            j, buf, expands = i + 1, [], False
            while j < n and script[j] != '"':
                if script[j] == "\\" and j + 1 < n:
                    buf.append(script[j + 1])
                    j += 2
                    continue
                if script.startswith("$(", j):
                    depth, k = 1, j + 2
                    while k < n and depth:
                        depth += {"(": 1, ")": -1}.get(script[k], 0)
                        k += 1
                    statements.extend(_shell_statements(script[j + 2:k - 1 if depth == 0 else k]))
                    expands = True
                    j = k
                    continue
                if script[j] == "$":
                    expands = True
                buf.append(script[j])
                j += 1
            if j >= n:
                cur.append(c)
                state["open"] = True
                i += 1
                continue
            cur.append("".join(buf) + (_EXPANSION_END if expands else ""))
            state["open"] = state["quoted"] = True
            i = j + 1
            continue
        if c == "#" and not state["open"]:
            newline = script.find("\n", i)
            i = n if newline < 0 else newline
            continue
        if c == "\n" or c in _SHELL_OPERATORS:
            end()
        elif c.isspace():
            flush()
        else:
            cur.append(c)
            state["open"] = True
        i += 1
    end()
    return statements


def _after_expansion(word: str) -> str | None:
    """The literal tail of a word after its last expansion (``$NAME``,
    ``${...}``, an Actions expression, or a quoted span that held one), a
    leading slash dropped: the path a call names under a root the expansion
    supplies (``${{ github.workspace }}/scripts/gate.py``). None where the word
    holds no expansion."""
    if _EXPANSION_END in word:
        tail = word[word.rfind(_EXPANSION_END) + 1:]
    elif "$" in word:
        rest = word[word.rfind("$") + 1:]
        if rest.startswith("{"):
            close = rest.find("}")
            tail = rest[close + 1:] if close >= 0 else ""
        else:
            k = 0
            while k < len(rest) and (rest[k].isalnum() or rest[k] == "_"):
                k += 1
            tail = rest[k:]
    else:
        return None
    return tail.lstrip("/") or None


#: The commands whose next word, quoted or not, is the script they run, and
#: whose `-m pkg.mod` names a module file (air, 2026-10-16).
_INTERPRETERS = frozenset({"python", "python3", "py", "bash", "sh", "pwsh", "node"})
#: The commands whose words are data: text printed, or a test's operands
#: (`[ -f espalier/__init__.py ]` checks a file, it does not call it).
_DATA_COMMANDS = frozenset({"echo", "printf", "[", "[[", "test"})
#: The shell words that open a statement before its command (`if [ -f x ]`
#: is the test command, not an `if` command with operands).
_SHELL_KEYWORDS = frozenset({"if", "then", "else", "elif", "while", "until", "do", "!", "time", "{"})


def _command_name(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_interpreter(name: str) -> bool:
    return name in _INTERPRETERS or (name.startswith("python") and name[6:].replace(".", "").isdigit())


def _statement_calls(words: list[tuple[str, bool]]) -> list[str]:
    """The words of one statement that name a file it calls: the command word
    itself, every unquoted word after it, the first word after an interpreter
    and its flags (quoted or not), and an interpreter's `-m` module as a path;
    an assignment before the command is skipped, and a data command's words
    are none."""
    k = 0
    while k < len(words) and not words[k][1] and (
            words[k][0] in _SHELL_KEYWORDS
            or ("=" in words[k][0] and words[k][0].split("=", 1)[0].replace("_", "").isalnum())):
        k += 1
    if k >= len(words):
        return []
    command = words[k][0].replace(_EXPANSION_END, "")
    name = _command_name(command)
    if name in _DATA_COMMANDS:
        return []
    calls = [command]
    interpreter = _is_interpreter(name)
    script_seen = False
    rest = words[k + 1:]
    j = 0
    while j < len(rest):
        word, quoted = rest[j]
        if interpreter and word == "-m" and j + 1 < len(rest):
            module = rest[j + 1][0].replace(".", "/")
            calls += [f"{module}.py", f"{module}/__main__.py"]
            j += 2
            script_seen = True
            continue
        if interpreter and not script_seen and not word.startswith("-"):
            calls.append(word)
            script_seen = True
        elif not quoted:
            calls.append(word)
        j += 1
    return calls


def _scalar(value: str) -> str:
    """One inline YAML value: a pair of enclosing quotes removed, or a plain
    value's trailing `` #`` comment."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


#: The keys of an action file whose value is a file the action runs, beside
#: its `run:` steps (a JavaScript action's entry points).
_ACTION_ENTRY_KEYS = frozenset({"main", "pre", "post"})


def _run_and_uses(text: str) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """``(runs, uses, entries)`` of one workflow or action file, read by line
    and indentation (stdlib only: the CI tier job runs this script before
    anything is installed): each ``run:`` script with the ``working-directory``
    its step names (``""`` for none), each ``uses:`` value, and each JavaScript
    action entry point (``main:``, ``pre:``, ``post:``). A block scalar
    (``key: |`` or ``key: >``) is every following line indented past its key,
    blank lines included, and is skipped whole unless the key is ``run``, so a
    line inside another key's block is never read as a key. Every other value
    -- an ``env:`` entry, a ``with:`` input, a comment -- is not a call. A step
    is a list item; its keys are the ones at its first key's column."""
    runs: list[tuple[str, str]] = []
    uses: list[str] = []
    entries: list[str] = []
    step_runs: list[str] = []
    step = {"col": -1, "dir": ""}

    def close_step() -> None:
        runs.extend((script, step["dir"]) for script in step_runs)
        step_runs.clear()
        step["col"], step["dir"] = -1, ""

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        body = line.lstrip(" ")
        col = len(line) - len(body)
        if not body.strip() or body.startswith("#"):
            continue
        if body.startswith("- "):
            close_step()
            rest = body[2:].lstrip(" ")
            col += len(body) - len(rest)
            body = rest
            step["col"] = col
        elif step["col"] >= 0 and col < step["col"]:
            close_step()
        key, sep, value = body.partition(":")
        if not sep:
            continue
        value = value.strip()
        in_step = step["col"] >= 0 and col == step["col"]
        if value[:1] in ("|", ">"):
            block: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= col:
                    break
                block.append(nxt)
                i += 1
            if key == "run" and in_step:
                step_runs.append("\n".join(block))
            elif key == "run":
                runs.append(("\n".join(block), ""))
        elif key == "run":
            if in_step:
                step_runs.append(_scalar(value))
            else:
                runs.append((_scalar(value), ""))
        elif key == "working-directory" and in_step:
            step["dir"] = _scalar(value)
        elif key == "uses":
            uses.append(_scalar(value))
        elif key in _ACTION_ENTRY_KEYS:
            entries.append(_scalar(value))
    close_step()
    return runs, uses, entries


def _head_files(root: Path, at_head: bool) -> tuple[set[str] | None, Callable[[str], str | None]]:
    """``(files, read)`` at the diff's head: with ``at_head`` (``--base``), the
    files of ``HEAD``'s tree and a reader of their blobs; otherwise ``None``
    (ask the disk) and a reader of the working tree. Raises
    ``BaseUnresolvable`` when git cannot list ``HEAD`` or read a blob it
    listed: an unread file is never read as an empty one."""
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
        if out.returncode != 0:
            raise BaseUnresolvable(f"cannot read HEAD:{rel}: {out.stderr.strip()}")
        return out.stdout
    return files, read_blob


def _file_test(root: Path, files: set[str] | None) -> Callable[[str], bool]:
    """Whether a repo-relative spelling names a file at the diff's head."""
    def is_file(rel: str) -> bool:
        if not rel or rel.startswith(("/", "../")) or ":" in rel or "/../" in rel:
            return False
        return rel in files if files is not None else (root / rel).is_file()
    return is_file


def workflow_named_files(root: Path = _ROOT, *, at_head: bool = False) -> dict[str, str]:
    """Every repo file a workflow at the diff's head calls, mapped to the file
    that names it: a call word of a ``run:`` script (`_statement_calls`) that
    is a file there, read from the step's ``working-directory`` too and past
    an expansion the runner fills in; a local action or reusable workflow
    (``uses: ./...``), whose own ``run:`` steps and JavaScript entry points are
    read in turn. The head is the working tree, or ``HEAD``'s tree with
    ``at_head`` (``--base``: a pull request's own run). A path a workflow
    names that is not a file at the head does not join; a remote ``uses:`` is
    not a repo file."""
    files, read = _head_files(root, at_head)
    is_file = _file_test(root, files)

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
        runs, uses, entries = _run_and_uses(text)
        for script, directory in runs:
            base_dir = (_after_expansion(directory) if "$" in directory else directory) or ""
            base_dir = base_dir.strip("/").removeprefix("./")
            for words in _shell_statements(script):
                for word in _statement_calls(words):
                    for spelling in (word.replace(_EXPANSION_END, ""), _after_expansion(word)):
                        if not spelling:
                            continue
                        rel = spelling[2:] if spelling.startswith("./") else spelling
                        for candidate in ((f"{base_dir}/{rel}", rel) if base_dir else (rel,)):
                            if is_file(candidate):
                                named.setdefault(candidate, src)
        action_dir = src.rsplit("/", 1)[0] if src.rsplit("/", 1)[-1].startswith("action.") else ""
        for entry in entries:
            candidate = f"{action_dir}/{entry.removeprefix('./')}" if action_dir else entry
            if is_file(candidate):
                named.setdefault(candidate, src)
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


def hook_loaded_files(root: Path = _ROOT, *, at_head: bool = False) -> dict[str, str]:
    """Every ``tools/cc/`` module a hook loads, mapped to the file that loads
    it: an ``import`` or ``from ... import`` of a name that is a module beside
    the hooks or in ``tools/cc/`` (the hooks put both on ``sys.path``), and a
    by-path load (a ``"<name>.py"`` joined to a path, or the first argument of
    ``_load_beside_hooks``), read through every module so loaded. A break in
    any of them makes the hook that loads it refuse every tool call (air,
    2026-10-16: this morning's lock-out), so each earns a hook's review.
    Derived from the hooks' own source at the diff's head, never a hand list."""
    import ast

    files, read = _head_files(root, at_head)
    is_file = _file_test(root, files)
    if files is not None:
        hooks = sorted(p for p in files if p.startswith(_HOOK_PREFIX) and p.endswith(".py") and p.count("/") == 3)
    else:
        hooks = sorted(f"{_HOOK_PREFIX}{p.name}" for p in (root / _HOOK_PREFIX).glob("*.py"))

    def module_file(name: str) -> str | None:
        for cand in (f"{_HOOK_PREFIX}{name}.py", f"tools/cc/{name}.py"):
            if is_file(cand):
                return cand
        return None

    def loads(source: str) -> set[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module.split(".")[0])
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str) \
                        and node.right.value.endswith(".py") and "/" not in node.right.value:
                    found.add(node.right.value[:-3])
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_load_beside_hooks" \
                    and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) and node.args[0].value.endswith(".py"):
                found.add(node.args[0].value[:-3])
        return found

    loaded: dict[str, str] = {}
    queue = list(hooks)
    seen = set(hooks)
    while queue:
        src = queue.pop(0)
        text = read(src)
        if text is None:
            continue
        for name in sorted(loads(text)):
            target = module_file(name)
            if target is None or target in seen:
                continue
            seen.add(target)
            queue.append(target)
            if not target.startswith(_HOOK_PREFIX):
                loaded[target] = src
    return loaded


def _mirror_rows(root: Path, at_head: bool) -> list[tuple[str, tuple[str, ...]]]:
    """``(source, mirrors)`` per ``MirrorRow(...)`` of
    ``espalier/mirror_registry.py`` at the diff's head, read from its literals
    by ``ast`` (nothing of it runs), a glob source read as the directory
    before its first wildcard; empty where the tree keeps no registry."""
    import ast

    _files, read = _head_files(root, at_head)
    source = read("espalier/mirror_registry.py")
    if source is None:
        return []
    rows = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "MirrorRow"):
            continue
        fields = {kw.arg: kw.value for kw in node.keywords}
        try:
            sot = ast.literal_eval(fields["sot"])
            mirrors = tuple(ast.literal_eval(fields["mirrors"]))
        except (KeyError, ValueError):
            continue
        for wild in ("*", "{", "?"):
            if wild in sot:
                sot = sot[:sot.index(wild)]
        rows.append((sot, mirrors))
    return rows


def _gitignore_touches_kill_switch(root: Path, base: str | None) -> bool:
    """A changed ``.gitignore`` line names ``.claude/settings.json``: the
    kill-switch's foreclosure (CLAUDE.md, Hooks), so the diff is a gate's
    (air, 2026-10-16). Read from the diff the review reads: the merge-base
    diff with ``base``, else the working tree's against ``HEAD``."""
    # Literal argv lists, as `changed_since` keeps them: the subprocess-contract
    # scanner resolves a literal and refuses a list chosen at run time.
    try:
        if base:
            diff = subprocess.run(
                ["git", "-C", str(root), "diff", f"{base}...HEAD", "--", ".gitignore"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
            ).stdout
        else:
            diff = subprocess.run(
                ["git", "-C", str(root), "diff", "HEAD", "--", ".gitignore"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
            ).stdout
    except (OSError, subprocess.CalledProcessError):
        return True
    return any(line[:1] in "+-" and not line.startswith(("+++", "---")) and ".claude/settings.json" in line
               for line in diff.splitlines())


#: The levels a review takes, lowest first (``REVIEWS`` in order).
_NONE, _CODE, _BOTH = 0, 1, 2


def review(changed: Iterable[str], root: Path = _ROOT, *, at_head: bool = False,
           base: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    """``(verdict, earned_by)``: the reviewers the diff's surface earns, one of
    ``REVIEWS``, and each path that earned the verdict with why. Both: a hook
    or a module a hook loads, a command / agent / skill / workflow body, a
    gate (the CI definition, ``bench/``, a file a workflow calls), the
    harness's configuration that a hook or a gate reads (``espalier.toml``,
    ``pyproject.toml``, the kill-switch's ``.gitignore`` line), and a
    mirror-registry source whose mirror earns both. Code-reviewer: the review
    surface, the suite's shared test code, any other ``.gitignore`` line.
    The derived sets are read only when a path is left that no prefix
    decides. ``base`` (``--base``) is the ref the ``.gitignore`` diff is read
    against; ``at_head`` follows it."""
    at_head = at_head or base is not None
    cache: dict[str, object] = {}

    def derived(key: str, make: Callable[[], object]) -> object:
        if key not in cache:
            cache[key] = make()
        return cache[key]

    def classify(rel: str, depth: int = 0) -> tuple[int, str]:
        if rel.startswith(_HOOK_PREFIX):
            return _BOTH, "a hook"
        if rel.startswith(_BODY_PREFIXES):
            return _BOTH, "a command, agent, skill or workflow body"
        if is_ci_definition(rel):
            return _BOTH, "the CI definition"
        if rel.startswith(_BENCH_PREFIX):
            return _BOTH, "the release bench"
        if rel in _CONFIG_BOTH_FILES:
            return _BOTH, "the configuration a hook or a gate reads"
        best = (_NONE, "")
        if rel.startswith("tools/cc/"):
            loaded = derived("hooks", lambda: hook_loaded_files(root, at_head=at_head))
            if rel in loaded:  # type: ignore[operator]
                return _BOTH, f"loaded by a hook: {loaded[rel]} loads it"  # type: ignore[index]
        named = derived("gates", lambda: workflow_named_files(root, at_head=at_head))
        if rel in named:  # type: ignore[operator]
            return _BOTH, f"a gate: {named[rel]} runs it"  # type: ignore[index]
        if rel == ".gitignore":
            if derived("gitignore", lambda: _gitignore_touches_kill_switch(root, base)):
                return _BOTH, "the kill-switch's .gitignore line"
            best = (_CODE, "the ignore rules")
        if depth == 0:
            for sot, mirrors in derived("mirrors", lambda: _mirror_rows(root, at_head)):  # type: ignore[attr-defined]
                if rel == sot or (sot.endswith("/") and rel.startswith(sot)):
                    for mirror in mirrors:
                        image = mirror + rel[len(sot):] if sot.endswith("/") else mirror
                        level, why = classify(image, depth + 1)
                        if level > best[0]:
                            best = (level, f"the source of {image} ({why})")
        if best[0] < _CODE and is_review_surface(rel):
            best = (_CODE, "on the review surface")
        if best[0] < _CODE and is_suite_config(rel):
            best = (_CODE, "the suite's shared test code")
        return best

    earned: dict[int, list[tuple[str, str]]] = {_NONE: [], _CODE: [], _BOTH: []}
    for rel in sorted({p.replace("\\", "/") for p in changed}):
        level, why = classify(rel)
        earned[level].append((rel, why))
    for level in (_BOTH, _CODE):
        if earned[level]:
            return REVIEWS[level], earned[level]
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
    diff_unread = False
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
            diff_unread = True
        untracked = []
        deleted = []
    else:
        changed, untracked = changed_paths(root)
        deleted = unstaged_deletions(root)
    earned = tier(changed + untracked, workflows_are_runtime=bool(args.base))
    which = earned if args.tier == "auto" else args.tier
    verdict = ""
    earned_by: list[tuple[str, str]] = []
    outside: list[str] = []
    if not args.quiet:
        # Not on --quiet: the CI tier job reads that one word and never pays for
        # the workflow read. What cannot be read reads as both reviewers, never
        # fewer: the workflows, the hooks or the registry at the head, and a
        # --base that did not resolve (its empty diff is not a diff with nothing
        # in it; failure-mode review, 2026-10-16).
        if diff_unread:
            verdict, earned_by = "both", [("(the diff)", f"unread: --base {args.base} did not resolve")]
        else:
            try:
                verdict, earned_by = review(changed + untracked, root, base=args.base)
            except BaseUnresolvable as exc:
                print(f"proof_tier: {exc}; the review reads both", file=sys.stderr)
                verdict, earned_by = "both", [("(the head)", "unread")]
        if args.base:
            # --base reads the committed diff alone; a dirty tree's paths are
            # named so a lane run before its commit is not read as clean.
            pending, fresh = changed_paths(root)
            outside = sorted(set(pending + fresh))
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
        "outside_the_base_diff": outside,
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
        if outside:
            print(f"note: {len(outside)} uncommitted path(s) are outside the --base diff, so neither "
                  "line read them: " + ", ".join(outside))
        for line in result["commands"]:
            print("run: " + line)
        if len(result["commands"]) > 1:
            # The recall tier's first two lines are byte-identical to the
            # contract tier's two, so a session that pastes a subset gets a
            # green indistinguishable from the tier it was meant to replace.
            if args.leg == "both":
                what = "the tier"
            elif args.leg == "parallel" and which != "full":
                what = ("the whole tier (its parallel leg: only the full tier has a serial leg, "
                        "and a changed serial file runs here at one worker)")
            else:
                what = f"the {args.leg} leg of the tier"
            print(f"all {len(result['commands'])} lines are {what} -- `--run` executes them under one receipt")
        if not result["commands"]:
            print(f"nothing to run: the {args.leg} leg of the {which} tier has no commands "
                  f"({_EMPTY_LEG_WHY})")
        if result["commands"]:
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
                  f"({_EMPTY_LEG_WHY})", flush=True)
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
