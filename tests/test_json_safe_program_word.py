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
import subprocess
import sys
from pathlib import Path

import pytest

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
]


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


class TestAKeptOlderJsonSafeStillStarts:
    """ruling bd0473 (b): an adopter who kept a ``_json_safe.py`` that predates
    the spelling gets hooks that start and print the bare path, as before."""

    def test_the_hooks_import_and_spell_bare(self, tmp_path):
        tree = tmp_path / "cc"
        shutil.copytree(TOOLS_CC, tree, ignore=shutil.ignore_patterns("__pycache__"))
        kept = tree / "_json_safe.py"
        text = kept.read_text(encoding="utf-8")
        for name in ("program_word", "windows_short_path", "quoted_if_spaced"):
            text = text.replace(f"def {name}(", f"def _gone_{name}(")
        # `_plain_path` calls quoted_if_spaced at run time only; keep the module importable.
        text = text.replace("return quoted_if_spaced(str(value))", "return str(value)")
        kept.write_bytes(text.encode("utf-8"))
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import _hook_utils as h; "
                "import post_write_check; print(h.executable_word())")
        proc = subprocess.run(  # spawn: ok a test driving a kept-sibling import in its own interpreter
            [sys.executable, "-c", code, str(tree / "hooks")],
            capture_output=True, text=True, timeout=scaled(30), cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == sys.executable, proc.stdout


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


def _bare_interpreter_commands(source: str, rel: str) -> list[str]:
    """Each f-string in ``source`` that opens a backticked command with
    ``{sys.executable}``: the program word of a paste, printed bare."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.JoinedStr):
            continue
        for before, value in zip(node.values, node.values[1:]):
            if (isinstance(value, ast.FormattedValue)
                    and isinstance(value.value, ast.Attribute) and value.value.attr == "executable"
                    and isinstance(value.value.value, ast.Name) and value.value.value.id == "sys"
                    and isinstance(before, ast.Constant) and isinstance(before.value, str)
                    and before.value.endswith("`")):
                found.append(f"{rel}:{node.lineno}")
    return found


class TestNoCommandOpensWithABareInterpreter:
    """A tools/cc message that tells the operator to run `` `{sys.executable} ...` ``
    spells it bare, which a spaced path cuts at the space; it goes through
    ``executable_word`` / ``program_word`` instead. A path named as information
    (``the hook interpreter (...)``) is not a command and is not counted."""

    def test_no_tools_cc_command_opens_with_a_bare_sys_executable(self):
        found: list[str] = []
        for path in sorted(TOOLS_CC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            found += _bare_interpreter_commands(path.read_text(encoding="utf-8"), rel)
        assert not found, found

    def test_the_pin_sees_the_shape_it_bans(self):
        src = 'x = f"run `{sys.executable} -m espalier memory prune` by hand"\n'
        assert _bare_interpreter_commands(src, "probe.py") == ["probe.py:1"]
        assert _bare_interpreter_commands('x = f"the interpreter ({sys.executable})"\n', "probe.py") == []
