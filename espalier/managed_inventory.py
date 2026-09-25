"""Managed-inventory SoT.

The single source of truth for **what Espalier-Harness owns**, used by:

- ``espalier init`` (deploy) — knows which paths it writes
- ``espalier clean-generated`` (cleanup) — removes managed files,
  preserves unmarked user files
- ``espalier doctor`` (ownership reporting) — reports drift
- ``cc/PACK_MANIFEST.txt`` (operator-facing) — generated from this
- ``espalier audit`` (surface gate) — manifest truth check

Three disjoint classifications:

- **public managed files** — Espalier deploys/regenerates these from
  package resources or renderers. Removable by ``clean-generated``.
- **local runtime files** — generated locally on first init or by
  per-install operations (``.claude/settings.json``,
  ``.espalier/integrity.json``, ``reports/*.json``). Never listed in
  ``PACK_MANIFEST``; never auto-deleted by ``clean-generated``.
- **local only files** — gitignored per-session state (cognitive
  blueprints, execution plans, surface handoff drafts, local
  settings). Never listed in ``PACK_MANIFEST``; never deployed.

Pack §1 functions return deterministic, slash-normalized lists.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from espalier import __version__, surface_contract
from espalier._safe_walk import safe_rglob
from espalier.asset_inventory import get_packaged_surface
from espalier.assets import assets_root
from espalier.managed_markers import SEED_STAMP_TOKEN, path_has_seed_stamp
from espalier.managed_paths import (
    STANDARD_MANAGED_CC_DOCS,
    STANDARD_MANAGED_TOOLS,
)

# Single source of truth for the committed project-memory filename — routed
# through one constant so a future rename is a value flip, not scattered edits.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

__all__ = [
    "get_managed_public_files",
    "get_managed_public_prefixes",
    "get_local_runtime_files",
    "get_local_runtime_prefixes",
    "local_state_on_disk",
    "is_render_artifact",
    "get_render_artifacts",
    "get_seed_docs",
    "unstamped_seed_docs",
    "count_unstamped_seed_docs",
    "get_seed_asset_source",
    "get_install_ci_artifacts",
    "seed_needs_adapt_header",
    "SEED_ADAPT_HEADER",
    "seed_stamp_line",
    "render_seed_body",
    "render_seed_stamp",
    "get_local_only_files",
    "get_generated_docs",
    "get_hook_entry_files",
    "get_hook_helper_files",
]


# ── Static classifications ────────────────────────────────────────────────


_HOOK_HELPERS: tuple[str, ...] = (
    "_bash_patterns.py",
    "_born_weak.py",
    "_denial_reasons.py",
    "_explain_path.py",
    "_hook_contract.py",
    "_hook_utils.py",
    "_integrity.py",
    "_maintenance_mode.py",
    "_protected_zones.py",
    "_recall.py",
    "_reinject.py",
    "_self_host_fingerprint.py",
    "_speedbump.py",
)
"""Helper modules under ``tools/cc/hooks/``. Init deploys these
alongside the entry scripts; cleanup must include them.

Note on counting: ``__init__.py`` is intentionally NOT a helper — it
is the package marker, not a hook collaborator. ``ls tools/cc/hooks/``
yields fourteen files matching ``_*.py`` (one ``__init__.py`` + thirteen
helpers), but only the thirteen count for SoT purposes.
``tests/_surface_expected.py::EXPECTED_HOOK_HELPER_COUNT`` pins the
canonical 13. The
same exclusion is enforced by ``get_hook_helper_files`` below — never
re-derive helper-membership from a directory walk; ask this module."""


_LOCAL_RUNTIME_REL_PATHS: tuple[str, ...] = (
    ".claude/settings.json",
    ".espalier/integrity.json",
    "reports/cc_surface_gate.json",
    "reports/harness_config.json",
    "reports/repo_fingerprint.json",
)
"""Files generated locally on each install. Not deployed *from* package
resources — produced per-install. Not part of PACK_MANIFEST. Not
auto-deleted by ``clean-generated``."""


_LOCAL_RUNTIME_PREFIXES: tuple[str, ...] = (
    ".espalier/",
    ".espalier-state/",
    "reports/",
    "cc/blueprints/",
    "cc/_cold/",
)
"""Directory roots the harness's RUNTIME writes into on an adopter tree,
outside the deployed surface: the integrity manifest and its write-lock,
freshness state and the candidate logs, ``stop_gate``'s session flags, the
fingerprint and scanner reports, the blueprint chain, the plan records the
``reset`` verb demotes (``execution_plan.py``). No inventory can list
those files by name -- they are created per session -- so "is this file
ours?" is answered by prefix here, and here only. Three consumers read it:
``cli._is_harness_owned`` (init's untracked-conflict advisory must not name
the harness's own output back to the adopter as their uncommitted work),
``cleanup`` (an uninstall must account for every file it leaves under these
roots), and ``analyze.HARNESS_OUTPUT_PREFIXES`` (the fingerprint must not read
the runtime's output as the adopter's code -- so a prefix added here also
removes that directory from every adopter's fingerprint, and
``tests/test_analyze.py::TestHarnessOutputPredicate`` pins the derived set so
the widening is a decision, not a side effect). Every prefix is covered by a
``cli.REQUIRED_GITIGNORE`` entry, pinned by
``tests/test_cleanup.py::TestLocalRuntimePrefixes``. Repo-root relative:
an adopter's nested ``src/reports/`` is theirs.

Sister site, deliberately different: ``surface_contract._LOCAL_ONLY_PATHS``
forbids a ``.espalier/`` prefix because that list answers the RELEASE
question and ``.espalier/freshness.json`` is committed on the self-host tree
and ships (BC-039). This list answers what the runtime WRITES, on a tree
where ``init``'s own ``REQUIRED_GITIGNORE`` entry ignores the directory whole,
so the prefix is right here -- and a file the adopter has committed anyway is
theirs whatever wrote it first, which ``local_state_on_disk`` honours by
subtracting the git index."""


_RENDER_ARTIFACT_REL_PATHS: tuple[str, ...] = (
    ".claude/settings.json.new",
    ".claude/settings.json.bak",
)
"""Files ``init`` and ``merge-settings`` render BESIDE the adopter's settings
rather than deploy: the ``.new`` template init writes when it declines to
overwrite an existing ``settings.json`` (``cli._render_settings_new_template``),
and the ``.bak`` copy ``merge-settings`` and ``--rewire-interpreter`` take
before rewriting (``cli._back_up_settings``: ``.bak``, then ``.bak.1``,
``.bak.2`` ... when the plain name is occupied and holds other bytes -- the
numbered form is read by ``settings_backup_rung`` below, the ladder grammar's
one spelling). Exact names, deliberately NOT a ``.claude/*.new`` arm: a
``.new`` the adopter authored is theirs, and init's advisory must still name
it (DEF-737)."""

def settings_backup_rung(name: str, base: str = "settings.json") -> int | None:
    """Position of file ``name`` on the settings backup ladder: 0 for
    ``settings.json.bak``, ``N`` for ``settings.json.bak.N`` (decimal digits
    only, so ``int`` never raises on a name this accepts), ``None`` for any
    other name -- ``settings.json.bak.old`` is the operator's own copy and
    ``settings.json.bakup`` is nothing of ours. The ladder grammar's one
    spelling: read by :func:`is_render_artifact` (the numbered arm), by
    ``cli._back_up_settings`` (which rung on disk already holds the bytes a
    wire would back up) and by ``cleanup``'s ordered listing of the copies an
    uninstall leaves (DEF-809). ``base`` is the settings file's own name, for
    a caller that owns a differently named file."""
    prefix = base + ".bak"
    if not name.startswith(prefix):
        return None
    tail = name[len(prefix):]
    if tail == "":
        return 0
    if tail.startswith(".") and tail[1:].isdecimal():
        return int(tail[1:])
    return None


_SEED_DOC_REL_PATHS: tuple[str, ...] = (
    "memory/README.md",
    "docs/sharp-edges/README.md",
    "docs/TROUBLESHOOTING.md",
    # Portable-knowledge carryover — seeded stamped, refreshed while untouched,
    # operator-editable. Tier 1 (verbatim) then Tier 2 (deploy-time
    # adapt-header, see ``_SEED_DOCS_WITH_ADAPT_HEADER`` below).
    "docs/external/cc-hook-protocol.md",
    "docs/sharp-edges/convergence-is-an-angle-set-property.md",
    "docs/sharp-edges/closed-loop-verification-trap.md",
    "docs/sharp-edges/hook-exit-codes-channel-xor.md",
    "task-packs/CLAUDE.md",
    # Deployed because `ci_guard.py`'s exit-2 output cites it, and that output
    # is read in a CI log by a contributor to the ADOPTER's repo -- who cannot
    # click a link, cannot tell the file was never deployed, and is looking at
    # the one manual step (branch protection) the whole guarantee depends on.
    # Tier 1: with the pre-release Private-Vulnerability-Reporting runbook
    # moved to docs/RELEASE_CHECKLIST.md, nothing here is an Espalier example
    # to genericize -- it is operating instruction for the artifact
    # `install-ci` just wrote into their repo. (DEF-503.)
    "docs/INSTALL-CI.md",
    "docs/FAILURE_MODES.md",
    "docs/PACK_AUTHORING.md",
    "docs/HOOKS.md",
    # Deployed because the hook-authoring skill and the seeded
    # cc-hook-protocol.md both send the reader here, and it documents the
    # behaviour of hooks the adopter actually runs -- not a maintainer ritual.
    # Adding it made the "self-host only / not deployed" parentheticals at
    # docs/HOOKS.md and .claude/skills/hook-authoring/SKILL.md false; both were
    # corrected in the same change.
    "docs/HOOK_ASSUMPTIONS.md",
    "docs/WORKFLOW.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
    "docs/FRESHNESS.md",
    "docs/ENV_CATALOG.md",
    # Tier 3 (adopter stubs) — near-empty scaffolds sourced from
    # ``espalier/assets/seed/`` via ``_SEED_ASSET_SOURCES`` below, NOT carried
    # copies of this repo's own docs. See that map for why the source path is
    # indirected rather than derived from the destination.
    "docs/SHARP_EDGES.md",
    "docs/CONVENTIONS.md",
)
"""Convention/doc scaffolds ``init`` seeds OUTSIDE the managed inventory
(unmarked, operator-editable; stamped, so an untouched copy is refreshed when
the packaged bytes change and an edited one is kept). Single source of truth for BOTH the
deploy loop (``cli.py``) and ``clean-generated``'s undeploy accounting
(``cleanup.py``), so the two cannot drift. Most seeds are NOT part of
``get_managed_public_files`` — they must stay out of PACK_MANIFEST / doctor /
the surface gate. EXCEPTION: entries that ALSO appear in ``_PACKAGED_ROOT_DOCS``
(currently ``docs/CHEAT-SHEET.md`` and ``docs/TASK_RECIPES.md``) carry a dual
role and ARE returned by ``get_managed_public_files`` via that constant —
mirroring the note on ``STANDARD_MANAGED_ROOT_DOCS`` (managed_paths.py)."""


_SEED_DOCS_WITH_ADAPT_HEADER: frozenset[str] = frozenset({
    "docs/FAILURE_MODES.md",
    "docs/PACK_AUTHORING.md",
    "docs/HOOKS.md",
    "docs/HOOK_ASSUMPTIONS.md",
    "docs/WORKFLOW.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
    "docs/FRESHNESS.md",
    "docs/ENV_CATALOG.md",
})
"""Tier-2 carried docs: portable method, but their bodies carry illustrative
Espalier-specific examples. Seeded WITH a deploy-time 'adapt these examples'
header (``SEED_ADAPT_HEADER`` below) so an adopter knows to genericize them.
Tier-1 seeds (cross-project / CC-protocol / pure method) ship verbatim. Must be
a subset of ``_SEED_DOC_REL_PATHS``."""


def seed_needs_adapt_header(rel: str) -> bool:
    """True if a seeded doc gets the deploy-time 'adapt these examples' header
    (Tier-2); False for Tier-1 docs that ship verbatim."""
    return rel in _SEED_DOCS_WITH_ADAPT_HEADER


_SEED_ASSET_SOURCES: dict[str, str] = {
    "docs/SHARP_EDGES.md": "seed/SHARP_EDGES.md",
    "docs/CONVENTIONS.md": "seed/CONVENTIONS.md",
}
"""Seed destination -> asset-root-relative SOURCE, for the seeds whose packaged
body is NOT this repo's own doc of the same name.

Without this indirection the deploy loop derives a seed's source directly from
its destination (``assets_root().joinpath(*dest.split("/"))``), so a seed at
``docs/X.md`` must be sourced from ``espalier/assets/docs/X.md`` — and two
contracts govern that directory: every ``.md`` under it must be listed in
``scripts/sync_asset_docs.py::_MIRRORED``
(``test_mirrored_covers_every_asset_doc``) and must be byte-equal to its
``docs/X.md`` twin (``test_source_asset_docs_are_byte_equal``). Together those
would force an adopter stub to become a byte-copy of this repo's own
``SHARP_EDGES.md`` / ``CONVENTIONS.md`` — contradicting the project rule that
those two documents describe THIS repo's real patterns and footguns, not generic
advice, and reproducing the shipping-docs-verbatim footgun.

Pointing the source at ``espalier/assets/seed/`` puts the stubs OUTSIDE that
rglob, so both contracts keep full strength and neither needs an exception.
``espalier/assets/memory/README.md`` is the standing precedent, and the precedent
holds on the SECOND half of what this note used to say rather than the first: it
evades the same two contracts purely by living outside ``espalier/assets/docs/``.

⚠ CORRECTED 2026-08-20. This used to read "a hand-authored asset with no
source-tree twin". The twin exists and is byte-identical — driven,
``cmp espalier/assets/memory/README.md memory/README.md`` returns 0, 2751 bytes
each. The location, not the absence of a twin, is what puts it outside both
contracts, so the argument above is unaffected; the reason offered for it was
wrong. It matters because this sentence is cited as the precedent for pointing a
future asset source at ``espalier/assets/seed/``, and a design decision resting on
a false premise is one nobody re-checks. Note also what the correction exposes:
the pair agrees today and no mirror row, sync script or parity test holds it
there.

Entries are asset-root-relative (``assets_root()`` is the base). A destination
absent from this map keeps today's identity derivation."""


def get_seed_asset_source(dest_relpath: str) -> str:
    """Asset-root-relative source path for a seeded doc's destination.

    Returns the ``_SEED_ASSET_SOURCES`` override when one exists, else the
    destination itself (today's identity derivation). Single source of truth for
    the indirection, so ``cli.py``'s deploy loop and any future consumer resolve
    a seed's body the same way — the same reason ``get_seed_docs`` is shared with
    ``cleanup.py``.
    """
    return _SEED_ASSET_SOURCES.get(dest_relpath, dest_relpath)


SEED_ADAPT_HEADER = (
    "<!-- espalier:seed-doc — Illustrative reference from Espalier-Harness.\n"
    "     The examples below describe the harness's OWN conventions; adapt them\n"
    "     to your repo. This file is yours — unmarked, refreshed on re-init only\n"
    "     while it still matches the copy it was deployed from, and otherwise\n"
    "     left exactly as you left it. -->\n\n"
)
"""Deploy-time preamble for Tier-2 seed docs (``seed_needs_adapt_header``).
Uses the ``espalier:seed-doc`` token — deliberately NOT ``espalier:managed``,
so ``has_managed_marker`` does not treat a seeded doc as harness-owned and
``clean-generated`` never deletes it (it stays operator-editable). Lived in
``cli`` until 2026-09-05; it is part of the rendered body the stamp digests,
so it moved here with the renderer (DEF-696). The last sentence states the
rule ``cli._write_seed`` implements, in the one wording that survives every
corner: a stamped copy whose body still matches its stamp is refreshed when
the packaged bytes change (an edit reverted byte for byte matches again), an
edited or unstamped copy is preserved. Until 2026-09-11 it promised "never
overwritten on re-init", which the refresh path had made false (DEF-432);
the two Tier-3 stubs and the reflect skill quote this wording, pinned by
``tests/test_cli.py``."""


def seed_stamp_line(post_stamp_text: str) -> str:
    """Render the seed-version stamp for ``post_stamp_text`` (the bytes that will
    follow it on disk). The version segment is informational; refresh decisions
    key on the hash, not the version, so a version bump alone never churns a
    byte-identical doc. The token and the regex that reads it back
    (``managed_markers.SEED_STAMP_RE``) share one owner."""
    digest = hashlib.sha256(post_stamp_text.encode("utf-8")).hexdigest()
    return f"<!-- {SEED_STAMP_TOKEN} v{__version__} sha256:{digest} -->\n"


def render_seed_body(dest_relpath: str) -> str:
    """The bytes ``init`` writes BELOW the stamp for the seed at ``dest_relpath``:
    the Tier-2 adapt header when the seed takes one, then the packaged asset.

    This is THE renderer -- ``cli._deploy_seed_docs`` writes exactly this
    string under ``seed_stamp_line`` of it, and ``doctor`` prints that same
    stamp for a seed whose first line is gone (DEF-696), so the two cannot
    disagree by construction; ``tests/test_managed_inventory.py`` pins the
    printed stamp byte-equal to the first line a driven ``init`` wrote, for
    every seed, on the real adopter tree. The asset is read straight from the
    ``assets_root()`` Traversable (wheel-safe; a read needs no ``as_file``
    materialisation) through ``get_seed_asset_source``, never from the
    destination path -- the two grounding stubs live under
    ``espalier/assets/seed/``, not beside their destination.
    """
    source_rel = get_seed_asset_source(dest_relpath)
    text = assets_root().joinpath(*source_rel.split("/")).read_text(encoding="utf-8")
    header = SEED_ADAPT_HEADER if seed_needs_adapt_header(dest_relpath) else ""
    return header + text


def render_seed_stamp(dest_relpath: str) -> str:
    """The exact first line ``init`` writes today for the seed at
    ``dest_relpath`` -- ``seed_stamp_line`` over ``render_seed_body``. What
    ``doctor`` prints so an adopter who removed it can paste it back with no
    git, no ``head`` and no committed copy: above an edited body its digest
    never matches, so every later ``init`` and ``upgrade`` preserves the file;
    above a body that still matches today's packaged bytes it restores the
    untouched status, so the next packaged drift refreshes it again. It is
    today's digest, so a legacy copy of an OLDER packaged body is kept from
    then on but stops receiving packaged updates -- delete-then-``init`` is
    that copy's path to current bytes."""
    return seed_stamp_line(render_seed_body(dest_relpath))


_INSTALL_CI_ARTIFACT_REL_PATHS: tuple[str, ...] = (
    "tools/cc/ci_guard.py",
    ".github/workflows/harness-guard.yml",
    ".github/workflows/harness-guard.yml.new",
)
"""Paths ``espalier install-ci`` writes (``cli.py::cmd_install_ci``) that are NOT
in ``get_managed_public_files`` -- they are install-ci-specific, not init-deployed
public surface, so they stay out of PACK_MANIFEST / doctor / the surface gate.
Consumed by ``cleanup.py``'s undeploy accounting so a teardown does not silently
orphan them. Includes the conditional ``harness-guard.yml.new`` parity twin
install-ci parks when the host already ships a differing ``harness-guard.yml``.

This is a hand-maintained MIRROR of ``cmd_install_ci``'s write set, not a shared
owner -- ``cmd_install_ci`` hard-codes its own destinations and does not read this
tuple. The two must be kept in sync BY HAND; a divergence (a future install-ci
write not added here) silently re-orphans the new artifact on uninstall -- the
exact class ``cleanup.py`` reconciles. That sync is pinned mechanically by
``tests/test_cleanup.py::TestInstallCiArtifactDriftPin`` (runs the real
``cmd_install_ci`` across both branches and asserts its observed CI writes equal
this tuple), so the mirror cannot silently drift.

``.espalier/integrity.json`` (install-ci re-seeds it) is deliberately NOT here -- it
is already covered by ``_LOCAL_RUNTIME_REL_PATHS`` (preserved, not orphaned)."""


def get_install_ci_artifacts() -> tuple[str, ...]:
    """Paths ``espalier install-ci`` writes OUTSIDE the public managed inventory,
    consumed by ``cleanup.py`` so an uninstall accounts for each present artifact
    (marked -> deleted; unmarked -> preserved_user) instead of silently orphaning
    it. See ``_INSTALL_CI_ARTIFACT_REL_PATHS``.
    """
    return _INSTALL_CI_ARTIFACT_REL_PATHS


_PUBLIC_PREFIXES: tuple[str, ...] = (
    *(f".claude/{kind}/" for kind in surface_contract.CLAUDE_SURFACE_KINDS),
    "cc/",
    "tools/cc/",
)
"""Directory roots where Espalier deploys public managed surface.

Fine-grained public-deploy surface — deliberately NOT the same as
managed_paths.owned_roots (a coarse top-level ownership summary). Purpose-scoped
divergence; do not collapse the two."""


_PACKAGED_ROOT_DOCS: tuple[str, ...] = (
    "CLAUDE.md",
    _MEMORY_FILENAME,
    "docs/CONVENTIONS.md",
    "docs/SHARP_EDGES.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
)
"""Root-level docs ``init`` writes or seeds into the adopter's tree.

Conditional on disk presence in ``get_managed_public_files``. The list
lives here as the SoT so ``render_pack_manifest`` is a thin consumer of
the inventory rather than carrying its own hardcoded copy.

Every member is a file the harness itself puts on disk: the two scaffolds
``init`` renders (``CLAUDE.md``, the memory file) and the four convention
docs it seeds. ``README.md`` is deliberately absent. It sat here until
2026-09-11 because it ships in the harness's own *package*, but this list
answers a different question -- what the harness OWNS in the tree it was
run on -- and ``init`` never writes an adopter's README. Its presence made
the manifest an adopter received claim their own README as shipped harness
surface while ``clean-generated`` reported the same file as a preserved user
file (DEF-556). A root doc belongs here only if ``init`` writes it.

Distinct from ``STANDARD_MANAGED_ROOT_DOCS`` (managed_paths.py) and
from ``self_host_managed_paths`` (in managed_paths.py). All three
describe overlapping subsets of "what the harness owns" but for
different consumers:

- ``_PACKAGED_ROOT_DOCS`` (this constant) → the root docs ``init`` writes,
  consumed by ``render_pack_manifest`` and PACK_MANIFEST.txt. Excludes
  ``.claudeignore`` (it is config the user might author) and ``README.md``
  (the adopter's own).
- ``STANDARD_MANAGED_ROOT_DOCS`` → the root-doc members of the harness's
  *managed-path inventory* (``managed_paths.py::managed_paths_from_plan``
  generic-mode + ``self_host_managed_paths``): what the harness treats as
  its own to protect/track *when present*. NOT an ``init`` deploy list —
  ``init``/``deploy_harness`` do not write ``.claudeignore`` or the
  ``CONVENTIONS``/``SHARP_EDGES``/``CHEAT-SHEET``/``TASK_RECIPES`` members
  to an adopter (the init seed set is the separate ``_SEED_DOC_REL_PATHS``).
  Includes ``.claudeignore`` (harness-owned config it protects); excludes
  ``README.md`` (left user-editable).
- ``self_host_managed_paths`` → the self-host managed-path inventory that
  ``doctor``'s ownership report reads. It is NOT write_guard's protected
  zone: that lives in ``tools/cc/hooks/_protected_zones.py``, names neither
  ``.claudeignore`` nor any ``.claude/`` kind, and cannot import this
  package. It reads ``STANDARD_MANAGED_ROOT_DOCS``, so it claims
  ``.claudeignore`` as harness-owned and treats ``README.md`` as the
  adopter's.

The divergence is intentional and pinned by
``test_lifecycle_parity.TestKnownRootDocsDelta``: ``.claudeignore`` is
owned but not shipped, and ``README.md`` is in neither view."""


# ── Public APIs (pack §1) ─────────────────────────────────────────────────


def get_managed_public_files(
    repo_root: Path,
    plan: dict | None = None,
) -> list[str]:
    """Return Espalier-Harness's public managed file inventory for ``repo_root``.

    Sourced from the package SoT (``asset_inventory.get_packaged_surface``)
    plus the canonical hook scripts, hook helpers, and generated cc/ docs.
    Excludes:

    - Local runtime files (``settings.json``, integrity manifest, ``reports/*.json``)
    - Local-only files (blueprints, execution plan, surface handoff, ``settings.local.json``)
    - User-authored files alongside the canonical surface (cleanup discovers
      these separately via prefix scan + marker check)

    The list is what ``PACK_MANIFEST.txt`` enumerates and what
    ``clean-generated`` operates on as its starting candidate set.

    """
    files: set[str] = set()

    # Package SoT — canonical commands, skills, agents.
    surface = get_packaged_surface()
    for cmd_rel in surface.commands.paths:
        files.add(f".claude/commands/{cmd_rel}")
    for skill_rel in surface.skills.paths:
        files.add(f".claude/skills/{skill_rel}")
    for agent_rel in surface.agents.paths:
        files.add(f".claude/agents/{agent_rel}")

    # harness_config.json is an informational recommendation file, not a
    # deploy spec. Agents do not appear in the managed inventory (they are
    # not deployed by init).

    # Hook entries + helpers (always-managed harness internals)
    files.update(get_hook_entry_files())
    files.update(get_hook_helper_files())

    # Non-hook tool scripts deployed by ``cli.INIT_TOOL_SCRIPTS`` —
    # cognitive_blueprint, execution_plan, reflect_protocol, session_resume.
    # Consuming ``STANDARD_MANAGED_TOOLS`` keeps self-host mode in agreement
    # with generic-plan mode on the tools that ``init`` deploys.
    files.update(STANDARD_MANAGED_TOOLS)

    # Generated cc/ docs (rendered by render_surface)
    files.update(get_generated_docs())

    # Root-level scaffold docs that ship if they exist (CLAUDE.md / ESPALIER_MEMORY.md
    # are user-edited after init; cleanup preserves them by marker check, but
    # PACK_MANIFEST still lists them so operators see what was shipped).
    for rel in _PACKAGED_ROOT_DOCS:
        if (repo_root / rel).exists():
            files.add(rel)

    return sorted(files)


def get_managed_public_prefixes() -> tuple[str, ...]:
    """Directory prefixes where public managed files live."""
    return _PUBLIC_PREFIXES


def get_local_runtime_files(repo_root: Path) -> list[str]:
    """Files generated locally on init (not part of public managed surface).

    Filtered to those that exist on disk so callers can distinguish
    "expected runtime artifact" from "missing deployment".
    """
    return sorted(
        rel for rel in _LOCAL_RUNTIME_REL_PATHS
        if (repo_root / rel).exists()
    )


def local_runtime_rel_paths() -> tuple[str, ...]:
    """Every local-runtime path ``init`` produces, unfiltered by existence.

    The sibling ``get_local_runtime_files`` filters to what is on disk, which is
    right for a diagnostic ("is this a missing deployment or an expected runtime
    artifact?") and wrong for documentation: a doc must describe what ``init``
    writes, not what happens to exist in the tree it was rendered from. Reading
    the existence-filtered list into prose is the dev-tree-is-not-the-artifact
    class, so the two callers get two accessors over one tuple.
    """
    return _LOCAL_RUNTIME_REL_PATHS


def get_local_runtime_prefixes() -> tuple[str, ...]:
    """Directory roots the harness's runtime writes into, repo-root relative.
    See ``_LOCAL_RUNTIME_PREFIXES``."""
    return _LOCAL_RUNTIME_PREFIXES


def local_state_on_disk(repo_root: Path) -> list[str]:
    """Every PRESENT file the harness's runtime wrote outside the deployed
    surface, minus what the adopter has committed.

    Three sources, each already the canon for its own question: the exact
    local-runtime paths (``init``'s per-install artifacts), the surface
    contract's exact local-only paths (per-session state) and its
    ``ADOPTER_RUNTIME_GENERATED`` list (files deployed code creates later,
    each with a cited writer -- ``cc/_working_summary.md`` is the one that
    sits directly under ``cc/``, which no prefix here covers), plus every file
    under a local-runtime prefix. A path in git's index is then removed: an
    adopter who committed ``.espalier/freshness.json`` on purpose has made it
    theirs, and naming it as disposable runtime state would send them to
    delete their own canon. On a tree where git cannot answer nothing is
    subtracted.

    This is the set an uninstall leaves behind on purpose and must therefore
    NAME. ``get_local_runtime_files`` answers a narrower question (which of
    the five per-install artifacts exist, for ``doctor``); an accounting that
    read only that list left the manifest write-lock, the session flags and a
    blueprint chain absent from every bucket of the uninstall report, so the
    adopter reconciling the report against ``ls`` could not tell a forgotten
    file from a deliberately kept one (DEF-410d, driven 2026-09-11; the
    working summary was the reviewers' second driven miss the same day).
    Read only, and never a delete list: a file being ours to NAME is not the
    same decision as it being ours to REMOVE.
    """
    root = Path(repo_root)
    found: set[str] = set()
    exact = (
        *_LOCAL_RUNTIME_REL_PATHS,
        *surface_contract.get_local_only_paths(),
        *surface_contract.ADOPTER_RUNTIME_GENERATED,
    )
    for rel in exact:
        if (root / rel).is_file():
            found.add(rel)
    for prefix in _LOCAL_RUNTIME_PREFIXES:
        base = root / prefix.rstrip("/")
        if not base.is_dir():
            continue
        for path in safe_rglob(base):
            if path.is_file():
                found.add(path.relative_to(root).as_posix())
    committed = surface_contract.tracked_paths(root) or set()
    return sorted(found - committed)


def is_render_artifact(rel: str) -> bool:
    """True when ``rel`` is a file ``init`` or ``merge-settings`` rendered
    beside the adopter's settings. See ``_RENDER_ARTIFACT_REL_PATHS``."""
    probe = rel.replace("\\", "/")
    if probe in _RENDER_ARTIFACT_REL_PATHS:
        return True
    parent, _, name = probe.rpartition("/")
    return parent == ".claude" and settings_backup_rung(name) is not None


def get_render_artifacts(repo_root: Path) -> list[str]:
    """Render artifacts present on disk, repo-root relative and sorted.

    Non-recursive by construction: the artifacts sit beside
    ``.claude/settings.json``, and a deeper ``.new`` or ``.bak`` is not one
    the harness wrote."""
    claude_dir = Path(repo_root) / ".claude"
    if not claude_dir.is_dir():
        return []
    try:
        entries = list(claude_dir.iterdir())
    except OSError:
        return []
    return sorted(
        f".claude/{entry.name}"
        for entry in entries
        if entry.is_file() and is_render_artifact(f".claude/{entry.name}")
    )


def unstamped_seed_docs(repo_root: Path) -> list[str]:
    """Repo-relative paths of the PRESENT seed docs carrying no first-line
    ``espalier:seed-version`` stamp, in seed-list order.

    A seed is excluded from the fingerprint, the docs surface and the
    grounding floor by that stamp, never by its path (an edited seed is still
    harness provenance; the same path unstamped IS the adopter's doc). So an
    adopter who deletes the stamp to tidy a header gets the day-one noise back
    -- ``Large files detected`` over a 464 KB catalog they did not write -- and
    until 2026-09-05 only ``upgrade`` counted the state (DEF-691). Hoisted here
    from ``cli`` because ``doctor`` must not import ``cli``.

    The predicate is ``path_has_seed_stamp`` -- the fingerprint's OWN (a
    256-byte peek, replacement decoding, BOM and CRLF folded) -- so this list
    and the fingerprint's exclusion cannot disagree: the first cut read the
    whole file strictly and skipped a seed a Windows editor had resaved as
    cp1252, under-counting exactly the doc that had re-entered the fingerprint
    (failure-mode pass, driven). A seed that is gone is not listed: a deleted
    file re-enters nothing.
    """
    return [
        rel for rel in get_seed_docs()
        if (Path(repo_root) / rel).is_file() and not path_has_seed_stamp(Path(repo_root) / rel)
    ]


def count_unstamped_seed_docs(repo_root: Path) -> int:
    """``len(unstamped_seed_docs(repo_root))`` -- what ``upgrade`` prints."""
    return len(unstamped_seed_docs(repo_root))


def get_seed_docs() -> tuple[str, ...]:
    """Convention/doc scaffolds ``init`` seeds (unmarked, operator-editable,
    refreshed only while untouched), consumed by BOTH ``cli.py``'s deploy loop
    and ``cleanup.py``'s undeploy accounting so the two cannot drift.
    """
    return _SEED_DOC_REL_PATHS


def get_local_only_files() -> tuple[str, ...]:
    """Local-only files that must never appear in PACK_MANIFEST.

    Sources from ``surface_contract.get_local_only_paths`` so the
    answer stays in lockstep with the static contract.
    """
    return surface_contract.get_local_only_paths()


def get_generated_docs() -> tuple[str, ...]:
    """The cc/ surface docs Espalier renders during init.

    These are public managed files (subset of get_managed_public_files)
    but called out separately because render_pack_manifest and the
    surface gate enumerate them.
    """
    return tuple(STANDARD_MANAGED_CC_DOCS)


def get_hook_entry_files() -> tuple[str, ...]:
    """Hook entry scripts under tools/cc/hooks/ (e.g., write_guard.py)."""
    return tuple(
        f"tools/cc/hooks/{name}"
        for name in surface_contract.get_canonical_hook_scripts()
    )


def get_hook_helper_files() -> tuple[str, ...]:
    """Hook helper modules under tools/cc/hooks/ (e.g., _hook_utils.py)."""
    return tuple(f"tools/cc/hooks/{name}" for name in _HOOK_HELPERS)
