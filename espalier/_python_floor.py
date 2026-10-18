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

    A ``version_output`` of None raises TypeError: it is what
    :func:`interpreter_banner` returns for a probe that never answered
    (``DEF-5015``), no answer either way, and read here it would be refused in
    silence, the defect that row closed. Every reader tests for None first.
    """
    if version_output is None:
        raise TypeError(
            "a banner probe that never answered (None) is no answer either way; "
            "test for it before reading a version from it (DEF-5015)")
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
    success. This runs ``-I -c 'import sys'`` after ``argv`` with the banner
    probe's two-second timeout and returns a clause for a sentence ("cannot
    start: ..."), naming the exit status and the last line the interpreter
    printed. ``-I`` is isolated mode (no ``PYTHON*`` environment, no user
    site, no script directory on ``sys.path``): settings.json outlives the
    shell that wrote it, so an interpreter that starts only because this
    shell sets ``PYTHONHOME`` or ``PYTHONPATH`` is one the hooks cannot count
    on.

    The verdict is the exit status, never the text, so the text is decoded
    with replacement: a failing interpreter's path dump may not be UTF-8, and
    a decode error must not turn a working interpreter into a refused one.

    The interpreter running this process demonstrably started, so a one-word
    ``argv`` that is the very PATH ``sys.executable`` was started as is
    answered without a spawn. The PATH, not the file: whether an interpreter
    starts depends on where it is invoked from (its ``pyvenv.cfg`` and
    ``home``), so a match by file would pass a broken venv
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
    status is not retried; it does not flake. A probe that times out on both
    tries says nothing either way, so this returns None for it and the
    banner's verdict stands, as it does in the hook-side twin (``DEF-5014``).
    A loaded host does exactly that to a working interpreter, and reading it
    as "cannot start" made ``init`` pass over a working ``python3`` for a name
    that was not there. A caller that CLAIMS a start also asks
    :func:`interpreter_start_unconfirmed` (``init``'s enforcement claim
    withholds itself), and ``doctor`` gives such an interpreter a blocking
    hook's whole time with :func:`interpreter_start_failure_within`.

    Each verdict is kept for the process (:data:`_START_VERDICTS`), so a
    process spends at most two spawns, 4 s, on each interpreter it asks
    about: ``init`` asked one interpreter 26 times on a host where every ask
    timed out twice.
    """
    verdict = _start_verdict(argv, START_PROBE_SECONDS, START_PROBE_TRIES)
    if verdict is not None and verdict.startswith(START_UNANSWERED):
        return None
    return verdict


#: The start-up probe's time per try, and its tries: the banner probe's two
#: seconds, and one retry for a shim that is slow once. Read by every sentence
#: that quotes them, so a sentence cannot drift from the probe.
START_PROBE_SECONDS = 2
START_PROBE_TRIES = 2


def interpreter_start_unconfirmed(argv: "list[str] | tuple[str, ...]") -> str | None:
    """A clause saying the start-up probe never answered for ``argv`` (both of
    :func:`interpreter_start_failure`'s tries timed out), or None when it
    answered either way. The same kept verdict, so asking both costs one
    probe. For a caller that claims a start (``DEF-5014``): a decision keeps
    the banner's verdict, a claim says the start was not confirmed."""
    verdict = _start_verdict(argv, START_PROBE_SECONDS, START_PROBE_TRIES)
    if verdict is not None and verdict.startswith(START_UNANSWERED):
        return verdict
    return None


def interpreter_start_failure_within(
    argv: "list[str] | tuple[str, ...]", seconds: int,
) -> str | None:
    """Why the interpreter at ``argv`` does not start within ``seconds``, on
    one try, or None when it does. No answer in that time is a failure here,
    not a non-answer: ``doctor`` passes the time a blocking hook gets per tool
    call, and an interpreter that cannot start in it leaves every blocking
    guard wired with it to time out before it decides, whatever the cause (a
    hang at start-up, or a host this loaded)."""
    verdict = _start_verdict(argv, seconds, 1)
    if verdict is not None and verdict.startswith(START_UNANSWERED):
        return f"{START_TOO_SLOW}: it did not start within {seconds} s"
    return verdict


#: How :func:`interpreter_start_failure_within` opens when the interpreter did
#: not start in the time it was given, as against an exit status.
START_TOO_SLOW = "cannot start in time"


def start_unconfirmed_of(name_or_path: str | None) -> str | None:
    """:func:`interpreter_start_unconfirmed` for an interpreter SPELLING
    (``python3``, a path, ``py -3``), resolved as :func:`interpreter_meets_floor`
    resolves it, so the two read one kept verdict. None when it does not
    resolve."""
    if not name_or_path:
        return None
    import shutil
    from pathlib import Path as _Path

    head, *flags = interpreter_argv(name_or_path)
    resolved = shutil.which(head) or (head if _Path(head).is_file() else None)
    return interpreter_start_unconfirmed([resolved, *flags]) if resolved else None


#: Each start-up verdict this process has asked for, keyed on the argv, the
#: time and tries it was given, and the file its head names (device, inode,
#: size, modification time, so a file rewritten in place is asked again). A
#: head that is not a path is never kept: a bare name resolves through PATH at
#: the spawn, which a file of that name in the working directory does not key.
_START_VERDICTS: dict[tuple[object, ...], "str | None"] = {}

#: How a start-up verdict opens when the probe never answered in its time
#: (``DEF-5014``). Internal to this module: :func:`interpreter_start_failure`
#: turns it into None (the banner's verdict stands),
#: :func:`interpreter_start_unconfirmed` hands it to a claim, and
#: :func:`interpreter_start_failure_within` turns it into a failure.
START_UNANSWERED = "start not confirmed"


def _start_verdict(
    argv: "list[str] | tuple[str, ...]", seconds: int, tries: int,
) -> str | None:
    """The kept start-up verdict for ``argv``: None (started), "cannot
    start: ..." (an exit status, or a probe that could not run), or a
    :data:`START_UNANSWERED` clause (every try timed out)."""
    import os
    import sys

    rescued = os.environ.get("PYTHONHOME") or os.environ.get("PYTHONPATH")
    if len(argv) == 1 and sys.executable and not rescued:
        def _as_invoked(path: str) -> str:
            return os.path.normcase(os.path.abspath(path))
        if _as_invoked(argv[0]) == _as_invoked(sys.executable):
            return None
    key = _probe_key(argv, seconds, tries)
    if key is not None and key in _START_VERDICTS:
        return _START_VERDICTS[key]
    verdict = _ask_start(argv, seconds, tries)
    if key is not None:
        _START_VERDICTS[key] = verdict
    return verdict


def _probe_key(
    argv: "list[str] | tuple[str, ...]", seconds: int, tries: int,
) -> tuple[object, ...] | None:
    """The key a kept probe answer is filed under: the argv, the time and
    tries it was given, and the file its head names (device, inode, size,
    modification time). None for a head that is not a path, or is gone: a bare
    name resolves through PATH at the spawn, which no file here keys."""
    import os

    head = argv[0] if argv else ""
    if "/" not in head.replace("\\", "/"):
        return None
    try:
        st = os.stat(head)
    except (OSError, ValueError):
        return None
    return (tuple(argv), seconds, tries, st.st_dev, st.st_ino, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


#: The ``--version`` probe's time per try and its tries (``DEF-5015``): the
#: start-up probe's two seconds, and one retry for an interpreter slow once.
BANNER_PROBE_SECONDS = 2
BANNER_PROBE_TRIES = 2

#: How a banner opens when the ``--version`` probe could not run at all (an
#: unspawnable path, an answer that does not decode): an answer against the
#: interpreter, unlike a probe that never answered in its time, which is None.
BANNER_PROBE_FAILED = "probe failed"

#: Each ``--version`` answer this process has asked for, keyed as
#: :func:`_probe_key` says.
_BANNER_VERDICTS: dict[tuple[object, ...], "str | None"] = {}


def interpreter_banner(argv: "list[str] | tuple[str, ...]") -> str | None:
    """What the interpreter at ``argv`` answers to ``--version`` -- its
    stdout, else its stderr, stripped -- or None when the probe never answered
    in :data:`BANNER_PROBE_TRIES` tries of :data:`BANNER_PROBE_SECONDS` s
    (``DEF-5015``). A loaded host does that to a working interpreter, so None
    is no answer either way: the resolver keeps such a candidate as its last
    choice ahead of the literal name, a claim says it was not confirmed, and
    the floor check, a decision, does not accept it. A probe that could not
    run opens with :data:`BANNER_PROBE_FAILED`, an answer against it; the
    decode is strict, a structured answer (``DEF-821``).

    Kept for the process like the start-up verdict, so the resolver, the floor
    check and doctor's identity check read one answer: asked apart, one
    interpreter could answer the first and miss the second, and doctor called
    a 3.10 "older than 3.10" that way.
    """
    return _banner_verdict(argv, BANNER_PROBE_SECONDS, BANNER_PROBE_TRIES)


def interpreter_banner_within(argv: "list[str] | tuple[str, ...]", seconds: int) -> str | None:
    """:func:`interpreter_banner` on one try of ``seconds`` (``doctor`` passes
    the time a blocking hook gets): None when it did not answer in it."""
    return _banner_verdict(argv, seconds, 1)


def interpreter_banner_unanswered(argv: "list[str] | tuple[str, ...]") -> str | None:
    """A clause saying the ``--version`` probe never answered for ``argv``, or
    None when it answered either way: the same kept answer, so no spawn beyond
    :func:`interpreter_banner`'s."""
    if interpreter_banner(argv) is not None:
        return None
    return (
        f"its `--version` probe did not answer within {BANNER_PROBE_SECONDS} s "
        f"in {BANNER_PROBE_TRIES} tries, which a loaded host does to a working "
        f"interpreter, and an interpreter that hangs at start-up does too"
    )


def banner_unanswered_of(name_or_path: str | None) -> str | None:
    """:func:`interpreter_banner_unanswered` for an interpreter SPELLING,
    resolved as :func:`interpreter_meets_floor` resolves it, so the two read
    one kept answer. None when it does not resolve."""
    if not name_or_path:
        return None
    import shutil
    from pathlib import Path as _Path

    head, *flags = interpreter_argv(name_or_path)
    resolved = shutil.which(head) or (head if _Path(head).is_file() else None)
    return interpreter_banner_unanswered([resolved, *flags]) if resolved else None


def _banner_verdict(
    argv: "list[str] | tuple[str, ...]", seconds: int, tries: int,
) -> str | None:
    """The kept ``--version`` answer for ``argv`` (:func:`interpreter_banner`).

    A one-word argv that is the interpreter running this, by the rule its
    platform launches by (:func:`_is_running_interpreter`), is answered from
    ``sys.version_info`` without a spawn, so the answer is read, not assumed,
    and a 3.9 running interpreter still reads 3.9. Asked by spawn, a loaded host
    could leave the very interpreter running doctor unanswered, and doctor
    called it "older than 3.10" (both reviews of DEF-5015, the common pip, pipx
    and Homebrew install). The start-up probe keys its own shortcut on the
    invoked path on every platform, since a start depends on where the
    interpreter is invoked from.
    """
    import sys

    if len(argv) == 1 and sys.executable:
        try:
            if _is_running_interpreter(argv[0]):
                return _running_interpreter_banner()
        except (OSError, ValueError):
            pass
    key = _probe_key(argv, seconds, tries)
    if key is not None and key in _BANNER_VERDICTS:
        return _BANNER_VERDICTS[key]
    banner = _ask_banner(argv, seconds, tries)
    if key is not None:
        _BANNER_VERDICTS[key] = banner
    return banner


def _running_interpreter_banner() -> str:
    """The banner the interpreter running this would print, read from
    ``sys.version_info``. A seam: a test that fakes ``sys.executable`` as an
    interpreter of another version fakes this with it."""
    import sys

    return "Python {}.{}.{}".format(*sys.version_info[:3])


def _is_running_interpreter(path: str) -> bool:
    """Whether ``path`` is the interpreter running this, for its ``--version``
    banner only, never its start (DEF-5016; the hook twin
    ``tools/cc/hooks/_hook_utils.py::_is_running_interpreter`` keeps the same
    rule, its body pinned equal). By the rule its platform launches an interpreter by. On Windows
    by its path as invoked: a venv's ``python.exe`` is a redirector that reads
    the ``pyvenv.cfg`` beside it, so a link of it elsewhere cannot start ("No
    pyvenv.cfg file"; the failure-mode review, driven) and is asked, as is an
    8.3 short spelling of this path, which at worst reads "not confirmed".
    Elsewhere by the file a symbolic link resolves to (``realpath``): the
    Homebrew and pipx ``python3`` is a symlink of the running binary and prints
    the same version, so a loaded host cannot leave it unanswered (DEF-5015),
    while a hard link in another folder is asked, since a build that loads its
    library from beside itself cannot print even its version there. The
    start-up probe keys on the invoked path on every platform
    (:func:`interpreter_start_failure`)."""
    import os
    import sys

    if _running_by_invoked_path():
        return (os.path.normcase(os.path.abspath(path))
                == os.path.normcase(os.path.abspath(sys.executable)))
    return os.path.realpath(path) == os.path.realpath(sys.executable)


def _running_by_invoked_path() -> bool:
    """True on Windows, where :func:`_is_running_interpreter` matches by the
    path as invoked; a seam, so one host's tests drive both platforms' rules."""
    import os

    return os.name == "nt"


def _ask_banner(argv: "list[str] | tuple[str, ...]", seconds: int, tries: int) -> str | None:
    """The spawn half of :func:`_banner_verdict`, unkept."""
    import subprocess

    from espalier._spawn import run_bounded
    for _attempt in range(tries):
        try:
            result = run_bounded(
                [*argv, "--version"], capture_output=True, text=True,
                encoding="utf-8", timeout=seconds,
            )
        except subprocess.TimeoutExpired:
            continue
        except (subprocess.SubprocessError, OSError, ValueError) as exc:  # strict decode: a structured answer (DEF-821)
            return f"{BANNER_PROBE_FAILED}: {type(exc).__name__}"
        return (result.stdout or result.stderr).strip()
    return None


def _ask_start(argv: "list[str] | tuple[str, ...]", seconds: int, tries: int) -> str | None:
    """The spawn half of :func:`_start_verdict`, unkept."""
    import subprocess

    from espalier._spawn import run_bounded
    result = None
    for _attempt in range(tries):
        try:
            # The tail is a literal, the one spelling of the probe, so the
            # subprocess-contract scanner resolves this argv as it does the
            # banner probe's below, rather than reading it as all-dynamic.
            result = run_bounded(
                [*argv, "-I", "-c", "import sys"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=seconds,
            )
        except subprocess.TimeoutExpired:
            continue
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            return f"cannot start: the start-up probe raised {type(exc).__name__}"
        break
    if result is None:
        times = ", twice" if tries == 2 else ""
        return (
            f"{START_UNANSWERED}: its start-up probe did not answer within "
            f"{seconds} s{times}, which a loaded host does to a working "
            f"interpreter, and an interpreter that hangs at start-up does too"
        )
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
    spawn there is paid on SessionStart. Its other askers (the
    ``python3``/``python``/``py -3`` a hint spells) are the one gap left. The
    twin keeps its banner per process, answers the running interpreter from
    ``sys.version_info`` and reads a probe that never answered as no answer, as
    this copy does (``DEF-5016``), but asks once, not twice: its spawn is paid
    on SessionStart's budget.

    ⚠ No short-circuit of its own in this body, and since DEF-5016 none in the
    identity probes either (doctor's ``samefile`` one was a third rule): a
    shortcut that assumed the answer could not answer the floor question, and
    a 3.9 host is exactly where it would be asked. The banner this reads
    answers the running interpreter from ``sys.version_info`` by the rule its
    platform launches by (:func:`_is_running_interpreter`), which reads the
    version rather than assuming it, so a 3.9 host still reads 3.9. (The
    start-up probe skips a spawn for the running interpreter's own path, for
    the start question only.)

    False for an unresolvable name, a non-interpreter, a probe that cannot
    run, or an interpreter that cannot start: an unreadable answer is not a
    passing one. A start-up probe that never answered is no answer about the
    start, so the banner's verdict stands (``DEF-5014``,
    :func:`interpreter_start_failure`).
    A launcher spelling (``py -3``) is probed as the launcher
    with its flag: resolved whole, the two words named nothing and a working
    launcher read as absent.
    """
    if not name_or_path:
        return False
    import shutil
    from pathlib import Path as _Path

    head, *flags = interpreter_argv(name_or_path)
    resolved = shutil.which(head) or (
        head if _Path(head).is_file() else None
    )
    if not resolved:
        return False
    # The kept banner (DEF-5015). One that never answered is not accepted by
    # this decision; the resolver and the claims ask the banner themselves.
    banner = interpreter_banner([resolved, *flags])
    if banner is None or not meets_python_floor(banner):
        return False
    # A start-up probe that never answered keeps the banner's verdict here
    # (DEF-5014): every caller of this decides with it.
    return interpreter_start_failure([resolved, *flags]) is None


def floor_text() -> str:
    """``"3.10"`` -- for interpolation into operator-facing messages.

    One renderer, so a message can never quote a floor the code does not
    enforce. Every emitted string naming the minimum reads it from here rather
    than spelling it, which is the ``DEF-410a`` shape one level up.
    """
    return ".".join(str(part) for part in MIN_PYTHON)
