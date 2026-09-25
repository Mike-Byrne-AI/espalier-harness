"""Pinned content fingerprint for self-host repo detection (BC-035).

The pin is the SHA-256 of the first 200 bytes of the canonical
``tools/cc/hooks/write_guard.py``. Updated by the hidden CLI subcommand
``espalier _refresh-self-host-pin`` after legitimate edits to
``write_guard.py``.

This is a defense-in-depth signal, NOT a cryptographic boundary. A
motivated attacker can byte-replay the write_guard.py prefix to spoof
self-host. The discipline forces them to ship harness code, which is an
observable supply-chain action rather than a passive name match. Without
this pin, a user repo named ``espalier-harness`` with empty stub
directories ``espalier/`` and ``tools/cc/`` would acquire the elevated
self-host posture (espalier/ added to write_guard's protected prefixes,
espalier/ added to plan_guard's exempt prefixes, etc.).
"""
from __future__ import annotations

WRITE_GUARD_PREFIX_SHA256 = "d72ea5ffa4aba60812c9c37530491eece48a6a44c2e48930932883feca3300ff"
WRITE_GUARD_PREFIX_BYTES = 200
