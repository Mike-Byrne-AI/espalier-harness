"""scripts/sync_claude_mirrors.py::sync must fail loud when the source-of-truth
``.claude/`` tree is missing/empty, instead of silently pruning EVERY mirror file.

The ``.claude`` analog of tests/test_sync_vendor_cc.py: sync() mirrors SRC
(``.claude``) -> each MIRROR and prunes any mirror file whose SoT source vanished.
If SRC is empty, ``_files(SRC)`` is the empty set, the copy loop no-ops, and the
prune loop unlinks every mirror file — emptying both mirrors and returning
``(0, N)`` with no error. ``sync_vendor_cc`` already has this guard;
``sync_claude_mirrors`` was missing it (TP-274 6-A). SRC/MIRRORS are monkeypatched
to tmp dirs so the real mirrors are never at risk.
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
        "_tp274_sync_claude_mirrors",
        REPO_ROOT / "scripts" / "sync_claude_mirrors.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_sync_fails_loud_when_source_empty_and_leaves_mirrors_intact(monkeypatch, tmp_path):
    """RED before the guard: an empty SRC makes sync() prune every mirror file and
    return (0, N). GREEN after: it raises SystemExit and the mirrors are untouched.
    SRC/MIRRORS are redirected to tmp dirs so the real mirrors are never at risk."""
    mod = _load_sync_script()

    mirror = tmp_path / "mirror"
    (mirror / "agents").mkdir(parents=True)
    (mirror / "agents" / "a.md").write_text("# mirror agent a\n", encoding="utf-8")
    (mirror / "commands").mkdir(parents=True)
    (mirror / "commands" / "b.md").write_text("# mirror command b\n", encoding="utf-8")
    before = _snapshot(mirror)
    assert before, "fixture precondition: tmp mirror should be non-empty"

    # An existing-but-empty SRC (no agents/commands/skills subdirs) -> _files(SRC)
    # is the empty set. This is the exact silent-prune trigger.
    src_empty = tmp_path / "empty-claude"
    src_empty.mkdir()
    monkeypatch.setattr(mod, "SRC", src_empty)
    monkeypatch.setattr(mod, "MIRRORS", (mirror,))

    with pytest.raises(SystemExit):
        mod.sync()

    assert _snapshot(mirror) == before, (
        "sync() emptied/altered the mirror instead of refusing on an empty source"
    )


def test_sync_mirrors_and_prunes_on_a_normal_tree(monkeypatch, tmp_path):
    """Positive control: with a real SRC, sync() copies files and prunes an orphan
    whose source was removed, returning (copied, pruned). Confirms the fail-loud
    guard does not break the normal path."""
    mod = _load_sync_script()

    src = tmp_path / "src"
    (src / "agents").mkdir(parents=True)
    (src / "agents" / "a.md").write_text("agent a\n", encoding="utf-8")
    (src / "commands").mkdir(parents=True)
    (src / "commands" / "b.md").write_text("command b\n", encoding="utf-8")

    mirror = tmp_path / "mirror"
    (mirror / "skills").mkdir(parents=True)
    (mirror / "skills" / "orphan.md").write_text("orphan\n", encoding="utf-8")  # no source

    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "MIRRORS", (mirror,))

    copied, pruned = mod.sync()
    assert copied == 2 and pruned == 1
    assert (mirror / "agents" / "a.md").read_text(encoding="utf-8") == "agent a\n"
    assert not (mirror / "skills" / "orphan.md").exists()


def test_check_mode_detects_drift_without_mutating(monkeypatch, tmp_path):
    """TP-274 8-A: ``--check`` must report drift (nonzero exit) WITHOUT writing.
    surface_impact.py cites ``sync_claude_mirrors.py --check`` as a verify command,
    but pre-fix the script had no argparse and the cited 'check' silently mutated
    + exited 0. RED before (main took no argv → TypeError), GREEN after."""
    mod = _load_sync_script()
    src = tmp_path / "src"
    (src / "agents").mkdir(parents=True)
    (src / "agents" / "a.md").write_text("agent a\n", encoding="utf-8")
    mirror = tmp_path / "mirror"
    (mirror / "agents").mkdir(parents=True)
    (mirror / "agents" / "a.md").write_text("DRIFTED\n", encoding="utf-8")  # stale
    before = _snapshot(mirror)
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "MIRRORS", (mirror,))
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)  # plan()/main() key off relative_to(REPO_ROOT)

    assert mod.main(["--check"]) == 1, "--check did not report drift"
    assert _snapshot(mirror) == before, "--check mutated the mirror (must be read-only)"


def test_check_mode_clean_tree_returns_zero(monkeypatch, tmp_path):
    """``--check`` on an in-parity tree returns 0 and writes nothing."""
    mod = _load_sync_script()
    src = tmp_path / "src"
    (src / "agents").mkdir(parents=True)
    (src / "agents" / "a.md").write_text("agent a\n", encoding="utf-8")
    mirror = tmp_path / "mirror"
    (mirror / "agents").mkdir(parents=True)
    (mirror / "agents" / "a.md").write_text("agent a\n", encoding="utf-8")  # in parity
    before = _snapshot(mirror)
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "MIRRORS", (mirror,))
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)  # plan()/main() key off relative_to(REPO_ROOT)

    assert mod.main(["--check"]) == 0
    assert _snapshot(mirror) == before
