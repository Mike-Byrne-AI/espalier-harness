"""Contract tests for ``tools/cc/ledger_row.py`` on a fixture ledger.

The ledger had no git undo until 2026-09-21 (it was gitignored), and a wrong
strike still deletes live work; these tests exist because the helper rewrites that file. They pin that
a strike keeps PRIOR TEXT, strikes the index row, retires the probe and leaves
the regions converged; that a filing drives its probe FIRST and writes nothing
when the probe does not print the open value; that the recorded row_sha is
the one ``check_ledger_probes`` recomputes; that a row shape the splitter
cannot round-trip is refused rather than mangled; and that a refused write
touches neither file; that a probe file whose ``_count`` disagrees with its
rows is refused by name unless ``--reconcile-count`` says the hand edit was
seen; that ``repin`` drives the probe first, rewrites only what it was
asked to, and stamps the sha the checker recomputes; and that a missing probe
file is created for a ledger with no live row and refused beside live rows.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_generate_ledger_regions import _ledger

# slow-exempt: one test drives the verb as a child process under a cp1252
# stdout (measured 0.2s) -- the failure is the real stream, so only the real
# CLI can show it.

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "cc" / "ledger_row.py"


def _load():
    spec = importlib.util.spec_from_file_location("ledger_row", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lr():
    return _load()


@pytest.fixture
def tree(tmp_path):
    return _build_tree(tmp_path)


def _build_tree(tmp_path: Path) -> dict:
    packs = tmp_path / "task-packs"
    packs.mkdir()
    ledger = packs / "FORWARD_LEDGER.md"
    ledger.write_text(_ledger(), encoding="utf-8")
    probes = packs / "LEDGER_PROBES.json"
    probes.write_text(json.dumps({
        "_count": 2,
        "probes": [
            {"id": "DEF-1", "subject": "site", "cmd": "echo a", "open_value": "a", "why_not": None, "row_sha": "x"},
            {"id": "DEF-2", "subject": "site", "cmd": "echo b", "open_value": "b", "why_not": None, "row_sha": "y"},
        ],
    }, indent=1) + "\n", encoding="utf-8")
    closing = tmp_path / "closing.md"
    closing.write_text("landed in abc123 after one pass\nof each red team", encoding="utf-8")
    body = tmp_path / "body.md"
    body.write_text("**A new defect.** Who: an adopter.", encoding="utf-8")
    return {"ledger": ledger, "probes": probes, "closing": closing, "body": body}


def _args(tree, *rest):
    return ["--ledger", str(tree["ledger"]), "--probes", str(tree["probes"]),
            "--date", "2026-09-06", *rest]


def _derived(lr, text: str) -> tuple[int, int, list]:
    """``(live total, §C1's member rows, stored totals)``. Derived: the ledger
    stores no total, so a verb's work is read from its rows, and the third
    item is empty on every ledger a verb leaves."""
    gen = lr._load("generate_ledger_regions")
    d = gen.derive(text)
    return d["live_total"], d["sections"].get("§C1", 0), gen.stored_counts(text)


def _tally(lr, text: str) -> dict[str, int]:
    """Every live population and audience figure, derived, in one dict (the
    two vocabularies are disjoint)."""
    d = lr._load("generate_ledger_regions").derive(text)
    return {**d["population_live"], **d["audience_live"]}


class TestStrike:
    def test_strike_keeps_prior_text_strikes_the_index_and_retires_the_probe(self, lr, tree):
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert ("| ~~`DEF-1`~~ | site | ✅ **CLOSED 2026-09-06 — landed in abc123 after one pass "
                "of each red team** PRIOR TEXT: what | major |") in text
        assert "| ~~`DEF-1`~~ | §C1 | site |" in text
        assert _derived(lr, text) == (1, 2, [])
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["DEF-2"] and data["_count"] == 1
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_struck_or_unknown_row_is_refused(self, lr, tree, capsys):
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "no unstruck member row" in capsys.readouterr().err
        assert lr.main(_args(tree, "strike", "DEF-9", "--text-file", str(tree["closing"]))) == 2

    def test_an_escaped_pipe_round_trips_and_an_unescaped_one_is_refused(self, lr, tree, capsys):
        """The real ledger escapes a literal pipe as `\\|`; one row does not, and
        one table has three cells. The first cut's split moved 1,194 characters
        of a real row into its severity column and raised on 28 others."""
        rows = (
            "| `DEF-1` | site | what with `a \\| b` inside | major |",
            "| `DEF-2` | site | what | unescaped | minor |",
        )
        tree["ledger"].write_text(_ledger(c1_rows=rows), encoding="utf-8")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-2", "--text-file", str(tree["closing"]))) == 2
        assert "5 cells, not 4" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "PRIOR TEXT: what with `a \\| b` inside | major |" in text

    def test_a_three_cell_row_from_another_table_is_refused(self, lr, tree, capsys):
        tree["ledger"].write_text(_ledger(c1_rows=("| `DEF-1` | decision text | open |",
                                                   "| `DEF-2` | site | what | minor |")), encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "3 cells, not 4" in capsys.readouterr().err

    def test_a_refused_strike_writes_neither_file(self, lr, tree, monkeypatch, capsys):
        """Atomicity: the first cut retired the probe before checking
        convergence, leaving an open row with no probe when the strike was
        refused (failure-mode pass, driven)."""
        monkeypatch.setattr(lr, "_converge", lambda gen, text, probes_path: (text, [{"region": "x", "detail": "forced"}]))
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "nothing written" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        assert not list(tree["probes"].parent.glob("*.pending"))

    def test_dry_run_writes_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert "PRIOR TEXT: what" in capsys.readouterr().out
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before


    def test_a_drifted_count_is_refused_by_name_unless_reconciled(self, lr, tree, capsys):
        """A ``_count`` that disagrees with the roster is a hand edit's only
        trace, and ``check_ledger_probes`` refuses every report on it. The
        sanctioned writer must not repair that trace silently: it names both
        numbers and writes nothing, and re-derives the count only under
        ``--reconcile-count`` (failure-mode pass, 2026-09-08 -- the first cut
        repaired it silently and two tests pinned the silence)."""
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["_count"] = 99
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        err = capsys.readouterr().err
        assert "_count=99" in err and "carries 2" in err and "--reconcile-count" in err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        assert lr.main(_args(tree, "--reconcile-count", "strike", "DEF-1",
                             "--text-file", str(tree["closing"]))) == 0
        after = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert after["_count"] == len(after["probes"]) == 1

class TestADeferralIntoTheStruckRow:
    """DEF-412a: a strike reads the in-flight packs' ``## Scope (out)`` first.

    Origin: TP-371 landed one member of the old §2.3 and parked its ~47 sibling
    read sites in its own Scope (out) as "a §2.3 remainder"; nothing mechanical
    read that sentence, so the landed-so-strike-it convention could take the
    section, remainder and all, with no git undo on a then-gitignored ledger.
    The population is the two shipped locations -- the ``task-packs/`` root and
    ``Deferred/`` -- and never ``Done/``: a landed pack's citation is history,
    not a deferral. Every row here runs on the fixture ledger under tmp_path;
    the live tree is never read.
    """

    @staticmethod
    def _pack(tree, rel: str, scope_out: str, before: str = "") -> Path:
        path = tree["ledger"].parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# TP stub\n\n## Status\n- State: DRAFT\n{before}\n## Scope (out)\n{scope_out}\n"
            "## Implementation\n\nunrelated\n", encoding="utf-8")
        return path

    def test_a_root_pack_deferring_into_the_row_refuses_and_writes_nothing(self, lr, tree, capsys):
        self._pack(tree, "TP-9-x.md", "- the rest waits on `DEF-1` (deferred)\n")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        err = capsys.readouterr().err
        assert "TP-9-x.md" in err and "DEF-1" in err and "--despite-deferrals" in err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        # the dry run reports the same refusal rather than a row it would never write
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2

    def test_despite_deferrals_strikes_under_an_advisory(self, lr, tree, capsys):
        self._pack(tree, "TP-9-x.md", "- the rest waits on `DEF-1` (deferred)\n")
        assert lr.main(_args(tree, "strike", "DEF-1", "--despite-deferrals",
                             "--text-file", str(tree["closing"]))) == 0
        err = capsys.readouterr().err
        assert "TP-9-x.md" in err and "despite" in err
        assert "| ~~`DEF-1`~~ |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_deferred_pack_is_population_and_a_done_pack_is_not(self, lr, tree, capsys):
        self._pack(tree, "Done/TP-8-landed.md", "- `DEF-1` stays open (deferred)\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        self._pack(tree, "Deferred/TP-7-parked.md", "- `DEF-1` stays open (deferred)\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "Deferred/TP-7-parked.md" in capsys.readouterr().err

    def test_a_citation_outside_scope_out_is_ownership_not_deferral(self, lr, tree):
        # A roadmap lists the rows its lanes will strike in its Reach and
        # Implementation; reading the whole pack would refuse every strike that
        # roadmap exists to make. (TP-449 also PARKS twelve rows in its Scope
        # (out) for its own later tiers -- all pre-rebuild ids today, so inert --
        # and those ARE refused until the pack records the tier: the refusal
        # says so. Scope (out) only, and only there.)
        self._pack(tree, "TP-9-x.md", "- nothing deferred\n",
                   before="## Reach\n- `DEF-1` closed by lane 1\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_an_id_is_matched_whole(self, lr, tree):
        # `DEF-1a` is a different row; striking `DEF-1` must not read it as a deferral.
        self._pack(tree, "TP-9-x.md", "- `DEF-1a` deferred\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_a_section_number_in_scope_out_is_not_read(self, lr, tree):
        # Class numbers were reissued at the 2026-09-20 rebuild, so `§C1` in a
        # pack authored before it names the OLD §C1; the structural cut owns
        # section removal. The first cut refused the strike that emptied a cited
        # section and would have fired on a stale number (failure-mode pass).
        self._pack(tree, "TP-9-x.md", "- the remainder is a §C1 remainder\n")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-2", "--text-file", str(tree["closing"]))) == 0

    def test_a_bare_tail_inside_a_backticked_list_is_read_and_a_lone_number_is_not(self, lr, tree, capsys):
        # TP-452 parks eleven rows as "(`736, 424b, 516, PR-3, 6,\n  451`)"; the
        # first cut read one of them (both reviewers, 2026-09-21). The list may
        # cross a line break; a lone backticked number is a count, not a row.
        self._pack(tree, "TP-9-x.md", "- the demoted rows (`7, 1,\n  9`) hold\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        assert "[cites DEF-1]" in capsys.readouterr().err
        self._pack(tree, "TP-9-x.md", "- `1` row is left, and `x, 1` is prose\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_a_fenced_block_inside_scope_out_is_not_read(self, lr, tree):
        # A fenced shell snippet's `# comment` is not a heading and its `DEF-1`
        # is not a citation (code review, 2026-09-21; latent on the live packs).
        self._pack(tree, "TP-9-x.md", "```bash\n# note\necho DEF-1\n```\n- nothing deferred\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0

    def test_one_line_citing_both_ids_of_a_two_id_row_is_one_hit(self, lr, tree, capsys):
        tree["ledger"].write_text(_ledger(c1_rows=("| `DEF-1` `LG-9` | site | what | major |",
                                                   "| `DEF-2` | site | what | minor |")), encoding="utf-8")
        self._pack(tree, "TP-9-x.md", "- `DEF-1` and `LG-9` wait on the walk\n")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2
        err = capsys.readouterr().err
        assert "1 Scope (out) line(s)" in err and "[cites DEF-1, LG-9]" in err

    def test_strike_anchor_re_points_the_index_row_too(self, lr, tree):
        # DEF-648's strike re-pointed the member anchor and left the index row
        # citing three moved paths (code review, 2026-09-21).
        assert lr.main(_args(tree, "strike", "DEF-1", "--anchor", "new::home",
                             "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| ~~`DEF-1`~~ | new::home | ✅ **CLOSED 2026-09-06" in text
        assert "| ~~`DEF-1`~~ | §C1 | new::home |" in text


class TestFile:
    def _file(self, lr, tree, *extra, pre=(), probe_cmd="echo open=True", open_value="open=True"):
        return lr.main(_args(
            tree, "--root", str(tree["ledger"].parents[1]), *pre,
            "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", probe_cmd, "--open-value", open_value, "--subject", "body.md", *extra,
        ))

    def test_file_inserts_both_rows_adds_a_driven_probe_and_converges(self, lr, tree):
        assert self._file(lr, tree) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        member = "| `DEF-3` | new/site.py::fn | **A new defect.** Who: an adopter. | minor |"
        assert member in text and "| `DEF-3` | §C1 | new/site.py::fn |" in text
        assert text.index("| `DEF-2` | site") < text.index(member)
        assert _derived(lr, text) == (3, 3, [])
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        new = [p for p in data["probes"] if p["id"] == "DEF-3"][0]
        assert new["open_value"] == "open=True" and data["_count"] == 3
        # the sha check_ledger_probes recomputes: sha256 of the unstruck member line, first 12
        assert new["row_sha"] == hashlib.sha256(member.encode("utf-8")).hexdigest()[:12]
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_both_files_are_written_with_lf_on_every_platform(self, lr, tree):
        """Measured 2026-09-28 on Windows: one `repin` rewrote the live ledger
        (1,922 lines) and the probes file with CRLF, because both writers called
        `write_text` without `newline`, and git warned on the next touch. The
        tracked files are LF; a verb must not re-line them. On a POSIX host this
        passes with or without the fix -- the sentinel is the Windows cell."""
        assert self._file(lr, tree) == 0
        for key in ("ledger", "probes"):
            assert b"\r\n" not in tree[key].read_bytes(), key

    def test_a_probe_that_does_not_print_its_open_value_files_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert self._file(lr, tree, probe_cmd="echo open=False") == 2
        err = capsys.readouterr().err
        assert "does not print its open value 'open=True'" in err and "STRIKE_CANDIDATE" in err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before

    def test_a_duplicate_id_is_refused(self, lr, tree):
        assert self._file(lr, tree) == 0
        assert self._file(lr, tree) == 2

    def test_file_writes_the_declared_inputs_after_driving_them(self, lr, tree, capsys):
        """`DEF-858`: a probe may read a path its subject does not name. The
        filing drives the probe through the runner's own inputs gate, so a
        declared path absent on this tree refuses it (nothing written) -- the
        same UNRESOLVED the recurring check would report there."""
        root = tree["ledger"].parents[1]
        before = tree["probes"].read_text(encoding="utf-8")
        assert self._file(lr, tree, "--inputs", "records/Done") == 2
        assert "input missing: records/Done" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before
        (root / "records" / "Done").mkdir(parents=True)
        (root / "records" / "Done" / "TP-1-x.md").write_text("", encoding="utf-8")  # a bare dir is "input empty"
        assert self._file(lr, tree, "--inputs", "records/Done") == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        by_id = {p["id"]: p for p in data["probes"]}
        assert by_id["DEF-3"]["inputs"] == ["records/Done"]
        # a row filed without the flag carries no key at all: the shape of every
        # existing entry is unchanged
        assert "inputs" not in by_id["DEF-1"]

    def test_file_refuses_inputs_on_a_row_declared_why_not(self, lr, tree, capsys):
        # `run_probe` returns NO_ORACLE before the inputs gate on a no-command
        # row, so the declaration would be written undriven (both reviewers,
        # 2026-09-22); `repin` refuses the same shape by name.
        before = tree["probes"].read_text(encoding="utf-8")
        with pytest.raises(SystemExit):
            lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]),
                          "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
                          "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]),
                          "--severity", "minor", "--subject", "body.md",
                          "--why-not", "no local oracle", "--inputs", "site"))
        assert "--inputs cannot be driven" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before

    def test_the_probe_runs_from_root_with_the_checkers_timeout(self, lr, tree, tmp_path):
        """A probe accepted at filing must be one the recurring checker can run:
        same cwd (the repo root), same timeout (read from check_ledger_probes)."""
        marker = tmp_path / "root-marker.txt"
        marker.write_text("open=True", encoding="utf-8")
        rc = lr.main(_args(
            tree, "--root", str(tmp_path), "file", "DEF-5", "--section", "C1", "--after", "DEF-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
            "--probe-cmd", "cat root-marker.txt", "--open-value", "open=True",
            "--subject", "root-marker.txt",
        ))
        assert rc == 0
        # a subject that does not exist under --root is UNRESOLVED to the
        # checker, and therefore refused here too -- the same verdict, by
        # construction, not by a second implementation
        rc = lr.main(_args(
            tree, "--root", str(tmp_path), "file", "DEF-6", "--section", "C1", "--after", "DEF-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
            "--probe-cmd", "cat root-marker.txt", "--open-value", "open=True",
            "--subject", "no/such/file.py",
        ))
        assert rc == 2

    def test_why_not_files_without_a_probe_command(self, lr, tree):
        rc = lr.main(_args(
            tree, "file", "DEF-4", "--section", "C1", "--after", "DEF-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
            "--subject", "a", "--why-not", "no local oracle: needs the GitHub console",
        ))
        assert rc == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        new = [p for p in data["probes"] if p["id"] == "DEF-4"][0]
        assert new["cmd"] is None and new["why_not"].startswith("no local oracle")

    def test_a_drifted_count_is_refused_on_file_unless_reconciled(self, lr, tree, capsys):
        """The filing twin: a wrong ``_count`` is named and refused, then
        re-derived under the flag."""
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["_count"] = 0
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert self._file(lr, tree) == 2
        assert "_count=0" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before
        assert self._file(lr, tree, pre=("--reconcile-count",)) == 0
        after = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert after["_count"] == len(after["probes"]) == 3


class TestMissingProbesFileIsCreated:
    """A ledger nobody has filed into yet has no probes file, and every verb
    crashed on it with a ``FileNotFoundError`` (measured 2026-09-30 on an empty
    skeleton). The file is created -- but only for a ledger with no live row.
    Every row a verb files gets a roster entry, so a live row with no file
    means the roster was LOST, and starting an empty one would hide every
    entry it held."""

    _STRUCK = ("| ~~`DEF-1`~~ | site | ✅ **CLOSED 2026-09-01 — landed** PRIOR TEXT: what | major |",
               "| ~~`DEF-2`~~ | site | ✅ **CLOSED 2026-09-01 — landed** PRIOR TEXT: what | minor |")
    _STRUCK_INDEX = ("| ~~`DEF-1`~~ | §C1 | site |", "| ~~`DEF-2`~~ | §C1 | site |")

    def _why_not(self, tree, rid="DEF-3"):
        return _args(tree, "file", rid, "--section", "C1", "--after", "DEF-2",
                     "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "nit",
                     "--subject", "a", "--why-not", "no local oracle")

    def test_filing_into_a_ledger_with_no_live_row_creates_the_probes_file(self, lr, tree):
        tree["ledger"].write_text(_ledger(c1_rows=self._STRUCK, appendix=self._STRUCK_INDEX),
                                  encoding="utf-8")
        tree["probes"].unlink()
        assert lr.main(self._why_not(tree)) == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["DEF-3"]
        assert data["_count"] == 1
        assert b"\r\n" not in tree["probes"].read_bytes()
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(tree["ledger"].read_text(encoding="utf-8")) == []

    def test_a_dry_run_creates_nothing(self, lr, tree):
        tree["ledger"].write_text(_ledger(c1_rows=self._STRUCK, appendix=self._STRUCK_INDEX),
                                  encoding="utf-8")
        tree["probes"].unlink()
        assert lr.main(_args(tree, "--dry-run", *self._why_not(tree)[6:])) == 0
        assert not tree["probes"].exists()

    def test_a_missing_file_beside_live_rows_is_refused_by_every_verb(self, lr, tree, capsys):
        tree["probes"].unlink()
        before = tree["ledger"].read_text(encoding="utf-8")
        verbs = (
            self._why_not(tree),
            _args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])),
            _args(tree, "repin", "DEF-1", "--reason", "moved", "--severity", "nit"),
        )
        for argv in verbs:
            assert lr.main(argv) == 2, argv[6]
            err = capsys.readouterr().err
            assert "2 live row(s)" in err and "LEDGER_PROBES.json" in err, err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert not tree["probes"].exists()


#: A ledger nobody has filed into: the counts pointer, the section-2 heading
#: and its vocabulary tables, an empty class index and an empty Appendix B --
#: no class section yet. The shape Task 0 of the adopter port drove on
#: 2026-09-30, where no verb could add the first class or its first row.
_SKELETON = """# Forward Ledger

**Counts are derived, never stored here:** run the generator with --print.

## §2 — Open fixes, by unit of work

| population | what it means |
|---|---|
| LOGIC_BUG | code behaves wrongly |
| HYGIENE | docs |
| OPERATOR_ACTION | no code fix exists |

| audience |
|---|
| **ADOPTER** — a person who uses what this repository ships |
| MAINTAINER |
| OPERATOR |

### Class index

| § | class | population | audience | effort |
|---|---|---|---|---|

## Appendix B — id index

| id | § | site |
|---|---|---|
"""
#: The same skeleton as a ledger seeded before 2026-10-09 carries it, every
#: total stored: an adopter's file the first verb run after an upgrade meets.
_SKELETON_WITH_TOTALS = """# Forward Ledger

**Live: 0** — 0 logic bugs · 0 hygiene · 0 operator actions.
**0** reach an adopter.

## §2 — Open fixes, by unit of work (0 LIVE issues in 0 classes + 0 standalone)

| population | live | what it means |
|---|---|---|
| LOGIC_BUG | 0 | code behaves wrongly |
| HYGIENE | 0 | docs |
| OPERATOR_ACTION | 0 | no code fix exists |

| audience | live |
|---|---|
| **ADOPTER** — a person who uses what this repository ships | **0** |
| MAINTAINER | 0 |
| OPERATOR | 0 |

### Class index

| § | class | members | population | audience | effort |
|---|---|---|---|---|---|

## Appendix B — id index

| id | § | site |
|---|---|---|
"""


class TestClassVerb:
    def _class(self, lr, tree, *rest):
        return lr.main(_args(tree, "class", *rest))

    def test_class_opens_an_index_row_and_an_empty_section_that_converge(self, lr, tree):
        from tests._md_anchors import heading_anchors

        assert self._class(lr, tree, "C7", "--title", "Make X do Y",
                           "--population", "HYGIENE", "--audience", "MAINTAINER") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "### §C7 — Make X do Y" in text
        index = [ln for ln in text.splitlines() if ln.startswith("| [§C7]")]
        assert index == ["| [§C7](#c7--make-x-do-y) | Make X do Y | HYGIENE | MAINTAINER | — |"]
        assert "c7--make-x-do-y" in heading_anchors(text)
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.ledger_sections(text)["§C7"] == []
        assert gen.find_drift(text) == []

    def test_a_mixed_class_gets_the_two_tag_columns(self, lr, tree):
        assert self._class(lr, tree, "C8", "--title", "Standalone",
                           "--population", "MIXED", "--audience", "MIXED") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        section = text.split("### §C8", 1)[1]
        assert "| id | site | what | sev | pop | aud |" in section

    @pytest.mark.parametrize("name,title,why", [
        ("C1", "Again", "already exists"),
        ("X7", "Bad name", "C<n>"),
        ("C9", "a | b", "no '|'"),
    ])
    def test_a_bad_class_is_refused_and_nothing_written(self, lr, tree, capsys, name, title, why):
        before = tree["ledger"].read_text(encoding="utf-8")
        assert self._class(lr, tree, name, "--title", title,
                           "--population", "HYGIENE", "--audience", "MAINTAINER") == 2
        assert why in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_dry_run_writes_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "class", "C7", "--title", "T",
                             "--population", "HYGIENE", "--audience", "MAINTAINER")) == 0
        assert "| [§C7](#c7--t) |" in capsys.readouterr().out
        assert tree["ledger"].read_text(encoding="utf-8") == before


class TestFileIntoAnEmptySection:
    def _first(self, lr, tree, section, *extra):
        return lr.main(_args(
            tree, "file", "DEF-3", "--section", section, "--anchor", "a",
            "--text-file", str(tree["body"]), "--severity", "nit", "--subject", "a",
            "--why-not", "no local oracle", *extra,
        ))

    def test_the_first_row_of_a_new_class_needs_no_after(self, lr, tree):
        assert lr.main(_args(tree, "class", "C7", "--title", "New", "--population", "HYGIENE",
                             "--audience", "MAINTAINER")) == 0
        assert self._first(lr, tree, "C7") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.ledger_sections(text)["§C7"] == ["| `DEF-3` | a | **A new defect.** Who: an adopter. | nit |"]
        assert text.rstrip().endswith("| `DEF-3` | §C7 | a |")
        assert gen.find_drift(text) == []

    def test_a_section_with_rows_still_needs_after(self, lr, tree, capsys):
        assert self._first(lr, tree, "C1") == 2
        assert "give --after" in capsys.readouterr().err

    def test_an_unknown_section_is_refused(self, lr, tree, capsys):
        assert self._first(lr, tree, "C9") == 2
        assert "no class section §C9" in capsys.readouterr().err

    def test_an_empty_ledger_round_trips_class_file_strike(self, lr, tmp_path, monkeypatch):
        """class -> first row (probe driven) -> strike, with the generator's own
        ``--check`` green after each verb and the probe file born on the first
        filing -- the whole lifecycle an adopter's first defect class needs."""
        packs = tmp_path / "task-packs"
        packs.mkdir()
        ledger, probes = packs / "FORWARD_LEDGER.md", packs / "LEDGER_PROBES.json"
        ledger.write_text(_SKELETON, encoding="utf-8")
        (tmp_path / "body.md").write_text("**First.** Who: the maintainer.", encoding="utf-8")
        (tmp_path / "close.md").write_text("fixed", encoding="utf-8")
        base = ["--root", str(tmp_path), "--ledger", str(ledger), "--probes", str(probes),
                "--date", "2026-09-30"]
        gen = lr._load("generate_ledger_regions")
        monkeypatch.setattr(gen, "_LEDGER", ledger)
        monkeypatch.setattr(gen, "_PROBES", probes)

        assert lr.main([*base, "class", "C1", "--title", "Initialise",
                        "--population", "OPERATOR_ACTION", "--audience", "MAINTAINER"]) == 0
        assert gen.main(["--check"]) == 0
        assert lr.main([*base, "file", "ONB-1", "--section", "C1", "--anchor", "cc/GOAL.md",
                        "--text-file", str(tmp_path / "body.md"), "--severity", "minor",
                        "--subject", "body.md", "--probe-cmd", "python -c \"print('open')\"",
                        "--open-value", "open"]) == 0
        assert gen.main(["--check"]) == 0
        assert _derived(lr, ledger.read_text(encoding="utf-8")) == (1, 1, [])
        assert [p["id"] for p in json.loads(probes.read_text(encoding="utf-8"))["probes"]] == ["ONB-1"]
        assert lr.main([*base, "strike", "ONB-1", "--text-file", str(tmp_path / "close.md")]) == 0
        assert gen.main(["--check"]) == 0
        text = ledger.read_text(encoding="utf-8")
        assert _derived(lr, text) == (0, 1, []) and "| ~~`ONB-1`~~ | §C1 | cc/GOAL.md |" in text
        assert json.loads(probes.read_text(encoding="utf-8"))["probes"] == []

    def test_the_first_verb_on_a_ledger_that_stores_totals_strips_them(self, lr, tmp_path):
        """An adopter's ledger seeded before the totals left: the class verb
        converges the whole file, so it comes out as a ledger seeded after --
        no total left for two lanes to rewrite -- with the new class in it."""
        out = {}
        for name, seed in (("new", _SKELETON), ("old", _SKELETON_WITH_TOTALS)):
            packs = tmp_path / name / "task-packs"
            packs.mkdir(parents=True)
            ledger = packs / "FORWARD_LEDGER.md"
            ledger.write_text(seed, encoding="utf-8", newline="\n")
            assert lr.main(["--root", str(tmp_path / name), "--ledger", str(ledger),
                            "--probes", str(packs / "LEDGER_PROBES.json"), "--date", "2026-10-09",
                            "class", "C1", "--title", "Initialise",
                            "--population", "HYGIENE", "--audience", "MAINTAINER"]) == 0
            out[name] = ledger.read_text(encoding="utf-8")
        old, new = out["old"].splitlines(), out["new"].splitlines()
        assert _derived(lr, out["old"])[2] == []
        assert old[2] == lr._load("generate_ledger_regions").COUNTS_POINTER  # the headline's place
        assert old[3:] == new[3:]


class TestTheVerbsTakeALock:
    """Two writing verbs at once lost a row and tore the ledger/roster pair
    (driven 2026-09-30 in the failure-mode review: shared fixed temp names,
    the ledger written before the roster). Every writing verb now holds an
    O_EXCL lock beside the ledger; a second one refuses and writes nothing."""

    def test_a_held_lock_refuses_every_writing_verb_and_writes_nothing(self, lr, tree, capsys):
        lock = tree["ledger"].with_name(tree["ledger"].name + ".lock")
        lock.write_text("pid 4242\n", encoding="utf-8")
        before = tree["ledger"].read_bytes(), tree["probes"].read_bytes()
        verbs = (
            _args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])),
            _args(tree, "class", "C7", "--title", "T", "--population", "HYGIENE",
                  "--audience", "MAINTAINER"),
            _args(tree, "file", "DEF-3", "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                  "--text-file", str(tree["body"]), "--severity", "nit", "--subject", "a",
                  "--why-not", "x"),
        )
        for argv in verbs:
            assert lr.main(argv) == 2, argv[6]
            err = capsys.readouterr().err
            assert "pid 4242" in err and "one at a time" in err, err
        assert (tree["ledger"].read_bytes(), tree["probes"].read_bytes()) == before
        assert lock.read_text(encoding="utf-8") == "pid 4242\n", "a refused verb removed the holder's lock"

    def test_a_verb_with_no_ledger_says_so_and_takes_no_lock(self, lr, tmp_path, capsys):
        """Deleting the ledger is how a repository stops keeping one; the lock's
        O_CREAT beside a missing task-packs/ raised FileNotFoundError before a
        word was said (both reviewers, 2026-09-30)."""
        body = tmp_path / "body.md"
        body.write_text("x", encoding="utf-8")
        rc = lr.main(["--root", str(tmp_path), "class", "C1", "--title", "T",
                      "--population", "HYGIENE", "--audience", "MAINTAINER"])
        assert rc == 2
        assert "no ledger at" in capsys.readouterr().err
        assert not (tmp_path / "task-packs").exists()

    def test_the_lock_is_released_after_a_verb_and_a_dry_run_takes_none(self, lr, tree):
        lock = tree["ledger"].with_name(tree["ledger"].name + ".lock")
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert not lock.exists()
        lock.write_text("pid 1\n", encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-2",
                             "--text-file", str(tree["closing"]))) == 0


class TestAPreviewSurvivesACp1252Console:
    def test_a_dry_run_strike_prints_on_a_cp1252_stream(self, tree):
        """A struck row carries the closed-row tick; printing it to a cp1252
        stdout raised UnicodeEncodeError (driven 2026-09-30, the Bash tool's
        pipe on Windows). Driven as the CLI under that stdout, which is the
        failure; the verb now replaces what the stream cannot show."""
        import os
        import subprocess
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), *_args(tree, "--dry-run", "strike", "DEF-1",
                                                      "--text-file", str(tree["closing"]))],
            capture_output=True, env=env, timeout=45,
        )
        assert proc.returncode == 0, proc.stderr.decode("cp1252", "replace")
        assert b"CLOSED 2026-09-06" in proc.stdout


class TestTheVerbsShareOneRoot:
    """The probe's working directory, the ledger and the roster come from one
    root, found by walking up from where the verb runs. Before, ``--ledger``
    and ``--probes`` defaulted from the script's own checkout while the probe
    ran in ``--root``, so the two could name different trees.

    The ids are ``ZZZ-`` on purpose: run against a checkout whose defaults
    still point at its own live ledger, ``--after ZZZ-2`` finds no row there
    and the verb refuses before it writes anything."""

    def test_a_verb_run_from_a_subdirectory_files_into_that_trees_ledger(
        self, lr, tree, monkeypatch
    ):
        root = tree["ledger"].parents[1]
        tree["ledger"].write_text(_ledger(
            c1_rows=("| `ZZZ-1` | site | what | major |", "| `ZZZ-2` | site | what | minor |"),
            appendix=("| `ZZZ-1` | §C1 | site |", "| `ZZZ-2` | §C1 | site |"),
        ), encoding="utf-8")
        tree["probes"].write_text(json.dumps({"_count": 0, "probes": []}) + "\n", encoding="utf-8")
        (root / "marker.txt").write_text("open=True\n", encoding="utf-8")
        deep = root / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        rc = lr.main([
            "--date", "2026-09-06", "file", "ZZZ-3", "--section", "C1", "--after", "ZZZ-2",
            "--anchor", "a", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", "python -c \"print(open('marker.txt').read().strip())\"",
            "--open-value", "open=True", "--subject", "body.md", "--inputs", "marker.txt",
        ])
        assert rc == 0
        assert "| `ZZZ-3` | a |" in tree["ledger"].read_text(encoding="utf-8")
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["ZZZ-3"]
        assert data["probes"][0]["inputs"] == ["marker.txt"]


class TestATwoIdRow:
    """DEF-863. A member row's id cell may carry two ids (`DEF-536` `LG-1`:
    eight live rows on 2026-09-20, three ids in `DEF-371a`'s). Every verb keyed
    the row on a lone id before the pipe, so such a row was invisible to strike,
    repin and file --after by EITHER id, and seven of the eight carried probes
    nothing could ever stamp. The cell is one row: addressed by any of its ids,
    struck as a whole, indexed once per id, its probes retired together.

    Earn-the-red (driven against the pre-change module): every leg reds on
    "no unstruck member row" / "no member row for --after" today."""

    _ROW = "| `DEF-1` `LG-9` | site | what | major |"

    def _two_id_tree(self, tree):
        tree["ledger"].write_text(_ledger(
            c1_rows=(self._ROW, "| `DEF-2` | site | what | minor |"),
            appendix=("| `DEF-1` | §C1 | site |", "| `LG-9` | §C1 | site |",
                      "| `DEF-2` | §C1 | site |"),
        ), encoding="utf-8")
        # the roster is written fresh (not appended), so a test may rebuild the
        # tree mid-way without drifting `_count` -- the verbs refuse that drift
        data = {"_count": 3, "probes": [
            {"id": "DEF-1", "subject": "site", "cmd": "echo a", "open_value": "a", "why_not": None, "row_sha": "x"},
            {"id": "DEF-2", "subject": "site", "cmd": "echo b", "open_value": "b", "why_not": None, "row_sha": "y"},
            {"id": "LG-9", "subject": "site", "cmd": "echo z", "open_value": "z", "why_not": None, "row_sha": "w"},
        ]}
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        return ["--root", str(tree["ledger"].parents[1])]

    @pytest.mark.parametrize("rid", ["DEF-1", "LG-9"])
    def test_a_strike_by_either_id_closes_the_whole_cell_and_retires_every_probe_it_owns(
        self, lr, tree, capsys, rid
    ):
        self._two_id_tree(tree)
        assert lr.main(_args(tree, "strike", rid, "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert ("| ~~`DEF-1`~~ ~~`LG-9`~~ | site | ✅ **CLOSED 2026-09-06 — landed in abc123 after "
                "one pass of each red team** PRIOR TEXT: what | major |") in text
        assert "| ~~`DEF-1`~~ | §C1 | site |" in text and "| ~~`LG-9`~~ | §C1 | site |" in text
        assert _derived(lr, text)[0] == 1
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        assert [p["id"] for p in data["probes"]] == ["DEF-2"] and data["_count"] == 1
        assert "2 probe(s) retired" in capsys.readouterr().out
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []
        # the closed cell is closed by either id
        assert lr.main(_args(tree, "strike", "LG-9", "--text-file", str(tree["closing"]))) == 2
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 2

    def test_a_repin_by_the_co_id_keeps_the_cell_whole_stamps_its_own_probe_and_names_the_sibling(
        self, lr, tree, capsys
    ):
        root = self._two_id_tree(tree)
        assert lr.main(_args(tree, *root, "repin", "LG-9", "--anchor", "site2",
                             "--reason", "the site moved")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-1` `LG-9` | site2 | what | major |"
        assert line in text
        # every id of the cell has an index row, and the anchor moves on each
        assert "| `DEF-1` | §C1 | site2 |" in text and "| `LG-9` | §C1 | site2 |" in text
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        by_id = {p["id"]: p for p in data["probes"]}
        chk = lr._load("check_ledger_probes")
        assert by_id["LG-9"]["row_sha"] == chk.row_sha(line)
        assert by_id["LG-9"]["text_sha"] == chk.text_sha(line)
        assert by_id["LG-9"]["verified_2026_09_06"].startswith(
            "STILL_OPEN (re-pinned value unchanged on 2026-09-06: the site moved")
        # the sibling's probe was not driven, so nothing about it moved -- and
        # the verb names it, so the operator knows one verb re-witnessed one id
        assert by_id["DEF-1"] == {"id": "DEF-1", "subject": "site", "cmd": "echo a",
                                  "open_value": "a", "why_not": None, "row_sha": "x"}
        assert "DEF-1" in capsys.readouterr().out
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_filing_after_the_co_id_lands_after_the_shared_row_and_a_duplicate_co_id_is_refused(
        self, lr, tree, capsys
    ):
        root = self._two_id_tree(tree)
        common = [*root, "file", "DEF-3", "--section", "C1", "--after", "LG-9",
                  "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]),
                  "--severity", "minor", "--probe-cmd", "echo open=True",
                  "--open-value", "open=True", "--subject", "body.md"]
        assert lr.main(_args(tree, *common)) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        member = "| `DEF-3` | new/site.py::fn | **A new defect.** Who: an adopter. | minor |"
        assert text.index(self._ROW) < text.index(member) < text.index("| `DEF-2` | site")
        assert (text.index("| `LG-9` | §C1 | site |")
                < text.index("| `DEF-3` | §C1 | new/site.py::fn |")
                < text.index("| `DEF-2` | §C1 | site |"))
        assert _derived(lr, text)[0] == 3
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []
        # a co-id already has a member row: filing it again is the duplicate refusal
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, *root, "file", "LG-9", "--section", "C1", "--after", "DEF-2",
                             "--anchor", "a", "--text-file", str(tree["body"]),
                             "--severity", "nit", "--probe-cmd", "echo open=True",
                             "--open-value", "open=True", "--subject", "body.md")) == 2
        assert "already has a member row" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_the_section_holding_a_row_is_read_by_either_id(self, lr, tree):
        self._two_id_tree(tree)
        text = tree["ledger"].read_text(encoding="utf-8")
        assert lr._section_holding(text, "LG-9") == "§C1" == lr._section_holding(text, "DEF-1")

    def test_a_dry_run_names_every_index_row_and_puts_the_sibling_note_on_its_own_line(
        self, lr, tree, capsys
    ):
        """Both reviews: the dry run is the one look an operator gets before the
        verb writes both files. A strike's dry run names each id's index row
        by state (the single-id wording had regressed to "not found" for an
        already-struck index row); a repin's sibling note used to be glued to
        the closing brace of a 700-character JSON dump."""
        root = self._two_id_tree(tree)
        # one index row already struck by hand: the note says so, per id
        text = tree["ledger"].read_text(encoding="utf-8")
        tree["ledger"].write_text(text.replace("| `LG-9` | §C1 | site |", "| ~~`LG-9`~~ | §C1 | site |"),
                                  encoding="utf-8")
        assert lr.main(_args(tree, "--dry-run", "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        out = capsys.readouterr().out
        assert "(index rows: DEF-1 struck, LG-9 already struck; 2 probe(s) would retire)" in out
        # single-id path: the three states are told apart
        tree["ledger"].write_text(_ledger(appendix=("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |")),
                                  encoding="utf-8")
        assert lr.main(_args(tree, "--reconcile-count", "--dry-run", "strike", "DEF-1",
                             "--text-file", str(tree["closing"]))) == 0
        assert "(index row already struck; 1 probe(s) would retire)" in capsys.readouterr().out
        # repin dry run: row, then the note on its own line, then parseable JSON
        self._two_id_tree(tree)
        assert lr.main(_args(tree, *root, "--dry-run", "repin", "LG-9", "--reason", "r")) == 0
        lines = capsys.readouterr().out.rstrip("\n").split("\n")
        assert lines[0] == self._ROW
        assert lines[1].startswith("(shares its row with DEF-1")
        assert json.loads("\n".join(lines[2:]))["id"] == "LG-9"

    def test_a_half_struck_cell_is_refused_by_every_verb(self, lr, tree, capsys):
        """Strike state is read at row level and a strike rewrites the whole
        cell, so a cell struck on some ids only would close a live co-id as
        collateral or re-pin a closed one. No such row exists (0 on
        2026-09-20); the verbs refuse it rather than guess (code review)."""
        root = self._two_id_tree(tree)
        text = tree["ledger"].read_text(encoding="utf-8")
        tree["ledger"].write_text(text.replace(self._ROW, "| `DEF-1` ~~`LG-9`~~ | site | what | major |"),
                                  encoding="utf-8")
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "strike", "LG-9", "--text-file", str(tree["closing"]))) == 2
        assert "struck on some ids and not others" in capsys.readouterr().err
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--reason", "r")) == 2
        assert "struck on some ids and not others" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before


class TestTheMixedClassShape:
    """§C0's rows carry `| sev | pop | aud |`; every verb must round-trip them."""

    def _mixed_tree(self, tree):
        tree["ledger"].write_text(_ledger(
            mixed=True,
        ), encoding="utf-8")
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"].append({"id": "DEF-3", "subject": "site", "cmd": "echo c", "open_value": "c",
                               "why_not": None, "row_sha": "z"})
        data["_count"] = 3
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    def test_a_strike_keeps_the_two_tag_cells(self, lr, tree):
        self._mixed_tree(tree)
        assert lr.main(_args(tree, "strike", "DEF-3", "--text-file", str(tree["closing"]))) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "PRIOR TEXT: what | nit | HYGIENE | MAINTAINER |" in text
        assert _tally(lr, text)["HYGIENE"] == 0 and _tally(lr, text)["MAINTAINER"] == 0
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_five_cell_row_is_refused(self, lr):
        with pytest.raises(lr.RowShape, match="not 4 .* or 6"):
            lr._cells("| `DEF-9` | site | what | nit | HYGIENE |")

    def test_a_tag_outside_the_vocabulary_is_refused(self, lr):
        with pytest.raises(lr.RowShape, match="not a population"):
            lr._cells("| `DEF-9` | site | what | nit | HYGIENE | ADOPTERS |")

    def test_filing_into_a_mixed_section_needs_both_tags_and_lands_them(self, lr, tree):
        self._mixed_tree(tree)
        common = ["--root", str(tree["ledger"].parents[1]), "file", "DEF-4", "--section", "C2",
                  "--after", "DEF-3", "--anchor", "new/site.py", "--text-file", str(tree["body"]),
                  "--severity", "minor", "--probe-cmd", "echo open=True", "--open-value", "open=True",
                  "--subject", "body.md"]
        # without the tags the verb refuses before anything is written
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, *common)) == 2
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert lr.main(_args(tree, *common, "--population", "LOGIC_BUG", "--audience", "ADOPTER")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-4` | new/site.py | **A new defect.** Who: an adopter. | minor | LOGIC_BUG | ADOPTER |" in text
        assert _tally(lr, text)["LOGIC_BUG"] == 3 and _tally(lr, text)["ADOPTER"] == 3

    def test_filing_tags_into_a_classed_section_is_refused(self, lr, tree, capsys):
        """A row under a token-tagged class is counted by the class; cells on it
        would be printed and never counted (both reviewers drove this)."""
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "file", "DEF-3",
                             "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                             "--text-file", str(tree["body"]), "--severity", "nit",
                             "--probe-cmd", "echo open=True", "--open-value", "open=True",
                             "--subject", "body.md", "--population", "HYGIENE",
                             "--audience", "MAINTAINER")) == 2
        assert "inherits its tags from the class index" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def _one_axis_mixed_tree(self, tree, *, first_row="| `DEF-1` | site | what | major | LOGIC_BUG | ADOPTER |"):
        """§C1 declared LOGIC_BUG / MIXED -- the shape the live ledger already
        carries for four classes (§C13, §C14, §C18, §C20 on 2026-09-20) and the
        third rebuild's file for ten, its §C1 being OPERATOR_ACTION / MIXED. The
        generator counts such a class by the class tag on the classed axis and
        by each row's OWN cell on the MIXED axis, so every row there is the
        6-cell shape and the classed cell must repeat the class tag. Callers
        that need a stranded row pass a 4-cell ``first_row``."""
        tree["ledger"].write_text(_ledger(
            c1_tags=("LOGIC_BUG", "MIXED"),
            c1_rows=(first_row,
                     "| `DEF-2` | site | what | minor | LOGIC_BUG | MAINTAINER |"),
        ), encoding="utf-8")

    def test_filing_into_a_section_mixed_on_one_axis_needs_both_tags_and_the_classed_one_must_match(
        self, lr, tree, capsys
    ):
        """Until 2026-09-20 the verb keyed "MIXED" on BOTH axes (`DEF-776`), so a
        row filed into a one-axis-MIXED class went out as the 4-cell shape and
        was refused only by convergence, with the generator's dump -- or, with
        tags, was refused as "inherits its tags from the class index", which is
        false for the MIXED axis. Earn-the-red (driven against the pre-change
        module by both reviewers): leg 1 reds because the old refusal is the
        convergence dump, not the verb's own MIXED-on-one-axis wording; leg 2
        reds on "inherits its tags"; leg 3 reds because the filing is refused
        instead of landing."""
        self._one_axis_mixed_tree(tree)
        common = ["--root", str(tree["ledger"].parents[1]), "file", "DEF-3", "--section", "C1",
                  "--after", "DEF-2", "--anchor", "new/site.py", "--text-file", str(tree["body"]),
                  "--severity", "minor", "--probe-cmd", "echo open=True", "--open-value", "open=True",
                  "--subject", "body.md"]
        before = tree["ledger"].read_text(encoding="utf-8")
        # no tags: refused before anything is written, by the verb's own wording,
        # which names the token the classed axis requires
        assert lr.main(_args(tree, *common)) == 2
        err = capsys.readouterr().err
        assert "is MIXED on one axis (LOGIC_BUG / MIXED)" in err and "--population LOGIC_BUG" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        # tags, but the classed axis disagrees with the class index: refused by name
        assert lr.main(_args(tree, *common, "--population", "HYGIENE", "--audience", "OPERATOR")) == 2
        err = capsys.readouterr().err
        assert "declares population 'LOGIC_BUG'" in err and "HYGIENE" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        # the classed axis repeats the class tag, the MIXED axis is the row's own: lands 6-cell
        assert lr.main(_args(tree, *common, "--population", "LOGIC_BUG", "--audience", "OPERATOR")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3` | new/site.py | **A new defect.** Who: an adopter. | minor | LOGIC_BUG | OPERATOR |" in text
        assert _tally(lr, text)["OPERATOR"] == 1 and _tally(lr, text)["LOGIC_BUG"] == 3
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_filing_refuses_a_section_that_is_not_the_one_after_sits_in(self, lr, tree, capsys):
        """`--section` selects the class whose tags the new row is validated
        against, but the row lands after `--after`'s row wherever that is: with
        `--section C2 --after DEF-1` the row was validated against §C2, inserted
        into §C1, indexed under §C2, and converged because the two classes
        happened to agree (both reviewers drove it, 2026-09-20). Earn-the-red:
        drop the `_section_holding` check in `file_row` and the call lands."""
        self._mixed_tree(tree)
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "file", "DEF-4",
                             "--section", "C2", "--after", "DEF-1", "--anchor", "a",
                             "--text-file", str(tree["body"]), "--severity", "nit",
                             "--probe-cmd", "echo open=True", "--open-value", "open=True",
                             "--subject", "body.md", "--population", "LOGIC_BUG",
                             "--audience", "ADOPTER")) == 2
        err = capsys.readouterr().err
        assert "--after DEF-1 sits in §C1, not §C2" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_repin_cannot_retag_the_classed_axis_of_a_one_axis_mixed_row(self, lr, tree, capsys):
        """`repin --population` on a row whose class index declares the population
        token would print the row's cell while the class keeps counting its own
        (the generator's contradiction arm); the MIXED axis stays retaggable.
        Earn-the-red: drop the classed-axis check in `repin` and the first call
        is refused only by convergence -- after the probe run and the sidecar
        write, as the generator's dump rather than a refusal the verb owns."""
        self._one_axis_mixed_tree(tree)
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        root = ["--root", str(tree["ledger"].parents[1])]
        before = tree["ledger"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--population", "HYGIENE", "--reason", "r")) == 2
        assert "sits in §C1, which declares population 'LOGIC_BUG'" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--audience", "OPERATOR",
                             "--reason", "its named user is the operator")) == 0
        assert "| `DEF-1` | site | what | major | LOGIC_BUG | OPERATOR |" in tree["ledger"].read_text(encoding="utf-8")

    def test_repin_widens_a_row_stranded_4_cell_when_its_class_went_mixed(self, lr, tree, capsys):
        """A rebuild flips a class to MIXED on an axis; a row it leaves 4-cell
        strands EVERY verb on the ledger, because convergence is global, and the
        old refusal ("inherits its tags from the class index") pointed the wrong
        way -- the class already IS MIXED (failure-mode pass, 2026-09-20). With
        one flag the verb names the remedy; with both it widens the row in place.
        Earn-the-red: restore the unconditional `len(cells) != 6` refusal and
        the second call is refused."""
        self._one_axis_mixed_tree(tree, first_row="| `DEF-1` | site | what | major |")
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        root = ["--root", str(tree["ledger"].parents[1])]
        before = tree["ledger"].read_text(encoding="utf-8")
        # the stranded state is real: the generator names the row
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert any("DEF-1" in d["detail"] and "MIXED" in d["detail"] for d in gen.find_drift(before))
        # one flag: the true remedy, nothing written
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--audience", "ADOPTER", "--reason", "r")) == 2
        err = capsys.readouterr().err
        assert "still carries no tag cells" in err and "give --population and --audience together" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        # both flags: widened, converged
        assert lr.main(_args(tree, *root, "repin", "DEF-1", "--population", "LOGIC_BUG",
                             "--audience", "ADOPTER", "--reason", "widened after §C1 went MIXED")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-1` | site | what | major | LOGIC_BUG | ADOPTER |" in text
        assert gen.find_drift(text) == []

    def test_repin_retags_a_mixed_row_without_staling_its_claim(self, lr, tree):
        self._mixed_tree(tree)
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-3",
                             "--audience", "ADOPTER", "--reason", "its named user is an adopter")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-3` | site | what | nit | HYGIENE | ADOPTER |"
        assert line in text and _tally(lr, text)["ADOPTER"] == 3
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        p = [x for x in data["probes"] if x["id"] == "DEF-3"][0]
        chk = lr._load("check_ledger_probes")
        assert p["row_sha"] == chk.row_sha(line) and p["text_sha"] == chk.text_sha(line)
        assert p["verified_2026_09_06"] == (
            "STILL_OPEN (re-pinned value unchanged on 2026-09-06: its named user is an adopter)"
        )
        assert chk.text_sha(line) == chk.text_sha("| `DEF-3` | site | what | nit | HYGIENE | MAINTAINER |")

    def test_a_repin_regrades_severity_and_leaves_the_two_tag_cells_alone(self, lr, tree):
        """The 6-cell shape carries severity in the same cell as the 4-cell
        one, so the --severity leg must round-trip it without disturbing the
        tags beside it. Earn-the-red: widen `cells[3] = severity` to also
        touch cells[4] or [5] and this reds on the tag cells."""
        self._mixed_tree(tree)
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-3",
                             "--severity", "major",
                             "--reason", "re-graded on realised consequence")) == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3` | site | what | major | HYGIENE | MAINTAINER |" in text

    def test_repin_cannot_retag_a_classed_row(self, lr, tree, capsys):
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-1",
                             "--audience", "ADOPTER", "--reason", "r")) == 2
        assert "inherits its tags from the class index" in capsys.readouterr().err

    def test_one_tag_without_the_other_is_a_usage_error(self, lr, tree):
        with pytest.raises(SystemExit):
            lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "file", "DEF-4",
                          "--section", "C1", "--after", "DEF-2", "--anchor", "a",
                          "--text-file", str(tree["body"]), "--severity", "nit",
                          "--why-not", "x", "--subject", "body.md", "--population", "HYGIENE"))


class TestRepin:
    def _repin(self, lr, tree, *extra):
        # the fixture probe's subject is `site`; the runner refuses a subject that moved
        (tree["ledger"].parents[1] / "site").write_text("", encoding="utf-8")
        return lr.main(_args(tree, "--root", str(tree["ledger"].parents[1]), "repin", "DEF-1", *extra))

    def _probe(self, tree):
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        return data, [p for p in data["probes"] if p["id"] == "DEF-1"][0]

    def test_repin_declares_the_inputs_the_command_reads_and_drives_them_first(self, lr, tree, capsys):
        """`DEF-858`: the verb writes the declaration and drives the probe through
        the runner's own gate with it, so a declared path absent on this tree
        refuses the re-pin (the UNRESOLVED the recurring check would report) and
        writes nothing; a later re-pin without the flag keeps the list AND still
        drives it."""
        root = tree["ledger"].parents[1]
        (root / "site").write_text("", encoding="utf-8")
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--inputs",
                             "records/Done", "--reason", "the command reads the folder")) == 2
        assert "input missing: records/Done" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before
        (root / "records" / "Done").mkdir(parents=True)
        (root / "records" / "Done" / "TP-1-x.md").write_text("", encoding="utf-8")  # a bare dir is "input empty"
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--inputs",
                             "records/Done", "--inputs", "site",
                             "--reason", "the command reads the folder")) == 0
        _data, p = self._probe(tree)
        assert p["inputs"] == ["records/Done", "site"] and p["open_value"] == "a"
        assert "inputs None -> ['records/Done', 'site']" in p["verified_2026_09_06"]
        # kept, and driven: with the folder gone the kept declaration refuses
        assert self._repin(lr, tree, "--reason", "value unchanged") == 0
        assert self._probe(tree)[1]["inputs"] == ["records/Done", "site"]
        (root / "records" / "Done" / "TP-1-x.md").unlink()
        (root / "records" / "Done").rmdir()
        assert self._repin(lr, tree, "--reason", "value unchanged") == 2
        assert "input missing: records/Done" in capsys.readouterr().err

    def test_repin_inputs_is_refused_on_a_row_with_no_probe_command(self, lr, tree, capsys):
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"][0]["cmd"] = None
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        root = tree["ledger"].parents[1]
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--inputs", "site",
                             "--reason", "r")) == 2
        assert "--inputs cannot be driven" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before

    def test_repin_re_points_the_subject_and_drives_the_probe_against_it(self, lr, tree, capsys):
        """A probe filed against the wrong subject -- 2026-09-21, DEF-914's read the
        packs but named the reader module it imports, and the paperwork ratchet
        (tests/test_check_ledger_probes.py) caught the shape -- had no verb to move
        it, and a hand edit of the probes file is the trace-destroying path. The
        new subject is driven first: a missing one is UNRESOLVED and re-pins nothing."""
        root = tree["ledger"].parents[1]
        (root / "site").write_text("", encoding="utf-8")
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--subject",
                             "task-packs/other.md", "--reason", "the fix edits the packs")) == 2
        assert "subject missing" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before
        (root / "task-packs" / "other.md").write_text("", encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--subject",
                             "task-packs/other.md", "--reason", "the fix edits the packs")) == 0
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        p = next(e for e in data["probes"] if e["id"] == "DEF-1")
        assert p["subject"] == "task-packs/other.md" and p["open_value"] == "a"
        assert "subject 'site' -> 'task-packs/other.md'" in p["verified_2026_09_06"]

    def test_repin_subject_is_refused_on_a_row_with_no_probe_command(self, lr, tree, capsys):
        # Nine roster rows carry `cmd: null`; a subject written there is un-driven.
        data = json.loads(tree["probes"].read_text(encoding="utf-8"))
        data["probes"][0]["cmd"] = None
        tree["probes"].write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        root = tree["ledger"].parents[1]
        (root / "task-packs" / "other.md").write_text("", encoding="utf-8")
        before = tree["probes"].read_text(encoding="utf-8")
        assert lr.main(_args(tree, "--root", str(root), "repin", "DEF-1", "--subject",
                             "task-packs/other.md", "--reason", "r")) == 2
        assert "give --probe-cmd" in capsys.readouterr().err
        assert tree["probes"].read_text(encoding="utf-8") == before

    def test_repin_drives_the_probe_moves_the_pin_and_stamps_the_reason(self, lr, tree):
        assert self._repin(lr, tree, "--probe-cmd", "echo drifted", "--open-value", "drifted",
                           "--reason", "count moved 1 -> 2") == 0
        data, p = self._probe(tree)
        assert p["open_value"] == "drifted" and p["cmd"] == "echo drifted"
        assert p["verified_2026_09_06"] == (
            "STILL_OPEN (re-pinned 'a' -> 'drifted' on 2026-09-06: count moved 1 -> 2)"
        )
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-1` | site | what | major |"
        assert line in text
        assert p["row_sha"] == hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]
        assert data["_count"] == 2
        gen = lr._load("generate_ledger_regions")
        gen._PROBES = tree["probes"]
        assert gen.find_drift(text) == []

    def test_a_probe_that_does_not_print_the_new_value_repins_nothing(self, lr, tree, capsys):
        before = tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")
        # the fixture probe is `echo a`: it prints a, never drifted
        assert self._repin(lr, tree, "--open-value", "drifted", "--reason", "r") == 2
        assert "does not print the new open value 'drifted'" in capsys.readouterr().err
        assert (tree["ledger"].read_text(encoding="utf-8"), tree["probes"].read_text(encoding="utf-8")) == before

    def test_repin_rewrites_the_text_cell_and_the_sha_the_checker_recomputes(self, lr, tree, tmp_path):
        new = tmp_path / "what.md"
        new.write_text("what, re-measured\ntoday", encoding="utf-8")
        assert self._repin(lr, tree, "--text-file", str(new), "--reason", "re-measured") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        member = "| `DEF-1` | site | what, re-measured today | major |"
        assert member in text
        _data, p = self._probe(tree)
        assert p["row_sha"] == hashlib.sha256(member.encode("utf-8")).hexdigest()[:12]
        assert p["open_value"] == "a"  # kept: the existing probe still prints it
        # the sha the checker recomputes from the live line
        chk = lr._load("check_ledger_probes")
        assert hashlib.sha256(chk._row_line("DEF-1", text).encode("utf-8")).hexdigest()[:12] == p["row_sha"]

    def test_a_struck_row_cannot_be_repinned(self, lr, tree, capsys):
        assert lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"]))) == 0
        assert self._repin(lr, tree, "--reason", "r") == 2
        assert "no unstruck member row" in capsys.readouterr().err

    def test_repin_regrades_a_CLASSED_row_no_mixed_class_needed(self, lr, tree):
        """The severity cell is cell 4 of EVERY member row, so unlike
        --audience this needs no MIXED class -- DEF-1 is a 4-cell classed row
        and its grade moves. Before 2026-09-18 there was no verb at all and a
        re-grade was a hand edit that staled row_sha; the sha assertion below
        is what pins that it no longer does.

        Earn-the-red: drop `cells[3] = severity` in `repin` and this reds on
        the line assertion; drop the `entry.update(_pins(new_line))` that
        follows it and this reds on the sha assertion instead."""
        assert self._repin(lr, tree, "--severity", "nit",
                           "--reason", "re-graded: no adopter reaches it") == 0
        text = tree["ledger"].read_text(encoding="utf-8")
        line = "| `DEF-1` | site | what | nit |"
        assert line in text
        assert "| `DEF-1` | site | what | major |" not in text
        _data, probe = self._probe(tree)
        chk = lr._load("check_ledger_probes")
        assert probe["row_sha"] == chk.row_sha(line), "a re-grade must not stale the claim"
        assert probe["verified_2026_09_06"] == (
            "STILL_OPEN (re-pinned value unchanged; severity major -> nit on 2026-09-06: "
            "re-graded: no adopter reaches it)"
        )

    def test_repin_without_severity_keeps_the_grade(self, lr, tree):
        """The false-deny twin: every other repin leg must leave cell 4 alone.
        A default that silently re-graded would be worse than no verb."""
        assert self._repin(lr, tree, "--reason", "anchor moved only",
                           "--anchor", "site2") == 0
        assert "| `DEF-1` | site2 | what | major |" in tree["ledger"].read_text(encoding="utf-8")


@pytest.mark.contract
def test_the_probes_file_is_byte_stable_under_its_own_serializer():
    """The sidecar is tracked since 2026-09-21. Pin the exact spelling
    scripts/ledger_row.py writes (`json.dumps(..., indent=1, ensure_ascii=False)`
    plus a trailing newline) so a reformat is a deliberate act, not a
    two-thousand-line hunk riding along with a one-row repin (the failure-mode
    lane, 2026-09-21)."""
    p = REPO_ROOT / "task-packs" / "LEDGER_PROBES.json"
    if not p.is_file():
        pytest.skip("self-host only: the probes file is absent on this tree")
    text = p.read_text(encoding="utf-8")
    assert json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n" == text, (
        "task-packs/LEDGER_PROBES.json is not byte-stable under ledger_row.py's own "
        "serializer -- something reformatted it; write it through the verbs only"
    )


# ── the verbs read the mail channel's claims before they write ───────────────

def _mail_module():
    spec = importlib.util.spec_from_file_location("_mail_for_ledger_tests", REPO_ROOT / "tools" / "cc" / "mail.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_channel(mail, *claims, machine="mac"):
    """A stand-in for the mail module: this box is named, the other box's
    claims are given, the fold and the overlap are the real ones."""
    import types
    return types.SimpleNamespace(
        machine_setting=lambda root, **kw: (machine, "named"),
        read_mail=lambda root, **kw: ({"win": list(claims)}, {}),
        live_claims=mail.live_claims,
        overlapping_claims=mail.overlapping_claims,
    )


class TestTheVerbsReadTheClaims:
    """Before a writing verb takes the lock, it reads the other machine's live
    claims from the local mail refs. A claim naming this ROW's id refuses by
    name (one id minted twice, or one row touched on both sides, is what the
    record merge cannot take); a claim naming only the row's CLASS is a note,
    because two rows in one class merge cleanly. Nothing is read where the
    box is unnamed or the channel is absent, and a refusal names the way past:
    --override."""

    def _file(self, lr, tree, *pre):
        return lr.main(_args(
            tree, "--root", str(tree["ledger"].parents[1]), *pre,
            "file", "DEF-3", "--section", "C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", "echo open=True", "--open-value", "open=True", "--subject", "body.md",
        ))

    def test_a_claim_on_the_id_refuses_before_anything_is_written(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C66"], ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        before = tree["ledger"].read_text(encoding="utf-8")
        assert self._file(lr, tree) == 2
        err = capsys.readouterr().err
        assert "refused" in err and "win claims id DEF-3 on lane/c66" in err and "--override" in err
        assert tree["ledger"].read_text(encoding="utf-8") == before
        assert not tree["ledger"].with_name(tree["ledger"].name + ".lock").exists()

    def test_override_writes_and_names_the_holder(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        assert self._file(lr, tree, "--override") == 0
        err = capsys.readouterr().err
        assert "override" in err and "win claims id DEF-3" in err
        assert "| `DEF-3` |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_dry_run_reports_the_claim_and_writes_nothing(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        before = tree["ledger"].read_text(encoding="utf-8")
        assert self._file(lr, tree, "--dry-run") == 0
        assert "win claims id DEF-3" in capsys.readouterr().err
        assert tree["ledger"].read_text(encoding="utf-8") == before

    def test_a_claim_on_the_class_only_is_a_note_and_the_row_lands(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C1"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        assert self._file(lr, tree) == 0
        err = capsys.readouterr().err
        assert "note" in err and "win claims class C1 on lane/c66" in err and "refused" not in err
        assert "| `DEF-3` |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_strike_of_a_row_the_other_box_claims_is_refused(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-1"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])))
        assert rc == 2
        assert "win claims id DEF-1" in capsys.readouterr().err
        assert "~~`DEF-1`~~" not in tree["ledger"].read_text(encoding="utf-8")

    def test_an_unnamed_box_or_an_absent_channel_reads_nothing(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["DEF-3"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs, machine=None))
        assert self._file(lr, tree) == 0
        assert "claims" not in capsys.readouterr().err
        monkeypatch.setattr(lr, "_mail_module", lambda: None)
        rc = lr.main(_args(tree, "strike", "DEF-3", "--text-file", str(tree["closing"])))
        assert rc == 0 and "claims" not in capsys.readouterr().err

    def test_a_two_id_row_is_read_by_every_id_on_its_cell(self, lr, tree, monkeypatch, capsys):
        """A row addressed by one of its ids is the same row to a claim on the
        other (failure-mode review, driven: twenty-one live rows carry more
        than one id)."""
        TestATwoIdRow()._two_id_tree(tree)
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", ids=["LG-9"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(tree, "strike", "DEF-1", "--text-file", str(tree["closing"])))
        assert rc == 2
        assert "win claims id LG-9" in capsys.readouterr().err
        assert "~~`DEF-1`" not in tree["ledger"].read_text(encoding="utf-8")

    def test_the_class_verb_refuses_on_a_class_claim(self, lr, tree, monkeypatch, capsys):
        """The verb mints the section: the same class opened on two boxes is
        one id minted twice, so here a class claim refuses, not notes."""
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C7"], ids=["DEF-9"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(tree, "class", "C7", "--title", "Make X do Y",
                           "--population", "HYGIENE", "--audience", "MAINTAINER"))
        assert rc == 2
        err = capsys.readouterr().err
        assert "refused" in err and "win claims class C7" in err and "minted twice" in err
        assert "C7" not in tree["ledger"].read_text(encoding="utf-8")

    def test_a_channel_present_without_its_sibling_is_a_note_and_a_write(self, lr, tree, monkeypatch, capsys):
        """mail.py imports record_merge at load; a copied subset that has the
        one and not the other raised out of the verb (both reviews, driven).
        The loader runs inside the fail-open now: a note, then the write."""
        def _broken():
            raise ModuleNotFoundError("No module named 'record_merge'")
        monkeypatch.setattr(lr, "_mail_module", _broken)
        assert self._file(lr, tree) == 0
        err = capsys.readouterr().err
        assert "could not be read" in err and "record_merge" in err
        assert "| `DEF-3` |" in tree["ledger"].read_text(encoding="utf-8")

    def test_a_section_typed_with_the_sign_reads_as_the_class(self, lr, tree, monkeypatch, capsys):
        mail = _mail_module()
        theirs = mail.new_message("win", "claim", "", lane="lane/c66", classes=["C1"])
        monkeypatch.setattr(lr, "_MAIL", _stub_channel(mail, theirs))
        rc = lr.main(_args(
            tree, "--root", str(tree["ledger"].parents[1]),
            "file", "DEF-3", "--section", "§C1", "--after", "DEF-2",
            "--anchor", "new/site.py::fn", "--text-file", str(tree["body"]), "--severity", "minor",
            "--probe-cmd", "echo open=True", "--open-value", "open=True", "--subject", "body.md",
        ))
        assert rc == 0
        assert "win claims class C1" in capsys.readouterr().err


# ── ids are minted from the seat's block (TP-479 Wave B-1) ───────────────────

_BLOCKS = """# the seat blocks, as the self-host espalier.toml carries them
dispatcher = "air"

[id_blocks]
win = { DEF = "2000-2999", INV = "100-199", TP = "500-599" }
win-2 = { DEF = "3000-3999", INV = "200-299", TP = "600-699" }
_unnamed = { DEF = "1199-1999", INV = "32-99", TP = "479-499" }
"""


def _seat_channel(mail, machine, *claims, inherited=False):
    """The mail module as a seat sees it: its name, whether a linked worktree
    inherited that name, and the live claims (the fold is the real one)."""
    import types
    return types.SimpleNamespace(
        machine_setting=lambda root, **kw: (machine, "named" if machine else "unnamed"),
        worktree_name_inherited=lambda root, **kw: inherited,
        read_mail=lambda root, **kw: ({"other": list(claims)}, {}),
        live_claims=mail.live_claims,
        overlapping_claims=mail.overlapping_claims,
    )


def _seat_tree(base: Path, blocks: str | None = _BLOCKS) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    t = _build_tree(base)
    if blocks is not None:
        (base / "espalier.toml").write_text(blocks, encoding="utf-8")
    return t


def _file_minted(lr, t, *pre, rid=()):
    return lr.main(_args(
        t, "--root", str(t["ledger"].parents[1]), *pre,
        "file", *rid, "--section", "C1", "--after", "DEF-2",
        "--anchor", "new/site.py::fn", "--text-file", str(t["body"]), "--severity", "minor",
        "--probe-cmd", "echo open=True", "--open-value", "open=True", "--subject", "body.md",
    ))


def _mint(lr, t, kind, *pre):
    return lr.main(_args(t, "--root", str(t["ledger"].parents[1]), *pre, "mint", "--kind", kind))


def _hand_picked_next(t) -> int:
    """The habit minting replaces: the highest DEF number on the base, plus one."""
    import re
    return max(int(n) for n in re.findall(r"DEF-(\d+)", t["ledger"].read_text(encoding="utf-8"))) + 1


class TestIdsAreMintedFromTheSeatsBlock:
    """``file`` with the id left out mints the lowest free number of this
    seat's block in ``espalier.toml [id_blocks]``; ``mint`` reserves one
    without filing. Two seats filing from one base cannot collide, which the
    old habit of "highest id plus one" does by construction."""

    def test_two_seats_filing_from_one_base_mint_different_ids(self, lr, tmp_path, monkeypatch, capsys):
        mail = _mail_module()
        a, b = _seat_tree(tmp_path / "win"), _seat_tree(tmp_path / "win-2")
        assert _hand_picked_next(a) == _hand_picked_next(b), "the fixture shows the hand-picked collision"
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win"))
        assert _file_minted(lr, a) == 0
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win-2"))
        assert _file_minted(lr, b) == 0
        assert "| `DEF-2000` |" in a["ledger"].read_text(encoding="utf-8")
        assert "| `DEF-3000` |" in b["ledger"].read_text(encoding="utf-8")
        assert "minted DEF-2000" in capsys.readouterr().err

    def test_a_reservation_holds_its_number_in_this_checkout_only(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        before = t["ledger"].read_text(encoding="utf-8")
        assert _mint(lr, t, "DEF") == 0 and _mint(lr, t, "DEF") == 0
        assert capsys.readouterr().out.split() == ["DEF-2000", "DEF-2001"]
        assert t["ledger"].read_text(encoding="utf-8") == before, "a mint writes no tracked file"
        assert json.loads((tmp_path / lr.MINTED_RECORD).read_text(encoding="utf-8")) == {"DEF": [2000, 2001]}
        assert _file_minted(lr, t) == 0, "the filing after them skips both"
        assert "| `DEF-2002` |" in t["ledger"].read_text(encoding="utf-8")

    def test_a_dry_run_mint_reserves_nothing(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "INV", "--dry-run") == 0 and _mint(lr, t, "INV", "--dry-run") == 0
        assert capsys.readouterr().out.count("INV-100 (dry run: not reserved)") == 2
        assert not (tmp_path / lr.MINTED_RECORD).exists()

    def test_a_live_claim_on_the_next_number_is_skipped(self, lr, tmp_path, monkeypatch, capsys):
        mail = _mail_module()
        t = _seat_tree(tmp_path)
        mine = mail.new_message("win", "claim", "", lane="lane/x", ids=["DEF-2000"])
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(mail, "win", mine))
        assert _mint(lr, t, "DEF") == 0
        assert capsys.readouterr().out.strip() == "DEF-2001"

    def test_a_pack_number_skips_every_pack_file_under_task_packs(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        (tmp_path / "task-packs" / "TP-500-first.md").write_text("x", encoding="utf-8")
        (tmp_path / "task-packs" / "Done").mkdir()
        (tmp_path / "task-packs" / "Done" / "TP-501-second.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "TP") == 0
        assert capsys.readouterr().out.strip() == "TP-502"

    def test_an_inherited_worktree_name_is_refused_with_the_commands(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win", inherited=True))
        before = t["ledger"].read_text(encoding="utf-8")
        assert _file_minted(lr, t) == 2
        err = capsys.readouterr().err
        assert "refused" in err and "answers its clone's name 'win'" in err
        assert "git config extensions.worktreeConfig true" in err
        assert "git config --worktree espalier.machine <name>" in err
        assert t["ledger"].read_text(encoding="utf-8") == before
        assert not (tmp_path / lr.MINTED_RECORD).exists()

    def test_an_unnamed_clone_mints_from_the_shared_range_and_says_so(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), None))
        assert _mint(lr, t, "DEF") == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "DEF-1199"
        assert "shared range" in captured.err

    def test_a_named_seat_without_a_block_is_sent_to_the_dispatcher(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "air"))
        assert _mint(lr, t, "DEF") == 2
        assert "'air' has no DEF block" in capsys.readouterr().err

    def test_without_a_block_table_a_mint_refuses_and_explicit_ids_file(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path, blocks=None)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _file_minted(lr, t) == 2
        assert "give the id explicitly" in capsys.readouterr().err
        assert _file_minted(lr, t, rid=("DEF-3",)) == 0

    def test_an_explicit_id_in_another_seats_block_is_refused(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _file_minted(lr, t, rid=("DEF-3000",)) == 2
        assert "DEF-3000 sits in win-2's DEF block" in capsys.readouterr().err
        assert _file_minted(lr, t, "--override", rid=("DEF-3000",)) == 0
        # A sub-row in this seat's own block and a pre-block id both file.
        assert _file_minted(lr, t, rid=("DEF-2005a",)) == 0
        assert _file_minted(lr, t, rid=("DEF-3",)) == 0

    def test_overlapping_blocks_are_refused_by_name(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path, blocks='[id_blocks]\nwin = { DEF = "2000-2999" }\nwin-2 = { DEF = "2500-3499" }\n')
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "DEF") == 2
        assert "overlaps" in capsys.readouterr().err

    def test_a_line_the_scan_cannot_read_is_refused_by_number(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path, blocks='[id_blocks]\nwin = { DEF = "2000-2999" }\nwin-2 = {\n  DEF = "3000" }\n')
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        assert _mint(lr, t, "DEF") == 2
        assert "line 3" in capsys.readouterr().err

    def test_a_mint_waits_for_the_ledger_lock(self, lr, tmp_path, monkeypatch, capsys):
        t = _seat_tree(tmp_path)
        monkeypatch.setattr(lr, "_MAIL", _seat_channel(_mail_module(), "win"))
        with lr._GEN.ledger_lock(t["ledger"]):
            assert _mint(lr, t, "DEF") == 2
        assert not (tmp_path / lr.MINTED_RECORD).exists()


class TestTheSelfHostBlockTable:
    """The live table the seats mint from: every seat the protocol names, every
    kind, and the shared range for an unnamed clone. ``read_id_blocks`` refuses
    an overlap, so a clean parse is also the no-overlap pin."""

    def test_the_self_host_table_names_every_seat_and_kind(self, lr):
        blocks = lr.read_id_blocks(REPO_ROOT)
        if blocks is None:
            pytest.skip("this tree's espalier.toml carries no [id_blocks] table")
        for seat in ("win", "win-2", "air", lr.UNNAMED_SEAT):
            assert set(blocks.get(seat, {})) == set(lr.ID_KINDS), seat
