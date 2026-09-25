"""Shared constants for blueprint read safety (library-side copy).

Stdlib-only, minimal. Imported by `espalier/cognitive_blueprint.py`.

The hook-side mirror lives at `tools/cc/_blueprint_limits.py`. Both
copies must export identical values; parity is asserted by
`tests/test_library_hook_parity.py`. The duplication is deliberate —
the standalone-execution invariant for `tools/cc/` forbids importing
from `espalier/`.
"""
from __future__ import annotations

BLUEPRINT_MAX_SIZE = 131_072

# Bound per-session blueprint accumulation. save_blueprint / _save write one
# {session_id}.json per session and never reclaim them, so a long-lived
# checkout grows without limit.
# Keep the BLUEPRINT_RETENTION most-recent per-session files; never prune one
# younger than BLUEPRINT_MIN_PRUNE_AGE_S (a concurrent session may still be
# writing it). latest.json is always preserved regardless of these bounds.
BLUEPRINT_RETENTION = 200
BLUEPRINT_MIN_PRUNE_AGE_S = 3600

# A freshly-started session writes an empty-session node (all content lists
# empty); on the self-host tree that serialises to exactly 575 bytes. Nodes at
# or below this size carry no reasoning; prune sorts substantive nodes first so
# stubs are evicted before real reasoning when the retention cap is hit. Headroom
# above 575 so a trivially-small-but-real node is never misclassified. If the
# empty-session template ever grows past this, prune degrades to name-order-only
# — no worse than the prior behaviour.
BLUEPRINT_STUB_MAX_BYTES = 600

# The retention cap is a WORKING-SET policy, not a destruction policy. Nodes
# evicted past BLUEPRINT_RETENTION are demoted into this sibling directory,
# never unlinked — measured 2026-08-31, the chain had already lost ~2 months
# (oldest surviving node 2026-07-03 against a 2026-04-30 first commit) to a
# prune that deleted, and the loss was silent because deleting and retaining
# produced identical output at every observable the tooling had.
#
# Must stay a name `bp_dir.glob("*.json")` cannot match, or the eviction tail
# would re-enter itself; the glob is non-recursive, so any directory name is
# safe. Readers fall back here (reflect_protocol's parent lookup) so a demoted
# node stays REACHABLE rather than merely present — preserved bytes the tooling
# cannot read are not a preserved record.
BLUEPRINT_COLD_DIR_NAME = "_cold"
