"""Which roster entries a release export is EXPECTED to lack -- derived, not typed.

Not a test module (leading underscore) -- no marker classification needed.
Pinned by ``tests/test_export_guard.py``, including the must-NOT-trip twin.

A self-expiry arm asserts that every entry of a hand-kept roster still names a
real file: ``_ROTATING_ANCHOR_HOSTS`` and ``_ANCHOR_SCAN_EXCLUDE_DOCS`` in
``test_catalog_self_consistency``, ``EXPECTED_MEMORY_CAP_SITES`` in
``test_documented_claims``, ``RECORD_SURFACES`` in
``test_record_axis_reconciliation``. On the dev tree that IS the arm: an entry
naming a file that is gone is dead judgement the next author extends rather
than prunes. On a release export the tree is pruned by construction, so an
entry naming a pruned file is absent for a reason the arm must not red on,
while an entry naming a shipped file that is missing is still the rot the arm
exists to catch.

ONE oracle for "pruned": the ``export-ignore`` patterns in ``.gitattributes``,
read through ``surface_contract.export_ignore_patterns`` and matched with
``matches_export_ignore`` -- the same source ``is_release_export`` keys on. The
shipping classifier (``classify_release_path``) is deliberately NOT consulted:
measured 2026-09-13 over every tracked path, no path it withholds escapes an
export-ignore pattern, so a classifier clause would forgive nothing that
exists and would forgive a phantom under ``reports/`` for a reason that has
nothing to do with exports.

Why a guard and not a registration. Until 2026-09-13 stage 02 of the release
matrix ran the suite in an extract with no git, where these arms skipped
fail-open on ``if not tracked``; the DEF-670 seed gave the extract git, the arms
ran, and four of them red on exactly this shape. Registering each in
``tests/conftest.py::_FULL_TREE_NODEIDS`` deselects the WHOLE test from the
export run -- the live assertions beside the self-expiry arm included. This
guard keeps those running and narrows only the expectation that cannot hold on
an export. It is inert everywhere else: on the dev tree and on a fresh clone it
returns the empty set, so the arm runs unchanged.

Self-expiry. ``ESPALIER_FULL_TREE_AUDIT=1`` is the one oracle that asks whether
a full-tree suppression still earns its place (``docs/ENV_CATALOG.md``); under
it this guard returns the empty set on an export too, so a roster entry whose
export-forgiveness has lapsed reds there instead of staying forgiven forever.
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from espalier import surface_contract

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The same switch ``tests/conftest.py`` reads to stop ``full_tree`` tests
#: auto-skipping on an export; here it stops this guard forgiving anything.
AUDIT_ENV = "ESPALIER_FULL_TREE_AUDIT"


def pruned_from_this_tree(
    rel_paths: Iterable[str], repo_root: Path = REPO_ROOT,
) -> set[str]:
    """The entries an export of ``repo_root`` does not ship; empty on a dev tree.

    Consulted only when the tree IS an export (``is_release_export``, which
    is positive-confirmation-only and stays False on any uncertainty) and the
    audit switch is off. An entry is pruned when an ``export-ignore`` pattern
    matches it.
    """
    if os.environ.get(AUDIT_ENV):
        return set()
    if not surface_contract.is_release_export(repo_root):
        return set()
    patterns = surface_contract.export_ignore_patterns(repo_root)
    return {
        rel for rel in rel_paths
        if any(surface_contract.matches_export_ignore(rel, pat) for pat in patterns)
    }
