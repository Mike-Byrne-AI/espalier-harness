r"""Regression: reflect must not false-flag harness-deployed assets (TP-193 R4).

On a fresh `espalier init` the every-10th-write reflect trigger fired ~16
false-positives about espalier's OWN deployed assets:

  * `.claude/skills/<name>/SKILL.md` reported as orphans (nothing links them);
  * `.claude/agents/*.md` template markers ({mod}, {module}, {Feature}) counted
    as placeholder residue;
  * a documented ${CLAUDE_PROJECT_DIR} env-var reference counted as a placeholder.

The fix adds `.claude/skills/` to DISCOVERY_DIRS, excludes DISCOVERY_DIRS from
the quality-signal scan, and adds a `(?<!\$)` lookbehind so ${ENV} refs are not
counted. These lock that the first-run experience is quiet about harness assets.
"""
from __future__ import annotations

# pytest-marker: default-unit  (pure reflect-function test; not a grandfather entry)

from espalier.reflect_protocol import (
    _count_placeholders,
    detect_quality_signals,
    find_orphans,
)


def test_skill_doc_is_not_flagged_as_orphan():
    # A deployed SKILL.md is discovered by directory scan, not cross-reference;
    # nothing links it, but it must not read as an orphan.
    matrix = {
        "CLAUDE.md": ["ESPALIER_MEMORY.md"],
        "ESPALIER_MEMORY.md": [],
        ".claude/skills/reflect/SKILL.md": [],
    }
    orphans = find_orphans(matrix)
    assert ".claude/skills/reflect/SKILL.md" not in orphans


def test_deployed_agent_template_markers_not_flagged(tmp_path):
    # A deployed agent body carries intentional {module}/{mod} substitution
    # markers; the quality scan must skip discovery dirs entirely.
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "test-writer.md").write_text(
        "# test-writer\nGenerate tests/test_{module}.py for {mod} matching "
        "the {specific_behavior} pattern with real substantive guidance here.\n",
        encoding="utf-8",
    )
    findings = detect_quality_signals(tmp_path)
    assert not any("test-writer.md" in f.description for f in findings), (
        "reflect flagged a deployed agent template as incomplete:\n"
        + "\n".join(f.description for f in findings)
    )


def test_env_var_reference_is_not_a_placeholder():
    # ${CLAUDE_PROJECT_DIR} is shell/env syntax, not a doc-template placeholder.
    assert _count_placeholders("set ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/x.py") == 0
    # ...but a real {placeholder} is still counted (the fix is surgical).
    assert _count_placeholders("fill in {module} here") == 1
