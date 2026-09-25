"""Unit tests for the de-provenance census SoT module + the ``espalier
provenance`` CLI exit contract.

The shipping-surface regression gate (does the live tree carry any tags?) lives
in tests/test_no_provenance_in_shipped_code.py; these cover the module internals
(the self-scan-exclusion trap, the report formatter) and the CLI's 0/2 exit
contract that /smoke relies on.
"""
from __future__ import annotations

# pytest-marker: default-unit  (fast module + CLI unit tests)

import argparse

from espalier import provenance_census
from espalier.cli import cmd_provenance


class TestProvenanceCensusModule:
    def test_census_module_is_self_excluded(self):
        # The SoT module embeds the vocabulary it polices (PROVENANCE_RE source +
        # _ALLOWED_HITS token data); it must exclude itself or it flags its own
        # allowlist. Regression guard for the self-scan trap.
        offenders = provenance_census.census_offenders()
        assert not [o for o in offenders if o[0] == "espalier/provenance_census.py"]

    def test_regex_catches_tags_not_benign_prose(self):
        rx = provenance_census.PROVENANCE_RE
        assert rx.search("guard (TP-243)")
        assert rx.search("round-7 review")
        assert rx.search("wf_6c5457")
        assert not rx.search("the STATUS code was 3 on retry")

    def test_format_offenders_empty_is_blank(self):
        assert provenance_census.format_offenders([]) == ""

    def test_format_offenders_reports_count_and_hint(self):
        out = provenance_census.format_offenders([("espalier/x.py", 5, "# TP-999 leak")])
        assert "1 internal build-history" in out
        assert "espalier/x.py:5" in out
        assert "_ALLOWED_HITS" in out

    def test_blind_asset_files_are_force_scanned(self):
        # C-1: two espalier/assets/ files have no scanned SoT (assets/CLAUDE.md is a
        # folder-router; assets/memory/README.md's SoT is itself excluded), so the
        # blanket assets/ exclusion would ship a leaked tag uncaught. They are
        # force-scanned instead of relying on a (nonexistent) byte-parity pin.
        scanned = set(provenance_census._shipping_surface_files(provenance_census._REPO_ROOT))
        assert "espalier/assets/CLAUDE.md" in scanned
        assert "espalier/assets/memory/README.md" in scanned

    def test_task_packs_router_asset_is_covered_by_exactly_one_scan_path(self):
        # TP-398 LANEA-02: the folder router ships to every adopter but was
        # scanned from NEITHER side -- the asset inherits the blanket
        # espalier/assets/ exclusion, and its byte-identical SoT sits under
        # the excluded "task-packs/" prefix (it classified local_only until
        # 2026-09-21; it is public now and excluded by prefix instead).
        # Exactly one side must be scanned: the asset (what actually ships).
        # Asserting BOTH halves so a later change on the SoT's side cannot
        # silently double-cover it.
        sot = "task-packs/CLAUDE.md"
        asset = "espalier/assets/task-packs/CLAUDE.md"
        assert provenance_census.path_is_scanned(asset) is True
        assert provenance_census.path_is_scanned(sot) is False

    def test_the_forward_work_tracker_is_excluded_as_a_whole(self):
        # 2026-09-21 (the ledger's DEC-13 row records the call): the tracked
        # task-packs/ set is public and MADE of pack ids, so the prefix is
        # excluded rather than each file allowlisted -- a new pack is covered
        # by construction. Pinned both ways: public per the classifier, and
        # still not scanned.
        from espalier.surface_contract import classify_release_path
        for rel in ("task-packs/FORWARD_LEDGER.md", "task-packs/TP-452-the-ledger-ships.md",
                    "task-packs/Deferred/TP-203a-learning-loop-finding-ledger.md"):
            assert classify_release_path(rel) == "public", rel
            assert provenance_census.path_is_scanned(rel) is False, rel

    def test_path_is_scanned_is_the_only_scan_decision(self):
        # The predicate and the census's own file walk must not drift apart:
        # two enumerations of "what the census covers" is the defect this
        # module's guard exists to catch, committed inside the guard.
        walked = set(
            provenance_census._shipping_surface_files(provenance_census._REPO_ROOT)
        )
        assert walked, "no shipping-surface files found -- walk is broken"
        assert all(provenance_census.path_is_scanned(rel) for rel in walked)

    def test_is_allowed_is_per_token_not_per_line(self):
        # C-2: an allowlisted token (TP-79 on write_guard.py) is permitted, but a
        # SECOND leaked tag on the SAME line is not whitewashed by the first.
        rel = "tools/cc/hooks/write_guard.py"
        assert provenance_census._is_allowed(rel, "# pinned on TP-79 head") is True
        assert provenance_census._is_allowed(rel, "# pinned on TP-79 + round-9 leak") is False
        # A file with no allowlist entry is never allowed on a hit.
        assert provenance_census._is_allowed("espalier/other.py", "# TP-79 here") is False


class TestProvenanceCLI:
    def test_clean_exits_0(self, monkeypatch):
        monkeypatch.setattr(provenance_census, "census_offenders", lambda _root: [])
        assert cmd_provenance(argparse.Namespace(repo=".")) == 0

    def test_offenders_exit_2(self, monkeypatch, capsys):
        monkeypatch.setattr(
            provenance_census,
            "census_offenders",
            lambda _root: [("espalier/foo.py", 1, "# TP-999 leaked tag")],
        )
        rc = cmd_provenance(argparse.Namespace(repo="."))
        assert rc == 2
        assert "espalier/foo.py:1" in capsys.readouterr().err
