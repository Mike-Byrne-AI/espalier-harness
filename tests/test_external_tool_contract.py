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

import re
import sys
from pathlib import Path

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
