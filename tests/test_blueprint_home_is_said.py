"""The cognitive blueprint lives on one machine, and every surface that names it
says so (DEF-1105).

``init`` gitignores ``cc/blueprints/``, so the chain ``/handoff`` records into
reaches the next session on the same disk and no other: a re-clone, a second
machine or a lost disk starts an empty one. The shipped workflow guide and the
handoff's step 1 called that store durable, and the resume report read an empty
chain as a fresh start. These rows pin the deployed text and the rendered line
to where the reasoning goes and where a decision that must be kept belongs.
"""
# pytest-marker: default-unit  (reads two packaged bodies; renders one report dict and one planted scaffold)
# slow-exempt: one python child running a one-line stub blueprint engine, the rest in-process
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.surface_hygiene import strip_self_host_blocks
from tools.cc.session_resume import assess_repo_state, render_context_report

REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = REPO_ROOT / "espalier" / "assets" / "docs" / "WORKFLOW.md"
_HANDOFF = REPO_ROOT / "espalier" / "assets" / "claude" / "commands" / "handoff.md"


def _section(body: str, heading: str) -> str:
    """The text under ``heading`` up to the next heading of its level or above."""
    lines = body.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    assert start is not None, f"no {heading!r} heading in the body"
    out: list[str] = []
    in_fence = False
    for line in lines[start + 1:]:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        stripped = line.lstrip("#")
        if (not in_fence and line.startswith("#") and stripped.startswith(" ")
                and len(line) - len(stripped) <= level):
            break
        out.append(line)
    return "\n".join(out)


def _first_item(section: str) -> str:
    """The text of the numbered list's item 1, its continuation lines joined."""
    lines = section.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("1. ")), None)
    assert start is not None, "no numbered item 1 in the section"
    item = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith("   "):
            break
        item.append(line.strip())
    return " ".join(item)


@pytest.mark.contract
class TestTheShippedTextSaysTheBlueprintIsPerMachine:
    def test_the_workflow_guide_says_where_the_handoffs_reasoning_goes(self):
        body = strip_self_host_blocks(_WORKFLOW.read_text(encoding="utf-8"), source=str(_WORKFLOW))
        item = _first_item(_section(body, "## Ending a session"))
        assert "this machine" in item, item
        assert "gitignore" in item, item
        assert "ESPALIER_MEMORY.md" in item, item
        assert "durable reasoning" not in item, item

    def test_the_handoffs_step_one_sends_a_kept_decision_off_the_machine(self):
        body = strip_self_host_blocks(_HANDOFF.read_text(encoding="utf-8"), source=str(_HANDOFF))
        step = _section(body, "## 1. Capture reasoning")
        assert "per-machine" in step, step[:600]
        assert "cc/blueprints/" in step, step[:600]
        assert "ESPALIER_MEMORY.md" in step, step[:600]
        assert "second machine" in step, step[:600]

    def test_the_self_host_record_branch_stays_out_of_the_adopters_step_one(self):
        body = strip_self_host_blocks(_HANDOFF.read_text(encoding="utf-8"), source=str(_HANDOFF))
        step = _section(body, "## 1. Capture reasoning")
        assert "record branch" not in step and "refs/heads/record" not in step, step[:600]


class TestTheResumeReadsAnEmptyChainAsThisMachines:
    def test_a_missing_chain_is_said_to_be_this_machines(self):
        text = render_context_report({"blueprint": {"status": "missing"}})
        last = next((line for line in text.splitlines() if line.startswith("LAST:")), "")
        assert "no blueprint chain on this machine" in last, last
        assert "gitignored" in last, last

    def test_an_engine_that_finds_no_chain_reads_as_this_machines(self, tmp_path):
        """The engine's own empty-chain answer -- `No blueprint found.` on stderr,
        exit 2 (cognitive_blueprint.cmd_load) -- is the one failure that means the
        chain is absent here, so it alone keeps the per-machine line."""
        _plant_engine(tmp_path, "import sys\nprint('No blueprint found.', file=sys.stderr)\nsys.exit(2)\n")
        report = assess_repo_state(tmp_path)
        assert report["blueprint"]["status"] == "missing", report["blueprint"]
        assert "no blueprint chain on this machine" in _last(report), _last(report)

    @pytest.mark.parametrize("body", [
        "raise ImportError('a sibling module is gone')\n",
        "import sys\nsys.exit(1)\n",
        "# prints nothing and exits 0\n",
    ], ids=["raises", "exits-nonzero", "prints-nothing"])
    def test_an_engine_that_fails_is_named_never_read_as_an_empty_chain(self, tmp_path, body):
        """An engine that crashes (an upgrade left a sibling import broken) while
        the chain is on disk used to read as `no blueprint chain on this machine`,
        a cause the code never checked: the line now says the engine failed and
        where to look."""
        _plant_engine(tmp_path, body)
        report = assess_repo_state(tmp_path)
        assert report["blueprint"]["status"] == "error", report["blueprint"]
        last = _last(report)
        assert "no blueprint chain on this machine" not in last, last
        assert "tools/cc/cognitive_blueprint.py" in last and "failed" in last, last

    def test_the_real_engine_answers_an_empty_chain_as_the_resume_reads_it(self, monkeypatch, capsys):
        """The contract the empty-chain row stubs, held to the engine itself."""
        from tools.cc import cognitive_blueprint as engine
        monkeypatch.setattr(engine, "_load_latest", lambda: None)
        with pytest.raises(SystemExit) as stop:
            engine.cmd_load(as_json=True)
        assert stop.value.code == 2, stop.value.code
        assert "No blueprint found." in capsys.readouterr().err


def _plant_engine(root: Path, body: str) -> None:
    (root / "tools" / "cc").mkdir(parents=True)
    (root / "tools" / "cc" / "cognitive_blueprint.py").write_text(body, encoding="utf-8")


def _last(report: dict) -> str:
    return next((line for line in render_context_report(report).splitlines()
                 if line.startswith("LAST:")), "")
