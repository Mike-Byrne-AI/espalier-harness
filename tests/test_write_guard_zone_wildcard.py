"""DEF-3010: a removed or relocated operand holding a wildcard is judged by
what it can name, never as the literal path it spells.

``write_guard._mutated_zone`` read `tools/*` as a path named `*` inside
`tools`, which is neither protected nor above anything protected, so both
tools' zone loops passed a wildcard clear of a directory holding the hooks or
the settings files, while the plain directory drew the zone deny (driven
in-process 2026-10-16, four spellings of four). The comparator,
``_protected_zones.glob_reach``, reads the operand segment by segment against
each protected entry; the verdict and the deny text both ask it.

Three layers, because each pins a wall-tier behaviour at the reader where it
can be: the comparator by its readings (paths only, no command text), the verdict
by effect and by checkout (paths only), then one composition through both
zone checks, built from the live protected roster crossed with the remove and
move verbs the zone loops consume, with a must-allow twin of every shape below
an unprotected directory and beside the zone.
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


#: (operand, entry, entry is a file, reach) -- each a reading the docstrings
#: of ``glob_reach`` and ``_prepare_segment`` name, read with no tree (the
#: existence filter is the next class's).
_READINGS = {
    "a star below the parent names the zone": ("tools/*", "tools/cc/", False, "names"),
    "a root stub encloses the zone": ("too*", "tools/cc/", False, "encloses"),
    "a question mark is a wildcard": ("tool?", "tools/cc/", False, "encloses"),
    "a class is a wildcard": ("tools/[c]c", "tools/cc/", False, "names"),
    "a pattern no zone name fits reaches nothing": ("tools/*.log", "tools/cc/", False, ""),
    "another directory reaches nothing": ("build/*", "tools/cc/", False, ""),
    "a star names an exact protected file": (".claude/*", ".claude/settings.json", True, "names"),
    "a pattern the file's name does not fit": (".claude/*.bak", ".claude/settings.json", True, ""),
    "nothing sits inside a file": (".claude/*/x", ".claude/settings.json", True, ""),
    "a remainder inside a zone names, absent a tree": ("*/build", "cc/", False, "names"),
    "the case fold is the protected check's": ("TOOLS/*", "tools/cc/", False, "names"),
    "a separator fold is the protected check's": ("tools\\*", "tools/cc/", False, "names"),
    "a leading dot-segment is no component": ("./tools/*", "tools/cc/", False, "names"),
    "an empty segment is no component": ("tools//*", "tools/cc/", False, "names"),
    "globstar is a star": ("**/hooks", "tools/cc/", False, ""),
    "a POSIX class is read before the fold cuts it": ("tools/[[:alpha:]]*", "tools/cc/", False, "names"),
    "an equivalence class fails closed": ("tools/[[=c=]]*", "tools/cc/", False, "names"),
    "a negated class is read before the case fold": ("tools/[^A-Z]*", "tools/cc/", False, "names"),
    "a bang-negated class fails closed": ("tools/[!A-Z]*", "tools/cc/", False, "names"),
    "an extended-glob group reads as a star": ("tools/*(c)", "tools/cc/", False, "names"),
    "an at-group with a wildcard reads as a star": ("tools/@(x)?", "tools/cc/", False, "names"),
    "a nested group fails closed": ("tools/*(a|*(b))", "tools/cc/", False, "names"),
    "a plain parenthesis is a literal": ("notes (1)*", "tools/cc/", False, ""),
    "an extended glob reaching nothing is allowed": ("*.@(png|jpg)", "tools/cc/", False, ""),
    "a brace list reaching nothing is allowed": ("*.{png,jpg}", "tools/cc/", False, ""),
    "a brace alternative reaching a zone wins": ("{too,x}*", "tools/cc/", False, "encloses"),
    "a brace list spanning a separator": ("{tools,x}/*", "tools/cc/", False, "names"),
    "a nested brace list expands as the shell's": ("{x,{too,y}}*", "tools/cc/", False, "encloses"),
    "a sequence fails closed": ("x{1..3}*", "tools/cc/", False, "names"),
}


@pytest.fixture
def tree(tmp_path: Path, monkeypatch) -> Path:
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


class TestGlobReachReadsAnOperandByWhatItCanName:
    """The comparator, by its readings: paths only, no command text."""

    @pytest.mark.parametrize("key", sorted(_READINGS))
    def test_each_reading(self, key: str) -> None:
        operand, entry, is_file, reach = _READINGS[key]
        assert _protected_zones.has_wildcard(operand)
        assert _protected_zones.glob_reach(operand, entry, is_file=is_file) == reach, key

    def test_a_literal_operand_is_never_asked(self, tree: Path, monkeypatch) -> None:
        """The read costs one scan on a literal operand: the verdict asks the
        comparator only past ``has_wildcard`` (the assign's no-weight rule)."""
        def boom(*_a, **_k):
            raise AssertionError("the comparator was asked about a literal operand")

        monkeypatch.setattr(write_guard, "_glob_reaches_protected", boom)
        for effect in ("delete", "move", "sweep", "clean"):
            assert write_guard._mutated_zone(effect, "build/out/app.js", tree) is False

    @pytest.mark.parametrize("remainder", ["build", "Build", "*.pyc", "*/x.txt"])
    def test_a_remainder_names_only_what_the_tree_holds(self, tree: Path, remainder: str) -> None:
        """A glob names nothing absent: a root `*/<remainder>` reaches inside
        `cc/` only once something there fits it, spelled as the operand spells
        it, and content the command would create first is not the harness's."""
        operand = "./*/" + remainder
        assert _protected_zones.glob_reaches_protected(operand, tree) == ("", "")
        made = {"build": "build", "Build": "Build", "*.pyc": "x.pyc", "*/x.txt": "sub/x.txt"}[remainder]
        target = tree / "cc" / made
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        assert _protected_zones.glob_reaches_protected(operand, tree) == ("names", "cc/")

    def test_globstar_in_a_remainder_is_a_star(self, tree: Path) -> None:
        """The shells read `**` as `*` (Bash's globstar is off by default), so
        a remainder's glob does not reach two levels down where pathlib's
        would."""
        (tree / "cc" / "a" / "b").mkdir(parents=True)
        (tree / "cc" / "a" / "b" / "x.txt").write_text("x", encoding="utf-8")
        assert _protected_zones.glob_reaches_protected("*/**/x.txt", tree)[0] == ""
        assert _protected_zones.glob_reaches_protected("*/**/*/x.txt", tree)[0] == "names"

    def test_the_remainder_is_read_in_the_checkout_the_operand_is_in(self, tree: Path, tmp_path: Path) -> None:
        """A path into a sibling worktree is relative to that checkout: its
        remainder is read there, never in the session's own root (both
        reviews of 8fb44800)."""
        other = tmp_path / "other"
        (other / "cc" / "build").mkdir(parents=True)
        assert _protected_zones.glob_reaches_protected("*/build", tree)[0] == ""
        assert _protected_zones.glob_reaches_protected("*/build", tree, tree=other)[0] == "names"
        assert write_guard._mutated_zone("delete", "*/build", tree, other) is True
        assert write_guard._mutated_zone("delete", "*/build", tree) is False


class TestTheVerdictByEffect:
    """Names refuses every effect; encloses only the effects that take a tree."""

    @pytest.mark.parametrize(("effect", "refused"), [
        ("delete", True), ("move", True), ("clean", True), ("sweep", False)])
    def test_an_enclosing_glob(self, tree: Path, effect: str, refused: bool) -> None:
        assert write_guard._mutated_zone(effect, "too*", tree) is refused

    @pytest.mark.parametrize("effect", ["delete", "move", "clean", "sweep"])
    def test_a_naming_glob(self, tree: Path, effect: str) -> None:
        assert write_guard._mutated_zone(effect, "tools/*", tree) is True


def _reached_entries() -> list[str]:
    """The roster an adopter tree protects, read as the guard reads it (the
    module's ``PROTECTED_PREFIXES`` also lists `espalier/`, operative on the
    self-host tree alone)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
        prefixes = _hook_utils.harness_protected_prefixes(Path(empty))
    return sorted({*prefixes, *_protected_zones.PROTECTED_FILES})


class TestTheFoldAndTheComparatorAgree:
    """Every protected entry, with any one letter of any component read as
    `?`, is refused as the entry itself is: the comparator folds a segment as
    ``_is_protected`` folds the path, or this reds."""

    @pytest.mark.parametrize("entry", _reached_entries())
    def test_one_letter_as_a_question_mark(self, tree: Path, entry: str) -> None:
        spelled = entry.rstrip("/")
        missed = []
        for i, ch in enumerate(spelled):
            if ch in "/.":
                continue
            variant = spelled[:i] + "?" + spelled[i + 1:]
            if not write_guard._mutated_zone("delete", variant, tree):
                missed.append(i)
        assert missed == [], entry


#: The remove and move verbs both zone loops consume, one template each, the
#: operand bare (a quoted glob is literal in Bash).
_VERBS = {
    "bash-recursive-remove": ("check_bash_for_protected_mutations", "rm -r {}"),
    "bash-move": ("check_bash_for_protected_mutations", "mv {} /tmp/t"),
    "bash-git-remove": ("check_bash_for_protected_mutations", "git rm -r {}"),
    "ps-recursive-remove": ("check_powershell_for_protected_mutations", "Remove-Item -Recurse {}"),
    "ps-move": ("check_powershell_for_protected_mutations", "Move-Item {} t"),
}


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


class TestBothZoneChecksReadAWildcardOperand:
    """The live roster crossed with the verbs both zone loops consume."""

    @pytest.mark.parametrize(("verb", "entry", "shape"), _cases())
    def test_a_wildcard_reaching_a_zone_draws_the_zone_deny(self, tree: Path, verb, entry, shape) -> None:
        check, template = _VERBS[verb]
        assert _zone_reason(check, template.format(shape), tree), (verb, entry, shape)

    @pytest.mark.parametrize(("verb", "entry", "shape"), _cases())
    def test_the_same_shape_below_an_unprotected_directory_is_allowed(self, tree: Path, verb, entry, shape) -> None:
        check, template = _VERBS[verb]
        assert _zone_reason(check, template.format("build/" + shape), tree) == "", (verb, entry, shape)

    @pytest.mark.parametrize("verb", sorted(_VERBS))
    def test_a_pattern_no_zone_name_fits_is_allowed_beside_the_zone(self, tree: Path, verb) -> None:
        """The friction the row declared, gone: `tools/*.log` names no
        protected entry, so it is judged as what it names."""
        check, template = _VERBS[verb]
        shapes = _beside_shapes(tree)
        assert "tools/*.log" in shapes and "*.log" in shapes, shapes
        assert [s for s in shapes if _zone_reason(check, template.format(s), tree)] == [], verb


class TestTheDenyTextReadsTheGlobAsItsLiteralTwin:
    def test_an_enclosing_glob_names_the_ground(self, tree: Path) -> None:
        """DEF-5012's text for a glob above harness ground, as for its literal
        twin, with what the glob reached in its path slot: the deny names the
        ground, never the relaunch."""
        check, template = _VERBS["bash-recursive-remove"]
        glob = _zone_reason(check, template.format("too*"), tree)
        literal = _zone_reason(check, template.format("tools"), tree)
        assert "(a wildcard that reaches `tools/cc/`)" in glob
        assert glob.replace(" (a wildcard that reaches `tools/cc/`)", "").replace("too*", "tools") == literal
        assert "`tools/cc/` is inside it" in glob

    def test_a_glob_reaching_inside_a_zone_names_what_it_reached(self, tree: Path) -> None:
        (tree / "cc" / "build").mkdir()
        check, template = _VERBS["ps-recursive-remove"]
        assert "a wildcard that reaches `cc/`" in _zone_reason(check, template.format("*/build"), tree)

    def test_an_adopter_zone_keeps_its_own_text(self, tree: Path) -> None:
        """A glob reaching only the adopter's `protected_paths` zone reads that
        zone's text, never the harness relaunch, though a harness entry fits
        the same pattern where the tree holds nothing (code review of
        8fb44800)."""
        (tree / "espalier.toml").write_text('protected_paths = ["data/"]\n', encoding="utf-8")
        (tree / "data" / "raw").mkdir(parents=True)
        assert write_guard._zone_reading("*/raw", tree)[0] == ("data/", "protected")
        check, template = _VERBS["bash-recursive-remove"]
        assert "protected_paths" in _zone_reason(check, template.format("*/raw"), tree)


_BASH = "check_bash_for_protected_mutations"
_PS = "check_powershell_for_protected_mutations"


class TestANonRecursiveRemoveReachesFilesOnly:
    """A remove that cannot take a directory reads its wildcard against the
    protected FILES alone (air's ruling 1f2d12 on DEF-3010): `rm` without a
    recursive flag refuses a directory, and a cmdlet without `-Recurse` on one
    with children prompts and aborts with no terminal. So the non-recursive
    root `rm -f *` stays the silent pair the operator settled (the three rows
    in test_write_guard.py the first cut turned red), while a move -- which
    takes directories -- and every remove that can recurse read every entry."""

    @pytest.mark.parametrize(("check", "command"), [
        (_BASH, "rm -f *"), (_BASH, "rm *"), (_BASH, 'for f in *; do rm -f "$f"; done'),
        (_BASH, "rm -f tools/*"), (_BASH, "unlink too*"), (_BASH, "/bin/rm -f *"),
        (_BASH, "(rm -f *)"), (_BASH, "true;rm -f *"),   # a separator glued to the verb
        (_BASH, "{ rm -f *; }"), (_BASH, 'for d in tools/*; do sudo rm -f "$d"; done'),
        (_PS, "Remove-Item *"), (_PS, "Remove-Item -Path tools/* -Force"), (_PS, "del *"),
    ])
    def test_the_settled_silent_pair_stays_silent(self, tree: Path, check: str, command: str) -> None:
        assert _zone_reason(check, command, tree) == "", command

    @pytest.mark.parametrize(("check", "command"), [
        (_BASH, "rm -f .claude/*"),                     # names a protected file
        (_BASH, "rm -r *"), (_BASH, "rm -rf tools/*"),  # recursing
        (_BASH, "rm -f *; rm -r *"),                    # the same word, also recursing
        (_BASH, "rm -f *; rmdir *"),                    # rmdir takes an empty directory
        (_BASH, 'sh -c "rm -f *"'),                     # a nested program: not counted, fails closed
        (_BASH, 'for f in *; do rm -r "$f"; done'),
        (_BASH, "mv * /tmp/t"),                         # a move takes directories (the ruling's edge 1)
        (_BASH, "rm -d *"), (_BASH, "rm --dir *"),      # `-d` takes an empty directory
        (_BASH, 'for d in tools/*; do rm -f "$d"; rm -rf "$d"; done'),     # a decoy before the recursion
        (_BASH, 'for d in tools/*; do rm -f "$d" && mv "$d" /tmp/x; done'),
        (_BASH, "rm $FLAGS *"), (_PS, "Remove-Item @p *"),   # flags the reader cannot see
        (_PS, "Remove-Item .claude/*"), (_PS, "Remove-Item -Recurse *"), (_PS, "Move-Item * t"),
        (_PS, "Remove-Item -Path * -Force; Remove-Item -Path * -Recurse"),   # the Bash mixed row's twin
    ])
    def test_a_remove_that_can_take_a_directory_or_a_file_still_draws_the_deny(
        self, tree: Path, check: str, command: str,
    ) -> None:
        assert _zone_reason(check, command, tree), command

    @pytest.mark.parametrize(("check", "command"), [(_BASH, "rm -f *"), (_PS, "Remove-Item *")])
    def test_a_root_protected_paths_file_keeps_the_deny(self, tree: Path, check: str, command: str) -> None:
        """The ruling's edge 2: an adopter's `protected_paths` entry arrives
        as a prefix with a slash; where the tree holds a FILE there, a root
        glob a non-recursive remove takes names it and is refused."""
        (tree / "espalier.toml").write_text('protected_paths = ["secret.cfg"]\n', encoding="utf-8")
        (tree / "secret.cfg").write_text("x", encoding="utf-8")
        reason = _zone_reason(check, command, tree)
        assert "secret.cfg" in reason and "protected_paths" in reason, reason

    @pytest.mark.parametrize("entry", [e for e in _reached_entries() if e.endswith("/")])
    @pytest.mark.parametrize("check", [_BASH, _PS])
    def test_a_glob_into_a_protected_directory_draws_the_deny(self, tree: Path, check: str, entry: str) -> None:
        """What the first cut of the files-only read dropped (the failure-mode
        review of 2270fd4a): such a remove leaves a directory but takes the
        files in it, so a glob reaching INSIDE a protected directory is
        refused. Each directory on the live roster, a file put inside it, one
        letter of its last component a `?`, then `/*`."""
        (tree / entry / "f.txt").parent.mkdir(parents=True, exist_ok=True)
        (tree / entry / "f.txt").write_text("x", encoding="utf-8")
        spelled = entry.rstrip("/")
        glob = spelled[:-1] + "?/*"
        verb = "rm -f " if check == _BASH else "Remove-Item "
        assert _zone_reason(check, verb + glob, tree), (check, glob)

    @pytest.mark.parametrize(("check", "command"), [
        (_BASH, "rm -f tools/*/hooks/*.py"), (_PS, "Remove-Item tools/*/hooks/*.py")])
    def test_a_glob_at_the_hook_scripts_draws_the_deny(self, tree: Path, check: str, command: str) -> None:
        """The code review's BLOCK on 2270fd4a: the hook scripts themselves,
        the anti-self-disable floor, reached two levels in."""
        (tree / "tools" / "cc" / "hooks" / "write_guard.py").write_text("x", encoding="utf-8")
        assert _zone_reason(check, command, tree), command

    @pytest.mark.parametrize(("check", "command"), [
        (_BASH, "rm -f dat?/*"), (_BASH, "rm -f */raw.csv"), (_PS, "Remove-Item dat?/*")])
    def test_a_glob_into_an_adopter_directory_draws_its_own_deny(self, tree: Path, check: str, command: str) -> None:
        (tree / "espalier.toml").write_text('protected_paths = ["data/"]\n', encoding="utf-8")
        (tree / "data").mkdir()
        (tree / "data" / "raw.csv").write_text("x", encoding="utf-8")
        reason = _zone_reason(check, command, tree)
        assert "protected_paths" in reason, (command, reason)

    def test_an_absent_adopter_entry_is_not_read_as_a_file(self, tree: Path) -> None:
        """A declared entry the tree does not hold names nothing: the root
        glob runs (the failure-mode review's absent-entry row)."""
        (tree / "espalier.toml").write_text('protected_paths = ["data/"]\n', encoding="utf-8")
        assert _zone_reason(_BASH, "rm -f *", tree) == ""

    def test_a_protected_paths_directory_is_a_directory(self, tree: Path) -> None:
        """Its twin: where the tree holds a directory at the entry, the
        non-recursive remove cannot take it, so the root glob runs."""
        (tree / "espalier.toml").write_text('protected_paths = ["keep/"]\n', encoding="utf-8")
        (tree / "keep").mkdir()
        assert _zone_reason(_BASH, "rm -f *", tree) == ""
        assert _zone_reason(_BASH, "rm -r *", tree)

    @pytest.mark.parametrize("check", [_BASH, _PS])
    def test_an_allowed_literal_operand_is_never_read_for_it(self, tree: Path, monkeypatch, check: str) -> None:
        """The files-only read is asked on a wildcard operand, or on a literal
        one the zone loop would refuse (DEF-4031, the next class): an allowed
        literal never pays for it (the assign's no-weight rule)."""
        import _bash_patterns

        def boom(*_a, **_k):
            raise AssertionError("the files-only read was asked about an allowed literal operand")

        monkeypatch.setattr(_bash_patterns, "files_only_removed_operands", boom)
        verb = "rm -f" if check == _BASH else "Remove-Item"
        assert _zone_reason(check, verb + " build/out.txt", tree) == ""


#: DEF-4031: the lone PowerShell deletes that cannot take a directory, each on
#: ``write_guard._LONE_DELETE_VERBS`` and ``_LONE_DELETE_FLAGS`` (air's ruling
#: 843d54). A remove cmdlet without its recurse switch fails on the
#: has-children prompt the non-interactive tool host cannot show (driven on
#: Windows PowerShell 5.1, 2026-10-17, and pwsh 7.6.5 on macOS, 2026-11-09),
#: and removes an EMPTY directory (5.1 and pwsh 7.6.5), so the relief needs a
#: directory holding an entry.
_FILE_ONLY_VERBS = [
    "Remove-Item", "Remove-Item -Force", "Remove-Item -LiteralPath", "Remove-Item -Path", "ri",
    "Remove-Item -Force -Confirm:$false", "Remove-Item -WhatIf", "Remove-Item -Confirm", "REMOVE-ITEM -force",
]
#: The Bash `rm` spellings that cannot take a directory as written. They keep
#: main's deny: the Bash tool replays the operator's rc aliases, so a bare `rm`
#: may be recursive or a move to the trash (ruling 267ffc; docs/HOOKS.md).
_BARE_RM = ["rm -f", "rm", "rm -fv", "rm -i", "rm --force", "rm --verbose", "rm --"]
#: The deletes that can take a directory, those whose flags the reader cannot
#: see, and every verb or flag off the allowlist: each keeps the deny.
_DIRECTORY_VERBS = {
    _BASH: ["rm -r", "rm -R", "rm -rf", "rm -d", "rm --dir", "rm --di", "rmdir", 'rm "-d"', "rm \\-d", "unlink"],
    _PS: ["Remove-Item -Recurse", "Remove-Item -r", "Remove-Item -Force:$v", "Remove-Item @p", "del", "rd",
          "rmdir", "erase", "Remove-Item \u2013Recurse", "Remove-Item \u2014Recurse", "Remove-Item \u2015Recurse",
          "Remove-Item -Path:", "Remove-Item `-Recurse"],
}
#: PowerShell commands where the delete is not the only statement, or its
#: recurse switch trails the operand (air's must-deny rows, note ab1566):
#: each keeps the deny on a full directory.
_NOT_ALONE = [
    "Remove-Item tools -Recurse", "$PSDefaultParameterValues['Remove-Item:Recurse']=$true; Remove-Item tools",
    "function Remove-Item { Microsoft.PowerShell.Management\\Remove-Item -Recurse @args }; Remove-Item tools",
    "Set-Alias ri rd; ri tools", "Remove-Item tools; Remove-Item -Recurse tools", "Remove-Item tools, build",
    "Remove-Item (Join-Path . tools)", "Remove-Item tools\\cc", "cd .; Remove-Item tools",
]
#: Left out, since main allows them too, so they are not this row's polarity:
#: an operand fed by a pipe (`'tools' | Remove-Item`) or a substitution, and
#: a flag that takes a value (`-Filter tools`, `-Include tools`).
#: The fixture's governed directories that hold an entry, and the empty ones.
_FULL_DIRS = ["tools", "tools/cc"]
_EMPTY_DIRS = ["cc", "tools/cc/hooks"]


def _spellings(directory: str) -> list[str]:
    """One directory as typed, dot-led and with a trailing separator."""
    return [directory, "./" + directory, directory + "/"]


def _compose(verbs: list[str], dirs: list[str]) -> list[str]:
    return [v + " " + s for v in verbs for d in dirs for s in _spellings(d)]


class TestADeleteThatCannotTakeADirectoryLeavesTheZone:
    """DEF-4031: on the PowerShell tool, a remove cmdlet that is the command's
    only statement, carries only allowlisted flags and has no recurse switch,
    naming a governed directory that holds an entry, removes nothing, so the
    zone check does not refuse it. The read is
    ``write_guard._a_lone_file_delete``: the relative operand as typed, joined
    to the directory the command runs in, by lstat and one scandir, and the
    path the zone check resolved. Everything else keeps main's deny (the row's
    polarity, air's ruling 843d54): an empty directory, a link, a junction, a
    file, a missing operand, a climb, an absolute spelling, any verb or flag
    off the allowlist, and any command with a second statement, a definition
    or an expansion. On the Bash tool every `rm` naming a governed directory
    keeps the deny: the tool replays rc aliases (ruling 267ffc)."""

    @pytest.mark.parametrize("command", _compose(_FILE_ONLY_VERBS, _FULL_DIRS))
    def test_it_is_allowed(self, tree: Path, command: str) -> None:
        assert _zone_reason(_PS, command, tree) == "", command

    @pytest.mark.parametrize("command", _compose(_FILE_ONLY_VERBS, _EMPTY_DIRS))
    def test_an_empty_directory_keeps_the_deny(self, tree: Path, command: str) -> None:
        """A cmdlet removes an empty directory (ruling 843d54, point 3)."""
        assert _zone_reason(_PS, command, tree), command

    @pytest.mark.parametrize("command", _compose(_BARE_RM, _FULL_DIRS + _EMPTY_DIRS))
    def test_a_bare_rm_keeps_the_deny_on_bash(self, tree: Path, command: str) -> None:
        """The declared limit: an rc alias can make a bare `rm` recursive, and
        main's zone deny holds whatever `rm` expands to."""
        assert _zone_reason(_BASH, command, tree), command

    @pytest.mark.parametrize(("check", "command"), [
        (c, x) for c, verbs in _DIRECTORY_VERBS.items() for x in _compose(verbs, _FULL_DIRS + _EMPTY_DIRS)])
    def test_a_delete_off_the_allowlist_keeps_the_deny(self, tree: Path, check: str, command: str) -> None:
        assert _zone_reason(check, command, tree), command

    @pytest.mark.parametrize("command", _NOT_ALONE)
    def test_a_delete_that_is_not_alone_keeps_the_deny(self, tree: Path, command: str) -> None:
        assert _zone_reason(_PS, command, tree), command

    @pytest.mark.parametrize("command", [
        "Remove-Item cc/d-confirm:$false", "Remove-Item -Force\x0btools", "Remove-Item tools\x0b",
        "Remove-Item tools\x0c", "Remove-Item tools\x1f", "Remove-Item tools -Confirm:$false-Recurse",
    ])
    def test_a_word_the_shell_reads_otherwise_keeps_the_deny(self, tree: Path, command: str) -> None:
        """The code review's shapes: a separator Python splits on and the shell
        does not, and `-Confirm:$false` inside a word. (A separator inside the
        command, `Remove-Item<VT>tools`, yields no zone operand on main either,
        so it is not this row's.)"""
        assert _zone_reason(_PS, command, tree), ascii(command)

    def test_an_absolute_operand_keeps_the_deny(self, tree: Path) -> None:
        """An absolute spelling can name another directory than the one the
        zone check resolved (the failure-mode review), so the relief reads a
        relative operand alone."""
        operand = str(tree / "tools").replace("\\", "/")
        assert _zone_reason(_PS, "Remove-Item " + operand, tree), operand

    def test_the_read_is_of_the_directory_the_zone_check_resolved(self, tree: Path) -> None:
        read = write_guard._a_lone_file_delete
        assert read("Remove-Item tools", "tools", tree, tree, tree / "tools")
        assert not read("Remove-Item tools", "tools", tree, tree, tree / "build")

    def test_every_allowlisted_word_is_spelled_in_the_allowed_roster(self) -> None:
        """A word added to the allowlist lands with an allow row here, so each
        word the relief accepts is driven, never only listed."""
        words = {w.lower() for spelling in _FILE_ONLY_VERBS for w in spelling.split()}
        listed = write_guard._LONE_DELETE_VERBS | write_guard._LONE_DELETE_FLAGS
        assert listed <= words, sorted(listed - words)

    @pytest.mark.parametrize("check", [_BASH, _PS])
    @pytest.mark.parametrize("operand", [".claude/settings.json", "tools/cc/gone", "tools/cc/../cc", "tools/../tools"])
    def test_a_file_a_missing_operand_or_a_climb_keeps_the_deny(self, tree: Path, check: str, operand: str) -> None:
        for verb in _FILE_ONLY_VERBS if check == _PS else _BARE_RM:
            assert _zone_reason(check, verb + " " + operand, tree), verb + " " + operand

    def test_the_operand_is_read_from_the_directory_the_command_runs_in(self, tree: Path) -> None:
        """`cc` below `tools` holds an entry; `cc` at the root is empty."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            write_guard.check_powershell_for_protected_mutations("Remove-Item cc", tree, tree / "tools")
        assert out.getvalue().strip() == ""
        assert _zone_reason(_PS, "Remove-Item cc", tree)

    def test_a_directory_whose_only_entry_is_hidden_is_allowed(self, tree: Path) -> None:
        """5.1 kept a directory whose only child is hidden (driven
        2026-11-09), so any entry counts."""
        (tree / "cc" / ".keep").write_text("", encoding="utf-8")
        assert _zone_reason(_PS, "Remove-Item cc", tree) == ""

    def test_a_link_to_the_directory_keeps_the_deny(self, tree: Path) -> None:
        """A link to a directory is itself removed (5.1, 2026-11-09), so the
        read is the operand's own, by lstat, never its target's, with or
        without a trailing separator."""
        try:
            (tree / "tools" / "lnk").symlink_to(tree / "tools" / "cc", target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"no symlink on this host: {exc}")
        for operand in ("tools/lnk", "tools/lnk/"):
            assert _zone_reason(_PS, "Remove-Item " + operand, tree), operand

    @pytest.mark.skipif(os.name != "nt", reason="a junction is a Windows reparse point")
    def test_a_junction_to_the_directory_keeps_the_deny(self, tree: Path) -> None:
        import _winapi

        _winapi.CreateJunction(str(tree / "tools" / "cc"), str(tree / "tools" / "jct"))
        for operand in ("tools/jct", "tools/jct/"):
            assert _zone_reason(_PS, "Remove-Item " + operand, tree), operand

    @pytest.mark.parametrize("check", [_BASH, _PS])
    def test_a_directory_beside_the_zone_needs_no_read(self, tree: Path, check: str, monkeypatch) -> None:
        def boom(*_a, **_k):
            raise AssertionError("the directory was read for an allowed operand")

        monkeypatch.setattr(write_guard, "_a_lone_file_delete", boom, raising=False)
        verb = "Remove-Item" if check == _PS else "rm -f"
        assert _zone_reason(check, verb + " build", tree) == ""
