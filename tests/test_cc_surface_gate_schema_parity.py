"""Schema parity for ``reports/cc_surface_gate.json`` — the SessionStart
coordination contract between the PRODUCER
(``espalier.proofs.run_cc_surface_gate``) and the CONSUMER
(``tools/cc/cognitive_blueprint.cmd_start``, which seeds ``gate_status``
from ``_load_json(... / "cc_surface_gate.json")``).

Registered in
``espalier.scanners.filesystem_contracts.FILESYSTEM_CONTRACTS`` (TP-151
D-3): the gate file is a hook-read coordination contract, not a
human-only report, so its producer/consumer key agreement is pinned
here rather than left to the ``reports/`` output exemption.

Non-circular: ``CONSUMER_REQUIRED_KEYS`` is bound to the hook source via
AST (the keys ``cmd_start`` actually reads off the ``gate`` dict), so a
new consumer read cannot silently outrun this contract.
"""
# pytest-marker: default-unit  (in-process producer call + AST parse; no
# subprocess, no slow integration — the default `unit` marker is correct)
from __future__ import annotations

import ast
import json
from pathlib import Path

from espalier.proofs import run_cc_surface_gate

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SIDE_SCRIPT = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"

# The keys cmd_start reads off the gate file
# (``gate = _load_json(.../cc_surface_gate.json)``). Bound to the hook
# source by test_consumer_required_keys_match_hook_source below.
CONSUMER_REQUIRED_KEYS = {"status"}


def _consumer_keys_from_hook() -> set[str]:
    """Every string key the hook's ``cmd_start`` reads off the ``gate``
    dict via ``gate.get("KEY"...)`` or ``gate["KEY"]``."""
    tree = ast.parse(HOOK_SIDE_SCRIPT.read_text(encoding="utf-8"))
    cmd_start = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "cmd_start"
    )
    keys: set[str] = set()
    for node in ast.walk(cmd_start):
        # gate.get("status", ...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "gate"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        # gate["status"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "gate"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def test_consumer_required_keys_match_hook_source():
    """The hardcoded CONSUMER_REQUIRED_KEYS must equal the keys cmd_start
    actually reads off the gate file — binds the constant to reality so the
    contract cannot fall behind a new read."""
    assert _consumer_keys_from_hook() == CONSUMER_REQUIRED_KEYS, (
        "cmd_start reads gate keys that drifted from CONSUMER_REQUIRED_KEYS; "
        "update the constant AND confirm the producer emits the new key."
    )


def test_producer_emits_consumer_required_keys(tmp_path):
    """run_cc_surface_gate must write every key the consumer reads."""
    run_cc_surface_gate(tmp_path)
    data = json.loads(
        (tmp_path / "reports" / "cc_surface_gate.json").read_text(encoding="utf-8")
    )
    missing = CONSUMER_REQUIRED_KEYS - set(data.keys())
    assert not missing, (
        f"producer omits consumer-required gate keys: {sorted(missing)}"
    )
