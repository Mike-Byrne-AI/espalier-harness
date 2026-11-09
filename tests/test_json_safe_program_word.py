"""DEF-2062: the hooks spell a spaced interpreter as one word every shell runs.

``tools/cc/hooks/_hook_utils.py::python_command_hint`` fell back to a bare
``sys.executable``, and two prune notes (``post_write_check``,
``record_merge``) printed it bare, so on a host whose good Python has a space in
its path every shell cut the pasted command at that space. The hooks cannot
import the engine, so ``tools/cc/_json_safe.py`` carries a twin of
``espalier/_text.py::program_word`` (DEF-2060's spelling: the forward-slash 8.3
short form on Windows, else the quoted path), and this module pins the twin to
the engine's, the hint to the twin, a kept older ``_json_safe.py`` to the bare
spelling it printed before, and every tools/cc command that opens with the
interpreter to the twin.
"""
# slow-exempt: one import subprocess over a copied tools/cc tree, measured 2026-11-09: 0.5 s for it, 2.9 s for the module
from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import string
import subprocess
import sys
from pathlib import Path

import pytest

from tests._live_tree import checkout_rglob, copy_checkout
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"

SPACED = "C:/Program Files/Py/python.exe"
SHORT = "C:\\PROGRA~1\\Py\\python.exe"


def _load(path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def js():
    return _load(TOOLS_CC / "_json_safe.py", "json_safe_for_program_word")


@pytest.fixture()
def hu():
    return _load(TOOLS_CC / "hooks" / "_hook_utils.py", "hook_utils_for_program_word")


# Each case: (path, what the lookup answers). The lookups cover every branch
# of the spelling: no lookup, no short form, a plain short form, one that keeps
# shell grammar, a spaced one, a UNC one and one with no drive.
_CASES = [
    ("/usr/bin/python3", None),
    ("C:/Python311/python.exe", "C:\\PYTHON~1\\python.exe"),
    (SPACED, None),
    (SPACED, SHORT),
    (SPACED, "C:\\MY(PYT~1\\python.exe"),
    (SPACED, "C:\\JO&COT~1\\python.exe"),
    (SPACED, "C:\\IT'SMI~1\\python.exe"),
    (SPACED, "C:\\Program Files\\Py\\python.exe"),
    (SPACED, "\\\\server\\share\\PY~1\\python.exe"),
    (SPACED, "\\\\?\\C:\\PROGRA~1\\python.exe"),
    (SPACED, "PROGRA~1\\python.exe"),
    (SPACED, ""),
    ("/home/a b/.venv/bin/python", None),
    # DEF-2064: a drive-rooted path's backslashes, spaced or not, and the
    # forms that are not drive-rooted and keep theirs.
    ("C:\\Users\\a\\Python312\\python.exe", None),
    ("c:\\Py\\python.exe", "unused"),
    ("C:/Py\\mixed\\python.exe", None),
    ("C:\\Program Files\\Py\\python.exe", None),
    ("C:\\Program Files\\Py\\python.exe", "C:\\JO&COT~1\\python.exe"),
    ("\\\\server\\share\\python.exe", None),
    ("\\\\?\\C:\\Py\\python.exe", None),
    ("C:python.exe", None),
    ("1:\\Py\\python.exe", None),
    ("\u00e9:\\Py\\python.exe", None),
    ("C:", None),
    ("", None),
    ("1:/Py/python.exe", None),
]
# An unspaced drive-rooted path holding one character of each kind (the
# failure-mode review: a bare `'` or `(` is grammar to every shell).
_CASES += [(f"C:\\A{c}B\\python.exe", None) for c in string.printable if c not in "\\" and not c.isspace()]
# Built from the alphabet, not by hand (both reviews of 165e78b3: the hand list
# let 33 of 39 one-sided edits through): one short form per printable
# character, the drive letter's edges, the length edge, and other whitespace
# in the long path.
_CASES += [(SPACED, f"C:\\A{c}B~1\\python.exe") for c in string.printable if c != "\\"]
_CASES += [(SPACED, f"{d}:\\PY~1\\python.exe") for d in ("c", "Z", "1", "\u00e9", "\u212a")]
_CASES += [(SPACED, s) for s in ("C:\\", "C:/", "C:\\\u00e9~1\\python.exe", "C:\\a+b\\p.exe", "C:\\a-b\\p.exe")]
_CASES += [(SPACED.replace(" ", ws), SHORT) for ws in ("\t", "\u00a0", "\u3000")]
_CASES += [(SPACED.replace(" ", ws), None) for ws in ("\t", "\u00a0", "\u3000")]


class TestTheHooksTwinSpellsAsTheEngineDoes:
    """The twin and the engine's helper give the same word for every case, so
    a fix to one that misses the other reds here."""

    @pytest.mark.parametrize("path,short", _CASES, ids=[f"case{i}" for i in range(len(_CASES))])
    def test_the_twin_matches_the_engine(self, js, path, short):
        from espalier._text import program_word

        lookup = None if short is None else (lambda p, s=short: s)
        assert js.program_word(path, lookup) == program_word(path, lookup)

    def test_a_plain_short_form_is_one_bare_word(self, js):
        assert js.program_word(SPACED, lambda p: SHORT) == "C:/PROGRA~1/Py/python.exe"

    def test_a_short_form_that_keeps_grammar_stays_quoted(self, js):
        assert js.program_word(SPACED, lambda p: "C:\\JO&COT~1\\python.exe") == f'"{SPACED}"'

    def test_off_windows_the_lookup_answers_none(self, js, monkeypatch):
        monkeypatch.setattr(js.sys, "platform", "linux")
        assert js.windows_short_path(sys.executable) is None


class TestTheHintSpellsASpacedInterpreterAsOneWord:
    """DEF-2062's probe: ``python_command_hint`` driven with a spaced
    ``sys.executable`` that alone clears the floor returned a word holding a
    space with no opening quote."""

    def _only_the_spaced_interpreter_clears_the_floor(self, hu, monkeypatch, short):
        monkeypatch.setattr(sys, "executable", SPACED)
        monkeypatch.setattr(hu, "interpreter_meets_floor", lambda p: p == SPACED)
        monkeypatch.setattr(hu, "windows_short_path", lambda p: short)

    def test_the_fallback_is_the_short_form(self, hu, monkeypatch):
        self._only_the_spaced_interpreter_clears_the_floor(hu, monkeypatch, SHORT)
        assert hu.python_command_hint() == "C:/PROGRA~1/Py/python.exe"

    def test_with_no_short_form_the_fallback_is_quoted(self, hu, monkeypatch):
        self._only_the_spaced_interpreter_clears_the_floor(hu, monkeypatch, None)
        assert hu.python_command_hint() == f'"{SPACED}"'

    def test_a_bare_name_that_clears_the_floor_is_unchanged(self, hu, monkeypatch):
        monkeypatch.setattr(hu, "interpreter_meets_floor", lambda p: p == "python3")
        monkeypatch.setattr(hu, "interpreter_start_failure", lambda p: None)
        assert hu.python_command_hint() == "python3"


class TestThePowerShellNote:
    """ack 2e78b5: a seen message after a quoted program word says PowerShell
    needs ``&``; a bare word, or a host off Windows, takes no note."""

    @pytest.mark.parametrize("word,platform,said", [
        (f'"{SPACED}"', "win32", True),
        ("C:/PROGRA~1/Py/python.exe", "win32", False),
        (f'"{SPACED}"', "linux", False),
        ("python3", "win32", False),
    ], ids=["quoted-win", "bare-win", "quoted-linux", "name-win"])
    def test_the_note_follows_a_quoted_word_on_windows(self, hu, monkeypatch, word, platform, said):
        monkeypatch.setattr(hu.sys, "platform", platform)
        assert ("type & before it" in hu.powershell_call_note(word)) is said


class TestAKeptOlderJsonSafeStillStarts:
    """ruling bd0473 (b): an adopter who kept a ``_json_safe.py`` that predates
    the spelling gets hooks that start and print the bare path, as before."""

    def test_the_hooks_import_and_spell_bare(self, tmp_path):
        """A real older ``_json_safe.py`` had ``quoted_if_spaced`` and not the
        two new names. A spaced ``sys.executable`` in the child tells the bare
        fallback apart from the new spelling on any host. Dies to: either
        guard (``_hook_utils``, ``record_merge``) removed."""
        tree = tmp_path / "cc"
        copy_checkout(TOOLS_CC, tree, ignore=shutil.ignore_patterns("__pycache__"))
        kept = tree / "_json_safe.py"
        text = kept.read_text(encoding="utf-8")
        for name in ("program_word", "windows_short_path"):
            text = text.replace(f"def {name}(", f"def _gone_{name}(")
        kept.write_bytes(text.encode("utf-8"))
        code = ("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; "
                "import _hook_utils as h, post_write_check, record_merge as rm; "
                f"sys.executable = {SPACED!r}; "
                "print(h.executable_word()); print(rm.program_word(sys.executable, rm.windows_short_path))")
        proc = subprocess.run(  # spawn: ok a test driving a kept-sibling import in its own interpreter
            [sys.executable, "-c", code, str(tree / "hooks"), str(tree)],
            capture_output=True, text=True, encoding="utf-8", timeout=scaled(30), cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split("\n")[:2] == [SPACED, SPACED], proc.stdout

    def test_post_write_check_reads_the_new_names_by_getattr(self):
        """The reverse kept sibling: a new ``post_write_check.py`` beside an
        older ``_hook_utils.py`` that lacks ``executable_word`` and
        ``quoted_if_spaced`` (failure-mode review of 165e78b3: an
        AttributeError in place of the prune note). Each is read through
        ``getattr`` with a fallback, never as an attribute."""
        for hook, names in (("post_write_check.py", ("executable_word", "quoted_if_spaced", "powershell_call_note")),
                            ("session_start.py", ("powershell_call_note",))):
            src = (TOOLS_CC / "hooks" / hook).read_text(encoding="utf-8")
            for name in names:
                assert f"_hook_utils.{name}" not in src, (hook, name)
                assert (f"getattr(_hook_utils, '{name}'" in src or f'getattr(_hook_utils, "{name}"' in src), (hook, name)


@pytest.mark.skipif(sys.platform != "win32", reason="GetShortPathNameW is Windows only")
class TestTheRealWindowsLookup:
    def test_a_real_spaced_file_spells_as_one_bare_word(self, js, tmp_path):
        spaced = tmp_path / "a b" / "python.exe"
        spaced.parent.mkdir()
        spaced.write_bytes(b"")
        short = js.windows_short_path(str(spaced))
        assert short is not None, "GetShortPathNameW failed on an existing file"
        assert os.path.samefile(short, spaced)
        assert js.windows_short_path(str(tmp_path / "no such" / "file.exe")) is None
        if any(ch.isspace() for ch in short):
            pytest.skip(f"8.3 names are off on this volume: {short}")
        word = js.program_word(str(spaced), js.windows_short_path)
        if word.startswith('"'):
            pytest.skip(f"the short form keeps a character a bare word cannot hold: {short}")
        assert "\\" not in word and " " not in word, word
        assert os.path.samefile(word, spaced)


def _is_sys_interpreter(expr: ast.expr) -> bool:
    """``sys.executable`` or ``sys._base_executable``, alone or in an ``or``."""
    if isinstance(expr, ast.BoolOp):
        return any(_is_sys_interpreter(v) for v in expr.values)
    return (isinstance(expr, ast.Attribute) and expr.attr in ("executable", "_base_executable")
            and isinstance(expr.value, ast.Name) and expr.value.id == "sys")


def _bare_interpreter_commands(source: str, rel: str) -> list[str]:
    """Each f-string in ``source`` where ``{sys.executable}`` (or
    ``_base_executable``) is followed by `` -m `` or a ``.py`` script: the
    program word of a command, printed bare. A path named as information (no
    command after it) is not counted. Declared limits, read by both reviews of
    165e78b3 and absent from tools/cc today: a local bound from
    ``sys.executable``, ``str.format``, ``%`` and ``+`` building."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.JoinedStr):
            continue
        for value, after in zip(node.values, node.values[1:]):
            if not (isinstance(value, ast.FormattedValue) and _is_sys_interpreter(value.value)):
                continue
            tail = after.value if isinstance(after, ast.Constant) and isinstance(after.value, str) else ""
            head = tail.split("`")[0].split(")")[0]
            if head.startswith(" -m ") or (head.startswith(" ") and ".py" in head.split(" ")[1]):
                found.append(f"{rel}:{node.lineno}")
    return found


class TestNoCommandOpensWithABareInterpreter:
    """A tools/cc message that tells the operator to run `` `{sys.executable} ...` ``
    spells it bare, which a spaced path cuts at the space; it goes through
    ``executable_word`` / ``program_word`` instead. A path named as information
    (``the hook interpreter (...)``) is not a command and is not counted."""

    def test_no_tools_cc_command_opens_with_a_bare_sys_executable(self):
        found: list[str] = []
        for path in sorted(checkout_rglob(TOOLS_CC, "*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            found += _bare_interpreter_commands(path.read_text(encoding="utf-8"), rel)
        assert not found, found

    @pytest.mark.parametrize("src", [
        'x = f"run `{sys.executable} -m espalier memory prune` by hand"',
        'x = f"run: {sys.executable} -m espalier memory prune"',
        'x = f"`{sys._base_executable or sys.executable} tools/cc/seat.py brief`"',
        'x = f"run {sys.executable} tools/cc/execution_plan.py status"',
    ], ids=["backticked", "no-backtick", "base-or", "script"])
    def test_the_pin_sees_the_shape_it_bans(self, src):
        assert _bare_interpreter_commands(src + "\n", "probe.py") == ["probe.py:1"]

    @pytest.mark.parametrize("src", [
        'x = f"the hook interpreter ({sys.executable}) has no pytest"',
        'x = f" (at {sys.executable})"',
        'x = f"`{sys.executable}` has no pytest"',
        'x = f"run `{_hook_utils.executable_word()} -m espalier memory prune`"',
    ], ids=["paren", "at", "backticked-info", "spelled"])
    def test_the_pin_passes_a_path_named_as_information(self, src):
        assert _bare_interpreter_commands(src + "\n", "probe.py") == []


#: The helpers that spell an interpreter as the program word of a command.
_SPELLERS = frozenset({"program_word", "_remedy_program_word", "_remedy_interpreter", "_remedy_py",
                       "executable_word", "python_command_hint"})
#: The calls that write a file (``espalier/``'s writers go through
#: ``atomic_write_*``, pinned by ``tests/test_atomic_io.py``'s census).
_FILE_WRITERS = frozenset({"atomic_write_text", "atomic_write_bytes", "write_text", "write_bytes"})
#: The one spelling of a command written INTO the adopter's tree, where a later
#: reader may be on another host or volume, so the path is kept as spelled.
_PERSISTED_SITES = {("espalier/cli.py", "_file_onboarding_rows"): 1}
#: The functions that write a file AND spell a typed word, with how many typed
#: spellings each holds. Each was read for DEF-2064 (2026-11-09) and prints its
#: spelling to the operator, never into a file: the worktree-include re-run hint
#: rides a WARN line, and the rest are `print` remedies. A new spelling in one
#: of them changes its count and is read again here.
_TYPED_IN_A_WRITER = {
    ("espalier/cli.py", "deploy_harness"): 1,
    ("espalier/cli.py", "cmd_upgrade"): 7,
    ("espalier/cli.py", "cmd_refresh_self_host_pin"): 1,
    ("espalier/cli.py", "cmd_memory_prune"): 1,
}


def _callee(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _spelling_sites(source: str, rel: str) -> list[tuple[str, str, bool, bool]]:
    """``(rel, enclosing function, persisted, the function writes a file)`` for
    each call of a speller in ``source``. ``persisted`` is a literal
    ``persisted=True`` keyword; the enclosing function is the innermost one."""
    found: list[tuple[str, str, bool, bool]] = []

    def visit(node: ast.AST, fn: ast.AST | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child)
                continue
            if isinstance(child, ast.Call) and _callee(child.func) in _SPELLERS:
                persisted = any(k.arg == "persisted" and isinstance(k.value, ast.Constant) and k.value.value is True
                                for k in child.keywords)
                writes = fn is not None and any(
                    isinstance(n, ast.Call) and _callee(n.func) in _FILE_WRITERS for n in ast.walk(fn))
                found.append((rel, getattr(fn, "name", "<module>"), persisted, writes))
            visit(child, fn)

    visit(ast.parse(source), None)
    return found


def _census() -> list[tuple[str, str, bool, bool]]:
    sites: list[tuple[str, str, bool, bool]] = []
    for base in (REPO_ROOT / "espalier", TOOLS_CC):
        for path in sorted(checkout_rglob(base, "*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" in path.parts or rel.startswith(("espalier/_vendor/", "espalier/assets/")):
                continue
            sites += _spelling_sites(path.read_text(encoding="utf-8"), rel)
    return sites


def _counted(sites: list[tuple[str, str, bool, bool]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for rel, fn, _persisted, _writes in sites:
        counts[(rel, fn)] = counts.get((rel, fn), 0) + 1
    return counts


class TestTheTypedAndPersistedSpellingsAreCounted:
    """DEF-2064's census, which the DEF-2060 review asked for: a typed remedy
    spells a Windows path with forward slashes (or its 8.3 short form), and a
    copy written into the adopter's tree keeps the path as spelled. Nothing
    pinned which sites were which, so a remedy moved into a written file, or
    a new writer spelling the typed word, passed. Every speller call is read
    here: the persisted ones are exactly the roster, and a typed one inside a
    function that writes a file is rostered with its count after a read. The
    hook head the rewire writes into ``settings.json`` is spelled apart, by
    ``cli._hook_head_word`` (DEF-2063), which calls no speller and is pinned by
    ``tests/test_init_rewire_interpreter.py``."""

    def test_the_persisted_spellings_are_the_roster(self):
        sites = _census()
        assert len(sites) >= 100, f"the census read {len(sites)} speller calls: the reader went blind"
        persisted = _counted([s for s in sites if s[2]])
        assert persisted == _PERSISTED_SITES, persisted

    def test_a_typed_spelling_in_a_writer_is_rostered(self):
        typed_in_writer = _counted([s for s in _census() if s[3] and not s[2]])
        assert typed_in_writer == _TYPED_IN_A_WRITER, (
            "a function that writes a file spells a TYPED interpreter word: read whether that word "
            f"reaches the file (then persisted=True) or the operator (then roster it): {typed_in_writer}")

    @pytest.mark.parametrize("src,expected", [
        ("def f(p):\n    p.write_text(f'{_remedy_py()} -m espalier')\n", [("probe.py", "f", False, True)]),
        ("def f(p):\n    atomic_write_text(p, _remedy_py(persisted=True))\n", [("probe.py", "f", True, True)]),
        ("def f():\n    print(_hook_utils.python_command_hint())\n", [("probe.py", "f", False, False)]),
        ("def f():\n    def g(p):\n        p.write_bytes(b'')\n    return program_word(x, None)\n",
         [("probe.py", "f", False, True)]),
        ("x = executable_word()\n", [("probe.py", "<module>", False, False)]),
    ], ids=["typed-in-writer", "persisted", "printed", "nested-writer", "module"])
    def test_the_census_sees_each_shape(self, src, expected):
        assert _spelling_sites(src, "probe.py") == expected


def git_bash() -> str | None:
    """Git for Windows' own ``bash.exe`` (``<git root>/bin/bash.exe``, found
    by walking up from the PATH ``git``, which is ``<git root>/cmd/git.exe``
    or ``<git root>/mingw64/bin/git.exe``), never a PATH ``bash``: on Windows
    that can be WSL's, which cannot run a ``C:/`` program."""
    git = shutil.which("git")
    if not git:
        return None
    for root in list(Path(git).resolve().parents)[:3]:
        candidate = root / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash is a Windows host's shell")
class TestGitBashRunsTheSpelledInterpreter:
    """DEF-2064's oracle: Git Bash itself, given the word each of this host's
    interpreters (this one and the base it was made from, the two differing
    under a venv) is spelled as. A backslash path reached it with its
    separators dropped (``C:UsersMichael...python.exe: command not found``)."""

    def test_git_bash_runs_the_spelled_interpreter(self, tmp_path):
        from espalier._text import program_word, windows_short_path

        bash = git_bash()
        if bash is None:
            pytest.skip("no Git for Windows bash.exe beside git on PATH")
        exes = dict.fromkeys(p for p in (sys.executable, getattr(sys, "_base_executable", None)) if p)
        for exe in exes:
            word = program_word(exe, windows_short_path)
            script = tmp_path / "run.sh"
            script.write_bytes(f"{word} -c 'print(4242)'\n".encode("utf-8"))
            proc = subprocess.run(  # spawn: ok the row's oracle is the real Git Bash
                [bash, "--noprofile", "--norc", str(script)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=scaled(20))
            assert "4242" in proc.stdout, (exe, word, proc.returncode, proc.stderr[-400:])
