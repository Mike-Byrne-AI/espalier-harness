"""Tests for the >=3.11 interpreter floor — `espalier/_python_floor.py` and its
parity twin in `tools/cc/hooks/_hook_utils.py` (TP-448 Class 3 / DEF-636).

Pins the defect that produced this module. `pyproject.toml` declares
`requires-python = ">=3.10"` while three interpreter probes tested only
`.startswith("Python 3.")`. On a host whose `python3` is stock
`/usr/bin/python3` — 3.9.6 on every macOS through Sequoia — `init` wrote that
name into 13 hook-command sites, `doctor` reported the resolver healthy, and the
hooks ran. `tools/cc/cognitive_blueprint.py` did not: its `match args.action:`
is 3.10+ syntax, so the blueprint chain, Gate 4 finalize and subagent-reasoning
capture raised SyntaxError every session while every blocking guard kept
working. Nothing visibly failed; SessionStart just said "No active blueprint"
forever.

⚠ **The mutation these tests must catch**, driven before they were trusted
(`STANDING_PRINCIPLES` §19): replace either copy's `meets_python_floor` body
with the pre-fix predicate — `return version_output.startswith("Python 3.")` —
and `test_the_pre_fix_predicate_is_rejected` plus the three site tests must red.
A floor whose derivation can be deleted while the suite stays green is not a
floor.
"""
from __future__ import annotations

import ast
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from espalier import _python_floor
from espalier.harness_config import GOVERNANCE_BLOCKING_HOOKS
from tests._cut_start import skip_if_cut
from tests._stubs import write_stub
from tests._wait_budget import scaled

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _hook_utils():
    """Import the hook-side twin the way a hook does — flat, on sys.path."""
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    import _hook_utils  # type: ignore[import-not-found]
    return _hook_utils


def _load_tools_cc(name: str):
    """Load ``tools/cc/<name>.py`` by file path: a plain import would drag the
    engine into the zero-import graph of a standalone script."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"_floor_parity_{name}", REPO_ROOT / "tools" / "cc" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The cases that separate the floor from the identity probe. `Python 3.9.6` is
# the whole defect: a TRUE Python 3 that this package does not run on.
FLOOR_CASES = [
    ("Python 3.14.0", True),
    ("Python 3.11.0", True),
    ("Python 3.11", True),
    ("Python 3.14.0rc1", True),
    ("Python 4.0.0", True),
    ("Python 3.10.12", False),  # the dropped floor: a Python 3 this package no longer runs on
    ("Python 3.10", False),
    ("Python 3.9.6", False),
    ("Python 3.9", False),
    ("Python 3.0.1", False),
    ("Python 2.7.18", False),
    ("", False),
    ("bash: python3: command not found", False),
    ("Python", False),
]


class TestPythonFloor:
    @pytest.mark.parametrize("version_output,expected", FLOOR_CASES)
    def test_meets_python_floor(self, version_output, expected):
        assert _python_floor.meets_python_floor(version_output) is expected

    def test_the_pre_fix_predicate_is_rejected(self):
        """The discriminating case, stated as the mutation it must catch.

        `startswith("Python 3.")` accepts every string in this list; the floor
        accepts only the first. If this ever passes under the old predicate,
        the mutation went undetected.
        """
        accepted_by_both = "Python 3.14.0"
        accepted_only_by_the_old_predicate = ["Python 3.9.6", "Python 3.9", "Python 3.0.1"]
        assert _python_floor.meets_python_floor(accepted_by_both)
        for said in accepted_only_by_the_old_predicate:
            assert said.startswith("Python 3."), "case does not exercise the mutation"
            assert not _python_floor.meets_python_floor(said), (
                f"{said!r} clears the floor -- the floor comparison is gone and "
                f"the predicate has decayed back to startswith('Python 3.')"
            )

    def test_min_python_matches_requires_python(self):
        """Derive the floor from `pyproject.toml`, don't trust a typed copy.

        `STANDING_PRINCIPLES` §14. If someone raises `requires-python` to 3.11
        and leaves `MIN_PYTHON` at 3.10, the package refuses to install on a
        host the harness would still happily wire.
        """
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'requires-python\s*=\s*"[><=~^ ]*(\d+)\.(\d+)', text)
        assert match, "could not read requires-python from pyproject.toml"
        declared = (int(match.group(1)), int(match.group(2)))
        assert _python_floor.MIN_PYTHON == declared, (
            f"MIN_PYTHON is {_python_floor.MIN_PYTHON} but pyproject.toml "
            f"declares requires-python >= {declared[0]}.{declared[1]}"
        )

    def test_floor_text_is_the_only_rendering(self):
        """Messages must interpolate the floor, never spell it.

        A message quoting "3.10" beside a constant that says 3.11 is the
        restated-number defect one level up.
        """
        assert _python_floor.floor_text() == ".".join(
            str(p) for p in _python_floor.MIN_PYTHON
        )


# The banner cases that separate "a Python 3 that is too old" from "not a
# Python 3 at all". `Python 2.7.18` is DEF-727: it parses, so a gate written as
# `parse_python_version(...) is not None` admitted it as below-floor and promised
# the operator that the blocking guards keep working -- on the one host where
# they cannot (Python 2 cannot parse the hook scripts).
BELOW_FLOOR_CASES = [
    ("Python 3.9.6", True),
    ("Python 3.9", True),
    ("Python 3.0.1", True),
    ("Python 3.10.12", True),   # the dropped floor
    ("Python 3.11.0", False),   # clears the floor: not below it
    ("Python 3.14.0", False),
    ("Python 4.0.0", False),
    ("Python 2.7.18", False),   # the defect: parses, is not a Python 3
    ("Python 2.7", False),
    ("", False),
    ("bash: python: command not found", False),
    ("Python", False),
]


# Identity read off the banner's MAJOR -- the ONE rule the two PATH-probing
# identity probes and the floor share. The prefixed banner is the case that
# split them (DEF-727 failure-mode review): `startswith("Python 3.")` on the
# stripped output said "not a Python 3" while the floor parser, searching
# anywhere, said "a Python 3 below the floor".
IDENTITY_CASES = [
    ("Python 3.14.0", True),
    ("Python 3.10", True),
    ("Python 3.9.6", True),
    ("  Python 3.10.0", True),
    ("Activating environment...\nPython 3.9.6", True),
    ("Python 2.7.18", False),
    ("Python 4.0.0", False),
    ("", False),
    ("bash: python: command not found", False),
    ("Python", False),
]


class TestBelowFloorPython3Banner:
    """`_python_floor.is_below_floor_python3` -- the classifier both cli
    decision sites route through (`DEF-727`) -- and `is_python3_banner`, the
    identity rule it is defined from."""

    @pytest.mark.parametrize("version_output,expected", IDENTITY_CASES)
    def test_is_python3_banner(self, version_output, expected):
        assert _python_floor.is_python3_banner(version_output) is expected

    def test_below_floor_is_defined_from_identity_and_the_floor(self):
        """The definitional identity over every banner this module is tested
        on: below-floor is exactly "a Python 3 banner that fails the floor". A
        third reading of the banner cannot creep in without reddening this."""
        for said, _ in FLOOR_CASES + BELOW_FLOOR_CASES + IDENTITY_CASES:
            ident = _python_floor.is_python3_banner(said)
            meets = _python_floor.meets_python_floor(said)
            assert _python_floor.is_below_floor_python3(said) is (ident and not meets), said

    @pytest.mark.parametrize("version_output,expected", BELOW_FLOOR_CASES)
    def test_is_below_floor_python3(self, version_output, expected):
        assert _python_floor.is_below_floor_python3(version_output) is expected

    def test_the_parse_succeeds_gate_is_rejected(self):
        """The mutation this catches, stated as the predicate it replaced:
        `parse_python_version(said) is not None` is True for every Python 2
        banner. If a Python 2 banner ever reads as below-floor again, the
        classifier has decayed back to that gate."""
        for said in ("Python 2.7.18", "Python 2.7", "Python 2.6.9"):
            assert _python_floor.parse_python_version(said) is not None, (
                "case does not exercise the mutation"
            )
            assert not _python_floor.is_below_floor_python3(said), (
                f"{said!r} reads as a below-floor Python 3 -- the gate has "
                f"decayed back to parse_python_version(...) is not None"
            )

    def test_below_floor_is_the_gap_between_identity_and_floor(self):
        """Below-floor is exactly "a Python 3 banner that fails the floor":
        never True where `meets_python_floor` is, never True for a banner
        that is not Python 3."""
        for said, _ in FLOOR_CASES + BELOW_FLOOR_CASES:
            below = _python_floor.is_below_floor_python3(said)
            meets = _python_floor.meets_python_floor(said)
            parsed = _python_floor.parse_python_version(said)
            assert not (below and meets), said
            if below:
                assert parsed is not None and parsed[0] == 3, said


class TestTwoCopyParity:
    """`tools/cc/` may not import espalier, so the floor exists twice."""

    def test_min_python_two_copy_parity(self):
        assert _hook_utils().MIN_PYTHON == tuple(_python_floor.MIN_PYTHON), (
            "the hook-side floor and the engine-side floor disagree; a hook "
            "would bless an interpreter the engine refuses, or the reverse"
        )

    def test_package_entry_floor_is_the_third_copy(self):
        """`espalier/__init__.py` holds the engine's own floor sentence, which
        must run before `_python_floor` (or anything else) is compiled, so it
        spells the floor as a literal: the third copy. Read from the source
        with ast rather than by importing the package, whose import already
        ran under this interpreter and so tests nothing about the literal."""
        tree = ast.parse((REPO_ROOT / "espalier" / "__init__.py").read_text(encoding="utf-8"))
        floors = [ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_FLOOR" for t in node.targets)]
        assert floors == [tuple(_python_floor.MIN_PYTHON)], (
            f"espalier/__init__.py's _FLOOR is {floors!r}, the floor is "
            f"{tuple(_python_floor.MIN_PYTHON)!r}: the package entry would let a "
            f"below-floor interpreter on, or turn a supported one away"
        )

    def test_start_refusal_floor_is_the_fourth_copy(self):
        """`tools/cc/hooks/_start_refusal.py` is the module each deny hook
        imports first and alone, so its floor check cannot read
        `_hook_utils.MIN_PYTHON` (the module that may not import below the
        floor) and spells the floor as a literal: the fourth copy (TP-706
        2-C). Read with ast, as the third is."""
        tree = ast.parse((HOOKS_DIR / "_start_refusal.py").read_text(encoding="utf-8"))
        floors = [ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_FLOOR" for t in node.targets)]
        assert floors == [tuple(_python_floor.MIN_PYTHON)], (
            f"_start_refusal.py's _FLOOR is {floors!r}, the floor is "
            f"{tuple(_python_floor.MIN_PYTHON)!r}: the deny hooks would refuse a "
            f"supported interpreter, or let a dropped one judge calls"
        )

    @pytest.mark.parametrize("version_output,expected", IDENTITY_CASES)
    def test_banner_identity_two_copy_parity(self, version_output, expected):
        hook_side = _hook_utils().is_python3_banner(version_output)
        engine_side = _python_floor.is_python3_banner(version_output)
        assert hook_side == engine_side == expected, (
            f"banner identity disagrees on {version_output!r}: "
            f"hook={hook_side} engine={engine_side}"
        )

    @pytest.mark.parametrize("version_output,expected", FLOOR_CASES)
    def test_predicate_two_copy_parity(self, version_output, expected):
        hook_side = _hook_utils().meets_python_floor(version_output)
        engine_side = _python_floor.meets_python_floor(version_output)
        assert hook_side == engine_side == expected, (
            f"floor predicates disagree on {version_output!r}: "
            f"hook={hook_side} engine={engine_side}"
        )

    def test_launcher_version_flag_four_copy_parity(self):
        """The launcher's version flag is recognised in the engine, the hooks,
        the zero-import CI guard and the ledger probe runner; one pattern,
        four copies, held equal -- and none of them admits `-2`, which selects
        a Python 2 that cannot parse a hook."""
        ci_guard = _load_tools_cc("ci_guard")
        probes = _load_tools_cc("check_ledger_probes")
        patterns = {
            "engine": _python_floor.LAUNCHER_VERSION_FLAG.pattern,
            "hooks": _hook_utils().LAUNCHER_VERSION_FLAG.pattern,
            "ci_guard": ci_guard._CI_LAUNCHER_VERSION_FLAG.pattern,
            "probe_runner": probes._LAUNCHER_VERSION_FLAG.pattern,
        }
        assert not _python_floor.LAUNCHER_VERSION_FLAG.fullmatch("-2"), patterns
        assert len(set(patterns.values())) == 1, patterns
        from espalier import cli
        assert _hook_utils().LAUNCHER_SPELLING == cli.LAUNCHER_CANDIDATE, (
            "the orientation line and init name different launcher spellings"
        )

    @pytest.mark.parametrize("spelling,argv", [
        ("py -3", ["py", "-3"]),
        ("py -3.11-64", ["py", "-3.11-64"]),
        ("C:\\Windows\\py.exe -3", ["C:\\Windows\\py.exe", "-3"]),
        ("python3", ["python3"]),
        ("py", ["py"]),
        ("py -c", ["py -c"]),             # not a version flag: not a launcher spelling
        ("py -3 x.py", ["py -3 x.py"]),   # more than one argument: not a spelling
        ("python3 -3", ["python3 -3"]),   # a flag only the launcher consumes
        ("py -2", ["py -2"]),             # a Python 2 selector is not a spelling
        ("PY.EXE -3", ["PY.EXE", "-3"]),
        # split at the LAST space, so a spaced launcher path still splits:
        ("C:\\Program Files\\Python Launcher\\py.exe -3",
         ["C:\\Program Files\\Python Launcher\\py.exe", "-3"]),
        ("C:\\Program Files\\Python311\\python.exe", ["C:\\Program Files\\Python311\\python.exe"]),
    ])
    def test_interpreter_argv_two_copy_parity(self, spelling, argv):
        assert _python_floor.interpreter_argv(spelling) == argv
        assert _hook_utils().interpreter_argv(spelling) == argv

    def test_both_floor_probes_run_the_launcher_spelling(self, tmp_path, monkeypatch):
        """On a launcher-only host `py -3` is the one interpreter that runs, and
        a probe that resolved the whole spelling as one name read it as absent."""
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_host(tmp_path, hosts.LAUNCHER_ONLY)
        monkeypatch.setenv("PATH", str(bin_dir))
        hook_utils = _hook_utils()
        monkeypatch.setattr(hook_utils, "_INTERPRETER_IDENTITY_MEMO", {})
        for probe in (_python_floor.interpreter_meets_floor, hook_utils.interpreter_meets_floor):
            assert probe("py -3") is True, probe.__module__
            assert probe("python") is False, probe.__module__
            assert probe("python3") is False, probe.__module__

    def test_no_samefile_shortcircuit_in_either_floor_probe(self):
        """The identity probe short-circuits on `sys.executable`; the floor
        probe must NOT, and this is the one place that difference is pinned.

        A hook spawned BY a 3.9 interpreter would short-circuit to True and
        bless exactly the host the check exists to catch — the check assuming
        its own answer. Read as AST so a comment mentioning `samefile` does not
        satisfy it.
        """
        # doctor's seam is an ALIAS of the engine implementation (a wrapper
        # read as a re-implementation by the sister-site probe), so the pin
        # sits on the two bodies that exist -- and the seam is held to the
        # pinned one by identity below.
        from espalier import _python_floor, doctor

        assert doctor._interpreter_meets_floor is _python_floor.interpreter_meets_floor, (
            "doctor._interpreter_meets_floor no longer IS the pinned engine "
            "implementation; if it grew a body of its own, inspect that body here too"
        )
        for path, func in (
            (REPO_ROOT / "espalier" / "_python_floor.py", "interpreter_meets_floor"),
            (HOOKS_DIR / "_hook_utils.py", "interpreter_meets_floor"),
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = [
                n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == func
            ]
            assert found, f"{func} not found in {path.name}"
            names = {
                n.attr for n in ast.walk(found[0]) if isinstance(n, ast.Attribute)
            }
            assert "samefile" not in names, (
                f"{path.name}::{func} short-circuits on sys.executable; the "
                f"floor question cannot be answered by assuming it"
            )


class TestFloorAtTheThreeDecisionSites:
    """The floor has to be wired in, not merely defined."""

    @staticmethod
    def _stub(tmp_path: Path, name: str, says: str) -> Path:
        return write_stub(tmp_path / name, f"#!/bin/sh\necho '{says}'\n")

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_detect_python_command_refuses_a_below_floor_host(
        self, tmp_path, monkeypatch, capsys
    ):
        """A below-floor host must get a RESOLVABLE name wired, plus a loud warning.

        ⚠ This test previously asserted the opposite (`!= "python3"`), and that
        contract was WRONG in a way an adversarial pass had to drive out. On a
        stock macOS -- `python3` is 3.9.6 and there is no `python` at all --
        refusing 3.9 fell through to the literal `"python"`, which is
        command-not-found there. Every hook then exited outside the `{0, 2}`
        decision range, and a non-decision is NON-BLOCKING: **every blocking
        guard failed OPEN**. The floor traded "blueprints dead, enforcement
        intact" for "enforcement dead", which is the worse half.

        Operator decision (2026-09-03): wire it and warn loudly. So the
        assertion that matters is not which name comes back but that the name
        RESOLVES -- a name that does not is what disarms the harness.

        Positive control in the same test: the identical stub reporting 3.14 is
        returned silently, so a green cannot come from the probe failing to run.
        """
        import shutil as _shutil

        from espalier import cli

        self._stub(tmp_path, "python3", "Python 3.9.6")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        got = cli._detect_python_command()
        assert _shutil.which(got) is not None, (
            f"_detect_python_command returned {got!r}, which does not resolve on "
            f"this PATH. Every hook wired to it is command-not-found, exits "
            f"outside {{0, 2}}, and every blocking guard fails OPEN."
        )
        assert got == "python3", (
            "the below-floor interpreter that DOES resolve is still the ANSWER "
            "(the read-only callers name it); no command writes it -- "
            "TestADroppedPythonIsRefusedBeforeAnyWrite pins the refusal"
        )
        warning = capsys.readouterr().err
        # The 2026-11-07 ruling: the one sentence, naming the version found
        # and the floor, and never the 2026-09-03 promise that it is wired.
        assert "The harness does not run on Python 3.9.6 (python3 at " in warning, warning
        floor = _python_floor.floor_text()
        assert (f"Update to Python {floor} or newer to install and use it, or put a "
                f"Python {floor} or newer on PATH as python3 or python.") in warning, warning
        assert "anyway" not in warning and "keep working" not in warning, (
            f"the warning still promises a wired, working below-floor "
            f"interpreter: {warning!r}"
        )

        self._stub(tmp_path, "python3", "Python 3.14.0")
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        capsys.readouterr()
        assert cli._detect_python_command() == "python3"
        assert capsys.readouterr().err == "", (
            "CONTROL FAILED: a conforming 3.14 stub still warned, so the "
            "warning above proves nothing about the floor"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_detect_python_command_does_not_promise_working_guards_on_python_2(
        self, tmp_path, monkeypatch, capsys
    ):
        """Python 2 must not be described as a below-floor Python 3.

        `below_floor` is documented as "A WORKING Python 3 that is merely too
        OLD", and the warning it drives says the blocking guards keep working.
        That is TRUE on 3.9 -- the case the test above pins -- and FALSE on 2.7,
        which cannot parse the hook scripts at all. The gate admits Python 2
        because it tests `parse_python_version(...) is not None`, and that
        parser matches any `Python X.Y` banner, Python 2 included.

        Driven on a real Windows host 2026-09-09 (Windows install walk 2):
        `init` printed "Wiring it anyway so the blocking guards keep working"
        and then "Hooks now intercept Claude Code tool calls", while the wired
        hook command exited 0 with non-JSON stdout -- a non-decision, which is
        NON-BLOCKING, so every blocking guard failed OPEN. `doctor` on the same
        tree reported the opposite ("each guard fails OPEN while init reports
        success"), so the correct classification already exists in-tree at
        `doctor._interpreter_is_python3`.

        This asserts the message's TRUTH, not a substring of it: the three
        assertions in the test above are all satisfied verbatim by a Python 2
        banner, so a fixture alone does not catch this.

        ⚠ Sibling site carrying the same predicate:
        `cli._warn_interpreter_unvalidated`.

        Filed as a strict xfail (2026-09-09) rather than left red: a standing
        red trips `/preflight` and `stop_gate` Gate 1 in every session until
        the fix lands, which is how a true test gets deleted. The marker came
        off on 2026-09-10 when `_python_floor.is_below_floor_python3` replaced
        the parse-succeeds gate at both cli sites (`DEF-727`) -- the same shape
        that closed `DEF-414b` (see `tests/test_write_guard_command_position.py`,
        the DEF-414b note above the wrapper roster, where the strict xfail
        "fired the day it closed -- exactly what it was for").
        """
        from espalier import cli

        self._stub(tmp_path, "python", "Python 2.7.18")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        # Assert the DECISION, not the prose. A substring test on the warning
        # text would XPASS on a reword with the defect fully intact, and the
        # marker's stated contract ("fails the suite the day the predicate is
        # narrowed") would then be false. `_warn_interpreter_below_floor` is
        # call-then-return at the tail of `_detect_python_command`, so recording it
        # does not alter flow.
        below_floor_calls: list = []
        monkeypatch.setattr(
            cli, "_warn_interpreter_below_floor", below_floor_calls.append
        )
        cli._detect_python_command()
        assert not below_floor_calls, (
            f"a Python 2 interpreter was routed to _warn_interpreter_below_floor, "
            f"whose contract is 'a WORKING Python 3 that is merely too OLD' -- so "
            f"the operator is promised surviving enforcement on a host where "
            f"Python 2 cannot parse the hook scripts at all and every blocking "
            f"guard fails OPEN: {below_floor_calls!r}"
        )

    def test_the_two_python_2_admitting_predicates_are_narrowed_together(self):
        """`cli.py` carries the Python-2-admitting predicate at TWO sites, and
        the fix is a class, not a site (CLAUDE.md Core Rule 12).

        `_detect_python_command` decides whether to call
        `_warn_interpreter_below_floor`; `_warn_interpreter_unvalidated`
        decides which headline to print -- and it is the function the
        `_detect_python_command` fix routes Python 2 INTO. Both gate on
        `parse_python_version(...) is not None`, which matches a `Python 2.x`
        banner. Narrow one and Python 2 stops being called a below-floor
        Python 3 at the first site and starts being called one at the second.

        This is the sister-site pin the strict xfail above cannot be: when
        `_detect_python_command` is narrowed the xfail flips green and its marker
        comes off, and nothing else in the suite would say
        `_warn_interpreter_unvalidated` is still wrong. Counting
        both sites reds on exactly that half-fix.

        Zero is the fixed state (landed 2026-09-10). One was the half-fix and
        two the defect at both sites; the pin accepted two while the row was
        open and accepts nothing but zero now, so a "simplification" back to
        the inline gate at both sites reds here as well as in the behavioural
        tests above.
        """
        text = (Path(__file__).resolve().parents[1] / "espalier" / "cli.py").read_text(
            encoding="utf-8"
        )
        hits = re.findall(r"parse_python_version\([^)]*\)\s+is not None", text)
        assert len(hits) == 0, (
            f"the Python-2-admitting predicate is back in cli.py at {len(hits)} "
            f"site(s): {hits!r}. Both decision sites route through "
            f"_python_floor.is_below_floor_python3 (DEF-727); one hit is the "
            f"half-fix that classifies Python 2 inconsistently between the "
            f"warning that fires and the headline it prints, two is the defect "
            f"at both sites."
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_python_2_stub_is_actually_reached_by_the_detector(
        self, tmp_path, monkeypatch, capsys
    ):
        """POSITIVE CONTROL for the strict-xfail test above. Not itself xfail.

        The xfail above asserts a NEGATIVE ("was not routed to below_floor").
        A negative passes vacuously whenever the probe stops running at all --
        the once-per-process latch pre-set elsewhere, the `sh` stub failing to
        resolve, the resolver gaining memoisation. Under `xfail(strict=True)` a
        broken probe then XPASSes, the suite reds, and the marker's own text
        says "delete the marker" -- so "probe broken" reads as "fix landed".

        This control fails LOUDLY in that case, in its own non-xfail test:
        the stub is found, and the detector says something about it. Both hold
        today AND after the predicate is narrowed (Python 2 routes to
        `_warn_interpreter_unvalidated`, which also writes to stderr), so this
        test does not need to change when the defect is fixed.
        """
        from espalier import cli

        self._stub(tmp_path, "python", "Python 2.7.18")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        got = cli._detect_python_command()
        warning = capsys.readouterr().err
        assert got == "python", (
            f"CONTROL FAILED: the Python 2 stub was not the detector's answer "
            f"({got!r}), so the xfail above is asserting its negative over a "
            f"code path that never ran"
        )
        assert "2.7.18" in warning, (
            f"CONTROL FAILED: the detector's warning does not quote the stub's "
            f"own banner, so the stub was never probed -- both warning paths "
            f"echo the probe's reported version, and only the no-probe path "
            f"(\"no interpreter answered\") omits it. The xfail above is then "
            f"asserting its negative over a branch that never ran, and under "
            f"strict xfail that reds the suite as if the fix had landed. "
            f"Returning 'python' does NOT rule this out: the unvalidated "
            f"fallback returns the same literal name. Warning was: {warning!r}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_the_warning_quotes_the_first_candidate_that_answered(
        self, tmp_path, monkeypatch, capsys
    ):
        """DEF-804: the evidence in the unvalidated warning is FIRST-wins, like
        `last_resort` and `below_floor` beside it. It used to be assigned on
        every iteration -- last-wins -- so on the Windows walk 3 host (2026-09-14)
        with both `RESOLVER_CANDIDATES` resolving the warning quoted `python3`,
        the Store alias's "Python was not found", and discarded the Python 2
        evidence from `python`: the operator was told the wrong thing about the
        wrong interpreter. No fixture in the suite planted two candidates before
        this one. RED on HEAD: the warning named `python3`."""
        from espalier import cli

        assert cli.RESOLVER_CANDIDATES == ("python", "python3"), (
            "this fixture plants both probed names in the resolver's own order; "
            "re-derive it if the candidate roster changes"
        )
        self._stub(tmp_path, "python", "Python 2.7.18")
        self._stub(
            tmp_path, "python3",
            "Python was not found; run without arguments to install from the Microsoft Store",
        )
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        got = cli._detect_python_command()
        warning = capsys.readouterr().err
        assert got == "python", got
        assert "'python' resolves to" in warning and "Python 2.7.18" in warning, (
            f"the warning must quote the FIRST candidate that answered and its "
            f"evidence:\n{warning}"
        )
        assert "'python3' resolves to" not in warning and "Microsoft Store" not in warning, (
            f"the LAST candidate's evidence displaced the first's:\n{warning}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_probe_that_raised_yields_to_the_next_candidates_banner(
        self, tmp_path, monkeypatch, capsys
    ):
        """DEF-804, the code review's corner: first-wins over EVERY probe would
        quote a synthetic `probe failed: FileNotFoundError` from a candidate
        whose shim is dead (a shebang pointing nowhere) and discard the next
        candidate's real banner. The first BANNER is the evidence; a failed
        probe is kept only as the evidence of last resort."""
        from espalier import cli

        dead = tmp_path / "python"
        dead.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
        dead.chmod(dead.stat().st_mode | stat.S_IEXEC)
        self._stub(tmp_path, "python3", "Python 2.7.18")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._detect_python_command()
        warning = capsys.readouterr().err
        assert "'python3' resolves to" in warning and "Python 2.7.18" in warning, warning
        assert "probe failed" not in warning, warning

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_lone_failed_probe_is_still_reported(
        self, tmp_path, monkeypatch, capsys
    ):
        """The fallback leg of the test above: when NO candidate answered
        with a banner, the failed probe is the only evidence and is quoted."""
        from espalier import cli

        dead = tmp_path / "python"
        dead.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
        dead.chmod(dead.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._detect_python_command()
        warning = capsys.readouterr().err
        assert "'python' resolves to" in warning and "probe failed:" in warning, warning

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_when_nothing_clears_the_floor_no_interpreter_is_spelled(
        self, tmp_path, monkeypatch, capsys
    ):
        """DEF-805's third state (the failure-mode review): a fusion driven
        under a below-floor interpreter has no interpreter to spell -- the
        resolver's answer is the failed candidate and `sys.executable` fails
        the floor too. The warning must say install first, never spell the
        broken name before `-m espalier`."""
        from espalier import cli

        stub = self._stub(tmp_path, "python3", "Python 3.9.6")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(sys, "executable", str(stub))
        # The running interpreter's own banner is read, not spawned (DEF-5015):
        # running under the 3.9 is what this models, so it reads 3.9 too.
        monkeypatch.setattr(_python_floor, "_running_interpreter_banner",
                            lambda: "Python 3.9.6", raising=False)
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._detect_python_command()
        warning = capsys.readouterr().err
        assert warning.count("WARNING:") == 1, warning
        assert "python3 -m espalier" not in warning, warning
        assert "no command can be spelled yet" in warning and "--rewire-interpreter" in warning, warning

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_the_below_floor_remedy_is_spelled_with_an_interpreter_that_can_run_it(
        self, tmp_path, monkeypatch, capsys
    ):
        """DEF-805, the residue of DEF-758: `_warn_interpreter_below_floor`
        spelled its `-m espalier init . --rewire-interpreter` with `name`, the
        candidate that had just failed the floor -- the one interpreter that
        cannot run the command -- because the DEF-758 pin keyed on names bound
        from a resolver call and this one was unpacked from a parameter. Now it
        spells `_remedy_py()`: on this host the resolver's answer is the 3.9
        stub, which fails the floor, so the remedy is the interpreter running
        the test. And the warning prints ONCE: `_remedy_py()` re-runs the
        resolver, which reaches the warner again, and the emitted flag is set
        before the print. RED on HEAD: the remedy said `python3 -m espalier`."""
        from espalier import cli

        self._stub(tmp_path, "python3", "Python 3.9.6")
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        got = cli._detect_python_command()
        warning = capsys.readouterr().err
        assert got == "python3", got
        assert warning.count("WARNING:") == 1, f"the warning must print once:\n{warning}"
        remedy = [line for line in warning.splitlines() if "--rewire-interpreter" in line]
        assert len(remedy) == 1, warning
        # The failed candidate is the bare word `python3`. The interpreter running
        # the test can end in `bin/python3` (`python3 -m pytest`), and the right
        # remedy then contains the substring, so the check anchors on the word.
        assert not re.search(r"(?<![\w./\\-])python3 -m espalier", remedy[0]), (
            f"the remedy is spelled with the interpreter that just failed the floor:\n{remedy[0]}"
        )
        assert f"{cli.quoted_if_spaced(sys.executable)} -m espalier init . --rewire-interpreter" in remedy[0], (
            f"the remedy must spell the interpreter running this command:\n{remedy[0]}"
        )

    def test_unvalidated_warning_does_not_call_python_2_below_floor(
        self, monkeypatch, capsys
    ):
        """The sister site (`DEF-727`): `_warn_interpreter_unvalidated` picks
        its headline with the same classifier. A Python 2 probe must get the
        "could not be validated" headline, because "no Python interpreter on
        PATH meets this package's floor" describes a too-OLD Python 3 and
        sends the operator to upgrade a Python they cannot run the hooks with
        at all. The 3.9 probe is the control: that one IS below-floor."""
        from espalier import cli

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._warn_interpreter_unvalidated(("python", "/stub/python", "Python 2.7.18"))
        py2 = capsys.readouterr().err
        assert "2.7.18" in py2, py2
        assert "could be validated" in py2, (
            f"a Python 2 probe was described as a below-floor Python 3: {py2!r}"
        )
        assert "meets this package's floor" not in py2, py2

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._warn_interpreter_unvalidated(("python3", "/stub/python3", "Python 3.9.6"))
        py39 = capsys.readouterr().err
        assert "meets this package's floor" in py39, (
            f"CONTROL FAILED: a 3.9 probe lost the below-floor headline: {py39!r}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_identity_probes_and_the_floor_agree_on_a_prefixed_banner(self, tmp_path):
        """The two-classifier split the DEF-727 failure-mode review drove: a
        wrapper that echoes a line before its banner read as a Python 3 to
        the floor parser and as not one to both identity probes, so `init`
        said "guards keep working" and "each guard fails OPEN" about one
        interpreter in one run. All three read the banner through one rule."""
        from espalier import doctor as doctor_module

        stub = write_stub(
            tmp_path / "python",
            "#!/bin/sh\necho 'Activating environment...'\necho 'Python 3.9.6'\n",
        )
        banner = subprocess.run(
            [str(stub), "--version"], capture_output=True, text=True, timeout=10, encoding="utf-8",
        ).stdout.strip()
        assert "Activating" in banner, banner  # the stub really prefixes
        assert _python_floor.is_below_floor_python3(banner) is True
        assert doctor_module._interpreter_is_python3(str(stub)) is True, (
            "doctor's identity probe disagrees with the floor about one banner"
        )
        hu = _hook_utils()
        hu._INTERPRETER_IDENTITY_MEMO.clear()
        try:
            assert hu.interpreter_is_python3(str(stub)) is True, (
                "the hook-side identity probe disagrees with the floor about one banner"
            )
        finally:
            hu._INTERPRETER_IDENTITY_MEMO.clear()

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_doctor_reports_a_below_floor_interpreter(self, tmp_path, monkeypatch):
        """`doctor` must distinguish "not Python 3" from "too old" — the
        remedies differ, and the not-Python-3 hint ("symlink -> python3") makes
        the breakage permanent on a 3.9-only host."""
        from espalier import doctor as doctor_module

        stub = self._stub(tmp_path, "python3", "Python 3.9.6")
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python3"}]}]}}',
            encoding="utf-8",
        )
        monkeypatch.setattr(doctor_module.shutil, "which", lambda x, path=None: str(stub))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        issues = doctor_module._check_python_resolver(tmp_path, settings)
        joined = " ".join(issues)
        assert issues, "a below-floor interpreter was reported as healthy"
        assert _python_floor.floor_text() in joined, f"the finding must name the floor: {joined!r}"
        assert "IS Python 3" in joined, (
            f"the finding must not claim it is not a Python 3 -- it is, and the "
            f"remedy differs: {joined!r}"
        )
        # The sentence stays as ruled (doctor names a WIRED interpreter), and
        # the re-wire's hint is keyed on the floor: every name here answers
        # 3.9.6, so the rewire has no target. Read by identity alone, the
        # `python3` arm said "a WORKING `python3` IS on PATH" of that 3.9.6
        # and named a rewire that returns no_target (TP-706).
        floor = _python_floor.floor_text()
        assert (_python_floor.does_not_run_sentence("Python 3.9.6")
                + " Then re-wire the hooks to it. ") in joined, joined
        assert "WORKING" not in joined, joined
        assert (f"nothing named 'python', 'python3' or 'py -3' on PATH starts and "
                f"clears the {floor} floor, so the rewire has no target yet") in joined, joined

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_doctor_names_the_rewire_target_beside_a_below_floor_wired_name(
            self, tmp_path, monkeypatch):
        """The below-floor finding's other arm (TP-706's code review, driven):
        wired `python3` answers 3.10.12 and PATH `python` answers 3.12.0, so
        the rewire has a target, and the hint names it with the command,
        never the identity-only "a WORKING `python3`" and its symlink."""
        from espalier import doctor as doctor_module

        stubs = {
            "python": str(self._stub(tmp_path, "python", "Python 3.12.0")),
            "python3": str(self._stub(tmp_path, "python3", "Python 3.10.12")),
        }
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python3"}]}]}}',
            encoding="utf-8",
        )
        monkeypatch.setattr(doctor_module.shutil, "which",
                            lambda x, path=None: stubs.get(str(x).split()[0]))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor_module._check_python_resolver(tmp_path, settings))
        assert (_python_floor.does_not_run_sentence("Python 3.10.12")
                + " Then re-wire the hooks to it. ") in joined, joined
        assert ("`python` starts and clears the floor -- run `python -m espalier "
                "init . --rewire-interpreter` to rewire the hooks to it.") in joined, joined
        assert "WORKING" not in joined and "symlink" not in joined, joined

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_doctor_calls_no_below_floor_python3_working(self, tmp_path, monkeypatch):
        """The sibling of the row above (TP-706's failure-mode review, driven on
        Windows): wired `python` is a Store alias, so doctor takes the
        not-a-Python-3 branch, and PATH `python3` answers 3.10.21. Read by
        identity alone, the `python3` arm called that one WORKING and named a
        rewire that refuses and a symlink that wires 3.10."""
        from espalier import doctor as doctor_module

        alias = ("#!/bin/sh\necho 'Python was not found; run without arguments "
                 "to install from the Microsoft Store' >&2\nexit 49\n")
        stubs = {
            "python": str(write_stub(tmp_path / "python", alias)),
            "python3": str(self._stub(tmp_path, "python3", "Python 3.10.21")),
        }
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"command": "python"}]}]}}',
            encoding="utf-8",
        )
        monkeypatch.setattr(doctor_module.shutil, "which",
                            lambda x, path=None: stubs.get(str(x).split()[0]))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor_module._check_python_resolver(tmp_path, settings))
        floor = _python_floor.floor_text()
        assert "WORKING" not in joined and "symlink" not in joined, joined
        assert (f"nothing named 'python', 'python3' or 'py -3' on PATH starts and "
                f"clears the {floor} floor, so the rewire has no target yet") in joined, joined

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_hook_side_probe_refuses_a_below_floor_interpreter(self, tmp_path):
        """The hook-side twin, driven, with a matched control."""
        hu = _hook_utils()
        old = self._stub(tmp_path, "py39", "Python 3.9.6")
        new = self._stub(tmp_path, "py314", "Python 3.14.0")
        hu._INTERPRETER_IDENTITY_MEMO.clear()
        try:
            assert hu.interpreter_meets_floor(str(old)) is False
            assert hu.interpreter_meets_floor(str(new)) is True, (
                "CONTROL FAILED: a 3.14 stub was also refused"
            )
            # And the identity probe still says BOTH are Python 3 -- the split
            # this class exists to express. Reporting `python3=no` for a
            # working 3.9 would put a false host fact in the orientation line.
            assert hu.interpreter_is_python3(str(old)) is True
        finally:
            hu._INTERPRETER_IDENTITY_MEMO.clear()


class TestAnInterpreterThatAnswersItsBannerAndCannotStart:
    """DEF-915: a banner is not a start, at every engine site that wires or
    vouches for an interpreter.

    ``--version`` is answered before an interpreter initialises, so one that
    cannot start prints a banner that clears the floor: a ``python -m venv
    --copies`` made from inside another venv on 3.10 records that venv as its
    ``home``, answers ``Python 3.10.x``, and dies importing ``encodings`` (the
    ledger row's drive, 2026-09-22, uv's 3.10.21 on the POSIX host; on the
    Windows host, 2026-10-06, the same steps wrote the base install as
    ``home`` and the copy started, so this class models the trap with a
    stub). Wired on its banner, every hook exits outside ``{0, 2}`` and every
    blocking guard fails open while ``init`` reports success.

    The stub (``tests/_interpreter_hosts.py::build_cannot_start``) answers
    ``--version`` with this interpreter's own banner and exits non-zero on
    anything else, beside working and Store-stub names built the way the
    shared hosts build them, so it runs on Windows, Linux and macOS alike.
    Every site test carries its control: the same site over a name that
    starts. RED before the fix: the resolver returned ``python`` and ``py
    -3``, the floor probe returned True, the rewire reported nothing to do,
    and doctor called the interpreter healthy.
    """

    @staticmethod
    def _host(tmp_path, monkeypatch, cannot_start, *, working=(), stubbed=()):
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_cannot_start(
            tmp_path / "host", cannot_start, working=working, stubbed=stubbed,
        )
        monkeypatch.setenv("PATH", str(bin_dir))
        return bin_dir

    def test_the_start_probe_reads_the_exit_not_the_banner(self, tmp_path, monkeypatch):
        import shutil

        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, ("python",), working=("python3",))
        broken, working = shutil.which("python"), shutil.which("python3")
        assert broken and working, (broken, working)
        banner = subprocess.run(
            [broken, "--version"], capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        ).stdout.strip()
        assert _python_floor.meets_python_floor(banner), (
            f"precondition: the broken stub's banner must clear the floor, or "
            f"this test is not about a banner that lies: {banner!r}"
        )
        failure = _python_floor.interpreter_start_failure([broken])
        assert failure is not None, "an interpreter that exits 1 at start-up read as starting"
        assert failure.startswith("cannot start:"), failure
        assert f"exits {hosts.CANNOT_START_EXIT}" in failure, failure
        assert "No module named 'encodings'" in failure, (
            f"the evidence must quote the interpreter's own last line: {failure}"
        )
        assert _python_floor.interpreter_start_failure([working]) is None, (
            "CONTROL FAILED: a stub forwarding to this interpreter read as unable to start"
        )

    def test_a_timeout_gets_one_second_chance_and_an_exit_status_none(self, monkeypatch):
        """A shim slow once must not turn a working interpreter into a refused
        one (the resolver has no retry of its own), and a hang must not be
        retried forever. Driven through the probe's own `subprocess.run`."""
        calls: list[list[str]] = []
        outcomes: list[object] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return subprocess.CompletedProcess(argv, outcome, stdout="", stderr="boom\n")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.delenv("PYTHONHOME", raising=False)
        monkeypatch.delenv("PYTHONPATH", raising=False)
        probe = ["/nonexistent/python-slow"]

        outcomes[:] = [subprocess.TimeoutExpired(probe, 2), 0]
        assert _python_floor.interpreter_start_failure(probe) is None
        assert len(calls) == 2, calls

        calls.clear()
        outcomes[:] = [subprocess.TimeoutExpired(probe, 2), subprocess.TimeoutExpired(probe, 2)]
        failure = _python_floor.interpreter_start_failure(probe)
        # Two timeouts keep the banner's verdict (DEF-5014).
        assert failure is None, failure
        assert len(calls) == 2, calls

        calls.clear()
        outcomes[:] = [1]
        failure = _python_floor.interpreter_start_failure(probe)
        assert failure is not None and "exits 1 (boom)" in failure, failure
        assert len(calls) == 1, f"an exit status was retried: {calls}"
        assert calls[0][1:] == ["-I", "-c", "import sys"], calls

    def test_the_running_interpreter_is_asked_only_when_no_env_rescues_it(self, monkeypatch):
        """The shortcut for ``sys.executable`` is sound only while this shell
        sets nothing ``-I`` drops."""
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.delenv("PYTHONHOME", raising=False)
        monkeypatch.delenv("PYTHONPATH", raising=False)
        assert _python_floor.interpreter_start_failure([sys.executable]) is None
        assert calls == [], f"the running interpreter was spawned: {calls}"
        monkeypatch.setenv("PYTHONPATH", "rescue")
        assert _python_floor.interpreter_start_failure([sys.executable]) is None
        assert len(calls) == 1, (
            "with PYTHONPATH set, 'it started here' does not answer 'it starts "
            "for a hook', so the probe must run"
        )

    def test_the_running_interpreter_shortcut_keys_on_its_path_not_its_file(
        self, tmp_path, monkeypatch
    ):
        """Whether an interpreter starts depends on where it is invoked from
        (its ``pyvenv.cfg``), so a broken venv whose ``python`` links to the
        running binary must still be probed: ``samefile`` would have passed
        it. A hardlink stands in for the link (no privilege needed on NTFS)."""
        import shutil

        self._host(tmp_path, monkeypatch, ("python",))
        stub = Path(shutil.which("python"))
        link = stub.with_name("python-linked" + stub.suffix)
        try:
            os.link(stub, link)
        except OSError as exc:  # a filesystem without hardlinks
            pytest.skip(f"no hardlink here: {exc}")
        monkeypatch.delenv("PYTHONHOME", raising=False)
        monkeypatch.delenv("PYTHONPATH", raising=False)
        monkeypatch.setattr(sys, "executable", str(stub))
        assert os.path.samefile(link, stub), "precondition: one file, two paths"
        assert _python_floor.interpreter_start_failure([str(stub)]) is None, (
            "the running interpreter's own path is answered without a spawn"
        )
        assert _python_floor.interpreter_start_failure([str(link)]) is not None, (
            "a second path to the running binary was passed on file identity"
        )

    def test_the_hook_side_twin_reads_the_banner_only_and_says_so(
        self, tmp_path, monkeypatch
    ):
        """The deliberate asymmetry, pinned so neither side drifts silently:
        the engine's floor check (which WIRES) refuses an interpreter that
        cannot start; the hook-side twin (which only warns and hints, on every
        SessionStart) reads the banner alone and its docstring says it may not
        decide wiring. A change that gives the hook side the probe, or takes
        it from the engine, reds here and must re-argue the split."""
        hu = _hook_utils()
        self._host(tmp_path, monkeypatch, ("python",))
        monkeypatch.setattr(hu, "_INTERPRETER_IDENTITY_MEMO", {})
        assert _python_floor.interpreter_meets_floor("python") is False
        assert hu.interpreter_meets_floor("python") is True
        doc = hu.interpreter_meets_floor.__doc__ or ""
        assert "never decide to WIRE" in doc, doc

    def test_the_floor_probe_refuses_it(self, tmp_path, monkeypatch):
        self._host(tmp_path, monkeypatch, ("python",), working=("python3",))
        assert _python_floor.interpreter_meets_floor("python") is False, (
            "the floor probe blessed an interpreter that cannot start on its banner alone"
        )
        assert _python_floor.interpreter_meets_floor("python3") is True, (
            "CONTROL FAILED: a working interpreter was refused"
        )

    def test_the_resolver_wires_the_next_candidate_instead(
        self, tmp_path, monkeypatch, capsys
    ):
        from espalier import cli

        self._host(tmp_path, monkeypatch, ("python",), working=("python3",))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python3", (
            "the resolver wired the first candidate on its banner, though it cannot start"
        )
        assert capsys.readouterr().err == "", "a host with a working candidate was warned"

    def test_a_lone_one_falls_through_and_the_warning_quotes_why(
        self, tmp_path, monkeypatch, capsys
    ):
        """The candidate falls through with its evidence. The evidence is a real
        answer from the first candidate, so it outranks a later candidate's
        Store-alias text (DEF-804's first-informative order) -- kept as the
        last-resort evidence instead, the warning would quote the alias and say
        nothing about the interpreter the operator thinks they have."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, ("python",), stubbed=("python3",))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._detect_python_command()
        warning = capsys.readouterr().err
        assert "'python' resolves to" in warning, warning
        assert "cannot start" in warning and "No module named 'encodings'" in warning, warning
        assert "could be validated" in warning, (
            f"a banner above the floor that cannot start is not a below-floor Python: {warning}"
        )
        assert "Microsoft Store" not in warning, (
            f"the later candidate's alias text displaced the first's evidence:\n{warning}"
        )

    def test_nor_is_the_launcher_wired_when_it_cannot_start(
        self, tmp_path, monkeypatch
    ):
        """The launcher branch is the floor probe's caller, so the launcher is
        held to the same test: ``py -3 -I -c 'import sys'``."""
        from espalier import cli
        from tests import _interpreter_hosts as hosts

        self._host(tmp_path, monkeypatch, ("py",), stubbed=("python", "python3"))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() != cli.LAUNCHER_CANDIDATE, (
            "the resolver wired a launcher whose -3 answers a banner and cannot start"
        )
        control = hosts.build_host(tmp_path / "control", hosts.LAUNCHER_ONLY)
        monkeypatch.setenv("PATH", str(control))
        assert cli._detect_python_command() == cli.LAUNCHER_CANDIDATE, (
            "CONTROL FAILED: a launcher that starts was not wired either"
        )

    @staticmethod
    def _settings(tmp_path: Path, interpreter: str) -> Path:
        path = tmp_path / ".claude" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{
            "type": "command", "command": interpreter,
            "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
        }]}]}}), encoding="utf-8")
        return path

    def test_doctor_names_the_start_failure_not_the_floor(self, tmp_path, monkeypatch):
        from espalier import doctor as doctor_module

        self._host(tmp_path, monkeypatch, ("python",), working=("python3",))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        issues = doctor_module._check_python_resolver(
            tmp_path, self._settings(tmp_path, "python"))
        joined = " ".join(issues)
        assert issues, "doctor reported an interpreter that cannot start as healthy"
        assert "cannot start" in joined and "fails OPEN" in joined, joined
        assert "older than" not in joined, (
            f"a start failure was reported as a below-floor Python whose guards "
            f"keep working -- the opposite consequence: {joined}"
        )
        assert "`python3` starts and clears the floor" in joined, (
            f"python3 here starts, so the rewire to it is the remedy: {joined}"
        )
        assert "python3 -m espalier init . --rewire-interpreter" in joined, joined

    def test_doctor_points_the_rewire_at_whichever_name_starts(
        self, tmp_path, monkeypatch
    ):
        """The wired ``python3`` is the broken one and ``python`` works: the
        remedy is keyed on what the rewire would do, not on ``python3`` --
        "a WORKING python3 IS on PATH" would be false, and "no working
        python3 either, install Python" would send the operator to install
        what they have."""
        from espalier import doctor as doctor_module

        self._host(tmp_path, monkeypatch, ("python3",), working=("python",))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor_module._check_python_resolver(
            tmp_path, self._settings(tmp_path, "python3")))
        assert "cannot start" in joined, joined
        assert "WORKING `python3`" not in joined, (
            f"doctor called the wired python3 working in the sentence that says "
            f"it cannot start: {joined}"
        )
        assert "`python` starts and clears the floor" in joined, joined
        assert "python -m espalier init . --rewire-interpreter" in joined, joined

    def test_doctor_calls_python3_working_only_if_it_starts_on_any_branch(
        self, tmp_path, monkeypatch
    ):
        """The other branches' remedy keyed on ``python3``'s banner: with the
        wired ``python`` absent and the PATH ``python3`` a copy that cannot
        start, doctor said "a WORKING `python3` IS on PATH -- re-run the
        rewire", and the rewire then found no target (failure-mode review)."""
        from espalier import doctor as doctor_module

        self._host(tmp_path, monkeypatch, ("python3",))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor_module._check_python_resolver(
            tmp_path, self._settings(tmp_path, "python")))
        assert "does not resolve" in joined, f"precondition: the wired name is absent: {joined}"
        assert "WORKING" not in joined, (
            f"doctor vouched for a python3 that cannot start on its banner: {joined}"
        )

    def test_doctor_says_the_rewire_has_no_target_when_nothing_starts(
        self, tmp_path, monkeypatch
    ):
        from espalier import doctor as doctor_module

        self._host(tmp_path, monkeypatch, ("python",), stubbed=("python3",))
        monkeypatch.setattr(doctor_module, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor_module._check_python_resolver(
            tmp_path, self._settings(tmp_path, "python")))
        assert "cannot start" in joined, joined
        assert "the rewire has no target yet" in joined, (
            f"nothing here starts, so prescribing the rewire alone would end in "
            f"its own refusal: {joined}"
        )

    def test_the_rewire_repairs_wiring_an_older_init_wrote(self, tmp_path, monkeypatch):
        """The adopter an older ``init`` already wired: ``init`` does not
        overwrite settings.json, so ``--rewire-interpreter`` is the repair, and
        it used to read the wired interpreter's banner as clearing the floor
        and report nothing to do."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, ("python3",), working=("python",))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        path = self._settings(tmp_path, "python3")
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert entry["command"] == "python", entry

    def test_the_rewire_refuses_one_as_its_target(self, tmp_path, monkeypatch):
        from espalier import cli

        import shutil

        self._host(tmp_path, monkeypatch, ("python3",), stubbed=("python",))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert shutil.which("python3"), "precondition: the target must resolve"
        path = self._settings(tmp_path, "python")  # a Store alias: stale
        before = path.read_bytes()
        result = cli.rewire_interpreter_in_settings(path, new_interpreter="python3")
        assert result.status == cli.REWIRE_NO_TARGET, result
        assert path.read_bytes() == before, "the file was modified on a refusal"


class TestAStartProbeThatNeverAnswers:
    """DEF-5014: on a loaded host the start-up probe times out on both tries,
    and that says nothing about the interpreter (DEF-1130 measured 31 to 73 s
    per concurrent interpreter start on windows-latest). So the verdict keeps
    the banner's, as the hook-side twin's does: no decision passes a working
    interpreter over on it. A claim asks ``interpreter_start_unconfirmed`` as
    well: init withholds the enforcement claim, and doctor gives the
    interpreter the time a blocking hook gets, once, and names it if it does
    not start in that time. Each verdict is kept for the process, so the
    probe's spawns are one bounded total.

    Only the ``-I -c 'import sys'`` spawn is stubbed; every other spawn (each
    ``--version``, git, doctor's own probes) runs for real against stubs
    forwarding to this interpreter, so the banner is a real answer. RED on
    main e388ec8: the verdict read "cannot start: ... timed out twice"; a
    ``python3``-only host had the literal ``python`` wired, which does not
    resolve there, and init said every guard fails OPEN; init asked the one
    interpreter 26 times and doctor 10. The tests marked "reviewed" were red
    on the lane's first commit d5e5f666, as both reviews drove them.
    """

    START_PROBE = ["-I", "-c", "import sys"]

    @pytest.fixture
    def slow(self, monkeypatch):
        """Time out the start-up probe, and record what each one asked.

        ``spare`` holds the file names whose probe runs for real; with
        ``patient`` set, a probe given more than 2 s runs for real too (a
        host that is loaded, not an interpreter that hangs)."""
        import types

        from espalier import _spawn

        real = _spawn.run_bounded
        state = types.SimpleNamespace(asked=[], spare=set(), patient=False)

        def run_bounded(argv, *args, **kwargs):
            argv = list(argv)
            if argv[-3:] == self.START_PROBE:
                timeout = kwargs.get("timeout") or 0
                state.asked.append((tuple(argv[:-3]), timeout))
                name = Path(argv[0]).stem
                if name not in state.spare and not (state.patient and timeout > 2):
                    raise subprocess.TimeoutExpired(argv, timeout)
            return real(argv, *args, **kwargs)

        monkeypatch.setattr(_spawn, "run_bounded", run_bounded)
        monkeypatch.delenv("PYTHONHOME", raising=False)
        monkeypatch.delenv("PYTHONPATH", raising=False)
        return state

    @staticmethod
    def _host(tmp_path, monkeypatch, *, working, stubbed=()):
        """Working stubs for ``working``, Store stubs for ``stubbed``, and git;
        nothing else on PATH. Returns the bin dir."""
        import shutil

        from tests import _interpreter_hosts as hosts

        git = shutil.which("git")
        assert git, "git is needed to drive init"
        bin_dir = hosts.build_cannot_start(tmp_path / "host", (), working=working, stubbed=stubbed)
        monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), str(Path(git).parent)]))
        return bin_dir

    @staticmethod
    def _adopter(tmp_path, monkeypatch):
        """An empty git tree to init, HOME kept in the test's own directory."""
        from espalier import cli

        for var in ("HOME", "USERPROFILE"):
            monkeypatch.setenv(var, str(tmp_path / "home"))
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        (tmp_path / "home").mkdir()
        target = tmp_path / "adopter"
        target.mkdir()
        (target / "README.md").write_text("# adopter\n", encoding="utf-8")
        (target / "pyproject.toml").write_text('[project]\nname = "adopter"\n', encoding="utf-8")
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        monkeypatch.chdir(target)
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        return target

    @staticmethod
    def _wire(target: Path, interpreter: str) -> None:
        """Rewrite every hook command in the tree's settings.json to ``interpreter``."""
        path = target / ".claude" / "settings.json"
        settings = json.loads(path.read_text(encoding="utf-8"))
        for groups in settings["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    hook["command"] = interpreter
        path.write_text(json.dumps(settings), encoding="utf-8")

    def test_two_timeouts_keep_the_banners_verdict_and_a_claim_hears_it(
        self, tmp_path, monkeypatch, slow
    ):
        import shutil

        self._host(tmp_path, monkeypatch, working=("python3",))
        python3 = shutil.which("python3")
        verdict = _python_floor.interpreter_start_failure([python3])
        assert verdict is None, (
            f"a probe that never answered was read as an interpreter that cannot start: {verdict}"
        )
        assert len(slow.asked) == 2, f"one timeout and its retry, no more: {slow.asked}"
        unconfirmed = getattr(_python_floor, "interpreter_start_unconfirmed")([python3])
        assert unconfirmed and unconfirmed.startswith("start not confirmed"), unconfirmed
        assert "loaded host" in unconfirmed, unconfirmed
        assert len(slow.asked) == 2, f"the claim's ask spawned again: {slow.asked}"

    def test_each_interpreter_is_asked_once_for_the_process(self, tmp_path, monkeypatch, slow):
        """Init asked one interpreter 26 times on a slow host, 2 s a try, so
        every remembered answer is up to 4 s not spent. A file rewritten in
        place is asked again: the verdict is keyed on the file as well."""
        import shutil

        self._host(tmp_path, monkeypatch, working=("python3",))
        python3 = shutil.which("python3")
        for _ in range(3):
            _python_floor.interpreter_start_failure([python3])
        assert len(slow.asked) == 2, f"the same interpreter was asked again: {slow.asked}"
        stub = Path(python3)
        stub.write_bytes(stub.read_bytes() + b"\n")
        os.utime(stub, ns=(stub.stat().st_atime_ns, stub.stat().st_mtime_ns + 10**9))
        _python_floor.interpreter_start_failure([python3])
        assert len(slow.asked) == 4, f"a rewritten file was answered from memory: {slow.asked}"

    def test_the_floor_check_keeps_the_banners_verdict(self, tmp_path, monkeypatch, slow):
        self._host(tmp_path, monkeypatch, working=("python3",))
        assert _python_floor.interpreter_meets_floor("python3") is True, (
            "a working interpreter whose start-up probe never answered was read as "
            "below the floor"
        )

    def test_the_resolver_wires_the_working_name_not_the_literal(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        from espalier import cli

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python3", (
            "the resolver passed over the one working name on a probe that never "
            "answered, and fell back to a name that does not run here"
        )
        assert "could be validated" not in capsys.readouterr().err

    def test_the_resolver_prefers_a_name_whose_start_was_seen(self, tmp_path, monkeypatch, slow):
        """Reviewed: ``python`` answers its banner and hangs at start-up (a
        blocking sitecustomize), ``python3`` works. A start nobody saw is no
        verdict, so the later candidate that started outranks it; d5e5f666
        wired the hanging one, where main wired ``python3``."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, working=("python", "python3"))
        slow.spare.add("python3")
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() == "python3"

    def test_the_rewire_repairs_a_wired_name_whose_start_nobody_saw(
        self, tmp_path, monkeypatch, slow
    ):
        """Reviewed: the floor check keeps the banner's verdict, so without
        its own test the rewire read the hanging ``python`` as already fine and
        said "nothing to rewire" over a working ``python3``."""
        import shutil

        from espalier import cli

        self._host(tmp_path, monkeypatch, working=("python", "python3"))
        slow.spare.add("python3")
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        path = TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python")
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        # The bare name, or its absolute path where the launchd PATH's python3
        # is older (the rewire's own DEF-636 rule).
        assert entry["command"] in ("python3", shutil.which("python3")), entry

    def test_init_withholds_the_claim_and_doctor_says_the_start_was_slow(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        """End to end on a ``python3``-only host that is loaded, not broken:
        init wires ``python3`` and withholds the enforcement claim (never a
        false all-clear), naming the unconfirmed start and a step to doctor;
        doctor gives the interpreter a blocking hook's time, it starts, and
        doctor says it starts but slowly, never "cannot start" and never
        healthy: a hook runs for several times a bare start (the failure-mode
        re-check measured 9.4 times on the Air). Each asks each interpreter
        once."""
        import argparse
        from collections import Counter

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        target = self._adopter(tmp_path, monkeypatch)
        slow.patient = True

        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        captured = capsys.readouterr()
        said = captured.out + captured.err
        settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        wired = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert wired == "python3", f"init wired {wired!r}:\n{said[-3000:]}"
        assert "cannot start:" not in said and "fails OPEN" not in said, said[-3000:]
        assert "Hooks now intercept" not in said, (
            f"init claimed enforcement on a start it never saw:\n{said[-3000:]}"
        )
        claim = [line for line in said.splitlines() if "not confirmed" in line]
        assert claim and "loaded host" in claim[0], said[-3000:]
        assert any("-m espalier doctor ." in line and "blocking hook" in line
                   for line in said.splitlines()), said[-3000:]
        assert set(Counter(slow.asked).values()) == {2}, f"init asked again: {Counter(slow.asked)}"

        slow.asked.clear()
        getattr(_python_floor, "_START_VERDICTS", {}).clear()  # doctor runs in a process of its own
        result = doctor.run_doctor_check(target)
        warned = [w for w in result["warnings"] if "python3" in w]
        assert warned and "and starts, but not within" in warned[0], result["warnings"]
        assert "cannot start" not in warned[0] and "did not start within" not in warned[0], warned
        assert any("less loaded" in s for s in result["next_steps"]), result["next_steps"]
        asked = Counter(slow.asked)
        assert sorted(asked.values()) == [1, 2], (
            f"doctor asks twice in 2 s and once in a blocking hook's time: {asked}"
        )

    def test_doctor_names_an_interpreter_that_does_not_start_in_a_blocking_hooks_time(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        """Reviewed: doctor stepped to itself forever on an interpreter that
        hangs, and spelled that step with the hanging interpreter. Given the
        time a blocking hook gets, one that does not start in it fails every
        blocking guard open, whatever the cause, and with nothing on PATH
        whose start was seen the step is doctor again on a less loaded host,
        spelled with the interpreter running doctor."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        target = self._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        capsys.readouterr()
        getattr(_python_floor, "_START_VERDICTS", {}).clear()  # doctor runs in a process of its own
        result = doctor.run_doctor_check(target)
        seconds = doctor._blocking_hook_seconds()
        late = [w for w in result["warnings"] if f"did not start within {seconds} s" in w]
        assert late and "fails OPEN" in late[0], result["warnings"]
        assert any(timeout > 2 for _, timeout in slow.asked), slow.asked
        again = [s for s in result["next_steps"]
                 if "-m espalier doctor ." in s and "less loaded" in s]
        assert again, result["next_steps"]
        # Read from the command's opening backtick: the interpreter running
        # doctor is the right spelling, and its own path may end in `python3`
        # (a venv's), which a bare substring read as the hanging one (red on a
        # worktree seat whose .venv/bin/python3 ran the slice, 2026-10-26).
        assert "`python3 -m espalier" not in again[0], (
            f"the step was spelled with the interpreter that does not start: {again[0]}"
        )

    def test_doctor_keeps_the_rewire_step_for_a_wired_name_that_is_not_python(
        self, tmp_path, monkeypatch, slow
    ):
        """Reviewed (the BLOCKER): the tree main's init left on a python3-only
        loaded host -- ``python`` wired, a Store stub -- on the same host. The
        python3 hint names an unconfirmed start, and d5e5f666 matched that
        text and dropped the rewire step for a false "run doctor again"."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        target = self._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        self._wire(target, "python")
        getattr(_python_floor, "_START_VERDICTS", {}).clear()
        result = doctor.run_doctor_check(target)
        assert any("does not answer as Python 3" in w or "does not resolve" in w
                   for w in result["warnings"]), result["warnings"]
        assert any("--rewire-interpreter" in s for s in result["next_steps"]), result["next_steps"]
        assert not any("start-up probe did not answer" in s for s in result["next_steps"]), (
            result["next_steps"])
        assert not any("WORKING" in w for w in result["warnings"]), (
            f"a python3 whose start nobody saw was called WORKING: {result['warnings']}")

    def test_the_claim_reads_its_own_verdict_not_a_second_banner_ask(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        """Reviewed: the narration asked the banner again, with no retry, and
        a miss there turned "not confirmed" back into DEF-5014's sentence. The
        fold saw the banner and not the start; the narration's own banner ask
        misses."""
        import argparse
        import shutil

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        target = self._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        capsys.readouterr()
        python3 = shutil.which("python3")
        clause = ("and answers as Python 3, but "
                  + _python_floor.interpreter_start_unconfirmed([python3]))
        found = {"python3": cli._NotPython3(
            python3, ["tools/cc/hooks/write_guard.py"], False, False, (python3,), clause)}
        monkeypatch.setattr(cli, "_not_python3_from_entries", lambda entries: found)
        monkeypatch.setattr(doctor, "_interpreter_is_python3", lambda resolved, *flags: False)
        reason, remedies = cli._disarmed_diagnosis(target)
        assert "not confirmed" in reason and "does not answer as Python 3" not in reason, reason
        assert any("-m espalier doctor ." in r for r in remedies), remedies

    def test_the_disarmed_diagnosis_prescribes_the_rewire_for_a_quoted_spaced_head(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        """DEF-4094's third reader: the prescriber reads the folded shape's
        `quoted` beside the form and the cut, so a hand-wired quoted spaced
        interpreter gets the rewire step, and the same head read without its
        closing quote (the unterminated shape) keeps the by-hand sentence.
        Dropping `quoted=` at this call turned no other test red (failure-mode
        review, by mutation)."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        target = self._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        capsys.readouterr()
        monkeypatch.setattr(doctor, "_interpreter_is_python3", lambda resolved, *flags: False)
        head = str(tmp_path / "with space" / "python3")
        for quoted, by_hand in ((True, False), (False, True)):
            found = {head: cli._NotPython3(None, ["tools/cc/hooks/write_guard.py"], False, False, (head,), "",
                                           quoted=quoted)}
            monkeypatch.setattr(cli, "_not_python3_from_entries", lambda entries, found=found: found)
            reason, remedies = cli._disarmed_diagnosis(target)
            joined = " ".join(remedies)
            assert ("declines this command shape" in joined) is by_hand, (quoted, reason, remedies)
            assert ("Rewire the hook commands" in joined) is not by_hand, (quoted, remedies)

    def test_the_rewire_says_what_it_left_and_never_already_starts(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        """Reviewed: on a host where no start is seen, the rewire has no
        target to move a site to, and its report said "every interpreter ...
        already starts" of interpreters whose start nobody saw."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, working=("python3",), stubbed=("python",))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        path = TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python3")
        before = path.read_bytes()
        assert cli._report_interpreter_rewire(path) == cli.REWIRE_NOTHING
        said = capsys.readouterr().err
        assert "already starts" not in said and "never answered" in said, said
        assert path.read_bytes() == before, "the file was written on a rewire with no target"

    def test_doctors_cannot_start_hint_says_starts_only_of_a_start_it_saw(
        self, tmp_path, monkeypatch, slow
    ):
        """Reviewed: the wired ``python`` cannot start (an exit status) and the
        rewire's target, ``python3``, answers its banner while its start-up
        probe never answers: the hint said "`python3` starts and clears the
        floor". The rewire still takes it, so the remedy stands."""
        from espalier import doctor
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_cannot_start(tmp_path / "host", ("python",), working=("python3",))
        monkeypatch.setenv("PATH", str(bin_dir))
        slow.spare.add("python")  # its probe runs for real, and exits
        monkeypatch.setattr(doctor, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor._check_python_resolver(
            tmp_path, TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python")))
        assert "cannot start" in joined, f"precondition: the wired python cannot start: {joined}"
        assert "starts and clears the floor" not in joined, joined
        assert "`python3` answers as Python" in joined and "--rewire-interpreter" in joined, joined

    def test_doctor_steps_to_the_rewire_when_a_started_target_is_there(
        self, tmp_path, monkeypatch, capsys, slow
    ):
        """Reviewed: the wired ``python`` hangs at start-up, ``python3``
        starts. Doctor names the hang and steps to the rewire, whose target
        started; "doctor again" is the step only when nothing on PATH did."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, working=("python", "python3"))
        slow.spare.add("python3")
        target = self._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        capsys.readouterr()
        self._wire(target, "python")
        getattr(_python_floor, "_START_VERDICTS", {}).clear()
        result = doctor.run_doctor_check(target)
        seconds = doctor._blocking_hook_seconds()
        assert any(f"did not start within {seconds} s" in w for w in result["warnings"]), (
            result["warnings"])
        assert any("--rewire-interpreter" in s for s in result["next_steps"]), result["next_steps"]
        assert not any("less loaded" in s for s in result["next_steps"]), result["next_steps"]

    def test_a_bare_name_is_asked_each_time(self, tmp_path, monkeypatch, slow):
        """Reviewed: a bare name resolves through PATH at the spawn, which a
        file of that name in the working directory does not key, so its
        verdict is never kept."""
        self._host(tmp_path, monkeypatch, working=("python3",))
        monkeypatch.chdir(tmp_path)
        (tmp_path / "python3").write_text("not an interpreter\n", encoding="utf-8")
        _python_floor.interpreter_start_failure(["python3"])
        _python_floor.interpreter_start_failure(["python3"])
        assert len(slow.asked) == 4, slow.asked

    def test_the_venv_only_probe_is_asked_once_per_candidate(self, tmp_path, monkeypatch):
        """Reviewed: unconfirmed candidates now reach the venv-only probe, a
        5 s spawn the resolver repeated for every remedy a run spells (13 in
        one init on a host where every spawn timed out)."""
        import shutil

        from espalier import cli

        self._host(tmp_path, monkeypatch, working=("python3",))
        python3 = shutil.which("python3")
        real = cli.run_no_stdin
        asked: list[list[str]] = []

        def run_bounded(argv, *args, **kwargs):
            if any("ESPALIER_PROBE" in str(a) for a in argv):
                asked.append(list(argv))
            return real(argv, *args, **kwargs)

        monkeypatch.setattr(cli, "run_no_stdin", run_bounded)
        for _ in range(3):
            assert cli._resolves_only_inside_a_virtualenv("python3", python3) is False
        assert len(asked) == 1, asked

    def test_the_engine_and_hook_probes_agree_on_two_timeouts(self, tmp_path, monkeypatch, slow):
        """The two copies keep the banner's verdict on a probe that never
        answered: the hook-side twin by design (DEF-1145), the engine since
        DEF-5014. A change to either reds here and must re-argue it."""
        import shutil

        hu = _hook_utils()
        self._host(tmp_path, monkeypatch, working=("python3",))
        monkeypatch.setattr(hu, "_INTERPRETER_IDENTITY_MEMO", {})

        def timed_out(argv, *args, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

        monkeypatch.setattr(hu, "run_bounded", timed_out)
        assert hu.interpreter_start_failure("python3") is None
        assert _python_floor.interpreter_start_failure([shutil.which("python3")]) is None

    def test_the_kept_verdicts_are_cleared_around_every_test(self, tmp_path, monkeypatch, slow):
        """Reviewed: a verdict one test drove answered the next test's ask
        (both reviews drove a test that passed or failed by order). The
        conftest fixture clears both engine memos; this pins the clearer."""
        import shutil

        from espalier import cli
        from tests import conftest

        self._host(tmp_path, monkeypatch, working=("python3",))
        _python_floor.interpreter_start_failure([shutil.which("python3")])
        cli._VENV_ONLY_VERDICTS[("x",)] = True
        _python_floor._BANNER_VERDICTS[("x",)] = None
        assert _python_floor._START_VERDICTS
        conftest._clear_engine_interpreter_memos()
        assert _python_floor._START_VERDICTS == {} and cli._VENV_ONLY_VERDICTS == {}
        assert _python_floor._BANNER_VERDICTS == {}


class TestABannerThatNeverAnswers:
    """DEF-5015: on a loaded host an interpreter's ``--version`` can miss its
    2 s too, and the engine read that as an answer: not a Python 3, below the
    floor. A ``python3``-only host had the literal ``python`` wired, which does
    not resolve there, while init said every guard fails OPEN and doctor told
    the operator to install a Python. The banner is now asked twice and kept
    for the process, shared by the resolver, the floor check and doctor's
    identity check. A candidate whose banner never answered is neither
    refused nor accepted on it: the resolver keeps it as the last choice ahead
    of the literal name, init withholds its claim ("not confirmed"), doctor
    gives the banner the time a blocking hook gets, and the rewire moves such
    a site only to a target that was seen. RED on the branch it is built on
    (lane/floor-check-names-the-slow-host, 0d8ad2f3).

    Only the stub interpreters' ``--version`` spawns are stubbed, each name to
    one of four answers: time out every try, time out the first try only, time
    out the 2 s tries and answer a longer one, or answer as a Python 2. Every
    other spawn runs for real.
    """

    @pytest.fixture
    def mute(self, monkeypatch, tmp_path):
        """Stub the banner probe of the host's stub interpreters, per name.

        ``modes`` maps a file name to "timeout" (every try), "retry" (the
        first try of each argv only), "patient" (every try of 2 s or less),
        "py2" or "py39" (answers ``Python 2.7.18`` or ``Python 3.9.6``), or
        "patient39" / "patientpy2" (times out at 2 s, then answers that); a
        name not listed answers for real. ``mute_start`` names whose start-up
        probe times out.
        """
        import types

        from espalier import _spawn

        real = _spawn.run_bounded
        state = types.SimpleNamespace(asked=[], modes={}, bin_dir=None, seen=set(),
                                      mute_start=set())

        def run_bounded(argv, *args, **kwargs):
            argv = list(argv)
            head = str(argv[0])
            if (argv[-3:] == ["-I", "-c", "import sys"] and state.bin_dir
                    and head.startswith(str(state.bin_dir)) and Path(head).stem in state.mute_start):
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
            if argv[-1:] == ["--version"] and state.bin_dir and head.startswith(str(state.bin_dir)):
                timeout = kwargs.get("timeout") or 0
                state.asked.append((tuple(argv[:-1]), timeout))
                mode = state.modes.get(Path(head).stem)
                first = tuple(argv) not in state.seen
                state.seen.add(tuple(argv))
                if mode == "timeout" or (mode == "retry" and first) or (
                        mode in ("patient", "patient39", "patientpy2") and timeout <= 2):
                    raise subprocess.TimeoutExpired(argv, timeout)
                said = {"py2": "Python 2.7.18", "patientpy2": "Python 2.7.18",
                        "py39": "Python 3.9.6", "patient39": "Python 3.9.6"}.get(mode)
                if said:
                    return subprocess.CompletedProcess(argv, 0, stdout=said + "\n", stderr="")
            return real(argv, *args, **kwargs)

        # cli and doctor reach it through run_no_stdin, which looks it up per call (DEF-928)
        monkeypatch.setattr(_spawn, "run_bounded", run_bounded)
        monkeypatch.delenv("PYTHONHOME", raising=False)
        monkeypatch.delenv("PYTHONPATH", raising=False)
        return state

    @staticmethod
    def _host(tmp_path, monkeypatch, mute, *, working, stubbed=(), modes=None):
        bin_dir = TestAStartProbeThatNeverAnswers._host(
            tmp_path, monkeypatch, working=working, stubbed=stubbed)
        mute.bin_dir = bin_dir
        mute.modes.update(modes or {})
        return bin_dir

    def test_the_banner_is_asked_twice_and_kept_for_the_process(self, tmp_path, monkeypatch, mute):
        self._host(tmp_path, monkeypatch, mute, working=("python3",), modes={"python3": "timeout"})
        for _ in range(3):
            assert _python_floor.interpreter_meets_floor("python3") is False
        assert len(mute.asked) == 2, f"two tries, then the kept answer: {mute.asked}"

    def test_a_banner_answering_on_its_retry_is_a_banner(self, tmp_path, monkeypatch, capsys, mute):
        """Polarity: a banner slow once is asked again and read as answered."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": "retry"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python3"
        assert "WARNING" not in capsys.readouterr().err

    def test_a_banner_that_answers_wrong_is_still_refused(self, tmp_path, monkeypatch, capsys, mute):
        """Polarity: a Python 2 answer is an answer, never a mute banner, so
        the literal fallback and its warning quoting the banner stand."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python",), stubbed=("python3",),
                   modes={"python": "py2"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python"
        warning = capsys.readouterr().err
        assert "2.7.18" in warning and "could be validated" in warning, warning

    def test_the_resolver_keeps_a_mute_banner_ahead_of_the_literal_name(
        self, tmp_path, monkeypatch, capsys, mute
    ):
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": "timeout"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python3", (
            "a working python3 whose banner never answered was passed over for the "
            "literal name, which does not run here"
        )
        warning = capsys.readouterr().err
        assert "Falling back to the literal name" not in warning, warning
        assert "python3" in warning and "--version" in warning, warning

    def test_a_banner_that_answered_outranks_a_mute_one(self, tmp_path, monkeypatch, mute):
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python": "timeout"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() == "python3"

    def test_init_withholds_the_claim_and_doctor_names_a_mute_banner(
        self, tmp_path, monkeypatch, capsys, mute
    ):
        """End to end on a ``python3``-only host whose banner never answers:
        init wires ``python3`` and withholds the claim, and doctor gives the
        banner a blocking hook's time, says every blocking guard runs out of
        it, and steps to doctor again (nothing on PATH was seen)."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": "timeout"})
        target = TestAStartProbeThatNeverAnswers._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        captured = capsys.readouterr()
        said = captured.out + captured.err
        settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        wired = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert wired == "python3", f"init wired {wired!r}:\n{said[-3000:]}"
        # The resolver's warning names the hang case conditionally; no claim
        # line says the guards fail OPEN or that it is not a Python.
        assert "does not answer as Python 3" not in said and "NOT yet active" not in said, said[-3000:]
        assert "Hooks now intercept" not in said, said[-3000:]
        claim = [line for line in said.splitlines() if "not confirmed" in line]
        assert claim and "--version" in claim[0], said[-3000:]

        mute.asked.clear()
        mute.seen.clear()
        getattr(_python_floor, "_BANNER_VERDICTS", {}).clear()
        getattr(_python_floor, "_START_VERDICTS", {}).clear()
        result = doctor.run_doctor_check(target)
        seconds = doctor._blocking_hook_seconds()
        late = [w for w in result["warnings"] if f"`--version` within {seconds} s" in w]
        assert late and "fails OPEN" in late[0], result["warnings"]
        assert "starts and clears the floor" not in late[0], late
        assert not any("brew install" in w for w in result["warnings"]), result["warnings"]
        assert any("slow to answer here" in s for s in result["next_steps"]), result["next_steps"]

    def test_doctor_says_a_banner_that_answers_late_is_slow(self, tmp_path, monkeypatch, capsys, mute):
        """A banner that answers only in the time a blocking hook gets: doctor
        warns that it is slow, never that it is not a Python 3."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": "patient"})
        target = TestAStartProbeThatNeverAnswers._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        capsys.readouterr()
        getattr(_python_floor, "_BANNER_VERDICTS", {}).clear()
        result = doctor.run_doctor_check(target)
        warned = [w for w in result["warnings"] if "python3" in w]
        assert warned and "not within" in warned[0], result["warnings"]
        assert "does not answer as Python 3" not in warned[0], warned

    def test_the_rewire_moves_a_mute_site_only_to_a_seen_target(
        self, tmp_path, monkeypatch, capsys, mute
    ):
        import shutil

        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python3": "timeout"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        path = TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python3")
        result = cli.rewire_interpreter_in_settings(path)
        assert result.status == cli.REWIRE_DONE, result
        entry = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert entry["command"] in ("python", shutil.which("python")), entry

        mute.modes["python"] = "timeout"
        getattr(_python_floor, "_BANNER_VERDICTS", {}).clear()
        path = TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path / "two", "python3")
        before = path.read_bytes()
        assert cli._report_interpreter_rewire(path) == cli.REWIRE_NOTHING
        said = capsys.readouterr().err
        assert "never answered" in said and "already starts" not in said, said
        assert path.read_bytes() == before, "a mute site was rewired to a mute target"


    def test_a_mute_banner_ranks_below_a_venv_only_name(self, tmp_path, monkeypatch, mute):
        """Pins the settled order (code re-check): the venv-only fallback, a
        name that answered, outranks one whose banner never did."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python": "timeout"})
        monkeypatch.setattr(cli, "_resolves_only_inside_a_virtualenv",
                            lambda name, resolved: name == "python3")
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() == "python3"

    def test_the_running_interpreters_banner_is_read_not_assumed(self):
        """Code re-check: the running interpreter's banner is answered without
        a spawn, so it must say what ``sys.executable --version`` says, never
        a pass taken for granted (the floor pin's own rationale)."""
        said = subprocess.run([sys.executable, "--version"], capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
        real = _python_floor.parse_python_version((said.stdout or said.stderr).strip())
        assert real is not None
        assert _python_floor.parse_python_version(_python_floor._running_interpreter_banner()) == real

    def test_doctors_cannot_start_hint_names_a_mute_target(self, tmp_path, monkeypatch, mute):
        """Code re-check (S2b, unpinned): the wired ``python`` cannot start and
        the rewire's only other candidate, ``python3``, never answers its
        banner: the hint says so, never "nothing named ... a fresh install"."""
        from espalier import doctor
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_cannot_start(tmp_path / "host", ("python",), working=("python3",))
        monkeypatch.setenv("PATH", str(bin_dir))
        mute.bin_dir = bin_dir
        mute.modes["python3"] = "timeout"
        monkeypatch.setattr(doctor, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor._check_python_resolver(
            tmp_path, TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python")))
        assert "cannot start" in joined, joined
        assert "so the rewire has no confirmed target yet" in joined, joined
        assert "nothing named" not in joined, joined

    def test_the_claims_remedy_names_a_mute_candidate(self, tmp_path, monkeypatch, capsys, mute):
        """Code re-check (S2d, unpinned): the claim's remedy over a wired word
        that is not a Python, beside a ``python3`` that never answered, says
        doctor again, never "Put a Python 3.11+ on PATH"."""
        import argparse

        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": "timeout"})
        target = TestAStartProbeThatNeverAnswers._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        TestAStartProbeThatNeverAnswers._wire(target, "python")
        capsys.readouterr()
        reason, remedies = cli._disarmed_diagnosis(target)
        joined = " ".join(remedies)
        assert "before putting another Python on PATH" in joined, joined
        assert "Put a Python" not in joined, joined

    def test_a_below_floor_best_candidate_beside_a_mute_one_is_not_install(
        self, tmp_path, monkeypatch, capsys, mute
    ):
        """Code re-check (residual S2 shape): the best candidate is a 3.9 and a
        ``python3`` beside it never answered: the rewire's no-target report and
        doctor's next step said install or put a Python on PATH."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python": "py39", "python3": "timeout"})
        target = TestAStartProbeThatNeverAnswers._adopter(tmp_path, monkeypatch)
        # init refuses the 3.9 before writing (the 2026-11-07 ruling) and says
        # the mute python3 may be the Python the floor needs.
        capsys.readouterr()
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 1
        refusal = capsys.readouterr().err
        assert "does not run on Python 3.9" in refusal and "'python3'" in refusal, refusal
        assert "before installing one" in refusal, refusal
        assert not (target / ".claude").exists(), "init wrote a tree it refused"
        # The rest is about a tree wired BEFORE the floor moved: modelled by
        # letting the setup init past the refusal.
        monkeypatch.setattr(cli, "_refuse_below_floor_wiring", lambda verb: None)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        TestAStartProbeThatNeverAnswers._wire(target, "python")
        capsys.readouterr()
        assert cli._report_interpreter_rewire(target / ".claude" / "settings.json") == cli.REWIRE_NO_TARGET
        report = capsys.readouterr().err
        assert f"Install Python {_python_floor.floor_text()} or newer first" not in report and "before installing" in report, report
        result = doctor.run_doctor_check(target)
        assert not any("neither name answers as one now" in s for s in result["next_steps"]), (
            result["next_steps"])

    def test_the_running_interpreter_answers_its_own_banner(self, tmp_path, monkeypatch, capsys, mute):
        """Reviewed (both): a ``python3`` that is the interpreter running
        espalier (pip --user, pipx, Homebrew) had its banner spawned and, on a
        loaded host, read as missing, so doctor called the running 3.x "older
        than 3.10". Its own file is answered from ``sys.version_info``."""
        import argparse

        from espalier import cli, doctor

        bin_dir = self._host(tmp_path, monkeypatch, mute, working=(), stubbed=("python",))
        # The name the wired python3 resolves to: python3.exe on Windows, else
        # python3 alone. A Homebrew sys.executable ends python3.14, whose suffix
        # is ".14", and Apple's /usr/bin/python3 beside git answered (air's
        # fc0256, read on its host).
        link = bin_dir / ("python3.exe" if os.name == "nt" else "python3")
        target = sys.executable
        if os.name == "nt":
            # On Windows no link to the running interpreter in another folder
            # starts under this host's PATH (measured on the Windows box,
            # 2026-10-17): a venv's python.exe is a redirector that needs the
            # pyvenv.cfg beside it (exit 106), and the base binary
            # (`tests/_interpreter_hosts.py::HOOK_PYTHON`) needs its DLLs beside
            # it (STATUS_DLL_NOT_FOUND unless its folder is on PATH). The start
            # probe rightly reads either as cannot start. So here the link IS the
            # running interpreter's path, the shape an espalier started as
            # `python3.exe` has, and both the banner and the start shortcut read
            # it without a spawn; on POSIX the link is another path to the
            # running file, and the start probe spawns it.
            from tests._interpreter_hosts import HOOK_PYTHON

            target = HOOK_PYTHON
        try:
            os.symlink(target, link)
        except OSError as exc:  # no symlinks here (Windows without the privilege)
            pytest.skip(f"no symlink here: {exc}")
        if os.name == "nt":
            monkeypatch.setattr(sys, "executable", str(link))
        mute.modes["python3"] = "timeout"
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python3"
        assert "unconfirmed" not in capsys.readouterr().err
        target = TestAStartProbeThatNeverAnswers._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        capsys.readouterr()
        result = doctor.run_doctor_check(target)
        said = " ".join(result["warnings"] + result["next_steps"])
        assert "older than" not in said and "Install Python" not in said, said
        assert not [a for a in mute.asked if Path(a[0][0]).stem == "python3"], mute.asked

    def test_a_mute_launcher_is_kept_like_a_bare_name(self, tmp_path, monkeypatch, mute):
        """Reviewed (code): on a launcher-only host, a ``py -3`` whose banner
        never answers was read as refused and the literal ``python`` wired."""
        import shutil

        from espalier import cli
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_host(tmp_path / "h", hosts.LAUNCHER_ONLY)
        monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), str(Path(shutil.which("git")).parent)]))
        mute.bin_dir = bin_dir
        mute.modes["py"] = "timeout"
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() == cli.LAUNCHER_CANDIDATE

    def test_a_launcher_answering_as_a_python_2_is_still_refused(self, tmp_path, monkeypatch, mute):
        """Polarity: an answer is an answer, the launcher's as a bare name's."""
        import shutil

        from espalier import cli
        from tests import _interpreter_hosts as hosts

        bin_dir = hosts.build_host(tmp_path / "h", hosts.LAUNCHER_ONLY)
        monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), str(Path(shutil.which("git")).parent)]))
        mute.bin_dir = bin_dir
        mute.modes["py"] = "py2"
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() != cli.LAUNCHER_CANDIDATE

    @pytest.mark.parametrize("mode", ["timeout", "patient"])
    def test_no_prescriber_says_install_over_a_mute_python3(
        self, tmp_path, monkeypatch, capsys, mute, mode
    ):
        """Reviewed (both): the tree main's fallback left -- ``python`` wired,
        a Store stub -- on the same loaded host. doctor's next step, init's
        remedy and the rewire's report each told the operator to install or
        put a Python on PATH, over a ``python3`` that only never answered. The
        "patient" row is the slow ``python3`` that answers in a blocking hook's
        time: the verification round found the hint saying install again."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": mode})
        target = TestAStartProbeThatNeverAnswers._adopter(tmp_path, monkeypatch)
        assert cli.cmd_init(argparse.Namespace(repo=str(target), config=None)) == 0
        TestAStartProbeThatNeverAnswers._wire(target, "python")
        capsys.readouterr()
        result = doctor.run_doctor_check(target)
        said = " ".join(result["warnings"] + result["next_steps"])
        # The unconditional "install" sentences; a step that says "doctor
        # again first, and if it still does not answer, put one on PATH" is the
        # honest order and stays.
        assert "neither name answers as one now" not in said, said
        assert "brew install" not in said and "nothing named" not in said, said
        assert any("--rewire-interpreter" in s for s in result["next_steps"]), result["next_steps"]
        assert cli._report_interpreter_rewire(target / ".claude" / "settings.json") == cli.REWIRE_NO_TARGET
        report = capsys.readouterr().err
        assert "Install Python" not in report and "before installing" in report, report

    @pytest.mark.parametrize("mode, cannot_start, says", [
        ("patient39", False, "does not run on Python 3.9"),
        ("patient", True, "cannot start"),
    ])
    def test_a_late_banner_is_still_read_for_the_floor_and_the_start(
        self, tmp_path, monkeypatch, mute, mode, cannot_start, says
    ):
        """Reviewed (both): a banner that answered only in a blocking hook's
        time was called slow before its floor and its start were asked, so a
        late 3.9 and a late copy that cannot start read "may run out of
        time"."""
        from espalier import doctor
        from tests import _interpreter_hosts as hosts

        if cannot_start:
            bin_dir = hosts.build_cannot_start(tmp_path / "host", ("python3",))
            monkeypatch.setenv("PATH", str(bin_dir))
            mute.bin_dir = bin_dir
        else:
            bin_dir = self._host(tmp_path, monkeypatch, mute, working=("python3",))
        mute.modes["python3"] = mode
        monkeypatch.setattr(doctor, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor._check_python_resolver(
            tmp_path, TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python3")))
        assert says in joined and "may run out of time" not in joined, joined

    def test_a_late_wrong_answer_is_not_called_mute(self, tmp_path, monkeypatch, mute):
        """Reviewed (code): a ``python3`` whose banner answered ``Python
        2.7.18`` on the longer ask was then called a mute python3 by the hint
        beside the warning that had just read its answer."""
        from espalier import doctor

        self._host(tmp_path, monkeypatch, mute, working=("python3",), modes={"python3": "patientpy2"})
        monkeypatch.setattr(doctor, "resolves_only_inside", lambda cmd: False)
        joined = " ".join(doctor._check_python_resolver(
            tmp_path, TestAnInterpreterThatAnswersItsBannerAndCannotStart._settings(tmp_path, "python3")))
        assert "does not answer as Python 3" in joined, joined
        assert "probe did not answer" not in joined, joined

    def test_a_mute_banner_ranks_below_a_below_floor_answer(self, tmp_path, monkeypatch, capsys, mute):
        """Pins the settled order (the dispatcher's): mute is the last choice,
        and the below-floor warning names the mute candidate beside it rather
        than tell the operator to install only."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python": "timeout", "python3": "py39"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        assert cli._detect_python_command() == "python3"
        warning = capsys.readouterr().err
        assert "'python'" in warning and "did not answer `--version` in time here" in warning, warning

    def test_a_mute_banner_ranks_below_an_unconfirmed_start(self, tmp_path, monkeypatch, mute):
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python": "timeout"})
        mute.mute_start.add("python3")
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() == "python3"

    def test_the_mute_warning_is_said_once(self, capsys, monkeypatch):
        from espalier import cli

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        cli._warn_interpreter_unanswered("python3", "/nowhere/python3")
        cli._warn_interpreter_unanswered("python3", "/nowhere/python3")
        cli._warn_interpreter_unvalidated(None)
        assert capsys.readouterr().err.count("WARNING:") == 1

    def test_a_banner_that_never_answered_is_no_banner_to_parse(self):
        """Reviewed (failure-mode): None read as a banner is refused in
        silence, DEF-5015 again; the parser says so instead."""
        with pytest.raises(TypeError):
            _python_floor.is_python3_banner(None)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _python_floor.meets_python_floor(None)  # type: ignore[arg-type]

    def test_every_engine_verdict_memo_is_cleared_between_tests(self):
        """Reviewed (failure-mode): the clearer's list is kept by hand, so it
        is derived here against the engine's own module-level ``_*_VERDICTS``
        dicts: a new memo that is not cleared reds rather than leaking."""
        from tests import conftest
        from tests._live_tree import checkout_glob

        found = set()
        for path in sorted(checkout_glob(REPO_ROOT / "espalier", "*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                targets = ([node.target] if isinstance(node, ast.AnnAssign)
                           else node.targets if isinstance(node, ast.Assign) else [])
                for t in targets:
                    if isinstance(t, ast.Name) and re.fullmatch(r"_[A-Z_]*_VERDICTS", t.id):
                        found.add((f"espalier.{path.stem}", t.id))
        assert found, "the census found no memo, so it reads nothing"
        assert found <= set(conftest._ENGINE_INTERPRETER_MEMOS), (
            f"engine verdict memos the conftest clearer does not clear: "
            f"{sorted(found - set(conftest._ENGINE_INTERPRETER_MEMOS))}")


def test_cognitive_blueprint_really_does_need_310():
    """The premise the whole class rests on, re-derived rather than cited.

    If `cognitive_blueprint.py` were 3.9-parseable the floor would still be
    right (pyproject says so) but DEF-636's *severity* argument would not be,
    and this pack quotes that argument. Compile it under 3.9 grammar rules by
    looking for the 3.10+ construct directly.
    """
    src = (REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    has_match = any(isinstance(n, ast.Match) for n in ast.walk(tree))
    assert has_match, (
        "cognitive_blueprint.py no longer uses `match`; DEF-636's severity "
        "argument (blueprints die on 3.9) needs re-deriving, and this test "
        "should be replaced with whatever the new 3.10+ dependency is"
    )


class TestSessionStartWarnDistinguishesTheTwoFailures:
    """The SessionStart warn covers two different broken interpreters.

    Before TP-448 Class 3 it keyed on identity, so a wired 3.9 was never
    reported at all; now it is, and it must not borrow the wrong words. "Does
    not resolve to a working Python 3" is false about a working 3.9 and sends
    the operator hunting for an install they already have — while the real
    symptom, `No active blueprint` forever, goes unnamed.
    """

    @staticmethod
    def _drive(tmp_path: Path, command: str) -> str:
        claude = tmp_path / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        # json.dumps, NOT repr: repr quotes with ' and produces invalid JSON,
        # which the hook silently skips -- the warning then never fires and the
        # test passes for the wrong reason. Caught by the control arm.
        (claude / "settings.json").write_text(
            json.dumps({
                "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
                    {"type": "command", "command": command, "args": ["x.py"]}
                ]}]}
            }),
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "session_start.py")],
            input='{"hook_event_name":"SessionStart","source":"startup"}',
            capture_output=True, text=True, timeout=30, env=env, cwd=str(tmp_path), encoding="utf-8",
        )
        # A start cut at its wall never reached the interpreter warn, so the
        # control's empty answer would pass on it: cannot-tell (DEF-2048).
        skip_if_cut(result.stdout)
        return "\n".join(
            ln for ln in result.stderr.splitlines() if "wired hook interpreter" in ln
        )

    @staticmethod
    def _stub(tmp_path: Path, name: str, says: str) -> str:
        return str(write_stub(tmp_path / name, f"#!/bin/sh\necho '{says}'\n"))

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_below_floor_gets_the_below_floor_words(self, tmp_path):
        # Python-shaped names: SessionStart asks only a word that names a
        # Python whether it is one (DEF-1024), so `py39` would go unasked.
        warn = self._drive(tmp_path, self._stub(tmp_path, "python39", "Python 3.9.6"))
        assert warn, "a wired 3.9 produced no warning at all"
        assert "IS a Python 3" in warn and _python_floor.floor_text() in warn, warn
        assert "does not resolve to a working Python 3" not in warn, (
            f"a working 3.9 was described as not being a Python 3: {warn}"
        )
        # The one sentence every surface says (the 2026-11-07 ruling), with the
        # version the banner spelled, then the re-wire: never the 2026-09-03
        # promise that the guards keep working on it. Built by the engine's own
        # renderer for the same banner, never spelled here: the hook cannot
        # import it and spells the words by hand, so a reworded engine
        # sentence reds this row until the banner says it too.
        assert _python_floor.does_not_run_sentence("Python 3.9.6") in warn, warn
        assert "re-wire the hooks" in warn, warn
        assert "keep working" not in warn, warn

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_non_python_keeps_the_fail_open_words(self, tmp_path):
        warn = self._drive(tmp_path, self._stub(tmp_path, "python-notpy", "not a python"))
        assert "does not resolve to a working Python 3" in warn, warn
        assert "fails OPEN" in warn or "fail OPEN" in warn, warn

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_conforming_interpreter_is_silent(self, tmp_path):
        """The control. Without it, both tests above pass on a hook that warns
        unconditionally. It wires the interpreter running this test, a
        conforming Python 3 by construction: a PATH lookup of ``python3`` can
        find a Store alias stub, which resolves and does not answer, and the
        hook is right to warn about that one."""
        warn = self._drive(tmp_path, sys.executable)
        assert warn == "", f"a conforming interpreter produced a warning: {warn}"

    def test_neither_message_prescribes_the_init_no_op(self):
        """DEF-620 lives one function over: `init` does not overwrite an
        existing settings.json, so "re-run init to rewrite the interpreter" is
        advice the operator can follow forever. Until
        `init --rewire-interpreter` exists, no message here may prescribe it.
        """
        src = (HOOKS_DIR / "session_start.py").read_text(encoding="utf-8")
        start = src.index("for interp in sorted(unresolved):")
        block = src[start:start + 2500]
        assert "espalier init" not in block, (
            "the SessionStart interpreter warning prescribes `espalier init`, "
            "which cannot rewire an existing settings.json (DEF-620)"
        )


@pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
class TestAPythonTwoHostIsToldTheTruth:
    """`DEF-727`, driven as the adopter meets it: `init` on a repo whose PATH
    holds one `python`, a Python 2 shim.

    Windows install walk 2 (2026-09-09, W2-24/27/29/30): settings wired to
    `python` at 12 sites; the wired hook printed `Python 2.7.18`, exit 0, not
    JSON -- a non-decision, which is NON-BLOCKING -- so every guard failed
    OPEN while `init` said "Wiring it anyway so the blocking guards keep
    working" and then "Hooks now intercept Claude Code tool calls". Three
    sites produced that: the below-floor gate admitted the banner, and the
    enforcement claim asked whether the wired paths resolve and whether the
    entries are executable in shape, never whether the interpreter answers as
    a Python 3.

    Driven as a subprocess on a tree the unit tests did not write, with the
    same stub answering as a conforming Python as the control (a banner that
    never prints the claim would pass the first half for the wrong reason).
    """

    @staticmethod
    def _host(tmp_path: Path, says: str) -> tuple[Path, dict]:
        stubs = tmp_path / "bin"
        stubs.mkdir()
        write_stub(stubs / "python", f"#!/bin/sh\necho '{says}'\n")
        import shutil as _shutil
        git = _shutil.which("git")
        assert git, "git is needed to drive init"
        (stubs / "git").symlink_to(git)
        target = tmp_path / "adopter"
        target.mkdir()
        (target / "README.md").write_text("# adopter\n", encoding="utf-8")
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        env = dict(os.environ)
        env["PATH"] = str(stubs)
        return target, env

    @staticmethod
    def _init(target: Path, env: dict) -> subprocess.CompletedProcess:
        # A budget UNDER pytest-timeout's 60 s ceiling (pyproject), so this
        # branch can actually fire: a larger number is dead code and one more
        # DEF-665 site. `init` on a stub host takes about a second.
        return subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target)],
            capture_output=True, text=True, timeout=50, env=env, encoding="utf-8",
        )

    def test_init_on_a_python_2_host_does_not_claim_enforcement(self, tmp_path):
        target, env = self._host(tmp_path, "Python 2.7.18")
        result = self._init(target, env)
        out = result.stdout + result.stderr
        assert "2.7.18" in out, (
            f"the Python 2 stub was never probed, so nothing below is about it:\n{out}"
        )
        assert "Hooks now intercept" not in result.stdout, (
            f"init claimed enforcement on a host whose only python is 2.7:\n{out}"
        )
        assert "blocking guards keep working" not in out, (
            f"Python 2 was described as a below-floor Python 3 whose guards run:\n{out}"
        )
        # The diagnosis line itself, not the whole stream: the unvalidated
        # warning above it already quotes 'python', so a stream-wide search
        # would pass on a narration that never named the word.
        active = [line for line in out.splitlines() if "NOT yet active" in line]
        assert active, f"no disarmed narration:\n{out}"
        assert "'python'" in active[0] and "answer as Python 3" in active[0], (
            f"the narration must name the interpreter and say WHY it disarms "
            f"the guards:\n{active[0]}"
        )
        # The blocker is PATH, not a missing install: this init ran under a
        # Python that clears the floor, so the remedy says what to put on PATH
        # and spells itself with that interpreter. Read the remedy LINE: the
        # resolver's own stderr warning, above it in the stream, says "Install
        # Python 3.10 or newer ... with it on PATH", which is the right sentence
        # for a host that may have no such Python at all.
        remedy = [line for line in out.splitlines() if "--rewire-interpreter" in line]
        assert len(remedy) == 1, f"expected one rewire remedy line:\n{out}"
        assert "on PATH" in remedy[0] and "-m espalier init . --rewire-interpreter" in remedy[0], (
            f"the remedy must name PATH and the rewire:\n{remedy[0]}"
        )
        assert "nstall" not in remedy[0], (
            f"an install the operator has already done was prescribed:\n{remedy[0]}"
        )
        # No command in the whole banner is spelled with the Python 2 word: a
        # bare `python` before `-m espalier` (an absolute path ending in
        # python3.14 is not one). The uninstall line three bullets under the
        # narration was, before the review.
        assert re.search(r"(?<![\w/.-])python -m espalier", out) is None, (
            f"a command was spelled with the Python 2 name:\n{out}"
        )

    def test_the_same_stub_answering_as_a_conforming_python_prints_the_claim(
        self, tmp_path
    ):
        """CONTROL. Without it the test above passes on a banner that never
        prints the claim at all."""
        target, env = self._host(tmp_path, "Python 3.14.0")
        result = self._init(target, env)
        out = result.stdout + result.stderr
        assert result.returncode == 0, out
        assert "Hooks now intercept" in result.stdout, (
            f"CONTROL FAILED: a conforming interpreter did not arm the claim:\n{out}"
        )
        assert "NOT yet active" not in out, out


class TestTheTwinsAgreeOnAProbeThatNeverAnswers:
    """DEF-5016: the hook twins read a probe that never answered as below the
    floor and not a Python 3 where the engine read it as no answer; they agree
    now, and both match the running interpreter by one rule per platform: by its
    invoked path on Windows (a link of a venv's python.exe elsewhere cannot
    start), elsewhere by the file a symlink resolves to (a symlink of the binary
    prints the same version; a hard link in another folder is asked)."""

    def test_a_timeout_is_no_answer_on_both_sides(self, tmp_path, monkeypatch):
        hu = _hook_utils()
        monkeypatch.setattr(hu, "_INTERPRETER_IDENTITY_MEMO", {})

        def timeout(argv, **_kw):
            raise subprocess.TimeoutExpired(argv, 2)
        monkeypatch.setattr(hu, "run_bounded", timeout)
        monkeypatch.setattr(_python_floor, "_BANNER_VERDICTS", {})
        monkeypatch.setattr(_python_floor, "_ask_banner", lambda argv, seconds, tries: None)
        other = tmp_path / "python3"
        other.write_bytes(b"")
        assert hu.interpreter_version_unanswered(str(other)) is True
        assert _python_floor.interpreter_banner([str(other)]) is None
        assert hu.interpreter_meets_floor(str(other)) is False and hu.interpreter_is_python3(str(other)) is False

    @staticmethod
    def _link_of_the_running_interpreter(tmp_path, *, symbolic=False, skip=True) -> "Path | None":
        """A hard (or symbolic) link of the running interpreter's file in
        another folder; where the host cannot make one the row skips, or with
        ``skip=False`` gets None."""
        link = tmp_path / ("sym" if symbolic else "hard") / Path(sys.executable).name
        link.parent.mkdir()
        # The binary itself: os.link does not follow a symlink on Linux, and a CI interpreter is
        # one (bin/python -> python3.11, relative), whose link in another folder would dangle.
        target = sys.executable if symbolic else os.path.realpath(sys.executable)
        try:
            (os.symlink if symbolic else os.link)(target, link)
        except OSError as exc:  # no hard links across volumes; no symlinks without the privilege
            if skip:
                pytest.skip(f"no {'symbolic' if symbolic else 'hard'} link here: {exc}")
            return None
        return link

    def test_on_windows_the_engine_asks_a_link_of_the_running_interpreter(self, tmp_path, monkeypatch):
        """The failure-mode review, driven on the hook twin and true of the
        engine's shortcut too: the Windows rule, driven on every host."""
        asked: list = []
        monkeypatch.setattr(_python_floor, "_BANNER_VERDICTS", {})
        monkeypatch.setattr(_python_floor, "_running_by_invoked_path", lambda: True, raising=False)
        monkeypatch.setattr(_python_floor, "_ask_banner",
                            lambda argv, seconds, tries: asked.append(list(argv)) or "No pyvenv.cfg file")
        link = self._link_of_the_running_interpreter(tmp_path)
        assert _python_floor.interpreter_banner([str(link)]) == "No pyvenv.cfg file"
        assert asked == [[str(link)]], asked
        assert _python_floor.interpreter_banner([sys.executable]) == _python_floor._running_interpreter_banner()
        assert asked == [[str(link)]], "the running interpreter by its own path is read, not asked"

    def test_elsewhere_the_engine_reads_a_symlink_of_the_running_binary(self, tmp_path, monkeypatch):
        """Off Windows a symlink of the binary prints the same version, so the
        engine reads it without a spawn, as
        ``TestABannerThatNeverAnswers::test_the_running_interpreter_answers_its_own_banner``
        drives on a POSIX host (DEF-5015). The POSIX rule, driven on every host."""
        asked: list = []
        monkeypatch.setattr(_python_floor, "_BANNER_VERDICTS", {})
        monkeypatch.setattr(_python_floor, "_running_by_invoked_path", lambda: False, raising=False)
        monkeypatch.setattr(_python_floor, "_ask_banner",
                            lambda argv, seconds, tries: asked.append(list(argv)) or None)
        link = self._link_of_the_running_interpreter(tmp_path, symbolic=True)
        assert _python_floor.interpreter_banner([str(link)]) == _python_floor._running_interpreter_banner()
        assert asked == [], asked

    def test_the_twins_keep_one_rule_per_platform(self, tmp_path, monkeypatch):
        """One rule in two copies with no import between them: the bodies are
        pinned equal (docstring and local imports aside), the default is by
        path on Windows only, and both copies agree on every spelling under
        either rule. The links come last, so a host that cannot make one still
        checks everything before them (the failure-mode pass on the split)."""
        import ast
        import inspect
        import textwrap

        hu = _hook_utils()

        def body(fn):
            node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
            return [ast.dump(s) for s in node.body[1:] if not isinstance(s, (ast.Import, ast.ImportFrom))]

        for name in ("_is_running_interpreter", "_running_by_invoked_path"):
            assert body(getattr(_python_floor, name)) == body(getattr(hu, name)), name
        assert _python_floor._running_by_invoked_path() is hu._running_by_invoked_path() is (os.name == "nt")
        gone = str(tmp_path / "gone" / Path(sys.executable).name)
        spellings = [sys.executable, sys.executable.upper(), sys.executable.lower(),
                     sys.executable.replace("\\", "/"), gone]

        def rule(by_path):
            monkeypatch.setattr(_python_floor, "_running_by_invoked_path", lambda: by_path)
            monkeypatch.setattr(hu, "_running_by_invoked_path", lambda: by_path)

        for by_path in (True, False):
            rule(by_path)
            for path in spellings:
                assert _python_floor._is_running_interpreter(path) is hu._is_running_interpreter(path), (by_path, path)
            assert _python_floor._is_running_interpreter(sys.executable) is True, by_path
            assert _python_floor._is_running_interpreter(gone) is False, by_path
            if os.name == "nt":
                assert _python_floor._is_running_interpreter(sys.executable.upper()) is True, by_path
        hard = self._link_of_the_running_interpreter(tmp_path, skip=False)
        sym = self._link_of_the_running_interpreter(tmp_path, symbolic=True, skip=False)
        for by_path in (True, False):
            rule(by_path)
            for link, running in ((hard, False), (sym, not by_path)):
                if link is not None:
                    assert _python_floor._is_running_interpreter(str(link)) is hu._is_running_interpreter(
                        str(link)) is running, (by_path, link)
        if hard is None and sym is None:
            pytest.skip("no link of either kind here; every link-free agreement above held")

    def test_doctor_has_no_identity_shortcut_of_its_own(self, tmp_path, monkeypatch):
        """The failure-mode pass on the split: doctor's ``_interpreter_is_python3``
        kept a ``samefile`` shortcut, a third rule, so on Windows a hard link of
        a venv's python.exe elsewhere, which cannot start, read as a Python 3 to
        doctor and not to the hook. It reads the banner now, which answers the
        running interpreter by the platform's rule. The Windows rule, driven on
        every host."""
        from espalier import doctor

        asked: list = []
        monkeypatch.setattr(_python_floor, "_BANNER_VERDICTS", {})
        monkeypatch.setattr(_python_floor, "_running_by_invoked_path", lambda: True, raising=False)
        monkeypatch.setattr(_python_floor, "_ask_banner",
                            lambda argv, seconds, tries: asked.append(list(argv)) or "No pyvenv.cfg file")
        link = self._link_of_the_running_interpreter(tmp_path)
        assert doctor._interpreter_is_python3(str(link)) is False
        assert asked == [[str(link)]], asked
        assert doctor._interpreter_is_python3(sys.executable) is True
        assert asked == [[str(link)]], "the running interpreter is read, never asked"


@pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
class TestADroppedPythonIsRefusedBeforeAnyWrite:
    """The operator's ruling of 2026-11-07, on the floor's move to 3.11: a
    dropped Python is dropped, never run in a reduced mode. When the only
    interpreter a command would wire is a Python 3 below the floor, every
    command that writes the resolver's answer into a tree (``init``, its dry
    run, ``upgrade``, ``merge-settings``, ``fuse``) refuses BEFORE it writes a
    single file, says plainly that the harness does not run on the version it
    found and to update to the floor or newer, and offers no fallback.

    This replaces the 2026-09-03 decision (wire it and warn, "so the blocking
    guards keep working"), which was right while a below-floor interpreter
    could still run the hooks. Driven as a real subprocess, PATH holding only
    the stub and git, with the conforming stub as the control
    (``TestAPythonTwoHostIsToldTheTruth::test_the_same_stub_answering_as_a_conforming_python_prints_the_claim``).
    """

    VERBS = [
        pytest.param(["init", "{target}"], id="init"),
        pytest.param(["init", "{target}", "--dry-run"], id="init-dry-run"),
        pytest.param(["upgrade", "{target}"], id="upgrade"),
        pytest.param(["upgrade", "{target}", "--execute"], id="upgrade-execute"),
        pytest.param(["merge-settings", "{target}"], id="merge-settings"),
        pytest.param(["fuse", "{target}", "--out", "{out}"], id="fuse"),
    ]

    @staticmethod
    def _tree(root: Path) -> set[str]:
        return {p.relative_to(root).as_posix() for p in root.rglob("*")
                if ".git" not in p.relative_to(root).parts}

    @pytest.mark.parametrize("banner, found", [
        ("Python 3.10.12", "3.10.12"),
        ("Python 3.9.6", "3.9.6"),
    ])
    @pytest.mark.parametrize("argv", VERBS)
    def test_a_below_floor_host_is_refused_before_any_write(self, tmp_path, argv, banner, found):
        target, env = TestAPythonTwoHostIsToldTheTruth._host(tmp_path, banner)
        out_dir = tmp_path / "fused"
        before = self._tree(target)
        words = [w.format(target=target, out=out_dir) for w in argv]
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", *words],
            capture_output=True, text=True, timeout=50, env=env, encoding="utf-8",
        )
        said = result.stdout + result.stderr
        assert result.returncode == 1, said
        stub = tmp_path / "bin" / "python"
        floor = _python_floor.floor_text()
        assert (f"The harness does not run on Python {found} (python at {stub}). "
                f"Update to Python {floor} or newer to install and use it, or put a "
                f"Python {floor} or newer on PATH as python3 or python. Nothing was "
                f"written.") in result.stderr, said
        assert self._tree(target) == before, (
            f"{words[0]} wrote into a tree it refused: "
            f"{sorted(self._tree(target) - before)}")
        assert not out_dir.exists(), f"fuse built a fusion it refused:\n{said}"
        assert "anyway" not in said and "keep working" not in said, said

    def test_the_gate_lets_a_floor_host_through_and_says_nothing(self, tmp_path, monkeypatch, capsys):
        """CONTROL, in-process: the same stub answering as a conforming Python
        is not refused and the gate prints nothing, so a refusal above cannot
        come from the gate refusing everything."""
        from espalier import cli

        stub = write_stub(tmp_path / "python", "#!/bin/sh\necho 'Python 3.14.0'\n")
        monkeypatch.setenv("PATH", str(stub.parent))
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False, raising=False)
        capsys.readouterr()
        assert cli._refuse_below_floor_wiring("init") is None
        assert "does not run on Python" not in capsys.readouterr().err

    def test_a_below_floor_launcher_behind_two_store_aliases_is_refused(self, tmp_path):
        """The resolver's third spelling (the Wave 1 failure-mode review,
        driven on real 3.10): both bare names are Store aliases and `py -3`
        answers a Python below the floor. Recorded by the bare-name loop only,
        it fell through to the literal `python`, which init wired into every
        hook site at rc 0 -- every guard failing open -- while the engine
        before the floor moved had wired `py -3`."""
        import shutil as _shutil

        stubs = tmp_path / "bin"
        stubs.mkdir()
        alias = ("#!/bin/sh\necho 'Python was not found; run without arguments "
                 "to install from the Microsoft Store' >&2\nexit 49\n")
        write_stub(stubs / "python", alias)
        write_stub(stubs / "python3", alias)
        launcher = write_stub(stubs / "py", "#!/bin/sh\necho 'Python 3.10.12'\n")
        git = _shutil.which("git")
        assert git, "git is needed to drive init"
        (stubs / "git").symlink_to(git)
        target = tmp_path / "adopter"
        target.mkdir()
        (target / "README.md").write_text("# adopter\n", encoding="utf-8")
        subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
        env = dict(os.environ)
        env["PATH"] = str(stubs)
        before = self._tree(target)
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target)],
            capture_output=True, text=True, timeout=50, env=env, encoding="utf-8",
        )
        said = result.stdout + result.stderr
        assert result.returncode == 1, said
        floor = _python_floor.floor_text()
        assert (f"The harness does not run on Python 3.10.12 (py -3 at {launcher}). "
                f"Update to Python {floor} or newer to install and use it, or put a "
                f"Python {floor} or newer on PATH as python3 or python. Nothing was "
                f"written.") in result.stderr, said
        assert self._tree(target) == before, (
            f"init wrote into a tree it refused: {sorted(self._tree(target) - before)}")


class TestTheRefusalNamesTheResolversRemedy:
    """TP-706's follow-on (option B of its floor-sentence call, as the
    dispatcher scoped it): where the resolver's own answer is below the floor
    and no candidate clears it -- the pack's trigger, the engine on 3.11
    through pipx or uv and PATH ``python3`` at 3.10.12 -- init's refusal and
    the read-only warning add one clause naming the other remedy: a newer
    Python under any of the resolver's names. It still refuses first, before
    any write, and still says it does not run on the version first; no
    compatibility path, no prompt.

    The clause is the caller's to ask for, and the caller renders the names
    (``cli.resolver_candidate_names``), so a fourth candidate reaches the
    sentence without a second list. In process, so these run on every host;
    the POSIX stub rows in :class:`TestADroppedPythonIsRefusedBeforeAnyWrite`
    drive the same words through a real subprocess.
    """

    @staticmethod
    def _clause() -> str:
        floor = _python_floor.floor_text()
        return f", or put a Python {floor} or newer on PATH as python3 or python"

    def test_the_sentence_adds_the_clause_only_when_asked(self):
        floor = _python_floor.floor_text()
        ruled = (f"The harness does not run on Python 3.10.12. Update to Python "
                 f"{floor} or newer to install and use it.")
        assert _python_floor.does_not_run_sentence("Python 3.10.12") == ruled
        assert _python_floor.does_not_run_sentence(
            "Python 3.10.12", path_remedy=True) == ruled[:-1] + self._clause() + "."

    def test_the_clauses_names_are_the_resolvers_bare_names(self):
        """The clause's names are spelled in `_python_floor`, which cannot
        import cli, so the set is pinned to `cli.RESOLVER_CANDIDATES`: a bare
        name added to or dropped from the resolver reds here before the
        sentence names a remedy the resolver does not try. `py -3` stays out:
        a spelling, not a PATH name, and a Python it picks is the sentence's
        own "Update" remedy (TP-706)."""
        from espalier import cli

        assert set(_python_floor.PATH_REMEDY_NAMES) == set(cli.RESOLVER_CANDIDATES)
        clause = _python_floor.does_not_run_sentence("Python 3.10.12", path_remedy=True)
        named = clause.rsplit(" on PATH as ", 1)[1].rstrip(".").split(" or ")
        assert set(named) == set(cli.RESOLVER_CANDIDATES), clause

    def test_inits_refusal_names_the_resolvers_remedy(self, monkeypatch, capsys):
        from espalier import cli

        answer = (("python3", "/usr/bin/python3", "Python 3.10.12"), None)
        monkeypatch.setattr(cli, "_BELOW_FLOOR_ANSWER", None)

        def resolver() -> str:
            cli._BELOW_FLOOR_ANSWER = answer
            return "python3"

        monkeypatch.setattr(cli, "_detect_python_command", resolver)
        capsys.readouterr()
        assert cli._refuse_below_floor_wiring("init") == 1
        floor = _python_floor.floor_text()
        assert capsys.readouterr().err == (
            f"[init] FAIL: The harness does not run on Python 3.10.12 (python3 at "
            f"/usr/bin/python3). Update to Python {floor} or newer to install and "
            f"use it{self._clause()}. Nothing was written.\n")

    def test_the_read_only_warning_names_the_resolvers_remedy(self, monkeypatch, capsys):
        from espalier import cli

        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", False)
        monkeypatch.setattr(cli, "_BELOW_FLOOR_REFUSING", False)
        monkeypatch.setattr(cli, "_remedy_interpreter", lambda **_: ("python3.12", True))
        capsys.readouterr()
        cli._warn_interpreter_below_floor(("python3", "/usr/bin/python3", "Python 3.10.12"))
        floor = _python_floor.floor_text()
        assert capsys.readouterr().err == (
            f"WARNING: The harness does not run on Python 3.10.12 (python3 at "
            f"/usr/bin/python3). Update to Python {floor} or newer to install and "
            f"use it{self._clause()}. After upgrading, re-wire with "
            f"`python3.12 -m espalier init . --rewire-interpreter`.\n")

    def test_the_sites_that_name_another_interpreter_keep_the_ruled_words(self):
        """The clause rides only where the resolver's answer is named with no
        candidate clearing the floor. ``espalier/__init__.py`` is the engine
        itself below the floor. ``_start_refusal`` is a hook run by the
        interpreter it names. ``session_start``'s wired-interpreter line could
        tell (``banner_below_floor`` exits first, so it runs on 3.11 or newer
        and names a different wired interpreter), and keeps the ruled words on
        the ruling, not for want of knowing. Doctor names a WIRED interpreter,
        possibly beside a good one already on PATH, where "put one there"
        points the wrong way; its remedy is the rewire hint instead.

        Two halves. The engine side is read as calls, not text: every call of
        ``does_not_run_sentence`` under ``espalier/`` (the vendored mirror
        aside) that passes ``path_remedy`` or a ``**`` mapping must sit in one
        of the two functions, so a spelling the text scan missed, or a new
        caller in another module, reds here. The hook side and ``__init__``
        spell the words by hand, so their text must not hold the clause."""
        allowed = {"_warn_interpreter_below_floor", "_refuse_below_floor_wiring"}
        found: set[str] = set()
        from tests._live_tree import checkout_rglob

        for path in sorted(checkout_rglob(REPO_ROOT / "espalier", "*.py", root=REPO_ROOT)):
            if "_vendor" in path.relative_to(REPO_ROOT).parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    if not isinstance(node, ast.Call):
                        continue
                    callee = node.func
                    name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
                    if name != "does_not_run_sentence":
                        continue
                    if any(k.arg in (None, "path_remedy") for k in node.keywords):
                        found.add(f"{path.relative_to(REPO_ROOT).as_posix()}::{fn.name}")
        assert {site.rsplit("::", 1)[1] for site in found} == allowed, sorted(found)
        assert all(site.startswith("espalier/cli.py::") for site in found), sorted(found)
        clause = _python_floor.does_not_run_sentence("Python 3.10.12", path_remedy=True)
        words = clause.split("install and use it", 1)[1].rstrip(".")
        for rel in ("espalier/__init__.py", "tools/cc/hooks/_start_refusal.py",
                    "tools/cc/hooks/session_start.py"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "install and use it" in text, rel
            assert " on PATH as python3 or python" not in text and words not in text, (
                f"{rel} says the resolver's remedy clause, which the ruling keeps "
                f"to init's refusal and the read-only warning")


class TestTheEngineSaysTheFloorFirst:
    """`espalier/__init__.py`'s floor sentence (air's ruling on request
    79c59b, 2026-11-07): every entry imports the package before
    `espalier.cli`, so the check there is what a host below the floor reads,
    never a traceback from a module that needs a newer interpreter."""

    #: What may stand above the check: the docstring, the `__future__`
    #: import, `import sys` (the check reads it) and the `_FLOOR` literal.
    @staticmethod
    def _allowed_above_the_check(node: ast.stmt, index: int) -> bool:
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            return isinstance(node.value.value, str)
        if isinstance(node, ast.ImportFrom):
            return node.module == "__future__"
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names] == ["sys"]
        if isinstance(node, ast.Assign):
            return ([getattr(t, "id", None) for t in node.targets] == ["_FLOOR"]
                    and isinstance(node.value, ast.Tuple))
        return False

    def test_the_check_is_the_first_statement_that_does_anything(self):
        """Ruff reads syntax only: an import placed above the check (one that
        pulls a module needing the floor) parses on 3.9 and still kills the
        sentence with a traceback. So the order is read here, with ast."""
        tree = ast.parse((REPO_ROOT / "espalier" / "__init__.py").read_text(encoding="utf-8"))
        checks = [i for i, node in enumerate(tree.body)
                  if isinstance(node, ast.If) and "sys.version_info" in ast.unparse(node.test)]
        assert checks, "espalier/__init__.py has no `sys.version_info` check"
        above = tree.body[:checks[0]]
        strays = [ast.unparse(node) for i, node in enumerate(above)
                  if not self._allowed_above_the_check(node, i)]
        assert not strays, (
            f"espalier/__init__.py runs {strays!r} before its floor check: on a "
            f"host below the floor that line runs first and can raise instead "
            f"of the sentence"
        )

    def test_a_below_floor_version_reads_the_sentence_and_exits_1(self):
        """Every CI cell runs this (a real 3.10 row would only skip there): the
        version is stubbed before the package is imported from this checkout.
        The control is the same command unstubbed, which imports cleanly."""
        floor = _python_floor.floor_text()
        stubbed = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.version_info = (3, 10, 21, 'final', 0); import espalier"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=50, encoding="utf-8",
        )
        assert stubbed.returncode == 1, (stubbed.returncode, stubbed.stdout, stubbed.stderr)
        assert (f"espalier-harness does not run on Python 3.10.21. Update to Python "
                f"{floor} or newer to install and use it.") in stubbed.stderr, stubbed.stderr
        assert "Traceback" not in stubbed.stderr, stubbed.stderr
        control = subprocess.run(
            [sys.executable, "-c", "import espalier"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=50, encoding="utf-8",
        )
        assert control.returncode == 0, (control.stdout, control.stderr)

    @staticmethod
    def _import_as(version: "tuple[int, int, int]") -> subprocess.CompletedProcess:
        stub = f"({version[0]}, {version[1]}, {version[2]}, 'final', 0)"
        return subprocess.run(
            [sys.executable, "-c", f"import sys; sys.version_info = {stub}; import espalier"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=50, encoding="utf-8",
        )

    def test_the_boundary_is_the_floor_itself(self):
        """Derived from `MIN_PYTHON`, never spelled, so the next floor move
        keeps testing its own boundary: exactly the floor imports, the minor
        below it refuses. A `<=` written for `<` reds here on any interpreter,
        not only on the floor's own CI cell."""
        major, minor = _python_floor.MIN_PYTHON
        at_floor = self._import_as((major, minor, 0))
        assert at_floor.returncode == 0, (
            f"Python {major}.{minor}.0 is the floor and was refused: {at_floor.stderr}")
        below = self._import_as((major, minor - 1, 0))
        assert below.returncode == 1, (below.returncode, below.stderr)
        assert (f"espalier-harness does not run on Python {major}.{minor - 1}.0. Update to "
                f"Python {_python_floor.floor_text()} or newer") in below.stderr, below.stderr

    def test_the_check_names_nothing_but_sys_and_the_floor(self):
        """The order row reads what stands ABOVE the check; this reads the
        check itself. A refactor that renders the sentence through
        `_python_floor.does_not_run_sentence` would sit below every import
        rule and still import a module that must parse on the old
        interpreter. So the `if` may name `sys`, `_FLOOR`, `SystemExit` and
        builtins, and reach attributes only through `sys`."""
        import builtins

        tree = ast.parse((REPO_ROOT / "espalier" / "__init__.py").read_text(encoding="utf-8"))
        check = next(node for node in tree.body
                     if isinstance(node, ast.If) and "sys.version_info" in ast.unparse(node.test))
        allowed = {"sys", "_FLOOR", "SystemExit"} | set(dir(builtins))
        strays = sorted({node.id for node in ast.walk(check)
                         if isinstance(node, ast.Name) and node.id not in allowed})
        assert not strays, (
            f"espalier/__init__.py's floor check names {strays}: on a host below "
            f"the floor anything it reaches beyond sys and the literal can raise "
            f"before the sentence"
        )


class TestTheRetiredWiringPromiseIsGone:
    """The 2026-09-03 decision wired a below-floor interpreter "so the blocking
    guards keep working"; the 2026-11-07 ruling dropped it (a dropped Python is
    refused before any write). The promise was repeated in six surfaces and
    the pack's hand list named five (the Wave 1 failure-mode review found the
    sixth in `init --help`), so the retired phrases are read across the live
    code and docs here rather than remembered. Record surfaces are left out
    (`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`)."""

    RETIRED = (
        "wiring it anyway",
        "guards keep working",
        "guards working while",
        "keep the blocking guards working",
        "leaves the blocking guards working",
    )
    #: path -> why that file may still carry one. Every live promise was
    #: reworded in the Wave 1 lane; what is left quotes the old output as a
    #: record.
    ALLOWED: dict[str, str] = {
        "docs/FAILURE_MODES.md": (
            "the 'two classifiers of one string' entry quotes, in the past "
            "tense, what `init` printed about one interpreter in the DEF-727 "
            "incident: a record of the old output, not a present promise"
        ),
    }

    @staticmethod
    def _surfaces() -> list[Path]:
        from tests._live_tree import checkout_glob, checkout_rglob
        from tests.test_doc_source_citations import _RECORD_SURFACE_DOCS

        files = [p for p in checkout_rglob(REPO_ROOT / "espalier", "*.py")
                 if not {"_vendor", "assets"} & set(p.relative_to(REPO_ROOT / "espalier").parts)]
        files += sorted(checkout_glob(REPO_ROOT / "tools" / "cc" / "hooks", "*.py"))
        files += [REPO_ROOT / "README.md"]
        files += [p for p in sorted(checkout_glob(REPO_ROOT / "docs", "*.md"))
                  if p.relative_to(REPO_ROOT).as_posix() not in _RECORD_SURFACE_DOCS]
        return files

    @staticmethod
    def _flattened(text: str) -> str:
        # A phrase wrapped across comment or prose lines still reads as one.
        return re.sub(r"\s*\n\s*(?:#+|//)?\s*", " ", text).lower()

    def hits(self, files: list[Path]) -> list[str]:
        found = []
        for path in files:
            text = self._flattened(path.read_text(encoding="utf-8"))
            rel = path.relative_to(REPO_ROOT).as_posix()
            found += [f"{rel}: {phrase!r}" for phrase in self.RETIRED
                      if phrase in text and rel not in self.ALLOWED]
        return found

    def test_no_live_surface_promises_working_guards_below_the_floor(self):
        files = self._surfaces()
        assert len(files) > 50, f"the census read too little to mean anything: {len(files)} files"
        found = self.hits(files)
        assert not found, (
            "a live surface still says a below-floor interpreter is wired so the "
            "guards keep working; the 2026-11-07 ruling refuses it before any "
            "write (say espalier/_python_floor.py::does_not_run_sentence's words, "
            "or add the file to ALLOWED with the reason):\n  " + "\n  ".join(found)
        )


#: The deny hooks and the event each answers (TP-706 2-C), read from the
#: canonical roster, so a blocking hook declared later gets every floor row the
#: day it is declared. Each says the floor itself, before any sibling imports,
#: when an interpreter below it runs the hook.
DENY_HOOKS = tuple((script.removesuffix(".py"), event)
                   for script, event in GOVERNANCE_BLOCKING_HOOKS.items())
#: The five files the floor's refusal runs through, the files pyproject.toml's
#: [tool.ruff] per-file-target-version holds at py310 (the 2026-11-07 ruling).
FLOOR_VOICE_FILES = ("_start_refusal",) + tuple(hook for hook, _ in DENY_HOOKS)


def _deny_payload(event: str, cwd: Path, *, continued: bool = False) -> dict:
    if event == "PreToolUse":
        return {"hook_event_name": event, "tool_name": "Write", "cwd": str(cwd),
                "tool_input": {"file_path": "x.py", "content": ""}}
    if event == "ConfigChange":
        return {"hook_event_name": event, "source": "project", "cwd": str(cwd),
                "file_path": ".claude/settings.json"}
    return {"hook_event_name": event, "stop_hook_active": continued, "cwd": str(cwd)}


def _run_hook_as(hook: str, version: "tuple[int, int, int]", payload: dict,
                 cwd: Path, env_extra: "dict[str, str] | None" = None) -> subprocess.CompletedProcess:
    """Run a deny hook as Claude Code does (as `__main__`, the payload on
    stdin) with `sys.version_info` stubbed first, so every CI cell reads what
    a below-floor host would (a real old-interpreter row would only skip
    there). The project root is a scratch directory, so the refusal's
    best-effort audit record lands there and never in this checkout."""
    path = str(HOOKS_DIR / f"{hook}.py")
    stub = f"({version[0]}, {version[1]}, {version[2]}, 'final', 0)"
    code = (f"import runpy, sys; sys.version_info = {stub}; sys.argv = [{path!r}]; "
            f"runpy.run_path({path!r}, run_name='__main__')")
    env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
    env["CLAUDE_PROJECT_DIR"] = str(cwd)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), cwd=str(cwd),
                          capture_output=True, text=True, timeout=scaled(50), encoding="utf-8",
                          env=env)


def _start_refusal_module():
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    import _start_refusal  # type: ignore[import-not-found]
    return _start_refusal


class TestTheDenyHooksSayTheFloor:
    """TP-706 2-C: a deny hook run by an interpreter below the floor answers
    with the structured refusal naming the floor (the one sentence,
    `_python_floor.does_not_run_sentence`'s words), never a sibling's import
    error and never an exit 1, which the hook protocol reads as non-blocking.
    The base before 2-C ran the hooks below the floor and judged the call, so
    every row here reds on it."""

    @pytest.mark.parametrize("hook,event", DENY_HOOKS)
    def test_a_below_floor_interpreter_is_refused_with_the_floor(self, hook, event, tmp_path):
        major, minor = _python_floor.MIN_PYTHON
        run = _run_hook_as(hook, (major, minor - 1, 21), _deny_payload(event, tmp_path), tmp_path)
        assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
        assert "Traceback" not in run.stderr, run.stderr
        out = json.loads(run.stdout)
        if event == "PreToolUse":
            decision = out["hookSpecificOutput"]
            assert decision["hookEventName"] == event, out
            assert decision["permissionDecision"] == "deny", out
            reason = decision["permissionDecisionReason"]
        else:
            assert out["decision"] == "block", out
            reason = out["reason"]
        assert reason.startswith(f"{hook} cannot run here. "), reason
        assert _python_floor.does_not_run_sentence(f"Python {major}.{minor - 1}.21") in reason, reason

    @pytest.mark.parametrize("hook,event", DENY_HOOKS)
    def test_maintenance_mode_does_not_lift_the_floor(self, hook, event, tmp_path):
        """The floor is not friction: maintenance mode lifts the zone and plan
        checks, and below the floor the refusal still answers, since a dropped
        Python is never run in a reduced mode."""
        major, minor = _python_floor.MIN_PYTHON
        run = _run_hook_as(hook, (major, minor - 1, 21), _deny_payload(event, tmp_path), tmp_path,
                           env_extra={"ESPALIER_MAINTENANCE_MODE": "1"})
        assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
        out = json.loads(run.stdout)
        reason = (out["hookSpecificOutput"]["permissionDecisionReason"] if event == "PreToolUse"
                  else out["reason"])
        assert reason.startswith(f"{hook} cannot run here. "), out

    def test_a_stop_continued_after_the_refusal_goes_through(self, tmp_path):
        """A pause, never a lockout: the protocol's loop signal lets the next
        Stop end the turn."""
        major, minor = _python_floor.MIN_PYTHON
        run = _run_hook_as("stop_gate", (major, minor - 1, 21),
                           _deny_payload("Stop", tmp_path, continued=True), tmp_path)
        assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
        assert run.stdout == "", run.stdout

    def test_the_boundary_is_the_floor_itself(self, monkeypatch, capsys):
        """Derived from `MIN_PYTHON`: exactly the floor returns, the minor
        below refuses. In process, with the record captured, so nothing is
        written to this checkout's audit log."""
        refusal = _start_refusal_module()
        records: list = []
        monkeypatch.setattr(refusal, "_record", lambda kind, details: records.append((kind, details)))
        major, minor = _python_floor.MIN_PYTHON
        monkeypatch.setattr(sys, "version_info", (major, minor, 0, "final", 0))
        assert refusal.refuse_below_floor("write_guard", "PreToolUse") is None
        assert capsys.readouterr().out == "" and records == []
        monkeypatch.setattr(sys, "version_info", (major, minor - 1, 99, "final", 0))
        with pytest.raises(SystemExit) as exited:
            refusal.refuse_below_floor("write_guard", "PreToolUse")
        monkeypatch.undo()
        assert exited.value.code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", out
        assert records == [("pretooluse_blocked_internal_error",
                            {"hook": "write_guard", "skew": "below floor",
                             "python": f"{major}.{minor - 1}.99"})], records

    def test_importing_the_refusal_below_the_floor_says_nothing(self):
        """The check is a call each hook makes, never this module's load:
        `_denial_reasons` imports it, and `session_start` imports that, so a
        load-time check would answer a SessionStart with a PreToolUse deny."""
        major, minor = _python_floor.MIN_PYTHON
        code = (f"import sys; sys.version_info = ({major}, {minor - 1}, 21, 'final', 0); "
                f"sys.path.insert(0, {str(HOOKS_DIR)!r}); "
                "import _start_refusal, _denial_reasons; print('imported')")
        run = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), capture_output=True,
                             text=True, timeout=scaled(50), encoding="utf-8")
        assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
        assert run.stdout == "imported\n", run.stdout


class TestTheBannerSaysTheFloor:
    """TP-706, the ruling on request 881ed0: below the floor the SessionStart
    banner is the floor's warning alone, said before any sibling imports. The
    siblings read espalier.toml through tomllib, which the old interpreter
    lacks; before the block, driven under a real 3.10.21 on a copy of the
    checkout wired to it, the crash took the whole banner, the warning with it.
    Here the version is stubbed, so every CI cell reads what a below-floor host
    would, and the base without the block builds the full banner and reds."""

    def test_a_below_floor_start_gives_the_floor_banner_alone(self, tmp_path):
        major, minor = _python_floor.MIN_PYTHON
        found = f"{major}.{minor - 1}.21"
        payload = {"session_id": "floor", "source": "startup", "cwd": str(tmp_path),
                   "hook_event_name": "SessionStart"}
        run = _run_hook_as("session_start", (major, minor - 1, 21), payload, tmp_path)
        assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
        assert run.stderr == "", run.stderr
        out = json.loads(run.stdout)
        assert set(out) == {"hookSpecificOutput"}, out
        spec = out["hookSpecificOutput"]
        assert set(spec) == {"hookEventName", "additionalContext"}, spec
        assert spec["hookEventName"] == "SessionStart", spec
        lines = spec["additionalContext"].splitlines()
        assert lines[0] == f"=== Espalier-Harness === SessionStart (short: Python {found} is below the floor) ===", lines
        assert len(lines) == 2, lines
        assert lines[1].startswith("[WARN] session_start cannot run here. "), lines
        sentence = _python_floor.does_not_run_sentence(f"Python {found}", f" (at {sys.executable})")
        assert sentence in lines[1], lines

    def test_the_banner_boundary_is_the_floor_itself(self, monkeypatch, capsys):
        """Derived from `MIN_PYTHON`: exactly the floor returns, the minor
        below gives the banner. In process, with the record captured, so
        nothing is written to this checkout's audit log."""
        refusal = _start_refusal_module()
        records: list = []
        monkeypatch.setattr(refusal, "_record", lambda kind, details: records.append((kind, details)))
        major, minor = _python_floor.MIN_PYTHON
        monkeypatch.setattr(sys, "version_info", (major, minor, 0, "final", 0))
        assert refusal.banner_below_floor("session_start") is None
        assert capsys.readouterr().out == "" and records == []
        monkeypatch.setattr(sys, "version_info", (major, minor - 1, 99, "final", 0))
        with pytest.raises(SystemExit) as exited:
            refusal.banner_below_floor("session_start")
        monkeypatch.undo()
        assert exited.value.code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart", out
        assert "permissionDecision" not in out["hookSpecificOutput"], out
        assert records == [("sessionstart_failed_open_crash",
                            {"hook": "session_start", "skew": "below floor",
                             "python": f"{major}.{minor - 1}.99"})], records


#: `_start_refusal.py`'s top-level imports, each a name every interpreter down
#: to the oldest one the refusal must speak to has (TP-706 2-D). An import
#: added there is added here knowingly: `import tomllib`, `from datetime import
#: UTC` or `from typing import Self` parse everywhere and pass ruff's py310
#: target, and each kills the refusal on the interpreter it exists for.
START_REFUSAL_IMPORTS = frozenset({
    ("__future__", "annotations"), ("sys", None), ("types", None),
    ("pathlib", "Path"), ("typing", "NoReturn"),
})


def _top_level_import_strays_in(body: list, allowed: frozenset) -> list[str]:
    strays = []
    for node in body:
        if isinstance(node, ast.Import):
            strays += [alias.name for alias in node.names if (alias.name, None) not in allowed]
        elif isinstance(node, ast.ImportFrom):
            strays += [f"{node.module}.{alias.name}" for alias in node.names
                       if (node.module, alias.name) not in allowed]
    return strays


def _top_level_import_strays(source: str) -> list[str]:
    return _top_level_import_strays_in(ast.parse(source).body, START_REFUSAL_IMPORTS)


def _statement_imports(node: ast.AST) -> set[str]:
    """Every module a statement imports when it runs: anywhere inside it but a
    function's body, whose imports run when it is called, not when it is
    defined (write_guard defines its judging-child parent above the floor
    call and calls it after the floor speaks, DEF-3048). A module-level call
    of such a function is not followed."""
    names: set[str] = set()
    pending = [node]
    while pending:
        sub = pending.pop()
        if isinstance(sub, ast.Import):
            names.update(alias.name for alias in sub.names)
        elif isinstance(sub, ast.ImportFrom):
            names.add(sub.module or "")
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        pending.extend(ast.iter_child_nodes(sub))
    return names


#: Every module a hook can import from its own folder or the tools folder
#: above it: a sibling is any of these, underscored or not (`stop_gate` imports
#: `ship`, whose top loads five more).
def _sibling_modules() -> frozenset:
    from tests._live_tree import checkout_glob
    return frozenset(path.stem for folder in (HOOKS_DIR, HOOKS_DIR.parent)
                     for path in checkout_glob(folder, "*.py"))


def _first_sibling_import(body: list) -> int | None:
    """The index of the first statement importing a sibling other than the
    start refusal."""
    siblings = _sibling_modules()
    return next((i for i, node in enumerate(body)
                 if any((name.startswith("_") or name.split(".")[0] in siblings)
                        and name not in ("_start_refusal", "__future__")
                        for name in _statement_imports(node))), None)


def _unconditional_calls(body: list) -> list[ast.Call]:
    """The calls a block makes as statements of its own, through a `try`'s
    body and its `else` (which guard an import, not a condition) and never
    into an `if` or a loop, so a floor call nested under a second condition is
    not one."""
    calls: list[ast.Call] = []
    for stmt in body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            calls.append(stmt.value)
        elif isinstance(stmt, ast.Try):
            calls += _unconditional_calls(stmt.body) + _unconditional_calls(stmt.orelse)
    return calls


def _main_guard_calls(body: list, func: str, args: list) -> list[int]:
    """The indices of the `if __name__ == "__main__"` statements that call
    ``func`` with exactly ``args``, unconditionally inside the block."""
    return [i for i, node in enumerate(body) if isinstance(node, ast.If)
            and ast.unparse(node.test).replace("'", '"') == '__name__ == "__main__"'
            and any(ast.unparse(call.func) == func
                    and [ast.literal_eval(arg) for arg in call.args] == args
                    for call in _unconditional_calls(node.body))]


#: Names the refusal's own functions import on the old interpreter, beyond the
#: module's top-level set.
FLOOR_PATH_IMPORTS = frozenset({("json", None)})


def _unguarded_import_strays(body: list, allowed: frozenset) -> list[str]:
    """Imports in ``body`` outside ``allowed``, skipping a `try` whose handler
    catches every exception (a best-effort step that cannot stop the
    refusal) and nested definitions."""
    strays: list[str] = []
    for node in body:
        if isinstance(node, ast.Try) and any(
                handler.type is None or ast.unparse(handler.type) in ("Exception", "BaseException")
                for handler in node.handlers):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            strays += _top_level_import_strays_in([node], allowed)
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for field in ("body", "orelse", "finalbody", "handlers"):
                strays += _unguarded_import_strays(
                    [n for n in getattr(node, field, []) if isinstance(n, ast.AST)], allowed)
    return strays


def _floor_path_import_strays(source: str) -> list[str]:
    """``function: module`` for each import the refusal runs below the floor
    that is not a pinned 3.10 name: inside `refuse_below_floor`,
    `banner_below_floor` and every module function they reach by name."""
    funcs = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    allowed = START_REFUSAL_IMPORTS | FLOOR_PATH_IMPORTS
    seen: set[str] = set()
    todo = ["refuse_below_floor", "banner_below_floor"]
    strays: list[str] = []
    while todo:
        name = todo.pop()
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        strays += [f"{name}: {stray}" for stray in _unguarded_import_strays(funcs[name].body, allowed)]
        todo += [node.func.id for node in ast.walk(funcs[name])
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert {"refuse_below_floor", "banner_below_floor"} <= seen, "the refusal's entry points moved"
    return strays


def _floor_call_order(source: str, hook: str, event: str) -> str | None:
    """None when the hook's module body calls `refuse_below_floor(hook,
    event)` under `__main__`, after the statement importing `_start_refusal`
    and before the first statement importing any other sibling; else what is
    wrong."""
    body = ast.parse(source).body
    start = next((i for i, node in enumerate(body) if "_start_refusal" in _statement_imports(node)), None)
    sibling = _first_sibling_import(body)
    calls = _main_guard_calls(body, "_start_refusal.refuse_below_floor", [hook, event])
    if start is None:
        return "no statement imports _start_refusal"
    if not calls:
        return f"no `if __name__ == '__main__'` calls refuse_below_floor({hook!r}, {event!r})"
    if not start < calls[0] < (sibling if sibling is not None else len(body)):
        return (f"the floor call is statement {calls[0]}; it must come after the _start_refusal "
                f"import ({start}) and before the first other sibling import ({sibling})")
    return None


#: The standard-library names `session_start.py` imports before its floor
#: block (TP-706, the ruling on request 881ed0), each one Python 3.10 has. An
#: import that fails there fails before the banner can say the floor, so a
#: name added above the block is added here knowingly.
SESSION_START_PRE_FLOOR_IMPORTS = frozenset({
    ("__future__", "annotations"), ("enum", None), ("importlib.util", None), ("json", None),
    ("os", None), ("re", None), ("shutil", None), ("subprocess", None), ("sys", None),
    ("tempfile", None), ("textwrap", None), ("threading", None), ("time", None),
    ("datetime", "datetime"), ("datetime", "timezone"), ("pathlib", "Path"),
    ("typing", "Any"), ("typing", "Callable"), ("typing", "NamedTuple"),
})


def _banner_floor_order(source: str) -> str | None:
    """None when `session_start`'s module body imports the start refusal and
    calls `banner_below_floor("session_start")` in one `__main__` block that
    comes before its first other sibling import, with only the pinned names
    imported above that block; else what is wrong."""
    body = ast.parse(source).body
    calls = _main_guard_calls(body, "_start_refusal.banner_below_floor", ["session_start"])
    if not calls:
        return "no `if __name__ == '__main__'` calls banner_below_floor('session_start')"
    if "_start_refusal" not in _statement_imports(body[calls[0]]):
        return "the floor block does not import _start_refusal itself"
    sibling = _first_sibling_import(body)
    if sibling is not None and not calls[0] < sibling:
        return (f"the floor block is statement {calls[0]}; it must come before the first "
                f"other sibling import ({sibling})")
    strays = _top_level_import_strays_in(body[:calls[0]], SESSION_START_PRE_FLOOR_IMPORTS)
    if strays:
        return f"imports above the floor block not pinned as Python 3.10 names: {strays}"
    return None


class TestTheFloorVoiceStaysReachable:
    """TP-706 2-D. The refusal speaks only if everything it runs through
    imports on the old interpreter: the syntax half is ruff's per-file py310
    target (Wave 1's 1-G); these rows are the import half and the order."""

    def test_the_refusal_module_imports_only_what_an_old_interpreter_has(self):
        source = (HOOKS_DIR / "_start_refusal.py").read_text(encoding="utf-8")
        strays = _top_level_import_strays(source)
        assert not strays, (
            f"_start_refusal.py imports {strays} at its top; below the floor that can "
            f"fail before the refusal speaks (add it to START_REFUSAL_IMPORTS only if "
            f"Python 3.10 has it)"
        )
        # Earn the red on every run: each shape the row exists for is caught.
        for planted in ("import tomllib\n", "from datetime import UTC\n", "from typing import Self\n"):
            assert _top_level_import_strays(planted + source), planted

    def test_the_refusal_path_imports_only_what_an_old_interpreter_has(self):
        """The import half inside the functions: a name the old interpreter
        lacks, imported in the refusal or a helper it reaches, is an exit 1
        with empty stdout there, and ruff and the 3.10 mypy row pass it."""
        source = (HOOKS_DIR / "_start_refusal.py").read_text(encoding="utf-8")
        strays = _floor_path_import_strays(source)
        assert not strays, (
            f"the below-floor refusal imports {strays}; add a name to FLOOR_PATH_IMPORTS "
            f"only if Python 3.10 has it, or guard a best-effort step with a broad except"
        )
        # Earn the red on every run: a planted import in an entry point and in a
        # helper it reaches is caught; the guarded audit record is not.
        for func in ("def refuse_below_floor", "def banner_below_floor", "def _read_payload"):
            start = source.index(func)
            at = source.index("    import json\n", start)
            planted = source[:at] + "    import tomllib\n" + source[at:]
            assert _floor_path_import_strays(planted), func

    @pytest.mark.parametrize("hook,event", DENY_HOOKS)
    def test_each_deny_hook_says_the_floor_before_any_sibling(self, hook, event):
        source = (HOOKS_DIR / f"{hook}.py").read_text(encoding="utf-8")
        wrong = _floor_call_order(source, hook, event)
        assert wrong is None, f"{hook}.py: {wrong}"
        # The mutation: the call moved below the sibling block reds.
        call = f'if __name__ == "__main__":\n    _start_refusal.refuse_below_floor("{hook}", "{event}")\n'
        assert call in source, f"{hook}.py's floor call is not in the shape this row mutates"
        moved = source.replace(call, "", 1) + "\n" + call
        assert _floor_call_order(moved, hook, event) is not None
        # A sibling without an underscore imported above the call reds, and so
        # does the call nested under a second condition.
        assert _floor_call_order(source.replace(call, "import ship\n" + call, 1), hook, event) is not None
        nested = call.replace("    _start_refusal", "    if not os.environ.get('X'):\n        _start_refusal")
        assert _floor_call_order(source.replace(call, nested, 1), hook, event) is not None
        # A sibling imported inside a function defined above the call runs at
        # the call, not at the definition, so it reads clean; the same import
        # at module level reds (above, `import ship`).
        deferred = "def _probe():\n    import _hook_utils\n    import ship\n\n\n" + call
        assert _floor_call_order(source.replace(call, deferred, 1), hook, event) is None
        hoisted = "class _Probe:\n    import _hook_utils\n\n\n" + call
        assert _floor_call_order(source.replace(call, hoisted, 1), hook, event) is not None

    def test_the_banner_says_the_floor_before_any_sibling(self):
        """The reporter's half (the ruling on request 881ed0): below the floor
        the banner's siblings read espalier.toml through tomllib, so the floor
        block comes before them, with only pinned 3.10 names imported above."""
        source = (HOOKS_DIR / "session_start.py").read_text(encoding="utf-8")
        wrong = _banner_floor_order(source)
        assert wrong is None, f"session_start.py: {wrong}"
        # The mutations: the block moved below the first sibling import, and a
        # name 3.10 lacks imported above it, each red.
        sibling = "import _hook_utils  # noqa: E402\n"
        start = source.index('if __name__ == "__main__":\n    try:\n        import _start_refusal')
        end = source.index(sibling)
        assert start < end, "session_start.py's floor block is not in the shape this row mutates"
        block = source[start:end]
        moved = source[:start] + sibling + block + source[end + len(sibling):]
        assert _banner_floor_order(moved) is not None
        planted = source.replace("import enum\n", "import enum\nfrom datetime import UTC\n", 1)
        assert planted != source and _banner_floor_order(planted) is not None

    def test_the_five_files_type_check_against_python_3_10(self, tmp_path):
        """The 3.10 import check Wave 1 retired when mypy's target moved to
        3.11 (air's note 000030): a `from typing import Self` atop a deny hook
        passes ruff's py310 table and mypy at 3.11, and under a real 3.10 is
        an exit 1 with empty stdout. Its own cache directory, never the
        checkout's, which the tier's own mypy line writes."""
        files = [str(HOOKS_DIR / f"{name}.py") for name in FLOOR_VOICE_FILES]
        run = subprocess.run(
            [sys.executable, "-m", "mypy", "--python-version", "3.10", "--follow-imports=silent",
             "--cache-dir", str(tmp_path / "mypy-cache"), *files],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=scaled(50), encoding="utf-8",
        )
        assert run.returncode == 0, run.stdout + run.stderr

    def test_the_floor_voice_files_are_ruffs_py310_table(self):
        """Ruff's per-file py310 target is the syntax half of these rows, so
        its table and the files the refusal runs through are one set: a deny
        hook added to the roster without its ruff line is named here."""
        import tomllib
        config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        table = config["tool"]["ruff"]["per-file-target-version"]
        py310 = {path for path, target in table.items() if target == "py310"}
        assert py310 == {f"tools/cc/hooks/{name}.py" for name in FLOOR_VOICE_FILES}, py310

    def test_session_start_parses_as_python_3_10(self):
        """The banner's file is outside ruff's py310 table, and a below-floor
        interpreter parses the whole file before its floor block runs, so
        syntax only newer interpreters read loses the banner to a SyntaxError."""
        source = (HOOKS_DIR / "session_start.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 10))
        planted = source + "\ntry:\n    pass\nexcept* ValueError:\n    pass\n"
        with pytest.raises(SyntaxError):
            ast.parse(planted, feature_version=(3, 10))


#: The fallback spellings a parser shim takes when the stdlib TOML module may be
#: missing (TP-706 2-E), assembled from fragments so this file's own source
#: never matches them. Never the shared reader's name (`_toml_parser`), which
#: stays and which `stop_gate` imported by name.
_BASE = "tom" + "l"
_SHIM = _BASE + "i"         # the third-party backport
_STDLIB = _BASE + "lib"     # the standard library module
_FALLBACK_SPELLINGS = re.compile("|".join((
    r"import " + _SHIM + r"\b",
    _SHIM + r" as " + _STDLIB,
    r"from " + _SHIM + r"\b",
    _STDLIB + r" = None",
    _STDLIB + r" is None",
    _STDLIB + r" is not None",
)))
#: The three regenerated mirror trees: their sources are walked where they live.
_MIRROR_TREES = ("espalier/_vendor/", "espalier/assets/", "examples/dogfooding/")


def _python_sources() -> list[Path]:
    from tests._live_tree import checkout_rglob

    return sorted(path for path in checkout_rglob(REPO_ROOT, "*.py")
                  if not path.relative_to(REPO_ROOT).as_posix().startswith(_MIRROR_TREES))


def _module_top_imports(source: str, module: str) -> list[int]:
    """Lines of every statement that imports ``module`` when the file is
    loaded: the module body, through its top-level ``if``/``try``/``with``
    blocks and class bodies (which run at import), never a function body."""
    found: list[int] = []

    def walk(body: list) -> None:
        for node in body:
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == module for a in node.names):
                found.append(node.lineno)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == module:
                found.append(node.lineno)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):
                    walk([n for n in getattr(node, field, []) if isinstance(n, ast.AST)])

    walk(ast.parse(source).body)
    return found


class TestTheFloorHasNoParserShims:
    """TP-706 2-E and 2-G. At a 3.11 floor every interpreter the package allows
    has the stdlib TOML module, so the fallback arms are gone (their own tests
    went with them) and these rows keep them gone: the spellings across the
    tracked Python sources, and the one placement that would silence the
    hooks below the floor."""

    def test_no_tracked_python_file_spells_a_parser_fallback(self):
        files = _python_sources()
        assert len(files) > 500, f"the walk read too little to mean anything: {len(files)} files"
        hits = []
        for path in files:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _FALLBACK_SPELLINGS.search(line):
                    hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: {line.strip()}")
        assert not hits, (
            "a fallback for a missing stdlib TOML module came back; every supported "
            "interpreter has it (TP-706):\n  " + "\n  ".join(hits)
        )
        # Earn the red on every run: each spelling the row exists for is caught.
        # The planted lines spell the two names by character, never from the
        # fragments above, so a fragment that spells the wrong module reds here.
        backport, stdlib = "".join(["t", "o", "m", "l", "i"]), "".join(["t", "o", "m", "l", "l", "i", "b"])
        for planted in (f"try:\n    import {backport}\n", f"import {backport} as {stdlib}\n",
                        f"{stdlib} = None\n", f"if {stdlib} is None:\n",
                        f"if {stdlib} is not None:\n", f"if _{stdlib} is None:\n",
                        f"from {backport} import loads\n"):
            assert _FALLBACK_SPELLINGS.search(planted), planted
        assert not _FALLBACK_SPELLINGS.search("parser = _hook_utils._toml_parser()\n")

    def test_no_tools_cc_module_imports_the_toml_parser_at_its_top(self):
        """Every hook and tool imports on an interpreter below the floor, so the
        deny hooks and the banner can say the floor: the parser is imported
        inside the reading function, never when the module loads."""
        modules = [path for path in _python_sources()
                   if path.relative_to(REPO_ROOT).as_posix().startswith("tools/cc/")]
        assert len(modules) > 40, f"the walk read too little to mean anything: {len(modules)} files"
        parser = "".join(["t", "o", "m", "l", "l", "i", "b"])  # by character (the row above says why)
        assert parser == _STDLIB
        hits = [f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
                for path in modules
                for line in _module_top_imports(path.read_text(encoding="utf-8"), parser)]
        assert not hits, (
            f"a tools/cc module imports {parser} when it loads, so it cannot import "
            f"below the floor and its hook cannot say the floor: move the import "
            f"inside the reading function:\n  " + "\n  ".join(hits)
        )
        # Earn the red on every run: the top, a top-level try, and a class
        # body are caught; a function body is not.
        assert _module_top_imports(f"import {parser}\n", parser) == [1]
        assert _module_top_imports(f"try:\n    import {parser}\nexcept ImportError:\n    pass\n", parser) == [2]
        assert _module_top_imports(f"class C:\n    from {parser} import loads\n", parser) == [2]
        assert _module_top_imports(f"def read():\n    import {parser}\n", parser) == []
