"""The pattern path's compiled size, held inside a band: TP-707's ratchet (1-B).

At b3eefcf every Bash, PowerShell, mutation and MCP call loaded write_guard's
pattern path (``tools/cc/hooks/write_guard.py::_load_the_pattern_path``), and
what that load costs tracks the characters it compiles. Task 0 read it on the
Air (3.14.7, the checkout's venv, under the box lock, n=10 a point,
2026-11-12): the two pattern modules import in 180.3 ms (IQR 171.2 to 182.1) at
b3eefcf, whose path compiles 206,695 characters, and in 282.9 ms (276.3 to
289.2) at caae022, #516's head, which compiles 387,130. 1-C read the same split
on Windows (3.11.9, 2026-11-12): 202.5 ms (195.6 to 203.9) at 43d8879 against
337.8 (329.7 to 350.1) at caae022.

The live row reads the figure with ``scripts/guard_cost_census.py``'s
``--compile`` reader (``::COMPILE_CHILD``), which runs in a fresh interpreter,
so an import elsewhere in this run cannot hide a growth. It reds where the
compiled characters or the shared command-position fragment
(``_bash_patterns._CMD_POS_NO_VERB``) leave a 10% band around the pinned
figure: past the ceiling a growth owes its per-call figure, and under the floor
the change that lowered it (a lever, or a reader that stopped counting the
imports) owes the band moved down. It also reds where the reader read no
pattern at all; where the loader compiled none of its own, since the imports
compile about 96% of the figure and a loader that loads nothing would sit
inside the band; and where no pattern read embeds the fragment. The check is a
pure function, tested on fixed figures: a mutated tree would drift with every
guard lane. The live row reads through the same helper as three synthetic
hooks trees (grown past both ceilings, a loader that loads nothing, a tree that
compiles nothing), each compiling its bulk at import as the real tree does, so
a reading the live row drops on its way to the check reds there.

The count's boundary: what the two pattern modules and ``write_guard`` compile
as they import, and what the loader compiles. A pattern compiled later is
outside it: on first use behind a cache (pinned by name below, so a new one
owes the per-call figure of the kind that reaches it), or inside a check at
call time (the reader never judges a call). The fragment ceiling reads
``_CMD_POS_NO_VERB`` alone, so a growth in ``_CMD_POS_VERB_PREFIX`` meets only
the character ceiling.

What the +10% line catches (ruling 2b), at b3eefcf's figures: a #516-sized
jump, and any growth of 21,306 compiled characters or of the fragment past
1,750. It does not catch one 100-character alternation added to the fragment
(1,680 characters; 65 copies across the 61 patterns that embed it, so +6,500
compiled characters, +3.1%), though a second one reds on the fragment. Nor does
it catch a second copy of the fragment in one pattern (+1,580, +0.8%): thirteen
such copies pass and the fourteenth reds.
"""
# slow-exempt: four census children, each a fresh interpreter compiling the hooks' patterns (under two seconds on the Air)
from __future__ import annotations

import ast
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "guard_cost_census.py"
HOOKS = REPO_ROOT / "tools" / "cc" / "hooks"

#: The reading the band is cut from (ruling 2b), with where and how it was
#: read. A re-pin replaces it whole (RULE); the limits below follow from it.
PINNED = {
    "at": "b3eefcf",
    "date": "2026-11-12",
    "python": "3.14.7, the checkout's venv (3.11 reads up to 516 more: the standard library's compiles a "
              "hook frame reaches move by interpreter and by what its startup imported first)",
    "hooks_patterns": 308,
    "hooks_chars": 206_695,
    "loader_patterns": 8,
    "fragment_len": 1_580,
    "embedding_patterns": 61,
    "fragment_copies": 65,
    "per_call": "Task 0's --calls 30 on the Air at b3eefcf (TP-707 Landing)",
}


def _ceil_to(n: int, step: int) -> int:
    return -(-n // step) * step


#: Plus 10%, rounded up to a thousand characters (the fragment: to fifty).
CEILING_COMPILED_CHARS = _ceil_to(-(-PINNED["hooks_chars"] * 11 // 10), 1_000)
CEILING_FRAGMENT_LEN = _ceil_to(-(-PINNED["fragment_len"] * 11 // 10), 50)
#: Less 10%, rounded down the same way.
FLOOR_COMPILED_CHARS = PINNED["hooks_chars"] * 9 // 10 // 1_000 * 1_000
FLOOR_FRAGMENT_LEN = PINNED["fragment_len"] * 9 // 10 // 50 * 50

#: The figures the check reads, at the pinned reading.
BASE = {"loader_ran": True, "fragment_found": True,
        **{k: PINNED[k] for k in ("hooks_patterns", "hooks_chars", "loader_patterns", "fragment_len",
                                  "embedding_patterns")}}
#: caae022's figures as the census's ``--at`` read them on 2026-11-12, held as
#: data, since CI has no ref to it (the pack's prototype read 387,144 on an
#: interpreter whose startup had not imported glob and fnmatch first). It
#: predates the loader, so the census read its imports alone, and that reds too.
CAAE022 = {"loader_ran": False, "fragment_found": True, "hooks_patterns": 288, "hooks_chars": 387_130,
           "loader_patterns": 0, "fragment_len": 4_301, "embedding_patterns": 60}

#: The pattern modules' functions that compile a pattern on first use behind a
#: cache, by file: outside the count, each one's per-call cost is its kind's.
FIRST_USE_COMPILES = {"_bash_patterns.py": {"_carrier_fed_remove_re"}}
_PATTERN_MODULES = ("_bash_patterns.py", "_speedbump.py", "write_guard.py")

WHERE = "scripts/guard_cost_census.py::COMPILE_CHILD reads that name"
RULE = ("Past a ceiling, a growth owes a measured per-call figure at or under main's "
        "(scripts/guard_cost_census.py --calls 30 under the box lock, at the lane's head and with --at origin/main; "
        "python3, or python or py -3 where python3 is not Python 3) or the operator's word. "
        "Under a floor, the change that lowered the figure moves the band down in its own lane. "
        "Either way, re-pin: run scripts/guard_cost_census.py --compile --json at the lane's head, replace "
        "PINNED from it, and name the --calls lines or the ruling's ack id in PINNED['per_call']; the limits "
        "follow, and the rows that hold literal arithmetic (the limits, TestWhatTheLineCatches, the synthetic "
        "trees) are re-derived from the new PINNED; fragment_copies is counted by hand, a copy per embedding. "
        "A red on main whose suspects were each green against their own base is their sum: the later "
        "merge re-lands with the re-pin (TP-707 1-B).")


def _load_census() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("guard_cost_census_under_ratchet", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _load_census()


def breaches(figures: dict) -> list[str]:
    """Each way ``figures`` (the census's ``compile`` block) fails the ratchet,
    one sentence each; empty when it holds."""
    found = []
    if not figures.get("loader_ran"):
        found.append("the census did not run write_guard._load_the_pattern_path, so the loader's own "
                     f"compiles went uncounted ({WHERE})")
    elif not figures.get("loader_patterns"):
        found.append("write_guard._load_the_pattern_path compiled no pattern of its own, so its compiles "
                     "moved to import or were dropped; read the per-call figure either way")
    if not figures.get("hooks_patterns"):
        found.append("the census read no pattern compiled from the hooks folder")
    if not figures.get("fragment_found"):
        found.append(f"the census found no _bash_patterns._CMD_POS_NO_VERB, so the fragment's length "
                     f"went unread ({WHERE})")
    elif not figures.get("embedding_patterns"):
        found.append("no pattern the census read embeds _CMD_POS_NO_VERB: the command-position family "
                     "compiles outside this count, so its lane owes the per-call figure of each kind "
                     "that reaches it")
    chars = figures.get("hooks_chars") or 0
    if chars > CEILING_COMPILED_CHARS:
        found.append(f"the pattern path compiles {chars:,} characters, past the ceiling of "
                     f"{CEILING_COMPILED_CHARS:,}")
    elif chars < FLOOR_COMPILED_CHARS:
        found.append(f"the pattern path compiles {chars:,} characters, under the floor of "
                     f"{FLOOR_COMPILED_CHARS:,}: a lower figure moves the band down, and a reader that "
                     "stopped counting the imports reads low too")
    fragment = figures.get("fragment_len") or 0
    if fragment > CEILING_FRAGMENT_LEN:
        found.append(f"_CMD_POS_NO_VERB is {fragment:,} characters, past the ceiling of "
                     f"{CEILING_FRAGMENT_LEN:,}")
    elif figures.get("fragment_found") and fragment < FLOOR_FRAGMENT_LEN:
        found.append(f"_CMD_POS_NO_VERB is {fragment:,} characters, under the floor of "
                     f"{FLOOR_FRAGMENT_LEN:,}: a shorter fragment moves the band down")
    return found


def _is_cache(decorator: ast.expr) -> bool:
    return re.search(r"\b(?:lru_cache|cache)\b", ast.unparse(decorator)) is not None


def _calls_compile(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "compile"
               for n in ast.walk(node))


def first_use_compiles(hooks: Path) -> dict[str, set[str]]:
    """The functions in ``hooks``' pattern modules that a cache decorator wraps
    and whose body compiles a pattern, by file."""
    found: dict[str, set[str]] = {}
    for name in _PATTERN_MODULES:
        path = hooks / name
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(_is_cache(d) for d in node.decorator_list) and _calls_compile(node)):
                found.setdefault(name, set()).add(node.name)
    return found


def _grown(*, chars: int = 0, fragment: int = 0) -> dict:
    return {**BASE, "hooks_chars": BASE["hooks_chars"] + chars, "fragment_len": BASE["fragment_len"] + fragment}


class TestTheBand:
    def test_the_limits_are_the_pinned_figure_plus_and_less_ten_percent(self):
        assert (CEILING_COMPILED_CHARS, CEILING_FRAGMENT_LEN) == (228_000, 1_750)
        assert (FLOOR_COMPILED_CHARS, FLOOR_FRAGMENT_LEN) == (186_000, 1_400)

    def test_the_pinned_reading_names_where_and_how_it_was_read(self):
        for key in ("at", "date", "python", "per_call"):
            assert isinstance(PINNED[key], str) and PINNED[key].strip(), key


class TestTheCeilingCheck:
    def test_the_base_holds(self):
        assert breaches(BASE) == []

    def test_the_compiled_characters_red_one_past_the_ceiling(self):
        got = breaches({**BASE, "hooks_chars": CEILING_COMPILED_CHARS + 1})
        assert got == ["the pattern path compiles 228,001 characters, past the ceiling of 228,000"]

    def test_the_compiled_characters_hold_at_the_ceiling_and_one_under(self):
        assert breaches({**BASE, "hooks_chars": CEILING_COMPILED_CHARS}) == []
        assert breaches({**BASE, "hooks_chars": CEILING_COMPILED_CHARS - 1}) == []

    def test_the_fragment_reds_one_past_the_ceiling(self):
        got = breaches({**BASE, "fragment_len": CEILING_FRAGMENT_LEN + 1})
        assert got == ["_CMD_POS_NO_VERB is 1,751 characters, past the ceiling of 1,750"]

    def test_the_fragment_holds_at_the_ceiling_and_one_under(self):
        assert breaches({**BASE, "fragment_len": CEILING_FRAGMENT_LEN}) == []
        assert breaches({**BASE, "fragment_len": CEILING_FRAGMENT_LEN - 1}) == []

    def test_caae022_reds_on_both_ceilings_and_its_missing_loader(self):
        got = breaches(CAAE022)
        assert len(got) == 3, got
        assert "_load_the_pattern_path" in got[0] and "COMPILE_CHILD" in got[0], got
        assert "387,130 characters" in got[1] and "4,301 characters" in got[2], got

    def test_a_reading_of_no_pattern_reds_though_its_fragment_sits_in_the_band(self):
        got = breaches({**BASE, "hooks_patterns": 0, "hooks_chars": 0, "loader_patterns": 0,
                        "embedding_patterns": 0})
        assert len(got) == 4, got
        assert "compiled no pattern of its own" in got[0], got
        assert got[1] == "the census read no pattern compiled from the hooks folder", got
        assert "embeds _CMD_POS_NO_VERB" in got[2] and "under the floor of 186,000" in got[3], got

    def test_a_reading_without_the_loader_or_the_fragment_reds(self):
        got = breaches({**BASE, "loader_ran": False, "fragment_found": False, "fragment_len": None})
        assert len(got) == 2, got
        assert "_load_the_pattern_path" in got[0] and "_CMD_POS_NO_VERB" in got[1], got
        assert all("COMPILE_CHILD" in line for line in got), got


class TestTheFloorCheck:
    def test_the_compiled_characters_red_one_under_the_floor_and_hold_at_it(self):
        assert breaches({**BASE, "hooks_chars": FLOOR_COMPILED_CHARS}) == []
        got = breaches({**BASE, "hooks_chars": FLOOR_COMPILED_CHARS - 1})
        assert len(got) == 1 and got[0].startswith(
            "the pattern path compiles 185,999 characters, under the floor of 186,000"), got

    def test_the_fragment_reds_one_under_the_floor_and_holds_at_it(self):
        assert breaches({**BASE, "fragment_len": FLOOR_FRAGMENT_LEN}) == []
        got = breaches({**BASE, "fragment_len": FLOOR_FRAGMENT_LEN - 1})
        assert len(got) == 1 and got[0].startswith(
            "_CMD_POS_NO_VERB is 1,399 characters, under the floor of 1,400"), got

    def test_a_reader_that_stopped_counting_the_imports_reds_under_the_floor(self):
        # The census's recorder installed after the two pattern-module imports,
        # driven on a copy of b3eefcf's tree on 3.13: 51 patterns, 10,770.
        got = breaches({**BASE, "hooks_patterns": 51, "hooks_chars": 10_770, "embedding_patterns": 3})
        assert len(got) == 1 and "under the floor of 186,000" in got[0], got

    def test_a_loader_that_compiles_nothing_reds_though_the_figure_sits_in_the_band(self):
        # b3eefcf with the loader stubbed: the imports' 300 patterns, 95.6%.
        got = breaches({**BASE, "hooks_patterns": 300, "hooks_chars": 197_698, "loader_patterns": 0})
        assert got == ["write_guard._load_the_pattern_path compiled no pattern of its own, so its compiles "
                       "moved to import or were dropped; read the per-call figure either way"]

    def test_a_family_compiled_outside_the_count_reds_on_the_embedding_floor(self):
        got = breaches({**BASE, "embedding_patterns": 0})
        assert len(got) == 1 and "embeds _CMD_POS_NO_VERB" in got[0], got


class TestWhatTheLineCatches:
    """The module docstring's arithmetic, held so a re-pinned ceiling owes a
    re-read of what it catches."""

    def test_the_smallest_growths_past_either_ceiling_red(self):
        headroom = CEILING_COMPILED_CHARS - BASE["hooks_chars"]
        assert headroom == 21_305
        assert breaches(_grown(chars=headroom)) == []
        assert len(breaches(_grown(chars=headroom + 1))) == 1
        assert len(breaches(_grown(fragment=170))) == 0
        assert len(breaches(_grown(fragment=171))) == 1

    def test_one_hundred_character_alternation_passes_and_a_second_reds(self):
        one = _grown(chars=100 * PINNED["fragment_copies"], fragment=100)
        assert one["hooks_chars"] == 213_195 and breaches(one) == []
        two = _grown(chars=200 * PINNED["fragment_copies"], fragment=200)
        assert breaches(two) == ["_CMD_POS_NO_VERB is 1,780 characters, past the ceiling of 1,750"]

    def test_thirteen_more_copies_of_the_fragment_pass_and_the_fourteenth_reds(self):
        frag = BASE["fragment_len"]
        assert breaches(_grown(chars=13 * frag)) == []
        assert breaches(_grown(chars=14 * frag)) == [
            "the pattern path compiles 228,815 characters, past the ceiling of 228,000"]


class RatchetBreach(AssertionError):
    """The live row's failure, carrying what the census read."""

    def __init__(self, figures: dict, problems: list[str]):
        version = sys.version.split()[0]
        super().__init__("\n".join([*problems, RULE, f"read on python {version} ({sys.executable}): {figures!r}"]))
        self.figures = figures
        self.problems = problems


def _assert_holds(root: Path, scratch: Path) -> dict:
    """The census's compile reading of ``root``'s hooks folder, raised as a
    ``RatchetBreach`` where it fails the check: the one path the live row and
    the synthetic trees share."""
    figures = census.compile_counts(census.hooks_of(root), scratch)
    problems = breaches(figures)
    if problems:
        raise RatchetBreach(figures, problems)
    return figures


def _hooks_tree(root: Path, *, bash_patterns: str, loader_body: str) -> Path:
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "_bash_patterns.py").write_text("import re\n" + bash_patterns, encoding="utf-8")
    (hooks / "_speedbump.py").write_text("X = 1\n", encoding="utf-8")
    (hooks / "write_guard.py").write_text(
        "import re\nimport _bash_patterns\n\n\ndef _load_the_pattern_path():\n    " + loader_body + "\n",
        encoding="utf-8")
    scratch = root / "scratch"
    scratch.mkdir()
    return scratch


def _fragment(length: int) -> str:
    return f'_CMD_POS_NO_VERB = "(?:" + "a" * {length - 4} + ")"\n'


class TestTheLiveFigure:
    def test_this_checkouts_pattern_path_holds_inside_the_band(self, tmp_path):
        _assert_holds(REPO_ROOT, tmp_path)

    def test_a_tree_grown_past_both_ceilings_reds_through_the_live_rows_reader(self, tmp_path):
        # A fragment one past its ceiling (3 + 1,747 + 1 characters): 130 copies
        # of it compiled at import and one by the loader, 229,381 characters.
        scratch = _hooks_tree(tmp_path, bash_patterns=_fragment(1_751) + "_BULK = re.compile(_CMD_POS_NO_VERB * 130)\n",
                              loader_body="re.compile(_bash_patterns._CMD_POS_NO_VERB)")
        with pytest.raises(RatchetBreach) as caught:
            _assert_holds(tmp_path, scratch)
        got = caught.value
        assert (got.figures["loader_patterns"], got.figures["loader_chars"], got.figures["hooks_chars"],
                got.figures["fragment_len"]) == (1, 1_751, 229_381, 1_751), got.figures
        assert got.problems == ["the pattern path compiles 229,381 characters, past the ceiling of 228,000",
                                "_CMD_POS_NO_VERB is 1,751 characters, past the ceiling of 1,750"], got.problems
        assert RULE in str(got) and "read on python " in str(got)

    def test_a_loader_that_loads_nothing_reds_though_the_imports_sit_in_the_band(self, tmp_path):
        # The pinned fragment, 130 copies compiled at import (205,400
        # characters), and a loader that compiles nothing.
        scratch = _hooks_tree(tmp_path, bash_patterns=_fragment(1_580) + "_BULK = re.compile(_CMD_POS_NO_VERB * 130)\n",
                              loader_body="pass")
        with pytest.raises(RatchetBreach) as caught:
            _assert_holds(tmp_path, scratch)
        got = caught.value
        assert (got.figures["loader_ran"], got.figures["loader_patterns"], got.figures["hooks_chars"]) == (
            True, 0, 205_400), got.figures
        assert got.problems == ["write_guard._load_the_pattern_path compiled no pattern of its own, so its compiles "
                                "moved to import or were dropped; read the per-call figure either way"], got.problems

    def test_a_tree_that_compiles_nothing_is_read_as_no_pattern_and_reds(self, tmp_path):
        scratch = _hooks_tree(tmp_path, bash_patterns=_fragment(1_580), loader_body="pass")
        with pytest.raises(RatchetBreach) as caught:
            _assert_holds(tmp_path, scratch)
        got = caught.value
        assert (got.figures["loader_ran"], got.figures["hooks_patterns"], got.figures["hooks_chars"]) == (
            True, 0, 0), got.figures
        assert "the census read no pattern compiled from the hooks folder" in got.problems, got.problems
        assert len(got.problems) == 4, got.problems


class TestTheFirstUseBoundary:
    def test_the_first_use_compiles_are_the_named_ones(self):
        got = first_use_compiles(HOOKS)
        assert got == FIRST_USE_COMPILES, (
            f"read {got!r}: a pattern compiled on first use behind a cache is outside the census's count, so "
            "its lane owes the per-call figure of each kind that reaches it (scripts/guard_cost_census.py "
            "--calls 30, at the lane's head and with --at origin/main) and names it in FIRST_USE_COMPILES")

    def test_a_cached_compile_is_read_and_an_uncached_or_compile_free_one_is_not(self, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "_bash_patterns.py").write_text(
            "import functools\nimport re\nfrom functools import lru_cache\n\n\n"
            "@functools.lru_cache(maxsize=1)\ndef a():\n    return re.compile('a')\n\n\n"
            "@lru_cache\ndef b():\n    return re.compile('b')\n\n\n"
            "@functools.cache\ndef c():\n    return re.compile('c')\n\n\n"
            "def d():\n    return re.compile('d')\n\n\n"
            "@functools.lru_cache(maxsize=1)\ndef e():\n    return 'e'\n",
            encoding="utf-8")
        for name, fn in (("_speedbump.py", "s"), ("write_guard.py", "w")):
            (hooks / name).write_text(
                f"import functools\nimport re\n\n\n@functools.lru_cache(maxsize=8)\ndef {fn}():\n"
                f"    return re.compile('{fn}')\n", encoding="utf-8")
        assert first_use_compiles(hooks) == {"_bash_patterns.py": {"a", "b", "c"}, "_speedbump.py": {"s"},
                                             "write_guard.py": {"w"}}
