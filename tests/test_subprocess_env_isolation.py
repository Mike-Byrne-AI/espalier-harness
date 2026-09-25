"""Regression: subprocesses to harness scripts must not inherit
parent-shell CLAUDE_PROJECT_DIR.

Category — under any Claude Code session, CLAUDE_PROJECT_DIR is exported
to the real repo root. ``tools/cc/cognitive_blueprint._repo_root()``
prefers that env var over cwd. So a test (or production helper) that
spawns ``cognitive_blueprint.py`` against a constructed tmp_path
without passing ``env=`` silently routes blueprint reads/writes into
the operator's real repo. The two visible regressions were:

  * ``tests/test_hooks.py::test_default_mode_skips_pytest`` — failed
    when the operator's shell exported ESPALIER_STOP_GATE=full
    (run_hook copied os.environ unconditionally).
  * ``tests/test_hooks.py::test_reflect_trigger_records_to_blueprint``
    — failed under any CC session that exported CLAUDE_PROJECT_DIR
    (inline subprocess.run did not pass env=).

Both fixed in commit 907c802. The latent third site
(``test_stop_gate_auto_finalizes_blueprint``) and the production leaks
in ``session_resume.py::_blueprint_summary`` and ``_start_session``
were fixed together with this regression file.

See docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR".
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_CC = REPO_ROOT / "tools" / "cc"
HOOKS_DIR = TOOLS_CC / "hooks"

# Hook subprocess.run calls that spawn either of these scripts must pin
# env= to override an inherited CLAUDE_PROJECT_DIR — cognitive_blueprint's
# _repo_root() reads the env var in preference to cwd. The leaky-sister-
# site catalog this audit guards is documented in ESPALIER_MEMORY.md and the
# docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR" entry.
_BLUEPRINT_REFLECT_TARGETS: tuple[str, ...] = (
    "cognitive_blueprint.py",
    "reflect_protocol.py",
)


def _bootstrap_probe_repo(root: Path) -> str:
    """Set up a minimal repo at ``root`` and start a blueprint inside it.

    Returns the probe blueprint's session_id (canon for the assertions
    below — if a leaked CLAUDE_PROJECT_DIR mis-routes the read, the
    returned session_id will not match what's actually in ``root``).
    """
    (root / "tools" / "cc").mkdir(parents=True)
    (root / "cc" / "blueprints").mkdir(parents=True)
    for fname in ("cognitive_blueprint.py", "_blueprint_limits.py", "_json_safe.py", "_paths.py"):
        (root / "tools" / "cc" / fname).write_bytes((TOOLS_CC / fname).read_bytes())

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    subprocess.run(
        [sys.executable, str(root / "tools" / "cc" / "cognitive_blueprint.py"), "start"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
    )
    data = json.loads((root / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
    return data["session_id"]


class TestSessionResumeRoutingIsolation:
    """``tools/cc/session_resume.py`` must use the path passed in, not
    inherited CLAUDE_PROJECT_DIR.

    Pre-fix, calling ``session_resume.py --mode <X> /target/repo`` while
    the parent shell exports CLAUDE_PROJECT_DIR=/other/repo routed the
    inner ``cognitive_blueprint.py`` subprocess at /other/repo. For
    ``--mode status`` this surfaced as a wrong session_id; for
    ``--mode normal`` it would START a blueprint in the wrong place.
    """

    def test_blueprint_lookup_reads_blueprint_at_path_arg(self, tmp_path):
        """``session_resume.py <path>`` must read the blueprint at
        ``<path>``, ignoring any inherited CLAUDE_PROJECT_DIR.

        Uses ``--mode normal``, which is the mode whose recovery-report
        output embeds the session_id and is therefore observable from
        the outside. The fix in ``_blueprint_summary`` is what's pinned
        here; ``_start_session`` is exercised by the sister test below.
        """
        probe_sid = _bootstrap_probe_repo(tmp_path)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(REPO_ROOT)}

        result = subprocess.run(
            [sys.executable, str(TOOLS_CC / "session_resume.py"),
             "--mode", "normal", str(tmp_path)],
            capture_output=True, text=True, env=env, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert probe_sid in result.stdout, (
            f"session_resume should report probe blueprint {probe_sid!r}, "
            f"got:\n{result.stdout}"
        )

    def test_normal_mode_writes_blueprint_at_path_arg(self, tmp_path):
        """``--mode normal <path>`` must write any new blueprint into
        ``<path>``, not into the leaked CLAUDE_PROJECT_DIR."""
        _bootstrap_probe_repo(tmp_path)
        canary_sid = json.loads(
            (tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8")
        )["session_id"]

        # Point the leak target at a sentinel dir that must NOT receive
        # any new write. Build a parallel minimal layout so the inner
        # cognitive_blueprint would be runnable there if the leak fired.
        sentinel = tmp_path.parent / f"{tmp_path.name}-SENTINEL"
        (sentinel / "tools" / "cc").mkdir(parents=True)
        (sentinel / "cc" / "blueprints").mkdir(parents=True)
        for fname in ("cognitive_blueprint.py", "_blueprint_limits.py", "_json_safe.py", "_paths.py"):
            (sentinel / "tools" / "cc" / fname).write_bytes(
                (TOOLS_CC / fname).read_bytes()
            )

        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(sentinel)}
        try:
            subprocess.run(
                [sys.executable, str(TOOLS_CC / "session_resume.py"),
                 "--mode", "normal", str(tmp_path)],
                capture_output=True, text=True, env=env, timeout=15, encoding="utf-8",
            )
            # Sentinel directory must remain empty of blueprints (no leaked
            # write); tmp_path's latest.json may have been overwritten by a
            # legitimate _start_session call routed to the right place.
            sentinel_blueprints = list(
                (sentinel / "cc" / "blueprints").glob("*.json")
            )
            assert sentinel_blueprints == [], (
                f"session_resume leaked a blueprint write into the "
                f"CLAUDE_PROJECT_DIR target instead of the path arg: "
                f"{sentinel_blueprints}"
            )
            # tmp_path must still have the probe blueprint or a successor —
            # not a stale state from a wrong-routing.
            latest = json.loads(
                (tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8")
            )
            assert latest["session_id"], "tmp_path blueprint cleared"
            assert latest.get("status") in (
                "active", "finalized"
            ) or "session_id" in latest, latest
            # Either the probe blueprint is still latest, or a new one was
            # started (both valid — leak would have written nothing here).
            assert canary_sid or latest["session_id"]
        finally:
            for path in sorted(sentinel.rglob("*"), reverse=True):
                if path.is_file() or path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            if sentinel.exists():
                sentinel.rmdir()


class TestRunHookEnvOverrides:
    """``tests/test_hooks.py::run_hook`` supports None semantics for env
    deletion — a contract test pinning the fix in commit 907c802.

    Each test points ``run_hook`` at a throwaway ``tmp_path`` probe that echoes
    ``ESPALIER_PROBE_VAR`` and asserts the child env directly — rather than
    running a real hook whose exit code is independent of the probed var, which
    left the delete/set effect unobserved. ``run_hook`` joins
    ``HOOKS_DIR / script_name``; an absolute ``script_name`` resets that join to
    the absolute path, so the probe runs in place.
    """

    @staticmethod
    def _write_env_probe(tmp_path):
        probe = tmp_path / "env_probe.py"
        probe.write_text(
            'import os\n'
            'print(os.environ.get("ESPALIER_PROBE_VAR", "<unset>"))\n',
            encoding="utf-8",
        )
        return probe

    def test_run_hook_deletes_var_when_value_none(self, tmp_path, monkeypatch):
        """value=None pops the inherited var from the subprocess env."""
        monkeypatch.setenv("ESPALIER_PROBE_VAR", "leaked")
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        try:
            from test_hooks import run_hook  # noqa: WPS433 (intentional cross-test reuse)
        finally:
            sys.path.pop(0)

        probe = self._write_env_probe(tmp_path)
        result = run_hook(
            str(probe),
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_PROBE_VAR": None},
        )
        assert result.returncode == 0
        # The None-delete popped the inherited "leaked" value from the child env.
        assert result.stdout.strip() == "<unset>"
        assert "leaked" not in result.stdout

    def test_run_hook_sets_var_when_value_string(self, tmp_path):
        """value=str sets the var (the unchanged-behavior side of the contract)."""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        try:
            from test_hooks import run_hook  # noqa: WPS433
        finally:
            sys.path.pop(0)

        probe = self._write_env_probe(tmp_path)
        result = run_hook(
            str(probe),
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_PROBE_VAR": "set"},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "set"


# ── AST-scan contract: every hook subprocess.run that spawns blueprint or
#    reflect_protocol must pin env= to override CLAUDE_PROJECT_DIR ─────────

def _enclosing_function(tree: ast.AST, target: ast.AST) -> ast.FunctionDef | None:
    """Return the FunctionDef ancestor of ``target`` in ``tree``, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for descendant in ast.walk(node):
                if descendant is target:
                    return node
    return None


def _function_names_target_script(func: ast.FunctionDef) -> bool:
    """True if any string literal in ``func`` ends with a target script name.

    The hook idiom is ``script = root / "tools" / "cc" / "<name>.py"``;
    the string literal "<name>.py" lives in the function body whether
    the subprocess argv references it directly or via a variable.
    """
    for node in ast.walk(func):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(node.value.endswith(t) for t in _BLUEPRINT_REFLECT_TARGETS):
                return True
    return False


def _is_subprocess_run(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "run"
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _has_env_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "env" for kw in call.keywords)


def _collect_blueprint_subprocess_calls() -> list[tuple[str, int, str, bool]]:
    """Walk tools/cc/hooks/*.py and return every subprocess.run call inside
    a function that names a blueprint/reflect script.

    Returns: list of (filename, lineno, enclosing_func_name, has_env_kwarg).
    """
    results: list[tuple[str, int, str, bool]] = []
    for hook_file in sorted(HOOKS_DIR.glob("*.py")):
        if hook_file.name.startswith("_"):
            continue  # skip private helpers like _hook_utils
        source = hook_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_subprocess_run(node):
                continue
            func_def = _enclosing_function(tree, node)
            if func_def is None or not _function_names_target_script(func_def):
                continue
            results.append((
                hook_file.name, node.lineno, func_def.name,
                _has_env_kwarg(node),
            ))
    return results


class TestHookSubprocessRoutingIsolation:
    """Every ``subprocess.run`` in ``tools/cc/hooks/*.py`` that spawns
    ``cognitive_blueprint.py`` or ``reflect_protocol.py`` must pass
    ``env=`` to override an inherited ``CLAUDE_PROJECT_DIR``.

    Pre-fix, six call sites across session_start.py, stop_gate.py,
    subagent_stop.py, and reflect_trigger.py lacked ``env=``. Under an
    operator shell that exports ``CLAUDE_PROJECT_DIR`` pointing at one
    repo while Claude works in another, those hooks silently routed
    blueprint reads/writes to the wrong repo. The proven pattern from
    ``tools/cc/session_resume.py::_git_summary``:

        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        subprocess.run([..., script, ...], cwd=str(root), env=env, ...)

    See docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR".
    """

    def test_every_blueprint_or_reflect_subprocess_has_env_override(self):
        leaky = [
            (path, line, func)
            for (path, line, func, has_env)
            in _collect_blueprint_subprocess_calls()
            if not has_env
        ]
        assert not leaky, (
            "subprocess.run sites spawning cognitive_blueprint.py or "
            "reflect_protocol.py must pin env= to override "
            "CLAUDE_PROJECT_DIR. Missing env= at:\n"
            + "\n".join(f"  {p}:{ln} in {fn}" for (p, ln, fn) in leaky)
        )

    def test_audit_finds_the_expected_known_sites(self):
        """Closed-loop-verification-trap defense: if the AST scan ever
        stops finding any blueprint subprocess calls (e.g. someone
        refactors with a wrapper that hides the call shape), the
        contract above silently passes. This positive check guards that.
        """
        results = _collect_blueprint_subprocess_calls()
        files_seen = {path for (path, _, _, _) in results}
        expected_files = {
            "session_start.py",
            "stop_gate.py",
            "subagent_stop.py",
            "reflect_trigger.py",
        }
        assert expected_files <= files_seen, (
            f"AST scan should detect blueprint subprocess calls in "
            f"{expected_files}; only found {files_seen}"
        )
        # At least 6 sites pre-fix (2 session_start + 1 stop_gate +
        # 1 subagent_stop + 2 reflect_trigger). Lower bound; future
        # additions are fine, removals are the regression shape.
        assert len(results) >= 6, (
            f"Expected >=6 blueprint subprocess sites, found {len(results)}: "
            f"{results}"
        )
