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
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

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
        capture_output=True, text=True, timeout=120, check=True, encoding="utf-8",
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
        tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "deploy_harness":
                source_segment = ast.get_source_segment(
                    CLI_PATH.read_text(encoding="utf-8"), node,
                ) or ""
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
        # At the pytest cap (60 s), not above it: a larger subprocess timeout
        # can never fire and joins the DEF-665 count for nothing.
        dry = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "init", str(target), "--dry-run"],
            capture_output=True, text=True, timeout=60, check=True, encoding="utf-8",
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
        goal = _deployed_current_tree(tmp_path) / "cc" / "GOAL.md"
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
    assert "of the 'workflow' profile" in out and "Bash(python3 -m pytest *)" in out
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
    rule = "Bash(python3 -m pytest *)"
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
        capture_output=True, text=True, timeout=180, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    plan = json.loads((target / "reports" / "harness_config.json").read_text(encoding="utf-8"))
    assert plan["settings_profile"] == "minimal"
    assert installed_settings_profile(target) == "minimal"
    refresh = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "fingerprint", str(target)],
        capture_output=True, text=True, timeout=180, encoding="utf-8",
    )
    assert refresh.returncode == 0, refresh.stderr
    assert installed_settings_profile(target) == "minimal", "a report rebuild forgot the profile"


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
        checker; a ``"``, ``$``, backtick or newline in a row's code would split
        it wrong, reading UNRESOLVED at best (code review, 2026-09-30)."""
        import shlex

        from espalier.cli import _ONBOARDING_ROWS, _PROBE_PY

        for row in _ONBOARDING_ROWS:
            if "code" not in row:
                continue
            argv = shlex.split(f'{_PROBE_PY} -c "{row["code"]}"')
            assert argv[:2] == [_PROBE_PY, "-c"] and argv[2] == row["code"], row["id"]
            compile(argv[2], row["id"], "exec")

    @pytest.mark.parametrize("rid,key", [("ONB-1", "goal_snapshot = false"),
                                         ("ONB-6", 'plan_exempt_prefixes = ["src/"]')])
    def test_a_key_under_a_table_leaves_its_row_open(self, tmp_path, rid, key):
        """TOML files every key below a ``[table]`` header INTO that table, so a
        key an adopter appends after ``[extra_actions]`` is not the engine's
        top-level key -- and the row must stay open. The same key above the
        table closes it (failure-mode review, 2026-09-30)."""
        from espalier.cli import _ONBOARDING_ROWS

        code = next(r["code"] for r in _ONBOARDING_ROWS if r["id"] == rid)
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "GOAL.md").write_text("(not set -- x)\n", encoding="utf-8")

        def prints(toml: str) -> str:
            (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
            return subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60).stdout.strip()

        assert prints(f'[extra_actions]\ntest = ["make"]\n{key}\n') == "True"
        assert prints(f'{key}\n\n[extra_actions]\ntest = ["make"]\n') == "False"

    def test_the_upgrade_preview_names_the_filing_only_where_an_install_would_file(self, tmp_path):
        from espalier.cli import _deploy_seed_docs, _onboarding_would_file

        assert _onboarding_would_file(tmp_path)          # absent: the seed would be created
        (tmp_path / ".git").mkdir()
        _deploy_seed_docs(tmp_path)
        assert _onboarding_would_file(tmp_path)          # the untouched seed
        ledger = tmp_path / "task-packs" / "FORWARD_LEDGER.md"
        ledger.write_text(ledger.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8")
        assert not _onboarding_would_file(tmp_path)      # edited: never refiled

    def test_every_row_has_a_probe_or_a_reason_and_a_seeded_section(self):
        import re

        from espalier.cli import _ONBOARDING_ROWS

        seed = (REPO_ROOT / "espalier" / "assets" / "seed" / "FORWARD_LEDGER.md").read_text(encoding="utf-8")
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
_ENGINE_FILES = sorted((REPO_ROOT / "espalier").glob("*.py"))  # the top-level package only


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
        capture_output=True, text=True, timeout=60, check=True, encoding="utf-8",
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
