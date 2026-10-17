"""TP-54 — deploy helper contract tests for ``espalier.cli``.

Pins three TP-54 sub-task contracts landing in the deploy helpers:

- ``TestDeployAssetIdempotency`` (sub-task 1-B / F3): rerunning init on
  an unchanged repo reports ``skipped_no_drift`` for ``.md`` assets
  instead of always claiming ``updated_managed`` — without this
  contract a re-init on a clean repo would silently re-stamp every
  managed file and dirty the git tree on every harness upgrade.
- ``TestDeployAtomicity`` (sub-task 1-C / F2): all deploy-helper writes
  route through ``atomic_write_text`` (no naked ``Path.write_text``
  calls), preventing the half-written-file class of bug if init
  crashes mid-deploy.
- ``TestDeployIterationInvariant`` (sub-task 1-D / BC-030/031):
  ``deploy_harness`` iterates over packaged-source enumeration at
  import time; mutating ``cc/PACK_MANIFEST.txt`` (the deploy *report*)
  does not change the deploy *set* — a regression here would let a
  hand-edit to the report silently delete files from future deploys.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from tests._source_segment import segment, source_lines
from tests._live_tree import checkout_glob, checkout_rglob
from tests._quiet_git import NO_BACKGROUND_GIT, background_git_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "espalier" / "cli.py"


def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / "README.md").write_text("# target\n", encoding="utf-8")
    subprocess.check_call(["git", "init", "--quiet"], cwd=str(target))
    return target


def _run_init(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(target)],
        capture_output=True, text=True, timeout=45, check=True, encoding="utf-8",
    )


def _summary_int(out: str, key: str) -> int:
    for line in out.splitlines():
        if f"{key}:" in line:
            return int(line.split(f"{key}:")[1].strip().split()[0])
    pytest.fail(f"summary key {key!r} not found in stdout:\n{out}")


# ---------------------------------------------------------------------------
# Sub-task 1-B / F3 — _deploy_asset_md gains skipped_no_drift
# ---------------------------------------------------------------------------


class TestDeployAssetIdempotency:
    """Rerunning init on an unchanged repo must report ``skipped_no_drift``
    for ``.md`` assets that already match the packaged copy.

    Pre-TP-54 ``_deploy_asset_md`` returned ``updated_managed`` even when
    content was byte-identical to the packaged source, so every rerun
    surfaced spurious "updated" drift in the init report and (worse)
    rewrote the file on disk for no reason. The fix adds the no-drift
    early return matching ``_deploy_managed_py``'s four-state shape.
    """

    def test_second_init_reports_skipped_no_drift(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        result = _run_init(target)
        out = result.stdout
        assert "skipped_no_drift:" in out, (
            "init summary missing skipped_no_drift counter:\n" + out
        )
        n_no_drift = _summary_int(out, "skipped_no_drift")
        assert n_no_drift > 0, (
            f"expected skipped_no_drift > 0 on rerun, got {n_no_drift}"
        )

    def test_second_init_does_not_report_updated_managed_for_md_assets(
        self, tmp_path,
    ):
        target = _make_target(tmp_path)
        _run_init(target)
        result = _run_init(target)
        out = result.stdout
        n_updated = _summary_int(out, "updated_managed")
        n_no_drift = _summary_int(out, "skipped_no_drift")
        assert n_no_drift > n_updated, (
            "rerun on unchanged repo: no_drift should dominate updated "
            f"(got no_drift={n_no_drift}, updated_managed={n_updated})"
        )

    def test_deploy_asset_md_returns_skipped_no_drift_directly(self, tmp_path):
        from espalier.cli import _deploy_asset_md
        from espalier.managed_markers import apply_marker_to_md
        src = tmp_path / "src.md"
        body = "# heading\n\nbody\n"
        src.write_text(body, encoding="utf-8")
        dest = tmp_path / "dest.md"
        dest.write_text(apply_marker_to_md(body), encoding="utf-8")
        assert _deploy_asset_md(src, dest) == "skipped_no_drift"

    def test_deploy_asset_md_returns_updated_managed_on_drift(self, tmp_path):
        from espalier.cli import _deploy_asset_md
        from espalier.managed_markers import apply_marker_to_md
        src = tmp_path / "src.md"
        src.write_text("# new body\n", encoding="utf-8")
        dest = tmp_path / "dest.md"
        dest.write_text(apply_marker_to_md("# old body\n"), encoding="utf-8")
        assert _deploy_asset_md(src, dest) == "updated_managed"

    def test_deploy_asset_md_non_utf8_dest_degrades_to_skipped_user_file(
        self, tmp_path
    ):
        # TP-313b ITEM C: parity with _deploy_managed_py — a pre-existing dest
        # that is unreadable / not valid UTF-8 must degrade to skipped_user_file
        # (preserve the user's file), not raise UnicodeDecodeError and abort the
        # whole init.
        from espalier.cli import _deploy_asset_md
        src = tmp_path / "src.md"
        src.write_text("# heading\n\nbody\n", encoding="utf-8")
        dest = tmp_path / "dest.md"
        dest.write_bytes(b"\xff\xfe\x00 not valid utf-8 \xff")
        assert _deploy_asset_md(src, dest) == "skipped_user_file"


# ---------------------------------------------------------------------------
# Sub-task 1-C / F2 — atomic_write_text at every deploy site
# ---------------------------------------------------------------------------


class TestDeployAtomicity:
    """No deploy helper or ``deploy_harness`` may call ``Path.write_text``
    directly. All writes must route through ``atomic_write_text`` so a
    concurrent SessionStart reading the file during an init rerun cannot
    observe a torn write.

    Superseded in scope by
    ``tests/test_atomic_io.py::TestEveryEngineWriteOfAdopterStateIsAtomic``,
    which censuses every raw write in ``espalier/`` by AST and owns the
    exemption rosters; this class survives as the cli.py-specific
    no-exemption floor for the deploy helpers.

    AST-level enforcement: walks the parsed module and asserts no
    ``Attribute(attr='write_text')`` calls survive in the deploy helpers
    or in ``deploy_harness``.
    """

    _DEPLOY_FUNCTIONS = frozenset({
        "_write_seed",
        "_deploy_managed_py",
        "_deploy_asset_md",
        "deploy_harness",
    })

    def _collect_write_text_calls(self, func: ast.FunctionDef) -> list[int]:
        offenders: list[int] = []
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                callee = node.func
                if (
                    isinstance(callee, ast.Attribute)
                    and callee.attr == "write_text"
                ):
                    offenders.append(node.lineno)
        return offenders

    def test_no_naked_write_text_in_deploy_helpers(self):
        tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
        offenders: dict[str, list[int]] = {}
        walked: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name in self._DEPLOY_FUNCTIONS
            ):
                walked.add(node.name)
                hits = self._collect_write_text_calls(node)
                if hits:
                    offenders[node.name] = hits
        # A name-keyed roster is blind to a rename: when `_deploy_file` became
        # `_write_seed` (2026-09-05) this test stayed green while walking one
        # function fewer. Every rostered helper must be found, or the contract
        # has silently stopped covering a writer.
        assert walked == self._DEPLOY_FUNCTIONS, (
            f"deploy helpers not found in cli.py (renamed or removed?): "
            f"{sorted(self._DEPLOY_FUNCTIONS - walked)}"
        )
        assert not offenders, (
            "Naked Path.write_text() calls found in deploy helpers — "
            "must route through atomic_write_text. "
            f"Offenders: {offenders}"
        )

    def test_no_naked_write_text_anywhere_in_cli(self):
        """Derived, not rostered: the roster above catches a rostered helper
        that vanished; it cannot catch a NEW writer nobody listed. cli.py has
        zero naked `write_text` calls today, so the stronger contract is free --
        every text write in the module routes through atomic_write_text."""
        tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
        hits = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
        ]
        assert not hits, f"naked Path.write_text in cli.py at lines {hits}"

    def test_atomic_write_text_imported(self):
        tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
        imported = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "espalier._atomic_io":
                    for alias in node.names:
                        if alias.name == "atomic_write_text":
                            imported = True
                            break
        assert imported, (
            "espalier/cli.py must import atomic_write_text from espalier._atomic_io"
        )


# ---------------------------------------------------------------------------
# Sub-task 1-D / BC-030/031 — packaged-source iteration invariant
# ---------------------------------------------------------------------------


class TestDeployIterationInvariant:
    """``deploy_harness`` iterates over packaged-source enumeration, not
    over ``cc/PACK_MANIFEST.txt`` on disk. The manifest is a *report* of
    what was deployed, not the *authority* for what to deploy.

    BC-030/031: if iteration consulted the on-disk manifest, an attacker
    who can write to it could silently shrink the deploy set — a hand-
    disabled hook would never get regenerated.
    """

    def test_mutated_manifest_does_not_shrink_deploy_set(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        manifest = target / "cc" / "PACK_MANIFEST.txt"
        original = manifest.read_text(encoding="utf-8")
        hook_path = target / "tools" / "cc" / "hooks" / "write_guard.py"
        assert hook_path.is_file(), (
            "fixture invariant: write_guard.py should be deployed on init"
        )
        # Prune the write_guard line from the manifest and delete the hook.
        # If deploy_harness iterates the on-disk manifest, the second init
        # will not regenerate write_guard.py and the file stays missing.
        pruned = "\n".join(
            line for line in original.splitlines()
            if "write_guard" not in line
        ) + "\n"
        manifest.write_text(pruned, encoding="utf-8")
        hook_path.unlink()
        assert not hook_path.exists()
        _run_init(target)
        assert hook_path.is_file(), (
            "BC-031: deploy_harness must re-deploy write_guard.py from "
            "packaged source even when cc/PACK_MANIFEST.txt was pruned"
        )

    def test_emptied_manifest_does_not_shrink_deploy_set(self, tmp_path):
        target = _make_target(tmp_path)
        _run_init(target)
        manifest = target / "cc" / "PACK_MANIFEST.txt"
        # Replace the manifest with the marker only — drop every entry.
        manifest.write_text(
            "# espalier:managed\n", encoding="utf-8",
        )
        for hook_name in ("write_guard.py", "stop_gate.py", "session_start.py"):
            (target / "tools" / "cc" / "hooks" / hook_name).unlink(
                missing_ok=True,
            )
        _run_init(target)
        for hook_name in ("write_guard.py", "stop_gate.py", "session_start.py"):
            hook_path = target / "tools" / "cc" / "hooks" / hook_name
            assert hook_path.is_file(), (
                f"BC-031: {hook_name} must be re-deployed even after the "
                f"on-disk manifest was emptied"
            )

    def test_deploy_harness_docstring_documents_invariant(self):
        from espalier.cli import deploy_harness
        doc = deploy_harness.__doc__ or ""
        assert "iteration invariant" in doc.lower() or "BC-030" in doc or "BC-031" in doc, (
            "deploy_harness docstring must document the packaged-source "
            "iteration invariant (TP-54 BC-030/031)"
        )

    def test_deploy_harness_does_not_read_pack_manifest(self):
        """Static check: deploy_harness body must not reference
        ``PACK_MANIFEST.txt`` as a read source. The manifest is written
        by ``write_required_surface`` post-deploy as a *report*.
        """
        text = CLI_PATH.read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = source_lines(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "deploy_harness":
                source_segment = segment(lines, node) or ""
                offenders = [
                    line for line in source_segment.splitlines()
                    if "PACK_MANIFEST" in line
                    and "read_text" in line
                ]
                assert not offenders, (
                    "deploy_harness must not read PACK_MANIFEST.txt as "
                    "iteration source. Offending lines: " + "\n".join(offenders)
                )
                return
        pytest.fail("deploy_harness function not found in espalier/cli.py")


class TestDeployRefusesAClaudeItCannotSearch:
    """DEF-763: the two library functions behind `init` and `upgrade` raise
    `PermissionError` for a caller on a `.claude` that denies traversal --
    never a silent deploy and never a "would create" tally. The CLI
    pre-flights refuse first, so these raises are unreachable through the
    commands; pinned here so a caller that skips the pre-flight
    (`fuse_repos` is one import away) gets the loud answer on every
    interpreter."""

    def test_deploy_harness_raises_and_names_the_directory(self, tmp_path):
        from _locked import locked
        from espalier.analyze import fingerprint_repo
        from espalier.cli import deploy_harness
        from espalier.models import BuildPlan

        (tmp_path / ".git").mkdir()
        (tmp_path / ".claude").mkdir()
        fp = fingerprint_repo(tmp_path)
        plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
        with locked(tmp_path / ".claude"), pytest.raises(PermissionError) as raised:
            deploy_harness(tmp_path, plan, fp)
        assert ".claude" in str(raised.value), raised.value

    def test_preview_managed_surface_raises_instead_of_would_create(self, tmp_path):
        from _locked import locked
        from espalier.cli import preview_managed_surface

        (tmp_path / ".git").mkdir()
        (tmp_path / ".claude").mkdir()
        with locked(tmp_path / ".claude"), pytest.raises(PermissionError) as raised:
            preview_managed_surface(tmp_path, goal_snapshot=True)
        assert ".claude" in str(raised.value), raised.value


def test_surface_skipped_user_file_not_double_counted_in_deployed(tmp_path):
    """TP-174b R15: a cc/ surface doc the operator hand-edited (managed marker
    dropped) classifies skipped_user_file on re-deploy and must NOT also appear
    in `deployed` — the prior unconditional append double-counted it."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import deploy_harness
    from espalier.models import BuildPlan

    (tmp_path / ".git").mkdir()
    fp = fingerprint_repo(tmp_path)
    plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
    deploy_harness(tmp_path, plan, fp)  # first deploy writes cc/ surfaces w/ markers
    commands = tmp_path / "cc" / "COMMANDS.md"
    commands.write_text(
        commands.read_text(encoding="utf-8").replace(
            "<!-- espalier:managed -->", "<!-- user edited -->"
        ),
        encoding="utf-8",
    )
    result = deploy_harness(tmp_path, plan, fp)
    assert "cc/COMMANDS.md" in result["skipped_user_files"]
    assert "cc/COMMANDS.md" not in result["deployed"]


def test_surface_no_drift_not_counted_as_deployed(tmp_path):
    """TP-313b ITEM D: on an idempotent re-deploy the cc/ surface docs render
    byte-identical (skipped_no_drift). They must fold into skipped_no_drift,
    NOT report as phantom `deployed`. Pre-fix the surface loop appended
    everything except skipped_user_file to `deployed` and never routed a
    skipped_no_drift surface doc into skipped_no_drift_files — so an idempotent
    re-init phantom-counted the unchanged cc/ docs as deployments."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import deploy_harness
    from espalier.models import BuildPlan

    (tmp_path / ".git").mkdir()
    fp = fingerprint_repo(tmp_path)
    plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
    deploy_harness(tmp_path, plan, fp)           # 1st: cc/ surfaces created
    result = deploy_harness(tmp_path, plan, fp)  # 2nd: byte-identical -> no drift
    assert "cc/COMMANDS.md" in result["skipped_no_drift"]
    assert "cc/COMMANDS.md" not in result["deployed"]


def test_init_nudges_on_legacy_memory_file_without_stranding(tmp_path, capsys):
    """TP-317 2-E: a repo initialized before the MEMORY.md -> ESPALIER_MEMORY.md
    rename carries its memory in the legacy name. deploy_harness must NOT write a
    fresh empty ESPALIER_MEMORY.md (which would strand the adopter's content in
    the old file) and must print a one-time migration nudge instead — never
    silently mutating the adopter's tracked file."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import deploy_harness
    from espalier.models import BuildPlan

    (tmp_path / ".git").mkdir()
    legacy = tmp_path / "MEMORY.md"
    legacy.write_text("# adopter's existing memory\n", encoding="utf-8")
    fp = fingerprint_repo(tmp_path)
    plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
    result = deploy_harness(tmp_path, plan, fp)

    # no fresh ESPALIER_MEMORY.md written (that would strand the legacy content)
    assert not (tmp_path / "ESPALIER_MEMORY.md").exists()
    assert "ESPALIER_MEMORY.md" not in result["deployed"]
    # the legacy file is left byte-for-byte untouched
    assert legacy.read_text(encoding="utf-8") == "# adopter's existing memory\n"
    # the operator is nudged to migrate
    assert "git mv MEMORY.md ESPALIER_MEMORY.md" in capsys.readouterr().out


def test_init_deploys_memory_file_on_fresh_repo_no_nudge(tmp_path, capsys):
    """TP-317 2-E discriminating negative: a fresh repo with no legacy MEMORY.md
    gets a real ESPALIER_MEMORY.md and NO migration nudge — the nudge fires only
    on the legacy condition, not on every init."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import deploy_harness
    from espalier.models import BuildPlan

    (tmp_path / ".git").mkdir()
    fp = fingerprint_repo(tmp_path)
    plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
    result = deploy_harness(tmp_path, plan, fp)

    assert (tmp_path / "ESPALIER_MEMORY.md").exists()
    assert "ESPALIER_MEMORY.md" in result["deployed"]
    assert "git mv MEMORY.md" not in capsys.readouterr().out


def test_upgrade_dry_run_nudges_on_legacy_memory_file(tmp_path, capsys):
    """TP-336 1-E: a pre-rename adopter running the documented ``upgrade .``
    PREVIEW (dry-run) must be told their legacy MEMORY.md needs renaming. The
    nudge lived only in ``deploy_harness``, which the dry-run path never calls --
    so the preview was SILENT about a tracked file needing migration (learned only
    on ``--execute``). Earn-the-red: pre-fix, dry-run stdout carried no ``git mv``
    nudge."""
    import argparse
    from espalier.cli import cmd_upgrade

    (tmp_path / ".git").mkdir()
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("# adopter's existing memory\n", encoding="utf-8")

    args = argparse.Namespace(repo=str(tmp_path), execute=False, config=None)
    rc = cmd_upgrade(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "git mv MEMORY.md ESPALIER_MEMORY.md" in out
    # a dry-run is a pure preview: it must not have created the file
    assert not (tmp_path / "ESPALIER_MEMORY.md").exists()


def test_upgrade_dry_run_no_nudge_when_already_migrated(tmp_path, capsys):
    """Discriminating negative: a repo that ALREADY has ESPALIER_MEMORY.md gets no
    migration nudge on upgrade dry-run -- the nudge fires only on the legacy
    condition (legacy present AND no ESPALIER_MEMORY.md), never on every upgrade."""
    import argparse
    from espalier.cli import cmd_upgrade

    (tmp_path / ".git").mkdir()
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("# legacy\n", encoding="utf-8")
    (tmp_path / "ESPALIER_MEMORY.md").write_text("# already migrated\n", encoding="utf-8")

    args = argparse.Namespace(repo=str(tmp_path), execute=False, config=None)
    rc = cmd_upgrade(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "git mv MEMORY.md" not in out


class TestUpgradeNamesTheHandoffPushFlip:
    """Review, 2026-10-03: an installed adopter's /handoff stops pushing after an
    upgrade (the default is now off), and init's line never reaches them. The
    upgrade says so whenever espalier.toml does not set the key."""

    @staticmethod
    def _tree(tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
        (tmp_path / "ESPALIER_MEMORY.md").write_text("# memory\n", encoding="utf-8")
        return tmp_path

    def _upgrade_out(self, tmp_path, capsys):
        import argparse
        from espalier.cli import cmd_upgrade
        assert cmd_upgrade(argparse.Namespace(repo=str(tmp_path), execute=False, config=None)) == 0
        return capsys.readouterr().out

    def test_an_upgrade_without_the_key_names_the_new_default(self, tmp_path, capsys):
        out = self._upgrade_out(self._tree(tmp_path), capsys)
        line = next((ln for ln in out.splitlines() if "handoff_push" in ln), "")
        assert "/handoff" in line and "handoff_push = true" in line and "/ship" in line, out[-600:]

    def test_an_upgrade_that_already_sets_the_key_says_nothing(self, tmp_path, capsys):
        root = self._tree(tmp_path)
        (root / "espalier.toml").write_text("handoff_push = true\n", encoding="utf-8")
        assert "handoff_push" not in self._upgrade_out(root, capsys)


class TestInitNamesTheHandoffPush:
    """Two field-trial adopters found that nothing but the agent's vigilance told
    a new user /handoff pushes. init's summary now says it pushes only where
    espalier.toml opts in, and how to push otherwise."""

    def test_init_says_whether_handoff_pushes_and_how_to_opt_in(self, tmp_path):
        out = _run_init(_make_target(tmp_path)).stdout
        line = next((ln for ln in out.splitlines() if "handoff_push" in ln), "")
        assert "/handoff" in line and "handoff_push = true" in line, out[-800:]
        assert "/ship" in line


class TestGoalSnapshotSeed:
    """cc/GOAL.md is seeded by default (2026-09-30). Before this, init created
    no goal snapshot on an adopter tree, so the section SessionStart injects
    near the top of every session reached only an operator who already knew to
    hand-make the file -- the first Windows adopter install met exactly that.
    Seeded only when absent, never refreshed (after the first /handoff it is
    curated text), and ``goal_snapshot = false`` in espalier.toml opts out."""

    @staticmethod
    def _deploy(root: Path, **config):
        from espalier.analyze import fingerprint_repo
        from espalier.cli import deploy_harness
        from espalier.models import BuildPlan, HarnessConfig

        (root / ".git").mkdir(exist_ok=True)
        plan = BuildPlan(repo_name="x", config=HarnessConfig(**config))
        return deploy_harness(root, plan, fingerprint_repo(root))

    def test_fresh_tree_gets_the_skeleton_perishable_first_goal_last(self, tmp_path):
        result = self._deploy(tmp_path)
        goal = tmp_path / "cc" / "GOAL.md"
        assert goal.is_file()
        assert result["goal_snapshot"] == "created"
        assert "cc/GOAL.md" in result["deployed"]
        text = goal.read_text(encoding="utf-8")
        assert text.isascii(), "the banner prints this on hosts without UTF-8 stdout"
        # SessionStart cuts from the TOP and keeps whole trailing sections, so
        # the goal-proper must trail the perishable notes.
        heads = [text.index(h) for h in (
            "## Notes to next session", "## Still owed", "## Goal\n", "## Where we are",
        )]
        assert heads == sorted(heads)
        assert "goal_snapshot = false" in text, "the file names its own opt-out"

    def test_an_existing_goal_is_kept_byte_for_byte(self, tmp_path):
        goal = tmp_path / "cc" / "GOAL.md"
        goal.parent.mkdir()
        goal.write_bytes(b"# mine\n\n## Goal\nship it\n")
        result = self._deploy(tmp_path)
        assert result["goal_snapshot"] == "kept"
        assert "cc/GOAL.md" not in result["deployed"]
        assert goal.read_bytes() == b"# mine\n\n## Goal\nship it\n"

    def test_opt_out_seeds_nothing(self, tmp_path):
        result = self._deploy(tmp_path, goal_snapshot=False)
        assert result["goal_snapshot"] == "opted_out"
        assert not (tmp_path / "cc" / "GOAL.md").exists()

    def test_opt_out_with_the_file_present_says_to_delete_it(self, tmp_path, capsys):
        """SessionStart keys on the file, not the key: an opted-out tree that
        still has one keeps seeing it, so init says so instead of staying quiet."""
        goal = tmp_path / "cc" / "GOAL.md"
        goal.parent.mkdir()
        goal.write_text("keep\n", encoding="utf-8")
        result = self._deploy(tmp_path, goal_snapshot=False)
        assert result["goal_snapshot"] == "opted_out_present"
        assert goal.read_text(encoding="utf-8") == "keep\n"
        err = capsys.readouterr().err
        assert "goal_snapshot = false" in err and "Delete the file" in err

    def test_the_key_is_read_from_espalier_toml(self, tmp_path):
        from espalier.config import load_config

        (tmp_path / "espalier.toml").write_text("goal_snapshot = false\n", encoding="utf-8")
        assert load_config(tmp_path).goal_snapshot is False
        (tmp_path / "espalier.toml").write_text("", encoding="utf-8")
        assert load_config(tmp_path).goal_snapshot is True

    def test_the_seeded_path_is_in_the_required_gitignore(self):
        """The file is per-machine continuity; an unignored one is committed by
        the first broad stage. The roster pin in test_init_gitignore_default
        asks git about every ADOPTER_RUNTIME_GENERATED member; this names the
        entry so a revert of the roster row alone still reds here."""
        from espalier import surface_contract
        from espalier.cli import REQUIRED_GITIGNORE

        assert "cc/GOAL.md" in REQUIRED_GITIGNORE
        assert "cc/GOAL.md" in surface_contract.ADOPTER_RUNTIME_GENERATED

    def test_the_source_tree_is_never_seeded(self, tmp_path, monkeypatch):
        """On the Espalier source tree GOAL is the operator's own, and
        scripts/check_handoff_landing.py reads its presence as the tell that a
        checkout is the operator's tree: a seeded skeleton on a second clone
        turned two of its notes into reds (driven, 2026-09-30 review)."""
        from espalier import surface_contract
        from espalier.cli import preview_managed_surface

        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda _root: True)
        result = self._deploy(tmp_path)
        assert result["goal_snapshot"] == "self_host"
        assert not (tmp_path / "cc" / "GOAL.md").exists()
        (tmp_path / "cc" / "GOAL.md").parent.mkdir(exist_ok=True)
        assert "cc/GOAL.md" not in preview_managed_surface(tmp_path, goal_snapshot=True)["created"]

    def test_handoff_names_the_seeded_sections_in_order(self):
        """Two creators: `_build_goal_md` and /handoff step 7's absent branch,
        which tells a session to create the file by hand. The prose's heading
        list must be the code's, in the code's order."""
        import re
        from espalier.cli import _build_goal_md

        body = (REPO_ROOT / ".claude" / "commands" / "handoff.md").read_text(encoding="utf-8")
        start = body.index("**If the file is absent")
        paragraph = body[start:body.index("\n\n", start)]
        prose = re.findall(r"`(## [^`]+)`", paragraph)
        code = [ln for ln in _build_goal_md().splitlines() if ln.startswith("## ")]
        assert prose == code, (prose, code)

    def test_init_names_the_file_and_dry_run_names_the_seed(self, tmp_path):
        target = _make_target(tmp_path)
        # Under the pytest cap (60 s): a subprocess timeout at or above it can
        # never fire (the ceiling contract in tests/test_test_suite_contract.py).
        dry = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target), "--dry-run"],
            capture_output=True, text=True, timeout=45, check=True, encoding="utf-8",
        )
        assert "Would seed cc/GOAL.md" in dry.stdout
        assert not (target / "cc").exists(), "a dry run wrote"
        from tests._git_oracle import require_is_gitignored

        out = _run_init(target).stdout
        assert "cc/GOAL.md is your goal/progress snapshot" in out
        assert require_is_gitignored(target, "cc/GOAL.md"), (
            "init seeded a GOAL its own .gitignore block does not cover"
        )

    def test_a_version_current_upgrade_repeats_the_opted_out_note(self, tmp_path, capsys):
        """The NOTE lived only in the deploy, which a current install never
        reaches: an operator who set the key and kept the file heard nothing."""
        _deployed_current_tree(tmp_path)
        (tmp_path / "espalier.toml").write_text("goal_snapshot = false\n", encoding="utf-8")
        capsys.readouterr()
        assert _upgrade(tmp_path, execute=False) == 0
        assert "NOTE: goal_snapshot = false in espalier.toml, but cc/GOAL.md exists" in (
            capsys.readouterr().out
        )

    @pytest.mark.parametrize("opted_out", [False, True])
    def test_a_version_current_upgrade_seeds_a_missing_goal_unless_opted_out(
        self, tmp_path, capsys, opted_out,
    ):
        """The installed base at the running version (the first adopter's
        install) reaches the seed through ``upgrade``, not only through a
        re-init: the preview's ``created`` is the oracle that decides whether
        a current install has anything to do, so it must predict the seed on
        the deploy's own rule, key included."""
        # A real init, saved plan included: that is the first adopter's
        # install. A deploy-only tree has no plan, which is a clone's state,
        # and there --execute refuses and names init (DEF-1063).
        goal = _initialized_tree(tmp_path) / "cc" / "GOAL.md"
        goal.unlink()
        if opted_out:
            (tmp_path / "espalier.toml").write_text("goal_snapshot = false\n", encoding="utf-8")
        capsys.readouterr()
        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        named = "created on --execute" in out and "cc/GOAL.md" in out
        assert named is not opted_out, out
        # Deleting the file is the natural way to stop using it; the line that
        # says it comes back must name the key that actually stops it.
        assert ("set goal_snapshot = false in espalier.toml" in out) is not opted_out, out
        assert not goal.exists(), "a preview never writes"
        assert _upgrade(tmp_path, execute=True) == 0
        assert goal.exists() is not opted_out


def test_upgrade_dry_run_reports_profile_allow_rules_the_file_lacks(tmp_path, capsys):
    """DEF-715: upgrade appends hook events only, so it must SAY which profile
    allow rules the operator's settings.json lacks and name the opt-in that
    appends them -- in the preview too, never silently."""
    import argparse
    import json
    from espalier.cli import cmd_upgrade

    (tmp_path / ".git").mkdir()
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}) + "\n", encoding="utf-8",
    )
    settings = tmp_path / ".claude" / "settings.json"
    before = settings.read_bytes()
    rc = cmd_upgrade(argparse.Namespace(repo=str(tmp_path), execute=False, config=None))
    out = capsys.readouterr().out
    assert rc == 0
    # A rule every fingerprint renders: this tree has none, and the pytest
    # rules render for a Python fingerprint only (DEF-965).
    assert "of the 'workflow' profile" in out and "Bash(git show *)" in out
    assert "--profile workflow --add-allows" in out
    assert settings.read_bytes() == before, "a preview never writes"
    assert not list((tmp_path / ".claude").glob("settings.json.bak*")), "a preview never backs up"


def _deployed_current_tree(tmp_path: Path) -> Path:
    """A tree ``deploy_harness`` has fully written: version-current by
    construction (the rendered manifest carries the running engine's stamp),
    every managed file at its packaged bytes, no saved plan (``init`` writes
    that, the deploy does not). The honest stand-in for an adopter's committed
    harness -- the three-line fake it replaces (a ``.git`` directory and a
    stamped manifest, nothing deployed) was version-current with 72 packaged
    files absent, which is exactly the tree ``upgrade`` must not call current
    (DEF-726)."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import deploy_harness
    from espalier.models import BuildPlan

    (tmp_path / ".git").mkdir()
    fp = fingerprint_repo(tmp_path)
    deploy_harness(tmp_path, BuildPlan(repo_name="x", profiles=["ci_cd"]), fp)
    return tmp_path


def test_upgrade_on_a_version_current_install_still_reports_the_gap(tmp_path, capsys):
    """The steady state of the installed base: stamp current, one rule missing.
    'Nothing to do' must be true when it is said (the .gitignore precedent in
    the same branch); the first cut returned before the report."""
    import argparse
    import json
    from espalier.cli import cmd_upgrade

    _deployed_current_tree(tmp_path)
    # Drop ONE rule from the deployed file rather than replace it: the hooks
    # stay wired (a file with no hooks block changes what cc/LIVE_SURFACE.md
    # renders, which is real drift and falls through to the stages).
    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    # A rule every fingerprint renders (the pytest rules are Python-only, DEF-965).
    rule = "Bash(git show *)"
    assert rule in data["permissions"]["allow"], "fixture: the deployed profile carries the rule"
    data["permissions"]["allow"].remove(rule)
    settings.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = settings.read_bytes()
    rc = cmd_upgrade(argparse.Namespace(repo=str(tmp_path), execute=False, config=None))
    out = capsys.readouterr().out
    assert rc == 0
    assert "harness is current" in out and "nothing to do" not in out
    assert rule in out and "--add-allows" in out
    assert settings.read_bytes() == before


def test_upgrade_on_a_version_current_install_names_a_retired_deny_rule_and_is_not_nothing_to_do(tmp_path, capsys):
    """The same steady state with the line `init` used to write and has since
    retired (the trailing-star rm rule, 2026-09-29) still in permissions.deny:
    the read-only report WARNs about it on stderr, and the sentence that
    follows may not say "nothing to do" -- it named the state for a missing
    allow rule and said "nothing to do" over a retired deny rule until the
    failure-mode review drove the contradiction."""
    import argparse
    import json
    from espalier.cli import cmd_upgrade

    _deployed_current_tree(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["permissions"].setdefault("deny", []).append("Bash(rm -rf /*)")
    settings.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = settings.read_bytes()
    rc = cmd_upgrade(argparse.Namespace(repo=str(tmp_path), execute=False, config=None))
    captured = capsys.readouterr()
    assert rc == 0
    assert "harness is current" in captured.out and "nothing to do" not in captured.out
    assert "retired deny rule" in captured.out, captured.out
    assert "Bash(rm -rf /*)" in captured.err and "retired deny rule" in captured.err, captured.err
    assert settings.read_bytes() == before


class TestInitNamesARetiredDenyRule:
    """DEF-4017: an adopter on 0.8.0b2 or earlier who refreshes by re-running
    ``init .`` (QUICKSTART lists it beside ``upgrade --execute``) was told
    nothing about the retired deny rule their settings.json still carries,
    the one that refuses every recursive delete of an absolute path in every
    permission mode, while ``upgrade``, ``doctor``, ``merge-settings`` and
    ``init --wire-hooks`` each named it. The re-run now says it in the same
    voice, read-only, and says nothing else about permissions."""

    RULE = "Bash(rm -rf /*)"
    WARN = "carries the retired deny rule Bash(rm -rf /*)"

    @staticmethod
    def _init(root: Path, **extra) -> int:
        import argparse
        from espalier.cli import cmd_init

        return cmd_init(argparse.Namespace(repo=str(root), config=None, write_gitignore=True, **extra))

    def _plant(self, root: Path) -> bytes:
        import json

        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"].setdefault("deny", []).append(self.RULE)
        settings.write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return settings.read_bytes()

    def test_a_plain_init_rerun_names_the_rule_and_leaves_the_file_alone(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        before = self._plant(_initialized_tree(tmp_path))
        capsys.readouterr()
        assert self._init(tmp_path) == 0
        err = capsys.readouterr().err
        assert f"[init] WARN: .claude/settings.json {self.WARN}" in err, err[-1500:]
        assert "Delete that line by hand" in err, err[-1500:]
        assert (tmp_path / ".claude" / "settings.json").read_bytes() == before

    def test_a_disarmed_install_is_not_told_to_delete_the_rule(self, tmp_path, capsys, monkeypatch):
        """Hooks wired to an interpreter this host cannot run (a settings.json
        from another machine) fail open, so write_guard is not there to stand
        in for the retired rule, and "delete that line" would take away the
        only guard left. The re-run names the disarmed hooks and leaves the
        rule to the re-run after the repair."""
        import json

        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        self._plant(root)
        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        for entries in data["hooks"].values():
            for entry in entries:
                for hook in entry["hooks"]:
                    hook["command"] = "no-such-python-w0"
        settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        capsys.readouterr()
        assert self._init(root) == 0
        captured = capsys.readouterr()
        assert "Hooks are NOT yet active" in captured.out, captured.out[-2500:]
        assert "retired deny rule" not in captured.err, captured.err[-2500:]
        assert "Delete that line" not in captured.err, captured.err[-2500:]

    def test_a_hand_written_rule_is_said_to_match_never_to_be_inits(self, tmp_path, capsys, monkeypatch):
        """The registry matches by rule text, so a rule the operator wrote by
        hand on an install this engine made (which never wrote it) reads the
        same as one an old init wrote. The shared reason every surface renders
        (doctor, merge-settings, upgrade, this re-run) says the text matches a
        rule init wrote, never that init wrote this one."""
        from espalier.cli import settings_stale_denies

        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        settings = root / ".claude" / "settings.json"
        assert self.RULE not in settings.read_text(encoding="utf-8")
        self._plant(root)
        ((rule, why),) = settings_stale_denies(settings)
        assert rule == self.RULE
        assert "this line matches a deny rule the init command wrote through 0.8.0b2" in why, why
        assert "wrote it" not in why, why
        capsys.readouterr()
        assert self._init(root) == 0
        err = capsys.readouterr().err
        assert "this line matches a deny rule the init command wrote through 0.8.0b2" in err, err[-1500:]
        assert "wrote it" not in err, err[-1500:]

    def test_a_plain_rerun_over_a_minimal_install_lists_no_allow_rules(self, tmp_path, capsys, monkeypatch):
        """A plain re-run keeps the profile the file was rendered from
        (DEF-2004); before that it recorded the default, and a gap read here
        would have listed the workflow profile's rules (Write among them) to a
        minimal install, with an append that widens its permissions. The
        re-run names the retired rule only."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "README.md").write_text("# t\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        assert self._init(tmp_path, profile="minimal") == 0
        self._plant(tmp_path)
        capsys.readouterr()
        assert self._init(tmp_path) == 0
        err = capsys.readouterr().err
        assert self.WARN in err, err[-1500:]
        assert "allow rule" not in err and "--add-allows" not in err, err[-2500:]

    def test_upgrade_execute_names_the_rule_once_not_once_per_layer(self, tmp_path, capsys, monkeypatch):
        """``upgrade --execute`` runs the same deploy init does and then its own
        report; the deploy's copy is init's alone, so the WARN is said once."""
        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        self._plant(root)
        (root / "docs" / "CHEAT-SHEET.md").unlink()  # drift, so --execute deploys
        capsys.readouterr()
        assert _upgrade(root, execute=True) == 0
        captured = capsys.readouterr()
        assert "[upgrade] re-deployed" in captured.out, captured.out[-1500:]
        assert captured.err.count(self.WARN) == 1, captured.err[-2500:]

    def test_init_never_calls_an_adopters_own_rule_retired(self, tmp_path, capsys, monkeypatch):
        """Case (b): no Espalier hook is wired, so the write_guard check that
        replaces a retired Read() rule is not running, and "delete that line"
        would take away the adopter's only guard on the file; that branch's one
        WARN sends them to merge-settings or --wire-hooks, which wire the hooks
        and name the rule in the same run."""
        import json

        from espalier import cli

        monkeypatch.chdir(tmp_path)
        # Off a TTY the arming prompt is skipped; say so, or `pytest -s` in a
        # terminal would stop at it.
        monkeypatch.setattr(cli, "_stream_isatty", lambda _stream: False)
        (tmp_path / "README.md").write_text("# t\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_bytes(
            json.dumps({"permissions": {"deny": [self.RULE, "Read(./.env)"]}}).encode("utf-8"))
        assert self._init(tmp_path) == 0
        err = capsys.readouterr().err
        assert "NO Espalier hooks wired" in err, err[-1500:]
        assert "retired deny rule" not in err, err[-1500:]


def _plant_retired_rule(root: Path) -> None:
    import json

    settings = root / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["permissions"].setdefault("deny", []).append("Bash(rm -rf /*)")
    settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))


def _rewire_every_hook(root: Path, command: str | None) -> None:
    """Every hook entry runs ``command``; ``None`` drops the hooks block."""
    import json

    settings = root / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    if command is None:
        data.pop("hooks", None)
    else:
        for entries in data["hooks"].values():
            for entry in entries:
                for hook in entry["hooks"]:
                    hook["command"] = command
    settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))


def _what_the_surface_says(surface: str, root: Path, capsys) -> str:
    import argparse

    from espalier import cli
    from espalier.doctor import run_doctor_check

    capsys.readouterr()
    if surface == "doctor":
        result = run_doctor_check(root, skip_self_host=True)
        return "\n".join(result["warnings"] + result["failures"] + result["next_steps"])
    if surface == "init":
        cli.cmd_init(argparse.Namespace(repo=str(root), config=None, write_gitignore=True))
    elif surface == "init --wire-hooks":
        cli.cmd_init(argparse.Namespace(repo=str(root), config=None, write_gitignore=True,
                                        wire_hooks=True))
    elif surface == "merge-settings":
        cli.cmd_merge_settings(argparse.Namespace(repo=str(root), profile=None, add_allows=False,
                                                  repair=False))
    else:
        cli.cmd_upgrade(argparse.Namespace(repo=str(root), execute="--execute" in surface,
                                           config=None))
    captured = capsys.readouterr()
    return captured.out + captured.err


# (surface, whether it needs drift to reach its report, whether the merge has an
# event to add -- upgrade --execute's WIRED branch; the event is Stop, a blocking
# gate, so a read taken before the merge would see a disarmed tree)
_RETIRED_RULE_SURFACES = [
    ("init", False, False), ("init --wire-hooks", False, False), ("merge-settings", False, False),
    ("doctor", False, False), ("upgrade, version-current", False, False),
    ("upgrade preview", True, False), ("upgrade --execute", True, False),
    ("upgrade --execute, an event added", True, True),
]
_SURFACE_IDS = [s for s, _, _ in _RETIRED_RULE_SURFACES]
# A word that names no interpreter, and one that reads as Python and never resolves:
# the two arms of the armament read that a disarmed tree trips.
_DISARMING_WORDS = ["no-such-python-w0", "python-no-such-w0"]


class TestNoDeleteAdviceWhileTheHooksDoNotRun:
    """Every surface that names a retired deny rule says "delete that line",
    and for every row the hook layer is what stands in for the rule
    (write_guard's root-wipe wall, its secret-path read check). Where the
    file's Espalier hooks do not run -- wired to an interpreter this host
    lacks, or not wired at all -- that advice takes away the only guard left,
    so no surface gives it; each names the disarmed hooks, and the run after
    the repair names the rule. The armed twin of each row holds the advice in
    place, so the gate cannot pass by silencing everything."""

    @staticmethod
    def _tree(tmp_path: Path, monkeypatch, *, drift: bool, command: str | None,
              drop_event: bool = False) -> Path:
        import json

        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        _plant_retired_rule(root)
        _rewire_every_hook(root, command)
        if drop_event:
            settings = root / ".claude" / "settings.json"
            data = json.loads(settings.read_text(encoding="utf-8"))
            data["hooks"].pop("Stop")  # a blocking gate: armed after the merge, not before
            settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        if drift:
            (root / "docs" / "CHEAT-SHEET.md").unlink()
        return root

    @pytest.mark.parametrize("word", _DISARMING_WORDS)
    @pytest.mark.parametrize("surface,drift,drop_event", _RETIRED_RULE_SURFACES, ids=_SURFACE_IDS)
    def test_a_disarmed_install_is_not_told_to_delete_it(self, surface, drift, drop_event, word,
                                                         tmp_path, capsys, monkeypatch):
        """...and is told why: each surface names the hooks that do not run, so
        holding the advice back never leaves the tree unexplained."""
        root = self._tree(tmp_path, monkeypatch, drift=drift, command=word, drop_event=drop_event)
        said = _what_the_surface_says(surface, root, capsys)
        assert "retired deny rule" not in said and "Bash(rm -rf /*)" not in said, said[-2500:]
        assert "runs no interpreter" in said or "does not resolve" in said, said[-2500:]

    @pytest.mark.parametrize("surface,drift,drop_event", _RETIRED_RULE_SURFACES, ids=_SURFACE_IDS)
    def test_an_armed_install_is_told(self, surface, drift, drop_event, tmp_path, capsys, monkeypatch):
        from espalier.cli import RETIRED_RULE_KEPT_WHY, _detect_python_command

        root = self._tree(tmp_path, monkeypatch, drift=drift, command=_detect_python_command(),
                          drop_event=drop_event)
        said = _what_the_surface_says(surface, root, capsys)
        assert "retired deny rule Bash(rm -rf /*)" in said, said[-2500:]
        # ...and why the advice is said here, so a tree that heard it late, or
        # not at all, can tell which state it was in (DEF-2006).
        assert RETIRED_RULE_KEPT_WHY in said, said[-2500:]

    def test_doctor_does_not_tell_a_file_with_no_espalier_hooks(self, tmp_path, capsys, monkeypatch):
        root = self._tree(tmp_path, monkeypatch, drift=False, command=None)
        said = _what_the_surface_says("doctor", root, capsys)
        assert "retired deny rule" not in said and "Bash(rm -rf /*)" not in said, said[-2500:]

    @staticmethod
    def _pause_write_guard(root: Path, form: str) -> None:
        """write_guard's entry rewritten in the old shell form as a comment, the
        way an operator pauses it; every other gate stays as it was."""
        import json

        from espalier.cli import _detect_python_command

        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        paused = 0
        for entries in data["hooks"].values():
            for entry in entries:
                for i, hook in enumerate(entry["hooks"]):
                    if any("write_guard.py" in str(a) for a in hook.get("args") or []):
                        entry["hooks"][i] = {"type": "command", "command": form.format(
                            python=_detect_python_command(),
                            script='"$CLAUDE_PROJECT_DIR/tools/cc/hooks/write_guard.py"')}
                        paused += 1
        assert paused, "the fixture paused nothing"
        settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))

    @staticmethod
    def _held_back(surface: str, said: str, reason: str) -> None:
        """The advice is not given, and every surface but doctor says why the
        rule is kept (doctor names the paused or switched-off hook itself)."""
        assert "carries the retired deny rule" not in said and "Delete that line" not in said, said[-2500:]
        if surface != "doctor":
            assert f"carries a retired deny rule, kept because {reason}" in said, said[-2500:]
            # The claim reads this tree as armed, so the disarmed-hooks WARN
            # would contradict it (the upgrade preview printed one, predicted
            # by the code review); the held line above is the whole account.
            assert ": WARNING -- " not in said, said[-2500:]
        # ...and no "nothing to do" over it, where a surface says that.
        assert "nothing to do" not in said.lower(), said[-2500:]
        if surface == "upgrade, version-current":
            assert "keeps a retired deny rule while write_guard does not run" in said, said[-2500:]

    @pytest.mark.parametrize("form", ["# {python} {script}", ": # {python} {script}"])
    @pytest.mark.parametrize("surface,drift,drop_event", _RETIRED_RULE_SURFACES, ids=_SURFACE_IDS)
    def test_a_paused_write_guard_keeps_its_rule_unnamed(self, surface, drift, drop_event, form,
                                                        tmp_path, capsys, monkeypatch):
        """DEF-2006: the enforcement claim lets a pre-v0.6.5 shell-form entry
        through on purpose, a commented one included, so the claim reads this
        tree as armed; the advice also asks the strict wiring read, where a
        commented write_guard is not wired, so the rule is kept and the run
        says why and what names it."""
        from espalier.cli import _detect_python_command

        root = self._tree(tmp_path, monkeypatch, drift=drift, command=_detect_python_command(),
                          drop_event=drop_event)
        self._pause_write_guard(root, form)
        said = _what_the_surface_says(surface, root, capsys)
        self._held_back(surface, said, "write_guard is not wired to run")

    @pytest.mark.parametrize("where", [".claude/settings.json", ".claude/settings.local.json"])
    @pytest.mark.parametrize("surface,drift,drop_event", _RETIRED_RULE_SURFACES, ids=_SURFACE_IDS)
    def test_a_kill_switch_keeps_the_rule_unnamed(self, surface, drift, drop_event, where,
                                                  tmp_path, capsys, monkeypatch):
        """The kill switch is the plain way to pause every hook, and the claim
        does not read it: the failure-mode review drove the advice, and its
        "write_guard runs here", beside doctor's own kill-switch failure."""
        import json

        from espalier.cli import _detect_python_command

        root = self._tree(tmp_path, monkeypatch, drift=drift, command=_detect_python_command(),
                          drop_event=drop_event)
        path = root / where
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data["disableAllHooks"] = True
        path.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        said = _what_the_surface_says(surface, root, capsys)
        self._held_back(surface, said, "a kill switch (disableAllHooks)")

    @pytest.mark.parametrize("surface", ["merge-settings", "doctor", "upgrade, version-current"])
    def test_a_write_guard_with_no_file_keeps_the_rule_unnamed(self, surface, tmp_path, capsys,
                                                               monkeypatch):
        """The strict wiring read skips a gate whose file is absent, by its own
        scope, so "not unwired" is no claim that write_guard runs: the advice
        asks for the file too (the failure-mode review's drive)."""
        import json

        from espalier.cli import _detect_python_command

        root = self._tree(tmp_path, monkeypatch, drift=False, command=_detect_python_command())
        hooks = root / "tools" / "cc" / "hooks"
        (hooks / "write_guard.py").rename(hooks / "write_guard.py.aside")
        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        for entries in data["hooks"].values():
            for entry in entries:
                entry["hooks"] = [h for h in entry["hooks"]
                                  if not any("write_guard.py" in str(a) for a in h.get("args") or [])]
        settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        said = _what_the_surface_says(surface, root, capsys)
        assert "carries the retired deny rule" not in said and "Delete that line" not in said, said[-2500:]

    def test_the_gate_holds_back_a_file_with_no_espalier_hooks_even_when_nothing_blocks(self, tmp_path):
        """The "wires Espalier hooks" arm on its own: with no gate script on disk
        the armament read finds nothing to fault, so only this arm withholds."""
        import json

        from espalier.cli import _retired_rules_to_name

        settings = tmp_path / "settings.json"
        settings.write_bytes(json.dumps({"permissions": {"deny": ["Bash(rm -rf /*)"]}}).encode("utf-8"))
        stale = (("Bash(rm -rf /*)", "why"),)
        assert _retired_rules_to_name(stale, repo_root=tmp_path, settings_path=settings,
                                      blockers=[]) == ()

    def test_version_current_upgrade_reads_the_armament_once(self, tmp_path, capsys, monkeypatch):
        """The WARN, the sentence that points at it and the disarmed narration
        share one read: three reads of a flaky interpreter can disagree, and
        the rule adds no interpreter spawn to the run."""
        from espalier import cli
        from espalier.cli import _detect_python_command

        root = self._tree(tmp_path, monkeypatch, drift=False, command=_detect_python_command())
        real, calls = cli._enforcement_claim_blockers, []

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)

        monkeypatch.setattr(cli, "_enforcement_claim_blockers", counting)
        said = _what_the_surface_says("upgrade, version-current", root, capsys)
        assert "retired deny rule Bash(rm -rf /*)" in said, said[-2500:]
        assert len(calls) == 1, len(calls)


class TestMergeSettingsSaysNothingToDoOnlyWhenItIsWhole:
    """upgrade's rule since 2026-09-29, for merge-settings: on a file whose
    hook events are current, "Nothing to do." printed above a retired-rule
    WARN (armed tree) or above the not-armed warning (disarmed tree), each
    of which is something to do."""

    @staticmethod
    def _said(root: Path, capsys) -> str:
        return _what_the_surface_says("merge-settings", root, capsys)

    def test_not_over_a_retired_rule_on_an_armed_tree(self, tmp_path, capsys, monkeypatch):
        from espalier.cli import _detect_python_command

        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        _plant_retired_rule(root)
        _rewire_every_hook(root, _detect_python_command())
        said = self._said(root, capsys)
        assert "retired deny rule Bash(rm -rf /*)" in said, said[-2500:]
        assert "Nothing to do" not in said, said[-2500:]

    def test_not_over_hooks_that_do_not_run(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        _rewire_every_hook(root, "python-no-such-w0")
        said = self._said(root, capsys)
        assert "does not resolve" in said, said[-2500:]
        assert "Nothing to do" not in said, said[-2500:]

    def test_still_said_when_it_is_whole(self, tmp_path, capsys, monkeypatch):
        from espalier.cli import _detect_python_command

        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        _rewire_every_hook(root, _detect_python_command())
        said = self._said(root, capsys)
        assert "Nothing to do." in said, said[-2500:]


class TestUpgradeExecuteReadsTheArmamentAfterItWires:
    """``--wire-hooks`` reads the hooks back after its merge writes events;
    ``upgrade --execute``'s same merge did not, and told a tree whose hooks
    cannot run that it had wired them, and nothing more."""

    @staticmethod
    def _tree(tmp_path: Path, monkeypatch, command: str) -> Path:
        import json

        monkeypatch.chdir(tmp_path)
        root = _initialized_tree(tmp_path)
        _rewire_every_hook(root, command)
        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["hooks"].pop("Stop")  # a blocking gate: armed after the merge, not before
        settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        (root / "docs" / "CHEAT-SHEET.md").unlink()
        return root

    def test_a_disarmed_tree_is_told_after_the_events_are_wired(self, tmp_path, capsys, monkeypatch):
        root = self._tree(tmp_path, monkeypatch, "python-no-such-w0")
        said = _what_the_surface_says("upgrade --execute", root, capsys)
        assert "into settings.json" in said, said[-2500:]
        assert "does not resolve" in said, said[-2500:]

    def test_an_armed_tree_is_not(self, tmp_path, capsys, monkeypatch):
        """Armed by the merge itself (the Stop gate it adds): read before the
        write, this tree would be told its hooks are not active."""
        from espalier.cli import _detect_python_command

        root = self._tree(tmp_path, monkeypatch, _detect_python_command())
        said = _what_the_surface_says("upgrade --execute", root, capsys)
        assert "into settings.json" in said, said[-2500:]
        assert "NOT yet active" not in said, said[-2500:]

    def test_a_retired_rule_adds_no_armament_read(self, tmp_path, capsys, monkeypatch):
        """The retired-rule gate reuses the read taken after the write, so a
        run with the rule asks the interpreters no more often than one without."""
        from espalier import cli
        from espalier.cli import _detect_python_command

        def reads(with_rule: bool, where: Path) -> int:
            where.mkdir()
            root = self._tree(where, monkeypatch, _detect_python_command())
            if with_rule:
                _plant_retired_rule(root)
            real, calls = cli._enforcement_claim_blockers, []

            def counting(*a, **k):
                calls.append(1)
                return real(*a, **k)

            monkeypatch.setattr(cli, "_enforcement_claim_blockers", counting)
            said = _what_the_surface_says("upgrade --execute", root, capsys)
            monkeypatch.setattr(cli, "_enforcement_claim_blockers", real)
            assert ("retired deny rule" in said) is with_rule, said[-2500:]
            return len(calls)

        assert reads(True, tmp_path / "with") == reads(False, tmp_path / "without")


class TestEveryRetiredRuleReportGoesThroughTheGate:
    """Derived from espalier/, so a reporter added later cannot skip the gate
    by not being on a hand-written list: every ``stale=`` handed to the shared
    reporter is the gate's output, and the WARN's text lives in the two places
    that render it (the shared reporter, and doctor's loop over a gated list)."""

    @staticmethod
    def _engine_modules():
        import ast

        root = Path(__file__).resolve().parents[1] / "espalier"
        for path in sorted(checkout_rglob(root, "*.py")):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(("_vendor/", "assets/")):
                continue
            yield rel, ast.parse(path.read_text(encoding="utf-8"))

    @staticmethod
    def _called(call, name: str) -> bool:
        """``name(...)`` or ``module.name(...)``: doctor reaches cli by attribute."""
        func = call.func
        return getattr(func, "id", None) == name or getattr(func, "attr", None) == name

    @classmethod
    def _gated_names(cls, func) -> set[str]:
        """Names bound from the gate and from nothing else in ``func``: a name
        later rebound to the raw list is not gated."""
        import ast

        from_gate, from_other = set(), set()
        for node in ast.walk(func):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For))
                       else [])
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and cls._called(node.value, "_retired_rules_to_name")):
                from_gate |= names
            else:
                from_other |= names
        return from_gate - from_other

    @classmethod
    def _is_gated(cls, value, gated: set[str]) -> bool:
        import ast

        if isinstance(value, ast.Call) and cls._called(value, "_retired_rules_to_name"):
            return True
        return isinstance(value, ast.Name) and value.id in gated

    def test_every_stale_argument_is_the_gates_output(self):
        import ast

        seen, bad = 0, []
        for rel, tree in self._engine_modules():
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                gated = self._gated_names(func)
                for call in ast.walk(func):
                    if isinstance(call, ast.Call) and self._called(call, "_report_allow_gaps"):
                        for kw in call.keywords:
                            if kw.arg is None:  # **kwargs could carry stale= past the census
                                bad.append(f"{rel}:{call.lineno} (**)")
                            elif kw.arg == "stale":
                                seen += 1
                                if not self._is_gated(kw.value, gated):
                                    bad.append(f"{rel}:{kw.value.lineno}")
        assert seen >= 5, seen
        assert not bad, f"stale= not from _retired_rules_to_name at {sorted(set(bad))}"

    def test_no_gate_call_hands_it_a_literal_armament(self):
        """``blockers=[]`` written into the engine would wave every tree through."""
        import ast

        bad = []
        for rel, tree in self._engine_modules():
            for call in ast.walk(tree):
                if isinstance(call, ast.Call) and self._called(call, "_retired_rules_to_name"):
                    for kw in call.keywords:
                        if kw.arg == "blockers" and isinstance(
                                kw.value, (ast.List, ast.Tuple, ast.Constant)):
                            bad.append(f"{rel}:{kw.value.lineno}")
        assert not bad, bad

    def test_every_retired_rule_stands_in_for_write_guard(self):
        """The gate holds the advice back while write_guard does not run
        (DEF-2006), so every retired row must be one write_guard stands in for:
        a row retired for another gate's sake would need its own check."""
        from espalier.settings_profiles import RETIRED_DENY_RULES

        assert RETIRED_DENY_RULES
        assert all("write_guard" in why for _rule, _version, why in RETIRED_DENY_RULES), [
            version for _rule, version, why in RETIRED_DENY_RULES if "write_guard" not in why]

    def test_the_warn_text_lives_in_two_places_and_doctor_loops_a_gated_list(self):
        import ast

        homes, doctor_loops = [], []
        for rel, tree in self._engine_modules():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and "carries the retired deny rule" in node.value:
                    homes.append(rel)
            if rel == "doctor.py":
                for func in ast.walk(tree):
                    if not isinstance(func, ast.FunctionDef):
                        continue
                    gated = self._gated_names(func)
                    for loop in ast.walk(func):
                        if isinstance(loop, ast.For) and any(
                                isinstance(n, ast.Constant) and isinstance(n.value, str)
                                and "carries the retired deny rule" in n.value
                                for n in ast.walk(loop)):
                            doctor_loops.append(self._is_gated(loop.iter, gated))
        assert sorted(homes) == ["cli.py", "doctor.py"], homes
        assert doctor_loops == [True], doctor_loops


def test_init_records_the_effective_settings_profile_and_refresh_keeps_it(tmp_path):
    """Every reader that compares settings.json against a profile needs the one
    init rendered it from; the per-machine file records nothing itself."""
    import json
    import subprocess
    import sys
    from espalier.cli import installed_settings_profile

    target = tmp_path / "adopter"
    target.mkdir()
    (target / "README.md").write_text("# t\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    proc = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(target), "--profile", "minimal"],
        capture_output=True, text=True, timeout=45, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    plan = json.loads((target / "reports" / "harness_config.json").read_text(encoding="utf-8"))
    assert plan["settings_profile"] == "minimal"
    assert installed_settings_profile(target) == "minimal"
    refresh = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "fingerprint", str(target)],
        capture_output=True, text=True, timeout=45, encoding="utf-8",
    )
    assert refresh.returncode == 0, refresh.stderr
    assert installed_settings_profile(target) == "minimal", "a report rebuild forgot the profile"


class TestAPlainReInitKeepsTheRecordedProfile:
    """DEF-2004: a plain re-run of ``init`` (the repair TROUBLESHOOTING names)
    recorded the built-in default over the profile the settings file was
    rendered from, so ``upgrade`` and ``doctor`` afterwards compared a
    ``minimal`` or ``full`` file against ``workflow`` and offered an append
    that widens it. With no flag and no ``default_profile`` the re-run keeps
    the recorded profile. The flag and the config still choose, and a profile
    only the flag may select is never re-selected from the record: the record
    can be committed (``gitignore_declined``), and a committed record would
    then widen every downstream operator's permissions, the rule the config
    already keeps."""

    @staticmethod
    def _tree(tmp_path: Path, monkeypatch) -> Path:
        from espalier import cli

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli, "_stream_isatty", lambda _stream: False)
        (tmp_path / "README.md").write_text("# t\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        return tmp_path

    @staticmethod
    def _init(root: Path, **extra) -> int:
        import argparse
        from espalier.cli import cmd_init

        return cmd_init(argparse.Namespace(repo=str(root), config=None, write_gitignore=True, **extra))

    @staticmethod
    def _plan(root: Path) -> Path:
        return root / "reports" / "harness_config.json"

    def _recorded(self, root: Path) -> object:
        import json

        return json.loads(self._plan(root).read_text(encoding="utf-8")).get("settings_profile")

    def _record(self, root: Path, name: str) -> None:
        import json

        plan = json.loads(self._plan(root).read_text(encoding="utf-8"))
        plan["settings_profile"] = name
        self._plan(root).write_bytes((json.dumps(plan, indent=2) + "\n").encode("utf-8"))

    @pytest.mark.parametrize("profile", ["minimal", "full"])
    def test_a_plain_rerun_keeps_the_profile_the_file_was_rendered_from(
            self, tmp_path, monkeypatch, capsys, profile):
        from espalier.cli import installed_settings_profile

        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile=profile) == 0
        capsys.readouterr()
        assert self._init(root) == 0
        assert self._recorded(root) == profile
        assert installed_settings_profile(root) == profile
        assert f"Settings profile: {profile} (kept from this install's record" in capsys.readouterr().out

    def test_a_committed_record_with_no_install_beside_it_is_the_default(self, tmp_path, monkeypatch):
        """The failure-mode review's drive: a tree that commits its record
        (``gitignore_declined``) handed a fresh clone, which has no settings
        file, the recording operator's ``full``. The record describes the
        file beside it; with none, the clone takes the default."""
        import json

        from espalier.settings_profiles import DEFAULT_PROFILE

        root = self._tree(tmp_path, monkeypatch)
        self._plan(root).parent.mkdir()
        self._plan(root).write_bytes(json.dumps({"settings_profile": "full"}).encode("utf-8"))
        assert self._init(root) == 0
        assert self._recorded(root) == DEFAULT_PROFILE

    @pytest.mark.parametrize("frame", [
        pytest.param(b"  \n", id="whitespace"),
        pytest.param(b"\xef\xbb\xbf\n", id="utf8-bom-only"),
        pytest.param(b"\xff\xfe \x00\n\x00", id="utf16-blank"),
    ])
    def test_an_empty_settings_file_is_no_install_to_keep_a_profile_for(self, tmp_path, monkeypatch, frame):
        """Empty as the deploy reads it (`is_effectively_empty_file`): nothing
        but whitespace after any byte-order mark, the frame a PowerShell
        `Out-File` or an editor leaves."""
        from espalier.settings_profiles import DEFAULT_PROFILE

        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="full") == 0
        (root / ".claude" / "settings.json").write_bytes(frame)
        assert self._init(root) == 0
        assert self._recorded(root) == DEFAULT_PROFILE

    def test_the_flag_still_chooses_over_the_record(self, tmp_path, monkeypatch):
        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="minimal") == 0
        assert self._init(root, profile="workflow") == 0
        assert self._recorded(root) == "workflow"

    def test_the_config_still_chooses_over_the_record(self, tmp_path, monkeypatch):
        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="minimal") == 0
        toml = root / "espalier.toml"
        toml.write_bytes(b'default_profile = "full"\n' + toml.read_bytes())
        assert self._init(root) == 0
        assert self._recorded(root) == "full"

    def test_a_profile_only_the_flag_selects_is_not_re_selected_from_the_record(
            self, tmp_path, monkeypatch, capsys):
        """Not kept, and the summary says which flag keeps it: a plain re-run
        on a self-host tree quietly re-recorded the default before too."""
        from espalier.cli import installed_settings_profile
        from espalier.settings_profiles import DEFAULT_PROFILE, PROFILES

        flag_only = sorted(name for name, p in PROFILES.items() if not p.config_selectable)
        assert flag_only, "no flag-only profile left to hold the rule against"
        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root) == 0
        for name in flag_only:
            self._record(root, name)
            # Every other reader still takes the record as it is (the two
            # readers differ on purpose; a merge of them would move doctor).
            assert installed_settings_profile(root) == name
            capsys.readouterr()
            assert self._init(root) == 0
            assert self._recorded(root) == DEFAULT_PROFILE, name
            assert f"which only `--profile {name}` keeps" in capsys.readouterr().out, name

    def test_an_unknown_recorded_name_is_the_default(self, tmp_path, monkeypatch):
        from espalier.settings_profiles import DEFAULT_PROFILE

        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="minimal") == 0
        self._record(root, "no-such-profile")
        assert self._init(root) == 0
        assert self._recorded(root) == DEFAULT_PROFILE

    @pytest.mark.parametrize("raw", [
        pytest.param(b"{not json", id="not-json"),
        pytest.param(b"[1]\n", id="not-an-object"),
        pytest.param(b'{"settings_profile": 5}\n', id="not-a-name"),
        pytest.param(b"\xff\xfe\x00", id="not-utf8"),
    ])
    def test_a_record_that_cannot_be_read_is_the_default(self, tmp_path, monkeypatch, raw):
        from espalier.settings_profiles import DEFAULT_PROFILE

        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="minimal") == 0
        self._plan(root).write_bytes(raw)
        assert self._init(root) == 0
        assert self._recorded(root) == DEFAULT_PROFILE

    def test_the_file_rendered_beside_a_kept_one_is_the_kept_profile(self, tmp_path, monkeypatch):
        """A re-run leaves an edited settings file alone and renders the
        profile beside it as `settings.json.new`; that render was the default's
        too (the code review drove 14 allow rules beside a minimal install's
        3), so taking it widened the file."""
        import json

        from espalier.cli import _build_settings_json

        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="minimal") == 0
        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"]["allow"].append("Bash(echo *)")
        settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        assert self._init(root) == 0
        rendered = root / ".claude" / "settings.json.new"
        assert rendered.is_file()
        allow = json.loads(rendered.read_text(encoding="utf-8"))["permissions"]["allow"]
        assert allow == _build_settings_json(profile_name="minimal", repo_root=root)["permissions"]["allow"]
        assert "Write" not in allow

    def test_upgrade_renders_the_installed_profile_beside_a_kept_file(self, tmp_path, monkeypatch):
        """The failure-mode review's sibling: ``upgrade --execute`` runs the
        deploy init does, and with no profile it rendered the default beside
        a minimal install (14 allow rules, Write among them)."""
        import json

        from espalier.cli import _build_settings_json

        root = self._tree(tmp_path, monkeypatch)
        assert self._init(root, profile="minimal") == 0
        settings = root / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        data["permissions"]["allow"].append("Bash(echo *)")
        settings.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))
        (root / "cc" / "PACK_MANIFEST.txt").write_bytes(b"")  # a stale deploy, so --execute deploys
        assert _upgrade(root, execute=True) == 0
        rendered = root / ".claude" / "settings.json.new"
        assert rendered.is_file()
        allow = json.loads(rendered.read_text(encoding="utf-8"))["permissions"]["allow"]
        assert allow == _build_settings_json(profile_name="minimal", repo_root=root)["permissions"]["allow"]
        assert self._recorded(root) == "minimal"


def _initialized_tree(tmp_path: Path) -> Path:
    """A real ``init`` on a README-only repo, in process: version-current,
    every managed file at its packaged bytes, the saved plan under
    ``reports/``. The tree ``upgrade`` MUST call current -- the control every
    drift test below runs first, because a fix that named drift on a clean
    tree would be the same false alarm from the other side (driven 2026-09-10:
    on this shape a fresh init says "nothing to do" and ``doctor`` says pass)."""
    import argparse
    from espalier.cli import cmd_init

    (tmp_path / "README.md").write_text("# t\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    # write_gitignore is what the CLI defaults to; a bare Namespace reads as
    # False, and a tree with no .gitignore is (rightly) never "nothing to do".
    assert cmd_init(argparse.Namespace(repo=str(tmp_path), config=None, write_gitignore=True)) == 0
    return tmp_path


def _grant_the_python_rules(tree: Path) -> None:
    """Give ``tree``'s settings.json the profile rules a Python fingerprint
    adds. A tree init'd with no Python and given a ``.py`` afterwards lacks
    them, and ``upgrade`` rightly names that gap (they render for a Python
    fingerprint only, DEF-965); a test whose stressor is that ``.py`` and
    whose oracle is something else grants them first, as an operator who ran
    ``merge-settings --add-allows`` would have."""
    import json

    from espalier.cli import _profile_allow_list

    settings = tree / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    allow = data["permissions"]["allow"]
    for rule in _profile_allow_list("workflow", fingerprint={"languages": ["python"]}):
        if rule not in allow:
            allow.append(rule)
    settings.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _upgrade(tmp_path: Path, *, execute: bool) -> int:
    import argparse
    from espalier.cli import cmd_upgrade

    return cmd_upgrade(argparse.Namespace(repo=str(tmp_path), execute=execute, config=None))


def test_preview_managed_surface_classifies_the_whole_deploy_set_without_writing(tmp_path):
    """DEF-726's oracle must classify exactly what ``deploy_harness`` writes.
    The pin is the deploy's OWN tally, not a copy of the enumerations the
    preview reads (a copy would pass over a new deploy step the preview
    forgot): on an empty tree the preview's ``created`` equals the deploy's
    written set; after the deploy the preview's ``skipped_no_drift`` equals a
    second deploy's; and the preview writes nothing. A second, derived pin:
    every path in the managed public inventory is classified here or is one
    of the packaged root docs, so a new managed surface cannot slip past."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import deploy_harness, preview_managed_surface
    from espalier.managed_inventory import _PACKAGED_ROOT_DOCS, get_managed_public_files
    from espalier.models import BuildPlan

    (tmp_path / ".git").mkdir()
    before = sorted(p.name for p in tmp_path.iterdir())
    predicted = preview_managed_surface(tmp_path, goal_snapshot=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "a preview wrote to the tree"
    for key in ("updated_managed", "skipped_user_files", "skipped_no_drift", "source_missing"):
        assert predicted[key] == [], (key, predicted[key])

    fp = fingerprint_repo(tmp_path)
    plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
    first = deploy_harness(tmp_path, plan, fp)
    assert set(predicted["created"]) == set(first["deployed"]), (
        "the preview and the deploy disagree about what an empty tree gets"
    )

    after = preview_managed_surface(tmp_path, goal_snapshot=True)
    second = deploy_harness(tmp_path, plan, fp)
    assert set(after["skipped_no_drift"]) == set(second["skipped_no_drift"])
    assert after["created"] == [] and after["updated_managed"] == []

    classified = {rel for paths in after.values() for rel in paths}
    unclassified = set(get_managed_public_files(tmp_path)) - classified - set(_PACKAGED_ROOT_DOCS)
    assert not unclassified, f"managed public files the preview never classifies: {sorted(unclassified)}"


def test_preview_renders_the_cc_docs_against_the_tree_as_it_is(tmp_path, capsys):
    """The declared caveat (DEF-757, FAILURE_MODES 5.25), pinned so it is a
    known shape and not a rediscovered bug: with one packaged agent deleted
    the preview names the agent (so the verdict holds) AND names
    cc/LIVE_SURFACE.md, which the deploy -- rendering after the agent lands --
    leaves unchanged. One --execute converges."""
    from espalier.cli import preview_managed_surface

    _initialized_tree(tmp_path)
    (tmp_path / ".claude" / "agents" / "code-reviewer.md").unlink()
    predicted = preview_managed_surface(tmp_path, goal_snapshot=True)
    assert ".claude/agents/code-reviewer.md" in predicted["created"]
    assert "cc/LIVE_SURFACE.md" in predicted["updated_managed"], "the caveat moved: update DEF-757"
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=True) == 0
    out = capsys.readouterr().out
    assert "re-deployed 1 file: .claude/agents/code-reviewer.md" in out
    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_upgrade_execute_converges_in_one_round_when_a_seed_doc_is_missing(tmp_path, capsys):
    """The seed docs deploy BEFORE the manifest renders, as init orders them:
    the manifest lists the packaged root docs on disk, so seeding after the
    render left cc/PACK_MANIFEST.txt one run behind and the preview run to
    confirm an --execute reported the command's own work as drift (driven by
    the failure-mode review: two rounds to converge)."""
    _initialized_tree(tmp_path)
    for rel in ("docs/CHEAT-SHEET.md", "docs/TASK_RECIPES.md"):
        (tmp_path / rel).unlink()
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out and "cc/PACK_MANIFEST.txt" in out
    assert _upgrade(tmp_path, execute=True) == 0
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out, "one --execute must converge"


def test_upgrade_names_an_absent_settings_json_as_a_file_the_deploy_writes(tmp_path, capsys):
    """A deleted .claude/settings.json is the state of an adopter who took
    init's default gitignore entry and cloned onto a second machine: the hooks
    are unwired. The preview classifies the root files on the deploy's own
    rule (created when absent), so the state is named for what it is rather
    than caught by whichever rendered doc happens to move."""
    _initialized_tree(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.unlink()
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert ".claude/settings.json" in out and "created on --execute" in out
    assert not settings.exists(), "a preview never writes"
    assert _upgrade(tmp_path, execute=True) == 0
    assert settings.exists()
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_upgrade_says_hand_edits_to_the_saved_plan_are_replaced(tmp_path, capsys):
    """The re-baseline regenerates reports/harness_config.json from the
    fingerprint and carries only settings_profile, as `fingerprint .` does.
    upgrade never wrote under reports/ before, so both modes say so where the
    operator decides, and this pin holds the contract to the sentence."""
    import json

    _initialized_tree(tmp_path)
    plan_path = tmp_path / "reports" / "harness_config.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["operator_note"] = "hand-edited"
    plan.setdefault("agents", []).append({"name": "legacy-reviewer"})  # forces the fall-through
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "would re-baseline" in out and "hand edits to it are replaced" in out
    assert json.loads(plan_path.read_text(encoding="utf-8"))["operator_note"] == "hand-edited"
    assert _upgrade(tmp_path, execute=True) == 0
    out = capsys.readouterr().out
    assert "re-baselined" in out and "hand edits to the plan replaced" in out
    after = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "operator_note" not in after
    assert after["settings_profile"] == plan["settings_profile"]


def _saved_plan(tree: Path) -> dict:
    import json

    return json.loads((tree / "reports" / "harness_config.json").read_text(encoding="utf-8"))


def test_upgrade_on_a_current_tree_lands_an_action_added_to_espalier_toml(tmp_path, capsys):
    """The version-current branch asked four oracles before "nothing to do"
    and none of them looked inside the saved plan, so an adopter who added an
    action to espalier.toml and ran the one verb whose job is reconciling the
    deployed surface was told there was nothing to do, while `doctor` on the
    same tree called the plan changed. The clean tree is the control, and the
    last run is the convergence: a plan that carries the configuration is not
    re-baselined again."""
    _initialized_tree(tmp_path)
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out

    (tmp_path / "espalier.toml").write_text(
        '[extra_actions]\nverify = ["npm test"]\n', encoding="utf-8")
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert "espalier.toml" in out and "verify" in out
    assert "verify" not in _saved_plan(tmp_path)["stable_actions"], "a dry run wrote the plan"

    assert _upgrade(tmp_path, execute=True) == 0
    capsys.readouterr()
    assert _saved_plan(tmp_path)["stable_actions"]["verify"] == ["npm test"]

    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_upgrade_on_a_current_tree_lands_the_zone_keys_of_espalier_toml(tmp_path, capsys):
    _initialized_tree(tmp_path)
    (tmp_path / "espalier.toml").write_text(
        'protected_paths = ["src/secrets/"]\ngenerated_paths = ["build/out/"]\n',
        encoding="utf-8")
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert "protected_paths" in out and "generated_paths" in out

    assert _upgrade(tmp_path, execute=True) == 0
    capsys.readouterr()
    plan = _saved_plan(tmp_path)
    assert "src/secrets/" in plan["mutable_zones"]
    assert "build/out/" in plan["read_only_zones"]

    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_upgrade_sees_a_suppressed_action_the_saved_plan_still_carries(tmp_path, capsys):
    _initialized_tree(tmp_path)
    (tmp_path / "espalier.toml").write_text(
        '[extra_actions]\nverify = ["npm test"]\n', encoding="utf-8")
    assert _upgrade(tmp_path, execute=True) == 0
    assert "verify" in _saved_plan(tmp_path)["stable_actions"]

    # Suppression wins over an extra of the same name, as the plan builder
    # applies them, so this configuration must converge and not loop.
    (tmp_path / "espalier.toml").write_text(
        'suppress_actions = ["verify"]\n\n[extra_actions]\nverify = ["npm test"]\n',
        encoding="utf-8")
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert "actions to drop: verify" in out

    assert _upgrade(tmp_path, execute=True) == 0
    capsys.readouterr()
    assert "verify" not in _saved_plan(tmp_path)["stable_actions"]
    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_when_upgrade_says_nothing_to_do_doctor_sees_no_plan_change(tmp_path, capsys):
    """The two verbs read one tree. Scoped to the plan diff, not doctor's
    overall status, which has other reasons to warn."""
    from espalier.doctor import run_doctor_check

    _initialized_tree(tmp_path)
    converged = 0
    # An action added, landed and converged; then the same action REMOVED from
    # the file, which a comparison reading only what the file declares cannot
    # see (the plan still carries it and the file no longer mentions it).
    for config_text in ('[extra_actions]\nverify = ["npm test"]\n', "# nothing declared\n"):
        (tmp_path / "espalier.toml").write_text(config_text, encoding="utf-8")
        for execute in (False, True, False):
            capsys.readouterr()
            assert _upgrade(tmp_path, execute=execute) == 0
            said_nothing = "nothing to do" in capsys.readouterr().out
            changed = run_doctor_check(tmp_path, skip_self_host=True)["checks"]["diff"][
                "build_plan_changed"]
            assert not (said_nothing and changed), (
                f"upgrade (execute={execute}) said nothing to do over a plan doctor "
                f"calls changed, with espalier.toml = {config_text!r}"
            )
        converged += said_nothing
    assert converged == 2, (
        "each round must end on a converged tree; without that the implication "
        "above was never exercised"
    )


def test_upgrade_survives_an_extra_actions_entry_that_is_not_a_command_list(tmp_path, capsys):
    """A top-level key written below the ``[extra_actions]`` header belongs to
    that table, so ``lane_count = 5`` there is an action whose commands are
    the number five, and a string is one command per character. The loader
    drops both and names them with the file; upgrade applies the entry that
    can be read, and nothing of the two reaches the saved plan. Driven on a
    tree with drift of its own as well, because the stages that rebuild the
    plan are reached from there whatever this comparison says."""
    import warnings

    _initialized_tree(tmp_path)
    hook = tmp_path / "tools" / "cc" / "hooks" / "post_write_check.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    (tmp_path / "espalier.toml").write_text(
        '[extra_actions]\nverify = ["npm test"]\nlane_count = 5\n'
        'default_profile = "workflow"\n', encoding="utf-8")
    capsys.readouterr()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert _upgrade(tmp_path, execute=True) == 0
    assert "nothing to do" not in out
    assert "espalier.toml" in out and "verify" in out
    said = " ".join(str(w.message) for w in caught)
    assert "lane_count" in said and "default_profile" in said and "espalier.toml" in said
    actions = _saved_plan(tmp_path)["stable_actions"]
    assert actions["verify"] == ["npm test"]
    assert "lane_count" not in actions and "default_profile" not in actions


def test_upgrade_says_so_when_the_saved_fingerprint_cannot_be_read(tmp_path, capsys):
    """The comparison rebuilds from the fingerprint on disk. Without one it
    did not run, and an oracle that did not run is narrated, never read as
    clean."""
    _initialized_tree(tmp_path)
    (tmp_path / "reports" / "repo_fingerprint.json").unlink()
    (tmp_path / "espalier.toml").write_text(
        '[extra_actions]\nverify = ["npm test"]\n', encoding="utf-8")
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert "not compared: espalier.toml against the saved plan" in out


def test_upgrade_on_the_self_host_tree_does_not_call_the_source_adopter_edits(capsys):
    """On this repo the deploy source IS the tree (tools/cc/ feeds the vendored
    mirror; .claude/ feeds the packaged bodies), so every source file differs
    from "the packaged version" and carries no marker by design. Before the
    guard, `upgrade .` here named seventy source files as kept adopter edits
    and printed the one remedy -- add the marker -- that would let a later
    deploy write the mirror over the source. Dry run only: read-only here."""
    import argparse
    from espalier import __version__
    from espalier.cli import _read_deployed_version, cmd_upgrade

    if _read_deployed_version(REPO_ROOT) != __version__:
        pytest.skip("self-host manifest stamp is not the running engine's")
    capsys.readouterr()
    assert cmd_upgrade(argparse.Namespace(repo=str(REPO_ROOT), execute=False, config=None)) == 0
    out = capsys.readouterr().out
    assert "not compared: the packaged surface (self-host tree" in out
    assert "add the marker line" not in out and "kept as yours" not in out


def test_a_crlf_copy_of_a_deployed_file_reads_as_no_drift(tmp_path):
    """The classifiers compare text after read_text's universal-newline
    translation, which is what keeps a Windows checkout under core.autocrlf
    from reading as seventy files of permanent drift (DEF-725 is the
    manifest's separate answer). A byte compare would break this silently."""
    from espalier.cli import preview_managed_surface

    _deployed_current_tree(tmp_path)
    rel = "tools/cc/hooks/post_write_check.py"
    hook = tmp_path / rel
    lf = hook.read_bytes()
    assert b"\r\n" not in lf
    hook.write_bytes(lf.replace(b"\n", b"\r\n"))
    agent = tmp_path / ".claude" / "agents" / "code-reviewer.md"
    agent.write_bytes(agent.read_bytes().replace(b"\n", b"\r\n"))
    tally = preview_managed_surface(tmp_path, goal_snapshot=True)
    assert rel in tally["skipped_no_drift"], "a CRLF working copy must not read as drift"
    assert ".claude/agents/code-reviewer.md" in tally["skipped_no_drift"]


def test_upgrade_does_not_say_nothing_to_do_when_the_packaged_bodies_are_missing(
    tmp_path, capsys, monkeypatch,
):
    """A wheel that shipped the hooks but not espalier/assets/claude/ used to
    enumerate an empty .md set and agree with itself: "nothing to do" over a
    tree with no agents, commands or skills deployable. The missing kind
    directories are named as missing sources and qualify the sentence."""
    import espalier.cli as cli

    _initialized_tree(tmp_path)
    bare_root = tmp_path / "bare-engine-root"
    bare_root.mkdir()
    monkeypatch.setattr(cli, "_espalier_root", lambda: bare_root)
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    captured = capsys.readouterr()
    assert "nothing to do" not in captured.out
    assert "packaged source" in captured.err and ".claude/agents/ (packaged bodies)" in captured.err
    assert "missing from this engine install" in captured.out


def test_upgrade_names_a_managed_file_that_differs_from_the_packaged_bytes(tmp_path, capsys):
    """DEF-726 (walk 2, W2-38, driven on the Windows host): a deployed hook
    altered by one appended line, stamp current. Before: the dry run said
    "harness is current; nothing to do", ``--execute`` printed the same and the
    line survived, while ``doctor`` on the tree said fail. Now: the control
    tree says nothing to do; the altered tree is named under its drift class
    and the preview writes nothing; ``--execute`` restores the packaged bytes
    and names the file; and the tree is current again afterwards. Both
    branches of the early return are driven (FAILURE_MODES: test both)."""
    from espalier.cli import _deploy_source_path
    from espalier.managed_markers import apply_marker_to_text

    _initialized_tree(tmp_path)
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out, "control: a fresh init must read as current"

    rel = "tools/cc/hooks/post_write_check.py"  # the file walk 2 altered
    hook = tmp_path / rel
    packaged = apply_marker_to_text(_deploy_source_path(rel).read_text(encoding="utf-8"))
    assert hook.read_text(encoding="utf-8") == packaged
    altered = packaged + "# WALK2-DRIFT-MARKER\n"
    hook.write_text(altered, encoding="utf-8")

    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert "but the deployed surface is not current" in out
    assert rel in out and "differs from the packaged version" in out
    assert hook.read_text(encoding="utf-8") == altered, "a preview never writes"

    assert _upgrade(tmp_path, execute=True) == 0
    out = capsys.readouterr().out
    assert hook.read_text(encoding="utf-8") == packaged, "--execute did not restore the packaged bytes"
    assert f"re-deployed 1 file: {rel}" in out

    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_upgrade_names_a_saved_plan_path_no_longer_on_disk_and_rebaselines_it(tmp_path, capsys):
    """DEF-728 (walk 2, W2-17, driven on the Windows host): a three-week-old
    fusion whose saved plan still listed an agent the engine no longer ships
    read as current while ``doctor`` said warn. Now the retired path is named
    under its drift class, the preview leaves the plan alone, ``--execute``
    re-baselines the plan (the way install-ci re-baselines what it changes,
    DEF-688), and afterwards ``upgrade`` and ``doctor`` agree the tree is
    current. The name is one no builder recommends: the walk's own
    ``component-reviewer`` turned out to be an unshipped recommendation, which
    is information, not drift (DEF-756)."""
    import json
    from espalier.doctor import run_doctor_check

    _initialized_tree(tmp_path)
    plan_path = tmp_path / "reports" / "harness_config.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan.setdefault("agents", []).append({"name": "legacy-reviewer"})
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stale = ".claude/agents/legacy-reviewer.md"
    assert not (tmp_path / stale).exists()
    capsys.readouterr()

    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "nothing to do" not in out
    assert stale in out and "no longer on disk" in out
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan, "a preview never writes"

    assert _upgrade(tmp_path, execute=True) == 0
    out = capsys.readouterr().out
    assert "re-baselined reports/repo_fingerprint.json" in out and "reports/harness_config.json" in out
    after = json.loads(plan_path.read_text(encoding="utf-8"))
    assert all(a.get("name") != "legacy-reviewer" for a in after["agents"])
    assert after["settings_profile"] == plan["settings_profile"], "the re-baseline forgot the profile"

    assert _upgrade(tmp_path, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out
    report = run_doctor_check(tmp_path)
    assert not any("saved-plan" in w or "saved plan" in w for w in report["warnings"]), report["warnings"]


def test_upgrade_names_a_kept_user_edit_without_falling_through_forever(tmp_path, capsys):
    """A managed file the adopter edited and un-marked is kept by the deploy
    contract, so it must not read as repairable drift: that would send every
    later run through the stages to say the same thing. It is named beside
    the sentence, the sentence stops short of "nothing to do", ``--execute``
    leaves the file alone, and the run after still does not fall through."""
    _initialized_tree(tmp_path)
    rel = "tools/cc/hooks/post_write_check.py"
    hook = tmp_path / rel
    text = hook.read_text(encoding="utf-8")
    assert "espalier:managed" in text, "fixture: the deployed hook carries the marker"
    edited = text.replace("espalier:managed", "adopter-owned") + "# local patch\n"
    hook.write_text(edited, encoding="utf-8")
    capsys.readouterr()

    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "harness is current" in out and "nothing to do" not in out
    assert f"kept as yours: {rel}" in out and "1 managed file kept as yours" in out
    assert "deployed surface is not current" not in out

    assert _upgrade(tmp_path, execute=True) == 0
    assert hook.read_text(encoding="utf-8") == edited, "--execute must keep an un-marked file"
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "deployed surface is not current" not in out and f"kept as yours: {rel}" in out


def _packaged_skill_and_command() -> tuple[str, str]:
    """Read from the roster, never typed: a renamed asset must not strand a row."""
    from espalier.asset_inventory import get_packaged_surface

    surface = get_packaged_surface()
    skill = sorted(p.replace("\\", "/").split("/")[0] for p in surface.skills.paths)[0]
    command = sorted(Path(p).stem for p in surface.commands.paths)[0]
    return skill, command


def _stamp_older(tmp_path: Path) -> None:
    """Send ``upgrade`` down its different-version arm: the deployed stamp names
    an engine older than the installed one."""
    manifest = tmp_path / "cc" / "PACK_MANIFEST.txt"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    stamped = [("# espalier-version: 0.0.1" if ln.startswith("# espalier-version:") else ln) for ln in lines]
    assert stamped != lines, "fixture: the deploy stamps its version"
    manifest.write_text("\n".join(stamped) + "\n", encoding="utf-8")


class TestUpgradeNamesWhatItKeepsWithoutPresumingAuthorship:
    """DEF-1096: ``upgrade`` called an adopter's own ``.claude`` file at a
    packaged name an edited Espalier copy and offered, as its one remedy, the
    marker line whose consequence is that the next deploy overwrites the file.
    It also never named a command-versus-skill shadow, on either arm.
    Mutations: restore the bespoke line and the first row reds on both
    assertions; drop the shadow call from either arm and its row goes quiet."""

    def test_the_kept_line_states_what_the_marker_would_do(self, tmp_path, capsys):
        _initialized_tree(tmp_path)
        _, command = _packaged_skill_and_command()
        rel = f".claude/commands/{command}.md"
        (tmp_path / rel).write_text("# our own command, never Espalier's\n", encoding="utf-8")
        capsys.readouterr()
        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert f"kept as yours: {rel}" in out, out
        assert "opt back into regeneration" not in out, "the remedy presumed an edited copy"
        assert "replaces it with the packaged version" in out, out
        assert "stays yours" in out, "the .claude/ note is the shared wording's"

    def test_the_same_version_arm_names_a_command_a_packaged_skill_replaces(self, tmp_path, capsys):
        _initialized_tree(tmp_path)
        skill, _ = _packaged_skill_and_command()
        (tmp_path / ".claude" / "commands" / f"{skill}.md").write_text("# ours\n", encoding="utf-8")
        capsys.readouterr()
        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert f"your /{skill} command (.claude/commands/{skill}.md) is replaced by the harness's {skill} skill" in out, out

    def test_the_different_version_arm_names_the_shadow_and_the_kept_file(self, tmp_path, capsys):
        _initialized_tree(tmp_path)
        skill, command = _packaged_skill_and_command()
        (tmp_path / ".claude" / "commands" / f"{skill}.md").write_text("# ours\n", encoding="utf-8")
        kept = tmp_path / ".claude" / "commands" / f"{command}.md"
        kept.write_text("# our own command, never Espalier's\n", encoding="utf-8")
        _stamp_older(tmp_path)
        capsys.readouterr()

        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert "deployed 0.0.1 -> engine" in out, "fixture: the different-version arm ran"
        assert f"would keep as yours: .claude/commands/{command}.md" in out, out
        assert f"would be replaced by the harness's {skill} skill" in out, out

        assert _upgrade(tmp_path, execute=True) == 0
        out = capsys.readouterr().out
        assert f"kept as yours: .claude/commands/{command}.md" in out, out
        assert f"is replaced by the harness's {skill} skill" in out, out
        assert kept.read_text(encoding="utf-8") == "# our own command, never Espalier's\n"

    def test_a_drifted_same_version_tree_names_each_kept_file_once(self, tmp_path, capsys):
        """The same-version arm names what it keeps, then a drifted tree falls
        through to the stages below, which named it again (the lane's review:
        three copies on --execute). Mutation: drop ``kept_named`` and the
        counts below read 2."""
        _initialized_tree(tmp_path)
        skill, command = _packaged_skill_and_command()
        (tmp_path / ".claude" / "commands" / f"{skill}.md").write_text("# ours\n", encoding="utf-8")
        (tmp_path / ".claude" / "commands" / f"{command}.md").write_text("# ours too\n", encoding="utf-8")
        hook = tmp_path / "tools" / "cc" / "hooks" / "post_write_check.py"
        hook.write_text(hook.read_text(encoding="utf-8") + "# drift, marker kept\n", encoding="utf-8")
        capsys.readouterr()
        for execute in (False, True):
            assert _upgrade(tmp_path, execute=execute) == 0
            out = capsys.readouterr().out
            assert "deployed surface is not current" in out, "fixture: the tree drifted"
            assert out.count("as yours: ") == 1, out
            assert out.count(f"harness's {skill} skill") == 1, out


def test_upgrade_says_the_saved_plan_was_not_compared_when_it_is_absent(tmp_path, capsys):
    """An oracle that cannot run is narrated, never read as clean: with no
    ``reports/harness_config.json`` the ownership delta is "could not
    compute", so the sentence says what was compared and does not say
    "nothing to do" (the return-0 green-wash shape)."""
    _deployed_current_tree(tmp_path)  # the deploy writes no plan; init does
    assert not (tmp_path / "reports").exists()
    capsys.readouterr()
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "harness is current" in out
    assert "nothing to do" not in out
    assert "not compared: the saved plan" in out and "reports/harness_config.json" in out

    # The drift arm says it too: a leg that could not run is narrated on both
    # arms, or the adopter with an altered hook AND no plan hears only half.
    hook = tmp_path / "tools" / "cc" / "hooks" / "post_write_check.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    assert _upgrade(tmp_path, execute=False) == 0
    out = capsys.readouterr().out
    assert "deployed surface is not current" in out
    assert "not compared: the saved plan" in out


def _stamp(tmp_path: Path, version: str) -> None:
    """Rewrite the deployed stamp in ``cc/PACK_MANIFEST.txt`` to ``version``."""
    manifest = tmp_path / "cc" / "PACK_MANIFEST.txt"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    stamped = [(f"# espalier-version: {version}" if ln.startswith("# espalier-version:") else ln)
               for ln in lines]
    assert stamped != lines, "fixture: the deploy stamps its version"
    manifest.write_text("\n".join(stamped) + "\n", encoding="utf-8")


def _tree_digest(root: Path) -> dict[str, str]:
    """Every file under ``root`` but ``.git`` by its content hash: "nothing
    was written" proven on the whole tree, not on the one file a test
    edited (a refusal moved below the first write would pass a one-file
    check)."""
    import hashlib

    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


class TestUpgradeAgainstTheStampAndTheSavedPlan:
    """TP-474 lane 2, the unit half of the Walk's four upgrade classes: each
    test drives one row's state in process, where the Walk drives the
    sequence. The rows: DEF-1063 (no saved plan), DEF-1064 (every overwritten
    file named), DEF-1104 (a newer deployed stamp), DEF-1126 (a retired
    fingerprint key)."""

    def test_the_version_bump_preview_and_report_name_an_edited_body_past_ten(
        self, tmp_path, capsys,
    ):
        """DEF-1064: twelve hooks ahead of it took the ten slots, and the
        version-bump preview printed one generic sentence, so the edited body
        went unnamed until it was gone. Mutation: the generic sentence back,
        or ``_name_paths``'s default cap, and the body is not named."""
        _initialized_tree(tmp_path)
        hooks = sorted((tmp_path / "tools" / "cc" / "hooks").glob("*.py"))[:12]
        assert len(hooks) == 12, "fixture: twelve hooks to stale"
        for hook in hooks:
            hook.write_text(hook.read_text(encoding="utf-8") + "#x\n", encoding="utf-8")
        body = ".claude/agents/code-reviewer.md"
        (tmp_path / body).write_text((tmp_path / body).read_text(encoding="utf-8") + "\nlane\n",
                                     encoding="utf-8")
        _stamp_older(tmp_path)
        capsys.readouterr()

        for execute in (False, True):
            assert _upgrade(tmp_path, execute=execute) == 0
            out = capsys.readouterr().out
            named = [ln for ln in out.splitlines() if body in ln]
            assert named, out
            # The line that names the body says what the marker did to it.
            assert any("managed marker line" in ln for ln in named), named
        assert "lane" not in (tmp_path / body).read_text(encoding="utf-8").splitlines()

    @pytest.mark.parametrize(("deployed", "engine", "newer"), [
        ("99.0.0", "0.8.0b2", True),
        ("0.8.0", "0.8.0b2", True),       # a release above its own pre-releases
        ("0.8.0rc1", "0.8.0b2", True),
        ("0.8.0b3", "0.8.0b2", True),
        ("0.8.0b2", "0.8.0b2", False),    # one string, two builds: the row's open half
        ("0.8.0a1", "0.8.0b2", False),
        ("0.0.1", "0.8.0b2", False),
        ("0.0.1-old", "0.8.0b2", False),  # a shape it cannot read never refuses
        ("0.8.0.dev1", "0.8.0b2", False),
        (None, "0.8.0b2", False),
    ])
    def test_the_stamp_order_ranks_pre_releases_and_fails_open(self, deployed, engine, newer):
        from espalier.cli import _deployed_is_newer

        assert _deployed_is_newer(deployed, engine) is newer

    def test_a_newer_deployed_stamp_refuses_every_writing_verb_and_writes_nothing(
        self, tmp_path, capsys,
    ):
        """DEF-1104's ordering half: an older engine over a newer deployment
        rolled every marked file back and called it repairing drift; ``init``
        never read the stamp, nor did ``install-ci`` (the merge gate) or
        ``fingerprint`` (the plan readers and runner bodies), the sisters the
        failure-mode review drove. Each refuses before a write -- the whole
        tree is compared, not one file -- and names what it would roll back
        and the way past on purpose. Mutation: drop any one call and that
        verb exits 0 and rewrites the tree."""
        import argparse
        from espalier.cli import cmd_fingerprint, cmd_init, cmd_install_ci

        _initialized_tree(tmp_path)
        assert cmd_install_ci(argparse.Namespace(repo=str(tmp_path))) == 0
        rel = "tools/cc/hooks/post_write_check.py"
        hook = tmp_path / rel
        hook.write_text(hook.read_text(encoding="utf-8") + "# from the newer build\n",
                        encoding="utf-8")
        _stamp(tmp_path, "99.0.0")
        before = _tree_digest(tmp_path)
        capsys.readouterr()

        runs = [
            ("upgrade", rel, lambda: _upgrade(tmp_path, execute=False)),
            ("upgrade", rel, lambda: _upgrade(tmp_path, execute=True)),
            ("init", rel, lambda: cmd_init(argparse.Namespace(
                repo=str(tmp_path), config=None, write_gitignore=True))),
            ("init", rel, lambda: cmd_init(argparse.Namespace(
                repo=str(tmp_path), config=None, write_gitignore=True, dry_run=True))),
            ("install-ci", "tools/cc/ci_guard.py",
             lambda: cmd_install_ci(argparse.Namespace(repo=str(tmp_path)))),
            ("fingerprint", "cc/COMMANDS.md",
             lambda: cmd_fingerprint(argparse.Namespace(repo=str(tmp_path), config=None))),
        ]
        for verb, named, run in runs:
            assert run() == 2, verb
            out, err = capsys.readouterr()
            assert "99.0.0" in out and "newer" in out, (verb, out)
            assert "would re-deploy" not in out, (verb, out)
            assert "REFUSED" in err and named in err, (verb, err)
            assert "To roll back on purpose" in err, (verb, err)
            assert _tree_digest(tmp_path) == before, verb

        # The control: the same tree at the engine's own stamp is not refused.
        from espalier import __version__
        _stamp(tmp_path, __version__)
        assert _upgrade(tmp_path, execute=False) == 0
        # And the named way past: the stamp line removed reads as unstamped.
        _stamp(tmp_path, "99.0.0")
        manifest = tmp_path / "cc" / "PACK_MANIFEST.txt"
        manifest.write_text("".join(ln for ln in manifest.read_text(encoding="utf-8")
                                    .splitlines(keepends=True)
                                    if not ln.startswith("# espalier-version:")),
                            encoding="utf-8")
        assert _upgrade(tmp_path, execute=False) == 0

    def test_execute_without_the_saved_plan_refuses_and_the_preview_says_so(
        self, tmp_path, capsys,
    ):
        """DEF-1063: every clone lacks the gitignored plan, and ``--execute``
        re-rendered the two plan-reading docs from an empty table while the
        preview listed them as drift. The execute refuses before any write
        and names ``init .``; the preview reports what differs, sets the two
        docs aside as not compared, and promises no stage. Mutation: drop the
        refusal and the execute exits 0 and rewrites the hook."""
        import argparse
        from espalier.cli import cmd_init

        import json

        _initialized_tree(tmp_path)
        (tmp_path / "reports" / "harness_config.json").unlink()
        hook = tmp_path / "tools" / "cc" / "hooks" / "post_write_check.py"
        hook.write_text(hook.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        # A settings file already here (a tracked one, or a plan lost in
        # place) with an event the engine wires dropped: plain init leaves it
        # unwired, so the redirect must carry --wire-hooks (the failure-mode
        # review drove it).
        settings = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        dropped = sorted(data["hooks"])[0]
        del data["hooks"][dropped]
        settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        before = _tree_digest(tmp_path)
        capsys.readouterr()

        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert "deployed surface is not current" in out and "post_write_check.py" in out, out
        assert "render differently" not in out, out
        assert "cc/COMMANDS.md and cc/LIVE_SURFACE.md, which render from it" in out, out
        assert "regenerated by `" in out and "init . --wire-hooks`" in out, out
        assert "is absent" in out, out
        self._assert_promises_no_execute(out)
        assert _tree_digest(tmp_path) == before

        assert _upgrade(tmp_path, execute=True) == 2
        out, err = capsys.readouterr()
        assert "REFUSED" in err and "init . --wire-hooks" in err, err
        assert _tree_digest(tmp_path) == before

        # The redirect is the repair: the command it names writes the plan,
        # wires the dropped event, and --execute then runs.
        assert cmd_init(argparse.Namespace(repo=str(tmp_path), config=None,
                                           write_gitignore=True, wire_hooks=True)) == 0
        assert dropped in json.loads(settings.read_text(encoding="utf-8"))["hooks"]
        assert _upgrade(tmp_path, execute=True) == 0

    def test_the_restore_command_follows_the_tree(self, tmp_path, monkeypatch):
        """The redirect names the command that does what --execute would:
        plain ``init .`` where init writes settings fresh, ``--wire-hooks``
        where a settings file is already here, and ``doctor`` on Espalier's
        own source tree, where init rewrites tracked docs."""
        from espalier import cli, surface_contract

        assert cli._plan_restore_command(tmp_path).endswith("-m espalier init .")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        assert cli._plan_restore_command(tmp_path).endswith("-m espalier init . --wire-hooks")
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda _root: True)
        assert cli._plan_restore_command(tmp_path) is None
        sentence = cli._no_saved_plan_sentence(tmp_path)
        assert "doctor ." in sentence and "init ." not in sentence, sentence

    @staticmethod
    def _assert_promises_no_execute(out: str) -> None:
        """A plan-less preview names what differs and the verb that applies
        it; no line previews a stage or credits --execute, which refuses
        (the review's mutation: a stage gate dropped, a drift line's verb)."""
        for line in out.splitlines():
            assert "on --execute" not in line, line
            assert not line.startswith("[upgrade] would "), line

    def test_an_older_stamped_clone_previews_no_stage_and_refuses_the_execute(
        self, tmp_path, capsys,
    ):
        """The version-bump arm never loaded the plan, so a clone of an
        older-stamped install went straight to the deploy (the 0-A review).
        Refused there too; its preview promises no stage, and names what the
        restore command would replace -- the edited body included -- before
        that command runs (the failure-mode review: the path the refusal
        sends a clone down named the body only after it was gone)."""
        import argparse
        from espalier.cli import cmd_init

        _initialized_tree(tmp_path)
        (tmp_path / "reports" / "harness_config.json").unlink()
        body = ".claude/agents/code-reviewer.md"
        (tmp_path / body).write_text((tmp_path / body).read_text(encoding="utf-8") + "\nlane\n",
                                     encoding="utf-8")
        _stamp_older(tmp_path)
        capsys.readouterr()

        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert "deployed 0.0.1 -> engine" in out and "init ." in out, out
        named = [ln for ln in out.splitlines() if body in ln]
        assert named and any("managed marker line" in ln for ln in named), out
        self._assert_promises_no_execute(out)
        assert _upgrade(tmp_path, execute=True) == 2
        assert "REFUSED" in capsys.readouterr().err
        # init's own preview names the body it would replace, too.
        assert cmd_init(argparse.Namespace(repo=str(tmp_path), config=None,
                                           write_gitignore=True, dry_run=True)) == 0
        out = capsys.readouterr().out
        assert any(body in ln and "Would replace" in ln for ln in out.splitlines()), out

    def test_an_unreadable_plan_is_named_unreadable_not_absent(self, tmp_path, capsys):
        """``load_harness_plan`` reads a corrupt file as no plan; the refusal
        must not tell the operator a file that is there does not exist."""
        _initialized_tree(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text("{not json", encoding="utf-8")
        capsys.readouterr()

        assert _upgrade(tmp_path, execute=True) == 2
        err = capsys.readouterr().err
        assert "cannot be read" in err and "is absent" not in err, err

    def test_a_never_deployed_tree_keeps_its_own_exit_and_sentence(self, tmp_path, capsys):
        """The plan refusal is asked only where a deployment exists: a tree
        with no manifest still exits 1 naming init for a first-time setup."""
        (tmp_path / ".git").mkdir()
        capsys.readouterr()

        assert _upgrade(tmp_path, execute=True) == 1
        err = capsys.readouterr().err
        assert "no harness deployment found" in err and "REFUSED" not in err, err

    def test_a_retired_fingerprint_key_reads_older_and_execute_clears_it(
        self, tmp_path, capsys,
    ):
        """DEF-1126: the saved fingerprint with one retired key was called
        "absent or unreadable". It is older: compared on the declared fields,
        named, and re-baselined once by ``--execute``, after which the line is
        gone. Mutation: ``cls(**payload)`` in ``from_dict`` and the dry run
        says unreadable again."""
        import json

        _initialized_tree(tmp_path)
        fp_path = tmp_path / "reports" / "repo_fingerprint.json"
        saved = json.loads(fp_path.read_text(encoding="utf-8"))
        saved["retired_field"] = 1
        fp_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        capsys.readouterr()

        assert _upgrade(tmp_path, execute=False) == 0
        out = capsys.readouterr().out
        assert "absent or unreadable" not in out, out
        assert "saved by an older release" in out and "retired_field" in out, out

        assert _upgrade(tmp_path, execute=True) == 0
        capsys.readouterr()
        assert "retired_field" not in json.loads(fp_path.read_text(encoding="utf-8"))
        assert _upgrade(tmp_path, execute=False) == 0
        assert "saved by an older release" not in capsys.readouterr().out


class TestLedgerSeed:
    """The forward ledger reaches an adopter (2026-09-30): ``init`` seeds the
    skeleton and files the onboarding rows through the DEPLOYED verb. Before,
    it seeded no ledger and deployed none of the verbs, so the review
    workflows' dedup step read nothing on every adopter tree."""

    @staticmethod
    def _install(root: Path, **config) -> dict:
        from espalier.analyze import fingerprint_repo
        from espalier.cli import _deploy_seed_docs, _file_onboarding_rows, deploy_harness
        from espalier.models import BuildPlan, HarnessConfig

        (root / ".git").mkdir(exist_ok=True)
        _deploy_seed_docs(root)
        deploy_harness(root, BuildPlan(repo_name="x", config=HarnessConfig(**config)),
                       fingerprint_repo(root))
        return _file_onboarding_rows(root)

    @staticmethod
    def _cc(name: str):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"_seed_test_{name}", REPO_ROOT / "tools" / "cc" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_fresh_tree_gets_every_onboarding_row_filed_and_converged(self, tmp_path, capsys):
        from espalier.cli import _ONBOARDING_ROWS

        outcome = self._install(tmp_path)
        assert outcome == {"filed": [r["id"] for r in _ONBOARDING_ROWS], "satisfied": [], "failed": []}
        gen = self._cc("generate_ledger_regions")
        text = (tmp_path / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        assert gen.live_member_ids(text) == {r["id"] for r in _ONBOARDING_ROWS}
        assert gen.main(["--root", str(tmp_path), "--check"]) == 0
        checker = self._cc("check_ledger_probes")
        capsys.readouterr()
        assert checker.main(["--root", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        opened = sum(1 for r in _ONBOARDING_ROWS if "code" in r)
        assert f"STILL_OPEN         {opened}" in out
        assert f"NO_ORACLE          {len(_ONBOARDING_ROWS) - opened}" in out

    def test_an_opted_in_tree_gets_its_rows_as_files_and_is_told_so(self, tmp_path):
        """``ledger_fragments = true`` before the first install: the deployed
        verb writes a row file and a probe file per row, the seed file stays
        the untouched seed, the sentence names where the rows went, and a
        second install files nothing. Dies to: the sentence naming the big
        file (round-2 review), or the onboarding gate reading the seed file
        alone (every upgrade re-filed and failed)."""
        from espalier.cli import _ONBOARDING_ROWS, _onboarding_sentence

        (tmp_path / "espalier.toml").write_text("ledger_fragments = true\n", encoding="utf-8")
        outcome = self._install(tmp_path)
        ids = [r["id"] for r in _ONBOARDING_ROWS]
        assert outcome["filed"] == ids and outcome["failed"] == []
        packs = tmp_path / "task-packs"
        assert sorted(p.stem for p in (packs / "ledger.d").glob("*.md")) == sorted(ids)
        assert "into task-packs/ledger.d/ (a file each)" in _onboarding_sentence(outcome)
        gen = self._cc("generate_ledger_regions")
        assert gen.main(["--root", str(tmp_path), "--check"]) == 0
        seed = (packs / "FORWARD_LEDGER.md").read_bytes()
        assert self._install(tmp_path) == {"filed": [], "satisfied": [], "failed": []}
        assert (packs / "FORWARD_LEDGER.md").read_bytes() == seed

    def test_a_second_install_files_nothing_again(self, tmp_path):
        self._install(tmp_path)
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        before = ledger.read_bytes()
        assert self._install(tmp_path) == {"filed": [], "satisfied": [], "failed": []}
        assert ledger.read_bytes() == before

    def test_a_row_the_tree_already_satisfies_is_not_filed(self, tmp_path):
        (tmp_path / "espalier.toml").write_text(
            "goal_snapshot = false\nplan_exempt_prefixes = []\n", encoding="utf-8")
        outcome = self._install(tmp_path, goal_snapshot=False, plan_exempt_prefixes=[])
        assert outcome["satisfied"] == ["ONB-1", "ONB-6"] and outcome["failed"] == []
        text = (tmp_path / "task-packs" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
        assert "`ONB-1`" not in text and "`ONB-6`" not in text and "`ONB-7`" in text
        gen = self._cc("generate_ledger_regions")
        assert gen.main(["--root", str(tmp_path), "--check"]) == 0

    def test_a_ledger_that_is_not_the_untouched_seed_is_left_alone(self, tmp_path):
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("# my own ledger\n", encoding="utf-8")
        assert self._install(tmp_path) == {"filed": [], "satisfied": [], "failed": []}
        assert ledger.read_text(encoding="utf-8") == "# my own ledger\n"

    def test_a_held_lock_stops_the_filing_with_one_whole_message(self, tmp_path):
        """Every row would meet the same lock: one failure naming it whole (path
        and remedy), not seven truncated ones (failure-mode review, 2026-09-30)."""
        from espalier.analyze import fingerprint_repo
        from espalier.cli import _deploy_seed_docs, _file_onboarding_rows, deploy_harness
        from espalier.models import BuildPlan, HarnessConfig

        (tmp_path / ".git").mkdir()
        _deploy_seed_docs(tmp_path)
        deploy_harness(tmp_path, BuildPlan(repo_name="x", config=HarnessConfig()),
                       fingerprint_repo(tmp_path))
        (tmp_path / "task-packs" / "FORWARD_LEDGER.md.lock").write_text("pid 9\n", encoding="utf-8")
        outcome = _file_onboarding_rows(tmp_path)
        assert outcome["filed"] == [] and len(outcome["failed"]) == 1
        assert "every row after it" in outcome["failed"][0]
        assert "FORWARD_LEDGER.md.lock" in outcome["failed"][0] and "delete the file" in outcome["failed"][0]

    def test_without_the_verb_nothing_is_filed_and_nothing_raises(self, tmp_path):
        from espalier.cli import _deploy_seed_docs, _file_onboarding_rows

        (tmp_path / ".git").mkdir()
        _deploy_seed_docs(tmp_path)
        assert _file_onboarding_rows(tmp_path) == {"filed": [], "satisfied": [], "failed": []}

    @staticmethod
    def _snapshot(root: Path) -> dict[str, tuple]:
        """Every entry under ``root`` with what a write would change: a file's
        size and mtime, a directory as itself (an empty ``__pycache__`` counts)."""
        out: dict[str, tuple] = {}
        for p in root.rglob("*"):
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                out[rel + "/"] = ("dir",)
            else:
                st = p.stat()
                out[rel] = (st.st_size, st.st_mtime_ns)
        return out

    def test_the_seeding_writes_exactly_the_ledger_and_its_probes(self, tmp_path, monkeypatch):
        """The verb imports its siblings by path, and the interpreter cached
        them under the ADOPTER's ``tools/cc/__pycache__`` -- before ``init`` had
        written the gitignore block, so the uncommitted-work disclosure named
        three ``.pyc`` files as the adopter's own work on every fresh install
        (red on all eight CI cells of the lane's pull request, 2026-09-30), and
        a ``git add -A`` after a declined gitignore write would have committed
        them. Pinned as the tree delta around the one spawn, not as "no
        bytecode anywhere": the delta names any byproduct a future verb strands
        (a cache, a lock, a scratch), and a precompile of ``tools/cc/`` at
        install (``DEF-946``'s shape) is its own step after the gitignore
        append, outside this window -- narrow the window, never delete the pin.
        Both bytecode variables are cleared from the parent first: a shell that
        suppresses bytecode, or diverts it with a cache prefix, would otherwise
        pass this without the spawn doing it; and the filed list is asserted
        whole, so the early returns that spawn nothing cannot pass it either
        (both reviews, 2026-10-01)."""
        from espalier.analyze import fingerprint_repo
        from espalier.cli import (
            _ONBOARDING_ROWS, _deploy_seed_docs, _file_onboarding_rows, deploy_harness,
        )
        from espalier.models import BuildPlan, HarnessConfig

        monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
        monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
        (tmp_path / ".git").mkdir()
        _deploy_seed_docs(tmp_path)
        deploy_harness(tmp_path, BuildPlan(repo_name="x", config=HarnessConfig()),
                       fingerprint_repo(tmp_path))
        before = self._snapshot(tmp_path)
        outcome = _file_onboarding_rows(tmp_path)
        after = self._snapshot(tmp_path)
        assert outcome["filed"] == [r["id"] for r in _ONBOARDING_ROWS], outcome
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        assert changed == ["task-packs/FORWARD_LEDGER.md", "task-packs/LEDGER_PROBES.json"], (
            "the seeding touched more than the ledger and its probes: " + ", ".join(changed)
        )


class TestUpgradeRepinsAFiledOnboardingProbe:
    """DEF-3003: ``_file_onboarding_rows`` files the onboarding rows only into
    an untouched seed ledger, so a probe a later release fixes never reached
    a tree installed before it (an ONB-1 filed before 2026-10-11 kept the
    whole-file test through every ``upgrade``). ``upgrade --execute`` now
    re-pins each live row's stale probe through the deployed verb, the
    store's one writer (``cli._refresh_onboarding_probes``). The three
    outcomes air's ack 6b0797 named, driven: a row still open is re-pinned; a
    row this release's probe reads as satisfied is named for the adopter to
    strike and its stored probe left byte-equal (the verb's repin gate: a
    probe reading satisfied is a strike, never a repin); a struck row is left
    as it is. Earned red: on main every row below failed."""

    @staticmethod
    def _store(root: Path) -> Path:
        roster = root / "task-packs" / "LEDGER_PROBES.json"
        return roster if roster.is_file() else root / "task-packs" / "probes.d" / "ONB-1.json"

    @classmethod
    def _onb1(cls, root: Path) -> dict:
        import json

        data = json.loads(cls._store(root).read_bytes())
        if "probes" in data:
            return next(p for p in data["probes"] if p["id"] == "ONB-1")
        return data

    @classmethod
    def _stale(cls, root: Path) -> tuple[str, str]:
        """Change one character of the stored ONB-1 command, as the row's
        probe does: the shape an earlier release's probe leaves. Returns the
        command init filed -- this release's, compared against, as the row's
        probe compares -- and the stale one."""
        import json

        store = cls._store(root)
        data = json.loads(store.read_bytes())
        entry = next(p for p in data["probes"] if p["id"] == "ONB-1") if "probes" in data else data
        filed = entry["cmd"]
        entry["cmd"] = filed.replace("(not set", "(not set ", 1)
        store.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        return filed, entry["cmd"]

    def test_a_stale_probe_on_a_row_still_open_is_repinned(self, tmp_path):
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        filed, _stale = self._stale(tmp_path)
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == filed
        assert any("re-pinned ONB-1" in line for line in lines), lines

    def test_a_row_the_new_probe_reads_satisfied_is_named_and_left_as_it_was(self, tmp_path):
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        _filed, stale = self._stale(tmp_path)
        goal = tmp_path / "cc" / "GOAL.md"
        text = goal.read_text(encoding="utf-8")
        goal.write_text(text[:text.index("(not set")] + "Ship the parser rewrite.\n", encoding="utf-8")
        before = self._store(tmp_path).read_bytes()
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._store(tmp_path).read_bytes() == before
        assert self._onb1(tmp_path)["cmd"] == stale
        assert any("ONB-1 reads satisfied" in line and "strike it with `" in line
                   and "ledger_row.py strike ONB-1 --text-file" in line for line in lines), lines
        assert not any("re-pinned" in line for line in lines), lines

    def test_a_struck_row_is_left_as_it_is(self, tmp_path):
        import os

        from espalier.cli import _refresh_onboarding_probes, _stored_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        self._stale(tmp_path)
        note = tmp_path / "close.md"
        note.write_text("the goal is written\n", encoding="utf-8")
        verb = tmp_path / "tools" / "cc" / "ledger_row.py"
        struck = subprocess.run(
            [sys.executable, str(verb), "--root", str(tmp_path), "strike", "ONB-1", "--text-file", str(note)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert struck.returncode == 0, struck.stderr
        assert "ONB-1" not in _stored_onboarding_probes(tmp_path)
        lines = _refresh_onboarding_probes(tmp_path)
        assert not any("ONB-1" in line for line in lines), lines

    def test_a_stale_open_value_alone_is_repinned(self, tmp_path):
        import json

        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        store = self._store(tmp_path)
        data = json.loads(store.read_bytes())
        entry = next(p for p in data["probes"] if p["id"] == "ONB-1") if "probes" in data else data
        entry["open_value"] = "False"
        store.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["open_value"] == "True"
        assert any("re-pinned ONB-1" in line for line in lines), lines

    def test_a_probe_kept_as_its_own_file_is_repinned_there(self, tmp_path):
        """A tree whose ledger keeps rows as files (``ledger_fragments``) holds
        the probe under ``task-packs/probes.d/``, which the reader takes when
        the roster has none, as the verb does."""
        import json

        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        filed, _stale = self._stale(tmp_path)
        roster = tmp_path / "task-packs" / "LEDGER_PROBES.json"
        data = json.loads(roster.read_bytes())
        entry = next(p for p in data["probes"] if p["id"] == "ONB-1")
        data["probes"] = [p for p in data["probes"] if p["id"] != "ONB-1"]
        roster.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        frag = tmp_path / "task-packs" / "probes.d" / "ONB-1.json"
        frag.parent.mkdir(exist_ok=True)
        frag.write_bytes((json.dumps(entry, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        lines = _refresh_onboarding_probes(tmp_path)
        assert json.loads(frag.read_bytes())["cmd"] == filed
        assert any("re-pinned ONB-1" in line for line in lines), lines

    @staticmethod
    def _cli(root: Path):
        import os

        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return lambda *a: subprocess.run([sys.executable, "-m", "espalier.cli", *a], capture_output=True,
                                         text=True, encoding="utf-8", errors="replace", timeout=50, env=env)

    def test_a_version_current_tree_reaches_the_repin(self, tmp_path):
        """The row's named user (failure-mode review, driven): every tree it
        names is version-current, since the version has been 0.8.0b2 since
        2026-09-27, and such a tree was told "harness is current; nothing to
        do" before the re-pin could run. The stale probe is drift there now:
        the tree falls through, ``--execute`` re-pins it, and the next run
        reads current again."""
        run = self._cli(tmp_path)
        subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=True)
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        assert run("init", str(tmp_path)).returncode == 0
        filed, _stale = self._stale(tmp_path)
        upgraded = run("upgrade", str(tmp_path), "--execute")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert "re-pinned ONB-1" in upgraded.stdout, upgraded.stdout
        # repaired in place, as the arm's other repairs are: no re-deploy
        assert "re-deployed" not in upgraded.stdout, upgraded.stdout
        assert self._onb1(tmp_path)["cmd"] == filed
        again = run("upgrade", str(tmp_path))
        assert "onboarding row" not in again.stdout, again.stdout

    def test_the_dry_run_names_the_repin_and_writes_nothing(self, tmp_path):
        run = self._cli(tmp_path)
        subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=True)
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        assert run("init", str(tmp_path)).returncode == 0
        _filed, stale = self._stale(tmp_path)
        before = self._store(tmp_path).read_bytes()
        previewed = run("upgrade", str(tmp_path))
        assert previewed.returncode == 0, previewed.stdout + previewed.stderr
        assert "would re-pin ONB-1" in previewed.stdout, previewed.stdout
        assert self._store(tmp_path).read_bytes() == before
        assert self._onb1(tmp_path)["cmd"] == stale

    @staticmethod
    def _stale_entries(root: Path, *ids: str) -> None:
        import json

        roster = root / "task-packs" / "LEDGER_PROBES.json"
        data = json.loads(roster.read_bytes())
        for entry in data["probes"]:
            if entry["id"] in ids:
                entry["cmd"] = entry["cmd"] + " "
        roster.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))

    def test_a_held_ledger_lock_stops_the_run_once(self, tmp_path, monkeypatch):
        """``_file_onboarding_rows``' own rule: every later row would meet the
        same lock, so it is said once, whole, with the verb's remedy."""
        from espalier import cli
        TestLedgerSeed._install(tmp_path)
        self._stale_entries(tmp_path, "ONB-1", "ONB-6")
        held = ("ledger_row: another ledger verb holds task-packs/FORWARD_LEDGER.md.lock (pid 4242); run the "
                "verbs one at a time. If none is running, delete that file")
        calls = []

        def fake(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 2, "", held + "\n")

        monkeypatch.setattr(cli, "run_bounded", fake)
        lines = cli._refresh_onboarding_probes(tmp_path)
        assert len(calls) == 1
        assert [line for line in lines if "could not re-pin" in line] == [
            f"forward ledger: could not re-pin ONB-1 and every row after it ({held}) -- the next "
            "`upgrade --execute` or `init .` tries again"]

    def test_a_repin_the_verb_refuses_is_named_with_its_reason(self, tmp_path, monkeypatch):
        from espalier import cli
        TestLedgerSeed._install(tmp_path)
        self._stale_entries(tmp_path, "ONB-1")
        monkeypatch.setattr(cli, "run_bounded", lambda argv, **k: subprocess.CompletedProcess(
            argv, 2, "", "ledger_row: the subject is unreadable\n"))
        lines = cli._refresh_onboarding_probes(tmp_path)
        assert any("could not re-pin ONB-1 (ledger_row: the subject is unreadable)" in line for line in lines), lines

    def test_a_row_deleted_by_hand_is_left_alone(self, tmp_path, monkeypatch):
        """The adopter deleted ONB-6's member row and kept its probe: the row
        is theirs, so nothing spawns for it and nothing names it."""
        from espalier import cli
        TestLedgerSeed._install(tmp_path)
        self._stale_entries(tmp_path, "ONB-6")
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        rows = tmp_path / "task-packs" / "ledger.d" / "ONB-6.md"
        target = rows if rows.is_file() else ledger
        # the member row only: its index row (a section in the second cell) stays,
        # as a hand edit of the row would leave it
        kept = [line for line in target.read_text(encoding="utf-8").splitlines(keepends=True)
                if not (line.startswith("| `ONB-6` |") and not line.split("|")[2].strip().startswith("§"))]
        assert any(line.startswith("| `ONB-6` |") for line in kept), "the index row should remain"
        target.write_text("".join(kept), encoding="utf-8")
        calls = []
        monkeypatch.setattr(cli, "run_bounded", lambda *a, **k: calls.append(a))
        assert cli._refresh_onboarding_probes(tmp_path) == []
        assert calls == []

    def test_the_adopters_own_repin_is_kept_and_named(self, tmp_path):
        import os

        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        verb = tmp_path / "tools" / "cc" / "ledger_row.py"
        mine = 'python -c "print(True)"'
        own = subprocess.run(
            [sys.executable, str(verb), "--root", str(tmp_path), "repin", "ONB-1", "--probe-cmd", mine,
             "--open-value", "True", "--reason", "our own goal check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert own.returncode == 0, own.stderr
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == mine
        assert any("keeping your own re-pin of ONB-1" in line for line in lines), lines

    def test_a_row_whose_text_was_rewritten_keeps_its_probe(self, tmp_path):
        """A re-pin restamps the row's pins, which would erase the checker's
        stale claim on a row the adopter rewrote: kept, and named."""
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        _filed, stale = self._stale(tmp_path)
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        rows = tmp_path / "task-packs" / "ledger.d" / "ONB-1.md"
        target = rows if rows.is_file() else ledger
        text = target.read_text(encoding="utf-8")
        line = next(x for x in text.splitlines() if x.startswith("| `ONB-1` |"))
        cells = line.split(" | ")
        cells[2] = cells[2] + " Our goal lives in docs/GOAL.md."
        target.write_text(text.replace(line, " | ".join(cells)), encoding="utf-8")
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == stale
        assert any("keeping the probe of ONB-1, whose text you rewrote" in line for line in lines), lines

    def test_the_text_pin_is_the_checkers(self, tmp_path):
        """The engine re-derives the deployed checker's text pin (it imports
        nothing from tools/cc): equal on an installed member row and on a row
        holding an escaped pipe."""
        from espalier.cli import _ledger_text_sha
        TestLedgerSeed._install(tmp_path)
        checker = TestLedgerSeed._cc("check_ledger_probes")
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        rows = tmp_path / "task-packs" / "ledger.d" / "ONB-1.md"
        source = (rows if rows.is_file() else ledger).read_text(encoding="utf-8")
        member = next(x for x in source.splitlines() if x.startswith("| `ONB-1` |"))
        piped = "| `X-1` | a.py | a cell with an escaped \\| pipe | minor |"
        for line in (member, piped):
            assert _ledger_text_sha(line) == checker.text_sha(line), line

    def test_a_satisfied_row_on_a_current_tree_settles_without_a_redeploy(self, tmp_path):
        """Both re-reviews, driven: a row this release's probe reads satisfied
        kept a drift entry non-empty, so every upgrade re-deployed and said
        "re-pinned on --execute" until the row was struck. Repaired in place,
        each run names the strike and re-deploys nothing, and once the
        adopter strikes the row the tree reads current again."""
        import os

        run = self._cli(tmp_path)
        subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=True)
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        assert run("init", str(tmp_path)).returncode == 0
        self._stale_entries(tmp_path, "ONB-1")
        goal = tmp_path / "cc" / "GOAL.md"
        text = goal.read_text(encoding="utf-8")
        goal.write_text(text[:text.index("(not set")] + "Ship the parser rewrite.\n", encoding="utf-8")
        for _ in range(2):
            upgraded = run("upgrade", str(tmp_path), "--execute")
            assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
            assert "ONB-1 reads satisfied" in upgraded.stdout, upgraded.stdout
            assert "re-deployed" not in upgraded.stdout, upgraded.stdout
        note = tmp_path / "close.md"
        note.write_text("the goal is written\n", encoding="utf-8")
        verb = tmp_path / "tools" / "cc" / "ledger_row.py"
        struck = subprocess.run(
            [sys.executable, str(verb), "--root", str(tmp_path), "strike", "ONB-1", "--text-file", str(note)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert struck.returncode == 0, struck.stderr
        again = run("upgrade", str(tmp_path))
        assert "nothing to do" in again.stdout, again.stdout

    def _verb(self, root: Path, *args: str):
        import os

        return subprocess.run(
            [sys.executable, str(root / "tools" / "cc" / "ledger_row.py"), "--root", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_a_severity_regrade_is_not_an_adopters_own_probe(self, tmp_path):
        """The first cut read any re-pin stamp with a reason of the adopter's
        as their own probe, and `repin --severity` writes that stamp: a
        re-graded row opted out of the refresh for good. The verb's stamp now
        lists the fields a repin changed, and only `probe` keeps a row."""
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        filed = self._onb1(tmp_path)["cmd"]
        self._stale_entries(tmp_path, "ONB-1")
        regrade = self._verb(tmp_path, "repin", "ONB-1", "--severity", "major", "--reason", "re-graded")
        assert regrade.returncode == 0, regrade.stderr
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == filed
        assert any("re-pinned ONB-1" in line for line in lines), lines
        assert not any("keeping your own" in line for line in lines), lines

    def test_a_hand_repin_from_an_older_verb_is_refreshed_and_named(self, tmp_path):
        """A stamp from a verb older than the changed-fields list cannot say
        whether it wrote the probe: the row is refreshed once, and the report
        names the date and the command it held, so the adopter can re-pin."""
        import json

        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        filed = self._onb1(tmp_path)["cmd"]
        roster = tmp_path / "task-packs" / "LEDGER_PROBES.json"
        data = json.loads(roster.read_bytes())
        entry = next(e for e in data["probes"] if e["id"] == "ONB-1")
        entry["cmd"] = 'python -c "print(True)"'
        entry["verified_2026_10_01"] = "STILL_OPEN (re-pinned value unchanged on 2026-10-01: our own check)"
        roster.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == filed
        assert any("re-pinned by hand on 2026-10-01" in line and '`python -c "print(True)"`' in line
                   and "open value `" in line
                   and ("put it back with `" in line and "repin ONB-1 --probe-cmd <that command> "
                        "--open-value <that value> --reason <why>`" in line)
                   for line in lines), lines

    def test_an_adopter_reason_that_starts_with_espalier_is_still_theirs(self, tmp_path):
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        mine = 'python -c "print(True)"'
        own = self._verb(tmp_path, "repin", "ONB-1", "--probe-cmd", mine, "--open-value", "True",
                         "--reason", "espalier probe misreads our goal file")
        assert own.returncode == 0, own.stderr
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == mine
        assert any("keeping your own re-pin of ONB-1" in line for line in lines), lines

    @pytest.mark.parametrize("layout", [
        "single file, index row first", "row file", "struck", "anchor reads like a section",
        "co-id, the other struck", "co-id, this one second", "co-id, the first struck",
        "a word before the id", "a lone id cell",
    ])
    def test_the_member_row_finder_is_the_checkers(self, tmp_path, monkeypatch, layout):
        """The engine re-derives the deployed checker's member-row rule
        (``check_ledger_probes._row_line`` over the checker's own view of the
        ledger, its row files placed in it): pinned equal on both ledger
        layouts, an index row before the member row, a struck row, an anchor
        that starts with a section sign, and the id cells the checker reads
        by the grammar's own reader (a co-id cell, strike state at the cell's
        lead, an id cell that does not open with an id, a line of one cell).
        The re-reviews, driven: the first re-derivation read a struck co-id
        as this row struck, and a word before the id as a member row."""
        from espalier.cli import _onboarding_member_line
        checker = TestLedgerSeed._cc("check_ledger_probes")
        member = "| `ONB-1` | cc/GOAL.md | Write the goal. | minor |"
        index = "| `ONB-1` | §C1 | cc/GOAL.md |"
        rows = {
            "single file, index row first": f"{index}\n\n{member}",
            "struck": f"| ~~`ONB-1`~~ | cc/GOAL.md | done | minor |\n{index}",
            "anchor reads like a section": "| `ONB-1` | §3 of our README | Write the goal. | minor |",
            "co-id, the other struck": "| `ONB-1` ~~`ONB-9`~~ | cc/GOAL.md | Write the goal. | minor |",
            "co-id, this one second": "| `ONB-9` `ONB-1` | cc/GOAL.md | Write the goal. | minor |",
            "co-id, the first struck": "| ~~`ONB-9`~~ `ONB-1` | cc/GOAL.md | done | minor |",
            "a word before the id": "| see `ONB-1` | cc/GOAL.md | Write the goal. | minor |",
            "a lone id cell": "| `ONB-1`",
        }
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.parent.mkdir(parents=True)
        if layout == "row file":
            # The view places a row file only into its class's member table.
            ledger.write_bytes((f"# L\n\n### §C1 Onboarding\n\n| ID | Site | Text | Severity |\n|---|---|---|---|\n\n"
                                f"## Appendix B\n\n| ID | Class | Site |\n|---|---|---|\n{index}\n").encode("utf-8"))
            (ledger.parent / "ledger.d").mkdir()
            (ledger.parent / "ledger.d" / "ONB-1.md").write_bytes(
                f"<!-- class: §C1 -->\n{member}\n".encode("utf-8"))
        else:
            ledger.write_bytes(f"# L\n\n{rows[layout]}\n".encode("utf-8"))
        monkeypatch.setattr(checker, "_LEDGER", ledger)
        found = _onboarding_member_line(tmp_path, "ONB-1")
        assert found == checker._row_line("ONB-1", checker._ledger_view())
        assert (found is None) == (layout in {"struck", "co-id, the first struck", "a word before the id"}), found

    def test_init_on_an_installed_tree_refreshes_too(self, tmp_path):
        """``init .`` re-deploys onto an installed tree and never refreshed
        (the failure-mode review, driven): it now runs the same refresh after
        its own filing step."""
        run = self._cli(tmp_path)
        subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=True)
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        assert run("init", str(tmp_path)).returncode == 0
        filed, _stale = self._stale(tmp_path)
        again = run("init", str(tmp_path))
        assert again.returncode == 0, again.stdout + again.stderr
        assert self._onb1(tmp_path)["cmd"] == filed
        assert "Forward ledger: re-pinned ONB-1" in again.stdout, again.stdout

    def test_no_deployed_verb_means_nothing_is_done(self, tmp_path, monkeypatch):
        from espalier import cli
        TestLedgerSeed._install(tmp_path)
        self._stale_entries(tmp_path, "ONB-1")
        (tmp_path / "tools" / "cc" / "ledger_row.py").rename(tmp_path / "ledger_row.py.kept")
        calls = []
        monkeypatch.setattr(cli, "run_bounded", lambda *a, **k: calls.append(a))
        assert cli._refresh_onboarding_probes(tmp_path) == []
        assert cli._onboarding_repin_preview(tmp_path) == []
        assert calls == []

    @classmethod
    def _restamp(cls, root: Path, cmd: str, **stamps: str) -> None:
        """Set the stored ONB-1 command and add re-pin stamps, as a hand
        re-pin (or the engine's) leaves them."""
        import json

        store = cls._store(root)
        data = json.loads(store.read_bytes())
        entry = next(p for p in data["probes"] if p["id"] == "ONB-1") if "probes" in data else data
        entry["cmd"] = cmd
        entry.update(stamps)
        store.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))

    def test_an_own_probe_outlives_a_later_regrade(self, tmp_path):
        """The failure-mode re-review, driven: read by the newest hand stamp
        alone, a re-grade after an adopter's own probe let the refresh
        overwrite that probe. A re-grade wrote no probe and is passed over."""
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        mine = 'python -c "print(True)"'
        self._restamp(
            tmp_path, mine,
            verified_2026_10_15="STILL_OPEN (re-pinned value unchanged on 2026-10-15: ours) [changed: probe]",
            verified_2026_10_16="STILL_OPEN (re-pinned value unchanged on 2026-10-16: re-graded) [changed: severity]",
        )
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == mine
        assert any("keeping your own re-pin of ONB-1" in line for line in lines), lines

    def test_an_own_probe_and_a_regrade_on_one_day_keep_the_probe(self, tmp_path):
        """Through the deployed verb: a second repin on one day writes over
        that day's stamp, and the verb carries the first one's list."""
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        mine = 'python -c "print(True)"'
        own = self._verb(tmp_path, "repin", "ONB-1", "--probe-cmd", mine, "--open-value", "True", "--reason", "ours")
        assert own.returncode == 0, own.stderr
        regrade = self._verb(tmp_path, "repin", "ONB-1", "--severity", "major", "--reason", "re-graded")
        assert regrade.returncode == 0, regrade.stderr
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == mine
        assert any("keeping your own re-pin of ONB-1" in line for line in lines), lines

    def test_the_keep_line_names_the_way_back_and_it_works(self, tmp_path):
        """The failure-mode re-review: "own" was a one-way door, so a later
        release's probe never reached an adopter who had once re-pinned by
        hand. The keep line prints the re-pin that hands the row back; run as
        printed, the next refresh takes this release's probe."""
        import shlex

        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        filed = self._onb1(tmp_path)["cmd"]
        mine = 'python -c "print(True)"'
        own = self._verb(tmp_path, "repin", "ONB-1", "--probe-cmd", mine, "--open-value", "True", "--reason", "ours")
        assert own.returncode == 0, own.stderr
        keep = next(line for line in _refresh_onboarding_probes(tmp_path) if "keeping your own" in line)
        printed = keep[keep.index("`", keep.index("to take it")) + 1:keep.rindex("`")]
        argv = shlex.split(printed.replace("<id>", "ONB-1"))
        back = self._verb(tmp_path, *argv[argv.index("repin"):])
        assert back.returncode == 0, back.stderr
        lines = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == filed
        assert any("re-pinned ONB-1" in line for line in lines), lines

    def test_a_hand_repin_the_engine_already_refreshed_is_not_named_again(self, tmp_path):
        """Both re-reviews, driven: the engine's refresh of a hand re-pin from
        an older verb left the hand stamp in the entry and did not count its
        own, so every later release named the row again, holding the engine's
        previous probe. The engine's own re-pin speaks for every stamp before
        it."""
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        filed = self._onb1(tmp_path)["cmd"]
        self._restamp(tmp_path, 'python -c "print(True)"',
                      verified_2026_10_01="STILL_OPEN (re-pinned value unchanged on 2026-10-01: our own check)")
        first = _refresh_onboarding_probes(tmp_path)
        assert any("re-pinned by hand on 2026-10-01" in line for line in first), first
        self._stale(tmp_path)   # the next release's probe differs again
        again = _refresh_onboarding_probes(tmp_path)
        assert self._onb1(tmp_path)["cmd"] == filed
        assert any("re-pinned ONB-1" in line for line in again), again
        assert not any("by hand" in line for line in again), again

    @pytest.mark.parametrize("listed", [False, True])
    def test_a_hand_repin_after_the_engines_own_still_speaks_for_the_row(self, tmp_path, listed):
        from espalier.cli import _refresh_onboarding_probes
        TestLedgerSeed._install(tmp_path)
        mine = 'python -c "print(True)"'
        self._restamp(
            tmp_path, mine,
            verified_2026_10_02=("STILL_OPEN (re-pinned value unchanged on 2026-10-02: espalier 0.8.0b1 reads "
                                 "this onboarding row with a new probe) [changed: probe]"),
            verified_2026_10_05=("STILL_OPEN (re-pinned value unchanged on 2026-10-05: our own check)"
                                 + (" [changed: probe]" if listed else "")),
        )
        lines = _refresh_onboarding_probes(tmp_path)
        if listed:
            assert self._onb1(tmp_path)["cmd"] == mine
            assert any("keeping your own re-pin of ONB-1" in line for line in lines), lines
        else:
            assert any("re-pinned by hand on 2026-10-05" in line for line in lines), lines

    def test_a_claim_that_refuses_the_write_is_named_in_the_preview(self, tmp_path, monkeypatch):
        """Both re-reviews: the verb's dry run reads a claim that refuses the
        write as a note and goes on, so the preview said "would re-pin" for a
        row --execute then refused. The deployed verb is driven here, in
        process, with another machine's claim on the row."""
        import contextlib
        import io
        import types

        from espalier import cli
        TestLedgerSeed._install(tmp_path)
        self._stale(tmp_path)
        lr, mail = TestLedgerSeed._cc("ledger_row"), TestLedgerSeed._cc("mail")
        theirs = mail.new_message("win", "claim", "", lane="lane/onb", ids=["ONB-1"])
        lr._MAIL = types.SimpleNamespace(
            machine_setting=lambda root, **kw: ("mac", "named"),
            read_mail=lambda root, **kw: ({"win": [theirs]}, {}),
            live_claims=mail.live_claims, overlapping_claims=mail.overlapping_claims,
        )

        def verb(argv, **_kw):
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                rc = lr.main(argv[2:])
            return types.SimpleNamespace(returncode=rc, stdout="", stderr=err.getvalue())

        monkeypatch.setattr(cli, "run_bounded", verb)
        before = self._store(tmp_path).read_bytes()
        lines = cli._onboarding_repin_preview(tmp_path)
        assert self._store(tmp_path).read_bytes() == before
        assert not any("would re-pin ONB-1" in line for line in lines), lines
        assert any("could not check ONB-1 (refused on --execute: win claims id ONB-1" in line
                   for line in lines), lines

    def test_a_current_probe_spawns_nothing(self, tmp_path, monkeypatch):
        from espalier import cli
        TestLedgerSeed._install(tmp_path)
        calls = []
        monkeypatch.setattr(cli, "run_bounded", lambda *a, **k: calls.append(a))
        assert cli._refresh_onboarding_probes(tmp_path) == []
        assert calls == []

    def test_upgrade_execute_repins_it_end_to_end(self, tmp_path):
        """The row's own sequence, through the real CLI: init, one character
        of the stored ONB-1 probe changed, the deployed stamp set back so the
        re-deploy path runs, ``upgrade --execute``."""
        import os

        import espalier

        subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True, check=True)
        (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        run = lambda *a: subprocess.run([sys.executable, "-m", "espalier.cli", *a], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=50, env=env)
        assert run("init", str(tmp_path)).returncode == 0
        filed, _stale = self._stale(tmp_path)
        manifest = tmp_path / "cc" / "PACK_MANIFEST.txt"
        manifest.write_bytes(manifest.read_bytes().replace(espalier.__version__.encode(), b"0.0.1"))
        previewed = run("upgrade", str(tmp_path))
        assert "would re-pin ONB-1" in previewed.stdout, previewed.stdout
        assert self._onb1(tmp_path)["cmd"] != filed
        upgraded = run("upgrade", str(tmp_path), "--execute")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert self._onb1(tmp_path)["cmd"] == filed
        assert "re-pinned ONB-1" in upgraded.stdout, upgraded.stdout


class TestOnboardingProbesDoNotWalk:
    """The onboarding probes run at ``init``, often before a first commit, and
    a tree-walking probe is UNRESOLVED on a repository with nothing tracked
    (measured 2026-09-30) -- so the seed would refuse its own rows. Keyed on
    the checker's own marker list, not a copy of it."""

    def test_no_onboarding_probe_carries_a_tree_walk_marker(self):
        import importlib.util

        from espalier.cli import _ONBOARDING_ROWS

        spec = importlib.util.spec_from_file_location(
            "_onb_walk_checker", REPO_ROOT / "tools" / "cc" / "check_ledger_probes.py")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        walking = [r["id"] for r in _ONBOARDING_ROWS
                   if "code" in r and checker._walks_the_tree(r["code"])]
        assert walking == []

    def test_every_probe_survives_the_checkers_argv_split_and_compiles(self):
        """The command is stored as one string and split with ``shlex`` by the
        checker; a ``"`` in a row's code would split it wrong, reading
        UNRESOLVED at best (code review, 2026-09-30). ``shlex`` keeps ``$``, a
        backtick, ``!`` and a newline, but a person re-verifying a strike pastes
        the command into a shell, which expands them (failure-mode review,
        2026-10-11), so none may appear."""
        import shlex

        from espalier.cli import _ONBOARDING_ROWS, _PROBE_PY

        for row in _ONBOARDING_ROWS:
            if "code" not in row:
                continue
            argv = shlex.split(f'{_PROBE_PY} -c "{row["code"]}"')
            assert argv[:2] == [_PROBE_PY, "-c"] and argv[2] == row["code"], row["id"]
            assert not set('"$`!\n') & set(row["code"]), row["id"]
            compile(argv[2], row["id"], "exec")

    @pytest.mark.parametrize("rid,key", [("ONB-1", "goal_snapshot = false"),
                                         ("ONB-6", 'plan_exempt_prefixes = ["src/"]')])
    def test_a_key_under_a_table_leaves_its_row_open(self, tmp_path, rid, key):
        """TOML files every key below a ``[table]`` header INTO that table, so a
        key an adopter appends after ``[extra_actions]`` is not the engine's
        top-level key -- and the row must stay open. The same key above the
        table closes it (failure-mode review, 2026-09-30). No ``cc/GOAL.md``:
        while that file is there ONB-1 reads its goal, whatever the key
        (``DEF-1033``), so the key is only the verdict once it is gone."""
        from espalier.cli import _ONBOARDING_ROWS

        code = next(r["code"] for r in _ONBOARDING_ROWS if r["id"] == rid)

        def prints(toml: str) -> str:
            (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
            return subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                                  text=True, encoding="utf-8", timeout=45).stdout.strip()

        assert prints(f'[extra_actions]\ntest = ["make"]\n{key}\n') == "True"
        assert prints(f'{key}\n\n[extra_actions]\ntest = ["make"]\n') == "False"

    @staticmethod
    def _goal(*, written: bool) -> str:
        """The seeded skeleton, or the skeleton with its ``## Goal`` filled and
        the next section left as seeded, which only ``/handoff`` fills: the
        state ``DEF-1032`` names."""
        from espalier.cli import _build_goal_md

        skeleton = _build_goal_md()
        if not written:
            return skeleton
        head, rest = skeleton.split("## Goal\n", 1)
        tail = rest[rest.index("## Where we are"):]
        assert "(not set" in tail, "the skeleton's second placeholder moved; re-derive this state"
        return head + "## Goal\n\nShip the demo CLI with tests.\n\n" + tail

    @staticmethod
    def _stubs(root: Path, conventions: bytes | None = None, sharp_edges: bytes | None = None) -> None:
        """The two stubs as ``init`` seeds them (stamped, untouched), each
        replaced by the given bytes where one is passed."""
        from espalier.cli import _deploy_seed_docs

        (root / ".git").mkdir(exist_ok=True)
        _deploy_seed_docs(root)
        for name, data in (("CONVENTIONS.md", conventions), ("SHARP_EDGES.md", sharp_edges)):
            if data is not None:
                (root / "docs" / name).write_bytes(data)

    #: (row, tree state, what the row's probe prints: ``True`` is open). The
    #: verdicts are the spec; ``_harness_reads`` gives the same verdict from the
    #: harness's own readers, so a reader that changes reds here beside the probe.
    _TRUTH_TABLE = [
        ("ONB-1", "skeleton", "True"),
        ("ONB-1", "goal written", "False"),
        ("ONB-1", "goal written, CRLF", "False"),
        ("ONB-1", "goal written, CR", "False"),
        ("ONB-1", "goal written, key set", "False"),
        ("ONB-1", "key set, skeleton kept", "True"),
        ("ONB-1", "key set, file deleted", "False"),
        ("ONB-1", "no key, file deleted", "True"),
        ("ONB-1", "empty file", "True"),
        ("ONB-1", "empty file, key set", "False"),
        ("ONB-1", "blank file", "True"),
        ("ONB-1", "only a byte-order mark", "True"),
        ("ONB-1", "no heading, placeholder", "True"),
        ("ONB-1", "no heading, goal", "False"),
        ("ONB-1", "empty Goal section", "True"),
        ("ONB-1", "Goal heading on the last line", "True"),
        ("ONB-1", "goal under a Goals heading", "False"),
        ("ONB-1", "goal under a Goal heading with a trailing space", "False"),
        ("ONB-1", "goal under a sub-heading of Goal", "False"),
        ("ONB-1", "goal mentions not settled", "False"),
        ("ONB-1", "goal with a real replacement character", "False"),
        ("ONB-1", "goal first, UTF-8 BOM", "False"),
        ("ONB-1", "goal written, UTF-16 BOM", "False"),
        ("ONB-1", "skeleton, UTF-16 BOM", "True"),
        ("ONB-1", "goal written, UTF-32 BOM", "False"),
        ("ONB-1", "goal written, UTF-16 without a BOM", "True"),
        ("ONB-1", "goal written, UTF-16 cut at an odd byte", "True"),
        ("ONB-1", "goal written, cp1252", "True"),
        ("ONB-1", "NUL outside the Goal section", "True"),
        ("ONB-1", "key under a table, file deleted", "True"),
        ("ONB-1", "key set in a UTF-16 config, file deleted", "True"),
        ("ONB-1", "key set in a cp1252 config, file deleted", "True"),
        ("ONB-1", "key set under a BOM, file deleted", "True"),
        ("ONB-1", "key set in a malformed config, file deleted", "True"),
        ("ONB-6", "key commented", "True"),
        ("ONB-6", "key set", "False"),
        ("ONB-6", "key set, CRLF config", "False"),
        ("ONB-6", "key set to a string", "True"),
        ("ONB-6", "key set under a table", "True"),
        ("ONB-6", "key set in a UTF-16 config", "True"),
        ("ONB-6", "key set in a cp1252 config", "True"),
        ("ONB-6", "key set under a BOM", "True"),
        ("ONB-6", "key set in a malformed config", "True"),
        ("ONB-7", "both stubs untouched", "True"),
        ("ONB-7", "untouched stub resaved with a BOM and CRLF", "True"),
        ("ONB-7", "one stub deleted, the other untouched", "True"),
        ("ONB-7", "both stubs edited", "False"),
        ("ONB-7", "cp1252 stub, the other edited", "False"),
        ("ONB-7", "UTF-16 stub, the other edited", "False"),
    ]

    def _build(self, root: Path, state: str) -> None:
        goal, toml = root / "cc" / "GOAL.md", root / "espalier.toml"
        goal.parent.mkdir()
        written, skeleton = self._goal(written=True), self._goal(written=False)
        e_acute = chr(0xE9)
        cafe = f"# Conventions\n\nCaf{e_acute} style.\n"
        edited = b"# Sharp edges\n\nNone yet.\n"
        where = "## Where we are / next gate\n\n(not set -- /handoff fills this in)\n"
        # `\S` is not a TOML escape: tomllib refuses the file, so the harness
        # reads none of its keys (the Windows path an adopter types for ONB-3).
        malformed = '\n[extra_actions]\ntest = ".venv\\Scripts\\pytest"\n'

        def put(path: Path, data: str | bytes, encoding: str = "utf-8") -> None:
            path.write_bytes(data if isinstance(data, bytes) else data.encode(encoding))

        def stub_resaved() -> None:
            self._stubs(root, sharp_edges=edited)
            stub = root / "docs" / "CONVENTIONS.md"
            put(stub, b"\xef\xbb\xbf" + stub.read_bytes().replace(b"\n", b"\r\n"))

        def stub_deleted() -> None:
            self._stubs(root)
            (root / "docs" / "SHARP_EDGES.md").unlink()

        builders: dict[str, Callable[[], object]] = {
            "skeleton": lambda: put(goal, skeleton),
            "goal written": lambda: put(goal, written),
            "goal written, CRLF": lambda: put(goal, written.replace("\n", "\r\n")),
            "goal written, CR": lambda: put(goal, written.replace("\n", "\r")),
            "goal written, key set": lambda: (put(goal, written), put(toml, "goal_snapshot = false\n")),
            "key set, skeleton kept": lambda: (put(goal, skeleton), put(toml, "goal_snapshot = false\n")),
            "key set, file deleted": lambda: put(toml, "goal_snapshot = false\n"),
            "no key, file deleted": lambda: None,
            "empty file": lambda: put(goal, b""),
            "empty file, key set": lambda: (put(goal, b""), put(toml, "goal_snapshot = false\n")),
            "blank file": lambda: put(goal, " \n\t\n"),
            "only a byte-order mark": lambda: put(goal, b"\xef\xbb\xbf"),
            "no heading, placeholder": lambda: put(goal, "(not set -- x)\n"),
            "no heading, goal": lambda: put(goal, "Ship the demo CLI.\n"),
            "empty Goal section": lambda: put(goal, "## Goal\n\n" + where),
            "Goal heading on the last line": lambda: put(goal, where + "\n## Goal\n"),
            "goal under a Goals heading": lambda: put(goal, "## Goals\n\nShip it.\n\n" + where),
            "goal under a Goal heading with a trailing space": lambda: put(
                goal, "## Goal \n\nShip it.\n\n" + where),
            "goal under a sub-heading of Goal": lambda: put(goal, "## Goal\n\n### Why\n\nShip it.\n\n" + where),
            "goal mentions not settled": lambda: put(
                goal, "## Goal\n\nShip v1 (not settled: Windows).\n\n" + where),
            "goal with a real replacement character": lambda: put(
                goal, f"## Goal\n\nShip the {chr(0xFFFD)} demo.\n\n" + where),
            "goal first, UTF-8 BOM": lambda: put(goal, "## Goal\n\nShip it.\n\n" + where, "utf-8-sig"),
            "goal written, UTF-16 BOM": lambda: put(goal, written, "utf-16"),
            "skeleton, UTF-16 BOM": lambda: put(goal, skeleton, "utf-16"),
            "goal written, UTF-32 BOM": lambda: put(goal, written, "utf-32"),
            "goal written, UTF-16 without a BOM": lambda: put(goal, written, "utf-16-le"),
            "goal written, UTF-16 cut at an odd byte": lambda: put(goal, written.encode("utf-16") + b"A"),
            "goal written, cp1252": lambda: put(
                goal, written.replace("Ship the", f"Caf{e_acute}: ship the"), "cp1252"),
            "NUL outside the Goal section": lambda: put(goal, written + chr(0)),
            "key under a table, file deleted": lambda: put(
                toml, '[extra_actions]\ntest = ["make"]\ngoal_snapshot = false\n'),
            "key set in a UTF-16 config, file deleted": lambda: put(toml, "goal_snapshot = false\n", "utf-16"),
            "key set in a cp1252 config, file deleted": lambda: put(
                toml, f"# caf{e_acute}\ngoal_snapshot = false\n", "cp1252"),
            "key set under a BOM, file deleted": lambda: put(
                toml, "# mine\ngoal_snapshot = false\n", "utf-8-sig"),
            "key set in a malformed config, file deleted": lambda: put(
                toml, "goal_snapshot = false\n" + malformed),
            "key commented": lambda: put(toml, '# plan_exempt_prefixes = ["src/"]\n'),
            "key set": lambda: put(toml, "plan_exempt_prefixes = []\n"),
            "key set, CRLF config": lambda: put(
                toml, 'plan_exempt_prefixes = ["src/"]\r\n\r\n[extra_actions]\r\ntest = ["make"]\r\n'),
            "key set to a string": lambda: put(toml, 'plan_exempt_prefixes = "src/"\n'),
            "key set under a table": lambda: put(
                toml, '[extra_actions]\ntest = ["make"]\nplan_exempt_prefixes = []\n'),
            "key set in a UTF-16 config": lambda: put(toml, "plan_exempt_prefixes = []\n", "utf-16"),
            "key set in a cp1252 config": lambda: put(
                toml, f"# caf{e_acute}\nplan_exempt_prefixes = []\n", "cp1252"),
            "key set under a BOM": lambda: put(toml, "# mine\nplan_exempt_prefixes = []\n", "utf-8-sig"),
            "key set in a malformed config": lambda: put(toml, "plan_exempt_prefixes = []\n" + malformed),
            "both stubs untouched": lambda: self._stubs(root),
            "untouched stub resaved with a BOM and CRLF": stub_resaved,
            "one stub deleted, the other untouched": stub_deleted,
            "both stubs edited": lambda: self._stubs(root, conventions=b"mine\n", sharp_edges=b"mine\n"),
            "cp1252 stub, the other edited": lambda: self._stubs(
                root, conventions=cafe.encode("cp1252"), sharp_edges=edited),
            "UTF-16 stub, the other edited": lambda: self._stubs(
                root, conventions=cafe.encode("utf-16"), sharp_edges=edited),
        }
        builders[state]()

    @staticmethod
    def _harness_reads(rid: str, root: Path, *, no_parser: bool = False) -> str:
        """The row's verdict as the harness's own readers give it: the plan
        gate's key reader for ONB-6 (its regex arm with ``no_parser``); the
        engine's config loader and the goal's decoder for ONB-1, with the row's
        section rule; doctor's untouched-seed check for ONB-7, an undecodable
        stub edited as the redeploy decision keeps it."""
        import importlib.util
        import re
        import warnings

        from espalier.config import load_config
        from espalier.managed_markers import seed_is_untouched

        def load(rel: str):
            # By path under a private name: these import only the standard
            # library at their top, and the readers called here stay there.
            spec = importlib.util.spec_from_file_location(
                "_onb_" + Path(rel).stem.lstrip("_"), REPO_ROOT / "tools" / "cc" / rel)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        if rid == "ONB-6":
            _hook_utils = load("hooks/_hook_utils.py")
            kwargs = {"parser": None} if no_parser else {}
            return str(not isinstance(
                _hook_utils.read_toml_string_list(root, "plan_exempt_prefixes", **kwargs), list))
        if rid == "ONB-7":
            def untouched(path: Path) -> bool:
                try:
                    return path.is_file() and seed_is_untouched(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    return False
            return str(any(untouched(root / "docs" / name) for name in ("CONVENTIONS.md", "SHARP_EDGES.md")))
        json_safe = load("_json_safe.py")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            off = load_config(root).goal_snapshot is False
        goal = root / "cc" / "GOAL.md"
        text, problem = json_safe.decode_text_or_problem(goal.read_bytes()) if goal.is_file() else ("", "")
        if not goal.is_file() or (not problem and not text.strip()):
            return str(not off)
        if problem:
            return "True"
        lines = text.splitlines()
        head = next((i for i, line in enumerate(lines) if re.match(r"##[ \t]+goals?\b", line, re.I)), None)
        body = lines if head is None else lines[head + 1:]
        if head is not None:
            body = body[:next((i for i, line in enumerate(body) if re.match(r"##[ \t]", line)), len(body))]
        joined = "\n".join(body)
        return str(not joined.strip() or re.search(r"\(not set\b", joined) is not None)

    @staticmethod
    def _probe(rid: str, root: Path, prelude: str = "") -> tuple[int, str, str]:
        from espalier.cli import _ONBOARDING_ROWS

        code = next(r["code"] for r in _ONBOARDING_ROWS if r["id"] == rid)
        run = subprocess.run([sys.executable, "-c", prelude + code], cwd=root, capture_output=True,
                             text=True, encoding="utf-8", timeout=45)
        return run.returncode, run.stdout.strip(), run.stderr

    @pytest.mark.parametrize("rid,state,prints", _TRUTH_TABLE, ids=[f"{r}: {s}" for r, s, _ in _TRUTH_TABLE])
    def test_each_probe_reads_its_file_the_way_the_harness_reads_it(self, tmp_path, rid, state, prints):
        """``DEF-1032``, ``DEF-1033``, ``DEF-1034`` (TP-474 5-A): ONB-1 reads the
        ``## Goal`` section of a kept, non-blank goal file (the whole file where
        it has no such heading) whatever the opt-out key says, and the key only
        once the file is gone or blank; every file reads as the harness reads it."""
        self._build(tmp_path, state)
        rc, out, err = self._probe(rid, tmp_path)
        assert (rc, out) == (0, prints), err

    @pytest.mark.parametrize("rid,state,prints", _TRUTH_TABLE, ids=[f"{r}: {s}" for r, s, _ in _TRUTH_TABLE])
    def test_each_verdict_is_the_one_the_harness_readers_give(self, tmp_path, rid, state, prints):
        """The spec above, held against the readers the probes mirror: a change
        to the config loader, the plan gate's key reader, the goal's decoder or
        the untouched-seed check reds here, and the probe must follow it
        (failure-mode review, 2026-10-11)."""
        self._build(tmp_path, state)
        assert self._harness_reads(rid, tmp_path) == prints

    #: Hides both TOML parsers from the probe, as on a Python 3.10 host
    #: without ``tomli``: ``importlib.util.find_spec`` returns None for a name
    #: ``sys.modules`` maps to None.
    _NO_PARSER = "import sys;sys.modules['tomllib']=None;sys.modules['tomli']=None;"

    @pytest.mark.parametrize("state", [s for r, s, _ in _TRUTH_TABLE if r == "ONB-6"])
    def test_without_a_parser_onb6_reads_as_the_hooks_regex_arm_does(self, tmp_path, state):
        self._build(tmp_path, state)
        rc, out, err = self._probe("ONB-6", tmp_path, self._NO_PARSER)
        assert (rc, out) == (0, self._harness_reads("ONB-6", tmp_path, no_parser=True)), err

    @pytest.mark.parametrize("toml,prints", [
        ("goal_snapshot = false\n", "False"),
        ('[extra_actions]\ntest = ["make"]\ngoal_snapshot = false\n', "True"),
        ("# goal_snapshot = false\n", "True"),
    ])
    def test_without_a_parser_onb1_reads_the_key_above_the_first_table(self, tmp_path, toml, prints):
        (tmp_path / "espalier.toml").write_bytes(toml.encode("utf-8"))
        rc, out, err = self._probe("ONB-1", tmp_path, self._NO_PARSER)
        assert (rc, out) == (0, prints), err

    def test_the_truth_table_holds_every_coded_row_open_and_closed(self):
        """A row that gains a probe joins the table with an open and a closed
        state, or its closed reading -- the one a strike rests on -- is pinned
        by nothing (failure-mode review, 2026-10-11)."""
        from espalier.cli import _ONBOARDING_ROWS

        coded = {r["id"] for r in _ONBOARDING_ROWS if "code" in r}
        assert {rid for rid, _, _ in self._TRUTH_TABLE} == coded
        for rid in sorted(coded):
            assert {p for r, _, p in self._TRUTH_TABLE if r == rid} == {"True", "False"}, rid

    def test_the_upgrade_preview_names_the_filing_only_where_an_install_would_file(self, tmp_path):
        from espalier.cli import _deploy_seed_docs, _onboarding_would_file

        assert _onboarding_would_file(tmp_path)          # absent: the seed would be created
        (tmp_path / ".git").mkdir()
        _deploy_seed_docs(tmp_path)
        assert _onboarding_would_file(tmp_path)          # the untouched seed
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.write_text(ledger.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8")
        assert not _onboarding_would_file(tmp_path)      # edited: never refiled

    @pytest.mark.contract
    def test_every_row_has_a_probe_or_a_reason_and_a_seeded_section(self):
        import re

        from espalier.cli import _ONBOARDING_ROWS

        seed = (REPO_ROOT / "espalier" / "assets" / "seed" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")  # ledger-read: the adopter's seed, one file by design
        for row in _ONBOARDING_ROWS:
            assert ("code" in row) != ("why_not" in row), row["id"]
            assert re.fullmatch(r"[A-Z]{2,5}-\d+", row["id"]), row["id"]
            assert f"### §{row['section']} " in seed, row["id"]
            assert "|" not in row["text"] and row["text"].isascii(), row["id"]


class TestWorkflowBodyDeploy:
    """A ``.claude/workflows/*.js`` body goes through the same four-state classifier
    as the ``.md`` bodies, with the ``//`` marker on line 1 ahead of ``export const
    meta`` (the module's first statement must stay first)."""

    BODY = "export const meta = {\n  name: 'demo',\n  description: 'd',\n}\nexport default async function () {}\n"

    def test_created_with_the_js_marker_on_line_one(self, tmp_path):
        from espalier.cli import _deploy_asset_md
        from espalier.managed_markers import MARKER_JS_COMMENT, file_carries_marker

        src = tmp_path / "src" / "_demo.js"
        src.parent.mkdir()
        src.write_text(self.BODY, encoding="utf-8")
        dest = tmp_path / ".claude" / "workflows" / "_demo.js"
        assert _deploy_asset_md(src, dest) == "created"
        lines = dest.read_text(encoding="utf-8").split("\n")
        assert lines[0] == MARKER_JS_COMMENT, lines[0]
        assert lines[1].startswith("export const meta"), lines[1]
        assert file_carries_marker(dest), "cleanup would refuse to delete an unmarked workflow"

    def test_a_rerun_is_no_drift_and_a_hand_edit_is_preserved(self, tmp_path):
        from espalier.cli import _deploy_asset_md
        from espalier.managed_markers import MARKER_JS_COMMENT

        src = tmp_path / "src" / "_demo.js"
        src.parent.mkdir()
        src.write_text(self.BODY, encoding="utf-8")
        dest = tmp_path / ".claude" / "workflows" / "_demo.js"
        _deploy_asset_md(src, dest)
        assert _deploy_asset_md(src, dest) == "skipped_no_drift"
        text = dest.read_text(encoding="utf-8")
        dest.write_text(text.replace("'d'", "'drifted'"), encoding="utf-8")
        assert _deploy_asset_md(src, dest) == "updated_managed"
        dest.write_text(text.replace(MARKER_JS_COMMENT + "\n", ""), encoding="utf-8")
        assert _deploy_asset_md(src, dest) == "skipped_user_file"


class TestWindowsShimDeploy:
    """DEF-729: the statusline shim is the one deployed non-.py file. It goes
    through the same five-state classifier as the scripts, with the batch
    marker on line 2 (a ``#`` line is a command to cmd.exe, and a line before
    ``@echo off`` is echoed to stdout, the statusline's channel)."""

    @staticmethod
    def _source_and_dest(tmp_path: Path):
        from espalier.cli import _deploy_source_path
        from espalier.managed_paths import STATUSLINE_SHIM

        return _deploy_source_path(STATUSLINE_SHIM), tmp_path / STATUSLINE_SHIM

    def test_created_with_the_batch_marker_on_line_two(self, tmp_path):
        from espalier.cli import _deploy_managed_py
        from espalier.managed_markers import MARKER_BATCH_COMMENT, file_carries_marker

        source, dest = self._source_and_dest(tmp_path)
        assert _deploy_managed_py(source, dest) == "created"
        lines = dest.read_text(encoding="utf-8").split("\n")
        assert lines[0].strip().lower() == "@echo off", lines[0]
        assert lines[1] == MARKER_BATCH_COMMENT, lines[1]
        assert file_carries_marker(dest), "cleanup would refuse to delete an unmarked shim"
        assert "espalier: statusline did not run" in dest.read_text(encoding="utf-8")

    def test_a_rerun_is_no_drift_and_a_hand_edit_is_preserved(self, tmp_path):
        from espalier.cli import _deploy_managed_py

        source, dest = self._source_and_dest(tmp_path)
        _deploy_managed_py(source, dest)
        assert _deploy_managed_py(source, dest) == "skipped_no_drift"
        # A managed copy that drifted regenerates; one whose marker was
        # removed is the adopter's now.
        text = dest.read_text(encoding="utf-8")
        dest.write_text(text.replace("setlocal", "setlocal\nrem mine"), encoding="utf-8")
        assert _deploy_managed_py(source, dest) == "updated_managed"
        dest.write_text(text.replace(":: espalier:managed\n", ""), encoding="utf-8")
        assert _deploy_managed_py(source, dest) == "skipped_user_file"

    def test_a_retired_shim_is_named_as_an_orphan_like_a_retired_script(self, tmp_path):
        """The retired-file scan is the only thing that tells an adopter a
        deployed file is no longer shipped; a suffix filter that still read
        ``*.py`` could never name the shim once it is retired (or the design
        falsified on the walk)."""
        from espalier.cli import _scan_managed_orphans
        from espalier.managed_markers import MARKER_BATCH_COMMENT, MARKER_HASH_COMMENT

        tools = tmp_path / "tools" / "cc"
        (tools / "hooks").mkdir(parents=True)
        (tools / "gone.cmd").write_text(f"@echo off\n{MARKER_BATCH_COMMENT}\n", encoding="utf-8")
        (tools / "gone.py").write_text(f"{MARKER_HASH_COMMENT}\n", encoding="utf-8")
        (tools / "mine.cmd").write_text("@echo off\nrem theirs\n", encoding="utf-8")
        (tools / "notes.md").write_text("# espalier:managed\n", encoding="utf-8")
        orphans = _scan_managed_orphans(tmp_path)
        assert "tools/cc/gone.cmd" in orphans and "tools/cc/gone.py" in orphans, orphans
        assert "tools/cc/mine.cmd" not in orphans, "an unmarked file is the adopter's"
        assert "tools/cc/notes.md" not in orphans, "only the deploy-source suffixes"

    def test_a_crlf_working_copy_reads_as_no_drift(self, tmp_path):
        """The compare is text after universal newlines, so a Windows checkout
        under core.autocrlf (the shim's own host) is not rewritten every init
        (the DEF-725 shape, one file over)."""
        from espalier.cli import _deploy_managed_py

        source, dest = self._source_and_dest(tmp_path)
        _deploy_managed_py(source, dest)
        dest.write_bytes(dest.read_bytes().replace(b"\n", b"\r\n"))
        assert _deploy_managed_py(source, dest) == "skipped_no_drift"


# ── Lane 6 / DEF-806: every writer of the saved plan re-renders the docs that read it ──
#
# reports/harness_config.json is rewritten by three commands through one
# seam, ``cli._refresh_fingerprint_derivatives``, and two required cc/ docs
# render its ``stable_actions``. Driven 2026-09-15 on a throwaway: init a
# README-only tree, add one .py (the plan gains ``scan``), run each writer --
# both docs kept the old plan's actions and the next ``upgrade`` named them
# as drift on a change the tool itself made. A fusion of a non-Python host
# hits the same seam through install-ci (walk 3, W3-P38): the post-overlay
# plan gains ``scan`` from the engine's own Python. The three cases below red
# on the prior head; the two contracts after them derive the writer set and
# the reader set from the source, so a fourth writer or a third reader cannot
# be enrolled by hand and missed.

_PLAN_GAINS = "espalier scan ."  # the action a README-only tree gains with one .py


def _run_fingerprint(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_fingerprint

    return cmd_fingerprint(argparse.Namespace(repo=str(tree), config=None))


def _run_install_ci(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_install_ci

    return cmd_install_ci(argparse.Namespace(repo=str(tree), config=None))


def _run_upgrade_execute(tree: Path) -> int:
    # Real deploy drift first, or ``upgrade`` says "nothing to do" and never
    # reaches the branch that rewrites the plan.
    (tree / ".claude" / "commands" / "status.md").unlink()
    return _upgrade(tree, execute=True)


# writer label -> (the engine owner of the call to the seam, the in-process runner)
_PLAN_WRITERS: dict[str, tuple[str, Callable[[Path], int]]] = {
    "fingerprint": ("cli.py::cmd_fingerprint", _run_fingerprint),
    "install-ci": ("cli.py::cmd_install_ci", _run_install_ci),
    "upgrade --execute": ("cli.py::cmd_upgrade", _run_upgrade_execute),
}
_ENGINE_FILES = sorted(checkout_glob(REPO_ROOT / "espalier", "*.py"))  # the top-level package only


def _stable_actions(tree: Path) -> dict:
    import json

    plan = json.loads((tree / "reports" / "harness_config.json").read_text(encoding="utf-8"))
    return plan.get("stable_actions", {})


def _calls(node: ast.AST, callee: str) -> bool:
    """True if ``node``'s subtree calls ``callee`` by bare name or as an
    attribute (``cli._refresh_fingerprint_derivatives(...)`` counts)."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        fn = sub.func
        if isinstance(fn, ast.Name) and fn.id == callee:
            return True
        if isinstance(fn, ast.Attribute) and fn.attr == callee:
            return True
    return False


def _owners(source_path: Path):
    """Yield ``(label, node)`` for every top-level function, async function
    and class method of the module, labelled ``file.py::name`` or
    ``file.py::Class.name``; a nested def is attributed to its owner."""
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    for top in module.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield f"{source_path.name}::{top.name}", top
        elif isinstance(top, ast.ClassDef):
            for item in top.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{source_path.name}::{top.name}.{item.name}", item


def _owners_calling(source_paths, callee: str) -> set[str]:
    return {label for path in source_paths for label, node in _owners(path) if _calls(node, callee)}


def _owners_writing_the_plan(source_paths) -> set[str]:
    """Owners that hand ``atomic_write_text`` the plan's path -- spelled
    inline, or bound earlier in the same owner to a name whose expression
    spells it. The plan has one filename; a writer that does not spell it
    is not a writer this contract can see (stated, not hidden)."""
    def spells_plan(node: ast.AST) -> bool:
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.endswith("harness_config.json") for n in ast.walk(node))

    found: set[str] = set()
    for path in source_paths:
        for label, owner in _owners(path):
            bound = {t.id for a in ast.walk(owner) if isinstance(a, ast.Assign)
                     for t in a.targets if isinstance(t, ast.Name) and spells_plan(a.value)}
            for call in ast.walk(owner):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                        and call.func.id == "atomic_write_text" and call.args):
                    continue
                first = call.args[0]
                if spells_plan(first) or (isinstance(first, ast.Name) and first.id in bound):
                    found.add(label)
                    break
    return found


@pytest.mark.parametrize("writer", sorted(_PLAN_WRITERS))
def test_a_plan_writer_re_renders_the_docs_that_read_the_plan(tmp_path, capsys, writer):
    """DEF-806: after a command rewrites the saved plan, the two cc/ docs that
    render its actions carry the new plan, the writer names them among what it
    refreshed, the classifier reports no drift and ``upgrade`` says nothing to
    do. The stressor is asserted before the command: the tree gains Python, so
    the plan gains an action the docs on disk lack. The ``doctor`` lines at the
    end are a no-regression control, not the oracle: doctor does not see a
    stale plan render (probed by the lane's code review), the classifier and
    ``upgrade`` do."""
    from espalier.doctor import run_doctor_check
    from espalier.render_surface import PLAN_READERS, write_required_surface

    _, run = _PLAN_WRITERS[writer]
    tree = _initialized_tree(tmp_path)
    assert _upgrade(tree, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out, "control: a fresh init is current"

    (tree / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _grant_the_python_rules(tree)
    assert "scan" not in _stable_actions(tree), "stressor: the plan predates the .py"
    for rel in PLAN_READERS:
        assert _PLAN_GAINS not in (tree / rel).read_text(encoding="utf-8"), rel

    assert run(tree) == 0
    captured = capsys.readouterr()
    narrated = captured.out + captured.err  # fingerprint reports its refresh on stderr
    assert "scan" in _stable_actions(tree), f"{writer} did not rewrite the plan"
    for rel in PLAN_READERS:
        assert _PLAN_GAINS in (tree / rel).read_text(encoding="utf-8"), (
            f"{writer} rewrote the plan and left {rel} rendering the old one"
        )
        assert rel in narrated, f"{writer} did not name {rel} among what it refreshed:\n{narrated}"
    moved = [rel for rel, action in write_required_surface(tree, dry_run=True)
             if action == "updated_managed"]
    assert moved == [], moved
    assert _upgrade(tree, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out, (
        f"after {writer}, upgrade names drift on a change the tool itself made"
    )
    report = run_doctor_check(tree)
    assert report["status"] == "pass", report
    assert not any("plan" in w or "surface" in w for w in report["warnings"]), report["warnings"]


def test_a_re_baseline_re_renders_the_runner_agents_it_derived(tmp_path, capsys):
    """The reviewer's and the test-writer's tools lines are rendered from the
    fingerprint's test commands at deploy, so they follow a re-baseline the
    way the plan's readers do (the DEF-806 shape, one artifact over): a tree
    init'd with no test command that gains one is re-rendered by
    `fingerprint .`, and `upgrade` then names no drift the tool made. An
    adopter's own body (no managed marker) is never rewritten."""
    tree = _initialized_tree(tmp_path)
    agents = tree / ".claude" / "agents"
    assert "Bash(npm test" not in (agents / "code-reviewer.md").read_text(encoding="utf-8")
    (agents / "test-writer.md").write_text("---\nname: test-writer\ntools: Read\n---\nmine\n", encoding="utf-8")
    (tree / "package.json").write_text('{"name": "x", "scripts": {"test": "node --test"}}\n', encoding="utf-8")

    capsys.readouterr()
    assert _run_fingerprint(tree) == 0
    narrated = "".join(capsys.readouterr())
    reviewer = (agents / "code-reviewer.md").read_text(encoding="utf-8")
    assert "Bash(npm test)" in reviewer and "Bash(npm test *)" in reviewer, reviewer[:600]
    assert ".claude/agents/code-reviewer.md" in narrated, narrated[-800:]
    assert (agents / "test-writer.md").read_text(encoding="utf-8").endswith("mine\n"), "the adopter's body is theirs"
    assert _upgrade(tree, execute=False) == 0
    out = capsys.readouterr().out
    assert ".claude/agents/code-reviewer.md" not in out, out


def test_a_byte_identical_render_is_not_reported_as_refreshed(tmp_path, capsys):
    """The re-render lists a doc only when its render moved: a plan re-baseline
    that changes nothing the docs read (install-ci's own ``ci_providers`` flip,
    DEF-688) names the plan and not the docs, so the line never claims a
    rewrite that did not happen."""
    from espalier.render_surface import PLAN_READERS

    tree = _initialized_tree(tmp_path)
    before = {rel: (tree / rel).read_bytes() for rel in PLAN_READERS}
    capsys.readouterr()
    assert _run_install_ci(tree) == 0
    out = capsys.readouterr().out
    assert "re-baselined reports/repo_fingerprint.json" in out, out
    for rel in PLAN_READERS:
        assert (tree / rel).read_bytes() == before[rel], rel
        assert rel not in out, f"{rel} was listed as refreshed with no change:\n{out}"


def test_the_plan_writer_set_is_derived_from_the_refreshers_callers():
    """The parametrisation above is a hand list; the truth is every owner in
    the engine package that calls ``_refresh_fingerprint_derivatives``, by
    bare name or through a module attribute, functions and methods alike.
    Held equal, so a fourth caller reds here until it is driven above."""
    owners = _owners_calling(_ENGINE_FILES, "_refresh_fingerprint_derivatives")
    assert owners == {name for name, _ in _PLAN_WRITERS.values()}, owners


def test_every_direct_writer_of_the_plan_is_init_or_the_seam():
    """The seam is not the only thing that can write the plan: ``init`` hands
    ``atomic_write_text`` the same path and then deploys the docs itself. A
    third direct writer would re-open DEF-806 with the caller contract above
    still green, so the direct-writer set is derived too and held to exactly
    those two (found by the lane's code review)."""
    writers = _owners_writing_the_plan(_ENGINE_FILES)
    assert writers == {"cli.py::cmd_init", "cli.py::_refresh_fingerprint_derivatives"}, writers


def test_the_plan_reader_set_is_derived_from_the_renderers():
    """``PLAN_READERS`` is a hand-kept pair; the truth is which required-doc
    renderer reads the plan (``_load_stable_actions``). Derived from the
    renderers' own source and held equal in both directions, so a renderer
    that starts reading the plan reds here until the refresh follows it, and
    one that stops reading it reds until it leaves the pair. One hop only: a
    renderer that reads the plan through a second helper, or parses the file
    itself, is outside what this derivation can see."""
    from espalier import render_surface
    from espalier.render_surface import PLAN_READERS, REQUIRED_SURFACE_RENDERERS

    source = Path(render_surface.__file__)
    readers = {label.split("::", 1)[1] for label in _owners_calling([source], "_load_stable_actions")}
    assert readers, "the derivation found no reader: the callee name moved"
    derived = {rel for rel, fn in REQUIRED_SURFACE_RENDERERS.items() if fn.__name__ in readers}
    assert derived == set(PLAN_READERS), (derived, PLAN_READERS)


def test_write_required_surface_targets_and_existing_only(tmp_path):
    """The re-baseline's mode of the one classifier: a misspelt target raises
    rather than classifying nothing, an absent doc is left out under
    ``existing_only`` and created without it, and the pass never touches a
    doc outside ``targets``."""
    from espalier.render_surface import PLAN_READERS, write_required_surface

    tree = _initialized_tree(tmp_path)
    with pytest.raises(ValueError, match="cc/NOPE.md"):
        write_required_surface(tree, targets=("cc/NOPE.md",), dry_run=True)
    (tree / "cc" / "COMMANDS.md").unlink()
    manifest_before = (tree / "cc" / "PACK_MANIFEST.txt").read_bytes()
    actions = write_required_surface(tree, targets=PLAN_READERS, existing_only=True)
    assert [rel for rel, _ in actions] == ["cc/LIVE_SURFACE.md"], actions
    assert not (tree / "cc" / "COMMANDS.md").exists(), "existing_only created a doc"
    preview = write_required_surface(tree, targets=PLAN_READERS, existing_only=True, dry_run=True)
    assert preview == actions, "a dry run under existing_only classifies the same docs"
    actions = write_required_surface(tree, targets=PLAN_READERS)
    assert ("cc/COMMANDS.md", "created") in actions, actions
    assert (tree / "cc" / "COMMANDS.md").exists()
    assert (tree / "cc" / "PACK_MANIFEST.txt").read_bytes() == manifest_before, (
        "a targeted pass touched a doc outside targets"
    )


def test_the_drift_line_verb_follows_the_count(tmp_path, capsys):
    """Ride-along from walk 3 (W3-P38): the preview counted ``2 cc/ surface
    docs that renders differently``. One doc drifts by an edit that keeps its
    marker; two drift by a plan the docs have not seen."""
    import json

    tree = _initialized_tree(tmp_path)
    live = tree / "cc" / "LIVE_SURFACE.md"
    live.write_text(live.read_text(encoding="utf-8") + "\n<!-- stale -->\n", encoding="utf-8")
    capsys.readouterr()
    assert _upgrade(tree, execute=False) == 0
    out = capsys.readouterr().out
    assert "1 cc/ surface doc that renders differently" in out, out

    plan_path = tree / "reports" / "harness_config.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["stable_actions"]["deploy"] = ["make deploy"]
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert _upgrade(tree, execute=False) == 0
    out = capsys.readouterr().out
    assert "2 cc/ surface docs that render differently" in out, out
    assert "docs that renders" not in out


def test_a_failed_doc_re_render_is_named_by_its_own_path(tmp_path, monkeypatch):
    """A doc the refresh could not re-render is reported under its own path
    and counted once each, never as one token joining two paths (the lane's
    reviews both read the first cut's label as a path that cannot exist)."""
    from espalier import cli
    from espalier.analyze import fingerprint_repo
    from espalier.config import load_config
    from espalier.render_surface import PLAN_READERS

    tree = _initialized_tree(tmp_path)

    def _refuse(*a, **k):
        raise PermissionError(13, "Permission denied", str(tree / "cc" / "LIVE_SURFACE.md"))

    monkeypatch.setattr(cli, "write_required_surface", _refuse)
    config = load_config(tree)
    refreshed, failures = cli._refresh_fingerprint_derivatives(tree, fingerprint_repo(tree, config), config)
    assert "reports/harness_config.json" in refreshed
    assert len(failures) == len(PLAN_READERS), failures
    for rel, label in zip(PLAN_READERS, failures):
        assert label.startswith(f"{rel} ("), label
        assert "PermissionError" in label and "LIVE_SURFACE.md/cc" not in label, label


def test_upgrade_preview_names_the_docs_the_plan_rebaseline_will_re_render(tmp_path, capsys):
    """Before this lane the preview and the execute agreed by both leaving
    the docs stale; now the execute re-renders them from the re-baselined
    plan, so the preview predicts it (the lane's failure-mode review drove a
    one-file preview against a three-file execute). Deploy drift makes the
    preview reach its branch; one Python file makes the plan's actions
    change under a fresh fingerprint."""
    from espalier.render_surface import PLAN_READERS

    tree = _initialized_tree(tmp_path)
    (tree / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _grant_the_python_rules(tree)
    # Drift that no cc/ doc renders from (a deleted command would move the
    # docs on its own and mask the line under test).
    (tree / "tools" / "cc" / "statusline.py").unlink()
    capsys.readouterr()
    assert _upgrade(tree, execute=False) == 0
    out = capsys.readouterr().out
    assert "that render differently" not in out and "that renders differently" not in out, out
    assert "would re-render 2 cc/ surface docs that read the plan" in out, out
    for rel in PLAN_READERS:
        assert rel in out
    assert _upgrade(tree, execute=True) == 0
    out = capsys.readouterr().out
    for rel in PLAN_READERS:
        assert rel in out, out
    assert _upgrade(tree, execute=False) == 0
    assert "nothing to do" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Field trial, 2026-10-01: on a repo with a harness of its own (Sports, a
# Trellis tree), init reported `skipped_user_files: 4` and named none of them --
# four of the adopter's commands shadowed the harness's -- and `--dry-run` said
# it "would write" a CLAUDE.md the real run keeps, and said nothing about the
# .gitignore edit or the forward ledger. The dry run now reads the deploy's own
# classifier and the .gitignore verdict, so it is pinned EQUAL to the real run
# in both directions, not merely to a list of words.
# ---------------------------------------------------------------------------

_KEPT_PREFIX = "of yours (no managed marker, so not overwritten): "


def _kept_named(out: str) -> set[str]:
    for line in out.splitlines():
        if _KEPT_PREFIX in line:
            return set(line.split(_KEPT_PREFIX, 1)[1].strip().split(", "))
    return set()


def _dry_run(target: Path) -> str:
    return subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(target), "--dry-run"],
        capture_output=True, text=True, timeout=45, check=True, encoding="utf-8",
    ).stdout


def _trellis_shaped_target(tmp_path: Path) -> Path:
    """A repo that brought its own CLAUDE.md, two commands of the harness's
    names, an agent of the harness's name, and committed task packs."""
    target = _make_target(tmp_path)
    (target / "CLAUDE.md").write_text("# ours\n", encoding="utf-8")
    commands = target / ".claude" / "commands"
    commands.mkdir(parents=True)
    for name in ("handoff", "implement-task"):
        (commands / f"{name}.md").write_text(f"# our {name}\n", encoding="utf-8")
    (target / ".claude" / "agents").mkdir()
    (target / ".claude" / "agents" / "code-reviewer.md").write_text("# ours\n", encoding="utf-8")
    (target / "task-packs").mkdir()
    (target / "task-packs" / "TP-1_first.md").write_text("# TP-1\n", encoding="utf-8")
    (target / ".gitignore").write_text("*.log\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "-A"], cwd=str(target))
    subprocess.check_call(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-qm", "adopter tree"], cwd=str(target))
    return target


class TestTheDryRunSaysWhatInitDoes:
    def test_init_names_every_user_file_it_keeps(self, tmp_path):
        target = _trellis_shaped_target(tmp_path)

        out = _run_init(target).stdout

        assert _kept_named(out) == {
            ".claude/commands/handoff.md", ".claude/commands/implement-task.md",
            ".claude/agents/code-reviewer.md",
        }, out
        assert "of that name stays yours" in out, out

    def test_the_dry_run_keeps_exactly_what_init_keeps(self, tmp_path):
        target = _trellis_shaped_target(tmp_path)

        dry = _dry_run(target)
        real = _run_init(target).stdout

        assert _kept_named(dry) and _kept_named(dry) == _kept_named(real), (dry, real)

    def test_the_dry_run_keeps_an_existing_claude_md_and_writes_the_rest(self, tmp_path):
        target = _trellis_shaped_target(tmp_path)

        dry = _dry_run(target)

        assert "keep your existing CLAUDE.md" in dry, dry
        write_lines = [ln for ln in dry.splitlines() if "Would write" in ln]
        assert not [ln for ln in write_lines if "CLAUDE.md" in ln], write_lines
        assert [ln for ln in write_lines if ".claude/settings.json" in ln], dry

    def test_the_dry_run_appends_exactly_the_entries_init_appends(self, tmp_path):
        from espalier.cli import (
            GITIGNORE_BLOCK_FOOTER, GITIGNORE_BLOCK_HEADER, GITIGNORE_REINCLUDES,
        )

        target = _trellis_shaped_target(tmp_path)
        dry = _dry_run(target)
        prefix = "to .gitignore: "
        line = next(ln for ln in dry.splitlines() if "Would append" in ln and prefix in ln)
        said = set(line.split(prefix, 1)[1].strip().split(", "))

        _run_init(target)

        lines = [ln.strip() for ln in
                 (target / ".gitignore").read_text(encoding="utf-8").splitlines()]
        block = lines[lines.index(GITIGNORE_BLOCK_HEADER) + 1:lines.index(GITIGNORE_BLOCK_FOOTER)]
        written = {ln for ln in block if ln not in GITIGNORE_REINCLUDES}
        assert said == written, (said ^ written)
        assert "/task-packs/*" not in said
        assert "Would leave /task-packs/* to you" in dry, dry

    def test_the_dry_run_names_the_forward_ledger_and_its_rows(self, tmp_path):
        dry = _dry_run(_make_target(tmp_path))

        assert "task-packs/FORWARD_LEDGER.md" in dry and "ONB-1" in dry, dry

    def test_the_dry_run_promises_no_repair_the_real_run_refuses(self, tmp_path):
        """Code review, 2026-10-01, driven: a `/task-packs/` of the adopter's
        own outside the harness block is never repaired, and the dry run said
        it would be."""
        target = _make_target(tmp_path)
        (target / ".gitignore").write_text("/task-packs/\n", encoding="utf-8")

        dry = _dry_run(target)
        real = _run_init(target).stdout

        assert "Would repair" not in dry, dry
        assert "Would leave the task-packs rule as it is" in dry, dry
        assert "Rewrote" not in real and "outside the harness block" in real, real

    def test_init_and_the_dry_run_name_a_command_a_skill_replaces(self, tmp_path):
        """Claude Code runs a skill over a command of the same name, so the
        harness's reflect skill replaces an adopter's /reflect command, and an
        adopter's commit skill replaces the harness's /commit (field trial,
        2026-10-01: probelab's /reflect). Different paths, so nothing kept or
        named them."""
        target = _make_target(tmp_path)
        (target / ".claude" / "commands").mkdir(parents=True)
        (target / ".claude" / "commands" / "reflect.md").write_text("# ours\n", encoding="utf-8")
        (target / ".claude" / "skills" / "commit").mkdir(parents=True)
        (target / ".claude" / "skills" / "commit" / "SKILL.md").write_text(
            "---\nname: commit\ndescription: ours\n---\n", encoding="utf-8")

        for out in (_dry_run(target), _run_init(target).stdout):
            assert "your /reflect command (.claude/commands/reflect.md)" in out, out
            assert "your commit skill (.claude/skills/commit/SKILL.md)" in out, out


def _real_git_current_tree(tmp_path: Path) -> Path:
    """``_deployed_current_tree`` over a REAL git repository (its fake `.git`
    leaves git unable to answer), committing a pack of the adopter's own under
    a harness block that still carries ``/task-packs/*``."""
    from espalier.analyze import fingerprint_repo
    from espalier.cli import (
        GITIGNORE_BLOCK_FOOTER, GITIGNORE_BLOCK_HEADER, REQUIRED_GITIGNORE,
        deploy_harness, render_gitignore_entries,
    )
    from espalier.models import BuildPlan

    subprocess.check_call(["git", "init", "--quiet"], cwd=str(tmp_path))
    deploy_harness(tmp_path, BuildPlan(repo_name="x", profiles=["ci_cd"]),
                   fingerprint_repo(tmp_path))
    (tmp_path / "task-packs").mkdir(exist_ok=True)   # init seeds it; the deploy does not
    (tmp_path / "task-packs" / "TP-1_first.md").write_text("# TP-1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("\n".join([
        GITIGNORE_BLOCK_HEADER, *render_gitignore_entries(REQUIRED_GITIGNORE),
        GITIGNORE_BLOCK_FOOTER]) + "\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "-A"], cwd=str(tmp_path))
    subprocess.check_call(["git", "add", "-f", "task-packs/TP-1_first.md"], cwd=str(tmp_path))
    subprocess.check_call(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit", "-qm", "an earlier init"], cwd=str(tmp_path))
    return tmp_path


def test_a_version_current_upgrade_does_not_call_a_pending_gitignore_report_nothing(
    tmp_path, capsys,
):
    """Both reviews, 2026-10-01, driven: the retire advice printed, then
    "harness is current; nothing to do" -- `needed_entries` holds only the
    entries an append would add."""
    _real_git_current_tree(tmp_path)
    capsys.readouterr()

    assert _upgrade(tmp_path, execute=False) == 0

    out = capsys.readouterr().out
    assert "delete the /task-packs/* line" in out, out
    assert "nothing to do" not in out, out
    assert "see the .gitignore report above" in out, out


# ── TP-472 2-B: init writes the config skeleton ───────────────────────────────


class TestInitWritesTheConfigSkeleton:
    """TP-472 2-B (DEF-1088's fingerprint half, DEF-1191). Every plan-guard
    deny, the onboarding row and the generated CLAUDE.md told the adopter to
    set a key in espalier.toml, and ``init`` wrote no such file (measured
    2026-10-07 and 2026-10-08 on an init'd Node tree). Now ``init`` writes it
    beside CLAUDE.md on the same rule -- created when absent, never rewritten
    -- with every ``HarnessConfig`` key and every deployed reader's key
    commented out and the fingerprint's candidates in the comments.

    RED when a field is dropped from the renderer (the every-field pin) and
    when the deploy rewrites a present file (the bytes pin).
    """

    def test_the_skeleton_is_written_once_and_never_rewritten(self, tmp_path):
        import dataclasses
        import re
        import warnings

        from espalier.config import FOREIGN_KEYS, load_config
        from espalier.models import HarnessConfig

        target = _make_target(tmp_path)
        out = _run_init(target).stdout
        toml = target / "espalier.toml"
        assert toml.is_file(), "init wrote no espalier.toml"
        assert "espalier.toml is your harness config" in out, out
        text = toml.read_text(encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert load_config(target) == HarnessConfig(), "the skeleton sets a key"
        assert not caught, [str(w.message) for w in caught]
        for f in dataclasses.fields(HarnessConfig):
            assert re.search(rf"(?m)^# (?:{f.name}\s*=|\[{f.name}\])", text), (
                f"no commented line for HarnessConfig.{f.name}"
            )
        deployed_foreign = [k for k, reader in FOREIGN_KEYS.items() if reader.startswith("tools/cc/")]
        assert deployed_foreign, "no deployed foreign key -- the derivation is vacuous"
        for key in deployed_foreign:
            # A deployed reader's key may be a table (`id_blocks`), commented as its
            # header -- the two forms the HarnessConfig loop above accepts.
            assert re.search(rf"(?m)^# (?:{key}\s*=|\[{key}\])", text), f"no commented line for {key}"

        # Uncomment a key: the file is the adopter's from here on. A second
        # init and an upgrade leave it byte for byte.
        edited = text + '\nplan_exempt_prefixes = ["lib/"]\n'
        toml.write_text(edited, encoding="utf-8")
        assert _run_init(target).returncode == 0
        assert toml.read_text(encoding="utf-8") == edited, "a second init rewrote the adopter's config"
        assert _run_upgrade_execute(target) == 0
        assert toml.read_text(encoding="utf-8") == edited, "upgrade rewrote the adopter's config"

    def test_the_skeleton_names_the_fingerprints_candidates(self, tmp_path):
        from tests._adopter_tree import build_adopter_tree

        tree = build_adopter_tree(tmp_path, stack="node", tree="adopter")
        text = (tree / "espalier.toml").read_text(encoding="utf-8")
        assert '# plan_exempt_prefixes = ["src/"]' in text, text  # the Node fixture is src_layout
        assert "test roots (__tests__/, spec/, test/, tests/) are exempt already" in text, text

    def test_the_roots_the_skeleton_names_are_the_roots_the_hook_exempts(self, tmp_path):
        """A Python tree with a few JavaScript files speaks two languages and
        carries one manifest. The skeleton's "exempt already" line must name
        what the hook exempts on THAT tree -- the Python manifest's roots --
        not every root of every language present (both 3-A reviewers drove
        the first cut, keyed on languages, naming `__tests__/` and `spec/`
        that the hook denied). The oracle is the hook itself, driven."""
        import json
        import os
        import re  # local: a top-level import shifts every line the derived-population census pins

        from tests._adopter_tree import build_adopter_tree
        from tests._hook_assertions import assert_hook_allowed, assert_hook_denied

        tree = build_adopter_tree(tmp_path, stack="python", tree="git")
        (tree / "assets").mkdir()
        (tree / "assets" / "app.js").write_text("export const x = 1;\n", encoding="utf-8")
        (tree / "assets" / "ui.jsx").write_text("export const y = 2;\n", encoding="utf-8")
        assert _run_init(tree).returncode == 0
        text = (tree / "espalier.toml").read_text(encoding="utf-8")
        named = re.search(r"test roots \(([^)]*)\) are exempt already", text)
        assert named, text
        roots = {r.strip() for r in named.group(1).split(",")}
        assert roots == {"test/", "tests/"}, roots
        hook = REPO_ROOT / "tools" / "cc" / "hooks" / "plan_guard.py"
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tree)}

        def drive(rel: str) -> subprocess.CompletedProcess:
            payload = {"tool_name": "Edit", "tool_input": {"file_path": str(tree / rel)}}
            return subprocess.run(
                [sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                text=True, timeout=15, env=env, encoding="utf-8",
            )

        for root in roots:
            assert_hook_allowed(drive(f"{root}a.py"))
        for root in ("__tests__/", "spec/"):
            assert root not in roots
            assert_hook_denied(drive(f"{root}a.py"), contains_reason="plan_exempt_prefixes")

    def test_a_kept_config_is_told_which_keys_it_has_no_line_for(self, tmp_path):
        """The CLAUDE.md nudge's twin (the 3-A review): a kept espalier.toml is
        never rewritten, so a key a later version adds reaches the adopter
        only through init's note, which names the keys the file has no line
        for and the render that prints them."""
        target = _make_target(tmp_path)
        (target / "espalier.toml").write_text('plan_exempt_prefixes = ["src/"]\n', encoding="utf-8")
        out = _run_init(target).stdout
        assert "kept your existing espalier.toml" in out, out
        assert "goal_snapshot" in out and "handoff_push" in out and "render-template toml" in out, out
        assert (target / "espalier.toml").read_text(encoding="utf-8") == 'plan_exempt_prefixes = ["src/"]\n'
        # A complete file draws no note.
        (tmp_path / "full").mkdir()
        full = _make_target(tmp_path / "full")
        assert _run_init(full).returncode == 0
        assert "kept your existing espalier.toml" not in _run_init(full).stdout

    def test_the_preview_classifies_the_skeleton_with_the_root_files(self, tmp_path):
        from espalier.cli import preview_managed_surface

        target = _make_target(tmp_path)
        assert "espalier.toml" in preview_managed_surface(target, goal_snapshot=True)["created"]
        _run_init(target)
        assert "espalier.toml" not in preview_managed_surface(target, goal_snapshot=True)["created"]


class TestTheInitSummaryNamesWhatGateOneRuns:
    """2-A of the 2026-10-08 lane: the init summary's stop-gate line said the
    suite ran only through the override and any other stack ran nothing. Gate
    1 runs the detected command now, and the line says the order of the three
    sources. Dies to the earlier text."""

    def test_the_line_names_the_detected_command_as_what_runs(self):
        import types
        from espalier.cli import _stop_gate_summary_line
        line = _stop_gate_summary_line(types.SimpleNamespace(test_commands=["npm test"]))
        assert "npm test" in line and "[extra_actions] test" in line and "ESPALIER_STOP_GATE_TEST_CMD" in line, line
        assert "only through" not in line and "runs nothing" not in line, line

    def test_more_than_one_detected_command_names_the_one_that_runs(self):
        import types
        from espalier.cli import _stop_gate_summary_line
        line = _stop_gate_summary_line(types.SimpleNamespace(test_commands=["pytest -q", "npm test"]))
        assert "pytest -q (the first of pytest -q, npm test; the others are not run)" in line, line

    def test_no_detected_command_is_said_plainly(self):
        import types
        from espalier.cli import _stop_gate_summary_line
        line = _stop_gate_summary_line(types.SimpleNamespace(test_commands=[]))
        assert "none detected" in line, line


# ── TP-474 4-A: every writer of a gated path names the approval marker ───────


_MARKER = "HARNESS-UPDATE-APPROVED"


def _git_q(tree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def _with_guard(tree: Path) -> Path:
    """A real git repository carrying the Harness Guard script, nothing else."""
    _git_q(tree, "init", "-q")
    guard = tree / "tools" / "cc" / "ci_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("# the guard\n", encoding="utf-8")
    return tree


class TestApprovalMarkerLines:
    """The helper's own arms: silent without the guard, where git cannot
    answer, on an ignored path and on an adopter's own workflow; both forms on
    an adopter, the pull-request form alone on the self-host repository."""

    def test_silent_without_the_guard(self, tmp_path):
        from espalier.cli import _approval_marker_lines
        _git_q(tmp_path, "init", "-q")
        assert _approval_marker_lines(tmp_path, ["tools/cc/hooks/write_guard.py"]) == []

    def test_silent_where_git_cannot_answer(self, tmp_path):
        from espalier.cli import _approval_marker_lines
        guard = tmp_path / "tools" / "cc" / "ci_guard.py"
        guard.parent.mkdir(parents=True)
        guard.write_text("# the guard\n", encoding="utf-8")
        assert _approval_marker_lines(tmp_path, ["tools/cc/ci_guard.py"]) == []  # no .git
        (tmp_path / ".git").mkdir()                                              # a .git git refuses
        assert _approval_marker_lines(tmp_path, ["tools/cc/ci_guard.py"]) == []

    def test_an_ignored_gated_path_is_silent_and_a_tracked_one_counts(self, tmp_path):
        from espalier.cli import _approval_marker_lines
        tree = _with_guard(tmp_path)
        (tree / ".gitignore").write_text(".claude/settings.json\n", encoding="utf-8")
        settings = tree / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text("{}\n", encoding="utf-8")
        assert _approval_marker_lines(tree, [".claude/settings.json"]) == []
        _git_q(tree, "add", "-f", ".claude/settings.json")
        lines = _approval_marker_lines(tree, [".claude/settings.json"])
        assert any(".claude/settings.json" in line for line in lines), lines

    def test_an_adopters_own_workflow_is_not_gated(self, tmp_path):
        from espalier.cli import _approval_marker_lines
        tree = _with_guard(tmp_path)
        assert _approval_marker_lines(tree, [".github/workflows/ci.yml"]) == []
        assert _approval_marker_lines(tree, [".github/workflows/harness-guard.yml"]) != []

    def test_an_adopter_reads_both_forms(self, tmp_path):
        from espalier.cli import _approval_marker_lines
        text = "\n".join(_approval_marker_lines(_with_guard(tmp_path), ["tools/cc/ci_guard.py"]))
        # HEAD: the gate reads the last pushed commit's message alone.
        assert f"{_MARKER} in the HEAD commit message" in text, text
        assert f"{_MARKER}@<sha> in the title" in text, text
        assert text.isascii(), text

    def test_one_batch_sorts_tracked_ignored_and_plain_paths(self, tmp_path):
        from espalier.cli import _git_ignored
        tree = _with_guard(tmp_path)
        (tree / ".gitignore").write_text(".claude/\nsub/*.log\n", encoding="utf-8")
        for rel in (".claude/settings.json", ".claude/settings.local.json", "sub/a.log", "sub/b.txt"):
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / rel).write_text("x\n", encoding="utf-8")
        _git_q(tree, "add", "-f", ".claude/settings.json")
        assert _git_ignored(tree, [".claude/settings.json", ".claude/settings.local.json",
                                   "sub/a.log", "sub/b.txt", "dir with space/x.py"]) == {
            ".claude/settings.local.json", "sub/a.log"}

    def test_the_install_ci_banner_never_spells_the_marker(self):
        """Its spelled forms come from the helper alone, so a dropped helper
        call reds the DEF-1050 probe and the Walk instead of being hidden by a
        static line printed on every run."""
        from espalier.cli import INSTALL_CI_INSTRUCTIONS
        assert _MARKER not in INSTALL_CI_INSTRUCTIONS
        assert "approval marker" in " ".join(INSTALL_CI_INSTRUCTIONS.split())

    def test_the_self_host_repository_reads_the_pull_request_form_alone(self, tmp_path, monkeypatch):
        from espalier import cli, surface_contract
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda root: True)
        text = "\n".join(cli._approval_marker_lines(_with_guard(tmp_path), ["tools/cc/ci_guard.py"]))
        assert f"{_MARKER}@<sha> in the title" in text, text
        assert "commit message" not in text, text


def _marker_tree(tmp_path: Path, *, guard: bool, track_settings: bool = False,
                 track_manifest: bool = False) -> Path:
    """A README-only repository with real git (the fake ``.git`` of
    ``_initialized_tree`` leaves git unable to answer, which the helper reads
    as silence), init'd in process; ``guard`` runs install-ci after it.
    ``track_settings``: the adopter tracked a ``.claude/settings.json`` before
    init, so init withholds its ignore entry (DEF-11) and a rewrite of it
    reaches a commit."""
    import argparse
    from espalier.cli import cmd_init, cmd_install_ci

    tree = tmp_path / "t"
    tree.mkdir()
    (tree / "README.md").write_text("# t\n", encoding="utf-8")
    _git_q(tree, "init", "-q")
    # DEF-1168's sister site (tests/_quiet_git.py): each commit spawns
    # `maintenance run --auto` here (GIT_TRACE of the census build), and the
    # census copies this tree once a run; its CI reds lost whole object
    # folders mid-copy.
    for key, value in NO_BACKGROUND_GIT:
        _git_q(tree, "config", key, value)
    if track_settings:
        (tree / ".claude").mkdir()
        (tree / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        _git_q(tree, "add", "-A")
        _git_q(tree, "commit", "-qm", "the adopter's own settings")
    assert cmd_init(argparse.Namespace(repo=str(tree), config=None, write_gitignore=True)) == 0
    if guard:
        assert cmd_install_ci(argparse.Namespace(repo=str(tree), config=None)) == 0
    if track_manifest:  # an adopter who tracks .espalier/integrity.json
        _git_q(tree, "add", "-f", ".espalier/integrity.json")
    return tree


def _stale_a_hook(tree: Path) -> None:
    hook = tree / "tools" / "cc" / "hooks" / "plan_guard.py"
    hook.write_bytes(hook.read_bytes() + b"#\n")


def _marker_install_ci(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_install_ci
    return cmd_install_ci(argparse.Namespace(repo=str(tree), config=None))


def _marker_upgrade(tree: Path) -> int:
    _stale_a_hook(tree)
    return _upgrade(tree, execute=True)


def _marker_init_rerun(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_init
    _stale_a_hook(tree)
    return cmd_init(argparse.Namespace(repo=str(tree), config=None, write_gitignore=True))


def _marker_upgrade_settings_only(tree: Path) -> int:
    """upgrade --execute whose one gated write is the settings merge: an
    older stamp sends it down the version-bump arm, which merges the file
    (a version-current tree with no drift says it is current and stops)."""
    (tree / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    _stamp_older(tree)
    return _upgrade(tree, execute=True)


def _marker_upgrade_nothing_else_gated(tree: Path) -> int:
    """upgrade --execute whose gated writes are the integrity refresh alone."""
    _stamp_older(tree)
    return _upgrade(tree, execute=True)


def _marker_clean_generated(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_clean_generated
    return cmd_clean_generated(argparse.Namespace(repo=str(tree), execute=True))


def _marker_integrity_refresh(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_integrity
    return cmd_integrity(argparse.Namespace(repo=str(tree), action="refresh"))


def _marker_merge_settings(tree: Path) -> int:
    import argparse
    from espalier.cli import cmd_merge_settings
    (tree / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")  # the merge has work
    return cmd_merge_settings(argparse.Namespace(repo=str(tree), profile=None, add_allows=False,
                                                 repair=False))


# writer -> (the tree it runs on, the writer, whether its output names the marker)
_MARKER_WRITERS: dict[str, tuple[dict, Callable[[Path], int], bool]] = {
    "install-ci": ({"guard": False}, _marker_install_ci, True),
    "upgrade --execute": ({"guard": True}, _marker_upgrade, True),
    "init re-run": ({"guard": True}, _marker_init_rerun, True),
    "merge-settings, tracked settings": ({"guard": True, "track_settings": True},
                                         _marker_merge_settings, True),
    "upgrade --execute, tracked settings": ({"guard": True, "track_settings": True},
                                            _marker_upgrade_settings_only, True),
    "upgrade --execute, tracked manifest": ({"guard": True, "track_manifest": True},
                                            _marker_upgrade_nothing_else_gated, True),
    "clean-generated --execute": ({"guard": True}, _marker_clean_generated, True),
    "integrity refresh, tracked manifest": ({"guard": True, "track_manifest": True},
                                            _marker_integrity_refresh, True),
    # The negative arms: no guard on disk; every gated path written is ignored.
    "upgrade --execute, no guard": ({"guard": False}, _marker_upgrade, False),
    "init re-run, no guard": ({"guard": False}, _marker_init_rerun, False),
    "merge-settings, ignored settings": ({"guard": True}, _marker_merge_settings, False),
    "upgrade --execute, ignored settings": ({"guard": True}, _marker_upgrade_settings_only, False),
    "integrity refresh, ignored manifest": ({"guard": True}, _marker_integrity_refresh, False),
}


class TestEveryWriterOfAGatedPathNamesTheMarker:
    """§C68 (DEF-1050, DEF-1052): a command that writes a path the Harness
    Guard gates, which git will commit, says the commit needs the approval
    marker, in both forms; where the guard is absent or every gated path it
    wrote is ignored, it says nothing. fuse, the fifth writer, is pinned in
    tests/test_fuse.py."""

    @pytest.mark.parametrize("writer", sorted(_MARKER_WRITERS))
    def test_the_writer_names_the_marker_exactly_when_the_commit_needs_it(
        self, writer, tmp_path, capsys, monkeypatch,
    ):
        # A shell inside a Claude Code session defers clean-generated's deletion.
        monkeypatch.delenv("CLAUDECODE", raising=False)
        tree_kwargs, run, names_it = _MARKER_WRITERS[writer]
        tree = _marker_tree(tmp_path, **tree_kwargs)
        capsys.readouterr()
        assert run(tree) == 0
        captured = capsys.readouterr()
        out = captured.out + captured.err  # clean-generated keeps stdout one JSON document
        if names_it:
            assert f"{_MARKER} in the HEAD commit message" in out, out
            assert f"{_MARKER}@<sha> in the title" in out, out
        else:
            assert _MARKER not in out, out

    def test_init_rewiring_a_tracked_settings_file_names_the_marker(self, tmp_path, capsys, monkeypatch):
        """--rewire-interpreter rewrites the settings file in place; where the
        adopter tracks it the commit is gated. The rewire itself is pinned
        elsewhere: here only that a rewrite reaches the clause."""
        import argparse
        from espalier import cli

        tree = _marker_tree(tmp_path, guard=True, track_settings=True)
        monkeypatch.setattr(cli, "_report_interpreter_rewire", lambda path: cli.REWIRE_DONE)
        capsys.readouterr()
        assert cli.cmd_init(argparse.Namespace(repo=str(tree), config=None, write_gitignore=True,
                                               rewire_interpreter=True)) == 0
        out = capsys.readouterr().out
        assert ".claude/settings.json" in out and f"{_MARKER}@<sha> in the title" in out, out


# DEF-3002: _MARKER_WRITERS is the population its authors remembered, and the CI
# lane found three silent writers it had missed. The census derives the
# population instead: every leaf command build_parser registers, run once bare
# and once per switch (a store_true or store_false flag, or each value of a
# flag or positional that takes choices), on a tree that gives each known
# writer work to do. A run that leaves a path the Harness Guard gates, and git
# does not ignore, changed in the tree must print the helper's clause. A new
# command or switch joins without an edit here; one the census cannot build
# reds by name until it gets a value (_CENSUS_VALUES) or a reason
# (_CENSUS_NOT_RUN), and one that exits non-zero, so may never have reached its
# write, reds until _CENSUS_REFUSES says why. The limits: a flag that takes a
# free value runs at its default, and a write that needs a state this tree
# lacks is not seen.

_CENSUS_PACK = "task-packs/TP-1-census.md"

#: A value for each positional that is neither the repository nor a choice.
_CENSUS_VALUES: dict[str, str] = {
    "pack_path": _CENSUS_PACK,
    "fragment_id": "census-fragment",
}

#: The leaf commands the census does not run, each with its reason.
_CENSUS_NOT_RUN: dict[str, str] = {
    "fuse": "writes a new tree at --out, never the census tree; "
            "tests/test_fuse.py::TestFuseCiGateBanner holds its clause",
    "refresh-externals": "fetches each docs/external/ pin's source over the network, and "
                         "--apply writes docs/external/, which the Harness Guard does not gate",
}

#: The runs that exit non-zero on the census tree, each with why. A refusal
#: may stop a command before its write, so an unlisted one reds; a listed one
#: that now exits 0 reds too, so the table cannot keep excusing a command that
#: has started to run through.
_CENSUS_REFUSES: dict[str, str] = {
    # A key is a census id; `<id> *` also covers every switch of that id.
    "doctor *": "reports the census tree's planted drift (the stale hook, the unwired "
                "settings file) and exits 1; a reader",
    "integrity verify": "reports the stale hook's drift and exits 1; a reader",
    "selfcheck --contracts": "fails its upstream-parity check on the stale hook; a reader",
    "scope-check *": "walks the pack's symbol through the tree and exits 2 on the scope "
                     "gap it finds; a reader",
    "blueprint record *": "needs the session `blueprint start` opens; the blueprint "
                          "commands write cc/blueprints/, which init ignores",
    "blueprint finalize *": "needs the session `blueprint start` opens; cc/blueprints/ "
                            "is ignored",
    "blueprint load *": "needs a blueprint on disk; a reader",
    "freshness pin *": "names a fragment no doc on the tree carries; "
                       ".espalier/freshness.json is not a path the Harness Guard gates",
    "freshness unpin": "names a fragment the manifest does not hold; not a gated path",
    "memory prune": "needs Session Log rows the tree does not have (--allow-empty runs "
                    "through); writes memory files, which the Harness Guard does not gate",
    "release-pack": "refuses off the Espalier-Harness source tree",
    "_refresh-self-host-pin": "refuses off the Espalier-Harness source tree; its pin "
                              "rewrite is held on a clone of this repository by "
                              "::TestTheSelfHostPinRefreshNamesTheMarker",
}


def _census_refusal(census_id: str) -> "str | None":
    """The reason a census id exits non-zero: its own key, or `<id> *` for a
    command it is a switch of."""
    for key, reason in _CENSUS_REFUSES.items():
        base = key.removesuffix(" *")
        if census_id == base or (key.endswith(" *") and census_id.startswith(base + " ")):
            return reason
    return None

#: The writers _MARKER_WRITERS names, as census ids. Each must change a gated
#: path on the census tree, or the tree has stopped giving writers work and
#: every assertion below passes over nothing.
_CENSUS_FLOOR = ("init", "merge-settings", "upgrade --execute", "clean-generated --execute",
                 "integrity refresh", "install-ci")


def _census_leaves(parser=None, path: tuple[str, ...] = ()):
    """(command path, its parser) for every leaf build_parser registers."""
    import argparse
    if parser is None:
        from espalier.cli import build_parser
        parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _census_leaves(sub, (*path, name))
            return
    yield path, parser


def _census_variants() -> dict[str, list[str]]:
    """census id -> argv, ``{repo}`` standing for the census tree."""
    import argparse
    variants: dict[str, list[str]] = {}
    for path, parser in _census_leaves():
        leaf = " ".join(path)
        if leaf in _CENSUS_NOT_RUN:
            continue
        heads: list[tuple[list[str], list[str]]] = [([], [])]  # (argv, the id's choice words)
        switches: list[list[str]] = []
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if not action.option_strings:
                if action.choices:
                    heads = [(argv + [str(c)], ids + [str(c)]) for argv, ids in heads
                             for c in action.choices]
                else:
                    value = "{repo}" if action.dest == "repo" else _CENSUS_VALUES.get(
                        action.dest, f"<no census value for {action.dest}>")
                    heads = [(argv + [value], ids) for argv, ids in heads]
            elif isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                switches.append([action.option_strings[-1]])
            elif action.choices:
                switches.extend([action.option_strings[-1], str(c)] for c in action.choices)
            elif type(action) is not argparse._StoreAction:  # a free value runs at its default
                # store_const, count, append and BooleanOptionalAction switch
                # behaviour too; until the census has a rule for one, it reds.
                switches.append([f"<no census rule for {type(action).__name__} "
                                 f"{action.option_strings[-1]}>"])
        for argv, ids in heads:
            base = " ".join([leaf, *ids])
            variants[base] = [*path, *argv]
            for switch in switches:
                variants[f"{base} {'='.join(switch)}"] = [*path, *argv, *switch]
    return variants


_CENSUS_VARIANTS = _census_variants()


def _census_changed(tree: Path) -> list[str]:
    """Every path git reports changed, added or deleted in ``tree`` (a rename's
    two names both), ignored paths left out as git leaves them out."""
    raw = subprocess.run(["git", "-C", str(tree), "status", "--porcelain=v1", "-z", "-uall"],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    entries = raw.split("\0")
    changed: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        changed.append(entry[3:])
        if entry[0] in "RC":  # -z puts the source name in the next field
            changed.append(entries[index])
            index += 1
    return changed


def _census_head(tree: Path) -> str:
    return subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def _census_committed(tree: Path, since: str) -> list[str]:
    """The paths the commits after ``since`` changed: a command that commits
    its own write leaves ``git status`` clean."""
    raw = subprocess.run(["git", "-C", str(tree), "diff", "--name-only", "-z", since, "HEAD"],
                         capture_output=True, check=True).stdout
    return [rel for rel in raw.decode("utf-8", "replace").split("\0") if rel]


# The census tree's object store as its fixture left it, keyed by the tree's
# path, so a failed copy's report shows what moved since the build.
_CENSUS_BUILT: dict[str, str] = {}


def _object_store(src: Path) -> str:
    """``src``'s object store in one line: its packs (a ``tmp_pack_*`` is a
    pack being written), then its loose objects and the folders holding
    them. Each is read on its own, so a folder that vanishes or cannot be
    listed costs its own count and never the pack line."""
    objects = src / ".git" / "objects"
    if not objects.is_dir():
        return "objects/ is GONE"
    try:
        packs = sorted(p.name for p in (objects / "pack").iterdir()
                       if p.name.endswith(".pack") or p.name.startswith("tmp_pack_"))
        pack_line = ", ".join(packs) or "no pack"
    except OSError as exc:
        pack_line = f"unread ({type(exc).__name__})"
    try:
        folders = [d for d in objects.iterdir() if len(d.name) == 2]
    except OSError as exc:
        return f"objects/pack: {pack_line}; loose objects unread ({type(exc).__name__})"
    loose, unread = 0, 0
    for folder in folders:
        try:
            loose += sum(1 for _ in folder.iterdir())
        except OSError:
            unread += 1
    tail = f", {unread} unreadable" if unread else ""
    return f"objects/pack: {pack_line}; loose objects: {loose} in {len(folders)} folders{tail}"


def _names_the_tree(value: str, roots: set[str]) -> bool:
    """``value`` (an argument, or a link a process holds) is a root or a path
    under one, at a separator: ``census0/tx`` is not ``census0/t``. A
    ``--key=<path>`` argument is read by its path, and a link to a removed
    folder by the path it had. Both sides compare with forward slashes."""
    value = value.removesuffix(" (deleted)").replace("\\", "/")
    if "=" in value and not value.startswith("/"):
        value = value.split("=", 1)[1]
    return any(value == root or value.startswith(root + "/") for root in roots)


def _processes_naming(roots: set[str], proc: Path) -> str:
    """Every process in ``proc`` whose working directory, open files or
    command line name a root. A 'none' says how many it read and how many
    links it could not, since a process that exited before this read, or
    one acting through a relative path, is not seen."""
    if not proc.is_dir():
        return f"no {proc} here: processes unread"
    found, read, unreadable = [], 0, 0
    for entry in sorted(proc.iterdir(), key=lambda p: p.name):
        if not entry.name.isdigit():
            continue
        read += 1
        links = []
        try:
            links.append(os.readlink(entry / "cwd"))
        except OSError:
            unreadable += 1
        try:
            links += [os.readlink(fd) for fd in (entry / "fd").iterdir()]
        except OSError:
            pass
        try:
            argv = (entry / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
        except OSError:
            argv = []
        if any(_names_the_tree(v, roots) for v in links + argv):
            found.append(f"pid {entry.name}: {' '.join(a for a in argv if a)[:300] or '?'}")
    if found:
        return "processes naming the tree now: " + "; ".join(found)
    return (f"processes naming the tree now: none of {read} pids ({unreadable} with an unreadable "
            "cwd; a process that exited before this read, or one acting through a relative "
            "path, is not seen)")


def _census_copy_failed(src: Path, *, proc: Path = Path("/proc"), built: "str | None" = None) -> str:
    """What the census tree looks like after a copy of it failed: whether
    it is there, its object store at build and now (a new pack is a gc that
    ran in it; missing folders and no pack are a removal), git's own gc and
    lock files, git's version, and every process naming the tree or the
    folder holding it (Linux's ``/proc``; elsewhere unread, and saying so).
    Every read tolerates the tree vanishing under it."""
    roots = {str(p).replace("\\", "/") for p in (src.parent, src.parent.resolve())}
    lines = [f"census tree {src} is {'there' if src.is_dir() else 'GONE'}",
             f"  at build: {built or 'unrecorded'}",
             f"  now:      {_object_store(src)}"]
    try:
        markers = sorted(p.name for p in (src / ".git").iterdir()
                         if p.name in ("gc.pid", "gc.log") or p.name.endswith(".lock"))
        if (src / ".git" / "objects" / "maintenance.lock").exists():  # held by `maintenance run`
            markers.append("objects/maintenance.lock")
        lines.append("  gc.pid, gc.log, *.lock in .git: " + (", ".join(markers) or "none"))
    except OSError as exc:
        lines.append(f"  .git unread ({type(exc).__name__})")
    try:
        version = subprocess.run(["git", "--version"], capture_output=True, text=True,
                                 encoding="utf-8", timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        version = f"unread ({type(exc).__name__})"
    lines.append(f"  git: {version or 'unread'}")
    lines.append("  " + _processes_naming(roots, proc))
    return "\n".join(lines)


def _census_copy(src: Path, dst: Path) -> None:
    """The census tree copied for one run. A copy that fails reports what
    its source looks like now (``_census_copy_failed``), beside the error
    that names the files that vanished."""
    import shutil

    try:
        shutil.copytree(src, dst)
    except OSError as exc:
        what = type(exc).__name__
        if isinstance(exc, shutil.Error) and exc.args and isinstance(exc.args[0], list):
            what += f", {len(exc.args[0])} entries"
        pytest.fail(f"the census tree's copy failed ({what}, the error above); what its source "
                    "looks like now:\n" + _census_copy_failed(src, built=_CENSUS_BUILT.get(str(src))))


@pytest.fixture(scope="module")
def census_tree(tmp_path_factory):
    """An install-ci tree that tracks its settings file and its integrity
    manifest, committed with work in it for every known writer: a stale hook
    (init, upgrade, integrity refresh), an older stamp (upgrade's version-bump
    arm), an unwired settings file (merge-settings) and a task pack (the
    commands that read one)."""
    with pytest.MonkeyPatch.context() as mp:
        for var in ("CLAUDECODE", "CLAUDE_PROJECT_DIR"):
            mp.delenv(var, raising=False)
        tree = _marker_tree(tmp_path_factory.mktemp("census"), guard=True,
                            track_settings=True, track_manifest=True)
    _stale_a_hook(tree)
    _stamp_older(tree)
    (tree / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    pack = tree / _CENSUS_PACK
    pack.parent.mkdir(parents=True, exist_ok=True)
    pack.write_text("# TP-1: the census pack\n\n## Affected symbols\n\n### Changed\n\n"
                    "- `tools/cc/hooks/plan_guard.py::main`\n",
                    encoding="utf-8")
    _git_q(tree, "add", "-A")
    _git_q(tree, "add", "-f", ".claude/settings.json", ".espalier/integrity.json")
    _git_q(tree, "commit", "-qm", "the census tree")
    _CENSUS_BUILT[str(tree)] = _object_store(tree)
    return tree


class TestEveryCommandThatWritesAGatedPathNamesTheMarker:
    """DEF-3002: the marker-writer population derived from build_parser,
    not remembered. The hand list above keeps its negative arms (no guard,
    every gated path ignored), which this census does not build."""

    @pytest.mark.parametrize("census_id", sorted(_CENSUS_VARIANTS))
    def test_a_run_that_changes_a_gated_path_names_the_marker(
        self, census_id, census_tree, tmp_path, capsys, monkeypatch,
    ):
        from espalier import surface_contract
        from espalier.cli import build_parser

        for var in ("CLAUDECODE", "CLAUDE_PROJECT_DIR"):
            monkeypatch.delenv(var, raising=False)
        tree = tmp_path / "t"
        _census_copy(census_tree, tree)
        argv = [arg.replace("{repo}", str(tree)) for arg in _CENSUS_VARIANTS[census_id]]
        unvalued = [arg for arg in argv if arg.startswith("<no census")]
        assert not unvalued, (
            f"{census_id}: {unvalued}. Give the positional a value in _CENSUS_VALUES, teach "
            "_census_variants the action, or give the command a reason in _CENSUS_NOT_RUN")
        try:
            args = build_parser().parse_args(argv)
        except SystemExit:
            pytest.fail(f"{census_id}: the parser refused {argv}. Give its positionals a value "
                        "in _CENSUS_VALUES, or the command a reason in _CENSUS_NOT_RUN")
        monkeypatch.chdir(tree)
        head = _census_head(tree)
        capsys.readouterr()
        try:
            rc = args.func(args)
        except SystemExit as exc:
            rc = exc.code
        captured = capsys.readouterr()
        out = captured.out + captured.err
        if _census_refusal(census_id) is not None:
            assert rc not in (0, None), (
                f"{census_id} now exits 0 on the census tree; drop its _CENSUS_REFUSES "
                "entry so the census holds the run it now makes")
        else:
            assert rc in (0, None), (
                f"`espalier {census_id}` exited {rc!r} on the census tree, so it may never "
                "have reached its write. Give the census tree the state it needs, or say "
                "why in _CENSUS_REFUSES. Output:\n" + out[-1500:])
        changed = set(_census_changed(tree))
        if _census_head(tree) != head:  # a command that commits its own write
            changed |= set(_census_committed(tree, head))
        self_host = surface_contract.is_self_host_repo(tree)
        gated = sorted(rel for rel in changed
                       if surface_contract.is_protected_from_ci(rel, self_host=self_host))
        if census_id in _CENSUS_FLOOR:
            assert gated, (
                f"{census_id} changed no gated path on the census tree, so the census no "
                "longer gives the writers it exists for anything to write")
        if gated:
            assert ("refuses the commit carrying" in out
                    and f"{_MARKER} in the HEAD commit message" in out
                    and f"{_MARKER}@<sha> in the title" in out), (
                f"`espalier {census_id}` changed {gated}, which the Harness Guard gates and "
                "git will commit, and did not print the approval-marker clause "
                "(espalier/cli.py::_approval_marker_lines). Output:\n" + out[-2000:])
            # The sibling roster: a command that rewrites a protected file
            # records its writes for the session's zone check
            # (tests/test_zone_writes.py::TestOnlyTheWritersAreBracketed).
            assert getattr(args, "zone_writer", False), (
                f"`espalier {census_id}` changed {gated} and its parser does not set "
                "zone_writer=True, so a session watching the tree reports the write back")

    def test_the_census_tables_name_only_what_the_parser_has(self):
        """Both ways: a reason or a value for something the parser no longer
        has would excuse nothing while reading as coverage."""
        leaves = {" ".join(path) for path, _ in _census_leaves()}
        positionals = {action.dest for _, parser in _census_leaves()
                       for action in parser._actions if not action.option_strings}
        assert set(_CENSUS_NOT_RUN) <= leaves, set(_CENSUS_NOT_RUN) - leaves
        assert all(reason.strip() for reason in _CENSUS_NOT_RUN.values())
        assert set(_CENSUS_VALUES) <= positionals, set(_CENSUS_VALUES) - positionals
        assert set(_CENSUS_FLOOR) <= set(_CENSUS_VARIANTS), set(_CENSUS_FLOOR) - set(_CENSUS_VARIANTS)
        refused = {key.removesuffix(" *") for key in _CENSUS_REFUSES}
        assert refused <= set(_CENSUS_VARIANTS), refused - set(_CENSUS_VARIANTS)
        assert not {cid for cid in _CENSUS_FLOOR if _census_refusal(cid)}, (
            "a floor writer cannot be excused")
        assert all(reason.strip() for reason in _CENSUS_REFUSES.values())

    def test_no_command_group_runs_on_its_own(self):
        """The census runs leaves. A group with subcommands that also runs by
        itself (a default ``func``) would be a command it never runs."""
        import argparse

        from espalier.cli import build_parser

        def groups(parser, path=()):
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, sub in action.choices.items():
                        yield (*path, name), sub
                        yield from groups(sub, (*path, name))

        runnable = [" ".join(path) for path, sub in groups(build_parser())
                    if any(isinstance(a, argparse._SubParsersAction) for a in sub._actions)
                    and sub.get_default("func") is not None]
        assert not runnable, runnable


def _fake_pid(proc: Path, pid: str, argv: list[str], *, cwd: "str | None" = None,
              fds: tuple[str, ...] = ()) -> None:
    """One ``/proc/<pid>`` entry in a fake process table: its command line,
    and its cwd and open files as the links Linux shows."""
    entry = proc / pid
    (entry / "fd").mkdir(parents=True)
    (entry / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
    if cwd is not None:
        os.symlink(cwd, entry / "cwd")
    for n, target in enumerate(fds):
        os.symlink(target, entry / "fd" / str(n + 3))


class TestACensusCopyThatFailsNamesWhatMovedItsSource:
    """The census tree's copy failed in CI with whole object folders gone
    from the source mid-copy, and the red named only the files that
    vanished. The writer measured since is git's own detached maintenance
    after each fixture commit, DEF-1168's writer, which ``_marker_tree`` now
    shuts off as conftest's ``initialized_repo_root`` does. The report these
    pin is what a recurrence prints, so it names a writer outside the
    fixture: a new pack is a gc, missing folders and no pack a removal, and a
    process naming the tree is named by pid."""

    def test_a_marker_tree_commit_spawns_no_background_git(self, tmp_path, monkeypatch):
        """Dies to: the three keys dropped after `git init` (each commit
        spawns `git maintenance run --auto`, which repacks when it has work).
        GIT_TRACE is the oracle DEF-1168 pinned."""
        for var in ("CLAUDECODE", "CLAUDE_PROJECT_DIR"):
            monkeypatch.delenv(var, raising=False)
        tree = _marker_tree(tmp_path, guard=False)
        (tree / "f").write_text("x\n", encoding="utf-8")
        _git_q(tree, "add", "f")
        traced = subprocess.run(
            ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "f"],
            capture_output=True, text=True, encoding="utf-8", env={**os.environ, "GIT_TRACE": "1"},
            check=True)
        assert "built-in: git commit" in traced.stderr, traced.stderr  # the trace was captured
        spawned = [line for line in traced.stderr.splitlines() if "run_command" in line]
        assert not [line for line in spawned if "maintenance" in line or " gc" in line], spawned

    def test_the_keys_are_def_1168s_three(self):
        """Dies to: a key dropped from the tuple (every site's pin compares with
        the tuple, so it would pass; with `gc.auto 0` and `gc.autoDetach
        false` alone, a commit still spawns `maintenance run --auto`)."""
        assert NO_BACKGROUND_GIT == (("gc.auto", "0"), ("gc.autoDetach", "false"),
                                     ("maintenance.auto", "false"))

    def test_the_first_site_reads_its_keys_back(self, initialized_repo_root):
        """Dies to: the keys dropped from conftest's initialized_repo_root build
        (DEF-1168's own site, whose tree several tests copy with its .git)."""
        assert background_git_settings(initialized_repo_root) == dict(NO_BACKGROUND_GIT)

    def test_the_read_back_ignores_an_exported_git_dir(self, tmp_path, monkeypatch):
        """Dies to: the reader keeping git's repo-selecting overrides (under
        `git rebase --exec pytest` an exported GIT_DIR outranks `-C`, and every
        pin would read the outer repository instead)."""
        outer, tree = tmp_path / "outer", tmp_path / "t"
        for repo in (outer, tree):
            repo.mkdir()
            _git_q(repo, "init", "-q")
        for key, value in NO_BACKGROUND_GIT:
            _git_q(tree, "config", key, value)
        monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
        assert background_git_settings(tree) == dict(NO_BACKGROUND_GIT)

    def test_the_maintenance_lock_is_reported(self, tmp_path):
        """Dies to: the objects/ lock left unread (`git maintenance run` holds
        `objects/maintenance.lock` while it works: the writer's own witness)."""
        tree = tmp_path / "census0" / "t"
        (tree / ".git" / "objects").mkdir(parents=True)
        (tree / ".git" / "objects" / "maintenance.lock").write_text("", encoding="utf-8")
        report = _census_copy_failed(tree, proc=tmp_path / "no-proc")
        assert "*.lock in .git: objects/maintenance.lock" in report, report

    def test_the_census_tree_records_its_store_at_build(self, census_tree):
        """Dies to: the build record dropped (a report could not say what
        moved since the fixture left the tree)."""
        built = _CENSUS_BUILT.get(str(census_tree), "")
        assert built.startswith("objects/pack: no pack; loose objects: "), built
        assert built == _object_store(census_tree), (built, _object_store(census_tree))

    def test_a_repacked_tree_shows_its_pack_beside_its_build(self, tmp_path):
        """Dies to: the pack listing dropped (a gc in the source would read as
        nothing found), or a pack folder counted as loose objects."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        _git_q(tree, "init", "-q")
        (tree / "f").write_text("x\n", encoding="utf-8")
        _git_q(tree, "add", "f")
        _git_q(tree, "commit", "-qm", "one")
        built = _object_store(tree)
        _git_q(tree, "gc", "-q")
        report = _census_copy_failed(tree, proc=tmp_path / "no-proc", built=built)
        assert f"at build: {built}" in report and "objects/pack: no pack" in built, report
        now = next(line for line in report.splitlines() if line.startswith("  now:"))
        assert ".pack" in now and "loose objects: 0 in 0 folders" in now, report

    @pytest.mark.skipif(sys.platform == "win32" or not hasattr(os, "geteuid") or os.geteuid() == 0,
                        reason="a folder made unlistable by its mode, which Windows and root ignore")
    def test_an_unlistable_folder_keeps_the_pack_line(self, tmp_path):
        """Dies to: the pack and the loose count read under one handler (a gc
        still clearing folders as the report reads them hides the pack, the
        evidence that it ran)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        _git_q(tree, "init", "-q")
        (tree / "f").write_text("x\n", encoding="utf-8")
        _git_q(tree, "add", "f")
        _git_q(tree, "commit", "-qm", "one")
        _git_q(tree, "gc", "-q")
        shut = tree / ".git" / "objects" / "ab"
        shut.mkdir()
        shut.chmod(0)
        try:
            store = _object_store(tree)
        finally:
            shut.chmod(0o755)
        assert ".pack" in store and "1 unreadable" in store, store

    def test_a_removed_tree_reads_gone(self, tmp_path):
        """Dies to: the presence check dropped (a removal would read as a tree
        that is there)."""
        report = _census_copy_failed(tmp_path / "census0" / "t", proc=tmp_path / "no-proc")
        assert report.splitlines()[0].endswith(" is GONE"), report
        assert "now:      objects/ is GONE" in report, report

    def test_a_process_whose_command_names_the_tree_is_named(self, tmp_path):
        """Dies to: the command-line read dropped (a `git -C <tree>` run from
        elsewhere would go unnamed)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "4242", ["git", "-C", str(tree), "gc"])
        _fake_pid(proc, "4243", ["sleep", "30"])
        (proc / "self").mkdir()
        report = _census_copy_failed(tree, proc=proc)
        assert f"pid 4242: git -C {tree} gc" in report and "pid 4243" not in report, report

    def test_a_removal_through_the_folder_holding_the_tree_is_named(self, tmp_path):
        """Dies to: the match narrowed to the tree itself (a removal of the
        fixture's folder takes the tree with it, naming only the folder)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "88", ["rm", "-r", str(tree.parent)])
        assert "pid 88: rm -r" in _census_copy_failed(tree, proc=proc)

    def test_a_sibling_whose_name_extends_the_folder_is_not_named(self, tmp_path):
        """Dies to: a prefix match without the separator (`census0x` would
        read as the census tree's folder)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "99", ["git", "-C", f"{tree.parent}x", "gc"])
        report = _census_copy_failed(tree, proc=proc)
        assert "pid 99" not in report and "none of 1 pids" in report, report

    @pytest.mark.skipif(sys.platform == "win32", reason="a /proc cwd entry is a symlink")
    def test_a_process_working_in_the_tree_is_named(self, tmp_path):
        """Dies to: the cwd read dropped (git's detached `maintenance run
        --auto` names no path on its command line; its working directory is
        the tree)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "77", ["git", "maintenance", "run", "--auto"], cwd=str(tree))
        assert "pid 77: git maintenance run --auto" in _census_copy_failed(tree, proc=proc)

    @pytest.mark.skipif(sys.platform == "win32", reason="a /proc cwd entry is a symlink")
    def test_a_process_working_in_the_removed_tree_is_named(self, tmp_path):
        """Dies to: the ` (deleted)` suffix kept (Linux marks the cwd of a
        process whose folder was removed, and a process working in the
        fixture's own folder when it went is the remover's best witness)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "66", ["python3", "-c", "x"], cwd=f"{tree.parent} (deleted)")
        assert "pid 66: python3" in _census_copy_failed(tree, proc=proc)

    @pytest.mark.skipif(sys.platform == "win32", reason="a /proc fd entry is a symlink")
    def test_a_process_holding_a_file_in_the_tree_is_named(self, tmp_path):
        """Dies to: the open files left unread (a pack writer holds its
        `tmp_pack_*` open however its command line spells the path)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "55", ["git", "pack-objects"], cwd="/",
                  fds=("/dev/null", str(tree / ".git" / "objects" / "pack" / "tmp_pack_x")))
        assert "pid 55: git pack-objects" in _census_copy_failed(tree, proc=proc)

    def test_none_says_what_it_read_and_could_not(self, tmp_path):
        """Dies to: an unqualified 'none' (a process whose cwd could not be
        read, or that exited before the read, would read as an all-clear)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        proc = tmp_path / "proc"
        _fake_pid(proc, "11", ["bash"])
        report = _census_copy_failed(tree, proc=proc)
        assert "none of 1 pids (1 with an unreadable cwd; a process that exited" in report, report

    def test_no_proc_says_the_processes_went_unread(self, tmp_path):
        """Dies to: a missing /proc read as no process found (macOS and
        Windows have none, so silence there would be a false all-clear)."""
        tree = tmp_path / "census0" / "t"
        tree.mkdir(parents=True)
        report = _census_copy_failed(tree, proc=tmp_path / "no-proc")
        assert "processes unread" in report and "processes naming the tree" not in report, report

    def test_a_failed_copy_fails_the_run_with_the_report(self, tmp_path, monkeypatch):
        """Dies to: the copy's handler dropped (the run reds on the bare
        shutil.Error, which names only the files that vanished)."""
        import shutil

        def vanished(src, dst, **kwargs):
            raise shutil.Error([(str(src), str(dst), "[Errno 2] No such file or directory")])

        monkeypatch.setattr(shutil, "copytree", vanished)
        with pytest.raises(pytest.fail.Exception, match="what its source looks like now") as caught:
            _census_copy(tmp_path / "census0" / "t", tmp_path / "copy")
        assert "(Error, 1 entries, the error above)" in str(caught.value), caught.value
        assert " is GONE" in str(caught.value), caught.value


class TestTheSelfHostPinRefreshNamesTheMarker:
    """`_refresh-self-host-pin` refuses on an adopter tree, so the census sees
    it exit 2 and never write. On this repository it rewrites three pin
    carriers under tools/cc/ and espalier/, which the Harness Guard gates
    here, so it is held on a clone of this repository instead (DEF-3002)."""

    def test_the_refresh_names_the_marker_exactly_when_it_moves_the_pin(
        self, tmp_path, capsys, monkeypatch,
    ):
        import argparse

        from espalier import cli, surface_contract
        from tests._git_oracle import owns_its_worktree

        if not owns_its_worktree(REPO_ROOT):
            pytest.skip("needs this repository's own history to clone")
        clone = tmp_path / "self-host"
        subprocess.run(["git", "clone", "-q", "--shared", str(REPO_ROOT), str(clone)],
                       check=True, capture_output=True)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        refresh = argparse.Namespace(repo=str(clone))

        # The pin is current at HEAD: the carriers are rewritten byte for byte,
        # nothing reaches a commit, and the clause stays quiet.
        capsys.readouterr()
        assert cli.cmd_refresh_self_host_pin(refresh) == 0
        assert _census_changed(clone) == []
        assert _MARKER not in capsys.readouterr().out

        # Inside the pinned 200 bytes: the refresh moves the pin in every carrier.
        guard = clone / "tools" / "cc" / "hooks" / "write_guard.py"
        guard.write_bytes(guard.read_bytes().replace(b"friction layer", b"friction  layer", 1))
        _git_q(clone, "commit", "-qam", "move the pinned prefix")
        assert cli.cmd_refresh_self_host_pin(refresh) == 0
        out = capsys.readouterr().out
        self_host = surface_contract.is_self_host_repo(clone)
        gated = sorted(rel for rel in _census_changed(clone)
                       if surface_contract.is_protected_from_ci(rel, self_host=self_host))
        gated_carriers = sorted(rel for rel in cli.SELF_HOST_PIN_CARRIERS
                                if surface_contract.is_protected_from_ci(rel, self_host=self_host))
        assert gated_carriers and gated == gated_carriers, (gated, gated_carriers)
        assert "refuses the commit carrying" in out and f"{_MARKER}@<sha> in the title" in out, out


# ── TP-473 1-C: a self-host-only block is stripped at deploy, off this tree ───


_FENCED = (
    "---\nname: x\n---\n"
    "keep 1\n"
    "<!-- espalier:self-host-only -->\n"
    "python scripts/proof_tier.py --run\n"
    "<!-- /espalier:self-host-only -->\n"
    "keep 2\n"
    "// <!-- espalier:self-host-only -->\n"
    "// SoT: espalier/fan_out_findings.py\n"
    "// <!-- /espalier:self-host-only -->\n"
    "keep 3\n"
)


class TestSelfHostBlocksStripAtDeploy:
    """A ``.claude`` body fences this repository's own procedure between the
    two ``espalier:self-host-only`` markers; ``init`` strips the block on every
    other tree and this repository's sessions keep it, so the mirrors stay
    byte-equal to their source."""

    def test_the_strip_takes_each_block_with_its_marker_lines(self):
        from espalier.surface_hygiene import strip_self_host_blocks as _strip_self_host_blocks
        assert _strip_self_host_blocks(_FENCED) == "---\nname: x\n---\nkeep 1\nkeep 2\nkeep 3\n"

    def test_an_unclosed_block_strips_nothing(self):
        from espalier.surface_hygiene import strip_self_host_blocks as _strip_self_host_blocks
        body = "a\n<!-- espalier:self-host-only -->\nb\n"
        assert _strip_self_host_blocks(body) == body

    def test_a_stray_opener_above_a_block_takes_nothing_with_it(self):
        """A stray opener must not pair with the NEXT block's closer and take the
        adopter text between them (the first cut's DOTALL body did: review)."""
        from espalier.surface_hygiene import strip_self_host_blocks as _strip_self_host_blocks
        body = ("a\n<!-- espalier:self-host-only -->\nKEEP\nmid\n"
                "<!-- espalier:self-host-only -->\nx\n<!-- /espalier:self-host-only -->\nafter\n")
        assert _strip_self_host_blocks(body) == "a\n<!-- espalier:self-host-only -->\nKEEP\nmid\nafter\n"

    def test_a_block_at_the_end_of_a_body_without_a_newline_goes(self):
        from espalier.surface_hygiene import strip_self_host_blocks as _strip_self_host_blocks
        body = "a\n<!-- espalier:self-host-only -->\nb\n<!-- /espalier:self-host-only -->"
        assert _strip_self_host_blocks(body) == "a\n"

    def test_the_strip_is_idempotent(self):
        from espalier.surface_hygiene import strip_self_host_blocks as _strip_self_host_blocks
        once = _strip_self_host_blocks(_FENCED)
        assert _strip_self_host_blocks(once) == once

    def test_off_this_tree_a_body_is_stripped_and_on_it_none_is(self, tmp_path):
        from espalier.cli import _asset_transform
        off = _asset_transform(".claude/commands/x.md", [], tmp_path)
        assert off is not None and "proof_tier" not in off(_FENCED)
        assert _asset_transform(".claude/commands/x.md", [], REPO_ROOT) is None

    def test_a_runner_agent_takes_both_renders(self, tmp_path):
        from espalier.cli import _asset_transform
        from espalier.harness_config import RUNNER_AGENT_PATHS
        rel = sorted(RUNNER_AGENT_PATHS)[0]
        body = "---\nname: x\ntools: Read, Bash(git *)\n---\n" + _FENCED.split("---\n", 2)[2]
        rendered = _asset_transform(rel, ["npm test"], tmp_path)(body)
        assert "proof_tier" not in rendered and "npm test" in rendered, rendered

    def test_a_fusion_built_with_init_off_strips_too(self, tmp_path):
        """fuse's overlay marks the bodies init did not deploy; with init off that
        is every body, and it shipped them unstripped (review)."""
        from espalier.fuse import _mark_overlaid_md
        from espalier.managed_markers import has_managed_marker
        dst = tmp_path / "x.md"
        dst.write_bytes(_FENCED.encode("utf-8"))
        _mark_overlaid_md(dst)
        text = dst.read_text(encoding="utf-8")
        assert "proof_tier" not in text and "self-host-only" not in text, text
        assert has_managed_marker(text)

    def test_every_workflow_an_adopter_receives_is_a_valid_function_body(self, tmp_path):
        """The strip removes whole lines from a .js workflow, so a fence around a
        code line would leave the adopter's copy unparseable while the source
        parses -- the silently absent slash command (review). The oracle
        tests/test_finding_ledger.py runs over the source, run over the render."""
        import shutil
        from espalier.cli import _asset_transform, _packaged_md_assets
        node = shutil.which("node")
        if not node:
            pytest.skip("node not installed")
        probe = (
            "const fs=require('fs');"
            "const src=fs.readFileSync(process.argv[1],'utf8').replace(/^export /mg,'');"
            "new (Object.getPrototypeOf(async function(){}).constructor)(src);"
        )
        workflows = [(rel, src) for rel, src in _packaged_md_assets(REPO_ROOT) if rel.endswith(".js")]
        assert len(workflows) >= 3, workflows
        for rel, src in workflows:
            out = tmp_path / Path(rel).name
            out.write_bytes(_asset_transform(rel, [], tmp_path)(src.read_text(encoding="utf-8")).encode("utf-8"))
            r = subprocess.run([node, "-e", probe, str(out)], capture_output=True, text=True,
                               timeout=45, encoding="utf-8")
            assert r.returncode == 0, (rel, r.stderr[-400:])

    def test_a_fenced_body_deploys_once_and_then_reads_as_current(self, tmp_path):
        """The refutation the pack names: if the adopter's body read as drifted
        after every init, the strip would not be idempotent through the deploy's
        own no-drift compare. Deploy, re-deploy, then the upgrade preview's dry run."""
        from espalier.cli import _asset_transform, _deploy_asset_md
        src = tmp_path / "src" / "x.md"
        src.parent.mkdir()
        src.write_bytes(_FENCED.encode("utf-8"))
        tree = tmp_path / "tree"
        tree.mkdir()
        rel = ".claude/commands/x.md"
        dest = tree / rel
        assert _deploy_asset_md(src, dest, transform=_asset_transform(rel, [], tree)) == "created"
        written = dest.read_text(encoding="utf-8")
        assert "self-host-only" not in written and "proof_tier" not in written, written
        assert _deploy_asset_md(src, dest, transform=_asset_transform(rel, [], tree)) == "skipped_no_drift"
        assert _deploy_asset_md(
            src, dest, dry_run=True, transform=_asset_transform(rel, ["pytest -q"], tree),
        ) == "skipped_no_drift"


# ── DEF-988: /implement-pack retires a pack into the tree's own folder ────────


class TestImplementPackRetiresIntoTheTreesOwnFolder:
    """Step 12 used to name ``task-packs/Done/`` as a literal, so an adopter whose
    finished packs live in ``done/`` got a second folder -- and on a case-insensitive
    filesystem the move landed in ``done/`` on disk while the index recorded
    ``Done/``. The deployed body now derives the folder; this drives the body's own
    probe, as an adopter receives it, against trees shaped like theirs."""

    _BODY = REPO_ROOT / "espalier" / "assets" / "claude" / "commands" / "implement-pack.md"

    def _probe(self, tmp_path) -> str:
        from espalier.cli import _asset_transform
        body = _asset_transform(".claude/commands/implement-pack.md", [], tmp_path)(
            self._BODY.read_text(encoding="utf-8"))
        lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("p='<pack-path>';")]
        assert len(lines) == 1, "step 12's retirement-folder probe is gone or doubled"
        return lines[0]

    def _retired(self, tmp_path, tree: Path, pack: str) -> str:
        import shutil
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("no bash on PATH; the probe is a POSIX shell line")
        script = self._probe(tmp_path).replace("<pack-path>", pack)
        out = subprocess.run([bash, "-c", script], cwd=tree, capture_output=True, text=True,
                             encoding="utf-8", timeout=30, check=True)
        return out.stdout.strip()

    def _tree(self, tmp_path, *files: str) -> Path:
        tree = tmp_path / "tree"
        for rel in files:
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / rel).write_bytes(b"x\n")
        return tree

    def test_an_existing_lowercase_done_folder_wins(self, tmp_path):
        tree = self._tree(tmp_path, "task-packs/done/TP-1-old.md", "task-packs/TP-2-new.md")
        assert self._retired(tmp_path, tree, "task-packs/TP-2-new.md") == "task-packs/done"

    def test_drafts_retire_beside_their_folder(self, tmp_path):
        """The probelab shape the row was found on: drafts under ``drafts/``,
        finished packs under ``done/`` beside it."""
        tree = self._tree(tmp_path, "task-packs/done/TP-80-old.md", "task-packs/drafts/TP-81_new.md")
        assert self._retired(tmp_path, tree, "task-packs/drafts/TP-81_new.md") == "task-packs/done"

    def test_the_folder_is_read_under_its_own_spelling(self, tmp_path):
        """On a case-insensitive filesystem ``done`` answers for ``Done``; the probe
        must still print the spelling on disk, or the index and the disk split."""
        tree = self._tree(tmp_path, "task-packs/Done/TP-1-old.md", "task-packs/TP-2-new.md")
        assert self._retired(tmp_path, tree, "task-packs/TP-2-new.md") == "task-packs/Done"

    def test_a_folder_without_packs_is_not_a_retirement_folder(self, tmp_path):
        tree = self._tree(tmp_path, "task-packs/archive/notes.txt", "task-packs/TP-2-new.md")
        assert self._retired(tmp_path, tree, "task-packs/TP-2-new.md") == "task-packs/Done"

    def test_a_fresh_tree_defaults_to_done(self, tmp_path):
        tree = self._tree(tmp_path, "task-packs/TP-2-new.md")
        assert self._retired(tmp_path, tree, "task-packs/TP-2-new.md") == "task-packs/Done"

    def test_a_pack_path_with_a_space_is_read_whole(self, tmp_path):
        tree = self._tree(tmp_path, "task packs/done/TP-1-old.md", "task packs/TP-2-new.md")
        assert self._retired(tmp_path, tree, "task packs/TP-2-new.md") == "task packs/done"

    def test_a_folder_at_the_repository_root_is_not_the_packs(self, tmp_path):
        """Climbing one level is for drafts beside their done folder; for a pack
        under task-packs/ it would reach the repository root (review)."""
        tree = self._tree(tmp_path, "archive/TP-9-elsewhere.md", "task-packs/TP-2-new.md")
        assert self._retired(tmp_path, tree, "task-packs/TP-2-new.md") == "task-packs/Done"


# ── DEF-1082, DEF-1187: the root CLAUDE.md says what is true of its tree ──────


def _canonical_claude_md(root=None) -> str:
    from espalier.cli import (
        _build_claude_md, _canonical_template_build_plan, _canonical_template_fingerprint,
    )
    return _build_claude_md(_canonical_template_fingerprint(), _canonical_template_build_plan(), root=root)


def _git_tree(tmp_path: Path, *, track_settings: bool) -> Path:
    tree = tmp_path / "tree"
    (tree / ".claude").mkdir(parents=True)
    (tree / "app.txt").write_bytes(b"x\n")
    (tree / ".claude" / "settings.json").write_bytes(b"{}\n")
    _git_q(tree, "init", "-q")
    _git_q(tree, "add", "app.txt", *((".claude/settings.json",) if track_settings else ()))
    _git_q(tree, "commit", "-qm", "initial")
    return tree


class TestTheRootClaudeMdSaysWhatIsTrueOfItsTree:
    """The template said "CI guarantees" and "...and CI" on every tree, while
    plain init installs no CI gate; it said settings.json does not travel with a
    clone on a repository that tracks it; and it handed every adopter the
    harness's own hook-authoring rules. It is written once and kept, so its CI
    sentence is the one true in both states; the other two read the tree."""

    def test_the_ci_sentence_promises_nothing_this_tree_lacks(self):
        from espalier.render_surface import CI_RECHECK_SENTENCE
        text = _canonical_claude_md()
        assert CI_RECHECK_SENTENCE in text
        assert "CI guarantees" not in text and "`post_write_check`, and CI." not in text

    def test_a_tracked_settings_file_travels_with_a_clone(self, tmp_path):
        text = _canonical_claude_md(_git_tree(tmp_path, track_settings=True))
        assert "which this repository\n> tracks, so the wiring travels with a clone" in text, text
        assert "does NOT travel with a clone" not in text

    def test_an_ignored_settings_file_does_not(self, tmp_path):
        text = _canonical_claude_md(_git_tree(tmp_path, track_settings=False))
        assert "does NOT travel with a clone" in text
        assert "travels with a clone" not in text

    def test_the_hook_authoring_rules_render_on_the_harness_tree_only(self, tmp_path):
        assert "## Architecture Rules" not in _canonical_claude_md()
        assert "## Architecture Rules" not in _canonical_claude_md(tmp_path)
        assert "## Architecture Rules" in _canonical_claude_md(REPO_ROOT)

    def test_doctor_still_counts_the_section_init_once_wrote_everywhere(self):
        """A tree installed while init wrote the section on every tree still holds
        it as init's; doctor's recall row must keep naming it (review)."""
        from espalier.doctor import _generated_claude_headings
        assert "Architecture Rules" in _generated_claude_headings()


class TestRenderTemplateRendersForTheTreeItRunsIn:
    """DEF-1187: init's NOTE sends an adopter with a CLAUDE.md of their own to
    copy sections from `render-template claude`, which rendered a fixed
    fingerprint and so told a Node tree its languages were Python. It renders
    the tree's saved fingerprint now; `--canonical` keeps the fixed one."""

    @staticmethod
    def _node_tree(tmp_path: Path) -> Path:
        import json
        from espalier.analyze import fingerprint_repo
        tree = tmp_path / "node"
        (tree / "src").mkdir(parents=True)
        (tree / "package.json").write_bytes(b'{"name": "n", "scripts": {"test": "node --test"}}\n')
        (tree / "src" / "index.js").write_bytes(b"export const x = 1;\n")
        fp = fingerprint_repo(tree)
        (tree / "reports").mkdir()
        (tree / "reports" / "repo_fingerprint.json").write_bytes(json.dumps(fp.to_dict()).encode("utf-8"))
        return tree

    @staticmethod
    def _render(tree: Path, monkeypatch, capsys, *, canonical: bool) -> str:
        import argparse
        from espalier.cli import cmd_render_template
        monkeypatch.chdir(tree)
        capsys.readouterr()
        assert cmd_render_template(argparse.Namespace(subject="claude", canonical=canonical)) == 0
        return capsys.readouterr().out

    @staticmethod
    def _languages(text: str) -> str:
        return next(ln for ln in text.splitlines() if ln.startswith("- **Languages:**"))

    def test_a_node_tree_is_not_described_as_python(self, tmp_path, monkeypatch, capsys):
        line = self._languages(self._render(self._node_tree(tmp_path), monkeypatch, capsys, canonical=False))
        assert "python" not in line.lower() and line != "- **Languages:** unknown", line

    def test_canonical_keeps_the_fixed_render(self, tmp_path, monkeypatch, capsys):
        line = self._languages(self._render(self._node_tree(tmp_path), monkeypatch, capsys, canonical=True))
        assert "python" in line.lower(), line

    def test_a_tree_with_no_saved_fingerprint_gets_the_canonical_render(self, tmp_path, monkeypatch, capsys):
        from espalier.cli import render_canonical_template
        assert self._render(tmp_path, monkeypatch, capsys, canonical=False) == render_canonical_template("claude")
