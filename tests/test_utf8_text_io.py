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
from pathlib import Path

import pytest

from espalier._safe_walk import visible

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
    paths = visible(claude.rglob("*.md"), claude) + visible((claude / "workflows").glob("*.js"), claude / "workflows")
    paths += sorted(p for p in (REPO_ROOT / "espalier" / "assets").rglob("*.md")
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
