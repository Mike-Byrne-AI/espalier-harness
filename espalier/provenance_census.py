"""De-provenance census — the single source of truth for the shipping-surface
provenance guard.

Detects internal build-history tags that must not survive on a SHIPPED surface a
public reader sees (the wheel + sdist payload plus the GitHub-browsable tree):
task-pack ids, review-round ids, workflow run ids, deferred-review cross-refs,
and adversarial-pass war-story lead-ins — outside a small load-bearing allowlist.
The behavioral content the comments / docs explain is KEPT verbatim; only the
build-history wrapper is stripped.

Consumed by BOTH:
  * ``tests/test_no_provenance_in_shipped_code.py`` — the regression gate (full suite)
  * ``espalier provenance`` — the fast-loop CLI + the ``/smoke`` check

Both read THIS module, so "what counts as a provenance tag" has exactly ONE
definition. A second copy would be the very drift this guard exists to prevent.

Add a load-bearing entry to ``_ALLOWED_HITS`` (with a reason) rather than
disabling the guard.

Scope (operator-settled):

* SCAN  = public-classified tracked files (``surface_contract.classify_release_path``)
  minus the regenerated mirrors (their own parity tests pin them byte-for-byte to
  a SoT this guard DOES scan — except the entries in ``_CENSUS_FORCE_SCAN``, which
  have no scanned SoT and are scanned directly), ``tests/`` (pruned from wheel + sdist),
  and the allowlisted config / reasoning surfaces below. One mirror is scanned
  directly rather than via its SoT: ``espalier/_vendor/selfcheck_tests/`` ships as
  package-data yet its SoT ``tests/`` is excluded here, so only the exact
  ``espalier/_vendor/cc/`` subtree is excluded and the selfcheck mirror is scanned.
* KEEP  = config/build files (terse structural cites), ``memory/`` (the reasoning
  corpus — provenance is intrinsic there), this census module itself (it
  necessarily embeds the vocabulary it polices), and the granular load-bearing
  ``_ALLOWED_HITS``. (``CHANGELOG.md`` was formerly kept but is now SCANNED — its
  public dated history was de-provenanced for the OSS launch and is gated here so
  the dev-log residue cannot silently re-accrue.)

The guard catches the mechanical *tags*. Prose meta-narration that carries no tag
is rephrased by the de-provenance sweep on judgment, not detected here.
"""
from __future__ import annotations

import re
from pathlib import Path

from espalier.repo_mode import list_tracked_or_walked_files
from espalier.surface_contract import classify_release_path
from espalier._text import plural

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Single source of truth for the committed project-memory filename — routed
# through one constant so a future rename is a value flip, not scattered edits.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

PROVENANCE_RE = re.compile(
    r"\bTP-(?:[A-Z]+-)?\d"  # TP-12, TP-169, TP-RELEASE-14, TP-OSS-01
    r"|\bPre-TP-(?:[A-Z]+-)?\d"  # Pre-TP-28 war-story lead-ins
    r"|\bTQ-(?:[A-Za-z]+-)?\d"  # TQ-adopter-3 / TQ-7 test-quality sub-task tags
    r"|\bXPLAT-\d"  # XPLAT-1 cross-platform sub-task tags
    r"|\bround[- ]\d"  # round-7 / round 7 review-round provenance
    r"|\bwf_[0-9a-f]{6}"  # workflow run ids (wf_6c5457cc…)
    r"|\bDR\d+ round"  # DR8 round-… deferred-review tags
    r"|§13 #\d+ round"  # §13 #5 round-… FAILURE_MODES cross-refs
    r"|the A\d adversarial"  # "the A4 adversarial pass found …"
)

# Regenerated mirrors (each pinned byte-for-byte to a SoT this guard scans) +
# not-shipped / operator-allowlisted trees.
_EXCLUDED_PREFIXES = (
    "espalier/_vendor/cc/",  # vendored tools/cc byte-mirror — tests/test_vendor_cc_parity.py
    # NB: espalier/_vendor/selfcheck_tests/ is deliberately NOT excluded — it ships
    # as package-data (pyproject.toml) but its SoT (tests/) is also excluded here,
    # so the shipped mirror would otherwise carry unscanned provenance. Clean the
    # tests/ SoT and re-run scripts/sync_selfcheck_tests.py; never hand-edit the mirror.
    "espalier/assets/",  # wheel asset mirrors — test_package_resource_parity / test_deploy_doc_parity
    "examples/dogfooding/.claude/",  # generated .claude mirror — test_package_resource_parity
    "tests/",  # pruned from wheel + sdist (MANIFEST.in `prune tests`)
    "memory/",  # reasoning corpus (operator-allowlisted); sibling to export-ignored ESPALIER_MEMORY.md
    # The forward-work tracker (the ledger, its probes file, the active packs),
    # public since 2026-09-21 and MADE of pack ids: every row is keyed on one,
    # every pack is named by one. Excluded as a whole on the same reasoning that
    # keeps ESPALIER_MEMORY.md allowlisted (the open operator call the ledger's
    # own DEC-13 row records), rather than a per-file entry that a new pack
    # would silently miss. The one public file under this prefix that ships to
    # ADOPTERS -- the router -- is covered through its force-scanned asset twin
    # below, not here.
    "task-packs/",
)

# Some espalier/assets/ files are NOT byte-pinned to a scanned SoT, so the blanket
# espalier/assets/ exclusion above would leave them uncensored: assets/memory/README.md
# (its SoT memory/README.md is itself excluded, and they are not byte-equal),
# assets/CLAUDE.md (a folder-router with no root SoT this guard scans), and the
# assets/seed/ adopter stubs (hand-authored; deliberately NOT byte-equal to the
# docs/ file they seed — that non-equality is the whole point of
# managed_inventory._SEED_ASSET_SOURCES, so no scanned SoT covers them). All are
# public-classified and deployed to every adopter, so a leaked tag there would ship
# and be caught by NOTHING. Force-scan them directly (currently clean).
#
# A new assets/seed/ stub must be added here — the set is exact-path, not a
# prefix, so a third stub would silently inherit the blanket exclusion.
_CENSUS_FORCE_SCAN = frozenset(
    {
        "espalier/assets/memory/README.md",
        "espalier/assets/CLAUDE.md",
        "espalier/assets/seed/SHARP_EDGES.md",
        "espalier/assets/seed/CONVENTIONS.md",
        # The task-packs/ folder router. THE SEAM, stated deliberately: this
        # asset and its SoT `task-packs/CLAUDE.md` are byte-identical (one
        # sync), but they are scanned DIFFERENTLY and that is intended. The
        # SoT sits under the "task-packs/" prefix in _EXCLUDED_PREFIXES (the
        # tracker is made of pack ids), so it is never scanned -- until
        # 2026-09-21 it was also never scanned, for a different reason: it
        # classified `local_only`. The asset classifies `public` and deploys
        # to every adopter. Before this entry NEITHER side was scanned, so a
        # pack-id literal in a shipped adopter-facing doc would have been
        # caught by nothing.
        #
        # Consequence to expect, not to debug: if a tag ever lands in the
        # SoT, the sync propagates it and the MIRROR reds while the SoT stays
        # green. That is the right place to catch it -- the mirror is what
        # ships -- but it reads as a bug unless you have read this comment.
        #
        # Scanning the SoT instead was considered and rejected: the folder is
        # excluded as a whole, so exempting this one file means a special
        # case beside the ledger and every pack that legitimately carries ids.
        "espalier/assets/task-packs/CLAUDE.md",
    }
)

# Config / build + owned surfaces: terse structural cites kept by operator decision.
_ALLOWLISTED_FILES = frozenset(
    {
        "CLAUDE.md",
        "pyproject.toml",
        "MANIFEST.in",
        ".gitignore",
        ".gitattributes",
        # CHANGELOG.md is intentionally NOT allowlisted: its public dated history
        # was de-provenanced for the OSS launch, and this census gates it so the
        # internal dev-log residue (task-pack ids, review-round labels) cannot
        # silently re-accrue on the surface a reader scrolls after the README.
        _MEMORY_FILENAME,
        # This census module IS the de-provenance SoT: it necessarily embeds the
        # provenance vocabulary it polices (PROVENANCE_RE source + the token data
        # in _ALLOWED_HITS). Scanning it would flag its own allowlist. Same
        # rationale as memory/ — provenance is intrinsic here.
        "espalier/provenance_census.py",
    }
)

# Granular load-bearing hits permitted to remain: (relpath, token-substring) -> reason.
_ALLOWED_HITS: dict[tuple[str, str], str] = {
    ("tools/cc/hooks/write_guard.py", "TP-79"): (
        "in the SHA-pinned first-200-byte self-host-signal head — must stay "
        "byte-stable (see memory/write-guard-first-200-bytes-selfhost-signal.md)"
    ),
    (".claude/commands/implement-pack.md", "TP-62"): (
        "Pack-artifact checklist version label asserted by "
        "tests/test_implement_pack_step_zero.py"
    ),
    ("tools/cc/pack_artifact_checklist.md", "TP-62"): (
        "Pack-artifact checklist version label asserted by "
        "tests/test_implement_pack_step_zero.py"
    ),
    ("espalier/scanners/retired_vocab.py", "TP-114"): (
        "the `retired_in` migration-pack field of every RetiredTerm + the "
        "Pre-TP-114 legacy-vocab note — asserted by "
        "tests/test_scanner_retired_vocab.py"
    ),
    ("tools/cc/hooks/plan_guard.py", "POST-TP-64"): (
        "the `POST-TP-64 NOTICE` banner sentinel — pinned by "
        "tests/test_plan_guard_branch_pinned.py::BANNER_SENTINEL"
    ),
    ("tools/cc/reasoning_review_checklist.md", "TP-63"): (
        "Reasoning-review checklist version label asserted by "
        "tests/test_reflect_reasoning.py"
    ),
    ("docs/CONVENTIONS.md", "TP-99-smoke-broken"): (
        "worked-example fixture filename illustrating the TP-NN pack-naming "
        "convention in the manual smoke procedure (not a real pack)"
    ),
}


def path_is_scanned(rel: str) -> bool:
    """Whether the provenance census scans ``rel`` at all — the single SoT.

    This is the WHOLE-FILE decision only. It is deliberately public because
    more than one caller needs it: ``espalier.surface_impact`` must not report
    a provenance obligation for a path this census would never look at. Every
    caller consults this predicate; nobody re-derives the lists, because two
    enumerations of "what the census covers" drift apart — the class this
    module's own guard exists to catch.

    Note the asymmetry with :func:`allowed_tokens`, which is easy to get
    wrong: ``_ALLOWLISTED_FILES`` skips a file entirely, whereas
    ``_ALLOWED_HITS`` forgives *specific tokens* in a file that IS scanned.
    Suppressing ``_ALLOWED_HITS`` paths here would be strictly wider than the
    census and would hide a genuinely new tag in, say, ``write_guard.py``.
    """
    if rel in _ALLOWLISTED_FILES:
        return False
    if rel not in _CENSUS_FORCE_SCAN and rel.startswith(_EXCLUDED_PREFIXES):
        return False
    return classify_release_path(rel) == "public"


def allowed_tokens(rel: str) -> frozenset[str]:
    """Provenance tokens forgiven in ``rel`` specifically (may be empty).

    Per-token, not per-file: a file with an entry here is still scanned, and a
    second, un-allowlisted tag on the same line is still an offender.
    """
    return frozenset(
        token for (allowed_rel, token) in _ALLOWED_HITS if allowed_rel == rel
    )


def _shipping_surface_files(repo_root: Path) -> list[str]:
    files, _source = list_tracked_or_walked_files(repo_root)
    return [rel for rel in files if path_is_scanned(rel)]


def _is_allowed(rel: str, line: str) -> bool:
    """True only when EVERY provenance hit in ``line`` is an allowlisted token for
    ``rel``. Neutralizes each allowed token for the file, then re-scans the
    remainder — so a SECOND (leaked) tag added to an allowlisted line is still
    flagged (per-token, not per-line whitewash)."""
    tokens = allowed_tokens(rel)
    if not tokens:
        return False
    remainder = line
    for token in tokens:
        remainder = remainder.replace(token, "")
    return PROVENANCE_RE.search(remainder) is None


def census_offenders(repo_root: Path | None = None) -> list[tuple[str, int, str]]:
    """Every ``(relpath, lineno, line)`` carrying a build-history tag on a
    shipping surface, outside the allowlist.

    ``repo_root`` defaults to this checkout's root so the regression test can
    call it argument-free; the CLI passes an explicit ``--repo``.
    """
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    offenders: list[tuple[str, int, str]] = []
    for rel in _shipping_surface_files(root):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if PROVENANCE_RE.search(line) and not _is_allowed(rel, line):
                offenders.append((rel, lineno, line.strip()[:100]))
    return offenders


def format_offenders(offenders: list[tuple[str, int, str]]) -> str:
    """Human/CLI report for a census result. Empty string when clean."""
    if not offenders:
        return ""
    from collections import Counter

    by_dir = Counter(rel.split("/")[0] for rel, _n, _t in offenders)
    lines = [
        f"{plural(len(offenders), 'internal build-history tag')} on shipping surfaces "
        f"(de-provenance incomplete). By top-dir: {dict(by_dir)}",
    ]
    for rel, n, txt in offenders:
        lines.append(f"  {rel}:{n}  {txt}")
    lines.append(
        "Strip the provenance wrapper (keep the behavioral content), or add a "
        "load-bearing entry to _ALLOWED_HITS with a reason."
    )
    return "\n".join(lines)
