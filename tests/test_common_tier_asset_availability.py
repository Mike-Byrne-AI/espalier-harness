"""TP-118: every file/tool referenced in a common-tier asset body
must exist on an adopter's filesystem after `espalier init`.

Pins the invariant that common-tier asset bodies (agent / command /
skill) do NOT reference harness-internal artifacts an adopter cannot
satisfy: `bench/corpus/`, `MANIFEST_FILES`, `scripts/release_check.py`,
`tests/test_integrity.py`, `cc/blueprints/`, etc. These paths exist
only in the harness-development tree; the wheel/sdist payload and
`espalier init` output do not contain them.

Sister-class to ``test_common_tier_assets_have_no_internal_pack_ids``
(TP-78): that contract scrubs ``TP-N`` / ``BC-NNN`` identifiers from
common-tier bodies. This contract scrubs filesystem paths and tool
invocations. Without this contract, asset prose can drift back into
harness-internal vocabulary and break adopter-tier installs silently
(the prose renders fine, but adopters following the instructions hit
``No such file or directory``).

Failure mode prevented: a future common-tier asset body adds (or
re-adds) a `bench/corpus/X.json` reference; adopters who don't ship
`bench/` follow the instruction and get an inscrutable error. The
parametrized matrix here catches the regression at authoring time.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMON_TIER_ROOTS = (
    REPO_ROOT / "espalier" / "assets" / "claude" / "agents",
    REPO_ROOT / "espalier" / "assets" / "claude" / "commands",
    REPO_ROOT / "espalier" / "assets" / "claude" / "skills",
)

# Tokens that name harness-internal surfaces adopters do not receive.
# Each entry is (substring, what-it-means, fix-direction).
FORBIDDEN_TOKENS: tuple[tuple[str, str, str], ...] = (
    ("bench/corpus/", "bench/ is harness-internal", "reframe in adopter-local terms or wrap in `[ -d bench/ ]` presence check"),
    ("bench/run_benchmark", "bench/ is harness-internal", "remove or wrap in presence check"),
    ("MANIFEST_FILES", "internal-only integrity constant", "describe in adopter-neutral terms (`espalier integrity verify .`)"),
    ("scripts/release_check.py", "scripts/ is not shipped", "use `espalier pre-release . --skip-tests --skip-parity`"),
    ("scripts/final_release_matrix", "scripts/ is not shipped", "remove or move to a self-host-only command"),
    ("tests/test_integrity.py", "harness-internal test suite", "remove"),
    ("cc/blueprints/", "self-host cognitive blueprint chain", "describe the read-side behavior, not the file path"),
)

# Asset bodies that explicitly opt-out. Empty today; reserved for
# tier-aware skills whose body documents the token as a token (e.g.
# a presence-check pattern that names the path it gates on).
OPT_OUTS: frozenset[str] = frozenset()


def _iter_common_tier_assets():
    # Scans every shipped command / agent / skill body. (The harness-dev
    # deploy tier was retired, so there is no longer a tier carve-out —
    # all assets ship to every consumer and must clear the token scan.)
    for root in COMMON_TIER_ROOTS:
        if not root.exists():
            continue
        if root.name == "skills":
            for skill_dir in root.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    yield skill_md
        else:
            for asset in root.glob("*.md"):
                yield asset


@pytest.mark.parametrize(
    "asset_path,token,reason,fix",
    [
        (asset, tok, reason, fix)
        for asset in _iter_common_tier_assets()
        for tok, reason, fix in FORBIDDEN_TOKENS
    ],
    ids=lambda x: x.name if hasattr(x, "name") else str(x),
)
def test_common_tier_asset_avoids_internal_reference(asset_path, token, reason, fix):
    body = asset_path.read_text(encoding="utf-8")
    if asset_path.name in OPT_OUTS:
        pytest.skip(f"{asset_path.name} opted out")
    # Permit references that are explicitly wrapped in a presence
    # check (`[ -d bench/ ]` / `if Path(...).exists():`) — these
    # degrade gracefully for adopters.
    head = token.split("/")[0]
    presence_pattern = re.compile(
        rf"(?:\[\s*-[ed]\s+[^]]*{re.escape(head)}|"
        rf"Path\([^)]*{re.escape(head)}[^)]*\)\.exists\(\))"
    )
    if presence_pattern.search(body):
        return
    if token in body:
        pytest.fail(
            f"{asset_path.relative_to(REPO_ROOT)} references {token!r} "
            f"({reason}). Fix direction: {fix}."
        )
