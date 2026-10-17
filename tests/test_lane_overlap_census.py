# pytest-marker: default-unit -- in-process and spawn-free: the script is loaded, never run
"""`scripts/lane_overlap_census.py`, the symbol-overlap pack's Task 0 oracle:
what the census keeps of its own -- its spawns, the window listing and the
mirror registry's full fold of the twins -- and that it keeps no copy of the
mapper. The mapper and the pair verdict live in `tools/cc/_symbols.py` since
Wave 1, with their cases in `tests/test_symbols.py`. This file pins what is
left here because a copy of the mapper beside the module is two homes for one
rule, which drift apart the moment one is edited, and a census that spawns from
the wrong directory reads every diff empty. Each test names, in its docstring,
the mutation it dies to."""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "lane_overlap_census.py"
_MODULE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "cc" / "_symbols.py"


def _load():
    spec = importlib.util.spec_from_file_location("lane_overlap_census", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_CENSUS = _load()


@pytest.fixture(scope="module")
def census():
    return _CENSUS


class TestTheCensusKeepsNoCopy:
    def test_the_mapper_is_the_module_s_and_no_definition_of_it_is_here(self, census):
        """Dies to: a copy of the mapper kept in the script beside the module (two homes for one
        rule, which part the moment one of them is edited)."""
        assert pathlib.Path(census._symbols.__file__).resolve() == _MODULE.resolve()
        defined = {n.name for n in ast.walk(ast.parse(_SCRIPT.read_text(encoding="utf-8")))
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        moved = {"spans", "innermost", "innermost_spans", "enclosing", "placed", "symbols_meet",
                 "changed_symbols", "concurrent", "pair_verdict", "_target_names", "_lines", "_indent"}
        assert not (defined & moved), sorted(defined & moved)

    def test_the_census_reads_through_the_module_at_the_repo_root(self, census, monkeypatch):
        """Dies to: the root dropped from the call (a `git diff -- path` from a subdirectory reads
        the pathspec relative to it, and every diff comes back empty), or the registry fold not
        handed over (a twin lands on a key of its own)."""
        seen = []

        def fake(base, head, **kw):
            seen.append((base, head, kw))
            return {}

        monkeypatch.setattr(census._symbols, "symbols_between", fake)
        census.symbols_between("b", "h")
        assert seen == [("b", "h", {"root": census.REPO_ROOT, "fold": census.canonical})]


class TestSpawns:
    def test_every_spawn_runs_at_the_repo_root_with_the_binary_first(self, census, monkeypatch):
        """Dies to: `cwd` dropped (a `git diff -- path` from a subdirectory reads the pathspec
        relative to it, every diff comes back empty and every file is certified), or the binary
        built into the argv at the call site, which the subprocess-contract scanner cannot read."""
        calls = []

        class Done:
            stdout = ""

        def fake(argv, **kw):
            calls.append((argv, kw))
            return Done()

        monkeypatch.setattr(census, "run_bounded", fake)
        census._git("status")
        census._gh("pr", "list")
        assert [c[0] for c in calls] == [["git", "status"], ["gh", "pr", "list"]]
        assert all(c[1]["cwd"] == census.REPO_ROOT for c in calls), calls
        assert all(c[1]["encoding"] == "utf-8" for c in calls), calls


class TestWindowLimit:
    def test_the_listing_reads_from_the_newest_number_down_to_the_window_s_floor(self, census):
        """Dies to: a fixed limit counted from the window's size (a pinned window truncates as
        merges accumulate above it, and the oldest numbers vanish with `unread: 0`)."""
        assert census.window_limit(276, 246) == 31
        assert census.window_limit(400, 180) == 221
        assert census.window_limit(5, 10) == 1
        assert census.window_limit(5000, 1) == 1000


class TestCanonical:
    def test_a_vendored_hook_folds_onto_its_source(self, census):
        """Dies to: the twin left apart (one lane meets another twice)."""
        if census._mirrors is None:
            pytest.skip("the mirror registry is not importable here")
        assert census.canonical("espalier/_vendor/cc/hooks/write_guard.py") == "tools/cc/hooks/write_guard.py"
        assert census.canonical("tools/cc/hooks/write_guard.py") == "tools/cc/hooks/write_guard.py"
        assert census.canonical("docs/HOOKS.md") == "docs/HOOKS.md"


class TestCanonicalFolding:
    def test_a_twin_of_a_region_host_folds_onto_the_region_s_source(self, census):
        """Dies to: one-hop folding (a region row's byte twins fold onto the region's host file,
        which itself folds onto the region's source, so one synced lane lands on two keys)."""
        if census._mirrors is None:
            pytest.skip("the mirror registry is not importable here")
        rows = census._mirrors.MIRROR_ROWS

        def base_dir(sot):
            glob = census._mirrors.glob_row_parts(sot)
            return glob[0] if glob is not None else sot

        hosts = [m for row in rows for m in row.mirrors if not m.endswith("/")]
        dirs = [(m, base_dir(row.sot)) for row in rows for m in row.mirrors if m.endswith("/")]
        pairs = [(d + host[len(sot):], host) for host in hosts for d, sot in dirs if host.startswith(sot)]
        if not pairs:
            pytest.skip("no region host under a mirrored directory in this registry")
        for twin, host in pairs:
            assert census.canonical(twin) == census.canonical(host), (twin, host)
            assert census.canonical(census.canonical(twin)) == census.canonical(twin), twin


class TestTheSummary:
    def test_the_beside_insertions_are_summed_and_printed_apart_from_the_unplaced_share(
            self, census, monkeypatch, capsys):
        """Dies to: the beside count dropped from the sum or from the printed line (an insertion
        naming no point declines its pair outside 0-C's share, and the census would hide how many
        did)."""
        listed = [{"number": n, "createdAt": "2026-10-01T00:00:00Z", "mergedAt": f"2026-10-0{n + 1}T00:00:00Z",
                   "headRefOid": f"h{n}", "mergeCommit": {"oid": f"m{n}"}} for n in (1, 2)]
        place = {"h1": {"a.py": {"kind": "python", "symbols": {"a.py::<module>"}, "changed": 4, "unplaced": 1,
                                 "beside": 2}},
                 "h2": {"b.py": {"kind": "python", "symbols": {"b.py::f"}, "changed": 3, "unplaced": 0,
                                 "beside": 1}}}
        monkeypatch.setattr(census, "_gh", lambda *argv: json.dumps(listed))
        monkeypatch.setattr(census, "_git", lambda *argv: "base\n" if argv[0] == "merge-base" else "")
        monkeypatch.setattr(census, "symbols_between", lambda base, head: place[head])
        result = census.census(prs=2)
        assert (result["beside_insertions"], result["unplaced_lines"], result["changed_lines"]) == (3, 1, 7)
        assert census.main(["--prs", "2"]) == 0
        out = capsys.readouterr().out
        assert "unplaced Python lines 1 of 7 (14.3%)" in out, out
        assert "(beside, apart from that share): 3 hunks, the only decline of 0 shared file(s)" in out, out

    def test_a_file_declined_by_beside_alone_is_counted_and_a_mark_is_said_in_words(
            self, census, monkeypatch, capsys):
        """Dies to: the files beside alone declines left uncounted (the hunk count reads as that
        many declines, though it may be none), or a pair's shared mark printed raw, not in the
        renderer's words (the reviews of Wave 2's last delta, driven)."""
        listed = [{"number": n, "createdAt": "2026-10-01T00:00:00Z", "mergedAt": f"2026-10-0{n + 1}T00:00:00Z",
                   "headRefOid": f"h{n}", "mergeCommit": {"oid": f"m{n}"}} for n in (1, 2)]
        place = {"h1": {"a.py": {"kind": "python", "symbols": {"a.py::f", "a.py::<after:f>"}, "changed": 2,
                                 "unplaced": 0, "beside": 0},
                        "b.py": {"kind": "python", "symbols": {"b.py::<module>"}, "changed": 1, "unplaced": 0,
                                 "beside": 1}},
                 "h2": {"a.py": {"kind": "python", "symbols": {"a.py::g", "a.py::<after:f>"}, "changed": 1,
                                 "unplaced": 0, "beside": 0},
                        "b.py": {"kind": "python", "symbols": {"b.py::h"}, "changed": 1, "unplaced": 0,
                                 "beside": 0}}}
        monkeypatch.setattr(census, "_gh", lambda *argv: json.dumps(listed))
        monkeypatch.setattr(census, "_git", lambda *argv: "base\n" if argv[0] == "merge-base" else "")
        monkeypatch.setattr(census, "symbols_between", lambda base, head: place[head])
        assert census.census(prs=2)["beside_only_files"] == 1
        assert census.main(["--prs", "2"]) == 0
        out = capsys.readouterr().out
        assert "1 hunks, the only decline of 1 shared file(s)" in out, out
        assert "shared symbol (the blank lines after a.py::f)" in out, out
