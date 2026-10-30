"""Pin the TP-157 157-A scan-telemetry history substrate.

Why this contract exists: ``scan_summary.json`` is overwritten every run, so
the harness could never answer "which self-gov scanner is wallpaper (never
fires) vs noisy (always exempted) over time." 157-A adds an append-only
``scan_telemetry.jsonl`` history beside it. Without this test a refactor could
silently regress the append (truncating instead of appending), break the
round-trip read, or let one malformed tail line poison the whole history —
none of which the point-in-time summary would surface. The integration test
also guards the invariant that wiring telemetry into ``cmd_scan`` does NOT
change the existing ``scan_summary.json`` shape.
"""
from __future__ import annotations

import argparse
import inspect
import json
import pkgutil
import re
from pathlib import Path

import espalier.scanners
from espalier import cli, scan_telemetry
from tests._live_tree import checkout_glob
from espalier import scan_composition

# The scanners cmd_scan drives, read from the map it writes telemetry through
# (one row each per run); TestScannerRosterIsDerivedFromThePackage holds that
# map to the package, so this list is never a hand copy.
_SCANNERS = list(cli.SCAN_TELEMETRY_KEYS)
# The summary's keys that are not a scanner's count.
_SUMMARY_ENVELOPE = {"status", "files_scanned", "not_run"}


def _counts(fires: int = 1, exemptions: int = 0) -> dict:
    # A fresh row object per scanner (a shared one would alias every row).
    # The derived-population census lists this comprehension; its entry in
    # scripts/derived_population_census.py::ADJUDICATED says why it is correct.
    return {s: {"fires": fires, "exemptions": exemptions} for s in _SCANNERS}


class TestAppendRun:
    def test_writes_one_row_per_scanner(self, tmp_path):
        n = scan_telemetry.append_run(tmp_path, "2026-06-02T00:00:00+00:00", _counts())
        # 11 on 2026-10-30: a floor, so a roster that shrinks says so here
        # rather than passing on fewer rows.
        assert n == len(_SCANNERS) >= 11
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == len(_SCANNERS)
        assert {r["scanner"] for r in records} == set(_SCANNERS)

    def test_two_runs_are_additive(self, tmp_path):
        """The pack's 157-A pass criterion: >=20 lines after two runs."""
        scan_telemetry.append_run(tmp_path, "2026-06-02T00:00:00+00:00", _counts())
        scan_telemetry.append_run(tmp_path, "2026-06-02T01:00:00+00:00", _counts(fires=2))
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == 2 * len(_SCANNERS)
        # both run timestamps survive — history, not a snapshot.
        assert {r["run_ts"] for r in records} == {
            "2026-06-02T00:00:00+00:00", "2026-06-02T01:00:00+00:00"
        }

    def test_round_trips_fires_and_exemptions(self, tmp_path):
        counts = {"magic_depth": {"fires": 7, "exemptions": 3}}
        scan_telemetry.append_run(tmp_path, "T", counts)
        (rec,) = scan_telemetry.read_history(tmp_path)
        assert rec == {"run_ts": "T", "scanner": "magic_depth", "fires": 7, "exemptions": 3}

    def test_a_stood_down_scanner_row_says_it_did_not_run(self, tmp_path):
        """A scanner that stood down writes ``ran: false``; one that ran keeps
        the row shape it always had, so older history reads as ran."""
        counts = {
            "magic_depth": {"fires": 0, "exemptions": 0, "ran": False},
            "prints": {"fires": 0, "exemptions": 0, "ran": True},
        }
        scan_telemetry.append_run(tmp_path, "T", counts)
        rows = {r["scanner"]: r for r in scan_telemetry.read_history(tmp_path)}
        assert rows["magic_depth"]["ran"] is False
        assert "ran" not in rows["prints"]

    def test_history_is_capped_to_max_rows(self, tmp_path):
        """Append-only history stays bounded: once past _MAX_TELEMETRY_ROWS only
        the most-recent rows survive, and they are the LATEST (highest run_ts)."""
        one = {"prints": {"fires": 0, "exemptions": 0}}  # 1 row/run
        runs = scan_telemetry._MAX_TELEMETRY_ROWS + 25
        for i in range(runs):
            scan_telemetry.append_run(tmp_path, f"T{i:05d}", one)
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == scan_telemetry._MAX_TELEMETRY_ROWS
        # the survivors are the tail (newest), not the head
        assert records[-1]["run_ts"] == f"T{runs - 1:05d}"
        assert records[0]["run_ts"] == f"T{runs - scan_telemetry._MAX_TELEMETRY_ROWS:05d}"

    def test_empty_counts_writes_nothing(self, tmp_path):
        assert scan_telemetry.append_run(tmp_path, "T", {}) == 0
        assert scan_telemetry.read_history(tmp_path) == []

    def test_creates_reports_dir_if_absent(self, tmp_path):
        target = tmp_path / "nested" / "reports"
        assert not target.exists()
        scan_telemetry.append_run(target, "T", {"prints": {"fires": 0, "exemptions": 0}})
        assert (target / scan_telemetry.TELEMETRY_FILENAME).exists()


class TestReadHistory:
    def test_absent_returns_empty(self, tmp_path):
        assert scan_telemetry.read_history(tmp_path) == []

    def test_skips_malformed_line(self, tmp_path):
        """A partial-write tail or hand-edit must not poison the whole read."""
        scan_telemetry.append_run(tmp_path, "T", {"prints": {"fires": 1, "exemptions": 0}})
        path = tmp_path / scan_telemetry.TELEMETRY_FILENAME
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{not valid json\n")
            fh.write('{"run_ts": "T2", "scanner": "magic_depth", "fires": 0, "exemptions": 0}\n')
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == 2  # the good first line + the good last line
        assert {r["scanner"] for r in records} == {"prints", "magic_depth"}


class TestCmdScanWiring:
    """Integration: cmd_scan appends one telemetry row per scanner it drives
    AND leaves the point-in-time scan_summary.json shape unchanged (no
    duplication)."""

    def _run_scan(self, repo):
        return cli.cmd_scan(argparse.Namespace(repo=str(repo)))

    def _python_repo(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text(
            "def f(x):\n    return x + 1\n", encoding="utf-8"
        )
        return tmp_path

    def test_two_scans_yield_twenty_telemetry_rows(self, tmp_path):
        repo = self._python_repo(tmp_path)
        assert self._run_scan(repo) == 0
        assert self._run_scan(repo) == 0
        records = scan_telemetry.read_history(repo / "reports")
        # one row per driven scanner per run, and every one of them
        assert len(records) == 2 * len(_SCANNERS)
        assert {r["scanner"] for r in records} == set(_SCANNERS)

    def test_summary_shape_preserved(self, tmp_path):
        repo = self._python_repo(tmp_path)
        assert self._run_scan(repo) == 0
        summary = json.loads((repo / "reports" / "scan_summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "scanned"
        # The count keys cmd_scan writes are exactly the map's values, both
        # ways: a count written under no map entry gets no telemetry row, and
        # an entry with no count breaks the telemetry read.
        assert set(summary) - _SUMMARY_ENVELOPE == set(cli.SCAN_TELEMETRY_KEYS.values())


# An import of a scanner module, in the three spellings the tree uses.
_SCANNER_IMPORT = re.compile(
    r"^\s*(?:from espalier\.scanners\.(\w+) import"
    r"|from espalier\.scanners import (\w+)"
    r"|import espalier\.scanners\.(\w+))",
    re.MULTILINE,
)


def _scanner_imports(text: str) -> set[str]:
    return {"".join(groups) for groups in _SCANNER_IMPORT.findall(text)}


def _package_modules() -> set[str]:
    """The public modules of ``espalier.scanners``, read from its directory:
    the population a dropped-in file joins, and neither map."""
    return {m.name for m in pkgutil.iter_modules(espalier.scanners.__path__)
            if not m.name.startswith("_")}


def _scanner_drivers() -> set[tuple[str, tuple[str, str]]]:
    """Every (scanner module, (kind, name)) pair the tree holds, read from source.

    The two kinds ``cli.SCANNERS_NOT_DRIVEN_BY_SCAN`` records: a ``"verb"``,
    a top-level subcommand whose handlers (its own and its nested
    subcommands') import the module, and a ``"test"`` file that does."""
    parser = cli.build_parser()
    top = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    pairs: set[tuple[str, tuple[str, str]]] = set()
    for verb, sub in top.choices.items():
        handlers = [sub.get_default("func")]
        for action in sub._actions:
            if isinstance(action, argparse._SubParsersAction):
                handlers += [nested.get_default("func") for nested in action.choices.values()]
        source = "".join(inspect.getsource(h) for h in handlers if inspect.isfunction(h))
        pairs |= {(module, ("verb", verb)) for module in _scanner_imports(source)}
    for path in checkout_glob(Path(__file__).parent, "test_*.py"):
        text = path.read_text(encoding="utf-8")
        pairs |= {(module, ("test", f"tests/{path.name}")) for module in _scanner_imports(text)}
    return pairs


class TestScannerRosterIsDerivedFromThePackage:
    """Every public module of ``espalier.scanners`` is driven by ``cmd_scan``
    (``SCAN_TELEMETRY_KEYS``: a summary count and a telemetry row each run) or
    recorded with what drives it instead (``SCANNERS_NOT_DRIVEN_BY_SCAN``).
    Until 2026-10-30 the map was a dict local to ``cmd_scan`` that no test
    read, and the two absentees were adjudicated nowhere: a scanner added to
    the package wrote no telemetry, earned no credibility verdict and never
    reached the wallpaper report, with nothing red. A module dropped into the
    package reds the first test here, by name, until one of the two maps
    names it."""

    def test_every_public_scanner_module_is_driven_by_scan_or_recorded(self):
        driven = set(cli.SCAN_TELEMETRY_KEYS)
        recorded = set(cli.SCANNERS_NOT_DRIVEN_BY_SCAN)
        modules = _package_modules()
        assert not driven & recorded, sorted(driven & recorded)
        assert driven | recorded == modules, {
            "in the package, in neither map": sorted(modules - driven - recorded),
            "in a map, not in the package": sorted((driven | recorded) - modules),
        }

    def test_scan_imports_exactly_the_scanners_its_map_names(self):
        """The ``scan`` verb's handler imports every scanner the map names and
        no other, so an entry cannot stand without the scan behind it, nor a
        scan without its entry."""
        by_scan = {module for module, driver in _scanner_drivers()
                   if driver == ("verb", "scan")}
        driven = set(cli.SCAN_TELEMETRY_KEYS)
        assert by_scan == driven, {
            "imported by cmd_scan, not in the map": sorted(by_scan - driven),
            "in the map, not imported by cmd_scan": sorted(driven - by_scan),
        }

    def test_each_recorded_absentee_names_a_driver_that_imports_it(self):
        """The adjudication is checkable, not prose: each recorded (module,
        (kind, name)) pair is one the source holds -- a subcommand of
        ``build_parser()`` whose handlers import the module, or a test file
        that does -- so a driver renamed, removed or rewired reds here."""
        recorded = set(cli.SCANNERS_NOT_DRIVEN_BY_SCAN.items())
        assert recorded - _scanner_drivers() == set()


def test_the_report_file_roster_names_the_same_scanners():
    """The sister roster: ``espalier/scan_composition.py::REPORT_FILES`` maps a
    report file to its scanner for the credibility baseline, the co-flag
    intersect and the pre-release noise set. A scanner enrolled in
    ``SCAN_TELEMETRY_KEYS`` and not here writes a report nothing downstream
    reads; the two populations are held equal, so a twelfth scanner reds here
    by name until both know it."""
    assert set(scan_composition.REPORT_FILES.values()) == set(cli.SCAN_TELEMETRY_KEYS)
