"""TP-30: ``espalier init`` must protect fresh repos from staging
machine-specific runtime state.

Pins the init guardrail against the pre-fix failure mode: a fresh
repo with no ``.gitignore`` got zero guidance from init, and the
most obvious next command (``git add -A``) silently staged
``.claude/settings.json`` (the machine's detected interpreter name),
``.espalier/integrity.json``, ``reports/harness_config.json``, and
``reports/repo_fingerprint.json`` — committing any of these would
have leaked machine-specific state into the shared repo history.

This test parametrizes on the two flows:

1. Suggest-only (default): init prints the warning; user is
   expected to act, but the staged-file check fails until they do.
2. ``--write-gitignore``: init writes the entries; staged-file
   check passes immediately.

Without this contract an init regression could silently drop the
warning OR the auto-write path, leaving the next adopter back at
the pre-TP-30 footgun.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from espalier.cli import REQUIRED_GITIGNORE


REQUIRED_IGNORE_PATHS = (
    ".claude/settings.json",
    ".espalier/",
    ".espalier-state/",
    "/reports/",
    "cc/blueprints/",
    "cc/_cold/",
    "cc/_working_summary.md",
    "__pycache__/",
    "*.pyc",
    ".claude/*.new",
    ".claude/*.bak",
    ".claude/*.bak.*",
    "/task-packs/",
)


def test_required_ignore_paths_match_cli_source() -> None:
    """Durable drift guard (TP-214..219 follow-up): this fixture's
    REQUIRED_IGNORE_PATHS must mirror ``cli.REQUIRED_GITIGNORE`` exactly, so a
    new managed-gitignore entry added to cli.py can never land without its
    init-protection coverage here."""
    assert set(REQUIRED_IGNORE_PATHS) == set(REQUIRED_GITIGNORE)


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"],
                   cwd=repo, check=True)


def _run_espalier_init(repo: Path, write_gitignore: bool = False) -> str:
    args = [sys.executable, "-m", "espalier.cli", "init"]
    # TP-119: default flipped to --write-gitignore-on. To preserve
    # this helper's historical intent (caller-explicit posture for
    # both branches), pass the matching explicit flag in each case.
    # ``write_gitignore=False`` originally meant "suggest-only flow"
    # (no flag passed, default was warn-only). Post-flip that gets
    # the auto-write flow unless we pass ``--no-write-gitignore``
    # explicitly.
    if write_gitignore:
        args.append("--write-gitignore")
    else:
        args.append("--no-write-gitignore")
    args.append(str(repo))
    result = subprocess.run(args, capture_output=True, text=True,
                            check=True, encoding="utf-8")
    return result.stdout


def _staged_after_add_all(repo: Path) -> list[str]:
    """Run `git add -A` and return staged paths."""
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    result = subprocess.run(
        ["git", "status", "--short", "--porcelain"],
        cwd=repo, capture_output=True, text=True, check=True, encoding="utf-8",
    )
    staged = []
    for line in result.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        path = line[3:].strip()
        staged.append(path)
    return staged


def _any_required_path_staged(staged: list[str]) -> list[str]:
    """Return staged paths that match REQUIRED_IGNORE_PATHS."""
    hits = []
    for path in staged:
        for required in REQUIRED_IGNORE_PATHS:
            # Staged paths are repo-relative and unanchored; a required entry
            # may carry git's root-anchor slash (DEF-429). Compare on the
            # unanchored form so `/reports/` still matches `reports/x.json`.
            bare = required.lstrip("/")
            if path == bare.rstrip("/"):
                hits.append(path)
                break
            if bare.endswith("/") and path.startswith(bare):
                hits.append(path)
                break
            if path == bare or path.startswith(bare.rstrip("/") + "/"):
                hits.append(path)
                break
    return hits


class TestFreshRepoGitignoreProtection:
    def test_suggest_default_warns_user(self, tmp_path):
        """Without --write-gitignore, init prints a warning."""
        _git_init(tmp_path)
        stdout = _run_espalier_init(tmp_path, write_gitignore=False)
        assert "WARN:" in stdout or "gitignore" in stdout.lower(), (
            f"init output should warn about missing gitignore.\n"
            f"stdout:\n{stdout}"
        )
        for required in REQUIRED_IGNORE_PATHS:
            assert required in stdout, (
                f"Suggest-only init should print {required!r} in the "
                f"copy-paste block.\n"
                f"stdout:\n{stdout}"
            )

    def test_write_gitignore_appends_entries(self, tmp_path):
        """--write-gitignore creates .gitignore with all required entries."""
        _git_init(tmp_path)
        _run_espalier_init(tmp_path, write_gitignore=True)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists(), (
            "--write-gitignore did not create .gitignore"
        )
        gi_text = gitignore.read_text(encoding="utf-8")
        for required in REQUIRED_IGNORE_PATHS:
            assert required in gi_text, (
                f".gitignore is missing {required!r} after "
                f"--write-gitignore.\n"
                f".gitignore contents:\n{gi_text}"
            )

    def test_write_gitignore_blocks_git_add_all(self, tmp_path):
        """After --write-gitignore, `git add -A` stages no required-ignore paths."""
        _git_init(tmp_path)
        _run_espalier_init(tmp_path, write_gitignore=True)
        staged = _staged_after_add_all(tmp_path)
        leaked = _any_required_path_staged(staged)
        assert not leaked, (
            "After --write-gitignore + git add -A, the following "
            "machine-specific paths were staged:\n  "
            + "\n  ".join(leaked)
            + "\n\nFull staged list:\n  "
            + "\n  ".join(staged)
        )

    def test_existing_gitignore_gets_missing_entries_appended(self, tmp_path):
        """If .gitignore exists but lacks entries, --write-gitignore adds them."""
        _git_init(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("# pre-existing user entries\n*.log\n", encoding="utf-8")
        _run_espalier_init(tmp_path, write_gitignore=True)
        gi_text = gitignore.read_text(encoding="utf-8")
        assert "*.log" in gi_text, (
            "User's pre-existing .gitignore content was clobbered. "
            "--write-gitignore must APPEND, not overwrite."
        )
        for required in REQUIRED_IGNORE_PATHS:
            assert required in gi_text, (
                f"Missing {required!r} after --write-gitignore append."
            )


class TestAdopterOwnedPathsSurviveInit:
    """DEF-429 / DEF-11 (§1A rows 2 and 14, §C13): the entries init appends
    must not reach past the harness's own runtime state into paths the
    adopter owns."""

    def test_nested_reports_dir_is_not_ignored(self, tmp_path):
        """DEF-429: the ``reports/`` entry must be ROOT-anchored.

        Git treats a pattern with no leading or embedded separator as
        matching at any depth, so a bare ``reports/`` also excludes an
        adopter's ``src/analytics/reports/`` -- a Django/Rails reports app,
        a dashboard module, a directory of committed templates. Driven
        against real git pre-fix: ``git check-ignore`` attributes the nested
        file to the appended ``reports/`` line and ``git add -A`` stages
        only ``.gitignore``, so the adopter's new file silently never
        reaches a commit.
        """
        _git_init(tmp_path)
        nested = tmp_path / "src" / "analytics" / "reports"
        nested.mkdir(parents=True)
        (nested / "q3.md").write_text("committed template\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "adopter source"],
                       cwd=tmp_path, check=True)

        _run_espalier_init(tmp_path, write_gitignore=True)

        # The adopter adds a NEW file under their own reports module.
        (nested / "q4.md").write_text("new template\n", encoding="utf-8")
        staged = _staged_after_add_all(tmp_path)
        assert "src/analytics/reports/q4.md" in staged, (
            "init's gitignore entry reached into the adopter's nested "
            "reports/ directory: a new file there was not staged by "
            "`git add -A`.\n\nFull staged list:\n  " + "\n  ".join(staged)
        )

    def test_tracked_path_is_not_newly_ignored(self, tmp_path):
        """DEF-11: init must not ignore a path the host already tracks.

        A team that commits its own ``.claude/settings.json`` ends up with a
        file that is BOTH git-tracked and git-ignored. The state is close to
        invisible: ``git check-ignore`` -- the one diagnostic an adopter
        reaches for -- skips indexed paths unless ``--no-index`` is passed,
        so it reports nothing at all. init must leave the entry out and name
        the remedy instead of silently creating that state.
        """
        _git_init(tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "adopter settings"],
                       cwd=tmp_path, check=True)

        stdout = _run_espalier_init(tmp_path, write_gitignore=True)

        gi_text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        gi_lines = {ln.strip() for ln in gi_text.splitlines()}
        assert ".claude/settings.json" not in gi_lines, (
            "init ignored a path the host already tracks, leaving "
            ".claude/settings.json both git-tracked and git-ignored.\n"
            f".gitignore contents:\n{gi_text}"
        )
        # Pin the remedy's IDENTITY -- untrack this exact path, with `--` so a
        # path that looks like an option or a glob cannot reach the operator's
        # shell as one -- but not the surrounding flag spelling.
        assert "git rm" in stdout and "--cached -- .claude/settings.json" in stdout, (
            "init withheld the already-tracked entry but never told the "
            f"operator, or gave no copy-pasteable remedy.\nstdout:\n{stdout}"
        )

    def test_shared_directory_still_protects_harness_state(self, tmp_path):
        """The ownership check must not trade a real leak for a cosmetic one.

        An adopter who tracks their own file under a directory the harness
        also writes to (``reports/2025-summary.md``) shares that namespace --
        they do not own the harness's ``repo_fingerprint.json`` sitting
        beside it. Withholding the whole ``/reports/`` entry on that ground
        sends the harness's machine-specific state straight into the
        adopter's shared history, which is the leak this whole tuple exists
        to prevent. Found by driving `init` on a real tree, not by the
        suite -- the earlier tests all used repos that tracked nothing under
        reports/.

        Writing the entry is safe for the adopter: git ignores nothing that
        is already tracked, so their committed file goes on staging and
        committing exactly as before (driven separately against real git).
        """
        _git_init(tmp_path)
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "2025-summary.md").write_text("legacy\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "adopter reports"],
                       cwd=tmp_path, check=True)

        _run_espalier_init(tmp_path, write_gitignore=True)

        staged = _staged_after_add_all(tmp_path)
        leaked = [p for p in staged if p.startswith("reports/")
                  and p != "reports/2025-summary.md"]
        assert not leaked, (
            "init withheld the shared /reports/ entry, so the harness's own "
            "generated state was staged into the adopter's history:\n  "
            + "\n  ".join(leaked)
        )
        # And the adopter's own tracked file is undisturbed.
        assert (reports / "2025-summary.md").exists()
