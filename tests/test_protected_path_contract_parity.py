"""TP-05 §7 — CI guard vs surface contract parity.

``tools/cc/ci_guard.py`` enumerates protected files and prefixes
locally to keep its zero-espalier-import invariant. The public
contract (``espalier.surface_contract``) must agree, otherwise CI
denies merges that the published contract didn't warn about.

Loaded by file path so the parity test doesn't drag espalier into the
ci_guard module's import graph.
"""
from __future__ import annotations

import importlib.util
import re
import textwrap
from pathlib import Path


from espalier import surface_contract
from tests._git_oracle import require_tracked_paths

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


def _load_ci_guard_module():
    """Load tools/cc/ci_guard.py without importing it as a builder package."""
    candidate = REPO_ROOT / "tools" / "cc" / "ci_guard.py"
    spec = importlib.util.spec_from_file_location("_cc_ci_guard", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot locate ci_guard.py at {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_hook_utils_module():
    """Load tools/cc/hooks/_hook_utils.py — home of `harness_protected_prefixes`.

    This is the OPERATIVE runtime source. `_protected_zones.PROTECTED_PREFIXES`
    is a *declaration* list whose own comment (lines 46-50) marks the
    `espalier/` entry NON-OPERATIVE: `_is_protected` iterates
    `harness_protected_prefixes(root)`, which adds `espalier/` only on the
    self-host repo and never on an adopter's. Reading the declaration instead
    was a measured error in the first draft of this module — it made the
    rendered stanza claim `espalier/` is runtime-protected everywhere.
    """
    candidate = REPO_ROOT / "tools" / "cc" / "hooks" / "_hook_utils.py"
    spec = importlib.util.spec_from_file_location("_cc_hook_utils", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot locate _hook_utils.py at {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_protected_zones_module():
    """Load tools/cc/hooks/_protected_zones.py — write_guard's RUNTIME zone.

    `write_guard.py` re-exports these two names verbatim (write_guard.py:109),
    but re-exporting the NAME is not the deny path: `_is_protected` iterates
    `_hook_utils.harness_protected_prefixes`, so this module's
    `PROTECTED_PREFIXES` is a DECLARATION list, not what the deny consults.
    Only `PROTECTED_FILES` is read from here; prefixes come from
    `runtime_prefixes()`. An earlier draft of this docstring claimed this was
    "the same inventory the live deny consults" — measured false: the
    `espalier/` entry is marked NON-OPERATIVE in the source itself, and
    `harness_protected_prefixes` omits it on an adopter repo.
    """
    candidate = REPO_ROOT / "tools" / "cc" / "hooks" / "_protected_zones.py"
    spec = importlib.util.spec_from_file_location("_cc_protected_zones", candidate)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Cannot locate _protected_zones.py at {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Exact-file parity
# ---------------------------------------------------------------------------


class TestProtectedFilesParity:
    def test_ci_guard_files_equal_surface_contract(self):
        ci_guard = _load_ci_guard_module()
        ci = set(ci_guard.PROTECTED_FILES)
        contract = set(surface_contract.get_protected_ci_files())

        only_in_contract = sorted(contract - ci)
        only_in_ci = sorted(ci - contract)

        assert ci == contract, (
            "PROTECTED_FILES drift detected between ci_guard and surface_contract.\n"
            f"  In surface_contract but NOT in ci_guard: {only_in_contract}\n"
            f"  In ci_guard but NOT in surface_contract: {only_in_ci}"
        )


# ---------------------------------------------------------------------------
# Prefix parity
# ---------------------------------------------------------------------------


class TestProtectedPrefixesParity:
    def test_ci_guard_prefixes_equal_surface_contract(self):
        ci_guard = _load_ci_guard_module()
        ci = set(ci_guard.PROTECTED_PREFIXES)
        contract = set(surface_contract.get_protected_ci_prefixes())

        only_in_contract = sorted(contract - ci)
        only_in_ci = sorted(ci - contract)

        assert ci == contract, (
            "PROTECTED_PREFIXES drift detected between ci_guard and surface_contract.\n"
            f"  In surface_contract but NOT in ci_guard: {only_in_contract}\n"
            f"  In ci_guard but NOT in surface_contract: {only_in_ci}"
        )


# ---------------------------------------------------------------------------
# Policy pin: .github/workflows/ is CI-protected
# ---------------------------------------------------------------------------


class TestWorkflowProtectionPolicy:
    """Pack §3 — .github/workflows/ protection is the recommended policy.

    Workflow mutation can change release, test, or benchmark enforcement,
    so any .github/workflows/*.yml change requires HARNESS-UPDATE-APPROVED.
    Pin both sides explicitly so a future "make CI lighter" PR can't
    quietly remove this coverage.
    """

    def test_contract_protects_workflows_prefix(self):
        prefixes = surface_contract.get_protected_ci_prefixes()
        assert ".github/workflows/" in prefixes, (
            "surface_contract must protect '.github/workflows/' (TP-05 §3 policy)"
        )

    def test_ci_guard_protects_workflows_prefix(self):
        ci_guard = _load_ci_guard_module()
        assert ".github/workflows/" in ci_guard.PROTECTED_PREFIXES, (
            "ci_guard must protect '.github/workflows/' (TP-05 §3 policy)"
        )

    def test_workflow_change_requires_approval_marker(self):
        """A .github/workflows/test.yml change is policy-protected.

        NOTE the scope: this asserts PREFIX MEMBERSHIP only — that workflow
        YAML is inside the CI-protected inventory. It does NOT assert that such
        a change requires the approval marker, and it must not be read that
        way: the marker requirement is scoped by repo posture, and a genuine
        Dependabot action-ref bump is exempt. The failure message here used to
        claim the stronger rule, which meant the one string a future operator
        reads on failure stated something no longer true. The real marker
        behaviour is pinned in tests/test_ci_guard.py
        (TestApprovalMarkerRepoPosture, TestDependabotActionBumpAllowance).
        """
        ci_guard = _load_ci_guard_module()
        # is_protected check via prefix match
        assert any(
            ".github/workflows/test.yml".startswith(prefix)
            for prefix in ci_guard.PROTECTED_PREFIXES
        ), (
            "TP-05 §3: .github/workflows/*.yml must be inside ci_guard's "
            "protected-path inventory (marker requirement is scoped separately "
            "— see tests/test_ci_guard.py)"
        )


# ---------------------------------------------------------------------------
# Approval marker contract
# ---------------------------------------------------------------------------


class TestApprovalMarkerConstant:
    def test_approval_marker_is_documented_string(self):
        ci_guard = _load_ci_guard_module()
        assert ci_guard.APPROVAL_MARKER == "HARNESS-UPDATE-APPROVED", (
            "Public docs reference 'HARNESS-UPDATE-APPROVED' literally — "
            "renaming this constant breaks the operator contract"
        )

# ---------------------------------------------------------------------------
# Doc parity — the surfaces that TELL a contributor which paths need the marker
# ---------------------------------------------------------------------------

#: Sentinels bounding the derived CI-gated-path block. HTML comments, so the
#: markers render invisibly in every markdown viewer while still being an exact
#: byte anchor. The BEGIN literal is deliberately built by implicit string
#: concatenation: written on one source line it would appear verbatim in THIS
#: file's bytes, enrolling the test module in its own population.
BLOCK_BEGIN = (
    "<!-- BEGIN GENERATED: ci-gated-paths — rendered from tools/cc/ci_guard.py"
    " + tools/cc/hooks/_protected_zones.py, do not hand-edit -->"
)
BLOCK_END = "<!-- END GENERATED: ci-gated-paths -->"


def runtime_only_paths(ci_guard, zones) -> tuple[str, ...]:
    """The runtime zone MINUS the CI zone — the over-claim vocabulary, derived.

    `ci_guard.is_protected` is the oracle, NOT a set difference over the raw
    strings. The two inventories are not parallel: `tools/cc/hooks/` is CI-gated
    and sits INSIDE the runtime prefix `tools/cc/`, so subtracting strings would
    answer a question about spelling where the question is about coverage. Both
    happen to agree today; `is_protected` keeps agreeing if a future CI row is
    nested under a runtime prefix.

    Order is deterministic: runtime prefixes in declaration order, then runtime
    files SORTED — `_protected_zones.PROTECTED_FILES` is a `set`, whose
    iteration order is not a contract.
    """
    runtime = runtime_prefixes() + tuple(sorted(zones.PROTECTED_FILES))
    return tuple(rel for rel in runtime if not ci_guard.is_protected(rel))


def runtime_prefixes() -> tuple[str, ...]:
    """The prefixes write_guard's deny ACTUALLY iterates, for THIS repo."""
    return tuple(_load_hook_utils_module().harness_protected_prefixes(REPO_ROOT))


def runtime_protected(token: str, zones) -> bool:
    """Would write_guard's zone check cover `token` on this repo?"""
    return token in zones.PROTECTED_FILES or any(
        token.startswith(prefix) for prefix in runtime_prefixes()
    )


#: Every `` `backticked` `` run on one line. The over-claim vocabulary is not a
#: fixed token list: real over-claims name a concrete FILE (`espalier/cli.py`),
#: not a bare prefix. Matching only the four prefix tokens let five of six
#: realistic over-claim spellings through — including the one this class's own
#: docstring cites as the motivating harm. Measured 2026-08-21.
_BACKTICK_TOKEN = re.compile(r"`([^`\n]+)`")


def overclaimed_tokens(para: str, ci_guard, zones) -> list[str]:
    """Backticked tokens in `para` that write_guard protects and ci_guard does not."""
    return sorted({
        tok for tok in _BACKTICK_TOKEN.findall(para)
        if runtime_protected(tok, zones) and not ci_guard.is_protected(tok)
    })


_LIST_ITEM = re.compile(r"\s*[-*+] ")


def _list_item_windows(para: str) -> list[str]:
    """A bullet list is N claims, not one.

    Markdown puts no blank line between list items, so the plain `\n\n` split
    hands the whole list back as a single window — and one bullet mentioning the
    marker then taints every other bullet in the list. Measured on the real
    pre-fix `.claude/agents/code-reviewer.md`: the "keep `espalier/hook_contract.py`
    in sync with its hook twin" pitfall flagged as an over-claim purely because
    the marker bullet sat four items above it. Correct prose, red guard — the
    shape that gets a guard switched off.

    A preamble that ends in `:` genuinely scopes the items under it, so a
    paragraph shaped that way stays whole.
    """
    lines = para.split("\n")
    if not any(_LIST_ITEM.match(ln) for ln in lines):
        return [para]
    first = next(i for i, ln in enumerate(lines) if _LIST_ITEM.match(ln))
    preamble = "\n".join(lines[:first]).strip()
    if preamble.endswith(":") or preamble.startswith("#"):
        return [para]

    windows: list[str] = []
    current: list[str] = []
    for line in lines:
        if _LIST_ITEM.match(line) and current:
            windows.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        windows.append("\n".join(current))
    return windows


def marker_windows(text: str) -> list[str]:
    """The units a marker claim can span.

    Two corrections to a plain `text.split("\n\n")`, both measured:

    * A heading line, or a line ending in `:`, INTRODUCES the block after it —
      "### PRs needing THE-MARKER" followed by a list of paths is the single
      most natural way to write the instruction doc this scan polices, and the
      blank line split the marker away from the paths. Glued.
    * A bare bullet list is split back into one window PER ITEM, because
      otherwise a marker in one bullet taints every other bullet in the list.

    Deliberately NOT full heading-scoped sections: measured, that lights up 12
    files including docs/CONVENTIONS.md and docs/SHARP_EDGES.md. The tight scope
    is doing real precision work; widen it and the exemption list has to grow to
    compensate, which is how a detector becomes a formality.
    """
    windows: list[str] = []
    lead: str | None = None
    for para in text.split("\n\n"):
        stripped = para.strip()
        if lead is not None:
            windows.append(f"{lead}\n\n{para}")
        else:
            windows.extend(_list_item_windows(para))
        lead = para if (stripped.startswith("#") or stripped.endswith(":")) else None
    return windows


def render_ci_gated_block(ci_guard, zones) -> str:
    """The ONE definition of the block. Every doc must carry it byte-for-byte.

    Two stanzas, both derived. The first is the CI-gated set: prefix rows in
    ``ci_guard.PROTECTED_PREFIXES`` declaration order, then file rows in
    ``PROTECTED_FILES`` declaration order. The second names the runtime-only
    paths as explicitly NOT CI-gated.

    The second stanza is the load-bearing one for the widening detector below.
    While that contrast was hand-written prose, no matcher could separate "names
    `espalier/` to CONTRAST it" from "names `espalier/` to CLAIM it is gated" —
    the two are spelled identically — which is why the old exemption keyed on the
    word ``write_guard`` and thereby exempted the exact form of the bug. Once the
    contrast is GENERATED, the rule needs no such vocabulary: inside this block a
    runtime-only path is expected, anywhere else in a marker-bearing paragraph it
    is an over-claim.
    """
    rows = [
        f"- `{prefix}` — prefix: every path under it"
        for prefix in ci_guard.PROTECTED_PREFIXES
    ]
    rows += [f"- `{rel}`" for rel in ci_guard.PROTECTED_FILES]

    runtime_only = runtime_only_paths(ci_guard, zones)
    # A generated block SHRINKS SILENTLY -- it just gets shorter and every test
    # still passes -- so refuse rather than render a stanza that names nothing.
    # Same floor discipline as scripts/generate_doc_regions.py::Region.render.
    if not runtime_only:
        raise ValueError(
            "runtime_only_paths() derived an EMPTY set, so the contrast stanza "
            "would name nothing and the widening detector below would have no "
            "vocabulary to match. Either the runtime and CI zones genuinely "
            "converged (then this whole class needs rewriting, not a shorter "
            "block) or a derivation broke. Refusing to render."
        )
    named = ", ".join(f"`{rel}`" for rel in runtime_only)
    # textwrap at a fixed width, so the stanza reflows deterministically as the
    # derived list grows instead of drifting into one very long source line.
    stanza = textwrap.fill(
        "`write_guard` protects a WIDER zone at RUNTIME — a different policy, "
        f"not this one restated. {named} are runtime-protected but are NOT "
        "themselves in the CI-gated set above, so a PR touching one needs no "
        "marker unless it also matches a row above.",
        width=79, break_long_words=False, break_on_hyphens=False,
    )
    return "\n".join([BLOCK_BEGIN, *rows, "", stanza, BLOCK_END])


def _extract_block(text: str) -> str | None:
    """The BEGIN..END span INCLUSIVE, or None when the pair is not present."""
    begin = text.find(BLOCK_BEGIN)
    if begin == -1:
        return None
    end = text.find(BLOCK_END, begin)
    if end == -1:
        return None
    return text[begin:end + len(BLOCK_END)]


def _without_block(text: str) -> str:
    """`text` with the BEGIN..END span removed.

    STRIP, never skip the file. Skipping made carrying the block an immunity
    from prose scanning — and the carriers are exactly the files where the
    over-claim has historically lived, so the exemption covered the entire
    population at risk. Measured 2026-08-21: the historical over-claim appended
    as a NEW paragraph to a carrier left all arms green. Stripping is safe only
    because the contrast prose is now GENERATED inside the block; while it was
    hand-written there was no way to tell it apart from the defect.
    """
    span = _extract_block(text)
    return text if span is None else text.replace(span, "")


#: Non-vacuity floors for the two populations below. TRIPWIRES against a
#: collapsed or foreign answer, not running counts, so each sits well under the
#: live number (992 tracked / 287 tracked `.md` on 2026-08-21) and moves only
#: when the tree genuinely shrinks. §C21: a raw `git ls-files` here would return
#: rc 0 with zero rows from a gitignored cwd, and every arm below would pass
#: having checked nothing.
_TRACKED_FLOOR = 500
_TRACKED_MD_FLOOR = 150


def _tracked(*patterns: str, minimum: int) -> list[str]:
    """The tracked population, or `GitAnswerUnavailable` — never a silent []."""
    return require_tracked_paths(
        REPO_ROOT, *patterns, minimum=minimum,
        what=f"tracked paths matching {patterns or ('<all>',)}",
    )


class TestCIGatedSetIsDerivedNotRestated:
    """A contributor doc must carry the DERIVED gated-path block, not a retype.

    `write_guard` (runtime) protects a WIDER zone than `ci_guard` (merge gate):
    the runtime set also covers `espalier/` and `cc/`. They are two deliberately
    different policies, and contributor-facing surfaces kept collapsing them
    into one restatement — telling an outside contributor that an
    `espalier/cli.py` PR needs `HARNESS-UPDATE-APPROVED` when
    `ci_guard.is_protected()` returns False for it. The cost lands on someone
    who does not know the difference: friction on a PR that would have merged.

    WHY THE PREVIOUS FORM WAS A FALSE PIN — do not "simplify" back to it.
    ------------------------------------------------------------------
    The class here before scanned each doc's marker paragraph for the literal
    tokens ``` `espalier/` ``` and ``` `cc/` ```. It was green against its own
    subject, two independently measured ways:

    1. **By-reference naming dodges a token scan.** The genuine defective text
       (``git show 3060e20^:.claude/agents/code-reviewer.md``) read "see
       `write_guard.py` protected zones" — it pointed AT the runtime zone
       instead of quoting it, so there was no token to match and the scan
       found nothing. Restoring that exact file left the class 8 passed, RC 0.
    2. **The exemption exempted the bug.** Its own carve-out cleared any
       paragraph containing the string ``write_guard`` — which is precisely the
       vocabulary the defective form used to do the pointing.

    Its `_CONTRIBUTOR_SURFACES` also failed open: a `if not path.is_file():
    continue` meant renaming CONTRIBUTING.md left the class 8 passed too.

    The replacement inverts the test. Instead of hunting for a wrong string
    (unbounded — every future paraphrase is a new evasion), it requires the
    RIGHT string: one block, rendered from `ci_guard` itself, byte-pinned
    wherever it appears, and required to be present on a named seed set that
    fails closed on a rename.

    WHY THE PREDICATE IS THE RUNTIME ZONE, NOT THE CI ZONE
    ------------------------------------------------------
    The first replacement scanned for 2+ members of the CI-gated set — a PROXY
    for "is this paragraph enumerating the set". It failed both directions,
    measured: it false-positived on `docs/INSTALL-CI.md`'s "install-ci deploys
    exactly one workflow" sentence (which enumerates nothing), and it could not
    detect the over-claim at all, because an over-claim names the RUNTIME-only
    zone — by definition not members — and scored 0.

    Arm 3 now asks the real question: does a marker-bearing paragraph name a
    path that write_guard protects at runtime but ci_guard does NOT gate? That
    set IS the over-claim vocabulary, so the threshold is 1, and both sides are
    derived (`runtime_only_paths`) rather than listed.

    That predicate only became usable once the contrast prose moved INSIDE the
    generated block. While it was hand-written, "names `espalier/` to contrast
    it" and "names `espalier/` to claim it is gated" were spelled identically —
    which is why the old exemption keyed on the word ``write_guard`` and so
    exempted the exact form of the bug. Generated, the rule needs no such
    vocabulary: inside the block a runtime-only path is expected; anywhere else
    beside the marker it is an over-claim. That is what makes stripping the
    block span (rather than skipping the whole file) safe — and stripping is
    what closes the hole where carrying the block bought immunity from prose
    scanning, in exactly the files where this defect has always lived.
    """

    # Path prefixes a contributor doc must NEVER present as merge-gated, computed
    # as "in the runtime zone but not the CI zone". Listed as representative files
    # so the assertion runs through `is_protected` rather than comparing strings.
    _RUNTIME_ONLY_REPRESENTATIVES = (
        "espalier/cli.py",
        "cc/GOAL.md",
    )

    #: The SEED — the source-of-truth docs that must instruct a
    #: contributor with the derived block. Hand-written on purpose and read
    #: fail-CLOSED below: this is the "did someone rename or delete the surface"
    #: witness, and a derived population cannot notice its own disappearance.
    #: Mirrors are NOT listed; they are caught by the byte-parity arm, which
    #: derives its population from the sentinel.
    _CONTRIBUTOR_SURFACES = (
        "CONTRIBUTING.md",
        ".claude/agents/code-reviewer.md",
    )

    #: The adopter-facing install guide is NOT a carrier. It is an `init` seed
    #: doc (`managed_inventory.get_seed_docs()`) AND a mirror source, and
    #: `cli._seed_redeploy_decision` returns "preserve" PERMANENTLY once an
    #: adopter's bytes diverge — so a "do not hand-edit" block there freezes on
    #: their first edit into something they cannot regenerate, having no
    #: `scripts/`. That is the rule `tests/test_doc_regions.py::
    #: TestTheGoverningRuleIsEnforced` enforces for registered regions; this
    #: block is not a registered region, so nothing would have caught it.
    #: It gets prose plus the under-claim arm below instead.
    _UNDERCLAIM_DOC = "docs/INSTALL-CI.md"
    _UNDERCLAIM_ANCHOR = "The protected paths:"

    #: Docs allowed to name a runtime-only path beside the marker.
    #:
    #: RE-MEASURED from scratch when the predicate changed from "names 2+ members
    #: of the CI-gated set" to "names a runtime-only path" (2026-08-21). Three
    #: entries stopped earning their place and were DROPPED rather than carried
    #: forward: `docs/session-archive.md` (0), `memory/CONVERGENCE_LEDGER.md` (0)
    #: and `docs/CONVENTIONS.md` (0 — it scored 1 under the old predicate, one
    #: token below that threshold, so it was the entry most likely to swallow a
    #: real future defect). Each survivor states its MEASURED hit count; an
    #: exemption nobody can point at a hit for is how a guard stops guarding.
    _ENUMERATION_EXEMPT = (
        # 1 paragraph — a release-note entry narrating a past red-team round,
        # which names the runtime tree while recounting what was found there.
        # It describes history; it does not instruct anyone to title a PR.
        "CHANGELOG.md",
        # The session log: a RECORD surface by the same rule as the two above.
        # One log row is one paragraph and narrates a whole session, so a row
        # that records the DEF-338 marker change beside three other lanes'
        # runtime paths is history, not an instruction; the window model this
        # test uses (marker-bearing paragraph names a runtime path) does not
        # fit a table row that is a session. Reddened first at f2656e3 (the
        # Group 3 memory row), read in the §C8 tier of 2026-09-11.
        "ESPALIER_MEMORY.md",
    )

    def test_runtime_only_paths_are_genuinely_not_ci_gated(self):
        """Guards the premise. If ci_guard ever widens to these, the doc arm
        below is asserting a distinction that no longer exists."""
        ci_guard = _load_ci_guard_module()
        # Same floor reasoning as the seed arm: emptied, the loop below runs
        # zero times and this premise guard passes having checked nothing.
        assert len(self._RUNTIME_ONLY_REPRESENTATIVES) >= 2, (
            "the runtime-only representatives were emptied; this arm guards the "
            "premise the whole class rests on and cannot do it over no paths."
        )
        for rel in self._RUNTIME_ONLY_REPRESENTATIVES:
            assert not ci_guard.is_protected(rel), (
                f"{rel} is now CI-gated, so the runtime/CI distinction this class "
                "documents has changed. Re-derive _RUNTIME_ONLY_REPRESENTATIVES "
                "and update the contributor docs to match — do not delete this test."
            )

    def test_every_sentinel_bearing_file_is_byte_current(self):
        """Wherever the block appears — source doc or byte-mirror — it must equal
        what `ci_guard` renders TODAY. Population derived from the sentinel, so a
        new carrier (or a mirror nobody remembered) enrolls itself."""
        ci_guard = _load_ci_guard_module()
        expected = render_ci_gated_block(ci_guard, _load_protected_zones_module())

        carriers: list[str] = []
        stale: list[str] = []
        for rel in _tracked(minimum=_TRACKED_FLOOR):
            path = REPO_ROOT / rel
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if BLOCK_BEGIN.encode("utf-8") not in raw:
                continue
            carriers.append(rel)
            decoded = raw.decode("utf-8")
            # _extract_block reads the FIRST pair only, so a second block would
            # rot unwatched -- the shape scripts/generate_doc_regions.py::splice
            # refuses for the same reason ("any later region would be silently
            # stale"). One block per file, checked rather than assumed.
            assert decoded.count(BLOCK_BEGIN) == 1, (
                f"{rel} carries {decoded.count(BLOCK_BEGIN)} ci-gated-paths "
                "blocks. Only the first is validated, so any later one rots "
                "unnoticed. Keep exactly one per file."
            )
            found = _extract_block(decoded)
            if found != expected:
                stale.append(rel)

        # A sentinel typo (or a botched rename) would otherwise empty the
        # population and pass this arm vacuously with zero files checked.
        assert carriers, (
            "no tracked file carries the ci-gated-paths BEGIN sentinel. Either "
            "the block was removed from every doc or BLOCK_BEGIN no longer "
            "matches what is written in them — check both before relaxing this."
        )
        assert not stale, (
            "ci-gated-paths block is stale in:\n  " + "\n  ".join(stale)
            + "\n\nThe block is rendered from tools/cc/ci_guard.py; re-render it "
            "and paste it into each file above (then run the mirror syncs: "
            "scripts/sync_claude_mirrors.py, scripts/sync_asset_docs.py).\n\n"
            "Expected:\n" + expected
        )

    def test_declared_contributor_surfaces_carry_the_block(self):
        """FAILS CLOSED. The old form skipped a missing path with `continue`, so
        renaming CONTRIBUTING.md left it green — the seed asserted nothing."""
        # The seed is HAND-written, so unlike arm 1's derived population it can
        # be emptied by an ordinary edit -- and both lists below would then come
        # back empty and pass. Arm 1 guards its population; this guards mine.
        assert len(self._CONTRIBUTOR_SURFACES) >= 2, (
            "the contributor-surface seed has shrunk below the declared "
            "source-of-truth docs. It is the fail-closed witness for this class; "
            "shrinking it IS the failure, not a smaller check."
        )
        missing_file: list[str] = []
        missing_block: list[str] = []
        for rel in self._CONTRIBUTOR_SURFACES:
            path = REPO_ROOT / rel
            if not path.is_file():
                missing_file.append(rel)
                continue
            if BLOCK_BEGIN not in path.read_text(encoding="utf-8"):
                missing_block.append(rel)

        assert not missing_file, (
            "declared contributor surface(s) no longer exist:\n  "
            + "\n  ".join(missing_file)
            + "\n\nIf you renamed or moved one, update _CONTRIBUTOR_SURFACES in "
            "this test IN THE SAME COMMIT. Do NOT make this skip: a missing "
            "surface is exactly the case the seed exists to notice."
        )
        assert not missing_block, (
            "contributor surface(s) missing the ci-gated-paths block:\n  "
            + "\n  ".join(missing_block)
            + "\n\nThese docs tell a contributor which PRs need the approval "
            "marker. They must carry the block rendered from ci_guard, not a "
            "hand-typed list and not a pointer at write_guard's wider zone."
        )

    #: (path, must_be_flagged). The negative twins are the point: a predicate
    #: widened from "4 prefix tokens" to "any backticked path" is born weak
    #: without them — it would happily flag every hook script and workflow in
    #: the repo, and the first false red is how a guard gets switched off.
    _OVERCLAIM_TWINS = (
        # runtime-protected AND CI-gated -> naming it beside the marker is CORRECT
        ("tools/cc/hooks/write_guard.py", False),
        ("tools/cc/ci_guard.py", False),
        (".github/workflows/release.yml", False),
        (".espalier/integrity.json", False),
        # runtime-protected but NOT CI-gated -> naming it beside the marker is
        # the over-claim. The first entry is verbatim the harm this class's
        # docstring cites, and it was invisible to the predicate until measured.
        ("espalier/cli.py", True),
        ("tools/cc/_paths.py", True),
        ("cc/GOAL.md", True),
        (".espalier/freshness.json", True),
    )

    def test_the_overclaim_oracle_trips_on_exactly_the_right_paths(self):
        """Both directions, or the detector is decor.

        Missing negative twins is how a widened matcher ships as a false-red
        machine; missing positive twins is how it ships as decoration. Neither
        is observable from a green repo scan, because the live tree contains no
        over-claim — which is the whole reason this arm is synthetic.
        """
        ci_guard = _load_ci_guard_module()
        zones = _load_protected_zones_module()
        marker = ci_guard.APPROVAL_MARKER

        wrong = []
        for path, should_flag in self._OVERCLAIM_TWINS:
            para = f"A PR touching `{path}` needs {marker} in its title."
            flagged = bool(overclaimed_tokens(para, ci_guard, zones))
            if flagged is not should_flag:
                wrong.append(
                    f"{path}: expected {'flag' if should_flag else 'no flag'}, "
                    f"got {'flag' if flagged else 'no flag'}"
                )
        assert not wrong, (
            "the over-claim oracle disagrees with its twins:\n  "
            + "\n  ".join(wrong)
            + "\n\nA path that is BOTH runtime-protected and CI-gated must not "
            "flag (the doc is right); a path that is runtime-protected but not "
            "CI-gated must flag (the doc demands a marker CI never asks for)."
        )

    def test_the_marker_window_keeps_a_heading_or_colon_with_its_list(self):
        """The `\n\n` split alone loses the most natural instruction shape."""
        shapes = (
            "### PRs needing MARK\n\n- `espalier/`",
            "Add MARK when you touch:\n\n- `espalier/`",
        )
        for shape in shapes:
            assert any(
                "MARK" in w and "`espalier/`" in w for w in marker_windows(shape)
            ), (
                "marker_windows() split the marker away from the paths it "
                f"introduces:\n{shape!r}\nA heading-plus-list and a "
                "colon-plus-list are how an instruction doc is actually "
                "written; both escaped the plain paragraph split."
            )

    def test_a_bare_list_does_not_let_one_bullet_taint_another(self):
        """The other direction — and this one is a MEASURED false red.

        Restoring the real pre-fix `.claude/agents/code-reviewer.md` flagged its
        "keep `espalier/hook_contract.py` in sync with its hook twin" bullet as
        an over-claim, purely because the marker bullet sat four items above it
        in the same blank-line-free list. That bullet is correct prose. A guard
        that reds on correct prose is a guard someone switches off, so the
        window splits a bare list per item.
        """
        para = (
            "- Adding a CI-gated file without MARK in the PR title\n"
            "- Editing `espalier/hook_contract.py` without mirroring it into\n"
            "  `tools/cc/hooks/_hook_contract.py` — the two must stay in sync"
        )
        tainted = [
            w for w in marker_windows(para)
            if "MARK" in w and "`espalier/hook_contract.py`" in w
        ]
        assert not tainted, (
            "a bare list is being treated as ONE claim, so the marker in one "
            "bullet reaches a path named in an unrelated bullet:\n"
            + "\n---\n".join(tainted)
        )

    def test_install_ci_prose_names_every_gated_member(self):
        """The adopter install guide gets prose, so prose carries the contract.

        This arm is what replaces the block's guarantee on the one doc that may
        not carry it. The defect it exists to catch is an UNDER-claim, the exact
        inverse of everything else in this class: the shipped list named only
        `.github/workflows/harness-guard.yml` while `ci_guard` gates the whole
        `.github/workflows/` prefix, so an adopter read that `release.yml` needed
        no marker and got blocked at merge with the doc on their side.

        Exact backticked tokens, not substrings. `` `.github/workflows/` `` is
        NOT a substring of `` `.github/workflows/harness-guard.yml` `` — the
        character after `workflows/` is `h`, not a backtick — which is precisely
        the distinction the shipped text got wrong, so a substring check would
        have called the defective doc compliant.
        """
        ci_guard = _load_ci_guard_module()
        members = tuple(ci_guard.PROTECTED_PREFIXES) + tuple(ci_guard.PROTECTED_FILES)
        path = REPO_ROOT / self._UNDERCLAIM_DOC
        assert path.is_file(), (
            f"{self._UNDERCLAIM_DOC} is gone. It is the adopter-facing CI install "
            "guide and the only gated-set surface with no block to pin it; update "
            "_UNDERCLAIM_DOC in the same commit that moved it."
        )
        text = path.read_text(encoding="utf-8")
        # Pinned, not merely asserted in prose: a session that "helpfully" adds
        # this doc to _CONTRIBUTOR_SURFACES and pastes the block would otherwise
        # go fully green and ship the adopter freeze this arm exists to avoid.
        assert BLOCK_BEGIN not in text, (
            f"{self._UNDERCLAIM_DOC} carries the generated block. It must NOT: "
            "it is an `init` seed doc AND a mirror source, so "
            "`cli._seed_redeploy_decision` freezes an adopter's copy the first "
            "time they edit it, leaving them a 'do not hand-edit' block and no "
            "`scripts/` to regenerate. Prose plus this arm is the contract here."
        )
        assert self._UNDERCLAIM_ANCHOR in text, (
            f"{self._UNDERCLAIM_DOC} no longer contains "
            f"{self._UNDERCLAIM_ANCHOR!r}. Without the anchor this arm would "
            "scan an empty section and pass having checked nothing — so it "
            "fails here instead. Re-point _UNDERCLAIM_ANCHOR."
        )
        start = text.index(self._UNDERCLAIM_ANCHOR)
        # ANY heading level ends the section. Keyed to the literal `\n### `,
        # promoting the next heading to `##` silently widened the slice 6x and
        # swallowed the Dependabot paragraph — which backticks
        # `.github/workflows/` — so deleting the bullet this arm guards went
        # GREEN. Measured both ways before and after.
        nxt = re.search(r"^#{1,6} ", text[start:], re.M)
        section = text[start:] if nxt is None else text[start:start + nxt.start()]

        # A prefix may legitimately be written as a glob -- the shipped text used
        # `tools/cc/hooks/**` -- so accept the bare token or a `*`/`**` suffix.
        # Measured why this matters: without it, R8b reded on `tools/cc/hooks/**`,
        # which is CORRECT prose, and a guard that reds on correct prose is a
        # guard someone switches off. It stays precise where it counts:
        # `.github/workflows/harness-guard.yml` still does NOT satisfy
        # `.github/workflows/`, because `harness-guard.yml` is not a glob -- and
        # that exact confusion IS the shipped defect this arm exists to catch.
        def _named(member: str) -> bool:
            for token in _BACKTICK_TOKEN.findall(section):
                if token == member:
                    return True
                # A glob spelling of the same prefix counts: `x/**`, `x/*`,
                # `x/*.yml`. A CONCRETE child does not — `.github/workflows/`
                # is NOT satisfied by `.github/workflows/harness-guard.yml`,
                # and mistaking those two IS the shipped defect this arm
                # catches. The discriminator is a `*` in the remainder.
                if token.startswith(member) and "*" in token[len(member):]:
                    return True
            return False

        missing = [m for m in members if not _named(m)]
        assert not missing, (
            f"{self._UNDERCLAIM_DOC}'s '{self._UNDERCLAIM_ANCHOR}' list omits "
            f"{missing}, which `ci_guard` DOES gate. An adopter reads that a PR "
            "touching one needs no marker, then the required check blocks the "
            "merge and the doc is what told them wrong. Name every member as a "
            "backticked token (a prefix may carry a `*`/`**` suffix).\n"
            f"Gated set derived just now: {list(members)}"
        )

    def test_no_doc_demands_the_marker_for_a_runtime_only_path(self):
        """The over-claim detector, over EVERY tracked `.md` — carriers included.

        Asks the real question rather than a proxy for it: does a marker-bearing
        paragraph name a path that `write_guard` protects at RUNTIME but
        `ci_guard` does NOT gate? That set is exactly the over-claim vocabulary,
        so one hit is enough — no threshold to tune, and no need for the
        "is this a contrast or a claim" judgement that made the previous
        exemption exempt the bug.
        """
        ci_guard = _load_ci_guard_module()
        zones = _load_protected_zones_module()
        marker = ci_guard.APPROVAL_MARKER
        runtime_only = runtime_only_paths(ci_guard, zones)
        # The renderer refuses to emit an empty stanza, but THIS arm calls the
        # derivation directly — without its own floor it would sweep 287 docs
        # matching nothing and pass. A floor that lives in a different arm is
        # not a floor on this one.
        assert runtime_only, (
            "runtime_only_paths() is empty, so this arm has no vocabulary and "
            "would pass vacuously over every doc in the repo."
        )

        offenders: list[str] = []
        for rel in _tracked("*.md", minimum=_TRACKED_MD_FLOOR):
            if rel.startswith("tests/") or rel in self._ENUMERATION_EXEMPT:
                continue
            path = REPO_ROOT / rel
            # Tracked but absent from the worktree (a plain `mv` before the
            # index catches up). Skipping is NOT the fail-open the seed arm
            # above forbids: there is no text here that could hide an
            # enumeration, and presence of the declared SoT docs is the seed
            # arm's job. Without this the widening detector raised FileNotFoundError
            # -- a red, but a crash-shaped one in the arm that did not own the
            # question, which is how a future session talks itself into
            # loosening the arm that did.
            if not path.is_file():
                continue
            text = _without_block(path.read_text(encoding="utf-8"))
            for para in marker_windows(text):
                if marker not in para:
                    continue
                named = overclaimed_tokens(para, ci_guard, zones)
                if named:
                    offenders.append(f"{rel}: names {named} beside {marker}")
                    break

        assert not offenders, (
            "doc(s) demand the approval marker for a path CI does NOT gate:\n  "
            + "\n  ".join(offenders)
            + f"\n\nRuntime-only paths, derived just now as write_guard's zone "
            f"minus ci_guard's: {list(runtime_only)}. Each is protected from "
            "LIVE edits and needs no PR marker, so naming one beside "
            f"{marker} tells a contributor to title a PR that would have merged "
            "untitled. If the doc means to CONTRAST the two zones, carry the "
            "generated block — its second stanza says exactly that, and the "
            "block span is stripped before this scan."
        )
