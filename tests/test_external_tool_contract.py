"""TP-147 147-B: every name in
``espalier.doctor._LOAD_BEARING_EXTERNAL_TOOLS`` must be supported by a
three-surface infrastructure stack:

1. **Dev-extras entry** in ``pyproject.toml [project.optional-dependencies].dev``
   — so ``pip install -e '.[dev]'`` brings the tool in for local dev.
2. **Doctor probe** via ``_check_external_tool`` — surfaces missing
   binaries through ``espalier doctor``.
3. **SessionStart banner** via ``tools/cc/hooks/session_start.py``'s
   ``_SESSION_START_LOAD_BEARING_TOOLS`` tuple — surfaces missing
   binaries at session boot.

The two side lists (doctor / session_start) are intentionally
parallel-and-separate to preserve the ``tools/cc/`` zero-espalier-imports
invariant. This contract enforces lock-step membership: adding a tool
to one side without the other fails the test.

This is the inverse-direction sibling of TP-146's ``REQUIRED_RULES`` —
that contract pinned which ruff rules MUST appear in the lint config;
this one pins the infrastructure every load-bearing external CLI tool
MUST carry.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

from espalier.doctor import _LOAD_BEARING_EXTERNAL_TOOLS


def _dev_extras_packages() -> set[str]:
    text = (REPO_ROOT / "pyproject.toml").read_bytes()
    data = tomllib.loads(text.decode("utf-8"))
    deps = data["project"]["optional-dependencies"].get("dev", [])
    names: set[str] = set()
    name_re = re.compile(r"^([A-Za-z0-9_.\-]+)")
    for spec in deps:
        m = name_re.match(spec)
        if m:
            names.add(m.group(1).lower())
    return names


def _session_start_tools() -> set[str]:
    """Parse the tuple-of-pairs from session_start.py without importing it.

    The hook module sits in tools/cc/hooks/ with sibling-import wiring;
    importing it from a test would require sys.path setup AND would
    perform the hook's own module-load side effects. Parsing source
    text avoids that coupling.

    Approach: locate the marker assignment line, then walk forward
    until the next module-level ``def`` / ``class`` / blank-line-then-
    non-indent. Within that region, every quoted name in a
    ``("name", "hint")`` pair is the first tuple element.
    """
    text = (
        REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py"
    ).read_text(encoding="utf-8")
    marker = "_SESSION_START_LOAD_BEARING_TOOLS"
    lines = text.splitlines()
    region: list[str] = []
    inside = False
    for line in lines:
        if not inside:
            if marker in line:
                inside = True
                region.append(line)
            continue
        # End of the assignment region: a top-level def/class/comment
        # block, or a line ending with a closing paren that re-aligns
        # to column 0.
        if line.startswith("def ") or line.startswith("class "):
            break
        region.append(line)
        if line.rstrip().endswith(")") and not line.startswith(" "):
            break
    region_text = "\n".join(region)
    found: set[str] = set()
    for pair_match in re.finditer(
        r'\(\s*"([A-Za-z0-9_.\-]+)"\s*,', region_text
    ):
        found.add(pair_match.group(1).lower())
    return found


def test_every_load_bearing_tool_has_dev_extras_entry():
    dev_packages = _dev_extras_packages()
    missing = [
        name for name in _LOAD_BEARING_EXTERNAL_TOOLS
        if name.lower() not in dev_packages
    ]
    assert not missing, (
        f"TP-147 147-B: tools in _LOAD_BEARING_EXTERNAL_TOOLS missing "
        f"from `[project.optional-dependencies].dev` in pyproject.toml: "
        f"{missing}. Adding a load-bearing tool requires the parity "
        f"triple — see docs/CONVENTIONS.md 'External-tool dependency "
        f"contract'."
    )


#: The gates whose OUTPUT is the finding. A new release of either can add,
#: stabilise or remove a check, so a floating range lets one release red every
#: required ``test (3.x)`` cell at once with no change in this repository, and
#: the red reads as an ordinary finding (DEF-4014). Each is pinned to one exact
#: version in the dev extra, and every workflow job that runs one installs it
#: from there, so the pin has one home and a bump is one pull request.
_FINDING_GATES: tuple[str, ...] = ("ruff", "mypy")
#: The proof tier's runners left on a range, each with its reason. pytest runs
#: the tests rather than reporting findings of its own.
_RANGED_RUNNERS: dict[str, str] = {"pytest": "runs the tests; reports no finding of its own"}
_EXACT_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==(\d+(?:\.\d+)+)$")
#: Where CI is defined: the root workflows, the packaged harness-guard source
#: they are generated from, and any composite action.
_WORKFLOW_GLOBS: tuple[tuple[Path, str], ...] = (
    (REPO_ROOT / ".github" / "workflows", "*.y*ml"),
    (REPO_ROOT / "espalier" / "assets" / "github" / "workflows", "*.y*ml"),
    (REPO_ROOT / ".github" / "actions", "**/action.y*ml"),
)
#: A command position: a line start or a shell separator, then blanks.
_CMD_START = r"(?:^|[;&|(\n]|\$\()[ \t]*"
#: A gate word, path-qualified or not (``.venv/bin/ruff``, ``ruff.exe``).
_GATE_WORD = r"(?:[\w.~${}-]*[\\/])*(ruff|mypy)(?:\.exe)?(?![\w.-])"
#: Installers that take a requirement spec, and runners that fetch their own copy.
_INSTALLER = (r"(?:(?:pip3?|python3?\s+-m\s+pip|py\s+-3\s+-m\s+pip|uv\s+pip)\s+install"
              r"|uv\s+tool\s+install|pipx\s+install|uv\s+add)\b")
_FETCH_AND_RUN = r"(?:uvx|pipx\s+run|uv\s+tool\s+run)\s+(?:-\S+\s+)*"
_RUNS_A_GATE = re.compile(
    _CMD_START + r"(?:(?:python3?|py\s+-3)\s+-m\s+|uv\s+run\s+(?:-\S+\s+)*|" + _FETCH_AND_RUN + r")?" + _GATE_WORD
    + r"|scripts[\\/]proof_tier\.py\b[^;&|\n]*--run",
    re.MULTILINE,
)
_INSTALL_ARGS = re.compile(_INSTALLER + r"([^;&|\n]*)")
_FETCHES_A_GATE = re.compile(_CMD_START + _FETCH_AND_RUN + r"(ruff|mypy)(?![\w.-])", re.MULTILINE)
_USES_A_GATE = re.compile(r"(?<![a-z0-9])(ruff|mypy)(?![a-z0-9])", re.IGNORECASE)
_INSTALLS_DEV_EXTRA = re.compile(
    r"(?:pip3?|python3?\s+-m\s+pip|py\s+-3\s+-m\s+pip|uv\s+pip)\s+install\b[^;&|\n]*\.\[[^\]]*\bdev\b[^\]]*\]"
)


def _joined(run: str) -> str:
    """A ``run`` block with its backslash-continued lines joined."""
    return re.sub(r"\\\r?\n", " ", run)


def _runs_a_gate(run: str) -> bool:
    return bool(_RUNS_A_GATE.search(_joined(run)))


def _installs_dev_extra(run: str) -> bool:
    return bool(_INSTALLS_DEV_EXTRA.search(_joined(run)))


def _own_spec_offences(run: str, uses: str = "") -> list[str]:
    """Every way one step gets a gate from a spec other than the dev extra's:
    an installer naming it, a fetch-and-run of it, or an action named for it."""
    run = _joined(run)
    found: list[str] = []
    for m in _INSTALL_ARGS.finditer(run):
        for token in m.group(1).split():
            token = token.strip("'\"")
            name = re.match(r"[A-Za-z0-9_.\-]+", token)
            if not token.startswith("-") and name and name.group(0).lower() in _FINDING_GATES:
                found.append(m.group(0).strip())
    found += [m.group(0).strip() for m in _FETCHES_A_GATE.finditer(run)]
    if _USES_A_GATE.search(uses):
        found.append(f"uses: {uses}")
    return found


def _dev_extras_specs() -> list[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_bytes().decode("utf-8"))
    return [spec.replace(" ", "") for spec in data["project"]["optional-dependencies"].get("dev", [])]


def _proof_tier_runners() -> tuple[str, ...]:
    spec = importlib.util.spec_from_file_location("_proof_tier_for_pins", REPO_ROOT / "scripts" / "proof_tier.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module._RUNNERS)


def _workflow_jobs():
    """``(path, job id, steps)`` for every job of every workflow file, and the
    steps of every composite action (job id ``runs``)."""
    yaml = pytest.importorskip("yaml")
    files = sorted({p for root, pattern in _WORKFLOW_GLOBS for p in root.glob(pattern)})
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data.get("jobs"), dict):
            for job_id, job in data["jobs"].items():
                yield path, job_id, [s for s in (job or {}).get("steps") or [] if isinstance(s, dict)]
        elif isinstance(data.get("runs"), dict):
            yield path, "runs", [s for s in data["runs"].get("steps") or [] if isinstance(s, dict)]


@pytest.mark.contract
def test_every_proof_tier_runner_is_a_pinned_gate_or_named_as_ranged():
    """Closed world both ways: a runner the tier gains is pinned or named here,
    and a name here that the tier dropped is removed."""
    runners = set(_proof_tier_runners())
    declared = set(_FINDING_GATES) | set(_RANGED_RUNNERS)
    assert runners == declared, (
        f"scripts/proof_tier.py::_RUNNERS is {sorted(runners)}, this contract declares "
        f"{sorted(declared)}: put a new runner in _FINDING_GATES (pinned exactly in the dev "
        f"extra) or in _RANGED_RUNNERS with its reason, drop a name the tier no longer runs, "
        f"and give the runner its own branch in proof_tier's run_commands and version_lines."
    )


@pytest.mark.contract
def test_each_finding_gate_is_pinned_to_one_exact_version_in_the_dev_extra():
    specs = _dev_extras_specs()
    for gate in _FINDING_GATES:
        mine = [s for s in specs if re.match(rf"{re.escape(gate)}(?![A-Za-z0-9_.\-])", s, re.IGNORECASE)]
        assert len(mine) == 1, f"the dev extra names {gate} {len(mine)} times: {mine}"
        assert _EXACT_PIN.match(mine[0]), (
            f"the dev extra takes {mine[0]!r}: pin {gate} to one exact version ({gate}==X.Y.Z), "
            f"so a new release cannot red every required cell with no change here; bump it "
            f"in its own pull request, whose CI then runs the new version."
        )


@pytest.mark.contract
def test_no_workflow_gets_a_finding_gate_from_a_spec_of_its_own():
    """The absence arm: a step that installs, fetches or uses ruff or mypy by a
    spec of its own carries a second version beside the dev extra's pin."""
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}::{job_id}: {hit}"
        for path, job_id, steps in _workflow_jobs()
        for step in steps
        for hit in _own_spec_offences(str(step.get("run", "")), str(step.get("uses", "")))
    ]
    assert not offenders, (
        "install the finding gates from the dev extra (pip install -e '.[dev]'), never from a "
        "spec, fetch or action of the workflow's own; the harness-guard workflow's source is "
        "espalier/assets/github/workflows/harness-guard.yml (sync it with "
        "scripts/sync_github_workflow_asset.py):\n" + "\n".join(offenders)
    )


@pytest.mark.contract
def test_each_job_that_runs_a_finding_gate_installs_the_dev_extra():
    """The presence arm, calibrated: the harness-guard lint and type cells are
    found, so a pattern that stops matching cannot pass on an empty set."""
    found: set[tuple[str, str]] = set()
    missing: list[str] = []
    for path, job_id, steps in _workflow_jobs():
        runs = [str(step.get("run", "")) for step in steps]
        if not any(_runs_a_gate(run) for run in runs):
            continue
        found.add((path.name, job_id))
        if not any(_installs_dev_extra(run) for run in runs):
            missing.append(f"{path.relative_to(REPO_ROOT).as_posix()}::{job_id}")
    assert {("harness-guard.yml", "ruff-lint"), ("harness-guard.yml", "mypy-hooks")} <= found, sorted(found)
    assert not missing, (
        "these jobs run ruff or mypy without installing the dev extra, so they run a "
        "version the pin does not name:\n" + "\n".join(missing)
    )


_RUNS_A_GATE_ROWS = [
    ("mypy", True), ("ruff check .", True), (".venv/bin/ruff check .", True),
    ("$HOME/.venv/Scripts/ruff.exe check .", True), ("python -m mypy tools/cc/hooks/", True),
    ("uvx ruff check .", True), ("pipx run ruff check .", True), ("cd x && mypy .", True),
    ("python scripts/proof_tier.py \\\n  --run --leg parallel", True),
    ("echo mypy is slow", False), ("git diff -- ruff.toml", False), ("pip install -e '.[dev]'", False),
]
_OWN_SPEC_ROWS = [
    ("pip install 'ruff>=0.5,<1.0'", "", True), ("pip3 install ruff==0.17.0", "", True),
    ("python -m pip install --upgrade mypy", "", True), ("uv tool install ruff@0.17.0", "", True),
    ("pip install \\\n  ruff", "", True), ("uvx ruff@0.17.0 check .", "", True),
    ("", "astral-sh/ruff-action@v3", True), ("pipx install mypy", "", True),
    ("pip install -e '.[dev]' && ruff check .", "", False), ("pip install -e '.[dev]'; mypy x", "", False),
    ("pip install pyyaml", "", False), ("", "actions/setup-python@v5", False),
]
_DEV_EXTRA_ROWS = [
    ("pip install -e '.[dev]'", True), ("pip install -e .[dev]", True),
    ('python -m pip install -e ".[dev]"', True), ("pip install --upgrade -e '.[dev,docs]'", True),
    ("pip install -e .", False), ("pip install '.[docs]'", False),
]


@pytest.mark.contract
@pytest.mark.parametrize(("run", "expected"), _RUNS_A_GATE_ROWS)
def test_the_gate_reader_finds_a_gate_only_at_a_command_position(run, expected):
    """Both reviewers' shapes, each a red this reader must earn: a bare trailing
    name, a path-qualified binary, a fetch-and-run, a continued line; and prose
    or a file name that only mentions a gate."""
    assert _runs_a_gate(run) is expected, run


@pytest.mark.contract
@pytest.mark.parametrize(("run", "uses", "expected"), _OWN_SPEC_ROWS)
def test_the_spec_reader_flags_every_second_source_of_a_gate(run, uses, expected):
    assert bool(_own_spec_offences(run, uses)) is expected, (run, uses)


@pytest.mark.contract
@pytest.mark.parametrize(("run", "expected"), _DEV_EXTRA_ROWS)
def test_the_install_reader_knows_the_dev_extra_however_it_is_spelled(run, expected):
    assert _installs_dev_extra(run) is expected, run


@pytest.mark.contract
def test_dependabot_bumps_each_finding_gate_in_a_pull_request_of_its_own():
    """A grouped bump would move ruff and mypy together, and a red from one
    would hold the other; each gate stays out of every pip group."""
    import fnmatch

    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    pip_updates = [u for u in data.get("updates") or [] if u.get("package-ecosystem") == "pip"]
    assert pip_updates, "no pip ecosystem in .github/dependabot.yml"
    grouped: list[str] = []
    for update in pip_updates:
        for name, group in (update.get("groups") or {}).items():
            for gate in _FINDING_GATES:
                caught = any(fnmatch.fnmatch(gate, p) for p in group.get("patterns") or [])
                excluded = any(fnmatch.fnmatch(gate, p) for p in group.get("exclude-patterns") or [])
                if caught and not excluded:
                    grouped.append(f"{gate} in group {name!r}")
    assert not grouped, (
        "add each finding gate to the group's exclude-patterns in .github/dependabot.yml, so its "
        "bump is a pull request of its own: " + ", ".join(grouped)
    )


def test_every_load_bearing_tool_has_session_start_warn_path():
    session_tools = _session_start_tools()
    doctor_tools = {name.lower() for name in _LOAD_BEARING_EXTERNAL_TOOLS}
    missing_in_session_start = doctor_tools - session_tools
    extra_in_session_start = session_tools - doctor_tools
    assert not missing_in_session_start, (
        f"TP-147 147-B: tools in doctor._LOAD_BEARING_EXTERNAL_TOOLS not "
        f"named in session_start._SESSION_START_LOAD_BEARING_TOOLS: "
        f"{sorted(missing_in_session_start)}. The two lists are parallel "
        f"by design (tools/cc/ zero-espalier-imports invariant)."
    )
    assert not extra_in_session_start, (
        f"TP-147 147-B: tools in session_start._SESSION_START_LOAD_BEARING_TOOLS "
        f"not named in doctor._LOAD_BEARING_EXTERNAL_TOOLS: "
        f"{sorted(extra_in_session_start)}. Add the doctor-side entry too."
    )
