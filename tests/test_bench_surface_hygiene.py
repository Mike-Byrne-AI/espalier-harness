"""The bench surface carries no internal vocabulary (DEF-410k, the narrow arm).

``bench/`` ships: its README and RESULTS are the first thing a stranger reads
about the guard, with the demo and end-to-end docs beside them. The tree-wide
provenance census (``espalier/provenance_census.py``) already refuses the
build-history tags -- pack ids, review-round labels, workflow run ids -- on
the shipping surface. This is the bench-scoped arm the row planned and nobody
built: three shapes the census does not spell, each a piece of THIS repo's
internal machinery that means nothing to a reader of the bench --

* a forward-ledger class section (``§C12``), which names a section of a record
  the reader does not have open;
* a raw 40-hex commit hash, which points into a history the export may not
  carry;
* one of this repo's own agent names, which reads as a product feature to
  someone who has not seen ``.claude/agents/``.

The agent roster is DERIVED from ``.claude/agents/`` (STANDING_PRINCIPLES
§14), so a renamed or added agent is covered without an edit here.

The population is the AUTHORED markdown: the front matter, the demo and
end-to-end guides, the baseline notes. Not scanned, and why: ``bench/results/``
is a generated run record (Core Rule 13 -- the remedy this test prescribes,
"rewrite the line", falsifies a record); the corpus rows are JSON, and by
operator decision (2026-09-13) a ledger row id in a corpus row's reason is
provenance the ledger ships under DEC-31, not internal vocabulary; the ``.py``
and ``.yaml`` files on this subtree carry the shapes today -- an agent name
in an end-to-end scenario fixture is test data, a code comment cites a
retired phrasing -- and are out of scope by decision, so "the bench surface
carries no agent names" is a claim about its DOCUMENTS. Measured on
2026-09-13 the live population was clean, so the first test pins a state
rather than earning a red; the negative control beside it is what proves the
scanner sees each shape (STANDING_PRINCIPLES §12).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "bench"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

#: A forward-ledger class section: `§C4`, `§ C12`.
_LEDGER_SECTION_RE = re.compile(r"§\s?C\d+")
#: A raw commit hash. A short one (`abc1234`) is how a changelog cites a
#: commit and is left alone.
_RAW_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")


def agent_names() -> frozenset[str]:
    """This repo's agent names, from the files that define them."""
    names = frozenset(p.stem for p in AGENTS_DIR.glob("*.md"))
    assert names, "no agents under .claude/agents/ -- the roster is derived from it"
    return names


#: The authored documents (see the module docstring for what is left out).
_AUTHORED_FILES = ("README.md", "RESULTS.md")
_AUTHORED_DIRS = ("demo", "end_to_end", "baselines")


def bench_docs(root: Path = BENCH_DIR) -> list[Path]:
    """The authored markdown under bench/: never a generated record."""
    docs = [root / name for name in _AUTHORED_FILES if (root / name).is_file()]
    for sub in _AUTHORED_DIRS:
        if (root / sub).is_dir():
            docs.extend((root / sub).rglob("*.md"))
    return sorted(docs)


def offenders(text: str, agents: frozenset[str]) -> list[tuple[int, str, str]]:
    """``(lineno, kind, line)`` for every line carrying one of the shapes."""
    agent_re = re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(a) for a in sorted(agents)) + r")(?![\w-])"
    )
    out: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _LEDGER_SECTION_RE.search(line):
            out.append((lineno, "ledger-section", line.strip()[:100]))
        if _RAW_SHA_RE.search(line):
            out.append((lineno, "raw-sha", line.strip()[:100]))
        if agent_re.search(line):
            out.append((lineno, "agent-name", line.strip()[:100]))
    return out


def test_the_bench_docs_carry_no_internal_vocabulary():
    agents = agent_names()
    docs = bench_docs()
    assert docs, "no markdown under bench/ -- the surface this pins is gone"
    found = [
        (doc.relative_to(REPO_ROOT).as_posix(), lineno, kind, line)
        for doc in docs
        for lineno, kind, line in offenders(
            doc.read_text(encoding="utf-8", errors="replace"), agents)
    ]
    assert not found, (
        "internal vocabulary on the bench surface -- rewrite the line for a "
        "reader who has never opened this repo's ledger, history or agent "
        "roster:\n" + "\n".join(f"  {rel}:{n} [{kind}] {line}" for rel, n, kind, line in found)
    )


def test_the_scanner_sees_each_shape():
    """The negative control: a synthetic document carrying one of each."""
    agents = agent_names()
    sample = "\n".join([
        "The guard was reviewed (§C12, row 4).",
        "Fixed in 0123456789abcdef0123456789abcdef01234567 on main.",
        f"Run the {sorted(agents)[0]} before shipping.",
        "A clean line: the guard denies the write.",
    ])
    assert [kind for _n, kind, _l in offenders(sample, agents)] == [
        "ledger-section", "raw-sha", "agent-name",
    ]


def test_a_short_hash_and_a_heading_sign_are_not_flagged():
    """A changelog's seven-character hash and a section sign that points at a
    heading of the same document are ordinary prose."""
    agents = agent_names()
    line = 'see README § "Adding a scenario"; fixed in abc1234; the code reviewer agreed'
    assert offenders(line, agents) == []
