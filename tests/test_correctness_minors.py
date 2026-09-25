"""TP-193 R4 correctness minors: charset fail-safety, theater kwargs, CLI exit code.

Each test pins one round-4 survivor against regression: an unknown HTTP charset
must degrade instead of crashing `refresh-externals`; convergence_theater must not
false-flag a kwargs-only difference as a tautology; and `pre-release` on a bad path
must exit 2 cleanly because a raw PosixPath repr at exit 1 is an internal leak.
"""
from __future__ import annotations

# pytest-marker: default-unit  (lightweight minors test; not a grandfather entry)

import argparse
import ast

import os

import pytest

from espalier import external_fetch
from espalier._text import os_error_text, plural, quoted_if_spaced
from espalier.cli import (
    cmd_audit,
    cmd_audit_accuracy,
    cmd_blueprint,
    cmd_clean_generated,
    cmd_diff,
    cmd_fingerprint,
    cmd_freshness_check,
    cmd_freshness_pin,
    cmd_freshness_unpin,
    cmd_install_ci,
    cmd_integrity,
    cmd_merge_settings,
    cmd_pre_release,
    cmd_provenance,
    cmd_recover,
    cmd_refresh_externals,
    cmd_refresh_self_host_pin,
    cmd_reflect,
    cmd_reflect_deep,
    cmd_release_pack,
    cmd_scaffolding_bench,
    cmd_scan,
    cmd_scope_check,
    cmd_self_host,
    cmd_selfcheck,
    cmd_surface_handoff,
    cmd_surface_impact,
    cmd_verify_landing,
    cmd_worktree_plan,
)
from espalier.scanners import convergence_theater as ct


# --- W5-1: external_fetch unknown charset degrades, never raises -------------
class _FakeHeaders:
    def get(self, key, default=""):
        return "text/html; charset=definitely-not-a-real-charset"

    def get_content_charset(self):
        return "definitely-not-a-real-charset"


class _FakeResp:
    status = 200
    url = "https://example.com/x"
    headers = _FakeHeaders()

    def read(self):
        return b"<html>hello world</html>"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_unknown_charset_degrades_to_utf8(monkeypatch):
    # Before the fix raw.decode("<bogus>") raised LookupError, which is NOT in
    # fetch_url's except clauses and escaped uncaught to crash refresh-externals.
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())
    result = external_fetch.fetch_url("https://example.com/x")
    assert result.error is None
    assert "hello world" in result.content


# --- TP-266 Fix 4: a malformed pin URL degrades to a fetch error, never raises -
# A control char / space in the host raises `http.client.InvalidURL` (an
# HTTPException — NOT URLError/OSError) and a bad IPv6 literal raises a bare
# `ValueError`, both while urllib PARSES the URL. Neither was in fetch_url's
# except clauses, so one malformed pin aborted the whole refresh-externals batch
# and cli.main() re-raised InvalidURL as a raw traceback. Both parse-time
# failures happen before any socket, so these tests need no network/monkeypatch.
def test_malformed_url_with_space_degrades_not_raises():
    result = external_fetch.fetch_url("https://exa mple.com/spec", retries=0)
    assert result.error is not None
    assert "malformed URL" in result.error


def test_malformed_ipv6_url_degrades_not_raises():
    result = external_fetch.fetch_url("http://[bad", retries=0)
    assert result.error is not None
    assert "malformed URL" in result.error


# --- W5-2: convergence_theater _same_args is keyword-aware -------------------
def _call(src: str) -> ast.Call:
    return ast.parse(src, mode="eval").body


def test_same_args_distinguishes_keyword_difference():
    # render(d, sort_keys=True) == render(d, sort_keys=False) is NOT a tautology.
    a = _call("render(d, sort_keys=True)")
    b = _call("render(d, sort_keys=False)")
    assert ct._same_args(a, b) is False


def test_same_args_true_for_identical_calls():
    assert ct._same_args(_call("render(d)"), _call("render(d)")) is True
    assert ct._same_args(_call("f(x, k=1)"), _call("f(x, k=1)")) is True


# --- W5-3: pre-release nonexistent path -> clean message + exit 2 -----------
def test_pre_release_nonexistent_path_exits_2_cleanly(tmp_path, capsys):
    args = argparse.Namespace(repo=str(tmp_path / "no-such-repo"))
    rc = cmd_pre_release(args)
    captured = capsys.readouterr()
    assert rc == 2
    assert "does not exist or is not a directory" in captured.err
    assert "PosixPath(" not in (captured.out + captured.err)


# --- TP-244 A: repo-scoped commands precheck the path -> clean msg + exit 2 --
# The shared precondition guard (reused from cmd_strengthen/cmd_pre_release) so a
# typo'd path errors cleanly instead of: install-ci scaffolding a phantom tree at
# exit 0; fingerprint/audit/scan/diff leaking a raw [Errno 2] + resolved PosixPath;
# or reflect/provenance/audit-accuracy/clean-generated false-greening "clean".
# The guard is now consolidated in cli._resolve_repo_arg; scaffolding-bench shares
# install-ci's phantom-tree failure mode, and recover/release-pack complete the set.
@pytest.mark.parametrize(
    "cmd_func",
    [
        cmd_install_ci,
        cmd_fingerprint,
        cmd_audit,
        cmd_scan,
        cmd_diff,
        cmd_reflect,
        cmd_reflect_deep,
        cmd_provenance,
        cmd_audit_accuracy,
        cmd_clean_generated,
        cmd_recover,
        cmd_release_pack,
        cmd_scaffolding_bench,
        # The shared repo-arg guard extended to the rest of the repo-consuming
        # commands: each rejects a nonexistent --repo with the canonical
        # message + exit 2 before touching any other arg.
        cmd_integrity,
        cmd_blueprint,
        cmd_merge_settings,
        cmd_selfcheck,
        cmd_self_host,
        cmd_surface_handoff,
        cmd_worktree_plan,
        cmd_refresh_externals,
        cmd_refresh_self_host_pin,
        cmd_scope_check,
        cmd_surface_impact,
        cmd_verify_landing,
        cmd_freshness_check,
        cmd_freshness_pin,
        cmd_freshness_unpin,
    ],
)
def test_repo_scoped_cmd_nonexistent_path_exits_2_cleanly(cmd_func, tmp_path, capsys):
    bad = tmp_path / "no-such-repo"
    rc = cmd_func(argparse.Namespace(repo=str(bad)))
    captured = capsys.readouterr()
    assert rc == 2, f"{cmd_func.__name__} should exit 2 on a nonexistent path"
    assert "does not exist or is not a directory" in captured.err
    # No raw pathlib repr leak (the internal-leak shape W5-3 forbids).
    assert "PosixPath(" not in (captured.out + captured.err)
    # install-ci must not scaffold a phantom tree at the bad path.
    assert not bad.exists(), f"{cmd_func.__name__} created a phantom dir"


class TestPluralHelper:
    """`espalier._text.plural` renders `<n> <word>`, pluralizing on the count."""

    def test_singular_at_one(self):
        assert plural(1, "warning") == "1 warning"

    def test_default_plural_adds_s(self):
        assert plural(2, "warning") == "2 warnings"

    def test_zero_is_plural(self):
        assert plural(0, "file") == "0 files"

    def test_irregular_plural_form(self):
        assert plural(1, "entry", "entries") == "1 entry"
        assert plural(3, "entry", "entries") == "3 entries"


class TestOsErrorText:
    """DEF-799: ``espalier._text.os_error_text`` is ``str(exc)`` with the path
    spelled as a path. ``OSError.__str__`` renders ``filename`` through
    ``repr``, which doubles every backslash and quotes the path, so a Windows
    operator who pastes the path a doctor failure names is told no such file.
    The red is earnable on POSIX: ``repr`` doubles on every platform."""

    def test_the_repr_shape_is_the_defect(self):
        exc = OSError(13, "Access is denied", r"C:\repo\.claude")
        assert str(exc) == r"[Errno 13] Access is denied: 'C:\\repo\\.claude'"
        assert os_error_text(exc) == r"[Errno 13] Access is denied: C:\repo\.claude"

    def test_everything_but_the_path_is_pythons_own_rendering(self, tmp_path):
        # A RAISED error, not a constructed one: `OSError(2, ..., None, dst)` sets
        # `winerror` to None explicitly, and on Windows CPython then renders
        # `[WinError None]` while the renderer, reading a falsy winerror, says
        # `[Errno 2]` -- a disagreement about a shape no real error has
        # (Portability, 2026-09-23). A real rename failure carries whatever
        # bracket this platform gives it, and both sides must agree on that.
        src, dst = tmp_path / "no-such-a", tmp_path / "no-such-b"
        with pytest.raises(OSError) as info:
            os.rename(src, dst)
        exc = info.value
        expected = str(exc)
        for raw in (exc.filename, exc.filename2):
            if raw is not None:
                expected = expected.replace(repr(raw), str(raw))
        assert os_error_text(exc) == expected

    def test_a_spaced_path_is_quoted_once(self):
        exc = OSError(13, "Permission denied", "/Program Files/x")
        assert os_error_text(exc) == '[Errno 13] Permission denied: "/Program Files/x"'

    def test_a_winerror_takes_the_bracket(self):
        exc = OSError(13, "Access is denied", r"C:\x")
        exc.winerror = 5  # what CPython sets on Windows; assignable everywhere
        assert os_error_text(exc) == r"[WinError 5] Access is denied: C:\x"

    def test_no_filename_and_non_oserror_pass_through_unchanged(self):
        import subprocess
        for exc in (OSError(5, "Input/output error"), OSError("bare"),
                    subprocess.TimeoutExpired(["git"], 5), ValueError("plain")):
            assert os_error_text(exc) == str(exc)

    def test_quoted_if_spaced(self):
        assert quoted_if_spaced("/a/b") == "/a/b"
        assert quoted_if_spaced("/a b/c") == '"/a b/c"'
        assert quoted_if_spaced("C:\\t\tab") == '"C:\\t\tab"'
