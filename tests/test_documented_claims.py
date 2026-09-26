"""Tests that bind documented claims to external truth or live repo state.

This file exists because espalier shipped a foundational hook protocol
bug for months — SHARP_EDGES.md documented the wrong contract, tests
verified the wrong contract, implementation matched the wrong contract,
and bench measured the wrong contract. Every internal cross-check agreed
because they all checked against the same misreading.

Tests here invert the trust direction: docs are claims that must be backed
by either (a) live repo state or (b) a pinned external excerpt in
docs/external/. If you write 'X is true' in a project doc, you owe a test
here that proves X.

Failure mode this is designed to avoid: confirming claims by quoting them
back from elsewhere in the same project.

Single-source NumericContracts (annotated `# doc-drift-only:` at each entry):
a handful of NumericContracts have exactly one SoT surface. These are
doc-vs-literal *snapshots* — they pin a count-by-occurrence in ONE file against
the expected_value literal hard-coded here, so they catch drift in that one
surface but are NOT independent behavioral oracles (they cannot fail the way a
true multi-surface contract does). They are honest drift catchers, not proofs;
turning them into real oracles (compute the number a second, independent way
and assert equality) is deferred — for several the only "second" surface would
be derived from the same source (synthetic parity), and a directory-count
witness would require changing TestNoStaleNumericContracts' text-regex logic.
The `# doc-drift-only:` annotation declares the weaker guarantee at each site.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _json_key_paths import key_paths

from espalier.changelog import category_label

from tests._export_guard import pruned_from_this_tree
from tests._git_oracle import owns_its_worktree, require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTERNAL_DIR = REPO_ROOT / "docs" / "external"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Doc → external truth ─────────────────────────────────────────────────


class TestSharpEdgesMatchesProtocol:
    """SHARP_EDGES.md hook-exit-code section is consistent with the pinned
    Claude Code hook protocol excerpt.

    This is the test that would have caught the original bug:
    the old SHARP_EDGES said 'exit 2 + JSON on stdout', the external
    contract says 'JSON only processed on exit 0'. The contradiction is
    surfaced here regardless of how the implementation behaves.
    """

    def test_sharp_edges_does_not_recommend_exit_two_plus_json(self):
        sharp = _read(REPO_ROOT / "docs" / "SHARP_EDGES.md")
        # Old wrong-contract recommendation phrasings must not be present.
        # Patterns target imperative/recommendation forms; descriptive mentions
        # of how exit 2 *ignores* JSON are correct and must not trip this test.
        wrong_patterns = [
            # "Use `sys.exit(2)` with JSON on stdout" — original recommendation.
            r"sys\.exit\(2\)\s+with\s+JSON",
            # "exit 2 + JSON" recommended as a combined channel.
            r"exit\s*2\s*\+\s*JSON",
            # "DENY (exit 2)" with structured-JSON claim — the old contract.
            r"DENY\s*\(\s*exit\s*2\s*\)\s*[:,]?\s*(?:print|return|with)\s+JSON",
        ]
        for pattern in wrong_patterns:
            assert not re.search(pattern, sharp, re.IGNORECASE), (
                f"SHARP_EDGES.md contains old wrong-contract phrasing matching "
                f"/{pattern}/. Per docs/external/cc-hook-protocol.md, JSON is "
                f"only processed on exit 0."
            )

    def test_sharp_edges_documents_xor_rule(self):
        sharp = _read(REPO_ROOT / "docs" / "SHARP_EDGES.md")
        # The new contract must be documented.
        assert "Channel XOR" in sharp or "channel XOR" in sharp, (
            "SHARP_EDGES.md must document the channel-XOR rule. "
            "See docs/external/cc-hook-protocol.md."
        )
        # The DIRECTION — not just the rule's name — is the contract: exit 0
        # carries stdout JSON, exit 2 falls back to stderr. Anchor to the
        # Channel-XOR SECTION and pin both directions there; a re.DOTALL scan
        # over the whole 2000-line doc matches distant unrelated mentions and
        # stays green after a clean directional inversion, so it proves nothing.
        m = re.search(r"^##[^\n]*Channel XOR[^\n]*\n(.*?)(?=^## )", sharp, re.S | re.M)
        assert m, "SHARP_EDGES.md must carry a '## … Channel XOR' section heading."
        section = m.group(1)
        assert re.search(r"stdout\b.*\bonly on exit 0", section, re.I | re.S), (
            "Channel-XOR section must state stdout JSON is processed only on "
            f"exit 0 (direction is the contract):\n{section}"
        )
        assert re.search(r"on exit 2\b.*\bstderr", section, re.I | re.S), (
            f"Channel-XOR section must state exit 2 falls back to stderr:\n{section}"
        )

    def test_external_protocol_pin_present(self):
        pinned = EXTERNAL_DIR / "cc-hook-protocol.md"
        assert pinned.exists(), (
            "docs/external/cc-hook-protocol.md must be present as the "
            "verification target for hook protocol claims."
        )
        text = _read(pinned)
        assert "Fetched:" in text, "Pinned excerpt must declare a fetch date."
        assert "Source:" in text, "Pinned excerpt must declare a canonical URL."
        # Hard-anchor key contract sentences so a careless edit to the pin
        # surfaces here.
        assert "JSON output is **only** processed on exit 0" in text or \
               "JSON output is only processed on exit 0" in text


# ── Doc → live repo state ────────────────────────────────────────────────


class TestClaudeMdHookCounts:
    """CLAUDE.md's hook numbers are pinned to the live repo.

    Replaces ``TestReadmeHookCount::test_claude_md_hook_count_if_stated``,
    deleted as structurally dead. That test searched CLAUDE.md for
    ``(\\d+)\\s+hooks?\\b`` and skipped when it found nothing — and it found
    nothing in every checkout, because the live phrasing is *"governs 10 of
    Claude Code's hook events"*, where the digit is followed by ``" of"``, not
    ``" hook"``. CLAUDE.md is tracked, so the skip was deterministic
    everywhere: the ``10`` it existed to pin was unpinned for as long as the
    sentence has read that way.

    **The ``_if_stated`` suffix was the whole defect** — a conditional gate
    whose condition silently stops matching is indistinguishable from a
    passing one. So the primary test below has **no skip arm**: an absent
    phrase is a FAILURE, because "the doc stopped stating the count" is
    precisely the drift worth catching.

    Two distinct numbers live here and conflating them is the easy mistake:
    **12** hook *scripts* (``len(CANONICAL_HOOK_WIRING)``) and **10** distinct
    hook *events*. CLAUDE.md states the event count.

    Not a rival to anything: ``test_skill_tier_contract.py``'s
    ``_HOOK_EVENT_NAMES`` is an exemption set, ``test_hook_event_contracts.py``
    pins the script→event mapping, and ``test_contracts.py::TestReadmeHookCount``
    (a *different* class that happens to share the old name) pins **README.md**
    against the *file* count. None of them reads CLAUDE.md's number.
    """

    # Anchored on the sentence, not on a bare digit: a loose `(\d+)` would bind
    # to any number in the file and re-create the drift this replaces.
    _EVENT_COUNT_RE = re.compile(
        r"governs\s+(\d+)\s+of\s+Claude\s+Code's\s+hook\s+events", re.IGNORECASE
    )

    def _actual_hook_file_count(self) -> int:
        hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        return len([
            p for p in hooks_dir.glob("*.py")
            if p.name != "__init__.py" and not p.name.startswith("_")
        ])

    def test_claude_md_hook_event_count_matches_canonical_wiring(self):
        """Reds on BOTH mutations: the doc's number, and the wiring's events."""
        from espalier.harness_config import CANONICAL_HOOK_WIRING

        claude_md = _read(REPO_ROOT / "CLAUDE.md")
        match = self._EVENT_COUNT_RE.search(claude_md)
        assert match is not None, (
            "CLAUDE.md no longer states its hook-EVENT count in the form "
            "\"governs N of Claude Code's hook events\". This is a failure, not a "
            "skip: the predecessor of this test skipped on exactly this condition "
            "and went dead for months. Either restore the sentence or update this "
            "pattern deliberately."
        )
        stated = int(match.group(1))
        actual = len({spec["event"] for spec in CANONICAL_HOOK_WIRING.values()})
        assert stated == actual, (
            f"CLAUDE.md says espalier governs {stated} hook events; "
            f"CANONICAL_HOOK_WIRING wires {actual} distinct events "
            f"(across {len(CANONICAL_HOOK_WIRING)} scripts). "
            f"Update the doc or update the wiring."
        )

    def test_claude_md_hook_file_count_claims_match_reality(self):
        """Forward guard on ``N hooks`` phrasing — the deleted test's original net.

        POPULATION IS ZERO TODAY and that is recorded deliberately rather than
        left to look like coverage: CLAUDE.md currently states no file-count
        claim, so this passes vacuously. It is not load-bearing on its own — the
        test above is the gate that cannot silently die. This one exists so that
        if someone later writes "espalier ships 12 hooks", it is pinned on
        arrival instead of drifting.
        """
        claude_md = _read(REPO_ROOT / "CLAUDE.md")
        claims = re.findall(r"(\d+)\s+hooks?\b", claude_md, re.IGNORECASE)
        actual = self._actual_hook_file_count()
        for stated in claims:
            assert int(stated) == actual, (
                f"CLAUDE.md states {stated} hooks; actual hook-script count is "
                f"{actual}. Update the doc or update the directory."
            )


class TestChangelogDateSanity:
    """CHANGELOG dates fall within the project's actual lifetime.

    This test exists because an earlier LLM session inserted plausible-looking
    but fabricated dates ('2025-Q3', '2025-Q4') into CHANGELOG.md, and every
    subsequent session — human and AI — trusted them. The minimum
    falsifiable assertion: dates are consistent with the project's first
    commit date or first known external reference.
    """

    PROJECT_LIFETIME_START = "2026-01"  # espalier did not exist before this

    def test_changelog_dates_after_project_start(self):
        changelog = _read(REPO_ROOT / "CHANGELOG.md")
        # Pull all YYYY-MM and YYYY-QN tokens.
        date_tokens = re.findall(r"\b(20\d{2}-(?:Q[1-4]|\d{2}))\b", changelog)
        violations = []
        for tok in date_tokens:
            if tok < self.PROJECT_LIFETIME_START and not tok.endswith(("Q1", "Q2", "Q3", "Q4")):
                violations.append(tok)
            elif tok.endswith(("Q3", "Q4")) and tok.startswith("2025"):
                violations.append(tok)
        assert not violations, (
            f"CHANGELOG.md contains dates predating the project's actual "
            f"lifetime ({self.PROJECT_LIFETIME_START}+): {violations}. "
            f"These were likely fabricated by an earlier session and "
            f"should be reconciled against actual repo history."
        )


# ── Doc → implementation ─────────────────────────────────────────────────


# pins: claim:hook-assumption-5-session-start-cardinality
class TestNoSessionStartBlocksClaim:
    """Public docs must not claim SessionStart can block / refuse a session.

    Per the official Claude Code hook protocol (docs/external/cc-hook-protocol.md):
    SessionStart cannot block. Doc claims to the contrary mislead users about
    what local hooks can guarantee. The blocking surfaces are PreToolUse and
    ConfigChange; CI is the merge-time gate.

    Allowed replacement language: SessionStart reports / warns / records audit
    events; PreToolUse blocks; ConfigChange blocks settings changes; CI gates
    protected changes.
    """

    # Derived from espalier.surface_contract.get_public_doc_relpaths() (the
    # canonical operator-facing audit set) plus two additional docs that
    # also make protocol claims but aren't in the count-audit set: CLAUDE.md
    # (project memory, internal-facing) and docs/INSTALL-CI.md (operator
    # install guide). Pre-fix this was a hand-curated tuple of 5 docs that
    # missed HOOKS.md, WORKFLOW.md, CHEAT-SHEET.md, CONVENTIONS.md, and
    # QUICKSTART.md — repo-analyst flagged the two SoTs as inconsistent.
    from espalier.surface_contract import get_public_doc_relpaths
    PUBLIC_DOCS = (
        *get_public_doc_relpaths(),
        "CLAUDE.md",
        "docs/INSTALL-CI.md",
    )

    FORBIDDEN_PHRASES = (
        "refuses to proceed",
        "refused session",
        "refuses session",
        "SessionStart blocks",
        "SessionStart enforcement",
    )

    @pytest.mark.parametrize("doc_name", PUBLIC_DOCS)
    def test_no_forbidden_session_start_phrasing(self, doc_name):
        path = REPO_ROOT / doc_name
        if not path.exists():
            pytest.skip(f"{doc_name} not present in repo")
        text = _read(path)
        violations: list[str] = []
        for phrase in self.FORBIDDEN_PHRASES:
            if re.search(re.escape(phrase), text, re.IGNORECASE):
                violations.append(phrase)
        assert not violations, (
            f"{doc_name} contains forbidden SessionStart-as-enforcement "
            f"phrasing: {violations}. Per docs/external/cc-hook-protocol.md, "
            f"SessionStart cannot block. Replace with visibility-only "
            f"language (reports/warns/audits) and point enforcement claims "
            f"at PreToolUse, ConfigChange, or CI."
        )


class TestHookDocstringMatchesImpl:
    """Hook docstrings that mention exit codes match the current
    implementation. Cheap regression on the failure mode where docstrings
    drift from refactored code.
    """

    HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
    GOVERNANCE_HOOKS = ["write_guard.py", "plan_guard.py", "stop_gate.py"]

    @pytest.mark.parametrize("hook_name", GOVERNANCE_HOOKS)
    def test_no_stale_exit_two_block_claim(self, hook_name):
        src = _read(self.HOOKS_DIR / hook_name)
        # Pull the top-of-file docstring.
        # A simple heuristic: the first triple-quoted block.
        match = re.search(r'"""(.+?)"""', src, re.DOTALL)
        assert match, f"{hook_name} has no top-of-file docstring"
        docstring = match.group(1)
        # The old wrong contract phrasing must not appear in docstrings.
        wrong = re.search(r"DENY\s*\(exit\s*2\)", docstring, re.IGNORECASE)
        assert not wrong, (
            f"{hook_name} docstring contains stale 'DENY (exit 2)' claim. "
            f"After TP-9, governance hooks return exit 0 with structured JSON."
        )


class TestAgentDefinitionsMatchProtocol:
    """Agent definitions in `.claude/agents/*.md` must not describe the
    old wrong hook contract (exit 2 + JSON, or the bare decision/reason
    schema as the only block-JSON shape).

    Failure mode this guards against: the audit-accuracy net catches drift
    in SHARP_EDGES and hook source docstrings, but leaves blindspots in
    agent definitions. Code reviewers following stale agent instructions
    would flag correct code as broken, or 'fix' it back to the broken
    contract. TP-RELEASE-14 found this drift; this test prevents recurrence.

    The test does NOT forbid mention of exit 2 — descriptive references to
    'exit 2 ignores JSON' or 'old contract' are fine. It targets imperative
    forms that recommend the broken combo.
    """

    AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

    def _agent_files(self) -> list[Path]:
        return sorted(self.AGENTS_DIR.glob("*.md"))

    def test_agents_dir_has_files(self):
        # Sanity: the test corpus must not silently be empty.
        assert self._agent_files(), (
            "No agent files found at .claude/agents/*.md — the test corpus "
            "is empty and the staleness check is vacuous."
        )

    def test_no_exit_two_block_with_json_recommendation(self):
        """Forbid imperative 'exit 2 + JSON on stdout' phrasings.

        Agents may mention exit 2 descriptively (e.g. 'exit 2 ignores
        stdout'). The forbidden patterns target recommendation forms.
        """
        wrong_patterns = [
            # "exit 2 (block with JSON on stdout)" — imperative form.
            r"exit\s*\*?\*?2\*?\*?\s*\(\s*block\s+with\s+JSON",
            # "exit 0 ... or 2 ..." stated as the canonical pair without
            # the channel-XOR clarification.
            r"hook\s+scripts?\s+exit\s+\*?\*?0\*?\*?\s*\([^)]*\)\s+or\s+\*?\*?2\*?\*?\s*\(",
            # "0/2 only" or "exit 0 or 2" as canonical contract claims.
            r"\b0/2\s+only\b",
        ]
        violations: list[str] = []
        for f in self._agent_files():
            text = _read(f)
            for pattern in wrong_patterns:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    line_no = text[: m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line_no} matches /{pattern}/")
        assert not violations, (
            "Agent definitions contain stale hook-contract phrasing:\n  "
            + "\n  ".join(violations)
            + "\n\nPer docs/external/cc-hook-protocol.md, espalier hooks use exit 0 "
            "with structured JSON. Update the agent to describe the channel-XOR rule "
            "or remove the inline contract restatement and link to the pin."
        )

    def test_pretooluse_schema_not_misdescribed(self):
        """If an agent gives an example block-JSON shape, PreToolUse hooks
        should not be described with the bare decision/reason schema.

        The bare schema is correct for Stop/ConfigChange; using it for
        PreToolUse is a real bug class. We only flag cases where the agent
        explicitly attaches the bare schema to PreToolUse / write_guard /
        plan_guard context.
        """
        # The phantom "stopReason" key in PreToolUse-context examples is
        # the most reliable signal, since it never appears in any current
        # CC schema.
        violations: list[str] = []
        for f in self._agent_files():
            text = _read(f)
            if re.search(
                r'"decision"\s*:\s*"block"[^}]*"stopReason"',
                text,
            ):
                violations.append(f.name)
        assert not violations, (
            f"Agent files contain phantom 'stopReason' field in block-JSON "
            f"examples: {violations}. No current CC hook schema includes "
            f"this field. See docs/external/cc-hook-protocol.md."
        )


# ── CHANGELOG structural invariants ──────────────────────────────────────


class TestChangelogStructure:
    """CHANGELOG.md must maintain Keep-a-Changelog section ordering.

    Guards against the drift that TP-RELEASE-16-changelog-restructure.md
    fixed: [Unreleased] must immediately precede the highest released
    version header. Also pins the stub implication: if [Unreleased] carries
    the sentinel '_No unreleased changes._', there must be no ### / ####
    subheadings between it and the next --- divider.
    """

    CHANGELOG = REPO_ROOT / "CHANGELOG.md"
    # Matches lines like: ## [0.5.0] — 2026-05-04 or ## [0.7.0a1] — 2026-05-18
    SEMVER_HEADER = re.compile(r"^## \[(\d+\.\d+\.\d+(?:\.\d+|a\d+|b\d+|rc\d+)?)\]")
    # Matches any ## [ section header line
    SECTION_HEADER = re.compile(r"^## \[")

    def _section_headers(self) -> list[str]:
        """Return all version/unreleased section header lines, in file order."""
        text = _read(self.CHANGELOG)
        return [line for line in text.splitlines() if self.SECTION_HEADER.match(line)]

    def test_unreleased_is_first_section_header(self):
        headers = self._section_headers()
        assert headers, "CHANGELOG.md has no ## [ section headers"
        assert headers[0].startswith("## [Unreleased]"), (
            f"First ## [ header must be '## [Unreleased]'; got: {headers[0]!r}. "
            "Keep-a-Changelog requires [Unreleased] above all released versions."
        )

    def test_second_header_is_semver_release(self):
        headers = self._section_headers()
        assert len(headers) >= 2, (
            "CHANGELOG.md must have at least one released version below [Unreleased]"
        )
        second = headers[1]
        assert self.SEMVER_HEADER.match(second), (
            f"Second ## [ header must be a SemVer release (e.g. '## [0.5.0] — …'); "
            f"got: {second!r}. Check that [Unreleased] immediately precedes the "
            f"highest released version."
        )

    # A release-section category label, in EITHER shape this project has used.
    #
    # BOTH arms are load-bearing and the live shape has now moved twice, which
    # is the entire argument for keeping the matcher dual-shape rather than
    # tracking whichever form is current:
    #   - `### Added`  — the archived shape (14 in the archived changelog), and
    #     the LIVE shape again as of 2026-08-16c (4 in CHANGELOG.md:
    #     Fixed/Added/Changed/Removed, one each).
    #   - `**Added**`  — the shape CHANGELOG.md used in between, and the one
    #     every dated section below the fold still carries.
    # When the file switched to bold, the contracts here did not follow: they
    # matched `^###` against a document containing ZERO h3 headers — measured
    # tree-wide. They were not merely blind to the duplicates they missed; they
    # had never matched anything at all since the switch, while reporting
    # success every run. A count in this comment has itself gone stale twice
    # (it read "6" until 2026-08-16c), which is the same drift one level up.
    #
    # ⚠ THE MATCHER NO LONGER LIVES HERE. This module owned a hand-rolled copy
    # that was byte-identical to `espalier.changelog.CATEGORY_LABEL_RE`, with
    # nothing binding the two — the same duplicate-detector shape that let the
    # release gate go blind (DEF-457/DEF-591) and that `sister_site_probe.py`
    # cannot see, being scoped to `tools/cc/hooks/` + top-level `espalier/`.
    # Delegate; do not re-roll. The canon documents the arms' semantics
    # (first word only; bold arm is whole-line so `**Why:** ...` inside a
    # bullet is not a category; the h3 arm is deliberately not end-anchored).
    _category = staticmethod(category_label)

    def test_stub_sentinel_implies_no_subheadings(self):
        """When [Unreleased] body contains the stub sentinel, there must be
        zero ### or #### subheadings between it and the next --- divider.

        If the sentinel is absent (real work is in flight), this test passes
        trivially — the implication only fires when the stub is present.
        """
        text = _read(self.CHANGELOG)
        lines = text.splitlines()

        # Locate the [Unreleased] header line index.
        unreleased_idx = next(
            (i for i, ln in enumerate(lines) if re.match(r"^## \[Unreleased\]", ln)),
            None,
        )
        assert unreleased_idx is not None, "CHANGELOG.md missing ## [Unreleased] header"

        # Collect lines from just after the header up to the next --- divider
        # or the next ## [ header, whichever comes first.
        body_lines: list[str] = []
        for ln in lines[unreleased_idx + 1:]:
            if ln.startswith("---") or self.SECTION_HEADER.match(ln):
                break
            body_lines.append(ln)

        body = "\n".join(body_lines)

        STUB_SENTINEL = "_No unreleased changes._"
        if STUB_SENTINEL not in body:
            # Work is in flight — structural check does not apply.
            return

        # Both shapes: an h3/h4 subheading OR a bold category label. Checking
        # only `^#{3,4}` would let a stub sentinel sit above a live `**Fixed**`
        # block — the same blindness that silenced the duplicate check.
        subheadings = [
            ln for ln in body_lines
            if re.match(r"^#{3,4} ", ln) or self._category(ln)
        ]
        assert not subheadings, (
            f"[Unreleased] body contains the stub sentinel {STUB_SENTINEL!r} "
            f"but also has subheadings: {subheadings}. Either remove the sentinel "
            f"(work is in flight) or remove the subheadings (section is a stub)."
        )

    def test_no_duplicate_categories_per_release(self):
        """Each ## [version] section must contain each ### category at most
        once. Per Keep-a-Changelog, duplicates are a format violation that
        confuses programmatic parsers and human readers alike.
        """
        text = _read(self.CHANGELOG)
        lines = text.splitlines()
        current_release: str | None = None
        seen_categories: dict[str, list[str]] = {}
        violations: list[str] = []
        first_seen: dict[str, dict[str, int]] = {}
        for lineno, ln in enumerate(lines, 1):
            if self.SECTION_HEADER.match(ln):
                # Start of a new release section — reset.
                current_release = ln.strip()
                seen_categories[current_release] = []
                first_seen[current_release] = {}
                continue
            category = self._category(ln)
            if category and current_release is not None:
                if category in seen_categories[current_release]:
                    violations.append(
                        f"{current_release} repeats {category!r} at line {lineno} "
                        f"(first at line {first_seen[current_release][category]})"
                    )
                else:
                    seen_categories[current_release].append(category)
                    first_seen[current_release][category] = lineno
        assert not violations, (
            "CHANGELOG.md has duplicate categories within a release section:\n  "
            + "\n  ".join(violations)
            + "\n\nPer Keep-a-Changelog, merge entries under a single category "
            "heading. Move the later block's bullets to the end of the first "
            "block of the same name — every bullet is kept; only the duplicate "
            "label goes away."
        )


# ── Auto-freshness contract layer (post-3-agent review) ─────────────────


class TestCheatSheetCliParity:
    """Every CLI subcommand registered in espalier/cli.py must be mentioned in
    docs/CHEAT-SHEET.md. Catches the recurring "CHEAT-SHEET drifted" bug
    surfaced by repo-analyst review.

    The check is name-only: a subcommand name appearing somewhere in the
    cheat sheet (under any tier or section) counts. Tier organization is a
    separate concern handled by human review.
    """

    CHEAT_SHEET = REPO_ROOT / "docs" / "CHEAT-SHEET.md"

    def _registered_subcommands(self) -> set[str]:
        """TP-29: use argparse introspection instead of regex scraping.
        The regex form missed 4 subcommands registered through helper
        functions. argparse's _SubParsersAction is the source of truth.
        """
        import espalier.cli as cli_module
        parser = cli_module.build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return set(action.choices.keys())
        return set()

    def test_every_cli_subcommand_mentioned_in_cheat_sheet(self):
        registered = self._registered_subcommands()
        cheat = _read(self.CHEAT_SHEET)
        missing = sorted(name for name in registered if name not in cheat)
        assert not missing, (
            "docs/CHEAT-SHEET.md is missing CLI subcommands registered in "
            "espalier/cli.py:\n  "
            + "\n  ".join(missing)
            + "\n\nAdd a line for each (e.g. `espalier <name> <repo>  # short summary`) "
            "or document why the subcommand is intentionally hidden."
        )


class TestSecurityMarkerCoverage:
    """Test files whose names match security-relevant patterns MUST be in
    `tests/conftest.py::_MARKER_RULES` security tuple. Catches the
    `test_stop_gate falls through to unit` class of bugs surfaced by
    repo-analyst review.

    Without this, `pytest -m security` silently misses critical hook /
    integrity / kill-switch tests.
    """

    CONFTEST = REPO_ROOT / "tests" / "conftest.py"
    TESTS_DIR = REPO_ROOT / "tests"

    # Filename stems matching these tokens are security-relevant.
    SECURITY_TOKENS = (
        "hook", "guard", "kill_switch", "integrity",
        "ci_guard", "security", "stop_gate",
    )

    # Stems explicitly NOT to require — keep the allow-list narrow with
    # a one-line reason per entry.
    EXEMPT_STEMS: frozenset[str] = frozenset({
        # test_init_fresh_hooks tests `espalier init`'s hook-deployment
        # behaviour, not hook semantics. It's an integration test, not a
        # security regression. Already classified `integration` + `slow`.
        "test_init_fresh_hooks",
        # test_reflect_link_guards matches the "guard" token nominally: its
        # subject is the reflect pass's broken-link *shape filters*, not a
        # security guard. The reflect surface is advisory and never blocks a
        # tool call, so `pytest -m security` gains nothing from it.
        # Already classified `integration`.
        "test_reflect_link_guards",
        # test_export_guard matches the "guard" token nominally: its subject is
        # tests/_export_guard.py, a test-population guard that narrows a
        # self-expiry assertion on a release export. It guards no tool call
        # and no protected path. Classified `contract` (DEF-670).
        "test_export_guard",
        # test_freshness_hook_count_migration matches the "hook" token by
        # name: its subject is the freshness manifest's hook-count literal
        # against the live wiring -- a tree-wide truth a re-pin can break,
        # not hook semantics. Classified `contract` (2026-09-20, the pre-cut
        # D1 fix) so every tier a re-pin earns runs it;
        # tests/test_proof_tier.py pins that placement.
        "test_freshness_hook_count_migration",
    })

    def _security_relevant_test_stems(self) -> list[str]:
        return sorted(
            p.stem for p in self.TESTS_DIR.glob("test_*.py")
            if any(token in p.stem for token in self.SECURITY_TOKENS)
            and p.stem not in self.EXEMPT_STEMS
        )

    def _security_tuple_in_conftest(self) -> set[str]:
        text = _read(self.CONFTEST)
        # Locate the `_MARKER_RULES` definition (annotated, so AnnAssign in 3.10+)
        # and walk its value: a list of (names_tuple, marker_str) pairs.
        import ast
        tree = ast.parse(text)
        rules_value: ast.expr | None = None
        for node in ast.walk(tree):
            target_id: str | None = None
            value: ast.expr | None = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_id, value = node.target.id, node.value
            elif isinstance(node, ast.Assign):
                first = node.targets[0]
                if isinstance(first, ast.Name):
                    target_id, value = first.id, node.value
            if target_id == "_MARKER_RULES":
                rules_value = value
                break
        if not isinstance(rules_value, ast.List):
            return set()
        for entry in rules_value.elts:
            if not isinstance(entry, ast.Tuple) or len(entry.elts) != 2:
                continue
            names_tuple, marker = entry.elts
            if (
                isinstance(marker, ast.Constant)
                and marker.value == "security"
                and isinstance(names_tuple, ast.Tuple)
            ):
                return {
                    e.value for e in names_tuple.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
        return set()

    def test_security_relevant_tests_are_in_security_tuple(self):
        relevant = self._security_relevant_test_stems()
        in_tuple = self._security_tuple_in_conftest()
        assert in_tuple, (
            "Could not find _MARKER_RULES security tuple in tests/conftest.py — "
            "the test class needs updating."
        )
        missing = sorted(set(relevant) - in_tuple)
        assert not missing, (
            "Security-relevant test files fall through to default 'unit' marker:\n  "
            + "\n  ".join(missing)
            + "\n\nAdd these stems to the 'security' tuple in tests/conftest.py "
            f"_MARKER_RULES. Otherwise `pytest -m security` silently misses them. "
            f"Tokens that classify a file as security-relevant: {self.SECURITY_TOKENS}."
        )


# ── docs/ location invariants (TP-DOC-01) ────────────────────────────────


class TestDocsLocation:
    """Documents moved to docs/ in TP-DOC-01 must not re-appear at repo root.

    The repo root is reserved for OSS-conventional files (README, LICENSE,
    CHANGELOG, CONTRIBUTING, SECURITY) plus the harness self-hosting surface
    (CLAUDE.md, ESPALIER_MEMORY.md). Other markdown belongs in docs/.
    """

    MOVED_TO_DOCS = (
        "POSITIONING.md",
        "SHARP_EDGES.md",
        "TASK_RECIPES.md",
        "CONVENTIONS.md",
        "CHEAT-SHEET.md",
        "INSTALL-CI.md",
    )

    def test_moved_docs_not_at_root(self):
        violations = [
            name for name in self.MOVED_TO_DOCS
            if (REPO_ROOT / name).exists()
        ]
        assert not violations, (
            f"Files re-appeared at repo root that belong in docs/: {violations}. "
            f"See TP-DOC-01."
        )

    def test_moved_docs_present_at_new_location(self):
        missing = [
            name for name in self.MOVED_TO_DOCS
            if not (REPO_ROOT / "docs" / name).exists()
        ]
        assert not missing, (
            f"Files missing from docs/ that should have been moved there: {missing}. "
            f"See TP-DOC-01."
        )


# ── Deploy template snapshots (TP-DOC-02) ────────────────────────────────


class TestDeployTemplateSnapshots:
    """examples/CLAUDE.template.md and examples/ESPALIER_MEMORY.template.md must
    match what `espalier init` actually deploys.

    Per TP-DOC-02 (modified scope): the harness's own root CLAUDE.md and
    ESPALIER_MEMORY.md are working documents the harness needs for self-hosting,
    not deploy templates. The canonical deploy templates live at
    examples/*.template.md so OSS visitors can preview what `init` writes
    to a fresh user repo.

    These tests prevent the snapshots from drifting from the template
    generators. Regenerate with `espalier render-template <subject>`.
    """

    def test_claude_template_render_is_host_independent(self):
        """A COMMITTED document must render the same on every operating system.

        `.claude/settings.json` is gitignored and per-machine, so keying it to
        the host that ran `init` is correct. `CLAUDE.md` is committed and read by
        every collaborator, so keying it to one host is wrong on the merits --
        and it also makes this file's own checked-in snapshot fail on the
        Windows CI leg while passing locally, which is the worst way to find out.

        Driven: an earlier cut of the maintenance-mode fix routed this template
        through the host-keyed renderer. It passed every targeted test and the
        snapshot assertion above is what caught it. Nothing pinned the property
        itself, so this does.
        """
        import sys as _sys
        from unittest import mock
        from espalier.cli import render_canonical_template

        posix = render_canonical_template("claude")
        with mock.patch.object(_sys, "platform", "win32"):
            windows = render_canonical_template("claude")
        assert posix == windows, (
            "the generated CLAUDE.md differs by host, but it is a COMMITTED "
            "file shared across collaborators' machines. Host-key printed "
            "output, never a checked-in document."
        )

    def test_claude_template_snapshot_matches_generator(self):
        from espalier.cli import render_canonical_template
        snapshot = _read(REPO_ROOT / "examples" / "CLAUDE.template.md")
        expected = render_canonical_template("claude")
        assert snapshot == expected, (
            "examples/CLAUDE.template.md is stale. Regenerate with:\n"
            "  python3 -m espalier.cli render-template claude > examples/CLAUDE.template.md"
        )

    def test_memory_template_snapshot_matches_generator(self):
        from espalier.cli import render_canonical_template
        snapshot = _read(REPO_ROOT / "examples" / "ESPALIER_MEMORY.template.md")
        expected = render_canonical_template("memory")
        assert snapshot == expected, (
            "examples/ESPALIER_MEMORY.template.md is stale. Regenerate with:\n"
            "  python3 -m espalier.cli render-template memory > examples/ESPALIER_MEMORY.template.md"
        )

    def test_changelog_template_snapshot_matches_generator(self):
        from espalier.cli import render_canonical_template
        snapshot = _read(REPO_ROOT / "examples" / "CHANGELOG.template.md")
        expected = render_canonical_template("changelog")
        assert snapshot == expected, (
            "examples/CHANGELOG.template.md is stale. Regenerate with:\n"
            "  python3 -m espalier.cli render-template changelog > examples/CHANGELOG.template.md"
        )

    def test_changelog_template_carries_no_internal_provenance_tags(self):
        """The shipped changelog skeleton must model the norm it preaches:
        no internal pack IDs / provenance tags in the template itself."""
        from espalier.cli import render_canonical_template
        from espalier.provenance_census import PROVENANCE_RE

        hits = PROVENANCE_RE.findall(render_canonical_template("changelog"))
        assert not hits, f"changelog template leaks internal tag(s): {hits}"

    def test_render_template_rejects_unknown_subject(self):
        from espalier.cli import render_canonical_template
        with __import__("pytest").raises(ValueError, match="unknown subject"):
            render_canonical_template("readme")


# ── TP-RELEASE-15: stale terminology drift detection ──────────────────────


class TestNoStaleBuilderReferences:
    """The package was renamed builder/ → espalier/ in TP-9. Stale references
    in source, docstrings, and test diagnostics read as 'rename incomplete'
    to anyone browsing the code. Codex was scrubbed in TP-RELEASE-15 (the
    architecture boundary remains, but the specific provider name does not).

    Excluded by design:
    - CHANGELOG.md (historical record).
    - ESPALIER_MEMORY.md and docs/session-archive.md (date-stamped history).
    - SHARP_EDGES entries that quote the rename story (narrative only).
    - Path tokens cc/ and tools/cc/ (refer to Claude Code, the target).
    """

    SCAN_GLOBS = (
        "espalier/**/*.py",
        "tools/**/*.py",
        ".claude/agents/*.md",
        ".claude/commands/*.md",
        ".claude/skills/**/*.md",
        "docs/**/*.md",
        "tests/**/*.py",
        "bench/**/*.py",
        "MANIFEST.in",
        "pyproject.toml",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CLAUDE.md",
    )

    EXEMPT_FILES = {
        "CHANGELOG.md",
        "ESPALIER_MEMORY.md",
        "docs/SHARP_EDGES.md",
        "docs/session-archive.md",
        # This file defines the forbidden patterns themselves; matching them
        # in the test class's own source is not drift.
        "tests/test_documented_claims.py",
    }

    # Word-boundary-anchored patterns. `\bbuilder\b` alone would false-positive
    # on common English ("the release-archive builder"), so each pattern targets
    # an identifier that only makes sense as a reference to the renamed package
    # — or to the project-specific compounds left over from the rename.
    FORBIDDEN_PATTERNS = (
        r"\bcc-builder\b",
        r"\bcc_builder\b",
        r"\bCC[-_ ]Builder\b",
        r"\bbuilder/\b",
        r"\bfrom\s+builder\b",
        r"\bimport\s+builder\b",
        r"\bbuilder\.cli\b",
        r"\bbuilder\.[a-z_]+\b",
        # TP-RELEASE-15: Codex was scrubbed from active surfaces.
        r"\bCodex\b",
        r"\bcodex-builder\b",
        r"\bespalier-codex\b",
    )

    def _should_scan(self, path: Path, repo_root: Path) -> bool:
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        return rel not in self.EXEMPT_FILES

    def test_no_stale_builder_or_codex_references(self):
        violations: list[str] = []
        for glob in self.SCAN_GLOBS:
            for path in REPO_ROOT.glob(glob):
                if not path.is_file():
                    continue
                if not self._should_scan(path, REPO_ROOT):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for pattern in self.FORBIDDEN_PATTERNS:
                    for m in re.finditer(pattern, text):
                        line_no = text[: m.start()].count("\n") + 1
                        rel = path.relative_to(REPO_ROOT)
                        violations.append(
                            f"{rel}:{line_no} matches /{pattern}/ — '{m.group(0)}'"
                        )
        assert not violations, (
            "Stale 'builder' / 'cc-builder' / 'Codex' references found:\n  "
            + "\n  ".join(violations)
            + "\n\nIf the match is intentional historical context, add the file "
            "to TestNoStaleBuilderReferences.EXEMPT_FILES with a comment "
            "explaining why."
        )


# ---------------------------------------------------------------------------
# TP-RELEASE-22 — Hook protocol doc-truth sweep across all public surfaces
# ---------------------------------------------------------------------------


# Wrong shapes — patterns that indicate a doc is recommending the conflated
# hook failure protocol (exit 2 combined with JSON on stdout).
#
# These are scope-narrow: they require a coupling word ("+", "with", "and")
# or the imperative sys.exit(2) form, so they don't fire on correct
# descriptive text such as "exit 2 ignores JSON" or "JSON only on exit 0".
#
# Correct protocol uses exactly ONE channel per hook response:
#   - Structured: exit 0 + JSON on stdout (allow or deny decision)
#   - Simple:     non-zero exit + plain text on stderr (no stdout JSON)
WRONG_PROTOCOL_PATTERNS: tuple[tuple[str, str], ...] = (
    # "exit 2 + JSON" — literal old combined form
    (r"exit\s*2\s*\+\s*json", "exit-2 + JSON conflation"),
    # sys.exit(2) in close proximity to JSON (imperative code pattern)
    (r"sys\.exit\(2\).{0,30}json", "sys.exit(2) alongside JSON"),
    # "exit 2 with/and/plus JSON" — explicit coupling words
    (r"exit\s+(?:code\s+)?2\s+(?:and|with|plus)\s+(?:\w+\s+){0,2}json", "exit-2 combined-with JSON"),
)


def _check_doc_for_wrong_protocol(path: Path) -> list[str]:
    """Return the list of wrong-protocol matches in a doc."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").lower()
    findings: list[str] = []
    for pattern, label in WRONG_PROTOCOL_PATTERNS:
        for m in re.finditer(pattern, text, re.DOTALL):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line_end = len(text) if line_end == -1 else line_end
            findings.append(
                f"{path.name}:{label}: '{text[line_start:line_end][:120]}...'"
            )
    return findings


class TestRootDocsMatchProtocol:
    """README, CLAUDE, CONTRIBUTING must not conflate hook protocols."""

    @pytest.mark.parametrize("relpath", ["README.md", "CLAUDE.md", "CONTRIBUTING.md"])
    def test_no_wrong_protocol_claim(self, relpath):
        findings = _check_doc_for_wrong_protocol(REPO_ROOT / relpath)
        assert not findings, (
            f"Hook protocol drift in {relpath}:\n"
            + "\n".join(f"  - {f}" for f in findings)
            + "\nCorrect: 'exit 2 + stderr text' OR 'JSON with continue=false' "
            "— never both in one response."
        )


class TestDocsDirMatchProtocol:
    """Every public doc under docs/ must not conflate hook protocols."""

    def test_docs_dir_clean(self):
        findings: list[str] = []
        docs_dir = REPO_ROOT / "docs"
        for doc in sorted(docs_dir.glob("*.md")):
            findings.extend(_check_doc_for_wrong_protocol(doc))
        assert not findings, (
            "Hook protocol drift in docs/:\n"
            + "\n".join(f"  - {f}" for f in findings)
        )


class TestAgentDocsMatchProtocol:
    """Every .claude/agents/*.md must not conflate hook protocols.

    Agent docs are read by Claude Code at session start; an agent that
    teaches the wrong protocol corrupts every subsequent hook Claude writes.
    """

    def test_agents_dir_clean(self):
        findings: list[str] = []
        agents_dir = REPO_ROOT / ".claude" / "agents"
        for agent in sorted(agents_dir.glob("*.md")):
            findings.extend(_check_doc_for_wrong_protocol(agent))
        assert not findings, (
            "Hook protocol drift in .claude/agents/:\n"
            + "\n".join(f"  - {f}" for f in findings)
        )


# ---------------------------------------------------------------------------
# TP-RELEASE-14 — Version consistency
# ---------------------------------------------------------------------------


class TestVersionConsistency:
    """pyproject version must have a dated CHANGELOG section, and
    [Unreleased] must not have substantive content above it."""

    def test_pyproject_version_has_dated_changelog_section(self):
        # Route through the canonical extractors: version_surfaces for the pyproject
        # version, changelog.DATED_VERSION_RE for the dated CHANGELOG headers.
        from espalier.changelog import DATED_VERSION_RE
        from espalier.version_surfaces import VERSION_SURFACES, read_surface_version

        version = read_surface_version(REPO_ROOT, *VERSION_SURFACES[0])
        assert version, "pyproject.toml has no version field"

        changelog_text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        assert any(
            m.group("version") == version
            for m in DATED_VERSION_RE.finditer(changelog_text)
        ), (
            f"pyproject version {version!r} has no dated CHANGELOG section. "
            f"Expected format: '## [{version}] — YYYY-MM-DD'"
        )

    # The strict-xfail marker this row carries between releases ([Unreleased]
    # legitimately accumulates the dev record; folding it is the at-cut step)
    # comes OFF in the fold commit, where the row can pass honestly -- last at
    # the 0.8.0b1 cut, 2026-09-24. The first post-cut [Unreleased] entry reds
    # it again; re-arm with ``@pytest.mark.xfail(strict=True, reason=...)``
    # rather than emptying the section (docs/RELEASE_CHECKLIST.md, the
    # "CHANGELOG fold (detail)" step).
    def test_unreleased_section_is_empty(self):
        """[Unreleased] must carry no substantive content between releases.

        SHAPE-BLIND until this rewrite, and completely so: it asserted on `^###`
        subheaders while CHANGELOG.md has never contained a single one -- measured 0 at
        HEAD and at every historical commit sampled. The file labels its groups with
        `**bold**`. So the assertion sat green over a 1,656-line section holding 183
        bullets, and would have sat green over any amount of content whatsoever.

        That is not a weak gate; it is an absent one wearing a gate's name, and it
        guards precisely the forgotten-step this repo's doctrine names as its primary
        threat -- a CHANGELOG fold missed at the release cut. It counts SUBSTANTIVE
        ENTRIES, which is what "substantive" meant all along.

        The count comes from ``espalier.changelog.substantive_entries`` rather than
        a bullet regex spelled here. An inline copy was the third hand-rolled
        content detector in this file, and hand-rolled content detectors in this
        file are the origin of the whole defect class (DEF-457/DEF-591).
        """
        from espalier.changelog import UNRELEASED_BODY_RE, substantive_entries

        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        m = UNRELEASED_BODY_RE.search(text)
        if not m:
            pytest.skip("No [Unreleased] section in CHANGELOG")
        entries = substantive_entries(m.group("body"))
        assert not entries, (
            f"[Unreleased] carries {len(entries)} substantive entries. Fold them into "
            f"a new dated section and bump the pyproject version at the release cut. "
            f"If this is the FIRST entry after a cut, do not empty the section: re-arm "
            f"@pytest.mark.xfail(strict=True, reason=...) on this test instead "
            f"(docs/RELEASE_CHECKLIST.md, the 'CHANGELOG fold (detail)' step)."
        )

    def test_unreleased_section_has_no_internal_provenance_tags(self):
        """The actively-edited [Unreleased] section must stay free of internal
        build-provenance tags (pack IDs, workflow-run ids, review-round tags).

        Historical dated sections are a frozen record and remain allowlisted in
        ``provenance_census`` pending a one-time back-clean; this guard keeps
        *new* changelog entries user-facing so the public changelog never
        re-accumulates a development log at its top. Reuses the census's own
        pattern so the two can't drift.
        """
        from espalier.changelog import UNRELEASED_BODY_RE
        from espalier.provenance_census import PROVENANCE_RE

        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        m = UNRELEASED_BODY_RE.search(text)
        if not m:
            pytest.skip("No [Unreleased] section in CHANGELOG")
        hits = PROVENANCE_RE.findall(m.group("body"))
        assert not hits, (
            f"[Unreleased] contains internal provenance tag(s): {hits}. "
            f"Rewrite the entry in user-facing terms; internal identifiers "
            f"belong in the gitignored dev-log archive, not the public changelog."
        )

    def test_changelog_body_v8_alpha_mentions_match_pyproject_or_tags(self):
        """Every `v0.8.0aN` mention in CHANGELOG body must match
        pyproject.version OR be an existing git tag.

        Scope note: regex narrowed to `v0.8.0a*` (the actual drift class
        TP-145 defends against — TP-141..144 parentheticals labelled
        aspirational versions before they were tagged). The footer's
        compare links are excluded from the scan: each names the PREVIOUS
        tag by construction, and `tests/test_changelog_footer.py` is their
        contract. A version with its own `## [x.y.z]` section counts as
        released alongside the tag list, because the public repository was
        seeded without the development tree's tags (2026-09-25: on its first
        tagged checkout every footer row read as drift against a one-tag
        history).
        """
        import subprocess
        if sys.version_info >= (3, 11):
            import tomllib
        else:  # pragma: no cover -- 3.10 fallback
            import tomli as tomllib  # type: ignore[no-redef]

        pyproject = tomllib.loads(
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        version = pyproject["project"]["version"]
        result = subprocess.run(
            ["git", "tag", "-l"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False, encoding="utf-8",
        )
        tags = set(result.stdout.split())
        if not owns_its_worktree(REPO_ROOT):
            # §C21 (2026-08-14): the tags git just listed are not necessarily
            # OURS. A release archive extracted inside another worktree gets
            # that repo's tags at rc 0, so this validated the parent's tag set
            # against the export's CHANGELOG and reported a pass the artifact
            # had not earned. Measured: passed under `dist/`, skipped outside.
            tags = set()
        if not tags:
            # TP-181 W1-2: a shallow / tagless clone (fresh `git clone`, or
            # espalier's first push without `fetch-depth: 0`) has NO tags, so
            # every historical `v0.8.0a*` mention would read as "drifted" and
            # red. Tag-parity is unknowable without the tags — skip, don't fail.
            pytest.skip("no git tags in this checkout (shallow / tagless clone) "
                        "— v0.8.0a* tag-parity cannot be validated")
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Footer link definitions (`[x.y.z]: https://.../compare/vA...vB`)
        # are the footer test's surface; the body is this one's.
        body = "\n".join(
            ln for ln in text.splitlines()
            if not re.match(r"^\[[^\]]+\]:\s*https?://", ln)
        )
        sectioned = set(re.findall(r"^## \[(\d[^\]]*)\]", text, re.M))
        mentions = set(re.findall(r"v(0\.8\.0a\d+)", body))
        drifted = {
            m for m in mentions
            if m != version and f"v{m}" not in tags and m not in sectioned
        }
        assert not drifted, (
            f"CHANGELOG body mentions v0.8.0a* versions that are not the "
            f"pyproject version, a git tag, or a CHANGELOG section: "
            f"{sorted(drifted)}"
        )


# ---------------------------------------------------------------------------
# Multi-surface numeric constants — drift detection
# ---------------------------------------------------------------------------
#
# Generalizes the pattern that bit twice: when a numeric
# constant lives in both a contract test (the SoT) and ≥3 doc surfaces
# that quote it as prose, raising the constant requires updating every
# surface manually. The 60→75 raise (TP-RELEASE-20) and the 75→80 raise
# (post-Sprint-6) both had stale-surface fallout because nothing
# mechanically pinned the prose against the SoT.
#
# Registry shape: each `NumericContract` declares the SoT value and a
# list of (file, regex) pairs where the same number must appear. The
# regex must have exactly one capturing group containing the number.
# Adding a new contract is one entry; the test logic doesn't change.
# ---------------------------------------------------------------------------


# TP-109b: NumericContract dataclass canonicalized in tests/_contracts.py
# (alongside StringContract / StringListContract). The NUMERIC_CONTRACTS
# tuple stays here as the data registry; the shape lives next to its
# StringContract/StringListContract siblings.
from espalier.claim_extractor import MIRROR, RECORD
from tests._contracts import NumericContract, NumericPopulation, population_sites

# Derived numeric SoTs (2026-09-10): a count the source can be asked for is
# never retyped here. The doc sentence bound in each row is the consent gate
# -- it reds until someone edits it -- and a deleted source row reds it as
# surely as an added one, so the deletion tripwire the literal gave is kept.
from espalier.release_denylist import DENIED_PATTERNS as _DENIED_PATTERNS
from espalier.release_noise import RELEASE_NOISE_PATTERNS as _RELEASE_NOISE_PATTERNS

#: In-scope bypass classes, counted with the glob `espalier/doctor.py` and
#: `scripts/release_check.py` use (tests/test_corpus_count_parity.py holds
#: those two to one pattern; this is that pattern).
_BENCH_IN_SCOPE_CLASSES = len(list((REPO_ROOT / "bench" / "corpus").glob("BC-[0-9]*.json")))

# TP-104: bind multi-surface numeric SoT here too — `ESPALIER_MEMORY.md line cap`
# consumers read from `_surface_expected.py` rather than literals in this
# file.
from tests._surface_expected import (
    CONTRACT_CEILINGS,
    EXPECTED_HOOK_HELPER_COUNT,
    EXPECTED_MEMORY_CAP_GLOB_SITES,
    EXPECTED_MEMORY_CAP_SITES,
    EXPECTED_MEMORY_MD_CAP,
    EXPECTED_UNIVERSAL_AGENTS,
)


# Cap-claim shapes, each verified against a real live site — none speculative.
# A bare "N lines" (space form) is deliberately ABSENT: it matched "324 lines",
# "656 lines" and similar session-log prose about unrelated things.
_CAP_CONTEXT_SHAPES: tuple[str, ...] = (
    # cap verb + number
    r"(?:at most|under|capped at|caps it at|bounded at|past the|over the"
    r"|stay at|--expected-value)\s*~?{value}\b",
    # comparison
    r"[≤<]=?\s*{value}\s+lines?\b",
    # hyphenated compound: "120-line cap", "~120-line index"
    r"~?{value}-line\b",
    # terminal element of a documented cap-history chain (60 → 75 → 80 → 120),
    # which is what makes a raise self-documenting: the history must be
    # APPENDED to rather than silently overwritten.
    r"(?:→|->)\s*{value}\b",
)


# Tracked .md files that state the cap but are deliberately NOT census rows.
# Each carries its reason; `test_census_covers_every_tracked_file_stating_the_cap`
# asserts this map plus the census plus the glob accounts for EVERY tracked
# file, so a new restating surface cannot appear unnoticed.
# Values carry an explicit CLASS token beside the prose: this registry exempts
# surfaces for two unrelated reasons (records vs byte-parity mirrors), and a
# reconciliation keyed on the wording would be one reword away from silently
# reclassifying one. `set(_NOT_CAP_SURFACES)` still yields the paths, so every
# membership read is unchanged.
_NOT_CAP_SURFACES: dict[str, tuple[str, str]] = {
    "CHANGELOG.md": (RECORD, 
        "append-only release record — its cap mentions narrate work done at a "
        "given value and stay CORRECT AS HISTORY once the value moves. "
        "Binding it would force edits to a log. (Discovered by this very "
        "contract: the entry describing it wrote '120-line cap', which is "
        "exactly the 'a new document starts restating the cap' case the "
        "derivation exists to surface.)"
    ),
    # The seven byte-parity mirrors. Binding these would create a second
    # inventory of a fact a mirror row already guarantees; the sync carries
    # them the moment their source moves.
    "espalier/assets/claude/agents/docs-maintainer.md": (MIRROR, "mirror of .claude/ (row: claude-asset)"),
    "espalier/assets/claude/commands/handoff.md": (MIRROR, "mirror of .claude/ (row: claude-asset)"),
    "espalier/assets/claude/skills/design/SKILL.md": (MIRROR, "mirror of .claude/ (row: claude-asset)"),
    "espalier/assets/docs/FRESHNESS.md": (MIRROR, "mirror of docs/ (row: asset-docs)"),
    "examples/dogfooding/.claude/agents/docs-maintainer.md": (MIRROR, "mirror of .claude/ (row: claude-dogfooding)"),
    "examples/dogfooding/.claude/commands/handoff.md": (MIRROR, "mirror of .claude/ (row: claude-dogfooding)"),
    "examples/dogfooding/.claude/skills/design/SKILL.md": (MIRROR, "mirror of .claude/ (row: claude-dogfooding)"),
}


MEMORY_CAP_POPULATION = NumericPopulation(
    name="ESPALIER_MEMORY.md line cap (population)",
    rule_id="memory-cap-population",
    expected_value=EXPECTED_MEMORY_MD_CAP,
    context_shapes=_CAP_CONTEXT_SHAPES,
    required=tuple(EXPECTED_MEMORY_CAP_SITES),
    # `**`, not `*`: memory/ is flat today, but docs/sharp-edges/ is the
    # precedent for reshaping into subdirectories, and the sister contract
    # tests/test_doc_test_citations.py already globs `memory/**/*.md`. Matching
    # it now is a no-op; matching it later would be a silent gap.
    glob_populations=("memory/**/*.md",),
    exclusions=(
        # ⚠ DROPPED 2026-08-20 on this gate's own instruction: the session-log
        # exclusion stopped silencing any cap-stating line once autoprune archived
        # the last row that quoted the cap, so it had become an unexplained hole.
        # It will be OWED AGAIN the next time a session-log row quotes the cap --
        # that is designed churn, not a defect, but the two arms of this module do
        # pull against each other: `test_exclusions_are_still_needed` demands an
        # exclusion be load-bearing TODAY, while this one's own retired reason said
        # the population "is not stable" by construction. Re-add it with that reason
        # rather than re-deriving it; the history is at this line.
        #
        # ⚠ RE-ADDED 2026-08-29 -- the third cycle of this oscillation, exactly as
        # the paragraph above predicted. A Session Log row again quotes the cap, so
        # the count read 2 against a census of 1 and `main` went red. Reason reused
        # verbatim rather than re-derived, per that instruction; the prior drop was
        # `54d3b92`.
        #
        # ⚠⚠ THIS ENTRY IS A KNOWN SCHEDULED RE-BREAK, NOT A FIX. Read this before
        # you are surprised by it: `test_exclusions_are_still_needed` asserts every
        # exclusion silences a cap-stating line TODAY, so this entry goes red the
        # moment autoprune archives that row out of the Session Log -- on
        # autoprune's schedule, not on any change of yours. The pattern being
        # structural rather than content-keyed does NOT prevent that; the assertion
        # is what guarantees the cycle.
        #
        # The non-oscillating fix is region-awareness: treat the rotating Session
        # Log table as outside the population entirely, rather than listing an
        # exclusion that must be added and dropped as rows come and go. That was
        # scoped (~11 gates share this defect, 2 red and 9 latent) and deliberately
        # DEFERRED to unblock the re-home migration. Do not "fix" the next red by
        # bumping the census 1->2 -- the census is right, the population is wrong.
        # 2026-09-07: the scheduled re-break arrived -- autoprune archived the
        # cap-narrating row at the first-hour lane's handoff, and the entry
        # (`"ESPALIER_MEMORY.md", r"^\|\s*\d{4}-\d{2}-\d{2}"`, "Session Log
        # rows are a rotating record, not a claim") was dropped as this note
        # prescribes. Re-add it, verbatim, when a dated Session Log row narrates
        # the cap again; the region-aware fix above is still the way out.
    ),
)


NUMERIC_CONTRACTS: tuple[NumericContract, ...] = (
    NumericContract(
        name="ESPALIER_MEMORY.md line cap",
        # TP-104: SoT moved to tests/_surface_expected.EXPECTED_MEMORY_MD_CAP.
        expected_value=EXPECTED_MEMORY_MD_CAP,
        sources=(
            # SoT: tests/test_contracts.py asserts `len(lines) <= N`
            ("tests/test_contracts.py", r"len\(lines\)\s*<=\s*(\d+)"),
            # Prose: ESPALIER_MEMORY.md self-describes its cap. Accept both phrasings the
            # file has used — "under N lines" and "Bounded at N lines" — while
            # keeping the under/bounded-at prefix anchor so an unrelated
            # "~200 lines/invocation" note elsewhere in the file can't false-match.
            ("ESPALIER_MEMORY.md", r"(?:[Uu]nder|[Bb]ounded at)\s+(\d+)\s+lines"),
            # SHARP_EDGES.md operator entry. Reworded from "stay under N lines" to
            # "stay at N lines or fewer": the mechanism is `<= 120`, so "under 120"
            # named a different (and stricter) number than the gate enforced. Four
            # prose surfaces said one thing and the assertion did another.
            ("docs/SHARP_EDGES.md", r"stay\s+at\s+(\d+)\s+lines\s+or\s+fewer"),
            # README's project structure caption (same rewording).
            ("README.md", r"at\s+most\s+(\d+)\s+lines\)"),
            # docs-maintainer agent definition (×3 occurrences each, both copies).
            # TP-86 rewrote "If >N lines" -> "over the N-line cap" when the
            # manual-prune precondition collapsed into the autoprune hook;
            # the regex source moved with the wording.
            (".claude/agents/docs-maintainer.md", r"target:\s*at\s+most\s+(\d+)\s+lines"),
            (".claude/agents/docs-maintainer.md", r"(\d+)-line\s+cap"),
            (".claude/agents/docs-maintainer.md", r"≤(\d+)\s+lines"),
            ("examples/dogfooding/.claude/agents/docs-maintainer.md", r"target:\s*at\s+most\s+(\d+)\s+lines"),
            ("examples/dogfooding/.claude/agents/docs-maintainer.md", r"(\d+)-line\s+cap"),
            ("examples/dogfooding/.claude/agents/docs-maintainer.md", r"≤(\d+)\s+lines"),
            # TP-86: post_write_check autoprune binds the hook-side cap
            # to the documented value. Subprocess-only invocation of
            # `espalier memory prune` keeps `tools/cc/` espalier-import-free.
            ("tools/cc/hooks/post_write_check.py", r"_MEMORY_MD_CAP\s*=\s*(\d+)"),
        ),
    ),
    # TP-29: three new contracts binding quantitative public claims to SoT counts.
    NumericContract(
        name="release_check result count",
        # SoT: test_release_check.py pins the actual result count from run_all_checks.
        # NOTE: result count (22) != def check_* count (21); one function returns 2 results.
        # TP-189 PUBINT-1 added check_canonical_urls (21->22 results).
        # README.md was previously a source via "... 21 checks ..." but TP-37
        # split that into "N passed, M skipped" (two numbers, not one total).
        # The README demo output snippet is asserted live by
        # test_demo_beat3_release_check_runs in tests/test_demo_end_to_end.py
        # rather than via a numeric contract.
        expected_value=22,
        sources=(
            # Whitespace-tolerant to match how scripts/release_check.py::
            # check_docs_count_claims scrapes the SAME anchor -- keep the two
            # regexes in sync so a trivial reformat of the assertion yields the
            # same verdict from both oracles (both fail loud on a real drift).
            ("tests/test_release_check.py", r"assert\s+len\(results\)\s*==\s*(\d+)"),
            # TP-189: bind README's prose count too — it drifted to "21
            # individual gates" undetected because check_docs_count_claims
            # scans the noun "checks", not "gates".
            ("README.md", r"(\d+) individual gates"),
        ),
    ),
    NumericContract(
        name="bypass class count",
        # Two witnesses since 2026-09-10: the in-scope corpus glob (the SoT,
        # asked directly) and README's sentence. Before that it was a
        # doc-vs-literal snapshot (see the module-docstring note).
        # SoT: BC-NNN-*.json files in bench/corpus/ (OOS variants excluded).
        # R9: added BC-010 (ZIP-slip) and BC-011 (MAINTENANCE_MODE-scope)
        # from round-6/round-8 audits; in-scope count rose 9 -> 11.
        # Post-v0.6.6 review-pass: added BC-012 (BOM JSON), BC-013 (ReDoS
        # interpreter regex), BC-014 (audit-dir symlink). Count rose 11 -> 14.
        # Round 3 must-fix: added BC-015 (blueprint symlink ingestion).
        # Count rose 14 -> 15.
        # TP-42 write-verb expansion: added BC-016 (dd), BC-017 (cp/mv/install -t),
        # BC-018 (install + rsync), BC-019 (truncate), BC-020 (tar -C), BC-021
        # (patch), BC-022 (PowerShell writes). Count rose 15 -> 22.
        # TP-48 trust-boundary: added BC-023 (malformed tool_input type) +
        # BC-024 (matcher missing Task/TodoWrite/SlashCommand). Count 22 -> 24.
        # TP-49 filesystem/encoding: added BC-025 (Unicode normalization
        # NFKC + casefold). Count 24 -> 25.
        # TP-54 marker contract hardening: added BC-026 (marker substring
        # forgery) + BC-031 (marker-preserving disable; folds BC-030's
        # iteration concern into the same row, deliberately no BC-027/028/029/030
        # files since the runner has no contiguity gate). Count 25 -> 27.
        # TP-59 library/hook parity + BC-033 prompt injection: added BC-033
        # (blueprint continuation injection), BC-034 (corpus documented_in
        # stale), BC-035 (self-host name spoof), BC-036 (integrity read
        # mid-write), BC-037 (reflect docs blind spot), BC-038 (library
        # blueprint asymmetry). Count 27 -> 33.
        # TP-55 statusline + maintenance hardening: added BC-027 (statusline
        # blueprint poison), BC-027b (blueprint JSON bomb), BC-028
        # (maintenance bash prefix), BC-028b (stop_gate bash prefix). BC-OOS-004
        # is OOS (out-of-scope shell-expansion class) and excluded from the
        # in-scope count. Count 33 -> 37 in-scope + 1 OOS.
        # TP-56-A freshness-signal-foundation: added BC-039 (gitignored
        # freshness manifest -> vacuous CI gate) and BC-040 (bound-redirect
        # eternal-fresh attack). Count 37 -> 39 in-scope + 1 OOS.
        # TP-74 stop_gate fingerprint shape parity: added BC-041
        # (test-shaped-fixture-bypasses-real-format — de-circularization
        # recipe 3rd occurrence). Count 39 -> 40 in-scope + 1 OOS.
        # v0.7.1.1 hotfix follow-up: added BC-041b (pytest-flag-value-as-path
        # — same site as BC-041, different shape: TP-74's Shape B parser
        # dropped tokens starting with `-` but kept the next token, so
        # marker/keyword/plugin values leaked as positional paths;
        # discovered by failure-mode-reviewer agent during v0.7.1 cluster
        # review). Count 40 -> 41 in-scope + 1 OOS.
        # TP-80 common-tier skill contract: added BC-043
        # (common-tier-skill-references-harness-dev-agent — pre-v0.7.1.1
        # debug skill named architecture-analyst unconditionally;
        # contract pinned by tests/test_skill_tier_contract.py). BC-042
        # is reserved by a TP-56-A internal defense (git-pathspec safety)
        # that has not yet been promoted to a corpus row — see
        # docs/FRESHNESS.md.
        # Count 41 -> 42 in-scope + 1 OOS.
        # TP-130 publish pipeline readiness: added BC-029
        # (audit-accuracy Unicode-digit regex defeat — TP-58 hardening),
        # BC-032 (CI approval-marker trust-the-trigger — TP-58
        # hardening), and BC-044 (kill-switch unconditional under
        # approval — TP-OSS-01 hardening, slot newly assigned).
        # Count 42 -> 45 in-scope + 4 OOS.
        # Rescope sweep (BC-013/BC-014 faithfulness audit): BC-013
        # (ReDoS interpreter regex) and BC-014 (audit-dir HOME-unset
        # symlink TOCTOU) renamed to BC-OOS-005 / BC-OOS-006. Both are
        # real defenses but cannot be faithfully exercised by the
        # block/allow bench runner: BC-013 is a linear-time perf
        # property (enforced in tests/test_redos.py), and BC-014's
        # defended branch (Path.home() raising) is unreachable without
        # monkeypatch + a multi-tenant symlink race. Moving them to the
        # BC-OOS namespace avoids the §5.10 presence-vs-firing trap.
        # Count 45 -> 43 in-scope + 6 OOS.
        # TP-150-B corpus<->runner reconciliation: wired faithful invokers
        # for the previously-unwired verifier names (write_guard_pretooluse,
        # matcher_coverage, is_self_host_repo, regex_extraction, iter_surface,
        # ci_marker, release_check_validate_archive, load_latest_blueprint,
        # list_blueprint_chain, post_compact_output, pytest_collection,
        # killswitch_under_maintenance) so the gate reaches N/N; rescoped two
        # classes that have no faithfully-simulatable runner defense:
        # BC-041b (pytest-flag-value, a2 has no runtime guard) -> BC-OOS-007,
        # BC-036 (integrity read-mid-write concurrent race) -> BC-OOS-008.
        # Count 43 -> 41 in-scope + 8 OOS.
        # TP-169 §13 #6: corpus rows pinning the four shipped freeze-blocker
        # fixes — BC-045 (A1 slash-equivalence), BC-046 (A1 fs-spelling/ADS),
        # BC-047 (A2 MCP nested leaf-walk), BC-048 (A3 symlink creation) +
        # BC-OOS-009 (C2/169-U ReDoS extraction-regex timing, out-of-scope
        # like BC-OOS-005). Count 41 -> 45 in-scope + 9 OOS.
        # Retired BC-043 (common-tier-skill-references-harness-dev-agent)
        # when the harness-dev deploy tier was removed — the bypass class is
        # structurally impossible once every agent ships to every consumer.
        # Count 45 -> 44 in-scope + 9 OOS.
        # TP-444: added BC-049 (in-place edit option-grammar tokenizer -- the
        # BSD/macOS `sed -i ''` spelling and the entire perl in-place verb wrote
        # to protected paths unchecked). Count 44 -> 45 in-scope + 9 OOS.
        # DEF-698 (2026-09-06): BC-OOS-003 (python heredoc) retired into the
        # in-scope row BC-051 (interpreter program on stdin). Count rose 46 -> 47;
        # the OOS namespace fell 9 -> 8.
        # DEF-712 / DEF-718 (2026-09-08): BC-052 (the PowerShell interpreter arm)
        # and BC-053 (the dotenv read leg on both shells). Count rose 47 -> 49.
        # DEF-637 (2026-09-09): BC-054 (a program handed to the other shell is
        # judged by that shell's grammar, both directions). Count rose 49 -> 50.
        # 2026-09-10: derived from the corpus glob. The literal moved five times
        # in a fortnight, each move four edits and a post-commit re-pin; README's
        # sentence is the one copy left to edit, and it reds either way.
        expected_value=_BENCH_IN_SCOPE_CLASSES,
        sources=(
            ("README.md", r"Tested against (\d+)\s+(?:in-scope\s+)?bypass classes"),
        ),
    ),
    # TP-56-A retired: `entry hooks deployed` migrated to the
    # `.espalier/freshness.json` manifest as the `hook-count`
    # fragment (proof-of-model for the freshness signal system).
    # The doc-side claims in CLAUDE.md and docs/HOOKS.md are now
    # checked against the manifest's frozen literal at pin SHA, with
    # bound-path drift detection via the freshness scanner. See
    # `tests/test_freshness_hook_count_migration.py` for the migrated
    # parametrized claim test and `docs/CONVENTIONS.md` "Document
    # freshness" for the workflow.
    # TP-39: bind SHARP_EDGES quantitative claims discovered missing by
    # the post-v0.6.5 multi-agent audit. Live SoT pinned by
    # tests/test_surface_support_matrix.py and tests/test_release_denylist.py
    # respectively (see those files for the live-count assertions).
    NumericContract(
        name="surface matrix row count",
        # doc-drift-only: SINGLE-SOURCE — a doc-vs-literal snapshot, not an
        # independent oracle (the value has one SoT surface; a second witness
        # would be derived from the same source). See the module-docstring note.
        # SoT: data rows in docs/SURFACE_SUPPORT_MATRIX.md (excludes header + separator).
        # FAILURE_MODES §1.11 binding-coverage erosion, again: the count is
        # restated in docs/FAILURE_MODES.md (a seeded doc, so a stale number
        # ships) and only SHARP_EDGES was bound until the 20th row landed
        # (2026-09-25) and the prose had to be found by hand.
        expected_value=20,
        sources=(
            ("docs/SHARP_EDGES.md", r"\((\d+) rows across \d+ status"),
            ("docs/FAILURE_MODES.md", r"repo; (\d+) rows,"),
        ),
    ),
    NumericContract(
        name="release denylist pattern count",
        # SoT: len(espalier.release_denylist.DENIED_PATTERNS), pinned to 56 by
        # tests/test_release_denylist.py::test_denied_patterns_count_matches_sharp_edges_claim.
        # FAILURE_MODES §1.11 binding-coverage erosion: the count drifted to
        # 32/33 on three surfaces because only SHARP_EDGES was bound. Every
        # STABLE surface that restates the count is bound here so it can
        # re-drift only by failing this test. (ESPALIER_MEMORY.md was normalized to
        # drop the brittle count instead of being bound — it is autopruned.)
        #
        # ⚠ THIS COMMENT IS ITSELF A BOUND SURFACE — the 4th source below. It
        # had drifted THREE times (50 → 51 → 55, repaired twice before) because
        # the contract bound three `.md` files and nothing scanned code
        # comments, so the sentence claiming "every stable surface is bound"
        # sat two lines above a stale number. Self-referential and mechanical:
        # the contract now re-drifts only by failing itself.
        # 2026-09-10: the value is the tuple's own length; the four bound
        # surfaces (this comment included) are what must move with it.
        expected_value=len(_DENIED_PATTERNS),
        sources=(
            ("docs/SHARP_EDGES.md", r"\((\d+) patterns, no shared"),
            ("docs/FAILURE_MODES.md", r"\((\d+) patterns, AST-asserted"),
            ("docs/REDEFINED_INFORMATION_REGISTRY.md", r"\((\d+) patterns second witness"),
            ("tests/test_documented_claims.py", r"pinned to (\d+) by"),
        ),
    ),
    NumericContract(
        name="release noise pattern count",
        # SoT: len(espalier.release_noise.RELEASE_NOISE_PATTERNS), pinned as
        # the literal _PINNED_PATTERN_COUNT in tests/test_release_noise_parity.py
        # (the deletion tripwire). The registry line beside the denylist count
        # had drifted 26 -> 47 unnoticed because only its neighbour was bound;
        # binding the doc to the test's literal makes the two move together.
        # 2026-09-10: the value is the tuple's own length; the parity test's
        # literal stays a bound surface, so a silent deletion still reds there.
        expected_value=len(_RELEASE_NOISE_PATTERNS),
        sources=(
            ("docs/REDEFINED_INFORMATION_REGISTRY.md", r"\((\d+) patterns SoT"),
            ("tests/test_release_noise_parity.py", r"_PINNED_PATTERN_COUNT = (\d+)"),
        ),
    ),
    # Post-v0.6.6: bind the ReDoS test budget and worst-case payload size
    # so the CHANGELOG / SHARP_EDGES claims ("linear time on 30KB
    # worst-case input", "100ms budget per pattern") cannot silently
    # drift if a future refactor changes the constants.
    NumericContract(
        name="redos timeout budget ms",
        # doc-drift-only: SINGLE-SOURCE — a doc-vs-literal snapshot, not an
        # independent oracle (one SoT constant). See the module-docstring note.
        # SoT: _BUDGET_MS in tests/test_redos.py. Anchored to line-start so the
        # sibling de-flake ceiling `_CI_SAFE_BUDGET_MS = 1000` (which contains
        # `_BUDGET_MS = 1000` as a substring) is NOT a second, conflicting match.
        expected_value=100,
        sources=(
            ("tests/test_redos.py", r"(?m)^_BUDGET_MS\s*=\s*(\d+)"),
        ),
    ),
    NumericContract(
        name="redos worst case payload bytes",
        # doc-drift-only: SINGLE-SOURCE — a doc-vs-literal snapshot, not an
        # independent oracle (one SoT constant). See the module-docstring note.
        # SoT: _WORST_CASE_BODY_LEN in tests/test_redos.py.
        expected_value=30000,
        sources=(
            ("tests/test_redos.py", r"_WORST_CASE_BODY_LEN\s*=\s*(\d+)"),
        ),
    ),
    NumericContract(
        name="self-host signal count",
        # SoT: espalier/surface_contract.py::is_self_host_repo checks
        # 5 signals -- espalier/ dir, tools/cc/ dir, bench/ dir,
        # pyproject name match, SHA pin on write_guard.py first 200
        # bytes. TP-67 hardened the library to 5; TP-76 brought the
        # hook side to parity via tools/cc/hooks/_self_host_fingerprint.py
        # mirror constants.
        expected_value=5,
        sources=(
            # ESPALIER_MEMORY.md was a 4th source pre-TP-86 (the v0.7.1 Session Log
            # row referenced "5-signal" prose); autoprune archived that row,
            # so ESPALIER_MEMORY.md is no longer a reliable signal-count surface.
            # The three stable code/doc sources remain canonical.
            ("espalier/surface_contract.py", r"(\d+)\s+signals"),
            ("docs/CONVENTIONS.md", r"(\d+)-signal\s+detector"),
            ("tools/cc/hooks/_hook_utils.py", r"(\d+)-signal\s+self-host"),
        ),
    ),
    NumericContract(
        name="canonical hook count",
        # SoT: espalier.harness_config.CANONICAL_HOOK_WIRING dict — the
        # canonical hook-name registry. TP-94 added this binding after
        # the v0.7.4 pre-OSS review caught a README hook-tree drift
        # (subagent_stop missing while prose at line 135 said "10
        # hook entry scripts"). README tree must now match the dict.
        # TP-163: 10 -> 12 (subagent_start.py + context_reinject_failure.py).
        expected_value=12,
        sources=(
            # README's "N hook entry scripts" prose (line pin dropped — TP-174a:
            # the literal line number drifted with surface edits and re-pinning
            # only resets the clock; match the phrase, not the line).
            ("README.md", r"(\d+)\s+hook\s+entry\s+scripts"),
            # README's hook-tree caption ("12 hook scripts:"). The (Ten|...)
            # alternative is vestigial — README no longer contains the word
            # "Ten" here — but is harmless, so kept.
            ("README.md", r"(Ten|\d+)\s+hook\s+scripts"),
            # CANONICAL_HOOK_WIRING dict keys — count-by-occurrence on
            # the canonical registry's structure. Each key matches the
            # `"<name>.py": {` opening; capture is the bare hook name
            # (non-digit so the test logic falls through to len(matches)).
            ("espalier/harness_config.py", r'"([a-z_]+)\.py":\s*\{'),
        ),
    ),
    # TP-145: pin previously-unbound common-tier asset counts. The bypass
    # class corpus count is already pinned above; the scanner sub-mode
    # count is deferred to TP-146 ("parse cli.py's scan-mode registry —
    # defer if non-trivial" per pack 145-L).
    NumericContract(
        name="slash command count",
        # doc-drift-only: SINGLE-SOURCE — a doc-vs-literal snapshot, not an
        # independent oracle. An on-disk `.claude/commands/*.md` count could be
        # a second witness, but adding it needs a logic change to
        # TestNoStaleNumericContracts (text-regex only) — deferred (TP-225
        # scope-out). See the module-docstring note.
        # SoT: all shipped .claude/commands/ entries. The renderer fills
        # the adopter-template Slash Commands table at init time.
        # Count-by-occurrence: each `| `/name` |` row is one match.
        # `(?m)` inlines re.MULTILINE so `^` anchors per-line —
        # the test uses re.findall(pattern, text) without flags.
        # TP-210: 11 -> 14 (implement-pack + scope-check + audit-accuracy
        # promoted); 14 -> 15 when /integrity joined the universal set
        # (the harness-dev deploy tier was retired); 15 -> 16 (TP-214: +/read-summary);
        # 16 -> 17 (TP-233b: +/strengthen).
        expected_value=17,
        sources=(
            (
                "examples/CLAUDE.template.md",
                r"(?m)^\|\s*`/([a-z][a-z-]*)`\s*\|",
            ),
            # The FRONT DOOR states it too, in three places, and none of them was
            # bound to anything until now — the surface a stranger reads first was
            # the one surface no contract watched.
            ("README.md", r"(\d+)\s+slash\s+commands"),
            ("docs/QUICKSTART.md", r"\d+ / (\d+) / \d+ \(agents / commands"),
        ),
    ),
    NumericContract(
        name="skill count",
        # doc-drift-only: SINGLE-SOURCE — a doc-vs-literal snapshot, not an
        # independent oracle. A `.claude/skills/*/SKILL.md` count could be a
        # second witness, but that needs a TestNoStaleNumericContracts logic
        # change — deferred (TP-225 scope-out). See the module-docstring note.
        # Skill rows have exactly two columns (Skill | Trigger phrase)
        # vs agent rows which have three (Agent | Model | Role). The
        # `[^|]+\|\s*$` tail anchors on the end-of-row pipe after a
        # single description column — excludes agent rows that have
        # a middle column break.
        # TP-210: 7 -> 9 (blueprint-authoring + hook-authoring promoted);
        # unchanged at 9 by the tier retirement (verify-release, the only
        # retired skill, was already harness-dev — never in this table).
        expected_value=9,
        sources=(
            (
                "examples/CLAUDE.template.md",
                r"(?m)^\|\s*`(?!/)([a-z][a-z-]*)`\s*\|[^|]+\|\s*$",
            ),
            ("README.md", r"(\d+)\s+on-demand\s+skills"),
            ("docs/QUICKSTART.md", r"\d+ / \d+ / (\d+) \(agents / commands"),
        ),
    ),
    NumericContract(
        name="governance agent count",
        # Previously bound NOWHERE. The README states it twice and QUICKSTART once,
        # and nothing checked any of them: `slash command count` and `skill count`
        # existed while their sibling did not, so an agent added or removed drifted
        # the front door silently.
        # SoT: tests/_surface_expected.EXPECTED_UNIVERSAL_AGENTS (`# class: literal`,
        # so it is a legitimate independent witness against prose).
        expected_value=len(EXPECTED_UNIVERSAL_AGENTS),
        sources=(
            ("README.md", r"(\d+)\s+governance\s+agents"),
            ("docs/QUICKSTART.md", r"(\d+) / \d+ / \d+ \(agents / commands"),
        ),
    ),
    NumericContract(
        name="hook helper module count",
        # The other half of README's "N hook entry scripts + M helper modules"
        # inventory bullet. The entry-script half has been bound since TP-94 (see
        # `canonical hook count`); the helper half never was, so half the sentence
        # was checked and half was prose.
        # SoT: tests/_surface_expected.EXPECTED_HOOK_HELPER_COUNT. Counts the
        # underscore-prefixed modules EXCLUDING `__init__.py`, which is a package
        # marker rather than a helper — that distinction is why a naive
        # `_*.py` count reads 14 and the honest answer is 13.
        expected_value=EXPECTED_HOOK_HELPER_COUNT,
        sources=(
            ("README.md", r"hook\s+entry\s+scripts\s*\+\s*(\d+)\s+helper\s+modules"),
        ),
    ),
)


class TestNoStaleNumericContracts:
    """Multi-surface numeric constants must agree across every surface
    that quotes them.

    Pre-fix this was a recurring class of bug — see ESPALIER_MEMORY.md "Multi-
    surface numeric constants drift silently" pattern row. Adding a new
    contract is one `NumericContract` entry in `NUMERIC_CONTRACTS`; the
    test logic doesn't change. When the SoT value changes, this test
    fails on every stale surface in one go and fixes are applied in one
    commit.
    """

    @pytest.mark.parametrize("contract", NUMERIC_CONTRACTS, ids=lambda c: c.name)
    def test_all_surfaces_agree(self, contract: NumericContract):
        from espalier.surface_contract import parse_count_token as _pct

        mismatches: list[str] = []
        for relpath, pattern in contract.sources:
            path = REPO_ROOT / relpath
            assert path.exists(), (
                f"NumericContract source missing: {relpath} "
                f"(contract: {contract.name}). Update the registry or "
                f"restore the file."
            )
            text = path.read_text(encoding="utf-8")
            matches = re.findall(pattern, text)
            if not matches:
                mismatches.append(
                    f"  {relpath}: regex {pattern!r} matched 0 times "
                    f"(expected ≥1 occurrence containing {contract.expected_value})"
                )
                continue
            for match_str in matches:
                if not match_str.isdigit():
                    # TP-29: non-digit match — either a spelled-out number
                    # ("nine", "Nine") or a count-by-occurrence source
                    # (function names when using `def (check_\w+)\(`).
                    n = _pct(match_str)
                    if n is not None:
                        value = n
                    else:
                        # Count-by-occurrence: the number of matches IS the value.
                        value = len(matches)
                        if value != contract.expected_value:
                            mismatches.append(
                                f"  {relpath}: {pattern!r} matched "
                                f"{value} occurrences (expected "
                                f"{contract.expected_value} per contract)"
                            )
                        break
                else:
                    value = int(match_str)
                if value != contract.expected_value:
                    mismatches.append(
                        f"  {relpath}: matched {match_str!r} → {value} "
                        f"(expected {contract.expected_value}) "
                        f"via regex {pattern!r}"
                    )
        assert not mismatches, (
            f"Numeric contract '{contract.name}' has stale surfaces "
            f"(expected value: {contract.expected_value}):\n"
            + "\n".join(mismatches)
            + "\n\nUpdate every stale surface to match the SoT value, "
            "or update NUMERIC_CONTRACTS in tests/test_documented_claims.py "
            "if the SoT itself changed."
        )


class TestMemoryCapPopulation:
    """The cap's whole restatement population, not four hand-picked phrasings.

    `TestNoStaleNumericContracts` above binds `(relpath, regex)` pairs, so a
    restatement nobody wrote a row for is invisible to it — and it leaked
    inside a file it already declared (`docs/SHARP_EDGES.md` had 1 of 4
    statements bound). These two tests close that: one proves each file still
    states the current value, the other proves it states it the expected
    number of times.
    """

    def test_census_covers_every_tracked_file_stating_the_cap(self):
        """Derive the population; do not trust the hand-written census.

        Without this, `EXPECTED_MEMORY_CAP_SITES` is a hand-maintained
        enumerator whose rows are read ONLY by the two parametrize decorators
        below — so deleting a row deletes its own tests and the suite stays
        green. Measured: dropping 4 rows shrinks the cases 20 → 12 silently.
        The instruction "do NOT drop the row" lived only in the failure text
        of a test that would no longer run.

        It is also symmetric: a NEW doc that starts restating the cap is
        enrolled by nothing. This asserts census + glob + documented
        exclusions == every tracked `.md` that states it.
        """
        try:
            out = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"],
                capture_output=True, text=True, check=True, encoding="utf-8",
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("`git ls-files` unavailable — not a dev tree / fresh clone")
        tracked = [f for f in out.split() if f.endswith(".md")]
        if not tracked:
            pytest.skip("`git ls-files` yielded no .md — not a dev tree / fresh clone")

        discovered = {
            rel for rel in tracked
            if population_sites(REPO_ROOT, MEMORY_CAP_POPULATION, rel)
        }
        glob_covered = {
            p.relative_to(REPO_ROOT).as_posix()
            for pattern in MEMORY_CAP_POPULATION.glob_populations
            for p in REPO_ROOT.glob(pattern)
        }
        accounted = set(EXPECTED_MEMORY_CAP_SITES) | glob_covered | set(_NOT_CAP_SURFACES)
        unaccounted = sorted(discovered - accounted)
        vanished = sorted(set(EXPECTED_MEMORY_CAP_SITES) - discovered)
        # On a release export a census row can be absent by construction
        # (ESPALIER_MEMORY.md is an export-ignore sentinel); that is not the
        # row ceasing to state the cap (DEF-670).
        vanished = sorted(set(vanished) - pruned_from_this_tree(vanished))
        assert not unaccounted and not vanished, (
            "the cap-population contract no longer accounts for every tracked "
            "file that states the cap.\n"
            f"  states the cap but accounted for nowhere ({len(unaccounted)}): "
            f"{unaccounted}\n"
            f"  in the census but no longer stating it ({len(vanished)}): "
            f"{vanished}\n"
            "Add a census row, or add it to _NOT_CAP_SURFACES WITH ITS CLASS AND REASON "
            "— do not narrow the discovery."
        )
        assert len(EXPECTED_MEMORY_CAP_SITES) >= 10, (
            f"only {len(EXPECTED_MEMORY_CAP_SITES)} surfaces enrolled; the "
            "census collapsed. This is a FLOOR, not a count: surfaces may be "
            "added, but a census that silently shrinks leaves the two "
            "parametrized contracts below asserting over fewer files while "
            "still reporting success."
        )

    def test_exclusions_are_still_needed(self):
        """Make the exclusion list self-expiring, and budget its size.

        An exclusion outlives its reason silently. The list is EMPTY today, and
        the way it emptied is the argument for keeping this docstring: the one
        entry here earned its keep while `ESPALIER_MEMORY.md`'s session log held a
        row quoting the cap, that file sat at its cap with no headroom, autoprune
        archived the row on its own schedule, and the exclusion was dropped in
        `54d3b92` once it silenced nothing. Exactly as predicted here, which is
        why the reasoning is preserved rather than deleted — the same exclusion is
        owed again the next time a session-log row quotes the cap.

        ⚠ Tense corrected 2026-08-20: this said "currently earns its keep" for as
        long as the list was empty. The ceiling assertion below is `<=`, so an
        empty population passes it and nothing red-flagged the drift.
        """
        ceiling = CONTRACT_CEILINGS[MEMORY_CAP_POPULATION.rule_id]
        assert len(MEMORY_CAP_POPULATION.exclusions) <= ceiling, (
            f"{len(MEMORY_CAP_POPULATION.exclusions)} exclusions vs "
            f"CONTRACT_CEILINGS['{MEMORY_CAP_POPULATION.rule_id}']={ceiling}. "
            "Adding exclusions is how this gate erodes — fix the prose or "
            "narrow a context shape instead, or justify raising the ceiling."
        )
        matcher = MEMORY_CAP_POPULATION.matcher()
        for relpath, pattern, reason in MEMORY_CAP_POPULATION.exclusions:
            path = REPO_ROOT / relpath
            assert path.is_file(), (
                f"exclusion names {relpath} ({reason}) but that file no "
                "longer exists — drop the entry."
            )
            rx = re.compile(pattern)
            silenced = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if rx.search(line) and matcher.search(line)
            ]
            assert silenced, (
                f"the exclusion {pattern!r} on {relpath} no longer silences "
                f"any cap-stating line, so it is a permanent unexplained hole "
                f"rather than a justified one. Reason on file: {reason!r}. "
                "Drop the entry — the census count will move by zero."
            )

    @pytest.mark.parametrize("relpath", sorted(MEMORY_CAP_POPULATION.required))
    def test_every_declared_file_states_the_current_cap(self, relpath: str):
        """Anti-stale: raise the cap and each file reds until its prose moves.

        This is the per-file red. An aggregate assertion would say only "the
        total moved" and leave the operator to find which surfaces are stale.
        """
        assert (REPO_ROOT / relpath).exists(), (
            f"Declared cap surface is missing: {relpath}. Update "
            f"EXPECTED_MEMORY_CAP_SITES in tests/_surface_expected.py or "
            f"restore the file."
        )
        sites = population_sites(REPO_ROOT, MEMORY_CAP_POPULATION, relpath)
        assert sites, (
            f"{relpath} no longer states the ESPALIER_MEMORY.md line cap "
            f"({EXPECTED_MEMORY_MD_CAP}). Either its prose went stale against "
            f"the SoT (tests/_surface_expected.EXPECTED_MEMORY_MD_CAP), or the "
            f"claim was reworded into a shape this contract does not know. "
            f"Fix the prose, or add the new shape to _CAP_CONTEXT_SHAPES — do "
            f"NOT drop the row, which would silently un-bind the surface.\n"
            f"\n"
            f"If you are RAISING the cap, this is a 3-step change and these "
            f"reds are only step 1:\n"
            f"  1. the prose on every surface below;\n"
            f"  2. `espalier freshness pin memory-line-cap` — the fragment is "
            f"verify-on-touch, and .espalier/freshness.json is "
            f"write-guard-protected, so a plain edit is DENIED;\n"
            f"  3. the mirror syncs (sync_claude_mirrors / sync_asset_docs / "
            f"sync_vendor_cc).\n"
            f"Cap-history chains are APPENDED to (…80 → 120 → <N>), not "
            f"overwritten — that is what keeps the history honest."
        )

    @pytest.mark.parametrize("relpath", sorted(MEMORY_CAP_POPULATION.required))
    def test_declared_files_state_it_the_expected_number_of_times(
        self, relpath: str
    ):
        """Completeness: a PARTIAL update reds too.

        The assertion that earns this contract. `docs/SHARP_EDGES.md` states
        the cap four times; updating only the one line the old occurrence
        contract bound leaves three false, and nothing caught that before.
        """
        expected = EXPECTED_MEMORY_CAP_SITES[relpath]
        # Same precheck as its sibling: without it a DELETED file reports
        # "states the cap 0 times" — a count complaint about a file that
        # isn't there, which reads as a prose problem.
        assert (REPO_ROOT / relpath).exists(), (
            f"Declared cap surface is missing: {relpath}. Update "
            f"EXPECTED_MEMORY_CAP_SITES in tests/_surface_expected.py or "
            f"restore the file."
        )
        sites = population_sites(REPO_ROOT, MEMORY_CAP_POPULATION, relpath)
        rendered = ", ".join(f":{ln} {txt!r}" for ln, txt in sites) or "(none)"
        assert len(sites) == expected, (
            f"{relpath} states the line cap {len(sites)} time(s); "
            f"EXPECTED_MEMORY_CAP_SITES declares {expected}.\n"
            f"  found: {rendered}\n"
            f"If you updated the cap, update EVERY site in this file — a "
            f"partial update is exactly what this assertion exists to catch. "
            f"If you deliberately added or removed a restatement, update the "
            f"census in tests/_surface_expected.py."
        )

    def test_glob_population_states_the_current_cap(self):
        """`memory/*.md` boilerplate, pinned in aggregate.

        No per-file rule here: most notes legitimately never mention the cap,
        so a min-one assertion would manufacture one finding per silent note.
        The aggregate still reds on a raise, because every stale site drops
        out of the count at the new value.
        """
        total = 0
        per_file: list[str] = []
        for pattern in MEMORY_CAP_POPULATION.glob_populations:
            for path in sorted(REPO_ROOT.glob(pattern)):
                relpath = path.relative_to(REPO_ROOT).as_posix()
                hits = population_sites(REPO_ROOT, MEMORY_CAP_POPULATION, relpath)
                if hits:
                    total += len(hits)
                    per_file.append(f"{relpath}={len(hits)}")
        assert total == EXPECTED_MEMORY_CAP_GLOB_SITES, (
            f"memory/*.md states the line cap {total} time(s); "
            f"EXPECTED_MEMORY_CAP_GLOB_SITES declares "
            f"{EXPECTED_MEMORY_CAP_GLOB_SITES}.\n"
            f"  found: {', '.join(per_file) or '(none)'}\n"
            f"Adding a memory note that carries the cross-link boilerplate "
            f"moves this count — bump the constant. A DROP to zero means the "
            f"cap was raised without updating the notes."
        )

    def test_declared_population_is_not_a_subset_of_the_occurrence_contract(self):
        """Guard the reason this contract exists.

        If someone folds every declared file back into `NUMERIC_CONTRACTS`,
        the population contract silently becomes a duplicate inventory and
        the next author will delete one of them. This pins the asymmetry that
        justifies keeping both: the population covers surfaces the occurrence
        contract does not.
        """
        occurrence_paths = {
            relpath
            for contract in NUMERIC_CONTRACTS
            if contract.name == "ESPALIER_MEMORY.md line cap"
            for relpath, _pattern in contract.sources
        }
        population_only = set(EXPECTED_MEMORY_CAP_SITES) - occurrence_paths
        # A FLOOR, not `assert population_only`. At >=1 this passes with 9 of
        # 10 folded back into the occurrence contract — it would have called
        # a collapsed population healthy, which is exactly the born-weak
        # shape it is meant to prevent. 6 are population-only today.
        assert len(population_only) >= 5, (
            f"only {len(population_only)} of "
            f"{len(EXPECTED_MEMORY_CAP_SITES)} census surfaces are covered "
            f"by this contract ALONE (was 6 when written): "
            f"{sorted(population_only)}. Below the floor it duplicates "
            "NUMERIC_CONTRACTS instead of extending it, and the next author "
            "will reasonably delete one of the two."
        )


class TestScanSubmodesConsistent:
    """The /scan sub-mode set must agree across espalier/cli.py::cmd_scan
    (SoT) and every doc surface that lists the modes.

    TP-77 found three different counts shipping simultaneously:
      - docs/CHEAT-SHEET.md   : 3 modes (missing perf_smells)
      - CLAUDE.md             : 5 modes (spurious freshness)
      - cmd_scan dispatch     : 4 modes (the SoT)

    Presence-set parity test rather than NumericContract because the
    /scan claim shape has no natural digit binding in prose. Canonical
    set is derived live from cmd_scan's `from espalier.scanners.<NAME>
    import scan_repo as ...` import block (AST-walked) — adding or
    removing a scanner there auto-updates the expectation here.

    `freshness` is a separate top-level command (cmd_freshness_check),
    not a /scan sub-mode. The second test bans /scan + freshness line
    co-occurrence in /scan-context surfaces.

    TWO VERDICTS, NOT ONE -- enumerate OR disclose. The canonical set
    was always derived; the *population* below was not, and
    `docs/WORKFLOW.md` sat outside it showing 3 of 10 while this test
    stayed green. Adding it exposed the real problem with a
    name-everything rule: WORKFLOW is a narrative walkthrough whose
    fence is deliberately a 3-item example, so forcing a ten-line block
    into it would be the gate degrading the doc to satisfy itself. So a
    surface now passes by naming every sub-mode OR by carrying an
    explicit "N of M" disclosure -- and the disclosure is CHECKED, not
    merely detected: M must equal the live canonical count and N must
    equal how many sub-modes the surface actually names. A doc cannot
    buy silence with a disclosure that is itself stale. Same shape as
    the "self-host only -- not deployed by `init`" marker the pointer
    gate uses: the disclosure IS the fix.
    """

    SUBMODE_DOC_SURFACES: tuple[str, ...] = (
        "docs/CHEAT-SHEET.md",
        "CLAUDE.md",
        ".claude/commands/scan.md",
        "espalier/assets/claude/commands/scan.md",
        "examples/dogfooding/.claude/commands/scan.md",
        "docs/WORKFLOW.md",
        "espalier/assets/docs/WORKFLOW.md",
        # The CHEAT-SHEET twin. Enrolled when the discovery arm below grew a
        # prose recognizer and named it: the WORKFLOW twin was already here and
        # this one was not, on no stated grounds. Byte-parity holds both to
        # their sources, so neither strictly needs enrolling -- but one-in
        # one-out is the inconsistency a future session copies.
        "espalier/assets/docs/CHEAT-SHEET.md",
    )

    #: Spelled-out numerals a disclosure may use. Kept small on purpose --
    #: a disclosure is prose, and a surface needing "seventeen of twenty"
    #: has outgrown being an example.
    _NUMERALS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12,
    }

    #: e.g. "Three of ten `/scan` sub-modes are shown above", "3 of 13 …".
    #: Tolerant where tolerance is free and strict where it is not: an optional
    #: article and an optional hyphen in "sub-modes" were both rejected by the
    #: first version, so ordinary true prose ("Three of THE ten `/scan`
    #: submodes") reded while the failure message told the author to write
    #: exactly what they had just written.
    _DISCLOSURE_RE = re.compile(
        r"\b(\w+) of (?:the )?(\w+) `?/scan`? sub-?modes\b", re.IGNORECASE
    )

    @classmethod
    def _disclosures(cls, text: str) -> "list[tuple[int, int]]":
        """EVERY (shown, total) the surface discloses.

        All of them, not the first. `.search` let a second, stale disclosure
        ride along unchecked -- measured: appending "Elsewhere we cover seven of
        four `/scan` sub-modes" left the suite green, which is the same silence
        the first-disclosure check exists to deny.
        """
        def num(tok: str) -> "int | None":
            tok = tok.lower()
            return int(tok) if tok.isdigit() else cls._NUMERALS.get(tok)

        out = []
        for m in cls._DISCLOSURE_RE.finditer(text):
            shown, total = num(m.group(1)), num(m.group(2))
            if shown is not None and total is not None:
                out.append((shown, total))
        return out

    @staticmethod
    def _canonical_submodes(repo_root: Path) -> set[str]:
        import ast
        source = (repo_root / "espalier" / "cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "cmd_scan":
                names: set[str] = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.ImportFrom):
                        mod = sub.module or ""
                        if mod.startswith("espalier.scanners."):
                            names.add(mod.rsplit(".", 1)[1])
                return names
        raise AssertionError("cmd_scan not found in espalier/cli.py")

    def test_each_doc_surface_mentions_every_canonical_submode(self) -> None:
        canonical = self._canonical_submodes(REPO_ROOT)
        assert canonical, "cmd_scan has no scanner imports — refactor regression?"
        for relpath in self.SUBMODE_DOC_SURFACES:
            text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
            # WORD-BOUNDED, not `name in text`. Plain containment lets an
            # unrelated word stand in for the sub-mode: "blueprints" satisfies
            # `prints`, and `test_scanner_magic_depth.py` satisfies
            # `magic_depth`. Measured: deleting every standalone `prints` from
            # docs/CHEAT-SHEET.md still left this green off "Cognitive
            # blueprints" alone -- and it also inflated `len(named)`, so the
            # disclosure arm below accepted "Three of ten" over a fence showing
            # two. Containment was standing in for enumeration in both arms.
            named = {
                name for name in canonical
                if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)
            }
            missing = sorted(canonical - named)
            if not missing:
                continue

            disclosures = self._disclosures(text)
            assert disclosures, (
                f"{relpath} missing canonical sub-mode(s) {missing} "
                f"from cmd_scan import set {sorted(canonical)}.\n"
                "Either name every sub-mode, or state the shortfall in prose "
                'as e.g. "Three of ten `/scan` sub-modes are shown" (digits '
                'work too: "3 of 10" — which is the form to use once the count '
                "passes twelve, where the spelled-out numerals stop) — a "
                "partial list with no disclosure reads as the whole set."
            )
            # EVERY disclosure is checked, not just the first.
            for shown, total in disclosures:
                assert total == len(canonical), (
                    f"{relpath} discloses '{shown} of {total}' but cmd_scan "
                    f"defines {len(canonical)} sub-modes. The disclosure is "
                    "stale — the same defect as the partial list it excuses."
                )
            # `shown` is a claim about the ENUMERATION, so it is measured
            # against invocations, not against `named`. `named` is
            # document-wide mentions, which is the right measure for the
            # *missing* arm above and the wrong one here: comparing a
            # whole-document token count to a claim about one block is the
            # count-and-list-from-two-populations defect this class is made of.
            # Measured: the ordinary English verb in "it prints recovery
            # guidance" kept `len(named)` at 3 after a sub-mode was deleted
            # from WORKFLOW's fence, so a stale "Three of ten" stayed green
            # even with word-boundary matching.
                invoked = {
                    m.group(1) for m in self._INVOCATION_RE.finditer(text)
                } & canonical
                assert shown == len(invoked), (
                    f"{relpath} discloses '{shown} of {total}' but invokes "
                    f"{len(invoked)}: {sorted(invoked)}."
                )

    #: A sub-mode invocation, e.g. ``/scan godfiles`` or ``| /scan prints |``.
    _INVOCATION_RE = re.compile(r"/scan\s+([a-z_]+)")

    #: The OTHER enumeration form: ``(sub-modes: exceptions, prints, …)``.
    #: Added because an invocation-only recognizer could not see the two
    #: surfaces carrying the complete list -- ``docs/CHEAT-SHEET.md`` (the doc
    #: WORKFLOW's own disclosure sends readers to "for the full set") and root
    #: ``CLAUDE.md``. Measured: removing either from the population went
    #: undetected, i.e. the discovery arm could not re-derive its own
    #: membership, which is the defect it exists to prevent.
    _PROSE_LIST_RE = re.compile(r"sub-?modes?:\s*([^)\n]+)")

    #: Surfaces exempt from discovery, with the reason each is exempt.
    #: ``CHANGELOG.md`` is append-only history: an ordinary release note naming
    #: two new scanners ("`/scan magic_depth` finds …, `/scan retired_vocab`
    #: flags …") would enroll it and then demand it enumerate all ten or carry
    #: a disclosure -- forcing an edit to a historical record mid-release, with
    #: no clean exit. The rest are declared record surfaces (Core Rule 13),
    #: where a stale enumeration is expected aging and editing one falsifies
    #: the record. Measured today: none of these is currently flagged, so this
    #: is a stated pre-decision, not a suppression of live noise.
    _DISCOVERY_EXEMPT = {
        "CHANGELOG.md",
        "docs/session-archive.md",
        "memory/CONVERGENCE_LEDGER.md",
    }

    def test_every_enumerating_doc_is_in_the_population(self) -> None:
        """The discovery arm -- without it, the population is a hand-list.

        This class derived its canonical set live and still missed
        ``docs/WORKFLOW.md`` for the whole of that doc's life, because the
        SURFACE list was hand-written: a doc outside it can enumerate 3 of 10
        forever and this file stays green. That is the enumeration-integrity
        class reproducing inside the guard built to catch it.

        **Calibrated against the live corpus, not guessed.** Two rules were
        measured over all 278 tracked ``.md`` files before this one was
        written. *Naming >=2 sub-mode tokens anywhere* flags 20 files, 13 of
        them prose mentions or record surfaces -- including
        ``docs/known-findings.md``, which Core Rule 13 forbids enrolling at
        all. *Invoking >=2 distinct sub-modes* still flags three docs whose
        references are incidental and, in ``docs/CONVENTIONS.md``'s case, 1100
        lines apart. The discriminator that actually separates an enumeration
        from a mention is **contiguity**: a list presents its items together.
        Requiring >=2 distinct invocations inside a single blank-line-delimited
        block flags exactly 5 files, all of them real enumeration surfaces,
        with zero false positives.
        """
        canonical = self._canonical_submodes(REPO_ROOT)
        # §C21/`DEF-570`: `check=True` catches rc 128 and NOT the zero-rows-at-rc-0
        # answer git gives inside a gitignored directory. This is the DISCOVERY arm
        # -- its whole purpose is that SUBMODE_DOC_SURFACES was hand-written and a
        # doc outside it "can enumerate 3 of 10 forever and this file stays green."
        # Over an empty population it IS that failure. Measured 2026-08-14: green
        # on a release archive extracted under `dist/`, red on the same archive
        # outside a worktree. The floor is well under the live count (278 tracked
        # `.md`) and well over any partial checkout.
        tracked = require_tracked_paths(
            REPO_ROOT, "*.md", minimum=200, what="tracked markdown files"
        )

        undeclared = []
        for rel in (p for p in tracked if p.strip()):
            if rel in self.SUBMODE_DOC_SURFACES or rel in self._DISCOVERY_EXEMPT:
                continue
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            enumerates = any(
                len({m.group(1) for m in self._INVOCATION_RE.finditer(block)}
                    & canonical) >= 2
                for block in re.split(r"\n\s*\n", text)
            ) or any(
                len({n for n in canonical
                     if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", m.group(1))}) >= 2
                for m in self._PROSE_LIST_RE.finditer(text)
            )
            if enumerates:
                undeclared.append(rel)

        assert not undeclared, (
            f"{undeclared} enumerate /scan sub-modes but are outside "
            "SUBMODE_DOC_SURFACES, so nothing checks them against cmd_scan. "
            "Add them to the tuple -- or, if the enumeration belongs to a "
            "record surface that must not be edited (Core Rule 13), say so "
            "here with the reason."
        )

    def test_no_spurious_freshness_claim_in_scan_surfaces(self) -> None:
        """`freshness` is a top-level command, not a /scan sub-mode.
        Any /scan-context surface line collocating them is drift."""
        for relpath in self.SUBMODE_DOC_SURFACES:
            text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "/scan" in line and "freshness" in line:
                    raise AssertionError(
                        f"{relpath}: line mixes /scan with freshness — "
                        f"freshness is `espalier freshness`, not a /scan "
                        f"sub-mode: {line!r}"
                    )


class TestGitHubURLConsistency:
    """TP-29: every github.com URL referencing espalier-harness must
    match the SoT in pyproject.toml [project.urls].

    Pre-fix: docs/QUICKSTART.md used `mbbyrne/espalier-harness` while
    pyproject.toml and all other docs used `Mike-Byrne-AI/espalier-harness`.
    A first-time user copy-pasting from QUICKSTART hit a 404.
    """

    PYPROJECT = REPO_ROOT / "pyproject.toml"
    SCAN_FILES = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "docs" / "QUICKSTART.md",
        REPO_ROOT / "docs" / "CHEAT-SHEET.md",
        REPO_ROOT / "docs" / "CONVENTIONS.md",
        REPO_ROOT / "docs" / "POSITIONING.md",
    )
    URL_RE = re.compile(
        r"github\.com/([\w-]+)/(espalier[-_]?harness)\b",
        re.IGNORECASE,
    )

    def _sot_org_repo(self) -> tuple[str, str]:
        text = _read(self.PYPROJECT)
        m = self.URL_RE.search(text)
        assert m, (
            "Cannot find canonical github.com URL in pyproject.toml. "
            "Expected a [project.urls] entry."
        )
        return m.group(1), m.group(2)

    def test_every_github_url_matches_sot(self):
        sot_org, sot_repo = self._sot_org_repo()
        mismatches: list[str] = []
        for path in self.SCAN_FILES:
            if not path.exists():
                continue
            for m in self.URL_RE.finditer(_read(path)):
                org, repo = m.group(1), m.group(2)
                if (org, repo.lower()) != (sot_org, sot_repo.lower()):
                    rel = path.relative_to(REPO_ROOT)
                    mismatches.append(
                        f"  {rel}: github.com/{org}/{repo} "
                        f"(expected github.com/{sot_org}/{sot_repo})"
                    )
        assert not mismatches, (
            f"GitHub URL drift detected. SoT: github.com/{sot_org}/{sot_repo}\n"
            + "\n".join(mismatches)
            + "\n\nFix each stale reference to match pyproject.toml."
        )


class TestReadmeDoctorExampleMatchesLiveOutput:
    """TP-29: README's 30-second demo doctor output must only reference
    keys that the live `espalier doctor` command actually emits.

    Pre-fix: README showed a `summary` key (`"summary": {"errors": 0,
    "warnings": 1}`) that the live doctor binary does not emit. Top-level
    keys emitted: checks, doc_drift, failures, info, mode, next_steps,
    primary_reason, repo_root, status, warnings (no `summary`).
    """

    README = REPO_ROOT / "README.md"

    def _extract_top_level_keys_from_demo(self, text: str) -> set[str]:
        """Extract every JSON key PATH from an abbreviated demo block.

        The README uses a ```text block with ``$ espalier doctor .`` as the
        first line. The block may contain abbreviated JSON with ``...``.

        ⚠ Returned outermost keys only until DEF-468. Its QUICKSTART twin had
        the identical depth-1 compare and stayed green while that sample
        claimed ``checks.presence.status`` — a key the presence dict has never
        had — because the false path was nested and only the outer layer was
        checked. README's block happens to be flat today, so recursing changes
        nothing here yet; it is fixed anyway because the two gates enforce one
        policy and leaving half the class open is how it grows back
        (STANDING_PRINCIPLES §8).
        """
        # Match the fenced block that starts with $ espalier doctor
        m = re.search(
            r"```[a-z]*\s*\n\$\s*espalier doctor[^\n]*\n([\s\S]+?)\n```",
            text,
        )
        if m is None:
            return set()
        block = m.group(1)
        # Find the first {...} JSON-like blob in the block (skip any shell output)
        json_m = re.search(r"(\{[\s\S]+\})", block)
        if json_m is None:
            return set()
        raw = json_m.group(1)
        # Normalise abbreviated JSON so it parses.
        # ⚠ This collapse used to be `\{[^{}]*\.\.\.[^{}]*\}` — ANY innermost
        # object CONTAINING an ellipsis, which deletes its real keys before
        # `key_paths` ever runs. README's house style is exactly that idiom
        # (its live block is captioned "abridged"), so the recursion added for
        # DEF-468 was inert here BY CONSTRUCTION, not merely unexercised:
        # `{"presence": {"status": "pass", ...}}` normalised to
        # `{"presence": {}}` and the false key vanished. Narrowed to an object
        # that is ONLY an ellipsis, which is the case the collapse is for.
        clean = re.sub(r'\{\s*\.\.\.\s*\}', '{}', raw)
        clean = re.sub(r'\.\.\.\s*,', '', clean)
        clean = re.sub(r',\s*\.\.\.', '', clean)
        try:
            return key_paths(json.loads(clean))
        except json.JSONDecodeError:
            return set()

    def test_the_readme_compare_reaches_nested_keys(self):
        """Pin the README half of the class-fix, which was silent.

        Two things could revert here without a single test noticing: the
        `key_paths` call dropping back to `set(parsed.keys())`, and the
        ellipsis collapse widening back to `\\{[^{}]*\\.\\.\\.[^{}]*\\}` — which
        deletes a nested object's real keys BEFORE the recursion runs, making
        the recursion inert for any sample written in README's own abbreviated
        idiom. README's live block is flat, so neither revert changes its
        result; only a synthetic fixture in the abbreviated house style can
        hold this. Measured: with the wide collapse, the DEF-468 defect shape
        transplanted into README passes.
        """
        demo = (
            "```text\n$ espalier doctor .\n"
            '{ "status": "warn", "checks": {"presence": {"status": "pass", ...}} }\n'
            "```\n"
        )
        paths = self._extract_top_level_keys_from_demo(demo)
        assert "checks.presence.status" in paths, (
            "the README extractor cannot see a nested key in the doc's own "
            "abbreviated idiom — either the compare went depth-1 again or the "
            "ellipsis collapse widened and ate the object's keys first"
        )
        # An object that is ONLY an ellipsis must still collapse, or every
        # abridged README block becomes unparseable and this gate goes vacuous.
        only = (
            "```text\n$ espalier doctor .\n"
            '{ "status": "warn", "checks": {...} }\n```\n'
        )
        assert self._extract_top_level_keys_from_demo(only) >= {"status", "checks"}

    def test_readme_doctor_keys_subset_of_live(self):
        text = _read(self.README)
        demo_keys = self._extract_top_level_keys_from_demo(text)
        assert demo_keys, (
            "Cannot locate or parse README doctor demo. If the demo was "
            "removed, delete this test."
        )
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "doctor",
             str(REPO_ROOT), "--skip-self-host"],
            capture_output=True,
            text=True, encoding="utf-8",
        )
        try:
            live_obj = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"espalier doctor output is not valid JSON: {exc}\n"
                f"stdout: {result.stdout[:500]}"
            )
        live_keys = key_paths(live_obj)
        unknown_keys = demo_keys - live_keys
        assert not unknown_keys, (
            f"README doctor demo references keys not in live output: "
            f"{unknown_keys}.\n"
            f"Live keys: {sorted(live_keys)}\n"
            f"Update README.md to match the actual doctor output shape."
        )


class TestPublicDocsEmailConsistency:
    """TP-32: the author/security email in public-facing docs must be
    consistent with pyproject.toml's authors block.

    Scope: pyproject.toml, SECURITY.md, README.md, CONTRIBUTING.md.
    NOT historical entries in CHANGELOG.md (those preserve the email
    as written at the time).
    """

    PYPROJECT = REPO_ROOT / "pyproject.toml"
    PUBLIC_DOC_SURFACE = (
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
    )
    EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    def _sot_email(self) -> str:
        """Extract canonical email from pyproject.toml authors."""
        text = _read(self.PYPROJECT)
        m = re.search(
            r'authors\s*=\s*\[\s*\{[^}]*email\s*=\s*"([^"]+)"',
            text,
        )
        assert m, "Cannot find authors email in pyproject.toml"
        return m.group(1)

    def test_emails_match_pyproject(self):
        sot = self._sot_email()
        mismatches: list[str] = []
        for path in self.PUBLIC_DOC_SURFACE:
            if not path.exists():
                continue
            text = _read(path)
            for found in self.EMAIL_RE.findall(text):
                if found in {"security@anthropic.com",
                             "noreply@example.com"}:
                    continue
                if found != sot:
                    rel = path.relative_to(REPO_ROOT)
                    mismatches.append(
                        f"  {rel}: found {found!r} (expected {sot!r})"
                    )
        assert not mismatches, (
            f"Public-doc emails diverge from pyproject SoT "
            f"({sot!r}):\n"
            + "\n".join(mismatches)
        )


class TestSpecificStaleClaims:
    """TP-29 amendment: pin each specific stale-claim regression
    surfaced by the unified-bundle cross-check.
    """

    def test_readme_no_22_checks_literal(self):
        text = _read(REPO_ROOT / "README.md")
        assert "22 checks" not in text, (
            "README still says '22 checks'. Replace with durable "
            "wording or update to the current check count."
        )

    def test_demo_md_version_not_0_4_or_0_5(self):
        path = REPO_ROOT / "docs" / "DEMO.md"
        if not path.exists():
            pytest.skip("docs/DEMO.md absent")
        text = _read(path)
        assert "0.4.0" not in text and "0.5.0" not in text, (
            "docs/DEMO.md contains a stale version literal. "
            "Use semver placeholder (e.g. 0.6.x) or current version."
        )

    def test_readme_hook_list_includes_config_guard(self):
        text = _read(REPO_ROOT / "README.md")
        if re.search(r"\b(?:Nine|9)\s+hook\s+scripts", text):
            assert "config_guard" in text, (
                "README says 'Nine hook scripts' and enumerates "
                "names, but omits config_guard.py. Either add it to "
                "the list or replace with 'see tools/cc/hooks/ for "
                "the canonical list'."
            )

    def test_demo_json_examples_parse(self):
        path = REPO_ROOT / "docs" / "DEMO.md"
        if not path.exists():
            pytest.skip("docs/DEMO.md absent")
        text = _read(path)
        blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        for block in blocks:
            try:
                obj = json.loads(block)
            except json.JSONDecodeError as exc:
                pytest.fail(
                    f"DEMO.md JSON example fails to parse: {exc}\n"
                    f"Block: {block[:200]}"
                )
            if "hookSpecificOutput" in obj:
                hso = obj["hookSpecificOutput"]
                if hso.get("hookEventName") == "PreToolUse":
                    assert "permissionDecision" in hso, (
                        "PreToolUse JSON in DEMO.md missing "
                        "permissionDecision field — likely stale."
                    )


class TestHookProtocolStaleForms:
    """TP-29 amendment: catch paraphrase variants of stale hook-protocol
    guidance in the public surface.

    The original TP-29 audit dropped this because docs/HOOKS.md was
    correct. Cross-check found docs/CHEAT-SHEET.md and hook-authoring
    skill still teaching the stale form ('exit 2 (block+JSON)').
    """

    PUBLIC_SCAN_PATHS = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs",
        REPO_ROOT / ".claude",
        REPO_ROOT / "examples",
    )

    STALE_PATTERNS = (
        (r"\bblock\s*\+\s*JSON\b",
         "use 'structured: exit 0 + JSON' instead"),
        (r"\b2\s*\(\s*block\s*\+?\s*JSON\s*\)",
         "exit 2 is stderr-only blocking, not JSON-block"),
        (r"\bexit\s+0\s+or\s+2\s+only\b",
         "exit 0 covers structured decisions; exit 2 covers simple stderr blocks"),
    )

    def test_no_stale_paraphrases_in_public_surface(self):
        offenders = []
        for root in self.PUBLIC_SCAN_PATHS:
            if not root.exists():
                continue
            files = [root] if root.is_file() else (
                list(root.rglob("*.md")) + list(root.rglob("*.py"))
            )
            for path in files:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern, hint in self.STALE_PATTERNS:
                    if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                        rel = path.relative_to(REPO_ROOT)
                        offenders.append(
                            f"  {rel}: matches {pattern!r} -- {hint}"
                        )
        assert not offenders, (
            "Stale hook-protocol paraphrases found. The structured-decision "
            "protocol is exit 0 + stdout JSON; exit 2 is stderr-only "
            "blocking with NO JSON. Don't conflate them.\n"
            + "\n".join(offenders)
        )


class TestFingerprintMatchesSchema:
    """TP-29: every key in RepoFingerprint.to_dict() must be declared
    in docs/schemas/repo_fingerprint.schema.json.

    Pre-fix: schema declared 21 fields; runtime emitted 29. Missing from
    schema: architecture, confidence, garbage_files, generated_zones,
    git_conventions, ops_directories, profiles, risky_mutable_zones.
    """

    SCHEMA = REPO_ROOT / "docs" / "schemas" / "repo_fingerprint.schema.json"

    def test_runtime_fields_declared_in_schema(self):
        from espalier.analyze import fingerprint_repo

        schema_obj = json.loads(_read(self.SCHEMA))
        declared = set(schema_obj.get("properties", {}).keys())
        fp = fingerprint_repo(REPO_ROOT)
        emitted = set(fp.to_dict().keys())
        undeclared = emitted - declared
        assert not undeclared, (
            f"RepoFingerprint emits fields not declared in schema: "
            f"{sorted(undeclared)}.\n"
            f"Update docs/schemas/repo_fingerprint.schema.json to add these "
            f"as properties (use the existing ml_surface / language_counts "
            f"entries as templates)."
        )
        # Reverse direction: a schema property the runtime no longer emits is
        # equally a doc-truth drift (a stale field documenting a shape that no
        # longer exists). to_dict() is a fixed-shape dict, so declared must
        # equal emitted exactly — same bidirectional guard the scaffolding_canon
        # schema carries (tests/test_scaffolding_canon.py::TestSchemaParity).
        stale = declared - emitted
        assert not stale, (
            f"Schema declares fields RepoFingerprint no longer emits: "
            f"{sorted(stale)}.\n"
            f"Remove them from docs/schemas/repo_fingerprint.schema.json."
        )


# ── 98-D: chmod-444 recidivism denylist ────────────────────────────────────


class TestNoChmod444Recidivism:
    """Guard against re-introducing chmod-444-on-hooks.

    The chmod-444 proposal was considered and rejected (see
    docs/sharp-edges/chmod-444-decision.md). Hook-pattern bypasses
    exist regardless (two-step subprocess, python3 heredoc — see
    bench/corpus/BC-OOS-001-two-step-subprocess.json); chmod 444 is
    itself bypassable via `chmod u+w`. The 3-tier defense
    (friction + visibility + CI guarantee) is the primary surface.

    Without this contract, the decision lives only in prose. A future
    contributor saying "I'll add chmod 444 to cmd_init for defense in
    depth" would re-open the closed door. The scan walks production
    code under espalier/ and tools/cc/ for FOUR equivalent forms of
    mode 0o444 (TP-103 W3 broadening):

    1. Literal `0o444` / `0o0444`.
    2. `int("444", 8)` octal-string parse.
    3. `stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH` (and reorderings).
    4. Computed octal OR `0o400 | 0o040 | 0o004` (and reorderings).

    All four equal 0o444; the original literal-only regex was bypassable
    by reaching for "more idiomatic" stat flags or computed forms.
    """

    _PRODUCTION_DIRS: tuple[str, ...] = ("espalier", "tools/cc")
    _EXEMPT_PATHS: tuple[str, ...] = (
        # The decision record itself documents the literal — exempt.
        "docs/sharp-edges/chmod-444-decision.md",
    )
    # Form 1: literal 0o444 / 0o0444
    _CHMOD_444_RE = re.compile(r"\b0o0?444\b")
    # Form 2: int("444", 8) / int('444', 8) — octal-string parse
    _INT_OCTAL_444_RE = re.compile(
        r"""int\s*\(\s*['"]\s*0?o?0?444\s*['"]\s*,\s*8\s*\)"""
    )
    # Form 3: stat.S_IRUSR | S_IRGRP | S_IROTH bit names.
    # All three must appear on the same logical line (BitOr expressions
    # collapse to a single statement).
    _STAT_RO_FLAGS: tuple[str, ...] = ("S_IRUSR", "S_IRGRP", "S_IROTH")
    # Form 4: computed octal OR of read bits — 0o400 + 0o040 + 0o004
    # (any case-sensitive matches with optional leading 0).
    _OCTAL_400_RE = re.compile(r"\b0o0?400\b")
    _OCTAL_040_RE = re.compile(r"\b0o0?040\b")
    _OCTAL_004_RE = re.compile(r"\b0o0?004\b")

    def _line_has_stat_read_only_or(self, line: str) -> bool:
        return all(flag in line for flag in self._STAT_RO_FLAGS)

    def _line_has_computed_octal_or(self, line: str) -> bool:
        return (
            bool(self._OCTAL_400_RE.search(line))
            and bool(self._OCTAL_040_RE.search(line))
            and bool(self._OCTAL_004_RE.search(line))
        )

    def test_no_chmod_444_in_production(self):
        offenders: list[tuple[str, int, str, str]] = []
        for prod_dir in self._PRODUCTION_DIRS:
            for path in (REPO_ROOT / prod_dir).rglob("*.py"):
                rel = path.relative_to(REPO_ROOT).as_posix()
                if rel in self._EXEMPT_PATHS:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if self._CHMOD_444_RE.search(line):
                        offenders.append((rel, lineno, line.strip(),
                                          "literal 0o444"))
                    elif self._INT_OCTAL_444_RE.search(line):
                        offenders.append((rel, lineno, line.strip(),
                                          "int('444', 8) octal parse"))
                    elif self._line_has_stat_read_only_or(line):
                        offenders.append((rel, lineno, line.strip(),
                                          "stat.S_IRUSR|S_IRGRP|S_IROTH"))
                    elif self._line_has_computed_octal_or(line):
                        offenders.append((rel, lineno, line.strip(),
                                          "computed octal OR 0o400|0o040|0o004"))
        assert not offenders, (
            "chmod 444 mode found in production code:\n"
            + "\n".join(
                f"  - {path}:{lineno} [{form}]: {text!r}"
                for path, lineno, text, form in offenders
            )
            + "\nThe chmod-444-on-hooks proposal is documented as "
            "RETIRED in docs/sharp-edges/chmod-444-decision.md. "
            "Bypass mechanisms (BC-OOS-001) mean chmod 444 adds "
            "friction without value. If a new use case requires "
            "this mode, update the sharp-edge entry first."
        )

    # ── Positive proofs: each broadened pattern catches its bypass form ──

    def test_literal_0o444_is_caught(self):
        """Original literal form — sanity check the broadening kept it."""
        assert self._CHMOD_444_RE.search("os.chmod(p, 0o444)")
        assert self._CHMOD_444_RE.search("os.chmod(p, 0o0444)")

    def test_int_octal_parse_form_is_caught(self):
        """Bypass: int('444', 8) computes 0o444 at runtime."""
        assert self._INT_OCTAL_444_RE.search('os.chmod(p, int("444", 8))')
        assert self._INT_OCTAL_444_RE.search("os.chmod(p, int('444', 8))")

    def test_stat_read_only_or_form_is_caught(self):
        """Bypass: stat.S_IRUSR | S_IRGRP | S_IROTH = 0o444."""
        assert self._line_has_stat_read_only_or(
            "os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)"
        )
        # Reordered — still catches because we require all-three-present.
        assert self._line_has_stat_read_only_or(
            "os.chmod(p, S_IROTH | S_IRUSR | S_IRGRP)"
        )

    def test_computed_octal_or_form_is_caught(self):
        """Bypass: 0o400 | 0o040 | 0o004 = 0o444 (each is one read bit)."""
        assert self._line_has_computed_octal_or(
            "os.chmod(p, 0o400 | 0o040 | 0o004)"
        )
        # Reordered.
        assert self._line_has_computed_octal_or(
            "os.chmod(p, 0o004 | 0o040 | 0o400)"
        )

    def test_unrelated_forms_are_not_caught(self):
        """Negative proof: a single S_IRUSR (without the OR'd siblings)
        or a single 0o400 (without the OR'd siblings) must NOT fire.
        These are legitimate non-444 patterns."""
        assert not self._line_has_stat_read_only_or(
            "os.chmod(p, stat.S_IRUSR)"  # 0o400, not 0o444
        )
        assert not self._line_has_computed_octal_or(
            "os.chmod(p, 0o400)"  # owner-read only, not 0o444
        )
        # 0o755 is unrelated.
        assert not self._CHMOD_444_RE.search("os.chmod(p, 0o755)")


class TestDogfoodingRosterCount:
    """R3:DOGFOOD-COUNT-UNGUARDED — the dogfooding README's adopter-facing
    roster claim ('N agents, N commands, N skills') had no drift guard, so a
    surface change could leave it stale with the suite still green."""

    def test_dogfooding_readme_roster_matches_actual(self):
        readme = REPO_ROOT / "examples" / "dogfooding" / "README.md"
        text = readme.read_text(encoding="utf-8")
        m = re.search(
            r"(\d+)\s+agents?,\s*(\d+)\s+commands?,\s*(\d+)\s+skills?", text
        )
        assert m, "dogfooding README roster line not found"
        stated = tuple(int(g) for g in m.groups())
        base = REPO_ROOT / "examples" / "dogfooding" / ".claude"
        actual = (
            len(list((base / "agents").glob("*.md"))),
            len(list((base / "commands").glob("*.md"))),
            len([p for p in (base / "skills").iterdir() if p.is_dir()]),
        )
        assert stated == actual, (
            f"dogfooding README says {stated} (agents, commands, skills) "
            f"but actual is {actual} — update examples/dogfooding/README.md"
        )


class TestShipBoundaryReviewWired:
    """The two ship-boundary commands must keep their orthogonal-context review
    step. A regeneration that silently drops the review paragraph leaves the three
    mirror legs parity-consistent (all empty) yet the review gone — nothing else
    asserts the paragraph EXISTS. These tests go RED if the review step is removed
    from either command body, or if the widened trigger surface is narrowed.

    Assertions are scoped to the step-6 review BLOCK (not the whole file) and pin
    the contiguous ordered trigger enumeration, so a bare `code-reviewer` /
    `scripts/` mention elsewhere in the body (the step-0A `code-reviewer` dispatch,
    a `scripts/sync_claude_mirrors.py` tool call) cannot stand in for the real
    wiring — the born-weak-pin trap this very change exists to prevent.
    `test_pin_fires_when_trigger_surface_is_stripped` is the committed negative twin
    proving the pin discriminates.
    """

    COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"

    @staticmethod
    def _review_block(text: str, start: str, end: str) -> str:
        """The step-6 review paragraph, sliced [start, end) — scoping the pin off
        the rest of the body so unrelated mentions can't satisfy it."""
        assert start in text, f"review-block start anchor {start!r} missing"
        i = text.index(start)
        assert end in text[i:], f"review-block end anchor {end!r} missing"
        return text[i : text.index(end, i)]

    @staticmethod
    def _assert_wired(block: str) -> None:
        assert "code-reviewer" in block, "correctness lens not dispatched in review block"
        assert "failure-mode-reviewer" in block, "adversarial lens not dispatched in review block"
        # The widened trigger surface as a contiguous ordered fragment (whitespace-
        # normalized for line wraps). A bare `scripts/` also matches
        # `scripts/sync_claude_mirrors.py`, and the rationale parenthetical carries the
        # roots WITHOUT the comma-list — so neither can stand in for the enumeration.
        assert "`bench/`, `scripts/`," in " ".join(block.split()), (
            "bench/+scripts/ not in the trigger-surface enumeration"
        )

    def test_implement_pack_dispatches_both_review_agents(self):
        block = self._review_block(
            _read(self.COMMANDS_DIR / "implement-pack.md"),
            "orthogonal-context review",
            "On a stop:",
        )
        self._assert_wired(block)

    def test_preflight_dispatches_both_review_agents(self):
        block = self._review_block(
            _read(self.COMMANDS_DIR / "preflight.md"),
            "Conditional orthogonal-context review",
            "## Report",
        )
        self._assert_wired(block)

    def test_pin_fires_when_trigger_surface_is_stripped(self):
        """Negative twin: dropping `scripts/` from the enumeration must flip the pin
        RED (an unrelated `scripts/…` mention must NOT keep it green). Proves the
        guard enforces what it advertises — the missing negative twin the born-weak
        class calls for."""
        block = self._review_block(
            _read(self.COMMANDS_DIR / "implement-pack.md"),
            "orthogonal-context review",
            "On a stop:",
        )
        stripped = block.replace("`scripts/`,", "", 1)  # remove the enumeration token only
        with pytest.raises(AssertionError):
            self._assert_wired(stripped)


class TestReleaseDecisionsRevisitLabel:
    """docs/RELEASE_DECISIONS.md:5 promises every entry locks a choice that is not
    re-litigated "without an explicit revisit trigger". The label was spelled two
    ways and omitted three times, so any label-shaped check reported absences that
    were present. One spelling now, one per entry; this holds it there."""

    def test_every_entry_carries_exactly_one_conditions_to_revisit_label(self):
        lines = (REPO_ROOT / "docs" / "RELEASE_DECISIONS.md").read_text(encoding="utf-8").splitlines()
        entries = sum(1 for line in lines if line.startswith("## 20"))
        labels = sum(1 for line in lines if line.startswith("**Conditions to revisit:**"))
        strays = [line for line in lines if line.startswith("**Revisit trigger:**")]
        assert entries and labels == entries, (entries, labels)
        assert not strays, strays


# -- The shipped packs and the tracker: no pack may say the tracker is gitignored --

_RETIRED_TRACKING_CLAIM = re.compile(
    r"`?task-packs/`?\s+is\s+gitignored"
    r"|FORWARD_LEDGER\.md`?\s*\*?\(gitignored"
    r"|This file is gitignored",
    re.I,
)


def test_no_shipped_pack_claims_the_tracker_is_gitignored():
    """A shipped pack is read by the public. The tracked half of task-packs/
    (the ledger, its probes file, the router, the active packs) stopped being
    gitignored on 2026-09-21; a pack that still says otherwise is a false claim
    on a shipping surface, and the two prose gates that would otherwise read it
    exempt packs by predicate (they are dated plans), so nothing else looks.
    Five sites across four packs were live when the failure-mode lane swept."""
    from espalier.surface_contract import is_shipped_pack

    tracked = require_tracked_paths(REPO_ROOT, "*.md", minimum=20, what="tracked markdown")
    packs = [p for p in tracked if is_shipped_pack(p)]
    if not packs:
        pytest.skip("no shipped pack is tracked on this tree")
    offenders = [
        (p, i, ln.strip()[:100])
        for p in packs
        for i, ln in enumerate((REPO_ROOT / p).read_text(encoding="utf-8").splitlines(), 1)
        if _RETIRED_TRACKING_CLAIM.search(ln)
    ]
    assert not offenders, (
        "shipped packs claiming the tracker is gitignored (date the sentence or correct it):\n  "
        + "\n  ".join(f"{p}:{i}  {t}" for p, i, t in offenders)
    )
