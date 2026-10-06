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


#: One Windows Python Launcher version flag: ``-3``, ``-3.11``, ``-3.11-64``,
#: ``-3-32``. The launcher consumes it before the interpreter starts. A ``-2``
#: flag is the launcher's too, and is NOT recognised: it selects a Python 2,
#: which cannot parse the hooks, so ``py -2 <hook>`` must read as unwired.
#: The
#: ``-V:Company/Tag`` form is not recognised, so a site spelled that way reads
#: as not-a-launcher-spelling: a false negative, never a fail-open. The engine
#: home; ``tools/cc/hooks/_hook_utils.py`` and ``tools/cc/ci_guard.py`` hold
#: the twins the no-import boundary requires, pinned equal by
#: ``tests/test_python_floor.py::TestTwoCopyParity``.
LAUNCHER_VERSION_FLAG = re.compile(r"-3(\.\d+)?(-(32|64|arm64))?")


def is_python_launcher(token: str) -> bool:
    """True if ``token`` is the Windows Python Launcher, ``py`` or ``py.exe``,
    optionally a full path."""
    base = token.replace("\\", "/").rsplit("/", 1)[-1]
    base = base.lower()
    if base.endswith(".exe"):
        base = base[: -len(".exe")]
    return base == "py"


def interpreter_argv(spelling: str) -> list[str]:
    """The argv head an interpreter SPELLING runs as.

    ``"py -3"`` -> ``["py", "-3"]``: the launcher and the one version flag it
    consumes are two words, so a probe or an exec-form ``command`` needs them
    apart. Every other spelling is ONE word, unchanged -- a path with a space
    in it (``C:\\Program Files\\...\\python.exe``) included -- because only
    the launcher-plus-one-flag shape is split, at its last space.
    """
    # Split at the LAST space, so a launcher path that itself holds a space
    # (`C:/Program Files/.../py.exe -3`) still splits into its two words.
    head, _, flag = spelling.strip().rpartition(" ")
    head = head.rstrip()
    if head and is_python_launcher(head) and LAUNCHER_VERSION_FLAG.fullmatch(flag):
        return [head, flag]
    return [spelling]


#: What the start-up probe runs after an interpreter's argv head. ``-I`` is
#: isolated mode (no ``PYTHON*`` environment, no user site, no script
#: directory on ``sys.path``): settings.json outlives the shell that wrote it,
#: so an interpreter that starts only because this shell sets ``PYTHONHOME``
#: or ``PYTHONPATH`` is one the hooks cannot count on.
START_PROBE_ARGS: tuple[str, ...] = ("-I", "-c", "import sys")


def interpreter_start_failure(argv: "list[str] | tuple[str, ...]") -> str | None:
    """Why the interpreter at ``argv`` cannot start, or None when it can.

    ``argv`` is the resolved argv head: ``[path]``, or ``[launcher, "-3"]``
    for the launcher spelling. ``--version`` is answered before the
    interpreter initialises, so a banner is not a start: a copied virtualenv
    interpreter whose ``home`` names another virtualenv (``python -m venv
    --copies`` run from inside one on 3.10 writes exactly that) prints
    ``Python 3.10.x`` and then dies importing ``encodings``. Wired on its
    banner, every hook exits outside the ``{0, 2}`` the hook protocol reads as
    a decision, so every blocking guard fails open while ``init`` reports
    success. This runs :data:`START_PROBE_ARGS` with the banner probe's
    two-second timeout and returns a clause for a sentence ("cannot start:
    ..."), naming the exit status and the last line the interpreter printed.

    The verdict is the exit status, never the text, so the text is decoded
    with replacement: a failing interpreter's path dump may not be UTF-8, and
    a decode error must not turn a working interpreter into a refused one.

    The interpreter running this process demonstrably started, so a one-word
    ``argv`` that is the very PATH ``sys.executable`` was started as is
    answered without a spawn. The PATH, not the file: whether an interpreter
    starts depends on where it is invoked from (its ``pyvenv.cfg`` and
    ``home``), so the identity probe's ``samefile`` would pass a broken venv
    whose ``python`` is a symlink or a hardlink to the running binary -- the
    trap this probe exists for, made by symlink instead of ``--copies``. Not
    when this shell sets ``PYTHONHOME`` or ``PYTHONPATH`` either: those are
    what ``-I`` drops, so "it started here" no longer answers "it starts for a
    hook". The floor is still read off the banner by every caller; this
    answers only whether the interpreter starts.

    A probe that TIMES OUT is run once more before it counts: a shim that is
    slow once (pyenv or asdf on a loaded box, a first-run scan) would
    otherwise turn a working interpreter into a refused one, which is the
    flake the enforcement claim's identity arm already retries. An exit
    status is not retried; it does not flake.
    """
    import os
    import subprocess
    import sys
    rescued = os.environ.get("PYTHONHOME") or os.environ.get("PYTHONPATH")
    if len(argv) == 1 and sys.executable and not rescued:
        def _as_invoked(path: str) -> str:
            return os.path.normcase(os.path.abspath(path))
        if _as_invoked(argv[0]) == _as_invoked(sys.executable):
            return None
    result = None
    for _attempt in (1, 2):
        try:
            result = subprocess.run(
                [*argv, *START_PROBE_ARGS], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=2,
            )
        except subprocess.TimeoutExpired:
            continue
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            return f"cannot start: the start-up probe raised {type(exc).__name__}"
        break
    if result is None:
        return "cannot start: the start-up probe timed out twice (2 s each)"
    if result.returncode == 0:
        return None
    said = [
        line.strip()
        for line in (result.stderr or result.stdout or "").splitlines()
        if line.strip()
    ]
    tail = said[-1][:200] if said else "no output"
    return (
        f"cannot start: `-I -c 'import sys'` exits {result.returncode} ({tail})"
    )


def interpreter_meets_floor(name_or_path: str | None) -> bool:
    """Does the interpreter named by ``name_or_path`` clear :data:`MIN_PYTHON`,
    and start?

    Resolves the name on PATH, runs ``--version``, reads it, and when the
    banner clears the floor runs :func:`interpreter_start_failure`: a banner
    is answered before the interpreter initialises, and every caller of this
    is deciding whether to WIRE or TRUST an interpreter (the resolver's
    launcher branch, the rewire's target and its staleness test, doctor's
    floor check, the remedy spelling), where one that cannot start disarms
    every guard. The single engine-side implementation --
    ``doctor._interpreter_meets_floor`` delegates here and exists only as a
    monkeypatch seam, and ``cli`` calls this directly rather than growing a
    third copy. ``_hook_utils.interpreter_meets_floor`` is its twin across the
    no-import boundary for the banner and does NOT run the start-up probe: it
    serves hook-side warnings and remedy hints, not wiring, where the wired
    interpreter it is usually asked about is the one running the hook, and a
    spawn there is paid on every SessionStart. Its other askers (the
    ``python3``/``python``/``py -3`` a hint spells) are the one gap left.

    ⚠ No ``samefile(sys.executable)`` short-circuit, unlike the IDENTITY probes.
    That shortcut is sound for "is this a Python 3" -- the process asking
    demonstrably is one -- but it cannot answer the floor question without
    assuming its own answer, and a 3.9 host is exactly where it would be asked.
    (The start-up probe skips a spawn for the running interpreter's own path,
    for the start question only: the version is still read here.)

    False for an unresolvable name, a non-interpreter, a probe that cannot
    run, or an interpreter that cannot start: an unreadable answer is not a
    passing one. A launcher spelling (``py -3``) is probed as the launcher
    with its flag: resolved whole, the two words named nothing and a working
    launcher read as absent.
    """
    if not name_or_path:
        return False
    import shutil
    import subprocess
    from pathlib import Path as _Path
    head, *flags = interpreter_argv(name_or_path)
    resolved = shutil.which(head) or (
        head if _Path(head).is_file() else None
    )
    if not resolved:
        return False
    try:
        result = subprocess.run(
            [resolved, *flags, "--version"], capture_output=True, text=True,
            encoding="utf-8", timeout=2,
        )
    except (subprocess.SubprocessError, OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return False
    if not meets_python_floor((result.stdout or result.stderr).strip()):
        return False
    return interpreter_start_failure([resolved, *flags]) is None


def floor_text() -> str:
    """``"3.10"`` -- for interpolation into operator-facing messages.

    One renderer, so a message can never quote a floor the code does not
    enforce. Every emitted string naming the minimum reads it from here rather
    than spelling it, which is the ``DEF-410a`` shape one level up.
    """
    return ".".join(str(part) for part in MIN_PYTHON)
