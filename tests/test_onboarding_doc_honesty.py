# pytest-marker: default-unit
"""TP-189 ONBOARD-1 / ONBOARD-2: adopter-facing onboarding docs stay honest.

The harness's culture is anti-overclaim; these contracts pin the surfaces a
fresh adopter reads in their first hour so they cannot drift back into telling
the adopter to run a command that errors.

- ONBOARD-1 / EXEC-2: the uninstall instructions must not reference
  ``clean-generated`` flags that do not exist (``--dry-run``, ``--keep-config``).
  The real command exposes only ``--execute``; the dry run is the default
  (running it with no flag prints what would be removed without deleting).
- ONBOARD-2 / PUBINT-4 (added in the pip-honesty step): no shipped onboarding
  doc may lead the adopter with ``pip install espalier-harness`` unqualified —
  the distribution name is unclaimed on PyPI and install is fusion-from-source.
"""
from __future__ import annotations

import re

from _denied_form import every_form_is_denied
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Adopter-facing onboarding surfaces (what a new user reads in their first
# hour). Maintainer-only release docs (RELEASE_CHECKLIST.md, RELEASE_DECISIONS.md)
# are deliberately EXCLUDED: they legitimately describe the post-publish future
# state where `pip install espalier-harness` will work.
#
# The seeded half is DERIVED from ``managed_inventory.get_seed_docs()`` -- the
# list ``espalier init`` actually writes -- rather than hand-copied. The
# hand-copied tuple this replaced had drifted to 14 of the 20 seeds, so six
# deployed docs (CONVENTIONS, HOOK_ASSUMPTIONS, INSTALL-CI, SHARP_EDGES,
# sharp-edges/README, memory/README) were never scanned (DEF-640). Every doc
# an adopter can read must clear the same no-overclaim bar; the source/asset
# byte-parity contract keeps the mirrors in lockstep, so scanning the sources
# here covers the shipped assets too.
from espalier.managed_inventory import get_seed_docs

_ONBOARDING_DOCS = tuple(dict.fromkeys((
    "README.md",
    "docs/QUICKSTART.md",
    "docs/TROUBLESHOOTING.md",
    "espalier/assets/docs/TROUBLESHOOTING.md",
    "examples/README.md",
    *get_seed_docs(),
)))


def _existing_docs() -> list[tuple[str, str]]:
    """(rel_path, text) for each onboarding doc that exists on disk."""
    out: list[tuple[str, str]] = []
    for rel in _ONBOARDING_DOCS:
        p = REPO_ROOT / rel
        if p.is_file():
            out.append((rel, p.read_text(encoding="utf-8")))
    return out


class TestCleanGeneratedFlags:
    """ONBOARD-1 / EXEC-2: only ``--execute`` exists; dry-run is the default."""

    # Both strings name flags that `espalier clean-generated --help` does not
    # list. Either one in an onboarding doc dead-ends an adopter with
    # `error: unrecognized arguments`.
    @pytest.mark.parametrize(
        "fiction", ["clean-generated --dry-run", "--keep-config"]
    )
    def test_no_fictional_clean_generated_flag(self, fiction: str) -> None:
        offenders = [rel for rel, text in _existing_docs() if fiction in text]
        assert not offenders, (
            f"onboarding doc(s) reference the nonexistent `{fiction}`. "
            f"`clean-generated` exposes only --execute; the dry run is the "
            f"default (no flag). Offending docs: {offenders}"
        )


_PIP_PHRASE = "pip install espalier-harness"

# Phrases that make a `pip install espalier-harness` mention honest: each
# SPECIFICALLY signals the PyPI channel is not yet the install path. The token
# is allowed only when one of these appears in the same neighborhood (the name
# is unclaimed on PyPI today; install is fusion-from-source). A bare "not yet"
# is deliberately NOT here — it is too generic and could incidentally collide
# with unrelated prose; the qualifier must name the publish/install status.
_PUBLISH_QUALIFIERS = (
    "not yet the install path",
    "not yet published",
    "not yet claimed",
    "not yet on pypi",
    "once that channel",
    "once published",
    "once it is published",
    "when published",
    "is planned",
    "planned but",
    "pre-release",
    "unpublished",
    "current install path",
    "if you installed espalier as a package",
    "if you pip-installed",
)

_WINDOW = 200  # chars of context on each side of a match


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace so a line-wrapped `pip install\\nespalier-
    harness` is matched the same as the inline phrase."""
    return re.sub(r"\s+", " ", text)


class TestPipInstallHonesty:
    """ONBOARD-2 / PUBINT-4: no onboarding doc leads the adopter with an
    unqualified ``pip install espalier-harness`` — install is fusion-from-source
    and the distribution name is unclaimed on PyPI."""

    def test_pip_install_only_appears_qualified(self) -> None:
        offenders: list[str] = []
        for rel, raw in _existing_docs():
            text = _normalize_ws(raw).lower()
            start = 0
            while (i := text.find(_PIP_PHRASE, start)) != -1:
                window = text[max(0, i - _WINDOW) : i + len(_PIP_PHRASE) + _WINDOW]
                if not any(q in window for q in _PUBLISH_QUALIFIERS):
                    offenders.append(f"{rel} (offset ~{i})")
                start = i + len(_PIP_PHRASE)
        assert not offenders, (
            "onboarding doc(s) mention `pip install espalier-harness` without a "
            "nearby 'not yet published / once published' qualifier. The PyPI "
            "name is unclaimed; install is fusion-from-source. Qualify the "
            "mention or remove it:\n  " + "\n  ".join(offenders)
        )


# ---------------------------------------------------------------------------
# README ships as the PyPI ``long_description`` (``pyproject.toml`` readme key).
# ``readme_renderer`` does NOT rewrite relative hrefs, so any relative markdown
# link renders as a dead link on the PyPI project page even though it resolves
# perfectly in the repo and in GitHub's own rendering. That asymmetry is why
# every working-tree check stays green while the published page is broken:
# the only oracle that can see it is one that reads README as the artifact it
# becomes. In-page ``#fragment`` anchors are fine (PyPI keeps them), as are
# ``mailto:`` and absolute URLs.
# ---------------------------------------------------------------------------

_RELATIVE_LINK_RE = re.compile(r"\][(](?!https?://|#|mailto:)([^)]+)[)]")


class TestReadmeLinksSurviveThePypiPage:
    """COMMHEALTH-04: README's links must resolve for a PyPI reader."""

    def test_readme_has_no_relative_markdown_links(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        relative = _RELATIVE_LINK_RE.findall(text)
        assert not relative, (
            "README.md carries relative markdown link(s). README ships as the "
            "PyPI long_description and readme_renderer does not rewrite "
            "relative hrefs, so each of these 404s on the project page while "
            "resolving fine in the repo. Use an absolute "
            "https://github.com/<owner>/<repo>/blob/main/<path> URL:\n  "
            + "\n  ".join(relative)
        )

    def test_readme_actually_carries_links(self) -> None:
        """Non-vacuous floor.

        Without this, a README reformat that stopped matching the link syntax
        would turn the assertion above into a permanent silent pass — the
        born-weak-gate shape this repo keeps re-finding.
        """
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        all_links = re.findall(r"\][(]([^)]+)[)]", text)
        assert len(all_links) >= 10, (
            "README carries fewer markdown links than expected "
            f"({len(all_links)}) — did the link syntax or the file change? "
            "The relative-link assertion above is only meaningful while this "
            "population is non-trivial."
        )


# ---------------------------------------------------------------------------
# DEF-640 / DEF-676: the relaunch an adopter is told to type must work in
# their shell and keep their session
# ---------------------------------------------------------------------------

# A line that IS a launch command (fenced form) or PRESCRIBES one in prose.
# The denied form (`ESPALIER_MAINTENANCE_MODE=1 claude -p ...` quoted as what
# NOT to do) sits behind a backticked `claude` and is not matched.
# Any position on the line: the fenced form, the labelled block form
# (`POSIX / Git Bash / WSL:  ESPALIER_…=1 claude --continue`, which is what the
# docs adopted and a `^\s*` anchor could not see), and a prose mention. The
# one shape excluded is the DENIED form quoted as what not to do
# (`… claude -p …`) -- and only when the line SAYS so. The first version
# exempted the `-p` token globally, so a remedy spelled `... claude -p ...`
# would have passed this gate and the hook scan alike (DEF-692); the exemption
# is now anchored to the denied-form context on the same line.
_POSIX_LAUNCH_LINE_RE = re.compile(r"ESPALIER_[A-Z_]+=\S+\s+claude\b")
_P_FORM_RE = re.compile(r"ESPALIER_[A-Z_]+=\S+\s+claude\s+-p\b")


def _is_prescribed_launch_line(line: str) -> bool:
    """A line that prescribes a launch -- not the denied `-p` form quoted as
    what not to do. The `-p` form is exempt only with a denied-context word
    WITHIN REACH of it (`tests/_denied_form.py`, shared with the maintenance
    gate); a bare `-p` remedy is a launch line and is held to the same
    siblings, and so is one that merely has a `not` elsewhere on the line."""
    if not _POSIX_LAUNCH_LINE_RE.search(line):
        return False
    if every_form_is_denied(line, _P_FORM_RE):
        return False
    return True
_POWERSHELL_LAUNCH_RE = re.compile(r"\$env:ESPALIER_[A-Z_]+\s*=")
_NEIGHBOURHOOD = 6  # lines on either side that count as "the same instruction"


def _deployed_bodies() -> list[tuple[str, str]]:
    """The onboarding docs plus every deployed command / skill / agent body."""
    out = list(_existing_docs())
    roots = (
        sorted((REPO_ROOT / ".claude" / "commands").glob("*.md")),
        sorted((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md")),
        sorted((REPO_ROOT / ".claude" / "agents").glob("*.md")),
    )
    for group in roots:
        for path in group:
            out.append((path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    return out


def _launch_sites() -> list[tuple[str, int, list[str]]]:
    sites = []
    for rel, text in _deployed_bodies():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if _is_prescribed_launch_line(line):
                lo, hi = max(0, i - _NEIGHBOURHOOD), min(len(lines), i + _NEIGHBOURHOOD + 1)
                sites.append((rel, i + 1, lines[lo:hi]))
    return sites


class TestTheDeniedFormCarveIsContextKeyed:
    """DEF-692: the `-p` exemption was a token carve, so a remedy spelled with
    `-p` and no denied context passed the gate. It is keyed to the context now;
    each arm has its negative twin."""

    @pytest.mark.parametrize("line", [
        "Don't run `ESPALIER_MAINTENANCE_MODE=1 claude -p ...` -- it drops your session",
        "the denied form (`ESPALIER_MAINTENANCE_MODE=1 claude -p x`) is refused by write_guard",
        "never launch with ESPALIER_MAINTENANCE_MODE=1 claude -p",
        "you should not run ESPALIER_MAINTENANCE_MODE=1 claude -p",
        "and don't launch `claude` with one (`ESPALIER_MAINTENANCE_MODE=1 claude -p ...`, or behind a wrapper",
    ])
    def test_the_denied_form_in_denied_context_is_exempt(self, line):
        assert not _is_prescribed_launch_line(line)

    @pytest.mark.parametrize("line", [
        "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p resume",
        "POSIX: ESPALIER_MAINTENANCE_MODE=1 claude -p",
        # a `not` elsewhere on the line does not launder a remedy: the first
        # re-key checked co-occurrence and this passed (code-reviewer, driven)
        "do not forget to relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p resume",
        "This is not optional: relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p",
        # a negation that governs something ELSE, or a refusal of the
        # complement, is no denial of the form (re-review, driven 4 of 5)
        "do not launch it any other way than ESPALIER_MAINTENANCE_MODE=1 claude -p x",
        "never use --continue, relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p",
        "if not run with ESPALIER_MAINTENANCE_MODE=1 claude -p, the fix is lost",
        "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p; anything else is refused",
        # a second, bare form after an exempted quote is still a remedy: the
        # first cut checked the first form only (re-review, driven)
        "the denied form (`ESPALIER_MAINTENANCE_MODE=1 claude -p ...`) misleads; just run ESPALIER_MAINTENANCE_MODE=1 claude -p directly",
        # a refusal turned into a condition is not a denial of the form
        "ESPALIER_MAINTENANCE_MODE=1 claude -p is refused unless you pass --continue",
        "ESPALIER_MAINTENANCE_MODE=1 claude --continue",
        "POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude --continue",
    ])
    def test_a_launch_line_without_denied_context_is_held_to_the_gate(self, line):
        assert _is_prescribed_launch_line(line)


class TestRelaunchLinesArePortable:
    """A bare ``VAR=1 claude`` is a PowerShell parse error, so every shipped
    POSIX launch line needs a PowerShell sibling within reach; and a relaunch
    without ``--continue`` starts a new conversation, losing the session the
    adopter was denied in, so the same neighbourhood must offer it."""

    def test_the_gate_engages(self) -> None:
        """A named site, not a count floor: the deny's own remedy sends the
        adopter to docs/TROUBLESHOOTING.md, so that doc must be in the net."""
        rels = {rel for rel, _lineno, _hood in _launch_sites()}
        assert "docs/TROUBLESHOOTING.md" in rels, sorted(rels)
        assert "docs/FAILURE_MODES.md" in rels, sorted(rels)

    def test_every_posix_launch_line_has_a_powershell_sibling(self) -> None:
        offenders = [
            f"{rel}:{lineno}" for rel, lineno, hood in _launch_sites()
            if not any(_POWERSHELL_LAUNCH_RE.search(ln) for ln in hood)
        ]
        assert not offenders, (
            "POSIX-only relaunch line with no PowerShell form nearby "
            "(a Windows adopter gets a parse error):\n  " + "\n  ".join(offenders)
        )

    def test_every_relaunch_neighbourhood_offers_continue(self) -> None:
        """Only where the instruction is a RELAUNCH (the deny remedy); a plain
        launch option such as `ESPALIER_STOP_GATE=full claude` is a fresh
        session by intent."""
        offenders = [
            f"{rel}:{lineno}" for rel, lineno, hood in _launch_sites()
            if any("relaunch" in ln.lower() for ln in hood)
            and not any("--continue" in ln for ln in hood)
        ]
        assert not offenders, (
            "relaunch instruction that never mentions --continue "
            "(following it loses the session):\n  " + "\n  ".join(offenders)
        )
