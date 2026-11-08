"""TP-146 contract: ``pyproject.toml [tool.ruff.lint]`` must keep the
HIGH-severity rule subset.

TP-147 147-C extension: ``[tool.ruff.lint.per-file-ignores]`` entries
must match ``espalier.ruff_config_contract.ALLOWED_PER_FILE_IGNORES``.
The inverse-direction sibling — REQUIRED_RULES pins what the lint
select MUST include; the allowlist pins what the ignore block MAY
include — closes the asymmetry surfaced by FM-17.

If a future edit drops one of REQUIRED_RULES, the bug class that ruff
was catching can silently re-introduce. If a future edit adds a
per-file ignore not in ALLOWED_PER_FILE_IGNORES, TP-146's gate
silently rolls back for that file. The complementary
``harness-guard.yml`` ``ruff-lint`` job runs the actual check; these
tests pin the canonical sets so drift is loud at unit-test time, not
silent at CI time.
"""
from __future__ import annotations

from pathlib import Path

import tomllib

from espalier.ruff_config_contract import ALLOWED_PER_FILE_IGNORES

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_RULES = frozenset({
    "F401",  # TP-196: unused-import gate — pinned so the dead-import class
             # (113 instances at round 7) cannot silently regrow if a future
             # edit drops it from select.
    "F821", "F811",
    "S102", "S110", "S202", "S310", "S602", "S605", "S608",
    "B017", "B904",
})


def _pyproject_text() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def _per_file_ignores_section_text(text: str) -> str:
    """Slice the ``[tool.ruff.lint.per-file-ignores]`` block from
    pyproject. Used by the reason-substring check so rationale comments
    can document the surface they govern."""
    lines = text.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines)
            if "[tool.ruff.lint.per-file-ignores]" in line
        )
    except StopIteration:
        return ""
    section: list[str] = [lines[start]]
    for line in lines[start + 1:]:
        if line.lstrip().startswith("[") and not line.lstrip().startswith("[["):
            break
        section.append(line)
    return "\n".join(section)


def test_pyproject_ruff_config_includes_security_rules():
    data = tomllib.loads(_pyproject_text())
    select = set(
        data.get("tool", {}).get("ruff", {}).get("lint", {}).get("select", [])
    )
    missing = REQUIRED_RULES - select
    assert not missing, (
        f"pyproject.toml [tool.ruff.lint] is missing TP-146 pinned rules: "
        f"{sorted(missing)}. Re-introducing any of these rules means the "
        f"bug class it catches can re-occur silently. If you intend to "
        f"drop a rule, also drop it from REQUIRED_RULES with documented "
        f"reason."
    )


def test_per_file_ignores_match_allowlist():
    text = _pyproject_text()
    data = tomllib.loads(text)
    actual = data.get("tool", {}).get("ruff", {}).get("lint", {}).get(
        "per-file-ignores", {}
    )
    section_text = _per_file_ignores_section_text(text)
    allowed_by_glob = {row[0]: row for row in ALLOWED_PER_FILE_IGNORES}
    drift: list[str] = []
    for glob, rules in actual.items():
        if glob not in allowed_by_glob:
            drift.append(
                f"per-file-ignores entry {glob!r} not in "
                f"ALLOWED_PER_FILE_IGNORES — add an explicit row in "
                f"espalier/ruff_config_contract.py with a reason "
                f"substring, or drop the ignore."
            )
            continue
        _, allowed_rules, reason_substring = allowed_by_glob[glob]
        rules_set = set(rules)
        if not rules_set.issubset(allowed_rules):
            drift.append(
                f"per-file-ignores {glob!r} ignores {sorted(rules_set)} "
                f"but allowlist permits only {sorted(allowed_rules)}. "
                f"Either narrow the pyproject entry or expand the "
                f"allowlist row with rationale."
            )
        if reason_substring not in section_text:
            drift.append(
                f"per-file-ignores {glob!r} missing required reason "
                f"substring {reason_substring!r} in the section "
                f"comments. The rationale must stay at the surface."
            )
    assert not drift, (
        "TP-147 147-C: per-file-ignores allowlist drift:\n  "
        + "\n  ".join(drift)
    )



# The files the "update Python" message runs through on a host below the
# floor, each with the oldest syntax it must parse under: the five the update
# deny runs through, at py310 (the operator's 1-G ruling of 2026-11-07,
# nothing wider), and `espalier/__init__.py`, the engine's own floor sentence,
# at py39 (air's ruling on request 79c59b: stock macOS python3 is 3.9.6, and a
# `match` there would kill the sentence on it). A below-floor interpreter
# compiles a file before running a line of it, so one construct newer than
# the target in any of them turns the message into a SyntaxError (for a deny
# hook, an exit 1, which Claude Code reads as non-blocking). ruff takes its
# syntax target from `requires-python`, so without this table `ruff check .`
# stops refusing that syntax everywhere the day the floor moves.
FLOOR_MESSAGE_SYNTAX_TARGETS = {
    "tools/cc/hooks/_start_refusal.py": "py310",
    "tools/cc/hooks/write_guard.py": "py310",
    "tools/cc/hooks/plan_guard.py": "py310",
    "tools/cc/hooks/config_guard.py": "py310",
    "tools/cc/hooks/stop_gate.py": "py310",
    "espalier/__init__.py": "py39",
}


def test_the_floor_message_files_keep_their_syntax_targets():
    """Strength, not text: an entry may join the table, none of these may
    leave it or move off its target, and each names a file that exists (a
    renamed hook would otherwise leave a key that matches nothing)."""
    table = (tomllib.loads(_pyproject_text()).get("tool", {}).get("ruff", {})
             .get("per-file-target-version", {}))
    drift = [f"{path}: {table.get(path)!r}, want {want!r}"
             for path, want in sorted(FLOOR_MESSAGE_SYNTAX_TARGETS.items())
             if table.get(path) != want]
    drift += [f"{path}: no such file" for path in sorted(FLOOR_MESSAGE_SYNTAX_TARGETS)
              if not (REPO_ROOT / path).is_file()]
    assert not drift, (
        "[tool.ruff] per-file-target-version no longer holds the floor "
        "message's files at their targets:\n  " + "\n  ".join(drift)
    )
