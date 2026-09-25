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

The full tier's command lines are the parallel recipe: ``pytest -n auto`` with
the three wall-clock-budget files left out, then those three serially. It is
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
tier is three commands and the recall tier two; a session that pastes only one
gets a green that never ran the rest -- one command with one receipt closes
that. ``--tier full`` forces the tier (the handoff's preflight runs the full
suite whatever the diff earned).

Usage::

    python3 scripts/proof_tier.py                    # prints the tier and its command line(s)
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
_RECALL_CORPUS_PREFIXES: tuple[str, ...] = ("memory/", "docs/sharp-edges/")
_RECALL_CORPUS_FILES: tuple[str, ...] = (
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
_TIER_ARGVS: dict[str, tuple[tuple[str, ...], ...]] = {
    "full": (
        ("mypy", "tools/cc/hooks/"),
        _PYTEST + ("-n", "auto") + tuple(f"--ignore={rel}" for rel in WALL_CLOCK_SERIAL_FILES),
        _PYTEST + WALL_CLOCK_SERIAL_FILES,
    ),
    "recall": (_CONTRACT_ARGV, _PYTEST + RECALL_SLICE_FILES),
    "contract": (_CONTRACT_ARGV,),
}
TIERS: tuple[str, ...] = tuple(_TIER_ARGVS)
FULL_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["full"])
RECALL_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["recall"])
CONTRACT_COMMANDS: tuple[str, ...] = tuple(shlex.join(argv) for argv in _TIER_ARGVS["contract"])
INSTALL_HINT = "needs pytest-xdist and mypy (the `dev` extra: pip install -e '.[dev]')"
#: The runners a proof command may lead with. `run_commands` dispatches on the
#: head with one literal call per runner, so the receipt line (shlex.join of the
#: argv) and the spawned binary are the same token by construction -- a widened
#: allowlist over a hard-coded ["pytest"] would print one and run the other.
_RUNNERS: tuple[str, ...] = ("mypy", "pytest")


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


def tier_argvs(which: str, changed=(), root: Path = _ROOT) -> tuple[tuple[str, ...], ...]:
    """The argv list a tier runs for THIS diff: the tier's own commands, then
    one line for the changed scripts' own test files on the two cheaper tiers.
    ``KeyError`` on a tier nobody wired -- never a silent fall-through to the
    cheaper tier."""
    argvs = _TIER_ARGVS[which]
    own = () if which == "full" else own_tests(changed, root)
    return argvs + ((_PYTEST + own,) if own else ())


def commands(which: str, changed=(), root: Path = _ROOT) -> tuple[str, ...]:
    """The command line(s) a tier runs for this diff, in order (``tier_argvs``
    rendered with ``shlex.join``, so the receipt and the execution cannot drift)."""
    return tuple(shlex.join(argv) for argv in tier_argvs(which, changed, root))


def run_commands(argvs, root: Path) -> int:
    """Run every command in order, one receipt line each, return the worst exit.

    Every command runs even after a failure, so the receipt always names all
    of them; the summary line says how many ran. Each argv leads with one of
    ``_RUNNERS`` (OS binaries the subprocess-contract scanner skips), and the
    dispatch below is one literal call per runner. A runner that is not
    installed is exit 127 with the install hint, never a silently skipped
    line."""
    worst = 0
    for argv in argvs:
        head, *rest = argv
        if head not in _RUNNERS:
            raise ValueError(f"proof commands lead with one of {_RUNNERS}, got {head!r}")
        try:
            if head == "mypy":
                rc = subprocess.run(["mypy"] + rest, cwd=root).returncode
            else:
                rc = subprocess.run(["pytest"] + rest, cwd=root).returncode
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
    else:
        changed, untracked = changed_paths(root)
    earned = tier(changed + untracked, workflows_are_runtime=bool(args.base))
    which = earned if args.tier == "auto" else args.tier
    result = {
        "tier": which,
        "earned_tier": earned,
        "base": args.base,
        "runtime_paths": sorted(p for p in changed + untracked if is_runtime(p)),
        "ci_definition_paths": sorted(p for p in changed + untracked if is_ci_definition(p)),
        "suite_config_paths": sorted(p for p in changed + untracked if is_suite_config(p)),
        "corpus_paths": sorted(p for p in changed + untracked if is_recall_corpus(p)),
        "untracked": untracked,
        "commands": list(commands(which, changed + untracked, root)),
    }
    if args.quiet:
        print(which)
        if untracked:
            print("untracked -- invisible to the git ls-files gates until staged:", file=sys.stderr)
            for p in untracked:
                print(f"  git add -N {p}", file=sys.stderr)
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
        for line in result["commands"]:
            print("run: " + line)
        if len(result["commands"]) > 1:
            # The recall tier's first line is byte-identical to the contract
            # tier's only line, so a session that pastes one line gets a green
            # indistinguishable from the tier it was meant to replace.
            print(f"all {len(result['commands'])} lines are the tier -- `--run` executes them under one receipt")
        if which == "full":
            print(INSTALL_HINT)
        if untracked:
            print("untracked -- invisible to the git ls-files gates until staged:")
            for p in untracked:
                print(f"  git add -N {p}")
    if untracked:
        return 2
    if args.run:
        rc = run_commands(tier_argvs(which, changed + untracked, root), root)
        if which != earned:
            # The forced-tier note printed at the top is four lines above the
            # receipt's summary; repeat it beside the verdict so a downgrade
            # (`--tier contract` on a runtime diff) cannot read as the earned run.
            print(f"forced: ran the {which} tier; the diff earned {earned}", flush=True)
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
