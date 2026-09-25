"""DEF-410f, driven 2026-09-12: ``init`` leaves the adopter's fingerprint alone.

``cmd_init`` seeds ``docs/`` and THEN fingerprints, so on a three-file repo
with no ``docs/`` the saved fingerprint and the build plan read the directory
the seeds had just created as the adopter's docs surface -- a ``docs`` cue, a
``docs_surface`` signal and two docs conventions. The whole deploy is the
oracle here: a detector that reads a harness artifact as adopter code --
present or future, inline probe or ``iterdir`` walk -- fails in this module,
where the literal census in ``tests/test_analyze.py`` cannot see a walk.

An integration module, not a unit one, because the deploy is driven for real:
``cmd_init``'s gitignore and tracked-conflict paths shell out to git, and a
bare ``.git`` mkdir sends them down their degraded branch
(``tests/_adopter_tree.py`` records why). The suite contract keeps child
processes out of the ``unit`` slice, so the two tests live here rather than
beside the detectors they prove.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from espalier.analyze import fingerprint_repo
from espalier.cli import cmd_init, cmd_install_ci


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")


def _three_file_repo(root: Path) -> None:
    """The tree DEF-410f was driven on: a manifest, one module, a README and
    no ``docs/`` -- so after ``init`` every docs cue can only be the harness's."""
    (root / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1"\n', encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# app\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "adopter@example.invalid")
    _git(root, "config", "user.name", "Adopter")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")


def _init(root: Path) -> None:
    assert cmd_init(argparse.Namespace(repo=str(root), config=None)) == 0


def _differing_keys(before: dict, after: dict) -> dict[str, tuple[object, object]]:
    return {
        key: (before.get(key), after.get(key))
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }


class TestInitLeavesTheFingerprintAlone:
    def test_init_changes_no_fingerprint_field(self, tmp_path):
        _three_file_repo(tmp_path)
        before = fingerprint_repo(tmp_path).to_dict()
        _init(tmp_path)
        assert (tmp_path / "docs").is_dir()  # the seeds landed; they are just not the adopter's
        after = fingerprint_repo(tmp_path).to_dict()
        assert _differing_keys(before, after) == {}
        # init fingerprints after seeding: the copy it saves -- what the build
        # plan and doctor's drift check read -- must still be the adopter's.
        saved = json.loads((tmp_path / "reports" / "repo_fingerprint.json").read_text(encoding="utf-8"))
        assert _differing_keys(before, saved) == {}

    def test_install_ci_changes_only_the_ci_fact(self, tmp_path):
        _three_file_repo(tmp_path)
        _init(tmp_path)
        before = fingerprint_repo(tmp_path).to_dict()
        assert cmd_install_ci(argparse.Namespace(repo=str(tmp_path))) == 0
        after = fingerprint_repo(tmp_path).to_dict()
        # The one probe on a harness path the census exempts: the workflow
        # install-ci writes makes "this repo runs GitHub Actions" true, and
        # install-ci re-baselines the saved fingerprint itself (DEF-688).
        assert set(_differing_keys(before, after)) == {"ci_providers"}
        assert after["ci_providers"] == ["github_actions"]
