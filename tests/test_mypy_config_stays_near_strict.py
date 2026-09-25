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
