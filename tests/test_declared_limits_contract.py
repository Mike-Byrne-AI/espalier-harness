"""Every "declared limit" in the shipped guard docs cites the row that pins it.

THE CLASS. A declared limit is a reader gap the operator chose to name rather
than close: the sentence in ``docs/HOOKS.md`` or ``docs/SHARP_EDGES.md`` says
what the guard does not read, and a test row asserts exactly that reading so
the day a reader closes the gap the row reds and the sentence is rewritten on
purpose. The sentence and the row stale independently. On 2026-09-19 eight
adopter-facing rows were struck as declared limits with the words "each pinned
by a row that reds the day a reader closes it"; the pre-cut review (Round 11,
2026-09-20) found three of the eight claiming pins that did not exist, a
fourth pinned only as "not the wall" (a form that cannot red when the limit
closes), and one declared clause that was false on the day it shipped -- and
when the pins were finally driven for this contract (2026-09-22) a declared
"nested program's directory" limit did not reproduce at all. Nothing coupled
the prose to the rows: ``tests/test_doc_source_citations.py``'s regex admits
``espalier/``, ``tools/`` and ``.claude/`` paths only, so a ``tests/`` node id
in a doc was invisible to every sweep.

THE CONTRACT. Every sentence in the two docs that declares a limit carries at
least one backticked pytest node id naming a test FUNCTION --
``tests/<file>.py::<Class>::<test>`` or ``tests/<file>.py::<test>`` (a
class-level cite is satisfied by any of the class's rows and cannot red when
one limit closes; the red team drove it) -- and each cited id (1) names a
tracked file whose class/function path resolves by AST and (2) RUNS AND PASSES
on this host in one pytest subprocess per run, matched by exact id (a
substring match let ``test_x`` be satisfied by ``test_x_loop``; collect-only
let a row that gains a ``skipif`` keep pinning while running on no host).
Parametrised rows are cited by function, never with brackets. The census
(sentences / cited) is printed on every red so a reader sees the population.

WHAT COUNTS AS A DECLARATION is the phrase key ``_PHRASE`` -- "declared
limit(s)", the hyphenated form, "(declared)" and "declared a … limit" --
calibrated 2026-09-22 against the live population: any "declar*" swept in 27
unrelated sentences (a scanner "declares EXEMPT_PREFIXES", a module "declares
deps"), so the key is deliberately narrow and a new spelling of a declaration
is added HERE, not worked around in the doc.

WHAT IT CANNOT SEE, said plainly: a pin that runs and asserts the wrong
DIRECTION, or the wrong LIMIT (a real row cited for a sentence it does not pin
-- the red team found one of those in this very batch). That is the reviewer's
question, not this file's; the 2026-09-22 rows were each measured in a fresh
project before their verdict was written, and the census's per-sentence
mapping was done by hand with the assertion's line as evidence.

# slow-exempt: only the run-and-pass test spawns pytest, and it carries its own `slow` mark
Stem is classified ``contract`` in ``tests/conftest.py::_MARKER_RULES``.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The shipped guard docs that declare limits. ``docs/HOOKS.md`` is byte-mirrored
#: to ``espalier/assets/docs/HOOKS.md`` (the asset-docs row), so the mirror is
#: covered by parity, not walked twice here.
DECLARING_DOCS = ("docs/HOOKS.md", "docs/SHARP_EDGES.md")

#: The declaration key. Narrow on purpose -- see the module docstring.
_PHRASE = re.compile(r"declared[ -]limits?|\(declared\)|declared a (?:\w+ )?limit", re.IGNORECASE)
#: A backticked node id under tests/: the file, then one or more ``::`` segments
#: (a class, a nested class, a function). No brackets: parametrised rows are
#: cited by their function.
_NODE_ID = re.compile(r"`(tests/[A-Za-z0-9_./-]+\.py)::([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*)`")
#: A sentence ends at ``.``/``!``/``?`` followed by whitespace and a capital,
#: an emphasis marker, a backtick or an open paren -- the shape the docs use.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`(])")
#: A markdown list item starts a new block whatever punctuation precedes it:
#: a paragraph's items are split BEFORE the sentence split, so a second
#: declaring bullet can never ride its neighbour's citation (the red team
#: drove that, 2026-09-22).
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s", re.MULTILINE)


def _blocks(text: str) -> list[str]:
    """Paragraphs, each further split at markdown list-item starts, flattened."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        starts = [m.start() for m in _LIST_ITEM.finditer(para)]
        pieces = [para] if not starts else (
            [para[:starts[0]]] + [para[a:b] for a, b in zip(starts, starts[1:] + [len(para)])]
        )
        for piece in pieces:
            flat = re.sub(r"\s+", " ", piece).strip()
            if flat:
                out.append(flat)
    return out


def declared_limit_sentences(text: str) -> list[str]:
    """Every sentence matching the declaration key, block by block."""
    return [s for block in _blocks(text) for s in _SENTENCE_END.split(block) if _PHRASE.search(s)]


def cited_node_ids(sentence: str) -> list[tuple[str, tuple[str, ...]]]:
    return [(m.group(1), tuple(m.group(2).split("::"))) for m in _NODE_ID.finditer(sentence)]


def _resolves_by_ast(rel: str, symbols: tuple[str, ...]) -> bool:
    """The file exists, the last segment is a test FUNCTION, and each ``::``
    segment is a class or function nested in the previous one."""
    path = REPO_ROOT / rel
    if not path.is_file() or not symbols[-1].startswith("test"):
        return False
    node: ast.AST = ast.parse(path.read_text(encoding="utf-8"))
    for name in symbols:
        body = getattr(node, "body", [])
        node = next(
            (n for n in body
             if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
            None,
        )
        if node is None:
            return False
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _tracked_test_files() -> set[str]:
    """The tracked ``tests/`` population through the shared git oracle, which
    raises instead of answering with an empty set when git cannot answer (a
    raw ``git ls-files`` here would read an unanswerable query as "untracked",
    and the ratchet in ``test_test_suite_contract.py`` forbids the raw form).
    Floor: the suite has well over a hundred test files; a smaller answer is a
    foreign tree."""
    from tests._git_oracle import require_tracked_paths

    return set(require_tracked_paths(REPO_ROOT, "tests/*.py", minimum=100, what="tests/*.py"))


def _census() -> dict[str, list[tuple[str, list[tuple[str, tuple[str, ...]]]]]]:
    """doc -> [(sentence, [cited ids])] for every declaring sentence."""
    out = {}
    for rel in DECLARING_DOCS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        out[rel] = [(s, cited_node_ids(s)) for s in declared_limit_sentences(text)]
    return out


def _census_line(census) -> str:
    parts = []
    for rel, rows in census.items():
        cited = sum(1 for _s, ids in rows if ids)
        parts.append(f"{rel}: {len(rows)} sentences, {cited} cited")
    return "; ".join(parts)


class TestTheSentenceSplitter:
    """The splitter is a claim too: a declaring sentence it cannot see is a
    limit the contract never asks about. Fixtures in both directions -- a
    must-trip (the sentence and its id are found) and a must-not-merge (a
    second declaring item does not ride the first's citation)."""

    def test_a_wrapped_sentence_with_its_pin_is_one_sentence(self):
        para = (
            "A stage between the enumerator and the loop is a declared limit,\n"
            "pinned by `tests/test_write_guard.py::TestX::test_y`. The next\n"
            "sentence is not one."
        )
        got = declared_limit_sentences(para)
        assert len(got) == 1, got
        assert cited_node_ids(got[0]) == [("tests/test_write_guard.py", ("TestX", "test_y"))]

    def test_a_declaring_sentence_ending_in_a_backtick_is_seen(self):
        para = (
            "**Declared limit** (2026-09-19), pinned by `tests/test_a.py::test_b`\n"
            "and `tests/test_a.py::TestC::test_d`. Plain prose follows."
        )
        got = declared_limit_sentences(para)
        assert len(got) == 1, got
        assert len(cited_node_ids(got[0])) == 2

    def test_a_second_declaring_list_item_does_not_ride_the_firsts_citation(self):
        """The red team's driven BLOCK (2026-09-22): before the list-aware split
        both items below were one 'sentence' with one citation."""
        para = (
            "   - `tools/cc/` is a declared limit, pinned by\n"
            "     `tests/test_write_guard.py::TestX::test_y`.\n"
            "   - A new zone the next session adds is a declared limit too.\n"
        )
        got = declared_limit_sentences(para)
        assert len(got) == 2, got
        assert cited_node_ids(got[0]) and not cited_node_ids(got[1]), got

    def test_a_numbered_item_is_its_own_block(self):
        # a bare numbered item: with bold item text the sentence regex splits
        # at the `.` before `**` anyway, which proved nothing about the list
        # split (the mutation drive found it, 2026-09-22)
        para = (
            "1. the verb rosters are a declared limit, pinned by `tests/test_a.py::test_b`.\n"
            "2. a path the walk cannot read is a declared limit.\n"
        )
        got = declared_limit_sentences(para)
        assert len(got) == 2 and not cited_node_ids(got[1]), got

    def test_the_other_declaration_spellings_are_keyed(self):
        for s in ("the walk's standing limit (declared).",
                  "a declared-limit the reader keeps.",
                  "it was declared a third limit on 2026-09-19."):
            assert _PHRASE.search(s), s
        for s in ("the scanner declares EXEMPT_PREFIXES at module level.",
                  "a structured scan only catches actual declared deps.",
                  "the converged chain declared closed."):
            assert not _PHRASE.search(s), s

    def test_a_sentence_without_the_phrase_is_not_counted(self):
        assert declared_limit_sentences("A limit that is not declared. Nor this.") == []

    def test_a_bracketed_parametrised_id_is_not_a_citation(self):
        s = "declared limit `tests/test_a.py::test_b[row-1]`"
        assert cited_node_ids(s) == [], "cite the function, never a parametrised id"

    def test_a_class_level_cite_does_not_resolve(self):
        """A class cite is satisfied by any of its rows and cannot red when one
        limit closes (the red team, 2026-09-22): only a function resolves."""
        assert not _resolves_by_ast("tests/test_declared_limits_contract.py", ("TestTheSentenceSplitter",))
        assert _resolves_by_ast(
            "tests/test_declared_limits_contract.py",
            ("TestTheSentenceSplitter", "test_a_class_level_cite_does_not_resolve"),
        )


#: The live census, pinned exactly with its date so ANY movement -- a limit
#: closed and its sentence rewritten, a splitter regression that merges two
#: sentences, a new declaration -- is a deliberate edit here (the red team:
#: a floor at half the population lets the merge in BLOCK-1 pass).
_CENSUS_ON_2026_09_22 = {"docs/HOOKS.md": 20, "docs/SHARP_EDGES.md": 4}


def test_the_census_is_the_pinned_population():
    census = _census()
    got = {rel: len(rows) for rel, rows in census.items()}
    assert got == _CENSUS_ON_2026_09_22, (
        f"the declaring-sentence census moved: {got} != {_CENSUS_ON_2026_09_22}. A limit "
        "closed or declared, or the splitter changed -- re-derive and re-pin the "
        "number on purpose (the message names the sentences on a red below).\n" + _census_line(census)
    )


def test_every_declared_limit_sentence_cites_a_pin():
    census = _census()
    offenders = [
        f"  {rel}: {s[:160]!r}"
        for rel, rows in census.items()
        for s, ids in rows
        if not ids
    ]
    assert not offenders, (
        "These declared-limit sentences cite no pytest node id "
        "(`tests/<file>.py::<Class>::<test>`, the row that reds the day a reader "
        f"closes the limit). Census -- {_census_line(census)}:\n" + "\n".join(offenders)
    )


def test_every_cited_pin_resolves_to_a_test_function_in_a_tracked_file():
    census = _census()
    tracked = _tracked_test_files()
    bad = []
    for rel, rows in census.items():
        for _s, ids in rows:
            for path, symbols in ids:
                if path not in tracked:
                    bad.append(f"  {rel} cites untracked {path}")
                elif not _resolves_by_ast(path, symbols):
                    bad.append(f"  {rel} cites {path}::{'::'.join(symbols)} which is not a test function there")
    assert not bad, (
        "A declared limit cites a pin that is not there -- the sentence has "
        "outlived its row, which is the class this contract exists to close:\n"
        + "\n".join(bad)
    )


def _cited_ids() -> list[str]:
    return sorted({
        f"{path}::{'::'.join(symbols)}"
        for rows in _census().values()
        for _s, ids in rows
        for path, symbols in ids
    })


@pytest.mark.slow
# One pytest child over the whole cited population: 37 s on the self-host box
# (2026-09-23) and past the global 60 s `timeout` on a 2-core CI runner, where
# `timeout_method = "thread"` then ends the WHOLE session (CI run 35917451001,
# the first after the 2026-09-10 switch-off). Above the child's own 300 s bound
# so its message, not this one, is what a reader sees.
@pytest.mark.timeout(360)
def test_every_cited_pin_runs_and_passes_on_this_host():
    """One pytest subprocess over every cited id: a pin that resolves but
    never RUNS here (a marker deselecting it, a ``skipif`` a hurried session
    added "for consistency", a class pytest does not collect) is a pin that
    cannot red, and collect-only would have said it was fine. Exact-id
    matching on the ``-rA`` report lines, parameters stripped."""
    cited = _cited_ids()
    if not cited:
        pytest.skip("no citations yet -- the sentence contract reports that")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", "--tb=line", *cited],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    outcomes: dict[str, set[str]] = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^(PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)\s+(\S+)", line)
        if not m:
            continue
        outcome, node = m.group(1), m.group(2)
        node = node.split("[", 1)[0]          # parameters stripped -> the cited form
        outcomes.setdefault(node, set()).add(outcome)
    problems = []
    for node in cited:
        seen = outcomes.get(node)
        if not seen:
            problems.append(f"  {node}: never ran (not collected, or reported under another id)")
        elif seen - {"PASSED", "XFAIL"}:
            problems.append(f"  {node}: {sorted(seen)}")
    assert not problems, (
        f"cited pins that do not run and pass here (pytest rc {proc.returncode}):\n"
        + "\n".join(problems) + f"\n--- tail ---\n{proc.stdout[-1500:]}\n{proc.stderr[-800:]}"
    )
