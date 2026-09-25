# slow-exempt: a dozen cases measured under three seconds -- the git work is
# `init`, a few `commit`s and a handful of `log`/`show`s on a five-row ledger.
"""Pins ``scripts/ledger_trend.py``'s metrics on a synthetic record ref, because a
number that feeds contract rule 5 must be able to fail.

The live ``record`` ref is local session state (never in CI, and its
snapshots are the operator's), so the proof is a scratch repository whose
orphan ref carries ledgers built from the one synthetic grammar the region
tests already own. The fixture is shaped so each metric can fail on its own:
a row filed untagged and tagged only when struck (latest-tag-wins), a row
filed and still open (replacement) beside one filed then struck (churn) and
one filed already struck (same-step churn, invisible to the per-step column),
and a second ref with a row deleted rather than struck and a row re-opened
(the two transitions that move ``net`` without a filing or a strike). The
first cut's fixture let three plausible bugs pass all nine tests (code
review, mutation-driven); this one reds on each.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from tests.test_generate_ledger_regions import _ledger

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "ledger_trend.py"
LEDGER = "task-packs/FORWARD_LEDGER.md"

if not MODULE_PATH.is_file():  # pragma: no cover - adopter tree
    pytest.skip("scripts/ledger_trend.py is self-host dev tooling", allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("ledger_trend", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def lt():
    return _load()


_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str, day: str = "2026-09-01") -> str:
    env = {**_ENV, "GIT_AUTHOR_DATE": f"{day}T00:00:00", "GIT_COMMITTER_DATE": f"{day}T00:00:00"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8", env=env).stdout


def _snapshot(repo: Path, text: str, day: str) -> None:
    path = repo / LEDGER
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-f", LEDGER)
    _git(repo, "commit", "-q", "-m", f"record: {day}", day=day)


def _repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "--orphan", "record")
    return repo


_STRUCK_1 = ("| ~~`DEF-1`~~ | site | closed | major |", "| `DEF-2` | site | what | minor |")
_APPX_1 = ("| ~~`DEF-1`~~ | §C1 | site |", "| `DEF-2` | §C1 | site |")


@pytest.fixture
def record_repo(tmp_path):
    """Three snapshots.

    1. 09-01: DEF-1 and DEF-2 live in §C1 (LOGIC_BUG / ADOPTER).
    2. 09-02: DEF-1 struck; DEF-3 filed in the MIXED §C2 WITHOUT its cells.
    3. 09-03: DEF-3 struck, now carrying HYGIENE / MAINTAINER; DEF-4 filed and
       live (LOGIC_BUG / ADOPTER, replacement); DEF-5 filed already struck
       (HYGIENE / OPERATOR, churn the per-step column never sees).
    """
    repo = _repo(tmp_path, "repo")
    _snapshot(repo, _ledger(), "2026-09-01")
    _snapshot(repo, _ledger(mixed=True, c1_rows=_STRUCK_1, appendix=_APPX_1,
                            c2_rows=("| `DEF-3` | site | what | nit |",)), "2026-09-02")
    _snapshot(repo, _ledger(mixed=True, c1_rows=_STRUCK_1, appendix=_APPX_1, c2_rows=(
        "| ~~`DEF-3`~~ | site | closed | nit | HYGIENE | MAINTAINER |",
        "| `DEF-4` | site | what | nit | LOGIC_BUG | ADOPTER |",
        "| ~~`DEF-5`~~ | site | closed | nit | **HYGIENE** | OPERATOR |",
    )), "2026-09-03")
    return repo


@pytest.fixture
def transitions_repo(tmp_path):
    """A: DEF-1, DEF-2 live. B: DEF-1 gone without a strike, DEF-2 struck.
    C: DEF-2 live again."""
    repo = _repo(tmp_path, "transitions")
    _snapshot(repo, _ledger(), "2026-09-01")
    _snapshot(repo, _ledger(c1_rows=("| ~~`DEF-2`~~ | site | closed | minor |",),
                            appendix=("| ~~`DEF-2`~~ | §C1 | site |",)), "2026-09-02")
    _snapshot(repo, _ledger(c1_rows=("| `DEF-2` | site | what | minor |",),
                            appendix=("| `DEF-2` | §C1 | site |",)), "2026-09-03")
    return repo


class TestTheSteps:
    def test_each_step_reports_filed_struck_and_net(self, lt, record_repo):
        steps = lt.trend(record_repo, "record", LEDGER, None)["steps"]
        assert [s["date"] for s in steps] == ["2026-09-02", "2026-09-03"]
        assert steps[0]["filed"] == ["DEF-3"] and steps[0]["struck"] == ["DEF-1"]
        assert steps[0]["net"] == 0 and steps[0]["live"] == 2
        # DEF-5 is filed even though it was never live: filed is set(cur) - set(prev)
        assert steps[1]["filed"] == ["DEF-4", "DEF-5"] and steps[1]["struck"] == ["DEF-3"]
        assert steps[1]["net"] == 0 and steps[1]["live"] == 2
        assert steps[0]["struck_by_audience"] == {"ADOPTER": 1}
        assert steps[1]["struck_by_population"] == {"HYGIENE": 1}

    def test_the_window_tells_backlog_from_churn_from_replacement(self, lt, record_repo):
        w = lt.trend(record_repo, "record", LEDGER, None)["window"]
        assert (w["live_first"], w["live_last"], w["net"]) == (2, 2, 0)
        assert w["backlog_struck"] == ["DEF-1"]
        assert w["filed"] == ["DEF-3", "DEF-4", "DEF-5"]
        assert w["churn"] == ["DEF-3", "DEF-5"] and w["replacement"] == ["DEF-4"]
        assert w["same_step_churn"] == ["DEF-5"]
        assert w["dropped"] == [] and w["reopened"] == [] and w["identity_gap"] == 0
        assert w["replacement_by_audience"] == {"ADOPTER": 1}
        assert w["churn_by_audience"] == {"MAINTAINER": 1, "OPERATOR": 1}
        assert w["churn_by_population"] == {"HYGIENE": 2}

    def test_since_and_from_narrow_the_window(self, lt, record_repo):
        by_date = lt.trend(record_repo, "record", LEDGER, "2026-09-02")
        assert [s["date"] for s in by_date["steps"]] == ["2026-09-03"]
        second = _git(record_repo, "log", "--format=%H", "record").split()[1]
        by_hash = lt.trend(record_repo, "record", LEDGER, None, second[:7])
        assert [s["date"] for s in by_hash["steps"]] == ["2026-09-03"]
        assert (by_hash["window"]["live_first"], by_hash["window"]["live_last"]) == (2, 2)
        assert by_hash["window"]["backlog_struck"] == ["DEF-3"]


class TestTags:
    def test_the_latest_snapshots_tags_win(self, lt, record_repo):
        """DEF-3 was filed untagged and tagged only when struck. The split for
        the step that filed it must read the tags the LATEST snapshot carries;
        an earliest-wins bug prints UNTAGGED here (mutation-driven)."""
        steps = lt.trend(record_repo, "record", LEDGER, None)["steps"]
        assert steps[0]["filed_by_audience"] == {"MAINTAINER": 1}
        assert steps[0]["filed_by_population"] == {"HYGIENE": 1}

    def test_an_untagged_row_is_reported_as_untagged_not_guessed(self, lt, record_repo):
        second = _git(record_repo, "log", "--format=%H", "record").split()[1]
        gen = lt._gen()
        st = lt.state(gen, lt.ledger_at(record_repo, second, LEDGER))
        assert st["DEF-3"] == {"struck": False, "population": lt.UNTAGGED, "audience": lt.UNTAGGED}

    def test_a_bolded_cell_on_a_struck_row_is_read_by_lead_token(self, lt, record_repo):
        w = lt.trend(record_repo, "record", LEDGER, None)["window"]
        assert w["churn_by_population"] == {"HYGIENE": 2}  # DEF-5's cell is **HYGIENE**

    def test_a_classed_row_inherits_its_class_tags_in_that_snapshot(self, lt):
        st = lt.state(lt._gen(), _ledger(c1_tags=("HYGIENE", "MAINTAINER")))
        assert st["DEF-1"] == {"struck": False, "population": "HYGIENE", "audience": "MAINTAINER"}


class TestTransitions:
    def test_a_deleted_row_and_a_reopened_row_are_named_and_the_identity_holds(self, lt, transitions_repo):
        report = lt.trend(transitions_repo, "record", LEDGER, None)
        b, c = report["steps"]
        assert b["dropped"] == ["DEF-1"] and b["struck"] == ["DEF-2"] and b["net"] == -2
        assert c["reopened"] == ["DEF-2"] and c["filed"] == [] and c["net"] == +1
        w = report["window"]
        assert (w["live_first"], w["live_last"], w["net"]) == (2, 1, -1)
        assert w["dropped"] == ["DEF-1"] and w["backlog_struck"] == [] and w["reopened"] == []
        assert w["identity_gap"] == 0
        text = lt.render(report, today=date(2026, 9, 5))
        assert "dropped without a strike: 1 ['DEF-1']" in text and "WARN" not in text


class TestTheRatio:
    def _states(self, n_first: int, struck: int, filed_live: int, filed_struck: int):
        first = {f"DEF-{i}": {"struck": False, "population": "LOGIC_BUG", "audience": "ADOPTER"}
                 for i in range(n_first)}
        last = {k: dict(v, struck=i < struck) for i, (k, v) in enumerate(first.items())}
        for j in range(filed_live):
            last[f"NEW-{j}"] = {"struck": False, "population": "HYGIENE", "audience": "MAINTAINER"}
        for j in range(filed_struck):
            last[f"CHURN-{j}"] = {"struck": True, "population": "HYGIENE", "audience": "MAINTAINER"}
        tags = {**first, **last}
        return first, last, tags, set(first)

    def test_the_ratio_carries_its_denominator_in_the_json(self, lt):
        w = lt.window(*self._states(6, 5, 1, 1))
        assert w["denominator"] == 5 and w["replacement_per_drained"] == pytest.approx(0.2)
        assert w["same_step_churn"] == ["CHURN-0"]

    def test_a_small_denominator_refuses_the_ratio(self, lt, record_repo, capsys):
        w = lt.window(*self._states(3, 2, 1, 0))
        assert w["denominator"] == 2 and w["replacement_per_drained"] is None
        assert lt.main(["--repo", str(record_repo)]) == 0
        assert "n too small (1 drained" in capsys.readouterr().out


class TestTheReport:
    def test_text_reconciles_the_struck_column_and_names_the_anchor(self, lt, record_repo):
        report = lt.trend(record_repo, "record", LEDGER, None)
        text = lt.render(report, today=date(2026, 9, 5))
        assert "last snapshot 2 day(s) old" in text
        assert "tags as of snapshot " in text and "the working ledger is not read" in text
        assert "UNTAGGED = tagged after that snapshot, or genuinely untagged" in text
        assert ("the steps' struck column sums to 2 = backlog 1 + churn struck in a later step 1; "
                "1 churn row(s) were filed and struck inside one step") in text
        assert "window: live 2 -> 2 (net +0)" in text and "churn 2" in text and "replacement 1" in text

    def test_json_and_text_agree_on_the_window(self, lt, record_repo, capsys):
        assert lt.main(["--repo", str(record_repo), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["window"]["replacement"] == ["DEF-4"] and payload["skipped_snapshots"] == []
        assert lt.main(["--repo", str(record_repo)]) == 0
        assert "replacement 1 (filed, still open)" in capsys.readouterr().out


class TestItFailsHonestly:
    def test_a_missing_ref_is_a_note_not_a_crash(self, lt, tmp_path, capsys):
        repo = tmp_path / "bare"
        repo.mkdir()
        _git(repo, "init", "-q")
        assert lt.main(["--repo", str(repo)]) == 0
        assert "fewer than two snapshots" in capsys.readouterr().out

    def test_one_snapshot_is_nothing_to_diff(self, lt, tmp_path, capsys):
        repo = _repo(tmp_path, "one")
        _snapshot(repo, _ledger(), "2026-09-01")
        assert lt.main(["--repo", str(repo)]) == 0
        assert "fewer than two snapshots" in capsys.readouterr().out

    def test_a_from_that_matches_nothing_is_an_error_not_a_missing_ref(self, lt, record_repo, capsys):
        """A typo'd hash used to print the missing-ref note and exit 0, which
        reads as 'the instrument does not apply here' (failure-mode pass)."""
        assert lt.main(["--repo", str(record_repo), "--from", "deadbee"]) == 2
        err = capsys.readouterr().err
        assert "no snapshot" in err and "--from 'deadbee'" in err
        assert lt.main(["--repo", str(record_repo), "--since", "2026-09-03", "--from",
                        _git(record_repo, "log", "--format=%h", "record").split()[-1]]) == 2
        assert "on or after --since 2026-09-03" in capsys.readouterr().err

    def test_a_malformed_since_is_a_usage_error(self, lt, record_repo, capsys):
        assert lt.main(["--repo", str(record_repo), "--since", "sept"]) == 2
        assert "YYYY-MM-DD" in capsys.readouterr().err
