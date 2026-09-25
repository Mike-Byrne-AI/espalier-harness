"""Agent and command contract tests — turn pack-16 drift findings into automated assertions.

Each test corresponds to a documented drift pattern from TASK_PACK_16_AGENT_COMMAND_CLEANUP.md.
All tests run against the live .claude/ directory so they catch future drift the moment
it's introduced.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agent_files() -> list[Path]:
    return [f for f in AGENTS_DIR.glob("*.md")]


def _command_files() -> list[Path]:
    return [f for f in COMMANDS_DIR.glob("*.md")]


def _claude_md_table_rows(heading_re: str, row_re: str) -> list[str]:
    """Rows matching ``row_re`` inside the section opened by ``heading_re``.

    The section ends at the next heading of ANY depth, so a ``###``
    subsection's own table cannot inflate the parent section's row count.
    """
    content = CLAUDE_MD.read_text(encoding="utf-8")
    section = re.search(rf"{heading_re}.*?(?=\n### |\n## |\Z)", content, re.DOTALL)
    assert section, f"CLAUDE.md must contain a section matching {heading_re!r}"
    return re.findall(row_re, section.group(0), re.MULTILINE)


def _all_doc_files() -> list[Path]:
    """All .md files in .claude/ and the repo's governance doc set."""
    files = list(AGENTS_DIR.glob("*.md")) + list(COMMANDS_DIR.glob("*.md"))
    # TP-174a S2: skill bodies carry hardcoded hook-count claims ("the twelve
    # hooks") that the count-claim battery never scanned — include them so a
    # stale "thirteen hooks" drift in a skill is caught.
    files += list((REPO_ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    for name in ("README.md", "CLAUDE.md", "ESPALIER_MEMORY.md", "docs/CONVENTIONS.md",
                 "docs/SHARP_EDGES.md", "docs/CHEAT-SHEET.md", "docs/TASK_RECIPES.md"):
        p = REPO_ROOT / name
        if p.exists():
            files.append(p)
    return files


def _parse_frontmatter_tools(content: str) -> list[str]:
    """Extract declared tool tokens from the frontmatter `tools:` line."""
    match = re.search(r"^tools:\s*(.+)$", content, re.MULTILINE)
    if not match:
        return []
    raw = match.group(1)
    # Split on comma, strip whitespace
    return [t.strip() for t in raw.split(",") if t.strip()]


def _extract_bash_blocks(content: str) -> list[str]:
    """Return all lines from ```bash ... ``` blocks in a markdown file."""
    lines = []
    in_block = False
    for line in content.splitlines():
        if line.strip().startswith("```bash"):
            in_block = True
            continue
        if in_block and line.strip() == "```":
            in_block = False
            continue
        if in_block:
            lines.append(line)
    return lines


def _first_word(line: str) -> str | None:
    """Return the first command word from a bash line, or None if not a command."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("$"):
        return None
    # Skip variable assignments and control-flow keywords
    if re.match(r"^[A-Z_]+=", stripped):
        return None
    if stripped.split()[0] in ("if", "then", "else", "fi", "for", "do", "done",
                                "while", "case", "esac", "function", "return",
                                "exit", "|", "&&", "||", ";", "}", "{"):
        return None
    # Handle pipes, redirects, semicolons — take first word only
    word = re.split(r"[\s|;&]", stripped)[0]
    return word if word else None


def _bash_pattern_covers(declared_tools: list[str], command: str) -> bool:
    """Return True if the command is covered by a declared Bash(...) pattern."""
    for tool in declared_tools:
        m = re.match(r"^Bash\((.+)\)$", tool)
        if not m:
            continue
        pattern = m.group(1)
        # Convert glob-like pattern to check: "git *" means starts with "git "
        # "python3 *" means starts with "python3 "
        prefix = pattern.rstrip("*").rstrip()
        if command == prefix or command.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# 1. Agent tool declarations: detect python vs python3 mismatch
# ---------------------------------------------------------------------------

class TestAgentToolDeclarations:
    def test_python3_usage_covered_by_python3_declaration(self):
        """If an agent uses 'python3' in bash blocks, it must declare Bash(python3 *).

        Catches the specific documented bug: repo-analyst declared Bash(python *)
        but used python3 in its protocol body.
        """
        violations = []
        for path in _agent_files():
            content = path.read_text(encoding="utf-8")
            tools = _parse_frontmatter_tools(content)
            bash_lines = _extract_bash_blocks(content)

            uses_python3 = any(
                (_first_word(line) or "").startswith("python3")
                for line in bash_lines
            )
            if not uses_python3:
                continue

            # python3 usage found — check coverage
            if not _bash_pattern_covers(tools, "python3"):
                violations.append(
                    f"{path.name}: uses 'python3' in bash blocks but declares {tools!r} "
                    f"(needs Bash(python3 *))"
                )

        assert not violations, (
            "Agent files use 'python3' in bash blocks without Bash(python3 *) declared.\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# 2. File paths referenced in agent/command docs must exist on disk
# ---------------------------------------------------------------------------

class TestAgentCommandFilePaths:
    # Paths that are legitimately referenced but may not exist in this repo
    # (e.g., example paths in docs, paths in installed packages)
    _SKIP_PREFIXES = ("reports/", "/tmp/", "~", "$")

    def test_builder_and_tools_paths_exist(self):
        """Every espalier/*.py and tools/cc/*.py path mentioned in agent/command .md files
        must exist on disk. Catches hallucinated file references like espalier/health.py.
        """
        violations = []
        pattern = re.compile(r"\b(espalier/[\w./]+\.py|tools/cc/[\w./]+\.py)\b")

        for path in _agent_files() + _command_files():
            content = path.read_text(encoding="utf-8")
            for match in pattern.finditer(content):
                ref = match.group(1)
                if any(ref.startswith(p) for p in self._SKIP_PREFIXES):
                    continue
                target = REPO_ROOT / ref
                if not target.exists():
                    violations.append(
                        f"{path.name}: references '{ref}' which does not exist on disk"
                    )

        assert not violations, (
            "Agent/command files reference files that don't exist.\n"
            + "\n".join(sorted(set(violations)))
        )


# ---------------------------------------------------------------------------
# 3. Hook count claims must match actual hook file count
# ---------------------------------------------------------------------------

# TP-174a S2: the hand-rolled word vocabulary stopped at "ten" while the live
# count is 12, so the spelled-out "twelve hooks" claims the docs and skills
# actually carry were dark, and a future "thirteen hooks" drift would survive
# green. Extend the vocabulary through "fifteen" (the canon parse_count_token
# range) and translate via the canon helper, but keep the original TIGHT
# anchoring — the count token must be immediately followed by "hook" (at most a
# "standard" adjective), so subset prose like "two PreToolUse hooks" or
# "chmod 444 ... hook" stays excluded. (The canon make_count_claim_regex was
# measured to over-fire on this corpus via its permissive single-adjective
# slot — not used here.) Words start at six (as the original did) so low-number
# subset prose ("one hook", "two hooks") never collides; digit forms cover any
# count.
_HOOK_WORD_ALT = (
    r"six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
)
# "12 hooks", "12 hook scripts" (digit, no intervening word).
_HOOK_NUMERIC_RE = re.compile(r"\b(\d+)\s+hook(?:s|\s+script)", re.IGNORECASE)
# "twelve hooks", "twelve standard hooks".
_HOOK_WORD_RE = re.compile(
    rf"\b({_HOOK_WORD_ALT})\s+(?:standard\s+)?hook(?:s|\s+script)?",
    re.IGNORECASE,
)
# "all 12 ... hooks", "all twelve standard hooks". Anchor 'hook' immediately
# after the (single) intervening word; the prior `.*hook` form matched across
# entire markdown table rows.
_HOOK_ALL_RE = re.compile(
    rf"\ball\s+(\d+|{_HOOK_WORD_ALT})\s+(?:\w+\s+)?hook(?:s|\s+script)?\b",
    re.IGNORECASE,
)


def _hook_count_violations(content: str, actual_count: int, source: str) -> list[str]:
    """Return stale-hook-count violations for one document's text."""
    from espalier.surface_contract import parse_count_token

    out: list[str] = []
    for pat in (_HOOK_NUMERIC_RE, _HOOK_WORD_RE, _HOOK_ALL_RE):
        for m in pat.finditer(content):
            n = parse_count_token(m.group(1).lower())
            if n is not None and n != actual_count:
                out.append(
                    f"{source}: claims '{m.group(0)}' but {actual_count} hooks exist"
                )
    return out


class TestHookCountConsistentAcrossDocs:
    def test_hook_count_claims_match_reality(self):
        """All .md files that make numeric hook count claims must match
        the actual number of .py files in tools/cc/hooks/.
        """
        actual_count = len([
            f for f in HOOKS_DIR.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ])

        violations = []
        for path in _all_doc_files():
            content = path.read_text(encoding="utf-8")
            violations.extend(_hook_count_violations(content, actual_count, path.name))

        assert not violations, (
            f"Stale hook count claims found (actual: {actual_count}).\n"
            + "\n".join(violations)
        )

    def test_skill_bodies_in_count_claim_corpus(self):
        """TP-174a S2 earn-the-red: skill SKILL.md bodies carry hook-count
        claims ('the twelve hooks') that the pre-fix corpus never scanned.
        Fails against pre-fix _all_doc_files() (skills absent)."""
        skill_docs = [
            p for p in _all_doc_files()
            if p.name == "SKILL.md" and p.parent.parent.name == "skills"
        ]
        assert skill_docs, (
            "skills/*/SKILL.md must be in the count-claim corpus so a stale "
            "'thirteen hooks' drift in a skill body is caught"
        )

    def test_spelled_drift_above_ten_is_caught(self):
        """TP-174a S2 earn-the-red: a spelled-out count above 'ten' must be
        detectable. The pre-fix vocabulary capped at 'ten', so 'twelve hooks'
        (correct today) and a future 'thirteen hooks' drift both went dark."""
        # Live count is 12: the correct spelled claim must NOT violate...
        assert not _hook_count_violations("the twelve hooks short-circuit", 12, "x")
        # ...but a 'thirteen hooks' drift against a live 12 MUST violate
        # (pre-fix word_map stopped at ten → returned no match → no violation).
        assert _hook_count_violations("all thirteen standard hooks fire", 12, "x")
        # Subset prose stays excluded (no false positive).
        assert not _hook_count_violations("two PreToolUse hooks run", 12, "x")


# ---------------------------------------------------------------------------
# 4. CLAUDE.md command table rows must match .claude/commands/ file count
# ---------------------------------------------------------------------------

class TestCommandTableMatchesFiles:
    def test_claude_md_command_table_matches_command_files(self):
        """The "Slash Commands" table in CLAUDE.md must have the same count as
        files in .claude/commands/. Skills live in a separate table and a
        separate disk location; checked by `test_claude_md_skills_table_matches_skill_dirs`.
        """
        command_file_count = len(list(COMMANDS_DIR.glob("*.md")))

        content = CLAUDE_MD.read_text(encoding="utf-8")

        # Scope to the Slash Commands section so the Skills table doesn't inflate the count.
        section_match = re.search(
            r"## Slash Commands.*?(?=\n## |\Z)",
            content,
            re.DOTALL,
        )
        assert section_match, "CLAUDE.md must contain a `## Slash Commands` section"
        table_rows = re.findall(r"^\|\s+`/\w", section_match.group(0), re.MULTILINE)
        table_count = len(table_rows)

        assert table_count == command_file_count, (
            f"CLAUDE.md Slash Commands table has {table_count} rows but "
            f".claude/commands/ has {command_file_count} files. "
            "Update CLAUDE.md or add/remove the command file."
        )

    def test_claude_md_skills_table_matches_skill_dirs(self):
        """The "Skills" table in CLAUDE.md must have the same count as skill
        directories under .claude/skills/."""
        skills_dir = REPO_ROOT / ".claude" / "skills"
        if not skills_dir.exists():
            return  # No skills layer yet — nothing to check
        skill_dir_count = sum(
            1 for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
        )

        content = CLAUDE_MD.read_text(encoding="utf-8")
        section_match = re.search(
            r"## Skills.*?(?=\n## |\Z)",
            content,
            re.DOTALL,
        )
        assert section_match, "CLAUDE.md must contain a `## Skills` section"
        # TP-29: skills no longer use the /slash prefix in the table.
        table_rows = re.findall(r"^\|\s+`[\w/]", section_match.group(0), re.MULTILINE)
        table_count = len(table_rows)

        assert table_count == skill_dir_count, (
            f"CLAUDE.md Skills table has {table_count} rows but "
            f".claude/skills/ has {skill_dir_count} skills. "
            "Update CLAUDE.md or add/remove the skill directory."
        )

    # -- TP-398 CD-03: the two tables that had no row-count pin at all. ------
    # Adding a 13th hook or an 8th agent used to leave CLAUDE.md a row short
    # with nothing firing. Both counts are DERIVED from the live population
    # (never a literal), so the pin cannot go stale the way the table did.

    def test_claude_md_hooks_table_matches_canonical_wiring(self):
        """The Hooks table row count must equal the canonical hook population.

        Scoped to the FIRST table under ``## Hooks``: the ``### Maintenance
        mode`` subsection carries a second table of four hook rows, so a
        section-wide match reads 16 where the population is 12.
        """
        from espalier.harness_config import CANONICAL_HOOK_WIRING

        rows = _claude_md_table_rows(
            r"## Hooks \(Mechanical Enforcement\)", r"^\|\s+`[a-z_]+\.py`\s+\|"
        )
        assert len(rows) == len(CANONICAL_HOOK_WIRING), (
            f"CLAUDE.md Hooks table has {len(rows)} rows but "
            f"CANONICAL_HOOK_WIRING has {len(CANONICAL_HOOK_WIRING)} hooks. "
            "Update the table or the wiring."
        )

    def test_claude_md_agents_table_matches_agent_files(self):
        """The Agents table row count must equal ``.claude/agents/*.md``."""
        rows = _claude_md_table_rows(r"## Agents", r"^\|\s+`[\w-]+`\s+\|")
        agent_count = len(_agent_files())
        assert len(rows) == agent_count, (
            f"CLAUDE.md Agents table has {len(rows)} rows but "
            f".claude/agents/ has {agent_count} files. "
            "Update the table or add/remove the agent file."
        )

    def test_cheat_sheet_lists_every_slash_command(self):
        """MEMBERSHIP, not a count: every command file must appear by name.

        A count pin would have stayed green on the defect this closes --
        ``docs/CHEAT-SHEET.md`` listed 15 of 17 commands, and a bare count is
        satisfiable by two unrelated rows. ``CLAUDE.md``'s command table is
        already count-pinned above; nothing derived the cheat sheet's listing
        from the same population, so a month-old omission went unnoticed by
        the nine test files that reference the doc.

        Scoped to ``commands/`` only: skills live in a separate table and a
        separate disk location, mirroring this class's own docstring caveat.
        """
        cheat_sheet = REPO_ROOT / "docs" / "CHEAT-SHEET.md"
        content = cheat_sheet.read_text(encoding="utf-8")
        missing = [
            f.stem
            for f in sorted(_command_files())
            # Boundary-aware: a bare substring test would let `/scan-deep`
            # satisfy `/scan`, greening a genuinely absent command.
            if not re.search(rf"/{re.escape(f.stem)}(?![\w-])", content)
        ]
        assert not missing, (
            f"docs/CHEAT-SHEET.md is missing {len(missing)} slash command(s): "
            f"{', '.join(missing)}. Add a row per command, or remove the "
            "command file."
        )

    def test_hooks_table_scope_excludes_the_maintenance_mode_table(self):
        """Discriminator: the scoping, not just the count, is what's pinned.

        A section-wide match would swallow ``### Maintenance mode``'s four
        rows and green only by coincidence if the two tables ever summed to
        the population. Assert the narrow scope really is narrower.
        """
        narrow = _claude_md_table_rows(
            r"## Hooks \(Mechanical Enforcement\)", r"^\|\s+`[a-z_]+\.py`\s+\|"
        )
        content = CLAUDE_MD.read_text(encoding="utf-8")
        section_wide = re.findall(
            r"^\|\s+`[a-z_]+\.py`\s+\|",
            re.search(r"## Hooks \(Mechanical Enforcement\).*?(?=\n## |\Z)",
                      content, re.DOTALL).group(0),
            re.MULTILINE,
        )
        assert len(section_wide) > len(narrow), (
            "The maintenance-mode table no longer contributes extra hook rows; "
            "if it was removed, simplify _claude_md_table_rows' stop condition "
            "rather than leaving a scope guard that can no longer fire."
        )


# ---------------------------------------------------------------------------
# 5. Duplicate command heuristic — same primary bash command, <5 unique lines
# ---------------------------------------------------------------------------

class TestNoDuplicateCommandBehavior:
    def test_no_duplicate_command_files(self):
        """Detect short command files (<15 total lines) that share an identical
        bash block and have fewer than 3 unique non-empty lines of their own.

        This catches stub sub-mode commands like scan-prints / scan-exceptions
        that ran exactly the same `espalier scan .` with no unique behavior,
        while avoiding false positives on commands that merely share a common
        binary (git, python, pytest) across substantively different protocols.
        """
        # Only consider short files — long files are substantively different
        SHORT_THRESHOLD = 15
        UNIQUE_THRESHOLD = 3

        short_commands: dict[str, tuple[set[str], int]] = {}
        for path in _command_files():
            content = path.read_text(encoding="utf-8")
            total_lines = len([l for l in content.splitlines() if l.strip()])
            if total_lines > SHORT_THRESHOLD:
                continue
            bash_lines = frozenset(
                l.strip() for l in _extract_bash_blocks(content) if l.strip()
            )
            if bash_lines:
                short_commands[path.stem] = (set(bash_lines), total_lines)

        violations = []
        stems = list(short_commands.keys())
        for i in range(len(stems)):
            for j in range(i + 1, len(stems)):
                a, b = stems[i], stems[j]
                bash_a, _ = short_commands[a]
                bash_b, _ = short_commands[b]
                # Check if one's bash block is a subset of the other's
                shared = bash_a & bash_b
                if not shared:
                    continue
                unique_to_a = bash_a - bash_b
                unique_to_b = bash_b - bash_a
                if len(unique_to_a) < UNIQUE_THRESHOLD and len(unique_to_b) < UNIQUE_THRESHOLD:
                    violations.append(
                        f"'{a}' and '{b}' are short files sharing bash content "
                        f"({len(shared)} shared lines, {len(unique_to_a)}/{len(unique_to_b)} unique) "
                        f"— consider merging"
                    )

        assert not violations, (
            "Potential duplicate command files detected:\n" + "\n".join(violations)
        )
