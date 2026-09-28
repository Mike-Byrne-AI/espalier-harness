"""Anti-regression: slash-command surface after context-load/recover merge.

Asserts the exact post-merge surface state:
- /recover is gone from the public command set
- /context-load is present and calls session_resume.py
- /status calls session_resume.py --mode status
- tools/cc/session_resume.py is in the pack manifest
- Discovered command count equals ``tests/_surface_expected.py::EXPECTED_COMMAND_COUNT``
  (the single source for the number; this docstring deliberately does not restate it)
"""
from __future__ import annotations

from pathlib import Path


from espalier import surface_contract

ROOT = Path(__file__).resolve().parent.parent


class TestRecoverCommandAbsent:
    def test_recover_md_not_on_disk(self):
        assert not (ROOT / ".claude" / "commands" / "recover.md").exists(), (
            ".claude/commands/recover.md must not exist after the context-load/recover merge"
        )

    def test_recover_absent_from_commands_md(self):
        text = (ROOT / "cc" / "COMMANDS.md").read_text(encoding="utf-8")
        assert "/recover" not in text, "cc/COMMANDS.md must not list /recover"

    def test_recover_absent_from_live_surface(self):
        text = (ROOT / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        assert "/recover" not in text, "cc/LIVE_SURFACE.md must not list /recover"

    def test_recover_absent_from_pack_manifest(self):
        text = (ROOT / "cc" / "PACK_MANIFEST.txt").read_text(encoding="utf-8")
        assert ".claude/commands/recover.md" not in text, (
            ".claude/commands/recover.md must not appear in cc/PACK_MANIFEST.txt"
        )


class TestContextLoadPresent:
    def test_context_load_md_exists(self):
        assert (ROOT / ".claude" / "commands" / "context-load.md").exists()

    def test_context_load_calls_session_resume_normal(self):
        text = (ROOT / ".claude" / "commands" / "context-load.md").read_text(encoding="utf-8")
        assert "session_resume.py --mode normal" in text, (
            "context-load.md must call session_resume.py --mode normal"
        )


class TestStatusCommandUsesEngine:
    def test_status_calls_session_resume_status(self):
        text = (ROOT / ".claude" / "commands" / "status.md").read_text(encoding="utf-8")
        assert "session_resume.py --mode status" in text, (
            "status.md must call session_resume.py --mode status"
        )

    def test_status_does_not_start_session(self):
        text = (ROOT / ".claude" / "commands" / "status.md").read_text(encoding="utf-8")
        assert "cognitive_blueprint.py start" not in text, (
            "status.md must never start a new blueprint session"
        )


class TestShipCommandBody:
    """The /ship body's load-bearing lines, pinned so an edit cannot quietly
    reopen a stall or a loss the command exists to close: step 1 moves commits
    only when HEAD is the default branch (run from a third branch, the same
    chain orphaned an unpushed default-branch commit -- reproduced 2026-09-28);
    the PR body's prose goes through a QUOTED heredoc (unquoted, a backtick in
    it ran as a command -- reproduced the same day); the marker check reads the
    guard from the repository root and prints a positive verdict; the marker is
    bound after the last push and re-bound on a new head; every later block
    names its pull request explicitly; the protected set is asked of the
    guard, never re-listed; one named tag, checked against the tree's version
    before anything leaves the machine, never a bulk push; the tag waits for
    the merge and lands on the merge commit; a lane the base branch's up-to-date
    rule holds is caught up on the server, pulled, and proven to sit at the pull
    request's head before the re-bind, never rebased (the first held pull request
    sat silently, 2026-09-28); every block names its pull request from a checked
    branch name, because an empty `--head` lists every pull request; and no stop
    message carries an apostrophe, which bash 3.2 cannot parse inside `${:?}`."""

    _BODY = ROOT / ".claude" / "commands" / "ship.md"

    def _text(self) -> str:
        return self._BODY.read_text(encoding="utf-8")

    def _blocks(self) -> list[str]:
        return [block.split("```", 1)[0] for block in self._text().split("```bash")[1:]]

    def test_ship_is_a_core_flow_command_between_commit_and_handoff(self):
        from espalier.render_surface import CORE_FLOW_COMMANDS
        assert "/ship" in CORE_FLOW_COMMANDS
        assert (CORE_FLOW_COMMANDS.index("/commit")
                < CORE_FLOW_COMMANDS.index("/ship")
                < CORE_FLOW_COMMANDS.index("/handoff"))

    def test_step_one_moves_commits_only_from_the_default_branch(self):
        moves = [b for b in self._blocks() if "git branch -f" in b]
        assert len(moves) == 1, "one block moves the default branch"
        block = moves[0]
        guard = '[ "$(git branch --show-current)" = "$BASE" ] ||'
        assert guard in block
        assert block.index(guard) < block.index('git branch "$LANE"') < block.index("git branch -f")

    def test_the_pr_body_prose_cannot_run_as_a_command(self):
        text = self._text()
        assert "<<EOF" not in text, "an unquoted heredoc executes backticks in the prose"
        assert "cat <<'EOF'" in text and "--body-file -" in text
        assert "--title '<subject, at most 72 characters>'" in text

    def test_marker_is_bound_to_the_pushed_head_after_the_push(self):
        text = self._text()
        bind = "HARNESS-UPDATE-APPROVED@$(git rev-parse --short=7 HEAD)"
        assert text.count(bind) == 2, "the first binding and the step-5 re-binding"
        assert text.index("git push -u origin HEAD") < text.index(bind)
        # The re-binding strips the old fragment before appending the new one.
        assert "sed -E 's/ *HARNESS-UPDATE-APPROVED@[0-9a-fA-F]+//'" in text

    def test_marker_check_reads_the_guard_from_the_root_and_says_what_it_found(self):
        text = self._text()
        checks = [b for b in self._blocks() if "ci_guard.is_protected(" in b]
        assert len(checks) == 1
        block = checks[0]
        assert "git rev-parse --show-toplevel" in block
        for verdict in ("MARKER REQUIRED", "MARKER NOT REQUIRED", "CHECK DID NOT RUN"):
            assert verdict in block, verdict
        assert "raise SystemExit(1)" in block, "no paths at all is a failed check, not a clean one"
        for listed in ("tools/cc/hooks/", ".github/workflows/", "PROTECTED_PREFIXES"):
            assert listed not in text, f"{listed!r} re-lists the guard's roster in prose"

    def test_every_gh_pr_verb_names_its_pull_request(self):
        for line in self._text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("gh pr edit", "gh pr view", "gh pr merge", "gh pr update-branch")):
                assert '"$PR"' in stripped, line
            # `gh pr view` is also nested inside a title substitution.
            if "$(gh pr view" in stripped:
                assert '$(gh pr view "$PR"' in stripped, line

    def test_behind_shape_catches_up_then_pulls_before_the_rebind(self):
        """Under the base branch's up-to-date rule an armed auto-merge on a
        behind-base pull request sits silently (the first one the rule held,
        2026-09-28): the remedy is a server-side catch-up, a wait for the head
        to move (the reply lands before the merge does), a pull that stops when
        it cannot fast-forward, a check that HEAD is the pull request's head,
        and only then the re-bind -- never a rebase of a pushed lane."""
        text = self._text()
        assert "`BEHIND`" in text, "the shape is named as GitHub spells it"
        catchups = [b for b in self._blocks() if "gh pr update-branch" in b]
        assert len(catchups) == 1, "one block catches the lane up"
        block = catchups[0]
        update = 'gh pr update-branch "$PR" || exit 1'
        pull = 'git pull --ff-only origin "$BR" || exit 1'
        head_check = '[ "$(git rev-parse HEAD)" = "$(gh pr view "$PR" --json headRefOid -q .headRefOid)" ] ||'
        assert update in block and pull in block and head_check in block
        assert block.index(update) < block.index("sleep 2") < block.index(pull) < block.index(head_check), (
            "catch up, wait for the head, pull, then prove HEAD is the pull request's head")
        # The hand-off to the re-bind follows the block, and adds no third copy of it.
        handoff = "the re-bind block at the top of this step"
        assert text.count(handoff) == 1 and text.index(update) < text.index(handoff)
        assert "--rebase" not in text and "git rebase" not in text, "a pushed lane is never rebased"

    def test_every_pull_request_is_named_from_a_checked_branch(self):
        """`gh pr list --head ""` lists every pull request (driven 2026-09-28: it
        returned an unrelated one), so on a detached HEAD a block that fed
        `git branch --show-current` straight into `--head` would edit, arm or
        catch up the wrong pull request; the name is checked before it is used."""
        derivations = [b for b in self._blocks() if "PR=$(gh pr list" in b]
        assert len(derivations) >= 5, "every pull-request verb derives its number"
        for block in derivations:
            assert 'PR=$(gh pr list --head "$BR"' in block, block
            assert ': "${BR:?' in block and block.index(': "${BR:?') < block.index("PR=$("), block
        assert '--head "$(git branch --show-current)"' not in self._text()

    def test_no_stop_message_carries_an_apostrophe(self):
        """/bin/bash 3.2 (macOS) fails to parse an apostrophe inside a
        `${VAR:?message}` inside double quotes (`unexpected EOF while looking
        for matching`); zsh accepts the same text, so the tool shell never saw
        it. Found 2026-09-28 by parsing every block as written under both
        shells: the release tail had shipped that way. A plain double-quoted
        echo may keep its apostrophes; the stop messages may not."""
        import re
        for body in self._blocks():
            for message in re.findall(r"\$\{[A-Z_]+:\?([^}]*)\}", body):
                assert "'" not in message, message

    def test_every_tag_push_names_one_tag_and_checks_it_first(self):
        text = self._text()
        pushes = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("git push")]
        assert pushes, "no push lines found"
        for line in pushes:
            assert "--tags" not in line and "--follow-tags" not in line, line
        assert any(line.startswith('git push origin "$TAG"') for line in pushes)
        release = [b for b in self._blocks() if 'git tag -a "$TAG"' in b]
        assert len(release) == 1
        block = release[0]
        assert block.index('[ "$TAG" = "v$VERSION" ] ||') < block.index('git tag -a "$TAG"')
        assert "MERGED <sha>" in text
        assert block.index('MERGE=$(gh pr view "$PR" --json mergeCommit') < block.index('git tag -a "$TAG"')
        assert 'git tag -a "$TAG" -m "$TAG: <one line>" "$MERGE"' in block
        assert "gh run watch \"$(gh run list" in block, "a bare `gh run watch` prompts and hangs off a terminal"

    def test_body_shows_python_not_python3_and_stands_alone_per_block(self):
        text = self._text()
        assert "python3" not in text
        assert "git status --short -uno" in text, "an untracked scratch file must not block a push"
        # Every block that expands a variable defines it, and every command
        # substitution that can come back empty is checked with `:?`: a tool
        # shell forgets variables between calls, `set -u` does not catch an
        # empty one, and an unbound one beside a glob has wiped a directory.
        for body in self._blocks():
            for var, define in (("$BASE", "BASE=$("), ("$LANE", 'LANE="'), ("$MERGE", "MERGE=$("),
                                ("$PR", "PR=$("), ("$TAG", "TAG="), ("$ROOT", "ROOT=$("),
                                ("$VERSION", "VERSION=$("), ("$BR", "BR=$("), ("$WAS", "WAS=$(")):
                if var in body:
                    assert define in body and "set -u" in body, (var, body)
            for var in ("BASE", "PR", "ROOT", "MERGE", "VERSION", "BR", "WAS"):
                if f"{var}=$(" in body:
                    assert f': "${{{var}:?' in body, (var, body)


class TestSessionResumeInManifest:
    def test_session_resume_in_pack_manifest(self):
        text = (ROOT / "cc" / "PACK_MANIFEST.txt").read_text(encoding="utf-8")
        assert "tools/cc/session_resume.py" in text, (
            "tools/cc/session_resume.py must appear in cc/PACK_MANIFEST.txt"
        )


class TestDiscoveredCommandCount:
    def test_discovered_count_matches_the_expected_constant(self):
        surface = surface_contract.discover_self_host_surface(ROOT)
        from tests._surface_expected import EXPECTED_COMMAND_COUNT
        commands = surface["commands"]
        assert len(commands) == EXPECTED_COMMAND_COUNT, (
            f"Expected {EXPECTED_COMMAND_COUNT} commands, got {len(commands)}. "
            "Update tests/_surface_expected.py if intentionally adding or removing a command."
        )

    def test_recover_not_in_discovered_commands(self):
        surface = surface_contract.discover_self_host_surface(ROOT)
        for cmd in surface["commands"]:
            assert "recover" not in cmd, (
                f"Unexpected recover command found in discovered surface: {cmd}"
            )


class TestLiveSurfaceRendering:
    """Anti-regression on the public artifact in cc/LIVE_SURFACE.md.

    TP-RELEASE-01: the renderer used to leak raw YAML block markers (`>`,
    `|`) into the agent roster when frontmatter used folded/literal scalars.
    This test pins the rendered output, not just the renderer.
    """

    def test_live_surface_does_not_render_yaml_block_markers(self):
        text = (ROOT / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        for forbidden in ("— >", "— |", "description: >", "description: |"):
            assert forbidden not in text, (
                f"cc/LIVE_SURFACE.md contains generated-doc artifact "
                f"{forbidden!r}. Re-run the renderer "
                "(`python -c 'from espalier.render_surface import write_required_surface; "
                "from pathlib import Path; write_required_surface(Path(\".\"))'`)."
            )

    def test_live_surface_renders_real_agent_descriptions(self):
        text = (ROOT / "cc" / "LIVE_SURFACE.md").read_text(encoding="utf-8")
        assert "architecture-analyst" in text
        # TP-184 B13: the prior sentinel "Understands how Espalier-Harness" was
        # the PRE-genericization (TP-87/129) wording; the committed surface had
        # gone stale against the agent file and this test passed on the stale
        # bytes. Assert a genericization-stable fragment of the REAL description
        # instead (TestCommittedSurfaceMatchesRenderer now byte-pins the whole
        # file to the renderer, so this only needs to prove a non-stub render).
        assert "reviews changes for architectural consistency" in text


class TestCommandTablePurposeRendering:
    """Anti-regression on the Slash Commands table in the generated adopter
    CLAUDE.md (auto-loaded into every session).

    `cli._build_asset_tables` used to take the first non-empty *physical
    line* of each command .md as its Purpose. For a command that opens with
    YAML frontmatter (audit-accuracy.md) that line is the `---` delimiter, so
    the Purpose cell rendered as a literal `---`; for prose commands whose
    first sentence wraps across lines it truncated mid-sentence. The sibling
    renderer `render_surface.render_commands_doc` already read frontmatter +
    body correctly; this pins the CLAUDE.md renderer to the same contract.
    """

    def _command_rows(self) -> list[tuple[str, str]]:
        import re

        from espalier.cli import _build_asset_tables

        rows: list[tuple[str, str]] = []
        for line in _build_asset_tables().splitlines():
            m = re.match(r"\| `/([^`]+)` \| (.*) \|$", line)
            if m:
                rows.append((m.group(1), m.group(2).strip()))
        return rows

    def test_no_purpose_leaks_frontmatter_delimiter(self):
        rows = self._command_rows()
        assert rows, "no command rows rendered — _build_asset_tables changed shape"
        bad = [name for name, purpose in rows if purpose == "---" or purpose.startswith("---")]
        assert not bad, (
            f"command Purpose cells leaked a frontmatter `---` delimiter: {bad}. "
            "The command branch of _build_asset_tables must read the frontmatter "
            "`description:` (like the skill/agent branches), not the first raw line."
        )

    def test_no_purpose_is_empty(self):
        rows = self._command_rows()
        empty = [name for name, purpose in rows if not purpose]
        assert not empty, f"command Purpose cells rendered empty: {empty}"

    def test_frontmatter_command_renders_its_description(self):
        purposes = dict(self._command_rows())
        assert "audit-accuracy" in purposes, "audit-accuracy command row missing"
        # audit-accuracy.md is the one command that uses YAML frontmatter; its
        # Purpose must be the description, not the `---` delimiter.
        assert purposes["audit-accuracy"].startswith("Run the accuracy audit"), (
            f"audit-accuracy Purpose is {purposes['audit-accuracy']!r}, expected its "
            "frontmatter description."
        )


class TestTableCellPipeEscaping:
    """A rendered command/skill/agent cell whose text contains a literal ``|``
    must not spawn a phantom table column. ``_build_asset_tables`` escapes ``|``
    (and ``\\``) in every free-text cell — otherwise a pipe in a description
    silently shifts every column after it in the auto-loaded CLAUDE.md tables.
    """

    @staticmethod
    def _count_unescaped_pipes(line: str) -> int:
        """Count ``|`` not preceded by a backslash — the real column delimiters
        of a rendered markdown row (an escaped ``\\|`` is cell content)."""
        n = 0
        i = 0
        while i < len(line):
            if line[i] == "\\":
                i += 2  # skip the escaped character
                continue
            if line[i] == "|":
                n += 1
            i += 1
        return n

    @staticmethod
    def _render_with_fake_command(tmp_path, monkeypatch, purpose_text: str) -> str:
        from espalier import cli

        cmds = tmp_path / "commands"
        cmds.mkdir()
        # Prose-first command (no frontmatter) so the raw purpose text flows
        # straight into the cell without the YAML parser touching the pipe.
        (cmds / "zzpipe.md").write_text(purpose_text + "\n", encoding="utf-8")
        monkeypatch.setattr(cli, "claude_assets_root", lambda: tmp_path)
        return cli._build_asset_tables()

    def test_pipe_in_purpose_does_not_add_a_column(self, tmp_path, monkeypatch):
        rendered = self._render_with_fake_command(
            tmp_path, monkeypatch, "A purpose with a | pipe inside it"
        )
        row = next(
            (ln for ln in rendered.splitlines() if ln.startswith("| `/zzpipe`")),
            None,
        )
        assert row is not None, "fake command row was not rendered"
        # A well-formed 2-column row has exactly three delimiters: | a | b |
        pipes = self._count_unescaped_pipes(row)
        assert pipes == 3, (
            f"a literal `|` in the cell leaked a phantom column: {row!r} has "
            f"{pipes} unescaped delimiters (expected 3 for a 2-column row)"
        )

    def test_md_cell_escapes_pipe_and_backslash(self):
        from espalier.cli import _md_cell

        # Backslash is escaped first so an already-escaped pipe stays one cell.
        assert _md_cell("a | b") == "a \\| b"
        assert _md_cell("a \\ b") == "a \\\\ b"
        assert _md_cell("no specials") == "no specials"


class TestFrontmatterParserParity:
    """The two frontmatter parsers over the SAME asset roster must agree on
    every valid ``description:`` scalar shape.

    ``cli._parse_yaml_frontmatter`` renders the CLAUDE.md tables;
    ``render_surface._read_frontmatter_description`` renders
    ``cc/LIVE_SURFACE.md`` + ``cc/COMMANDS.md``. Before this lock they DISAGREED
    on the value-interpretation rules: cli kept the raw block-scalar marker
    (``>-``, ``>+``, ``|-``, ``|+``, ``|2``) and the surrounding quotes on a
    quoted value, while render_surface folded the block body and unquoted the
    scalar. Latent today — every live asset uses plain ``>`` or unquoted text —
    but a single idiomatic chomp/indent indicator or a quoted description would
    silently leak a literal ``>-`` / ``"..."`` into the CLAUDE.md tables. This
    is the sister-site divergence class the harness treats as first-class, and
    it lived inside ①'s own fix helper. The block-scalar/quoted rows below are
    the earn-the-red: they diverge on pre-fix cli.py, agree after cli shares
    render_surface's canonical value-rule helpers.
    """

    # Block-scalar headers: the value is on an indented continuation line.
    _BLOCK_MARKERS = (">", "|", ">-", ">+", "|-", "|+", "|2")
    # Inline scalars: (raw `description:` text, expected rendered value).
    _INLINE_SHAPES = (
        ('"hello world"', "hello world"),   # double-quoted
        ("'hello world'", "hello world"),   # single-quoted
        ("hello world", "hello world"),     # plain, unquoted
    )

    def _parity(self, tmp_path, frontmatter: str, label: str):
        from espalier.cli import _parse_yaml_frontmatter
        from espalier.render_surface import _read_frontmatter_description

        md = tmp_path / f"{label}.md"
        md.write_text(frontmatter, encoding="utf-8")
        cli_val = _parse_yaml_frontmatter(frontmatter).get("description", "")
        rs_val = _read_frontmatter_description(md)
        return cli_val, rs_val

    def test_block_scalar_shapes_agree(self, tmp_path):
        for i, marker in enumerate(self._BLOCK_MARKERS):
            fm = f"---\ndescription: {marker}\n  hello world\n---\n"
            cli_val, rs_val = self._parity(tmp_path, fm, f"block_{i}")
            assert cli_val == rs_val, (
                f"parser divergence on block-scalar {marker!r}: "
                f"cli={cli_val!r} render_surface={rs_val!r}"
            )
            assert rs_val == "hello world"

    # The VALUE-rule half of this divergence closed when cli adopted
    # render_surface's `_is_block_scalar_header` / `_unquote_frontmatter_value`.
    # The BODY-FOLD half did not, and it is the half that loses text: cli
    # terminated a block scalar at the first blank line (render_surface treats a
    # blank as a paragraph break and keeps reading), and cli preserved internal
    # whitespace runs the renderer collapses. Neither parser is YAML-correct —
    # real YAML turns a blank line into a literal newline, so PyYAML agrees with
    # neither — so these rows pin AGREEMENT between the two, not conformance.
    _BODY_SHAPES = (
        # (body lines after `description: >`, expected folded value)
        (["  First paragraph.", "", "  Second paragraph."],
         "First paragraph. Second paragraph."),
        (["  hello    world"], "hello world"),
    )

    def test_block_scalar_bodies_agree(self, tmp_path):
        for i, (body, expected) in enumerate(self._BODY_SHAPES):
            fm = "---\ndescription: >\n" + "\n".join(body) + "\n---\n"
            cli_val, rs_val = self._parity(tmp_path, fm, f"body_{i}")
            assert cli_val == rs_val, (
                f"body-fold divergence on {body!r}: "
                f"cli={cli_val!r} render_surface={rs_val!r}"
            )
            assert rs_val == expected

    def test_inline_scalar_shapes_agree(self, tmp_path):
        for i, (raw, expected) in enumerate(self._INLINE_SHAPES):
            fm = f"---\ndescription: {raw}\n---\n"
            cli_val, rs_val = self._parity(tmp_path, fm, f"inline_{i}")
            assert cli_val == rs_val, (
                f"parser divergence on inline {raw!r}: "
                f"cli={cli_val!r} render_surface={rs_val!r}"
            )
            assert rs_val == expected


class TestCoreFlowSourcing:
    """TP-241: _commands_footer derives the banner command line from
    cc/COMMANDS.md's rendered ``## Core flow`` section (single source of truth),
    not a hardcoded tuple that can drift on the add-axis.
    """

    @staticmethod
    def _session_start():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_ss_cf", ROOT / "tools" / "cc" / "hooks" / "session_start.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_commands_md_has_core_flow_section(self):
        text = (ROOT / "cc" / "COMMANDS.md").read_text(encoding="utf-8")
        assert "## Core flow" in text, (
            "regen cc/COMMANDS.md (render_commands_doc emits ## Core flow)"
        )

    def test_footer_reads_rendered_core_section(self):
        ss = self._session_start()
        core = ss._parse_core_flow(
            (ROOT / "cc" / "COMMANDS.md").read_text(encoding="utf-8")
        )
        assert core, "## Core flow must be present and parseable"
        footer = ss._commands_footer(ROOT)
        for name in core:
            assert name in footer, f"{name} from Core flow missing in banner footer"

    def test_name_absent_from_core_section_is_dropped(self):
        ss = self._session_start()
        # The table row `/x` precedes the section; only the Core-flow names parse,
        # and a name not listed (/handoff) is not surfaced.
        text = "# Commands\n\n| `/x` |\n\n## Core flow\n\n`/status` `/commit`\n\n## Stable actions\n"
        assert ss._parse_core_flow(text) == ["/status", "/commit"]
        assert "/handoff" not in ss._parse_core_flow(text)
