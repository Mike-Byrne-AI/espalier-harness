# pytest-marker: default-unit
"""TP-189 ONBOARD-1 / ONBOARD-2: adopter-facing onboarding docs stay honest.

The harness's culture is anti-overclaim; these contracts pin the surfaces a
fresh adopter reads in their first hour so they cannot drift back into telling
the adopter to run a command that errors.

- ONBOARD-1 / EXEC-2: the uninstall instructions must not reference
  ``clean-generated`` flags that do not exist (``--dry-run``, ``--keep-config``).
  The real command exposes only ``--execute``; the dry run is the default
  (running it with no flag prints what would be removed without deleting).
- ONBOARD-2 / PUBINT-4 (the pip-honesty step, INVERTED at the v0.8.0b1 cut):
  until 2026-09-25 the distribution name was unclaimed on PyPI, so a shipped
  onboarding doc could mention ``pip install espalier-harness`` only beside a
  "not yet published" qualifier. The release flipped the premise -- 0.8.0b1 is
  on PyPI and a plain ``pip install`` resolves it in a fresh venv with no
  ``--pre`` -- so the same qualifiers are now the overclaim in the other
  direction: an adopter who reads one clones the repo and builds an editable
  install they do not need. No onboarding doc may deny the channel, and the two
  first-hour docs must carry the install line itself.
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

# Phrases that DENY the PyPI channel. Until 2026-09-25 these were the
# qualifiers that made a `pip install espalier-harness` mention honest (the
# name was unclaimed; install was fusion-from-source). The v0.8.0b1 release
# inverted the premise -- the distribution is on PyPI and a plain `pip install`
# resolves it in a fresh venv, measured 2026-09-25 -- so the same phrases are
# now the overclaim: an adopter who reads one clones the repo and builds an
# editable install they do not need. Matched on whitespace-collapsed,
# lower-cased text so a line-wrapped form is caught too. `pre-release` is
# deliberately NOT here: the version IS a pre-release, and saying so is honest.
_PYPI_DENIALS = (
    "no pypi yet",
    "not yet the install path",
    "not yet published",
    "not yet claimed",
    "not yet on pypi",
    "once that channel is published",
    "planned but not yet",
    "(it is not yet)",
    "unclaimed on pypi",
)

# The three live forms the inversion was written against, one per doc
# (README:39, docs/QUICKSTART.md:14-15, docs/TROUBLESHOOTING.md:339 on
# 2026-09-25). The engage test below pins them so the denial list cannot be
# emptied or reworded into a green over a doc that still says "not yet".
_RECORDED_DENIAL_FORMS = frozenset({
    "no pypi yet",
    "not yet the install path",
    "(it is not yet)",
})

# The two docs a first-hour adopter reads must show the install line itself.
# Presence, not only the absence of a denial: deleting every mention of pip
# would pass the denial row and leave the adopter with no install command.
_MUST_CARRY_PIP_INSTALL = ("README.md", "docs/QUICKSTART.md")


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace so a line-wrapped `pip install\\nespalier-
    harness` is matched the same as the inline phrase."""
    return re.sub(r"\s+", " ", text)


# Words that, within this many characters of the pip phrase, make the mention
# read as "not really available": the closed twin of the whole-document
# denial scan above. The old contract was closed-world (every unqualified
# mention failed); the phrase list alone is open-world (only nine spellings
# fail), so a reworded denial beside the install line -- "publication is
# pending", "unpublished for now" -- would slip. Kept small and specific;
# `pre-release` is honest and stays out.
_PIP_NEIGHBOURHOOD_DENIALS = (
    "not yet", "unpublished", "unclaimed", "once published", "pending",
    "from source instead",
)
_WINDOW = 200  # chars of context on each side of the pip phrase


def _denials_in(text: str) -> list[str]:
    """Every denial the scan finds in one document's whitespace-collapsed,
    lower-cased text: a listed phrase anywhere, or a neighbourhood word within
    ``_WINDOW`` chars of a ``pip install espalier-harness`` mention."""
    found = [phrase for phrase in _PYPI_DENIALS if phrase in text]
    start = 0
    while (i := text.find(_PIP_PHRASE, start)) != -1:
        window = text[max(0, i - _WINDOW): i + len(_PIP_PHRASE) + _WINDOW]
        found.extend(
            f"{word!r} beside the pip line" for word in _PIP_NEIGHBOURHOOD_DENIALS
            if word in window
        )
        start = i + len(_PIP_PHRASE)
    return found


class TestPipInstallHonesty:
    """ONBOARD-2 / PUBINT-4, inverted at the v0.8.0b1 cut: the distribution is
    on PyPI, so no onboarding doc may tell the adopter it is not, and the two
    first-hour docs must carry the pip install line."""

    def test_no_onboarding_doc_denies_the_pypi_channel(self) -> None:
        offenders: list[str] = []
        for rel, raw in _existing_docs():
            for hit in _denials_in(_normalize_ws(raw).lower()):
                offenders.append(f"{rel}: {hit}")
        assert not offenders, (
            "onboarding doc(s) still tell the adopter the PyPI channel does not "
            "exist. `espalier-harness` has been on PyPI since 0.8.0b1 and a "
            "plain `python -m pip install espalier-harness` resolves it; reword "
            "the mention to the pip install path:\n  " + "\n  ".join(offenders)
        )

    @pytest.mark.parametrize("rel", _MUST_CARRY_PIP_INSTALL)
    def test_first_hour_docs_carry_the_pip_install_line(self, rel: str) -> None:
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} is missing; the first-hour docs must exist"
        text = _normalize_ws(path.read_text(encoding="utf-8")).lower()
        assert _PIP_PHRASE in text, (
            f"{rel} never shows `{_PIP_PHRASE}`; the first-hour docs must carry "
            "the install line, not only avoid denying the channel."
        )

    def test_the_denial_list_engages(self) -> None:
        """Earn the gate: the list carries the three forms the docs actually
        used on 2026-09-25, so the denial row is not green over an emptied or
        reworded list. A denial spelled some fourth way is the next row."""
        assert _RECORDED_DENIAL_FORMS <= set(_PYPI_DENIALS), (
            sorted(_RECORDED_DENIAL_FORMS - set(_PYPI_DENIALS))
        )
        assert _existing_docs(), "no onboarding doc found on disk; the rows above are vacuous"

    @pytest.mark.parametrize("form", sorted(_RECORDED_DENIAL_FORMS))
    def test_the_matcher_catches_each_recorded_denial(self, form: str) -> None:
        """The negative control the row above lacks: a synthetic document body
        carrying one recorded denial, line-wrapped and mixed-case, must produce
        an offender -- so a refactor that stops calling the matcher, drops the
        lower-casing or the whitespace fold, or scopes the scan to a subset
        goes red here instead of leaving a blind gate (both reviews, 2026-09-25)."""
        wrapped = form.replace(" ", "\n  ", 1).upper()
        body = f"Some prose. {wrapped} More prose about installing."
        assert _denials_in(_normalize_ws(body).lower()), (form, body)

    def test_the_matcher_catches_a_denial_beside_the_pip_line(self) -> None:
        body = "Run `pip install espalier-harness` once published; for now, clone."
        hits = _denials_in(_normalize_ws(body).lower())
        assert hits, body
        clean = "Run `python -m pip install espalier-harness`, then `espalier init .`."
        assert not _denials_in(_normalize_ws(clean).lower()), clean

    def test_readme_leads_with_the_pip_install_and_never_a_clone(self) -> None:
        """The first fenced block of README.md is what an evaluator pastes. It
        must carry the install line and must not clone the repository: the
        clone-and-editable form is the contributor path, one section down."""
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        first = re.search(r"```bash\n(.*?)```", text, re.S)
        assert first is not None, "README.md has no fenced bash block"
        block = first.group(1)
        assert _PIP_PHRASE in block, block
        assert "git clone" not in block, block


# ---------------------------------------------------------------------------
# An `init` that asks a question inside a pasted block is answered by the next
# pasted line (walk 3 on the Windows host, 2026-09-14: the decline is silent
# and the harness ships disarmed). Every install block an adopter pastes must
# therefore spell `--wire-hooks`, or make `init` the last command in the
# block. Scoped to paste sequences -- fences that install or clone -- so the
# verb-per-line reference lists in README's `## CLI` section are not held to
# a paste rule they were never meant to satisfy.
# ---------------------------------------------------------------------------

_PASTE_DOCS = ("README.md", "docs/QUICKSTART.md", "examples/README.md")
# Shell fences only (a .gitignore or JSON listing is not a paste sequence), and
# an `init` COMMAND only: the verb at the start of the line, optionally behind
# `python -m` / `python3 -m`, never a mention mid-sentence.
_FENCE_RE = re.compile(r"```(?:bash|sh|shell|console|powershell)\n(.*?)```", re.S)
_BARE_INIT_RE = re.compile(r"^(?:python3? -m )?espalier init\b")
_WIRE_FLAG = "--wire-hooks"


def _command_lines(block: str) -> list[str]:
    return [
        ln.strip() for ln in block.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _bare_init_not_last(block: str) -> list[str]:
    lines = _command_lines(block)
    return [
        ln for i, ln in enumerate(lines)
        if _BARE_INIT_RE.search(ln) and _WIRE_FLAG not in ln and i != len(lines) - 1
    ]


class TestPasteBlocksNeverBuryABareInit:
    def test_no_paste_block_buries_a_bare_init(self) -> None:
        offenders: list[str] = []
        for rel in _PASTE_DOCS:
            path = REPO_ROOT / rel
            if not path.is_file():
                continue
            for m in _FENCE_RE.finditer(path.read_text(encoding="utf-8")):
                block = m.group(1)
                if "pip install" not in block and "git clone" not in block:
                    continue
                offenders.extend(f"{rel}: {ln}" for ln in _bare_init_not_last(block))
        assert not offenders, (
            "a paste block runs a bare `espalier init` before another command; "
            "on a repo with a settings.json the wire prompt eats that next line. "
            "Spell `--wire-hooks` or make init the last line:\n  " + "\n  ".join(offenders)
        )

    def test_the_paste_rule_engages(self) -> None:
        bad = "python -m pip install espalier-harness\ncd repo\npython -m espalier init .\npython -m espalier doctor .\n"
        assert _bare_init_not_last(bad) == ["python -m espalier init ."]
        good_flag = bad.replace("init .", "init . --wire-hooks")
        assert _bare_init_not_last(good_flag) == []
        good_last = "git clone x && cd x\npython -m espalier init .\n"
        assert _bare_init_not_last(good_last) == []
        commented = "python -m espalier init .\n# a trailing comment is not a command\n"
        assert _bare_init_not_last(commented) == []

    def test_the_readme_windows_anchor_has_its_heading(self) -> None:
        """README.md links `docs/QUICKSTART.md#windows` by absolute URL, which
        the relative-anchor tests skip; the fragment resolves only while the
        heading is exactly `## Windows`."""
        quickstart = (REPO_ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
        assert "\n## Windows\n" in quickstart
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "docs/QUICKSTART.md#windows" in readme


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
