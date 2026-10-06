"""Contract: ``pyproject.toml [tool.mypy]`` must keep the near-strict flags
that make the hook-layer type gate fail-open-proof.

The ``harness-guard.yml`` ``mypy-hooks`` CI job runs the actual ``mypy
tools/cc/hooks/`` check; this test pins the *config* so a future edit dropping
(say) ``disallow_untyped_defs = true`` is loud at unit-test time rather than
silently green in a CI job now running a weaker check. ``disallow_untyped_defs``
is the load-bearing flag: it forces every hook to declare its return type, and
mypy's return check then flags a ``-> int``/``-> bool`` that falls off the end
(implicit ``None`` → falsy → ALLOW, a silent fail-open); ``warn_no_return`` is
confirmatory. A second test pins that the CI *job* still exists and runs the
check — a gate pinned in config but silently deletable in CI is no gate.

Mirrors ``tests/test_ruff_config_includes_security_rules.py`` (pin the canonical
config so drift is loud at unit-test time, not silent at CI time).
"""
from __future__ import annotations

import pytest

import ast
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 fallback (espalier supports >=3.10)
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
# The shipped workflow asset; byte-identical to the root .github/ copy
# (pinned by test_package_resource_parity), so checking one copy suffices.
SHIPPED_WORKFLOW = REPO_ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml"

# The three flags that make the near-strict gate discriminate. Dropping any one
# silently weakens it; see the [tool.mypy] rationale in pyproject.toml.
REQUIRED_NEAR_STRICT_FLAGS = (
    "disallow_untyped_defs",
    "warn_no_return",
    "no_implicit_optional",
)


def _mypy_config() -> dict:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data.get("tool", {}).get("mypy", {})


def test_mypy_config_keeps_near_strict_flags():
    cfg = _mypy_config()
    for flag in REQUIRED_NEAR_STRICT_FLAGS:
        assert cfg.get(flag) is True, (
            f"[tool.mypy] must keep {flag} = true — dropping it silently weakens "
            f"the hook-layer type gate (the fail-open class it exists to catch)"
        )
    # The target view, pinned beside the flags: one interpreter version and one
    # platform, so a red reproduces on every CI cell and on every local host. With
    # no `platform`, mypy checks under the host's `sys.platform`, and on Windows
    # typeshed hides `os.getuid` and `fcntl`: the hooks guard both at runtime, so
    # the gate reds there on code that is correct, and a line that is red on every
    # run on one host teaches that host to skip it.
    assert cfg.get("python_version") == "3.10", (
        f"[tool.mypy] python_version must stay the oldest supported interpreter, "
        f"got {cfg.get('python_version')!r}"
    )
    assert cfg.get("platform") == "linux", (
        f"[tool.mypy] must pin platform = \"linux\" (the view of every CI cell), got "
        f"{cfg.get('platform')!r}; without it the hook gate reds on a Windows host "
        f"on platform-guarded code"
    )


# Under `platform = "linux"` mypy treats a `sys.platform == "win32"` arm as
# unreachable and checks nothing in it. That is safe only while every such arm
# holds nothing to type. The arms allowed: `pass`, a docstring, a bare or
# constant return, a returned f-string of names, and a raise of a builtin
# exception built from constants. An arm that grows real code (a call, an
# attribute read, an assignment) must be typed some other way: under
# `--platform win32`, or moved behind a function mypy sees.
_TRIVIAL_EXCEPTIONS = frozenset({"OSError", "RuntimeError", "NotImplementedError", "ValueError"})


def _is_trivial_expr(node: ast.expr | None) -> bool:
    if node is None or isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.JoinedStr):
        return all(
            isinstance(v, ast.Constant)
            or (isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name))
            for v in node.values
        )
    return False


def _is_trivial_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Constant)
    if isinstance(stmt, ast.Return):
        return _is_trivial_expr(stmt.value)
    if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
        call = stmt.exc
        return (
            isinstance(call.func, ast.Name) and call.func.id in _TRIVIAL_EXCEPTIONS
            and not call.keywords and all(_is_trivial_expr(a) for a in call.args)
        )
    return False


def _windows_only_arm(node: ast.AST) -> list | ast.expr | None:
    """The arm of an ``if``/conditional expression that only Windows runs, when
    its test is a ``sys.platform`` comparison mypy narrows on; else None."""
    if not isinstance(node, (ast.If, ast.IfExp)):
        return None
    test = node.test
    if (
        isinstance(test, ast.Compare) and len(test.ops) == 1
        and ast.unparse(test.left) == "sys.platform"
        and isinstance(test.comparators[0], ast.Constant)
        and str(test.comparators[0].value).startswith("win")
    ):
        if isinstance(test.ops[0], ast.Eq):
            return node.body
        if isinstance(test.ops[0], ast.NotEq):
            return node.orelse
    if (
        isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)
        and test.func.attr == "startswith" and ast.unparse(test.func.value) == "sys.platform"
        and test.args and isinstance(test.args[0], ast.Constant)
        and str(test.args[0].value).startswith("win")
    ):
        return node.body
    return None


def _untypable_windows_arms(source: str) -> list[int]:
    """Line numbers of Windows-only arms that hold something mypy would type."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        arm = _windows_only_arm(node)
        if arm is None:
            continue
        if isinstance(arm, list):
            trivial = all(_is_trivial_stmt(s) for s in arm)
        else:
            trivial = _is_trivial_expr(arm)
        if not trivial:
            bad.append(node.lineno)
    return sorted(bad)


def test_every_windows_only_arm_in_the_gate_scope_holds_nothing_to_type():
    cfg = _mypy_config()
    assert cfg.get("platform") == "linux", "this pin exists because of the platform pin"
    offenders, arms = [], 0
    for scope in cfg.get("files", []):
        for path in sorted((REPO_ROOT / scope).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            arms += sum(_windows_only_arm(n) is not None for n in ast.walk(ast.parse(source)))
            offenders += [f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
                          for line in _untypable_windows_arms(source)]
    assert arms, "found no `sys.platform` arm at all -- the matcher broke"
    assert not offenders, (
        "Windows-only arms that mypy cannot see under platform = \"linux\" now hold "
        f"code it would type: {offenders}. Type them under `--platform win32`, or move "
        "the code behind a function the gate checks."
    )


def test_the_windows_arm_pin_refuses_an_arm_with_real_code():
    planted = (
        "import os, sys\n"
        "if sys.platform == 'win32':\n"
        "    uid = os.getuid()\n"
        "elif sys.platform != 'win32':\n"
        "    pass\n"
        "else:\n"
        "    raise OSError('x')\n"
        "N = 20 if sys.platform == 'win32' else 1\n"
        "M = os.getpid() if sys.platform.startswith('win') else 1\n"
    )
    assert _untypable_windows_arms(planted) == [2, 9]


def test_mypy_config_scopes_to_hook_layer():
    # Tier 1 is the hooks only. A `files` widening to espalier/ would turn on
    # ~354 near-strict findings before the Tier-2 engine work is ready.
    cfg = _mypy_config()
    assert cfg.get("files") == ["tools/cc/hooks"], (
        f"[tool.mypy] files must scope to the hook layer, got {cfg.get('files')!r}"
    )


def _job_block(wf_text: str, job: str) -> str:
    """Slice one job block out of the workflow (naive 2-space-indented split,
    mirroring tests/test_shipped_ci_asset_self_contained.py::_jobs)."""
    out: list[str] = []
    capturing = False
    for line in wf_text.splitlines():
        if re.match(rf"^  {re.escape(job)}:\s*$", line):
            capturing = True
            out.append(line)
            continue
        if capturing:
            if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):  # next top-level job
                break
            out.append(line)
    return "\n".join(out)


@pytest.mark.contract
def test_mypy_hooks_ci_job_exists_and_runs_the_check():
    # A gate pinned in [tool.mypy] is worthless if the CI job that runs it can be
    # silently deleted or weakened. Pin the shipped workflow's mypy-hooks job:
    # it must exist, run `mypy tools/cc/hooks`, and stay self-host-gated (else it
    # red-fails adopter CI — adopters get the hooks but not the near-strict config).
    block = _job_block(SHIPPED_WORKFLOW.read_text(encoding="utf-8"), "mypy-hooks")
    assert block, "the mypy-hooks CI job was removed from harness-guard.yml"
    # Check the actual `run:` step command, not a bare substring — the job's
    # rationale comment also mentions `mypy tools/cc/hooks/`, so a substring test
    # would pass even if the command were gutted (caught by earn-red).
    assert "run: mypy tools/cc/hooks" in block, (
        "mypy-hooks job no longer runs `mypy tools/cc/hooks`"
    )
    assert "needs.detect-source.outputs.is_source == 'true'" in block, (
        "mypy-hooks job lost its self-host gate — it would red-fail adopter CI"
    )
    # The weakening that leaves the job in place: `continue-on-error: true` keeps
    # every assertion above green while the gate can no longer fail a merge. It
    # is the lowest-friction unblock for a red job, which is exactly when it
    # would be reached for (failure-mode pass, 2026-09-06, with the job red on
    # main across two pushes).
    assert "continue-on-error" not in block, (
        "mypy-hooks job was made non-blocking -- the gate exists but cannot fail a merge"
    )


@pytest.mark.contract
def test_ruff_lint_ci_job_exists_and_runs_the_check():
    # The structural twin of mypy-hooks: adjacent job, same self-host gate, a
    # config-pinning test of its own (tests/test_ruff_config_includes_security_rules.py)
    # but, until 2026-09-06, no pin that the job itself exists and blocks.
    block = _job_block(SHIPPED_WORKFLOW.read_text(encoding="utf-8"), "ruff-lint")
    assert block, "the ruff-lint CI job was removed from harness-guard.yml"
    assert "run: ruff check ." in block, "ruff-lint job no longer runs `ruff check .`"
    assert "needs.detect-source.outputs.is_source == 'true'" in block, (
        "ruff-lint job lost its self-host gate — it would red-fail adopter CI"
    )
    assert "continue-on-error" not in block, (
        "ruff-lint job was made non-blocking -- the gate exists but cannot fail a merge"
    )
