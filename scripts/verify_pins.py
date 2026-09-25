#!/usr/bin/env python3
"""Revert a change's NON-TEST files and check that at least one test goes red.

WHY THIS EXISTS (measured 2026-08-21, not asserted)
---------------------------------------------------
``docs/FAILURE_MODES.md`` holds 195 sections; 20 of them (10%) name an enforcing
test. §5.18 -- "the red you earned against a synthetic defect proves nothing
about the real one" -- names none, and was committed ONE COMMIT AFTER the broken
pin it describes shipped. 15 of 24 fix claims across ``536a8c5``/``9b97e89``/
``3060e20`` are pinned by nothing: delete the guard and the suite stays green.

The root cause is not carelessness. A fix and its proof are written in ONE pass,
by one author, and nothing independent ever checks that the proof CAN FAIL. This
script is that independent check, and it is deliberately the dumbest possible
form of it: put the code back the way it was, leave the test alone, and see if
the test notices.

THE LOAD-BEARING DETAIL
-----------------------
Revert the NON-TEST files. Leave the TEST files at their NEW state.

Reverting the tests alongside the fix makes everything trivially green -- the
suite goes back to a state it was already green in, and the tool reports the
comforting answer for every change ever made. That inversion is the whole trap.

It is genuinely covered -- three ways, MEASURED by reverting the test files
alongside the fix and watching what reds: ``test_the_working_tree_is_pinned``,
``test_the_committed_pair_carries_the_same_separation`` and
``test_no_changed_test_file_appears_in_the_reverted_set`` all fail. None of
those is a neutralisation test, and this docstring used to claim one existed
("``tests/test_verify_pins.py`` neutralises this exact line"). It does not, and
a file whose whole subject is not over-crediting a pin has no business
over-crediting its own.

WHAT A VERDICT MEANS -- AND DOES NOT
------------------------------------
    PINNED           reverting the non-test files reddened >=1 selected test.
                     The change carries at least one test that can fail.
    UNPINNED         nothing went red. Delete the change and the suite stays
                     green. This is a PROMPT TO LOOK, not a defect finding:
                     a docs-only commit lands here too (see SCOPE below).
    NOT_APPLICABLE   the changed set contains ZERO non-test files, so there is
                     nothing to revert and the mechanic has no subject.
    ERROR            the answer is unavailable -- bad sha, merge commit, or the
                     selection was ALREADY RED before the revert.

PINNED is a floor, never a ceiling. It says one test noticed; it does not say
the test asserts the right thing, covers the whole change, or would notice a
subtler regression. See "LIMITS" at the bottom of this docstring.

SCOPE -- and the rule this repo does NOT have
---------------------------------------------
Measured across the 20 commits ending at ``7a533e3`` (see ``--calibrate``):
five commits changed only ``.md`` files and owe no pin; one (``536a8c5``)
changed ``.py`` + ``.yml`` and owes ten. An extension test separates those six
IN THIS WINDOW -- and it is still the wrong rule, for two reasons visible in
the same window:

  * ``.github/workflows/publish.yml`` (in ``536a8c5`` and ``9b97e89``) is
    executable CI behaviour and carries no source-language extension. A commit
    touching only it would be waved through.
  * ``.claude/agents/code-reviewer.md`` and its two byte-pinned mirrors (in
    ``3060e20`` AND in the working tree that motivated this script) are shipped
    ASSETS whose content is asserted by the suite. They are ``.md``. The single
    artifact this whole tool was built to discriminate on is on the wrong side
    of the extension rule.

The other candidate separator -- "is this path named by any test file?" -- was
measured too and does not separate at all: it fires on 5 of 5 docs-only commits
(``ESPALIER_MEMORY.md``, ``docs/FAILURE_MODES.md`` and
``memory/CONVERGENCE_LEDGER.md`` are all named by some test).

So this script DOES NOT auto-classify docs-only changes as exempt. It reports
UNPINNED and hands you the two buckets as evidence. The bucket split uses
``tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS`` -- this repo's own
declaration, loaded from source, never a list retyped here -- and it is printed
as EVIDENCE, not applied as a verdict. A hand-tuned exemption list is how a
detector becomes a formality, and the honest "you decide" is affordable because
this gate is advisory.

CONSEQUENCE, stated so nobody wires this in blind: on this repo's commit mix
today, ``--strict`` would fail 5 of 20 recent commits for owing a pin they do
not owe. Do not put ``--strict`` in CI until a separator exists.

ISOLATION
---------
Every run happens in a throwaway ``git clone --no-hardlinks`` (~1s, ~62MB). The
live tree is never written, and not read-locked either: every ``git`` call here
passes ``--no-optional-locks``, so ``git status`` skips the stat-cache refresh
that used to rewrite the SOURCE repo's ``.git/index`` (measured: identical
sha256 across a ``worktree_changes`` call that previously changed it). The old
wording claimed this before it was true.

``--carry`` is the one arm that writes toward the repo, and it is confined:
arguments are normalised to repo-relative and refused if they resolve outside
the repo or would escape the clone. An absolute ``--carry`` used to delete its
own target from the SOURCE tree, because ``Path(clone) / "/abs"`` discards the
left operand -- and ``--carry``'s documented targets (``reports/``,
``.espalier/``) are gitignored, so git could not put them back.

The isolation pin (``tests/test_verify_pins.py::TestIsolation``) compares a
FILESYSTEM manifest, not ``git status``: git's view is blind to gitignored paths
and to ``.git/`` -- which is exactly the region ``--carry`` operates in.

USAGE
-----
    python3 scripts/verify_pins.py                      # the working tree vs HEAD
    python3 scripts/verify_pins.py --commit 3060e20     # one commit vs its parent
    python3 scripts/verify_pins.py --json               # machine-readable
    python3 scripts/verify_pins.py --calibrate 20       # the measurement table
    python3 scripts/verify_pins.py --strict             # UNPINNED exits 1

LIMITS -- what this cannot detect
---------------------------------
See ``README``-style prose in ``main()``'s ``--explain`` output; kept in one
place so the two cannot drift.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

REPO_DEFAULT = Path(__file__).resolve().parent.parent

PINNED = "PINNED"
UNPINNED = "UNPINNED"
NOT_APPLICABLE = "NOT_APPLICABLE"
ERROR = "ERROR"

#: Incremented into every child pytest env. A test module that itself drives
#: this script reads it to bound recursion. See `run_pytest`.
DEPTH_ENV = "ESPALIER_VERIFY_PINS_DEPTH"


class VerifyPinsError(Exception):
    """The answer is unavailable. Never silently degraded into a verdict."""


# ---------------------------------------------------------------------------
# git plumbing -- BYTES throughout
#
# Every blob read is bytes, never text. That is not fussiness: it is how binary
# content is handled without a separate code path, and how a CRLF or a lone
# surrogate in a doc survives the round trip. `git show <base>:<path>` on a PNG
# and on a Markdown file are the same operation here.
# ---------------------------------------------------------------------------


def _git_text(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise VerifyPinsError(
            f"git {' '.join(args)} failed in {repo} (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _git_bytes(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args], capture_output=True)
    if proc.returncode != 0:
        raise VerifyPinsError(
            f"git {' '.join(args)} failed in {repo} (rc={proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def _blob_mode(repo: Path, rev: str, path: str) -> str | None:
    """The file mode git recorded for `path` at `rev`, or None if absent.

    Restoring content without restoring mode loses the exec bit on
    `scripts/*.sh` and turns a symlink into a regular file holding its target
    as text -- both of which change behaviour while looking like a clean revert.
    """
    out = _git_text(repo, "ls-tree", rev, "--", path)
    if not out.strip():
        return None
    return out.split()[0]


# ---------------------------------------------------------------------------
# The changed set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One path's transition. `path` is the POST-change name."""

    status: str            # "M" | "A" | "D" | "R" | "T"
    path: str
    old_path: str | None = None   # set only for R


def _parse_name_status(raw: str) -> list[Change]:
    changes: list[Change] = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0].strip()
        letter = code[0]
        if letter == "R" and len(parts) >= 3:
            changes.append(Change("R", parts[2].replace("\\", "/"),
                                  parts[1].replace("\\", "/")))
        elif letter == "C" and len(parts) >= 3:
            # A copy leaves the source untouched, so reverting it is exactly
            # "delete the new path" -- an ADD.
            changes.append(Change("A", parts[2].replace("\\", "/")))
        elif len(parts) >= 2:
            changes.append(Change(letter, parts[1].replace("\\", "/")))
    return changes


def commit_changes(repo: Path, sha: str) -> list[Change]:
    parents = _git_text(repo, "rev-list", "--parents", "-n", "1", sha).split()
    if len(parents) > 2:
        raise VerifyPinsError(
            f"{sha} is a merge commit ({len(parents) - 1} parents). "
            f"'the change' is undefined against which parent, so there is no "
            f"honest changed set to revert."
        )
    if len(parents) < 2:
        raise VerifyPinsError(
            f"{sha} is a root commit -- it has no parent state to revert to."
        )
    raw = _git_text(repo, "show", "--name-status", "--format=", "-M", sha)
    return _parse_name_status(raw)


def worktree_changes(repo: Path) -> list[Change]:
    """The working tree vs HEAD, index included, untracked files included.

    `--porcelain -z` deliberately: a path with a space or a newline in it is
    unparseable from the space-separated form, and this tool's job is to be
    trusted about a file set.
    """
    raw = _git_bytes(repo, "status", "--porcelain=v1", "-z", "-uall")
    fields = raw.decode("utf-8", "surrogateescape").split("\0")
    changes: list[Change] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:].replace("\\", "/")
        if x == "R" or y == "R":
            old = fields[i].replace("\\", "/") if i < len(fields) else None
            i += 1
            changes.append(Change("R", path, old))
        elif x == "?" or x == "A":
            changes.append(Change("A", path))
        elif "D" in (x, y):
            changes.append(Change("D", path))
        else:
            changes.append(Change("M", path))
    return changes


# ---------------------------------------------------------------------------
# Test vs non-test
#
# Derived from the repo's own pytest configuration (`testpaths`), not from a
# list written here. Everything under a declared test root is test material --
# `conftest.py` and `tests/_git_oracle.py` are as load-bearing to a pin as
# `test_foo.py`, and reverting them would re-open the trap through the side
# door.
# ---------------------------------------------------------------------------


def declared_test_roots(repo: Path) -> tuple[str, ...]:
    """`testpaths` from pyproject.toml, or ("tests",) if undeclared.

    NOT named `test_roots`: this module is imported by `tests/test_verify_pins.py`,
    and pytest COLLECTS any imported module-level callable whose name starts with
    `test_`. It did -- as `test_roots(repo)` with a missing `repo` fixture, which
    reddened the whole file at collection. Measured 2026-08-21.
    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return ("tests",)
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return ("tests",)
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a malformed pyproject must not decide a verdict
        return ("tests",)
    paths = (
        data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths")
    )
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        return ("tests",)
    return tuple(str(p).rstrip("/") for p in paths)


def is_test_path(rel: str, roots: tuple[str, ...]) -> bool:
    """Location, and ONLY location. `testpaths` is the whole rule.

    This used to also return True for any basename matching `test_*.py`
    wherever it lived, which is not a derivation -- pytest never collects
    outside `testpaths`, so the glob had no basis in pytest's behaviour. It was
    wrong on 13 tracked paths, including the live engine module
    `espalier/scanners/test_loosening.py` (imported at espalier/cli.py:3921) and
    the seven files of the byte-pinned `selfcheck-tests` mirror row. The cost
    was not cosmetic: on `45b24c7` six scanners were fixed and only five were
    reverted -- `test_loosening.py` was silently held at its NEW state through
    the revert and the commit reported PINNED for a scanner change that was
    never put back. Measured 2026-08-21.
    """
    rel = rel.replace("\\", "/")
    return any(rel == r or rel.startswith(r + "/") for r in roots)


def is_test_module(rel: str, roots: tuple[str, ...]) -> bool:
    """Selectable by pytest as a module -- `conftest.py` is not."""
    name = Path(rel).name
    return is_test_path(rel, roots) and name.startswith("test_") and name.endswith(".py")


# ---------------------------------------------------------------------------
# Evidence buckets (NOT a verdict -- see the module docstring's SCOPE section)
# ---------------------------------------------------------------------------


#: The owner is named ONCE. The path the loader reads and the provenance the
#: report prints used to be two independent hand-typed copies of this string, so
#: the printed citation could stay true while the loader went stale -- and no
#: citation gate could catch it, because the prose was still accurate. One value
#: now feeds both.
SOURCE_EXT_OWNER_REL = "tools/cc/hooks/_hook_utils.py"
SOURCE_EXT_OWNER_SYMBOL = "SOURCE_LANGUAGE_EXTENSIONS"
SOURCE_EXT_OWNER = f"{SOURCE_EXT_OWNER_REL}::{SOURCE_EXT_OWNER_SYMBOL}"


def source_language_extensions(repo: Path) -> frozenset[str] | None:
    """This repo's OWN declaration, loaded from source. None if UNAVAILABLE.

    `tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS` is the single
    owner (`plan_guard` and `reflect_trigger` both alias it). Loading it means
    the bucket split tracks the repo instead of a copy that goes stale here.
    Loaded by path, not import: `tools/cc/` is standalone by contract.

    RETURNS None, NEVER AN EMPTY SET, WHEN THE OWNER CANNOT BE LOADED. Four
    failure paths (absent file, no spec, exec raising, symbol missing) used to
    collapse into `frozenset()`, which is indistinguishable from "nothing
    matched" -- so after a plausible refactor moved the owner, every run would
    print "0 of N non-test paths carry a source-language extension" forever,
    under a line still naming the owner it no longer read. A `.py`-bearing
    behaviour change would then carry the evidence signature of a docs commit.
    `VerifyPinsError` states the principle this restores: the answer is
    unavailable, and unavailable is never silently degraded into a measurement.
    """
    candidate = repo / SOURCE_EXT_OWNER_REL
    if not candidate.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_vp_hook_utils", candidate)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - evidence is optional; a verdict is not
        return None
    declared = getattr(module, SOURCE_EXT_OWNER_SYMBOL, None)
    if declared is None:
        return None
    return frozenset(declared)


# ---------------------------------------------------------------------------
# Clone + revert
# ---------------------------------------------------------------------------


def make_clone(repo: Path, dest: Path) -> None:
    proc = subprocess.run(
        ["git", "clone", "--no-hardlinks", "-q", str(repo), str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise VerifyPinsError(f"clone failed: {proc.stderr.strip()}")


def _write_blob(clone: Path, rel: str, content: bytes, mode: str | None) -> None:
    target = clone / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    if mode == "120000":
        # A symlink's blob IS its target. Writing it as a regular file is a
        # silent behaviour change dressed as a clean revert.
        os.symlink(content.decode("utf-8", "surrogateescape"), target)
        return
    target.write_bytes(content)
    if mode and mode.endswith("755"):
        target.chmod(0o755)


def _remove(clone: Path, rel: str) -> None:
    target = clone / rel
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def apply_worktree_state(repo: Path, clone: Path, changes: list[Change]) -> None:
    """Make the clone match the live working tree for every changed path."""
    for ch in changes:
        if ch.status == "D":
            _remove(clone, ch.path)
            continue
        if ch.status == "R" and ch.old_path:
            _remove(clone, ch.old_path)
        src = repo / ch.path
        if not src.exists():
            _remove(clone, ch.path)
            continue
        dest = clone / ch.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() or dest.exists():
            _remove(clone, ch.path)
        if src.is_symlink():
            os.symlink(os.readlink(src), dest)
        elif src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)


def revert_to_base(repo: Path, clone: Path, base: str, changes: list[Change]) -> list[str]:
    """Put each change back the way `base` had it. Returns the paths touched.

    ADDED   -> delete (the file did not exist at base)
    DELETED -> restore from base
    RENAMED -> delete the new name, restore the old one
    MODIFIED/TYPECHANGE -> overwrite with base's bytes and base's mode
    """
    touched: list[str] = []
    for ch in changes:
        if ch.status == "A":
            _remove(clone, ch.path)
            touched.append(f"delete {ch.path}")
        elif ch.status == "D":
            _write_blob(clone, ch.path, _git_bytes(repo, "show", f"{base}:{ch.path}"),
                        _blob_mode(repo, base, ch.path))
            touched.append(f"restore {ch.path}")
        elif ch.status == "R":
            _remove(clone, ch.path)
            if ch.old_path:
                _write_blob(clone, ch.old_path,
                            _git_bytes(repo, "show", f"{base}:{ch.old_path}"),
                            _blob_mode(repo, base, ch.old_path))
                touched.append(f"un-rename {ch.old_path} <- {ch.path}")
        else:
            _write_blob(clone, ch.path, _git_bytes(repo, "show", f"{base}:{ch.path}"),
                        _blob_mode(repo, base, ch.path))
            touched.append(f"restore {ch.path}")
    return touched


def sync_git_metadata(clone: Path) -> bool:
    """Record the reverted worktree as a commit. Returns True if one was made.

    THE DEFECT THIS CLOSES, measured 2026-08-21 on two real artifacts.
    `revert_to_base` restores CONTENT and never touches the index. In `--commit`
    mode the clone is detached AT the change, so after the revert every ADDED
    non-test path is tracked-but-absent and every DELETED one is
    present-but-untracked. That is a state git cannot reach on its own, and
    every test driving `git ls-files` or `git archive` is then asked a question
    about a tree that never existed.

    It was not theoretical. `a198289` and `dec327f` -- two of the seven PINNED
    rows in this tool's own calibration table -- were FALSE PASSES: their single
    red was `test_git_archive_export_ignores_internal_docs`, reddening because
    `git archive HEAD` reads the INDEX and shipped `WINDOWS_FUSE_NOTES.md`, a
    file the revert had deleted from disk and which does not exist at the real
    base at all. An independent oracle (detach at `<sha>^`, overlay the change's
    new test blobs, so HEAD/index/worktree agree) puts both at 277-passed and
    15-passed, rc=0: UNPINNED. The detector was manufacturing the verdict it
    exists to prevent.

    `--no-verify` matters: the clone carries this repo's own hook configuration.
    The commit is skipped when the revert reproduced HEAD exactly, so worktree
    mode -- where the revert lands back ON HEAD -- keeps its original sha.
    """
    _git_text(clone, "add", "-A")
    staged = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(clone), "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if staged.returncode == 0:
        return False
    _git_text(
        clone,
        "-c", "user.email=verify-pins@local", "-c", "user.name=verify-pins",
        "commit", "-q", "--no-verify",
        "-m", "verify_pins: base tree + this change's test files",
    )
    return True


def git_metadata_is_consistent(clone: Path) -> list[str]:
    """[] when HEAD/index/worktree agree. Otherwise the paths that disagree.

    The invariant `sync_git_metadata` exists to hold, stated as something
    cheaper to assert than any verdict: no path may be tracked while absent from
    disk, and no restored path may be untracked.
    """
    tracked = _git_text(clone, "ls-files", "-z").split("\0")
    missing = [t for t in tracked if t and not (clone / t).exists()]
    untracked = _git_text(
        clone, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted(missing + [u for u in untracked if u])


# ---------------------------------------------------------------------------
# Test selection
# ---------------------------------------------------------------------------


def select_tests(clone: Path, changes: list[Change], roots: tuple[str, ...],
                 full: bool, wide: bool = False) -> tuple[list[str], list[str]]:
    """(selection, notes). Three tiers, widening on demand.

    tier 1  the change's OWN changed test modules.
    tier 2  exact name-derived candidates: `espalier/foo.py` -> `tests/test_foo.py`.
    tier 3  (`--wide`) any test module whose stem CONTAINS the changed stem.

    Tiers 1+2 are the default because the claim under test is "this change
    carries a pin", a pin normally ships beside its fix, and this keeps a run at
    seconds instead of 11.5 minutes.

    Tier 2 measurably under-selects. Measured on the last 40 commits:
    `espalier/scanners/subprocess_contracts.py` has no `test_subprocess_contracts.py`
    (its test is `test_scanner_subprocess_contracts.py`) and `tools/cc/hooks/_recall.py`
    has no `test__recall.py` (its tests are `test_recall.py` +
    `test_recall_calibration.py`). Tier 3 recovers both.

    NO minimum stem length on tier 3, and that is a measured choice rather than
    an oversight: the shortest non-test changed stem in the last 40 commits is
    `cli` (3 chars), whose containment matches are eight genuinely CLI-focused
    modules. A length guard would exclude the most common short stem in the
    population and prevent nothing observed.
    """
    if full:
        return [r for r in roots if (clone / r).exists()], ["selection: --full"]

    # EXACT-CASE existence, deliberately not Path.is_file().
    #
    # macOS/APFS is case-INSENSITIVE, so `Path("tests/test_ENV_CATALOG.py").is_file()`
    # returns True for a file actually named `test_env_catalog.py`. pytest is
    # handed the literal string, finds nothing, and exits rc=4 "no tests ran" --
    # which this tool then correctly refuses to turn into a verdict, leaving two
    # real commits (63beda2, 9820d5f) unanswerable. Measured 2026-08-21 on the
    # calibration sweep, not predicted. A directory listing is case-exact on
    # every platform; `is_file()` is not.
    listings: dict[str, set[str]] = {"": {p.name for p in clone.iterdir()}}
    for root in roots:
        root_dir = clone / root
        listings[root] = (
            {p.name for p in root_dir.iterdir()} if root_dir.is_dir() else set()
        )

    def exists_exact(root: str, name: str) -> bool:
        return name in listings.get(root, set())

    notes: list[str] = []
    selection: list[str] = []
    for ch in changes:
        if ch.status == "D":
            continue
        if not is_test_module(ch.path, roots):
            continue
        root, _, name = ch.path.rpartition("/")
        if exists_exact(root, name):
            selection.append(ch.path)

    derived: list[str] = []
    widened: list[str] = []
    for ch in changes:
        if is_test_path(ch.path, roots) or ch.status == "D":
            continue
        stem = Path(ch.path).stem
        if not stem:
            continue
        hit = False
        for root in roots:
            name = f"test_{stem}.py"
            if exists_exact(root, name):
                hit = True
                cand = f"{root}/{name}"
                if cand not in selection and cand not in derived:
                    derived.append(cand)
        if hit or not wide:
            continue
        for root in roots:
            for name in sorted(listings.get(root, set())):
                if not (name.startswith("test_") and name.endswith(".py")):
                    continue
                if stem.lower() not in name[:-3].lower():
                    continue
                cand = f"{root}/{name}"
                if cand not in selection and cand not in derived and cand not in widened:
                    widened.append(cand)
    if derived:
        notes.append(f"name-derived candidates: {', '.join(derived)}")
    if widened:
        notes.append(f"--wide containment candidates: {', '.join(widened)}")
    selection.extend(derived)
    selection.extend(widened)
    return sorted(set(selection)), notes


# ---------------------------------------------------------------------------
# Running pytest
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    rc: int
    failures: list[str] = field(default_factory=list)
    tail: str = ""


def run_pytest(clone: Path, selection: list[str], timeout: int) -> RunResult:
    env = os.environ.copy()
    # The launching shell has ESPALIER_MAINTENANCE_MODE=1 during harness
    # self-edits; a hook subprocess spawned by a test would inherit it and
    # bypass the very protection under test. conftest strips it too -- belt and
    # braces, because this runner must be trustworthy on a tree whose conftest
    # is the thing being reverted.
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    env.pop("ESPALIER_STOP_GATE", None)
    # The child's stdout is PARSED (`line.startswith("FAILED ")` below), so it
    # must not be colorized. pytest colorizes on a TTY -- which this is not,
    # being captured -- but `FORCE_COLOR` overrides that check, and Claude Code
    # sets `FORCE_COLOR=3` in the shell this runner is most often launched from.
    # The inherited value made every ANSI-prefixed `FAILED` line miss the
    # anchor, so `failures` came back EMPTY on a red child and the runner
    # reported "rc=1 without naming a single failing test" -- an ERROR verdict
    # on every pin it was asked to check. Driven both directions on one commit:
    # with FORCE_COLOR=3 the three pin tests fail; with it unset they pass.
    # Env-relative, so it never reproduced outside a color-forcing shell.
    env.pop("FORCE_COLOR", None)
    env.pop("PY_COLORS", None)
    env["NO_COLOR"] = "1"
    # docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR": a leaked
    # value would point child hooks at the LIVE tree from inside the clone. The
    # sharp edge is closed by UNSETTING the variable, not by re-pointing it --
    # `_hook_utils.resolve_project_root()` then falls back to cwd, and cwd is
    # already the clone, so isolation is preserved either way.
    #
    # Re-pointing it was measurably worse. Controlled A/B, two fresh clones of
    # this repo, one variable: with the var unset,
    # `tests/test_execution_plan_cli.py tests/test_task_router.py` is 54 passed
    # rc=0; with it set to the clone, 10 failed / 44 passed rc=1. 46 tests at
    # HEAD isolate themselves by `cwd=tmp_path` alone and read the plan path
    # through this variable (tools/cc/execution_plan.py::_plan_path), so setting
    # it re-introduced from the outside the exact leak tests/conftest.py:114-117
    # says no test commits. The blast radius was the whole tool: any subject
    # whose selection touched those 7 modules returned ERROR instead of a
    # verdict (`--commit b4ef0c8` -> ERROR, `--strict` -> rc=2), and `--full`
    # could never return a verdict for ANY subject. Measured 2026-08-21.
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # `pip install -e .` puts the LIVE repo on sys.path. Without this the clone's
    # tests would import the live `espalier` and the revert would be invisible.
    env["PYTHONPATH"] = str(clone) + os.pathsep + env.get("PYTHONPATH", "")
    # RECURSION FUSE, and this one is not hypothetical: on the change that
    # introduced this file, the selection contained `tests/test_verify_pins.py`
    # -- so the inner pytest ran the gate's own controls, each of which clones
    # and runs pytest again. Measured 2026-08-21: 17 live clones and a run that
    # never terminated. The depth counter is read by that test module, which
    # skips its cloning controls (and ONLY those) at depth >= 1.
    env[DEPTH_ENV] = str(int(os.environ.get(DEPTH_ENV, "0")) + 1)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *selection, "-q", "--tb=no", "-rfE",
         "-p", "no:cacheprovider", "--continue-on-collection-errors"],
        cwd=str(clone), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )
    # --continue-on-collection-errors, deliberately. Reverting a non-test file
    # can break an IMPORT (the reverted state may predate a symbol a test module
    # imports at module scope), and pytest's default is to abort the whole
    # session on the first collection error -- which would hide every other
    # test's result behind the first broken module. Measured 2026-08-21 on the
    # working-tree control: the revert deleted `scripts/verify_pins.py`, the
    # matching test module failed to import, collection aborted at rc=2, and the
    # four REAL parity reds never ran or reported.
    failures = [
        line.split(" ")[1] if " " in line else line
        for line in proc.stdout.split("\n")
        if line.startswith("FAILED ") or line.startswith("ERROR ")
    ]
    tail = "\n".join([ln for ln in proc.stdout.split("\n") if ln.strip()][-6:])
    return RunResult(proc.returncode, failures, tail)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


#: Emitted whenever the changed set contains ZERO test files. Stated because it
#: is a structural fact about the mechanic that a reader will otherwise mistake
#: for a sampling result -- and because it tells you `--full` is pointless here.
_ANALYTIC_ZERO_TEST_NOTE = (
    "ANALYTIC: this change touched no test file, so reverting its non-test "
    "files reproduces the base tree BYTE-FOR-BYTE. No test in the suite can "
    "distinguish the two, so UNPINNED here is structural, not a sampling "
    "result, and --full cannot change it. The one exception -- and the reason "
    "this still RUNS rather than short-circuiting -- is a base tree that was "
    "itself red: then a pre-existing test really is the pin, and only a run "
    "shows it."
)


def verify(repo: Path, *, sha: str | None = None, full: bool = False,
           baseline: bool = True, carry: list[str] | None = None,
           timeout: int = 1800, keep: bool = False, wide: bool = False,
           per_file: bool = False, revert_only: list[str] | None = None) -> dict:
    report: dict = {
        "tool": "verify_pins",
        "schema": 1,
        "subject": {},
        "verdict": ERROR,
        "reason": "",
        "changed": {"test": [], "non_test": []},
        "evidence": {},
        "selection": [],
        "reverted": [],
        "baseline": None,
        "after_revert": None,
        "per_file": [],
        "notes": [],
    }
    roots = declared_test_roots(repo)
    try:
        if sha:
            resolved = _git_text(repo, "rev-parse", sha).strip()
            changes = commit_changes(repo, resolved)
            base = f"{resolved}^"
            report["subject"] = {
                "kind": "commit", "id": resolved[:12], "base": f"{resolved[:12]}^",
                "subject_line": _git_text(repo, "log", "-1", "--format=%s", resolved).strip(),
            }
        else:
            changes = worktree_changes(repo)
            head = _git_text(repo, "rev-parse", "HEAD").strip()
            base = head
            report["subject"] = {
                "kind": "worktree", "id": "working tree", "base": head[:12],
                "subject_line": f"uncommitted changes vs {head[:12]}",
            }
    except VerifyPinsError as exc:
        report["reason"] = str(exc)
        return report

    test_paths = [c.path for c in changes if is_test_path(c.path, roots)]
    non_test = [c for c in changes if not is_test_path(c.path, roots)]
    report["changed"]["test"] = sorted(test_paths)
    report["changed"]["non_test"] = sorted(c.path for c in non_test)

    src_exts = source_language_extensions(repo)
    if src_exts is None:
        report["notes"].append(
            f"EVIDENCE UNAVAILABLE: {SOURCE_EXT_OWNER_REL} could not be loaded, so "
            f"the source-extension bucket below is EMPTY BECAUSE IT WAS NEVER "
            f"MEASURED -- not because no path carries a source extension. Do not "
            f"read it as evidence."
        )
    owner = (
        SOURCE_EXT_OWNER if src_exts is not None
        else f"UNAVAILABLE -- {SOURCE_EXT_OWNER_REL} not loadable"
    )
    known = src_exts or frozenset()
    report["evidence"] = {
        "source_ext_owner": owner,
        "source_ext_non_test": sorted(
            c.path for c in non_test if Path(c.path).suffix.lower() in known),
        "other_non_test": sorted(
            c.path for c in non_test if Path(c.path).suffix.lower() not in known),
        "note": (
            "BUCKETS, NOT A VERDICT. No rule here decides whether a non-source "
            "path owes a pin -- measured, none separates docs-only from an "
            "unpinned behaviour change on this repo. You judge."
        ),
    }

    if not test_paths:
        report["notes"].append(_ANALYTIC_ZERO_TEST_NOTE)

    if not non_test:
        report["verdict"] = NOT_APPLICABLE
        report["reason"] = (
            "the changed set contains no non-test files, so there is nothing to "
            "revert and the mechanic has no subject"
        )
        return report

    if not changes:
        report["verdict"] = NOT_APPLICABLE
        report["reason"] = "empty changed set"
        return report

    tmp_root = Path(tempfile.mkdtemp(prefix="verify-pins-"))
    clone = tmp_root / "clone"
    try:
        make_clone(repo, clone)
        if sha:
            _git_text(clone, "checkout", "-q", "--detach", report["subject"]["id"])
        else:
            apply_worktree_state(repo, clone, changes)

        # `Path("/tmp/clone") / "/abs/path"` DISCARDS the left operand, so an
        # absolute --carry made dest == src == the live path and the "clear the
        # destination first" rmtree deleted it FROM THE SOURCE REPO -- driven
        # 2026-08-21 in a throwaway clone: `--carry <abs>/reports` removed a
        # gitignored, git-unrecoverable directory and then crashed. --carry's
        # documented targets (`reports/`, `.espalier/`) are exactly the paths
        # git cannot restore. Normalise to repo-relative and confine both ends.
        repo_resolved, clone_resolved = repo.resolve(), clone.resolve()
        for given in carry or []:
            asked = Path(str(given).replace("\\", "/"))
            src = (asked if asked.is_absolute() else repo / asked).resolve()
            try:
                rel = str(src.relative_to(repo_resolved)).replace("\\", "/")
            except ValueError:
                raise VerifyPinsError(
                    f"--carry {given} resolves to {src}, which is OUTSIDE "
                    f"{repo_resolved}. Refusing: this argument names a path to "
                    f"copy FROM the repo INTO the clone, and an out-of-tree "
                    f"value has no meaning inside the clone. Pass a "
                    f"repo-relative path (e.g. --carry reports)."
                ) from None
            if not src.exists():
                report["notes"].append(f"--carry {rel}: absent in {repo}, skipped")
                continue
            dest = (clone / rel).resolve()
            if not dest.is_relative_to(clone_resolved):
                raise VerifyPinsError(
                    f"--carry {given} would write to {dest}, outside the clone."
                )
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            report["notes"].append(f"carried gitignored path into clone: {rel}")

        selection, notes = select_tests(clone, changes, roots, full, wide=wide)
        report["selection"] = selection
        report["notes"].extend(notes)

        if not selection:
            report["verdict"] = UNPINNED
            # The `--full` advice is right in ONE of the two ways to reach here
            # (test files changed but none is a selectable module -- a pin
            # through `tests/conftest.py` or `tests/_surface_expected.py`) and
            # WRONG in the other, where the ANALYTIC note above already states
            # that reverting reproduces the base tree byte-for-byte. Emitting
            # both sent 40% of commits to spend ~24 minutes reaching the
            # identical verdict, which is how a reader learns to stop reading.
            report["reason"] = (
                "the change touched no test module and no name-derived candidate "
                "(tests/test_<stem>.py) exists for any changed file -- so there "
                "is no test that could be the pin."
            ) + (
                " Re-run with --full if you believe a PRE-EXISTING test covers "
                "this." if test_paths else
                " --full CANNOT change this -- see the ANALYTIC note: reverting "
                "these files reproduces the base tree byte-for-byte."
            )
            return report

        if baseline:
            pre = run_pytest(clone, selection, timeout)
            report["baseline"] = {"rc": pre.rc, "failures": pre.failures}
            if pre.rc < 0:
                report["verdict"] = ERROR
                report["reason"] = (
                    f"the baseline pytest was KILLED BY SIGNAL {-pre.rc} with the "
                    f"change fully applied. That is a process death, not a red, "
                    f"and it says nothing about the selection. tail: {pre.tail}"
                )
                return report
            if pre.rc != 0:
                report["verdict"] = ERROR
                report["reason"] = (
                    "the selection was ALREADY RED with the change fully applied "
                    f"(rc={pre.rc}). A red after the revert could not be "
                    "attributed to the revert, so no verdict is honest here. "
                    f"Failures: {pre.failures or pre.tail}"
                )
                return report

        # `revert_only` restricts WHAT is put back; the SELECTION is still
        # derived from the whole change, which is the point of the leave-one-out
        # pass (see `per_file_probe`).
        revert_set = (
            non_test if revert_only is None
            else [c for c in non_test if c.path in set(revert_only)]
        )
        report["reverted"] = revert_to_base(repo, clone, base, revert_set)
        # The revert reconstructs a TREE. Until git's own metadata agrees with
        # it, the tree it reconstructs is not one git could produce -- see
        # `sync_git_metadata`.
        if sync_git_metadata(clone):
            report["notes"].append(
                "recorded the reverted tree as a commit so HEAD, the index and "
                "the worktree agree (git ls-files / git archive read the index)"
            )
        disagree = git_metadata_is_consistent(clone)
        if disagree:
            report["notes"].append(
                f"WARNING: git metadata still disagrees with the reverted tree "
                f"on {len(disagree)} path(s): {disagree[:8]}"
            )
        post = run_pytest(clone, selection, timeout)
        report["after_revert"] = {"rc": post.rc, "failures": post.failures}

        # A DEATH IS NOT A RED. `subprocess.run` returns a NEGATIVE rc when the
        # child dies by signal, and `if post.rc != 0` blessed that as PINNED --
        # while the baseline branch above turned the IDENTICAL event into ERROR.
        # The tool was asymmetric about the same fact: a runner death before the
        # revert refused to answer, a runner death after it was called a pin.
        # Reachable, and measured both ways on 2026-08-21: a real `--full` run
        # here returned rc=-9 (SIGKILL at ~76% of the suite), and driven
        # end-to-end through this CLI on a two-commit repo whose test SIGKILLs
        # itself, the verdict was `PINNED / reverting 1 non-test file(s) reddened
        # 1 test(s)` with `after_revert.failures == []` and not one RED line
        # printed. That count of 1 was manufactured by a `len(...) or 1`
        # fallback, so the report was confident, quantified, and unfalsifiable
        # from its own contents -- the worst shape a false pass can take.
        if post.rc < 0:
            report["verdict"] = ERROR
            report["reason"] = (
                f"the after-revert pytest was KILLED BY SIGNAL {-post.rc}. A "
                f"process death is not a red and cannot demonstrate a pin. "
                f"tail: {post.tail}"
            )
            return report
        if post.rc != 0 and not post.failures:
            report["verdict"] = ERROR
            report["reason"] = (
                f"the after-revert pytest exited rc={post.rc} without naming a "
                f"single failing test -- a usage error, a no-tests-collected, or "
                f"an interrupt. Refusing to call that a pin. tail: {post.tail}"
            )
            return report

        if post.rc != 0:
            report["verdict"] = PINNED
            report["reason"] = (
                f"reverting {len(revert_set)} non-test file(s) reddened "
                f"{len(post.failures)} test(s) that were green with the "
                f"change applied"
            )
        else:
            report["verdict"] = UNPINNED
            report["reason"] = (
                f"reverting {len(revert_set)} non-test file(s) left the selection "
                f"green (rc=0) -- delete the change and nothing notices"
            )
            if per_file and revert_only is None and len(non_test) > 1:
                report["per_file"] = per_file_probe(
                    repo, sha=sha, paths=[c.path for c in non_test],
                    baseline=baseline, carry=carry, timeout=timeout,
                    wide=wide, full=full,
                )
                hits = [r["path"] for r in report["per_file"] if r["verdict"] == PINNED]
                report["notes"].append(
                    f"PER-FILE: {len(hits)} of {len(non_test)} non-test file(s) red "
                    f"the selection when reverted ALONE: {hits}"
                    if hits else
                    f"PER-FILE: none of the {len(non_test)} non-test files reds the "
                    f"selection when reverted alone either"
                )
        return report
    except subprocess.TimeoutExpired:
        report["verdict"] = ERROR
        report["reason"] = f"pytest exceeded --timeout={timeout}s"
        return report
    except VerifyPinsError as exc:
        report["verdict"] = ERROR
        report["reason"] = str(exc)
        return report
    except Exception as exc:  # noqa: BLE001 - a crash must not become a verdict
        # The interface documents "advisory -- exit 0 whatever the verdict", and
        # only `VerifyPinsError`/`TimeoutExpired` were caught. Everything else
        # escaped as a raw traceback at exit 1, which under `--strict` is
        # byte-indistinguishable from a legitimate UNPINNED and under the
        # default violates the contract outright. Driven 2026-08-21: an absolute
        # `--carry` produced `RC=1` with no VERDICT line and no JSON at all.
        # Friction is this repo's high-severity class (FAILURE_MODES §C19) and a
        # tool that stack-traces on a docs commit is a tool that gets removed.
        report["verdict"] = ERROR
        report["reason"] = f"{type(exc).__name__}: {exc}"
        report["notes"].append(traceback.format_exc())
        return report
    finally:
        if keep:
            report["notes"].append(f"clone kept at {clone}")
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)


def per_file_probe(repo: Path, *, sha: str | None, paths: list[str],
                   **kw) -> list[dict]:
    """Revert each non-test file ALONE and report which ones red by themselves.

    WHY A WHOLE-CHANGE REVERT CAN MISS A REAL PIN. The default mechanic reverts
    every non-test file as one atom, so it only sees pins on ABSOLUTE content. A
    pin on a RELATION between two changed files is invariant under it by
    construction, and this repo's enforcement is heavily relational: nine
    byte-pinned mirror rows, generated-block parity, surface counts, tree-wide
    caps. Two real artifacts, both measured 2026-08-21:

      * `de32f81` raised `MAX_PRAGMA_COUNT` 6 -> 7 in the same commit that added
        the one new pragma. `sc.count_pragmas` is a TREE-WIDE count, so the
        whole-change revert drops the measurement and the threshold together and
        they cancel: 60 passed, rc=0, "delete the change and nothing notices".
        Reverting the scanner ALONE reds
        `test_pragma_count_within_cap` ("pragma count (7) exceeds cap (6)").
      * `3060e20` edited `.claude/agents/code-reviewer.md` and its two byte
        mirrors together. Reverting the mirror ALONE reds two
        `test_package_resource_parity.py` controls.

    THIS DELIBERATELY DOES NOT CHANGE THE VERDICT, and that restraint is the
    load-bearing part. "The SYNC of these files is pinned" is not "the CONTENT
    of this change is pinned" -- a parity test asserts the three sides agree,
    never what they say. Folding a per-file red into PINNED would flip
    `3060e20`, the discriminator this whole tool exists to produce, from UNPINNED
    to PINNED and collapse it against the working-tree control. Measured, not
    reasoned: the mirror leave-one-out above reds. So this reports, and the
    whole-change verdict stands.

    Opt-in (`--per-file`) because it costs one clone and up to two pytest runs
    per changed file.
    """
    out: list[dict] = []
    for path in paths:
        sub = verify(repo, sha=sha, revert_only=[path], **kw)
        out.append({
            "path": path,
            "verdict": sub["verdict"],
            "reason": sub["reason"][:200],
            "failures": (sub["after_revert"] or {}).get("failures", []),
        })
    return out


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def calibrate(repo: Path, count: int) -> list[dict]:
    """The measurement Step 1 of this tool's build rests on. Static only.

    Deliberately does NOT run pytest per commit: the point is the CHANGED-SET
    shape across a window, and a 20-commit x baseline+revert run is ~40 pytest
    invocations. Verdicts come from `--commit`, one at a time, on purpose.
    """
    roots = declared_test_roots(repo)
    src_exts = source_language_extensions(repo) or frozenset()
    rows: list[dict] = []
    shas = _git_text(repo, "log", "--format=%h", f"-{count}").split()
    for sha in shas:
        try:
            changes = commit_changes(repo, sha)
        except VerifyPinsError as exc:
            rows.append({"sha": sha, "error": str(exc)})
            continue
        tests = [c.path for c in changes if is_test_path(c.path, roots)]
        non_test = [c.path for c in changes if not is_test_path(c.path, roots)]
        rows.append({
            "sha": sha,
            "subject": _git_text(repo, "log", "-1", "--format=%s", sha).strip()[:52],
            "n_files": len(changes),
            "n_test": len(tests),
            "n_non_test": len(non_test),
            "n_src_ext_non_test": sum(
                1 for p in non_test if Path(p).suffix.lower() in src_exts),
            "exts": sorted({Path(c.path).suffix.lower() or "<none>" for c in changes}),
        })
    return rows


_EXPLAIN = """\
verify_pins -- what it cannot detect
====================================

1. A PIN THAT PASSES FOR THE WRONG REASON. A red is a red. If the reverted file
   makes an unrelated test explode on an import error, that reads as PINNED.
   Read `after_revert.failures` and judge whether the red is the RIGHT red --
   this tool tells you a test noticed, not that it noticed correctly.

2. PARTIAL COVERAGE. One red on a seven-file change reports PINNED. Six of the
   seven files can be unpinned inside a PINNED verdict. The verdict is per
   CHANGE, never per file or per claim.

3. WEAK ASSERTIONS. A test that reds when the file is deleted but would not red
   on a subtle regression still reports PINNED. This measures existence of a
   failure mode, not the assertion's sharpness.

4. DEFAULT SELECTION MISSES A PRE-EXISTING PIN. The default runs the change's
   own test modules plus name-derived candidates. A change pinned only by a
   test elsewhere in the suite reports UNPINNED. `--full` is the corrective and
   costs ~11.5 minutes PER SIDE on this repo.

   MEASURED 2026-08-21, because a corrective that is only recommended is not a
   corrective: the whole suite inside a fresh clone, in the environment this
   tool builds, is 8510 passed / 0 failed / rc=0 in 693.84s (11m33s). It was
   NOT green before the same day's fix -- 46 tests reddened, all of them
   because `run_pytest` SET `CLAUDE_PROJECT_DIR` to the clone, so `--full`
   could never return a verdict for any subject and limit 4 had no corrective
   at all. The redness was manufactured by this tool, not present in the repo.

   Honest edge on that number: the baseline was driven once, and end-to-end
   `--full` (~23 min for both sides) is driven by no control here -- only
   `select_tests(full=True)` is pinned. Treat the first `--full` run on a new
   machine as a measurement, not a given.

5. NO SEPARATOR FOR DOCS-ONLY CHANGES. Measured, none exists here (see the
   module docstring). Every docs-only commit reports UNPINNED. That is ~25% of
   this repo's recent commits, and it is why `--strict` must not go into CI.

   Related and larger: over the last 100 commits, ~40% have an EMPTY default
   selection and are auto-UNPINNED with no pytest run at all. Where the change
   touched no test file the ANALYTIC note says so and `--full` genuinely cannot
   help; where it did, `--full` is the corrective. The report now says which of
   the two you got instead of recommending `--full` in both.

11. A WHOLE-CHANGE REVERT CANCELS RELATIONAL AND TREE-WIDE PINS. Every non-test
   file is reverted as one atom, so only pins on ABSOLUTE content are visible.
   A pin on a RELATION between two changed files is invariant under it by
   construction -- and this repo's enforcement is heavily relational (nine
   byte-mirror rows, generated-block parity, surface counts, tree-wide caps).
   `de32f81` raised a cap in the same commit that added the thing being
   counted; the revert dropped both and they cancelled, so the tool printed
   "delete the change and nothing notices" about a change whose scanner edit
   reds `test_pragma_count_within_cap` when reverted ALONE.

   `--per-file` is the corrective: on a GREEN whole-change revert it reverts
   each non-test file by itself and reports which red alone. It never changes
   the verdict, and that restraint is deliberate -- "the SYNC of these files is
   pinned" is not "the CONTENT of this change is pinned", and folding the two
   together would flip `3060e20` (the discriminator this tool exists to
   produce) from UNPINNED to PINNED.

   KNOWN REMAINING GAP: `--per-file` can only red a test that is in the
   SELECTION, so it inherits limit 4. It recovers `de32f81`'s cap pin under
   `--wide`; it does NOT recover the mirror-parity pin on `3060e20`, because
   `tests/test_package_resource_parity.py` is neither name-derived nor a
   containment match for `code-reviewer.md`. Reading the mirror rows out of
   `espalier/mirror_registry.py` would close that, and was deliberately not
   done: it would put a hard `espalier` import into a script that accepts
   `--repo <any repo>`, and it would apply THIS repo's declared mirror families
   to a foreign tree.

12. A DEATH IS NOT A RED. A child pytest killed by a signal, or exiting
   non-zero without naming a failing test (usage error, no tests collected,
   interrupt), is reported ERROR on BOTH sides of the revert. It used to be
   ERROR before the revert and PINNED after it -- the same fact, two verdicts.

6. NON-PYTHON GATES ARE INVISIBLE. `ruff`, `espalier audit`, the CI workflows
   and the hook-level enforcement are all real pins this tool never runs. A
   change gated only by `ci_guard.py` reports UNPINNED.

7. FLAKES AND ORDER-DEPENDENCE. A single run each side. A test that fails
   intermittently reads as PINNED; a test that only fails in full-suite order
   reads as UNPINNED under the default selection.

8. GITIGNORED STATE IS ABSENT. `reports/`, `.espalier/` and any other
   gitignored path do not exist in the clone. A test that reads one either
   skips (the disciplined shape here) or errors -- and an error at baseline is
   reported as ERROR, not as a verdict. `--carry` is the escape hatch.

9. IT DOES NOT KNOW WHAT THE CHANGE CLAIMED. 24 fix claims across three commits
   became "did any test red". A change can be PINNED and still have nine of its
   ten prose claims unbacked.

10. MERGE COMMITS ARE REFUSED. 'The change' has no single parent to revert to.
"""


def _print_human(report: dict) -> None:
    subj = report["subject"]
    print(f"verify_pins: {subj.get('kind', '?')} {subj.get('id', '?')} "
          f"(base {subj.get('base', '?')})")
    if subj.get("subject_line"):
        print(f"  {subj['subject_line']}")
    print()
    print(f"  VERDICT: {report['verdict']}")
    print(f"  {report['reason']}")
    print()
    ch = report["changed"]
    print(f"  changed: {len(ch['non_test'])} non-test, {len(ch['test'])} test")
    ev = report.get("evidence") or {}
    if ev:
        n_src = len(ev.get("source_ext_non_test", []))
        n_all = n_src + len(ev.get("other_non_test", []))
        print(f"  evidence: {n_src} of {n_all} non-test paths carry a "
              f"source-language extension")
        print(f"            (owner: {ev.get('source_ext_owner')})")
        if ev.get("other_non_test"):
            print(f"            other: {', '.join(ev['other_non_test'][:6])}"
                  + (" ..." if len(ev["other_non_test"]) > 6 else ""))
        print(f"            {ev.get('note', '')}")
    if report["selection"]:
        print(f"  selection: {', '.join(report['selection'])}")
    if report.get("baseline"):
        print(f"  baseline rc={report['baseline']['rc']} "
              f"(with the change applied)")
    if report.get("after_revert"):
        ar = report["after_revert"]
        print(f"  after revert rc={ar['rc']}")
        for f in ar["failures"][:10]:
            print(f"    RED  {f}")
    for row in report.get("per_file") or []:
        mark = "PINNED-ALONE" if row["verdict"] == PINNED else row["verdict"]
        print(f"  per-file: {mark:<14} {row['path']}")
        for f in row["failures"][:3]:
            print(f"              RED  {f}")
    for note in report.get("notes", []):
        print(f"  note: {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revert a change's non-test files and check a test goes red.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Advisory by default: exit 0 whatever the verdict.",
    )
    parser.add_argument("--commit", metavar="SHA",
                        help="check one commit against its parent "
                             "(default: the working tree against HEAD)")
    parser.add_argument("--wide", action="store_true",
                        help="also select any test module whose stem CONTAINS a "
                             "changed file's stem -- the middle rung between the "
                             "default and --full (see select_tests)")
    parser.add_argument("--per-file", dest="per_file", action="store_true",
                        help="on a GREEN whole-change revert, also revert each "
                             "non-test file ALONE and report which red by "
                             "themselves -- catches relational pins (mirror "
                             "sync, tree-wide caps) that a whole-change revert "
                             "cancels. Reports; never changes the verdict.")
    parser.add_argument("--full", action="store_true",
                        help="run the whole suite instead of the change's own "
                             "tests + name-derived candidates (~11.5 min here)")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on UNPINNED, 2 on ERROR (NOT for CI here -- "
                             "see --explain limit 5)")
    parser.add_argument("--no-baseline", dest="baseline", action="store_false",
                        help="skip the pre-revert green check. Faster, and "
                             "unsound: a pre-existing red then reads as PINNED.")
    parser.add_argument("--carry", action="append", default=[], metavar="PATH",
                        help="copy a gitignored path into the clone (repeatable)")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="per-pytest-run timeout in seconds (default 1800)")
    parser.add_argument("--keep", action="store_true",
                        help="leave the clone on disk and print its path")
    parser.add_argument("--repo", default=str(REPO_DEFAULT),
                        help="repo root (default: this script's repo)")
    parser.add_argument("--calibrate", type=int, metavar="N", nargs="?", const=20,
                        help="print the static changed-set table for the last N "
                             "commits and exit (default 20)")
    parser.add_argument("--explain", action="store_true",
                        help="print what this tool cannot detect, and exit")
    args = parser.parse_args(argv)

    if args.explain:
        print(_EXPLAIN)
        return 0

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"verify_pins: {repo} is not a git repository", file=sys.stderr)
        return 2 if args.strict else 0

    if args.calibrate is not None:
        try:
            rows = calibrate(repo, args.calibrate)
        except VerifyPinsError as exc:
            print(f"verify_pins: {exc}", file=sys.stderr)
            return 2 if args.strict else 0
        if args.json:
            print(json.dumps({"calibration": rows}, indent=2))
            return 0
        print(f"{'sha':<10}{'files':>6}{'test':>6}{'nontest':>8}{'src-ext':>9}  "
              f"{'exts':<26}subject")
        for row in rows:
            if "error" in row:
                print(f"{row['sha']:<10}  {row['error']}")
                continue
            print(f"{row['sha']:<10}{row['n_files']:>6}{row['n_test']:>6}"
                  f"{row['n_non_test']:>8}{row['n_src_ext_non_test']:>9}  "
                  f"{','.join(row['exts']):<26}{row['subject']}")
        return 0

    report = verify(
        repo, sha=args.commit, full=args.full, baseline=args.baseline,
        carry=args.carry, timeout=args.timeout, keep=args.keep, wide=args.wide,
        per_file=args.per_file,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)

    if args.strict:
        if report["verdict"] == UNPINNED:
            return 1
        if report["verdict"] == ERROR:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
