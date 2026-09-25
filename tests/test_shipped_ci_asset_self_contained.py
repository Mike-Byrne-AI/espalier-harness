"""A harness-guard.yml job that references a script `espalier install-ci`
does NOT deploy (or `pip install -e .`) must be gated to self-host so it skips
on adopter repos rather than red-failing on day one (§14.1).

Mechanism (TP-246): the self-host gate cannot use `hashFiles()` in a job-level
`if:` — `hashFiles()` is only valid in step contexts, so GitHub rejected the
whole workflow at parse time and created ZERO jobs (the gate was dead on every
adopter AND self-host run). The fix computes the gate in a dedicated
`detect-source` job (a step MAY call `hashFiles()`/read the filesystem) that
exposes an `is_source` output; each self-host job reads it via the `needs`
context, which IS legal in a job-level `if:`. This test pins the new mechanism:
a `detect-source` job whose body checks both `espalier/__init__.py` (engine
present) and `.espalier-fusion` (not a fusion overlay), and each self-host job
gating on `needs.detect-source.outputs.is_source`.

Parses the deployed asset; the asset stays byte-identical to the root copy per
tests/test_package_resource_parity.py. Per TP-148 148-C; mechanism updated by
TP-246."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET = REPO_ROOT / "espalier" / "assets" / "github" / "workflows" / "harness-guard.yml"
DEPLOYED = {"tools/cc/ci_guard.py"}          # install-ci deploy set (cli.cmd_install_ci)
DETECT_JOB = "detect-source"                 # the job that computes the self-host gate
# The job-level gate expression each self-host job reads (legal — `needs` is
# available in a job-level `if:`, unlike `hashFiles()`).
GATE_EXPR = "needs.detect-source.outputs.is_source"
# The two filesystem signals detect-source's step must check.
ENGINE_SENTINEL = "espalier/__init__.py"     # source engine present
FUSION_MARKER = ".espalier-fusion"           # NOT a fusion overlay (marker absent)


def _jobs(text: str) -> dict[str, str]:
    """Split the workflow body into job-name -> job-block (naive YAML split on
    2-space-indented top-level job keys under `jobs:`)."""
    blocks, name, buf = {}, None, []
    in_jobs = False
    for line in text.splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if in_jobs and re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            if name:
                blocks[name] = "\n".join(buf)
            name, buf = line.strip().rstrip(":"), [line]
        elif name:
            buf.append(line)
    if name:
        blocks[name] = "\n".join(buf)
    return blocks


def test_self_host_only_jobs_are_gated():
    """Every job that depends on the espalier source tree (undeployed script,
    editable install, or repo-wide lint) must gate on the detect-source output,
    so it skips on an adopter install rather than red-failing."""
    text = ASSET.read_text(encoding="utf-8")
    ungated = []
    for name, block in _jobs(text).items():
        refs = set(re.findall(r"(?:python3?\s+|bash\s+)([\w./-]+\.(?:py|sh))", block))
        # A job depends on the espalier source tree if it references an
        # undeployed script, installs the package editable, OR runs a repo-wide
        # linter/type-checker (`ruff check .` / `mypy tools/cc/hooks/` — their
        # config + targets only exist on self-host). The ruff clause closes
        # WARN-2 from the 0-A review; the `mypy` clause (TP-321a) closes the same
        # class for the mypy-hooks job — its `mypy tools/cc/hooks/` command has
        # neither a `python/bash <file>` shape, an undeployed script ref, nor
        # `pip install -e`, so without it the contract would pass even if the
        # mypy-hooks gate were forgotten (adopters receive the hooks but not the
        # [tool.mypy] config, so an ungated run red-fails their CI).
        needs_gate = (
            bool(refs - DEPLOYED)
            or "pip install -e" in block
            or "ruff check" in block
            or "mypy " in block
        )
        if needs_gate and GATE_EXPR not in block:
            ungated.append(name)
    assert not ungated, (
        f"harness-guard.yml jobs reference undeployed scripts but lack the "
        f"self-host gate ({GATE_EXPR}): {ungated}. They would red-fail on "
        f"adopter CI (§14.1)."
    )


def test_detect_source_job_checks_engine_and_fusion():
    """TP-246: the gate the self-host jobs read is computed by `detect-source`,
    whose step must check BOTH signals — engine present (`espalier/__init__.py`)
    AND not a fusion overlay (`.espalier-fusion` absent). A fusion overlays
    espalier/, so the engine signal alone is TRUE there; without the marker
    clause the self-host jobs would fire on a fused adopter's first PR and red
    CI under the 'harness is live' banner (TP-181 W1-1). This replaces the old
    per-job `hashFiles('.espalier-fusion')` assertion, which pinned the illegal
    job-level mechanism that startup-failed the whole workflow."""
    text = ASSET.read_text(encoding="utf-8")
    jobs = _jobs(text)
    assert DETECT_JOB in jobs, (
        f"harness-guard.yml has no `{DETECT_JOB}` job; the self-host gate "
        f"({GATE_EXPR}) has nothing to read."
    )
    detect_block = jobs[DETECT_JOB]
    assert ENGINE_SENTINEL in detect_block, (
        f"`{DETECT_JOB}` must check engine presence ({ENGINE_SENTINEL})."
    )
    assert FUSION_MARKER in detect_block, (
        f"`{DETECT_JOB}` must ALSO check the fusion marker ({FUSION_MARKER}) — "
        f"without it the self-host jobs fire on a fused repo (TP-181 W1-1)."
    )
    # Every job that reads the gate must declare the dependency, or the `needs`
    # context is empty and the gate silently evaluates false-y (job skipped —
    # a fail-safe direction, but a latent misconfig worth catching here).
    missing_needs = [
        name
        for name, block in jobs.items()
        if name != DETECT_JOB and GATE_EXPR in block and DETECT_JOB not in _needs_of(block)
    ]
    assert not missing_needs, (
        f"jobs read {GATE_EXPR} but do not list `{DETECT_JOB}` in `needs:`: "
        f"{missing_needs}. The gate would evaluate empty and the job would "
        f"never run."
    )


def _needs_of(block: str) -> str:
    """Return the text of a job's `needs:` declaration (inline scalar or list
    form), or '' if absent — enough to check membership by substring."""
    m = re.search(r"^    needs:\s*(.+)$", block, re.MULTILINE)
    return m.group(1) if m else ""
