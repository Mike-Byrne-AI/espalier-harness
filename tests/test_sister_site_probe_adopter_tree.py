"""DEF-673, driven on the artifact an adopter gets: the DEPLOYED probe on a
real ``espalier init`` tree.

The synthetic cases in ``test_sister_site_probe_synthetic.py`` prove the
mechanism on hand-built trees. This file proves it where the defect was
found -- a foreign repo after ``init`` -- so the marker the mode keys on is
the one ``init`` actually writes, the probe under test is the deployed copy
at ``tools/cc/sister_site_probe.py``, and the harness debt reported is
whatever the shipped hooks really carry.

What an adopter's first ``/implement-pack`` step 0-C must now see:

1. the exit code keys on THEIR duplicates only;
2. Espalier's own hook debt is listed, labelled advisory, and never gates;
3. the report says whose code it read and what it skipped.

This file pins the ledger row's own verification criterion on the real
artifact, because the synthetic fixtures cannot: a hand-typed marker or a
hand-built overlay proves the mechanism, not the deployment -- and the defect
was found by driving a wheel install, so its proof has to drive one too.
It prevents the regression class where the source-tree scan stays green
while the deployed copy drifts.

Test naming follows ``test_{specific_behavior}`` per docs/CONVENTIONS.md.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _adopter_tree import _git, build_adopter_tree, deployed_python
from espalier.managed_markers import file_carries_marker

_MARKER = "# espalier:managed v0.0.0 sha256:0000\n"


@pytest.fixture(scope="module")
def fused_tree(tmp_path_factory) -> Path:
    """A real ``espalier fuse`` of a small host: the harness overlaid at the
    host's root (engine package, tools/, bench, two scripts) plus ``init``."""
    from espalier import fuse

    base = tmp_path_factory.mktemp("def673_fuse")
    host = base / "host"
    (host / "src" / "demo").mkdir(parents=True)
    (host / "README.md").write_text("# Demo App\n", encoding="utf-8")
    (host / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\nversion = "0.1.0"\n', encoding="utf-8",
    )
    (host / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (host / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (host / "src" / "demo" / "app.py").write_text(
        "def main() -> int:\n    return 0\n", encoding="utf-8",
    )
    # The host's OWN tools/ and bench/ -- names the overlay shares. No file
    # collides, so fuse proceeds; the probe must keep these in scope.
    (host / "tools").mkdir()
    (host / "tools" / "host_tool.py").write_text("def t():\n    return 1\n", encoding="utf-8")
    (host / "bench").mkdir()
    (host / "bench" / "host_bench.py").write_text("def b():\n    return 1\n", encoding="utf-8")
    _git(host, "init", "-q", "-b", "main", ".")
    _git(host, "config", "user.email", "adopter@example.invalid")
    _git(host, "config", "user.name", "Adopter")
    _git(host, "add", "-A")
    _git(host, "commit", "-qm", "initial")
    out = base / "out"
    report = fuse.fuse_repos(host, out, run_init=True)
    assert report["init_rc"] == 0, report
    return out


@pytest.fixture(scope="module")
def pristine_tree(tmp_path_factory) -> Path:
    """One ``git init`` + ``espalier init`` for the module; never mutated."""
    return build_adopter_tree(tmp_path_factory.mktemp("def673"))


@pytest.fixture
def tree(pristine_tree: Path, tmp_path: Path) -> Path:
    """A private copy a test may plant files in."""
    dst = tmp_path / "tree"
    shutil.copytree(pristine_tree, dst, symlinks=True)
    return dst


def _run_probe(tree: Path, *extra: str) -> subprocess.CompletedProcess:
    """Run the DEPLOYED probe, from the adopter's cwd, the way step 0-C does."""
    return subprocess.run(
        [
            sys.executable, str(tree / "tools" / "cc" / "sister_site_probe.py"),
            "--root", str(tree), "--json", *extra,
        ],
        capture_output=True, text=True, cwd=tree, timeout=50, encoding="utf-8",
    )


def _plant_clique(tree: Path, *names: str) -> None:
    for name in names:
        (tree / "src" / "demo" / f"{name}.py").write_text(
            "def helper():\n    return 42\n", encoding="utf-8",
        )


@pytest.mark.security
class TestDeployedProbeOnAdopterTree:
    def test_every_deployed_hook_carries_the_marker_the_mode_keys_on(self, pristine_tree):
        """The signal is what ``init`` wrote, derived from the deploy
        inventories -- not a marker this test typed."""
        hooks = [
            p for p in deployed_python(pristine_tree)
            if p.parent == pristine_tree / "tools" / "cc" / "hooks"
        ]
        assert hooks, "fixture drift: init deployed no hooks"
        unmarked = [p.name for p in hooks if not file_carries_marker(p)]
        assert not unmarked, f"deployed hooks without the managed marker: {unmarked}"

    def test_mode_is_adopter_and_scope_is_their_source(self, pristine_tree):
        result = _run_probe(pristine_tree)
        payload = json.loads(result.stdout)
        scope = payload["scope"]
        assert scope["mode"] == "adopter", result.stderr
        assert scope["explicit_roots"] is False
        assert scope["scanned"] == ["src/demo/__init__.py", "src/demo/app.py"], (
            "the gating scope is not the adopter's own package"
        )
        assert "tools/cc/" in scope["pruned"]
        assert "tests/" in scope["pruned"]
        assert scope["harness_files"], "the deployed hooks were not scanned at all"
        assert all(f.startswith("tools/cc/hooks/") for f in scope["harness_files"])
        assert "[scope] adopter:" in result.stderr

    def test_pristine_tree_exits_zero_whatever_the_hooks_carry(self, pristine_tree):
        """The defect as found: rc=2 on a wheel install with no adopter
        duplicate at all. Whatever debt the shipped hooks carry today, it is
        Espalier's and it must not red the adopter's pre-flight."""
        result = _run_probe(pristine_tree)
        payload = json.loads(result.stdout)
        assert result.returncode == 0, (
            f"rc={result.returncode} on a tree with no adopter duplicate; "
            f"top-level findings: cliques={payload['cliques']} "
            f"canon={payload['canon_misses']} alias={payload['alias_misses']}"
        )
        assert payload["has_debt"] is False
        assert payload["harness_internal"] is not None
        # Every finding in the advisory sub-report names a deployed hook and
        # nothing of the adopter's.
        harness = payload["harness_internal"]
        cited = {m["shadow_file"] for m in harness["canon_misses"]}
        cited |= {s["file"] for c in harness["cliques"] for s in c["sites"]}
        cited |= {a["file"] for a in harness["alias_misses"]}
        assert all(f.startswith("tools/cc/hooks/") for f in cited), cited

    def test_planted_harness_debt_is_reported_but_never_gates(self, tree):
        """Independent of the live hooks' debt: plant a 3-site identical
        clique into MARKED hook files and prove the gate ignores it."""
        hooks = tree / "tools" / "cc" / "hooks"
        for name in ("zz_a", "zz_b", "zz_c"):
            (hooks / f"{name}.py").write_text(
                _MARKER + "def zz_dup():\n    return 1\n", encoding="utf-8",
            )
        result = _run_probe(tree)
        payload = json.loads(result.stdout)
        assert result.returncode == 0, result.stdout
        assert payload["has_debt"] is False
        harness = payload["harness_internal"]
        assert harness["has_debt"] is True
        assert any(c["name"] == "zz_dup" and c["severity"] == "WARN"
                   for c in harness["cliques"])
        assert not any(c["name"] == "zz_dup" for c in payload["cliques"]), (
            "harness debt leaked into the adopter's gating findings"
        )
        assert "harness-internal (advisory, not gating): " in result.stderr

    def test_adopters_own_clique_gates_on_the_deployed_artifact(self, tree):
        """The other half of the row's verification: THEIR duplicate reds."""
        _plant_clique(tree, "x", "y", "z")
        result = _run_probe(tree)
        payload = json.loads(result.stdout)
        assert result.returncode == 2, result.stderr
        assert payload["has_debt"] is True
        clique = next(c for c in payload["cliques"] if c["name"] == "helper")
        assert clique["severity"] == "WARN" and clique["divergent"] is False
        assert {s["file"] for s in clique["sites"]} == {
            "src/demo/x.py", "src/demo/y.py", "src/demo/z.py",
        }

    def test_accept_flag_still_clears_the_adopters_own_debt(self, tree):
        _plant_clique(tree, "x", "y", "z")
        result = _run_probe(tree, "--accept-compression-debt", "known, tracked")
        assert result.returncode == 0
        assert "[ACCEPTED]" in result.stderr

    def test_roots_narrow_to_what_the_adopter_names(self, tree):
        _plant_clique(tree, "x", "y", "z")
        (tree / "lib").mkdir()
        (tree / "lib" / "clean.py").write_text("X = 1\n", encoding="utf-8")
        result = _run_probe(tree, "--roots", "lib")
        payload = json.loads(result.stdout)
        assert result.returncode == 0
        assert payload["scope"]["roots"] == ["lib/"]
        assert payload["scope"]["scanned"] == ["lib/clean.py"]
        assert payload["scope"]["explicit_roots"] is True

    def test_fused_tree_gates_on_the_host_not_the_overlay(self, fused_tree):
        """Driven by the failure-mode pass on the first cut: rc=2, 98 files
        "under ." of which 97 were Espalier's (the engine, bench, tools/),
        and three engine parallels gated. The overlay is pruned by the
        tracked ``.espalier-fusion`` marker; only the host's code is scanned."""
        assert (fused_tree / ".espalier-fusion").is_file(), "fuse no longer writes its marker"
        result = _run_probe(fused_tree)
        payload = json.loads(result.stdout)
        scope = payload["scope"]
        assert scope["mode"] == "adopter", result.stderr
        assert scope["scanned"] == [
            "bench/host_bench.py", "src/demo/__init__.py", "src/demo/app.py",
            "tools/host_tool.py",
        ], (
            f"the overlay leaked into the gating scope, or the host's own "
            f"tools/ / bench/ files were pruned with it: {scope['scanned']}"
        )
        assert result.returncode == 0, result.stdout
        assert payload["has_debt"] is False
        for expected in (
            "espalier/ (fused harness overlay)",
            "bench/end_to_end/ (fused harness overlay)",
            "bench/run_benchmark.py (fused harness overlay)",
            "tools/review_agent_audit.py (fused harness overlay)",
            "tools/cc/",
        ):
            assert expected in scope["pruned"], scope["pruned"]
        # Mechanical accounting: nothing the overlay wrote is in the gating
        # scope. Derived from the manifest, not from this test's expectations.
        from espalier.fusion_manifest import HARNESS_INCLUDE
        overlaid_prefixes = tuple(e for e in HARNESS_INCLUDE if e.endswith("/"))
        overlaid_files = {e for e in HARNESS_INCLUDE if e.endswith(".py")}
        leaked = [
            f for f in scope["scanned"]
            if f in overlaid_files or (
                f.startswith(overlaid_prefixes) and not f.startswith(("tools/host", "bench/host"))
            )
        ]
        assert not leaked, leaked
        # The deployed hooks are still the advisory scope.
        assert scope["harness_files"] and all(
            f.startswith("tools/cc/hooks/") for f in scope["harness_files"]
        )

    def test_an_initialised_self_host_clone_still_reads_as_self_host(self, initialized_repo_root):
        """``init`` on the harness's own tree leaves its hooks unmarked, so the
        probe stays in self-host mode with every arm gating. Pinned on the
        initialised clone, not just the committed tree: a uniformity refactor
        that marked self-host hooks would flip the mode, prune the engine as
        "vendored", demote every hook finding to advisory and turn the gate
        green on identical debt -- with every probe test still passing (third
        failure-mode pass, measured: rc 2 -> rc 0)."""
        result = _run_probe(initialized_repo_root)
        payload = json.loads(result.stdout)
        assert payload["scope"]["mode"] == "self-host", result.stderr
        assert payload["harness_internal"] is None
        assert payload["scope"]["harness_files"] == []
        assert payload["scope"]["roots"] == ["tools/cc/hooks/*.py", "espalier/*.py"]

    def test_text_report_reads_as_two_scopes(self, tree):
        """What the adopter actually sees at 0-C without ``--json``."""
        _plant_clique(tree, "x", "y", "z")
        result = subprocess.run(
            [
                sys.executable, str(tree / "tools" / "cc" / "sister_site_probe.py"),
                "--root", str(tree),
            ],
            capture_output=True, text=True, cwd=tree, timeout=50, encoding="utf-8",
        )
        out = result.stdout
        assert result.returncode == 2
        assert "SCOPE: adopter tree -- the gating scan below covers YOUR source." in out
        assert "Scanned 5 .py file(s) under ." in out
        assert "HARNESS-INTERNAL (advisory, never gates this run)" in out
        assert "write_guard keeps these files read-only" in out
        # The SCOPE block announces the tail by name, so anchor on the
        # heading itself, not the first mention.
        tail = out.index("HARNESS-INTERNAL (advisory, never gates this run)")
        assert out.index("`helper`") < tail, (
            "the adopter's own finding must come before the advisory tail"
        )
        assert "CANON-MISS  tools/cc/hooks/" not in out[:tail], (
            "harness debt printed inside the adopter's gating sections"
        )
        assert (out + result.stderr).isascii(), "operator-facing report must be 7-bit ASCII"
        assert "_hook_utils" not in out, "self-host remediation leaked into the adopter's report"
