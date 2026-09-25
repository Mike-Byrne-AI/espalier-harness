"""Known-negative perf_smells scanner fixtures (must-NOT-trip corpus).

Mirror of test_perf_smells_positives.py, but every construct is the
*clean-but-tempting* variant of a GENERAL_PATTERNS smell: shaped to sit
right at the boundary the scanner draws, yet provably silent under
scan_file. The earn-the-gate test proves the scanner FIRES on positives;
this corpus proves it STAYS SILENT on clean input (TP-156 Tier 1).

The three GENERAL_PATTERNS the scanner can surface line-by-line are
subprocess_shell, global_import_star and bare_open. Each is defanged here:

- subprocess_shell: subprocess.run WITHOUT `shell=True` (the default,
  shell-less form the smell warns about avoiding).
- global_import_star: an explicit named import, not `import *`.
- bare_open: the file-open call is wrapped in a `with` statement -- the
  scanner's `(?<!with\\s)` lookbehind exempts a single-space `with `
  prefix, which is the recommended context-manager form.

Live-scan exemption: EXEMPT_PREFIXES ("tests/fixtures/") keeps this file
out of normal `espalier scan perf_smells` runs, same as the positives.

Fixtures-only. NO real assertions. Inner functions OMIT the `test_`
prefix so pytest does not collect them. TP-156 Tier 1.
"""
from __future__ import annotations

from typing import Any  # named import, not `import *` -- not global_import_star

import os
import subprocess


def shape_subprocess_no_shell() -> None:
    # subprocess.run without shell=True -- the safe, smell-free form.
    subprocess.run(["echo", "hi"], check=True)


def shape_open_with_context_manager() -> None:
    # `with open(...)` -- the `(?<!with\s)` lookbehind exempts this.
    with open("/tmp/x", encoding="utf-8") as f:
        f.read()


def shape_named_import() -> Any:
    # An explicit named import (above) stands in for the tempting
    # `from typing import *`. Returning Any keeps the import live.
    return None


# precision-boundary: a dotted-receiver attribute access, plus string-literal
# and comment spans carrying the same call name — the token detector excludes
# all three; the raw line regex over-matched them. (Class named; the live
# trigger substring is deliberately not quoted, per TP-217a's self-trip trap.)


def shape_open_inside_string() -> str:
    # The literal text contains the call name but it is a STRING, not a call.
    return "subprocess.run(open(...))  -- this is data, not code"


def shape_open_in_comment() -> None:
    # how to open( a file -- this comment must not trip bare_open
    return None


def shape_dotted_open() -> None:
    # `os.open` / `x.open()` are attribute accesses, not the builtin open().
    fd = os.open("/tmp/x", os.O_RDONLY)
    os.close(fd)


def shape_popen_lookalike() -> None:
    # `Popen(` is a dotted attribute and a different name -- must not trip.
    subprocess.Popen(["true"])
