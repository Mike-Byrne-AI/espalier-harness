"""TP-52 — statusline contract for ``tools/cc/statusline.py``.

Pins the per-session statusline emission rules that Claude Code
invokes on every refresh:

- Return ``espalier`` alone when no observable state is present
  (no env vars + no blueprint).
- Surface ``MAINT``, ``STOP=full|light``, and the short blueprint
  id + accumulated depth when those signals are present.
- Never raise on malformed or missing blueprint state — the
  statusline is a visibility surface, not a correctness gate; a
  raise would silently hide the harness header from the operator
  for the entire session.

Without this contract a regression in the statusline emitter could
silently strip the ``MAINT`` indicator, leaving the operator
unaware that ``ESPALIER_MAINTENANCE_MODE`` was active and that the
write guards they expected to fire are bypassed for the session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._symlink_support import requires_symlink


REPO_ROOT = Path(__file__).resolve().parent.parent
STATUSLINE = REPO_ROOT / "tools" / "cc" / "statusline.py"


def _run(env: dict | None = None, cwd: Path | None = None) -> str:
    proc_env = {**os.environ}
    # Strip any inherited harness state so each test starts from
    # a known-baseline environment.
    for var in ("ESPALIER_MAINTENANCE_MODE", "ESPALIER_STOP_GATE",
                "ESPALIER_AUDIT_DIR", "CLAUDE_PROJECT_DIR"):
        proc_env.pop(var, None)
    if env:
        proc_env.update(env)
    result = subprocess.run(
        [sys.executable, str(STATUSLINE)],
        env=proc_env,
        cwd=str(cwd or Path.cwd()),
        capture_output=True,
        text=True,
        timeout=5, encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"statusline exited {result.returncode}; stderr={result.stderr!r}"
    )
    return result.stdout.strip()


pytestmark = [pytest.mark.integration]


class TestStatuslineOutput:
    def test_minimal_output_when_no_state(self, tmp_path):
        out = _run(env={"CLAUDE_PROJECT_DIR": str(tmp_path)}, cwd=tmp_path)
        assert out == "espalier", (
            f"expected bare 'espalier' when no state; got {out!r}"
        )

    def test_full_output_with_all_state(self, tmp_path):
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "latest.json").write_text(json.dumps({
            "accumulated_depth": 17,
            "session_id": "abcdef1234",
        }), encoding="utf-8")
        out = _run(env={
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "ESPALIER_MAINTENANCE_MODE": "1",
            "ESPALIER_STOP_GATE": "full",
        }, cwd=tmp_path)
        # Pipe-separated; order is deterministic per statusline.main().
        assert "espalier" in out
        assert "MAINT" in out
        assert "STOP=full" in out
        assert "bp=abcdef" in out
        assert "d17" in out

    def test_malformed_blueprint_graceful(self, tmp_path):
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "latest.json").write_text("not json", encoding="utf-8")
        out = _run(env={"CLAUDE_PROJECT_DIR": str(tmp_path)}, cwd=tmp_path)
        # No bp= piece; no traceback escapes.
        assert out == "espalier", (
            f"expected bare 'espalier' on malformed blueprint; got {out!r}"
        )

    def test_missing_blueprints_dir_graceful(self, tmp_path):
        out = _run(env={"CLAUDE_PROJECT_DIR": str(tmp_path)}, cwd=tmp_path)
        assert out == "espalier"

    def test_stop_gate_light_indicator(self, tmp_path):
        out = _run(env={
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "ESPALIER_STOP_GATE": "light",
        }, cwd=tmp_path)
        assert "STOP=light" in out

    def test_invalid_stop_gate_value_ignored(self, tmp_path):
        out = _run(env={
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "ESPALIER_STOP_GATE": "garbage",
        }, cwd=tmp_path)
        assert out == "espalier", (
            f"expected bare 'espalier' on unrecognised STOP value; got {out!r}"
        )

    def test_maintenance_mode_off_means_no_indicator(self, tmp_path):
        out = _run(env={
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "ESPALIER_MAINTENANCE_MODE": "0",
        }, cwd=tmp_path)
        assert "MAINT" not in out, (
            f"MAINT must only appear when MAINTENANCE_MODE is exactly '1'; "
            f"got {out!r}"
        )


class TestStatuslineHardening:
    """TP-55: statusline resolves CLAUDE_PROJECT_DIR to absolute path
    and reads blueprints with fd-level + size + parse-depth bounds.

    Cases:
    - (a) F4 root.resolve() when env unset
    - (b) BC-027 part 1: symlink to /dev/zero degrades gracefully
    - (c) BC-027 part 2: oversize (>128 KB) blueprint degrades
    - (d) BC-027b: in-content amplification (>4 KB string field)
          rejected by _parse_blueprint_safe
    Writer-side cap (case e) lives in
    tests/test_cognitive_blueprint.py::TestBlueprintWriterCap because
    it targets `cognitive_blueprint._save`, not the statusline reader.
    """

    def test_resolves_root_when_env_unset(self, tmp_path):
        """(a) F4: statusline reads CLAUDE_PROJECT_DIR.resolve() —
        when the env var is unset, cwd is the fallback. Running from
        inside tmp_path with the env stripped must still read the
        blueprint at tmp_path/cc/blueprints/latest.json."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "latest.json").write_text(
            '{"session_id": "abc123", "accumulated_depth": 3}',
            encoding="utf-8",
        )
        # _run strips CLAUDE_PROJECT_DIR by default; cwd=tmp_path
        # exercises the resolve() fallback path.
        out = _run(cwd=tmp_path)
        assert "bp=abc123/d3" in out, (
            f"expected resolved cwd to surface blueprint; got {out!r}"
        )

    @requires_symlink
    def test_symlink_to_device_degrades_gracefully(self, tmp_path):
        """(b) BC-027 part 1: a symlinked latest.json -> /dev/zero
        must NOT hang the prompt. O_NOFOLLOW makes os.open raise
        ELOOP on symlinks; statusline returns bare 'espalier'."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        bp = bp_dir / "latest.json"
        bp.symlink_to("/dev/zero")
        # _run has timeout=5; if the read blocks, this raises.
        out = _run(
            env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
            cwd=tmp_path,
        )
        assert out == "espalier", (
            f"expected bare 'espalier' on symlinked /dev/zero; got {out!r}"
        )

    def test_oversize_blueprint_degrades(self, tmp_path):
        """(c) BC-027 part 2: a 200 KB blueprint exceeds the 128 KB
        cap. fstat.st_size > BLUEPRINT_MAX_SIZE returns None;
        statusline degrades to bare 'espalier'."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        # ~200 KB > 131_072-byte cap.
        (bp_dir / "latest.json").write_text(
            '{"session_id":"x","accumulated_depth":1,"junk":"'
            + "A" * 200_000
            + '"}',
            encoding="utf-8",
        )
        out = _run(
            env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
            cwd=tmp_path,
        )
        assert out == "espalier", (
            f"expected bare 'espalier' on oversize blueprint; got {out!r}"
        )

    def test_parse_bound_rejects_amplification(self, tmp_path):
        """(d) BC-027b: a sub-cap blueprint with a single >4 KB
        string field is rejected by _parse_blueprint_safe even
        though the file passes the byte cap. The walk-depth /
        per-string-bytes guard catches in-content amplification."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        # ~10 KB total file; one 10 KB string field > 4 KB string cap.
        (bp_dir / "latest.json").write_text(
            '{"session_id":"x","accumulated_depth":1,"big":"'
            + "A" * 10_000
            + '"}',
            encoding="utf-8",
        )
        out = _run(
            env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
            cwd=tmp_path,
        )
        assert out == "espalier", (
            f"expected bare 'espalier' on amplification payload; got {out!r}"
        )

    def test_numeric_session_id_does_not_crash(self, tmp_path):
        """TP-152 A-2 (W18): a numeric session_id must be coerced with
        str(), not crash the `[:6]` slice. Pre-fix `(12345 or "")[:6]`
        raised TypeError -> exit 1 + traceback, hiding the header for
        the whole session."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "latest.json").write_text(
            '{"session_id": 12345, "accumulated_depth": 4}',
            encoding="utf-8",
        )
        # _run asserts returncode == 0 (the never-raise contract).
        out = _run(env={"CLAUDE_PROJECT_DIR": str(tmp_path)}, cwd=tmp_path)
        assert "bp=12345" in out, f"expected coerced numeric id; got {out!r}"
        assert "d4" in out

    def test_parse_bound_rejects_deep_nesting(self, tmp_path):
        """(d2) BC-027b depth half: a JSON > MAX_BLUEPRINT_DEPTH
        (10) levels is rejected even if every field is small."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        # 15-level nested list inside a top-level dict value.
        nest = "[" * 15 + "1" + "]" * 15
        (bp_dir / "latest.json").write_text(
            '{"session_id":"x","accumulated_depth":1,"deep":' + nest + '}',
            encoding="utf-8",
        )
        out = _run(
            env={"CLAUDE_PROJECT_DIR": str(tmp_path)},
            cwd=tmp_path,
        )
        assert out == "espalier", (
            f"expected bare 'espalier' on depth-bomb; got {out!r}"
        )
