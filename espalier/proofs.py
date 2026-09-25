"""Surface gate — verify CC surface integrity: required files, valid JSON, no placeholders."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from espalier import surface_contract
from espalier._atomic_io import atomic_write_text
from espalier._compat import tomllib
from espalier._report_io import load_report_json, report_is_json_object, safe_text
from espalier._safe_walk import safe_rglob
from espalier.analyze import SUSPICIOUS_CONTENT
from espalier.managed_markers import file_carries_marker


CONTROL_ROOTS = [".claude", "tools/cc", "reports"]
# Which files this proof reads as text — purpose-scoped, deliberately narrower than
# scope_walker.INCLUDED_EXTS / surface_impact._PATH_SUFFIXES (its concept-siblings).
# Not a collapse candidate: widening it here would change what content the proofs
# scan, not just "recognize one more extension." See scope_walker.INCLUDED_EXTS.
# sister-site: ok purpose-scoped: text-read gate; sibling of scope_walker.INCLUDED_EXTS / surface_impact._PATH_SUFFIXES (see comment above)
TEXT_SUFFIXES = {".md", ".toml", ".txt", ".py", ".json"}
PLACEHOLDERS = ["<repo>", "<fill>", "INSERT HERE", "TEMPLATE_ONLY"]
# SUSPICIOUS_CONTENT is imported directly from the canonical analyze module — the
# fingerprint module owns the token list; the gate reuses it.


def _safe_text(path: Path) -> str:
    return safe_text(path)


def _mentions_token(text: str, token: str) -> bool:
    """Whole-token containment: a hyphen/word char on either side disqualifies,
    so ``review`` is not satisfied by ``code-review``."""
    return re.search(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])", text) is not None


def _is_managed(path: Path) -> bool:
    # Single owner: managed_markers.file_carries_marker (same exists()/is_file()
    # guard + replacement-decoded read this used to hand-roll via _safe_text).
    return file_carries_marker(path)


def _iter_control_files(repo_root: Path, managed_only: bool = False):
    for rel_root in CONTROL_ROOTS:
        root = repo_root / rel_root
        if not root.exists():
            continue
        for path in safe_rglob(root):
            if not path.is_file():
                continue
            # Skip symlinks. A symlink-to-outside-the-repo inside
            # tools/cc/ would otherwise be opened + scanned for placeholders
            # / suspicious text, leaking the target file's content into the
            # audit log. scope_walker carries the same filter.
            if path.is_symlink():
                continue
            if managed_only and not _is_managed(path):
                continue
            yield path


def _manifest_items(repo_root: Path) -> set[str]:
    manifest = repo_root / "cc" / "PACK_MANIFEST.txt"
    if not manifest.exists():
        return set()
    return {
        line.strip()
        for line in _safe_text(manifest).splitlines()
        if line.strip() and not line.startswith("#")
    }


def _load_json(path: Path) -> dict:
    # Route to the single canonical owner. Field-level coercion happens at the
    # run_cc_surface_gate call sites, not here — load_report_json guards only
    # the TOP-LEVEL shape.
    return load_report_json(path)


def first_error_detail(report: Mapping[str, Any] | None) -> str:
    """The ``detail`` of the first error-level finding in a surface-gate
    report, or ``""``. The gate reports findings, not a sentence; this is
    the sentence a failure hands on -- read by doctor's audit line and by
    ``self_hosting.run_self_host_check`` (DEF-785), so the two never forward
    different findings for one gate."""
    if not isinstance(report, Mapping):
        return ""
    for finding in report.get("findings") or []:
        if isinstance(finding, dict) and finding.get("level") == "error" and finding.get("detail"):
            return str(finding["detail"]).strip()
    return ""


def run_cc_surface_gate(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    findings: list[dict[str, str]] = []

    # A `.claude` this process cannot search or list is ONE finding naming
    # the permission, not a manifest's worth of "missing" files: asked file
    # by file, the same tree read as absent on CPython 3.14 and raised out
    # of the first `exists()` on 3.10-3.13 (DEF-763). The walk is reached
    # only once this gate has passed, and its existence checks are
    # `os.path.*`, which answer the same on every interpreter. A NEW check
    # belongs in `_walk_surface_findings`, below the gate -- added here it
    # would run on the locked tree and re-open the phantom-missing list.
    unreadable = surface_contract.unreadable_harness_root(repo_root)
    if unreadable is not None:
        findings.append({
            "level": "error", "check": "presence",
            "detail": surface_contract.unreadable_root_sentence(unreadable),
        })
    else:
        _walk_surface_findings(repo_root, findings)

    report = {
        "repo": repo_root.name,
        "status": "pass" if not any(item["level"] == "error" for item in findings) else "fail",
        "summary": {
            "errors": sum(1 for item in findings if item["level"] == "error"),
            "warnings": sum(1 for item in findings if item["level"] == "warning"),
        },
        "findings": findings,
    }
    # cc_surface_gate.json is read by the SessionStart hook
    # (cmd_start seeds gate_status from it), so a torn write could be caught
    # by a concurrent reader. Write atomically (temp + os.replace). The path
    # literal is inlined (not via an intermediate `out` variable) so the
    # filesystem_contracts scanner can resolve the hint and pin it PINNED
    # rather than miss it as a stealth contract. atomic_write_text creates the
    # parent dir, so the explicit mkdir is no longer needed.
    atomic_write_text(
        repo_root / "reports" / "cc_surface_gate.json",
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    return report


def _walk_surface_findings(repo_root: Path, findings: list[dict[str, str]]) -> None:
    """The gate's walk -- required files, the saved plan, the manifest, the
    generated docs and COMMANDS.md -- each appending to ``findings``. Reached
    only once ``.claude`` can be searched and listed."""
    required_files = (
        repo_root / "reports" / "repo_fingerprint.json",
        repo_root / "reports" / "harness_config.json",
        repo_root / "cc" / "PACK_MANIFEST.txt",
        repo_root / ".claude" / "settings.json",
    )
    for required in required_files:
        # Forward-slash the relative path for Windows compat (same class as the
        # placeholder/malformed details below). Computed as a plain assignment,
        # not inside the f-string: the 3.10/3.11 release lanes reject a
        # backslash inside an f-string expression.
        rel = str(required.relative_to(repo_root)).replace("\\", "/")
        if not os.path.exists(required):
            findings.append({"level": "error", "check": "freshness", "detail": f"missing generated file: {rel}"})
        elif required.suffix == ".json" and not report_is_json_object(required):
            # F1 (CV2): a present-but-corrupt required report degrades to {} via
            # _load_json, which would otherwise void the field-level checks below
            # yet still return status 'pass'. Fail CLOSED: flag it as an error.
            findings.append({"level": "error", "check": "freshness", "detail": f"required report present but unreadable / not a JSON object: {rel}"})

    build_plan = _load_json(repo_root / "reports" / "harness_config.json")
    # Value-level coercion. _load_json guards only that the TOP-LEVEL report is
    # a dict; a present-but-wrong-typed FIELD (generated_docs/stable_actions/
    # agents = null / str / list-of-str) still tracebacks the build_plan.get(...)
    # derefs below. Coerce each to its expected type once, here, before use
    # (mirrors diffing._saved_plan_surface_view's isinstance discipline). Both
    # stable_actions consumers (LIVE_SURFACE + COMMANDS) and the agents loop read
    # the coerced values.
    _gen_docs = build_plan.get("generated_docs")
    gen_docs = [d for d in _gen_docs if isinstance(d, str)] if isinstance(_gen_docs, list) else []
    _stable = build_plan.get("stable_actions")
    stable_actions = _stable if isinstance(_stable, dict) else {}
    _agents = build_plan.get("agents")
    agents = _agents if isinstance(_agents, list) else []
    manifest_items = _manifest_items(repo_root)
    # PACK_MANIFEST is operator-facing and strict for its own scope: every file
    # it *promises* must exist. It is NOT an exhaustive cleanup inventory —
    # that lives in espalier.managed_paths / surface_contract.
    missing_promised = sorted(
        item for item in manifest_items if not os.path.exists(repo_root / item)
    )
    if missing_promised:
        findings.append({
            "level": "error", "check": "manifest",
            "detail": f"PACK_MANIFEST promises missing files: {missing_promised}",
        })

    for rel_path in gen_docs:
        if not os.path.exists(repo_root / rel_path):
            findings.append({"level": "error", "check": "generated_docs", "detail": f"missing generated doc promised by build plan: {rel_path}"})

    dot_claude = repo_root / ".claude"
    if dot_claude.exists() and tomllib is not None:
        for path in safe_rglob(dot_claude, "*.toml"):
            if not _is_managed(path):
                continue
            try:
                tomllib.loads(_safe_text(path))
            except tomllib.TOMLDecodeError as exc:
                rel = str(path.relative_to(repo_root)).replace("\\", "/")
                findings.append({"level": "error", "check": "toml", "detail": f"{rel}: {exc}"})

    # post_write_check.py legitimately defines PLACEHOLDERS as a
    # constant for matching downstream templates; the placeholder-scan
    # would match the file against its own definition. Exclude this one file
    # (not all .py files — the test suite expects placeholder warnings on
    # arbitrary .py templates in tools/cc/).
    # _hook_utils.py is a sister site — its path-normalization comment
    # carries a literal ``<repo>`` token ("a bare ``../<repo>/...`` string"),
    # which trips the scan once the file is managed-marked (every fusion, where
    # the scan runs managed_only). Same false-positive shape, same fix.
    # _bash_patterns.py is the THIRD site of the same shape (added 781fd89,
    # DEF-499): its docstring cites the literal ``<repo>/build`` path the
    # unbypassable tier once misfired on. Only the DEPLOYED copy is
    # managed-marked, so self-host `audit` never saw it and every adopter's
    # first `audit .` warned that the harness ships placeholder text
    # (DEF-689). The class gate is
    # tests/test_proofs.py::test_deployed_tools_cc_has_no_placeholder_findings,
    # which scans the real deploy source with markers applied -- a fourth site
    # reds there before it reaches an adopter.
    _PLACEHOLDER_SCAN_EXCLUSIONS = {
        "tools/cc/hooks/post_write_check.py",
        "tools/cc/hooks/_hook_utils.py",
        "tools/cc/hooks/_bash_patterns.py",
        # The hook half of /reflect defines the residue tokens it scans for,
        # pattern-for-pattern with the engine half (pinned by
        # tests/test_reflect_protocol.py::TestReflectTwinParity), so the
        # literals are the definition, not residue (2026-09-08).
        "tools/cc/reflect_protocol.py",
    }
    for path in _iter_control_files(repo_root, managed_only=True):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel_path = str(path.relative_to(repo_root)).replace("\\", "/")
        text = _safe_text(path)
        if (
            rel_path not in _PLACEHOLDER_SCAN_EXCLUSIONS
            and any(token in text for token in PLACEHOLDERS)
        ):
            findings.append({"level": "warning", "check": "placeholder", "detail": f"{rel_path} contains placeholder text"})
        if any(token in text for token in SUSPICIOUS_CONTENT):
            findings.append({"level": "warning", "check": "malformed_text", "detail": f"{rel_path} contains suspicious terminal text"})

    for path in repo_root.iterdir():
        # Word-bound the ``less`` alternative (``\bless\b``) so a
        # benign root filename that merely CONTAINS ``less`` as a word-internal
        # substring (painless/flawless/useless/blessing) is not flagged; only a
        # standalone ``less`` token (pager-spillage shape, e.g. ``less.out``) is.
        if path.is_file() and re.match(r"(cc.*(surface|manifest)|.*\bless\b.*|.*skipping.*)", path.name, flags=re.IGNORECASE):
            findings.append({"level": "warning", "check": "root_garbage", "detail": f"suspicious root file: {path.name}"})

    live_surface = repo_root / "cc" / "LIVE_SURFACE.md"
    if live_surface.exists() and build_plan:
        live_text = _safe_text(live_surface)
        for action in stable_actions.keys():
            if not _mentions_token(live_text, action):
                findings.append({"level": "warning", "check": "live_surface", "detail": f"LIVE_SURFACE.md missing action: {action}"})
        # A plan agent is a recommendation; only one with a body -- packaged,
        # or written by the adopter at the recommended path -- can appear in a
        # doc rendered from the deployed tree. Warning that a bodiless
        # recommendation is absent fired on every fresh init of an API, ML, UI
        # or ops project (DEF-766: `audit` after `init` on an API repo warned
        # `LIVE_SURFACE.md missing agent: api-reviewer`, an agent nothing
        # ships). The DEF-756 premise, at this consumer.
        from espalier.asset_inventory import packaged_agent_names
        agents_with_a_body = packaged_agent_names()
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            name = agent.get("name")
            if not name:
                continue
            if (
                name not in agents_with_a_body
                and not os.path.isfile(repo_root / ".claude" / "agents" / f"{name}.md")
            ):
                continue
            if not _mentions_token(live_text, name):
                findings.append({"level": "warning", "check": "live_surface", "detail": f"LIVE_SURFACE.md missing agent: {name}"})

    commands_doc = repo_root / "cc" / "COMMANDS.md"
    if commands_doc.exists() and build_plan:
        commands_text = _safe_text(commands_doc)
        for action in stable_actions.keys():
            if not _mentions_token(commands_text, action):
                findings.append({"level": "warning", "check": "commands", "detail": f"COMMANDS.md missing action: {action}"})
