"""TP-117: maintenance_mode flag state-machine transitions + behavioral
test for the new ``_maintenance_mode_active`` helper.

The maintenance_mode flag is a parent-shell env var
(``ESPALIER_MAINTENANCE_MODE``) read by hooks via
``tools/cc/hooks/_maintenance_mode.py``. Domain: ("unset", "0", "1").
Each transition is exercised below; the TP-117 contract test
(``tests/test_state_transitions.py``) walks for these function names.

The behavioral test pins the pure-predicate ``_maintenance_mode_active``
truth table against the registered declaration in
``tests/_state_machines.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Add the hooks dir to sys.path so we can import the helper directly.
_HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
sys.path.insert(0, str(_HOOKS_DIR))
from _maintenance_mode import _maintenance_mode_active  # noqa: E402


def _set_env(monkeypatch, value):
    """Set or unset the ENV_VAR per the three domain values."""
    if value == "unset":
        monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)
    else:
        monkeypatch.setenv("ESPALIER_MAINTENANCE_MODE", value)


def _env_value():
    """Return the current env-var value formatted as one of the three
    domain literals: 'unset', '0', '1' (or the raw value if some other)."""
    import os
    raw = os.environ.get("ESPALIER_MAINTENANCE_MODE")
    if raw is None:
        return "unset"
    return raw


# ── Behavioral test for the new _maintenance_mode_active helper ──────────────

@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("unset", False),
        ("0", False),
        ("1", True),
    ],
)
def test_maintenance_mode_active_truth_table(env_value, expected, monkeypatch):
    """_maintenance_mode_active is the pure-predicate form for the TP-117
    truth-table contract; ``is_active(hook_name, ...)`` is the operator-
    facing form with stderr observability. Both must agree on the
    underlying bool.
    """
    _set_env(monkeypatch, env_value)
    import os
    raw = os.environ.get("ESPALIER_MAINTENANCE_MODE")
    assert _maintenance_mode_active(raw) is expected


# ── TP-117 transition coverage ───────────────────────────────────────────────

def test_maintenance_mode_unset_to_1_transition(monkeypatch):
    """unset -> 1: parent shell sets the flag (the typical operator
    workflow: ``ESPALIER_MAINTENANCE_MODE=1 claude``)."""
    _set_env(monkeypatch, "unset")
    assert _env_value() == "unset"
    _set_env(monkeypatch, "1")
    assert _env_value() == "1"
    assert _maintenance_mode_active(_env_value()) is True


def test_maintenance_mode_1_to_unset_transition(monkeypatch):
    """1 -> unset: parent shell removes the flag entirely (e.g., new
    shell session without the var)."""
    _set_env(monkeypatch, "1")
    assert _env_value() == "1"
    _set_env(monkeypatch, "unset")
    assert _env_value() == "unset"
    assert _maintenance_mode_active(_env_value()) is False


def test_maintenance_mode_unset_to_0_transition(monkeypatch):
    """unset -> 0: explicit-off override (rare but valid; semantically
    the same as unset for the predicate)."""
    _set_env(monkeypatch, "unset")
    assert _env_value() == "unset"
    _set_env(monkeypatch, "0")
    assert _env_value() == "0"
    assert _maintenance_mode_active(_env_value()) is False


def test_maintenance_mode_0_to_1_transition(monkeypatch):
    """0 -> 1: toggle from explicit-off to active."""
    _set_env(monkeypatch, "0")
    assert _env_value() == "0"
    _set_env(monkeypatch, "1")
    assert _env_value() == "1"
    assert _maintenance_mode_active(_env_value()) is True


def test_maintenance_mode_1_to_0_transition(monkeypatch):
    """1 -> 0: toggle from active to explicit-off."""
    _set_env(monkeypatch, "1")
    assert _env_value() == "1"
    _set_env(monkeypatch, "0")
    assert _env_value() == "0"
    assert _maintenance_mode_active(_env_value()) is False


# ---------------------------------------------------------------------------
# relaunch_hint -- the ONE dialect-aware relaunch spelling in the hook layer
# (DEF-640: POSIX prefix is a PowerShell parse error; DEF-676: --continue keeps
# the session the deny happened in)
# ---------------------------------------------------------------------------

import importlib.util as _ilu
import re

from _denied_form import every_form_is_denied

_HOOKS = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"


def _load(name: str):
    if str(_HOOKS) not in sys.path:
        sys.path.insert(0, str(_HOOKS))
    spec = _ilu.spec_from_file_location(name, _HOOKS / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRelaunchHint:
    def test_posix_form_carries_continue(self, monkeypatch):
        mm = _load("_maintenance_mode")
        monkeypatch.setattr(mm.sys, "platform", "linux")
        hint = mm.relaunch_hint()
        assert hint == f"`{mm.ENV_VAR}=1 claude --continue`"

    def test_windows_leads_with_powershell_and_names_every_dialect(self, monkeypatch):
        mm = _load("_maintenance_mode")
        monkeypatch.setattr(mm.sys, "platform", "win32")
        hint = mm.relaunch_hint()
        ps = f'`$env:{mm.ENV_VAR}="1"; claude --continue` (PowerShell)'
        assert hint.startswith(ps), hint
        assert f"`set {mm.ENV_VAR}=1 && claude --continue` (cmd.exe)" in hint
        assert f"`{mm.ENV_VAR}=1 claude --continue` (Git Bash / WSL)" in hint

    def test_command_is_a_parameter(self, monkeypatch):
        mm = _load("_maintenance_mode")
        monkeypatch.setattr(mm.sys, "platform", "linux")
        assert mm.relaunch_hint(command="pytest -q") == f"`{mm.ENV_VAR}=1 pytest -q`"

    def test_every_deny_remedy_routes_through_it(self):
        """The protected-zone hint (write_guard), the protected-zone deny body
        and the env-prefix refusal (_denial_reasons) all spell the relaunch via
        relaunch_hint(): each carries --continue on this host, and none carries
        a bare `claude` relaunch."""
        wg = _load("write_guard")
        dr = _load("_denial_reasons")
        mm = _load("_maintenance_mode")
        expected = mm.relaunch_hint()
        assert expected in wg._PROTECTED_ZONE_HINT
        assert "--continue keeps this session" in wg._PROTECTED_ZONE_HINT
        body = dr.PROTECTED_ZONE_WRITE.format(path="tools/cc/hooks/x.py", hint=wg._PROTECTED_ZONE_HINT)
        assert body.count(expected) == 2, body  # hint + the Do: line
        assert "=1 claude`" not in body, body  # no bare relaunch survives
        assert expected in dr.HARNESS_ENV_PREFIX_INLINE
        assert "=1 claude`" not in dr.HARNESS_ENV_PREFIX_INLINE

    def test_no_hook_spells_a_bare_relaunch_outside_the_helper(self):
        """DERIVED, not enumerated: the hand-listed check above went green while
        `_speedbump.CP_GATEWEAKEN` still said `relaunch with {ENV_VAR}=1 claude`
        (found by the failure-mode pass). Scan every hook module's string
        literals, by SOURCE segment, for a spelled-out relaunch; only
        relaunch_hint() may."""
        offenders = []
        for path in sorted(_HOOKS.glob("*.py")):
            if path.name == "_maintenance_mode.py":
                continue
            offenders.extend(
                f"{path.name}:{lineno}: {seg[:70]!r}"
                for lineno, seg in _bare_relaunch_offenders(path.read_text(encoding="utf-8"))
            )
        assert not offenders, (
            "a hook spells the maintenance relaunch by hand instead of via "
            "_maintenance_mode.relaunch_hint():\n  " + "\n  ".join(offenders)
        )

    @pytest.mark.parametrize("shape", [
        # the exact pre-fix _speedbump line
        'BODY = f"relaunch with {_maintenance_mode.ENV_VAR}=1 claude "',
        # a plain literal
        'BODY = "exit and relaunch with ESPALIER_MAINTENANCE_MODE=1 claude now"',
        # an implicit concatenation wrapped at the seam, the way every long deny
        # body in _denial_reasons.py is wrapped
        'BODY = (\n    f"relaunch with {_maintenance_mode.ENV_VAR}"\n    "=1 claude BEFORE the edit"\n)',
        'BODY = (\n    "relaunch with ESPALIER_MAINTENANCE_MODE=1 "\n    "claude BEFORE the edit"\n)',
        # a comment AT the seam -- the wrap style _denial_reasons.py actually uses
        'BODY = (\n    f"relaunch with {_maintenance_mode.ENV_VAR}"  # why\n    # and why not\n    "=1 claude BEFORE the edit"\n)',
        # DEF-692: a `-p` remedy with no denied-context word IS an offender --
        # the token carve let it through.
        'BODY = "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p resume"',
        # a `not` out of reach does not launder a remedy (code-reviewer, driven)
        'BODY = "do not forget to relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p resume"',
        'BODY = "never use --continue, relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p"',
        'BODY = "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude -p; anything else is refused"',
        'BODY = "the denied form (`ESPALIER_MAINTENANCE_MODE=1 claude -p ...`) misleads; just run ESPALIER_MAINTENANCE_MODE=1 claude -p directly"',
        # a form feed on an EARLIER line: `str.splitlines()` breaks on it and
        # shifts every later line, so a slicer built on it reads the wrong
        # line for this literal and misses the offender; `_lines_no_ff` does
        # not break there (the `ast` rule), so the offender is read
        'X = 1\f\nBODY = "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude now"',
    ])
    def test_the_scan_catches_each_shape(self, shape):
        """The negative twin held in-tree: a later refactor of the scanner is
        witnessed here, not in session memory."""
        assert _bare_relaunch_offenders(shape), shape

    @pytest.mark.parametrize("src", [
        # single-line, a multibyte prefix before the literal on the same line
        'x = "\u00e9\u00e9\u00e9"; BODY = "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude now"',
        # a form feed on an earlier line
        'X = 1\f\nBODY = "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude now"',
        # implicit concatenation with a multibyte prefix, wrapped at the seam
        'p = "\u2192"; BODY = (\n    "relaunch with ESPALIER_MAINTENANCE_MODE=1 "\n    "claude"\n)',
        # a lone carriage return as a line end
        'A = 1\rBODY = "relaunch with ESPALIER_MAINTENANCE_MODE=1 claude now"',
        # an f-string with a multibyte prefix
        'q = "\u00fc"; BODY = f"relaunch with {ENV_VAR}=1 claude now"',
        # nothing to find at all
        'X = 1\nY = 2\n',
    ])
    def test_the_slicer_reads_exactly_what_ast_get_source_segment_reads(self, src):
        """The one-split slicer is a faithful copy of `get_source_segment`
        (byte offsets, `_splitlines_no_ff` line ends): every string node's
        segment is identical, including the shapes a char-offset or a
        `str.splitlines()` draft mis-slices (red-team lane A, driven)."""
        import ast
        lines = _lines_no_ff(src)
        nodes = [n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.JoinedStr) or (isinstance(n, ast.Constant) and isinstance(n.value, str))]
        for node in nodes:
            assert _segment(lines, node) == ast.get_source_segment(src, node), ast.dump(node)[:80]

    def test_the_scan_ignores_the_denied_form_and_the_helper_form(self):
        assert not _bare_relaunch_offenders('X = "do not launch (`ESPALIER_MAINTENANCE_MODE=1 claude -p ...`)"')
        assert not _bare_relaunch_offenders('X = f"relaunch with {ENV_VAR}=1 claude --continue"')
        # an escaped quote inside a literal is not a seam; the segment must
        # survive intact so the --continue carve still sees its own tail
        assert not _bare_relaunch_offenders('X = "say \\"hi\\" then ESPALIER_MAINTENANCE_MODE=1 claude --continue"')


_BARE_RELAUNCH_RE = re.compile(
    # `--continue` excluded: that is the helper's own form. `-p` is NOT excluded
    # by token any more -- _denial_reasons quotes `... claude -p ...` as the
    # DENIED form, and that spelling is exempt only beside a denied-context word
    # in the same segment (DEF-692; a `-p` remedy with no such word is an
    # offender). Same carve the doc-side gate makes.
    r"(?:\{[^}]*ENV_VAR\}|ESPALIER_MAINTENANCE_MODE)=1 claude(?!\s+--continue\b)"
)
# The form starts at the VARIABLE, as the doc-side gate's does, so the
# denied-context window is measured from the same place in both gates: keyed
# on `=1 claude` alone, the 25-character variable name ate the window and the
# denied quote `do not launch (` + the variable + `=1 claude -p ...`)` read as
# a remedy (driven).
_P_FORM_RE = re.compile(
    r"(?:\{[^}]*ENV_VAR\}|ESPALIER_MAINTENANCE_MODE)=1 claude\s+-p\b"
)
# A closing quote (not an escaped one), optional whitespace / line
# continuation / `# comment` lines, optional string prefix, opening quote: the
# seam of an implicit concatenation. Collapsed before matching so a relaunch
# wrapped across two literals is still one relaunch. Comment-aware because
# _denial_reasons.py wraps its long bodies with inline comments AT the seam.
_CONCAT_SEAM_RE = re.compile(
    r"(?<!\\)[\"']\s*(?:\\\n)?\s*(?:#[^\n]*\n\s*)*[fFrRbBuU]{0,2}[\"']"
)


# `ast.get_source_segment` re-splits the WHOLE module on every call (3.10's
# `_splitlines_no_ff` is pure Python and unbounded; 3.13+ stops at the node's
# line), so a scan that calls it once per string node is quadratic in the
# module: 179.7 s on 3.10 and 18.7 s on 3.14 for the 12,397-line
# `_bash_patterns.py`, a per-test timeout on the floor interpreter and an
# xdist worker death (measured 2026-09-22 in a fresh clone). Split each module
# ONCE and slice by the node's positions -- the rule `get_source_segment`
# applies after its split. The line ends are `\r\n`, `\n` and `\r` and
# nothing else, exactly `_splitlines_no_ff`'s: `str.splitlines()` also breaks
# on `\f`, `\v`, `\x1c`-`\x1e`, `\x85`, `\u2028` and `\u2029` and would
# shift every line after a form feed (the shapes row carries one).
_LINE_NO_FF_RE = re.compile(r"(.*?(?:\r\n|\n|\r|$))")


def _lines_no_ff(source: str) -> list[str]:
    lines = _LINE_NO_FF_RE.findall(source)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _segment(lines: list[str], node) -> str | None:
    """The source text of ``node`` from a module split once by
    :func:`_lines_no_ff` -- byte offsets, as the AST's columns are."""
    try:
        lineno, end_lineno = node.lineno - 1, node.end_lineno - 1
        col, end_col = node.col_offset, node.end_col_offset
    except (AttributeError, TypeError):
        return None
    if end_lineno == lineno:
        return lines[lineno].encode("utf-8")[col:end_col].decode("utf-8")
    first = lines[lineno].encode("utf-8")[col:].decode("utf-8")
    last = lines[end_lineno].encode("utf-8")[:end_col].decode("utf-8")
    return "".join([first, *lines[lineno + 1:end_lineno], last])


def _bare_relaunch_offenders(src: str) -> list[tuple[int, str]]:
    """(lineno, source segment) for every string literal in ``src`` that spells
    the maintenance relaunch by hand. Reads the SOURCE segment, not the
    evaluated value: an f-string's pieces arrive as separate ast.Constant
    nodes with the `{...}` gone, and a value-based scan passed against the
    exact pre-fix _speedbump line. Comments are not string nodes and are
    never read. The module is split once (see `_lines_no_ff`)."""
    import ast

    tree = ast.parse(src)
    lines = _lines_no_ff(src)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) or (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        ):
            segment = _segment(lines, node) or ""
            joined = _CONCAT_SEAM_RE.sub("", segment)
            if not _BARE_RELAUNCH_RE.search(joined):
                continue
            if every_form_is_denied(joined, _P_FORM_RE):
                continue  # every form the segment holds is the denied quote
            out.append((node.lineno, segment))
    return out


# ── the bypass roster is DERIVED from the callers, and every carrier names it ──

_REPO_ROOT = _HOOKS_DIR.parent.parent.parent
_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def _maintenance_bypass_callers() -> set[str]:
    """DERIVED, not enumerated: every hook module whose SOURCE calls
    ``_maintenance_mode.is_active`` -- the logging bypass entry point -- through
    any spelling of the import (``_maintenance_mode.is_active(...)``, an
    ``import _maintenance_mode as mm`` alias, or ``from _maintenance_mode import
    is_active``). An AST walk, so a docstring or comment that merely mentions the
    name does not count. Readers of the raw predicate or of ``ENV_VAR`` (the
    session-start warning, ``_explain_path``'s explanation) are not bypasses: a
    hook that early-returned on those would be a bypass that never logs, which
    the helper's own contract forbids."""
    import ast

    callers: set[str] = set()
    for path in sorted(_HOOKS_DIR.glob("*.py")):
        if path.name == "_maintenance_mode.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_aliases = {"_maintenance_mode"}
        bare_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "_maintenance_mode":
                        module_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "_maintenance_mode":
                for alias in node.names:
                    if alias.name == "is_active":
                        bare_names.add(alias.asname or alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "is_active"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_aliases
            ) or (isinstance(func, ast.Name) and func.id in bare_names):
                callers.add(path.stem)
    return callers


def _units(text: str):
    """Roster-claim units: each markdown table row on its own, otherwise a
    blank-line-separated paragraph (a table is one paragraph, but each row scopes
    one thing)."""
    for para in re.split(r"\n\s*\n", text):
        lines = para.splitlines()
        if lines and all(line.lstrip().startswith("|") for line in lines if line.strip()):
            yield from lines
        else:
            yield para


def _paragraph_at(lines: list[str], index: int) -> str:
    """The blank-line-delimited paragraph containing ``lines[index]`` -- the
    window grows with the paragraph, so a roster that reflows when a name is
    added is still read whole."""
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return "\n".join(lines[start:end + 1])


# Units that name the env var and two or more roster hooks WITHOUT being a
# statement of what the flag bypasses. Each entry is (tracked path, a substring
# of the unit) with its reason; the sweep asserts every entry still matches, so
# a stale exclusion reds instead of silently widening the blind spot.
_NOT_A_ROSTER_CLAIM = (
    (".claude/commands/implement-pack.md", "enforce protected-zone and plan-required"),  # a guard explainer plus the relaunch line
    ("bench/README.md", "A caveat the numbers do not carry"),  # a dated measurement narrative
    ("docs/HOOKS.md", "Every gate block also lands one record"),  # which hooks WRITE an audit record on bypass; subagent_stop writes none
    ("memory/injection-opportunity-atlas.md", "MAINTENANCE_MODE active"),  # a design sketch of banner lines
    ("memory/speedbump-checkpoint-atlas.md", "CP-GATEWEAKEN"),  # the gate-weaken predicate's file set
    ("docs/SURFACE_SUPPORT_MATRIX.md", "Main session Write/Edit/NotebookEdit"),  # one surface's guards, "hard-blocked unless" the flag; not the flag's roster
)
# Append-only records and generated mirrors: a stale roster there is history, or
# a copy of a source the sweep already reads.
_NOT_SWEPT_PREFIXES = ("espalier/assets/", "examples/dogfooding/", "espalier/_vendor/")
_NOT_SWEPT_FILES = frozenset({
    "CHANGELOG.md", "ESPALIER_MEMORY.md",
    "docs/session-archive.md", "memory/CONVERGENCE_LEDGER.md",
})


class TestBypassRosterCarriers:
    """The roster of hooks that early-return under maintenance mode was restated
    at many carriers and every one of them said three while four hooks bypass
    (a fan-out under maintenance mode silently lost every subagent's blueprint
    reasoning while the places a reader might check said it was still captured).
    The roster IS the caller set; each carrier must name every member, and the
    one carrier that states a count must state the derived one."""

    def test_the_derivation_sees_the_callers(self):
        callers = _maintenance_bypass_callers()
        assert len(callers) >= 2, callers  # a broken walk would pass a vacuous check

    def test_the_helper_docstring_names_every_caller(self):
        mm = _load("_maintenance_mode")
        for name in _maintenance_bypass_callers():
            assert name in (mm.__doc__ or ""), f"_maintenance_mode docstring omits {name}"

    def test_the_charter_table_names_every_caller_and_the_sentence_states_the_derived_count(self):
        text = (_REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        start = text.index("### Maintenance mode")
        section = text[start:text.index("\n## ", start)]
        # The bypass TABLE only -- the section's tail lists the hooks that are
        # deliberately NOT bypassed, and a whole-section search matched those.
        table_start = section.index("| Hook | What's bypassed")
        table = section[table_start:section.index("\n\n", table_start)]
        callers = _maintenance_bypass_callers()
        for name in callers:
            assert name in table, f"CLAUDE.md maintenance-mode bypass table omits {name}"
        m = re.search(r"When active, (\w+) checks early-return", section)
        assert m, "the charter's roster sentence moved; re-anchor this test"
        word = _NUMBER_WORDS.get(len(callers)) or pytest.fail(f"add {len(callers)} to _NUMBER_WORDS")
        assert m.group(1) == word, (
            f"CLAUDE.md says {m.group(1)!r} checks; {len(callers)} hooks call is_active: {sorted(callers)}"
        )

    @pytest.mark.parametrize("rel, needle", [
        ("docs/ENV_CATALOG.md", "| `ESPALIER_MAINTENANCE_MODE` |"),
        ("docs/HOOKS.md", "| `ESPALIER_MAINTENANCE_MODE=1` | write_guard (protected-zone check)"),  # the friction-bypass table, not a per-hook section row
        ("docs/TROUBLESHOOTING.md", "When `ESPALIER_MAINTENANCE_MODE=1`, `write_guard` skips"),
        ("docs/WORKFLOW.md", "This bypasses write_guard's protected-zone check"),
    ])
    def test_the_seeded_carriers_name_every_caller(self, rel, needle):
        lines = (_REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
        hits = [i for i, line in enumerate(lines) if needle in line]
        assert len(hits) == 1, f"{rel}: the roster sentence moved; re-anchor this test ({hits})"
        line = lines[hits[0]]
        unit = line if line.lstrip().startswith("|") else _paragraph_at(lines, hits[0])
        for name in _maintenance_bypass_callers():
            assert name in unit, f"{rel} roster statement omits {name}:\n{unit}"

    def test_no_tracked_doc_states_a_partial_roster(self):
        """DERIVED sweep: any unit (table row or paragraph) of a tracked markdown
        file that names the env var and two or more roster hooks must name them
        all. This is the net the hand-listed carriers above are not: the HOOKS.md
        table row above was found by this sweep, not by the list."""
        from tests._git_oracle import require_tracked_paths

        callers = _maintenance_bypass_callers()
        tracked = [
            rel for rel in require_tracked_paths(_REPO_ROOT, "*.md", what="tracked markdown")
            if not rel.startswith(_NOT_SWEPT_PREFIXES) and rel not in _NOT_SWEPT_FILES
        ]
        assert "docs/HOOKS.md" in tracked and "memory/hook-authoring.md" in tracked, tracked[:5]
        partial: list[str] = []
        matched: set[tuple[str, str]] = set()
        for rel in tracked:
            text = (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for unit in _units(text):
                if "MAINTENANCE_MODE" not in unit:
                    continue
                named = {n for n in callers if re.search(rf"\b{re.escape(n)}\b", unit)}
                if len(named) < 2 or named == callers:
                    continue
                excl = next(((p, sub) for p, sub in _NOT_A_ROSTER_CLAIM if p == rel and sub in unit), None)
                if excl:
                    matched.add(excl)
                    continue
                partial.append(f"{rel}: omits {sorted(callers - named)} :: {unit.strip()[:120]!r}")
        assert not partial, "a doc states a partial maintenance-mode roster:\n  " + "\n  ".join(partial)
        stale = set(_NOT_A_ROSTER_CLAIM) - matched
        assert not stale, f"exclusions that no longer match a unit (delete them): {sorted(stale)}"
