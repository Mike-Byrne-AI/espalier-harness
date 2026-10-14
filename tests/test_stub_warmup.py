"""Every executable stand-in the suite writes is warmed before a test times it.

A stub's first exec is slow on macOS and slower under load, and the production
probes these stubs stand in for give an interpreter one or two seconds; a test
whose subject was parsing or a choice of candidate went red whenever its probe
met a cold file in a loaded tier (`tests/README.md` races line, 2026-09-23 and
2026-10-14; two `TestEngineLine` reds in a fresh worktree's full tier). The one
writer, `tests/_stubs.py::write_stub`, executes each stub once through an
early-exit guard, so the cost is paid before any timed probe and the stub's body
never runs (measured on the 8 GB Air, interleaved under 8 busy processes: cold
median 0.159 s with 1 of 40 past the hook's 1.0 s cap, warm 0.012 s and 0 of 40).

This module pins that: a census reds any function in `tests/` that writes a
file and makes that same file executable without going through the one writer,
a stub whose subject is timing or a failed exec is exempt by name, and the
writer's own rows prove the warm-up runs the stub while leaving no trace a
recording stub could count.
"""
# slow-exempt: its children are /bin/sh stand-ins that print a line or append to a log, measured 2026-10-14: the whole module in 3.5 s on the Air, the census parse most of it
from __future__ import annotations

import ast
import functools
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from tests import _stubs

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

#: Writers that stay cold on purpose, by (file, function): their subject is
#: timing or an exec that fails, which a warm-up would change or cannot do.
EXEMPT: dict[tuple[str, str], str] = {
    ("test_bounded_spawn.py", "_holder"):
        "timing is its subject: a holder that keeps the pipe must start inside the cap",
    ("test_python_floor.py", "test_a_probe_that_raised_yields_to_the_next_candidates_banner"):
        "a shebang naming no interpreter: the failed exec is its subject",
    ("test_python_floor.py", "test_a_lone_failed_probe_is_still_reported"):
        "a shebang naming no interpreter: the failed exec is its subject",
}

_EXEC_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
_EXEC_NAMES = re.compile(r"\bS_I(EXEC|XUSR|XGRP|XOTH|RWXU|RWXG|RWXO)\b")


def _target(node: ast.AST) -> str:
    """A file expression with any ``str()`` / ``os.fspath()`` around it peeled off,
    so ``os.chmod(str(p), m)`` and ``p.write_text(...)`` name one file."""
    while (isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords
           and (isinstance(node.func, ast.Name) and node.func.id in ("str", "fspath")
                or isinstance(node.func, ast.Attribute) and node.func.attr == "fspath")):
        node = node.args[0]
    return ast.unparse(node)


def _chmod_target_and_mode(call: ast.Call) -> tuple[str, ast.AST] | None:
    """``(the file, the mode)`` of ``p.chmod(mode)`` or ``os.chmod(p, mode)``,
    the mode positional or ``mode=``; None for any other call."""
    f = call.func
    if not (isinstance(f, ast.Attribute) and f.attr == "chmod"):
        return None
    args = list(call.args)
    if isinstance(f.value, ast.Name) and f.value.id == "os":
        if not args:
            return None
        target, args = _target(args[0]), args[1:]
    else:
        target = _target(f.value)
    mode = args[0] if args else next((k.value for k in call.keywords if k.arg == "mode"), None)
    return None if mode is None else (target, mode)


def _makes_executable(mode: ast.AST) -> bool:
    # Anywhere in the mode expression: `0o755`, `st_mode | 0o111`, `| stat.S_IEXEC`.
    if any(isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool)
           and n.value & _EXEC_BITS for n in ast.walk(mode)):
        return True
    return bool(_EXEC_NAMES.search(ast.unparse(mode)))


def _literal_text(node: ast.AST) -> str | None:
    """The text of a str/bytes literal, an f-string's literal parts, or a
    concatenation of them; None for anything computed (a helper's parameter, or
    an f-string that opens on a substitution, whose shebang may be in it)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        return node.value if isinstance(node.value, str) else node.value.decode("latin-1")
    if isinstance(node, ast.JoinedStr):
        if node.values and not isinstance(node.values[0], ast.Constant):
            return None
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp):
        left, right = _literal_text(node.left), _literal_text(node.right)
        return None if left is None else left + (right or "")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "encode":
        return _literal_text(node.func.value)
    return None


def _is_stub_text(node: ast.AST | None) -> bool:
    """A program body: a shebang or a ``.cmd``'s ``@echo off``. A computed body
    counts too (a helper writes whatever it is handed); a literal that is
    neither is content, never run (a mode test's ``"old"``)."""
    if node is None:
        return True
    text = _literal_text(node)
    return text is None or text.startswith("#!") or "@echo off" in text.lower()


def executable_writers(source: str) -> list[tuple[str, int]]:
    """``(function, line)`` for each function in ``source`` that writes a
    program body to a file and makes that same file executable: a
    ``write_text`` / ``write_bytes`` on, or an ``open()`` of, the file a
    ``chmod`` with an exec bit is called on (``p.chmod(m)`` or ``os.chmod(p, m)``,
    the mode positional or ``mode=``).

    Not seen, by construction: a write and its chmod in different functions, a
    module-level writer, ``os.open`` with ``os.fchmod``, ``touch(mode=...)``, and a
    copy of an executable (``shutil.copy`` makes a new, cold file). Route those
    through ``write_stub`` by hand."""
    hits = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        written, made_exec = {}, set()
        handle_writes = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                         and isinstance(c.func, ast.Attribute) and c.func.attr == "write"]
        for c in ast.walk(fn):
            if not isinstance(c, ast.Call):
                continue
            f = c.func
            if isinstance(f, ast.Attribute) and f.attr in ("write_text", "write_bytes"):
                if _is_stub_text(c.args[0] if c.args else None):
                    written.setdefault(_target(f.value), c.lineno)
            elif isinstance(f, ast.Name) and f.id == "open" and c.args:
                if any(_is_stub_text(w.args[0] if w.args else None) for w in handle_writes):
                    written.setdefault(_target(c.args[0]), c.lineno)
            elif (found := _chmod_target_and_mode(c)) and _makes_executable(found[1]):
                made_exec.add(found[0])
        for target in sorted(made_exec & set(written)):
            hits.append((fn.name, written[target]))
    return hits


@functools.lru_cache(maxsize=None)
def _census() -> tuple[tuple[str, str, int], ...]:
    rows: list[tuple[str, str, int]] = []
    for p in sorted(TESTS.glob("*.py")):
        if p.name == "_stubs.py":
            continue  # the one writer
        rows += [(p.name, fn, line) for fn, line in executable_writers(p.read_text(encoding="utf-8"))]
    return tuple(rows)


class TestEveryStandInIsWarmed:
    def test_no_writer_bypasses_the_one_writer(self):
        """Dies to: a builder or a test that writes an executable stub and
        chmods it itself (the warm-up dropped)."""
        stray = [f"tests/{f}:{line} in {fn}" for f, fn, line in _census()
                 if (f, fn) not in EXEMPT]
        assert not stray, (
            "these write an executable stand-in without tests._stubs.write_stub, so a "
            "timed probe can meet it cold (its first exec crossed a 1.0 s cap under a "
            "loaded tier); route it through write_stub, or exempt it by name in "
            "EXEMPT with the reason timing is its subject:\n  " + "\n  ".join(stray))

    def test_every_exemption_still_names_a_writer(self):
        """An exemption whose writer is gone is a hole waiting for a new one."""
        found = {(f, fn) for f, fn, _ in _census()}
        stale = sorted(set(EXEMPT) - found)
        assert not stale, f"exempted writers no longer write a stub: {stale}"

    def test_every_exemption_names_its_subject(self):
        """An exemption is for a stub whose subject is timing or a failed exec,
        and its reason says so. Dies to: an exemption added with an empty or
        any other reason, the easy way to silence the census."""
        bad = {k: v for k, v in EXEMPT.items() if "is its subject" not in v}
        assert not bad, bad

    def test_the_census_sees_the_writers_it_guards(self):
        """A floor, so the census cannot pass by reading nothing: the exempt
        writers are real stub writers it finds, and the converted builders
        call the one writer."""
        assert set(EXEMPT) <= {(f, fn) for f, fn, _ in _census()}
        hosts = (TESTS / "_interpreter_hosts.py").read_text(encoding="utf-8")
        assert "write_stub(" in hosts


@pytest.mark.skipif(os.name == "nt", reason="the stand-ins here are /bin/sh scripts")
class TestTheWriterWarmsWithoutATrace:
    def test_the_warm_up_runs_the_stub(self, tmp_path):
        """Dies to: the warm-up exec removed (the stub left cold)."""
        stub = _stubs.write_stub(tmp_path / "python", "#!/bin/sh\necho 'Python 3.12.0'\n")
        assert stub in _stubs.WARMED
        assert os.access(stub, os.X_OK)

    def test_a_recording_stub_counts_only_the_runs_a_test_makes(self, tmp_path):
        """A stub that records its calls records none for the warm-up. Dies to:
        the guard line dropped, so the warm-up reaches the body."""
        import subprocess

        log = tmp_path / "calls.log"
        stub = _stubs.write_stub(tmp_path / "rec", f"#!/bin/sh\necho \"$@\" >> '{log}'\n")
        assert not log.exists(), log.read_text(encoding="utf-8")
        for arg in ("one", "two"):
            subprocess.run([str(stub), arg], check=True, timeout=30,
                           env={k: v for k, v in os.environ.items() if k != _stubs.STUB_WARMUP_ENV})
        assert log.read_text(encoding="utf-8").split() == ["one", "two"]

    def test_a_strict_shell_stub_still_reaches_its_body(self, tmp_path):
        """Dies to: a guard that reads the variable bare, which a `sh -u` stub
        refuses on its real run, when the variable is unset."""
        import subprocess

        stub = _stubs.write_stub(tmp_path / "strict", "#!/bin/sh -u\necho body\n")
        out = subprocess.run([str(stub)], capture_output=True, text=True, encoding="utf-8", timeout=30,
                             env={k: v for k, v in os.environ.items() if k != _stubs.STUB_WARMUP_ENV})
        assert out.stdout == "body\n", (out.returncode, out.stderr)

    def test_a_stub_that_is_no_shell_script_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            _stubs.write_stub(tmp_path / "py", f"#!{sys.executable}\nprint('x')\n")
        with pytest.raises(ValueError):
            _stubs.write_stub(tmp_path / "bare", "echo no shebang\n")


class TestTheCensusShapes:
    """The census's own rows: what it must find, and what it must leave alone."""

    def test_a_write_then_exec_chmod_of_the_same_file_is_found(self):
        src = ("def f(p):\n    p.write_text('#!/bin/sh\\n')\n    p.chmod(0o755)\n"
               "def g(p, body):\n    p.write_bytes(body)\n    p.chmod(p.stat().st_mode | stat.S_IEXEC)\n"
               "def h(p):\n    with open(p, 'w') as fh:\n        fh.write('#!/bin/sh\\n')\n    p.chmod(0o700)\n"
               "def i(p, body):\n    p.write_bytes(body)\n    p.chmod(p.stat().st_mode | 0o111)\n"
               "def j(p):\n    p.write_text('#!/bin/sh\\n')\n    os.chmod(p, 0o755)\n"
               "def k(p):\n    p.write_text('#!/bin/sh\\n')\n    p.chmod(mode=0o755)\n"
               "def m(p):\n    p.write_text(f'{SHEBANG}\\necho x\\n')\n    p.chmod(0o755)\n"
               "def n(p):\n    p.write_text('#!/bin/sh\\n')\n    os.chmod(str(p), stat.S_IRWXG)\n")
        assert [fn for fn, _ in executable_writers(src)] == ["f", "g", "h", "i", "j", "k", "m", "n"]

    def test_a_non_exec_chmod_or_another_file_is_left_alone(self):
        src = ("def f(p, q):\n    p.write_text('#!/bin/sh\\n')\n    q.chmod(0o755)\n"
               "def g(d):\n    d.write_text('#!/bin/sh\\n')\n    d.chmod(0)\n"
               "def h(p):\n    write_stub(p, '#!/bin/sh\\n')\n"
               "def i(p):\n    p.write_text('old')\n    p.chmod(0o755)\n"
               "def j(p, q):\n    p.write_text('#!/bin/sh\\n')\n    os.chmod(q, 0o755)\n"
               "def k(p):\n    p.write_text('#!/bin/sh\\n')\n    os.chmod(p, 0o644)\n")
        assert executable_writers(src) == []
