"""Contract for ``scripts/check_ledger_probes.py`` -- the three-way verdict.

The runner re-derives every ``task-packs/FORWARD_LEDGER.md`` row's claim and
reports a row whose probe stopped printing its ``open_value`` as a STRIKE
CANDIDATE. Its whole safety argument is that the verdict is **three-way**, and
the reason is asymmetric harm: a wrong STRIKE tells a human to delete live work
(from a file `git checkout` could not restore until the ledger was tracked on
2026-09-21), while a wrong STILL_OPEN merely costs a re-check.

Every branch pinned here is one that a live cut got WRONG, so none of these is
hypothetical:

* A probe whose ``subject`` file is missing once graded STRIKE -- reading "the
  probe stopped saying True" as "the defect is fixed" when the truth was "the
  probe lost its subject".
* ``shlex.split`` raises ``ValueError`` on unbalanced quotes, which escaped
  ``run_probe`` (whose docstring promised "Never raises") and aborted the whole
  batch, so one malformed row silently cost every other probe its verdict.
* A corrupt probes file read as an honest null and printed a clean zero-strike
  report over a file nobody had checked.

The suite that motivated the runner found 41 of 222 ledger rows already dead --
this file exists so the instrument that replaced that census cannot fail silently
in the direction that destroys work.
"""
# pytest-marker: integration -- seven cases in
# TestTheContaminationPopulationIsActuallyDerived drive real `git init`/`git add`
# against tmp_path repos, so the `unit` bucket's "no subprocess" clause is false
# for this module and it is classified `integration`, the remedy that clause
# names. The rest are still pure unit tests over run_probe/main. Reclassified
# 2026-09-02 when the derivation tests landed: mocking git hid BOTH bugs the
# derivation actually shipped with, so driving it is the point, not an excess.
# slow-exempt: 47 cases measured 0.87s -- the git work is `init` + `add` on
# throwaway trees of four files, so this stays in the `not slow` slice and the
# fast smoke slice loses no coverage.
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is dev tooling and is intentionally NOT shipped in the sdist (per
# MANIFEST.in). When tests run from a sdist install, scripts/ is absent; skip
# the whole file with a clear reason in that environment.
if not (REPO_ROOT / "scripts" / "check_ledger_probes.py").is_file():
    pytest.skip(
        "scripts/check_ledger_probes.py is dev tooling not shipped in sdist; "
        "this test file applies only to source-checkout runs.",
        allow_module_level=True,
    )

# full-tree-exempt: the two live-tree tests in TestTheLiveProbeFile read
# `task-packs/LEDGER_PROBES.json`, which IS pruned from a release export
# (.gitattributes `/task-packs/`), but each carries its own
# `skipif(not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file())` so it
# SKIPS rather than FileNotFoundErrors on an extracted archive. Every other test
# in this file drives `run_probe`/`main` against tmp_path or a subject that ships
# (README.md), so none of them touches dev-tree-only content at all.

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_ledger_probes  # noqa: E402  (module object: TestStaleClaimAxis
                            #  monkeypatches its module-level `_LEDGER`)
from check_ledger_probes import (  # noqa: E402
    NO_ORACLE,
    STILL_OPEN,
    STRIKE_CANDIDATE,
    UNRESOLVED,
    run_probe,
)

# A subject that certainly exists in any source checkout, so the subject gate is
# never the thing under test except where it IS the thing under test.
_REAL_SUBJECT = "README.md"


def _probe(cmd: str, open_value: str, subject: str = _REAL_SUBJECT) -> dict:
    return {"id": "T", "subject": subject, "cmd": cmd, "open_value": open_value}


class TestTheVerdictIsThreeWay:
    """The distinction that makes a wrong strike impossible to reach by accident."""

    def test_matching_output_is_still_open(self):
        verdict, _ = run_probe(_probe('python3 -c "print(1)"', "1"))
        assert verdict == STILL_OPEN

    def test_differing_output_is_a_strike_candidate(self):
        verdict, detail = run_probe(_probe('python3 -c "print(2)"', "1"))
        assert verdict == STRIKE_CANDIDATE
        assert "2" in detail and "1" in detail, (
            "a strike candidate must report BOTH the observed and the expected "
            f"value so a human can adjudicate without re-running it: {detail!r}"
        )

    def test_missing_subject_is_unresolved_never_a_strike(self):
        """THE load-bearing case. A probe that lost its subject answers a question
        about a file that is not there -- which is not evidence the defect was fixed."""
        verdict, detail = run_probe(
            _probe('python3 -c "print(999)"', "1", subject="no/such/file/anywhere.py")
        )
        assert verdict == UNRESOLVED, (
            "a missing subject graded as something other than UNRESOLVED -- this is "
            "the branch that once told a human to strike a live row"
        )
        assert verdict != STRIKE_CANDIDATE
        assert "subject missing" in detail

    def test_absent_cmd_is_no_oracle_not_a_strike(self):
        verdict, _ = run_probe(
            {"id": "T", "subject": _REAL_SUBJECT, "cmd": None,
             "why_not": "external state", "open_value": "True"}
        )
        assert verdict == NO_ORACLE


class TestAMalformedProbeCannotCostOtherProbesTheirVerdict:
    """One bad row must not abort the batch -- the isolation the design promises."""

    def test_unbalanced_quotes_are_unresolved_not_an_exception(self):
        bad = _probe('python3 -c "print(1)\' ', "1")
        verdict, detail = run_probe(bad)  # must not raise
        assert verdict == UNRESOLVED
        assert "not parseable" in detail

    def test_a_good_probe_still_grades_after_a_malformed_one(self):
        run_probe(_probe('python3 -c "print(1)\' ', "1"))
        verdict, _ = run_probe(_probe('python3 -c "print(1)"', "1"))
        assert verdict == STILL_OPEN, (
            "a malformed probe leaked state into the next one -- the batch is "
            "supposed to be per-probe isolated"
        )

    def test_a_nonexistent_binary_is_unresolved(self):
        verdict, _ = run_probe(_probe("definitely-not-a-real-binary-xyz", "1"))
        assert verdict == UNRESOLVED


class TestAProbeDeclaresThePathsItsCommandReads:
    """The subject gate's twin (`DEF-858`). The subject is the file the FIX
    edits; the COMMAND may read others -- `DEF-411a`/`DEF-412h` shell out to
    `scripts/check_pack_landing.py` (tracked, always present) whose population
    is `task-packs/Done/` (local-only, absent on the public checkout). Measured
    2026-09-22 in a `--shared` clone without `Done/`: the tool printed its
    all-clear over nothing, the probe printed `False`, and both rows graded
    STRIKE_CANDIDATE -- `DEF-765` too, over an untracked doc. An `inputs` list
    names those paths, and a missing member is UNRESOLVED like a missing subject.
    """

    def test_a_missing_input_is_unresolved_never_a_strike(self):
        probe = _probe('python3 -c "print(999)"', "1")   # on its own this grades STRIKE
        probe["inputs"] = ["README.md", "no/such/dir/anywhere"]
        verdict, detail = run_probe(probe)
        assert verdict == UNRESOLVED, (
            "a probe whose declared input is absent graded as something other than "
            f"UNRESOLVED ({verdict}: {detail}) -- this is the branch that struck two "
            "live rows on the public checkout"
        )
        assert "input missing" in detail and "no/such/dir/anywhere" in detail
        assert "README.md" not in detail, "the present member must not be reported as missing"

    def test_every_declared_input_present_lets_the_command_answer(self):
        probe = _probe('python3 -c "print(1)"', "1")
        probe["inputs"] = ["README.md", "scripts"]        # a file and a directory
        verdict, detail = run_probe(probe)
        assert verdict == STILL_OPEN, detail

    def test_an_empty_list_declares_nothing_and_gates_nothing(self):
        probe = _probe('python3 -c "print(1)"', "1")
        probe["inputs"] = []
        assert run_probe(probe)[0] == STILL_OPEN

    def test_a_bare_string_fails_on_its_shape_not_by_iterating_characters(self):
        """`for p in "README.md"` walks `R`, `E`, `A`... and `R` does not exist,
        so a runner with no shape check would ALSO say UNRESOLVED -- for the
        wrong reason, green here on the wrong implementation. Pin the detail."""
        probe = _probe('python3 -c "print(1)"', "1")
        probe["inputs"] = "README.md"
        verdict, detail = run_probe(probe)
        assert verdict == UNRESOLVED
        assert "not a list" in detail and "input missing" not in detail

    def test_an_escaping_member_is_refused_by_shape_not_resolved_outside_the_checkout(self):
        """`root / "/etc/hosts"` is `/etc/hosts`: an absolute member pins the row
        to one machine, a `..` member walks out of the tree, `~` never expands.
        Each is UNRESOLVED by shape and the detail names it (both reviewers)."""
        for member in ("/etc/hosts", "../README.md", "~/x", "C:/x"):
            probe = _probe('python3 -c "print(1)"', "1")
            probe["inputs"] = [member]
            verdict, detail = run_probe(probe)
            assert verdict == UNRESOLVED and "repo-relative" in detail and member in detail, member

    def test_a_backslash_member_is_read_as_the_forward_slash_path(self):
        probe = _probe('python3 -c "print(1)"', "1")
        probe["inputs"] = ["scripts\\check_ledger_probes.py"]
        verdict, detail = run_probe(probe)
        assert verdict == STILL_OPEN, detail

    def test_a_declared_directory_that_holds_nothing_is_as_absent_as_a_missing_one(
        self, tmp_path, monkeypatch,
    ):
        """The pack-landing checklist's `mkdir -p task-packs/Done && mv ...`
        leaves the folder behind when zsh aborts the `mv` on an unmatched glob;
        present and empty, the tool the probe runs says SCANNED NOTHING over it,
        and an existence-only gate let the probe answer -- every earlier row in
        this class green (failure-mode pass, 2026-09-22)."""
        monkeypatch.setattr(check_ledger_probes, "_ROOT", tmp_path)
        (tmp_path / "subject.py").write_text("", encoding="utf-8")
        (tmp_path / "records" / "Done").mkdir(parents=True)
        probe = {"id": "T", "subject": "subject.py", "open_value": "1",
                 "inputs": ["records/Done"], "cmd": 'python3 -c "print(1)"'}
        verdict, detail = run_probe(probe)
        assert verdict == UNRESOLVED and "input empty" in detail and "records/Done" in detail
        (tmp_path / "records" / "Done" / "TP-1-x.md").write_text("", encoding="utf-8")
        assert run_probe(probe)[0] == STILL_OPEN

    def test_the_subject_gate_still_answers_first(self):
        probe = _probe('python3 -c "print(1)"', "1", subject="no/such/subject.py")
        probe["inputs"] = ["no/such/dir/either"]
        verdict, detail = run_probe(probe)
        assert verdict == UNRESOLVED and "subject missing" in detail

    def test_the_two_tree_property_on_a_scratch_root(self, tmp_path, monkeypatch):
        """The SAME probe must read UNRESOLVED on a tree without its input and
        a real verdict on one with it -- driven on a tmp root, the way the seed
        clone was driven by hand (principle 12: a gate is proven on a tree it
        was not written on)."""
        monkeypatch.setattr(check_ledger_probes, "_ROOT", tmp_path)
        (tmp_path / "subject.py").write_text("", encoding="utf-8")
        probe = {
            "id": "T", "subject": "subject.py", "open_value": "1",
            "inputs": ["records/Done"],
            "cmd": 'python3 -c "import os;print(int(os.path.isdir(\'records/Done\')))"',
        }
        verdict, detail = run_probe(probe)
        assert verdict == UNRESOLVED and "records/Done" in detail
        (tmp_path / "records" / "Done").mkdir(parents=True)
        (tmp_path / "records" / "Done" / "TP-1-x.md").write_text("", encoding="utf-8")
        verdict, detail = run_probe(probe)
        assert verdict == STILL_OPEN, detail


class TestTheRunnerFailsClosedOnACorruptProbeFile:
    """A probes file that will not parse is not an honest null."""

    def test_unparseable_probe_file_exits_nonzero_and_says_so(self, tmp_path, monkeypatch, capsys):
        import check_ledger_probes as mod

        broken = tmp_path / "LEDGER_PROBES.json"
        broken.write_text('{"probes": [ NOT JSON', encoding="utf-8")
        monkeypatch.setattr(mod, "_PROBES", broken)

        rc = mod.main([])
        out = capsys.readouterr().out
        assert rc == 1, (
            "a corrupt probes file returned success -- it would print a clean "
            "zero-strike report over a file nobody checked"
        )
        assert "refusing to report" in out

    def test_a_latin1_probe_file_is_refused_not_a_traceback(self, tmp_path, monkeypatch, capsys):
        """Ledger DEF-829: ``UnicodeDecodeError`` is a ``ValueError`` the
        ``(JSONDecodeError, OSError, AttributeError)`` tuple let past. The
        file is a structured answer: the strict read stays and the handler
        names ValueError, so a code-page re-save takes the refuse-loudly limb."""
        import check_ledger_probes as mod

        bad = tmp_path / "LEDGER_PROBES.json"
        bad.write_bytes(b'{"_count": 1, "probes": [{"id": "DEF-1", "note": "caf\xe9"}]}')
        monkeypatch.setattr(mod, "_PROBES", bad)

        assert mod.main([]) == 1
        assert "refusing to report" in capsys.readouterr().out

    def test_an_empty_probe_list_is_refused_not_reported_as_zero_strikes(
        self, tmp_path, monkeypatch, capsys
    ):
        """The quieter half of the same false green. A file that PARSES but
        yields no probes reported "0 probes re-derived" and exited 0 -- a clean
        green over a file whose own `_count` said 181. Zero probes is
        indistinguishable from zero strikes, so it must refuse."""
        import check_ledger_probes as mod

        # ⚠ NO `_count` KEY. With one present the count-mismatch limb fires FIRST
        # and both limbs print "refusing to report" -- so asserting that shared
        # string witnessed nothing. Proven: deleting the `if not probes:` block
        # left this file 13/13 green. The fixture must reach ONLY this limb, and
        # the assertion must name what only this limb says.
        empty = tmp_path / "LEDGER_PROBES.json"
        empty.write_text('{"probes": []}', encoding="utf-8")
        monkeypatch.setattr(mod, "_PROBES", empty)

        rc = mod.main(["--strikes"])
        assert rc == 1, "an empty probe list reported success"
        assert "yielded no probes" in capsys.readouterr().out

    def test_a_renamed_probes_key_is_refused(self, tmp_path, monkeypatch, capsys):
        """`.get("probes", [])` silently tolerates schema drift; the count
        cross-check is what catches a renamed key."""
        import check_ledger_probes as mod

        drifted = tmp_path / "LEDGER_PROBES.json"
        drifted.write_text('{"_count": 181, "probez": [1, 2, 3]}', encoding="utf-8")
        monkeypatch.setattr(mod, "_PROBES", drifted)

        assert mod.main(["--strikes"]) == 1
        # names the COUNT limb specifically, so this test and the one above
        # cannot both be satisfied by whichever limb happens to run first
        assert "declares _count" in capsys.readouterr().out

    def test_absent_probe_file_is_a_clean_noop_not_a_failure(self, tmp_path, monkeypatch, capsys):
        """Self-host only: an adopter tree has no task-packs/, and that is not an error."""
        import check_ledger_probes as mod

        monkeypatch.setattr(mod, "_PROBES", tmp_path / "absent.json")
        rc = mod.main([])
        assert rc == 0
        assert "nothing to do" in capsys.readouterr().out


class TestTheLiveProbeFile:
    """Contracts on the shipped data, not just the runner."""

    _LIVE = REPO_ROOT / "task-packs" / "LEDGER_PROBES.json"

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host tooling: the probes file is absent on an adopter tree",
    )
    def test_every_probe_declares_a_subject(self):
        """Without a subject the three-way verdict collapses to two, and the
        branch that collapses is the one that destroys work."""
        probes = json.loads(self._LIVE.read_text(encoding="utf-8"))["probes"]
        missing = [p["id"] for p in probes if p.get("cmd") and not p.get("subject")]
        assert not missing, (
            f"{len(missing)} probe(s) carry a command but no subject, so a moved "
            f"file would grade STRIKE instead of UNRESOLVED: {missing[:10]}"
        )

    #: The two report headings and the all-clear a probe greps out of
    #: `scripts/check_pack_landing.py`'s stdout. Keyed on what binds the probe
    #: to `task-packs/Done/`, not on how it runs the script: `subprocess`,
    #: `os.system`, `runpy` and `python3 -m` all read the same lines
    #: (failure-mode pass, 2026-09-22).
    _LANDING_LINT_LINES = ("ROADMAP packs in Done/", "incomplete Landing stanza",
                           "carry a terminal State")

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host tooling: the probes file is absent on an adopter tree",
    )
    def test_a_probe_that_reads_the_landing_lints_report_declares_done_and_reads_its_marker(self):
        """`scripts/check_pack_landing.py` is tracked and always present; the
        folder it reads is not. A probe that reads its REPORT answers about
        `task-packs/Done/` and must (1) declare it, or the public checkout's
        first strike run grades it fixed, and (2) key on the lint's SCANNED
        NOTHING marker, or a `Done/` that exists but holds no pack -- reachable
        by the landing checklist's own `mkdir -p` -- lets it answer over nothing
        (`DEF-858`, both measured 2026-09-22). Keyed on the probes file alone, so
        the verdict is the same on the seed tree."""
        probes = json.loads(self._LIVE.read_text(encoding="utf-8"))["probes"]
        readers = [
            p for p in probes
            if p.get("cmd") and any(line in p["cmd"] for line in self._LANDING_LINT_LINES)
        ]
        assert readers, (
            "no live probe reads the landing lint's report: the chore drained and its "
            "rows were struck -- DELETE this ratchet rather than leave a guard that can "
            "no longer fail for the right reason"
        )

        def declares_done(p: dict) -> bool:
            inputs = p.get("inputs")
            return isinstance(inputs, list) and "task-packs/Done" in [
                x.replace("\\", "/").rstrip("/") for x in inputs if isinstance(x, str)
            ]

        undeclared = [p["id"] for p in readers if not declares_done(p)]
        assert not undeclared, (
            f"probe(s) read check_pack_landing.py's report without declaring task-packs/Done "
            f"in `inputs`, so a checkout without it grades them STRIKE_CANDIDATE: {undeclared}"
        )
        blind = [p["id"] for p in readers if "SCANNED NOTHING" not in p["cmd"]]
        assert not blind, (
            f"probe(s) grep the lint's report without keying on its SCANNED NOTHING "
            f"marker, so a Done/ that exists but holds no pack lets them answer: {blind}"
        )

    #: Path literals a command NAMES that are not what it READS: an absence
    #: check, a classifier argument, pattern text. Declaring one in `inputs`
    #: would UNRESOLVE the probe on every tree that lacks it -- the opposite
    #: error. Each carries its reason; a new entry needs one. (2026-09-22 census
    #: in a --shared clone: six live probes name a path the clone lacks; three
    #: read it and now declare it, these three only name it.)
    _NAMED_NOT_READ = {
        "DEF-664": {"tools/cc/hooks/.espalier-state"},              # `test -d` asserts its ABSENCE
        "DEF-741": {"WALK2_FINDINGS.md", "WINDOWS_FUSE_NOTES.md"},  # classifier arguments, never opened
        "DEF-884": {".espalier/integrity.json"},                    # text inside a bash pattern under test
    }
    _PATH_LITERAL = re.compile(
        r"(?<![\w/.-])((?:[A-Za-z_.][\w.-]*/)+[\w.-]*"
        r"|[A-Za-z_][\w-]*\.(?:py|md|json|toml|yml|yaml|txt|sh|cfg|ini))(?![\w/-])"
    )

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host tooling: the probes file is absent on an adopter tree",
    )
    def test_every_untracked_path_a_command_names_is_declared_or_baselined(self):
        """The DIRECT shape of `DEF-858`, derived rather than listed: a path
        literal in a command that exists on THIS tree and is not tracked is
        exactly what a public checkout lacks, so the probe declares it in
        `inputs` -- or `_NAMED_NOT_READ` says why naming it is not reading it.
        The probe's own subject is the subject gate's business. Vacuous on the
        seed tree by construction (its untracked-and-present set is empty); the
        seed test is that tree's proof. The transitive shape -- a command that
        runs a tool which reads the folder -- shows no literal and is pinned by
        the ratchet above."""
        from tests._git_oracle import require_tracked_paths  # never a silently empty set

        probes = json.loads(self._LIVE.read_text(encoding="utf-8"))["probes"]
        tracked = set(require_tracked_paths(REPO_ROOT, minimum=200, what="tracked files"))

        def is_tracked(rel: str) -> bool:
            return rel in tracked or any(t.startswith(rel + "/") for t in tracked)

        offenders = []
        for p in probes:
            cmd = p.get("cmd") or ""
            if not cmd:
                continue
            subject = (p.get("subject") or "").rstrip("/")
            declared = {
                x.replace("\\", "/").rstrip("/") for x in (p.get("inputs") or [])
                if isinstance(x, str)
            }
            baseline = self._NAMED_NOT_READ.get(p["id"], set())
            for tok in {m.group(1).rstrip("/.") for m in self._PATH_LITERAL.finditer(cmd)}:
                if not tok or tok == subject or tok in declared or tok in baseline:
                    continue
                if (REPO_ROOT / tok).exists() and not is_tracked(tok):
                    offenders.append((p["id"], tok))
        assert not offenders, (
            "probe(s) name a path that exists here and is untracked -- a public checkout "
            "lacks it -- without declaring it in `inputs` (ledger_row file|repin --inputs) "
            f"or baselining it in _NAMED_NOT_READ with the reason: {sorted(offenders)}"
        )
        dead = sorted(rid for rid in self._NAMED_NOT_READ if rid not in {p["id"] for p in probes})
        assert not dead, f"_NAMED_NOT_READ names probe(s) that no longer exist: {dead}"

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "Done").is_dir(),
        reason="self-host only: the declared inputs are local-only paths that travel "
               "with task-packs/Done/, absent in a fresh clone",
    )
    def test_every_declared_input_resolves_on_the_development_tree(self):
        """A declaration that resolves nowhere is a probe that never answers, and
        `--strikes` never moves on UNRESOLVED, so a typo would retire a row's
        measurement silently (failure-mode pass). On the tree that carries the
        local-only folders every member resolves and holds something."""
        probes = json.loads(self._LIVE.read_text(encoding="utf-8"))["probes"]
        dangling = [
            (p["id"], x) for p in probes for x in (p.get("inputs") or [])
            if isinstance(x, str) and (
                not (REPO_ROOT / x.replace("\\", "/")).exists()
                or ((REPO_ROOT / x).is_dir() and not any((REPO_ROOT / x).iterdir()))
            )
        ]
        assert not dangling, f"declared input(s) that do not resolve on this tree: {dangling}"

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host tooling: the probes file is absent on an adopter tree",
    )
    def test_every_declared_inputs_list_has_the_shape_the_gate_reads(self):
        """A bare string here is UNRESOLVED by shape on every tree -- a probe
        that can never answer. The verb writes a list; pin that nothing else did."""
        probes = json.loads(self._LIVE.read_text(encoding="utf-8"))["probes"]
        malformed = [
            p["id"] for p in probes
            if "inputs" in p and not (
                isinstance(p["inputs"], list) and p["inputs"]
                and all(isinstance(x, str) and x for x in p["inputs"])
            )
        ]
        assert not malformed, f"probe(s) carry an `inputs` that is not a non-empty list of paths: {malformed}"

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host tooling: the probes file is absent on an adopter tree",
    )
    def test_no_probe_pins_a_line_number(self):
        """A line-anchored probe false-STRIKES on any edit above its subject.
        Measured 2026-08-20: two did, and one of them belonged to the row whose
        own fix is 'cite by section heading rather than by line'."""
        probes = json.loads(self._LIVE.read_text(encoding="utf-8"))["probes"]
        import re

        offenders = [
            p["id"] for p in probes
            if p.get("open_value") and re.fullmatch(r"\[\d+\]|\d{3,}", str(p["open_value"]))
        ]
        assert not offenders, (
            "probe(s) pin what looks like a line number as their open_value; any "
            f"insert above the citation false-STRIKES the row: {offenders}"
        )


class TestATreeWalkingProbeRefusesAContaminatedTree:
    """A probe that enumerates the tree must not answer over a generated copy.

    MEASURED 2026-09-02: `DEF-636`'s probe counts a literal across
    ``rglob('*.py')`` and printed 5 at 17:40, 3 at 18:50, with no change to the
    code it measures. The difference was ``build/lib/espalier/`` -- a setuptools
    staging copy one test run created and a later one cleaned. At 5 it reported
    STRIKE_CANDIDATE on a row whose defect was untouched, and the ledger was
    gitignored at the time, so acting on that verdict destroyed live work that
    `git checkout` could not bring back.
    """

    def _probe(self):
        return {
            "id": "T-1",
            "subject": "README.md",
            "cmd": "python3 -c \"import pathlib;print(len(list(pathlib.Path('.').rglob('*.py'))))\"",
            "open_value": "0",
        }

    def test_a_planted_duplicate_makes_the_verdict_unresolved(self, monkeypatch, tmp_path):
        """The whole point: no verdict beats a wrong one."""
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", {"build": {".py"}})
        verdict, detail = check_ledger_probes.run_probe(self._probe())
        assert verdict == UNRESOLVED, f"got {verdict}: {detail}"
        assert "build/" in detail

    def test_a_clean_tree_still_gets_a_real_verdict(self, monkeypatch):
        """The guard must not cost every walking probe its answer."""
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", {})
        verdict, _ = check_ledger_probes.run_probe(self._probe())
        assert verdict != UNRESOLVED

    def test_a_probe_that_excludes_the_tree_itself_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", {"build": {".py"}})
        probe = self._probe()
        # walks the tree AND filters the contaminating dir itself -> not gated.
        # Scoped to scripts/ so the fixture stays fast; the gate keys on the
        # presence of `rglob` and of the tree's name, not on the walk's breadth.
        probe["cmd"] = (
            "python3 -c \"import pathlib;"
            "print(len([f for f in pathlib.Path('scripts').rglob('*.py') "
            "if 'build' not in str(f)]))\""
        )
        verdict, detail = check_ledger_probes.run_probe(probe)
        assert verdict != UNRESOLVED, detail

    def test_a_non_walking_probe_is_never_gated(self, monkeypatch):
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", {"build": {".py"}})
        verdict, _ = check_ledger_probes.run_probe(
            {"id": "T-2", "subject": "README.md",
             "cmd": "python3 -c \"print(0)\"", "open_value": "0"}
        )
        assert verdict != UNRESOLVED

    def test_a_duplicate_of_a_type_the_probe_ignores_does_not_gate_it(self, monkeypatch):
        """`build/` is recreated by the suite itself, so precision is not optional.

        A presence-only gate put 21 probes into UNRESOLVED after every full run
        (`tests/test_wheel_payload.py` builds an sdist), and `build/` oscillates
        as tests create and clean it -- intermittent gating on the common path.
        A probe counting `*.md` is unaffected by a staging tree holding `.py`.
        """
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", {"build": {".py"}})
        verdict, detail = check_ledger_probes.run_probe(
            {"id": "T-3", "subject": "README.md",
             "cmd": "python3 -c \"import pathlib;print(len(list(pathlib.Path('docs').rglob('*.md'))))\"",
             "open_value": "0"}
        )
        assert verdict != UNRESOLVED, detail

    def test_an_unfiltered_walk_is_still_gated(self, monkeypatch):
        """No `*.ext` in the command means unknown breadth -- stay conservative."""
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", {"build": {".py"}})
        verdict, _ = check_ledger_probes.run_probe(
            {"id": "T-4", "subject": "README.md",
             "cmd": "python3 -c \"import pathlib;print(len(list(pathlib.Path('.').rglob('*'))))\"",
             "open_value": "0"}
        )
        assert verdict == UNRESOLVED

    def test_a_word_containing_the_tree_name_does_not_waive_the_gate(self):
        """`rebuild` is not an exclusion of `build/`, and neither is a real path.

        `_excludes` was a bare `name in cmd`, so any probe whose command merely
        contained the letters "build" -- `build_release_archive.py` is a real
        path in this repo -- read as "already filters the contaminating tree"
        and was silently waived. A fail-open one function below the check
        written to stop fail-opens.
        """
        assert not check_ledger_probes._excludes("x rebuild y", ["build"])
        assert not check_ledger_probes._excludes("scripts/build_release_archive.py", ["build"])
        assert check_ledger_probes._excludes("if 'build' not in str(f)", ["build"])
        assert check_ledger_probes._excludes("skip build/ entirely", ["build"])

    def test_a_recursive_glob_counts_as_walking_the_tree(self):
        """`Path(x).glob('**/*.py')` reaches `build/` exactly as `rglob` does."""
        assert check_ledger_probes._walks_the_tree("Path('.').glob('**/*.py')")
        assert check_ledger_probes._walks_the_tree("p.rglob('*.py')")
        assert not check_ledger_probes._walks_the_tree("open('README.md').read()")


class TestTheContaminationPopulationIsActuallyDerived:
    """The DERIVATION half, on a real tree with a real duplicate planted in it.

    ⚠ THIS CLASS EXISTS BECAUSE THE FIRST CUT DID NOT HAVE IT, and an adversarial
    pass caught that. Every sibling test in
    `TestATreeWalkingProbeRefusesAContaminatedTree` monkeypatches
    `_CONTAMINATION` to a literal, so all six exercise how the gate CONSUMES the
    population and none exercise how it is COMPUTED. Measured 2026-09-02:
    replacing `_contaminating_trees`'s body with `return {}` -- the gate can then
    never fire, for any tree, ever -- left the module 28/28 green. A gate whose
    detector can be deleted without a red is the born-weak shape this repo
    records more than any other, and it had been reproduced inside the fix for a
    probe that fails open.

    These tests build a throwaway git repo instead of mocking git, because the
    two bugs the derivation actually shipped with (a 3-segment key that never
    matched a real staging layout, and a root-level basename that matched
    `.pytest_cache/README.md`) were both invisible to a mock and obvious against
    a real `git ls-files`.
    """

    @staticmethod
    def _repo(tmp_path: Path, *, ignore: str = "build/\n") -> Path:
        """A minimal tracked tree: one package file, one ignored dir pattern."""
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "demo.gif").write_bytes(b"GIF89a")
        (tmp_path / ".gitignore").write_text(ignore, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True,
                       capture_output=True)
        return tmp_path

    @staticmethod
    def _plant(root: Path, rel: str, *, body: bytes = b"x = 1\n") -> None:
        """Write a byte-copy of a tracked file at a generated location."""
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)

    def test_a_planted_duplicate_is_found(self, monkeypatch, tmp_path):
        """The whole detector, end to end. `return {}` in the derivation reds here."""
        root = self._repo(tmp_path)
        # setuptools' real layout: the copy sits one level DEEPER than tracked.
        self._plant(root, "build/lib/pkg/mod.py")
        monkeypatch.setattr(check_ledger_probes, "_ROOT", root)
        assert check_ledger_probes._contaminating_trees() == {"build": {".py"}}

    def test_a_clean_ignored_tree_is_not_reported(self, monkeypatch, tmp_path):
        """An ignored dir holding no copy of tracked source is not contamination.

        The hand-written first cut failed exactly here: it named `.venv` and the
        caches on sight, and measured, `.venv`'s 405 `.py` files duplicate ZERO
        tracked paths. That cut moved 22 probes to UNRESOLVED on a healthy tree.
        """
        root = self._repo(tmp_path)
        self._plant(root, "build/lib/unrelated/other.py", body=b"y = 2\n")
        monkeypatch.setattr(check_ledger_probes, "_ROOT", root)
        assert check_ledger_probes._contaminating_trees() == {}

    def test_a_duplicate_of_any_extension_is_found(self, monkeypatch, tmp_path):
        """No extension whitelist. `.gif` and `.js` are live walked types.

        A six-extension index (`.py .md .json .toml .yml .yaml`) shipped first
        and made three probes permanently ungateable -- `DEF-539` and `LG-6`
        walk `*.gif`, `DEF-625` walks `*.js`. Package data is precisely what a
        wheel build stages, so those walks are the MOST exposed to a staging
        copy, not the least.
        """
        root = self._repo(tmp_path)
        self._plant(root, "build/lib/assets/demo.gif", body=b"GIF89a")
        monkeypatch.setattr(check_ledger_probes, "_ROOT", root)
        assert check_ledger_probes._contaminating_trees() == {"build": {".gif"}}

    def test_a_matching_basename_at_the_wrong_path_is_not_a_duplicate(self, monkeypatch, tmp_path):
        """The basename is indexed, but the path is not a copy of the tracked one.

        This pins the `rel.endswith("/" + tracked)` line, which is the whole
        difference between "a file with this name exists somewhere" and "this is
        a copy of that file". Mutating it to `if True:` left the module green:
        the sibling cases plant a basename that is skipped from the index, or one
        that is absent from it, so neither reaches the comparison. `pkg/mod.py`
        is tracked; `build/other/mod.py` shares only the basename.
        """
        root = self._repo(tmp_path)
        self._plant(root, "build/other/mod.py")
        monkeypatch.setattr(check_ledger_probes, "_ROOT", root)
        assert check_ledger_probes._contaminating_trees() == {}

    def test_a_tracked_directory_is_never_its_own_contamination(self, monkeypatch, tmp_path):
        """Only IGNORED dirs are candidates -- the tree proper is the original."""
        root = self._repo(tmp_path)
        monkeypatch.setattr(check_ledger_probes, "_ROOT", root)
        assert "pkg" not in check_ledger_probes._contaminating_trees()

    def test_a_root_level_basename_alone_is_not_a_duplicate(self, monkeypatch, tmp_path):
        """`.pytest_cache/README.md` is not a copy of the repo.

        Measured: keying on the bare basename flagged the pytest cache and cost
        22 probes their verdict on a healthy tree. This pins the `"/" not in rel`
        skip in `_tracked_by_basename`, which the earlier index-shape test only
        asserted about the index and never drove through the derivation.
        """
        root = self._repo(tmp_path)
        (root / "README.md").write_text("# repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True,
                       capture_output=True)
        self._plant(root, "build/README.md", body=b"# repo\n")
        monkeypatch.setattr(check_ledger_probes, "_ROOT", root)
        assert check_ledger_probes._contaminating_trees() == {}

    def test_git_failing_is_not_read_as_a_clean_tree(self, monkeypatch, tmp_path):
        """The fail-open the whole file exists to prevent, in the check itself.

        `git ls-files` outside a repository exits non-zero with empty stdout.
        The first cut returned `{}` for that -- indistinguishable from "clean" --
        so a probe run from a non-repo copy got a real verdict from a detector
        that could no longer detect anything. It must refuse instead.
        """
        monkeypatch.setattr(check_ledger_probes, "_ROOT", tmp_path)   # no .git
        with pytest.raises(check_ledger_probes._GitUnavailable):
            check_ledger_probes._tracked_by_basename()

    def test_an_unconsultable_git_gates_the_probe_rather_than_passing_it(
        self, monkeypatch, tmp_path
    ):
        """End to end: the refusal must reach the VERDICT, not just raise."""
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        monkeypatch.setattr(check_ledger_probes, "_ROOT", tmp_path)
        monkeypatch.setattr(check_ledger_probes, "_CONTAMINATION", None)
        verdict, detail = check_ledger_probes.run_probe(
            {"id": "T-5", "subject": "README.md",
             "cmd": "python3 -c \"import pathlib;print(len(list(pathlib.Path('.').rglob('*.py'))))\"",
             "open_value": "0"}
        )
        assert verdict == UNRESOLVED, detail
        assert "git could not be consulted" in detail

class TestProbeShapesAreRatcheted:
    """A probe must not be satisfiable by the paperwork of its own fix.

    THE TRAP, measured twice in this repo. `DEF-583`'s probe counted files
    containing a model literal -- including the prose explaining why that literal
    was retired, so the fix could never report itself. `DEF-632`'s probe counted
    DEC-25 vocabulary inside `docs/RELEASE_CHECKLIST.md`, the very file its fix
    rewrites, so a single "see DEC-25" line would have closed the row with the
    dangerous push sequence fully intact (calibrated 2026-09-02: the mutation
    reads CLOSED with the defect untouched).

    ⚠ THIS IS A FROZEN SET, NOT A COUNT, and the first cut was a count of 30
    that an adversarial pass falsified two ways.

    *It measured three spellings, not the class.* The detector required
    `findall` / `count(` / `grep`; the dominant idiom in this file is
    `'literal' in open(subject).read()` -- a count thresholded at one,
    mechanically identical -- and it was invisible. Measured: **131** probes read
    text out of their own subject; the shipped detector saw **30** and missed
    **101**. Its docstring's claim that "no NEW one can be authored blind" was
    false for the file's majority idiom.

    *And a ceiling with no floor is not a ratchet.* Re-pointing or striking a
    trapped probe dropped the count and silently bought a slot for the next one.
    A set has no slots: an id is either baselined or it is new.

    Removing an id from the baseline is the point -- it means that probe was
    re-pointed at a structural predicate. Adding one is not. The 131 are
    corrected just-in-time as each row surfaces (a batch correction stales on the
    first execution), and the honest reading of this number is "most of this file
    predates the lesson", not "131 rows are wrong".
    """

    #: Probes reading their own subject's TEXT, measured 2026-09-02 over 222.
    #: Shrink this set freely; every addition needs a reason in the diff.
    #:
    #: DEF-672 is the one deliberate addition since. Its row's DELIVERABLE is
    #: text -- four items dropped from a runbook have to be written back -- so a
    #: text predicate is the honest oracle rather than a shortcut. It is keyed on
    #: the stray-tag sweep's COMMAND (`for-each-ref` + `refs/tags`), not on the
    #: topic, so prose about lightweight tags does not close it; only restoring
    #: the command does. That narrowing is what earns the baseline slot.
    #:
    #: Shrunk 2026-09-20 by the third rebuild's live write (TP-452 1-D): seven
    #: ids left with their rows -- DEF-451, DEF-529, DEF-581, DEF-6, DEF-666 and
    #: LG-8 struck by the rebuild's adjudication, TP-332 re-keyed to DEF-864 by
    #: the structural cut (same probe, same slot, carried below, not added) --
    #: and the five text probes 1-C had filed (DEF-857, 858, 859, 861, 862) were
    #: re-pointed at `ast` predicates by `ledger_row.py repin --probe-cmd`
    #: instead of being baselined, so the set did not grow.
    _TEXT_OVER_OWN_SUBJECT = {
        "CONV-3", "DEC-29", "DEF-20", "DEF-343a",
        "DEF-346c", "DEF-378a",
        "DEF-383b", "DEF-392c", "DEF-392d", "DEF-392e",
        "DEF-393a", "DEF-400b", "DEF-411b", "DEF-413a", "DEF-415b",
        "DEF-415f", "DEF-415h", "DEF-416b",
        "DEF-417h", "DEF-418b", "DEF-419b", "DEF-419c",
        "DEF-419e", "DEF-424b", "DEF-424g", "DEF-437",
        "DEF-438", "DEF-439", "DEF-449",
        "DEF-450", "DEF-476", "DEF-477", "DEF-479", "DEF-483", "DEF-485", "DEF-486", "DEF-487", "DEF-488", "DEF-489",
        "DEF-516", "DEF-519",
        "DEF-523", "DEF-543",
        "DEF-561", "DEF-564",
        "DEF-576", "DEF-579", "DEF-588", "DEF-590", "DEF-593", "DEF-623", "DEF-625", "DEF-628", "DEF-629",
        "DEF-631", "DEF-633", "DEF-644",
        "DEF-645", "DEF-649", "DEF-655", "DEF-660", "DEF-661", "DEF-662", "DEF-663",
        "DEF-864",  # TP-332's slot, re-keyed 2026-09-20 (see above)
        #: DEF-874 (filed 2026-09-21 at the corpus fold): the row's deliverable is the
        #: wording of a release-checklist headline itself, so the probe quotes the exact
        #: bulk-push promise the fix must delete (the only occurrence in the file) and no
        #: enforcer exists to key on instead -- none of the contract test's functions reads
        #: that headline. DEF-672's shape: same subject file, same reason, earns the slot.
        "DEF-874",
        #: DEF-885 (filed 2026-09-21 at the corpus fold): the deliverable is the operator
        #: procedure text of the release checklist's tag-count gate; the contract test pins
        #: push FORMS only, so no enforcer subject can flip for a doc-only fix. The probe keys
        #: on the measurement stage line and the code line after it inside the fenced block,
        #: comments skipped, holding no status guard -- driven: a guard inserted after the
        #: measurement flips it, a comment inside the block or prose outside it does not.
        "DEF-885",
        #: DEF-889 (filed 2026-09-21 at the corpus fold): the deliverable IS a markdown link
        #: in docs/README.md; the probe reads it through the engine's own link extractor
        #: (reflect_protocol._extract_local_links), keyed on a link whose target resolves to
        #: the orphaned doc -- driven: a Reference-table row with that link flips it, a prose
        #: sentence naming the path does not, so no comment or pointer can satisfy it.
        "DEF-889",
        #: DEF-896 and DEF-878 left this set on 2026-09-22: both struck (the link form
        #: deleted and the archive gate gained an absolute-link arm; the staging check
        #: re-based on `git diff --name-only` and pinned by the checklist contract), so
        #: their probes retired and a baseline slot for a retired probe is dead.
        "LG-12", "PR-3", "PR-5", "SUP-2",
    }

    #: Ways a probe reads text rather than asking a structural question. The
    #: first three were the whole shipped detector; the rest are what it missed.
    _TEXT_READS = ("findall", "count(", "grep", ".read()", "read_text",
                   "in open(", "splitlines")

    #: ⚠ A predicate built on `ast.parse` is STRUCTURAL even though it reads the
    #: file, and exempting it is not a loosening. The trap is that the paperwork
    #: of a fix -- a comment, a changelog line, a "see X" pointer -- satisfies the
    #: predicate while the defect stands. Comments do not survive parsing: they
    #: produce no AST node at all, so no amount of prose moves an assertion about
    #: `ast.Call` or `ast.FunctionDef`. Satisfying one of these takes writing the
    #: code it names, which is the fix.
    #:
    #: The exemption is deliberately narrow -- the command must actually call
    #: `ast.parse(`, not merely mention the module -- and
    #: `test_reading_a_file_to_parse_it_is_not_the_trap` pins both directions, so
    #: a probe that parses AND separately counts vocabulary is still caught.
    _STRUCTURAL_READS = ("ast.parse(",)

    @classmethod
    def _is_trap_shaped(cls, probe: dict) -> bool:
        """True when the predicate reads text out of the file its fix edits."""
        cmd = probe.get("cmd") or ""
        subject = (probe.get("subject") or "").strip()
        if not cmd or not subject or subject not in cmd:
            return False
        if any(marker in cmd for marker in cls._STRUCTURAL_READS):
            return False
        return any(marker in cmd for marker in cls._TEXT_READS)

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host only: task-packs/LEDGER_PROBES.json absent",
    )
    def test_no_new_probe_is_satisfiable_by_its_own_fixs_paperwork(self):
        data = json.loads(
            (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8")
        )
        rows = data["probes"]
        rows = list(rows.values()) if isinstance(rows, dict) else rows
        trapped = {r["id"] for r in rows if self._is_trap_shaped(r)}
        new = sorted(trapped - self._TEXT_OVER_OWN_SUBJECT)
        assert not new, (
            f"{len(new)} probe(s) count vocabulary inside their own subject file "
            f"and are not baselined. Such a probe is closed by the paperwork of "
            f"its own fix -- a changelog line, a comment, or a 'see X' pointer "
            f"flips it while the defect stands (docs/FAILURE_MODES.md 5.23). "
            f"Re-point it at the SUBJECT: a structural predicate the fix must "
            f"actually satisfy.\n  {new}"
        )

    def test_the_detector_recognises_every_spelling_it_claims_to(self):
        """Earn the red. The first fixture passed four WRONG classifiers.

        It asserted only that one trap classifies true and one non-trap false, so
        a constant `True`, a constant `False`, and a classifier with the subject
        relation deleted all satisfied it. These drive the distinctions the
        detector actually has to make.
        """
        subj = "docs/RELEASE_CHECKLIST.md"

        def probe(cmd, s=subj):
            return {"subject": s, "cmd": cmd}

        # every text-reading spelling over its own subject -> trapped
        for cmd in (
            f"python3 -c \"import re;print(len(re.findall(r'DEC-25',open('{subj}').read())))\"",
            f"python3 -c \"print('DEC-25' in open('{subj}').read())\"",
            f"python3 -c \"from pathlib import Path;print(Path('{subj}').read_text().count('x'))\"",
            f"grep -c 'DEC-25' {subj}",
            f"python3 -c \"print(len(open('{subj}').read().splitlines()))\"",
        ):
            assert self._is_trap_shaped(probe(cmd)), cmd

        # structural predicate over the SAME subject -> not the trap
        assert not self._is_trap_shaped(probe(
            f"python3 -c \"import pathlib;print(pathlib.Path('{subj}').stat().st_size)\""
        ))
        # reads text, but out of a DIFFERENT file than the fix's subject
        assert not self._is_trap_shaped(probe(
            "python3 -c \"print('DEC-25' in open('README.md').read())\""
        ))
        # no subject at all -> nothing to be circular about
        assert not self._is_trap_shaped({"subject": "", "cmd": "grep -c x README.md"})

    def test_reading_a_file_to_parse_it_is_not_the_trap(self):
        """An `ast.parse` predicate is structural; a text count is not.

        Both commands below open the same subject and read it. The difference is
        what the ANSWER depends on: a comment changes the second and cannot
        change the first, because comments produce no AST node. Written when the
        ratchet flagged `DEF-670`, whose predicate asserts a `git init` Call node
        exists inside a named function -- unsatisfiable by prose.
        """
        subj = "scripts/final_release_matrix.py"
        assert not self._is_trap_shaped({
            "subject": subj,
            "cmd": f"python3 -c \"import ast;s=open('{subj}').read();"
                   f"print(any(isinstance(n,ast.Call) for n in ast.walk(ast.parse(s))))\"",
        })
        # merely naming the module is not the exemption
        assert self._is_trap_shaped({
            "subject": subj,
            "cmd": f"python3 -c \"import ast;print(open('{subj}').read().count('ast'))\"",
        })
        # parsing does not launder a sibling vocabulary count in the same command
        assert self._is_trap_shaped({
            "subject": subj,
            "cmd": f"python3 -c \"import re;print(len(re.findall('x',open('{subj}').read())))\"",
        })

    def test_a_constant_classifier_cannot_satisfy_this_suite(self):
        """The property the old fixture lacked: both verdicts must be reachable."""
        subj = "docs/RELEASE_CHECKLIST.md"
        yes = {"subject": subj, "cmd": f"grep -c 'x' {subj}"}
        no = {"subject": subj, "cmd": f"python3 -c \"print(__import__('os').stat('{subj}').st_size)\""}
        assert self._is_trap_shaped(yes) and not self._is_trap_shaped(no)

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").is_file(),
        reason="self-host only: task-packs/LEDGER_PROBES.json absent",
    )
    def test_the_baseline_has_no_dead_entries(self):
        """A baselined id that no longer exists is bookkeeping rot, not safety."""
        data = json.loads(
            (REPO_ROOT / "task-packs" / "LEDGER_PROBES.json").read_text(encoding="utf-8")
        )
        rows = data["probes"]
        rows = list(rows.values()) if isinstance(rows, dict) else rows
        live = {r["id"] for r in rows}
        dead = sorted(self._TEXT_OVER_OWN_SUBJECT - live)
        assert not dead, (
            f"{len(dead)} baselined probe id(s) are gone from LEDGER_PROBES.json. "
            f"Drop them from _TEXT_OVER_OWN_SUBJECT -- a baseline that outlives "
            f"its population stops being a measurement.\n  {dead}"
        )


class TestStaleClaimAxis:
    """Contract for `stale_claims` — Tier 3, the drift half.

    ⚠ THIS IS NOT A FOURTH VERDICT AND THE DISTINCTION IS THE WHOLE POINT.
    A row can be STILL_OPEN and stale at the same time. `DEF-493` was, for five
    days: its probe drove the original redirect symptom and correctly reported
    STILL_OPEN, while the row's prose had been rewritten on 2026-08-25 to state a
    cause that a connector x punctuation matrix had already refuted. A liveness
    check cannot see a misattribution — nothing mechanical can. What it CAN see
    is that a claim was rewritten and never re-measured, which is the reachable
    half, and that is exactly what this axis reports.

    Synthetic and deterministic, per this file's convention: the live ledger's
    content is this tree's own, so a live-tree test proves nothing anybody else can reproduce.
    """

    _MEMBER = "| `DEF-900` | tools/x.py::f | the original claim | major |"
    _INDEX = "| `DEF-900` | §C5 | tools/x.py::f |"

    @staticmethod
    def _sha(line: str) -> str:
        import hashlib
        return hashlib.sha256(line.rstrip().encode("utf-8")).hexdigest()[:12]

    def _run(self, monkeypatch, tmp_path, ledger_body: str, probe: dict):
        led = tmp_path / "FORWARD_LEDGER.md"
        led.write_text(ledger_body, encoding="utf-8")
        monkeypatch.setattr(check_ledger_probes, "_LEDGER", led)
        return check_ledger_probes.stale_claims([probe])

    def _probe(self, sha: str) -> dict:
        return {"id": "DEF-900", "subject": "README.md", "cmd": "true",
                "open_value": "x", "row_sha": sha}

    def test_unchanged_row_is_not_stale(self, monkeypatch, tmp_path):
        body = f"{self._MEMBER}\n{self._INDEX}\n"
        assert self._run(monkeypatch, tmp_path, body,
                         self._probe(self._sha(self._MEMBER))) == []

    def test_rewritten_prose_is_reported(self, monkeypatch, tmp_path):
        """The DEF-493 shape: the row's claim changed, the probe did not."""
        rewritten = "| `DEF-900` | tools/x.py::f | a DIFFERENT stated cause | major |"
        out = self._run(monkeypatch, tmp_path, f"{rewritten}\n{self._INDEX}\n",
                        self._probe(self._sha(self._MEMBER)))
        assert [r[0] for r in out] == ["DEF-900"]

    def test_a_struck_row_is_not_stale(self, monkeypatch, tmp_path):
        """A retired row has nothing left to re-measure, so demanding a
        re-derivation of it is a false alarm that trains people to ignore this."""
        struck = "| ~~`DEF-900`~~ | tools/x.py::f | closed | major |"
        assert self._run(monkeypatch, tmp_path, f"{struck}\n{self._INDEX}\n",
                         self._probe(self._sha(self._MEMBER))) == []

    def test_appendix_index_row_is_not_mistaken_for_the_member_row(
            self, monkeypatch, tmp_path):
        """⚠ EARNED BY MUTATION, not imagined. The first cut of `_row_line` took
        the first line opening with the backticked id. Every id appears twice —
        member row and Appendix B index row — so striking the member row made the
        search fall through to the INDEX row, whose text differs, and reported
        STALE_CLAIM for a row that had just been retired. The false alarm arrived
        through a door the unstruck-only rule could not see."""
        struck = "| ~~`DEF-900`~~ | tools/x.py::f | closed | major |"
        # index row FIRST, so a naive search finds it before anything else
        assert self._run(monkeypatch, tmp_path, f"{self._INDEX}\n{struck}\n",
                         self._probe(self._sha(self._MEMBER))) == []

    @pytest.mark.parametrize("rid", ["DEF-900", "LG-90"])
    def test_a_two_id_row_is_found_by_either_id(self, monkeypatch, tmp_path, rid):
        """DEF-863's reader half. A row whose id cell carries two ids (eight
        live rows on 2026-09-20) was found by NEITHER id: the lookup demanded a
        lone id before the pipe, so a rewrite of such a row was never reported
        for either probe and a pin stamped on it was inert. Earn-the-red:
        restore the lone-id lookup and the first leg reports nothing."""
        original = "| `DEF-900` `LG-90` | tools/x.py::f | the original claim | major |"
        rewritten = "| `DEF-900` `LG-90` | tools/x.py::f | a DIFFERENT stated cause | major |"
        index = "| `DEF-900` | §C5 | tools/x.py::f |\n| `LG-90` | §C5 | tools/x.py::f |"
        probe = {"id": rid, "subject": "README.md", "cmd": "true", "open_value": "x",
                 "row_sha": self._sha(original)}
        out = self._run(monkeypatch, tmp_path, f"{index}\n{rewritten}\n", probe)
        assert [r[0] for r in out] == [rid]
        assert self._run(monkeypatch, tmp_path, f"{index}\n{original}\n", probe) == []

    def test_a_struck_two_id_row_retires_the_probe_of_either_id(self, monkeypatch, tmp_path):
        """`retired_ids` keyed the strike marker on a lone leading id, so the
        co-id's probe on a struck two-id row was listed as a candidate rather
        than as retired -- the cries-wolf state the roster rule exists to
        prevent, arriving one door over (DEF-863)."""
        struck = "| ~~`DEF-900`~~ ~~`LG-90`~~ | tools/x.py::f | closed | major |"
        led = tmp_path / "FORWARD_LEDGER.md"
        led.write_text(f"{struck}\n| `DEF-2` | site | what | minor |\n", encoding="utf-8")
        monkeypatch.setattr(check_ledger_probes, "_LEDGER", led)
        probes = [{"id": "DEF-900"}, {"id": "LG-90"}, {"id": "DEF-2"}]
        assert check_ledger_probes.retired_ids(probes) == {"DEF-900", "LG-90"}

    def test_probe_without_a_row_hash_is_silently_skipped_not_crashed(
            self, monkeypatch, tmp_path):
        """Coverage of the axis is enforced in test_forward_ledger_completeness;
        here the only contract is that an un-stamped entry degrades quietly."""
        p = self._probe("x")
        del p["row_sha"]
        assert self._run(monkeypatch, tmp_path, f"{self._MEMBER}\n", p) == []

    def test_missing_ledger_yields_no_false_drift(self, monkeypatch, tmp_path):
        """Adopter trees have no ledger. Absence must read as 'nothing to say',
        never as 'everything drifted' — the same fail-quiet direction the
        subject gate takes for a moved file."""
        monkeypatch.setattr(check_ledger_probes, "_LEDGER", tmp_path / "nope.md")
        assert check_ledger_probes.stale_claims([self._probe("abc")]) == []


class TestTextShaIsTheClaim:
    """`row_sha` covers the whole line, so a structural edit (the §C0 table
    gaining its tag cells re-pinned 37 rows) reads as a claim rewrite. A probe
    carrying `text_sha` is judged on the text cell alone; one without falls
    back to `row_sha` (reflect pass + failure-mode pass, 2026-09-08)."""

    _LINE = "| `DEF-7` | site | the claim | minor | HYGIENE | MAINTAINER |"

    def _mod(self, tmp_path, monkeypatch, line):
        mod = check_ledger_probes
        ledger = tmp_path / "FORWARD_LEDGER.md"
        ledger.write_text("### §C0 - x\n\n| id | site | what | sev | pop | aud |\n"
                          "|---|---|---|---|---|---|\n" + line + "\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_LEDGER", ledger)
        return mod

    def test_a_retag_is_not_stale_when_the_text_is_pinned(self, tmp_path, monkeypatch):
        mod = self._mod(tmp_path, monkeypatch, self._LINE.replace("MAINTAINER", "ADOPTER"))
        probe = {"id": "DEF-7", "row_sha": mod.row_sha(self._LINE), "text_sha": mod.text_sha(self._LINE)}
        assert mod.stale_claims([probe]) == []

    def test_a_text_edit_is_stale_even_with_the_same_tags(self, tmp_path, monkeypatch):
        mod = self._mod(tmp_path, monkeypatch, self._LINE.replace("the claim", "another claim"))
        probe = {"id": "DEF-7", "row_sha": mod.row_sha(self._LINE), "text_sha": mod.text_sha(self._LINE)}
        assert [s[0] for s in mod.stale_claims([probe])] == ["DEF-7"]

    def test_a_probe_without_text_sha_is_judged_on_the_whole_line(self, tmp_path, monkeypatch):
        mod = self._mod(tmp_path, monkeypatch, self._LINE.replace("MAINTAINER", "ADOPTER"))
        probe = {"id": "DEF-7", "row_sha": mod.row_sha(self._LINE)}
        assert [s[0] for s in mod.stale_claims([probe])] == ["DEF-7"]
