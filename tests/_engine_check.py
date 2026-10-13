"""Stop a test session whose interpreter imports another tree's engine.

Fifteen-odd call sites in this suite spawn ``[sys.executable, "-m", "espalier",
...]``, and many more spawn the CLI through an ``init`` or an ``upgrade``.
Each child imports whichever ``espalier`` that interpreter resolves, not the
package beside these tests. On 2026-10-12 this box's editable install named
the main checkout, so a worktree seat's full tier ran the main checkout's
engine in every one of those tests and passed: green, about the wrong code.
The SessionStart ``Engine:`` line is the early notice, but it can only guess
the interpreter from the PATH Claude Code was launched with; this check asks
the interpreter that is really running, before any test runs.

Silent when the answer is this tree's ``espalier/`` (every CI job installs
its checkout editable), on a tree with no engine source, and when the
interpreter cannot answer (a session that cannot import ``espalier`` fails
loudly on its own). The remedy it names is a ``.venv`` of the checkout's own,
never a global ``PYTHONPATH``: the wheel and fresh-clone tests build venvs of
their own, and an inherited ``PYTHONPATH`` would point those at the source
tree and turn them into false greens.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

#: Where ``espalier`` would come from, asked without importing it.
PROBE = ("import importlib.util as u; s = u.find_spec('espalier'); "
         "print(s.origin if s and s.origin else '')")


def foreign_engine(repo_root: Path, *, executable: str | None = None,
                   env: dict[str, str] | None = None, timeout: float = 30.0) -> str | None:
    """The message to stop the session with, or None when the interpreter's
    ``espalier`` is this tree's (or it cannot say). Asked from a fresh empty
    directory, so neither the cwd nor this process's sys.path answers for the
    child; the last line of its output, so a shim that prints at start is no
    false alarm."""
    exe = executable or sys.executable
    own = repo_root / "espalier"
    if not (own / "__init__.py").is_file():
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="espalier-engine-check-") as neutral:
            done = subprocess.run([exe, "-c", PROBE], cwd=neutral, env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                  check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]
    origin = lines[-1] if lines else ""
    if done.returncode != 0 or not origin.endswith("__init__.py") or not Path(origin).is_absolute():
        return None
    found = Path(origin).parent
    try:
        if os.path.samefile(found, own):
            return None
    except OSError:
        pass
    bindir = Path(".venv") / ("Scripts" if os.name == "nt" else "bin")
    return (
        f"this test session's interpreter ({exe}) imports espalier from {found}, not from this "
        f"checkout ({repo_root}): every test that spawns the CLI would run that engine and pass "
        "about the wrong code. Run the suite with an interpreter whose espalier is this checkout: "
        f"a .venv of its own (`uv venv .venv`, then `uv pip install --python {bindir / 'python'} "
        f"-e '.[dev]'` here) with {bindir} first on PATH. Not a global PYTHONPATH: the wheel and "
        "fresh-clone tests build venvs of their own and would inherit it. No test ran."
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Once, on the controller (an xdist worker inherits its answer), before
    collection: stop when the running interpreter imports another engine."""
    if hasattr(session.config, "workerinput"):
        return
    problem = foreign_engine(Path(__file__).resolve().parent.parent)
    if problem:
        pytest.exit(problem, returncode=4)
