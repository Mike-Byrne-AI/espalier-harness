# pytest-marker: default-unit
"""TP-217c — the four espalier-pinned scanners are gated to the self-host repo.

On an adopter (non-self-host) repo `cmd_scan` must EMIT empty reports for
subprocess_contracts / filesystem_contracts / magic_depth / retired_vocab
(count 0, findings []) rather than walking the repo — encoding_contracts left
that set on 2026-10-08 and walks the adopter's tree with the deployed harness
output left out, pinned below — but
must NOT drop the report files, the 11 summary count keys, or the 11 telemetry rows. The
precision boundary is "report 0, don't vanish": the summary/telemetry
contracts (test_scan_telemetry.py) pin all 11, so an over-aggressive gate
that removed keys/rows would regress them.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from espalier import cli, surface_contract


def _adopter_python_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8"
    )
    return tmp_path


def test_adopter_repo_is_not_self_host(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    assert not surface_contract.is_self_host_repo(repo)


def test_pinned_scanners_emit_empty_reports_on_adopter(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    reports = repo / "reports"
    for name in (
        "scan_subprocess_contracts.json",
        "scan_filesystem_contracts.json",
        "scan_magic_depth.json",
        "scan_retired_vocab.json",
    ):
        path = reports / name
        assert path.exists(), f"{name} must still be written on an adopter repo"
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["count"] == 0
        assert report["findings"] == []
        assert report["ran"] is False
    # The encoding scanner is not in the set: it ran, on a tree with nothing to find.
    ec = json.loads((reports / "scan_encoding_contracts.json").read_text(encoding="utf-8"))
    assert ec.get("ran", True) is True and ec["count"] == 0, ec


def test_gate_does_not_drop_summary_keys_on_adopter(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    summary = json.loads((repo / "reports" / "scan_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "scanned"
    for key in (
        "exceptions", "prints", "large_files", "perf_hotspots",
        "test_loosening", "convergence_theater", "subprocess_contracts",
        "filesystem_contracts", "magic_depth", "retired_vocab",
        "encoding_contracts",
    ):
        assert key in summary
    # the four gated scanners report 0 on an adopter
    for key in ("subprocess_contracts", "filesystem_contracts",
                "magic_depth", "retired_vocab"):
        assert summary[key] == 0


def test_the_encoding_scanner_walks_an_adopter_tree_but_not_the_deployed_hooks(tmp_path):
    """encoding_contracts runs on an adopter tree (it left SELF_HOST_ONLY_SCANNERS
    on 2026-10-08) and its walk is BOUNDED: the adopter's own locale read is a
    finding, their pragma is counted into the overrides corpus, and the deployed
    harness output -- `tools/cc/` here -- is left out, so an adopter never reads
    a wall of findings about the hooks `init` wrote. Drop the exempt prefixes
    `cmd_scan` passes and the `tools/cc/` finding appears (driven red); the
    overrides corpus is walked on the same scope, so the deployed hook's own
    pragma never lands in the adopter's persisted corpus (the 5-A review's
    BLOCK, driven red against the unbounded call)."""
    repo = _adopter_python_repo(tmp_path)
    (repo / "pkg" / "ok.py").write_text(
        "from pathlib import Path\n"
        "# encoding-locale-ok: an adopter pragma, counted into their overrides corpus\n"
        "x = Path('f').read_text(encoding='ascii')\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "bad.py").write_text(
        "def load(p):\n    return open(p).read()\n", encoding="utf-8"
    )
    hook = repo / "tools" / "cc" / "hooks" / "deployed.py"
    hook.parent.mkdir(parents=True)
    hook.write_text(
        "from pathlib import Path\n"
        "# encoding-locale-ok: a deployed hook's own pragma, never the adopter's corpus\n"
        "y = Path('g').read_text(encoding='ascii')\n"
        "def load(p):\n    return open(p).read()\n",
        encoding="utf-8",
    )
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    report = json.loads((repo / "reports" / "scan_encoding_contracts.json").read_text(encoding="utf-8"))
    paths = sorted(f["path"] for f in report["findings"])
    assert report.get("ran", True) is True and paths == ["pkg/bad.py"], report
    assert not [p for p in paths if p.startswith("tools/cc/")], paths
    # The narrowing is on the record, in the report itself.
    from espalier.analyze import HARNESS_OUTPUT_PREFIXES
    assert report["walk_exempt"] == [f"{p}/" for p in HARNESS_OUTPUT_PREFIXES], report["walk_exempt"]
    overrides = json.loads((repo / "reports" / "scan_overrides.json").read_text(encoding="utf-8"))
    assert [o["path"] for o in overrides["overrides"] if o["scanner"] == "encoding_contracts"] == ["pkg/ok.py"]
    from espalier import scan_telemetry
    rows = [r for r in scan_telemetry.read_history(repo / "reports") if r["scanner"] == "encoding_contracts"]
    assert rows and all(r.get("ran", True) is True and r["fires"] == 1 and r["exemptions"] == 1 for r in rows), rows


# ── A stood-down scanner is recorded as not run, never as a clean zero ──────
#
# The empty reports above keep every key present; these pin that each record
# of the run also says the five did not run, so an adopter does not read
# `Subproc: 0 | FS: 0 | ...` as a verdict on code nothing looked at. Until
# 2026-10-04 the one not-run sentence printed only when no scanner found
# anything, and the five zeros reached the summary and the credibility budget
# as observations.


def _scan(repo, capsys=None):
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    return capsys.readouterr().out if capsys is not None else ""


def test_every_stood_down_report_says_it_did_not_run_and_why(tmp_path):
    """Derived from the run, both ways: the reports marked `ran: false` are
    exactly SELF_HOST_ONLY_SCANNERS (a key in the tuple that no gated call
    reads would leave one missing here), and every other report ran."""
    repo = _adopter_python_repo(tmp_path)
    _scan(repo)
    marked = set()
    for path in (repo / "reports").glob("*.json"):
        if path.name in ("scan_summary.json", "scan_overrides.json"):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(report, dict) and report.get("ran") is False:
            assert report["why"], path.name
            marked.add(path.stem.removeprefix("scan_"))
    assert marked == set(cli.SELF_HOST_ONLY_SCANNERS)


def test_the_summary_lists_what_did_not_run(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    _scan(repo)
    summary = json.loads((repo / "reports" / "scan_summary.json").read_text(encoding="utf-8"))
    assert summary["not_run"] == sorted(cli.SELF_HOST_ONLY_SCANNERS)


def test_the_counts_line_prints_n_a_and_the_note_prints_beside_a_finding(tmp_path, capsys):
    """The usual adopter run has a finding somewhere; the not-run note must
    print on that run too, and the four labels read n/a, not 0 -- while
    Encoding, which runs here since 2026-10-08, reads its real count."""
    repo = _adopter_python_repo(tmp_path)
    (repo / "pkg" / "noisy.py").write_text("print('hello')\n", encoding="utf-8")
    out = _scan(repo, capsys)
    counts = next(line for line in out.splitlines() if line.startswith("Exceptions: "))
    cells = dict(cell.split(": ", 1) for cell in counts.split(" | "))
    for label in ("Subproc", "FS", "MagicDepth", "RetiredVocab"):
        assert cells[label] == "n/a", counts
    assert cells["Encoding"] == "0", counts   # ran, on a tree with nothing to find
    assert cells["Prints"] == "1", counts
    assert "Details (file and line per finding)" in out, out
    assert "Espalier-only scanners that do not run here" in out, out


def test_a_stood_down_scanner_never_reads_as_wallpaper(tmp_path):
    """End to end, scan to telemetry to the credibility budget: past the
    budget's run floor, none of the four is judged, while a scanner that ran
    and never fired still is (the budget is not simply switched off)."""
    from espalier import scan_credibility, scan_telemetry
    repo = _adopter_python_repo(tmp_path)
    for _ in range(scan_credibility.WALLPAPER_MIN_RUNS + 1):
        _scan(repo)
    rows = scan_telemetry.read_history(repo / "reports")
    assert {r["scanner"] for r in rows if r.get("ran") is False} == set(cli.SELF_HOST_ONLY_SCANNERS)
    report = scan_credibility.wallpaper_report(rows)
    assert not set(cli.SELF_HOST_ONLY_SCANNERS) & set(report), sorted(report)
    assert report["prints"]["status"] == "candidate-wallpaper", report["prints"]


_SCAN_ROW = re.compile(r"^\| `/scan (\w+)` \|(.*)\|\s*$", re.MULTILINE)


def _self_host_only_rows(body: str) -> tuple[set[str], set[str]]:
    """(every scanner with a `/scan <name>` row, the ones marked self-host only)."""
    rows = {m.group(1): m.group(2) for m in _SCAN_ROW.finditer(body)}
    return set(rows), {name for name, cell in rows.items() if "(self-host only)" in cell}


# reads the shipped command body: doc text a docs-only change moves, so it
# runs in the tier such a change earns
@pytest.mark.contract
def test_the_scan_body_marks_exactly_the_scanners_that_stand_down():
    """Both directions, on the body adopters receive: a gated scanner without
    the mark lets an agent report it as checked clean; a mark on a scanner
    that runs everywhere tells it to discount a real result."""
    body = (Path(cli.__file__).parent / "assets" / "claude" / "commands" / "scan.md"
            ).read_text(encoding="utf-8")
    rows, marked = _self_host_only_rows(body)
    assert set(cli.SELF_HOST_ONLY_SCANNERS) <= rows, sorted(set(cli.SELF_HOST_ONLY_SCANNERS) - rows)
    assert marked == set(cli.SELF_HOST_ONLY_SCANNERS), (sorted(marked), cli.SELF_HOST_ONLY_SCANNERS)



@pytest.mark.contract
def test_the_scan_body_names_prefixes_the_bounded_walk_really_leaves_out():
    """The encoding row's parenthetical names the deployed harness output the
    walk leaves out off self-host; every name it gives is one the derived
    exempt set really holds (the list is illustrative, so a subset, both on
    the body adopters receive)."""
    from espalier.analyze import HARNESS_OUTPUT_PREFIXES
    body = (Path(cli.__file__).parent / "assets" / "claude" / "commands" / "scan.md"
            ).read_text(encoding="utf-8")
    row = next(m for m in _SCAN_ROW.finditer(body) if m.group(1) == "encoding_contracts")
    named = re.findall(r"`([^`]+/)`", row.group(2).split("deployed harness output (", 1)[1])
    derived = {f"{p}/" for p in HARNESS_OUTPUT_PREFIXES}
    assert named and set(named) <= derived, (named, sorted(derived))


def test_every_bounded_scanner_threads_exempt_to_its_pragma_walks():
    """A key added to WALK_BOUNDED_OFF_SELF_HOST makes `_gated` call its
    builder with `exempt=`; the pragma count and the overrides corpus beside it
    are hand-wired per scanner, so this pins all three -- a bounded report with
    an unbounded pragma walk would break the scanner's own scope invariant."""
    import importlib
    import inspect
    src = inspect.getsource(cli.cmd_scan)
    for key in cli.WALK_BOUNDED_OFF_SELF_HOST:
        mod = importlib.import_module(f"espalier.scanners.{key}")
        for fn in ("build_report", "count_pragmas", "collect_pragmas"):
            assert "exempt" in inspect.signature(getattr(mod, fn)).parameters, (key, fn)
        assert src.count(f'bounded_exempt.get("{key}", ())') >= 2, key   # the count and the corpus


def test_history_from_before_the_ran_flag_does_not_bring_the_advisory_back(tmp_path, capsys):
    """An adopter who scanned before telemetry carried `ran` holds rows of the
    five's placeholder zeros with no flag. Those runs must not put the five in
    the advisory on the very run that prints `Not run:` (failure-mode review,
    driven on an upgraded tree: all five listed beside the not-run line)."""
    from espalier import scan_credibility, scan_telemetry
    repo = _adopter_python_repo(tmp_path)
    for i in range(scan_credibility.WALLPAPER_MIN_RUNS + 2):
        scan_telemetry.append_run(
            repo / "reports", f"OLD{i}",
            {s: {"fires": 0, "exemptions": 0} for s in cli.SELF_HOST_ONLY_SCANNERS},
        )
    out = _scan(repo, capsys)
    assert "Not run: " in out, out
    advisory = [line for line in out.splitlines() if line.startswith("Scan credibility")]
    for line in advisory:
        for scanner in cli.SELF_HOST_ONLY_SCANNERS:
            assert scanner not in line, line


def test_the_not_run_line_names_the_scanners_by_key(tmp_path, capsys):
    """By the key `/scan` and the summary's `not_run` use, so a reader can map
    the line to both without a table."""
    repo = _adopter_python_repo(tmp_path)
    out = _scan(repo, capsys)
    (line,) = [ln for ln in out.splitlines() if ln.startswith("Not run: ")]
    for scanner in cli.SELF_HOST_ONLY_SCANNERS:
        assert scanner in line, line


def test_a_tree_without_python_still_lists_what_did_not_run(tmp_path):
    (tmp_path / "README.md").write_text("# not python\n", encoding="utf-8")
    _scan(tmp_path)
    summary = json.loads((tmp_path / "reports" / "scan_summary.json").read_text(encoding="utf-8"))
    assert summary == {"status": "skipped_no_python_files",
                       "not_run": sorted(cli.SELF_HOST_ONLY_SCANNERS)}


def test_the_self_host_answer_is_read_only_inside_the_gate():
    """A later scanner gated inline (`scan_x(root) if _pinned_self_host else
    {...}`, the idiom this file's first tests describe) would write a report
    with no `ran: false`, print `0`, and pass every test above, since each
    derives from the tuple. So the self-host answer is asked once, and read
    only inside `_gated`: a second reader reds here."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(cli.cmd_scan)).body[0]
    gate = next(n for n in ast.walk(fn) if isinstance(n, ast.FunctionDef) and n.name == "_gated")
    inside = {id(n) for n in ast.walk(gate)}
    readers = [n for n in ast.walk(fn)
               if isinstance(n, ast.Name) and n.id == "_pinned_self_host"
               and isinstance(n.ctx, ast.Load) and id(n) not in inside]
    asks = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "is_self_host_repo"]
    assert not readers, [n.lineno for n in readers]
    assert len(asks) == 1, [n.lineno for n in asks]
