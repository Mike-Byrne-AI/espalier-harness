"""Unit tests for espalier/selfcheck.py — the TP-226b adopter-side contracts.

Covers the three live/parity contracts and their earn-the-red discriminators:
  * C-1 LIVE DENY-PATH    — the deployed write_guard still DENIES the three core
                            bypass classes; a stubbed allow-everything hook reds.
  * C-2 UPSTREAM PARITY   — deployed hooks byte-match the installed package; a
                            one-byte drift reds; a source-checkout (no vendor
                            dir) skips cleanly.
  * C-3 LIVE KILL-SWITCH  — no kill-switch in the LIVE settings; disableAllHooks
                            / bypassPermissions red; the marker set is parity-
                            pinned against the deployed _integrity SoT.

Tests build synthetic tmp_path repos (or point at the real REPO_ROOT, whose own
deployed hook already denies and whose vendor tree already matches). The
aggregate entry point is run_contracts (run_selfcheck is the TP-226c mirror-test
runner, a separate surface).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from espalier import selfcheck

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


# ── C-1: live deny-path ──────────────────────────────────────────────────────

def test_c1_passes_against_real_deployed_hook():
    """The repo's own deployed write_guard denies all three bypass classes."""
    result = selfcheck.check_live_deny_path(REPO_ROOT)
    assert result.passed, f"C-1 failed against the real deployed hook: {result.failures}"


_STUB_ALLOW_HOOK = "import sys\nsys.exit(0)\n"  # prints nothing, never denies


def test_c1_red_when_hook_stubbed_to_allow(tmp_path):
    """EARN-THE-RED: a write_guard stubbed to allow-everything reds C-1, and all
    three bypass classes appear in the failures."""
    hooks = tmp_path / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "write_guard.py").write_text(_STUB_ALLOW_HOOK, encoding="utf-8")

    result = selfcheck.check_live_deny_path(tmp_path)
    assert not result.passed
    joined = " | ".join(result.failures)
    assert "protected-zone write" in joined
    assert "dangerous bash" in joined
    assert "kill-switch" in joined


def test_c1_red_when_hook_missing(tmp_path):
    """No deployed hook at all reds C-1 with a 'missing' failure."""
    result = selfcheck.check_live_deny_path(tmp_path)
    assert not result.passed
    assert any("missing" in f for f in result.failures)


# ── C-2: upstream parity ──────────────────────────────────────────────────────

def test_c2_passes_on_synced_tree():
    """REPO_ROOT's deployed hooks byte-match the installed package (the repo's
    own test_vendor_cc_parity already guarantees this)."""
    result = selfcheck.check_upstream_parity(REPO_ROOT)
    assert result.passed, f"C-2 failed on the synced self-host tree: {result.failures}"


def test_c2_red_on_byte_drift(tmp_path, monkeypatch):
    """EARN-THE-RED: a deployed hook one byte different from the package vendor
    copy reds C-2 and names the drifted file."""
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    (deployed / "foo.py").write_text("x = 1\n", encoding="utf-8")

    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)
    (vendor / "foo.py").write_text("x = 2\n", encoding="utf-8")  # one byte differs

    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert not result.passed
    assert any("foo.py" in f and "drifted" in f for f in result.failures)


def test_c2_passes_on_a_crlf_checkout_of_the_package(tmp_path, monkeypatch):
    """DEF-725's sister site: the deployed tree is git-tracked and a Windows
    checkout re-ends it to CRLF, while pip never re-ends the wheel's vendor
    copy. The compare is in the manifest's canonical text form (a BOM or an
    ending is not drift); a real byte change beside them still is."""
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    (deployed / "foo.py").write_bytes(b"\xef\xbb\xbfx = 1\r\ny = 2\r\n")
    (deployed / "bar.py").write_bytes(b"z = 3\r\n")

    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)
    (vendor / "foo.py").write_bytes(b"x = 1\ny = 2\n")
    (vendor / "bar.py").write_bytes(b"z = 4\n")  # the real drift beside the re-ending

    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert not result.passed
    assert any("bar.py" in f and "foo.py" not in f for f in result.failures), result.failures


def test_c2_red_on_set_divergence(tmp_path, monkeypatch):
    """A deployed-only hook file the HARNESS wrote (it carries the managed
    marker) and the package no longer ships reds C-2 as a set divergence.
    Since 2026-09-12 the marker is what makes it ours (DEF-735): the
    original fixture's unmarked file is now the adopter's, pinned below."""
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    (deployed / "extra.py").write_text("# espalier:managed\ny = 1\n", encoding="utf-8")

    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)  # empty — extra.py is deployed-only

    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert not result.passed
    assert any("extra.py" in f for f in result.failures)


def test_c2_compares_in_the_deployed_form(tmp_path, monkeypatch):
    """DEF-735 (TP-449 Tier 2, 2026-09-12): driven on a fresh adopter init,
    C-2 named every hook as drifted -- `init` prepends `# espalier:managed`
    to each copy (after a shebang when there is one) and the package carries
    an `__init__.py` the deploy never ships. The marker the deploy added is
    not drift; the package-internal file is not drift; a real byte change
    beside the marker still is."""
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    (deployed / "plain.py").write_text("# espalier:managed\nx = 1\n", encoding="utf-8")
    (deployed / "shebang.py").write_text(
        "#!/usr/bin/env python3\n# espalier:managed\ny = 2\n", encoding="utf-8"
    )
    (deployed / "drifted.py").write_text("# espalier:managed\nz = 3\n", encoding="utf-8")

    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)
    (vendor / "plain.py").write_text("x = 1\n", encoding="utf-8")
    (vendor / "shebang.py").write_text("#!/usr/bin/env python3\ny = 2\n", encoding="utf-8")
    (vendor / "drifted.py").write_text("z = 4\n", encoding="utf-8")
    (vendor / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert not result.passed
    assert len(result.failures) == 1, result.failures
    assert "drifted.py" in result.failures[0], result.failures
    assert "plain.py" not in result.failures[0] and "shebang.py" not in result.failures[0]
    assert "__init__.py" not in result.failures[0], result.failures


def test_c2_a_package_only_file_the_deploy_ships_is_drift(tmp_path, monkeypatch):
    """The deploy set comes from the packaged surface: a shipped hook missing
    from the tree is a set divergence; a package-internal file is not."""
    shipped = sorted(selfcheck._deployed_hook_basenames())
    assert "write_guard.py" in shipped and "__init__.py" not in shipped, shipped
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)
    (vendor / "write_guard.py").write_text("x = 1\n", encoding="utf-8")
    (vendor / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert not result.passed
    assert any("write_guard.py" in f and "package-only" in f for f in result.failures), result.failures
    assert not any("__init__.py" in f for f in result.failures), result.failures


def test_c2_an_unmarked_deployed_only_file_is_the_adopters(tmp_path, monkeypatch):
    """A file under tools/cc/hooks/ without the managed marker was not written
    by the harness; the adopter's own script is not drift from the package."""
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    (deployed / "mine.py").write_text("y = 1\n", encoding="utf-8")
    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)
    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert result.passed, result.failures


def test_c2_on_the_self_host_tree_an_unmarked_deployed_only_file_is_drift(tmp_path, as_self_host_tree):
    """On the self-host tree the deployed hooks are the package source and
    carry no marker, so the marker rule would read every deployed-only file
    as the adopter's; there a deployed-only file is a hook added without the
    vendor sync, and C-2 says so (failure-mode review, 2026-09-12)."""
    deployed = tmp_path / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    (deployed / "zz_new_hook.py").write_text("y = 1\n", encoding="utf-8")
    result = selfcheck.check_upstream_parity(tmp_path)
    assert not result.passed
    assert any("zz_new_hook.py" in f for f in result.failures), result.failures


def test_c2_strips_only_an_anchored_marker_and_on_both_sides(tmp_path, monkeypatch):
    """A first line that merely MENTIONS the token is not the marker (kept on
    both sides, so equal); a source hook carrying an anchored marker itself
    matches its copy, because the strip is applied to both sides."""
    deployed = tmp_path / "deployed" / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    vendor = tmp_path / "vendor" / "hooks"
    vendor.mkdir(parents=True)
    mention = '"""A note about the espalier:managed contract."""\nx = 1\n'
    (deployed / "mention.py").write_text("# espalier:managed\n" + mention, encoding="utf-8")
    (vendor / "mention.py").write_text(mention, encoding="utf-8")
    anchored = "# espalier:managed\nx = 2\n"
    (deployed / "anchored.py").write_text(anchored, encoding="utf-8")
    (vendor / "anchored.py").write_text(anchored, encoding="utf-8")
    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: vendor)
    result = selfcheck.check_upstream_parity(tmp_path / "deployed")
    assert result.passed, result.failures


def test_c2_passes_on_a_fresh_adopter_init(tmp_path):
    """The driven instance: `init` on a scratch tree, then C-2 against the
    package that deployed it. Red before 2026-09-12 (every hook 'drifted')."""
    import argparse
    from espalier.cli import cmd_init
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    assert cmd_init(argparse.Namespace(repo=str(tmp_path), config=None)) == 0
    result = selfcheck.check_upstream_parity(tmp_path)
    assert result.passed, result.failures


def test_c2_skips_on_source_checkout(monkeypatch):
    """Verifier #4: when no installed-package vendor dir resolves (zipapp / odd
    install), C-2 SKIPS cleanly (passed=True) rather than false-failing. This is
    the only way the skip branch gets coverage on the self-host repo, whose real
    vendor dir always resolves."""
    monkeypatch.setattr(selfcheck, "_package_vendor_hooks_dir", lambda: None)
    result = selfcheck.check_upstream_parity(REPO_ROOT)
    assert result.passed
    assert "skipped" in result.detail


def test_c2_red_on_missing_deployed_dir(tmp_path):
    """No deployed tools/cc/hooks dir reds C-2 with a 'missing' failure."""
    result = selfcheck.check_upstream_parity(tmp_path)
    assert not result.passed
    assert any("missing" in f for f in result.failures)


# ── C-3: live kill-switch absence ─────────────────────────────────────────────

def test_c3_passes_clean(tmp_path):
    """A tree with no settings files has no kill-switch."""
    result = selfcheck.check_live_kill_switch_absent(tmp_path)
    assert result.passed
    assert result.failures == []


def test_c3_red_on_disable_all_hooks(tmp_path):
    """EARN-THE-RED: disableAllHooks: true in the live settings reds C-3."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8"
    )
    result = selfcheck.check_live_kill_switch_absent(tmp_path)
    assert not result.passed
    assert any("disableAllHooks" in f for f in result.failures)


def test_c3_red_on_bypass_permissions(tmp_path):
    """EARN-THE-RED: permissions.defaultMode == bypassPermissions reds C-3."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text(
        json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}),
        encoding="utf-8",
    )
    result = selfcheck.check_live_kill_switch_absent(tmp_path)
    assert not result.passed
    assert any("bypassPermissions" in f for f in result.failures)


def test_c3_ignores_malformed_settings(tmp_path):
    """A malformed settings file is not a kill-switch (the parse failure surfaces
    elsewhere) — C-3 must not crash or false-fail on it.

    C-3 asks whether a kill switch is LIVE. Claude Code cannot parse this file
    either, so `disableAllHooks` is not in effect and "no" is the honest answer.
    """
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{not json", encoding="utf-8")
    result = selfcheck.check_live_kill_switch_absent(tmp_path)
    assert result.passed


def test_the_elsewhere_that_malformed_settings_surfaces_in_is_real(tmp_path):
    """Pin the "surfaces elsewhere" claim the test above depends on.

    That claim sat in a code comment for a long time with nothing checking it —
    an untested assertion propping up a deliberate no-op, which is the shape
    this repo treats as a defect rather than a decision. If both sibling
    surfaces ever stop reporting, C-3's silence becomes a real fail-open and
    this test is what says so.
    """
    import importlib.util

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text('{"disableAllHooks": true,}', encoding="utf-8")

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_ig_elsewhere", root / "tools" / "cc" / "hooks" / "_integrity.py"
    )
    integ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(integ)
    reported = integ.scan_for_kill_switches(tmp_path, include_unreadable=True)
    assert any("unreadable settings file" in f for f in reported), (
        "SessionStart's kill-switch report no longer surfaces an unparseable "
        "settings file — C-3's deliberate silence is now a fail-open"
    )

    spec2 = importlib.util.spec_from_file_location(
        "_cg_elsewhere", root / "tools" / "cc" / "ci_guard.py"
    )
    cig = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(cig)
    assert cig.scan_unreadable_settings(str(tmp_path)), (
        "the merge gate no longer fails on an unparseable committed settings "
        "file — the other half of C-3's 'surfaces elsewhere'"
    )


def test_c3_marker_parity_with_integrity():
    """Parity lock: selfcheck._find_kill_switch_markers must agree with the
    deployed _integrity._find_kill_switches SoT on the two VALUE-marker inputs
    (disableAllHooks / bypassPermissions). C-3 deliberately covers only those two
    live-value kill-switches; _integrity additionally detects structural
    empty/no-op-hooks markers (committed-config tampering owned by ci_guard +
    integrity), which are intentionally NOT mirrored here — so the parity is
    asserted on the value-marker inputs only."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import _integrity  # noqa: E402
    finally:
        sys.path.pop(0)

    value_marker_inputs = [
        {"disableAllHooks": True},
        {"permissions": {"defaultMode": "bypassPermissions"}},
        {"disableAllHooks": True,
         "permissions": {"defaultMode": "bypassPermissions"}},
        {},  # neither marker present
        {"disableAllHooks": False},  # explicit False is not a kill-switch
    ]
    for data in value_marker_inputs:
        rel = ".claude/settings.json"
        ours = selfcheck._find_kill_switch_markers(rel, data)
        theirs = _integrity._find_kill_switches(rel, data)
        assert ours == theirs, (
            f"marker parity drift on {data!r}: selfcheck={ours} integrity={theirs}"
        )


# ── aggregate ─────────────────────────────────────────────────────────────────

def test_run_contracts_returns_0_on_clean_repo():
    """The repo at rest passes all three contracts → run_contracts returns 0."""
    assert selfcheck.run_contracts(REPO_ROOT) == 0


def test_run_contracts_returns_1_when_a_contract_fails(tmp_path, capsys):
    """A tree with a deployed hook but a planted live kill-switch reds the
    aggregate (C-3 fails) → run_contracts returns 1 and prints a fail report."""
    # Deploy the real hook into tmp_path so C-1/C-2 can run, then plant a
    # kill-switch in the live settings so C-3 reds.
    import shutil
    deployed = tmp_path / "tools" / "cc" / "hooks"
    deployed.mkdir(parents=True)
    shutil.copytree(HOOKS_DIR, deployed, dirs_exist_ok=True)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8"
    )
    rc = selfcheck.run_contracts(tmp_path)
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "fail"
