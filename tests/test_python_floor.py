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

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _hook_utils():
    """Import the hook-side twin the way a hook does — flat, on sys.path."""
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    import _hook_utils  # type: ignore[import-not-found]
    return _hook_utils


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
        stub = tmp_path / name
        stub.write_text(f"#!/bin/sh\necho '{says}'\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        return stub

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
        assert "python3 -m espalier" not in remedy[0], (
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

        stub = tmp_path / "python"
        stub.write_text(
            "#!/bin/sh\necho 'Activating environment...'\necho 'Python 3.9.6'\n",
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
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
        stub = tmp_path / name
        stub.write_text(f"#!/bin/sh\necho '{says}'\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        return str(stub)

    @pytest.mark.skipif(sys.platform == "win32", reason="sh stub is POSIX")
    def test_below_floor_gets_the_below_floor_words(self, tmp_path):
        warn = self._drive(tmp_path, self._stub(tmp_path, "py39", "Python 3.9.6"))
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
        warn = self._drive(tmp_path, self._stub(tmp_path, "notpy", "not a python"))
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
        stub = stubs / "python"
        stub.write_text(f"#!/bin/sh\necho '{says}'\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
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
