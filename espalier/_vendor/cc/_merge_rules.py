"""The base branch's merge rules, read live from branch protection.

A written rule once said the up-to-date rule was on for a day after it had
been turned off, so the docs point at what GitHub answers instead of
restating the setting. Two readers
share this module: the SessionStart banner's ``Merging:`` line
(``hooks/session_start.py``) and the board (``board.py``).

One local git question (``origin/HEAD``, no network) and one bounded
``gh api`` read. Reporter-shaped: anything it cannot read is no line, never a
guessed setting. Stdlib-only, zero espalier imports; text is 7-bit ASCII.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from pathlib import Path

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
    endpoint = f"repos/{{owner}}/{{repo}}/branches/{urllib.parse.quote(base, safe='')}/protection/required_status_checks"
    try:
        result = subprocess.run(  # spawn: ok a reporter: a gh that cannot run costs the merge-rules line; a missing gh is named by the load-bearing-tool warning
            ["gh", "api", endpoint],
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
