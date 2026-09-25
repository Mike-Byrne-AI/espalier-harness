"""scripts/sync_vendor_cc.py::sync must fail loud when the source-of-truth dir
(tools/cc) is renamed or missing, instead of silently pruning the ENTIRE
vendored mirror.

Rationale (self-contained, per the contract-rationale convention): sync mirrors
SRC (tools/cc) -> VENDOR (espalier/_vendor/cc) and prunes any vendored file
whose source vanished. If SRC is missing or empty, ``_py_files(SRC)`` returns an
empty set, the copy loop no-ops, and the prune loop unlinks every vendored file
— emptying the mirror and returning ``(0, N)`` with no error. The guard turns
that silent data-loss into a loud ``SystemExit``. Both SRC and VENDOR are
monkeypatched to tmp dirs, so the test exercises the logic with zero risk to the
real espalier/_vendor/cc mirror (never operate the destructive path against the
live tree).
"""
# pytest-marker: default-unit  (fast pure-logic script test; not a grandfather entry)
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_sync_script():
    """Import the script as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(
        "_tp267_sync_vendor_cc",
        REPO_ROOT / "scripts" / "sync_vendor_cc.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.py")}


def test_sync_fails_loud_when_source_empty_and_leaves_vendor_intact(monkeypatch, tmp_path):
    """RED before the guard: an empty SRC makes sync() prune the whole mirror and
    return (0, N). GREEN after: it raises SystemExit and the mirror is untouched.
    SRC/VENDOR are redirected to tmp dirs so the real mirror is never at risk."""
    mod = _load_sync_script()

    vendor = tmp_path / "vendor"
    (vendor / "hooks").mkdir(parents=True)
    (vendor / "hooks" / "a.py").write_text("# mirror file a\n", encoding="utf-8")
    (vendor / "b.py").write_text("# mirror file b\n", encoding="utf-8")
    before = _snapshot(vendor)
    assert before, "fixture precondition: tmp mirror should be non-empty"

    # An existing-but-empty SRC -> _py_files(SRC) is the empty set (deterministic,
    # no rglob-on-missing ambiguity). This is the exact silent-prune trigger.
    src_empty = tmp_path / "empty-tools-cc"
    src_empty.mkdir()
    monkeypatch.setattr(mod, "SRC", src_empty)
    monkeypatch.setattr(mod, "VENDOR", vendor)

    with pytest.raises(SystemExit):
        mod.sync()

    assert _snapshot(vendor) == before, (
        "sync() emptied/altered the mirror instead of refusing on an empty source"
    )


def test_sync_mirrors_and_prunes_on_a_normal_tree(monkeypatch, tmp_path):
    """Positive control: with a real SRC, sync() copies new files and prunes an
    orphan whose source was removed, returning (copied, pruned). Confirms the
    fail-loud guard does not break the normal path."""
    mod = _load_sync_script()

    src = tmp_path / "src"
    (src / "hooks").mkdir(parents=True)
    (src / "hooks" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (src / "b.py").write_text("print('b')\n", encoding="utf-8")

    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "orphan.py").write_text("print('orphan')\n", encoding="utf-8")  # no source

    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "VENDOR", vendor)

    copied, pruned = mod.sync()
    assert copied == 2 and pruned == 1
    assert (vendor / "hooks" / "a.py").read_text(encoding="utf-8") == "print('a')\n"
    assert not (vendor / "orphan.py").exists()


def test_check_mode_detects_drift_without_mutating(monkeypatch, tmp_path):
    """``--check`` must report drift (nonzero exit) WITHOUT writing. Pre-fix the
    script had no argparse, so a cited ``--check`` was swallowed and silently ran a
    REAL sync (exit 0). RED before (main took no argv -> TypeError), GREEN after.
    SRC/VENDOR redirected to tmp dirs so the real mirror is never at risk."""
    mod = _load_sync_script()
    src = tmp_path / "src"
    (src / "hooks").mkdir(parents=True)
    (src / "hooks" / "a.py").write_text("print('a')\n", encoding="utf-8")
    vendor = tmp_path / "vendor"
    (vendor / "hooks").mkdir(parents=True)
    (vendor / "hooks" / "a.py").write_text("print('DRIFTED')\n", encoding="utf-8")  # stale
    before = _snapshot(vendor)
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "VENDOR", vendor)

    assert mod.main(["--check"]) == 1, "--check did not report drift"
    assert _snapshot(vendor) == before, "--check mutated the mirror (must be read-only)"


def test_check_mode_clean_tree_returns_zero(monkeypatch, tmp_path):
    """``--check`` on an in-parity tree returns 0 and writes nothing."""
    mod = _load_sync_script()
    src = tmp_path / "src"
    (src / "hooks").mkdir(parents=True)
    (src / "hooks" / "a.py").write_text("print('a')\n", encoding="utf-8")
    vendor = tmp_path / "vendor"
    (vendor / "hooks").mkdir(parents=True)
    (vendor / "hooks" / "a.py").write_text("print('a')\n", encoding="utf-8")  # in parity
    before = _snapshot(vendor)
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "VENDOR", vendor)

    assert mod.main(["--check"]) == 0
    assert _snapshot(vendor) == before


def test_unknown_flag_is_rejected_fail_loud(monkeypatch, tmp_path):
    """An unknown flag must be REJECTED (argparse SystemExit code 2), not silently
    swallowed into a real sync as the pre-argparse script did. VENDOR is redirected
    to an empty tmp dir so even a regressed guard cannot touch the real mirror."""
    mod = _load_sync_script()
    src = tmp_path / "src"
    (src / "hooks").mkdir(parents=True)
    (src / "hooks" / "a.py").write_text("print('a')\n", encoding="utf-8")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "VENDOR", vendor)

    with pytest.raises(SystemExit) as exc:
        mod.main(["--bogus"])
    assert exc.value.code == 2, "unknown flag should argparse-exit 2, not run a sync"
    assert not (vendor / "hooks" / "a.py").exists(), "rejected flag must not have synced"
