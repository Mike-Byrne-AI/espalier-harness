"""Benchmark release hygiene — TP-RELEASE-07 §D + TP-09.

Contract checks for `bench/`:

1. `bench/results/` has zero tracked files (timestamped per-run output is
   regenerable; tracking it pollutes diff and bloats archives).
2. `.gitignore` carries an explicit `bench/results` rule so a contributor
   running `git add .` after a benchmark run doesn't silently re-track
   the directory.
3. `bench/RESULTS.md` carries the "does not prove" disclaimer required
   by §C — without it, the benchmark presents as a proof of safety
   rather than a regression corpus.
4. The disclaimer appears near the top of RESULTS.md (TP-09) — burying
   it at the bottom defeats the calibration intent.
5. Benchmark docs (bench/README.md, bench/RESULTS.md) reference
   `sandbox` / `security boundary` only in negated/qualified form
   (TP-09) — unqualified mentions imply guarantees the friction layer
   does not provide.
6. README.md's bench-corpus link sits beside the calibrated caveat
   (TP-09) — readers who land on the link should see the framing
   without scrolling away.

Stem `test_benchmark_release_hygiene` is registered in
`tests/conftest.py::_MARKER_RULES` under the `release` group.
"""

# slow-exempt: the only subprocess calls are `pytest --collect-only -q <node-id>`
# for the handful of node-ids bench/RESULTS.md cites (2 today, ~0.4s total). They
# resolve citations rather than exercising a slow path, so the module stays in the
# `not slow` fast slice where the rest of its hygiene checks belong.
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 fallback (espalier supports >=3.10)
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "bench" / "RESULTS.md"


def _git_ls_files(path: str) -> list[str]:
    """Return tracked-or-walked files under `path`.

    TP-RELEASE-19: same shape as test_no_tracked_release_noise._git_ls_files
    but filters the result by the given path prefix. Falls back to
    filesystem walk on non-git contexts.
    """
    from espalier.repo_mode import list_tracked_or_walked_files
    files, _source = list_tracked_or_walked_files(REPO_ROOT)
    prefix = path.rstrip("/") + "/"
    return [f for f in files if f == path or f.startswith(prefix)]


def test_bench_results_not_tracked():
    """bench/results/ must not be tracked. It's regenerable per run."""
    tracked = _git_ls_files("bench/results")
    assert not tracked, (
        f"bench/results/ has tracked files: {tracked}. This directory is "
        "regenerable per run; remove from tracking with `git rm --cached "
        "<path>` for each entry."
    )


def test_bench_results_dir_gitignored():
    """The .gitignore must exclude bench/results/ explicitly."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "bench/results" in gitignore, (
        ".gitignore must contain 'bench/results' (or 'bench/results/') "
        "to prevent accidental tracking of generated benchmark outputs. "
        "TP-RELEASE-03 added this rule; if it's missing, restore it."
    )


def test_bench_claims_have_corpus_disclaimer():
    """RESULTS.md must include the explicit 'does not prove' disclaimer.

    Without this, the benchmark presents as a universal proof of safety.
    The required framing per TP-RELEASE-07 §C: a regression corpus over
    known bypass classes, not a proof that no bypass exists.
    """
    results_md = REPO_ROOT / "bench" / "RESULTS.md"
    assert results_md.exists(), "bench/RESULTS.md missing"
    text = results_md.read_text(encoding="utf-8").lower()
    assert "does not prove" in text or "does **not** prove" in text, (
        "bench/RESULTS.md must include the 'does not prove' disclaimer "
        "(see TP-RELEASE-07 §C). Add a 'What this benchmark does NOT "
        "prove' section near the top."
    )


def test_bench_results_documents_reproduction_command():
    """RESULTS.md must show the reproduction command so readers can
    regenerate locally without reading runner source."""
    results_md = REPO_ROOT / "bench" / "RESULTS.md"
    text = results_md.read_text(encoding="utf-8")
    assert "python3 bench/run_benchmark.py" in text, (
        "bench/RESULTS.md must show the explicit "
        "`python3 bench/run_benchmark.py` command so the table is "
        "reproducible from the doc alone."
    )


# ---------------------------------------------------------------------------
# TP-09: disclaimer placement, overclaim absence, README caveat anchor
# ---------------------------------------------------------------------------

# Lines within the head window where readers anchor on the framing. 40
# lines covers the title block + an explicit "What this benchmark does NOT
# prove" section without forcing a particular layout — the disclaimer can
# move within that window as the doc evolves, but cannot drift to the
# bottom (the prior failure mode).
_DISCLAIMER_HEAD_LINES = 40

# Phrases that imply the benchmark is more than a regression corpus.
# Each phrase must appear only in negated/qualified form in benchmark
# docs (e.g. "not a sandbox", "is not a security boundary"). The
# qualifier regex below recognises common negation/qualification shapes.
_OVERCLAIM_TERMS = ("sandbox", "security boundary")

# Negation/qualification shapes that legitimise an overclaim term on a
# given line. Order doesn't matter — any match clears the line.
_QUALIFIER_PATTERNS = [
    re.compile(r"\bnot\s+(?:a|an|the|a\s+hard|a\s+true)?\s*(?:sandbox|security boundary)\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+(?:prove|imply|require)\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+(?:prove|imply|require|claim)\b", re.IGNORECASE),
    re.compile(r"\brather\s+than\s+(?:a\s+)?(?:sandbox|security boundary)\b", re.IGNORECASE),
    re.compile(r"\b(?:requires|requiring|require)\s+sandbox(?:ing)?\b", re.IGNORECASE),
    re.compile(r"\bsandbox-class\s+bypass(?:es)?\b", re.IGNORECASE),
    re.compile(r"\bos-?level\s+sandbox(?:ing)?\b", re.IGNORECASE),
    re.compile(r"\bout\s+of\s+scope\b", re.IGNORECASE),
    re.compile(r"\boutside\s+(?:of\s+)?(?:espalier|the\s+friction|this)", re.IGNORECASE),
    re.compile(r"#.*(?:sandbox|security boundary)", re.IGNORECASE),  # heading callouts
]


def _is_qualified(line: str) -> bool:
    return any(p.search(line) for p in _QUALIFIER_PATTERNS)


def _scan_unqualified_overclaims(rel: str) -> list[tuple[int, str]]:
    """Return (line_no, line_text) for lines that mention an overclaim
    term without a recognised negation/qualification."""
    path = REPO_ROOT / rel
    text = path.read_text(encoding="utf-8")
    in_fence = False
    bad: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        # Skip fenced code blocks — those are reproduction commands and
        # corpus schemas, not prose claims.
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = raw.lower()
        if not any(term in line for term in _OVERCLAIM_TERMS):
            continue
        if _is_qualified(raw):
            continue
        bad.append((i, raw.strip()))
    return bad


def test_bench_results_disclaimer_appears_near_top():
    """The 'does not prove' disclaimer must sit near the top of RESULTS.md.

    Burying it at the bottom (the pre-TP-09 state) defeats the
    calibration intent — readers anchor on the first screen.
    """
    results_md = REPO_ROOT / "bench" / "RESULTS.md"
    head = "\n".join(
        results_md.read_text(encoding="utf-8").splitlines()[:_DISCLAIMER_HEAD_LINES]
    ).lower()
    assert "does not prove" in head or "does **not** prove" in head, (
        f"bench/RESULTS.md must place the 'does not prove' disclaimer "
        f"within the first {_DISCLAIMER_HEAD_LINES} lines (TP-09). The "
        "disclaimer can be anywhere in that window but must not drift "
        "to the bottom of the doc."
    )


@pytest.mark.parametrize("doc", ["bench/RESULTS.md", "bench/README.md"])
def test_bench_docs_avoid_unqualified_overclaims(doc):
    """Benchmark docs must reference 'sandbox' / 'security boundary'
    only in negated or qualified form (TP-09).

    Unqualified usage implies the benchmark proves guarantees the
    friction layer does not actually provide. Code blocks (fenced
    triple-backticks) are skipped — those are commands and schemas.
    """
    bad = _scan_unqualified_overclaims(doc)
    assert not bad, (
        f"{doc} contains unqualified mentions of 'sandbox' / 'security boundary' "
        f"(TP-09 — every mention must be negated or qualified):\n  "
        + "\n  ".join(f"line {ln}: {txt}" for ln, txt in bad)
    )


def test_readme_benchmark_section_carries_caveat():
    """The README's bench/RESULTS.md link must sit beside calibrated
    framing (TP-09) — readers landing on the link should see that the
    benchmark is a regression corpus, not a proof of safety, without
    scrolling away.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    link_idx = readme.find("bench/RESULTS.md")
    assert link_idx >= 0, "README.md must reference bench/RESULTS.md"
    # 600-char window straddling the link picks up either an inline
    # caveat at the link site or a same-paragraph 'not a' framing.
    start = max(0, link_idx - 300)
    end = min(len(readme), link_idx + 400)
    window = readme[start:end].lower()
    has_caveat = (
        "regression corpus" in window
        or "not a proof" in window
        or "does not prove" in window
        or "not a sandbox" in window
        or "not a security boundary" in window
    )
    assert has_caveat, (
        "README.md's bench/RESULTS.md reference must sit beside the "
        "calibrated caveat (regression corpus / not a proof of safety / "
        "does not prove / not a sandbox / not a security boundary). "
        "TP-09: the link should not stand alone."
    )


# ---------------------------------------------------------------------------
# TP-27 amendment: version parity + limitations + future denylist check
# ---------------------------------------------------------------------------


def _pyproject_version() -> str:
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_bench_results_version_matches_pyproject():
    """bench/RESULTS.md version must match pyproject.toml.

    Pre-TP-27: RESULTS.md said 0.5.0 while package was 0.6.0. Nothing
    tested the parity. Refresh by running:
      python3 bench/run_benchmark.py --update-canonical
    """
    if not RESULTS.exists():
        pytest.skip("bench/RESULTS.md absent")
    text = RESULTS.read_text(encoding="utf-8")
    m = re.search(r"espalier version:\s*(\S+)", text)
    assert m, (
        "bench/RESULTS.md is missing 'espalier version:' line.\n"
        "Run: python3 bench/run_benchmark.py --update-canonical"
    )
    bench_version = m.group(1)
    pyproject_version = _pyproject_version()
    assert bench_version == pyproject_version, (
        f"bench/RESULTS.md version {bench_version!r} does not match "
        f"pyproject.toml {pyproject_version!r}.\n"
        f"Run: python3 bench/run_benchmark.py --update-canonical"
    )


def test_bench_results_has_limitations_section():
    """RESULTS.md must retain a limitations/caveat section."""
    if not RESULTS.exists():
        pytest.skip("bench/RESULTS.md absent")
    text = RESULTS.read_text(encoding="utf-8").lower()
    assert any(token in text for token in
               ("limitation", "caveat", "does not prove",
                "does not measure")), (
        "bench/RESULTS.md must retain a limitations/caveat section. "
        "Benchmark proof should be modest about what it measures."
    )


def test_bench_results_dir_excluded_from_archive():
    """Per-run bench/results/ output must not ship in the release archive.

    Depends on espalier.release_denylist (ships with TP-37). Skips until
    that module is available.
    """
    release_denylist = pytest.importorskip(
        "espalier.release_denylist",
        reason="espalier.release_denylist not yet available (ships with TP-37)",
    )
    find_denied_members = release_denylist.find_denied_members
    fake_members = ["README.md", "bench/results/run-20260512.json"]
    denied = find_denied_members(fake_members)
    assert any(
        "bench/results/" in path for path, _ in denied
    ), (
        "espalier/release_denylist.py must reject bench/results/. "
        "The denylist exists from TP-37; this test pins the bench/"
        "results/ pattern specifically."
    )


# ---------------------------------------------------------------------------
# BENCH-04 / BENCH-05: RESULTS.md's own citations must stay resolvable.
#
# RESULTS.md is the public credibility surface: it publishes the benchmark
# figures and points a sceptical reader at the tests that back them. A cited
# pytest node-id that a reader runs and gets "no tests collected" from reads as
# an unbacked claim -- worse than no citation. BENCH-04 shipped exactly that:
# an UNQUALIFIED node-id for a test nested in a class, which collects nothing.
#
# Boundary note (coordination with the artifact link guard): that check builds
# a payload and resolves relative markdown LINKS inside it. This one resolves
# pytest NODE-IDS against a live collection. Different surfaces, different
# oracles -- neither subsumes the other, so both exist.
# ---------------------------------------------------------------------------

# ``.`` is inside the trailing class so a dotted id (``::TestFoo.test_bar``) is captured
# WHOLE. This is the third site of one class -- the two doc-citation guards carried the
# same gap -- but its failure mode is the worst of the three: unanchored ``findall`` over
# prose does not skip a dotted id, it TRUNCATES it to the class prefix and then resolves
# the truncation, so ``--collect-only`` succeeds on a class that exists and the guard
# reports green while the published id collects nothing. Pinned by
# ``test_node_id_regex_captures_dotted_ids_whole``.
_NODE_ID_RE = re.compile(r"tests/[A-Za-z0-9_/]+\.py::[A-Za-z0-9_.:]+")


class TestResultsMdCitationsResolve:
    """Every pytest node-id cited in bench/RESULTS.md must actually collect."""

    def test_node_id_regex_captures_dotted_ids_whole(self):
        """A dotted node-id must be captured WHOLE, not truncated at the class.

        Earn-the-red: with ``.`` outside the character class this returns
        ``['tests/test_x.py::TestC']`` — and that truncation is not a near-miss, it is a
        false GREEN. The collector then runs against a class prefix that collects fine,
        while the id actually published in ``bench/RESULTS.md`` collects nothing. Neither
        existing arm catches it: ``--collect-only`` on a real class exits 0, so the
        returncode arm is silent, and the ``no tests collected`` arm never sees the full
        id because the regex already dropped the method.

        This is the public credibility surface, so a citation that does not collect is
        exactly the defect this class exists to prevent."""
        whole = "tests/test_x.py::TestC.test_m"
        assert _NODE_ID_RE.findall(f"see {whole} for detail") == [whole]
        # the undotted and double-colon forms keep their existing capture
        assert _NODE_ID_RE.findall("tests/test_x.py::TestC") == ["tests/test_x.py::TestC"]
        assert _NODE_ID_RE.findall("tests/test_x.py::TestC::test_m") == [
            "tests/test_x.py::TestC::test_m"]

    def _cited(self) -> list[str]:
        # A trailing ``.`` is prose punctuation, never part of a node-id. It has to be
        # stripped HERE rather than excluded from the regex: the regex must capture the
        # dot so a genuinely dotted id (``::TestC.test_m``) is seen whole instead of
        # truncated to its class, and that same widening admits a sentence period landing
        # inside the id. RESULTS.md carries one today (``::TestVerifyReadLock.``), which
        # collected only because the old pattern stopped before the dot.
        return sorted({
            m.rstrip(".")
            for m in _NODE_ID_RE.findall(RESULTS.read_text(encoding="utf-8"))
        })

    def test_results_md_cites_at_least_one_node_id(self) -> None:
        """Non-vacuous floor.

        A reformat that stopped matching ``_NODE_ID_RE`` would turn the
        resolution test below into a permanent silent pass -- the born-weak
        shape where a gate reads as coverage precisely because it cannot fire.
        """
        cited = self._cited()
        assert cited, (
            "no pytest node-ids found in bench/RESULTS.md. Either the citation "
            "format changed (update _NODE_ID_RE) or the citations were removed "
            "(restore them -- they are what make the published figures "
            "checkable). Do not leave this test vacuously green."
        )

    def test_every_cited_node_id_collects(self) -> None:
        import subprocess

        unresolved: list[str] = []
        for node_id in self._cited():
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "-q", node_id],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True, encoding="utf-8",
            )
            if proc.returncode != 0 or "no tests collected" in proc.stdout:
                unresolved.append(f"{node_id} (rc={proc.returncode})")

        assert not unresolved, (
            "bench/RESULTS.md cites pytest node-id(s) that do not collect. A "
            "reader who runs them gets 'no tests collected', which reads as an "
            "unbacked claim on the project's credibility surface. The usual "
            "cause is an unqualified id for a test nested in a class -- use "
            "the Class::test form:\n  " + "\n  ".join(unresolved)
        )


# ---------------------------------------------------------------------------
# DEF-654: the README's oracle inventory is DERIVED from the tracked tree, not
# hand-kept. Two sites -- the "Curated, tracked" list and the layout tree --
# must each name every top-level bench/*.py; the tracked file list is the
# external witness (docs/SHARP_EDGES.md: parallel inventories drift
# independently; a hand-maintained enumeration rots silently). Three of four
# oracles were absent from both sites when this was filed.
# ---------------------------------------------------------------------------

def _top_level_bench_scripts() -> list[str]:
    scripts = sorted(Path(f).name for f in _git_ls_files("bench")
                     if f.count("/") == 1 and f.endswith(".py"))
    assert scripts, "no tracked top-level bench script: the witness is empty"
    return scripts


def _readme_region(start_marker: str, end_marker: str) -> str:
    """The README text between two markers, or a named failure: a reworded
    heading must read as 'the test lost its region', not as a traceback."""
    readme = (REPO_ROOT / "bench" / "README.md").read_text(encoding="utf-8")
    start = readme.find(start_marker)
    if start < 0:
        pytest.fail(f"bench/README.md lost the marker {start_marker!r}; the inventory "
                    "test cannot locate its region")
    end = readme.find(end_marker, start + len(start_marker))
    if end < 0:
        pytest.fail(f"bench/README.md lost the marker {end_marker!r} after "
                    f"{start_marker!r}; the inventory test cannot locate its region")
    return readme[start:end]


def test_bench_readme_tracked_list_names_every_top_level_oracle():
    scripts = _top_level_bench_scripts()
    region = _readme_region("**Curated, tracked**", "**Generated, NOT tracked**")
    missing = [s for s in scripts if f"`bench/{s}`" not in region]
    assert not missing, (
        "bench/README.md's 'Curated, tracked' list omits tracked oracle(s): "
        f"{missing}. A reader editing the guards opens this list to find which "
        "oracle to run before trusting a green suite; an unlisted one is never run."
    )


def test_bench_readme_layout_tree_names_every_top_level_oracle():
    scripts = _top_level_bench_scripts()
    region = _readme_region("```\nbench/\n", "\n```")
    # the tree-entry form, not a bare substring: `reachability_differential.py`
    # is a substring of its PowerShell twin's name
    missing = [s for s in scripts if f"\u2500\u2500 {s}" not in region]
    assert not missing, (
        f"bench/README.md's layout tree omits tracked oracle(s): {missing}"
    )
