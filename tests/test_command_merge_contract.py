"""Anti-regression: implement-task/accomplish merge contract.

Locks the merged command surface so /accomplish cannot silently drift back into
a second independent workflow and /implement-task cannot lose its execution-plan
requirement.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

IMPLEMENT_TASK = REPO_ROOT / ".claude" / "commands" / "implement-task.md"
ACCOMPLISH = REPO_ROOT / ".claude" / "commands" / "accomplish.md"
TASK_ROUTER = REPO_ROOT / "tools" / "cc" / "hooks" / "task_router.py"
PLAN_GUARD = REPO_ROOT / "tools" / "cc" / "hooks" / "plan_guard.py"
# TP-112: deny() reason prose moved from plan_guard.py inline f-strings
# to _denial_reasons.NO_ACTIVE_PLAN_FILE / _BASH templates. The
# composition still routes through plan_guard; the prose lives next door.
DENIAL_REASONS = REPO_ROOT / "tools" / "cc" / "hooks" / "_denial_reasons.py"

_PUBLIC_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "CHEAT-SHEET.md",
    REPO_ROOT / "docs" / "TASK_RECIPES.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "cc" / "COMMANDS.md",
    REPO_ROOT / "cc" / "LIVE_SURFACE.md",
]


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


class TestAccomplishAlias:
    def test_accomplish_mentions_implement_task_multi(self):
        assert "/implement-task --multi" in ACCOMPLISH.read_text(encoding="utf-8")

    def test_accomplish_uses_alias_language(self):
        text = ACCOMPLISH.read_text(encoding="utf-8").lower()
        assert "alias" in text or "compatibility" in text, (
            "accomplish.md must use 'alias' or 'compatibility' language"
        )

    def test_accomplish_does_not_have_independent_phase_headings(self):
        text = ACCOMPLISH.read_text(encoding="utf-8")
        independent_headings = ["## Phase 1", "## Phase 2", "## Phase 3", "## Phase 4"]
        for heading in independent_headings:
            assert heading not in text, (
                f"accomplish.md must not define an independent workflow ({heading!r} found). "
                "Use implement-task.md for the full workflow."
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


class TestDocsDoNotPresentAccomplishAsPrimary:
    # Patterns that indicate /accomplish is presented as a primary command
    # (not as an alias/compatibility note). Must appear adjacent to /accomplish.
    _FORBIDDEN_ACCOMPLISH_CONTEXTS = [
        "routes toward /accomplish",
        "Use /accomplish to create",
        "primary task command is /accomplish",
    ]

    def _check_doc(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        violations = []
        for pattern in self._FORBIDDEN_ACCOMPLISH_CONTEXTS:
            if pattern in text:
                violations.append(f"{path.name}: contains forbidden pattern {pattern!r}")
        return violations

    def test_no_doc_presents_accomplish_as_primary(self):
        all_violations: list[str] = []
        for doc in _PUBLIC_DOCS:
            all_violations.extend(self._check_doc(doc))
        assert not all_violations, "\n".join(all_violations)
