"""TP-119: settings.json allow-list must reflect fingerprint
``test_commands`` / ``build_commands``.

Pins the parity between what ``analyze.detect_tests`` writes to
``reports/repo_fingerprint.json`` and what ``espalier init``
ultimately emits in ``.claude/settings.json[permissions.allow]``.
Sister-class to TP-30's ``_build_claude_md_uses_fingerprint``
contract — same defect shape: the renderer ignores fingerprint data
it has been given.

Without this contract, the workflow profile's static allow-list
remains Python-monoculture. TypeScript / Go / Rust / Elixir / .NET
adopters following QUICKSTART hit a permission-prompt flood on
``npm test``, ``cargo build``, ``go test`` because the fingerprint
value (already written by the language detector) never reaches the
settings renderer.

Since 2026-10-06 each derived rule is narrowed to its command's prefix
(``Bash(npm test)`` with ``Bash(npm test *)``, ``Bash(npm run build *)``,
``Bash(go test *)``), never the bare binary: ``Bash(npm *)`` pre-approved
``npm install``, ``npm exec --yes`` and every script (DEF-965, the operator's
call DEC-37 branch (a)). The four rows that pinned ``Bash(npm *)``,
``Bash(go *)``, ``Bash(cargo *)`` and ``Bash(make *)`` moved to the narrowed
shapes, and each bare binary is now a never-derived row beside the existing
``Bash(python *)`` ones.

Failure mode prevented: a future contributor adds a new test-binary
detector to ``analyze.detect_tests`` (e.g. ``mix test`` for Elixir)
and forgets to extend the workflow profile. The parametrized matrix
here re-renders the helper against the canonical input shape and
fails when the binary doesn't propagate.
"""
import pytest

from espalier.cli import _profile_allow_list
from espalier.settings_profiles import PYTHON_ONLY_ALLOWS, _SELF_HOST, _WORKFLOW

FINGERPRINTS: tuple[tuple[str, dict, str | None], ...] = (
    ("python_pytest", {"test_commands": ["pytest -q"]}, "Bash(pytest -q *)"),
    ("typescript_npm", {"test_commands": ["npm test"]}, "Bash(npm test *)"),
    # Both forms: the pinned docs do not settle whether the wildcard form
    # matches the bare command, so the exact rule ships beside it.
    ("typescript_npm_exact", {"test_commands": ["npm test"]}, "Bash(npm test)"),
    ("go", {"test_commands": ["go test ./..."]}, "Bash(go test *)"),
    ("rust_cargo", {"test_commands": ["cargo test"]}, "Bash(cargo test *)"),
    ("make", {"test_commands": ["make test"]}, "Bash(make test *)"),
    (
        "python_module",
        {"test_commands": ["python -m unittest discover"]},
        "Bash(python -m unittest *)",
    ),
    (
        # DEF-714: the spelling the fingerprint recorded is one of two the
        # adopter's Claude may type; the derived rule carries both.
        "python3_module_gets_its_python_twin",
        {"test_commands": ["python3 -m unittest discover"]},
        "Bash(python -m unittest *)",
    ),
    (
        "python_module_gets_its_python3_twin",
        {"test_commands": ["python -m unittest discover"]},
        "Bash(python3 -m unittest *)",
    ),
    (
        # The recorded spelling itself survives (an implementation that
        # collapsed python3 to python would pass the twin rows alone).
        "python3_module_keeps_python3",
        {"test_commands": ["python3 -m unittest discover"]},
        "Bash(python3 -m unittest *)",
    ),
    (
        # A script command narrows to the script under both names -- never
        # the broad `Bash(python *)` (failure-mode review, DEF-714).
        "python_script_is_narrow_and_twinned",
        {"test_commands": ["python run_tests.py"]},
        "Bash(python3 run_tests.py *)",
    ),
    ("empty_fp", {"test_commands": []}, None),  # no derived patterns
)

#: Commands whose bare binary must never derive: each is a package installer,
#: a script runner or a build driver, so `Bash(<binary> *)` pre-approves far
#: more than the fingerprinted command.
NEVER_DERIVED: tuple[tuple[str, str], ...] = (
    ("npm test", "Bash(npm *)"),
    ("npm run build", "Bash(npm *)"),
    ("npm run build", "Bash(npm run *)"),
    ("npm run", "Bash(npm run *)"),
    ("pnpm run -s build", "Bash(pnpm run *)"),
    ("yarn test", "Bash(yarn *)"),
    ("go test ./...", "Bash(go *)"),
    ("cargo test", "Bash(cargo *)"),
    ("make test", "Bash(make *)"),
    ("make", "Bash(make *)"),
    ("pytest -q", "Bash(pytest *)"),
    ("python run_tests.py", "Bash(python *)"),
    ("python -m", "Bash(python -m *)"),
    # Code or a package run by name, not the repository's own command
    # (the 2026-10-06 reviews drove each): exact form only.
    ("python -c print(1)", "Bash(python -c *)"),
    ("node -e 1", "Bash(node -e *)"),
    ("npm exec --yes foo", "Bash(npm exec *)"),
    ("pnpm dlx create-x", "Bash(pnpm dlx *)"),
    ("npx vitest", "Bash(npx vitest *)"),
    ("uv run pytest", "Bash(uv run *)"),
    ("uv run python -c 1", "Bash(uv run python *)"),
    ("poetry run pytest", "Bash(poetry run *)"),
    ("docker compose run web", "Bash(docker compose *)"),
)


@pytest.mark.parametrize(
    "name,fp,expected",
    FINGERPRINTS,
    ids=[t[0] for t in FINGERPRINTS],
)
def test_workflow_fingerprint_derives_allow(name, fp, expected):
    derived = _WORKFLOW.fingerprint_allows(fp)
    if expected is None:
        assert derived == ()
    else:
        assert expected in derived, (
            f"Fingerprint {name!r} (test_commands={fp['test_commands']!r}) "
            f"should derive {expected!r} but got: {derived!r}"
        )


@pytest.mark.parametrize("command,broad", NEVER_DERIVED, ids=[f"{c}->{b}" for c, b in NEVER_DERIVED])
def test_a_bare_binary_never_derives(command, broad):
    derived = _WORKFLOW.fingerprint_allows(
        {"test_commands": [command], "inferred_actions": {"build": [command], "lint": [command]}},
        extra_actions={"lint": [command], "test": [command], "build": [command]},
    )
    assert broad not in derived, derived


def test_workflow_static_allow_preserved_under_merge():
    """The fingerprint helper MUST NOT remove static curated patterns."""
    derived = _WORKFLOW.fingerprint_allows({"test_commands": ["go test ./..."]})
    # Static patterns are still in _WORKFLOW.allow regardless of derived.
    assert "Bash(pytest *)" in _WORKFLOW.allow
    assert "Bash(git status)" in _WORKFLOW.allow
    # Derived adds, doesn't replace.
    assert "Bash(go test *)" in derived


def test_workflow_build_commands_also_derive():
    """TP-151 G-3: build commands live under ``inferred_actions['build']`` (a
    ``list[str]`` written by ``analyze.detect_actions`` — e.g. ``["make build"]``
    / ``["npm run build"]``), NOT a top-level ``build_commands`` key. The real
    fingerprint never carries ``build_commands`` (verified against
    ``reports/repo_fingerprint.json``), so the prior fabricated-shape test gave
    false confidence: the consumer's build-derive branch never fired on a real
    fingerprint. Drive the real shape."""
    derived = _WORKFLOW.fingerprint_allows(
        {
            "test_commands": ["pytest -q"],
            "inferred_actions": {"build": ["make build"]},
        }
    )
    assert "Bash(pytest -q *)" in derived
    assert "Bash(make build *)" in derived


def test_lint_and_declared_commands_derive_too():
    """The prompt count stays low under narrowing because the repository's
    own lint and its espalier.toml declarations derive rules as well. A
    declared command derives its EXACT form only: an adopter can declare
    anything there, and /preflight runs it as written."""
    derived = _WORKFLOW.fingerprint_allows(
        {"test_commands": ["npm test"], "inferred_actions": {"lint": ["npm run lint"]}},
        extra_actions={"lint": ["npm run typecheck"], "test": ["uv run pytest -q"],
                       "deploy": ["npm publish"]},
    )
    assert {"Bash(npm run lint)", "Bash(npm run lint *)",
            "Bash(npm run typecheck)", "Bash(uv run pytest -q)"} <= set(derived), derived
    assert "Bash(npm run typecheck *)" not in derived and "Bash(uv run pytest -q *)" not in derived
    assert not any("publish" in rule for rule in derived), (
        "only lint, test and build derive; a declared deploy action is not pre-approved"
    )


def test_a_suppressed_action_derives_nothing():
    """suppress_actions removes an action from the plan, so its rules do not
    render either (the readers agree on precedence: suppress wins)."""
    fp = {"test_commands": ["npm test"], "inferred_actions": {"build": ["npm run build"]}}
    derived = _WORKFLOW.fingerprint_allows(
        fp, extra_actions={"build": ["npm run build:prod"]}, suppressed=["build", "test"],
    )
    assert not any(("build" in r) or ("npm test" in r) for r in derived), derived


def test_a_tool_wrapper_derives_the_wrapped_commands_rule():
    derived = _WORKFLOW.fingerprint_allows({"test_commands": ["uv run pytest -q", "poetry run python -m pytest"]})
    assert {"Bash(uv run pytest -q)", "Bash(uv run pytest -q *)",
            "Bash(poetry run python -m pytest *)", "Bash(poetry run python3 -m pytest *)"} <= set(derived), derived


def test_workflow_non_string_command_skipped():
    """Defensive: a malformed fingerprint entry (None, int) is ignored,
    not crashed on. Catches a real-world fingerprint corruption shape."""
    derived = _WORKFLOW.fingerprint_allows(
        {"test_commands": ["pytest -q", None, 42, "go test"]}
    )
    assert "Bash(pytest -q *)" in derived
    assert "Bash(go test *)" in derived


def test_workflow_dedup_across_commands():
    """Two test_commands that emit the same Bash() pattern only land once."""
    derived = _WORKFLOW.fingerprint_allows(
        {"test_commands": ["go test ./...", "go test -race ./..."]}
    )
    assert derived.count("Bash(go test *)") == 1


def test_self_host_inherits_workflow_helper():
    """Self-host profile uses the same fingerprint translator — adopters
    governing meta-tooling in non-Python repos still get auto-allows."""
    derived = _SELF_HOST.fingerprint_allows({"test_commands": ["cargo test"]})
    assert "Bash(cargo test *)" in derived
    assert "Bash(cargo *)" not in derived


def test_a_python_script_command_never_derives_the_broad_grant():
    """`python run_tests.py` used to derive `Bash(python *)` -- the exact
    broad grant the static self-host list forbids -- under one spelling."""
    derived = _WORKFLOW.fingerprint_allows({"test_commands": ["python run_tests.py", "python3 tools/check.py --all"]})
    assert "Bash(python *)" not in derived and "Bash(python3 *)" not in derived
    assert {"Bash(python run_tests.py *)", "Bash(python3 run_tests.py *)",
            "Bash(python tools/check.py *)", "Bash(python3 tools/check.py *)"} <= set(derived), derived


_NODE_FP = {
    "languages": ["javascript", "astro"],
    "test_commands": ["npm test"],
    "inferred_actions": {"lint": ["npm run lint"], "build": ["npm run build"]},
}


@pytest.mark.parametrize("profile", ["workflow", "self-host"])
def test_a_node_only_render_carries_no_python_rule(profile):
    """DEF-965: the pytest, ruff and black rules went to every repository; on
    a Node tree the only Python is the harness's vendored tools/cc/, which an
    unprompted `ruff format .` rewrote into integrity drift."""
    allow = _profile_allow_list(profile, fingerprint=_NODE_FP, posix=True)
    assert not (PYTHON_ONLY_ALLOWS & set(allow)), sorted(PYTHON_ONLY_ALLOWS & set(allow))
    assert {"Bash(npm test)", "Bash(npm test *)", "Bash(npm run lint *)",
            "Bash(npm run build *)"} <= set(allow), allow
    assert not any(rule in allow for rule in ("Bash(npm *)", "Bash(npm run *)")), allow


@pytest.mark.parametrize("profile", ["workflow", "self-host"])
def test_a_python_render_keeps_the_python_rules(profile):
    allow = _profile_allow_list(
        profile, fingerprint={"languages": ["python"], "test_commands": ["pytest -q"]}, posix=True,
    )
    assert PYTHON_ONLY_ALLOWS <= set(allow), sorted(PYTHON_ONLY_ALLOWS - set(allow))


@pytest.mark.parametrize("languages,expected", [
    (["javascript"], {"Bash(npm *)", "Bash(ruff *)", "Bash(pytest *)"}),
    (["python", "javascript"], {"Bash(npm *)"}),
])
def test_an_existing_install_is_told_of_the_broad_rules_an_older_init_wrote(tmp_path, languages, expected):
    """The narrowing reaches a fresh install only, and the merge never removes
    a rule: an install from before 2026-10-06 keeps `Bash(npm *)` (and, on a
    tree without Python, the Python rules). Doctor's twin names them; a rule
    the profile still renders, or one the operator spelled otherwise, is not
    named."""
    import json

    from espalier.cli import settings_superseded_allows

    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "repo_fingerprint.json").write_text(json.dumps({
        "languages": languages, "test_commands": ["npm test"],
        "inferred_actions": {"build": ["npm run build"]},
    }), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": [
        "Bash(npm *)", "Bash(ruff *)", "Bash(pytest *)", "Bash(git status)",
        "Bash(npm test *)", "Bash(npm:*)",
    ]}}), encoding="utf-8")
    got = dict(settings_superseded_allows(settings, profile="workflow", repo_root=tmp_path))
    assert set(got) == expected, got
    assert settings_superseded_allows(settings, profile="full", repo_root=tmp_path) == ()


def test_no_fingerprint_is_not_a_python_one():
    """init writes the fingerprint before it renders settings, so a render
    without one has nothing to say the repository is Python."""
    allow = _profile_allow_list("workflow", fingerprint=None, posix=True)
    assert not (PYTHON_ONLY_ALLOWS & set(allow)), allow
    assert "Bash(git status)" in allow
