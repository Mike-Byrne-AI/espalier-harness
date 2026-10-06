"""TP-189-A (OVERCLAIM-2): the auto-reflect pass surfaces surface drift to the
AGENT, not only the operator's stderr.

``_run_reflect`` printed its whole summary to ``sys.stderr`` — debug-log-only on
a PostToolUse event, so the agent never saw the drift the pass found (only an
operator watching raw stderr did). The non-clean branch now also keeps a
``hookSpecificOutput.additionalContext`` advisory, which the hook prints as the
ONE JSON object on stdout at the end of its run (exit 0; ``_run_main`` ->
``_hook_utils.emit_advisories``) and which the pinned protocol
(docs/external/cc-hook-protocol.md) confirms reaches the model. The clean
branch stays stderr-only: the debug log, by the no-mid-flow-noise decision
the clean test pins.

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
    """A root where reflect_protocol.py and cognitive_blueprint.py 'exist' (so
    _run_reflect proceeds and the record step runs against the faked spawn).
    Without the second, the record step says once that the blueprint path is
    dark -- a seen advisory since the voice repair, and not this test's subject."""
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "tools" / "cc" / "reflect_protocol.py").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "cc" / "cognitive_blueprint.py").write_text("", encoding="utf-8")
    return tmp_path


def _emitted(rt, capsys) -> str:
    """What the hook prints on stdout at the end of its run: the ONE JSON
    object carrying every advisory this run kept (or nothing)."""
    rt._hook_utils.emit_advisories("PostToolUse")
    return capsys.readouterr().out


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
    out = _emitted(rt, capsys)
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
    out = _emitted(rt, capsys)
    assert out.strip() == "", "a clean reflect must not inject into the agent's context"


def test_the_advisory_names_the_first_findings_and_counts_the_rest(capsys) -> None:
    """C62: the model sees only the additionalContext of an exit-0 hook, so the
    advisory names the files it asks the model to review: the first three
    findings, each description capped, then how many more there are."""
    rt = _import_reflect_trigger()
    findings = [
        {"kind": "orphan", "severity": "medium",
         "description": f"docs/n{i}.md is not referenced by any other surface file"}
        for i in range(4)
    ] + [{"kind": "gap", "severity": "low", "description": "x" * 500}]
    rt._render_reflect_report({"findings": findings, "gap_count": 1, "orphan_count": 4,
                               "files_analyzed": 9})
    context = json.loads(_emitted(rt, capsys))["hookSpecificOutput"]["additionalContext"]
    assert all(f"docs/n{i}.md" in context for i in range(3)), context
    assert "docs/n3.md" not in context and "x" * 300 not in context, context
    assert "and 2 more" in context, context
    assert context.isascii(), context

    rt._render_reflect_report({"findings": [{"kind": "gap", "description": "y" * 500}],
                               "gap_count": 1, "orphan_count": 0, "files_analyzed": 1})
    context = json.loads(_emitted(rt, capsys))["hookSpecificOutput"]["additionalContext"]
    assert "[GAP] " + "y" * 197 + "..." in context and "more" not in context, context


def test_a_broken_link_is_named_before_the_orphans_found_ahead_of_it(capsys) -> None:
    """The hook twin lists orphans first and broken links last; naming the first
    three in report order would let four unlinked docs hide the one broken link
    in CLAUDE.md from the model. A non-dict row is skipped, not counted."""
    rt = _import_reflect_trigger()
    findings = [
        {"kind": "orphan", "severity": "medium",
         "description": f"docs/adr-{i}.md is not referenced by any other surface file"}
        for i in range(4)
    ] + ["drifted producer row", {"kind": "gap", "severity": "high",
                                  "description": "CLAUDE.md links docs/gone.md which does not exist"}]
    rt._render_reflect_report({"findings": findings, "gap_count": 1, "orphan_count": 4,
                               "files_analyzed": 7})
    context = json.loads(_emitted(rt, capsys))["hookSpecificOutput"]["additionalContext"]
    first = context.split(" First: ", 1)[1]
    assert first.startswith("[GAP] CLAUDE.md links docs/gone.md"), context
    # five usable findings, three named: the drifted string row is not counted
    assert "and 2 more" in context, context
