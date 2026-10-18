"""The guard oracles' receipts name their tree, and a baseline from another tree is refused (DEF-860).

``bench/powershell_guard_rehearsal.py`` and ``bench/guard_row_probe.py`` drive
the guard's row tables and write a receipt (``bench/rehearsal-results.json``,
``bench/row-probe-results.json``, both gitignored). The scarce Windows pass is
read as a diff against a baseline receipt from another host, and a baseline
written at another tree reads every verdict the tree moved as a Windows
regression: the 2026-09-20 baseline sat four guard commits behind HEAD, and
regenerating it moved nine verdicts. These pin the consumer side, a
``--baseline`` run that refuses before a single row runs a baseline it cannot
honestly diff against, and the producer's own stale-tree check, which compares
the guard under test with the guard the rows were written against instead of
looking for a 2026-08 symbol.

Every test here runs in-process: the drive is stubbed and the tree's facts are
planted, so no hook and no git process is spawned.
"""
# pytest-marker: default-unit -- in-process and spawn-free, which is what the
# `unit` marker declares; the guard is never driven here (the stale-tree test
# stubs git out), so the enforcement slice's spawning contracts are not its kind.
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests._live_tree import checkout_glob, copy_checkout

_BENCH_DIR = Path(__file__).resolve().parent.parent / "bench"
_REPO_ROOT = _BENCH_DIR.parent
_REHEARSAL = "powershell_guard_rehearsal"
_PROBE = "guard_row_probe"


def _oracles() -> list[str]:
    """Every bench script that names its tree, read from the source, so the
    next oracle that writes a receipt is pinned here too."""
    return sorted(p.stem for p in checkout_glob(_BENCH_DIR, "*.py")
                  if "tree_facts(" in p.read_text(encoding="utf-8"))


_ORACLES = _oracles()


def test_the_derived_oracles_hold_the_two_that_write_receipts():
    """A floor under the derivation: a renamed helper empties it, and an empty
    parameter set skips every oracle test instead of failing one."""
    assert {_REHEARSAL, _PROBE} <= set(_ORACLES)


@pytest.fixture
def bench(monkeypatch):
    """A loader for ``bench/<name>.py``, registered under its bare name (the
    probe imports the rehearsal by name), with sys.path and sys.modules put
    back after the test."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in (_REHEARSAL, _PROBE):
        monkeypatch.delitem(sys.modules, name, raising=False)

    def load(name: str) -> ModuleType:
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, _BENCH_DIR / f"{name}.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, mod)
        spec.loader.exec_module(mod)
        return mod

    load(_REHEARSAL)
    return load


_SAME = object()


def _facts(rehearsal, sha="93df04f1", guard="g1", *, rows_guard=_SAME, rows_sha=_SAME, rows="r1"):
    """Planted ``TreeFacts``: the rows' guard and commit default to the ones
    under test (one checkout)."""
    return rehearsal.TreeFacts(sha, guard, guard if rows_guard is _SAME else rows_guard,
                               sha if rows_sha is _SAME else rows_sha, rows)


def _cc(root: Path, files: dict[str, bytes]) -> Path:
    """A ``tools/cc/`` tree under ``root`` holding ``files`` (paths below it)."""
    base = root / "tools" / "cc"
    for name, data in files.items():
        (base / name).parent.mkdir(parents=True, exist_ok=True)
        (base / name).write_bytes(data)
    return root


class TestTheGuardDigest:
    def test_one_commit_on_two_platforms_reads_one_digest(self, bench, tmp_path):
        """A Windows checkout with autocrlf holds CRLF where macOS holds LF."""
        rehearsal = bench(_REHEARSAL)
        lf = _cc(tmp_path / "lf", {"hooks/write_guard.py": b"a = 1\nb = 2\n"})
        crlf = _cc(tmp_path / "crlf", {"hooks/write_guard.py": b"a = 1\r\nb = 2\r\n"})
        assert rehearsal.guard_digest(lf) == rehearsal.guard_digest(crlf) is not None

    def test_a_changed_byte_a_new_module_or_a_module_beside_the_hooks_moves_it(self, bench, tmp_path):
        """A zone constant in ``tools/cc/_paths.py`` moves a verdict as surely
        as a hook does (the failure-mode review drove one)."""
        rehearsal = bench(_REHEARSAL)
        files = {"hooks/write_guard.py": b"a = 1\n", "_paths.py": b"Z = 'cc/'\n"}
        base = rehearsal.guard_digest(_cc(tmp_path / "a", files))
        for i, change in enumerate([{"hooks/write_guard.py": b"a = 2\n"}, {"hooks/_new.py": b""},
                                    {"_paths.py": b"Z = 'cc/LIVE'\n"}]):
            assert rehearsal.guard_digest(_cc(tmp_path / f"b{i}", {**files, **change})) != base, change

    def test_caches_and_prose_beside_the_guard_do_not_move_it(self, bench, tmp_path):
        rehearsal = bench(_REHEARSAL)
        base = rehearsal.guard_digest(_cc(tmp_path / "a", {"hooks/write_guard.py": b"a = 1\n"}))
        other = _cc(tmp_path / "b", {"hooks/write_guard.py": b"a = 1\n", "hooks/CLAUDE.md": b"notes\n",
                                     "hooks/__pycache__/write_guard.cpython-311.pyc": b"\x00\x01"})
        assert rehearsal.guard_digest(other) == base

    def test_files_are_taken_in_the_order_of_their_names_as_strings(self, bench, tmp_path):
        """Windows sorts paths case-blind and POSIX by code point, so a module
        named with a capital would make one commit read two digests."""
        rehearsal = bench(_REHEARSAL)
        root = _cc(tmp_path, {"hooks/Zones.py": b"z\n", "hooks/a.py": b"a\n"})
        want = hashlib.sha256()
        for name, data in (("hooks/Zones.py", b"z\n"), ("hooks/a.py", b"a\n")):   # "Z" < "a"
            want.update(name.encode() + b"\0" + data + b"\0")
        assert rehearsal.guard_digest(root) == want.hexdigest()[:16]

    def test_a_tree_with_no_guard_has_no_digest(self, bench, tmp_path):
        assert bench(_REHEARSAL).guard_digest(tmp_path) is None

    def test_the_rows_digest_reads_both_oracles_and_moves_with_either(self, bench, tmp_path):
        rehearsal = bench(_REHEARSAL)
        root = tmp_path / "rows"
        (root / "bench").mkdir(parents=True)
        for name in rehearsal.ORACLE_FILES:
            (root / "bench" / name).write_bytes(b"ROWS = []\n")
        base = rehearsal.rows_digest(root)
        assert base is not None and set(rehearsal.ORACLE_FILES) == {f"{_REHEARSAL}.py", f"{_PROBE}.py"}
        (root / "bench" / f"{_PROBE}.py").write_bytes(b"ROWS = [1]\n")
        assert rehearsal.rows_digest(root) != base
        (root / "bench" / f"{_PROBE}.py").unlink()
        assert rehearsal.rows_digest(root) is None


class TestTheStaleTreeIsReadFromTheTree:
    def test_a_guard_other_than_the_rows_own_is_refused(self, bench, capsys):
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.refuse_stale_tree(_facts(rehearsal, guard="aaaa", rows_guard="bbbb")) is True
        err = capsys.readouterr().err
        assert "STOP" in err and "aaaa" in err and "bbbb" in err

    def test_an_unread_guard_is_refused(self, bench):
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.refuse_stale_tree(_facts(rehearsal, guard=None, rows_guard="bbbb")) is True
        assert rehearsal.refuse_stale_tree(_facts(rehearsal, guard="aaaa", rows_guard=None)) is True

    def test_another_commit_with_an_equal_guard_is_refused(self, bench, capsys):
        """A receipt names one commit; a checkout at another one, guard
        untouched, would be recorded under the wrong name."""
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.refuse_stale_tree(_facts(rehearsal, sha="470ab751", rows_sha="6f37f1f5")) is True
        assert "470ab751" in capsys.readouterr().err

    def test_the_rows_own_guard_runs(self, bench, capsys):
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.refuse_stale_tree(_facts(rehearsal)) is False
        assert capsys.readouterr().err == ""

    def test_the_rows_own_guard_is_this_checkouts(self, bench):
        """The digest is of the guard beside the script: one checkout, one guard."""
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.ROWS_ROOT == _REPO_ROOT
        assert rehearsal.guard_digest(rehearsal.ROWS_ROOT) is not None

    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_foreign_checkout_whose_guard_moved_is_refused_before_a_row(self, bench, name, monkeypatch, tmp_path):
        """The 2026-08-24 marker passed any checkout newer than that day: a
        copy of this guard with one function body changed still carries it."""
        mod = bench(name)
        foreign = tmp_path / "foreign"
        copy_checkout(_REPO_ROOT / "tools" / "cc", foreign / "tools" / "cc")
        patterns = foreign / "tools" / "cc" / "hooks" / "_bash_patterns.py"
        patterns.write_bytes(patterns.read_bytes() + b"\n# a later guard commit\n")
        rehearsal = bench(_REHEARSAL)

        def no_git(*args, **kwargs):
            raise OSError("no git in this test")

        monkeypatch.setattr(rehearsal, "run_bounded", no_git)
        monkeypatch.setattr(mod, "drive", lambda *a, **k: pytest.fail("a row ran on a stale tree"))
        assert mod.main(["--repo-root", str(foreign), "--out", str(tmp_path / "r.json")]) == 4


def _receipt(**overrides) -> dict:
    record = {"oracle": _REHEARSAL, "host": "the-baseline-host", "platform": "macOS-15",
              "python": "3.11.9", "tree_sha": "93df04f1", "guard_digest": "g1", "rows_digest": "r1",
              "has_fixes": True, "shapes": ["plain", "spaced"], "passed": 4, "mismatched": 0,
              "known_gaps": 0, "gaps_closed": 0,
              "rows": [{"id": i, "shape": s, "actual": "HARD"} for i in ("a", "b") for s in ("plain", "spaced")]}
    record.update(overrides)
    return record


class TestABaselineThatCannotBeHonestlyDiffedIsRefused:
    @pytest.mark.parametrize(("baseline", "sha", "says"), [
        pytest.param({"oracle": _PROBE}, "93df04f", _PROBE, id="the-other-oracle"),
        pytest.param({"oracle": None}, "93df04f", "nameless", id="a-receipt-from-before-the-oracle-was-named"),
        pytest.param({"host": platform.node()}, "93df04f", "this host", id="this-hosts-own-receipt"),
        pytest.param({"tree_sha": "842bc68"}, "93df04f", "842bc68", id="another-commit"),
        pytest.param({"tree_sha": "unknown"}, "93df04f", "unknown", id="baseline-names-no-tree"),
        pytest.param({"tree_sha": None}, "93df04f", "unknown", id="baseline-with-an-empty-tree-field"),
        pytest.param({"tree_sha": "93df04f"}, "unknown", "unknown", id="this-checkout-unread"),
        pytest.param({"tree_sha": "unknown"}, "unknown", "unknown", id="neither-side-read"),
        pytest.param({"guard_digest": None}, "93df04f", "guard digests", id="baseline-without-a-guard-digest"),
        pytest.param({"guard_digest": "g0"}, "93df04f", "uncommitted edits under tools/cc", id="same-commit-other-guard"),
        pytest.param({"rows_digest": None}, "93df04f", "rows digests", id="baseline-without-a-rows-digest"),
        pytest.param({"rows_digest": "r0"}, "93df04f", "uncommitted edits to", id="same-commit-other-rows"),
        pytest.param({"rows": None}, "93df04f", "rows are not", id="no-rows"),
        pytest.param({"rows": "abc"}, "93df04f", "rows are not", id="rows-a-string"),
        pytest.param({"rows": [1]}, "93df04f", "rows are not", id="rows-not-objects"),
        pytest.param({"rows": [{"id": "a", "actual": "HARD"}]}, "93df04f", "rows are not", id="a-row-without-a-shape"),
        pytest.param({"rows": []}, "93df04f", "no shape in common", id="an-empty-table"),
        pytest.param({"rows": [{"id": "a", "shape": "paren", "actual": "HARD"}]}, "93df04f",
                     "no shape in common", id="no-shape-in-common"),
    ])
    def test_the_refusal_says_why(self, bench, baseline, sha, says):
        rehearsal = bench(_REHEARSAL)
        reason = rehearsal.baseline_refusal(_receipt(**baseline), _facts(rehearsal, sha=sha),
                                            oracle=_REHEARSAL, shapes=["plain", "spaced"])
        assert reason is not None and says in reason, reason

    @pytest.mark.parametrize("ours", ["93df04f", "93df04f1", "93df04f1aa"])
    def test_one_commit_at_another_short_length_is_the_same_tree(self, bench, ours):
        """``git rev-parse --short`` picks its length per clone."""
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.baseline_refusal(_receipt(), _facts(rehearsal, sha=ours),
                                          oracle=_REHEARSAL, shapes=["plain"]) is None

    def test_a_short_prefix_never_matches(self, bench):
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.baseline_refusal(_receipt(tree_sha="93df"), _facts(rehearsal, sha="93df04f"),
                                          oracle=_REHEARSAL, shapes=["plain"]) is not None


class TestTheDifferences:
    def test_a_verdict_that_moved_and_a_row_on_one_side_are_named(self, bench):
        rehearsal = bench(_REHEARSAL)
        theirs = [{"id": "a", "shape": "plain", "actual": "HARD"}, {"id": "b", "shape": "plain", "actual": "SOFT"}]
        ours = [{"id": "a", "shape": "plain", "actual": "ALLOW"}, {"id": "c", "shape": "plain", "actual": "HARD"}]
        assert rehearsal.baseline_differences(theirs, ours) == [
            "a@plain: baseline HARD, here ALLOW",
            "b@plain: in the baseline only (SOFT)",
            "c@plain: here only (HARD)",
        ]

    def test_only_the_shapes_both_sides_ran_are_compared(self, bench):
        """A run narrowed to one shape is not told the other shapes vanished."""
        rehearsal = bench(_REHEARSAL)
        theirs = [{"id": "a", "shape": s, "actual": "HARD"} for s in ("plain", "spaced")]
        ours = [{"id": "a", "shape": "plain", "actual": "HARD"}]
        assert rehearsal.baseline_differences(theirs, ours) == []

    def test_a_difference_each_side_expects_is_declared_and_does_not_fail(self, bench):
        """DEF-2024's probe rows: on each side the host-keyed rows read the
        tier their own host's table expects (4B-6 on the drive-root temp, 4B-3
        and 4D-3 on a shallow home), which is the table working. The control
        row's second side is off its own expectation, so it still fails."""
        rehearsal = bench(_REHEARSAL)
        theirs = [_row("4B-6", "ALLOW", "ALLOW"), _row("4B-3", "SOFT", "SOFT"),
                  _row("4D-3", "SOFT", "SOFT"), _row("control", "SOFT", "SOFT")]
        ours = [_row("4B-6", "SOFT", "SOFT"), _row("4B-3", "HARD", "HARD"),
                _row("4D-3", "HARD", "HARD"), _row("control", "SOFT", "ALLOW")]
        assert rehearsal.baseline_differences(theirs, ours) == ["control@plain: baseline SOFT, here ALLOW"]
        assert rehearsal.host_differences(theirs, ours) == [
            "4B-3@plain: the baseline expects and reads SOFT, here expects and reads HARD",
            "4B-6@plain: the baseline expects and reads ALLOW, here expects and reads SOFT",
            "4D-3@plain: the baseline expects and reads SOFT, here expects and reads HARD",
        ]

    @pytest.mark.parametrize(("theirs", "ours"), [
        pytest.param(("ALLOW", "ALLOW"), ("SOFT", "HARD"), id="this-run-off-its-own-expectation"),
        pytest.param(("ALLOW", "HARD"), ("SOFT", "SOFT"), id="the-baseline-off-its-own-expectation"),
        pytest.param(("SOFT", "SOFT"), ("SOFT", "ALLOW"), id="one-expectation-on-both-sides"),
        pytest.param((None, "ALLOW"), ("SOFT", "SOFT"), id="a-baseline-row-with-no-expectation"),
        pytest.param(("ALLOW", "ALLOW"), (None, "SOFT"), id="a-row-here-with-no-expectation"),
    ])
    def test_a_side_off_its_own_expectation_still_fails(self, bench, theirs, ours):
        """A real difference on a host-keyed row is a failing line, never a
        declared one: the declaration needs both sides on their own tier."""
        rehearsal = bench(_REHEARSAL)
        base, here = [_row("4B-6", *theirs)], [_row("4B-6", *ours)]
        assert rehearsal.baseline_differences(base, here) == [f"4B-6@plain: baseline {theirs[1]}, here {ours[1]}"]
        assert rehearsal.host_differences(base, here) == []


def _module_tree(name: str) -> ast.Module:
    return ast.parse((_BENCH_DIR / f"{name}.py").read_text(encoding="utf-8"))


def _keyed_rows(name: str) -> list[str]:
    """The ids of ``bench/<name>.py``'s ``ROWS`` whose expected tier is not a
    string literal, read from the source: every row whose expectation can
    follow the host it runs on."""
    table = next(node.value for node in _module_tree(name).body
                 if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "ROWS")
    assert isinstance(table, ast.List) and table.elts, name
    return sorted(ast.literal_eval(row.elts[0]) for row in table.elts
                  if not (isinstance(row.elts[1], ast.Constant) and isinstance(row.elts[1].value, str)))


def _names_read(name: str, key: str) -> set[str]:
    """The bare names the module-level assignment of ``key`` reads."""
    value = next(node.value for node in _module_tree(name).body
                 if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == key)
    return {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}


class TestTheHostKeyedRows:
    """A declared host difference passes the diff (DEF-2024), so a row whose
    expectation follows the host is quiet on both signals: its MISMATCH and its
    cross-host difference. The keyed rows are pinned by id, so a new key is an
    edit here, made on purpose, and each key reads a host fact the guard does
    not compute, never the guard's own verdict (the failure-mode review)."""

    def test_the_probe_keys_three_rows_and_the_rehearsal_none(self):
        assert _keyed_rows(_PROBE) == ["4B-3", "4B-6", "4D-3"]
        assert _keyed_rows(_REHEARSAL) == []

    def test_each_key_reads_the_disk_or_the_home_and_nothing_of_the_guard(self):
        """``_DRIVE_CD_TIER`` reads ``os.name`` and the drive-root temp on disk;
        ``_SHALLOW_HOME`` the depth of the home. A key rewritten to ask a
        guard helper reads a name outside these."""
        assert _names_read(_PROBE, "_DRIVE_CD_TIER") == {"os", "Path"}
        assert _names_read(_PROBE, "_SHALLOW_HOME") == {"len", "Path"}


def _row(case_id: str, expected: str | None, actual: str) -> dict:
    """A receipt row on the plain shape; ``expected`` None leaves the key out,
    as a receipt that carries no expectation does."""
    row = {"id": case_id, "shape": "plain", "actual": actual}
    if expected is not None:
        row["expected"] = expected
    return row


def _stub_run(mod, monkeypatch, rows: list[dict], sha="93df04f1"):
    rehearsal = sys.modules[_REHEARSAL]
    planted = _facts(rehearsal, sha=sha)
    monkeypatch.setattr(mod, "tree_facts", lambda root: planted)
    ran = []

    def drive(hook, table, gaps, shapes):
        ran.append(shapes)
        return {"passed": len(rows), "mismatched": 0, "known_gaps": 0, "gaps_closed": 0,
                "rows": [r for r in rows if r["shape"] in shapes]}

    monkeypatch.setattr(mod, "drive", drive)
    return ran


def _carried(path: Path) -> Path:
    """The receipt at ``path`` as another host wrote it: carried across by
    hand, it names the host it came from."""
    record = json.loads(path.read_text(encoding="utf-8"))
    record["host"] = "the-baseline-host"
    carried = path.with_name("carried-" + path.name)
    carried.write_text(json.dumps(record), encoding="utf-8")
    return carried


class TestTheOraclesReadABaseline:
    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_refused_baseline_runs_no_row(self, bench, name, monkeypatch, tmp_path):
        mod = bench(name)
        ran = _stub_run(mod, monkeypatch, [])
        baseline = tmp_path / "rehearsal-results.json"
        baseline.write_text(json.dumps(_receipt(oracle=name, tree_sha="842bc68")), encoding="utf-8")
        out = tmp_path / "here.json"
        rc = mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline), "--out", str(out)])
        assert rc == 5 and ran == [] and not out.exists()

    @pytest.mark.parametrize("name", _ORACLES)
    @pytest.mark.parametrize("content", ["{not json", "[]", None], ids=["invalid", "not-an-object", "missing"])
    def test_an_unreadable_baseline_is_refused(self, bench, name, content, monkeypatch, tmp_path):
        mod = bench(name)
        ran = _stub_run(mod, monkeypatch, [])
        baseline = tmp_path / "rehearsal-results.json"
        if content is not None:
            baseline.write_text(content, encoding="utf-8")
        rc = mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline),
                       "--out", str(tmp_path / "here.json")])
        assert rc == 5 and ran == []

    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_baseline_that_is_also_the_out_file_is_refused_before_it_is_overwritten(
            self, bench, name, monkeypatch, tmp_path):
        mod = bench(name)
        ran = _stub_run(mod, monkeypatch, [])
        baseline = tmp_path / "rehearsal-results.json"
        baseline.write_text(json.dumps(_receipt(oracle=name)), encoding="utf-8")
        before = baseline.read_bytes()
        rc = mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline),
                       "--out", str(tmp_path / "." / "rehearsal-results.json")])
        assert rc == 2 and ran == [] and baseline.read_bytes() == before

    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_verdict_that_differs_on_this_host_fails_the_run_and_lands_in_the_receipt(
            self, bench, name, monkeypatch, tmp_path, capsys):
        mod = bench(name)
        here = [{"id": i, "shape": s, "actual": "ALLOW" if (i, s) == ("b", "spaced") else "HARD"}
                for i in ("a", "b") for s in ("plain", "spaced")]
        _stub_run(mod, monkeypatch, here)
        baseline = tmp_path / "rehearsal-results.json"
        baseline.write_text(json.dumps(_receipt(oracle=name)), encoding="utf-8")
        out = tmp_path / "here.json"
        rc = mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline), "--out", str(out)])
        assert rc == 1
        block = json.loads(out.read_text(encoding="utf-8"))["baseline"]
        assert block["differences"] == ["b@spaced: baseline HARD, here ALLOW"]
        assert block["tree_sha"] == "93df04f1" and block["host"] == "the-baseline-host"
        assert block["shapes_compared"] == ["plain", "spaced"]
        said = capsys.readouterr().out
        assert "b@spaced: baseline HARD, here ALLOW" in said and "shapes plain, spaced" in said

    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_run_whose_only_differences_are_declared_passes_and_says_them(
            self, bench, name, monkeypatch, tmp_path, capsys):
        """DEF-2024: a Windows pass diffed against a macOS receipt differs on
        the host-keyed rows by design. The run exits 0, prints them under their
        own heading and keeps them in the receipt apart from the failing ones."""
        mod = bench(name)
        _stub_run(mod, monkeypatch, [_row("a", "ALLOW", "ALLOW"), _row("b", "HARD", "HARD")])
        baseline = tmp_path / "rehearsal-results.json"
        rows = [_row("a", "SOFT", "SOFT"), _row("b", "HARD", "HARD")]
        baseline.write_text(json.dumps(_receipt(oracle=name, rows=rows)), encoding="utf-8")
        out = tmp_path / "here.json"
        rc = mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline), "--out", str(out)])
        assert rc == 0
        block = json.loads(out.read_text(encoding="utf-8"))["baseline"]
        declared = "a@plain: the baseline expects and reads SOFT, here expects and reads ALLOW"
        assert block["differences"] == [] and block["host_differences"] == [declared]
        said = capsys.readouterr().out
        assert "0 difference(s), 1 declared host difference(s)" in said and declared in said
        assert said.index(declared) < said.index("0 difference(s) fail the run; the 1 declared above do not")

    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_real_difference_beside_a_declared_one_fails_and_each_is_said_apart(
            self, bench, name, monkeypatch, tmp_path, capsys):
        mod = bench(name)
        _stub_run(mod, monkeypatch, [_row("a", "ALLOW", "ALLOW"), _row("b", "HARD", "ALLOW")])
        baseline = tmp_path / "rehearsal-results.json"
        rows = [_row("a", "SOFT", "SOFT"), _row("b", "HARD", "HARD")]
        baseline.write_text(json.dumps(_receipt(oracle=name, rows=rows)), encoding="utf-8")
        out = tmp_path / "here.json"
        rc = mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline), "--out", str(out)])
        assert rc == 1
        block = json.loads(out.read_text(encoding="utf-8"))["baseline"]
        assert block["differences"] == ["b@plain: baseline HARD, here ALLOW"]
        assert block["host_differences"] == [
            "a@plain: the baseline expects and reads SOFT, here expects and reads ALLOW"]
        said = capsys.readouterr().out
        assert said.index("b@plain: baseline HARD") < said.index("declared host differences") < said.index("a@plain")
        assert said.index("a@plain") < said.index("1 difference(s) fail the run; the 1 declared above do not")

    @pytest.mark.parametrize("name", _ORACLES)
    def test_a_receipt_carried_to_another_host_is_a_baseline_and_its_own_host_refuses_it(
            self, bench, name, monkeypatch, tmp_path):
        """Round trip: what one host writes names it, its oracle, its tree and
        its guard; the same file read back on the host that wrote it is
        refused (the self-diff a default --out invites), and read on another
        at one tree with one set of verdicts it shows no difference."""
        mod = bench(name)
        rows = [{"id": "a", "shape": s, "actual": "HARD"} for s in ("plain", "spaced")]
        _stub_run(mod, monkeypatch, rows)
        produced = tmp_path / "rehearsal-results.json"
        assert mod.main(["--repo-root", str(_REPO_ROOT), "--out", str(produced)]) == 0
        receipt = json.loads(produced.read_text(encoding="utf-8"))
        assert {k: receipt[k] for k in ("oracle", "host", "tree_sha", "guard_digest", "rows_digest")} == {
            "oracle": name, "host": platform.node(), "tree_sha": "93df04f1", "guard_digest": "g1",
            "rows_digest": "r1"}
        out = tmp_path / "here.json"
        assert mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(produced), "--out", str(out)]) == 5
        assert mod.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(_carried(produced)),
                         "--out", str(out)]) == 0
        assert json.loads(out.read_text(encoding="utf-8"))["baseline"]["differences"] == []

    def test_one_oracles_receipt_is_not_the_others_baseline(self, bench, monkeypatch, tmp_path):
        probe = bench(_PROBE)
        ran = _stub_run(probe, monkeypatch, [])
        baseline = tmp_path / "rehearsal-results.json"
        baseline.write_text(json.dumps(_receipt(oracle=_REHEARSAL)), encoding="utf-8")
        rc = probe.main(["--repo-root", str(_REPO_ROOT), "--baseline", str(baseline),
                         "--out", str(tmp_path / "here.json")])
        assert rc == 5 and ran == []

    def test_the_rehearsals_default_receipt_is_the_gitignored_one(self, bench):
        rehearsal = bench(_REHEARSAL)
        assert rehearsal.DEFAULT_OUT == _BENCH_DIR / "rehearsal-results.json"

    def test_the_probes_one_command_takes_no_baseline(self, bench, monkeypatch, tmp_path, capsys):
        probe = bench(_PROBE)
        _stub_run(probe, monkeypatch, [])
        monkeypatch.setattr(probe, "_tier", lambda *a: pytest.fail("ran the command"))
        rc = probe.main(["--repo-root", str(_REPO_ROOT), "--command", "ls",
                         "--baseline", str(tmp_path / "rehearsal-results.json")])
        assert rc == 2 and "--baseline" in capsys.readouterr().err
