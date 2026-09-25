"""Structured reflect protocol — the analysis engine behind DEEP-WORK.md.

Performs programmatic analysis of a CC surface:
- Cross-reference matrix between markdown files
- Orphan detection (files nothing references)
- Expected-reference gap checking
- Placeholder/sparse section detection
- Agent-path and command-tool validation
- Quality signals (section density, terminology consistency)

This is the measurable half of the reflect protocol. The other half —
emergent pattern discovery, architectural insights — requires an LLM
re-reading the files. The generated /reflect command combines both.

This is the library version of reflect_protocol. The hook-side
standalone CLI lives at `tools/cc/reflect_protocol.py` and solves a
narrower problem (surface walk for hook output). Bug fixes that affect
both concerns must land in both files. The two measure different things,
so there is no whole-file parity test; the axes that MUST agree are
pinned individually by `tests/test_reflect_link_guards.py` (broken-link
guards + the LOCAL_ONLY_PREFIXES surface exclusion).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from espalier._report_io import safe_text
from espalier._safe_walk import has_git_entry, safe_rglob
from espalier.claim_extractor import RECORD_SURFACES
from espalier.models import ReflectFinding, ReflectPass
from espalier._text import plural

# Single source of truth for the committed project-memory filename — routed
# through one constant so a future rename is a value flip, not scattered edits.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)")
# Non-navigable local-only trees excluded from the reflect surface walk.
# Forced twin of tools/cc/reflect_protocol.py's LOCAL_ONLY_PREFIXES across the
# no-import boundary — keep the two in sync (locked by
# tests/test_reflect_link_guards.py). cc/blueprints/ is the per-session archive;
# the cc/_ underscore prefix covers the auto-regenerated summary and the
# gitignored review scratch (cc/_working_summary.md, cc/_pack_review_*, …), all
# transient "regenerated prose"; cc/SURFACE_HANDOFF.md is the one excluded entry
# without the underscore. This mirrors the reference reflection.py, which
# excludes the same set via classify_release_path (the cc/_ prefix + the exact
# cc/SURFACE_HANDOFF.md). cc/GOAL.md is curated — kept scanned.
LOCAL_ONLY_PREFIXES = (
    "cc/blueprints/",
    "cc/_",
    "cc/SURFACE_HANDOFF.md",
)
PLACEHOLDER_PATTERNS = [
    # The (?<!\$) lookbehind excludes ${ENV} references (e.g. a documented
    # ${CLAUDE_PROJECT_DIR}) — those are shell/env syntax, never a
    # doc-template placeholder, and would otherwise be false-counted as residue.
    re.compile(r"(?<!\$)\{[A-Za-z_][A-Za-z0-9_ ]*\}"),   # {placeholder}, not ${ENV}
    re.compile(r"<fill>", re.IGNORECASE),
    re.compile(r"INSERT HERE", re.IGNORECASE),
    re.compile(r"TEMPLATE_ONLY", re.IGNORECASE),
    re.compile(r"TODO[:\s]", re.IGNORECASE),
    re.compile(r"FIXME[:\s]", re.IGNORECASE),
]
# An inline code span is a MENTION of a token, never template residue: every one
# of the 12 placeholder hits /reflect raised on docs/CONVENTIONS.md, SHARP_EDGES.md
# and FAILURE_MODES.md on 2026-09-08 was a backticked identifier such as
# `tests/test_{topic}.py`, which this module then graded "high". A span never
# crosses a line; a double-backtick span may hold a single backtick. Forced twin
# of tools/cc/reflect_protocol._INLINE_CODE_RE across the no-import boundary
# (pinned by tests/test_reflect_protocol.py::TestReflectTwinParity, as are the
# PLACEHOLDER_PATTERNS list and the record and orphan exemptions below).
_INLINE_CODE_RE = re.compile(r"``[^`\n]*``|`[^`\n]*`")


def _strip_inline_code(text: str) -> str:
    return _INLINE_CODE_RE.sub(" ", text)


# Residue-exempt surfaces: the append-only records (Core Rule 13's canon) MINUS
# docs/FAILURE_MODES.md, which is a record for its point-in-time counts but also
# a catalog adopters receive and edit, so template residue there must stay
# reportable. The canon answers "is a stale number here expected aging?"; this
# tuple answers "is quoted residue here content?" -- the same set but for that
# one member (2026-09-08 review). Forced twin of the hook side's
# RESIDUE_EXEMPT_SURFACES, pinned by TestReflectTwinParity.
RESIDUE_EXEMPT_SURFACES = tuple(k for k in RECORD_SURFACES if k != "docs/FAILURE_MODES.md")


# Expected cross-references: (source_pattern, should_mention)
# If a file matching source_pattern exists, it should reference should_mention
EXPECTED_REFS = [
    ("CLAUDE.md", [_MEMORY_FILENAME, "docs/SHARP_EDGES.md"]),
    ("docs/CHEAT-SHEET.md", [_MEMORY_FILENAME, "docs/SHARP_EDGES.md"]),
    ("docs/TASK_RECIPES.md", [_MEMORY_FILENAME]),
]


# Posix-relative idiom mandated inline by CLAUDE.md; intentional twin of analyze._rel
# and tools/cc/reflect_protocol._rel — not worth a shared helper. Leave inline.
def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _safe_text(path: Path) -> str:
    # Delegate to the single guarded owner.
    return safe_text(path)


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


_MD_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_SLUG_DROP = re.compile(r"[^\w\- ]", re.UNICODE)
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")


def _heading_anchors(markdown: str) -> set[str]:
    """Every anchor a GitHub-rendered copy of this document would expose.

    Mirrors ``tools/cc/reflect_protocol.py::_heading_anchors`` byte-for-byte in
    behaviour; that twin cannot import this one (``tools/cc/`` runs standalone with
    zero espalier imports), and this one does not import the ``tests/`` copy because
    the engine must not depend on the test tree. Three copies is the architecture's
    price -- the same reason the link-skip rules a few lines below are inlined from
    ``espalier/reflection.py``. The calibration behind the slug rules lives in
    ``tests/_md_anchors.py``'s docstring; keep all three in step.
    """
    seen: dict[str, int] = {}
    out: set[str] = set()
    fenced = False
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _ATX_HEADING.match(line)
        if not m:
            continue
        text = _SLUG_DROP.sub("", _MD_LINK_TEXT.sub(r"\1", m.group(2))).strip().lower()
        base = text.replace(" ", "-")
        if not base:
            continue
        n = seen.get(base, 0)
        seen[base] = n + 1
        for variant in {base, re.sub(r"-{2,}", "-", base)}:
            out.add(variant if n == 0 else f"{variant}-{n}")
    return out


def _text_without_fences(text: str, *, strip_html_comments: bool = False) -> str:
    """Strip fenced code blocks so we don't match links/placeholders inside them.

    With ``strip_html_comments=True`` also removes HTML comments first, so
    placeholder image refs (e.g. a README gif that hasn't been recorded yet)
    inside a comment don't register as broken links — the reflection.py use case.
    """
    if strip_html_comments:
        text = _HTML_COMMENT_RE.sub("", text)
    lines: list[str] = []
    in_fence = False
    for raw in text.splitlines():
        if raw.strip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(raw)
    return "\n".join(lines)


# Dependency and build trees the router walk prunes on BOTH halves: an npm
# package ships its own CLAUDE.md, and classify_release_path calls node_modules/
# public. Forced twin of the hook side's _WALK_SKIP_DIRS.
_WALK_SKIP_DIRS = {"node_modules", "__pycache__", "dist", "build", "site-packages", "venv"}


def _walk_router_docs(repo_root: Path) -> list[str]:
    """Every CLAUDE.md under `repo_root` as a repo-relative posix path, from ONE
    walk shape shared by both halves (forced twin of the hook side's
    _walk_router_docs): never follows a directory symlink, never enters a nested
    git repository, a dot-directory other than .claude, or a dependency tree. A
    filesystem walk on purpose: Claude Code's folder ladder loads an untracked
    or gitignored router too."""
    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if not (d.startswith(".") and d != ".claude")
            and d not in _WALK_SKIP_DIRS
            and not has_git_entry(Path(dirpath) / d))
        if "CLAUDE.md" in filenames:
            rels.append((Path(dirpath) / "CLAUDE.md").relative_to(repo_root).as_posix())
    return sorted(rels)


def _iter_surface_files(repo_root: Path) -> list[Path]:
    """Enumerate all markdown files in the CC surface."""
    hits: list[Path] = []
    # Root-level docs
    for name in ["CLAUDE.md", _MEMORY_FILENAME]:
        p = repo_root / name
        if p.exists():
            hits.append(p)
    # docs/ — the full tree, matching the hook twin's docs/**/*.md walk. A
    # hardcoded subset silently dropped new docs (HOOK_ASSUMPTIONS.md,
    # MEMORY_SYSTEMS.md, docs/schemas/*).
    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        hits.extend(sorted(safe_rglob(docs_dir, "*.md")))
    # cc/ directory, minus the non-navigable local-only trees (LOCAL_ONLY_PREFIXES):
    # the blueprint archive (historical session prose that *discusses* markdown-
    # link syntax), the cc/_ underscore class (auto-regenerated summaries +
    # gitignored review scratch), and cc/SURFACE_HANDOFF.md — link-checking any
    # of them yields only phantom gaps. Excluded by prefix rather than by
    # classify_release_path == "public": cc/GOAL.md is curated (a broken link in
    # it is a real defect) yet classifies local_only, so a blanket public-gate
    # would drop that real surface.
    cc_dir = repo_root / "cc"
    if cc_dir.exists():
        for p in sorted(safe_rglob(cc_dir, "*.md")):
            rel = p.relative_to(repo_root).as_posix()
            if any(rel.startswith(pre) for pre in LOCAL_ONLY_PREFIXES):
                continue
            hits.append(p)
    # .claude/ directory
    claude_dir = repo_root / ".claude"
    if claude_dir.exists():
        hits.extend(sorted(safe_rglob(claude_dir, "*.md")))
    # memory/ — the recall corpus. Reached by the recall index rather than by a
    # link, so it is orphan-exempt (ORPHAN_EXEMPT_PREFIXES) but link- and
    # residue-checked like any other doc. Both halves skipped it, and the nine
    # folder routers below, while reflection.py's public walker already covered
    # them (DEF-416a; measured 2026-09-08: 103 files here against 237 there).
    memory_dir = repo_root / "memory"
    if memory_dir.exists():
        hits.extend(sorted(safe_rglob(memory_dir, "*.md")))
    # Every public folder-router CLAUDE.md — the ladder Claude Code loads on
    # directory entry — from the shared pruned walk, kept by classify_release_path
    # the way reflection.py keeps its whole surface. The assets mirror's routers
    # resolve in the adopter tree, not here. Lazy import: keeps this module
    # import-cheap and circular-safe (mirrors reflection.py). The pack tree
    # stays out because the classifier says local_only -- except its folder
    # router, which ships with the forward ledger since 2026-09-21 and so
    # classifies public; the hook side mirrors that verdict as a prefix skip
    # with the one exact-path allow.
    from espalier.surface_contract import classify_release_path

    for rel in _walk_router_docs(repo_root):
        if rel.startswith("espalier/assets/") or classify_release_path(rel) != "public":
            continue
        hits.append(repo_root / rel)
    # Dedup while preserving order — the fuller docs/ walk can't double-count.
    return list(dict.fromkeys(hits))


def _extract_local_links(text: str) -> list[str]:
    """Extract local (non-URL) link targets from markdown text."""
    clean = _text_without_fences(text)
    targets: list[str] = []
    for m in LOCAL_LINK_RE.finditer(clean):
        target = m.group(1).split("#")[0].strip()
        if target:
            targets.append(target)
    return targets


def _count_placeholders(text: str) -> int:
    """Count placeholder patterns in prose: outside fences and inline code."""
    clean = _strip_inline_code(_text_without_fences(text))
    count = 0
    for pattern in PLACEHOLDER_PATTERNS:
        count += len(pattern.findall(clean))
    return count


def _section_density(text: str) -> dict[str, Any]:
    """Measure heading-to-content ratio. Sparse sections suggest incomplete generation."""
    lines = text.splitlines()
    heading_count = sum(1 for line in lines if line.strip().startswith("#"))
    content_lines = sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))
    empty_sections = 0
    current_heading = None
    lines_since_heading = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_heading is not None and lines_since_heading == 0:
                empty_sections += 1
            current_heading = stripped
            lines_since_heading = 0
        elif stripped:
            lines_since_heading += 1
    if current_heading is not None and lines_since_heading == 0:
        empty_sections += 1
    return {
        "headings": heading_count,
        "content_lines": content_lines,
        "empty_sections": empty_sections,
        "ratio": round(content_lines / max(heading_count, 1), 1),
    }


# ── Cross-Reference Analysis ─────────────────────────────────────────

def build_reference_matrix(repo_root: Path) -> dict[str, list[str]]:
    """Build a directed graph: file → [files it references]."""
    surface = _iter_surface_files(repo_root)
    # STALE-1: basename → count across the surface, so the basename-mention
    # fallback below can skip non-unique basenames (SKILL.md, README.md, ...).
    _basename_counts: dict[str, int] = {}
    for _p in surface:
        if _p.suffix == ".md":
            _basename_counts[_p.name] = _basename_counts.get(_p.name, 0) + 1
    matrix: dict[str, list[str]] = {}
    for path in surface:
        if not path.suffix == ".md":
            continue
        rel = _rel(path, repo_root)
        text = _safe_text(path)
        targets = _extract_local_links(text)
        # Also check for plain-text mentions of other surface files
        resolved: list[str] = []
        for target in targets:
            # Resolve relative paths
            candidate = (path.parent / target).resolve()
            if candidate.exists():
                try:
                    resolved.append(_rel(candidate, repo_root))
                except ValueError:
                    continue  # Path resolves outside repo root — skip intentionally
        # STALE-1: a bare-basename mention only resolves a cross-ref when the
        # basename is UNIQUE across the surface. `SKILL.md`/`README.md` recur on
        # 10+ surfaces; resolving one mention to all of them is a phantom edge
        # that suppresses orphan detection. Skip the ambiguous ones (a real
        # link is already captured via _extract_local_links above).
        for other in surface:
            if other == path or not other.suffix == ".md":
                continue
            other_name = other.name
            if _basename_counts.get(other_name, 0) != 1:
                continue
            other_rel = _rel(other, repo_root)
            if other_rel not in resolved and other_name in text:
                resolved.append(other_rel)
        matrix[rel] = sorted(set(resolved))
    return matrix


DISCOVERY_DIRS = {".claude/commands/", ".claude/agents/", ".claude/skills/"}
# Surfaces reached by a LOADER, not by a link, so "nothing references it" is not
# a finding: the .claude discovery dirs (a directory scan), memory/ notes (the
# recall index) and every folder-router CLAUDE.md (Claude Code's folder ladder
# loads it on directory entry). Widening the surface without this manufactured
# twelve phantom orphans on the live tree (2026-09-08). Forced twin of the hook
# side's ORPHAN_EXEMPT_PREFIXES + _is_discovery_loaded.
ORPHAN_EXEMPT_PREFIXES = ("memory/",)


def _is_discovery_loaded(rel: str) -> bool:
    return (any(rel.startswith(d) for d in DISCOVERY_DIRS)
            or any(rel.startswith(p) for p in ORPHAN_EXEMPT_PREFIXES)
            or rel.rsplit("/", 1)[-1] == "CLAUDE.md")


def find_orphans(matrix: dict[str, list[str]]) -> list[str]:
    """Markdown surfaces nothing else references, minus the loader-reached ones
    (_is_discovery_loaded): flagging a discovery dir, a memory note or a folder
    router as an orphan is noise rather than signal.
    """
    all_files = set(matrix.keys())
    referenced = set()
    for targets in matrix.values():
        referenced.update(targets)
    # Only flag markdown docs, not config files; skip loader-reached surfaces
    orphans = [
        f for f in all_files - referenced
        if f.endswith(".md") and not _is_discovery_loaded(f)
    ]
    return sorted(orphans)


def find_expected_ref_gaps(repo_root: Path, matrix: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Check expected cross-references. Returns (source, missing_target) pairs."""
    gaps: list[tuple[str, str]] = []
    for source_name, expected_targets in EXPECTED_REFS:
        source_path = repo_root / source_name
        if not source_path.exists():
            continue
        source_rel = source_name
        text = _safe_text(source_path)
        for target in expected_targets:
            if target not in text:
                gaps.append((source_rel, target))
    return gaps


# ── Quality Signals ──────────────────────────────────────────────────

def detect_quality_signals(repo_root: Path) -> list[ReflectFinding]:
    """Detect quality issues: sparse sections, placeholder residue, etc."""
    findings: list[ReflectFinding] = []
    surface = _iter_surface_files(repo_root)
    for path in surface:
        if not path.suffix == ".md":
            continue
        rel = _rel(path, repo_root)
        # Skip discovery-based dirs (harness-deployed command / agent / skill
        # templates). Their intentional substitution markers ({mod}, {module})
        # and short SKILL.md bodies are not incomplete adopter docs; flagging
        # them is first-run false-positive noise, mirroring find_orphans. Skip
        # the residue-exempt records (Core Rule 13): a record that quotes a
        # template string is content, not residue — the old findings corpus
        # alone drew a "high" for 24 quoted tokens. Links in a record are still
        # checked below, exactly as before.
        if any(rel.startswith(d) for d in DISCOVERY_DIRS) or rel in RESIDUE_EXEMPT_SURFACES:
            continue
        text = _safe_text(path)
        # Placeholder detection
        pc = _count_placeholders(text)
        if pc > 0:
            findings.append(ReflectFinding(
                kind="quality_signal",
                severity="medium" if pc <= 3 else "high",
                description=f"{plural(pc, 'placeholder pattern')} in {rel}",
                files=[rel],
            ))
        # Sparse section detection
        density = _section_density(text)
        if density["empty_sections"] > 0:
            findings.append(ReflectFinding(
                kind="quality_signal",
                severity="low",
                description=f"{plural(density['empty_sections'], 'empty section')} in {rel} "
                            f"(content ratio: {density['ratio']} lines/heading)",
                files=[rel],
            ))
        # Very short docs
        if density["content_lines"] < 3 and density["headings"] > 0:
            findings.append(ReflectFinding(
                kind="quality_signal",
                severity="high",
                description=f"{rel} has {density['content_lines']} content lines — "
                            f"likely incomplete",
                files=[rel],
            ))
    return findings


def validate_command_tools(repo_root: Path) -> list[ReflectFinding]:
    """Check that commands reference tools/scripts that exist."""
    findings: list[ReflectFinding] = []
    commands_dir = repo_root / ".claude" / "commands"
    if not commands_dir.exists():
        return findings
    for cmd_file in commands_dir.glob("*.md"):
        text = _safe_text(cmd_file)
        rel = _rel(cmd_file, repo_root)
        # Find script references like "python tools/cc/something.py"
        for m in re.finditer(r"python\s+(tools/[^\s\"']+\.py)", text):
            script_path = m.group(1)
            if not (repo_root / script_path).exists():
                findings.append(ReflectFinding(
                    kind="gap",
                    severity="high",
                    description=f"Command {cmd_file.stem} references `{script_path}` "
                                f"which does not exist",
                    files=[rel],
                ))
    return findings


# ── Full Reflect Pass ────────────────────────────────────────────────

def run_reflect_pass(repo_root: Path, pass_number: int = 1) -> ReflectPass:
    """Execute a complete structured reflect pass.

    This is the programmatic half of the DEEP-WORK reflect protocol.
    It measures what code can measure: cross-references, orphans, gaps,
    quality signals. The cognitive half — emergent patterns, architectural
    insights — requires an LLM re-reading the files with the prompt
    pattern from DEEP-WORK.md Method 1.
    """
    repo_root = repo_root.resolve()
    findings: list[ReflectFinding] = []

    # 1. Build cross-reference matrix
    matrix = build_reference_matrix(repo_root)
    total_refs = sum(len(targets) for targets in matrix.values())
    files_analyzed = len(matrix)
    density = round(total_refs / max(files_analyzed, 1), 2)

    # 2. Find orphans
    orphans = find_orphans(matrix)
    for orphan in orphans:
        findings.append(ReflectFinding(
            kind="orphan",
            severity="medium",
            description=f"{orphan} is not referenced by any other surface file",
            files=[orphan],
        ))

    # 3. Check expected cross-references
    ref_gaps = find_expected_ref_gaps(repo_root, matrix)
    for source, target in ref_gaps:
        findings.append(ReflectFinding(
            kind="gap",
            severity="medium",
            description=f"{source} should reference {target} but doesn't",
            files=[source],
        ))

    # 4. Quality signals
    findings.extend(detect_quality_signals(repo_root))

    # 5. Command validation
    findings.extend(validate_command_tools(repo_root))

    # 6. Broken markdown links (from existing reflection.py logic)
    for path in _iter_surface_files(repo_root):
        if not path.suffix == ".md":
            continue
        text = _text_without_fences(_safe_text(path))
        for m in LOCAL_LINK_RE.finditer(text):
            target = m.group(1).split("#")[0].strip()
            if not target:
                continue
            # Parity with reflection.py — skip trailing-slash directory links
            # (structural nav, valid-when-deployed), angle-bracket placeholder
            # targets and bare ellipsis targets (documentation OF the link shape,
            # not a navigable link). The `<` test is scoped to the target: a real
            # broken link whose display text merely contains `<` must still fire.
            if target.rstrip().endswith("/") or "<" in target or target == "...":
                continue
            candidate = (path.parent / target).resolve() if not target.startswith("/") \
                else (repo_root / target.lstrip("/"))
            if not candidate.exists():
                findings.append(ReflectFinding(
                    kind="gap",
                    severity="high",
                    description=f"Broken link in {_rel(path, repo_root)}: "
                                f"[...]({target}) target does not exist",
                    files=[_rel(path, repo_root)],
                ))
                continue
            # The target file exists -- now check the `#fragment`, which this loop
            # used to discard. A renamed heading leaves the file in place, so the
            # existence check above passes and the link is broken anyway; that is
            # the whole class, and it was invisible here.
            fragment = m.group(1).partition("#")[2].strip()
            if fragment and candidate.suffix == ".md" and candidate.is_file():
                if fragment.lower() not in _heading_anchors(_safe_text(candidate)):
                    findings.append(ReflectFinding(
                        kind="gap",
                        severity="medium",
                        description=f"Broken anchor in {_rel(path, repo_root)}: "
                                    f"[...]({target}#{fragment}) names no such heading",
                        files=[_rel(path, repo_root)],
                    ))

    gap_count = sum(1 for f in findings if f.kind == "gap")
    orphan_count = sum(1 for f in findings if f.kind == "orphan")
    placeholder_count = sum(1 for f in findings if f.kind == "quality_signal"
                           and "placeholder" in f.description)

    return ReflectPass(
        pass_number=pass_number,
        timestamp=datetime.now(timezone.utc).isoformat(),
        findings=findings,
        files_analyzed=files_analyzed,
        total_references=total_refs,
        cross_ref_density=density,
        gap_count=gap_count,
        orphan_count=orphan_count,
        placeholder_count=placeholder_count,
    )


def render_reflect_pass(rp: ReflectPass) -> str:
    """Human-readable render of a reflect pass."""
    lines = [
        f"REFLECT PASS {rp.pass_number}",
        "=" * 40,
        f"Files analyzed:      {rp.files_analyzed}",
        f"Cross-references:    {rp.total_references}",
        f"Cross-ref density:   {rp.cross_ref_density} refs/file",
        f"Gaps:                {rp.gap_count}",
        f"Orphans:             {rp.orphan_count}",
        f"Placeholders:        {rp.placeholder_count}",
        "",
    ]
    if rp.findings:
        by_kind: dict[str, list[ReflectFinding]] = {}
        for f in rp.findings:
            by_kind.setdefault(f.kind, []).append(f)
        for kind in ("gap", "orphan", "quality_signal"):
            items = by_kind.get(kind, [])
            if items:
                lines.append(f"[{kind.upper()}]")
                for item in items:
                    sev = f"[{item.severity}]" if item.severity != "low" else ""
                    lines.append(f"  {sev} {item.description}")
                lines.append("")
    else:
        lines.append("No findings. Surface is coherent.")
    return "\n".join(lines).strip() + "\n"
