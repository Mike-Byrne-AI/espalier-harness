"""The minimum Python this package runs on, and the one parser that reads it.

``pyproject.toml`` declares ``requires-python = ">=3.10"``. Nothing enforced
it before this module existed: three interpreter probes tested only
``.startswith("Python 3.")``, so on a host whose ``python3`` is stock
``/usr/bin/python3`` -- 3.9.6 on every macOS through Sequoia -- ``init`` wrote
that name into 13 hook-command sites, ``doctor`` reported the resolver healthy,
and the hooks ran. What did NOT run was ``tools/cc/cognitive_blueprint.py``,
whose ``match args.action:`` is 3.10+ syntax: the blueprint chain, Gate 4
finalize and subagent-reasoning capture raised SyntaxError every session while
every blocking guard kept working -- so nothing visibly failed and SessionStart
said "No active blueprint" forever.

**Identity and capability are different questions, and this module answers the
second.** "Does this name answer as a Python 3 at all?" -- asked of a PATH name,
by spawning it -- stays with ``doctor._interpreter_is_python3`` /
``_hook_utils.interpreter_is_python3``, because reporting ``python3=no`` for a
working 3.9 would put a false host fact into the orientation line -- the exact
error those probes were built to stop. Both probes read the banner they get
back through :func:`is_python3_banner` (or its hook-side parity twin), the ONE
rule for what a Python 3 banner is, so identity and the floor cannot disagree
about a banner. This module answers "does it clear the floor the package
declares?", which is the question every WRITE decision needs: which interpreter
to wire into settings.json, and whether an already-wired one should be trusted.
It also names the gap between the two, read off a banner the caller already
holds: :func:`is_below_floor_python3` is "a Python 3 that fails the floor", the
state ``cli`` wires with a warning -- and the state a parse-succeeds gate once
let a Python 2 banner into (``DEF-727``).

⚠ ``MIN_PYTHON`` is duplicated in ``tools/cc/hooks/_hook_utils.py`` because
``tools/cc/`` may not import espalier, and it cannot be derived from
``pyproject.toml`` at runtime: the hooks run inside an ADOPTER's tree, where the
only ``pyproject.toml`` is the adopter's own and says nothing about espalier's
floor. The two copies are parity-pinned by
``tests/test_python_floor.py::TestTwoCopyParity``; this copy is pinned to
``pyproject.toml`` by
``tests/test_python_floor.py::TestPythonFloor::test_min_python_matches_requires_python``.
Follows the ``decode_bom`` three-copy precedent: duplicated logic in this repo
gets a parity test, not a note asking a future reader to remember.
"""
from __future__ import annotations

import re

#: The floor ``pyproject.toml`` declares. Parity-pinned twin in
#: ``tools/cc/hooks/_hook_utils.py``; keep both in step with ``requires-python``.
MIN_PYTHON: tuple[int, int] = (3, 10)

# `python --version` prints `Python 3.14.0`; older builds print it to stderr,
# which is why every caller passes `stdout or stderr`. Tolerate a missing patch
# level (`Python 3.10`), a pre-release suffix (`Python 3.14.0rc1`), and leading
# whitespace. Anything else is not a version banner.
_VERSION_RE = re.compile(r"Python\s+(\d+)\.(\d+)")


def parse_python_version(version_output: str) -> tuple[int, int] | None:
    """``(major, minor)`` from ``python --version`` output, or None.

    None for anything that is not a Python version banner -- empty output, a
    shell error, the output of a resolving non-interpreter such as a Microsoft
    Store App Execution Alias. Callers treat None as "does not clear the floor",
    never as "assume it is fine": an unreadable answer is the case this module
    exists for.
    """
    if not version_output:
        return None
    match = _VERSION_RE.search(version_output)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def meets_python_floor(version_output: str) -> bool:
    """True when ``version_output`` reports at least :data:`MIN_PYTHON`.

    ``Python 3.9.6`` is False -- that is the whole point, and the case all three
    predecessor probes accepted. ``Python 2.7.18`` is False, unreadable output
    is False, and a future major (``Python 4.0``) is True: a floor is a floor,
    and refusing an interpreter for being too NEW would be a fail-closed
    invented to serve the fix rather than the adopter.
    """
    parsed = parse_python_version(version_output)
    return parsed is not None and parsed >= MIN_PYTHON


def is_python3_banner(version_output: str) -> bool:
    """True when ``version_output`` is a Python 3 version banner: identity, read
    off the banner's MAJOR.

    ONE rule for the question. The PATH-probing identity probes
    (``doctor._interpreter_is_python3`` and its ``_hook_utils`` twin) read their
    ``--version`` output through this or its parity twin, and
    :func:`is_below_floor_python3` is defined from it. Before it existed the
    probes tested ``startswith("Python 3.")`` on the stripped output while the
    floor parser searched anywhere in it, so a banner with a line before it (a
    wrapper that echoes, a sitecustomize notice) read as a Python 3 to the floor
    and as not one to identity -- and ``init`` said "the blocking guards keep
    working" and "each guard fails OPEN" about the same interpreter in one run
    (driven by the ``DEF-727`` failure-mode review). ``Python 4.0`` is not a
    Python 3 under either reading; the floor decides what to do with it.
    """
    parsed = parse_python_version(version_output)
    return parsed is not None and parsed[0] == 3


def is_below_floor_python3(version_output: str) -> bool:
    """True when ``version_output`` reports a Python 3 that fails :data:`MIN_PYTHON`.

    The third state between "clears the floor" and "not a Python 3 at all", and
    the one both of ``cli``'s wiring decisions need by name: a WORKING Python 3
    that is merely too OLD runs the blocking guards and loses only the blueprint
    chain, so it is wired with a warning that says exactly that. ``Python
    2.7.18`` is NOT this state. It parses, and a gate written as
    ``parse_python_version(...) is not None`` admitted it here (``DEF-727``,
    driven on a real Windows host): the operator was promised working guards on
    the one interpreter that cannot parse the hook scripts at all, so every
    guard failed OPEN under a banner saying they were live. Identity is read
    off the banner's MAJOR (:func:`is_python3_banner`), never off whether the
    banner parsed.
    """
    return is_python3_banner(version_output) and not meets_python_floor(version_output)


def interpreter_meets_floor(name_or_path: str | None) -> bool:
    """Does the interpreter named by ``name_or_path`` clear :data:`MIN_PYTHON`?

    Resolves the name on PATH, runs ``--version``, and reads it. The single
    engine-side implementation -- ``doctor._interpreter_meets_floor`` delegates
    here and exists only as a monkeypatch seam, and ``cli`` calls this directly
    rather than growing a third copy. Symmetric with
    ``_hook_utils.interpreter_meets_floor`` across the no-import boundary.

    ⚠ No ``samefile(sys.executable)`` short-circuit, unlike the IDENTITY probes.
    That shortcut is sound for "is this a Python 3" -- the process asking
    demonstrably is one -- but it cannot answer the floor question without
    assuming its own answer, and a 3.9 host is exactly where it would be asked.

    False for an unresolvable name, a non-interpreter, or a probe that cannot
    run: an unreadable answer is not a passing one.
    """
    if not name_or_path:
        return False
    import shutil
    import subprocess
    from pathlib import Path as _Path
    resolved = shutil.which(name_or_path) or (
        name_or_path if _Path(name_or_path).is_file() else None
    )
    if not resolved:
        return False
    try:
        result = subprocess.run(
            [resolved, "--version"], capture_output=True, text=True,
            encoding="utf-8", timeout=2,
        )
    except (subprocess.SubprocessError, OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return False
    return meets_python_floor((result.stdout or result.stderr).strip())


def floor_text() -> str:
    """``"3.10"`` -- for interpolation into operator-facing messages.

    One renderer, so a message can never quote a floor the code does not
    enforce. Every emitted string naming the minimum reads it from here rather
    than spelling it, which is the ``DEF-410a`` shape one level up.
    """
    return ".".join(str(part) for part in MIN_PYTHON)
