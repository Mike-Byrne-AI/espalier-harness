"""TP-37: PASS/FAIL/SKIP semantics + ``--validate-archive`` mode.

Pins the post-TP-37 status taxonomy against the pre-fix
conflation. The old ``release_check`` returned ``status="PASS"``
for env-gated checks while emitting ``"skipped (set X=1 to run)"``
in the detail string — silently conflating passes and skips in
the summary so an operator reading "all PASS" could not tell
which checks actually ran. After TP-37 those env-gated paths
return ``status="SKIP"`` and the summary line distinguishes them.

The new ``--validate-archive PATH`` mode runs the dual-witness
(classifier + denylist) against an arbitrary ZIP. Without this
contract a regression could re-merge PASS and SKIP into the same
bucket, returning the gate to its pre-TP-37 dishonest signal.
"""
from __future__ import annotations

import io
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import release_check  # type: ignore
sys.path.pop(0)


class TestSkipStatus:
    """Opt-in checks return SKIP without their env var, PASS with it."""

    def test_tests_pass_skips_without_env(self, monkeypatch):
        monkeypatch.delenv("ESPALIER_RELEASE_CHECK_WITH_TESTS", raising=False)
        result = release_check.check_tests_pass(REPO_ROOT)
        assert result.status == "SKIP"
        assert "ESPALIER_RELEASE_CHECK_WITH_TESTS" in result.detail

    def test_wheel_smoke_skips_without_env(self, monkeypatch):
        monkeypatch.delenv("ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE", raising=False)
        result = release_check.check_wheel_smoke(REPO_ROOT)
        assert result.status == "SKIP"
        assert "ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE" in result.detail


class TestSummaryPrintsCounts:
    """Summary line distinguishes truly-passed from skipped."""

    def _make_results(self, passes=0, skips=0, fails=0):
        return (
            [release_check.CheckResult(f"p{i}", "PASS") for i in range(passes)]
            + [release_check.CheckResult(f"s{i}", "SKIP", "env-gated") for i in range(skips)]
            + [release_check.CheckResult(f"f{i}", "FAIL", "bad") for i in range(fails)]
        )

    def test_all_pass_says_all_passed(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            release_check.print_results(self._make_results(passes=5))
        out = buf.getvalue()
        assert "All 5 checks passed" in out
        assert "release_check OK" in out

    def test_mix_with_skip_distinguishes(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            release_check.print_results(self._make_results(passes=19, skips=2))
        out = buf.getvalue()
        assert "19 passed, 2 skipped" in out
        assert "release_check OK" in out

    def test_fail_suppresses_ok_trailer(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            release_check.print_results(self._make_results(passes=10, fails=1))
        out = buf.getvalue()
        assert "1 check(s) failed" in out
        assert "release_check OK" not in out


class TestExitCodeIgnoresSkip:
    """Exit code stays 0 when only SKIP, 1 when any FAIL."""

    def test_only_skip_returns_zero(self, monkeypatch):
        # tests_pass and wheel_smoke skip; everything else should pass on live repo.
        monkeypatch.delenv("ESPALIER_RELEASE_CHECK_WITH_TESTS", raising=False)
        monkeypatch.delenv("ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE", raising=False)
        # ``main([])`` accepts the explicit empty argv directly — the
        # earlier ``patch("sys.argv", ...)`` wrapper was redundant.
        rc = release_check.main([])
        assert rc == 0


class TestValidateArchiveMode:
    """``release_check.py --validate-archive PATH`` runs the dual witness."""

    def _make_zip(self, path: Path, members: dict[str, bytes]) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)

    def test_nonexistent_path_fails(self, tmp_path):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(tmp_path / "missing.zip")])
        assert rc == 1
        assert "not found" in buf.getvalue()

    def test_not_a_zip_fails(self, tmp_path):
        not_zip = tmp_path / "thing.txt"
        not_zip.write_text("hi", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(not_zip)])
        assert rc == 1
        assert "not a .zip" in buf.getvalue()

    def test_clean_zip_passes(self, tmp_path):
        z = tmp_path / "clean.zip"
        # All-public archive: every required member under the version-stamped
        # root (the content floor is part of "clean" since TP-454 3-D(ii);
        # a README-and-pyproject ZIP is a near-empty build, not a clean one).
        members = {
            f"espalier-harness-0.6.4/{rel}": b"x\n"
            for rel in release_check.REQUIRED_ARCHIVE_MEMBERS
        }
        self._make_zip(z, members)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        # Archive members go through classifier; if a member doesn't classify
        # as public it's a fail. Every required member is public.
        assert rc == 0
        out = buf.getvalue()
        assert "PASS" in out
        assert f"{len(members)} members" in out

    def test_dirty_zip_fails_both_witnesses(self, tmp_path):
        z = tmp_path / "dirty.zip"
        self._make_zip(z, {
            "project.zip": b"fake nested archive",
            "README.md": b"# hi\n",
            "reports/run.json": b"{}",
        })
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        assert rc == 1
        out = buf.getvalue()
        assert "project.zip" in out
        assert "classifier:" in out
        assert "denylist:" in out

    def test_empty_zip_fails_cleanly(self, tmp_path):
        """A 0-byte file with .zip extension must fail with a readable
        message, not raise BadZipFile out of the gate."""
        z = tmp_path / "empty.zip"
        z.write_bytes(b"")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        assert rc == 1
        assert "not a valid ZIP" in buf.getvalue()

    def test_zip_with_absolute_member_name_fails(self, tmp_path):
        """Round-6: a poisoned release ZIP whose members start with
        ``/`` (absolute) must be rejected by the name-safety pre-witness
        BEFORE the classifier and denylist run. Pre-fix, both witnesses
        passed it as ``public``/``no-match``."""
        z = tmp_path / "abs.zip"
        self._make_zip(z, {"/etc/passwd": b"evil"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        assert rc == 1
        out = buf.getvalue()
        assert "/etc/passwd" in out
        assert "name-safety" in out
        assert "absolute path" in out

    def test_zip_with_dotdot_member_name_fails(self, tmp_path):
        """Round-6: ``..`` path-segment members must also be rejected."""
        z = tmp_path / "traverse.zip"
        self._make_zip(z, {"../escape.txt": b"oops"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        assert rc == 1
        out = buf.getvalue()
        assert "../escape.txt" in out
        assert "name-safety" in out
        assert "traversal segment" in out

    def test_zip_with_windows_drive_member_name_fails(self, tmp_path):
        """Round-6: Windows drive prefix in a member name is also a
        traversal attempt (on a Windows operator's machine)."""
        z = tmp_path / "drive.zip"
        self._make_zip(z, {r"C:\Windows\System32\drivers\etc\hosts": b"x"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        assert rc == 1
        out = buf.getvalue()
        assert "name-safety" in out
        assert "Windows drive prefix" in out

    def test_dirty_zip_with_archive_prefix_exercises_normalisation(self, tmp_path):
        """The same dirty content but under the standard
        ``espalier-harness-<version>/`` archive prefix — exercises the
        ``_archive_member_to_rel`` normalisation path that both
        witnesses now share. A regression that broke the rel-stripping
        would surface this rather than the prefix-less form."""
        z = tmp_path / "prefixed_dirty.zip"
        self._make_zip(z, {
            "espalier-harness-0.6.4/project.zip": b"fake nested",
            "espalier-harness-0.6.4/README.md": b"# hi\n",
            "espalier-harness-0.6.4/reports/run.json": b"{}",
        })
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = release_check.main(["--validate-archive", str(z)])
        assert rc == 1
        out = buf.getvalue()
        # After the rel-strip both witness lines show the same path form
        # — verifies the symmetry fix from this remediation pass.
        assert "project.zip" in out
        assert "classifier:" in out
        assert "denylist:" in out


class TestArchiveCleanCheckConsultsDenylist:
    """check_release_archive_builds_and_clean wires the denylist as 2nd witness."""

    def test_detail_mentions_dual_witness(self, monkeypatch):
        # On a clean self-host repo the check should pass and mention both witnesses.
        builds, clean = release_check.check_release_archive_builds_and_clean(REPO_ROOT)
        assert builds.status == "PASS", builds.detail
        assert clean.status == "PASS", clean.detail
        assert "classifier + denylist" in clean.detail

    def test_tree_enumerated_build_on_a_git_root_fails(self, monkeypatch):
        """§C13: a root that owns its .git but walked the tree is git failing,
        and the artifact holds every untracked public file; the WARN on stderr
        was the only trace. Driven by taking the index away from the builder."""
        from espalier import surface_contract
        monkeypatch.setattr(surface_contract, "tracked_paths", lambda root: None)
        builds, clean = release_check.check_release_archive_builds_and_clean(REPO_ROOT)
        assert builds.status == "FAIL" and "working tree" in builds.detail, builds
        assert clean.status == "FAIL"
