"""Anti-regression: release-surface parity fixture (Pack 6 Task 6-D).

`pre_release.run_cleanliness_gate` and `release_pack.create_release_zip`
both classify paths via `surface_contract`. This test seeds a canonical
synthetic repo tree covering every classification category (internal,
local-only, transient, public), runs both consumers against it, and
asserts they agree on the classification of each sample.

If these tests fail, either:

- A classification function in `surface_contract` moved (update samples to
  match the new semantics), OR
- A consumer silently hardcoded logic that no longer reads the contract
  (fix the consumer — do not weaken the fixture).

The shared-outcome invariant is the value: `pre_release` and `release_pack`
cannot drift without this test catching it.
"""
from __future__ import annotations

# slow-exempt: the only child is a local `git init` + `git add` on a tmp tree
# (tens of milliseconds), which gives the archive builder the index it now
# enumerates; no network, no interpreter spawn.
import subprocess
import zipfile
from pathlib import Path

import pytest

from espalier import pre_release, release_pack, surface_contract


# ---------------------------------------------------------------------------
# Fixture manifest — one sample per classification class
# ---------------------------------------------------------------------------

INTERNAL_SAMPLES = (
    "docs/internal/sample.md",
    "docs/session-archive.md",
    "TASK_PACK_SAMPLE.md",
    "BLUEPRINT_SAMPLE.md",
)

LOCAL_ONLY_SAMPLES = (
    ".claude/settings.local.json",
    "reports/analysis.json",
    "reports/cc_surface_gate.json",
)

TRANSIENT_SAMPLES = (
    "__pycache__/foo.pyc",
    ".DS_Store",
    "dist/wheel.whl",
    "build/lib/x.py",
    ".pytest_cache/README.md",
    ".git/HEAD",
    ".espalier-state/x.json",
)

PUBLIC_SAMPLES = (
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "espalier/x.py",
    "tools/cc/hooks/x.py",
)

ALL_SAMPLES = INTERNAL_SAMPLES + LOCAL_ONLY_SAMPLES + TRANSIENT_SAMPLES + PUBLIC_SAMPLES


def _seed_tree(root: Path) -> None:
    """Create one file per sample path under a git-backed root, and STAGE them.

    The archive is the git index, classified, so the parity these tests pin
    holds on the index branch only if the samples are tracked: a tracked
    `__pycache__/foo.pyc` is what the contract must still refuse, and an
    untracked one never reaches the builder at all. The one sample under
    `.git/` is not written -- `git init` owns that directory, and a hand-made
    `.git/HEAD` turned the root into a repository git could not answer for,
    which sent every consumer test here down the no-index fallback (six
    WARN lines per run, and a parity contract that never touched the branch
    that ships).
    """
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    for rel in ALL_SAMPLES:
        if rel.startswith(".git/"):
            continue
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        # Keep content trivial — classification is path-based, not content-based.
        full.write_text("sample\n", encoding="utf-8")
    # `-f`: this machine's global git ignore excludes `**/.claude/settings.local.json`,
    # and any machine may exclude more; a fixture that lets the global excludes
    # decide what is tracked proves the contract on whatever survived them.
    # Junk must be TRACKED here, or the index never enumerates it.
    subprocess.run(["git", "-C", str(root), "add", "-A", "-f"], check=True, capture_output=True)
    assert surface_contract.tracked_paths(root) is not None, (
        "the seeded tree must answer from its index, or every consumer test in "
        "this module runs on the no-index fallback and pins nothing that ships"
    )


@pytest.fixture
def seeded_tree(tmp_path: Path) -> Path:
    _seed_tree(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Contract-only classification checks (no consumer involvement)
# ---------------------------------------------------------------------------

class TestContractClassifiesFixtureSamples:
    @pytest.mark.parametrize("rel", INTERNAL_SAMPLES)
    def test_internal_samples_classified_internal(self, rel: str):
        assert surface_contract.is_internal_release_leak(rel), (
            f"{rel} should be classified as internal leak"
        )
        assert not surface_contract.is_public_release_allowed(rel), (
            f"{rel} must not be public-release-allowed"
        )

    @pytest.mark.parametrize("rel", LOCAL_ONLY_SAMPLES)
    def test_local_only_samples_classified_local_only(self, rel: str):
        assert surface_contract.is_local_only(rel), (
            f"{rel} should be classified as local-only"
        )

    @pytest.mark.parametrize("rel", TRANSIENT_SAMPLES)
    def test_transient_samples_classified_transient(self, rel: str):
        assert surface_contract.is_transient(rel), (
            f"{rel} should be classified as transient"
        )

    @pytest.mark.parametrize("rel", PUBLIC_SAMPLES)
    def test_public_samples_allowed_public(self, rel: str):
        assert surface_contract.is_public_release_allowed(rel), (
            f"{rel} should be public-release-allowed"
        )
        assert not surface_contract.is_internal_release_leak(rel), (
            f"{rel} public sample must not be an internal leak"
        )


# ---------------------------------------------------------------------------
# Consumer outcomes on the seeded tree
# ---------------------------------------------------------------------------

def _build_and_read_members(seeded_tree: Path) -> set[str]:
    """Build the release zip and return its real member set.

    These tests assert the OUTCOME their names promise -- absence from the
    shipped archive -- rather than membership in ``skipped_entries``, which
    only proves the walker considered the file. The two come apart the moment
    the walker prunes a subtree instead of classifying it: a pruned path is
    correctly absent from the zip while never appearing in the skip list at
    all. Asserting the label instead of the fact makes a pruning change look
    like a regression when the payload has not moved.
    """
    out = seeded_tree / "dist" / "out.zip"
    release_pack.create_release_zip(seeded_tree, out)
    with zipfile.ZipFile(out) as zf:
        return set(zf.namelist())


def _assert_not_shipped(members: set[str], samples: tuple[str, ...], kind: str) -> None:
    # Anti-vacuity guard. ``not any(...)`` over an EMPTY member set passes for
    # free, so a broken walker that shipped nothing at all would satisfy every
    # exclusion assertion below. Pin that the archive is non-empty first --
    # otherwise these tests are strictly weaker than the skipped_entries
    # membership checks they replace.
    assert members, (
        f"release zip has no members at all -- {kind} exclusion assertions "
        "would pass vacuously"
    )
    for rel in samples:
        # Exact match, not ``endswith``: create_release_zip names every member
        # exactly ``rel_path.as_posix()`` with no shared prefix, so an exact
        # test is both simpler and immune to a basename collision --
        # ``"docs/README.md".endswith("README.md")`` is True, which would
        # false-red the moment a sample shares a basename with a public file.
        assert rel not in members, (
            f"{rel} {kind} was SHIPPED in the release zip"
        )


def _assert_shipped(members: set[str], samples: tuple[str, ...]) -> None:
    """The inclusion side, asserted as a FACT rather than as a label.

    This is the direction where the label became worthless. Before the walker
    pruned anything, ``excluded-from-zip`` and ``in skipped_entries`` were
    equivalent, so ``rel not in skipped_entries`` was a valid inclusion proof.
    Walk-time pruning broke that equivalence: a pruned path is absent from the
    skip list AND absent from the archive, so the old assertion passes **for
    free** on exactly the files that silently stopped shipping.

    Measured, not theorised: adding a one-line ``tools/`` arm to
    ``release_pack._is_pruned_from_walk`` drops 47 files from the real release
    archive -- the entire vendored hook tree -- and the full suite stayed green
    at 7,051 passed. This assertion is what turns that mutation red.
    """
    for rel in samples:
        assert rel in members, (
            f"{rel} is public-release-allowed but is NOT in the release zip -- "
            "either the walker pruned it or the archive dropped it; both are "
            "silent, because a pruned path never reaches skipped_entries either"
        )


class TestReleasePackConsumerOutcomes:
    def test_internal_samples_excluded_from_zip(self, seeded_tree: Path):
        summary = release_pack.create_release_zip(
            seeded_tree, seeded_tree / "dist" / "out.zip"
        )
        for rel in INTERNAL_SAMPLES:
            assert rel in summary.skipped_internal, (
                f"{rel} not marked internal-skip by release_pack"
            )
        _assert_not_shipped(
            _build_and_read_members(seeded_tree), INTERNAL_SAMPLES, "internal"
        )

    def test_local_only_samples_excluded_from_zip(self, seeded_tree: Path):
        _assert_not_shipped(
            _build_and_read_members(seeded_tree), LOCAL_ONLY_SAMPLES, "local-only"
        )

    def test_transient_samples_excluded_from_zip(self, seeded_tree: Path):
        _assert_not_shipped(
            _build_and_read_members(seeded_tree), TRANSIENT_SAMPLES, "transient"
        )

    def test_public_samples_included_in_zip(self, seeded_tree: Path):
        _assert_shipped(_build_and_read_members(seeded_tree), PUBLIC_SAMPLES)


class TestPreReleaseConsumerOutcomes:
    def test_internal_samples_flagged_as_leaks(self, seeded_tree: Path):
        gate = pre_release.run_cleanliness_gate(seeded_tree)
        leaks = set(gate["internal_leaks"])
        for rel in INTERNAL_SAMPLES:
            assert rel in leaks, f"{rel} not flagged as internal leak"

    def test_public_samples_not_flagged_as_leaks(self, seeded_tree: Path):
        gate = pre_release.run_cleanliness_gate(seeded_tree)
        leaks = set(gate["internal_leaks"])
        for rel in PUBLIC_SAMPLES:
            assert rel not in leaks, f"public sample {rel} flagged as leak"


# ---------------------------------------------------------------------------
# Parity: both consumers classify identically on the same input
# ---------------------------------------------------------------------------

class TestSharedOutcomeInvariant:
    """Both consumers must report the same internal set. If they drift, a
    release could leak internal material or be unnecessarily rejected."""

    def test_internal_classification_parity(self, seeded_tree: Path):
        gate = pre_release.run_cleanliness_gate(seeded_tree)
        summary = release_pack.create_release_zip(
            seeded_tree, seeded_tree / "dist" / "out.zip"
        )
        pre_internal = set(gate["internal_leaks"])
        pack_internal = set(summary.skipped_internal)
        assert pre_internal == pack_internal, (
            f"pre_release and release_pack disagree on internal classification.\n"
            f"pre_release only: {sorted(pre_internal - pack_internal)}\n"
            f"release_pack only: {sorted(pack_internal - pre_internal)}"
        )
