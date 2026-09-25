"""Tests for ``espalier.pack_manifest`` — the TP-38 parser that
extracts ``Scope (in)`` and ``Affected symbols`` sections from
``task-packs/TP-NN.md`` for ``espalier scope-check``.

Pins the parser's contract for the four section kinds (``ADDED``,
``REMOVED_PATH``, ``RENAMED``, ``CHANGED_SEMANTICS``) and the
markdown shapes it recognizes (top-level ``-`` bullets, ``### h3``
subheadings). Without this contract a markdown-format drift in the
``blueprint-authoring`` skill could silently make scope-check
under-report affected symbols, which lets packs ship with broken
reference graphs and integration-time surprise failures.
"""
# full-tree-exempt: the two live-tree tests in this module read task-packs/,
# which is gitignored and export-ignored; each carries its own skipif over
# `REPO_ROOT / "task-packs"` so it skips with a reason rather than fail on a
# fresh clone or an extracted archive (the idiom of test_check_pack_landing.py).
from __future__ import annotations

from pathlib import Path

import pytest

from espalier.pack_manifest import (
    ADDED,
    CHANGED_SEMANTICS,
    REMOVED_PATH,
    RENAMED,
    affected_symbols_diagnostics,
    parse_affected_literals,
    parse_affected_symbols,
    parse_pack,
    parse_scope_in,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


SAMPLE_PACK = """# TP-31 — Bundled-asset strategy

## Status

- **Version target:** v0.6.1

## Scope (in)

- **31-A** Move `espalier/assets/claude/agents/` to `examples/dogfooding/.claude/`
- **31-B** Remove the deploy loop at `espalier/cli.py:468`
- **31-C** Update `README.md` surface description
- **31-D** Drop `_LOCAL_ONLY_PATHS` agent/command/skill references in `espalier/surface_contract.py`

## Scope (out)

- Rewriting agent frontmatter
- Adding a new CLI mode

## Affected symbols

### Removed paths
- `.claude/agents/` — deploy target; init no longer populates
- `.claude/commands/` — same
- `.claude/skills/` — same

### Added paths/symbols
- `examples/dogfooding/.claude/` — reference dogfooding location

### Changed semantics
- `harness_config.json::agents` — was: deploy spec; now: informational recommendation
- `_LOCAL_ONLY_PATHS` — references to agents/commands/skills removed

### Renamed symbols
- `_OLD_NAME` — see TP-31-A; renamed to `_NEW_NAME`

## Implementation

Step-by-step plan ...
"""


class TestParseScopeIn:
    def test_extracts_backticked_paths(self):
        paths = parse_scope_in(SAMPLE_PACK)
        assert "espalier/assets/claude/agents/" in paths
        assert "examples/dogfooding/.claude/" in paths
        # Line-column suffix is stripped so the bare path matches what
        # scope_walker reports — the code-review pass caught this.
        assert "espalier/cli.py" in paths
        assert "espalier/cli.py:468" not in paths
        assert "README.md" in paths
        assert "espalier/surface_contract.py" in paths
        assert "_LOCAL_ONLY_PATHS" not in paths  # not path-shaped

    def test_strips_line_suffix(self):
        text = """## Scope (in)
- **A** Edit `foo/bar.py:42` per spec
- **B** Edit `baz/qux.py:100:5` (line + col form)
## Scope (out)
"""
        paths = parse_scope_in(text)
        assert paths == ["baz/qux.py", "foo/bar.py"]

    def test_strip_line_suffix_preserves_urls(self):
        """Round-6 fix: ``http://localhost:8080`` must not be mangled
        into ``http://localhost``. URL schemes short-circuit the strip."""
        from espalier.pack_manifest import _strip_line_suffix
        assert _strip_line_suffix("http://localhost:8080") == "http://localhost:8080"
        assert _strip_line_suffix("https://example.com:443/path") == "https://example.com:443/path"
        assert _strip_line_suffix("git+ssh://host:22/repo.git") == "git+ssh://host:22/repo.git"

    def test_strip_line_suffix_handles_arbitrary_depth(self):
        """Deterministic peel: any number of trailing ``:digits`` groups
        collapses cleanly without the super-linear regex backtracking
        the previous regex form was susceptible to on long inputs."""
        from espalier.pack_manifest import _strip_line_suffix
        assert _strip_line_suffix("foo.py:1:2:3:4:5") == "foo.py"
        # Adversarial long input — must complete fast.
        long = "foo.py" + ":42" * 200 + "y"
        # Trailing 'y' means the peel stops at first non-digit segment.
        assert _strip_line_suffix(long).endswith("y")

    def test_returns_empty_when_section_missing(self):
        assert parse_scope_in("# Pack with no scope section") == []

    def test_parses_numbered_heading_and_table_rows(self):
        """TP-151 F-2: real packs use numbered headings (``## 3. Scope (in)``)
        and markdown tables. Pre-fix the bullet-only, unnumbered-heading regex
        returned 0 files for such packs, so 0-B scope-check silently passed."""
        text = (
            "## 3. Scope (in)\n"
            "\n"
            "| Sub-task | File | Theme |\n"
            "|---|---|---|\n"
            "| 1-A | `espalier/foo.py` | bar |\n"
            "| 1-B | `tools/cc/hooks/baz.py` | qux |\n"
            "\n"
            "## 4. Scope (out)\n"
            "\n"
            "- `should/not/appear.py`\n"
        )
        paths = parse_scope_in(text)
        assert "espalier/foo.py" in paths, paths
        assert "tools/cc/hooks/baz.py" in paths, paths
        # The numbered end-heading must stop the section so out-of-scope
        # files don't bleed in.
        assert "should/not/appear.py" not in paths, paths

    def test_parses_numbered_list_items(self):
        """TP-426 4-E: a ``Scope (in)`` written as a NUMBERED list declared
        zero files, so every reference surfaced as a scope gap and 0-B's
        report carried no signal.

        Third instance of the class ``test_parses_numbered_heading_and_table_rows``
        closed for numbered HEADINGS and table ROWS: ``_logical_bullets`` started
        a bullet only on ``-`` or ``|``, so ``1.`` list items were never opened
        and their paths — including any on a wrapped continuation line — were
        dropped. Measured over the live tree at authoring time: TP-426, TP-427
        and TP-425 parsed to 0 files, and TP-415 landed with the paths in its
        five numbered items silently missing from a 38-bullet section.
        """
        text = (
            "## Scope (in)\n"
            "\n"
            "1. **Bind the population** in `tests/_contracts.py`, registered in\n"
            "   `tests/test_documented_claims.py`.\n"
            "2. Counts live in `tests/_surface_expected.py`.\n"
            "10. Two-digit ordinals open a bullet too: `tests/tenth.py`\n"
            "3) The paren form is also a list marker: `tests/paren.py`\n"
            "\n"
            "## Scope (out)\n"
            "\n"
            "- `should/not/appear.py`\n"
        )
        paths = parse_scope_in(text)
        assert "tests/_contracts.py" in paths, paths
        # The wrapped continuation line's path must survive the join.
        assert "tests/test_documented_claims.py" in paths, paths
        assert "tests/_surface_expected.py" in paths, paths
        assert "tests/tenth.py" in paths, paths
        assert "tests/paren.py" in paths, paths
        assert "should/not/appear.py" not in paths, paths

    def test_version_string_at_line_start_is_not_a_list_item(self):
        """TP-426 4-E guard: the numbered-item pattern requires whitespace
        after the ordinal's ``.``/``)``, so a wrapped continuation line opening
        with a dotted version (``0.8.0b1 ...``) stays a continuation rather
        than silently starting a new bullet and orphaning the text before it.
        """
        text = (
            "## Scope (in)\n"
            "\n"
            "- Target `espalier/foo.py` for the release\n"
            "0.8.0b1 ships it alongside `espalier/bar.py`\n"
            "\n"
            "## Scope (out)\n"
        )
        paths = parse_scope_in(text)
        assert "espalier/foo.py" in paths, paths
        assert "espalier/bar.py" in paths, paths

    def test_h4_scope_heading_is_not_matched(self):
        """TP-151 F-2 (review follow-up): the heading regex must anchor to
        line start with exactly 2-3 hashes. An `#### Scope (in)` (h4) is NOT a
        valid Scope heading; pre-anchor the unanchored `#{2,3}` matched 3 of
        the 4 hashes and mis-detected it."""
        text = (
            "#### Scope (in)\n"
            "\n"
            "- `espalier/should_not_match.py`\n"
        )
        assert parse_scope_in(text) == [], parse_scope_in(text)

    def test_only_takes_in_section_not_out(self):
        text = """## Scope (in)

- `keep.py`

## Scope (out)

- `drop.py`
"""
        paths = parse_scope_in(text)
        assert "keep.py" in paths
        assert "drop.py" not in paths


class TestParseAffectedSymbols:
    def test_finds_each_subsection(self):
        symbols = parse_affected_symbols(SAMPLE_PACK)
        kinds = {s.change_type for s in symbols}
        assert REMOVED_PATH in kinds
        assert ADDED in kinds
        assert CHANGED_SEMANTICS in kinds
        assert RENAMED in kinds

    def test_returns_empty_when_section_missing(self):
        assert parse_affected_symbols("# pack with nothing") == []

    def test_extracts_name_and_description(self):
        symbols = parse_affected_symbols(SAMPLE_PACK)
        agents = next(s for s in symbols if s.name == ".claude/agents/")
        assert agents.change_type == REMOVED_PATH
        assert "deploy target" in agents.description

    def test_stops_at_next_h2(self):
        """Affected symbols parser should not bleed into ## Implementation."""
        symbols = parse_affected_symbols(SAMPLE_PACK)
        names = {s.name for s in symbols}
        assert "Step-by-step" not in names  # implementation section text

    def test_strips_path_prefix_from_double_colon_symbol(self):
        """TP-151 F-1: a ``path/to/file.py::symbol`` token stores the BARE
        symbol (after ``::``), since scope_walker.walk_references greps the
        symbol and the literal ``path::symbol`` token never appears in source.
        Pre-fix the full token was stored and resolved to 0 refs on every real
        pack (the scope-check gate was a structural no-op)."""
        text = (
            "## Affected symbols\n"
            "\n"
            "### Changed semantics\n"
            "- `espalier/cli.py::cmd_init` — was X; now Y\n"
        )
        symbols = parse_affected_symbols(text)
        names = {s.name for s in symbols}
        assert "cmd_init" in names, names
        assert "espalier/cli.py::cmd_init" not in names, names


class TestParsePack:
    def test_full_pack_round_trip(self, tmp_path: Path):
        pack_path = tmp_path / "TP-31-bundled-asset.md"
        pack_path.write_text(SAMPLE_PACK, encoding="utf-8")
        manifest = parse_pack(pack_path)
        assert manifest.pack_id == "TP-31"
        assert manifest.pack_path == pack_path
        assert len(manifest.scope_in_files) >= 4
        assert len(manifest.affected_symbols) >= 6

    @pytest.mark.parametrize("stem,expected", [
        ("TP-31-bundled-asset", "TP-31"),
        ("TP-2-foo", "TP-2"),
        ("TP-OSS-01-something", "TP-OSS-01"),
        ("TP-RELEASE-21-windows", "TP-RELEASE-21"),
        ("not-a-pack-name", "not-a-pack-name"),
    ])
    def test_pack_id_extraction(self, tmp_path: Path, stem: str, expected: str):
        pack_path = tmp_path / f"{stem}.md"
        pack_path.write_text("# header\n", encoding="utf-8")
        manifest = parse_pack(pack_path)
        assert manifest.pack_id == expected

    def test_non_utf8_pack_does_not_traceback(self, tmp_path: Path):
        """TP-191 W2: a non-UTF-8 pack must not crash `espalier scope-check`
        with UnicodeDecodeError. Undecodable bytes are replaced (U+FFFD) and
        the parse proceeds — the pack id still resolves from the filename."""
        pack_path = tmp_path / "TP-99-binary.md"
        pack_path.write_bytes(
            b"# TP-99\n\n## Scope (in)\n- `espalier/x.py` \xff\xfe garbage\n"
        )
        manifest = parse_pack(pack_path)  # must not raise
        assert manifest.pack_id == "TP-99"


class TestSubsectionAliases:
    def test_added_alias_accepted(self):
        text = """## Affected symbols

### Added
- `new_thing` — purpose
"""
        symbols = parse_affected_symbols(text)
        assert any(s.name == "new_thing" and s.change_type == ADDED for s in symbols)

    def test_numbered_affected_symbols_heading_parses(self):
        """TP-174b: a numbered heading (``## 5. Affected symbols``) — the
        convention every real pack uses — must parse. The TP-151 F-2 widening
        taught the Scope-in parser to tolerate ``## N.`` but missed this sister
        parser, so scope-check found 0 symbols (a structural no-op) on every
        numbered pack."""
        text = """## 5. Affected symbols

### Changed semantics
- `espalier/foo.py` — `bar` changed
"""
        symbols = parse_affected_symbols(text)
        assert any(s.name == "espalier/foo.py" for s in symbols), symbols
        # the un-numbered form (existing convention) must still parse too
        assert parse_affected_symbols(
            "## Affected symbols\n\n### Changed semantics\n- `x/y.py` — z\n"
        )

    def test_hyphen_and_short_form_subsection_headers_route_by_first_word(self):
        """The blueprint-authoring skill documents the hyphen forms
        ``### Changed-semantics`` / ``### Added-paths`` (and the short
        ``### Renamed``), but the parser previously matched only the exact
        space-form canonical strings, so a pack authored per the skill parsed
        to ZERO symbols and scope-check was a structural no-op. First-word
        routing makes every documented spelling equivalent. Earn-the-red:
        pre-fix this asserted 0 for each hyphen/short header."""
        text = """## Affected symbols

### Added-paths
- `a.py::new_fn` — added

### Changed-semantics
- `b.py::changed_fn` — changed

### Renamed
- `c.py::renamed_fn` — renamed

### Removed-paths
- `d.py::gone_fn` — removed
"""
        got = {s.name: s.change_type for s in parse_affected_symbols(text)}
        assert got == {
            "new_fn": ADDED,
            "changed_fn": CHANGED_SEMANTICS,
            "renamed_fn": RENAMED,
            "gone_fn": REMOVED_PATH,
        }, got

    def test_unknown_subsection_first_word_is_skipped(self):
        """First-word routing must not over-match: a subsection whose first
        word is not a known change-type (``### Notes``) contributes nothing."""
        text = "## Affected symbols\n\n### Notes\n- `x::skipme` — y\n"
        assert parse_affected_symbols(text) == []

    def test_subsection_header_with_trailing_description_parses(self):
        """Real packs annotate the subsection name (``### Changed semantics —
        command count 14→15``). The old exact-match regex required a BARE
        header and silently dropped these, under-counting symbols (TP-163/167
        parsed 5/3 of their real 12/15). First-word routing reads past the
        annotation and still routes it. Earn-the-red: pre-fix this got 0."""
        text = """## Affected symbols

### Changed semantics — command count 14→15 (annotated)
- `a.py::fn_one` — bumped
- `b.py::fn_two` — bumped
"""
        got = [(s.name, s.change_type) for s in parse_affected_symbols(text)]
        assert ("fn_one", CHANGED_SEMANTICS) in got
        assert ("fn_two", CHANGED_SEMANTICS) in got


class TestParseAffectedLiterals:
    """TP-318 2-A: the ``## Affected literals`` parser. A literal is a raw
    string whose rename/edit blast radius the symbol-walk cannot see."""

    def test_ordered_marker_on_an_exclude_continuation_splits_the_bullet(self):
        """Pin the known tradeoff of teaching ``_logical_bullets`` ordered items.

        ``_logical_bullets`` is shared by ``parse_scope_in`` and this parser.
        ``parse_scope_in`` is immune to a false split — it unions backticked
        tokens across all bullets, so grouping is irrelevant there. This
        parser is NOT: an ``EXCLUDE:`` clause wrapped onto a line that opens
        with ``1.`` now starts a new bullet, so that line's globs leave the
        EXCLUDE list and a description-less literal is fabricated.

        Pinned rather than fixed, for two reasons. A continuation opening
        with ``1.`` is malformed Markdown — it already RENDERS as a new list
        item, so the parser is now agreeing with the renderer. And the
        direction is safe: a glob that leaves EXCLUDE becomes *ambiguous*,
        which scope-check reports, never silently excluded. Measured across
        all tracked packs at authoring time, no live pack's
        ``parse_affected_literals`` output changed.

        If this ever bites, the fix is to suppress ordered-item detection
        while an ``EXCLUDE:`` continuation is open — not to revert the
        ordered-item arm, which closed a real blind spot in ``Scope (in)``.
        """
        from espalier.pack_manifest import parse_affected_literals

        text = (
            "## Affected literals\n"
            "\n"
            "- `TOKEN_Q` — desc\n"
            "  EXCLUDE: `a/b.md`, `c/d.md`,\n"
            "  1. more glob: `e/f.md`\n"
        )
        literals = parse_affected_literals(text)
        by_token = {lit.token: lit for lit in literals}
        assert "TOKEN_Q" in by_token, literals
        # The wrapped globs before the ordered marker survive...
        assert by_token["TOKEN_Q"].exclude_globs == ("a/b.md", "c/d.md"), literals
        # ...and the split fabricates a second, description-less literal.
        assert "e/f.md" in by_token, literals
        assert by_token["e/f.md"].exclude_globs == (), literals

    def test_plain_exclude_continuation_still_joins(self):
        """The ordered-item arm must not disturb ORDINARY wrapped EXCLUDE
        clauses — the shape every real pack actually uses."""
        from espalier.pack_manifest import parse_affected_literals

        text = (
            "## Affected literals\n"
            "\n"
            "- `TOKEN_R` — desc\n"
            "  EXCLUDE: `a/b.md`, `c/d.md`,\n"
            "  `e/f.md`\n"
        )
        literals = parse_affected_literals(text)
        assert len(literals) == 1, literals
        assert literals[0].exclude_globs == ("a/b.md", "c/d.md", "e/f.md"), literals

    def test_returns_empty_when_section_missing(self):
        from espalier.pack_manifest import parse_affected_literals
        assert parse_affected_literals("# pack, no literals section") == []

    def test_extracts_token_description_and_exclude_globs(self):
        from espalier.pack_manifest import parse_affected_literals
        text = (
            "## Affected literals\n\n"
            "- `ESPALIER_MEMORY.md` — the committed memory filename; every ref is renamed\n"
            "  EXCLUDE: docs/MEMORY_SYSTEMS.md, CLAUDE.md, examples/auto-memory.template.md\n\n"
            "## Pass criteria\n"
        )
        lits = parse_affected_literals(text)
        assert len(lits) == 1
        lit = lits[0]
        assert lit.token == "ESPALIER_MEMORY.md"
        assert "committed memory filename" in lit.description
        assert lit.exclude_globs == (
            "docs/MEMORY_SYSTEMS.md", "CLAUDE.md", "examples/auto-memory.template.md",
        )
        # The EXCLUDE clause must not bleed into the description.
        assert "EXCLUDE" not in lit.description

    def test_literal_without_exclude_has_empty_globs(self):
        from espalier.pack_manifest import parse_affected_literals
        text = "## Affected literals\n\n- `ENV_VAR_X` — a renamed env var\n"
        lits = parse_affected_literals(text)
        assert len(lits) == 1
        assert lits[0].token == "ENV_VAR_X"
        assert lits[0].exclude_globs == ()

    def test_section_stops_at_next_h2(self):
        from espalier.pack_manifest import parse_affected_literals
        text = (
            "## Affected literals\n\n"
            "- `KEEP_ME` — in section\n\n"
            "## Pass criteria\n\n"
            "- `DROP_ME` — a stray token past the section boundary\n"
        )
        tokens = {lit.token for lit in parse_affected_literals(text)}
        assert "KEEP_ME" in tokens
        assert "DROP_ME" not in tokens

    def test_exclude_first_bullet_does_not_bind_the_glob_as_the_token(self):
        """TP-318 (step-6 hardening): the token is read from the text BEFORE the
        EXCLUDE: clause. A malformed bullet that puts EXCLUDE: (with a backticked
        glob) ahead of the literal must NOT silently bind that glob as the token
        and walk the WRONG string — it yields no literal instead (safe).
        Earn-the-red: pre-fix `ticks[0]` scanned the whole bullet and bound
        `docs/x.md` as the token."""
        from espalier.pack_manifest import parse_affected_literals
        text = (
            "## Affected literals\n\n"
            "- EXCLUDE: `docs/x.md` — note with `REAL_TOKEN` embedded\n"
        )
        lits = parse_affected_literals(text)
        assert lits == [], lits  # no token before EXCLUDE -> nothing declared

    def test_backticked_exclude_globs_are_stripped_and_do_not_shadow_the_token(self):
        """A well-formed bullet (token first) with backtick-quoted EXCLUDE globs:
        the token is the first backtick BEFORE EXCLUDE, and each glob is stored
        with its backticks stripped."""
        from espalier.pack_manifest import parse_affected_literals
        text = (
            "## Affected literals\n\n"
            "- `REAL_TOKEN` — the thing to rename\n"
            "  EXCLUDE: `docs/twin.md`, docs/other.md\n"
        )
        lits = parse_affected_literals(text)
        assert len(lits) == 1
        assert lits[0].token == "REAL_TOKEN"
        assert lits[0].exclude_globs == ("docs/twin.md", "docs/other.md")

    def test_parse_pack_populates_affected_literals(self, tmp_path: Path):
        pack = tmp_path / "TP-99-lit.md"
        pack.write_text(
            "# TP-99\n\n## Affected literals\n\n- `TOKEN_Q` — desc\n  EXCLUDE: a/b.md\n",
            encoding="utf-8",
        )
        manifest = parse_pack(pack)
        assert len(manifest.affected_literals) == 1
        assert manifest.affected_literals[0].token == "TOKEN_Q"
        assert manifest.affected_literals[0].exclude_globs == ("a/b.md",)


class TestHeadingPrefixParity:
    """One heading-prefix idiom, four regex sites, three parser functions.

    ``parse_scope_in`` owns TWO of the four — its section START pattern and its
    section TERMINATION pattern — while ``parse_affected_symbols`` and
    ``parse_affected_literals`` own one each. Every per-parser test above drives
    ONE parser against ONE shape, so none of them can see a desync between the
    sites; that lockstep gap is what let ``/scope-check`` silently no-op once,
    and its failure direction is a 0-result silent PASS.

    The h2/h3 axis is asserted on the ``parse_scope_in`` pair only: at ``###``
    the ``Affected symbols`` section heading would collide with its own ``###``
    change-type subsections, so an h3 row there would be testing ambiguity
    rather than parity.
    """

    @staticmethod
    def _pack(level="##", numbered=False):
        def h(n, title):
            return f"{level} {f'{n}. ' if numbered else ''}{title}"
        return "\n".join([
            h(3, "Scope (in)"),
            "- Edit `espalier/in_scope.py` per spec",
            h(4, "Scope (out)"),
            "- Leave `out/only.py` alone",
            h(5, "Affected symbols"),
            "### Changed-semantics",
            "- `espalier/in_scope.py::alpha`",
            h(6, "Affected literals"),
            "- `ESPALIER_PARITY_TOKEN`",
            "",
        ])

    @pytest.mark.parametrize("numbered", [False, True])
    def test_every_section_parser_accepts_the_same_heading_shapes(self, numbered):
        """Sites 140 / 232 / 291 — the three section-START patterns."""
        text = self._pack(numbered=numbered)
        assert parse_scope_in(text), f"scope_in empty (numbered={numbered})"
        assert parse_affected_symbols(text), f"affected_symbols empty (numbered={numbered})"
        assert parse_affected_literals(text), f"affected_literals empty (numbered={numbered})"

    @pytest.mark.parametrize("numbered", [False, True])
    def test_scope_in_terminates_at_scope_out_rather_than_slurping(self, numbered):
        """Site 141 — the TERMINATION pattern, which has no parser of its own.

        ``out/only.py`` appears only under ``Scope (out)``. If the terminator
        desyncs from the start pattern the section never ends and the token is
        falsely reported in-scope — over-reporting blast radius, which reads as
        conscientious and so invites no suspicion.
        """
        assert "out/only.py" not in parse_scope_in(self._pack(numbered=numbered))

    @pytest.mark.parametrize("numbered", [False, True])
    def test_h3_sections_accepted_by_the_scope_in_pair(self, numbered):
        text = self._pack(level="###", numbered=numbered)
        assert parse_scope_in(text), f"h3 scope_in empty (numbered={numbered})"
        assert "out/only.py" not in parse_scope_in(text)


class TestAffectedSymbolsDiagnostics:
    """``parse_affected_symbols`` returns a COUNT; a count is not a success
    signal unless something pins the expected count. These pin what the count
    cannot say.

    Calibrated against the live population, which twice overturned the intake's
    story. An unrouted ``### <subsection>`` is NOT reported: censusing every
    such heading in the tree found 35, of which 34 are deliberate authoring
    convention (``### Referenced authorities (read-only)`` x10, ``### Docs`` x5,
    ``### Unmodified-on-purpose``, ``### Walked, no change required``) — and the
    pack whose "5 declared -> 1 parsed" motivated the check parks its extras
    under ``### Read-only (0-B does NOT walk these)`` ON PURPOSE. The single
    genuine near-miss, ``### Deleted-paths``, is fixed at the routing table.
    Reporting the rest would be 34 false fires on a toolbelt where
    false-positives outrank leak-closing.
    """

    _HEAD = "## Affected symbols\n\n### Changed-semantics\n"
    _TAIL = "\n## Pass criteria\n"

    def _diag(self, body):
        return affected_symbols_diagnostics(self._HEAD + body + self._TAIL)

    def test_multi_declaration_bullet_is_reported(self):
        notes = self._diag("- `espalier/a.py`, `b.py`, `c.py`\n")
        assert len(notes) == 1, notes
        assert "declared 3" in notes[0]
        assert "'b.py'" in notes[0] and "'c.py'" in notes[0]

    def test_prose_annotation_is_not_reported(self):
        """The shape that made an unfiltered version fire 113 times."""
        assert self._diag(
            "- `espalier/a.py::alpha` *(the append site — confirmed at "
            "`a.py:631`, NOT `alpha_old`)*\n"
        ) == []

    def test_rename_arrow_is_not_reported(self):
        """`old` -> `new` is two tokens BY DESIGN; keeping the first is the
        documented rename convention, not a drop."""
        assert self._diag("- `espalier/old.py` → `espalier/new.py`\n") == []

    def test_a_token_only_inside_an_annotation_declares_nothing_and_is_reported(self):
        """DEF-778, the ledger probe's shape: the only backticked token sits
        in a parenthesised aside. Read from the whole line it declared
        `README.md`; the parser and the diagnostics now read one rule."""
        body = "- something happened (see `README.md` for details)\n"
        assert parse_affected_symbols(self._HEAD + body + self._TAIL) == []
        notes = self._diag(body)
        assert len(notes) == 1, notes
        assert "inside an annotation" in notes[0] and "README.md" in notes[0], notes

    def test_a_token_after_a_dash_tail_is_an_annotation_too(self):
        body = "- the append site moved — see `espalier/a.py::alpha`\n"
        assert parse_affected_symbols(self._HEAD + body + self._TAIL) == []
        assert any("inside an annotation" in n for n in self._diag(body))

    def test_a_leading_label_keeps_its_declaration(self):
        """Ten live packs open a bullet with a closed parenthetical label; a
        head cut at the first opener read them as declaring nothing."""
        body = "- (A2) `espalier propose-rules` subcommand in `espalier/cli.py`\n"
        syms = parse_affected_symbols(self._HEAD + body + self._TAIL)
        assert [s.name for s in syms] == ["espalier propose-rules"], syms
        assert self._diag(body) == []

    def test_a_declaration_before_its_annotation_is_still_read(self):
        body = "- `espalier/a.py::alpha` (see `README.md` for the why)\n"
        syms = parse_affected_symbols(self._HEAD + body + self._TAIL)
        assert [s.name for s in syms] == ["alpha"], syms
        assert self._diag(body) == []

    def test_a_dash_inside_a_closed_label_is_not_a_tail(self):
        """The live TP-378 shape: the label's own em-dash used to kill every
        token after it under a whole-prefix dash rule."""
        body = "- Rows kept, open (verified unbuilt — must NOT be struck): `TP-237`, `TP-203b` (INV-3).\n"
        syms = parse_affected_symbols(self._HEAD + body + self._TAIL)
        assert [s.name for s in syms] == ["TP-237"], syms

    def test_a_label_opening_bullet_with_two_declarations_is_reported(self):
        """The diagnostics read the declaration span, not a head cut at the
        first parenthesis -- so the label shape's dropped second token is
        named like any other."""
        notes = self._diag("- (A2) `espalier/a.py::alpha` `espalier/b.py::beta`\n")
        assert len(notes) == 1 and "declared 2" in notes[0], notes

    def test_deliberate_context_subsection_is_not_reported(self):
        text = (
            "## Affected symbols\n\n### Referenced authorities (read-only)\n"
            "- `docs/CONVENTIONS.md`\n- `docs/SHARP_EDGES.md`\n" + self._TAIL
        )
        assert affected_symbols_diagnostics(text) == []

    def test_deleted_paths_subsection_routes_rather_than_vanishing(self):
        """``deleted`` was the one unrouted heading in the tree that meant a
        change type. Pre-fix its whole subsection parsed to nothing."""
        text = (
            "## Affected symbols\n\n### Deleted-paths\n"
            "- `tools/cc/gone.py`\n" + self._TAIL
        )
        syms = parse_affected_symbols(text)
        assert [s.name for s in syms] == ["tools/cc/gone.py"]
        assert syms[0].change_type == REMOVED_PATH


class TestEdgeCases:
    def test_section_runs_to_eof_without_terminator(self):
        """``## Scope (in)`` without a following ``## Scope (out)`` —
        the parser must still extract bullets up to EOF rather than
        returning an empty list."""
        text = """# header

## Scope (in)

- `src/a.py` — only section, no terminator
- `src/b.py` — same
"""
        paths = parse_scope_in(text)
        assert paths == ["src/a.py", "src/b.py"]

    def test_credits_path_on_wrapped_continuation_line(self):
        """TP-318 0-A: a bullet whose path spills onto a WRAPPED continuation
        line (no leading ``-``/``|``) must still credit that path. Pre-fix
        ``parse_scope_in`` scanned only the line that STARTED with ``-``/``|``,
        so a pack could list a file on the second visual line and still have
        scope-check flag it as a false gap. Earn-the-red: pre-fix
        ``wrapped/continuation.py`` is missing from the result."""
        text = """## Scope (in)

- `espalier/first.py` — the bullet starts here and wraps onto a
  continuation line that also names `wrapped/continuation.py` in scope
- `standalone.py` — a normal one-line bullet

## Scope (out)

- `should/not/appear.py`
"""
        paths = parse_scope_in(text)
        assert "espalier/first.py" in paths, paths
        assert "wrapped/continuation.py" in paths, paths  # RED before the 0-A fix
        assert "standalone.py" in paths, paths
        # The continuation-line join must NOT leak past the blank line into
        # Scope (out) — a bullet ends at a blank line.
        assert "should/not/appear.py" not in paths, paths

    def test_looks_like_path_false_branch_via_dedicated_pack(self):
        """Tokens that are neither slash-bearing nor extension-bearing
        must be dropped — pin this without relying on SAMPLE_PACK's
        side-effects."""
        text = """## Scope (in)

- `BARE_IDENTIFIER` — neither path nor file
- `another_token` — same
- `real/path.py` — path-shaped
- `also.md` — extension-shaped

## Scope (out)
"""
        paths = parse_scope_in(text)
        assert paths == ["also.md", "real/path.py"]
        assert "BARE_IDENTIFIER" not in paths
        assert "another_token" not in paths

    def test_looks_like_path_excludes_numeric_ratio_and_whitespace(self):
        """The only slash-bearing tokens excluded by contract are a pure numeric
        ratio (`14/15`) and a whitespace-bearing token (`yes / no`). Word-pairs
        like `and/or` / `read/write` are ADMITTED as harmless in-scope entries
        (over-inclusion is the safe direction — they get looked up and are never
        flagged as a gap)."""
        from espalier.pack_manifest import _looks_like_path
        for prose in ("14/15", "1/2", "yes / no"):
            assert not _looks_like_path(prose), f"{prose!r} should be excluded"
        for admitted in ("and/or", "read/write", "either/or"):
            assert _looks_like_path(admitted), f"{admitted!r} should be admitted (harmless)"

    def test_looks_like_path_keeps_real_paths(self):
        """The `/` branch must not drop real paths. Includes the bare
        extensionless DIRECTORY shape (no trailing slash) that a prior
        extension-or-dot shape-gate wrongly dropped — a false out-of-scope-gap
        regression on packs declaring directory scope."""
        from espalier.pack_manifest import _looks_like_path
        for path in ("espalier/cli.py", "docs/external/", "tools/cc/hooks/_recall.py",
                     "cc/blueprints/latest.json", "reports/",
                     # regression: extensionless dir paths, no trailing slash
                     "tools/cc/hooks", "src/components", "espalier/scanners", "lib/utils"):
            assert _looks_like_path(path), f"{path!r} should look like a path"

    def test_looks_like_path_recognizes_dotfiles_and_cfg_ini(self):
        """TP-275 5-A: the recognizer dropped leading-dot dotfiles (`.flake8`,
        `.gitignore`) and `.cfg`/`.ini` config files, contradicting its own
        docstring (DROPPING a real path is the cardinal sin). Recognize them —
        but PRECISELY: a prose method-call token (`.strip()`, `.get(x)`) must NOT
        be admitted, because `verify_landing` shares this heuristic and a false
        path claim there manufactures a fake OWED blocker (its safe-over-inclusion
        contract does not extend to that caller)."""
        from espalier.pack_manifest import _looks_like_path
        for path in (".flake8", ".gitignore", ".editorconfig", "setup.cfg", "tox.ini"):
            assert _looks_like_path(path), f"{path!r} should be recognized as a path"
        for prose in (".strip()", ".get(x)", "_SEED_ADAPT_HEADER"):
            assert not _looks_like_path(prose), (
                f"{prose!r} must NOT be admitted (would mint a false OWED in verify_landing)"
            )

    def test_parse_pack_raises_filenotfounderror_on_missing(self, tmp_path):
        """Contract: parse_pack propagates the OSError from read_text
        rather than silently returning an empty manifest."""
        import pytest

        with pytest.raises(FileNotFoundError):
            parse_pack(tmp_path / "nope.md")


class TestFormatGrowthDoesNotPerturbTheParsers:
    """The pack format may gain sections and Landing fields without touching
    its consumers — pinned, rather than left as a property that happens to hold.

    Every consumer that could reject uses an INCLUSION list, never an allow-list:
    ``_CLAIM_SECTIONS`` is a fixed tuple, ``_LANDING_FIELDS`` asks only "present
    and non-empty" and never "is every line recognised", and the section parser
    bounds on a generic ``^## `` terminator. So unknown sections and unknown
    fields are invisible by construction, and the archived corpus exercises that
    daily — ``Done/`` already carries ~70 distinct Landing field-sets, with 100+
    ad-hoc field names flowing through.

    But nothing asserted it. Before this class, a refactor of any of the three
    to an allow-list would have gone green while breaking every archived pack,
    which is the whole reason a format revision could be landed without touching
    them. The assertions are DIFFERENTIAL — same pack, with and without the new
    sections, must parse identically — so they pin the property itself rather
    than a snapshot of today's output, and cannot stale when the format grows
    again.
    """

    #: A WELL-FORMED pack. `## Scope (out)` is not decoration here: it is the
    #: literal terminator `parse_scope_in` bounds on, so a fixture omitting it
    #: never terminates the scope-in section and slurps every downstream path
    #: token — which looked exactly like a parser defect until driven. The
    #: parser's own comment warns about this; the fixture has to be a real pack
    #: shape before it can test anything about real packs.
    _BASE = """# TP-999 — a pack

## Scope (in)
- touch `espalier/example.py` and `tests/test_example.py`

## Scope (out)
- `espalier/unrelated.py` — deferred, separate concern

## Affected symbols

### Changed-semantics
- `espalier/example.py::do_thing`

## Pass criteria
1. Full suite green.

## Files touched
- `espalier/example.py`

## Landing
- State: LANDED
- Commits: abc1234
- Suite: 10 passed
- Earn-the-red: drove the red first
- Date: 2026-01-01
"""

    #: Everything the revised format added, placed WHERE THE FORMAT PUTS IT:
    #: Task 0 is slot 4.5, ahead of Affected symbols. That position is
    #: load-bearing for this fixture, not cosmetic — a first cut inserted the
    #: new sections *after* Affected symbols, and a parser mutated to truncate
    #: at the unknown heading then lost nothing and stayed green. A fixture that
    #: does not model the artifact's real shape cannot see the real failure.
    #: The Task 0 oracle names a real script path for the same reason: without a
    #: path-shaped token, widening the claim-section tuple to swallow Task 0
    #: adds no claims and that mutation survives too. The BARE path matters
    #: separately from the command: `_extract_path_tokens` drops any backticked
    #: token containing whitespace as a command rather than a path, so an oracle
    #: line alone is invisible to it — a real Task 0 names its subject file too,
    #: and that is the token a widened claim tuple would wrongly claim.
    #: The Landing additions go BETWEEN existing fields rather than appended,
    #: since a position-keyed field reader would pass an append-only fixture.
    _GROWN = _BASE.replace(
        "## Affected symbols",
        "## Task 0 — Verify\n"
        "| Oracle | Refuting result | Exit |\n"
        "|---|---|---|\n"
        "| `python3 scripts/check_pack_landing.py` | non-zero | stop and re-raise |\n"
        "| subject: `scripts/check_pack_landing.py` | absent | re-derive |\n\n"
        "## Recall triggers\n"
        "- Before authoring: `/recall citation rot`\n\n"
        "## Affected symbols",
    ).replace(
        "- Suite: 10 passed",
        "- Suite: 10 passed\n- Red-team: 2 lanes, none found\n- Reach: 3 closed / 1 deferred",
    )

    def _pack(self, tmp_path, name: str, text: str) -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_pack_manifest_parses_both_identically(self, tmp_path):
        """Scope-in files and affected symbols must not shift."""
        base = parse_pack(self._pack(tmp_path, "TP-999-base.md", self._BASE))
        grown = parse_pack(self._pack(tmp_path, "TP-999-grown.md", self._GROWN))
        assert base.scope_in_files == grown.scope_in_files, (
            "an added section changed which files the pack is read as claiming"
        )
        assert [(s.name, s.change_type) for s in base.affected_symbols] == [
            (s.name, s.change_type) for s in grown.affected_symbols
        ], "an added section perturbed Affected symbols parsing"
        assert base.affected_symbols, "fixture parsed nothing -- the assertion above is vacuous"

    def test_check_pack_landing_reads_both_identically(self):
        """`State:` detection and completeness must ignore unknown fields."""
        import importlib.util

        repo_root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "_cpl_tolerance", repo_root / "scripts" / "check_pack_landing.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.landed_state(self._BASE) == mod.landed_state(self._GROWN) == "LANDED"
        missing_base = [f for f in mod._LANDING_FIELDS if f"- {f}:" not in self._BASE]
        missing_grown = [f for f in mod._LANDING_FIELDS if f"- {f}:" not in self._GROWN]
        assert missing_base == missing_grown == [], (
            "the completeness fields must be found in both; a field-set that is "
            "position-keyed rather than name-keyed would fail on the grown pack"
        )

    def test_verify_landing_classifies_both_identically(self):
        """The claim sections are a fixed tuple; new sections must not add claims."""
        from espalier.verify_landing import classify_against

        tracked = {"espalier/example.py", "tests/test_example.py"}
        base = classify_against(self._BASE, tracked, set())
        grown = classify_against(self._GROWN, tracked, set())
        assert [e.path for e in base] == [e.path for e in grown], (
            "an added section introduced a new claimed path -- Task 0's oracle "
            "commands would be read as landing claims"
        )
        assert base, "fixture produced no claims -- the assertion above is vacuous"


class TestLiveRenameSpellings:
    """DEF-410j review: run over all 234 packs in the tree, two `### Renamed`
    spellings real packs use read as a whole-file rename the moment a reader
    turned a bullet's first token into a prescription. Verbatim bullets, pinned
    at the parser so 0-B and 0-D read them the same way."""

    def test_spaced_path_symbol_names_the_symbol(self):
        text = (
            "## Affected symbols\n\n### Renamed\n"
            "- `espalier/cli.py` :: local `_tp88_deploys` → `deployed_seed_docs` "
            "(4-A; pack-id identifier, two sites)\n"
        )
        syms = parse_affected_symbols(text)
        assert [s.name for s in syms] == ["_tp88_deploys"]
        assert syms[0].change_type == RENAMED

    def test_spaced_path_symbol_without_a_qualifier(self):
        text = (
            "## Affected symbols\n\n### Changed semantics\n"
            "- `espalier/cli.py` :: `cmd_init` — was X; now Y\n"
        )
        assert [s.name for s in parse_affected_symbols(text)] == ["cmd_init"]

    def test_none_bullets_declare_nothing(self):
        text = (
            "## Affected symbols\n\n### Renamed\n"
            "- *(none — `docs/TASK_RECIPES.md`'s heading rename is doc text, not a\n"
            "  production symbol.)*\n\n"
            "### Added-paths\n- (none)\n- _(none)_\n- (None yet — `docs/x.md` later)\n"
        )
        assert parse_affected_symbols(text) == []

    def test_a_none_bullet_is_not_reported_as_a_drop(self):
        text = (
            "## Affected symbols\n\n### Renamed\n"
            "- *(none — `docs/a.md`, `docs/b.md` considered)*\n\n## Pass criteria\n"
        )
        assert affected_symbols_diagnostics(text) == []


# ── §C7: the parser honours the pack's own markup (2026-09-11) ─────────────


class TestStruckBulletsAreWithdrawn:
    """CONV-2: a bullet struck with ``~~`` was still parsed and still walked,
    so the pre-flight aimed at code the pack no longer touched (two live
    instances in the archived TP-432). A struck span is now dead text for
    both parsers and the diagnostics."""

    def test_a_struck_symbol_bullet_is_skipped(self):
        text = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- `a.py::keep` — x\n"
            "- ~~`scripts/gone.sh`~~ *(432-E — removed, premise falsified)*\n"
        )
        assert [s.name for s in parse_affected_symbols(text)] == ["keep"]

    def test_a_partially_struck_bullet_keeps_its_live_token(self):
        text = "## Affected symbols\n\n### Changed-semantics\n- `a.py::keep` — ~~old note~~ new note\n"
        (sym,) = parse_affected_symbols(text)
        assert (sym.name, sym.description) == ("keep", "new note")

    def test_a_struck_literal_is_skipped(self):
        from espalier.pack_manifest import parse_affected_literals
        text = "## Affected literals\n\n- `LIVE` — kept\n- ~~`DEAD`~~ — withdrawn\n"
        assert [lit.token for lit in parse_affected_literals(text)] == ["LIVE"]

    def test_a_struck_bullet_is_not_reported_as_a_drop(self):
        text = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- ~~`scripts/gone.sh`~~ *(removed)*\n"
        )
        assert affected_symbols_diagnostics(text) == []

    def test_a_strike_that_wraps_onto_a_continuation_line_is_honoured_by_both_parsers(self):
        """The symbols parser reads physical lines, the literals parser
        logical bullets; a strike that wraps must withdraw in both (the
        failure-mode review drove the symbols side still walking it: 87
        references, rc 2). 22 percent of the archive's bullets wrap."""
        from espalier.pack_manifest import parse_affected_literals
        symbols = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- ~~`espalier/pack_manifest.py::parse_affected_symbols` -- withdrawn, the\n"
            "  sub-task was dropped on 09-11~~\n"
            "- `a.py::keep` -- x\n"
        )
        assert [s.name for s in parse_affected_symbols(symbols)] == ["keep"]
        assert affected_symbols_diagnostics(symbols) == []
        literals = (
            "## Affected literals\n\n"
            "- ~~`DEAD` -- withdrawn, the\n  sub-task was dropped~~\n"
            "- `LIVE` -- kept\n"
        )
        assert [lit.token for lit in parse_affected_literals(literals)] == ["LIVE"]

    def test_a_stray_double_tilde_does_not_pair_across_bullets(self):
        """A strike never crosses a bullet start or a blank line, so `~~` in
        one bullet's prose cannot pair with a strike below and eat the text
        between; a bullet with a stray `~~` and no token is still reported."""
        text = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- `a.py::first` -- approx ~~10 refs, see below\n"
            "- `b.py::second` -- y\n"
            "- ~~`c.py::gone`~~ *(withdrawn)*\n"
            "- README.md ~~regenerated by the deploy, see below\n"
        )
        assert [s.name for s in parse_affected_symbols(text)] == ["first", "second"]
        (note,) = affected_symbols_diagnostics(text)
        assert "declares no backticked token" in note and "README.md" in note

    def test_an_unhandled_strike_spelling_is_reported_not_silently_walked(self):
        text = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- <del>`a.py::old`</del> -- withdrawn the GitHub way\n"
            "- STRUCK: `b.py::older` -- withdrawn the prefix way\n"
        )
        notes = affected_symbols_diagnostics(text)
        assert len(notes) == 2
        assert all("strike spelling the parser does not honour" in n for n in notes)
        # ...and, honestly, both are still walked until the author fixes them.
        assert [s.name for s in parse_affected_symbols(text)] == ["old", "older"]

    def test_withdrawn_tokens_are_named_so_a_strike_is_known_to_register(self):
        from espalier.pack_manifest import affected_symbols_withdrawn
        text = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- `a.py::keep` -- ~~old note~~ new note\n"
            "- ~~`scripts/gone.sh`~~ *(removed)*\n"
            "- ~~`scripts/also.py::f` -- withdrawn, the\n  reason wraps~~\n\n"
            "### Referenced authorities (read-only)\n- ~~`not/routed.py`~~\n"
        )
        assert affected_symbols_withdrawn(text) == ["scripts/gone.sh", "scripts/also.py::f"]
        assert affected_symbols_withdrawn("## Pass criteria\n") == []

    @pytest.mark.skipif(
        not (REPO_ROOT / "task-packs" / "Done").is_dir(),
        reason="self-host only: task-packs/Done/ is gitignored -- absent in a fresh clone",
    )
    def test_the_archived_pack_that_motivated_the_row_walks_no_struck_symbol(self):
        pack = REPO_ROOT / "task-packs" / "Done" / "TP-432-c14-durable-home-for-instrument-output.md"
        if not pack.is_file():
            pytest.skip("TP-432 is not in this checkout's archive")
        from espalier.pack_manifest import parse_pack
        struck = [s.name for s in parse_pack(pack).affected_symbols if s.name.startswith("scripts/")]
        assert struck == [], f"struck symbols still walked: {struck}"


class TestNoneSpellings:
    """A sub-section that declares nothing says so in more spellings than the
    paren form; each is skipped by the parser and reported by nothing."""

    @pytest.mark.parametrize("bullet", [
        "- None.",
        "- _None._",
        "- None to production code.",
        "- (No new files — see Scope (out))",
        "- none. The event is observational.",
        "- *(none — `docs/x.md` considered)*",
    ])
    def test_declares_nothing(self, bullet):
        text = f"## Affected symbols\n\n### Added-paths\n{bullet}\n"
        assert parse_affected_symbols(text) == []
        assert affected_symbols_diagnostics(text) == []

    def test_a_prose_bullet_is_not_a_none(self):
        text = "## Affected symbols\n\n### Added-paths\n- Nothing here yet, see below\n"
        (note,) = affected_symbols_diagnostics(text)
        assert "declares no backticked token" in note

    @pytest.mark.parametrize("bullet, name", [
        ("- No longer generated: `espalier/assets/x.md` -- the deploy stops emitting it", "espalier/assets/x.md"),
        ("- No-op wrapper `espalier/a.py::f` removed", "f"),
        ("- No changes to behaviour, but `config.py::LIMIT` bumped from 10 to 20", "LIMIT"),
    ])
    def test_a_sentence_that_merely_opens_with_no_is_a_declaration(self, bullet, name):
        """Both reviewers drove the bare `no` widening swallowing these with
        the diagnostic silenced too; only `no new` is a none spelling."""
        text = f"## Affected symbols\n\n### Removed-paths\n{bullet}\n"
        assert [s.name for s in parse_affected_symbols(text)] == [name]

    @pytest.mark.parametrize("bullet", [
        "- (test functions/fixtures only -- see Files touched)",
        "- (a companion committed-but-ungated marker file path, if that approach is chosen)",
        "- *(2-A adds no symbol -- reuses the existing `repo_mode.detect_repo_mode`.)*",
    ])
    def test_a_parenthesised_aside_declares_nothing(self, bullet):
        """The three archived shapes; the third had parsed as a declaration of
        the symbol it says it reuses."""
        text = f"## Affected symbols\n\n### Added-paths\n{bullet}\n"
        assert parse_affected_symbols(text) == []
        assert affected_symbols_diagnostics(text) == []


class TestUnparseableBulletGuard:
    """The guard the class asked for: a bullet under a ROUTED sub-heading that
    names no backticked token is one the walk cannot see, so it is reported,
    and the active packs on this tree carry none."""

    def test_a_bare_path_under_a_routed_heading_is_reported(self):
        text = (
            "## Affected symbols\n\n### Changed-semantics\n"
            "- README.md / docs/CONVENTIONS.md — regenerated by the deploy\n"
        )
        (note,) = affected_symbols_diagnostics(text)
        assert "declares no backticked token" in note
        assert "Changed-semantics" in note
        assert "README.md" in note

    def test_under_an_unrouted_heading_nothing_is_reported(self):
        text = "## Affected symbols\n\n### Notes\n- prose the pre-flight never routes\n"
        assert affected_symbols_diagnostics(text) == []

    @pytest.mark.skipif(
        not list((REPO_ROOT / "task-packs").glob("TP-*.md")),
        reason="self-host only: no active pack at the task-packs/ root on this tree",
    )
    def test_active_packs_declare_every_routed_bullet(self):
        packs = sorted((REPO_ROOT / "task-packs").glob("TP-*.md"))
        offenders = [
            (pack.name, note)
            for pack in packs
            for note in affected_symbols_diagnostics(pack.read_text(encoding="utf-8", errors="replace"))
            if "declares no backticked token" in note
        ]
        assert offenders == [], (
            "an active pack declares a routed bullet the walk cannot see; "
            f"backtick the path or write `- (none — ...)`: {offenders}"
        )


class TestSubsectionsAndHeading:
    """What scope-check needs to name a zero parse's cause (DEF-430) and the
    heading it really matched instead of a hard-coded name."""

    def test_subsections_report_whether_they_route(self):
        from espalier.pack_manifest import affected_symbols_subsections
        text = (
            "## Affected symbols\n\n### Fixed\n- `a.py::f` — y\n\n"
            "### Added-paths\n- `b.py` — z\n\n### Referenced authorities (read-only)\n- `c.py`\n"
        )
        assert affected_symbols_subsections(text) == [
            ("Fixed", False), ("Added-paths", True), ("Referenced authorities (read-only)", False),
        ]
        assert affected_symbols_subsections("## Pass criteria\n") == []

    @pytest.mark.parametrize("heading", [
        "## Affected symbols", "## 5. Affected symbols", "### Affected symbols",
    ])
    def test_the_heading_is_reported_as_spelled(self, heading):
        from espalier.pack_manifest import affected_symbols_heading
        text = f"# TP\n\n{heading}\n\n### Added-paths\n- `a.py` — x\n\n## Pass criteria\n"
        assert affected_symbols_heading(text) == heading

    def test_a_heading_broken_across_lines_is_reported_on_one(self):
        from espalier.pack_manifest import affected_symbols_heading
        assert affected_symbols_heading("##\nAffected symbols\n") == "## Affected symbols"

    def test_all_declare_nothing_is_the_fifth_cause(self):
        from espalier.pack_manifest import affected_symbols_all_declare_nothing as all_none
        assert all_none("## Affected symbols\n\n### Changed-semantics\n- none. The event is observational.\n")
        assert all_none("## Affected symbols\n\n### Added-paths\n- *(none -- children declare their own)*\n")
        assert not all_none("## Affected symbols\n\n### Added-paths\n- none.\n- a bare path\n")
        assert not all_none("## Affected symbols\n\n### Notes\n- none.\n"), "unrouted bullets do not count"
        assert not all_none("## Affected symbols\n\nTo be determined.\n"), "no bullet at all is not all-none"
        assert not all_none("## Pass criteria\n")

    def test_no_heading_reports_none_and_parse_pack_records_it(self, tmp_path):
        from espalier.pack_manifest import affected_symbols_heading, parse_pack
        assert affected_symbols_heading("## Pass criteria\n") is None
        pack = tmp_path / "TP-1-x.md"
        pack.write_text("# TP-1\n\n## 5. Affected symbols\n\n### Added-paths\n- `a.py` — x\n", encoding="utf-8")
        assert parse_pack(pack).affected_symbols_heading == "## 5. Affected symbols"
