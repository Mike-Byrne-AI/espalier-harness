"""Which task packs are in flight, and what each one's ``## Scope (out)`` defers.

Two readers share this module and must not disagree: ``ledger_row.py strike``
(its deferral guard refuses to close a row an active pack still parks work
into) and the Espalier source tree's closeout lint, ``scripts/check_pack_landing.py``,
which re-exports every name here. It was that lint's own code until the ledger
verbs moved into ``tools/cc/`` to ship: a deployed verb cannot load a script that
is not deployed, and a second copy of the Scope (out) reader is the drift this
single home exists to prevent.

An absent folder is an empty population, never an error -- a repository that
keeps only a ``task-packs/`` root (no ``Deferred/``, ``Done/`` ...) has no packs
in the others. Stdlib only; no ``espalier`` import (this directory runs without
the engine installed).
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

# WHICH FOLDERS OWE A TERMINAL STANZA -- declared, and deliberately NOT derived.
#
# "Terminal" is a judgement about what a folder MEANS, and no filesystem walk
# supplies it. `Merged/` is the proof: its packs ARE finished, and its README
# says they are "preserved **unedited** as the provenance record", so requiring
# them to carry a stamp would demand editing files a documented invariant
# forbids editing. A rglob that "derived the terminal set" would sweep them in
# and be WRONG -- deriving is not automatically the safer choice.
#
# So the enumeration is GUARDED rather than derived: the closeout lint's
# `unclassified_dirs()` reds when a folder exists that no row here claims.
TERMINAL_DIRS = ("Done", "Scrapped")        # finished AND editable -> stamp required
NON_TERMINAL_DIRS = ("Deferred",)           # parked, not finished -> no stamp owed
UNSTAMPABLE_DIRS = ("Merged",)              # finished, but preserved unedited

# THE SCOPE (OUT) READER AND THE ACTIVE POPULATION -- one home, two readers.
#
# A pack's ``## Scope (out)`` is where deferred work is parked ("deferred to
# §C32", "a §2.3 remainder", "the successor pack owns this"), and until 2026-09-21 nothing
# mechanical read it: the strike verb rewrote a row without
# looking at the packs, and the completeness contract built its populations
# from folders and ids, never from the sentence saying where the work went.
# Two ledger rows named the two missing readers -- DEF-412a (the strike verb: a
# section struck while an in-flight pack still defers into it) and DEF-412e
# (the gate: a Scope (out) naming a pack nobody has written). Both read the
# same region of the same population, so the region and the population are
# defined ONCE, here -- a guard and a gate that parsed "Scope (out)" separately
# would disagree the first time a heading gained a trailing note.
# Calibrated on the live population (2026-09-21): 217 of 221 packs write exactly
# ``## Scope (out)``, one landed pack writes ``## Scope-out``, three have no such
# section; every active pack uses the exact form. The pattern admits the hyphen
# and case variants so a pack that drifts to one is read, not silently skipped,
# and refuses ``Scope (outline)``-shaped near-misses via the trailing lookahead.
_SCOPE_OUT_RE = re.compile(
    r"^#{1,6}[ \t]+Scope[ \t-]*\(?out\)?(?![A-Za-z])[^\n]*\n(.*?)(?=^#{1,2}[ \t]|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)


def blank_fences(text: str) -> str:
    """``text`` with every fenced code block replaced by spaces, newlines kept, so
    offsets and line numbers are those of the original. A fenced shell snippet's
    ``# comment`` would otherwise read as a heading and end the section, and a
    pack quoting the skill template inside a fence would read as the section
    itself (both latent on 2026-09-21: zero of 221 packs hit either; the code
    review drove both on a synthetic pack)."""
    return _FENCE_RE.sub(lambda m: "".join("\n" if ch == "\n" else " " for ch in m.group(0)), text)


def scope_out_spans(pack_text: str) -> list[tuple[int, int]]:
    """``(start, end)`` character offsets into ``pack_text`` of every Scope (out)
    body -- one per heading, so a pack with two such sections (one landed pack
    has two) is read whole. Fences are blanked before matching; the offsets index the
    ORIGINAL text, so a caller can count lines into it."""
    return [(m.start(1), m.end(1)) for m in _SCOPE_OUT_RE.finditer(blank_fences(pack_text))]


def scope_out(pack_text: str) -> str:
    """The body of the pack's ``## Scope (out)`` section(s), fenced blocks blanked,
    or ``""`` when it has none.

    Each body runs from its heading line to the next h1/h2 heading, so ``###``
    sub-headings inside the section stay inside it. The heading may carry a
    trailing note (``## Scope (out) -- deferred, with reasons``) and may be
    spelled ``Scope-out`` or ``Scope (Out)``; only a heading is keyed on, never a
    prose mention, and never a heading inside a fence.
    """
    blanked = blank_fences(pack_text)
    return "\n".join(blanked[s:e] for s, e in scope_out_spans(pack_text))


def active_pack_dirs(packs_root: Path) -> tuple[Path, ...]:
    """The folders whose packs are ACTIVE and ship: the root plus every
    NON-TERMINAL folder (``Deferred/``). Never ``Done/``, ``Scrapped/`` or
    ``Merged/`` -- landed and dead work has left the ledger by its own contract
    rule, so a citation there is history, not a deferral. Derived from the
    folder declaration above, so a folder that gains a row there joins or
    leaves this population by the same edit. A folder that does not exist is
    returned anyway; ``pack_files`` reads it as holding nothing."""
    return (packs_root, *(packs_root / d for d in NON_TERMINAL_DIRS))


def pack_files(pack_dirs: Path | Iterable[Path]) -> list[Path]:
    """Every pack file DIRECTLY under each of ``pack_dirs``: ``.md`` or
    ``.markdown``, stem opening ``tp-`` case-insensitively; a directory that does
    not exist contributes nothing (an empty population, never an error).

    ``iterdir()`` with explicit suffix/stem checks, not ``glob("TP-*.md")``: the
    glob let an off-convention orphan -- a lowercase ``tp-`` name or a
    ``.markdown`` extension -- escape the completeness guard uncounted (the
    orphan detector's own earn-the-red case),
    and the escape was platform-dependent (APFS globs case-insensitively, Linux
    CI does not). Two deliberate sibling copies exist on the Espalier source
    tree: the orphan detector in ``tests/test_forward_ledger_completeness.py::_pack_files``
    (it must run on a tree without ``scripts/``) and
    ``tests/test_cross_pack_assertions.py::_pack_index`` (it walks all four status
    folders, not the active two). This one is the copy the strike verb and the
    deferral gate share.
    """
    dirs = [pack_dirs] if isinstance(pack_dirs, Path) else list(pack_dirs)
    return sorted(
        p for d in dirs if d.is_dir() for p in d.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".md", ".markdown"}
        and p.stem.lower().startswith("tp-")
    )
