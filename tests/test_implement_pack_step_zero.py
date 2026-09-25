"""TP-62 + TP-107: pack-artifact review + scope/compression pre-flight pins.

Tests verify the testable surfaces of /implement-pack's pre-flight gates:
- Checklist file exists at the expected path and is versioned (TP-62).
- Slash-command body contains the step 0-A instruction (TP-62).
- Slash-command body contains step 0-B + 0-C instructions (TP-107).
- Step 0-B/0-C presence holds across all 3 mirror copies (runtime,
  asset SoT, dogfooding) so a future edit cannot silently delete the
  pre-flight wiring from all three in lockstep and still pass
  byte-parity tests.
- Shipped asset matches the local copy.

The agent dispatch itself is Claude-Code-runtime; not testable in
pytest. The false-negative regression class below documents the
manual smoke procedure operators run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
CHECKLIST = REPO / "tools" / "cc" / "pack_artifact_checklist.md"


def _checklist_item_bodies(path: Path) -> list[str]:
    """Full item blocks (title + elaboration), whitespace-normalised.

    Deliberately an INDEPENDENT oracle. The companion test compares the command
    body against ``scripts/sync_checklist_regions.py``'s own render, which proves the
    region is in sync but cannot prove the render is right -- the same code sits
    on both sides of the equals sign (``docs/sharp-edges/
    closed-loop-verification-trap.md``). This re-slices the source with its own
    logic, and normalises whitespace so the five-space indent the command body
    adds is not mistaken for a content difference.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("1. "))
    end = next(
        i for i, ln in enumerate(lines) if ln.startswith("Output format per item:")
    )
    items: list[str] = []
    current: list[str] = []
    for ln in lines[start:end]:
        if re.match(r"^\d+\.\s", ln):
            if current:
                items.append(" ".join(" ".join(current).split()))
            current = [ln]
        elif ln.strip():
            current.append(ln)
    if current:
        items.append(" ".join(" ".join(current).split()))
    return items


def _load_sync_script():
    """Load ``scripts/sync_checklist_regions.py`` by path.

    ``scripts/`` is not a package, so a plain import would depend on cwd.
    """
    import importlib.util

    path = REPO / "scripts" / "sync_checklist_regions.py"
    spec = importlib.util.spec_from_file_location("sync_checklist_regions", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMMAND = REPO / ".claude" / "commands" / "implement-pack.md"
SHIPPED = REPO / "espalier" / "assets" / "claude" / "commands" / "implement-pack.md"
DOGFOODING = REPO / "examples" / "dogfooding" / ".claude" / "commands" / "implement-pack.md"

# Three-way mirror set for cross-parity presence checks.
ALL_MIRRORS = (COMMAND, SHIPPED, DOGFOODING)


class TestPackArtifactReviewSurface:
    def test_checklist_file_exists(self):
        assert CHECKLIST.is_file(), f"missing checklist at {CHECKLIST}"

    def test_checklist_carries_version_header(self):
        body = CHECKLIST.read_text(encoding="utf-8")
        assert "TP-62 v2" in body, "checklist must declare its version"

    def test_step_0a_in_command_body(self):
        body = COMMAND.read_text(encoding="utf-8")
        assert "0-A" in body, "/implement-pack must reference step 0-A"
        assert "code-reviewer" in body.lower(), (
            "step 0-A must name the code-reviewer agent"
        )

    def test_checklist_inlined_into_command_body(self):
        # TP-189 ARCH-1: the checklist is INLINED into the command body (it
        # used to instruct "read tools/cc/pack_artifact_checklist.md" -- a
        # dangling ref for adopters who never receive that file). TP-210: the
        # version label was de-provenanced when implement-pack.md was promoted
        # to the common tier, where TestCommonTierAssetHygiene forbids pack IDs.
        #
        # This assertion used to compare each item's leading TITLE only, and its
        # own docstring said so. Under that guard the two copies of item 9 drifted
        # and read green for the whole of their life, and replacing an item's
        # entire elaboration with nonsense left the full suite green -- measured,
        # not supposed. It now compares each item's FULL text.
        raw = COMMAND.read_text(encoding="utf-8")
        body = " ".join(raw.split())
        assert "Pack-artifact review checklist v2" in raw, (
            "inlined checklist must carry its version label"
        )
        items = _checklist_item_bodies(CHECKLIST)
        assert len(items) == 9, f"expected 9 pack-artifact items, found {len(items)}"
        for item in items:
            assert item in body, (
                "checklist item text is in the canonical file but not inlined "
                "into the command body (drift). Run "
                "`python3 scripts/sync_checklist_regions.py`.\n"
                f"  missing: {item[:120]}..."
            )

    def test_inlined_checklist_is_generated_from_source(self):
        """The inlined region equals what the sync script renders from the SoT.

        The companion assertion above re-slices the source with its own logic, so
        a bug in the script's extraction surfaces as a disagreement between the
        two rather than as a blind spot shared by both.
        """
        sync = _load_sync_script()
        region = next(r for r in sync.REGIONS if r.name == "pack-artifact-checklist")
        rendered = sync.render(
            region, sync.extract_items(region, CHECKLIST.read_text(encoding="utf-8"))
        )
        _, current = sync.splice(region, COMMAND.read_text(encoding="utf-8"), rendered)
        assert current == rendered, (
            "the generated checklist region is out of sync with "
            f"{CHECKLIST.relative_to(REPO)} -- run "
            "`python3 scripts/sync_checklist_regions.py`"
        )

    def test_generated_region_stays_nested_inside_the_step_0a_bullet(self):
        """The transform itself, pinned from the FILE rather than the constant.

        Neither companion assertion can see the indent: the round-trip one calls
        ``render()`` for its expected value, so the constant sits on both sides of
        the ``==``; the independent one normalises whitespace precisely so indent
        is not a content difference. Measured by substituting the constant --
        at 0, 5 and 17 spaces BOTH passed.

        The indent is not cosmetic. At 0 the items become a top-level ordered
        list, which terminates step 0-A's bullet block and changes the structure
        of the prompt the reviewing agent is handed.

        Read from disk on purpose -- importing ``sync._INDENT`` here would rebuild
        the closed loop this test exists to break.
        """
        raw = COMMAND.read_text(encoding="utf-8").split("\n")
        b = next(i for i, ln in enumerate(raw) if "pack-artifact-checklist: BEGIN" in ln)
        e = next(i for i, ln in enumerate(raw[b + 1:], b + 1)
                 if "pack-artifact-checklist: END" in ln)
        body = [ln for ln in raw[b + 1:e] if ln.strip()]
        assert body, "the generated region is empty"
        # The MINIMUM indent, not a per-line pattern: item lines sit at 5 and their
        # continuations at 8, so `^ {5}\S` would reject every continuation, while a
        # bare `startswith("     ")` cannot tell 5 from 17. The floor distinguishes
        # all three of the values measured as passing before this test existed.
        base = min(len(ln) - len(ln.lstrip()) for ln in body)
        assert base == 5, (
            f"the generated region's base indent is {base}, expected 5. The items "
            "must stay NESTED inside step 0-A's bullet; at 0 they become a sibling "
            "top-level list and terminate the block, changing the structure of the "
            "prompt the reviewing agent is handed."
        )

    def test_sync_rejects_a_duplicated_generated_region(self):
        """Both the writer and its pinning test read only the FIRST marker pair,
        so a second region would be regenerated by neither and checked by
        neither -- stale forever, with the suite green."""
        sync = _load_sync_script()
        region = next(r for r in sync.REGIONS if r.name == "pack-artifact-checklist")
        doubled = COMMAND.read_text(encoding="utf-8")
        doubled += ("\n" + region.begin_marker + "\n     1. x\n     "
                    + region.end_marker + "\n")
        with pytest.raises(ValueError, match="more than one"):
            sync.splice(region, doubled, "     1. x")

    def test_sync_refuses_to_ship_a_pack_id_into_the_common_tier(self):
        """A digit-bearing pack id in an ITEM must fail at the sync, not later.

        The command body is common-tier; a leaked ``TP-NN`` with digits reds
        TestCommonTierAssetHygiene with a message pointing at the generated copy
        rather than at the source that produced it.
        """
        sync = _load_sync_script()
        region = next(r for r in sync.REGIONS if r.name == "pack-artifact-checklist")
        poisoned = CHECKLIST.read_text(encoding="utf-8").replace(
            "1. Line-number accuracy.", "1. Line-number accuracy (per TP-62).", 1
        )
        with pytest.raises(ValueError, match="TP-62"):
            sync.extract_items(region, poisoned)

    def test_shipped_asset_matches_local(self):
        local = COMMAND.read_text(encoding="utf-8")
        shipped = SHIPPED.read_text(encoding="utf-8")
        assert local == shipped, (
            "shipped asset must match local copy in the step 0-A region"
        )

    @pytest.mark.parametrize("mirror", ALL_MIRRORS, ids=lambda p: p.parent.parent.name)
    def test_step_0b_in_command_body(self, mirror):
        """Step 0-B (scope-check) must remain wired in every mirror.

        Without this assertion a future edit could remove the 0-B block
        from all three mirrors in lockstep, and the byte-parity tests
        would still pass because parity says nothing about content.
        """
        body = mirror.read_text(encoding="utf-8")
        assert "0-B" in body, f"{mirror.name} missing 0-B section"
        assert "scope-check" in body, (
            f"{mirror} step 0-B must mention scope-check"
        )
        assert "--accept-scope-gap" in body, (
            f"{mirror} step 0-B must document the --accept-scope-gap override"
        )

    @pytest.mark.parametrize("mirror", ALL_MIRRORS, ids=lambda p: p.parent.parent.name)
    def test_step_0c_in_command_body(self, mirror):
        """Step 0-C (compression probe) must remain wired in every mirror.

        Same lockstep-parity hazard as 0-B: byte-parity does not detect
        a coordinated removal across all three mirrors.
        """
        body = mirror.read_text(encoding="utf-8")
        assert "0-C" in body, f"{mirror.name} missing 0-C section"
        assert "sister_site_probe.py" in body, (
            f"{mirror} step 0-C must invoke sister_site_probe.py"
        )
        assert "--accept-compression-debt" in body, (
            f"{mirror} step 0-C must document --accept-compression-debt override"
        )


class TestFalseNegativeRegression:
    """The smoke test the operator runs manually to verify the gate
    detects real errors. See docs/CONVENTIONS.md TP-62 section.

    Fixture: a tmp pack containing a known WRONG (e.g., line number
    that doesn't exist in any real file, symbol name that doesn't
    exist). Manual smoke procedure:

    1. Author the fixture pack with the planted error.
    2. Invoke `/implement-pack <fixture-path>`.
    3. Verify step 0-A surfaces the WRONG finding.
    4. Verify execution stops at step 0-A (does not proceed to 0-B
       scope-check or sub-task 1-A).

    This is documented as manual smoke because the dispatch happens
    at Claude runtime; pytest cannot exercise it. If a future
    revision wires a subprocess-callable shim around the dispatch,
    this test class becomes the automated regression target.
    """

    def test_smoke_fixture_documented(self):
        """Asserts the manual smoke procedure is documented."""
        conventions = (REPO / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")
        assert "false-negative regression" in conventions.lower(), (
            "CONVENTIONS.md must document the manual smoke procedure"
        )



def _probe_blocking_labels() -> tuple[str, ...]:
    """``sister_site_probe.BLOCKING_LABELS`` via the file, not a package import
    (tools/cc modules keep a zero-espalier import graph)."""
    import importlib.util

    path = REPO / "tools" / "cc" / "sister_site_probe.py"
    spec = importlib.util.spec_from_file_location("_ssp_for_step_zero", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return tuple(mod.BLOCKING_LABELS)


class TestStepZeroCNamesEveryBlockingKind:
    """DEF-673 failure-mode pass: the 0-C exit table said ``0 = no 3+ identical
    cliques`` while ``_blocking_items`` also gates on identical CONSTANT
    cliques, so an adopter whose only debt was a constant clique could not map
    rc=2 to any listed cause. The kinds are derived from the probe's own
    tuple, so a fifth blocking kind reds this test until the body names it."""

    @pytest.mark.parametrize("mirror", ALL_MIRRORS, ids=lambda p: p.parent.parent.name)
    def test_every_blocking_kind_is_named_in_the_exit_table(self, mirror):
        # Slice the 0-C block, so a label named only in a prose aside or a
        # negative sentence elsewhere in the file cannot satisfy this (the
        # first cut matched the whole file and passed a "does not gate on
        # identical constant cliques" mutant). Wrapped at ~72 columns, so a
        # label can straddle a line break: collapse whitespace.
        raw = mirror.read_text(encoding="utf-8")
        start, end = raw.index("0-C."), raw.index("0-D.")
        block = " ".join(raw[start:end].lower().split())
        assert "exit code semantics" in block, f"{mirror}: the 0-C exit table anchor moved"
        body = block[block.index("exit code semantics"):]
        labels = _probe_blocking_labels()
        assert len(labels) >= 4, "BLOCKING_LABELS collapsed"
        missing = [label for label in labels if label.lower() not in body]
        assert not missing, (
            f"{mirror} step 0-C does not name blocking kind(s) {missing}; the "
            f"probe gates on them (sister_site_probe.BLOCKING_LABELS)."
        )
