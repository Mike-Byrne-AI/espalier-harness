"""Write-verb extractors must recognise LONG flags, not only clustered short ones.

`_CP_MV_RE`'s option run was `(?:-[a-zA-Z]+\\s+)*`, which cannot match `--force`:
after the first `-` it demands a letter and finds the second `-`. The flag was
therefore read as the SOURCE argument and the real destination fell outside the
capture, so a protected target went unchecked. Driven at the live hook with
maintenance OFF (i.e. enforcement, not friction), `cp --force src.py <protected>`
ALLOWED while `cp -f src.py <protected>` denied.

SCOPE, measured rather than assumed. The same short-vs-long probe was run against
every write verb the guard models -- cp, mv, install, rsync, tee, truncate, sed,
ln -- and the other six already handled long flags. This is a two-verb class, so
the fix is two verbs; a tree-wide sweep would have been scope inflation. The probe
lives on as ``test_every_write_verb_handles_its_long_flag`` below, which is the
part that keeps the claim honest: it fails if a NEW verb arrives with the old
short-only shape.

Not a security boundary (docs/STANDING_PRINCIPLES.md §2) -- `harness-guard.yml`
still gates a committed write. The value is catching the everyday slip, and
`cp --force` is an everyday spelling.
"""
# slow-exempt: pure in-process regex/predicate calls, no child processes.
from __future__ import annotations

import pytest

from tools.cc.hooks import _bash_patterns as bp

PROTECTED = "tools/cc/hooks/write_guard.py"


def _extracts(command: str) -> bool:
    return PROTECTED in list(bp._candidate_paths_from_bash(command))


# (label, short-flag spelling, long-flag spelling) -- the short one is the control:
# if IT stops extracting, the long-flag assertion beside it proves nothing.
_VERB_PAIRS = [
    ("cp-force", f"cp -f src.py {PROTECTED}", f"cp --force src.py {PROTECTED}"),
    ("cp-recursive", f"cp -r src {PROTECTED}", f"cp --recursive src {PROTECTED}"),
    ("mv-force", f"mv -f src.py {PROTECTED}", f"mv --force src.py {PROTECTED}"),
    ("install", f"install -m 644 src.py {PROTECTED}", f"install --mode=644 src.py {PROTECTED}"),
    ("rsync", f"rsync -a src.py {PROTECTED}", f"rsync --archive src.py {PROTECTED}"),
    ("tee", f"tee -a {PROTECTED}", f"tee --append {PROTECTED}"),
    ("truncate", f"truncate -s 0 {PROTECTED}", f"truncate --size=0 {PROTECTED}"),
    ("sed", f"sed -i 's/a/b/' {PROTECTED}", f"sed --in-place 's/a/b/' {PROTECTED}"),
]


@pytest.mark.parametrize("label,short,long", _VERB_PAIRS, ids=[p[0] for p in _VERB_PAIRS])
def test_every_write_verb_handles_its_long_flag(label, short, long):
    """The derived contract: for every verb, the long-flag spelling must extract
    the same protected target its short-flag twin does."""
    assert _extracts(short), (
        f"{label}: the SHORT-flag control stopped extracting — the long-flag "
        f"assertion below is meaningless until this is fixed"
    )
    assert _extracts(long), (
        f"{label}: {long!r} writes to a protected path but the extractor missed "
        f"it, while the short-flag spelling was caught"
    )


@pytest.mark.parametrize("command", [
    f"cp --preserve=all src.py {PROTECTED}",     # long flag carrying a value
    f"cp -p --force src.py {PROTECTED}",         # mixed short + long
    f"cp --force -p src.py {PROTECTED}",         # mixed, other order
    f"mv --verbose --force src.py {PROTECTED}",  # two long flags
    f"cp -- src.py {PROTECTED}",                 # end-of-options marker
])
def test_cp_mv_option_run_shapes(command):
    assert _extracts(command), command


@pytest.mark.parametrize("command", [
    f"cp src.py {PROTECTED}",
    f"mv src.py {PROTECTED}",
    f"cp -rf src {PROTECTED}",
])
def test_plain_and_clustered_short_forms_still_extract(command):
    """Regression floor: widening the option run must not cost the forms that
    already worked."""
    assert _extracts(command), command


@pytest.mark.parametrize("command", [
    "cp src.py docs/notes.md",
    "mv a.py b.py",
    "cp --force a.py b.py",
])
def test_unprotected_targets_are_not_extracted_as_protected(command):
    """The widened option run must not start manufacturing protected hits."""
    assert not _extracts(command), command


def test_cp_assignment_is_still_not_a_command():
    """`cp=...` is a shell variable assignment, not the verb. The sibling verbs
    carry an explicit `\\b(?!=)` guard for this; cp/mv rely on the required
    whitespace after the verb. Pinned because the option run was just widened
    and `=` now appears inside it (`--preserve=all`)."""
    assert not _extracts(f"cp=--force {PROTECTED}")
