#!/usr/bin/env python3
"""Snapshot this repo's generated-knowledge surfaces onto an orphan git ref.

A governed repo generates a large body of knowledge that ``.gitignore``
deliberately keeps out of the tracked tree: session blueprints, task packs,
analysis reports, the session archive. Keeping it untracked is correct --
tracking it was measured and costs real test failures -- but the consequence
is that this knowledge exists on exactly one disk with no history.

This writes it to ``refs/heads/record``: an orphan branch that shares no
history with the working branch. Nothing in the harness or the test suite
reads that ref, which is precisely why it is free to carry. Each run adds a
snapshot as a child of the previous one, so the branch becomes a history of
the record rather than a single replaceable blob; git de-duplicates unchanged
blobs, so the marginal cost of a run is the delta, not the whole set.

The build uses a SEPARATE INDEX (``GIT_INDEX_FILE``) so the working branch's
index, ``HEAD`` and worktree are never touched. Older git has no
``worktree --orphan``, so this is the portable construction.

RESTORING: use ``git archive record | tar -x`` or ``git show record:<path>``.
Do NOT use ``git checkout record -- <path>`` -- that writes the file AND
stages it onto the working branch, silently growing the tracked set.

CONTENT EXCLUSIONS ARE NOT OPTIONAL BY DEFAULT. A record is append-only in
practice: ``git add -f`` takes an explicit list, so a path left out today can
be added tomorrow, but a path included today can never be withdrawn from a
pushed history. Anything sensitive must be excluded on the FIRST write. The
exclusion vocabulary lives in a gitignored config file rather than in this
source, because this file is tracked and would otherwise publish the very
strings it exists to withhold. If the config is absent the run REFUSES rather
than silently including everything -- a gate that passes when its own
configuration is missing is not a gate.

Usage:
    python3 scripts/record_snapshot.py --dry-run
    python3 scripts/record_snapshot.py
    python3 scripts/record_snapshot.py --verify
    python3 scripts/record_snapshot.py --no-content-exclusions
    python3 scripts/record_snapshot.py --exclude-patterns-file PATH
    python3 scripts/record_snapshot.py --audit-history
    python3 scripts/record_snapshot.py --json

Exit codes:
    0 = snapshot written / already current / --dry-run / --verify or
        --audit-history clean
    1 = script error (a bug)
    2 = REFUSED, or a check found something. Every operator-fixable condition
        lands here rather than as a traceback: exclusion config missing, empty,
        unreadable or holding an invalid regex; `record` checked out or not
        ours; --verify stale; --audit-history found withheld content in
        history. The stderr message names which.

Espalier-Harness self-host tooling. It lives in ``scripts/`` rather than
``tools/cc/`` for a mechanical reason worth recording: ``/handoff`` invokes it,
and that command body is byte-mirrored into the shipped assets, so a body that
runs an undeployed ``tools/cc/*.py`` sends every adopter to a
No-such-file (``tests/test_shipped_asset_md_refs.py`` pins exactly that). An
adopter repo has no ``scripts/``, so the same invocation is inert there instead
of broken -- the shape ``scripts/check_pack_landing.py`` already uses.

Stdlib-only; no espalier imports.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: Same resolver every sibling in ``scripts/`` uses. Deliberately NOT
#: ``tools/cc/_paths._repo_root`` -- that walks up for a marker pair because a
#: hook can be launched from any subdir, whereas a ``scripts/`` file is only
#: ever run from its own checkout. ``--repo-root`` overrides it for tests.
REPO_ROOT = Path(__file__).resolve().parent.parent

RECORD_REF = "refs/heads/record"

#: The remote the record branch is pushed to when no checkout-local setting
#: names one. Under DEC-31 the public checkout pushes its record to the private
#: archive, never to `origin`: the First-publish runbook sets
#: `git config --local espalier.recordRemote <name>` there and
#: `record_remote()` reads it. Local config is not cloned, which is right --
#: only the operator's checkout pushes the record -- and a worktree of that
#: checkout shares it (driven 2026-09-22 in a scratch repo: `git config --local`
#: inside a worktree reads and writes the main checkout's `.git/config` unless
#: `extensions.worktreeConfig` is set). `handoff_mechanics.after_goal` reads
#: the resolver once and uses its answer at the probe, the refusal text and the
#: push; the constant is never restated there.
RECORD_REMOTE_DEFAULT = "origin"
RECORD_REMOTE_CONFIG_KEY = "espalier.recordRemote"
#: TRACKED companion to the checkout-local key above, in espalier.toml: when
#: true, an UNSET key refuses instead of defaulting. The default is the
#: publishing direction -- on the public checkout `origin` IS the public repo,
#: and local config is never cloned, so every fresh clone starts unset. The
#: marker ships in the seed (espalier.toml is public), which is the half of the
#: fact that survives a clone; the key itself is set per checkout. Same
#: doctrine as `record_requires_exclusions` below (found by the failure-mode
#: review of 2026-09-22).
RECORD_REMOTE_REQUIRED_KEY = "record_remote_required"


def record_remote(root: Path) -> str:
    """The remote the record branch is pushed to.

    The checkout-local git config key when set and non-empty; else the default
    -- unless this repo's tracked config says the key is required
    (``record_remote_required = true`` in espalier.toml), in which case an
    unset key raises ``RecordError`` naming the exact line to run. Read under
    the clean git env so an ambient ``GIT_DIR`` cannot answer for a different
    repository. Only "key unset" (git exits 1) may fall to the default: any
    other failure raises, because the default is the publishing direction.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "config", "--local", "--get", RECORD_REMOTE_CONFIG_KEY],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=_clean_git_env(),
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    if proc.returncode not in (0, 1):
        raise RecordError(
            f"git config --local --get {RECORD_REMOTE_CONFIG_KEY} exited {proc.returncode} at "
            f"{root}: {proc.stderr.strip()[:200]} -- not falling back to {RECORD_REMOTE_DEFAULT!r}"
        )
    if _config_flag_is_true(root, RECORD_REMOTE_REQUIRED_KEY):
        raise RecordError(
            f"{RECORD_REMOTE_CONFIG_KEY} is not set in this checkout and espalier.toml requires it "
            f"({RECORD_REMOTE_REQUIRED_KEY} = true): the record branch must not default to "
            f"{RECORD_REMOTE_DEFAULT!r}. Run `git config --local {RECORD_REMOTE_CONFIG_KEY} <remote>` "
            f"-- the archive remote on the public checkout, {RECORD_REMOTE_DEFAULT} on the private "
            "tree -- then re-run."
        )
    return RECORD_REMOTE_DEFAULT

#: Provenance trailer. Distinguishes a commit THIS tool built from an unrelated
#: branch that happens to be named `record` -- without it the builder would
#: happily chain onto an adopter's own branch and move it.
RECORD_TRAILER = "Espalier-Record: v1"

#: Ambient git env that silently re-points every command at a DIFFERENT
#: repository. Set by `git bisect run`, `git rebase --exec`, and any hook, so a
#: handoff reached from inside one of those would read one tree and write the
#: ref into another -- reporting success. Stripped for every call here; the
#: scratch-index var is layered back on deliberately where it is wanted. Same
#: channel `tests/_git_oracle.py` closes for the test side.
_GIT_ENV_OVERRIDES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
)


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}

#: Where the record's content-exclusion patterns live. Gitignored, so the
#: vocabulary never enters tracked source. One extended-regex per line;
#: blank lines and ``#`` comments ignored.
DEFAULT_EXCLUDE_PATTERNS_REL = ".espalier/record_exclude_patterns.txt"

#: TRACKED companion to the gitignored vocabulary above, as a key in the repo's
#: own config. Names no patterns -- it asserts only that this repo HAS material
#: to withhold, which is the half of the fact that must survive a clone.
#:
#: Read by line-scan rather than a TOML parser: `tomllib` is 3.11+ and this
#: script targets the same floor as the rest of the harness. The cost is that a
#: MISTYPED key reads as absent, which re-permits the bypass -- so treat this as
#: defence-in-depth over the primary gate (a missing or empty vocabulary refuses
#: regardless), never as the thing standing between you and a leak.
REQUIRES_EXCLUSIONS_KEY = "record_requires_exclusions"
CONFIG_REL = "espalier.toml"


def _config_flag_is_true(repo_root: Path, key: str) -> bool:
    """``<key> = true`` on its own line in espalier.toml (line-scan, see above)."""
    cfg = repo_root / CONFIG_REL
    if not cfg.is_file():
        return False
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    for line in text.splitlines():
        bare = line.split("#", 1)[0].replace(" ", "").replace("\t", "")
        if bare == f"{key}=true":
            return True
    return False


def repo_requires_exclusions(repo_root: Path) -> bool:
    return _config_flag_is_true(repo_root, REQUIRES_EXCLUSIONS_KEY)

#: The declared knowledge surfaces. A positive list: the record is what these
#: roots contain, minus the subtractions below. Deriving the population by
#: walking declared roots keeps the list from drifting out of sync with a
#: hand-maintained copy of itself.
RECORD_ROOTS: tuple[str, ...] = (
    "cc/blueprints",
    "cc/GOAL.md",
    "cc/GOAL_OWED.json",
    "cc/finding_ledger.jsonl",
    "reports",
    "task-packs",
    "docs/session-archive.md",
    # NOT re-declared here: the fan-out findings corpus (docs/known-findings.md),
    # retired from the tracked tree 2026-09-21. An absent root adds nothing to a
    # snapshot and would sit in the absent-roots report forever, blunting the
    # one signal that catches a renamed root. Its last snapshot is b3e36ae;
    # read it with `git show b3e36ae:docs/known-findings.md`.
    "docs/blueprint-archive",
    "WINDOWS_FUSE_NOTES.md",
    "WALK2_FINDINGS.md",  # both walk files: memory/windows-walk-output-routing.md
    # Walk 3 (2026-09-14): the run sheet is the INSTRUMENT, not a journal --
    # it carries the corrected Leg 5 and every pre-registered oracle, and it
    # lived only as an untracked file in the walk worktree until now.
    "WALK3_RUN_SHEET.md",
    "WALK3_BRIEFING.md",
    "WALK3_PREFLIGHT_FINDINGS.md",
)

#: Paths inside the declared roots that are deliberately NOT record material.
#: Each is state or a mirror rather than knowledge: the surface handoff is
#: regenerated per session; the discard log is dominated
#: by machine-local absolute paths and dangling object ids; the working-summary
#: files are a rewritten mirror of the latest boundary, not the record itself.
DISQUALIFIED_PATHS: frozenset[str] = frozenset({
    "cc/SURFACE_HANDOFF.md",
    "cc/discard_snapshots.log",
})

#: Prefix form of the same rule, for the per-boundary working-summary mirrors
#: (``_working_summary.md`` plus any dated sibling).
DISQUALIFIED_PREFIXES: tuple[str, ...] = (
    "cc/_working_summary",
)

#: Runtime artifacts and OS debris that live inside the roots but carry no
#: knowledge: lock sentinels, resume ledgers, receipts, byte-compiled output.
JUNK_NAMES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db"})
JUNK_SUFFIXES: tuple[str, ...] = (".lock", ".pyc", ".pyo")
JUNK_PATH_PARTS: frozenset[str] = frozenset({"__pycache__"})


class RecordError(RuntimeError):
    """A refusal the caller should surface, not a crash."""


def _git(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run a git command in ``repo_root`` and return stdout, stripped."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        env=env if env is not None else _clean_git_env(),
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RecordError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def tracked_paths(repo_root: Path) -> set[str]:
    """Every path the working branch already tracks.

    The record exists for what the tracked tree does NOT carry, so a tracked
    path is excluded by definition. This is also what keeps the clean-restore
    property true: if every recorded path is ignored by the working branch,
    restoring the record into a clone leaves ``git status`` empty.
    """
    out = _git(repo_root, "ls-files", "-z")
    return {p for p in out.split("\0") if p}


def _is_junk(rel: str) -> bool:
    """Case-folded throughout: macOS and Windows resolve ``.DS_STORE`` and
    ``.DS_Store`` to the same file, so a case variation would otherwise walk
    straight past every predicate here."""
    low = rel.casefold()
    name = low.rsplit("/", 1)[-1]
    if name in {n.casefold() for n in JUNK_NAMES}:
        return True
    if name.startswith(".") and name.endswith(".lock"):
        return True
    if any(low.endswith(suffix) for suffix in JUNK_SUFFIXES):
        return True
    return bool({p.casefold() for p in JUNK_PATH_PARTS}.intersection(low.split("/")))


def _is_disqualified(rel: str) -> bool:
    """Case-folded for the same reason as :func:`_is_junk`."""
    low = rel.casefold()
    if low in {p.casefold() for p in DISQUALIFIED_PATHS}:
        return True
    return low.startswith(tuple(p.casefold() for p in DISQUALIFIED_PREFIXES))


def walk_roots(repo_root: Path, roots: tuple[str, ...] = RECORD_ROOTS) -> list[str]:
    """Repo-relative files under the declared roots, sorted. Absent roots are
    skipped: a root that does not exist yet is not an error, it is a surface
    this repo has not generated."""
    found: list[str] = []
    for root in roots:
        target = repo_root / root
        if target.is_file():
            found.append(root)
        elif target.is_dir():
            # espalier:safe-walk-ok declared knowledge roots inside this repo, never a handed-in adopter tree
            for path in target.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    found.append(path.relative_to(repo_root).as_posix())
    return sorted(set(found))


def absent_roots(repo_root: Path, roots: tuple[str, ...] = RECORD_ROOTS) -> list[str]:
    """Declared roots with nothing on disk behind them.

    ``walk_roots`` skips these by design -- a surface this repo has not
    generated yet is not an error. But the same silence covers a RENAMED or
    MISTYPED root: the run prints ``written``, the file leaves the record tip,
    and the next ``--verify`` goes clean again, so a durability guarantee is
    withdrawn without a word. The zero-file refusal only fires when EVERY root
    vanishes. Reporting the list costs nothing and makes the difference between
    "not generated yet" and "no longer reachable" the reader's call instead of
    the script's.
    """
    return sorted(r for r in roots if not (repo_root / r).exists())


def load_exclude_patterns(path: Path) -> list[str]:
    """Read one extended-regex per line; skip blanks and ``#`` comments.

    Every failure here is an OPERATOR-CONFIG error, not a bug, so each raises
    ``RecordError`` (exit 2) rather than escaping as a traceback (exit 1). A
    traceback at this step reads as "the harness is broken" when the true
    meaning is "your exclusion vocabulary is broken" -- and the second is
    something only the operator can fix.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordError(
            f"exclusion pattern file at {path} could not be read: {exc}"
        ) from exc
    patterns: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Compiled INDIVIDUALLY so a bad line names itself. Joined into one
        # alternation later, where a single syntax error would otherwise
        # disable every pattern at once.
        try:
            re.compile(stripped)
        except re.error as exc:
            raise RecordError(
                f"{path}:{lineno}: not a valid regex ({exc}): {stripped!r}. "
                "One bad line would disable the whole vocabulary, so this "
                "refuses rather than recording with partial exclusions."
            ) from exc
        patterns.append(stripped)
    return patterns


def content_excluded(
    repo_root: Path, rels: list[str], patterns: list[str]
) -> set[str]:
    """Paths whose CONTENT matches any exclusion pattern.

    Content-derived rather than a hand-listed file set: a hand list goes stale
    the moment the same material is quoted into a new file, and the failure is
    silent. Matching is case-insensitive. A file that cannot be read as text is
    excluded rather than admitted -- an unreadable file cannot be cleared.
    """
    if not patterns:
        return set()
    compiled = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    hits: set[str] = set()
    for rel in rels:
        try:
            text = (repo_root / rel).read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            hits.add(rel)
            continue
        # Matched against BOTH the raw text and a whitespace-collapsed shadow:
        # the record is hard-wrapped markdown and JSON, so a phrase can be
        # split mid-token across a line break and slip a raw search. This
        # narrows the miss window; it does not close it. Content matching
        # cannot catch a paraphrase, a re-encoding, or a token the vocabulary
        # does not name -- keep patterns token-level, and treat this as a
        # reduction of exposure rather than a proof of absence.
        if any(compiled.search(v) for v in (text, *_shadows(text))):
            hits.add(rel)
    return hits


def _shadows(text: str) -> tuple[str, str]:
    """Two wrap-tolerant views of ``text``, matched in addition to the raw.

    Both are needed and neither subsumes the other: collapsing runs to a single
    SPACE rejoins a phrase broken across a line (``"goes\npublic"`` ->
    ``"goes public"``); removing whitespace ENTIRELY rejoins a single token
    broken mid-word (``"tunnel-\ndashboard"`` -> ``"tunnel-dashboard"``), but
    would destroy any pattern containing a space. Shadow strings only -- never
    written anywhere.
    """
    ws = r"[\s\u200b-\u200d]+"
    return re.sub(ws, " ", text), re.sub(ws, "", text)


def build_add_list(
    repo_root: Path,
    patterns: list[str],
    roots: tuple[str, ...] = RECORD_ROOTS,
) -> tuple[list[str], dict]:
    """Derive the record's file list and a report of what each rule removed."""
    candidates = walk_roots(repo_root, roots)
    tracked = tracked_paths(repo_root)

    junk = {r for r in candidates if _is_junk(r)}
    remaining = [r for r in candidates if r not in junk]

    disqualified = {r for r in remaining if _is_disqualified(r)}
    remaining = [r for r in remaining if r not in disqualified]

    already_tracked = {r for r in remaining if r in tracked}
    remaining = [r for r in remaining if r not in already_tracked]

    carriers = content_excluded(repo_root, remaining, patterns)
    final = sorted(r for r in remaining if r not in carriers)

    report = {
        "candidates": len(candidates),
        "excluded_junk": sorted(junk),
        "excluded_disqualified": sorted(disqualified),
        "excluded_tracked": sorted(already_tracked),
        "excluded_by_content": sorted(carriers),
        "absent_roots": absent_roots(repo_root, roots),
        "included": len(final),
    }
    return final, report


def _write_tree(repo_root: Path, add_list: list[str]) -> str:
    """Stage ``add_list`` into a scratch index and return the tree object id.

    The scratch index is a temp file outside ``.git`` so a crashed run leaves
    no half-written index behind for the next one to inherit.
    """
    fd, index_path = tempfile.mkstemp(prefix="record-index-", suffix=".idx")
    os.close(fd)
    os.unlink(index_path)  # git wants to create it itself
    # Built from the CLEANED env, then the scratch index layered back on: a
    # plain dict(os.environ) would carry an ambient GIT_DIR/GIT_WORK_TREE
    # straight into `git add`, staging from -- and writing to -- a different
    # repository while every command still reports success.
    env = _clean_git_env()
    env["GIT_INDEX_FILE"] = index_path
    try:
        _git(repo_root, "read-tree", "--empty", env=env)
        # -f overrides .gitignore. Paths are passed after `--` and in batches
        # so a large record does not overflow the argument limit.
        batch = 500
        for i in range(0, len(add_list), batch):
            _git(repo_root, "add", "-f", "--", *add_list[i:i + batch], env=env)
        return _git(repo_root, "write-tree", env=env)
    finally:
        for leftover in (index_path, index_path + ".lock"):
            try:
                os.unlink(leftover)
            except OSError:
                pass


def current_record_tree(repo_root: Path) -> str | None:
    """The tree id of the existing record tip, or None if there is no ref."""
    try:
        return _git(repo_root, "rev-parse", f"{RECORD_REF}^{{tree}}")
    except RecordError:
        return None


def _record_tip(repo_root: Path) -> str | None:
    """The record tip commit id, or None if the ref does not exist."""
    try:
        return _git(repo_root, "rev-parse", f"{RECORD_REF}^{{commit}}")
    except RecordError:
        return None


def assert_ref_is_ours(repo_root: Path, adopt: bool = False) -> str | None:
    """Refuse to touch a ``record`` ref this tool did not build.

    Two distinct hazards, both measured:

    1. ``refs/heads/record`` may be somebody's ORDINARY branch that happens to
       share the name. Chaining onto it moves their branch and replaces its
       content with our tree -- and a later push publishes that. A commit we
       built carries :data:`RECORD_TRAILER`; one that does not is not ours.
    2. ``record`` may be the CHECKED-OUT branch. Then the index this tool reads
       for the already-tracked subtraction is the record's own file list, every
       candidate classifies as "already tracked", and the result is an empty
       snapshot committed onto the branch HEAD points at -- which moves HEAD's
       branch and stages the whole record onto the worktree.

    Returns the tip commit (or None for a fresh ref); raises on either hazard.
    """
    try:
        head_ref = _git(repo_root, "symbolic-ref", "-q", "HEAD")
    except RecordError:
        head_ref = ""  # detached HEAD is fine -- it is not the record branch
    if head_ref == RECORD_REF:
        raise RecordError(
            f"{RECORD_REF} is the CHECKED-OUT branch. Reading the index here "
            "would classify the record's own files as already-tracked and "
            "commit an empty snapshot over it, moving HEAD. Switch back to "
            "your working branch first (`git checkout -`)."
        )

    tip = _record_tip(repo_root)
    if tip is None:
        return None
    body = _git(repo_root, "log", "-1", "--format=%B", tip)
    if RECORD_TRAILER not in body and adopt:
        # Deliberate one-time adoption. Needed because the trailer was added
        # after the first records were written -- a guard introduced later than
        # the thing it guards will always refuse its own history, and refusing
        # forever is not a safe default either: it leaves the only durable copy
        # of that content unable to grow. Explicit by construction; never
        # automatic, or the check protects nothing.
        return tip
    if RECORD_TRAILER not in body:
        raise RecordError(
            f"{RECORD_REF} exists but its tip ({tip[:12]}) was not written by "
            f"this tool -- no `{RECORD_TRAILER}` trailer. It is probably an "
            "unrelated branch of the same name. Chaining onto it would move "
            "that branch and replace its content. Rename it, or delete the "
            "ref deliberately if it really is a stale record.\n"
            "If this ref IS an older record of yours, written before the "
            "trailer existed, re-run with --adopt-untrailered to chain onto it "
            "once; every commit after that carries the trailer."
        )
    return tip


def write_snapshot(
    repo_root: Path, add_list: list[str], message: str,
    adopt_untrailered: bool = False,
) -> tuple[str | None, str]:
    """Build the tree and, if it differs from the tip, commit and move the ref.

    Returns ``(commit_or_None, tree)``. A ``None`` commit means the tree was
    byte-identical to the current tip, so no empty commit was made -- running
    this on every session boundary should be free when nothing changed.
    """
    parent = assert_ref_is_ours(repo_root, adopt=adopt_untrailered)
    tree = _write_tree(repo_root, add_list)
    if tree == current_record_tree(repo_root):
        return None, tree

    if not add_list and parent is not None:
        raise RecordError(
            "refusing to record ZERO files over a non-empty history. An empty "
            "add-list on a repo that has recorded before means the roots "
            "stopped resolving, not that the knowledge was deleted."
        )

    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    args += ["-m", f"{message}\n\n{RECORD_TRAILER}"]
    commit = _git(repo_root, *args)
    # Compare-and-swap against the parent we read. A plain `update-ref` lets a
    # concurrent run's snapshot be silently overwritten -- both processes report
    # success and one history is orphaned (two sessions both reaching /handoff
    # is the realistic trigger).
    _git(repo_root, "update-ref", RECORD_REF, commit, parent or ("0" * 40))
    return commit, tree


def audit_history(repo_root: Path, patterns: list[str]) -> list[tuple[str, str]]:
    """Every (commit, path) in the record's whole history matching ``patterns``.

    The exclusion rule only binds at write time, but the vocabulary is mutable
    and history is not: material that looked clean under the vocabulary of the
    day stays permanently reachable, and a tip-only ``--verify`` reports the
    record as current while it does. This is the only way to know the
    "exclude on the FIRST write" rule was actually honoured -- run it before a
    first push, and after any widening of the vocabulary.
    """
    if not patterns or _record_tip(repo_root) is None:
        return []
    compiled = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    hits: list[tuple[str, str]] = []
    for commit in _git(repo_root, "rev-list", RECORD_REF).splitlines():
        listing = _git(repo_root, "ls-tree", "-r", commit)
        for row in listing.splitlines():
            meta, _, path = row.partition("\t")
            sha = meta.split()[2]
            try:
                blob = _git(repo_root, "cat-file", "blob", sha)
            except RecordError:
                continue
            if any(compiled.search(v) for v in (blob, *_shadows(blob))):
                hits.append((commit[:12], path))
    return hits


def _resolve_patterns(
    repo_root: Path, args: argparse.Namespace
) -> list[str]:
    # The vocabulary file is gitignored by design -- it names what must not be
    # published -- so it is absent on every machine but the one that wrote it.
    # This marker IS tracked and names nothing: it carries only the fact that a
    # vocabulary is required, which is the half that must survive a clone.
    # Without it, the first thing a second machine meets is the refusal below,
    # whose own advice (--no-content-exclusions) is the wrong move here.
    requires = repo_requires_exclusions(repo_root)

    if args.no_content_exclusions:
        if requires:
            raise RecordError(
                f"--no-content-exclusions refused: {CONFIG_REL} sets "
                f"{REQUIRES_EXCLUSIONS_KEY} = true, which records that this "
                "repo has material it must withhold. The vocabulary file itself is gitignored, so on a "
                "fresh clone you need a copy of it -- not a bypass. Recording "
                "unfiltered here would publish exactly what the marker exists "
                "to protect."
            )
        return []
    rel = args.exclude_patterns_file or DEFAULT_EXCLUDE_PATTERNS_REL
    path = Path(rel)
    if not path.is_absolute():
        path = repo_root / rel
    if path.is_file():
        patterns = load_exclude_patterns(path)
        if not patterns:
            raise RecordError(
                f"exclusion pattern file at {path} yields ZERO patterns "
                "(empty, or only blanks and comments).\n"
                "A present-but-empty vocabulary records EVERYTHING while "
                "looking configured, which is the failure this refusal exists "
                "to prevent -- absent and empty are the same gate.\n"
                "Add at least one pattern, or pass --no-content-exclusions to "
                "state deliberately that this repo has nothing to withhold."
            )
        return patterns
    raise RecordError(
            f"exclusion pattern file not found: {path}\n"
            "The record is effectively append-only -- a path included today "
            "cannot be withdrawn from a pushed history -- so this refuses "
            "rather than writing an unfiltered snapshot.\n"
            + ("Copy the vocabulary file from the machine that has it -- "
               f"{CONFIG_REL} records that this repo has material to "
               "withhold, so --no-content-exclusions is NOT the way out here."
               if requires else
               "Create the file (one regex per line), or pass "
               "--no-content-exclusions to state deliberately that this repo "
               "has nothing to withhold.")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot generated-knowledge surfaces onto an orphan git ref.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be recorded; write nothing")
    parser.add_argument("--verify", action="store_true",
                        help="exit 2 if the ref is missing or behind the tree")
    parser.add_argument("--audit-history", action="store_true",
                        help="apply the current patterns to EVERY blob in the "
                             "record's history; exit 2 on any hit")
    parser.add_argument("--no-content-exclusions", action="store_true",
                        help="declare that no content needs withholding")
    parser.add_argument("--exclude-patterns-file",
                        help=f"default: {DEFAULT_EXCLUDE_PATTERNS_REL}")
    parser.add_argument("--adopt-untrailered", action="store_true",
                        help="chain onto an existing record ref that predates "
                             "the provenance trailer (one-time, deliberate)")
    parser.add_argument("--message", help="commit message for this snapshot")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--repo-root", help="override repo root detection")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT

    try:
        patterns = _resolve_patterns(repo_root, args)
        add_list, report = build_add_list(repo_root, patterns)

        if args.audit_history:
            hits = audit_history(repo_root, patterns)
            result = {
                "action": "audit-history", "ref": RECORD_REF,
                "history_hits": [f"{c}:{p}" for c, p in hits], **report,
            }
            if hits:
                _emit(result, args.json)
                return 2
        elif args.dry_run:
            result = {"action": "dry-run", "ref": RECORD_REF, **report}
        elif args.verify:
            tree = _write_tree(repo_root, add_list)
            tip = current_record_tree(repo_root)
            stale = tree != tip
            result = {
                "action": "verify", "ref": RECORD_REF, "stale": stale,
                "tree": tree, "recorded_tree": tip, **report,
            }
            if stale:
                _emit(result, args.json)
                return 2
        else:
            message = args.message or f"record: snapshot of {report['included']} files"
            commit, tree = write_snapshot(
                repo_root, add_list, message,
                adopt_untrailered=args.adopt_untrailered,
            )
            result = {
                "action": "unchanged" if commit is None else "written",
                "ref": RECORD_REF, "commit": commit, "tree": tree, **report,
            }
    except RecordError as exc:
        print(f"record_snapshot: {exc}", file=sys.stderr)
        return 2

    _emit(result, args.json)
    return 0


def _emit(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print(f"record_snapshot: {result['action']} ({result['ref']})")
    print(f"  candidates {result['candidates']} -> included {result['included']}")
    for key, label in (
        ("excluded_junk", "junk/locks"),
        ("excluded_disqualified", "disqualified"),
        ("excluded_tracked", "already tracked"),
        ("excluded_by_content", "content-excluded"),
    ):
        items = result.get(key) or []
        if items:
            print(f"  {label}: {len(items)}")
            if key == "excluded_tracked":
                # Named, not counted: a declared root that becomes tracked is
                # dropped from the record tip while history keeps serving a
                # stale blob -- durability that reads healthy.
                for item in items:
                    print(f"    - {item}")
    absent = result.get("absent_roots") or []
    if absent:
        print(f"  absent roots: {len(absent)} (declared, nothing on disk)")
        for item in absent:
            print(f"    - {item}")
    if result.get("commit"):
        print(f"  commit {result['commit'][:12]}")
    if result.get("stale"):
        print("  STALE -- the ref does not match the current tree")
    if result.get("action") == "audit-history":
        hits = result.get("history_hits") or []
        if hits:
            print(f"  {len(hits)} withheld-content hit(s) IN HISTORY:")
            for h in hits[:20]:
                print(f"    {h}")
        else:
            print("  history clean against the current vocabulary")


if __name__ == "__main__":
    raise SystemExit(main())
