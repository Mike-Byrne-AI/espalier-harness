"""TP-89 — folder CLAUDE.md routers contract.

Pins five invariants on every named router:

1. Exists at the expected path.
2. Is small (<=20 lines) — routers are procedural anchors, not
   content stores.
3. Declares `**Doing:**` and `**Don't break:**` within the first
   10 lines.
4. Every `Read first:` link resolves to a real file (no dead
   pointers to memory/).
5. No TP-NN pack identifiers in router bodies — routers are
   visible to any Claude session walking the subtree, including
   sessions in adopter repos that have cloned the harness.
   Internal IDs leak harness context.
"""

from __future__ import annotations

# slow-exempt: the only subprocess calls are `git ls-files '*CLAUDE.md'` enumerations
# (`_discover_routers` and the population pin's independent restatement of it) — one
# fast index read each, no repo walk.

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tracked ``CLAUDE.md`` files that are NOT folder routers. Each carries the reason it
# is not one: an exclusion inside a mechanical gate is itself an assertion, and a
# derivation whose exclusions are unexplained is a hand-list with extra steps.
_NOT_ROUTERS: dict[str, str] = {
    # Whole-project governance — priority order, core rules, the architecture and hook
    # tables. A different artifact at a different altitude, and it satisfies none of the
    # five router contracts (308 lines, no `**Doing:**`, no `**Read first:**`).
    "CLAUDE.md": "root project-governance doc, not a folder router",
    # Byte-identical mirror of ``task-packs/CLAUDE.md``; parity is pinned separately.
    # Its `**Read first:**` target ``../.claude/skills/...`` is correct FOR THE SOURCE
    # and resolves from here to ``espalier/assets/.claude/``, which does not exist (only
    # the dash-less ``espalier/assets/claude/`` does). The link is right and the location
    # is wrong, which is exactly what "a mirror, not an authored router" means — so the
    # mirror can never satisfy ``test_router_read_first_link_resolves`` and enrolling it
    # would red on the SoT's correctness.
    "espalier/assets/task-packs/CLAUDE.md": "byte-mirror of task-packs/CLAUDE.md",
}


def _discover_routers() -> tuple[tuple[str, str], ...]:
    """Every git-tracked folder ``CLAUDE.md`` minus ``_NOT_ROUTERS``, as
    ``(relpath, label)`` pairs.

    Derived rather than hand-listed, and the hand-list is why: it named 7 routers while
    the tree carried 12, so ``tools/cc/CLAUDE.md`` sat at 23 lines against a cap of 20
    with the whole module green — it escaped the contract by never being in the list.
    Two more (``espalier/``, ``tests/``) sat at exactly 20, one line from the same
    silent exit. A guard whose population is authored by hand only ever guards what
    someone remembered to type.

    ``git ls-files`` (NOT ``Path.rglob``) so only committed surface is walked and a new
    folder router auto-enrols — the same property, and the same spelling, as the sibling
    contract in ``tests/test_ladder_claudemd_pointers.py``. Empty on a non-git tree, and
    ``test_router_population_is_the_whole_tracked_tree`` is the visible fail-closed
    signal for that case (a parametrize over an empty list would silently cover nothing).
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "*CLAUDE.md"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return ()
    return tuple(
        (rel, f"{rel.rsplit('/', 1)[0]} router")
        for rel in sorted(out.split())
        if rel.endswith("CLAUDE.md") and rel not in _NOT_ROUTERS
    )


EXPECTED_ROUTERS: tuple[tuple[str, str], ...] = _discover_routers()

ROUTER_MAX_LINES = 20

_READ_FIRST_LINK_RE = re.compile(
    r"\*\*Read first:\*\*.*?\[[^\]]+\]\(([^)]+)\)",
    re.IGNORECASE,
)

_TP_ID_RE = re.compile(r"\bTP-\d+\b")


class TestFolderClaudeMdRouters:
    """TP-89 — folder router contract."""

    @pytest.mark.parametrize("rel_path,label", EXPECTED_ROUTERS)
    def test_router_exists(self, rel_path, label):
        path = REPO_ROOT / rel_path
        assert path.is_file(), (
            f"{label} missing at {rel_path} — TP-89 incomplete"
        )

    @pytest.mark.parametrize("rel_path,label", EXPECTED_ROUTERS)
    def test_router_under_line_limit(self, rel_path, label):
        path = REPO_ROOT / rel_path
        if not path.is_file():
            pytest.skip(f"{label} missing — covered by test_router_exists")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= ROUTER_MAX_LINES, (
            f"{label} is {len(lines)} lines; routers must stay "
            f"<={ROUTER_MAX_LINES} (procedural anchor, not content store)"
        )

    @pytest.mark.parametrize("rel_path,label", EXPECTED_ROUTERS)
    def test_router_has_required_headers(self, rel_path, label):
        path = REPO_ROOT / rel_path
        if not path.is_file():
            pytest.skip(f"{label} missing — covered by test_router_exists")
        head = "\n".join(
            path.read_text(encoding="utf-8").splitlines()[:10]
        )
        assert "**Doing:**" in head, (
            f"{label} missing `**Doing:**` in first 10 lines"
        )
        assert "**Don't break:**" in head, (
            f"{label} missing `**Don't break:**` in first 10 lines"
        )

    @pytest.mark.parametrize("rel_path,label", EXPECTED_ROUTERS)
    def test_router_read_first_link_resolves(self, rel_path, label):
        """Every `Read first:` link must point to a real file.
        Dead pointers defeat the router's purpose."""
        path = REPO_ROOT / rel_path
        if not path.is_file():
            pytest.skip(f"{label} missing — covered by test_router_exists")
        text = path.read_text(encoding="utf-8")
        match = _READ_FIRST_LINK_RE.search(text)
        assert match, (
            f"{label} has no `**Read first:** [...](path)` link"
        )
        link_target = match.group(1)
        target = (path.parent / link_target).resolve()
        assert target.is_file(), (
            f"{label} `Read first:` points to non-existent file: "
            f"{link_target} (resolved: {target})"
        )

    @pytest.mark.parametrize("rel_path,label", EXPECTED_ROUTERS)
    def test_router_has_no_internal_pack_ids(self, rel_path, label):
        """Routers must not name internal TP-NN identifiers. Pack
        IDs are harness-internal context that leaks if the router
        is read in an adopter repo that has cloned the harness."""
        path = REPO_ROOT / rel_path
        if not path.is_file():
            pytest.skip(f"{label} missing — covered by test_router_exists")
        text = path.read_text(encoding="utf-8")
        stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        leaks = _TP_ID_RE.findall(stripped)
        assert not leaks, (
            f"{label} contains internal pack identifiers in prose: "
            f"{leaks}. Use descriptive names (e.g., 'autoprune contract' "
            f"not 'TP-86'). Code-fenced references are allowed."
        )


def test_router_population_is_the_whole_tracked_tree():
    """Pin the POPULATION, not just each router's verdict.

    The five contracts above are parametrized over ``EXPECTED_ROUTERS``, and a
    parametrize over an EMPTY tuple generates zero cases and reports success — so
    without this test the whole module can go green while guarding nothing. That is
    not hypothetical: it is how the hand-list hid ``tools/cc/CLAUDE.md`` at 23 lines
    against a cap of 20, just at a different granularity.

    THE DUPLICATION IS THE GATE. The enumeration below deliberately restates the
    ``git ls-files`` call and the exclusion rule instead of calling
    ``_discover_routers``. Sharing them would move both sides together, and this test
    would go green through the exact edit it exists to catch — a router quietly dropped
    from the population. Narrowing is then reachable only by ADDING a ``_NOT_ROUTERS``
    entry, which is visible in review and obliged to carry its reason.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "*CLAUDE.md"],
            capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("`git ls-files` unavailable — not a dev tree / fresh clone")
    tracked = {f for f in out.split() if f.endswith("CLAUDE.md")}
    if not tracked:
        pytest.skip("`git ls-files` yielded no CLAUDE.md — not a dev tree / fresh clone")

    expected = tracked - set(_NOT_ROUTERS)
    enrolled = {rel for rel, _label in EXPECTED_ROUTERS}
    missing = sorted(expected - enrolled)
    extra = sorted(enrolled - expected)
    assert not missing and not extra, (
        "the folder-router contract no longer covers every tracked folder CLAUDE.md.\n"
        f"  enrolled {len(enrolled)}, expected {len(expected)}\n"
        f"  tracked but NOT enrolled ({len(missing)}): {missing}\n"
        f"  enrolled but not tracked ({len(extra)}): {extra}\n"
        "If a file genuinely is not a folder router, add it to _NOT_ROUTERS WITH ITS "
        "REASON — do not narrow the discovery."
    )
    assert len(enrolled) >= 7, (
        f"only {len(enrolled)} routers enrolled; the population collapsed. This "
        "asserts a FLOOR, not a census: routers are expected to be added over time, "
        "but a discovery that silently returns near-nothing leaves five parametrized "
        "contracts asserting over an empty set while reporting success."
    )


def test_excluded_files_are_tracked_and_still_need_their_exclusion():
    """Every ``_NOT_ROUTERS`` entry must still exist AND still fail the router contract.

    An exclusion outlives its reason silently. If a listed file is deleted, or is
    reshaped into a genuine router, the entry becomes a permanent hole that nothing
    reports. This makes the exclusion list self-expiring: it reds when an entry is no
    longer needed, which is the only way an allowlist inside a gate stays honest.
    """
    for rel, reason in _NOT_ROUTERS.items():
        path = REPO_ROOT / rel
        assert path.is_file(), (
            f"_NOT_ROUTERS names {rel} ({reason}) but that file no longer exists — "
            "drop the entry."
        )
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        head = "\n".join(lines[:10])
        match = _READ_FIRST_LINK_RE.search(text)
        link_ok = bool(match) and (path.parent / match.group(1)).resolve().is_file()
        satisfies_all = (
            len(lines) <= ROUTER_MAX_LINES
            and "**Doing:**" in head
            and "**Don't break:**" in head
            and link_ok
            and not _TP_ID_RE.findall(re.sub(r"```.*?```", "", text, flags=re.DOTALL))
        )
        assert not satisfies_all, (
            f"_NOT_ROUTERS excludes {rel} as {reason!r}, but it now satisfies every "
            "router contract — either it became a real router (remove the exclusion "
            "and let it enrol) or the reason changed and the comment is now false."
        )
