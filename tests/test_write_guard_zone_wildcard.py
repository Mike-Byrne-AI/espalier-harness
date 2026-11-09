"""DEF-3010: a removed or relocated operand holding a wildcard is judged by
what it can name, never as the literal path it spells.

``write_guard._mutated_zone`` read `tools/*` as a path named `*` inside
`tools`, which is neither protected nor above anything protected, so both
tools' zone loops passed a wildcard clear of a directory holding the hooks or
the settings files, while the plain directory drew the zone deny (driven
in-process 2026-10-16, four spellings of four). The comparator,
``_protected_zones.glob_reach``, reads the operand segment by segment against
each protected entry; the verdict and the deny text both ask it.

Two layers, so a wall-tier behaviour is pinned at the reader where it can be:
the comparator by its readings (paths only, no command text), then one
composition through both zone checks, built from the live protected roster
crossed with the remove and move verbs the zone loops consume, with a
must-allow twin of every shape below an unprotected directory and beside the
zone.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _hook_utils  # noqa: E402
import _protected_zones  # noqa: E402
import write_guard  # noqa: E402


#: (operand, entry, entry is a file, reach, tail) -- each a reading the
#: docstring of ``glob_reach`` names, plus the folds it must share with
#: ``_is_protected``.
_READINGS = {
    "a star below the parent names the zone": ("tools/*", "tools/cc/", False, "names", ""),
    "a root stub encloses the zone": ("too*", "tools/cc/", False, "encloses", ""),
    "a question mark is a wildcard": ("tool?", "tools/cc/", False, "encloses", ""),
    "a class is a wildcard": ("tools/[c]c", "tools/cc/", False, "names", ""),
    "the shell's caret class negates as fnmatch's bang": ("tools/[^x]c", "tools/cc/", False, "names", ""),
    "a pattern no zone name fits reaches nothing": ("tools/*.log", "tools/cc/", False, "", ""),
    "another directory reaches nothing": ("build/*", "tools/cc/", False, "", ""),
    "a star names an exact protected file": (".claude/*", ".claude/settings.json", True, "names", ""),
    "a pattern the file's name does not fit": (".claude/*.bak", ".claude/settings.json", True, "", ""),
    "nothing sits inside a file": (".claude/*/x", ".claude/settings.json", True, "", ""),
    "a literal remainder inside a zone is the shell's to expand": ("*/build", "cc/", False, "names", "cc/build"),
    "the remainder keeps its own spelling": ("*/Build", "cc/", False, "names", "cc/Build"),
    "a wildcard remainder inside a zone fails closed": ("*/*", "cc/", False, "names", ""),
    "globstar names whatever lies below it": ("**/hooks", "tools/cc/", False, "names", ""),
    "syntax fnmatch does not read fails closed": ("tools/*(x)", "tools/cc/", False, "names", ""),
    "the case fold is the protected check's": ("TOOLS/*", "tools/cc/", False, "names", ""),
    "a separator fold is the protected check's": ("tools\\*", "tools/cc/", False, "names", ""),
    "a leading dot-segment is no component": ("./tools/*", "tools/cc/", False, "names", ""),
}

#: The remove and move verbs both zone loops consume, one template each, the
#: operand bare (a quoted glob is literal in Bash).
_VERBS = {
    "bash-recursive-remove": ("check_bash_for_protected_mutations", "rm -r {}"),
    "bash-move": ("check_bash_for_protected_mutations", "mv {} /tmp/t"),
    "bash-git-remove": ("check_bash_for_protected_mutations", "git rm -r {}"),
    "ps-recursive-remove": ("check_powershell_for_protected_mutations", "Remove-Item -Recurse {}"),
    "ps-move": ("check_powershell_for_protected_mutations", "Move-Item {} t"),
}


def _tree(tmp_path: Path, monkeypatch) -> Path:
    """A throwaway adopter tree holding every zone the composition reaches,
    with the harness switches cleared and the audit records kept out of the
    live tree."""
    monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
    for name in [k for k in os.environ if k.startswith("ESPALIER_") and k != "ESPALIER_AUDIT_DIR"]:
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "tree"
    (root / "tools" / "cc" / "hooks").mkdir(parents=True)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (root / "cc").mkdir()
    (root / "build").mkdir()
    root = root.resolve()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


def _reached_entries() -> list[str]:
    """The roster an adopter tree protects, read as the guard reads it (the
    module's ``PROTECTED_PREFIXES`` also lists `espalier/`, operative on the
    self-host tree alone)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
        prefixes = _hook_utils.harness_protected_prefixes(Path(empty))
    return sorted({*prefixes, *_protected_zones.PROTECTED_FILES})


def _wildcard_shapes(entry: str) -> list[str]:
    """Wildcard operands reaching one protected entry, derived from its
    spelling: a star below its parent, a stub of its first component, a
    question mark for that component's last letter."""
    parts = [p for p in entry.split("/") if p]
    first = parts[0]
    shapes = [first[:2] + "*", first[:-1] + "?"]
    if len(parts) > 1:
        shapes.append("/".join(parts[:-1]) + "/*")
    return shapes


def _cases() -> list[tuple[str, str, str]]:
    return [(verb, entry, shape) for verb in sorted(_VERBS)
            for entry in _reached_entries() for shape in _wildcard_shapes(entry)]


def _beside_shapes(root: Path) -> list[str]:
    """A pattern no protected name fits, in each entry's parent directory (the
    root for a top-level entry), wherever that parent is not itself protected."""
    shapes = set()
    for entry in _reached_entries():
        parts = [p for p in entry.split("/") if p]
        candidate = "/".join(parts[:-1] + ["*.log"])
        if not _protected_zones._is_protected(candidate, root):
            shapes.add(candidate)
    return sorted(shapes)


def _zone_reason(check: str, command: str, root: Path) -> str:
    """One zone check, in-process: the deny reason it printed, or "" for an
    allow."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        getattr(write_guard, check)(command, root, root)
    text = out.getvalue().strip()
    return json.loads(text)["hookSpecificOutput"]["permissionDecisionReason"] if text else ""


class TestGlobReachReadsAnOperandByWhatItCanName:
    """The comparator, by its readings: paths only, no command text."""

    @pytest.mark.parametrize("key", sorted(_READINGS))
    def test_each_reading(self, key: str) -> None:
        operand, entry, is_file, reach, tail = _READINGS[key]
        assert _protected_zones.has_wildcard(operand)
        assert _protected_zones.glob_reach(operand, entry, is_file=is_file) == (reach, tail), key

    def test_a_literal_operand_is_never_asked(self) -> None:
        """The read costs one scan on a literal operand: the verdict asks the
        comparator only past ``has_wildcard``."""
        assert not _protected_zones.has_wildcard("tools/cc/hooks/x.py")
        assert not _protected_zones.has_wildcard("build")

    def test_a_remainder_the_tree_lacks_reaches_nothing(self, tmp_path: Path, monkeypatch) -> None:
        """A glob names nothing absent: a root `*/build` reaches `cc/build`
        only once it exists, and content the command would create first is not
        the harness's."""
        root = _tree(tmp_path, monkeypatch)
        assert _protected_zones.glob_reaches_protected("*/build", root) == ""
        (root / "cc" / "build").mkdir()
        assert _protected_zones.glob_reaches_protected("*/build", root) == "names"


class TestBothZoneChecksReadAWildcardOperand:
    """The live roster crossed with the verbs both zone loops consume."""

    @pytest.mark.parametrize(("verb", "entry", "shape"), _cases())
    def test_a_wildcard_reaching_a_zone_draws_the_zone_deny(
            self, tmp_path: Path, monkeypatch, verb, entry, shape) -> None:
        root = _tree(tmp_path, monkeypatch)
        check, template = _VERBS[verb]
        assert _zone_reason(check, template.format(shape), root), (verb, entry, shape)

    @pytest.mark.parametrize(("verb", "entry", "shape"), _cases())
    def test_the_same_shape_below_an_unprotected_directory_is_allowed(
            self, tmp_path: Path, monkeypatch, verb, entry, shape) -> None:
        root = _tree(tmp_path, monkeypatch)
        check, template = _VERBS[verb]
        assert _zone_reason(check, template.format("build/" + shape), root) == "", (verb, entry, shape)

    @pytest.mark.parametrize("verb", sorted(_VERBS))
    def test_a_pattern_no_zone_name_fits_is_allowed_beside_the_zone(
            self, tmp_path: Path, monkeypatch, verb) -> None:
        """The friction the row declared, gone: `tools/*.log` names no
        protected entry, so it is judged as what it names."""
        root = _tree(tmp_path, monkeypatch)
        check, template = _VERBS[verb]
        shapes = _beside_shapes(root)
        assert "tools/*.log" in shapes and "*.log" in shapes, shapes
        assert [s for s in shapes if _zone_reason(check, template.format(s), root)] == [], verb


class TestTheDenyTextReadsTheGlobAsItsLiteralTwin:
    def test_an_enclosing_glob_names_the_ground(self, tmp_path: Path, monkeypatch) -> None:
        """DEF-5012's text for a glob above harness ground, as for its literal
        twin: the deny names the ground, never the relaunch."""
        root = _tree(tmp_path, monkeypatch)
        check, template = _VERBS["bash-recursive-remove"]
        glob = _zone_reason(check, template.format("too*"), root)
        literal = _zone_reason(check, template.format("tools"), root)
        assert glob.replace("too*", "tools") == literal
        assert "`tools/cc/` is inside it" in glob
