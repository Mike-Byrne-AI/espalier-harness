"""The shipped first-contact diagnostics report the adopter's tree, not the
harness's own source (the forward ledger's class on first-contact diagnostics).

Five deployed bodies census a tree: ``/analyze`` Step 3 (coverage gaps and
TODOs), the test-writer agent's discovery (coverage gaps) and its priority
list, the harness-config-advisor's dead-config pass (the source paths the
bodies cite), the repo-analyst's stack, architecture and testing fences
(language breakdown, frameworks, database, directory and module structure,
size, test count) and the code-reviewer's convention census (Phase 1: naming,
type hints, error handling, output and private-function style; Phase 3: the
test tree; Phase 4: the drift check). Each was written on this repository and
read its layout as the adopter's. On a fresh ``espalier init`` tree with no
``espalier/`` the coverage loop's glob stayed unexpanded and the census named a
module ``*``; the TODO census listed the vendored ``tools/cc/`` lines, never
the adopter's; the dead-config pass flagged the harness's own citations as dead
config in bodies the adopter did not write; the size census counted the 44
deployed ``tools/cc/`` files, the three ``.claude/workflows/*.js`` bodies and
every dependency tree as the adopter's (driven 2026-10-01 and 2026-10-06 on
init'd temp trees: the ledger's rows); then, with those pruned, it still
counted the seeded docs, so 38 of the 44 files it counted were the harness's
and Markdown was the first language; and the code-reviewer's Phase 1 and 4
grepped ``espalier/`` by name, printing bare ``0`` counts under the census
headings on a tree without it (its Type hints grep printed nothing anywhere:
its pattern ``-> `` read to grep as an option). No test drove any of the five
on an adopter's tree before this module, which is how four bodies drifted while
two siblings guard every ``espalier/`` read.

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
the fallback the block leaves behind, and its ``own`` walk prunes every path
the harness writes, a roster the engine's inventory owns
(``managed_inventory.harness_written_paths``) and renders into the deployed
body's one ``own`` line (``harness_config.render_own_walk``), so no body keeps
the list by hand. The adopter's own files here are a hand count
(``ADOPTER_FILES``: the stack row plus the plants outside a pruned directory),
so a test that reads the deployed fence needs no engine symbol and reds by its
assertion at the base. The dead-config pass skips a body that carries the
managed marker and says how many bodies it read; its inline read of the marker
is pinned equal to the engine's here.
"""
from __future__ import annotations

import argparse
import collections
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _adopter_tree import build_adopter_tree
from _live_tree import checkout_glob, checkout_rglob
from _stack_trees import ADOPTER_PREFIX, STACKS
from espalier import analyze
from espalier._safe_walk import visible
from espalier.managed_markers import has_managed_marker

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The five deployed bodies, and the heading each probe reads its fence after.
ANALYZE = ".claude/skills/analyze/SKILL.md"
TEST_WRITER = ".claude/agents/test-writer.md"
ADVISOR = ".claude/agents/harness-config-advisor.md"
REPO_ANALYST = ".claude/agents/repo-analyst.md"
REPO_ANALYST_FENCES = ("### 2. STACK DETECTION", "### 3. ARCHITECTURE ANALYSIS", "### 4. TESTING & QUALITY")
CODE_REVIEWER = ".claude/agents/code-reviewer.md"
#: The code-reviewer's two fences that walk the tree (Phase 3 reads the test
#: tree by name), each a self-host census and the adopter's in one fence.
CODE_REVIEWER_FENCES = ("### Phase 1", "### Phase 4")
#: The bodies this module walks, as ``(kind, glob)`` under ``.claude/``: every
#: fenced grep and every ``walk``/``own`` copy is read from these. A diff that
#: touches one earns the contract tier, whose ``-m contract`` deselects this
#: integration-classified file, so ``scripts/proof_tier.py`` adds the file for
#: a changed body by this roster (its ``BODY_KINDS``, pinned equal in
#: tests/test_proof_tier.py; DEF-4067).
BODY_KINDS = (("agents", "*.md"), ("commands", "*.md"), ("skills", "*/SKILL.md"))
SELF_HOST_OPEN = "<!-- espalier:self-host-only -->"
SELF_HOST_CLOSE = "<!-- /espalier:self-host-only -->"

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
#: environment names. The fences' ``walk`` is pinned to cover every name in it.
PRUNED = frozenset(analyze.DEFAULT_SKIP_PARTS | analyze.VENDORED_PARTS | {".venv", "venv"})
#: The adopter's own files, by hand: the stack row ``init`` was run on (its
#: ``.gitignore`` is still theirs after init appends to it) and the two plants
#: outside a pruned directory. Everything else on the tree the harness wrote,
#: and the expected numbers are computed from this set, not from the engine's
#: roster of what it writes, so the fence tests red by their own assertion at
#: a base that lacks the roster.
STACK_FILES = frozenset(STACKS[ADOPTER_PREFIX + "python"])
ADOPTER_FILES = STACK_FILES | {OWN_TODO, EGG_INFO}
COUNTED_SUFFIXES = (".py", ".js", ".ts", ".go", ".rs")
#: A Session Log row, as the deployed handoff writes one: the harness's record,
#: which the census counted as the adopter's Markdown after the first handoff.
SESSION_ROW = "memory/session-log.d/2026-10-31-000000-local.md"
#: An adopter's own files at paths the harness writes, or might: planted before
#: ``init``, which keeps each, and every one stays in the census. A ``reports/``
#: package, a ``tools/`` package, their own ``docs/HOOKS.md`` and
#: ``docs/external/`` notes, a ``bench/`` of their own.
LOOKALIKES = {
    "reports/__init__.py": "",
    "reports/models.py": "def load():\n    try:\n        return 1\n    except:\n        return 0\n",
    "docs/HOOKS.md": "# Our webhooks\n",
    "docs/external/vendor-api.md": "# Vendor API notes\n",
    "tools/__init__.py": "",
    "bench/README.md": "# Benchmarks\n",
}

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
        (SESSION_ROW, "| 2026-10-31 | **local: a row** | body |\n"),
    ):
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tree


def _git_in(tree: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(tree), check=True, capture_output=True,
                   text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def lookalike(tmp_path_factory) -> Path:
    """The Python adopter tree with :data:`LOOKALIKES` committed before
    ``init`` and ``install-ci`` run, built once, read only."""
    from espalier.cli import cmd_init, cmd_install_ci

    tree = build_adopter_tree(tmp_path_factory.mktemp("lookalike"), stack="python", tree="git")
    for rel, text in LOOKALIKES.items():
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git_in(tree, "add", "-A")
    _git_in(tree, "commit", "-qm", "the adopter's own reports, tools, docs and bench")
    assert cmd_init(argparse.Namespace(repo=str(tree), config=None)) == 0
    assert cmd_install_ci(argparse.Namespace(repo=str(tree))) == 0
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


def _adopter_files(tree: Path) -> list[Path]:
    """The adopter's own files on ``tree``, by this module's hand count
    (``ADOPTER_FILES``), each checked present."""
    out = [tree / rel for rel in sorted(ADOPTER_FILES)]
    missing = [p for p in out if not p.is_file()]
    assert missing == [], missing
    return out


def _harness_files(tree: Path) -> list[str]:
    """Every file on ``tree`` outside a pruned directory that is not the
    adopter's: what ``init`` and ``install-ci`` wrote, as the tree holds it."""
    out: list[str] = []
    for path in tree.rglob("*"):
        rel = path.relative_to(tree)
        if not path.is_file() or set(rel.parts) & PRUNED or rel.parts[0] == ".git":
            continue
        if rel.as_posix() not in ADOPTER_FILES:
            out.append(rel.as_posix())
    return sorted(out)


def _covered(rel: str, roster: tuple[str, ...]) -> bool:
    """Whether a roster entry prunes ``rel``, as ``find -path`` reads it: the
    path itself, a listed directory's member, or a suffix glob's match."""
    return any(
        rel == p or (p.endswith("/") and rel.startswith(p)) or ("*" in p and fnmatch.fnmatchcase(rel, p))
        for p in roster
    )


def _own_listing(tree: Path) -> set[str]:
    """The deployed repo-analyst's ``own -type f`` on ``tree``: the ledger
    probe's read (DEF-4066), the first fence's ``walk`` and ``own`` alone."""
    body = _read(tree / REPO_ANALYST)
    start = body.index("walk() {")
    end = body.index("\n", body.index("own() {"))
    return set(_bash(tree, body[start:end] + "\nown -type f").split())


def _walk_fences(root: Path) -> list[tuple[str, str]]:
    """Every bash fence of a ``.claude`` body under ``root`` that defines the
    ``walk`` and ``own`` pair, as ``(body, fence)``: the population the walk
    rule holds, read from the bodies, so a sixth copy is held too."""
    bodies: list[Path] = []
    for kind, pattern in BODY_KINDS:
        base = root / ".claude" / kind
        bodies += visible(checkout_glob(base, pattern), base)
    found = []
    for body in bodies:
        for fence in re.findall(r"```bash\n(.*?)```", _read(body), re.S):
            if re.search(r"^walk\(\) \{$", fence, re.M):
                found.append((body.relative_to(root).as_posix(), fence))
    return found


def _bare_zeros(out: str) -> list[str]:
    """The lines that are a bare ``0``: a count printed with nothing to count,
    which reads as a finding under a census heading (DEF-4065's probe)."""
    return [line for line in out.splitlines() if line.strip() == "0"]


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


#: The adopter's Python modules outside its test tree, as the code-reviewer's
#: Phase 1 lists them (``__init__.py`` included: it can hold code).
ADOPTER_MODULES = ("src/demo/__init__.py", "src/demo/app.py", OWN_TODO)
HARNESS_PATHS = ("espalier", "tools/cc", ".claude", ".venv", "node_modules")


@_NEEDS_BASH
class TestTheConventionCensusReadsTheAdoptersSource:
    """The code-reviewer's Phase 1 and Phase 4 grepped ``espalier/`` by name on
    every tree and Phase 3 ``tests/``; on an adopter's tree the counts under the
    census headings were bare zeros, and on a fused tree the vendored engine's
    (DEF-4065). The self-host census sits in the block init strips; what is
    left walks the adopter's own modules and stands down in words."""

    @pytest.mark.parametrize("shell", SHELLS)
    def test_phase_1_on_the_adopters_tree(self, adopter, shell):
        fence = _fence_after(_read(adopter / CODE_REVIEWER), "### Phase 1")
        assert not re.search(r"grep[^\n]* espalier/", fence), "the harness's own census reached the adopter's copy"
        proc = _run(adopter, fence, shell)
        assert proc.returncode == 0 and "no matches found" not in proc.stderr, proc.stderr
        out = proc.stdout
        # A count of 0 here is a measurement of the demo app (no stderr print,
        # no private def); the bare-zero rule is the no-Python tree's below.
        status = _section(out, "SURFACE STATUS")
        assert f"Python modules outside the test tree: {len(ADOPTER_MODULES)}" in status, status
        assert "tests/ present" in status and "docs/CONVENTIONS.md present" in status, status
        naming = [line for line in _section(out, "Naming style (multi-file sample)").splitlines() if line]
        assert naming and all(line.startswith("./src/demo/") for line in naming), naming
        # The Type hints counts, dead on every tree while their pattern read as
        # an option (DEF-1059): one line a module from each of the two greps.
        # The `^def ` grep beside it prints into the same section, so a single
        # line proves nothing: the -> half alone going quiet halves the count.
        hints = [line for line in _section(out, "Type hints coverage").splitlines() if line]
        assert len(hints) == 2 * len(ADOPTER_MODULES), hints
        for harness_path in HARNESS_PATHS:
            assert harness_path not in out, (harness_path, out)

    @pytest.mark.parametrize("shell", SHELLS)
    def test_phase_3_reads_the_test_tree(self, adopter, shell):
        proc = _run(adopter, _fence_after(_read(adopter / CODE_REVIEWER), "### Phase 3"), shell)
        assert proc.returncode == 0 and "no matches found" not in proc.stderr, proc.stderr
        assert "tests/test_app.py:" in _section(proc.stdout, "Test function naming"), proc.stdout
        assert "tools/cc" not in proc.stdout, proc.stdout

    @pytest.mark.parametrize("shell", SHELLS)
    def test_phase_4_on_the_adopters_tree(self, adopter, shell):
        fence = _fence_after(_read(adopter / CODE_REVIEWER), "### Phase 4")
        assert not re.search(r"grep[^\n]* espalier/", fence), fence
        proc = _run(adopter, fence, shell)
        assert proc.returncode == 0 and "no matches found" not in proc.stderr, proc.stderr
        out = proc.stdout
        assert "SURFACE MISSING" not in out and _bare_zeros(out) == [], out
        for header in ("Bare except violations", "Missing type hints on public functions",
                       "Print to stdout in source (convention: use stderr)", "Hardcoded path separators"):
            assert f"=== {header} ===" in out, (header, out)
        for harness_path in HARNESS_PATHS:
            assert harness_path not in out.split("=== Bare except violations ===", 1)[1], (harness_path, out)

    def test_a_tree_without_python_stands_down_in_words(self, tmp_path, adopter):
        """A Node adopter's census says what it did not evaluate; before the
        class it printed three bare zeros under the census headings."""
        tree = tmp_path / "node"
        (tree / "src").mkdir(parents=True)
        (tree / "src" / "index.js").write_text("export default 1;\n", encoding="utf-8")
        body = _read(adopter / CODE_REVIEWER)
        one = _bash(tree, _fence_after(body, "### Phase 1"))
        assert "no Python modules outside the test tree — phase 1 NOT EVALUATED" in one, one
        assert "test tree MISSING (tests/, test/)" in one, one
        assert "=== Naming style" not in one and _bare_zeros(one) == [], one
        three = _bash(tree, _fence_after(body, "### Phase 3"))
        assert "test tree MISSING (tests/, test/) — phase 3 NOT EVALUATED" in three, three
        assert "=== Test function naming" not in three and _bare_zeros(three) == [], three
        four = _bash(tree, _fence_after(body, "### Phase 4"))
        assert "SURFACE MISSING: no Python modules outside the test tree" in four, four
        assert "=== Bare except violations" not in four and _bare_zeros(four) == [], four
        # A Node project's test/ holds no Python: the pytest checks stand down
        # too, where they printed empty sections and a bare 0 (the review's m6).
        (tree / "test").mkdir()
        (tree / "test" / "index.test.js").write_text("test('x', () => {});\n", encoding="utf-8")
        three = _bash(tree, _fence_after(body, "### Phase 3"))
        assert "index.test.js" in _section(three, "Test file naming"), three
        assert "no Python test files under test/ — the pytest checks are NOT EVALUATED" in three, three
        assert "=== Test function naming" not in three and _bare_zeros(three) == [], three

    @pytest.mark.parametrize("shell", SHELLS)
    def test_an_adopters_files_at_the_harness_paths_are_read(self, lookalike, shell):
        """Their ``reports/`` package is source the drift check reads, where a
        roster of every path the harness might write dropped it (the review's
        M1)."""
        four = _run(lookalike, _fence_after(_read(lookalike / CODE_REVIEWER), "### Phase 4"), shell)
        assert four.returncode == 0 and "no matches found" not in four.stderr, four.stderr
        assert "./reports/models.py:4:" in _section(four.stdout, "Bare except violations"), four.stdout

    def test_the_two_halves_of_each_fence_print_the_same_sections(self):
        """The self-host census and the adopter's are kept by hand side by
        side: a section added to one alone reaches one audience (the review's
        m8)."""
        body = _read(REPO_ROOT / CODE_REVIEWER)
        for heading in CODE_REVIEWER_FENCES:
            fence = _fence_after(body, heading)
            block = fence[fence.index(SELF_HOST_OPEN):fence.index(SELF_HOST_CLOSE)]
            fallback = fence[fence.index('if [ -z "$CENSUS" ]'):]
            headers = [set(re.findall(r'echo "=== (.+?) ==="', part)) for part in (block, fallback)]
            assert headers[0] and headers[0] == headers[1], (heading, headers)

    def test_on_this_checkout(self):
        """The control: the self-host block init strips is kept here, so the
        census is the engine's, ``espalier/`` against ``tests/``, and the Type
        hints count prints (it printed nothing until DEF-1059's ``-e``)."""
        body = _read(REPO_ROOT / CODE_REVIEWER)
        one = _bash(REPO_ROOT, _fence_after(body, "### Phase 1"))
        assert "espalier/ present" in _section(one, "SURFACE STATUS"), one
        naming = [line for line in _section(one, "Naming style (multi-file sample)").splitlines() if line]
        assert naming and all(line.startswith("espalier/") for line in naming), naming
        hints = [line for line in _section(one, "Type hints coverage").splitlines() if line]
        assert len(hints) == 20 and all(line.startswith("espalier/") for line in hints), hints
        four = _bash(REPO_ROOT, _fence_after(body, "### Phase 4"))
        assert "=== Bare except violations ===" in four and "SURFACE MISSING" not in four, four


_GREP_USAGE_RE = re.compile(r"(?i)grep: (unknown|invalid|illegal) option|usage: grep")


def _fenced_grep_lines(body: str) -> list[str]:
    """Every line inside a code fence that runs ``grep``, continuations joined
    and a leading ``&&`` or ``||`` made runnable on its own: the DEF-1059
    probe's read of a body."""
    lines = body.replace("\\\n", " ").split("\n")
    out: list[str] = []
    fenced = False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced and re.search(r"\bgrep\b", line) and not line.lstrip().startswith("#"):
            out.append(re.sub(r"^\s*(&&|\|\|)", "true &&", line))
    return out


#: What a fenced line reads that its fence set: a census's file list and test
#: tree, so a ``printf "$SRC" | xargs grep`` line hands grep a file and runs
#: it (an unset list ran no grep at all under BSD xargs, the review's M3).
_FENCE_VARS = "SRC=espalier/__init__.py; TDIR=tests; "


def _grep_usage_error(command: str) -> bool:
    """True when ``command``, its redirects stripped and run under bash with
    the fence's variables set and nothing on stdin, makes grep refuse its own
    arguments."""
    proc = subprocess.run(
        [_BASH, "-c", _FENCE_VARS + re.sub(r"[0-9&]?>[ ]*(&[0-9]|/dev/null)", "", command)],
        cwd=str(REPO_ROOT), capture_output=True, input=b"", timeout=FENCE_TIMEOUT,
    )
    return bool(_GREP_USAGE_RE.search(proc.stderr.decode("utf-8", errors="replace")))


#: ``grep``, its options (never ``-e``, ``--regexp``, ``-f``, ``--file`` or a
#: bare ``--``, after which a dash-led operand is a pattern), then a quoted
#: operand opening with ``-``: a pattern grep reads as an option.
_OPTION_LED_PATTERN_RE = re.compile(
    r"""\bgrep(?:\s+-(?!e\b|-regexp\b|f\b|-file\b|-(?:\s|$))\S*)*\s+["']-"""
)


def _pattern_reads_as_an_option(command: str) -> bool:
    """True when a ``grep`` in ``command`` takes a quoted pattern opening
    with ``-`` as its first operand, with no ``-e`` before it and no ``--``:
    what grep reads as an option, read from the text alone, so a line whose
    grep never runs where the test does is held too."""
    return bool(_OPTION_LED_PATTERN_RE.search(command))


def _shipped_bodies() -> list[Path]:
    """Every agent, command and skill body this checkout ships."""
    bodies: list[Path] = []
    for kind, pattern in BODY_KINDS:
        base = REPO_ROOT / ".claude" / kind
        bodies += visible(checkout_glob(base, pattern), base)
    return bodies


@_NEEDS_BASH
class TestEveryFencedGrepParses:
    """The code-reviewer's Type hints grep spelled its pattern ``-> ``, which
    grep read as an option and refused into ``2>/dev/null``, so the line
    printed nothing on every tree since 0.8.0b1 (DEF-1059). The ledger probe's
    loop, as a test: no fenced grep in any agent body is refused by grep."""

    def test_the_detectors_read_the_bare_pattern_and_not_its_e_twin(self):
        assert _grep_usage_error('grep -c "-> " -')
        assert not _grep_usage_error('grep -c -e "-> " -')
        # The adopter's shape: a file list piped to xargs.
        assert _grep_usage_error('printf \'%s\\n\' "$SRC" | tr \'\\n\' \'\\0\' | xargs -0 grep -cH "-> "')
        for bare in ('grep -c "-> " espalier/*.py 2>/dev/null | sort',
                     'printf x | xargs -0 grep -cH "-> " 2>/dev/null | head -10'):
            assert _pattern_reads_as_an_option(bare), bare
            assert not _pattern_reads_as_an_option(bare.replace('"-> "', '-e "-> "')), bare
        assert not _pattern_reads_as_an_option('grep -v "__pycache__\\|file=sys.stderr" | grep -c --include="*.py" "x"')
        assert not _pattern_reads_as_an_option('grep -n -- "-> " x.py')

    def test_no_shipped_body_spells_a_grep_pattern_that_reads_as_an_option(self):
        """The text read over every agent, command and skill body: a line the
        run below cannot drive is held here."""
        bodies = _shipped_bodies()
        assert len(bodies) >= 30, len(bodies)
        lines = [(body.name, line) for body in bodies for line in _fenced_grep_lines(_read(body))]
        assert len(lines) >= 60, len(lines)
        flagged = [(name, line) for name, line in lines if _pattern_reads_as_an_option(line)]
        assert flagged == [], flagged

    def test_no_agent_body_runs_a_grep_whose_pattern_reads_as_an_option(self):
        bodies = [body for body in _shipped_bodies() if body.parent.name == "agents"]
        assert len(bodies) >= 7, bodies
        lines = [(body.name, line) for body in bodies for line in _fenced_grep_lines(_read(body))]
        assert len(lines) >= 40, len(lines)
        refused = [(name, line) for name, line in lines if _grep_usage_error(line)]
        assert refused == [], refused


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
        # The deployed tools/ whole: the citation root, and the hook scripts
        # the copied settings wire (the pass reads them from args[]).
        shutil.copytree(adopter / "tools", tree / "tools")
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


#: What the harness writes at the adopter's root, as the repo-analyst's lines
#: print it: a directory or a file no census of the adopter's own files names.
HARNESS_ROOTS = ("./tools", "./.claude", "./cc", "./reports", "./memory", "./task-packs",
                 "./docs", "./.github", "./.espalier", "./espalier.toml", "./CLAUDE.md")


@_NEEDS_BASH
class TestTheSizeCensusCountsTheAdoptersFiles:
    def test_on_the_adopters_tree(self, adopter):
        body = _read(adopter / REPO_ANALYST)
        arch = _bash(adopter, _fence_after(body, "### 3. ARCHITECTURE ANALYSIS"))
        size = _section(arch, "Size")
        total = int(re.findall(r"(\d+)\s+total", size)[-1])
        vendored = _lines(list((adopter / "tools" / "cc").rglob("*.py")))
        assert vendored > 1000, vendored  # the deployed layer is there to be miscounted
        own = _adopter_files(adopter)
        assert total == _lines([p for p in own if p.suffix in COUNTED_SUFFIXES]), (total, size)
        assert total < min(vendored, *DEPENDENCY_LINES), (total, vendored)
        files = int(size.split()[0])
        assert files == len(own) == 8, (files, len(own))
        structure = _section(arch, "Directory structure")
        assert "./src/demo" in structure and "./tests" in structure, structure
        # Derived from the files: a directory only the harness populated
        # (docs/, memory/, task-packs/, .github/workflows/) is not the adopter's.
        for section in ("Directory structure", "Module structure"):
            for deployed in HARNESS_ROOTS + ("node_modules", ".venv"):
                assert deployed not in _section(arch, section), (deployed, _section(arch, section))
        stack = _bash(adopter, _fence_after(body, "### 2. STACK DETECTION"))
        breakdown = _section(stack, "Language breakdown")
        counts = {ext: int(n) for n, ext in re.findall(r"^\s*(\d+)\s+(\S+)$", breakdown, re.M)}
        assert counts.get("py", 0) == sum(1 for p in own if p.suffix == ".py") == 4, counts
        assert counts.get("md", 0) == 1 and sum(counts.values()) == len(own), counts  # not a Markdown repository
        assert "js" not in counts, counts
        testing = _bash(adopter, _fence_after(body, "### 4. TESTING & QUALITY"))
        assert _section(testing, "Test count").strip() == "1", testing

    def test_the_own_walk_lists_the_adopters_files_alone(self, adopter):
        """The ledger probe's read (DEF-4066): the deployed ``own -type f`` on an
        init'd tree, which listed ``memory/README.md`` and the seeded docs while
        the walk pruned the two deployed layers alone; and the Session Log row
        a handoff wrote after init stays the harness's (the review's M2)."""
        listed = _own_listing(adopter)
        assert listed == {"./" + rel for rel in ADOPTER_FILES}, sorted(listed)

    def test_an_adopters_files_at_the_harness_paths_stay_counted(self, lookalike):
        """Their ``reports/`` and ``tools/`` packages, their own
        ``docs/HOOKS.md`` and ``docs/external/`` notes and their ``bench/``:
        init keeps each, and so does the census (the review's M1)."""
        listed = _own_listing(lookalike)
        assert listed == {"./" + rel for rel in STACK_FILES | set(LOOKALIKES)}, sorted(listed)

    def test_every_file_the_harness_wrote_is_on_the_engines_roster(self, adopter):
        """The roster the deployed line is rendered from covers the tree as it
        is after init, install-ci and a handoff row, so a new deployed file that
        joins no inventory list reds here; and the line is that render."""
        from espalier.harness_config import own_walk_prunes
        from espalier.managed_inventory import census_prune_paths

        roster = census_prune_paths(adopter)
        written = _harness_files(adopter)
        assert len(written) > 40 and SESSION_ROW in written, written
        missed = [rel for rel in written if not _covered(rel, roster)]
        assert missed == [], missed
        body = _read(adopter / REPO_ANALYST)
        owns = re.findall(r"^own\(\) \{.*\}$", body, re.M)
        assert owns == ['own() { walk "$@" ' + own_walk_prunes(roster) + '; }'] * 3, owns

    @pytest.mark.parametrize("heading", REPO_ANALYST_FENCES)
    def test_no_fence_names_the_harness_or_a_dependency_tree(self, adopter, heading):
        """The sister censuses (frameworks, database, test framework and count)
        walk the same files: no line of any fence names the deployed layer, a
        seeded file or a dependency tree. Before the class the Database census
        was ten lines of the deployed hooks on a tree with no database code."""
        out = _bash(adopter, _fence_after(_read(adopter / REPO_ANALYST), heading))
        offenders = [
            line for line in out.splitlines()
            if line.startswith(HARNESS_ROOTS + ("tools/cc/", ".claude/"))
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
    """The five fences each define ``walk`` and ``own`` (a fence is one shell):
    the copies are byte-equal, every name the engine's walk skips is in them,
    every caller passes tests only, and the deployed ``own`` line is the one
    the deploy renders."""

    def _fences(self) -> list[str]:
        return [fence for _body, fence in _walk_fences(REPO_ROOT)]

    def test_every_copy_is_byte_equal(self):
        found = _walk_fences(REPO_ROOT)
        assert {body for body, _fence in found} >= {REPO_ANALYST, CODE_REVIEWER}, found
        fences = [fence for _body, fence in found]
        assert len(fences) >= 5, len(fences)
        walks = [re.search(r"^walk\(\) \{\n(?:.*\n)*?\}$", f, re.M).group(0) for f in fences]
        assert len(set(walks)) == 1, walks
        owns = collections.Counter(re.findall(r"^own\(\) \{.*\}$", "\n".join(fences), re.M))
        assert sorted(owns.values()) == [len(fences)] * 2, owns
        assert 'own() { walk "$@"; }' in owns, owns

    def test_the_deployed_own_line_renders_in_every_fence(self):
        """The render keys on the fallback's shape, so each fence's copy is the
        line it rewrites and the self-host redefinition is not."""
        from espalier.harness_config import render_own_walk

        for fence in self._fences():
            rendered = render_own_walk(fence, ["cc/"])
            changed = [
                (a, b) for a, b in zip(fence.splitlines(), rendered.splitlines()) if a != b
            ]
            assert len(changed) == 1 and changed[0][0].startswith('own() { walk "$@" ! -path'), changed
            assert changed[0][1] == 'own() { walk "$@" ! -path "./cc" ! -path "./cc/*"; }', changed
            assert 'own() { walk "$@"; }' in rendered

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
            if re.match(r"\s*(own|walk) ", line) or re.match(r"\s*\w+=\$\((own|walk) ", line)
        ]
        assert len(calls) >= 10, calls
        for call in calls:
            assert " -o " not in call or "\\(" in call, call
            assert not re.search(r" -(print|print0|exec|delete|ls)\b", call), call
