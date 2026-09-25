"""TP-189-A (OVERCLAIM-2): the auto-reflect pass surfaces surface drift to the
AGENT, not only the operator's stderr.

``_run_reflect`` printed its whole summary to ``sys.stderr`` — debug-log-only on
a PostToolUse event, so the agent never saw the drift the pass found (only an
operator watching raw stderr did). The non-clean branch now also emits a
``hookSpecificOutput.additionalContext`` JSON on stdout (exit 0), which the
pinned protocol (docs/external/cc-hook-protocol.md, 2026-06-02 refresh) confirms
reaches the model. The clean branch stays stderr-only.

Earn-the-red: before the fix ``_run_reflect`` wrote nothing to stdout, so the
drift test's ``json.loads(out)`` raised on an empty string → RED. The clean test
pins that a coherent surface does NOT inject (no mid-flow noise).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path


def _import_reflect_trigger():
    hooks_dir = Path(__file__).parent.parent / "tools" / "cc" / "hooks"
    tools_cc_dir = Path(__file__).parent.parent / "tools" / "cc"
    sys.path.insert(0, str(hooks_dir))
    sys.path.insert(0, str(tools_cc_dir))
    if "reflect_trigger" in sys.modules:
        del sys.modules["reflect_trigger"]
    import reflect_trigger  # type: ignore[import-not-found]
    return reflect_trigger


def _repo_with_reflect_script(tmp_path: Path) -> Path:
    """A root where reflect_protocol.py 'exists' (so _run_reflect proceeds) but
    cognitive_blueprint.py does not (record step is skipped, irrelevant here)."""
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "tools" / "cc" / "reflect_protocol.py").write_text("", encoding="utf-8")
    return tmp_path


def _patch_reflect_report(rt, monkeypatch, report: dict) -> None:
    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr="")
    monkeypatch.setattr(rt.subprocess, "run", fake_run)


def test_run_reflect_emits_additionalcontext_on_drift(monkeypatch, capsys, tmp_path) -> None:
    rt = _import_reflect_trigger()
    root = _repo_with_reflect_script(tmp_path)
    _patch_reflect_report(rt, monkeypatch, {
        "findings": [{"kind": "gap", "severity": "high", "description": "x"}],
        "gap_count": 2, "orphan_count": 1, "files_analyzed": 5,
    })
    rt._run_reflect(root)
    out = capsys.readouterr().out
    payload = json.loads(out)  # RED pre-fix: out was "" → ValueError
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "drift" in payload["hookSpecificOutput"]["additionalContext"].lower()


def test_run_reflect_silent_on_clean_surface(monkeypatch, capsys, tmp_path) -> None:
    rt = _import_reflect_trigger()
    root = _repo_with_reflect_script(tmp_path)
    _patch_reflect_report(rt, monkeypatch, {
        "findings": [], "gap_count": 0, "orphan_count": 0, "files_analyzed": 5,
    })
    rt._run_reflect(root)
    out = capsys.readouterr().out
    assert out.strip() == "", "a clean reflect must not inject into the agent's context"
