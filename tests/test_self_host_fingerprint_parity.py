"""SHA pin parity between library and hook-side mirror (TP-76).

Byte-equality test at import time. Drift between the two constants
silently regresses BC-035 hardening on the hook side (every PreToolUse
fires through the hook-side detector). Runs in <1ms.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_hook_mirror():
    spec = importlib.util.spec_from_file_location(
        "_self_host_fingerprint_hook",
        REPO_ROOT / "tools" / "cc" / "hooks" / "_self_host_fingerprint.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_sha_hash_matches() -> None:
    from espalier import _self_host_fingerprint as lib
    hook = _load_hook_mirror()
    assert lib.WRITE_GUARD_PREFIX_SHA256 == hook.WRITE_GUARD_PREFIX_SHA256


def test_prefix_byte_length_matches() -> None:
    from espalier import _self_host_fingerprint as lib
    hook = _load_hook_mirror()
    assert lib.WRITE_GUARD_PREFIX_BYTES == hook.WRITE_GUARD_PREFIX_BYTES


def test_gitattributes_pins_python_eol_lf() -> None:
    """TP-174b W7: the signal-5 hash is computed over write_guard.py's raw
    first 200 bytes, so a Windows core.autocrlf=true checkout that rewrote LF
    to CRLF would break self-host detection. A `*.py text eol=lf` rule in
    .gitattributes makes the on-disk bytes deterministic. The behavioral break
    only manifests on a windows-latest CI leg, so this is the local witness."""
    ga = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.py text eol=lf" in ga, (
        ".gitattributes must pin `*.py text eol=lf` so the self-host signal-5 "
        "hash survives a Windows CRLF checkout (see the write-guard-first-200-"
        "bytes sharp edge)."
    )


def test_live_lf_hash_matches_pin() -> None:
    """TP-174b W7: the pin is an LF hash and the working tree is LF, so they
    must match. (Belt-and-braces with the eol=lf rule above — proves the pin
    was not silently re-computed against CRLF.)"""
    import hashlib

    from espalier import _self_host_fingerprint as lib
    prefix = (REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_bytes()[
        : lib.WRITE_GUARD_PREFIX_BYTES
    ]
    assert hashlib.sha256(prefix).hexdigest() == lib.WRITE_GUARD_PREFIX_SHA256


def test_the_pinned_region_warns_its_own_editor() -> None:
    """The load-bearing prose must say it is load-bearing, INSIDE the pin.

    The pinned region is a shebang plus an ordinary module docstring. Nothing
    about it looks special, so a routine reflow silently flips
    ``is_self_host_repo()`` to False on this repo -- and since the
    provenance / pre-release / release-pack verbs now stand down on that
    predicate, the fast-loop gates start reporting "not applicable" HERE.

    The warning lives inside the hashed bytes on purpose: deleting it is
    itself a pin change, so the warning cannot be removed any more quietly
    than the thing it guards. This test keeps it from drifting past byte 200
    as the docstring above it grows -- which would leave the text present,
    the reader reassured, and the protection gone.
    """
    from espalier import _self_host_fingerprint as lib

    prefix = (REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py").read_bytes()[
        : lib.WRITE_GUARD_PREFIX_BYTES
    ]
    for probe in (b"DO NOT REFLOW", b"SHA-pinned", b"espalier _refresh-self-host-pin"):
        assert probe in prefix, (
            f"{probe!r} has drifted OUT of write_guard.py's first "
            f"{lib.WRITE_GUARD_PREFIX_BYTES} bytes. The warning is only "
            "self-protecting while it sits inside the hashed region — move it "
            "back up, or shorten the text above it."
        )


def test_every_pin_carrier_is_refreshed() -> None:
    """`_refresh-self-host-pin` must cover EVERY file holding the hash.

    DERIVED, not declared. Twice in one session a "fix" to this verb was
    itself incomplete: it began rewriting only the library copy, the repair
    took it to two carriers, and `tools/cc/ci_guard.py` -- which inlines its
    own copy because it must run standalone -- was still missed. A
    hand-written list is what produced that, so this walks the live tree for
    files carrying a 64-hex `WRITE_GUARD_PREFIX_SHA256` literal and requires
    each to be in `SELF_HOST_PIN_CARRIERS`.

    The failure mode is silent by construction: a stale carrier does not
    raise, it answers "this is not the self-host repo", which withdraws the
    harness-dev posture and stands the provenance / pre-release /
    release-pack verbs down on this very tree.
    """
    import re

    from espalier.cli import SELF_HOST_PIN_CARRIERS

    assign = re.compile(r'WRITE_GUARD_PREFIX_SHA256\s*=\s*\(?\s*"[0-9a-f]{64}"')
    found = set()
    for root in ("espalier", "tools", "scripts"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/_vendor/" in f"/{rel}" or "__pycache__" in rel:
                continue  # byte-mirrors; sync_vendor_cc.py carries them
            if assign.search(path.read_text(encoding="utf-8", errors="replace")):
                found.add(rel)

    assert found, (
        "no pin carrier found at all — the constant was renamed or the "
        "recognizer broke, and this gate is now vacuous"
    )
    declared = set(SELF_HOST_PIN_CARRIERS)
    assert found == declared, (
        "the set of files carrying the write_guard SHA pin changed.\n"
        f"  NOT refreshed by the verb (add to SELF_HOST_PIN_CARRIERS): "
        f"{sorted(found - declared)}\n"
        f"  declared but no longer carrying a pin (drop it): "
        f"{sorted(declared - found)}\n"
        "A carrier the refresh verb misses goes stale silently and makes "
        "is_self_host_repo() return False on this repo."
    )
