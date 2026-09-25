"""Tests for ``espalier.pre_release`` — the cleanliness gate run
before every tagged release to catch placeholder contacts, missing
``LICENSE`` / ``CONTRIBUTING.md`` / ``SECURITY.md`` (TP-OSS-02), and
other release-noise.

Pins the gate's positive-vs-negative checks: placeholder contact
strings (e.g., ``security-contact@example.com``) trip the gate;
the minimum-valid ``SECURITY.md`` shape passes. Without this contract
a copy-paste of a template README into production could silently
ship with a fake email address, sending real vulnerability reports
into the void — the failure mode is invisible until someone tries
to use the published channel.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


from espalier import pre_release, surface_contract
from espalier.pre_release import run_cleanliness_gate

REPO_ROOT = Path(__file__).resolve().parent.parent


def _add_required_files(repo: Path) -> None:
    for fname, content in [
        ("LICENSE", "MIT License\nCopyright 2024\n"),
        ("CONTRIBUTING.md", "# Contributing\nSend a pull request.\n"),
        ("pyproject.toml", '[project]\nname = "test"\nversion = "0.1.0"\n'),
        ("SECURITY.md", _MINIMAL_SECURITY_MD),
        # CODE_OF_CONDUCT.md joined REQUIRED_PUBLIC_FILES when the release
        # gate stopped exempting it; every "this repo is clean" fixture below
        # needs it or it fails on a missing-file, not on what it is testing.
        ("CODE_OF_CONDUCT.md", "# Code of Conduct\nReport to conduct@real.example.\n"),
    ]:
        path = repo / fname
        if not path.exists():
            path.write_text(content, encoding="utf-8")


# Minimal SECURITY.md that satisfies _check_security_policy (TP-OSS-02).
_MINIMAL_SECURITY_MD = """# Security Policy

## Reporting a Vulnerability

Please do not open a public GitHub issue with vulnerability details.

Use GitHub's private vulnerability reporting flow from the Security tab
by selecting `Report a vulnerability`.
"""


class TestCleanlinessGate:
    def test_catches_placeholder_contact(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "Report issues to security-contact@example.com.\n", encoding="utf-8"
        )
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any("placeholder contact" in f for f in result["failures"])

    def test_catches_placeholder_url(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "Source: https://github.com/OWNER/REPO\n", encoding="utf-8"
        )
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any("placeholder URL" in f for f in result["failures"])

    def test_catches_angle_bracket_owner_placeholder(self, tmp_path):
        """TP-171 §3.3 earn-the-red: the `<owner>` dialect that actually shipped
        in README.md — the pre-fix marker list was blind to it."""
        (tmp_path / "README.md").write_text(
            "git clone https://github.com/<owner>/espalier-harness.git\n",
            encoding="utf-8",
        )
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any("placeholder URL" in f for f in result["failures"])

    def test_real_owner_url_not_flagged_as_placeholder(self, tmp_path):
        """A concrete owner/repo URL must NOT trip the placeholder gate."""
        (tmp_path / "README.md").write_text(
            "git clone https://github.com/Mike-Byrne-AI/espalier-harness.git\n",
            encoding="utf-8",
        )
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        assert not any("placeholder URL" in f for f in result["failures"])

    def test_catches_missing_required_files(self, tmp_path):
        (tmp_path / "README.md").write_text("# Clean repo\n", encoding="utf-8")
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        failure_text = " ".join(result["failures"])
        assert "LICENSE" in failure_text

    def test_placeholder_contact_in_code_of_conduct_fails_gate(self, tmp_path):
        """COMMHEALTH-03 earn-the-red: the CoC was scanned by nothing.

        Pre-fix this returned status=pass with failures=[] — the enforcement
        contact a stranger is told to write to could be the gate's own
        placeholder string and the release gate said nothing.
        """
        (tmp_path / "README.md").write_text("# Clean\n", encoding="utf-8")
        _add_required_files(tmp_path)
        (tmp_path / "CODE_OF_CONDUCT.md").write_text(
            "Report conduct concerns to security-contact@example.com.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any(
            "CODE_OF_CONDUCT.md" in f and "placeholder contact" in f
            for f in result["failures"]
        )

    def test_missing_code_of_conduct_fails_gate(self, tmp_path):
        """COMMHEALTH-03's other half: a DELETED CoC used to pass green."""
        (tmp_path / "README.md").write_text("# Clean\n", encoding="utf-8")
        _add_required_files(tmp_path)
        (tmp_path / "CODE_OF_CONDUCT.md").unlink()
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert "CODE_OF_CONDUCT.md" in " ".join(result["failures"])

    def test_placeholder_scan_covers_every_required_public_file(
        self, tmp_path, monkeypatch
    ):
        """The scan list is DERIVED from REQUIRED_PUBLIC_FILES, not a twin.

        Asserting today's membership would pass against two hand-kept lists
        that happen to agree. This mutates the SoT with a file neither list
        ever named: if the scan still derives, the new entry is scanned and
        its placeholder is caught. A reintroduced literal list stays blind
        to it and this goes red.
        """
        from espalier import pre_release

        monkeypatch.setattr(
            pre_release,
            "REQUIRED_PUBLIC_FILES",
            (*pre_release.REQUIRED_PUBLIC_FILES, "GOVERNANCE.md"),
        )
        (tmp_path / "GOVERNANCE.md").write_text(
            "Escalate to security-contact@example.com.\n", encoding="utf-8"
        )
        findings = pre_release._scan_placeholders(tmp_path)
        assert any("GOVERNANCE.md" in f for f in findings), (
            "a file added to REQUIRED_PUBLIC_FILES was not placeholder-scanned "
            "— the scan list has drifted back into a second hand-kept literal"
        )

    def test_passes_clean_repo(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# My Project\nA real project with real content.\n", encoding="utf-8"
        )
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "pass"
        assert result["failures"] == []

    def test_flags_transient_noise(self, tmp_path):
        (tmp_path / "README.md").write_text("# Clean\n", encoding="utf-8")
        _add_required_files(tmp_path)
        (tmp_path / "__pycache__").mkdir()
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "scan_exceptions.json").write_text("{}", encoding="utf-8")
        result = run_cleanliness_gate(tmp_path)
        assert len(result["warnings"]) > 0
        warn_text = " ".join(result["warnings"])
        assert "transient noise" in warn_text


class TestTransientNoiseIsTheContract:
    """§C13 (DEF-417e): the warning half of the release gate classifies with
    the archive half's predicate and walks under the archive half's prune.

    Before: a hand-kept set of four directory names, and a walk that descended
    into the release-matrix workspace the packer prunes silently -- so the
    gate warned about junk the archive never enumerates (driven 2026-09-08:
    `dist/final-release-matrix/work/__pycache__` reported on a worktree).
    """

    def _tree(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# r\n", encoding="utf-8")
        _add_required_files(tmp_path)
        return tmp_path

    def test_matrix_workspace_residue_is_never_named(self, tmp_path):
        """Earn-the-red: the pruned subtree was walked and reported before."""
        repo = self._tree(tmp_path)
        residue = repo / "dist" / "final-release-matrix" / "work" / "__pycache__"
        residue.mkdir(parents=True)
        (residue / "x.pyc").write_bytes(b"x")
        noise = pre_release._find_transient_noise(repo)
        assert not any(n.startswith("dist/final-release-matrix") for n in noise), noise
        assert "dist" in noise  # the transient tree itself, once

    def test_a_transient_tree_is_reported_once_not_per_file(self, tmp_path):
        repo = self._tree(tmp_path)
        (repo / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
        (repo / ".pytest_cache" / "v" / "cache" / "nodeids").write_text("[]", encoding="utf-8")
        (repo / ".pytest_cache" / "README.md").write_text("cache\n", encoding="utf-8")
        assert pre_release._find_transient_noise(repo) == [".pytest_cache"]

    def test_the_four_hand_kept_names_still_fire_from_the_contract(self, tmp_path):
        """Regression control for the deleted `TRANSIENT_NOISE_DIRS` set."""
        repo = self._tree(tmp_path)
        for name in (".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"):
            (repo / name).mkdir()
        noise = pre_release._find_transient_noise(repo)
        assert {".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"} <= set(noise)
        assert not hasattr(pre_release, "TRANSIENT_NOISE_DIRS"), (
            "the hand-kept directory set is back beside the contract"
        )

    def test_a_transient_file_outside_any_tree_is_reported(self, tmp_path):
        repo = self._tree(tmp_path)
        (repo / ".DS_Store").write_bytes(b"\x00")
        (repo / "docs").mkdir()
        (repo / "docs" / "notes.md.orig").write_text("old\n", encoding="utf-8")
        (repo / "docs" / "notes.md").write_text("new\n", encoding="utf-8")
        noise = pre_release._find_transient_noise(repo)
        assert ".DS_Store" in noise and "docs/notes.md.orig" in noise
        assert "docs/notes.md" not in noise and "README.md" not in noise

    def test_every_reported_path_is_one_the_archive_rejects(self, tmp_path):
        """The two halves agree: nothing this half names would the other half
        ship, and a root `.git` of either kind is pruned by both."""
        repo = self._tree(tmp_path)
        (repo / "__pycache__").mkdir()
        (repo / "build" / "lib").mkdir(parents=True)
        (repo / "build" / "lib" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "stray.zip").write_bytes(b"PK")
        (repo / ".git").write_text("gitdir: /Users/someone/main/.git/worktrees/wt\n", encoding="utf-8")
        reports = repo / "reports"
        reports.mkdir()
        (reports / "scan_exceptions.json").write_text("{}", encoding="utf-8")
        noise = pre_release._find_transient_noise(repo)
        assert noise, "seeded junk produced no warnings"
        assert ".git" not in noise
        # Ask the ARCHIVE, not the selector the scan itself used: build the
        # zip from the same tree and require that nothing this half named is
        # a member (a directory: nothing under it).
        from espalier.release_pack import create_release_zip
        out = repo / "dist" / "out.zip"
        create_release_zip(repo, out)
        with zipfile.ZipFile(out) as zf:
            members = set(zf.namelist())
        assert members, "the archive half shipped nothing; the check below is vacuous"
        for rel in noise:
            if (repo / rel).is_dir():
                shipped = sorted(m for m in members if m.startswith(rel + "/"))
                assert not shipped, f"{rel}/ is warned about as noise but the archive ships {shipped}"
            else:
                assert rel not in members, f"{rel} is warned about as noise but the archive ships it"

    def test_the_walk_prune_is_the_packers_own_object(self):
        """The noise scan imports release_pack's private prune on purpose: it is
        the archive walker's report-only policy, and one object shared is how
        the two halves stay on one prune. A rename or a local copy reds here
        with a sentence, not as an ImportError three modules away."""
        from espalier import release_pack
        assert pre_release._is_pruned_from_walk is release_pack._is_pruned_from_walk

    def test_secret_files_are_labelled_as_secrets_not_noise(self, tmp_path):
        """`.env` is transient in the contract's vocabulary (SECRET_FILES sit
        inside RELEASE_NOISE_PATTERNS) and the archive refuses it on both
        witnesses; the warning must not file it under a clean-this-up heading."""
        repo = self._tree(tmp_path)
        for name in (".env", ".pypirc", "id_rsa"):
            (repo / name).write_text("s\n", encoding="utf-8")
        (repo / "__pycache__").mkdir()
        result = run_cleanliness_gate(repo)
        secret_lines = [w for w in result["warnings"] if w.startswith("secret file present")]
        noise_lines = [w for w in result["warnings"] if w.startswith("transient noise")]
        assert {w.rsplit(": ", 1)[1] for w in secret_lines} == {".env", ".pypirc", "id_rsa"}
        assert all("do not delete" in w for w in secret_lines)
        assert [w.rsplit(": ", 1)[1] for w in noise_lines] == ["__pycache__"]
        assert result["status"] == "pass"  # both stay warnings


class TestInternalLeaksEnumerateWhatShips:
    """§C13 (DEF-417g's failing sister): a leak is a file the ARCHIVE would
    carry. Once the archive became the git index, an untracked internal
    scratch file could not reach it, yet `_find_internal_leaks` still walked
    the tree and hard-failed `/preflight` on it (driven 2026-09-08)."""

    def _git(self, repo: Path, *args: str) -> None:
        import subprocess
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    def test_untracked_internal_file_is_not_a_leak_but_a_tracked_one_is(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / "docs" / "internal").mkdir(parents=True)
        (repo / "README.md").write_text("# r\n", encoding="utf-8")
        (repo / "docs" / "internal" / "tracked.md").write_text("i\n", encoding="utf-8")
        self._git(repo, "init", "-q")
        self._git(repo, "add", "-A")
        (repo / "docs" / "internal" / "scratch.md").write_text("notes\n", encoding="utf-8")
        leaks = pre_release._find_internal_leaks(repo)
        assert leaks == ["docs/internal/tracked.md"], leaks

    def test_a_root_with_no_index_still_walks_the_tree(self, tmp_path):
        repo = tmp_path / "plain"
        (repo / "docs" / "internal").mkdir(parents=True)
        (repo / "docs" / "internal" / "scratch.md").write_text("notes\n", encoding="utf-8")
        assert pre_release._find_internal_leaks(repo) == ["docs/internal/scratch.md"]


class TestReleasePackStageFailures:
    """The pack stage's two silent shapes, now failures (§C13): an archive
    with nothing in it, and one enumerated from the working tree on a root
    that owns its `.git` -- git failing, with every untracked public file in
    the artifact. Both were green at the builder and loud only on stderr."""

    def _summary(self, root: Path, *, files: int, enumeration: str):
        from espalier.release_pack import ReleasePackSummary
        return ReleasePackSummary(
            repo_root=str(root), output_zip=str(root / "dist" / "x.zip"),
            files_written=files, enumeration=enumeration,
        )

    def test_empty_archive_is_a_failure(self, tmp_path):
        failures = pre_release._release_pack_failures(tmp_path, self._summary(tmp_path, files=0, enumeration="index"))
        assert len(failures) == 1 and "nothing packageable" in failures[0]

    def test_tree_enumeration_on_a_git_root_is_a_failure(self, tmp_path):
        (tmp_path / ".git").mkdir()  # a root that owns a .git git cannot read
        failures = pre_release._release_pack_failures(tmp_path, self._summary(tmp_path, files=3, enumeration="tree"))
        assert len(failures) == 1 and "working tree" in failures[0]

    def test_tree_enumeration_on_a_plain_directory_is_not(self, tmp_path):
        assert pre_release._release_pack_failures(tmp_path, self._summary(tmp_path, files=3, enumeration="tree")) == []

    def test_index_enumeration_with_files_is_clean(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert pre_release._release_pack_failures(tmp_path, self._summary(tmp_path, files=3, enumeration="index")) == []

    def test_the_stage_reports_them(self, tmp_path, monkeypatch):
        """Wired, not just defined: the failures reach the report's `failures`."""
        import espalier.pre_release as pr
        calls: list[str] = []
        monkeypatch.setattr(pr, "_release_pack_failures", lambda root, summary: calls.append("called") or ["release pack: probe"])
        monkeypatch.setattr(pr, "create_release_zip", lambda root, out: self._summary(root, files=1, enumeration="index"))
        monkeypatch.setattr(pr, "run_cleanliness_gate", lambda root: {"status": "pass", "failures": [], "warnings": [], "internal_leaks": []})
        monkeypatch.setattr(pr, "_parity_runnable", lambda: False)
        report = pr.run_pre_release_check(tmp_path, skip_tests=True)
        assert calls == ["called"]
        assert "release pack: probe" in report["failures"]
        assert report["status"] == "fail"


class TestSecurityPolicyGate:
    """TP-OSS-02 §5 — SECURITY.md must route reports privately."""

    def _clean_repo(self, tmp_path):
        (tmp_path / "README.md").write_text("# My Project\n", encoding="utf-8")
        _add_required_files(tmp_path)
        return tmp_path

    def test_missing_security_md_fails_gate(self, tmp_path):
        """SECURITY.md is now required for release."""
        (tmp_path / "README.md").write_text("# My Project\n", encoding="utf-8")
        # Add required files but NOT SECURITY.md.
        for fname, content in [
            ("LICENSE", "MIT\n"),
            ("CONTRIBUTING.md", "# Contributing\n"),
            ("pyproject.toml", '[project]\nname = "x"\nversion = "0.1.0"\n'),
        ]:
            (tmp_path / fname).write_text(content, encoding="utf-8")
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any("SECURITY.md" in f for f in result["failures"])

    def test_public_issue_vulnerability_routing_fails_gate(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        (repo / "SECURITY.md").write_text(
            "# Security\n\n"
            "Report it by opening a GitHub issue at "
            "https://github.com/x/y/issues.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        text = " ".join(result["failures"])
        assert "publicly" in text or "public" in text.lower()

    def test_missing_private_disclosure_phrasing_fails_gate(self, tmp_path):
        """SECURITY.md without 'Report a vulnerability' / 'private' / 'do not'
        should fail — these concepts are load-bearing for the policy."""
        repo = self._clean_repo(tmp_path)
        (repo / "SECURITY.md").write_text(
            "# Security\n\nWe take security seriously.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any(
            "private-disclosure concept" in f for f in result["failures"]
        )

    def test_placeholder_security_contact_fails_gate(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        (repo / "SECURITY.md").write_text(
            "# Security\n\n"
            "## Reporting a Vulnerability\n"
            "Please do not open a public GitHub issue. Use the private "
            "vulnerability reporting Security tab → "
            "`Report a vulnerability`. Fallback: "
            "<REAL_PRIVATE_SECURITY_CONTACT>.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        text = " ".join(result["failures"])
        assert "<REAL_PRIVATE_SECURITY_CONTACT>" in text

    def test_private_reporting_policy_passes_gate(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        # _add_required_files already wrote a minimal compliant SECURITY.md
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", (
            f"Expected pass, got failures: {result['failures']}"
        )

    def test_canonical_short_redirect_passes_gate(self, tmp_path):
        """TP-191 M2 earn-the-red: the canonical SHORT redirect "do not open a
        public issue" CONTAINS the forbidden substring "open a public issue".
        A textbook-correct SECURITY.md using it satisfies the required-concept
        check AND (pre-M2) false-tripped the forbidden scan. After masking the
        required redirects before the forbidden scan, it must PASS."""
        repo = self._clean_repo(tmp_path)
        (repo / "SECURITY.md").write_text(
            "# Security Policy\n\n"
            "## Reporting a Vulnerability\n\n"
            "Please do not open a public issue with vulnerability details. "
            "Report it privately using GitHub's private vulnerability reporting "
            "from the Security tab by selecting `Report a vulnerability`.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", (
            f"Canonical short redirect false-failed the gate: {result['failures']}"
        )

    def test_genuine_public_routing_still_fails_after_mask(self, tmp_path):
        """TP-191 M2 negative control: masking the required redirect must be
        surgical — a SECURITY.md that ALSO routes publicly ("open a github
        issue to escalate") still fails, because no required redirect contains
        that forbidden phrase. Proves the mask did not over-broaden into a
        blanket bypass of the forbidden scan."""
        repo = self._clean_repo(tmp_path)
        (repo / "SECURITY.md").write_text(
            "# Security Policy\n\n"
            "## Reporting a Vulnerability\n\n"
            "Please do not open a public issue. Report it privately via the "
            "Security tab by selecting `Report a vulnerability`. If urgent you "
            "may also open a github issue to escalate.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("open a github issue" in f for f in result["failures"]), (
            f"genuine public routing was masked away: {result['failures']}"
        )

    def test_redirect_negating_non_masked_forbidden_phrase_passes(self, tmp_path):
        """TP-313b ITEM F-4 earn-the-red: the forbidden-phrase mask only
        neutralizes the redirect spellings enumerated as required concepts (in
        practice just "open a public issue"), but the gate CHECKS all of
        PUBLIC_VULN_REPORTING_PHRASES. A correct SECURITY.md whose redirect
        negates a DIFFERENT forbidden phrase ("do not report vulnerabilities via
        github issues") false-fails pre-fix. Widening the mask to the negated
        form of every forbidden phrase must let it PASS (the genuine-public
        negative control above still fails)."""
        repo = self._clean_repo(tmp_path)
        (repo / "SECURITY.md").write_text(
            "# Security Policy\n\n"
            "## Reporting a Vulnerability\n\n"
            "To report a vulnerability, report it privately using the private "
            "vulnerability reporting flow from the Security tab. "
            "Please do not report vulnerabilities via github issues, and "
            "do not open a public github issue with details.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", (
            f"valid redirect false-failed the gate: {result['failures']}"
        )

    def test_public_security_issue_template_fails_gate(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        templates = repo / ".github" / "ISSUE_TEMPLATE"
        templates.mkdir(parents=True)
        (templates / "security.yml").write_text(
            "name: Security report\n"
            "description: Report a security issue\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any(
            "ISSUE_TEMPLATE/security.yml" in f for f in result["failures"]
        )

    def test_public_security_issue_template_yaml_ext_fails_gate(self, tmp_path):
        """R12 earn-the-red: GitHub accepts both .yml and .yaml for issue
        templates. A vuln-routing security.yaml template must trip the gate
        too; the pre-fix glob('*.yml') was blind to the .yaml spelling."""
        repo = self._clean_repo(tmp_path)
        templates = repo / ".github" / "ISSUE_TEMPLATE"
        templates.mkdir(parents=True)
        (templates / "security.yaml").write_text(
            "name: Security report\n"
            "description: Report a security issue\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any(
            "ISSUE_TEMPLATE/security.yaml" in f for f in result["failures"]
        )

    def test_bug_template_with_redirect_passes_gate(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        templates = repo / ".github" / "ISSUE_TEMPLATE"
        templates.mkdir(parents=True)
        (templates / "bug_report.yml").write_text(
            "name: Bug report\n"
            "description: Non-security bug\n"
            "body:\n"
            "  - type: markdown\n"
            "    attributes:\n"
            "      value: 'Do not include vulnerability details. "
            "Use Report a vulnerability privately.'\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", (
            f"Expected pass, got failures: {result['failures']}"
        )

    def test_far_redirect_template_still_passes_gate(self, tmp_path):
        """TP-176 W4-5 REVERTED: the redirect-excusal check is whole-file, so a
        legitimate template whose redirect sits far from the solicitation MUST
        still pass — a windowed check would false-fail it (the friction the
        revert avoids). The whole-file check's trivial-defeatability is an
        accept-and-leave (docs/FAILURE_MODES.md §6.10)."""
        repo = self._clean_repo(tmp_path)
        templates = repo / ".github" / "ISSUE_TEMPLATE"
        templates.mkdir(parents=True)
        filler = "x" * 600  # redirect lands far from the solicitation
        (templates / "feedback.yml").write_text(
            "name: Feedback\n"
            "description: General feedback form\n"
            "body:\n"
            "  - type: markdown\n"
            "    attributes:\n"
            "      value: 'Do not file security reports here; use private "
            "disclosure.'\n"
            f"  - type: markdown\n"
            f"    attributes:\n"
            f"      value: '{filler}'\n"
            "  - type: textarea\n"
            "    attributes:\n"
            "      label: Details\n"
            "      description: 'To report a vulnerability, see the security "
            "policy.'\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", (
            f"a template with a (far) redirect must not false-fail the gate: "
            f"{result['failures']}"
        )


class TestInstructedIssueRouteGate:
    """DEF-424h — a doc that instructs a free-form public issue makes a
    promise `.github/ISSUE_TEMPLATE/config.yml` has to keep.

    `blank_issues_enabled: false` removes the blank route, so the
    "request: private security contact" issue SECURITY.md and CONTRIBUTING.md
    both instruct becomes unopenable — as does an install question, which no
    bug/feature template serves.
    """

    _INSTRUCTING_SECURITY_MD = (
        _MINIMAL_SECURITY_MD
        + "\nIf neither private path is available, you may publicly request "
        "a private security contact.\n"
    )

    def _repo_with_config(self, tmp_path, blank_issues: str | None):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "README.md").write_text("# My Project\n", encoding="utf-8")
        _add_required_files(tmp_path)
        if blank_issues is not None:
            templates = tmp_path / ".github" / "ISSUE_TEMPLATE"
            templates.mkdir(parents=True, exist_ok=True)
            (templates / "config.yml").write_text(
                f"blank_issues_enabled: {blank_issues}\n", encoding="utf-8"
            )
        return tmp_path

    def test_disabled_blank_issues_with_instructing_doc_fails_gate(
        self, tmp_path
    ):
        """Earn-the-red: this is the live DEF-424h state reconstructed —
        a doc instructing the free-form issue, and a config that removes it."""
        repo = self._repo_with_config(tmp_path, "false")
        (repo / "SECURITY.md").write_text(
            self._INSTRUCTING_SECURITY_MD, encoding="utf-8"
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any(
            "blank_issues_enabled" in f and "SECURITY.md" in f
            for f in result["failures"]
        ), result["failures"]

    def test_line_wrapped_instruction_is_recognized(self, tmp_path):
        """The recognizer must be whitespace-normalized, not substring.

        This is the live CONTRIBUTING.md spelling: markdown wraps
        "private security\\ncontact" across two lines, so a raw `phrase in
        text` scan misses it. Measured on the real corpus, dropping
        normalization found 1 of 2 instructing docs while still going red on
        the other — the gate would have looked like it worked.
        """
        repo = self._repo_with_config(tmp_path, "false")
        (repo / "CONTRIBUTING.md").write_text(
            "# Contributing\n\n"
            "If private reporting is unavailable, open a public issue only\n"
            "to ask for a private security\ncontact and omit all details.\n",
            encoding="utf-8",
        )
        raw = (repo / "CONTRIBUTING.md").read_text(encoding="utf-8")
        assert "private security contact" not in raw, (
            "fixture must wrap the phrase, or it does not test normalization"
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any(
            "CONTRIBUTING.md" in f and "blank_issues_enabled" in f
            for f in result["failures"]
        ), result["failures"]

    def test_enabled_blank_issues_passes_gate(self, tmp_path):
        """The shipped state: the instruction stands and the route exists."""
        repo = self._repo_with_config(tmp_path, "true")
        (repo / "SECURITY.md").write_text(
            self._INSTRUCTING_SECURITY_MD, encoding="utf-8"
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", result["failures"]

    def test_absent_config_passes_gate(self, tmp_path):
        """GitHub enables blank issues unless a config turns them off, so no
        config means the route exists. Guessing 'route exists' cannot invent
        one — this helper only ever gates a failure."""
        repo = self._repo_with_config(tmp_path, None)
        (repo / "SECURITY.md").write_text(
            self._INSTRUCTING_SECURITY_MD, encoding="utf-8"
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", result["failures"]

    def test_disabled_blank_issues_without_instruction_passes_gate(
        self, tmp_path
    ):
        """Negative control. Turning blank issues off is a legitimate choice
        for a repo whose docs never promise the free-form route; a gate that
        reds on correct configuration gets switched off (§C19)."""
        repo = self._repo_with_config(tmp_path, "false")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", result["failures"]

    def test_yaml_falsey_spelling_is_read_as_disabled(self, tmp_path):
        """`no` is YAML 1.1 falsey. Reading an unrecognized spelling as
        DISABLED makes the gate fire more; a false alarm costs one line, a
        false silence ships the defect."""
        repo = self._repo_with_config(tmp_path, "no")
        (repo / "SECURITY.md").write_text(
            self._INSTRUCTING_SECURITY_MD, encoding="utf-8"
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail", result["failures"]

    def test_a_wrapped_leaky_security_md_still_fails(self, tmp_path):
        """The higher-stakes sibling scanner must flatten too.

        `_flatten_ws` was written for this module's newest check and left off
        `_check_security_policy`, 130 lines up, scanning the SAME SECURITY.md
        with phrases up to 40 characters. Measured: a policy that genuinely
        routes vulnerabilities to public issues reports ZERO failures when the
        editor wraps the phrase and one when it does not. Diagnosing a class
        and fixing one site is how the class survives.
        """
        repo = self._repo_with_config(tmp_path, "true")
        (repo / "SECURITY.md").write_text(
            "# Security Policy\n\n## Reporting a Vulnerability\n\n"
            "Please do not open a public GitHub issue with vulnerability "
            "details.\nUse private vulnerability reporting from the Security "
            "tab by selecting\n`Report a vulnerability`.\n\n"
            # The leak, wrapped mid-phrase exactly as an 80-col editor would.
            "To report a bug, report it by opening a\ngithub issue.\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail", (
            "a wrapped public-routing instruction passed the security gate; "
            "the scan is reading raw text again"
        )
        assert any("routes vulnerability reports publicly" in f
                   for f in result["failures"]), result["failures"]

    def test_naming_a_private_contact_is_not_instructing_an_issue(
        self, tmp_path
    ):
        """A phrase match is a TOPIC; the gate must require an ACT.

        Both of these fired before the sentence-level discriminator, and both
        exit 1 through the documented adopter-facing `espalier pre-release` —
        telling the reader to "drop the instruction" when the sentence either
        instructs nothing or instructs the opposite. §C19: a gate that reds on
        correct configuration is a gate that gets switched off.
        """
        for label, sentence in (
            ("bare mention", "Our private security contact is s@acme.example."),
            ("explicit negation",
             "Do not open a public issue to ask for a private security contact."),
        ):
            repo = self._repo_with_config(tmp_path / label.replace(" ", "_"), "false")
            (repo / "SECURITY.md").write_text(
                _MINIMAL_SECURITY_MD + "\n" + sentence + "\n", encoding="utf-8"
            )
            assert pre_release._check_instructed_issue_route(repo) == [], (
                f"{label!r} was read as an instruction to open a free-form issue"
            )

    def test_a_present_but_unparsed_config_is_not_read_as_enabled(
        self, tmp_path
    ):
        """Unknown is not enabled.

        A BOM before the key, a duplicated key (YAML takes the last, `search`
        took the first), and an empty value all returned "route exists" and
        reported nothing — contradicting the policy stated on
        `_BLANK_ISSUES_DISABLED_VALUES`, that a false alarm costs one line and
        a false silence ships the defect.
        """
        cases = {
            "bom": "﻿blank_issues_enabled: false\n",
            "dup": "blank_issues_enabled: true\nblank_issues_enabled: false\n",
            "empty": "blank_issues_enabled:\n",
        }
        for label, body in cases.items():
            repo = self._repo_with_config(tmp_path / label, None)
            templates = repo / ".github" / "ISSUE_TEMPLATE"
            templates.mkdir(parents=True, exist_ok=True)
            (templates / "config.yml").write_text(body, encoding="utf-8")
            assert not pre_release._blank_issue_route_exists(repo), (
                f"{label!r} config read as blank-issues-ENABLED; a config that "
                f"names the key but does not parse is unknown, not enabled"
            )
        # Negative control: a genuinely enabled config must stay enabled, or
        # the fix above degenerates into "always disabled".
        ok = self._repo_with_config(tmp_path / "ok", "true")
        assert pre_release._blank_issue_route_exists(ok)

    def test_the_failure_names_the_config_that_is_actually_wrong(
        self, tmp_path
    ):
        """With both spellings present, name the offender.

        The message hardcoded `config.yml` while `config.yaml` held the
        disabling value, sending the operator to a file that already looked
        correct — a red whose instruction cannot be acted on.
        """
        repo = self._repo_with_config(tmp_path, "true")          # config.yml: true
        templates = repo / ".github" / "ISSUE_TEMPLATE"
        (templates / "config.yaml").write_text(
            "blank_issues_enabled: false\n", encoding="utf-8"
        )
        (repo / "SECURITY.md").write_text(
            self._INSTRUCTING_SECURITY_MD, encoding="utf-8"
        )
        failures = pre_release._check_instructed_issue_route(repo)
        assert failures, "the .yaml spelling was not read at all"
        assert any("config.yaml" in f for f in failures), failures

    def test_recognizer_still_engages_the_live_corpus(self):
        """Anti-vacuity floor.

        The gate is worth nothing if its phrase list stops matching the docs
        it exists to protect. A reword that leaves the instruction in place
        but unrecognized would silence it with the suite green — the exact
        way the required-status-check guard went half-blind. If this reds,
        either the recognizer needs the new spelling or the instruction is
        genuinely gone and the gate should be retired; both need a human.
        """
        matched = []
        for rel in pre_release.REQUIRED_PUBLIC_FILES:
            if not rel.endswith(".md"):
                continue
            doc = REPO_ROOT / rel
            if not doc.is_file():
                continue
            flat = pre_release._flatten_ws(
                doc.read_text(encoding="utf-8", errors="replace")
            ).lower()
            if any(
                p in flat
                for p in pre_release.DOC_INSTRUCTED_BLANK_ISSUE_PHRASES
            ):
                matched.append(rel)
        assert matched, (
            "no required public doc matches "
            "DOC_INSTRUCTED_BLANK_ISSUE_PHRASES — the gate is vacuous. "
            "Either a doc was reworded past the recognizer (fix the phrase "
            "list) or the free-form instruction is gone (retire the gate)."
        )

    def test_live_repo_keeps_the_route_it_instructs(self):
        """The shipped repo must satisfy its own gate."""
        assert pre_release._check_instructed_issue_route(REPO_ROOT) == []


class TestPack3InternalLeakFailures:
    """Pack 3-A — internal leaks are hard failures, not warnings."""

    def _clean_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# My Project\n", encoding="utf-8")
        _add_required_files(tmp_path)
        return tmp_path

    def test_docs_internal_tree_fails_gate(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        (repo / "docs" / "internal").mkdir(parents=True)
        (repo / "docs" / "internal" / "secret.md").write_text("private\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("docs/internal/secret.md" in f for f in result["failures"])
        assert "docs/internal/secret.md" in result["internal_leaks"]

    @staticmethod
    def _force_self_host(monkeypatch) -> None:
        # The filename-pattern arm (session-archive, TASK_PACK, blueprint) is
        # the harness's OWN internal-doc vocabulary; TP-174a gates it behind
        # self-host. These tests assert the harness protects its own release,
        # so represent the self-host scenario explicitly.
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda root: True)

    def test_session_archive_fails_gate(self, tmp_path, monkeypatch):
        self._force_self_host(monkeypatch)
        repo = self._clean_repo(tmp_path)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "session-archive.md").write_text("history\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("docs/session-archive.md" in f for f in result["failures"])

    def test_root_task_pack_md_fails_gate(self, tmp_path, monkeypatch):
        self._force_self_host(monkeypatch)
        repo = self._clean_repo(tmp_path)
        (repo / "TASK_PACK_X.md").write_text("internal\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("TASK_PACK_X.md" in f for f in result["failures"])

    def test_root_blueprint_md_fails_gate(self, tmp_path, monkeypatch):
        self._force_self_host(monkeypatch)
        repo = self._clean_repo(tmp_path)
        (repo / "BLUEPRINT_NOTES.md").write_text("internal\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("BLUEPRINT_NOTES.md" in f for f in result["failures"])

    def test_adopter_tree_does_not_hard_fail_on_harness_filename_vocab(self, tmp_path):
        """TP-174a: an adopter (NOT self-host — the default tmp_path) running
        `espalier pre-release` must NOT HARD-FAIL on files that merely match the
        harness's internal-doc filename vocabulary (`*-atlas.md`, `TP-*.md`,
        `blueprint.md`, `TASK_PACK*.md`). Pre-fix every one of these failed the
        gate. Classification stays universal (parity), but the verdict is
        adopter-aware: status passes and none appear in failures."""
        repo = self._clean_repo(tmp_path)
        (repo / "world-atlas.md").write_text("# Atlas\n", encoding="utf-8")
        (repo / "TP-Link-notes.md").write_text("# Notes\n", encoding="utf-8")
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "blueprint.md").write_text("# Blueprint\n", encoding="utf-8")
        (repo / "TASK_PACKAGES.md").write_text("# Packages\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass", result["failures"]
        leak_failures = [f for f in result["failures"] if f.startswith("internal leak:")]
        assert leak_failures == [], leak_failures

    def test_adopter_prefix_arm_still_blocks(self, tmp_path):
        """TP-174a negative control (not an earn-the-red — this passes pre-fix
        too): the generic path-prefix arm (docs/internal/) must STILL HARD-FAIL
        on every repo, adopter or not. Guards against the verdict-gating fix
        over-widening into a false-negative (cardinal constraint #2). The
        earn-the-red for the fix is test_adopter_tree_does_not_hard_fail_*."""
        repo = self._clean_repo(tmp_path)
        (repo / "docs" / "internal").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "internal" / "secret.md").write_text("x\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("docs/internal/secret.md" in f for f in result["failures"])

    def test_public_only_tree_passes(self, tmp_path):
        repo = self._clean_repo(tmp_path)
        (repo / "espalier").mkdir()
        (repo / "espalier" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "tools").mkdir()
        (repo / "tools" / "bar.py").write_text("y = 2\n", encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text("def test(): pass\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass"
        assert result["internal_leaks"] == []

    def test_failure_output_names_specific_path(self, tmp_path, monkeypatch):
        self._force_self_host(monkeypatch)
        repo = self._clean_repo(tmp_path)
        (repo / "TASK_PACK_Q.md").write_text("x\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        opaque = [f for f in result["failures"] if "unclean" in f.lower()]
        assert opaque == []
        named = [f for f in result["failures"] if "TASK_PACK_Q.md" in f]
        assert named

    def test_transient_noise_does_not_fail_gate(self, tmp_path):
        """A __pycache__ directory alone must not cause a hard failure."""
        repo = self._clean_repo(tmp_path)
        (repo / "__pycache__").mkdir()
        (repo / "__pycache__" / "x.pyc").write_bytes(b"x")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass"
        assert any("transient" in w for w in result["warnings"])

    def test_internal_file_without_export_ignore_still_flagged(self, tmp_path, monkeypatch):
        """TP-171 1-B earn-the-red: a tracked-internal file with no
        export-ignore rule is still a leak (the skip is gated on .gitattributes,
        not unconditional). Self-host scenario — the harness's own release."""
        self._force_self_host(monkeypatch)
        repo = self._clean_repo(tmp_path)
        (repo / "blueprint.md").write_text("internal design proposal\n", encoding="utf-8")
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert "blueprint.md" in result["internal_leaks"]

    def test_export_ignored_internal_file_not_flagged(self, tmp_path):
        """TP-171 1-B: an internal file that .gitattributes marks export-ignore
        does not ship in `git archive`, so it is not a leak — even though it is
        classified internal. This is what lets blueprint.md / ESPALIER_MEMORY.md stay
        tracked-for-transparency without reddening a clean-checkout pre-release."""
        repo = self._clean_repo(tmp_path)
        (repo / "blueprint.md").write_text("internal design proposal\n", encoding="utf-8")
        (repo / ".gitattributes").write_text(
            "blueprint.md export-ignore\nmemory/*-atlas.md export-ignore\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(repo)
        assert result["status"] == "pass"
        assert "blueprint.md" not in result["internal_leaks"]

    def test_export_ignore_pattern_matching_anchoring(self, tmp_path):
        """A pattern whose only separator is TRAILING is unanchored — it matches
        that name at any depth; a pattern with a leading or interior separator is
        anchored to the repo root (mirrors surface_contract dispatch).

        The original docstring here said "a slash pattern is path-anchored",
        which is false for the trailing-slash case and is the misreading that
        let TP-413's asset-prune defect through. The assertions below were all
        correct and are unchanged; only the rule they illustrate is restated.
        """
        from espalier.pre_release import _matches_export_ignore
        assert _matches_export_ignore("memory/x-atlas.md", "memory/*-atlas.md")
        assert _matches_export_ignore("deep/nested/ESPALIER_MEMORY.md", "ESPALIER_MEMORY.md")
        # path-anchored: a slash pattern does not match a different directory
        assert not _matches_export_ignore("other/x-atlas.md", "memory/*-atlas.md")
        # TP-239: a trailing-/ DIRECTORY pattern matches the dir + everything
        # beneath it (git attribute inheritance, which plain fnmatch missed),
        # without bleeding into a same-prefix sibling directory.
        assert _matches_export_ignore("task-packs/TP-1.md", "task-packs/")
        assert _matches_export_ignore("task-packs/Done/TP-2.md", "task-packs/")
        assert _matches_export_ignore("task-packs", "task-packs/")  # the dir itself
        assert not _matches_export_ignore("task-packsX/y.md", "task-packs/")  # no bleed

    def test_export_ignore_anchoring_matches_driven_git_semantics(self, tmp_path):
        """TP-413 0-Z. The matcher must agree with git, in BOTH directions.

        Every row below was measured by driving ``git archive
        --worktree-attributes`` over a scratch repo and reading which paths
        survived — not read off ``gitattributes(5)`` and not inferred from the
        old model. The model was wrong in opposite directions on the first two
        rows, which is why ``espalier/assets/task-packs/CLAUDE.md`` — a package
        asset ``espalier init`` deploys — was silently pruned from the archive
        while every model-based check stayed green.

        The lesson one layer below ``docs/sharp-edges/source-tree-is-not-an-
        artifact-oracle.md``: a *model* of the artifact is not the artifact
        either. Only git can answer what git prunes.
        """
        from espalier.pre_release import _matches_export_ignore

        # (rel, pattern, git prunes it?) — driven, 2026-08-01.
        driven = [
            # A LEADING slash anchors to the repo root.
            ("task-packs/CLAUDE.md", "/task-packs/", True),
            ("espalier/assets/task-packs/CLAUDE.md", "/task-packs/", False),
            ("nested/deep/task-packs/x.md", "/task-packs/", False),
            # No leading slash + no INTERIOR slash: matches at ANY depth. The
            # trailing slash alone does not anchor — this is the row the old
            # model got backwards, and the one that pruned the asset.
            ("task-packs/CLAUDE.md", "task-packs/", True),
            ("espalier/assets/task-packs/CLAUDE.md", "task-packs/", True),
            ("nested/deep/task-packs/x.md", "task-packs/", True),
            # A bare directory name with NO trailing slash behaves identically:
            # it matches the directory, and export-ignore prunes the subtree.
            ("espalier/assets/task-packs/CLAUDE.md", "task-packs", True),
            # An INTERIOR slash anchors to the root even with no leading slash.
            ("docs/RELEASE_FINDINGS_LEDGER.md", "docs/RELEASE_FINDINGS_LEDGER.md", True),
            ("a/docs/RELEASE_FINDINGS_LEDGER.md", "docs/RELEASE_FINDINGS_LEDGER.md", False),
            (".claude/workflows/x.js", ".claude/workflows/", True),
            (".claude/agents/x.md", ".claude/workflows/", False),
            # A pattern with no separator at all matches the basename anywhere.
            ("deep/nested/ESPALIER_MEMORY.md", "ESPALIER_MEMORY.md", True),
            # `*` does NOT cross a separator (git's wildmatch), though
            # fnmatch.fnmatch's does — a latent over-match while memory/ is flat.
            ("memory/x-atlas.md", "memory/*-atlas.md", True),
            ("memory/sub/y-atlas.md", "memory/*-atlas.md", False),
        ]
        wrong = [
            f"{rel!r} vs {pat!r}: model={_matches_export_ignore(rel, pat)} git={expected}"
            for rel, pat, expected in driven
            if _matches_export_ignore(rel, pat) is not expected
        ]
        assert not wrong, (
            "surface_contract.matches_export_ignore disagrees with driven git "
            "behaviour on:\n  " + "\n  ".join(wrong)
        )

    def test_live_gitattributes_uses_no_unsupported_double_star(self):
        """Floor for the matcher's one documented gap.

        ``matches_export_ignore`` implements git's anchoring and its
        "``*`` never crosses ``/``" rule, but NOT ``**`` (zero-or-more
        directories) — no live pattern uses it, so building it would be an
        untested branch. This reds the day someone adds one, instead of the
        matcher silently disagreeing with git again.
        """
        from espalier.pre_release import _export_ignore_patterns
        patterns = _export_ignore_patterns(REPO_ROOT)
        # Floor: vacuous if the patterns stopped being found at all.
        assert len(patterns) >= 8, (
            f"only {len(patterns)} export-ignore patterns parsed from "
            ".gitattributes — floor failed (parser or file moved?)"
        )
        unsupported = sorted(p for p in patterns if "**" in p)
        assert not unsupported, (
            "`.gitattributes` gained a `**` export-ignore pattern, which "
            f"matches_export_ignore does not implement: {unsupported}\n"
            "Remediation: implement `**` segment matching (and extend "
            "test_export_ignore_anchoring_matches_driven_git_semantics with "
            "driven rows) before relying on it."
        )


class TestSharedOutcomeInvariant:
    """Pack 3-A — pre_release and release_pack classify identically."""

    def _synth_tree(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")
        (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (tmp_path / "CONTRIBUTING.md").write_text("# c\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n', encoding="utf-8")
        (tmp_path / "espalier").mkdir()
        (tmp_path / "espalier" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "docs" / "internal").mkdir(parents=True)
        (tmp_path / "docs" / "internal" / "plans.md").write_text("i\n", encoding="utf-8")
        (tmp_path / "docs" / "session-archive.md").write_text("h\n", encoding="utf-8")
        (tmp_path / "TASK_PACK_1.md").write_text("i\n", encoding="utf-8")
        (tmp_path / "BLUEPRINT_X.md").write_text("i\n", encoding="utf-8")
        return tmp_path

    # Golden: the internal files _synth_tree plants. Hand-maintained HERE so the
    # test has an operand independent of ``is_internal_release_leak`` — which
    # drives BOTH gate_leaks and pack_internal, so a regression inside it moves
    # the two together and the parity assert alone stays green. If the classifier
    # silently stops flagging one of these, gate_leaks diverges from this golden
    # and reds. Keep in sync with the planted internal files in ``_synth_tree``.
    _PLANTED_INTERNAL = frozenset({
        "docs/internal/plans.md",
        "docs/session-archive.md",
        "TASK_PACK_1.md",
        "BLUEPRINT_X.md",
    })

    def test_same_synthetic_tree_classified_identically(self, tmp_path):
        from espalier.release_pack import create_release_zip
        repo = self._synth_tree(tmp_path)

        gate = run_cleanliness_gate(repo)
        out = tmp_path / "dist" / "out.zip"
        summary = create_release_zip(repo, out)

        gate_leaks = set(gate["internal_leaks"])
        pack_internal = set(summary.skipped_internal)
        # Independent-provenance anchor (the teeth): both backends must actually
        # flag every planted internal file. A classifier regression that stops
        # flagging one reds here even though the two backends still agree with
        # each other (the parity assert below).
        assert self._PLANTED_INTERNAL <= gate_leaks, (
            "Cleanliness gate stopped flagging planted internal files: "
            f"{sorted(self._PLANTED_INTERNAL - gate_leaks)}"
        )
        assert self._PLANTED_INTERNAL <= pack_internal, (
            "release_pack stopped skipping planted internal files: "
            f"{sorted(self._PLANTED_INTERNAL - pack_internal)}"
        )
        # Every path the gate flags as a leak must be excluded by release_pack
        # as an internal skip (not transient, not just missing).
        assert gate_leaks <= pack_internal, (
            f"Classification drift!\n"
            f"  gate leaks not in pack_internal: {gate_leaks - pack_internal}\n"
            f"  pack_internal extras: {pack_internal - gate_leaks}"
        )


class TestFullPreRelease:
    def test_skip_tests_and_pack(self, harness_repo):
        from espalier.pre_release import run_pre_release_check

        for fname in ("LICENSE", "CONTRIBUTING.md"):
            p = harness_repo / fname
            if not p.exists():
                p.write_text(f"# {fname}\n", encoding="utf-8")

        result = run_pre_release_check(
            harness_repo, skip_tests=True, skip_pack=True,
        )
        assert result["commands"] == []

    def test_skip_pack_leaves_release_pack_none(self, harness_repo):
        from espalier.pre_release import run_pre_release_check

        for fname in ("LICENSE", "CONTRIBUTING.md"):
            p = harness_repo / fname
            if not p.exists():
                p.write_text(f"# {fname}\n", encoding="utf-8")

        result = run_pre_release_check(
            harness_repo, skip_tests=True, skip_pack=True,
        )
        assert result["release_pack"] is None

    def test_parity_auto_skip_is_recorded_not_silent(self, harness_repo, monkeypatch):
        """TP-247a #1: when ``python -m build`` is not runnable, the parity
        AUTO-skip must be recorded in ``skipped_checks`` — a degraded audit
        trail — rather than green-passing byte-identically to a real parity
        PASS. Pre-fix the ``else`` branch set ``parity_report={"parity":
        "skipped"}`` with no ``skipped_checks`` entry, so a self-disabled
        release sub-layer was invisible to the exit-code/JSON audit trail the
        operator gates a publish on."""
        import espalier.pre_release as pr
        from espalier.pre_release import run_pre_release_check

        for fname in ("LICENSE", "CONTRIBUTING.md"):
            p = harness_repo / fname
            if not p.exists():
                p.write_text(f"# {fname}\n", encoding="utf-8")

        monkeypatch.setattr(pr, "_parity_runnable", lambda: False)
        result = run_pre_release_check(
            harness_repo, skip_tests=True, skip_pack=True,
        )
        # The auto-skip is now distinguishable from a verified PASS.
        assert any(
            "artifact-parity" in s and "runnable" in s.lower()
            for s in result["skipped_checks"]
        ), (
            f"parity auto-skip not recorded in skipped_checks; got "
            f"{result['skipped_checks']!r}"
        )
        # And it must NOT masquerade as an explicit --skip-parity opt-out.
        assert not any("--skip-parity" in s for s in result["skipped_checks"])
        assert result["artifact_parity"]["parity"] == "skipped"


# ---------------------------------------------------------------------------
# Surface-truth gate — self-host-only (Pack 17)
# ---------------------------------------------------------------------------

# Synthetic shape for the cleanliness-gate parity tests below. NOT the live
# surface count — `cc/PACK_MANIFEST.txt` (and the live-surface test in this
# file) is authoritative for the real count. The synthetic value just needs
# to match the synthetic README claim so the gate is exercised on a
# self-consistent fixture; keeping it distinct from the live count makes
# this independence explicit.
SYNTHETIC_COMMAND_COUNT_FOR_PARITY_TEST = 18
SYNTHETIC_AGENT_COUNT_FOR_PARITY_TEST = 6


def _make_self_host_shape(
    root: Path,
    agent_count: int = SYNTHETIC_AGENT_COUNT_FOR_PARITY_TEST,
    command_count: int = SYNTHETIC_COMMAND_COUNT_FOR_PARITY_TEST,
) -> None:
    """Build minimal synthetic self-host repo shape for surface-truth tests.

    `agent_count` and `command_count` are SYNTHETIC test fixture sizes,
    independent of the live surface count (see `cc/PACK_MANIFEST.txt`).

    TP-59 BC-035: `is_self_host_repo` now requires THREE signals --
    project name, bench/ directory, and a content-hash match on
    `tools/cc/hooks/write_guard.py`. This helper copies the live
    write_guard.py so the synthetic shape satisfies the pin.
    """
    (root / "espalier").mkdir(exist_ok=True)
    (root / "espalier" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (root / "tools" / "cc" / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "bench").mkdir(exist_ok=True)
    import shutil as _shutil
    live_write_guard = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks" / "write_guard.py"
    _shutil.copy(live_write_guard, root / "tools" / "cc" / "hooks" / "write_guard.py")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "espalier-harness"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "CONTRIBUTING.md").write_text("# Contributing\n", encoding="utf-8")
    agents_dir = root / ".claude" / "agents"
    commands_dir = root / ".claude" / "commands"
    agents_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)
    for i in range(agent_count):
        (agents_dir / f"agent-{i}.md").write_text(f"# agent {i}\n", encoding="utf-8")
    for i in range(command_count):
        (commands_dir / f"command-{i}.md").write_text(f"# command {i}\n", encoding="utf-8")


class TestSurfaceTruthGate:
    def test_stale_agent_count_fails_gate(self, tmp_path):
        _make_self_host_shape(tmp_path)
        (tmp_path / "README.md").write_text(
            "7 governance agents and 18 slash commands\n", encoding="utf-8"
        )
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        failure_text = " ".join(result["failures"])
        assert "6 governance agents" in failure_text

    def test_stale_command_count_fails_gate(self, tmp_path):
        _make_self_host_shape(tmp_path)
        (tmp_path / "README.md").write_text(
            "6 governance agents and 22 slash commands\n", encoding="utf-8"
        )
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        failure_text = " ".join(result["failures"])
        assert "18 slash commands" in failure_text

    def test_worktree_lanes_in_readme_fails_gate(self, tmp_path):
        _make_self_host_shape(tmp_path)
        (tmp_path / "README.md").write_text(
            "6 governance agents and 18 slash commands\nWORKTREE_LANES.md lives here\n",
            encoding="utf-8",
        )
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any("WORKTREE_LANES" in f for f in result["failures"])

    def test_worktree_lanes_in_surface_file_fails_gate(self, tmp_path):
        _make_self_host_shape(tmp_path)
        (tmp_path / "README.md").write_text(
            "6 governance agents and 18 slash commands\n", encoding="utf-8"
        )
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "CONVENTIONS.md").write_text(
            "See WORKTREE_LANES.md for lane config.\n", encoding="utf-8"
        )
        result = run_cleanliness_gate(tmp_path)
        assert result["status"] == "fail"
        assert any("CONVENTIONS.md" in f and "WORKTREE_LANES" in f for f in result["failures"])

    def test_clean_self_host_readme_passes_gate(self, tmp_path):
        _make_self_host_shape(tmp_path)
        (tmp_path / "README.md").write_text(
            "6 governance agents and 18 slash commands\n", encoding="utf-8"
        )
        result = run_cleanliness_gate(tmp_path)
        surface_failures = [f for f in result["failures"] if "governance agents" in f
                            or "slash commands" in f or "WORKTREE_LANES" in f]
        assert surface_failures == []

    def test_non_self_host_repo_skips_surface_check(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "7 governance agents and 22 slash commands and WORKTREE_LANES.md\n",
            encoding="utf-8",
        )
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        surface_failures = [f for f in result["failures"] if "governance agents" in f
                            or "slash commands" in f or "WORKTREE_LANES" in f]
        assert surface_failures == [], (
            "Surface-truth check should not run on non-self-host repos"
        )


# TP-28 cleanup: removed TestLiveCommandSurfaceCount.
# Pre-TP-31, `cc/PACK_MANIFEST.txt` listed bundled `.claude/commands/`
# entries and `espalier init` copied them verbatim to user repos, so
# manifest count and live count had to agree. Post-TP-31 the manifest
# is rendered from `get_packaged_surface().commands.paths` (the bundled
# tree, now empty); the self-host's own `.claude/commands/` are its
# own dogfooded usage, not a bundled surface. The two counts no longer
# describe the same thing.


# ---------------------------------------------------------------------------
# _run_command timeout tests (Pack 18)
# ---------------------------------------------------------------------------

class TestRunCommandTimeout:
    def test_normal_completion_returns_timed_out_false(self, tmp_path):
        from espalier.pre_release import _run_command
        result = _run_command(
            [sys.executable, "-c", "print('ok')"],
            tmp_path,
            timeout_seconds=10,
        )
        assert result["timed_out"] is False
        assert result["returncode"] == 0
        assert result["timeout_seconds"] == 10

    def test_normal_completion_captures_stdout(self, tmp_path):
        from espalier.pre_release import _run_command
        result = _run_command(
            [sys.executable, "-c", "print('hello')"],
            tmp_path,
            timeout_seconds=10,
        )
        assert "hello" in result["stdout"]

    def test_timeout_returns_code_124(self, tmp_path):
        from espalier.pre_release import TIMEOUT_RETURN_CODE, _run_command
        result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path,
            timeout_seconds=1,
        )
        assert result["returncode"] == TIMEOUT_RETURN_CODE

    def test_timeout_sets_timed_out_true(self, tmp_path):
        from espalier.pre_release import _run_command
        result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path,
            timeout_seconds=1,
        )
        assert result["timed_out"] is True

    def test_timeout_preserves_timeout_seconds(self, tmp_path):
        from espalier.pre_release import _run_command
        result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path,
            timeout_seconds=1,
        )
        assert result["timeout_seconds"] == 1

    def test_timeout_stderr_contains_message(self, tmp_path):
        from espalier.pre_release import _run_command
        result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path,
            timeout_seconds=1,
        )
        assert "Command timed out after" in result["stderr"]

    def test_timeout_partial_stdout_captured_safely(self, tmp_path):
        from espalier.pre_release import _run_command
        result = _run_command(
            [sys.executable, "-c", "import sys, time; print('starting'); sys.stdout.flush(); time.sleep(5)"],
            tmp_path,
            timeout_seconds=1,
        )
        assert result["timed_out"] is True
        assert isinstance(result["stdout"], str)
        assert isinstance(result["stderr"], str)


class TestPreReleaseTestLayerScope:
    """Pin the pre-release test layer's command shape + timeout.

    `espalier pre-release` used to run the full ``pytest -q`` under the 120s
    helper-command timeout — but the suite takes minutes (measured ~308s), so the
    test layer ALWAYS timed out: a guaranteed false-RED that no test caught. The
    timeout is env/scale-gated (it can't be earned-red on a fast host), so these
    lock the fix mechanically: the layer deselects the redundant ``heavy_e2e``
    matrix-smoke and uses its own realistic timeout. A revert to the 120s default,
    or dropping the marker filter, reds HERE instead of silently false-RED-ing a
    real release run.
    """

    def _capture_test_layer(self, tmp_path, monkeypatch):
        import espalier.pre_release as pr
        import espalier.self_hosting as sh

        calls: list[dict] = []

        def _fake_run_command(command, cwd, *, timeout_seconds=None):
            calls.append({"command": list(command), "timeout_seconds": timeout_seconds})
            return {
                "command": " ".join(command),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "timeout_seconds": timeout_seconds,
            }

        monkeypatch.setattr(pr, "_run_command", _fake_run_command)
        monkeypatch.setattr(
            sh, "run_self_host_check", lambda root: {"surface_gate_status": "pass"}
        )
        pr.run_pre_release_check(
            tmp_path, skip_tests=False, skip_pack=True, skip_parity=True
        )
        pytest_calls = [c for c in calls if "pytest" in c["command"]]
        assert len(pytest_calls) == 1, f"expected one pytest layer call, got {calls}"
        return pytest_calls[0]

    def test_test_layer_deselects_heavy_e2e(self, tmp_path, monkeypatch):
        cmd = self._capture_test_layer(tmp_path, monkeypatch)["command"]
        assert cmd[:4] == [sys.executable, "-m", "pytest", "-q"]
        # the redundant suite-spawning mega-test is deselected; everything else runs
        assert "-m" in cmd
        assert "not heavy_e2e" in cmd

    def test_test_layer_uses_realistic_timeout(self, tmp_path, monkeypatch):
        from espalier.pre_release import (
            DEFAULT_COMMAND_TIMEOUT_SECONDS,
            NOT_HEAVY_E2E_LEG_MEASURED_S,
            TEST_COMMAND_TIMEOUT_SECONDS,
        )

        layer = self._capture_test_layer(tmp_path, monkeypatch)
        captured = layer["timeout_seconds"]
        # the test command uses the dedicated ceiling, not the 120s helper default
        assert captured == TEST_COMMAND_TIMEOUT_SECONDS
        assert TEST_COMMAND_TIMEOUT_SECONDS > DEFAULT_COMMAND_TIMEOUT_SECONDS
        # DEF-917: the bound DERIVES from a recorded measurement of the leg,
        # never from a literal. The literal this row used to floor at 300 sat
        # at 600 against a leg the release matrix measured at 2,711 s on
        # 2026-09-23 (stage 02, the same selection, serial), and nothing here
        # could see the drift. A bound that is not twice the recorded leg reds.
        assert TEST_COMMAND_TIMEOUT_SECONDS == 2 * NOT_HEAVY_E2E_LEG_MEASURED_S
        # The floor is keyed to the MODE the leg runs in: while `_run_command`
        # builds a serial argv (no `-n`), the recorded leg cannot sit under the
        # serial measurement. DEF-918 moves the leg to xdist after the cut and
        # re-pins the constant at that mode's own figure -- a fraction of this
        # one -- so the floor must not read as "never lower the number".
        if "-n" not in layer["command"]:
            assert NOT_HEAVY_E2E_LEG_MEASURED_S >= 2711, (
                "the leg still runs serially, and the recorded figure fell below "
                "the matrix's 2026-09-23 serial measurement (2,711 s) -- re-measure "
                "in this mode, never lower it by hand"
            )

    def test_a_fired_bound_is_reported_as_a_bound_not_a_failed_suite(
        self, tmp_path, monkeypatch
    ):
        """DEF-917: when the test layer times out, the report names the bound
        in seconds and the constant to re-measure, and does NOT say the suite
        failed -- the shape `scripts/release_check.py::check_tests_pass` already
        reports one file over. Before this row a timed-out leg read as
        `test suite failed` on a tree whose code was fine."""
        import espalier.pre_release as pr
        import espalier.self_hosting as sh

        def _pytest_times_out(command, cwd, *, timeout_seconds=None):
            timed_out = "pytest" in command
            return {
                "command": " ".join(command),
                "returncode": pr.TIMEOUT_RETURN_CODE if timed_out else 0,
                "stdout": "",
                "stderr": "",
                "timed_out": timed_out,
                "timeout_seconds": timeout_seconds,
            }

        monkeypatch.setattr(pr, "_run_command", _pytest_times_out)
        monkeypatch.setattr(
            sh, "run_self_host_check", lambda root: {"surface_gate_status": "pass"}
        )
        result = pr.run_pre_release_check(
            tmp_path, skip_tests=False, skip_pack=True, skip_parity=True
        )
        timed = [f for f in result["failures"] if "TIMED OUT" in f]
        assert timed, f"no TIMED OUT failure in {result['failures']}"
        assert str(pr.TEST_COMMAND_TIMEOUT_SECONDS) in timed[0]
        assert "NOT_HEAVY_E2E_LEG_MEASURED_S" in timed[0]
        assert "test suite failed" not in result["failures"], (
            "a fired bound is not a failed suite; the report must not say it is"
        )

    def test_a_genuinely_failing_suite_is_still_reported_as_failed(
        self, tmp_path, monkeypatch
    ):
        """The other branch of the same `if`/`elif`: a red pytest leg that did
        NOT time out is `test suite failed`, with no bound line. Without this
        row, deleting the `elif` would report a red suite as a pass."""
        import espalier.pre_release as pr
        import espalier.self_hosting as sh

        def _pytest_fails(command, cwd, *, timeout_seconds=None):
            failing = "pytest" in command
            return {
                "command": " ".join(command),
                "returncode": 1 if failing else 0,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "timeout_seconds": timeout_seconds,
            }

        monkeypatch.setattr(pr, "_run_command", _pytest_fails)
        monkeypatch.setattr(
            sh, "run_self_host_check", lambda root: {"surface_gate_status": "pass"}
        )
        result = pr.run_pre_release_check(
            tmp_path, skip_tests=False, skip_pack=True, skip_parity=True
        )
        assert "test suite failed" in result["failures"], result["failures"]
        assert not [f for f in result["failures"] if "TIMED OUT" in f], result["failures"]


# ---------------------------------------------------------------------------
# Plan-guard regression coverage gate (Pack 19)
# ---------------------------------------------------------------------------

class TestPlanGuardRegressionCoverageGate:
    """run_cleanliness_gate must fail if plan-guard regression markers are absent."""

    def _make_self_host_with_tests(self, tmp_path: Path, test_content: str) -> Path:
        """Build a minimal self-host repo with a synthetic tests/ directory."""
        _make_self_host_shape(tmp_path)
        (tmp_path / "README.md").write_text(
            "6 governance agents and 18 slash commands\n", encoding="utf-8"
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_synthetic.py").write_text(test_content, encoding="utf-8")
        return tmp_path

    def test_all_markers_present_passes_gate(self, tmp_path):
        content = (
            "def test_plan_guard_checks_redirects_before_readonly_allowlist(): pass\n"
            "def test_plan_guard_blocks_inline_python_write(): pass\n"
            "def test_execution_plan_status_exits_nonzero_without_active_plan(): pass\n"
        )
        repo = self._make_self_host_with_tests(tmp_path, content)
        result = run_cleanliness_gate(repo)
        coverage_failures = [f for f in result["failures"] if "plan-guard regression" in f]
        assert coverage_failures == []

    def test_missing_redirect_marker_fails_gate(self, tmp_path):
        content = (
            "def test_plan_guard_blocks_inline_python_write(): pass\n"
            "def test_execution_plan_status_exits_nonzero_without_active_plan(): pass\n"
        )
        repo = self._make_self_host_with_tests(tmp_path, content)
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("checks_redirects_before_readonly_allowlist" in f for f in result["failures"])

    def test_missing_inline_python_marker_fails_gate(self, tmp_path):
        content = (
            "def test_plan_guard_checks_redirects_before_readonly_allowlist(): pass\n"
            "def test_execution_plan_status_exits_nonzero_without_active_plan(): pass\n"
        )
        repo = self._make_self_host_with_tests(tmp_path, content)
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("blocks_inline_python_write" in f for f in result["failures"])

    def test_missing_execution_plan_marker_fails_gate(self, tmp_path):
        content = (
            "def test_plan_guard_checks_redirects_before_readonly_allowlist(): pass\n"
            "def test_plan_guard_blocks_inline_python_write(): pass\n"
        )
        repo = self._make_self_host_with_tests(tmp_path, content)
        result = run_cleanliness_gate(repo)
        assert result["status"] == "fail"
        assert any("execution_plan_status_exits_nonzero_without_active_plan" in f for f in result["failures"])

    def test_non_self_host_repo_skips_coverage_check(self, tmp_path):
        """Coverage check must not run on non-self-host repos."""
        (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")
        _add_required_files(tmp_path)
        result = run_cleanliness_gate(tmp_path)
        coverage_failures = [f for f in result["failures"] if "plan-guard regression" in f]
        assert coverage_failures == []


# ── TP-142 (FM-3 §1.9 + §5.6): missing release_check.py must FAIL ─────


class TestReleaseCheckScriptMissing:
    """FM-3 §1.9 + §5.6 close: missing ``scripts/release_check.py`` is a
    FAIL, not a silent pass.

    Pre-fix the ``if gate_script.exists():`` branch in ``cmd_pre_release``
    silently produced ``gate_status="pass"`` with empty ``gate_results``
    when the script was absent — hiding wheel-only installs and
    accidental deletes. The operator most needs to be told about absence;
    silence is the worst possible signal.
    """

    @staticmethod
    def _make_namespace(repo: Path, *, skip_release_check: bool):
        import argparse
        return argparse.Namespace(
            repo=str(repo),
            output=str(repo / "dist" / "out.zip"),
            skip_tests=True,
            skip_pack=True,
            skip_parity=True,
            skip_release_check=skip_release_check,
        )

    def test_fails_when_gate_script_absent(self, harness_repo, capsys, as_self_host_tree):
        """No ``--skip-release-check``, no ``scripts/release_check.py``:
        gate_status=fail with an explicit release_check_present FAIL row."""
        import json
        from espalier.cli import cmd_pre_release

        gate_script = harness_repo / "scripts" / "release_check.py"
        if gate_script.exists():
            gate_script.unlink()

        for fname in ("LICENSE", "CONTRIBUTING.md"):
            p = harness_repo / fname
            if not p.exists():
                p.write_text(f"# {fname}\n", encoding="utf-8")

        args = self._make_namespace(harness_repo, skip_release_check=False)
        rc = cmd_pre_release(args)

        captured = capsys.readouterr()
        report = json.loads(captured.out)

        assert rc == 1, (
            f"missing gate script must produce non-zero exit; got rc={rc}"
        )
        assert report["release_check"]["status"] == "fail"
        names = {r["name"] for r in report["release_check"]["results"]}
        assert "release_check_present" in names, (
            f"expected release_check_present FAIL row; got {names}"
        )
        # Overall report must propagate the failure
        assert report["status"] == "fail"

    def test_skip_release_check_omits_gate_entirely(self, harness_repo, capsys, as_self_host_tree):
        """``--skip-release-check`` preserves the pre-fix bypass behavior:
        gate_results=[], gate_status="pass", regardless of script presence."""
        import json
        from espalier.cli import cmd_pre_release

        gate_script = harness_repo / "scripts" / "release_check.py"
        if gate_script.exists():
            gate_script.unlink()

        for fname in ("LICENSE", "CONTRIBUTING.md"):
            p = harness_repo / fname
            if not p.exists():
                p.write_text(f"# {fname}\n", encoding="utf-8")

        args = self._make_namespace(harness_repo, skip_release_check=True)
        cmd_pre_release(args)

        captured = capsys.readouterr()
        report = json.loads(captured.out)

        # Gate is omitted on opt-out; absence does not propagate.
        assert report["release_check"]["status"] == "pass"
        assert report["release_check"]["results"] == []
