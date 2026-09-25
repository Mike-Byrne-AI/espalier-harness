"""Tests for ``espalier._report_io`` — the single guarded owner for the
report-sidecar JSON loader, the "safe" text read, and the harness-plan
loader (TP-204a).

The earn-the-red here is the latent traceback this module fixes: before
TP-204a, ``handoff._load_json`` / ``reflection._load_json`` read
``reports/*.json`` UNGUARDED and ``cleanup._load_plan`` caught only
``JSONDecodeError`` — so a BOM-prefixed / non-UTF-8 / malformed report
tracebacked ``/handoff``, ``espalier reflect``, and (worst) cleanup's
pre-delete path. These tests pin the degrade-not-raise contract at both
the unit (loader) and integration (command) layers.
"""
# pytest-marker: default-unit  (loader-contract + in-process degrade tests; not a grandfather entry)
from __future__ import annotations

import json
from pathlib import Path

from espalier import cleanup, handoff, reflection
from espalier._report_io import load_harness_plan, load_report_json, safe_text

# Bytes that are valid UTF-16 ("{}") but invalid UTF-8 — the exact shape
# of a report saved by a tool that emitted a BOM / wrong encoding.
NON_UTF8 = b"\xff\xfe{\x00}\x00"


class TestLoadReportJson:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert load_report_json(tmp_path / "absent.json") == {}

    def test_valid_dict_is_returned(self, tmp_path: Path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps({"a": 1, "b": [2, 3]}), encoding="utf-8")
        assert load_report_json(f) == {"a": 1, "b": [2, 3]}

    def test_non_dict_json_degrades_to_empty(self, tmp_path: Path):
        f = tmp_path / "r.json"
        f.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert load_report_json(f) == {}

    def test_malformed_json_degrades_to_empty(self, tmp_path: Path):
        f = tmp_path / "r.json"
        f.write_text("{not valid", encoding="utf-8")
        assert load_report_json(f) == {}

    def test_non_utf8_degrades_to_empty(self, tmp_path: Path):
        # The headline earn-the-red: pre-TP-204a this raised UnicodeDecodeError.
        f = tmp_path / "r.json"
        f.write_bytes(NON_UTF8)
        assert load_report_json(f) == {}

    def test_leading_managed_marker_line_is_stripped(self, tmp_path: Path):
        f = tmp_path / "r.json"
        f.write_text("# espalier:managed\n" + json.dumps({"k": "v"}), encoding="utf-8")
        assert load_report_json(f) == {"k": "v"}


class TestSafeText:
    def test_valid_text_is_returned(self, tmp_path: Path):
        f = tmp_path / "t.txt"
        f.write_text("hello\nworld", encoding="utf-8")
        assert safe_text(f) == "hello\nworld"

    def test_non_utf8_uses_replacement(self, tmp_path: Path):
        f = tmp_path / "t.txt"
        f.write_bytes(b"a\xffb")
        # errors="replace" never raises; the bad byte becomes U+FFFD.
        out = safe_text(f)
        assert out.startswith("a") and out.endswith("b")

    def test_oserror_degrades_to_empty(self, tmp_path: Path):
        # Reading a directory raises IsADirectoryError (an OSError) -> "".
        assert safe_text(tmp_path) == ""


class TestLoadHarnessPlan:
    def test_missing_returns_none(self, tmp_path: Path):
        assert load_harness_plan(tmp_path) is None

    def test_valid_dict_is_returned(self, tmp_path: Path):
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"profiles": ["python_library"]}), encoding="utf-8"
        )
        assert load_harness_plan(tmp_path) == {"profiles": ["python_library"]}

    def test_non_dict_returns_none(self, tmp_path: Path):
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps([1, 2]), encoding="utf-8"
        )
        assert load_harness_plan(tmp_path) is None

    def test_non_utf8_returns_none(self, tmp_path: Path):
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "harness_config.json").write_bytes(NON_UTF8)
        assert load_harness_plan(tmp_path) is None


class TestCommandsDegradeNotTraceback:
    """Integration earn-the-red: a non-UTF-8 harness_config.json must
    degrade the hot commands, never traceback (was the TP-204a defect)."""

    def _write_bad_plan(self, root: Path) -> None:
        (root / "reports").mkdir(parents=True, exist_ok=True)
        (root / "reports" / "harness_config.json").write_bytes(NON_UTF8)

    def test_handoff_degrades(self, tmp_path: Path):
        self._write_bad_plan(tmp_path)
        # Pre-fix: UnicodeDecodeError out of handoff._load_json.
        result = handoff.build_surface_handoff(tmp_path)
        assert isinstance(result, dict)

    def test_reflect_degrades(self, tmp_path: Path):
        self._write_bad_plan(tmp_path)
        # Pre-fix: UnicodeDecodeError out of reflection._load_json.
        result = reflection.reflect_repo(tmp_path)
        assert isinstance(result, dict)

    def test_cleanup_dry_run_degrades(self, tmp_path: Path):
        self._write_bad_plan(tmp_path)
        # Pre-fix: UnicodeDecodeError out of cleanup._load_plan on the
        # STATE-CHANGING path (runs before the delete loop).
        result = cleanup.clean_generated_surface(tmp_path, dry_run=True)
        assert isinstance(result, dict)
