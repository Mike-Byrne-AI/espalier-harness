"""Pre-release validation — two-layer check before publishing.

Layer 1 (cleanliness gate): no placeholder contacts, no internal-material leaks,
    all required public files present, no transient noise.
Layer 2 (integration check): tests pass, surface gate passes, self-host passes,
    release zip builds cleanly, source vs wheel structural parity passes.

Internal-leak classification is delegated to `surface_contract` so this module
and `release_pack` cannot drift from each other (Pack 3).
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from espalier import surface_contract
from espalier._safe_walk import is_own_git_repo, safe_rglob
from espalier.release_noise import SECRET_FILES
from espalier.release_pack import ReleasePackSummary, _is_pruned_from_walk, create_release_zip
from espalier.scan_composition import REPORT_FILES
from espalier._text import os_error_text


# ── Layer 1: Cleanliness gate ────────────────────────────────────────

PLACEHOLDER_CONTACT_MARKERS = (
    "security-contact@example.com",
    "maintainer-contact@example.com",
    "replace-before-release.invalid",
    # Private security reporting placeholders.
    "<REAL_PRIVATE_SECURITY_CONTACT>",
    "security@example.com",
    "security@YOUR-DOMAIN.example",
)

# Match ANY github.com placeholder-URL dialect, not a fixed marker list.
# This regex matches an angle-bracket metavariable (`<owner>` / `<org>` /
# `<repo>`) OR the conventional ALL-CAPS `OWNER` / `REPO` placeholder as a
# full path segment; a real owner (`Mike-Byrne-AI`) is left untouched.
_PLACEHOLDER_URL_RE = re.compile(
    r"https://github\.com/(?:<[^>/\s]+>|(?:OWNER|REPO)(?=[/.\s]|$))"
)

REQUIRED_PUBLIC_FILES = (
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
)

# Derived from the single owner scan_composition.REPORT_FILES so this set cannot
# fossilize behind the scanner registry (it previously listed only 4 of the 10).
# Every scanner report file is transient noise — warning-only, and reports/ is
# gitignored, so widening to all 10 changes no gate outcome.
TRANSIENT_NOISE_FILES = {f"reports/{name}" for name in REPORT_FILES}


def _scan_placeholders(repo_root: Path) -> list[str]:
    """Find placeholder contacts and URLs in the required public files.

    The scan list is DERIVED from REQUIRED_PUBLIC_FILES rather than kept as a
    second literal beside it. The two were independent lists and they drifted:
    CODE_OF_CONDUCT.md was in neither, so a placeholder enforcement contact --
    and a CoC deleted outright -- passed the release gate green. Anything the
    gate requires a stranger to be able to read is a file worth scanning, so
    there is no exempt subset to fall out of date. (LICENSE is now scanned too
    and matches nothing today; that is coverage, not a behaviour change.)
    """
    findings: list[str] = []
    for rel in REQUIRED_PUBLIC_FILES:
        path = repo_root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in PLACEHOLDER_CONTACT_MARKERS:
            if marker in text:
                findings.append(f"{rel}: placeholder contact '{marker}'")
        for match in sorted({m.group(0) for m in _PLACEHOLDER_URL_RE.finditer(text)}):
            findings.append(f"{rel}: placeholder URL '{match}'")
    return findings


def _check_required_files(repo_root: Path) -> list[str]:
    """Check that required public-facing files exist."""
    return [f for f in REQUIRED_PUBLIC_FILES if not (repo_root / f).exists()]


# Vulnerability disclosure policy must route reports privately.
#
# A SECURITY.md that tells reporters to open a public issue is a release
# embarrassment and a real user-safety risk: vulnerability details end up
# public before a fix exists. This gate fails when SECURITY.md uses any
# public-issue routing language for vulnerabilities OR omits the required
# private-disclosure phrases. It also scans
# .github/ISSUE_TEMPLATE/*.yml and *.yaml for templates that would route
# security reports publicly.

# Phrases (case-insensitive substrings) that indicate public-issue routing
# of vulnerability reports.
PUBLIC_VULN_REPORTING_PHRASES = (
    "report it by opening a github issue",
    "report it by opening an issue",
    "open a github issue",
    "open a public issue",
    "report it via github issues",
    "report vulnerabilities via github issues",
)

# Required concepts in SECURITY.md (case-insensitive substrings). Each
# row is an "any of these substrings present" alternative.
REQUIRED_SECURITY_CONCEPTS = (
    ("Report a vulnerability",),
    ("private vulnerability", "report vulnerabilities privately",
     "report it privately", "private disclosure"),
    ("do not open a public github issue", "do not open a public issue",
     "please do not open a public github issue",
     "please do not open a public issue"),
)


def _flatten_ws(text: str) -> str:
    """Collapse every whitespace run to a single space.

    Markdown wraps prose wherever the line runs out, so a phrase a human
    reads as contiguous is routinely split by a newline in the source.
    Matching on the flattened form is what lets one scan see both spellings.

    ⚠ Every substring scan over authored prose in this module MUST go through
    this. `_check_security_policy` did not, and the omission was measured: a
    SECURITY.md genuinely routing vulnerabilities to public issues reports
    ZERO failures when its editor wraps `opening a\\ngithub issue` at 80
    columns, and one failure when it does not. Same document, same phrase,
    same gate. The phrases here run to 40 characters, which is well inside the
    wrap window of any normal markdown doc.
    """
    return re.sub(r"\s+", " ", text)


def _check_security_policy(repo_root: Path) -> list[str]:
    """Fail if SECURITY.md routes vulnerability reports publicly OR omits
    the required private-disclosure phrasing. Also scans issue templates
    for any security-report routing that would be public."""
    failures: list[str] = []
    security_md = repo_root / "SECURITY.md"
    if not security_md.exists():
        # Missing-file failure is reported by _check_required_files.
        return failures
    text = security_md.read_text(encoding="utf-8", errors="replace")
    # Flattened: a wrapped forbidden phrase is the same defect as a flat one.
    text_lower = _flatten_ws(text).lower()

    # (a) Forbidden public-issue routing language for vulnerabilities.
    # The required private-disclosure redirects (e.g. "do not open
    # a public issue") CONTAIN forbidden substrings ("open a public issue"), so
    # a correct SECURITY.md using the canonical short redirect satisfies (b)
    # AND false-fails (a) — a release gate that rejects textbook-correct input.
    # Mask every required-concept alternative that itself contains a forbidden
    # phrase out of the scan text before the forbidden scan. Derive the mask
    # set from REQUIRED_SECURITY_CONCEPTS rather than a duplicated literal list
    # so the two can't drift if a redirect spelling is added. Genuine public
    # routing ("open a github issue to report") survives the mask and still
    # fails, because no required redirect contains it.
    scan_text = text_lower
    for alternatives in REQUIRED_SECURITY_CONCEPTS:
        for alt in alternatives:
            alt_lower = alt.lower()
            if any(phrase in alt_lower for phrase in PUBLIC_VULN_REPORTING_PHRASES):
                scan_text = scan_text.replace(alt_lower, "")
    # The concept-derived mask above only neutralizes the redirect spellings
    # enumerated in REQUIRED_SECURITY_CONCEPTS (in practice just "open a public
    # issue"), but the gate CHECKS all of PUBLIC_VULN_REPORTING_PHRASES. So a
    # correct SECURITY.md whose redirect negates a DIFFERENT forbidden phrase
    # (e.g. "do not report vulnerabilities via github issues") would still
    # false-fail. Also mask the negated ("do not ...") form of every forbidden
    # phrase (this subsumes "please do not ...", which contains "do not ...").
    # Genuine public routing -- the bare phrase NOT preceded by "do not"
    # ("open a github issue to escalate") -- survives and still fails, so the
    # negative control is preserved.
    for phrase in PUBLIC_VULN_REPORTING_PHRASES:
        scan_text = scan_text.replace(f"do not {phrase}", "")
    for phrase in PUBLIC_VULN_REPORTING_PHRASES:
        if phrase in scan_text:
            failures.append(
                f"SECURITY.md routes vulnerability reports publicly via "
                f"phrase {phrase!r}; use private disclosure instead."
            )

    # (b) Required private-disclosure phrasing.
    for alternatives in REQUIRED_SECURITY_CONCEPTS:
        if not any(alt.lower() in text_lower for alt in alternatives):
            failures.append(
                "SECURITY.md missing required private-disclosure concept "
                f"(any of: {alternatives})"
            )

    # (c) Scan issue templates for security routing that would be public.
    # allow-text-scan-of-structured-config: the issue
    # template's BODY field is user-facing prose; matching on natural
    # language ("report a vulnerability") inside it is the goal, not
    # the YAML structure. Structural parse would still require the same
    # substring match on the body string.
    template_dir = repo_root / ".github" / "ISSUE_TEMPLATE"
    if template_dir.is_dir():
        # GitHub accepts both .yml and .yaml for issue-template forms;
        # glob both so a vuln-routing security.yaml cannot evade the gate.
        for tpl in sorted(
            (*template_dir.glob("*.yml"), *template_dir.glob("*.yaml"))
        ):
            tpl_text_lower = _flatten_ws(
                tpl.read_text(encoding="utf-8", errors="replace")
            ).lower()
            stem = tpl.stem.lower()
            # A template whose name suggests it's a security/vulnerability
            # form, or whose body solicits vulnerability details, is a leak.
            looks_like_security = (
                "security" in stem or "vuln" in stem
            )
            # Whole-file "do not" excusal rather than a windowed redirect
            # check: a windowed check would narrow the excusal and so WIDEN
            # this gate's deny predicate — a legitimate multi-section template
            # whose redirect sits outside the window would false-fail. The
            # whole-file check fires only when NO redirect appears anywhere,
            # never false-positives on a template that has one. Its
            # trivial-defeatability (an unrelated "do not" excuses a leaky
            # template) is recorded as accept-and-leave in
            # docs/FAILURE_MODES.md §6.10 — a false-negative in a
            # controlled-template gate beats a false-positive.
            solicits_vuln_details = (
                "report a vulnerability" in tpl_text_lower
                and "do not" not in tpl_text_lower
            )
            if looks_like_security:
                failures.append(
                    f".github/ISSUE_TEMPLATE/{tpl.name}: public security "
                    "issue template found; security reports must use "
                    "private disclosure (config.yml contact_links)."
                )
            elif solicits_vuln_details:
                failures.append(
                    f".github/ISSUE_TEMPLATE/{tpl.name}: appears to solicit "
                    "vulnerability details without a 'do not' redirect; "
                    "route security reports privately instead."
                )

    return failures


# A doc that TELLS a reader to open a free-form public issue makes a promise
# the repo's issue configuration has to keep. GitHub's
# `blank_issues_enabled: false`, paired with a fixed template set, removes the
# blank route entirely — so the instructed issue cannot be opened and the
# reader is sent to a door that is not there. DEF-424h: SECURITY.md and
# CONTRIBUTING.md both instruct a "request: private security contact" issue
# that a bug template (which forbids security content) and a feature template
# cannot carry.
#
# Recognition is WHITESPACE-NORMALIZED, and that is load-bearing rather than
# tidiness. The live corpus proves a raw substring scan covers HALF the
# population: SECURITY.md carries "private security contact" on one line while
# CONTRIBUTING.md wraps it across two, so `phrase in text` finds one site,
# misses the other, and still reads as full coverage. Coverage is population
# times recognition — deriving the population alone buys reach without it.
DOC_INSTRUCTED_BLANK_ISSUE_PHRASES = (
    "private security contact",
    "open a blank issue",
    "open a free-form issue",
)

# ⚠ A phrase match alone is a TOPIC, not an INSTRUCTION, and the first cut of
# this gate conflated them. Measured on the real code path: `Our private
# security contact is sec@acme.example. Email us there.` fired, and so did
# `Do not open a public issue to ask for a private security contact.` — an
# explicit negation of the very thing being flagged. Both exit 1 through the
# documented adopter-facing `espalier pre-release`, telling the reader to
# "drop the instruction" when there is no instruction to drop.
#
# `_check_security_policy` had already solved this class 130 lines up and
# carries a 14-line comment about it; this gate reproduced the bug that
# comment exists to document. The discriminator is per-SENTENCE: the phrase
# must share a sentence with an act that actually opens something public, and
# a negated sentence instructs nobody.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Acts that open a public thing. `publicly request` is here because it is how
# the live SECURITY.md spells it — requiring `open … issue` would have dropped
# the primary site and left the recogniser narrower than the corpus, which is
# the failure this gate was written in response to.
_PUBLIC_ACT_RE = re.compile(
    r"\b(?:open|file|create|raise|submit)\b[^.]{0,80}?\bissue\b"
    r"|\bpublicly\s+(?:request|ask|open|file)\b"
)

_NEGATED_RE = re.compile(r"\b(?:do not|don't|never|must not|cannot|can't|no need to)\b")

# Falsey spellings accepted for `blank_issues_enabled`. Read liberally on
# purpose: treating an unrecognized spelling as DISABLED makes this gate fire
# more often, and a false alarm costs one release-gate line while a false
# silence ships the defect.
_BLANK_ISSUES_DISABLED_VALUES = frozenset({"false", "no", "off", "n"})

_BLANK_ISSUES_RE = re.compile(
    r"^[ \t]*blank_issues_enabled[ \t]*:[ \t]*(\S+)", re.MULTILINE
)


def _blank_issue_route_state(repo_root: Path) -> tuple[bool, str | None]:
    """``(route_exists, offending_relpath)`` for the blank-issue route.

    An ABSENT config means the route exists — GitHub enables blank issues
    unless a template config turns them off, so absence is *known* enabled.

    ⚠ A config that is PRESENT but unreadable is *unknown*, not enabled, and
    the first cut collapsed the two. Measured: a BOM before the key, a
    duplicated key (`true` then `false`, where YAML takes the last and
    ``search`` took the first), and an empty value all returned "route
    exists" and reported zero failures, while a plain `false` reported one.
    That contradicts the policy stated on ``_BLANK_ISSUES_DISABLED_VALUES``
    twenty lines up — a false alarm costs one line, a false silence ships the
    defect. Naming the key at all now means "assume disabled unless a value
    parses as enabled".

    Returns the path that disabled the route so the failure can name the file
    the operator must actually open: with both a `.yaml` and a `.yml` present
    the message previously cited `config.yml` while `config.yaml` held the
    offending value, sending them to a file that already looked correct.
    """
    template_dir = repo_root / ".github" / "ISSUE_TEMPLATE"
    for name in ("config.yml", "config.yaml"):
        config = template_dir / name
        if not config.is_file():
            continue
        rel = f".github/ISSUE_TEMPLATE/{name}"
        # allow-text-scan-of-structured-config: `blank_issues_enabled` is a
        # top-level scalar. A line-anchored regex reads it without adding a
        # YAML dependency to a module the release gate imports, matching the
        # text scan already used for the template bodies above.
        text = config.read_text(encoding="utf-8", errors="replace")
        values = [
            v.strip().strip("\'\"").lower() for v in _BLANK_ISSUES_RE.findall(text)
        ]
        if any(v in _BLANK_ISSUES_DISABLED_VALUES for v in values):
            return False, rel
        if not values and "blank_issues_enabled" in text:
            return False, rel
    return True, None


def _blank_issue_route_exists(repo_root: Path) -> bool:
    """True when a reader can still open a free-form issue."""
    return _blank_issue_route_state(repo_root)[0]


def _check_instructed_issue_route(repo_root: Path) -> list[str]:
    """Fail when a required public doc instructs opening a free-form public
    issue that the repo's own template config has made unopenable.

    The population is DERIVED from `REQUIRED_PUBLIC_FILES` rather than naming
    SECURITY.md and CONTRIBUTING.md, so a doc joining the required set is
    scanned without anyone remembering to enroll it here.
    """
    route_exists, offender = _blank_issue_route_state(repo_root)
    if route_exists:
        return []
    failures: list[str] = []
    for rel in REQUIRED_PUBLIC_FILES:
        if not rel.endswith(".md"):
            continue
        doc = repo_root / rel
        if not doc.is_file():
            continue
        matched = _instructed_blank_issue_phrase(
            doc.read_text(encoding="utf-8", errors="replace")
        )
        if matched:
            failures.append(
                f"{rel} instructs a free-form public issue ({matched!r}) "
                f"but {offender} sets blank_issues_enabled to a disabled or "
                "unreadable value and no template carries it -- enable blank "
                "issues or drop the instruction."
            )
    return failures


def _instructed_blank_issue_phrase(text: str) -> str | None:
    """The phrase a doc uses to INSTRUCT a free-form public issue, or None.

    Per-sentence, because a phrase match alone is a topic. `Our private
    security contact is sec@acme.example.` names the subject and instructs
    nothing; `Do not open a public issue to ask for a private security
    contact.` instructs the opposite. Both fired before this existed, and both
    exited 1 through the documented adopter-facing `espalier pre-release`.
    """
    for sentence in _SENTENCE_SPLIT_RE.split(_flatten_ws(text)):
        low = sentence.lower()
        hit = next(
            (p for p in DOC_INSTRUCTED_BLANK_ISSUE_PHRASES if p in low), None
        )
        if hit is None:
            continue
        if _NEGATED_RE.search(low):
            continue
        if _PUBLIC_ACT_RE.search(low):
            return hit
    return None


def _is_secret_noise(rel: str) -> bool:
    """True when ``rel``'s basename matches a ``release_noise.SECRET_FILES`` glob."""
    basename = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(basename, pattern) for pattern in SECRET_FILES)


def _release_pack_failures(repo_root: Path, summary: ReleasePackSummary) -> list[str]:
    """The pack stage's failures: an archive with nothing in it, or one built
    from the working tree on a root that owns its ``.git``.

    Both are green at the builder (it returns a summary either way) and loud
    only on stderr, which no gate reads. An empty index enumerates nothing and
    would otherwise pass with ``files_written: 0``; a git root that answered
    "tree" is git failing (absent from PATH, dubious ownership, a moved
    gitdir), and the archive it produced carries every untracked public file
    -- the shape the index enumeration exists to close. A root that is not a
    repository at all (the release matrix's extracted archive) legitimately
    walks the tree, so that shape is not a failure here.
    """
    failures: list[str] = []
    if summary.files_written == 0:
        failures.append(
            "release pack: nothing packageable (an empty git index enumerates "
            "nothing); refusing to call an empty archive a release"
        )
    if summary.enumeration == "tree" and is_own_git_repo(repo_root):
        failures.append(
            "release pack: built from the working tree on a root that owns its "
            ".git -- git could not answer for this checkout (see the "
            "surface_contract WARN on stderr), so every untracked public file "
            "would ship; fix git rather than ship the tree"
        )
    return failures


def _find_transient_noise(repo_root: Path) -> list[str]:
    """Transient files and directories to clean before release -- the warning
    half of the gate whose other half is the release archive.

    Classified by ``surface_contract.is_transient``, the predicate the archive
    builder rejects with (the sibling ``_find_internal_leaks`` already routes
    through ``is_internal_release_leak``), and walked under the builder's own
    ``_is_pruned_from_walk`` prune, so this half cannot name a path the
    archive half never enumerates. It did: a leftover release-matrix workspace
    under ``dist/final-release-matrix/`` was pruned silently by the packer and
    warned about here one ``__pycache__`` at a time, from a hand-kept set of
    four directory names the contract had long outgrown. A transient DIRECTORY
    is reported once and not descended, so the list stays one line per tree
    rather than one per file; a transient FILE outside any such tree (a stray
    ``.DS_Store``, an editor backup) is reported on its own. The directory
    question is the contract's ``name/`` pattern arm only: the download-dupe
    arm keys on a basename, and a directory asked with a trailing slash has
    none, so a ``Downloads copy/`` tree is not named here (the archive half
    never asks a directory question either, so the two do not diverge).

    The scanner report files under ``reports/`` are local-only, not transient,
    in the contract's vocabulary; they stay on the list by name because a
    stale report is what a release should not carry, and ``reports/`` is
    gitignored, so either way this is a warning.
    """
    found: list[str] = []
    for rel in sorted(TRANSIENT_NOISE_FILES):
        if (repo_root / rel).exists():
            found.append(rel)
    noisy_trees: list[str] = []
    for path in safe_rglob(repo_root):  # symlink-safe; skips embedded git repos
        rel = path.relative_to(repo_root).as_posix()
        # The packer's prune first: every tree it never enumerates is a tree
        # this scan never names, whatever the contract would say about it.
        if _is_pruned_from_walk(rel):
            continue
        if any(rel.startswith(tree + "/") for tree in noisy_trees):
            continue
        if path.is_dir():
            # A trailing slash makes the directory's own name a directory
            # component, which is where `is_transient` tests `name/` patterns.
            if surface_contract.is_transient(rel + "/"):
                noisy_trees.append(rel)
                found.append(rel)
        elif surface_contract.is_transient(rel):
            found.append(rel)
    return sorted(set(found))


# The canonical implementations live in surface_contract so the release-zip
# builders can reuse them without a release_pack↔pre_release import cycle.
# Aliased here to preserve the existing call sites + tests. The walk prune is
# the one shared predicate that stays in release_pack: it is the archive
# walker's own report-only policy (its docstring is that contract), and this
# module already imports release_pack one way, so there is no cycle to avoid;
# tests/test_pre_release.py pins that the two modules share one object.
_export_ignore_patterns = surface_contract.export_ignore_patterns
_matches_export_ignore = surface_contract.matches_export_ignore


def _find_internal_leaks(repo_root: Path) -> list[str]:
    """Files the contract classifies as internal, among those that could ship.

    Uses `surface_contract.is_internal_release_leak` so pre_release and
    release_pack can never disagree about what counts as private material --
    and enumerates what release_pack enumerates: the git index, with the
    working-tree walk only for a root that has no index. A leak is a file the
    ARCHIVE would carry; once the archive became the index, an untracked
    `docs/internal/scratch.md` could not reach it, yet this scan still walked
    the tree and turned it into a hard `/preflight` failure (the failing half
    of the gate, unlike its warning sibling). Transient/build-cache paths are
    filtered out — those are warnings, not failures, and live in
    `_find_transient_noise`.

    A file that is both classified internal AND marked
    `export-ignore` in `.gitattributes` is deliberately kept in-repo but
    excluded from the public archive — it is not a leak. Without this skip,
    classifying tracked files like `blueprint.md` / `ESPALIER_MEMORY.md` as internal
    would flip a clean-checkout `espalier pre-release` from green to red even
    though those files never ship.
    """
    export_ignored = _export_ignore_patterns(repo_root)
    leaks: list[str] = []
    tracked = surface_contract.tracked_paths(repo_root)
    candidates = (
        safe_rglob(repo_root) if tracked is None  # symlink-safe; skips embedded git repos
        else (repo_root / rel for rel in sorted(tracked))
    )
    for path in candidates:
        if not path.is_file():
            continue
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if surface_contract.is_transient(rel):
            continue
        if surface_contract.is_internal_release_leak(rel):
            if any(_matches_export_ignore(rel, p) for p in export_ignored):
                continue
            leaks.append(rel)
    return sorted(set(leaks))




CURRENT_FACING_SURFACE_FILES = [
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

# Count-shaped stale strings ("7 governance agents", "22 slash
# commands") are deliberately excluded. The dynamic agent/command count check below already
# enforces README counts against disk reality, and a count-shaped denylist entry
# makes the gate UN-PASSABLE if the live count ever equals it: the count would be
# simultaneously required (must match disk) AND forbidden (stale). Only genuine
# phantom references — not live-count-shaped values — belong here.
STALE_README_STRINGS = (
    "WORKTREE_LANES.md",
)


def _check_surface_truth(repo_root: Path) -> list[str]:
    """Self-host-only: README counts must match disk reality; no phantom files."""
    failures: list[str] = []

    agents_dir = repo_root / ".claude" / "agents"
    commands_dir = repo_root / ".claude" / "commands"
    if not agents_dir.is_dir() or not commands_dir.is_dir():
        return failures

    agent_count = len(list(agents_dir.glob("*.md")))
    command_count = len(list(commands_dir.glob("*.md")))

    readme_path = repo_root / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")
        expected_agents = f"{agent_count} governance agents"
        expected_commands = f"{command_count} slash commands"
        if expected_agents not in readme:
            failures.append(
                f"README.md: expected '{expected_agents}' but not found "
                f"(actual disk count: {agent_count})"
            )
        if expected_commands not in readme:
            failures.append(
                f"README.md: expected '{expected_commands}' but not found "
                f"(actual disk count: {command_count})"
            )
        for stale in STALE_README_STRINGS:
            if stale in readme:
                failures.append(f"README.md: stale claim '{stale}' must be removed")

    for rel in CURRENT_FACING_SURFACE_FILES:
        p = repo_root / rel
        if not p.exists():
            continue
        if "WORKTREE_LANES" in p.read_text(encoding="utf-8"):
            failures.append(f"{rel}: phantom WORKTREE_LANES.md reference must be removed")

    return failures


# Stable marker strings whose presence proves the regression tests still exist.
# Pre-release fails if any marker is absent from the test suite.
PLAN_GUARD_REGRESSION_MARKERS = (
    "checks_redirects_before_readonly_allowlist",
    "blocks_inline_python_write",
    "execution_plan_status_exits_nonzero_without_active_plan",
)


def _check_plan_guard_regression_coverage(repo_root: Path) -> list[str]:
    """Verify that plan-guard and execution-plan regression tests are still present.

    Scans tests/ for the stable marker strings that identify each regression test.
    Fails if a marker is absent — meaning the test was removed or renamed without
    an equivalent replacement.
    """
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return ["tests/ directory not found — cannot verify regression coverage"]

    combined = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in tests_dir.rglob("*.py")  # espalier:safe-walk-ok self-host pre-release gate: walks espalier's own tests/ only, never an adopter tree
    )

    failures: list[str] = []
    for marker in PLAN_GUARD_REGRESSION_MARKERS:
        if marker not in combined:
            failures.append(
                f"plan-guard regression test missing: no test mentions '{marker}'"
            )
    return failures

def run_cleanliness_gate(repo_root: Path) -> dict[str, Any]:
    """Layer 1: verify the repo is clean enough for public release.

    Failures (hard): placeholder contacts/URLs, missing required files,
    internal-material leaks (classified by surface_contract).
    Warnings (soft): transient workspace noise (build caches, .pyc files).
    """
    repo_root = repo_root.resolve()
    failures: list[str] = []
    warnings: list[str] = []

    placeholders = _scan_placeholders(repo_root)
    if placeholders:
        failures.extend(placeholders)

    missing = _check_required_files(repo_root)
    if missing:
        failures.extend(f"missing required file: {f}" for f in missing)

    # Classification stays universal (parity with release_pack's archive
    # cleanliness). The VERDICT, though, is adopter-aware: on a repo
    # that is NOT Espalier-Harness itself, a file merely matching the harness's
    # internal-doc *filename* vocabulary (*-atlas.md, TP-*.md, blueprint.md,
    # TASK_PACK*.md) is the adopter's own material and must NOT HARD-FAIL their
    # `espalier pre-release`. The generic path-prefix arm (docs/internal/, …)
    # still blocks on every repo, and release_pack keeps stripping all of it
    # from the harness's own public archive.
    leaks = _find_internal_leaks(repo_root)
    self_host = surface_contract.is_self_host_repo(repo_root)
    for p in leaks:
        if self_host or surface_contract.is_internal_path_prefix(p):
            failures.append(f"internal leak: {p}")
        else:
            warnings.append(
                f"internal-pattern filename (non-blocking on adopter repo): {p}"
            )

    security_failures = _check_security_policy(repo_root)
    if security_failures:
        failures.extend(security_failures)

    failures.extend(_check_instructed_issue_route(repo_root))

    if self_host:
        surface_failures = _check_surface_truth(repo_root)
        failures.extend(surface_failures)
        coverage_failures = _check_plan_guard_regression_coverage(repo_root)
        failures.extend(coverage_failures)

    noise = _find_transient_noise(repo_root)
    for f in noise:
        # SECRET_FILES live inside RELEASE_NOISE_PATTERNS, so the contract
        # calls `.env` transient and it lands here -- but "transient noise" is
        # a clean-this-up heading, and the one thing to do with a secret the
        # archive already refuses is NOT to delete it on the strength of a
        # label. Say what it is.
        if _is_secret_noise(f):
            warnings.append(f"secret file present (never ships; do not delete blindly): {f}")
        else:
            warnings.append(f"transient noise: {f}")

    return {
        "repo_root": str(repo_root),
        "status": "fail" if failures else "pass",
        "failures": failures,
        "warnings": warnings,
        "internal_leaks": leaks,
    }


# ── Layer 2: Integration check ───────────────────────────────────────

DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
#: The test layer's leg -- `pytest -q -m "not heavy_e2e"`, run SERIALLY by
#: `_run_command` -- measured at 2,711 s on the self-host box on 2026-09-23 (the
#: release matrix's stage 02: the same selection on the EXTRACTED ARCHIVE in a
#: fresh venv, 17,397 collected; this tree collects about two hundred more for
#: the same selection, so the figure is a proxy a few percent under the tree's
#: own, harmless at twice; `DEF-917`). The 120s default -- correct for the fast helper
#: commands below (`build --help`) -- made `espalier pre-release` ALWAYS time out
#: on its own `pytest` layer, and the literal 600 that replaced it (sized on a
#: 2026-era ~249 s run) drifted under the leg with no signal: the lock row only
#: floored it at 300. The bound now DERIVES from this recorded figure, the way
#: `scripts/release_check.py::NOT_SLOW_LEG_BOUND_S` derives from its leg.
#: Re-measure this constant (the date beside it); never edit the bound.
#: `DEF-918` moves the leg to xdist after the cut and re-pins it.
NOT_HEAVY_E2E_LEG_MEASURED_S = 2711
TEST_COMMAND_TIMEOUT_SECONDS = 2 * NOT_HEAVY_E2E_LEG_MEASURED_S
TIMEOUT_RETURN_CODE = 124


def _coerce_output(value: "str | bytes | None") -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_command(
    command: list[str],
    cwd: Path,
    *,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    try:
        # subprocess-contract: ok generic-command-runner-callers-pin-each-CLI-surface
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=timeout_seconds,
        )
        return {
            "command": " ".join(command),
            "returncode": result.returncode,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
            "timed_out": False,
            "timeout_seconds": timeout_seconds,
        }
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr)
        timeout_message = f"Command timed out after {timeout_seconds} seconds"
        stderr = f"{stderr}\n{timeout_message}".strip()
        return {
            "command": " ".join(command),
            "returncode": TIMEOUT_RETURN_CODE,
            "stdout": stdout[-500:] if stdout else "",
            "stderr": stderr[-500:] if stderr else timeout_message,
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
        }


def _parity_runnable() -> bool:
    """True only when `python -m build` can be executed here (needed for parity)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--help"],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # strict decode: a structured answer (DEF-821)
        return False
    return result.returncode == 0 and "usage" in (result.stdout + result.stderr).lower()


def run_pre_release_check(
    repo_root: Path,
    *,
    output_zip: str = "dist/espalier.zip",
    skip_tests: bool = False,
    skip_pack: bool = False,
    skip_parity: bool = False,
) -> dict[str, Any]:
    """Full pre-release validation.

    Returns a structured report with pass/fail status for each layer.
    Layers: cleanliness gate → tests → self-host → structural artifact parity → release pack.
    """
    repo_root = repo_root.resolve()
    failures: list[str] = []
    commands: list[dict[str, Any]] = []
    skipped_checks: list[str] = []

    # Layer 1: cleanliness
    gate = run_cleanliness_gate(repo_root)
    if gate["status"] != "pass":
        failures.extend(gate["failures"])

    # Layer 2: integration
    if not skip_tests:
        # Deselect `heavy_e2e` (the release-matrix stage-one smoke): it re-spawns the
        # whole suite as a child — a check CI and `final_release_matrix.py` already
        # own, so running it inside this gate is pure redundancy. Everything else
        # still runs, including all slow packaging/git/wheel tests. Paired with the
        # realistic TEST_COMMAND_TIMEOUT_SECONDS so the multi-minute run no longer
        # false-RED-times-out. The exact command is recorded in `commands` below,
        # so the deselection is visible in the audit trail.
        test_result = _run_command(
            [sys.executable, "-m", "pytest", "-q", "-m", "not heavy_e2e"],
            repo_root,
            timeout_seconds=TEST_COMMAND_TIMEOUT_SECONDS,
        )
        commands.append(test_result)
        if test_result.get("timed_out"):
            # A fired bound is a bound, not a failed suite -- say which, and
            # name the constant to re-measure (`DEF-917`; the shape
            # `scripts/release_check.py::check_tests_pass` reports one file over).
            failures.append(
                f"test suite TIMED OUT at {test_result['timeout_seconds']} s "
                f"(twice the recorded {NOT_HEAVY_E2E_LEG_MEASURED_S} s serial leg): "
                "a bound, not a failed suite -- re-measure NOT_HEAVY_E2E_LEG_MEASURED_S"
            )
        elif test_result["returncode"] != 0:
            failures.append("test suite failed")
    else:
        skipped_checks.append("tests (--skip-tests)")

    # Self-host check. Reads the shared accept-set rather than a local
    # `!= "pass"`: that narrower test turned the deliberate `uninitialized`
    # first-run hint into "self-host check failed" and discarded
    # `primary_reason` -- leaving a reader with a check named after THIS repo
    # and no next step. A real failure now carries the producer's own sentence.
    from espalier.self_hosting import gate_failure_reason, run_self_host_check
    self_host = run_self_host_check(repo_root)
    self_host_failure = gate_failure_reason(self_host)
    if self_host_failure:
        failures.append(self_host_failure)

    # Structural source-vs-wheel parity (Pack 3-B).
    parity_report: dict[str, Any] | None = None
    if skip_parity:
        skipped_checks.append("artifact-parity (--skip-parity)")
    else:
        if _parity_runnable():
            from espalier.artifact_parity import check_source_vs_wheel
            try:
                parity_report = check_source_vs_wheel(repo_root)
                if not parity_report.get("parity"):
                    failures.append(
                        "artifact parity failed: " + "; ".join(parity_report.get("diffs", []))
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                parity_report = {"parity": False, "error": os_error_text(exc), "diffs": []}
                failures.append(f"artifact parity check errored: {os_error_text(exc)}")
        else:
            # AUTO-skip: `python -m build` is not runnable here, so parity
            # cannot be verified. Record it in `skipped_checks` so the
            # exit-code/JSON audit trail distinguishes "verified" from
            # "silently not run" — mirroring the explicit `--skip-parity`
            # path above and the `cli.py` missing-sub-check treatment. Do NOT
            # leave a self-disabled release sub-layer byte-identical to a real
            # parity PASS.
            parity_report = {
                "parity": "skipped",
                "reason": "python -m build not runnable in this interpreter",
                "diffs": [],
            }
            skipped_checks.append("artifact-parity (build not runnable)")

    # Release pack
    if skip_pack:
        skipped_checks.append("release-pack (--skip-pack)")

    pack_summary = None
    if not failures and not skip_pack:
        summary = create_release_zip(repo_root, repo_root / output_zip)
        pack_summary = summary.to_dict()
        failures.extend(_release_pack_failures(repo_root, summary))

    return {
        "repo_root": str(repo_root),
        "status": "pass" if not failures else "fail",
        "cleanliness_gate": gate,
        "commands": commands,
        "self_host": {
            "status": self_host.get("surface_gate_status", "unknown"),
            # Carry the producer's actionable sentence even when the status is
            # NOT a failure -- `uninitialized` is precisely the case where the
            # reader most needs it and the old code most reliably lost it.
            "reason": (
                (self_host.get("gate_details") or {}).get("primary_reason") or ""
            ),
        },
        "artifact_parity": parity_report,
        "release_pack": pack_summary,
        "failures": failures,
        "skipped_checks": skipped_checks,
    }
