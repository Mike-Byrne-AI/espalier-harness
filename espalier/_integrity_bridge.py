"""Bridge to the hook-side integrity module without a ``tools/cc`` import.

``tools/cc/hooks/_integrity.py`` is standalone by the zero-espalier-import
contract (pinned by ``tests/test_contracts.py::TestToolsCcNoEspalierImports``).
The inverse — espalier loading that single module BY FILE PATH via importlib —
is the sanctioned exception (it adds no import edge).

This helper is a LEAF: it imports neither ``cli`` nor ``doctor``, so BOTH can
call it without a circular import. Reusing ``cli``'s former loader from
``doctor`` would have created ``doctor -> cli -> doctor`` (``cli`` already does
``from espalier.doctor import run_doctor_check``); this module removes that edge.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_integrity_module():
    """Load tools/cc/hooks/_integrity.py without making tools/cc an espalier dep.

    Preserves the rule that tools/cc/ scripts have zero espalier imports. The
    inverse (espalier importing a single helper module by file path) is fine.
    """
    here = Path(__file__).resolve().parent  # espalier/
    candidate = here.parent / "tools" / "cc" / "hooks" / "_integrity.py"
    if not candidate.exists():
        # Wheel install: ships under espalier/_vendor/cc/; tools/cc is no longer
        # a top-level package.
        candidate = here / "_vendor" / "cc" / "hooks" / "_integrity.py"
    spec = importlib.util.spec_from_file_location("_cc_integrity", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot locate _integrity.py at {candidate}")
    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None  # narrowed above
    loader.exec_module(module)
    _backfill_sentinels(module)
    return module


# The verdict sentinels are a WIRE VALUE between the hook module and the engine,
# and the two can be version-skewed: `git checkout <older-sha> -- tools/` during a
# bisect or a partial revert leaves a new engine reading an old producer. Engine
# code reads these as module ATTRIBUTES, so a pre-split producer raised
# AttributeError from inside doctor's integrity block -- which catches OSError,
# not AttributeError -- turning "no integrity signal" into a crash, in a command
# that CI invokes. On the self-host repo the skew is self-triggering: the swapped
# file is itself manifest-covered, so verification always reports drift, which is
# the exact branch that reads the attribute.
#
# MANIFEST_ABSENT's VALUE was deliberately left unchanged when the states were
# split, precisely so old and new interoperate. Backfilling here cashes that in:
# one owner, so no consumer needs a defensive getattr and none can forget one.
_LEGACY_MANIFEST_ABSENT = "<manifest missing>"
_UTF8_BOM = b"\xef\xbb\xbf"
_LEGACY_PROTOCOL_MISMATCH_PREFIXES = ("<algorithm_unsupported:", "<schema_version_unsupported:")


def _legacy_canonical_text_bytes(raw: bytes) -> bytes:
    """The rule ``cli._same_ignoring_eol`` carried before DEF-725 moved it into
    the hook module: a leading UTF-8 BOM stripped, CRLF and bare CR folded to
    LF. Backfilled so ``install-ci`` and ``selfcheck`` keep comparing the way
    they did at that sha under a pre-DEF-725 hook module (both reviews drove
    the bisect skew: ``install-ci`` re-run and ``fuse`` raised AttributeError
    mid-deploy)."""
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM):]
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _legacy_is_protocol_mismatch(mismatched) -> bool:
    return len(mismatched) == 1 and str(mismatched[0]).startswith(_LEGACY_PROTOCOL_MISMATCH_PREFIXES)


def _backfill_sentinels(module) -> None:
    """Give a pre-split ``_integrity`` module every name engine code reads that
    a producer may predate: the two verdict sentinels, and since DEF-725 the
    text canon and the protocol-mismatch predicate.

    ``MANIFEST_UNREADABLE`` backfills to ``None`` rather than a string: a producer
    that predates the absent-vs-unreadable split never emits that state, so every
    ``mismatched == [MANIFEST_UNREADABLE]`` test must simply not match. A string
    default would make a legacy verdict of ``[None]`` impossible but a legacy
    verdict that happened to equal the placeholder possible.
    """
    if not hasattr(module, "MANIFEST_ABSENT"):
        module.MANIFEST_ABSENT = _LEGACY_MANIFEST_ABSENT
    if not hasattr(module, "MANIFEST_UNREADABLE"):
        module.MANIFEST_UNREADABLE = None
    if not hasattr(module, "canonical_text_bytes"):
        module.canonical_text_bytes = _legacy_canonical_text_bytes
    if not hasattr(module, "PROTOCOL_MISMATCH_PREFIXES"):
        module.PROTOCOL_MISMATCH_PREFIXES = _LEGACY_PROTOCOL_MISMATCH_PREFIXES
    if not hasattr(module, "is_protocol_mismatch"):
        module.is_protocol_mismatch = _legacy_is_protocol_mismatch
