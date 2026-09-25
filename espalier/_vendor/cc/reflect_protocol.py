#!/usr/bin/env python3
"""Structured reflect protocol (hook-side standalone) — surface walker.

This is the hook-side version of reflect_protocol. Hooks in
`tools/cc/hooks/` cannot import from `espalier/` (isolation rule
enforced by tests/test_hook_contracts.py), so this file is a
self-contained CLI that does the narrow walk a hook needs.

For the full library version with cross-reference density, orphan
detection, and quality signals used by `espalier doctor` and
`espalier reflect`, see `espalier/reflect_protocol.py` (~425 lines).
The two files share a name and the broad concept but solve different
problems:

  - `tools/cc/reflect_protocol.py` (this file): hook-invoked surface
    walker. Self-contained. Walks SURFACE_ROOTS plus cc/ and
    .claude/ for markdown, plus tools/cc/ for python. Output feeds
    the reflect_trigger hook.
  - `espalier/reflect_protocol.py`: library module imported by
    `espalier.cli` and `espalier.doctor`. Computes density metrics,
    drift findings, and the full reflect report.

Bug fixes that affect both concerns must be applied to both files.
The files measure different things — naming similarity is structural,
not semantic — so there is no whole-file parity test; the axes that MUST
agree are pinned individually by tests/test_reflect_link_guards.py
(broken-link guards + the LOCAL_ONLY_PREFIXES surface exclusion).

Usage:
    python tools/cc/reflect_protocol.py [--pass N] [--json]
"""
from __future__ import annotations
import hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)")
# Forced twin of espalier/reflect_protocol.PLACEHOLDER_PATTERNS across the
# no-import boundary, pinned pattern-for-pattern by
# tests/test_reflect_protocol.py::TestReflectTwinParity. This side carried three
# of the six for months, so the two halves of /reflect disagreed on what residue
# even IS (the DEF-410g lane, 2026-09-08).
PLACEHOLDER_RES = [
    # (?<!\$) excludes ${ENV} refs (e.g. ${CLAUDE_PROJECT_DIR}) from
    # the {placeholder} pattern — shell/env syntax is not template residue.
    re.compile(r"(?<!\$)\{[A-Za-z_][A-Za-z0-9_ ]*\}"),
    re.compile(r"<fill>", re.IGNORECASE),
    re.compile(r"INSERT HERE", re.IGNORECASE),
    re.compile(r"TEMPLATE_ONLY", re.IGNORECASE),
    re.compile(r"TODO[:\s]", re.IGNORECASE),
    re.compile(r"FIXME[:\s]", re.IGNORECASE),
]
# An inline code span is a MENTION of a token, never template residue: every one
# of the 12 placeholder hits /reflect raised on docs/CONVENTIONS.md, SHARP_EDGES.md
# and FAILURE_MODES.md on 2026-09-08 was a backticked identifier such as
# `tests/test_{topic}.py`. A span never crosses a line; a double-backtick span may
# hold a single backtick. Forced twin of the engine's _INLINE_CODE_RE.
_INLINE_CODE_RE = re.compile(r"``[^`\n]*``|`[^`\n]*`")


def _strip_inline_code(text):
    return _INLINE_CODE_RE.sub(" ", text)
# Committed project-memory filename, routed through one per-file constant so a
# future rename is a value flip. Per-file (not a shared import) — tools/cc scripts
# run standalone; adding a sibling import risks the copy-subset footgun.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"
# Forced twin of _blueprint_limits.BLUEPRINT_COLD_DIR_NAME across the
# no-import boundary, same policy as _MEMORY_FILENAME above and
# LOCAL_ONLY_PREFIXES below (locked by tests/test_reflect_link_guards.py).
# The retention cap DEMOTES nodes here instead of deleting them, so the
# parent walk must look here or a demoted ancestor reads as a chain end.
_COLD_DIR_NAME = "_cold"
SURFACE_ROOTS = ["CLAUDE.md", _MEMORY_FILENAME, "docs/CONVENTIONS.md", "docs/SHARP_EDGES.md",
                 "docs/CHEAT-SHEET.md", "docs/TASK_RECIPES.md"]
EXPECTED_REFS = [("CLAUDE.md", [_MEMORY_FILENAME, "docs/SHARP_EDGES.md"]),
                 ("docs/CHEAT-SHEET.md", [_MEMORY_FILENAME, "docs/SHARP_EDGES.md"])]
DISCOVERY_DIRS = {".claude/commands/", ".claude/agents/", ".claude/skills/"}
# Residue-exempt surfaces: the append-only RECORDS (Core Rule 13). A findings
# corpus that quotes a template string, or a session archive that spells "TODO:"
# while describing one, is content, not residue. They stay link-checked exactly
# as before; only the quality scan skips them. Forced twin of the KEYS of
# espalier/claim_extractor.RECORD_SURFACES MINUS docs/FAILURE_MODES.md -- a
# record for its point-in-time counts, but also a catalog adopters receive and
# edit, so residue there must stay reportable (2026-09-08 review). Pinned by
# tests/test_reflect_protocol.py::TestReflectTwinParity.
RESIDUE_EXEMPT_SURFACES = (
    _MEMORY_FILENAME,
    "CHANGELOG.md",
    "docs/session-archive.md",
    "docs/RELEASE_FINDINGS_LEDGER.md",
    "docs/RELEASE_DECISIONS.md",
    "memory/CONVERGENCE_LEDGER.md",
)
# Surfaces reached by a LOADER, not by a link, so "nothing references it" is not
# a finding: the .claude discovery dirs (a directory scan), memory/ notes (the
# recall index) and every folder-router CLAUDE.md (Claude Code's folder ladder
# loads it on directory entry). Widening the surface without this manufactured
# twelve phantom orphans on the live tree. Forced twin of the engine's
# ORPHAN_EXEMPT_PREFIXES + _is_discovery_loaded.
ORPHAN_EXEMPT_PREFIXES = ("memory/",)


def _is_discovery_loaded(rel):
    return (any(rel.startswith(d) for d in DISCOVERY_DIRS)
            or any(rel.startswith(p) for p in ORPHAN_EXEMPT_PREFIXES)
            or rel.rsplit("/", 1)[-1] == "CLAUDE.md")
# Non-navigable local-only trees: the per-session blueprint archive (prose that
# discusses markdown-link syntax as subject matter), the cc/_ underscore class
# (auto-regenerated summaries + gitignored review scratch), and
# cc/SURFACE_HANDOFF.md. cc/GOAL.md is curated — kept scanned. Forced twin of the
# espalier reflect_protocol.LOCAL_ONLY_PREFIXES across the no-import boundary —
# keep the two in sync (locked by tests/test_reflect_link_guards.py).
# The SURFACE_HANDOFF.md entry stays a string literal (not _paths.SURFACE_HANDOFF_REL):
# this forced-twin tuple is compared across the zero-import boundary by
# ast.literal_eval (test_reflect_link_guards.py), and must match the engine twin,
# which cannot import _paths. Hence the per-line path-literal opt-out below.
LOCAL_ONLY_PREFIXES = (
    "cc/blueprints/",
    "cc/_",
    "cc/SURFACE_HANDOFF.md",  # contract: ok path-literal — twin tuple is ast.literal_eval'd for cross-boundary parity
)

# Posix-relative idiom (CLAUDE.md, inline repo-wide). Forced twin of the espalier
# reflect_protocol._rel across the no-import boundary — no shared helper. Leave inline.
def _rel(path, root): return str(path.relative_to(root)).replace("\\", "/")
def _safe(path):
    try: return path.read_text(encoding="utf-8", errors="replace")
    except OSError: return ""

def _safe_rglob(root, pattern="*"):
    """Symlink-safe rglob (local copy — tools/cc has zero espalier imports).
    See espalier/_safe_walk.py for the canonical version. os.walk(followlinks=
    False) never descends a symlinked dir, so it is crash-safe on CPython
    3.10-3.12 where bare rglob follows dir symlinks (ELOOP on a loop)."""
    import fnmatch, os
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            if fnmatch.fnmatch(name, pattern):
                yield base / name

_MD_LINK_TEXT = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_SLUG_DROP = re.compile(r"[^\w\- ]", re.UNICODE)
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")


def _heading_anchors(markdown):
    """Every anchor a GitHub-rendered copy of this document would expose.

    Duplicated from `tests/_md_anchors.py` rather than imported: `tools/cc/` scripts
    run standalone in an adopter repo with zero espalier (and zero tests/) imports, so
    a shared module is not reachable from here. That is the architecture's price and
    it is already how this file works -- the link-skip rules below are inlined from
    espalier/reflection.py for the same reason. Keep the two in step: the calibration
    behind these rules (snake_case survives; only links need unwrapping; a run of
    spaces may slug either way) lives in the tests/ copy's docstring.
    """
    seen, out, fenced = {}, set(), False
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


def _strip_fences(text):
    lines, in_fence = [], False
    for raw in text.splitlines():
        if raw.strip().startswith(("```", "~~~")): in_fence = not in_fence; continue
        if not in_fence: lines.append(raw)
    return "\n".join(lines)

# Trees a folder-router walk must not read, beyond LOCAL_ONLY_PREFIXES: the
# assets mirror (its routers resolve in the adopter tree, not here) and the two
# prefixes the engine's classify_release_path calls local_only that can carry a
# router (the pack tree, the per-install reports). A hand-kept mirror of those
# verdicts across the no-import boundary; pinned equal to the engine's derived
# set on the live tree by TestReflectTwinParity, which proves nothing about
# another tree -- so the list stays SHORT and every entry names its verdict.
_ROUTER_SKIP_PREFIXES = ("espalier/assets/", "task-packs/", "reports/")
# The one router under a skipped prefix that the engine classifies PUBLIC: the
# pack folder's own router ships with the forward ledger since 2026-09-21 (the
# engine carves a named ship set out of the local-only prefix; this is that
# carve-out's router member, mirrored by exact path).
_ROUTER_SHIP_EXACT = ("task-packs/CLAUDE.md",)
# Dependency and build trees the router walk prunes on BOTH halves: an npm
# package ships its own CLAUDE.md, and the classifier calls node_modules/ public.
# Forced twin of the engine's _WALK_SKIP_DIRS.
_WALK_SKIP_DIRS = {"node_modules", "__pycache__", "dist", "build", "site-packages", "venv"}


def _walk_router_docs(root):
    """Every CLAUDE.md under `root` as a repo-relative posix path, from ONE walk
    shape shared by both halves (forced twin of the engine's _walk_router_docs):
    never follows a directory symlink, never enters a nested git repository, a
    dot-directory other than .claude, or a dependency tree. A filesystem walk on
    purpose: Claude Code's folder ladder loads an untracked or gitignored router
    too, and a `git ls-files` route was measured (2026-09-08 review) to drop
    those, to need an encoding pin and quotePath, and to diverge from the engine."""
    import os
    rels = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if not (d.startswith(".") and d != ".claude")
            and d not in _WALK_SKIP_DIRS
            and not (Path(dirpath) / d / ".git").exists())
        if "CLAUDE.md" in filenames:
            rels.append(_rel(Path(dirpath) / "CLAUDE.md", root))
    return sorted(rels)


def _iter_router_docs(root):
    """The folder routers the reflect surface scans: the walk minus the
    local-only and mirror prefixes. The prefix tuples are read into a local
    and never appear in the return expression: the adopter-pointer gate reads
    a constant referenced from a `return` as emitted output, and the local-only
    tuple names a self-host file (test_adopter_pointer_resolution, code arm)."""
    skip = LOCAL_ONLY_PREFIXES + _ROUTER_SKIP_PREFIXES
    ship = _ROUTER_SHIP_EXACT
    hits = []
    for rel in _walk_router_docs(root):
        if rel in ship or not any(rel.startswith(pre) for pre in skip):
            hits.append(root / rel)
    return hits


def iter_surface(root):
    # BC-037: include all docs/**/*.md, not just the entries in
    # SURFACE_ROOTS. Drift between SURFACE_ROOTS and the actual docs/ tree
    # would let orphans, placeholder markers, and broken links in newer docs
    # be silently missed by reflect. Dedupe by absolute path so SURFACE_ROOTS
    # overlap with docs/**/*.md doesn't double-count.
    seen = set()
    hits = []
    for n in SURFACE_ROOTS:
        p = root / n
        if p.exists() and p not in seen:
            hits.append(p); seen.add(p)
    for d in ["cc", ".claude"]:
        dd = root / d
        if dd.exists():
            for p in sorted(_safe_rglob(dd, "*.md")):
                if any(_rel(p, root).startswith(pre) for pre in LOCAL_ONLY_PREFIXES):
                    continue
                if p not in seen:
                    hits.append(p); seen.add(p)
    docs = root / "docs"
    if docs.exists():
        for p in sorted(_safe_rglob(docs, "*.md")):
            if p not in seen:
                hits.append(p); seen.add(p)
    # memory/ (the recall corpus) and every public folder-router CLAUDE.md: both
    # halves of /reflect skipped them while the engine's reflection.py walker
    # already treated them as public (DEF-416a). Orphan-exempt, see above.
    memory_dir = root / "memory"
    if memory_dir.exists():
        for p in sorted(_safe_rglob(memory_dir, "*.md")):
            if p not in seen:
                hits.append(p); seen.add(p)
    for p in _iter_router_docs(root):
        if p not in seen:
            hits.append(p); seen.add(p)
    tcc = root / "tools" / "cc"
    if tcc.exists():
        for p in sorted(_safe_rglob(tcc, "*.py")):
            if p not in seen:
                hits.append(p); seen.add(p)
    return hits

def build_matrix(root, surface=None):
    matrix = {}
    surface = iter_surface(root) if surface is None else surface
    md_files = [p for p in surface if p.suffix == ".md"]
    # Parity with engine build_reference_matrix: basename
    # -> count, so the bare-basename fallback below only resolves a cross-ref
    # when the basename is UNIQUE across the surface. SKILL.md/README.md recur on
    # 10+ surfaces; resolving one mention to all of them is a phantom edge that
    # suppresses orphan detection. The engine twin already has this guard.
    _basename_counts = {}
    for _p in md_files:
        _basename_counts[_p.name] = _basename_counts.get(_p.name, 0) + 1
    for path in md_files:
        rel = _rel(path, root)
        text = _safe(path)
        refs = []
        for m in LOCAL_LINK_RE.finditer(_strip_fences(text)):
            t = m.group(1).split("#")[0].strip()
            if t:
                c = (path.parent / t).resolve()
                if c.exists():
                    try: refs.append(_rel(c, root))
                    except ValueError: pass
        for other in md_files:
            if other != path:
                orel = _rel(other, root)
                if _basename_counts.get(other.name, 0) != 1:
                    continue
                if orel not in refs and other.name in text:
                    refs.append(orel)
        matrix[rel] = sorted(set(refs))
    return matrix


def find_orphans(matrix):
    """Markdown surfaces nothing else references, minus the loader-reached ones.
    Forced twin of the engine's find_orphans."""
    referenced = set()
    for targets in matrix.values():
        referenced.update(targets)
    return sorted(f for f in set(matrix.keys()) - referenced
                  if f.endswith(".md") and not _is_discovery_loaded(f))


def placeholder_findings(root, surface=None):
    """One quality_signal per markdown surface with template residue in its
    prose. Inline code is a mention; the discovery dirs carry intentional
    {mod}-style markers; the record surfaces quote residue as content -- none
    of those count. Severity follows the engine's rule (more than three: high).
    Forced twin of the placeholder half of the engine's detect_quality_signals."""
    findings = []
    for path in (iter_surface(root) if surface is None else surface):
        if path.suffix != ".md":
            continue
        rel = _rel(path, root)
        if any(rel.startswith(d) for d in DISCOVERY_DIRS) or rel in RESIDUE_EXEMPT_SURFACES:
            continue
        text = _strip_inline_code(_strip_fences(_safe(path)))
        hits = sum(len(pat.findall(text)) for pat in PLACEHOLDER_RES)
        if hits:
            findings.append({"kind": "quality_signal",
                             "severity": "medium" if hits <= 3 else "high",
                             "description": f"{hits} placeholder(s) in {rel}"})
    return findings

# --- memory-promotion candidate detector ------------------------------------
# memory_candidates() is the mechanical half of /reflect's "promote durable
# insights" phase — it filters this session's blueprint reasoning entries to
# durable-shaped ones and attaches the nearest existing memory/ note (via the
# _recall ranker) so the skill's LLM layer + the operator can decide
# promote-new vs append vs skip, AND proposes a SHIP-TIER per candidate
# (_propose_ship_tier) so an adopter-relevant insight is routed to a SHIPPING docs
# catalog (reachable via /recall) instead of the non-shipping memory/ folder by
# default -- the recall-indexed memory/ note stays the nearest-note hint. Pure + deterministic; reads the recall
# corpus read-only and writes nothing (propose-not-write, honors the standing
# "never auto-record memories without asking" rule).
#
# recall is a RELATEDNESS oracle, not a DUPLICATE oracle — token overlap cannot
# tell "shares vocabulary" from "states the same insight", so it does NOT
# auto-classify novel-vs-covered (both a genuine novel insight and a pure
# session-history line can clear a topicality floor by matching a tangentially-
# related note). The real noise suppressor is the durability pre-filter
# (eligible kind + not session-history); recall only surfaces the nearest note
# as advisory context for the human/LLM promote-vs-append call.

# Includes alternative_rejected because rejected-design rationale is sometimes
# the most reusable. reflect_insight is deliberately excluded — it is a
# meta-finding about a reflect pass, and surfacing it would let /reflect recurse
# on its own prior insights.
_ELIGIBLE_KINDS = frozenset({"decision", "pattern_discovered", "alternative_rejected"})

# A candidate shorter than this is too thin to be a durable note.
_MIN_CANDIDATE_LEN = 25

# subagent_stop.py auto-records EVERY subagent completion as a `pattern_discovered`
# reasoning entry "[subagent:<type>] <lead>" — the single largest source of
# pattern_discovered entries in this repo's own blueprints. Since DEF-586 the
# entry carries the lead of the agent's final message (with the transcript as
# evidence) rather than a fixed sentence, and it is STILL dropped here: an
# agent's report is a claim (STANDING_PRINCIPLES 3), never a durable note by
# itself -- the operator distils it into a note if it earns one, and the
# blueprint's own readers carry it forward (cognitive_blueprint's report slot).
# Drop any entry whose description starts with this marker. This is the ONLY
# mechanical noise drop, and deliberately so:
#
# Any id/tally "session-history" regex false-positives real insights, because
# this repo's blueprint style embeds pack-ids and "suite NNNN" counts inside
# genuinely durable decisions — and under the governing frame, dropping a
# durable insight is asymmetrically worse than leaking one skippable terse-
# history row. The "[subagent:" prefix is the one CLEAN signal: a
# machine-generated marker that never appears in human-authored insight.
# Everything else — "is this a terse status report or a reusable insight?" — is
# a durability judgment that belongs to the skill body + operator, NOT a fragile
# mechanical regex.
_ACTIVITY_LOG_PREFIX = "[subagent:"


def _load_recall():
    """Import the ``_recall`` ranker sibling (tools/cc/hooks/).

    Guarded: returns ``None`` if unavailable so the candidate pass degrades
    rather than crashing the reflect run (hook-fail-open discipline). ``_recall``
    guards its CLI under ``__main__``, so importing runs only side-effect-free
    module code; it pulls in ``_hook_utils`` + ``_reinject`` (both tools/cc/hooks
    siblings, zero-espalier), hence the hooks dir on ``sys.path``. Importing a
    tools/cc sibling adds NO espalier import — the isolation contract holds.
    """
    hooks_dir = Path(__file__).resolve().parent / "hooks"
    try:
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        import _recall  # noqa: PLC0415
        return _recall
    except Exception:  # noqa: BLE001 -- optional dependency; degrade to no-nearest
        return None


# A SessionStart (compact / resume / new CC session) starts a FRESH blueprint
# (session_start.py + session_resume.py both shell `cognitive_blueprint start`),
# so ONE work session's reasoning scatters across several per-session files.
# Reading only the newest (latest.json) means a /reflect that runs after any
# mid-session rotation surfaces nothing — the exact failure the candidate pass is
# meant to prevent. So we walk the blueprint lineage and aggregate, bounded by:
#   * the parent_session_id CHAIN — the true lineage cmd_start records, not an
#     mtime sort. (mtime is fragile: the CURRENT blueprint is rewritten on every
#     record/finalize so its mtime is "now", while a prior blueprint's mtime is
#     frozen at its last touch — the gap between them balloons during long waits
#     even WITHIN one session. Verified live: a 45-min wait split the session.)
#   * a session GAP on the stable `timestamp` (creation time, never rewritten):
#     parent more than this far back in creation time = a separate prior session.
#   * a hard CAP on chain hops — a safety net.
# We deliberately do NOT use a "finalized" flag as the boundary: Stop-gate Gate 4
# auto-finalizes the blueprint at EVERY turn end, so continuation_fragments is set
# mid-session and is not a reliable handoff marker (verified on the live chain).
_SESSION_GAP_SECONDS = 3600   # 60 min: a creation gap this long = a separate session
_CHAIN_SCAN_CAP = 12          # never walk more than this many blueprints back


def _blueprint_created_at(bp):
    """Epoch seconds from a blueprint's stable ``timestamp`` field, or None."""
    try:
        return datetime.fromisoformat(bp.get("timestamp", "")).timestamp()
    except (ValueError, TypeError):
        return None


def _load_session_entries(root):
    """Return this work-session's blueprint reasoning entries (read-only).

    Walks the ``parent_session_id`` lineage from the current blueprint, gathering
    ``reasoning_entries`` until the creation-time gap to the parent exceeds
    :data:`_SESSION_GAP_SECONDS` (a separate prior session) or
    :data:`_CHAIN_SCAN_CAP` hops. Returns them chronological (oldest-first).
    Degrades to ``[]`` on any error. Uses the ``cognitive_blueprint`` sibling's
    ``_bp_dir``/``_load_latest`` so the root resolves via ``$CLAUDE_PROJECT_DIR``
    the same way the corpus root (:func:`_candidate_root`) does.
    """
    # Ensure this script's own dir is importable so the `cognitive_blueprint`
    # sibling resolves whether we run as the CLI (dir is sys.path[0]) or are
    # imported via importlib (the test path, where it is not).
    cc_dir = str(Path(__file__).resolve().parent)
    if cc_dir not in sys.path:
        sys.path.insert(0, cc_dir)
    try:
        import cognitive_blueprint as _cb  # noqa: PLC0415 -- tools/cc sibling
        from _json_safe import load_json_dict_safe  # noqa: PLC0415
        bp_dir = _cb._bp_dir()
        current = _cb._load_latest()
    except Exception:  # noqa: BLE001 -- blueprint optional; degrade quietly
        return []
    if not isinstance(current, dict):
        return []

    chain: list = []  # newest-first
    seen_ids: set = set()
    bp = current
    for _hop in range(_CHAIN_SCAN_CAP):
        sid = bp.get("session_id")
        if not sid or sid in seen_ids:
            break
        seen_ids.add(sid)
        chain.append(bp)
        parent_id = bp.get("parent_session_id")
        if not parent_id:
            break
        parent_file = bp_dir / f"{parent_id}.json"
        if not parent_file.is_file() or parent_file.is_symlink():
            # Demoted past the retention cap: the node is in _cold/, not
            # gone. Without this fallback a chain whose ancestor was
            # demoted breaks BYTE-IDENTICALLY to one whose ancestor was
            # deleted -- preserved bytes the tooling cannot reach are not
            # a preserved record.
            parent_file = bp_dir / _COLD_DIR_NAME / f"{parent_id}.json"
            if not parent_file.is_file() or parent_file.is_symlink():
                break
        try:
            parent = load_json_dict_safe(parent_file.read_text(encoding="utf-8"), default=None)
        except (OSError, UnicodeDecodeError):
            break
        if not isinstance(parent, dict):
            break
        t_cur, t_par = _blueprint_created_at(bp), _blueprint_created_at(parent)
        if t_cur is not None and t_par is not None and (t_cur - t_par) > _SESSION_GAP_SECONDS:
            break  # parent belongs to a prior work session
        bp = parent

    collected: list = []
    for bp in reversed(chain):  # oldest-first
        entries = bp.get("reasoning_entries", [])
        if isinstance(entries, list):
            collected.extend(entries)
    return collected


# Ship-tier heuristic for a promotion candidate. memory_candidates
# used to imply a single destination -- the non-shipping memory/ folder. It now
# proposes a TIER so the /reflect operator/LLM layer can route an adopter-relevant
# lesson to a SHIPPING surface instead:
#   SHIP_ADOPTER     -> docs/FAILURE_MODES.md, the one catalog deployed WITH ITS
#                       CONTENT (byte-mirrored into espalier/assets/docs/), so an
#                       entry there is reachable by adopters via /recall
#   SELFHOST_DEV     -> the repo memory/ corpus (tracked, dogfooding, non-shipping)
#   OPERATOR_PRIVATE -> keep local (operator identity / personal workflow)
#
# NOT ship targets: docs/SHARP_EDGES.md and docs/CONVENTIONS.md. Both are init-seeded
# from assets/seed/ as near-empty STUBS -- "refreshed on re-init only while it still
# matches the copy it was deployed from" -- so the host repo fills them with ITS OWN
# patterns and footguns. This repo's copies are contributor content an adopter never
# receives; routing an adopter-relevant lesson there reaches nobody. They remain the
# right home for a footgun THIS repo trips on -- just not a SHIP_ADOPTER destination.
# ADVISORY ONLY -- the operator/LLM layer confirms; nothing is auto-written. A
# keyword signal, not a classifier (the human makes the real call, as it already
# does for the nearest-note hint). Ordered most-restrictive first, so an
# operator-private note that also names a self-host token stays private.
_SHIP_SELFHOST_RE = re.compile(
    r"\bTP-\d|\bespalier\b|write_guard|_reinject|\bfuse\b|\bvendor\b|self-?host|scanner",
    re.IGNORECASE,
)
_SHIP_OPERATOR_RE = re.compile(
    r"@\w+|co-?author|trailer|commit to main|no[- ]branch|\bI prefer\b|my workflow",
    re.IGNORECASE,
)
_SHIP_CATALOG_TARGET = "docs/FAILURE_MODES.md"


def _propose_ship_tier(text):
    """Return ``(ship_tier, ship_target)`` for a candidate insight -- an ADVISORY
    heuristic the operator/LLM layer confirms (never auto-written). See the
    tier notes above."""
    if _SHIP_OPERATOR_RE.search(text):
        return ("OPERATOR_PRIVATE", "-")
    if _SHIP_SELFHOST_RE.search(text):
        return ("SELFHOST_DEV", "memory/")
    return ("SHIP_ADOPTER", _SHIP_CATALOG_TARGET)


def _norm(text):
    """The ONE normalization that defines 'the same candidate' -- shared by the
    within-session de-dupe and the cross-session suppression key so the two
    can never drift."""
    return " ".join(text.lower().split())


def _candidate_key(text):
    """Stable, compact identity for a candidate insight, safe to log verbatim.
    A digest of the NORMALIZED RAW text (not the rendered/displayed line), so
    the key survives whitespace/case reflow and display truncation -- the
    render->key footgun the disposition log would otherwise re-open. sha256
    (no insecure-hash lint); 12 hex is ample for a per-repo operator log."""
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()[:12]


def memory_candidates(root, entries):
    """Surface durable-insight promotion candidates from blueprint reasoning.

    ``entries`` is a list of blueprint reasoning-entry dicts
    (``{"kind", "description", ...}``). Returns a list of candidate dicts
    ``{"text", "kind", "nearest_note", "nearest_score", "ship_tier",
    "ship_target"}`` in chronological
    order, where ``nearest_note`` is the closest existing ``memory/`` note (or
    ``None`` when recall suppresses) and ``nearest_score`` its IDF score.

    Pre-filter: keep only :data:`_ELIGIBLE_KINDS`, drop ``[subagent:`` activity
    logs (:data:`_ACTIVITY_LOG_PREFIX` — the one mechanical noise drop), drop
    too-short entries, and de-dupe identical descriptions within the session.
    ``recall`` then attaches the nearest note as ADVISORY context — it does not
    classify novel-vs-covered. The "is this a reusable insight or a terse
    status line?" durability judgment is the skill body's + operator's, not a
    mechanical regex. No LLM, no writes.
    """
    root = Path(root)
    recall_mod = _load_recall()
    out = []
    seen = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("kind", "") not in _ELIGIBLE_KINDS:
            continue
        text = (e.get("description") or "").strip()
        if text.startswith(_ACTIVITY_LOG_PREFIX):
            continue  # transient subagent activity log, not a durable insight
        if len(text) < _MIN_CANDIDATE_LEN:
            continue
        norm = _norm(text)
        if norm in seen:
            continue
        seen.add(norm)
        nearest_note, nearest_score, nearest_notes = None, 0.0, []
        if recall_mod is not None:
            # TITLE match, not body match, and THREE of them rather than one.
            # `recall()` scores against document bodies and is built for a short
            # topic; handing it a whole reasoning entry made the largest document
            # in the corpus win on breadth -- measured, five consecutive entries
            # on five unrelated subjects all returned the same 1718-token ledger.
            # A "nearest note" question is really "which note is ABOUT this",
            # which is what a title says, and titles are short enough that the
            # size bias cannot arise. Showing three keeps a weak hit legible as
            # one option among several instead of reading as an answer.
            try:
                hits = recall_mod.nearest_by_title(text, root, top=3)
            except Exception:  # noqa: BLE001 -- recall is advisory; degrade
                hits = []
            if hits:
                nearest_note, nearest_score = hits[0].source, hits[0].score
                nearest_notes = [(h.source, h.score) for h in hits]
        ship_tier, ship_target = _propose_ship_tier(text)
        out.append({
            "text": text,
            "kind": e.get("kind", ""),
            "key": _candidate_key(text),
            # `nearest_note`/`nearest_score` stay top-1: the disposition-log
            # schema in the reflect skill (which SHIPS) names them, so they are a
            # contract, not an implementation detail. `nearest_notes` is additive.
            "nearest_note": nearest_note,
            "nearest_score": nearest_score,
            "nearest_notes": nearest_notes,
            "ship_tier": ship_tier,
            "ship_target": ship_target,
            # One contract for every candidate: a consumer may read `held`
            # without a membership test. Held rows from the log set both.
            "held": False,
            "held_since": None,
        })
    return out


def _print_candidates(cands, as_json, skip_rate=None, suppressed_count=0,
                      unreadable=0, ignored=0):
    """Render the MEMORY CANDIDATES report (suppress-on-empty) + skip-rate.

    ``unreadable`` / ``ignored`` are the log lines the read dropped (see
    ``_read_disposition_log_report``); the JSON always carries both keys, the
    text prints them only when non-zero, like every other advisory line."""
    if as_json:
        print(json.dumps({"memory_candidates": cands, "skip_rate": skip_rate,
                          "suppressed": suppressed_count,
                          "unreadable": unreadable, "ignored": ignored}, indent=2))
        return
    if unreadable or ignored:
        # Before the candidates: a candidate shown as undecided below may be
        # one of these rows, and the operator should know that before they
        # re-decide it.
        print(f"UNREADABLE LOG LINES: {unreadable} not JSON, {ignored} parsed but "
              f"carrying no string disposition ({_CANDIDATE_LOG_REL}). A decision "
              "recorded on such a line is not read: the candidate below may be one "
              "you already dispositioned. Rewrite each as ONE json.dumps line per key.")
    if not cands:
        print("MEMORY CANDIDATES: none")
    else:
        print(f"MEMORY CANDIDATES: {len(cands)}")
        for c in cands:
            if c.get("held"):
                print(f"  [held since {c['held_since']}] [{c['kind']}] {c['text']}")
                print(f"      key: {c.get('key', '?')}  (held in {_CANDIDATE_LOG_REL}; "
                      "re-proposed every run until a promoted/updated/skipped row lands)")
                # The exact row that retires it. A resolution row without the
                # verbatim key never retires a hold (the paraphrase re-keys to
                # something else), so the row is printed rather than described.
                print("      to retire, append: "
                      + json.dumps({"key": c.get("key", "?"), "disposition": "skipped"})
                      + "  (or promoted / updated)")
                continue
            print(f"  [{c['kind']}] {c['text']}")
            print(f"      key: {c.get('key', '?')}  (log this verbatim with the disposition)")
            if c.get("nearest_notes"):
                print("      closest existing notes by title (advisory -- a new "
                      "insight often has no near neighbour):")
                for src, sc in c["nearest_notes"]:
                    print(f"        {sc:7.2f}  {src}")
            elif c["nearest_note"]:
                print(f"      nearest: {c['nearest_note']}  (score {c['nearest_score']})")
            else:
                print("      nearest: (none -- no related note in memory/ corpus)")
    held = [c for c in cands if c.get("held")]
    if held:
        # A hold has no expiry and leaves the skip-rate, so the pile is the
        # one alert-fatigue path the metric can no longer see. Count it here.
        print(f"HELD: {len(held)} awaiting a decision (first parked {held[0]['held_since']})")
        if len(held) > _HELD_PILE_HINT:
            print(f"  hint: more than {_HELD_PILE_HINT} held candidates -- decide or skip them; "
                  "a hold that never resolves is alert-fatigue the skip-rate cannot see.")
    # Feedback loop: candidates the operator already dispositioned -- skipped,
    # promoted OR updated -- are hidden so an insight already dealt with is not
    # re-proposed every run (advisory). Single summary line (suppressed
    # candidates are already filtered out of `cands`).
    if suppressed_count:
        print(f"SUPPRESSED: {suppressed_count} already-dispositioned candidate(s) "
              f"hidden (skipped/promoted/updated in {_CANDIDATE_LOG_REL})")
    # The skip-rate is historical (independent of this session's yield), so it
    # prints even when no new candidates surfaced.
    if skip_rate:
        r, a = skip_rate["recent"], skip_rate["all_time"]
        print(f"SKIP-RATE: {r['skipped']}/{r['total']} last-{skip_rate['window_size']} "
              f"({r['skip_rate']:.0%}), {a['skipped']}/{a['total']} all-time ({a['skip_rate']:.0%})")
        if skip_rate["noisy"]:
            print("  hint: high skip-rate -- the durability bar may be too low; consider tightening "
                  "_ELIGIBLE_KINDS / _MIN_CANDIDATE_LEN (advisory; operator judgment).")
        if skip_rate.get("coarse_clock"):
            print(f"  hint: {skip_rate['coarse_clock']} of the last-{skip_rate['window_size']} rows "
                  "carry a coarse or missing clock (a bare date, a naive time, or none) -- the "
                  "window is by time; write session_ts in the SKILL's one spelling.")


def _candidate_root() -> Path:
    """Resolve the project root for the candidate pass the way ``_recall``'s own
    CLI does: honor ``$CLAUDE_PROJECT_DIR`` via ``resolve_project_root()`` so
    the recall corpus root matches the blueprint root even when ``/reflect``
    runs from a subdirectory.

    Without this the two halves diverge — ``_load_session_entries`` loads the
    blueprint via ``cognitive_blueprint`` (env-resolved) while the corpus would
    read ``cwd/memory`` — so a subdir launch silently renders EVERY candidate's
    nearest note as "(none)", a false-novel signal. Falls back to cwd if the
    helper is unavailable.
    """
    hooks_dir = Path(__file__).resolve().parent / "hooks"
    try:
        if str(hooks_dir) not in sys.path:
            sys.path.insert(0, str(hooks_dir))
        from _hook_utils import resolve_project_root  # noqa: PLC0415
        return resolve_project_root()
    except Exception:  # noqa: BLE001 -- helper optional; degrade to cwd
        return Path(".").resolve()


# --- skip-rate reader: mechanical surfacing of the anti-theater metric --------
# The disposition log (.espalier/memory_candidate_log.jsonl) is an append-only
# operator-judgment sink that, until now, NOTHING read — the SKILL told the
# operator to "watch the skip-rate" by hand. memory_candidate_skip_rate() tallies
# it so the candidate pass can print the metric. ADVISORY ONLY: a high skip-rate
# hints the durability bar is too low, but the operator still makes the tightening
# call (design intent: "No mechanical enforcement; operator judgment"). Guarded:
# a missing/torn/malformed log degrades to None, never crashing the pass.
_CANDIDATE_LOG_REL = ".espalier/memory_candidate_log.jsonl"
_SKIP_RATE_WINDOW = 20            # last-N dispositions ~= the SKILL's "~10 sessions"
_SKIP_RATE_NOISE_THRESHOLD = 0.6  # recent rate >= this -> print the "too loose" hint
_HELD_PILE_HINT = 5               # more held rows than this -> print the "decide them" hint


def _read_disposition_log_report(root: Path) -> "tuple[list, int, int]":
    """``(rows, unreadable, ignored)``: the disposition rows (list of dicts)
    in FILE order, the count of lines that are not JSON, and the count of
    lines that parse but are not a dict with a string ``disposition``.

    The log has no Python writer, so "oldest-first" is what the append
    discipline intends, not what the file promises; a reader that needs time
    order sorts with _sorted_by_time (the skip-rate window does). A torn line
    is SKIPPED, never fatal -- and COUNTED, because a skipped row is a decision
    the operator made that the candidate pass will re-propose as undecided
    (DEF-764: one hand-typed row with raw newlines inside a string became
    several unparseable lines, and five decided candidates came back as
    `[held since ...]` at the next pass). ``([], 0, 0)`` when the log cannot
    be opened. Decoded with ``errors="replace"``, as the landing check reads
    the same file: the log is hand-written, and a row saved by an editor in
    another encoding is a row with one mangled character, not a lost log --
    the old strict decode threw the whole file away and reported nothing."""
    try:
        raw = (root / _CANDIDATE_LOG_REL).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0, 0
    rows = []
    unreadable = ignored = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            unreadable += 1
            continue  # skip a torn/partial append; never fail the whole read
        if isinstance(row, dict) and isinstance(row.get("disposition"), str):
            rows.append(row)
        else:
            ignored += 1
    return rows, unreadable, ignored


def _read_disposition_log(root: Path) -> list:
    """The rows alone -- every reader that only needs them."""
    return _read_disposition_log_report(root)[0]


# The SKILL's writer is a session appending JSON by hand, and the live log on
# 2026-09-08 carried six spellings of `session_ts` (ISO with `+00:00`, with `Z`,
# with microseconds, the blueprint id `YYYYMMDD-HHMMSS-hex`, a bare date) plus six
# rows whose only clock was a legacy `date` key -- and the last-20 window by file
# order already disagreed with the window by time. So the window is by TIME, and
# every shape the log has ever carried parses; the SKILL now pins the one shape
# new rows are written in.
_BLUEPRINT_ID_TS_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})")
_DATE_ONLY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _disposition_clock(row):
    """(when, precise) for a row: its clock as an aware UTC datetime, or None
    when no shape fits, and whether that clock is trustworthy to the second
    with an explicit zone. `session_ts` first, then the legacy `date` key. A
    bare date reads as midnight and a naive time as UTC -- both PARSE, and both
    can be hours off, which is why they are reported as coarse rather than
    silently trusted (the review's "spellings that parse as the wrong instant")."""
    for key in ("session_ts", "date"):
        raw = row.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        raw = raw.strip()
        m = _BLUEPRINT_ID_TS_RE.match(raw)
        if m:   # the harness's own id: UTC to the second
            try:
                return datetime(*map(int, m.groups()), tzinfo=timezone.utc), True
            except ValueError:
                continue
        m = _DATE_ONLY_RE.match(raw)
        if m:   # midnight of that day: coarse
            try:
                return datetime(*map(int, m.groups()), tzinfo=timezone.utc), False
            except ValueError:
                continue
        iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if parsed.tzinfo is None:   # a local-clock naive value: coarse
            return parsed.replace(tzinfo=timezone.utc), False
        return parsed, True
    return None, False


def _disposition_when(row):
    """The row's clock as an aware UTC datetime, or None when no shape fits."""
    return _disposition_clock(row)[0]


def _sorted_by_time(rows):
    """Rows oldest-first by their clock, stable. A row with no readable clock
    inherits the clock of the nearest dated row ABOVE it in the file: the append
    discipline is the only evidence of when it was written, and the three such
    rows in the live log on 2026-09-08 were that day's newest decisions -- read
    as "oldest" they would have left the recent window. Undated rows before any
    dated row read as the epoch."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    keyed = []
    last = epoch
    for i, row in enumerate(rows):
        when = _disposition_when(row)
        if when is not None:
            last = when
        keyed.append((last, i, row))
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [row for _, _, row in keyed]


def memory_candidate_skip_rate(root: Path):
    """All-time + recent-window skip summary for the candidate pass, or None if
    the log holds no decision. The recent window is the last N by TIME
    (_sorted_by_time), not by file position (DEF-589).

    DECISIONS ONLY. A row whose disposition is not in RESOLVED_DISPOSITIONS --
    ``held``, or an unrecognised value -- is neither a skip nor a promotion and
    leaves the denominator. Before this (DEF-685) any string disposition
    counted: four ``HOLD --`` rows a session wrote for candidates it had not
    decided sat in the denominator of the one metric the SKILL tells the
    operator to watch, deflating it. Measured on the live log, 2026-09-05:
    79/118 -> 79/114 all-time.
    """
    rows = _sorted_by_time([r for r in _read_disposition_log(root)
                            if r.get("disposition") in RESOLVED_DISPOSITIONS])
    if not rows:
        return None

    def _tally(subset):
        n = len(subset)
        skipped = sum(1 for r in subset if r.get("disposition") == "skipped")
        return {"total": n, "skipped": skipped,
                "skip_rate": round(skipped / n, 3) if n else 0.0}

    window = rows[-_SKIP_RATE_WINDOW:]
    recent = _tally(window)
    # Rows in the window whose clock is a bare date, a naive time, or absent:
    # they sort, but by an instant that can be hours off. The printer turns the
    # count into the one nudge the SKILL's prose cannot deliver.
    coarse = sum(1 for r in window if not _disposition_clock(r)[1])
    return {"all_time": _tally(rows), "recent": recent,
            "window_size": _SKIP_RATE_WINDOW,
            "noisy": recent["skip_rate"] >= _SKIP_RATE_NOISE_THRESHOLD,
            "coarse_clock": coarse}


# A disposition means the operator DEALT WITH that candidate; all three of them
# do. Suppressing only `skipped` made the pass re-propose a PROMOTED insight
# forever, and the only two answers to a re-proposal are "skip it again" --
# which inflates the skip-rate, the very metric that then advises the durability
# bar is too low -- or "promote a duplicate". The metric degraded as a function
# of successful promotions. Measured: back-filling two promotions the operator
# had made but never logged moved the rate 75% -> 65% on its own.
#
# NOT the deferred maturity/expiry policy from this feature's own scope-out
# ("un-suppress / skipped N times but keeps recurring"). That axis is about
# suppression being too STICKY; this is the opposite -- two dispositions that
# never suppressed at all. The scope-out reasoned entirely on the `skipped`
# axis and so never asked what `promoted` and `updated` should do.
#
# Enumerated rather than "any non-empty disposition": an unrecognized value is
# a typo or a future disposition whose semantics are unknown, and silently
# suppressing on it would hide candidates for a reason nobody chose.
RESOLVED_DISPOSITIONS: frozenset = frozenset({"skipped", "promoted", "updated"})


def resolved_candidate_keys(root: Path) -> set:
    """Stable keys of every candidate the operator already dispositioned --
    ``skipped``, ``promoted`` or ``updated`` -- the suppression set fed back
    into the candidate pass so an insight that has been dealt with is not
    re-proposed on the next run. Prefers each row's machine-emitted
    ``key`` (copied verbatim from the printed candidate); falls back to
    re-deriving it from the row's ``candidate`` text for legacy rows written
    before the key existed. Guarded via _read_disposition_log: any error ->
    empty set (no suppression), never crashes the pass (advisory, fail-open)."""
    keys = set()
    for row in _read_disposition_log(root):
        if row.get("disposition") not in RESOLVED_DISPOSITIONS:
            continue
        k = row.get("key")
        if isinstance(k, str) and k:
            keys.add(k)
        else:
            # Legacy fallback (rows written before the machine `key` existed):
            # re-derive from the freehand `candidate`. The pre-key SKILL never
            # instructed a VERBATIM `candidate`, so this holds only for a
            # byte-faithful transcription -- a paraphrased legacy row silently
            # under-suppresses. Best-effort by design; every new row carries `key`.
            cand = row.get("candidate")
            if isinstance(cand, str) and cand.strip():
                keys.add(_candidate_key(cand))
    return keys


#: The fourth disposition, and the only one that is not a decision. A candidate
#: the operator has read but not yet promoted, updated or skipped is ``held``:
#: its row keeps the text and the key, it suppresses nothing, it leaves the
#: skip-rate, and the candidate pass RE-PROPOSES IT FROM THE LOG on every run
#: until a resolved row for the same key lands. Before this existed (DEF-685) a
#: held candidate had no durable home: one session wrote ``HOLD --`` rows the
#: enumeration could not read, the next wrote the keys into the memory row and
#: called them "logged", and the lineage walk above forgot both past the
#: session gap -- five cited keys, zero log rows, `MEMORY CANDIDATES: none`.
HELD_DISPOSITION = "held"


def held_candidates(root: Path) -> list:
    """Candidates the operator parked with a ``held`` row and has not resolved.

    Shaped like :func:`memory_candidates` output so the printer and the JSON
    contract need no second branch, plus ``held_since`` (the row's
    ``session_ts``) so the report can say how long it has waited. The LOGGED
    key is authoritative: a held row's ``candidate`` cell is what the operator
    wrote, which in most live rows is a paraphrase rather than the verbatim
    text the key was derived from, so re-keying it would break the link a later
    ``promoted``/``updated``/``skipped`` row uses to retire the hold. A keyless
    row falls back to its text the way :func:`resolved_candidate_keys` does; a
    row with neither proposes nothing.

    ORDER IS THE CONTRACT. A hold is retired by a resolved row for the same key
    that comes AFTER it in file order; a ``held`` row written after a decision
    re-opens the candidate (the operator changed their mind, and the SKILL's
    "until a decision row lands" reads as *subsequently*). The last held row
    per key in file order wins. File order is insertion order only as far as
    the append discipline holds -- see _read_disposition_log. Deliberately NOT
    the time order the skip-rate window uses (_sorted_by_time): a decision
    stamped with a bare date sorts to midnight, BEFORE a hold written that
    morning, and time order would leave such a hold re-proposed forever; the
    window tolerates hours of slop, retirement does not (pinned by
    test_a_date_only_decision_after_a_hold_still_retires_it). Guarded through
    the reader: any error -> empty list, never crashes the pass.
    """
    last_resolved: dict = {}   # key -> index of its newest resolved row
    held_rows: dict = {}       # key -> (index, row) of its last held row
    for idx, row in enumerate(_read_disposition_log(root)):
        disposition = row.get("disposition")
        text = row.get("candidate")
        text = text.strip() if isinstance(text, str) else ""
        key = row.get("key")
        if not (isinstance(key, str) and key):
            key = _candidate_key(text) if text else None
        if disposition in RESOLVED_DISPOSITIONS:
            if key:
                last_resolved[key] = idx
            continue
        if disposition != HELD_DISPOSITION or key is None:
            continue
        held_rows[key] = (idx, row)
    by_key: dict = {}
    for key, (idx, row) in held_rows.items():
        if last_resolved.get(key, -1) > idx:
            continue  # a decision landed after the hold: retired
        text = row.get("candidate")
        text = text.strip() if isinstance(text, str) else ""
        ship_tier, ship_target = _propose_ship_tier(text) if text else (None, None)
        by_key[key] = {
            "text": text or "(held row carries no candidate text)",
            "kind": row.get("kind") or "held",
            "key": key,
            "nearest_note": row.get("nearest_note"),
            "nearest_score": 0.0,
            "nearest_notes": [],
            "ship_tier": ship_tier,
            "ship_target": ship_target,
            # `held` is the discriminator the printer reads; `held_since` is
            # display only, so a row that never recorded a session_ts still
            # renders as held rather than as a fresh lineage candidate.
            "held": True,
            "held_since": row.get("session_ts") or "an unrecorded session",
        }
    return list(by_key.values())


def suppress_resolved(cands: list, resolved_keys: set) -> list:
    """Drop candidates whose stable ``key`` is in ``resolved_keys`` (already
    dispositioned). Pure filter -- only the operator-invoked --candidates pass
    applies it; the reflect_trigger hook path (--pass 1 --json) never does."""
    if not resolved_keys:
        return cands
    return [c for c in cands if c.get("key") not in resolved_keys]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Structured reflect protocol")
    parser.add_argument("--pass", dest="pass_number", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    # Memory-promotion candidate pass. Separate flag (NOT the default
    # report) so the reflect_trigger hook — which calls `--pass 1 --json` on
    # every 10th source write — never runs it (too frequent).
    # Only the operator-invoked /reflect skill passes --candidates.
    parser.add_argument("--candidates", action="store_true",
                        help="emit memory-promotion candidates instead of the surface report")
    args = parser.parse_args()

    if args.candidates:
        # Env-resolved root so the corpus and the blueprint agree from any cwd.
        cand_root = _candidate_root()
        raw = memory_candidates(cand_root, _load_session_entries(cand_root))
        shown = suppress_resolved(raw, resolved_candidate_keys(cand_root))
        suppressed = len(raw) - len(shown)
        # Held rows come FROM THE LOG, not the lineage: a candidate parked last
        # week is in no blueprint the walk can still reach (DEF-685). On a key
        # collision the lineage copy wins, so one insight is never shown twice.
        shown_keys = {c.get("key") for c in shown}
        shown = shown + [h for h in held_candidates(cand_root)
                         if h["key"] not in shown_keys]
        _rows, unreadable, ignored = _read_disposition_log_report(cand_root)
        _print_candidates(
            shown,
            args.json,
            skip_rate=memory_candidate_skip_rate(cand_root),
            suppressed_count=suppressed,
            unreadable=unreadable,
            ignored=ignored,
        )
        return 0
    root = Path(".").resolve()
    surface = iter_surface(root)   # one walk; the matrix, the residue scan and the link loop share it
    matrix = build_matrix(root, surface)
    total_refs = sum(len(v) for v in matrix.values())
    files = len(matrix)
    density = round(total_refs / max(files, 1), 2)
    orphans = find_orphans(matrix)

    findings = []
    for o in orphans:
        findings.append({"kind": "orphan", "severity": "medium",
                         "description": f"{o} is not referenced by any other surface file"})
    for src, expected in EXPECTED_REFS:
        if (root / src).exists():
            text = _safe(root / src)
            for tgt in expected:
                if tgt not in text:
                    findings.append({"kind": "gap", "severity": "medium",
                                     "description": f"{src} should reference {tgt}"})
    findings.extend(placeholder_findings(root, surface))
    for path in surface:
        if path.suffix != ".md": continue
        rel = _rel(path, root)
        text = _strip_fences(_safe(path))
        for m in LOCAL_LINK_RE.finditer(text):
            t = m.group(1).split("#")[0].strip()
            if not t: continue
            # Parity with espalier/reflection.py (inlined — tools/cc has zero
            # espalier imports): skip dir-links / <placeholder>-in-target /
            # ellipsis. The `<` test is on the target, not the whole span — a
            # real broken link whose display text contains `<` still fires.
            if t.rstrip().endswith("/") or "<" in t or t == "...": continue
            c = (path.parent / t).resolve() if not t.startswith("/") else (root / t.lstrip("/"))
            if not c.exists():
                findings.append({"kind": "gap", "severity": "high",
                                 "description": f"Broken link in {rel}: {t}"})
                continue
            # The target file exists -- now check the `#fragment`, which this loop
            # used to discard. A renamed heading leaves the file in place, so the
            # existence check above passes and the link is broken anyway; that is
            # the whole class, and it was invisible here.
            frag = m.group(1).partition("#")[2].strip()
            if frag and c.suffix == ".md" and c.is_file():
                if frag.lower() not in _heading_anchors(_safe(c)):
                    findings.append({"kind": "gap", "severity": "medium",
                                     "description": f"Broken anchor in {rel}: {t}#{frag}"})

    gap_count = sum(1 for f in findings if f["kind"] == "gap")
    report = {
        "pass_number": args.pass_number,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files_analyzed": files,
        "total_references": total_refs,
        "cross_ref_density": density,
        "gap_count": gap_count,
        "orphan_count": len(orphans),
        "findings": findings,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"REFLECT PASS {args.pass_number}")
        print("=" * 40)
        print(f"Surface files:     {files}")
        print(f"Cross-references:  {total_refs}")
        print(f"Cross-ref density: {density} refs/file")
        print(f"Gaps:              {gap_count}")
        print(f"Orphans:           {len(orphans)}")
        if findings:
            print()
            for f in findings:
                sev = f"[{f['severity']}] " if f["severity"] != "low" else ""
                print(f"  [{f['kind'].upper()}] {sev}{f['description']}")
        else:
            print("\nNo findings. Surface is coherent.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
