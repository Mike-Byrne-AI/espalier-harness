"""The pattern path's compiled size, held under a ceiling: TP-707's ratchet (1-B).

Every Bash, PowerShell, mutation and MCP call loads write_guard's pattern path
(``tools/cc/hooks/write_guard.py::_load_the_pattern_path``), and what that load
costs tracks the characters it compiles. Task 0 read it on the Air (3.14.7,
under the box lock, n=10 a point, 2026-11-12): the two pattern modules import in
180.3 ms (IQR 171.2 to 182.1) at b3eefcf, which compiles 206,695 characters, and
in 282.9 ms (276.3 to 289.2) at caae022, #516's head, which compiles 387,130.

The live row reads the figure with ``scripts/guard_cost_census.py``'s
``--compile`` reader, which runs in a fresh interpreter, so an import elsewhere
in this run cannot hide a growth. It reds where the compiled characters or the
shared command-position fragment (``_bash_patterns._CMD_POS_NO_VERB``) grow past
a ceiling, and where the reader read no pattern at all, so a loader that loads
nothing cannot pass. The check is a pure function, tested on fixed figures: a
mutated tree would drift with every guard lane. The live row reads through the
same helper as two synthetic hooks trees, one that loads nothing and one grown
past both ceilings, so a reading the live row drops on its way to the check
reds there.

What the +10% line catches (ruling 2b), at b3eefcf's figures: a #516-sized
jump, and any growth of 21,306 compiled characters or of the fragment past
1,750. It does not catch one 100-character alternation added to the fragment
(1,680 characters; 65 copies across the 61 patterns that embed it, so +6,500
compiled characters, +3.1%), though a second one reds on the fragment. Nor does
it catch a second copy of the fragment in one pattern (+1,580, +0.8%): thirteen
such copies pass and the fourteenth reds.
"""
# slow-exempt: two census children, each a fresh interpreter compiling the hooks' patterns (under a second on the Air)
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "guard_cost_census.py"

#: The pattern path's compiled characters, from the hooks folder. At b3eefcf
#: (2026-11-12) the census read 206,695 on the Air's 3.14.7 venv and up to
#: 207,211 on 3.11: the standard library's own compiles that a hook's frame
#: reaches move by interpreter. Plus 10% (ruling 2b), rounded up to a thousand.
CEILING_COMPILED_CHARS = 228_000
#: ``_bash_patterns._CMD_POS_NO_VERB``'s length: 1,580 at b3eefcf, plus 10%,
#: rounded up to fifty.
CEILING_FRAGMENT_LEN = 1_750

#: b3eefcf's figures, the base the arithmetic above is read from.
BASE = {"loader_ran": True, "fragment_found": True, "hooks_patterns": 308, "hooks_chars": 206_695,
        "fragment_len": 1_580}
#: The fragment's copies across the patterns that embed it at b3eefcf.
BASE_FRAGMENT_COPIES = 65
#: caae022's figures as the census's ``--at`` read them on 2026-11-12, held as
#: data, since CI has no ref to it (the pack's prototype read 387,144, a method
#: 14 characters apart). It predates the loader, so the census read its imports
#: alone, and that reds too.
CAAE022 = {"loader_ran": False, "fragment_found": True, "hooks_patterns": 288, "hooks_chars": 387_130,
           "fragment_len": 4_301}

RULE = ("A growth owes a measured per-call figure at or under main's (python3 "
        "scripts/guard_cost_census.py --calls 30, under the box lock, both arms) or the operator's word; "
        "a change that lowers the figure moves these ceilings down in its own lane (TP-707 1-B). "
        "The figure: python3 scripts/guard_cost_census.py --compile")


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
                     "compiles went uncounted")
    if not figures.get("hooks_patterns"):
        found.append("the census read no pattern compiled from the hooks folder: a loader that loads "
                     "nothing is not a path that costs nothing")
    if not figures.get("fragment_found"):
        found.append("the census found no _bash_patterns._CMD_POS_NO_VERB, so the fragment's length "
                     "went unread")
    chars = figures.get("hooks_chars") or 0
    if chars > CEILING_COMPILED_CHARS:
        found.append(f"the pattern path compiles {chars:,} characters, past the ceiling of "
                     f"{CEILING_COMPILED_CHARS:,}")
    fragment = figures.get("fragment_len") or 0
    if fragment > CEILING_FRAGMENT_LEN:
        found.append(f"_CMD_POS_NO_VERB is {fragment:,} characters, past the ceiling of "
                     f"{CEILING_FRAGMENT_LEN:,}")
    return found


def _grown(*, chars: int = 0, fragment: int = 0) -> dict:
    return {**BASE, "hooks_chars": BASE["hooks_chars"] + chars, "fragment_len": BASE["fragment_len"] + fragment}


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
        assert "_load_the_pattern_path" in got[0], got
        assert "387,130 characters" in got[1] and "4,301 characters" in got[2], got

    def test_a_reading_of_no_pattern_reds_though_it_sits_under_both_ceilings(self):
        got = breaches({"loader_ran": True, "fragment_found": True, "hooks_patterns": 0, "hooks_chars": 0,
                        "fragment_len": 1_580})
        assert len(got) == 1 and "no pattern compiled from the hooks folder" in got[0], got

    def test_a_reading_without_the_loader_or_the_fragment_reds(self):
        got = breaches({**BASE, "loader_ran": False, "fragment_found": False, "fragment_len": None})
        assert len(got) == 2, got
        assert "_load_the_pattern_path" in got[0] and "_CMD_POS_NO_VERB" in got[1], got


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
        one = _grown(chars=100 * BASE_FRAGMENT_COPIES, fragment=100)
        assert one["hooks_chars"] == 213_195 and breaches(one) == []
        two = _grown(chars=200 * BASE_FRAGMENT_COPIES, fragment=200)
        assert breaches(two) == ["_CMD_POS_NO_VERB is 1,780 characters, past the ceiling of 1,750"]

    def test_thirteen_more_copies_of_the_fragment_pass_and_the_fourteenth_reds(self):
        frag = BASE["fragment_len"]
        assert breaches(_grown(chars=13 * frag)) == []
        assert breaches(_grown(chars=14 * frag)) == [
            "the pattern path compiles 228,815 characters, past the ceiling of 228,000"]


def _read_and_judge(root: Path, scratch: Path) -> "tuple[dict, list[str]]":
    """The census's compile reading of ``root``'s hooks folder, and its breaches:
    the one path the live row and the synthetic trees share."""
    figures = census.compile_counts(census.hooks_of(root), scratch)
    return figures, breaches(figures)


def _hooks_tree(root: Path, *, bash_patterns: str, loader_body: str) -> Path:
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "_bash_patterns.py").write_text(bash_patterns, encoding="utf-8")
    (hooks / "_speedbump.py").write_text("X = 1\n", encoding="utf-8")
    (hooks / "write_guard.py").write_text(
        "import re\nimport _bash_patterns\n\n\ndef _load_the_pattern_path():\n    " + loader_body + "\n",
        encoding="utf-8")
    scratch = root / "scratch"
    scratch.mkdir()
    return scratch


class TestTheLiveFigure:
    def test_this_checkouts_pattern_path_holds_under_both_ceilings(self, tmp_path):
        figures, problems = _read_and_judge(REPO_ROOT, tmp_path)
        assert not problems, "\n".join([*problems, RULE, f"read: {figures!r}"])

    def test_a_tree_grown_past_both_ceilings_reds_through_the_live_rows_reader(self, tmp_path):
        # A fragment one past its ceiling (3 + 1,747 + 1 characters), and one
        # pattern of 131 copies of it: 229,381 compiled characters.
        scratch = _hooks_tree(tmp_path, bash_patterns='_CMD_POS_NO_VERB = "(?:" + "a" * 1747 + ")"\n',
                              loader_body="re.compile(_bash_patterns._CMD_POS_NO_VERB * 131)")
        figures, got = _read_and_judge(tmp_path, scratch)
        assert (figures["loader_ran"], figures["hooks_chars"], figures["fragment_len"]) == (True, 229_381, 1_751), \
            figures
        assert got == ["the pattern path compiles 229,381 characters, past the ceiling of 228,000",
                       "_CMD_POS_NO_VERB is 1,751 characters, past the ceiling of 1,750"], got

    def test_a_loader_that_loads_nothing_is_read_as_no_pattern_and_reds(self, tmp_path):
        scratch = _hooks_tree(tmp_path, bash_patterns="_CMD_POS_NO_VERB = '(?:^|;)'\n", loader_body="pass")
        figures, got = _read_and_judge(tmp_path, scratch)
        assert (figures["loader_ran"], figures["hooks_patterns"], figures["hooks_chars"]) == (True, 0, 0), figures
        assert len(got) == 1 and "no pattern compiled from the hooks folder" in got[0], got
