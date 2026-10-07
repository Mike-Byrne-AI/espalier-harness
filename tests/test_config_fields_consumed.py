"""Every ``HarnessConfig`` field has a behavioural consumer, or a declared
display-only reason (TP-461 Fix 3, closing ``DEF-951``'s documented-but-unread
zones).

The population is derived -- ``dataclasses.fields(HarnessConfig)`` -- and each
field is checked against a DECLARED consumer map with a witness: the
``path::symbol`` that acts on it. The test parses that file (AST, not grep),
finds the symbol, and asserts the field name appears inside the symbol's own
source. A field with no map entry reds; a map entry whose symbol is gone reds;
a map entry for a field that no longer exists reds. A grep count was refuted at
authoring: ``harness_config.py`` and ``cli.py`` already mention
``protected_paths`` (the drift compare), so a count was green before the hook
read the field and would stay green after the reader's use was deleted.

Earn-the-red (recorded at execution 2026-09-30): before 1-B landed, the zone
rows' witness did not exist and both zone fields redded here. The mutation
that keeps this honest is renaming the key inside ``ADOPTER_ZONE_KEYS`` (the
constant the reader iterates); the 2-A review drove it and it reds.
"""
from __future__ import annotations

import ast
import dataclasses
import warnings
from pathlib import Path

import pytest

from espalier.config import load_config
from espalier.models import HarnessConfig

REPO_ROOT = Path(__file__).resolve().parents[1]

# The floor the census discovered its population at (2026-09-30, thirteen
# fields; the first draft said fourteen and the drive corrected it). A field
# added without a map entry reds below regardless; the floor catches the other
# direction -- the dataclass losing fields without anyone noticing the reader
# census shrank.
FIELD_FLOOR = 13

DISPLAY_ONLY = "display-only"

# field -> "path::symbol" (the code that ACTS on the field), or
#          (DISPLAY_ONLY, "<why no behaviour is the design>").
CONSUMERS: dict[str, str | tuple[str, str, str]] = {
    "preferred_profiles": "espalier/profiles.py::classify_repo",
    "suppress_profiles": "espalier/profiles.py::classify_repo",
    "extra_actions": "espalier/harness_config.py::build_harness_config",
    "suppress_actions": "espalier/harness_config.py::build_harness_config",
    "include_paths": "espalier/analyze.py::_path_allowed",
    "exclude_paths": "espalier/analyze.py::_path_allowed",
    # The two zone fields: documented as write protection since the first
    # release, read by no hook until TP-461 1-B (DEF-951). The engine's
    # ``build_harness_config`` copies them into the plan for the drift
    # compare, which is not a consumer -- the deny is.
    # The witness is the CONSTANT the reader iterates, not the reader: the
    # reader's docstring and messages name the keys, so a witness on its body
    # stayed green with the constant emptied (the 2-A review drove it).
    "protected_paths": "tools/cc/hooks/_hook_utils.py::ADOPTER_ZONE_KEYS",
    "generated_paths": "tools/cc/hooks/_hook_utils.py::ADOPTER_ZONE_KEYS",
    "lane_count": (
        DISPLAY_ONLY,
        "espalier/handoff.py::build_surface_handoff",
        "echoed into the handoff report; no behaviour by design -- an adopter may "
        "have set it, so it stays a field",
    ),
    "surface_mode": "espalier/harness_config.py::build_harness_config",
    "default_profile": "espalier/cli.py::installed_settings_profile",
    "plan_exempt_prefixes": "tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes",
    # The hook-read knobs of 2026-10-06 (the Node-defaults class): the hooks
    # read espalier.toml directly; the witness for the relief pair is the
    # constant the reader iterates, as for the zones above.
    "source_extensions": "tools/cc/hooks/_hook_utils.py::_read_source_extensions",
    # The dependency-directory key (TP-469 lane C): the hook-side reader for
    # the two tools/cc walkers; the engine walks read it through
    # espalier/_safe_walk.py::declared_dependency_dirs.
    "dependency_dirs": "tools/cc/hooks/_hook_utils.py::declared_dependency_dirs",
    "code_review_agents": "tools/cc/hooks/_hook_utils.py::RELIEF_AGENT_KEYS",
    "docs_refresh_agents": "tools/cc/hooks/_hook_utils.py::RELIEF_AGENT_KEYS",
    # deploy_harness is where the flag decides whether the goal file is seeded;
    # _seed_goal_snapshot names the field only in its docstring.
    "goal_snapshot": "espalier/cli.py::deploy_harness",
    # The one reader of the FIELD (``config.gitignore_declined``), which every
    # command that loaded its configuration passes to cli.gitignore_status, so
    # `--config` is honoured (DEF-1106; the first draft parsed the TOML key in
    # this function instead, and the census passed on the matching string).
    "gitignore_declined": "espalier/config.py::declined_gitignore_entries",
}


def _field_names() -> list[str]:
    return [f.name for f in dataclasses.fields(HarnessConfig)]


def _symbol_source(rel_path: str, symbol: str) -> str | None:
    """The source text of ``symbol`` in ``rel_path`` -- a def or class at any
    nesting, WITHOUT its docstring (a docstring that names the field is not a
    read of it), or a module-level constant's assignment -- or None when the
    file or the symbol is absent."""
    path = REPO_ROOT / rel_path
    if not path.is_file():
        return None
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
                body = body[1:]
            return "\n".join(ast.get_source_segment(src, stmt) or "" for stmt in body)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == symbol for t in targets):
                return ast.get_source_segment(src, node) or ""
    return None


class TestEveryConfigFieldIsConsumed:
    def test_population_floor(self):
        assert len(_field_names()) >= FIELD_FLOOR, (
            f"HarnessConfig has {len(_field_names())} fields, below the census floor "
            f"{FIELD_FLOOR}; if a field was removed on purpose, lower the floor and "
            "drop its CONSUMERS row in the same change"
        )

    def test_map_names_only_live_fields(self):
        stale = sorted(set(CONSUMERS) - set(_field_names()))
        assert not stale, f"CONSUMERS rows for fields HarnessConfig no longer has: {stale}"

    @pytest.mark.parametrize("field", _field_names())
    def test_field_has_a_consumer_or_a_declared_reason(self, field):
        entry = CONSUMERS.get(field)
        assert entry is not None, (
            f"HarnessConfig.{field} has no CONSUMERS row: name the path::symbol that "
            f"acts on it, or declare it ({DISPLAY_ONLY!r}, <reason>). A field nothing "
            "reads is a setting the user wrote that does nothing (DEF-951)."
        )
        if isinstance(entry, tuple):
            kind, witness, reason = entry
            assert kind == DISPLAY_ONLY and reason.strip(), (
                f"HarnessConfig.{field}: a tuple row must be ({DISPLAY_ONLY!r}, path::symbol, reason)"
            )
            rel_path, _, symbol = witness.partition("::")
            source = _symbol_source(rel_path, symbol)
            assert source is not None and field in source, (
                f"HarnessConfig.{field}: the display-only witness {witness} is gone or no "
                "longer names the field"
            )
            return
        rel_path, _, symbol = entry.partition("::")
        source = _symbol_source(rel_path, symbol)
        assert source is not None, (
            f"HarnessConfig.{field}: consumer {entry} does not exist (file or symbol "
            "missing) -- the witness is gone, so the field may be unread again"
        )
        assert field in source, (
            f"HarnessConfig.{field}: {entry} exists but its body never names the "
            "field -- the witness no longer acts on it"
        )


class TestSelfHostConfigLoadsClean:
    """The live-tree pin for ``config.FOREIGN_KEYS``: the self-host
    ``espalier.toml`` carries keys ``scripts/record_snapshot.py`` reads and
    ``HarnessConfig`` does not. A reader that adds a key without declaring it
    reds HERE, in this tree, not in an adopter's terminal on every load. Lives
    in this file (not ``tests/test_config.py``) because that file is
    byte-mirrored into the selfcheck package, which must never read the harness
    tree."""

    def test_self_host_espalier_toml_loads_without_an_unknown_key_warning(self):
        assert (REPO_ROOT / "espalier.toml").is_file(), "the self-host tree carries espalier.toml"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(REPO_ROOT)
        unknown = [str(w.message) for w in caught if "unknown key" in str(w.message)]
        assert unknown == [], (
            "the self-host espalier.toml warns on load; declare the key in "
            f"espalier/config.py::FOREIGN_KEYS with its reader, or remove it: {unknown}"
        )
