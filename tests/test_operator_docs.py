"""Anti-regression: operator docs stay repaired (Pack 6 Task 6-C / Pack 17).

Pack 2 purged phantom references (convention-monitor agent, /diff-review
command) from the operator-facing docs. These tests lock that in: any future
edit that reintroduces the stale string will fail loudly.

Pack 17 adds surface-truth regression tests: disk counts must match README
claims, phantom WORKTREE_LANES.md must not appear in current-facing surfaces.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier.managed_paths import self_host_managed_paths
from espalier.surface_contract import (
    classify_release_path,
    get_indexed_doc_relpaths,
    get_public_doc_relpaths,
)
from tests._git_oracle import require_tracked_paths
from tests._surface_expected import CONTRACT_CEILINGS


REPO_ROOT = Path(__file__).resolve().parent.parent

OPERATOR_DOCS = (
    REPO_ROOT / "cc" / "LIVE_SURFACE.md",
    REPO_ROOT / "docs" / "CHEAT-SHEET.md",
    REPO_ROOT / "docs" / "TASK_RECIPES.md",
)

PHANTOM_STRINGS = (
    "convention-monitor",  # phantom agent removed in Pack 2
    "/diff-review",         # phantom command removed in Pack 2
)

REAL_AGENT_NAMES = (
    "repo-analyst",
    "harness-config-advisor",
    "docs-maintainer",
    "architecture-analyst",
    "code-reviewer",
    "test-writer",
)


@pytest.mark.parametrize("doc", OPERATOR_DOCS, ids=lambda p: p.name)
class TestOperatorDocsAntiRegression:
    def test_doc_exists(self, doc: Path):
        assert doc.exists(), f"Operator doc missing: {doc}"

    def test_doc_not_empty(self, doc: Path):
        content = doc.read_text(encoding="utf-8")
        assert content.strip(), f"Operator doc is empty: {doc}"

    def test_no_phantom_strings(self, doc: Path):
        content = doc.read_text(encoding="utf-8")
        for phantom in PHANTOM_STRINGS:
            assert phantom not in content, (
                f"{doc.name}: phantom reference '{phantom}' reappeared "
                "(Pack 2 purged it — if this is intentional, update the "
                "PHANTOM_STRINGS list in this test)"
            )

    def test_mentions_at_least_one_real_agent(self, doc: Path):
        content = doc.read_text(encoding="utf-8")
        found = [name for name in REAL_AGENT_NAMES if name in content]
        assert found, (
            f"{doc.name}: no real agent name found — doc may no longer "
            f"describe the live surface. Expected at least one of: "
            f"{REAL_AGENT_NAMES}"
        )


# ---------------------------------------------------------------------------
# Surface-truth regression tests (Pack 17)
# ---------------------------------------------------------------------------

CURRENT_FACING_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "CLAUDE.md",
    "docs/CONVENTIONS.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
    "cc/LIVE_SURFACE.md",
    "cc/COMMANDS.md",
    "espalier/managed_paths.py",
    "espalier/recovery.py",
    "espalier/reflect_protocol.py",
    "tools/cc/reflect_protocol.py",
    "tools/cc/hooks/post_write_check.py",
]


class TestDiskSurfaceCounts:
    def test_agent_count_on_disk(self):
        from tests._surface_expected import EXPECTED_AGENT_COUNT_MIN
        agents = list((REPO_ROOT / ".claude" / "agents").glob("*.md"))
        assert len(agents) >= EXPECTED_AGENT_COUNT_MIN, (
            f"Expected at least {EXPECTED_AGENT_COUNT_MIN} agent files (universal floor), "
            f"found {len(agents)}: {[a.name for a in agents]}"
        )

    def test_command_count_on_disk(self):
        from tests._surface_expected import EXPECTED_COMMAND_COUNT
        commands = list((REPO_ROOT / ".claude" / "commands").glob("*.md"))
        assert len(commands) == EXPECTED_COMMAND_COUNT, (
            f"Expected {EXPECTED_COMMAND_COUNT} command files, found {len(commands)}: "
            f"{[c.name for c in commands]}"
        )


class TestReadmeSurfaceClaims:
    def _readme(self) -> str:
        return (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    def _actual_counts(self) -> tuple[int, int]:
        agents = len(list((REPO_ROOT / ".claude" / "agents").glob("*.md")))
        commands = len(list((REPO_ROOT / ".claude" / "commands").glob("*.md")))
        return agents, commands

    def test_readme_reports_correct_agent_count(self):
        agents, _ = self._actual_counts()
        expected = f"{agents} governance agents"
        assert expected in self._readme(), (
            f"README.md does not contain '{expected}' — update the agent count claim"
        )

    def test_readme_reports_correct_command_count(self):
        _, commands = self._actual_counts()
        expected = f"{commands} slash commands"
        assert expected in self._readme(), (
            f"README.md does not contain '{expected}' — update the command count claim"
        )

    def test_readme_has_no_stale_agent_count(self):
        assert "8 governance agents" not in self._readme()

    def test_readme_has_no_stale_command_count(self):
        assert "22 slash commands" not in self._readme()
        assert "18 slash commands" not in self._readme()
        assert "16 slash commands" not in self._readme()

    def test_readme_has_no_worktree_lanes(self):
        assert "WORKTREE_LANES.md" not in self._readme()


class TestPhantomWorktreeLanes:
    def test_worktree_lanes_absent_from_current_facing_files(self):
        found_in: list[str] = []
        for rel in CURRENT_FACING_FILES:
            path = REPO_ROOT / rel
            if not path.exists():
                continue
            if "WORKTREE_LANES" in path.read_text(encoding="utf-8"):
                found_in.append(rel)
        assert not found_in, (
            "WORKTREE_LANES.md reference found in current-facing files: "
            + ", ".join(found_in)
        )

    def test_worktree_lanes_not_in_self_host_managed_paths(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert "WORKTREE_LANES.md" not in paths


# ---------------------------------------------------------------------------
# OSS readiness tests (Pack 20)
# ---------------------------------------------------------------------------


class TestReadmeOSSReadiness:
    def test_readme_has_30_second_demo(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "30-Second Demo" in readme or "30-second demo" in readme.lower(), (
            "README.md must have a 30-second demo section"
        )


class TestRequiredDocsExist:
    _REQUIRED = [
        "README.md", "CONTRIBUTING.md", "CLAUDE.md", "docs/CONVENTIONS.md",
        "docs/CHEAT-SHEET.md", "docs/TASK_RECIPES.md", "docs/INSTALL-CI.md",
        "SECURITY.md", "CHANGELOG.md", "LICENSE", "pyproject.toml",
    ]

    def test_all_required_docs_exist(self):
        missing = [r for r in self._REQUIRED if not (REPO_ROOT / r).exists()]
        assert not missing, f"Required docs missing: {missing}"


class TestReleaseArtifactDocs:
    def test_contributing_mentions_release_command(self):
        text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "release-pack" in text or "pre-release" in text, (
            "CONTRIBUTING.md must document how to build release artifacts with espalier"
        )

    def test_cheatsheet_mentions_release_command(self):
        text = (REPO_ROOT / "docs" / "CHEAT-SHEET.md").read_text(encoding="utf-8")
        assert "release-pack" in text or "pre-release" in text, (
            "docs/CHEAT-SHEET.md must document release artifact command (not manual zip)"
        )


class TestPostCompactDocsTruth:
    """PostCompact docs must not claim context reinjection."""

    _OVERCLAIM = "Re-injects critical context"

    def test_live_surface_no_reinjection_overclaim(self):
        text = (REPO_ROOT / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        assert self._OVERCLAIM not in text, (
            "cc/LIVE_SURFACE.md still claims PostCompact re-injects context"
        )

    def test_harness_config_no_reinjection_overclaim(self):
        text = (REPO_ROOT / "espalier" / "harness_config.py").read_text(encoding="utf-8")
        assert self._OVERCLAIM not in text, (
            "espalier/harness_config.py still claims PostCompact re-injects context"
        )


class TestStopGateModeDocs:
    """Public docs must explain how to opt into the full Stop pytest gate."""

    def test_stop_gate_full_mode_documented(self):
        candidates = [
            REPO_ROOT / "README.md",
            REPO_ROOT / "docs" / "SHARP_EDGES.md",
            REPO_ROOT / "docs" / "CHEAT-SHEET.md",
        ]
        text = "\n".join(
            p.read_text(encoding="utf-8") for p in candidates if p.exists()
        )
        assert "ESPALIER_STOP_GATE" in text, (
            "At least one operator doc must mention the ESPALIER_STOP_GATE env var"
        )
        assert "full" in text, (
            "At least one operator doc must mention the 'full' opt-in value"
        )

    def test_live_surface_not_claiming_pytest_first(self):
        text = (REPO_ROOT / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        assert "Five-gate sequence: tests" not in text, (
            "cc/LIVE_SURFACE.md still claims Stop runs tests first by default"
        )


class TestAdoptingDocLinked:
    def test_adopting_doc_exists_and_is_linked(self):
        assert (REPO_ROOT / "docs" / "ADOPTING.md").is_file()
        quickstart = (REPO_ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
        doc_index = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        assert "ADOPTING.md" in quickstart, "QUICKSTART.md must link to ADOPTING.md"
        assert "ADOPTING.md" in doc_index, "docs/README.md index must list ADOPTING.md"


class TestDocIndexCompleteness:
    """docs/CLAUDE.md asserts `README.md` is the index: it maps every doc.
    Enforce that for the PUBLIC top-level ``docs/`` set: every tracked
    ``docs/*.md`` that ``classify_release_path`` calls ``public`` is linked
    from ``docs/README.md``, minus the exemptions declared below, each with
    its reason. A shipped, publicly-classified doc the index never mentions
    makes the index read as aspirational (TP-366 1-H).

    The population is derived from git, not read from
    ``get_indexed_doc_relpaths()`` (the 2026-09-22 change). That set is
    AUDITED-minus-internal -- ten of the thirty-one public top-level docs on
    2026-09-22 -- so a public doc outside the audited set
    (``docs/CLASSIFIER_FALSE_POSITIVES.md``, linked from nowhere but the memory
    file) shipped unindexed while this class was green. Measured that day:
    35 tracked, 31 public, 5 unlinked, of which two were real gaps and three are
    the exemptions below. ``TestIndexedDocsAreShippable`` still pins the
    INDEXED set's derivation; this class no longer reads it.

    Scoped to top-level ``docs/`` deliberately: the two ROOT public docs
    (``README.md``, ``CONTRIBUTING.md``) are documented known-gaps -- linking
    them into ``docs/README.md`` is the docs-map change TP-366 scope-out
    bullet 2 forbids -- and ``docs/sharp-edges/`` has its own index. Links in
    ``docs/README.md`` are relative to ``docs/``, so a ``docs/<NAME>.md`` entry
    is linked as ``[<NAME>.md](<NAME>.md)``; match the link *target*
    ``](<NAME>.md)`` so a bare prose mention does not false-pass.
    """

    # Public top-level docs the index deliberately does not link -- each with
    # the reason, and each must still be a live tracked public doc (a dead
    # exemption is a silent widening; the row below reds on one).
    INDEX_EXEMPT: dict[str, str] = {
        "docs/README.md": "the index itself",
        "docs/CLAUDE.md": (
            "the folder-ladder file the harness injects on entry to docs/; "
            "a reader reaches it through the ladder, not the index"
        ),
        "docs/STANDING_PRINCIPLES.aliases.md": (
            "a machine-read alias table for the recall engine, the sidecar of "
            "STANDING_PRINCIPLES.md, which IS linked"
        ),
    }

    @staticmethod
    def _public_top_level_docs() -> list[str]:
        tracked = require_tracked_paths(
            REPO_ROOT, "docs/*.md", minimum=20, what="tracked docs/*.md"
        )
        return sorted(
            rp for rp in tracked
            if rp.count("/") == 1 and classify_release_path(rp) == "public"
        )

    @staticmethod
    def _unlinked(doc_index: str, population: list[str], exempt: dict[str, str]) -> list[str]:
        return [
            rp for rp in population
            if rp not in exempt and f"]({Path(rp).name})" not in doc_index
        ]

    def test_every_public_top_level_doc_is_linked_from_index(self):
        doc_index = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        population = self._public_top_level_docs()
        # Non-vacuity floor: 31 on 2026-09-22. A collapsed population passes
        # `not missing` while checking nothing.
        assert len(population) >= 25, population
        missing = self._unlinked(doc_index, population, self.INDEX_EXEMPT)
        assert not missing, (
            "docs/README.md (the doc index, per docs/CLAUDE.md) does not link "
            f"these publicly-classified top-level docs/ files: {missing}. Add a "
            "table row linking each by basename, or exempt it in INDEX_EXEMPT "
            "with a reason."
        )

    def test_every_exemption_names_a_live_public_doc_and_a_reason(self):
        assert len(self.INDEX_EXEMPT) <= CONTRACT_CEILINGS["doc-index-exempt"], (
            "INDEX_EXEMPT grew past its ceiling: link the doc from the index instead "
            "of exempting it (tests/_surface_expected.py::CONTRACT_CEILINGS)"
        )
        population = set(self._public_top_level_docs())
        for rp, why in self.INDEX_EXEMPT.items():
            assert why.strip(), f"{rp} is exempted with no reason"
            assert rp in population, (
                f"{rp} is exempted but is not a tracked public top-level doc "
                "any more -- a dead exemption; delete it"
            )

    def test_an_unlinked_public_doc_is_named(self):
        """Earn the red (the survivor's own mutation): unlink TROUBLESHOOTING.md
        in a scratch copy of the index and the row names exactly it."""
        doc_index = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        assert "](TROUBLESHOOTING.md)" in doc_index, "the index lost its TROUBLESHOOTING row"
        mutated = doc_index.replace("](TROUBLESHOOTING.md)", "](TROUBLESHOOTING.md.gone)")
        missing = self._unlinked(mutated, self._public_top_level_docs(), self.INDEX_EXEMPT)
        assert missing == ["docs/TROUBLESHOOTING.md"], missing


class TestIndexedDocsAreShippable:
    """The INDEXED set must never contain an ``internal``-classified doc.

    ``get_indexed_doc_relpaths()`` derives INDEXED from AUDITED by dropping
    ``internal`` entries. If that derivation is ever replaced by a hand-kept
    copy of ``_PUBLIC_DOC_RELPATHS`` -- the declared-population shape §C1
    catalogues -- this goes red instead of the failure surfacing two layers
    away as a dangling link inside a built artifact.

    Earned red: reverting ``get_indexed_doc_relpaths`` to
    ``return _PUBLIC_DOC_RELPATHS`` fails this with
    ``docs/RELEASE_CHECKLIST.md`` named.
    """

    def test_no_indexed_doc_classifies_internal(self):
        leaked = sorted(
            rel for rel in get_indexed_doc_relpaths()
            if classify_release_path(rel) == "internal"
        )
        assert not leaked, (
            "get_indexed_doc_relpaths() returned internal-classified docs: "
            f"{leaked}. docs/README.md would be required to link them, and that "
            "link 404s in the release archive and the sdist. INDEXED must stay "
            "DERIVED from AUDITED, not hand-copied."
        )

    def test_indexed_is_a_subset_of_audited(self):
        audited = set(get_public_doc_relpaths())
        assert set(get_indexed_doc_relpaths()) <= audited, (
            "INDEXED must be a strict narrowing of AUDITED — a doc the index "
            "advertises but nothing audits is the inverse defect."
        )

    def test_derivation_drops_internal_regardless_of_live_population(
        self, monkeypatch
    ):
        """The two tests above only bite while some AUDITED row classifies
        `internal` — today exactly one does. Delete that row and both go
        vacuously green, and the next 'simplify this to return
        _PUBLIC_DOC_RELPATHS' refactor is green too, so both halves evaporate
        and the failure resurfaces as a 404 inside a built artifact.

        This one is population-independent: it feeds a synthetic AUDITED set, so
        it fails on a broken derivation whatever the live list happens to hold.
        """
        from espalier import surface_contract

        monkeypatch.setattr(
            surface_contract,
            "_PUBLIC_DOC_RELPATHS",
            ("README.md", "docs/RELEASE_FINDINGS_LEDGER.md"),
        )
        assert surface_contract.classify_release_path(
            "docs/RELEASE_FINDINGS_LEDGER.md"
        ) == "internal", "fixture drifted: pick another known-internal doc"
        assert surface_contract.get_indexed_doc_relpaths() == ("README.md",), (
            "get_indexed_doc_relpaths() must DERIVE the indexed set by dropping "
            "internal-classified entries, not return AUDITED unchanged."
        )


class TestConventionsNameTheAtomicWriteGate:
    """The convention page licensed a raw one-shot ``Path.write_text`` for
    a day after the census that reds on it landed (both reviewers,
    2026-09-11). Deleting the gate, or renaming it, must red the page."""

    def test_conventions_point_at_the_census_class(self):
        text = (REPO_ROOT / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
        assert "TestEveryEngineWriteOfAdopterStateIsAtomic" in text
        assert "fine for one-shot writes" not in text
        import tests.test_atomic_io as gate
        assert hasattr(gate, "TestEveryEngineWriteOfAdopterStateIsAtomic")


# ── The epistemic-partnership doc names only built checkpoints ──────────────

_SPEEDBUMP_SOURCE = REPO_ROOT / "tools" / "cc" / "hooks" / "_speedbump.py"
# A checkpoint id in prose: backticked, hyphens allowed (`CP-MCP-SIDEEFFECT`).
_CP_ID_RE = re.compile(r"`(CP-[A-Z][A-Z-]*)`")
# A checkpoint the speed-bump DEFINES: the `id="CP-..."` constructor argument,
# never a mention in a comment -- a retired checkpoint's explanatory comment
# would otherwise keep it in the roster (driven by both reviews, 2026-09-22).
_CP_DEFINITION_RE = re.compile(r'id="(CP-[A-Z][A-Z-]*)"')


def _speedbump_roster(source: str | None = None) -> frozenset[str]:
    """Every checkpoint id the speed-bump defines, derived from its source."""
    text = _SPEEDBUMP_SOURCE.read_text(encoding="utf-8") if source is None else source
    return frozenset(_CP_DEFINITION_RE.findall(text))


def _cp_ids_named_in(text: str) -> list[str]:
    return _CP_ID_RE.findall(text)


class TestEpistemicPartnershipNamesOnlyBuiltCheckpoints:
    """``docs/epistemic-partnership.md`` §"Which principles wire" names a built
    checkpoint by its backticked ``CP-`` id and marks an unbuilt one deferred,
    in words.

    Until 2026-09-22 the section said "That wiring now exists" and then named,
    with the definite article, a task-fan-out checkpoint, a clean-review
    checkpoint and a record-commitment checkpoint the tree does not contain,
    beside the post-compact and release checkpoints that do (``DEF-656``). The
    roster is derived from ``tools/cc/hooks/_speedbump.py``, so a checkpoint
    retired there reds the sentence that still names it, and an unbuilt one
    must never be written as a ``CP-`` id at all.
    """

    DOC = REPO_ROOT / "docs" / "epistemic-partnership.md"

    def test_every_named_checkpoint_id_is_in_the_speedbump_roster(self):
        roster = _speedbump_roster()
        assert len(roster) >= 5, roster  # nine on 2026-09-22
        named = _cp_ids_named_in(self.DOC.read_text(encoding="utf-8"))
        assert named, (
            "the wiring section names no CP id -- it must name the built "
            "checkpoints by id so this row can check them"
        )
        unknown = sorted(set(named) - roster)
        assert not unknown, (
            f"docs/epistemic-partnership.md names checkpoint ids the speed-bump "
            f"does not define: {unknown}. Roster: {sorted(roster)}. Mark an "
            "unbuilt checkpoint '(not built -- deferred)' in words, never as a "
            "CP- id."
        )

    def test_a_checkpoint_named_only_in_a_comment_is_not_in_the_roster(self):
        """A retired checkpoint leaves its explanatory comment behind; the roster
        reads definitions, so the doc sentence still naming it reds."""
        src = '# CP-GONE was retired 2026-01-01 because ...\nCheckpoint(\n    id="CP-KEPT",\n)\n'
        assert _speedbump_roster(src) == frozenset({"CP-KEPT"})

    def test_a_hyphenated_id_is_read_whole_on_both_sides(self):
        roster = _speedbump_roster()
        assert "CP-MCP-SIDEEFFECT" in roster and "CP-MCP" not in roster, sorted(roster)
        assert _cp_ids_named_in("built as `CP-MCP-SIDEEFFECT`.") == ["CP-MCP-SIDEEFFECT"]
        assert sorted(set(_cp_ids_named_in("built as `CP-MCP`.")) - roster) == ["CP-MCP"]

    def test_an_unbuilt_id_is_named(self):
        """Earn the red: a planted ``CP-CLEANREVIEW`` -- the id ``DEF-656``'s
        probe counts, still zero in the tree -- is reported by name while the
        built id beside it is not."""
        roster = _speedbump_roster()
        assert "CP-CLEANREVIEW" not in roster and "CP-RELEASE" in roster
        planted = "the clean-review checkpoint (`CP-CLEANREVIEW`) and `CP-RELEASE`."
        unknown = sorted(set(_cp_ids_named_in(planted)) - roster)
        assert unknown == ["CP-CLEANREVIEW"], unknown
