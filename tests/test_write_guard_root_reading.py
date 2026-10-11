"""How the guard reads a removal's ROOT on the Windows-facing tools.

The friction guard (a workflow toolbelt, not a security boundary --
docs/STANDING_PRINCIPLES.md principle 2) judges a recursive removal by the
directory it starts from: the wall when that is the checkout, the zone deny
when it is a protected harness directory, the nudge for any other un-narrowed
directory off the build-output roster. A root read with a stray character on
it encloses nothing, so all three go quiet together. The rows below compose
each spelling with all three tiers, and every command is handed to the
in-process classifier against a ``tmp_path`` root -- nothing here is run on a
shell (docs/CLASSIFIER_FALSE_POSITIVES.md).

DEF-1170: on the PowerShell tool a listing grouped in parentheses, a
subexpression or an array subexpression -- the idiom that finishes the
enumeration before the remove starts -- kept the group's closer on a root
that was the last word inside the group.
"""
# pytest-marker: default-unit  (in-process classifier calls against tmp_path;
# no subprocess, nothing executed)
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _bash_patterns  # noqa: E402
import _speedbump  # noqa: E402
import write_guard  # noqa: E402

#: The plain spelling first (the control every grouped row is compared
#: with), then the three PowerShell group shapes.
_GROUPS = ("{}", "({})", "$({})", "@({})")
_GROUPED = _GROUPS[1:]


def _piped(group: str, root: str, listing: str = "Get-ChildItem -Recurse") -> str:
    """A recursive listing of ``root`` in ``group``, piped into a recursive remove."""
    return group.format(f"{listing} {root}") + " | Remove-Item -Recurse -Force"


def _zone_denies(command: str, root: Path) -> bool:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = write_guard.check_powershell_for_protected_mutations(command, root, root)
    return bool(code) or "deny" in out.getvalue()


def _nudges(command: str, root: Path) -> bool:
    return _speedbump._pred_rmrf("PowerShell", {"command": command}, root)


class TestGroupedListingRoot:
    """DEF-1170: the cmdlet listing's root, last inside a group."""

    @pytest.mark.parametrize("group", _GROUPS)
    def test_the_wall_reads_the_checkout_inside_a_group(self, tmp_path, group):
        cmd = _piped(group, ".")
        assert _bash_patterns.has_catastrophic_ps_sweep(cmd, str(tmp_path), cwd=tmp_path), cmd

    # `cc\` is the spelling tab completion types for a directory: the
    # backslash is a separator on this tool, so the closer after it is
    # still the group's.
    @pytest.mark.parametrize("spelled", ["cc", "cc\\", ".\\cc"])
    @pytest.mark.parametrize("group", _GROUPS)
    def test_the_zone_deny_reads_a_protected_directory_inside_a_group(self, tmp_path, group, spelled):
        (tmp_path / "cc").mkdir()
        cmd = _piped(group, spelled)
        assert _zone_denies(cmd, tmp_path), cmd

    @pytest.mark.parametrize("group", _GROUPS)
    def test_a_build_directory_inside_a_group_draws_no_nudge(self, tmp_path, group):
        # the friction direction: a suffixed name is off the roster
        cmd = _piped(group, "build")
        assert not _nudges(cmd, tmp_path), cmd

    @pytest.mark.parametrize("group", _GROUPS)
    def test_a_source_directory_inside_a_group_still_draws_the_nudge(self, tmp_path, group):
        cmd = _piped(group, "src")
        assert _nudges(cmd, tmp_path), cmd

    @pytest.mark.parametrize("group", _GROUPED)
    def test_a_narrowed_listing_inside_a_group_is_not_the_wall(self, tmp_path, group):
        cmd = _piped(group, ".", listing="Get-ChildItem -Recurse -Filter *.log")
        assert not _bash_patterns.has_catastrophic_ps_sweep(cmd, str(tmp_path), cwd=tmp_path), cmd

    @pytest.mark.parametrize("group", _GROUPED)
    def test_a_switch_after_the_root_inside_a_group_reads_the_same(self, tmp_path, group):
        # the closer abuts the switch, never the root: the reading the fix
        # must leave as it was
        cmd = group.format("Get-ChildItem . -Recurse") + " | Remove-Item -Recurse -Force"
        assert _bash_patterns.has_catastrophic_ps_sweep(cmd, str(tmp_path), cwd=tmp_path), cmd


class TestGroupedNativeListingRoot:
    """The native listings the PowerShell reader hands to the Bash readers
    (`git ls-files`, a `find` head): the same group, the same root."""

    @pytest.mark.parametrize("spelled", ["cc", "cc\\"])
    @pytest.mark.parametrize("group", _GROUPED)
    def test_the_zone_deny_reads_a_tracked_listing_root_inside_a_group(self, tmp_path, group, spelled):
        (tmp_path / "cc").mkdir()
        cmd = group.format(f"git ls-files {spelled}") + " | Remove-Item -Force"
        assert _zone_denies(cmd, tmp_path), cmd


class TestGroupedDirectRemoveRoot:
    """A remove verb whose own target is last inside a group."""

    @pytest.mark.parametrize("group", _GROUPS)
    def test_the_wall_reads_the_checkout_inside_a_group(self, tmp_path, group):
        cmd = group.format("Remove-Item -Recurse -Force .")
        assert _bash_patterns.powershell_removal_lands_catastrophic(cmd, str(tmp_path), tmp_path), cmd

    @pytest.mark.parametrize("spelled", ["cc", "cc\\"])
    @pytest.mark.parametrize("group", _GROUPS)
    def test_the_zone_deny_reads_a_protected_directory_inside_a_group(self, tmp_path, group, spelled):
        (tmp_path / "cc").mkdir()
        cmd = group.format(f"Remove-Item -Recurse -Force {spelled}")
        assert _zone_denies(cmd, tmp_path), cmd


class TestDriveLetterBinding:
    """DEF-1173: on the Bash tool a drive-qualified path bound to a variable
    without quotes (bash takes it as one word) must bind whole, as the quoted
    binding does. The plain-word value class held no colon, so the walls read
    the name as unbound and every other reader bound the drive letter alone.

    The tier rows bind the targets by their own `as_posix()` spelling: on a
    Windows host that carries the drive colon and the unquoted rows earned
    the red there; on a POSIX host the spelling has no colon and the rows pin
    that the three binding styles read alike. The expander rows spell a drive
    path outright and hold on every host."""

    _STYLES = ("{}", '"{}"', "'{}'")

    @pytest.mark.parametrize("wall", [True, False])
    @pytest.mark.parametrize("value", ["C:/fixture/repo", "c:/fixture", "D:/x/y"])
    def test_the_expander_inlines_an_unquoted_drive_path_whole(self, value, wall):
        cmd = f'd={value}; rm -rf "$d"'
        assert _bash_patterns._expand_simple_var_assignments(cmd, wall=wall).endswith(f'"{value}"'), cmd

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        scratch, repo = tmp_path / "scratch", tmp_path / "repo"
        for d in (scratch / "sp", repo / "cc"):
            d.mkdir(parents=True)
        for var in ("TEMP", "TMP", "TMPDIR"):
            monkeypatch.setenv(var, str(scratch))
        return repo, scratch

    @staticmethod
    def _bound(style: str, target: Path, ref: str) -> str:
        return f"d={style.format(target.as_posix())}; rm -rf {ref}"

    @pytest.mark.parametrize("ref", ['"$d"', "$d"])
    @pytest.mark.parametrize("style", _STYLES)
    def test_the_wall_reads_the_checkout_through_the_binding(self, env, style, ref):
        repo, _scratch = env
        cmd = self._bound(style, repo, ref)
        assert _bash_patterns.has_catastrophic_recursive_rm(cmd, str(repo), cwd=repo), cmd

    @pytest.mark.parametrize("ref", ['"$d"', "$d"])
    @pytest.mark.parametrize("style", _STYLES)
    def test_the_zone_deny_reads_a_protected_directory_through_the_binding(self, env, style, ref):
        repo, _scratch = env
        cmd = self._bound(style, repo / "cc", ref)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = write_guard.check_bash_for_protected_mutations(cmd, repo, repo)
        assert code or "deny" in out.getvalue(), cmd

    @pytest.mark.parametrize("ref", ['"$d"', "$d"])
    @pytest.mark.parametrize("style", _STYLES)
    def test_scratch_below_the_temp_root_passes_through_the_binding(self, env, style, ref):
        repo, scratch = env
        cmd = self._bound(style, scratch / "sp", ref)
        assert not _speedbump._pred_rmrf("Bash", {"command": cmd}, repo), cmd
        assert not _bash_patterns.has_catastrophic_recursive_rm(cmd, str(repo), cwd=repo), cmd


class TestFindRootGrammar:
    """`_find_delete_roots` read by the tool's own grammar: on PowerShell a
    backslash is a separator, never an escape, so the closer after a root's
    trailing separator is cut (DEF-1170's find-family sibling; the row drove
    no wrong verdict here, so this pins the reading, not a tier)."""

    def test_the_powershell_grammar_cuts_the_closer_after_a_trailing_separator(self):
        assert _bash_patterns._find_delete_roots("cc\\) -delete", powershell=True)[0] == ["cc\\"]

    def test_the_bash_grammar_keeps_an_escaped_closer(self):
        assert _bash_patterns._find_delete_roots("cc\\) -delete")[0] == ["cc\\)"]
