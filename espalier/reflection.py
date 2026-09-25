"""Lightweight reflection — scan for broken markdown links and missing plan/manifest docs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from espalier._report_io import load_report_json
from espalier._safe_walk import safe_rglob
from espalier.reflect_protocol import LOCAL_LINK_RE, _text_without_fences


def _load_json(path: Path) -> dict[str, Any]:
    # Single guarded owner (tolerates a non-UTF-8/malformed report). The
    # caller still gates on plan_path.exists() first; the loader's own
    # existence guard is redundant-but-safe.
    return load_report_json(path)


def _iter_markdown_files(repo_root: Path) -> list[Path]:
    # Only the navigable PUBLIC doc surface. classify_release_path excludes build
    # artifacts (dist/, caches -> transient), per-install/local state (reports/,
    # cc/blueprints/ -> local_only), and dev-internal docs (session-archive.md,
    # TP-*.md, blueprint.md -> internal). Without this the bare rglob walked the
    # dist/ extracted-release trees + gitignored scratch and reported ~30 phantom
    # "broken links" — the bulk of the `espalier doctor` surface WARN. Lazy import
    # (mirrors reflect_deep) to keep reflection import-cheap and circular-safe.
    from espalier.surface_contract import classify_release_path, is_shipped_pack

    out: list[Path] = []
    for md in safe_rglob(repo_root, "*.md"):
        rel = md.relative_to(repo_root).as_posix()
        # A task pack in a shipped location (the folder root or Deferred/)
        # classifies public since 2026-09-21, but it is a dated PLAN, not a
        # navigable doc: it cites files it proposes to create and links it wrote
        # for another tree, and its own scope-check re-walks it at execution.
        # On an adopter tree the same location holds gitignored scratch. Out of
        # the reflect surface by the one predicate that defines a pack.
        if is_shipped_pack(rel):
            continue
        # ``espalier/assets/`` holds byte-mirrors of source docs that init/fuse
        # deploy verbatim to adopters. Their relative links are DEPLOY-context —
        # they resolve in the adopter tree (``.claude/``, ``tools/cc/`` siblings),
        # not in this mirror location — so link-checking the mirror produces false
        # positives. The source docs are scanned in their own location and the
        # folder-router link contract (test_folder_claude_md_routers) covers the
        # routers, so the mirror is redundant to scan here.
        if rel.startswith("espalier/assets/"):
            continue
        if classify_release_path(rel) == "public":
            out.append(md)
    return sorted(out)


def _normalize_link(base_file: Path, target: str, repo_root: Path) -> Path:
    cleaned = target.split("#", 1)[0].strip()
    if cleaned.startswith("/"):
        return repo_root / cleaned.lstrip("/")
    return (base_file.parent / cleaned).resolve()


def reflect_repo(repo_root: Path) -> dict[str, Any]:
    plan_path = repo_root / "reports" / "harness_config.json"
    manifest_path = repo_root / "cc" / "PACK_MANIFEST.txt"

    plan_missing_docs: list[str] = []
    manifest_missing_docs: list[str] = []
    broken_markdown_links: list[dict[str, str]] = []

    if plan_path.exists():
        plan = _load_json(plan_path)
        for rel in plan.get("generated_docs", []):
            candidate = repo_root / str(rel)
            if not candidate.exists():
                plan_missing_docs.append(str(rel))

    if manifest_path.exists():
        # F5 (CV2): reflect_repo runs inside run_doctor_check; an unguarded read of a
        # non-UTF-8 manifest/markdown raised UnicodeDecodeError that propagated out and
        # bypassed doctor's honest "N unreadable" framing. Read tolerantly (errors=replace)
        # so a mojibake file degrades the advisory checks instead of crashing the diagnostic.
        for raw in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
            rel = raw.strip()
            if rel and not rel.startswith("#") and not rel.startswith("<!--") and not (repo_root / rel).exists():
                manifest_missing_docs.append(rel)

    for md_path in _iter_markdown_files(repo_root):
        text = _text_without_fences(
            md_path.read_text(encoding="utf-8", errors="replace"), strip_html_comments=True
        )
        for match in LOCAL_LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target:
                continue
            # Skip DIRECTORY links (trailing `/`): they are structural nav /
            # valid-when-deployed references (e.g. a template's `[memory/](memory/)`,
            # which resolves in the adopter repo, not next to the template), not
            # broken FILE links.
            if target.split("#", 1)[0].rstrip().endswith("/"):
                continue
            # Skip template/format EXAMPLES rather than real links: a link whose
            # target carries an angle-bracket placeholder
            # (`[memory/<slug>.md](memory/<slug>.md)`) or a bare `...` ellipsis
            # target is documentation OF the link shape, not a navigable link.
            # Scoped to the target: a real broken link whose display *text*
            # merely contains `<` must still be reported.
            if "<" in target or target == "...":
                continue
            candidate = _normalize_link(md_path, target, repo_root)
            if not candidate.exists():
                broken_markdown_links.append({
                    "file": md_path.relative_to(repo_root).as_posix(),
                    "target": target,
                })

    missing_connections: list[str] = []
    if plan_missing_docs and not manifest_missing_docs:
        missing_connections.append("build plan and on-disk docs drifted before PACK_MANIFEST drifted")
    if manifest_missing_docs and not plan_missing_docs:
        missing_connections.append("PACK_MANIFEST lists files that the build plan may no longer own")
    if broken_markdown_links:
        missing_connections.append("local markdown navigation is broken in at least one file")

    recommended_actions: list[str] = []
    if plan_missing_docs or manifest_missing_docs:
        recommended_actions.append("repair missing generated docs before deeper refactor work")
    if broken_markdown_links:
        recommended_actions.append("fix broken markdown links before handoff")
    if not recommended_actions:
        recommended_actions.append("manual reread recommended for terminology drift and quality-gradient review")

    return {
        "repo_root": str(repo_root),
        "plan_missing_docs": sorted(set(plan_missing_docs)),
        "manifest_missing_docs": sorted(set(manifest_missing_docs)),
        "broken_markdown_links": broken_markdown_links,
        "missing_connections": missing_connections,
        "recommended_actions": recommended_actions,
    }


def reflect_deep(repo_root: Path, pass_number: int = 1) -> dict[str, Any]:
    """Run a full structured reflect pass combining legacy checks and the
    new reflect protocol (cross-refs, orphans, quality signals, validation).

    Returns a combined report with both the legacy fields (for backward
    compatibility) and the structured ReflectPass data.
    """
    from espalier.reflect_protocol import run_reflect_pass, render_reflect_pass

    # Legacy checks
    legacy = reflect_repo(repo_root)

    # Structured protocol pass
    rp = run_reflect_pass(repo_root, pass_number=pass_number)

    return {
        **legacy,
        "reflect_pass": rp.to_dict(),
        "rendered": render_reflect_pass(rp),
    }


def render_reflection_report(report: dict[str, Any]) -> str:
    lines = [
        "REFLECTION",
        "==========",
        f"Repo root: {report['repo_root']}",
        f"Plan gaps: {len(report.get('plan_missing_docs', []))}",
        f"Manifest gaps: {len(report.get('manifest_missing_docs', []))}",
        f"Broken markdown links: {len(report.get('broken_markdown_links', []))}",
        "",
    ]
    if report.get("plan_missing_docs"):
        lines.append("Plan-promised docs missing on disk:")
        lines.extend(f"- {item}" for item in report["plan_missing_docs"])
        lines.append("")
    if report.get("manifest_missing_docs"):
        lines.append("Manifest-promised docs missing on disk:")
        lines.extend(f"- {item}" for item in report["manifest_missing_docs"])
        lines.append("")
    if report.get("broken_markdown_links"):
        lines.append("Broken local markdown links:")
        lines.extend(f"- {item['file']} -> {item['target']}" for item in report["broken_markdown_links"][:20])
        lines.append("")
    lines.append("Recommended actions:")
    lines.extend(f"- {item}" for item in report.get("recommended_actions", []))

    # Append structured pass if present
    if "rendered" in report:
        lines.extend(["", "-" * 40, "", report["rendered"]])

    return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a reflection pass over a built Claude Code repo")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--deep", action="store_true", help="Run full structured reflect protocol")
    parser.add_argument("--pass-number", type=int, default=1)
    args = parser.parse_args(argv)
    if args.deep:
        report = reflect_deep(args.repo_root, pass_number=args.pass_number)
    else:
        report = reflect_repo(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_reflection_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
