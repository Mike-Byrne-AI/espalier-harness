"""Tests for ``espalier init`` — the first-run deployment command
that materializes ``.claude/settings.json``, the hook scripts, the
managed CC docs, and the cognitive-blueprint scaffolding into an
adopter repo.

Pins the deployment contract: ``settings.json`` lands with all
required hook events wired (``SessionStart``, ``PreToolUse``,
``Stop``, ...). Without this contract an init regression could
silently ship a half-installed harness — hook files present on disk
but never wired into ``settings.json``, so no enforcement actually
fires and the user only finds out when something they expected to
block doesn't.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from espalier import cli, surface_contract
from espalier.cli import cmd_init, cmd_upgrade
from espalier.harness_config import CANONICAL_HOOK_WIRING


class TestInitDeployment:
    """Verify init creates a working harness."""

    def _make_repo(self, tmp_path: Path) -> Path:
        """Create a minimal git-initialized repo."""
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test-app"\n', encoding="utf-8"
        )
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        return tmp_path

    def _run_init(self, repo: Path, **overrides) -> int:
        args = argparse.Namespace(repo=str(repo), config=None, **overrides)
        return cmd_init(args)

    def test_creates_settings_json(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        settings_path = repo / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]
        assert "PreToolUse" in settings["hooks"]
        assert "Stop" in settings["hooks"]

    def test_creates_hook_scripts(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        for hook in [
            "session_start.py", "task_router.py", "plan_guard.py",
            "write_guard.py", "post_write_check.py",
            "reflect_trigger.py", "stop_gate.py", "post_compact.py",
        ]:
            assert (repo / "tools" / "cc" / "hooks" / hook).exists(), f"Missing hook: {hook}"

    def test_creates_claude_md(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        claude_md = repo / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text(encoding="utf-8")
        assert "Governance Harness" in content
        assert "session_start.py" in content

    def test_survives_unwritable_gitignore(self, tmp_path, capsys):
        """LANEB-01 earn-the-red: init must not fail AFTER it has succeeded.

        Pre-fix, a `.gitignore` that could not be appended to made init exit 1
        with a bare errno — after all 96 files were deployed and every hook
        wired. The success banner never printed, so the operator had a fully
        configured repo they believed had failed, and every re-run failed the
        same way. The realistic trigger is a dangling symlink into a dotfiles
        directory that has not been cloned yet.
        """
        repo = self._make_repo(tmp_path)
        gitignore = repo / ".gitignore"
        gitignore.symlink_to(tmp_path / "dotfiles-not-cloned" / "gitignore")
        # write_gitignore is passed explicitly for the record: since
        # 2026-09-12 (DEF-399b) cmd_init's getattr fallback agrees with the
        # parser's default of True, so the shared _run_init helper reaches the
        # append on its own; the explicit True keeps this case's intent
        # readable without relying on that.
        rc = self._run_init(repo, write_gitignore=True)
        out = capsys.readouterr().out
        assert rc == 0, "a .gitignore that cannot be written is not an init failure"
        assert "What just happened" in out, "the success banner must still print"
        assert "could not update .gitignore" in out
        # The warning has to be actionable: it names the entries to add by hand.
        assert "# Espalier-Harness runtime" in out
        # ...and the CLOSING reminder must survive too. It was gated on
        # `not write_gitignore`, so it fired on the deliberate opt-out and was
        # suppressed on the failure path — where the operator is one
        # `git add -A` from committing .claude/settings.json, the file the root
        # CLAUDE.md calls the primary foreclosure against a committed
        # kill switch. The WARN is ~25 lines up, under the whole success banner.
        assert "Address the .gitignore warning above" in out

    def test_successful_gitignore_write_does_not_nag(self, tmp_path, capsys):
        """Negative control for the reminder fix.

        Making the reminder fire on the failure path must not make it fire when
        the append actually worked — `needs_gitignore` now means "STILL missing
        after this run", so a successful write empties it.
        """
        repo = self._make_repo(tmp_path)
        rc = self._run_init(repo, write_gitignore=True)
        out = capsys.readouterr().out
        assert rc == 0
        assert "entries to .gitignore" in out
        assert "Address the .gitignore warning above" not in out
        assert (repo / ".claude" / "settings.json").exists(), (
            "the deploy that already succeeded must be intact"
        )

    def test_survives_gitignore_that_is_a_directory(self, tmp_path, capsys):
        """The read side has the same exposure as the write side.

        `.gitignore` as a DIRECTORY makes read_text raise IsADirectoryError
        before the append is ever reached, so guarding only the write would
        still abort init here.
        """
        repo = self._make_repo(tmp_path)
        (repo / ".gitignore").mkdir()
        rc = self._run_init(repo, write_gitignore=True)
        out = capsys.readouterr().out
        assert rc == 0
        assert "What just happened" in out
        assert "could not update .gitignore" in out

    def test_creates_reports(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        assert (repo / "reports" / "repo_fingerprint.json").exists()
        assert (repo / "reports" / "harness_config.json").exists()

    def test_seeds_carryover_docs_with_tier_split_headers(self, tmp_path):
        # init seeds the portable-knowledge docs; a Tier-2 doc (carries
        # illustrative Espalier examples) gets the deploy-time adapt-header, a
        # Tier-1 doc ships verbatim. Neuter the seed-loop `header=` wiring and
        # this goes red.
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        tier2 = repo / "docs" / "FAILURE_MODES.md"
        tier1 = repo / "docs" / "external" / "cc-hook-protocol.md"
        assert tier2.exists() and tier1.exists()
        # The first line is now the seed-version stamp (TP-348); the Tier-2
        # adapt-header follows immediately below it. Neuter the seed-loop
        # `header=` wiring and the second assertion goes red.
        t2 = tier2.read_text(encoding="utf-8")
        assert t2.startswith("<!-- espalier:seed-version ")
        assert t2[t2.index("\n") + 1:].startswith("<!-- espalier:seed-doc")
        assert "espalier:seed-doc" not in tier1.read_text(encoding="utf-8")
        # De-seeded: the "why-we-built-this" philosophy docs are no longer
        # deployed into an adopter tree (they stay as self-host contributor docs).
        assert not (repo / "docs" / "epistemic-partnership.md").exists()
        assert not (repo / "docs" / "DEEP-WORK.md").exists()

    def test_skips_existing_files(self, tmp_path):
        repo = self._make_repo(tmp_path)
        # Pre-create CLAUDE.md with custom content
        (repo / "CLAUDE.md").write_text("# My Custom Config\n", encoding="utf-8")
        self._run_init(repo)
        # Should NOT overwrite
        assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == "# My Custom Config\n"

    def test_hook_scripts_have_no_builder_imports(self, tmp_path):
        import ast
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        for py_file in (repo / "tools" / "cc").rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    assert not mod.startswith("espalier"), (
                        f"{py_file.name} imports from espalier ({mod})"
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("espalier"), (
                            f"{py_file.name} imports espalier ({alias.name})"
                        )


class TestInitStartHereAnchor:
    """1-A sister site: `init <path>` need not target cwd, so the same
    un-anchored start-here line that bit the Windows walk in `fuse` is reachable
    here too. BOTH branches are pinned on purpose -- an unfired conditional is
    this pack's own recurring defect, and a one-branch pin would not notice."""

    def _make_repo(self, tmp_path: Path) -> Path:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n', encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)  # cmd_init pre-flight.
        return tmp_path

    def test_cds_when_target_is_not_cwd(self, tmp_path, monkeypatch, capsys):
        # Spaced path, same reasoning as the fuse pin.
        repo = self._make_repo(tmp_path / "some repo")
        monkeypatch.chdir(tmp_path)
        cmd_init(argparse.Namespace(repo=str(repo), config=None))
        printed = capsys.readouterr().out
        assert f'cd "{repo.resolve()}"' in printed, (
            "init targeted a tree that is not cwd and did not anchor the "
            f"start-here line to it.\n{printed[-800:]}"
        )

    def test_no_redundant_cd_when_target_is_cwd(self, tmp_path, monkeypatch, capsys):
        repo = self._make_repo(tmp_path)
        monkeypatch.chdir(repo)
        cmd_init(argparse.Namespace(repo=str(repo), config=None))
        printed = capsys.readouterr().out
        assert "Start Claude Code with: claude" in printed
        assert 'cd "' not in printed, (
            "init . emitted a redundant cd to the directory the operator is "
            f"already in.\n{printed[-800:]}"
        )


class TestInitCreatesRequiredSurface:
    """Pack 2-B — init renders the required cc/ surface docs from discovery."""

    def _make_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        return tmp_path

    def _run_init(self, repo: Path) -> int:
        args = argparse.Namespace(repo=str(repo), config=None)
        return cmd_init(args)

    def test_all_required_init_files_exist(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        for rel in surface_contract.get_required_init_files():
            assert (repo / rel).exists(), f"Missing required init file: {rel}"

    def test_live_surface_mentions_disk_hooks(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        live_surface = (repo / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        # Every hook that init deployed should be mentioned
        for hook_name in surface_contract.get_canonical_hook_scripts():
            assert hook_name in live_surface, (
                f"LIVE_SURFACE.md does not mention hook {hook_name}"
            )

    def test_live_surface_excludes_phantom_scripts(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        live_surface = (repo / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        for phantom in ["settings_validator", "memory_guard", "blueprint_capture",
                        "test_pairing", "drift_detector", "commit_guard"]:
            assert phantom not in live_surface, (
                f"LIVE_SURFACE.md leaks phantom script {phantom}"
            )

    def test_commands_doc_header_renders(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        commands_doc = (repo / "cc" / "COMMANDS.md").read_text(encoding="utf-8")
        assert "# Commands" in commands_doc
        assert "espalier:managed" in commands_doc

    def test_pack_manifest_lists_hooks(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        manifest = (repo / "cc" / "PACK_MANIFEST.txt").read_text(encoding="utf-8")
        for hook_name in surface_contract.get_canonical_hook_scripts():
            assert f"tools/cc/hooks/{hook_name}" in manifest

    def test_init_idempotent(self, tmp_path):
        """Running init twice does not corrupt or duplicate content."""
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        first = (repo / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        self._run_init(repo)
        second = (repo / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        assert first == second, "Second init changed cc/LIVE_SURFACE.md"


class TestInitPortabilityContract:
    """Verify init generates settings that meet the OS-portability contract.

    TP-35 cleanup: the pre-TP-35 portability checks (absolute interpreter
    path, sys.executable identity, spaces-in-interpreter-path quoting) are
    obsolete. Exec form spawns ``python`` directly via Claude Code with
    each arg passed verbatim, so there is no interpreter path to quote
    and no shell tokenization to worry about. The new TP-35 contract
    (exec form, ``python`` command, curly-form ``${CLAUDE_PROJECT_DIR}``
    args) is pinned in ``tests/test_hook_exec_form.py``.
    """

    def _make_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        return tmp_path

    def _run_init(self, repo: Path) -> int:
        args = argparse.Namespace(repo=str(repo), config=None)
        return cmd_init(args)

    def test_all_nine_hooks_wired(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
        commands = []
        for event_entries in settings["hooks"].values():
            for entry in event_entries:
                for hook in entry.get("hooks", []):
                    commands.append(hook.get("command", ""))
        from tests._surface_expected import EXPECTED_HOOK_COUNT
        assert len(commands) == EXPECTED_HOOK_COUNT, (
            f"Expected {EXPECTED_HOOK_COUNT} hooks, got {len(commands)}"
        )

    def test_settings_is_valid_json(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        text = (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert "hooks" in parsed

    def test_init_claude_md_lists_all_canonical_hooks(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        for hook_name in CANONICAL_HOOK_WIRING:
            assert hook_name in claude_md, (
                f"Deployed CLAUDE.md missing canonical hook: {hook_name}"
            )

    def test_init_on_clean_temp_repo(self, tmp_path):
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        args = argparse.Namespace(repo=str(tmp_path), config=None)
        result = cmd_init(args)
        assert result == 0
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists(), "settings.json was not created"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        commands = []
        for event_entries in settings.get("hooks", {}).values():
            for entry in event_entries:
                for hook in entry.get("hooks", []):
                    commands.append(hook.get("command", ""))
        from tests._surface_expected import EXPECTED_HOOK_COUNT
        assert len(commands) == EXPECTED_HOOK_COUNT


class TestInitCommandMergeContract:
    """Fresh init must deploy the full .claude/ harness surface.

    Per TP-13 Task 13-B: cmd_init copies bundled .claude/commands/,
    .claude/skills/, and the 6 rich .claude/agents/*.md into target repos.
    Profile-driven OPTIONAL_AGENTS (api-reviewer, etc.) are layered on top
    via the existing stub generator. Each deployed file is tagged with the
    espalier:managed marker so users can distinguish harness-deployed from
    user-authored content. Init also deploys: tools/cc/task_router.py,
    tools/cc/hooks/plan_guard.py, CLAUDE.md, and generated cc/COMMANDS.md.
    """

    def _make_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        return tmp_path

    def _run_init(self, repo: Path) -> int:
        args = argparse.Namespace(repo=str(repo), config=None)
        return cmd_init(args)

    def test_task_router_deployed_with_implement_task_multi(self, tmp_path):
        """Deployed task_router.py must route to /implement-task --multi."""
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        router = (repo / "tools" / "cc" / "hooks" / "task_router.py").read_text(encoding="utf-8")
        assert "/implement-task --multi" in router

    def test_task_router_does_not_present_accomplish_as_primary(self, tmp_path):
        """Deployed task_router.py must not say 'Use /accomplish to create'."""
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        router = (repo / "tools" / "cc" / "hooks" / "task_router.py").read_text(encoding="utf-8")
        assert "Use /accomplish to create" not in router

    def test_plan_guard_deployed_with_implement_task_guidance(self, tmp_path):
        """Deployed plan_guard.py denial message must reference /implement-task."""
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        hooks_dir = repo / "tools" / "cc" / "hooks"
        guard = (hooks_dir / "plan_guard.py").read_text(encoding="utf-8")
        reasons = (hooks_dir / "_denial_reasons.py").read_text(encoding="utf-8")
        assert "import _denial_reasons" in guard
        denial_surface = guard + reasons
        assert "/implement-task" in denial_surface
        assert "--multi" in denial_surface

    def test_generated_claude_md_routes_to_implement_task(self, tmp_path):
        """Generated CLAUDE.md must show /implement-task as the task command."""
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert "/implement-task" in claude_md

    def test_generated_claude_md_routes_to_implement_task_multi(self, tmp_path):
        """Generated CLAUDE.md hook table must reference /implement-task --multi."""
        repo = self._make_repo(tmp_path)
        self._run_init(repo)
        claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert "/implement-task --multi" in claude_md

    def test_init_fusion_reachable_hints_use_python_m_espalier(self, tmp_path, capsys):
        """TP-184 B7: in a fusion there is no `espalier` on PATH (the engine is
        vendored, not pip-installed) and fuse_repos reaches cmd_init. Every
        operator hint cmd_init PRINTS must therefore use `python -m espalier`,
        never a bare `espalier <cmd>` (command-not-found in a fusion)."""
        repo = self._make_repo(tmp_path)
        claude = repo / ".claude"
        claude.mkdir(exist_ok=True)
        # A permissions-only settings.json triggers the case-(b) "NO HOOKS WIRED"
        # WARN + the "NOT yet active" banner — the fusion-reachable hint sites.
        (claude / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}) + "\n",
            encoding="utf-8")
        self._run_init(repo)
        captured = capsys.readouterr()
        out = captured.out + captured.err
        for verb in ("espalier merge-settings", "espalier clean-generated",
                     "espalier init"):
            bare = out.count(verb)
            # TP-391 4-A: `-m <verb>` alone is NOT enough. `out.count("-m " + verb)`
            # also matches a hint rendered with NO interpreter token at all, which is
            # exactly the regression a detection-driven interpreter change introduces --
            # and which this assertion's own message already claimed to catch. Require an
            # interpreter-shaped token immediately before ` -m `, which holds for both
            # `python` and `python3` without pinning either.
            #
            # The class is `[\w./-]+`, NOT `\S+`: several hint sites in cli.py wrap the
            # command in backticks (`{py} -m espalier init .`), and `\S+` happily matches
            # the BACKTICK as the interpreter -- so an empty token would still pass at
            # those sites. `_detect_python_command` only ever returns `python`/`python3`
            # (never a path, never quoted), so the tighter class cannot false-red here.
            prefixed = len(re.findall(r"[\w./-]+ -m " + re.escape(verb), out))
            assert bare == prefixed, (
                f"cmd_init printed a bare `{verb}` hint (command-not-found in a "
                f"fusion). All {bare} occurrence(s) must be `<interp> -m {verb}`; "
                f"only {prefixed} are.\nOutput:\n{out}")

    # TP-13 Task 13-B's "deploy-all .claude/ surface" tests were removed
    # in the TP-28 cleanup. TP-31 (Path B) stripped bundled commands,
    # skills, and rich agents from the default deploy — the current deploy
    # contract is pinned by `tests/test_init_tier_split.py` (post-TP-129:
    # the common tier deploys 7 agents).
    # The previous tests asserted the pre-TP-31 deploy shape (14 commands,
    # 6 skills, 6 rich agents from `espalier/assets/claude/`) and were
    # obsolete once that tree became empty.


class TestInitReportsAPreservedClaudeMd:
    """DEF-428 — an adopter who already owns a root CLAUDE.md must be TOLD that
    the harness sections the hook denials cite are not in it.

    Before this, `init` recorded the skip as ``"CLAUDE.md (exists)"`` and the
    summary collapsed it to ``Skipped (other): 1 entries`` -- the filename never
    reached the operator. They then hit a plan-required deny reading ``see
    CLAUDE.md "Plan Guard" section``, searched their own CLAUDE.md, and found
    nothing. `doctor` reported ``status: pass`` with no warnings throughout.

    Drives the real command end-to-end rather than calling the printer. That is
    load-bearing: the first cut of this fix referenced a variable defined in a
    different function, so `cmd_init` raised NameError on exactly this path --
    with the whole suite green, because no test had ever run init over a repo
    that already had a CLAUDE.md.
    """

    _ADOPTER_BODY = "# my-app\n\nHouse style: 2-space indent. Run `make test`.\n"

    def _make_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)  # TP-73 cmd_init pre-flight.
        return tmp_path

    def _run_init(self, repo: Path) -> int:
        args = argparse.Namespace(repo=str(repo), config=None)
        return cmd_init(args)

    def test_preserved_claude_md_is_named_with_its_missing_sections(
        self, tmp_path, capsys
    ):
        repo = self._make_repo(tmp_path)
        (repo / "CLAUDE.md").write_text(self._ADOPTER_BODY, encoding="utf-8")

        rc = self._run_init(repo)
        out = capsys.readouterr().out

        assert rc == 0
        assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == self._ADOPTER_BODY, (
            "init must never rewrite a CLAUDE.md the adopter owns"
        )
        assert "CLAUDE.md" in out, (
            "the skipped file must be named, not folded into a count"
        )
        for section in cli.REQUIRED_CLAUDE_MD_SECTIONS:
            assert section in out, (
                f"init did not tell the adopter their CLAUDE.md lacks the "
                f"{section!r} section that hook denials cite by name.\n{out}"
            )
        assert "render-template claude" in out, (
            "naming the gap without naming the remedy leaves the adopter stuck"
        )

    def test_generated_claude_md_draws_no_nudge(self, tmp_path, capsys):
        """Negative control. When init RENDERS the skeleton, every cited
        section is present, so the report must stay silent -- and must not
        claim to have 'kept your existing CLAUDE.md' for a file it just
        wrote."""
        repo = self._make_repo(tmp_path)
        assert not (repo / "CLAUDE.md").exists()

        rc = self._run_init(repo)
        out = capsys.readouterr().out

        assert rc == 0
        assert "kept your existing CLAUDE.md" not in out
        for section in cli.REQUIRED_CLAUDE_MD_SECTIONS:
            assert f"## {section}" in (repo / "CLAUDE.md").read_text(encoding="utf-8"), (
                f"the rendered skeleton is missing the cited {section!r} section"
            )

    def test_adopter_claude_md_that_covers_the_sections_is_left_alone(
        self, tmp_path, capsys
    ):
        """Suppress on no-match. An adopter who wrote their own coverage of
        these topics must not be nagged -- the nudge models their search, so
        anything findable ends the search successfully."""
        repo = self._make_repo(tmp_path)
        # Derived, not a hand-written copy: a section added to the cited set
        # must extend this fixture too, or the test would silently start
        # asserting "silent" about a CLAUDE.md that is in fact incomplete.
        own_coverage = "".join(
            f"\n## {section}\n\nour own notes\n"
            for section in cli.REQUIRED_CLAUDE_MD_SECTIONS
        )
        (repo / "CLAUDE.md").write_text(self._ADOPTER_BODY + own_coverage, encoding="utf-8")

        rc = self._run_init(repo)
        out = capsys.readouterr().out

        assert rc == 0
        assert "kept your existing CLAUDE.md" not in out, (
            f"nagged an adopter whose CLAUDE.md already covers both sections:\n{out}"
        )

    def test_upgrade_also_reports_a_preserved_claude_md(self, tmp_path, capsys):
        """`upgrade`, not `init`, is the verb an adopter on an old harness
        reaches for -- and they are precisely the population whose CLAUDE.md
        predates a cited section.

        This path was missed on the first pass: the report lived only in
        `cmd_init`'s summary, so `upgrade .` stayed silent about exactly the
        gap it exists to surface. Asserted on the DRY-RUN, because `upgrade`
        never rewrites an existing CLAUDE.md, so a preview that said nothing
        would be the same silence the fix removes.
        """
        repo = self._make_repo(tmp_path)
        (repo / "CLAUDE.md").write_text(self._ADOPTER_BODY, encoding="utf-8")
        assert self._run_init(repo) == 0
        capsys.readouterr()

        # Make the deployed harness look older than the engine so upgrade does
        # not short-circuit with "harness is current; nothing to do".
        (repo / "cc" / "PACK_MANIFEST.txt").write_text(
            "espalier-harness 0.0.1-ancient\n", encoding="utf-8"
        )

        args = argparse.Namespace(repo=str(repo), config=None, execute=False)
        rc = cmd_upgrade(args)
        out = capsys.readouterr().out

        assert rc == 0
        for section in cli.REQUIRED_CLAUDE_MD_SECTIONS:
            assert section in out, (
                f"`upgrade` did not report that the preserved CLAUDE.md lacks "
                f"the cited {section!r} section.\n{out}"
            )
        assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == self._ADOPTER_BODY, (
            "a dry-run upgrade must not touch the adopter's CLAUDE.md"
        )

    def test_incidental_prose_does_not_count_as_coverage(self, tmp_path, capsys):
        """The nudge's predicate is a HEADING match, not a bare substring, and
        this pins that as a decision rather than an accident.

        `maintenance mode` and `plan guard` are ordinary English phrases that
        turn up in real CLAUDE.md prose. Under a substring match, a line like
        "we freeze deploys during maintenance mode" reads as coverage and
        suppresses the report -- leaving the adopter with a dangling citation
        AND no notice, which is the exact pair this exists to break. The
        asymmetry decides it: a false alarm costs one line of stdout, a false
        silence costs the whole fix.
        """
        repo = self._make_repo(tmp_path)
        prose = "\n".join(
            f"We have opinions about {s.lower()} but no section for it."
            for s in cli.REQUIRED_CLAUDE_MD_SECTIONS
        )
        (repo / "CLAUDE.md").write_text(f"{self._ADOPTER_BODY}\n{prose}\n", encoding="utf-8")

        assert self._run_init(repo) == 0
        out = capsys.readouterr().out

        for section in cli.REQUIRED_CLAUDE_MD_SECTIONS:
            assert section in out, (
                f"a passing mention of {section!r} in prose suppressed the "
                f"report; the adopter has no such section and no notice.\n{out}"
            )

    def test_remedy_names_the_host_interpreter(self, tmp_path, capsys):
        """The printed remedy must run on the host it is printed on.

        A bare `python -m espalier ...` is `command not found` on a macOS host
        that ships only `python3` -- while telling the adopter to go add a
        section named "Cross-platform Python invocation".
        """
        repo = self._make_repo(tmp_path)
        (repo / "CLAUDE.md").write_text(self._ADOPTER_BODY, encoding="utf-8")

        assert self._run_init(repo) == 0
        out = capsys.readouterr().out

        remedy = next(
            ln for ln in out.splitlines() if "render-template claude" in ln
        )
        # The REMEDY interpreter, not the resolver's write answer: on a host
        # where the resolver's answer fails the floor the two differ, and the
        # remedy is the one an operator can paste (DEF-758).
        assert f"{cli._remedy_py()} -m espalier" in remedy, remedy
