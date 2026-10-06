"""Build the tree an adopter actually receives, by driving ``espalier init``.

**Why this exists.** Every doc-pointer checker in this suite resolves against
one of three oracles, and none of them is the adopter's tree:

- the self-host worktree (``test_ladder_claudemd_pointers``,
  ``test_md_heading_anchors``, ``test_doc_source_citations``,
  ``reflection.py`` over ``REPO_ROOT``);
- a *path-string set* derived from ``get_seed_docs()`` with no bodies behind
  it (``test_deploy_doc_parity`` Arm A, ``test_shipped_asset_md_refs``);
- a shipping artifact whose ``espalier/assets/**`` templates are then
  allowlisted out *precisely because* they are deploy-context
  (``test_git_archive_parity.ARTIFACT_LINK_ALLOWLIST``,
  ``test_wheel_payload``).

Four of those scope-outs defer the obligation by name to a gate that did not
exist. This module is the missing oracle.

**Why not ``initialized_repo_root``.** That fixture (``conftest.py``) clones
*this repo* and runs ``init`` over the copy. The self-host copies carry no seed
stamp, so the seed writer preserves them (only a stamped, untouched copy is
refreshed), the self-host ``docs/SHARP_EDGES.md`` (4,295 lines) and
``docs/CONVENTIONS.md`` (1,999 lines) survive and the Tier-3 stubs are **never
written**. A pointer
gate resolved against that tree is green because this repo's own content is
already sitting there -- born-weak in the precise sense of ledger class C5.
``assert_is_adopter_tree`` below refuses that tree by name rather than
trusting a comment to keep the next person off it.

The repo is FOREIGN on purpose -- a small third-party project, not a
harness checkout -- because that is the only shape in which a seed stub is
the thing on disk.

**Why ``install-ci`` runs too, and why that is not optional.** ``init`` is only
half the artifact. ``tools/cc/ci_guard.py`` reaches an adopter through
``cmd_install_ci`` (``cli.py``), never through ``cmd_init`` -- so a tree built
from ``init`` alone does not contain the single most adopter-visible deny
message the harness emits, the one printed into a failing CI log. A pointer
gate resolved against an init-only tree reports green on ``ci_guard.py``
because it never read the file, which is the born-weak shape (ledger §C5) this
module was written to end, arriving one layer down. DEF-503 was claimed closed
against exactly that blind spot.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from _stack_trees import ADOPTER_PREFIX, ADOPTER_STACKS, write_stack
from espalier import managed_inventory
from espalier.cli import cmd_init, cmd_install_ci

# The two Tier-3 seeds whose destination path collides with a far larger
# self-host document of the same name. Their line counts are the mechanical
# tell that `init` wrote the stub rather than a self-host body surviving.
_STUB_SEEDS = ("docs/SHARP_EDGES.md", "docs/CONVENTIONS.md")

# A stub body is small; the self-host twins are 1,999 and 4,295 lines. Any
# threshold in between separates them -- this one is deliberately loose so
# ordinary growth of a seed stub does not trip it.
_MAX_STUB_LINES = 200


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    )


#: The build depths ``build_adopter_tree`` takes, cheapest first.
TREE_DEPTHS: tuple[str, ...] = ("files", "git", "adopter")


def build_adopter_tree(
    dest: Path, *, stack: str = "python", tree: str = "adopter", branch: str = "main",
) -> Path:
    """Create a foreign repo of ``stack`` under ``dest`` and, by default, run
    ``espalier init`` and ``install-ci`` on it. Returns the tree.

    ``stack`` names an adopter row of ``tests/_stack_trees.py`` without its
    prefix (``stack="node"`` writes ``adopter-node``; ``ADOPTER_STACKS`` lists
    them). The default row is the small, ordinary Python project this builder
    has always written, enough for the fingerprinter to classify a layout, with
    no harness vocabulary anywhere in it.

    ``tree`` is the depth:

    * ``"files"`` writes the row and nothing else;
    * ``"git"`` adds a real ``git init`` on ``branch``, an identity and the
      initial commit;
    * ``"adopter"`` (the default) adds ``init`` and ``install-ci`` as an adopter
      runs them, then checks the result is an adopter tree.

    Real ``git init``/``add``/``commit`` rather than the bare ``.git`` mkdir
    the other init tests use: ``init``'s gitignore-ownership and
    tracked-conflict paths shell out to git, and a fake ``.git`` sends them
    down their degraded branch. The full depth is not cheap: about 5 s per tree
    on the Windows host (4.5 to 5.9 s measured, 2026-10-06), nearly all of it
    ``init``. So build it once per module or session, and take a shallower
    depth when the test does not need the harness installed.
    """
    if stack not in ADOPTER_STACKS:
        raise ValueError(f"unknown stack {stack!r}; expected one of {ADOPTER_STACKS}")
    if tree not in TREE_DEPTHS:
        raise ValueError(f"unknown depth {tree!r}; expected one of {TREE_DEPTHS}")
    root = dest / "tree"
    root.mkdir(parents=True)
    write_stack(root, ADOPTER_PREFIX + stack)
    if tree == "files":
        return root

    _git(root, "init", "-q", "-b", branch, ".")
    _git(root, "config", "user.email", "adopter@example.invalid")
    _git(root, "config", "user.name", "Adopter")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    if tree == "git":
        return root
    return _install(root)


def _install(tree: Path) -> Path:
    """Run ``init`` and then ``install-ci`` on ``tree``, as an adopter does."""
    rc = cmd_init(argparse.Namespace(repo=str(tree), config=None))
    if rc != 0:
        raise AssertionError(f"espalier init returned {rc} on the adopter tree")

    # The CI leg, in the documented order: `install-ci` re-seeds the integrity
    # manifest `init` wrote, so running it second is the adopter's real
    # sequence rather than a convenient one.
    rc = cmd_install_ci(argparse.Namespace(repo=str(tree)))
    if rc != 0:
        raise AssertionError(
            f"espalier install-ci returned {rc} on the adopter tree"
        )

    assert_is_adopter_tree(tree)
    return tree


def assert_is_adopter_tree(tree: Path) -> None:
    """Refuse a tree that is really a self-host checkout with ``init`` applied.

    This is the fixture's own earn-the-red: pointed at ``initialized_repo_root``
    it raises here instead of quietly passing every downstream pointer check on
    the strength of content no adopter receives.
    """
    for rel in _STUB_SEEDS:
        path = tree / rel
        if not path.is_file():
            raise AssertionError(
                f"{rel} is absent from the driven init tree; the deploy set no "
                f"longer matches managed_inventory.get_seed_docs()."
            )
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if lines > _MAX_STUB_LINES:
            raise AssertionError(
                f"{rel} is {lines} lines on the 'adopter' tree, over the "
                f"{_MAX_STUB_LINES}-line stub ceiling. This tree is a self-host "
                f"checkout with init applied, not an adopter install: seeds are "
                f"skip-if-exists, so the self-host body survived and the Tier-3 "
                f"stub was never written. Resolving pointers here would pass on "
                f"content no adopter receives."
            )
    # The harness's own marker file must NOT be here -- a self-host tree is
    # identified by espalier/ being importable from the root.
    if (tree / "espalier" / "managed_inventory.py").is_file():
        raise AssertionError(
            "the driven tree contains espalier/ -- this is a harness checkout, "
            "not a foreign adopter repo."
        )
    # The CI leg must be present, for the same reason the stub check above
    # exists: a MISSING carrier reads as "nothing dangling" rather than "the
    # population lost a file". `ci_guard.py` is the only adopter-visible
    # deny message that prints into a CI log; if install-ci ever stops writing
    # it, the code-carrier arm goes vacuous for the highest-signal file on the
    # tree and every pointer gate downstream reports green.
    #
    # Derived from `get_install_ci_artifacts()` rather than named here, minus
    # the `.new` parity twin -- that one is CONDITIONAL by construction
    # (install-ci parks it only when the host already ships a DIFFERING
    # harness-guard.yml, which a fresh adopter repo does not).
    for rel in managed_inventory.get_install_ci_artifacts():
        if rel.endswith(".new"):
            continue
        if not (tree / rel).is_file():
            raise AssertionError(
                f"{rel} is absent from the driven tree -- `install-ci` did not "
                f"run, or no longer writes it. Resolving pointers here would "
                f"skip the CI deny messages entirely and pass for that reason."
            )


def deployed_markdown(tree: Path) -> list[Path]:
    """Every markdown file `init` left on the adopter's tree, sorted."""
    return sorted(
        p for p in tree.rglob("*.md")
        if ".git/" not in p.relative_to(tree).as_posix() + "/"
    )


def deployed_python(tree: Path) -> list[Path]:
    """Every ``.py`` file espalier put on the adopter's tree, sorted.

    DERIVED from the deploy inventories, never a ``tools/cc/**`` glob. The
    tree also holds the fixture's own demo package (``src/demo/app.py``,
    ``tests/test_app.py``) -- props, not harness output -- and a glob would
    scan them, so a stray ``.md`` mention in a fixture file would read as a
    harness defect. Deriving from ``get_managed_public_files`` +
    ``get_install_ci_artifacts`` also means a newly-deployed script joins the
    population the moment the inventory lists it, with nobody editing this
    function.

    Both inventories are consulted because neither is complete alone:
    ``get_managed_public_files`` covers the ``init`` leg (hook entries,
    helpers, ``STANDARD_MANAGED_TOOLS``) and is blind to ``ci_guard.py``,
    which only ``install-ci`` writes.
    """
    rels = set(managed_inventory.get_managed_public_files(tree))
    rels.update(managed_inventory.get_install_ci_artifacts())
    out: list[Path] = []
    for rel in sorted(rels):
        if not rel.endswith(".py"):
            continue
        path = tree / rel
        if path.is_file():
            out.append(path)
    return out


def expected_seed_docs() -> tuple[str, ...]:
    """The seeded doc destinations, for a population-shape assertion."""
    return tuple(sorted(managed_inventory.get_seed_docs()))
