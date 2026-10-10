"""The base branch's merge rules, read live from branch protection.

A written rule once said the up-to-date rule was on for a day after it had
been turned off, so the docs point at what GitHub answers instead of
restating the setting. Two readers
share this module: the SessionStart banner's ``Merging:`` line
(``hooks/session_start.py``) and the board (``board.py``).

One local git question (``origin/HEAD``, no network) and one bounded
``gh api`` read. Reporter-shaped: anything it cannot read is no line, never a
guessed setting. Stdlib-only, zero espalier imports; text is 7-bit ASCII.

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
from typing import Callable

READ_CAP_SECONDS = 2.0       # one branch-protection read (measured 0.48 s median, 2026-10-09), never more
BASE_REF_CAP_SECONDS = 1.0   # the local origin/HEAD question, never more


def _left(deadline: float | None, cap: float) -> float:
    return cap if deadline is None else min(cap, deadline - time.monotonic())


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def base_branch(root: Path, deadline: float | None = None) -> str:
    """The remote's default branch, from the local ``origin/HEAD`` ref (no
    network); ``main`` when that ref is unset or cannot be read. The line names
    the branch it read, so a wrong default shows as a branch GitHub does not
    know, which prints no line rather than a wrong setting."""
    timeout = _left(deadline, BASE_REF_CAP_SECONDS)
    if timeout <= 0.2:
        return "main"
    try:
        result = subprocess.run(  # spawn: ok a reporter: a git that cannot answer costs the base name, which falls back to main
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok text-fallback -- an unanswered origin/HEAD reads as main, and a wrong guess prints no line
        return "main"
    name = result.stdout.strip() if result.returncode == 0 else ""
    return name.split("/", 1)[1] if name.startswith("origin/") and len(name) > len("origin/") else "main"


def protection_endpoint(base: str) -> str:
    """The ``gh api`` path of ``base``'s required-status-checks protection."""
    return f"repos/{{owner}}/{{repo}}/branches/{urllib.parse.quote(base, safe='')}/protection/required_status_checks"


def read(root: Path, deadline: float | None = None, base: str | None = None) -> tuple[str, int, str]:
    """One ``gh api`` read of the base branch's required-status-checks
    protection: ``(base, returncode, stdout)``. GitHub answers an unprotected
    or unknown branch with HTTP 404 and a JSON message on stdout, and ``gh``
    exits 1, so stdout is kept whatever the exit code. Returncode -1 when the
    read could not be made (no ``gh``, a timeout, no budget left). ``base`` is
    the caller's when it already read it."""
    base = base or base_branch(root, deadline)
    timeout = _left(deadline, READ_CAP_SECONDS)
    if timeout <= 0.2:
        return base, -1, ""
    try:
        result = subprocess.run(  # spawn: ok a reporter: a gh that cannot run costs the merge-rules line; a missing gh is named by the load-bearing-tool warning
            ["gh", "api", protection_endpoint(base)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- a reporter that cannot run gh prints no merge-rules line, never a guessed setting
        return base, -1, ""
    return base, result.returncode, result.stdout


def line(base: str, returncode: int, stdout: str) -> str:
    """Whether a pull request must be caught up with ``base`` before it merges
    (the up-to-date rule, GitHub's ``strict``), and how many checks are
    required, as GitHub answered just now. An unprotected base says so.
    Anything else (an unknown branch, a token without admin rights, a foreign
    shape, no read) is ``""``: the docs point here instead of restating the
    setting, so this must never print a guess."""
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


def stale_base(root: Path, *, base_ref: str, tested_when: str, pr_paths: list[str], pr_rev: str,
               run_: Runner) -> dict:
    """Has ``base_ref`` moved near this pull request since its CI fixed the
    base it tested (``tested_when``, from ``tested_at``)? ``pr_paths`` are the
    paths the pull request changes; ``pr_rev`` is where to read their imports
    (its head, or the base when the head is not here). Returns ``{"tested",
    "now", "moved", "near", "unread"}``: ``moved`` counts the base's
    first-parent commits since, ``near`` names each meeting (a path both
    changed, or an import between a file each changed), and ``unread`` says
    what could not be read -- a read that failed is said, never a silent
    "fresh"."""
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
    mine, theirs = set(pr_paths), set(changed)
    near = [f"{p} (both changed)" for p in sorted(mine & theirs)]
    tree_now = set(_git_lines(root, run_, "ls-tree", "-r", "--name-only", now[0]) or [])
    tree_pr = tree_now if pr_rev == now[0] else set(
        _git_lines(root, run_, "ls-tree", "-r", "--name-only", pr_rev) or []) | tree_now
    pr_imports = _imports(root, pr_rev, mine, theirs - mine, tree_pr, run_)
    base_imports = _imports(root, now[0], theirs - mine, mine, tree_now, run_)
    unread = [side for side, got in (("the pull request's", pr_imports), (f"{base_ref}'s", base_imports))
              if got is None]
    if unread:
        out["unread"] = (f"the import hop into {' and '.join(unread)} files was not read (their module names "
                         f"outgrow the {PATTERN_CAP}-character pattern, or git grep failed): paths only")
    for path, targets in sorted((pr_imports or {}).items()):
        near += [f"{path} imports {t} (changed on {base_ref})" for t in sorted(targets)]
    for path, targets in sorted((base_imports or {}).items()):
        near += [f"{path} (changed on {base_ref}) imports {t}" for t in sorted(targets)]
    out["near"] = near
    return out


def stale_line(result: dict, base: str, number: object = None) -> str:
    """The advisory for one ``stale_base`` result, or "" when the green
    stands: the base did not move, or moved away from this pull request's
    files and their imports. A read that failed is said."""
    who = f"#{number}'s" if number is not None else "the pull request's"
    near = result.get("near") or []
    if not near:
        return _ascii(f"stale-base check not read for {who} CI: {result['unread']}") if result.get("unread") else ""
    shown = "; ".join(near[:3]) + (f"; and {len(near) - 3} more" if len(near) > 3 else "")
    return _ascii(f"{base} moved {result.get('moved')} merge(s) since {who} CI tested it on "
                  f"{str(result.get('tested') or '')[:7]}, near its files ({shown}): catch up "
                  "(python tools/cc/ship.py catch-up) so CI tests the combination before it merges")
