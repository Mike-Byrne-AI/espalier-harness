"""The retention cap is a working-set policy, not a destruction policy.

Measured 2026-08-31: ``cc/blueprints/`` held exactly 200 per-session files
against ``BLUEPRINT_RETENTION = 200`` with zero stubs, and the chain's oldest
surviving node was ``2026-07-03`` against a ``2026-04-30`` first commit --
roughly two months of reasoning already gone. The loss was silent because
deleting and retaining produced identical output at every observable the
tooling had: no count moved that anyone read, no error was raised, and
``cmd_chain`` reported a healthy number either way.

These tests were written BEFORE the fix and driven red against the deleting
implementation (STANDING_PRINCIPLES section 7 -- earn the red). Available here,
unlike for new code, because the behaviour being changed already existed and
already had an observable.
"""

import ast
import os
import sys
import time as _time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPruneDemotesNeverDeletes:
    """Every file the cap evicts must still be readable afterwards --
    under ``bp_dir/_cold/``, byte-identical."""

    def test_evicted_blueprints_survive_in_cold(self, tmp_path):
        from espalier._blueprint_limits import (
            BLUEPRINT_COLD_DIR_NAME,
            BLUEPRINT_MIN_PRUNE_AGE_S,
            BLUEPRINT_RETENTION,
        )
        from espalier.cognitive_blueprint import _prune_blueprints

        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        old_epoch = _time.time() - (BLUEPRINT_MIN_PRUNE_AGE_S + 3600)

        # Substantive nodes only, no stubs -- the live shape. The real store
        # sat at 200/200 with zero stubs, so the eviction tail was reasoning,
        # not scratch, and the stub-first sort key had nothing left to spend.
        written = {}
        for i in range(BLUEPRINT_RETENTION + 25):
            p = bp_dir / f"2026{i:04d}-000000-abcdef.json"
            body = '{"session_id":"s%04d","reasoning":"%s"}\n' % (i, "x" * 1000)
            p.write_text(body, encoding="utf-8")
            os.utime(p, (old_epoch, old_epoch))
            written[p.name] = body

        _prune_blueprints(bp_dir)

        hot = {p.name for p in bp_dir.glob("*.json")}
        cold = {p.name for p in (bp_dir / BLUEPRINT_COLD_DIR_NAME).glob("*.json")}

        assert len(hot) == BLUEPRINT_RETENTION, (
            f"retention cap not enforced: {len(hot)} hot files"
        )
        destroyed = set(written) - hot - cold
        assert not destroyed, (
            f"{len(destroyed)} blueprints DESTROYED by prune, not demoted. "
            f"The retention cap is deleting reasoning. Sample: "
            f"{sorted(destroyed)[:3]}"
        )
        for name in cold:
            got = (bp_dir / BLUEPRINT_COLD_DIR_NAME / name).read_text(encoding="utf-8")
            assert got == written[name], f"{name} was altered in transit to _cold/"

    def test_cold_dir_does_not_re_enter_the_eviction_tail(self, tmp_path):
        """``_cold/`` lives inside ``bp_dir``. The enumeration is a
        non-recursive ``glob("*.json")``, so a demoted node must never be
        re-considered -- otherwise each prune would re-demote its own output."""
        from espalier._blueprint_limits import (
            BLUEPRINT_COLD_DIR_NAME,
            BLUEPRINT_MIN_PRUNE_AGE_S,
            BLUEPRINT_RETENTION,
        )
        from espalier.cognitive_blueprint import _prune_blueprints

        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        old_epoch = _time.time() - (BLUEPRINT_MIN_PRUNE_AGE_S + 3600)
        for i in range(BLUEPRINT_RETENTION + 5):
            p = bp_dir / f"2026{i:04d}-000000-abcdef.json"
            p.write_text('{"session_id":"x","r":"%s"}\n' % ("y" * 1000), encoding="utf-8")
            os.utime(p, (old_epoch, old_epoch))

        _prune_blueprints(bp_dir)
        first = {p.name for p in (bp_dir / BLUEPRINT_COLD_DIR_NAME).glob("*.json")}
        # Age the cold copies too, then prune again with nothing new added.
        for p in (bp_dir / BLUEPRINT_COLD_DIR_NAME).glob("*.json"):
            os.utime(p, (old_epoch, old_epoch))
        _prune_blueprints(bp_dir)
        second = {p.name for p in (bp_dir / BLUEPRINT_COLD_DIR_NAME).glob("*.json")}

        assert first == second, "a second prune disturbed the cold store"
        assert not (bp_dir / BLUEPRINT_COLD_DIR_NAME / BLUEPRINT_COLD_DIR_NAME).exists(), (
            "cold store nested into itself -- the eviction tail re-entered"
        )


class TestDemotedNodesStayReachable:
    """Preserved bytes the tooling cannot read are not a preserved record.

    This was first written as ``assert "_COLD_DIR_NAME" in src``. A mutation
    that deleted the constant's DEFINITION did not kill it -- the usage site
    still spells the name, so the substring was still present and the gate
    passed on a build with no fallback at all. Driving the real walk is the
    only version that can fail.
    """

    @staticmethod
    def _load_reflect():
        import importlib.util

        tools_cc = REPO_ROOT / "tools" / "cc"
        if str(tools_cc) not in sys.path:
            sys.path.insert(0, str(tools_cc))
        spec = importlib.util.spec_from_file_location(
            "_cold_demotion_reflect", tools_cc / "reflect_protocol.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _node(session_id, parent_id, stamp, text):
        node = {
            "session_id": session_id,
            "timestamp": stamp,
            "reasoning_entries": [{"decision": text}],
        }
        if parent_id:
            node["parent_session_id"] = parent_id
        return node

    def test_walk_reaches_a_parent_that_was_demoted_to_cold(
        self, tmp_path, monkeypatch
    ):
        """The chain must not terminate at a demoted ancestor. Without the
        fallback this breaks BYTE-IDENTICALLY to a deleted ancestor: same
        truncated chain, no error, no missing-file message."""
        import json

        from espalier._blueprint_limits import BLUEPRINT_COLD_DIR_NAME

        mod = self._load_reflect()

        bp_dir = tmp_path / "cc" / "blueprints"
        (bp_dir / BLUEPRINT_COLD_DIR_NAME).mkdir(parents=True)

        parent = self._node(
            "20260101-000000-parent", None, "2026-01-01T00:00:00+00:00", "PARENT-REASONING"
        )
        child = self._node(
            "20260101-001000-child",
            "20260101-000000-parent",
            "2026-01-01T00:10:00+00:00",
            "CHILD-REASONING",
        )

        # The parent is DEMOTED -- present only in the cold store, exactly as
        # _prune_blueprints leaves it.
        (bp_dir / BLUEPRINT_COLD_DIR_NAME / "20260101-000000-parent.json").write_text(
            json.dumps(parent), encoding="utf-8"
        )
        (bp_dir / "20260101-001000-child.json").write_text(
            json.dumps(child), encoding="utf-8"
        )
        (bp_dir / "latest.json").write_text(json.dumps(child), encoding="utf-8")

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        entries = mod._load_session_entries(tmp_path)

        blob = json.dumps(entries)
        assert "CHILD-REASONING" in blob, (
            "the walk did not even reach the current node -- fixture is wrong, "
            "not the fallback"
        )
        assert "PARENT-REASONING" in blob, (
            "the chain walk stopped at a DEMOTED ancestor. reflect_protocol "
            "must fall back to the cold store, or demotion preserves bytes "
            "the tooling can never read"
        )


class TestPruneSourceCarriesNoUnlink:
    """Pin the change itself. Once the behavioural tests are green nothing
    else distinguishes 'demote' from 'delete', so a future edit could restore
    ``unlink`` and only a slow test would notice. The twins have diverged
    before: ``_truncate_to_cap`` was fixed in the engine copy and not the hook
    copy, and ``test_library_hook_parity`` pins the ``_blueprint_limits``
    CONSTANTS, not these bodies."""

    @pytest.mark.parametrize(
        "modpath",
        ["tools/cc/cognitive_blueprint.py", "espalier/cognitive_blueprint.py"],
    )
    def test_prune_blueprints_demotes_and_does_not_unlink(self, modpath):
        tree = ast.parse((REPO_ROOT / modpath).read_text(encoding="utf-8"))

        fn = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_prune_blueprints"
            ),
            None,
        )
        assert fn is not None, f"no _prune_blueprints in {modpath}"

        calls = [
            n.func.attr
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        assert "unlink" not in calls, (
            f"{modpath}::_prune_blueprints calls .unlink() -- the retention "
            f"cap destroys reasoning"
        )
        assert "replace" in calls, (
            f"{modpath}::_prune_blueprints does not call .replace() -- "
            f"eviction must demote into _cold/, not delete"
        )

    def test_audit_log_prune_demotes_and_does_not_unlink(self):
        """Same class, third site. ``_prune_old_audit_logs`` runs on EVERY
        SessionStart against a store measured at 4,923 files with a 30-day
        window -- i.e. already at the window's edge."""
        tree = ast.parse(
            (REPO_ROOT / "tools" / "cc" / "hooks" / "_integrity.py").read_text(
                encoding="utf-8"
            )
        )
        fn = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_prune_old_audit_logs"
            ),
            None,
        )
        assert fn is not None, "no _prune_old_audit_logs in _integrity.py"
        calls = [
            n.func.attr
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        assert "unlink" not in calls, (
            "_prune_old_audit_logs calls .unlink() -- the harness's own "
            "enforcement record is being destroyed on a 30-day timer"
        )
        assert "replace" in calls, "_prune_old_audit_logs must demote into _cold/"


class TestColdDirNameTwinParity:
    """``_cold`` is duplicated across the no-import boundary on purpose --
    ``tools/cc`` scripts run standalone and a new sibling import would have to
    be added to every fixture that copies a subset. Same policy as
    ``_MEMORY_FILENAME`` and ``LOCAL_ONLY_PREFIXES``. Duplication is only safe
    while something pins it."""

    def test_all_copies_agree(self):
        import re

        from espalier._blueprint_limits import BLUEPRINT_COLD_DIR_NAME

        sites = [
            "tools/cc/_blueprint_limits.py",
            "espalier/_blueprint_limits.py",
            "tools/cc/reflect_protocol.py",
            "tools/cc/execution_plan.py",
            "tools/cc/hooks/_integrity.py",
        ]
        pattern = re.compile(
            r"^_?(?:BLUEPRINT_)?COLD_DIR_NAME\s*=\s*[\"']([^\"']+)[\"']", re.M
        )
        found = {}
        for rel in sites:
            m = pattern.search((REPO_ROOT / rel).read_text(encoding="utf-8"))
            assert m, f"{rel} defines no COLD_DIR_NAME constant"
            found[rel] = m.group(1)

        drift = {k: v for k, v in found.items() if v != BLUEPRINT_COLD_DIR_NAME}
        assert not drift, (
            f"cold-dir name drift against "
            f"BLUEPRINT_COLD_DIR_NAME={BLUEPRINT_COLD_DIR_NAME!r}: {drift}"
        )
