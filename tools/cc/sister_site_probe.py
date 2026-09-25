"""Sister-site compression probe.

Stdlib-only AST scanner that surfaces near-duplicate function bodies.
Two-stage filter: function-name match, then body-hash similarity. Flags
CANON-MISS when a non-canonical file redefines what ``_hook_utils.py``
already exports.

Scope -- whose code is under scan (``probe_mode``):

    self-host  The harness SOURCE tree, or a fixture shaped like one: the
               engine package ``espalier/`` AND an unmarked
               ``tools/cc/hooks/`` tree are both present and no fusion
               marker is. Scans ``tools/cc/hooks/*.py`` + top-level
               ``espalier/*.py``; every arm gates. Unchanged from the
               probe's first version.
    adopter    Any tree whose ``tools/cc/hooks/`` are DEPLOYED copies (they
               carry the ``# espalier:managed`` line ``espalier init``
               writes), any fused tree (``.espalier-fusion``), or any tree
               missing the engine package or the hooks tree. The gating
               scan walks the adopter's own ``.py`` source -- the whole tree
               minus junk, tests, dot-directories, nested git repos, the
               harness's deploy zones and, on a fused tree, the whole harness
               overlay; narrow it with ``--roots``. The deployed hooks are
               scanned too, but reported under a separate HARNESS-INTERNAL
               heading that never gates: that debt is Espalier's, and
               write_guard keeps those files read-only for the adopter.
               Canon-miss and alias-miss are harness conventions and run
               only over harness files.

    The report always says what it scanned. ``scanned 0`` means the probe
    never looked, not that the code is clean.

CLI:
    python tools/cc/sister_site_probe.py [--root .] [--roots PATH ...]
                                          [--json] [--ignore PATTERN]
                                          [--include-info]
                                          [--accept-compression-debt REASON]

Exit codes:
    0 -- clean in the GATING scope (no canon-misses; no 3+ IDENTICAL
         cliques), OR debt acknowledged via
         ``--accept-compression-debt "<reason>"``. Harness-internal debt on
         an adopter tree never changes the exit code.
    1 -- script bug (uncaught exception), or a ``--roots`` path that does
         not exist or lies outside ``--root``
    2 -- compression debt in the gating scope (any canon-miss, or any 3+
         IDENTICAL clique). DIVERGENT cliques (same name, different bodies
         -- e.g. every hook's ``main``) are advisory only, and so are
         DELEGATING cliques (every site a one-line ``return <owner>(...)``
         naming the same owner -- the logic lives once already, in the
         owner).

Library API:
    probe_compression_debt(roots, threshold=1.0, scan_roots=None) -> ProbeReport
    probe_mode(root) -> MODE_SELF_HOST | MODE_ADOPTER
    report_has_debt(report) -> bool

The probe is a SIGNAL, not a guarantee. It misses copy-paste-then-rename
refactors and logic duplicates with structurally different shape. The
convention plus the gate compresses; the gate alone is not enough.

Pinned by a step in ``.claude/commands/implement-pack.md``.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple

from _json_safe import os_error_text


# Files that DEFINE canonicals — excluded from clique detection. Other files
# duplicating their content trigger CANON-MISS instead.
#
# ``_protected_zones.py`` is deliberately NOT in this set: it only exports
# ``_is_protected`` and ``_is_allowed``, and leaving it out makes those two
# private helpers first-class shadow-detectable canonicals — if a future hook
# shadows either, the probe catches it via body-hash canon-miss.
#
# ``espalier/_archive_safety.py`` is the canonical source for
# ``safe_extract_tar`` / ``safe_extract_zip``. Future modules exporting
# ``safe_*`` helpers should be added here too so consumers don't silently
# re-implement the wrappers. The convention is "list explicitly" rather than
# dynamic-discover so the canonical set is stable, scrutable, and grep-able.
CANONICAL_FILES: frozenset[str] = frozenset({
    "tools/cc/hooks/_hook_utils.py",
    "espalier/_archive_safety.py",
})

# Default ignore patterns (regex applied to forward-slash relative path).
# Empty today: scope-out files (``espalier/scanners/``, ``espalier/assets/``)
# are already excluded by the default scan targets. Override via ``--ignore``.
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = ()

# Per-function opt-out marker, placed on its own line directly above ``def``
# (blank lines between marker and def are tolerated).
OPT_OUT_RE = re.compile(r"^\s*#\s*sister-site:\s*ok(?:\s+(.+))?\s*$")

# Concept-overlap detector (advisory): flag two str-element collections with
# DIFFERENT names whose elements overlap heavily. This is the divergent-name /
# divergent-value class the name-clique and value-hash detectors both miss.
# Uses CONTAINMENT (|A intersect B| / min(|A|, |B|)), not Jaccard, so a narrow set
# that is a near-subset of a wide one (the derive-from-core signal) is caught.
# Advisory-only (excluded from has_debt), heavily floored to stay quiet, and
# acknowledged via the `# sister-site: ok` marker like any other opt-out.
_CONCEPT_OVERLAP_K = 0.6           # containment threshold (fraction of the smaller set)
_CONCEPT_OVERLAP_MIN_SIZE = 4      # a candidate set must have >= this many str elements
_CONCEPT_OVERLAP_MIN_OVERLAP = 4   # absolute shared-element floor

# Builtin names, derived rather than hand-listed (a literal tuple here would be
# the enumeration-integrity defect this repo tracks as its own class). Used to
# refuse "delegation" status to a clique of one-line builtin wrappers -- see
# `_clique_delegation`. A repo function deliberately shadowing a builtin name
# is rare, and the failure direction is the safe one: the clique keeps gating.
_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins))

# ── Scope: whose code is under scan? ─────────────────────────────────────────
#
# ``espalier init`` writes every ``.py`` it deploys under ``tools/cc/`` with an
# anchored ``# espalier:managed`` comment line near the top
# (``espalier.managed_markers.apply_marker_to_text``); the harness's own SOURCE
# files never carry one, and neither does the byte-mirror at
# ``espalier/_vendor/cc/``. So the marker answers the one question this probe's
# scope turns on -- "are the hooks under ``tools/cc/hooks/`` deployed copies?"
# -- without borrowing the 5-signal self-host detector, whose fifth signal (a
# content-hash pin on write_guard.py) guards a PRIVILEGE fork this reporting
# fork does not have: a spoofed self-host layout gains nothing here but a
# stricter probe. Inline mirror of ``managed_markers._MARKER_LINE_RE`` and
# ``MARKER_SCAN_BYTES`` (tools/cc has zero espalier imports); parity is pinned
# by tests/test_sister_site_probe_unit.py::TestProbeMode.
_MANAGED_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?:#|<!--|::)[ \t]*espalier:managed\b",
    re.ASCII,
)
_MANAGED_MARKER_SCAN_CHARS = 600

MODE_SELF_HOST = "self-host"
MODE_ADOPTER = "adopter"

# Adopter-mode walk: directory NAMES pruned at any depth. Junk that is never
# source, plus ``tests``/``test`` -- test modules legitimately repeat small
# same-named helpers across files, which would read as a 3+ identical clique
# on an adopter's very first run; opt them in with ``--roots tests``. Any
# directory whose name starts with ``.`` is pruned too (``.git``, ``.venv``,
# ``.tox``, and the harness's own ``.claude`` / ``.espalier``). A pruned
# directory named on ``--roots`` is walked: pruning applies below a start.
_ADOPTER_PRUNE_NAMES: frozenset[str] = frozenset({
    "__pycache__", "venv", "env", "node_modules", "site-packages",
    "build", "dist", "_vendor", "vendor", "vendored", "third_party",
    "tests", "test",
})
# Adopter-mode walk: repo-relative directory PATHS pruned -- the harness's own
# deploy zones, never the adopter's source. ``tools/cc`` is scanned separately
# as the harness-internal scope.
_ADOPTER_PRUNE_PATHS: frozenset[str] = frozenset({"tools/cc", "cc"})

# Fused trees (``espalier fuse``): the harness is OVERLAID into the host --
# ``fusion_manifest.HARNESS_INCLUDE`` copies the whole engine package, the
# whole ``tools/`` tree, the bench and two scripts as UNMARKED byte copies --
# and writes the tracked ``.espalier-fusion`` marker at the root. That overlay
# is Espalier's, never the adopter's source, so the adopter walk prunes it
# wherever the marker is present. Inline mirror of the manifest's .py-bearing
# entries (tools/cc has zero espalier imports); parity with
# ``fusion_manifest.HARNESS_INCLUDE`` is pinned by
# tests/test_sister_site_probe_unit.py::TestFusedOverlay, and the whole
# overlay is driven by a real ``fuse`` in
# tests/test_sister_site_probe_adopter_tree.py. Measured before this existed:
# 97 of the 98 files a fused tree's first cut called "your source" were
# Espalier's, and three of them gated.
_FUSION_MARKER_FILE = ".espalier-fusion"
# Whole-tree manifest entries that are the engine itself.
_FUSED_OVERLAY_DIRS: frozenset[str] = frozenset({"espalier"})
# Manifest entries below a directory the host may ALSO own: pruned at the
# manifest's own granularity, never wholesale -- a host's ``bench/hb.py`` or
# ``tools/host.py`` sits beside the overlay and stays in the gating scope
# (failure-mode pass, round two: a wholesale ``bench/`` prune hid two of the
# host's own 3-site cliques under a label calling them Espalier's).
# Recorded limit: a host file INSIDE one of these sub-directories (a host that
# already had its own ``bench/corpus/``, which ``fuse`` merges into) is pruned
# with the overlay and labelled as Espalier's. Visible in ``pruned`` and
# recoverable with ``--roots bench/corpus``; the alternative -- pruning by
# file identity against a manifest the probe cannot import -- is not worth
# its weight for a shape ``fuse`` warns about at plan time.
_FUSED_OVERLAY_PATHS: frozenset[str] = frozenset({
    "bench/corpus", "bench/baselines", "bench/end_to_end",
})
_FUSED_OVERLAY_FILES: frozenset[str] = frozenset({
    "bench/run_benchmark.py",
    "scripts/check_exception_policy.py",
    "scripts/check_memory_md_tag_parity.py",
    # ``tools/`` is a whole-tree manifest entry; ``tools/cc`` is already a
    # deploy-zone prune, and these are the only other .py the tree holds
    # (the parity test derives this pair from the live ``tools/*.py``).
    "tools/__init__.py",
    "tools/review_agent_audit.py",
})
# A vendored engine package is recognisable without the fusion marker too
# (a hand-vendored copy): two engine modules an adopter package of the same
# name has no reason to carry. Pinned to the live package by the same test.
_ENGINE_SIGNATURE: tuple[str, ...] = ("espalier/cli.py", "espalier/managed_markers.py")

# Mirror of the default-ignorable prefix strip in
# ``managed_markers.has_managed_marker``: a leading run of Format / Control /
# Surrogate / Unassigned / line- and paragraph-separator codepoints (BOM,
# ZWSP, ZWJ, LRM, NUL, ...) would otherwise displace the regex's ``^`` anchor
# and read a marked hook as unmarked. PREFIX-STRIP parity with the engine is
# pinned behaviourally by TestProbeMode::test_marker_prefix_normalisation_matches_the_engine;
# the engine's YAML-frontmatter window widening is deliberately NOT mirrored
# (the glob is ``*.py`` and ``---`` is not valid Python), and the same test
# records that divergence as asserted, not accidental.
_MARKER_IGNORABLE_CATEGORIES: frozenset[str] = frozenset({"Cf", "Cc", "Cs", "Cn", "Zl", "Zp"})


class FunctionSite(NamedTuple):
    name: str
    file: str          # rel path from root, forward-slashes
    lineno: int
    body_hash: str
    opt_out_reason: str | None
    # Callee name when the body is a pure forwarding alias (see
    # `_forwarding_target`), else None. Computed during the AST walk that
    # already visits this node so the clique pass does not re-parse to ask.
    delegation_target: str | None = None
    # True when `delegation_target` is bound by a module-level IMPORT in this
    # site's own file and not shadowed by a local def. The clique exclusion
    # requires it: a locally-defined target is a per-file owner, not a shared
    # one. Defaulted False so a construction path that forgets it keeps gating.
    delegation_target_imported: bool = False


class Clique(NamedTuple):
    name: str
    sites: tuple[FunctionSite, ...]
    severity: str      # "WARN" (3+ sites) | "INFO" (2 sites)
    divergent: bool    # True when site bodies do not all share one hash
    # True when EVERY site is a one-line `return <owner>(...)` naming the same
    # owner, which is not this clique's own name. Such sites are the RESULT of
    # compression -- the logic lives once, in the owner -- so they are reported
    # but excluded from the gate. Defaulted so existing positional construction
    # (tests, callers) keeps working.
    delegating: bool = False


class CanonMiss(NamedTuple):
    canonical_name: str
    canonical_file: str
    shadow_name: str
    shadow_file: str
    shadow_lineno: int
    shape: str         # "body-match" | "alias-call"


class AliasMiss(NamedTuple):
    """A module-level rename shim whose local name diverges from the name of
    the thing it aliases (basename, stripped of leading underscores).
    Prefix-underscore renames (``_X = M.X`` / ``import X as _X``) are the
    legitimate "rename-for-private" convention and are skipped.

    Three spellings of the identical shim are covered:
    - ``shape="assign"``      — ``LHS = Module.Attr``
    - ``shape="import-from"`` — ``from Module import Attr as LHS``
    - ``shape="import"``      — ``import Module as LHS``
    """
    lhs_name: str
    rhs_module: str
    rhs_attr: str
    file: str
    lineno: int
    shape: str = "assign"


class ConstantSite(NamedTuple):
    name: str          # constant name (e.g. "MUTATION_TOOLS")
    file: str
    lineno: int
    value_hash: str    # sha256 of ast.dump of the RHS expression
    # str elements if the RHS is a str-homogeneous set/list/tuple literal (or a
    # set/frozenset/tuple/list(<literal>) call), else None. Feeds the concept-
    # overlap detector; None disqualifies the site from element-wise comparison.
    str_elems: frozenset[str] | None = None


class ConstantClique(NamedTuple):
    name: str          # shared constant name
    sites: tuple[ConstantSite, ...]
    severity: str      # "WARN" (3+ sites) | "INFO" (2 sites)
    divergent: bool    # True when sites share a name but not all the same hash


class ConceptOverlap(NamedTuple):
    members: tuple[ConstantSite, ...]  # cluster sites (>= 2, spanning >= 2 names)
    shared: tuple[str, ...]            # normalized tokens common to every member


class ProbeScope(NamedTuple):
    """What the probe looked at -- so a clean exit can be read for what it is."""
    mode: str                         # MODE_SELF_HOST | MODE_ADOPTER
    roots: tuple[str, ...]            # gating-scope roots, repo-relative ("." = the tree)
    scanned: tuple[str, ...]          # gating-scope .py files actually analysed
    pruned: tuple[str, ...]           # directories the adopter walk skipped
    harness_files: tuple[str, ...]    # harness-internal (advisory) files; adopter mode only
    explicit_roots: bool              # True when --roots / scan_roots narrowed the scope


class ProbeReport(NamedTuple):
    cliques: tuple[Clique, ...]
    canon_misses: tuple[CanonMiss, ...]
    alias_misses: tuple[AliasMiss, ...] = ()
    constant_cliques: tuple[ConstantClique, ...] = ()
    concept_overlaps: tuple[ConceptOverlap, ...] = ()
    # Whose code was scanned, and what exactly. None only for a report built
    # by hand (tests) without going through ``probe_compression_debt``.
    scope: ProbeScope | None = None
    # Adopter mode only: the same analysis over the DEPLOYED hooks under
    # ``tools/cc/hooks/``, reported but never gating -- that debt is
    # Espalier's, and write_guard keeps those files read-only for the adopter.
    harness_internal: ProbeReport | None = None


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Drop a leading docstring statement, if present.

    Every question this module asks about a body -- what does it hash to, does
    it delegate -- is a question about its LOGIC, and a docstring is not logic.
    Asking it in one place is load-bearing: when the delegation check carried
    its own copy of this and the hash did not, five sites that were all
    ``return load_report_json(path)`` hashed identical while only the four
    WITHOUT a docstring read as delegating, so the clique kept gating.
    """
    stmts = list(body)
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        return stmts[1:]
    return stmts


def _hash_body(body: list[ast.stmt]) -> str:
    """SHA-256 over a normalized AST dump of the function body.

    ``annotate_fields=False, include_attributes=False`` excludes line/column
    metadata so formatting whitespace doesn't change the hash; semantic
    differences (different statements, identifiers, call shapes) do.

    A leading docstring is stripped first. ``ast.dump`` includes
    the docstring ``Expr(Constant(str))`` node, so without this two
    logic-identical functions that differ ONLY in their docstring would hash
    DIVERGENT — a false-negative that lets a real duplicate escape the
    clique check. Docstrings are excluded like comments/whitespace already are.
    """
    stmts = _strip_docstring(body)
    parts = [
        ast.dump(n, annotate_fields=False, include_attributes=False)
        for n in stmts
    ]
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _read_source(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _opt_out_marker_above(source_lines: list[str], func_lineno: int) -> str | None:
    """Return the opt-out reason if a marker comment sits above ``def``.

    Walks backward from the line above the def, skipping blank lines; the
    nearest non-blank line must match ``OPT_OUT_RE`` for the function to be
    opted out. Decorators count as non-blank and break the search (a marker
    above the decorator does not apply).
    """
    idx = func_lineno - 2  # `lineno` is 1-based; -1 for the def line, -1 for above
    while idx >= 0 and source_lines[idx].strip() == "":
        idx -= 1
    if idx < 0:
        return None
    m = OPT_OUT_RE.match(source_lines[idx])
    if m:
        return (m.group(1) or "").strip() or "<no reason given>"
    return None


def _is_passthrough_arg(node: ast.expr) -> bool:
    """True iff an argument carries no logic of its own.

    A bare name or a literal is forwarded; anything else -- a comprehension, a
    call, a binop, a lambda -- is LOGIC that happens to sit inside the call
    parentheses. Without this, ``return _weighted({...comprehension...},
    base=sum(...), cap=X - len(y) % 7)`` reads as "holds no logic of its own",
    and five byte-identical copies of it were measured escaping the gate.
    """
    return isinstance(node, (ast.Name, ast.Constant))


def _forwarding_target(node: ast.FunctionDef) -> str | None:
    """Return the callee name iff ``node`` is a pure forwarding alias.

    The shape is ``return <name>(<pass-through args>)`` -- a body that holds no
    logic, only a local name for something defined elsewhere. Both the
    canon-miss detector (does this alias a KNOWN canonical?) and the clique
    detector (do these N sites share ONE owner?) ask this same question, so it
    is asked in one place.

    Three conditions beyond the call shape, each of which was measured letting
    real duplication through when it was absent:

    - **every argument is pass-through** -- otherwise arbitrary logic rides
      along inside the parentheses (see ``_is_passthrough_arg``);
    - **no ``*``/``**`` unpacking of an expression** -- same hole, different
      spelling;
    - **the callee is not one of this function's own parameters** -- ``def
      _apply(fn, x): return fn(x)`` names no owner at all, and three identical
      copies of it exited 0.

    Returns ``None`` for a call through an attribute (``return mod.f(x)``):
    that names a module-qualified owner rather than a bare local name, and the
    alias-miss detector already owns that shape.
    """
    stmts = _strip_docstring(node.body)
    if len(stmts) != 1:
        return None
    stmt = stmts[0]
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return None
    call = stmt.value
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if not isinstance(func, ast.Name):
        return None
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            if not _is_passthrough_arg(arg.value):
                return None
        elif not _is_passthrough_arg(arg):
            return None
    for kw in call.keywords:
        if not _is_passthrough_arg(kw.value):
            return None
    if func.id in _own_parameter_names(node):
        return None
    return func.id


def _own_parameter_names(node: ast.FunctionDef) -> frozenset[str]:
    """Every parameter name bound by ``node``'s own signature."""
    a = node.args
    names = [
        p.arg
        for p in (*a.posonlyargs, *a.args, *a.kwonlyargs)
    ]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return frozenset(names)


def _module_import_names(tree: ast.Module) -> frozenset[str]:
    """Names bound by a module-level import.

    The clique exclusion rests on the duplication having MOVED to a shared
    owner. That is only true when the target names something the module
    IMPORTED; a target bound by a local ``def`` is a per-file owner, and three
    files forwarding to three DIFFERENT local ``_impl``s were measured exiting
    0 while the probe simultaneously reported those ``_impl``s as divergent.
    """
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
    return frozenset(out)


def _module_local_defs(tree: ast.Module) -> frozenset[str]:
    """Names bound by a module-level ``def``/``class``/assignment."""
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return frozenset(out)


def _is_one_line_call(node: ast.FunctionDef, target_name: str) -> bool:
    """True iff ``node`` is a pure forwarding alias to ``target_name``.

    Shares ``_forwarding_target``'s strictness deliberately. An ADAPTER that
    binds arguments (``return read_text_nofollow(root / "x", within=root)``)
    is not an alias, and telling a contributor to replace it with one produces
    a bug -- the deny message's suggested `_x = _hook_utils.x` drops the
    binding.
    """
    return _forwarding_target(node) == target_name


def _clique_delegation(sites: list[FunctionSite], name: str) -> bool:
    """True iff every site delegates to one shared owner that is not ``name``.

    Requiring a SINGLE shared target is what keeps this narrow: N sites that
    each forward to a DIFFERENT function are not one compressed helper, they
    are N helpers that happen to be one line long. Excluding the clique's own
    name keeps a self-call (``def _f(x): return _f(x)``) out -- it names no
    owner and compresses nothing.
    """
    targets = {s.delegation_target for s in sites}
    if len(targets) != 1:
        return False
    target = next(iter(targets))
    if target is None or target == name:
        return False
    # Every site must IMPORT the target. A locally-defined target is a per-file
    # owner: three files forwarding to three different local `_impl`s were
    # measured exiting 0 while the report simultaneously printed those `_impl`s
    # as DIVERGENT -- the probe contradicting itself in one frame.
    if not all(s.delegation_target_imported for s in sites):
        return False
    # A BUILTIN target is not a shared owner. The exclusion rests on the
    # duplication having MOVED to the target -- which the clique pass then
    # examines on its own merits, so `return _helper(x)` x3 stays gated via the
    # `_helper` clique. A builtin has no such clique to catch it, so
    # `def _norm(x): return dict(x)` x3 would escape entirely: the wrapper IS
    # the duplicated thing. Measured, not reasoned -- that case exited 0 before
    # this guard.
    return target not in _BUILTIN_NAMES


def _strip_default_ignorable(text: str) -> str:
    """Drop a leading run of default-ignorable codepoints (see
    ``_MARKER_IGNORABLE_CATEGORIES``) so the anchored marker regex sees the
    same first line ``managed_markers.has_managed_marker`` does."""
    i = 0
    while i < len(text) and unicodedata.category(text[i]) in _MARKER_IGNORABLE_CATEGORIES:
        i += 1
    return text[i:] if i else text


def _hooks_are_deployed_copies(root: Path) -> bool:
    """True when any ``tools/cc/hooks/*.py`` carries the managed marker."""
    hooks_dir = root / "tools" / "cc" / "hooks"
    if not hooks_dir.is_dir():
        return False
    for p in sorted(hooks_dir.glob("*.py")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Strip FIRST, then window -- the engine's order. Windowing first
        # shortened the search by the prefix's length, so a marker the engine
        # finds just inside its 600 chars fell outside ours (code-reviewer,
        # round two, reproduced with a 20-codepoint prefix). A hook file is
        # tens of KB at most, so reading it whole costs nothing measurable.
        head = _strip_default_ignorable(text)[:_MANAGED_MARKER_SCAN_CHARS]
        if _MANAGED_MARKER_RE.search(head):
            return True
    return False


def probe_mode(root: Path) -> str:
    """Whose code is under scan at ``root``: ``MODE_SELF_HOST`` or ``MODE_ADOPTER``.

    ======================================  ===========  ====================
    tree shape                              mode         gating scope
    ======================================  ===========  ====================
    ``tools/cc/hooks/`` carries the         adopter      adopter source (tree
    managed marker (``init`` / ``upgrade``               walk, or ``--roots``)
    / ``fuse`` wrote it)
    the tracked ``.espalier-fusion``        adopter      adopter source; the
    marker is at the root (``fuse``, even                overlay is pruned
    ``--no-init``: unmarked hook copies)
    no marker; the engine package           self-host    hooks + top-level
    ``espalier/`` AND an unmarked                        engine, unchanged
    ``tools/cc/hooks/`` tree are both here
    (the harness source tree, or a fixture
    shaped like it)
    anything else                           adopter      adopter source
    ======================================  ===========  ====================

    Two markers decide first: deployed hooks are marked, and a fused tree is
    marked even when ``fuse --no-init`` copied the hooks unmarked. After
    that, the SOURCE tree is the one that has BOTH the engine package and a
    hooks tree -- a vendored engine with no hooks (an offline copy, or
    ``install-ci`` alone, which deploys no hook) is an adopter's, and
    reading it as self-host would scan the engine copy as theirs and never
    their code (failure-mode pass, round two). The engine test is the bare
    directory, weaker than the two-module ``_ENGINE_SIGNATURE`` the walk
    uses to PRUNE a vendored copy: a false positive here needs an unmarked
    hooks tree beside it, whereas the walk's prune would hide an adopter's
    own package of that name and so needs the stronger signature. A fixture
    that forgets either directory lands in adopter mode and fails LOUD (its
    hook findings move to ``harness_internal``), never green.
    """
    if _hooks_are_deployed_copies(root):
        return MODE_ADOPTER
    if (root / _FUSION_MARKER_FILE).is_file():
        return MODE_ADOPTER
    if (root / "espalier").is_dir() and (root / "tools" / "cc" / "hooks").is_dir():
        return MODE_SELF_HOST
    return MODE_ADOPTER

def _rel_label(path: Path, root: Path) -> str:
    """Repo-relative posix label for ``path``; ``.`` for the root itself."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()
    return rel or "."


def _same_file(a: Path, b: Path) -> bool:
    """True when ``a`` and ``b`` are one directory entry on disk -- identity,
    not spelling. On a case-insensitive filesystem an adopter's existing
    ``Tools/`` IS the parent ``init`` wrote ``tools/cc`` into, and a spelling
    compare missed it (failure-mode pass, round two: 38 of 39 gating files
    were Espalier's). On a case-sensitive one ``Tools/`` and ``tools/`` are
    two entries and neither is mistaken for the other. False when either is
    absent."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _harness_zones(root: Path) -> list[tuple[Path, str]]:
    """Every path the adopter walk must skip because it is the harness's,
    as ``(path, reason)`` pairs; only paths that exist are returned.

    - the deploy zones (``tools/cc``, ``cc``) on every tree;
    - on a fused tree (``.espalier-fusion`` present): the engine package, the
      manifest's ``bench/`` sub-entries and its handful of files, each at its
      own granularity so the host's neighbours under ``bench/`` / ``tools/``
      stay in scope;
    - otherwise, a vendored engine recognised by ``_ENGINE_SIGNATURE``.
    """
    zones: list[tuple[Path, str]] = [(root / rel, "") for rel in sorted(_ADOPTER_PRUNE_PATHS)]
    if (root / _FUSION_MARKER_FILE).is_file():
        for rel in sorted(_FUSED_OVERLAY_DIRS | _FUSED_OVERLAY_PATHS | _FUSED_OVERLAY_FILES):
            zones.append((root / rel, " (fused harness overlay)"))
    elif all((root / rel).is_file() for rel in _ENGINE_SIGNATURE):
        zones.append((root / "espalier", " (vendored engine)"))
    return [(p, why) for p, why in zones if p.exists()]


def _walk_python_sources(start: Path, root: Path) -> tuple[list[Path], list[str]]:
    """Every ``.py`` under ``start`` (or ``start`` itself when it is a file),
    pruning junk, tests, dot-directories, nested git repos and the harness's
    own zones (``_harness_zones``).

    ``os.walk(followlinks=False)`` never descends a symlinked directory and
    symlinked files are skipped, so the walk cannot leave the tree or loop.
    A directory holding a ``.git`` (dir, worktree/submodule file, or a
    dangling symlink to one) is a foreign project, never part of this
    tree's surface -- ``espalier/_safe_walk.py::has_git_entry``'s rule,
    re-derived here because this script cannot import it. Name prunes are
    case-insensitive (``Tests/`` is ``tests/``); zone prunes are matched by
    on-disk identity (``_same_file``), so the spelling the walk meets never
    matters. Returns ``(files, pruned)``; ``pruned`` holds repo-relative
    labels, each with its reason when the reason is not the name itself, so
    the report can say what it did NOT look at.
    """
    if start.is_file():
        return ([start] if start.suffix == ".py" else []), []
    zones = _harness_zones(root)
    files: list[Path] = []
    pruned: list[str] = []
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        base = Path(dirpath)
        keep: list[str] = []
        for d in sorted(dirnames):
            here = base / d
            rel = _rel_label(here, root)
            low = d.lower()
            why: str | None = None
            if d.startswith(".") or low in _ADOPTER_PRUNE_NAMES or low.endswith(".egg-info"):
                why = ""
            else:
                for zone, zone_why in zones:
                    if _same_file(here, zone):
                        why = zone_why
                        break
            if why is None and ((here / ".git").exists() or (here / ".git").is_symlink()):
                why = " (nested repo)"
            if why is None:
                keep.append(d)
            else:
                pruned.append(rel + "/" + why)
        dirnames[:] = keep
        for f in sorted(filenames):
            p = base / f
            if p.suffix != ".py" or p.is_symlink():
                continue
            skip = next((zone_why for zone, zone_why in zones if _same_file(p, zone)), None)
            if skip is not None:
                pruned.append(_rel_label(p, root) + skip)
                continue
            files.append(p)
    return files, pruned

def _self_host_scan_targets(root: Path) -> list[Path]:
    """Self-host gating scope, unchanged since the probe's first version.

    - ``tools/cc/hooks/*.py`` (excludes ``CANONICAL_FILES``)
    - ``espalier/*.py`` top-level only (excludes ``espalier/scanners/`` and
      ``espalier/assets/`` per pack scope-out -- scanners have legitimately
      parallel ``_classify`` shapes; assets are templated, not runtime).
    """
    targets: list[Path] = []
    hooks_dir = root / "tools" / "cc" / "hooks"
    if hooks_dir.is_dir():
        for p in sorted(hooks_dir.glob("*.py")):
            rel = p.relative_to(root).as_posix()
            if rel in CANONICAL_FILES:
                continue
            targets.append(p)
    espalier_dir = root / "espalier"
    if espalier_dir.is_dir():
        for p in sorted(espalier_dir.glob("*.py")):
            rel = p.relative_to(root).as_posix()
            if rel in CANONICAL_FILES:
                # A canonical source; skip it from regular-site clique
                # detection (its content is checked via canon-miss instead).
                continue
            targets.append(p)
    return targets


def _adopter_scan_targets(
    root: Path, scan_roots: tuple[Path, ...] | None,
) -> tuple[list[Path], tuple[str, ...], tuple[str, ...]]:
    """Adopter gating scope: walk ``scan_roots`` (default: the whole tree).

    Returns ``(files, root_labels, pruned)``. ``CANONICAL_FILES`` are dropped
    so an explicit ``--roots tools/cc/hooks`` on a self-host tree keeps the
    canon-miss arm honest.
    """
    starts = tuple(scan_roots) if scan_roots else (root,)
    canon = [root / rel for rel in sorted(CANONICAL_FILES) if (root / rel).is_file()]
    files: list[Path] = []
    pruned: list[str] = []
    seen: set[Path] = set()
    for start in starts:
        walked, walked_pruned = _walk_python_sources(start, root)
        for p in walked:
            if p in seen:
                continue
            seen.add(p)
            if any(_same_file(p, c) for c in canon):
                continue
            files.append(p)
        pruned.extend(walked_pruned)
    labels = tuple(
        _rel_label(s, root) + ("/" if s.is_dir() and _rel_label(s, root) != "." else "")
        for s in starts
    )
    return files, labels, tuple(dict.fromkeys(pruned))


def _default_scan_targets(
    root: Path, scan_roots: tuple[Path, ...] | None = None,
) -> list[Path]:
    """Files in the GATING scope for ``root`` (see ``probe_mode``).

    Self-host without ``scan_roots``: ``_self_host_scan_targets``. Any other
    combination walks ``scan_roots`` (default: the whole tree, adopter mode).
    """
    if scan_roots is None and probe_mode(root) == MODE_SELF_HOST:
        return _self_host_scan_targets(root)
    return _adopter_scan_targets(root, scan_roots)[0]


def _harness_internal_targets(root: Path) -> list[Path]:
    """The deployed hooks on an adopter tree: ``tools/cc/hooks/*.py`` minus
    ``CANONICAL_FILES`` -- the same slice the self-host scan takes of them."""
    hooks_dir = root / "tools" / "cc" / "hooks"
    if not hooks_dir.is_dir():
        return []
    canon = [root / rel for rel in sorted(CANONICAL_FILES) if (root / rel).is_file()]
    return [
        p for p in sorted(hooks_dir.glob("*.py"))
        if not any(_same_file(p, c) for c in canon)
    ]


def _canonical_targets(root: Path) -> list[Path]:
    out: list[Path] = []
    for rel in sorted(CANONICAL_FILES):
        p = root / rel
        if p.is_file():
            out.append(p)
    return out


def _collect_sites(path: Path, root: Path) -> list[FunctionSite]:
    """Collect FunctionSite entries for top-level and class-method defs.

    Module-level FunctionDef keeps its bare ``name``. Methods inside a
    ClassDef are qualified as ``ClassName.method_name`` so cross-class
    same-method-name duplication can be detected without same-class
    aliasing (each method in a single class has a unique qualified
    name). Dunder methods (``__init__``, ``__repr__``, etc.) are skipped
    to avoid noise from the universal ``__init__`` pattern.
    """
    src = _read_source(path)
    if src is None:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    rel = path.relative_to(root).as_posix()
    imported = _module_import_names(tree)
    local_defs = _module_local_defs(tree)

    def _target_of(fn: ast.FunctionDef) -> tuple[str | None, bool]:
        t = _forwarding_target(fn)
        return t, bool(t is not None and t in imported and t not in local_defs)

    sites: list[FunctionSite] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            sites.append(FunctionSite(
                name=node.name,
                file=rel,
                lineno=node.lineno,
                body_hash=_hash_body(node.body),
                opt_out_reason=_opt_out_marker_above(lines, node.lineno),
                delegation_target=_target_of(node)[0],
                delegation_target_imported=_target_of(node)[1],
            ))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if not isinstance(sub, ast.FunctionDef):
                    continue
                if sub.name.startswith("__"):
                    continue
                sites.append(FunctionSite(
                    name=f"{node.name}.{sub.name}",
                    file=rel,
                    lineno=sub.lineno,
                    body_hash=_hash_body(sub.body),
                    opt_out_reason=_opt_out_marker_above(lines, sub.lineno),
                    delegation_target=_target_of(sub)[0],
                    delegation_target_imported=_target_of(sub)[1],
                ))
    return sites


def _collect_canonical_names(root: Path) -> dict[str, tuple[str, str]]:
    """Map canonical FunctionDef name -> (rel-file, body-hash).

    Only top-level FunctionDefs without a dunder prefix are considered
    canonical surface. Private (single-underscore) names are included
    because hooks may shadow private helpers too.
    """
    canon: dict[str, tuple[str, str]] = {}
    for path in _canonical_targets(root):
        src = _read_source(path)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = path.relative_to(root).as_posix()
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name.startswith("__"):
                continue
            canon[node.name] = (rel, _hash_body(node.body))
    return canon


_MIN_CONSTANT_STRING_LEN = 20


def _string_elements(value: ast.expr) -> frozenset[str] | None:
    """Return the frozenset of str elements of a str-HOMOGENEOUS literal
    collection, or None if the node is not such a collection.

    Accepts ``{...}`` / ``[...]`` / ``(...)`` literals and the
    ``set/frozenset/tuple/list(<literal>)`` call forms. ANY non-str (or
    non-constant) element, a dict, or an empty collection returns None so a mixed
    or dynamic collection is never compared element-wise. A set DERIVED via a
    comprehension (``{e[1:] for e in CANON}``) is an ``ast.SetComp``, not a
    literal, so it returns None — the detector self-silences once a duplicate is
    fixed by deriving from the canon.
    """
    node = value
    if isinstance(node, ast.Call):
        if not (
            isinstance(node.func, ast.Name)
            and node.func.id in {"set", "frozenset", "tuple", "list"}
        ):
            return None
        if len(node.args) != 1:
            return None
        node = node.args[0]
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return None
    elems: set[str] = set()
    for e in node.elts:
        if not (isinstance(e, ast.Constant) and isinstance(e.value, str)):
            return None
        elems.add(e.value)
    return frozenset(elems) if elems else None


def _normalize_overlap_token(token: str) -> str:
    """Fold ``.py`` and ``py`` to the same token (drop a single leading dot),
    case-insensitively, so an extension set written with dots overlaps one
    written without."""
    return (token[1:] if token.startswith(".") else token).casefold()


def _is_interesting_constant(value: ast.expr) -> bool:
    """Return True if RHS is a literal collection or long string worth
    tracking. Short scalars (``MAX_RETRIES = 3``, ``_DEBUG = False``)
    are skipped to avoid noise.
    """
    if isinstance(value, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
        return True
    if isinstance(value, ast.Constant):
        return (
            isinstance(value.value, str)
            and len(value.value) >= _MIN_CONSTANT_STRING_LEN
        )
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name) and value.func.id in {
            "set", "frozenset", "tuple", "list", "dict",
        }:
            return True
    return False


def _collect_constant_sites(path: Path, root: Path) -> list[ConstantSite]:
    """Collect module-level constant assignments worth tracking.

    Handles both ``ast.Assign`` (``X = {...}``) and ``ast.AnnAssign``
    (``X: frozenset[str] = frozenset({...})``). Hash is taken over the
    AST dump of the RHS expression (annotate_fields=False) so equality
    is structural, not source-formatting-sensitive. The opt-out marker
    above the assignment suppresses collection.
    """
    src = _read_source(path)
    if src is None:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    rel = path.relative_to(root).as_posix()
    sites: list[ConstantSite] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if _opt_out_marker_above(lines, node.lineno) is not None:
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(
                node.targets[0], ast.Name
            ):
                continue
            name = node.targets[0].id
            value = node.value
        else:  # ast.AnnAssign
            if not isinstance(node.target, ast.Name) or node.value is None:
                continue
            name = node.target.id
            value = node.value
        if not _is_interesting_constant(value):
            continue
        value_hash = hashlib.sha256(
            ast.dump(value, annotate_fields=False,
                     include_attributes=False).encode("utf-8")
        ).hexdigest()
        sites.append(ConstantSite(
            name=name,
            file=rel,
            lineno=node.lineno,
            value_hash=value_hash,
            str_elems=_string_elements(value),
        ))
    return sites


def _build_concept_overlaps(sites: list[ConstantSite]) -> list[ConceptOverlap]:
    """Cluster constant sites whose str-element sets overlap heavily under
    DIFFERENT names (same-name overlaps are already ``constant_cliques``).

    Metric is CONTAINMENT (|A intersect B| / min(|A|, |B|)), not Jaccard, so a
    narrow set that is a near-subset of a wide one — the derive-from-core signal —
    is caught even where Jaccard would miss it. Five stacked floors keep the rule
    quiet: str-homogeneous-only, MIN_SIZE, MIN_OVERLAP (absolute), K (containment),
    and different-name-only. Clusters are connected components over the qualifying
    edges; a cluster must span >= 2 distinct names to be reported.
    """
    candidates = [
        s for s in sites
        if s.str_elems is not None
        and len(s.str_elems) >= _CONCEPT_OVERLAP_MIN_SIZE
    ]
    norm = [
        frozenset(_normalize_overlap_token(t) for t in s.str_elems)
        for s in candidates
    ]
    n = len(candidates)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if candidates[i].name == candidates[j].name:
                continue  # same name -> constant_cliques' domain
            inter = norm[i] & norm[j]
            if len(inter) < _CONCEPT_OVERLAP_MIN_OVERLAP:
                continue
            if len(inter) / min(len(norm[i]), len(norm[j])) < _CONCEPT_OVERLAP_K:
                continue
            parent[find(i)] = find(j)

    comps: dict[int, list[int]] = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)

    overlaps: list[ConceptOverlap] = []
    for idxs in comps.values():
        if len(idxs) < 2:
            continue
        member_sites = [candidates[i] for i in idxs]
        if len({s.name for s in member_sites}) < 2:
            continue
        # A reported cluster must have a shared CORE across ALL members, not just
        # transitive pairwise edges — connected components can chain A-B-C where
        # A and C barely overlap, yielding a coreless blob that is not a
        # derive-from-core candidate. Require the global intersection to clear the
        # same absolute floor a single edge does.
        shared = frozenset.intersection(*(norm[i] for i in idxs))
        if len(shared) < _CONCEPT_OVERLAP_MIN_OVERLAP:
            continue
        overlaps.append(ConceptOverlap(
            members=tuple(sorted(member_sites, key=lambda s: (s.file, s.lineno))),
            shared=tuple(sorted(shared)),
        ))
    return sorted(overlaps, key=lambda o: (o.members[0].file, o.members[0].lineno))


def _collect_alias_misses(path: Path, root: Path) -> list[AliasMiss]:
    """Detect module-level rename shims whose local name diverges from the
    aliased target's name (not just a leading-underscore prefix rename),
    across all three spellings of the shim:

    - ``LHS = Module.Attr``             (assignment)
    - ``from Module import Attr as LHS`` (import-from)
    - ``import Module as LHS``           (import)

    Skips (all spellings):
    - Targets that aren't a single ``Name`` (tuple / attribute assign targets).
    - RHS that isn't ``Module.Attr`` shape (assignment); imports without an
      ``as`` rename (``import stat``, ``from M import x``); ``from M import *``.
    - Local basename equal to the target basename after ``lstrip("_")`` on BOTH
      sides (``_X = M.X`` / ``import X as _X`` — rename-for-private). The
      symmetric strip makes ``_REDIRECT_RE = _bash_patterns._REDIRECT_RE`` the
      legitimate re-export shape while still flagging genuine renames like
      ``_my_normalize = _hook_utils.normalize_path``.
    - A ``# sister-site: ok <reason>`` marker directly above the statement.
    """
    src = _read_source(path)
    if src is None:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    rel = path.relative_to(root).as_posix()
    misses: list[AliasMiss] = []

    def _diverges(local: str, target: str) -> bool:
        return local.lstrip("_") != target.lstrip("_")

    for node in tree.body:
        # Opt-out check is at the top of the loop so it applies uniformly to
        # all three shims; on a non-alias node (FunctionDef/ClassDef) a marker
        # above just skips a node that is not an alias site anyway.
        if _opt_out_marker_above(lines, node.lineno) is not None:
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if not isinstance(value, ast.Attribute):
                continue
            if not isinstance(value.value, ast.Name):
                continue
            if not _diverges(target.id, value.attr):
                continue
            misses.append(AliasMiss(
                lhs_name=target.id,
                rhs_module=value.value.id,
                rhs_attr=value.attr,
                file=rel,
                lineno=node.lineno,
                shape="assign",
            ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or "."
            for alias in node.names:
                if alias.asname is None or alias.name == "*":
                    continue
                if not _diverges(alias.asname, alias.name):
                    continue
                misses.append(AliasMiss(
                    lhs_name=alias.asname,
                    rhs_module=module,
                    rhs_attr=alias.name,
                    file=rel,
                    lineno=node.lineno,
                    shape="import-from",
                ))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is None:
                    continue
                imported = alias.name.rsplit(".", 1)[-1]
                if not _diverges(alias.asname, imported):
                    continue
                misses.append(AliasMiss(
                    lhs_name=alias.asname,
                    rhs_module=(alias.name.rsplit(".", 1)[0]
                                if "." in alias.name else ""),
                    rhs_attr=imported,
                    file=rel,
                    lineno=node.lineno,
                    shape="import",
                ))
    return misses


def _apply_ignores(
    targets: list[Path], root: Path, ignore_res: tuple[re.Pattern[str], ...],
) -> list[Path]:
    return [
        p for p in targets
        if not any(r.search(_rel_label(p, root)) for r in ignore_res)
    ]


def _analyse(
    targets: list[Path],
    root: Path,
    ignore_res: tuple[re.Pattern[str], ...],
    *,
    harness_arms: bool,
) -> ProbeReport:
    """Run the detectors over ``targets`` (already ignore-filtered by the caller).

    Function cliques, constant cliques and concept overlaps run everywhere.
    Canon-miss (re-implementing a ``_hook_utils`` export) and alias-miss (a
    rename shim whose local name diverges) are HARNESS conventions and run
    only with ``harness_arms``: an adopter's ``import numpy as np`` is not
    rename drift, and their code has no canonical file to shadow.
    """
    sites_by_name: dict[str, list[FunctionSite]] = {}
    for path in targets:
        for site in _collect_sites(path, root):
            if site.opt_out_reason is not None:
                continue
            sites_by_name.setdefault(site.name, []).append(site)

    cliques: list[Clique] = []
    for name, sites in sorted(sites_by_name.items()):
        if len(sites) < 2:
            continue
        divergent = len({s.body_hash for s in sites}) > 1
        severity = "WARN" if len(sites) >= 3 else "INFO"
        cliques.append(Clique(
            name=name,
            sites=tuple(sites),
            severity=severity,
            divergent=divergent,
            delegating=_clique_delegation(sites, name),
        ))

    misses: list[CanonMiss] = []
    alias_misses: list[AliasMiss] = []
    if harness_arms:
        canon = _collect_canonical_names(root)
        canon_by_hash: dict[str, list[tuple[str, str]]] = {}
        for cname, (cfile, chash) in canon.items():
            canon_by_hash.setdefault(chash, []).append((cname, cfile))

        for path in targets:
            rel = _rel_label(path, root)
            src = _read_source(path)
            if src is None:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            lines = src.splitlines()
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef):
                    continue
                if _opt_out_marker_above(lines, node.lineno) is not None:
                    continue
                # Same-name shadows are the helper-shadow contract's domain
                # (tests/test_hook_helper_consolidation.py::TestHelperShadow).
                # Don't double-report here.
                if node.name in canon:
                    continue
                shadow_hash = _hash_body(node.body)
                if shadow_hash in canon_by_hash:
                    for cname, cfile in canon_by_hash[shadow_hash]:
                        misses.append(CanonMiss(
                            canonical_name=cname,
                            canonical_file=cfile,
                            shadow_name=node.name,
                            shadow_file=rel,
                            shadow_lineno=node.lineno,
                            shape="body-match",
                        ))
                    continue
                # ``canon`` maps name -> (file, hash); the body-match branch
                # above unpacks via ``canon_by_hash``, and this branch used to
                # hand the whole tuple to ``canonical_file`` (pre-existing;
                # surfaced once --json became a pinned step 0-C contract).
                for cname, (cfile, _chash) in canon.items():
                    if _is_one_line_call(node, cname):
                        misses.append(CanonMiss(
                            canonical_name=cname,
                            canonical_file=cfile,
                            shadow_name=node.name,
                            shadow_file=rel,
                            shadow_lineno=node.lineno,
                            shape="alias-call",
                        ))
                        break

        for path in targets:
            alias_misses.extend(_collect_alias_misses(path, root))

    constant_sites_by_name: dict[str, list[ConstantSite]] = {}
    for path in targets:
        for cs in _collect_constant_sites(path, root):
            constant_sites_by_name.setdefault(cs.name, []).append(cs)

    constant_cliques: list[ConstantClique] = []
    for cname, csites in sorted(constant_sites_by_name.items()):
        if len(csites) < 2:
            continue
        divergent = len({s.value_hash for s in csites}) > 1
        severity = "WARN" if len(csites) >= 3 else "INFO"
        constant_cliques.append(ConstantClique(
            name=cname,
            sites=tuple(csites),
            severity=severity,
            divergent=divergent,
        ))

    all_constant_sites = [
        s for csites in constant_sites_by_name.values() for s in csites
    ]
    concept_overlaps = _build_concept_overlaps(all_constant_sites)

    return ProbeReport(
        cliques=tuple(cliques),
        canon_misses=tuple(misses),
        alias_misses=tuple(alias_misses),
        constant_cliques=tuple(constant_cliques),
        concept_overlaps=tuple(concept_overlaps),
    )


def probe_compression_debt(
    roots: list[Path],
    threshold: float = 1.0,
    ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS,
    scan_roots: tuple[Path, ...] | None = None,
) -> ProbeReport:
    """Scan ``roots[0]`` and return a ``ProbeReport`` -- gating findings for
    the tree's own scope, plus ``scope`` (what was looked at) and, on an
    adopter tree, ``harness_internal`` (the deployed hooks, advisory).

    ``threshold`` is reserved for future fuzzy-match support; v1 only
    supports exact AST-dump hash matching. Non-1.0 values are accepted
    but currently have no effect.

    ``roots`` semantics: the first root is the project root from which
    default scan targets are derived. Additional roots are reserved for
    future cross-repo or multi-tree scans. ``scan_roots`` (the CLI's
    ``--roots``) narrows the GATING scope to those directories or files in
    either mode; relative entries resolve against the project root.
    """
    if not roots:
        return ProbeReport(
            cliques=(), canon_misses=(),
            alias_misses=(), constant_cliques=(),
        )
    root = roots[0].resolve()
    ignore_res = tuple(re.compile(p) for p in ignore_patterns)
    mode = probe_mode(root)

    starts: tuple[Path, ...] | None = None
    if scan_roots:
        starts = tuple(s if s.is_absolute() else root / s for s in scan_roots)

    if starts is None and mode == MODE_SELF_HOST:
        targets = _self_host_scan_targets(root)
        root_labels: tuple[str, ...] = ("tools/cc/hooks/*.py", "espalier/*.py")
        pruned: tuple[str, ...] = ()
    else:
        targets, root_labels, pruned = _adopter_scan_targets(root, starts)
    targets = _apply_ignores(targets, root, ignore_res)

    gating = _analyse(
        targets, root, ignore_res, harness_arms=(mode == MODE_SELF_HOST),
    )

    harness: ProbeReport | None = None
    harness_files: tuple[str, ...] = ()
    if mode == MODE_ADOPTER:
        h_targets = _apply_ignores(_harness_internal_targets(root), root, ignore_res)
        harness_files = tuple(_rel_label(p, root) for p in h_targets)
        harness = _analyse(h_targets, root, ignore_res, harness_arms=True)

    scope = ProbeScope(
        mode=mode,
        roots=root_labels,
        scanned=tuple(_rel_label(p, root) for p in targets),
        pruned=pruned,
        harness_files=harness_files,
        explicit_roots=starts is not None,
    )
    return gating._replace(scope=scope, harness_internal=harness)


# The four blocking-class kinds, by the label ``_blocking_items`` prints. The
# 0-C body in .claude/commands/implement-pack.md must name every one of them;
# tests/test_implement_pack_step_zero.py derives that check from this tuple
# rather than from a hand-list of its own.
BLOCKING_LABELS: tuple[str, ...] = (
    "CANON-MISS",
    "ALIAS-MISS",
    "IDENTICAL FUNCTION CLIQUE",
    "IDENTICAL CONSTANT CLIQUE",
)
_L_CANON, _L_ALIAS, _L_FUNC, _L_CONST = BLOCKING_LABELS


def _blocking_items(report: ProbeReport) -> list[str]:
    """Blocking-class findings in ``report``'s OWN scope, one ASCII line each.

    Exactly the set the exit code keys on -- ``report_has_debt`` is its
    truth value, and the HARNESS-INTERNAL section prints it, so the gate and
    the advisory heading can never disagree about what counts:

    - any canon-miss (re-implementing a ``_hook_utils`` export)
    - any alias-miss (LHS basename != aliased attr -- the rename-drift class,
      driven to zero and gated so it cannot re-accrue; a deliberate short-name
      alias is opted out with a ``# sister-site: ok <reason>`` marker)
    - any 3+ IDENTICAL function clique that is not DELEGATING
    - any 3+ IDENTICAL constant clique (same value across 3 sites)

    DIVERGENT cliques (same name, different bodies) are advisory -- every
    CLI/hook legitimately has its own ``main``, scanners legitimately have
    parallel ``_classify`` shapes. DELEGATING cliques are advisory for the
    same reason: every site is a one-line ``return <owner>(...)`` naming ONE
    shared owner, so the logic already lives exactly once and the sites are
    what compression LEFT BEHIND. Blocking on them asks a caller to
    un-delegate. Measured on this repo when the arm was added: both blocking
    cliques were this shape, i.e. a 2-of-2 false-positive rate on the live
    corpus, on a gate ``/implement-pack`` step 0-C runs at every invocation.
    """
    items: list[str] = []
    for m in report.canon_misses:
        items.append(
            f"{_L_CANON}  {m.shadow_file}:{m.shadow_lineno} `{m.shadow_name}` "
            f"({m.shape}) re-implements `{m.canonical_name}`"
        )
    for a in report.alias_misses:
        qualified = f"{a.rhs_module}.{a.rhs_attr}" if a.rhs_module else a.rhs_attr
        items.append(
            f"{_L_ALIAS}  {a.file}:{a.lineno} `{a.lhs_name}` = `{qualified}` ({a.shape})"
        )
    for c in report.cliques:
        if c.severity == "WARN" and not c.divergent and not c.delegating:
            where = ", ".join(f"{s.file}:{s.lineno}" for s in c.sites)
            items.append(f"{_L_FUNC}  `{c.name}` x{len(c.sites)}: {where}")
    for c in report.constant_cliques:
        if c.severity == "WARN" and not c.divergent:
            where = ", ".join(f"{s.file}:{s.lineno}" for s in c.sites)
            items.append(f"{_L_CONST}  `{c.name}` x{len(c.sites)}: {where}")
    return items


def report_has_debt(report: ProbeReport) -> bool:
    """The gate: blocking-class debt in ``report``'s own scope. The
    ``harness_internal`` sub-report is never consulted -- on an adopter tree
    that debt is Espalier's to fix, not the adopter's to be blocked on."""
    return bool(_blocking_items(report))


def _clique_tag(clique) -> str:
    """One-word classification shown beside a clique name.

    Shared by the function-clique and constant-clique renderers so the three
    call sites do not each carry their own copy of the ternary.

    The ``delegating`` read is an explicit ``isinstance`` rather than a
    ``getattr(..., False)`` default: ``has_debt`` reads ``c.delegating``
    directly, and a defaulted lookup here would let a future rename of that
    field print "identical" from the renderer while the gate raised
    AttributeError -- the two views of one field disagreeing silently, which
    is the class this probe exists to find.
    """
    if clique.divergent:
        return "DIVERGENT"
    if isinstance(clique, Clique) and clique.delegating:
        return "delegating"
    return "identical"


def _format_scope_lines(scope: ProbeScope) -> list[str]:
    """The SCOPE block: whose code, how many files, what was pruned. The
    SCANNED NOTHING line fires in BOTH modes -- a self-host-shaped tree with
    no hooks and an empty engine dir used to print ``0 file(s)`` then CLEAN."""
    out: list[str] = []
    n = len(scope.scanned)
    where = ", ".join(scope.roots)
    self_host = scope.mode == MODE_SELF_HOST
    if self_host:
        out.append(f"SCOPE: harness source tree -- {n} file(s) under {where}.")
        if scope.explicit_roots:
            out.append(
                "  note: --roots bypasses the self-host scope-outs (espalier/ "
                "subpackages such as scanners/ and assets/, tools/cc/ root "
                "scripts); expect parallels the default scan leaves out."
            )
        else:
            out.append(
                "  tools/cc/ root scripts and espalier/ subpackages are out of "
                "scope; a clean exit is not an absence proof for them."
            )
        how = "narrowed by --roots" if scope.explicit_roots else "default self-host scope"
    else:
        how = (
            "narrowed by --roots" if scope.explicit_roots
            else "default walk of the whole tree; pass --roots <dir>... to narrow"
        )
        out.append("SCOPE: adopter tree -- the gating scan below covers YOUR source.")
        if n:
            out.append(f"  Scanned {n} .py file(s) under {where} ({how}).")
    if n == 0:
        whose = "this tree" if self_host else "your code"
        out.append(f"  SCANNED NOTHING: no .py source found under {where} ({how}).")
        if scope.explicit_roots:
            out.append(
                f"  A clean exit here says nothing about {whose} -- the --roots "
                "you named hold no .py source; name the directory that does."
            )
        else:
            out.append(
                f"  A clean exit here says nothing about {whose} -- point the "
                "probe at it with --roots <dir>."
            )
    if scope.pruned:
        shown = list(scope.pruned[:8])
        more = len(scope.pruned) - len(shown)
        tail = f" (+{more} more)" if more else ""
        out.append(
            "  Pruned: " + ", ".join(shown) + tail
            + " -- name a pruned dir on --roots to include it."
        )
    if scope.harness_files:
        out.append(
            f"  Espalier's own deployed hooks ({len(scope.harness_files)} file(s) "
            "under tools/cc/hooks/) are listed at the end under HARNESS-INTERNAL: "
            "advisory only, never gating."
        )
    return out

def _format_harness_internal(report: ProbeReport) -> list[str]:
    """The advisory tail on an adopter tree; empty on self-host."""
    if report.harness_internal is None:
        return []
    count = len(report.scope.harness_files) if report.scope is not None else 0
    out: list[str] = [""]
    out.append(
        f"HARNESS-INTERNAL (advisory, never gates this run) -- {count} deployed "
        "hook file(s) under tools/cc/hooks/:"
    )
    out.append(
        "  Debt here belongs to Espalier, not to this repo; write_guard keeps "
        "these files read-only. Report it upstream, do not fix it here."
    )
    items = _blocking_items(report.harness_internal)
    if items:
        for item in items:
            out.append("  " + item)
    else:
        out.append("  Nothing blocking-class found in the deployed hooks.")
    return out


def _format_report_text(report: ProbeReport, include_info: bool) -> str:
    out: list[str] = []
    out.append("Sister-site compression probe")
    out.append("=" * 40)
    if report.scope is not None:
        out.extend(_format_scope_lines(report.scope))
    # Remediation text names ``_hook_utils`` only when the findings are the
    # harness's own; an adopter cannot write there (write_guard denies it) and
    # a hand-built report (scope None) keeps the historical wording.
    harness_scope = report.scope is None or report.scope.mode == MODE_SELF_HOST

    warn_cliques = [c for c in report.cliques if c.severity == "WARN"]
    info_cliques = [c for c in report.cliques if c.severity == "INFO"]
    warn_const = [
        c for c in report.constant_cliques if c.severity == "WARN"
    ]
    info_const = [
        c for c in report.constant_cliques if c.severity == "INFO"
    ]
    # INFO (2-site) cliques print only with --include-info, so they must not
    # suppress the CLEAN line when hidden: a report whose only content is
    # hidden used to print a bare header and nothing else.
    hidden_info = 0 if include_info else len(info_cliques) + len(info_const)
    nothing = (
        not warn_cliques and (include_info is False or not info_cliques)
        and not report.canon_misses and not report.alias_misses
        and not warn_const and (include_info is False or not info_const)
        and not report.concept_overlaps
    )
    if nothing:
        out.append(
            "CLEAN -- no cliques, no canon-misses, no alias-misses, "
            "no constant-cliques."
            + (
                f" ({hidden_info} 2-site INFO clique(s) hidden; "
                "--include-info shows them.)" if hidden_info else ""
            )
        )
        # Plain ``sep.join(out)`` on purpose: the portability contract's
        # rule (g) registers this accumulator from that exact shape, and a
        # ``join(out + tail)`` silently dropped the whole report body out of
        # the ASCII net when it was tried.
        out.extend(_format_harness_internal(report))
        return "\n".join(out)

    if report.canon_misses:
        out.append("")
        out.append(f"CANON-MISS ({len(report.canon_misses)}):")
        for m in report.canon_misses:
            out.append(
                f"  {m.shadow_file}:{m.shadow_lineno} `{m.shadow_name}` "
                f"({m.shape}) -- re-implements `{m.canonical_name}` from "
                f"{m.canonical_file}. "
                f"Use `{m.shadow_name} = _hook_utils.{m.canonical_name}` "
                f"or import directly."
            )

    if report.alias_misses:
        out.append("")
        out.append(f"ALIAS-MISS ({len(report.alias_misses)}):")
        for a in report.alias_misses:
            qualified = (
                f"{a.rhs_module}.{a.rhs_attr}" if a.rhs_module else a.rhs_attr
            )
            out.append(
                f"  {a.file}:{a.lineno} `{a.lhs_name}` = "
                f"`{qualified}` ({a.shape}) -- names diverge. "
                f"Adopt the canonical name (`{a.rhs_attr}`), or -- if this is a "
                f"deliberate or conventional alias -- add a `# sister-site: ok "
                f"<reason>` marker above it."
            )

    if warn_cliques:
        out.append("")
        out.append(f"WARN cliques ({len(warn_cliques)} -- 3+ sites):")
        for c in warn_cliques:
            tag = _clique_tag(c)
            out.append(f"  `{c.name}` ({tag}, {len(c.sites)} sites):")
            for s in c.sites:
                out.append(f"    {s.file}:{s.lineno}")
            if c.delegating:
                out.append(
                    f"    Advisory, not debt: every site is "
                    f"`return {c.sites[0].delegation_target}(...)`, so the "
                    f"logic already lives once."
                )

    if warn_const:
        out.append("")
        out.append(
            f"CONSTANT-CLIQUE WARN ({len(warn_const)} -- 3+ sites):"
        )
        for c in warn_const:
            tag = _clique_tag(c)
            out.append(f"  `{c.name}` ({tag}, {len(c.sites)} sites):")
            for s in c.sites:
                out.append(f"    {s.file}:{s.lineno}")
            if not c.divergent and harness_scope:
                out.append(
                    f"    Suggested: promote `{c.name}` to "
                    f"_hook_utils.{c.name}; import at each site."
                )
            elif not c.divergent:
                out.append(
                    f"    Suggested: promote `{c.name}` to one shared module; "
                    "import at each site."
                )

    if include_info and info_cliques:
        out.append("")
        out.append(f"INFO cliques ({len(info_cliques)} -- 2 sites):")
        for c in info_cliques:
            tag = _clique_tag(c)
            out.append(f"  `{c.name}` ({tag}, {len(c.sites)} sites):")
            for s in c.sites:
                out.append(f"    {s.file}:{s.lineno}")

    if include_info and info_const:
        out.append("")
        out.append(
            f"CONSTANT-CLIQUE INFO ({len(info_const)} -- 2 sites):"
        )
        for c in info_const:
            tag = _clique_tag(c)
            out.append(f"  `{c.name}` ({tag}, {len(c.sites)} sites):")
            for s in c.sites:
                out.append(f"    {s.file}:{s.lineno}")

    if report.concept_overlaps:
        out.append("")
        out.append(
            f"CONCEPT-OVERLAP ({len(report.concept_overlaps)} -- advisory, "
            f"different names, overlapping elements):"
        )
        for o in report.concept_overlaps:
            names = ", ".join(sorted({s.name for s in o.members}))
            out.append(f"  {{{names}}} share {len(o.shared)} element(s):")
            for s in o.members:
                out.append(f"    {s.name}  {s.file}:{s.lineno}")

    out.extend(_format_harness_internal(report))
    return "\n".join(out)


def _report_to_json(report: ProbeReport) -> str:
    return json.dumps(_report_payload(report), indent=2, sort_keys=True)


def _report_payload(report: ProbeReport) -> dict:
    def _site(s: FunctionSite) -> dict:
        return {
            "name": s.name,
            "file": s.file,
            "lineno": s.lineno,
            "body_hash": s.body_hash,
        }

    def _csite(s: ConstantSite) -> dict:
        return {
            "name": s.name,
            "file": s.file,
            "lineno": s.lineno,
            "value_hash": s.value_hash,
        }

    payload = {
        "cliques": [
            {
                "name": c.name,
                "severity": c.severity,
                "divergent": c.divergent,
                # Advisory-but-not-debt, like `divergent`. A consumer reading
                # only `severity` would otherwise see a WARN it cannot explain.
                "delegating": c.delegating,
                "delegation_target": (
                    c.sites[0].delegation_target if c.delegating else None
                ),
                "sites": [_site(s) for s in c.sites],
            }
            for c in report.cliques
        ],
        "canon_misses": [
            {
                "canonical_name": m.canonical_name,
                "canonical_file": m.canonical_file,
                "shadow_name": m.shadow_name,
                "shadow_file": m.shadow_file,
                "shadow_lineno": m.shadow_lineno,
                "shape": m.shape,
            }
            for m in report.canon_misses
        ],
        "alias_misses": [
            {
                "lhs_name": a.lhs_name,
                "rhs_module": a.rhs_module,
                "rhs_attr": a.rhs_attr,
                "file": a.file,
                "lineno": a.lineno,
                "shape": a.shape,
            }
            for a in report.alias_misses
        ],
        "constant_cliques": [
            {
                "name": c.name,
                "severity": c.severity,
                "divergent": c.divergent,
                "sites": [_csite(s) for s in c.sites],
            }
            for c in report.constant_cliques
        ],
        "concept_overlaps": [
            {
                "shared": list(o.shared),
                "members": [_csite(s) for s in o.members],
            }
            for o in report.concept_overlaps
        ],
        # The gate's own verdict, so a --json consumer need not re-derive it.
        "has_debt": report_has_debt(report),
        # True when the gating scope held no file at all: rc 0 with this set
        # is "never looked", not "clean" -- a --json caller must read it.
        "scanned_nothing": report.scope is not None and not report.scope.scanned,
        "scope": None if report.scope is None else {
            "mode": report.scope.mode,
            "roots": list(report.scope.roots),
            "scanned_count": len(report.scope.scanned),
            "scanned": list(report.scope.scanned),
            "pruned": list(report.scope.pruned),
            "harness_files": list(report.scope.harness_files),
            "explicit_roots": report.scope.explicit_roots,
        },
        # Same shape as the top level, minus scope; advisory, never gating.
        "harness_internal": (
            None if report.harness_internal is None
            else _report_payload(report.harness_internal)
        ),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sister_site_probe",
        description="Surface near-duplicate function bodies.",
    )
    parser.add_argument("--root", default=".",
                        help="Project root (default: cwd)")
    parser.add_argument("--roots", action="extend", nargs="+", default=[],
                        metavar="PATH",
                        help="Scan only these dirs/files (relative to --root) "
                             "as the gating scope; repeatable. Default: an "
                             "adopter tree walks itself minus junk, tests and "
                             "the harness's zones; the harness source tree "
                             "scans hooks + top-level engine")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON report on stdout")
    parser.add_argument("--ignore", action="append", default=[],
                        metavar="PATTERN",
                        help="Regex matched against rel-path; repeatable")
    parser.add_argument("--include-info", action="store_true",
                        help="Include 2-site INFO cliques in the report")
    parser.add_argument("--accept-compression-debt", metavar="REASON",
                        default=None,
                        help="Acknowledge debt; exit 0 with reason recorded")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    ignore = tuple(args.ignore) or DEFAULT_IGNORE_PATTERNS
    scan_roots: list[Path] = []
    for raw in args.roots:
        p = Path(raw)
        p = (p if p.is_absolute() else root / p).resolve()
        if not p.exists():
            print(f"[ERROR] --roots: {raw} does not exist under {root}",
                  file=sys.stderr)
            return 1
        try:
            p.relative_to(root)
        except ValueError:
            print(f"[ERROR] --roots: {raw} lies outside --root {root}",
                  file=sys.stderr)
            return 1
        scan_roots.append(p)
    report = probe_compression_debt(
        [root], ignore_patterns=ignore,
        scan_roots=tuple(scan_roots) or None,
    )

    if args.json:
        print(_report_to_json(report))
    else:
        print(_format_report_text(report, args.include_info))

    scope = report.scope
    if scope is not None:
        # One stderr line in every mode, so a --json caller (step 0-C) still
        # sees whose code the exit code is about.
        harness_note = ""
        if report.harness_internal is not None:
            k = len(_blocking_items(report.harness_internal))
            harness_note = (
                f"; harness-internal (advisory, not gating): {k} blocking-class "
                f"item(s) across {len(scope.harness_files)} deployed hook file(s)"
            )
        loud = (
            " -- SCANNED NOTHING, this verdict says nothing about the code"
            if not scope.scanned else ""
        )
        print(
            f"[scope] {scope.mode}: {len(scope.scanned)} file(s) under "
            f"{', '.join(scope.roots)}{loud}{harness_note}",
            file=sys.stderr,
        )

    # Blocking-class debt in the GATING scope only -- see `_blocking_items`
    # for the exact set and why DIVERGENT/DELEGATING cliques stay advisory.
    has_debt = report_has_debt(report)
    if has_debt and args.accept_compression_debt:
        print(
            f"\n[ACCEPTED] Compression debt acknowledged: "
            f"{args.accept_compression_debt}",
            file=sys.stderr,
        )
        return 0
    return 2 if has_debt else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — top-level guard
        print(f"[ERROR] sister_site_probe crashed: {type(e).__name__}: {os_error_text(e)}", file=sys.stderr)
        sys.exit(1)
