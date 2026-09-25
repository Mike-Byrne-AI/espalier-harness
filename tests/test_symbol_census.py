"""Contract tests for ``scripts/symbol_census.py``.

These pin the property the 2026-09-05 rename lost, because a census piped
through `head` hid five sibling sites and cost four fix-and-rerun rounds: a
census is complete or it is not a census. Each test guards one way the tool
could drift back into that failure -- a hit elided, a record surface confused
with work, a mirror offered as an edit target instead of named with its sync,
or an exit code that says "swept" while live mentions remain.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "symbol_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("symbol_census", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sc():
    return _load()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A scratch tree shaped like this repo's surfaces, with the engine's mirror
    registry importable from it so mirror classification is DERIVED here too."""
    r = tmp_path / "repo"
    (r / "espalier").mkdir(parents=True)
    (r / "espalier" / "__init__.py").write_text("", encoding="utf-8")
    (r / "espalier" / "mirror_registry.py").write_text(
        (REPO_ROOT / "espalier" / "mirror_registry.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (r / "espalier" / "cli.py").write_text(
        "def _deploy_file():\n    pass\n\nx = cli._deploy_file\ny = _deploy_files\n",
        encoding="utf-8",
    )
    (r / "espalier" / "_vendor" / "cc").mkdir(parents=True)
    (r / "espalier" / "_vendor" / "cc" / "w.py").write_text("_deploy_file\n", encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "test_many.py").write_text(
        "".join(f"call_{i} = _deploy_file  # {i}\n" for i in range(60)), encoding="utf-8",
    )
    (r / "docs").mkdir()
    (r / "docs" / "session-archive.md").write_text("- `_deploy_file` did X\n", encoding="utf-8")
    (r / "docs" / "GUIDE.md").write_text("see `_deploy_file`\n", encoding="utf-8")
    (r / "CHANGELOG.md").write_text("- `_deploy_file` gone\n", encoding="utf-8")
    (r / "memory").mkdir()
    (r / "memory" / "note.md").write_text("nothing here\n", encoding="utf-8")
    (r / "binary.bin").write_bytes(b"\xff\xfe_deploy_file\x00")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    # gitignored working state that still names symbols
    (r / "task-packs").mkdir()
    (r / "task-packs" / "LEDGER_PROBES.json").write_text('{"cmd": "c._deploy_file"}\n', encoding="utf-8")
    (r / "task-packs" / "FORWARD_LEDGER.md").write_text(
        "| `DEF-1` | cli.py::_deploy_file | live row | minor |\n"
        "| ~~`DEF-2`~~ | x | CLOSED PRIOR TEXT: _deploy_file | nit |\n", encoding="utf-8",
    )
    (r / ".gitignore").write_text("task-packs/\n", encoding="utf-8")
    return r


class TestTheCensusIsComplete:
    def test_every_hit_is_listed_never_truncated(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        many = [h for h in res["hits"] if h["path"] == "tests/test_many.py"]
        assert len(many) == 60
        assert [h["line"] for h in many] == list(range(1, 61))
        text = sc.render(res, include_records=False)
        assert "tests/test_many.py  (60)" in text
        assert "60: call_59" in text, "the last hit must be printed, not elided"

    def test_a_dotted_prefix_counts_and_a_longer_identifier_does_not(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        cli = [h for h in res["hits"] if h["path"] == "espalier/cli.py"]
        assert {h["line"] for h in cli} == {1, 4}, cli   # def + cli._deploy_file; not _deploy_files

    def test_untracked_working_state_is_in_the_population(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        assert any(h["path"] == "task-packs/LEDGER_PROBES.json" for h in res["hits"])

    def test_a_live_ledger_row_is_work_and_a_struck_one_is_a_record(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        rows = {h["line"]: h["kind"] for h in res["hits"] if h["path"].endswith("FORWARD_LEDGER.md")}
        assert rows == {1: "live", 2: "record"}

    def test_binary_files_are_skipped(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        assert not any(h["path"] == "binary.bin" for h in res["hits"])


class TestClassification:
    def test_a_mirror_is_named_with_its_sync_not_offered_as_work(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        vendor = [h for h in res["hits"] if h["path"].startswith("espalier/_vendor/")]
        assert vendor and all(h["kind"] == "mirror" for h in vendor)
        assert "sync_vendor_cc" in vendor[0]["detail"]
        text = sc.render(res, include_records=False)
        assert "[mirror -- edit the SoT, then: vendor-cc" in text

    def test_records_are_counted_not_listed_unless_asked(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        assert res["record"] == 3   # session-archive + CHANGELOG + the struck ledger row
        hidden = sc.render(res, include_records=False)
        shown = sc.render(hidden and res, include_records=True)
        assert "docs/session-archive.md" not in hidden and "records not listed" in hidden
        assert "docs/session-archive.md" in shown and "CHANGELOG.md" in shown

    def test_quiet_surfaces_are_named(self, sc, repo):
        res = sc.census(repo, ["_deploy_file"])
        assert "memory" in res["groups_without_live_hits"]
        assert "tests" not in res["groups_without_live_hits"]


class TestTheRecordSetAndTheRegionRows:
    def test_the_record_set_covers_the_declared_canon(self, sc):
        from tests.test_doc_source_citations import _RECORD_SURFACE_DOCS
        assert _RECORD_SURFACE_DOCS <= set(sc._RECORD_SURFACES)
        assert "ESPALIER_MEMORY.md" in sc._RECORD_SURFACES

    def test_a_region_only_mirror_row_is_live_outside_its_region(self, sc, repo):
        """`implement-pack.md` is mirrored only inside a generated region; its
        ordinary prose is work. Derived from the registry: the row is found by
        its shape (a file path, subset+transform), never by name."""
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from espalier import mirror_registry
        finally:
            sys.path.pop(0)
        rows = [r for r in mirror_registry.MIRROR_ROWS
                if any(not m.endswith("/") for m in r.mirrors) and "transform" in str(r.kind)]
        assert rows, "no region-only mirror row in the registry -- this test's premise is gone"
        rel = rows[0].mirrors[0]
        assert sc.classify(rel, mirror_registry.MIRROR_ROWS)[0] == "live"
        # a whole-tree row is still a mirror
        tree_row = next(r for r in mirror_registry.MIRROR_ROWS if r.mirrors[0].endswith("/"))
        assert sc.classify(tree_row.mirrors[0] + "x.py", mirror_registry.MIRROR_ROWS)[0] == "mirror"


class TestTheExitCodeIsTheSweepAnswer:
    def test_live_mentions_exit_one_and_none_exit_zero(self, sc, repo, capsys):
        assert sc.main(["_deploy_file", "--root", str(repo)]) == 1
        capsys.readouterr()
        assert sc.main(["no_such_symbol_anywhere", "--root", str(repo)]) == 0

    def test_json_carries_the_same_census(self, sc, repo, capsys):
        sc.main(["_deploy_file", "--root", str(repo), "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["live"] >= 60 and data["record"] == 3 and data["mirror"] == 1


class TestOnThisTree:
    def test_a_name_removed_this_week_has_no_live_mentions_left(self, sc):
        """The rename this script was written after: `_deploy_file` left `cli`
        on 2026-09-05. Its only remaining mentions are records and the
        deliberate history notes in docstrings, which are live-surface text
        and therefore MUST appear here -- this pins that the census sees them
        (a census that hid a docstring would hide the next roster)."""
        res = sc.census(REPO_ROOT, ["_deploy_file"])
        live_paths = {h["path"] for h in res["hits"] if h["kind"] == "live"}
        assert "espalier/cli.py" in live_paths        # the history note in _write_seed's docstring
        assert not any(p.startswith("espalier/_vendor/") and h["kind"] == "live"
                       for h in res["hits"] for p in [h["path"]])
