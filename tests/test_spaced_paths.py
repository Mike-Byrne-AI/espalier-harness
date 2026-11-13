"""``tests/_spaced_paths.py``: a fixture's temp path quoted for its shell only
when spaced, driven on a path that holds a space on EVERY host and read back
through the real shells (DEF-5082's quoter; the fixtures it fills are the
guard's, the differential's and the worktree rows')."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._pwsh_cache import private_cache_env
from tests._spaced_paths import CMD, PS, SH, fill, quoted, skip_unless_plain, spaced

# slow-exempt: five sub-second bash and pwsh reads of a filled word, 1.7 s for the module on the Air, measured 2026-11-04

SPACED = "/x/axis basetemp/t/repo"
PLAIN = "/x/axis-basetemp/t/repo"


class TestQuotedOnlyWhenSpaced:
    @pytest.mark.parametrize("shell", [SH, PS, CMD])
    def test_a_plain_word_keeps_its_bytes_on_every_shell(self, shell):
        for word in (PLAIN, PLAIN + "/*", "~/*", "$HOME", "build", "C:/Windows/System32"):
            assert quoted(word, shell) == word

    @pytest.mark.parametrize("shell", [PS, CMD])
    def test_powershell_and_cmd_take_the_whole_word_wildcard_inside(self, shell):
        assert quoted(SPACED, shell) == f'"{SPACED}"'
        assert quoted(SPACED + "/*", shell) == f'"{SPACED}/*"'
        assert quoted(SPACED + "/sub/x", shell) == f'"{SPACED}/sub/x"'

    def test_bash_leaves_the_glob_tail_outside_the_quotes(self):
        assert quoted(SPACED + "/*", SH) == f'"{SPACED}"/*'
        assert quoted(SPACED + "/*.o", SH) == f'"{SPACED}"/*.o'
        assert quoted(SPACED + "/x/**", SH) == f'"{SPACED}/x"/**'
        assert quoted(SPACED + "/sub/x", SH) == f'"{SPACED}/sub/x"'
        assert quoted(SPACED, SH) == f'"{SPACED}"'

    def test_spaced_reads_any_whitespace(self):
        assert spaced(Path(SPACED)) and spaced("a\tb") and not spaced(Path(PLAIN))


class TestFill:
    def test_a_plain_path_fills_every_template_byte_for_byte(self):
        for template in ("rm -rf {t}", "cd {t} && echo x > {t}/tools/cc/hooks/f.py",
                         "Remove-Item -Recurse -Force {t}, build", "'{t}/a,b'", '"src, {t}/x"',
                         "Start-Process cmd -ArgumentList '/c rd /s /q {t}'"):
            for shell in (SH, PS, CMD):
                assert fill(template, "{t}", PLAIN, shell) == template.replace("{t}", PLAIN)

    def test_the_word_the_placeholder_begins_is_quoted_whole(self):
        assert fill("cd {abs} && echo x > {abs}/tools/cc/hooks/f.py", "{abs}", SPACED) == (
            f'cd "{SPACED}" && echo x > "{SPACED}/tools/cc/hooks/f.py"')
        assert fill("mkdir -p {abs}/nd && cd {abs}/nd; ls", "{abs}", SPACED) == (
            f'mkdir -p "{SPACED}/nd" && cd "{SPACED}/nd"; ls')
        assert fill("Remove-Item -Recurse -Force build, {s}/x", "{s}", SPACED, PS) == (
            f'Remove-Item -Recurse -Force build, "{SPACED}/x"')
        assert fill("if (Test-Path {s}) { Remove-Item -Recurse -Force {s} }", "{s}", SPACED, PS) == (
            f'if (Test-Path "{SPACED}") {{ Remove-Item -Recurse -Force "{SPACED}" }}')

    def test_a_glob_tail_follows_the_shells_rule(self):
        assert fill("rm -rf {t}", "{t}", SPACED + "/*", SH) == f'rm -rf "{SPACED}"/*'
        assert fill("Remove-Item -Recurse {t}", "{t}", SPACED + "/*", PS) == f'Remove-Item -Recurse "{SPACED}/*"'
        assert fill("cmd //c rd /s /q {t}", "{t}", SPACED + "/*", CMD) == f'cmd //c rd /s /q "{SPACED}/*"'

    def test_a_placeholder_the_fixture_quoted_itself_is_filled_bare(self):
        assert fill("'{s}/a,b'", "{s}", SPACED, PS) == f"'{SPACED}/a,b'"
        assert fill('"{s}/x,C:/Windows"', "{s}", SPACED, PS) == f'"{SPACED}/x,C:/Windows"'
        assert fill('"src, {s}/x"', "{s}", SPACED, PS) == f'"src, {SPACED}/x"'
        assert fill('S="{tmp}"; cd "$S"', "{tmp}", SPACED) == f'S="{SPACED}"; cd "$S"'
        assert fill("'build', '{s}/x'", "{s}", SPACED, PS) == f"'build', '{SPACED}/x'"

    def test_inside_a_single_quoted_program_the_word_is_double_quoted(self):
        assert fill("Start-Process cmd -ArgumentList '/c del /s /q {t}'", "{t}", SPACED, PS) == (
            f"Start-Process cmd -ArgumentList '/c del /s /q \"{SPACED}\"'")

    def test_inside_cmds_outer_quotes_the_word_is_quoted_as_if_bare(self):
        # cmd strips the pair that opens right after /c or /k and reads the
        # program inside bare, so that pair quotes nothing (#608's
        # ps-cmd-stopparse-quoted-* rows)
        assert fill('cmd --% /c "rd /s /q {t}"', "{t}", SPACED, CMD) == (
            f'cmd --% /c "rd /s /q "{SPACED}""')
        assert fill('cmd /C "del /s /q {t}/*"', "{t}", SPACED, CMD) == (
            f'cmd /C "del /s /q "{SPACED}/*""')
        assert fill('cmd /r"rd /s /q {t}"', "{t}", SPACED, CMD) == f'cmd /r"rd /s /q "{SPACED}""'
        assert fill('cmd /k "dir {t}"', "{t}", PLAIN, CMD) == f'cmd /k "dir {PLAIN}"'
        # Git Bash's //c text is bash's to unquote first: today's rule
        assert fill('cmd //c "del /s /q {t}"', "{t}", SPACED, CMD) == f'cmd //c "del /s /q {SPACED}"'
        # any other double-quoted string is the fixture's own quoting, and
        # another shell's fill keeps today's rule
        assert fill('cmd /c rd /s /q "{t}"', "{t}", SPACED, CMD) == f'cmd /c rd /s /q "{SPACED}"'
        assert fill('cmd /c echo x "a {t}"', "{t}", SPACED, CMD) == f'cmd /c echo x "a {SPACED}"'
        assert fill('cmd --% /c "rd /s /q {t}"', "{t}", SPACED, PS) == (
            f'cmd --% /c "rd /s /q {SPACED}"')

    def test_every_placeholder_is_filled_and_the_rest_kept(self):
        assert fill("cd / ; ls sub ; cd {abs} ; rm -rf sub", "{abs}", SPACED) == (
            f'cd / ; ls sub ; cd "{SPACED}" ; rm -rf sub')
        assert fill("{t} {t}/*", "{t}", SPACED) == f'"{SPACED}" "{SPACED}"/*'
        assert fill("no placeholder here", "{t}", SPACED) == "no placeholder here"


class TestTheRealShellsReadOneWord:
    """The oracle: each filled form is one word to the shell it is for, and a
    bare spaced path is two. A test fixture is only right when the shell
    reads the quoted text the way the fixture meant it."""

    @pytest.fixture
    def tree(self, tmp_path):
        base = tmp_path / "with space" / "repo"
        base.mkdir(parents=True)
        (base / "f1").write_text("", encoding="utf-8")
        (base / "f2").write_text("", encoding="utf-8")
        return base

    def _bash(self, command: str) -> list[str]:
        if sys.platform == "win32" or not shutil.which("bash"):
            pytest.skip("no POSIX bash on PATH to read the filled text")
        run = subprocess.run(["bash", "-c", command], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30, check=False)
        assert run.returncode == 0, run.stderr
        return run.stdout.splitlines()

    def test_bash_reads_the_filled_path_as_one_word_and_a_bare_one_as_two(self, tree):
        posix = tree.as_posix()
        assert self._bash(fill('printf "%s\\n" {t}', "{t}", posix, SH)) == [posix]
        # one word per blank-free run: two, or more under a root that is itself spaced
        assert len(self._bash(f'printf "%s\\n" {posix}')) == len(posix.split()) >= 2
        assert sorted(self._bash(fill('printf "%s\\n" {t}', "{t}", posix + "/*", SH))) == [
            posix + "/f1", posix + "/f2"]

    def _pwsh(self, command: str) -> list[str]:
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            pytest.skip("no pwsh or powershell on PATH to read the filled text")
        run = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=45, check=False, env=private_cache_env())
        assert run.returncode == 0, run.stderr
        return run.stdout.splitlines()

    def test_powershell_reads_the_filled_path_as_one_word_and_expands_the_wildcard_inside(self, tree):
        posix = tree.as_posix()
        assert self._pwsh(fill("Write-Output {t}", "{t}", posix, PS)) == [posix]
        assert len(self._pwsh(f"Write-Output {posix}")) == len(posix.split()) >= 2
        names = self._pwsh(fill("Get-ChildItem -Path {t} | ForEach-Object Name", "{t}", posix + "/*", PS))
        assert sorted(names) == ["f1", "f2"]

    def test_cmd_reads_the_path_inside_its_outer_quotes_as_one_word(self, tree):
        if sys.platform != "win32":
            pytest.skip("cmd.exe reads the filled text on Windows only")
        # a string argv reaches CreateProcess as typed, so cmd sees the quotes
        run = subprocess.run(fill('cmd /c "dir /b {t}"', "{t}", str(tree), CMD),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30, check=False)
        assert run.returncode == 0, run.stderr
        assert sorted(run.stdout.split()) == ["f1", "f2"]
        # filled bare, as before the rule, the spaced path is two words to dir
        bare = subprocess.run(f'cmd /c "dir /b {tree}"', capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30, check=False)
        assert sorted(bare.stdout.split()) != ["f1", "f2"]


class TestSkipUnlessPlain:
    def test_a_plain_path_passes_and_a_spaced_one_skips_naming_the_row(self):
        skip_unless_plain(Path(PLAIN), "a row")
        with pytest.raises(pytest.skip.Exception) as info:
            skip_unless_plain(Path(SPACED), "the unquoted binding row")
        assert "DEF-5082" in str(info.value) and "the unquoted binding row" in str(info.value)
