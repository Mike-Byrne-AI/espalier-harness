"""Anti-regression: the implement-task merge contract.

Locks the merged command surface. /accomplish, once a compatibility alias for
/implement-task --multi, was retired on 2026-09-28 (roster 18 -> 17, back inside
the advisor's 10-17 band) and must not come back as a command; /implement-task
cannot lose its execution-plan requirement.
"""
from __future__ import annotations

import re
from pathlib import Path

from espalier.surface_contract import CLAUDE_KIND_GLOBS
from tests._surface_expected import EXPECTED_COMMAND_COUNT
from tests.test_doc_source_citations import _RECORD_SURFACE_DOCS

REPO_ROOT = Path(__file__).resolve().parent.parent

IMPLEMENT_TASK = REPO_ROOT / ".claude" / "commands" / "implement-task.md"
RETIRED_ACCOMPLISH = REPO_ROOT / ".claude" / "commands" / "accomplish.md"
TASK_ROUTER = REPO_ROOT / "tools" / "cc" / "hooks" / "task_router.py"
PLAN_GUARD = REPO_ROOT / "tools" / "cc" / "hooks" / "plan_guard.py"
# TP-112: deny() reason prose moved from plan_guard.py inline f-strings
# to _denial_reasons.NO_ACTIVE_PLAN_FILE / _BASH templates. The
# composition still routes through plan_guard; the prose lives next door.
DENIAL_REASONS = REPO_ROOT / "tools" / "cc" / "hooks" / "_denial_reasons.py"
DESIGN_SKILL = REPO_ROOT / ".claude" / "skills" / "design" / "SKILL.md"
ADVISOR = REPO_ROOT / ".claude" / "agents" / "harness-config-advisor.md"

class TestImplementTaskContent:
    def test_exposes_multi_flag(self):
        assert "/implement-task --multi" in IMPLEMENT_TASK.read_text(encoding="utf-8")

    def test_has_focused_mode_section(self):
        assert "Focused mode" in IMPLEMENT_TASK.read_text(encoding="utf-8")

    def test_has_multi_phase_mode_section(self):
        assert "Multi-phase mode" in IMPLEMENT_TASK.read_text(encoding="utf-8")

    def test_focused_mode_creates_execution_plan_before_writes(self):
        text = IMPLEMENT_TASK.read_text(encoding="utf-8")
        assert "execution_plan.py create" in text, (
            "implement-task.md must instruct creation of an execution plan "
            "with execution_plan.py create before source writes"
        )

    def test_multi_mode_preserves_mark_mechanic(self):
        assert "execution_plan.py mark" in IMPLEMENT_TASK.read_text(encoding="utf-8")

    def test_multi_mode_has_status_resume(self):
        assert "execution_plan.py status" in IMPLEMENT_TASK.read_text(encoding="utf-8")

    def test_multi_mode_has_failed_and_passed_keywords(self):
        text = IMPLEMENT_TASK.read_text(encoding="utf-8")
        assert "failed" in text
        assert "passed" in text

    def test_multi_mode_has_resume_keyword(self):
        assert "resume" in IMPLEMENT_TASK.read_text(encoding="utf-8").lower()


class TestAccomplishIsRetired:
    """The alias file is gone, and no SHIPPED surface mentions `/accomplish`:
    the `.claude` kinds (derived from the surface contract, so a new kind
    enrols itself), `.claude/CLAUDE.md`, every doc under docs/ except the
    declared record surfaces, README.md, CLAUDE.md, the rendered cc/ surfaces,
    the adopter template, the dogfooding README, and the hook modules whose
    deny prose carried two sentences naming the alias until 2026-09-28. Any
    mention is forbidden, not only one presenting it as a command: a historical
    note belongs in CHANGELOG.md or on the record ref, neither of which is
    scanned. Every glob must match something, so a moved directory cannot pass
    vacuously. Run red on 2026-09-28 against the tree with the alias present.
    The router tests' negatives stay: they forbid one string's return in a
    file that is not a prose surface here."""

    _FIXED_GLOBS = (
        ".claude/CLAUDE.md", "docs/**/*.md", "README.md", "CLAUDE.md",
        "cc/COMMANDS.md", "cc/LIVE_SURFACE.md", "cc/PACK_MANIFEST.txt",
        "examples/CLAUDE.template.md", "examples/dogfooding/README.md",
        "tools/cc/hooks/*.py",
    )

    @classmethod
    def _surfaces(cls) -> dict[str, list[Path]]:
        globs = [f".claude/{kind}/{pattern}" for kind, pattern in CLAUDE_KIND_GLOBS.items()]
        globs.extend(cls._FIXED_GLOBS)
        return {
            g: [
                p for p in sorted(REPO_ROOT.glob(g))
                if p.is_file() and p.relative_to(REPO_ROOT).as_posix() not in _RECORD_SURFACE_DOCS
            ]
            for g in globs
        }

    def test_the_alias_file_is_gone(self):
        assert not RETIRED_ACCOMPLISH.exists(), "the retired alias came back"

    def test_no_shipped_surface_mentions_the_alias(self):
        surfaces = self._surfaces()
        empty = [g for g, files in surfaces.items() if not files]
        assert not empty, f"a glob matched nothing, so it guards nothing: {empty}"
        files = [p for found in surfaces.values() for p in found]
        assert len(files) >= 80, f"only {len(files)} surfaces found; the set shrank"
        hits = [
            p.relative_to(REPO_ROOT).as_posix()
            for p in files if "/accomplish" in p.read_text(encoding="utf-8")
        ]
        assert not hits, (
            f"a shipped surface mentions the retired alias: {hits}. A historical "
            "note belongs in CHANGELOG.md or on the record ref, neither of which "
            "is scanned; a live surface names /implement-task --multi instead."
        )

    def test_command_count_sits_inside_the_designed_band(self):
        """The band lived in prose in two homes with no mechanical pin: the
        roster reached 18 on 2026-09-28 with every test green, and a human read
        found it. Read the band from the design skill, check the advisor states
        the same numbers, and hold the count inside it. Raising the band is a
        deliberate edit to both prose homes, never a silent bump of the count."""
        skill = re.search(
            r"Count discipline: (\d+)[\u2013-](\d+) commands", DESIGN_SKILL.read_text(encoding="utf-8")
        )
        assert skill, "the design skill no longer states the command band"
        lo, hi = int(skill.group(1)), int(skill.group(2))
        advisor = re.search(
            r"Command count: typical range is (\d+)[\u2013-](\d+)", ADVISOR.read_text(encoding="utf-8")
        )
        assert advisor and (int(advisor.group(1)), int(advisor.group(2))) == (lo, hi), (
            "the advisor and the design skill state different command bands"
        )
        assert lo <= EXPECTED_COMMAND_COUNT <= hi, (
            f"{EXPECTED_COMMAND_COUNT} commands is outside the designed band {lo}-{hi}: "
            "retire one, or raise the band in both prose homes on purpose"
        )


class TestRouterPointsToImplementTaskMulti:
    def test_router_contains_implement_task_multi(self):
        assert "/implement-task --multi" in TASK_ROUTER.read_text(encoding="utf-8")

    def test_router_does_not_present_accomplish_as_primary(self):
        text = TASK_ROUTER.read_text(encoding="utf-8")
        assert "Use /accomplish to create" not in text, (
            "task_router.py must not present /accomplish as the primary command"
        )


class TestPlanGuardMatchesCanonicalCommand:
    def test_plan_guard_mentions_implement_task(self):
        # TP-112: prose now lives in _denial_reasons.py templates that
        # plan_guard composes via deny(). Check both files; either
        # surface satisfies the user-facing-prose intent.
        plan_text = PLAN_GUARD.read_text(encoding="utf-8")
        denial_text = DENIAL_REASONS.read_text(encoding="utf-8")
        assert "/implement-task" in plan_text or "/implement-task" in denial_text

    def test_plan_guard_mentions_multi_flag(self):
        plan_text = PLAN_GUARD.read_text(encoding="utf-8")
        denial_text = DENIAL_REASONS.read_text(encoding="utf-8")
        assert "--multi" in plan_text or "--multi" in denial_text
