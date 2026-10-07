"""Tests for ``espalier.harness_config`` — the builder that turns a
``RepoFingerprint`` into a deployable ``BuildPlan`` (agent selection,
action detection, scope paths, hook emission).

Pins the derivation rules unit-by-unit: ``choose_agents`` selects the
agent roster matching the fingerprint; ``_detect_actions`` derives the
stable-action set; ``_scope_paths`` excludes vendored/garbage paths.
Without this contract a fingerprint-schema tweak or an agent-roster
reorder could silently change the deployed surface without any visible
failure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.models import (
    AgentSpec,
    HarnessConfig,
    BuildPlan,
    RepoFingerprint,
)
from espalier.harness_config import (
    CORE_GENERATED_DOCS,
    EXTENDED_GENERATED_DOCS,
    _detect_actions,
    _scope_paths,
    build_harness_config,
    choose_agents,
    suggest_agents,
)
from espalier.surface_contract import get_required_init_files
from espalier.harness_config import declared_action, preflight_command


def _minimal_fp(**kwargs) -> RepoFingerprint:
    defaults = dict(repo_name="test-repo", repo_root=".")
    defaults.update(kwargs)
    return RepoFingerprint(**defaults)


class TestDetectActions:
    def test_always_includes_audit(self):
        fp = _minimal_fp()
        actions = _detect_actions(fp)
        assert "audit" in actions
        assert actions["audit"] == ["espalier audit ."]

    def test_test_command_added_when_present(self):
        fp = _minimal_fp(test_commands=["pytest -q"])
        actions = _detect_actions(fp)
        assert "test" in actions
        assert actions["test"] == ["pytest -q"]

    def test_no_test_action_when_no_test_commands(self):
        fp = _minimal_fp(test_commands=[])
        actions = _detect_actions(fp)
        assert "test" not in actions

    def test_python_adds_scan_action(self):
        fp = _minimal_fp(languages=["python"])
        actions = _detect_actions(fp)
        assert "scan" in actions

    def test_non_python_no_scan_action(self):
        fp = _minimal_fp(languages=["javascript"])
        actions = _detect_actions(fp)
        assert "scan" not in actions

    def test_always_includes_reflect_and_execution_plan(self):
        fp = _minimal_fp()
        actions = _detect_actions(fp)
        assert "reflect" in actions
        assert "execution-plan" in actions

    def test_inferred_lint_and_build_are_carried(self):
        """DEF-962: the plan carried only the test command, so cc/COMMANDS.md
        named no lint or build for a Node repository whose package.json
        declares both. The dev-server smoke stays out."""
        fp = _minimal_fp(
            test_commands=["npm test"],
            inferred_actions={
                "lint": ["npm run lint"], "build": ["npm run build"], "smoke": ["npm run dev"],
            },
        )
        actions = _detect_actions(fp)
        assert actions["lint"] == ["npm run lint"]
        assert actions["build"] == ["npm run build"]
        assert "smoke" not in actions

    def test_a_malformed_inferred_action_is_not_carried(self):
        fp = _minimal_fp(inferred_actions={"lint": "npm run lint", "build": [3]})
        actions = _detect_actions(fp)
        assert "lint" not in actions and "build" not in actions


def _node_root(tmp_path, *, toml: str | None = None, extra_scripts: str = ""):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "node --test", "lint": "eslint .", "build": "astro build"'
        + extra_scripts + "}}\n",
        encoding="utf-8",
    )
    if toml is not None:
        (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
    return tmp_path


class TestDeclaredAction:
    """What /preflight runs (DEF-962): the repository's declarations, before
    any PATH probe."""

    def test_the_fingerprint_infers_each_preflight_action_on_a_node_tree(self, tmp_path):
        root = _node_root(tmp_path)
        assert declared_action(root, "lint") == ("fingerprint", ["npm run lint"])
        assert declared_action(root, "test") == ("fingerprint", ["npm test"])
        assert declared_action(root, "build") == ("fingerprint", ["npm run build"])

    def test_extra_actions_outrank_the_inference(self, tmp_path):
        root = _node_root(tmp_path, toml='[extra_actions]\nlint = ["npm run check", "npm run typecheck"]\n')
        assert declared_action(root, "lint") == ("espalier.toml", ["npm run check", "npm run typecheck"])
        assert preflight_command("lint", root) == "npm run check && npm run typecheck"

    def test_a_suppressed_action_says_so_and_runs_nothing_else(self, tmp_path):
        root = _node_root(tmp_path, toml='suppress_actions = ["lint"]\n')
        assert declared_action(root, "lint") == ("suppressed", [])
        line = preflight_command("lint", root)
        assert line.startswith("echo ") and "suppressed" in line

    def test_nothing_declared_is_an_empty_line(self, tmp_path):
        assert declared_action(tmp_path, "lint") == ("", [])
        assert preflight_command("lint", tmp_path) == ""

    def test_the_run_names_its_gate_and_the_repository_gate_it_skipped(self, tmp_path, capsys):
        root = _node_root(tmp_path, extra_scripts=', "preflight": "npm run lint && npm test"')
        assert preflight_command("lint", root) == "npm run lint"
        err = capsys.readouterr().err
        assert "/preflight lint gate: npm run lint" in err, err
        assert "`preflight`" in err and "does not execute" in err, err

    def test_a_ruff_config_file_is_a_lint_declaration(self, tmp_path):
        (tmp_path / "ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
        assert declared_action(tmp_path, "lint") == ("fingerprint", ["ruff check ."])

    def test_the_inferred_ruff_line_leaves_the_vendored_tree_out(self, tmp_path, capsys):
        """DEF-1154: the fingerprint infers `ruff check .` for a repository
        that configures ruff, and /preflight ran it as declared -- over the 44
        deployed files under tools/cc/, which pass Espalier's own rule set and
        not necessarily the adopter's (measured 2026-10-06: 412 to 1,683
        findings on a fresh init). Only the PATH fallback in the body spelled
        the exclude. The runner now adds it to the INFERRED line; the
        fingerprint's own string stays byte-identical (TP-469 pins it), and
        the stderr line names the line that actually ran."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "a"\n[tool.ruff.lint]\nselect = ["E", "F"]\n', encoding="utf-8")
        assert declared_action(tmp_path, "lint") == ("fingerprint", ["ruff check ."])
        assert preflight_command("lint", tmp_path) == "ruff check --extend-exclude tools/cc ."
        assert "/preflight lint gate: ruff check --extend-exclude tools/cc ." in capsys.readouterr().err

    def test_a_declared_ruff_line_runs_as_written(self, tmp_path):
        """A `[extra_actions] lint` is the adopter's exact line: it runs
        verbatim, and the init note is what tells them about the exclude."""
        (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nline-length = 100\n', encoding="utf-8")
        (tmp_path / "espalier.toml").write_text('[extra_actions]\nlint = ["ruff check ."]\n', encoding="utf-8")
        assert declared_action(tmp_path, "lint") == ("espalier.toml", ["ruff check ."])
        assert preflight_command("lint", tmp_path) == "ruff check ."

    def test_a_makefile_or_script_lint_outranks_the_inference_and_runs_as_it_is(self, tmp_path):
        """The failure-mode review of DEF-1154: ruff declared AND a Makefile
        `lint` target (or a package.json lint script). The inference picks the
        Makefile, the runner leaves it alone, and the adopter's `[tool.ruff]`
        exclude from init's note is what reaches that run, through ruff's own
        configuration discovery. Pinned so the note's claim stays a superset
        of the runner's, never an equality."""
        (tmp_path / "pyproject.toml").write_text('[tool.ruff.lint]\nselect = ["E", "F"]\n', encoding="utf-8")
        (tmp_path / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")
        assert declared_action(tmp_path, "lint") == ("fingerprint", ["make lint"])
        assert preflight_command("lint", tmp_path) == "make lint"

    def test_the_exclude_is_added_once_and_only_to_a_ruff_check_line(self):
        from espalier.harness_config import VENDORED_RUFF_EXCLUDE, _inferred_ruff_without_the_vendored_tree as f
        assert VENDORED_RUFF_EXCLUDE == "tools/cc"
        assert f("ruff check .") == "ruff check --extend-exclude tools/cc ."
        assert f("ruff  check .") == "ruff check --extend-exclude tools/cc ."   # rebuilt from tokens
        assert f("ruff check src tests") == "ruff check --extend-exclude tools/cc src tests"
        for verbatim in ("ruff check --extend-exclude tools/cc .", "ruff check --exclude x .",
                         "ruff format --check .", "npm run lint", "make lint", "ruff"):
            assert f(verbatim) == verbatim, verbatim

    def test_suppress_outranks_a_declaration_as_the_plan_applies_it(self, tmp_path):
        """The plan builder merges [extra_actions] and then pops
        suppress_actions; /preflight and the allow rules read it the same way
        (the failure-mode review found three readers disagreeing)."""
        root = _node_root(
            tmp_path, toml='suppress_actions = ["build"]\n[extra_actions]\nbuild = ["npm run build:prod"]\n',
        )
        assert declared_action(root, "build") == ("suppressed", [])
        plan = build_harness_config(_minimal_fp(), config=HarnessConfig(
            extra_actions={"build": ["npm run build:prod"]}, suppress_actions=["build"],
        ))
        assert "build" not in plan.stable_actions

    @pytest.mark.contract
    def test_the_deployed_preflight_asks_for_exactly_the_preflight_actions(self):
        """One roster: the body's Step 1 and Step 2 ask preflight_command for
        PREFLIGHT_ACTIONS, in order, and the settings profile derives from
        the same tuple (an action added to one and not the others reds)."""
        import re

        from espalier.harness_config import PREFLIGHT_ACTIONS
        from espalier.settings_profiles import DERIVED_ACTIONS

        body = (
            Path(__file__).resolve().parent.parent / "espalier" / "assets" / "claude"
            / "commands" / "preflight.md"
        ).read_text(encoding="utf-8")
        asked = re.findall(r"preflight_command\('(\w+)'\)", body)
        looped = re.findall(r"for action in ([a-z ]+); do", body)
        assert asked == ["lint"] and len(looped) == 1, (asked, looped)
        assert tuple(asked + looped[0].split()) == PREFLIGHT_ACTIONS == DERIVED_ACTIONS


class TestRenderAgentTools:
    """The deploy's render of the runner agents' tools line touches the comma
    form only (the 2026-10-06 code review drove both other forms)."""

    RULES = ("Bash(npm test)", "Bash(npm test *)")

    @pytest.mark.parametrize("body", [
        "---\nname: x\ntools:\n  - Read\n---\nbody\n",          # a YAML block list
        "---\nname: x\ntools: [Read, Grep]\n---\nbody\n",       # a flow list
        "---\nname: x\n---\nbody\n",                            # no tools line: every tool
        "no frontmatter\ntools: Read\n",                         # a tools line outside it
        "---\nname: x\ntools: Read, Bash\n---\nbody\n",         # bare Bash grants all
    ])
    def test_other_forms_are_left_as_they_are(self, body):
        from espalier.harness_config import render_agent_tools

        assert render_agent_tools(body, self.RULES) == body

    def test_a_crlf_body_keeps_its_line_endings(self):
        from espalier.harness_config import render_agent_tools

        body = "---\r\nname: x\r\ntools: Read, Grep\r\n---\r\nbody\r\n"
        out = render_agent_tools(body, self.RULES)
        assert out == "---\r\nname: x\r\ntools: Read, Grep, Bash(npm test), Bash(npm test *)\r\n---\r\nbody\r\n"


class TestChooseAgents:
    def test_always_includes_code_reviewer(self):
        fp = _minimal_fp(test_commands=["pytest"])
        agents = choose_agents(fp)
        names = [a.name for a in agents]
        assert "code-reviewer" in names

    def test_test_writer_included_when_test_commands_exist(self):
        fp = _minimal_fp(test_commands=["pytest -q"])
        agents = choose_agents(fp)
        names = [a.name for a in agents]
        assert "test-writer" in names

    def test_test_writer_excluded_when_no_test_commands(self):
        fp = _minimal_fp(test_commands=[])
        agents = choose_agents(fp)
        names = [a.name for a in agents]
        assert "test-writer" not in names

    # The surface-keyed agents ship no body, so since 2026-10-06 (the operator's
    # call: demote, not ship) they are suggestions, never agents. These three
    # inverted by design: each used to assert the name joined the agents.
    def test_api_reviewer_suggested_not_chosen_for_api_surface(self):
        fp = _minimal_fp(api_surface=True, test_commands=["pytest"])
        assert "api-reviewer" not in [a.name for a in choose_agents(fp)]
        assert "api-reviewer" in [a.name for a in suggest_agents(fp)]

    def test_api_reviewer_excluded_without_api_surface(self):
        fp = _minimal_fp(api_surface=False)
        assert "api-reviewer" not in [a.name for a in choose_agents(fp)]
        assert "api-reviewer" not in [a.name for a in suggest_agents(fp)]

    def test_experiment_analyst_suggested_not_chosen_for_ml_surface(self):
        fp = _minimal_fp(ml_surface=True, test_commands=["pytest"])
        assert "experiment-analyst" not in [a.name for a in choose_agents(fp)]
        assert "experiment-analyst" in [a.name for a in suggest_agents(fp)]

    def test_component_reviewer_suggested_not_chosen_for_ui_surface(self):
        fp = _minimal_fp(ui_surface=True, test_commands=["pytest"])
        assert "component-reviewer" not in [a.name for a in choose_agents(fp)]
        assert "component-reviewer" in [a.name for a in suggest_agents(fp)]

    def test_every_chosen_agent_has_a_packaged_body(self):
        """The plan's agents are what init can put on disk: a fingerprint that
        trips every surface predicate still chooses only packaged bodies, and
        every predicate that fired is a suggestion instead."""
        from espalier.asset_inventory import packaged_agent_names
        from espalier.harness_config import OPTIONAL_AGENTS

        fp = _minimal_fp(
            test_commands=["pytest"], api_surface=True, ml_surface=True,
            ui_surface=True, ops_surface=True,
        )
        chosen = {a.name for a in choose_agents(fp)}
        assert chosen <= packaged_agent_names(), chosen - packaged_agent_names()
        assert {a.name for a in suggest_agents(fp)} == {row[0] for row in OPTIONAL_AGENTS}

    def test_an_optional_agent_with_a_body_is_chosen(self, monkeypatch):
        """The split keys on the packaged bodies, not on the table: the day a
        body ships for a surface agent, it is an agent again."""
        from espalier import asset_inventory

        real = asset_inventory.packaged_agent_names()
        monkeypatch.setattr(
            asset_inventory, "packaged_agent_names", lambda: real | {"component-reviewer"},
        )
        fp = _minimal_fp(ui_surface=True, test_commands=["pytest"])
        assert "component-reviewer" in [a.name for a in choose_agents(fp)]
        assert "component-reviewer" not in [a.name for a in suggest_agents(fp)]

    def test_the_plan_saves_suggestions_apart_from_agents(self):
        plan = build_harness_config(_minimal_fp(ui_surface=True, test_commands=["npm test"]))
        assert [a.name for a in plan.suggested_agents] == ["component-reviewer"]
        assert "component-reviewer" not in [a.name for a in plan.agents]
        assert plan.to_dict()["suggested_agents"][0]["name"] == "component-reviewer"

    def test_all_returned_are_agent_spec_instances(self):
        fp = _minimal_fp(test_commands=["pytest"], api_surface=True)
        agents = choose_agents(fp)
        assert all(isinstance(a, AgentSpec) for a in agents)


class TestScopePaths:
    def test_review_scope_includes_docs_and_runtime(self):
        fp = _minimal_fp(docs_surface=["README.md"], runtime_surface=["espalier/"])
        paths = _scope_paths("review", fp)
        assert "README.md" in paths
        assert "espalier/" in paths

    def test_validation_scope_includes_tests_when_test_commands(self):
        fp = _minimal_fp(test_commands=["pytest"], runtime_surface=["src/"])
        paths = _scope_paths("validation", fp)
        assert "tests" in paths

    def test_validation_scope_no_tests_when_no_test_commands(self):
        fp = _minimal_fp(test_commands=[], runtime_surface=["src/"])
        paths = _scope_paths("validation", fp)
        assert "tests" not in paths

    def test_no_duplicate_paths_in_result(self):
        fp = _minimal_fp(docs_surface=["README.md", "README.md"], runtime_surface=["README.md"])
        paths = _scope_paths("review", fp)
        assert paths.count("README.md") == 1

    def test_empty_strings_excluded(self):
        fp = _minimal_fp(docs_surface=["", "README.md"], runtime_surface=[])
        paths = _scope_paths("review", fp)
        assert "" not in paths

    def test_package_roots_slash_excluded(self):
        fp = _minimal_fp(package_roots=["/", ".", "espalier"])
        paths = _scope_paths("review", fp)
        assert "/" not in paths
        assert "." not in paths


class TestBuildHarnessConfig:
    def test_returns_build_plan(self):
        fp = _minimal_fp(test_commands=["pytest -q"])
        plan = build_harness_config(fp)
        assert isinstance(plan, BuildPlan)

    def test_plan_repo_name_matches_fingerprint(self):
        fp = _minimal_fp(repo_name="cool-repo", test_commands=["pytest"])
        plan = build_harness_config(fp)
        assert plan.repo_name == "cool-repo"

    def test_unresolved_question_when_no_test_commands(self):
        fp = _minimal_fp(test_commands=[])
        plan = build_harness_config(fp)
        assert any("test" in q.lower() for q in plan.unresolved_questions)

    def test_no_unresolved_question_when_test_commands_present(self):
        fp = _minimal_fp(test_commands=["pytest -q"], entrypoints=["espalier"])
        plan = build_harness_config(fp)
        assert not any("test" in q.lower() for q in plan.unresolved_questions)

    def test_unresolved_question_when_no_entrypoints(self):
        fp = _minimal_fp(entrypoints=[])
        plan = build_harness_config(fp)
        assert any("entrypoint" in q.lower() for q in plan.unresolved_questions)

    def test_generated_docs_equals_the_required_init_surface(self):
        """441-E / §18.4 — this REPLACES a tautology rather than tightening it.

        The prior body looped ``CORE_GENERATED_DOCS`` asserting each name was in
        ``plan.generated_docs``. But ``build_harness_config`` builds
        ``generated_docs`` FROM that same constant (harness_config.py:345,
        ``gen_docs = list(CORE_GENERATED_DOCS)``), so the row reduced to
        ``x in list(x_source)``. Driven: it passes with two members deleted,
        with the constant EMPTY, and with a FABRICATED member -- it could not
        fail in either direction. (That is also why 441-D's filed harm, "an
        adopter is told ``espalier audit .`` passes", came back FALSE when
        driven on a real adopter tree: the manifest arm still exits 1 naming
        cc/COMMANDS.md.)

        The invariant worth asserting is the one harness_config.py:150-152
        declares in PROSE and nothing anywhere asserted: CORE_GENERATED_DOCS is
        "kept aligned with render_surface.write_required_surface +
        surface_contract.get_required_init_files". Two independently-authored
        rosters, so neither side derives from the other and a deletion from
        EITHER reds.

        ⚠ ``sorted()`` is load-bearing, not idle defensiveness: the rosters are
        set-equal but ORDER-different at HEAD (CORE_GENERATED_DOCS leads with
        cc/LIVE_SURFACE.md, get_required_init_files with cc/COMMANDS.md).
        "Tidying" this to a bare ``==`` reds on a correct tree.
        """
        plan = build_harness_config(_minimal_fp())
        required = list(get_required_init_files())
        assert sorted(plan.generated_docs) == sorted(required), (
            "the docs `init` generates have drifted from the docs the surface "
            "gate requires -- a fresh init would leave `espalier audit .` "
            "reporting a missing artifact.\n"
            f"  plan.generated_docs      : {sorted(plan.generated_docs)}\n"
            f"  get_required_init_files(): {sorted(required)}\n"
            "Update BOTH rosters deliberately; they are cross-witnesses, not "
            "one derived from the other."
        )
        assert EXTENDED_GENERATED_DOCS == [], (
            "EXTENDED_GENERATED_DOCS is no longer empty, so build_harness_config "
            "extends generated_docs on an `extended` surface_mode and this "
            "assertion — which drives only the DEFAULT mode via _minimal_fp() — "
            "no longer covers what its own message claims. Its members are "
            "commented out today with 'Uncomment when the code that creates them "
            "is implemented'; the session that uncomments one must also add it "
            "to surface_contract's required-init roster, or a fresh init on an "
            "extended repo leaves `espalier audit .` reporting a missing "
            "artifact with this test still green. Parametrize over surface_mode "
            "rather than raising this pin."
        )
        assert sorted(CORE_GENERATED_DOCS) == sorted(required), (
            "CORE_GENERATED_DOCS itself drifted from "
            "surface_contract.get_required_init_files(); harness_config.py:150-152 "
            "promises these stay aligned and this is the only assertion of it.\n"
            f"  CORE_GENERATED_DOCS      : {sorted(CORE_GENERATED_DOCS)}\n"
            f"  get_required_init_files(): {sorted(required)}"
        )

    def test_core_generated_docs_is_still_a_hand_written_literal(self):
        """441-E, the fourth part of the attested DEF-595 fix shape.

        The parity above is only a real cross-witness while the two rosters are
        INDEPENDENTLY AUTHORED. This module already imports the surface_contract
        module at top level, and already derives a SIBLING roster from it in this
        same file: the canonical-hooks loop iterates
        `surface_contract.get_canonical_hook_scripts()` directly. So collapsing
        this constant to
        ``CORE_GENERATED_DOCS = list(surface_contract.get_required_init_files())``
        is ONE plausible DRY-up line, made BY someone tidying, not by someone
        breaking anything. It would silently reduce the assertion above to
        ``x == x`` and leave a green suite over an unwatched invariant.

        Found by the scheduled adversarial pass over this very fix, which is the
        point: §18.4 warns that the obvious fix is blind in the same direction,
        and DEF-595's closure measured this exact guard as load-bearing rather
        than belt-and-braces (without it, regenerating a roster while deleting a
        member ran fully green with a real hole open).

        AST-level, because the runtime value is identical either way -- that is
        precisely what makes the collapse invisible to every other assertion.
        """
        import ast
        from pathlib import Path

        import espalier.harness_config as hc_mod

        src = Path(hc_mod.__file__)
        tree = ast.parse(src.read_text(encoding="utf-8"))
        node = None
        for stmt in tree.body:
            targets = (
                stmt.targets if isinstance(stmt, ast.Assign)
                else [stmt.target] if isinstance(stmt, ast.AnnAssign) and stmt.value
                else []
            )
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "CORE_GENERATED_DOCS":
                    node = stmt.value
        assert node is not None, (
            "CORE_GENERATED_DOCS is no longer a module-level assignment in "
            f"{src.name}; the parity test above can no longer prove the two "
            "rosters are independent."
        )
        why = (
            "CORE_GENERATED_DOCS must stay a hand-written list of string "
            "literals. If it is ever computed -- most plausibly from "
            "surface_contract.get_required_init_files(), the very thing it is "
            "checked against -- then "
            "test_generated_docs_equals_the_required_init_surface silently "
            "becomes a tautology and stops watching anything. Keep the "
            "duplication; it IS the witness."
        )
        assert isinstance(node, (ast.List, ast.Tuple)), why
        assert node.elts, why
        for element in node.elts:
            assert (
                isinstance(element, ast.Constant) and isinstance(element.value, str)
            ), why

    def test_config_extra_actions_merged(self):
        fp = _minimal_fp()
        cfg = HarnessConfig(extra_actions={"my-action": ["my-command"]})
        plan = build_harness_config(fp, config=cfg)
        assert "my-action" in plan.stable_actions
        assert plan.stable_actions["my-action"] == ["my-command"]

    def test_config_suppress_actions_removed(self):
        fp = _minimal_fp(languages=["python"])
        cfg = HarnessConfig(suppress_actions=["scan"])
        plan = build_harness_config(fp, config=cfg)
        assert "scan" not in plan.stable_actions

    def test_read_only_zones_from_fingerprint_and_config(self):
        fp = _minimal_fp(generated_zones=["cc/"])
        cfg = HarnessConfig(generated_paths=["output/"])
        plan = build_harness_config(fp, config=cfg)
        assert "cc/" in plan.read_only_zones
        assert "output/" in plan.read_only_zones

    def test_default_config_used_when_none_provided(self):
        fp = _minimal_fp()
        plan = build_harness_config(fp)
        assert isinstance(plan.config, HarnessConfig)

    def test_hooks_list_not_empty(self):
        fp = _minimal_fp(test_commands=["pytest"])
        plan = build_harness_config(fp)
        assert len(plan.hooks) > 0


class TestCanonicalHookEmission:
    """Pack 2-D — only canonical hooks exist in emitted plans."""

    PHANTOM_SCRIPTS = (
        "settings_validator", "memory_guard", "blueprint_capture",
        "instructions_loaded", "subagent_logger", "test_pairing",
        "drift_detector", "commit_guard",
    )

    def test_no_phantom_scripts_emitted(self):
        fp = _minimal_fp(
            test_commands=["pytest"],
            git_conventions={"format": "conventional", "confidence": 0.9},
        )
        plan = build_harness_config(fp)
        scripts = [h.script for h in plan.hooks]
        for phantom in self.PHANTOM_SCRIPTS:
            assert not any(phantom in s for s in scripts), (
                f"Phantom script {phantom!r} still appears in hooks"
            )

    def test_all_emitted_script_paths_exist_on_disk(self, tmp_path):
        """For every emitted hook with a tools/cc/hooks/ path, the file exists
        under the Espalier-Harness source tree."""
        from espalier.cli import _espalier_root
        fp = _minimal_fp(test_commands=["pytest"])
        plan = build_harness_config(fp)
        harness_root = _espalier_root()
        for hook in plan.hooks:
            if hook.script.startswith("tools/cc/hooks/"):
                assert (harness_root / hook.script).exists(), (
                    f"Emitted hook path {hook.script!r} has no file on disk"
                )

    def test_task_router_wired_to_user_prompt_submit(self):
        fp = _minimal_fp()
        plan = build_harness_config(fp)
        task_router = next(
            (h for h in plan.hooks if h.script.endswith("/task_router.py")), None
        )
        assert task_router is not None, "task_router.py not emitted"
        assert task_router.event == "UserPromptSubmit"

    def test_write_guard_and_plan_guard_on_pre_tool_use(self):
        fp = _minimal_fp()
        plan = build_harness_config(fp)
        events_by_script = {h.script: h.event for h in plan.hooks}
        assert events_by_script.get("tools/cc/hooks/write_guard.py") == "PreToolUse"
        assert events_by_script.get("tools/cc/hooks/plan_guard.py") == "PreToolUse"

    def test_canonical_hook_count_matches_contract(self):
        """Exactly the canonical hook set is emitted (plus any formatter hook)."""
        from espalier import surface_contract
        fp = _minimal_fp()
        plan = build_harness_config(fp)
        script_hooks = [
            h for h in plan.hooks if h.script.startswith("tools/cc/hooks/")
        ]
        assert len(script_hooks) == len(surface_contract.get_canonical_hook_scripts())

    def test_extended_surface_mode_triggers_extended_docs(self):
        # EXTENDED_GENERATED_DOCS is a designed no-op today (commented out), so
        # "extended" mode currently yields EXACTLY CORE_GENERATED_DOCS — no
        # extras, no crash, and no difference from "core" mode. This locks that
        # reality: when EXTENDED_GENERATED_DOCS is eventually populated, this
        # assertion goes RED and forces the test (and its name) to be updated
        # to the real extended set, rather than silently passing on a no-op.
        fp = _minimal_fp()
        plan = build_harness_config(fp, config=HarnessConfig(surface_mode="extended"))
        assert plan.generated_docs == CORE_GENERATED_DOCS
        core_plan = build_harness_config(fp, config=HarnessConfig(surface_mode="core"))
        assert plan.generated_docs == core_plan.generated_docs

    def test_ruff_format_hook_added_when_pyproject_has_ruff_format_section(self, tmp_path):
        # TP-146 narrowed the heuristic: only `[tool.ruff.format]` opts the
        # user into format-on-write. A bare `[tool.ruff]` or
        # `[tool.ruff.lint]` block does not — those are commonly present
        # for lint config and should not implicitly inject a non-canonical
        # PostToolUse formatter hook into the plan.
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 100\n[tool.ruff.format]\nquote-style = \"double\"\n",
            encoding="utf-8",
        )
        fp = RepoFingerprint(repo_name="r", repo_root=str(tmp_path))
        plan = build_harness_config(fp)
        hook_scripts = [h.script for h in plan.hooks]
        assert any("ruff" in s for s in hook_scripts)

    def test_no_ruff_format_hook_when_pyproject_has_lint_only(self, tmp_path):
        # Counterpart: lint-only ruff config should NOT inject the format hook.
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 100\n[tool.ruff.lint]\nselect = [\"E\"]\n",
            encoding="utf-8",
        )
        fp = RepoFingerprint(repo_name="r", repo_root=str(tmp_path))
        plan = build_harness_config(fp)
        hook_scripts = [h.script for h in plan.hooks]
        assert not any("ruff format" in s for s in hook_scripts), (
            "Lint-only [tool.ruff.lint] config should not auto-inject a "
            "format-on-write hook (TP-146 heuristic narrowing)."
        )

    def test_black_hook_added_when_pyproject_has_black(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 100\n", encoding="utf-8")
        fp = RepoFingerprint(repo_name="r", repo_root=str(tmp_path))
        plan = build_harness_config(fp)
        hook_scripts = [h.script for h in plan.hooks]
        assert any("black" in s for s in hook_scripts)

    def test_no_formatter_hook_without_pyproject(self, tmp_path):
        fp = RepoFingerprint(repo_name="r", repo_root=str(tmp_path))
        plan = build_harness_config(fp)
        hook_scripts = [h.script for h in plan.hooks]
        assert not any("ruff" in s for s in hook_scripts)
        assert not any("black" in s for s in hook_scripts)


class TestBlobNamesScript:
    """DEF-618 blocker (found by both reviewers, driven): `script in blob` read
    an operator's `my_plan_guard.py` as a copy of `plan_guard.py`, so the
    classifier filed the gate as legacy-form and `--repair` deleted the
    operator's entry. One anchored predicate serves the classifier's blob
    reader and the repair."""

    def test_basename_equality_not_substring(self):
        from espalier.harness_config import blob_names_script as f

        assert f("python3 ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/plan_guard.py", "plan_guard.py")
        assert f('"C:\\Program Files\\Python\\python.exe" C:\\r\\tools\\cc\\hooks\\plan_guard.py', "plan_guard.py")
        assert f("plan_guard.py", "plan_guard.py")
        assert not f("python3 tools/cc/hooks/my_plan_guard.py", "plan_guard.py")
        assert not f("node ops/run.js tests/test_write_guard.py", "write_guard.py")
        assert not f("", "plan_guard.py")

    def test_the_classifier_reads_through_it(self, tmp_path):
        """An operator's `my_plan_guard.py` beside an absent `plan_guard.py`
        classifies ABSENT/ORPHANED, never legacy-form."""
        import json
        from espalier import harness_config as hc

        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "hooks" / "plan_guard.py").write_text("# x\n", encoding="utf-8")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
            "PreToolUse": [{"matcher": "Edit", "hooks": [{
                "type": "command", "command": "python3",
                "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/my_plan_guard.py"]}]}],
        }}), encoding="utf-8")
        assert hc.classify_unwired_gate(tmp_path, "plan_guard.py") == hc.GATE_ORPHANED

