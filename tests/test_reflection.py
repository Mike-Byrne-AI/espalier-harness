"""Tests for ``espalier.reflection`` — ``reflect_repo`` and
``render_reflection_report``, the unstructured-reflection counterpart
to ``reflect_protocol`` that consumes ``reports/*.json`` artifacts.

Pins the JSON loader's tolerance for the ``espalier:managed`` marker
on top of the JSON body, and its refusal to load non-object JSON
(arrays at root, invalid syntax). Without this guard a regression
in ``_load_json`` could silently mask broken reports/* files — the
reflect report would render with empty sections instead of surfacing
the load failure to the operator.
"""
from __future__ import annotations

import json
from pathlib import Path

from espalier.reflect_protocol import _text_without_fences

from espalier.reflection import (
    _load_json,
    _normalize_link,
    reflect_repo,
    render_reflection_report,
)

# full-tree-exempt: the one live-tree walk here (reflect_repo on the repo root
# in TestReflectScanScope) derives its population from the tree it runs on.
# The row was registered in tests/conftest.py::_FULL_TREE_NODEIDS as one of the
# seven @requires_self_host seeds; measured on a DEF-670-seeded release export
# under ESPALIER_FULL_TREE_AUDIT=1 (2026-09-23, TP-455 1-G) it walks the shipped
# docs and reports zero broken links, so it runs on an export and the entry left.
# This marker exempts the MODULE: a new pruned-path read anywhere in this file
# gets no detector signal, only the chain-count pin in
# tests/test_test_suite_contract.py (measured 1 here).


# ─── _load_json ──────────────────────────────────────────────────────────────

class TestLoadJson:
    def test_loads_plain_json_object(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}\n', encoding="utf-8")
        result = _load_json(f)
        assert result == {"key": "value"}

    def test_strips_managed_marker_line(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('# espalier:managed\n{"key": "value"}\n', encoding="utf-8")
        result = _load_json(f)
        assert result == {"key": "value"}

    def test_non_dict_json_degrades_to_empty(self, tmp_path):
        """TP-174a: Class-B parity — a valid-JSON-but-non-dict report degrades
        to {} (matching diffing/handoff) instead of crashing `espalier reflect`."""
        f = tmp_path / "data.json"
        f.write_text("[1, 2, 3]\n", encoding="utf-8")
        assert _load_json(f) == {}

    def test_degrades_on_invalid_json(self, tmp_path):
        # TP-204a: _load_json now routes through the guarded _report_io owner,
        # so malformed JSON degrades to {} instead of tracebacking `reflect`.
        f = tmp_path / "data.json"
        f.write_text("not json\n", encoding="utf-8")
        assert _load_json(f) == {}


# ─── _normalize_link ─────────────────────────────────────────────────────────

class TestNormalizeLink:
    def test_resolves_relative_link(self, tmp_path):
        base = tmp_path / "docs" / "guide.md"
        base.parent.mkdir(parents=True)
        result = _normalize_link(base, "setup.md", tmp_path)
        assert result == (tmp_path / "docs" / "setup.md").resolve()

    def test_resolves_absolute_link(self, tmp_path):
        base = tmp_path / "docs" / "guide.md"
        base.parent.mkdir(parents=True)
        result = _normalize_link(base, "/README.md", tmp_path)
        assert result == tmp_path / "README.md"

    def test_strips_anchor_fragment(self, tmp_path):
        base = tmp_path / "README.md"
        result = _normalize_link(base, "CONTRIBUTING.md#section", tmp_path)
        assert "#" not in str(result)


# ─── _text_without_fences (TP-204h: single-owned in reflect_protocol; the
#     strip_html_comments=True path is reflection.py's former _text_without_fenced_blocks)

class TestTextWithoutFencedBlocks:
    def test_removes_code_block_content(self):
        text = "Before\n```\ncode here\n```\nAfter\n"
        result = _text_without_fences(text, strip_html_comments=True)
        assert "code here" not in result
        assert "Before" in result
        assert "After" in result

    def test_preserves_text_outside_fences(self):
        text = "Normal text\n\nMore text\n"
        result = _text_without_fences(text, strip_html_comments=True)
        assert "Normal text" in result
        assert "More text" in result

    def test_handles_empty_string(self):
        result = _text_without_fences("", strip_html_comments=True)
        assert result == ""

    def test_handles_text_with_no_fences(self):
        text = "Just some text without fences."
        result = _text_without_fences(text, strip_html_comments=True)
        assert "Just some text without fences." in result


# ─── reflect_repo ────────────────────────────────────────────────────────────

class TestReflectRepo:
    def test_returns_dict_with_required_keys(self, tmp_path):
        result = reflect_repo(tmp_path)
        assert "repo_root" in result
        assert "plan_missing_docs" in result
        assert "manifest_missing_docs" in result
        assert "broken_markdown_links" in result
        assert "recommended_actions" in result

    def test_empty_repo_has_no_gaps(self, tmp_path):
        result = reflect_repo(tmp_path)
        assert result["plan_missing_docs"] == []
        assert result["manifest_missing_docs"] == []

    def test_repo_root_is_string(self, tmp_path):
        result = reflect_repo(tmp_path)
        assert isinstance(result["repo_root"], str)

    def test_non_utf8_manifest_does_not_crash(self, tmp_path):
        # F5 (CV2): reflect_repo runs inside run_doctor_check; a non-UTF-8 manifest
        # (or public .md) must not raise UnicodeDecodeError and bypass doctor's honest
        # "N unreadable" framing — it must degrade (errors=replace) and complete.
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_bytes(b"cc/x.md\n\xff\xfe not utf-8 \xe9\n")
        (tmp_path / "BADENC.md").write_bytes(b"# Title \xff\xfe\n[link](missing.md)\n")
        result = reflect_repo(tmp_path)  # must not raise
        assert isinstance(result, dict)
        assert "manifest_missing_docs" in result

    def test_detects_plan_missing_docs(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        harness_config = {
            "generated_docs": ["cc/COMMANDS.md", "cc/LIVE_SURFACE.md"],
        }
        (reports_dir / "harness_config.json").write_text(
            json.dumps(harness_config), encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert "cc/COMMANDS.md" in result["plan_missing_docs"]
        assert "cc/LIVE_SURFACE.md" in result["plan_missing_docs"]

    def test_plan_doc_present_on_disk_not_flagged(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        (cc_dir / "COMMANDS.md").write_text("# Commands\n", encoding="utf-8")
        harness_config = {"generated_docs": ["cc/COMMANDS.md"]}
        (reports_dir / "harness_config.json").write_text(
            json.dumps(harness_config), encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert "cc/COMMANDS.md" not in result["plan_missing_docs"]

    def test_detects_manifest_missing_files(self, tmp_path):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        (cc_dir / "PACK_MANIFEST.txt").write_text(
            "nonexistent/file.md\n", encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert "nonexistent/file.md" in result["manifest_missing_docs"]

    def test_manifest_comment_lines_ignored(self, tmp_path):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        (cc_dir / "PACK_MANIFEST.txt").write_text(
            "# This is a comment\n<!--also ignored-->\n", encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert result["manifest_missing_docs"] == []

    def test_detects_broken_markdown_link(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "See [guide](nonexistent-doc.md) for details.\n", encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert len(result["broken_markdown_links"]) > 0
        link_targets = [item["target"] for item in result["broken_markdown_links"]]
        assert "nonexistent-doc.md" in link_targets

    def test_broken_link_file_field_is_posix_normalized(self, tmp_path):
        """The broken-link ``file`` field is emitted via ``.as_posix()`` so it
        carries forward slashes on every OS (matches the sibling normalizer at
        reflection.py:33 and the repo's path-comparison Architecture Rule).

        Earn-the-red note ([[earn-the-red-has-a-platform-ceiling]]): on POSIX
        ``str(PurePosixPath("sub/dir/x.md"))`` already yields forward slashes,
        so this CANNOT go RED on Darwin/Linux — it locks the contract
        version-agnostically. The backslash-on-Windows magnitude it guards
        against is unverified-on-host.
        """
        nested = tmp_path / "sub" / "dir"
        nested.mkdir(parents=True)
        (nested / "x.md").write_text(
            "See [guide](nonexistent-doc.md) for details.\n", encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        files = {item["file"] for item in result["broken_markdown_links"]}
        assert "sub/dir/x.md" in files
        assert not any("\\" in f for f in files)

    def test_valid_local_link_not_flagged(self, tmp_path):
        (tmp_path / "setup.md").write_text("# Setup\n", encoding="utf-8")
        (tmp_path / "README.md").write_text(
            "See [setup](setup.md) for details.\n", encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert not any(
            item["target"] == "setup.md" for item in result["broken_markdown_links"]
        )

    def test_link_inside_fenced_block_not_flagged(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "Example:\n```\n[broken](definitely-missing.md)\n```\nEnd.\n",
            encoding="utf-8",
        )
        result = reflect_repo(tmp_path)
        assert not any(
            item["target"] == "definitely-missing.md"
            for item in result["broken_markdown_links"]
        )

    def test_recommended_actions_always_present(self, tmp_path):
        result = reflect_repo(tmp_path)
        assert len(result["recommended_actions"]) > 0

    def test_missing_connections_populated_when_plan_drifts(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["missing.md"]}), encoding="utf-8"
        )
        result = reflect_repo(tmp_path)
        assert len(result["missing_connections"]) > 0


# ─── render_reflection_report ────────────────────────────────────────────────

class TestRenderReflectionReport:
    def test_output_contains_header(self, tmp_path):
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "REFLECTION" in output

    def test_output_shows_plan_gap_count(self, tmp_path):
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "Plan gaps:" in output

    def test_output_shows_manifest_gap_count(self, tmp_path):
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "Manifest gaps:" in output

    def test_output_shows_broken_link_count(self, tmp_path):
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "Broken markdown links:" in output

    def test_output_lists_broken_links(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "See [missing](ghost.md)\n", encoding="utf-8"
        )
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "ghost.md" in output

    def test_output_lists_plan_missing_docs(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["cc/MISSING.md"]}), encoding="utf-8"
        )
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "cc/MISSING.md" in output

    def test_output_ends_with_newline(self, tmp_path):
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert output.endswith("\n")

    def test_recommended_actions_in_output(self, tmp_path):
        report = reflect_repo(tmp_path)
        output = render_reflection_report(report)
        assert "Recommended actions:" in output


# ─── TP-184: reflect scan scope (broken_links doctor-WARN fix) ────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]


class TestReflectScanScope:
    """The `espalier doctor` reflect WARN was driven by reflect_repo's bare
    rglob("*.md") scanning build artifacts (dist/), gitignored scratch
    (task-packs/, session-archive.md), and mis-parsing doc placeholders. These
    pin the fix: scan only the navigable PUBLIC doc surface, skip dir-links and
    angle-bracket/ellipsis placeholders — WITHOUT masking a genuine broken link.
    """

    def test_transient_and_internal_dirs_excluded(self, tmp_path):
        # A would-be-flagged broken file link planted in a build artifact
        # (transient) and gitignored scratch (internal) must NOT be scanned...
        (tmp_path / "dist" / "x").mkdir(parents=True)
        (tmp_path / "dist" / "x" / "README.md").write_text(
            "[gone](missing.md)\n", encoding="utf-8")
        (tmp_path / "task-packs").mkdir()
        (tmp_path / "task-packs" / "TP-99.md").write_text(
            "[gone](missing.md)\n", encoding="utf-8")
        # ...while the same broken link in a PUBLIC doc still is.
        (tmp_path / "README.md").write_text(
            "[gone](missing.md)\n", encoding="utf-8")
        result = reflect_repo(tmp_path)
        files = {item["file"] for item in result["broken_markdown_links"]}
        assert "README.md" in files, "public-doc broken link not caught"
        assert not any(f.startswith("dist/") for f in files), "dist/ scanned"
        assert not any(f.startswith("task-packs/") for f in files), "scratch scanned"

    def test_directory_link_not_flagged(self, tmp_path):
        # A directory link (trailing /) is structural / valid-when-deployed
        # (a template's `[memory/](memory/)`), not a broken FILE link.
        (tmp_path / "README.md").write_text(
            "See [`memory/`](memory/) for notes.\n", encoding="utf-8")
        result = reflect_repo(tmp_path)
        assert not any(
            item["target"] == "memory/"
            for item in result["broken_markdown_links"]
        )

    def test_placeholder_links_not_flagged(self, tmp_path):
        # Angle-bracket placeholder (template/format example) + bare ellipsis
        # target are documentation OF the link shape, not navigable links.
        (tmp_path / "README.md").write_text(
            "Format: [memory/<slug>.md](...) and [x](...).\n", encoding="utf-8")
        result = reflect_repo(tmp_path)
        assert result["broken_markdown_links"] == []

    def test_real_broken_file_link_still_flagged(self, tmp_path):
        # FALSE-NEGATIVE guard: the skips above must NOT mask an ordinary
        # broken file link in a public doc.
        (tmp_path / "README.md").write_text(
            "Real broken: [setup](setup.md).\n", encoding="utf-8")
        result = reflect_repo(tmp_path)
        assert any(
            item["target"] == "setup.md"
            for item in result["broken_markdown_links"]
        ), "a genuine broken file link was wrongly skipped"

    def test_live_repo_has_no_broken_links(self):
        # Earn-the-red / durable gate: after the scope fix the live repo's
        # navigable docs have ZERO broken links, so `espalier doctor`'s reflect
        # WARN stays clear (this test fails the moment a real broken link lands).
        links = reflect_repo(_REPO_ROOT)["broken_markdown_links"]
        assert links == [], (
            "reflect_repo found broken markdown links in tracked docs:\n  "
            + "\n  ".join(f"{l['file']} -> {l['target']}" for l in links)
        )
