"""Shipped Python entry points run to completion on a default-code-page pipe.

On Windows without UTF-8 mode, a redirected stream encodes through the ANSI code
page (cp1252), and ``read_text()`` with no ``encoding=`` decodes through the
locale. The operator's own hosts hide both: ``PYTHONUTF8=1`` on Windows, a UTF-8
locale elsewhere. So every drive here runs a child with every ``PYTHON*`` and
``CLAUDE*`` variable removed and ``PYTHONIOENCODING=cp1252`` forced, which
reproduces the stream half on any host, and feeds it content cp1252 cannot hold
(a CJK repository name, an arrow in a commit subject, box-drawing characters in
the shipped bodies). The child's output is read as bytes and decoded here
explicitly -- never through this process's locale.

The read half is not reproduced by ``PYTHONIOENCODING`` (the locale decides it),
so its acceptance rule is the static contract over the shipped bodies below.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections import Counter, namedtuple
from pathlib import Path

import pytest

from espalier._safe_walk import visible
from tests import _live_tree_census as live_tree_census
from tests._live_tree import (
    EXCLUDED_DIR_PARTS,
    checkout_files,
    checkout_glob,
    checkout_iterdir,
    checkout_rglob,
    copy_checkout,
    exclude_worktrees,
    in_checkout,
    is_under_excluded_dir,
    keep_in_checkout,
    live_tree_copy_ignore,
    live_tree_skip_names,
    nested_repo_names,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
PACKAGED_CLAUDE = REPO_ROOT / "espalier" / "assets" / "claude"
ADVISOR_BODY = REPO_ROOT / ".claude" / "agents" / "harness-config-advisor.md"

REPO_NAME = "r" + chr(0x65E5)          # r + a CJK ideograph: outside cp1252
ARROW_TEXT = "sqlite " + chr(0x2192) + " postgres"   # a right arrow: outside cp1252


def _code_page_env(**extra: str) -> dict[str, str]:
    """The parent environment minus every PYTHON* and CLAUDE* variable, with the
    child's stdio forced to cp1252. HOME, PATH and SYSTEMROOT stay: removing them
    breaks the interpreter and git, which is a different failure."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "CLAUDE"))}
    env["PYTHONIOENCODING"] = "cp1252"
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
    )


def _seed_repo(repo: Path, subject: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", subject)


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


class TestInitOnACodePagePipe:
    """``espalier init`` prints the repository name first and tracked paths later;
    both must reach the pipe as UTF-8, and the run must reach the ignore block."""

    def _env(self, tmp_path: Path) -> dict[str, str]:
        # PYTHONPATH back to the tree under test: stripped, the child would import
        # whatever espalier the interpreter has installed (an editable install of
        # another checkout), and a second worktree would test the wrong code.
        env = _code_page_env(ESPALIER_AUDIT_DIR=str(tmp_path / "audit"),
                             PYTHONPATH=str(REPO_ROOT))
        probe = subprocess.run(
            [sys.executable, "-c", "import espalier; print(espalier.__file__)"],
            capture_output=True, env=env, cwd=str(tmp_path), timeout=50,
        )
        imported = Path(probe.stdout.decode("utf-8", "replace").strip()).resolve()
        assert REPO_ROOT in imported.parents, f"the child imports {imported}, not this tree"
        return env

    def _init(self, tmp_path: Path, *flags: str) -> tuple[subprocess.CompletedProcess, Path]:
        repo = tmp_path / REPO_NAME
        _seed_repo(repo, "seed")
        result = subprocess.run(
            [sys.executable, "-m", "espalier", "init", *flags, str(repo)],
            capture_output=True, stdin=subprocess.DEVNULL, env=self._env(tmp_path),
            cwd=str(tmp_path), timeout=50,
        )
        return result, repo

    def test_dry_run_names_the_repository_in_utf8(self, tmp_path):
        result, _ = self._init(tmp_path, "--dry-run")
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert b"charmap" not in result.stderr
        assert REPO_NAME.encode("utf-8") in result.stdout
        assert _is_utf8(result.stdout) and _is_utf8(result.stderr)

    def test_init_completes_through_the_ignore_block(self, tmp_path):
        result, repo = self._init(tmp_path, "--write-gitignore")
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert REPO_NAME.encode("utf-8") in result.stdout
        gitignore = repo / ".gitignore"
        assert gitignore.is_file(), "init died before writing the ignore block"
        assert ".espalier" in gitignore.read_text(encoding="utf-8")


class TestMainNamesAnEncodeError:
    """``UnicodeEncodeError`` is a ``ValueError``: unless ``main`` catches it first,
    an unwritable character reads as "malformed data", which sends the reader to
    their input instead of to the encoding."""

    def test_encode_error_is_named_not_reported_as_malformed_data(self, monkeypatch, capsys, tmp_path):
        import argparse

        from espalier import cli

        def _raise(_args):
            raise UnicodeEncodeError("cp1252", REPO_NAME, 1, 2, "character maps to <undefined>")

        class _Parser:
            def parse_args(self):
                return argparse.Namespace(func=_raise)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli, "build_parser", _Parser)
        monkeypatch.setattr(cli, "_maybe_nudge_source_checkout", lambda _args: None)
        assert cli.main() == 1
        err = capsys.readouterr().err
        assert "malformed data" not in err
        assert "could not encode '\\u65e5' as cp1252" in err
        assert err.isascii(), "the message itself must stay 7-bit"


class TestHandoffClisOnACodePagePipe:
    """The three ``tools/cc`` CLIs on the ``/handoff`` and ``/read-summary`` path
    print operator content (a commit subject, the summary, a recorded decision).
    Each must exit 0 and print that content as valid UTF-8. They run by path
    from this tree, so no PYTHONPATH is needed to reach the code under test."""

    @pytest.fixture
    def handoff_repo(self, tmp_path):
        repo = tmp_path / "repo"
        _seed_repo(repo, ARROW_TEXT)
        (repo / "cc").mkdir()
        (repo / "cc" / "_working_summary.md").write_text(ARROW_TEXT + "\n", encoding="utf-8")
        env = _code_page_env(CLAUDE_PROJECT_DIR=str(repo))
        blueprint = [sys.executable, str(TOOLS_CC / "cognitive_blueprint.py")]
        subprocess.run(blueprint + ["start"], cwd=repo, env=env, capture_output=True,
                       check=True, timeout=50)
        subprocess.run(blueprint + ["record", "--kind", "decision", "--description",
                                    "moved the job queue from " + ARROW_TEXT],
                       cwd=repo, env=env, capture_output=True, check=True, timeout=50)
        return repo, env

    @pytest.mark.parametrize("argv", [
        ("session_summary.py",),
        ("read_summary.py",),
        ("reflect_protocol.py", "--candidates"),
    ], ids=["session_summary", "read_summary", "reflect_candidates"])
    def test_cli_prints_operator_content_as_utf8(self, handoff_repo, argv):
        repo, env = handoff_repo
        result = subprocess.run(
            [sys.executable, str(TOOLS_CC / argv[0]), *argv[1:]],
            cwd=repo, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=50,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert _is_utf8(result.stdout), "stdout is not valid UTF-8"
        assert ARROW_TEXT.encode("utf-8") in result.stdout

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="PYTHONSAFEPATH arrived in 3.11")
    def test_reflect_survives_a_safe_path_interpreter(self, handoff_repo):
        # PYTHONSAFEPATH drops the script's directory from sys.path; this CLI never
        # relied on it, so the stream pin's sibling import must not either.
        repo, env = handoff_repo
        result = subprocess.run(
            [sys.executable, str(TOOLS_CC / "reflect_protocol.py"), "--candidates"],
            cwd=repo, env={**env, "PYTHONSAFEPATH": "1"}, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=50,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    def test_record_reflect_reads_piped_utf8(self, handoff_repo):
        # stdin is pinned too: a UTF-8 producer piped into a CLI on a cp1252 host
        # was silently mis-decoded (an em dash stored as three cp1252 glyphs).
        repo, env = handoff_repo
        # Its own text, not the fixture's: the fixture already recorded an arrow,
        # so finding that would pass whatever stdin did. `description` is one of
        # the finding fields the projection keeps.
        piped = "piped through stdin " + chr(0x2014) + " intact"
        report = {"pass_number": 1, "findings": [
            {"kind": "gap", "severity": "low", "description": piped, "files": []}]}
        payload = json.dumps(report, ensure_ascii=False).encode("utf-8")
        blueprint = [sys.executable, str(TOOLS_CC / "cognitive_blueprint.py")]
        subprocess.run(blueprint + ["record-reflect"], input=payload, cwd=repo, env=env,
                       capture_output=True, check=True, timeout=50)
        stored = "".join(p.read_text(encoding="utf-8")
                         for p in (repo / "cc" / "blueprints").rglob("*.json"))
        assert piped in stored or json.dumps(piped)[1:-1] in stored


# ---- entry points --------------------------------------------------------------

_STREAM_PIN_HELPER = "pin_utf8_streams"

# Entry points that print through another module's pinned entry instead of
# pinning themselves. Each entry states where the pin happens.
_DELEGATES_ITS_PIN = {
    "espalier/__main__.py": "runs espalier.cli.main, whose first statement pins",
}

_MAIN_LINE_RE = re.compile(r"""^if __name__ == ["']__main__["']\s*:""", re.M)


def _main_block(tree):
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in node.test.comparators)):
            return node
    return None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", "")


def _is_sys_stream(node, stream: str) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == stream
            and isinstance(node.value, ast.Name) and node.value.id in ("sys", "_sys"))


def _utf8_reconfigure(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reconfigure"
            and any(k.arg == "encoding" and isinstance(k.value, ast.Constant)
                    and str(k.value.value).lower().replace("_", "-") == "utf-8"
                    for k in node.keywords))


def _pins_stream(node, stream: str) -> bool:
    """``node`` reconfigures ``sys.<stream>`` to UTF-8: through the layer's helper
    (which pins every stream), directly, or in a loop over a tuple naming it."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _call_name(sub) == _STREAM_PIN_HELPER:
            return True
        if _utf8_reconfigure(sub) and _is_sys_stream(sub.func.value, stream):
            return True
        if (isinstance(sub, ast.For) and isinstance(sub.target, ast.Name)
                and isinstance(sub.iter, (ast.Tuple, ast.List))
                and any(_is_sys_stream(e, stream) for e in sub.iter.elts)
                and any(_utf8_reconfigure(c) and isinstance(c.func.value, ast.Name)
                        and c.func.value.id == sub.target.id for c in ast.walk(sub))):
            return True
    return False


def _pinned_before_use(stmts) -> bool:
    """stdout and stderr are both pinned by a statement that runs before the first
    statement that prints or calls into the program (``main``, ``args.func``)."""
    for stmt in stmts:
        if _pins_stream(stmt, "stdout") and _pins_stream(stmt, "stderr"):
            return True
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call) and _call_name(sub) in ("print", "main", "func"):
                return False
    return False


def _first_statement(fn: ast.FunctionDef):
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return body[0] if body else None


def _entry_point_files() -> list[Path]:
    """Top-level ``tools/cc/*.py``, the non-event CLIs in ``tools/cc/hooks/``
    (``_recall.py`` is ``/recall``'s; event hooks print ASCII JSON and are out of
    scope), and every ``espalier/`` module outside the ``_vendor`` byte-mirror."""
    return (sorted(TOOLS_CC.glob("*.py")) + sorted((TOOLS_CC / "hooks").glob("_*.py"))
            + sorted(p for p in (REPO_ROOT / "espalier").rglob("*.py")
                     if "_vendor" not in p.parts))


def _entry_points() -> dict[str, ast.Module]:
    found = {}
    for path in _entry_point_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _main_block(tree) is not None:
            found[path.relative_to(REPO_ROOT).as_posix()] = tree
    return found


def _console_scripts() -> dict[str, str]:
    """``[project.scripts]`` as ``{name: "module:function"}``, read as text: the
    floor interpreter (3.10) has no ``tomllib``."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r"^\[project\.scripts\]\s*\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert section is not None, "pyproject.toml declares no [project.scripts]"
    return dict(re.findall(r'^\s*([\w.-]+)\s*=\s*"([\w.]+:\w+)"', section.group(1), re.M))


@pytest.mark.contract
class TestEveryEntryPointPinsItsStreams:
    """A shipped entry point pins stdout and stderr to UTF-8 before it prints or
    calls into the program: in its ``__main__`` block, or first in the ``main()``
    that block runs (three ledger tools pin inside ``main()`` because tests load
    them by path). Every console script's target pins as its first statement. A
    new CLI that skips the pin reds here instead of on an adopter's Windows pipe."""

    def test_population_matches_a_text_search(self):
        by_text = {p.relative_to(REPO_ROOT).as_posix() for p in _entry_point_files()
                   if _MAIN_LINE_RE.search(p.read_text(encoding="utf-8"))}
        assert set(_entry_points()) == by_text
        assert len(by_text) >= 20, sorted(by_text)

    def test_every_entry_point_pins_before_use(self):
        unpinned = []
        for rel, tree in _entry_points().items():
            if rel in _DELEGATES_ITS_PIN:
                continue
            main_fn = next((n for n in tree.body
                            if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
            if not (_pinned_before_use(_main_block(tree).body)
                    or (main_fn is not None and _pinned_before_use(main_fn.body))):
                unpinned.append(rel)
        assert not unpinned, (
            "these entry points print without first pinning stdout and stderr to UTF-8; "
            "call the layer's pin_utf8_streams() first in the __main__ block "
            "(espalier/_text, or tools/cc/_json_safe), or inline the reconfigure of "
            f"both streams where the file cannot import it: {unpinned}"
        )

    def test_every_console_script_pins_first(self):
        scripts = _console_scripts()
        assert scripts, "no console scripts parsed"
        for name, target in scripts.items():
            module, func = target.split(":")
            path = REPO_ROOT / Path(*module.split(".")).with_suffix(".py")
            fn = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                      if isinstance(n, ast.FunctionDef) and n.name == func)
            first = _first_statement(fn)
            assert first is not None and _pins_stream(first, "stdout") \
                and _pins_stream(first, "stderr"), (
                    f"console script {name} enters {target} directly, so its first "
                    "statement must pin the streams")

    def test_every_delegation_is_live(self):
        found = _entry_points()
        for rel, reason in _DELEGATES_ITS_PIN.items():
            assert rel in found, f"{rel} is no longer an entry point; drop it ({reason})"
            assert not _pins_stream(found[rel], "stdout"), \
                f"{rel} now pins itself; drop the delegation entry"

    def test_the_pin_checks_fire_on_planted_modules(self):
        def pinned(src: str) -> bool:
            return _pinned_before_use(_main_block(ast.parse(src)).body)

        head = "import sys\nif __name__ == '__main__':\n"
        assert pinned(head + "    pin_utf8_streams()\n    main()\n")
        assert pinned(head + "    for s in (sys.stdout, sys.stderr):\n"
                             "        s.reconfigure(encoding='utf-8', errors='replace')\n"
                             "    main()\n")
        assert not pinned(head + "    main()\n    pin_utf8_streams()\n")       # too late
        assert not pinned(head + "    sys.stdin.reconfigure(encoding='utf-8')\n    main()\n")
        assert not pinned(head + "    sys.stdout.reconfigure(encoding='utf-8')\n    main()\n")
        assert not pinned(head + "    for s in (sys.stdout, sys.stderr):\n"
                                 "        s.reconfigure(errors='replace')\n    main()\n")


@pytest.mark.contract
class TestDeadConfigPassOnACodePagePipe:
    """The Dead-Config pass in the shipped ``harness-config-advisor`` body reads
    every packaged body (box-drawing characters included) and names the dead
    hook's file; on a default code page it must still report it. The hook's name
    is outside cp1252, so a dropped stdout pin reds here even if the body's own
    glyphs go ASCII one day. Contract-marked although it drives a child (under a
    second): an edit to the body alone earns only the contract tier."""

    DEAD = "gone" + chr(0x65E5) + ".py"

    def test_pass_reports_a_dead_hook(self, tmp_path):
        body = _heredoc_after(ADVISOR_BODY.read_text(encoding="utf-8"), "### Dead-Config Pass")
        shutil.copytree(PACKAGED_CLAUDE, tmp_path / ".claude")
        settings = {"hooks": {"Stop": [{"hooks": [{"command": f'python "{self.DEAD}"'}]}]}}
        (tmp_path / ".claude" / "settings.json").write_text(
            json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-"], input=body.encode("utf-8"), cwd=tmp_path,
            env=_code_page_env(), capture_output=True, timeout=50,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert b"DEAD HOOK" in result.stdout
        assert self.DEAD.encode("utf-8") in result.stdout
        assert _is_utf8(result.stdout)


# ---- shipped bodies: the collector -----------------------------------------------
#
# A shipped body is Python a shipped text hands to an interpreter: a heredoc or a
# ``-c`` string inside a markdown fence (whatever the fence's tag), or the same
# inside a workflow's JS template literals. Out of reach, stated rather than
# implied: PowerShell here-strings (``@'...'@``), and Python reached only through
# a variable expansion such as ``python -c "$CODE"``. No shipped text uses either.

# A command word that runs Python: a bare name, the Windows launcher, the
# resolver variable the command bodies set, or that resolver's own loop variable
# (``for c in 'python3' python 'py -3'; do $c -c``).
_PY_WORD = r'(?:python3?|py|"?\$\{?(?:PY|c)\}?"?)'
_PY_WORD_NAMES = {"python", "python3", "py", "$PY", "${PY}", "$c", "${c}"}
# A word whose ``-c`` or heredoc is not Python: shells take a command string,
# ``cat``/``tee`` take a heredoc, ``grep -c`` is grep's count flag.
_NOT_PYTHON_WORDS = {"bash", "sh", "zsh", "pwsh", "powershell", "cat", "tee", "grep"}
_CMD_START = r"(?:^|(?<=[\s|;&(`]))"
_WORD = r"""(?P<word>[^\s|;&(`<>]+)"""
_FLAGS = r"(?P<flags>(?:[ \t]+(?:-X[ \t]+\S+|-[0-9A-Za-z]+))*?)"
_DASH_C_OPENER_RE = re.compile(_CMD_START + _WORD + _FLAGS + r"""[ \t]+-c[ \t]+(?=["'])""", re.M)
_DASH_C_BODY_RE = re.compile(r""""(?P<dq>(?:[^"\\]|\\.)*)"|'(?P<sq>[^']*)'""", re.S)
_HERESTRING_RE = re.compile(r"""<<<[ \t]*(?:"(?P<dq>(?:[^"\\]|\\.)*)"|'(?P<sq>[^']*)')""", re.S)
_HEREDOC_OPENER_RE = re.compile(r"""(?<!<)<<(?P<dash>-?)[ \t]*(?P<q>["']?)\\?(?P<tag>[A-Za-z_]\w*)(?P=q)""")
_PY_ON_LINE_RE = re.compile(_CMD_START + _PY_WORD + r"(?=[ \t]|$)", re.M)
_FENCE_RE = re.compile(r"^[ \t]*(?P<f>`{3,}|~{3,})[^\n]*\n(?P<code>.*?)^[ \t]*(?P=f)[ \t]*$",
                       re.M | re.S)
_JS_TEMPLATE_RE = re.compile(r"`((?:[^`\\]|\\.)*)`", re.S)
_PLACEHOLDER_RE = re.compile(r"\s*<[^<>\n]+>\s*")


def _word_name(word: str) -> str:
    return word.strip("\"'")


def _shell_dq(text: str) -> str:
    """A double-quoted shell string's content as the shell passes it on."""
    return re.sub(r'\\(["\\$`])', r"\1", text.replace("\\\n", ""))


def _script_bodies(code: str) -> tuple[list[tuple[str, str]], list[str]]:
    """``(bodies, problems)`` for one block of shell text. A body is
    ``(kind, python_source)``; a problem is an opener the collector cannot read,
    named by its whole line, so a new spelling reds instead of dropping a body."""
    bodies: list[tuple[str, str]] = []
    problems: list[str] = []
    lines = code.split("\n")
    rest: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("#"):
            i += 1
            continue
        opener = _HEREDOC_OPENER_RE.search(line)
        if opener is None:
            rest.append(line)
            i += 1
            continue
        tag = opener.group("tag")
        end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == tag), None)
        is_python = bool(_PY_ON_LINE_RE.search(line))
        # The word that consumes the heredoc is the first of ITS segment: in
        # `git commit -m "$(cat <<'EOF'` that is `cat`, not `git`.
        segment = re.split(r"[|;&(]", line[:opener.start()])[-1].split()
        word = _word_name(segment[0]) if segment else ""
        if not is_python and word not in _NOT_PYTHON_WORDS:
            problems.append(f"heredoc with an unknown command word: {line.strip()}")
        elif is_python and end is None:
            problems.append(f"heredoc with no terminator: {line.strip()}")
        elif is_python:
            bodies.append(("heredoc", textwrap.dedent("\n".join(lines[i + 1:end]))))
        rest.append(line[:opener.start()])
        i = (end + 1) if (end is not None and is_python) else (i + 1)
    text = "\n".join(rest)
    for m in _HERESTRING_RE.finditer(text):
        if _PY_ON_LINE_RE.search(text[text.rfind("\n", 0, m.start()) + 1:m.start()]):
            bodies.append(("here-string", m.group("sq") if m.group("sq") is not None
                           else _shell_dq(m.group("dq"))))
    for m in _DASH_C_OPENER_RE.finditer(text):
        name = _word_name(m.group("word"))
        line = text[text.rfind("\n", 0, m.start()) + 1:].split("\n", 1)[0].strip()
        if name in _NOT_PYTHON_WORDS:
            continue
        if name not in _PY_WORD_NAMES:
            problems.append(f"-c string after an unknown command word: {line}")
            continue
        quoted = _DASH_C_BODY_RE.match(text, m.end())
        if quoted is None:
            problems.append(f"-c string the collector could not read to its close: {line}")
            continue
        body = quoted.group("sq") if quoted.group("sq") is not None else _shell_dq(quoted.group("dq"))
        if not _PLACEHOLDER_RE.fullmatch(body):
            bodies.append(("-c", body))
    return bodies, problems


def _markdown_bodies(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    bodies, problems = [], []
    for fence in _FENCE_RE.finditer(text.replace("\r", "")):
        b, p = _script_bodies(fence.group("code"))
        bodies += b
        problems += p
    return bodies, problems


def _js_bodies(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """A workflow assembles its shell commands from template literals joined by
    ``+``; joined in file order and unescaped the way JS reads them, a ``-c '...'``
    body ends at its shell quote, which by construction it cannot contain."""
    joined = "".join(_JS_TEMPLATE_RE.findall(text.replace("\r", "")))
    unescaped = re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)),
                       joined, flags=re.S)
    return _script_bodies(unescaped)


def _shipped_texts() -> dict[str, str]:
    """``.claude/`` bodies (markdown and the workflow scripts) and the seeded docs
    under ``espalier/assets/`` (``espalier/assets/claude`` is ``.claude``'s mirror)."""
    claude = REPO_ROOT / ".claude"
    # git's view: a linked worktree under .claude/worktrees/ is another checkout, not
    # this tree's text, and `visible` keeps it (`worktrees` is not a hidden name) -- DEF-1196
    paths = visible(checkout_rglob(claude, "*.md"), claude) + visible(
        checkout_glob(claude / "workflows", "*.js"), claude / "workflows")
    paths += sorted(p for p in checkout_rglob(REPO_ROOT / "espalier" / "assets", "*.md")
                    if "claude" not in p.relative_to(REPO_ROOT / "espalier" / "assets").parts[:1])
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in paths}


def _shipped_bodies() -> dict[str, tuple[list[tuple[str, str]], list[str]]]:
    return {rel: (_js_bodies(text) if rel.endswith(".js") else _markdown_bodies(text))
            for rel, text in _shipped_texts().items()}


def _heredoc_after(text: str, heading: str) -> str:
    """The first Python heredoc body after ``heading`` in a markdown text."""
    bodies, _ = _markdown_bodies(text.replace("\r", "").split(heading, 1)[1])
    heredocs = [b for kind, b in bodies if kind == "heredoc"]
    assert heredocs, f"no python heredoc after {heading!r}"
    return heredocs[0]


def _bare_text_reads(tree) -> list[str]:
    """``read_text`` calls and text-mode ``open(`` calls without ``encoding=``."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or any(k.arg == "encoding" for k in node.keywords):
            continue
        name = _call_name(node)
        if name == "read_text":
            found.append(f"read_text (body line {node.lineno})")
        elif name == "open":
            mode = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "mode"), None)
            if not (isinstance(mode, ast.Constant) and "b" in str(mode.value)):
                found.append(f"open (body line {node.lineno})")
        elif _is_sys_stream(getattr(node.func, "value", None), "stdin") or (
                name in ("load", "loads") and node.args
                and _is_sys_stream(node.args[0], "stdin")):
            found.append(f"stdin decoded through the locale (body line {node.lineno})")
    return found


def _ascii_safe(arg) -> bool:
    """An argument whose printed form is ASCII whatever the data: an ASCII
    constant, a ``len(...)``, or ``json.dumps`` with its default ``ensure_ascii``."""
    if isinstance(arg, ast.Constant):
        return not isinstance(arg.value, str) or arg.value.isascii()
    if isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "len":
        return True
    if isinstance(arg, ast.Call) and _call_name(arg) == "dumps":
        return not any(k.arg == "ensure_ascii" and not (
            isinstance(k.value, ast.Constant) and k.value.value is True) for k in arg.keywords)
    return False


def _unsafe_stdout_prints(tree) -> list[int]:
    """Lines printing to stdout something that may fall outside ASCII. stderr
    prints are left out: stderr's ``backslashreplace`` cannot raise."""
    lines = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
            continue
        dest = next((k.value for k in node.keywords if k.arg == "file"), None)
        if dest is not None and not _is_sys_stream(dest, "stdout"):
            continue
        if not all(_ascii_safe(a) for a in node.args):
            lines.append(node.lineno)
    return lines


@pytest.mark.contract
class TestShippedBodiesPinTheirText:
    """Every Python body a shipped text runs names the encoding of every text
    read, and pins stdout to UTF-8 before printing anything that may fall outside
    ASCII. ``read_text()``, ``open()`` and ``sys.stdin`` decode through the locale,
    which ``PYTHONIOENCODING`` does not touch, so no subprocess drive on a UTF-8
    host can see the read half; this static check is its oracle. No ``encoding``
    scanner reaches these bodies: they are not ``*.py`` files."""

    def test_the_collector_reads_every_opener(self):
        problems = {rel: p for rel, (_, p) in _shipped_bodies().items() if p}
        assert not problems, (
            "a shipped text opens a heredoc or a -c string the collector cannot read, so "
            "its body is outside this contract. A Python spelling belongs in _PY_WORD and "
            "_PY_WORD_NAMES; only a command word that never runs Python belongs in "
            f"_NOT_PYTHON_WORDS: {problems}"
        )

    def test_the_word_lists_agree(self):
        for name in sorted(_PY_WORD_NAMES):
            for fence in (f'```\n{name} -c "x = 1"\n```\n',
                          f"```\n{name} - <<'EOF'\nx = 1\nEOF\n```\n"):
                bodies, problems = _markdown_bodies(fence)
                assert bodies and not problems, (name, fence, bodies, problems)
        for word in _NOT_PYTHON_WORDS:
            assert re.fullmatch(r"[a-z]+", word), word
            assert not _PY_ON_LINE_RE.search(word), word

    def test_the_population_is_non_trivial(self):
        bodies = [b for (found, _) in _shipped_bodies().values() for _, b in found]
        dead_config = _heredoc_after(ADVISOR_BODY.read_text(encoding="utf-8"),
                                     "### Dead-Config Pass")
        # 18 when this was written; a floor, so a collector that stopped matching
        # cannot pass over an empty population.
        assert len(bodies) >= 15, len(bodies)
        assert dead_config in bodies

    def test_every_body_parses(self):
        broken = []
        for rel, (found, _) in _shipped_bodies().items():
            for kind, body in found:
                try:
                    ast.parse(body)
                except SyntaxError as exc:
                    broken.append(f"{rel} [{kind}] line {exc.lineno}: {exc.msg}")
        assert not broken, f"a shipped body does not parse, so nothing else can check it: {broken}"

    def test_every_text_read_names_its_encoding(self):
        bare = []
        for rel, (found, _) in _shipped_bodies().items():
            for kind, body in found:
                bare += [f"{rel} [{kind}] {r}" for r in _bare_text_reads(ast.parse(body))]
        assert not bare, (
            "pass encoding='utf-8' on these reads (or read sys.stdin.buffer); without it "
            f"they decode through the locale, cp1252 on a stock Windows interpreter: {bare}"
        )

    def test_every_printing_body_pins_stdout(self):
        unpinned = []
        for rel, (found, _) in _shipped_bodies().items():
            for kind, body in found:
                tree = ast.parse(body)
                lines = _unsafe_stdout_prints(tree)
                if lines and not _pins_stream(tree, "stdout"):
                    unpinned.append(f"{rel} [{kind}] prints at body lines {lines}")
        assert not unpinned, (
            "these bodies print text that may fall outside ASCII without pinning stdout "
            "to UTF-8 first (sys.stdout.reconfigure(encoding='utf-8', errors='replace')); "
            f"on a cp1252 pipe the first such character ends the run: {unpinned}"
        )

    def test_a_live_worktree_under_claude_is_not_shipped_text(self, tmp_path, monkeypatch):
        """DEF-1196: `claude --worktree` checks a second copy of the tree out under
        `.claude/worktrees/<name>/`, and `visible` keeps it (`worktrees` is not a hidden
        name), so every markdown body of that checkout was read as this tree's shipped
        text -- three reds in this class beside a live session, measured 2026-10-09 with
        a detached worktree. On a scratch tree: the worktree's body is dropped and the
        real body beside it is kept, so the exclusion is earned here, not inferred."""
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "real.md").write_text("# real\n", encoding="utf-8")
        planted = tmp_path / ".claude" / "worktrees" / "probe" / "docs"
        planted.mkdir(parents=True)
        (planted / "planted.md").write_text("```\npython -c 'print(1)'\n```\n", encoding="utf-8")
        (tmp_path / "espalier" / "assets").mkdir(parents=True)
        monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        texts = _shipped_texts()
        assert ".claude/commands/real.md" in texts, sorted(texts)
        assert not [rel for rel in texts if "worktrees" in rel], sorted(texts)

    def test_the_checks_fire_on_planted_bodies(self):
        planted = (
            "~~~bash\n"
            'python -c "import json; json.load(open(\\"x.json\\"))"\n'
            '"$PY" - <<"EOF"\nfrom pathlib import Path\nprint(Path("y").read_text())\nEOF\n'
            "py -c 'import sys; json.load(sys.stdin)'\n"
            "  python3 -u - <<-'PY2'\n\timport sys\n\tprint(sys.argv)\n\tPY2\n"
            "node -c 'console.log(1)'\n"
            "cd sub && python - <<'EOF'\nx = 1\n"
            "~~~\n"
        )
        bodies, problems = _markdown_bodies(planted)
        assert [k for k, _ in bodies] == ["heredoc", "heredoc", "-c", "-c"], bodies
        reads = [r for _, b in bodies for r in _bare_text_reads(ast.parse(b))]
        assert sorted(r.split()[0] for r in reads) == ["open", "read_text", "stdin"], reads
        printing = [b for _, b in bodies if _unsafe_stdout_prints(ast.parse(b))]
        assert len(printing) == 2 and not any(_pins_stream(ast.parse(b), "stdout")
                                              for b in printing)
        assert any("unknown command word: node" in p for p in problems), problems
        assert any("no terminator" in p for p in problems), problems
        assert _PLACEHOLDER_RE.fullmatch("<exec the path>")
        js = "const c = `$PY -c '\\n` +\n  `print(open(\"p\").read())\\n` +\n  `'`\n"
        js_bodies, js_problems = _js_bodies(js)
        assert [b for _, b in js_bodies] == ['\nprint(open("p").read())\n'] and not js_problems
        with pytest.raises(SyntaxError):
            ast.parse(_markdown_bodies('```\npython -c "def broken(:"\n```\n')[0][0][1])


@pytest.mark.contract
class TestLiveTreeExclusion:
    """`tests/_live_tree.py` is the one home of the excluded-directory set a walk
    that must see past git keeps out (DEF-1196): a mutation guard snapshotting the
    tree, the no-git fallback, a copy's ignore. Pin the predicate in both
    directions so it cannot widen into a blanket suppressor or narrow past a
    nested checkout. A contract over this tree's text reads git's view instead
    (TestCheckoutView, the ratchet below)."""

    def test_the_pair_is_matched_anywhere_below_the_root(self, tmp_path):
        assert is_under_excluded_dir(tmp_path / ".claude" / "worktrees" / "w" / "docs" / "x.md", tmp_path)
        assert is_under_excluded_dir(tmp_path / "examples" / "demo" / ".claude" / "worktrees" / "w" / "a.md", tmp_path)

    def test_a_half_pair_or_a_lookalike_is_kept(self, tmp_path):
        assert not is_under_excluded_dir(tmp_path / ".claude" / "commands" / "real.md", tmp_path)
        assert not is_under_excluded_dir(tmp_path / "docs" / "worktrees" / "x.md", tmp_path)
        assert not is_under_excluded_dir(tmp_path / ".claude" / "worktrees-notes.md", tmp_path)

    def test_a_path_outside_the_root_is_judged_on_its_own_parts(self, tmp_path):
        other = Path("/elsewhere/.claude/worktrees/w/x.md")
        assert is_under_excluded_dir(other, tmp_path)
        assert exclude_worktrees([other, tmp_path / "a.md"], tmp_path) == [tmp_path / "a.md"]

    def test_the_set_holds_the_one_measured_member(self):
        """The set grows only with a measured red -- as a pin, not prose: adding a
        directory on a hunch costs an edit here that names its red (the
        failure-mode review, 2026-10-09). One member today: Claude Code's linked
        worktrees, measured on 2026-10-09 beside a detached worktree."""
        assert EXCLUDED_DIR_PARTS == ((".claude", "worktrees"),), (
            "a directory joined the live-tree exclusion set; name the red it was measured "
            f"on in tests/_live_tree.py and here: {EXCLUDED_DIR_PARTS}"
        )

    def test_a_live_tree_copy_leaves_every_nested_repo_out(self, tmp_path):
        """The copy half (DEF-1196): a gitlink file and a `.git` directory each mark a
        repository of its own and are left out whole, and so is a worktree folder
        whose `.git` link is gone (the walkers' name pair); a lookalike name, and the
        `.git` pattern's own work on the root, are the controls."""
        src = tmp_path / "src"
        (src / ".git").mkdir(parents=True)
        probe = src / ".claude" / "worktrees" / "probe"
        probe.mkdir(parents=True)
        (probe / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        (probe / "x.md").write_text("x\n", encoding="utf-8")
        (src / "vendor" / "clone" / ".git").mkdir(parents=True)
        (src / "docs" / "worktrees").mkdir(parents=True)
        (src / "docs" / "worktrees" / "x.md").write_text("x\n", encoding="utf-8")
        assert nested_repo_names(str(src / ".claude" / "worktrees"), ["probe"]) == {"probe"}
        assert nested_repo_names(str(src / "docs"), ["worktrees"]) == set()
        assert live_tree_skip_names(str(src / ".claude"), ["worktrees", "commands"]) == {"worktrees"}
        assert live_tree_skip_names(str(src / "docs"), ["worktrees"]) == set()
        dst = tmp_path / "dst"
        shutil.copytree(src, dst, ignore=live_tree_copy_ignore(".git"))
        assert not (dst / ".git").exists()
        assert not (dst / ".claude" / "worktrees").exists()
        assert not (dst / "vendor" / "clone").exists()
        assert (dst / "docs" / "worktrees" / "x.md").is_file()


#: Enumerations of this checkout in tests/ that still list its files from the
#: filesystem, by (owner, what it calls, what it walks), waiting for the second
#: lane of DEF-2013 (air bcc9eb: every enumeration rooted in the checkout reads
#: git's view; this lane routed the ones rooted at the checkout root, at a
#: directory holding a path-bearing .gitignore rule, or at a computed root).
#: Dated 2026-10-15: 235 sites. A lane that routes or marks a site deletes its
#: entry; an entry whose site is gone reds until it is deleted; and an entry the
#: merge base's baseline does not hold reds (the baseline only shrinks). A walk
#: of gitignored state is never routed -- git's view holds nothing there, and
#: tests/_live_tree.py refuses such a base -- it is marked: the entries noted
#: "mark, never route" below.
_PENDING_SITES: dict[str, int] = {
    # mark, never route: it reads gitignored state on purpose (win-2's claims 4b5b25, #230)
    "tests/conftest.py::_live_session_markers::os.scandir::.espalier-state/sessions": 1,
    # mark, never route: it reads gitignored state on purpose (win-2's claims 4b5b25, #230)
    "tests/conftest.py::_live_tree_fingerprint::os.listdir::<computed>": 1,
    # mark, never route: it reads gitignored state on purpose (win-2's claims 4b5b25, #230)
    "tests/conftest.py::_no_live_once_flags._flags::glob::.espalier-state": 1,
    # route once win-2's claims (4b5b25, #230) merge
    "tests/conftest.py::initialized_repo_root::copytree::<root>": 1,
    "tests/test_adopter_message_hints.py::test_runtime_strings_do_not_deny_the_pypi_channel::rglob::espalier": 1,
    "tests/test_adopter_verb_stand_down.py::TestCommitStagesOnlyWhatWasReviewed.test_every_amend_a_body_teaches_leaves_a_staged_change_staged::rglob::espalier/assets/claude": 1,
    "tests/test_adopter_verb_stand_down.py::TestCommitStagesOnlyWhatWasReviewed.test_every_shipped_body_that_commits_is_driven::rglob::espalier/assets/claude": 1,
    "tests/test_adopter_verb_stand_down.py::TestCommitStagesOnlyWhatWasReviewed.test_no_shipped_body_teaches_a_wide_commit_in_prose::rglob::espalier/assets/claude": 1,
    "tests/test_adopter_verb_stand_down.py::TestHarmfulVerbsAreDeclaredAgainstTheHiddenCanon.test_hidden_ness_is_not_the_canon_for_this_class::rglob::espalier": 1,
    "tests/test_agent_contracts.py::TestCommandTableMatchesFiles.test_claude_md_skills_table_matches_skill_dirs::iterdir::.claude/skills": 1,
    "tests/test_agent_contracts.py::TestHookCountConsistentAcrossDocs.test_hook_count_claims_match_reality::glob::tools/cc/hooks": 1,
    "tests/test_agent_contracts.py::_agent_files::glob::.claude/agents": 1,
    "tests/test_agent_contracts.py::_all_doc_files::glob::.claude/skills": 1,
    "tests/test_agent_contracts.py::_command_files::glob::.claude/commands": 1,
    "tests/test_agent_frontmatter_contract.py::test_every_agent_on_disk_has_tier::glob::.claude/agents": 1,
    "tests/test_atomic_io.py::_engine_raw_writes::rglob::espalier": 1,
    "tests/test_atomic_io.py::_raw_writes_under::rglob::espalier": 1,
    "tests/test_bench_corpus_schema.py::<module>::glob::bench/corpus": 1,
    "tests/test_bench_corpus_wiring_parity.py::_all_corpus_verifiers::glob::bench/corpus": 1,
    "tests/test_bench_corpus_wiring_parity.py::_in_scope_blocked_verifiers::glob::bench/corpus": 1,
    "tests/test_bench_demo_script_quotes.py::_demo_files::glob::bench/demo": 1,
    "tests/test_bench_results_parity.py::corpus_files::glob::bench/corpus": 1,
    "tests/test_bench_surface_hygiene.py::agent_names::glob::.claude/agents": 1,
    "tests/test_board.py::TestDerivedNotRestated.test_the_ledger_count_is_the_generators::copytree::task-packs/ledger.d": 1,
    "tests/test_board_ledger_base.py::_behind_its_base::copytree::tools/cc": 1,
    "tests/test_ci_yaml_hook_count.py::_yaml_files::glob::.github/workflows": 1,
    "tests/test_cli_deploy.py::<module>::glob::espalier": 1,
    "tests/test_cli_deploy.py::TestEveryRetiredRuleReportGoesThroughTheGate._engine_modules::rglob::espalier": 1,
    "tests/test_common_tier_agent_adopter_handoff.py::_enumerate_common_tier_agents::glob::espalier/assets/claude/agents": 1,
    "tests/test_contracts.py::TestHookExitCodesNoStrayOne.test_no_stray_sys_exit_one::glob::tools/cc/hooks": 1,
    "tests/test_contracts.py::TestHookWiring.test_every_hook_file_wired_in_settings::glob::tools/cc/hooks": 1,
    "tests/test_contracts.py::TestReadmeHookCount.test_readme_hook_count_matches_reality::glob::tools/cc/hooks": 1,
    "tests/test_contracts.py::TestScannersStdlibOnly.test_scanners_stdlib_only::glob::espalier/scanners": 1,
    "tests/test_contracts.py::TestToolsCcAndHooksShareNoModuleName.test_no_basename_is_in_both_tools_cc_and_its_hooks_dir::glob::tools/cc": 1,
    "tests/test_contracts.py::TestToolsCcAndHooksShareNoModuleName.test_no_basename_is_in_both_tools_cc_and_its_hooks_dir::glob::tools/cc/hooks": 1,
    "tests/test_contracts.py::TestToolsCcNoEspalierImports.test_espalier_does_not_import_tools_cc_except_sanctioned::rglob::espalier": 1,
    "tests/test_contracts.py::_engine_modules::rglob::espalier": 1,
    "tests/test_contracts.py::_scan_for_espalier_imports::rglob::tools/cc": 1,
    "tests/test_convergence_workflow_stages.py::TestConvergenceWorkflowStages._scope_breaker_scaffolds::glob::.claude/workflows": 1,
    "tests/test_convergence_workflow_stages.py::TestWorkflowBodiesResolveTheInterpreterOnTheHost.test_every_persist_command_opens_with_the_resolver_idiom::glob::.claude/workflows": 1,
    "tests/test_convergence_workflow_stages.py::TestWorkflowBodiesResolveTheInterpreterOnTheHost.test_no_workflow_body_hands_an_agent_a_bare_versioned_invocation::glob::.claude/workflows": 1,
    "tests/test_corpus_count_parity.py::TestCorpusIdsAreUnique.test_numeric_prefixes_are_unique_except_the_b_variant::glob::bench/corpus": 1,
    "tests/test_corpus_documented_in_resolves.py::TestCorpusDocumentedIn.test_documented_in_resolves::glob::bench/corpus": 1,
    "tests/test_count_claims.py::_live_agent_count::glob::.claude/agents": 1,
    "tests/test_count_claims.py::_live_command_count::glob::.claude/commands": 1,
    "tests/test_count_claims.py::_live_helper_count::glob::tools/cc/hooks": 1,
    "tests/test_demo_end_to_end.py::_hook_sources::glob::tools/cc/hooks": 1,
    "tests/test_denial_reason_actionability.py::_roster::glob::.claude/agents": 1,
    "tests/test_denial_reason_actionability.py::_slash_commands::glob::.claude/commands": 1,
    "tests/test_denial_reason_actionability.py::_slash_commands::glob::.claude/skills": 1,
    "tests/test_denial_reasons.py::_adopter_visible_doc_sources::rglob::espalier/assets/claude": 1,
    "tests/test_denial_reasons.py::_cited_claude_md_sections::glob::tools/cc/hooks": 1,
    "tests/test_denial_reasons.py::_cited_sections_all_files::glob::tools/cc/hooks": 1,
    "tests/test_deny_markers.py::_collect_deny_sites::glob::tools/cc/hooks": 1,
    "tests/test_deny_markers.py::test_composed_fragments_are_still_composed::glob::tools/cc/hooks": 1,
    "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity.test_mirrored_covers_every_asset_doc::rglob::espalier/assets/docs": 1,
    "tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity.test_source_asset_docs_are_byte_equal::rglob::espalier/assets/docs": 1,
    "tests/test_deploy_doc_parity.py::_hook_string_literal_refs::glob::tools/cc/hooks": 1,
    "tests/test_deploy_set_import_closure.py::<module>::glob::espalier/_vendor/cc": 1,
    "tests/test_deploy_set_import_closure.py::<module>::glob::espalier/_vendor/cc/hooks": 1,
    "tests/test_deploy_set_import_closure.py::test_closure_guard_analyzes_vendored_ship_surface_not_dev_tree::glob::espalier/_vendor/cc": 1,
    "tests/test_deploy_set_import_closure.py::test_closure_guard_analyzes_vendored_ship_surface_not_dev_tree::glob::espalier/_vendor/cc/hooks": 1,
    "tests/test_documented_claims.py::<module>::glob::bench/corpus": 1,
    "tests/test_documented_claims.py::TestAgentDefinitionsMatchProtocol._agent_files::glob::.claude/agents": 1,
    "tests/test_documented_claims.py::TestAgentDocsMatchProtocol.test_agents_dir_clean::glob::.claude/agents": 1,
    "tests/test_documented_claims.py::TestClaudeMdHookCounts._actual_hook_file_count::glob::tools/cc/hooks": 1,
    "tests/test_documented_claims.py::TestDogfoodingRosterCount.test_dogfooding_readme_roster_matches_actual::glob::examples/dogfooding/.claude/agents": 1,
    "tests/test_documented_claims.py::TestDogfoodingRosterCount.test_dogfooding_readme_roster_matches_actual::glob::examples/dogfooding/.claude/commands": 1,
    "tests/test_documented_claims.py::TestDogfoodingRosterCount.test_dogfooding_readme_roster_matches_actual::iterdir::examples/dogfooding/.claude/skills": 1,
    "tests/test_documented_claims.py::TestSecurityMarkerCoverage._security_relevant_test_stems::glob::tests": 1,
    "tests/test_e2e_bench.py::TestADeadRunIsNotAHookVerdict.test_only_the_plan_scenario_allows_a_planned_change::glob::bench/end_to_end/scenarios": 1,
    "tests/test_e2e_bench.py::TestScenarioYAML.test_id_matches_filename::glob::bench/end_to_end/scenarios": 1,
    "tests/test_e2e_bench.py::TestScenarioYAML.test_required_fields_present::glob::bench/end_to_end/scenarios": 1,
    "tests/test_e2e_bench.py::TestTheSmokeScenarioCatchesCliDrift.test_the_retry_scenarios_set_the_canary_too::glob::bench/end_to_end/scenarios": 1,
    "tests/test_failopen_voice.py::TestCollectedAdvisoriesAreRendered.test_a_hook_that_emits_prints_nothing_else_to_stdout::glob::tools/cc/hooks": 1,
    "tests/test_failopen_voice.py::TestCollectedAdvisoriesAreRendered.test_every_hook_that_collects_renders::glob::tools/cc/hooks": 1,
    "tests/test_failopen_voice.py::TestCollectedAdvisoriesAreRendered.test_no_deciding_hook_collects_or_emits::glob::tools/cc/hooks": 1,
    "tests/test_failopen_voice.py::TestCollectedAdvisoriesAreRendered.test_no_shared_helper_collects::glob::tools/cc/hooks": 1,
    "tests/test_failopen_voice.py::TestFailOpenVoice.test_the_file_level_declaration_is_the_parsers_alone::glob::tools/cc/hooks": 1,
    "tests/test_failopen_voice.py::_population::glob::tools/cc/hooks": 1,
    "tests/test_failopen_voice.py::_stderr_population::glob::tools/cc/hooks": 1,
    "tests/test_finding_ledger.py::TestStandingCallerLedgerWiring._corpus_persisting_workflows::glob::.claude/workflows": 1,
    "tests/test_finding_ledger.py::TestStandingCallerLedgerWiring.test_every_workflow_body_is_a_valid_function_body::glob::.claude/workflows": 1,
    "tests/test_finding_ledger.py::TestStandingCallerLedgerWiring.test_no_scaffold_description_is_a_run_record::glob::.claude/workflows": 1,
    "tests/test_finding_ledger.py::TestStandingCallerLedgerWiring.test_no_workflow_references_the_retired_shared_corpus::glob::.claude/workflows": 1,
    "tests/test_finding_ledger.py::TestStandingCallerLedgerWiring.test_runnable_persisters_strip_every_private_lane_key::glob::.claude/workflows": 1,
    # the freshness scanner raises before keep_in_checkout filters: scan a copy_checkout copy
    "tests/test_freshness_semantic_fragments.py::TestMarkerContractClosure.test_marker_contract_has_bound_closure_true::scanner:discover_fragments::<root>": 1,
    # the freshness scanner raises before keep_in_checkout filters: scan a copy_checkout copy
    "tests/test_freshness_semantic_fragments.py::TestSemanticFragmentBounds.test_all_seeded_fragments_discoverable::scanner:discover_fragments::<root>": 1,
    # the freshness scanner raises before keep_in_checkout filters: scan a copy_checkout copy
    "tests/test_freshness_semantic_fragments.py::_verify_on_touch_fragments::scanner:discover_fragments::<root>": 1,
    "tests/test_golden_examples.py::<module>::glob::examples/golden": 1,
    "tests/test_governance_audit_log.py::TestFailOpenRecordsReachTheStatusLog.test_the_family_is_a_predicate_not_a_roster::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::TestMaintenanceBypassIsRecorded.test_the_written_set_equals_the_readers_set_and_sits_in_neither_tier::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::TestNoHookCallsTheReasonOnlySpeedBumpView.test_no_hook_calls_check_and_write_guard_calls_check_fired::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::_crash_guard_writers::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::_emitted_bypass_event_types::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::_emitted_denial_event_types::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::_hook_trees::glob::tools/cc/hooks": 1,
    "tests/test_governance_audit_log.py::_hooks_defining_an_emitter::glob::tools/cc/hooks": 1,
    "tests/test_hook_event_contracts.py::test_every_hookEventName_emitter_in_contracts::glob::tools/cc/hooks": 1,
    "tests/test_hook_helper_consolidation.py::TestHelperShadow.test_no_shadow_def::glob::tools/cc/hooks": 1,
    "tests/test_hook_helper_consolidation.py::TestHookHelperConsolidation.test_no_inline_project_root_def::glob::tools/cc/hooks": 1,
    "tests/test_hook_protocol.py::test_every_deny_hook_in_fixtures_or_exempt::glob::tools/cc/hooks": 1,
    "tests/test_hook_voice_reaches_claude.py::test_the_reporter_crash_guards_are_the_eight_the_census_named::glob::tools/cc/hooks": 1,
    "tests/test_hooks.py::TestKillSwitchTextsNameOnlyTheCIGateThisTreeHas.test_a_kept_older_denial_reasons_costs_the_clause_not_the_deny_or_the_warning::copytree::tools/cc": 1,
    "tests/test_hooks_start_on_a_kept_helper.py::TestTheDerivation.test_the_blocking_hooks_are_the_four_and_each_defines_an_emitter::glob::tools/cc/hooks": 1,
    "tests/test_hooks_start_on_a_kept_helper.py::TestTheDerivation.test_the_whole_module_census_is_at_least_the_authored_figure::glob::tools/cc/hooks": 1,
    "tests/test_hooks_start_on_a_kept_helper.py::_copy_cc::copytree::tools/cc": 1,
    "tests/test_library_hook_parity.py::test_every_engine_hook_twin_is_named_in_the_conventions_registry::rglob::espalier": 1,
    "tests/test_library_hook_parity.py::test_every_engine_hook_twin_is_named_in_the_conventions_registry::rglob::tools/cc": 1,
    "tests/test_live_root_gate_writers.py::_test_sources::glob::tests": 1,
    "tests/test_live_root_gate_writers.py::gate_writers::rglob::espalier": 1,
    "tests/test_maintenance_mode.py::TestRelaunchHint.test_no_hook_spells_a_bare_relaunch_outside_the_helper::glob::tools/cc/hooks": 1,
    "tests/test_maintenance_mode.py::_maintenance_bypass_callers::glob::tools/cc/hooks": 1,
    "tests/test_maintenance_mode_constant_parity.py::test_no_maintenance_mode_literal_in_hook_string_constants::glob::tools/cc/hooks": 1,
    "tests/test_managed_markers.py::TestConfusableDetection.test_assets_have_no_confusables_at_release::rglob::espalier/assets": 1,
    "tests/test_managed_markers.py::TestJsonSentinelIsRealSoT.test_literal_appears_in_no_production_code::rglob::espalier": 1,
    "tests/test_managed_paths.py::TestCanonicalHookCountFromContract.test_canonical_hooks_match_disk::glob::tools/cc/hooks": 1,
    "tests/test_managed_paths.py::TestHarnessOwnedRootsSingleOwner._iter_production_files::rglob::espalier": 1,
    "tests/test_manifest_truth.py::TestManifestIncludesManagedSurface.test_all_hook_files_in_manifest::glob::tools/cc/hooks": 1,
    "tests/test_marker_parity.py::_full_tree_marks_outside_the_registry::glob::tests": 1,
    "tests/test_marker_taxonomy.py::TestDocReadersRunInTheContractTier.test_every_doc_reading_test_is_in_the_contract_tier::glob::tests": 1,
    "tests/test_marker_taxonomy.py::TestMarkerTaxonomyMembership.test_every_test_file_is_classified::glob::tests": 1,
    "tests/test_nested_repo_skip.py::test_bare_os_walk_walkers_prune_nested_repos::rglob::espalier": 1,
    "tests/test_no_internal_codenames.py::TestNoPackIdsInHookRuntimeStrings.test_no_pack_ids_in_injected_runtime_strings::glob::tools/cc/hooks": 1,
    "tests/test_onboarding_doc_honesty.py::_deployed_bodies::glob::.claude/agents": 1,
    "tests/test_onboarding_doc_honesty.py::_deployed_bodies::glob::.claude/commands": 1,
    "tests/test_onboarding_doc_honesty.py::_deployed_bodies::glob::.claude/skills": 1,
    "tests/test_operator_docs.py::TestDiskSurfaceCounts.test_agent_count_on_disk::glob::.claude/agents": 1,
    "tests/test_operator_docs.py::TestDiskSurfaceCounts.test_command_count_on_disk::glob::.claude/commands": 1,
    "tests/test_operator_docs.py::TestReadmeSurfaceClaims._actual_counts::glob::.claude/agents": 1,
    "tests/test_operator_docs.py::TestReadmeSurfaceClaims._actual_counts::glob::.claude/commands": 1,
    "tests/test_paths_consolidation.py::_iter_tools_cc_files::rglob::tools/cc": 1,
    "tests/test_portability_contract.py::<module>::rglob::espalier": 1,
    "tests/test_portability_contract.py::<module>::rglob::tools/cc": 1,
    "tests/test_portability_contract.py::TestManagedHooksMatchDisk.test_canonical_hook_inventory_matches_disk::glob::tools/cc/hooks": 1,
    "tests/test_portability_contract.py::TestOperatorDocsPortability.test_operator_docs_no_unix_only_default_workflows::glob::.claude/agents": 1,
    "tests/test_portability_contract.py::TestOperatorDocsPortability.test_operator_docs_no_unix_only_default_workflows::glob::.claude/commands": 1,
    "tests/test_portability_contract.py::TestOperatorStringsArePortable.test_collector_reaches_the_denial_reason_registry::glob::tools/cc/hooks": 1,
    "tests/test_portability_contract.py::TestRemediesSpellTheRemedyInterpreter::rglob::espalier": 1,
    "tests/test_pre_release.py::TestNoticeNamesEveryExternalPin._pin_names::glob::docs/external": 1,
    "tests/test_proof_tier.py::TestTheContractSliceHoldsTheLiveManifestReaders._readers::glob::tests": 1,
    "tests/test_proof_tier.py::TestTheLegsAndTheHeavyLane.test_neither_line_collects_a_heavy_stage_without_heavy::glob::tests": 1,
    "tests/test_proof_tier.py::TestTheRecallSlice.test_no_unlisted_test_file_asserts_a_wall_clock_upper_bound::glob::tests": 1,
    "tests/test_proof_tier.py::TestTheRecallSlice.test_the_slice_is_every_recall_test_file::glob::tests": 1,
    "tests/test_publish_workflow.py::TestUsesAreSHAPinned.test_every_narrative_pin_mention_matches_its_uses_tag_comment::glob::.github/workflows": 1,
    "tests/test_recall.py::test_every_corpus_doc_closes_its_fences::glob::docs/sharp-edges": 1,
    "tests/test_recall.py::test_every_corpus_doc_closes_its_fences::glob::memory": 1,
    "tests/test_recall.py::test_every_corpus_tier_still_loads::glob::docs/sharp-edges": 1,
    "tests/test_recall.py::test_every_corpus_tier_still_loads::glob::memory": 1,
    "tests/test_recall.py::test_indexed_sources_follows_the_corpus_gates::glob::espalier/assets/seed": 1,
    "tests/test_recall.py::test_pull_excluded_memory_notes_exist_and_are_not_indexed::glob::memory": 1,
    "tests/test_recall_pasted_counts.py::test_the_loader_sees_every_file_under_each_file_backed_root::glob::docs/sharp-edges": 1,
    "tests/test_recall_pasted_counts.py::test_the_loader_sees_every_file_under_each_file_backed_root::glob::memory": 1,
    "tests/test_record_merge.py::_begin_merge::copytree::tools/cc": 1,
    "tests/test_redos.py::test_every_dynamic_compile_exemption_is_live::glob::tools/cc/hooks": 1,
    "tests/test_redos.py::test_no_unreviewed_dotstar_in_hook_regexes::glob::tools/cc/hooks": 1,
    "tests/test_reinject_sync.py::TestWitnessSetParity.test_docs_asset_tails_match_deployed_set::rglob::espalier/assets/docs": 1,
    "tests/test_required_status_checks.py::TestEveryMatrixReadsEveryCell._matrices::glob::.github/workflows": 1,
    "tests/test_required_status_checks.py::TestRequiredStatusCheckNamesResolve.test_every_instructed_check_can_actually_report::glob::.github/workflows": 1,
    "tests/test_required_status_checks.py::TestTheTierGateCannotParkThePullRequest.test_the_heavy_stages_have_exactly_one_ci_home::glob::.github/workflows": 1,
    "tests/test_required_status_checks.py::_build_resolver::glob::.github/workflows": 1,
    "tests/test_safe_walk.py::test_every_safe_rglob_prune_set_under_the_engine_is_the_one_sanctioned_call::glob::espalier": 1,
    "tests/test_scanner_earn_the_gate_parity.py::TestEveryScannerHasEarnTheGate.test_scanner_has_earn_the_gate::glob::espalier/scanners": 1,
    # the freshness scanner raises before keep_in_checkout filters: scan a copy_checkout copy
    "tests/test_scanner_freshness.py::test_fixture_not_in_live_scan::scanner:scan_repo::<root>": 1,
    "tests/test_scanner_negative_corpus_parity.py::_non_exempt_scanner_names::glob::espalier/scanners": 1,
    "tests/test_scanners.py::TestScannerExemptPrefixesParity.test_exempt_prefixes_within_declared_cap::glob::espalier/scanners": 1,
    "tests/test_scanners.py::TestScannerExemptPrefixesParity.test_test_walking_scanners_exempt_fixtures::glob::espalier/scanners": 1,
    "tests/test_scanners.py::TestScannerSelfContainment.test_no_scanner_imports_from_espalier::glob::espalier/scanners": 1,
    "tests/test_selfcheck.py::test_run_contracts_returns_1_when_a_contract_fails::copytree::tools/cc/hooks": 1,
    "tests/test_selfcheck_tests_parity.py::_mirror_files::rglob::espalier/_vendor/selfcheck_tests": 1,
    "tests/test_session_resume.py::TestBlueprintSummaryParsesLoadJsonOutput.test_blueprint_summary_returns_found_on_real_repo_with_active_blueprint::glob::cc/blueprints": 1,
    "tests/test_settings_profiles.py::test_one_function_renders_the_allow_list_and_one_the_fresh_settings::glob::espalier": 1,
    "tests/test_sharp_edges_forward_links.py::_unlinked_sharp_edges::glob::docs/sharp-edges": 1,
    "tests/test_ship_driver.py::TestPushClaimsInShippedBodiesNameTheSetting.test_every_handoff_push_claim_names_the_setting::glob::espalier/assets/claude/commands": 1,
    "tests/test_shipped_asset_md_refs.py::_shipped_asset_bodies::rglob::espalier/assets/claude": 1,
    "tests/test_shipped_commands_ascii_runtime.py::test_command_bash_blocks_are_ascii::glob::espalier/assets/claude/commands": 1,
    "tests/test_sister_site_probe_unit.py::_live_tools_py::rglob::tools": 1,
    "tests/test_skill_delegation_parity.py::TestNoBodyNamesTheSubagentTool.test_the_scan_sees_every_body_kind::iterdir::.claude/skills": 1,
    "tests/test_skill_delegation_parity.py::TestOrphanAgentParity.test_every_agent_invoked_outside_its_own_definition::glob::.claude/commands": 1,
    "tests/test_skill_delegation_parity.py::TestOrphanAgentParity.test_every_agent_invoked_outside_its_own_definition::glob::tools/cc/hooks": 1,
    "tests/test_skill_delegation_parity.py::TestOrphanAgentParity.test_every_agent_invoked_outside_its_own_definition::rglob::.claude/skills": 1,
    "tests/test_skill_delegation_parity.py::_agent_names::glob::.claude/agents": 1,
    "tests/test_skill_delegation_parity.py::_scan_surfaces::glob::.claude/commands": 1,
    "tests/test_skill_delegation_parity.py::_scan_surfaces::glob::tools/cc/hooks": 1,
    "tests/test_skill_delegation_parity.py::_scan_surfaces::rglob::.claude/skills": 1,
    "tests/test_skill_delegation_parity.py::_wired_bodies::glob::.claude/agents": 1,
    "tests/test_skill_delegation_parity.py::_wired_bodies::glob::.claude/commands": 1,
    "tests/test_skill_delegation_parity.py::_wired_bodies::rglob::.claude/skills": 1,
    "tests/test_skill_tier_contract.py::_all_agent_names::glob::espalier/assets/claude/agents": 1,
    "tests/test_skill_tier_contract.py::_common_tier_skill_paths::glob::espalier/assets/claude/skills": 1,
    "tests/test_skill_tier_contract.py::test_runtime_and_asset_skill_dirs_have_parity_for_tier_check::iterdir::.claude/skills": 1,
    "tests/test_skill_tier_contract.py::test_runtime_and_asset_skill_dirs_have_parity_for_tier_check::iterdir::espalier/assets/claude/skills": 1,
    "tests/test_spawn_chokepoint.py::spawn_sites::glob::tools/cc/hooks": 1,
    "tests/test_stack_table.py::_deployed_copy::copytree::tools/cc": 1,
    "tests/test_state_dir_single_source.py::_hook_modules::glob::tools/cc/hooks": 1,
    "tests/test_state_file_flag_parity.py::test_no_unexpected_flag_files::iterdir::.espalier-state": 1,
    "tests/test_stub_warmup.py::_census::glob::tests": 1,
    "tests/test_subagent_stop.py::TestDocsMaintainerReliefFlag.test_relief_table_keys_are_roster_agents::glob::.claude/agents": 1,
    "tests/test_subprocess_env_isolation.py::_collect_blueprint_subprocess_calls::glob::tools/cc/hooks": 1,
    "tests/test_surface_expected_witness_contract.py::test_derived_constants_not_used_as_witnesses::rglob::tests": 1,
    "tests/test_test_quality.py::TestContractRationale.test_every_file_has_rationale_docstring::glob::tests": 1,
    "tests/test_test_quality.py::test_no_pass_through_tests::glob::tests": 1,
    "tests/test_test_suite_contract.py::_all_test_dir_modules::glob::tests": 1,
    "tests/test_test_suite_contract.py::_eacces_unsafe_probes_in_denial_blocks::glob::tests": 1,
    "tests/test_test_suite_contract.py::_live_test_modules::glob::tests": 1,
    "tests/test_test_suite_contract.py::_raw_git_population_census::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_a_module_that_asserts_on_a_spawned_hooks_parent_spawns_through_hook_python::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_every_dev_tree_test_is_full_tree_or_exempt::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_every_exempt_module_carries_exactly_its_measured_dev_only_chains::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_every_spawned_step_lives_in_the_spawn_helper::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_every_subprocess_test_is_slow_or_exempt::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_every_test_file_matches_a_marker_rule_or_defaults_to_unit::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_no_non_test_function_carries_a_skip_or_xfail_mark::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_no_test_command_string_opens_with_an_unquoted_interpreter::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_no_test_module_imports_a_dev_extra_at_module_level::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_scripts_dir_matches_pinned_inventory::glob::scripts": 1,
    "tests/test_test_suite_contract.py::test_suite_size_lower_bound::glob::tests": 1,
    "tests/test_test_suite_contract.py::test_the_denial_block_detector_still_engages_the_live_corpus::glob::tests": 1,
    "tests/test_utf8_text_io.py::TestDeadConfigPassOnACodePagePipe.test_pass_reports_a_dead_hook::copytree::espalier/assets/claude": 1,
    "tests/test_utf8_text_io.py::_entry_point_files::glob::tools/cc": 1,
    "tests/test_utf8_text_io.py::_entry_point_files::glob::tools/cc/hooks": 1,
    "tests/test_utf8_text_io.py::_entry_point_files::rglob::espalier": 1,
    "tests/test_vendor_cc_parity.py::_mirrored_files::rglob::tools/cc": 1,
    "tests/test_wheel_payload.py::TestWheelPayloadExclusion.test_wheel_excludes_top_level_tools_package::rglob::espalier/_vendor/cc": 1,
    "tests/test_wheel_smoke.py::TestExpectedCountsMatchPackagedAssets.test_expected_agent_count_min_at_most_packaged_rich_agents::glob::espalier/assets/claude/agents": 1,
    "tests/test_wheel_smoke.py::TestExpectedCountsMatchPackagedAssets.test_expected_hook_entry_count_matches_packaged_hooks::glob::tools/cc/hooks": 1,
    "tests/test_wheel_smoke.py::TestExpectedCountsMatchPackagedAssets.test_expected_hook_helper_count_matches_packaged_helpers::glob::tools/cc/hooks": 1,
    "tests/test_wheel_smoke.py::TestPackagedCommandsMatchDeclaredSurface.test_packaged_commands_match_commands_md_table::glob::espalier/assets/claude/commands": 1,
    "tests/test_workflow_launch_conventions.py::_scaffolds::glob::.claude/workflows": 1,
    "tests/test_workflow_schedule_claims.py::_scheduled_workflows::glob::.github/workflows": 1,
    "tests/test_write_guard.py::TestPowerShellEphemeralCarveOut.test_the_roster_is_read_through_one_exemption_helper::glob::tools/cc/hooks": 1,
    "tests/test_zone_watch.py::test_a_deploy_without_the_helper_says_so_once_and_keeps_the_hook::copytree::tools/cc": 1,
    "tests/test_zone_writes.py::TestTheTwinsAgree.test_the_script_writers_are_the_scripts_that_record::glob::scripts": 1,
}

#: The sites carrying a ``# live-tree: ok -- <reason>`` marker, by (owner, what
#: it calls, what it walks): a walk that must see past git on purpose, each a
#: diff here a reviewer reads.
_MARKED_SITES: frozenset[str] = frozenset({
    # the scanner's own walk scope and its two readings of one walk: the
    # scanner (an adopter's scan) is judged, not this tree
    "tests/test_scanner_encoding_contracts.py::TestPragmaRegistryIsTheAllowList.test_collect_and_count_agree::scanner:collect_pragmas::<root>",
    "tests/test_scanner_encoding_contracts.py::TestPragmaRegistryIsTheAllowList.test_collect_and_count_agree::scanner:count_pragmas::<root>",
    "tests/test_scanner_encoding_contracts.py::TestTheWalk.test_walk_covers_the_hook_tree_tests_and_the_transformed_mirror_and_skips_the_rest::scanner:_iter_scoped_files::<root>",
    # a case-only existence check of one selected path, by its directory's names
    "tests/test_verify_pins.py::TestSelectionExistsWithExactCase.test_no_selected_path_is_a_case_only_match::iterdir::<computed>",
    # a mutation guard: it must see what git ignores (its 2026-08-21
    # measurement); nested checkouts are pruned (DEF-2005, air bcc9eb Q2)
    "tests/test_verify_pins.py::_fs_manifest::os.walk::<root>",
    # the build litter (build/, dist/, *.egg-info) git ignores, looked for on purpose
    "tests/test_wheel_payload.py::_packaging_litter::iterdir::<root>",
    # the self-host status folders git ignores by design (task-packs/Done/,
    # Merged/, Scrapped/): read from disk where git ignores them, each by
    # tests/_live_tree.py::ignored_by_git or because every one is the subject
    "tests/test_check_ledger_probes.py::_input_dangles::iterdir::<computed>",
    "tests/test_cross_pack_assertions.py::_pack_index::iterdir::task-packs/<computed>",
    "tests/test_cross_pack_assertions.py::_pack_subfolders::iterdir::task-packs",
    "tests/test_forward_ledger_completeness.py::_deferral_kind::rglob::task-packs",
    "tests/test_check_pack_landing.py::test_live_done_tree_population_is_non_trivial::glob::task-packs/Done",
    "tests/test_forward_ledger_completeness.py::_pack_is_landed::glob::task-packs/Done",
})


def _baseline_at_the_merge_base() -> dict[str, int] | None:
    """``_PENDING_SITES`` as the merge base with ``origin/main`` holds it, or
    None where no base can be read (an extracted archive, a clone without the
    ref, a base that predates the baseline)."""
    from tests._git_oracle import _git_env

    rel = "tests/test_utf8_text_io.py"
    try:
        base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=REPO_ROOT, env=_git_env(),
                              capture_output=True, encoding="utf-8", timeout=30)
        if base.returncode != 0 or not base.stdout.strip():
            return None
        shown = subprocess.run(["git", "show", f"{base.stdout.strip()}:{rel}"], cwd=REPO_ROOT, env=_git_env(),
                               capture_output=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if shown.returncode != 0:
        return None
    for node in ast.parse(shown.stdout).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "_PENDING_SITES" and node.value is not None:
            return ast.literal_eval(node.value)
    return None


def _grown_entries(current: dict[str, int], base: dict[str, int]) -> list[str]:
    """The baseline entries ``current`` holds above ``base``: a new walk
    written in as an allowance."""
    return sorted(k for k, n in current.items() if n > base.get(k, 0))


@pytest.mark.contract
class TestLiveTreeWalkRatchet:
    """The live-tree walk ratchet (DEF-2013). A contract over this tree's text
    reads git's view of the checkout (``tests/_live_tree.py``); a walk that
    lists the checkout from the filesystem judges what git ignores. Every
    enumeration of the checkout in ``tests/`` is routed (``keep_in_checkout``
    over a scanner's result; ``checkout_glob`` / ``checkout_rglob`` /
    ``checkout_iterdir`` / ``copy_checkout`` leave no site at all), marked with
    its reason, or a baseline site still waiting for its lane. The census is
    ``tests/_live_tree_census.py``, the same walker the ledger probe runs."""

    @staticmethod
    def _pending() -> Counter:
        return Counter(s.key for s in live_tree_census.unrouted_sites())

    def test_the_census_reads_every_tests_module_and_sees_the_measured_members(self):
        """Non-vacuity, by name: the modules it must read are read, its own two
        files are not, and the sites the first lane routed are found AS routed --
        the encoding walk that redded on reports/c0-sort/run_sort.py
        (2026-10-14), the retired-vocabulary scan that judged
        docs/session-archive.md, and the verify_pins guard as a marked walk."""
        files = {p.relative_to(REPO_ROOT).as_posix() for p in live_tree_census.census_files()}
        assert {"tests/conftest.py", "tests/_stack_census.py", "tests/test_scanner_encoding_contracts.py"} <= files
        assert not files & live_tree_census.SELF
        sites = live_tree_census.live_tree_sites()
        routed = {s.key for s in sites if s.routed}
        assert ("tests/test_scanner_encoding_contracts.py::TestTheWalk.test_live_tree_has_no_locale_following_io"
                "::scanner:scan_repo_with_skips::<root>") in routed
        assert "tests/test_scanner_retired_vocab.py::test_scanner_returns_clean_against_live_repo::scanner:scan_repo::<root>" in routed
        assert "tests/test_verify_pins.py::_fs_manifest::os.walk::<root>" in {s.key for s in sites if s.marked}

    def test_no_new_enumeration_lists_the_checkout_from_the_filesystem(self):
        found = self._pending()
        new = sorted(k for k, n in found.items() if n > _PENDING_SITES.get(k, 0))
        where = [f"{s.rel}:{s.line} {s.kind} [{s.root or '<root>'}]"
                 for s in live_tree_census.unrouted_sites() if s.key in new]
        assert not new, (
            "a test lists this checkout's files from the filesystem, so it judges what git "
            f"ignores (a local script under reports/, docs/session-archive.md, a worktree): {where}. "
            "Read git's view through tests/_live_tree.py (checkout_glob / checkout_rglob / "
            "checkout_iterdir for a walk, keep_in_checkout(...) around a scanner's result, "
            "copy_checkout for a copy). A walk that must see past git -- a guard watching "
            "gitignored state -- keeps its walk, gets `# live-tree: ok -- <why>` on its line or the "
            "comment lines directly above, and its key in _MARKED_SITES. Never a new "
            "_PENDING_SITES entry: the baseline only shrinks."
        )

    def test_the_baseline_only_shrinks(self):
        """An entry whose site was routed or marked is deleted here, so the
        list is the live list of pending sites; and no entry appears that the
        merge base's baseline did not hold, so a new walk is never an
        allowance. Per-key, so two lanes that each route a different site
        merge clean (a stored total two lanes both lower would not)."""
        found = self._pending()
        stale = sorted(k for k, n in _PENDING_SITES.items() if found.get(k, 0) < n)
        assert not stale, (
            f"baseline entries no longer listing the checkout from the filesystem: {stale} -- "
            "delete them from _PENDING_SITES (the baseline only shrinks)"
        )
        base = _baseline_at_the_merge_base()
        if base is None:
            pytest.skip("no merge base with origin/main whose baseline can be read here")
        grown = _grown_entries(_PENDING_SITES, base)
        assert not grown, (
            f"_PENDING_SITES gained entries the merge base's baseline does not hold: {grown}. "
            "Route or mark the walk instead; the baseline only shrinks."
        )

    def test_the_shrink_check_names_an_entry_the_base_did_not_hold(self):
        """The merge-base comparison on planted baselines, so it is pinned on a
        lane whose base holds no baseline yet (this one): an entry added or
        raised is named, one removed or lowered is not."""
        base = {"a::f::glob::docs": 1, "b::g::rglob::<root>": 2}
        assert _grown_entries({"a::f::glob::docs": 1, "b::g::rglob::<root>": 1}, base) == []
        assert _grown_entries({"a::f::glob::docs": 2, "c::h::iterdir::cc": 1}, base) == [
            "a::f::glob::docs", "c::h::iterdir::cc"]

    def test_every_marked_walk_is_declared_and_says_why(self):
        sites = [s for s in live_tree_census.live_tree_sites() if s.marked]
        assert {s.key for s in sites} == _MARKED_SITES
        for s in sites:
            lines = (REPO_ROOT / s.rel).read_text(encoding="utf-8").splitlines()
            block = [lines[s.line - 1]]
            i = s.line - 2
            while i >= 0 and lines[i].strip().startswith("#"):
                block.append(lines[i])
                i -= 1
            assert any(live_tree_census.MARKER_WITH_REASON.search(line) for line in block), (
                f"{s.rel}:{s.line}: a `# live-tree: ok` marker without its `-- <reason>`"
            )

    def test_the_ledger_probe_reports_the_row_open_until_both_halves_close(self):
        """The probe is ``python3 tests/_live_tree_census.py`` from the root: it
        prints ``True`` while any enumeration in tests/ is pending or any engine
        site is listed -- a verdict, not a count, so two lanes that each route
        a site never both rewrite one stored number -- and the row's probe pins
        that line."""
        from tests.test_check_ledger_probes import _live_roster_probes

        out = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tests" / "_live_tree_census.py")],
            cwd=REPO_ROOT, capture_output=True, encoding="utf-8", timeout=45, check=True,
        ).stdout.strip().splitlines()[-1]
        assert out == live_tree_census.probe_line() == str(bool(_PENDING_SITES) or bool(live_tree_census.ENGINE_SITES))
        probe = next(p for p in _live_roster_probes() if p["id"] == "DEF-2013")
        assert "tests/_live_tree_census.py" in probe["cmd"] and probe["open_value"] == "True"

    def test_the_probe_stays_open_while_an_engine_site_is_listed(self, monkeypatch):
        """Both halves close the row: the census at zero with an engine site
        still listed is open, and only both empty is closed."""
        monkeypatch.setattr(live_tree_census, "unrouted_count", lambda: 0)
        assert live_tree_census.ENGINE_SITES and live_tree_census.probe_open() is True
        monkeypatch.setattr(live_tree_census, "ENGINE_SITES", {})
        assert live_tree_census.probe_open() is False

    def test_every_engine_site_names_a_function_that_exists(self):
        """The engine and script walks the census cannot read are declared;
        each names a real function, so the second lane's list cannot drift
        from the code it points at."""
        for where in live_tree_census.ENGINE_SITES:
            rel, _, name = where.partition("::")
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            assert any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
                       for n in ast.walk(tree)), where

    def test_an_open_lane_owner_is_allowed_only_while_its_lane_is_open(self):
        """``OPEN_LANE_OWNERS`` names another seat's unmerged walk so the ratchet
        passes whichever lane merges second; each entry says whose lane, and the
        allowance is that owner's alone -- a walk beside it in the same file is
        still a new site."""
        for (rel, name), whose in live_tree_census.OPEN_LANE_OWNERS.items():
            assert rel.startswith("tests/") and name and "lane/" in whose, (rel, name, whose)
        planted = textwrap.dedent('''
            from pathlib import Path
            REPO_ROOT = Path(__file__).resolve().parents[1]

            def _naming_prose_offenders():
                return list((REPO_ROOT / "docs").rglob("*.md"))

            def _beside_it():
                return list((REPO_ROOT / "docs").rglob("*.md"))
        ''')
        sites = live_tree_census.sites_in(planted, "tests/test_mail.py")
        assert [s.owner for s in sites if not live_tree_census.on_an_open_lane(s)] == ["_beside_it"]

    def test_the_scanner_walkers_are_derived_and_exclude_one_file_readers(self):
        """Derived from espalier/scanners/: a scanner's ``scan_repo`` is a site
        the day it lands. ``ast.walk`` is a tree walk, not a directory one, so a
        function that reads one file it is handed is not a walker (the first cut
        counted every per-file reader through it)."""
        walkers = live_tree_census.scanner_walkers()
        assert {"scan_repo", "scan_repo_with_skips", "collect_pragmas", "count_pragmas",
                "build_report", "discover_fragments", "verify_repo"} <= walkers
        assert not {"scan_file", "_scan_file", "sites_in_source"} & walkers

    def test_the_census_follows_the_spellings(self):
        """Its reach, pinned on a planted module rather than inferred: each line
        tagged SITE is an unrouted site, ROUTED a routed one, MARKED a marked
        one, and NOT none at all."""
        planted = textwrap.dedent('''
            import glob
            import os
            import pathlib
            import shutil
            from shutil import copytree as ct
            from pathlib import Path
            from tests._live_tree import checkout_glob, keep_in_checkout
            from espalier.scanners import encoding_contracts as ec
            from espalier.scanners import freshness as fr
            import espalier.scanners as scanners_pkg
            REPO_ROOT = Path(__file__).resolve().parents[1]
            DOCS = REPO_ROOT / "docs"
            HOOKS = REPO_ROOT / "tools" / "cc" / "hooks"
            ROOTS = (REPO_ROOT / "docs", REPO_ROOT / ".claude")
            HERE = pathlib.Path(__file__).resolve().parent.parent

            class TestPlanted:
                HOME = REPO_ROOT / "memory"
                PUBLIC = (REPO_ROOT / "README.md", REPO_ROOT / "docs")

                def _repo_root(self):
                    return Path(__file__).resolve().parents[1]

                def test_spellings(self, tmp_path, flag):
                    list(REPO_ROOT.rglob("*.py"))  # SITE
                    list(DOCS.glob("*.md"))  # SITE
                    here = Path(__file__).parent.parent
                    list(here.iterdir())  # SITE
                    os.walk(str(REPO_ROOT.resolve()))  # SITE
                    glob.glob(f"{REPO_ROOT}/docs/*.md")  # SITE
                    glob.glob("*.md", root_dir=REPO_ROOT)  # SITE
                    os.listdir(os.path.join(REPO_ROOT, "cc"))  # SITE
                    list(self.HOME.rglob("*.md"))  # SITE
                    list(type(self).HOME.rglob("*.md"))  # SITE
                    for root in ROOTS:
                        list(root.rglob("*.md"))  # SITE
                    ct(REPO_ROOT, tmp_path / "c")  # SITE
                    shutil.copytree(src=REPO_ROOT, dst=tmp_path / "d")  # SITE
                    ec.scan_repo(REPO_ROOT)  # SITE
                    list(HOOKS.parent.rglob("*.py"))  # SITE
                    list(Path(REPO_ROOT, "docs").glob("*.md"))  # SITE
                    list((DOCS if flag else REPO_ROOT).glob("*.md"))  # SITE
                    list(HERE.glob("*.md"))  # SITE
                    list(self._repo_root().glob("*.md"))  # SITE
                    list(Path(scanners_pkg.__file__).parent.glob("*.py"))  # SITE
                    keep_in_checkout(fr.discover_fragments(REPO_ROOT))  # SITE
                    _walk_each(self.PUBLIC)
                    keep_in_checkout(ec.scan_repo(REPO_ROOT))  # ROUTED
                    # live-tree: ok -- planted: a walk that must see past git
                    list(REPO_ROOT.glob("*"))  # MARKED
                    list(checkout_glob(REPO_ROOT, "*.md"))  # NOT
                    list(tmp_path.rglob("*"))  # NOT
                    list(Path("relative").glob("*"))  # NOT
                    list(Path(pathlib.__file__).parent.glob("*.py"))  # NOT
                    walk(REPO_ROOT)  # NOT

            def walk(root):
                return root

            def _docs_dir():
                return REPO_ROOT / "docs"

            def test_a_returned_root():
                list(_docs_dir().glob("*.md"))  # SITE

            def _walk_each(roots):
                for root in roots:
                    list(root.rglob("*.md"))  # SITE

            def _helper(base):
                return list(base.rglob("*.py"))  # SITE

            def test_caller():
                _helper(REPO_ROOT / "scripts")
        ''')
        sites = live_tree_census.sites_in(planted, "tests/test_planted.py")
        lines = planted.splitlines()
        tagged = {tag: {i + 1 for i, line in enumerate(lines) if line.rstrip().endswith(f"# {tag}")}
                  for tag in ("SITE", "ROUTED", "MARKED", "NOT")}
        assert {s.line for s in sites if not s.routed and not s.marked} == tagged["SITE"]
        assert {s.line for s in sites if s.routed} == tagged["ROUTED"]
        assert {s.line for s in sites if s.marked} == tagged["MARKED"]
        assert not {s.line for s in sites} & tagged["NOT"]
        # the ratchet's unit is (owner, call, root): one owner's walks are many keys
        spelled = [s for s in sites if s.owner == "TestPlanted.test_spellings" and not s.routed and not s.marked]
        assert len({s.key for s in spelled}) >= 15, sorted({s.key for s in spelled})


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(root), *args],
                   check=True, capture_output=True)


def _planted_checkout(root: Path) -> Path:
    """A repository holding each kind of file a walk meets: tracked, untracked,
    gitignored, excluded through .git/info/exclude, tracked but deleted, and a
    nested checkout with no ignore rule naming it."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    files = {
        "a.py": "x = 1\n", "docs/guide.md": "# g\n", ".claude/skills/s/SKILL.md": "s\n",
        "src/b.py": "y = 2\n", "reports/local/probe.py": "z = 3\n", "scripts/local.py": "w = 4\n",
        "gone.py": "v = 5\n", ".claude/worktrees/w/x.py": "u = 6\n", "docs/session-archive.md": "old\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode("utf-8"))
    (root / ".gitignore").write_bytes(b"/reports/\ndocs/session-archive.md\n")
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "exclude").write_bytes(b"scripts/local.py\n")
    (root / ".claude" / "worktrees" / "w" / ".git").write_bytes(b"gitdir: /elsewhere\n")
    _git(root, "add", "a.py", "docs/guide.md", ".claude/skills/s/SKILL.md", "gone.py", ".gitignore")
    (root / "gone.py").unlink()
    return root


@pytest.mark.contract
class TestCheckoutView:
    """`tests/_live_tree.py`'s git view, on planted trees: what a contract over
    "this tree" reads (DEF-2013)."""

    def test_the_view_is_tracked_plus_untracked_minus_ignored(self, tmp_path):
        root = _planted_checkout(tmp_path)
        rels = {p.relative_to(root).as_posix() for p in checkout_files(root)}
        assert rels == {".gitignore", "a.py", "docs/guide.md", ".claude/skills/s/SKILL.md", "src/b.py"}, rels
        assert {p.relative_to(root).as_posix() for p in checkout_rglob(root, "*.py")} == {"a.py", "src/b.py"}
        assert in_checkout("a.py", root=root) and in_checkout(root / "src" / "b.py", root=root)
        assert not in_checkout("reports/local/probe.py", root=root)

    def test_the_globs_are_pathlib_over_the_view(self, tmp_path):
        """Parity, stated as the property: each helper returns what ``Path.glob``
        / ``rglob`` / ``iterdir`` return, kept to the view's files and the
        directories that hold one, sorted."""
        root = _planted_checkout(tmp_path)
        rels = {p.relative_to(root).as_posix() for p in checkout_files(root)}
        dirs = {"/".join(r.split("/")[:i]) for r in rels for i in range(1, r.count("/") + 1)}

        def kept(paths):
            return sorted(p for p in paths if p.relative_to(root).as_posix() in rels | dirs)

        for base, pattern in ((root, "*"), (root, "*.py"), (root / "docs", "*.md"), (root, "*/*.md"),
                              (root / ".claude", "*/*/SKILL.md"), (root, "**/*.md")):
            assert sorted(checkout_glob(base, pattern)) == kept(base.glob(pattern)), (base, pattern)
        assert sorted(checkout_rglob(root, "*.md")) == kept(root.rglob("*.md"))
        assert sorted(checkout_iterdir(root)) == kept(root.iterdir())
        assert ".claude" in {p.name for p in checkout_iterdir(root)}
        assert "reports" not in {p.name for p in checkout_iterdir(root)}

    def test_a_planted_tree_with_no_git_is_walked_minus_nested_checkouts(self, tmp_path):
        """No git, no view to ask: every file but a nested repository's and a
        worktree folder's (the pair rule), and none of an archive root's
        release-excluded prune -- judged from a planted root it dropped a planted
        pack (``TP-1.md``) and redded four fixtures."""
        (tmp_path / "packs" / "Done").mkdir(parents=True)
        (tmp_path / "packs" / "TP-1.md").write_bytes(b"p\n")
        (tmp_path / "packs" / "Done" / "TP-2.md").write_bytes(b"q\n")
        (tmp_path / "vendor" / "clone" / ".git").mkdir(parents=True)
        (tmp_path / "vendor" / "clone" / "x.md").write_bytes(b"x\n")
        (tmp_path / ".claude" / "worktrees" / "w").mkdir(parents=True)
        (tmp_path / ".claude" / "worktrees" / "w" / "y.md").write_bytes(b"y\n")
        found = {p.relative_to(tmp_path).as_posix() for p in checkout_rglob(tmp_path, "*.md")}
        assert found == {"packs/TP-1.md", "packs/Done/TP-2.md"}

    def test_keep_in_checkout_filters_each_result_shape(self, tmp_path):
        root = _planted_checkout(tmp_path)
        Finding = namedtuple("Finding", "path line")
        Claim = namedtuple("Claim", "surface_path")
        Canon = namedtuple("Canon", "claim severity")
        good, bad = Finding("a.py", 1), Finding("reports/local/probe.py", 2)
        assert keep_in_checkout([good, bad], root=root) == [good]
        assert keep_in_checkout(([good, bad], [{"path": "reports/local/probe.py"}]), root=root) == ([good], [])
        report = {"count": 2, "findings": [{"file": "a.py"}, {"file": "reports/local/probe.py"}]}
        assert keep_in_checkout(report, root=root) == {"count": 2, "findings": [{"file": "a.py"}]}
        nested = [Canon(Claim("docs/guide.md"), "OK"), Canon(Claim("docs/session-archive.md"), "OK")]
        assert keep_in_checkout(nested, root=root) == nested[:1]
        assert keep_in_checkout([good, object], root=root) == [good, object], "a pathless finding is kept"
        with pytest.raises(TypeError):
            keep_in_checkout(3, root=root)

    def test_keep_in_checkout_refuses_what_it_cannot_place(self, tmp_path):
        """The hiding direction raises: a planted scan routed without ``root=``
        (its relative paths land under THIS checkout, where they are no files),
        a path relative to another base, and a finding type whose file field
        this does not read. A plain string that names no file -- a pattern, a
        ``path:line`` message -- is kept, never dropped."""
        root = _planted_checkout(tmp_path)
        Finding = namedtuple("Finding", "path line")
        Unread = namedtuple("Unread", "caller line")
        with pytest.raises(ValueError):
            keep_in_checkout([Finding("src/b.py", 1)])
        with pytest.raises(ValueError):
            keep_in_checkout([Finding("b.py", 1)], root=root)
        with pytest.raises(TypeError):
            keep_in_checkout([Unread("a.py", 1)], root=root)
        patterns = {"patterns": ["subprocess_shell", "a.py:12"], "results": [{"file": "a.py"}]}
        assert keep_in_checkout(patterns, root=root) == patterns

    def test_a_base_git_ignores_is_refused(self, tmp_path):
        """Git's view holds nothing under an ignored directory, so a walk of it
        routed here would judge nothing and never red -- a guard of gitignored
        state blinded. It raises, naming the marker that walk wants."""
        root = _planted_checkout(tmp_path)
        with pytest.raises(ValueError, match="live-tree: ok"):
            list(checkout_iterdir(root / "reports"))
        assert [p.name for p in checkout_iterdir(root / "docs")] == ["guide.md"]

    def test_git_answers_about_the_root_or_the_view_raises(self, tmp_path, monkeypatch):
        """An inherited ``GIT_DIR`` (a hook, ``rebase --exec``) is stripped, so the
        view is still this root's; and a root git will not answer about -- a
        gitlink whose target is gone -- raises rather than fall back to a walk
        that judges what git ignores."""
        from tests._git_oracle import GitAnswerUnavailable

        root = _planted_checkout(tmp_path / "repo")
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
        assert {p.relative_to(root).as_posix() for p in checkout_rglob(root, "*.py")} == {"a.py", "src/b.py"}
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_bytes(b"gitdir: " + str(tmp_path / "gone").encode() + b"\n")
        (broken / "x.py").write_bytes(b"x = 1\n")
        with pytest.raises(GitAnswerUnavailable):
            list(checkout_rglob(broken, "*.py"))

    def test_the_order_is_sorted_paths(self, tmp_path):
        """``sorted(Path)``'s order -- case-folded on Windows -- not a string sort,
        so a site taking the first hit reads the same file it read before."""
        root = _planted_checkout(tmp_path)
        for name in ("B.md", "a.md", "c.md"):
            (root / "docs" / name).write_bytes(b"x\n")
        assert list(checkout_glob(root / "docs", "*.md")) == sorted(
            p for p in (root / "docs").glob("*.md") if p.name != "session-archive.md")

    def test_copy_checkout_copies_the_view_and_asks_the_ignore_per_directory(self, tmp_path):
        root = _planted_checkout(tmp_path / "src")
        asked: list[str] = []

        def ignore(directory, names):
            asked.append(Path(directory).relative_to(root).as_posix())
            return {"skills"} if Path(directory).name == ".claude" else set()

        dst = copy_checkout(root, tmp_path / "dst", ignore=ignore)
        copied = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
        assert copied == {".gitignore", "a.py", "docs/guide.md", "src/b.py"}, copied
        assert ".claude" in asked and "." in asked

    def test_the_named_red_is_closed_on_the_test_side(self, tmp_path):
        """The assign's site end to end: an untracked script under a gitignored
        reports/ with a locale-following subprocess call is a finding of the
        scanner's own walk (an adopter's scan, unchanged) and not one of the
        contract's view of the tree."""
        from espalier.scanners import encoding_contracts as ec

        root = _planted_checkout(tmp_path)
        (root / "reports" / "local" / "probe.py").write_bytes(
            b'import subprocess\nsubprocess.run(["git", "status"], capture_output=True, text=True)\n')
        raw, _skipped = ec.scan_repo_with_skips(root)
        assert any(str(f.path).replace("\\", "/") == "reports/local/probe.py" for f in raw)
        kept, _ = keep_in_checkout(ec.scan_repo_with_skips(root), root=root)
        assert kept == []
