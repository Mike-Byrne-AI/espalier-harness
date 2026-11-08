"""The one predicate the guard censuses read for "anchored at a bash command position".

Two fragments open a command position in `tools/cc/hooks/_bash_patterns.py`:
`_CMD_POS_NO_VERB` (every verb reader, which `_CMD_POS` begins with) and
`_CMD_POS_IN_SHELL`, the cd tracker's anchor (ruling 6344f9: the same
separator-anchored start with the current shell's own words in place of the
wrapper run, since a cd a wrapper runs moves no later statement). Each census
used to test `_CMD_POS_NO_VERB in pattern` on its own, so when the directory-verb
matcher moved onto the tracker's anchor it dropped out of six censuses at once and
only one of them went red; the rest stopped reading it without a word (air's
c2bbdd). A census asks this function, and each keeps its own PowerShell clause.
"""
from __future__ import annotations

from types import ModuleType


def bash_anchors(bp: ModuleType) -> tuple[str, ...]:
    """The bash command-position fragments, read from the module."""
    return (bp._CMD_POS_NO_VERB, bp._CMD_POS_IN_SHELL)


def is_bash_anchored(pattern_text: str, bp: ModuleType) -> bool:
    """Whether a pattern's text composes a bash command-position anchor."""
    return any(anchor in pattern_text for anchor in bash_anchors(bp))
