"""The shipped first-contact diagnostics report the adopter's tree, not the
harness's own source (the forward ledger's class on first-contact diagnostics).

Four deployed bodies census a tree: ``/analyze`` Step 3 (coverage gaps and
TODOs), the test-writer agent's discovery (coverage gaps) and its priority
list, the harness-config-advisor's dead-config pass (the source paths the
bodies cite) and the repo-analyst's stack, architecture and testing fences
(language breakdown, frameworks, database, directory and module structure,
size, test count). Each was written on this repository and read its layout as
the adopter's. On a fresh ``espalier init`` tree with no ``espalier/`` the
coverage loop's glob stayed unexpanded and the census named a module ``*``; the
TODO census listed the vendored ``tools/cc/`` lines, never the adopter's; the
dead-config pass flagged the harness's own citations as dead config in bodies
the adopter did not write; and the size census counted the 44 deployed
``tools/cc/`` files, the three ``.claude/workflows/*.js`` bodies and every
dependency tree as the adopter's (driven 2026-10-01 and 2026-10-06 on init'd
temp trees: the ledger's rows). No test drove any of the four on an adopter's
tree before this module, which is how three bodies drifted while two siblings
guard every ``espalier/`` read.

One oracle for the class: ``espalier init`` into the Python adopter tree
``tests/_adopter_tree.py`` builds (``src/demo/app.py``, ``tests/test_app.py``,
no ``espalier/``), with a TODO planted in the adopter's own module and under the
vendored ``tools/cc/``, an editable install's ``src/demo.egg-info/``, a
500-line file under ``.venv/`` and a 700-line one under ``node_modules/``; then
each DEPLOYED fence run verbatim from the tree's root under a real POSIX bash
and, where the host has one, under zsh (the shell the Bash tool runs on macOS,
where an unmatched glob aborts the command), the same read as the ledger's
probes (the first ``bash`` fence, or the first ``python -`` heredoc, after the
heading); the advisor's pass under a Python with UTF-8 mode off. This checkout
is the control: its bodies keep the self-host blocks ``init`` strips, so the
same fences census the engine's modules and count ``tools/cc/`` as the
repository's own.

The harness-only step of each fence sits in a self-host-only block, gated by
the self-host predicate at deploy and never by a directory's presence (a
fusion vendors ``espalier/`` and would pass that test); the adopter's census is
the fallback the block leaves behind. The dead-config pass skips a body that
carries the managed marker and says how many bodies it read; its inline read
of the marker is pinned equal to the engine's here.
"""
from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from _live_tree import checkout_rglob
from espalier import analyze
from espalier.managed_markers import has_managed_marker

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The four deployed bodies, and the heading each probe reads its fence after.
ANALYZE = ".claude/skills/analyze/SKILL.md"
TEST_WRITER = ".claude/agents/test-writer.md"
ADVISOR = ".claude/agents/harness-config-advisor.md"
REPO_ANALYST = ".claude/agents/repo-analyst.md"
REPO_ANALYST_FENCES = ("### 2. STACK DETECTION", "### 3. ARCHITECTURE ANALYSIS", "### 4. TESTING & QUALITY")

#: What the fixture plants on the adopter tree after ``init``: a TODO in the
#: adopter's own module, one under the vendored layer, an editable install's
#: metadata directory beside the package, and a dependency tree in each of the
#: two languages the size census counts.
OWN_TODO = "src/demo/todo.py"
VENDORED_TODO = "tools/cc/zz_planted_by_this_test.py"
EGG_INFO = "src/demo.egg-info/PKG-INFO"
DEPENDENCY_PY = ".venv/lib/dep/big.py"
DEPENDENCY_JS = "node_modules/dep/index.js"
DEPENDENCY_LINES = (500, 700)

#: The directories no census of the adopter's own files walks: the engine's
#: own repository walk's skip set (the stack table's dependency directories,
#: the build outputs, the caches) and the vendored names, plus the two Python
#: environment names. The layer the harness deployed (``tools/cc/`` and
#: ``.claude/``) is ``DEPLOYED``. The expected numbers are computed by this
#: rule, and the fences' ``walk`` is pinned to cover every name in it.
PRUNED = frozenset(analyze.DEFAULT_SKIP_PARTS | analyze.VENDORED_PARTS | {".venv", "venv"})
DEPLOYED = (("tools", "cc"), (".claude",))
COUNTED_SUFFIXES = (".py", ".js", ".ts", ".go", ".rs")

#: Below the suite's 60 s ceiling for a test, which the contract reads off
#: every wait budget in the module; the harness-tree walks are the slow ones.
FENCE_TIMEOUT = 45

#: The ledger probe's still-open rule for the advisor's output (DEF-1003): any
#: line naming a dead reference or a source path.
PROBE_DEAD_RE = re.compile(r"\bDEAD\b|\w/[\w./]*\.py")


def _posix_bash() -> str | None:
    """A real POSIX bash: ``/bin/bash`` off Windows; on Windows, Git Bash found
    beside ``git``, never a bare ``bash`` (a Windows subprocess resolves that to
    the WSL shim). The same lookup ``tests/test_node_adopter_defaults.py`` runs
    the deployed /preflight fences under."""
    if os.name != "nt":
        return "/bin/bash" if Path("/bin/bash").exists() else None
    git = shutil.which("git")
    if not git:
        return None
    for root in Path(git).resolve().parents:
        for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    return None


_BASH = _posix_bash()
_ZSH = shutil.which("zsh") if os.name != "nt" else None
_NEEDS_BASH = pytest.mark.skipif(
    not _BASH, reason="the deployed fences are bash; no POSIX bash on this host",
)
#: The shells the adopter's fences are driven under: bash always, zsh where
#: the host has one (macOS; a Linux cell without it drives bash alone).
SHELLS = [pytest.param(_BASH, id="bash")] + (
    [pytest.param(_ZSH, id="zsh")] if _ZSH else []
)


@pytest.fixture(scope="module")
def adopter(tmp_path_factory) -> Path:
    """The init'd Python adopter tree with the plants, built once, read only."""
    tree = build_adopter_tree(tmp_path_factory.mktemp("first-contact"), stack="python")
    (tree / OWN_TODO).write_text("x = 1  # TODO adopter\n", encoding="utf-8")
    (tree / VENDORED_TODO).write_text("# TODO vendored\n", encoding="utf-8")
    for rel, text in (
        (EGG_INFO, "Name: demo\n"),
        (DEPENDENCY_PY, "y = 2\n" * DEPENDENCY_LINES[0]),
        (DEPENDENCY_JS, "var z = 3;\n" * DEPENDENCY_LINES[1]),
    ):
        path = tree / rel
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
    return tree


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _fence_after(body: str, heading: str) -> str:
    """The first ```bash fence after ``heading``: the ledger probes' own read."""
    tail = body[body.index(heading):]
    match = re.search(r"```bash\n(.*?)```", tail, re.S)
    assert match, f"no bash fence after {heading!r}"
    return match.group(1)


def _heredoc_after(body: str, heading: str) -> str:
    """The first ``python - <<'EOF'`` program after ``heading``."""
    tail = body[body.index(heading):]
    match = re.search(r"python3? - <<'EOF'\n(.*?)\nEOF", tail, re.S)
    assert match, f"no python heredoc after {heading!r}"
    return match.group(1)


def _section(out: str, name: str) -> str:
    """The lines a fence printed under ``=== name ===``, up to its next header."""
    marker = f"=== {name} ==="
    assert marker in out, out
    return out.split(marker, 1)[1].split("\n=== ", 1)[0]


def _run(tree: Path, fence: str, shell: str | None = None) -> subprocess.CompletedProcess:
    """Run one deployed fence from ``tree``'s root under ``shell`` (bash by
    default). The exit status is the fence's last command's (an ``ls`` of
    absent files is 1), so a caller reads the output and, under zsh, the
    unmatched-glob abort by its exit status and its stderr."""
    return subprocess.run(
        [shell or _BASH, "-c", fence], cwd=str(tree), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=FENCE_TIMEOUT,
    )


def _bash(tree: Path, fence: str) -> str:
    return _run(tree, fence).stdout


def _advisor(tree: Path, program: str) -> subprocess.CompletedProcess:
    """The dead-config pass as the probe drives it: UTF-8 mode off, the C
    locale, so a read that leans on the locale fails here before it fails on a
    default-code-page Windows host."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    env.update(PYTHONIOENCODING="utf-8", LC_ALL="C", PYTHONCOERCECLOCALE="0")
    return subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", program], cwd=str(tree),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=FENCE_TIMEOUT, env=env,
    )


def _own_files(tree: Path) -> list[Path]:
    """The adopter's own files, by this module's rule: nothing under a pruned
    directory and nothing under the layer the harness deployed."""
    out: list[Path] = []
    for path in tree.rglob("*"):
        rel = path.relative_to(tree)
        if not path.is_file() or set(rel.parts) & PRUNED:
            continue
        if any(rel.parts[:len(prefix)] == prefix for prefix in DEPLOYED):
            continue
        out.append(path)
    return out


def _lines(paths: list[Path]) -> int:
    """Newlines, as ``wc -l`` counts them."""
    return sum(_read(p).count("\n") for p in paths)


def _star_lines(out: str) -> list[str]:
    """Lines naming a module ``*``: the unexpanded glob the class was found on."""
    return [line for line in out.splitlines() if line.split()[1:2] == ["*"]]


COVERAGE_FENCES = [
    (ANALYZE, "## Step 3", "Test coverage gaps"),
    (TEST_WRITER, "## Test Pattern Discovery", "Coverage gaps"),
]


@_NEEDS_BASH
class TestTheCoverageCensusNamesTheAdoptersModules:
    """/analyze Step 3 and the test-writer discovery ran one unguarded loop."""

    @pytest.mark.parametrize("shell", SHELLS)
    @pytest.mark.parametrize("rel,heading,header", COVERAGE_FENCES)
    def test_on_the_adopters_tree(self, adopter, rel, heading, header, shell):
        fence = _fence_after(_read(adopter / rel), heading)
        assert "espalier/*.py" not in fence, "the harness's own loop reached the adopter's copy"
        proc = _run(adopter, fence, shell)
        assert proc.returncode == 0 and "no matches found" not in proc.stderr, proc.stderr
        census = _section(proc.stdout, header)
        assert _star_lines(census) == [], census
        assert re.search(r"✓ src/demo/app\.py", census), census
        assert re.search(r"✗ src/demo/todo\.py", census), census
        for harness_path in ("espalier", "tools/cc", ".claude", ".venv", "node_modules"):
            assert harness_path not in census, (harness_path, census)

    @pytest.mark.parametrize("shell", SHELLS)
    def test_the_todo_census_on_the_adopters_tree(self, adopter, shell):
        proc = _run(adopter, _fence_after(_read(adopter / ANALYZE), "## Step 3"), shell)
        todos = _section(proc.stdout, "TODOs/FIXMEs")
        assert OWN_TODO in todos, todos
        assert "tools/cc/" not in todos, todos

    def test_a_tree_without_python_says_so(self, tmp_path, adopter):
        """A Node adopter's census stands down in words, never blank."""
        tree = tmp_path / "node"
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "index.js").write_text("export default 1;\n", encoding="utf-8")
        out = _bash(tree, _fence_after(_read(adopter / ANALYZE), "## Step 3"))
        assert "(no Python modules outside the test tree)" in _section(out, "Test coverage gaps"), out

    @pytest.mark.parametrize("rel,heading,header", COVERAGE_FENCES)
    def test_on_this_checkout(self, rel, heading, header):
        """The control: the self-host block init strips is kept here, so the
        census is the engine's top-level modules, as it was before the class."""
        census = _section(_bash(REPO_ROOT, _fence_after(_read(REPO_ROOT / rel), heading)), header)
        assert _star_lines(census) == [], census
        named = [line.split()[1] for line in census.splitlines() if line.split()[1:2]]
        assert "cli" in named and "analyze" in named, named
        missing = [mod for mod in named if not (REPO_ROOT / "espalier" / f"{mod}.py").is_file()]
        assert missing == [], missing

    def test_the_todo_census_on_this_checkout(self):
        out = _bash(REPO_ROOT, _fence_after(_read(REPO_ROOT / ANALYZE), "## Step 3"))
        lines = [line for line in _section(out, "TODOs/FIXMEs").splitlines() if line.strip()]
        assert lines, out
        assert all(line.startswith(("espalier/", "tools/")) for line in lines), lines

    def test_the_priority_list_the_census_feeds_is_the_adopters(self, adopter):
        """Coverage Priority steps that name this repository's hooks and engine
        functions sit in a self-host-only block; the adopter's list stands alone."""
        deployed = _read(adopter / TEST_WRITER)
        assert "fingerprint_repo" not in deployed and "Hook scripts" not in deployed, deployed
        items = re.findall(r"^(\d)\. \*\*", deployed[deployed.index("## Coverage Priority"):], re.M)
        assert items[:4] == ["1", "2", "3", "4"], items


class TestTheDeadConfigPassReadsTheAdoptersBodies:
    def test_on_the_adopters_tree_under_a_default_code_page(self, adopter):
        proc = _advisor(adopter, _heredoc_after(_read(adopter / ADVISOR), "### Dead-Config Pass"))
        assert proc.returncode == 0, proc.stderr[-800:]
        lines = proc.stdout.splitlines()
        assert not [line for line in lines if PROBE_DEAD_RE.search(line)], lines
        assert "Dead-config pass: CLEAN" in lines, lines
        read = re.search(r"(\d+) of (\d+) bodies", proc.stdout)
        assert read, proc.stdout
        checked, total = int(read.group(1)), int(read.group(2))
        # Every body init deployed carries the marker; a fresh tree has no other.
        assert checked == 0 and total >= 30, (checked, total)
        assert f"({total} deployed by the harness" in proc.stdout, proc.stdout

    def test_an_unmanaged_body_citing_a_missing_path_is_still_flagged(self, adopter, tmp_path):
        """The skip is the marker's, not a blanket: the adopter's own body is
        read, a placeholder stem is not a citation, a present path passes, a
        root this tree does not have is the harness's, and one dead citation
        named twice is one issue."""
        program = _heredoc_after(_read(adopter / ADVISOR), "### Dead-Config Pass")
        tree = tmp_path / "tree"
        for rel, text in (
            (".claude/agents/mine.md",
             "# mine\nSee tools/cc/gone_for_good.py, then tools/cc/gone_for_good.py again, "
             "tools/cc/x.py and espalier/surface_contract.py.\n"),
            (".claude/agents/deployed.md",
             "---\nname: deployed\ndescription: one line\n---\n<!-- espalier:managed -->\n"
             "See tools/cc/not_here.py.\n"),
            (".claude/commands/go.md", "<!-- espalier:managed -->\nRun tools/cc/also_gone.py.\n"),
            (".claude/skills/own/SKILL.md", "# own\nRead tools/cc/present.py first.\n"),
            ("tools/cc/present.py", "x = 1\n"),
        ):
            path = tree / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        proc = _advisor(tree, program)
        assert proc.returncode == 0, proc.stderr[-800:]
        out = proc.stdout
        assert "DEAD CONFIG (1 issues):" in out, out
        assert "DEAD REF in mine: 'tools/cc/gone_for_good.py' not on disk" in out, out
        for skipped in ("x.py", "not_here", "also_gone", "present.py", "surface_contract"):
            assert skipped not in out, (skipped, out)
        assert "2 of 4 bodies" in out and "(2 deployed by the harness" in out, out

    def test_an_unmarked_deployed_body_reads_clean_on_the_adopters_tree(self, adopter, tmp_path):
        """An adopter who drops the marker to keep an edit (what the bodies tell
        them to do) is not then told the harness's own citations are dead."""
        tree = tmp_path / "tree"
        shutil.copytree(adopter / ".claude", tree / ".claude")
        (tree / "tools" / "cc").mkdir(parents=True)
        smoke = tree / ".claude" / "commands" / "smoke.md"
        unmarked = "\n".join(
            line for line in _read(smoke).splitlines() if "espalier:managed" not in line
        ) + "\n"
        smoke.write_text(unmarked, encoding="utf-8")
        assert not has_managed_marker(unmarked)
        proc = _advisor(tree, _heredoc_after(_read(adopter / ADVISOR), "### Dead-Config Pass"))
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "Dead-config pass: CLEAN" in proc.stdout, proc.stdout
        assert re.search(r"\b1 of \d+ bodies", proc.stdout), proc.stdout

    def test_on_this_checkout(self):
        """The control: this repository's bodies carry no marker, so every one
        is read, and the one placeholder stem a worked example cites is not
        a dead reference."""
        proc = _advisor(REPO_ROOT, _heredoc_after(_read(REPO_ROOT / ADVISOR), "### Dead-Config Pass"))
        assert proc.returncode == 0, proc.stderr[-800:]
        assert "Dead-config pass: CLEAN" in proc.stdout, proc.stdout
        read = re.search(r"(\d+) of (\d+) bodies", proc.stdout)
        assert read, proc.stdout
        assert read.group(1) == read.group(2) and int(read.group(2)) >= 30, proc.stdout
        assert "(0 deployed by the harness" in proc.stdout, proc.stdout

    def test_the_inline_marker_read_matches_the_engines(self):
        """The pass carries its own copy of the marker rule (the fence cannot
        import the engine): the regex, its window and the byte-order-mark step,
        pinned to ``has_managed_marker``'s verdict over the shapes that differ."""
        program = _heredoc_after(_read(REPO_ROOT / ADVISOR), "### Dead-Config Pass")
        start = program.index("SOURCE_PREFIXES = ")
        end = program.index("\nchecked = skipped = 0")
        namespace: dict[str, object] = {"re": re, "Path": Path}
        exec(program[start:end], namespace)  # noqa: S102 -- the fence's own definitions, nothing run
        is_managed = namespace["is_managed"]
        long_front = "---\nname: x\ndescription: " + "a long description " * 50 + "\n---\n"
        corpus = {
            "short frontmatter": "---\nname: x\n---\n<!-- espalier:managed -->\nbody\n",
            "long frontmatter": long_front + "<!-- espalier:managed -->\nbody\n",
            "hash leader": "# espalier:managed\nbody\n",
            "bom": "﻿<!-- espalier:managed -->\nbody\n",
            "no marker": "---\nname: x\n---\nbody\n",
            "quoted past the window": "# body\n" + ("text\n" * 200) + "<!-- espalier:managed -->\n",
            "in prose": "the marker espalier:managed is not on a comment line\n",
            "crlf frontmatter": "---\r\nname: x\r\n---\r\n<!-- espalier:managed -->\r\nbody\r\n",
        }
        assert len(long_front) > 600
        verdicts = {name: (is_managed(text), has_managed_marker(text)) for name, text in corpus.items()}
        assert all(mine == engine for mine, engine in verdicts.values()), verdicts
        assert verdicts["long frontmatter"] == (True, True) and verdicts["no marker"] == (False, False)


@_NEEDS_BASH
class TestTheSizeCensusCountsTheAdoptersFiles:
    def test_on_the_adopters_tree(self, adopter):
        body = _read(adopter / REPO_ANALYST)
        arch = _bash(adopter, _fence_after(body, "### 3. ARCHITECTURE ANALYSIS"))
        size = _section(arch, "Size")
        total = int(re.findall(r"(\d+)\s+total", size)[-1])
        vendored = _lines(list((adopter / "tools" / "cc").rglob("*.py")))
        assert vendored > 1000, vendored  # the deployed layer is there to be miscounted
        own = _own_files(adopter)
        assert total == _lines([p for p in own if p.suffix in COUNTED_SUFFIXES]), (total, size)
        assert total < min(vendored, *DEPENDENCY_LINES), (total, vendored)
        files = int(size.split()[0])
        assert files == len(own), (files, len(own))
        structure = _section(arch, "Directory structure")
        assert "./src/demo" in structure and "./tests" in structure, structure
        for section in ("Directory structure", "Module structure"):
            for deployed in ("tools/cc", ".claude", "node_modules", ".venv"):
                assert deployed not in _section(arch, section), (deployed, _section(arch, section))
        stack = _bash(adopter, _fence_after(body, "### 2. STACK DETECTION"))
        breakdown = _section(stack, "Language breakdown")
        counts = {ext: int(n) for n, ext in re.findall(r"^\s*(\d+)\s+(\S+)$", breakdown, re.M)}
        assert counts.get("py", 0) == sum(1 for p in own if p.suffix == ".py"), counts
        assert "js" not in counts, counts
        testing = _bash(adopter, _fence_after(body, "### 4. TESTING & QUALITY"))
        assert _section(testing, "Test count").strip() == "1", testing

    @pytest.mark.parametrize("heading", REPO_ANALYST_FENCES)
    def test_no_fence_names_the_harness_or_a_dependency_tree(self, adopter, heading):
        """The sister censuses (frameworks, database, test framework and count)
        walk the same files: no line of any fence names the deployed layer or a
        dependency tree. Before the class the Database census was ten lines of
        the deployed hooks on a tree with no database code."""
        out = _bash(adopter, _fence_after(_read(adopter / REPO_ANALYST), heading))
        offenders = [
            line for line in out.splitlines()
            if line.startswith(("./tools/cc", "./.claude", "tools/cc/", ".claude/"))
            or "/.venv/" in line or "/node_modules/" in line
        ]
        assert offenders == [], offenders

    def test_on_this_checkout(self):
        """The control: on this repository ``tools/cc/`` is its own source and
        stays in the count."""
        arch = _bash(REPO_ROOT, _fence_after(_read(REPO_ROOT / REPO_ANALYST), "### 3. ARCHITECTURE ANALYSIS"))
        total = int(re.findall(r"(\d+)\s+total", _section(arch, "Size"))[-1])
        vendored = _lines(list(checkout_rglob(REPO_ROOT / "tools" / "cc", "*.py")))
        assert total >= vendored, (total, vendored)
        assert "./tools/cc/hooks" in _section(arch, "Directory structure")


class TestTheWalkIsOneRule:
    """The three fences each define ``walk`` and ``own`` (a fence is one shell):
    the copies are byte-equal, every name the engine's walk skips is in them,
    and every caller passes tests only."""

    def _fences(self) -> list[str]:
        body = _read(REPO_ROOT / REPO_ANALYST)
        return [_fence_after(body, heading) for heading in REPO_ANALYST_FENCES]

    def test_the_three_copies_are_byte_equal(self):
        walks = [re.search(r"^walk\(\) \{\n(?:.*\n)*?\}$", f, re.M).group(0) for f in self._fences()]
        assert len(set(walks)) == 1 and len(walks) == 3, walks
        owns = collections.Counter(re.findall(r"^own\(\) \{.*\}$", "\n".join(self._fences()), re.M))
        assert sorted(owns.values()) == [3, 3], owns
        assert 'own() { walk "$@"; }' in owns, owns

    def test_the_walk_skips_every_name_the_engines_walk_skips(self):
        walk = re.search(r"^walk\(\) \{\n(?:.*\n)*?\}$", self._fences()[0], re.M).group(0)
        missing = [
            name for name in sorted(PRUNED)
            if f'! -path "*/{name}"' not in walk or f'! -path "*/{name}/*"' not in walk
        ]
        assert missing == [], missing

    def test_every_caller_passes_tests_only(self):
        calls = [
            line.strip() for f in self._fences() for line in f.splitlines()
            if re.match(r"\s*(own|walk) ", line)
        ]
        assert len(calls) >= 8, calls
        for call in calls:
            assert " -o " not in call or "\\(" in call, call
            assert not re.search(r" -(print|print0|exec|delete|ls)\b", call), call
