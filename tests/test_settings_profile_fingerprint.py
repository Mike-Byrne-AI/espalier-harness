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

Failure mode prevented: a future contributor adds a new test-binary
detector to ``analyze.detect_tests`` (e.g. ``mix test`` for Elixir)
and forgets to extend the workflow profile. The parametrized matrix
here re-renders the helper against the canonical input shape and
fails when the binary doesn't propagate.
"""
import pytest

from espalier.settings_profiles import _SELF_HOST, _WORKFLOW

FINGERPRINTS: tuple[tuple[str, dict, str | None], ...] = (
    ("python_pytest", {"test_commands": ["pytest -q"]}, "Bash(pytest *)"),
    ("typescript_npm", {"test_commands": ["npm test"]}, "Bash(npm *)"),
    ("go", {"test_commands": ["go test ./..."]}, "Bash(go *)"),
    ("rust_cargo", {"test_commands": ["cargo test"]}, "Bash(cargo *)"),
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


def test_workflow_static_allow_preserved_under_merge():
    """The fingerprint helper MUST NOT remove static curated patterns."""
    derived = _WORKFLOW.fingerprint_allows({"test_commands": ["go test ./..."]})
    # Static patterns are still in _WORKFLOW.allow regardless of derived.
    assert "Bash(pytest *)" in _WORKFLOW.allow
    assert "Bash(git status)" in _WORKFLOW.allow
    # Derived adds, doesn't replace.
    assert "Bash(go *)" in derived


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
    assert "Bash(pytest *)" in derived
    assert "Bash(make *)" in derived


def test_workflow_non_string_command_skipped():
    """Defensive: a malformed fingerprint entry (None, int) is ignored,
    not crashed on. Catches a real-world fingerprint corruption shape."""
    derived = _WORKFLOW.fingerprint_allows(
        {"test_commands": ["pytest -q", None, 42, "go test"]}
    )
    assert "Bash(pytest *)" in derived
    assert "Bash(go *)" in derived


def test_workflow_dedup_across_commands():
    """Two test_commands that emit the same Bash() pattern only land once."""
    derived = _WORKFLOW.fingerprint_allows(
        {"test_commands": ["go test ./...", "go vet ./..."]}
    )
    assert derived.count("Bash(go *)") == 1


def test_self_host_inherits_workflow_helper():
    """Self-host profile uses the same fingerprint translator — adopters
    governing meta-tooling in non-Python repos still get auto-allows."""
    derived = _SELF_HOST.fingerprint_allows({"test_commands": ["cargo test"]})
    assert "Bash(cargo *)" in derived


def test_a_python_script_command_never_derives_the_broad_grant():
    """`python run_tests.py` used to derive `Bash(python *)` -- the exact
    broad grant the static self-host list forbids -- under one spelling."""
    derived = _WORKFLOW.fingerprint_allows({"test_commands": ["python run_tests.py", "python3 tools/check.py --all"]})
    assert "Bash(python *)" not in derived and "Bash(python3 *)" not in derived
    assert {"Bash(python run_tests.py *)", "Bash(python3 run_tests.py *)",
            "Bash(python tools/check.py *)", "Bash(python3 tools/check.py *)"} <= set(derived), derived

