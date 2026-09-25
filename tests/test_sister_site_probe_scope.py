"""TP-107: scan-target closure contract for the sister-site probe.

REPAIRED 2026-08-09. The original test asserted a symmetric diff between
``_default_scan_targets(REPO_ROOT)`` and an "independently-computed"
expected set — but the expectation restated *the probe's own two globs*
(``tools/cc/hooks/*.py`` | ``espalier/*.py``) and subtracted *the probe's
own* ``CANONICAL_FILES``. Both sides moved together, so **both** of the
drift modes the docstring advertised were structurally unreachable:

1. *"A new directory under ``tools/cc/`` is silently scoped out"* — the
   expectation globs the same two directories, so the new tree is absent
   from both sides. Measured on a synthetic tree: planting a new hook
   module inside a new directory under ``tools/cc/`` left the old
   assertion **GREEN**.
2. *"A canonical file is added or removed without updating
   ``CANONICAL_FILES``"* — the probe subtracts ``CANONICAL_FILES``
   internally (``sister_site_probe.py:238,245``) and the test subtracted
   the same imported frozenset, so an edit moves both sides in lockstep.

It duplicated the NARROWING rather than the derivation. Its sibling one
directory away — ``tests/test_folder_claude_md_routers.py::test_router_population_is_the_whole_tracked_tree`` — is the
correct form of the same idea, and its docstring says why: the duplication
is only a gate when the two sides are genuinely independent.

The repair asserts a CLOSURE property instead, against an independent
oracle (``git ls-files``, not ``Path.glob``):

    every tracked .py under tools/ + espalier/
        == what the probe scans
         + the canonical sources
         + a named exclusion, each carrying its reason

Nothing may fall through silently. A new directory appears in
``git ls-files``, matches no exclusion, is not scanned — and reds. The
only way to narrow the probe is to ADD an exclusion row with a written
reason, which is visible in review.

Scope note: three exclusion rows below record a REAL GAP (``DEF-20``,
``DEF-533``) rather than a justified carve-out. Widening the probe is a
separate scoping decision and is deliberately not made here; naming the
gap with its defect id is strictly better than the silence it replaces.

Test naming follows ``test_{specific_behavior}`` per docs/CONVENTIONS.md.
"""
from __future__ import annotations

# slow-exempt: the only subprocess calls are `git ls-files tools/*.py espalier/*.py`
# enumerations (`_tracked_py`, memoized by nothing but called at most once per
# test) — one fast index read each, no repo walk. Matches the exemption on
# tests/test_folder_claude_md_routers.py, the sibling closure contract.

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PROBE_PATH = REPO_ROOT / "tools" / "cc"
sys.path.insert(0, str(PROBE_PATH))
from sister_site_probe import CANONICAL_FILES, _default_scan_targets  # noqa: E402


# Directories holding tracked .py the probe does NOT scan, keyed by the file's
# EXACT parent directory — not a path prefix. Prefix matching would let
# ``tools/cc/`` silently absorb ``tools/cc/hooks/`` the day the probe stopped
# scanning it, which is the same swallow-the-population failure this contract
# exists to prevent. Exact-parent means ``tools/cc/hooks`` is unlisted, so if it
# ever leaves the scan set it reds by name.
_UNSCANNED_DIRS: dict[str, str] = {
    # --- justified carve-outs -------------------------------------------
    "espalier/_vendor/cc": (
        "Byte-mirror of tools/cc/ (mirror_registry row: vendor-cc). Scanning it "
        "would report every file as a duplicate clique of its own source."
    ),
    "espalier/_vendor/cc/hooks": (
        "Byte-mirror of tools/cc/hooks/ — same reason as espalier/_vendor/cc."
    ),
    "espalier/_vendor/selfcheck_tests": (
        "Vendored test mirror; a transform-mirror of tests/, not runtime source."
    ),
    # --- recorded gaps, NOT carve-outs ----------------------------------
    "tools/cc": (
        "DEF-20 (OPEN): tools/cc root modules — cognitive_blueprint, "
        "execution_plan, reflect_protocol, ci_guard — are unscanned in either "
        "spelling. This row records the gap; widening the probe is DEF-20's "
        "scoping decision, not this contract's."
    ),
    "espalier/scanners": (
        "DEF-20 (OPEN): the probe's docstring scopes scanners out because they "
        "have legitimately parallel _classify shapes. That rationale covers "
        "clique detection, not the rename-alias arm, which inherits the "
        "narrowing. Recorded, not resolved."
    ),
    "tools": (
        "DEF-533 (OPEN): top-level tools/ (review_agent_audit.py, __init__.py) "
        "sits outside every surface-governance mechanism that covers scripts/."
    ),
}

# A floor, not a count. The scan set may grow; a silent COLLAPSE (a bad glob, a
# moved directory) would otherwise leave every arm below asserting over almost
# nothing while still reporting success — the exact shape this file just spent
# its whole life demonstrating.
_MIN_SCANNED = 80


def _tracked_py() -> set[str]:
    """Every tracked .py under tools/ + espalier/, via git — an oracle
    independent of the ``Path.glob`` calls the probe itself uses."""
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "tools/*.py", "espalier/*.py"],
        capture_output=True, text=True, check=True, encoding="utf-8",
    ).stdout
    return {line for line in out.split() if line.endswith(".py")}


@pytest.mark.security
class TestDefaultScanTargetsAgainstRepo:
    def _scanned(self) -> set[str]:
        return {
            p.relative_to(REPO_ROOT).as_posix()
            for p in _default_scan_targets(REPO_ROOT)
        }

    def test_every_tracked_module_is_scanned_canonical_or_excluded(self):
        """Closure: nothing tracked falls out of the probe's scope silently."""
        try:
            tracked = _tracked_py()
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("`git ls-files` unavailable — not a dev tree / fresh clone")
        if not tracked:
            pytest.skip("`git ls-files` yielded no .py — not a dev tree / fresh clone")

        scanned = self._scanned()
        excluded = {
            rel for rel in tracked
            if rel.rsplit("/", 1)[0] in _UNSCANNED_DIRS
        }
        unaccounted = sorted(tracked - scanned - set(CANONICAL_FILES) - excluded)
        assert not unaccounted, (
            f"{len(unaccounted)} tracked module(s) are NOT scanned by the probe, "
            f"NOT named as canonical, and excluded by nothing:\n  "
            + "\n  ".join(unaccounted)
            + "\n\nEither widen _default_scan_targets, or add the file's parent "
            "directory to _UNSCANNED_DIRS WITH ITS REASON. Do NOT narrow the "
            "git ls-files derivation — that is how this contract went blind the "
            "first time."
        )

    def test_probe_scans_nothing_untracked(self):
        """The reverse arm: the probe must not reach outside the tracked tree."""
        try:
            tracked = _tracked_py()
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("`git ls-files` unavailable — not a dev tree / fresh clone")
        if not tracked:
            pytest.skip("`git ls-files` yielded no .py — not a dev tree / fresh clone")

        stray = sorted(self._scanned() - tracked)
        assert not stray, (
            f"probe scans {len(stray)} untracked file(s) — generated or "
            f"left-over artifacts skew every detection mode:\n  "
            + "\n  ".join(stray)
        )

    def test_scan_set_has_not_collapsed(self):
        """A floor, so a broken glob cannot quietly empty the population."""
        scanned = self._scanned()
        assert len(scanned) >= _MIN_SCANNED, (
            f"probe scan set collapsed to {len(scanned)} (floor {_MIN_SCANNED}). "
            "This is a FLOOR, not a pin: the set may grow freely. A shrink means "
            "a glob or directory moved, and every arm above would still pass "
            "while asserting over almost nothing."
        )

    def test_every_canonical_file_still_exists(self):
        """The only non-tautological claim available about CANONICAL_FILES.

        The probe subtracts this same frozenset internally, so any contract
        comparing "expected minus CANONICAL_FILES" against the probe's output
        moves both sides together and cannot fail. What IS assertable: a
        canonical entry that no longer names a real file is stale, and its
        canon-miss detection has been silently dead since the rename.
        """
        missing = sorted(p for p in CANONICAL_FILES if not (REPO_ROOT / p).is_file())
        assert not missing, (
            f"CANONICAL_FILES names {len(missing)} path(s) that no longer exist: "
            f"{missing}. Canon-miss detection for these is dead — repoint or "
            f"remove the entry."
        )

    def test_every_unscanned_dir_row_is_still_needed(self):
        """Self-expiring exclusions: a row silencing nothing is a stale row."""
        try:
            tracked = _tracked_py()
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("`git ls-files` unavailable — not a dev tree / fresh clone")
        if not tracked:
            pytest.skip("`git ls-files` yielded no .py — not a dev tree / fresh clone")

        parents = {rel.rsplit("/", 1)[0] for rel in tracked}
        dead = sorted(d for d in _UNSCANNED_DIRS if d not in parents)
        assert not dead, (
            f"{len(dead)} _UNSCANNED_DIRS row(s) no longer match any tracked "
            f".py and are silencing nothing: {dead}. Delete them — an exclusion "
            "that outlives its reason is how an allowlist grows without review."
        )
