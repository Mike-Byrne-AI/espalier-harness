"""A ``.claude`` body whose frontmatter Claude Code will not load is said so.

Claude Code parses a body's frontmatter as strict YAML and, when that fails,
retries after quoting each value with a pattern a trailing carriage return
defeats. Measured on Claude Code 2.1.314 (2026-11-02, one headless run per
shape on a throwaway tree, the stream's ``init`` event naming what loaded and
the model reading back each description): an unquoted ``: `` inside a value,
or a value opening on ``[``, loads with LF line endings and fails with CRLF --
the agent does not register, and a skill or command loads with its
frontmatter dropped (its description falls back to the body's first line);
quoted, both load under either ending; a `` #`` loads under both, the
description cut where YAML starts its comment. A Windows checkout with
``core.autocrlf=true`` and no ``.gitattributes`` rule writes CRLF, and nothing
said so: the audit parsed only managed ``.toml`` under ``.claude``, the
post-write check looked for placeholders alone, and ``cc/LIVE_SURFACE.md``
listed the unloaded agent with its full description.

The oracle for the predicate is PyYAML (a test dependency): a value it
rejects is FRAGILE and one it reads shorter than written is CUT. The engine's
copy (``espalier.render_surface.frontmatter_hazards``) and the hook's
(``post_write_check._frontmatter_hazards``; a hook cannot import the engine)
are held to one verdict over one corpus. Each row reads its function by
name, so at a base without the fix it fails by its assertion.
"""
# pytest-marker: default-unit  (in-process predicate, audit and roster calls on
# tmp trees, no child process; the shipped-body sweep is marked contract. The
# hook's rows, which spawn it, are tests/test_hooks.py's
# TestPostWriteCheckReadsTheFrontmatter, and doctor's, which run git, are
# tests/test_doctor.py's TestDoctorRecommendsTheFrontmatterLineEndingRule)
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from espalier import render_surface
from espalier._safe_walk import visible
from tests._live_tree import checkout_glob

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

#: Values for ``description:`` inside a three-key frontmatter, each one line.
#: Out of the predicate's domain, so not here: a tab inside a value (PyYAML
#: rejects ``x<TAB>y``, which the JS loaders read), an anchor or a standard or
#: non-specific tag (``&a x``, ``!!str x``, ``! x``: YAML strips the property),
#: an escape inside double quotes the lenient reader does not unescape, and a
#: comment after a closing quote.
SINGLE_LINE_VALUES = (
    "Reviews code for bugs",
    "Reviews code: bugs and style",
    "Reviews code:",
    "Reviews code:bugs",
    "http://example.com/x",
    "Reviews code #bugs and style",
    "Reviews code#bugs",
    "Reviews code # bugs: style",
    "#bugs",
    "[draft] reviews code",
    "[Read, Grep]",
    "{a: b}",
    "{a: b} trailing",
    "[unclosed",
    '"Reviews code: bugs and style"',
    '"quoted" trailing',
    '"bad \\q escape"',
    '"unterminated',
    "'fine: really'",
    "'x' trailing",
    "'unterminated",
    "> see docs",
    ">",
    ">-",
    "|2",
    "|x",
    "*alias",
    "!tag value",
    "- item",
    "-item",
    "? q",
    "?q",
    ": x",
    ":x",
    "-",
    "%x",
    "@x",
    "`x",
    ",x",
    "]x",
    "}x",
    "a: b: c",
    "trailing space ",
    # Escapes inside double quotes YAML accepts, and one it refuses: the two
    # copies' escape tables are held equal here (a dropped `U` or `N` in one
    # copy parts them on these alone).
    '"\\x41 ok"',
    '"\\U0001F600 ok"',
    '"\\N ok"',
    '"\\L ok"',
    '"\\P ok"',
    '"\\xZZ"',
)

#: Whole frontmatter blocks: the cases a one-line value cannot show, and two the
#: lenient reader reads otherwise than YAML without any cut (a ``''`` escape,
#: a block header's comment), so the cut arm leaves them out.
MULTI_LINE_BLOCKS = (
    "name: n\ndescription: 'it''s fine: really'\n",
    "name: n\ndescription: > # a comment\n  folded body\n",
    "name: n\ndescription: first line\n  second: line\nmodel: sonnet\n",
    "name: n\ndescription: first line\n  second line\nmodel: sonnet\n",
    "name: n\ndescription: a #b\n  more\nmodel: sonnet\n",
    "name: n\ndescription: >\n  folded: with a colon\n  and more\nmodel: sonnet\n",
    "name: n\ndescription:\n  nested: map\n",
    "name: n\ntools:\n- Read\n- Grep\n",
    "name: n\nmodel: sonnet: fast\n",
    "name: n\ntools: [Read, Grep] extra\n",
    # A quote opens a quoted item only at an item's start; inside a plain flow
    # item it is a character (YAML reads these four as written).
    "name: n\ntools: [don't, b]\n",
    "name: n\ntools: {k: don't}\n",
    "name: n\ntools: [a 'b' c]\n",
    "name: n\ntools: [a, 'b c']\n",
)


def _engine():
    return getattr(render_surface, "frontmatter_hazards", None)


def _hook_module():
    spec = importlib.util.spec_from_file_location(
        "_post_write_check_frontmatter", HOOKS_DIR / "post_write_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hook():
    return getattr(_hook_module(), "_frontmatter_hazards", None)


def _doc(block: str, eol: str = "\n") -> str:
    return eol.join(["---", *block.rstrip("\n").split("\n"), "---", "", "Body text.", ""])


def _single(value: str) -> str:
    return f"name: n\ndescription: {value}\nmodel: sonnet\n"


def _verdicts(fn, text: str) -> dict[str, str]:
    return {key: verdict for key, verdict, _why, _kept in fn(text)}


def _yaml_or_error(block: str):
    yaml = pytest.importorskip("yaml")
    try:
        return yaml.safe_load(block), None
    except yaml.YAMLError as exc:
        return None, exc


def _norm(value) -> str:
    return " ".join(("" if value is None else str(value)).split())


class TestThePredicateReadsWhatStrictYamlRejects:
    """FRAGILE where PyYAML rejects the block, CUT where it reads the
    description shorter than the lenient reader does."""

    def test_fragile_exactly_where_strict_yaml_rejects_the_block(self):
        fn = _engine()
        assert fn is not None, "render_surface.frontmatter_hazards is missing"
        wrong = []
        for block in [_single(v) for v in SINGLE_LINE_VALUES] + list(MULTI_LINE_BLOCKS):
            _data, err = _yaml_or_error(block)
            fragile = "fragile" in _verdicts(fn, _doc(block)).values()
            if fragile != (err is not None):
                wrong.append((block, "rejected" if err else "parsed", "fragile" if fragile else "not fragile"))
        assert wrong == [], wrong

    def test_cut_exactly_where_yaml_reads_the_description_shorter(self):
        fn = _engine()
        assert fn is not None, "render_surface.frontmatter_hazards is missing"
        wrong = []
        for value in SINGLE_LINE_VALUES:
            data, err = _yaml_or_error(_single(value))
            if err is not None or isinstance(data.get("description"), (list, dict)):
                continue
            if value.startswith('"') and "\\" in value:
                continue  # an escape YAML expands and the lenient reader keeps: no cut either way
            lenient = render_surface._unquote_frontmatter_value(value)
            if render_surface._is_block_scalar_header(value.strip()):
                lenient = ""
            shorter = _norm(data.get("description")) != _norm(lenient)
            cut = _verdicts(fn, _doc(_single(value))).get("description") == "cut"
            if cut != shorter:
                wrong.append((value, repr(data.get("description")), "cut" if cut else "not cut"))
        assert wrong == [], wrong

    def test_a_cut_names_what_claude_code_shows(self):
        fn = _engine()
        assert fn is not None, "render_surface.frontmatter_hazards is missing"
        got = fn(_doc("description: Reviews code #bugs and style\n"))
        assert len(got) == 1, got
        [(key, verdict, _why, kept)] = got
        assert (key, verdict, kept) == ("description", "cut", "Reviews code")

    def test_crlf_on_disk_is_read_from_the_block(self):
        has_crlf = getattr(render_surface, "frontmatter_has_crlf", None)
        assert has_crlf is not None, "render_surface.frontmatter_has_crlf is missing"
        block = _single("Reviews code: bugs")
        assert has_crlf(_doc(block, "\r\n")) is True
        assert has_crlf(_doc(block)) is False
        assert has_crlf("no frontmatter\r\nat all\r\n") is False

    def test_the_hook_twin_gives_the_same_verdicts(self):
        engine, hook = _engine(), _hook()
        assert engine is not None and hook is not None, (
            "the engine's frontmatter_hazards or the hook's _frontmatter_hazards is missing")
        blocks = [_single(v) for v in SINGLE_LINE_VALUES] + list(MULTI_LINE_BLOCKS)
        for eol in ("\n", "\r\n"):
            differ = [b for b in blocks if engine(_doc(b, eol)) != hook(_doc(b, eol))]
            assert differ == [], differ

    def test_a_leading_bom_is_read_past(self):
        """A byte-order mark before the opening ``---`` hid every hazard from
        both copies. Whether Claude Code reads a BOM'd body's frontmatter at
        all is unmeasured; the check judges what follows the mark."""
        engine, hook = _engine(), _hook()
        assert engine is not None and hook is not None
        text = "\ufeff" + _doc(_single("Reviews code: bugs"), "\r\n")
        assert _verdicts(engine, text) == {"description": "fragile"}, engine(text)
        assert _verdicts(hook, text) == {"description": "fragile"}, hook(text)
        assert render_surface.frontmatter_has_crlf(text) is True

    def test_the_hook_twin_reads_the_same_bodies(self):
        """The two copies agree on which paths are bodies Claude Code reads
        frontmatter from: nested, case-varied and non-body paths."""
        mod = _hook_module()
        hook_kind = getattr(mod, "_frontmatter_kind", None)
        assert hook_kind is not None, "post_write_check._frontmatter_kind is missing"
        paths = (
            ".claude/agents/a.md", ".claude/agents/team/a.md", ".CLAUDE/Agents/A.MD",
            ".claude/commands/c.md", ".claude/commands/ns/deep/c.md",
            ".claude/skills/s/SKILL.md", ".claude/skills/s/skill.md",
            ".claude/skills/group/s/SKILL.md", ".claude/skills/SKILL.md",
            ".claude/skills/s/other.md", ".claude/workflows/w.js", ".claude/settings.json",
            "docs/agents/a.md", ".claude\\agents\\win.md",
        )
        differ = [p for p in paths if hook_kind(p) != render_surface.frontmatter_body_kind(p)]
        assert differ == [], differ

    def test_the_hook_twin_says_the_same_sentences(self):
        """What the write-time advisory says of a key is the engine's sentence,
        word for word, for every kind, ending and verdict."""
        mod = _hook_module()
        hook_sentence = getattr(mod, "_fm_sentence", None)
        assert hook_sentence is not None, "post_write_check._fm_sentence is missing"
        rel = ".claude/agents/p.md"
        wrong = []
        for kind in ("agent", "command", "skill"):
            for crlf in (False, True):
                want = render_surface.frontmatter_fragile_sentence(rel, kind, "tools", "a why", crlf)
                got = hook_sentence(rel, kind, "tools", "fragile", "a why", "", crlf)
                if got != want:
                    wrong.append((kind, crlf, got, want))
            for why, kept in (("' #' inside an unquoted value", "Reviews"), ("a value opening on '#'", "")):
                want = render_surface.frontmatter_cut_sentence(rel, why, kept)
                got = hook_sentence(rel, kind, "description", "cut", why, kept, False)
                if got != want:
                    wrong.append((kind, why, got, want))
            if hook_sentence(rel, kind, "model", "cut", "' #' inside an unquoted value", "x", False) is not None:
                wrong.append((kind, "a cut on a key other than description is said"))
        assert wrong == [], wrong


@pytest.mark.contract
class TestEveryShippedBodyLoads:
    """The bodies ``init`` deploys parse as strict YAML and the predicate finds
    nothing in them: the generated CLAUDE.md tables (``cli._build_asset_tables``)
    render these alone, never an adopter's body, so they carry no mark."""

    def test_every_shipped_agent_command_and_skill(self):
        fn = _engine()
        assert fn is not None, "render_surface.frontmatter_hazards is missing"
        bodies = [
            path
            for kind, pattern in (("agents", "*.md"), ("commands", "*.md"), ("skills", "*/SKILL.md"))
            for path in visible(checkout_glob(REPO_ROOT / ".claude" / kind, pattern), REPO_ROOT / ".claude" / kind)
        ]
        assert len(bodies) > 20, bodies
        flagged, rejected = [], []
        for path in bodies:
            text = path.read_text(encoding="utf-8")
            if fn(text):
                flagged.append((path.name, fn(text)))
            block = text.split("\n---", 1)[0][3:] if text.startswith("---") else ""
            if block and _yaml_or_error(block)[1] is not None:
                rejected.append(path.name)
        assert (flagged, rejected) == ([], []), (flagged, rejected)


def _scaffold(tree: Path) -> Path:
    """The minimal surface the audit passes on (``tests/test_proofs.py``'s)."""
    (tree / ".claude").mkdir(parents=True, exist_ok=True)
    (tree / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tree / "reports").mkdir(exist_ok=True)
    (tree / "reports" / "repo_fingerprint.json").write_text("{}", encoding="utf-8")
    (tree / "reports" / "harness_config.json").write_text("{}", encoding="utf-8")
    (tree / "cc").mkdir(exist_ok=True)
    (tree / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    return tree


def _body(tree: Path, rel: str, block: str, eol: str = "\n") -> Path:
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_doc(block, eol).encode("utf-8"))
    return path


COLON_AGENT = "name: probe\ndescription: Reviews code: bugs and style\ntools: Read\n"
COLON_SKILL = "name: probe\ndescription: Reviews code: bugs and style\n"
CUT_AGENT = "name: probe\ndescription: Reviews code #bugs and style\ntools: Read\n"


def _frontmatter_findings(tree: Path) -> list[dict]:
    from espalier.proofs import run_cc_surface_gate
    return [f for f in run_cc_surface_gate(tree)["findings"] if f["check"] == "frontmatter"]


class TestTheAuditNamesABodyByTheLineEndingsOnDisk:
    def test_a_crlf_agent_that_does_not_register_is_a_warning(self, tmp_path):
        tree = _scaffold(tmp_path)
        _body(tree, ".claude/agents/probe.md", COLON_AGENT, "\r\n")
        got = _frontmatter_findings(tree)
        assert len(got) == 1, got
        [hit] = got
        assert hit["level"] == "warning"
        assert hit["detail"].startswith(".claude/agents/probe.md: this agent does not register")
        assert "`description`" in hit["detail"] and "quote the value" in hit["detail"]

    def test_the_same_agent_with_lf_is_no_finding(self, tmp_path):
        tree = _scaffold(tmp_path)
        _body(tree, ".claude/agents/probe.md", COLON_AGENT)
        assert _frontmatter_findings(tree) == []

    def test_a_crlf_skill_and_command_say_their_frontmatter_is_dropped(self, tmp_path):
        tree = _scaffold(tmp_path)
        _body(tree, ".claude/skills/probe/SKILL.md", COLON_SKILL, "\r\n")
        _body(tree, ".claude/commands/probe.md", "description: Reviews code: bugs\n", "\r\n")
        details = sorted(f["detail"] for f in _frontmatter_findings(tree))
        assert len(details) == 2, details
        assert details[0].startswith(".claude/commands/probe.md: Claude Code drops this command's frontmatter")
        assert details[1].startswith(".claude/skills/probe/SKILL.md: Claude Code drops this skill's frontmatter")

    def test_a_cut_description_is_a_note_under_either_ending(self, tmp_path):
        for eol in ("\n", "\r\n"):
            tree = _scaffold(tmp_path / ("crlf" if eol == "\r\n" else "lf"))
            _body(tree, ".claude/agents/probe.md", CUT_AGENT, eol)
            got = _frontmatter_findings(tree)
            assert len(got) == 1, got
            [hit] = got
            assert "the description is cut" in hit["detail"], hit
            assert '"Reviews code"' in hit["detail"] and "register" not in hit["detail"], hit

    def test_a_strict_body_is_no_finding(self, tmp_path):
        tree = _scaffold(tmp_path)
        _body(tree, ".claude/agents/probe.md",
              'name: probe\ndescription: "Reviews code: bugs"\n', "\r\n")
        assert _frontmatter_findings(tree) == []

    def test_a_nested_crlf_command_and_agent_are_named(self, tmp_path):
        """A body in a subfolder (a namespaced command, an agent grouped by
        team, a skill under a group) is judged as the write-time check judges
        it, not only the top level the roster's discovery lists."""
        tree = _scaffold(tmp_path)
        _body(tree, ".claude/commands/ns/probe.md", "description: Reviews code: bugs\n", "\r\n")
        _body(tree, ".claude/agents/team/probe.md", COLON_AGENT, "\r\n")
        _body(tree, ".claude/skills/group/probe/SKILL.md", COLON_SKILL, "\r\n")
        details = sorted(f["detail"] for f in _frontmatter_findings(tree))
        assert [d.split(":", 1)[0] for d in details] == [
            ".claude/agents/team/probe.md",
            ".claude/commands/ns/probe.md",
            ".claude/skills/group/probe/SKILL.md",
        ], details


class TestTheRosterMarksABodyThatDoesNotRegister:
    def _roster(self, tree: Path) -> list[str]:
        return [ln for ln in render_surface.render_live_surface(tree).splitlines() if "probe" in ln]

    def test_a_crlf_agent_is_marked_not_registered(self, tmp_path):
        _body(tmp_path, ".claude/agents/probe.md", COLON_AGENT, "\r\n")
        got = self._roster(tmp_path)
        assert len(got) == 1, got
        [line] = got
        assert line.startswith("- `probe` -- NOT REGISTERED:"), line
        assert "Reviews code: bugs and style" not in line, line

    def test_a_crlf_skill_is_marked_frontmatter_dropped(self, tmp_path):
        _body(tmp_path, ".claude/skills/probe/SKILL.md", COLON_SKILL, "\r\n")
        got = self._roster(tmp_path)
        assert len(got) == 1, got
        [line] = got
        assert line.startswith("- `/probe` -- FRONTMATTER DROPPED:"), line

    def test_the_same_agent_with_lf_is_listed_as_it_loads(self, tmp_path):
        _body(tmp_path, ".claude/agents/probe.md", COLON_AGENT)
        assert self._roster(tmp_path) == ["- `probe` -- Reviews code: bugs and style"]

    def test_a_cut_description_lists_what_claude_code_shows(self, tmp_path):
        _body(tmp_path, ".claude/agents/probe.md", CUT_AGENT)
        got = self._roster(tmp_path)
        assert len(got) == 1, got
        [line] = got
        assert line.startswith("- `probe` -- Reviews code (description cut at"), line


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
