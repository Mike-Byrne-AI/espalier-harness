"""The base branch's merge rules, read live from branch protection.

A written rule once said the up-to-date rule was on for a day after it had
been turned off, so the docs point at what GitHub answers instead of
restating the setting. Two readers
share this module: the SessionStart banner's ``Merging:`` line
(``hooks/session_start.py``) and the board (``board.py``).

One local git question (``origin/HEAD``, no network) and one bounded
``gh api`` read. Reporter-shaped: an answer it cannot read is no line, never a
guessed setting, and a read that did not answer in time says so. Stdlib-only, zero espalier imports; text is 7-bit ASCII.

The second half is what the rule being OFF leaves to the seats: a pull
request merges on its own green CI, which tested it merged with the base as
of its last push, so ``stale_base`` says when the base has moved
since then NEAR the pull request's files -- a path both changed, or a Python
module one import away from one -- and stays silent otherwise. The board and
``ship.py`` call it; the banner never does (its budget has no room for the
git reads).
"""
from __future__ import annotations

import json
import posixpath
import re
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

try:  # the bounded spawn beside this file; it is also loaded where that sibling is not importable
    from _json_safe import run_bounded
except ImportError:  # fail-open: ok deliberate -- tools/cc is not on sys.path (copied alone, or loaded by path): subprocess.run, a bound everywhere but Windows
    def run_bounded(
        args: Any, *, timeout: float | None = None, input: Any = None,
        capture_output: bool = False, check: bool = False, **kwargs: Any,
    ) -> "subprocess.CompletedProcess[Any]":
        """``subprocess.run``, read when called, so a replaced one is honoured as ``run_bounded`` honours it."""
        return subprocess.run(  # spawn: ok the bounded spawn's fallback where _json_safe.py is not importable
            args, timeout=timeout, input=input, capture_output=capture_output, check=check, **kwargs)

READ_CAP_SECONDS = 2.0       # one branch-protection read (measured 0.48 s median, 2026-10-09), never more
BASE_REF_CAP_SECONDS = 1.0   # the local origin/HEAD question, never more
#: ``read``'s returncode for a protection read that did not answer: killed at
#: its cap, or never started for want of time. ``line`` says so, and ``strict``
#: reads it as no answer, so nothing about merging is decided on it.
UNANSWERED = -2
#: ``read``'s returncode when git did not answer for the default branch's own
#: name, so no protection was asked: a ``main`` read in its place would print
#: another branch's rules as this one's.
BASE_UNANSWERED = -3


def _left(deadline: float | None, cap: float) -> float:
    return cap if deadline is None else min(cap, deadline - time.monotonic())


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _base_answer(root: Path, deadline: float | None) -> str | None:
    """``base_branch``'s answer, or None when git did not answer in time
    (killed at its cap, or no time left to ask)."""
    timeout = _left(deadline, BASE_REF_CAP_SECONDS)
    if timeout <= 0.2:
        return None
    try:
        result = run_bounded(  # spawn: ok a reporter: a git that cannot answer costs the base name, which falls back to main
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a read that did not answer is no name, never main: read() returns BASE_UNANSWERED and line() says so
        return None
    except (OSError, subprocess.SubprocessError):  # fail-open: ok text-fallback -- a git that cannot run reads as main, and a wrong guess prints no line
        return "main"
    name = result.stdout.strip() if result.returncode == 0 else ""
    return name.split("/", 1)[1] if name.startswith("origin/") and len(name) > len("origin/") else "main"


def base_branch(root: Path, deadline: float | None = None) -> str:
    """The remote's default branch, from the local ``origin/HEAD`` ref (no
    network); ``main`` when that ref is unset or cannot be read. The line names
    the branch it read, so a wrong default shows as a branch GitHub does not
    know, which prints no line rather than a wrong setting. A git that did not
    answer in time reads as ``main`` here too; ``read`` tells it apart
    (``BASE_UNANSWERED``), so a caller that prints the rules takes its base
    from ``read``."""
    return _base_answer(root, deadline) or "main"


def protection_endpoint(base: str) -> str:
    """The ``gh api`` path of ``base``'s required-status-checks protection."""
    return f"repos/{{owner}}/{{repo}}/branches/{urllib.parse.quote(base, safe='')}/protection/required_status_checks"


def read(root: Path, deadline: float | None = None, base: str | None = None) -> tuple[str, int, str]:
    """One ``gh api`` read of the base branch's required-status-checks
    protection: ``(base, returncode, stdout)``. GitHub answers an unprotected
    or unknown branch with HTTP 404 and a JSON message on stdout, and ``gh``
    exits 1, so stdout is kept whatever the exit code. Returncode -1 when the
    read could not be made (no ``gh``); ``UNANSWERED`` when it did not answer
    in time (killed at its cap, or no budget left to start it), and
    ``BASE_UNANSWERED`` with ``main`` when the default branch's name did not
    (no protection is asked then). ``base`` is the caller's when it already
    read it."""
    if not base:
        base = _base_answer(root, deadline)
        if base is None:
            return "main", BASE_UNANSWERED, ""
    timeout = _left(deadline, READ_CAP_SECONDS)
    if timeout <= 0.2:
        return base, UNANSWERED, ""
    try:
        result = run_bounded(  # spawn: ok a reporter: a gh that cannot run costs the merge-rules line; a missing gh is named by the load-bearing-tool warning
            ["gh", "api", protection_endpoint(base)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a read that did not answer is UNANSWERED, which line() says, never a guessed setting
        return base, UNANSWERED, ""
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a reporter that cannot run gh prints no merge-rules line, never a guessed setting
        return base, -1, ""
    return base, result.returncode, result.stdout


def line(base: str, returncode: int, stdout: str) -> str:
    """Whether a pull request must be caught up with ``base`` before it merges
    (the up-to-date rule, GitHub's ``strict``), and how many checks are
    required, as GitHub answered just now. An unprotected base says so, and so
    does a read that did not answer in time (``UNANSWERED``,
    ``BASE_UNANSWERED``): its silence would read as a branch with no rules
    this reader can see. Anything else (an unknown branch, a token without
    admin rights, a foreign shape, no ``gh``) is ``""``: the docs point here
    instead of restating the setting, so this must never print a guess."""
    if returncode == BASE_UNANSWERED:
        return ("merge rules unread: git gave no name for the remote's default branch in time "
                "(or no time was left to ask), so its branch protection was not asked")
    if returncode == UNANSWERED:
        return _ascii(f"{base}: merge rules unread (the branch-protection read gave no answer in time, "
                      "or no time was left to ask)")
    try:
        answer = json.loads(stdout or "")  # json-dict-safe: ok isinstance-checked on the next line before any deref
    except ValueError:  # fail-open: ok deliberate -- an unparseable answer prints no merge-rules line, never a guessed setting
        return ""
    if not isinstance(answer, dict):
        return ""
    if returncode == 0 and isinstance(answer.get("strict"), bool):
        checks = answer.get("checks")
        named = checks if isinstance(checks, list) else answer.get("contexts")
        count = len(named) if isinstance(named, list) else 0
        rule = ("ON: a pull request must be caught up with it before it merges" if answer["strict"]
                else "off: a pull request merges on its own green CI")
        return _ascii(f"{base}: up-to-date rule {rule}; {count} required checks (branch protection, read live)")
    if "not protected" in str(answer.get("message") or "").lower():
        return _ascii(f"{base}: not protected (no required checks, no up-to-date rule)")
    return ""


def strict(returncode: int, stdout: str) -> bool | None:
    """GitHub's ``strict`` (the up-to-date rule) from a ``read`` answer: True
    or False as GitHub said, None when the answer says neither (an unprotected
    base, an unknown branch, no read)."""
    try:
        answer = json.loads(stdout or "")  # json-dict-safe: ok isinstance-checked on the next line before any deref
    except ValueError:  # fail-open: ok deliberate -- no answer is no setting, never a guess
        return None
    if returncode == 0 and isinstance(answer, dict) and isinstance(answer.get("strict"), bool):
        return answer["strict"]
    return None


# ------------------------------------------------------------- stale base --

Runner = Callable[..., tuple[int, str, str]]

#: The longest import-line pattern the hop hands `git grep` (one alternation of
#: the other side's module names), well under Windows' 32767-character command
#: line; a wider change is judged by its paths alone and says so.
PATTERN_CAP = 16000
#: Conclusions of a run that tested nothing: cancelled by a newer run, or
#: skipped by a job-level `if`.
_TESTED_NOTHING = frozenset({"CANCELLED", "SKIPPED"})
#: An import statement's first line: `import a.b, c` or `from .x import y`.
#: Read line by line from `git grep`, so the names of a parenthesised import
#: that continue on later lines are not read (its module is).
_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)")
_FROM_RE = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+\(?\s*([\w\s,*]*)")


def tested_at(runs: object, head: str) -> str:
    """When GitHub fixed the base that ``head``'s CI tested: the newest run
    of each workflow on ``head`` (a re-run keeps its run's creation time and
    its test merge, so it never reads as fresher), then the OLDEST of those --
    the stalest workflow decides. ``createdAt`` is the event's time, when
    GitHub computed the test merge, not when a runner picked the job up. A
    run's own record does not keep the base it tested (``pull_requests`` is
    empty once the pull request merges, read 2026-10-10 on #170's runs), so
    the time is the oracle. "" when no run on ``head`` tested anything."""
    newest: dict[str, str] = {}
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict) or str(r.get("headSha") or "") != head:
            continue
        if str(r.get("conclusion") or "").upper() in _TESTED_NOTHING:
            continue
        name = str(r.get("workflowName") or r.get("name") or "?")
        at = str(r.get("createdAt") or "")
        if at and at > newest.get(name, ""):
            newest[name] = at
    return min(newest.values()) if newest else ""


def _git_lines(root: Path, run_: Runner, *args: str) -> list[str] | None:
    rc, out, _ = run_(["git", *args], cwd=str(root), timeout=30.0)
    return [ln for ln in out.splitlines() if ln.strip()] if rc == 0 else None


def _import_names(line: str) -> tuple[int, list[str]]:
    """``(level, names)`` for one import line: the dotted names it may load
    (for ``from m import a`` both ``m`` and ``m.a``, since ``a`` may be a
    submodule). Level is the leading dots of a relative import."""
    m = _FROM_RE.match(line)
    if m:
        level, module = len(m.group(1)), m.group(2)
        parts = [n.split() for n in m.group(3).split(",")]
        names = [p[0] for p in parts if p and p[0] != "*"]
        out = [module] if module else []
        out += [f"{module}.{n}" if module else n for n in names]
        return level, out
    m = _IMPORT_RE.match(line)
    if m:
        return 0, [part.split()[0] for part in m.group(1).split(",") if part.strip()]
    return 0, []


def _resolve(path: str, level: int, name: str, tree: set[str], by_stem: dict[str, list[str]]) -> list[str]:
    """The tree's files an import of ``name`` in ``path`` may load: relative
    to the file's own directory (a script that puts its directory on
    ``sys.path``, as every ``tools/cc`` script does), then from the root; a
    bare name found neither way matches every file of that stem (a test that
    inserts a script directory, then imports by stem)."""
    here = posixpath.dirname(path)
    if level:
        for _ in range(level - 1):
            here = posixpath.dirname(here)
        bases = [here]
    else:
        bases = [here, ""]
    rel = name.replace(".", "/")
    hits = []
    for base in bases:
        stem = posixpath.join(base, rel) if base else rel
        for cand in (stem + ".py", stem + "/__init__.py"):
            if cand in tree:
                hits.append(cand)
    if not hits and not level and "." not in name:
        hits = list(by_stem.get(name, []))
    return hits


def _module_name(path: str) -> str:
    """The last name an import of ``path`` spells: its stem, or for a
    package's ``__init__.py`` its directory's name."""
    base = posixpath.basename(path)[:-3]
    return posixpath.basename(posixpath.dirname(path)) if base == "__init__" else base


def _imports(root: Path, rev: str, side: set[str], targets: set[str], tree: set[str],
             run_: Runner) -> dict[str, set[str]] | None:
    """``{path: the targets it imports}`` for the Python files in ``side`` as
    they are at ``rev``. One ``git grep`` over the whole tree at ``rev`` for
    import lines naming any target's module name (no pathspec, so a wide change
    never meets the command-line limit), kept to ``side``'s files, then
    resolved. None when the names outgrow the pattern cap, or the grep fails."""
    names = sorted({n for n in (_module_name(t) for t in targets if t.endswith(".py")) if n.isidentifier()})
    py = {p for p in side if p.endswith(".py") and p in tree}
    if not names or not py:
        return {}
    pattern = r"^[[:space:]]*(import|from)[[:space:]].*(" + "|".join(names) + ")"
    if len(pattern) > PATTERN_CAP:
        return None
    rc, out, _ = run_(["git", "grep", "-I", "--null", "-E", pattern, rev], cwd=str(root), timeout=30.0)
    if rc not in (0, 1):   # 1 is "no line matched"
        return None
    by_stem: dict[str, list[str]] = {}
    for t in tree:
        if t.endswith(".py"):
            by_stem.setdefault(posixpath.basename(t)[:-3], []).append(t)
    found: dict[str, set[str]] = {}
    prefix = f"{rev}:"
    for raw in out.splitlines():
        # `<rev>:<path>\0<line>`: the path ends at the NUL, so a colon in it is safe.
        head, sep, line = raw.partition("\0")
        path = head[len(prefix):] if head.startswith(prefix) else head
        if not sep or path not in py:
            continue
        level, imported = _import_names(line)
        for name in imported:
            hits = {t for t in _resolve(path, level, name, tree, by_stem) if t != path} & targets
            if hits:
                found.setdefault(path, set()).update(hits)
    return found


def _tree(root: Path, run_: Runner, rev: str) -> dict[str, str] | None:
    """``{path: "<mode> <type> <object>"}`` for every file at ``rev``, from one
    ``ls-tree -r --full-tree`` (its paths from the top and quoted as ``diff
    --name-only`` gives them, from any directory, so the two compare); None
    when git could not list it."""
    lines = _git_lines(root, run_, "ls-tree", "-r", "--full-tree", rev)
    if lines is None:
        return None
    entries: dict[str, str] = {}
    for line in lines:
        meta, sep, path = line.partition("\t")
        if sep:
            entries[path] = meta
    return entries


def _alike(root: Path, run_: Runner, paths: set[str], *, tested: str, pr_rev: str,
           entries_now: dict[str, str] | None, entries_pr: dict[str, str] | None) -> set[str]:
    """The ``paths`` both sides changed that leave no meeting: the head and the
    base now hold the same entry (the same mode and blob, or none on either),
    and the base had not touched the path between the fork and ``tested``, so
    the CI merged the head's copy of it too and the landing holds what the CI
    tested. Empty wherever a read fails: a failed read keeps the meeting."""
    if not paths or entries_now is None or entries_pr is None:
        return set()
    same = {p for p in paths if entries_now.get(p) == entries_pr.get(p)}
    if not same:
        return set()
    fork = _git_lines(root, run_, "merge-base", tested, pr_rev)
    before = _git_lines(root, run_, "diff", "--name-only", "--no-renames", fork[0], tested) if fork else None
    return same - set(before) if before is not None else set()


def stale_base(root: Path, *, base_ref: str, tested_when: str, pr_paths: list[str], pr_rev: str,
               run_: Runner) -> dict:
    """Has ``base_ref`` moved near this pull request since its CI fixed the
    base it tested (``tested_when``, from ``tested_at``)? ``pr_paths`` are the
    paths the pull request changes; ``pr_rev`` is where to read their imports
    (its head, or the base when the head is not here). Returns ``{"tested",
    "now", "moved", "near", "unread"}``: ``moved`` counts the base's
    first-parent commits since, ``near`` names each meeting (a path both
    changed, or an import between a file each changed; a Python path both
    changed says in which function, from ``_symbol_clauses``), and ``unread``
    says what could not be read -- a read that failed is said, never a
    silent "fresh". A path both changed that the head and the base now hold
    alike (the same mode and blob, or absent on both) is no meeting where the
    head is here and the base left the path alone until the CI ran
    (``_alike``)."""
    out: dict = {"tested": "", "now": "", "moved": 0, "near": [], "unread": ""}
    now = _git_lines(root, run_, "rev-parse", "--verify", "-q", f"{base_ref}^{{commit}}")
    if not now:
        out["unread"] = f"{base_ref} is not here (fetch it)"
        return out
    out["now"] = now[0]
    if not tested_when:
        out["unread"] = "no run on the pull request's head tested anything yet"
        return out
    tested = _git_lines(root, run_, "rev-list", "--first-parent", "-1", f"--before={tested_when}", base_ref)
    if not tested:
        out["unread"] = f"no {base_ref} commit is older than the CI run ({tested_when})"
        return out
    out["tested"] = tested[0]
    if tested[0] == now[0]:
        return out
    count = _git_lines(root, run_, "rev-list", "--first-parent", "--count", f"{tested[0]}..{now[0]}")
    out["moved"] = int(count[0]) if count and count[0].isdigit() else 0
    changed = _git_lines(root, run_, "diff", "--name-only", "--no-renames", tested[0], now[0])
    if changed is None:
        out["unread"] = f"git diff {tested[0][:7]} {now[0][:7]} failed"
        return out
    # The head is here when pr_rev names a commit other than the base's: the
    # base read against itself agrees on every path and is no comparison.
    head = _git_lines(root, run_, "rev-parse", "--verify", "-q", f"{pr_rev}^{{commit}}")
    head_here = bool(head) and head[0] != now[0]
    entries_now = _tree(root, run_, now[0])
    entries_pr = _tree(root, run_, pr_rev) if head_here else entries_now
    # A path both changed that each side holds alike (one parked row folded, or
    # one old row pruned, on each) leaves both sides' paths, so it is neither a
    # meeting nor an end of an import hop.
    alike = _alike(root, run_, set(pr_paths) & set(changed), tested=tested[0], pr_rev=pr_rev,
                   entries_now=entries_now, entries_pr=entries_pr) if head_here else set()
    mine, theirs = set(pr_paths) - alike, set(changed) - alike
    both = sorted(mine & theirs)
    clauses = _symbol_clauses(root, both, base_ref=base_ref, tested=tested[0], now=now[0], pr_rev=pr_rev,
                              head_here=head_here, run_=run_)
    near = [f"{p} {clauses.get(p, '(both changed)')}" for p in both]
    tree_now = set(entries_now or {})
    tree_pr = (set(entries_pr or {}) | tree_now) if head_here else tree_now
    pr_imports = _imports(root, pr_rev, mine, theirs - mine, tree_pr, run_)
    base_imports = _imports(root, now[0], theirs - mine, mine, tree_now, run_)
    unread = [side for side, got in (("the pull request's", pr_imports), (f"{base_ref}'s", base_imports))
              if got is None]
    notes: list[str] = []
    if unread:
        notes.append(f"the import hop into {' and '.join(unread)} files was not read (their module names "
                     f"outgrow the {PATTERN_CAP}-character pattern, or git grep failed)")
    unlisted = [rev[:7] for rev, got in ((now[0], entries_now), (pr_rev, entries_pr if head_here else {}))
                if got is None]
    if unlisted:
        notes.append(f"git ls-tree failed at {' and '.join(unlisted)}, so the import hop may have missed "
                     "files there")
    if notes:
        out["unread"] = "; ".join(notes) + ": paths only"
    for path, targets in sorted((pr_imports or {}).items()):
        near += [f"{path} imports {t} (changed on {base_ref})" for t in sorted(targets)]
    for path, targets in sorted((base_imports or {}).items()):
        near += [f"{path} (changed on {base_ref}) imports {t}" for t in sorted(targets)]
    out["near"] = near
    return out


def _symbol_mapper() -> Any:
    """``tools/cc/_symbols.py``, imported where ``stale_base`` runs (the board
    and ship.py put this directory on the path); None where it cannot be,
    which the clause says. Imported here and not at the top: the banner loads
    this module by path alone and never calls ``stale_base``, so its
    ``Merging:`` line never depends on the mapper."""
    try:
        import _symbols
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate -- a missing or broken mapper: the clause says the symbols were not read, and why
        return None
    return _symbols


def _git_text(root: Path, run_: Runner, *args: str) -> str | None:
    rc, out, _ = run_(["git", *args], cwd=str(root), timeout=30.0)
    return out if rc == 0 else None


def _changed_in(root: Path, run_: Runner, mapper: Any, a: str, b: str, path: str) -> dict | None:
    """What ``a..b`` changed in ``path``, placed by the mapper (raw blobs, the
    mapper's own diff format); None where git could not answer."""
    diff = _git_text(root, run_, "diff", "-U0", *mapper.DIFF_ARGS, a, b, "--", path)
    if diff is None:
        return None
    old = _git_text(root, run_, "cat-file", "blob", f"{a}:{path}") or ""   # a file one side added
    new = _git_text(root, run_, "cat-file", "blob", f"{b}:{path}") or ""
    return mapper.changed_symbols(path, old, new, diff)


def _symbol_clauses(root: Path, paths: list[str], *, base_ref: str, tested: str, now: str, pr_rev: str,
                    head_here: bool, run_: Runner) -> dict[str, str]:
    """For each Python path both changed, what the catch-up will meet: the
    pull request's own diff (from its merge base with the base) against the
    base's moves since ``tested``, read by ``pair_verdict``: meeting at a
    symbol both change or one next to the other's change, different functions
    with none shared or next to the other's, or lines no node holds. Where the
    head is not here (``head_here``, ``stale_base``'s one reading of it), no
    function verdict: the base compared with itself is no comparison. A path
    that is not Python keeps its bare clause; a mapper that cannot be read, or
    a read that fails, costs this clause alone, never the verdict it
    decorates."""
    py = [p for p in paths if p.endswith(".py")]
    if not py:
        return {}

    def not_read(why: str) -> dict[str, str]:
        return {p: f"(both changed; symbols not read: {why})" for p in py}

    if not head_here:
        return not_read("head not here")
    out: dict[str, str] = {}
    try:
        mapper = _symbol_mapper()
        if mapper is None:
            return not_read("the symbol mapper (tools/cc/_symbols.py) is not importable here")
        fork = _git_lines(root, run_, "merge-base", now, pr_rev)
        if not fork:
            return not_read(f"no merge base of the head with {base_ref}")
        for path in py:
            lane = _changed_in(root, run_, mapper, fork[0], pr_rev, path)
            moved = _changed_in(root, run_, mapper, tested, now, path)
            if lane is None or moved is None:
                out[path] = "(both changed; symbols not read: git could not diff it)"
                continue
            verdict = mapper.pair_verdict({path: lane}, {path: moved})
            if verdict["verdict"] == "shared symbol":
                words = [mapper.mark_words(s, in_file=True) for s in verdict["shared"]]
                out[path] = f"(both changed, meeting at {', '.join(words)})"
            elif verdict["verdict"] == "different functions":
                out[path] = "(both changed, different functions, none shared or next to the other's)"
            else:
                out[path] = "(both changed, unplaced lines)"
    except Exception as exc:  # noqa: BLE001 -- fail-open with voice: the symbol reading is a clause on the verdict, never the verdict
        for path in py:
            out.setdefault(path, f"(both changed; symbols not read: {type(exc).__name__})")
    return out


def stale_line(result: dict, base: str, number: object = None) -> str:
    """The advisory for one ``stale_base`` result, or "" when the green
    stands: the base did not move, or moved away from this pull request's
    files and their imports. A read that failed is said, beside the meetings
    when there are some: a hop not read can hide another."""
    who = f"#{number}'s" if number is not None else "the pull request's"
    near = result.get("near") or []
    if not near:
        return _ascii(f"stale-base check not read for {who} CI: {result['unread']}") if result.get("unread") else ""
    shown = "; ".join(near[:3]) + (f"; and {len(near) - 3} more" if len(near) > 3 else "")
    also = f"; also, {result['unread']}" if result.get("unread") else ""
    return _ascii(f"{base} moved {result.get('moved')} merge(s) since {who} CI tested it on "
                  f"{str(result.get('tested') or '')[:7]}, near its files ({shown}): catch up "
                  f"(python tools/cc/ship.py catch-up) so CI tests the combination before it merges{also}")
