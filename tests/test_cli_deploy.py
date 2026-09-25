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
            preview_managed_surface(tmp_path)
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
    predicted = preview_managed_surface(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "a preview wrote to the tree"
    for key in ("updated_managed", "skipped_user_files", "skipped_no_drift", "source_missing"):
        assert predicted[key] == [], (key, predicted[key])

    fp = fingerprint_repo(tmp_path)
    plan = BuildPlan(repo_name="x", profiles=["ci_cd"])
    first = deploy_harness(tmp_path, plan, fp)
    assert set(predicted["created"]) == set(first["deployed"]), (
        "the preview and the deploy disagree about what an empty tree gets"
    )

    after = preview_managed_surface(tmp_path)
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
    predicted = preview_managed_surface(tmp_path)
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
    tally = preview_managed_surface(tmp_path)
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
