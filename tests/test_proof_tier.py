"""Contract tests for ``scripts/proof_tier.py``, the one place the proof-tier
boundary is computed.

The boundary was prose in four bodies and drifted into three spellings within
a day; this script exists so the bodies can cite a computation instead. These
tests pin that computation -- a hook or engine file earns the full suite, a
file the pull-recall corpus reads earns the contract slice plus the recall
engine's own tests, any other doc or test or script earns the contract slice,
a byte-mirror under ``espalier/assets/`` does not count as engine code -- and
that an untracked file is named and fails the exit code, because the
``git ls-files`` gates cannot see it.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shlex
import subprocess
import sys
import types
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "proof_tier.py"
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _recall_module():
    """The pull-recall loader, imported the way its own tests import it, so the
    corpus predicate below is pinned against the corpus the tree really builds."""
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    import _recall
    return _recall


def _load():
    spec = importlib.util.spec_from_file_location("proof_tier", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pt():
    return _load()


def _repo(tmp_path):
    r = tmp_path / "r"; r.mkdir()
    for rel in ("tools/cc/hooks/h.py", "espalier/cli.py", "espalier/assets/docs/X.md",
                "espalier/_vendor/cc/hooks/h.py", "docs/X.md", "tests/test_x.py", "scripts/s.py",
                "memory/n.md"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text("x\n", encoding="utf-8")
    git = ["git", "-C", str(r), "-c", "user.email=a@b", "-c", "user.name=a"]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-qm", "i"], check=True, capture_output=True)
    return r


class TestTheBoundary:
    @pytest.mark.parametrize("rel,expected", [
        ("tools/cc/hooks/h.py", "full"),
        ("tools/cc/anything.md", "full"),
        ("espalier/cli.py", "full"),
        ("espalier/assets/docs/X.md", "contract"),
        ("espalier/_vendor/cc/hooks/h.py", "contract"),
        ("docs/X.md", "contract"),
        ("tests/test_x.py", "contract"),
        ("scripts/s.py", "contract"),
        (".claude/commands/c.md", "contract"),
        ("memory/n.md", "recall"),
        ("memory/README.md", "recall"),
        ("memory/notes.txt", "contract"),
        ("docs/sharp-edges/x.md", "recall"),
        ("docs/SHARP_EDGES.md", "recall"),
        ("docs/FAILURE_MODES.md", "recall"),
        ("docs/STANDING_PRINCIPLES.md", "recall"),
        ("docs/STANDING_PRINCIPLES.aliases.md", "recall"),
        ("docs/sharp-edges/README.md", "recall"),
        ("tests/fixtures/paraphrase_heldout_arm.md", "contract"),
        # A re-pin touches only the manifest; the contract tier is what it
        # earns, so the contract slice must hold every live-manifest reader
        # (TestTheContractSliceHoldsTheLiveManifestReaders below).
        (".espalier/freshness.json", "contract"),
        # Locally a workflow edit is a doc to the suite (the contract slice
        # holds the workflow-reading contracts; nothing here executes one).
        (".github/workflows/test.yml", "contract"),
        (".github/actions/setup/action.yml", "contract"),
        (".github/dependabot.yml", "contract"),
        # The suite's own configuration and shared test code move what every
        # test does; the contract slice cannot vouch for a selection it no
        # longer knows.
        ("tests/conftest.py", "full"),
        ("tests/_git_oracle.py", "full"),
        ("pyproject.toml", "full"),
        ("espalier.toml", "full"),
        ("tests/test_x.py", "contract"),
    ])
    def test_a_path_earns_its_tier(self, pt, rel, expected):
        assert pt.tier([rel]) == expected

    def test_a_workflow_is_runtime_only_where_it_runs(self, pt):
        """In a pull request's own run the changed workflow (or a composite
        action it calls) is what executes, so there it earns full; any other
        .github/ file never does."""
        assert pt.tier([".github/workflows/test.yml"], workflows_are_runtime=True) == "full"
        assert pt.tier([".github/actions/setup/action.yml"], workflows_are_runtime=True) == "full"
        assert pt.tier([".github/dependabot.yml"], workflows_are_runtime=True) == "contract"

    def test_a_changed_test_file_rides_along_on_the_cheaper_tiers(self, pt, tmp_path):
        """A test-only diff must run the test it changed: the contract slice
        is a hand-keyed marker set and holds almost none of them."""
        r = _repo(tmp_path)
        ride = shlex.join(("pytest", "-q", "tests/test_x.py"))
        assert ride in pt.commands("contract", ["tests/test_x.py"], r)
        assert ride in pt.commands("recall", ["tests/test_x.py"], r)
        assert ride not in pt.commands("full", ["tests/test_x.py"], r)
        assert pt.own_tests(["tests/test_missing.py"], r) == ()

    def test_the_runtime_outranks_the_corpus(self, pt):
        """A diff that touches a hook and a memory note earns the whole suite,
        which already contains the recall slice."""
        assert pt.tier(["memory/n.md", "tools/cc/hooks/h.py"]) == "full"
        assert pt.tier(["memory/n.md", "docs/X.md"]) == "recall"

    def test_a_memory_note_change_in_a_real_tree_earns_recall(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "memory" / "n.md").write_text("y\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("recall")
        assert "recall corpus changed: memory/n.md" in out
        for line in pt.RECALL_COMMANDS:
            assert "run: " + line in out
        # The tier's first line is byte-identical to the contract tier's only
        # line; the nudge is what stops a one-line paste reading as the tier.
        assert "all 2 lines are the tier" in out

    def test_a_docs_change_prints_no_multi_line_nudge(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        pt.main(["--root", str(r)])
        assert "lines are the tier" not in capsys.readouterr().out

    def test_a_modified_hook_in_a_real_tree_earns_full(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "tools" / "cc" / "hooks" / "h.py").write_text("y\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("full")
        for line in pt.FULL_COMMANDS:
            assert "run: " + line in out

    def test_a_docs_change_earns_contract(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        assert capsys.readouterr().out.startswith("contract")


def _git(r):
    return ["git", "-C", str(r), "-c", "user.email=a@b", "-c", "user.name=a"]


def _commit(r, rel, text="y\n", msg="c"):
    (r / rel).parent.mkdir(parents=True, exist_ok=True)
    (r / rel).write_text(text, encoding="utf-8")
    subprocess.run(_git(r) + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(_git(r) + ["commit", "-qm", msg], check=True, capture_output=True)


class TestTheBaseMode:
    """``--base <ref>`` classifies the merge-base diff -- the diff a pull
    request's own run is judged on -- and ``--quiet`` prints the one word the
    workflow step captures. Same ``tier()``, a different path source."""

    @pytest.mark.parametrize("rel,expected", [
        ("docs/X.md", "contract"),
        ("memory/n.md", "recall"),
        ("tools/cc/hooks/h.py", "full"),
        (".github/workflows/ci.yml", "full"),
    ])
    def test_a_committed_change_earns_its_tier_against_the_base(
        self, pt, tmp_path, capsys, rel, expected
    ):
        r = _repo(tmp_path)
        _commit(r, rel)
        assert pt.main(["--root", str(r), "--base", "HEAD~1", "--quiet"]) == 0
        assert capsys.readouterr().out == expected + "\n"

    def test_the_diff_is_against_the_merge_base_not_the_base_tip(self, pt, tmp_path, capsys):
        """A local branch behind a base that moved on: the base's own later
        runtime change is not on this branch's bill. (On a pull request's own
        run HEAD is the merge ref, so the shape does not arise there; the
        merge-base rule is what makes both shapes read the branch's changes.)"""
        r = _repo(tmp_path)
        default = subprocess.run(
            _git(r) + ["rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout.strip()
        subprocess.run(_git(r) + ["checkout", "-qb", "topic"], check=True, capture_output=True)
        _commit(r, "docs/X.md")
        subprocess.run(_git(r) + ["checkout", "-q", default], check=True, capture_output=True)
        _commit(r, "tools/cc/hooks/h.py", text="moved on\n")
        subprocess.run(_git(r) + ["checkout", "-q", "topic"], check=True, capture_output=True)
        assert pt.main(["--root", str(r), "--base", default, "--quiet"]) == 0
        assert capsys.readouterr().out == "contract\n"

    def test_a_deleted_runtime_file_still_earns_full(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "tools" / "cc" / "hooks" / "h.py").unlink()
        subprocess.run(_git(r) + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(_git(r) + ["commit", "-qm", "rm"], check=True, capture_output=True)
        assert pt.main(["--root", str(r), "--base", "HEAD~1", "--quiet"]) == 0
        assert capsys.readouterr().out == "full\n"

    def test_an_untracked_file_is_not_consulted_in_base_mode(self, pt, tmp_path, capsys):
        """The local refusal (exit 2, `git add -N`) is about a working tree; a
        CI checkout has no untracked files, and a stray one here must not
        turn the answer into a refusal."""
        r = _repo(tmp_path)
        _commit(r, "docs/X.md")
        (r / "scripts" / "new.py").write_text("x\n", encoding="utf-8")
        assert pt.main(["--root", str(r), "--base", "HEAD~1", "--quiet"]) == 0
        assert capsys.readouterr().out == "contract\n"

    def test_an_unresolvable_base_is_a_loud_exit(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        assert pt.main(["--root", str(r), "--base", "no-such-ref", "--quiet"]) == 3
        err = capsys.readouterr().err
        assert "no-such-ref" in err

    def test_an_unresolvable_base_with_a_forced_tier_runs_over_an_empty_diff(
        self, pt, tmp_path, capsys
    ):
        """The `test` cells force the tier the `tier` job chose; the diff only
        adds the changed test files. A base the cells cannot resolve must not
        red five required checks with zero tests run."""
        r = _repo(tmp_path)
        assert pt.main(["--root", str(r), "--base", "no-such-ref", "--tier", "contract", "--quiet"]) == 0
        out, err = capsys.readouterr()
        assert out == "contract\n"
        assert "no-such-ref" in err and "empty diff" in err

    def test_a_committed_test_change_runs_that_file(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        _commit(r, "tests/test_x.py")
        assert pt.main(["--root", str(r), "--base", "HEAD~1"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("contract")
        assert "run: pytest -q tests/test_x.py" in out

    def test_a_hook_moved_out_of_the_runtime_still_earns_full(self, pt, tmp_path, capsys):
        """Renames are read as delete plus add, so the vacated runtime path is
        on the bill; with rename detection on it would read as a docs change."""
        r = _repo(tmp_path)
        subprocess.run(_git(r) + ["mv", "tools/cc/hooks/h.py", "docs/h.py"], check=True, capture_output=True)
        subprocess.run(_git(r) + ["commit", "-qm", "mv"], check=True, capture_output=True)
        assert pt.main(["--root", str(r), "--base", "HEAD~1", "--quiet"]) == 0
        assert capsys.readouterr().out == "full\n"

    def test_json_in_base_mode_names_the_base_and_the_workflow_paths(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        _commit(r, ".github/workflows/ci.yml")
        assert pt.main(["--root", str(r), "--base", "HEAD~1", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["tier"] == "full"
        assert data["base"] == "HEAD~1"
        assert data["ci_definition_paths"] == [".github/workflows/ci.yml"]
        assert data["runtime_paths"] == [] and data["untracked"] == []


class TestUntrackedFilesAreNamed:
    def test_an_untracked_file_fails_the_exit_and_is_listed_until_intent_added(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "scripts" / "new.py").write_text("x\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 2
        assert "git add -N scripts/new.py" in capsys.readouterr().out
        subprocess.run(["git", "-C", str(r), "add", "-N", "scripts/new.py"], check=True)
        assert pt.main(["--root", str(r)]) == 0

    def test_json_carries_the_same_answer(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "espalier" / "cli.py").write_text("y\n", encoding="utf-8")
        pt.main(["--root", str(r), "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["tier"] == "full" and data["runtime_paths"] == ["espalier/cli.py"] and data["untracked"] == []
        assert data["commands"] == list(pt.FULL_COMMANDS)


class TestTheFullRecipe:
    """The full tier is the parallel run minus the wall-clock-budget files, then
    those files serially. The list has one home, ``WALL_CLOCK_SERIAL_FILES``;
    every member must exist, and the two lines must agree on it."""

    def test_every_wall_clock_file_exists(self, pt):
        for rel in pt.WALL_CLOCK_SERIAL_FILES:
            assert (REPO_ROOT / rel).is_file(), rel

    def test_the_full_tier_runs_the_hook_type_gate_first_and_the_contract_tier_never(self, pt):
        """The near-strict mypy gate lived only in CI from 2026-07-23 and went red
        unread twice; the full tier runs it first, on exactly the diffs that
        can break it."""
        assert pt.FULL_COMMANDS[0] == "mypy tools/cc/hooks/"
        assert not any(c.startswith("mypy") for c in pt.CONTRACT_COMMANDS)

    def test_the_parallel_line_leaves_out_exactly_the_files_the_serial_line_runs(self, pt):
        parallel, serial = [c for c in pt.FULL_COMMANDS if c.startswith("pytest ")]
        assert " -n auto " in parallel and " -n " not in serial
        ignored = sorted(tok[len("--ignore="):] for tok in parallel.split() if tok.startswith("--ignore="))
        assert ignored == sorted(pt.WALL_CLOCK_SERIAL_FILES)
        assert sorted(tok for tok in serial.split() if tok.startswith("tests/")) == sorted(pt.WALL_CLOCK_SERIAL_FILES)

    def test_the_contract_tier_is_one_serial_command(self, pt):
        assert pt.commands("contract") == ("pytest -m contract -q",)

    def test_the_recall_tier_is_the_contract_slice_then_the_recall_files(self, pt):
        assert pt.commands("recall") == (
            "pytest -m contract -q",
            "pytest -q " + " ".join(pt.RECALL_SLICE_FILES),
        )
        assert not any(c.startswith("mypy") for c in pt.RECALL_COMMANDS)

    def test_a_changed_scripts_own_test_file_rides_along_on_the_cheaper_tiers(self, pt):
        """`tests/test_ledger_row.py` is integration-classified, so the contract
        tier collected none of the rows written for the row tool's 2026-09-20
        fix (failure-mode pass; DEF-775's shape one directory over). Derived
        from the diff, never enumerated: a changed `scripts/<stem>.py` brings
        `tests/test_<stem>.py` when it exists, on the two cheaper tiers; the
        full tier already runs it, so nothing is appended there. Earn-the-red:
        the function did not exist before this test. Since 2026-09-25 a changed
        test file rides along the same way (the last assertion below)."""
        changed = ["scripts/ledger_row.py", "scripts/no_such_script.py", "docs/X.md", "tests/test_x.py",
                   "scripts/ledger_row.py"]
        assert pt.own_tests(changed, REPO_ROOT) == ("tests/test_ledger_row.py",)
        assert pt.commands("contract", changed, REPO_ROOT) == (
            "pytest -m contract -q", "pytest -q tests/test_ledger_row.py")
        assert pt.commands("recall", changed, REPO_ROOT) == (
            *pt.RECALL_COMMANDS, "pytest -q tests/test_ledger_row.py")
        assert pt.commands("full", changed, REPO_ROOT) == pt.FULL_COMMANDS
        # the tier-only spellings the bodies cite are unchanged
        assert pt.commands("contract") == ("pytest -m contract -q",)
        assert pt.own_tests(["scripts/nested/x.py", "tests/nested/test_y.py"], REPO_ROOT) == ()
        assert pt.own_tests(["tests/test_proof_tier.py"], REPO_ROOT) == ("tests/test_proof_tier.py",)

    def test_a_changed_script_in_a_real_tree_prints_and_runs_its_own_test_line(self, pt, tmp_path, capsys):
        """The receipt path, not only `commands()`: `main` must hand the diff to
        the tier, or the printed lines and the executed argvs are the tier's
        alone. The repo helper ships `scripts/s.py` with no test; commit one, then
        change the script."""
        r = _repo(tmp_path)
        (r / "tests" / "test_s.py").write_text("def test_s():\n    pass\n", encoding="utf-8")
        git = ["git", "-C", str(r), "-c", "user.email=a@b", "-c", "user.name=a"]
        subprocess.run(git + ["add", "tests/test_s.py"], check=True, capture_output=True)
        subprocess.run(git + ["commit", "-qm", "t"], check=True, capture_output=True)
        (r / "scripts" / "s.py").write_text("y\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("contract")
        assert "run: pytest -q tests/test_s.py" in out
        assert "all 2 lines are the tier" in out
        # and the argv list --run would execute carries the same line
        changed, untracked = pt.changed_paths(r)
        assert pt.tier_argvs("contract", changed + untracked, r)[-1] == ("pytest", "-q", "tests/test_s.py")


#: Engine entry points that read the freshness manifest of the root they are
#: handed, by the module that defines each. A test that calls one with the
#: module's ``REPO_ROOT`` asserts on the live manifest as surely as one that
#: opens the file. Resolved through the test module's own imports, because
#: every scanner defines a ``scan_repo`` and only these read the manifest.
#: Hand-kept: a new entry point that reads the manifest is added here when
#: it is written.
_LIVE_MANIFEST_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    "espalier.freshness": ("scan_repo",),
    "espalier.scanners.freshness": ("scan_repo",),
    "espalier.audit_accuracy": ("audit_accuracy",),
}


def _div_chain(node: ast.expr) -> list[ast.expr]:
    """``a / b / c`` as ``[a, b, c]``; any other node as ``[node]``."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _div_chain(node.left) + [node.right]
    return [node]


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a Name/Attribute chain, else ``None``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _manifest_reader_names(tree: ast.Module) -> set[str]:
    """The dotted call names that reach a ``_LIVE_MANIFEST_ENTRYPOINTS``
    function in this module: the bare name it was imported under
    (``from espalier.freshness import scan_repo [as x]``) or ``<alias>.<fn>``
    for a module imported whole (``import espalier.scanners.freshness as scn``,
    ``from espalier.scanners import freshness [as scn]``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                bound = alias.asname or alias.name
                if node.module in _LIVE_MANIFEST_ENTRYPOINTS:
                    if alias.name in _LIVE_MANIFEST_ENTRYPOINTS[node.module]:
                        names.add(bound)
                elif full in _LIVE_MANIFEST_ENTRYPOINTS:
                    names.update(f"{bound}.{fn}" for fn in _LIVE_MANIFEST_ENTRYPOINTS[full])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _LIVE_MANIFEST_ENTRYPOINTS:
                    bound = alias.asname or alias.name
                    names.update(f"{bound}.{fn}" for fn in _LIVE_MANIFEST_ENTRYPOINTS[alias.name])
    return names


def _reads_live_manifest(source: str) -> bool:
    """Whether a test module asserts on the LIVE tree's freshness manifest.

    Two shapes, read from the AST so a mention in a comment or a docstring
    does not count (the mention-vs-use rule tests/test_marker_taxonomy.py
    documents): the manifest path built from the module's ``REPO_ROOT``
    (``REPO_ROOT / ".espalier" / "freshness.json"``, or the two segments as
    one), and a call of a ``_LIVE_MANIFEST_ENTRYPOINTS`` function -- resolved
    through the module's imports -- with ``REPO_ROOT`` as its first argument.
    What this cannot see is the stated bound, not a claim of completeness: a
    helper under ``tests/_*.py``, a root under another name, a reader under
    ``tests/fixtures/``.
    """
    tree = ast.parse(source)
    readers = _manifest_reader_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            head, *segments = _div_chain(node)
            if isinstance(head, ast.Name) and head.id == "REPO_ROOT":
                literal = "/".join(
                    s.value for s in segments
                    if isinstance(s, ast.Constant) and isinstance(s.value, str)
                )
                if literal.endswith(".espalier/freshness.json"):
                    return True
        if isinstance(node, ast.Call) and node.args and readers:
            first = node.args[0]
            if (
                _dotted(node.func) in readers
                and isinstance(first, ast.Name) and first.id == "REPO_ROOT"
            ):
                return True
    return False


class TestTheContractSliceHoldsTheLiveManifestReaders:
    """A re-pin changes ``.espalier/freshness.json`` and nothing else, and the
    contract tier is what that diff earns; so every test that asserts on the
    live manifest must be classified ``contract``, or a re-pin lands blind to
    it. ff9eaff (2026-09-19) re-pinned ``hook-count`` one fragment at a time
    and dropped its literal; the file that reds on that sat in the security
    roster (so ``-m contract`` never collected it) and in ``_SLOW_FILES`` (so
    the fast slice never ran it), and ``main`` went red for a day (the
    pre-cut review's D1). The population is derived by ``_reads_live_manifest``
    from every ``tests/test_*.py``, and the classifier asked is the one
    collection uses -- not a second roster."""

    def _readers(self) -> list[str]:
        return sorted(
            p.stem for p in (REPO_ROOT / "tests").glob("test_*.py")
            if _reads_live_manifest(p.read_text(encoding="utf-8"))
        )

    def test_the_rows_this_was_written_for_are_in_the_population(self):
        # The stressor exists, for both shapes: a green below over a
        # population that lost a known member to a reworded read would be
        # silent. The first two read the path; the third calls an entry point.
        readers = self._readers()
        for stem in (
            "test_freshness_hook_count_migration",
            "test_freshness_semantic_fragments",
            "test_scanner_freshness",
        ):
            assert stem in readers, (
                f"tests/{stem}.py no longer reads the live manifest by a shape "
                f"_reads_live_manifest knows -- teach it the new shape, do not "
                f"drop the contract"
            )

    def test_a_mention_is_not_a_read(self):
        # This module spells both shapes in prose and never reads the manifest.
        assert "test_proof_tier" not in self._readers()

    def test_every_live_manifest_reader_is_contract_classified(self):
        from tests.conftest import _primary_marker
        wrong = {
            stem: _primary_marker(stem)
            for stem in self._readers()
            if _primary_marker(stem) != "contract"
        }
        assert not wrong, (
            f"these test modules assert on the live freshness manifest but are "
            f"not in the contract roster of tests/conftest.py::_MARKER_RULES, so "
            f"a re-pin (which earns the contract tier) cannot see them red: "
            f"{wrong}. Move each stem to the contract tuple (and exempt it in "
            f"tests/test_documented_claims.py::TestSecurityMarkerCoverage if its "
            f"name carries a security token), or make the test read a fixture "
            f"copy instead of the live tree."
        )


class TestTheRecallSlice:
    """The recall tier's two rosters have one home each in the script and are
    pinned against what the tree holds: the slice against every
    ``tests/test_recall*.py`` (the derived complement of a hand-kept list, as
    the wall-clock list is), the corpus predicate against the files the
    pull-recall loader actually reads, in both directions."""

    def test_every_recall_slice_file_exists(self, pt):
        for rel in pt.RECALL_SLICE_FILES:
            assert (REPO_ROOT / rel).is_file(), rel

    def test_the_slice_is_every_recall_test_file(self, pt):
        on_disk = sorted(f"tests/{p.name}" for p in (REPO_ROOT / "tests").glob("test_recall*.py"))
        assert on_disk == sorted(pt.RECALL_SLICE_FILES), (
            "a tests/test_recall*.py file is not in RECALL_SLICE_FILES (or a listed "
            "one is gone) -- a corpus change would land without running it"
        )

    def test_every_indexed_file_satisfies_the_predicate(self, pt):
        """Forward direction: no file the corpus reads can change on the contract
        tier. Pointer entries carry a repo path as their `source` but are not
        read from disk, so they are the one family left out."""
        rc = _recall_module()
        docs = rc._load_corpus(REPO_ROOT)
        assert len(docs) > 200, "corpus collapsed; the assertion below would be vacuous"
        files = sorted({d.source.split(" :: ", 1)[0] for d in docs
                        if d.family != "pull-only shape pointers"})
        missed = [f for f in files if not pt.is_recall_corpus(f)]
        assert not missed, f"corpus files the tier predicate does not cover: {missed[:5]}"

    def test_every_listed_source_is_read_by_the_loader(self, pt):
        """Reverse direction: a listed file or prefix that the loader no longer
        reads is a stale row that would earn the slice for nothing."""
        rc = _recall_module()
        docs = rc._load_corpus(REPO_ROOT)
        files = {d.source.split(" :: ", 1)[0] for d in docs
                 if d.family != "pull-only shape pointers"}
        for prefix in pt._RECALL_CORPUS_PREFIXES:
            assert any(f.startswith(prefix) for f in files), prefix
        loader = (HOOKS_DIR / "_recall.py").read_text(encoding="utf-8")
        for rel in pt._RECALL_CORPUS_FILES:
            assert (REPO_ROOT / rel).is_file(), rel
            # The aliases sidecar is folded into the principles' bags rather than
            # yielded as a doc, so it is pinned by the loader naming it.
            assert rel in files or rel.rsplit("/", 1)[-1] in loader, rel

    def test_json_carries_the_corpus_paths(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "memory" / "n.md").write_text("y\n", encoding="utf-8")
        pt.main(["--root", str(r), "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["tier"] == "recall" and data["corpus_paths"] == ["memory/n.md"]
        assert data["runtime_paths"] == [] and data["commands"] == list(pt.RECALL_COMMANDS)

    def test_an_unwired_tier_raises_instead_of_falling_through_to_the_cheaper_one(self, pt):
        with pytest.raises(KeyError):
            pt.commands("nonsense")

    def test_the_root_claude_md_build_block_quotes_the_commands(self, pt):
        """The build block is the one place the two lines are restated for
        pasting; this pins that second home to the constant."""
        text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for line in pt.FULL_COMMANDS:
            assert line in text, line

    def test_no_unlisted_test_file_asserts_a_wall_clock_upper_bound(self, pt):
        """The derived complement of the hand-kept list: a wall-clock bound --
        a clock-derived local compared against a ceiling, or a `setitimer`
        arm -- in any module under tests/ that is not one of the serial files
        would false-fail the default parallel run. The population is every
        `.py` under tests/, helpers included (a timed helper hoisted into a
        `tests/_*.py` module still runs in the parallel slice); a hit is a
        real bound site by the AST walk the rule itself uses, so a snippet
        quoted in a string -- this file's own must-trip rows -- is not an
        offender, and `test_the_detector_...` below are its twins."""
        offenders = _unlisted_wall_clock_files(
            sorted((REPO_ROOT / "tests").glob("*.py")), set(pt.WALL_CLOCK_SERIAL_FILES),
        )
        assert not offenders, f"wall-clock upper bounds outside WALL_CLOCK_SERIAL_FILES: {offenders}"

    def test_the_detector_flags_a_bound_on_a_clock_derived_local(self, tmp_path):
        """The must-trip twin, on the shape the failure-mode review drove past
        the first cut: a local not named `elapsed*` compared against a named
        ceiling, no `setitimer` anywhere."""
        offender = tmp_path / "test_probe.py"
        offender.write_text(
            "import time\nmax_took = 5\ndef test_x():\n    t = time.time()\n"
            "    took = time.time() - t\n    assert took < max_took\n",
            encoding="utf-8",
        )
        assert _unlisted_wall_clock_files([offender], set()) == ["test_probe.py"]

    def test_the_detector_ignores_a_bound_quoted_in_a_string(self, tmp_path):
        """The must-NOT-trip twin: the text of a bound inside a string literal
        is not a site (this file carries ten of them)."""
        quiet = tmp_path / "test_quiet.py"
        quiet.write_text(
            'SNIPPET = "signal.setitimer(signal.ITIMER_REAL, 1.0); assert elapsed_ms < 1000"\n',
            encoding="utf-8",
        )
        assert _unlisted_wall_clock_files([quiet], set()) == []


# ── the wall-clock rule (DEF-922) ─────────────────────────────────────────────
#
# Every ceiling a serial timing file asserts is a named constant no less than
# ten times a named, dated floor -- the rule `tests/test_redos.py` states at its
# constants block. It was applied by hand at five sites in two days
# (2026-09-23/24) and pinned nowhere, so each new row shipped at twice or three
# times a floor measured on the self-host box and was found one shared-runner
# red at a time (the fifth on the release tree's closing witness). This derives
# the population from the files themselves and from the timing IDIOM, not a
# vocabulary: a local assigned from a clock reading (`time.time()`,
# `perf_counter()`, `monotonic()`, spelled through `time.` or a bare import,
# transitively through other locals) compared against anything that is not
# itself a clock reading, and every `setitimer` arm; a bound that is a helper's
# parameter is followed to the helper's call sites. Each site is judged against
# the file's own `_WALL_CLOCK_FLOORS` pairing of ceiling -> (floor, date, the
# floor's value at the pin). Two things the rule holds fixed: the pairing
# records the floor's VALUE with its date, so a floor edited alone reds until
# both move together; and A CEILING NEVER DROPS -- the high-water table below
# reds a ceiling under the value it was pinned at, so a floor re-measured on a
# faster host cannot lower the line a slower runner is read against (the
# failure-mode review's arithmetic: a chain floor of 340 ms here is about
# 1000 ms on a 3x runner against a 3400 ceiling; re-pinned on a 2.5x-faster
# box it would read 136, the derived ceiling 1360, and the runner would red
# again). A bound a row must NOT satisfy -- a must-trip witness whose pass IS
# the alarm -- opts out on its own line with `# wall-clock-exempt: <reason>`,
# and the exemption census below is exact.

_WALL_CLOCK_PAIRING = "_WALL_CLOCK_FLOORS"
_WALL_CLOCK_EXEMPT = "# wall-clock-exempt:"
_WALL_CLOCK_MULTIPLE = 10
_CLOCK_CALLS = frozenset({"time", "perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "process_time"})
#: The population at the pin, and the floor the scan must clear before its
#: verdict is read: a scan that finds fewer bound sites than half the pinned
#: population is broken, not looking at clean files
#: (docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md). The tracking
#: row reds under half or over twice the pin; re-pin the number here when it
#: does, with the date.
_WALL_CLOCK_SITES_AT_PIN = 65  # 2026-09-24: 59 in test_redos.py, 5 in test_speedbump_irreversible.py, 1 in test_hooks.py (upper bounds only)
_WALL_CLOCK_SITE_FLOOR = _WALL_CLOCK_SITES_AT_PIN // 2
#: The ratchet: every ceiling a serial file pairs, at the value it was pinned
#: at. A new ceiling is enrolled here at its value in the same commit; a mark
#: is lowered only with the reason in the commit, never because a floor read
#: lower on a faster host. (file, ceiling name) -> milliseconds.
_WALL_CLOCK_HIGH_WATER: dict[tuple[str, str], float] = {
    ("tests/test_redos.py", "_CI_SAFE_BUDGET_MS"): 1000,
    ("tests/test_redos.py", "_CHAIN_CEILING_MS"): 3400,
    ("tests/test_redos.py", "_WALKER_CEILING_MS"): 8800,
    ("tests/test_speedbump_irreversible.py", "_SPEEDBUMP_CI_SAFE_MS"): 500,
    ("tests/test_speedbump_irreversible.py", "_SPEEDBUMP_GIT_CEILING_MS"): 80,
    ("tests/test_hooks.py", "_ENV_PREFIX_CEILING_MS"): 1000,
}
#: The exemption census, EXACT: (file, enclosing function). A marker is the
#: cheapest way to silence the rule, so every one is enrolled here with the
#: row that carries it, and an unenrolled one reds.
_WALL_CLOCK_EXEMPTIONS: frozenset[tuple[str, str]] = frozenset({
    ("tests/test_redos.py", "test_the_nested_run_the_gate_once_carried_is_caught_by_these_rows"),
})
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class WallClockReading(NamedTuple):
    sites: int
    problems: list[str]
    exemptions: frozenset[tuple[str, str]]


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level `NAME = <expr>` (plain or annotated) by name."""
    out: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def _resolve_number(expr: ast.expr | None, consts: dict[str, ast.expr], depth: int = 0) -> float | None:
    """A literal number, a named module constant, or a product or quotient of
    those, followed through the constants; None for anything else."""
    if expr is None or depth > 8:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, (int, float)) and not isinstance(expr.value, bool):
        return float(expr.value)
    if isinstance(expr, ast.Name):
        return _resolve_number(consts.get(expr.id), consts, depth + 1)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Mult, ast.Div)):
        left = _resolve_number(expr.left, consts, depth + 1)
        right = _resolve_number(expr.right, consts, depth + 1)
        if left is None or right is None:
            return None
        if isinstance(expr.op, ast.Mult):
            return left * right
        return left / right if right else None
    return None


def _bound_name(expr: ast.expr) -> str | None:
    """The one Name a bound is built on -- `X`, `X / 1000.0`, `X * 1000`,
    `10 * X` -- or None for a literal or any other shape."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Mult, ast.Div)):
        if isinstance(expr.left, ast.Name) and isinstance(expr.right, ast.Constant):
            return expr.left.id
        if isinstance(expr.op, ast.Mult) and isinstance(expr.right, ast.Name) and isinstance(expr.left, ast.Constant):
            return expr.right.id
    return None


def _is_clock_call(expr: ast.AST) -> bool:
    """`time.perf_counter()` and its siblings, through `time.` or a bare import."""
    if not isinstance(expr, ast.Call):
        return False
    f = expr.func
    if isinstance(f, ast.Attribute):
        return isinstance(f.value, ast.Name) and f.value.id == "time" and f.attr in _CLOCK_CALLS
    return isinstance(f, ast.Name) and f.id in _CLOCK_CALLS


def _mentions_clock(expr: ast.AST, clock_names: set[str]) -> bool:
    return any(
        _is_clock_call(node) or (isinstance(node, ast.Name) and node.id in clock_names)
        for node in ast.walk(expr)
    )


def _clock_names(scope: ast.AST) -> set[str]:
    """Every name in `scope` assigned from a clock reading, or from an
    expression over another such name, to a fixpoint -- the timed locals,
    whatever they are called."""
    names: set[str] = set()
    assigns = [n for n in ast.walk(scope) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names and _mentions_clock(node.value, names):
                    names.add(target.id)
                    changed = True
    return names


def _is_setitimer(func: ast.expr) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "setitimer") or (
        isinstance(func, ast.Name) and func.id == "setitimer"
    )


def _is_zero(expr: ast.expr) -> bool:
    return isinstance(expr, ast.Constant) and not isinstance(expr.value, bool) and expr.value == 0


def _bound_sites(tree: ast.Module) -> list[tuple[int, ast.expr, ast.FunctionDef | None]]:
    """Every (line, bound expression, enclosing function): the second argument
    of a `setitimer(ITIMER_REAL, ...)` arm other than the literal-0 disarm, and
    the far side of every comparison that bounds a clock reading FROM ABOVE --
    `clock < X`, `clock <= X`, `X > clock`, `X >= clock` -- which is the only
    shape a slow host can red. A lower bound (`elapsed >= hold * 0.5`, a lock
    that must block), a liveness floor against the literal 0, an identity or
    equality test (`best is None`) and a comparison of two clock readings (a
    spinner's `perf_counter() < end`) are none of them ceilings. An overrun
    test spelled `clock >= CEILING` is not counted either: the idiom is
    `clock < CEILING`, and the constant it names is asserted that way
    elsewhere or the pairing check reds."""
    sites: list[tuple[int, ast.expr, ast.FunctionDef | None]] = []

    def walk(node: ast.AST, func: ast.FunctionDef | None, clock: set[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                walk(child, child, _clock_names(child))
                continue
            if isinstance(child, ast.Call) and _is_setitimer(child.func) and len(child.args) >= 2:
                arg = child.args[1]
                if not _is_zero(arg):
                    sites.append((child.lineno, arg, func))
            if isinstance(child, ast.Compare) and len(child.comparators) == 1:
                left, right = child.left, child.comparators[0]
                op = child.ops[0]
                left_clock, right_clock = _mentions_clock(left, clock), _mentions_clock(right, clock)
                if isinstance(op, (ast.Lt, ast.LtE)) and left_clock and not right_clock and not _is_zero(right):
                    sites.append((child.lineno, right, func))
                elif isinstance(op, (ast.Gt, ast.GtE)) and right_clock and not left_clock and not _is_zero(left):
                    sites.append((child.lineno, left, func))
            walk(child, func, clock)

    walk(tree, None, _clock_names(tree))
    return sites


def _ceiling_names(
    expr: ast.expr, func: ast.FunctionDef | None, tree: ast.Module, rel: str, lineno: int, problems: list[str],
) -> list[str]:
    """The ceiling names a site asserts: the bound's own Name, or -- when that
    Name is a parameter of the enclosing helper -- the Name each call site
    passes for it. Literals at either level are recorded as problems."""
    name = _bound_name(expr)
    if name is None:
        problems.append(
            f"{rel}:{lineno}: the bound `{ast.unparse(expr)}` is a literal, not a named ceiling "
            f"(name it and pair it in {_WALL_CLOCK_PAIRING}; or, when the alarm firing IS the pass, "
            f"opt out on this same line with `{_WALL_CLOCK_EXEMPT} <reason>`)"
        )
        return []
    if func is None:
        return [name]
    params = [a.arg for a in func.args.args]
    if name not in params and name not in {a.arg for a in func.args.kwonlyargs}:
        return [name]
    position = params.index(name) if name in params else None
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == func.name
    ]
    if not calls:
        problems.append(f"{rel}:{lineno}: `{func.name}` times its `{name}` parameter and nothing calls it")
    out: list[str] = []
    for call in calls:
        arg = call.args[position] if position is not None and position < len(call.args) else None
        if arg is None:
            arg = next((k.value for k in call.keywords if k.arg == name), None)
        if arg is None:
            problems.append(f"{rel}:{call.lineno}: `{func.name}(...)` passes no `{name}`")
            continue
        inner = _bound_name(arg)
        if inner is None:
            problems.append(
                f"{rel}:{call.lineno}: `{func.name}(...)` passes the literal `{ast.unparse(arg)}` "
                f"as `{name}`, not a named ceiling"
            )
            continue
        out.append(inner)
    return out


def wall_clock_violations(
    files: list[tuple[str, str]], high_water: dict[tuple[str, str], float],
) -> WallClockReading:
    """The rule as a pure function over (relative path, source) pairs and a
    high-water table, so the must-trip rows below can feed it a snippet with
    one thing wrong."""
    from datetime import date

    seen = 0
    problems: list[str] = []
    exemptions: set[tuple[str, str]] = set()
    paired: set[tuple[str, str]] = set()
    for rel, text in files:
        tree = ast.parse(text)
        lines = text.splitlines()
        consts = _module_constants(tree)
        pairing: dict = {}
        pairing_expr = consts.get(_WALL_CLOCK_PAIRING)
        if pairing_expr is not None:
            try:
                pairing = ast.literal_eval(pairing_expr)
            except ValueError:
                problems.append(f"{rel}: {_WALL_CLOCK_PAIRING} is not a literal dict")
        used: set[str] = set()
        sites = _bound_sites(tree)
        seen += len(sites)
        if sites and pairing_expr is None:
            problems.append(f"{rel}: {len(sites)} bound sites and no {_WALL_CLOCK_PAIRING} pairing")
        for lineno, expr, func in sites:
            line = lines[lineno - 1]
            if _WALL_CLOCK_EXEMPT in line:
                if not line.split(_WALL_CLOCK_EXEMPT, 1)[1].strip():
                    problems.append(f"{rel}:{lineno}: `{_WALL_CLOCK_EXEMPT}` without a reason")
                exemptions.add((rel, func.name if func is not None else "<module>"))
                continue
            for name in _ceiling_names(expr, func, tree, rel, lineno, problems):
                if name not in pairing:
                    problems.append(f"{rel}:{lineno}: `{name}` is not paired with a floor in {_WALL_CLOCK_PAIRING}")
                used.add(name)
        for ceiling, entry in pairing.items():
            paired.add((rel, ceiling))
            if ceiling not in used:
                problems.append(f"{rel}: {ceiling} is paired in {_WALL_CLOCK_PAIRING} and no timer or comparison asserts it")
            if not (
                isinstance(entry, tuple) and len(entry) == 3
                and isinstance(entry[0], str) and isinstance(entry[1], str)
                and isinstance(entry[2], (int, float)) and not isinstance(entry[2], bool)
            ):
                problems.append(f"{rel}: {_WALL_CLOCK_PAIRING}[{ceiling!r}] is not a (floor name, date, floor value) triple")
                continue
            floor_name, dated, pinned = entry
            ceiling_ms = _resolve_number(consts.get(ceiling), consts)
            floor_ms = _resolve_number(consts.get(floor_name), consts)
            if ceiling_ms is None:
                problems.append(f"{rel}: {ceiling} does not resolve to a number")
            if floor_ms is None:
                problems.append(f"{rel}: {floor_name} (the floor paired with {ceiling}) does not resolve to a number")
            else:
                if abs(floor_ms - pinned) > 1e-9:
                    problems.append(
                        f"{rel}: {floor_name} reads {floor_ms:g} ms and the pairing records {pinned:g} ms dated "
                        f"{dated}: a floor is re-pinned by measuring, then moving the constant, the pairing's "
                        "value and its date together"
                    )
                if ceiling_ms is not None and ceiling_ms < _WALL_CLOCK_MULTIPLE * floor_ms:
                    problems.append(
                        f"{rel}: {ceiling} = {ceiling_ms:g} ms is under {_WALL_CLOCK_MULTIPLE} x "
                        f"{floor_name} = {floor_ms:g} ms"
                    )
            try:
                if not _ISO_DATE_RE.match(dated) or date.fromisoformat(dated) > date.today():
                    raise ValueError(dated)
            except ValueError:
                problems.append(f"{rel}: {floor_name}'s date {dated!r} is not a past ISO date")
            mark = high_water.get((rel, ceiling))
            if mark is None:
                problems.append(
                    f"{rel}: {ceiling} has no high-water mark: enrol ({rel!r}, {ceiling!r}) at its value "
                    "in tests/test_proof_tier.py::_WALL_CLOCK_HIGH_WATER in the same commit"
                )
            elif ceiling_ms is not None and ceiling_ms < mark:
                problems.append(
                    f"{rel}: {ceiling} = {ceiling_ms:g} ms is under its high-water mark of {mark:g} ms -- a "
                    "ceiling never drops because a floor read lower on a faster host; lower the mark only "
                    "with the reason in the commit"
                )
    for key in sorted(set(high_water) - paired):
        problems.append(f"{key[0]}: a high-water mark for {key[1]}, which no {_WALL_CLOCK_PAIRING} pairs")
    return WallClockReading(seen, problems, frozenset(exemptions))


def _unlisted_wall_clock_files(paths: list[Path], listed: set[str]) -> list[str]:
    """The modules among `paths` that carry a bound site and are not in the
    serial list -- the text scan is the cheap pre-filter, the AST walk the
    confirmation."""
    pat = re.compile(r"\bsetitimer\(|\bperf_counter\b|\bmonotonic\b|\btime\.time\(")
    offenders = []
    for path in paths:
        if f"tests/{path.name}" in listed:
            continue
        text = path.read_text(encoding="utf-8")
        if pat.search(text) and _bound_sites(ast.parse(text)):
            offenders.append(path.name)
    return offenders


class TestTheWallClockRule:
    """The derived rule, and its own must-trip rows: a contract that has never
    redded proves nothing (`docs/STANDING_PRINCIPLES.md` §7)."""

    @staticmethod
    def _live(pt) -> WallClockReading:
        files = [(rel, (REPO_ROOT / rel).read_text(encoding="utf-8")) for rel in pt.WALL_CLOCK_SERIAL_FILES]
        return wall_clock_violations(files, _WALL_CLOCK_HIGH_WATER)

    def test_every_wall_clock_ceiling_is_ten_times_a_dated_floor(self, pt):
        """Over `WALL_CLOCK_SERIAL_FILES`, read not copied. The population
        floor is asserted FIRST: a scan that found nothing would otherwise
        read as clean."""
        reading = self._live(pt)
        assert reading.sites >= _WALL_CLOCK_SITE_FLOOR, (
            f"only {reading.sites} bound sites across {pt.WALL_CLOCK_SERIAL_FILES}: the scan is broken, "
            f"not the files clean (the floor is {_WALL_CLOCK_SITE_FLOOR})"
        )
        assert not reading.problems, "\n".join(reading.problems)

    def test_the_site_floor_tracks_the_population(self, pt):
        """A floor validated only at the population's size it was set at goes
        stale silently (docs/FAILURE_MODES.md §13.21): under half or over
        twice the pin, re-pin `_WALL_CLOCK_SITES_AT_PIN` with the date."""
        sites = self._live(pt).sites
        assert _WALL_CLOCK_SITE_FLOOR <= sites <= 2 * _WALL_CLOCK_SITES_AT_PIN, (sites, _WALL_CLOCK_SITES_AT_PIN)

    def test_the_exemption_census_is_exact(self, pt):
        """Every `wall-clock-exempt` marker in the serial files, by file and
        enclosing row, equals the enrolled set: a new marker reds here until it
        is enrolled with its row, and a retired one until it is struck."""
        assert self._live(pt).exemptions == _WALL_CLOCK_EXEMPTIONS

    # One file with one row, one helper and one pairing, green as written;
    # each row below breaks exactly one thing and names the sentence the rule
    # must answer with.
    _GREEN = (
        "import signal, time\n"
        "_FLOOR_MS = 30\n"
        "_CEILING_MS = 10 * _FLOOR_MS\n"
        '_WALL_CLOCK_FLOORS = {"_CEILING_MS": ("_FLOOR_MS", "2026-09-24", 30)}\n'
        "def _under(fn, budget_s):\n"
        "    signal.setitimer(signal.ITIMER_REAL, budget_s)\n"
        "    t = time.time(); fn(); elapsed_ms = (time.time() - t) * 1000\n"
        "    signal.setitimer(signal.ITIMER_REAL, 0)\n"
        "    assert elapsed_ms < budget_s * 1000\n"
        "def test_row():\n"
        "    signal.setitimer(signal.ITIMER_REAL, _CEILING_MS / 1000.0)\n"
        "    t = time.time(); elapsed_ms = (time.time() - t) * 1000\n"
        "    signal.setitimer(signal.ITIMER_REAL, 0)\n"
        "    assert elapsed_ms < _CEILING_MS\n"
        "def test_helper_row():\n"
        "    _under(lambda: None, _CEILING_MS / 1000.0)\n"
    )
    _MARKS = {("t.py", "_CEILING_MS"): 300.0}

    def _read(self, text: str, marks=None) -> WallClockReading:
        return wall_clock_violations([("t.py", text)], self._MARKS if marks is None else marks)

    def test_the_green_snippet_reads_green_and_counts_every_site(self):
        reading = self._read(self._GREEN)
        assert reading.problems == []
        assert reading.sites == 4, reading.sites  # an arm and a compare in the row, an arm and a compare in the helper
        assert reading.exemptions == frozenset()

    @pytest.mark.parametrize("label, old, new, expect", [
        ("a literal timer arm", "_CEILING_MS / 1000.0)\n    t = time.time(); elapsed_ms",
         "1.0)\n    t = time.time(); elapsed_ms", "is a literal, not a named ceiling"),
        ("a literal elapsed bound", "assert elapsed_ms < _CEILING_MS\n", "assert elapsed_ms < 1000\n",
         "is a literal, not a named ceiling"),
        ("a literal bound on a timed local not named elapsed",
         "t = time.time(); elapsed_ms = (time.time() - t) * 1000\n    signal.setitimer(signal.ITIMER_REAL, 0)\n    assert elapsed_ms < _CEILING_MS\n",
         "t = time.time(); took_ms = (time.time() - t) * 1000\n    signal.setitimer(signal.ITIMER_REAL, 0)\n    assert took_ms < 1000\n",
         "is a literal, not a named ceiling"),
        ("a literal bound on the clock difference itself",
         "assert elapsed_ms < _CEILING_MS\n", "assert (time.time() - t) * 1000 < 1000\n",
         "is a literal, not a named ceiling"),
        ("a bare-imported setitimer with a literal",
         "import signal, time\n", "import signal, time\nfrom signal import setitimer\ndef test_bare():\n    setitimer(signal.ITIMER_REAL, 2.0)\n",
         "is a literal, not a named ceiling"),
        ("a ceiling the pairing does not list", '{"_CEILING_MS": ("_FLOOR_MS", "2026-09-24", 30)}', "{}",
         "is not paired with a floor"),
        ("a paired ceiling no row asserts", '{"_CEILING_MS": ("_FLOOR_MS", "2026-09-24", 30)}',
         '{"_CEILING_MS": ("_FLOOR_MS", "2026-09-24", 30), "_FLOOR_MS": ("_FLOOR_MS", "2026-09-24", 30)}',
         "no timer or comparison asserts it"),
        ("a ceiling under ten times its floor", "_CEILING_MS = 10 * _FLOOR_MS", "_CEILING_MS = 3 * _FLOOR_MS",
         "is under 10 x _FLOOR_MS"),
        ("a floor edited without its pairing", "_FLOOR_MS = 30\n", "_FLOOR_MS = 40\n",
         "the pairing records 30 ms"),
        ("a floor without an ISO date", '"2026-09-24"', '"yesterday"', "is not a past ISO date"),
        ("a floor dated in the future", '"2026-09-24"', '"2099-01-01"', "is not a past ISO date"),
        ("a floor that is not a number", "_FLOOR_MS = 30\n", '_FLOOR_MS = "thirty"\n', "does not resolve to a number"),
        ("a helper call site passing a literal", "_under(lambda: None, _CEILING_MS / 1000.0)",
         "_under(lambda: None, 1.0)", "passes the literal"),
        ("an opt-out without a reason", "_CEILING_MS / 1000.0)\n    t = time.time(); elapsed_ms",
         "1.0)  # wall-clock-exempt:\n    t = time.time(); elapsed_ms", "without a reason"),
        ("a file with sites and no pairing", '_WALL_CLOCK_FLOORS = {"_CEILING_MS": ("_FLOOR_MS", "2026-09-24", 30)}\n', "",
         "no _WALL_CLOCK_FLOORS pairing"),
    ])
    def test_the_rule_reds_on(self, label, old, new, expect):
        assert old in self._GREEN, label
        reading = self._read(self._GREEN.replace(old, new))
        assert any(expect in p for p in reading.problems), (label, reading.problems)

    def test_the_rule_reds_on_a_ceiling_under_its_high_water_mark(self):
        reading = self._read(self._GREEN, {("t.py", "_CEILING_MS"): 600.0})
        assert any("under its high-water mark" in p for p in reading.problems), reading.problems

    def test_the_rule_reds_on_a_ceiling_with_no_high_water_mark(self):
        reading = self._read(self._GREEN, {})
        assert any("has no high-water mark" in p for p in reading.problems), reading.problems

    def test_the_rule_reds_on_a_high_water_mark_nothing_pairs(self):
        reading = self._read(self._GREEN, {**self._MARKS, ("t.py", "_GONE_MS"): 100.0})
        assert any("which no _WALL_CLOCK_FLOORS pairs" in p for p in reading.problems), reading.problems

    def test_an_opt_out_with_a_reason_excuses_a_literal_witness(self):
        """The must-trip witness shape: the alarm firing IS the pass, so its
        bound is deliberately under the floor and says why on its line; the
        reading names the row so the census can pin it."""
        old = "_CEILING_MS / 1000.0)\n    t = time.time(); elapsed_ms"
        new = "0.5)  # wall-clock-exempt: must-trip witness, the alarm firing is the pass\n    t = time.time(); elapsed_ms"
        reading = self._read(self._GREEN.replace(old, new))
        assert reading.problems == [], reading.problems
        assert reading.exemptions == frozenset({("t.py", "test_row")})

    @pytest.mark.parametrize("label, extra", [
        ("a liveness floor against zero", "def test_alive():\n    t = time.time(); elapsed_ms = (time.time() - t) * 1000\n    assert elapsed_ms > 0\n"),
        ("a spinner comparing two clock readings", "def spin():\n    end = time.perf_counter() + 0.01\n    while time.perf_counter() < end:\n        pass\n"),
        ("a helper's result compared against a sample floor", "def judge():\n    t_small = _under(lambda: None, _CEILING_MS / 1000.0)\n    assert t_small is None or t_small < 5.0\n"),
        ("a lower bound on how long a lock blocked", "def test_blocks():\n    t0 = time.monotonic(); elapsed = time.monotonic() - t0\n    assert elapsed >= 0.05\n"),
        ("an identity test on a timed local", "def best_of():\n    best = None\n    t = time.time(); elapsed_ms = (time.time() - t) * 1000\n    best = elapsed_ms if best is None else min(best, elapsed_ms)\n    return best\n"),
    ])
    def test_the_rule_stays_quiet_on(self, label, extra):
        reading = self._read(self._GREEN + extra)
        assert reading.problems == [], (label, reading.problems)


class TestRun:
    """``--run`` is one command with one receipt: every command runs, each gets
    an exit line, the summary names how many ran, and the worst code is the
    exit. The subprocess is faked so no pytest is spawned from inside pytest."""

    def _fake_run(self, monkeypatch, pt, codes):
        """Fake only the pytest spawns; the script's own `git status` call goes
        through to the real runner (pt.subprocess IS the stdlib module)."""
        calls = []
        real = subprocess.run
        def fake(argv, **kw):
            if list(argv)[:1] not in (["pytest"], ["mypy"]):
                return real(argv, **kw)
            calls.append(list(argv))
            return types.SimpleNamespace(returncode=codes[len(calls) - 1])
        monkeypatch.setattr(pt.subprocess, "run", fake)
        return calls

    def test_a_forced_downgrade_is_named_beside_the_receipt(self, pt, monkeypatch, tmp_path, capsys):
        """`--tier contract` on a runtime diff prints the forced note at the top
        and, four lines later, a receipt that would otherwise read as the earned
        run; the note is repeated beside the verdict. The upgrade twin
        (`--tier full` on a docs diff) is pinned separately."""
        r = _repo(tmp_path)
        (r / "tools" / "cc" / "hooks" / "h.py").write_text("y\n", encoding="utf-8")
        self._fake_run(monkeypatch, pt, [0])
        assert pt.main(["--root", str(r), "--tier", "contract", "--run"]) == 0
        out = capsys.readouterr().out
        assert "contract (forced; the diff earned full)" in out
        assert "forced: ran the contract tier; the diff earned full" in out
        assert out.index("1 of 1 command(s) ran") < out.index("forced: ran the contract tier")

    def test_an_earned_run_carries_no_forced_note(self, pt, monkeypatch, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        self._fake_run(monkeypatch, pt, [0])
        assert pt.main(["--root", str(r), "--run"]) == 0
        assert "forced" not in capsys.readouterr().out

    def test_every_command_runs_and_the_worst_exit_wins(self, pt, monkeypatch, capsys):
        calls = self._fake_run(monkeypatch, pt, [0, 3, 0])
        assert pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT) == 3
        assert calls == [list(argv) for argv in pt._TIER_ARGVS["full"]]
        out = capsys.readouterr().out
        exit_lines = [line for line in out.splitlines() if line.startswith("exit ")]
        assert len(exit_lines) == 3 and "3 of 3 command(s) ran" in out and "FAIL (worst exit 3)" in out

    def test_run_spawns_the_head_it_prints(self, pt, monkeypatch, capsys):
        """The receipt line and the spawned binary are the same token: a mypy
        entry spawns mypy, a pytest entry spawns pytest."""
        calls = self._fake_run(monkeypatch, pt, [0, 0, 0])
        pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT)
        assert [c[0] for c in calls] == [argv[0] for argv in pt._TIER_ARGVS["full"]] == ["mypy", "pytest", "pytest"]
        out = capsys.readouterr().out
        assert "exit 0: mypy tools/cc/hooks/" in out

    def test_a_missing_runner_is_a_loud_exit_127_with_the_install_hint(self, pt, monkeypatch, capsys):
        real = subprocess.run
        def fake(argv, **kw):
            if list(argv)[:1] == ["mypy"]:
                raise FileNotFoundError("mypy")
            if list(argv)[:1] == ["pytest"]:
                return types.SimpleNamespace(returncode=0)
            return real(argv, **kw)
        monkeypatch.setattr(pt.subprocess, "run", fake)
        assert pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT) == 127
        out = capsys.readouterr().out
        assert "exit 127: mypy tools/cc/hooks/" in out and pt.INSTALL_HINT in out and "3 of 3" in out

    def test_a_forced_full_tier_on_a_docs_only_tree_says_so_and_runs_both(self, pt, tmp_path, monkeypatch, capsys):
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        calls = self._fake_run(monkeypatch, pt, [0, 0, 0])
        assert pt.main(["--root", str(r), "--tier", "full", "--run"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("full (forced; the diff earned contract)") and pt.INSTALL_HINT in out
        assert len(calls) == 3 and "PASS -- 3 of 3" in out

    def test_run_refuses_while_a_file_is_untracked(self, pt, tmp_path, monkeypatch, capsys):
        r = _repo(tmp_path)
        (r / "scripts" / "new.py").write_text("x\n", encoding="utf-8")
        calls = self._fake_run(monkeypatch, pt, [0, 0])
        assert pt.main(["--root", str(r), "--run"]) == 2
        assert calls == [] and "git add -N scripts/new.py" in capsys.readouterr().out

    def test_a_command_not_led_by_a_known_runner_is_refused(self, pt):
        with pytest.raises(ValueError):
            pt.run_commands((("rm", "-rf", "x"),), REPO_ROOT)
