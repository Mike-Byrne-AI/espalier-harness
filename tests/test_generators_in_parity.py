"""Every generated mirror and doc region is in parity, under the contract marker.

Pins: each generator's own read-only ``--check`` exits 0 on this tree. The
generators are the sync script of every row in ``espalier/mirror_registry.py``
plus the two region generators that are not mirror rows, and a census holds
every ``--check`` script under ``scripts/`` and ``tools/cc/`` to one of the two
lists: covered here, or exempt with a reason.

Prevents two shapes, measured 2026-10-10 by collecting ``-m contract``:

- The self-check test mirror's own pin (``test_selfcheck_tests_parity``) is
  outside the slice, while an edit to a mirrored test file earns only the
  contract tier (``scripts/proof_tier.py::tier``), locally and in CI's
  required cells. A forgotten sync merged green.
- Vendor-cc's pin and the doc regions' pin are outside the slice too. Their
  inputs are full-tier paths, so they bite a lane whose local run was only the
  contract slice. PR #168's five test cells went red on two stale
  deploy-inventory regions that way.

The other rows' own pins are already in the slice: an unsynced
``.claude/commands`` body reds two ``test_package_resource_parity`` tests under
``-m contract``. This file repeats them on purpose. The coverage is derived from
the registry, so no hand list decides which rows count.

Each script runs with ``--check`` against the live tree and writes nothing; the
seven together take about four seconds.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from espalier.mirror_registry import MIRROR_ROWS

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Region generators that are not mirror rows: each rewrites marked regions of
#: tracked docs from a live Python object, and has a ``--check``.
_REGION_GENERATORS: tuple[str, ...] = (
    "scripts/generate_doc_regions.py",
    "tools/cc/generate_ledger_regions.py",
)

#: ``--check`` scripts that are not parity generators, with the reason.
_NOT_A_GENERATOR: dict[str, str] = {
    "scripts/archive_transcripts.py": "its --check is a dry run of the transcript archive, not a parity check",
}

_CHECK_FLAG = re.compile(r"""["']--check["']""")


def _sync_script(sync: str) -> str:
    """The script path inside a row's ``sync`` command (``python3 scripts/x.py``)."""
    scripts = [tok for tok in sync.split() if tok.endswith(".py")]
    assert len(scripts) == 1, f"a mirror row's sync names one script, got {sync!r}"
    return scripts[0].replace("\\", "/")


def _generators() -> tuple[str, ...]:
    out: list[str] = []
    for script in [_sync_script(row.sync) for row in MIRROR_ROWS] + list(_REGION_GENERATORS):
        if script not in out:
            out.append(script)
    return tuple(out)


GENERATORS = _generators()


def _check_flag_scripts() -> list[str]:
    found = []
    for folder in ("scripts", "tools/cc"):
        for path in sorted((REPO_ROOT / folder).glob("*.py")):
            if _CHECK_FLAG.search(path.read_text(encoding="utf-8", errors="replace")):
                found.append(f"{folder}/{path.name}")
    return found


class TestEveryGeneratorChecksClean:
    @pytest.mark.parametrize("script", GENERATORS)
    def test_check_mode_exits_zero(self, script):
        proc = subprocess.run(
            [sys.executable, script, "--check"], cwd=REPO_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=50,
        )
        tail = (proc.stdout + proc.stderr).strip()[-1500:]
        assert proc.returncode == 0, (
            f"{script} --check exited {proc.returncode}: a generated mirror or region is stale. "
            f"Run `python3 {script}` and commit what it writes.\n{tail}"
        )


class TestEveryCheckScriptIsClassified:
    def test_every_check_flag_script_is_a_generator_or_exempt(self):
        unclassified = [s for s in _check_flag_scripts() if s not in GENERATORS and s not in _NOT_A_GENERATOR]
        assert not unclassified, (
            f"{unclassified} take --check but are neither covered by this contract nor exempt: add a "
            "region generator to _REGION_GENERATORS, or a non-parity script to _NOT_A_GENERATOR with its reason"
        )

    def test_every_listed_script_exists_and_takes_check(self):
        flagged = set(_check_flag_scripts())
        stale = [s for s in list(GENERATORS) + list(_NOT_A_GENERATOR) if s not in flagged]
        assert not stale, f"{stale} are listed here but are missing or take no --check"


class TestEveryMirrorFileIsCheckedOutLF:
    """The comparators read bytes, and a generator plans LF. Under
    ``core.autocrlf=true`` (the Windows default) a fresh checkout writes CRLF
    into any mirror file whose ``eol`` ``.gitattributes`` leaves unspecified, and
    its ``--check`` then reports drift that is not there. Measured 2026-10-10:
    ``espalier/_vendor/selfcheck_tests/pytest.ini`` in a new worktree held 104
    bytes against the 100 planned, the only unpinned file under any mirror."""

    def test_every_tracked_mirror_file_pins_eol_lf(self):
        from tests._git_oracle import require_tracked_paths

        mirrors = sorted({path for row in MIRROR_ROWS for path in row.mirrors})
        # 159 tracked files on 2026-10-10; the floor catches a collapsed listing.
        tracked = require_tracked_paths(REPO_ROOT, *mirrors, minimum=100, what="files under the mirrors")
        attrs = subprocess.run(
            ["git", "check-attr", "-z", "--stdin", "eol"], cwd=REPO_ROOT, input="\0".join(tracked) + "\0",
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50, check=True,
        ).stdout.split("\0")
        rows = list(zip(attrs[0::3], attrs[2::3]))
        assert len(rows) == len(tracked), f"git check-attr answered {len(rows)} of {len(tracked)} paths"
        unpinned = [path for path, eol in rows if eol != "lf"]
        assert not unpinned, (
            f"{unpinned} sit under a mirror without eol=lf in .gitattributes: a fresh checkout under "
            "core.autocrlf=true writes CRLF and the sync's --check reports false drift"
        )
