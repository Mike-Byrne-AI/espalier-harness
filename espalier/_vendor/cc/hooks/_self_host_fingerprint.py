"""SHA pin mirror for self-host detection.

Stdlib-only -- zero espalier imports. The mirrored constants must
match ``espalier/_self_host_fingerprint.py`` byte-for-byte. Parity
is asserted by ``tests/test_self_host_fingerprint_parity.py``. Both
mirrors must be refreshed in lockstep whenever
``tools/cc/hooks/write_guard.py`` changes.

See ``espalier/_self_host_fingerprint.py`` for the canonical
docstring on attack model and threat scope.
"""
from __future__ import annotations

WRITE_GUARD_PREFIX_SHA256 = "d72ea5ffa4aba60812c9c37530491eece48a6a44c2e48930932883feca3300ff"
WRITE_GUARD_PREFIX_BYTES = 200
