# pytest-marker: default-unit
"""TP-189 ARCH-1: shipped recipe bodies must not reference a tools/cc/*.md
file that ``espalier init`` never deploys.

The deployed ``reflect`` skill and ``implement-pack`` command used to instruct
the adopter's Claude to read ``tools/cc/reasoning_review_checklist.md`` /
``...pack_artifact_checklist.md`` and paste its contents into a sub-agent
prompt. Neither checklist ships -- no ``.md`` deploys under ``tools/cc/`` -- so
on a fresh adopter the reference dangled. The checklists are now inlined into
the bodies; this gate keeps any future ``tools/cc/*.md`` reference in a shipped
body honest: it must name a file the deploy set actually delivers, or the
content must be inlined. The contract **prevents** that dangling-reference bug
class from regressing as new shipped recipes are added.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The deploy SOURCE for ALL shipped asset bodies -- what reaches an adopter via
# init/fuse. Covers claude/ (agents/commands/skills) AND the docs/ + memory/ +
# CLAUDE.md template bodies cmd_init seeds (TP-189 adversarial C2: scanning only
# claude/ left those other shipped bodies uncovered). The runtime .claude/ and
# the dogfooding fixture are held byte-identical by the parity tests, so
# scanning the asset source is sufficient. (The runtime-generated root CLAUDE.md
# from _build_claude_md is out of scope here -- it is Python-generated, not a
# static body, and carries no tools/cc/*.md refs.)
_ASSET_DIR = REPO_ROOT / "espalier" / "assets"


def _shipped_asset_bodies() -> list[Path]:
    """Every markdown body under the asset tree that `init` actually ships.

    DERIVED from the deploy inventory: the `.claude/` triplet mirror (every
    file under `assets/claude/`) plus the asset source of every seed doc
    (`managed_inventory.get_seed_asset_source`, which is how the Tier-3
    stubs under `assets/seed/` are reached). A plain ``rglob("*.md")`` also
    scans `assets/CLAUDE.md`, the maintainer folder router for this tree --
    a doc that tells a contributor to run `scripts/sync_claude_mirrors.py`
    and is never deployed -- and the invocation gate below read that as a
    shipped body telling an adopter to run a script they lack.
    """
    from espalier import managed_inventory

    bodies = set((_ASSET_DIR / "claude").rglob("*.md"))
    for rel in managed_inventory.get_seed_docs():
        src = _ASSET_DIR / managed_inventory.get_seed_asset_source(rel)
        if src.suffix == ".md" and src.is_file():
            bodies.add(src)
    return sorted(bodies)

# A ``tools/cc/<path>.md`` reference embedded anywhere in body text.
_REF_RE = re.compile(r"tools/cc/[\w./-]+\.md")

# tools/cc/*.md refs that are intentionally allowed in a shipped body even
# though the file is not deployed. Each pairs a path with a reason. These are
# NOT the ARCH-1 "read the file and paste its contents" dependency (that class
# must be inlined) -- they are soft enumerations of self-host example paths in
# agent bodies, which ship as "starting examples drawn from Espalier-Harness"
# (CLAUDE.md) that adopters adapt. A missing router degrades to a no-op sweep.
_ALLOWED_UNDEPLOYED_REFS: dict[str, str] = {
    "tools/cc/hooks/CLAUDE.md": (
        "self-host folder-router example in the docs-maintainer agent's "
        "memory-rename sweep list (alongside task-packs/, espalier/scanners/, "
        "espalier/assets/ routers); soft enumeration, not a paste-the-file "
        "dependency; agent bodies are adapter-adapted starting examples"
    ),
}


def _deployed_tools_cc_md() -> frozenset[str]:
    """tools/cc/*.md paths ``espalier init`` actually deploys (currently none).

    Anchored to the deploy constants in ``espalier.cli`` -- NOT filesystem
    discovery -- so a stray ``.md`` left under ``tools/cc/`` can't silently
    bless a dangling reference.
    """
    from espalier.cli import INIT_HOOK_SCRIPTS, INIT_TOOL_SCRIPTS

    return frozenset(
        p for p in (*INIT_HOOK_SCRIPTS, *INIT_TOOL_SCRIPTS) if p.endswith(".md")
    )


def test_shipped_asset_bodies_reference_no_undeployed_tools_cc_md() -> None:
    deployed = _deployed_tools_cc_md()
    offenders: list[str] = []
    for path in _shipped_asset_bodies():
        text = path.read_text(encoding="utf-8")
        for ref in _REF_RE.findall(text):
            if ref not in deployed and ref not in _ALLOWED_UNDEPLOYED_REFS:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel} -> {ref}")
    assert not offenders, (
        "shipped asset body references a tools/cc/*.md file that "
        "`espalier init` does not deploy (the adopter hits a dangling "
        "reference). Inline the content, or add the file to the deploy "
        "set, or allowlist it with a reason in _ALLOWED_UNDEPLOYED_REFS:\n  "
        + "\n  ".join(offenders)
    )


def test_every_allowlist_entry_has_a_reason() -> None:
    """An allowlisted ref without a documented reason is a silent escape
    hatch -- mirror TP-129's allowlist-hygiene contract."""
    blank = [k for k, v in _ALLOWED_UNDEPLOYED_REFS.items() if not v.strip()]
    assert not blank, f"allowlist entries missing a reason: {blank}"


# An EXECUTION reference in a shipped body -- ``python tools/cc/x.py``,
# ``python scripts/y.py``, ``pytest tests/test_z.py``. Scoped to the
# invocation form -- NOT bare path mentions -- so illustrative example paths
# in agent bodies are not flagged; only "run this script" dependencies, which
# MUST be deployed or disclaimed, or the adopter hits No-such-file.
# (R2:SISTER-PROBE: /implement-pack step 0-C invoked an undeployed
# tools/cc/sister_site_probe.py on every fresh adopter; the .md sibling gate
# above covers paste-the-file refs, not execution.)
#
# The population is DERIVED by ``_doc_pointers.exec_refs`` -- every
# interpreter invocation, whatever directory the script lives in. This was a
# hand-written ``tools/cc/`` prefix (DEF-622), and the count of invocations
# it could not see GREW while the defect stood: six ``scripts/`` scripts
# across ``/handoff`` and ``/implement-pack`` that no adopter has. The
# mechanism was never the defect; the enumeration was.
#
# The deploy set stays anchored to the constants in ``espalier.cli``, not to
# filesystem discovery, so a script present in the tree but absent from the
# deploy set cannot bless itself. A self-host script is allowed when the body
# says so where the reader reads it -- a ``#`` comment in the same fence, a
# marker within two lines of a prose mention, or a ``[ -f <path> ]`` guard in
# the fence -- the same vocabulary `tests/test_adopter_pointer_resolution.py`
# reads (imported, never restated), so the two gates cannot disagree about
# what counts as disclaimed. That gate resolves the same invocations against a
# driven adopter tree; this one keeps the deploy-constant anchor.


def _deployed_py() -> frozenset[str]:
    """Scripts ``espalier init`` actually deploys, from the deploy constants."""
    from espalier.cli import INIT_HOOK_SCRIPTS, INIT_TOOL_SCRIPTS

    return frozenset(
        p for p in (*INIT_HOOK_SCRIPTS, *INIT_TOOL_SCRIPTS) if p.endswith(".py")
    )


def test_shipped_asset_bodies_execute_no_undeployed_script() -> None:
    """A shipped body that tells Claude to run a script must name one ``init``
    deploys, or say beside the command that the reader may not have it."""
    from _doc_pointers import exec_refs
    from tests.test_adopter_pointer_resolution import (
        _NOT_POINTERS,
        _invocation_is_marked,
    )

    deployed = _deployed_py()
    declared = {(e.carrier, e.target) for e in _NOT_POINTERS if e.literal is None}
    offenders: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path in _shipped_asset_bodies():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        # The deployed relpath is what the sibling gate's rows are keyed on:
        # `assets/claude/<kind>/x.md` lands at `.claude/<kind>/x.md` (the dot
        # is the deploy's, not the asset tree's); every other asset keeps its
        # relpath.
        deployed_rel = rel.removeprefix("espalier/assets/")
        if deployed_rel.startswith("claude/"):
            deployed_rel = "." + deployed_rel
        for ref in exec_refs(text):
            if ref.file in deployed or ref.guarded:
                continue
            if _invocation_is_marked(text, ref) or (deployed_rel, ref.file) in declared:
                continue
            if (rel, ref.file) in seen:
                continue
            seen.add((rel, ref.file))
            offenders.append(f"{rel}:{ref.lineno} -> {ref.file}")
    assert not offenders, (
        "shipped asset body runs a script `espalier init` does not deploy, with "
        "nothing beside the command saying so (the adopter hits No such file or "
        "directory). Add the script to INIT_HOOK_SCRIPTS/INIT_TOOL_SCRIPTS, guard "
        "the fence on the file (`if [ -f scripts/x.py ]; then ... fi`), or say "
        "'Espalier source repo only -- not deployed by init' in a comment in the "
        "same fence or within two lines of the mention:\n  "
        + "\n  ".join(offenders)
    )


def test_the_exec_population_is_not_vacuous() -> None:
    """The derived population must still see the invocations it exists for:
    at least one deployed ``tools/cc`` script and at least one disclaimed
    self-host script, or a regex change has silently emptied the gate."""
    from _doc_pointers import exec_refs

    deployed = _deployed_py()
    seen_deployed = seen_selfhost = False
    for path in _shipped_asset_bodies():
        for ref in exec_refs(path.read_text(encoding="utf-8")):
            if ref.file in deployed:
                seen_deployed = True
            elif ref.file.startswith("scripts/"):
                seen_selfhost = True
    assert seen_deployed and seen_selfhost, (
        f"exec population lost a class: deployed={seen_deployed} "
        f"self-host={seen_selfhost}"
    )
