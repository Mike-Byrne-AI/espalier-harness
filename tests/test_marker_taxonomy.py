"""TP-105: every test file gets a deliberate marker assignment.

The default-unit fallthrough in tests/conftest.py:_MARKER_RULES means
silent misclassification: a new contract test lands in the `unit`
bucket and runs in the fast slice (correct) OR a new security test
lands in `unit` and is invisible to `pytest -m security` (wrong).
This contract pins the assignment as explicit.

Prevents new test files defaulting silently to `unit`. Catches the
"new file lands in wrong slice" failure mode without requiring
contributors to know the marker taxonomy by heart.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent

_OPT_OUT_MARKER = "# pytest-marker: default-unit"


def _carries_default_unit_optout(text: str) -> bool:
    """True only when the opt-out appears as a real COMMENT token.

    Substring matching cannot tell a USE from a MENTION. This module and
    tests/test_test_suite_contract.py both discuss the marker in prose, and a
    substring test matches them against themselves -- which is how the
    redundant-opt-out contract below flagged its own author on first run.

    The same shape has now cost this repo four separate defects in a month:
    the Bash guards read prose ABOUT a command as the command, the
    retired-vocab scanner read a backticked severity term as a use of the
    label, the bench overclaim gate could not see a negation written in bold,
    and this. Whenever a guard fires on documentation, the question is role,
    not spelling -- so ask the tokenizer, which knows the difference between a
    comment and a string, instead of asking `in`.

    A file that does not tokenize returns False rather than guessing; pytest
    will fail its collection loudly, so this is not a silent hole.
    """
    try:
        return any(
            tok.type == tokenize.COMMENT and tok.string.startswith(_OPT_OUT_MARKER)
            for tok in tokenize.generate_tokens(io.StringIO(text).readline)
        )
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return False


class TestMarkerTaxonomyMembership:
    def test_every_test_file_is_classified(self):
        """Every tests/test_*.py file is named in _MARKER_RULES or carries
        an explicit `# pytest-marker: default-unit` opt-out comment.
        """
        from tests.conftest import _MARKER_RULES

        all_stems = {f.stem for f in TESTS_DIR.glob("test_*.py")}
        classified = {stem for tup, _marker in _MARKER_RULES for stem in tup}
        unclassified = all_stems - classified

        forgiven: set[str] = set()
        for stem in unclassified:
            text = (TESTS_DIR / f"{stem}.py").read_text(encoding="utf-8")
            # Token-level, not substring: a file that merely MENTIONS the
            # marker in prose must not be forgiven by it.
            if _carries_default_unit_optout(text):
                forgiven.add(stem)
        truly_unclassified = unclassified - forgiven

        assert not truly_unclassified, (
            "New test files default to `unit` marker silently. Either add "
            "the stem to the appropriate tuple in tests/conftest.py "
            "_MARKER_RULES, or add `# pytest-marker: default-unit` to opt "
            "out explicitly:\n  " + "\n  ".join(sorted(truly_unclassified))
        )

        # Reverse direction: a rule naming a file that no longer exists is
        # dead weight (a removed test file leaves an orphaned stem behind).
        orphaned = classified - all_stems
        assert not orphaned, (
            "tests/conftest.py _MARKER_RULES names test files that no longer "
            "exist:\n  " + "\n  ".join(sorted(orphaned))
        )

    def test_no_classified_file_also_carries_the_opt_out(self):
        """A file named in `_MARKER_RULES` must NOT also carry
        `# pytest-marker: default-unit`.

        The comment is inert while the stem is classified, which is exactly
        why it rots unseen: it keeps asserting the file is a default-unit
        fall-through long after the tuples say otherwise, and several such
        comments were found in 2026-08-24 still claiming "no subprocess" for
        modules that shell out two lines later. Worse, it is a LATENT
        re-forgiveness -- remove the stem from its tuple and the stale comment
        silently waves the file back into `unit` instead of redding the sibling
        assertion above.

        One statement, one owner: the tuples classify, the comment opts out,
        and no file gets to do both.
        """
        from tests.conftest import _MARKER_RULES

        classified = {stem for tup, _marker in _MARKER_RULES for stem in tup}
        both = sorted(
            stem for stem in classified
            if (TESTS_DIR / f"{stem}.py").exists()
            and _carries_default_unit_optout(
                (TESTS_DIR / f"{stem}.py").read_text(encoding="utf-8")
            )
        )
        assert not both, (
            "These files are classified in tests/conftest.py::_MARKER_RULES "
            "AND still carry a `# pytest-marker: default-unit` opt-out. The "
            "comment is stale and re-forgives the file into `unit` the moment "
            f"the stem leaves its tuple -- delete it: {both}"
        )


# --- doc readers run in the tier a docs-only change earns ---------------------

#: A tree-wide markdown sweep over the repository, not a fixture directory.
_DOC_SWEEP = re.compile(
    r"require_tracked_paths\([^)]*\*\.md|_tracked\(\s*[\"']\*\.md|ls-files[^\n]*\.md"
    r"|(?:REPO_ROOT|_REPO_ROOT|ROOT)\b[^\n]*\.r?glob\(\s*[\"'](?:\*\*/)?\*\.md"
)
#: A read of one named repository doc, rooted at the repo (not at tmp_path).
_NAMED_DOC = re.compile(
    r"(?:REPO_ROOT|_REPO_ROOT|\bROOT)\s*/\s*[\"'](?:docs|CLAUDE\.md|README\.md|CHANGELOG\.md"
    r"|ESPALIER_MEMORY\.md|task-packs|memory)\b"
)


def _marks_contract(decorators: list) -> bool:
    return any(
        (isinstance(d, ast.Attribute) and d.attr == "contract")
        or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "contract")
        for d in decorators
    )


def _module_pytestmark_has_contract(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            if any(isinstance(n, ast.Attribute) and n.attr == "contract" for n in ast.walk(node.value)):
                return True
    return False


def _unmarked_doc_readers(paths, primary_marker) -> list[str]:
    """Every test function whose verdict reads repository documentation -- a
    tree-wide markdown sweep or a named repo doc, directly or through a
    module-level helper or constant it uses (transitively, within the module)
    -- that the contract tier does not select: its file's primary marker is not
    ``contract`` and neither the module's ``pytestmark``, its class nor the
    function carries ``pytest.mark.contract``."""
    found = []
    for path in paths:
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        if primary_marker(path.stem) == "contract" or _module_pytestmark_has_contract(tree):
            continue
        table = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                table[node.name] = (node, None)
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        table[f"{node.name}.{sub.name}"] = (sub, node)
        lines = src.splitlines()

        def _reads_docs(node) -> bool:
            seg = "\n".join(lines[node.lineno - 1:node.end_lineno])
            return bool(_DOC_SWEEP.search(seg) or _NAMED_DOC.search(seg))

        consts = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and _reads_docs(node):
                consts |= {n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        # Each function's names once, and who uses each name: propagation is a
        # worklist over that index, linear in the module (a re-walk per pass
        # was quadratic and took a minute over the suite).
        used_by: dict[str, list[str]] = {}
        reads = {}
        for q, (n, _) in table.items():
            names = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
            names |= {x.attr for x in ast.walk(n) if isinstance(x, ast.Attribute)}
            reads[q] = _reads_docs(n) or bool(names & consts)
            for name in names:
                used_by.setdefault(name, []).append(q)
        work = [q for q, flag in reads.items() if flag]
        while work:
            other = work.pop()
            cls = other.split(".")[0] if "." in other else None
            for q in used_by.get(other.split(".")[-1], ()):
                if reads[q]:
                    continue
                # A module-level helper reaches every caller; a method only its class.
                if cls is None or (q.split(".")[0] if "." in q else None) == cls:
                    reads[q] = True
                    work.append(q)
        for q, (n, cls_node) in table.items():
            if not reads[q] or not n.name.startswith("test"):
                continue
            if _marks_contract(n.decorator_list) or (cls_node and _marks_contract(cls_node.decorator_list)):
                continue
            found.append(f"{path.name}::{q.replace('.', '::')}")
    return found


@pytest.mark.contract
class TestDocReadersRunInTheContractTier:
    """A docs-only pull request earns the contract tier (``scripts/proof_tier.py``),
    so a test whose verdict reads repository documentation and sits in any
    other tier never runs on the change that breaks it: the change merges
    green and ``main`` is red for the next lane that earns the full tier.
    Measured 2026-10-02: PR #69's ledger rows tripped the approval-marker
    over-claim sweep, which ran only because that lane also touched a
    workflow; a census then found 75 such tests (18 tree-wide sweeps, 61
    named-doc readers, 4 in both) outside the slice, about nine seconds of
    serial runtime in all, and marked them. This class keeps it that way.

    Heuristic by construction: a doc read through a helper in another module
    (``tests/_*.py``) is not followed, so a miss is possible; a hit is a test
    that reads a repo doc and must be marked ``contract``."""

    def test_every_doc_reading_test_is_in_the_contract_tier(self):
        from tests.conftest import _primary_marker

        missing = _unmarked_doc_readers(sorted(TESTS_DIR.glob("test_*.py")), _primary_marker)
        assert not missing, (
            "tests that read repository docs but run outside the contract tier "
            "(add @pytest.mark.contract):\n  " + "\n  ".join(missing)
        )

    def test_the_gate_reds_on_an_unmarked_reader_and_clears_on_a_marked_one(self, tmp_path):
        reader = (
            "from pathlib import Path\n"
            "REPO_ROOT = Path(__file__).parent\n"
            "def _read():\n"
            "    return (REPO_ROOT / \"docs\" / \"HOOKS.md\").read_text()\n"
            "def test_reads_a_doc():\n"
            "    assert _read()\n"
        )
        bare = tmp_path / "test_bare_reader.py"
        bare.write_text(reader, encoding="utf-8")
        marked = tmp_path / "test_marked_reader.py"
        marked.write_text(
            reader.replace("def test_reads_a_doc", "@pytest.mark.contract\ndef test_reads_a_doc"),
            encoding="utf-8",
        )
        unit = lambda stem: "unit"  # noqa: E731
        assert _unmarked_doc_readers([bare], unit) == ["test_bare_reader.py::test_reads_a_doc"]
        assert _unmarked_doc_readers([marked], unit) == []
        assert _unmarked_doc_readers([bare], lambda stem: "contract") == []
