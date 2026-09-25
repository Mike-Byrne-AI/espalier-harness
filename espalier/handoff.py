"""Build structured surface handoff reports for installed harness state."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from espalier._atomic_io import atomic_write_text
from espalier._report_io import load_report_json
from espalier.managed_markers import MARKER_HTML_COMMENT_SHORT, apply_marker_to_md

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict[str, Any]:
    # Route through the single guarded owner (tolerates a BOM'd/malformed report).
    return load_report_json(path)


def build_surface_handoff(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    plan = _load_json(repo_root / "reports" / "harness_config.json")
    fingerprint = _load_json(repo_root / "reports" / "repo_fingerprint.json")
    gate = _load_json(repo_root / "reports" / "cc_surface_gate.json")

    agents = plan.get("agents", []) if isinstance(plan.get("agents"), list) else []
    stable_actions = plan.get("stable_actions", {}) if isinstance(plan.get("stable_actions"), dict) else {}
    profiles = plan.get("profiles", []) if isinstance(plan.get("profiles"), list) else []
    generated_docs = plan.get("generated_docs", []) if isinstance(plan.get("generated_docs"), list) else []
    unresolved = plan.get("unresolved_questions", []) if isinstance(plan.get("unresolved_questions"), list) else []
    notes = plan.get("notes", []) if isinstance(plan.get("notes"), list) else []
    lane_count = int(plan.get("config", {}).get("lane_count", 3)) if isinstance(plan.get("config"), dict) else 3

    commands = []
    for name, cmds in stable_actions.items():
        command = list(cmds)[0] if isinstance(cmds, list) and cmds else ""
        commands.append({"action": str(name), "command": str(command)})

    return {
        "repo_root": str(repo_root),
        "repo_name": str(plan.get("repo_name") or fingerprint.get("repo_name") or repo_root.name),
        "surface_mode": str(plan.get("config", {}).get("surface_mode", "core")) if isinstance(plan.get("config"), dict) else "core",
        "profiles": [str(item) for item in profiles],
        "languages": [str(item) for item in fingerprint.get("languages", [])] if isinstance(fingerprint.get("languages"), list) else [],
        "entrypoints": [str(item) for item in fingerprint.get("entrypoints", [])] if isinstance(fingerprint.get("entrypoints"), list) else [],
        "package_roots": [str(item) for item in fingerprint.get("package_roots", [])] if isinstance(fingerprint.get("package_roots"), list) else [],
        "commands": commands,
        "agents": [
            {
                "name": str(agent.get("name", "")),
                "scope": str(agent.get("scope", "")),
                "primary_paths": [str(item) for item in agent.get("primary_paths", [])][:5] if isinstance(agent.get("primary_paths"), list) else [],
            }
            for agent in agents[:10]
            if isinstance(agent, dict)
        ],
        "generated_docs": [str(item) for item in generated_docs],
        "gate_status": str(gate.get("status", "unknown")),
        "gate_errors": int(gate.get("summary", {}).get("errors", 0)) if isinstance(gate.get("summary"), dict) else 0,
        "gate_warnings": int(gate.get("summary", {}).get("warnings", 0)) if isinstance(gate.get("summary"), dict) else 0,
        "unresolved_questions": [str(item) for item in unresolved],
        "notes": [str(item) for item in notes],
        "lane_count": max(1, lane_count),
        "owned_roots": [
            ".claude/**",
            "cc/**",
            "tools/cc/**",
            "reports/repo_fingerprint.json",
            "reports/harness_config.json",
            "reports/cc_surface_gate.json",
        ],
        "non_destructive_rule": "Preserve existing repo tools, commands, and agent surfaces outside the generated Espalier-Harness control roots.",
    }


def render_surface_handoff(report: dict[str, Any]) -> str:
    def md_list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- none"

    command_lines = [f"`{item['action']}` -> `{item['command']}`" for item in report.get("commands", []) if item.get("action")]
    agent_lines = []
    for agent in report.get("agents", []):
        name = agent.get("name", "unknown")
        scope = agent.get("scope", "unknown")
        primary = ", ".join(agent.get("primary_paths", [])) or "unknown"
        agent_lines.append(f"`{name}` — scope: `{scope}` — primary paths: {primary}")

    return (
        "# SURFACE HANDOFF\n\n"
        "## Repo identity\n"
        f"- repo: {report.get('repo_name', 'unknown')}\n"
        f"- surface mode: {report.get('surface_mode', 'core')}\n"
        f"- proof gate: {report.get('gate_status', 'unknown')}\n"
        f"- proof errors: {report.get('gate_errors', 0)}\n"
        f"- proof warnings: {report.get('gate_warnings', 0)}\n"
        f"- lane count: {report.get('lane_count', 1)}\n\n"
        "## Repo shape\n"
        f"- languages: {', '.join(report.get('languages', [])) or 'unknown'}\n"
        f"- package roots: {', '.join(report.get('package_roots', [])) or 'unknown'}\n"
        f"- entrypoints: {', '.join(report.get('entrypoints', [])) or 'unknown'}\n"
        f"- detected shapes: {', '.join(report.get('profiles', [])) or 'unknown'}\n\n"
        "## Generated control roots\n"
        f"{md_list(report.get('owned_roots', []))}\n\n"
        "## Non-destructive rule\n"
        f"- {report.get('non_destructive_rule', 'Preserve existing tooling outside generated roots.')}\n\n"
        "## Stable actions\n"
        f"{md_list(command_lines)}\n\n"
        "## Agent roster\n"
        f"{md_list(agent_lines)}\n\n"
        "## Generated docs\n"
        f"{md_list(report.get('generated_docs', []))}\n\n"
        "## Unresolved questions\n"
        f"{md_list(report.get('unresolved_questions', []))}\n\n"
        "## Risk notes\n"
        f"{md_list(report.get('notes', []))}\n\n"
        "## Ready-to-use handoff template\n"
        "1. Owned lane and file boundary:\n"
        "2. Files changed:\n"
        "3. Commands actually run:\n"
        "4. Proof result and evidence:\n"
        "5. Remaining risks or unanswered questions:\n"
        "6. Smallest next recommended step:\n"
    )


def write_surface_handoff(repo_root: Path, output_path: Path | None = None) -> Path:
    repo_root = repo_root.resolve()
    default_out = repo_root / "cc" / "SURFACE_HANDOFF.md"
    out = output_path or default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    content = render_surface_handoff(build_surface_handoff(repo_root))
    if out.resolve() == default_out.resolve():
        content = apply_marker_to_md(content, comment=MARKER_HTML_COMMENT_SHORT)
    if out.exists() and not out.is_file():
        # A caller-supplied --out that is not a regular file (a FIFO,
        # /dev/stdout) cannot host a tempfile beside it: write it directly.
        out.write_text(content, encoding="utf-8", newline="\n")
    else:
        atomic_write_text(out, content)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a surface handoff report for an installed Claude Code harness")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_surface_handoff(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    out = write_surface_handoff(args.repo_root, args.out)
    logger.info("Wrote surface handoff: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
