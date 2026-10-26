# pytest-marker: default-unit
"""scripts/usage_tail.py: the threshold handoff's instrument, driven in-process
on a synthetic transcript directory whose lines repeat a message across content
blocks. This file pins the instrument's arithmetic (one record per message, the
bucket shares, the cap counterfactual and its restart overhead, the per-day
table, the subagent shape) against hand-computed figures, because a measurement
that drifts silently would mis-state the lever the threshold handoff was built
on; the dedup is the earned red (the first derivation counted every content
block)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "usage_tail.py"


def _load():
    spec = importlib.util.spec_from_file_location("_usage_tail_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_usage_tail_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _record(mid: str, req: str, inp: int, cc: int, cr: int, out: int) -> dict:
    return {"type": "assistant", "requestId": req, "message": {"id": mid, "usage": {
        "input_tokens": inp, "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr,
        "output_tokens": out}}}


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _synthetic(tmp_path: Path) -> Path:
    """Two sessions and one subagent. Session A: 25 messages, each written
    twice (two content blocks), ten at 100k context and fifteen at 400k.
    Session B: 10 messages, under the floor, left out. The subagent: 3."""
    d = tmp_path / "slug"
    a = []
    for i in range(10):
        a += [_record(f"a{i}", f"r{i}", 0, 0, 100_000, 100)] * 2
    for i in range(10, 25):
        a += [_record(f"a{i}", f"r{i}", 0, 0, 400_000, 100)] * 2
    a.append({"type": "user", "message": {"content": "x"}})
    a.append({"type": "assistant", "message": {"content": "no usage"}})
    _write(d / "aaaaaaaa-1.jsonl", a)
    _write(d / "bbbbbbbb-2.jsonl", [_record(f"b{i}", f"q{i}", 0, 0, 50_000, 10) for i in range(10)])
    _write(d / "aaaaaaaa-1" / "subagents" / "agent-1.jsonl",
           [_record("s1", "x1", 0, 40_000, 0, 10), _record("s2", "x2", 0, 0, 60_000, 10), _record("s3", "x3", 0, 0, 90_000, 10)])
    return d


class TestScanTranscript:
    def test_one_record_per_message_across_content_blocks(self, tmp_path):
        mod = _load()
        d = _synthetic(tmp_path)
        turns = mod.scan_transcript(str(d / "aaaaaaaa-1.jsonl"))
        assert len(turns) == 25   # fifty lines, twenty-five messages
        assert turns[0]["cache_read_input_tokens"] == 100_000 and turns[-1]["cache_read_input_tokens"] == 400_000

    def test_records_with_no_ids_are_not_folded_into_one_turn(self, tmp_path):
        mod = _load()
        p = tmp_path / "t.jsonl"
        bare = {"type": "assistant", "message": {"usage": {"input_tokens": 1, "cache_creation_input_tokens": 0,
                                                            "cache_read_input_tokens": 0, "output_tokens": 1}}}
        p.write_text(json.dumps(bare) + "\n" + json.dumps(bare) + "\n", encoding="utf-8")
        assert len(mod.scan_transcript(str(p))) == 2

    def test_a_non_numeric_count_reads_as_zero_not_a_crash(self, tmp_path):
        mod = _load()
        p = tmp_path / "t.jsonl"
        p.write_text(json.dumps(_record("m", "r", "x", None, 3, 4)) + "\n", encoding="utf-8")
        assert mod.scan_transcript(str(p))[0]["input_tokens"] == 0

    def test_the_context_figure_uses_the_hook_reader_s_keys(self):
        # The instrument and the gate it measures agree on what "context" sums.
        mod = _load()
        sys.path.insert(0, str(REPO_ROOT / "tools" / "cc" / "hooks"))
        import _hook_utils
        assert tuple(k for k in mod.USAGE_KEYS if k != "output_tokens") == _hook_utils._USAGE_INPUT_KEYS

    def test_lines_without_usage_or_json_are_skipped(self, tmp_path):
        mod = _load()
        p = tmp_path / "t.jsonl"
        p.write_text('not json\n{"type": "assistant"}\n' + json.dumps(_record("m", "r", 1, 2, 3, 4)) + "\n", encoding="utf-8")
        assert mod.scan_transcript(str(p)) == [{"input_tokens": 1, "cache_creation_input_tokens": 2,
                                                "cache_read_input_tokens": 3, "output_tokens": 4, "day": 0}]


class TestAnalyseDir:
    def test_the_bucket_shares_and_the_floor(self, tmp_path):
        mod = _load()
        d = _synthetic(tmp_path)
        report = mod.analyse_dir(str(d), mod.weights(2.0))
        assert report["sessions"] == 1 and report["turns"] == 25     # session B is under the floor
        # Weighted: ten turns at 100k * 0.1 + 100 * 5 = 10,500 each; fifteen at 400k * 0.1 + 500 = 40,500 each.
        low, high = 10 * 10_500, 15 * 40_500
        total = low + high
        assert abs(report["buckets"]["100-150k"]["weighted_share"] - low / total) < 1e-9
        assert abs(report["buckets"]["300-500k"]["weighted_share"] - high / total) < 1e-9
        assert report["buckets"]["<50k"]["turns"] == 0
        assert abs(report["weighted_total"] - total) < 1e-6

    def test_the_cap_counterfactual_and_the_restart_overhead(self, tmp_path):
        mod = _load()
        d = _synthetic(tmp_path)
        report = mod.analyse_dir(str(d), mod.weights(2.0))
        total = 10 * 10_500 + 15 * 40_500
        # At a 200k cap a 400k turn's cache read is re-priced at an average of 100k: 100k * 0.1 + 500 = 10,500.
        expected = (10 * 10_500 + 15 * 10_500) / total
        c = report["caps"][200_000]
        assert abs(c["counterfactual"] - expected) < 1e-9
        # Peak 400k over a 200k cap: two restarts, each the session's first five turns (5 * 10,500).
        assert c["restarts"] == 2
        assert abs(c["restart_overhead"] - (2 * 5 * 10_500) / total) < 1e-9
        assert abs(c["net"] - (c["counterfactual"] + c["restart_overhead"])) < 1e-12
        assert report["caps"][500_000]["counterfactual"] == 1.0

    def test_the_per_day_table_sums_each_day_s_turns(self, tmp_path):
        mod = _load()
        d = tmp_path / "slug"
        recs = []
        for i in range(25):
            r = _record(f"a{i}", f"r{i}", 0, 0, 10_000, 0)
            r["timestamp"] = "2026-10-25T23:59:00Z" if i < 10 else "2026-10-26T00:01:00Z"
            recs.append(r)
        _write(d / "s.jsonl", recs)
        days = mod.analyse_dir(str(d), mod.weights(2.0))["days"]
        assert days == {"20261025": {"turns": 10, "weighted": 10 * 1000.0}, "20261026": {"turns": 15, "weighted": 15 * 1000.0}}

    def test_the_subagent_shape(self, tmp_path):
        mod = _load()
        d = _synthetic(tmp_path)
        s = mod.analyse_dir(str(d), mod.weights(2.0))["subagents"]
        assert s["runs"] == 1 and s["peak_p50"] == 90_000 and s["first_turn_p50"] == 40_000
        # Three runs: one cache write at 2.0, two cache reads at 0.1, ten output tokens each at 5.
        assert abs(s["weighted_total"] - (40_000 * 2.0 + 60_000 * 0.1 + 90_000 * 0.1 + 3 * 10 * 5)) < 1e-6

    def test_the_cache_write_weight_moves_only_cache_writes(self, tmp_path):
        mod = _load()
        d = _synthetic(tmp_path)
        a = mod.analyse_dir(str(d), mod.weights(1.25))["subagents"]["weighted_total"]
        b = mod.analyse_dir(str(d), mod.weights(2.0))["subagents"]["weighted_total"]
        assert abs((b - a) - 40_000 * 0.75) < 1e-6


class TestMain:
    def test_json_and_text_outputs_and_a_bad_directory(self, tmp_path, capsys):
        mod = _load()
        d = _synthetic(tmp_path)
        assert mod.main([str(d), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["cache_write_weight"] == 2.0 and payload["reports"][0]["sessions"] == 1
        assert mod.main([str(d), "--cache-write-weight", "1.25"]) == 0
        text = capsys.readouterr().out
        assert "cache-write weight 1.25" in text and "300-500k" in text and "subagents: runs 1" in text
        assert mod.main([str(tmp_path / "absent")]) == 2
