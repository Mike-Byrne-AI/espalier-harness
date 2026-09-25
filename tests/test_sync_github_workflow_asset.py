"""Behaviour tests for ``scripts/sync_github_workflow_asset.py``.

The script syncs the ONE mirror in this repo that runs packaged-asset -> repo
root. Its siblings each have a test module; this one shipped without and the
gap is the reason these exist: a cited ``--check`` that silently mutates and
exits 0 is a failure this repo has already had once, and the surface pin in
``tests/_surface_expected.py`` pins the script's NAME, not its behaviour.

The destructive-default case matters more here than for any other sync. Every
other workflow in ``.github/workflows/`` is edited in place, so the habitual
move is to edit the generated file -- and a sync that then overwrites it prints
"synced" and exits 0.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "sync_github_workflow_asset.py"

ASSET_REL = "espalier/assets/github/workflows/harness-guard.yml"
ROOT_REL = ".github/workflows/harness-guard.yml"


def _load(root: Path):
    """Load the script with its module-level ``_ROOT`` repointed at ``root``."""
    spec = importlib.util.spec_from_file_location(
        f"_sync_ghwa_{root.name}", SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ROOT = root
    return mod


def _commit(root: Path, message: str) -> None:
    """Stage everything and commit, immune to a global signing default.

    Same `-c` belt-and-braces as the ``tree`` fixture below, and for the same
    reason -- see its comments.
    """
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit", "-qm", message],
        cwd=root, check=True,
    )


def _git_status_clean(root: Path) -> bool:
    """True when git reports no uncommitted changes anywhere in ``root``."""
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root,
        capture_output=True, text=True, check=True, encoding="utf-8",
    )
    return not out.stdout.strip()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A tmp repo with both sides present, in parity, and git-clean."""
    asset = tmp_path / ASSET_REL
    rootf = tmp_path / ROOT_REL
    asset.parent.mkdir(parents=True)
    rootf.parent.mkdir(parents=True)
    asset.write_text("name: guard\n", encoding="utf-8")
    rootf.write_text("name: guard\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    # Immune to a global commit.gpgsign — same fix, same reason, as
    # tests/test_nested_repo_litter.py:32. Without it every fixture that commits
    # errors on a machine that signs by default.
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    # `-c` on the command line outranks BOTH repo-local config and the
    # GIT_CONFIG_* environment form, so the commit survives a signing default set
    # either way. The repo-local write above is kept because it also covers git
    # invocations this fixture does not make.
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit", "-qm", "seed"],
        cwd=tmp_path, check=True,
    )
    return tmp_path


class TestCheckMode:
    def test_check_passes_when_in_parity(self, tree, capsys):
        assert _load(tree).main(["--check"]) == 0

    def test_check_reports_drift_without_writing(self, tree):
        (tree / ROOT_REL).write_text("name: hand-edited\n", encoding="utf-8")
        before = (tree / ROOT_REL).read_bytes()
        assert _load(tree).main(["--check"]) == 1
        # The cited-but-mutating --check is the failure this pins against.
        assert (tree / ROOT_REL).read_bytes() == before

    def test_check_names_the_direction_on_drift(self, tree, capsys):
        (tree / ROOT_REL).write_text("name: hand-edited\n", encoding="utf-8")
        _load(tree).main(["--check"])
        err = capsys.readouterr().err
        assert "source of truth" in err and "generated" in err


class TestSync:
    def test_sync_copies_asset_over_root(self, tree):
        (tree / ASSET_REL).write_text("name: updated\n", encoding="utf-8")
        assert _load(tree).main([]) == 0
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: updated\n"

    def test_refuses_to_clobber_a_dirty_root_file(self, tree, capsys):
        """The whole point of the guard.

        Root file edited but not committed, asset unchanged: syncing would
        silently discard the edit and report success.
        """
        (tree / ROOT_REL).write_text("name: my-uncommitted-work\n", encoding="utf-8")
        assert _load(tree).main([]) == 1
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: my-uncommitted-work\n"
        assert "REFUSING" in capsys.readouterr().err

    def test_refusal_does_not_claim_uncommitted_changes_when_git_cannot_answer(
        self, tmp_path, capsys, monkeypatch
    ):
        """A refusal must not assert a fact it never established.

        In a git-less container or an unpacked sdist the status probe cannot
        answer. Refusing is right; saying "it has uncommitted changes" is not --
        and a refusal with a false stated reason is the kind a reader learns to
        --force past, which disables the protection for the case it exists for.
        """
        asset = tmp_path / ASSET_REL
        rootf = tmp_path / ROOT_REL
        asset.parent.mkdir(parents=True)
        rootf.parent.mkdir(parents=True)
        asset.write_text("name: asset\n", encoding="utf-8")
        rootf.write_text("name: differs\n", encoding="utf-8")  # no git init at all
        mod = _load(tmp_path)
        assert mod.main([]) == 1
        err = capsys.readouterr().err
        assert "git could not report its status" in err
        assert "it has uncommitted changes" not in err
        assert rootf.read_text(encoding="utf-8") == "name: differs\n"

    def test_force_overrides_the_dirty_guard(self, tree):
        (tree / ROOT_REL).write_text("name: my-uncommitted-work\n", encoding="utf-8")
        assert _load(tree).main(["--force"]) == 0
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: guard\n"

    def test_clean_root_syncs_without_force(self, tree):
        """The guard must not block the ordinary case -- a committed root file
        that drifted because the ASSET moved."""
        (tree / ASSET_REL).write_text("name: asset-moved\n", encoding="utf-8")
        assert _load(tree).main([]) == 0
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: asset-moved\n"

    def test_refuses_when_the_root_side_edit_was_committed(self, tree, capsys):
        """The cleanliness proxy's blind spot: a COMMITTED root-side edit.

        ``git status`` clean was standing in for "the root carries no unmirrored
        work", and a commit falsifies the proxy while leaving the fact it stands
        for unchanged. Measured before the fix: the script printed "synced",
        exited 0, and the committed edit was gone.

        Note what this does NOT rely on: the sibling above
        (``test_clean_root_syncs_without_force``) is the other half of the same
        oracle, and the two differ ONLY in which side moved. A guard that reds
        here by refusing everything clean would red there too, so the pair is
        what makes either meaningful.
        """
        (tree / ROOT_REL).write_text("name: committed-root-work\n", encoding="utf-8")
        _commit(tree, "root-side edit, committed")
        assert _git_status_clean(tree), "fixture precondition: git must report clean"

        assert _load(tree).main([]) == 1
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: committed-root-work\n"
        err = capsys.readouterr().err
        assert "REFUSING" in err
        # The reason must name the committed case. "it has uncommitted changes"
        # here would be the false-stated-reason failure the sibling test pins.
        assert "committed" in err and "uncommitted changes" not in err

    def test_verdict_does_not_depend_on_commit_timestamps(self, tree, capsys):
        """Two commits in the same second must still resolve correctly.

        The first cut of this guard compared ``git log --format=%ct`` and let the
        dangerous case straight through in its own earn-the-red: the fixture's
        two commits landed in the same second, so ``root > asset`` was false and
        the sync proceeded. Committer dates are also reordered by rebase and
        settable by env. This drives the shape with NO sleep between the commits,
        so it reds against any timestamp-based implementation.
        """
        (tree / ROOT_REL).write_text("name: same-second-root-edit\n", encoding="utf-8")
        _commit(tree, "root edit in the same second as the seed")
        assert _load(tree).main([]) == 1
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: same-second-root-edit\n"

    def test_a_root_only_sync_commit_is_not_treated_as_unmirrored_work(self, tree):
        """The negative twin of the committed-root guard, and the one that
        killed the second implementation.

        Ordinary workflow: commit an asset edit (forgetting the sync -- which is
        what a parity red actually produces), run the sync, commit the regenerated
        root on its own. The root's last commit now DESCENDS the asset's forever,
        so an ancestry-based guard refuses every later asset edit, with a stated
        reason that is false ("the root file carries a committed edit") and no
        exit but ``--force``. That is precisely the failure ``_root_file_status``'s
        own docstring forbids: a refusal with a false reason is one the reader
        learns to bypass, and the bypass disables the guard for the case it exists
        for.

        Content-at-the-root's-last-commit resolves it: a sync commit leaves the
        two sides EQUAL, so there is nothing to protect.
        """
        (tree / ASSET_REL).write_text("name: v2\n", encoding="utf-8")
        _commit(tree, "asset edit, sync forgotten")
        assert _load(tree).main([]) == 0          # the sync itself
        _commit(tree, "sync: regenerate root from asset")

        (tree / ASSET_REL).write_text("name: v3\n", encoding="utf-8")
        assert _load(tree).main([]) == 0, (
            "the ordinary asset-edit workflow was refused after a root-only sync "
            "commit -- the guard has become sticky and trains the operator to --force"
        )
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: v3\n"

    def test_a_root_hand_edit_in_the_SAME_commit_as_an_asset_change_is_refused(
        self, tree, capsys
    ):
        """Both sides changed in one commit: equal SHAs, both clean, still dangerous.

        A broad ``git add -A`` is this repo's own self-host convention, so an
        unrelated asset change and a root hand-edit landing in one commit is a
        live shape, not a contrivance. Any oracle that ORDERS the two commits
        reports "same commit -> the root did not move after the asset" and lets
        the copy through -- reproducing the original silent discard inside the fix
        written to prevent it. Comparing the two sides' content at that commit
        sees the divergence regardless of ordering.
        """
        (tree / ASSET_REL).write_text("name: asset-v2\n", encoding="utf-8")
        (tree / ROOT_REL).write_text("name: root-handedit\n", encoding="utf-8")
        _commit(tree, "git add -A: asset change and root hand-edit together")
        assert _git_status_clean(tree), "fixture precondition: both sides committed"

        assert _load(tree).main([]) == 1
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: root-handedit\n"
        assert "REFUSING" in capsys.readouterr().err

    def test_an_asset_added_after_the_roots_last_commit_still_syncs(self, tree):
        """``git show <root_sha>:<asset>`` failing means the asset is NEWER.

        Reading that as "cannot determine -> refuse" would block the legitimate
        case where the asset joined the tree after the root's last commit. The
        failure direction of an unreadable side must be argued, not defaulted.
        """
        subprocess.run(["git", "rm", "-q", "--cached", ASSET_REL], cwd=tree, check=True)
        (tree / ASSET_REL).unlink()
        _commit(tree, "remove the asset")
        (tree / ASSET_REL).parent.mkdir(parents=True, exist_ok=True)
        (tree / ASSET_REL).write_text("name: new-asset\n", encoding="utf-8")
        _commit(tree, "add the asset back, later than the root's last commit")

        assert _load(tree).main([]) == 0
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: new-asset\n"

    def test_force_overrides_the_committed_root_guard(self, tree):
        """--force stays the one escape, for both refusal reasons."""
        (tree / ROOT_REL).write_text("name: committed-root-work\n", encoding="utf-8")
        _commit(tree, "root-side edit, committed")
        assert _load(tree).main(["--force"]) == 0
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: guard\n"


class TestSourceGuards:
    def test_missing_source_is_an_error(self, tree, capsys):
        (tree / ASSET_REL).unlink()
        assert _load(tree).main([]) == 1
        assert "missing source of truth" in capsys.readouterr().err

    def test_empty_source_is_refused(self, tree, capsys):
        """Matches sync_vendor_cc.py and sync_claude_mirrors.py. Without it a
        truncated asset propagates and silently disables the workflow."""
        (tree / ASSET_REL).write_text("", encoding="utf-8")
        assert _load(tree).main([]) == 1
        assert "EMPTY source" in capsys.readouterr().err
        assert (tree / ROOT_REL).read_text(encoding="utf-8") == "name: guard\n"


def test_live_repo_is_in_parity():
    """The real tree, not a fixture -- the drift this script exists to catch."""
    assert (REPO / ASSET_REL).read_bytes() == (REPO / ROOT_REL).read_bytes(), (
        "harness-guard workflow drifted; run scripts/sync_github_workflow_asset.py"
    )


def test_script_is_importable_without_side_effects():
    assert SCRIPT.is_file()
    assert sys.version_info >= (3, 10)
