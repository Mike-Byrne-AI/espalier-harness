"""TP-32: ``_build_claude_md`` must use ``fp.test_commands``, not
hardcoded pytest.

Pre-fix: every generated ``CLAUDE.md`` said ``'pytest -q'`` regardless
of detected language. This test parametrizes on the four major
language fingerprints and pins the rule that fingerprint-driven
test-command selection actually fires through ``_build_claude_md``.
Without this contract a hardcoded fallback could silently re-emerge,
regressing every adopter's ``CLAUDE.md`` to the pre-TP-32 mis-claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from espalier.cli import _build_claude_md


@dataclass
class _FakeFingerprint:
    repo_name: str = "test"
    languages: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)


@dataclass
class _FakeHarness:
    profiles: list[str] = field(default_factory=list)
    agents: list = field(default_factory=list)


@pytest.mark.parametrize(
    "language, test_command",
    [
        ("python", "pytest -q"),
        ("rust", "cargo test"),
        ("go", "go test ./..."),
        ("node", "npm test"),
    ],
)
def test_renderer_uses_detected_test_command(language, test_command):
    fp = _FakeFingerprint(
        repo_name="myproject",
        languages=[language],
        test_commands=[test_command],
    )
    harness = _FakeHarness(profiles=[f"{language}_library"], agents=[])
    rendered = _build_claude_md(fp, harness)
    assert test_command in rendered, (
        f"CLAUDE.md for {language} project should reference "
        f"{test_command!r} but doesn't.\n"
        f"Rendered:\n{rendered[-500:]}"
    )


def test_renderer_falls_back_to_pytest_when_no_commands():
    """Repos with no detected test_commands fall back to pytest -q."""
    fp = _FakeFingerprint(
        repo_name="empty",
        languages=["python"],
        test_commands=[],
    )
    harness = _FakeHarness(profiles=["python_library"], agents=[])
    rendered = _build_claude_md(fp, harness)
    assert "pytest -q" in rendered, (
        "Fallback to pytest -q failed when test_commands is empty."
    )


def test_renderer_rust_does_not_mention_pytest():
    """A Rust project's CLAUDE.md must not tell the user to run pytest."""
    fp = _FakeFingerprint(
        repo_name="rusty",
        languages=["rust"],
        test_commands=["cargo test"],
    )
    harness = _FakeHarness(profiles=["rust_library"], agents=[])
    rendered = _build_claude_md(fp, harness)
    build_section_start = rendered.find("## Build & Test")
    assert build_section_start != -1, "No '## Build & Test' section"
    build_section = rendered[build_section_start:build_section_start + 300]
    assert "pytest" not in build_section.lower(), (
        f"Rust project's Build & Test section mentions pytest:\n"
        f"{build_section}"
    )
