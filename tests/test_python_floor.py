"""Tests for the >=3.10 interpreter floor — `espalier/_python_floor.py` and its
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
from tests._stubs import write_stub

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
    ("Python 3.10.0", True),
    ("Python 3.10", True),
    ("Python 3.14.0rc1", True),
    ("Python 4.0.0", True),
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
                f"{said!r} clears the floor -- the >=3.10 comparison is gone and "
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
    ("Python 3.10.0", False),   # clears the floor: not below it
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
            "the below-floor interpreter that DOES resolve is the right answer "
            "here; guards keep working and only blueprints are lost"
        )
        warning = capsys.readouterr().err
        assert "3.10" in warning, f"the warning must name the floor: {warning!r}"
        assert "blueprint" in warning.lower(), (
            f"the warning must name what actually breaks, not just the "
            f"version: {warning!r}"
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
        assert "3.10" in joined, f"the finding must name the floor: {joined!r}"
        assert "IS Python 3" in joined, (
            f"the finding must not claim it is not a Python 3 -- it is, and the "
            f"remedy differs: {joined!r}"
        )

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
            f"a 3.10+ banner that cannot start is not a below-floor Python: {warning}"
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
        assert "python3 -m espalier" not in again[0], (
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
        real = cli.run_bounded
        asked: list[list[str]] = []

        def run_bounded(argv, *args, **kwargs):
            if any("ESPALIER_PROBE" in str(a) for a in argv):
                asked.append(list(argv))
            return real(argv, *args, **kwargs)

        monkeypatch.setattr(cli, "run_bounded", run_bounded)
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

        from espalier import _spawn, cli, doctor

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

        for module in (_spawn, cli, doctor):
            monkeypatch.setattr(module, "run_bounded", run_bounded)
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
        assert any("less loaded" in s for s in result["next_steps"]), result["next_steps"]

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


    def test_the_running_interpreter_answers_its_own_banner(self, tmp_path, monkeypatch, capsys, mute):
        """Reviewed (both): a ``python3`` that is the interpreter running
        espalier (pip --user, pipx, Homebrew) had its banner spawned and, on a
        loaded host, read as missing, so doctor called the running 3.x "older
        than 3.10". Its own file is answered from ``sys.version_info``."""
        import argparse

        from espalier import cli, doctor

        bin_dir = self._host(tmp_path, monkeypatch, mute, working=(), stubbed=("python",))
        link = bin_dir / ("python3" + Path(sys.executable).suffix)
        try:
            os.symlink(sys.executable, link)
        except OSError as exc:  # no symlinks here (Windows without the privilege)
            pytest.skip(f"no symlink here: {exc}")
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

    def test_no_prescriber_says_install_over_a_mute_python3(self, tmp_path, monkeypatch, capsys, mute):
        """Reviewed (both): the tree main's fallback left -- ``python`` wired,
        a Store stub -- on the same loaded host. doctor's next step, init's
        remedy and the rewire's report each told the operator to install or
        put a Python on PATH, over a ``python3`` that only never answered."""
        import argparse

        from espalier import cli, doctor

        self._host(tmp_path, monkeypatch, mute, working=("python3",), stubbed=("python",),
                   modes={"python3": "timeout"})
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
        ("patient39", False, "older than"),
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

    def test_a_mute_banner_ranks_below_a_below_floor_answer(self, tmp_path, monkeypatch, mute):
        """Pins the settled order (the dispatcher's): mute is the last choice."""
        from espalier import cli

        self._host(tmp_path, monkeypatch, mute, working=("python", "python3"),
                   modes={"python": "timeout", "python3": "py39"})
        monkeypatch.setattr(cli, "_INTERPRETER_WARNING_EMITTED", True, raising=False)
        assert cli._detect_python_command() == "python3"

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

        found = set()
        for path in sorted((REPO_ROOT / "espalier").glob("*.py")):
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
        assert "IS a Python 3" in warn and "3.10" in warn, warn
        assert "does not resolve to a working Python 3" not in warn, (
            f"a working 3.9 was described as not being a Python 3: {warn}"
        )
        assert "No active blueprint" in warn, (
            f"the warning must name the symptom the operator actually sees: {warn}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_non_python_keeps_the_fail_open_words(self, tmp_path):
        warn = self._drive(tmp_path, self._stub(tmp_path, "python-notpy", "not a python"))
        assert "does not resolve to a working Python 3" in warn, warn
        assert "fails OPEN" in warn or "fail OPEN" in warn, warn

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_a_conforming_interpreter_is_silent(self, tmp_path):
        """The control. Without it, both tests above pass on a hook that warns
        unconditionally."""
        import shutil as _shutil
        warn = self._drive(tmp_path, _shutil.which("python3") or sys.executable)
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
