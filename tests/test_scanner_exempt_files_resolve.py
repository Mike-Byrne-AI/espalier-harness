"""Pin every scanner's EXEMPT_FILES / EXEMPT_PROSE_FILES entry to a
real file on disk.

FM-14 §4.6 close (TP-144): a path in EXEMPT_FILES that doesn't resolve
is a vacuous registry entry -- a rename silently drops the exemption
AND starts flapping findings. The cap-based discipline
(``MAX_EXEMPT_FILES``) is itself vacuous when entries are ghosts.

Sibling: tests/test_scanners.py::TestScannerExemptPrefixesParity
(TP-139) -- same shape, different aspect (prefix-presence vs
file-existence).

A second contract once lived here (TestDocWalkingScannersAccountForCorpus,
TP-436): every doc-walking scanner had to account for the machine-appended
dedup corpus. It retired with the corpus on 2026-09-21 -- no scanner surface
carries machine-appended reviewer text any more.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests._git_oracle import require_is_gitignored

REPO_ROOT = Path(__file__).resolve().parents[1]


# (module_import_path, attribute_name)
#
# Both shapes covered: ``EXEMPT_FILES`` on the AST scanners
# (convergence_theater, retired_vocab); ``EXEMPT_PROSE_FILES`` on
# canon_verifier (different name -- the scanner walks prose docs that
# mention canon-annotation syntax inside backticks, distinct from the
# AST-scanner exemption shape). Same registry semantic: "skip these
# specific repo-relative paths when scanning."
_SCANNER_EXEMPT_REGISTRIES: tuple[tuple[str, str], ...] = (
    ("espalier.scanners.convergence_theater", "EXEMPT_FILES"),
    ("espalier.scanners.retired_vocab", "EXEMPT_FILES"),
    ("espalier.scanners.canon_verifier", "EXEMPT_PROSE_FILES"),
)


class TestScannerExemptFilesResolveOnDisk:
    """Walk every (scanner, exempt-attr) pair; assert every entry
    resolves to a real file under ``REPO_ROOT``.

    Why disk-existence over symbolic-name is the right contract: an
    exempt entry exists to prevent the scanner from false-firing on a
    specific real file. If the file is renamed or deleted, the entry
    becomes a ghost -- it doesn't suppress anything (no file matches)
    AND the original file (if renamed) starts flapping findings again.
    A failing test forces the operator to either fix the path or
    remove the dead entry.
    """

    @pytest.mark.parametrize(
        "module_path,attr_name",
        _SCANNER_EXEMPT_REGISTRIES,
        ids=lambda x: x.split(".")[-1] if "." in x else x,
    )
    def test_every_exempt_path_resolves(
        self, module_path: str, attr_name: str
    ) -> None:
        import importlib
        module = importlib.import_module(module_path)
        registry = getattr(module, attr_name)
        unresolved: list[str] = []
        for rel_path in registry:
            target = REPO_ROOT / rel_path
            if target.is_file():
                continue
            # A gitignored, never-committed exempt entry (e.g. a local-only
            # session log) is legitimately absent on a fresh clone / CI -- the
            # scanner skips it there too (`if not path.exists(): continue`), so
            # the exemption is vacuous-but-harmless. Only a TRACKED entry that
            # fails to resolve signals a rename dropped the file AND silently
            # restored the finding-flap. (TP-177 W0-1)
            #
            # §C21/`DEF-573`: this used to read a bare `check-ignore` rc, which
            # is rc 0 for EVERY path -- including nonexistent ones -- whenever
            # REPO_ROOT sits inside someone else's gitignored directory. Measured
            # 2026-08-14: the whole registry was waved through when the release
            # archive was extracted under `dist/`, while the same archive
            # unpacked outside a worktree failed. The oracle refuses to answer
            # there instead, and the raise propagates: a tree where this cannot
            # be checked must not report that it was. A genuine release export
            # is handled one layer up, by the `full_tree` auto-skip.
            if not require_is_gitignored(REPO_ROOT, rel_path):
                unresolved.append(rel_path)
        assert not unresolved, (
            f"{module_path}.{attr_name} has {len(unresolved)} entries "
            f"pointing at non-existent, git-TRACKED files (likely a rename "
            f"dropped the exemption AND silently restored the finding-flap). "
            f"Either fix the path or remove the dead entry -- don't "
            f"add the ghost as a separate finding-suppressor. "
            f"Unresolved: {unresolved}"
        )
