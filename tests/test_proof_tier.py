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
import os
import re
import shlex
import subprocess
import sys
import types
from pathlib import Path
from typing import Iterable, NamedTuple

import pytest
from tests._live_tree import checkout_glob

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
        ride = shlex.join(("pytest", "-q", *pt._PARALLEL, *pt._NOT_HEAVY, "tests/test_x.py"))
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
        # The tier opens with the contract tier's lines, byte for byte; the
        # nudge is what stops a partial paste reading as the tier.
        assert f"all {len(pt.RECALL_COMMANDS)} lines are the tier" in out

    def test_a_docs_change_prints_the_nudge_naming_every_line(self, pt, tmp_path, capsys):
        """The contract tier was one line and printed no nudge; with the lint
        line it was two, and three since its serial files' contract rows left
        for a line of their own (DEF-5044): a paste of one pytest line alone
        would skip the rest, so the nudge names them all."""
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        pt.main(["--root", str(r)])
        assert f"all {len(pt.CONTRACT_COMMANDS)} lines are the tier" in capsys.readouterr().out

    def test_the_one_line_serial_leg_prints_no_nudge(self, pt, tmp_path, capsys):
        """The negative the lint line retired from the contract tier, kept on
        the one tier-leg that is still a single line: the full tier's serial
        leg, which the five test-serial cells run."""
        r = _repo(tmp_path)
        (r / "tools" / "cc" / "hooks" / "h.py").write_text("y\n", encoding="utf-8")
        pt.main(["--root", str(r), "--tier", "full", "--leg", "serial"])
        out = capsys.readouterr().out
        assert out.count("run: ") == 1 and "lines are" not in out

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
        assert "run: pytest -q -n auto -m 'not heavy_e2e' tests/test_x.py" in out

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
    """The full tier is the parallel run minus the serial files, then those
    files serially. Each reason's list has one home (the three tuples
    ``SERIAL_FILES`` joins); every member must exist, none is listed twice,
    and the two lines must agree on them."""

    def test_every_serial_file_exists(self, pt):
        for rel in pt.SERIAL_FILES:
            assert (REPO_ROOT / rel).is_file(), rel

    def test_every_serial_list_joins_serial_files(self, pt):
        """A reason's list that never joins ``SERIAL_FILES`` keeps its files on
        the parallel leg while every line-level pin reads green."""
        lists = [name for name in vars(pt) if name.endswith("_SERIAL_FILES")]
        assert len(lists) >= 3, lists
        assert set(pt.SERIAL_FILES) == {rel for name in lists for rel in getattr(pt, name)}, lists

    def test_the_full_tier_runs_the_hook_type_gate_first_and_the_contract_tier_never(self, pt):
        """The near-strict mypy gate lived only in CI from 2026-07-23 and went red
        unread twice; the full tier runs it first, on exactly the diffs that
        can break it."""
        assert pt.FULL_COMMANDS[0] == "mypy tools/cc/hooks/"
        assert not any(c.startswith("mypy") for c in pt.CONTRACT_COMMANDS)

    def test_every_tier_lints_right_after_its_type_gate(self, pt):
        """A lane's execution commit landed five F401/F811 errors past a green
        full tier on 2026-10-01: no tier ran ruff, and CI's ruff-lint cell is not
        a required check, so auto-merge waited on nothing that saw the red. The
        lint line leads every tier below the type gate, so the lane's own receipt
        is the catch, and the cheapest tier catches it too."""
        assert pt.FULL_COMMANDS[1] == "ruff check ."
        assert pt.RECALL_COMMANDS[0] == "ruff check ."
        assert pt.CONTRACT_COMMANDS[0] == "ruff check ."
        for tier in pt.TIERS:
            assert pt.commands(tier).count("ruff check .") == 1, tier
        # The lint line rides the parallel leg: the serial leg is the one
        # wall-clock line, and a cheaper tier has no serial leg at all.
        assert "ruff check ." in pt.commands("full", leg="parallel")
        assert "ruff check ." not in pt.commands("full", leg="serial")

    def test_the_module_docstring_counts_each_tiers_commands(self, pt):
        """The docstring says how many commands each tier runs, and the contract
        tier's count went stale the day a line joined it (DEF-5044): read
        against the tier table here, not kept by hand twice."""
        words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
        doc = " ".join((pt.__doc__ or "").split())
        m = re.search(r"The full tier is (\w+) commands, the recall tier (\w+) and the contract tier (\w+)", doc)
        assert m, "the module docstring no longer counts each tier's commands"
        assert [words.get(w) for w in m.groups()] == [len(pt.tier_argvs(t)) for t in ("full", "recall", "contract")]

    def test_the_parallel_line_leaves_out_exactly_the_files_the_serial_line_runs(self, pt):
        parallel, serial = [c for c in pt.FULL_COMMANDS if c.startswith("pytest ")]
        assert " -n auto " in parallel and " -n 1 " in serial
        ignored = sorted(tok[len("--ignore="):] for tok in parallel.split() if tok.startswith("--ignore="))
        assert ignored == sorted(pt.SERIAL_FILES)
        assert sorted(tok for tok in serial.split() if tok.startswith("tests/")) == sorted(pt.SERIAL_FILES)
        assert len(pt.SERIAL_FILES) == len(set(pt.SERIAL_FILES)), pt.SERIAL_FILES

    def test_every_pytest_line_runs_under_xdist(self, pt):
        """DEF-2017: where pytest-timeout uses its thread method (Windows, a
        seat's own box), a plain session that crosses the per-test ceiling ends
        with no summary and no test named; under xdist the test fails by name and
        the run reports the rest. Every pytest line of every tier, the own-tests
        lines included, carries ``-n``: one worker for a line of serial files
        only, ``-n auto`` for every other. A line that names no file collects
        the tree, so its file tokens say nothing about the serial files it
        runs: ``TestNoParallelLineCollectsASerialFile`` drives that (DEF-5044)."""
        changed = ["tests/test_final_release_matrix.py", "tests/test_hooks.py"]
        lines = [argv for which in pt.TIERS for argv in pt.tier_argvs(which, changed, REPO_ROOT)
                 if argv[0] == "pytest"]
        assert len(lines) >= 11, lines   # full's two; contract's two and recall's three, each with two own lines
        for argv in lines:
            assert "-n" in argv, argv
            workers = argv[argv.index("-n") + 1]
            files = [tok for tok in argv if tok.startswith("tests/")]
            if any(rel in pt.SERIAL_FILES for rel in files):
                # A serial file never rides a parallel line, whatever it shares it with.
                assert all(rel in pt.SERIAL_FILES for rel in files) and workers == "1", argv
            else:
                assert workers == "auto", argv

    def test_every_timeout_near_gate_is_in_the_slow_lane(self, pt):
        """The serial-leg pin is for the parallel FULL tier; the `not slow`
        slice must already leave these out, or a cheaper run inherits the
        worker crash the pin exists to prevent."""
        from tests.conftest import _SLOW_FILES
        for rel in pt.TIMEOUT_NEAR_SERIAL_FILES:
            assert Path(rel).stem in _SLOW_FILES, rel

    def test_the_contract_tier_is_the_lint_then_the_two_contract_lines(self, pt):
        """A bare ``-m contract`` over the tree less the serial files it would
        collect a row of, then those at one worker (DEF-5044): the own line
        leaves contract-classified files off because these lines run every row
        of them (DEF-4089), so a ``-k`` or a narrower ``-m`` added here changes
        what the cheaper tiers run."""
        held = pt.SERIAL_CONTRACT_FILES
        assert held, "no serial file holds a contract row: the second line goes, and this pin says so"
        assert pt.commands("contract") == (
            "ruff check .",
            "pytest -n auto -m contract -q " + " ".join(f"--ignore={rel}" for rel in held),
            "pytest -n 1 -m contract -q " + " ".join(held),
        )

    def test_the_recall_tier_is_the_contract_slice_then_the_recall_files(self, pt):
        """The slice line is bare, so its files leave the own line (DEF-4089,
        ``_runs_whole``); a selection added to it puts them back there."""
        assert pt.commands("recall") == (
            "ruff check .",
            *pt.commands("contract")[1:],
            "pytest -q -n auto " + " ".join(pt.RECALL_SLICE_FILES),
        )
        assert not any(c.startswith("mypy") for c in pt.RECALL_COMMANDS)

    def test_a_changed_scripts_own_test_file_rides_along_on_the_cheaper_tiers(self, pt, tmp_path):
        """`tests/test_ledger_row.py` is integration-classified, so the contract
        tier collected none of the rows written for the row tool's 2026-09-20
        fix (failure-mode pass; DEF-775's shape one directory over). Derived
        from the diff, never enumerated: a changed `scripts/<stem>.py` brings
        `tests/test_<stem>.py` when it exists, on the two cheaper tiers; the
        full tier already runs it, so nothing is appended there. Earn-the-red:
        the function did not exist before this test. Since 2026-09-25 a changed
        test file rides along the same way. Pinned on a scratch tree whose test
        files name no path: in this checkout the files that name a changed path
        ride behind the own file (``path_readers``, DEF-5042), this module among
        them, since it names each path it asks about."""
        assert pt.own_tests(["scripts/ledger_row.py"], REPO_ROOT)[0] == "tests/test_ledger_row.py"
        r = _repo(tmp_path)
        (r / "tests" / "test_s.py").write_text("def test_s():\n    pass\n", encoding="utf-8")
        changed = ["scripts/s.py", "scripts/no_such_script.py", "docs/X.md", "tests/test_x.py", "scripts/s.py"]
        assert pt.own_tests(changed, r) == ("tests/test_s.py", "tests/test_x.py")
        assert pt.commands("contract", changed, r) == (
            *pt.CONTRACT_COMMANDS,
            "pytest -q -n auto -m 'not heavy_e2e' tests/test_s.py tests/test_x.py")
        assert pt.commands("recall", changed, r) == (
            *pt.RECALL_COMMANDS, "pytest -q -n auto -m 'not heavy_e2e' tests/test_s.py tests/test_x.py")
        assert pt.commands("full", changed, r) == pt.FULL_COMMANDS
        # the tier-only spelling the bodies cite: the lint line, then the slice
        # (its lines are pinned in test_the_contract_tier_is_the_lint_then_the_two_contract_lines)
        assert pt.commands("contract") == pt.CONTRACT_COMMANDS
        assert pt.own_tests(["scripts/nested/x.py", "tests/nested/test_y.py"], r) == ()
        assert pt.own_tests(["tests/test_s.py"], r) == ("tests/test_s.py",)

    def test_a_changed_body_brings_the_tests_that_drive_the_bodies(self, pt):
        """DEF-4067: a diff that edits only an agent, command or skill body
        earns the contract tier, whose ``-m contract`` deselects every row of
        tests/test_first_contact_diagnostics.py (integration-classified), so the
        first-contact diagnostics could regress with every pull-request cell
        green and the red arrived on ``main``. A changed body, in this checkout
        or in the deploy source ``espalier init`` copies into the adopter tree
        that file builds, now brings the file on the two cheaper tiers; a path
        beside a body (a skill's other file, a nested agent, a workflow, the
        dogfooding mirror the file never opens) does not bring it. The test
        files that name a changed path ride behind it (``path_readers``,
        DEF-5040), so each row reads the roster's file, not the whole line."""
        diagnostics = "tests/test_first_contact_diagnostics.py"
        for body in (".claude/agents/repo-analyst.md", ".claude/commands/handoff.md",
                     ".claude/skills/analyze/SKILL.md", "espalier/assets/claude/agents/repo-analyst.md",
                     ".claude\\agents\\code-reviewer.md"):
            assert pt.own_tests([body], REPO_ROOT)[0] == diagnostics, body
        for beside in (".claude/skills/analyze/notes.md", ".claude/agents/nested/x.md",
                       ".claude/workflows/fanout-audit.js", ".claude/CLAUDE.md", ".claude/settings.json",
                       "examples/dogfooding/.claude/agents/repo-analyst.md", "docs/.claude/agents/x.md",
                       ".claude/skills/SKILL.md", ".claude/skills/a/b/SKILL.md", ".claude/skills//SKILL.md",
                       ".claude/agents//x.md"):
            # beside a body the roster does not come: the line is the path's own
            # readers alone (the dogfooding mirror's tail is the source body's
            # path, so the files that name that path come by name)
            assert not pt.is_body(beside), beside
            assert pt.own_tests([beside], REPO_ROOT) == tuple(
                t for t in pt.path_readers([beside], REPO_ROOT) if not _contract_classified(t)), beside
        changed = [".claude/agents/repo-analyst.md", "espalier/assets/claude/agents/repo-analyst.md",
                   "scripts/ledger_row.py", diagnostics]
        readers = [t for t in pt.path_readers(changed, REPO_ROOT) if not _contract_classified(t)]
        assert pt.own_tests(changed, REPO_ROOT) == tuple(
            dict.fromkeys((diagnostics, "tests/test_ledger_row.py", *readers)))
        own = pt.own_tests([".claude/agents/repo-analyst.md"], REPO_ROOT)
        assert own[0] == diagnostics and not set(own) & set(pt.SERIAL_FILES), own
        assert pt.commands("contract", [".claude/agents/repo-analyst.md"], REPO_ROOT) == (
            *pt.CONTRACT_COMMANDS,
            shlex.join(("pytest", "-q", *pt._PARALLEL, *pt._NOT_HEAVY, *own)))
        assert pt.commands("full", [".claude/agents/repo-analyst.md"], REPO_ROOT) == pt.FULL_COMMANDS

    def test_the_body_roster_is_the_walk_the_diagnostics_read(self, pt):
        """Hand-kept like ``SERIAL_FILES`` and pinned the same way: the kinds
        ``own_tests`` maps are the module's own walk, every body that walk
        reads in this checkout (and its deploy-source twin) brings the module,
        and every body the module names by constant, or reads through its fence
        walk, is one of them (a walk that bypassed ``BODY_KINDS`` read nested
        agents the roster leaves out: failure-mode review)."""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        try:
            import test_first_contact_diagnostics as fcd
        finally:
            sys.path.remove(str(REPO_ROOT / "tests"))
        rel = "tests/test_first_contact_diagnostics.py"
        assert pt.BODY_TEST_FILES == (rel,) and (REPO_ROOT / rel).is_file()
        assert pt.BODY_KINDS == fcd.BODY_KINDS
        walked = [b.relative_to(REPO_ROOT).as_posix() for b in fcd._shipped_bodies()]
        assert walked, "the module's walk read no body"
        named = {fcd.ANALYZE, fcd.TEST_WRITER, fcd.ADVISOR, fcd.REPO_ANALYST, fcd.CODE_REVIEWER,
                 *(body for body, _heading, _header in fcd.COVERAGE_FENCES)}
        assert named <= set(walked), named - set(walked)
        fenced = {body for body, _fence in fcd._walk_fences(REPO_ROOT)}
        assert fenced and fenced <= set(walked), fenced - set(walked)
        for body in walked:
            assert pt.own_tests([body], REPO_ROOT)[0] == rel, body
            twin = "espalier/assets/claude/" + body[len(".claude/"):]
            assert (REPO_ROOT / twin).is_file(), twin
            assert pt.own_tests([twin], REPO_ROOT)[0] == rel, twin

    def test_the_contract_tiers_body_line_collects_the_diagnostics(self, pt):
        """Driven, not read: the line a body-only diff adds to the contract tier
        collects every row the diagnostics module holds, where the tier's
        ``-m contract`` line collects none of them (the gap DEF-4067 names)."""
        rel = "tests/test_first_contact_diagnostics.py"
        line = pt.tier_argvs("contract", [".claude/agents/repo-analyst.md"], REPO_ROOT)[-1]
        assert rel in line and "contract" not in line
        marks = line[line.index("-m"):line.index("-m") + 2]

        def collected(extra: tuple[str, ...]) -> int:
            argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra, rel]
            out = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8").stdout
            return sum(1 for row in out.splitlines() if row.startswith(rel + "::"))

        every = collected(())
        assert every, "the diagnostics module collected no row at all"
        assert collected(marks) == every
        assert collected(pt._CONTRACT_ARGV[pt._CONTRACT_ARGV.index("-m"):][:2]) == 0

    #: The five readers DEF-4067's census found, each reading one named body
    #: by a literal or a join the contract tier never collected (DEF-5040).
    _ONE_BODY_READERS: tuple[tuple[str, str], ...] = (
        (".claude/commands/inbox.md", "tests/test_mail.py"),
        (".claude/skills/hook-authoring/SKILL.md", "tests/test_hook_authoring_skill_parity.py"),
        (".claude/skills/reflect/SKILL.md", "tests/test_reflect_memory_candidates.py"),
        (".claude/commands/smoke.md", "tests/test_adopter_lifecycle_diagnostics.py"),
        (".claude/commands/preflight.md", "tests/test_node_adopter_defaults.py"),
        # the failure-mode review's: a path constant imported from a helper
        (".claude/commands/recall.md", "tests/test_recall_pasted_counts.py"),
    )

    def test_a_changed_body_brings_every_test_file_that_names_it(self, pt):
        """DEF-5040: a diff that edits one body earned the contract tier, whose
        ``-m contract`` deselected every row of the five files that read that
        body's text, so their reds arrived on ``main`` after the merge. Each
        now rides the cheaper tiers' own line, read from the test files: a
        literal, a join from the repository root, and a join on a tree
        ``espalier init`` built (the preflight reader). Earn-the-red: none
        of the five came back before ``path_readers`` existed."""
        for body, reader in self._ONE_BODY_READERS:
            assert reader in pt.own_tests([body], REPO_ROOT), (
                f"{reader} no longer names {body} by a shape _module_names reads -- "
                f"teach it the new shape rather than drop the pair")
            assert reader in pt.path_readers([body], REPO_ROOT), body
            line = pt.tier_argvs("contract", [body], REPO_ROOT)[-1]
            assert reader in line and "contract" not in line, line
            assert pt.commands("full", [body], REPO_ROOT) == pt.FULL_COMMANDS

    def test_a_name_is_a_literal_or_the_end_of_a_join(self, pt, tmp_path):
        """The shapes ``_module_names`` reads, on a scratch tree, each beside
        the near miss that must not count: prose that mentions the path, a
        longer path, a bare file name, a name built at run time, a module
        below ``tests/`` or a helper, a module that does not parse. Every
        changed path is looked up as it is, a body or not, a doc or a note
        outside ``BODY_ROOTS`` included (DEF-5042; DEF-5040's map read those
        roots alone, request 4ccfb9)."""
        tests = tmp_path / "tests"
        (tests / "sub").mkdir(parents=True)
        reads = {
            "test_literal.py": 'X = ".claude/commands/x.md"\nD = "docs/x.md"\n',
            "test_join.py": 'P = ROOT / ".claude" / "commands" / "x.md"\n',
            "test_path_call.py": 'from pathlib import Path\nP = Path(".claude") / "commands" / "x.md"\n',
            "test_suffix.py": 'P = claude_dir / "commands" / "x.md"\n',
            "test_windows.py": 'X = ".claude\\\\commands\\\\x.md"\n',
            "test_asset.py": 'X = "espalier/assets/claude/commands/x.md"\n',
            "test_notes.py": 'X = ".claude/skills/a/notes.md"\n',
            "test_path_args.py": 'P = Path(ROOT, ".claude", "commands", "x.md")\n',
            "test_joinpath.py": 'P = ROOT.joinpath(".claude", "commands", "x.md")\n',
            "test_os_join.py": 'import os\nP = os.path.join(ROOT, ".claude", "commands", "x.md")\n',
            "test_helper_reader.py": 'from tests._paths import BODY\n',
            "test_helper_other.py": 'from tests._paths import OTHER\n',
            "_paths.py": 'BODY = ROOT / ".claude" / "commands" / "x.md"\nOTHER = "docs/y.md"\n',
        }
        misses = {
            "test_prose.py": '"""Edit .claude/commands/x.md first."""\nM = "see .claude/commands/x.md"\n',
            "test_longer.py": 'X = ".claude/commands/x.md.bak"\n',
            "test_bare.py": 'X = "x.md"\n',
            "test_fstring.py": 'X = f".claude/commands/{name}"\n',
            "test_broken.py": 'X = ".claude/commands/x.md"\ndef (\n',
            "sub/test_nested.py": 'X = ".claude/commands/x.md"\n',
            "_helper.py": 'X = ".claude/commands/x.md"\n',
        }
        for name, text in {**reads, **misses}.items():
            (tests / name).write_text(text, encoding="utf-8")
        # PowerShell 5.1's Set-Content -Encoding UTF8 writes a BOM; Python imports it
        (tests / "test_bom.py").write_bytes(b'\xef\xbb\xbfX = ".claude/commands/x.md"\n')
        body = ".claude/commands/x.md"
        assert pt.path_readers([body], tmp_path) == tuple(
            f"tests/{n}" for n in ("test_bom.py", "test_helper_reader.py", "test_join.py", "test_joinpath.py",
                                   "test_literal.py", "test_os_join.py", "test_path_args.py",
                                   "test_path_call.py", "test_suffix.py", "test_windows.py"))
        assert pt.path_readers([".claude\\commands\\x.md"], tmp_path) == pt.path_readers([body], tmp_path)
        # a join from a directory variable may hold either tree, so it reads both
        assert pt.path_readers(["espalier/assets/claude/commands/x.md"], tmp_path) == (
            "tests/test_asset.py", "tests/test_suffix.py")
        assert not pt.is_body(".claude/skills/a/notes.md")
        assert pt.path_readers([".claude/skills/a/notes.md"], tmp_path) == ("tests/test_notes.py",)
        assert pt.path_readers(["docs/x.md"], tmp_path) == ("tests/test_literal.py",)
        assert pt.own_tests(["docs/x.md"], tmp_path) == ("tests/test_literal.py",)
        assert pt.path_readers(["docs/y.md"], tmp_path) == ("tests/test_helper_other.py",)
        assert pt.path_readers([body], tmp_path / "no-such-root") == ()

    @pytest.mark.parametrize("rel", [".claude/commands/x.md", "docs/x.md"])
    def test_a_file_a_test_only_writes_into_a_tree_is_not_read(self, pt, tmp_path, rel):
        """DEF-5042: keyed on every changed path, one ``README.md`` edit brought
        86 non-contract files, many of them only putting a file of that name
        into a tree they built. A join a module only writes to names nothing
        (``_written_joins``); each write shape sits beside the near miss that
        must still count: the same join read, a join on a scratch tree read
        back (``espalier init`` copies this checkout's files into it), a name
        written and then read, passed on or bound for another function to
        load (one bound twice and only ever written is a write), a copy's
        source, an ``os.path.join`` whose ``replace`` is the string's, and the
        module naming the path again elsewhere. Earn-the-red: on the body path
        every write shape came back before the discriminator; on the doc path
        nothing did, the map reading ``BODY_ROOTS`` alone."""
        parts = rel.split("/")
        join, args, lit = " / ".join(f'"{p}"' for p in parts), ", ".join(f'"{p}"' for p in parts), f'"{rel}"'
        writes = {
            "test_write_text.py": f"(tmp_path / {join}).write_text('x')\n",
            "test_unlink.py": f"def t(tree):\n    (tree / {lit}).unlink()\n",
            "test_bound_write.py": f"def t(tmp_path):\n    p = tmp_path / {join}\n    p.parent.mkdir()\n"
                                  "    p.write_bytes(b'')\n",
            "test_open_write.py": f"open(tmp / {join}, 'w')\nopen(tmp / {join}, mode='a')\n",
            "test_path_open_write.py": f"(tree / {join}).open('w')\n",
            "test_copy_dest.py": f"import shutil\nshutil.copy(src, tree / {join})\n",
            "test_os_join_write.py": f"import os\nopen(os.path.join(tree, {args}), 'wb')\n",
            "test_touch_chmod.py": f"Path(tree, {args}).touch()\n(tree / {join}).chmod(0o444)\n",
            "test_bound_twice.py": f"def t(a, b):\n    p = a / {join}\n    p = b / {join}\n    p.write_text('x')\n",
        }
        reads = {
            "test_read_text.py": f"(ROOT / {join}).read_text()\n",
            "test_scratch_read.py": f"def t(tmp_path):\n    (tmp_path / {join}).read_text()\n",
            "test_written_then_read.py": f"def t(tmp_path):\n    p = tmp_path / {join}\n    p.write_text('x')\n"
                                        "    assert p.read_text()\n",
            "test_passed_on.py": f"def t(tree):\n    p = tree / {join}\n    p.write_text('x')\n    check(p)\n",
            "test_global.py": f"def setup():\n    global DOC\n    DOC = ROOT / {join}\n\ndef t():\n    DOC.read_text()\n",
            "test_global_written.py": f"def setup():\n    global DOC\n    DOC = ROOT / {join}\n    DOC.touch()\n"
                                      "\ndef t():\n    DOC.read_text()\n",
            "test_copy_source.py": f"import shutil\nshutil.copy(ROOT / {join}, tree / {join})\n",
            "test_open_read.py": f"open(ROOT / {join})\n",
            "test_open_read_plus.py": f"open(ROOT / {join}, 'r+')\n",
            "test_str_replace.py": f"import os\nos.path.join(ROOT, {args}).replace('\\\\', '/')\n",
            "test_tuple.py": f"for rel in ({lit},):\n    (ROOT / rel).read_text()\n",
            "test_named_again.py": f"(tmp_path / {join}).write_text('x')\nWANT = {lit}\n",
        }
        tests = tmp_path / "tests"
        tests.mkdir()
        for name, text in {**writes, **reads}.items():
            compile(text, name, "exec")
            (tests / name).write_text(text, encoding="utf-8")
        assert pt.path_readers([rel], tmp_path) == tuple(f"tests/{n}" for n in sorted(reads))

    #: The readers DEF-5042's row names: a doc and a memory note whose phrases
    #: tests/test_mail.py asserts, read through a tuple joined onto the root.
    _DOC_READERS: tuple[tuple[str, str], ...] = (
        ("docs/WORKFLOW.md", "tests/test_mail.py"),
        ("memory/parallel-work-protocol.md", "tests/test_mail.py"),
    )

    def test_a_changed_doc_brings_every_test_file_that_reads_it(self, pt):
        """DEF-5042: a diff that edits only docs/WORKFLOW.md (the contract
        tier) or memory/parallel-work-protocol.md (the recall tier) ran no row
        of tests/test_mail.py, which asserts phrases in each, so a red there
        arrived on ``main`` after the merge. Each now rides its tier's own
        line. Earn-the-red: neither came back while the map read
        ``BODY_ROOTS`` alone (the row's probe, 0 at filing)."""
        for doc, reader in self._DOC_READERS:
            assert reader in pt.own_tests([doc], REPO_ROOT), (
                f"{reader} no longer names {doc} by a shape _module_names reads -- "
                f"teach it the new shape rather than drop the pair")
            which = pt.tier([doc])
            assert which in ("contract", "recall"), (doc, which)
            lines = pt.tier_argvs(which, [doc], REPO_ROOT)
            assert any(reader in line and "contract" not in line for line in lines), lines

    def test_a_test_module_edited_after_the_first_read_is_read_again(self, pt, tmp_path):
        """The names are cached per module (the pins above ask once per body),
        keyed on its text: the three writes below keep one size and one mtime
        (a coarse filesystem clock gives two quick writes the same tick), and
        each holds the file name, so each is parsed; a cache keyed on size and
        mtime would answer every ask from the first read."""
        tests = tmp_path / "tests"
        tests.mkdir()
        module = tests / "test_late.py"
        body = ".claude/commands/x.md"
        unnamed = 'X = "x.md"; Y = ".claude/commands/q.md"\n'
        named = 'X = "q.md"; Y = ".claude/commands/x.md"\n'
        assert len(unnamed) == len(named)
        tick = 1_700_000_000_000_000_000
        for text, want in ((unnamed, ()), (named, ("tests/test_late.py",)), (unnamed, ())):
            module.write_text(text, encoding="utf-8")
            os.utime(module, ns=(tick, tick))
            assert pt.path_readers([body], tmp_path) == want, text

    def test_a_reader_among_the_serial_files_rides_the_one_worker_line(self, pt, tmp_path):
        """A reader that is one of ``SERIAL_FILES`` keeps its measured placement
        on a cheaper tier: the one-worker line, never the parallel one."""
        serial = pt.WALL_CLOCK_SERIAL_FILES[0]
        (tmp_path / "tests").mkdir()
        (tmp_path / serial).write_text('X = ".claude/commands/x.md"\n', encoding="utf-8")
        lines = pt.tier_argvs("contract", [".claude/commands/x.md"], tmp_path)
        assert lines[-1] == pt._PYTEST + pt._ONE_WORKER + pt._NOT_HEAVY + (serial,), lines
        assert not any(serial in line for line in lines[:-1]), lines

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
        assert "run: pytest -q -n auto -m 'not heavy_e2e' tests/test_s.py" in out
        assert f"all {len(pt.CONTRACT_COMMANDS) + 1} lines are the tier" in out
        # and the argv list --run would execute carries the same line
        changed, untracked = pt.changed_paths(r)
        assert pt.tier_argvs("contract", changed + untracked, r)[-1] == ("pytest", "-q", "-n", "auto", "-m", "not heavy_e2e", "tests/test_s.py")


def _tracked_bodies(pt) -> list[str]:
    """Every tracked agent, command and skill body under the roots, read from
    the index at each call (the DEF-4089 probe's own population), with a floor."""
    from tests._git_oracle import require_tracked_paths
    tracked = require_tracked_paths(REPO_ROOT, *pt.BODY_ROOTS, minimum=50, what="paths under the body roots")
    bodies = [rel for rel in tracked if pt.is_body(rel)]
    assert len(bodies) >= 50, bodies
    return bodies


def _contract_classified(rel: str) -> bool:
    from tests.conftest import _primary_marker
    return _primary_marker(Path(rel).stem) == "contract"


#: The scratch suite the rows below ask: a contract-classified file, one that
#: shares its prefix, an integration file and an unclassified one, each naming
#: ``docs/x.md`` by a literal.
_SCRATCH_RULES = '_MARKER_RULES = [(("test_c",), "contract"), (("test_i",), "integration")]\n'
_SCRATCH_TESTS = ("test_c.py", "test_c_more.py", "test_i.py", "test_u.py")


def _scratch_suite(root: Path, conftest: str | None = _SCRATCH_RULES) -> None:
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    for name in _SCRATCH_TESTS:
        (tests / name).write_text('X = "docs/x.md"\n', encoding="utf-8")
    if conftest is not None:
        (tests / "conftest.py").write_text(conftest, encoding="utf-8")


class TestNoParallelLineCollectsASerialFile:
    """A line that names no test file collects the tree (or the directories
    it names), so its marker selection, not its file tokens, decides which
    serial files ride the ``-n auto`` pool: the contract line both cheaper
    tiers carry ran every row of the cited-pin run there, past the file-token
    pin (``test_every_pytest_line_runs_under_xdist``), until it left them out
    (DEF-5044). Driven by collection, never read from the classifier rules: a
    row can carry a marker its file's rule does not give it."""

    @staticmethod
    def _collected(marks: tuple[str, ...], serial_files: tuple[str, ...]) -> set[str]:
        """The members of ``serial_files`` the selection ``marks`` collects a
        row of. Exit 5 is a selection that kept no row; any other non-zero
        exit, or an exit 0 that printed no row, is a collection that broke,
        whose missing rows would read as absent (both reviews, DEF-5044)."""
        argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                *marks, *serial_files]
        proc = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
        rows = {row.split("::", 1)[0] for row in proc.stdout.splitlines() if "::" in row}
        assert proc.returncode in (0, 5) and (rows or proc.returncode == 5), (
            proc.returncode, (proc.stdout + proc.stderr)[-600:])
        return rows & set(serial_files)

    @classmethod
    def _on_the_pool(cls, argv: tuple[str, ...], serial_files: tuple[str, ...]) -> set[str]:
        """The serial files an ``-n auto`` line that names no test file runs on
        the pool: those under the directories it names (the tree when it names
        none) that its selection collects a row of and it does not ignore. A
        line that names a file is the file-token pin's."""
        if argv[0] != "pytest" or argv[argv.index("-n") + 1] != "auto":
            return set()
        paths = [tok for tok in argv[1:] if tok.startswith("tests")]
        if any(tok.endswith(".py") or "::" in tok for tok in paths):
            return set()
        under = tuple(rel for rel in serial_files
                      if not paths or any(rel.startswith(tok.rstrip("/") + "/") for tok in paths))
        if not under:
            return set()
        marks = tuple(tok for i in range(len(argv) - 1) if argv[i] == "-m" for tok in argv[i:i + 2])
        ignored = {tok[len("--ignore="):] for tok in argv if tok.startswith("--ignore=")}
        return cls._collected(marks, under) - ignored

    def test_no_parallel_line_that_names_no_file_collects_a_serial_file(self, pt):
        lines = {argv for which in pt.TIERS for argv in pt.tier_argvs(which)}
        for argv in lines:
            assert not self._on_the_pool(argv, pt.SERIAL_FILES), shlex.join(argv)

    def test_the_check_sees_the_bare_contract_line_and_a_directory_line(self, pt):
        """The negative twin: the contract line as it stood before DEF-5044,
        and the same selection naming the tests directory (which a file-token
        filter reads as a file), both put the cited-pin run on the pool."""
        bare = ("pytest", "-n", "auto", "-m", "contract", "-q")
        cited = set(pt.SERIAL_CONTRACT_FILES)   # a nested-run file with no contract row is not on this line
        assert self._on_the_pool(bare, pt.SERIAL_FILES) >= cited
        assert self._on_the_pool(bare + ("tests/",), pt.SERIAL_FILES) >= cited
        assert not self._on_the_pool(bare + tuple(f"--ignore={rel}" for rel in cited), pt.SERIAL_FILES) & cited

    def test_the_one_worker_contract_line_runs_exactly_the_serial_files_with_a_contract_row(self, pt):
        """Both ways: a serial file with a contract row that is not listed rides
        the pool (the pin above); a listed file with none leaves the one-worker
        line collecting nothing, which pytest exits 5 on in every cell. The line
        is there exactly while the list holds a file."""
        listed = pt.SERIAL_CONTRACT_FILES
        assert len(set(listed)) == len(listed) and set(listed) <= set(pt.SERIAL_FILES), listed
        assert self._collected(("-m", "contract"), pt.SERIAL_FILES) == set(listed)
        for which in ("contract", "recall"):
            assert (pt._CONTRACT_SERIAL_ARGV in pt.tier_argvs(which)) == bool(listed), which


class TestTheOwnLineSkipsWhatTheTierRan:
    """DEF-4089: the own line ran a file whole that another line of the same
    tier had already run whole. Both cheaper tiers carry the contract line,
    which runs every row of a contract-classified file, and the recall tier's
    slice line runs its four files with no marker filter, so the own line
    added time and no rows: 16 of the 56 files the tracked bodies' lines
    brought were contract-classified (the row's probe, 2026-11-01), and 27
    recall-tier paths brought ``tests/test_recall.py`` beside the slice that
    runs it."""

    def test_no_contract_classified_file_rides_a_bodys_own_line(self, pt):
        """The row's probe as a pin: every tracked body's own line, together,
        holds no file the conftest classifies ``contract``. Earn-the-red: 16
        at 3ad6dcb, before the skip."""
        bodies = _tracked_bodies(pt)
        own = pt.own_tests(bodies, REPO_ROOT)
        assert own, "the bodies' own line came back empty: the reader map read nothing"
        assert not [rel for rel in own if _contract_classified(rel)], own

    def test_the_walk_is_the_conftests_over_every_test_module(self, pt):
        """``primary_marker`` walks the rules the conftest's own literal holds
        and must answer as ``tests/conftest.py::_primary_marker`` does for
        every module the suite collects; a change to the conftest's matching
        reds here rather than drifting the two apart."""
        from tests.conftest import _primary_marker
        rules = pt._marker_rules(REPO_ROOT)
        assert rules, "the conftest's _MARKER_RULES did not read as a literal"
        stems = sorted(p.stem for p in checkout_glob(REPO_ROOT / "tests", "test_*.py"))
        assert len(stems) >= 400, len(stems)
        differ = [(s, pt.primary_marker(s, rules), _primary_marker(s)) for s in stems
                  if pt.primary_marker(s, rules) != _primary_marker(s)]
        assert not differ, (
            f"{differ}: scripts/proof_tier.py::primary_marker is a pytest-free copy of "
            f"tests/conftest.py::_primary_marker's walk (CI's tier job composes the own line "
            f"with no pytest installed, DEF-4089): change both the same way")
        assert {pt.primary_marker(s, rules) for s in stems} >= {"contract", "integration", "unit"}

    def test_a_contract_classified_file_is_left_off_and_the_rest_stay(self, pt, tmp_path):
        """Both directions, on a scratch suite: the contract file and its
        prefix sibling leave the line, the integration and unclassified files
        stay, whichever way the file came (a reader, a changed test file, a
        changed script's own test)."""
        _scratch_suite(tmp_path)
        (tmp_path / "scripts").mkdir()
        assert pt.own_tests(["docs/x.md"], tmp_path) == ("tests/test_i.py", "tests/test_u.py")
        assert pt.own_tests(["tests/test_c.py", "scripts/c.py"], tmp_path) == ()
        assert pt.own_tests(["tests/test_i.py"], tmp_path) == ("tests/test_i.py",)
        assert pt.commands("contract", ["docs/x.md"], tmp_path)[-1] == (
            "pytest -q -n auto -m 'not heavy_e2e' tests/test_i.py tests/test_u.py")

    @pytest.mark.parametrize("label,conftest", [
        ("no conftest", None),
        ("a conftest that does not parse", "_MARKER_RULES = [\n"),
        ("rules built at run time", "_MARKER_RULES = list(RULES)\n"),
        ("rules of another shape", '_MARKER_RULES = {"test_c": "contract"}\n'),
        ("no rules", "X = 1\n"),
        ("rules bound twice", _SCRATCH_RULES + "_MARKER_RULES = []\n"),
        ("rules extended", _SCRATCH_RULES + '_MARKER_RULES += [(("test_u",), "contract")]\n'),
        ("rules changed in place", _SCRATCH_RULES + '_MARKER_RULES.insert(0, (("test_i",), "contract"))\n'),
        ("an item set", _SCRATCH_RULES + '_MARKER_RULES[0] = (("test_u",), "contract")\n'),
    ])
    def test_rules_that_cannot_be_read_leave_nothing_off(self, pt, tmp_path, label, conftest):
        """Where the rules cannot be read the line is the one before the skip,
        never a shorter one: a file the walk cannot classify runs."""
        _scratch_suite(tmp_path, conftest)
        assert pt.own_tests(["docs/x.md"], tmp_path) == tuple(
            f"tests/{name}" for name in _SCRATCH_TESTS), label

    def test_the_line_is_composed_with_no_pytest_to_import(self, pt):
        """The CI tier job installs no pytest and composes the commands under
        ``--quiet`` too, so the rules are read from the conftest's text: a
        script that imported the conftest would answer every pull request
        ``full`` there. Driven in a child where ``import pytest`` fails."""
        code = ("import sys; sys.modules['pytest'] = None; sys.path.insert(0, 'scripts'); "
                "import proof_tier as t; "
                "print(len(t._marker_rules(t._ROOT) or ())); "
                "print(len(t.own_tests(['.claude/skills/reflect/SKILL.md'])))")
        done = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", check=False)
        assert done.returncode == 0, done.stderr
        rules, line = (int(n) for n in done.stdout.split())
        assert rules > 0 and line == len(pt.own_tests([".claude/skills/reflect/SKILL.md"], REPO_ROOT))

    def test_a_line_with_a_selection_on_it_runs_no_file_whole(self, pt, tmp_path, monkeypatch):
        """Only a bare pytest line runs its files whole: with a ``-k`` on the
        slice line its file's deselected rows would run nowhere, so the own
        line keeps it (the failure-mode review's row)."""
        slice_file = pt.RECALL_SLICE_FILES[0]
        (tmp_path / "tests").mkdir()
        (tmp_path / slice_file).write_text('X = "memory/n.md"\n', encoding="utf-8")
        narrowed = pt._TIER_ARGVS["recall"][:-1] + (
            pt._PYTEST + pt._PARALLEL + ("-k", "not floor") + pt.RECALL_SLICE_FILES,)
        monkeypatch.setitem(pt._TIER_ARGVS, "recall", narrowed)
        assert pt.tier_argvs("recall", ["memory/n.md"], tmp_path)[-1] == (
            pt._PYTEST + pt._PARALLEL + pt._NOT_HEAVY + (slice_file,))
        for argv, whole in ((pt._PYTEST + pt._PARALLEL + pt.RECALL_SLICE_FILES, True),
                            (pt._CONTRACT_ARGV, False), (pt._PYTEST + pt._ONE_WORKER + (slice_file,), False),
                            (pt._PYTEST + (f"{slice_file}::T::t",), False), (pt._RUFF_ARGV, False)):
            assert pt._runs_whole(argv) is whole, argv

    def test_a_file_the_recall_line_runs_whole_is_left_off_its_own_line(self, pt, tmp_path):
        """On the recall tier the slice line runs its files whole, so a corpus
        path's reader among them leaves the own line; the contract tier runs
        no slice, so there it stays."""
        slice_file = pt.RECALL_SLICE_FILES[0]
        (tmp_path / "tests").mkdir()
        (tmp_path / slice_file).write_text('X = "memory/n.md"\n', encoding="utf-8")
        (tmp_path / "tests" / "test_reads_n.py").write_text('X = "memory/n.md"\n', encoding="utf-8")
        assert pt.tier(["memory/n.md"]) == "recall"
        assert pt.commands("recall", ["memory/n.md"], tmp_path) == (
            *pt.RECALL_COMMANDS, "pytest -q -n auto -m 'not heavy_e2e' tests/test_reads_n.py")
        assert pt.commands("contract", ["memory/n.md"], tmp_path)[-1] == (
            "pytest -q -n auto -m 'not heavy_e2e' " + " ".join(sorted((slice_file, "tests/test_reads_n.py"))))


class TestTheOwnLineCeiling:
    """DEF-4089: nothing capped how many test files one changed body brings to
    the own line, so a census list added to a heavy test file grew every
    body's line, and the five required cells that run it, with nothing to
    decide (the reflect skill's line of 14 files: 8382 tests in 302 s on four
    workers at cfa837f, 2026-11-01, mostly tests/test_write_guard.py). The
    ceiling bounds files, not their cost."""

    def test_every_tracked_body_brings_at_most_the_ceiling(self, pt):
        bodies = _tracked_bodies(pt)
        over = {}
        for body in bodies:
            own = pt.own_tests([body], REPO_ROOT)
            if len(own) > pt.OWN_LINE_CEILING:
                over[body] = own
        assert not over, (
            f"past OWN_LINE_CEILING ({pt.OWN_LINE_CEILING}, scripts/proof_tier.py), each body's "
            f"own line: {over}. A body you did not touch counts too: a test file that names it "
            f"joins its line. {pt.OWN_LINE_REMEDY}")

    def test_the_receipt_prints_each_changed_bodys_count_beside_the_ceiling(
            self, pt, tmp_path, capsys, monkeypatch):
        r = _repo(tmp_path)
        _commit(r, ".claude/commands/x.md", "x\n", "body")
        _commit(r, "tests/test_reads_x.py", 'X = ".claude/commands/x.md"\n', "reader")
        (r / ".claude" / "commands" / "x.md").write_text("y\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        out = capsys.readouterr().out
        want = f"own line per body (ceiling {pt.OWN_LINE_CEILING}): .claude/commands/x.md 1"
        assert want in out.splitlines(), out
        assert pt.main(["--root", str(r), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["own_line_ceiling"] == pt.OWN_LINE_CEILING
        assert data["own_line_by_body"] == {".claude/commands/x.md": 1}
        monkeypatch.setattr(pt, "OWN_LINE_CEILING", 0)
        assert pt.main(["--root", str(r)]) == 0
        out = capsys.readouterr().out
        assert ".claude/commands/x.md 1 (past the ceiling" in out, out
        # the full tier runs no own line, so it prints no count
        assert pt.main(["--root", str(r), "--tier", "full"]) == 0
        assert "own line per body" not in capsys.readouterr().out


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
            p.stem for p in checkout_glob(REPO_ROOT / "tests", "test_*.py")
            if _reads_live_manifest(p.read_text(encoding="utf-8"))
        )

    def test_the_rows_this_was_written_for_are_in_the_population(self):
        # The stressor exists, for both shapes: a green below over a
        # population that lost a known member to a reworded read would be
        # silent. The first two read the path; the third calls an entry point
        # (test_scanner_freshness was that member until its live-scan test
        # moved to a copy of the surface git sees, DEF-2013 lane two, and
        # stopped reading the manifest).
        readers = self._readers()
        for stem in (
            "test_freshness_hook_count_migration",
            "test_freshness_semantic_fragments",
            "test_audit_accuracy",
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
        on_disk = sorted(f"tests/{p.name}" for p in checkout_glob(REPO_ROOT / "tests", "test_recall*.py"))
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
        # The seeded reference docs index only on an adopter's tree, so the live
        # corpus above cannot name them; an edit to either (or to the shipped copy
        # their rows read) must still earn the recall slice.
        reference = [p for rel in rc.REFERENCE_DOCS for p in (rel, f"espalier/assets/{rel}")]
        assert not [r for r in reference if not pt.is_recall_corpus(r)], reference

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
        """The build block is the one place the tier's lines are restated for
        pasting; this pins that second home to the constant -- inside the
        fenced block, because `ruff check .` also stands in the Lint section
        and a whole-file substring test was green with the paste block short."""
        text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        head, sep, rest = text.partition("\n## Build & Test\n")
        assert sep, "CLAUDE.md lost its Build & Test section"
        fence_open = rest.index("```bash\n")
        fence_close = rest.index("\n```\n", fence_open)
        block = rest[fence_open:fence_close]
        for line in pt.FULL_COMMANDS:
            assert line in block, line

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
            sorted(checkout_glob(REPO_ROOT / "tests", "*.py")), set(pt.WALL_CLOCK_SERIAL_FILES),
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


# ── the nested-run rule (DEF-2035) ────────────────────────────────────────────
#
# A test that launches a pytest child puts a second session on the box, and on
# the parallel leg that session runs beside the `-n auto` pool. The cited-pin
# run's child redded a windows-latest leg there (DEF-4062) and moved to
# `NESTED_RUN_SERIAL_FILES`; nothing caught the next one, and the axis
# registry's run of its proving nodes (64 s alone on the Windows seat,
# 2026-11-01) rode the pool until this rule. So every launch under tests/ is
# read by the AST: a `subprocess` launcher or `run_bounded` whose argv is a
# pytest command -- `-m pytest`, a bare `pytest` head, or `-c` with a program
# that calls `pytest.main`, a constant or a `dedent` of one -- spelled in the
# call, through a name bound in the function or the module, through `+` or a
# starred name. One script hop is read too (DEF-2036): a launch whose argv's
# head, or the word after an interpreter, is a path ending `scripts/<name>.py`
# (a constant, a `/` chain, `Path(...)`, `.joinpath`, an `os.path.join`, a
# `str()` of one) counts when that script launches a pytest child as this
# rule reads it (the scripts that spell pytest in a launch it cannot read are
# declared in `_SCRIPTS_THE_HOP_CANNOT_READ`, exact both ways), so
# `tests/test_verify_pins.py`'s run of `scripts/verify_pins.py` is a launch,
# and so is a run of a script whose pytest leg is off by default (the reading
# is of the script, not of the flags handed it). A launching function in a
# file on no serial list reds until it is placed: a child that runs this
# repo's rows for long, or rows that keep a budget (a hook judgment, a timed
# bound), joins `NESTED_RUN_SERIAL_FILES` (and `SERIAL_CONTRACT_FILES` when
# its file holds a contract row); one that only collects, runs a tree the
# test planted, or runs a few in-process rows for seconds is enrolled below
# with what it runs and its time alone. Not read: a second hop (a script that
# reaches pytest through another script, as `scripts/fresh_clone_gate.py`
# does), a hop script imported and its launching function called in process,
# a script launched as `-m scripts.<name>`, past interpreter flags or through
# `.as_posix()` / `os.fspath`, `os.system`, a shell string, a wrapper head
# (`bash -c`, `uv run`), an f-string program, an argv a helper returns or
# takes as a parameter, one held on a class attribute, a dict or imported,
# and one grown by `+=` or `.extend`; a launch the rule cannot see is placed
# by hand, by the same measure. An enrolment covers its function whole: a second launch
# written into it, or a new caller handing an enrolled helper `-n auto`, reads
# green. A launch in a `tests/_*.py` helper is judged where it is written, so
# place it by the files that call it, never by enrolling the helper for them.

_LAUNCHERS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
#: Launchers read by name wherever they come from (``tools/cc/_json_safe.py``'s
#: bounded spawn, which takes the argv first).
_NAMED_LAUNCHERS = frozenset({"run_bounded"})
#: The launches the scan finds at the pin, the serial files' included; the
#: floor the scan must clear before its verdict is read, as the wall-clock
#: rule's (a scan that finds a handful is broken, not looking at clean files).
_NESTED_LAUNCHES_AT_PIN = 18  # 2026-11-01: 12 enrolled below, the cited-pin run, the axis registry's two,
#                               and verify_pins's three through the script hop (DEF-2036)
_NESTED_LAUNCH_FLOOR = _NESTED_LAUNCHES_AT_PIN // 2
#: The launches whose child rides the parallel leg, EXACT: ``file::qualname``
#: -> what the child runs and how long its row took alone. An unenrolled launch
#: reds, and so does an entry whose function no longer launches (a rename
#: re-enrolls it). Timed 2026-11-01 on the Windows seat, one worker, a quiet box.
_PARALLEL_NESTED_RUNS: dict[str, str] = {
    "tests/test_benchmark_release_hygiene.py::TestResultsMdCitationsResolve::test_every_cited_node_id_collects":
        "a --collect-only child per node id the bench results cite; 1.2 s",
    "tests/test_box_lock.py::_spawn":
        "a planted one-file suite under the box lock's plugin; up to 6.0 s a row",
    "tests/test_demo_end_to_end.py::test_demo_beat3_release_check_runs":
        "scripts/release_check.py through the script hop, its pytest leg off (the test strips "
        "ESPALIER_RELEASE_CHECK_WITH_TESTS from the child's environment): no pytest child; 11.0 to 11.6 s, "
        "three runs beside another seat's tier",
    "tests/test_golden_examples.py::test_golden_examples_pass_under_bare_pytest":
        "the golden examples under a bare pytest, a few one-assert files; under 0.5 s",
    "tests/test_marker_parity.py::TestFullTreeFragmentsResolve::test_every_fragment_collects_at_least_one_real_nodeid":
        "one --collect-only of the whole tests/ tree, no row run; 29 s, under its own 300 s bound; the one "
        "enrolled row marked past the 60 s ceiling (360 s), kept here because no test body runs",
    "tests/test_proof_tier.py::TestNoParallelLineCollectsASerialFile::_collected":
        "a --collect-only of the serial files under a tier line's selection; up to 5.5 s a row",
    "tests/test_proof_tier.py::TestTheFullRecipe::test_the_contract_tiers_body_line_collects_the_diagnostics::collected":
        "a --collect-only of one file under a selection; 2.3 s",
    "tests/test_proof_tier.py::TestTheLegsAndTheHeavyLane::test_neither_line_collects_a_heavy_stage_without_heavy::collected":
        "a --collect-only of one file under a selection; 1.9 s",
    "tests/test_timeout_backstop.py::_drive":
        "a planted one-file suite under --timeout=1; POSIX only (SIGALRM), untimed",
    "tests/test_write_guard.py::TestGitBashDrivePrefix::_inner_session":
        "a planted two-test probe under the floor's construction refusal; POSIX only, untimed",
    "tests/test_write_guard.py::TestGitBashDrivePrefix::test_the_rows_the_floor_cannot_drive_are_exactly_the_skipped_ones":
        "this file's 13 emulated path rows, in process, no hook spawned; the row runs on POSIX at 3.12+, "
        "and its child took 1.9 s driven by hand on the Windows seat",
    "tests/test_xdist_never_ran.py::_drive":
        "a planted one-file suite under xdist with a crash or a ceiling planted; up to 7.2 s a row",
}
#: The scripts that spell pytest in a launch the rule cannot read, EXACT, each
#: with why: a test's launch of one of them is not seen by the hop, so it is
#: placed by hand (DEF-2036). One that turns readable leaves this dict for the
#: hop set; a hop script refactored out of the rule's reading lands here, never
#: silently out of the scan.
_SCRIPTS_THE_HOP_CANNOT_READ: dict[str, str] = {
    "scripts/final_release_matrix.py": "its suite runs go through a local `_run(argv, ...)` helper",
    "scripts/fresh_clone_gate.py": "a second hop: it runs scripts/proof_tier.py --run in a clone",
    "scripts/host_check.py": "its pytest argv is held in a step dict",
}


def _bindings(nodes: Iterable[ast.AST]) -> dict[str, list[ast.expr]]:
    """Every value assigned to a plain name among ``nodes``, by name."""
    out: dict[str, list[ast.expr]] = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out.setdefault(node.target.id, []).append(node.value)
    return out


def _module_bindings(tree: ast.Module) -> dict[str, list[ast.expr]]:
    """``_bindings`` over the statements no function or class body holds, so
    a name bound under a module-level ``if`` or ``try`` is read too."""
    stack: list[ast.AST] = list(tree.body)
    nodes: list[ast.AST] = []
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        nodes.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return _bindings(nodes)


def _word(node: ast.expr, names: dict[str, list[ast.expr]]) -> str | None:
    """``node`` as a string constant, through a name bound to one and through
    a ``dedent`` of one."""
    if (isinstance(node, ast.Call) and node.args
            and (getattr(node.func, "id", None) == "dedent" or getattr(node.func, "attr", None) == "dedent")):
        return _word(node.args[0], names)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        for value in names.get(node.id, ()):
            word = _word(value, {})
            if word is not None:
                return word
    return None


def _path_word(node: ast.expr, names: dict[str, list[ast.expr]], depth: int = 0) -> str | None:
    """``node`` as a path string as far as its last parts are constants: a
    ``/`` chain, an ``os.path.join``, a ``str()`` of either, through a name
    bound to one (``REPO_ROOT / "scripts" / "x.py"`` reads ``/scripts/x.py``)."""
    if depth > 8:
        return None
    if isinstance(node, ast.Call) and len(node.args) == 1 and getattr(node.func, "id", None) == "str":
        return _path_word(node.args[0], names, depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = _path_word(node.right, names, depth + 1)
        return None if right is None else f"{_path_word(node.left, names, depth + 1) or ''}/{right}"
    if isinstance(node, ast.Call) and node.args and (
            getattr(node.func, "id", getattr(node.func, "attr", None)) in {"Path", "PurePath", "joinpath"}
            or (getattr(node.func, "attr", None) == "join" and len(node.args) > 1)):
        parts = [_path_word(a, names, depth + 1) for a in node.args]
        if getattr(node.func, "attr", None) == "joinpath":   # the receiver is the path's head
            parts.insert(0, _path_word(node.func.value, names, depth + 1))
        return None if parts[-1] is None else "/".join(p or "" for p in parts)
    if isinstance(node, ast.Name):
        for value in names.get(node.id, ()):
            word = _path_word(value, names, depth + 1)
            if word is not None:
                return word
        return None
    return _word(node, {})


#: A script path's tail, ``scripts/<name>.py``, as ``_path_word`` reads it.
_SCRIPT_TAIL = re.compile(r"(?:^|/)(scripts/\w+\.py)$")


def _is_pytest_argv(node: ast.expr | None, names: dict[str, list[ast.expr]], depth: int = 0,
                    hops: frozenset[str] = frozenset()) -> bool:
    if node is None or depth > 8:
        return False
    if isinstance(node, ast.Name):
        return any(_is_pytest_argv(value, names, depth + 1, hops) for value in names.get(node.id, ()))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_is_pytest_argv(node.left, names, depth + 1, hops)
                or _is_pytest_argv(node.right, names, depth + 1, hops))
    if not isinstance(node, (ast.List, ast.Tuple)):
        return False
    if any(isinstance(e, ast.Starred) and _is_pytest_argv(e.value, names, depth + 1, hops) for e in node.elts):
        return True
    words = [_word(e, names) for e in node.elts]
    pairs = list(zip(words, words[1:]))
    # The script hop: the argv's head, or the word after an interpreter (a
    # non-constant head such as `sys.executable`, or a constant `python...`).
    head = words[0] if words else ""
    lead = node.elts[:2] if head is None or head.startswith(("python", "py")) else node.elts[:1]
    heads = (_SCRIPT_TAIL.search(_path_word(e, names) or "") for e in lead)
    return (words[:1] == ["pytest"] or ("-m", "pytest") in pairs
            or any(a == "-c" and b is not None and "pytest.main(" in b for a, b in pairs)
            or any(m is not None and m.group(1) in hops for m in heads))


def nested_pytest_launches(text: str, hops: frozenset[str] = frozenset()) -> set[str]:
    """The functions in ``text`` that launch a pytest child, each by its
    qualified name (``Class::function``; ``<module>`` for a launch at module
    level). ``hops`` are the ``scripts/<name>.py`` paths whose own launches
    read as one, so a launch of one of them reads as one too."""
    tree = ast.parse(text)
    modules, bare = {"subprocess"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            bare.update(a.asname or a.name for a in node.names if a.name in _LAUNCHERS)
    found: set[str] = set()

    def launches(call: ast.Call) -> bool:
        f = call.func
        return ((isinstance(f, ast.Attribute) and f.attr in _LAUNCHERS
                 and isinstance(f.value, ast.Name) and f.value.id in modules)
                or (isinstance(f, ast.Name) and f.id in bare)
                or getattr(f, "id", getattr(f, "attr", None)) in _NAMED_LAUNCHERS)

    def visit(node: ast.AST, qual: tuple[str, ...], names: dict[str, list[ast.expr]]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own = _bindings(ast.walk(child))
                visit(child, qual + (child.name,), {k: names.get(k, []) + own.get(k, []) for k in {*names, *own}})
                continue
            if isinstance(child, ast.ClassDef):
                visit(child, qual + (child.name,), names)
                continue
            if isinstance(child, ast.Call) and launches(child):
                argv = child.args[0] if child.args else next(
                    (k.value for k in child.keywords if k.arg == "args"), None)
                if _is_pytest_argv(argv, names, hops=hops):
                    found.add("::".join(qual) or "<module>")
            visit(child, qual, names)

    visit(tree, (), _module_bindings(tree))
    return found


class TestTheNestedRunRule:
    """DEF-2035: a pytest child launched off the serial lists is placed when it
    lands, not found by a red leg; with the detector's must-trip and
    must-not-trip rows (`docs/STANDING_PRINCIPLES.md` §7)."""

    # Every launch spells the constant `pytest` or `pytest.main(` in a string,
    # or, through the script hop, names a hop script's file (``_live`` reads both).
    _PREFILTER = re.compile(r"""["']pytest["']|pytest\.main\(""")

    @classmethod
    def _hops(cls) -> frozenset[str]:
        """The ``scripts/<name>.py`` files that launch a pytest child as the
        rule reads them, read without a hop set of their own: one hop."""
        return frozenset(
            f"scripts/{path.name}" for path in checkout_glob(REPO_ROOT / "scripts", "*.py")
            if cls._PREFILTER.search(text := path.read_text(encoding="utf-8")) and nested_pytest_launches(text))

    @classmethod
    def _live(cls) -> dict[str, set[str]]:
        """``{file: its launching functions}`` over every module under tests/,
        helpers included (a launch hoisted into a ``tests/_*.py`` helper runs
        wherever its callers do), a launch of a script in ``_hops`` counted."""
        hops = cls._hops()
        stems = tuple(hop.split("/")[-1] for hop in hops)
        out: dict[str, set[str]] = {}
        for path in checkout_glob(REPO_ROOT / "tests", "*.py"):
            text = path.read_text(encoding="utf-8")
            if cls._PREFILTER.search(text) or any(stem in text for stem in stems):
                found = nested_pytest_launches(text, hops)
                if found:
                    out[f"tests/{path.name}"] = found
        return out

    def test_the_runs_this_was_written_for_are_in_the_population(self):
        """Asserted first: the two children a leg has measured read as
        launches, and the scan clears its floor, so a clean verdict below is
        not a scan that found nothing."""
        live = self._live()
        assert "test_every_cited_pin_runs_and_passes_on_this_host" in live.get(
            "tests/test_declared_limits_contract.py", set()), live
        assert "outcomes" in live.get("tests/test_axis_registry.py", set()), live
        assert "scripts/verify_pins.py" in self._hops(), self._hops()
        assert "_run" in live.get("tests/test_verify_pins.py", set()), live   # through the script hop (DEF-2036)
        count = sum(map(len, live.values()))
        assert _NESTED_LAUNCH_FLOOR <= count <= 2 * _NESTED_LAUNCHES_AT_PIN, (
            f"{count} launches against a pin of {_NESTED_LAUNCHES_AT_PIN}: under half is a broken "
            "scan, over twice a population the pin no longer describes; re-pin it with the date")

    def test_no_launch_off_the_serial_lists_is_unplaced(self, pt):
        """The guard: a new launch in a file on no serial list reds here
        until it is placed (the section comment says where)."""
        live = self._live()
        assert sum(map(len, live.values())) >= _NESTED_LAUNCH_FLOOR, live   # an empty scan is not a pass
        unplaced = sorted(f"{rel}::{fn}" for rel, fns in live.items() if rel not in pt.SERIAL_FILES
                          for fn in fns if f"{rel}::{fn}" not in _PARALLEL_NESTED_RUNS)
        assert not unplaced, (
            "these launch a pytest child beside the -n auto pool and are not placed: time each alone; "
            "a child that runs this repo's rows for long, or rows that keep a budget, joins "
            "NESTED_RUN_SERIAL_FILES in scripts/proof_tier.py (and SERIAL_CONTRACT_FILES when its file "
            "holds a contract row); one that only collects, runs a planted tree, or runs a few in-process "
            f"rows for seconds is enrolled in _PARALLEL_NESTED_RUNS with what it runs: {unplaced}")

    def test_every_enrolled_launch_still_launches_off_the_serial_lists(self, pt):
        """The other way: an entry whose function was renamed, stopped
        launching or moved to a serial file is struck, so the roster names
        only what rides the pool."""
        live = self._live()
        current = {f"{rel}::{fn}" for rel, fns in live.items() if rel not in pt.SERIAL_FILES for fn in fns}
        assert not set(_PARALLEL_NESTED_RUNS) - current, sorted(set(_PARALLEL_NESTED_RUNS) - current)
        assert all(why.strip() for why in _PARALLEL_NESTED_RUNS.values())

    @pytest.mark.parametrize("label, source, expect", [
        ("an -m pytest display in the call",
         "import subprocess, sys\ndef test_x():\n    subprocess.run([sys.executable, '-m', 'pytest', '-q'])\n",
         {"test_x"}),
        ("a bare pytest head through Popen",
         "import subprocess\ndef helper():\n    subprocess.Popen(['pytest', 'tests/'])\n", {"helper"}),
        ("an argv bound to a local first",
         "import subprocess, sys\ndef _drive():\n    argv = [sys.executable, '-m', 'pytest']\n"
         "    return subprocess.run(argv)\n", {"_drive"}),
        ("an argv built with + and a starred name",
         "import subprocess, sys\nBASE = [sys.executable, '-m', 'pytest']\nclass TestA:\n"
         "    def test_y(self):\n        subprocess.run([*BASE, '-q'] + ['x'])\n", {"TestA::test_y"}),
        ("a -c program that calls pytest.main, held in a module constant",
         "import subprocess, sys\n_PROG = 'import pytest; pytest.main([])'\ndef collect():\n"
         "    subprocess.run([sys.executable, '-c', _PROG], timeout=45)\n", {"collect"}),
        ("an aliased module and an args= keyword",
         "import subprocess as sp, sys\ndef test_z():\n    sp.check_output(args=[sys.executable, '-m', 'pytest'])\n",
         {"test_z"}),
        ("a launcher imported bare",
         "from subprocess import run\nimport sys\ndef test_w():\n    run([sys.executable, '-m', 'pytest'])\n",
         {"test_w"}),
        ("a launch at module level", "import subprocess, sys\nsubprocess.run([sys.executable, '-m', 'pytest'])\n",
         {"<module>"}),
        ("an argv bound under a module-level if",
         "import subprocess, sys\nif sys.platform:\n    ARGV = [sys.executable, '-m', 'pytest']\n"
         "def test_v():\n    subprocess.run(ARGV)\n", {"test_v"}),
        ("the bounded spawn",
         "import sys\ndef test_u(primitive):\n    primitive.run_bounded([sys.executable, '-m', 'pytest'], timeout=9)\n",
         {"test_u"}),
        ("a -c program built with dedent",
         "import subprocess, sys, textwrap\ndef test_t():\n"
         "    prog = textwrap.dedent('''\\n    import pytest\\n    pytest.main([])\\n    ''')\n"
         "    subprocess.run([sys.executable, '-c', prog])\n", {"test_t"}),
    ])
    def test_the_detector_reads(self, label, source, expect):
        assert nested_pytest_launches(source) == expect, label

    @pytest.mark.parametrize("label, source", [
        ("an argv compared, never launched (tests/test_archive_probe.py's shape)",
         "import sys\ndef test_x(vpy):\n    assert build(vpy, []) == [str(vpy), '-m', 'pytest']\n"),
        ("an argv handed to a function that is not a launcher",
         "def test_x(pt):\n    pt.run_commands([('pytest', '--version')])\n"),
        ("a launch of another program",
         "import subprocess, sys\ndef test_x():\n    subprocess.run([sys.executable, '-m', 'pip', 'list'])\n"),
        ("a launch quoted in a string",
         "SNIPPET = \"subprocess.run([sys.executable, '-m', 'pytest'])\"\n"),
        ("a run method of something that is not subprocess",
         "import sys\ndef test_x(runner):\n    runner.run([sys.executable, '-m', 'pytest'])\n"),
    ])
    def test_the_detector_stays_quiet_on(self, label, source):
        assert nested_pytest_launches(source) == set(), label

    _HOP = frozenset({"scripts/hop.py"})
    _ROOTED = "import os, subprocess, sys\nfrom pathlib import Path\nROOT = Path(__file__).parent\n"

    @pytest.mark.parametrize("label, source, expect", [
        ("a script held as a path chain, launched through str()",
         _ROOTED + "_SCRIPT = ROOT / 'scripts' / 'hop.py'\ndef _run():\n"
         "    subprocess.run([sys.executable, str(_SCRIPT), '--json'])\n", {"_run"}),
        ("a script spelled as a constant at the argv's head",
         _ROOTED + "def test_x():\n    subprocess.run(['scripts/hop.py', '-q'])\n", {"test_x"}),
        ("a script joined by os.path.join",
         _ROOTED + "class TestA:\n    def test_y(self):\n"
         "        subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'hop.py')])\n", {"TestA::test_y"}),
        ("a scripts directory bound to a name, joined in the function",
         _ROOTED + "SCRIPTS = ROOT / 'scripts'\ndef test_z():\n    script = SCRIPTS / 'hop.py'\n"
         "    subprocess.run([sys.executable, str(script)])\n", {"test_z"}),
        ("a relative Path chain",
         _ROOTED + "def test_p():\n    subprocess.run([sys.executable, str(Path('scripts') / 'hop.py')])\n",
         {"test_p"}),
        ("a Path of one constant",
         _ROOTED + "def test_q():\n    subprocess.run([sys.executable, Path('scripts/hop.py')])\n", {"test_q"}),
        ("a joinpath on the root",
         _ROOTED + "def test_r():\n    subprocess.run([sys.executable, ROOT.joinpath('scripts', 'hop.py')])\n",
         {"test_r"}),
    ])
    def test_the_detector_reads_one_script_hop(self, label, source, expect):
        """DEF-2036: a launch of a script whose own launches the rule reads is
        a launch of a pytest child."""
        assert nested_pytest_launches(source, self._HOP) == expect, label

    @pytest.mark.parametrize("label, source, hops", [
        ("a script the hop set does not hold",
         _ROOTED + "def test_x():\n    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'other.py')])\n", _HOP),
        ("a hop script's path read, never launched",
         _ROOTED + "_SCRIPT = ROOT / 'scripts' / 'hop.py'\ndef test_x():\n    text = _SCRIPT.read_text()\n"
         "    subprocess.run(['git', 'log'])\n", _HOP),
        ("a hop script named as data past the program and its verb",
         _ROOTED + "def test_x():\n    subprocess.run(['git', 'add', 'scripts/hop.py'])\n", _HOP),
        ("a hop script as the second word after a program that is not an interpreter",
         _ROOTED + "def test_x():\n    subprocess.run(['git', 'scripts/hop.py'])\n", _HOP),
        ("a hop script launched with no hop set, as the scripts are scanned",
         _ROOTED + "def test_x():\n    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'hop.py')])\n",
         frozenset()),
    ])
    def test_the_hop_stays_quiet_on(self, label, source, hops):
        assert nested_pytest_launches(source, hops) == set(), label

    def test_every_script_that_spells_pytest_is_a_hop_or_declared(self):
        """The hop set cannot shrink unseen: a script that spells pytest is
        either one the rule reads as launching it or declared unreadable with
        why, and a declared one that turns readable is struck."""
        spelled = {f"scripts/{p.name}" for p in checkout_glob(REPO_ROOT / "scripts", "*.py")
                   if self._PREFILTER.search(p.read_text(encoding="utf-8"))}
        assert spelled - self._hops() == set(_SCRIPTS_THE_HOP_CANNOT_READ), (
            sorted(spelled - self._hops()), sorted(_SCRIPTS_THE_HOP_CANNOT_READ))
        assert all(why.strip() for why in _SCRIPTS_THE_HOP_CANNOT_READ.values())


class TestRun:
    """``--run`` is one command with one receipt: every command runs, each gets
    an exit line, the summary names how many ran, and the worst code is the
    exit. The subprocess is faked so no pytest is spawned from inside pytest."""

    def _fake_run(self, monkeypatch, pt, codes, versions=None):
        """Fake only the runner spawns; the script's own `git status` call goes
        through to the real runner (pt.subprocess IS the stdlib module). A
        runner's ``--version`` read answers from ``versions`` (default
        ``<runner> 0.0.0``) and is kept out of ``calls``, which records the
        tier's commands only."""
        calls = []
        real = subprocess.run
        def fake(argv, **kw):
            if list(argv)[:1] not in (["pytest"], ["mypy"], ["ruff"]):
                return real(argv, **kw)
            if list(argv)[1:] == ["--version"]:
                said = (versions or {}).get(argv[0], f"{argv[0]} 0.0.0")
                return types.SimpleNamespace(returncode=0, stdout=said + "\n", stderr="")
            calls.append(list(argv))
            return types.SimpleNamespace(returncode=codes[len(calls) - 1])
        monkeypatch.setattr(pt.subprocess, "run", fake)
        return calls

    def test_the_receipt_names_each_runners_version_once_before_its_commands(self, pt, monkeypatch, capsys):
        self._fake_run(monkeypatch, pt, [0, 0, 0, 0],
                       versions={"mypy": "mypy 2.4.0 (compiled: yes)", "ruff": "ruff 0.17.0", "pytest": "pytest 9.1.1"})
        assert pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT) == 0
        lines = capsys.readouterr().out.splitlines()
        version = [line for line in lines if line.startswith("version: ")]
        assert [v.split()[1] for v in version] == ["mypy", "ruff", "pytest"], version
        first_exit = next(i for i, line in enumerate(lines) if line.startswith("exit "))
        assert all(lines.index(v) < first_exit for v in version), lines

    def test_a_runner_off_the_dev_extras_pin_is_named_with_the_reinstall_line(self, pt, monkeypatch, capsys, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\n[project.optional-dependencies]\n'
            'dev = ["ruff==0.17.0", "mypy == 2.4.0", "pytest>=7.0"]\n', encoding="utf-8")
        assert pt.dev_extra_pins(tmp_path) == {"ruff": "0.17.0", "mypy": "2.4.0"}
        self._fake_run(monkeypatch, pt, [0, 0, 0, 0],
                       versions={"mypy": "mypy 2.4.0 (compiled: yes)", "ruff": "ruff 0.16.9", "pytest": "pytest 9.1.1"})
        assert pt.run_commands(pt._TIER_ARGVS["full"], tmp_path) == 0
        version = {line.split()[1]: line for line in capsys.readouterr().out.splitlines() if line.startswith("version: ")}
        assert "the dev extra pins ruff==0.17.0, which CI runs: python -m pip install ruff==0.17.0" in version["ruff"]
        assert "pins" not in version["mypy"] and "pins" not in version["pytest"], version

    def test_a_runner_with_no_branch_of_its_own_is_refused_not_read_as_pytest(self, pt, tmp_path):
        """Both dispatches end in a refusal, so a runner added to the roster
        without its own branch cannot print pytest's version in its slot."""
        with pytest.raises(ValueError, match="black"):
            pt.version_lines((("black", "."),), tmp_path)

    def test_a_runner_with_no_version_or_no_binary_never_changes_the_verdict(self, pt, monkeypatch, capsys, tmp_path):
        real = subprocess.run
        def fake(argv, **kw):
            if list(argv) == ["ruff", "--version"]:
                raise FileNotFoundError("ruff")
            if list(argv)[:1] in (["mypy"], ["ruff"], ["pytest"]):
                return subprocess.CompletedProcess(argv, 0)  # no stdout, no stderr
            return real(argv, **kw)
        monkeypatch.setattr(pt.subprocess, "run", fake)
        assert pt.run_commands(pt._TIER_ARGVS["full"], tmp_path) == 0
        out = capsys.readouterr().out
        assert "version: ruff not installed" in out and "version: mypy printed no version (exit 0)" in out
        assert "proof: PASS -- 4 of 4 command(s) ran" in out

    def test_a_forced_downgrade_is_named_beside_the_receipt(self, pt, monkeypatch, tmp_path, capsys):
        """`--tier contract` on a runtime diff prints the forced note at the top
        and, four lines later, a receipt that would otherwise read as the earned
        run; the note is repeated beside the verdict. The upgrade twin
        (`--tier full` on a docs diff) is pinned separately."""
        r = _repo(tmp_path)
        (r / "tools" / "cc" / "hooks" / "h.py").write_text("y\n", encoding="utf-8")
        n = len(pt.CONTRACT_COMMANDS)
        self._fake_run(monkeypatch, pt, [0] * n)
        assert pt.main(["--root", str(r), "--tier", "contract", "--run"]) == 0
        out = capsys.readouterr().out
        assert "contract (forced; the diff earned full)" in out
        assert "forced: ran the contract tier; the diff earned full" in out
        assert out.index(f"{n} of {n} command(s) ran") < out.index("forced: ran the contract tier")

    def test_an_earned_run_carries_no_forced_note(self, pt, monkeypatch, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        self._fake_run(monkeypatch, pt, [0] * len(pt.CONTRACT_COMMANDS))
        assert pt.main(["--root", str(r), "--run"]) == 0
        assert "forced" not in capsys.readouterr().out

    def test_every_command_runs_and_the_worst_exit_wins(self, pt, monkeypatch, capsys):
        calls = self._fake_run(monkeypatch, pt, [0, 0, 3, 0])
        assert pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT) == 3
        assert calls == [list(argv) for argv in pt._TIER_ARGVS["full"]]
        out = capsys.readouterr().out
        exit_lines = [line for line in out.splitlines() if line.startswith("exit ")]
        assert len(exit_lines) == 4 and "4 of 4 command(s) ran" in out and "FAIL (worst exit 3)" in out

    def test_run_spawns_the_head_it_prints(self, pt, monkeypatch, capsys):
        """The receipt line and the spawned binary are the same token: a mypy
        entry spawns mypy, a pytest entry spawns pytest."""
        calls = self._fake_run(monkeypatch, pt, [0, 0, 0, 0])
        pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT)
        assert [c[0] for c in calls] == [argv[0] for argv in pt._TIER_ARGVS["full"]] == ["mypy", "ruff", "pytest", "pytest"]
        out = capsys.readouterr().out
        assert "exit 0: mypy tools/cc/hooks/" in out

    def test_a_missing_runner_is_a_loud_exit_127_with_the_install_hint(self, pt, monkeypatch, capsys):
        real = subprocess.run
        def fake(argv, **kw):
            if list(argv)[:1] == ["mypy"]:
                raise FileNotFoundError("mypy")
            if list(argv)[:1] in (["pytest"], ["ruff"]):
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            return real(argv, **kw)
        monkeypatch.setattr(pt.subprocess, "run", fake)
        assert pt.run_commands(pt._TIER_ARGVS["full"], REPO_ROOT) == 127
        out = capsys.readouterr().out
        assert "exit 127: mypy tools/cc/hooks/" in out and pt.INSTALL_HINT in out and "4 of 4" in out

    def test_a_forced_full_tier_on_a_docs_only_tree_says_so_and_runs_both(self, pt, tmp_path, monkeypatch, capsys):
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        calls = self._fake_run(monkeypatch, pt, [0, 0, 0, 0])
        assert pt.main(["--root", str(r), "--tier", "full", "--run"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("full (forced; the diff earned contract)") and pt.INSTALL_HINT in out
        assert len(calls) == 4 and "PASS -- 4 of 4" in out

    def test_run_refuses_while_a_file_is_untracked(self, pt, tmp_path, monkeypatch, capsys):
        r = _repo(tmp_path)
        (r / "scripts" / "new.py").write_text("x\n", encoding="utf-8")
        calls = self._fake_run(monkeypatch, pt, [0, 0])
        assert pt.main(["--root", str(r), "--run"]) == 2
        assert calls == [] and "git add -N scripts/new.py" in capsys.readouterr().out

    def test_run_refuses_while_a_tracked_file_is_deleted_but_not_staged(self, pt, tmp_path, monkeypatch, capsys):
        """The twin of the untracked refusal: an index row with no file behind
        it is counted by every git ls-files gate (and, since the tracked-set
        oracle leaves it out, no longer crashes them), so the tier refuses
        until the deletion is staged."""
        r = _repo(tmp_path)
        (r / "docs" / "X.md").unlink()
        calls = self._fake_run(monkeypatch, pt, [0, 0])
        assert pt.main(["--root", str(r), "--run"]) == 2
        out = capsys.readouterr().out
        assert calls == [] and "git add -u docs/X.md" in out and "deleted but not staged" in out

    def test_every_tier_prints_the_install_hint(self, pt, tmp_path, capsys):
        """Every tier's pytest lines carry ``-n`` since DEF-2017, so a venv
        without pytest-xdist fails the contract tier too: the hint prints for
        every tier, not only the full one (failure-mode review, 2026-10-16)."""
        r = _repo(tmp_path)
        (r / "docs" / "X.md").write_text("y\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("contract") and pt.INSTALL_HINT in out

    def test_a_usage_error_on_an_xdist_line_names_the_install_hint(self, pt, monkeypatch, capsys):
        """pytest without pytest-xdist reads ``-n`` as an unknown argument and
        exits 4, its usage error: the receipt names the extra beside that exit,
        as it does for a runner that is not installed at all."""
        def fake(argv, **kw):
            if list(argv)[1:] == ["--version"]:
                return types.SimpleNamespace(returncode=0, stdout=f"{argv[0]} 0.0.0\n", stderr="")
            return types.SimpleNamespace(returncode=4 if argv[0] == "pytest" else 0, stdout="", stderr="")
        monkeypatch.setattr(pt.subprocess, "run", fake)
        assert pt.run_commands(pt._TIER_ARGVS["contract"], REPO_ROOT) == 4
        out = capsys.readouterr().out
        assert "exit 4: pytest -n auto -m contract -q" in out and pt.INSTALL_HINT in out

    def test_a_command_not_led_by_a_known_runner_is_refused(self, pt):
        with pytest.raises(ValueError):
            pt.run_commands((("rm", "-rf", "x"),), REPO_ROOT)


class TestTheLegsAndTheHeavyLane:
    """The heavy end-to-end stages left the per-pull-request tier on 2026-09-30
    (the stage-one smoke alone was 848 s of a 992 s parallel leg in a CI cell),
    and the serial leg runs beside the parallel one as its own required cells.
    ``--leg`` is defined by complement so a cheaper tier's required cells keep
    running their whole tier; ``--heavy`` puts the stages back on BOTH lines,
    because one member lives in a serial-leg file (the pack-artifact review
    caught the parallel-only shape)."""

    def test_leg_serial_on_the_contract_tier_reports_and_runs_nothing(self, pt, tmp_path, capsys, monkeypatch):
        assert pt.tier_argvs("contract", leg="serial") == ()
        assert pt.tier_argvs("recall", leg="serial") == ()
        calls: list[list[str]] = []
        real_run = pt.subprocess.run

        def fake_run(argv, **kw):  # git reads stay real; a runner spawn is recorded, never run
            if argv[0] == "git":
                return real_run(argv, **kw)
            calls.append(list(argv))
            return _Rc(0)

        monkeypatch.setattr(pt.subprocess, "run", fake_run)
        r = _repo(tmp_path)
        rc = pt.main(["--root", str(r), "--tier", "contract", "--run", "--leg", "serial"])
        out = capsys.readouterr().out
        assert rc == 0 and calls == []
        assert "nothing to run: the serial leg of the contract tier has no commands" in out
        assert "no commands on this run -- the receipt below proves nothing" in out
        assert "proof: PASS -- 0 of 0 command(s) ran" in out
        # the print path says it too, so a dry run is never mute about an empty leg
        pt.main(["--root", str(r), "--tier", "contract", "--leg", "serial"])
        assert "nothing to run: the serial leg of the contract tier" in capsys.readouterr().out

    def test_a_changed_serial_file_rides_a_cheaper_tiers_parallel_leg_and_the_words_say_so(
        self, pt, tmp_path, capsys,
    ):
        """A test-only diff that changes a serial file earns the contract tier,
        and that file rides a line of its own at one worker inside the parallel
        leg (the legs are by complement, so a cheaper tier's required cells run
        it under ``parallel``): the words may not say the tier has no line for
        it, or that the serial files belong to the full tier (failure-mode
        review, 2026-10-16)."""
        r = _repo(tmp_path)
        rel = pt.SERIAL_FILES[0]
        (r / rel).write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(r), "add", rel], check=True)
        pt.main(["--root", str(r), "--leg", "parallel"])
        out = capsys.readouterr().out
        assert out.startswith("contract") and f"run: pytest -q -n 1 -m 'not heavy_e2e' {rel}" in out
        assert "no serial line" not in out and "a changed serial file runs here at one worker" in out
        pt.main(["--root", str(r), "--leg", "serial"])
        out = capsys.readouterr().out
        assert "nothing to run: the serial leg of the contract tier" in out
        assert "belong to the full tier" not in out and "in its parallel leg, at one worker" in out

    def test_the_own_tests_line_carries_the_heavy_filter_on_the_cheaper_tiers(self, pt):
        """Both reviews found the same regression: a changed heavy module rides
        along on the cheaper tiers' own-tests line, and that line carried no
        filter, so a docs-plus-test pull request would have run the 848 s
        smoke in five required cells. Every pytest line filters; ``--heavy``
        strips every line. A changed serial file rides on its own line at one
        worker, the rest at ``-n auto`` (DEF-2017). The files that name a
        changed path ride with them (``path_readers``; this module names both)."""
        changed = ["tests/test_final_release_matrix.py", "tests/test_powershell_reachability_differential.py"]
        own = pt.own_tests(changed, REPO_ROOT)
        parallel = tuple(rel for rel in own if rel not in pt.SERIAL_FILES)
        serial = tuple(rel for rel in own if rel in pt.SERIAL_FILES)
        assert parallel[0] == changed[0] and serial[0] == changed[1], own
        for which in ("contract", "recall"):
            own_parallel, own_serial = pt.tier_argvs(which, changed, REPO_ROOT)[-2:]
            assert own_parallel == pt._PYTEST + pt._PARALLEL + pt._NOT_HEAVY + parallel, (which, own_parallel)
            assert own_serial == pt._PYTEST + pt._ONE_WORKER + pt._NOT_HEAVY + serial, (which, own_serial)
            heavy_own = pt.tier_argvs(which, changed, REPO_ROOT, heavy=True)[-2:]
            assert "heavy_e2e" not in " ".join(heavy_own[0] + heavy_own[1])
            assert (heavy_own[0][-len(parallel):], heavy_own[1][-len(serial):]) == (parallel, serial)
            assert pt.tier_argvs(which, changed, REPO_ROOT, leg="serial") == ()
            assert pt.tier_argvs(which, changed, REPO_ROOT, leg="parallel")[-2:] == (own_parallel, own_serial)

    def test_leg_parallel_is_the_complement_of_the_serial_line_on_every_tier(self, pt):
        for which in pt.TIERS:
            both = pt.tier_argvs(which)
            parallel = pt.tier_argvs(which, leg="parallel")
            serial = pt.tier_argvs(which, leg="serial")
            assert parallel + serial == both, which
            assert all(argv[-len(pt.SERIAL_FILES):] == pt.SERIAL_FILES for argv in serial), which
        assert pt.tier_argvs("full", leg="serial") == (pt.tier_argvs("full")[-1],)
        assert pt.tier_argvs("contract", leg="parallel") == pt.tier_argvs("contract")
        with pytest.raises(ValueError):
            pt.tier_argvs("full", leg="sideways")

    def test_heavy_restores_the_stages_on_both_lines(self, pt):
        pair = pt._NOT_HEAVY
        default = pt.tier_argvs("full")
        carrying = [argv for argv in default if any(argv[i:i + 2] == pair for i in range(len(argv) - 1))]
        assert [argv[0] for argv in carrying] == ["pytest", "pytest"], "both pytest lines, and only them"
        heavy = pt.tier_argvs("full", heavy=True)
        assert not any("heavy_e2e" in tok for argv in heavy for tok in argv)
        assert heavy[0] == default[0] == ("mypy", "tools/cc/hooks/")
        assert len(pt.FULL_COMMANDS) == 4 and all("heavy_e2e" in c for c in pt.FULL_COMMANDS[2:])
        assert pt.commands("full", heavy=True, leg="serial") == (shlex.join(heavy[-1]),)

    def test_neither_line_collects_a_heavy_stage_without_heavy(self, pt):
        """Driven, not read: the marker expression the two lines carry deselects
        every member of ``_HEAVY_E2E_TESTS`` at collection, and the ``--heavy``
        form (no expression) collects them. The population is derived -- every
        test module that defines a member -- so a member added to the set is in
        the proof without a hand edit here."""
        from tests.conftest import _HEAVY_E2E_TESTS
        members = sorted(_HEAVY_E2E_TESTS)
        files = sorted(
            str(f.relative_to(REPO_ROOT)).replace("\\", "/") for f in checkout_glob(REPO_ROOT / "tests", "test_*.py")
            if any(f"def {name}(" in f.read_text(encoding="utf-8") for name in members)
        )
        assert files, "no module defines a heavy member -- the set and the tree disagree"

        def collected(extra: tuple[str, ...]) -> int:
            argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra, *files]
            out = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8").stdout
            return sum(1 for line in out.splitlines() for name in members if line.endswith("::" + name))

        assert collected(pt._NOT_HEAVY) == 0
        assert collected(()) == len(members)


class _Rc:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode



#: A scratch workflow for the gate derivation (air's red, 2026-10-16): one
#: planted call per shape that joins (a YAML-quoted value is the shell's text,
#: so it joins), and one per shape that must not -- a
#: comment, a quoted string either way, an assignment value, an ``env:`` value,
#: a line inside another key's block, a sibling key after a ``run:`` block, and
#: a path no file at the head answers.
_PLANTED_WORKFLOW = """name: ci
on: push
jobs:
  t:
    runs-on: ubuntu-latest
    env:
      GATE_ENV: scripts/env_value.py
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/new_gate.py --check
      - run: "python scripts/yaml_quoted.py"
      - name: block
        run: |
          # python scripts/commented.py
          echo "python scripts/double_quoted.py"
          echo 'scripts/single_quoted.py'
          GATE=scripts/assigned.py true
          python scripts/absent.py
          python ./scripts/dotted.py && python scripts/chained.py
          python "$PREFIX"scripts/prefixed.py
          echo "say \\" python scripts/escaped_quote.py now"
        working-directory: scripts/sibling_key.py
      - uses: actions/github-script@v7
        with:
          script: |
            run: python scripts/other_block.py
      - uses: ./.github/actions/local  # the local action
"""
_PLANTED_ACTION = """name: local
runs:
  using: composite
  steps:
    - run: python tools/from_action.py
      shell: bash
"""
_JOINS = ("scripts/new_gate.py", "scripts/yaml_quoted.py", "scripts/dotted.py", "scripts/chained.py",
          "scripts/prefixed.py",
          ".github/actions/local/action.yml", "tools/from_action.py")
_NOT_CALLS = ("scripts/commented.py", "scripts/double_quoted.py", "scripts/single_quoted.py",
              "scripts/assigned.py", "scripts/env_value.py", "scripts/other_block.py",
              "scripts/sibling_key.py", "scripts/escaped_quote.py")


def _planted(tmp_path, *, workflow=_PLANTED_WORKFLOW):
    r = tmp_path / "rv"
    files = {rel: "x\n" for rel in _JOINS + _NOT_CALLS}
    files[".github/actions/local/action.yml"] = _PLANTED_ACTION
    if workflow is not None:
        files[".github/workflows/ci.yml"] = workflow
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text, encoding="utf-8")
    return r


class TestTheReviewLine:
    """``review`` is ``/implement-task`` and ``/preflight`` step 6's rule made
    mechanical, over the tier's own changed paths: a path on the review surface
    earns ``code-reviewer``; a hook, a command / agent / skill / workflow body,
    or a gate earns ``both``; anything else ``none``. A gate is the CI
    definition, ``bench/``, and every file a workflow at the diff's head calls,
    derived and never kept by hand (air, 2026-10-16)."""

    @pytest.mark.parametrize("rel,expected", [
        ("docs/X.md", "none"),
        ("memory/n.md", "none"),
        ("task-packs/TP-1-x.md", "none"),
        ("tests/test_x.py", "none"),
        # the suite's shared test code reads the code reviewer, the harness
        # configuration a hook or a gate reads both (air, 2026-10-16)
        ("tests/conftest.py", "code-reviewer"),
        ("tests/_helper.py", "code-reviewer"),
        ("pyproject.toml", "both"),
        ("espalier.toml", "both"),
        ("espalier/assets/claude/commands/x.md", "none"),
        ("espalier/_vendor/cc/hooks/h.py", "none"),
        ("examples/dogfooding/.claude/commands/x.md", "none"),
        ("scripts/s.py", "code-reviewer"),
        ("espalier/cli.py", "code-reviewer"),
        ("tools/cc/seat.py", "code-reviewer"),
        (".claude/CLAUDE.md", "code-reviewer"),
        ("tools/cc/hooks/h.py", "both"),
        (".claude/commands/x.md", "both"),
        (".claude/agents/a.md", "both"),
        (".claude/skills/s/SKILL.md", "both"),
        (".claude/workflows/w.js", "both"),
        (".github/workflows/ci.yml", "both"),
        (".github/actions/a/action.yml", "both"),
        ("bench/x.py", "both"),
    ])
    def test_each_surface_earns_its_reviewers(self, pt, tmp_path, rel, expected):
        verdict, earned_by = pt.review([rel], tmp_path)
        assert verdict == expected, (rel, earned_by)
        assert [p for p, _ in earned_by] == ([] if expected == "none" else [rel])

    @pytest.mark.parametrize("rel,why", [
        ("tools/cc/hooks/h.py", "a hook"),
        (".claude/skills/s/SKILL.md", "a command, agent, skill or workflow body"),
        (".github/workflows/ci.yml", "the CI definition"),
        (".github/actions/a/action.yml", "the CI definition"),
        ("bench/x.py", "the release bench"),
        ("scripts/s.py", "on the review surface"),
    ])
    def test_the_line_says_why_each_path_earned_it(self, pt, tmp_path, rel, why):
        assert pt.review([rel], tmp_path)[1] == [(rel, why)]

    def test_the_heaviest_path_decides_and_is_the_one_named(self, pt, tmp_path):
        verdict, earned_by = pt.review(
            ["docs/X.md", "scripts/s.py", "tools/cc/hooks/h.py"], tmp_path)
        assert (verdict, earned_by) == ("both", [("tools/cc/hooks/h.py", "a hook")])

    def test_a_script_a_workflow_runs_reads_both(self, pt, tmp_path):
        r = _planted(tmp_path)
        assert pt.review(["scripts/new_gate.py"], r) == (
            "both", [("scripts/new_gate.py", "a gate: .github/workflows/ci.yml runs it")])

    def test_the_same_script_with_no_workflow_reads_code_reviewer(self, pt, tmp_path):
        r = _planted(tmp_path, workflow=None)
        assert pt.review(["scripts/new_gate.py"], r)[0] == "code-reviewer"

    def test_the_derivation_is_exactly_the_calls(self, pt, tmp_path):
        named = pt.workflow_named_files(_planted(tmp_path))
        assert set(named) == set(_JOINS)
        assert named["tools/from_action.py"] == ".github/actions/local/action.yml"

    def test_a_path_a_workflow_names_that_is_absent_does_not_join(self, pt, tmp_path):
        r = _planted(tmp_path)
        assert "python scripts/absent.py" in _PLANTED_WORKFLOW
        assert "scripts/absent.py" not in pt.workflow_named_files(r)
        assert pt.review(["scripts/absent.py"], r)[0] == "code-reviewer"

    @pytest.mark.parametrize("rel", _NOT_CALLS)
    def test_a_word_that_is_not_a_call_does_not_join(self, pt, tmp_path, rel):
        r = _planted(tmp_path)
        assert rel in _PLANTED_WORKFLOW
        assert pt.review([rel], r)[0] == "code-reviewer"

    def test_base_mode_reads_the_head_not_the_working_tree(self, pt, tmp_path):
        r = _planted(tmp_path)
        subprocess.run(_git(r) + ["init", "-q"], check=True)
        subprocess.run(_git(r) + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(_git(r) + ["commit", "-qm", "i"], check=True, capture_output=True)
        wf = r / ".github" / "workflows" / "ci.yml"
        wf.write_text(_PLANTED_WORKFLOW.replace("scripts/new_gate.py", "scripts/commented.py"),
                      encoding="utf-8")
        assert "scripts/new_gate.py" in pt.workflow_named_files(r, at_head=True)
        assert "scripts/new_gate.py" not in pt.workflow_named_files(r)
        assert "scripts/commented.py" in pt.workflow_named_files(r)
        assert "scripts/commented.py" not in pt.workflow_named_files(r, at_head=True)
        (r / "scripts" / "late.py").write_text("x\n", encoding="utf-8")
        wf.write_text(_PLANTED_WORKFLOW + "      - run: python scripts/late.py\n", encoding="utf-8")
        assert "scripts/late.py" in pt.workflow_named_files(r)
        assert "scripts/late.py" not in pt.workflow_named_files(r, at_head=True)

    def test_the_cli_prints_the_line_beside_the_tier(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        (r / "tools" / "cc" / "hooks" / "h.py").write_text("changed\n", encoding="utf-8")
        assert pt.main(["--root", str(r)]) == 0
        assert "review: both -- tools/cc/hooks/h.py (a hook)\n" in capsys.readouterr().out
        assert pt.main(["--root", str(r), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["review"] == "both"
        assert data["review_earned_by"] == [{"path": "tools/cc/hooks/h.py", "why": "a hook"}]

    def test_a_docs_diff_says_none_and_why(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        _commit(r, "docs/X.md")
        assert pt.main(["--root", str(r), "--base", "HEAD~1"]) == 0
        assert "review: none -- no changed path is on the review surface\n" in capsys.readouterr().out

    def test_quiet_never_reads_the_workflows(self, pt, tmp_path, capsys, monkeypatch):
        """The CI tier job captures ``--quiet``'s one word; a workflow read it
        never needed must not be able to fail it."""
        r = _repo(tmp_path)
        _commit(r, "docs/X.md")

        def boom(*a, **k):
            raise AssertionError("--quiet read the workflows")
        monkeypatch.setattr(pt, "workflow_named_files", boom)
        assert pt.main(["--root", str(r), "--base", "HEAD~1", "--quiet"]) == 0
        assert capsys.readouterr().out == "contract\n"

    def test_unreadable_workflows_read_both_never_fewer(self, pt, tmp_path, capsys, monkeypatch):
        r = _repo(tmp_path)
        _commit(r, "docs/X.md")

        def unreadable(*a, **k):
            raise pt.BaseUnresolvable("cannot list HEAD's files: planted")
        monkeypatch.setattr(pt, "_head_files", unreadable)
        assert pt.main(["--root", str(r), "--base", "HEAD~1"]) == 0
        captured = capsys.readouterr()
        assert "review: both -- (the head) (unread)\n" in captured.out
        assert "planted; the review reads both" in captured.err

    def test_the_merge_gate_is_a_gate_on_this_tree(self, pt):
        """The live derivation: ``ci_guard.py`` alone reads both because
        harness-guard runs it (air: the merge gate's force-add backstop), and
        every path the derivation names is a file here."""
        named = pt.workflow_named_files(REPO_ROOT)
        assert named.get("tools/cc/ci_guard.py") == ".github/workflows/harness-guard.yml"
        assert all((REPO_ROOT / rel).is_file() for rel in named), named
        assert pt.review(["tools/cc/ci_guard.py"], REPO_ROOT)[0] == "both"


class TestTheBodiesCiteTheReviewLine:
    """The step 6 bodies keep the review rule as prose (the adopter branch has
    no script) and cite the script's line on this tree. The self-host surface
    they list and the script's surface roots agree both ways: one list kept in
    two places drifts on the cell nobody enumerated (FAILURE_MODES 1.12), and a
    presence-only pin is blind to an addition (SHARP_EDGES)."""

    _BODIES = {
        "implement-task.md": ("6. **Review before the one full run.**", "7. **Run the proof tier once"),
        "preflight.md": ("## Step 6: Diff review", "## Step 7:"),
        "implement-pack.md": ("dispatch the orthogonal-context review here",
                              "Stop conditions, per agent vocabulary"),
    }

    @classmethod
    def _step(cls, name: str) -> str:
        start, end = cls._BODIES[name]
        text = (REPO_ROOT / ".claude" / "commands" / name).read_text(encoding="utf-8")
        i = text.index(start)
        return " ".join(text[i:text.index(end, i)].split())

    @pytest.mark.parametrize("name", sorted(_BODIES))
    def test_the_self_host_surface_list_is_the_scripts(self, pt, name):
        step = self._step(name)
        i = step.index("Espalier-Harness tree")
        listed = step[i:step.index("engine code", i)].split("`")[1::2]
        roots = {t for t in listed if t.endswith("/") and " " not in t}
        assert roots == set(pt._REVIEW_PREFIXES) | set(pt._FULL_PREFIXES) | {pt._ENGINE_PREFIX}

    @pytest.mark.parametrize("name", sorted(_BODIES))
    def test_the_body_kinds_the_prose_names_are_the_scripts(self, pt, name):
        """The bodies say which bodies earn both reviewers; the script's
        `_BODY_PREFIXES` decide it. A workflow body once counted in the script
        and not in the prose (failure-mode review, 2026-10-16)."""
        step = self._step(name)
        i = step.index("a command / ")
        kinds = set(step[i + len("a "):step.index(" body", i)].split(" / "))
        assert kinds == {prefix.split("/")[1][:-1] for prefix in pt._BODY_PREFIXES}, kinds

    @pytest.mark.parametrize("name", sorted(_BODIES))
    def test_each_body_cites_the_review_line(self, name):
        step = self._step(name)
        assert "scripts/proof_tier.py" in step and "`review:` line" in step, name


#: Call shapes a gate is spelled with (both reviews and air, 2026-10-16): a
#: quoted script after an interpreter, a `$(...)` inside double quotes, a
#: module run with `-m`, a step's working directory, an Actions expression
#: before the path, an apostrophe in heredoc prose ahead of a call, and a
#: JavaScript action's entry point; and the shapes that stay data (printed
#: text, a test's operand).
_CALL_SHAPES_WORKFLOW = """name: ci
on: push
jobs:
  t:
    runs-on: ubuntu-latest
    steps:
      - run: python "scripts/quoted_call.py" --x
      - run: tier="$(python scripts/substituted.py --quiet || echo full)"
      - run: printf 'scripts/printed.py'; echo scripts/echoed.py
      - run: if [ -f scripts/tested.py ]; then true; fi
      - run: python -m tools.module_main
      - run: python gate.py
        working-directory: scripts
      - run: python ${{ github.workspace }}/scripts/expression.py
      - run: |
          cat <<EOF
          Don't stop
          EOF
          python scripts/after_apostrophe.py
      - uses: ./tools/js_action
"""
_CALLED = ("scripts/quoted_call.py", "scripts/substituted.py", "tools/module_main.py", "scripts/gate.py",
           "scripts/expression.py", "scripts/after_apostrophe.py", "tools/js_action/action.yml",
           "tools/js_action/dist/index.js")
_DATA = ("scripts/printed.py", "scripts/echoed.py", "scripts/tested.py")


def _call_shapes(tmp_path):
    r = tmp_path / "cs"
    files = {rel: "x\n" for rel in _CALLED + _DATA}
    files[".github/workflows/ci.yml"] = _CALL_SHAPES_WORKFLOW
    files["tools/js_action/action.yml"] = "name: js\nruns:\n  using: node20\n  main: dist/index.js\n"
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text, encoding="utf-8")
    return r


def _hooked(tmp_path):
    """A scratch tools/cc/ whose one hook loads modules every way a hook does."""
    r = tmp_path / "hk"
    files = {
        "tools/cc/hooks/h.py": (
            "import _imported\n"
            "from _from_imported import x\n"
            "from pathlib import Path\n"
            "p = Path(__file__).resolve().parent.parent / 'by_path.py'\n"
            "_load_beside_hooks('beside.py', 'alias')\n"
        ),
        "tools/cc/_imported.py": "import _transitive\n",
        "tools/cc/_from_imported.py": "x = 1\n",
        "tools/cc/by_path.py": "",
        "tools/cc/beside.py": "",
        "tools/cc/_transitive.py": "",
        "tools/cc/unloaded.py": "",
    }
    for rel, text in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text, encoding="utf-8")
    return r


class TestWhatAHookOrAGateReads:
    """The fix batch of both reviews (2026-10-16), under air's three answers:
    a hook is tools/cc/hooks/ and every tools/cc module a hook loads, derived;
    the configuration a hook or a gate reads earns both; a quoted script after
    an interpreter and a `$(...)` inside double quotes are calls, printed text
    and a test's operand are not; a mirror-registry source earns its mirrors'
    class; what cannot be read reads both."""

    def test_every_module_a_hook_loads_is_derived(self, pt, tmp_path):
        r = _hooked(tmp_path)
        assert set(pt.hook_loaded_files(r)) == {
            "tools/cc/_imported.py", "tools/cc/_from_imported.py", "tools/cc/by_path.py",
            "tools/cc/beside.py", "tools/cc/_transitive.py"}
        assert pt.review(["tools/cc/_transitive.py"], r) == (
            "both", [("tools/cc/_transitive.py", "loaded by a hook: tools/cc/_imported.py loads it")])
        assert pt.review(["tools/cc/unloaded.py"], r)[0] == "code-reviewer"

    def test_the_live_hooks_load_the_bounded_spawn(self, pt):
        """`_hook_utils.py` imports `_json_safe`: a break there refused every
        tool call on 2026-10-16, so the module reads as a hook does."""
        assert pt.review(["tools/cc/_json_safe.py"], REPO_ROOT)[0] == "both"

    @pytest.mark.parametrize("line,expected", [
        ("build/", "code-reviewer"),
        (".claude/settings.json", "both"),
    ])
    def test_the_kill_switch_line_of_gitignore_is_a_gates(self, pt, tmp_path, line, expected):
        r = _repo(tmp_path)
        _commit(r, ".gitignore", "build/\n.claude/settings.json\n")
        (r / ".gitignore").write_text(
            "build/\n.claude/settings.json\n".replace(line + "\n", ""), encoding="utf-8")
        assert pt.review([".gitignore"], r)[0] == expected
        subprocess.run(_git(r) + ["commit", "-qam", "drop"], check=True, capture_output=True)
        assert pt.review([".gitignore"], r, base="HEAD~1")[0] == expected

    def test_the_call_shapes_join_and_the_data_shapes_do_not(self, pt, tmp_path):
        named = pt.workflow_named_files(_call_shapes(tmp_path))
        assert set(named) == set(_CALLED)
        assert named["tools/js_action/dist/index.js"] == "tools/js_action/action.yml"

    def test_the_gates_ci_rests_on_stay_named_on_this_tree(self, pt):
        """A floor, not the set: the scripts the required cells and the
        release run, each named by a workflow today."""
        named = set(pt.workflow_named_files(REPO_ROOT))
        assert {"scripts/proof_tier.py", "tools/cc/ci_guard.py", "scripts/release_check.py",
                "bench/run_benchmark.py", "tools/review_agent_audit.py"} <= named, sorted(named)

    def test_every_mirror_source_earns_at_least_its_mirrors_review(self, pt):
        """`espalier/assets/github/workflows/harness-guard.yml` is the source of
        the merge gate's workflow (a SOT_IS_PACKAGED row) and read none until
        the review; every row of the registry is held to the order."""
        from tests._git_oracle import require_tracked_paths
        tracked = require_tracked_paths(REPO_ROOT, minimum=1000, what="the tree the mirror rows read")
        rows = pt._mirror_rows(REPO_ROOT, False)
        assert any(sot == "espalier/assets/github/workflows/harness-guard.yml" for sot, _ in rows), rows
        for sot, mirrors in rows:
            source = sot if not sot.endswith("/") else next(p for p in tracked if p.startswith(sot))
            for mirror in mirrors:
                image = mirror + source[len(sot):] if sot.endswith("/") else mirror
                assert pt.REVIEWS.index(pt.review([source], REPO_ROOT)[0]) >= \
                    pt.REVIEWS.index(pt.review([image], REPO_ROOT)[0]), (source, image)

    def test_an_unresolved_base_reads_both_never_fewer(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        assert pt.main(["--root", str(r), "--base", "no-such-ref", "--tier", "full", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["review"] == "both"
        assert data["review_earned_by"][0]["path"] == "(the diff)"

    def test_base_mode_names_the_uncommitted_paths_it_leaves_out(self, pt, tmp_path, capsys):
        r = _repo(tmp_path)
        _commit(r, "docs/X.md")
        (r / "tools" / "cc" / "hooks" / "h.py").write_text("uncommitted\n", encoding="utf-8")
        assert pt.main(["--root", str(r), "--base", "HEAD~1"]) == 0
        out = capsys.readouterr().out
        assert "review: none" in out
        assert "note: 1 uncommitted path(s) are outside the --base diff" in out
        assert "tools/cc/hooks/h.py" in out

    def test_a_staged_rename_reads_as_both_its_paths(self, pt, tmp_path):
        """Under `-z` a rename's original path is a field of its own after the
        new one, and it counts too: the rename deletes it, and the `--base`
        diff (`--no-renames`) reads the same change as a delete beside an add.
        Read as the new path alone, a hook moved out of tools/cc/ earned the
        contract tier locally and a renamed doc's readers stayed off the line
        (failure-mode review, DEF-5042)."""
        r = _repo(tmp_path)
        subprocess.run(_git(r) + ["mv", "tools/cc/hooks/h.py", "scripts/h.py"], check=True, capture_output=True)
        changed, untracked = pt.changed_paths(r)
        assert (changed, untracked) == (["tools/cc/hooks/h.py", "scripts/h.py"], [])   # git's old -> new
        assert pt.tier(changed) == "full"

    @pytest.mark.parametrize("name", ["my hook.py", "né.py"])
    def test_a_changed_path_is_read_as_written(self, pt, tmp_path, name):
        """`git status --porcelain` quotes a path with a space or a non-ASCII
        character unless asked for `-z`."""
        r = _repo(tmp_path)
        _commit(r, f"tools/cc/hooks/{name}", "one\n")
        (r / "tools" / "cc" / "hooks" / name).write_text("two\n", encoding="utf-8")
        changed, _untracked = pt.changed_paths(r)
        assert changed == [f"tools/cc/hooks/{name}"]
        assert pt.tier(changed) == "full"
        assert pt.review(changed, r)[0] == "both"
