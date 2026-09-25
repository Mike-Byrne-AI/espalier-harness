"""espalier init deploy contract + shipped-asset hygiene.

``espalier init`` deploys the full packaged surface — 7 agents, 17
commands, 9 skills — to every consumer. The harness-dev deploy tier was
retired: there is no longer a common/harness-dev split, an
``--include-harness-dev`` flag, or self-host auto-detection of a tier.
Every shipped asset goes to every repo.

The hygiene contract pins that no shipped command / agent / skill body
leaks internal pack IDs (``TP-NN`` / ``BC-NNN``) or self-host-only
vocabulary into adopter installs.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from espalier.cli import cmd_init
from espalier.surface_hygiene import (
    FORBIDDEN_SELF_HOST_PATTERNS,
    SPECIFIC_ID_RE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-app"\n', encoding="utf-8",
    )
    (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
    return tmp_path


def _run_init(repo: Path) -> int:
    args = argparse.Namespace(repo=str(repo), config=None)
    return cmd_init(args)


def _count_assets(repo: Path) -> dict[str, int]:
    return {
        "agents": len(list((repo / ".claude" / "agents").glob("*.md"))),
        "commands": len(list((repo / ".claude" / "commands").glob("*.md"))),
        "skills": len(list((repo / ".claude" / "skills").rglob("SKILL.md"))),
    }


class TestInitDeploy:
    def test_init_deploys_7_agents_17_commands_9_skills(
        self, tmp_path: Path
    ) -> None:
        """init deploys the full packaged surface. The harness-dev tier
        was retired, so /integrity now ships to every repo: commands
        14 -> 15. (TP-210 had previously promoted the task-pack workflow
        commands + the blueprint-authoring/hook-authoring skills.)
        TP-214 added /read-summary: 15 -> 16. TP-233b added /strengthen: 16 -> 17."""
        repo = _make_repo(tmp_path)
        _run_init(repo)
        counts = _count_assets(repo)
        assert counts == {"agents": 7, "commands": 17, "skills": 9}

    def test_init_does_not_deploy_retired_surfaces(
        self, tmp_path: Path
    ) -> None:
        """release-verifier (agent) and verify-release (skill) were
        retired with the harness-dev tier; init must never deploy them."""
        repo = _make_repo(tmp_path)
        _run_init(repo)
        assert not (repo / ".claude" / "agents" / "release-verifier.md").exists()
        assert not (
            repo / ".claude" / "skills" / "verify-release" / "SKILL.md"
        ).exists()

    def test_init_deploys_pack_authoring_commands(
        self, tmp_path: Path
    ) -> None:
        """The pack-workflow commands ship to every repo, including the
        /integrity command (previously harness-dev-only)."""
        repo = _make_repo(tmp_path)
        _run_init(repo)
        for cmd in (
            "implement-pack.md", "scope-check.md", "audit-accuracy.md",
            "integrity.md",
        ):
            assert (repo / ".claude" / "commands" / cmd).exists(), (
                f"init should deploy command {cmd}"
            )

    def test_init_deploys_pack_authoring_skills(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        _run_init(repo)
        for skill in ("blueprint-authoring", "hook-authoring"):
            assert (repo / ".claude" / "skills" / skill / "SKILL.md").exists(), (
                f"init should deploy skill {skill}"
            )

    def test_init_deploys_expected_agents(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        _run_init(repo)
        agents_dir = repo / ".claude" / "agents"
        for present in (
            "architecture-analyst.md",
            "code-reviewer.md",
            "docs-maintainer.md",
            "failure-mode-reviewer.md",
            "harness-config-advisor.md",
            "repo-analyst.md",
            "test-writer.md",
        ):
            assert (agents_dir / present).exists(), (
                f"init missing expected agent {present}"
            )


class TestCommonTierAssetHygiene:
    """TP-72 — common-tier asset bodies must not reference
    harness-internal tooling that isn't deployed to host repos, and
    must not leak specific TP-NN / BC-NNN pack identifiers from the
    harness's own development log."""

    # Specific IDs contain at least one digit (TP-71, TP-SYN-08,
    # BC-035, TASK_PACK_14). Generic placeholders without digits
    # (``TP-NN``, ``BC-NNN``) are explicitly allowed as documentation
    # vocabulary. The regex is now the SoT in espalier/surface_hygiene.py
    # so the pre-flight (`espalier surface-impact`) scans with the exact
    # same oracle this contract enforces; tests/test_surface_hygiene_parity.py
    # pins them together.
    _SPECIFIC_ID_RE = SPECIFIC_ID_RE

    def test_code_reviewer_does_not_reference_missing_tool(self) -> None:
        """``code-reviewer.md`` must not reference
        ``tools/review_agent_audit.py`` — host repos don't deploy it,
        and a stale reference causes ``python: can't open file ...``
        on every ``/review`` invocation."""
        body = (
            REPO_ROOT
            / "espalier" / "assets" / "claude" / "agents" / "code-reviewer.md"
        ).read_text(encoding="utf-8")
        assert "review_agent_audit.py" not in body

    def test_common_tier_assets_have_no_internal_pack_ids(self) -> None:
        """No specific ``TP-NN`` / ``BC-NNN`` / ``TASK_PACK_NN`` IDs
        in common-tier command, agent, or skill bodies. Generic
        placeholders (``TP-NN``, ``BC-NNN``) are allowed; only IDs
        with embedded digits trip the contract."""
        asset_root = REPO_ROOT / "espalier" / "assets" / "claude"
        offenders: list[tuple[str, str]] = []
        for sub in ("agents", "commands", "skills"):
            for path in (asset_root / sub).rglob("*.md"):
                rel = path.relative_to(asset_root).as_posix()
                hits = self._SPECIFIC_ID_RE.findall(
                    path.read_text(encoding="utf-8"),
                )
                if hits:
                    offenders.append((rel, ", ".join(sorted(set(hits)))))
        # TP-174b R26: the claude/ loop above was blind to the deployed
        # docs/ + memory/ bootstrap assets (TP-88 deploys them verbatim to
        # adopters), so internal pack IDs leaked there undetected. Scan them
        # too. No HARNESS_DEV_ASSETS carve-out is needed (no dev-only assets
        # live under docs/memory). ``github/`` is deliberately excluded:
        # harness-guard.yml carries intentional BC-/TP- provenance comments
        # that TP-171 #14 adjudicated do-not-reopen.
        # ``seed`` joined docs/memory when the adopter stubs for the
        # init-seeded docs/SHARP_EDGES.md + docs/CONVENTIONS.md moved OUT of
        # assets/docs/ (managed_inventory._SEED_ASSET_SOURCES). They are
        # adopter-deployed asset bodies like the others, and the loop below was
        # the only sweep that would have caught a pack-ID leak in them.
        assets_root = REPO_ROOT / "espalier" / "assets"
        for extra in ("docs", "memory", "seed"):
            for path in (assets_root / extra).rglob("*.md"):
                hits = self._SPECIFIC_ID_RE.findall(
                    path.read_text(encoding="utf-8"),
                )
                if hits:
                    rel = path.relative_to(assets_root).as_posix()
                    offenders.append((rel, ", ".join(sorted(set(hits)))))
        assert not offenders, (
            "common-tier asset(s) leak specific pack IDs:\n"
            + "\n".join(f"  {rel}: {ids}" for rel, ids in offenders)
        )

    # TP-129 forbidden self-host vocabulary in common-tier asset bodies.
    # The TP-118 sweep (_SPECIFIC_ID_RE above) caught TP-/BC-NNN ID
    # leaks; this v2 contract catches the prose that survived because
    # it carries no embedded digits. The (label, pattern) tuple is now
    # the SoT in espalier/surface_hygiene.py (shared with the
    # surface-impact pre-flight); the per-line + wrapped-text scan that
    # reports line numbers stays below.
    _FORBIDDEN_SELF_HOST_PATTERNS = FORBIDDEN_SELF_HOST_PATTERNS

    def test_common_tier_assets_have_no_self_host_vocabulary(self) -> None:
        """Forbidden self-host vocabulary must not appear in common-tier
        asset bodies. The TP-129 forbidden-tokens list catches prose
        that frames the harness as the adopter's own development
        target rather than as a tool the adopter installed."""
        asset_root = REPO_ROOT / "espalier" / "assets" / "claude"
        offenders: list[tuple[str, str, int, str]] = []
        for sub in ("agents", "commands", "skills"):
            for path in (asset_root / sub).rglob("*.md"):
                rel = path.relative_to(asset_root).as_posix()
                text = path.read_text(encoding="utf-8")
                lines = text.splitlines()
                per_line_labels: set[str] = set()
                for lineno, line in enumerate(lines, start=1):
                    for label, pat in self._FORBIDDEN_SELF_HOST_PATTERNS:
                        if pat.search(line):
                            offenders.append((rel, label, lineno, line.strip()))
                            per_line_labels.add(label)
                # TP-174b T05: a forbidden phrase can wrap across a line break
                # (e.g. "*Self-host\n  meaning:*"), which the per-line scan
                # above misses. Re-scan a whitespace-collapsed copy and report
                # any pattern that matches the joined text but was not already
                # caught on a single line. Verified false-positive-free across
                # all common-tier assets (the R-NNN lookahead's bounded
                # [^.]{0,80} window keeps it contained on the joined text).
                joined = re.sub(r"\s+", " ", text)
                for label, pat in self._FORBIDDEN_SELF_HOST_PATTERNS:
                    if label not in per_line_labels and pat.search(joined):
                        offenders.append((rel, label, 0, "(wrapped across lines)"))
        assert not offenders, (
            "common-tier asset(s) carry self-host vocabulary:\n"
            + "\n".join(
                f"  {rel}:{lineno} [{label}] {snippet[:120]}"
                for rel, label, lineno, snippet in offenders
            )
            + "\n\nRewrite as adopter-neutral (drop \"THIS harness\" "
            "emphasis; replace \"Self-host meaning:\" prose with a plain "
            "\"What happens:\" framing; remove R-NNN review-round refs)."
        )


class TestDryRunPreview:
    """`init --dry-run` must PREVIEW the full deployed surface (7/17/9),
    matching what a real init writes. The harness-dev deploy tier was
    retired, so the preview no longer filters by tier."""

    def test_dry_run_previews_full_surface_counts(self, tmp_path: Path) -> None:
        import subprocess
        import sys
        repo = _make_repo(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(repo), "--dry-run"],
            capture_output=True, text=True, timeout=60, encoding="utf-8",
        )
        m = re.search(
            r"Would deploy (\d+) agents, (\d+) commands, (\d+) skills", r.stdout
        )
        assert m, f"no dry-run preview line:\n{r.stdout}\n{r.stderr}"
        counts = tuple(int(g) for g in m.groups())
        assert counts == (7, 17, 9), (
            f"dry-run preview should match the real init surface (7,17,9); "
            f"got {counts}"
        )
